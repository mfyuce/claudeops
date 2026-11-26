# İz T5 federasyon istemcisi (`rs/hosts`, crate `cops-hosts`)

## Durum (26 Kas 2026 akşam, iş 4-5 sonrası): BİRLEŞTİRMEYE HAZIR DEĞİL (kalan maddeler aşağıda)

`cargo test -p cops-hosts` 123/123 geçiyor (22 birim + 101 entegrasyon, `tests/parity.rs` 12 dahil);
`cargo clippy -p cops-hosts --all-targets -- -D warnings` temiz. Eşleme tablosu `docs/rs-hosts-mapping.md` (üreteç ve
denetim `rust/crates/cops-hosts/tools/mapping.py`, `--check` temiz): tanım 358 (243 karşılandı, 115 kapsam dışı, 0 AÇIK),
Python test durumu 873 / 61 dosya (151 karşılandı, 722 kapsam dışı, 0 AÇIK).
Hiçbir yere bağlanmadı (copsd/cops-proxy bu crate'i henüz çağırmıyor). Gerçek uzak host'a istek atılmadı.

Kalan (birleştirmeyi tutan) maddeler:
- Gözden geçirme #15 kullanıcı yolu e2e ve ders 2.8 iki gerçek istemcili WS e2e: crate copsd'ye bağlanınca (cops).
- Python bulguları (aşağıda "İş 4'te bulunan Python hataları"): sahip kararı gerekir; Rust güvenli davranışta, parity
  testinde "bilinen fark" olarak kilitli. Karar Rust'ta değişiklik gerektirirse parity listesi düşer, unutulmaz.
- Prober'ın kendi takılma yeniden başlatması testsiz (iş 3 gerekçesi; davranış Python'da hiç yok).

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
2. BİTTİ (26 Kas): poller/health testleri, `tests/fake_poller.rs` (13) + `tests/fake_health.rs` (13); destek
   `support::{MemSource, RecEvents, closed_port, count_path}`. Eşleme aşağıda "İş 2 test eşlemesi".
3. BİTTİ (26 Kas): destek `support::{ws::WsFake (aynı portta REST + /ws + /ws/term, hyper upgrade, isteğe bağlı TLS),
   grpc::GrpcFake (tonic, crate'in `pb` mesajlarıyla), tls::Ca (rcgen geçici kök)}`; testler `fake_ws.rs` (18),
   `fake_grpc.rs` (7), `fake_tls.rs` (5), `fake_restart.rs` (2). Eşleme aşağıda "İş 3 test eşlemesi".
   gRPC'de `Dial` + `origin` ile https yolu ÇALIŞIYOR (sunucu `:scheme=https` görüyor, `origin` kaldırılınca test düşer).
4. BİTTİ (26 Kas akşam): `tests/parity.rs` (12 test) + Python kahini `tools/py_parity.py`; eşleme tablosu
   `docs/rs-hosts-mapping.md` + `tools/mapping.py`. Ayrıntı aşağıda "İş 4 parite eşlemesi".
