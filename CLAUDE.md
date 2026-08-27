# claudeops — Claude Context

Açık Claude CLI session'larını toplu yönet. **`py/cops`** = canlı Python tool; **`./claudeops`** (bash) = layout + eski komutlar.

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. Aynı sid resume → cache'li, değiştirmek için `--new`.
- **xdotool**: `windowmove` → **`--sync` YOK** (hang).
- **claude 2.1.169**: fresh `--new` session'lar `sessions/<pid>.json` yazmıyor → keşif proc-scan'le. [[claude-2169-session-detection]]
- **claude 2.1.183 KILL=TRUNCATE**: lazy-checkpoint storage; kill'de flush için zaman gerek → **hep SIGTERM + ~8-10s bekle, sadece canlıysa SIGKILL**. Ani kapanma/sert-OOM = son mesajlar gider (iş git'te güvende, sadece transkript). [[claude-2183-conversation-truncation]] [[reboot-recovery]]
- **1M context**: `[1m]` suffix → beta header; şu an KAPALI (token kısıtı). [[model-1m-context]]
- **spawn env-leak**: claude session'ı kendi Bash tool'undan spawn tetiklerse `CLAUDE_CODE_CHILD_SESSION` sızar → yeni session transcript kaydını sessizce kapatır. `spawn.py` `CLAUDE*` env'i filtreliyor (2026-08-24). [[spawn-env-leak-disables-transcript]]
- **spawn zombie-child**: gnome-terminal client'ı reap edilmezse uzun yaşayan `py/cops web`'de zombie birikir → spawn sessizce güvenilmezleşir. Fix: daemon thread'de `.wait()` (global SIGCHLD=SIG_IGN YAPMA — layout'un subprocess.run'ını bozar). Fallback: kısa-ömürlü CLI'dan spawn hep güvenilir. [[spawn-zombie-child-degrades-web-server]]
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Roster / model (`~/.claude/claudeops/{roster,models}.tsv` — repo DIŞI, kaynak-of-truth)

