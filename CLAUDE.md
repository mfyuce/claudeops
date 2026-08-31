# claudeops — Claude Context

Açık Claude CLI session'larını toplu yönet. **`py/cops`** = canlı Python tool; **`./claudeops`** (bash) = layout + eski komutlar (silinir mi: TOBEDECIDED.md #12).

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. Aynı sid resume → cache'li, değiştirmek için `--new`.
- **xdotool**: `windowmove` → **`--sync` YOK** (hang).
- **claude 2.1.183 KILL=TRUNCATE**: lazy-checkpoint storage → **hep SIGTERM + ~8-10s bekle, sadece canlıysa SIGKILL** (sert kill = son mesajlar gider, iş git'te güvende). [[claude-2183-conversation-truncation]]
- **claude resume "deferred tool marker"**: promptsuz `--resume` bazen ANINDA hata verir → resume'a mutlaka `--prompt` ver (`--new` OLMADAN). [[resume-deferred-tool-marker]]
- **spawn güvenilirliği**: CLAUDE*/GEMINI*/ANTIGRAVITY* env filtrelenir (yoksa transcript kapanır). gnome-terminal flake → oto-retry+fallback, windowless'i **"pencere aç"**la düzelt. "restart hâlâ olmuyor" → **gt-restart** (Tanı sekmesi, web'den bağımsız). [[spawn-env-leak-disables-transcript]] [[spawn-zombie-child-degrades-web-server]]
- **`service.py`'nin `WEB_UNIT_TEMPLATE`'ini düzenlersen `bash -ic '...'` ExecStart'ı ve `KillMode=process`'i BOZMA** — ikisi de canlı yaşanan gerçek hasarların fix'i (sırasıyla: minimal systemd PATH → `claude: command not found`; varsayılan `control-group` → servis restart'ı ALTINDAKİ tmux'u da öldürür), tam gerekçe modülün kendi docstring'inde.
- **`web.py`'de `guard_lock(timeout=...)` her yerde `GUARD_LOCK_ACQUIRE_TIMEOUT` (60s) KULLANMALI, geri düşürme** — kilit kill+spawn+stabilize boyunca (~45-50s worst-case) tutuluyor; 5s'lik eski değer bulk handover'da sıradaki item'ı erken timeout'a düşürüyordu (2026-08-31, canlı bulundu — DONE.md).
- **oomd TÜM oturumu öldürebilir** (sadece fleet'in cgroup'unu değil) — kurtarma `py/cops service watchdog` (root-seviyeli, oturumdan bağımsız timer). [[oomd-cgroup-kill]]
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Roster / model (`~/.claude/claudeops/{roster,models}.tsv` — repo DIŞI, kaynak-of-truth)

- Tüm isimler **`claude-sonnet-5`** (2026-08-24 Claude 5 geçişi; opus split geri alındı — istenirse `sed -i 's/claude-sonnet-5/claude-opus-5/'` ile grup bazında geri, önce tek isimle test).
- **İsimler base-name** (suffix yok). `Session.base` tarih+`_N` suffix'lerini indirger: `cops20260824_1`→`cops`. Panel eşlemesi önce TAM isim, sonra base — tarih-isimli satırlar kendi satırında görünür, görünmez canlı proc imkansız.
- **co + cops** (self) + **ulaksec** aktif (guard ayakta tutsun). İsim-bazlı hariç tutma YOK, seçim panel checkbox'larıyla; tek koruma process-bazlı self-koruma (`ancestor_pids()`). [[co-ulaksec-guard-yes-ho-no]]
- Kapalı/emekli satırlar `#`'lı. `py/cops close <name>` = kill + models.tsv yorumla; geri: panel "tekrar işe al". Tarih-isimli çöp satır temizliği bekliyor (detay TODO.md).
- roster.tsv'nin opsiyonel **4. kolonu = `cli`** (`claude`|`agy`|`shell`, yoksa/eskiyse `"claude"`). `shell` = düz interaktif bash (sudo/TTY işleri için — panel terminali gerçek PTY). Provider mimarisi `py/claudeops/providers/`: yeni backend = yeni dosya, dallanma yok (adaylar TODO.md'de).

## Fleet kontrolü — MANUEL (2026-08-24 karar)

