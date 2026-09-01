# claudeops — Claude Context

Açık Claude CLI session'larını toplu yönet. **`py/cops`** = canlı Python tool; **`./claudeops`** (bash) = layout + eski komutlar (silinir mi: TOBEDECIDED.md #12).

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. Aynı sid resume → cache'li, değiştirmek için `--new`.
- **xdotool**: `windowmove` → **`--sync` YOK** (hang).
- **claude 2.1.183 KILL=TRUNCATE**: lazy-checkpoint storage → **hep SIGTERM + ~8-10s bekle, sadece canlıysa SIGKILL** (sert kill = son mesajlar gider, iş git'te güvende). [[claude-2183-conversation-truncation]]
- **claude resume "deferred tool marker"**: promptsuz `--resume` bazen ANINDA hata verir → resume'a mutlaka `--prompt` ver (`--new` OLMADAN). [[resume-deferred-tool-marker]]
- **spawn güvenilirliği**: CLAUDE*/GEMINI*/ANTIGRAVITY* env filtrelenir (yoksa transcript kapanır). gnome-terminal flake → oto-retry+fallback, windowless'i **"pencere aç"**la düzelt. "restart hâlâ olmuyor" → **gt-restart** (Tanı sekmesi, web'den bağımsız). [[spawn-env-leak-disables-transcript]] [[spawn-zombie-child-degrades-web-server]]
- **`service.py`'nin `WEB_UNIT_TEMPLATE`'ini düzenlersen `bash -ic '...'` ExecStart'ı, `KillMode=process`, ve tunnel unit'inin `Wants=` (`Requires=` DEĞİL) satırını BOZMA** — üçü de canlı yaşanan gerçek hasarların fix'i (sırasıyla: minimal systemd PATH → `claude: command not found`; varsayılan `control-group` → restart altındaki tmux'u da öldürür; `Requires=` → web servisini restart etmek tunnel'ı da stop+start eder, quick-tunnel modda URL her seferinde rastgele değişip kullanıcının bookmark'ını kırar), tam gerekçe modülün kendi docstring'inde. `run-tunnel.sh` `CLAUDEOPS_TUNNEL_URL_FILE`/`_LOG`/`_LABEL`/`CLAUDEOPS_PORT` env override'larını destekler — ikinci bir paralel deploy'un tünel/log dosyasını canlı olanınkiyle EZMEDEN çalışabilmesi için (2026-09-01 merge'de main'den korunan versiyon; [[tunnel-flag-shares-live-log-file]]).
- **oomd TÜM oturumu öldürebilir** (sadece fleet'in cgroup'unu değil) — kurtarma `py/cops service watchdog` (root-seviyeli, oturumdan bağımsız timer). [[oomd-cgroup-kill]]
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Roster / model (`~/.claude/claudeops/{roster,models}.tsv` — repo DIŞI, kaynak-of-truth)

- Tüm isimler **`claude-sonnet-5`** (2026-08-24 Claude 5 geçişi; opus split geri alındı — istenirse `sed -i 's/claude-sonnet-5/claude-opus-5/'` ile grup bazında geri, önce tek isimle test).
- **İsimler base-name** (suffix yok). `Session.base` tarih+`_N` suffix'lerini indirger: `cops20260824_1`→`cops`. Panel eşlemesi önce TAM isim, sonra base — tarih-isimli satırlar kendi satırında görünür, görünmez canlı proc imkansız.
- **co + cops** (self) + **ulaksec** aktif (guard ayakta tutsun). İsim-bazlı hariç tutma YOK, seçim panel checkbox'larıyla; tek koruma process-bazlı self-koruma (`ancestor_pids()`). [[co-ulaksec-guard-yes-ho-no]]
- Kapalı/emekli satırlar `#`'lı. `py/cops close <name>` = kill + models.tsv yorumla; geri: panel "tekrar işe al". **Temizlik bekliyor:** tarih-isimli çöp satırlar (rustrino*/line*/trino*/sase* tarihli, TODO.md'de detay) — kullanıcıya sorup birleştir/sil.
- roster.tsv'nin opsiyonel **4. kolonu = `cli`** (`claude`|`agy`|`shell`, yoksa/eskiyse `"claude"`). `shell` = düz interaktif bash (sudo/TTY işleri için — panel terminali gerçek PTY). Provider mimarisi `py/claudeops/providers/`: yeni backend = yeni dosya, dallanma yok (adaylar TODO.md'de).

## Fleet kontrolü — MANUEL (2026-08-24 karar)

