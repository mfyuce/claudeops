# claudeops — TOBEDECIDED

> Kullanıcı kararı bekleyen açık sorular. Karar verildikçe sil + DONE.md'ye yaz.

## Açık

### 13) Sabit (hiç değişmeyen) tunnel URL'i — hangi domain?
- **Bağlam (2026-08-30):** Kullanıcı `hoce.me`'yi (doğrusu **hoca.me**) sabit Cloudflare tunnel domain'i olarak kullanmayı sordu — "videogen için kurulum yaptığımız yer".
- **Bulgu:** `hoca.me` kullanıcının CANLI production hoca video-gen servisi (gerçek ödeyen müşteriler, iyzico ödeme, Google OAuth — bkz. videogen `DONE.md` "hoca.me deploy (2026-06-05) — ilk production sunucu CANLI"). Canlı DNS'e bakıldı: nameserver'lar `dnsenable.com`, A kaydı doğrudan Hetzner sunucusuna (`49.13.238.226`) gidiyor — **hoca.me şu an Cloudflare'de bile değil** (`docs/hoca_me_deploy.md`'deki Cloudflare DNS tablosu bir plandı, gerçekte uygulanmamış: checklist'i hâlâ tamamen işaretsiz). Domain'in TAMAMINI Cloudflare'e taşımak (nameserver değişikliği) canlı siteyi (OAuth redirect, Caddy/Let's Encrypt, ödeme, mail linkleri) riske atar — bunun için bedeli yok.
- **Seçenekler:**
  (a) `hoca.me`'de GÜVENLİ bir alt-domain (ör. `ops.hoca.me`) — sadece o TEK alt-domain'i NS-delegation ile Cloudflare'e bağlamak (dnsenable.com panelinden 2-3 NS kaydı eklemek), canlı sitenin geri kalanına DOKUNMAZ. Elle bir adım gerekir (parent DNS panelinde NS kaydı eklemek), ama güvenli.
  (b) Ayrı, ufak yeni bir domain (~1-2$/yıl) — canlı hoca.me'ye hiç dokunmadan en basit/en riske-en-uzak yol.
  (c) Şimdilik vazgeç — quick-tunnel (rastgele URL) + değişince ntfy.sh push bildirimi (`py/cops service notify`, UYGULANDI 2026-08-30) yeterli.
