# rs/gate (İz W0-c: kapı)

**Durum (26 Kas 2026 akşam): BİRLEŞTİRMEYE HAZIR DEĞİL.** Dört görevin kodu ve testleri bitti; sahibin sonradan eklediği iki
zorunlu belge (aşağıda "Açık işler" 1 ve 2) yapılmadı. Canlı `copsd` ikilisine ve servislere dokunulmadı.

## Açık işler (sırayla)

1. [ ] **Ders listesi (EK, sahip):** `docs/rust-lessons-from-python.md` genel liste + bu izin kontrol listesi ZORUNLU; her maddeyi
   burada test adı ya da gerekçeyle karşıla. 26 Kas 17:25'te dosya henüz yoktu (ana checkout'ta da yok): yeniden bak.
2. [ ] **Eşleme tablosu (EK 2, sahip):** izin kapsadığı Python modüllerindeki HER işlev/metot/sınıf/modül düzeyi atama (`ast` ile)
   bir satır: `Python adı (dosya:satır) | Rust karşılığı | parite testi | durum`; o modüllerin `py/tests` altındaki HER `test_*`
   metodu bir satır (Rust testi ya da neden gereksiz). Boş / "sonra" satırı varken HAZIR yazma. Kenar durumları (boş girdi, bozuk
   JSON/dosya, Unicode, eksik alan, eşzamanlı yazım, zaman aşımı) Python gibi; Python hatalı görünüyorsa SESSİZCE düzeltme,
   "Python hatası?" diye işaretle ve STEWARD-ASK ile sor. cops birleştirme kapısında tabloyu `ast` çıktısıyla karşılaştırır.
   Aday kapsam (henüz doğrulanmadı): `py/claudeops/front.py`, `commands/front_cmd.py`, `commands/web.py` içindeki kimlik/ön kapı
   parçaları (`_authorized`, `_Handler` yönlendirme başı, `_internal` uçları); testler `test_front_{cmd,internal,xff}.py`.
3. [ ] `cops-parity`yi gerçek Python iç portuna karşı bir kez koş (geçici `--state-dir`li deneme `copsd`si, yalnız GET) ve
   `requests/basic.json`daki `dynamic`/`unordered` desenlerini gerçek `/api/status` çıktısına göre ayarla. Örnek liste hiç
   gerçek veriye karşı koşmadı.
4. [ ] Bitince son satır: `BİRLEŞTİRMEYE HAZIR: rs/gate <commit> <test özeti>`.

## Yapılanlar

### 1. Çoklu rota kaydı (`cops_proxy::routes::RouteTable`)

- Sonraki izlerin kayıt yeri TEK işlev: `copsd/src/routes.rs::register(&mut table, &RouteCtx)` (şimdilik boş).
  `table.get("/api/files/*", hook)` (kimliği vekil denetler) ya da `table.own_auth("POST", "/api/start", hook)`.
- Eşleşme: yöntem + tam yol ya da `/.../*` öneki; tam yol > uzun önek > kısa önek. `route()` `None` dönerse sıradaki aday, sonra
  eski tek kanca (`Hooks.routes`, enterprise), sonra `try_local`, sonra Python.
