# rs/hosts eşleme tablosu (Python -> cops-hosts)

ÜRETİLMİŞ DOSYA, elle düzenleme. Kaynak: `rust/crates/cops-hosts/tools/mapping.py`.
Denetim: `python3 -I rust/crates/cops-hosts/tools/mapping.py --check` (AÇIK varsa da düşsün: `--strict`).

Durumlar: **karşılandı** = Rust karşılığı ve onu sınayan test/parite adımı var (not sütunu sınırı ve farkı söyler); **kapsam dışı** = bu crate'in işi değil, gerekçe ve iz yazılı; **AÇIK** = kapsamda olduğu hâlde davranış ya da test karşılığı yok.

Rust yolları `rust/crates/cops-hosts/src/` altındadır; `tests/...` crate'in entegrasyon testleri (`tests/parity.rs` Python ile diferansiyel ve metin paritesi). Denetim adların kaynakta VARLIĞINI sınar; testin o davranışı gerçekten kapsadığı elle değerlendirilmiştir. Bu betik testleri koşturmaz. Belgeli farklar: `docs/rs-hosts.md` "Python'dan bilinçli farklar". Modül kapsamı: TAM modüllerde her `ast` tanımı (işlev, sınıf, metot, modül/sınıf sabiti, `re.*` çağrısı) bir satırdır; `web_steward.py`de adı desene uyan her tanım (crate'in karşılamadıkları `T10`), `authz.py`de giden imza adları. Test kapsamı: kapsam modüllerini içe aktaran/yamalayan ya da kapsam adlarını anan her `py/tests` dosyasının her `test*` metodu.

## Özet

| Küme | Toplam | karşılandı | kapsam dışı | AÇIK |
|---|---|---|---|---|
| tanım | 358 | 243 | 115 | 0 |
| test durumu (61 dosya) | 857 | 148 | 709 | 0 |

| Modül | Kapsam | Toplam | karşılandı | kapsam dışı | AÇIK |
|---|---|---|---|---|---|
| `commands/web_hosts.py` | TAM | 153 | 153 | 0 | 0 |
| `hosts.py` | TAM | 30 | 22 | 8 | 0 |
| `commands/web_grpc.py` | TAM | 42 | 21 | 21 | 0 |
| `commands/web_steward.py` | seçili (`(?i)remote\|host\|caps\|facts\|backoff\|backing_off\|transport\|_HEALTH\|_RECOVERED_DOWN`) | 124 | 38 | 86 | 0 |
| `authz.py` | seçili (giden imza) | 9 | 9 | 0 | 0 |

## AÇIK satırlar

Yok.

## Tanımlar

