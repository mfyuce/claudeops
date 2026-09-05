# claudeops — Codex Context

claudeops açık CLI agent session'larını (claude/agy/codex/shell) toplu yönetir — sen bu filodaki bir Codex session'ısın. **`py/cops`** = canlı Python tool; **`./claudeops`** (bash) = layout + eski komutlar (silinir mi: TOBEDECIDED.md #12).

Bu dosya `CLAUDE.md`'nin mirror'ı (fleet-geneli gerçekler ortak). `claude`'a özgü satırlar BİLEREK "claude" diye kalıyor (silinmedi/"codex" yapılmadı) — bunlar SENİN değil, filodaki `claude` sibling'lerinin davranışı, onlarla etkileşirken (kill/spawn/resume) bilmen gerekiyor.

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "codex ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı (claude: `-n NAME --remote-control NAME 'PROMPT'`; her provider'ın isimlendirme flag'i farklı olabilir — bkz. `py/claudeops/providers/`).
- **xdotool**: `windowmove` → **`--sync` YOK** (hang).
- **claude KILL=TRUNCATE riski**: `claude`'un lazy-checkpoint storage'ı → onu kill ederken **hep SIGTERM + ~8-10s bekle, sadece canlıysa SIGKILL** (sert kill = son mesajlar gider). [[claude-2183-conversation-truncation]]
- **claude resume "deferred tool marker"**: `claude --resume` promptsuz bazen ANINDA hata verir → resume'a mutlaka `--prompt` ver (`--new` OLMADAN). [[resume-deferred-tool-marker]]
- **spawn güvenilirliği**: `spawn.py` env'den `CLAUDE*`/`GEMINI*`/`ANTIGRAVITY*`-prefixli değişkenleri filtreler (yoksa child'ın transcript kaydı sessizce kapanır) — **`CODEX*` bu listede YOK, doğrulanmadı/eklenmedi** (bkz. TODO.md — codex kendi bir session-id env var'ı set ediyorsa aynı bug codex→codex spawn'da tekrarlanabilir, ama körlemesine eklemek codex'in kendi auth/config'ini de filtreleyip bozabilir, önce doğrulanmalı). gnome-terminal flake → oto-retry+fallback, windowless'i **"pencere aç"**la düzelt. "restart hâlâ olmuyor" → **gt-restart** (Tanı sekmesi). [[spawn-env-leak-disables-transcript]] [[spawn-zombie-child-degrades-web-server]]
- **`service.py`'nin `WEB_UNIT_TEMPLATE`'ini düzenlersen `bash -ic '...'` ExecStart'ı, `KillMode=process`, tunnel unit'inin `Wants=` (`Requires=` DEĞİL) satırını BOZMA** — üçü de canlı hasar fix'i. Tunnel URL rastgele döner + ntfy push telefona ulaşmayabilir — "ulaşamadım" derse `tunnel_url.txt`'ten güncel URL'i doğrudan ver. [[tunnel-flag-shares-live-log-file]] [[tunnel-no-named-tunnel-autoupdate-rotates-url]]
- **oomd TÜM oturumu öldürebilir** — kurtarma `py/cops service watchdog` (root, oturumdan bağımsız). [[oomd-cgroup-kill]]
- **`web.py`'nin `_serve_static()`'i `index.html`'i HER ZAMAN `no-cache`, `/assets/*`'i `immutable` göndermeli** — aksi halde redeploy sonrası eski `index.html` silinmiş hash'li dosyaları 404'lar, sayfa açılmaz.
- **`rust/screenshare` (Uzak Masaüstü) — asla `pkill`/pattern-match ile öldürme** — HER ZAMAN `remote_desktop.stop()`/`.start()`, PID-exact. Input enjeksiyonu var ("Kontrolü Al", varsayılan KAPALI) — GERÇEK fare/klavyeyi fiziksel kullanıcıyla paylaşır (X11 click/scroll imleç KONUMUNA göre yönlenir, focus'a değil), kilitli ekranı şifre yazıp açabilir (kasıtlı). Ctrl/Alt/⌘ kombinasyonları YOK. [[remote-desktop-screenshare-v1]] [[pkill-pattern-kills-live-daemon]]
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Roster / model (`~/.claude/claudeops/{roster,models}.tsv` — repo DIŞI, kaynak-of-truth)

- `claude` session'ları **`claude-sonnet-5`**; `codex` kendi model adlarını kullanır (roster.tsv'nin `cli` kolonuna göre ayrışır). **İsimler base-name** (suffix yok) — `Session.base` tarih+`_N` suffix'lerini indirger (`cops20260824_1`→`cops`); panel eşlemesi önce TAM isim, sonra base.
- **co + cops** (self) + **ulaksec** aktif (guard ayakta tutsun). İsim-bazlı hariç tutma YOK, seçim panel checkbox'larıyla; tek koruma process-bazlı self-koruma (`ancestor_pids()`). [[co-ulaksec-guard-yes-ho-no]]
- Kapalı/emekli satırlar `#`'lı. `py/cops close <name>` = kill + models.tsv yorumla; geri: panel "tekrar işe al".
- roster.tsv'nin opsiyonel **4. kolonu = `cli`** (`claude`|`agy`|`codex`|`shell`, yoksa/eskiyse `"claude"`). `shell` = düz interaktif bash. Provider mimarisi `py/claudeops/providers/`: yeni backend = yeni dosya, dallanma yok.