- Boru hattı sırası: mount'lar -> `/api/front/stats` -> `force_proxy` -> statik -> metrik -> tablo -> tek kanca -> yerel uç -> Python.
- Yinelenen kayıt, bozuk desen, `/*`, `/api/_internal*`, `/api/front/*`: açılışta panik.
- Karar: panel kimlikli kayıt yalnız GET (yazma yetkisinin kaynağı gövdede olabilir; `LocalAuth` yalnız başlık/sorgu görür).
- Tablo boş değilse ve `web.token` yok / 0600 değilse tablo HİÇ takılmaz (istek Python'a).

İzler için sınırlar:
- `LocalAuth` "izin" derse kanca KİMİN sorduğunu bilmez. Çok kullanıcıda kullanıcıya göre süzülen veri (T1 `/api/status`, K3)
  `own_auth` ister ya da sözleşmeye `Principal` eklenmeli.
- `RouteResponse.body` tamponlu `Vec<u8>`, WS yükseltmesi yok: T2 (`/ws/term`) ve T3 (indirme, mp3 akışı) için sözleşme genişlemeli.
- Yol HAM karşılaştırılır (yüzde çözme yok).

### 2. `force_proxy`

- Dosya `<durum dizini>/front_force_proxy` (`--force-proxy-file`): satır başına yol öneki, `#` yorum, `*` hepsi; yazım
  `ent_auth_force_proxy` ile aynı. Statik, metrik, tablo, tek kanca ve yerel uca uygulanır; mount'lara ve `/api/front/stats`a DEĞİL.
- Okuma: açılışta ve SIGHUP'ta. Dosya yok = boş. İlk okumada okunamazsa `*`; SIGHUP'ta okunamazsa eski liste. 512 satır üstü `*`.
- Canlıda uygulama: `systemctl --user kill --kill-who=main -s HUP claudeops-front.service`.
  **DİKKAT:** bugünkü canlı (eski) `copsd` SIGHUP işlemez, sinyal onu ÖLDÜRÜR; komut yalnız yeni ikili konduktan sonra.
  `front.py`/`cops front` birimine `ExecReload` eklenmedi (izin dışı yol).
- **DİKKAT (enterprise):** `ent_auth_rust_write=on` iken `/api/auth`, `/api/enterprise/*` (ya da `*`) bu listeye yazılırsa yazma
  Python'a gider ("tek yazar" bozulur). Orada geri alma `ent_auth_force_proxy` iledir. Canlıda yazma kipi kapalı.

### 3. `GET /api/front/stats`

- Kimlik: `web.token` ya da loopback + `X-Cops-Front`. Çok kullanıcıda da yalnız bunlar.
- `totals`, `endpoints[{method,path,local,fallback,forced,upstream_error}]`, `other`, `routes`, `force_proxy`, `started_at`.
  Mount istekleri sayılmaz. Sayaçlar bellekte (yeniden başlatmada sıfır).
- Anahtar sınırı: `/q/`, `/readfile/` ve API dışı yollar ilk parçaya iner, kimlik benzeri parçalar `*`, yeni anahtar yalnız
  401/403/404 dışı yanıtla, en çok 512; gerisi `other`.

### 4. `cops-parity`

- `cargo run -p cops-parity -- rust/crates/cops-parity/requests/basic.json` (yol çalışılan dizine göre); `--help` tam liste.
- Anahtar sırası önemsiz, `1` == `1.0`; liste başına `ignore` / `dynamic` (tür aynı olmalı) / `unordered`; bilinmeyen alan hata.
- Varsayılan yalnız GET/HEAD ve `side_effect_free: true`; `--include-unsafe` her isteği İKİ kez uygular.
- İstek `X-Cops-Parity: 1` taşırsa ön kapı `X-Cops-Served: local|python` döner; `expect: "local"` sahte pariteyi yakalar.
  Başlık istenmezse yanıtlar değişmez; üst sunucunun aynı adlı başlığı silinir.
- Gövde değerleri raporda yazılmaz (`--show-values` ile). Loopback dışı adres `--allow-remote` ister.
- Bilinen kasıtlı fark: `/api/steward/questions?all=1|since=` Rust'ta çıplak dizi (Danış sözleşmesi); listeye konmadı.

## `cops-proxy` / `copsd` genel API

Kırıcı değişiklik YOK, yalnız ek: modüller `routes`, `force`, `stats`; `Proxy::with_route_table|with_force_proxy|with_stats`;
`StatsCfg`, `PARITY_HEADER`, `SERVED_HEADER`; `copsd::routes::{register, RouteCtx}`. `copsd::Hooks` alanları değişmedi.
`/api/front/stats` yalnız `with_stats` takılıysa yerel (copsd takar, dolayısıyla `copsd-ent` de alır; `force_proxy` ve SIGHUP da).

## Doğrulama (26 Kas)

- `cargo test -p cops-proxy -p copsd -p cops-parity`: 85 geçti, 0 kaldı, 1 atlanan (önceden de `ignored`).
- `cargo clippy -p cops-proxy -p copsd -p cops-parity --all-targets -- -D warnings`: temiz; `cargo fmt --check` temiz.
- Enterprise `34cfdd3` `copsd-ent`, scratchpad kopyasında `--config patch` ile bu dala karşı: `check --all-targets` ve testler geçti
  (50 geçti, 0 kaldı). Enterprise reposuna yazılmadı.
- Python `test_front_internal.py` (CSP eşitliği `lib.rs`i okur), `test_front_cmd.py`, `test_authz_vectors.py`: geçti.
- Testler yalnız geçici dizin ve boş port kullanır.