### `py/claudeops/commands/web_hosts.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `commands/web_hosts.py::HOST_ROUTED_PATHS` | sabit:65 | karşılandı | `consts.rs::HOST_ROUTED_PATHS` | `tests/parity.rs::host_routed_route_sets_equal_python_source`<br>`tests/parity.rs::host_routed_paths_have_the_same_authz_action_as_python` | yok |
| `commands/web_hosts.py::SECRET_BODY_PATHS` | sabit:79 | karşılandı | `consts.rs::SECRET_BODY_PATHS` | `tests/parity.rs::host_routed_route_sets_equal_python_source`<br>`tests/fake_proxy.rs::secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked` | yok |
| `commands/web_hosts.py::_secret_safe_url` | işlev:82 | karşılandı | `guard.rs::secret_safe_url` | `guard.rs::secret_urls`<br>`tests/parity.rs::address_filters_match_python` | yok |
| `commands/web_hosts.py::GET_HOST_ROUTED_PATHS` | sabit:90 | karşılandı | `consts.rs::GET_HOST_ROUTED_PATHS` | `tests/parity.rs::host_routed_route_sets_equal_python_source`<br>`tests/parity.rs::host_routed_paths_have_the_same_authz_action_as_python` | yok |
| `commands/web_hosts.py::FILE_DOWNLOAD_PATH` | sabit:94 | karşılandı | `consts.rs::FILE_DOWNLOAD_PATH`<br>`consts.rs::FILE_UPLOAD_PATH` | `tests/parity.rs::host_routed_route_sets_equal_python_source`<br>`tests/parity.rs::host_routed_paths_have_the_same_authz_action_as_python` | yok |
| `commands/web_hosts.py::FILE_UPLOAD_PATH` | sabit:95 | karşılandı | `consts.rs::FILE_DOWNLOAD_PATH`<br>`consts.rs::FILE_UPLOAD_PATH` | `tests/parity.rs::host_routed_route_sets_equal_python_source`<br>`tests/parity.rs::host_routed_paths_have_the_same_authz_action_as_python` | yok |
| `commands/web_hosts.py::STATUS_TIMEOUT_SECONDS` | sabit:117 | karşılandı | `consts.rs::Timeouts` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_http.rs::silent_server_times_out_and_socket_is_closed` | Rust'ta adım başı sınır + 600 sn mutlak tavan (belgeli fark) |
| `commands/web_hosts.py::TERM_READ_TIMEOUT_SECONDS` | sabit:125 | karşılandı | `consts.rs::Timeouts` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_http.rs::silent_server_times_out_and_socket_is_closed` | Rust'ta adım başı sınır + 600 sn mutlak tavan (belgeli fark) |
| `commands/web_hosts.py::ACTION_TIMEOUT_SECONDS` | sabit:129 | karşılandı | `consts.rs::Timeouts` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_http.rs::silent_server_times_out_and_socket_is_closed` | Rust'ta adım başı sınır + 600 sn mutlak tavan (belgeli fark) |
| `commands/web_hosts.py::POLL_INTERVAL_SECONDS` | sabit:130 | karşılandı | `consts.rs::POLL_INTERVAL` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_poller.rs::poller_beat_age_stays_within_one_interval` | yok |
| `commands/web_hosts.py::_EMPTY_REMOTE` | sabit:132 | karşılandı | `status.rs::HostStatus::failed` | `tests/parity.rs::status_reduction_matches_python`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python` | yok |
| `commands/web_hosts.py::_CONN_POOL_MAX_IDLE` | sabit:153 | karşılandı | `http.rs::POOL_MAX_IDLE` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_http.rs::pool_reuses_one_keepalive_connection` | yok |
| `commands/web_hosts.py::_conn_pool_lock` | sabit:154 | karşılandı | `http.rs::Pool.idle` | `tests/fake_http.rs::pool_reuses_one_keepalive_connection` | yok |
| `commands/web_hosts.py::_conn_pool` | sabit:155 | karşılandı | `http.rs::Pool.idle` | `tests/fake_http.rs::pool_reuses_one_keepalive_connection` | yok |
| `commands/web_hosts.py::_inflight_lock` | sabit:188 | karşılandı | `flight.rs::Flights::begin` | `flight.rs::busy_returns_last_good_and_releases_on_drop`<br>`tests/fake_proxy.rs::concurrent_same_url_sends_one_request_and_reuses_last_good` | anahtarda kullanıcı kimliği (belgeli fark) |
| `commands/web_hosts.py::_inflight_starts` | sabit:190 | karşılandı | `flight.rs::Flights::begin` | `flight.rs::busy_returns_last_good_and_releases_on_drop`<br>`tests/fake_proxy.rs::concurrent_same_url_sends_one_request_and_reuses_last_good` | anahtarda kullanıcı kimliği (belgeli fark) |
| `commands/web_hosts.py::_dedup_last_good` | sabit:195 | karşılandı | `flight.rs::Flight::remember`<br>`flight.rs::LAST_GOOD_MAX` | `flight.rs::lru_is_bounded_and_keeps_recent`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::_DEDUP_LAST_GOOD_MAX` | sabit:196 | karşılandı | `flight.rs::Flight::remember`<br>`flight.rs::LAST_GOOD_MAX` | `flight.rs::lru_is_bounded_and_keeps_recent`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::_remember_good` | işlev:199 | karşılandı | `flight.rs::Flight::remember`<br>`flight.rs::LAST_GOOD_MAX` | `flight.rs::lru_is_bounded_and_keeps_recent`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::_INFLIGHT_MAX_SECONDS` | sabit:221 | karşılandı | `flight.rs::INFLIGHT_MAX` | `flight.rs::stale_flight_is_replaced_and_old_drop_does_not_free_new`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::_split_url` | işlev:224 | karşılandı | `endpoint.rs::Endpoint::parse`<br>`proxy.rs::target` | `tests/fake_proxy.rs::outgoing_host_is_forced_local_and_caller_query_is_filtered` | yok |
| `commands/web_hosts.py::_pool_key` | işlev:235 | karşılandı | `endpoint.rs::Endpoint::pool_key` | `tests/fake_http.rs::pool_reuses_one_keepalive_connection` | yok |
| `commands/web_hosts.py::_BlockedPeer` | sınıf:240 | karşılandı | `net.rs::blocked_error` | `tests/fake_proxy.rs::secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked`<br>`tests/fake_ws.rs::dns_name_resolving_to_loopback_is_refused_for_ws_before_connecting` | yok |
| `commands/web_hosts.py::_check_peer` | işlev:244 | karşılandı | `net.rs::Connector::tcp` | `tests/fake_proxy.rs::secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked`<br>`tests/fake_ws.rs::dns_name_resolving_to_loopback_is_refused_for_ws_before_connecting` | denetim bağlanmadan ÖNCE (çözülen adres = bağlanılan adres) |
| `commands/web_hosts.py::_GuardedHTTPConnection` | sınıf:261 | karşılandı | `net.rs::Connector::connect` | `tests/fake_tls.rs::wss_and_https_rest_work_with_a_custom_root`<br>`tests/fake_proxy.rs::secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked` | yok |
| `commands/web_hosts.py::_GuardedHTTPConnection.connect` | işlev:262 | karşılandı | `net.rs::Connector::connect` | `tests/fake_tls.rs::wss_and_https_rest_work_with_a_custom_root`<br>`tests/fake_proxy.rs::secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked` | yok |
| `commands/web_hosts.py::_GuardedHTTPSConnection` | sınıf:267 | karşılandı | `net.rs::Connector::connect` | `tests/fake_tls.rs::wss_and_https_rest_work_with_a_custom_root`<br>`tests/fake_proxy.rs::secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked` | yok |
| `commands/web_hosts.py::_GuardedHTTPSConnection.connect` | işlev:268 | karşılandı | `net.rs::Connector::connect` | `tests/fake_tls.rs::wss_and_https_rest_work_with_a_custom_root`<br>`tests/fake_proxy.rs::secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked` | yok |
| `commands/web_hosts.py::_conn_cls_for` | işlev:273 | karşılandı | `net.rs::Connector::connect` | `tests/fake_tls.rs::wss_and_https_rest_work_with_a_custom_root`<br>`tests/fake_proxy.rs::secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked` | yok |
| `commands/web_hosts.py::_guarded_ws_connect` | işlev:277 | karşılandı | `ws.rs::HostClient::ws_connect` | `tests/fake_ws.rs::dns_name_resolving_to_loopback_is_refused_for_ws_before_connecting`<br>`tests/fake_ws.rs::ws_message_limit_is_16_mib_exactly` | Python `close_timeout` 1,5 sn: Rust düşürmede beklemez (görev iptal, soket kapanır), yoklamada kapanış 1 sn |
| `commands/web_hosts.py::_conn_is_alive` | işlev:300 | karşılandı | `http.rs::Pool::checkout` | `tests/fake_http.rs::server_closed_idle_connection_does_not_fail_post` | yok |
| `commands/web_hosts.py::_pool_checkout` | işlev:325 | karşılandı | `http.rs::Pool::checkout`<br>`http.rs::Pool::checkin` | `tests/fake_http.rs::pool_reuses_one_keepalive_connection`<br>`tests/fake_http.rs::server_closed_idle_connection_does_not_fail_post` | yok |
| `commands/web_hosts.py::_pool_checkin` | işlev:354 | karşılandı | `http.rs::Pool::checkout`<br>`http.rs::Pool::checkin` | `tests/fake_http.rs::pool_reuses_one_keepalive_connection`<br>`tests/fake_http.rs::server_closed_idle_connection_does_not_fail_post` | yok |
| `commands/web_hosts.py::REFUSED_PREFIX` | sabit:374 | karşılandı | `proxy.rs::CallError` | `tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::_refused` | işlev:377 | karşılandı | `proxy.rs::refused_reply` | `tests/fake_proxy.rs::signer_refusal_panic_and_bad_headers_are_502_and_nothing_is_sent` | yok |
| `commands/web_hosts.py::_ws_signed_kw` | işlev:385 | karşılandı | `proxy.rs::HostClient::sign_service` | `tests/fake_ws.rs::ws_handshake_carries_a_fresh_panel_signature_per_connection` | yok |
| `commands/web_hosts.py::_signed_headers` | işlev:395 | karşılandı | `proxy.rs::HostClient::sign` | `tests/fake_proxy.rs::user_caller_is_signed_over_path_and_body_without_query`<br>`tests/fake_proxy.rs::unbound_caller_is_never_signed` | host adı kayıttan (Python base_url eşleşmesinden; belgeli fark) |
| `commands/web_hosts.py::_http_json` | işlev:407 | karşılandı | `proxy.rs::HostClient::json`<br>`proxy.rs::HostClient::exchange`<br>`http.rs::Pool::attempt` | `tests/fake_http.rs::stale_pooled_get_is_retried_once_with_fresh_signature`<br>`tests/fake_http.rs::stale_pooled_post_that_reached_server_is_not_retried`<br>`tests/fake_http.rs::non_json_non_object_and_error_statuses`<br>`tests/fake_proxy.rs::concurrent_same_url_sends_one_request_and_reuses_last_good` | yok |
| `commands/web_hosts.py::_CLI_OPTIONS_FIELDS` | sabit:510 | karşılandı | `status.rs::CLI_OPTION_FIELDS` | `tests/parity.rs::status_reduction_matches_python` | yok |
| `commands/web_hosts.py::_normalize_cli_options` | işlev:513 | karşılandı | `status.rs::normalize_cli_options` | `tests/parity.rs::status_reduction_matches_python`<br>`tests/fake_poller.rs::malformed_remote_status_is_an_error_or_reduced_to_empty_fields` | yok |
| `commands/web_hosts.py::_orphan_brief` | işlev:525 | karşılandı | `status.rs::orphan_brief` | `tests/parity.rs::status_reduction_matches_python` | Python `int(x or 0)` kuralı; Python'da `Infinity` yakalanmayan OverflowError (Python bulgusu) |
| `commands/web_hosts.py::_build_running` | işlev:535 | karşılandı | `status.rs::build_running` | `tests/parity.rs::status_reduction_matches_python` | yok |
| `commands/web_hosts.py::_fwd_brief` | işlev:541 | karşılandı | `status.rs::fwd_brief` | `tests/parity.rs::status_reduction_matches_python` | metin/nesne `kids` Python'da karaktere/anahtara bölünür, Rust `fwd`i yok sayar (Python bulgusu, parity bilinen fark) |
| `commands/web_hosts.py::_tag_rows` | işlev:554 | karşılandı | `status.rs::tag_rows` | `tests/parity.rs::status_reduction_matches_python`<br>`tests/fake_poller.rs::malformed_remote_status_is_an_error_or_reduced_to_empty_fields` | yok |
| `commands/web_hosts.py::_finalize_remote_result` | işlev:569 | karşılandı | `status.rs::finalize` | `tests/parity.rs::status_reduction_matches_python`<br>`tests/fake_poller.rs::malformed_remote_status_is_an_error_or_reduced_to_empty_fields` | dizi olmayan `cli_list`/`dups` Python'da olduğu gibi geçer, Rust boş dizi (Python bulgusu) |
| `commands/web_hosts.py::_fetch_status_from` | işlev:592 | karşılandı | `federation.rs::Federation::status_from` | `tests/fake_poller.rs::malformed_remote_status_is_an_error_or_reduced_to_empty_fields` | 2xx dışı yanıt hata (belgeli fark) |
| `commands/web_hosts.py::fetch_remote_status` | işlev:612 | karşılandı | `federation.rs::Federation::fetch_status` | `tests/fake_poller.rs::malformed_remote_status_is_an_error_or_reduced_to_empty_fields`<br>`tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale` | yok |
| `commands/web_hosts.py::FALLBACK_TIMEOUT_SECONDS` | sabit:631 | karşılandı | `consts.rs::Timeouts` | `tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::_is_private_lan_http` | işlev:634 | karşılandı | `guard.rs::is_private_lan_http` | `tests/parity.rs::address_filters_match_python` | Rust yalnız RFC1918 + ULA (Python `is_private` geniş; parity bilinen fark, daha sıkı) |
| `commands/web_hosts.py::_candidate_allowed` | işlev:649 | karşılandı | `guard.rs::candidate_allowed` | `guard.rs::https_never_downgrades_to_public_http`<br>`tests/parity.rs::address_filters_match_python`<br>`tests/fake_poller.rs::https_base_never_falls_back_to_plain_http` | yok |
| `commands/web_hosts.py::_apply_probe_choice` | işlev:657 | karşılandı | `federation.rs::Federation::apply_probe_choice` | `tests/fake_poller.rs::probe_choice_only_promotes_registered_allowed_candidates` | seçim deposu (`host_probe`) T7; Rust yalnız kayıtlı ve izinli adayı terfi ettirir |
| `commands/web_hosts.py::_try_fallback_urls` | işlev:673 | karşılandı | `federation.rs::Federation::try_fallback_urls` | `tests/fake_poller.rs::extra_urls_fallback_runs_on_threshold_and_every_twentieth_failure`<br>`tests/fake_poller.rs::https_base_never_falls_back_to_plain_http`<br>`tests/fake_poller.rs::host_without_extra_urls_never_tries_a_fallback` | yok |
| `commands/web_hosts.py::_cache_lock` | sabit:711 | karşılandı | `status.rs::StatusBook::record` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python` | yok |
| `commands/web_hosts.py::_cache` | sabit:712 | karşılandı | `status.rs::StatusBook::record` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python` | yok |
| `commands/web_hosts.py::_last_good` | sabit:720 | karşılandı | `status.rs::StatusBook::record` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python` | yok |
| `commands/web_hosts.py::_apply_stale_while_error` | işlev:723 | karşılandı | `status.rs::StatusBook::record` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python` | yok |
| `commands/web_hosts.py::CONSECUTIVE_FAILURES_BEFORE_ERROR` | sabit:754 | karşılandı | `consts.rs::CONSECUTIVE_FAILURES_BEFORE_ERROR` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale` | yok |
| `commands/web_hosts.py::STATUS_PUSH_SILENCE_SECONDS` | sabit:757 | karşılandı | `consts.rs::STATUS_PUSH_SILENCE` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_ws.rs::status_silence_watchdog_boundary` | yok |
| `commands/web_hosts.py::_last_try_at` | sabit:758 | karşılandı | `status.rs::StatusBook::last_try_at` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/parity.rs::steward_client_parts_match_python` | yok |
| `commands/web_hosts.py::_fail_streak` | sabit:759 | karşılandı | `status.rs::StatusBook::fail_streak` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python` | yok |
| `commands/web_hosts.py::_last_ok_at` | sabit:762 | karşılandı | `status.rs::StatusBook::last_ok_at` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale` | yok |
| `commands/web_hosts.py::_record_poll_result` | işlev:765 | karşılandı | `status.rs::StatusBook::record` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python` | yok |
| `commands/web_hosts.py::_poll_once` | işlev:793 | karşılandı | `federation.rs::Federation::poll_once`<br>`federation.rs::Federation::poll_host` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/fake_poller.rs::extra_urls_fallback_runs_on_threshold_and_every_twentieth_failure`<br>`tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data` | host'lar eşzamanlı (belgeli fark) |
| `commands/web_hosts.py::POLLER_STALL_SECONDS` | sabit:832 | karşılandı | `consts.rs::POLLER_STALL` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers` | yok |
| `commands/web_hosts.py::WATCHDOG_INTERVAL_SECONDS` | sabit:833 | karşılandı | `consts.rs::WATCHDOG_INTERVAL` | `tests/parity.rs::shared_constants_and_error_texts_equal_python` | Rust'ta ayrı bekçi döngüsü yok: tur zaman aşımı (POLLER_STALL) aynı işi görür, sabit eşitlik için tutulur |
| `commands/web_hosts.py::_poller_lock` | sabit:834 | karşılandı | `federation.rs::Running` | `tests/fake_poller.rs::dropping_running_stops_poller_and_prober`<br>`tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers` | yok |
| `commands/web_hosts.py::_poller_started` | sabit:835 | karşılandı | `federation.rs::Running` | `tests/fake_poller.rs::dropping_running_stops_poller_and_prober`<br>`tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers` | yok |
| `commands/web_hosts.py::_poller_gen` | sabit:836 | karşılandı | `federation.rs::Running` | `tests/fake_poller.rs::dropping_running_stops_poller_and_prober`<br>`tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers` | yok |
| `commands/web_hosts.py::_poller_beat` | sabit:837 | karşılandı | `federation.rs::Federation.beat`<br>`federation.rs::Federation.restarts` | `tests/fake_poller.rs::poller_beat_age_stays_within_one_interval`<br>`tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers`<br>`tests/fake_restart.rs::panicking_turn_is_counted_and_the_poller_keeps_running` | yok |
| `commands/web_hosts.py::_poller_thread` | sabit:838 | karşılandı | `federation.rs::Running` | `tests/fake_poller.rs::dropping_running_stops_poller_and_prober`<br>`tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers` | yok |
| `commands/web_hosts.py::_poller_restarts` | sabit:839 | karşılandı | `federation.rs::Federation.beat`<br>`federation.rs::Federation.restarts` | `tests/fake_poller.rs::poller_beat_age_stays_within_one_interval`<br>`tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers`<br>`tests/fake_restart.rs::panicking_turn_is_counted_and_the_poller_keeps_running` | yok |
| `commands/web_hosts.py::_poller_loop` | işlev:842 | karşılandı | `federation.rs::Federation::start` | `tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers`<br>`tests/fake_restart.rs::panicking_turn_is_counted_and_the_poller_keeps_running`<br>`tests/fake_poller.rs::dropping_running_stops_poller_and_prober` | takılan tur iptal edilip yeniden başlar (iş parçacığı nesli yerine) |
| `commands/web_hosts.py::_spawn_poller_locked` | işlev:856 | karşılandı | `federation.rs::Federation::start` | `tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers`<br>`tests/fake_restart.rs::panicking_turn_is_counted_and_the_poller_keeps_running`<br>`tests/fake_poller.rs::dropping_running_stops_poller_and_prober` | takılan tur iptal edilip yeniden başlar (iş parçacığı nesli yerine) |
| `commands/web_hosts.py::poller_health` | işlev:864 | karşılandı | `federation.rs::Federation::poller_health` | `tests/fake_poller.rs::poller_beat_age_stays_within_one_interval`<br>`tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers` | yok |
| `commands/web_hosts.py::ensure_poller_alive` | işlev:872 | karşılandı | `federation.rs::Federation::start` | `tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers`<br>`tests/fake_restart.rs::panicking_turn_is_counted_and_the_poller_keeps_running`<br>`tests/fake_poller.rs::dropping_running_stops_poller_and_prober` | takılan tur iptal edilip yeniden başlar (iş parçacığı nesli yerine) |
| `commands/web_hosts.py::_watchdog_loop` | işlev:889 | karşılandı | `federation.rs::Federation::start` | `tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers`<br>`tests/fake_restart.rs::panicking_turn_is_counted_and_the_poller_keeps_running`<br>`tests/fake_poller.rs::dropping_running_stops_poller_and_prober` | takılan tur iptal edilip yeniden başlar (iş parçacığı nesli yerine) |
| `commands/web_hosts.py::start_remote_poller` | işlev:898 | karşılandı | `federation.rs::Federation::start` | `tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers`<br>`tests/fake_restart.rs::panicking_turn_is_counted_and_the_poller_keeps_running`<br>`tests/fake_poller.rs::dropping_running_stops_poller_and_prober` | takılan tur iptal edilip yeniden başlar (iş parçacığı nesli yerine) |
| `commands/web_hosts.py::_PROBE_MIN_GAP_SECONDS` | sabit:910 | karşılandı | `federation.rs::Federation::probe_host`<br>`consts.rs::PROBE_MIN_GAP` | `tests/fake_poller.rs::probe_host_is_rate_limited_and_records_like_the_poller`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::_probe_at` | sabit:911 | karşılandı | `federation.rs::Federation::probe_host`<br>`consts.rs::PROBE_MIN_GAP` | `tests/fake_poller.rs::probe_host_is_rate_limited_and_records_like_the_poller`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::_probe_lock` | sabit:912 | karşılandı | `federation.rs::Federation::probe_host`<br>`consts.rs::PROBE_MIN_GAP` | `tests/fake_poller.rs::probe_host_is_rate_limited_and_records_like_the_poller`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::probe_host` | işlev:915 | karşılandı | `federation.rs::Federation::probe_host`<br>`consts.rs::PROBE_MIN_GAP` | `tests/fake_poller.rs::probe_host_is_rate_limited_and_records_like_the_poller`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::last_try_at` | işlev:935 | karşılandı | `status.rs::StatusBook::last_try_at`<br>`status.rs::StatusBook::cached`<br>`status.rs::StatusBook::last_ok_at` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/parity.rs::steward_client_parts_match_python` | yok |
| `commands/web_hosts.py::get_cached` | işlev:940 | karşılandı | `status.rs::StatusBook::last_try_at`<br>`status.rs::StatusBook::cached`<br>`status.rs::StatusBook::last_ok_at` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/parity.rs::steward_client_parts_match_python` | yok |
| `commands/web_hosts.py::last_ok_at` | işlev:946 | karşılandı | `status.rs::StatusBook::last_try_at`<br>`status.rs::StatusBook::cached`<br>`status.rs::StatusBook::last_ok_at` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/parity.rs::steward_client_parts_match_python` | yok |
| `commands/web_hosts.py::test_now` | işlev:952 | karşılandı | `federation.rs::Federation::test_now` | `tests/fake_poller.rs::test_now_returns_the_fresh_result_not_the_smoothed_one` | yok |
| `commands/web_hosts.py::merge_status` | işlev:984 | karşılandı | `status.rs::StatusBook::merge_status` | `tests/fake_poller.rs::merge_status_resorts_globally_and_keeps_host_rows`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python` | ayar `fleet_sort` çağıranın (`sort_by_cwd`) |
| `commands/web_hosts.py::merge_status._text` | işlev:1036 | karşılandı | `status.rs::StatusBook::merge_status` | `tests/fake_poller.rs::merge_status_resorts_globally_and_keeps_host_rows`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python` | ayar `fleet_sort` çağıranın (`sort_by_cwd`) |
| `commands/web_hosts.py::merge_status._row_key` | işlev:1039 | karşılandı | `status.rs::StatusBook::merge_status` | `tests/fake_poller.rs::merge_status_resorts_globally_and_keeps_host_rows`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python` | ayar `fleet_sort` çağıranın (`sort_by_cwd`) |
| `commands/web_hosts.py::proxy_action` | işlev:1048 | karşılandı | `proxy.rs::HostClient::proxy_action` | `tests/fake_proxy.rs::outgoing_host_is_forced_local_and_caller_query_is_filtered`<br>`tests/fake_proxy.rs::secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked` | yok |
| `commands/web_hosts.py::TERM_RETRY_PATHS` | sabit:1077 | karşılandı | `consts.rs::TERM_RETRY_PATHS`<br>`consts.rs::Timeouts`<br>`consts.rs::TERM_MAX_ATTEMPTS` | `tests/parity.rs::host_routed_route_sets_equal_python_source`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_proxy.rs::term_input_retries_three_times_with_same_input_id` | yok |
| `commands/web_hosts.py::TERM_ATTEMPT_TIMEOUT` | sabit:1078 | karşılandı | `consts.rs::TERM_RETRY_PATHS`<br>`consts.rs::Timeouts`<br>`consts.rs::TERM_MAX_ATTEMPTS` | `tests/parity.rs::host_routed_route_sets_equal_python_source`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_proxy.rs::term_input_retries_three_times_with_same_input_id` | yok |
| `commands/web_hosts.py::TERM_MAX_ATTEMPTS` | sabit:1079 | karşılandı | `consts.rs::TERM_RETRY_PATHS`<br>`consts.rs::Timeouts`<br>`consts.rs::TERM_MAX_ATTEMPTS` | `tests/parity.rs::host_routed_route_sets_equal_python_source`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_proxy.rs::term_input_retries_three_times_with_same_input_id` | yok |
| `commands/web_hosts.py::proxy_term_action` | işlev:1082 | karşılandı | `proxy.rs::HostClient::proxy_term_action`<br>`proxy.rs::valid_input_id` | `tests/fake_proxy.rs::term_input_retries_three_times_with_same_input_id`<br>`tests/parity.rs::input_id_rule_is_python_or_stricter` | kimlik kuralı Python'dan sıkı: ASCII dışı kimlik yeniden denenmez (yinelenen girdi riski yok) |
| `commands/web_hosts.py::_http_raw` | işlev:1099 | karşılandı | `proxy.rs::HostClient::proxy_get_raw` | `tests/fake_proxy.rs::download_passes_raw_body_and_only_two_headers`<br>`tests/fake_proxy.rs::concurrent_same_download_is_refused_not_cached` | yok |
| `commands/web_hosts.py::proxy_get` | işlev:1144 | karşılandı | `proxy.rs::HostClient::proxy_get` | `tests/fake_proxy.rs::outgoing_host_is_forced_local_and_caller_query_is_filtered`<br>`tests/fake_proxy.rs::concurrent_same_url_sends_one_request_and_reuses_last_good` | `token`/`ticket` da süzülür (belgeli fark) |
| `commands/web_hosts.py::proxy_get_raw` | işlev:1171 | karşılandı | `proxy.rs::HostClient::proxy_get_raw` | `tests/fake_proxy.rs::download_passes_raw_body_and_only_two_headers`<br>`tests/fake_proxy.rs::concurrent_same_download_is_refused_not_cached` | yok |
| `commands/web_hosts.py::_BoundedReader` | sınıf:1187 | karşılandı | `http.rs::Counted` | `tests/fake_proxy.rs::upload_body_ending_early_or_overflowing_is_an_error` | yok |
| `commands/web_hosts.py::_BoundedReader.__slots__` | sabit:1195 | karşılandı | `http.rs::Counted` | `tests/fake_proxy.rs::upload_body_ending_early_or_overflowing_is_an_error` | yok |
| `commands/web_hosts.py::_BoundedReader.__init__` | işlev:1197 | karşılandı | `http.rs::Counted` | `tests/fake_proxy.rs::upload_body_ending_early_or_overflowing_is_an_error` | yok |
| `commands/web_hosts.py::_BoundedReader.read` | işlev:1201 | karşılandı | `http.rs::Counted` | `tests/fake_proxy.rs::upload_body_ending_early_or_overflowing_is_an_error` | yok |
| `commands/web_hosts.py::proxy_post_raw` | işlev:1212 | karşılandı | `proxy.rs::HostClient::proxy_post_raw` | `tests/fake_proxy.rs::slow_but_progressing_upload_is_not_cut`<br>`tests/fake_proxy.rs::stalled_upload_times_out_and_bad_reply_is_reported` | nesne olmayan JSON yanıt Rust'ta `bad response` (Python olduğu gibi döner; daha sıkı) |
| `commands/web_hosts.py::_TIER_RANK` | sabit:1274 | karşılandı | `tier.rs::Tier` | `tier.rs::upgrade_is_immediate_downgrade_is_tolerated`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python` | yok |
| `commands/web_hosts.py::CAPABILITY_PROBE_INTERVAL_SECONDS` | sabit:1275 | karşılandı | `consts.rs::CAPABILITY_PROBE_INTERVAL` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_poller.rs::dropping_running_stops_poller_and_prober` | yok |
| `commands/web_hosts.py::_GRPC_PROBE_TIMEOUT_SECONDS` | sabit:1276 | karşılandı | `consts.rs::Timeouts` | `tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::_WS_PROBE_TIMEOUT_SECONDS` | sabit:1277 | karşılandı | `consts.rs::Timeouts` | `tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::_tier_lock` | sabit:1279 | karşılandı | `tier.rs::TierBook::update`<br>`tier.rs::TierBook::get` | `tier.rs::upgrade_is_immediate_downgrade_is_tolerated`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python`<br>`tests/fake_ws.rs::ws_probe_raises_tier_at_once_and_lowers_it_only_after_tolerance` | yok |
| `commands/web_hosts.py::_tier` | sabit:1280 | karşılandı | `tier.rs::TierBook::update`<br>`tier.rs::TierBook::get` | `tier.rs::upgrade_is_immediate_downgrade_is_tolerated`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python`<br>`tests/fake_ws.rs::ws_probe_raises_tier_at_once_and_lowers_it_only_after_tolerance` | yok |
| `commands/web_hosts.py::_tier_downgrade_streak` | sabit:1281 | karşılandı | `tier.rs::TierBook::update`<br>`tier.rs::TierBook::get` | `tier.rs::upgrade_is_immediate_downgrade_is_tolerated`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python`<br>`tests/fake_ws.rs::ws_probe_raises_tier_at_once_and_lowers_it_only_after_tolerance` | yok |
| `commands/web_hosts.py::_ws_url` | işlev:1284 | karşılandı | `ws.rs::HostClient::ws_connect` | `tests/fake_ws.rs::base_path_is_kept_for_ws_and_signed_over_it` | taban yolu korunur (belgeli fark) |
| `commands/web_hosts.py::_probe_ws` | işlev:1291 | karşılandı | `ws.rs::HostClient::ws_probe` | `tests/fake_ws.rs::ws_probe_raises_tier_at_once_and_lowers_it_only_after_tolerance` | yok |
| `commands/web_hosts.py::_probe_tier` | işlev:1305 | karşılandı | `federation.rs::Federation::probe_tier` | `tests/fake_ws.rs::ws_probe_raises_tier_at_once_and_lowers_it_only_after_tolerance`<br>`tests/fake_grpc.rs::grpc_probe_needs_transport_token_and_service_and_tier_moves_like_python` | yok |
| `commands/web_hosts.py::_update_tier` | işlev:1317 | karşılandı | `tier.rs::TierBook::update`<br>`tier.rs::TierBook::get` | `tier.rs::upgrade_is_immediate_downgrade_is_tolerated`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python`<br>`tests/fake_ws.rs::ws_probe_raises_tier_at_once_and_lowers_it_only_after_tolerance` | yok |
| `commands/web_hosts.py::get_tier` | işlev:1336 | karşılandı | `tier.rs::TierBook::update`<br>`tier.rs::TierBook::get` | `tier.rs::upgrade_is_immediate_downgrade_is_tolerated`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python`<br>`tests/fake_ws.rs::ws_probe_raises_tier_at_once_and_lowers_it_only_after_tolerance` | yok |
| `commands/web_hosts.py::_capability_prober_loop` | işlev:1341 | karşılandı | `federation.rs::Federation::start`<br>`federation.rs::Federation::probe_tiers_once` | `tests/fake_poller.rs::dropping_running_stops_poller_and_prober`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed` | yok |
| `commands/web_hosts.py::_prober_lock` | sabit:1354 | karşılandı | `federation.rs::Federation::start`<br>`federation.rs::Federation::probe_tiers_once` | `tests/fake_poller.rs::dropping_running_stops_poller_and_prober`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed` | yok |
| `commands/web_hosts.py::_prober_started` | sabit:1355 | karşılandı | `federation.rs::Federation::start`<br>`federation.rs::Federation::probe_tiers_once` | `tests/fake_poller.rs::dropping_running_stops_poller_and_prober`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed` | yok |
| `commands/web_hosts.py::start_capability_prober` | işlev:1358 | karşılandı | `federation.rs::Federation::start`<br>`federation.rs::Federation::probe_tiers_once` | `tests/fake_poller.rs::dropping_running_stops_poller_and_prober`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed` | yok |
| `commands/web_hosts.py::_CONSUMER_DEATH_LOG_MIN_INTERVAL_SECONDS` | sabit:1373 | karşılandı | `consts.rs::CONSUMER_DEATH_LOG_MIN_INTERVAL`<br>`push.rs::DeathLog::report` | `push.rs::consumer_death_is_logged_once_a_minute_per_label`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::_consumer_death_log_last` | sabit:1374 | karşılandı | `consts.rs::CONSUMER_DEATH_LOG_MIN_INTERVAL`<br>`push.rs::DeathLog::report` | `push.rs::consumer_death_is_logged_once_a_minute_per_label`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::_log_consumer_death` | işlev:1377 | karşılandı | `consts.rs::CONSUMER_DEATH_LOG_MIN_INTERVAL`<br>`push.rs::DeathLog::report` | `push.rs::consumer_death_is_logged_once_a_minute_per_label`<br>`tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `commands/web_hosts.py::_PushConsumer` | sınıf:1391 | karşılandı | `push.rs::PushConsumer::spawn` | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data`<br>`tests/fake_ws.rs::junk_frames_keep_the_stream_alive_but_rest_polling_continues`<br>`tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | yok |
| `commands/web_hosts.py::_PushConsumer.__init__` | işlev:1400 | karşılandı | `push.rs::PushConsumer::spawn` | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data`<br>`tests/fake_ws.rs::junk_frames_keep_the_stream_alive_but_rest_polling_continues`<br>`tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | yok |
| `commands/web_hosts.py::_PushConsumer._run` | işlev:1419 | karşılandı | `push.rs::PushConsumer::spawn` | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data`<br>`tests/fake_ws.rs::junk_frames_keep_the_stream_alive_but_rest_polling_continues`<br>`tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | yok |
| `commands/web_hosts.py::_PushConsumer.is_alive` | işlev:1443 | karşılandı | `push.rs::PushConsumer::is_alive` | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data` | yok |
| `commands/web_hosts.py::_PushConsumer.silent_seconds` | işlev:1446 | karşılandı | `push.rs::PushConsumer::silent` | `tests/fake_ws.rs::status_silence_watchdog_boundary` | yok |
| `commands/web_hosts.py::_PushConsumer.stop` | işlev:1451 | karşılandı | `push.rs::PushConsumer` | `tests/fake_ws.rs::dropped_streams_close_their_sockets_and_leak_no_fds`<br>`tests/fake_grpc.rs::dropped_grpc_consumers_cancel_streams_and_removed_hosts_close_the_channel` | durdurma = `Drop` (görev iptal, bağlantı kapanır); kasıtlı durdurma ölüm sayılmaz |
| `commands/web_hosts.py::_PushConsumer._close_call` | işlev:1459 | karşılandı | `push.rs::PushConsumer` | `tests/fake_ws.rs::dropped_streams_close_their_sockets_and_leak_no_fds`<br>`tests/fake_grpc.rs::dropped_grpc_consumers_cancel_streams_and_removed_hosts_close_the_channel` | durdurma = `Drop` (görev iptal, bağlantı kapanır); kasıtlı durdurma ölüm sayılmaz |
| `commands/web_hosts.py::_status_consumer_lock` | sabit:1471 | karşılandı | `federation.rs::Federation.consumers` | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data`<br>`tests/fake_ws.rs::status_silence_watchdog_boundary` | yok |
| `commands/web_hosts.py::_status_consumers` | sabit:1472 | karşılandı | `federation.rs::Federation.consumers` | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data`<br>`tests/fake_ws.rs::status_silence_watchdog_boundary` | yok |
| `commands/web_hosts.py::_bad_frame_log_last` | sabit:1475 | karşılandı | `push.rs::SkipLog` | `push.rs::skipped_frames_are_logged_at_most_once_a_minute_per_kind`<br>`tests/fake_ws.rs::junk_frames_keep_the_stream_alive_but_rest_polling_continues` | yok |
| `commands/web_hosts.py::_ws_envelope` | işlev:1478 | karşılandı | `ws.rs::decode_frame`<br>`push.rs::SkipLog::report` | `tests/parity.rs::ws_frames_match_python`<br>`tests/fake_ws.rs::junk_frames_keep_the_stream_alive_but_rest_polling_continues`<br>`push.rs::skipped_frames_are_logged_at_most_once_a_minute_per_kind` | yok |
| `commands/web_hosts.py::_parse_ws_status_frame` | işlev:1495 | karşılandı | `ws.rs::parse_status_frame` | `tests/parity.rs::ws_frames_match_python`<br>`tests/fake_ws.rs::junk_frames_keep_the_stream_alive_but_rest_polling_continues` | yok |
| `commands/web_hosts.py::_start_status_consumer` | işlev:1518 | karşılandı | `federation.rs::Federation::start_status_consumer` | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data`<br>`tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | yok |
| `commands/web_hosts.py::_start_status_consumer.on_item` | işlev:1529 | karşılandı | `federation.rs::Federation::start_status_consumer` | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data`<br>`tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | yok |
| `commands/web_hosts.py::_ensure_status_consumer` | işlev:1535 | karşılandı | `federation.rs::Federation::ensure_status_consumer` | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data`<br>`tests/fake_ws.rs::status_silence_watchdog_boundary`<br>`tests/fake_ws.rs::status_stream_is_rebuilt_when_address_or_token_changes_not_extra_urls` | yok |
| `commands/web_hosts.py::_reap_status_consumers` | işlev:1594 | karşılandı | `federation.rs::Federation::poll_once` | `tests/fake_ws.rs::dropped_streams_close_their_sockets_and_leak_no_fds` | yok |
| `commands/web_hosts.py::_TERM_RELAY_IDLE_TTL_SECONDS` | sabit:1607 | karşılandı | `consts.rs::TERM_RELAY_IDLE_TTL`<br>`consts.rs::TERM_RELAY_RESTART_MIN_INTERVAL`<br>`consts.rs::TERM_RELAY_SILENCE` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed`<br>`tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval`<br>`tests/fake_ws.rs::silent_relay_is_restarted_after_45s_without_serving_the_stale_frame` | yok |
| `commands/web_hosts.py::_TERM_RELAY_RESTART_MIN_INTERVAL_SECONDS` | sabit:1612 | karşılandı | `consts.rs::TERM_RELAY_IDLE_TTL`<br>`consts.rs::TERM_RELAY_RESTART_MIN_INTERVAL`<br>`consts.rs::TERM_RELAY_SILENCE` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed`<br>`tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval`<br>`tests/fake_ws.rs::silent_relay_is_restarted_after_45s_without_serving_the_stale_frame` | yok |
| `commands/web_hosts.py::_TERM_RELAY_SILENCE_SECONDS` | sabit:1615 | karşılandı | `consts.rs::TERM_RELAY_IDLE_TTL`<br>`consts.rs::TERM_RELAY_RESTART_MIN_INTERVAL`<br>`consts.rs::TERM_RELAY_SILENCE` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed`<br>`tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval`<br>`tests/fake_ws.rs::silent_relay_is_restarted_after_45s_without_serving_the_stale_frame` | yok |
| `commands/web_hosts.py::_TermRelay` | sınıf:1618 | karşılandı | `relay.rs::Relay`<br>`relay.rs::Federation::term_output` | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed` | yok |
| `commands/web_hosts.py::_TermRelay.__init__` | işlev:1619 | karşılandı | `relay.rs::Relay`<br>`relay.rs::Federation::term_output` | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed` | yok |
| `commands/web_hosts.py::_TermRelay.__init__.on_item` | işlev:1626 | karşılandı | `relay.rs::Relay`<br>`relay.rs::Federation::term_output` | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed` | yok |
| `commands/web_hosts.py::_TermRelay.is_alive` | işlev:1632 | karşılandı | `relay.rs::Federation::term_output` | `tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval`<br>`tests/fake_ws.rs::silent_relay_is_restarted_after_45s_without_serving_the_stale_frame` | yok |
| `commands/web_hosts.py::_TermRelay.read` | işlev:1639 | karşılandı | `relay.rs::Relay`<br>`relay.rs::Federation::term_output` | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed` | yok |
| `commands/web_hosts.py::_TermRelay.idle_seconds` | işlev:1644 | karşılandı | `relay.rs::Relay`<br>`relay.rs::Federation::term_output` | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed` | yok |
| `commands/web_hosts.py::_TermRelay.silent_seconds` | işlev:1647 | karşılandı | `relay.rs::Federation::term_output` | `tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval`<br>`tests/fake_ws.rs::silent_relay_is_restarted_after_45s_without_serving_the_stale_frame` | yok |
| `commands/web_hosts.py::_TermRelay.stop` | işlev:1651 | karşılandı | `relay.rs::Federation::term_output` | `tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval`<br>`tests/fake_ws.rs::silent_relay_is_restarted_after_45s_without_serving_the_stale_frame` | yok |
| `commands/web_hosts.py::_term_relay_lock` | sabit:1655 | karşılandı | `relay.rs::Relays` | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed` | yok |
| `commands/web_hosts.py::_term_relays` | sabit:1660 | karşılandı | `relay.rs::Relays` | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed` | yok |
| `commands/web_hosts.py::_parse_ws_term_frame` | işlev:1663 | karşılandı | `ws.rs::parse_term_frame` | `tests/parity.rs::ws_frames_match_python`<br>`tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set` | yok |
| `commands/web_hosts.py::term_output_relay` | işlev:1673 | karşılandı | `relay.rs::Federation::term_output` | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set`<br>`tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval`<br>`tests/fake_ws.rs::silent_relay_is_restarted_after_45s_without_serving_the_stale_frame`<br>`tests/fake_ws.rs::relay_is_rebuilt_when_the_host_record_changes`<br>`tests/fake_grpc.rs::grpc_term_relay_serves_frames_and_error_updates` | kayıt değişince yeniden kurulur (belgeli fark); `interval` biçimi belgeli fark |
| `commands/web_hosts.py::term_output_relay.fetch_fn` | işlev:1725 | karşılandı | `relay.rs::Federation::term_output` | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set`<br>`tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval`<br>`tests/fake_ws.rs::silent_relay_is_restarted_after_45s_without_serving_the_stale_frame`<br>`tests/fake_ws.rs::relay_is_rebuilt_when_the_host_record_changes`<br>`tests/fake_grpc.rs::grpc_term_relay_serves_frames_and_error_updates` | kayıt değişince yeniden kurulur (belgeli fark); `interval` biçimi belgeli fark |
| `commands/web_hosts.py::_reap_idle_term_relays` | işlev:1774 | karşılandı | `relay.rs::Relays::reap_idle` | `tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed` | yok |

### `py/claudeops/hosts.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `hosts.py::HOSTS_JSON` | sabit:32 | kapsam dışı | yok | yok | dosya yolu ve okuma/yazma çağıranın (`HostSource`). İz: W0-a durum (rs/state) |
| `hosts.py::LOCAL_HOST_NAME` | sabit:36 | karşılandı | `consts.rs::LOCAL_HOST_NAME` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`record.rs::validation_order` | yok |
| `hosts.py::_NAME_RE` | sabit:38 | karşılandı | `record.rs::valid_name` | `record.rs::validation_order`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | yok |
| `hosts.py::ERR` | sabit:40 | karşılandı | `record.rs::RecordError::message` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | bilinmeyen dil = tr (Python gibi) |
| `hosts.py::_err` | işlev:78 | karşılandı | `record.rs::RecordError::message` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | bilinmeyen dil = tr (Python gibi) |
| `hosts.py::_host_is_blocked` | işlev:82 | karşılandı | `guard.rs::host_is_blocked`<br>`guard.rs::host_is_blocked_via` | `guard.rs::legacy_ipv4_forms_are_blocked_at_registration`<br>`guard.rs::hung_or_failed_resolution_fails_open_and_loopback_is_blocked`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | yok |
| `hosts.py::LOOPBACK_REACH_DEFAULT` | sabit:116 | karşılandı | `guard.rs::LOOPBACK_REACH_DEFAULT` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`guard.rs::reach_ports_setting` | yok |
| `hosts.py::reach_loopback_ports` | işlev:119 | karşılandı | `guard.rs::reach_loopback_ports` | `guard.rs::reach_ports_setting`<br>`tests/parity.rs::address_filters_match_python` | ayar okuma çağıranın (`HostSource::reach_ports`) |
| `hosts.py::_is_reach_loopback` | işlev:136 | karşılandı | `guard.rs::is_reach_loopback` | `guard.rs::reach_ports_setting`<br>`tests/parity.rs::address_filters_match_python` | yok |
| `hosts.py::DNS_CHECK_TIMEOUT` | sabit:147 | karşılandı | `guard.rs::DNS_CHECK_TIMEOUT` | `tests/parity.rs::shared_constants_and_error_texts_equal_python` | yok |
| `hosts.py::_resolve_with_timeout` | işlev:150 | karşılandı | `guard.rs::host_is_blocked_via` | `guard.rs::hung_or_failed_resolution_fails_open_and_loopback_is_blocked` | iş parçacığı yerine tokio zaman aşımı |
| `hosts.py::_resolve_with_timeout.run` | işlev:154 | karşılandı | `guard.rs::host_is_blocked_via` | `guard.rs::hung_or_failed_resolution_fails_open_and_loopback_is_blocked` | iş parçacığı yerine tokio zaman aşımı |
| `hosts.py::ip_is_blocked` | işlev:166 | karşılandı | `guard.rs::ip_is_blocked` | `guard.rs::blocked_ranges`<br>`tests/parity.rs::address_filters_match_python` | yok |
| `hosts.py::hostname_is_dns_name` | işlev:177 | karşılandı | `endpoint.rs::host_is_dns_name` | `endpoint.rs::parses_common_forms`<br>`tests/parity.rs::address_filters_match_python` | kapsam (`%eth0`) farkı belgeli (parity bilinen fark) |
| `hosts.py::load_hosts` | işlev:189 | karşılandı | `record.rs::parse_document`<br>`record.rs::parse_value` | `record.rs::corrupt_and_irregular_documents`<br>`tests/fake_poller.rs::irregular_host_records_are_skipped_by_the_poller` | dosya/DB okuma W0-a; Rust adı metin olmayan kaydı da düşürür (Python `'name' in h`) |
| `hosts.py::_read_checked` | işlev:203 | karşılandı | `record.rs::parse_document`<br>`record.rs::Parsed.corrupt` | `record.rs::corrupt_and_irregular_documents`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | dosya/DB seçimi W0-a |
| `hosts.py::_db_mode` | işlev:230 | kapsam dışı | yok | yok | durum deposu kipi (`statedocs`). İz: W0-a durum (rs/state) |
| `hosts.py::_backup_corrupt` | işlev:235 | kapsam dışı | yok | yok | bozuk dosya yedeği; Rust yalnız işaret verir (`Parsed.corrupt`/`irregular`). İz: W0-a durum (rs/state) |
| `hosts.py::_has_irregular_entries` | işlev:254 | karşılandı | `record.rs::Parsed.irregular` | `record.rs::corrupt_and_irregular_documents` | yok |
| `hosts.py::_load_for_write` | işlev:267 | kapsam dışı | yok | yok | kilit altında okuma. İz: W0-a durum (rs/state) |
| `hosts.py::get_host` | işlev:275 | karşılandı | `record.rs::find` | `tests/fake_proxy.rs::unknown_host_sends_nothing_and_does_not_sign` | yok |
| `hosts.py::_write_hosts` | işlev:282 | kapsam dışı | yok | yok | atomik yazım ve kilit. İz: W0-a durum (rs/state) |
| `hosts.py::_write_txn` | işlev:293 | kapsam dışı | yok | yok | atomik yazım ve kilit. İz: W0-a durum (rs/state) |
| `hosts.py::_txn` | işlev:300 | kapsam dışı | yok | yok | atomik yazım ve kilit. İz: W0-a durum (rs/state) |
| `hosts.py::_txn.wrapper` | işlev:302 | kapsam dışı | yok | yok | atomik yazım ve kilit. İz: W0-a durum (rs/state) |
| `hosts.py::save_host` | işlev:308 | karşılandı | `record.rs::Draft::new`<br>`record.rs::Draft::apply` | `record.rs::validation_order`<br>`record.rs::upsert_keeps_token_and_unknown_fields_clears_optionals`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | yazım W0-a; denetim karakterli token Rust'ta red (daha sıkı); eksik `base_url`li kayıt yazımı parity bilinen fark |
| `hosts.py::save_host::re1` | regex:332 | karşılandı | `record.rs::Draft::new` | `tests/parity.rs::save_host_validation_and_upsert_match_python` | `[,\n]+` bölme |
| `hosts.py::promote_base_url` | işlev:376 | karşılandı | `record.rs::promote_base_url` | `record.rs::promote_and_remove`<br>`tests/fake_poller.rs::extra_urls_fallback_runs_on_threshold_and_every_twentieth_failure` | yok |
| `hosts.py::remove_host` | işlev:409 | karşılandı | `record.rs::remove` | `record.rs::promote_and_remove` | yok |
| `hosts.py::list_hosts_public` | işlev:420 | karşılandı | `record.rs::HostRecord::public` | `record.rs::unknown_fields_survive_and_token_never_public`<br>`tests/fake_poller.rs::public_rows_never_carry_the_token` | yok |