5. BİTTİ: kontrol listeleri test adlarıyla güncellendi; `.ok()` / `let _` taraması yapıldı (gözden geçirme #5).

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

### İş 2 test eşlemesi

| Senaryo | Test |
|---|---|
| eşik altı hata yazılmaz, `last_ok_at` değişmez; eşikte ok:false ama satırlar KORUNUR, 6.+ hatada da silinmez; başarı sayacı sıfırlar; hiç başarısı olmayan host ilk hatada görünür; silinen host önbellekten kalkar; hata metni temiz | `fake_poller::consecutive_failures_are_tolerated_then_rows_are_kept_stale` |
| `extra_urls` yalnız 5. ve her 20. hatalı turda, başarısız aday kalıcılaşmaz, çalışan aday `promote` + kayıt güncellenir, sonraki tur yeni adrese | `fake_poller::extra_urls_fallback_runs_on_threshold_and_every_twentieth_failure` |
| `extra_urls` yoksa yedek ve `probe_choice` hiç devreye girmez | `fake_poller::host_without_extra_urls_never_tries_a_fallback` |
| https tabanlı host'ta düz http aday: TCP bağlantısı bile yok, olayda URL yok; https aday denenir; `probe_choice` da aynı kural; reach portundaki aday izinli | `fake_poller::https_base_never_falls_back_to_plain_http` |
| `probe_choice` yalnız kayıtlı aday, ağa gitmez, `note_switch` + olay | `fake_poller::probe_choice_only_promotes_registered_allowed_candidates` |
| bozuk uzak yanıt: `sessions` yok/nesne/sayı, dizi, JSON değil, boş, 2xx dışı = hata; nesne olmayan satır düşer, yanlış tipli alanlar boşa, `cli_options` 4 alana tamamlanır, `orphan_watch`/`fwd`/`build` indirgemesi | `fake_poller::malformed_remote_status_is_an_error_or_reduced_to_empty_fields` |
| bozuk host kaydı (sayı, metin, adsız) yoklanmaz | `fake_poller::irregular_host_records_are_skipped_by_the_poller` |
| `merge_status`: ad (küçük harf) sonra cwd ya da tersi, eşit anahtarda kararlı (yerel önce), adsız satır, yanlış tipli yerel liste, `mirror_open` yalnız uzak satır ve yalnız küme verilince, yoklanmamış host yer tutucusu, kayıt sırası, kesintide bayat satırlar | `fake_poller::merge_status_resorts_globally_and_keeps_host_rows` |
| `/api/hosts` satırlarında token/`token=` yok, `has_token`, hata metni temiz, `build_diff`, yoklanmamış host | `fake_poller::public_rows_never_carry_the_token` |
| `probe_host`: kayıtsız host, 15 sn hız sınırı (istek GİTMEZ), sınır sonrası yeniden, poller ile aynı tolerans | `fake_poller::probe_host_is_rate_limited_and_records_like_the_poller` |
| `test_now` taze sonucu döner, paylaşılan önbellek toleranslı kalır | `fake_poller::test_now_returns_the_fresh_result_not_the_smoothed_one` |
| `Running` düşünce poller+prober durur (görevler `Federation` kopyalarını bırakır, 600 sn'de tur yok); tutulurken döner | `fake_poller::dropping_running_stops_poller_and_prober` (sanal saat) |
| poller kalp atışı yaşı bir aralığı aşmaz, yeniden başlatma yok | `fake_poller::poller_beat_age_stays_within_one_interval` (sanal saat) |
| taşıma hatası sınıfı (502-504, `<host> unreachable:` öneki; 404, 500, uygulama reddi, başka host adı değil) | `fake_health::transport_error_classification` |
| devre kesici 3 hatalı tick'te açılır, `Down` bir kez, 600 sn, sonraki hata uzatır, temiz tick `Up` + sıfır | `fake_health::breaker_opens_after_three_failing_ticks_and_reports_once` |
| eylemsiz tick sayılmaz, temiz tick sayacı sıfırlar, aynı tick'te hata önce, değişiklikler sıralı | `fake_health::breaker_ignores_idle_ticks_and_success_resets_streak` |
| probe başarısı geri çekilmeyi ANINDA bitirir, sayaç sıfırlanır | `fake_health::probe_success_clears_backoff_immediately` |
| tek yavaş okuma (gerçek zaman aşımı) host'u suçlamaz, hepsi yavaşsa suçlar | `fake_health::slow_single_read_does_not_blame_a_reachable_host` |
| tazelik (bayat, hiç başarı yok, stale-while-error satırı) ve dosya kapısı (5 negatif) | `fake_health::freshness_and_files_gate` |
| `probe_facts` tek istekte yetenek+olgu, sorgu, api>0 her seferinde sorulur, geçersiz `api` reddi | `fake_health::probe_facts_reads_caps_and_facts_in_one_request` |
| 404 = api 0 önbelleğe, taşıma değil, 10 dk istek GİTMEZ, sonra yeniden yoklama | `fake_health::probe_facts_404_caches_old_host_and_stops_asking` |
| geçici hata (500, ok:false, 502, 503, kopma, kapalı port, kayıtsız host) önbelleğe YAZILMAZ; yalnız taşıma hatası `tick.failed` | `fake_health::probe_facts_transient_failure_is_not_cached` |
| `remote_post` 4 yıkıcı yolu ve `host` alanını reddeder (bağlantı yok), normal yol `host=local` ile gider | `fake_health::remote_post_refuses_destructive_paths_and_host_field` |
| 404 `remote_not_found`, uygulama reddi aynen, kopma = `host_down` + POST yeniden denenmez + aynı tick'te istek yok, olayda token yok, 502 | `fake_health::remote_post_breaker_and_error_marking` |
| belirsiz (2 çalışan satır, Python doğruluk kuralı), önek eşleşmesi, çalışmayan, büyük/küçük harf, bayat/kapalı host, yetenek yok/bilinmiyor: istek GİTMEZ (sunucu sayacı 0) | `fake_health::ambiguous_or_inexact_target_sends_nothing` |
| `remote_stop` gövdesi, host başına tick başına 1 yıkıcı eylem, başka host ayrı bütçe, uzak ret uygulanmış sayılmaz, bloklu host, yeni tick | `fake_health::remote_stop_sends_one_exact_stop_per_host_per_tick` |

Mutasyonla doğrulandı (26 mutasyon, hepsi en az bir testi düşürdü; kaynak geri alındı): tolerans eşiği, bayat satır
koruması, yedek sıklığı, https düşürme denetimi, `probe_choice` kayıt denetimi, sıralama (küçük harf ve cwd eşitlik
anahtarı), `public()` yerine `to_value()`, `Running` abort'u, breaker `clear`/`settle` önceliği, `record_reads`,
facts geçici hatayı önbelleğe yazma, api 0 kısa devresi, yıkıcı yol reddi, `ambiguous`, bütçe, `probe_host` hız sınırı,
2xx denetimi, taşıma öneki, doğruluk kuralı, bloklu `remote_stop`, `caps_unknown`, `retain`, `mirror_open`, `promote`.

Kapsanamayanlar (iş 2): poller takılma/panik yeniden başlatması (`POLLER_STALL` 90 sn; tur içinde engelleyen bir adım
gerekir, gerçek ağla sanal saat birlikte oynak olur); push tüketicili (`ws`/`grpc` kademe) poller dalı ve prober'ın
kademe yükseltmesi (iş 3: sahte `/ws` ve tonic); özel ağ (RFC1918) http istisnası (loopback dışı adres gerekir;
kural `guard` birim testinde). Rust'ta paralel okuma bütçesi (`_remote_last_assistant`) yok, değnekçi izinin işi:
test `proxy_get` + `record_reads` bileşimini sınar.

İş 2'de düzeltilen (Python ile eşitleme, `health.rs`):
- `exact_target` sırası Python `_remote_stop` gibi: tazelik, satır, sonra yetenek (önce yetenek bakılıyordu).
  Yetenek `Option`: bilinmiyorsa `caps_unknown`, bilinip `exact_target` yoksa `remote_too_old` (eskiden bilinmeyen
  yetenek `remote_too_old`, api>0 `capability_missing` diye etiketleniyordu).
- `running` eşleşme sayımı Python doğruluk kuralıyla (`bool(x)`): yalnız `true` sayılınca Python'da belirsiz olan
  (`running: 1` ikinci satır) durum Rust'ta TEK hedef görünüyordu (kapalı yöne düşmüyordu).
- `remote_stop`: bütçe kodu `destructive_budget` + Python metni (eskiden `deferred`), bloklu host yanıtında
  `code: host_down`, yanıt `host` ve `name` taşır, `ok` olmayan yanıt `ok:false` (Python `_remote_stop`).

Python'da hatalı bulunanlar (TBD#372, sahip kararı: Python'da ve Rust'ta düzelsin):
- Python düzeltildi: `e2e497a`. `web_hosts.merge_status._row_key`: `cwd`/`name` alanı olmayan, `null` ya da metin
  olmayan uzak satır yerel `/api/status` birleştirmesini düşürüyordu. İki taraf da boş metin sayar.
- Python düzeltildi: `3e525fe`. `web_hosts._tag_rows` / `_fetch_status_from`: nesne olmayan satır ve `sessions: 5`
  poller turunu öldürüyordu. İki taraf da: dizi olmayan `sessions` = "unexpected response shape", nesne olmayan satır
  atlanır. WS push'ta `sessions` dizi olmayan (eksik ve `null` dahil) durum karesi atlanır; Rust eskiden bunu boş
  oturum listesiyle "ok" kaydediyordu (Rust `4cee0a1`, test
  `fake_ws::junk_frames_keep_the_stream_alive_but_rest_polling_continues`).
- Python düzeltildi: `a0cd64f`. `web_steward._remote_session` tam ad yolu ve `_remote_running_row` ilk çalışan satırı
  alıyordu. Aynı adlı iki çalışan satır artık `ambiguous_sessions` (`_remote_running_row`: bilinmiyor); Rust
  `exact_target` zaten `ambiguous` dönüyordu.
- Python düzeltildi: `769f899`. `_probe_facts` / `_caps_put`: metin `capabilities` karakterlerine bölünüyordu. İki taraf
  da dizi olmayanı boş sayar, metin olmayan öğeyi atar.

### İş 3 test eşlemesi

| Senaryo | Test |
|---|---|
| WS yoklaması: 101 yeter, kapanış el sıkışmasıyla kapanır; ret (401/200/kapalı port) = rest; kademe anında yükselir, 5 düşük yoklamada düşer | `fake_ws::ws_probe_raises_tier_at_once_and_lowers_it_only_after_tolerance` |
| push tüketicili poller: rest kademede tüketici yok; yeni akışın turu REST; veri getiren canlı akışta REST yok; kopunca REST + yeni akış + token'sız ölüm olayı; kademe rest'e düşünce soket kapanır | `fake_ws::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data` |
| bozuk/ilgisiz kareler (dizi, JSON değil, başka tür, `data` nesne değil, bozuk ikili) akışı öldürmez, veri sayılmaz (REST sürer); JSON ikili kare veri sayılır | `fake_ws::junk_frames_keep_the_stream_alive_but_rest_polling_continues` |
| durum sessizlik watchdog'u: 44 sn güvenilir, 46 sn'de yenisi + o tur REST, eski soket kapanır, olay; ölüm sayılmaz | `fake_ws::status_silence_watchdog_boundary` (sanal saat yalnız ağsız pencerede) |
| durum akışı token/adres/grpc_url değişince yeniden kurulur, `extra_urls` değişince KURULMAZ | `fake_ws::status_stream_is_rebuilt_when_address_or_token_changes_not_extra_urls` |
| term relay: ilk okuma "henüz veri gelmedi", sorgu (name/lang/token), seçenek başına ayrı akış (lite/interval/viewport sorguda), geçersiz aralık yok sayılır, bozuk kare son kareyi ezmez, kayıtsız host | `fake_ws::term_relay_streams_frames_and_keeps_one_stream_per_option_set` |
| ölü relay donmuş kareyi VERMEZ, 2 sn içinde yeniden kurulmaz, sonra kurulur | `fake_ws::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval` |
| sessiz relay 45 sn sınırı, bayat kare verilmez, olay, eski soket kapanır | `fake_ws::silent_relay_is_restarted_after_45s_without_serving_the_stale_frame` |
| relay kayıt (token/adres) değişince yeniden kurulur, `extra_urls` ile kurulmaz | `fake_ws::relay_is_rebuilt_when_the_host_record_changes` |
| boştaki relay 10 sn'de biçilir (9 sn'de değil), soket kapanır | `fake_ws::idle_relays_are_reaped_and_their_sockets_closed` |
| WS mesaj sınırı tam 16 MiB (tek çerçeve ve parçalı mesaj); fazlası akışı öldürür, kare verilmez | `fake_ws::ws_message_limit_is_16_mib_exactly`, `fragmented_ws_message_over_16_mib_is_refused` |
| taban yolu `/panel/ws`, `/panel/ws/term`; imza taban yollu | `fake_ws::base_path_is_kept_for_ws_and_signed_over_it` |
| Federation düşünce 60 akışın soketi kapanır, fd sayısı tabana döner; host silinince tur tüketiciyi bırakır | `fake_ws::dropped_streams_close_their_sockets_and_leak_no_fds` |
| DNS adı loopback'e çözülünce WS yoklaması/relay/durum akışı reddedilir, sunucu kabulü 0; IP literali kontrol | `fake_ws::dns_name_resolving_to_loopback_is_refused_for_ws_before_connecting` |
| WS el sıkışmasında panel (legacy) kimliğiyle her bağlantıya yeni imza, sorgusuz yol, gövdesiz | `fake_ws::ws_handshake_carries_a_fresh_panel_signature_per_connection` |
| imza reddi/panik/yasak başlık (connection, upgrade, sec-websocket-*, geçersiz ad) = bağlantı AÇILMAZ (kabul 0) | `fake_ws::ws_signer_refusal_panic_or_bad_header_opens_no_connection` |
| H18: sunucu Ping'ine Pong, akış bozulmaz; sunucu Close'una istemci Close yanıtı, `stream_ended` | `fake_ws::server_ping_gets_pong_and_server_close_is_acknowledged` |
| gRPC `Ping` (taşıma + `Bearer` token + servis); yanlış token ws'e düşer (5 düşük yoklama toleransı); grpc_url boşsa bağlantı yok; susan uç 1 sn'de biter; HTTP/1 uç gRPC sayılmaz | `fake_grpc::grpc_probe_needs_transport_token_and_service_and_tier_moves_like_python` |
| gRPC durum akışı poller'ı besler (etiket, build, extras süzgeci), canlıyken REST yok, WS açılmaz; sunucu bitirince ölüm (grpc) + REST + yeni akış; URL başına tek kanal | `fake_grpc::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` |
| gRPC term relay: istek (ad, dil), alanlar, `ok:false` güncellemesi | `fake_grpc::grpc_term_relay_serves_frames_and_error_updates` |
| gRPC mesaj sınırı tam 4 MiB (Python varsayılanı) | `fake_grpc::grpc_message_limit_is_4_mib` |
| akışlar tek HTTP/2 bağlantıda; Federation düşünce akışlar iptal + TCP kapanır; host silinince kanal bırakılır | `fake_grpc::dropped_grpc_consumers_cancel_streams_and_removed_hosts_close_the_channel` |
| gRPC DNS adı loopback'e çözülünce red (kabul 0) | `fake_grpc::grpc_dns_name_resolving_to_loopback_is_refused_before_connecting` |
| gRPC imzalanmaz (bilinen eşit davranış; reddeden signer hiç çağrılmaz) | `fake_grpc::grpc_calls_are_not_signed_known_parity_with_python` |
| TLS: özel kökle REST + wss yoklaması + wss term akışı | `fake_tls::wss_and_https_rest_work_with_a_custom_root` |
| TLS: güvenilmeyen kök, yalnız sistem kökleri, ad uyuşmazlığı: REST/WS reddi, sunucuya HTTP isteği ULAŞMAZ, hata metni temiz | `fake_tls::wrong_root_wrong_name_or_system_roots_refuse_tls_and_send_no_request` |
| gRPC https: kendi `Dial` (ALPN h2) + `origin` ile `:scheme=https`, `:authority`; yoklama + iki akış tek TLS bağlantısında | `fake_tls::grpc_over_https_works_through_own_dial_and_origin`, `grpc_plain_http_sends_http_scheme` |
| gRPC TLS: yanlış kök / sistem kökleri / ad uyuşmazlığı reddi, hiçbir çağrı ulaşmaz | `fake_tls::grpc_tls_with_wrong_root_or_name_is_refused_and_no_call_arrives` |
| poller takılması (adım sınırı > 90 sn): tur 90 sn'de iptal, `stalled:true`, kalp atışı tazelenmez, takılan turların soketi birikmez, host düzelince toparlanır | `fake_restart::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers` (sanal saat) |
| panik eden tur sayılır (`stalled:false`), poller yaşar, sonra normal turlar | `fake_restart::panicking_turn_is_counted_and_the_poller_keeps_running` (sanal saat) |

Mutasyonla doğrulandı (21 mutasyon, hepsi düştü; kaynak geri alındı): WS mesaj sınırı (parçalı testle; tek çerçeve
testini çerçeve sınırı da yakalar), taban yolu, el sıkışma imzası, durum sessizlik denetimi, `has_data`, rest
kademede tüketiciyi bırakma, `POLLER_STALL` zaman aşımı, kayıt anahtarı karşılaştırması, relay sessizlik denetimi,
relay 2 sn kuralı, ölü relay'i kaldırma, `PushConsumer` düşünce abort (WS ve gRPC), DNS-loopback peer denetimi (WS ve
gRPC), gRPC `origin`, gRPC 4 MiB sınırı, `GrpcClient::retain`, boştaki relay biçme, ikili çerçeve ayrıştırma.