- **Guard cron KASITLI kapalı.** Kullanıcı `py/cops web`'den tek tek başlatıyor — **sen açma**, sormadan toplu spawn YAPMA. [[feedback-manual-fleet-control]]
- **`py/cops web [--port 8765] [--tunnel]`** — kontrol paneli; tam sekme/özellik listesi `py/README*.md` + [[diag-tab-feature]]. CLI seçici çoklu-backend (claude/agy/shell).
- **`py/cops service install|status|uninstall|notify|watchdog`** — web+tunnel artık systemd `--user` ile KALICI (logout/reboot'ta otomatik, `Restart=on-failure`); `notify` = tunnel URL değişince ntfy.sh push'u; `watchdog` = yukarıdaki oomd-tüm-oturum senaryosunu kurtarır (root, `sudo` ister). Detay: `py/README*.md`.
- **Repo PUBLIC** (MIT, github + gitlab mirror) — roster/models/token repo dışında. Kullanıcı: "dünyaya açığız, DONE/TODO/changelog önemli" → kayıtları özenli tut.
- Web Stop / `kill` / `rc --kill-first`: tmux-backed'de ad-bazlı `tmux kill-session` (PID-ancestry YASAK — paylaşımlı server riski). Pencere kapatmama açık bug'ı: TODO.md.
- **Web panel React+TypeScript+WebSocket'e yeniden yazıldı, `feature/react-ui` branch'inde TAMAMLANDI** (ayrı worktree `../claudeops-react-ui`, `main` dokunulmadı) — merge kararı bekliyor, bkz. TOBEDECIDED #14, detay DONE.md 2026-08-31.

## Handover (3-fazlı)

- **Faz 1:** `py/cops handover [--dry-run]` — batch'li (mass aynı anda = rate-limit → blank-TUI [[mass-faz1-ratelimit-stuck]]); self (komutun atası) otomatik atlanır. Konuşması olmayan provider'lar (`shell`) `has_conversation()=False` ile otomatik dışlanır — kill edilmezler.
- **Faz 2:** Faz1 sağlıksızsa (503/529) DUR, kullanıcı onayı şart. `py/cops rc <isimler SPACE'li> --new --kill-first --model='claude-sonnet-5' --permission-mode=auto --effort=max --one-by-one` (bash rc DEĞİL). `--prompt` VERME (boş başlasınlar [[faz2-new-session-devam]]). Config doğrula: `python3 -c "import json;json.load(open('$HOME/.claude.json'))"`. Bridge rate-limit: 4'er batch + 20s [[bridge-batch-spawn-ratelimit]].
- **Faz 3:** ÖNCE `loginctl show-session <id> -p LockedHint`=no doğrula [[layout-needs-unlocked-screen]]. `./claudeops layout grid 4 --claude-only --pin=... --group=...` (bash — `py/cops layout` eşdeğerliği CANLI doğrulanıp CLAUDE.md güncellenmedi, TOBEDECIDED.md #12) — 2× çalıştır, `xwininfo` ile doğrula (wmctrl 2× yalan).
- **Skip kriteri:** RFH var + sonrasında yeni istek yok + repo temiz+pushed (github+gitlab).
- Detay: [[handover-procedure]] [[handover-edge-cases]] [[feedback-ho-stop-on-error]] [[config-corruption-resume-hang]]

## Sınırlamalar / açık bug'lar

Wayland: layout çalışmaz. gnome-terminal hard-coded. `rc --kill-first` permission modal keser. Target virgül parse yok (SPACE). Tam liste: TODO.md (öne çıkanlar: tmux-backed "stop" penceresi kapatmıyor; terminal görünümü mobilde work-in-progress).

## Meta

`DONE.md` = CHANGELOG. `TOBEDECIDED.md` = açık mimari sorular (karar verildikçe "Kapatılmış"a taşınır, silinmez). Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
Ho-prep sync (her ho'da): TODO done → DONE.

## READY FOR HANDOVER (2026-08-31, 2)

`main` temiz, github+gitlab senkron (`bba86f2`). Önceki HANDOVER notundan (aynı gün, birkaç saat önce) beri tek ek olay: kullanıcı canlı olarak (masaüstü/lokal) 4 session seçip bulk handover denedi, sadece ilki (`cops`, kendi session'ı) işlendi, diğer 3'üne hiç dokunulmadı. **KÖK SEBEP bulunup düzeltildi ve deploy edildi:** `guard_lock(timeout=5.0)` — kilit ACQUIRE süresi, kilidin kendisinin kill+spawn+stabilize boyunca TUTULMA süresinden (~45-50s worst-case) çok daha kısaydı; item 1 sunucu tarafında başarıyla bitmesine rağmen yanıt istemciye zamanında ulaşmayınca döngü item 2'ye geçiyor, o da sadece 5s bekleyip timeout alıyordu. Fix: paylaşılan `GUARD_LOCK_ACQUIRE_TIMEOUT=60.0`, 8 çağrı noktasının hepsinde. `main`'e deploy + `feature/react-ui`'ye de port edildi (aynı bug, aynı backend kodu), ikisi de commit+push edildi. Detay: DONE.md 2026-08-31 (3).

**Değişmeyenler:** TOBEDECIDED #14 (`feature/react-ui` merge kararı) hâlâ açık — kullanıcı bu session'da onu bizzat canlı test etti (handover fix'i doğrulamak için), henüz merge etmedi. Bash `claudeops` silinebilir mi (TOBEDECIDED #12), yeni CLI backend adayları (gemini, TODO.md) — değişmedi.

**Canlı:** fleet'te 7 session ayakta (`cops` fix sonrası taze resume aldı), config sağlıklı, dup yok; web+tunnel servisleri aktif, reboot yok.

READY FOR HANDOVER
