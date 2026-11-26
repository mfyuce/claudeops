"""Eşleme tablosu (sahip eki "İŞLEVCE EŞLİK"): `docs/rs-hosts-mapping.md` üretir ve denetler.

Koşum (repo kökünden):
  python3 -I rust/crates/cops-hosts/tools/mapping.py            tabloyu yazar
  python3 -I rust/crates/cops-hosts/tools/mapping.py --check    tabloyu `ast` çıktısı ve Rust kaynağıyla karşılaştırır
  python3 -I rust/crates/cops-hosts/tools/mapping.py --pins     dosya özetlerini basar (gözden geçirmeden sonra)

`py/` modülleri İÇE AKTARILMAZ: yalnız dosya okunup `ast` ile ayrıştırılır. Yazılan tek dosya tablodur.
`--check` sıfırdan farklı çıkar: `ast`te olup tabloda olmayan satır, tabloda olup `ast`te olmayan satır, boş hücre,
kaynakta bulunmayan Rust adı ya da testi, bayat tablo ya da bayat eşleme verisi. AÇIK satırlar `--check`i düşürmez
(sayılır ve listelenir); `--check --strict` AÇIK varsa da düşer.

Eşleme verisi ELLE girilir (yukarıdaki `ast` listesi değil):
- tanımlar: her `ast` adı tek tek yazılır;
- crate'in davranışına değen Python testleri tek tek yazılır;
- crate'in davranışını sınamayan test dosyaları dosya başına (gerekçe, iz, sayı + ad özeti) yazılır. Dosyaya test
  eklenir, silinir ya da adı değişirse özet tutmaz ve betik durur (dosya yeniden gözden geçirilmeli).
"""
from __future__ import annotations

import ast
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CRATE = HERE.parent
REPO = HERE.parents[3]
PKG = REPO / "py" / "claudeops"
TESTS = REPO / "py" / "tests"
OUT = REPO / "docs" / "rs-hosts-mapping.md"

OK, OOS, GAP = "karşılandı", "kapsam dışı", "AÇIK"

# ── kapsam ───────────────────────────────────────────────────────────────────
FULL = ["commands/web_hosts.py", "hosts.py", "commands/web_grpc.py"]
# `web_steward.py`: uzak/host/yetenek/geri çekilme adlı HER tanım (crate'in karşıladıkları + T10'a kalanlar).
STEWARD = "commands/web_steward.py"
STEWARD_RE = re.compile(r"(?i)remote|host|caps|facts|backoff|backing_off|transport|_HEALTH|_RECOVERED_DOWN")
# `authz.py`: yalnız giden istek imzası ve iş parçacığına bağlı kimlik (Rust `Caller`).
AUTHZ = "authz.py"
AUTHZ_NAMES = ["outbound_service_headers", "has_outbound_signer", "OutboundRefused", "OutboundRefused.__init__",
               "_OUTBOUND_SIGNER", "set_outbound_signer", "outbound_headers", "bind_principal", "current_principal"]
TEST_IMPORT = re.compile(r"claudeops\.(hosts|commands\.web_hosts|commands\.web_grpc|proto)(\.|$)")
TEST_SYMBOL = re.compile(
    r"\b(_remote_post|_remote_stop|_probe_facts|_caps_put|_caps_cached|host_capabilities|_HOST_HEALTH|"
    r"_remote_tick_done|_is_transport_error|_remote_files_gate|_remote_running_row|_remote_named_rows|_host_fresh|"
    r"_clear_backoff|_backing_off|_RemoteTick|remote_health|outbound_headers|outbound_service_headers|"
    r"set_outbound_signer|has_outbound_signer|web_hosts|hosts_mod|web_grpc)\b")

# ── izler ────────────────────────────────────────────────────────────────────
W0A = "W0-a durum (rs/state)"
GATE = "W0-c kapı (rs/gate) / copsd uç bağlama (cops)"
T1, T2, T3, T4 = "T1 (durum)", "T2 (terminal)", "T3 (dosya)", "T4 (yaşam döngüsü)"
T6, T7, T8, T9, T10 = "T6 (CLI)", "T7 (periyodik)", "T8 (reviewer)", "T9 (enterprise)", "T10 (değnekçi)"
SRV = "T5 sunucu rolü (uzak panelin kendi gRPC sunucusu; copsd'de ayrı iş, bu crate istemci)"


def ok(names, rust, tests, note=""):
    return (names.split(), OK, rust, tests, note)


def oos(names, why, track):
    return (names.split(), OOS, "", "", f"{why}. İz: {track}")


def gap(names, why, rust="", tests=""):
    return (names.split(), GAP, rust, tests, why)


# Test önekleri: U: crate içi birim testi (`src/<dosya>`), I: entegrasyon testi (`tests/<dosya>`).
PAR = "I:parity.rs::"
P_ROUTES = PAR + "host_routed_route_sets_equal_python_source"
P_AUTHZ = PAR + "host_routed_paths_have_the_same_authz_action_as_python"
P_CONST = PAR + "shared_constants_and_error_texts_equal_python"
P_ADDR = PAR + "address_filters_match_python"
P_SAVE = PAR + "save_host_validation_and_upsert_match_python"
P_RED = PAR + "status_reduction_matches_python"
P_WS = PAR + "ws_frames_match_python"
P_POLL = PAR + "poll_cache_tier_and_merge_match_python"
P_STEW = PAR + "steward_client_parts_match_python"
P_PB = PAR + "grpc_messages_match_proto_text_and_python_descriptors"
P_WIRE = PAR + "grpc_wire_decoding_matches_python_conversion"
P_ID = PAR + "input_id_rule_is_python_or_stricter"
FP = "I:fake_poller.rs::"
FH = "I:fake_health.rs::"
FX = "I:fake_proxy.rs::"
FT = "I:fake_http.rs::"
FW = "I:fake_ws.rs::"
FG = "I:fake_grpc.rs::"
FS = "I:fake_tls.rs::"
FR = "I:fake_restart.rs::"

# ── tanım eşlemesi ───────────────────────────────────────────────────────────
DEFS: dict = {}

DEFS["hosts.py"] = [
    oos("HOSTS_JSON", "dosya yolu ve okuma/yazma çağıranın (`HostSource`)", W0A),
    ok("LOCAL_HOST_NAME", "consts.rs::LOCAL_HOST_NAME", f"{P_CONST} U:record.rs::validation_order"),
    ok("_NAME_RE", "record.rs::valid_name", f"U:record.rs::validation_order {P_SAVE}"),
    ok("ERR _err", "record.rs::RecordError::message", f"{P_CONST} {P_SAVE}", "bilinmeyen dil = tr (Python gibi)"),
    ok("_host_is_blocked", "guard.rs::host_is_blocked guard.rs::host_is_blocked_via",
       f"U:guard.rs::legacy_ipv4_forms_are_blocked_at_registration "
       f"U:guard.rs::hung_or_failed_resolution_fails_open_and_loopback_is_blocked {P_SAVE}"),
    ok("LOOPBACK_REACH_DEFAULT", "guard.rs::LOOPBACK_REACH_DEFAULT", f"{P_CONST} U:guard.rs::reach_ports_setting"),
    ok("reach_loopback_ports", "guard.rs::reach_loopback_ports", f"U:guard.rs::reach_ports_setting {P_ADDR}",
       "ayar okuma çağıranın (`HostSource::reach_ports`)"),
    ok("_is_reach_loopback", "guard.rs::is_reach_loopback", f"U:guard.rs::reach_ports_setting {P_ADDR}"),
    ok("DNS_CHECK_TIMEOUT", "guard.rs::DNS_CHECK_TIMEOUT", P_CONST),
    ok("_resolve_with_timeout _resolve_with_timeout.run", "guard.rs::host_is_blocked_via",
       "U:guard.rs::hung_or_failed_resolution_fails_open_and_loopback_is_blocked",
       "iş parçacığı yerine tokio zaman aşımı"),
    ok("ip_is_blocked", "guard.rs::ip_is_blocked", f"U:guard.rs::blocked_ranges {P_ADDR}"),
    ok("hostname_is_dns_name", "endpoint.rs::host_is_dns_name", f"U:endpoint.rs::parses_common_forms {P_ADDR}",
       "kapsam (`%eth0`) farkı belgeli (parity bilinen fark)"),
    ok("load_hosts", "record.rs::parse_document record.rs::parse_value",
       f"U:record.rs::corrupt_and_irregular_documents {FP}irregular_host_records_are_skipped_by_the_poller",
       "dosya/DB okuma W0-a; Rust adı metin olmayan kaydı da düşürür (Python `'name' in h`)"),
    ok("_read_checked", "record.rs::parse_document record.rs::Parsed.corrupt",
       f"U:record.rs::corrupt_and_irregular_documents {P_SAVE}", "dosya/DB seçimi W0-a"),
    oos("_db_mode", "durum deposu kipi (`statedocs`)", W0A),
    oos("_backup_corrupt", "bozuk dosya yedeği; Rust yalnız işaret verir (`Parsed.corrupt`/`irregular`)", W0A),
    ok("_has_irregular_entries", "record.rs::Parsed.irregular", "U:record.rs::corrupt_and_irregular_documents"),
    oos("_load_for_write", "kilit altında okuma", W0A),
    ok("get_host", "record.rs::find", f"{FX}unknown_host_sends_nothing_and_does_not_sign"),
    oos("_write_hosts _write_txn _txn _txn.wrapper", "atomik yazım ve kilit", W0A),
    ok("save_host", "record.rs::Draft::new record.rs::Draft::apply",
       f"U:record.rs::validation_order U:record.rs::upsert_keeps_token_and_unknown_fields_clears_optionals {P_SAVE}",
       "yazım W0-a; denetim karakterli token Rust'ta red (daha sıkı); eksik `base_url`li kayıt yazımı parity bilinen fark"),
    ok("save_host::re1", "record.rs::Draft::new", f"{P_SAVE}", "`[,\\n]+` bölme"),
    ok("promote_base_url", "record.rs::promote_base_url",
       f"U:record.rs::promote_and_remove {FP}extra_urls_fallback_runs_on_threshold_and_every_twentieth_failure"),
    ok("remove_host", "record.rs::remove", "U:record.rs::promote_and_remove"),
    ok("list_hosts_public", "record.rs::HostRecord::public",
       f"U:record.rs::unknown_fields_survive_and_token_never_public {FP}public_rows_never_carry_the_token"),
]

