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

## Mount (copsd): panel adresi altında uygulama (21 Kas)

Panel adresi `<panel>/<id>/` istekleri copsd'de panel kimliğinden geçer, sonra yerel derbent'in o uygulamaya ayrılmış loopback portuna AKIŞLI iletilir (HTTP + WebSocket, Python'a uğramaz). Kod: `rust/crates/cops-proxy/src/mount.rs`, `Proxy::handle_mount`; testler `crates/cops-proxy/tests/mounts.rs`.

- **Dosya:** `copsd --mounts-file` (varsayılan `~/.claude/claudeops/derbent/mounts.json`). Biçim: `[{"path":"/grafana/","upstream":"127.0.0.1:18101"}]`. Yalnız `path` ve `upstream` anahtarları (bilinmeyen anahtar = hata). `path` = tek segment kimlik `/<id>/`, `id` `[a-z0-9][a-z0-9_-]*` (en çok 63); `upstream` = loopback `ip:port` (port != 0); en çok 256 girdi, 1 MB. Aynı yol iki kez = hata. Hata varsa dosyanın TAMAMI reddedilir.
- **Yasaklı kimlikler** (panelin kendi yolları, `mount::RESERVED`, testle sabit): `api`, `ws`, `assets`, `q`, `readfile`, `v1`, `desktop`, `favicon.svg`, enterprise `readlist`, `missing`. Yeni bir panel üst düzey yolu eklenirse bu liste de güncellenir. Eklenti `register_route` önekleri dinamik olduğu için listede olmayan bir önekle aynı ad verilirse mount kazanır.
- **Yükleme:** dosya yoksa, düz dosya değilse ya da izinleri 0600 değilse mount KAPALI (istekler eskisi gibi Python'a). Arka plan görevi 2 sn'de bir `stat` yapar (sıcak yolda dosya okuma yok); mtime/ctime/boyut/inode/kip değişince yeniden okur. Bozuk içerikte son geçerli tablo korunur ve stderr'e bir satır yazılır; her geçerli yükleme de tabloyu tek satırda yazar (`copsd: mount yüklendi ...`). Tablo boşken istek başına maliyet tek atomik okumadır. `web.token` yoksa ya da 0600 değilse mount hiç açılmaz.
- **Kimlik:** geçerli panel token'ı (`?token=` ya da `Authorization: Bearer`) ya da geçerli `cops_ext` çerezi (`HMAC-SHA256(key=token, "claudeops-ext-session")` hex, Python `extensions.cookie_ok` ile aynı kural, sabit zamanlı). Yoksa 401 (kısa düz metin; `Accept: text/html` ise küçük bir 401 sayfası, panel girişine yönlendirme YOK). Kimliksiz istek `/<id>` için de 401 alır (mount varlığı sızmaz).
- **Yönlendirmeler:** `/<id>` (sonda `/` yok) -> 308 `/<id>/` (sorgu korunur). `?token=` ile gelen GET/HEAD -> 302 ile `token` parametresi silinmiş adrese; çerez yoksa yanıtta `Set-Cookie: cops_ext=<hmac>; Path=/; HttpOnly; SameSite=Strict` (panelle aynı çerez; `Path=/` bilinçli). `Secure` yalnız istemci https ise: copsd TLS sonlandırmadığı için https yalnız loopback eşten (aynı makinedeki tünel/ters vekil) gelen `X-Forwarded-Proto: https` ile kabul edilir. GET dışı yöntemde yönlendirme yapılmaz (yöntem korunur): token sorgudan silinip aktarılır, çerez yanıta eklenir.
- **Upstream'e GİTMEYENLER:** `token` sorgu parametresi (yüzde-kodlu adı dahil), `Authorization`, adı `cops_` ile başlayan çerezler (`cops_ext`, enterprise `cops_t`), istemcinin `X-Cops-Front*`, `X-Forwarded-For/Proto/Host`, `Forwarded`, `X-Real-IP` başlıkları; ön kapı gizlisi uygulamaya hiç eklenmez. Diğer çerezler (ör. `grafana_session`) tek `Cookie` başlığında aynen geçer.
- **Korunanlar:** `Host` DEĞİŞMEZ, yol DEĞİŞMEZ (önek yeniden yazımı yok: mount yolu = uygulamanın alt yolu, ör. Grafana `serve_from_sub_path` ile `/grafana/`). copsd `X-Forwarded-For` (eş IP) ve `X-Forwarded-Proto` (`http|https`, yukarıdaki kural) yazar; derbent `{origin}` yeniden yazımı bunlara dayanır. Yanıt gövdesi tamponlanmaz (SSE ve 100 MB akış testli, bellek sabit); uygulamanın `Set-Cookie` başlıkları aynen döner.
- **Bilinen sınırlar:** panel token'ı değişirse copsd yeniden başlatılana kadar eski token ve çerez geçerli kalır (diğer yerel uçlarla aynı); çok kullanıcı (enterprise authenticator, `cops_t`) kipinde mount kimliği henüz yok, yalnız tek kullanıcı `web.token`; `mounts.json`'u enterprise Uygulamalar kaydı yazar (bkz. "Faz 3b uygulaması").

## Faz 3b uygulaması: kayıt, mounts.json, CLI (21 Kas, enterprise `derbent-int`)

Kod: claudeops-enterprise `claudeops_enterprise/apps/{registry,mounts,upstream,api,cli}.py`, testler `tests/test_apps_mounts.py`. Çekirdekte değişiklik yok (`cops app` mevcut `register_command` kancasıyla gelir).
- **Kayıt alanları:** `id, host, target, mount, rewrite?, tls?, websocket?, roles?` (+ eski `name, project, via, gate, max_body, timeout, local_port`). Saklama bugünkü gibi: claudeops meta `apps.json` + derbent `conf.d/<id>.yaml`. Neden tek dosya değil: derbent `deny_unknown_fields` ile `mount`/`roles`/`target` anahtarlarını reddeder; D3 `meta:` gelince conf.d tek kaynak olur. derbent'in kendi `host` alanı (yalnız saklanır) conf.d'ye yazılır.
- **Geriye uyum:** `mount` yoksa eski davranış (yerel port + bilet kapısı). API'de `mount: true` = `/<id>/`; CLI'da varsayılan `/<id>/`, `--no-mount` eski davranış.
- **Yol:** derbent `uri`'nin yalnız şema + host:port kısmını kullanır (README "only scheme and host:port are used"; `AppConfig.uri` "a path here is ignored"), istek yolunu DEĞİŞTİRMEDEN iletir. Bu yüzden conf.d `uri` her zaman köken + `/`; `target` alt yolu yalnız mount ile aynıysa kabul edilir (`https://10.20.4.165/grafana/` + `/grafana/`), farklıysa red (önek yeniden yazımı yok). `/grafana/login` isteği hedefe `/grafana/login` olarak gider.
- **mounts.json:** her ekle/sil/resync'te `<CLAUDEOPS_DIR>/derbent/mounts.json` yeniden üretilir (0600, tmp + rename, içerik aynıysa dokunulmaz): yalnız mount'u olan ve açılabilir kayıtlar, `upstream` = derbent'in o uygulamaya ayırdığı `127.0.0.1:<18100-18199>`. 422 geri almada da son geçerli kayıtlardan yeniden üretilir.
- **Mount'ta bilet kapısı yok:** kimlik copsd'de (panel token / `cops_ext`); copsd uygulamaya gizli bir şey eklemediğinden derbent `ExternalFilter` kapısı bu istekleri ayırt edemez. Aç düğmesi mount'lu uygulamada panel yolunu (`/<mount>/`) döner.
- **Doğrulama:** mount tek segment `/<ad>/`, `[a-z0-9][a-z0-9_-]*` en çok 63; kök ve `RESERVED` (copsd listesiyle birebir, test mount.rs'i okuyup kilitler) red; aynı/iç içe mount red; host `local` ya da hosts.json adı; hedef http/https; `rewrite` derbent şemasıyla doğrulanıp birebir iletilir (kısa biçim köken dizesi ya da `{rules, content_types, encoding, headers, request_headers, host_header}`).
- **Erişim denemesi (yalnız uyarı, yazımı engellemez):** yerel hedefe 0,5 sn TCP; uzak hedefe hosts.json kanalıyla o host panelinin `GET /api/enterprise/apps-admin/probe?target=` ucu (o uç hedefe HEAD atar, salt-okunur, denetime yazılır). Kanal/uç yoksa ya da erişilemezse kayıt `warning` ile yazılır.
- **Uzak host (hop yok):** kayıt saklanır, `warning: "uzak hop kurulu değil"`, conf.d'ye ve mounts.json'a girmez, Aç 409. Kanca: `upstream.set_remote_hop(fn)`, `fn(kayıt) -> yerel derbent uri | None`; `resolve_upstream(kayıt)` tek bağlantı noktası, hop bağlanınca `resync()` conf.d + mounts.json'u üretir. Uzak kayıtta pinsiz `tls.verify: false` uyarıyla kabul (hedef TLS'i uzak hop'ta kurulur); yerelde eskisi gibi pin şart.
- **CLI:** `cops app add <id> --host H --target URL [--mount /yol/ | --no-mount] [--rewrite KÖKEN [--rewrite-to {origin}]] [--websocket] [--roles a,b] [--tls-insecure] [--tls-pin X]`, `cops app list [--json]`, `cops app rm <id>`; her alt komutta `--port` (varsayılan 8765). Panel API'sini `web.token` ile çağırır (tek yazım yolu panel süreci).
- **Yardımcı süreç düzeltmesi:** `review.py` içe aktarımı ve `cops <eklenti komutu>` eklentiyi yükleyip `_register_apps`'ı çalıştırıyordu; kapı portu panelde olduğundan süzgeç başlatılamıyor, `gate=""` ile `resync()` canlı conf.d'den bilet kapısını kaldırıyordu. Artık kapı portu başka süreçteyse yardımcı süreç conf.d'ye dokunmaz, gözcü başlatmaz.
- **Örnek kayıtlar (testte):** Grafana `{id: grafana, host: ulak_31, target: https://10.20.4.165/, mount: /grafana/, rewrite: {rules: [{from: "https://10.20.4.165", to: "{origin}"}]}, tls: {verify: false}, websocket: true}`; varaka `{id: varaka, host: local, target: http://127.0.0.1:8080, mount: /varaka/}`. Üretilen conf.d gerçek `derbent check` ile geçer (Grafana sahte hop ile). Not: varaka kökte yayın yapıyorsa `/varaka/...` yolunu tanımaz; önek soyma kapsam dışı (uygulamanın alt yol ayarı gerekir).