- Tüm isimler **`claude-sonnet-5`** (2026-08-24 Claude 5 geçişi; opus split geri alındı — istenirse `sed -i 's/claude-sonnet-5/claude-opus-5/'` ile grup bazında geri, önce tek isimle test; TOBEDECIDED Kapatılmış #7).
- **İsimler base-name** (suffix yok, 2026-06-26). `Session.base` tarih+`_N` suffix'lerini indirger: `cops20260824_1`→`cops` (2026-08-25). Panel eşlemesi önce TAM isim, sonra base (2026-08-26) — tarih-isimli satırlar kendi satırında görünür, görünmez canlı proc imkansız.
- **co + cops** (self) + **ulaksec** aktif (guard ayakta tutsun). **HO_EXCLUDE isim-listesi KALDIRILDI (2026-08-25)** — toplu işlem hedefi panel checkbox'larıyla; tek koruma process-bazlı self-koruma (`ancestor_pids()` py handover+rc; bash `filter_not_self`). ulaksec'i artık sadece dikkat koruyor. [[co-ulaksec-guard-yes-ho-no]]
- Kapalı/emekli satırlar `#`'lı. `py/cops close <name>` = kill + models.tsv yorumla; geri: panel "tekrar işe al". **Temizlik bekliyor:** tarih-isimli çöp satırlar (rustrino*/line*/trino*/sase* tarihli) — kullanıcıya sorup birleştir/sil.
- roster.tsv'nin opsiyonel **4. kolonu = `cli`** (`claude`|`agy`, yoksa/eskiyse `"claude"`) — hangi provider'ın açtığı (bkz. yukarıdaki çoklu-CLI notu).

## Fleet kontrolü — MANUEL (2026-08-24 karar)

- **Guard cron KASITLI kapalı** (crontab'da 3 satır `#`'lı). Kullanıcı web'den tek tek yönetiyor — **sen açma**, sormadan toplu spawn YAPMA. [[feedback-manual-fleet-control]]
- **`py/cops web [--port 8765] [--tunnel]`** — TAB'lı panel (Çalışanlar / Kayıtlı / Devre dışı / Emekli / Layout, 2026-08-25 revizyonu): satır checkbox'ları + toplu işlemler (handover/durdur/devre dışı bırak/emekli et), **ho?** kolonu + "needs-ho seç", satır-içi başlat seçenekleri, kayıtsızlara "devral", "+ yeni proje kaydet" formu Kayıtlı sekmesinde. UI "devre dışı bırak" = API/CLI `close`. Layout sekmesi kilitli-ekran pre-flight'lı. Token-gated; `--tunnel` = cloudflared. Detay: `py/README*.md`.
- **Repo PUBLIC** (MIT, github + gitlab mirror) — roster/models/token repo dışında. Kullanıcı: "dünyaya açığız, DONE/TODO/changelog önemli" → kayıtları özenli tut.
- Web Stop / `py/cops kill` / `rc --kill-first` parent bash'i de öldürür (`kill_session_and_parent`) — tmux-backed session'da bunun yerine ad-bazlı `tmux kill-session` (aşağıya bkz, parent PID tüm filoyu paylaşan tmux server olabilir).
- **Web'den canlı terminal (2026-08-27, TBD#11 kapandı):** yeni spawn'lar tmux-backed (`tmux -L cops`, `py/claudeops/tmux_backend.py` + bundled `data/tmux.conf`) — panelde "Terminal" butonu → `/api/term/output` (200ms poll, capture-pane) + `/api/term/input` (send-keys) + `/api/term/key` (Ctrl-C/Esc/oklar) → xterm.js render (ilk kullanımda lazy-indirilir, offline'da düz-metin fallback). Eski/bare session'lar tmux'a taşınmaz, sadece bir sonraki respawn'da geçer. `tmux.conf`'ta `focus-events on` ŞART (yoksa `--remote-control` session'larına girdi ekranda hiç görünmez — Claude'un kendi TUI'si bunu ipucu olarak basar).
- **Çoklu-CLI (claude + agy) — provider mimarisi (2026-08-27, TBD#10 kapandı):** `py/claudeops/providers/` (`base.py` ABC + `claude_provider.py` + `agy_provider.py` + registry `get_provider(cli)`) — `spawn.py`/`discovery.py`/`commands/web.py` `cli` string'ine göre HİÇ dallanmaz, sadece arayüz üzerinden çağırır (3. bir CLI = yeni provider dosyası + registry satırı). agy'nin `--remote-control` muadili yok → isimlendirme `COPS_NAME` env; **komut satırına `env COPS_NAME=... <binary>` olarak GÖMÜLÜR, Popen'ın env dict'ine DEĞİL** — tmux zaten çalışan bir server'da yeni session açarken kendi `update-environment` listesi (DISPLAY, SSH_AUTH_SOCK, ...) DIŞINDAKİ her şeyi sessizce yok sayıyor, canlı doğrulandı. COPS_NAME'siz bare agy → `agy-<pid>` placeholder, kayıtsız/adopt edilebilir. agy model listesi CANLI çekilir (`agy models`, 300s TTL) — sabit değil, 2 günde bir değişti.

## Handover (3-fazlı)

- **Faz 1:** `py/cops handover [--dry-run]` — batch'li (mass aynı anda = rate-limit → blank-TUI [[mass-faz1-ratelimit-stuck]]); self (komutun atası) otomatik atlanır.
- **Faz 2:** Faz1 sağlıksızsa (503/529) DUR, kullanıcı onayı şart. `py/cops rc <isimler SPACE'li> --new --kill-first --model='claude-sonnet-5' --permission-mode=auto --effort=max --one-by-one` (bash rc DEĞİL — py cwd'yi roster'dan alır). `--prompt` VERME (boş başlasınlar [[faz2-new-session-devam]]). Config doğrula: `python3 -c "import json;json.load(open('$HOME/.claude.json'))"`. Bridge rate-limit: 4'er batch + 20s [[bridge-batch-spawn-ratelimit]].
- **Faz 3:** ÖNCE `loginctl show-session <id> -p LockedHint`=no doğrula [[layout-needs-unlocked-screen]]. `./claudeops layout grid 4 --claude-only --pin=... --group=...` — 2× çalıştır, `xwininfo` ile doğrula (wmctrl 2× yalan). `[1m]` tek tırnak; target SPACE-separated.
- **Skip kriteri:** RFH var + sonrasında yeni istek yok + repo temiz+pushed (github+gitlab).
- Detay: [[handover-procedure]] [[handover-edge-cases]] [[feedback-ho-stop-on-error]] [[config-corruption-resume-hang]]

## Sınırlamalar / açık bug'lar

Wayland: layout çalışmaz. gnome-terminal hard-coded. `rc --kill-first` permission modal keser. Target virgül parse yok (SPACE). Tam liste: TODO.md. TOBEDECIDED #10+#11 UYGULANDI (2026-08-27) — açık kalan tasarım sorusu yok, sadece küçük TODO kalemleri (rename UI, agy Faz-3 handover/RFH, panelde dile-göre handover metni copy-paste).

## Meta

`DONE.md` = CHANGELOG. Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
Ho-prep sync (her ho'da): TODO done → DONE; TOBEDECIDED karar → TODO.

## READY FOR HANDOVER (2026-08-27, güncellendi — TBD#10+#11 uygulandı, commit+push YAPILDI)

**DURUM:** Fleet manuel kontrolde (guard cron kasıtlı kapalı). Panel (8765) + cloudflared tüneli ayakta. Roster: 20 aktif (8 çalışıyor / 12 kayıtlı-durmuş) / 30 devre dışı / 8 emekli; config VALID, DUP yok. Çalışanlar: `cops20260827` (bu session), `hc20260827`, `line`, `mo20260827` (**agy**, `gemini-3.1-pro-high`), `rustrino20260827_1`, `saseimpl`, `saseppr`, `trino` — hepsi `ho!` (henüz handover almadı, beklenen: hepsi bu session'ın kendisi tarafından yapılan işi konuşuyor). **Repo temiz, HEAD = `ebf1f45`, github+gitlab ikisi de senkron.**

**Bu session'da yapılanlar (25-27 Ağu, hepsi commit+push'lu, DONE.md'de detay):**
1. **TBD #11 — Web panelden canlı terminal UYGULANDI:** yeni spawn'lar `tmux -L cops` ile sarılıyor (`tmux_backend.py` + bundled `data/tmux.conf`), panelde **Terminal** butonu (xterm.js, ~200ms poll, Ctrl-C/Esc/ok tuşları, mobilde copy butonu + ANSI-strip fallback). Kritik canlı-test bulgusu: `kill_session_and_parent` PID-ancestry'si tmux'ta TÜM filoyu silme riskiydi (parent = paylaşılan tmux server) → ad-bazlı `tmux kill-session`'a geçildi.
2. **TBD #10 — agy (Google Antigravity CLI) çoklu-CLI desteği UYGULANDI:** kullanıcının istediği **provider mimarisiyle** (`py/claudeops/providers/` — `CliProvider` ABC + `claude_provider.py` + `agy_provider.py` + registry; `spawn.py`/`discovery.py`/`web.py` `cli` string'ine göre HİÇ dallanmıyor). roster.tsv 4. kolon `cli`; agy isimlendirmesi `COPS_NAME` env (komut satırına gömülü, Popen env'ine DEĞİL — tmux'un `update-environment` filtresini atlamak için). agy model listesi canlı çekiliyor (300s TTL).
3. **README'ler (EN+TR) her iki yeni özellik için güncellendi** (Terminal butonu + CLI seçici bölümleri) + **Klasör yapısı/Nasıl çalışır bölümleri** yeni dosyaları (`providers/`, `tmux_backend.py`, `data/`, roster 4. kolon) yansıtacak şekilde tazelendi + **ekran görüntüleri yenilendi** (canlı panelden, CLI kolonu + Terminal butonu görünür halde — eskisi bu özelliklerden önceydi).
4. **README'lere ileriye-dönük not eklendi (kullanıcı isteğiyle):** Terminal butonunun tmux'un kendi scrollback'i olduğu (CLI'ın kendi ekran çizimiyle birebir eşleşmediği, ufak kayma bilinen ince kusur) ama her durumda ulaşılabilir kaldığı + **her** CLI backend için çalıştığı (kendi uzaktan-erişimi olmasa bile) açıkça yazıldı; CLI seçici bölümüne "bugünkü claude/agy sadece şu ana kadarki, provider mimarisi sayesinde üçüncü bir backend (ör. GitHub Copilot CLI) eklemek yeni kod değil yeni dosya" notu; telefon-erişim bölümüne "quick tunnel şu an tek yol, ileride kalıcı/self-hosted server seçeneği gelebilir" notu.
5. **Ayrı bir bulgu:** `hc20260827` (videogen) projesinin `.claude/settings.local.json`'ında wildcard'ı komutun ORTASINDA olan bir Bash izin kuralı vardı (`pytest test_a*.py ... test_i*.py`) — Claude Code'un kural eşleyicisi ilk `*`'dan sonrasını tamamen wildcard sayıyor, yani prefix'ten sonra HERHANGİ bir ek argüman sessizce onaylanıyordu. Ayrıca dosyalar artık mevcut değildi (bayat kural). Satır silindi — kullanıcı fark edip sordu, kural + repo kontrol edilip düzeltildi (o proje kendi commit sorumluluğunda, claudeops repo'suna dahil değil).
6. **TOBEDECIDED #10/#11 "Kapatılmış"a taşındı**, CLAUDE.md'deki "açık tasarım" referansı güncellendi — artık gerçekten açık bir TBD tasarım sorusu yok (sadece küçük TODO kalemleri: rename UI, agy Faz-3 handover/RFH, panelde dile-göre handover-metni copy-paste).
7. **İki commit, ikisi de push'landı** (`eb961f9` özellik+doküman ana commit'i, `ebf1f45` README ileriye-dönük not eki) — `origin` (github) ve `gitlab` ikisi de HEAD'de senkron, çalışma ağacı temiz.

**Yeni session yapacaklar:** (1) MEMORY.md oku. (2) Guard cron'u açma. (3) Tarih-isimli çöp roster satırları hâlâ temizlik bekliyor (rustrino*/line*/trino*/sase* tarihli — kullanıcıya sorup birleştir/sil). (4) agy Faz-3 (kendi handover/RFH/needs_ho sinyali) hâlâ ertelenmiş durumda, istenirse ayrı iş. (5) Bu session'ı kullanıcı kapatacak (self-kill yapma).

READY FOR HANDOVER