_GRPC_PRB = f"{FG}grpc_probe_needs_transport_token_and_service_and_tier_moves_like_python"
_GRPC_ST = f"{FG}grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest"
_GRPC_TERM = f"{FG}grpc_term_relay_serves_frames_and_error_updates"
DEFS["commands/web_grpc.py"] = [
    oos("_GRPC_MAX_WORKERS _STATUS_TICK_SECONDS _STATUS_DICT_KEYS _reduce_status _dict_to_session_row "
        "_cli_options_to_proto _extras_to_proto _status_dict_to_proto _term_dict_to_proto",
        "sunucu tarafı (dict -> proto, yayın kadansı)", SRV),
    oos("_AuthInterceptor _AuthInterceptor.__init__ _AuthInterceptor._authorized _AuthInterceptor.intercept_service "
        "_deny_unary _deny_stream _HostBridgeServicer _HostBridgeServicer.__init__ _HostBridgeServicer.Ping "
        "_HostBridgeServicer.StreamStatus _HostBridgeServicer.StreamTermOutput start_grpc_server",
        "sunucu tarafı (kimlik denetimi, servis)", SRV),
    ok("_OPTIONAL_SESSION_FIELDS _session_row_to_dict", "grpc.rs::session_row_to_value", f"{P_WIRE} {_GRPC_ST}"),
    ok("_PB_HAS_UCLI_FLAGS", "grpc.rs::SessionRow", f"{P_PB} {P_WIRE}",
       "Rust mesajı 19-21 alanlarını hep bilir (Python pb2 bayatsa yok sayar; pb2 güncel, parity denetler)"),
    ok("_OPTIONAL_TERM_FIELDS _term_proto_to_dict", "grpc.rs::term_to_value", f"{P_WIRE} {_GRPC_TERM}"),
    ok("_cli_options_from_proto _extras_from_proto _status_proto_to_dict", "grpc.rs::status_to_value",
       f"{P_WIRE} {_GRPC_ST}"),
    ok("_EXTRA_KEYS", "grpc.rs::EXTRA_KEYS", f"{P_CONST} {P_WIRE}"),
    ok("_KEEPALIVE_OPTIONS", "grpc.rs::GrpcClient::channel", P_CONST, "20 sn / 5 sn / boştayken açık"),
    ok("_channel_lock _channels", "grpc.rs::GrpcClient.channels",
       f"{FG}dropped_grpc_consumers_cancel_streams_and_removed_hosts_close_the_channel",
       "Rust kaydı silinen adresin kanalını bırakır (Python tutar)"),
    ok("_check_grpc_host", "net.rs::Connector::tcp",
       f"{FG}grpc_dns_name_resolving_to_loopback_is_refused_before_connecting {FG}grpc_unresolvable_name_is_fail_closed",
       "denetim her bağlanışta (Python yalnız kanal kurulurken)"),
    ok("_channel_for", "grpc.rs::GrpcClient::channel",
       f"{FS}grpc_over_https_works_through_own_dial_and_origin {FS}grpc_plain_http_sends_http_scheme"),
    ok("_stub_for", "grpc.rs::GrpcClient::ready", _GRPC_PRB),
    ok("_auth_metadata", "grpc.rs::GrpcClient::request", _GRPC_PRB),
    ok("probe", "grpc.rs::GrpcClient::probe", _GRPC_PRB),
    ok("open_status_stream stream_status", "grpc.rs::GrpcClient::status_stream", _GRPC_ST),
    ok("open_term_stream stream_term_output", "grpc.rs::GrpcClient::term_stream", _GRPC_TERM),
]

