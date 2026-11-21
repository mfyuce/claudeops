# derbent entegrasyonu: uygulama planı (19 Kas 2026)

Sahip kararı (19 Kas): derbent UI'ı enterprise'da başlar. Kapsam: (1) `settings.derbent {dir,bin,port}`, (2) uygulama kaydı + bilet, (3) Araçlar > Uygulamalar (enterprise rol/denetim), (4) otomatik keşif. Çekirdek (public) yalnız genel kanca verir; derbent'e özgü davranış `claudeops-enterprise`'ta. Uzak host (derbent faz 3) ve uygulama başına tünel (faz 4, derbent TBD 1/2/6) bu planın DIŞINDA.

## Okunan dayanak (yalnız okundu)

- derbent `docs/plan.md`, `README.md`, `CLAUDE.md`, `TOBEDECIDED.md`, `src/admin.rs` (grep).
- derbent'te HAZIR: tek ikili + YAML, `include`/`conf.d/*.yaml`, uygulama başına loopback dinleyici (`listen.port` verilmezse boş port), sıcak yeniden yükleme (dosya yoklama 2 sn, `SIGHUP`, `POST /reload`), bilinmeyen anahtar = hata, sırlar yalnız `${ENV}`/`file:`, `default-filters` (`StripCookie=cops_*`, `AddForwardedHeaders`, `RewriteLocation`), `ExternalFilter` (HTTP/gRPC dış karar servisi).
- Yönetim API'si (`admin:` bölümü varsa, yalnız 127.0.0.1/[::1], Bearer token `file:` ile): `GET /health`, `GET /apps` (id, uri, listen, upstreams, dns_error, last_reload), `GET /status`, `POST /reload`. YAZMA UCU YOK: config diske yazılır, sonra reload.
- derbent'te YOK (src grep: "ticket" eşleşmesi yok): bilet/çerez denetimi, uygulama hedefine sağlık yoklaması, kayıt dışı meta alan (`project`, `roles`, görünen ad).
- claudeops uzakgoz kalıbı: `settings.py` `uzakgoz_config()` (dir = Cargo.toml olan dizin ya da varsayılan, bin = çalıştırılabilir, port 1024-65535; geçersiz sessizce atlanır, fırlatmaz); `DEFAULT_SETTINGS` + `_save_settings_locked` dict birleştirme listesi; `remote_desktop.py` (`cargo build --release` + `cargo metadata` ile ikili yolu, PID_FILE ile yetim süreci sahiplenme, `/proc/<pid>/cmdline` doğrulama, token ortam değişkeniyle, `start/stop/status`).
- Enterprise kancaları (`extensions.py`): `register_api_route(prefix, fn, methods, action)` (`/api/enterprise/...`, eylem `admin.*|self.*`, `_gate`ten geçer), `register_ui_extension(id, dir, roles, title, entry, title_en)`, `on_session_event`, `register_audit_sink`, `api.projects()` (ad + yerel cwd), `api.settings(key)`. Enterprise örnek: `admin/api.py` (`_audit` -> `admin/audit.write`), `admin/webui/admin.js` (derlemesiz tek ES modülü, `uiApi = 1`, `mount(el, ctx)`, yalnız `textContent`).
- Tespit edilen iki boşluk: (a) UI uzantı sekmeleri panelde ÜST düzey sekme olur (`webui/src/state/tabs.ts`: `TOOLS_SUBS` sabit, `ext:<id>` grupsuz); Araçlar altına koymak için çekirdek kancası gerek. (b) Enterprise UI uzantıları bugün yalnız `_register_multi_user` içinde kaydediliyor; tek kullanıcı kipinde görünmezler (sahibin kurulumunun kipi DOĞRULANMADI).

## Dilimler (her biri tek commit, testli; sıra = önerilen uygulama sırası)

C = çekirdek (claudeops, public), E = enterprise (claudeops-enterprise, private), D = derbent'ten istenen.

**C1. `settings.derbent` anahtarı + `derbent_config()`** (bağımlılık yok)
- `DEFAULT_SETTINGS["derbent"] = {}`, dict birleştirme listesine `"derbent"`, `derbent_config()` uzakgoz ile aynı sözleşme: `dir` (Cargo.toml; boşsa `~/work/projects/tmp/derbent` varsa), `bin`, `port` (= yönetim API portu, 1024-65535). Yalnız doğrulayıcı; süreç başlatma YOK.
- Test: uzakgoz testlerinin kopyası (geçersiz port/dir/bin atlanır, boş değer anahtarı siler, fırlatmaz).

