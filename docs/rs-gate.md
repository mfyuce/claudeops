# rs/gate (İz W0-c: kapı)

**Durum (26 Kas 2026 gece):** kod ve testler tamam (aşağıda "Doğrulama"); değişiklikler `rs/gate` dalında
(ana oturum testleri yeniden koştu: 122 geçti, clippy ve fmt temiz). Canlı `copsd` ikilisine ve servislere dokunulmadı. Birleştirme kararı ve son satır cops'un (kapı: bağımsız
gözden geçirme dahil, `docs/rust-sprint-plan.md` "Sahip eki").

## Açık işler

1. [x] Ders listesi: aşağıda "Ders listesi" (2.3 ve genel 20 madde, her satır test adı ya da gerekçe; test adları grep ile doğrulandı).
2. [x] Eşleme tablosu: `docs/rs-gate-eslik.md` (durumlar, satır numaraları ve sayım bu turda güncellendi; bölüm 5 işleri 1-7 kodda).
3. [x] `cops-parity` gerçek Python iç portuna karşı: 26 Kas, `174c18e`, yalnız GET, 7/7 istek fark 0, üç ardışık koşu; yedi isteğin
   yedisini de Python cevapladı (`X-Cops-Served: python`; yerel uç karşılaştırması bu listede yok). Kayıt: eşlik bölüm 5 iş 9.