### `py/claudeops/commands/web_grpc.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `commands/web_grpc.py::_GRPC_MAX_WORKERS` | sabit:57 | kapsam dışı | yok | yok | sunucu tarafı (dict -> proto, yayın kadansı). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_STATUS_TICK_SECONDS` | sabit:59 | kapsam dışı | yok | yok | sunucu tarafı (dict -> proto, yayın kadansı). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_OPTIONAL_SESSION_FIELDS` | sabit:64 | karşılandı | `grpc.rs::session_row_to_value` | `tests/parity.rs::grpc_wire_decoding_matches_python_conversion`<br>`tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | yok |
| `commands/web_grpc.py::_PB_HAS_UCLI_FLAGS` | sabit:68 | karşılandı | `grpc.rs::SessionRow` | `tests/parity.rs::grpc_messages_match_proto_text_and_python_descriptors`<br>`tests/parity.rs::grpc_wire_decoding_matches_python_conversion` | Rust mesajı 19-21 alanlarını hep bilir (Python pb2 bayatsa yok sayar; pb2 güncel, parity denetler) |
| `commands/web_grpc.py::_OPTIONAL_TERM_FIELDS` | sabit:69 | karşılandı | `grpc.rs::term_to_value` | `tests/parity.rs::grpc_wire_decoding_matches_python_conversion`<br>`tests/fake_grpc.rs::grpc_term_relay_serves_frames_and_error_updates` | yok |
| `commands/web_grpc.py::_STATUS_DICT_KEYS` | sabit:76 | kapsam dışı | yok | yok | sunucu tarafı (dict -> proto, yayın kadansı). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_reduce_status` | işlev:79 | kapsam dışı | yok | yok | sunucu tarafı (dict -> proto, yayın kadansı). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_dict_to_session_row` | işlev:90 | kapsam dışı | yok | yok | sunucu tarafı (dict -> proto, yayın kadansı). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_session_row_to_dict` | işlev:116 | karşılandı | `grpc.rs::session_row_to_value` | `tests/parity.rs::grpc_wire_decoding_matches_python_conversion`<br>`tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | yok |
| `commands/web_grpc.py::_cli_options_to_proto` | işlev:134 | kapsam dışı | yok | yok | sunucu tarafı (dict -> proto, yayın kadansı). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_cli_options_from_proto` | işlev:146 | karşılandı | `grpc.rs::status_to_value` | `tests/parity.rs::grpc_wire_decoding_matches_python_conversion`<br>`tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | yok |
| `commands/web_grpc.py::_extras_to_proto` | işlev:158 | kapsam dışı | yok | yok | sunucu tarafı (dict -> proto, yayın kadansı). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_status_dict_to_proto` | işlev:165 | kapsam dışı | yok | yok | sunucu tarafı (dict -> proto, yayın kadansı). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_EXTRA_KEYS` | sabit:179 | karşılandı | `grpc.rs::EXTRA_KEYS` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/parity.rs::grpc_wire_decoding_matches_python_conversion` | yok |
| `commands/web_grpc.py::_extras_from_proto` | işlev:182 | karşılandı | `grpc.rs::status_to_value` | `tests/parity.rs::grpc_wire_decoding_matches_python_conversion`<br>`tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | yok |
| `commands/web_grpc.py::_status_proto_to_dict` | işlev:193 | karşılandı | `grpc.rs::status_to_value` | `tests/parity.rs::grpc_wire_decoding_matches_python_conversion`<br>`tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | yok |
| `commands/web_grpc.py::_term_dict_to_proto` | işlev:211 | kapsam dışı | yok | yok | sunucu tarafı (dict -> proto, yayın kadansı). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_term_proto_to_dict` | işlev:226 | karşılandı | `grpc.rs::term_to_value` | `tests/parity.rs::grpc_wire_decoding_matches_python_conversion`<br>`tests/fake_grpc.rs::grpc_term_relay_serves_frames_and_error_updates` | yok |
| `commands/web_grpc.py::_AuthInterceptor` | sınıf:238 | kapsam dışı | yok | yok | sunucu tarafı (kimlik denetimi, servis). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_AuthInterceptor.__init__` | işlev:239 | kapsam dışı | yok | yok | sunucu tarafı (kimlik denetimi, servis). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_AuthInterceptor._authorized` | işlev:242 | kapsam dışı | yok | yok | sunucu tarafı (kimlik denetimi, servis). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_AuthInterceptor.intercept_service` | işlev:251 | kapsam dışı | yok | yok | sunucu tarafı (kimlik denetimi, servis). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_deny_unary` | işlev:260 | kapsam dışı | yok | yok | sunucu tarafı (kimlik denetimi, servis). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_deny_stream` | işlev:264 | kapsam dışı | yok | yok | sunucu tarafı (kimlik denetimi, servis). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_HostBridgeServicer` | sınıf:268 | kapsam dışı | yok | yok | sunucu tarafı (kimlik denetimi, servis). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_HostBridgeServicer.__init__` | işlev:269 | kapsam dışı | yok | yok | sunucu tarafı (kimlik denetimi, servis). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_HostBridgeServicer.Ping` | işlev:273 | kapsam dışı | yok | yok | sunucu tarafı (kimlik denetimi, servis). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_HostBridgeServicer.StreamStatus` | işlev:276 | kapsam dışı | yok | yok | sunucu tarafı (kimlik denetimi, servis). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_HostBridgeServicer.StreamTermOutput` | işlev:295 | kapsam dışı | yok | yok | sunucu tarafı (kimlik denetimi, servis). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::start_grpc_server` | işlev:317 | kapsam dışı | yok | yok | sunucu tarafı (kimlik denetimi, servis). İz: T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci) |
| `commands/web_grpc.py::_KEEPALIVE_OPTIONS` | sabit:338 | karşılandı | `grpc.rs::GrpcClient::channel` | `tests/parity.rs::shared_constants_and_error_texts_equal_python` | 20 sn / 5 sn / boştayken açık |
| `commands/web_grpc.py::_channel_lock` | sabit:344 | karşılandı | `grpc.rs::GrpcClient.channels` | `tests/fake_grpc.rs::dropped_grpc_consumers_cancel_streams_and_removed_hosts_close_the_channel` | Rust kaydı silinen adresin kanalını bırakır (Python tutar) |
| `commands/web_grpc.py::_channels` | sabit:345 | karşılandı | `grpc.rs::GrpcClient.channels` | `tests/fake_grpc.rs::dropped_grpc_consumers_cancel_streams_and_removed_hosts_close_the_channel` | Rust kaydı silinen adresin kanalını bırakır (Python tutar) |
| `commands/web_grpc.py::_check_grpc_host` | işlev:348 | karşılandı | `net.rs::Connector::tcp` | `tests/fake_grpc.rs::grpc_dns_name_resolving_to_loopback_is_refused_before_connecting`<br>`tests/fake_grpc.rs::grpc_unresolvable_name_is_fail_closed` | denetim her bağlanışta (Python yalnız kanal kurulurken) |
| `commands/web_grpc.py::_channel_for` | işlev:365 | karşılandı | `grpc.rs::GrpcClient::channel` | `tests/fake_tls.rs::grpc_over_https_works_through_own_dial_and_origin`<br>`tests/fake_tls.rs::grpc_plain_http_sends_http_scheme` | yok |
| `commands/web_grpc.py::_stub_for` | işlev:381 | karşılandı | `grpc.rs::GrpcClient::ready` | `tests/fake_grpc.rs::grpc_probe_needs_transport_token_and_service_and_tier_moves_like_python` | yok |
| `commands/web_grpc.py::_auth_metadata` | işlev:385 | karşılandı | `grpc.rs::GrpcClient::request` | `tests/fake_grpc.rs::grpc_probe_needs_transport_token_and_service_and_tier_moves_like_python` | yok |
| `commands/web_grpc.py::probe` | işlev:389 | karşılandı | `grpc.rs::GrpcClient::probe` | `tests/fake_grpc.rs::grpc_probe_needs_transport_token_and_service_and_tier_moves_like_python` | yok |
| `commands/web_grpc.py::open_status_stream` | işlev:400 | karşılandı | `grpc.rs::GrpcClient::status_stream` | `tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | yok |
| `commands/web_grpc.py::open_term_stream` | işlev:412 | karşılandı | `grpc.rs::GrpcClient::term_stream` | `tests/fake_grpc.rs::grpc_term_relay_serves_frames_and_error_updates` | yok |
| `commands/web_grpc.py::stream_status` | işlev:419 | karşılandı | `grpc.rs::GrpcClient::status_stream` | `tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | yok |
| `commands/web_grpc.py::stream_term_output` | işlev:428 | karşılandı | `grpc.rs::GrpcClient::term_stream` | `tests/fake_grpc.rs::grpc_term_relay_serves_frames_and_error_updates` | yok |

### `py/claudeops/commands/web_steward.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `commands/web_steward.py::REMOTE_STALE_SECONDS` | sabit:251 | karşılandı | `health.rs::REMOTE_STALE_SECONDS` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_health.rs::freshness_and_files_gate` | yok |
| `commands/web_steward.py::REMOTE_READ_BUDGET_SECONDS` | sabit:252 | kapsam dışı | yok | yok | değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır. İz: T10 (değnekçi) |
| `commands/web_steward.py::MAX_REMOTE_CARDS_PER_TICK` | sabit:253 | kapsam dışı | yok | yok | değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır. İz: T10 (değnekçi) |
| `commands/web_steward.py::REMOTE_CARD_BUDGET_SECONDS` | sabit:254 | kapsam dışı | yok | yok | değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır. İz: T10 (değnekçi) |
| `commands/web_steward.py::REMOTE_DESTRUCTIVE_KINDS` | sabit:255 | kapsam dışı | yok | yok | değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır. İz: T10 (değnekçi) |
| `commands/web_steward.py::MAX_DESTRUCTIVE_PER_HOST` | sabit:256 | karşılandı | `health.rs::MAX_DESTRUCTIVE_PER_HOST` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_health.rs::remote_stop_sends_one_exact_stop_per_host_per_tick` | yok |
| `commands/web_steward.py::REMOTE_STOP_TIMEOUT_SECONDS` | sabit:257 | kapsam dışı | yok | yok | değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır. İz: T10 (değnekçi) |
| `commands/web_steward.py::REMOTE_INPUT_TIMEOUT_SECONDS` | sabit:258 | kapsam dışı | yok | yok | değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır. İz: T10 (değnekçi) |
| `commands/web_steward.py::REMOTE_HANDOVER_TIMEOUT_SECONDS` | sabit:259 | kapsam dışı | yok | yok | değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır. İz: T10 (değnekçi) |
| `commands/web_steward.py::REMOTE_START_TIMEOUT_SECONDS` | sabit:260 | kapsam dışı | yok | yok | değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır. İz: T10 (değnekçi) |
| `commands/web_steward.py::REMOTE_READY_UNKNOWN_POLLS` | sabit:261 | kapsam dışı | yok | yok | değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır. İz: T10 (değnekçi) |
| `commands/web_steward.py::REMOTE_READY_POLL_SECONDS` | sabit:262 | kapsam dışı | yok | yok | değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır. İz: T10 (değnekçi) |
| `commands/web_steward.py::REMOTE_BORN_TOLERANCE_SECONDS` | sabit:263 | kapsam dışı | yok | yok | değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır. İz: T10 (değnekçi) |
| `commands/web_steward.py::REMOTE_BACKOFF_TICKS` | sabit:264 | karşılandı | `health.rs::BACKOFF_TICKS`<br>`health.rs::BACKOFF_SECONDS` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_health.rs::breaker_opens_after_three_failing_ticks_and_reports_once` | yok |
| `commands/web_steward.py::REMOTE_BACKOFF_SECONDS` | sabit:265 | karşılandı | `health.rs::BACKOFF_TICKS`<br>`health.rs::BACKOFF_SECONDS` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_health.rs::breaker_opens_after_three_failing_ticks_and_reports_once` | yok |
| `commands/web_steward.py::REMOTE_DENIED_DEDUP_SECONDS` | sabit:266 | kapsam dışı | yok | yok | değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır. İz: T10 (değnekçi) |
| `commands/web_steward.py::_RemoteIO` | sınıf:274 | karşılandı | `status.rs::StatusBook::cached`<br>`status.rs::StatusBook::last_ok_at` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/parity.rs::steward_client_parts_match_python` | değnekçinin G/Ç bağdaştırıcısı; Rust karşılığı `Federation` alanları |
| `commands/web_steward.py::_RemoteIO.status` | işlev:279 | karşılandı | `status.rs::StatusBook::cached`<br>`status.rs::StatusBook::last_ok_at` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/parity.rs::steward_client_parts_match_python` | değnekçinin G/Ç bağdaştırıcısı; Rust karşılığı `Federation` alanları |
| `commands/web_steward.py::_RemoteIO.probe` | işlev:287 | karşılandı | `federation.rs::Federation::probe_host` | `tests/fake_poller.rs::probe_host_is_rate_limited_and_records_like_the_poller` | yok |
| `commands/web_steward.py::_RemoteIO.get` | işlev:291 | karşılandı | `proxy.rs::HostClient::proxy_get` | `tests/fake_health.rs::probe_facts_reads_caps_and_facts_in_one_request` | yok |
| `commands/web_steward.py::_RemoteIO.post` | işlev:294 | karşılandı | `proxy.rs::HostClient::proxy_action` | `tests/fake_health.rs::remote_post_breaker_and_error_marking` | yok |
| `commands/web_steward.py::_remote` | sabit:298 | karşılandı | `status.rs::StatusBook::cached`<br>`status.rs::StatusBook::last_ok_at` | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale`<br>`tests/parity.rs::steward_client_parts_match_python` | değnekçinin G/Ç bağdaştırıcısı; Rust karşılığı `Federation` alanları |
| `commands/web_steward.py::_host_fresh` | işlev:301 | karşılandı | `health.rs::host_fresh` | `tests/fake_health.rs::freshness_and_files_gate`<br>`tests/parity.rs::steward_client_parts_match_python` | `_fresh_hosts` döngüsü çağıranın |
| `commands/web_steward.py::_fresh_hosts` | işlev:310 | karşılandı | `health.rs::host_fresh` | `tests/fake_health.rs::freshness_and_files_gate`<br>`tests/parity.rs::steward_client_parts_match_python` | `_fresh_hosts` döngüsü çağıranın |
| `commands/web_steward.py::_HOST_HEALTH` | sabit:317 | karşılandı | `health.rs::Breaker` | `tests/fake_health.rs::breaker_opens_after_three_failing_ticks_and_reports_once` | yok |
| `commands/web_steward.py::_HEALTH_LOCK` | sabit:318 | karşılandı | `health.rs::Breaker` | `tests/fake_health.rs::breaker_opens_after_three_failing_ticks_and_reports_once` | yok |
| `commands/web_steward.py::_backing_off` | işlev:321 | karşılandı | `health.rs::Breaker::backing_off` | `tests/fake_health.rs::breaker_opens_after_three_failing_ticks_and_reports_once`<br>`tests/fake_health.rs::probe_success_clears_backoff_immediately` | yok |
| `commands/web_steward.py::_clear_backoff` | işlev:326 | karşılandı | `health.rs::Breaker::clear` | `tests/fake_health.rs::probe_success_clears_backoff_immediately` | yok |
| `commands/web_steward.py::_RemoteTick` | sınıf:339 | karşılandı | `health.rs::TickState`<br>`health.rs::TickState.failed`<br>`health.rs::TickState.succeeded`<br>`health.rs::TickState.destructive` | `tests/fake_health.rs::remote_post_breaker_and_error_marking`<br>`tests/fake_health.rs::remote_stop_sends_one_exact_stop_per_host_per_tick` | yok |
| `commands/web_steward.py::_RemoteTick.now` | sabit:346 | kapsam dışı | yok | yok | tick anlık görüntüsü ve toparlama döngüsü (yapı taşları: `StatusBook::cached`, `host_fresh`, `Breaker::backing_off/clear`, `Federation::probe_host`). İz: T10 (değnekçi) |
| `commands/web_steward.py::_RemoteTick.statuses` | sabit:347 | kapsam dışı | yok | yok | tick anlık görüntüsü ve toparlama döngüsü (yapı taşları: `StatusBook::cached`, `host_fresh`, `Breaker::backing_off/clear`, `Federation::probe_host`). İz: T10 (değnekçi) |
| `commands/web_steward.py::_RemoteTick.fresh` | sabit:348 | kapsam dışı | yok | yok | tick anlık görüntüsü ve toparlama döngüsü (yapı taşları: `StatusBook::cached`, `host_fresh`, `Breaker::backing_off/clear`, `Federation::probe_host`). İz: T10 (değnekçi) |
| `commands/web_steward.py::_RemoteTick.failed` | sabit:349 | karşılandı | `health.rs::TickState`<br>`health.rs::TickState.failed`<br>`health.rs::TickState.succeeded`<br>`health.rs::TickState.destructive` | `tests/fake_health.rs::remote_post_breaker_and_error_marking`<br>`tests/fake_health.rs::remote_stop_sends_one_exact_stop_per_host_per_tick` | yok |
| `commands/web_steward.py::_RemoteTick.succeeded` | sabit:350 | karşılandı | `health.rs::TickState`<br>`health.rs::TickState.failed`<br>`health.rs::TickState.succeeded`<br>`health.rs::TickState.destructive` | `tests/fake_health.rs::remote_post_breaker_and_error_marking`<br>`tests/fake_health.rs::remote_stop_sends_one_exact_stop_per_host_per_tick` | yok |
| `commands/web_steward.py::_RemoteTick.destructive` | sabit:351 | karşılandı | `health.rs::TickState`<br>`health.rs::TickState.failed`<br>`health.rs::TickState.succeeded`<br>`health.rs::TickState.destructive` | `tests/fake_health.rs::remote_post_breaker_and_error_marking`<br>`tests/fake_health.rs::remote_stop_sends_one_exact_stop_per_host_per_tick` | yok |
| `commands/web_steward.py::_RemoteTick.started` | sabit:352 | kapsam dışı | yok | yok | tick anlık görüntüsü ve toparlama döngüsü (yapı taşları: `StatusBook::cached`, `host_fresh`, `Breaker::backing_off/clear`, `Federation::probe_host`). İz: T10 (değnekçi) |
| `commands/web_steward.py::_RemoteTick.blocked` | işlev:354 | karşılandı | `health.rs::TickState::blocked` | `tests/fake_health.rs::remote_post_breaker_and_error_marking` | yok |
| `commands/web_steward.py::_RemoteTick.refresh` | işlev:358 | kapsam dışı | yok | yok | tick anlık görüntüsü ve toparlama döngüsü (yapı taşları: `StatusBook::cached`, `host_fresh`, `Breaker::backing_off/clear`, `Federation::probe_host`). İz: T10 (değnekçi) |
| `commands/web_steward.py::_RECOVERED_DOWN` | sabit:369 | kapsam dışı | yok | yok | tick anlık görüntüsü ve toparlama döngüsü (yapı taşları: `StatusBook::cached`, `host_fresh`, `Breaker::backing_off/clear`, `Federation::probe_host`). İz: T10 (değnekçi) |
| `commands/web_steward.py::REMOTE_PROBES_PER_TICK` | sabit:370 | karşılandı | `health.rs::PROBES_PER_TICK` | `tests/parity.rs::shared_constants_and_error_texts_equal_python` | yalnız sabit: tick başına yoklama döngüsü (`_probe_stale_hosts`) T10 |
| `commands/web_steward.py::_probe_stale_hosts` | işlev:373 | kapsam dışı | yok | yok | tick anlık görüntüsü ve toparlama döngüsü (yapı taşları: `StatusBook::cached`, `host_fresh`, `Breaker::backing_off/clear`, `Federation::probe_host`). İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_snapshot` | işlev:398 | kapsam dışı | yok | yok | tick anlık görüntüsü ve toparlama döngüsü (yapı taşları: `StatusBook::cached`, `host_fresh`, `Breaker::backing_off/clear`, `Federation::probe_host`). İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_tick_done` | işlev:421 | karşılandı | `health.rs::Breaker::settle` | `tests/fake_health.rs::breaker_opens_after_three_failing_ticks_and_reports_once`<br>`tests/fake_health.rs::breaker_ignores_idle_ticks_and_success_resets_streak` | olay yazımı (`remote_unreachable`) çağıranın: `Change` listesi döner |
| `commands/web_steward.py::_is_transport_error` | işlev:446 | karşılandı | `health.rs::is_transport_error` | `tests/fake_health.rs::transport_error_classification`<br>`tests/parity.rs::steward_client_parts_match_python` | yok |
| `commands/web_steward.py::_remote_post` | işlev:469 | karşılandı | `health.rs::remote_post` | `tests/fake_health.rs::remote_post_refuses_destructive_paths_and_host_field`<br>`tests/fake_health.rs::remote_post_breaker_and_error_marking` | `host`lu gövde Python'da ValueError, Rust hata değeri; yıkıcı yol Rust'ta yalnız `remote_stop` (daha sıkı) |
| `commands/web_steward.py::_name_host` | işlev:508 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_last_assistant` | işlev:517 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_last_assistant.work` | işlev:530 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_view` | işlev:561 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::REMOTE_CAPS_RECHECK_SECONDS` | sabit:584 | karşılandı | `health.rs::CAPS_RECHECK_SECONDS` | `tests/parity.rs::shared_constants_and_error_texts_equal_python`<br>`tests/fake_health.rs::probe_facts_404_caches_old_host_and_stops_asking` | yok |
| `commands/web_steward.py::_CAPS` | sabit:585 | karşılandı | `health.rs::CapabilityCache`<br>`health.rs::CapabilityCache::cached` | `tests/fake_health.rs::probe_facts_reads_caps_and_facts_in_one_request`<br>`tests/fake_health.rs::probe_facts_404_caches_old_host_and_stops_asking` | yok |
| `commands/web_steward.py::_CAPS_LOCK` | sabit:586 | karşılandı | `health.rs::CapabilityCache`<br>`health.rs::CapabilityCache::cached` | `tests/fake_health.rs::probe_facts_reads_caps_and_facts_in_one_request`<br>`tests/fake_health.rs::probe_facts_404_caches_old_host_and_stops_asking` | yok |
| `commands/web_steward.py::_caps_put` | işlev:589 | karşılandı | `health.rs::CapabilityCache`<br>`health.rs::CapabilityCache::cached` | `tests/fake_health.rs::probe_facts_reads_caps_and_facts_in_one_request`<br>`tests/fake_health.rs::probe_facts_404_caches_old_host_and_stops_asking` | yok |
| `commands/web_steward.py::_caps_cached` | işlev:597 | karşılandı | `health.rs::CapabilityCache`<br>`health.rs::CapabilityCache::cached` | `tests/fake_health.rs::probe_facts_reads_caps_and_facts_in_one_request`<br>`tests/fake_health.rs::probe_facts_404_caches_old_host_and_stops_asking` | yok |
| `commands/web_steward.py::_probe_facts` | işlev:608 | karşılandı | `health.rs::CapabilityCache::probe_facts` | `tests/fake_health.rs::probe_facts_reads_caps_and_facts_in_one_request`<br>`tests/fake_health.rs::probe_facts_404_caches_old_host_and_stops_asking`<br>`tests/fake_health.rs::probe_facts_transient_failure_is_not_cached` | yok |
| `commands/web_steward.py::host_capabilities` | işlev:636 | karşılandı | `health.rs::CapabilityCache::host_capabilities`<br>`health.rs::CAPS_PROBE_TIMEOUT` | `tests/fake_health.rs::host_capabilities_uses_cache_then_probes_once` | yok |
| `commands/web_steward.py::_apply_facts` | işlev:646 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_views` | işlev:662 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_views.probe` | işlev:701 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_DRYABLE_REMOTE` | sabit:836 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_log_remote_denied` | işlev:868 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_denied` | işlev:881 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_target.remote` | işlev:939 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::REMOTE_GIT_UNKNOWN` | sabit:1076 | kapsam dışı | yok | yok | değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_running_listing` | işlev:1079 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::remote_health` | işlev:1098 | karşılandı | `health.rs::health_view` | `health.rs::health_view_matches_python_remote_health`<br>`tests/parity.rs::steward_client_parts_match_python` | yok |
| `commands/web_steward.py::_remote_ref` | işlev:1118 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_cwd` | işlev:1152 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_file_head` | işlev:1157 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_last_exchange` | işlev:1172 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_read_context` | işlev:1185 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_files_gate` | işlev:1203 | karşılandı | `health.rs::files_gate` | `tests/fake_health.rs::freshness_and_files_gate` | yok |
| `commands/web_steward.py::_REMOTE_CARD_CHECKED` | sabit:1213 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_raw_card` | işlev:1216 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_transient_host_error` | işlev:1439 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_rows` | işlev:1771 | karşılandı | `health.rs::host_fresh`<br>`health.rs::Breaker::backing_off`<br>`health.rs::running_row` | `tests/parity.rs::steward_client_parts_match_python` | tick anlık görüntüsünden okuma (`rt.statuses`) T10 |
| `commands/web_steward.py::_remote_running_row` | işlev:1785 | karşılandı | `health.rs::running_row` | `health.rs::running_row_is_exact_truthy_and_ambiguous_is_unknown`<br>`tests/parity.rs::steward_client_parts_match_python` | yok |
| `commands/web_steward.py::_remote_named_rows` | işlev:1799 | karşılandı | `health.rs::named_running_rows` | `health.rs::running_row_is_exact_truthy_and_ambiguous_is_unknown`<br>`tests/fake_health.rs::ambiguous_or_inexact_target_sends_nothing` | yok |
| `commands/web_steward.py::_remote_key` | işlev:1804 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_project_rows` | işlev:1813 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_session` | işlev:1823 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_sleep` | sabit:1879 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_wait_ready` | işlev:1882 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_ensure_running_remote` | işlev:1904 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_oversized_resume` | işlev:1957 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::remote_resume_warning` | işlev:1973 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_START_BACKOFF_STEPS` | sabit:2119 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_start_backoff_remaining` | işlev:2122 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_start_backoff_note` | işlev:2131 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_born` | işlev:2279 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_name_host_in` | işlev:2725 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_refresh_remote_cards` | işlev:2789 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_nudge` | işlev:3304 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_handover` | işlev:3340 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_stop` | işlev:3357 | karşılandı | `health.rs::exact_target`<br>`health.rs::remote_stop` | `tests/fake_health.rs::ambiguous_or_inexact_target_sends_nothing`<br>`tests/fake_health.rs::remote_stop_sends_one_exact_stop_per_host_per_tick` | projeye göre satır seçimi, `not_own`, `manual`, olay yazımı T10; kodlar Python ile aynı (`no_exact_row`, `ambiguous_sessions`, `caps_unknown`, `remote_too_old`, `destructive_budget`, `host_down`) |
| `commands/web_steward.py::_remote_wait_closed` | işlev:3408 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_stop_and_wait` | işlev:3422 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_respawn` | işlev:3449 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_respawn.failed` | işlev:3460 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_advance_candidates.remote_todo_of` | işlev:4356 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_read_full` | işlev:5798 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_append_idea` | işlev:5810 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_in_remote_roster` | işlev:6001 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_register_remote` | işlev:6136 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_REMOTE_CREATABLE` | sabit:6685 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_before` | işlev:6688 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::_remote_edit_doc` | işlev:6702 | kapsam dışı | yok | yok | uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir. İz: T10 (değnekçi) |
| `commands/web_steward.py::RemoteReviewDriver` | sınıf:8566 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver.POLL_STALE_NONE` | sabit:8573 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver.__init__` | işlev:8575 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver._owner` | işlev:8580 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver._rows` | işlev:8584 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver._project_cwd_remote` | işlev:8587 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver._ambiguous` | işlev:8596 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver.ready` | işlev:8602 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver.cwd` | işlev:8614 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver._wait_closed` | işlev:8621 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver.start` | işlev:8624 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver.send` | işlev:8663 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver.poll` | işlev:8674 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver.read_rel` | işlev:8689 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver.export_file` | işlev:8700 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver.sweep` | işlev:8745 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |
| `commands/web_steward.py::RemoteReviewDriver.stop` | işlev:8757 | kapsam dışı | yok | yok | uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı). İz: T8 (reviewer) |