**C2. Uzantı sekmesini gruba koyma kancası** (bağımlılık yok)
- `register_ui_extension(..., group="")`; `group in ("", "tools", "settings")`, `/api/ui/extensions` yanıtına `group`; panelde `group == "tools"` olan `ext:<id>` Araçlar alt sekme satırına girer (`visibleSubs`), diğerleri bugünkü gibi üst düzey.
- Test: Python birim (geçersiz grup reddi, yanıtta alan), `tabs.ts` birim testi, `tsc --noEmit`, dist derle; Chrome masaüstü + 390 px ekran görüntüsü.

**E1. derbent süreç yöneticisi** (C1'e bağlı)
- `claudeops_enterprise/apps/daemon.py`: `remote_desktop.py` kalıbı (build, ikili çözümü, PID dosyası + sahiplenme, cmdline doğrulama, SIGTERM/SIGKILL). Durum dizini `CLAUDEOPS_DIR/derbent/`: ana `derbent.yaml` (`admin: {listen: 127.0.0.1:<port>, token: file:admin.token}`, `include: [conf.d]`, `default-filters`), `admin.token` (0600), `conf.d/`. Sağlık = `GET /health` Bearer ile.
- Etkinleştirme: lisans sözleşmesi bayraksız kurulumda rota kaydını yasaklıyor (`test_license_wire`), bu yüzden opt-in bayrak `ent_apps=on` (notes feed kalıbı). Bkz. Açık soru 2.
- Test: sahte ikili (küçük Python HTTP sunucusu) ile start/stop/adopt/yanlış süreci öldürmeme; `derbent` ikilisi varsa `derbent check` ile üretilen YAML doğrulanır (yoksa atla).

**E2. Uygulama kaydı + conf.d yazımı + port ayırma** (E1'e bağlı)
- Kayıt: `id`, `name`, `project` (isteğe bağlı, `api.projects()` adı), `target`, `local_port`, `roles`, `tls_pin_sha256`, `max_body`, `timeout`. Her kayıt `conf.d/<id>.yaml` (derbent anahtarları) + claudeops meta (D3 gelene kadar `apps.json`; bkz. Açık soru 3). Port: sabit aralıktan (öneri 18100-18199) boş olan, kayıtta kalıcı. Yazım atomik (tmp + rename), sonra `POST /reload`; 422 ise dosya geri alınır, hata döner.
- Test: YAML üretimi (bilinmeyen anahtar yok, sır satır içi değil), çakışan port, reload 422 geri alma (sahte admin), `derbent check` entegrasyonu (ikili varsa).

**E3. Uygulamalar API'si + denetim** (E2'ye bağlı)
- `register_api_route("/api/enterprise/apps/", ..., ("GET","POST"), "admin.apps")` yazma için; liste için rol süzmeli okuma (`self.apps`): kullanıcı yalnız `roles` kesişen uygulamaları görür. Liste satırı: ad, proje, host (şimdilik yerel), hedef, sağlık (derbent `/apps` + `last_reload`), Aç. Her ekle/düzenle/sil/aç `admin/audit.write` ile.
- Test: rol süzme, admin olmayan yazma 403, denetim satırı yazıldı, derbent kapalıyken liste "durdu" döner (500 değil).

**E4. Uygulamalar sekmesi (UI)** (C2, E3'e bağlı)
- `apps/webui/apps.js` (admin.js sözleşmesi: `uiApi=1`, `mount/destroy`, yalnız `textContent`, TR/EN). `register_ui_extension("apps", ..., roles=("admin","user"), title="Uygulamalar", group="tools")`. Admin: ekle/düzenle/sil, derbent başlat/durdur; kullanıcı: liste + Aç.
- Test: `node --check`, mevcut `test_admin_js_*` tarzı statik test (innerHTML yok), Chrome masaüstü + 390 px, Aç düğmesi yeni sekmede uygulamayı açıyor (varaka :8080 ile).

**E5. Bilet** (D1 ve E3'e bağlı)
- Aç = kısa ömürlü (öneri 60 sn) imzalı bilet basar: `app_id`, `exp`, `nonce`, `uid`; HMAC anahtarı `CLAUDEOPS_DIR/derbent/ticket.key` (0600), derbent'e `file:` ile. Yanıt: `http://localhost:<port>/?<D1'deki parametre>=<bilet>`. Rol denetimi bilet basılmadan; basım denetime yazılır. Panel token'ı uygulama origin'ine hiç gitmez.
- Test: Python başvuru doğrulayıcısıyla gidiş-dönüş, süresi geçmiş/başka uygulamanın bileti red; derbent ikilisiyle uçtan uca (bilet -> 302 + çerez -> 200; biletsiz -> 401).

**E6. Otomatik keşif** (E2'ye bağlı; E5'ten bağımsız)
- `ss -ltnpH` çıktısından dinleyen TCP portları + PID; `/proc/<pid>/cwd` bir projenin cwd'si altındaysa öneri (proje, port, süreç adı). OTOMATİK KAYIT YOK: UI'da "Öneriler" + tek tıkla kaydet. Tetik: sekme açılınca ve isteğe bağlı 5 dk'lık iş parçacığı (yalnız sekme yakın zamanda açıksa; boşta yoklama yok). derbent'in kendi dinleyicileri ve claudeops portları hariç.
- Test: `ss` çıktısı fikstürleri (IPv4/IPv6, birden çok PID), cwd eşleşmesi, kendi portlarını dışlama.

## derbent'ten istenenler (derbent oturumuna direktif)

- **D1 (zorunlu, E5 için): yerel bilet/çerez filtresi.** Örn. `CopsTicket` (ad derbent'e kalır): ilk istekte sorgu parametresindeki HMAC-SHA256 bileti doğrular (`app_id` eşleşmesi, `exp`, nonce tek kullanım bellek içi, saat kayması toleransı), parametreyi URL'den silip 302 ile uygulama kapsamlı `HttpOnly; SameSite=Lax` (yerel http'de `Secure` yok) çerez verir; sonraki isteklerde yalnız çerez imzası denetlenir (sıcak yolda ayırma yok, bütçe ölçümü bench'e). Anahtar `file:` ile, reload'da yeniden okunur. Geçersiz/eksik: 401 (yapılandırılabilir yönlendirme isteğe bağlı). Bilet biçimi için ortak test vektörü dosyası (claudeops Python testi aynı vektörü kullanır).
- **D2 (önerilen): uygulama hedef sağlığı.** Uygulama başına isteğe bağlı zamanlayıcılı yoklama (`health: {path, interval}`, varsayılan kapalı), sonuç `GET /apps` içinde (`health: {ok, at_ms, ms, error}`). Yoksa claudeops hedefi kendisi yoklar (E3'te geri dönüş yolu).
- **D3 (önerilen): serbest `meta:` haritası.** Uygulama girdisinde proxy'nin yok saydığı, `GET /apps`'ta aynen dönen düz string haritası (`project`, `roles`, `name`). Böylece conf.d tek doğruluk kaynağı kalır (derbent planındaki "UI ve CLI aynı dosyaları düzenler" kuralı), claudeops ayrı `apps.json` tutmaz.
- **D4 (doğrulama):** `listen.port` claudeops'tan sabit verildiğinde port doluysa reload 422 ve `last_reload.error` uygulama adıyla döner mü? README iki aşamalı reload'u anlatıyor; E2 geri alması buna güvenir, derbent tarafında bir test istenir.

## Bağımlılık özeti

C1 -> E1 -> E2 -> E3 -> E4; C2 -> E4; D1 + E3 -> E5; E2 -> E6. D1 hemen istenebilir (paralel ilerler). E5'e kadar Aç düğmesi biletsiz düz URL verir ve YALNIZ admin'e görünür (yerel loopback, panel token'ı gitmez); E5 ile bilete geçer.

## Açık sorular (sahip)

1. **derbent süreç yöneticisi nerede?** (a) Enterprise (E1, bu plan); (b) çekirdek (`remote_desktop.py` gibi, OSS kullanıcıları da derbent'i başlatabilir); çekirdek yalnız `settings.derbent` doğrulayıcısını taşır. Öneri: (a), "UI enterprise'da başlasın" kararıyla uyumlu; ileride gerekirse çekirdeğe taşınır. Not: (a)'da da `derbent` adı public çekirdekte yalnız ayar anahtarı olarak görünür; bu kabul mü?
2. **Tek kullanıcı (lisanssız) kurulumda görünürlük:** (a) opt-in bayrak `ent_apps=on` ile lisanssız da kaydedilir (notes feed kalıbı); (b) yalnız çok kullanıcılı lisansla. Öneri: (a); sahibin kendi kurulumu tek kullanıcı ise (doğrulanmadı) (b) sekmeyi hiç göstermez.
3. **Meta nerede tutulur?** (a) derbent D3 `meta:` alanı, conf.d tek kaynak; (b) claudeops `apps.json` + conf.d (iki kaynak, eşitleme gerekir). Öneri: (a); D3 gelene kadar (b) geçici.
4. **Bilet denetimi:** (a) derbent içinde yerel filtre (D1); (b) mevcut `ExternalFilter` ile her istekte claudeops'a sorma (derbent değişikliği yok ama istek başına ~110 µs p50 + Python süreci sıcak yolda). Öneri: (a), derbent gecikme bütçesi (p50 <= 0,2 ms) (b) ile tutmaz.

## Faz 3 tasarım notu: uzak uygulamada mutlak adres (20 Kas, sahip)

Sorun: Grafana arayüzü API'yi tarayıcıdan mutlak şirket adresine (`https://10.20.4.165/api/...`) çağırıyor; yol menzil reach -> 127.0.0.1 -> derbent iken bu istek tarayıcıdan doğrudan şirket ağına gider ve dışarıda asılı kalır. derbent yolu (proxy) yalnız göreli/aynı-köken istekleri taşır.
Seçenekler: (c) uygulamanın kendi `root_url`/base ayarı (Grafana `root_url`) = göreli adres, uygulama izin veriyorsa ilk tercih (ek kod yok); (a) menzil `proxy` (SOCKS çıkışı, menzilde "not implemented yet": menzil oturumuna steward direktifiyle istenecek) + tarayıcıda PAC yalnız 10.20.0.0/16 için, genel çözüm; (b) derbent yanıt gövdesinde mutlak köken yeniden yazımı: akışı ve gecikme bütçesini bozar, son çare.
**Karar (sahip, 21 Kas, önceki karar yerine geçer):** çözüm SAF derbent ile ve YALNIZ config ile; Grafana `root_url` (c) ve menzil SOCKS/PAC (a) yolları KULLANILMAZ. derbent'e uygulama başına `rewrite` alanı eklenir (kurallar `from -> to`; varsayılan yalnız `text/html` gövde + başlıklar: Location, Set-Cookie Domain, CORS, CSP; JS/JSON taraması `content_types` ile isteğe bağlı; `encoding: strip|recode|skip`; istek yönünde upstream'e Host/Origin/Referer geri yazımı, `host_header: from|upstream`). Uygulama kendi kökünde yayınlanır, alt yol öneki kapsam dışı. Grafana için `to: "{origin}"` (`""` appUrl'yi `/` yapar ve frontend `new URL(appUrl)` TypeError verir). Uygulandı: derbent e76aea8; yerel Grafana konteynerinde (root_url=http://10.20.4.165/) giriş, dashboard, POST, WebSocket ve çıkış derbent üzerinden doğrulandı. Gövde yeniden yazımı akışlıdır (chunk sınırında bölünen eşleşme taşınır, sabit bellek); `rewrite` tanımsız uygulamada sıfır ek maliyet, gecikme bütçesi (p50 <= 0,2 ms) yalnız rewrite'lı uygulamada ölçülür. Sınır: minify edilmiş JS içinde dinamik kurulan URL'ler yakalanamaz. E-dilimleri (yerel uygulamalar) bundan bağımsız ilerler. TBD#273 bu kararla kapanır.

## Faz 3b: panel yol öneki ile genel eşleme (21 Kas, sahip)

Sahip kararı: Grafana'ya claudeops web panelinden (quick tunnel, mobil dahil) `<panel>/grafana/` ile ulaşılır; Grafana yalnız ilk örnektir, mekanizma GENEL ve DİNAMİKTİR: herkes config ile `<host>:<port>[/<yol>] -> <panel>/<mount>/` eşlemesi ekler (host = `local` ya da hosts.json adı; hedef o makineden görülen adres).
- Tek kayıt biçimi `conf.d/<id>.yaml`: `id, host, target, mount, rewrite?, tls?, websocket?, roles?`. Ekle/sil kod değişikliği ve restart gerektirmez (derbent canlı reload; copsd mounts.json mtime ile).
- Yol: tarayıcı -> panel (tünel) -> copsd: `mount` önekini eşleyip panel kimliğini (token/`cops_ext` çerezi) denetler, panel kimliğini siler, derbent'in uygulama portuna iletir (WS dahil) -> derbent: köken/Host/Origin yeniden yazımı, uzak host ise o host'un derbent'ine mTLS hop -> hedef.
- Mount yolu upstream alt yoluyla AYNI seçilirse (Grafana `serve_from_sub_path`, `/grafana/`) önek yeniden yazımı gerekmez; farklı önek yeniden yazımı kapsam dışı.
- Doğrulama: mount çakışması ve panel yolları (`/api`, `/ws`, `/q`, `/desktop`, `/assets`, kök) reddedilir; uzak hedef erişilemezse kayıtta uyarı. Yetki: enterprise rolleri (tek kullanıcıda sahip) + denetim kaydı. Arayüz: `cops app add|list|rm`, Araçlar>Uygulamalar formu, keşif önerisi tek tıkla eşleme.
- Ölçüm (21 Kas): ulak_31 -> `https://10.20.4.165/grafana/login` HTTP 200, 70 ms.
- Kabul: telefondan (390 px) `<tünel>/grafana/` dashboard, live panel, giriş/çıkış, bir POST; ikinci örnek yerel varaka :8080 `/varaka/`.
