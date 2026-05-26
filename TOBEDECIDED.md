# claudeops — TOBEDECIDED

> Kullanıcı kararı bekleyen açık sorular. Karar verildikçe sil + DONE.md'ye yaz.

## Açık

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
- **Kişi-/makine-bağımlı parçalar (aday):** session isim + model-grup listeleri (hms/hve/oa… opus vs sonnet), proje cwd path'leri, handover/respawn name listeleri, `READY FOR HANDOVER` blokları (kişiye özel session durumu), ekran geometrisi (1680×1050 hard-coded), gnome-terminal hard-coding, remote URL'leri (mfyuce github/gitlab), encoded memory path. (`desktops.local.md` zaten gitignored — model.)
- **Seçenekler:** (a) `claudeops.local.conf` / `~/.config/claudeops/config` gitignored + kod generic; (b) env-var override; (c) `*.example` template commit'le, gerçeği gitignore.
- **Soru:** Hangi ayrım modeli? Public repo'da ne kalsın, ne lokal olsun?
- **Karar:** ? (konuşulacak — kullanıcı, 2026-05-26)

## Kapatılmış (karar verildi)

### Layout default per-desktop sayısı
- **Karar (2026-05-26):** şimdilik 4 (2×2 grid, laptop primary 1680×1050'de 840×525).

### GitHub vs GitLab remote
- **Karar (2026-05-26):** ikisine de push (origin=github, gitlab=gitlab.com). Bu repo public/personal araç.

### Model-spesifik permission mode
- **Karar (2026-05-25):** Hepsi `--permission-mode=auto` (sonnet'e de auto geldi). Model hâlâ ayrı: opus/sonnet.
