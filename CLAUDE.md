# claudeops — Claude Context

Açık Claude CLI session'larını toplu yönet. **`py/cops`** = canlı Python tool; **`./claudeops`** (bash) = layout + eski komutlar.

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. Aynı sid resume → cache'li, değiştirmek için `--new`.
- **xdotool**: `windowmove` → **`--sync` YOK** (hang).
- **claude 2.1.169**: fresh `--new` session'lar `sessions/<pid>.json` yazmıyor → keşif proc-scan'le. [[claude-2169-session-detection]]
- **claude 2.1.183 KILL=TRUNCATE**: lazy-checkpoint storage; kill'de flush için zaman gerek → **hep SIGTERM + ~8-10s bekle, sadece canlıysa SIGKILL**. Ani kapanma/sert-OOM = son mesajlar gider (iş git'te güvende, sadece transkript). [[claude-2183-conversation-truncation]] [[reboot-recovery]]
- **claude resume "deferred tool marker"**: promptsuz `--resume` bazen ANINDA "No deferred tool marker found" ile çıkar → resume'a mutlaka `--prompt` ver (`py/cops rc <name> --prompt='devam'`, `--new` OLMADAN). [[resume-deferred-tool-marker]]
- **1M context**: `[1m]` suffix → beta header; şu an KAPALI (token kısıtı). [[model-1m-context]]
- **spawn güvenilirliği**: CLAUDE*/GEMINI*/ANTIGRAVITY* env her spawn'da filtrelenir (yoksa transcript sessizce kapanır). gnome-terminal başarısız olursa (kendi D-Bus/uzun-yaşam bozulması, ARADA SIRADA olur) spawn.py OTOMATİK tmux-only fallback'e düşer — panelin **Tanı** sekmesinden durum görülür/test edilir/gt-restart tetiklenir. [[spawn-env-leak-disables-transcript]] [[spawn-zombie-child-degrades-web-server]] [[diag-tab-feature]]
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Roster / model (`~/.claude/claudeops/{roster,models}.tsv` — repo DIŞI, kaynak-of-truth)

- Tüm isimler **`claude-sonnet-5`** (2026-08-24 Claude 5 geçişi; opus split geri alındı — istenirse `sed -i 's/claude-sonnet-5/claude-opus-5/'` ile grup bazında geri, önce tek isimle test).
- **İsimler base-name** (suffix yok). `Session.base` tarih+`_N` suffix'lerini indirger: `cops20260824_1`→`cops`. Panel eşlemesi önce TAM isim, sonra base — tarih-isimli satırlar kendi satırında görünür, görünmez canlı proc imkansız.
- **co + cops** (self) + **ulaksec** aktif (guard ayakta tutsun). İsim-listesiyle hariç tutma YOK — toplu işlem hedefi panel checkbox'larıyla; tek koruma process-bazlı self-koruma (`ancestor_pids()` py handover+rc; bash `filter_not_self`). [[co-ulaksec-guard-yes-ho-no]]
- Kapalı/emekli satırlar `#`'lı. `py/cops close <name>` = kill + models.tsv yorumla; geri: panel "tekrar işe al". **Temizlik bekliyor:** tarih-isimli çöp satırlar (rustrino*/line*/trino*/sase* tarihli, TODO.md'de detay) — kullanıcıya sorup birleştir/sil.
- roster.tsv'nin opsiyonel **4. kolonu = `cli`** (`claude`|`agy`, yoksa/eskiyse `"claude"`).

## Fleet kontrolü — MANUEL (2026-08-24 karar)

- **Guard cron KASITLI kapalı.** Kullanıcı `py/cops web`'den tek tek başlatıyor — **sen açma**, sormadan toplu spawn YAPMA. [[feedback-manual-fleet-control]]
- **`py/cops web [--port 8765] [--tunnel]`** — panel sekmeleri: Çalışanlar / Kayıtlı / Devre dışı / Emekli / Layout / **Tanı**. Satır checkbox'ları + toplu işlemler, **ho?** kolonu, satır-içi başlat seçenekleri (model/permission-mode/effort/CLI), panelden canlı **Terminal** (tmux-capture tabanlı, xterm.js). CLI seçici (claude/agy, `providers/` registry — 3. bir backend eklemek yeni dosya, kod dallanması değil). **Tanı** sekmesi: web/gt çalışma süreleri, windowless-fallback session listesi, spawn sağlık testi, gt-restart, `diag.log`, "LLM'e sor" (seçilen CLI ile gerçek bir fleet session'ı + Terminal — kayıt-dışı chat değil). Detay: `py/README*.md`, [[diag-tab-feature]].
- **Repo PUBLIC** (MIT, github + gitlab mirror) — roster/models/token repo dışında. Kullanıcı: "dünyaya açığız, DONE/TODO/changelog önemli" → kayıtları özenli tut.
- Web Stop / `py/cops kill` / `rc --kill-first`: tmux-backed session'da ad-bazlı `tmux kill-session` (parent bash paylaşımlı server olabilir, PID-ancestry YASAK) — AMA bu, gnome-terminal PENCERESİNİ kapatmıyor (açık TODO, orphan bash kalıyor).

## Handover (3-fazlı)

- **Faz 1:** `py/cops handover [--dry-run]` — batch'li (mass aynı anda = rate-limit → blank-TUI [[mass-faz1-ratelimit-stuck]]); self (komutun atası) otomatik atlanır.
- **Faz 2:** Faz1 sağlıksızsa (503/529) DUR, kullanıcı onayı şart. `py/cops rc <isimler SPACE'li> --new --kill-first --model='claude-sonnet-5' --permission-mode=auto --effort=max --one-by-one` (bash rc DEĞİL — py cwd'yi roster'dan alır). `--prompt` VERME (boş başlasınlar [[faz2-new-session-devam]]). Config doğrula: `python3 -c "import json;json.load(open('$HOME/.claude.json'))"`. Bridge rate-limit: 4'er batch + 20s [[bridge-batch-spawn-ratelimit]].
- **Faz 3:** ÖNCE `loginctl show-session <id> -p LockedHint`=no doğrula [[layout-needs-unlocked-screen]]. `./claudeops layout grid 4 --claude-only --pin=... --group=...` — 2× çalıştır, `xwininfo` ile doğrula (wmctrl 2× yalan). `[1m]` tek tırnak; target SPACE-separated.
- **Skip kriteri:** RFH var + sonrasında yeni istek yok + repo temiz+pushed (github+gitlab).
- Detay: [[handover-procedure]] [[handover-edge-cases]] [[feedback-ho-stop-on-error]] [[config-corruption-resume-hang]]

## Sınırlamalar / açık bug'lar

Wayland: layout çalışmaz. gnome-terminal hard-coded. `rc --kill-first` permission modal keser. Target virgül parse yok (SPACE). Tam liste: TODO.md (öne çıkanlar: tmux-backed "stop" penceresi kapatmıyor; terminal görünümünde kozmetik taşma).

## Meta

`DONE.md` = CHANGELOG. `TOBEDECIDED.md` = açık mimari sorular (karar verildikçe "Kapatılmış"a taşınır, silinmez). Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
Ho-prep sync (her ho'da): TODO done → DONE.
