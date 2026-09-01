# claudeops — Claude Context

Açık Claude CLI session'larını toplu yönet. **`py/cops`** = canlı Python tool; **`./claudeops`** (bash) = layout + eski komutlar (silinir mi: TOBEDECIDED.md #12).

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. Aynı sid resume → cache'li, değiştirmek için `--new`.
- **xdotool**: `windowmove` → **`--sync` YOK** (hang).
- **claude 2.1.183 KILL=TRUNCATE**: lazy-checkpoint storage → **hep SIGTERM + ~8-10s bekle, sadece canlıysa SIGKILL** (sert kill = son mesajlar gider, iş git'te güvende). [[claude-2183-conversation-truncation]]
- **claude resume "deferred tool marker"**: promptsuz `--resume` bazen ANINDA hata verir → resume'a mutlaka `--prompt` ver (`--new` OLMADAN). [[resume-deferred-tool-marker]]
- **spawn güvenilirliği**: CLAUDE*/GEMINI*/ANTIGRAVITY* env filtrelenir (yoksa transcript kapanır). gnome-terminal flake → oto-retry+fallback, windowless'i **"pencere aç"**la düzelt. [[spawn-env-leak-disables-transcript]] [[spawn-zombie-child-degrades-web-server]]
- **`service.py`'nin `WEB_UNIT_TEMPLATE`'ini düzenlersen `bash -ic '...'` ExecStart'ı, `KillMode=process`, ve tunnel unit'inin `Wants=` (`Requires=` DEĞİL) satırını BOZMA** — üçü de canlı yaşanan gerçek hasarların fix'i (minimal PATH → `command not found`; `control-group` → restart altındaki tmux'u da öldürür; `Requires=` → her web-redeploy'da tunnel URL'i rastgele değişir). Detay: DONE.md 2026-08-30/31.
- **`web.py`'de `guard_lock(timeout=...)` her yerde `GUARD_LOCK_ACQUIRE_TIMEOUT` (60s) KULLANMALI, geri düşürme** — kilit kill+spawn+stabilize boyunca (~45-50s worst-case) tutuluyor.
- **oomd TÜM oturumu öldürebilir** (sadece fleet'in cgroup'unu değil) — kurtarma `py/cops service watchdog` (root-seviyeli, oturumdan bağımsız timer). [[oomd-cgroup-kill]]
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Roster / model (`~/.claude/claudeops/{roster,models}.tsv` — repo DIŞI, kaynak-of-truth)

- Tüm isimler **`claude-sonnet-5`**.
- **İsimler base-name** (suffix yok). `Session.base` tarih+`_N` suffix'lerini indirger: `cops20260824_1`→`cops`. Panel eşlemesi önce TAM isim, sonra base.
- **co + cops** (self) + **ulaksec** aktif (guard ayakta tutsun). İsim-bazlı hariç tutma YOK, seçim panel checkbox'larıyla; tek koruma process-bazlı self-koruma (`ancestor_pids()`). [[co-ulaksec-guard-yes-ho-no]]
- Kapalı/emekli satırlar `#`'lı. `py/cops close <name>` = kill + models.tsv yorumla; geri: panel "tekrar işe al".
- roster.tsv'nin opsiyonel 4. kolonu = `cli`. Provider mimarisi (`py/claudeops/providers/base.py` + registry, dallanma yok — yeni backend = 1 dosya + registry satırı) kendi docstring'inde belgeli, burada tekrarlanmıyor.

## Fleet kontrolü — MANUEL (2026-08-24 karar)

