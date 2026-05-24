# claudeops — DONE

> Tamamlanan iş kalemleri. Son tarih yukarıda.

## 2026-05-24 (convention genişletme)

- ✅ **gedikvm, gedikido, kulturiot → opus auto convention** — 3 mevcut 21-session (BLM308 veri madenciliği, BLMS431 ileri derin öğrenme, kultur/iot) handover-procedure memory + CLAUDE.md Faz 2 rc örneğine eklendi. Sonraki handover round'undan itibaren dahil. Toplam: opus auto 12 + sonnet acceptEdits 7 + co (self) = 20 (+ sqli SKIP).

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
