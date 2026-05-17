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

### 4) Layout default per-desktop sayısı
- **Bağlam:** Şu an `--per=4` (2×2 grid). 6 (3×2) veya 9 (3×3) seçenekleri de mantıklı küçük ekranlarda farklı.
- **Soru:** Default 4 mü, başka mı? Multi-monitor desteği nasıl?
- **Karar:** şimdilik 4 (laptop primary 1680×1050'de 840×525)

### 5) Backup retention
- **Bağlam:** Her compact/batch'te `.bak.YYYYMMDD-HHMMSS` yazılıyor. Birikiyor.
- **Soru:** `claudeops cleanup-backups --older-than=30d` gerekli mi?
- **Karar:** ?

### 6) GitHub vs GitLab vs internal Ulak gitlab — hangi remote default?
- **Bağlam:** sqli projesinde origin'in aslında Ulak internal'a redirect ettiğini gördük.
- **Soru:** claudeops repo için origin = GitHub mı GitLab.com mı?
- **Karar:** ikisine de push (origin=github, gitlab=gitlab.com). Bu repo public/personal araç, internal yok.

## Kapatılmış (karar verildi)

_(buraya taşınacaklar geldikçe)_
