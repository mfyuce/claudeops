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
- **Tunnel unit'i `Requires=claudeops-web.service` DEĞİL `Wants=` kullanmalı** — `Requires=` web restart'ını tunnel'a PROPAGATE ediyordu (her web redeploy'unda tunnel de restart → quick-tunnel modda YENİ rastgele URL, kullanıcının aktif sekmesini sessizce kırıyordu; 2026-08-31 canlı bulundu+düzeltildi, hem deploy hem `service.py` şablonu).
- **Repo PUBLIC** (MIT, github + gitlab mirror) — roster/models/token repo dışında. Kullanıcı: "dünyaya açığız, DONE/TODO/changelog önemli" → kayıtları özenli tut.
- Web Stop / `kill` / `rc --kill-first`: tmux-backed'de ad-bazlı `tmux kill-session` + pencereyi title'dan (`wmctrl`+`xdotool windowkill`) kapatır (2026-08-31 fix, PID-ancestry hâlâ YASAK — paylaşımlı server riski). Canlı doğrulanmadı (ekran kilitliydi) — bkz. TODO.md.
- **Web panel React+TypeScript+WebSocket'e yeniden yazıldı, `feature/react-ui` branch'inde TAMAMLANDI — main'e MERGE EDİLMEDİ ama artık main'le PARALEL, kalıcı deploy edilmiş durumda** (2026-08-31, kullanıcı kararı: "ikisini iki ayrı tunnel ile gidelim"): main aynen `py/cops web` :8765 (`claudeops-web.service`+`claudeops-tunnel.service`); react-ui ayrı worktree'den (`../claudeops-react-ui`) :8766 (`claudeops-web-react.service`+`claudeops-tunnel-react.service`, main'in BİREBİR aynı deseni, port hariç — **bu iki yeni unit repo'da TAKİP EDİLMİYOR**, `~/.config/systemd/user/`'da elle/ad-hoc oluşturuldu). URL'ler `~/.claude/claudeops/tunnel_url{,-react}.txt`; ntfy AYNI topic'i `[main]`/`[react]` etiketiyle paylaşıyor. İkisi de `server_started_at` alanıyla redeploy sonrası açık sekmeleri OTOMATİK yeniliyor. Nihai merge kararı hâlâ açık — bkz. TOBEDECIDED #14, detay DONE.md 2026-08-31.

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

## READY FOR HANDOVER (2026-08-31, 3)

`main` temiz, github+gitlab senkron. **DÜZELTME (bir önceki HANDOVER notu YANLIŞ iyimserdi):** `guard_lock` timeout fix'i (`GUARD_LOCK_ACQUIRE_TIMEOUT=60.0`, deploy edildi) bug'ı ÇÖZMEDİ, sadece KISMEN iyileştirdi — `cops` artık güvenilir şekilde handover oluyor (2 kez doğrulandı) ama kullanıcı 3. kez 4 session seçip DAKİKALARCA bekledi, yine sadece 1 tanesi başarılı oldu. **Kullanıcı "todo, yeni session'da başlarız" dedi — canlı tekrar-üretime yeşil ışık VERMEDİ, servisi de KAPATMAMAMI istedi (dokunmadım).** Tam teşhis izi (ekarte edilenler + kanıt + önerilen ilk adım) TODO.md'nin en üstünde, "Bekleyen karar" bölümünde — yeni session doğrudan oradan devam etsin, bu araştırmayı tekrarlamasın.

**Değişmeyenler:** TOBEDECIDED #14 (`feature/react-ui` merge kararı) açık. Bash `claudeops` silinebilir mi (TOBEDECIDED #12), yeni CLI backend adayları (gemini, TODO.md) — değişmedi.

**Canlı:** fleet'te 7 session ayakta, config sağlıklı, dup yok; web+tunnel servisleri aktif (18:56'dan beri, bu handover'da DOKUNULMADI — kullanıcı isteği), reboot yok.

READY FOR HANDOVER
