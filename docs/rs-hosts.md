# İz T5 federasyon istemcisi (`rs/hosts`, crate `cops-hosts`)

## Durum (26 Kas 2026, devir anı): BİRLEŞTİRMEYE HAZIR DEĞİL

Kütüphane kodu yazıldı ve derleniyor; `cargo clippy -p cops-hosts --all-targets -- -D warnings` temiz;
`cargo test -p cops-hosts` 44/44 geçiyor (17 birim + 27 sahte sunuculu entegrasyon; art arda 8 koşu, oynak değil).
Birim: `endpoint`, `guard`, `record`, `flight`, `tier`. Entegrasyon (iş 1, `tests/fake_*.rs`): `http` havuzu ve zaman
aşımları, `proxy` (vekil, dedup, yükleme/indirme), `sign` (imza kapısı), `net` (REST yolunda DNS-loopback reddi).
`status`, `health`, `federation`, `relay`, `push`, `ws`, `grpc` için HİÇ test yok (iş 2-3); Python parite testi yok (iş 4).
Test edilmemiş davranış doğrulanmış sayılmaz.
Hiçbir yere bağlanmadı (copsd/cops-proxy bu crate'i henüz çağırmıyor). Gerçek uzak host'a istek atılmadı.

## Sıradaki işler (sırayla)

1. BİTTİ (26 Kas): `tests/support/mod.rs` (hyper `Fake` + çıplak TCP `Raw`, sunucu tarafı sayaçlar, sayan sahte
   `Resolver`, `TestSigner`), `tests/fake_http.rs` (9), `tests/fake_proxy.rs` (17), `tests/fake_fd.rs` (1). Test adları
   aşağıdaki "İş 1 test eşlemesi" tablosunda. Kapsanamayanlar o tablonun altında. Senaryolar (özgün liste):
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

### İş 1 test eşlemesi

| Senaryo | Test |
|---|---|
| keep-alive yeniden kullanımı (GET+POST, tek bağlantı) | `fake_http::pool_reuses_one_keepalive_connection` |
| sunucunun kapattığı boş bağlantı (POST bile düşmez) | `fake_http::server_closed_idle_connection_does_not_fail_post` |
| bayat bağlantıda GET tek kez yeniden, her denemede yeni imza | `fake_http::stale_pooled_get_is_retried_once_with_fresh_signature` |
| karşıya ulaşmış POST yeniden denenmez (sunucu sayacı 1, yeni bağlantı yok) | `fake_http::stale_pooled_post_that_reached_server_is_not_retried` |
| 100 GET + 100 POST zaman aşımı sonrası fd artmaz, sunucu her soketin kapandığını görür | `fake_fd::hundred_timeouts_do_not_leak_sockets` |
| yanıt vermeyen sunucu (adım sınırı, POST yeniden denenmez) | `fake_http::silent_server_times_out_and_socket_is_closed` |
| damla damla yanıt: mutlak tavan keser | `fake_http::drip_feed_response_is_cut_by_total_cap` |
| dev gövde (1 TiB bildirimli) reddi, bağlantı kapanır; sınır tam | `fake_http::huge_response_body_is_refused_and_connection_dropped`, `max_body_boundary_is_exact` |
| JSON olmayan / nesne olmayan / boş / 502 HTML; 404 ve 500 JSON aynen geçer | `fake_http::non_json_non_object_and_error_statuses` |
| bilinmeyen host: 5 vekil yolunda istek ve imza yok | `fake_proxy::unknown_host_sends_nothing_and_does_not_sign` |
| `host=local` zorlaması, `host/token/ticket` süzgeci, taban yolu | `fake_proxy::outgoing_host_is_forced_local_and_caller_query_is_filtered` |
| sır gövdesi düz http'ye gitmez (ad çözülmeden red); loopback'e gider; DNS adı loopback'e çözülünce bağlantı yok | `fake_proxy::secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked` |
| `input_id` 3 deneme aynı kimlikle, deneme başı kısa sınır; uzak ok:false / kimliksiz / geçersiz kimlik / başka yol = 1 | `fake_proxy::term_input_retries_three_times_with_same_input_id` |
| dedup: eşzamanlı aynı URL tek istek, sonra son başarılı yanıt | `fake_proxy::concurrent_same_url_sends_one_request_and_reuses_last_good` |
| dedup anahtarında kimlik (alice/bob/Unbound ayrı) | `fake_proxy::dedup_key_includes_identity` |
| iptal edilen görev uçuşu bırakır | `fake_proxy::cancelled_task_releases_its_flight` |
| `dedup:false` eşzamanlı iki istek | `fake_proxy::dedup_off_lets_concurrent_requests_through` |
| eşzamanlı aynı indirme geri çevrilir, önbelleğe alınmaz | `fake_proxy::concurrent_same_download_is_refused_not_cached` |
| yükleme: erken biten ve taşan gövde hata, sunucuya tam istek ulaşmaz | `fake_proxy::upload_body_ending_early_or_overflowing_is_an_error` |
| yavaş ama ilerleyen yükleme kesilmez (gövde, başlıklar, sorgu doğru) | `fake_proxy::slow_but_progressing_upload_is_not_cut` |
| duran yükleme zaman aşımı; JSON olmayan yükleme yanıtı | `fake_proxy::stalled_upload_times_out_and_bad_reply_is_reported` |
| indirme: ham gövde, yalnız 2 başlık, uzak durum aynen | `fake_proxy::download_passes_raw_body_and_only_two_headers` |
| `Unbound` imzalanmaz (4 yol) | `fake_proxy::unbound_caller_is_never_signed` |
| imza: sorgusuz yol (taban dahil), tam gövde, akış gövdesiz | `fake_proxy::user_caller_is_signed_over_path_and_body_without_query` |
| red/panik/yasak başlık (12 durum) = 502, yeniden deneme yok, hiç bağlantı açılmaz | `fake_proxy::signer_refusal_panic_and_bad_headers_are_502_and_nothing_is_sent` |
| hata metinlerinde URL, port, token yok (kapalı port, susan, bozuk yanıt, geçersiz URL x 4 yol) | `fake_proxy::error_texts_carry_no_url_port_or_token` |

Testlerin gerçekten yakaladığı, kaynakta geçici bozmayla (mutasyon) doğrulandı: POST'u yeniden denemek, `sent`
bayrağını yok saymak, erken biten gövde denetimini kaldırmak, sır süzgecini kaldırmak, sorgu süzgecini kaldırmak, uçuşu
bırakmamak, dedup anahtarından kimliği çıkarmak, gövde sınırında bir fazla: hepsi en az bir testi düşürdü. Kaynak geri
alındı (diff yok). Tek istisna: havuzdaki `is_closed` denetimini kaldırmak testi düşürmez, çünkü ölü bağlantıya istek
hiç yazılamaz (`!sent`) ve güvenli yeniden deneme devreye girer; iki yol da doğru, dışarıdan ayırt edilemez.

Kapsanamayanlar (iş 1 içinde): bağlanma aşamasında zaman aşımı (loopback hemen bağlanır; yönlendirilemeyen adres
loopback dışına istek olurdu), `!sent` POST yeniden denemesinin kendi başına deterministik sınaması (yukarıdaki yarış),
TLS (iş 3), `long_read` (yalnız değer; çağıran seçer). Üretim koduna dikiş EKLENMEDİ: IP literali kayıt anında
denetlendiği için bağlantı kurucu 127.0.0.1'e izin verir; DNS yolu için mevcut `net::Resolver` kullanıldı.
Bulunan hata: yok (Rust kodunda değişiklik yapılmadı). Python ile bilinen fark `ticket` süzgeci (aşağıda) dışında yeni
fark görülmedi.

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
| Açık, uzun zaman aşımı | T (adım + tavan + terminal deneme sınırı), K (`long_read`) | `Timeouts` (`long_read` 90 sn çağıran seçer) |
| İmzalı kimlik: istemci başlığı güvenilmez, gövde özeti | T (signer tam gövdeyi ve sorgusuz yolu alır) | vekil istemci başlığı taşımaz, gövde signer'a verilir; doğrulama alıcıda |
| hosts.json kilitli yaz, db kipinde DB | gerekçe | bu crate yazmaz (`cops-state`); `record` saf |
| Uzak WS kapanışı + sessizlik watchdog'u | K | `push`, `STATUS_PUSH_SILENCE`, `TERM_RELAY_SILENCE`; düşürülen görev soketi kapatır |

## Genel gözden geçirme listesi (20 madde)

| # | Durum | Not |
|---|---|---|
| 1 hedef Unique | K | `exact_target` tam ad, birden çok eşleşme `ambiguous` |
| 2 atomik yazım | gerekçe | dosya yazımı yok |
| 3 belirsiz = kapalı | kısmen T | signer paniği ve yasak başlık red (T, iş 1), bozuk belge yazılmaz (T), `Remote` ayrımı (K) |
| 4 sonuç doğrulama + negatif test | kısmen T | iş 1 negatifleri sunucu sayacıyla (T); iş 2-3 açık |
| 5 hata yutma | A | `.ok()`/`let _` taraması yapılmadı (WS kapanışı ve TCP nodelay bilerek yutuluyor) |
| 6 bayat önbellek | K | kayıtlar her turda okunur; hata `last_good`u ezmez; test yok. Sistem TLS kökleri süreçte bir kez yüklenir |
| 7 sınırlı döngü | kısmen T | yeniden deneme 2 ve 3 (T, iş 1); poller/prober sonsuz ama `Running` düşünce durur; dedup TTL + LRU (T) |
| 8 CLI/TUI fixture | gerekçe | TUI yok |
| 9 sahiplik, fd sızıntı testi | T (REST) | `fake_fd` (200 zaman aşımı, sunucu her soketin kapandığını görür); iptal edilen görev uçuşu bırakır (T). WS/relay görevleri iş 3. Havuz bağlantı görevi karşı taraf kapatınca biter |
| 10 girdi sınırları | kısmen T | URL, kayıt, belge; uzak REST yanıt tipleri ve gövde sınırı (T, iş 1); WS/gRPC iş 3 |
| 11 metin ayrıştırma | gerekçe | yok |
| 12 Python paritesi | A | iş 4; `py_strip` kullanıldı, `$HOME` erişimi yok |
| 13 sırlar | T (kayıt) | `Secret`, `public()`; hata metinlerinde URL/port/token yok (T, `error_texts_carry_no_url_port_or_token`) |
| 14 adres denetimi | T (guard, REST bağlantısı), A (WS/gRPC) | canonical `::ffff:` testli; DNS adı loopback'e çözülünce REST bağlantısı yok (T); WS/gRPC iş 3 |
| 15 kullanıcı yolu e2e | A | copsd entegrasyonundan sonra |
| 16 route tabloları | A | iş 4 |
| 17 test yalıtımı | T | testler dosya yazmaz, canlı dizine dokunmaz |
| 18 uzak sürüm/deploy notu | K | uzak hostlara deploy gerektirmez (istemci tarafı) |
| 19 GIT_SHA / geri dönüş | gerekçe | ikili yok |
| 20 kanıt | yapıldı | perf iddiası yok; Python'a yazılmadı |

H1-H21'den bu ize değen diğerleri: H1 (bağlantı sahipliği: REST fd testi T), H18 (WS çerçeveleme: iş 3), H20 (olaylar
`Events` ile, token'sız alanlar), H15/H4/H6 kapsam dışı (vekil sunucu, TUI, metin işareti yok).