- **Guard cron KASITLI kapalı.** Kullanıcı `py/cops web`'den tek tek başlatıyor — **sen açma**, sormadan toplu spawn YAPMA. [[feedback-manual-fleet-control]]
- **`py/cops web [--port 8765] [--tunnel]`** — kontrol paneli; tam sekme/özellik listesi `py/README*.md` + [[diag-tab-feature]]. CLI seçici çoklu-backend (claude/agy/shell).
- **`py/cops service install|status|uninstall|notify|watchdog`** — web+tunnel artık systemd `--user` ile KALICI (logout/reboot'ta otomatik, `Restart=on-failure`); `notify` = tunnel URL değişince ntfy.sh push'u; `watchdog` = yukarıdaki oomd-tüm-oturum senaryosunu kurtarır (root, `sudo` ister). Detay: `py/README*.md`.
- **Repo PUBLIC** (MIT, github + gitlab mirror) — roster/models/token repo dışında. Kullanıcı: "dünyaya açığız, DONE/TODO/changelog önemli" → kayıtları özenli tut.
- Web Stop / `kill` / `rc --kill-first`: tmux-backed'de ad-bazlı `tmux kill-session` (PID-ancestry YASAK — paylaşımlı server riski) + `find_outer_bash_pids()` ile session ölmeden ÖNCE yakalanan outer-pencere PID'lerini de kapatır (2026-09-01 fix, DONE.md).

## Handover (3-fazlı)

- **Faz 1:** `py/cops handover [--dry-run]` — batch'li (mass aynı anda = rate-limit → blank-TUI [[mass-faz1-ratelimit-stuck]]); self (komutun atası) otomatik atlanır. Konuşması olmayan provider'lar (`shell`) `has_conversation()=False` ile otomatik dışlanır — kill edilmezler.
- **Faz 2:** Faz1 sağlıksızsa (503/529) DUR, kullanıcı onayı şart. `py/cops rc <isimler SPACE'li> --new --kill-first --model='claude-sonnet-5' --permission-mode=auto --one-by-one` (bash rc DEĞİL). `--effort` VERME — varsayılan artık `high` (2026-09-01 kullanıcı kararı: max/xhigh yerine, respawn edilen session'ın kalıcı varsayımı olduğu için — [[handover-effort-high-not-max]]). `--prompt` VERME (boş başlasınlar [[faz2-new-session-devam]]). Config doğrula: `python3 -c "import json;json.load(open('$HOME/.claude.json'))"`. Bridge rate-limit: 4'er batch + 20s [[bridge-batch-spawn-ratelimit]].
- **Faz 3:** ÖNCE `loginctl show-session <id> -p LockedHint`=no doğrula [[layout-needs-unlocked-screen]]. `./claudeops layout grid 4 --claude-only --pin=... --group=...` (bash — `py/cops layout` eşdeğerliği CANLI doğrulanıp CLAUDE.md güncellenmedi, TOBEDECIDED.md #12) — 2× çalıştır, `xwininfo` ile doğrula (wmctrl 2× yalan).
- **Skip kriteri:** RFH var + sonrasında yeni istek yok + repo temiz+pushed (github+gitlab).
- Detay: [[handover-procedure]] [[handover-edge-cases]] [[feedback-ho-stop-on-error]] [[config-corruption-resume-hang]]

## Sınırlamalar / açık bug'lar

Wayland: layout çalışmaz. gnome-terminal hard-coded. `rc --kill-first` permission modal keser. Target virgül parse yok (SPACE). Tam liste: TODO.md (öne çıkanlar: terminal görünümü mobilde work-in-progress; bulk handover'da bazen sadece ilk item başarılı oluyor — main'de kısmi teşhis edildi, tam kök sebep hâlâ açık).

## Meta

`DONE.md` = CHANGELOG. `TOBEDECIDED.md` = açık mimari sorular (karar verildikçe "Kapatılmış"a taşınır, silinmez). Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
Ho-prep sync (her ho'da): TODO done → DONE.

## READY FOR HANDOVER (2026-09-01)

**BÜYÜK GÜN: `feature/react-ui` main'e merge edildi, React panel artık ASIL panel** (TOBEDECIDED.md #14, kullanıcı kararı — detay DONE.md). Eski PAGE_HTML panel emekli. Merge, main'in 19 kendine-özgü commit'i tek tek incelenerek yapıldı (kör "react kazanır" değil) — main'den korunan tek 2 şey: `service.py`'nin tunnel `Wants=` fix'i + `run-tunnel.sh` parametrizasyonu (ikisi de zaten canlı deploy edilmiş haldeydi, sadece react-ui'nin tracked kaynağı bayattı). Bu ikisi artık yukarıdaki "Kritik kısıtlar"da.

Aynı session'da ayrıca: tmux-backed "stop" orphan-window bug'ı (PID-bazlı, X11'den bağımsız, canlı doğrulandı), adopt'un tirelenmiş/foreign isimleri reddetmesi, handover'ın varsayılan effort'u max→high (3 fix, detay DONE.md 2026-09-01 (1)-(3)).

**Canlı:** main :8765 (`claudeops-web.service`+`claudeops-tunnel.service`) — yeni koda restart edildi, fleet (7 session) etkilenmedi, tunnel URL değişmedi (`Wants=` doğrulandı, `journalctl` restart YOK). React-only paralel deploy (:8766) durduruldu+disable edildi (unit'ler silinmedi). `feature/react-ui` branch+worktree silinmedi (rollback referansı). github+gitlab'a push edildi (main + feature/react-ui).

**Sıradaki session'ın bilmesi gereken:** eski "main sadece parity alır, asıl react-ui'de" kuralı ARTIK GEÇERSİZ — tek ağaç var, react-ui worktree'si sadece tarihsel referans. TODO.md'ye bugün 2 yeni madde eklendi: tablara sayfalama (kullanıcı isteği, kapsam netleşmedi) + main'de kısmen teşhis edilmiş "bulk handover'da sadece ilk item başarılı oluyor" (kök sebep hâlâ açık, taşındı).

READY FOR HANDOVER
