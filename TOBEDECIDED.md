# claudeops — TOBEDECIDED

> Kullanıcı kararı bekleyen açık sorular. Karar verildikçe sil + DONE.md'ye yaz.

## Açık

### 12) Bash `claudeops` (ROOT) hâlâ gerekli mi — silinsin mi?
- **Bağlam (kullanıcı sorusu, 2026-08-30):** "eski bash tabanlı kodlara ihtiyaç yok artık onları silelim?" TBD#8'den (2026-06-22) beri Python (`py/cops`) büyüyor — artık web panel + provider mimarisi (claude/agy/shell) + `service` (systemd kalıcılık) dahil çoğu operasyonu kapsıyor.
- **Bulgular:**
  1. ~~Somut, canlı bağımlılık: `~/.config/autostart/claudeops.desktop` cold-boot'ta hâlâ BASH `claudeops guard --boot --lock` çalıştırıyor~~ — **kullanıcı (2026-08-30) itirazı haklı: artık gerekmiyor.** `py/cops service` ile web panel+tunnel zaten kalıcı/reboot'ta kendiliğinden ayakta; kullanıcı fleet'i telefondan panelden TEK TEK başlatıyor (2026-08-24 "Fleet kontrolü — MANUEL" kararıyla zaten tutarlı — guard cron o yüzden KASITLI kapalı; cold-boot'ta otomatik toplu-reopen aslında o kararın istisnasıydı). Yani bu madde bir PORT gerektirmiyor, autostart `.desktop`'ı TAMAMEN kaldırmak yeterli — TODO.md'deki 2026-06-25 maddesi de "py'ye taşı" değil "kaldır" olarak kapanmalı.
  2. CLAUDE.md'nin kendi Faz 3 tarifi hâlâ `./claudeops layout ...` (BASH) diyor — `py/claudeops/commands/layout.py` docstring'inde kendini "bash'in karşılığı" tanımlasa da, gerçekten Faz 3'te CANLI denenip CLAUDE.md'nin `py/cops layout`'a çevrildiği DOĞRULANMADI; sadece dokümantasyon gecikmesi mi yoksa gerçek bir eksiklik mi bilinmiyor. **Hâlâ açık.**
  3. Bash'te olup py/cops'ta muadili net olmayan komutlar: `desktops` (N masaüstü sabitle), `send` (session'a metin/slash-komut — web panelin terminal input'u kısmen üstleniyor olabilir), `compact`, `batch`, `new`, `self`. Gerçekten hâlâ kullanılıyorlar mı, denetlenmedi. **Hâlâ açık.**
- **Öneri (silmeden önce sırayla):** (a) ~~autostart'ı py'ye taşı~~ → **autostart `.desktop`'ı kaldır** (küçük, geri alınabilir bir adım — istersen şimdi yaparım); (b) Faz 3'ü gerçekten `py/cops layout`'la deneyip CLAUDE.md'yi güncelle; (c) `desktops`/`send`/`compact`/`batch`/`new`/`self`'i tek tek gözden geçir. (b)+(c) kapanınca bash güvenle silinebilir — (a) artık engel değil.
- **Karar:** ? (madde (a) çözüldü/moot; (b)+(c) açık kaldığı sürece "hepsi test edildi" diyemeyiz, ama tek somut kırılma riski ortadan kalktı)

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

### 10) agy (Google Antigravity CLI) entegrasyonu — çoklu-CLI fleet — UYGULANDI
- **Karar (2026-08-27):** Uygulandı (faz 1+2), canlı doğrulandı. Mimari kullanıcı isteğiyle DEĞİŞTİ: ilk taslağım `if cli=="agy"` branch'leriydi, kullanıcı reddetti — "iki ayrı provider, bir base ana operasyonları belirtir, claude ve agy kendi içeriğini doldurur, cops manager olarak o metodları çağırır." Sonuç: yeni `py/claudeops/providers/` paketi (`base.py` ABC + `claude_provider.py` + `agy_provider.py` + registry) — `spawn.py`/`discovery.py`/`commands/web.py` artık HİÇBİR YERDE `cli` string'ine göre dallanmıyor, sadece `get_provider(cli)` üzerinden çağırıyor (bkz. [[feedback-multi-backend-provider-pattern]]).
  - roster.tsv 4. kolon (`cli`, opsiyonel, yoksa "claude" — eski satırlar bozulmadı); isimlendirme `COPS_NAME` env (agy'nin `--remote-control` muadili yok) + discovery `psutil.Process.environ()`; COPS_NAME olmadan (bare agy) `agy-<pid>` placeholder — adoptable.
  - **İki gerçek canlı-test sürprizi:** (1) agy 2 günde 1.1.2→1.1.22'ye auto-update olmuş, artık gerçek bir `--effort low|medium|high` flag'i VAR (orijinal tasarım notu "yok" diyordu — CLI'lar sabit durmuyor, her seferinde yeniden doğrula). (2) `COPS_NAME` env'i Popen'ın env dict'ine koymak ZATEN ÇALIŞAN bir tmux server'da yeni session açarken proc'a hiç ulaşmıyordu — tmux sadece kendi `update-environment` varsayılan listesini (DISPLAY, SSH_AUTH_SOCK, ...) yeni pane'e aktarıyor, gerisini sessizce yok sayıyor. Fix: `env_overrides()` artık Popen env'ine değil, komut satırının kendisine `env KEY=VAL ... <binary>` olarak gömülüyor (tmux'un env-inheritance'ını tamamen atlar).
  - agy model listesi CANLI çekiliyor (`agy models`, 300s TTL cache) — 2 günde bir kez değiştiği görüldü, sabit kodlamak hemen bayatlardı.
  - **Faz 3 (agy'nin kendi handover/RFH/needs_ho sinyali) hâlâ AÇIK/ertelendi** — `find_latest_jsonl` claude'a özel olduğu için agy session'ları bugünkü haliyle Faz1 batch handover'dan TEMİZCE atlanıyor (crash yok, sadece "skipped-no-jsonl"), istenirse ayrı bir iş.

### 11) tmux-backed session'lar → web tabanlı CLI (panelden girdi/çıktı) — UYGULANDI
- **Karar (2026-08-27):** Uygulandı, A→D fazlarıyla, canlı doğrulandı. Detay: DONE.md 2026-08-27 girdisi. Kısaca: `tmux_backend.py` (dedicated socket `-L cops`) + `spawn.py`/`kill.py` tmux-aware + `/api/term/{output,input,key}` + panelde xterm.js (lazy-vendored). İki gerçek sürpriz canlı testte çıktı: (1) `kill_session_and_parent`'ın PID-ancestry'sini tmux'a olduğu gibi uygulamak TÜM filoyu silme riskiydi — ad-bazlı kill'e geçildi; (2) `--remote-control` session'larına girdi ulaşmıyordu, kök sebep tmux `focus-events off` idi (Claude'un kendi TUI'si ipucu veriyordu), `tmux.conf`'a `set-option -g focus-events on` eklenince (spawn'dan ÖNCE, session zaten bağlıyken değil) düzeldi.

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
