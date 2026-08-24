# claudeops — TOBEDECIDED

> Kullanıcı kararı bekleyen açık sorular. Karar verildikçe sil + DONE.md'ye yaz.

## Açık

### 9) needs_ho: git-dışı dosya değişimi takibi
- **Bağlam:** `needs_ho` şu an tüm sinyaller git-bazlı (dirty/untracked/committed_since/RFH). Git repo olmayan ya da `.gitignore`'lı dizinlerdeki dosya değişimleri yakalanmıyor. Ayrıca "en son değişen dosya + tarih" hiçbir yerde saklanmıyor — her kontrol anlık git sorgusu.
- **Soru:** CWD'deki dosyaların son mtime'ını (`mtime > last-handover.ts`) ayrıca takip etmeli miyiz? (git olmayan projeler için fallback)
- **Seçenekler:** (a) `os.walk` + mtime karşılaştırma (basit, gitignore'u bilmez); (b) `git ls-files + mtime` (git'teki dosyaları izle); (c) şimdilik git yeterli, gerekince ekle.
- **Karar:** ? (TBD, 2026-06-23)

### 3) Compact frequency politikası
- **Bağlam:** Compact token kullanımını azaltır ama API çağrısı yapar. Çok sık → token harcaması; çok seyrek → resume yavaş.
- **Soru:** Otomatik trigger eklensin mi? (örn. jsonl > X MB veya turn count > Y)
- **Karar:** ?

### 4) Backup retention
- **Bağlam:** Her compact/batch'te `.bak.YYYYMMDD-HHMMSS` yazılıyor. Birikiyor.
- **Soru:** `claudeops cleanup-backups --older-than=30d` gerekli mi?
- **Karar:** ?

## Kapatılmış (karar verildi)

### 5) Açık-kaynak (dünyaya açmak) — kişiye/makineye özel kısımları lokalde tut
- **Karar (2026-08-24):** Repo'yu gerçekten public'e açmadan önce içerik taraması yapıldı — endişe zaten büyük ölçüde **kendiliğinden çözülmüştü**: Python rewrite'ın `paths.py` tasarımı gereği roster.tsv/models.tsv/web.token (isim+cwd+model, kişiye özel her şey) zaten repo'nun DIŞINDA (`~/.claude/claudeops/`) yaşıyor, hiç commit edilmiyor. Tracked dosyalarda (CLAUDE.md/TODO/DONE/TOBEDECIDED) gerçek path/IP/secret YOK, sadece birkaç yerde `/home/fatihyuce` ve proje kod-adı geçiyor (machine_ops, hoca-worker) — düşük risk, historical changelog'un doğal parçası, silinmedi. `*.local.md`/`*.local.txt` zaten gitignored. Ekstra ayrım şeması (a/b/c seçenekleri) GEREKMEDİ. MIT LICENSE eklendi, README/py/README güncellendi (`py/cops web` öne çıkarıldı), repo public'e çevrildi.

### 6) Web server üzerinden claudeops yönetimi — TBD#1 (Python UI) ile birleşti
- **Karar (2026-08-24):** `py/cops web [--tunnel]` — stdlib `http.server` (Flask/PySide/Textual/Tkinter'ın hiçbiri, TBD#1'i de kapatır: dependency sıfır). Web'den anlamlı olan: **roster'ın tamamını göster (çalışan/duran/kapalı/emekli) + tek tek başlat (model/permission-mode/effort/fresh seçenekleriyle) / durdur / emekli et / tekrar işe al**. Layout/xdotool web'e TAŞINMADI (haklı çıktı: Wayland/display bağımlılığı yerel kalmalı). Token-gated (`~/.claude/claudeops/web.token`) + `--tunnel` ile `cloudflared` quick-tunnel (kurulu: `~/.local/bin/cloudflared`) — kullanıcı: "cf tunnel ile web'e ulaşırım, istediğim yerden başlatırım."

### 7) Fleet ÇOK BÜYÜK → küçült/hafiflet?
- **Karar (2026-08-24):** Headcount AZALTILMADI (27 kaldı) — bunun yerine **kök nedenler farklı çözüldü**: (1) pahalı → tüm fleet **claude-sonnet-5**'e çekildi (split kalktı, opus-5 migration anında 529/overloaded'dı); (2) kırılgan/OOM → guard cron **kasıtlı devre dışı**, artık hiçbir şey otomatik toplu açılmıyor, kullanıcı `py/cops web` ile TEK TEK başlatıyor → 27'si aynı anda ayakta olma riski kullanıcının elinde/görünür. (3) remote-RC-limit (~10 eşzamanlı) hâlâ TEST EDİLMEDİ — web-panelden aynı anda kaç tanesini gerçekten RC-bridge'li tutabildiği ampirik olarak doğrulanmadı, ileride sorun çıkarsa buraya bak.

### claudeops Python rewrite — TBD#8
- **Karar (2026-06-22):** Python, incremental. `py/` dizini. 8 komut tamamlandı: `list`, `config`, `kill`, `guard`, `rc`, `handover`, `stuck`, `layout`. Bash `claudeops` ROOT'ta canlı fleet'i yönetmeye devam eder; Python `py/cops` ile birlikte büyür. Derin review + fix tamam (c8d20c4).

### Layout default per-desktop sayısı
- **Karar (2026-05-26):** şimdilik 4 (2×2 grid, laptop primary 1680×1050'de 840×525).

### GitHub vs GitLab remote
- **Karar (2026-05-26):** ikisine de push (origin=github, gitlab=gitlab.com). Bu repo public/personal araç.

### Model-spesifik permission mode
- **Karar (2026-05-25):** Hepsi `--permission-mode=auto` (sonnet'e de auto geldi). Model hâlâ ayrı: opus/sonnet.
