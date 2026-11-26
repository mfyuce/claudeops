# rs/gate eşlik tablosu: ön kapı ve kimlik (Python -> Rust)

Taban: dal `rs/gate`, commit `174c18e` + bölüm 5 işleri 1-7'nin çalışma ağacı değişiklikleri (26 Kas gece, henüz commit yok).
Python yolları `py/claudeops/` altına, Rust yolları `rust/crates/` altına görelidir; Rust satır numaraları bu çalışma ağacına
göredir (Python dosyaları değişmedi). Test adları ve satırlar betikle kaynaktan doğrulandı; testler koşuldu (`docs/rs-gate.md`
"Doğrulama"). Parite koşusu kaydı bölüm 5 iş 9.

## 0. Durum sözlüğü ve kapsam

- `eşit`: Rust kodu okundu, davranış aynı ve adı verilen test bunu sınıyor.
- `eşit (daha sıkı)`: Python'un reddettiğini Rust da reddeder, Python'un kabul ettiğinin bir kısmını Rust BİLEREK reddeder
  (fark hücrede); adı verilen test sınıyor. İlke: Rust yalnız bu yönde ayrışabilir.
- `kod var, test yok`: Rust kodu var ama Python davranışına eşliği sınayan test yok ya da eksik (bu turdan sonra boş; bilerek daha sıkı davranışlar `eşit (daha sıkı)`).
- `eksik (Rust'ta karşılığı yok)`: kapsanan davranış çekirdek crate'lerde (`cops-proxy`, `copsd`, `cops-auth`, `cops-parity`) yok ya da yalnız bir bölümü var.
- `kapsam dışı: neden, hangi iz`: Python'da kalıyor ya da başka izin işi. İz adları `docs/rust-sprint-plan.md`; "?" envanterdeki tahmindir.

Dahil: `front.py` ve `commands/front_cmd.py` (tümü); `commands/web.py` içinde `_authorized`, `_authorized_ws`, `_client_ip`,
`X-Cops-Front` okuyan `trusted_forwarded_ip`, `do_POST` içindeki `/api/_internal/` dalı ve doğrudan çağırdıkları (`_json`,
`_read_body`, `_read_body_raw`, `_body_timeout_ctx`, `_BodyTimeout`, `BODY_READ_TIMEOUT`, `_body_pending`, `token`; `do_POST`
bu dalın istisnalarını 408/400'e çevirdiği için dahil). Doğrudan çağrılan dış modül tanımları: `ws_ticket.py` (tümü; üç tüketim
işlevi çağrılıyor, kalanı aynı deponun durumu) ve `authz.py`den `RequestView`, `Principal`, `LEGACY`, `Resource`, `action_for`
(+ tablosu, `UNMAPPED`), `has_authenticator`, `authenticate`, `check`. Bunların kendi iç bağımlılıkları (`_audit`, `_log`,
`_AUTHENTICATOR`, `_AUTHORIZER`) doğrudan çağrı olmadığı için alınmadı. Hariç: standart kitaplık (`hmac`, `secrets`, `json`,
`ipaddress`, `parse_qs`, `urlparse`) ve günlük yazımı `diag_log` (yanıtı değiştirmez; T7 tanı). `web.py`deki komşu tanımlar
bölüm 1.5'te nedeniyle listelendi.

## 1. Python tanımları

### 1.1 `front.py`