_POOL = f"{FT}pool_reuses_one_keepalive_connection"
_STALE_GET = f"{FT}stale_pooled_get_is_retried_once_with_fresh_signature"
_STALE_POST = f"{FT}stale_pooled_post_that_reached_server_is_not_retried"
_IDLE_CLOSE = f"{FT}server_closed_idle_connection_does_not_fail_post"
_DNS_REST = f"{FX}secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked"
_DNS_WS = f"{FW}dns_name_resolving_to_loopback_is_refused_for_ws_before_connecting"
_DEDUP = f"{FX}concurrent_same_url_sends_one_request_and_reuses_last_good"
_TOL = f"{FP}consecutive_failures_are_tolerated_then_rows_are_kept_stale"
_MAL = f"{FP}malformed_remote_status_is_an_error_or_reduced_to_empty_fields"
_PUSH = f"{FW}poller_skips_rest_only_while_a_live_push_stream_has_delivered_data"
_SIL = f"{FW}status_silence_watchdog_boundary"
_JUNK = f"{FW}junk_frames_keep_the_stream_alive_but_rest_polling_continues"
_RELAY = f"{FW}term_relay_streams_frames_and_keeps_one_stream_per_option_set"
_DEAD = f"{FW}dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval"
_SILR = f"{FW}silent_relay_is_restarted_after_45s_without_serving_the_stale_frame"
_REAP = f"{FW}idle_relays_are_reaped_and_their_sockets_closed"
_STALL = f"{FR}stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers"
_PANIC = f"{FR}panicking_turn_is_counted_and_the_poller_keeps_running"
_RUN = f"{FP}dropping_running_stops_poller_and_prober"
_WSPROBE = f"{FW}ws_probe_raises_tier_at_once_and_lowers_it_only_after_tolerance"
DEFS["commands/web_hosts.py"] = [
    ok("HOST_ROUTED_PATHS", "consts.rs::HOST_ROUTED_PATHS", f"{P_ROUTES} {P_AUTHZ}"),
    ok("SECRET_BODY_PATHS", "consts.rs::SECRET_BODY_PATHS", f"{P_ROUTES} {_DNS_REST}"),
    ok("_secret_safe_url", "guard.rs::secret_safe_url", f"U:guard.rs::secret_urls {P_ADDR}"),
    ok("GET_HOST_ROUTED_PATHS", "consts.rs::GET_HOST_ROUTED_PATHS", f"{P_ROUTES} {P_AUTHZ}"),
    ok("FILE_DOWNLOAD_PATH FILE_UPLOAD_PATH", "consts.rs::FILE_DOWNLOAD_PATH consts.rs::FILE_UPLOAD_PATH",
       f"{P_ROUTES} {P_AUTHZ}"),
    ok("STATUS_TIMEOUT_SECONDS TERM_READ_TIMEOUT_SECONDS ACTION_TIMEOUT_SECONDS", "consts.rs::Timeouts",
       f"{P_CONST} {FT}silent_server_times_out_and_socket_is_closed",
       "Rust'ta adım başı sınır + 600 sn mutlak tavan (belgeli fark)"),
    ok("POLL_INTERVAL_SECONDS", "consts.rs::POLL_INTERVAL", f"{P_CONST} {FP}poller_beat_age_stays_within_one_interval"),
    ok("_EMPTY_REMOTE", "status.rs::HostStatus::failed", f"{P_RED} {P_POLL}"),
    ok("_CONN_POOL_MAX_IDLE", "http.rs::POOL_MAX_IDLE", f"{P_CONST} {_POOL}"),
    ok("_conn_pool_lock _conn_pool", "http.rs::Pool.idle", _POOL),
    ok("_inflight_lock _inflight_starts", "flight.rs::Flights::begin",
       f"U:flight.rs::busy_returns_last_good_and_releases_on_drop {_DEDUP}",
       "anahtarda kullanıcı kimliği (belgeli fark)"),
    ok("_dedup_last_good _DEDUP_LAST_GOOD_MAX _remember_good", "flight.rs::Flight::remember flight.rs::LAST_GOOD_MAX",
       f"U:flight.rs::lru_is_bounded_and_keeps_recent {P_CONST}"),
    ok("_INFLIGHT_MAX_SECONDS", "flight.rs::INFLIGHT_MAX",
       f"U:flight.rs::stale_flight_is_replaced_and_old_drop_does_not_free_new {P_CONST}"),
    ok("_split_url", "endpoint.rs::Endpoint::parse proxy.rs::target",
       f"{FX}outgoing_host_is_forced_local_and_caller_query_is_filtered"),
    ok("_pool_key", "endpoint.rs::Endpoint::pool_key", _POOL),
    ok("_BlockedPeer", "net.rs::blocked_error", f"{_DNS_REST} {_DNS_WS}"),
    ok("_check_peer", "net.rs::Connector::tcp", f"{_DNS_REST} {_DNS_WS}",
       "denetim bağlanmadan ÖNCE (çözülen adres = bağlanılan adres)"),
    ok("_GuardedHTTPConnection _GuardedHTTPConnection.connect _GuardedHTTPSConnection "
       "_GuardedHTTPSConnection.connect _conn_cls_for", "net.rs::Connector::connect",
       f"{FS}wss_and_https_rest_work_with_a_custom_root {_DNS_REST}"),
    ok("_guarded_ws_connect", "ws.rs::HostClient::ws_connect", f"{_DNS_WS} {FW}ws_message_limit_is_16_mib_exactly",
       "Python `close_timeout` 1,5 sn: Rust düşürmede beklemez (görev iptal, soket kapanır), yoklamada kapanış 1 sn"),
    ok("_conn_is_alive", "http.rs::Pool::checkout", _IDLE_CLOSE),
    ok("_pool_checkout _pool_checkin", "http.rs::Pool::checkout http.rs::Pool::checkin", f"{_POOL} {_IDLE_CLOSE}"),
    ok("REFUSED_PREFIX", "proxy.rs::CallError", P_CONST),
    ok("_refused", "proxy.rs::refused_reply", f"{FX}signer_refusal_panic_and_bad_headers_are_502_and_nothing_is_sent"),
    ok("_ws_signed_kw", "proxy.rs::HostClient::sign_service",
       f"{FW}ws_handshake_carries_a_fresh_panel_signature_per_connection"),
    ok("_signed_headers", "proxy.rs::HostClient::sign",
       f"{FX}user_caller_is_signed_over_path_and_body_without_query {FX}unbound_caller_is_never_signed",
       "host adı kayıttan (Python base_url eşleşmesinden; belgeli fark)"),
    ok("_http_json", "proxy.rs::HostClient::json proxy.rs::HostClient::exchange http.rs::Pool::attempt",
       f"{_STALE_GET} {_STALE_POST} {FT}non_json_non_object_and_error_statuses {_DEDUP}"),
    ok("_CLI_OPTIONS_FIELDS", "status.rs::CLI_OPTION_FIELDS", P_RED),
    ok("_normalize_cli_options", "status.rs::normalize_cli_options", f"{P_RED} {_MAL}"),
    ok("_orphan_brief", "status.rs::orphan_brief", f"{P_RED} {FP}non_finite_orphan_count_fails_only_that_host",
       "Python `int(x or 0)` kuralı; sonsuz sayıda Python yalnız alanı atar, Rust tüm yanıtı reddeder (serde)"),
    ok("_build_running", "status.rs::build_running", P_RED),
    ok("_fwd_brief", "status.rs::fwd_brief", P_RED,
       "metin/nesne `kids` Python'da karaktere/anahtara bölünür, Rust `fwd`i yok sayar (Python bulgusu, parity bilinen fark)"),
    ok("_tag_rows", "status.rs::tag_rows", f"{P_RED} {_MAL}"),
    ok("_finalize_remote_result", "status.rs::finalize", f"{P_RED} {_MAL}",
       "dizi olmayan `cli_list`/`dups` Python'da olduğu gibi geçer, Rust boş dizi (Python bulgusu)"),
    ok("_fetch_status_from", "federation.rs::Federation::status_from", _MAL, "2xx dışı yanıt hata (belgeli fark)"),
    ok("fetch_remote_status", "federation.rs::Federation::fetch_status", f"{_MAL} {_TOL}"),
    ok("FALLBACK_TIMEOUT_SECONDS", "consts.rs::Timeouts", P_CONST),
    ok("_is_private_lan_http", "guard.rs::is_private_lan_http", P_ADDR,
       "Rust yalnız RFC1918 + ULA (Python `is_private` geniş; parity bilinen fark, daha sıkı)"),
    ok("_candidate_allowed", "guard.rs::candidate_allowed",
       f"U:guard.rs::https_never_downgrades_to_public_http {P_ADDR} {FP}https_base_never_falls_back_to_plain_http"),
    ok("_apply_probe_choice", "federation.rs::Federation::apply_probe_choice",
       f"{FP}probe_choice_only_promotes_registered_allowed_candidates",
       "seçim deposu (`host_probe`) T7; Rust yalnız kayıtlı ve izinli adayı terfi ettirir"),
    ok("_try_fallback_urls", "federation.rs::Federation::try_fallback_urls",
       f"{FP}extra_urls_fallback_runs_on_threshold_and_every_twentieth_failure "
       f"{FP}https_base_never_falls_back_to_plain_http {FP}host_without_extra_urls_never_tries_a_fallback"),
    ok("_cache_lock _cache _last_good _apply_stale_while_error _record_poll_result", "status.rs::StatusBook::record",
       f"{_TOL} {P_POLL}"),
    ok("CONSECUTIVE_FAILURES_BEFORE_ERROR", "consts.rs::CONSECUTIVE_FAILURES_BEFORE_ERROR", f"{P_CONST} {_TOL}"),
    ok("STATUS_PUSH_SILENCE_SECONDS", "consts.rs::STATUS_PUSH_SILENCE", f"{P_CONST} {_SIL}"),
    ok("_last_try_at", "status.rs::StatusBook::last_try_at", f"{_TOL} {P_STEW}"),
    ok("_fail_streak", "status.rs::StatusBook::fail_streak", f"{_TOL} {P_POLL}"),
    ok("_last_ok_at", "status.rs::StatusBook::last_ok_at", _TOL),
    ok("_poll_once", "federation.rs::Federation::poll_once federation.rs::Federation::poll_host",
       f"{_TOL} {FP}extra_urls_fallback_runs_on_threshold_and_every_twentieth_failure {_PUSH}",
       "host'lar eşzamanlı (belgeli fark)"),
    ok("POLLER_STALL_SECONDS", "consts.rs::POLLER_STALL", f"{P_CONST} {_STALL}"),
    ok("WATCHDOG_INTERVAL_SECONDS", "consts.rs::WATCHDOG_INTERVAL", P_CONST,
       "Rust'ta ayrı bekçi döngüsü yok: tur zaman aşımı (POLLER_STALL) aynı işi görür, sabit eşitlik için tutulur"),
    ok("_poller_lock _poller_started _poller_gen _poller_thread", "federation.rs::Running", f"{_RUN} {_STALL}"),
    ok("_poller_beat _poller_restarts", "federation.rs::Federation.beat federation.rs::Federation.restarts",
       f"{FP}poller_beat_age_stays_within_one_interval {_STALL} {_PANIC}"),
    ok("_poller_loop _spawn_poller_locked ensure_poller_alive _watchdog_loop start_remote_poller",
       "federation.rs::Federation::start", f"{_STALL} {_PANIC} {_RUN}",
       "takılan tur iptal edilip yeniden başlar (iş parçacığı nesli yerine)"),
    ok("poller_health", "federation.rs::Federation::poller_health", f"{FP}poller_beat_age_stays_within_one_interval {_STALL}"),
    ok("_PROBE_MIN_GAP_SECONDS _probe_at _probe_lock probe_host", "federation.rs::Federation::probe_host consts.rs::PROBE_MIN_GAP",
       f"{FP}probe_host_is_rate_limited_and_records_like_the_poller {P_CONST}"),
    ok("last_try_at get_cached last_ok_at",
       "status.rs::StatusBook::last_try_at status.rs::StatusBook::cached status.rs::StatusBook::last_ok_at",
       f"{_TOL} {P_STEW}"),
    ok("test_now", "federation.rs::Federation::test_now", f"{FP}test_now_returns_the_fresh_result_not_the_smoothed_one"),
    ok("merge_status merge_status._text merge_status._row_key", "status.rs::StatusBook::merge_status",
       f"{FP}merge_status_resorts_globally_and_keeps_host_rows {P_POLL}",
       "ayar `fleet_sort` çağıranın (`sort_by_cwd`)"),
    ok("proxy_action", "proxy.rs::HostClient::proxy_action",
       f"{FX}outgoing_host_is_forced_local_and_caller_query_is_filtered {_DNS_REST}"),
    ok("TERM_RETRY_PATHS TERM_ATTEMPT_TIMEOUT TERM_MAX_ATTEMPTS",
       "consts.rs::TERM_RETRY_PATHS consts.rs::Timeouts consts.rs::TERM_MAX_ATTEMPTS",
       f"{P_ROUTES} {P_CONST} {FX}term_input_retries_three_times_with_same_input_id"),
    ok("proxy_term_action", "proxy.rs::HostClient::proxy_term_action proxy.rs::valid_input_id",
       f"{FX}term_input_retries_three_times_with_same_input_id {P_ID}",
       "kimlik kuralı Python'dan sıkı: ASCII dışı kimlik yeniden denenmez (yinelenen girdi riski yok)"),
    ok("_http_raw proxy_get_raw", "proxy.rs::HostClient::proxy_get_raw",
       f"{FX}download_passes_raw_body_and_only_two_headers {FX}concurrent_same_download_is_refused_not_cached"),
    ok("proxy_get", "proxy.rs::HostClient::proxy_get",
       f"{FX}outgoing_host_is_forced_local_and_caller_query_is_filtered {_DEDUP}",
       "`token`/`ticket` da süzülür (belgeli fark)"),
    ok("_BoundedReader _BoundedReader.__slots__ _BoundedReader.__init__ _BoundedReader.read", "http.rs::Counted",
       f"{FX}upload_body_ending_early_or_overflowing_is_an_error"),
    ok("proxy_post_raw", "proxy.rs::HostClient::proxy_post_raw",
       f"{FX}slow_but_progressing_upload_is_not_cut {FX}stalled_upload_times_out_and_bad_reply_is_reported",
       "nesne olmayan JSON yanıt Rust'ta `bad response` (Python olduğu gibi döner; daha sıkı)"),
    ok("_TIER_RANK", "tier.rs::Tier", f"U:tier.rs::upgrade_is_immediate_downgrade_is_tolerated {P_POLL}"),
    ok("CAPABILITY_PROBE_INTERVAL_SECONDS", "consts.rs::CAPABILITY_PROBE_INTERVAL", f"{P_CONST} {_RUN}"),
    ok("_GRPC_PROBE_TIMEOUT_SECONDS _WS_PROBE_TIMEOUT_SECONDS", "consts.rs::Timeouts", P_CONST),
    ok("_tier_lock _tier _tier_downgrade_streak _update_tier get_tier",
       "tier.rs::TierBook::update tier.rs::TierBook::get",
       f"U:tier.rs::upgrade_is_immediate_downgrade_is_tolerated {P_POLL} {_WSPROBE}"),
    ok("_ws_url", "ws.rs::HostClient::ws_connect", f"{FW}base_path_is_kept_for_ws_and_signed_over_it",
       "taban yolu korunur (belgeli fark)"),
    ok("_probe_ws", "ws.rs::HostClient::ws_probe", _WSPROBE),
    ok("_probe_tier", "federation.rs::Federation::probe_tier", f"{_WSPROBE} {_GRPC_PRB}"),
    ok("_capability_prober_loop _prober_lock _prober_started start_capability_prober",
       "federation.rs::Federation::start federation.rs::Federation::probe_tiers_once", f"{_RUN} {_REAP}"),
    ok("_CONSUMER_DEATH_LOG_MIN_INTERVAL_SECONDS _consumer_death_log_last _log_consumer_death",
       "consts.rs::CONSUMER_DEATH_LOG_MIN_INTERVAL push.rs::DeathLog::report",
       f"U:push.rs::consumer_death_is_logged_once_a_minute_per_label {P_CONST}"),
    ok("_PushConsumer _PushConsumer.__init__ _PushConsumer._run", "push.rs::PushConsumer::spawn",
       f"{_PUSH} {_JUNK} {_GRPC_ST}"),
    ok("_PushConsumer.is_alive", "push.rs::PushConsumer::is_alive", _PUSH),
    ok("_PushConsumer.silent_seconds", "push.rs::PushConsumer::silent", _SIL),
    ok("_PushConsumer.stop _PushConsumer._close_call", "push.rs::PushConsumer",
       f"{FW}dropped_streams_close_their_sockets_and_leak_no_fds "
       f"{FG}dropped_grpc_consumers_cancel_streams_and_removed_hosts_close_the_channel",
       "durdurma = `Drop` (görev iptal, bağlantı kapanır); kasıtlı durdurma ölüm sayılmaz"),
    ok("_status_consumer_lock _status_consumers", "federation.rs::Federation.consumers", f"{_PUSH} {_SIL}"),
    ok("_bad_frame_log_last", "push.rs::SkipLog",
       f"U:push.rs::skipped_frames_are_logged_at_most_once_a_minute_per_kind {_JUNK}"),
    ok("_ws_envelope", "ws.rs::decode_frame push.rs::SkipLog::report",
       f"{P_WS} {_JUNK} U:push.rs::skipped_frames_are_logged_at_most_once_a_minute_per_kind"),
    ok("_parse_ws_status_frame", "ws.rs::parse_status_frame", f"{P_WS} {_JUNK}"),
    ok("_start_status_consumer _start_status_consumer.on_item", "federation.rs::Federation::start_status_consumer",
       f"{_PUSH} {_GRPC_ST}"),
    ok("_ensure_status_consumer", "federation.rs::Federation::ensure_status_consumer",
       f"{_PUSH} {_SIL} {FW}status_stream_is_rebuilt_when_address_or_token_changes_not_extra_urls"),
    ok("_reap_status_consumers", "federation.rs::Federation::poll_once",
       f"{FW}dropped_streams_close_their_sockets_and_leak_no_fds"),
    ok("_TERM_RELAY_IDLE_TTL_SECONDS _TERM_RELAY_RESTART_MIN_INTERVAL_SECONDS _TERM_RELAY_SILENCE_SECONDS",
       "consts.rs::TERM_RELAY_IDLE_TTL consts.rs::TERM_RELAY_RESTART_MIN_INTERVAL consts.rs::TERM_RELAY_SILENCE",
       f"{P_CONST} {_REAP} {_DEAD} {_SILR}"),
    ok("_TermRelay _TermRelay.__init__ _TermRelay.__init__.on_item _TermRelay.read _TermRelay.idle_seconds",
       "relay.rs::Relay relay.rs::Federation::term_output", f"{_RELAY} {_REAP}"),
    ok("_TermRelay.is_alive _TermRelay.silent_seconds _TermRelay.stop", "relay.rs::Federation::term_output",
       f"{_DEAD} {_SILR}"),
    ok("_term_relay_lock _term_relays", "relay.rs::Relays", f"{_RELAY} {_REAP}"),
    ok("_parse_ws_term_frame", "ws.rs::parse_term_frame", f"{P_WS} {_RELAY}"),
    ok("term_output_relay term_output_relay.fetch_fn", "relay.rs::Federation::term_output",
       f"{_RELAY} {_DEAD} {_SILR} {FW}relay_is_rebuilt_when_the_host_record_changes {_GRPC_TERM}",
       "kayıt değişince yeniden kurulur (belgeli fark); `interval` biçimi belgeli fark"),
    ok("_reap_idle_term_relays", "relay.rs::Relays::reap_idle", _REAP),
]