### `py/claudeops/authz.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `authz.py::outbound_service_headers` | işlev:244 | karşılandı | `proxy.rs::HostClient::sign_service` | `tests/fake_ws.rs::ws_handshake_carries_a_fresh_panel_signature_per_connection` | yok |
| `authz.py::has_outbound_signer` | işlev:260 | karşılandı | `proxy.rs::HostClient.signer` | `tests/fake_proxy.rs::user_caller_is_signed_over_path_and_body_without_query` | kayıt noktası yerine alan; enterprise doldurur (T9) |
| `authz.py::bind_principal` | işlev:439 | karşılandı | `sign.rs::Caller` | `tests/fake_proxy.rs::unbound_caller_is_never_signed`<br>`tests/fake_proxy.rs::dedup_key_includes_identity` | iş parçacığına bağlı kimlik yerine açık parametre (görevler arası sızma yok) |
| `authz.py::current_principal` | işlev:445 | karşılandı | `sign.rs::Caller` | `tests/fake_proxy.rs::unbound_caller_is_never_signed`<br>`tests/fake_proxy.rs::dedup_key_includes_identity` | iş parçacığına bağlı kimlik yerine açık parametre (görevler arası sızma yok) |
| `authz.py::OutboundRefused` | sınıf:455 | karşılandı | `sign.rs::OutboundRefused` | `tests/fake_proxy.rs::signer_refusal_panic_and_bad_headers_are_502_and_nothing_is_sent` | yok |
| `authz.py::OutboundRefused.__init__` | işlev:458 | karşılandı | `sign.rs::OutboundRefused` | `tests/fake_proxy.rs::signer_refusal_panic_and_bad_headers_are_502_and_nothing_is_sent` | yok |
| `authz.py::_OUTBOUND_SIGNER` | sabit:465 | karşılandı | `proxy.rs::HostClient.signer` | `tests/fake_proxy.rs::user_caller_is_signed_over_path_and_body_without_query` | kayıt noktası yerine alan; enterprise doldurur (T9) |
| `authz.py::set_outbound_signer` | işlev:468 | karşılandı | `proxy.rs::HostClient.signer` | `tests/fake_proxy.rs::user_caller_is_signed_over_path_and_body_without_query` | kayıt noktası yerine alan; enterprise doldurur (T9) |
| `authz.py::outbound_headers` | işlev:474 | karşılandı | `sign.rs::headers_for`<br>`sign.rs::OutboundSigner` | `tests/fake_proxy.rs::signer_refusal_panic_and_bad_headers_are_502_and_nothing_is_sent`<br>`tests/fake_proxy.rs::user_caller_is_signed_over_path_and_body_without_query` | signer paniği / yasak başlık = RED (Python imzasız gönderir; belgeli fark) |

## Python test durumları

### `py/tests/test_bad_encoding_state_files.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_bad_encoding_state_files.py::BadBytes.test_instances` | 11 | kapsam dışı | yok | instances.json okuma. İz: W0-a durum (rs/state) |
| `test_bad_encoding_state_files.py::BadBytes.test_hosts` | 21 | karşılandı | `record.rs::corrupt_and_irregular_documents` | UTF-8 olmayan belge = bozuk |
| `test_bad_encoding_state_files.py::SaveHostKeepsUnknownFields.test_unknown_field_survives_upsert_and_dns_outside_lock` | 35 | karşılandı | `record.rs::upsert_keeps_token_and_unknown_fields_clears_optionals`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | DNS denetimi `Draft::new`de (kilit dışı), kilit W0-a |

### `py/tests/test_cache_info.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_cache_info.py::CacheInfoTests.test_a_recent_request_gives_its_age_and_the_one_hour_ttl` | 68 | kapsam dışı | yok | `/api/status` önbellek bilgisi alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_a_cli_without_a_cache_lifetime_has_no_info_and_is_never_probed` | 73 | kapsam dışı | yok | `/api/status` önbellek bilgisi alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_no_matching_transcript_is_unknown_not_cold` | 78 | kapsam dışı | yok | `/api/status` önbellek bilgisi alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_an_expired_cache_still_reports_so_the_ui_can_show_cold` | 81 | kapsam dışı | yok | `/api/status` önbellek bilgisi alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_the_probe_is_cached_but_the_age_keeps_advancing` | 84 | kapsam dışı | yok | `/api/status` önbellek bilgisi alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_the_probe_is_repeated_after_the_ttl_and_sees_a_new_request` | 91 | kapsam dışı | yok | `/api/status` önbellek bilgisi alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_a_failing_provider_is_unknown_never_an_error_and_is_not_hammered` | 99 | kapsam dışı | yok | `/api/status` önbellek bilgisi alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_a_clock_skew_never_gives_a_negative_age` | 105 | kapsam dışı | yok | `/api/status` önbellek bilgisi alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_a_restarted_session_with_a_new_pid_is_probed_afresh` | 108 | kapsam dışı | yok | `/api/status` önbellek bilgisi alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_retired_sessions_do_not_pile_up_in_the_cache` | 114 | kapsam dışı | yok | `/api/status` önbellek bilgisi alanı. İz: T1 (durum) |
| `test_cache_info.py::StatusPayloadCacheTests.test_both_running_row_builders_carry_the_cache_info` | 146 | kapsam dışı | yok | `/api/status` önbellek bilgisi alanı. İz: T1 (durum) |
| `test_cache_info.py::StatusPayloadCacheTests.test_a_stopped_row_has_none` | 151 | kapsam dışı | yok | `/api/status` önbellek bilgisi alanı. İz: T1 (durum) |

### `py/tests/test_chat_remote_panel_transport.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_chat_remote_panel_transport.py::PanelTransportTest.test_idle_strips_ansi_prompt` | 13 | kapsam dışı | yok | panel taşıma yardımcısı (ANSI süzme). İz: T2 (terminal) |
| `test_chat_remote_panel_transport.py::PanelTransportTest.test_download_rejects_non_200` | 19 | karşılandı | `tests/fake_proxy.rs::download_passes_raw_body_and_only_two_headers` | uzak durum aynen döner; 200 dışı reddi çağıranın |
| `test_chat_remote_panel_transport.py::PanelTransportTest.test_download_ok` | 27 | karşılandı | `tests/fake_proxy.rs::download_passes_raw_body_and_only_two_headers` | uzak durum aynen döner; 200 dışı reddi çağıranın |

### `py/tests/test_graphical_session.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_graphical_session.py::Status.test_own_session_resolved_by_user_not_first_row` | 41 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Status.test_other_user_active` | 47 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Status.test_no_own_session` | 53 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Status.test_never_raises` | 58 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Selection.test_graphical_seat_session_chosen_over_ssh_and_tty` | 65 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Selection.test_only_ssh_session_means_no_own_graphical` | 72 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Activate.test_already_active_no_activate_call` | 85 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Activate.test_other_active_needs_confirm_and_names_user` | 90 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Activate.test_confirm_activates_own_session_only` | 96 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Activate.test_no_unlock_ever` | 102 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Activate.test_failure_reported` | 107 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Activate.test_non_numeric_session_id_refused` | 112 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Setting.test_default_off` | 121 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Setting.test_on_words_only` | 127 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |
| `test_graphical_session.py::Routing.test_paths_registered` | 134 | kapsam dışı | yok | uzak grafik oturum ucu. İz: T7 (periyodik) |

### `py/tests/test_host_liveness.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_host_liveness.py::SilentConsumerTest.test_healthy_consumer_keeps_rest_off` | 36 | karşılandı | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data`<br>`tests/fake_ws.rs::junk_frames_keep_the_stream_alive_but_rest_polling_continues` | yok |
| `test_host_liveness.py::SilentConsumerTest.test_silent_but_alive_consumer_replaced_and_rest_used_this_tick` | 43 | karşılandı | `tests/fake_ws.rs::status_silence_watchdog_boundary` | Rust'ta tüketici kurulumu eşzamanlı başarısız olamaz (görev); eski tüketici değişimde düşer |
| `test_host_liveness.py::SilentConsumerTest.test_replacement_failure_still_stops_old_and_falls_to_rest` | 53 | karşılandı | `tests/fake_ws.rs::status_silence_watchdog_boundary` | Rust'ta tüketici kurulumu eşzamanlı başarısız olamaz (görev); eski tüketici değişimde düşer |
| `test_host_liveness.py::SilentConsumerTest.test_fed01_dead_consumer_restarted_and_rest_used_this_tick` | 64 | karşılandı | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data`<br>`tests/fake_ws.rs::junk_frames_keep_the_stream_alive_but_rest_polling_continues` | yok |
| `test_host_liveness.py::SilentConsumerTest.test_fed01_first_start_uses_rest` | 75 | karşılandı | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data`<br>`tests/fake_ws.rs::junk_frames_keep_the_stream_alive_but_rest_polling_continues` | yok |
| `test_host_liveness.py::SilentConsumerTest.test_fed01_poll_once_records_failure_when_push_dies` | 81 | karşılandı | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data`<br>`tests/fake_ws.rs::junk_frames_keep_the_stream_alive_but_rest_polling_continues` | yok |
| `test_host_liveness.py::SilentConsumerTest.test_push_consumer_sets_has_data` | 97 | karşılandı | `tests/fake_ws.rs::poller_skips_rest_only_while_a_live_push_stream_has_delivered_data`<br>`tests/fake_ws.rs::junk_frames_keep_the_stream_alive_but_rest_polling_continues` | yok |
| `test_host_liveness.py::SilentConsumerTest.test_push_consumer_tracks_last_message` | 105 | karşılandı | `tests/fake_ws.rs::status_silence_watchdog_boundary` | Rust'ta tüketici kurulumu eşzamanlı başarısız olamaz (görev); eski tüketici değişimde düşer |
| `test_host_liveness.py::PollerWatchdogTest.test_not_started_is_noop` | 123 | karşılandı | `tests/fake_poller.rs::dropping_running_stops_poller_and_prober` | global durum yok: görevler yalnız `start` ile |
| `test_host_liveness.py::PollerWatchdogTest.test_dead_thread_restarted` | 127 | karşılandı | `tests/fake_restart.rs::panicking_turn_is_counted_and_the_poller_keeps_running` | yok |
| `test_host_liveness.py::PollerWatchdogTest.test_stalled_thread_restarted_and_healthy_left_alone` | 136 | karşılandı | `tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers` | yok |
| `test_host_liveness.py::PollerWatchdogTest.test_old_generation_loop_exits` | 148 | karşılandı | `tests/fake_restart.rs::stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers` | yok |
| `test_host_liveness.py::ProbeTest.test_probe_records_success_and_is_rate_limited` | 161 | karşılandı | `tests/fake_poller.rs::probe_host_is_rate_limited_and_records_like_the_poller` | yok |
| `test_host_liveness.py::ProbeTest.test_probe_failure_and_unknown_host` | 170 | karşılandı | `tests/fake_poller.rs::probe_host_is_rate_limited_and_records_like_the_poller` | yok |
| `test_host_liveness.py::ProbeTest.test_probe_never_raises` | 177 | karşılandı | `tests/fake_poller.rs::probe_host_is_rate_limited_and_records_like_the_poller` | yok |
| `test_host_liveness.py::StewardSideTest.test_probe_stale_hosts_recovers_and_refreshes` | 183 | kapsam dışı | yok | tick toparlama döngüsü ve durum satırı. İz: T10 (değnekçi) |
| `test_host_liveness.py::StewardSideTest.test_probe_cap_per_tick_and_errors_swallowed` | 199 | kapsam dışı | yok | tick toparlama döngüsü ve durum satırı. İz: T10 (değnekçi) |
| `test_host_liveness.py::StewardSideTest.test_remote_health_gives_reason_and_last_try_when_down` | 210 | karşılandı | `health.rs::health_view_matches_python_remote_health`<br>`tests/parity.rs::steward_client_parts_match_python` | yok |
| `test_host_liveness.py::StewardSideTest.test_status_line_shows_reason` | 219 | kapsam dışı | yok | tick toparlama döngüsü ve durum satırı. İz: T10 (değnekçi) |
| `test_host_liveness.py::BackoffRecoveryTest.test_clear_backoff_resets_breaker` | 240 | karşılandı | `tests/fake_health.rs::probe_success_clears_backoff_immediately` | yok |
| `test_host_liveness.py::BackoffRecoveryTest.test_probe_success_clears_backoff_and_marks_recovered` | 249 | karşılandı | `tests/fake_health.rs::probe_success_clears_backoff_immediately` | yok |
| `test_host_liveness.py::BackoffRecoveryTest.test_probe_failure_keeps_backoff` | 265 | karşılandı | `tests/fake_health.rs::probe_success_clears_backoff_immediately` | yok |
| `test_host_liveness.py::BackoffRecoveryTest.test_human_not_blocked_by_backoff_when_host_fresh_but_engine_is` | 286 | kapsam dışı | yok | insan/motor kapısı ayrımı. İz: T10 (değnekçi) |
| `test_host_liveness.py::BackoffRecoveryTest.test_human_still_denied_when_host_stale` | 293 | kapsam dışı | yok | insan/motor kapısı ayrımı. İz: T10 (değnekçi) |
| `test_host_liveness.py::BackoffRecoveryTest.test_transport_error_is_logged_with_reason` | 300 | karşılandı | `tests/fake_health.rs::remote_post_breaker_and_error_marking` | yok |
| `test_host_liveness.py::OutageScenarioTest.test_outage_backoff_recovery` | 363 | karşılandı | `tests/fake_health.rs::breaker_opens_after_three_failing_ticks_and_reports_once`<br>`tests/fake_health.rs::breaker_ignores_idle_ticks_and_success_resets_streak` | yok |
| `test_host_liveness.py::OutageScenarioTest.test_human_passes_while_backing_off_if_host_fresh` | 379 | kapsam dışı | yok | insan/motor kapısı ayrımı. İz: T10 (değnekçi) |
| `test_host_liveness.py::OutageScenarioTest.test_sub_threshold_failures_do_not_back_off` | 388 | karşılandı | `tests/fake_health.rs::breaker_opens_after_three_failing_ticks_and_reports_once`<br>`tests/fake_health.rs::breaker_ignores_idle_ticks_and_success_resets_streak` | yok |
| `test_host_liveness.py::EnsureConsumerStopOutsideLock.test_silent_old_stopped_without_lock_when_start_fails` | 400 | karşılandı | `tests/fake_ws.rs::status_silence_watchdog_boundary` | durdurma `Drop` (iptal), kilitte G/Ç yok |

### `py/tests/test_host_pick_fastest.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_host_pick_fastest.py::AllowedTest.test_http_to_https_base_only_for_private_lan_literal` | 23 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::RecordTest.test_avg_of_last_n_and_fail_counters` | 34 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::ScoreTest.test_components_and_penalty` | 67 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::ScoreTest.test_record_fills_window_capped` | 78 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::ChooseTest.test_picks_much_better_score` | 94 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::ChooseTest.test_keeps_base_when_gain_small` | 97 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::ChooseTest.test_cold_candidate_never_chosen_even_if_fast` | 101 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::ChooseTest.test_flaky_base_loses_to_clean_candidate_with_similar_latency` | 105 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::ChooseTest.test_candidate_too_flaky_ignored` | 109 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::ChooseTest.test_base_down_picks_best_warm_candidate` | 112 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::ChooseTest.test_hysteresis_no_flapping` | 116 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::ChooseTest.test_stale_store_means_no_decision` | 123 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::ChooseTest.test_public_http_candidate_never_chosen` | 127 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::ChooseTest.test_unknown_host_or_empty_store` | 131 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::RunProbeTest.test_probes_candidates_several_attempts_writes_store_and_drops_gone_urls` | 136 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::RunProbeTest.test_same_host_addresses_probed_sequentially` | 156 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::RunProbeTest.test_public_http_candidate_not_probed` | 174 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::RunProbeTest.test_probe_exception_counts_as_failed_attempt` | 180 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::PollerAndJobTest.test_poller_promotes_from_store_without_network` | 189 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |
| `test_host_pick_fastest.py::PollerAndJobTest.test_periodic_job_registered_on_and_plans_without_probing` | 198 | kapsam dışı | yok | adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular (`probe_choice_only_promotes_registered_allowed_candidates`). İz: T7 (periyodik) |

### `py/tests/test_hosts.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_hosts.py::ConcurrentWriteTest.test_parallel_saves_all_survive` | 20 | kapsam dışı | yok | hosts.json kilitli yazım. İz: W0-a durum (rs/state) |
| `test_hosts.py::ConcurrentWriteTest.test_flock_failure_falls_back_to_thread_lock` | 37 | kapsam dışı | yok | hosts.json kilitli yazım. İz: W0-a durum (rs/state) |
| `test_hosts.py::ReachLoopbackTest.test_reach_port_loopback_ok_in_extra_urls` | 58 | karşılandı | `record.rs::validation_order`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | yok |
| `test_hosts.py::ReachLoopbackTest.test_everything_else_still_blocked` | 63 | karşılandı | `record.rs::validation_order`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | yok |
| `test_hosts.py::ReachLoopbackTest.test_https_base_may_fall_back_to_reach_loopback` | 72 | karşılandı | `guard.rs::https_never_downgrades_to_public_http`<br>`tests/parity.rs::address_filters_match_python` | yok |
| `test_hosts.py::ReachLoopbackTest.test_helper` | 78 | karşılandı | `guard.rs::reach_ports_setting`<br>`tests/parity.rs::address_filters_match_python` | yok |
| `test_hosts.py::ReachLoopbackTest.test_setting_overrides_ports` | 84 | karşılandı | `guard.rs::reach_ports_setting`<br>`tests/parity.rs::address_filters_match_python` | yok |
| `test_hosts.py::DbModeIrregularTest.test_irregular_detected_from_db_not_stale_file` | 96 | kapsam dışı | yok | DB kipi okuma. İz: W0-a durum (rs/state) |

### `py/tests/test_hosts_corrupt.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_hosts_corrupt.py::CorruptHostsTest.test_save_refused_on_corrupt_and_backup_kept` | 26 | karşılandı | `record.rs::upsert_keeps_token_and_unknown_fields_clears_optionals`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | yedek dosyası W0-a |
| `test_hosts_corrupt.py::CorruptHostsTest.test_remove_and_promote_refused_on_corrupt` | 38 | karşılandı | `record.rs::promote_and_remove` | yok |
| `test_hosts_corrupt.py::CorruptHostsTest.test_non_list_json_is_corrupt` | 44 | karşılandı | `record.rs::corrupt_and_irregular_documents`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | yok |
| `test_hosts_corrupt.py::CorruptHostsTest.test_missing_or_empty_file_still_writable` | 49 | karşılandı | `record.rs::corrupt_and_irregular_documents`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | yok |
| `test_hosts_corrupt.py::CorruptHostsTest.test_irregular_entries_backed_up_before_being_dropped` | 56 | kapsam dışı | yok | yedekleme; Rust işareti (`Parsed.irregular`) testli. İz: W0-a durum (rs/state) |
| `test_hosts_corrupt.py::CorruptHostsTest.test_healthy_roundtrip_unchanged` | 64 | karşılandı | `record.rs::unknown_fields_survive_and_token_never_public` | yok |

### `py/tests/test_hosts_dns_timeout.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_hosts_dns_timeout.py::DnsTimeout.test_hung_resolution_does_not_block_and_fails_open` | 12 | karşılandı | `guard.rs::hung_or_failed_resolution_fails_open_and_loopback_is_blocked` | yok |
| `test_hosts_dns_timeout.py::DnsTimeout.test_loopback_still_blocked_and_gaierror_fails_open` | 19 | karşılandı | `guard.rs::hung_or_failed_resolution_fails_open_and_loopback_is_blocked` | yok |

### `py/tests/test_hosts_unspecified.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_hosts_unspecified.py::UnspecifiedBlockedTest.test_unspecified_literals_are_blocked` | 11 | karşılandı | `guard.rs::blocked_ranges`<br>`tests/parity.rs::address_filters_match_python`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | yok |
| `test_hosts_unspecified.py::UnspecifiedBlockedTest.test_loopback_still_blocked` | 15 | karşılandı | `guard.rs::blocked_ranges`<br>`tests/parity.rs::address_filters_match_python`<br>`tests/parity.rs::save_host_validation_and_upsert_match_python` | yok |

### `py/tests/test_http_json_post_no_retry.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_http_json_post_no_retry.py::PostRetryTest.test_post_not_retried_after_send` | 46 | karşılandı | `tests/fake_http.rs::stale_pooled_post_that_reached_server_is_not_retried` | yok |
| `test_http_json_post_no_retry.py::PostRetryTest.test_post_retried_when_send_failed` | 53 | karşılandı | `tests/fake_http.rs::server_closed_idle_connection_does_not_fail_post` | `!sent` yolunun kendi başına deterministik sınaması yok (docs/rs-hosts.md iş 1) |
| `test_http_json_post_no_retry.py::PostRetryTest.test_get_still_retried_after_send` | 59 | karşılandı | `tests/fake_http.rs::stale_pooled_get_is_retried_once_with_fresh_signature` | yok |

### `py/tests/test_labels.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_labels.py::TestLabels.test_concurrent_updates_lose_nothing` | 34 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestLabels.test_system_defs_present_and_undeletable` | 45 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestLabels.test_name_validation` | 52 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestLabels.test_add_remove_autodefine_and_find` | 57 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestLabels.test_delete_def_strips_assignments` | 65 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestLabels.test_key_for_and_attach` | 71 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestLabels.test_api_action` | 80 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestLabels.test_corrupt_file_is_empty` | 89 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestLabels.test_auto_remove_only_listed` | 95 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestCli.test_flow` | 109 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestStewardAutoRemove.test_phase_back_to_planned_removes` | 131 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestStewardAutoRemove.test_new_project_in_planned_does_not_touch_labels` | 141 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestStewardAutoRemove.test_directive_success_removes_but_not_job_delivery` | 146 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestApi.test_local_only_route` | 183 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestApi.test_post_flow_ignores_host_field` | 186 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestApi.test_status_payload_has_labels` | 195 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |
| `test_labels.py::TestSearchParserTs.test_label_terms` | 206 | kapsam dışı | yok | etiket deposu ve ucu (yerel). İz: T1 (durum) |