Kapanamayanlar (iş 3): gerçek 60+ sn sessiz WS bağlantısının canlılığı (sessizlik zaten 45 sn'de yeniden kurar;
Python ile aynı); prober'ın kendi takılma yeniden başlatması (`CAPABILITY_PROBE_INTERVAL` zaman aşımı) testsiz:
yoklamalar kısa zaman aşımlı, takılma üretmek için üretim koduna dikiş gerekirdi; tarayıcı + Python `websockets`
ikili e2e (H18) copsd entegrasyonunda. Özel ağ http istisnası (iş 2'deki gerekçe).

İş 3'te düzeltilen (Python ile eşitleme, `federation.rs`/`relay.rs`): durum tüketicisinin "uç değişti" anahtarı tüm
`HostRecord`du (`extra_urls` ya da tanınmayan alan değişince canlı akış kapatılıp yeniden kuruluyordu); artık Python
R-18 anahtarı `(base_url, grpc_url, token)` + kademe (`StreamEndpoint`). Term relay aynı adres anahtarını kullanır,
kademe değişimi tek başına relay'i yenilemez (Python gibi; önceki Rust davranışı da buydu).
Üretim koduna dikiş EKLENMEDİ: özel kök mevcut programatik `Connector.tls` alanıyla verildi (ortam değişkeni/ayar yok),
doğrulama gevşetilmedi. Dev-bağımlılık: `rcgen 0.14` (`crypto`, `ring`; Cargo.lock'a yalnız test bağımlılıkları).

WS karesi (TBD#376, Python düzeltildi: `fix(hosts)` bozuk kare) ve açık yarış:
- `web_hosts._parse_ws_status_frame` / `_parse_ws_term_frame`: JSON dizi/sayı karesi `parsed.get` AttributeError
  verir (yalnız JSONDecodeError/TypeError yakalanıyor); `_PushConsumer._run` istisnayla ölür, tek bozuk kare akışı
  düşürürdü. Artık iki taraf da kareyi atlar (`junk_frames_keep_the_stream_alive_but_rest_polling_continues`);
  iki taraf da tür (`status`/`term`) başına dakikada en çok bir `push_frame_skipped` loglar (Rust `push::SkipLog`,
  testler `push::tests::skipped_frames_are_logged_at_most_once_a_minute_per_kind`, `fake_ws::junk_frames_...`,
  `fake_ws::term_relay_streams_...`).
- Yarış (Python ile aynı, ders H3 açık): yeni akışın ilk karesi aynı turun REST sonucundan önce gelirse REST onu ezer
  (her iki kaynak da `record` eder, sıra/damga yok). Bir tur kadar daha eski veri; sonraki kare düzeltir.

### İş 4 parite eşlemesi

Kahin (`tools/py_parity.py`) `python3 -I` ile, geçici `CLAUDEOPS_DIR`/`HOME`/`CLAUDEOPS_DIAG_LOG` ve
`CLAUDEOPS_EXTENSIONS=0` olmadan çalışmayı reddeder; soket bağlantısı ve sayısal olmayan ad çözümü süreç içinde
engellidir; tek yazımı geçici `hosts.json`. Bilinen farklar her testte gerekçeli listede; listedeki girdi eşitlenirse test
düşer.

| Kapsam | Yöntem | Test |
|---|---|---|
| `HOST_ROUTED_PATHS`, `GET_HOST_ROUTED_PATHS`, `SECRET_BODY_PATHS`, `TERM_RETRY_PATHS`, indirme/yükleme yolu = `web_hosts.py` | Python KAYNAK METNİ ayrıştırılır (yorum atlanır, ayrıştırıcı kendini sınar) | `parity::host_routed_route_sets_equal_python_source` |
| her host-routed yol (+ `/api/status`, `/ws`, `/ws/term`) `cops_auth::authz::action_for` ile `UNMAPPED` değil ve Python `authz.action_for` ile aynı eylem | metin + kahin | `parity::host_routed_paths_have_the_same_authz_action_as_python` |
| `grpc::pb` ad/numara/etiket/tür = `host_bridge.proto` metni = Python pb2 tanımlayıcısı; servis yolu, yöntem ve istek/yanıt türleri | metin + kahin | `parity::grpc_messages_match_proto_text_and_python_descriptors` |
| Python pb2 ile kodlanan `StatusUpdate`/`TermUpdate` Rust'ta çözülür, dict dönüşümü aynı (ucli bayrakları, extras, boş alanlar) | kahin | `parity::grpc_wire_decoding_matches_python_conversion` |
| zaman aşımları, eşikler, TTL'ler, LRU/havuz sınırları, `hosts.ERR` (iki dil), `REFUSED_PREFIX`, gRPC keepalive, `_EXTRA_KEYS` | kahin (içe aktarılmış değer) + metin | `parity::shared_constants_and_error_texts_equal_python` |
| aday adres kuralı, özel ağ, sır URL'si, engelli IP, DNS adı, reach portları, `urlencode` | kahin | `parity::address_filters_match_python` |
| `input_id` kuralı (Rust hiçbir girdide Python'dan gevşek değil) | kahin | `parity::input_id_rule_is_python_or_stricter` |
| kayıt doğrulama sırası, hata metni, upsert (token koruma, bilinmeyen alan, bozuk/boş belge) | kahin | `parity::save_host_validation_and_upsert_match_python` |
| `finalize` (satır etiketleme, `cli_options`, `orphan_watch`, `fwd`, `build`, `ok` doğruluk kuralı) | kahin | `parity::status_reduction_matches_python` |
| WS durum/terminal karesi, atlama (loglanan) ile ilgisiz kare ayrımı | kahin | `parity::ws_frames_match_python` |
| ardışık hata toleransı dizileri, kademe dizileri, `merge_status` (sıralama, `mirror_open`, yer tutucu) | kahin | `parity::poll_cache_tier_and_merge_match_python` |
| taşıma hatası sınıfı, tazelik, `_remote_running_row`, `remote_health` | kahin | `parity::steward_client_parts_match_python` |

İş 4-5'te Rust'a eklenen/düzeltilen (Python ile eşitleme):
- `push_frame_skipped` (`push::SkipLog`, `ws::decode_frame`); `pub mod ws`.
- `health::exact_target`: geri çekilmedeki host `host_down` (Python `_remote_rows`; eskiden yalnız tazelik), hata kodları
  Python ile aynı: `no_exact_row` (eski `no_exact_match`), `ambiguous_sessions` (eski `ambiguous`).
- `health::running_row`, `named_running_rows` (Python `_remote_running_row`/`_remote_named_rows`), `health_view`
  (`remote_health`), `CapabilityCache::host_capabilities` + `CAPS_PROBE_TIMEOUT` (`host_capabilities`).
- `status::finalize`: `ok` doğru değilse (yok dahil) başarısız (Python `not result.get("ok")`); `build.running` ve
  `fwd.mode` Python `str()` ile (sayı/doğru değer), `fwd.kids` yanlış (falsy) değerde boş, `fwd.now` bool kabul, `skew`
  Python `round(x, 1)` ile (tam ondalık, `x*10` ara adımı yok); `orphan_watch` Python `int(x or 0)` (boş dizi/nesne 0).
- `merge_status` `mirror_open` anahtarı Python f-string'i gibi (`host:None`, `host:7`).
- `record::Draft::new`: şema öneki küçük harf (Python `startswith`); eskiden `HTTP://` kabul ediliyordu (gevşekti).
- `proxy::valid_input_id` Python'dan SIKI: yalnız ASCII görünür (Python `isprintable` Unicode sürümüne bağlı; uzak
  Python kimliği geçersiz sayarsa tekrar ayıklanmaz, Rust yeniden denerse girdi iki kez yazılırdı; eskiden U+200B gibi
  biçim karakterlerini kabul ediyordu).
- `guard::host_is_blocked_via` (çözümleyici + süre parametreli; asılı DNS testi), `relay` ölüm etiketi testi,
  gRPC çözülemeyen ad testi, `capabilities` metin/nesne testi.

Aynı adlı oturum ve sonsuz sayı (TBD#380, sahip kararı: iki tarafta düzelsin):
- Python düzeltildi: `27772e9`. `web_steward._remote_ref` ve `RemoteReviewDriver._project_cwd_remote` aynı adlı iki
  çalışan uzak satırda ilkinin klasörünü alıyordu (uzak okuma/yazma yanlış dizine gidebilirdi). Artık klasör bilinmiyor
  (`("", "")` / `""`), `_remote_read_context` son konuşmayı da okumaz. Bu crate'te uzak dosya hedefi yok (T10/T8);
  satır kuralı `health::running_row` / `named_running_rows` ile aynı.
- Python düzeltildi: `af10181`. `web._open_mirror_window` adı eşleşen ilk satırı alıyordu; iki çalışan adaş artık
  `ambiguous_name` (geri yükleme ve `force` dahil). Rust karşılığı yok (masaüstü yansı penceresi, T2).
- Python düzeltildi: `6ae44d5`. `web_hosts._orphan_brief`: `servers`/`procs` sonsuz (`Infinity`, `1e999`) ise `int(inf)`
  OverflowError yakalanmıyordu: `_finalize_remote_result` düşüyor, REST turu o host'tan sonrakiler için bitiyor, WS'te
  tüketici ölüyordu. Python artık yalnız `orphan_watch`ı atar (`None`), host `ok` kalır. Rust davranışı değişmedi: serde
  sonsuz sayıyı JSON saymaz, o host'un yanıtı "bad response (not JSON)"; iki tarafta da tur sürer
  (`fake_poller::non_finite_orphan_count_fails_only_that_host`). Kalan bu fark "Python'dan bilinçli farklar"da.

İş 4'te bulunan Python hataları (Python'a YAZILMADI; sahip kararı gerekir, Rust güvenli davranışta, parity bilinen fark):
- `web_hosts._fwd_brief`: `now` `NaN` ise `skew: nan` üretir; `/api/status` JSON'unda geçersiz `NaN` (tarayıcı
  `JSON.parse` reddeder). Rust: girdi JSON değil sayılır.
- `web_hosts._fwd_brief`: metin `kids` karakterlere, nesne `kids` anahtarlarına bölünür (TBD#372 `capabilities`
  hatasıyla aynı sınıf). Rust tüm `fwd`i yok sayar.
- `web_hosts._finalize_remote_result`: dizi olmayan doğru `cli_list`/`dups` (metin, dolu nesne) olduğu gibi geçer
  (ön yüz dizi bekler). Rust boş dizi.
- `web_hosts._is_private_lan_http` Python 3.10 `is_private`i geniş (198.18/15, 192.0.2/24, 2001:db8::/32 "özel ağ"):
  https tabanlı host'ta bu http adaylar token'ı şifresiz alabilir. Rust yalnız RFC1918 + ULA (bilinçli fark, zaten
  belgeliydi).
- Bilinen eşit davranışlar değişmedi: gRPC çağrıları imzalanmaz; WS/REST yarışı (H3).

Hata yutma taraması (gözden geçirme #5): `src/` içindeki her `.ok()`, `let _`, `unwrap_or_default()`, `Err(_)`,
`map_err(|_| ...)` okundu. Sonucu değiştiren yutma yok. Bilerek yutulanlar: `net.rs` `set_nodelay` (performans
seçeneği), `ws.rs` yoklama sonrası kapanış (sonuç zaten belli, 1 sn sınırlı), `http.rs` bağlantı sürücüsü görevinin
sonucu (hata isteğin kendisine yansır), `federation.rs` başarısız `extra_urls` adayı (Python gibi; tabanın hatası
kaydedilir), `ws.rs` yoklama hatası (Python gibi `rest`). Ayrıştırma `.ok()`leri kapalı yöne düşer (geçersiz = red ya da
Python ile aynı indirgeme). `map_err(|_| ...)` yalnız URL/token taşıyan iç hata metnini dışarı vermemek için.

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
- Term relay kayıt (adres/token/grpc_url) değişince yeniden kurulur (Python hiç yenilemiyordu); `extra_urls` ya da kademe
  değişimi yenilemez.
- `interval` sorgu biçimi Rust `f64::to_string` (Python `{:g}`): 0.5/1/2.5 aynı; çok küçük/büyük değerde metin farklı
  (`1e-05` / `0.00001`). 0, negatif, NaN, sonsuz aralık Rust'ta yok sayılır (Python olduğu gibi iletir).
- `input_id` yeniden deneme kuralı Python'dan sıkı (yalnız ASCII görünür karakter).
- `remote_post` yıkıcı yolları (`/api/stop` vb.) reddeder; yalnız `remote_stop` (Python `_remote_post` gönderir) ve gövdede
  `host` istisna değil hata değeri. `exact_target` yeteneği yalnız önbellekten okur (çağıran önce `host_capabilities`);
  yetenek ve `blocked` denetim sırası farklı (ikisi de istek göndermez).
- `finalize`, kahin dışı girdide (JSON'da `NaN`/`Infinity`/`1e999`) Python'dan önce reddeder (serde): Rust o host'u
  hata sayar, Python yanıtı kabul eder (`orphan_watch`ta sonsuz sayı yalnız o alanı düşürür).
- Python `str()` yalnız skalerlerde birebir; dizi/nesne değer JSON metni olarak kalır (`build.running`, `fwd.kids` öğesi).
- Bilinen eşit davranış (düzeltilmedi): gRPC çağrıları imzalanmaz.

## Ders listesi 2.11 (federasyon)

Durum: T = testli, K = kodda var, TEST YOK, A = açık.

| Madde | Durum | Karşılık |
|---|---|---|
| `Remote<T>`; yıkıcı eylem yalnız `Ok` | T | `health::Remote`, `exact_target` (tazelik + geri çekilme + tek satır + yetenek) + `remote_stop`; `remote_post` yıkıcı yolu reddeder (`fake_health::ambiguous_or_inexact_target_sends_nothing`, `remote_stop_sends_one_exact_stop_per_host_per_tick`) |
| SSRF tablo, menzil istisnası yalnız `extra_urls` | T | `guard::tests::*`, `record::tests::validation_order`, `parity::address_filters_match_python`, `parity::save_host_validation_and_upsert_match_python` |
| HTTPS'ten düz HTTP'ye sessiz düşüş yok | T | `https_never_downgrades_to_public_http`, `try_fallback_urls` |
| Breaker, probe başarısında sıfırlama, yavaş okuma suçlamaz | T | `Breaker::{settle,clear}`, `TickState::record_reads` (`fake_health::breaker_*`, `probe_success_clears_backoff_immediately`, `slow_single_read_does_not_blame_a_reachable_host`) |
| Yetenek yoklaması, eski sürüme zarif düşüş | T | `CapabilityCache::probe_facts`, `host_capabilities`, `Remote::Unsupported` (`fake_health::probe_facts_*`, `host_capabilities_uses_cache_then_probes_once`) |
| Route = host-routed = yetki tablosu eşitlik testi | T | `parity::host_routed_route_sets_equal_python_source`, `parity::host_routed_paths_have_the_same_authz_action_as_python` (yerel POST tablosu = host-routed eşitliği W0-c/copsd) |
| Deploy smoke | gerekçe | kütüphane; ikili ve deploy copsd entegrasyonunda (cops) |
| Açık, uzun zaman aşımı | T (adım + tavan + terminal deneme sınırı), K (`long_read`) | `Timeouts` (`long_read` 90 sn çağıran seçer) |
| İmzalı kimlik: istemci başlığı güvenilmez, gövde özeti | T (signer tam gövdeyi ve sorgusuz yolu alır) | vekil istemci başlığı taşımaz, gövde signer'a verilir; doğrulama alıcıda |
| hosts.json kilitli yaz, db kipinde DB | gerekçe | bu crate yazmaz (`cops-state`); `record` saf |
| Uzak WS kapanışı + sessizlik watchdog'u | T | iş 3: sessizlik sınırları, ölü/sessiz relay, düşürülen görev soketi kapatır, Ping/Pong, Close yanıtı |

## Genel gözden geçirme listesi (20 madde)

| # | Durum | Not |
|---|---|---|
| 1 hedef Unique | T (`ambiguous_or_inexact_target_sends_nothing`, `health::tests::running_row_is_exact_truthy_and_ambiguous_is_unknown`) | `exact_target` tam ad, birden çok eşleşme `ambiguous_sessions`, geri çekilmede `host_down` |
| 2 atomik yazım | gerekçe | dosya yazımı yok |
| 3 belirsiz = kapalı | T | signer paniği ve yasak başlık red (`fake_proxy::signer_refusal_...`), bozuk belge yazılmaz (`record::tests::corrupt_and_irregular_documents`), `Remote` ayrımı (`fake_health::probe_facts_*`), belirsiz satır = bilinmiyor (`running_row`), `ok` doğru değilse başarısız (`parity::status_reduction_matches_python`), asılı DNS fail-open ama bağlantı anı peer denetimi (`guard::tests::hung_or_failed_...`) |
| 4 sonuç doğrulama + negatif test | T | iş 1-3 negatifleri sunucu sayacıyla (bağlantı/istek/çağrı GİTMEDİ) |
| 5 hata yutma | T (tarama) | yukarıda "Hata yutma taraması"; sonucu değiştiren yutma yok, bilerek yutulanlar listeli |
| 6 bayat önbellek | T | kayıtlar her turda okunur; hata `last_good`u ezmez (T, iş 2). Sistem TLS kökleri süreçte bir kez yüklenir |
| 7 sınırlı döngü | T | yeniden deneme 2 ve 3 (`fake_http::stale_*`, `fake_proxy::term_input_retries_three_times_with_same_input_id`); poller/prober sonsuz ama `Running` düşünce durur (`fake_poller::dropping_running_stops_poller_and_prober`); dedup TTL + LRU (`flight::tests::*`); kahin `timeout 120` altında |
| 8 CLI/TUI fixture | gerekçe | TUI yok |
| 9 sahiplik, fd sızıntı testi | T | `fake_fd` (REST); WS/relay/gRPC: görev düşünce soket kapanır, fd tabana döner (`dropped_streams_close_their_sockets_and_leak_no_fds`, `dropped_grpc_consumers_...`) |
| 10 girdi sınırları | T | REST gövde sınırı (iş 1); WS 16 MiB (tek ve parçalı), gRPC 4 MiB, bozuk kareler (iş 3) |
| 11 metin ayrıştırma | gerekçe | yok |
| 12 Python paritesi | T | `tests/parity.rs` (12 test, kahin `tools/py_parity.py`), eşleme `docs/rs-hosts-mapping.md`; `py_strip`, `$HOME` erişimi yok |
| 13 sırlar | T (kayıt) | `Secret`, `public()`; hata metinlerinde URL/port/token yok (T, `error_texts_carry_no_url_port_or_token`) |
| 14 adres denetimi | T | canonical `::ffff:` testli; DNS adı loopback'e çözülünce REST/WS/gRPC bağlantısı yok (sunucu kabulü 0); TLS ad/kök denetimi (T, iş 3) |
| 15 kullanıcı yolu e2e | A | copsd entegrasyonundan sonra (birleştirmeyi tutan madde) |
| 16 route tabloları | T | `parity::host_routed_route_sets_equal_python_source`, `parity::host_routed_paths_have_the_same_authz_action_as_python` |
| 17 test yalıtımı | T | testler canlı dizine dokunmaz; kahin geçici dizin dışında çalışmayı reddeder, ağsız; DNS testi sahte çözümleyiciyle (gerçek ad sunucusuna `.invalid` sorgusu kaldırıldı) |
| 18 uzak sürüm/deploy notu | K | uzak hostlara deploy gerektirmez (istemci tarafı) |
| 19 GIT_SHA / geri dönüş | gerekçe | ikili yok |
| 20 kanıt | yapıldı | perf iddiası yok; Python'a yazılmadı; Python hataları kahinle doğrulandı |

H1-H21'den bu ize değen diğerleri: H1 (bağlantı sahipliği: REST/WS/gRPC T), H18 (WS çerçeveleme: Ping/Pong, Close, sınır T; iki gerçek istemcili e2e copsd'de), H20 (olaylar
`Events` ile, token'sız alanlar), H15/H4/H6 kapsam dışı (vekil sunucu, TUI, metin işareti yok).