- **Guard cron KASITLI kapalı.** Kullanıcı `py/cops web`'den tek tek başlatıyor — **sen açma**, sormadan toplu spawn YAPMA. [[feedback-manual-fleet-control]]
- **`py/cops web [--port 8765] [--tunnel]`** — kontrol paneli; tam sekme/özellik listesi `py/README*.md` + [[diag-tab-feature]].
- **`py/cops service install|status|uninstall|notify|watchdog`** — web+tunnel systemd `--user` ile KALICI (logout/reboot'ta otomatik). Detay: `py/README*.md`.
- **Repo PUBLIC** (MIT, github + gitlab mirror) — roster/models/token repo dışında. DONE/TODO/changelog özenli tutulmalı.
- Web Stop / `kill` / `rc --kill-first`: tmux-backed'de ad-bazlı `tmux kill-session` + pencereyi title'dan (`wmctrl`+`xdotool windowkill`) kapatır. Canlı doğrulanmadı — bkz. TODO.md.
- **İki panel PARALEL canlı deploy, merge YOK:** main :8765, `feature/react-ui` (worktree `../claudeops-react-ui`) :8766 — ayrı systemd+tunnel her ikisinde. `py/claudeops/**` (backend) HER worktree'de AYRI edit edilmeli (paylaşılmıyor, "identical dosya" güveni yanıltıcı — [[react-ui-rewrite-unmerged-branch]]); **CLAUDE.md/TODO.md/DONE.md/TOBEDECIDED.md de branch-bazlı BAĞIMSIZ** — her worktree kendi handover geçmişini tutar, birbirini güncellemez. **Kullanıcı yönü net: "react'e devam"** — yeni özellik/fix önceliği react-ui'de, main sadece parite alır. Karar geçmişi: TOBEDECIDED #14.

## Handover (3-fazlı)

- **Faz 1:** `py/cops handover [--dry-run]` — batch'li (mass aynı anda = rate-limit → blank-TUI [[mass-faz1-ratelimit-stuck]]); self (komutun atası) otomatik atlanır. Konuşması olmayan provider'lar (`shell`) `has_conversation()=False` ile otomatik dışlanır — kill edilmezler.
- **Faz 2:** Faz1 sağlıksızsa (503/529) DUR, kullanıcı onayı şart. `py/cops rc <isimler SPACE'li> --new --kill-first --model='claude-sonnet-5' --permission-mode=auto --effort=max --one-by-one` (bash rc DEĞİL). `--prompt` VERME (boş başlasınlar [[faz2-new-session-devam]]). Config doğrula: `python3 -c "import json;json.load(open('$HOME/.claude.json'))"`. Bridge rate-limit: 4'er batch + 20s [[bridge-batch-spawn-ratelimit]].
- **Faz 3:** ÖNCE `loginctl show-session <id> -p LockedHint`=no doğrula [[layout-needs-unlocked-screen]]. `./claudeops layout grid 4 --claude-only --pin=... --group=...` (bash — `py/cops layout` eşdeğerliği CANLI doğrulanıp CLAUDE.md güncellenmedi, TOBEDECIDED.md #12) — 2× çalıştır, `xwininfo` ile doğrula (wmctrl 2× yalan).
- **Skip kriteri:** RFH var + sonrasında yeni istek yok + repo temiz+pushed (github+gitlab).
- Detay: [[handover-procedure]] [[handover-edge-cases]] [[feedback-ho-stop-on-error]] [[config-corruption-resume-hang]]

## Sınırlamalar / açık bug'lar

Wayland: layout çalışmaz. gnome-terminal hard-coded. `rc --kill-first` permission modal keser. Target virgül parse yok (SPACE). Bulk handover sadece 1 item başarılı oluyor (teşhis eklendi, veri bekleniyor); terminal mobil touch-scroll doğrulanmadı. Tam liste + detay: TODO.md.

## Meta

`DONE.md` = CHANGELOG. `TOBEDECIDED.md` = açık mimari sorular (karar verildikçe "Kapatılmış"a taşınır, silinmez). Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
Ho-prep sync (her ho'da): TODO done → DONE.

## READY FOR HANDOVER (2026-09-01)

`main` + `feature/react-ui` ikisi de temiz, github+gitlab senkron. Docs bu ho'da sadece main'de güncellendi (worktree'ler doc geçmişini bağımsız tutuyor, yukarıya bkz.).

**4. provider: codex (OpenAI Codex CLI) eklendi** (`claude`/`agy`/`codex`/`shell`), her iki worktree'de. Mimarinin branch-free kaldığını ikinci kez doğruladı — 2 dosya (yeni provider + registry satırı) yetti. **İnteraktif spawn henüz canlı denenmedi** (panel→gnome-terminal→tmux üzerinden gerçek bir codex konuşması) — sadece provider round-trip + `codex exec` API-seviyesi testler yapıldı.

**İki gerçek bug bulunup düzeltildi + deploy edildi, ama kullanıcı teyidi BEKLİYOR:** (1) cli değiştirip model combosuna dokunmadan başlatınca eski cli'nin modeliyle spawn oluyordu (`_start`/`_new_chat`, her iki worktree — kullanıcının kendi teşhisiyle bulundu: "model secimi combosu değistirilmezse claude kalior"). (2) main panelde açık bir `<select>` varken 4s'lik refresh popup'ı kapatıyordu (react'te sorun yok, kullanıcı canlı doğruladı) — fix sadece main'de.

**Sıradaki session'ın ilk işi:** kullanıcıya iki fix'in gerçekten işe yaradığını (codex artık doğru modelle açılıyor mu, combo artık kapanmıyor mu) sor.

**Canlı:** main+react-ui web/tunnel (4 unit) aktif, bu oturumda restart edildi, dup yok.

READY FOR HANDOVER