### `py/tests/test_mirror_marker.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_mirror_marker.py::NoteMirrorTests.test_records_the_pid_under_the_spec` | 47 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::NoteMirrorTests.test_same_spec_accumulates_pids` | 52 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::NoteMirrorTests.test_anything_else_leaves_the_dict_alone` | 58 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::FindSessionsMirrorsOutTests.test_viewers_are_collected_in_the_same_pass` | 91 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::FindSessionsMirrorsOutTests.test_viewers_are_not_sessions_and_fleet_result_is_unchanged` | 97 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::FindSessionsMirrorsOutTests.test_default_does_not_collect_anything` | 104 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::FindSessionsMirrorsOutTests.test_a_real_viewer_process_is_seen_by_the_real_scan` | 110 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_open_and_closed_are_stamped_per_remote_row` | 148 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_same_name_on_two_hosts_is_told_apart` | 155 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_match_is_exact_not_a_prefix` | 162 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_cached_rows_are_copied_not_mutated` | 169 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_stale_value_from_upstream_is_overwritten` | 177 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_no_marker_at_all_when_the_state_is_unknown` | 182 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_empty_set_means_known_and_closed` | 187 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_local_closed_and_retired_rows_are_not_stamped` | 192 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_a_dict_works_as_the_container_like_find_sessions_hands_it_over` | 201 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_unpolled_host_adds_no_rows_and_no_crash` | 206 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::StatusPayloadWiringTests.test_remote_rows_carry_the_marker_from_the_fleet_scan` | 243 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::StatusPayloadWiringTests.test_exactly_one_scan_carries_the_collector` | 249 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |
| `test_mirror_marker.py::StatusPayloadWiringTests.test_a_closed_window_flips_the_marker_on_the_next_tick` | 259 | kapsam dışı | yok | masaüstü yansı işaretleri. İz: T2 (terminal) |

### `py/tests/test_mirror_window.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_mirror_window.py::SpecFromCmdlineTests.test_host_and_name` | 33 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::SpecFromCmdlineTests.test_bare_name_is_local` | 36 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::SpecFromCmdlineTests.test_flags_before_or_after_the_target` | 39 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::SpecFromCmdlineTests.test_value_of_a_flag_is_not_mistaken_for_the_target` | 44 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::SpecFromCmdlineTests.test_once_is_not_a_window` | 47 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::SpecFromCmdlineTests.test_other_commands_do_not_match` | 50 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::SpecFromCmdlineTests.test_watch_without_a_target` | 56 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::SpecFromCmdlineTests.test_empty_parts` | 60 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::RunningMirrorsTests.test_collects_pids_per_spec` | 78 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::RunningMirrorsTests.test_other_users_processes_are_ignored` | 83 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::RunningMirrorsTests.test_unreadable_processes_are_skipped` | 86 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::RunningMirrorsTests.test_default_uid_is_the_current_user` | 89 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::RunningMirrorsTests.test_a_process_vanishing_mid_scan_is_skipped` | 94 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::FocusWindowTests.test_uses_exact_title_matching_and_the_given_display` | 104 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::FocusWindowTests.test_failures_are_false_not_exceptions` | 117 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowSpawnTests.test_gnome_terminal_argv` | 138 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowSpawnTests.test_the_command_runs_cops_watch_against_this_panels_port` | 145 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowSpawnTests.test_a_failing_viewer_keeps_the_window_open_and_a_clean_exit_closes_it` | 151 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowSpawnTests.test_arguments_are_shell_quoted` | 158 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowSpawnTests.test_environment` | 162 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowSpawnTests.test_popen_failure_is_false` | 170 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_success_spawns_once_with_the_panels_port` | 211 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_local_sessions_are_rejected` | 215 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_bad_characters_never_reach_the_command_line` | 222 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_unknown_host` | 229 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_session_must_be_in_the_hosts_last_known_state` | 234 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_a_session_without_tmux_has_no_terminal_to_mirror` | 245 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_no_x11_display` | 250 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_an_open_mirror_is_focused_not_duplicated` | 257 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_force_opens_a_second_one` | 263 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_another_sessions_mirror_does_not_count` | 269 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_launch_failure` | 274 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_messages_follow_the_language` | 280 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::MirrorRouteHttpTests.test_route_is_declared_local_only` | 323 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::MirrorRouteHttpTests.test_post_with_a_remote_host_field_is_handled_locally` | 326 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::MirrorRouteHttpTests.test_force_flag_is_passed_through` | 331 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::MirrorRouteHttpTests.test_name_is_required` | 335 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::MirrorRouteHttpTests.test_token_is_required` | 340 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::LayoutRecognisesMirrorWindowsTests.test_a_mirror_window_is_tiled_once_its_spec_is_known` | 355 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::LayoutRecognisesMirrorWindowsTests.test_without_the_spec_it_is_skipped_as_before` | 360 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |
| `test_mirror_window.py::LayoutRecognisesMirrorWindowsTests.test_title_from_the_viewer_survives_list_windows_cleaning` | 365 | kapsam dışı | yok | masaüstü yansı penceresi. İz: T2 (terminal) |

### `py/tests/test_orphan_brief.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_orphan_brief.py::OrphanBriefTest.test_brief` | 6 | karşılandı | `tests/parity.rs::status_reduction_matches_python` | yok |
| `test_orphan_brief.py::FwdBriefTest.test_brief` | 18 | karşılandı | `tests/parity.rs::status_reduction_matches_python` | yok |
| `test_orphan_brief.py::WsFrameTest.test_ws_frame_keeps_host_badges` | 27 | karşılandı | `tests/parity.rs::ws_frames_match_python`<br>`tests/parity.rs::status_reduction_matches_python` | yok |
| `test_orphan_brief.py::GrpcExtrasTest.test_roundtrip_extras` | 38 | karşılandı | `tests/parity.rs::grpc_wire_decoding_matches_python_conversion`<br>`tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | dict -> proto yarısı sunucu tarafı (kapsam dışı) |
| `test_orphan_brief.py::GrpcExtrasTest.test_no_extras_is_clean` | 49 | karşılandı | `tests/parity.rs::grpc_wire_decoding_matches_python_conversion`<br>`tests/fake_grpc.rs::grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest` | dict -> proto yarısı sunucu tarafı (kapsam dışı) |
| `test_orphan_brief.py::BuildRunningTest.test_build_running` | 56 | karşılandı | `tests/parity.rs::status_reduction_matches_python` | yok |

### `py/tests/test_outbound_signer.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_outbound_signer.py::OutboundSignerTest.test_no_signer_no_header` | 55 | karşılandı | `tests/fake_proxy.rs::unbound_caller_is_never_signed`<br>`tests/fake_http.rs::pool_reuses_one_keepalive_connection` | signer yoksa `headers_for` boş; sahte testlerin çoğu signer'sız istemciyle |
| `test_outbound_signer.py::OutboundSignerTest.test_signer_gets_host_path_and_header_sent_each_call` | 60 | karşılandı | `tests/fake_proxy.rs::user_caller_is_signed_over_path_and_body_without_query`<br>`tests/fake_http.rs::stale_pooled_get_is_retried_once_with_fresh_signature` | yok |
| `test_outbound_signer.py::OutboundSignerTest.test_no_principal_no_signing` | 73 | karşılandı | `tests/fake_proxy.rs::unbound_caller_is_never_signed` | yok |
| `test_outbound_signer.py::OutboundSignerTest.test_refused_returns_error_without_request` | 78 | karşılandı | `tests/fake_proxy.rs::signer_refusal_panic_and_bad_headers_are_502_and_nothing_is_sent` | signer çökmesi Python'da imzasız gönderim, Rust'ta RED (belgeli fark, kapalı yön) |
| `test_outbound_signer.py::OutboundSignerTest.test_signer_crash_falls_back_unsigned` | 88 | karşılandı | `tests/fake_proxy.rs::signer_refusal_panic_and_bad_headers_are_502_and_nothing_is_sent` | signer çökmesi Python'da imzasız gönderim, Rust'ta RED (belgeli fark, kapalı yön) |
| `test_outbound_signer.py::StatusExtraTest.test_extras` | 105 | kapsam dışı | yok | `/api/status` ek alanları (sunucu tarafı). İz: T1 (durum) |
| `test_outbound_signer.py::PeekBodyTest.test_peek_then_read_same_bytes` | 137 | kapsam dışı | yok | gelen isteğin gövdesini imza doğrulaması için okuma (sunucu tarafı). İz: T9 (enterprise) |
| `test_outbound_signer.py::PeekBodyTest.test_cache_not_leaked_to_next_request` | 143 | kapsam dışı | yok | gelen isteğin gövdesini imza doğrulaması için okuma (sunucu tarafı). İz: T9 (enterprise) |
| `test_outbound_signer.py::PeekBodyTest.test_too_large_returns_none` | 151 | kapsam dışı | yok | gelen isteğin gövdesini imza doğrulaması için okuma (sunucu tarafı). İz: T9 (enterprise) |
| `test_outbound_signer.py::WsSignedKwTest.test_ws_kw` | 161 | karşılandı | `tests/fake_ws.rs::ws_handshake_carries_a_fresh_panel_signature_per_connection` | yok |
| `test_outbound_signer.py::Refused502Test.test_proxy_get_and_action_502` | 190 | karşılandı | `tests/fake_proxy.rs::signer_refusal_panic_and_bad_headers_are_502_and_nothing_is_sent` | signer çökmesi Python'da imzasız gönderim, Rust'ta RED (belgeli fark, kapalı yön) |
| `test_outbound_signer.py::Refused502Test.test_unreachable_stays_200` | 204 | karşılandı | `tests/fake_proxy.rs::error_texts_carry_no_url_port_or_token` | yok |

### `py/tests/test_post_routes_vs_host_routed.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_post_routes_vs_host_routed.py::PostRoutesVsHostRouted.test_allowlist_parsed` | 48 | kapsam dışı | yok | yerel POST route tablosu (`web.py` do_POST) ile host-routed kümenin eşitliği; host-routed küme Rust'ta `parity::host_routed_route_sets_equal_python_source` ile Python'a bağlı. İz: W0-c kapı (rs/gate) / copsd uç bağlama (cops) |
| `test_post_routes_vs_host_routed.py::PostRoutesVsHostRouted.test_every_host_routed_path_is_in_post_allowlist` | 53 | kapsam dışı | yok | yerel POST route tablosu (`web.py` do_POST) ile host-routed kümenin eşitliği; host-routed küme Rust'ta `parity::host_routed_route_sets_equal_python_source` ile Python'a bağlı. İz: W0-c kapı (rs/gate) / copsd uç bağlama (cops) |
| `test_post_routes_vs_host_routed.py::PostRoutesVsHostRouted.test_unrouted_post_paths_are_explicit_exceptions` | 57 | kapsam dışı | yok | yerel POST route tablosu (`web.py` do_POST) ile host-routed kümenin eşitliği; host-routed küme Rust'ta `parity::host_routed_route_sets_equal_python_source` ile Python'a bağlı. İz: W0-c kapı (rs/gate) / copsd uç bağlama (cops) |
| `test_post_routes_vs_host_routed.py::PostRoutesVsHostRouted.test_known_local_only_has_no_stale_entries` | 63 | kapsam dışı | yok | yerel POST route tablosu (`web.py` do_POST) ile host-routed kümenin eşitliği; host-routed küme Rust'ta `parity::host_routed_route_sets_equal_python_source` ile Python'a bağlı. İz: W0-c kapı (rs/gate) / copsd uç bağlama (cops) |

### `py/tests/test_remote_capabilities_shape.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_remote_capabilities_shape.py::CapabilitiesShapeTest.test_text_is_not_split_into_characters` | 22 | karşılandı | `tests/fake_health.rs::probe_facts_reads_caps_and_facts_in_one_request` | yok |
| `test_remote_capabilities_shape.py::CapabilitiesShapeTest.test_other_non_list_values_are_empty_and_do_not_raise` | 25 | karşılandı | `tests/fake_health.rs::probe_facts_reads_caps_and_facts_in_one_request` | yok |
| `test_remote_capabilities_shape.py::CapabilitiesShapeTest.test_non_text_items_are_dropped` | 29 | karşılandı | `tests/fake_health.rs::probe_facts_reads_caps_and_facts_in_one_request` | yok |

### `py/tests/test_remote_duplicate_name.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_remote_duplicate_name.py::TestResolvers.test_remote_session_refuses_two_running_rows_of_the_same_name` | 31 | karşılandı | `tests/fake_health.rs::ambiguous_or_inexact_target_sends_nothing` | yok |
| `test_remote_duplicate_name.py::TestResolvers.test_running_row_is_unknown_not_absent` | 37 | karşılandı | `health.rs::running_row_is_exact_truthy_and_ambiguous_is_unknown`<br>`tests/parity.rs::steward_client_parts_match_python` | yok |
| `test_remote_duplicate_name.py::TestResolvers.test_one_running_and_one_closed_row_is_not_ambiguous` | 40 | karşılandı | `health.rs::running_row_is_exact_truthy_and_ambiguous_is_unknown`<br>`tests/parity.rs::steward_client_parts_match_python` | yok |
| `test_remote_duplicate_name.py::TestResolvers.test_registered_project_with_duplicate_name_is_refused_too` | 46 | kapsam dışı | yok | projeye göre satır seçimi. İz: T10 (değnekçi) |
| `test_remote_duplicate_name.py::TestCallers.test_ensure_running_neither_adopts_nor_starts` | 55 | kapsam dışı | yok | uzak oturum yönetimi çağıranları. İz: T10 (değnekçi) |
| `test_remote_duplicate_name.py::TestCallers.test_nudge_handover_and_stop_send_nothing` | 59 | kapsam dışı | yok | uzak oturum yönetimi çağıranları. İz: T10 (değnekçi) |
| `test_remote_duplicate_name.py::TestCallers.test_waits_do_not_report_ready_or_closed` | 68 | kapsam dışı | yok | uzak oturum yönetimi çağıranları. İz: T10 (değnekçi) |
| `test_remote_duplicate_name.py::TestCallers.test_panel_stop_with_handover_fails_closed_without_plain_stop_fallback` | 72 | kapsam dışı | yok | panel devirli durdurma. İz: T4 (yaşam döngüsü) |
| `test_remote_duplicate_name.py::TestReviewDriver.test_start_stop_send_and_sweep_post_nothing` | 90 | kapsam dışı | yok | uzak review sürücüsü. İz: T8 (reviewer) |
| `test_remote_duplicate_name.py::TestReviewDriver.test_poll_reports_unknown_not_ended` | 101 | kapsam dışı | yok | uzak review sürücüsü. İz: T8 (reviewer) |
| `test_remote_duplicate_name.py::TestReviewDriver.test_single_review_session_still_gets_stop_and_send` | 104 | kapsam dışı | yok | uzak review sürücüsü. İz: T8 (reviewer) |
| `test_remote_duplicate_name.py::TestTwinAppearsDuringHandover.test_no_second_handover_request` | 134 | kapsam dışı | yok | panel devirli durdurma (`web.py`). İz: T4 (yaşam döngüsü) |
| `test_remote_duplicate_name.py::TestTwinAppearsDuringHandover.test_no_stop_after_reply` | 137 | kapsam dışı | yok | panel devirli durdurma (`web.py`). İz: T4 (yaşam döngüsü) |

### `py/tests/test_remote_resume_context.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_remote_resume_context.py::RemoteOversizedResumeTests.test_big_context_returns_tokens` | 14 | kapsam dışı | yok | uzak devam bağlamı uyarısı. İz: T10 (değnekçi) |
| `test_remote_resume_context.py::RemoteOversizedResumeTests.test_small_or_missing_is_zero` | 18 | kapsam dışı | yok | uzak devam bağlamı uyarısı. İz: T10 (değnekçi) |
| `test_remote_resume_context.py::RemoteOversizedResumeTests.test_old_host_without_capability_is_zero` | 24 | kapsam dışı | yok | uzak devam bağlamı uyarısı. İz: T10 (değnekçi) |
| `test_remote_resume_context.py::RemoteOversizedResumeTests.test_threshold_off` | 28 | kapsam dışı | yok | uzak devam bağlamı uyarısı. İz: T10 (değnekçi) |
| `test_remote_resume_context.py::RemoteOversizedResumeTests.test_host_facts_for_stopped_name_carry_resume_tokens` | 32 | kapsam dışı | yok | uzak devam bağlamı uyarısı. İz: T10 (değnekçi) |

### `py/tests/test_review_20261125_upload_newchat.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_review_20261125_upload_newchat.py::BoundedReader.test_full_body` | 16 | karşılandı | `tests/fake_proxy.rs::upload_body_ending_early_or_overflowing_is_an_error`<br>`tests/fake_proxy.rs::slow_but_progressing_upload_is_not_cut` | yok |
| `test_review_20261125_upload_newchat.py::BoundedReader.test_early_eof_raises` | 20 | karşılandı | `tests/fake_proxy.rs::upload_body_ending_early_or_overflowing_is_an_error`<br>`tests/fake_proxy.rs::slow_but_progressing_upload_is_not_cut` | yok |
| `test_review_20261125_upload_newchat.py::NewChatNames.test_concurrent_calls_get_distinct_names` | 28 | kapsam dışı | yok | yeni sohbet adı yarışı. İz: T4 (yaşam döngüsü) |

### `py/tests/test_review_findings_flow.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_review_findings_flow.py::TestAutoFindings.test_done_review_records_findings_as_new` | 89 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestExportStaleCheck.test_stale_reason_pure` | 116 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestExportStaleCheck.test_stale_finding_not_exported_and_rejected` | 126 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestExportStaleCheck.test_changed_after_review_is_marked` | 138 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestScanVerdicts.test_only_real_line_start` | 150 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestVerify.test_verify_sends_via_owner_human_directive_and_marks` | 164 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestVerify.test_closed_project_is_explicit_error_and_nothing_sent` | 179 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestVerify.test_busy_or_subagent_defers` | 188 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestVerify.test_remote_routed_to_its_host_unknown_rejected` | 196 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestVerdicts.test_verdict_from_owner_session_applied_once` | 216 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestVerdicts.test_code_block_example_not_counted` | 233 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestVerdicts.test_other_session_source_rejected` | 239 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestVerdicts.test_baseline_text_not_reprocessed` | 248 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestVerdicts.test_ambiguous_sessions_not_read` | 260 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestExportUnverifiedToRtodo.test_split_by_kind_and_note_and_state` | 274 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestExportUnverifiedToRtodo.test_unknown_kind_rejected` | 294 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestDecideExport.test_approve_rules` | 309 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestDecideExport.test_export_only_approved_once` | 327 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestDecideExport.test_export_tbd_and_remote_rejected` | 354 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestRemoteExport.test_remote_export_once_and_sensitive_skipped` | 397 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestRemoteExport.test_remote_stale_finding_rejected_not_written` | 415 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestRemoteExport.test_remote_unreadable_source_does_not_block_export` | 435 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestRemoteExport.test_remote_missing_file_stops_and_reports` | 445 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestRemoteExport.test_remote_sensitive_finding_skipped` | 454 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestRemoteExport.test_no_driver_is_error_not_crash` | 465 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestRemoteExportRealDriver.test_real_driver_writes_once_and_marks_exported` | 504 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestRemoteExportRealDriver.test_real_driver_conflict_between_reads_leaves_finding_approved` | 516 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestGates.test_brain_actor_rejected_on_all_new_posts` | 534 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestGates.test_non_reviewer_rejected` | 545 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestGates.test_reviewer_target_refusal_unchanged` | 550 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestCli.test_cli_maps` | 575 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestEvrenRemoteExportE2E.test_report_to_remote_todo_once` | 626 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestEvrenRemoteExportE2E.test_busy_session_written_but_not_notified` | 645 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestEvrenRemoteExportE2E.test_write_failure_keeps_approved_for_retry` | 652 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestEvrenRemoteExportE2E.test_conflict_during_export_keeps_approved` | 665 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestEvrenRemoteExportE2E.test_transient_conflict_retries_once_and_succeeds` | 682 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoApprove.test_held_sensitive_finding_notifies_owner_once` | 714 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoApprove.test_level_1_approves_only_verified_p3_without_secrets` | 733 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoApprove.test_level_2_adds_p2_but_never_p1_unclear_or_secret` | 740 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoApprove.test_level_3_approves_all_but_secret_and_unclear` | 745 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoApprove.test_off_and_tick_wiring` | 751 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoExport.test_off_by_default_writes_nothing` | 790 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoExport.test_on_exports_to_todo_only_never_tbd` | 796 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoExport.test_unclear_goes_to_tbd_after_todo` | 809 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoExport.test_already_in_file_is_not_written_twice` | 823 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoExport.test_sensitive_and_remote_are_skipped` | 837 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoExport.test_body_secret_is_exported_without_body` | 846 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoExport.test_secret_skip_is_loud_once_and_listed_for_manual_export` | 857 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoExport.test_word_only_finding_is_auto_written_redacted` | 871 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoExport.test_one_project_per_tick_and_error_continues` | 880 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoExport.test_exception_is_logged_and_next_project_goes` | 887 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoExport.test_review_tick_runs_it_when_on` | 903 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoVerify.test_sends_once_per_tick_and_marks` | 917 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoVerify.test_stale_waiting_does_not_block` | 928 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestAutoVerify.test_off_and_busy_send_nothing` | 939 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestBeforeTbd.test_writes_only_unclear_and_refuted_once_and_hides_secrets` | 967 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestBeforeTbd.test_off_when_dir_empty_or_missing` | 980 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::TestBeforeTbd.test_tick_wiring` | 986 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |
| `test_review_findings_flow.py::StoreReportsTest.test_copies_report_and_usage_once_and_skips_private_traces` | 996 | kapsam dışı | yok | review bulgu akışı. İz: T8 (reviewer) |

### `py/tests/test_review_fixes_batch.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_review_fixes_batch.py::TestDeleteSymlink.test_symlink_to_dir_removes_link_not_target` | 30 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestDeleteSymlink.test_symlink_to_outside_removes_only_link` | 41 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestDeleteSymlink.test_regular_dir_still_removed` | 50 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestRename.test_dangling_symlink_at_new_name_not_overwritten` | 58 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestWriteTextMode.test_mode_preserved` | 68 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestWriteTextMode.test_private_mode_preserved` | 76 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestReadOnlyMetaRoots.test_listing_and_reading_still_work` | 98 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestReadOnlyMetaRoots.test_destructive_ops_refused` | 102 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestListDirSymlinkMarker.test_symlink_flagged` | 112 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestAtomicJson.test_bare_filename_works` | 121 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestAtomicJson.test_tmp_removed_on_failure_and_fsync_called` | 131 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestSettingsLock.test_concurrent_patches_not_lost` | 143 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestSnapshot.test_closing_survives_malformed_last_entry` | 171 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestSnapshot.test_duplicate_pair_is_a_change` | 178 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |
| `test_review_fixes_batch.py::TestHostsLock.test_symlinked_lock_file_not_followed` | 185 | kapsam dışı | yok | review düzeltmeleri. İz: T8 (reviewer) |

### `py/tests/test_review_remote.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_review_remote.py::PureTest.test_parse_answer` | 77 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::PureTest.test_parse_answer_long_free_text_starting_with_no_is_not_off` | 84 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::PureTest.test_parse_answer_keyword_beats_path` | 91 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::PureTest.test_parse_answer_word_boundary` | 101 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::PureTest.test_prepare_copy_updates_and_refuses_dirty` | 108 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::PureTest.test_prepare_copy_stops_on_divergence` | 126 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::RemoteFlowTest.test_set_where_from_panel` | 168 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::RemoteFlowTest.test_unknown_choice_blocks_review_and_asks_the_owner_once` | 184 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::RemoteFlowTest.test_local_answer_enables_the_copy_and_runs_there` | 193 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::RemoteFlowTest.test_dirty_copy_blocks_manual_run_and_tick_logs_once` | 208 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::RemoteFlowTest.test_off_answer_stops_asking_and_remote_is_recorded_only` | 223 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::RemoteFlowTest.test_remote_mode_tick_starts_job_with_empty_cwd_when_ready` | 234 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::RemoteFlowTest.test_remote_mode_tick_waits_when_gates_say_no` | 242 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::RemoteFlowTest.test_remote_mode_accepts_only_evren_targets` | 250 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::RemoteFlowTest.test_remote_run_job_end_to_end_writes_report_and_stops_session` | 259 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::RemoteFlowTest.test_recover_on_start_skips_live_job_of_this_process` | 286 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::RemoteFlowTest.test_sweep_closes_orphan_only_when_no_live_job_and_is_throttled` | 297 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::RemoteFlowTest.test_unrecognized_answer_reasks_only_after_retry_window` | 310 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::RemoteFlowTest.test_invalid_values_are_ignored_by_upsert` | 319 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::FirstPollRaceTest.test_early_running_false_is_not_a_dead_run` | 339 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |
| `test_review_remote.py::FirstPollRaceTest.test_running_false_after_grace_still_ends_run` | 349 | kapsam dışı | yok | uzak review. İz: T8 (reviewer) |

