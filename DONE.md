# claudeops — DONE

> Tamamlanan iş kalemleri. Son tarih yukarıda.

## 2026-05-30 (28→29 transition + tek-model geçişi + 1M context + --effort flag)

- ✅ **`rc --effort` flag** (`4e31b4a`) — `--effort low/medium/high/xhigh/max` pass-through eklendi (`effort_arg` → `model_arg`'a append). `claude --effort` CLI flag'ini destekler.
- ✅ **Handover 28→29 (standard)** — 20 session 29-suffix'e geçti, --prompt yok (idle). Faz 3 layout grid 4 --pin=anomaly29,rustrino29.
- ✅ **Tek-model geçişi** — opus/sonnet ayrımı KALDIRILDI. Tüm 20 session tek modelde: `claude-opus-4-8[1m]` (1M context) + `--permission-mode=auto` + `--effort=max`. Faz 2 artık tek `rc` komutu (eski 2 komut: opus grubu + sonnet grubu). CLAUDE.md + handover-procedure memory güncellendi.
- ✅ **1M context mekanizması keşfedildi** — claude binary (v2.1.157) strings analizi: `function TZ(H){return /\[1m\]/i.test(H)}` → model ID'de `[1m]` varsa `Sg=context-1m-2025-08-07` beta header eklenir + context=1e6. Alternatif: `CLAUDE_CODE_MAX_CONTEXT_TOKENS` env var. Model'in `-p` ile self-report'u güvenilmez (200K diyordu). Memory: [[model-1m-context]]. Menüde "Default (recommended) — Opus 4.8 with 1M context" = `claude-opus-4-8[1m]`.
- ✅ **CLAUDE.md büyüklük optimizasyonu** — 83→58 satır. Model-permission konvansiyonu tek-modele güncellendi, eski READY bloğu yenilendi, Self Protection + Bilinen sınırlamalar sıkılaştırıldı.

## 2026-05-28 (handover 26→27→28 + araroot/aggroot eklendi)

- ✅ **Handover 26→27 (TODO-loop)** — 19 session (12 opus + 7 sonnet) 27-suffix'e geçti. Her session'a "TODO.md'deki karar gerektirmeyen tüm iş kalemlerini çöz, 5dk'da bir bak, sadece kullanıcı kararı gerekince dur" prompt'u verildi.
- ✅ **Handover 27→28 (standard)** — 19 session 28-suffix'e geçti, --prompt yok (idle açıldı). Faz 3 layout grid 4 --pin=anomaly28,rustrino28 tamamlandı.
- ✅ **araroot28 + aggroot28 yeni session** — opus grubuna eklendi; araroot ws2 (trroot'un eski slotu), aggroot ws5.
- ✅ **trroot28 kapatıldı** — simdilik; bir sonraki ho'da opus listesinden çıkar.
- ✅ **desktops.local.md** — 26→27→28 geçişleri + yeni sessionlar güncellendi.

## 2026-05-26 (repo_dirty çift-remote fix + handover 25→26)

- ✅ **`repo_dirty` çift-remote + fetch + behind** (`418ebf8`) — eski hâl sadece `@{u}` bakıyordu; çift-remote'lu repolarda (github+gitlab) birine push edilip diğerine edilmemiş "clean" yanılması vardı. Yeni: HER remote için ahead (unpushed) **ve** behind (remote ileride) kontrolü. `repo_fetch_once()` eklendi: pre-check'te session başına 1× `git fetch --all` (timeout 20s, dedup) → ref'ler taze.
- ✅ **idle-only-DIRTY rescue** — Faz 1 skip edilen gedikvm/gedikido/kulturiot'un commitlenmemiş tracked değişiklikleri fetch+ahead/behind ile tespit edildi → fresh respawn + commit prompt CLI-argümanıyla kendi repolarında commitlendi + tüm remote'lara push'landı. Doğrulama: ahead=0 behind=0 her remote'da.
- ✅ **Handover-prep MD sync kuralı** (CLAUDE.md Meta) — her ho'da: (1) TODO'da done → DONE'a taşı+sil; (2) TOBEDECIDED'da karar verilmiş → TODO'ya taşı+sil.
- ✅ **TOBEDECIDED #4 + #6 kapatıldı** — layout default=4 ve github+gitlab ikisine push kararları Kapatılmış bölümüne taşındı.
- ✅ **TODO: Layout in-place** — xdotool no-sync + read-back implement edilmişti (2026-05-25); TODO'dan çıkarıldı.
- ✅ **Handover 24→25 + 25→26** — 19 session (12 opus + 7 sonnet) iki round'da geçti, hepsi idle+auto. idle-only-DIRTY rescue ile kayıp iş yok.
- ✅ **TOBEDECIDED #7** — açık-kaynak durumunda kişiye/makineye özel kısımlar (session listeleri, path'ler, geometri, terminal) lokal kalmalı → karar bekliyor.

## 2026-05-25 (b) (sonnet→auto + layout hız/self-pin + cancel + handover --force)

- ✅ **Sonnet → auto** — sonnet'e de `--permission-mode=auto` geldi; convention "hepsi auto" oldu (model hâlâ ayrı: opus/sonnet). 7 sonnet session auto ile respawn. CLAUDE.md + memory güncel.
- ✅ **Layout hız fix (321s→~3-9s)** — `xdotool windowmove --sync` pencere zaten hedefteyse ConfigureNotify gelmeyince ~15s hang ediyordu (20 pencere=321s). Fix: önce "zaten hedefte mi?" read-back kontrol (idempotent anında döner) + `--sync`'siz move + sleep + verify + retry. Ayrıca desktop-grouped (`_ensure_desktop`: switch sadece ws değişince → switch sayısı=desktop sayısı).
- ✅ **Layout self-pin** — self session (co) artık ws0'a pinleniyor (self_pid→session.json→name). Eski "machine cleaning required" başlık kontrolü hiç eşleşmiyordu → self ws1'e kaçıyordu.
- ✅ **`claudeops cancel <names>`** — RC'yi bloklayan modal'a (permission/model/trust dialog) Esc gönderir (görünür yap+activate+Esc). VTE reject ihtimaline karşı rc --kill-first fallback önerir.
- ✅ **`handover --force`** — skip kontrollerini (already-done/idle-only/dirty) baypas, hepsine gönder. jsonl yoksa fresh-spawn (model/perm /proc/cmdline'dan). Default'ta skip geçerli (kullanıcı: "bu sefer dirty bakmasın hepsine, dahakine baksın").
- ✅ **ho mesajına cross-session satırı** — "paralel/diğer session'larda konuşulup kaydedilmemiş bulgu/karar kaldı mı? kaydet."
- ✅ **`handover --layout [--pin=a,b]`** — tüm wrap-up pencereleri açıldıktan sonra otomatik `layout grid 4` çalıştırır (kullanıcı: "Faz 1 komutları gittikten sonra layout çalışmalı"). Faz 1 + tile tek komutta.
- ✅ **23 forced-ho sonucu** — 19/19 işlendi (force). dirty-check fix değerini kanıtladı: emergence dışında carla23/anomaly23/vrk23 de "idle-only KİRLİ" (limbo iş) çıktı → fresh-spawn + commit prompt'uyla kendileri commit etti. 15 temiz session RFH baseline aldı.

## 2026-05-25 (22→23 transition + handover skip kriteri + layout xdotool fix)

### Handover doğruluk

- ✅ **Skip kriteri yeniden tanımlandı: `handover_done()`** — kullanıcı: "repo temizliği yetmez". Doğru kriter = jsonl'de READY FOR HANDOVER var **VE** son RFH'den sonra yeni user isteği yok **VE** repo temiz+pushed. Üçü birden → güvenle atla. Aksi → wrap-up. jsonl parse (python) ile son-RFH-index vs son-user-istek-index karşılaştırılır.
- ✅ **`repo_dirty()` helper** — idle-only skip artık jsonl yokluğuna değil repo durumuna da bakıyor. jsonl yok + repo KİRLİ → WARN (limbo iş, emrgence vakası), sessiz skip yok.
- ✅ **PRE-CHECK 2 sınıflandırma** — handover öncesi: needs-ho / already-done / idle-clean / idle-DIRTY listesi basılır.
- ✅ **emrgence kurtarma** — 2 gündür commit'lenmemiş 11. tur wrap-up (idle-only döngüsünde limboda). Fresh respawn'da **commit prompt'u CLI argümanı olarak** verilerek (keystroke değil → VTE reject bypass) session kendi commit+push etti (`9be23ae`).

### Layout (kapatmadan in-place)

- ✅ **`_place_win` wmctrl -e → xdotool --sync** — Mutter multi-monitor'da `wmctrl -e` flaky (pencereler ekran dışına/üst üste). Kök neden: xdotool windowmove pencere **görünür (aktif desktop) değilse** yanlış konuma taşıyor. Fix: hedef desktop'a ata + `wmctrl -s` ile SWITCH + `xdotool get_desktop` ile doğrula (Mutter rapid switch coalesce ediyor) + sonra taşı. `_reopen_win` da xdotool'a geçti. Dependency check'e xdotool eklendi.
- ✅ **wmctrl -G güvenilmez** — koordinatları ~2× raporluyor (scale artifact). Gerçek konum doğrulaması `xdotool getwindowgeometry` ile yapılmalı.

## 2026-05-24 (convention genişletme + idle-only handover fix)

- ✅ **gedikvm, gedikido, kulturiot → opus auto convention** — 3 mevcut 21-session (BLM308 veri madenciliği, BLMS431 ileri derin öğrenme, kultur/iot) handover-procedure memory + CLAUDE.md Faz 2 rc örneğine eklendi. Sonraki handover round'undan itibaren dahil. Toplam: opus auto 12 + sonnet acceptEdits 7 + co (self) = 20 (+ sqli SKIP).
- ✅ **Handover Faz 1: idle-only session pre-flight skip** — `--prompt YOK` ile açılan session hiç mesaj almazsa jsonl yazılmaz; kill edilince resume edilemez (`nobridge` fail). Vaka: 21→22 Faz 1'de emrgence21 (20→21'de idle açılmıştı). Fix: cmd_handover pre-check 2 ekledi — `find_jsonl` boşsa session'ı kill etmeden SKIP. Summary'de `skipped=N` ayrı sayılır. Faz 2'deki `rc --new --kill-first` fresh respawn'da otomatik hallolur. Memory: [[handover-edge-cases]].
- ✅ **rc: orphan target warning** — `claudeops rc <name>` ile verilen isim aktif session'larda yoksa sessizce skip ediliyordu. Vaka: 21→22 Faz 2'de emrgence21 rc'ye verildi ama emrgence21 Faz 1'de zaten kill edilmişti → emrgence22 spawn olmadı. Fix: cmd_rc başına WARN ekledi (eşleşmeyen isimleri liste olarak söyler + `claudeops new` önerir). emrgence22 manuel `gnome-terminal ... claude --model opus --permission-mode auto -n emrgence22 --remote-control emrgence22` ile açıldı (memory: [[handover-edge-cases]] case 3).

## 2026-05-23 (20→21 transition + mo migration + migrate komutu)

### Yeni komut / flag

- ✅ **`claudeops migrate <name> --to=<new-cwd>`** — session cwd taşıma + ilgili md/memory dosyalarını taşıma + path rewrite + trust dialog patch + opsiyonel `--gh`/`--glab` ile private remote yaratma + respawn (model/permission-mode /proc/<pid>/cmdline'dan inherit).
- ✅ **`claudeops handover --exclude=name1,name2`** — handover'dan belirli session'ları skip. 2026-05-23 20→21 transition'ında trroot dahil edilmedi sonra dahil edildi senaryosunda kullanıldı.

### Operasyon

- ✅ **mo session /home/fatihyuce → /home/fatihyuce/work/projects/tmp/machine_ops** — yeni cwd, github + gitlab private remote, CLAUDE.md/howtos.md/sessions-snapshot.md taşındı, memory dosyalarındaki path'ler güncellendi, trust patch + .claude.json backup.
- ✅ **20→21 transition** — Faz 1: 17 wrap-up (hms20+hve20 manuel önce, sonra 15 handover-komutu, trroot dahil), Faz 2: 16 fresh respawn (sqli SKIP, **--prompt YOK** kullanıcı tercihi → idle açıldılar), Faz 3: layout grid 4 --pin=anomaly21,rustrino21. sqli20 wrap-up sonrası kapatıldı.
- ✅ **hve20 recovery** — handover sırasında TaskStop ile yarıda kalan hve20 (kill edildi, yeni TUI açılamadan) manuel `gnome-terminal --window ... claude --resume <sid> --remote-control hve20 '<HANDOVER_MSG>'` ile wrap-up'a yeniden alındı.

### Kararlar

- ✅ **Faz 2 respawn'da `--prompt` opsiyonel olabilir** — kullanıcı 2026-05-23'te "devam yazmayalim, sadece acilsin" dedi. Yeni session'lar idle açıldı, kullanıcı manuel prompt verecek.
- ✅ **sqli21 SKIP** — kullanıcı "sqli simdilik bir daha acilmasin" → Faz 2'ye girmedi, sqli20 wrap-up sonrası kill edildi (`./claudeops kill sqli20`).

## 2026-05-17/18 (yoğun iterasyon — production tests)

### Kritik fix'ler

- ✅ **CLAUDE_CODE_SESSION_ID env var self-protection** — nohup-detached script $$ ata zincirinde claude bulamıyordu, filter_not_self no-op → SELF KILL incident'i (pid 78492 öldü, harness 1506400 olarak rebirth). Fix: env var ile sessionId match (`find_self_claude_pid`'in birinci preferred mekanizması)
- ✅ **`-n NAME + --remote-control NAME` combo** — `--remote-control devam` "devam"ı RC name yapıyordu (claude.ai mobilde "devam" gözüküyordu). Doğru syntax: `-n NAME --remote-control NAME 'prompt'` üçü ayrı. Session display name, RC bridge name, initial prompt.
- ✅ **Pre-busy-wait safety in rc --kill-first** — handover mid-process'te kill ile 7 repo uncommitted state'te yarım kaldı. Fix: kill-first ile target busy'lere idle olana kadar bekle (60dk timeout). cmd_handover'a da var.
- ✅ **xdotool windowactivate + type + key Return** — initial prompt auto-submit ve permission prompts için. `--clearmodifiers` + sync. Permission prompt'lar kısmen sorunlu (VTE/Ink synthetic keypress reject), type devam+Enter genelde çalışıyor.
- ✅ **gnome-terminal-server pid match fix** — `pgrep -x gnome-terminal-server` boş döner (comm 15-char truncate). Doğrusu `ps -eo pid,comm | awk '$2 == "gnome-terminal-"'`. cmd_cleanup + cmd_layout düzeltildi.
- ✅ **wmctrl -s gerçek visual desktop switch** — xprop -root _NET_CURRENT_DESKTOP sadece property set ediyor (Mutter görsel uygulamıyor). wmctrl -s ClientMessage yolu ile Mutter visible switch yapıyor.
- ✅ **claude.ai/projects path encoding** — `_` ve `/` ikisi de `-` olarak encoded. tr '/_' '-'.

### Yeni flag'ler / komutlar

- ✅ `--prompt=<text>` (rc komutu) — initial prompt için
- ✅ `--model=<sonnet|opus>` (rc/handover) — per-session model seçimi
- ✅ `--permission-mode=<auto|acceptEdits|...>` (rc/handover)
- ✅ `--sticky=<csv>` (rc) — açılan pencereleri sticky yapar
- ✅ `--desktop=<name>:<n>,...` (rc) — open sonrası belirli desktop'a
- ✅ `handover` komutu — kill+wrap-up+respawn zinciri (visible mode default, RC + tool onayı için)
- ✅ `layout --reopen` flag — Mutter in-place desktop change buggy olduğunda kill+switch+reopen on target desktop (proven recipe)
- ✅ `--include-sticky` / sticky-skip default — sticky pencerelere layout default'ta dokunmaz

### Kararlar (TOBEDECIDED → kapatıldı)

- ✅ **Opus → --permission-mode=auto** (classifier-based, esnek)
- ✅ **Sonnet → --permission-mode=acceptEdits** (Edit/Write auto, Bash hâlâ onay ister)

### OCR + screenshot

- ✅ tesseract 4.1 + ImageMagick (sudo apt gerekmedi, varolan) ile permission prompt'ları OCR ile okuma kanıtlandı
- ✅ `import -window $WID /tmp/out.png` + `tesseract /tmp/out.png stdout` çalışıyor
- Keystroke auto-submit hâlâ blocker (TODO)

### Production tests (2026-05-17/18)

- ✅ 14 session compact pipeline (sequential, sıfır kayıp, jsonl backup'lı, isCompactSummary marker ile doğrulamalı)
- ✅ Birden çok handover round + 13→14→15 transition cycles
- ✅ Layout grid 4 --reopen --pin=rustrino+anomaly (test edildi, çalışıyor — Mutter snap'ten kurtaran tek yol)
- ✅ desktops 5 + 2×2 grid + pin (kullanıcı eDP primary'de 1680×1050 quadrants)
- ⚠️ Geometry occasionally fails on multi-monitor (HDMI'a düşüyor) — kullanıcı ekran kilidi hipotezi öne sürdü (TODO)
- ⚠️ Permission prompt auto-respond hâlâ manuel (RC URL'den telefonla) — xdotool keystroke landing'i intermittent

## 2026-05-17 (ilk versiyon)

### Script

- ✅ `claudeops` tek dosya bash script (~400 satır)
- ✅ Self protection: `find_self_claude_pid` via `$$` ata zinciri
- ✅ Komutlar: `self`, `list`, `kill`, `compact`, `rc`, `send`, `batch`, `desktops`, `layout`, `new`, `cleanup`, `help`
- ✅ Hedef syntax: `all`, `all-but-self`, `<name1> <name2>...`
- ✅ Compact için `< /dev/null` zorunlu (stdin leak fix'i)
- ✅ Compact başarı doğrulaması (isCompactSummary marker count)
- ✅ Rate-limit tespit + otomatik durma
- ✅ RC visible (gnome-terminal) + detached (script -qfc) mode'ları
- ✅ `--kill-first` flag mevcut session'ı kapatıp resume
- ✅ `--rename=<name>` ve `--suffix=<n>` (toplu rename: <name>13→<name>14)
- ✅ `--new` flag (yeni boş session)
- ✅ `layout` 2×2 grid, primary monitor, pinned-on-desktop-0 (`--pin=`)
- ✅ `desktops <N>` gsettings ile workspace count
- ✅ `cleanup` orphan bash pencereleri kapatır
- ✅ `compact --visible` gnome-terminal penceresinde canlı görünür

### Dokümantasyon

- ✅ `README.md` — usage + bug'lar + fix'ler
- ✅ `CLAUDE.md` — proje context (gelecek session'lar için)
- ✅ `TODO.md` — açık işler
- ✅ `TOBEDECIDED.md` — kullanıcı kararı bekleyenler
- ✅ `DONE.md` — bu dosya

### Gerçek dünya kanıtı (script doğmadan önce manuel yapıldı, sonra script'leştirildi)

- ✅ **14/14 Claude session compact** (sequential, ~25dk, sıfır kayıp; tüm backup'lar diskte)
- ✅ **13/14 RC reopen** (home13 = bu konuşma kabul edildi, skip)
- ✅ **14 görünür gnome-terminal pencere** (compact + RC + bash exec ile pencere kalıcılığı)
- ✅ Bug bulundu+fix'lendi: stdin leak'i ("/compact" sonrası TSV içeriği sızıyordu)
- ✅ Self-protection mekanizması test edildi (`pid 78492` bu konuşma, dokunulmadı)

### Snapshot

- `~/sessions-snapshot.md` — 2026-05-16 akşamı tüm session envanteri
- `~/howtos.md` — RC enable + kompakt-via-resume recipe (claudeops bu öğrenilenlerin script hali)