4. [ ] Kalan, bilerek bırakılan: eşlik iş 8 (`RequestView` `body_fn` ve eklenti eylem kaydı) T9 ile; "Ders listesi"ndeki AÇIK
   satırlar (taze tarayıcı e2e, enterprise'ın `Ctx.front`a geçişi); sahibe sorular aşağıda "Sahip kararı bekleyenler".
5. [x] Commit + push (iki remote).

## Bu turun işleri (eşlik bölüm 5)

| iş | yapılan | test |
|---|---|---|
| 1 varsayılan `--upstream` | `copsd::DEFAULT_UPSTREAM` = `127.0.0.1:28765` (`front_cmd.DEFAULT_INTERNAL`), USAGE ve modül belgesi | `default_upstream_matches_python_front_cmd`, `help_and_version_have_no_side_effects` |
| 2 gizli yaşam döngüsü | `cops_proxy::front::FrontSecret` (dosya imzası: aygıt, inode, boyut, mtime, ctime, mod; değişince yeniden okuma), `Proxy::with_front_secret`; açılışta kullanılamayan dosya uyarı + gizli yok (kapı 3), çalışırken yok/gevşek/bozuk = gizli yok; uzak istemci için `Cf-Connecting-IP` sabitleme (aşağıda gerekçe) | `file_secret_follows_changes_and_fails_closed`, `trusted_front_needs_secret_loopback_and_exact_header`, `front_secret_file_is_reread_and_fails_closed`, `runtime_secret_changes_apply_without_restart`, `startup_ignores_unusable_secret_file_and_warns`, `pin_client_ip_overwrites_only_for_non_loopback_peers`, `python_sees_real_client_with_or_without_secret` |
| 3 başlık süre sınırı | `serve_on` hyper `TokioTimer` + `header_read_timeout(15 sn)` (`HEADER_READ_TIMEOUT`, Python ile aynı; boşta keep-alive da 15 sn, Python gibi); `serve_on_with` sınama için; metrik POST gövdesi 10 sn (`ROUTE_BODY_TIMEOUT`) ve bildirilen boy sınırı aşarsa okumadan 413 | `slow_headers_are_cut_off`, `short_body_is_408_and_closes`, `security_headers_match_python_end_headers` (413) |
| 4 güvenlik başlıkları | `harden`: Python `end_headers` kümesi (`nosniff`, `Referrer-Policy`, kendi CSP'si yoksa `X-Frame-Options` + `CSP`); Rust'ın cevapladığı her yanıt, iç uç 404'ü ve Python yolunda copsd'nin ürettiği 502/400; mount ve Python'dan gelen yanıt hariç | `security_headers_match_python_end_headers` |
| 5 iç uç engeli | `python_path` (3.10 `parse_request` `//` indirgemesi + `urlparse`), `is_internal_target`; 404 gövdesi Python gibi `{"error": "not found"}` | `internal_block_covers_every_form_python_would_route`, `internal_paths_are_never_forwarded` |
| 6 güvenilen istemci IP'si | `front::trusted_client_ip` (Python `trusted_forwarded_ip`), `front::view_client_ip` (Python `_client_ip` karşılığı, `RequestView`den); `RequestView.client_ip` sözleşmesi DEĞİŞMEDİ (soket eşi; enterprise `trusted_ip` bunu varsayıyor) | `trusted_client_ip_matches_python_test_front_xff`, `python_sees_real_client_with_or_without_secret` |
| 7 eksik testler | loopback dışı eş ve boş gizli; `cops_ext` çerezi yerel API'yi açmaz; eksik gövde 408 (kanca ve metrik; `BodyError::Read` artık kancaya ulaşmaz, Python gibi 408 + kapanış); yerel ret sonrası aynı bağlantı; `force_proxy` 512 satır / 64 KiB | `trusted_front_needs_secret_loopback_and_exact_header`, `cops_ext_cookie_does_not_open_local_api`, `short_body_is_408_and_closes`, `early_reject_then_second_request_on_same_connection`, `force_proxy_size_limits` |
| 8 `body_fn`, eklenti eylem kaydı | YAPILMADI: T9 ile (gerekçe eşlik bölüm 5) | yok |
| 9 parite kaydı | yukarıda açık iş 3 | koşu kaydı |

### Gizli yaşam döngüsü ve "gizli yokken uzak istemci loopback görünmesin" kararı

- Açılış: `CLAUDEOPS_FRONT_SECRET` boş değilse o (sabit, kırpılmaz). Yoksa `--secret-file` / `<durum dizini>/front.secret`:
  yoksa gizlisiz açılır; var ama kullanılamıyorsa (0600 değil, UTF-8 değil, okunamıyor, düzenli dosya değil) yüksek sesle uyarı
  yazar ve gizliyi yok sayar (kapı 3: eski çıkış 2, systemd yeniden başlatma döngüsüyle dış portu düşürürdü; çalışma anı ve Python
  ile aynı). Dosya düzelince yeniden başlatmadan kullanılır.
- Çalışma: dosya her istekte `stat` edilir; imza değişince yeniden okunur (Python her çağrıda okur). Yok, gevşek, bozuk, 64 KiB
  üstü ya da boş = gizli YOK: aktarılan isteğe `X-Cops-Front` eklenmez (Python da aynı dosyayı okuduğu için zaten güvenmez),
  stats/metrik `X-Cops-Front` denetimi reddeder. Süreç ÇIKMAZ. Bilinen sınır: aynı inode, aynı boy ve çekirdeğin kaba zaman
  damgası içinde iki ardışık yazım imzayı değiştirmeyebilir (Python gizliyi yalnız `cops front on` ile, `os.replace` ile yani yeni inode olarak yazar).
- Gizli yokken Python `X-Forwarded-For`a güvenmez ve her isteği copsd'nin `127.0.0.1`inden görür; `_client_ip`nin son adımı
  "sonuç loopback ise `Cf-Connecting-IP`" kuralıdır. Seçilen çözüm (`front::pin_client_ip`): eş Python loopback'i DEĞİLSE copsd
  `Cf-Connecting-IP`yi eşin kanonik adresiyle EZER (istemcinin değeri asla geçmez). Loopback eşte (cloudflared tüneli) tünelin
  başlığı aynen kalır, tünel yolu değişmez. Gizli varken `X-Forwarded-For` = uzak eş loopback olmadığından Python başlığı okumaz:
  bugünkü canlı (gizli var) davranış değişmez. Sonuç: gizli olsun olmasın Python uzak istemcinin GERÇEK adresini görür
  (hız sınırı, `session_lock` günlüğü, eklenti `client_addr`), loopback ayrıcalığı almaz. Reddedilen seçenekler: gizlisiz açılışı
  reddetmek (canlıda gizli var ama `cops front on` öncesi/silinme anında paneli düşürürdü); uzak eşli isteği reddetmek (paneli
  kırar).
- Kancalar: `copsd::Ctx.front` (`Arc<FrontSecret>`, vekille aynı nesne) canlı değeri verir; `Ctx.front_secret` açılış kopyası
  uyumluluk için durur. AÇIK (enterprise): `copsd-ent` bugün `front_secret` okuyor, rev yükselirken `front`a geçmeli.

## Sahip kararı bekleyenler

- Gövde süre sınırı: Rust yerel uçlarda 10 sn TOPLAM (Python 60 sn, her okuma). Daha sıkı; büyük yükleme alan yerel uç (T3)
  gelince ayrı sınır gerekir.
- TBD#371 cevaplandı (26 Kas): eşlik "Python hatası?" 1-3 düzeltildi (`f7dedcc`, `5737ae8`, `31ff561`).

## TBD#371'den açık kalanlar

- [ ] (sahip numarası 4, T6) `cops front on/off`: port ayrıştırma, yabancı porta vekillik, geri sarma yokluğu (eşlik "Python hatası?" 4-6).
- [ ] (sahip numarası 5, T9) eklentiye giden başlıklar her erişimde harf duyarsız olsun (eşlik "Python hatası?" 7).
- [ ] (T6/T9) `cops front on` sızmış gizliyi artık YENİLER: bugünkü `copsd-ent` eski `Ctx.front_secret`i restart'a dek yollar (`Ctx.front`a geçince biter). Kabukta
  `CLAUDEOPS_DIR` doluyken `front on`, gizliyi birimlerin okumadığı dizine yazar.
- Canlı etkisi: iki serviste `CLAUDEOPS_DIR` yok (26 Kas ölçümü), canlı gizli yolu değişmez; canlı `front.secret`e dokunulmadı.

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
  `ent_auth_force_proxy` ile aynı. Statik, metrik, tablo, tek kanca ve yerel uca uygulanır; mount'lara ve `/api/front/stats`a DEĞİL (belgeli istisna: stats'ın Python karşılığı yok ve geri alma oradan
  doğrulanır; `*` altında da Rust cevaplar, `sighup_reloads_force_proxy_and_stats_count_it`).
- Okuma: açılışta ve SIGHUP'ta. Dosya yok = boş. Dosya var ama okunamıyor/bozuksa açılışta da SIGHUP'ta da `*` (kapalı yön). 512 satır üstü `*`.
- Canlıda uygulama: `systemctl --user kill --kill-who=main -s HUP claudeops-front.service`.
  **DİKKAT:** bugünkü canlı (eski) `copsd` SIGHUP işlemez, sinyal onu ÖLDÜRÜR; komut yalnız yeni ikili konduktan sonra.
  `front.py`/`cops front` birimine `ExecReload` eklenmedi (izin dışı yol).
- **DİKKAT (enterprise):** `ent_auth_rust_write=on` iken `/api/auth`, `/api/enterprise/*` (ya da `*`) bu listeye yazılırsa yazma
  Python'a gider ("tek yazar" bozulur). Orada geri alma `ent_auth_force_proxy` iledir. Canlıda yazma kipi kapalı.

### 3. `GET /api/front/stats`

- Kimlik: `web.token` ya da loopback + `X-Cops-Front`. Çok kullanıcıda da yalnız bunlar.
- `totals`, `endpoints[{method,path,local,fallback,forced,upstream_error}]`, `other`, `routes`, `force_proxy`, `started_at`,
  `version` (`Proxy::with_version`; copsd `GIT_SHA`, `build.rs`: kısa commit + derleme anında `rust/` kirliyse `-dirty`).
  Mount istekleri sayılmaz. Sayaçlar bellekte (yeniden başlatmada sıfır).
- Anahtar sınırı: `/q/`, `/readfile/` ve API dışı yollar ilk parçaya iner, kimlik benzeri parçalar `*`, yeni anahtarı yalnız yerel ya da
  panel kimlikli (web.token / `X-Cops-Front`) istek açar, 401/403/404 açmaz, en çok 512; gerisi `other`
  (`unauthenticated_forwards_cannot_open_keys`). Yalnız eklenti çerezli aktarımlar açılmamış anahtarda `other`da kalır.

### 4. `cops-parity`

- `cargo run -p cops-parity -- rust/crates/cops-parity/requests/basic.json` (yol çalışılan dizine göre); `--help` tam liste.
- Anahtar sırası önemsiz, `1` == `1.0`; liste başına `ignore` / `dynamic` (tür aynı olmalı) / `unordered`; bilinmeyen alan hata.
- Varsayılan yalnız GET/HEAD ve `side_effect_free: true`; `--include-unsafe` her isteği İKİ kez uygular.
- İstek `X-Cops-Parity: 1` taşırsa ön kapı `X-Cops-Served: local|python` döner; `expect: "local"` sahte pariteyi yakalar.
  Başlık istenmezse yanıtlar değişmez; üst sunucunun aynı adlı başlığı silinir.
- Gövde değerleri raporda yazılmaz (`--show-values` ile). Loopback dışı adres `--allow-remote` ister.
- Bilinen kasıtlı fark: `/api/steward/questions?all=1|since=` Rust'ta çıplak dizi (Danış sözleşmesi); listeye konmadı.

## `cops-proxy` / `copsd` genel API

Kırıcı değişiklik YOK, yalnız ek: modüller `routes`, `force`, `stats`, `front`; `Proxy::with_route_table|with_force_proxy|with_stats|
with_front_secret|with_version`; `StatsCfg`, `PARITY_HEADER`, `SERVED_HEADER`, `HEADER_READ_TIMEOUT`, `serve_on_with`, `harden`,
`python_path`, `is_internal_target`, `prepare_forward_headers`, `read_body_limited`; `copsd::routes::{register, RouteCtx}`,
`copsd::{DEFAULT_UPSTREAM, GIT_SHA, secret_file}`. `copsd::Ctx`e `front` alanı EKLENDİ (alan okuyan
tüketici etkilenmez), `ACCEPT_RETRY` eklendi; `copsd::Hooks`, `StatsCfg`, `MetricsCfg`, `RequestView` alanları değişmedi. `cops-auth`: `py_strip` ve `ct_eq` `pub` oldu (zorunlu küçük ek: çekirdekte tek `strip()` yardımcısı, ders H14; yeni
`front.rs` ikinci kopya yazmasın diye).

Davranış değişiklikleri (genel API imzası aynı): `Proxy::with_secret` artık sabit bir `FrontSecret` takar; takılı `FrontSecret`
varken `StatsCfg`/`MetricsCfg` `front_secret` alanı yok sayılır. Kancanın üstlendiği istekte eksik/kopan gövde kancaya
`BodyError::Read` olarak GİTMEZ, 408 JSON + kapanış döner (Python `_BodyTimeout`); `copsd-ent` eşlemesi ölü dal olur, testleri
geçti. Bildirilen `Content-Length` kancanın sınırını aşarsa gövde okunmadan `TooLarge`.

## Ders listesi (`docs/rust-lessons-from-python.md`)

Her test adı `rust/crates` altında grep ile bulundu (betik: eşlik bölüm 7). "AÇIK" = bu izde kapanmadı.

### 2.3 copsd / cops-proxy kontrol listesi

| # | madde | durum |
|---|---|---|
| 1 | Erken ret + aynı bağlantıda ikinci istek (gövdeli, chunked, büyük) | karşılandı: `early_reject_then_second_request_on_same_connection` (401 gövdeli/chunked/200 KiB, 413 1 MiB+, tablo 401), `unread_post_body_does_not_poison_next_request` |
| 2 | `Content-Length` doğrulama (negatif/dev/çift) ve gövde üst sınırı | karşılandı: `bad_content_length_is_rejected_before_python` (-1, abc, dev, çift, `2, 3`, `+2`: 400, Python'a hiç gitmez; TE+CL'de CL silinir), `oversized_body_is_reported_not_read_whole`, `security_headers_match_python_end_headers` (metrik 413, okumadan). Python'a aktarılan gövde akışlıdır, sınırı Python koyar (`MAX_JSON_BODY_BYTES`) |
| 3 | `Location` üreticisi tek işlev; `//`, `/\`, `%2f` | karşılandı: `same_origin_path` tek işlev; `prefixed_redirect_never_leaves_the_origin` (`//`, `///`, `//\`, `%2f%2f`, `%5C%5C`) |
| 4 | Mount senaryo matrisi + taze tarayıcı e2e | kısmen: `rootrel_requests_follow_the_referer_into_the_mount`, `referer_beats_the_cookie`, `cookie_routes_refererless_root_requests_to_the_app`, `panel_path_from_an_app_page_with_cookie_goes_to_the_app`, `rootrel_app_keeps_its_own_authorization_but_never_a_panel_credential`, `deep_page_under_the_mount_whose_base_href_is_its_own_segment_moves_to_that_root`. AÇIK: taze tarayıcı profiliyle kullanıcı yolu e2e (bu iz mount koduna dokunmadı; canlıya alırken cops) |
| 5 | Başlık aktarımı tablosu; XFF yalnız loopback eşten güvenilir, uzak eşin başlığı silinir | karşılandı: `forward_header_table`, `forwards_and_overwrites_x_forwarded_for`, `cf_connecting_ip_survives_only_from_loopback_peer`, `pin_client_ip_overwrites_only_for_non_loopback_peers`, `front_secret_is_injected_and_client_copy_dropped`, `token_cookie_and_authorization_never_reach_app_host_and_other_cookies_kept` |
| 6 | Adres denetimi `to_canonical()` sonrası tablo | karşılandı: `python_loopback_address_table`, `mount_upstream_address_table`, `mapped_ipv4_loopback_peer_may_report_https` |
| 7 | `Unavailable` asla `Allow`; istemci denetimindeki hata `Deny` | karşılandı: `hook_panic_and_timeout_fail_closed`, `authentication_failures_are_401_and_not_audited`, `filter_verdicts_strip_and_failures_fall_back_to_on_failure`, `oversized_body_is_reported_not_read_whole`, `short_body_is_408_and_closes` |
| 8 | Yerel uç yalnız TAM taklit ettiği sorgu biçimleri | karşılandı: `questions_endpoint_is_local_authenticated_and_everything_else_proxies` |
| 9 | `web.token` her istekte taze | karşılandı: `file_token_follows_rotation_deletion_and_mode` (her sorguda okur; imza önbelleği yok, daha taze) |
| 10 | `?token=`, çerez, Bearer altın vektör; `py_strip` tek yardımcı | karşılandı: `token_query_matches_python_parse_qs`, `whitespace_stripping_matches_python_str_strip`, `cookie_matches_python_rule`, `duplicate_cookie_takes_last_and_header_takes_first`, `bearer_with_trailing_latin1_space_is_rejected`; `cops_auth::py_strip` tek metin yardımcısı (`front.rs` onu kullanır; `lib.rs` `py_trim` bayt düzeyi Latin-1 başlık içindir) |
| 11 | Hata günlüğü hız sınırlı, 401 ayrı kova, sır yok, 502 kök neden | karşılandı: `limiter_caps_a_window_and_reports_skipped_lines_in_the_next`, `skipped_count_is_flushed_once_after_the_window_without_a_new_line`, `line_carries_method_mount_first_segment_and_status_only`, `upstream_reason_is_appended_clipped_and_single_line`, `matrix_params_are_cut_and_long_segments_clipped`. Gizli günlüğe yazılmaz (yalnız "var/YOK") |
| 12 | Panik/zaman aşımı kapalı yön; kuyruk taşması RED satırını düşürmez | karşılandı: `hook_panic_and_timeout_fail_closed`, `failing_sink_does_not_change_the_decision`. Kuyruk: uygulanmaz (çekirdekte denetim kuyruğu yok, `AuditSink` eşzamanlı; kuyruk enterprise'ta) |
| 13 | `--help` yan etkisiz; `GIT_SHA` `/api/front/stats`ta | karşılandı: `help_and_version_have_no_side_effects`, `stats_carry_binary_version`, `runtime_secret_changes_apply_without_restart` (ikilinin sürümü) |
| 14 | Canlı ikili güncelleme: `copsd.prev`, yalnız front restart | uygulanmaz: dağıtım adımı (CLAUDE.md, cops); bu iz canlıya dokunmaz |
| 15 | Route/yetki/host-routed tabloları tek kaynak + eşitlik testi | karşılandı: `registered_routes_have_authz_actions` (çekirdek rota tablosundaki her uç yetki tablosunda eşli), `table_is_identical_in_order`, `action_for_matches_python`, `bad_registrations_panic`. Host-routed: uygulanmaz (copsd uzak host'a yönlendirmez) |

### Genel 20 madde (bölüm 3)

| # | madde | durum |
|---|---|---|
| 1 | Hedef çözümü `Unique`; önek/"en yeni" tahmini yok | uygulanmaz: bu izde yıkıcı eylem yok. Rota eşleşmesi tam yol > uzun önek, yinelenen kayıt panik: `most_specific_entry_wins_and_unclaimed_falls_through`, `bad_registrations_panic` |
| 2 | `atomic_write`/transaction; çok yazarlı belgede kilit | karşılandı: çekirdek ön kapı yalnız mount öğrenme tablosuna yazar (SQLite transaction): `learned_sqlite_migrates_json_and_persists`; gizli, token, `force_proxy`, mount dosyası yalnız okunur |
| 3 | Belirsiz/okunamayan durum `Allow`/"başarı"/"yok" olmuyor | karşılandı: gizli okunamaz = gizli yok, güven yok (`file_secret_follows_changes_and_fails_closed`); `force_proxy` okunamaz = `*` (`force_file_parsing_and_failure_modes`, `force_proxy_size_limits`); token okunamaz = kapalı (`file_token_follows_rotation_deletion_and_mode`); kanca panik/süre = 500/503/401 (`hook_panic_and_timeout_fail_closed`) |
| 4 | Eylem sonucu doğrulanıyor; NEGATİF test | karşılandı: aktarım sonucu sayaçta (`upstream_error`): `stats_count_local_and_fallback_per_endpoint`; negatif: `upstream_down_gives_502`, `dead_app_upstream_is_502` |
| 5 | Hata yutma yok; yutulan hata sayaç/log taşır | gerekçeli: yutulanlar bağlantı sonu G/Ç (`serve_connection`, WS `copy_bidirectional`), bildirilecek eyleyen yok, sonuç bağlantının kapanması (kapalı yön). `HOME` yoksa gizli yolu `/.claude/...` olur, dosya yok = gizli yok (kapalı yön). Kancalar ve kurulum hataları günlüğe yazılır |
| 6 | Önbellek/ayar/sır açılışta bir kez okunup bayatlamıyor | karşılandı: gizli (`file_secret_follows_changes_and_fails_closed`, `runtime_secret_changes_apply_without_restart`), token (`file_token_follows_rotation_deletion_and_mode`), `force_proxy` SIGHUP (`sighup_reloads_force_proxy_and_stats_count_it`), mount 2 sn yoklama (`mount_table_hot_reload_through_proxy`). AÇIK: `copsd::Ctx.front_secret` (enterprise kancasına açılış değeri; sahip kararı). Rota tablosu ve yerel uçlar açılışta token yoksa takılmaz (istek Python'a: güvenli yön; token sonradan gelirse yeniden başlatma) |
| 7 | Her döngü/bekleme sınırlı | karşılandı: hizmet döngüleri (kabul, saatlik ilerleme işi, mount yoklama, SIGHUP) bilerek sonsuz ve süreçle ölür; istek yolundaki her bekleme süreli (başlık 15 sn, gövde 10 sn, kanca 2/60 sn); testlerin bekleme döngüleri süreli (`until`, `wait_exit`, `spawn` 10 sn) |
| 8 | Dış CLI/TUI fixture | uygulanmaz: ön kapı dış CLI/TUI ekranı okumaz |
| 9 | Alt süreç/bağlantı/görev sahibi; fd sızıntı testi | karşılandı: `no_fd_leak_after_many_connections` (`/proc/self/fd`, 200 bağlantı: aktarım, iç uç 404, başlık süresi, bozuk uzunluk); üst sunucu havuzu kapalı (`pool_max_idle_per_host(0)`); copsd alt süreç açmaz |
| 10 | Girdi sınırları: boş token, negatif/dev uzunluk, NaN, bozuk UTF-8, tip hatalı JSON | karşılandı: `query_and_bearer_accept_empty_token_is_closed_non_ascii_rejected`, `bad_content_length_is_rejected_before_python`, `file_secret_follows_changes_and_fails_closed` (UTF-8, 64 KiB, boşluk), `points_series_names_with_auth` (400), `force_proxy_size_limits` |
| 11 | Metin işaret/ad ayrıştırma tek modül, corpus | uygulanmaz: işaret ayrıştırma yok; mount kimliği `valid_id` (`parse_rejects_bad_paths_collisions_and_upstreams`) |
| 12 | Python ile paylaşılan kural altın vektörle; `$HOME` doğrudan yok | karşılandı: `trusted_client_ip_matches_python_test_front_xff`, `token_query_matches_python_parse_qs`, `table_is_identical_in_order`, `default_upstream_matches_python_front_cmd`; CSP eşitliği Python `CspParity.test_rust_csp_equals_python_csp`. `$HOME`: yalnız `front.secret` varsayılan yolu (Python `secret_path` ile AYNI, "Python hatası?" 3) ve `state_dir` son yedeği (Python `paths` ile aynı): `startup_ignores_unusable_secret_file_and_warns`, `token_file_defaults_to_state_dir` |
| 13 | Sırlar sızmıyor; kimlik başına "yetkisinin ötesi" matrisi | karşılandı: gizli/token `Debug`/`Display` türetmez, argv'de değil, günlükte yalnız var/YOK; `cops_ext_cookie_does_not_open_local_api`, `token_cookie_and_authorization_never_reach_app_host_and_other_cookies_kept`, `panel_entries_need_token_own_auth_entries_do_not`, `rootrel_app_keeps_its_own_authorization_but_never_a_panel_credential` |
| 14 | Yol/adres canonical; symlink/`..`/`::ffff:` | karşılandı: `static_assets_served_from_dist_with_headers_and_no_escape`, `python_loopback_address_table`, `mount_upstream_address_table`, `internal_block_covers_every_form_python_would_route` |
| 15 | Vekil/WS kullanıcı yolundan e2e | kısmen: keep-alive (`early_reject_then_second_request_on_same_connection`), WS tüneli (`websocket_upgrade_is_tunnelled`, `websocket_through_mount_is_bidirectional_and_clean`); Ping/Pong copsd'de uygulanmaz (çerçeveyi sonlandırmaz, bayt aktarır). AÇIK: taze tarayıcı profiliyle e2e (canlıya alırken cops) |
| 16 | Yeni uç/route eklendiyse tablolar eşit | karşılandı: bu izde yeni panel ucu yok (`/api/front/stats` yalnız Rust, kendi kimliği); `registered_routes_have_authz_actions` gelecek kayıtları denetler |
| 17 | Testler yalıtılmış; canlı dizin değişmedi | karşılandı: Rust testleri geçici dizin (`TmpDir`, `tempfile`) ve `127.0.0.1:0`; Python testleri geçici `HOME`/`CLAUDEOPS_DIR` ile koşuldu; 8765/28765 kullanılmadı (varsayılan üst port testi kaynak karşılaştırır) |
| 18 | Uzak host sürüm/yetenek, devre kesici | uygulanmaz: copsd uzak host çağırmaz (mount üst sunucusu yalnız loopback) |
| 19 | `GIT_SHA` görünür; canlı = main HEAD; `.prev` geri dönüş | karşılandı: `help_and_version_have_no_side_effects`, `stats_carry_binary_version`. Canlı = main denetimi ve `.prev` adımı cops'ta (uygulanmaz bu izde) |
| 20 | Perf/kök neden iddiası ölçümlü; `--dry-run` yan etkisiz; Python'a yeni özellik yok | karşılandı: performans iddiası yok; `--help`/`--version` yan etkisiz (`help_and_version_have_no_side_effects`); Python dosyası değişmedi (`git status -- py` boş) |

## Doğrulama (26 Kas gece, çalışma ağacı, taban `174c18e`)

- `cargo test -p cops-proxy -p copsd -p cops-parity -p cops-auth`: 122 geçti, 0 kaldı, 1 atlanan (doctest, önceden de `ignored`; önceki tur 85).
- `cargo clippy -p cops-proxy -p copsd -p cops-parity -p cops-auth --all-targets -- -D warnings`: temiz; `cargo fmt --check` temiz.
- Enterprise `34cfdd3` `copsd-ent`, scratchpad kopyasında (`git archive`), `--config patch` ile bu çalışma ağacına karşı
  (`copsd`, `cops-proxy`, `cops-auth`, `cops-local`, `cops-metrics`, `cops-progress`): `cargo test --offline` 50 geçti, 0 kaldı.
  Enterprise reposuna yazılmadı.
- Python (`py/tests` içinde, geçici `HOME` ve `CLAUDEOPS_DIR`): `test_front_internal` (CSP eşitliği `lib.rs`i okur),
  `test_front_cmd`, `test_authz_vectors`, `test_front_xff`: 24 test geçti.
- Testler yalnız geçici dizin ve boş port kullanır.

## Doğrulama (26 Kas, TBD#371 düzeltmeleri, kod `31ff561`)

- `cargo test -p cops-proxy -p copsd -p cops-parity -p cops-auth`: hata yok; clippy `-D warnings` temiz; `cargo fmt --check` (`copsd`, `cops-proxy`) temiz.
- Python tam paket (`unittest discover -s tests`): 5669 test, 23 atlanan, hata yok.
- Yeni üç gizli testi (sızmış, boş/bozuk, eşzamanlı) eski `front.py`ye karşı düşüyor.
- Enterprise `34cfdd3` `copsd-ent` (scratchpad kopyası, `patch` ile bu ağaca karşı): 50 geçti, 0 kaldı. Python paketiyle eşzamanlı ilk
  koşuda `r2_maint::b7_watchdog_closes_when_maintenance_stops` bir kez düştü; tekrar koşuda geçti (zamanlamaya duyarlı).
- Parite yeniden koşulmadı (son koşu `174c18e`); bu düzeltmeler yanıt üreten yolu değiştirmiyor.

BİRLEŞTİRMEYE HAZIR: rs/gate 31ff561 (yukarıdaki doğrulama). Birleştirilmiş ağaçta testler ve bağımsız gözden geçirme cops kapısında.