### `py/tests/test_review_remote_export.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_review_remote_export.py::T.test_write_verify_notify` | 41 | kapsam dışı | yok | uzak review dışa aktarımı. İz: T8 (reviewer) |
| `test_review_remote_export.py::T.test_busy_session_not_notified` | 48 | kapsam dışı | yok | uzak review dışa aktarımı. İz: T8 (reviewer) |
| `test_review_remote_export.py::T.test_missing_file_stops_without_write` | 54 | kapsam dışı | yok | uzak review dışa aktarımı. İz: T8 (reviewer) |
| `test_review_remote_export.py::T.test_write_failure_reported` | 60 | kapsam dışı | yok | uzak review dışa aktarımı. İz: T8 (reviewer) |
| `test_review_remote_export.py::T.test_nothing_new_no_write` | 66 | kapsam dışı | yok | uzak review dışa aktarımı. İz: T8 (reviewer) |
| `test_review_remote_export.py::T.test_write_unverified_when_readback_differs` | 71 | kapsam dışı | yok | uzak review dışa aktarımı. İz: T8 (reviewer) |
| `test_review_remote_export.py::T.test_files_gate_denied_no_io` | 87 | kapsam dışı | yok | uzak review dışa aktarımı. İz: T8 (reviewer) |
| `test_review_remote_export.py::T.test_empty_remote_cwd_stops` | 95 | kapsam dışı | yok | uzak review dışa aktarımı. İz: T8 (reviewer) |
| `test_review_remote_export.py::T.test_tobedecided_target_is_exported` | 103 | kapsam dışı | yok | uzak review dışa aktarımı. İz: T8 (reviewer) |
| `test_review_remote_export.py::T.test_bad_filename` | 111 | kapsam dışı | yok | uzak review dışa aktarımı. İz: T8 (reviewer) |

### `py/tests/test_review_remote_run.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_review_remote_run.py::ProcTest.test_done_needs_two_stable_idle_polls_and_stops_session` | 53 | kapsam dışı | yok | uzak review koşusu. İz: T8 (reviewer) |
| `test_review_remote_run.py::ProcTest.test_stale_answer_from_previous_conversation_is_not_taken` | 59 | kapsam dışı | yok | uzak review koşusu. İz: T8 (reviewer) |
| `test_review_remote_run.py::ProcTest.test_prompt_echoed_but_assistant_still_previous_turn_is_not_taken` | 65 | kapsam dışı | yok | uzak review koşusu. İz: T8 (reviewer) |
| `test_review_remote_run.py::ProcTest.test_busy_never_finishes_then_timeout_then_abort_returns_partial` | 72 | kapsam dışı | yok | uzak review koşusu. İz: T8 (reviewer) |
| `test_review_remote_run.py::ProcTest.test_session_died_without_report_is_failure` | 83 | kapsam dışı | yok | uzak review koşusu. İz: T8 (reviewer) |
| `test_review_remote_run.py::ProcTest.test_start_failure_and_cancel` | 89 | kapsam dışı | yok | uzak review koşusu. İz: T8 (reviewer) |
| `test_review_remote_run.py::ProcTest.test_report_without_format_is_not_done` | 98 | kapsam dışı | yok | uzak review koşusu. İz: T8 (reviewer) |
| `test_review_remote_run.py::DriverTest.test_gate_denial_blocks_start_and_reports_why` | 135 | kapsam dışı | yok | uzak review koşusu. İz: T8 (reviewer) |
| `test_review_remote_run.py::DriverTest.test_start_registers_distinct_session_then_starts_read_only_fresh_ucli` | 142 | kapsam dışı | yok | uzak review koşusu. İz: T8 (reviewer) |
| `test_review_remote_run.py::DriverTest.test_leftover_review_session_is_stopped_first_and_registration_skipped` | 153 | kapsam dışı | yok | uzak review koşusu. İz: T8 (reviewer) |
| `test_review_remote_run.py::DriverTest.test_sweep_stops_only_a_running_orphan` | 167 | kapsam dışı | yok | uzak review koşusu. İz: T8 (reviewer) |
| `test_review_remote_run.py::DriverTest.test_send_goes_exact_to_review_session_only` | 180 | kapsam dışı | yok | uzak review koşusu. İz: T8 (reviewer) |
| `test_review_remote_run.py::DriverTest.test_ready_fails_when_remote_folder_unknown` | 187 | kapsam dışı | yok | uzak review koşusu. İz: T8 (reviewer) |

### `py/tests/test_review_uzops_p3b.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_review_uzops_p3b.py::P3b.test_diag_log_rotates_and_tail_reads_window` | 10 | kapsam dışı | yok | tanı günlüğü döndürme ve rustup ortamı. İz: T7 (periyodik) |
| `test_review_uzops_p3b.py::P3b.test_stop_before_connect_closes_call` | 22 | karşılandı | `tests/fake_ws.rs::dropped_streams_close_their_sockets_and_leak_no_fds` | Rust'ta bağlantı öncesi düşürme = açılış görevi iptal |
| `test_review_uzops_p3b.py::P3b.test_status_consumer_replaced_when_endpoint_changes` | 40 | karşılandı | `tests/fake_ws.rs::status_stream_is_rebuilt_when_address_or_token_changes_not_extra_urls` | yok |
| `test_review_uzops_p3b.py::SharedRustup.test_rustup_home_points_to_real_home_when_toolchains_exist` | 66 | kapsam dışı | yok | tanı günlüğü döndürme ve rustup ortamı. İz: T7 (periyodik) |

### `py/tests/test_session_lock.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_session_lock.py::SetLock.test_lock_and_unlock_target_only_own_graphical_session` | 49 | kapsam dışı | yok | oturum kilidi ucu (yerel). İz: T7 (periyodik) |
| `test_session_lock.py::SetLock.test_confirm_required_and_nothing_runs_without_it` | 59 | kapsam dışı | yok | oturum kilidi ucu (yerel). İz: T7 (periyodik) |
| `test_session_lock.py::SetLock.test_already_in_state_is_noop` | 66 | kapsam dışı | yok | oturum kilidi ucu (yerel). İz: T7 (periyodik) |
| `test_session_lock.py::SetLock.test_unlock_setting_off_disables_unlock_only` | 75 | kapsam dışı | yok | oturum kilidi ucu (yerel). İz: T7 (periyodik) |
| `test_session_lock.py::SetLock.test_unlock_setting_default_on_and_tolerant` | 85 | kapsam dışı | yok | oturum kilidi ucu (yerel). İz: T7 (periyodik) |
| `test_session_lock.py::SetLock.test_failures` | 93 | kapsam dışı | yok | oturum kilidi ucu (yerel). İz: T7 (periyodik) |
| `test_session_lock.py::Endpoint.test_human_confirm_logged` | 125 | kapsam dışı | yok | oturum kilidi ucu (yerel). İz: T7 (periyodik) |
| `test_session_lock.py::Endpoint.test_remote_host_refused` | 132 | kapsam dışı | yok | oturum kilidi ucu (yerel). İz: T7 (periyodik) |
| `test_session_lock.py::Endpoint.test_non_human_actor_and_agent_token_refused` | 137 | kapsam dışı | yok | oturum kilidi ucu (yerel). İz: T7 (periyodik) |
| `test_session_lock.py::Endpoint.test_unlock_disabled_is_403` | 148 | kapsam dışı | yok | oturum kilidi ucu (yerel). İz: T7 (periyodik) |
| `test_session_lock.py::Endpoint.test_routes_are_post_allowlisted_and_local_only` | 152 | kapsam dışı | yok | oturum kilidi ucu (yerel). İz: T7 (periyodik) |

### `py/tests/test_snapshot_mirrors.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_snapshot_mirrors.py::NormalizeMirrorsTests.test_sorted_deduplicated_and_junk_dropped` | 52 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::NormalizeMirrorsTests.test_none_and_non_list` | 58 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SaveSnapshotTests.test_mirrors_are_stored_normalized_and_separate_from_sessions` | 65 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SaveSnapshotTests.test_default_is_an_empty_list` | 71 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SaveSnapshotTests.test_get_snapshot_returns_the_mirrors` | 74 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SaveSnapshotTests.test_manual_always_appends` | 78 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::ClosingSnapshotComparisonTests.test_identical_sessions_and_mirrors_are_not_duplicated` | 85 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::ClosingSnapshotComparisonTests.test_only_a_window_change_still_records_a_closing_snapshot` | 91 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::ClosingSnapshotComparisonTests.test_changed_sessions_with_the_same_mirrors_record` | 101 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::ClosingSnapshotComparisonTests.test_an_old_entry_without_the_field_equals_no_mirrors` | 106 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::ClosingSnapshotComparisonTests.test_an_old_entry_vs_open_mirrors_records_a_new_one` | 112 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::ListSnapshotsTests.test_mirror_count_in_the_metadata_and_old_entries_count_zero` | 120 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::ListSnapshotsTests.test_legacy_single_record_migration_is_unaffected` | 128 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::LiveMirrorEntriesTests.test_remote_hosts_only_sorted` | 140 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::LiveMirrorEntriesTests.test_nothing_open` | 147 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::LiveMirrorEntriesTests.test_a_failing_scan_returns_an_empty_list_instead_of_breaking_the_closing_snapshot` | 150 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SaveWiringTests.test_manual_save_records_the_open_windows` | 159 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SaveWiringTests.test_closing_snapshot_records_the_open_windows_and_skips_an_unchanged_state` | 166 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SaveWiringTests.test_closing_snapshot_failure_is_logged_not_raised` | 178 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SaveWiringTests.test_status_info_carries_the_mirror_count` | 188 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SaveWiringTests.test_status_info_of_an_old_entry` | 193 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::MirrorWindowRestoreModeTests.test_opens_even_though_the_remote_session_is_not_running_yet` | 221 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::MirrorWindowRestoreModeTests.test_the_normal_route_still_requires_a_running_session` | 225 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::MirrorWindowRestoreModeTests.test_the_other_checks_still_apply` | 230 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::MirrorWindowRestoreModeTests.test_an_open_window_is_not_duplicated_and_not_raised` | 238 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_windows_open_after_every_session_started` | 270 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_mirrors_are_opened_in_restore_mode_with_this_panels_port` | 277 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_default_port_when_the_caller_gives_none` | 284 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_a_mirror_only_snapshot_is_not_empty` | 288 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_a_truly_empty_snapshot_is_still_rejected` | 295 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_an_old_snapshot_without_the_field_behaves_as_before` | 305 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_hidden_start_opens_no_windows` | 311 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_one_failing_mirror_does_not_stop_the_others` | 317 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_an_already_open_window_is_counted_separately` | 327 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_junk_mirror_entries_are_ignored` | 332 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_a_gap_is_kept_only_after_a_window_was_actually_opened` | 337 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_hidden_start_never_sleeps` | 351 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_latest_snapshot_is_used_when_no_saved_at` | 358 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::SnapshotResumeTests.test_session_results_keep_their_shape` | 362 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |
| `test_snapshot_mirrors.py::ResumeRouteHttpTests.test_the_handler_passes_the_servers_port` | 370 | kapsam dışı | yok | anlık görüntü ve yansılar. İz: T3 (dosya) |

### `py/tests/test_statedocs_hosts_diag.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_statedocs_hosts_diag.py::HostsDiagDual.test_hosts_dual_roundtrip_and_perm` | 21 | kapsam dışı | yok | durum deposu ayna/DB kipi. İz: W0-a durum (rs/state) |
| `test_statedocs_hosts_diag.py::HostsDiagDual.test_hosts_hand_edit_wins_in_dual` | 27 | kapsam dışı | yok | durum deposu ayna/DB kipi. İz: W0-a durum (rs/state) |
| `test_statedocs_hosts_diag.py::HostsDiagDual.test_hosts_db_mode_without_file` | 32 | kapsam dışı | yok | durum deposu ayna/DB kipi. İz: W0-a durum (rs/state) |
| `test_statedocs_hosts_diag.py::HostsDiagDual.test_diag_log_mirrors` | 38 | kapsam dışı | yok | durum deposu ayna/DB kipi. İz: W0-a durum (rs/state) |

### `py/tests/test_steward_remote.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_remote.py::TestSelectRows.test_remote_rows_only_for_their_projects_on_fresh_hosts` | 178 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestSelectRows.test_stale_host_rows_drop` | 193 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestSelectRows.test_index_hosts_skip_local_and_conflicts` | 196 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestPlanTickRemote.test_unavailable_project_is_not_started_nor_forgotten` | 218 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestPlanTickRemote.test_pending_answer_for_unavailable_project_neither_starts_nor_blocks` | 228 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestPlanTickRemote.test_remote_session_counts_for_max_active` | 235 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestPlanTickRemote.test_subagent_unknown_defers_done_and_shutdown_handover` | 242 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestPlanTickRemote.test_subagent_unknown_but_quiet_idle_session_is_closed` | 254 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestPlanTickRemote.test_answer_delivery_still_allowed_with_unknown_subagent` | 275 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestProjectHost.test_old_records_load_as_local` | 285 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestProjectHost.test_validation_and_normalization` | 293 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestProjectHost.test_host_change_needs_a_stopped_project_or_force_and_clears_state` | 302 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestProjectHost.test_ownership_lock_first` | 325 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestEngineRemote.test_views_come_from_cache_and_term_chat` | 346 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestEngineRemote.test_observe_records_would_with_host_and_never_posts` | 365 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestEngineRemote.test_observe_start_and_answer_of_remote_project` | 379 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestEngineRemote.test_act_mode_denies_remote_while_remote_actions_off` | 393 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestEngineRemote.test_act_mode_remote_project_does_not_eat_local_start_budget` | 403 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestEngineRemote.test_host_down_keeps_state_and_drops_views` | 412 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestEngineRemote.test_last_assistant_reads_share_a_budget` | 423 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestEngineRemote.test_one_slow_session_does_not_blame_a_reachable_host` | 431 | karşılandı | `tests/fake_health.rs::slow_single_read_does_not_blame_a_reachable_host` | yok |
| `test_steward_remote.py::TestEngineRemote.test_all_reads_timing_out_still_blames_host` | 439 | karşılandı | `tests/fake_health.rs::slow_single_read_does_not_blame_a_reachable_host` | yok |
| `test_steward_remote.py::TestTargetRemote.test_rules` | 455 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestTargetRemote.test_http_endpoints` | 475 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestLocalFsGuards.test_cwd_and_cards` | 505 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestLocalFsGuards.test_idea_export_register_file_context` | 513 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestLocalFsGuards.test_project_for_session_skips_local_instance_registry` | 531 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestUpsertRemote.test_active_phase_needs_remote_roster` | 541 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestUpsertRemote.test_host_change_checks_running_sessions` | 555 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestUpsertRemote.test_cli_set_host_goes_through_the_panel` | 574 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote.py::TestWebHostsLastOk.test_last_ok_at_tracks_only_successes` | 587 | karşılandı | `tests/fake_poller.rs::consecutive_failures_are_tolerated_then_rows_are_kept_stale` | yok |

### `py/tests/test_steward_remote_actions.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_remote_actions.py::TestRemoteActions.test_handover_path_body_timeout` | 108 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteActions.test_handover_needs_an_exact_running_row` | 117 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteActions.test_answer_goes_through_term_input_exact_and_preamble_key_is_host_colon_name` | 129 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteActions.test_unknown_born_sends_full_preamble_and_records_nothing` | 153 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteActions.test_start_waits_on_the_poller_cache_without_network` | 164 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteActions.test_start_ready_timeout_is_bounded` | 179 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteActions.test_unknown_busy_is_ready_after_a_few_polls_not_the_full_timeout` | 187 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteActions.test_start_is_not_attempted_on_a_down_host` | 204 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteActions.test_directive_endpoint_and_remote_reject_passes_through` | 209 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteActions.test_not_tmux_backed_or_not_running_rows_are_not_sent` | 220 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteGates.test_observe_records_would_and_never_posts` | 234 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteGates.test_remote_actions_off_denies_in_act_and_logs_once` | 249 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteGates.test_mismatch_unknown_and_unregistered_are_denied` | 260 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteGates.test_down_or_stale_host_gets_no_actions` | 273 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteGates.test_destructive_kinds_need_exact_target_on_the_host` | 283 | karşılandı | `tests/fake_health.rs::ambiguous_or_inexact_target_sends_nothing`<br>`tests/fake_health.rs::remote_post_refuses_destructive_paths_and_host_field` | yok |
| `test_steward_remote_actions.py::TestRemoteGates.test_local_actions_are_unchanged_next_to_a_remote_project` | 298 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteResilience.test_breaker_stops_after_first_transport_error_in_a_tick` | 322 | karşılandı | `tests/fake_health.rs::remote_post_breaker_and_error_marking`<br>`tests/fake_health.rs::transport_error_classification` | yok |
| `test_steward_remote_actions.py::TestRemoteResilience.test_404_and_app_level_reject_do_not_open_the_breaker` | 332 | karşılandı | `tests/fake_health.rs::remote_post_breaker_and_error_marking`<br>`tests/fake_health.rs::transport_error_classification` | yok |
| `test_steward_remote_actions.py::TestRemoteResilience.test_backoff_after_three_failed_ticks_and_single_state_events` | 345 | karşılandı | `tests/fake_health.rs::breaker_opens_after_three_failing_ticks_and_reports_once` | yok |
| `test_steward_remote_actions.py::TestRemoteResilience.test_no_phone_notification_for_unreachable` | 367 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteResilience.test_one_freshness_snapshot_per_tick` | 377 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteResilience.test_read_timeouts_feed_the_breaker` | 386 | karşılandı | `tests/fake_health.rs::slow_single_read_does_not_blame_a_reachable_host` | yok |
| `test_steward_remote_actions.py::TestRemoteResilience.test_snapshot_drives_both_unavailable_and_views` | 401 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_actions.py::TestRemoteResilience.test_proxy_action_timeout_and_forced_local_host` | 413 | karşılandı | `tests/fake_proxy.rs::outgoing_host_is_forced_local_and_caller_query_is_filtered`<br>`tests/fake_health.rs::remote_post_breaker_and_error_marking` | yok |
| `test_steward_remote_actions.py::TestRemoteResilience.test_remote_post_refuses_a_body_with_host` | 428 | karşılandı | `tests/fake_health.rs::remote_post_refuses_destructive_paths_and_host_field` | yok |

### `py/tests/test_steward_remote_cards.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_remote_cards.py::TestRemoteCards.test_card_built_from_remote_reads_and_written_locally` | 129 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteCards.test_manual_refresh_card_uses_remote` | 148 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteCards.test_skipped_when_off_or_host_unavailable` | 155 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteCards.test_running_remote_project_is_skipped` | 176 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteCards.test_one_remote_card_per_tick_oldest_checked_first` | 182 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteCards.test_remote_card_budget_stops_reads` | 199 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteIdeaExport.test_reads_first_then_writes_to_remote_path` | 217 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteIdeaExport.test_tbd_target_file` | 236 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteIdeaExport.test_missing_remote_notes_file_is_created_with_flag` | 243 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteIdeaExport.test_conflict_between_reads_leaves_file_alone` | 251 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteIdeaExport.test_observe_brain_is_dry_but_human_http_writes` | 264 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteIdeaExport.test_gate_off_stale_down_skip_without_any_request` | 275 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteIdeaExport.test_write_failure_reported` | 288 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteRegister.test_adopts_existing_remote_roster_row_without_creating_anything` | 304 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteRegister.test_missing_remote_row_or_gate_gives_clear_error` | 318 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |
| `test_steward_remote_cards.py::TestRemoteRegister.test_conflicting_host_refused` | 335 | kapsam dışı | yok | uzak proje kartları ve dosya dışa aktarımı. İz: T10 (değnekçi) |

### `py/tests/test_steward_remote_destructive.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_remote_destructive.py::TestRemoteStop.test_steward_done_stop_path_body_timeout` | 93 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteStop.test_done_confirmed_read_from_term_chat_when_facts_last_assistant_is_empty` | 105 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteStop.test_done_confirmed_on_host_without_facts_closes_a_quiet_idle_session` | 118 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteStop.test_no_exact_target_logs_remote_too_old_once_and_never_posts` | 128 | karşılandı | `tests/fake_health.rs::ambiguous_or_inexact_target_sends_nothing` | tek seferlik log değnekçinin (T10) |
| `test_steward_remote_destructive.py::TestRemoteStop.test_unknown_capabilities_are_not_treated_as_supported` | 142 | karşılandı | `tests/fake_health.rs::ambiguous_or_inexact_target_sends_nothing` | tek seferlik log değnekçinin (T10) |
| `test_steward_remote_destructive.py::TestRemoteStop.test_precheck_exact_running_own_row` | 150 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteStop.test_no_exact_match_is_not_applied_and_does_not_open_the_breaker` | 164 | karşılandı | `tests/fake_health.rs::remote_stop_sends_one_exact_stop_per_host_per_tick` | yok |
| `test_steward_remote_destructive.py::TestRemoteStop.test_transport_error_still_opens_the_breaker` | 178 | karşılandı | `tests/fake_health.rs::remote_post_breaker_and_error_marking`<br>`tests/fake_health.rs::remote_stop_sends_one_exact_stop_per_host_per_tick` | yok |
| `test_steward_remote_destructive.py::TestRemoteStop.test_observe_records_would_and_never_posts` | 186 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteStop.test_remote_actions_off_and_down_host_are_denied` | 203 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteStop.test_one_destructive_action_per_host_per_tick` | 216 | karşılandı | `tests/fake_health.rs::remote_stop_sends_one_exact_stop_per_host_per_tick` | yok |
| `test_steward_remote_destructive.py::TestRemoteStop.test_human_http_stop_gates` | 237 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteRespawn.test_ready_after_handover_respawns_stop_start_directive_in_order` | 261 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteRespawn.test_stop_failure_means_no_start` | 282 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteRespawn.test_stop_ok_but_row_never_closes_waits_bounded_then_stops` | 291 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteRespawn.test_start_failure_means_no_directive` | 301 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteRespawn.test_session_already_gone_skips_stop` | 309 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteRespawn.test_old_host_respawn_is_refused_without_any_post` | 317 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteRespawn.test_two_respawns_on_one_host_second_is_deferred_to_next_tick` | 325 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteRespawn.test_restart_stops_waits_then_directs` | 340 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteRespawn.test_restart_without_confirmed_stop_sends_nothing_more` | 352 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestRemoteRespawn.test_restart_host_mismatch_is_denied` | 361 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |
| `test_steward_remote_destructive.py::TestLocalUnchanged.test_local_stop_and_respawn_use_the_local_callbacks` | 381 | kapsam dışı | yok | uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile). İz: T10 (değnekçi) |

### `py/tests/test_steward_remote_facts.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_remote_facts.py::TestFactsEndpoint.test_facts_for_exact_names` | 64 | kapsam dışı | yok | `/api/session/facts` ucu (sunucu tarafı). İz: T10 (değnekçi) |
| `test_steward_remote_facts.py::TestFactsEndpoint.test_non_claude_has_no_context_or_subagent` | 76 | kapsam dışı | yok | `/api/session/facts` ucu (sunucu tarafı). İz: T10 (değnekçi) |
| `test_steward_remote_facts.py::TestFactsEndpoint.test_codex_context_from_provider_live_context` | 81 | kapsam dışı | yok | `/api/session/facts` ucu (sunucu tarafı). İz: T10 (değnekçi) |
| `test_steward_remote_facts.py::TestFactsEndpoint.test_codex_background_work_reported` | 97 | kapsam dışı | yok | `/api/session/facts` ucu (sunucu tarafı). İz: T10 (değnekçi) |
| `test_steward_remote_facts.py::TestFactsEndpoint.test_no_names_gives_capabilities_only` | 103 | kapsam dışı | yok | `/api/session/facts` ucu (sunucu tarafı). İz: T10 (değnekçi) |
| `test_steward_remote_facts.py::TestFactsEndpoint.test_route_is_host_routed` | 107 | karşılandı | `tests/parity.rs::host_routed_route_sets_equal_python_source` | yok |
| `test_steward_remote_facts.py::TestExact.test_stop_exact_requires_full_name` | 132 | kapsam dışı | yok | uzak panelin `exact` hedef çözümü (sunucu tarafı). İz: T4 (yaşam döngüsü) |
| `test_steward_remote_facts.py::TestExact.test_stop_without_exact_keeps_unique_base` | 138 | kapsam dışı | yok | uzak panelin `exact` hedef çözümü (sunucu tarafı). İz: T4 (yaşam döngüsü) |
| `test_steward_remote_facts.py::TestExact.test_term_input_exact` | 142 | kapsam dışı | yok | uzak panelin `exact` hedef çözümü (sunucu tarafı). İz: T4 (yaşam döngüsü) |
| `test_steward_remote_facts.py::TestExact.test_handover_exact_refuses_before_touching_session` | 149 | kapsam dışı | yok | uzak panelin `exact` hedef çözümü (sunucu tarafı). İz: T4 (yaşam döngüsü) |
| `test_steward_remote_facts.py::TestExact.test_term_resolve_exact` | 153 | kapsam dışı | yok | uzak panelin `exact` hedef çözümü (sunucu tarafı). İz: T4 (yaşam döngüsü) |
| `test_steward_remote_facts.py::TestClient.test_404_caches_api0_and_rechecks_after_ten_minutes` | 202 | karşılandı | `tests/fake_health.rs::probe_facts_404_caches_old_host_and_stops_asking` | yok |
| `test_steward_remote_facts.py::TestClient.test_404_is_not_a_transport_failure` | 217 | karşılandı | `tests/fake_health.rs::probe_facts_404_caches_old_host_and_stops_asking` | yok |
| `test_steward_remote_facts.py::TestClient.test_network_error_does_not_write_cache` | 225 | karşılandı | `tests/fake_health.rs::probe_facts_transient_failure_is_not_cached` | yok |
| `test_steward_remote_facts.py::TestClient.test_view_enriched_from_facts_single_request` | 235 | kapsam dışı | yok | olguların oturum görünümüne işlenmesi (`_apply_facts`); tek istek kuralı `probe_facts_reads_caps_and_facts_in_one_request`. İz: T10 (değnekçi) |
| `test_steward_remote_facts.py::TestClient.test_empty_facts_last_assistant_falls_back_to_term_chat_but_keeps_facts` | 249 | kapsam dışı | yok | olguların oturum görünümüne işlenmesi (`_apply_facts`); tek istek kuralı `probe_facts_reads_caps_and_facts_in_one_request`. İz: T10 (değnekçi) |
| `test_steward_remote_facts.py::TestClient.test_facts_missing_for_a_session_falls_back_to_term_chat` | 261 | kapsam dışı | yok | olguların oturum görünümüne işlenmesi (`_apply_facts`); tek istek kuralı `probe_facts_reads_caps_and_facts_in_one_request`. İz: T10 (değnekçi) |
| `test_steward_remote_facts.py::TestClient.test_old_host_keeps_a1_behavior` | 267 | kapsam dışı | yok | olguların oturum görünümüne işlenmesi (`_apply_facts`); tek istek kuralı `probe_facts_reads_caps_and_facts_in_one_request`. İz: T10 (değnekçi) |
| `test_steward_remote_facts.py::TestClient.test_enriched_view_clears_subagent_unknown` | 274 | kapsam dışı | yok | olguların oturum görünümüne işlenmesi (`_apply_facts`); tek istek kuralı `probe_facts_reads_caps_and_facts_in_one_request`. İz: T10 (değnekçi) |

### `py/tests/test_steward_remote_session_resolve.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_remote_session_resolve.py::TestDirective.test_project_name_reaches_the_single_dated_session_without_any_start` | 103 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDirective.test_engine_counts_a_dated_session_without_blueprint_as_running` | 116 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDirective.test_no_running_session_starts_with_the_project_name` | 124 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDirective.test_prefix_neighbour_session_is_not_a_second_session_of_the_project` | 135 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDirective.test_repeated_identical_failure_is_logged_once` | 144 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDirective.test_two_running_sessions_are_ambiguous_and_nothing_is_posted` | 159 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDirective.test_full_session_name_is_verified_against_the_rows` | 174 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDirective.test_underscore_suffix_resolves` | 187 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDirective.test_another_projects_prefix_does_not_mix_in` | 195 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDestructiveAndHandover.test_handover_uses_the_real_name_and_records_it` | 211 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDestructiveAndHandover.test_stop_uses_the_real_name` | 218 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDestructiveAndHandover.test_wait_closed_watches_the_real_name` | 225 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDestructiveAndHandover.test_respawn_after_handover_stops_real_name_starts_project_directs_new_name` | 236 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDestructiveAndHandover.test_human_restart_stops_real_name_then_starts_the_project` | 256 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestDestructiveAndHandover.test_engine_handover_on_dated_view_name` | 264 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestStartOnceAndReads.test_refresh_after_start_sees_the_new_session` | 275 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestStartOnceAndReads.test_lagging_cache_still_gets_no_second_start_in_the_tick` | 284 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestStartOnceAndReads.test_cwd_and_file_reads_use_the_real_name` | 296 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |
| `test_steward_remote_session_resolve.py::TestLocalUnchanged.test_local_directive_still_uses_the_local_path` | 315 | kapsam dışı | yok | uzak proje -> oturum çözümü. İz: T10 (değnekçi) |