_T10 = "uzak değnekçi politikası (dünya/sahiplik/görünüm/kart/oturum yönetimi); crate yalnız yapı taşlarını verir"
_FH_BREAK = f"{FH}breaker_opens_after_three_failing_ticks_and_reports_once"
DEFS[STEWARD] = [
    ok("REMOTE_STALE_SECONDS", "health.rs::REMOTE_STALE_SECONDS", f"{P_CONST} {FH}freshness_and_files_gate"),
    ok("MAX_DESTRUCTIVE_PER_HOST", "health.rs::MAX_DESTRUCTIVE_PER_HOST",
       f"{P_CONST} {FH}remote_stop_sends_one_exact_stop_per_host_per_tick"),
    ok("REMOTE_BACKOFF_TICKS REMOTE_BACKOFF_SECONDS", "health.rs::BACKOFF_TICKS health.rs::BACKOFF_SECONDS",
       f"{P_CONST} {_FH_BREAK}"),
    ok("REMOTE_PROBES_PER_TICK", "health.rs::PROBES_PER_TICK", P_CONST,
       "yalnız sabit: tick başına yoklama döngüsü (`_probe_stale_hosts`) T10"),
    ok("REMOTE_CAPS_RECHECK_SECONDS", "health.rs::CAPS_RECHECK_SECONDS",
       f"{P_CONST} {FH}probe_facts_404_caches_old_host_and_stops_asking"),
    oos("REMOTE_READ_BUDGET_SECONDS MAX_REMOTE_CARDS_PER_TICK REMOTE_CARD_BUDGET_SECONDS REMOTE_DESTRUCTIVE_KINDS "
        "REMOTE_STOP_TIMEOUT_SECONDS REMOTE_INPUT_TIMEOUT_SECONDS REMOTE_HANDOVER_TIMEOUT_SECONDS "
        "REMOTE_START_TIMEOUT_SECONDS REMOTE_READY_UNKNOWN_POLLS REMOTE_READY_POLL_SECONDS "
        "REMOTE_BORN_TOLERANCE_SECONDS REMOTE_DENIED_DEDUP_SECONDS REMOTE_GIT_UNKNOWN",
        "değnekçi bütçe/zaman aşımı/politika sabitleri; crate işlevleri süreyi parametre alır", T10),
    ok("_RemoteIO _remote _RemoteIO.status", "status.rs::StatusBook::cached status.rs::StatusBook::last_ok_at",
       f"{_TOL} {P_STEW}", "değnekçinin G/Ç bağdaştırıcısı; Rust karşılığı `Federation` alanları"),
    ok("_RemoteIO.probe", "federation.rs::Federation::probe_host",
       f"{FP}probe_host_is_rate_limited_and_records_like_the_poller"),
    ok("_RemoteIO.get", "proxy.rs::HostClient::proxy_get", f"{FH}probe_facts_reads_caps_and_facts_in_one_request"),
    ok("_RemoteIO.post", "proxy.rs::HostClient::proxy_action", f"{FH}remote_post_breaker_and_error_marking"),
    ok("_host_fresh _fresh_hosts", "health.rs::host_fresh", f"{FH}freshness_and_files_gate {P_STEW}",
       "`_fresh_hosts` döngüsü çağıranın"),
    ok("_HOST_HEALTH _HEALTH_LOCK", "health.rs::Breaker", _FH_BREAK),
    ok("_backing_off", "health.rs::Breaker::backing_off", f"{_FH_BREAK} {FH}probe_success_clears_backoff_immediately"),
    ok("_clear_backoff", "health.rs::Breaker::clear", f"{FH}probe_success_clears_backoff_immediately"),
    ok("_RemoteTick _RemoteTick.failed _RemoteTick.succeeded _RemoteTick.destructive",
       "health.rs::TickState health.rs::TickState.failed health.rs::TickState.succeeded health.rs::TickState.destructive",
       f"{FH}remote_post_breaker_and_error_marking {FH}remote_stop_sends_one_exact_stop_per_host_per_tick"),
    ok("_RemoteTick.blocked", "health.rs::TickState::blocked", f"{FH}remote_post_breaker_and_error_marking"),
    oos("_RemoteTick.now _RemoteTick.statuses _RemoteTick.fresh _RemoteTick.started _RemoteTick.refresh "
        "_RECOVERED_DOWN _probe_stale_hosts _remote_snapshot",
        "tick anlık görüntüsü ve toparlama döngüsü (yapı taşları: `StatusBook::cached`, `host_fresh`, "
        "`Breaker::backing_off/clear`, `Federation::probe_host`)", T10),
    ok("_remote_tick_done", "health.rs::Breaker::settle",
       f"{_FH_BREAK} {FH}breaker_ignores_idle_ticks_and_success_resets_streak",
       "olay yazımı (`remote_unreachable`) çağıranın: `Change` listesi döner"),
    ok("_is_transport_error", "health.rs::is_transport_error", f"{FH}transport_error_classification {P_STEW}"),
    ok("_remote_post", "health.rs::remote_post",
       f"{FH}remote_post_refuses_destructive_paths_and_host_field {FH}remote_post_breaker_and_error_marking",
       "`host`lu gövde Python'da ValueError, Rust hata değeri; yıkıcı yol Rust'ta yalnız `remote_stop` (daha sıkı)"),
    ok("_CAPS _CAPS_LOCK _caps_put _caps_cached", "health.rs::CapabilityCache health.rs::CapabilityCache::cached",
       f"{FH}probe_facts_reads_caps_and_facts_in_one_request {FH}probe_facts_404_caches_old_host_and_stops_asking"),
    ok("_probe_facts", "health.rs::CapabilityCache::probe_facts",
       f"{FH}probe_facts_reads_caps_and_facts_in_one_request {FH}probe_facts_404_caches_old_host_and_stops_asking "
       f"{FH}probe_facts_transient_failure_is_not_cached"),
    ok("host_capabilities", "health.rs::CapabilityCache::host_capabilities health.rs::CAPS_PROBE_TIMEOUT",
       f"{FH}host_capabilities_uses_cache_then_probes_once"),
    ok("remote_health", "health.rs::health_view", f"U:health.rs::health_view_matches_python_remote_health {P_STEW}"),
    ok("_remote_files_gate", "health.rs::files_gate", f"{FH}freshness_and_files_gate"),
    ok("_remote_rows", "health.rs::host_fresh health.rs::Breaker::backing_off health.rs::running_row", P_STEW,
       "tick anlık görüntüsünden okuma (`rt.statuses`) T10"),
    ok("_remote_running_row", "health.rs::running_row",
       f"U:health.rs::running_row_is_exact_truthy_and_ambiguous_is_unknown {P_STEW}"),
    ok("_remote_named_rows", "health.rs::named_running_rows",
       f"U:health.rs::running_row_is_exact_truthy_and_ambiguous_is_unknown {FH}ambiguous_or_inexact_target_sends_nothing"),
    ok("_remote_stop", "health.rs::exact_target health.rs::remote_stop",
       f"{FH}ambiguous_or_inexact_target_sends_nothing {FH}remote_stop_sends_one_exact_stop_per_host_per_tick",
       "projeye göre satır seçimi, `not_own`, `manual`, olay yazımı T10; kodlar Python ile aynı (`no_exact_row`, "
       "`ambiguous_sessions`, `caps_unknown`, `remote_too_old`, `destructive_budget`, `host_down`)"),
    oos("_name_host _remote_last_assistant _remote_last_assistant.work _remote_view _remote_views _remote_views.probe "
        "_apply_facts _DRYABLE_REMOTE _log_remote_denied _remote_denied _target.remote _remote_running_listing "
        "_remote_ref _remote_cwd _remote_file_head _remote_last_exchange _remote_read_context _REMOTE_CARD_CHECKED "
        "_remote_raw_card _transient_host_error _remote_key _remote_project_rows _remote_session _remote_sleep "
        "_remote_wait_ready _ensure_running_remote _remote_oversized_resume remote_resume_warning "
        "_START_BACKOFF_STEPS _start_backoff_remaining _start_backoff_note _remote_born _name_host_in "
        "_refresh_remote_cards _remote_nudge _remote_handover _remote_wait_closed _remote_stop_and_wait "
        "_remote_respawn _remote_respawn.failed _advance_candidates.remote_todo_of _remote_read_full "
        "_remote_append_idea _in_remote_roster _register_remote _REMOTE_CREATABLE _remote_before _remote_edit_doc",
        _T10, T10),
    oos("RemoteReviewDriver RemoteReviewDriver.POLL_STALE_NONE RemoteReviewDriver.__init__ RemoteReviewDriver._owner "
        "RemoteReviewDriver._rows RemoteReviewDriver._project_cwd_remote RemoteReviewDriver._ambiguous "
        "RemoteReviewDriver.ready RemoteReviewDriver.cwd RemoteReviewDriver._wait_closed RemoteReviewDriver.start "
        "RemoteReviewDriver.send RemoteReviewDriver.poll RemoteReviewDriver.read_rel RemoteReviewDriver.export_file "
        "RemoteReviewDriver.sweep RemoteReviewDriver.stop",
        "uzak review oturumu sürücüsü (belirsiz ad kuralı `health::running_row` ile aynı)", T8),
]

DEFS[AUTHZ] = [
    ok("outbound_service_headers", "proxy.rs::HostClient::sign_service",
       f"{FW}ws_handshake_carries_a_fresh_panel_signature_per_connection"),
    ok("has_outbound_signer _OUTBOUND_SIGNER set_outbound_signer", "proxy.rs::HostClient.signer",
       f"{FX}user_caller_is_signed_over_path_and_body_without_query",
       "kayıt noktası yerine alan; enterprise doldurur (T9)"),
    ok("OutboundRefused OutboundRefused.__init__", "sign.rs::OutboundRefused",
       f"{FX}signer_refusal_panic_and_bad_headers_are_502_and_nothing_is_sent"),
    ok("outbound_headers", "sign.rs::headers_for sign.rs::OutboundSigner",
       f"{FX}signer_refusal_panic_and_bad_headers_are_502_and_nothing_is_sent "
       f"{FX}user_caller_is_signed_over_path_and_body_without_query",
       "signer paniği / yasak başlık = RED (Python imzasız gönderir; belgeli fark)"),
    ok("bind_principal current_principal", "sign.rs::Caller",
       f"{FX}unbound_caller_is_never_signed {FX}dedup_key_includes_identity",
       "iş parçacığına bağlı kimlik yerine açık parametre (görevler arası sızma yok)"),
]


# ── Python test eşlemesi ─────────────────────────────────────────────────────
def t_ok(names, tests, note=""):
    return (names.split(), OK, tests, note)


def t_oos(names, why, track):
    return (names.split(), OOS, "", f"{why}. İz: {track}")


def t_gap(names, why, tests=""):
    return (names.split(), GAP, tests, why)


def cls(name, methods):
    return " ".join(f"{name}.{m}" for m in methods.split())


CASES: dict = {}