## Fleet kontrolü — MANUEL (2026-08-24 karar)

- **Guard cron KASITLI kapalı.** Kullanıcı `py/cops web`'den tek tek başlatıyor — **sen açma**, sormadan toplu spawn YAPMA. [[feedback-manual-fleet-control]]
- **`py/cops web [--port 8765] [--tunnel]`** — kontrol paneli; tam sekme/özellik listesi `py/README*.md` + [[diag-tab-feature]].
- **`py/cops service install|status|uninstall|notify|watchdog`** — web+tunnel systemd `--user` ile KALICI. Detay: `py/README*.md`.
- **Repo PUBLIC** (MIT, github + gitlab mirror) — roster/models/token repo dışında. DONE/TODO/changelog kayıtlarını özenli tut.
- Web Stop / `kill` / `rc --kill-first`: ad-bazlı `tmux kill-session` (PID-ancestry YASAK) + `find_outer_bash_pids()` outer-pencereyi de kapatır.

## Handover (Faz 1 = canlı mesaj, kill/respawn YOK — 2026-09-04)

- **Faz 1:** `py/cops handover [--dry-run]` wrap-up mesajını `tmux_send_keys` ile ÇALIŞAN session'a enjekte eder — pencere/proc'a hiç dokunmaz. [[handover-live-injection-no-kill]] `claude` session'ları opus/fable ise mesaj öncesi geçici sonnet'e düşer, sonra geri döner. Batch throttle var (mass aynı anda = rate-limit [[mass-faz1-ratelimit-stuck]]); self otomatik atlanır; konuşması olmayan (`shell`) ve boş/idle session'lar `needs_ho()` ile otomatik skip. **Taze reboot (≤30dk) → DUR + uyar**, `--force` ile baypas ([[reboot-no-handover]]).
- **Faz 2/3 artık Faz 1'in otomatik/örtük devamı DEĞİL** — fresh session (Faz 2) / pencere düzeni (Faz 3) kullanıcının kendi, ayrı kararı.
- **Faz 2 (istenirse):** Faz1 sağlıksızsa DUR, kullanıcı onayı şart. `py/cops rc <isimler SPACE'li> --new --kill-first --permission-mode=auto --one-by-one` (`--model`/`--effort`/`--prompt` VERME — zincirden düşsün [[handover-effort-high-not-max]] [[faz2-new-session-devam]]). Bridge rate-limit: 4'er batch + 20s [[bridge-batch-spawn-ratelimit]].
- **Faz 3 (istenirse):** ÖNCE `loginctl show-session <id> -p LockedHint`=no doğrula [[layout-needs-unlocked-screen]]. `./claudeops layout grid 4 --pin=... --group=...` — 2× çalıştır, `xwininfo` ile doğrula (wmctrl 2× yalan).
- **Skip kriteri:** RFH var + sonrasında yeni istek yok + repo temiz+pushed.
- Detay: [[handover-procedure]] [[handover-edge-cases]] [[feedback-ho-stop-on-error]] [[config-corruption-resume-hang]]

## Sınırlamalar / açık bug'lar

Wayland: layout çalışmaz (X11 gerekli). gnome-terminal hard-coded. `rc --kill-first` permission modal keser. Target virgül parse yok (SPACE, bash'e özel). Tam liste: TODO.md.

## Meta

`DONE.md` = CHANGELOG. `TOBEDECIDED.md` = açık mimari sorular (karar verildikçe "Kapatılmış"a taşınır, silinmez). **Memory (Claude Code'a özgü bir özellik, sende karşılığı yok):** `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/` — `claude` session'larının hafızası, `[[...]]` linkleri buraya işaret ediyor, referans için okunabilir.
Ho-prep sync (her ho'da): TODO done → DONE; `CLAUDE.md` + bu dosya ikisi de güncel mi kontrol et.