### `py/tests/test_steward_remote_surface.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_remote_surface.py::TestState.test_running_has_remote_rows_with_host_and_project_flag` | 72 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestState.test_state_shows_open_tbd_and_todo_counts` | 85 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestState.test_local_namesake_does_not_make_remote_project_running` | 93 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestState.test_no_double_count` | 99 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestState.test_stale_host_rows_not_listed` | 106 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestState.test_question_host_and_remote_hosts_health` | 111 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestState.test_local_only_state_has_no_remote_keys` | 128 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestRemoteReads.test_context_reads_over_host_not_local_fs` | 148 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestRemoteReads.test_context_running_with_dated_session_name` | 161 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestRemoteReads.test_same_path_local_folder_is_never_read` | 169 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestRemoteReads.test_errors_and_down_host_return_empty_never_raise` | 178 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestRemoteReads.test_file_read_and_path_guard` | 191 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestRemoteReads.test_enrich_item_remote` | 200 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestNotifyAndLog.test_ask_prefix` | 210 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestNotifyAndLog.test_ask_goes_out_with_host_prefix` | 221 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestNotifyAndLog.test_action_log_host_only_remote` | 229 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestJobSubmit.test_host_is_the_projects_host` | 254 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestJobSubmit.test_remote_project_rejects_local_files` | 261 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestMcpAndBrain.test_mcp_overview_carries_host_only_for_remote` | 269 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestMcpAndBrain.test_mcp_signatures_unchanged_notes_added` | 276 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestMcpAndBrain.test_workspace_note_only_when_remote` | 285 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestCli.test_projects_host_column_only_with_remote` | 308 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestCli.test_status_remote_summary_and_health` | 316 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestCli.test_status_panel_down_is_unknown_not_error` | 326 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |
| `test_steward_remote_surface.py::TestCli.test_status_without_remote_does_not_call_panel` | 331 | kapsam dışı | yok | değnekçi durum yüzeyi, MCP, CLI. İz: T10 (değnekçi) |

### `py/tests/test_steward_review_api.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_review_api.py::TestPool.test_pool_add_disable_enable_remove` | 46 | kapsam dışı | yok | review API. İz: T8 (reviewer) |
| `test_steward_review_api.py::TestPool.test_remove_of_auto_project_is_not_reenabled_by_sync` | 60 | kapsam dışı | yok | review API. İz: T8 (reviewer) |
| `test_steward_review_api.py::TestPool.test_list_row_carries_role_only_for_reviewer` | 66 | kapsam dışı | yok | review API. İz: T8 (reviewer) |
| `test_steward_review_api.py::TestPool.test_non_reviewer_and_unknown_steward_rejected` | 72 | kapsam dışı | yok | review API. İz: T8 (reviewer) |
| `test_steward_review_api.py::TestPool.test_brain_actor_rejected_everywhere` | 78 | kapsam dışı | yok | review API. İz: T8 (reviewer) |
| `test_steward_review_api.py::TestRunCancel.test_manual_run_validates_and_starts` | 87 | kapsam dışı | yok | review API. İz: T8 (reviewer) |
| `test_steward_review_api.py::TestRunCancel.test_manual_run_picks_the_effort_pair` | 96 | kapsam dışı | yok | review API. İz: T8 (reviewer) |
| `test_steward_review_api.py::TestRunCancel.test_manual_run_refused_when_disabled_or_busy` | 105 | kapsam dışı | yok | review API. İz: T8 (reviewer) |
| `test_steward_review_api.py::TestRunCancel.test_cancel_calls_cancel_key` | 116 | kapsam dışı | yok | review API. İz: T8 (reviewer) |
| `test_steward_review_api.py::TestReads.test_state_findings_and_file` | 127 | kapsam dışı | yok | review API. İz: T8 (reviewer) |
| `test_steward_review_api.py::TestReads.test_file_path_escape_rejected` | 151 | kapsam dışı | yok | review API. İz: T8 (reviewer) |
| `test_steward_review_api.py::TestReads.test_reads_need_reviewer` | 162 | kapsam dışı | yok | review API. İz: T8 (reviewer) |
| `test_steward_review_api.py::TestCli.test_parsing_maps_to_api` | 188 | kapsam dışı | yok | review API. İz: T8 (reviewer) |
| `test_steward_review_api.py::TestCli.test_reads_status_history_findings` | 204 | kapsam dışı | yok | review API. İz: T8 (reviewer) |

### `py/tests/test_stop_with_handover.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_stop_with_handover.py::LocalTest.test_success_handover_then_exact_stop` | 62 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::LocalTest.test_handover_send_failure_does_not_stop` | 67 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::LocalTest.test_timeout_does_not_stop` | 73 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::LocalTest.test_unreadable_baseline_does_not_handover_or_stop` | 78 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::LocalTest.test_not_applicable_returns_none` | 88 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::LocalTest.test_english_message` | 94 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::ReaskTest.test_reask_then_ready` | 115 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::ReaskTest.test_reask_still_none_does_not_close` | 122 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_success_handover_then_forced_exact_stop` | 148 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_timeout_does_not_stop` | 155 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_handover_failure_does_not_stop` | 160 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_unreadable_baseline_does_nothing` | 165 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_not_applicable_returns_none` | 170 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_unreadable_host_does_not_stop` | 174 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_each_outcome_is_logged` | 180 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteFallbackTest.test_fallback_stop_is_exact_and_logged` | 190 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_without_ho_field_old_behaviour_byte_for_byte` | 265 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_force_with_ho_is_a_400_conflict_never_a_silent_plain_stop` | 271 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_exact_with_ho_still_hands_over_with_the_exact_flag` | 278 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_exact_with_ho_not_applicable_falls_back_to_exact_plain_stop` | 290 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_exact_without_ho_stays_plain_stop` | 298 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_remote_without_ho_goes_straight_to_proxy` | 302 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_ho_returns_pending_immediately_while_job_blocks` | 308 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_ho_failure_is_reported_and_never_plain_stops` | 314 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_ho_success` | 322 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_ho_not_applicable_falls_back_to_plain_stop_inside_the_job` | 329 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_second_ho_while_pending_does_not_start_second_job` | 336 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_remote_ho_runs_remote_helper_in_job` | 344 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_job_exception_becomes_error_with_force_hint` | 350 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_status_unknown_after_restart_is_none` | 356 | kapsam dışı | yok | devirli durdurma (yerel + uzak). İz: T4 (yaşam döngüsü) |

### `py/tests/test_term_dedup.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_term_dedup.py::Dedup.test_claim_once_then_dup_until_ttl` | 13 | kapsam dışı | yok | girdi tekrar ayıklama (uzak panelin kendi tarafı). İz: T2 (terminal) |
| `test_term_dedup.py::Dedup.test_scoped_by_path_and_name` | 18 | kapsam dışı | yok | girdi tekrar ayıklama (uzak panelin kendi tarafı). İz: T2 (terminal) |
| `test_term_dedup.py::Dedup.test_release_allows_retry` | 23 | kapsam dışı | yok | girdi tekrar ayıklama (uzak panelin kendi tarafı). İz: T2 (terminal) |
| `test_term_dedup.py::Dedup.test_valid_id` | 28 | karşılandı | `tests/parity.rs::input_id_rule_is_python_or_stricter` | Rust kuralı Python'dan sıkı (ASCII dışı geçersiz) |
| `test_term_dedup.py::Dedup.test_failed_write_releases` | 33 | kapsam dışı | yok | girdi tekrar ayıklama (uzak panelin kendi tarafı). İz: T2 (terminal) |
| `test_term_dedup.py::ProxyRetry.test_retries_transport_failure_same_body_short_timeout` | 44 | karşılandı | `tests/fake_proxy.rs::term_input_retries_three_times_with_same_input_id` | yok |
| `test_term_dedup.py::ProxyRetry.test_gives_up_after_three` | 55 | karşılandı | `tests/fake_proxy.rs::term_input_retries_three_times_with_same_input_id` | yok |
| `test_term_dedup.py::ProxyRetry.test_remote_logic_error_not_retried` | 61 | karşılandı | `tests/fake_proxy.rs::term_input_retries_three_times_with_same_input_id` | yok |
| `test_term_dedup.py::ProxyRetry.test_without_input_id_legacy_single_call_default_timeout` | 66 | karşılandı | `tests/fake_proxy.rs::term_input_retries_three_times_with_same_input_id` | yok |
| `test_term_dedup.py::ProxyRetry.test_other_paths_untouched` | 73 | karşılandı | `tests/fake_proxy.rs::term_input_retries_three_times_with_same_input_id` | yok |
| `test_term_dedup.py::HttpDedup.test_second_delivery_does_not_write` | 106 | kapsam dışı | yok | girdi tekrar ayıklama (uzak panelin kendi tarafı). İz: T2 (terminal) |
| `test_term_dedup.py::HttpDedup.test_failed_write_can_be_retried` | 113 | kapsam dışı | yok | girdi tekrar ayıklama (uzak panelin kendi tarafı). İz: T2 (terminal) |
| `test_term_dedup.py::HttpDedup.test_no_input_id_always_writes` | 121 | kapsam dışı | yok | girdi tekrar ayıklama (uzak panelin kendi tarafı). İz: T2 (terminal) |

### `py/tests/test_term_history.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_term_history.py::TermHistoryTests.test_a_page_is_exactly_the_requested_lines_and_matches_tmux` | 84 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_lines_are_in_order_and_just_above_the_screen` | 92 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_pages_tile_the_whole_buffer_without_gaps_or_overlap` | 100 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_the_visible_range_equals_the_live_viewport` | 110 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_colours_are_kept` | 114 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_the_range_is_clamped_to_the_real_buffer` | 117 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_one_request_never_returns_more_than_the_cap` | 124 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_the_default_cap_is_far_below_a_full_capture` | 130 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_reversed_and_out_of_range_requests_are_errors` | 133 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_the_reply_carries_what_the_client_needs_to_realign` | 139 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_history_growth_shifts_the_numbering_and_the_reply_says_so` | 143 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_session_gone_is_a_clear_error_and_drops_the_resolve_cache` | 151 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_a_failed_capture_after_a_good_size_query_drops_the_resolve_cache_too` | 159 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_a_full_screen_app_that_started_in_the_alternate_screen_has_no_history` | 167 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_the_reply_flags_the_alternate_screen_even_when_old_history_exists` | 180 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryTests.test_range_values_cannot_reach_the_tmux_command_line` | 188 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryRouteTests.test_local_page` | 236 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryRouteTests.test_it_needs_the_token` | 243 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryRouteTests.test_name_and_integer_range_are_required` | 247 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryRouteTests.test_a_remote_host_is_proxied_with_a_clean_query` | 255 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryRouteTests.test_a_remote_error_status_reaches_the_client` | 268 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::TermHistoryRouteTests.test_the_path_is_listed_as_host_routed` | 273 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::ProxyGetDedupTests.test_dedup_defaults_to_on_and_keeps_one_entry_per_url` | 308 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::ProxyGetDedupTests.test_a_page_request_without_dedup_leaves_no_trace` | 313 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::ProxyGetDedupTests.test_without_dedup_overlapping_identical_requests_are_not_turned_away` | 321 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |
| `test_term_history.py::DedupLastGoodBoundTests.test_cache_is_lru_bounded` | 336 | kapsam dışı | yok | terminal geçmişi ucu. İz: T2 (terminal) |

### `py/tests/test_term_poll_interval.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_term_poll_interval.py::ParseIntervalTests.test_missing_or_invalid_or_not_slower_means_no_parameter` | 44 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::ParseIntervalTests.test_slower_intervals_are_kept_and_rounded_to_a_tenth` | 48 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::ParseIntervalTests.test_upper_bound_keeps_a_forgotten_connection_from_going_stale` | 55 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::PollLoopTests.test_default_cadence_is_the_module_constant_read_at_call_time` | 91 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::PollLoopTests.test_slow_interval_polls_much_less_often` | 96 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::PollLoopTests.test_wake_polls_immediately_then_fast_for_the_burst_then_slows_down_again` | 102 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::PollLoopTests.test_close_wakes_a_long_wait_immediately` | 116 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::PollLoopTests.test_plain_client_without_wake_keeps_the_old_behavior` | 126 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::WakerRegistryTests.test_notify_sets_only_the_watchers_of_that_name` | 141 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::WakerRegistryTests.test_unregister_removes_the_entry_so_the_registry_cannot_leak` | 150 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::WakerRegistryTests.test_unknown_or_empty_names_are_harmless` | 158 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::RealServerTests.test_default_connection_polls_every_200ms` | 199 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::RealServerTests.test_interval_connection_polls_far_less_often` | 204 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::RealServerTests.test_input_notification_wakes_the_slow_loop_and_the_new_frame_reaches_the_client` | 210 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::RealServerTests.test_closing_the_client_stops_the_loop_and_unregisters_the_waker` | 222 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::FetchFnIntervalTests.test_without_interval_the_relay_is_called_exactly_as_before` | 250 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::FetchFnIntervalTests.test_interval_is_forwarded_to_the_relay_only_when_given` | 254 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::FetchFnIntervalTests.test_loop_interval_lands_on_the_local_loop_only_when_the_tick_is_real_work` | 258 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::InputNotifiesTests.test_text_key_and_raw_input_wake_the_watchers` | 287 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::InputNotifiesTests.test_failed_send_does_not_wake` | 294 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::InputNotifiesTests.test_rejected_key_and_empty_raw_do_not_wake` | 302 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::InputNotifiesTests.test_other_sessions_are_not_woken` | 307 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::RelayIntervalTests.test_interval_goes_to_the_remote_url_and_into_the_key` | 367 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set` | `interval` metin biçimi belgeli fark (`f64` / `{:g}`) |
| `test_term_poll_interval.py::RelayIntervalTests.test_without_interval_url_and_key_are_exactly_as_before` | 374 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set` | `interval` metin biçimi belgeli fark (`f64` / `{:g}`) |
| `test_term_poll_interval.py::RelayIntervalTests.test_slow_and_default_watchers_of_one_session_get_separate_remote_streams` | 380 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set` | `interval` metin biçimi belgeli fark (`f64` / `{:g}`) |
| `test_term_poll_interval.py::RelayIntervalTests.test_two_slow_watchers_share_one_remote_stream` | 388 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set` | `interval` metin biçimi belgeli fark (`f64` / `{:g}`) |
| `test_term_poll_interval.py::RelayIntervalTests.test_death_label_names_the_interval` | 397 | karşılandı | `tests/fake_ws.rs::relay_death_label_names_lite_interval_and_viewport`<br>`tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval` | yok |
| `test_term_poll_interval.py::RelayIntervalTests.test_death_label_without_interval_is_unchanged` | 405 | karşılandı | `tests/fake_ws.rs::relay_death_label_names_lite_interval_and_viewport`<br>`tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval` | yok |
| `test_term_poll_interval.py::WatchQueryTests.test_ws_asks_for_the_slow_interval_but_the_rest_fallback_does_not` | 417 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |
| `test_term_poll_interval.py::WatchQueryTests.test_the_viewers_interval_is_one_the_panel_accepts_as_slow` | 423 | kapsam dışı | yok | terminal yoklama aralığı (yerel + relay kullanımı). İz: T2 (terminal) |

### `py/tests/test_term_resize.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_term_resize.py::SizeFollowerTests.test_a_window_matching_the_pane_never_posts` | 58 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::SizeFollowerTests.test_a_stable_different_size_posts_once_with_the_status_bar_row_removed` | 65 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::SizeFollowerTests.test_a_changing_size_restarts_the_wait_and_arriving_at_the_expected_size_cancels` | 78 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::SizeFollowerTests.test_a_rejected_request_disables_following_for_the_window_lifetime` | 91 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::SizeFollowerTests.test_release_posts_only_after_a_size_was_sent` | 100 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::SizeFollowerTests.test_the_same_size_is_not_sent_twice` | 110 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::ViewerHookTests.test_observed_after_the_window_was_asked_to_match_the_pane` | 131 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::ViewerHookTests.test_not_observed_when_resize_is_disabled_or_pane_unknown` | 137 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::ServerSideTests.test_resizes_a_session_without_attached_clients` | 163 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::ServerSideTests.test_refuses_when_a_client_is_attached_or_unknown` | 168 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::ServerSideTests.test_rejects_out_of_range_and_non_integer_sizes` | 176 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::ServerSideTests.test_release_does_not_need_a_size_and_skips_the_client_check` | 181 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::ServerSideTests.test_the_route_is_host_routed` | 187 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::TmuxArgvTests.test_bounds_are_enforced_before_any_subprocess` | 192 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |
| `test_term_resize.py::TmuxArgvTests.test_argv_uses_the_exact_target` | 198 | kapsam dışı | yok | terminal boyutu ucu. İz: T2 (terminal) |

