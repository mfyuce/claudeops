# claudeops — TOBEDECIDED

> Kullanıcı kararı bekleyen açık sorular. Karar verildikçe sil + DONE.md'ye yaz.

## Açık

### 8) claudeops'u Python/Rust'a taşı — >2000 satır bash sürdürülemez (2026-06-21, kullanıcı: "bence olmaz")
- **Bağlam:** Tek-dosya bash CLI **>2000 satır**. Bu gece bash'in kırılganlığı canlı yaşandı: (1) **truncation** kill-timing inceliği (SIGTERM→SIGKILL grace); (2) **quoting/pattern bug'ları** runtime'da (proc-match `(\s|$)` anchor, trailing-space tuzağı); (3) **virgül-parse** bug (target SPACE şart, TODO-a); (4) her yere serpilmiş kırılgan `python3 -c "..."` inline (json/proc/sid parse) — zaten Python'a yarı-bağımlı. Tip yok, test yok → her değişiklik canlı 27-session fleet'te risk.
- **Seçenekler:**
  - **Python (pragmatik):** en kolay port yolu (zaten her yerde `python3 -c`); `psutil` (proc/kill — `ps|grep` cımbızını bitirir), `subprocess`, `argparse`, `json` native. Hızlı iterasyon. Runtime dep zaten var. Eksi: dinamik tip (yine de bash'ten kat kat sağlam).
  - **Rust (sağlamlık):** tek statik binary, **tip-güvenliği quoting/parse bug sınıfını öldürür**, `sysinfo`/`nix` ile robust proc, hızlı. Eksi: büyük port eforu, yavaş iterasyon, glue-tool için overkill; gnome-terminal/xdotool/cron yine shell-out.
  - **Bash kal + modülerleştir:** source'lu dosyalara böl + test ekle. En ucuz ama temel kırılganlığı çözmez.
- **Yaklaşım:** **Incremental** (komut-komut port, bash entry shim korunur, davranış birebir, canlıya karşı test) >> big-bang rewrite — çünkü **CANLI** araç (27 session + guard cron `*/2` bağımlı), göçerken fleet'i bozmamalı.
- **Lean:** Python (port eforu düşük + en büyük acıyı — json/proc/quoting — çözer). Rust ancak uzun-vade dağıtım/sağlamlık iterasyondan önemliyse.
- **Karar:** ? (dil + incremental mı rewrite mi + ne zaman)

### 7) Fleet ÇOK BÜYÜK → küçült/hafiflet? (2026-06-21, gecenin ana çıkarımı)
- **Bağlam:** 27 session (çoğu opus) üç sorunu birden doğuruyor: (1) **pahalı** — büyük opus konuşmalar her turn tüm bağlamı yeniden işliyor, **Max 20x efektif 5x gibi** davranıyor [[usage-limits-5h-vs-weekly]]; (2) **kırılgan** — 25 opus bellek baskısı → **OOM** (bugün oldu) → recovery kaosu; (3) **remote-limit** — claude.ai/code muhtemelen **~10 eşzamanlı RC bağlantı** limiti → 27 session hepsi remote-erişilebilir OLAMAZ (anomaly mobilde flicker = slot yarışı).
- **Seçenekler:** (a) session sayısını azalt (≤~10-15); (b) **co → sonnet** (orkestrasyon opus gerektirmez, opus drain'i keser); (c) geçici "hepsi opus"tan **models.tsv split'e dön** (coding sonnet / paper opus); (d) sık handover'ı bırak (churn = bridge kaosu + truncation riski + kota).
- **Karar:** ? (kullanıcı "şimdilik hepsi opus, döneriz" dedi — dönülecek. Gece geç bırakıldı, taze kafayla.)

### 1) Python UI framework seçimi
- **Bağlam:** TODO'da "Python UI" eklendi. CLI yerine GUI'den session yönetmek.
- **Seçenekler:**
  - **PySide6 (Qt)** — masaüstü GUI, native widget'lar. ~30MB dependency.
  - **Textual** — terminal UI, tarayıcı render gerek yok, X11/Wayland bağımsız. CLI feel.
  - **Tkinter** — stdlib, install sıfır, ama eski UI hissi.
  - **Web (Flask + htmx)** — tarayıcıda; local server. Mobil access bonus.
- **Karar:** ?

### 2) `home13` / pid 23814 statüsü
- **Bağlam:** Eski yetim session (no name, no bridge, idle 30+h, cwd `/home/fatihyuce`). Kullanıcıya göre "kendisi" sayıldı, killed/skip.
- **Soru:** jsonl backup'ı duruyor (~6MB). Sil mi, arşivle mi?
- **Karar:** ?

### 3) Compact frequency politikası
- **Bağlam:** Compact token kullanımını azaltır ama API çağrısı yapar. Çok sık → token harcaması; çok seyrek → resume yavaş.
- **Soru:** Otomatik trigger eklensin mi? (örn. jsonl > X MB veya turn count > Y)
- **Karar:** ?

### 4) Backup retention
- **Bağlam:** Her compact/batch'te `.bak.YYYYMMDD-HHMMSS` yazılıyor. Birikiyor.
- **Soru:** `claudeops cleanup-backups --older-than=30d` gerekli mi?
- **Karar:** ?

### 5) Açık-kaynak (dünyaya açmak) — kişiye/makineye özel kısımları lokalde tut
- **Bağlam:** Bu kod public'e açılırsa, **her kullanıcıda farklı olacak / olması gereken** kısımlar repo'ya push'lanmamalı; lokalde kalmalı (gitignore + local config/template).
- **Kişi-/makine-bağımlı parçalar (aday):** session isim + model-grup listeleri (hms/hve/oa… opus vs sonnet), proje cwd path'leri, handover/respawn name listeleri, `READY FOR HANDOVER` blokları (kişiye özel session durumu), ekran geometrisi (1680×1050 hard-coded), gnome-terminal hard-coding, remote URL'leri (mfyuce github/gitlab), encoded memory path, **layout `--group` blok config'leri** (hc,hcr,mecdtfl / mo,kulturiot,gedikvm,gedikido — CLAUDE.md Faz 3'te). (`desktops.local.md` zaten gitignored — model.)
- **Seçenekler:** (a) `claudeops.local.conf` / `~/.config/claudeops/config` gitignored + kod generic; (b) env-var override; (c) `*.example` template commit'le, gerçeği gitignore.
- **Soru:** Hangi ayrım modeli? Public repo'da ne kalsın, ne lokal olsun?
- **Karar:** ? (konuşulacak — kullanıcı, 2026-05-26)

### 6) Web server üzerinden claudeops yönetimi
- **Bağlam:** claudeops şu an yerel bash CLI + gnome-terminal. Soru: fleet yönetimi (list, rc, handover, layout) bir web sunucusu üzerinden yapılabilir mi? Olası yaklaşımlar: (a) claudeops komutlarını wrap eden minimal HTTP API (FastAPI/Flask); (b) Claude.ai web arayüzü üzerinden RC bridge ile uzaktan kontrol; (c) tamamen web tabanlı UI (TODO'daki Python UI maddesinin web versiyonu). Ana engeller: layout (xdotool/Wayland), gnome-terminal spawn, display ortamı — bunlar yerel masaüstü gerektiriyor; uzaktan sadece RC/send/list/kill mantıklı.
- **Soru:** Hangi komutlar web'den anlamlı? Sadece RC/send/status mu, yoksa tam fleet yönetimi mi?
- **Karar:** ? (2026-06-18)

## Kapatılmış (karar verildi)

### Layout default per-desktop sayısı
- **Karar (2026-05-26):** şimdilik 4 (2×2 grid, laptop primary 1680×1050'de 840×525).

### GitHub vs GitLab remote
- **Karar (2026-05-26):** ikisine de push (origin=github, gitlab=gitlab.com). Bu repo public/personal araç.

### Model-spesifik permission mode
- **Karar (2026-05-25):** Hepsi `--permission-mode=auto` (sonnet'e de auto geldi). Model hâlâ ayrı: opus/sonnet.
