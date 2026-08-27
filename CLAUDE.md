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

## Fleet kontrolü — MANUEL (2026-08-24 karar)

- **Guard cron KASITLI kapalı** (crontab'da 3 satır `#`'lı). Kullanıcı web'den tek tek yönetiyor — **sen açma**, sormadan toplu spawn YAPMA. [[feedback-manual-fleet-control]]
- **`py/cops web [--port 8765] [--tunnel]`** — TAB'lı panel (Çalışanlar / Kayıtlı / Devre dışı / Emekli / Layout, 2026-08-25 revizyonu): satır checkbox'ları + toplu işlemler (handover/durdur/devre dışı bırak/emekli et), **ho?** kolonu + "needs-ho seç", satır-içi başlat seçenekleri, kayıtsızlara "devral", "+ yeni proje kaydet" formu Kayıtlı sekmesinde. UI "devre dışı bırak" = API/CLI `close`. Layout sekmesi kilitli-ekran pre-flight'lı. Token-gated; `--tunnel` = cloudflared. Detay: `py/README*.md`.
- **Repo PUBLIC** (MIT, github + gitlab mirror) — roster/models/token repo dışında. Kullanıcı: "dünyaya açığız, DONE/TODO/changelog önemli" → kayıtları özenli tut.
- Web Stop / `py/cops kill` / `rc --kill-first` parent bash'i de öldürür (`kill_session_and_parent`).

## Handover (3-fazlı)

- **Faz 1:** `py/cops handover [--dry-run]` — batch'li (mass aynı anda = rate-limit → blank-TUI [[mass-faz1-ratelimit-stuck]]); self (komutun atası) otomatik atlanır.
- **Faz 2:** Faz1 sağlıksızsa (503/529) DUR, kullanıcı onayı şart. `py/cops rc <isimler SPACE'li> --new --kill-first --model='claude-sonnet-5' --permission-mode=auto --effort=max --one-by-one` (bash rc DEĞİL — py cwd'yi roster'dan alır). `--prompt` VERME (boş başlasınlar [[faz2-new-session-devam]]). Config doğrula: `python3 -c "import json;json.load(open('$HOME/.claude.json'))"`. Bridge rate-limit: 4'er batch + 20s [[bridge-batch-spawn-ratelimit]].
- **Faz 3:** ÖNCE `loginctl show-session <id> -p LockedHint`=no doğrula [[layout-needs-unlocked-screen]]. `./claudeops layout grid 4 --claude-only --pin=... --group=...` — 2× çalıştır, `xwininfo` ile doğrula (wmctrl 2× yalan). `[1m]` tek tırnak; target SPACE-separated.
- **Skip kriteri:** RFH var + sonrasında yeni istek yok + repo temiz+pushed (github+gitlab).
- Detay: [[handover-procedure]] [[handover-edge-cases]] [[feedback-ho-stop-on-error]] [[config-corruption-resume-hang]]

## Sınırlamalar / açık bug'lar

Wayland: layout çalışmaz. gnome-terminal hard-coded. `rc --kill-first` permission modal keser. Target virgül parse yok (SPACE). Tam liste: TODO.md. Açık tasarımlar (karar bekliyor, implement ETME): TOBEDECIDED **#10 agy/Antigravity-CLI entegrasyonu**, **#11 tmux-backed web-CLI**.

## Meta

`DONE.md` = CHANGELOG. Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
Ho-prep sync (her ho'da): TODO done → DONE; TOBEDECIDED karar → TODO.

## READY FOR HANDOVER (2026-08-27)

**DURUM:** Fleet manuel kontrolde (guard cron kasıtlı kapalı). Çalışanlar: `cops` (bu session, `cops20260824_1` proc'u), `line20260825`, `rustrino20260826`, `sase20260826`, `saseimpl`, `trino20260826_1`. Roster: 21 aktif / 21 devre dışı / 7 emekli; config VALID, DUP yok. Panel (8765) + cloudflared tüneli ayakta; kullanıcı paneli aktif kullanıyor (toplu devre-dışı, handover, saseimpl start hep panelden yapıldı).

**Bu session'da (25-27 Ağu, hepsi commit+push'lu, DONE.md'de detay):**
1. **cops roster'a kaydedildi**; register hata mesajı artık çakışma kaynağını ayırt ediyor (`conflicts_running` — "retired'da var" yanılgısı bitti).
2. **Panel UI revizyonu:** TAB + checkbox + toplu işlemler + ho? kolonu + "needs-ho seç"; "close" UI'de "devre dışı bırak" oldu (API adı değişmedi). README'ler (EN+TR) + ekran görüntüleri yenilendi.
3. **HO_EXCLUDE isim-listesi kaldırıldı** (kullanıcı kararı) → process-bazlı self-koruma (`ancestor_pids()`); ulaksec artık sadece dikkatle korunuyor.
4. **`Session.base` `_N` suffix indirgeme** + **panel canlı-proc eşlemesi tam-isim öncelikli** (rename sonrası görünmez-proc riski kapandı; duplicates() artık gerçekten çalışıyor).
5. **sase → saseppr** rename (elle TSV — UI'de rename yok, TODO'da tasarımıyla kayıtlı); **saseimpl** = `.../maya3/ng_sdn/sase/sdwan/ng_sdwan` kaydedildi (`sase_imp_paper` AYRI, sırası gelmemiş bir proje — karıştırma).
6. **TBD #10 (agy/Antigravity CLI) + #11 (tmux web-CLI)** tasarım taslakları yazıldı — kullanıcı "biraz daha konuşalım" dedi, KARAR YOK, implement etme.

**Yeni session yapacaklar:** (1) MEMORY.md oku. (2) Guard cron'u açma. (3) Tarih-isimli çöp roster satırlarını kullanıcıya sorup temizle. (4) TBD #10/#11 tartışması sürüyor — kullanıcı karar verince başla. (5) Bu session'ı kullanıcı kapatacak (self-kill yapma).

READY FOR HANDOVER