CASES["test_hosts.py"] = [
    t_oos(cls("ConcurrentWriteTest", "test_parallel_saves_all_survive test_flock_failure_falls_back_to_thread_lock"),
          "hosts.json kilitli yazım", W0A),
    t_ok(cls("ReachLoopbackTest", "test_reach_port_loopback_ok_in_extra_urls test_everything_else_still_blocked"),
         f"U:record.rs::validation_order {P_SAVE}"),
    t_ok("ReachLoopbackTest.test_https_base_may_fall_back_to_reach_loopback",
         f"U:guard.rs::https_never_downgrades_to_public_http {P_ADDR}"),
    t_ok(cls("ReachLoopbackTest", "test_helper test_setting_overrides_ports"), f"U:guard.rs::reach_ports_setting {P_ADDR}"),
    t_oos("DbModeIrregularTest.test_irregular_detected_from_db_not_stale_file", "DB kipi okuma", W0A),
]
CASES["test_hosts_corrupt.py"] = [
    t_ok("CorruptHostsTest.test_save_refused_on_corrupt_and_backup_kept",
         f"U:record.rs::upsert_keeps_token_and_unknown_fields_clears_optionals {P_SAVE}", "yedek dosyası W0-a"),
    t_ok("CorruptHostsTest.test_remove_and_promote_refused_on_corrupt", "U:record.rs::promote_and_remove"),
    t_ok("CorruptHostsTest.test_non_list_json_is_corrupt", f"U:record.rs::corrupt_and_irregular_documents {P_SAVE}"),
    t_ok("CorruptHostsTest.test_missing_or_empty_file_still_writable",
         f"U:record.rs::corrupt_and_irregular_documents {P_SAVE}"),
    t_oos("CorruptHostsTest.test_irregular_entries_backed_up_before_being_dropped",
          "yedekleme; Rust işareti (`Parsed.irregular`) testli", W0A),
    t_ok("CorruptHostsTest.test_healthy_roundtrip_unchanged", "U:record.rs::unknown_fields_survive_and_token_never_public"),
]
CASES["test_hosts_unspecified.py"] = [
    t_ok(cls("UnspecifiedBlockedTest", "test_unspecified_literals_are_blocked test_loopback_still_blocked"),
         f"U:guard.rs::blocked_ranges {P_ADDR} {P_SAVE}"),
]
CASES["test_hosts_dns_timeout.py"] = [
    t_ok(cls("DnsTimeout", "test_hung_resolution_does_not_block_and_fails_open test_loopback_still_blocked_and_gaierror_fails_open"),
         "U:guard.rs::hung_or_failed_resolution_fails_open_and_loopback_is_blocked"),
]
CASES["test_bad_encoding_state_files.py"] = [
    t_oos("BadBytes.test_instances", "instances.json okuma", W0A),
    t_ok("BadBytes.test_hosts", "U:record.rs::corrupt_and_irregular_documents", "UTF-8 olmayan belge = bozuk"),
    t_ok("SaveHostKeepsUnknownFields.test_unknown_field_survives_upsert_and_dns_outside_lock",
         f"U:record.rs::upsert_keeps_token_and_unknown_fields_clears_optionals {P_SAVE}",
         "DNS denetimi `Draft::new`de (kilit dışı), kilit W0-a"),
]
CASES["test_triage_fixes_20261107.py"] = [
    t_ok("HostsDbNonListTest.test_db_mode_non_list_is_corrupt", "U:record.rs::corrupt_and_irregular_documents",
         "`parse_value` dizi olmayan değeri bozuk sayar"),
]
CASES["test_statedocs_hosts_diag.py"] = [
    t_oos(cls("HostsDiagDual", "test_hosts_dual_roundtrip_and_perm test_hosts_hand_edit_wins_in_dual "
              "test_hosts_db_mode_without_file test_diag_log_mirrors"), "durum deposu ayna/DB kipi", W0A),
]
CASES["test_web_hosts_remote_shape.py"] = [
    t_ok(cls("MergeStatusBadFieldsTest", "test_missing_null_or_non_text_name_and_cwd_do_not_break_the_merge "
             "test_unusable_values_sort_as_empty_text"),
         f"{FP}merge_status_resorts_globally_and_keeps_host_rows {P_POLL}"),
    t_ok(cls("RemoteShapeTest", "test_non_object_rows_are_skipped test_non_list_closed_and_retired_are_empty"),
         f"{_MAL} {P_RED}"),
    t_ok("RemoteShapeTest.test_non_list_sessions_is_an_unexpected_shape", _MAL),
    t_ok("RemoteShapeTest.test_one_bad_host_does_not_end_the_poll_turn", f"{_MAL} {_PANIC}",
         "Rust'ta her host ayrı görev: bozuk yanıt hata değeri, panik bile turu düşürmez"),
    t_ok("RemoteShapeTest.test_push_frame_without_a_session_list_is_skipped", f"{_JUNK} {P_WS}"),
    t_ok("RemoteShapeTest.test_non_object_or_unreadable_frame_is_skipped_and_logged_once",
         f"{_JUNK} U:push.rs::skipped_frames_are_logged_at_most_once_a_minute_per_kind {P_WS}"),
]
CASES["test_web_hosts_peer_guard.py"] = [
    t_ok("PeerGuardTest.test_dns_name_resolving_to_loopback_is_refused", _DNS_REST),
    t_ok("PeerGuardTest.test_dns_name_resolving_to_lan_is_allowed", f"U:guard.rs::blocked_ranges {_DNS_WS}",
         "izin kararı `ip_is_blocked` tablosu; DNS adıyla LAN'a gerçek bağlantı testte kurulamaz (loopback dışı yasak)"),
    t_ok("PeerGuardTest.test_ip_literal_is_not_rechecked", _DNS_WS, "IP literali kontrol adımı"),
    t_ok("PeerGuardTest.test_helpers", f"U:guard.rs::blocked_ranges U:endpoint.rs::parses_common_forms {P_ADDR}"),
    t_ok("PeerGuardTest.test_conn_cls_for", f"{FS}wss_and_https_rest_work_with_a_custom_root"),
]
CASES["test_ws_grpc_peer_guard.py"] = [
    t_ok(cls("WsGuardTest", "test_dns_name_resolving_to_loopback_is_refused_and_socket_closed "
             "test_public_ip_passes_socket_to_ws_connect test_ip_literal_skips_the_pre_connect"), _DNS_WS),
    t_ok("GrpcGuardTest.test_blocked_resolution_refused", f"{FG}grpc_dns_name_resolving_to_loopback_is_refused_before_connecting"),
    t_ok("GrpcGuardTest.test_unresolvable_is_fail_closed", f"{FG}grpc_unresolvable_name_is_fail_closed"),
    t_ok("GrpcGuardTest.test_public_and_literal_pass", _GRPC_PRB),
]
CASES["test_web_hosts_keepalive_idle_close.py"] = [
    t_ok("KeepAliveIdleCloseTests.test_peer_closed_idle_connection_is_replaced_silently", _IDLE_CLOSE),
    t_ok("KeepAliveIdleCloseTests.test_race_dead_conn_judged_alive_is_retried_once_without_error", _STALE_GET),
]
CASES["test_web_hosts_close_timeout.py"] = [
    t_ok(cls("CloseTimeoutTest", "test_default_close_timeout_is_short test_explicit_close_timeout_wins"),
         f"{FW}dropped_streams_close_their_sockets_and_leak_no_fds {_WSPROBE}",
         "Rust kapanışta beklemez (görev iptal); yoklama kapanışı 1 sn sınırlı"),
]
CASES["test_http_json_post_no_retry.py"] = [
    t_ok("PostRetryTest.test_post_not_retried_after_send", _STALE_POST),
    t_ok("PostRetryTest.test_post_retried_when_send_failed", _IDLE_CLOSE,
         "`!sent` yolunun kendi başına deterministik sınaması yok (docs/rs-hosts.md iş 1)"),
    t_ok("PostRetryTest.test_get_still_retried_after_send", _STALE_GET),
]
CASES["test_orphan_brief.py"] = [
    t_ok(cls("InfiniteOrphanTest", "test_infinite_counts_are_dropped_like_any_other_bad_shape "
             "test_rest_and_ws_results_survive_an_infinite_count"), f"{FP}non_finite_orphan_count_fails_only_that_host",
         "belgeli fark: Rust tüm yanıtı reddeder, Python yalnız `orphan_watch`ı atar"),
    t_ok(cls("OrphanBriefTest", "test_brief") + " " + cls("FwdBriefTest", "test_brief") + " " +
         cls("BuildRunningTest", "test_build_running"), P_RED),
    t_ok("WsFrameTest.test_ws_frame_keeps_host_badges", f"{P_WS} {P_RED}"),
    t_ok(cls("GrpcExtrasTest", "test_roundtrip_extras test_no_extras_is_clean"), f"{P_WIRE} {_GRPC_ST}",
         "dict -> proto yarısı sunucu tarafı (kapsam dışı)"),
]
CASES["test_remote_capabilities_shape.py"] = [
    t_ok(cls("CapabilitiesShapeTest", "test_text_is_not_split_into_characters "
             "test_other_non_list_values_are_empty_and_do_not_raise test_non_text_items_are_dropped"),
         f"{FH}probe_facts_reads_caps_and_facts_in_one_request"),
]
CASES["test_post_routes_vs_host_routed.py"] = [
    t_oos(cls("PostRoutesVsHostRouted", "test_allowlist_parsed test_every_host_routed_path_is_in_post_allowlist "
              "test_unrouted_post_paths_are_explicit_exceptions test_known_local_only_has_no_stale_entries"),
          "yerel POST route tablosu (`web.py` do_POST) ile host-routed kümenin eşitliği; host-routed küme Rust'ta "
          "`parity::host_routed_route_sets_equal_python_source` ile Python'a bağlı", GATE),
]
CASES["test_usage_byok_host_routed.py"] = [
    t_ok("Routing.test_routed_but_whole_settings_stays_local", P_ROUTES),
    t_ok("Routing.test_byok_needs_admin_config", P_AUTHZ, "eylem adı Python `authz.action_for` ile aynı"),
    t_ok(cls("Routing", "test_secret_not_sent_over_plain_http test_https_loopback_and_status_read_pass"),
         f"{_DNS_REST} U:guard.rs::secret_urls"),
    t_oos(cls("Endpoint", "test_set_read_clear_never_echoes_value test_rejects_bad_input_without_writing"),
          "BYOK ayar ucu (sunucu tarafı)", T7),
]
CASES["test_ucli_checks_host_routing.py"] = [
    t_ok("Routing.test_sets", P_ROUTES),
    t_oos(cls("Routing", "test_get_branches_proxy_when_host_given test_metrics_routed test_compare_routed"),
          "`web.py` GET dalının vekile bağlanması", GATE),
]
CASES["test_web_grpc_ucli_flags.py"] = [
    t_ok(cls("GrpcUcliFlagsTest", "test_roundtrip_never_raises_and_keeps_core_fields test_no_flags_means_none "
             "test_flags_roundtrip test_non_ucli_row_has_no_flags"), P_WIRE,
         "istemci yarısı (proto -> dict) Python pb2 ile kodlanıp Rust'ta çözülür; dict -> proto sunucu tarafı"),
]
CASES["test_host_liveness.py"] = [
    t_ok(cls("SilentConsumerTest", "test_healthy_consumer_keeps_rest_off test_fed01_dead_consumer_restarted_and_rest_used_this_tick "
             "test_fed01_first_start_uses_rest test_fed01_poll_once_records_failure_when_push_dies "
             "test_push_consumer_sets_has_data"), f"{_PUSH} {_JUNK}"),
    t_ok(cls("SilentConsumerTest", "test_silent_but_alive_consumer_replaced_and_rest_used_this_tick "
             "test_replacement_failure_still_stops_old_and_falls_to_rest test_push_consumer_tracks_last_message"), _SIL,
         "Rust'ta tüketici kurulumu eşzamanlı başarısız olamaz (görev); eski tüketici değişimde düşer"),
    t_ok("EnsureConsumerStopOutsideLock.test_silent_old_stopped_without_lock_when_start_fails", _SIL,
         "durdurma `Drop` (iptal), kilitte G/Ç yok"),
    t_ok("PollerWatchdogTest.test_not_started_is_noop", _RUN, "global durum yok: görevler yalnız `start` ile"),
    t_ok("PollerWatchdogTest.test_dead_thread_restarted", _PANIC),
    t_ok(cls("PollerWatchdogTest", "test_stalled_thread_restarted_and_healthy_left_alone test_old_generation_loop_exits"),
         _STALL),
    t_ok(cls("ProbeTest", "test_probe_records_success_and_is_rate_limited test_probe_failure_and_unknown_host "
             "test_probe_never_raises"), f"{FP}probe_host_is_rate_limited_and_records_like_the_poller"),
    t_oos(cls("StewardSideTest", "test_probe_stale_hosts_recovers_and_refreshes test_probe_cap_per_tick_and_errors_swallowed "
              "test_status_line_shows_reason"), "tick toparlama döngüsü ve durum satırı", T10),
    t_ok("StewardSideTest.test_remote_health_gives_reason_and_last_try_when_down",
         f"U:health.rs::health_view_matches_python_remote_health {P_STEW}"),
    t_ok(cls("BackoffRecoveryTest", "test_clear_backoff_resets_breaker test_probe_success_clears_backoff_and_marks_recovered "
             "test_probe_failure_keeps_backoff"), f"{FH}probe_success_clears_backoff_immediately"),
    t_oos(cls("BackoffRecoveryTest", "test_human_not_blocked_by_backoff_when_host_fresh_but_engine_is "
              "test_human_still_denied_when_host_stale") + " " +
          cls("OutageScenarioTest", "test_human_passes_while_backing_off_if_host_fresh"),
          "insan/motor kapısı ayrımı", T10),
    t_ok("BackoffRecoveryTest.test_transport_error_is_logged_with_reason", f"{FH}remote_post_breaker_and_error_marking"),
    t_ok(cls("OutageScenarioTest", "test_outage_backoff_recovery test_sub_threshold_failures_do_not_back_off"),
         f"{_FH_BREAK} {FH}breaker_ignores_idle_ticks_and_success_resets_streak"),
]
CASES["test_web_hosts_term_relay.py"] = [
    t_ok(cls("TermRelayTests", "test_second_tick_does_not_raise_and_pushed_frame_is_delivered test_fresh_relay_is_not_restarted "
             "test_lite_relay_asks_the_remote_for_lite_frames test_plain_relay_does_not_send_lite "
             "test_lite_flag_false_is_the_default_and_matches_the_plain_key "
             "test_lite_and_plain_are_separate_relays_with_separate_frames test_two_lite_consumers_share_one_remote_stream"),
         _RELAY),
    t_ok(cls("TermRelayTests", "test_dead_consumer_is_recreated_and_old_frame_is_not_replayed "
             "test_instantly_dying_consumer_is_not_reconnected_every_tick"), _DEAD),
    t_ok("TermRelayTests.test_silent_half_open_relay_is_restarted_and_logged", _SILR),
    t_ok(cls("TermRelayTests", "test_consumer_death_is_logged_once_per_label test_lite_relay_death_is_logged_under_its_own_label"),
         f"U:push.rs::consumer_death_is_logged_once_a_minute_per_label {_DEAD}"),
    t_ok("TermRelayTests.test_intentional_stop_is_not_logged_as_death", f"{_SILR} {_REAP}"),
]
CASES["test_outbound_signer.py"] = [
    t_ok("OutboundSignerTest.test_no_signer_no_header", f"{FX}unbound_caller_is_never_signed {_POOL}",
         "signer yoksa `headers_for` boş; sahte testlerin çoğu signer'sız istemciyle"),
    t_ok("OutboundSignerTest.test_signer_gets_host_path_and_header_sent_each_call",
         f"{FX}user_caller_is_signed_over_path_and_body_without_query {_STALE_GET}"),
    t_ok("OutboundSignerTest.test_no_principal_no_signing", f"{FX}unbound_caller_is_never_signed"),
    t_ok(cls("OutboundSignerTest", "test_refused_returns_error_without_request test_signer_crash_falls_back_unsigned")
         + " " + cls("Refused502Test", "test_proxy_get_and_action_502"),
         f"{FX}signer_refusal_panic_and_bad_headers_are_502_and_nothing_is_sent",
         "signer çökmesi Python'da imzasız gönderim, Rust'ta RED (belgeli fark, kapalı yön)"),
    t_ok("Refused502Test.test_unreachable_stays_200", f"{FX}error_texts_carry_no_url_port_or_token"),
    t_ok("WsSignedKwTest.test_ws_kw", f"{FW}ws_handshake_carries_a_fresh_panel_signature_per_connection"),
    t_oos("StatusExtraTest.test_extras", "`/api/status` ek alanları (sunucu tarafı)", T1),
    t_oos(cls("PeekBodyTest", "test_peek_then_read_same_bytes test_cache_not_leaked_to_next_request test_too_large_returns_none"),
          "gelen isteğin gövdesini imza doğrulaması için okuma (sunucu tarafı)", T9),
]
CASES["test_steward_remote_facts.py"] = [
    t_oos(cls("TestFactsEndpoint", "test_facts_for_exact_names test_non_claude_has_no_context_or_subagent "
              "test_codex_context_from_provider_live_context test_codex_background_work_reported "
              "test_no_names_gives_capabilities_only"), "`/api/session/facts` ucu (sunucu tarafı)", T10),
    t_ok("TestFactsEndpoint.test_route_is_host_routed", P_ROUTES),
    t_oos(cls("TestExact", "test_stop_exact_requires_full_name test_stop_without_exact_keeps_unique_base "
              "test_term_input_exact test_handover_exact_refuses_before_touching_session test_term_resolve_exact"),
          "uzak panelin `exact` hedef çözümü (sunucu tarafı)", T4),
    t_ok(cls("TestClient", "test_404_caches_api0_and_rechecks_after_ten_minutes test_404_is_not_a_transport_failure"),
         f"{FH}probe_facts_404_caches_old_host_and_stops_asking"),
    t_ok("TestClient.test_network_error_does_not_write_cache", f"{FH}probe_facts_transient_failure_is_not_cached"),
    t_oos(cls("TestClient", "test_view_enriched_from_facts_single_request "
              "test_empty_facts_last_assistant_falls_back_to_term_chat_but_keeps_facts "
              "test_facts_missing_for_a_session_falls_back_to_term_chat test_old_host_keeps_a1_behavior "
              "test_enriched_view_clears_subagent_unknown"),
          "olguların oturum görünümüne işlenmesi (`_apply_facts`); tek istek kuralı `probe_facts_reads_caps_and_facts_in_one_request`", T10),
]
CASES["test_remote_duplicate_name.py"] = [
    t_ok("TestResolvers.test_remote_session_refuses_two_running_rows_of_the_same_name",
         f"{FH}ambiguous_or_inexact_target_sends_nothing"),
    t_ok(cls("TestResolvers", "test_running_row_is_unknown_not_absent test_one_running_and_one_closed_row_is_not_ambiguous"),
         f"U:health.rs::running_row_is_exact_truthy_and_ambiguous_is_unknown {P_STEW}"),
    t_oos("TestResolvers.test_registered_project_with_duplicate_name_is_refused_too", "projeye göre satır seçimi", T10),
    t_oos(cls("TestCallers", "test_ensure_running_neither_adopts_nor_starts test_nudge_handover_and_stop_send_nothing "
              "test_waits_do_not_report_ready_or_closed"), "uzak oturum yönetimi çağıranları", T10),
    t_oos("TestCallers.test_panel_stop_with_handover_fails_closed_without_plain_stop_fallback", "panel devirli durdurma", T4),
    t_oos(cls("TestReviewDriver", "test_start_stop_send_and_sweep_post_nothing test_poll_reports_unknown_not_ended "
              "test_single_review_session_still_gets_stop_and_send"), "uzak review sürücüsü", T8),
    t_oos(cls("TestTwinAppearsDuringHandover", "test_no_second_handover_request test_no_stop_after_reply"),
          "panel devirli durdurma (`web.py`)", T4),
    t_ok("TestRemoteRefTwins.test_one_running_and_one_closed_row_still_resolves",
         f"U:health.rs::running_row_is_exact_truthy_and_ambiguous_is_unknown {P_STEW}",
         "satır sayımı kuralı; uzak klasör seçimi T10"),
    t_oos(cls("TestRemoteRefTwins", "test_remote_ref_refuses test_closed_row_of_the_same_name_does_not_rescue_twins "
              "test_tracked_session_twins_are_refused test_context_and_file_views_read_nothing "
              "test_card_is_not_read_or_overwritten test_advance_todo_status_is_unknown "
              "test_idea_export_writes_nothing_and_keeps_the_idea test_owner_answer_stays_queued_for_retry "
              "test_directive_reports_the_unwritten_todo_line"), "uzak dosya hedefi ve çağıranları", T10),
    t_oos(cls("TestRemoteRefTwins", "test_review_driver_has_no_folder_and_keeps_findings "
              "test_review_cwd_fallback_refuses_dated_twins"), "uzak review sürücüsü", T8),
    t_oos(cls("TestMirrorWindowTwins", "test_twins_are_refused_whatever_their_folder_or_tmux_state "
              "test_a_stopped_row_of_the_same_name_does_not_hide_the_running_one"), "masaüstü yansı penceresi", T2),
]
CASES["test_steward_remote_actions.py"] = [
    t_ok(cls("TestRemoteResilience", "test_breaker_stops_after_first_transport_error_in_a_tick "
             "test_404_and_app_level_reject_do_not_open_the_breaker"),
         f"{FH}remote_post_breaker_and_error_marking {FH}transport_error_classification"),
    t_ok("TestRemoteResilience.test_backoff_after_three_failed_ticks_and_single_state_events", _FH_BREAK),
    t_ok("TestRemoteResilience.test_read_timeouts_feed_the_breaker", f"{FH}slow_single_read_does_not_blame_a_reachable_host"),
    t_ok("TestRemoteResilience.test_proxy_action_timeout_and_forced_local_host",
         f"{FX}outgoing_host_is_forced_local_and_caller_query_is_filtered {FH}remote_post_breaker_and_error_marking"),
    t_ok("TestRemoteResilience.test_remote_post_refuses_a_body_with_host",
         f"{FH}remote_post_refuses_destructive_paths_and_host_field"),
    t_ok("TestRemoteGates.test_destructive_kinds_need_exact_target_on_the_host",
         f"{FH}ambiguous_or_inexact_target_sends_nothing {FH}remote_post_refuses_destructive_paths_and_host_field"),
]
CASES["test_steward_remote_destructive.py"] = [
    t_ok(cls("TestRemoteStop", "test_no_exact_target_logs_remote_too_old_once_and_never_posts "
             "test_unknown_capabilities_are_not_treated_as_supported"), f"{FH}ambiguous_or_inexact_target_sends_nothing",
         "tek seferlik log değnekçinin (T10)"),
    t_ok(cls("TestRemoteStop", "test_no_exact_match_is_not_applied_and_does_not_open_the_breaker "
             "test_one_destructive_action_per_host_per_tick"), f"{FH}remote_stop_sends_one_exact_stop_per_host_per_tick"),
    t_ok("TestRemoteStop.test_transport_error_still_opens_the_breaker",
         f"{FH}remote_post_breaker_and_error_marking {FH}remote_stop_sends_one_exact_stop_per_host_per_tick"),
]
CASES["test_steward_remote.py"] = [
    t_ok(cls("TestEngineRemote", "test_one_slow_session_does_not_blame_a_reachable_host test_all_reads_timing_out_still_blames_host"),
         f"{FH}slow_single_read_does_not_blame_a_reachable_host"),
    t_ok("TestWebHostsLastOk.test_last_ok_at_tracks_only_successes", _TOL),
]
CASES["test_term_dedup.py"] = [
    t_ok("Dedup.test_valid_id", P_ID, "Rust kuralı Python'dan sıkı (ASCII dışı geçersiz)"),
    t_ok(cls("ProxyRetry", "test_retries_transport_failure_same_body_short_timeout test_gives_up_after_three "
             "test_remote_logic_error_not_retried test_without_input_id_legacy_single_call_default_timeout "
             "test_other_paths_untouched"), f"{FX}term_input_retries_three_times_with_same_input_id"),
]
CASES["test_review_20261125_upload_newchat.py"] = [
    t_ok(cls("BoundedReader", "test_full_body test_early_eof_raises"),
         f"{FX}upload_body_ending_early_or_overflowing_is_an_error {FX}slow_but_progressing_upload_is_not_cut"),
]
CASES["test_review_uzops_p3b.py"] = [
    t_ok("P3b.test_stop_before_connect_closes_call", f"{FW}dropped_streams_close_their_sockets_and_leak_no_fds",
         "Rust'ta bağlantı öncesi düşürme = açılış görevi iptal"),
    t_ok("P3b.test_status_consumer_replaced_when_endpoint_changes",
         f"{FW}status_stream_is_rebuilt_when_address_or_token_changes_not_extra_urls"),
]
CASES["test_chat_remote_panel_transport.py"] = [
    t_ok(cls("PanelTransportTest", "test_download_rejects_non_200 test_download_ok"),
         f"{FX}download_passes_raw_body_and_only_two_headers", "uzak durum aynen döner; 200 dışı reddi çağıranın"),
]

