# claudeops — TODO

> Açık iş kalemleri. Tamamlananlar `DONE.md`'ye taşınır.

## Kritik bug'lar (devam)

- [ ] **BUG: `rc <a,b,c>` virgül-separated isim listesi parse edilmiyor** — 2026-05-19'da 15→16, 2026-05-23'te 20→21 transition'larında doğrulandı. `cmd_rc`/`resolve_targets` SPACE-separated bekliyor. CLAUDE.md eski örnekler virgüllü idi → güncellendi. Fix: cmd_rc başında target ve "$@" içindeki virgüllü string'leri split et (IFS=','). Aynı bug `cmd_kill`, `cmd_compact`, `cmd_send` için de var.
- [ ] **`claudeops layout` orphan terminal kaldırmıyor** — 2026-05-19/05-23/05-25 transition'larında doğrulandı (ws1'de "fatihyuce@483-LNX: ~" bir quad slot işgal ediyor). Fix: layout iterasyonunda window-name'in geçerli session.json'da olup olmadığını kontrol et + yoksa skip (oth_wins'e ekleme).
- [ ] **`cancel` Esc güvenilmez (VTE reject)** — 2026-05-25 kulturiot23 "waiting" modal'da Esc inmedi. Garantili iptal = respawn. Fix: cancel Esc dene → 2s sonra hâlâ takılıysa otomatik `rc <name> --kill-first` öner/yap (flag ile).
- [ ] **`handover --exclude=<name>` filtrelemiyor** — 2026-06-08 (*36→*37) `--exclude=anomaly` (base-name) verildi ama anomaly36 yine wrap-up edildi (pre-check sınıflandırmasında HO listesinde kaldı). Muhtemelen exclude suffix'li tam isim (`anomaly36`) bekliyor ya da parse hiç çalışmıyor. Fix: `cmd_handover` exclude eşleşmesini base-name + suffix'li ikisini de kabul edecek şekilde düzelt (handover hedef döngüsünde isim normalize).
- [ ] **KRİTİK (j kaldı): rc guard.lock'u KAYIT bitene kadar tutsun** (TODO-j, 2026-06-09 *37→*38) — ~~(h) `exec 9>guard.lock; flock 9` `cmd_rc` başında YAPILDI (2026-06-17, `93f99df`)~~. (j) hâlâ açık: spawn bitince lock serbest bırakılıyor ama RC bridge kaydı dakikalarca sürebiliyor → guard yarışıp dup açabiliyor. Fix: spawn'lardan sonra **beklenen N session `list`'te kayıtlı olana kadar poll** (timeout ~5dk), SONRA `flock -u`. Memory [[handover-edge-cases]] edge-9.
- [ ] **handover Faz1 bridge-verify NAME eşlesin (sid değil)** (TODO-k, 2026-06-09) — `cmd_handover` reopen sonrası bridge-verify `sessionId==$sid` (eski sid) arıyor (~satır 1372); `claude --resume` sid fork edince eşleşmez → `nobridge` log + session aslında AÇIK (false negative). Fix: has_jsonl=1 resume'da da sadece `name==$name` eşle (fresh-spawn'daki gibi), sid şartını kaldır.
- [ ] **rc/handover: spawn sonrası RC-kayıt yavaş → kaydı doğrula sonra dön** (TODO-l, 2026-06-09) — rc'nin `=== bridge check ===` adımı *38'de BOŞ döndü (kayıt henüz olmamıştı); yine de "bitti" deyip döndü. Fix: bridge-check'i kayıt tamamlanana kadar (poll + timeout) beklet; eksik kalanları WARN'la. (Yukarıdaki guard.lock-tutma fix'iyle birlikte.)
- [ ] **cron/boot recovery: artefakt jsonl'i atla, "en son GERÇEK konuşma"yı aç** (TODO-o, 2026-06-18, KRİTİK) — `_latest_sid_for_cwd` (guard satır ~2013 + boot ~1864 kullanıyor) **en yeni mtime**'ı seçiyor. Reboot sonrası bu YANLIŞ: boot SONRASI oluşan boş/thin spawn-artefaktı (ör. ilk-user="session", 0 gerçek user mesajı) en yeni mtime'a sahip olup gerçek 808-satırlık pre-boot konuşmanın önüne geçiyor → session boş context'le açılıyor (2026-06-18 mo50: 1e6e54b7=808 satır orphan, 2d85e4b1=35 satır fresh açıldı). **Fix:** aday jsonl "artefakt" ise atla — artefakt = **hiç gerçek user turn'ü yok** (system-reminder + wrap-up promptu + tek-kelime "session" hariç substantive free-text user mesajı 0). Aday kalmazsa mevcut davranışa düş. Alternatif/ek: `uptime -s` boot-anchor — reboot-recovery'de sadece `mtime < boot` adayları al (steady-state guard'da post-boot işi resume etmeli, o yüzden boot-anchor SADECE boot-yakını pencerede). Kullanıcı kuralı (2026-06-18): "restart oldu → cron en son nerede ise ordan başlasın, ho olsun olmasın; restart-anındaki konuşma neyse o." ⚠ Steady-state'te (session mid-work crash) en son = post-boot olabilir → artefakt-skip boot-anchor'dan daha güvenli (ikisinde de çalışır). İlgili [[reboot-no-handover]].
- [ ] **handover co + ulaksec'i base-name ile hard-exclude etsin** (TODO-n, 2026-06-18) — co + ulaksec models.tsv'de aktif (guard crash-recovery'de ayakta tutsun — İSTENEN davranış, kullanıcı 2026-06-18). AMA handover ASLA dokunmamalı. Eskiden co/ulaksec fleet'ten farklı suffix'te (co43 vs fleet49) olduğu için doğal atlanıyordu; guard die olunca onları **fleet suffix'ine bumplıyor** (co43→co50, ulaksec43→ulaksec50, çünkü guard `base+suffix` çalışmıyorsa resume eder). Artık `handover --from-suffix=50` co50+ulaksec50'yi eşler: co50 `filter_not_self` ile atlanır (self güvende) ama **ulaksec50 self değil → ho listesine girer = "dokunma" ihlali**. Fix: `cmd_handover`'da sabit `HO_EXCLUDE="co ulaksec"` base-name listesi, `filter_not_self`'ten sonra base-name (suffix-stripli) eşleşeni rows'tan düş. (TODO-d `--exclude` base-name parse'ıyla birleşebilir.) Kök sebep ayrıca: guard cwd-tespiti *50 cutover yoğunluğunda co43/ulaksec43'ü bir an ıskaladı → bumpladı.
- [ ] **handover `sid=-` → cwd-based jsonl fallback** (TODO-m, 2026-06-17) — `find_jsonl "$sid"` `sid=-` olunca boş dönüyor → `jsonl=no` → `needs_ho` SKIP → iş yapan yeni session'lar (sase49, marwan49 vb.) Faz 1'den atlıyor. Fix: `sid` boş/`-` ise cwd'den encode edilmiş proje path'ini türet → `~/.claude/projects/<encoded>/` altındaki en yeni `.jsonl`'ı kullan; encoding `add-session-to-fleet` kuralına uy (`/`→`-`, `_`→`-`). Etkilenen: `find_jsonl`, `needs_ho` sinyal tablosu, `handover_done`, `cmd_handover`'daki `--resume $sid` satırı.

- [ ] **config-corruption: eşzamanlı `~/.claude.json` yazması config'i BOZUYOR** (2026-06-13, [[config-corruption-resume-hang]]) — toplu handover/respawn'da onlarca claude config'e aynı anda yazınca **truncated JSON** → `claude --resume` startup'ta **BLANK-TUI hang** (fresh `--new` çalışır → yanıltıcı; teşhis `claude --resume <sid> -p x --debug`). Manuel fix: `~/.claude/backups/`'tan en yeni VALID backup'ı restore. **KOD FİX:** handover/rc respawn'larını **serialize et** (tek-tek, her birinden sonra bridge-kaydını bekle) + her adımda `python3 json.load(~/.claude.json)` config-check → bozulursa DUR + backups'tan auto-restore. (TODO-h+j lock-tutma ile birleşik.) ⚠ Done-tespiti: jsonl-stale **≥150s** (60s erken — session iş ortasında 60s+ duraklıyor → çakışma); `status` lag'liyor; en güvenilir done = kullanıcı-gözü. Ek tuzaklar: `import -window` (Mutter) stale-buffer YANILTICI; `ps|grep|kill`/`pkill -f` komut-metni session-adı içerince **kendi shell'ini ($$) öldürür** → `$$` hariç tut / PID ile.

## Geliştirme

- [ ] **`deep-ho` komutu (yeni, ayrı cmd)** — 2026-06-01 istek. Normal `ho` sadece wrap-up (commit/push + MD güncel mi) sorar. `deep-ho` ek olarak: her CLI/session'ın TÜM jsonl geçmişini okuyup "kaçırdığımız bir şey var mı?" analizini yaptırır (yarım kalan iş, kaydedilmemiş karar, eksik test/doküman, TODO'ya yazılmamış fikir). Tek komut hem `ho` hem `deep-ho` fazını çalıştırabilmeli (`ho --deep` veya `deep-ho` ayrı dispatch). Her session'a daha uzun/derin bir wrap-up prompt'u gider; çıktı per-session özet + co'ya toplanır.
- [ ] **`boot`/`recover` `models.tsv` lookup** — 2026-06-01 model-split'e dönüldü (`~/.claude/claudeops/models.tsv` name→model), AMA `cmd_boot` hâlâ `BOOT_MODEL_DEFAULT` tek opus kullanıyor. Split kalıcıysa boot her session'ı models.tsv'deki modeliyle açmalı (yoksa default). Aynı şekilde handover Faz-2 elle 2-grup'a bölünüyor → ileride `rc --from-models-tsv` ile tek komut respawn (her isme kendi modeli) düşünülebilir.
- [ ] **`--model` verince default `--permission-mode=auto`** — 2026-05-25: artık HEPSİ auto (sonnet de). Yani mapping basitleşti: `--model=opus|sonnet` verilince permission-mode otomatik `auto` olsun (explicit verilirse override). Şu an her çağrıda elle `--permission-mode=auto` yazılıyor.
- [ ] **Python UI (büyük)** — claudeops için GUI: session listesini göster, tıkla → compact/RC/kill/send butonları, layout görsel önizleme. Stack TBD (PySide6 / Textual / Web). Ana motivasyon: CLI yerine UI.
- [ ] **`claudeops history` + `claudeops launch <name|sid>`** — geçmişte açık olan TÜM session'ları registry'le, `launch` ile yeni gnome-terminal'de RC açar.
- [ ] **`--models=name:model,...` per-name config** — manuel name→model map. Şu an model PLAN array'de gömülü, hatalara açık.
- [ ] **Spawn geometry: ekran kilidi hipotezi** — 2026-05-17 spawn'da pencereler HDMI'da rows olarak yerleşti (eDP 2×2 değil). Hipotez: ekran kilitliyse Mutter farklı davranıyor. Pre-flight lock check + defer placement.
- [ ] **Auto-respond permission prompts** — OCR çalışıyor (tesseract), keystroke landing intermittent. Seçenekler: OCR + RC API inject, ydotool (Wayland), claude TUI `--auto-accept` flag.
- [ ] Wayland desteği için layout fallback (gdbus + Mutter extension veya hint)
- [ ] Terminal emülatör parametrize (gnome-terminal yerine kitty/alacritty config/env)
- [ ] Rate-limit reset zamanını output'tan parse + auto-resume
- [ ] `claudeops batch --dry-run`
- [ ] `claudeops list --json` machine-readable
- [ ] `claudeops send` stdin'den prompt okuma
- [ ] `claudeops layout` için "BR köşede her zaman boş bırak" benzeri kural
- [ ] **handover `--layout` oto-tile `--group` geçirmiyor** — tek-komut `handover --force --layout` yolunda grup'lar uygulanmaz (ayrı Faz 3 komutu --group içeriyor). Fix: `cmd_handover`'a `--group=` passthrough → `cmd_layout`'a ilet. (2026-05-31, --group eklenince fark edildi.)
- [ ] **`layout --group` desktop no'su serbest-other sayısına bağlı** — 16 serbest-other → grup ws4/5; sayı değişirse kayar (gruplar yine birlikte ama ws no farklı). Sabit istenirse `--group=names@ws` hedefleme ekle (others o ws'i atlar). (2026-05-31)

## Dokümantasyon

- [ ] README'ye actual workflow örnekleri (güncel session isimleri)
- [ ] CLAUDE.md'ye "ne zaman compact" rehberi
- [ ] Demo gif/video — visible mode reopen sırası

## Test/Quality

- [ ] Unit test: `find_self_claude_pid` (claude değil bash'tan çağrılınca)
- [ ] Smoke test: tek session aç, kill, compact, RC, doğrula
- [ ] Edge case: 0 session açıkken komut davranışı

## Açık sorular

- [ ] gnome-terminal `--title` flag'i claude TUI tarafından override mı?
- [ ] `--remote-control` flag'i `--name` ile çakışıyor mu? (RC name session name'i de set ediyor görünüyor)