### `py/tests/test_term_viewport.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_term_viewport.py::SnapshotTests.test_returns_the_geometry_and_the_visible_screen` | 93 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::SnapshotTests.test_agrees_with_the_separate_calls_it_replaces` | 104 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::SnapshotTests.test_it_is_one_tmux_process_running_two_commands` | 112 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::SnapshotTests.test_a_missing_session_is_none` | 120 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::SnapshotTests.test_the_alternate_screen_is_reported` | 123 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::SnapshotTests.test_a_gone_session_never_falls_back_to_a_longer_sibling_name` | 130 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::SnapshotTests.test_a_hostile_name_cannot_smuggle_a_tmux_command` | 137 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::SnapshotTests.test_a_masked_prompt_is_visible_through_the_snapshot_pty` | 143 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::SnapshotTests.test_tty_is_masked_is_none_without_a_usable_path` | 150 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::SnapshotParsingTests.test_an_empty_pty_field_is_kept_as_an_empty_string` | 163 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::SnapshotParsingTests.test_malformed_output_is_none` | 166 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::SnapshotParsingTests.test_a_failing_tmux_is_none` | 170 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::SnapshotParsingTests.test_a_missing_tmux_binary_is_none` | 173 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::ViewportFrameTests.test_it_equals_the_classic_lite_frame_except_for_the_scrollback_derived_fields` | 191 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::ViewportFrameTests.test_the_first_line_is_self_contained_when_a_wrapped_colored_line_is_cut_at_the_top` | 203 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::ViewportFrameTests.test_the_frame_is_much_smaller_than_the_full_capture` | 222 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::ViewportFrameTests.test_a_masked_prompt_is_reported` | 227 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::ViewportFrameTests.test_the_classic_path_spawns_three_tmux_processes_and_the_viewport_path_one` | 233 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::ViewportFrameTests.test_it_falls_back_to_the_classic_frame_when_the_single_call_fails` | 239 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::ViewportFrameTests.test_a_gone_session_is_the_same_error_as_before_and_drops_the_resolve_cache` | 246 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::ViewportFrameTests.test_the_mode_is_read_from_the_visible_screen` | 255 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::PlumbingTests.test_remote_query_adds_viewport_only_when_requested` | 298 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::PlumbingTests.test_local_viewport_asks_the_viewport_frame_and_the_lite_wrapper_leaves_it_alone` | 304 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::PlumbingTests.test_local_without_viewport_keeps_the_old_call_shape` | 309 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::PlumbingTests.test_rest_tier_forwards_viewport_to_the_remote_host` | 313 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::PlumbingTests.test_ws_tier_forwards_viewport_and_interval_to_the_relay` | 318 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::PlumbingTests.test_ws_tier_without_viewport_keeps_the_old_call_shape` | 323 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::RelayKeyTests.test_viewport_adds_the_query_parameter_the_label_and_the_key` | 370 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set`<br>`tests/fake_ws.rs::relay_death_label_names_lite_interval_and_viewport` | yok |
| `test_term_viewport.py::RelayKeyTests.test_without_viewport_url_label_and_key_are_exactly_as_before` | 376 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set`<br>`tests/fake_ws.rs::relay_death_label_names_lite_interval_and_viewport` | yok |
| `test_term_viewport.py::RelayKeyTests.test_viewer_with_and_without_viewport_never_share_a_relay` | 384 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set`<br>`tests/fake_ws.rs::relay_death_label_names_lite_interval_and_viewport` | yok |
| `test_term_viewport.py::RouteTests.test_rest_viewport_returns_the_screen_only_frame` | 416 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::RouteTests.test_rest_without_viewport_is_untouched` | 424 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |
| `test_term_viewport.py::RouteTests.test_ws_term_route_parses_viewport_and_passes_it_on` | 431 | kapsam dışı | yok | terminal görünüm alanı. İz: T2 (terminal) |

### `py/tests/test_triage_fixes_20261107.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_triage_fixes_20261107.py::RunDirTest.test_rejects_traversal` | 16 | kapsam dışı | yok | çeşitli yerel düzeltmeler. İz: T4 (yaşam döngüsü) |
| `test_triage_fixes_20261107.py::RunDirTest.test_normal_id_ok` | 21 | kapsam dışı | yok | çeşitli yerel düzeltmeler. İz: T4 (yaşam döngüsü) |
| `test_triage_fixes_20261107.py::HandoverDoneUserMessageTest.test_user_message_with_rfh_text_does_not_count` | 34 | kapsam dışı | yok | çeşitli yerel düzeltmeler. İz: T4 (yaşam döngüsü) |
| `test_triage_fixes_20261107.py::HandoverDoneUserMessageTest.test_assistant_rfh_counts` | 38 | kapsam dışı | yok | çeşitli yerel düzeltmeler. İz: T4 (yaşam döngüsü) |
| `test_triage_fixes_20261107.py::HandoverDoneUserMessageTest.test_non_assistant_row_types_with_rfh_do_not_count` | 43 | kapsam dışı | yok | çeşitli yerel düzeltmeler. İz: T4 (yaşam döngüsü) |
| `test_triage_fixes_20261107.py::HandoverDoneUserMessageTest.test_real_rfh_after_blob_row_counts` | 50 | kapsam dışı | yok | çeşitli yerel düzeltmeler. İz: T4 (yaşam döngüsü) |
| `test_triage_fixes_20261107.py::HostsDbNonListTest.test_db_mode_non_list_is_corrupt` | 56 | karşılandı | `record.rs::corrupt_and_irregular_documents` | `parse_value` dizi olmayan değeri bozuk sayar |

### `py/tests/test_ucli_checks_host_routing.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_checks_host_routing.py::Routing.test_sets` | 10 | karşılandı | `tests/parity.rs::host_routed_route_sets_equal_python_source` | yok |
| `test_ucli_checks_host_routing.py::Routing.test_get_branches_proxy_when_host_given` | 15 | kapsam dışı | yok | `web.py` GET dalının vekile bağlanması. İz: W0-c kapı (rs/gate) / copsd uç bağlama (cops) |
| `test_ucli_checks_host_routing.py::Routing.test_metrics_routed` | 20 | kapsam dışı | yok | `web.py` GET dalının vekile bağlanması. İz: W0-c kapı (rs/gate) / copsd uç bağlama (cops) |
| `test_ucli_checks_host_routing.py::Routing.test_compare_routed` | 26 | kapsam dışı | yok | `web.py` GET dalının vekile bağlanması. İz: W0-c kapı (rs/gate) / copsd uç bağlama (cops) |

### `py/tests/test_ucli_phase.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_phase.py::LivePhaseTests.test_a_streaming_phase_comes_through` | 36 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseTests.test_the_last_write_time_of_the_file_comes_through_as_last_unix` | 41 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseTests.test_a_missing_or_garbage_last_activity_is_left_out_not_zeroed` | 46 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseTests.test_a_retry_phase_keeps_its_reason` | 54 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseTests.test_no_phase_a_null_phase_or_an_older_binary_mean_none` | 60 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseTests.test_a_phase_without_a_usable_name_is_ignored` | 67 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseTests.test_bad_numbers_are_dropped_never_turned_into_an_invented_zero` | 73 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseTests.test_text_is_trimmed_and_capped` | 79 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseTests.test_a_future_phase_name_passes_through_so_the_badge_does_not_go_silent` | 85 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseTests.test_only_the_known_fields_are_returned` | 89 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseTests.test_no_status_file_no_sid_or_a_broken_file_mean_none` | 93 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseTests.test_every_other_provider_has_no_phase` | 101 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_it_asks_the_sessions_own_provider_with_its_cwd_and_sid` | 122 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_waiting_for_the_response_turns_amber_then_red_on_the_thresholds` | 127 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_retries_and_rate_limits_are_always_amber` | 133 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_a_model_that_is_thinking_or_writing_is_progress_not_a_warning` | 139 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_a_stream_that_goes_quiet_turns_amber_then_red_and_progress_stays_green` | 145 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_a_long_running_stream_that_keeps_writing_is_not_a_warning` | 154 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_idle_is_reported_but_does_not_decide_the_waiting_colour` | 159 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_without_a_last_write_time_a_stream_has_no_idle_and_no_warning` | 163 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_the_internal_last_unix_is_not_leaked_to_the_wire` | 167 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_the_providers_dict_is_not_mutated` | 171 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_a_missing_since_unix_means_no_elapsed_and_no_warning` | 176 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_a_since_in_the_future_never_gives_a_negative_elapsed` | 180 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_no_phase_means_none` | 184 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_a_failing_provider_never_breaks_the_panel` | 188 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::StatusPayloadPhaseTests.test_a_registered_running_ucli_row_carries_its_phase` | 226 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::StatusPayloadPhaseTests.test_an_unregistered_running_ucli_row_carries_its_phase_and_the_amber_wait` | 231 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::StatusPayloadPhaseTests.test_a_frozen_stream_row_goes_amber_from_the_file_write_time` | 235 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |
| `test_ucli_phase.py::StatusPayloadPhaseTests.test_a_stopped_row_and_a_phaseless_provider_have_no_phase` | 242 | kapsam dışı | yok | ucli evresi. İz: T7 (periyodik) |

### `py/tests/test_ucli_usage.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_usage.py::LiveUsageTests.test_the_counters_come_through_as_written` | 50 | kapsam dışı | yok | ucli kullanım ucu. İz: T7 (periyodik) |
| `test_ucli_usage.py::LiveUsageTests.test_a_binary_without_usage_means_unknown_not_zero` | 54 | kapsam dışı | yok | ucli kullanım ucu. İz: T7 (periyodik) |
| `test_ucli_usage.py::LiveUsageTests.test_a_usage_that_is_not_an_object_means_unknown` | 58 | kapsam dışı | yok | ucli kullanım ucu. İz: T7 (periyodik) |
| `test_ucli_usage.py::LiveUsageTests.test_no_status_file_no_sid_or_a_broken_file_mean_unknown` | 64 | kapsam dışı | yok | ucli kullanım ucu. İz: T7 (periyodik) |
| `test_ucli_usage.py::LiveUsageTests.test_the_unmetered_fields_of_an_older_binary_count_as_zero` | 72 | kapsam dışı | yok | ucli kullanım ucu. İz: T7 (periyodik) |
| `test_ucli_usage.py::LiveUsageTests.test_garbage_values_become_zero_never_an_invented_number` | 78 | kapsam dışı | yok | ucli kullanım ucu. İz: T7 (periyodik) |
| `test_ucli_usage.py::LiveUsageTests.test_only_the_known_counters_are_returned` | 86 | kapsam dışı | yok | ucli kullanım ucu. İz: T7 (periyodik) |
| `test_ucli_usage.py::LiveUsageTests.test_every_other_provider_has_no_counter` | 92 | kapsam dışı | yok | ucli kullanım ucu. İz: T7 (periyodik) |
| `test_ucli_usage.py::LiveUsageHelperTests.test_it_asks_the_sessions_own_provider_with_its_cwd_and_sid` | 104 | kapsam dışı | yok | ucli kullanım ucu. İz: T7 (periyodik) |
| `test_ucli_usage.py::LiveUsageHelperTests.test_a_failing_provider_never_breaks_the_panel` | 112 | kapsam dışı | yok | ucli kullanım ucu. İz: T7 (periyodik) |
| `test_ucli_usage.py::StatusPayloadUsageTests.test_a_registered_running_ucli_row_carries_its_counters` | 148 | kapsam dışı | yok | ucli kullanım ucu. İz: T7 (periyodik) |
| `test_ucli_usage.py::StatusPayloadUsageTests.test_an_unregistered_running_ucli_row_carries_its_counters` | 153 | kapsam dışı | yok | ucli kullanım ucu. İz: T7 (periyodik) |
| `test_ucli_usage.py::StatusPayloadUsageTests.test_a_stopped_row_and_a_counterless_provider_have_no_usage` | 157 | kapsam dışı | yok | ucli kullanım ucu. İz: T7 (periyodik) |

### `py/tests/test_usage_byok_host_routed.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_usage_byok_host_routed.py::Routing.test_routed_but_whole_settings_stays_local` | 15 | karşılandı | `tests/parity.rs::host_routed_route_sets_equal_python_source` | yok |
| `test_usage_byok_host_routed.py::Routing.test_byok_needs_admin_config` | 20 | karşılandı | `tests/parity.rs::host_routed_paths_have_the_same_authz_action_as_python` | eylem adı Python `authz.action_for` ile aynı |
| `test_usage_byok_host_routed.py::Routing.test_secret_not_sent_over_plain_http` | 29 | karşılandı | `tests/fake_proxy.rs::secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked`<br>`guard.rs::secret_urls` | yok |
| `test_usage_byok_host_routed.py::Routing.test_https_loopback_and_status_read_pass` | 34 | karşılandı | `tests/fake_proxy.rs::secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked`<br>`guard.rs::secret_urls` | yok |
| `test_usage_byok_host_routed.py::Endpoint.test_set_read_clear_never_echoes_value` | 51 | kapsam dışı | yok | BYOK ayar ucu (sunucu tarafı). İz: T7 (periyodik) |
| `test_usage_byok_host_routed.py::Endpoint.test_rejects_bad_input_without_writing` | 61 | kapsam dışı | yok | BYOK ayar ucu (sunucu tarafı). İz: T7 (periyodik) |

### `py/tests/test_usage_cli.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_usage_cli.py::UsageCliTests.test_table_sorted_by_spend_and_skips_non_claude` | 61 | kapsam dışı | yok | kullanım CLI'si. İz: T6 (CLI) |
| `test_usage_cli.py::UsageCliTests.test_json_and_name_filter` | 68 | kapsam dışı | yok | kullanım CLI'si. İz: T6 (CLI) |
| `test_usage_cli.py::UsageCliTests.test_command_is_registered` | 75 | kapsam dışı | yok | kullanım CLI'si. İz: T6 (CLI) |
| `test_usage_cli.py::StatusUsageTotalTests.test_status_rows_carry_usage_total_without_blocking` | 81 | kapsam dışı | yok | kullanım CLI'si. İz: T6 (CLI) |

### `py/tests/test_web_agents_glue.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_web_agents_glue.py::CallerTests.test_agent_token_maps_to_parent` | 31 | kapsam dışı | yok | ajan token'ı ve yerel uçlar. İz: T9 (enterprise) |
| `test_web_agents_glue.py::CallerTests.test_panel_token_is_human` | 34 | kapsam dışı | yok | ajan token'ı ve yerel uçlar. İz: T9 (enterprise) |
| `test_web_agents_glue.py::CallerTests.test_bad_or_missing_token_rejected` | 37 | kapsam dışı | yok | ajan token'ı ve yerel uçlar. İz: T9 (enterprise) |
| `test_web_agents_glue.py::CallerTests.test_agent_token_is_not_a_panel_token` | 41 | kapsam dışı | yok | ajan token'ı ve yerel uçlar. İz: T9 (enterprise) |
| `test_web_agents_glue.py::CallerTests.test_agents_paths_are_local_only` | 46 | kapsam dışı | yok | ajan token'ı ve yerel uçlar. İz: T9 (enterprise) |
| `test_web_agents_glue.py::StopHookTests.test_stop_notifies_agents_for_each_killed_session` | 52 | kapsam dışı | yok | ajan token'ı ve yerel uçlar. İz: T9 (enterprise) |

### `py/tests/test_web_grpc_ucli_flags.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_web_grpc_ucli_flags.py::GrpcUcliFlagsTest.test_roundtrip_never_raises_and_keeps_core_fields` | 19 | karşılandı | `tests/parity.rs::grpc_wire_decoding_matches_python_conversion` | istemci yarısı (proto -> dict) Python pb2 ile kodlanıp Rust'ta çözülür; dict -> proto sunucu tarafı |
| `test_web_grpc_ucli_flags.py::GrpcUcliFlagsTest.test_no_flags_means_none` | 24 | karşılandı | `tests/parity.rs::grpc_wire_decoding_matches_python_conversion` | istemci yarısı (proto -> dict) Python pb2 ile kodlanıp Rust'ta çözülür; dict -> proto sunucu tarafı |
| `test_web_grpc_ucli_flags.py::GrpcUcliFlagsTest.test_flags_roundtrip` | 29 | karşılandı | `tests/parity.rs::grpc_wire_decoding_matches_python_conversion` | istemci yarısı (proto -> dict) Python pb2 ile kodlanıp Rust'ta çözülür; dict -> proto sunucu tarafı |
| `test_web_grpc_ucli_flags.py::GrpcUcliFlagsTest.test_non_ucli_row_has_no_flags` | 37 | karşılandı | `tests/parity.rs::grpc_wire_decoding_matches_python_conversion` | istemci yarısı (proto -> dict) Python pb2 ile kodlanıp Rust'ta çözülür; dict -> proto sunucu tarafı |

### `py/tests/test_web_hosts_close_timeout.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_web_hosts_close_timeout.py::CloseTimeoutTest.test_default_close_timeout_is_short` | 12 | karşılandı | `tests/fake_ws.rs::dropped_streams_close_their_sockets_and_leak_no_fds`<br>`tests/fake_ws.rs::ws_probe_raises_tier_at_once_and_lowers_it_only_after_tolerance` | Rust kapanışta beklemez (görev iptal); yoklama kapanışı 1 sn sınırlı |
| `test_web_hosts_close_timeout.py::CloseTimeoutTest.test_explicit_close_timeout_wins` | 17 | karşılandı | `tests/fake_ws.rs::dropped_streams_close_their_sockets_and_leak_no_fds`<br>`tests/fake_ws.rs::ws_probe_raises_tier_at_once_and_lowers_it_only_after_tolerance` | Rust kapanışta beklemez (görev iptal); yoklama kapanışı 1 sn sınırlı |

### `py/tests/test_web_hosts_keepalive_idle_close.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_web_hosts_keepalive_idle_close.py::KeepAliveIdleCloseTests.test_peer_closed_idle_connection_is_replaced_silently` | 81 | karşılandı | `tests/fake_http.rs::server_closed_idle_connection_does_not_fail_post` | yok |
| `test_web_hosts_keepalive_idle_close.py::KeepAliveIdleCloseTests.test_race_dead_conn_judged_alive_is_retried_once_without_error` | 89 | karşılandı | `tests/fake_http.rs::stale_pooled_get_is_retried_once_with_fresh_signature` | yok |

### `py/tests/test_web_hosts_peer_guard.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_web_hosts_peer_guard.py::PeerGuardTest.test_dns_name_resolving_to_loopback_is_refused` | 34 | karşılandı | `tests/fake_proxy.rs::secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked` | yok |
| `test_web_hosts_peer_guard.py::PeerGuardTest.test_dns_name_resolving_to_lan_is_allowed` | 39 | karşılandı | `guard.rs::blocked_ranges`<br>`tests/fake_ws.rs::dns_name_resolving_to_loopback_is_refused_for_ws_before_connecting` | izin kararı `ip_is_blocked` tablosu; DNS adıyla LAN'a gerçek bağlantı testte kurulamaz (loopback dışı yasak) |
| `test_web_hosts_peer_guard.py::PeerGuardTest.test_ip_literal_is_not_rechecked` | 42 | karşılandı | `tests/fake_ws.rs::dns_name_resolving_to_loopback_is_refused_for_ws_before_connecting` | IP literali kontrol adımı |
| `test_web_hosts_peer_guard.py::PeerGuardTest.test_helpers` | 45 | karşılandı | `guard.rs::blocked_ranges`<br>`endpoint.rs::parses_common_forms`<br>`tests/parity.rs::address_filters_match_python` | yok |
| `test_web_hosts_peer_guard.py::PeerGuardTest.test_conn_cls_for` | 52 | karşılandı | `tests/fake_tls.rs::wss_and_https_rest_work_with_a_custom_root` | yok |

### `py/tests/test_web_hosts_remote_shape.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_web_hosts_remote_shape.py::MergeStatusBadFieldsTest.test_missing_null_or_non_text_name_and_cwd_do_not_break_the_merge` | 25 | karşılandı | `tests/fake_poller.rs::merge_status_resorts_globally_and_keeps_host_rows`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python` | yok |
| `test_web_hosts_remote_shape.py::MergeStatusBadFieldsTest.test_unusable_values_sort_as_empty_text` | 33 | karşılandı | `tests/fake_poller.rs::merge_status_resorts_globally_and_keeps_host_rows`<br>`tests/parity.rs::poll_cache_tier_and_merge_match_python` | yok |
| `test_web_hosts_remote_shape.py::RemoteShapeTest.test_non_object_rows_are_skipped` | 62 | karşılandı | `tests/fake_poller.rs::malformed_remote_status_is_an_error_or_reduced_to_empty_fields`<br>`tests/parity.rs::status_reduction_matches_python` | yok |
| `test_web_hosts_remote_shape.py::RemoteShapeTest.test_non_list_closed_and_retired_are_empty` | 68 | karşılandı | `tests/fake_poller.rs::malformed_remote_status_is_an_error_or_reduced_to_empty_fields`<br>`tests/parity.rs::status_reduction_matches_python` | yok |
| `test_web_hosts_remote_shape.py::RemoteShapeTest.test_non_list_sessions_is_an_unexpected_shape` | 73 | karşılandı | `tests/fake_poller.rs::malformed_remote_status_is_an_error_or_reduced_to_empty_fields` | yok |
| `test_web_hosts_remote_shape.py::RemoteShapeTest.test_one_bad_host_does_not_end_the_poll_turn` | 79 | karşılandı | `tests/fake_poller.rs::malformed_remote_status_is_an_error_or_reduced_to_empty_fields`<br>`tests/fake_restart.rs::panicking_turn_is_counted_and_the_poller_keeps_running` | Rust'ta her host ayrı görev: bozuk yanıt hata değeri, panik bile turu düşürmez |
| `test_web_hosts_remote_shape.py::RemoteShapeTest.test_push_frame_without_a_session_list_is_skipped` | 85 | karşılandı | `tests/fake_ws.rs::junk_frames_keep_the_stream_alive_but_rest_polling_continues`<br>`tests/parity.rs::ws_frames_match_python` | yok |
| `test_web_hosts_remote_shape.py::RemoteShapeTest.test_non_object_or_unreadable_frame_is_skipped_and_logged_once` | 92 | karşılandı | `tests/fake_ws.rs::junk_frames_keep_the_stream_alive_but_rest_polling_continues`<br>`push.rs::skipped_frames_are_logged_at_most_once_a_minute_per_kind`<br>`tests/parity.rs::ws_frames_match_python` | yok |

### `py/tests/test_web_hosts_term_relay.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_web_hosts_term_relay.py::TermRelayTests.test_second_tick_does_not_raise_and_pushed_frame_is_delivered` | 102 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set` | yok |
| `test_web_hosts_term_relay.py::TermRelayTests.test_dead_consumer_is_recreated_and_old_frame_is_not_replayed` | 113 | karşılandı | `tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval` | yok |
| `test_web_hosts_term_relay.py::TermRelayTests.test_silent_half_open_relay_is_restarted_and_logged` | 130 | karşılandı | `tests/fake_ws.rs::silent_relay_is_restarted_after_45s_without_serving_the_stale_frame` | yok |
| `test_web_hosts_term_relay.py::TermRelayTests.test_fresh_relay_is_not_restarted` | 147 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set` | yok |
| `test_web_hosts_term_relay.py::TermRelayTests.test_instantly_dying_consumer_is_not_reconnected_every_tick` | 156 | karşılandı | `tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval` | yok |
| `test_web_hosts_term_relay.py::TermRelayTests.test_consumer_death_is_logged_once_per_label` | 169 | karşılandı | `push.rs::consumer_death_is_logged_once_a_minute_per_label`<br>`tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval` | yok |
| `test_web_hosts_term_relay.py::TermRelayTests.test_intentional_stop_is_not_logged_as_death` | 184 | karşılandı | `tests/fake_ws.rs::silent_relay_is_restarted_after_45s_without_serving_the_stale_frame`<br>`tests/fake_ws.rs::idle_relays_are_reaped_and_their_sockets_closed` | yok |
| `test_web_hosts_term_relay.py::TermRelayTests.test_lite_relay_asks_the_remote_for_lite_frames` | 207 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set` | yok |
| `test_web_hosts_term_relay.py::TermRelayTests.test_plain_relay_does_not_send_lite` | 216 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set` | yok |
| `test_web_hosts_term_relay.py::TermRelayTests.test_lite_flag_false_is_the_default_and_matches_the_plain_key` | 222 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set` | yok |
| `test_web_hosts_term_relay.py::TermRelayTests.test_lite_and_plain_are_separate_relays_with_separate_frames` | 226 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set` | yok |
| `test_web_hosts_term_relay.py::TermRelayTests.test_two_lite_consumers_share_one_remote_stream` | 240 | karşılandı | `tests/fake_ws.rs::term_relay_streams_frames_and_keeps_one_stream_per_option_set` | yok |
| `test_web_hosts_term_relay.py::TermRelayTests.test_lite_relay_death_is_logged_under_its_own_label` | 249 | karşılandı | `push.rs::consumer_death_is_logged_once_a_minute_per_label`<br>`tests/fake_ws.rs::dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval` | yok |

### `py/tests/test_web_orch_remote_fatal.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_web_orch_remote_fatal.py::RemoteFatal.test_fatal_gives_up_on_first_poll` | 22 | kapsam dışı | yok | orkestrasyon uzak bekleme. İz: T10 (değnekçi) |
| `test_web_orch_remote_fatal.py::RemoteFatal.test_transient_retries_until_threshold` | 28 | kapsam dışı | yok | orkestrasyon uzak bekleme. İz: T10 (değnekçi) |

### `py/tests/test_web_review_tick.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_web_review_tick.py::TestReviewerSmalls.test_report_file_is_private` | 64 | kapsam dışı | yok | reviewer tick. İz: T8 (reviewer) |
| `test_web_review_tick.py::TestReviewerSmalls.test_cfg_lang_reaches_run_job` | 69 | kapsam dışı | yok | reviewer tick. İz: T8 (reviewer) |
| `test_web_review_tick.py::TestTick.test_pool_autofills_and_starts_one_job_at_a_time` | 84 | kapsam dışı | yok | reviewer tick. İz: T8 (reviewer) |
| `test_web_review_tick.py::TestTick.test_remote_project_skipped` | 95 | kapsam dışı | yok | reviewer tick. İz: T8 (reviewer) |
| `test_web_review_tick.py::TestTick.test_disabled_identity_starts_nothing_and_cancels` | 103 | kapsam dışı | yok | reviewer tick. İz: T8 (reviewer) |
| `test_web_review_tick.py::TestTick.test_disabled_project_cancels_running_job` | 119 | kapsam dışı | yok | reviewer tick. İz: T8 (reviewer) |
| `test_web_review_tick.py::TestTick.test_readded_project_resumes_skipping_done_pairs` | 132 | kapsam dışı | yok | reviewer tick. İz: T8 (reviewer) |
| `test_web_review_tick.py::TestTick.test_drain_finishes_running_job_but_starts_nothing_new` | 146 | kapsam dışı | yok | reviewer tick. İz: T8 (reviewer) |
| `test_web_review_tick.py::TestTick.test_min_gap_blocks_start` | 163 | kapsam dışı | yok | reviewer tick. İz: T8 (reviewer) |
| `test_web_review_tick.py::TestTick.test_recover_once_and_missing_cwd_skipped_and_no_targets` | 173 | kapsam dışı | yok | reviewer tick. İz: T8 (reviewer) |
| `test_web_review_tick.py::TestModelsFailure.test_current_targets_swallows_errors` | 190 | kapsam dışı | yok | reviewer tick. İz: T8 (reviewer) |

### `py/tests/test_web_term_fetch.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_web_term_fetch.py::RemoteQueryTests.test_lite_is_only_added_when_requested` | 36 | kapsam dışı | yok | terminal kare alma (yerel kırpma, relay seçimi çağıranı). İz: T2 (terminal) |
| `test_web_term_fetch.py::FetchFnTests.test_local_plain_frame_is_untouched` | 68 | kapsam dışı | yok | terminal kare alma (yerel kırpma, relay seçimi çağıranı). İz: T2 (terminal) |
| `test_web_term_fetch.py::FetchFnTests.test_local_lite_frame_is_trimmed_to_the_visible_rows` | 72 | kapsam dışı | yok | terminal kare alma (yerel kırpma, relay seçimi çağıranı). İz: T2 (terminal) |
| `test_web_term_fetch.py::FetchFnTests.test_remote_rest_lite_forwards_lite_to_the_host` | 81 | kapsam dışı | yok | terminal kare alma (yerel kırpma, relay seçimi çağıranı). İz: T2 (terminal) |
| `test_web_term_fetch.py::FetchFnTests.test_remote_rest_plain_does_not_send_lite` | 87 | kapsam dışı | yok | terminal kare alma (yerel kırpma, relay seçimi çağıranı). İz: T2 (terminal) |
| `test_web_term_fetch.py::FetchFnTests.test_remote_lite_frame_is_not_trimmed_twice` | 92 | kapsam dışı | yok | terminal kare alma (yerel kırpma, relay seçimi çağıranı). İz: T2 (terminal) |
| `test_web_term_fetch.py::FetchFnTests.test_old_remote_that_ignores_lite_is_trimmed_locally` | 97 | kapsam dışı | yok | terminal kare alma (yerel kırpma, relay seçimi çağıranı). İz: T2 (terminal) |
| `test_web_term_fetch.py::FetchFnTests.test_remote_error_frames_pass_through_untouched` | 103 | kapsam dışı | yok | terminal kare alma (yerel kırpma, relay seçimi çağıranı). İz: T2 (terminal) |
| `test_web_term_fetch.py::FetchFnTests.test_remote_ws_tier_asks_the_relay_for_lite` | 111 | kapsam dışı | yok | terminal kare alma (yerel kırpma, relay seçimi çağıranı). İz: T2 (terminal) |
| `test_web_term_fetch.py::FetchFnTests.test_remote_ws_tier_plain_uses_the_plain_relay_and_no_wrapper` | 119 | kapsam dışı | yok | terminal kare alma (yerel kırpma, relay seçimi çağıranı). İz: T2 (terminal) |
| `test_web_term_fetch.py::FetchFnTests.test_grpc_tier_full_frames_are_still_trimmed_locally` | 125 | kapsam dışı | yok | terminal kare alma (yerel kırpma, relay seçimi çağıranı). İz: T2 (terminal) |

### `py/tests/test_ws_grpc_peer_guard.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ws_grpc_peer_guard.py::WsGuardTest.test_dns_name_resolving_to_loopback_is_refused_and_socket_closed` | 25 | karşılandı | `tests/fake_ws.rs::dns_name_resolving_to_loopback_is_refused_for_ws_before_connecting` | yok |
| `test_ws_grpc_peer_guard.py::WsGuardTest.test_public_ip_passes_socket_to_ws_connect` | 34 | karşılandı | `tests/fake_ws.rs::dns_name_resolving_to_loopback_is_refused_for_ws_before_connecting` | yok |
| `test_ws_grpc_peer_guard.py::WsGuardTest.test_ip_literal_skips_the_pre_connect` | 41 | karşılandı | `tests/fake_ws.rs::dns_name_resolving_to_loopback_is_refused_for_ws_before_connecting` | yok |
| `test_ws_grpc_peer_guard.py::GrpcGuardTest.test_blocked_resolution_refused` | 49 | karşılandı | `tests/fake_grpc.rs::grpc_dns_name_resolving_to_loopback_is_refused_before_connecting` | yok |
| `test_ws_grpc_peer_guard.py::GrpcGuardTest.test_unresolvable_is_fail_closed` | 55 | karşılandı | `tests/fake_grpc.rs::grpc_unresolvable_name_is_fail_closed` | yok |
| `test_ws_grpc_peer_guard.py::GrpcGuardTest.test_public_and_literal_pass` | 60 | karşılandı | `tests/fake_grpc.rs::grpc_probe_needs_transport_token_and_service_and_tier_moves_like_python` | yok |
