# İz T5 federasyon istemcisi (`rs/hosts`, crate `cops-hosts`)

## Durum (26 Kas 2026, devir anı): BİRLEŞTİRMEYE HAZIR DEĞİL

Kütüphane kodu yazıldı ve derleniyor; `cargo clippy -p cops-hosts --all-targets -- -D warnings` temiz;
`cargo test -p cops-hosts` 17/17 geçiyor. Testler YALNIZ `endpoint`, `guard`, `record`, `flight`, `tier` birim testleri.
`http`, `proxy`, `status`, `health`, `federation`, `relay`, `push`, `ws`, `grpc`, `net`, `sign` için HİÇ test yok:
sahte sunuculu entegrasyon testi ve Python parite testi yazılmadı. Test edilmemiş davranış doğrulanmış sayılmaz.
Hiçbir yere bağlanmadı (copsd/cops-proxy bu crate'i henüz çağırmıyor). Gerçek uzak host'a istek atılmadı.

## Sıradaki işler (sırayla)

1. `tests/fake.rs`: 127.0.0.1 rastgele portta sahte HTTP sunucusu (hyper server). Senaryolar:
   - havuz: keep-alive yeniden kullanımı; sunucunun kapattığı boş bağlantı; bayat bağlantıda GET yeniden denenir,
     karşıya ulaşmış POST denenmez; 100 zaman aşımı sonrası `/proc/self/fd` sayısı artmaz.
   - zaman aşımı: yanıt vermeyen, damla damla yanıt veren, dev gövde, JSON olmayan, nesne olmayan yanıt.
   - vekil: bilinmeyen host, `host=local` zorlaması, sır gövdesi düz http'de gitmez, `input_id` 3 deneme, 404/502.
   - dedup: eşzamanlı aynı URL tek istek; farklı kimlik ayrı anahtar; iptal edilen görev uçuşu bırakır.
   - yükleme: erken biten ve taşan gövde hata; ilerleyen yavaş gövde kesilmez; indirme başlık süzgeci.
   - imza: her denemede yeni imza, `Unbound`da imza yok, red = 502 ve istek GİTMEZ, panik ve yasak başlık = red.
2. Poller/health testleri: N ardışık hata toleransı, `extra_urls` yedeği ve https'ten düşmeme, bozuk satırlar,
   `merge_status` sıralaması, breaker, `probe_facts` (404, geçici hata önbelleğe yazılmaz), `remote_post`/`remote_stop`.
3. WS ve gRPC: sahte `/ws`, `/ws/term` (tokio-tungstenite server) ve sahte tonic servisi; sessizlik watchdog'u, ölü
   relay yeniden kurma, DNS adı loopback'e çözülünce red (sahte `Resolver`). TLS: özel kök ile bir tur.
   gRPC'de `Dial` + `origin` ile https yolunun gerçekten çalıştığı DOĞRULANMADI.
4. `tests/parity.rs`: route kümeleri = `web_hosts.py`; her host-routed yol `cops_auth::authz::action_for` ile
   `UNMAPPED` değil; `grpc::pb` alan numaraları = `host_bridge.proto`; hata metinleri = `hosts.ERR`.
5. Bu belgedeki kontrol listelerini test adlarıyla güncelle, sonra "BİRLEŞTİRMEYE HAZIR".

## Modüller

| Modül | Python karşılığı |
|---|---|
| `record` | `hosts.py` (model, doğrulama, upsert, remove, promote; G/Ç YOK) |
| `guard`, `endpoint`, `net` | SSRF süzgeci, aday adres kuralı, peer denetimi |
| `http`, `flight`, `proxy` | `_http_json`/`_http_raw`, havuz, dedup, `proxy_*` |
| `status`, `tier`, `federation` | indirgeme, önbellek, `merge_status`, poller, prober, `/api/hosts` satırları |
| `push`, `ws`, `grpc`, `relay` | `_PushConsumer`, `web_grpc` istemcisi, term relay |
| `sign` | `authz.outbound_headers` karşılığı: `OutboundSigner` trait (enterprise doldurur) |
| `health` | `web_steward` istemci parçaları: breaker, facts yoklaması, dosya kapısı, uzak eylem |

## Entegrasyon sözleşmesi (copsd tarafı için)

- Host kayıtları `HostSource` ile verilir (`cops-state` gelince onunla doldurulur). `promote` kilit altında oku,
  `record::promote_base_url`, atomik yaz; `hosts.json` yazımı, bozuk dosya yedeği ve kilit BU CRATE'TE DEĞİL.
- Bağlanacak uçlar: `/api/hosts` GET/POST/remove/test, host-routed GET/POST, indirme, yükleme, `/ws/term` uzak dalı.
- Yerel yetki (K1/K2) ve yükleme/indirme boyut sınırı çağıranındır; vekil yalnız yerel kapıdan geçen isteği iletir.
- `Federation::term_output` tier `rest` iken çağrılmamalı (Python gibi: o dalda `proxy_get`).

## Python'dan bilinçli farklar

- Host'lar eşzamanlı yoklanır (Python sıralı); push/poll görevleri iptal edilebilir görevlerdir.
- Zaman aşımı adım başı + mutlak tavan (600 sn); yüklemede "ilerleme yok" süresi. Yanıt gövdesi sınırlı.
- İmza host adını kayıttan alır (Python base_url eşleşmesinden; yedek adreste boş ad veriyordu). Signer paniği ve
  geçersiz/taşıma başlığı = RED (Python boş başlıkla gönderiyordu).
- Dedup anahtarında kullanıcı kimliği var (Python yalnız URL).
- Peer denetimi bağlanmadan ÖNCE, REST/WS/gRPC aynı kurucudan.
- URL'de `user@`, sorgu, parça reddedilir. Özel ağ http istisnası yalnız RFC1918 + IPv6 ULA.
- Vekil `token`/`ticket`/`host` sorgu parametrelerini uzağa taşımaz.
- `/api/status` yoklamasında 2xx dışı yanıt hata.
- `extra_urls` seçimi (`probe_choice`) kayıtlı adaylarla ve https düşürmeme kuralıyla sınırlı.
- WS en büyük mesaj 16 MiB (Python varsayılanı 1 MiB). Uzak WS URL'si taban yolunu korur (Python düşürüyordu).
- Term relay kayıt (adres/token) değişince yeniden kurulur.
- Bilinen eşit davranış (düzeltilmedi): gRPC çağrıları imzalanmaz.

## Ders listesi 2.11 (federasyon)

Durum: T = testli, K = kodda var, TEST YOK, A = açık.

| Madde | Durum | Karşılık |
|---|---|---|
| `Remote<T>`; yıkıcı eylem yalnız `Ok` | K | `health::Remote`, `exact_target` + `remote_stop`; `remote_post` yıkıcı yolu reddeder |
| SSRF tablo, menzil istisnası yalnız `extra_urls` | T | `guard::tests::*`, `record::tests::validation_order` |
| HTTPS'ten düz HTTP'ye sessiz düşüş yok | T (kural), K (poller) | `https_never_downgrades_to_public_http`, `try_fallback_urls` |
| Breaker, probe başarısında sıfırlama, yavaş okuma suçlamaz | K | `Breaker::{settle,clear}`, `TickState::record_reads` |
| Yetenek yoklaması, eski sürüme zarif düşüş | K | `CapabilityCache::probe_facts`, `Remote::Unsupported` |
| Route = host-routed = yetki tablosu eşitlik testi | A | iş 4 |
| Deploy smoke | gerekçe | kütüphane; ikili ve deploy copsd entegrasyonunda (cops) |
| Açık, uzun zaman aşımı | K | `Timeouts` (`long_read` 90 sn çağıran seçer) |
| İmzalı kimlik: istemci başlığı güvenilmez, gövde özeti | K | vekil istemci başlığı taşımaz, gövde signer'a verilir; doğrulama alıcıda |
| hosts.json kilitli yaz, db kipinde DB | gerekçe | bu crate yazmaz (`cops-state`); `record` saf |
| Uzak WS kapanışı + sessizlik watchdog'u | K | `push`, `STATUS_PUSH_SILENCE`, `TERM_RELAY_SILENCE`; düşürülen görev soketi kapatır |

## Genel gözden geçirme listesi (20 madde)

| # | Durum | Not |
|---|---|---|
| 1 hedef Unique | K | `exact_target` tam ad, birden çok eşleşme `ambiguous` |
| 2 atomik yazım | gerekçe | dosya yazımı yok |
| 3 belirsiz = kapalı | K | signer paniği red, bozuk belge yazılmaz (T), `Remote` ayrımı |
| 4 sonuç doğrulama + negatif test | A | negatif testler iş 1-3 |
| 5 hata yutma | A | `.ok()`/`let _` taraması yapılmadı (WS kapanışı ve TCP nodelay bilerek yutuluyor) |
| 6 bayat önbellek | K | kayıtlar her turda okunur; hata `last_good`u ezmez; test yok. Sistem TLS kökleri süreçte bir kez yüklenir |
| 7 sınırlı döngü | K | yeniden deneme 2 ve 3; poller/prober sonsuz ama `Running` düşünce durur; dedup TTL + LRU (T) |
| 8 CLI/TUI fixture | gerekçe | TUI yok |
| 9 sahiplik, fd sızıntı testi | A | görevler `Drop` ile iptal; fd testi iş 1. Havuz bağlantı görevi karşı taraf kapatınca biter |
| 10 girdi sınırları | kısmen T | URL, kayıt, belge testli; uzak yanıt tipleri testsiz |
| 11 metin ayrıştırma | gerekçe | yok |
| 12 Python paritesi | A | iş 4; `py_strip` kullanıldı, `$HOME` erişimi yok |
| 13 sırlar | T (kayıt) | `Secret`, `public()`; hata metinleri URL taşımayacak şekilde yazıldı, testi iş 1 |
| 14 adres denetimi | T (guard), A (bağlantı) | canonical `::ffff:` testli; DNS rebinding testi iş 3 |
| 15 kullanıcı yolu e2e | A | copsd entegrasyonundan sonra |
| 16 route tabloları | A | iş 4 |
| 17 test yalıtımı | T | testler dosya yazmaz, canlı dizine dokunmaz |
| 18 uzak sürüm/deploy notu | K | uzak hostlara deploy gerektirmez (istemci tarafı) |
| 19 GIT_SHA / geri dönüş | gerekçe | ikili yok |
| 20 kanıt | yapıldı | perf iddiası yok; Python'a yazılmadı |

H1-H21'den bu ize değen diğerleri: H1 (bağlantı sahipliği: iş 1 fd testi), H18 (WS çerçeveleme: iş 3), H20 (olaylar
`Events` ile, token'sız alanlar), H15/H4/H6 kapsam dışı (vekil sunucu, TUI, metin işareti yok).