_LABEL = f"{FW}relay_death_label_names_lite_interval_and_viewport"
CASES["test_term_poll_interval.py"] = [
    t_ok(cls("RelayIntervalTests", "test_interval_goes_to_the_remote_url_and_into_the_key "
             "test_without_interval_url_and_key_are_exactly_as_before "
             "test_slow_and_default_watchers_of_one_session_get_separate_remote_streams "
             "test_two_slow_watchers_share_one_remote_stream"), _RELAY,
         "`interval` metin biçimi belgeli fark (`f64` / `{:g}`)"),
    t_ok(cls("RelayIntervalTests", "test_death_label_names_the_interval test_death_label_without_interval_is_unchanged"),
         f"{_LABEL} {_DEAD}"),
]
CASES["test_term_viewport.py"] = [
    t_ok(cls("RelayKeyTests", "test_viewport_adds_the_query_parameter_the_label_and_the_key "
             "test_without_viewport_url_label_and_key_are_exactly_as_before "
             "test_viewer_with_and_without_viewport_never_share_a_relay"), f"{_RELAY} {_LABEL}"),
]

# dosya -> (gerekçe, iz) — tek tek eşlenmeyen kalan testler için.
_STEW_POL = "uzak değnekçi politikası (yalnız sahte `_remote`/`web_hosts` ile)"
FILES = {
    "cache_info": ("`/api/status` önbellek bilgisi alanı", T1),
    "chat_remote_panel_transport": ("panel taşıma yardımcısı (ANSI süzme)", T2),
    "graphical_session": ("uzak grafik oturum ucu", T7),
    "host_pick_fastest": ("adres yoklama deposu ve seçimi (`host_probe` periyodik işi); Rust yalnız seçimi uygular "
                          "(`probe_choice_only_promotes_registered_allowed_candidates`)", T7),
    "labels": ("etiket deposu ve ucu (yerel)", T1),
    "mirror_marker": ("masaüstü yansı işaretleri", T2),
    "mirror_window": ("masaüstü yansı penceresi", T2),
    "remote_resume_context": ("uzak devam bağlamı uyarısı", T10),
    "review_findings_flow": ("review bulgu akışı", T8),
    "review_fixes_batch": ("review düzeltmeleri", T8),
    "review_remote": ("uzak review", T8),
    "review_remote_export": ("uzak review dışa aktarımı", T8),
    "review_remote_run": ("uzak review koşusu", T8),
    "review_20261125_upload_newchat": ("yeni sohbet adı yarışı", T4),
    "review_uzops_p3b": ("tanı günlüğü döndürme ve rustup ortamı", T7),
    "session_lock": ("oturum kilidi ucu (yerel)", T7),
    "snapshot_mirrors": ("anlık görüntü ve yansılar", T3),
    "steward_remote": (_STEW_POL, T10),
    "steward_remote_actions": (_STEW_POL, T10),
    "steward_remote_cards": ("uzak proje kartları ve dosya dışa aktarımı", T10),
    "steward_remote_destructive": (_STEW_POL, T10),
    "steward_remote_session_resolve": ("uzak proje -> oturum çözümü", T10),
    "steward_remote_surface": ("değnekçi durum yüzeyi, MCP, CLI", T10),
    "steward_review_api": ("review API", T8),
    "stop_with_handover": ("devirli durdurma (yerel + uzak)", T4),
    "term_dedup": ("girdi tekrar ayıklama (uzak panelin kendi tarafı)", T2),
    "term_history": ("terminal geçmişi ucu", T2),
    "term_poll_interval": ("terminal yoklama aralığı (yerel + relay kullanımı)", T2),
    "term_resize": ("terminal boyutu ucu", T2),
    "term_viewport": ("terminal görünüm alanı", T2),
    "triage_fixes_20261107": ("çeşitli yerel düzeltmeler", T4),
    "ucli_phase": ("ucli evresi", T7),
    "ucli_usage": ("ucli kullanım ucu", T7),
    "usage_cli": ("kullanım CLI'si", T6),
    "web_agents_glue": ("ajan token'ı ve yerel uçlar", T9),
    "web_orch_remote_fatal": ("orkestrasyon uzak bekleme", T10),
    "web_review_tick": ("reviewer tick", T8),
    "web_term_fetch": ("terminal kare alma (yerel kırpma, relay seçimi çağıranı)", T2),
}

