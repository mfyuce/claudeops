# claudeops — Claude Context

Açık Claude CLI session'larını toplu yönet. **`py/cops`** = canlı Python tool; **`./claudeops`** (bash) = layout + eski komutlar (silinir mi: TOBEDECIDED.md #12).

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. Aynı sid resume → cache'li, değiştirmek için `--new`.
- **xdotool**: `windowmove` → **`--sync` YOK** (hang).
- **claude KILL=TRUNCATE riski**: lazy-checkpoint storage → **hep SIGTERM + ~8-10s bekle, sadece canlıysa SIGKILL** (sert kill = son mesajlar gider, iş git'te güvende). [[claude-2183-conversation-truncation]]
- **claude resume "deferred tool marker"**: promptsuz `--resume` bazen ANINDA hata verir → resume'a mutlaka `--prompt` ver (`--new` OLMADAN). [[resume-deferred-tool-marker]]
- **spawn güvenilirliği**: CLAUDE*/GEMINI*/ANTIGRAVITY* env filtrelenir (yoksa transcript kapanır). gnome-terminal flake → oto-retry+fallback, windowless'i **"pencere aç"**la düzelt. "restart hâlâ olmuyor" → **gt-restart** (Tanı sekmesi, web'den bağımsız). [[spawn-env-leak-disables-transcript]] [[spawn-zombie-child-degrades-web-server]]
- **`service.py`'nin `WEB_UNIT_TEMPLATE`'ini düzenlersen `bash -ic '...'` ExecStart'ı, `KillMode=process`, tunnel unit'inin `Wants=` (`Requires=` DEĞİL) satırını BOZMA** — üçü de canlı hasar fix'i (PATH kaybı / restart altındaki tmux'u öldürme / tunnel URL rotasyonu). Tunnel URL rastgele döner (named tunnel kurulu değil) + ntfy push telefona ulaşmayabilir — biri "ulaşamadım" derse `tunnel_url.txt`'ten güncel URL'i doğrudan ver. [[tunnel-flag-shares-live-log-file]] [[tunnel-no-named-tunnel-autoupdate-rotates-url]]
- **oomd TÜM oturumu öldürebilir** (sadece fleet'in cgroup'unu değil) — kurtarma `py/cops service watchdog` (root, oturumdan bağımsız). [[oomd-cgroup-kill]]
- **`web.py`'nin `_serve_static()`'i `index.html`'i HER ZAMAN `no-cache`, `/assets/*`'i (Vite hash'li) `immutable` göndermeli** — aksi halde redeploy sonrası tarayıcıda kalan eski `index.html`, silinmiş eski-hash'li JS/CSS'i 404'lar, sayfa hiç açılmaz.
- **`rust/screenshare` (Uzak Masaüstü) — asla `pkill`/pattern-match ile öldürme** (port/isim eşleşmesi canlı/panelde-kullanılan instance'ı vurabilir, 2026-09-04 canlı yaşandı) — HER ZAMAN `remote_desktop.stop()`/`.start()`, PID-exact. **v2'den itibaren input enjeksiyonu var** ("Kontrolü Al", varsayılan KAPALI) — GERÇEK fare/klavyeyi fiziksel kullanıcıyla paylaşır (X11 click/scroll imleç KONUMUNA göre yönlenir, klavye focus'una değil — eşzamanlı fiziksel kullanım çakışabilir, canlı doğrulandı), kilitli ekranı şifre yazıp açabilir (kasıtlı/beklenen). Ctrl/Alt/⌘ kombinasyonları YOK (stuck-modifier riski, bilerek). [[remote-desktop-screenshare-v1]] [[pkill-pattern-kills-live-daemon]]
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Roster / model (`~/.claude/claudeops/{roster,models}.tsv` — repo DIŞI, kaynak-of-truth)

- Tüm isimler **`claude-sonnet-5`**. **İsimler base-name** (suffix yok) — `Session.base` tarih+`_N` suffix'lerini indirger (`cops20260824_1`→`cops`); panel eşlemesi önce TAM isim, sonra base.
- **co + cops** (self) + **ulaksec** aktif (guard ayakta tutsun). İsim-bazlı hariç tutma YOK, seçim panel checkbox'larıyla; tek koruma process-bazlı self-koruma (`ancestor_pids()`). [[co-ulaksec-guard-yes-ho-no]]
- Kapalı/emekli satırlar `#`'lı. `py/cops close <name>` = kill + models.tsv yorumla; geri: panel "tekrar işe al".
- roster.tsv'nin opsiyonel **4. kolonu = `cli`** (`claude`|`agy`|`codex`|`shell`, yoksa/eskiyse `"claude"`). `shell` = düz interaktif bash. Provider mimarisi `py/claudeops/providers/`: yeni backend = yeni dosya, dallanma yok (adaylar TODO.md'de).

## Fleet kontrolü — MANUEL (2026-08-24 karar)

- **Guard cron KASITLI kapalı.** Kullanıcı `py/cops web`'den tek tek başlatıyor — **sen açma**, sormadan toplu spawn YAPMA. [[feedback-manual-fleet-control]]
- **`py/cops web [--port 8765] [--tunnel]`** — kontrol paneli; tam sekme/özellik listesi `py/README*.md` + [[diag-tab-feature]].
- **`py/cops service install|status|uninstall|notify|watchdog`** — web+tunnel systemd `--user` ile KALICI (`notify`=URL değişince ntfy push, `watchdog`=oomd-tüm-oturum kurtarma, root ister). Detay: `py/README*.md`.
- **Repo PUBLIC** (MIT, github + gitlab mirror) — roster/models/token repo dışında. DONE/TODO/changelog kayıtlarını özenli tut.
- Web Stop / `kill` / `rc --kill-first`: ad-bazlı `tmux kill-session` (PID-ancestry YASAK — paylaşımlı server riski) + `find_outer_bash_pids()` session ölmeden ÖNCE yakalanan outer-pencere PID'lerini de kapatır.

## Handover (Faz 1 = canlı mesaj, kill/respawn YOK — 2026-09-04)

- **Faz 1:** `py/cops handover [--dry-run]` wrap-up mesajını `tmux_send_keys` ile ÇALIŞAN session'a enjekte eder — pencere/proc'a hiç dokunmaz. [[handover-live-injection-no-kill]] Model opus/fable ise mesaj öncesi geçici sonnet'e düşer, mesajdan sonra geri döner (sonnet/haiku zaten dokunulmaz). Batch throttle var (mass aynı anda = rate-limit [[mass-faz1-ratelimit-stuck]]); self otomatik atlanır; konuşması olmayan (`shell`) ve boş/idle session'lar `needs_ho()` ile otomatik skip. **Taze reboot (≤30dk) → DUR + uyar**, `--force` ile baypas ([[reboot-no-handover]]).
- **Faz 2/3 artık Faz 1'in otomatik/örtük devamı DEĞİL** — fresh session (Faz 2) / pencere düzeni (Faz 3) kullanıcının kendi, ayrı kararı.
- **Faz 2 (istenirse):** Faz1 sağlıksızsa (503/529) DUR, kullanıcı onayı şart. `py/cops rc <isimler SPACE'li> --new --kill-first --permission-mode=auto --one-by-one` (bash `rc` DEĞİL; `--model`/`--effort`/`--prompt` VERME — models.tsv/Ayarlar zincirine düşsün, boş başlasınlar [[handover-effort-high-not-max]] [[faz2-new-session-devam]]). Config doğrula: `python3 -c "import json;json.load(open('$HOME/.claude.json'))"`. Bridge rate-limit: 4'er batch + 20s [[bridge-batch-spawn-ratelimit]].
- **Faz 3 (istenirse):** ÖNCE `loginctl show-session <id> -p LockedHint`=no doğrula [[layout-needs-unlocked-screen]]. `./claudeops layout grid 4 --claude-only --pin=... --group=...` — 2× çalıştır, `xwininfo` ile doğrula (wmctrl 2× yalan).
- **Skip kriteri:** RFH var + sonrasında yeni istek yok + repo temiz+pushed.
- Detay: [[handover-procedure]] [[handover-edge-cases]] [[feedback-ho-stop-on-error]] [[config-corruption-resume-hang]]

## Sınırlamalar / açık bug'lar

Wayland: layout çalışmaz (X11 gerekli). gnome-terminal hard-coded. `rc --kill-first` permission modal keser. Target virgül parse yok (SPACE, bash'e özel). Tam liste: TODO.md.

## Meta

`DONE.md` = CHANGELOG. `TOBEDECIDED.md` = açık mimari sorular (karar verildikçe "Kapatılmış"a taşınır, silinmez). **`AGENTS.md` = bu dosyanın Codex-CLI mirror'ı — biri değişince İKİSİNİ birlikte güncelle** (2026-09-04'te stale + birkaç mekanik-yanlış çeviri bulunup düzeltildi, örn. model id'nin "Codex-sonnet-5" olarak değişmiş olması — Claude'a özgü somut gerçekler AGENTS.md'de de Claude'a özgü kalmalı, sadece çerçeveleme Codex'e uyarlanır). Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
Ho-prep sync (her ho'da): TODO done → DONE; CLAUDE.md + AGENTS.md ikisi de güncel mi kontrol et.

## READY FOR HANDOVER (2026-09-04)

Uzak Masaüstü v2 (mouse/klavye/scroll input, "Kontrolü Al") TAMAMLANDI + CANLIYA DEPLOY EDİLDİ. Rust tarafı izole testte doğrulandı (Türkçe Unicode dahil, prod porta dokunulmadan); frontend (Pointer Events tabanlı capture, koordinat ölçekleme, mobil-klavye tetikleyici, varsayılan-KAPALI güvenlik anahtarı) yazıldı, `tsc`/`oxlint` temiz, `npm run build` ile canlıya alındı (restart gerekmedi, tunnel URL'inden doğrulandı). Test sırasında gerçek bir güvenlik bulgusu çıktı: X11'de scroll/click imleç KONUMUNA göre yönleniyor (klavye focus'una değil) — makine eşzamanlı aktif kullanımdayken bu, fiziksel kullanıcıyla çakışabiliyor; bu yüzden "Kontrolü Al" varsayılan kapalı ve her aksiyondan önce taze `move` gönderiyor.

**Kullanıcı ofisten çıkıp panele uzaktan bağlanıp gerçek bir tarayıcıda deneyecek — bu handover anında SONUÇ BİLİNMİYOR.** Bir sonraki session önce sorup öğrenmeli, "çalışıyor" varsaymamalı; bir hata bildirilirse TODO.md'deki ilgili maddeden devam et.

Ayrıca bu turda: CLAUDE.md boyutu küçültüldü (moot/tarihsel yorumlar budandı, eski RFH bloğu kaldırıldı) + repoda stale/kısmen-yanlış bir `AGENTS.md` (Codex-CLI'nin okuduğu mirror dosya) bulunup düzeltildi — ikisini birlikte güncel tutma kuralı Meta'ya eklendi. TODO.md'de iki staleness düzeltildi: codex provider'ının zaten eklenmiş olduğu (eski madde hâlâ "eklenmedi" diyordu) ve `spawn.py`'nin env-filtresinin `CODEX*` içermediği (doğrulanmamış bir risk, körlemesine eklenmedi).

**Repo:** clean, github+gitlab senkron (bu commit dahil).

READY FOR HANDOVER