| Python adı (dosya:satır) | Rust karşılığı (dosya:satır) | parite testi (Rust) | durum |
|---|---|---|---|
| `LOOPBACK` (front.py:14) | `cops-proxy/src/front.rs:18` `LOOPBACK`, `cops-proxy/src/front.rs:27` `python_loopback` (IPv4 eşlemeli `::ffff:127.0.0.1` kanonik yazımıyla dahil, 127/8'in geri kalanı DEĞİL). `client_https` ve `drop_untrusted_client_ip` (`cops-proxy/src/lib.rs:247`, `cops-proxy/src/lib.rs:257`) 127/8 kullanır: orada eş Python loopback'i değilse `Cf-Connecting-IP` zaten `pin_client_ip` ile ezilir | `python_loopback_address_table`, `trusted_front_needs_secret_loopback_and_exact_header`, `mapped_ipv4_loopback_peer_may_report_https` | eşit |
| `secret_path` (front.py:21) | `copsd/src/lib.rs:81` `secret_file`: `<durum dizini>/front.secret` (`--state-dir`, `CLAUDEOPS_DIR`, `$HOME/.claude/claudeops`; ek: `--secret-file`); "Python hatası?" 3 iki tarafta düzeltildi | `default_secret_path_follows_state_dir`, `test_secret_follows_state_dir` | eşit |
| `read_secret` (front.py:25) | `cops-proxy/src/front.rs:69` `read_secret_file`, `cops-proxy/src/front.rs:148` `FrontSecret::current` (her istekte `stat`, imza değişince yeniden okuma), `copsd/src/lib.rs:87` `warn_unusable_secret` (açılışta uyarı, süreç sürer). Açılışta ve çalışırken yok/gevşek/bozuk UTF-8/64 KiB üstü = gizli yok (Python bozuk UTF-8'de de gizli yok, düzeltildi) | `file_secret_follows_changes_and_fails_closed`, `front_secret_file_is_reread_and_fails_closed`, `runtime_secret_changes_apply_without_restart`, `startup_ignores_unusable_secret_file_and_warns` | eşit |
| `ensure_secret` (front.py:40) | yok (copsd gizli üretmez) | yok | kapsam dışı: yalnız `cops front on` çağırır, Python CLI kalıyor, T6 |
| `trusted_front` (front.py:57) | `cops-proxy/src/front.rs:176` `FrontSecret::trusted` (gizli dolu, Python loopback eşi, ilk `X-Cops-Front` HAM bayt sabit zamanlı eşit; kırpma yok, Python gibi); stats/metrik denetimi bunu kullanır (`cops-proxy/src/lib.rs:1172` `front_trusted`) | `trusted_front_needs_secret_loopback_and_exact_header`, `front_secret_file_is_reread_and_fails_closed` | eşit |
| `internal_authz` (front.py:68) | sunucu tarafı yok; copsd yolu dışarıya kapatır (`cops-proxy/src/lib.rs:1200`); istemcisi enterprise `copsd-ent` `PyAuthz` | yok | kapsam dışı: karar Python'da, Rust yalnız tüketir, T9 (envanter W50 "T9?") |
| `internal_authz._H` (front.py:82) | karşılığı gereksiz: Rust `RequestView.headers` küçük harf listesi | yok | kapsam dışı: `internal_authz` iç yardımcısı, T9 |
| `internal_authz._H.get` (front.py:83) | `cops-auth/src/authz.rs:80` (ilk başlık, ad küçük harf verilmeli) | `duplicate_cookie_takes_last_and_header_takes_first` | kapsam dışı: `internal_authz` iç yardımcısı, T9 |
| `ws_ticket_consume` (front.py:118) | yok; `/api/_internal/*` dışarıya kapalı, bilet deposu Python belleğinde | yok | kapsam dışı: bilet deposu Python'da, T2 (envanter W51 "T9?") |
| ortam değişkeni `CLAUDEOPS_FRONT_SECRET` (boş değilse dosyadan önce, kırpılmadan) (front.py:23) | `cops-proxy/src/front.rs:132` `from_env_or_file`, `copsd/src/lib.rs:185` aynı öncelik, kırpılmaz | `trusted_front_needs_secret_loopback_and_exact_header` (kırpılmaz) | eşit |
| izin kuralı `st_mode & 0o077` (gevşek dosyaya güvenme) (front.py:28) | `cops-proxy/src/front.rs:84`: açılışta ve çalışırken gizli yok (Python gibi); açılışta uyarı | `file_secret_follows_changes_and_fails_closed`, `runtime_secret_changes_apply_without_restart`, `startup_ignores_unusable_secret_file_and_warns` | eşit |
| copsd varsayılan üst port, `front_cmd.DEFAULT_INTERNAL` (28765) ile aynı olmalı (commands/front_cmd.py:32) | `copsd/src/lib.rs:38` `DEFAULT_UPSTREAM` = `127.0.0.1:28765`, `copsd/src/main.rs:17` USAGE | `default_upstream_matches_python_front_cmd` (kaynak karşılaştırır, ağ yok), `help_and_version_have_no_side_effects` | eşit |

### 1.2 `commands/front_cmd.py`

| Python adı (dosya:satır) | Rust karşılığı (dosya:satır) | parite testi (Rust) | durum |
|---|---|---|---|
| `UNIT_DIR` (commands/front_cmd.py:26) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `FRONT_UNIT` (commands/front_cmd.py:27) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `WEB_UNIT` (commands/front_cmd.py:28) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `DROPIN` (commands/front_cmd.py:29) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `DEFAULT_BIN` (commands/front_cmd.py:30) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `DEFAULT_LISTEN` (commands/front_cmd.py:31) | `copsd/src/lib.rs:182` aynı değer | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `DEFAULT_INTERNAL` (commands/front_cmd.py:32) | `copsd/src/lib.rs:38` `DEFAULT_UPSTREAM` AYNI değer (bölüm 1.1 son satır) | `default_upstream_matches_python_front_cmd` | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `FRONT_UNIT_TEMPLATE` (commands/front_cmd.py:34) | verdiği bayraklar `--listen --upstream --dist --state-dir` `copsd/src/lib.rs:180` içinde okunur | `sighup_reloads_force_proxy_and_stats_count_it` (bayrakların kabulü) | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `register` (commands/front_cmd.py:49) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `_unit_text` (commands/front_cmd.py:59) | `--state-dir` bayrağı copsd `state_dir` ile okunur | `default_secret_path_follows_state_dir` (bayrağın kabulü) | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `web_execstart` (commands/front_cmd.py:66) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `with_internal_port` (commands/front_cmd.py:71) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `dropin_text` (commands/front_cmd.py:82) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `port_busy` (commands/front_cmd.py:86) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `plan_on` (commands/front_cmd.py:93) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `_sc` (commands/front_cmd.py:113) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| `run` (commands/front_cmd.py:117) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |
| regex `^ExecStart=(.*)$` (`re.M`, ilk eşleşme) (commands/front_cmd.py:67) | yok | yok | kapsam dışı: `cops front` CLI Python'da kalıyor, T6 |

### 1.3 `commands/web.py` (kimlik ve ön kapı)

| Python adı (dosya:satır) | Rust karşılığı (dosya:satır) | parite testi (Rust) | durum |
|---|---|---|---|
| `_BodyTimeout` (commands/web.py:4785) | `cops-proxy/src/lib.rs:210` `body_timeout_resp` (408 `{"ok": false, "error": "request body timeout"}` + `Connection: close`), `cops-proxy/src/lib.rs:222` `read_body_limited` (süre aşımı VE erken kopan/eksik gövde) | `slow_body_times_out_with_408`, `short_body_is_408_and_closes` | eşit |
| `trusted_forwarded_ip` (commands/web.py:4792) | `cops-proxy/src/front.rs:194` `trusted_client_ip` (metin üstünde aynı kural); üretici taraf `cops-proxy/src/lib.rs:916` `prepare_forward_headers` + `cops-proxy/src/front.rs:232` `pin_client_ip`. Biçim farkı: IPv4 eşlemeli IPv6 Python `::ffff:102:304`, Rust `::ffff:1.2.3.4`; kapsam kimlikli IPv6'yı Rust kabul etmez (loopback kalır) | `trusted_client_ip_matches_python_test_front_xff`, `python_sees_real_client_with_or_without_secret` | eşit |
| `_Handler.token` (commands/web.py:4824) | `cops-auth/src/lib.rs:146`. Fark: her istekte okur, 0600 değilse ya da yoksa kapalı (Python açılışta bir kez yükler/üretir): döndürülen ya da silinen token Rust'ta hemen geçersiz | `file_token_follows_rotation_deletion_and_mode`, `token_file_defaults_to_state_dir` | eşit (daha sıkı) |
| `_Handler.BODY_READ_TIMEOUT` (commands/web.py:4825) | `cops-proxy/src/gate.rs:133` `ROUTE_BODY_TIMEOUT` 10 sn TOPLAM (kanca ve metrik POST; Python 60 sn, her soket okuması) | `slow_body_times_out_with_408`, `short_body_is_408_and_closes` | eşit (daha sıkı) |
| `_Handler._body_pending` (commands/web.py:4829) | hyper bağlantı durumu okunmamış gövdeyi boşaltır ya da bağlantıyı kapatır; metrik 413 açıkça `Connection: close` | `early_reject_then_second_request_on_same_connection`, `unread_post_body_does_not_poison_next_request` | eşit |
| `_Handler._authorized` (commands/web.py:4933) | `cops-auth/src/lib.rs:196` `Token::authorized` (boş token kapalı, `?token=` ilk dolu değer, `Bearer `, ASCII dışı aday red, sabit zaman) | `query_and_bearer_accept_empty_token_is_closed_non_ascii_rejected`, `token_query_matches_python_parse_qs`, `whitespace_stripping_matches_python_str_strip` | eşit |
| `_Handler._authorized_ws` (commands/web.py:5010) | yok; `/ws*` yükseltmesi sorgu (bilet dahil) değişmeden aktarılır (`cops-proxy/src/lib.rs:1370`) | `websocket_upgrade_is_tunnelled` | kapsam dışı: WS uçları ve bilet Python'da, T2 (`/ws/term`), T1 (`/ws`) |
| `_Handler._json` (commands/web.py:5066) | `cops-proxy/src/lib.rs:194` `json_resp`: durum, `Content-Type`, JSON gövde, ek `Cache-Control: no-store`; güvenlik başlıkları `cops-proxy/src/lib.rs:145` `harden` (Python `end_headers`) | `security_headers_match_python_end_headers`, `questions_endpoint_is_local_authenticated_and_everything_else_proxies` | eşit |
| `_Handler._client_ip` (commands/web.py:5468) | `cops-proxy/src/front.rs:222` `view_client_ip` (Python'un vekillenen istekte göreceği değer, `RequestView`den); `RequestView.client_ip` soket eşi olarak KALDI (enterprise `trusted_ip` bunu varsayıyor). Çekirdekte henüz tüketen uç yok (T7/T9) | `python_sees_real_client_with_or_without_secret`, `trusted_client_ip_matches_python_test_front_xff` | eşit |
| `_Handler._body_timeout_ctx` (commands/web.py:5922) | `tokio::time::timeout` (soket durumu yok, geri yükleme gerekmez) | `slow_body_times_out_with_408` | kapsam dışı: soket zaman aşımını geri koyma Rust'ta gereksiz, iz yok |
| `_Handler._read_body` (commands/web.py:5956) | `cops-proxy/src/lib.rs:222` `read_body_limited` (önbellek yok: gövde bir kez okunur; bildirilen boy sınırı aşarsa okumadan `TooLarge`) | `claimed_path_is_answered_by_hook_with_body`, `oversized_body_is_reported_not_read_whole`, `short_body_is_408_and_closes` | eşit |
| `_Handler._read_body_raw` (commands/web.py:5963) | `cops-proxy/src/lib.rs:222`: süre aşımı ve kısa/kopan gövde 408 (kanca çağrılmaz; `BodyError::Read` artık kancaya gitmez) | `slow_body_times_out_with_408`, `short_body_is_408_and_closes` | eşit |
| `_Handler.do_POST` (commands/web.py:5976) | `cops-proxy/src/lib.rs:929` `run_hook` ve metrik POST: 408 JSON + kapanış; `cops-proxy/src/gate.rs:201` panik 500, süre 503; gövde tipi hatası yerel uçta 400 (metrik `bad json`/`bad body`), kancada kancanın işi | `slow_body_times_out_with_408`, `short_body_is_408_and_closes`, `hook_panic_and_timeout_fail_closed`, `points_series_names_with_auth` | eşit |
| `_Handler._do_post_inner` (commands/web.py:5999) | yalnız `/api/_internal/` dalı kapsamda (alt satırlar bölüm 1.4); sunucu tarafı Rust'ta yok | yok | kapsam dışı: iç uçları Python sunar, T9 |
| `loopback` yerel sabiti `("127.0.0.1", "::1")` (commands/web.py:4794) | `cops-proxy/src/front.rs:18` `LOOPBACK` (aynı metin kümesi) | `trusted_client_ip_matches_python_test_front_xff` | eşit |
| içe aktarma `front_mod` (`from .. import front`) (commands/web.py:4789) | copsd gizliyi kendi okur (`read_secret`) | yok | kapsam dışı: Python modül bağı, iz yok |
| başlık boşluğu: `Bearer` sonrası `str.strip()`, `0x85/0xA0` dahil (commands/web.py:4961) | Rust `to_str()` ASCII dışı baytlı `Authorization`ı yok sayar: böyle sonlanan doğru token Python'da geçer, Rust'ta 401 | `bearer_with_trailing_latin1_space_is_rejected` | eşit (daha sıkı) |

### 1.4 `/api/_internal/` dalı, adım adım

| Python adı (dosya:satır) | Rust karşılığı (dosya:satır) | parite testi (Rust) | durum |
|---|---|---|---|
| dal girişi: dış istemci iç uca ulaşamaz, durum 404 (commands/web.py:6014) | `cops-proxy/src/lib.rs:1200` `is_internal_target` (`cops-proxy/src/lib.rs:185`): Rust yolu YA DA Python'un aynı hedeften çıkaracağı yol (`cops-proxy/src/lib.rs:160` `python_path`: `//` indirgemesi, mutlak biçim) `api/_internal` ile başlıyorsa, harf duyarsız, her yöntem 404 | `internal_paths_are_never_forwarded`, `internal_block_covers_every_form_python_would_route`, `https_only_from_loopback_forwarded_proto_and_internal_never_routed` | eşit (daha sıkı) |
| 404 gövdesi ve başlıkları (`{"error": "not found"}` + güvenlik başlıkları) (commands/web.py:6018) | `cops-proxy/src/lib.rs:1200`: aynı JSON gövde, `harden` | `internal_block_covers_every_form_python_would_route`, `security_headers_match_python_end_headers` | eşit |
| güven koşulu `trusted_front(peer, headers)` (loopback + gizli) (commands/web.py:6017) | Rust sunmaz; her aktarılan isteğe o anki gizliyi ekler (`cops-proxy/src/lib.rs:916` `prepare_forward_headers`), istemci kopyasını siler | `front_secret_is_injected_and_client_copy_dropped`, `front_secret_file_is_reread_and_fails_closed` (üretici taraf) | kapsam dışı: doğrulama Python'da, T9 |
| `Content-Length` ayrıştırma, `0..65536` dışı: 400 + bağlantı kapanır (commands/web.py:6024) | yok (istemci tarafı sınırı enterprise `MAX_PAYLOAD`) | yok | kapsam dışı: doğrulama Python'da, T9 |
| bozuk JSON / nesne olmayan gövde: 400 `bad json` (commands/web.py:6033) | yok | yok | kapsam dışı: doğrulama Python'da, T9 |
| `/api/_internal/authz` yönlendirmesi (commands/web.py:6035) | yok | yok | kapsam dışı: uç Python'da, T9 |
| `/api/_internal/ws-ticket/consume` yönlendirmesi (commands/web.py:6037) | yok | yok | kapsam dışı: uç Python'da, T2 |
| bilinmeyen iç yol: 404 (commands/web.py:6039) | dış istek zaten Rust'ta 404 | `internal_paths_are_never_forwarded` | kapsam dışı: iç çağrı Python'da, T9 |
| `_json` üzerinden her yanıta eklenen `nosniff`, `Referrer-Policy`, `X-Frame-Options`, CSP (commands/web.py:4921) | `cops-proxy/src/lib.rs:145` `harden`: Rust'ın cevapladığı her yanıt (statik, metrik, soru, tablo, kanca, stats), iç uç 404'ü, Python yolunda copsd'nin ürettiği 502/400; kendi CSP'sini veren kanca yanıtına ikinci CSP/XFO eklenmez (`_ext_own_csp`); mount yanıtı ve Python'dan gelen yanıt hariç | `security_headers_match_python_end_headers`, `static_assets_served_from_dist_with_headers_and_no_escape` | eşit |

### 1.5 `commands/web.py` komşu tanımlar (bilerek dışarıda; bölüm 5 iş 3-4 ile Rust'a gelenler `eşit`)

| Python adı (dosya:satır) | Rust karşılığı (dosya:satır) | parite testi (Rust) | durum |
|---|---|---|---|
| `TOKEN_FILE` (commands/web.py:114) | bu tabloda eşlenmedi | yok | kapsam dışı: `self.token` açılışta `run` içinde atanır, kapsam işlevleri doğrudan kullanmaz (Rust: `copsd::token_file`), iz atanmamış (panel açılışı) |
| `_load_or_create_token` (commands/web.py:340) | bu tabloda eşlenmedi | yok | kapsam dışı: token üretimi panel açılışında; Rust yalnız okur, iz atanmamış (panel açılışı) |
| `MAX_JSON_BODY_BYTES` (commands/web.py:4775) | bu tabloda eşlenmedi | yok | kapsam dışı: genel POST gövde sınırı; iç dal kendi 65536 sınırını kullanır, T4/T7 (yazma uçları) |
| `UNAUTHORIZED_HTML` (commands/web.py:4778) | bu tabloda eşlenmedi | yok | kapsam dışı: yalnız `_unauthorized` kullanır, kapsam işlevleri çağırmaz, T9 |
| `_Handler.HEADER_READ_TIMEOUT` (commands/web.py:4826) | `cops-proxy/src/lib.rs:1899` `HEADER_READ_TIMEOUT` 15 sn, `cops-proxy/src/lib.rs:1910` `serve_on_with` (hyper `TokioTimer` + `header_read_timeout`; boşta keep-alive bağlantısı da 15 sn'de kapanır, Python gibi) | `slow_headers_are_cut_off` | eşit |
| `_Handler.DRAIN_MAX_BYTES` (commands/web.py:4827) | bu tabloda eşlenmedi | yok | kapsam dışı: keep-alive gövde boşaltma, iz yok |
| `_Handler.DRAIN_TIMEOUT` (commands/web.py:4828) | bu tabloda eşlenmedi | yok | kapsam dışı: keep-alive gövde boşaltma, iz yok |
| `_Handler.handle_one_request` (commands/web.py:4831) | hyper bağlantı döngüsü; başlık süre sınırı bir üst satır | `slow_headers_are_cut_off` | eşit |
| `_Handler.parse_request` (commands/web.py:4840) | hyper ayrıştırıcı; iç uç kararı için Python'un `//` indirgemesi `cops-proxy/src/lib.rs:160` `python_path` | `internal_block_covers_every_form_python_would_route`, `bad_content_length_is_rejected_before_python` | eşit |
| `_Handler._declared_body_length` (commands/web.py:4850) | hyper: geçersiz/çelişkili `Content-Length` 400 (Python -1 sayıp bağlantıyı kapatır), `Transfer-Encoding` varken `Content-Length` silinir (RFC 9112 6.1) | `bad_content_length_is_rejected_before_python` | eşit (daha sıkı) |
| `_Handler._drain_body` (commands/web.py:4860) | hyper okunmamış gövdeyi boşaltır ya da bağlantıyı kapatır | `early_reject_then_second_request_on_same_connection` | eşit |
| `_Handler.log_message` (commands/web.py:4883) | bu tabloda eşlenmedi | yok | kapsam dışı: erişim günlüğünü susturur, iz yok |
| `_Handler.end_headers` (commands/web.py:4886) | `cops-proxy/src/lib.rs:145` `harden` (bölüm 1.4 son satır) | `security_headers_match_python_end_headers` | eşit |
| `_Handler._request_view` (commands/web.py:4970) | bu tabloda eşlenmedi | yok | kapsam dışı: `_client_ip`yi ÇAĞIRAN işlev, çağrılan değil (Rust: `request_view`), T9 |
| `_Handler._principal` (commands/web.py:4982) | bu tabloda eşlenmedi | yok | kapsam dışı: çok kullanıcı kimliği, listede yok, T9 |
| `_Handler._gate` (commands/web.py:4997) | bu tabloda eşlenmedi | yok | kapsam dışı: yetki kapısı, listede yok, T9 |
| `_Handler._agents_caller` (commands/web.py:5017) | bu tabloda eşlenmedi | yok | kapsam dışı: ajan kimliği (`_authorized`ı çağırır), T7 |
| `_Handler._ext_dispatch` (commands/web.py:5114) | bu tabloda eşlenmedi | yok | kapsam dışı: eklenti yolu kimliği (`_authorized`ı çağırır), T9 |
| `_Handler._unauthorized` (commands/web.py:5157) | bu tabloda eşlenmedi | yok | kapsam dışı: 401/302 yanıtı, kapsam işlevleri çağırmaz, T9 |
| `_Handler._session_lock` (commands/web.py:5302) | bu tabloda eşlenmedi | yok | kapsam dışı: uç işleyicisi (`_client_ip`yi çağırır), T7 (envanter "T7?") |
| `_Handler.do_GET` (commands/web.py:5459) | bu tabloda eşlenmedi | yok | kapsam dışı: yönlendirme başı, listede yok, T1-T10 (uç aileleri) |
| `_Handler._do_get_inner` (commands/web.py:5478) | bu tabloda eşlenmedi | yok | kapsam dışı: yönlendirme başı, listede yok, T1-T10 (uç aileleri) |
| `_Handler._question_page` (commands/web.py:5895) | bu tabloda eşlenmedi | yok | kapsam dışı: `/q/` sayfası (`_authorized`ı çağırır), T10 |
| `_Handler._PEEK_BODY_MAX` (commands/web.py:5938) | bu tabloda eşlenmedi | yok | kapsam dışı: `_peek_body` sınırı, T9 |
| `_Handler._peek_body` (commands/web.py:5940) | bu tabloda eşlenmedi | yok | kapsam dışı: gövde bağlama (`_request_view` kullanır), T9 |

### 1.6 `ws_ticket.py` (dalın ve `_authorized_ws`nin çağırdığı depo)

| Python adı (dosya:satır) | Rust karşılığı (dosya:satır) | parite testi (Rust) | durum |
|---|---|---|---|
| `TTL_SECONDS` (ws_ticket.py:13) | yok (çekirdek Rust'ta bilet deposu yok) | yok | kapsam dışı: bilet deposu Python belleğinde, T2 |
| `MAX_PENDING` (ws_ticket.py:14) | yok (çekirdek Rust'ta bilet deposu yok) | yok | kapsam dışı: bilet deposu Python belleğinde, T2 |
| `_LOCK` (ws_ticket.py:16) | yok (çekirdek Rust'ta bilet deposu yok) | yok | kapsam dışı: bilet deposu Python belleğinde, T2 |
| `_TICKETS` (ws_ticket.py:17) | yok (çekirdek Rust'ta bilet deposu yok) | yok | kapsam dışı: bilet deposu Python belleğinde, T2 |
| `_BOUND` (ws_ticket.py:18) | yok (çekirdek Rust'ta bilet deposu yok) | yok | kapsam dışı: bilet deposu Python belleğinde, T2 |
| `issue` (ws_ticket.py:21) | yok (çekirdek Rust'ta bilet deposu yok) | yok | kapsam dışı: bilet deposu Python belleğinde, T2 |
| `consume_principal` (ws_ticket.py:39) | yok (çekirdek Rust'ta bilet deposu yok) | yok | kapsam dışı: bilet deposu Python belleğinde, T2 |
| `consume` (ws_ticket.py:50) | yok (çekirdek Rust'ta bilet deposu yok) | yok | kapsam dışı: bilet deposu Python belleğinde, T2 |
| `consume_full` (ws_ticket.py:61) | yok (çekirdek Rust'ta bilet deposu yok) | yok | kapsam dışı: bilet deposu Python belleğinde, T2 |

### 1.7 `authz.py` (dalın doğrudan çağırdıkları)

| Python adı (dosya:satır) | Rust karşılığı (dosya:satır) | parite testi (Rust) | durum |
|---|---|---|---|
| `UNMAPPED` (authz.py:18) | `cops-auth/src/authz.rs:10` | `table_is_identical_in_order` | eşit |
| `Principal` (authz.py:22) | `cops-auth/src/authz.rs:22` (`kind` enum) | `legacy_principal_matches_python` | eşit |
| `Principal.has_role` (authz.py:28) | `cops-auth/src/authz.rs:39` | `legacy_principal_matches_python` | eşit |
| `LEGACY` (authz.py:32) | `cops-auth/src/authz.rs:30`, `cops-auth/src/authz.rs:12` | `legacy_principal_matches_python` | eşit |
| `Resource` (authz.py:36) | `cops-auth/src/authz.rs:46`, varsayılan `global` | `resources_match_python` | eşit |
| `RequestView` (authz.py:45) | `cops-auth/src/authz.rs:68`: `body_fn` yok, `client_ip` soket eşi (güvenilen IP: `cops-proxy/src/front.rs:222` `view_client_ip`), sorgu/çerez ham | `duplicate_cookie_takes_last_and_header_takes_first`, `hook_sees_lowercase_headers_and_is_not_asked_for_post_or_proxied_requests`, `python_sees_real_client_with_or_without_secret` | kapsam dışı: `body_fn` (imzalı kimlik iletimi gövde bağlama) T9, bölüm 5 iş 8 |
| `_ACTION_TABLE` (authz.py:59) | `cops-auth/src/authz.rs:133` | `table_is_identical_in_order` | eşit |
| `action_for` (authz.py:151) | `cops-auth/src/authz.rs:207` (sabit tablo; eklenti kaydı bir alttaki satır) | `action_for_matches_python` | eşit |
| `has_authenticator` (authz.py:211) | karşılığı "kanca takılı mı": `copsd/src/lib.rs:143` (`Hooks`) | `without_hook_behaviour_is_unchanged` | kapsam dışı: sağlayıcı enterprise'ta, T9 |
| `authenticate` (authz.py:283) | `cops-proxy/src/gate.rs:247` (`Gate`, fail-closed; copsd'ye bağlı değil) | `authentication_failures_are_401_and_not_audited` | kapsam dışı: sağlayıcı enterprise'ta, T9 |
| `check` (authz.py:305) | `cops-proxy/src/gate.rs:247` (yetki + denetim; yetkilendirici yoksa "izin" varsayılanı yok) | `authorization_failures_are_403_and_audited`, `every_resource_must_be_allowed_and_empty_list_is_denied` | kapsam dışı: sağlayıcı enterprise'ta, T9 |
| `action_for` içindeki eklenti eylemi araması (`_EXT_ACTIONS`) (authz.py:158) | taşınmadı: `/api/enterprise/*` Rust'ta `admin.unmapped` | yok | kapsam dışı: eklenti eylem kaydı (`register_action`) T9, bölüm 5 iş 8 |
| `action_for` özel durumları (`/`, GET `/api/ucli/approvals`) (authz.py:153) | `cops-auth/src/authz.rs:207` | `action_for_matches_python` | eşit |

## 2. Python testleri

"Rust karşılığı" sütunu test eşlemesinde karşılık ya da neden gereksiz olduğudur. Kalıtımla ikinci kez koşan sınıfların metotları tanımlandığı sınıfta bir kez yazıldı.

| Python testi (dosya:satır) | Rust karşılığı / neden | parite testi (Rust) | durum |
|---|---|---|---|
| `T.test_execstart_patch` (tests/test_front_cmd.py:13) | gereksiz: CLI taşınmadı | yok | kapsam dışı: `cops front` CLI Python'da, T6 |
| `T.test_dropin_resets_execstart` (tests/test_front_cmd.py:19) | gereksiz: CLI taşınmadı | yok | kapsam dışı: `cops front` CLI Python'da, T6 |
| `T.test_plan_blockers` (tests/test_front_cmd.py:23) | gereksiz: CLI taşınmadı | yok | kapsam dışı: `cops front` CLI Python'da, T6 |
| `T.test_unit_template_has_no_secret` (tests/test_front_cmd.py:30) | gereksiz: CLI taşınmadı | yok | kapsam dışı: `cops front` CLI Python'da, T6 |
| `T.test_applied_unit_passes_the_secret_state_dir` (tests/test_front_cmd.py:35) | gereksiz: CLI taşınmadı | yok | kapsam dışı: `cops front` CLI Python'da, T6 |
| `Secret.test_ensure_creates_0600_and_is_stable` (tests/test_front_internal.py:21) | gereksiz: Rust gizli üretmez | yok | kapsam dışı: `cops front` CLI Python'da, T6 |
| `Secret.test_loose_permissions_are_not_trusted` (tests/test_front_internal.py:28) | `FrontSecret::current` (açılışta ve çalışırken gizli yok) | `file_secret_follows_changes_and_fails_closed`, `runtime_secret_changes_apply_without_restart`, `startup_ignores_unusable_secret_file_and_warns` | eşit |
| `Secret.test_env_wins_and_missing_is_empty` (tests/test_front_internal.py:76) | `FrontSecret::from_env_or_file`, copsd açılışı | `file_secret_follows_changes_and_fails_closed` (yok = gizli yok), `ctx_front_follows_secret_rotation` (dosya kaynağı), `trusted_front_needs_secret_loopback_and_exact_header` | eşit |
| `Secret.test_trusted_front` (tests/test_front_internal.py:81) | `FrontSecret::trusted` | `trusted_front_needs_secret_loopback_and_exact_header` (loopback dışı eş, boş gizli, yanlış başlık) | eşit |
| `Secret.test_secret_follows_state_dir` (tests/test_front_internal.py:16) | copsd `secret_file` | `default_secret_path_follows_state_dir` | eşit |
| `Secret.test_leaked_secret_is_replaced_not_reused` (tests/test_front_internal.py:33) | gereksiz: Rust gizli üretmez; yenilenen değeri yeniden okur | `runtime_secret_changes_apply_without_restart`, `ctx_front_follows_secret_rotation` (yalnız okuma) | kapsam dışı: `cops front` CLI Python'da, T6 |
| `Secret.test_empty_or_corrupt_file_is_replaced` (tests/test_front_internal.py:41) | gereksiz: Rust gizli üretmez; boş/bozuk = gizli yok | `file_secret_follows_changes_and_fails_closed` (yalnız okuma) | kapsam dışı: `cops front` CLI Python'da, T6 |
| `Secret.test_concurrent_ensure_returns_the_value_on_disk` (tests/test_front_internal.py:50) | gereksiz: Rust gizli üretmez | yok | kapsam dışı: `cops front` CLI Python'da, T6 |
| `Secret.test_non_utf8_file_means_no_secret` (tests/test_front_internal.py:69) | `read_secret_file`: UTF-8 değil = gizli yok | `file_secret_follows_changes_and_fails_closed`, `startup_ignores_unusable_secret_file_and_warns` | eşit |
| `Authz.test_legacy_token_via_query_and_bearer` (tests/test_front_internal.py:92) | iç uç Rust'ta sunulmuyor | `query_and_bearer_accept_empty_token_is_closed_non_ascii_rejected` (yalnız token kuralı) | kapsam dışı: iç uç sunucusu Python'da, T9 |
| `Authz.test_empty_token_fails_closed` (tests/test_front_internal.py:100) | iç uç Rust'ta sunulmuyor | `query_and_bearer_accept_empty_token_is_closed_non_ascii_rejected` (yalnız token kuralı) | kapsam dışı: iç uç sunucusu Python'da, T9 |
| `Authz.test_authenticator_and_authorizer_are_used` (tests/test_front_internal.py:104) | iç uç Rust'ta sunulmuyor | `authorization_failures_are_403_and_audited` (yalnız `Gate`) | kapsam dışı: iç uç sunucusu Python'da, T9 |
| `Authz.test_resource_steward_reaches_authorizer` (tests/test_front_internal.py:120) | iç uç Rust'ta sunulmuyor | yok | kapsam dışı: iç uç sunucusu Python'da, T9 |
| `Authz.test_ws_ticket_fallback_for_ws_paths` (tests/test_front_internal.py:135) | iç uç Rust'ta sunulmuyor | yok | kapsam dışı: iç uç sunucusu Python'da, T9 |
| `Ticket.test_consume_once_bound_and_unbound` (tests/test_front_internal.py:143) | bilet deposu yok | yok | kapsam dışı: bilet deposu Python'da, T2 |
| `Ticket.test_expired` (tests/test_front_internal.py:153) | bilet deposu yok | yok | kapsam dışı: bilet deposu Python'da, T2 |
| `Wiring.test_internal_branch_guarded_before_auth` (tests/test_front_internal.py:160) | Python kaynak sırası denetimi; Rust eşdeğeri dış engelin her şeyden önce olması | `internal_paths_are_never_forwarded` (mount önceliği ayrıca sınanmıyor) | kapsam dışı: iç uç sunucusu Python'da, T9 |
| `CspParity.test_rust_csp_equals_python_csp` (tests/test_front_internal.py:172) | gereksiz: bu Python testi `cops-proxy` `CSP` sabitini okuyup karşılaştırır (parite testinin kendisi) | yok | kapsam dışı: ayrı Rust testi gereksiz, iz yok |
| `XFF.test_no_secret_ignores_header` (tests/test_front_xff.py:11) | `front::trusted_client_ip` (aynı vektör) | `trusted_client_ip_matches_python_test_front_xff` | eşit |
| `XFF.test_wrong_or_missing_secret` (tests/test_front_xff.py:14) | `front::trusted_client_ip` (aynı vektör) | `trusted_client_ip_matches_python_test_front_xff` | eşit |
| `XFF.test_non_loopback_peer_never_trusted` (tests/test_front_xff.py:18) | `front::trusted_client_ip` (aynı vektör) | `trusted_client_ip_matches_python_test_front_xff` | eşit |
| `XFF.test_tunnel_client_ip_only_from_loopback` (tests/test_front_xff.py:21) | `front::trusted_client_ip` (aynı vektör) | `trusted_client_ip_matches_python_test_front_xff` | eşit |
| `XFF.test_valid_secret_uses_last_xff` (tests/test_front_xff.py:40) | `front::trusted_client_ip` (aynı vektör) | `trusted_client_ip_matches_python_test_front_xff` | eşit |
| `XFF.test_route_request_uses_trusted_ip` (tests/test_front_xff.py:30) | eklenti `RouteRequest` | yok | kapsam dışı: eklenti yolları Python'da, T9 |
| `BodyTimeout.test_read_ok_restores_previous_timeout` (tests/test_post_body_timeout.py:37) | gereksiz: soket zaman aşımı durumu yok | yok | kapsam dışı: Python soket ayrıntısı, iz yok |
| `BodyTimeout.test_slow_body_raises` (tests/test_post_body_timeout.py:44) | `run_hook` süre aşımı | `slow_body_times_out_with_408` | eşit |
| `BodyTimeout.test_short_body_raises` (tests/test_post_body_timeout.py:50) | `read_body_limited` kısa gövde = 408 | `short_body_is_408_and_closes` | eşit |
| `BodyTimeout.test_do_post_maps_to_408_and_closes` (tests/test_post_body_timeout.py:54) | `run_hook`: 408 JSON (Python ile aynı alanlar) + `Connection: close` | `slow_body_times_out_with_408`, `short_body_is_408_and_closes` | eşit |
| `BodyTimeout.test_real_socket_slow_body_gets_408` (tests/test_post_body_timeout.py:63) | gerçek sokette 408 + kapanış | `slow_body_times_out_with_408` | eşit |
| `AuthFailClosed.test_empty_server_token_never_authorizes` (tests/test_post_body_timeout.py:90) | `Token::authorized` | `query_and_bearer_accept_empty_token_is_closed_non_ascii_rejected` | eşit |
| `AuthFailClosed.test_valid_token_still_ok` (tests/test_post_body_timeout.py:99) | `Token::authorized` | `query_and_bearer_accept_empty_token_is_closed_non_ascii_rejected` | eşit |
| `WsTicket.test_single_use` (tests/test_ws_ticket.py:13) | bilet deposu yok | yok | kapsam dışı: bilet deposu Python'da, T2 |
| `WsTicket.test_expires` (tests/test_ws_ticket.py:18) | bilet deposu yok | yok | kapsam dışı: bilet deposu Python'da, T2 |
| `WsTicket.test_unknown_and_empty` (tests/test_ws_ticket.py:22) | bilet deposu yok | yok | kapsam dışı: bilet deposu Python'da, T2 |
| `WsTicket.test_cap_drops_oldest` (tests/test_ws_ticket.py:26) | bilet deposu yok | yok | kapsam dışı: bilet deposu Python'da, T2 |
| `HandlerWiring.test_ws_accepts_ticket_once_and_legacy_token` (tests/test_ws_ticket.py:43) | `/ws` aktarılır | yok | kapsam dışı: bilet deposu Python'da, T2 |
| `HandlerWiring.test_ticket_does_not_authorize_rest` (tests/test_ws_ticket.py:52) | Rust yerel uçlarda bilet kavramı yok | yok | kapsam dışı: bilet deposu Python'da, T2 |
| `CallerTests.test_agent_token_is_not_a_panel_token` (tests/test_web_agents_glue.py:41) | yerel uç yalnız `web.token` kabul eder | `panel_entries_need_token_own_auth_entries_do_not` | eşit |
| `Routes.test_no_auth_is_401_and_wrong_cookie` (tests/test_extensions_routes.py:80) | `_ext_dispatch` Rust'ta yok | yok | kapsam dışı: eklenti yolları Python'da, T9 |
| `Routes.test_token_sets_cookie_cookie_then_works` (tests/test_extensions_routes.py:88) | `_ext_dispatch` Rust'ta yok | yok | kapsam dışı: eklenti yolları Python'da, T9 |
| `Routes.test_post_with_cookie_needs_header` (tests/test_extensions_routes.py:102) | `_ext_dispatch` Rust'ta yok | yok | kapsam dışı: eklenti yolları Python'da, T9 |
| `Routes.test_own_csp_flag_set_only_when_extension_sends_csp` (tests/test_extensions_routes.py:111) | `_ext_dispatch` Rust'ta yok | yok | kapsam dışı: eklenti yolları Python'da, T9 |
| `Routes.test_plugin_error_is_500` (tests/test_extensions_routes.py:121) | `_ext_dispatch` Rust'ta yok | yok | kapsam dışı: eklenti yolları Python'da, T9 |
| `Routes.test_cookie_does_not_open_core_api` (tests/test_extensions_routes.py:127) | `try_local`, `try_metrics`, `try_table`, `try_stats` çerezi kimlik saymaz | `cops_ext_cookie_does_not_open_local_api` | eşit |
| `ApiRoutes.test_token_ok_and_principal` (tests/test_extensions_routes.py:245) | K12 yolu Rust çekirdekte yok | yok | kapsam dışı: eklenti yolları Python'da, T9 |
| `ApiRoutes.test_no_token_401_and_cookie_not_accepted` (tests/test_extensions_routes.py:251) | K12 yolu Rust çekirdekte yok | yok | kapsam dışı: eklenti yolları Python'da, T9 |
| `ApiRoutes.test_post_requires_json` (tests/test_extensions_routes.py:259) | K12 yolu Rust çekirdekte yok | yok | kapsam dışı: eklenti yolları Python'da, T9 |
| `ApiRoutes.test_gate_uses_action_and_forbids` (tests/test_extensions_routes.py:264) | K12 yolu Rust çekirdekte yok | yok | kapsam dışı: eklenti yolları Python'da, T9 |
| `Endpoint.test_human_confirm_logged` (tests/test_session_lock.py:125) | `_client_ip` kullanan uç Rust'ta yok | yok | kapsam dışı: kilit ucu Python'da, T7 (envanter "T7?") |
| `Endpoint.test_remote_host_refused` (tests/test_session_lock.py:132) | `_client_ip` kullanan uç Rust'ta yok | yok | kapsam dışı: kilit ucu Python'da, T7 (envanter "T7?") |
| `Endpoint.test_non_human_actor_and_agent_token_refused` (tests/test_session_lock.py:137) | `_client_ip` kullanan uç Rust'ta yok | yok | kapsam dışı: kilit ucu Python'da, T7 (envanter "T7?") |
| `Endpoint.test_unlock_disabled_is_403` (tests/test_session_lock.py:148) | `_client_ip` kullanan uç Rust'ta yok | yok | kapsam dışı: kilit ucu Python'da, T7 (envanter "T7?") |
| `PeekBodyTest.test_peek_then_read_same_bytes` (tests/test_outbound_signer.py:137) | `_read_body` önbelleği Rust'ta yok | yok | kapsam dışı: imzalı gövde bağlama Python'da, T9 |
| `PeekBodyTest.test_cache_not_leaked_to_next_request` (tests/test_outbound_signer.py:143) | `_read_body` önbelleği Rust'ta yok | yok | kapsam dışı: imzalı gövde bağlama Python'da, T9 |
| `PeekBodyTest.test_too_large_returns_none` (tests/test_outbound_signer.py:151) | `_read_body` önbelleği Rust'ta yok | yok | kapsam dışı: imzalı gövde bağlama Python'da, T9 |
| `Post.test_posts_with_front_secret_and_swallows_errors` (tests/test_metrics_push.py:28) | alıcı taraf `try_metrics` | `points_series_names_with_auth` | kapsam dışı: gönderici Python'da, T7 |
| `AuthzVectorsTest.test_vectors_match_python` (tests/test_authz_vectors.py:97) | aynı vektör dosyasını Rust okur | `table_is_identical_in_order`, `action_for_matches_python`, `legacy_principal_matches_python`, `token_query_matches_python_parse_qs`, `resources_match_python` | eşit |
| `DefaultsTest.test_no_hooks_is_noop` (tests/test_authz.py:27) | kancasız varsayılan | `without_hook_behaviour_is_unchanged` (`check`/süzgeç varsayılanı yok) | kapsam dışı: yetki kancaları enterprise, T9 |
| `DefaultsTest.test_every_web_path_has_an_action` (tests/test_authz.py:34) | Python kaynak taraması; Rust tablosu birebir | `table_is_identical_in_order` | kapsam dışı: Python kaynak denetimi, iz yok |
| `DefaultsTest.test_uzakgoz_freshness_is_read_only_mapped` (tests/test_authz.py:40) | `action_for` vektörleri | `action_for_matches_python` | eşit |
| `DefaultsTest.test_unknown_path_unmapped` (tests/test_authz.py:43) | `action_for` vektörleri | `action_for_matches_python` | eşit |
| `DefaultsTest.test_fail_closed` (tests/test_authz.py:48) | `Gate` (süzgeç K3 yok) | `authentication_failures_are_401_and_not_audited`, `authorization_failures_are_403_and_audited` | kapsam dışı: yetki kancaları enterprise, T9 |
| `HttpTest.test_legacy_token_unchanged_without_hooks` (tests/test_authz.py:87) | yerel uçta token ile 200, tokensız 401 | `hook_verdicts_apply_and_default_keeps_the_token_path`, `questions_endpoint_is_local_authenticated_and_everything_else_proxies` | eşit |
| `HttpTest.test_authenticator_replaces_token_and_401` (tests/test_authz.py:91) | `LocalAuth` kararı token'ı ezer | `hook_verdicts_apply_and_default_keeps_the_token_path` | kapsam dışı: sağlayıcı enterprise, T9 |
| `HttpTest.test_ticket_keeps_panel_cookie_in_single_user` (tests/test_authz.py:177) | `/api/files/ticket` Rust'ta yok | yok | kapsam dışı: dosya ucu Python'da, T3 |
| `TicketAndQuestionTest.test_ws_ticket_bound_to_principal` (tests/test_authz.py:358) | bilet deposu yok | yok | kapsam dışı: bilet deposu Python'da, T2 |
| `TicketAndQuestionTest.test_ticket_replaces_cookie_for_ws_only` (tests/test_authz.py:368) | bilet deposu yok | yok | kapsam dışı: bilet deposu Python'da, T2 |
| `MirrorRouteHttpTests.test_token_is_required` (tests/test_mirror_window.py:340) | uç aktarılır, 401 Python'dan | yok | kapsam dışı: uç Python'da, T2 |
| `TestApi.test_post_flow_ignores_host_field` (tests/test_labels.py:186) | uç aktarılır, 401 Python'dan | yok | kapsam dışı: uç Python'da, T7 (envanter "T7?") |
| `TermHistoryRouteTests.test_it_needs_the_token` (tests/test_term_history.py:243) | uç aktarılır, 401 Python'dan | yok | kapsam dışı: uç Python'da, T2 |
| `UnreadBodyTests.test_401_then_valid_request_on_same_socket` (tests/test_web_unread_body.py:60) | yerel 401/413 sonrası aynı bağlantı: hyper boşaltır ya da kapatır | `early_reject_then_second_request_on_same_connection` | eşit |
| `QuestionPageHttpTest.test_question_page_round_trip` (tests/test_steward_core_b.py:693) | `/q/` aktarılır | yok | kapsam dışı: uç Python'da, T10 |

## 3. Kenar durumları

| durum | Python | Rust | sonuç / test |
|---|---|---|---|
| boş sunucu token'ı | her istek red | red | aynı; `query_and_bearer_accept_empty_token_is_closed_non_ascii_rejected` |
| boş aday (`?token=`, `Bearer `) | red | red | aynı; aynı test |
| yinelenen / boş / yüzde kodlu `token` parametresi | `parse_qs` ilk dolu | aynı | `token_query_matches_python_parse_qs` |
| ASCII dışı aday | `TypeError` yutulur, red | red | aynı |
| `Authorization` yok | aday yalnız sorgu | aynı | aynı |
| yinelenen `Authorization` | ilk satır | ilk satır | koddan; test yok |
| `Bearer` sonunda `0x85`/`0xA0` | kırpılır, geçer | başlık yok sayılır, 401 | Rust daha sıkı; `bearer_with_trailing_latin1_space_is_rejected` |
| `web.token` dosyası yok / gevşek izin | açılışta üretir ya da 0600'e çeker | boş = kapalı; açılışta yoksa yerel uç hiç açılmaz | farklı; `file_token_follows_rotation_deletion_and_mode` |
| `web.token` çalışırken değişir | eski değer yeniden başlatmaya dek | yeni değer hemen | iki süreç yeniden başlatmaya dek farklı token kabul eder |
| `front.secret` yok | boş: başlığa güvenilmez | gizli eklenmez; uzak eşin adresi `Cf-Connecting-IP` ile iletilir (`pin_client_ip`) | Python uzak istemciyi gerçek adresiyle görür, loopback DEĞİL; tünel yolu aynı; `python_sees_real_client_with_or_without_secret`, `front_secret_file_is_reread_and_fails_closed` |
| `front.secret` açılıştan sonra oluşur / değişir / silinir | her çağrıda taze | her istekte `stat`, imza değişince yeniden okunur | aynı; `file_secret_follows_changes_and_fails_closed`, `runtime_secret_changes_apply_without_restart` (kaba zaman damgası içinde aynı inode ve boyla iki yazım istisnası, `docs/rs-gate.md`) |
| `front.secret` boş ya da yalnız boşluk | "" | gizli yok | aynı (kırpma `cops_auth::py_strip` = Python `strip`, U+001C..U+001F dahil); `file_secret_follows_changes_and_fails_closed` |
| `front.secret` gevşek izin | "" (panel çalışır) | gizli yok, süreç sürer; açılışta uyarı | aynı; `startup_ignores_unusable_secret_file_and_warns`, `runtime_secret_changes_apply_without_restart` |
| `front.secret` UTF-8 değil | gizli yok (`test_non_utf8_file_means_no_secret`; düzeltme `f7dedcc`) | gizli yok, süreç sürer; açılışta uyarı | aynı; `file_secret_follows_changes_and_fails_closed`, `startup_ignores_unusable_secret_file_and_warns` |
| `front.secret` yolu, `CLAUDEOPS_DIR` farklı | durum dizinini izler (`31ff561`) | durum dizinini izler (`31ff561`) | eşit; `test_secret_follows_state_dir`, `default_secret_path_follows_state_dir` |
| `X-Cops-Front` yok / yanlış | güvenilmez | aynı | `trusted_front_needs_secret_loopback_and_exact_header`, `front_secret_file_is_reread_and_fails_closed` |
| istemcinin sahte `X-Cops-Front` / `X-Forwarded-For` | (Rust arkasında görmez) | siler / ezer | `front_secret_is_injected_and_client_copy_dropped`, `forwards_and_overwrites_x_forwarded_for` |
| uzak eşin sahte `Cf-Connecting-IP` | yok sayılır | silinir | `cf_connecting_ip_survives_only_from_loopback_peer` |
| `//x/api/_internal/...` hedefi | 3.10.12 `parse_request` baştaki `//`yi teke indirir: yol `/x/api/...`, iç uç değil | aktarır; Python'un iç uç sayacağı her biçim (`//api/...`, mutlak biçim) `python_path` ile engellenir | `internal_block_covers_every_form_python_would_route` |
| iç uçta eksik `Content-Length` | gövde `{}` sayılır | dıştan 404 | Python içi |
| yavaş gövde | 60 sn soket zaman aşımı, 408 JSON | kanca ve metrik POST'ta 10 sn toplam, 408 JSON + kapanış | Rust daha sıkı; `slow_body_times_out_with_408`, `short_body_is_408_and_closes` |
| yavaş başlık (slowloris) | 15 sn | 15 sn (`HEADER_READ_TIMEOUT`, hyper `TokioTimer`) | aynı; `slow_headers_are_cut_off` |
| erken kopan gövde | 408 | 408 + kapanış | aynı; `short_body_is_408_and_closes` |
| eşzamanlı bilet tüketimi | kilit altında tek kullanım | Python'a aktarılır | kapsam dışı T2 |
| eşzamanlı `ensure_secret` | kilit + atomik değiştirme, tek değer (`5737ae8`, `test_concurrent_ensure_returns_the_value_on_disk`) | üretmez | kapsam dışı T6 |
| yanıt yazılırken bağlantı koparsa | `diag_log`, yutulur | hyper bağlantıyı bırakır | günlük satırı yok |

## 4. Referans: `force_proxy`

Python çekirdeğinde karşılığı yoktur. Enterprise geri alma bayrağıyla karşılaştırma public belgede tutulmaz (private notlarda). Çekirdek testleri:
`force_proxy_sends_local_routes_upstream_until_reloaded`, `force_file_parsing_and_failure_modes`, `sighup_reloads_force_proxy_and_stats_count_it`,
`force_proxy_size_limits`. Enterprise geri alması çekirdek dosyasıyla yapılmaz (`docs/rs-gate.md`).

## Python hatası?

Sahip cevabı (TBD#371, 26 Kas): 1-3 şimdi iki tarafta düzeltildi; 4-6 `cops front` Rust'a taşınırken (T6), 7 enterprise taşımasında (T9).
Aşağıdaki metin düzeltme ÖNCESİ bulgudur (satır numaraları `04c91cb`).

| bulgu | durum |
|---|---|
| 1 | [x] `f7dedcc` |
| 2a, 2b | [x] `5737ae8` (sızmış, boş, bozuk gizli yeniden üretilir; kilit + `os.replace`) |
| 3 | [x] `31ff561` (Python ve copsd) |
| 4, 5, 6 | [ ] AÇIK: T6 |
| 7 | [ ] AÇIK: T9 |

1. **Doğrulandı (26 Kas, yalıtılmış geçici `HOME`, `python3 -I`, `sys.path` = `py`):** bozuk UTF-8 `front.secret` (0600) ile
   `read_secret()` ve `trusted_front()` `UnicodeDecodeError` fırlattı. `front.py:26-33` `read_secret` yalnız `OSError` yakalar. `front.secret` UTF-8 olmayan bayt içerirse (bozuk dosya)
   `UnicodeDecodeError` yükselir: `/api/_internal/*` 400 döner (`do_POST` `ValueError` yakalar), çok kullanıcı kipinde
   `_client_ip` çağıran GET yanıtsız kopar, `cops front status` izleme dökümü verir, `metrics_push.py:33` iş parçacığı ölür.
2. **(a) doğrulandı (aynı koşu):** 0644 ve dolu dosyada `read_secret()` `""` döndü; ardından `ensure_secret()` izni 0600 yapıp
   AYNI değeri (`sizmis-gizli`) döndürdü. (b) doğrulanmadı (yarış, koşulmadı). `front.py:36-54` `ensure_secret`: (a) dosya 0644 ve doluysa `read_secret` "sızmış sayılır" deyip reddeder, `ensure_secret`
   ise izni 0600 yapıp AYNI gizliyi yeniden kullanır. (b) "atomik, O_EXCL" değil: A boş dosyayı açıp henüz yazmamışken B boş
   okur, `O_TRUNC` ile kendi değerini yazar; A diskte olmayan bir gizli döndürebilir.
3. `front.py:17-18` `secret_path` `CLAUDEOPS_DIR`yi yok sayar (`web.token` izler, `paths.py:45`): geçici durum dizinli deneme
   paneli ya da `cops front on` CANLI `front.secret`i okur/üretir. Rust da aynı davranıyor.
4. `commands/front_cmd.py:71-72, 79-83` `--internal 28765` (iki nokta yok) önce `port_busy`de `connect_ex(("", 28765))` olarak
   geçer, birime `--host  --port 28765` yazılabilir; sayı olmayan port `ValueError` dökümü; `[::1]:28765` AF_INET sokette hata verir.
5. `commands/front_cmd.py:102, 128-134` drop-in varken `--internal` BAŞKA bir sürecin tuttuğu porta verilirse engel atlanır ve
   `reapply` sayılır: web yeniden başlamaz, ön kapı yabancı porta vekillik eder.
6. `commands/front_cmd.py:143-138, 148-155` geri sarma yok: web iç porta geçtikten sonra front başlatılamazsa dış port boş
   kalır. `off` `disable --now` sonucunu yok sayar; front hâlâ dinliyorsa web dış porta bağlanamaz.
7. `front.py:82-86` `_H` yalnız `get`i harf duyarsız yapar; eklenti `view.headers["Authorization"]` ya da `in` kullanırsa gerçek
   istekten (`http.client.HTTPMessage`) farklı davranır.

## 5. Yapılacak Rust işleri (öncelik sırasıyla)

Durum 26 Kas gece (çalışma ağacı, commit yok). Ayrıntı ve testler `docs/rs-gate.md` "Bu turun işleri".

1. [x] **copsd varsayılan `--upstream`** 28765 (`copsd::DEFAULT_UPSTREAM`, USAGE, modül belgesi); `default_upstream_matches_python_front_cmd`.
2. [x] **Gizli yaşam döngüsü:** `front::FrontSecret` (dosya imzasıyla yeniden okuma); açılışta ve çalışırken yok/gevşek/bozuk = gizli yok,
   süreç sürer (birleştirme kapısı madde 3; açılışta uyarı). Gizli yokken uzak istemci: copsd uzak eşin adresini
   `Cf-Connecting-IP`ye yazar (`pin_client_ip`), Python `_client_ip` loopback adımında gerçek adresi bulur; tünel yolu değişmez
   (gerekçe `docs/rs-gate.md`). `read_secret` testleri: ortam önceliği, boş, 0644, bozuk UTF-8, dizin, 64 KiB.
3. [x] **Başlık okuma süre sınırı** 15 sn (`HEADER_READ_TIMEOUT`); metrik POST gövdesi 10 sn ve bildirilen boy sınırı.
4. [x] **Güvenlik başlıkları:** `harden` (Python `end_headers` kümesi), mount ve Python'dan gelen yanıt hariç.
5. [x] **İç uç engeli derinliği:** `python_path` + `is_internal_target`; her yöntem, `//`, mutlak biçim testi; 404 gövdesi Python gibi.
6. [x] **Güvenilen istemci IP'si:** `front::trusted_client_ip`, `front::view_client_ip`; `test_front_xff.py` vektörleri.
   `RequestView`e alan EKLENMEDİ (enterprise yapı ifadesiyle kuruyor: kırıcı olurdu).
7. [x] **Eksik testler:** `trusted_front` loopback dışı eş ve boş gizli; `cops_ext` çerezi; eksik gövde 408 (karar: Python gibi
   408 + kapanış, kanca çağrılmaz); yerel ret sonrası aynı bağlantı; `force_proxy` 512 satır / 64 KiB.
8. [ ] `RequestView` için `body_fn` karşılığı ve eklenti eylem kaydı (`register_action`): YAPILMADI, T9 ile. Gerekçe: ikisinin de
   tek tüketicisi enterprise (imzalı kimlik iletimi gövde bağlama, eklenti `/api/enterprise/*` eylemleri); çekirdek Rust'ta
   bugün gövde isteyen kimlik doğrulayıcı ya da eklenti yolu yok. `RequestView`e alan eklemek `copsd-ent` testlerini kırar
   (yapı ifadesi), T9'da iki repo birlikte değişmeli.
9. [x] `cops-parity` gerçek Python iç portuna karşı: 26 Kas, commit `174c18e`, `requests/basic.json`, yalnız GET (varsayılan
   `side_effect_free`), 7/7 istek fark 0, üç ardışık koşu; yedi isteğin yedisini de Python cevapladı (`X-Cops-Served: python`).
   Liste bugün yerel Rust ucu içermiyor: yerel uç paritesi T1+ izlerinin kendi istek listeleriyle.

## 6. Sayım özeti

| durum | Python tanım/davranış satırı | Python test satırı | toplam |
|---|---|---|---|
| eşit | 32 | 23 | 55 |
| eşit (daha sıkı) | 5 | 0 | 5 |
| kod var, test yok | 0 | 0 | 0 |
| eksik (Rust'ta karşılığı yok) | 0 | 0 | 0 |
| kapsam dışı | 66 | 54 | 120 |
| **toplam** | **103** | **77** | **180** |

Önceki sayım (taban `174c18e`): eşit 20, kod var/test yok 21, eksik 13, kapsam dışı 119. `kapsam dışı`ndan çıkanlar bölüm 1.5'in altı
satırı (`HEADER_READ_TIMEOUT`, `handle_one_request`, `parse_request`, `_declared_body_length`, `_drain_body`, `end_headers`: artık Rust'ta); giren iki satır bölüm 1.7 `body_fn` ve eklenti eylem
kaydı (iş 8, T9).

## 7. Eksiksizlik denetimi (`ast`)

Betik (oturum scratchpad'inde, repoya girmedi) üretilen tabloyu kaynaktan ayrıca denetledi: `front.py`, `front_cmd.py`,
`ws_ticket.py` içindeki her işlev, sınıf, iç içe tanım ve modül/sınıf düzeyi atama; `web.py`de dört kapsam işlevi ile
`/api/_internal/` dalının `ast` yürüyüşünde adı geçen her modül/`_Handler` tanımı (+ elle seçilen dolaylı bağımlılıklar ve bölüm 1.5 komşuları); `authz.*`
çağrıları; beş tam test dosyasının her `test_*` metodu ve diğer dosyalarda gövdesinde kapsam adı geçen her test. Her biri
ad VE satır numarasıyla arandı. `do_POST` ile dolaylı sınayan testler (mirror, labels, history, unread body, soru sayfası,
`authz` varsayılanları) elle seçildi; denetim bunların seçim eksikliğini yakalayamaz. Geçerli token'la yalnız mutlu yolu
geçen gerçek sunucu testleri (ör. `test_term_viewport.py`, `test_term_dedup.py`) ile `test_web_unread_body.py`nin diğer
(`end_headers` boşaltma) testleri, `_gate`/`_agents_caller`/`_question_page` işlev testleri alınmadı.

Sonuç (taban turu): tanım: 80 zorunlu ad (front 9, front_cmd 16, web 39 [14 kapsam, bunun 7 tanesi ast yürüyüşünden + 25 komşu], ws_ticket 9, authz 7); test: 43 zorunlu metot; eksik: 0; boş hücreli satır: 0. Bu tur (Python dosyaları değişmediği için ad kümesi aynı): o turda satır sayısı 102 + 71 idi (26 Kas birleştirme kapısı turunda bir tanım ve altı test satırı eklendi), belgede adı geçen farklı Rust test adı 53, hepsi `rust/crates` altında `#[test]`/`#[tokio::test]` olarak bulundu; belgedeki her `dosya:satır` başvurusu betikle açılıp tanımla karşılaştırıldı.