- **Karar (2026-08-30):** Şimdilik **(c)** — sabit URL peşinde koşulmuyor, bildirim mekanizması yeterli bulundu. (a)/(b) ileride istenirse burası tekrar açılır.
- **Güncelleme (2026-09-02) — (c)'nin dayanağı sarsıldı:** Kullanıcı "mobilden ulaşamadım" dedi. Teşhis: `~/.cloudflared` hâlâ boş (hep quick-tunnel), üstüne cloudflared'ın kendi 24h auto-update'i (crash'ten bağımsız) de URL'i döndürüyor. Daha kritik: ntfy push CANLI test edildi (telefonda gerçek push atıldı, kullanıcı kontrol etti) — **bildirim telefona ULAŞMADI**. 2026-08-30'daki "uçtan-uca doğrulandı" notu (DONE.md) yanıltıcı çıktı: sadece ntfy.sh SUNUCUSUNA ulaştığını doğrulamıştı, telefonda göründüğünü değil. Ayrıca ntfy.sh'nin ~12h server-cache'i yüzünden geç fark edilen değişiklikler kalıcı kayboluyor (1 Eylül'deki asıl URL-değişim mesajı artık geri getirilemez). Kullanıcıya telefon tarafı (Instant Delivery ayarı / Android pil optimizasyonu) kontrolü önerildi, sonuç henüz bilinmiyor. Düzelirse (c) hâlâ geçerli sayılabilir; düzelmezse (a)/(b) ciddi olarak yeniden gündeme gelmeli. Kullanıcı şimdilik hiçbir fix'e (ne `--no-autoupdate` ne named tunnel) onay vermedi — sadece kayıt. [[tunnel-no-named-tunnel-autoupdate-rotates-url]]

### 12) Bash `claudeops` (ROOT) hâlâ gerekli mi — silinsin mi?
- **Bağlam (kullanıcı sorusu, 2026-08-30):** "eski bash tabanlı kodlara ihtiyaç yok artık onları silelim?" TBD#8'den (2026-06-22) beri Python (`py/cops`) büyüyor — artık web panel + provider mimarisi (claude/agy/shell) + `service` (systemd kalıcılık) dahil çoğu operasyonu kapsıyor.
- **Bulgular:**
  1. ~~Somut, canlı bağımlılık: `~/.config/autostart/claudeops.desktop` cold-boot'ta hâlâ BASH `claudeops guard --boot --lock` çalıştırıyor~~ — **KALKTI (2026-09-02): dosya fiilen kaldırıldı** (zaten `X-GNOME-Autostart-enabled=false` idi, silme davranış değiştirmedi — TODO.md L58). `py/cops service` ile web panel+tunnel zaten kalıcı/reboot'ta kendiliğinden ayakta.
  2. CLAUDE.md'nin kendi Faz 3 tarifi hâlâ `./claudeops layout ...` (BASH) diyor — `py/claudeops/commands/layout.py` docstring'inde kendini "bash'in karşılığı" tanımlasa da, gerçekten Faz 3'te CANLI denenip CLAUDE.md'nin `py/cops layout`'a çevrildiği DOĞRULANMADI; sadece dokümantasyon gecikmesi mi yoksa gerçek bir eksiklik mi bilinmiyor. **Hâlâ açık** — ayrıca `py/cops layout`'un kendisi hâlâ bilinen bir çoklu-monitor bug'ı taşıyor (TODO.md, 2026-09-02'de kullanıcı tarafından canlı yeniden doğrulandı) — Faz 3 geçişi bu bug çözülmeden riskli olur.
  3. **Denetim tamamlandı (2026-09-02, kullanıcıya doğrudan soruldu):** Bash'te olup py/cops'ta muadili net olmayan 6 komut tek tek gözden geçirildi:
     - **`compact` → ARTIK KAPANDI.** Kullanıcı: "terminal de ve listeden seçip onlara compact gonderme iyi olur" — py/cops'a `_compact()` + web panelde bulk action olarak EKLENDİ (TODO.md, 2026-09-02). Bash'inkiyle aynı mekanizma (headless `-p '/compact'`, kill-önce).
     - **`desktops`/`send` → İSTENİYOR, ama `send`'in temel işlevi ZATEN panelde var.** Kullanıcı: "dekstoplar ve cli ların gideceği yerleri set etme yolsa default yayma olsa iyi olur" (yeni TODO: spawn-anında hedef-masaüstü/otomatik-dağıtım, madde 2'deki layout bug'ına bağımlı, henüz yapılmadı) + "metin gonderioz ama komut da gönderebilir miyiz" (`send`'in "session'a metin yolla" temel işlevi zaten `/api/term/input` ile panelde var — kullanıcı bunun FARKINDA, ekstra istediği "CLI'nın kendi komut listesinden seçip gönderme" — yeni TODO, kullanıcı: "acil değil").
     - **`batch`/`self`/`new` → muhtemelen kullanılmıyor.** Kullanıcının kendi tepkisi ("batch self new nedir?") bu üçünü TANIMADIĞINI gösteriyor — aktif kullanılan komutlar olsa isimlerini hatırlardı. `new` zaten panelin "+ Yeni proje kaydet"/reactivate akışıyla, `batch` (backup→kill→compact→rc pipeline'ı) artık panelin ayrı ayrı stop/compact/start aksiyonlarıyla, `self` (kendi session bilgini yazdır) panelin zaten her satırda gösterdiği bilgiyle fiilen karşılanmış durumda — YENİDEN İNŞA EDİLMESİ GEREKMİYOR.
- **Öneri (silmeden önce sırayla):** (a) ~~autostart~~ **KAPANDI**; (b) Faz 3'ü gerçekten `py/cops layout`'la denemek HÂLÂ AÇIK (+ önce çoklu-monitor bug'ı çözülmeli); (c) ~~komut denetimi~~ **KAPANDI** (yukarı bkz. — `compact` yapıldı, `desktops`/`send`-palette ayrı düşük-öncelikli TODO'lara döndü, `batch`/`self`/`new` gerek yok kararı verildi). Kalan TEK engel (b) — o kapanınca bash güvenle silinebilir.
- **Karar:** ? (a)+(c) KAPANDI, sadece (b) açık — bash'in silinmesi artık SADECE Faz 3'ün gerçekten `py/cops layout`'la canlı denenmesine bağlı.

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

### 14) `feature/react-ui` branch'i main'e merge edilsin mi? — MERGE EDİLDİ, react-ui ASIL
- **Karar (2026-09-01, kullanıcı):** "artık reacti marge edelim, asıl olsun, yeterince iyi, eskisiyle bir daha uğraşmayalım, son hali deploy edelim." ~5 haftalık paralel-deploy denemesi (2026-08-31'de "merge etme şimdilik, paralel çalıştır, karşılaştır" kararıyla başlamıştı) sonuçlandı: react-ui panel yeterince olgunlaştı, `main` artık react-ui'nin KENDİSİ (2-parent gerçek merge commit, main'in TÜM eski commit'leri git history'de kayıp değil). Eski PAGE_HTML panel emekli. Detay/mekanik: DONE.md 2026-09-01 "feature/react-ui → main merge".
- **Uygulanan:** react-only paralel deploy (port 8766, `claudeops-web-react.service`/`claudeops-tunnel-react.service`) durduruldu+disable edildi (unit dosyaları SİLİNMEDİ — kolay rollback). `feature/react-ui` branch+worktree de SİLİNMEDİ (rollback referansı). Merge öncesi main'in 19 kendine-özgü commit'i tek tek incelendi — ikisi (service.py'nin tunnel `Wants=` fix'i + `run-tunnel.sh` parametrizasyonu) gerçekten main'de daha ileriydi ve KORUNDU, gerisi ya moot (eski panel'e özel) ya da react-ui'de zaten eşdeğeri vardı.
- **Not (bash `claudeops`):** bu merge'in kapsamı DIŞINDA bilerek bırakıldı — TBD#12 (aşağıda) hâlâ açık, bağımsız bir soru.

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