# dosya -> (adet, ad özeti). Dosya değişince betik yeni değeri basar; gözden geçirmeden GÜNCELLEME.
PINS: dict = {}


# ── ast ──────────────────────────────────────────────────────────────────────
def definitions(path: Path):
    """[(nitelikli ad, tür, satır)] kaynak sırasıyla: işlev, sınıf, metot, modül/sınıf sabiti, satır içi regex."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list = []

    def targets(node):
        ts = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in ts:
            for e in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]):
                if isinstance(e, ast.Name):
                    yield e.id

    def walk(node, stack, in_func, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = stack + [child.name]
                is_class = isinstance(child, ast.ClassDef)
                out.append((".".join(q), "sınıf" if is_class else "işlev", child.lineno))
                walk(child, q, not is_class, ".".join(q))
                continue
            if isinstance(child, (ast.Assign, ast.AnnAssign)) and not in_func:
                for name in targets(child):
                    out.append((".".join(stack + [name]), "sabit", child.lineno))
                    value = child.value
                    if value is not None:
                        walk(value, stack, in_func, ".".join(stack + [name]))
                continue
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                    and isinstance(child.func.value, ast.Name) and child.func.value.id == "re"
                    and child.args and isinstance(child.args[0], (ast.Constant, ast.JoinedStr, ast.BinOp))):
                n = 1 + sum(1 for o in out if o[0].startswith(f"{owner}::re"))
                out.append((f"{owner or 'modul'}::re{n}", "regex", child.lineno))
            walk(child, stack, in_func, owner)

    walk(tree, [], False, "")
    seen: dict = {}
    uniq = []
    for q, kind, line in out:
        seen[q] = seen.get(q, 0) + 1
        if seen[q] == 1:
            uniq.append((q, kind, line))
        elif kind != "sabit":
            uniq.append((f"{q}#{seen[q]}", kind, line))
    return uniq


def scoped_definitions(mod: str):
    defs = definitions(PKG / mod)
    if mod == STEWARD:
        return [d for d in defs if STEWARD_RE.search(d[0])]
    if mod == AUTHZ:
        return [d for d in defs if d[0] in AUTHZ_NAMES]
    return defs


MODULES = FULL + [STEWARD, AUTHZ]


def test_methods(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list = []

    def walk(body, stack):
        for n in body:
            if isinstance(n, ast.ClassDef):
                walk(n.body, stack + [n.name])
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
                out.append((".".join(stack + [n.name]), n.lineno))
            else:
                for field in ("body", "orelse", "finalbody", "handlers"):
                    sub = getattr(n, field, None)
                    if isinstance(sub, list) and not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        walk(sub, stack)

    walk(tree.body, [])
    return out


def scoped_test_files():
    """Kapsam modüllerini içe aktaran (ya da dizgiyle yamalayan) veya kapsam adlarını anan test dosyaları."""
    out = []
    for f in sorted(TESTS.rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        found = bool(TEST_SYMBOL.search(src))
        for n in ast.walk(ast.parse(src)):
            names: list = []
            if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                names = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
            elif isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("claudeops."):
                names = [n.value]
            found = found or any(TEST_IMPORT.match(x) for x in names)
        if found and test_methods(f):
            out.append(f)
    return out


def digest(names) -> str:
    return hashlib.sha1("\n".join(sorted(names)).encode()).hexdigest()[:10]


# ── Rust adları ──────────────────────────────────────────────────────────────
def _read(rel: str):
    p = CRATE / rel
    return p.read_text(encoding="utf-8") if p.is_file() else None


def _blocks(text: str, head: str):
    """Sütun 0'da başlayıp sütun 0'daki `}` ile biten bloklar (rustfmt biçimi)."""
    for m in re.finditer(head, text, re.M):
        end = re.compile(r"^\}", re.M).search(text, m.end())
        yield text[m.start(): end.end() if end else len(text)]


def rust_symbol_exists(ref: str) -> bool:
    file, _, sym = ref.partition("::")
    field = None
    if "." in sym:
        sym, _, field = sym.partition(".")
    text = _read(f"src/{file}")
    if text is None or not sym:
        return False
    if field:
        return any(re.search(rf"^\s*(pub(\([a-z]+\))?\s+)?{re.escape(field)}\s*:", b, re.M)
                   for b in _blocks(text, rf"^(pub(\([a-z]+\))?\s+)?struct {re.escape(sym)}\b[^;]*?\{{"))
    parts = sym.split("::")
    decl = r"\b(fn|struct|enum|const|static|type|trait|mod)\s+{}\b"
    if len(parts) == 1:
        return re.search(decl.format(re.escape(parts[0])), text) is not None
    owner, name = parts
    return any(re.search(decl.format(re.escape(name)), b)
               for b in _blocks(text, rf"^impl(<[^>]*>)?\s+([\w:<>]+\s+for\s+)?{re.escape(owner)}\b[^\n]*\{{"))


def rust_test_exists(kind: str, body: str) -> bool:
    file, _, name = body.partition("::")
    text = _read(f"{'src' if kind == 'U' else 'tests'}/{file}")
    return text is not None and re.search(
        rf"#\[(tokio::)?test[^\]]*\]\s*\n(\s*(#\[[^\n]*\]|//[^\n]*)\n)*\s*(async\s+)?fn {re.escape(name)}\s*\(",
        text) is not None


def show_test(ref: str) -> str:
    kind, _, body = ref.partition(":")
    return body if kind == "U" else f"tests/{body}"


def parse_shown_test(shown: str):
    if shown.startswith("tests/"):
        return "I", shown[len("tests/"):]
    return "U", shown


# ── üretim ───────────────────────────────────────────────────────────────────
def cell(items) -> str:
    return "<br>".join(f"`{x}`" for x in items) if items else "yok"


def build():
    errors: list = []
    def_rows: dict = {}
    for mod in MODULES:
        defs = scoped_definitions(mod)
        if mod == AUTHZ:
            missing = set(AUTHZ_NAMES) - {d[0] for d in defs}
            errors += [f"{mod}: AUTHZ_NAMES adı ast'te yok: {n}" for n in sorted(missing)]
        data: dict = {}
        for names, status, rust, tests, note in DEFS.get(mod, []):
            for n in names:
                if n in data:
                    errors.append(f"{mod}: iki kez eşlenmiş: {n}")
                data[n] = (status, rust.split(), tests.split(), note)
        have = {d[0] for d in defs}
        errors += [f"{mod}: eşlemesi yok: {n}" for n, _, _ in defs if n not in data]
        errors += [f"{mod}: eşlemede var, ast'te yok: {n}" for n in data if n not in have]
        rows = []
        for q, kind, line in defs:
            if q not in data:
                continue
            status, rust, tests, note = data[q]
            if status == OK and not (rust and tests):
                errors.append(f"{mod}::{q}: karşılandı satırında Rust ya da test yok")
            if status != OK and not note:
                errors.append(f"{mod}::{q}: gerekçe yok")
            rows.append((q, kind, line, status, rust, tests, note))
        def_rows[mod] = rows

    test_rows: dict = {}
    files = scoped_test_files()
    names_seen = {f.relative_to(TESTS).as_posix() for f in files}
    errors += [f"test eşlemesi var, dosya kapsam taramasında yok: {n}" for n in CASES if n not in names_seen]
    errors += [f"FILES girdisi var, dosya kapsam taramasında yok: {n}"
               for n in FILES if f"test_{n}.py" not in names_seen]
    for f in files:
        rel = f.relative_to(TESTS).as_posix()
        methods = test_methods(f)
        data = {}
        for names, status, tests, note in CASES.get(rel, []):
            for n in names:
                if n in data:
                    errors.append(f"{rel}: iki kez eşlenmiş: {n}")
                data[n] = (status, tests.split(), note)
        have = {m for m, _ in methods}
        errors += [f"{rel}: eşlemede var, ast'te yok: {n}" for n in data if n not in have]
        rest = [m for m, _ in methods if m not in data]
        key = rel[len("test_"):-len(".py")]
        if rest:
            if key not in FILES:
                errors += [f"{rel}: eşlemesi yok: {n}" for n in rest]
            else:
                why, track = FILES[key]
                pin = (len(rest), digest(rest))
                if PINS.get(key) != pin:
                    errors.append(f"{rel}: dosya özeti tutmuyor (kayıtlı {PINS.get(key)}, şimdi {pin}); "
                                  "yeni/değişen testleri gözden geçir")
                for m in rest:
                    data[m] = (OOS, [], f"{why}. İz: {track}")
        elif key in FILES:
            errors.append(f"{rel}: FILES girdisi boşta (tüm testler tek tek eşlenmiş)")
        test_rows[rel] = [(m, line, *data[m]) for m, line in methods if m in data]

    for mod, rows in def_rows.items():
        for q, *_, status, rust, tests, note in rows:
            errors += [f"{mod}::{q}: Rust adı kaynakta yok: {r}" for r in rust if not rust_symbol_exists(r)]
            errors += [f"{mod}::{q}: Rust testi yok: {t}" for t in tests
                       if not rust_test_exists(*t.split(":", 1))]
    for rel, rows in test_rows.items():
        for m, line, status, tests, note in rows:
            if status == OK and not tests:
                errors.append(f"{rel}::{m}: karşılandı satırında test yok")
            errors += [f"{rel}::{m}: Rust testi yok: {t}" for t in tests if not rust_test_exists(*t.split(":", 1))]
    return def_rows, test_rows, errors


def render(def_rows, test_rows) -> str:
    def count(rows, idx):
        c = {OK: 0, OOS: 0, GAP: 0}
        for r in rows:
            c[r[idx]] += 1
        return c

    all_defs = [r for rows in def_rows.values() for r in rows]
    all_tests = [r for rows in test_rows.values() for r in rows]
    dc, tc = count(all_defs, 3), count(all_tests, 2)
    scope = {STEWARD: "seçili (`{}`)".format(STEWARD_RE.pattern.replace("|", "\\|")), AUTHZ: "seçili (giden imza)"}
    out = [
        "# rs/hosts eşleme tablosu (Python -> cops-hosts)",
        "",
        "ÜRETİLMİŞ DOSYA, elle düzenleme. Kaynak: `rust/crates/cops-hosts/tools/mapping.py`.",
        "Denetim: `python3 -I rust/crates/cops-hosts/tools/mapping.py --check` (AÇIK varsa da düşsün: `--strict`).",
        "",
        "Durumlar: **karşılandı** = Rust karşılığı ve onu sınayan test/parite adımı var (not sütunu sınırı ve farkı "
        "söyler); **kapsam dışı** = bu crate'in işi değil, gerekçe ve iz yazılı; **AÇIK** = kapsamda olduğu hâlde "
        "davranış ya da test karşılığı yok.",
        "",
        "Rust yolları `rust/crates/cops-hosts/src/` altındadır; `tests/...` crate'in entegrasyon testleri "
        "(`tests/parity.rs` Python ile diferansiyel ve metin paritesi). Denetim adların kaynakta VARLIĞINI sınar; "
        "testin o davranışı gerçekten kapsadığı elle değerlendirilmiştir. Bu betik testleri koşturmaz. Belgeli "
        "farklar: `docs/rs-hosts.md` \"Python'dan bilinçli farklar\". Modül kapsamı: TAM modüllerde her `ast` tanımı "
        "(işlev, sınıf, metot, modül/sınıf sabiti, `re.*` çağrısı) bir satırdır; `web_steward.py`de adı desene uyan "
        "her tanım (crate'in karşılamadıkları `T10`), `authz.py`de giden imza adları. Test kapsamı: kapsam "
        "modüllerini içe aktaran/yamalayan ya da kapsam adlarını anan her `py/tests` dosyasının her `test*` metodu.",
        "",
        "## Özet",
        "",
        "| Küme | Toplam | karşılandı | kapsam dışı | AÇIK |",
        "|---|---|---|---|---|",
        f"| tanım | {len(all_defs)} | {dc[OK]} | {dc[OOS]} | {dc[GAP]} |",
        f"| test durumu ({len(test_rows)} dosya) | {len(all_tests)} | {tc[OK]} | {tc[OOS]} | {tc[GAP]} |",
        "",
        "| Modül | Kapsam | Toplam | karşılandı | kapsam dışı | AÇIK |",
        "|---|---|---|---|---|---|",
    ]
    for mod, rows in def_rows.items():
        c = count(rows, 3)
        out.append(f"| `{mod}` | {scope.get(mod, 'TAM')} | {len(rows)} | {c[OK]} | {c[OOS]} | {c[GAP]} |")
    out += ["", "## AÇIK satırlar", ""]
    for mod, rows in def_rows.items():
        out += [f"- `{mod}::{r[0]}`: {r[6]}" for r in rows if r[3] == GAP]
    for rel, rows in test_rows.items():
        out += [f"- `{rel}::{r[0]}`: {r[4]}" for r in rows if r[2] == GAP]
    if out[-1] == "":
        out.append("Yok.")
    out += ["", "## Tanımlar", ""]
    for mod, rows in def_rows.items():
        out += [f"### `py/claudeops/{mod}`", "",
                "| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |",
                "|---|---|---|---|---|---|"]
        for q, kind, line, status, rust, tests, note in rows:
            out.append(f"| `{mod}::{q}` | {kind}:{line} | {status} | {cell(rust)} | "
                       f"{cell([show_test(t) for t in tests])} | {note or 'yok'} |")
        out.append("")
    out += ["## Python test durumları", ""]
    for rel, rows in test_rows.items():
        out += [f"### `py/tests/{rel}`", "",
                "| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |",
                "|---|---|---|---|---|"]
        for m, line, status, tests, note in rows:
            out.append(f"| `{rel}::{m}` | {line} | {status} | {cell([show_test(t) for t in tests])} | "
                       f"{note or 'yok'} |")
        out.append("")
    return "\n".join(out)


# ── denetim ──────────────────────────────────────────────────────────────────
def check_table(text: str):
    """Yazılı tabloyu eşleme verisinden BAĞIMSIZ olarak `ast` ve Rust kaynağıyla karşılaştırır."""
    errors: list = []
    expected = set()
    for mod in MODULES:
        expected |= {f"{mod}::{d[0]}" for d in scoped_definitions(mod)}
    for f in scoped_test_files():
        expected |= {f"{f.relative_to(TESTS).as_posix()}::{m}" for m, _ in test_methods(f)}
    seen: dict = {}
    gaps: list = []
    section = ""
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            section = line[3:]
        if section not in ("Tanımlar", "Python test durumları") or not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        key = cells[0].strip("`")
        width = 6 if section == "Tanımlar" else 5
        if len(cells) != width or not all(cells):
            errors.append(f"satır {number}: boş ya da eksik hücre: {key}")
            continue
        if key in seen:
            errors.append(f"satır {number}: yinelenen satır: {key}")
        seen[key] = number
        status = cells[2]
        rust = cells[3] if section == "Tanımlar" else ""
        tests = cells[4] if section == "Tanımlar" else cells[3]
        note = cells[-1]
        if status not in (OK, OOS, GAP):
            errors.append(f"satır {number}: bilinmeyen durum: {status}")
        if status == OK and (tests == "yok" or (section == "Tanımlar" and rust == "yok")):
            errors.append(f"satır {number}: karşılandı ama Rust/test boş: {key}")
        if status == OOS and "İz: " not in note:
            errors.append(f"satır {number}: kapsam dışı ama iz yok: {key}")
        if status == GAP:
            gaps.append(key)
            if note == "yok":
                errors.append(f"satır {number}: AÇIK ama açıklama yok: {key}")
        errors += [f"satır {number}: Rust adı kaynakta yok: {r}"
                   for r in re.findall(r"`([^`]+)`", rust) if not rust_symbol_exists(r)]
        errors += [f"satır {number}: Rust testi yok: {t}"
                   for t in re.findall(r"`([^`]+)`", tests) if not rust_test_exists(*parse_shown_test(t))]
    errors += [f"ast'te var, tabloda yok: {k}" for k in sorted(expected - set(seen))]
    errors += [f"tabloda var, ast'te yok: {k}" for k in sorted(set(seen) - expected)]
    return errors, len(seen), gaps


def load_pins():
    for line in PIN_DATA.split():
        key, n, h = line.split(":")
        PINS[key] = (int(n), h)


PIN_DATA = """
cache_info:12:9f2b8b4e3c
chat_remote_panel_transport:1:615e199771
graphical_session:15:f6a11d4c9a
host_pick_fastest:20:f855ab596d
labels:17:6c43bbff65
mirror_marker:20:b48dacfc73
mirror_window:41:478cd40f73
remote_resume_context:5:e697032eec
review_20261125_upload_newchat:1:e411f92f9c
review_findings_flow:59:52b602ef8b
review_fixes_batch:15:d28541676e
review_remote:21:51fe8afa5f
review_remote_export:10:0548d3c6e8
review_remote_run:13:0ca51d4ddc
review_uzops_p3b:2:618c9ca3d3
session_lock:11:1deed1d545
snapshot_mirrors:40:9b4093b114
steward_remote:28:d4daee9dff
steward_remote_actions:18:cde799e0c0
steward_remote_cards:16:4ea5fb6fea
steward_remote_destructive:18:f08bb035a9
steward_remote_session_resolve:19:ea0e53d4f5
steward_remote_surface:25:c2b96c4156
steward_review_api:14:8168429dc9
stop_with_handover:30:1888241d42
term_dedup:7:8bfc43c524
term_history:26:39bab78a7e
term_poll_interval:24:d873401052
term_resize:15:541d06cbaf
term_viewport:30:34c0d9e65d
triage_fixes_20261107:6:ea950c1fe0
ucli_phase:30:6588d1ea97
ucli_usage:13:adc8be28ee
usage_cli:4:0c156997ca
web_agents_glue:6:1b1c715937
web_orch_remote_fatal:2:fe0f58b471
web_review_tick:11:62ededdf88
web_term_fetch:11:8c41adb23f
"""


def main(argv) -> int:
    load_pins()
    if "--pins" in argv:                      # gözden geçirme sonrası yeni özetleri basar (dosyayı değiştirmez)
        for f in scoped_test_files():
            rel = f.relative_to(TESTS).as_posix()
            done = {n for names, *_ in CASES.get(rel, []) for n in names}
            rest = [m for m, _ in test_methods(f) if m not in done]
            if rest:
                print(f"{rel[5:-3]}:{len(rest)}:{digest(rest)}")
        return 0
    def_rows, test_rows, errors = build()
    text = render(def_rows, test_rows)
    if "--check" in argv:
        if not OUT.is_file():
            print(f"tablo yok: {OUT}")
            return 1
        current = OUT.read_text(encoding="utf-8")
        found, n, gaps = check_table(current)
        errors += found
        if current != text:
            errors.append("tablo bayat: betiği --check olmadan koştur")
        for e in errors:
            print(e)
        print(f"satır {n}, AÇIK {len(gaps)}, hata {len(errors)}")
        return 1 if errors or ("--strict" in argv and gaps) else 0
    if errors:
        print("\n".join(errors))
        print(f"hata {len(errors)}; tablo yazılmadı")
        return 1
    OUT.write_text(text, encoding="utf-8")
    gaps = sum(r[3] == GAP for rows in def_rows.values() for r in rows)
    tgaps = sum(r[2] == GAP for rows in test_rows.values() for r in rows)
    print(f"yazıldı: {OUT.relative_to(REPO)}; tanım {sum(map(len, def_rows.values()))} (AÇIK {gaps}), "
          f"test {sum(map(len, test_rows.values()))} (AÇIK {tgaps})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
