# rs/cli (İz T6: Rust `cops` CLI)

**Durum (26 Kas 2026 gece): BİRLEŞTİRMEYE HAZIR** (kod + eşlik tablosu + ders listesi). Canlıda `cops-rs` kullanılmadan ÖNCE `bin/cops-py` kurulumu gerekir (bkz. Bilinen açıklar); `list` `cops-procscan` birleşince bağlanır.

## Doğrulama (26 Kas, `22348088`; gözden geçiren alt ajanın koşusu)

`cargo test -p cops-cli` 80 geçti 0 kaldı (son test eklendikten sonra); önceki uçta workspace `cargo test` 225 geçti 0 kaldı; `cargo clippy --all-targets -- -D warnings`
(workspace) ve `cargo fmt -p cops-cli --check` temiz. Python dosyası değişmedi, Python tam paketi koşulmadı. Testler yalıtık
HOME/CLAUDEOPS_DIR ve sahte systemctl ile; canlı birimlere ve `front.secret`e dokunulmadı.

## Crate (`rust/crates/cops-cli`, ikili `cops-rs`)

| dosya | içerik |
|---|---|
| `src/lib.rs` | yönlendirme: `front`, `self` Rust; gerisi Python'a |
| `src/delegate.rs` | Python CLI'ı bulma (`COPS_PY`, ikilinin ataları, `<durum dizini>/bin/cops-py`), özyineleme koruması, `exec`, çıkış 125 |
| `src/argp.rs`, `src/pyenv.rs` | argparse biçimleri (taklit edilmeyen devredilir), Python yol kuralları |
| `src/front/` | `front status|on|off [--apply]`, TBD#371/4 (a) adres ayrıştırma, (b) yabancı porta vekillik, (c) geri alma; gizli üretimi |
| `src/selfcmd.rs` | `self` |
| `src/list.rs` | `list` yalnız arayüz; komut Python'a devredilir |

## İşlevce eşlik tablosu

Taban `22348088`. Python yolları depo köküne, Rust yolları `rust/crates/cops-cli/` altına görelidir (başka crate adıyla
yazılır). Satır numaraları Python'da `ast`, bash'te `grep` ile alındı. Durum: `karşılandı` = Rust karşılığı var ve adı verilen
test sınıyor (bilinçli fark hücrede); `kapsam dışı` = neden ve iz; `EKSİK` = karşılık ya da onu sınayan test yok. Eşlik
koddan okunarak yazıldı; testler bu tablo için yeniden koşulmadı (koşu kaydı "Doğrulama").

### `py/claudeops/front.py`

| Python adı (satır) | Rust karşılığı | Rust testi | durum |
|---|---|---|---|
| `LOOPBACK` (18) | `cops-cli` kullanmıyor; `cops-proxy` `src/front.rs` `LOOPBACK` (docs/rs-gate-eslik.md 1.1) | `cops-proxy`: `trusted_front_needs_secret_loopback_and_exact_header` | kapsam dışı: CLI kullanmaz, rs/gate'te |
| `secret_path` (21) | `src/front/secret.rs` `secret_path` | `paths_follow_python_pathlib`, `applied_unit_passes_the_secret_state_dir` | karşılandı |
| `read_secret` (25) | `src/front/secret.rs` `read_secret` (dosya kuralı `cops-proxy` `read_secret_file`) | `env_is_ignored_for_the_file_but_wins_for_reading`, `creates_0600_stable_and_replaces_leaked_or_corrupt`, `parity_front_status_variants` | karşılandı |
| `ensure_secret` (40) | `src/front/secret.rs` `ensure_secret_file` (fark: ortam gizlisi dosya üretimini engellemez, P1; kilit süreli; `fsync`) | `creates_0600_stable_and_replaces_leaked_or_corrupt`, `concurrent_threads_agree_on_disk_value`, `lock_wait_is_bounded`, `secret_lock_contract_with_python` | karşılandı |
| `trusted_front` (66) | `cops-cli` kullanmıyor; `cops-proxy` `FrontSecret::trusted` (rs-gate 1.1) | `cops-proxy`: `trusted_front_needs_secret_loopback_and_exact_header` | kapsam dışı: CLI kullanmaz, rs/gate'te |
| `internal_authz` (77) | yok (rs-gate 1.1: karar Python'da) | yok | kapsam dışı: iç uç Python'da, T9 |
| `internal_authz._H` (91) | yok | yok | kapsam dışı: `internal_authz` iç yardımcısı, T9 |
| `internal_authz._H.get` (92) | yok | yok | kapsam dışı: `internal_authz` iç yardımcısı, T9 |
| `ws_ticket_consume` (127) | yok (rs-gate 1.1: bilet deposu Python'da) | yok | kapsam dışı: T2 |

### `py/claudeops/commands/front_cmd.py`

| Python adı (satır) | Rust karşılığı | Rust testi | durum |
|---|---|---|---|
| `UNIT_DIR` (26) | `src/front/mod.rs` `Paths.unit_dir` | `paths_follow_python_pathlib` | karşılandı |
| `FRONT_UNIT` (27) | `Paths.front_unit` | `parity_front_status_variants`, `parity_front_on_plans` | karşılandı |
| `WEB_UNIT` (28) | `Paths.web_unit` | `parity_front_on_plans` | karşılandı |
| `DROPIN` (29) | `Paths.dropin` | `parity_front_status_variants`, `parity_front_on_plans` | karşılandı |
| `DEFAULT_BIN` (30) | `Paths.default_bin` | `paths_follow_python_pathlib`, `parity_front_status_variants` (`--bin`siz koşu) | karşılandı |
| `DEFAULT_LISTEN` (31) | `src/front/mod.rs` `DEFAULT_LISTEN` | `default_addresses_match_python_front_cmd` | karşılandı |
| `DEFAULT_INTERNAL` (32) | `src/front/mod.rs` `DEFAULT_INTERNAL` | `default_addresses_match_python_front_cmd` | karşılandı |
| `FRONT_UNIT_TEMPLATE` (34) | `src/front/mod.rs` `FRONT_UNIT_TEMPLATE` | `unit_template_has_no_secret_and_passes_state_dir_quoted` | karşılandı |
| `register` (49) | `src/argp.rs` `parse_front`, `FrontArgs`, `OPTS`; `src/lib.rs` `route` (yardım ve hata Python'a devredilir) | `rust_parse_agrees_with_python_argparse`, `accepted_forms`, `errors_and_help_are_delegated`, `routing`, `parity_delegated_commands_and_argparse_errors` | karşılandı |
| `_unit_text` (59) | `src/front/mod.rs` `unit_text`, `sd_quote` (fark: `bin`/`dist` gerekirse tırnaklı) | `unit_template_has_no_secret_and_passes_state_dir_quoted`, `bin_and_dist_with_spaces_are_quoted` | karşılandı |
| `web_execstart` (66) | `src/front/mod.rs` `web_execstart` | `execstart_patch` | karşılandı |
| `regex ^ExecStart=(.*)$` (67) | `web_execstart` (regex yerine satır bölme + `strip_prefix`, `py_strip`) | `execstart_patch` (ilk satır, `\r`, satır başı) | karşılandı |
| `with_internal_port` (71) | `src/front/mod.rs` `with_internal_port` | `execstart_patch` | karşılandı |
| `dropin_text` (82) | `src/front/mod.rs` `dropin_text` | `dropin_resets_execstart`, `applied_unit_passes_the_secret_state_dir` | karşılandı |
| `port_busy` (86) | `src/front/net.rs` `Net::busy` / `RealNet` (adres ayrıştırma `parse_listen`, `parse_internal`; fark: geçersiz adres engel) | `parity_front_status_variants`, `parity_front_on_plans`, `listen_and_internal_parsing`, `fix_a_status_reports_bad_address_without_crashing` | karşılandı |
| `plan_on` (93) | `src/front/mod.rs` `plan_on`, `Plan` (ekler: yabancı port, adres, `bin` engelleri) | `plan_blockers`, `internal_busy_without_dropin_keeps_python_blocker`, `parity_front_on_plans`, `fix_a_bad_internal_addresses_are_blockers_not_crashes`, `fix_b_foreign_process_on_internal_port_blocks_even_with_dropin`, `relative_bin_is_a_blocker`, `control_characters_in_paths_block` | karşılandı |
| `_sc` (113) | `src/front/systemctl.rs` `Systemctl`, `RealSystemctl` | `on_apply_with_failing_systemctl_rolls_back_files` (gerçek çalıştırıcı, `PATH`te sahte `systemctl`) | karşılandı |
| `run` (117) | `src/front/mod.rs` `run`, `status`, `on`, `off`; `src/main.rs` `run_front` (fark: geri alma, doğrulama) | status: `parity_front_status_variants`; on: `plan_only_changes_nothing`, `applied_unit_passes_the_secret_state_dir`, `fix_b_our_web_on_internal_port_is_a_reapply`, `fix_c_on_rolls_back_at_every_systemctl_step`; off: `off_success_sequence_matches_python_and_verifies_web`, `off_without_front_unit_ignores_disable_error_like_python`, `fix_c_off_web_restart_failure_returns_to_front` | karşılandı |

İçe aktarılan sabitler (bu modüllerin adı değil, sayıma girmez): `DIST_DIR` -> `dist_dir` (`dist_dir_resolves_from_python_repo`,
`parity_front_on_plans`); `HOME`, `CLAUDEOPS_DIR` -> `src/pyenv.rs` `Roots` (`roots_follow_paths_py`).

### `self` (bash `claudeops`; Python'da yok)

| bash adı (satır) | Rust karşılığı | Rust testi | durum |
|---|---|---|---|
| `SESS_DIR` (17) | `src/main.rs` `run_self`: `Roots::claude_dir()/sessions` -> `SelfCfg.sessions_dir` | `parity_self_with_bash_claudeops` (`/tmp/claudeops` yoksa atlanır) | karşılandı |
| `find_self_claude_pid` (55), oturum kimliği dalı | `src/selfcmd.rs` `find_self_pid` (fark: canlı olmayan ya da başka uid'in pid'i atlanır) | `session_id_match_prints_bash_layout`, `stale_dead_pid_record_is_skipped_for_live_one`, `parity_self_with_bash_claudeops` | karşılandı |
| `find_self_claude_pid` (55), ata zinciri dalı | `find_self_pid` (`comm`, `ppid`; `ps` yerine `/proc`, 64 adım) | `ancestor_walk_finds_claude_and_is_bounded`, `parity_self_with_bash_claudeops` | karşılandı |
| `cmd_self` (1875) | `src/selfcmd.rs` `run` (`py_str`, `truthy`; Python dökümü yerine tek satır hata) | `session_id_match_prints_bash_layout`, `ancestor_walk_finds_claude_and_is_bounded`, `missing_field_and_bad_bridge_fail_after_partial_output`, `python_str_and_repr`, `parity_self_with_bash_claudeops` | karşılandı |
| dağıtıcı `self) cmd_self` (2273) | `src/lib.rs` `route` -> `Route::SelfCmd` | `routing` | karşılandı |
| betik girişi (`set -u`, `mkdir -p /tmp/claudeops`, `PATH` eki) | yok | yok | kapsam dışı: `cmd_self`in parçası değil, silinecek bash aracının genel hazırlığı (TBD#12) |

Koddan okunan, "Bilinçli sapmalar"da yazmayan ve testi olmayan farklar (koşulmadı): bash `*.json` globu noktalı dosyaları
almaz, `json_files` alır; sıralama bash'te yerel ayara, Rust'ta bayt sırasına göre; `pid`i metin olan kaydı bash kabul eder,
Rust atlar; UTF-8 olmayan `CLAUDEOPS_FRONT_SECRET`i Python dolu sayar, `cops-rs` yok sayıp dosyaya bakar.

### `list` (yalnız arayüz)

| Python adı (satır) | Rust karşılığı | Rust testi | durum |
|---|---|---|---|
| `py/claudeops/commands/ls.py` `register` (11), `run` (19) | `src/list.rs` yalnız tipler; komut Python'a devredilir | `list_is_delegated_until_procscan_lands`, `routing` | kapsam dışı: cops-procscan birleşince (`rs/proc`) |

### Python testleri: `py/tests/test_front_cmd.py`

| Python adı (satır) | Rust karşılığı / neden | Rust testi | durum |
|---|---|---|---|
| `LIVE` (8) | `src/front/tests.rs` `LIVE` | `execstart_patch` | karşılandı |
| `NEW` (9) | `src/front/tests.rs` `NEW` | `execstart_patch` | karşılandı |
| `T` (12) | `src/front/tests.rs` (modül) | alttaki satırlar | karşılandı |
| `T.test_execstart_patch` (13) | aynı vektörler | `execstart_patch` | karşılandı |
| `T.test_dropin_resets_execstart` (19) | aynı | `dropin_resets_execstart` | karşılandı |
| `T.test_plan_blockers` (23) | aynı iki engel, adım sayısı çıktıdan | `plan_blockers` | karşılandı |
| `T.test_unit_template_has_no_secret` (30) | `unit_text` üzerinden | `unit_template_has_no_secret_and_passes_state_dir_quoted` | karşılandı |
| `T.test_applied_unit_passes_the_secret_state_dir` (35) | uygulama + gizli yeri bir testte, tırnaklı `--state-dir` satırı ötekinde | `applied_unit_passes_the_secret_state_dir`, `unit_template_has_no_secret_and_passes_state_dir_quoted` | karşılandı |

### Python testleri: `py/tests/test_front_internal.py`

| Python adı (satır) | Rust karşılığı / neden | Rust testi | durum |
|---|---|---|---|
| `Secret` (8) | `src/front/secret.rs` testleri | alttaki satırlar | karşılandı |
| `Secret.setUp` (9) | her testte geçici dizin, ortam değeri parametre | `creates_0600_stable_and_replaces_leaked_or_corrupt` | karşılandı |
| `Secret.test_secret_follows_state_dir` (16) | `secret_path` | `paths_follow_python_pathlib`, `applied_unit_passes_the_secret_state_dir` | karşılandı |
| `Secret.test_ensure_creates_0600_and_is_stable` (21) | `ensure_secret_file` | `creates_0600_stable_and_replaces_leaked_or_corrupt` | karşılandı |
| `Secret.test_loose_permissions_are_not_trusted` (28) | `read_secret` | `parity_front_status_variants` (0644 = `gizli: YOK`) | karşılandı |
| `Secret.test_leaked_secret_is_replaced_not_reused` (33) | `ensure_secret_file` | `creates_0600_stable_and_replaces_leaked_or_corrupt`, `secret_lock_contract_with_python` | karşılandı |
| `Secret.test_empty_or_corrupt_file_is_replaced` (41) | aynı üç bozuk içerik | `creates_0600_stable_and_replaces_leaked_or_corrupt` | karşılandı |
| `Secret.test_concurrent_ensure_returns_the_value_on_disk` (50) | 8 iş parçacığı; artık dosya denetimi sıralı testte | `concurrent_threads_agree_on_disk_value`, `creates_0600_stable_and_replaces_leaked_or_corrupt` | karşılandı |
| `Secret.test_concurrent_ensure_returns_the_value_on_disk.go` (56) | iş parçacığı gövdesi | `concurrent_threads_agree_on_disk_value` | karşılandı |
| `Secret.test_non_utf8_file_means_no_secret` (69) | okuma kuralı `cops-proxy`de; `trusted_front` yarısı CLI'da yok | `cops-proxy`: `file_secret_follows_changes_and_fails_closed`; `creates_0600_stable_and_replaces_leaked_or_corrupt` | karşılandı |
| `Secret.test_env_wins_and_missing_is_empty` (76) | `read_secret` | `env_is_ignored_for_the_file_but_wins_for_reading` | karşılandı |
| `Secret.test_trusted_front` (81) | CLI'da yok (rs-gate bölüm 2) | `cops-proxy`: `trusted_front_needs_secret_loopback_and_exact_header` | kapsam dışı: CLI kullanmaz, rs/gate'te |
| `Authz` (88) | iç uç | yok | kapsam dışı: T9 |
| `Authz.tearDown` (89) | Python kanca sıfırlaması | yok | kapsam dışı: T9 |
| `Authz.test_legacy_token_via_query_and_bearer` (92) | iç uç (rs-gate: yalnız token kuralı `cops-auth`ta) | `cops-auth`: `query_and_bearer_accept_empty_token_is_closed_non_ascii_rejected` | kapsam dışı: T9 |
| `Authz.test_empty_token_fails_closed` (100) | iç uç (aynı) | `cops-auth`: `query_and_bearer_accept_empty_token_is_closed_non_ascii_rejected` | kapsam dışı: T9 |
| `Authz.test_authenticator_and_authorizer_are_used` (104) | iç uç | `cops-proxy`: `authorization_failures_are_403_and_audited` (yalnız `Gate`) | kapsam dışı: T9 |
| `Authz.test_authenticator_and_authorizer_are_used.auth` (106) | test kancası | yok | kapsam dışı: T9 |
| `Authz.test_resource_steward_reaches_authorizer` (120) | iç uç | yok | kapsam dışı: T9 |
| `Authz.test_ws_ticket_fallback_for_ws_paths` (135) | iç uç | yok | kapsam dışı: T9 |
| `Ticket` (142) | bilet deposu | yok | kapsam dışı: T2 |
| `Ticket.test_consume_once_bound_and_unbound` (143) | bilet deposu | yok | kapsam dışı: T2 |
| `Ticket.test_expired` (153) | bilet deposu | yok | kapsam dışı: T2 |
| `Wiring` (159) | `web.py` kaynak sırası | yok | kapsam dışı: T9 |
| `Wiring.test_internal_branch_guarded_before_auth` (160) | dış engel `cops-proxy`de | `cops-proxy`: `internal_paths_are_never_forwarded` | kapsam dışı: T9 |
| `CspParity` (171) | `cops-proxy` `CSP` sabiti (rs-gate bölüm 2) | yok | kapsam dışı: rs/gate'in parite testi, iz yok |
| `CspParity.test_rust_csp_equals_python_csp` (172) | Python testi Rust sabitini okur | yok | kapsam dışı: rs/gate, iz yok |
| `regex pub const CSP: &str = "([^"]+)"` (176) | `CspParity` içi | yok | kapsam dışı: rs/gate, iz yok |
| `regex "([^"]*)"` (179) | `CspParity` içi | yok | kapsam dışı: rs/gate, iz yok |

### Python testleri: `py/tests/test_front_xff.py`

`trusted_forwarded_ip` (`web.py`) CLI'da kullanılmaz; karşılığı `cops-proxy` `trusted_client_ip` (rs-gate bölüm 2).

| Python adı (satır) | Rust karşılığı / neden | Rust testi | durum |
|---|---|---|---|
| `H` (5) | başlık sahtesi | `cops-proxy`: `trusted_client_ip_matches_python_test_front_xff` | kapsam dışı: CLI kullanmaz, rs/gate'te |
| `H.get` (6) | başlık sahtesi | `cops-proxy`: `trusted_client_ip_matches_python_test_front_xff` | kapsam dışı: CLI kullanmaz, rs/gate'te |
| `XFF` (10) | vektör sınıfı | `cops-proxy`: `trusted_client_ip_matches_python_test_front_xff` | kapsam dışı: CLI kullanmaz, rs/gate'te |
| `XFF.test_no_secret_ignores_header` (11) | aynı vektör | `cops-proxy`: `trusted_client_ip_matches_python_test_front_xff` | kapsam dışı: CLI kullanmaz, rs/gate'te |
| `XFF.test_wrong_or_missing_secret` (14) | aynı vektör | `cops-proxy`: `trusted_client_ip_matches_python_test_front_xff` | kapsam dışı: CLI kullanmaz, rs/gate'te |
| `XFF.test_non_loopback_peer_never_trusted` (18) | aynı vektör | `cops-proxy`: `trusted_client_ip_matches_python_test_front_xff` | kapsam dışı: CLI kullanmaz, rs/gate'te |
| `XFF.test_tunnel_client_ip_only_from_loopback` (21) | aynı vektör | `cops-proxy`: `trusted_client_ip_matches_python_test_front_xff` | kapsam dışı: CLI kullanmaz, rs/gate'te |
| `XFF.test_route_request_uses_trusted_ip` (30) | eklenti `RouteRequest` | yok | kapsam dışı: eklenti yolları Python'da, T9 |
| `XFF.test_route_request_uses_trusted_ip.Fake` (33) | test sahtesi | yok | kapsam dışı: T9 |
| `XFF.test_route_request_uses_trusted_ip.Fake.path` (34) | test sahtesi | yok | kapsam dışı: T9 |
| `XFF.test_route_request_uses_trusted_ip.Fake.client_address` (34) | test sahtesi | yok | kapsam dışı: T9 |
| `XFF.test_route_request_uses_trusted_ip.Fake._client_ip` (36) | test sahtesi | yok | kapsam dışı: T9 |
| `XFF.test_valid_secret_uses_last_xff` (40) | aynı vektör | `cops-proxy`: `trusted_client_ip_matches_python_test_front_xff` | kapsam dışı: CLI kullanmaz, rs/gate'te |

### Sayım ve denetim

| satır kümesi | toplam | karşılandı | kapsam dışı | EKSİK |
|---|---|---|---|---|
| `ast` öğeleri (`front.py` 9, `front_cmd.py` 18, `test_front_cmd.py` 8, `test_front_internal.py` 29, `test_front_xff.py` 13) | 77 | 40 | 37 | 0 |
| `self` (bash) | 6 | 5 | 1 | 0 |
| `list` (tek satır) | 1 | 0 | 1 | 0 |
| **toplam** | **84** | **45** | **39** | **0** |

`ast` öğesi = işlev, sınıf, metot, iç içe tanım, modül/sınıf düzeyi atama ve sabit metinli `re.*` çağrısı. Denetim betiği
(oturum scratchpad'inde, repoya girmedi): 77 öğenin her biri ad ve satır numarasıyla kendi dosyasının tablosunda bulundu
(eksik 0, fazla 0); `ls.py` adları ve bash adları tabloda; "Rust testi" sütunundaki her ad `rust/crates` altında `#[test]` /
`#[tokio::test]` olarak bulundu.

## Gözden geçirme düzeltmeleri

| commit | hata | test |
|---|---|---|
| `37b7cd5f` | cgroup v1/hibritte her süreç `user@<uid>.service` sayılıyordu | `fake_proc_tree_unit_detection` |
| `6a66373b` | geri alma önceki birim durumunu port sahibinden okuyordu (`on` eski ön kapıyı kapatabiliyor, `off` durmuş olanı açıyordu) | `fix_c_on_listen_change_failure_restarts_old_front_instead_of_stopping_it`, `fix_c_on_rollback_keeps_previous_enablement`, `fix_c_off_disable_failure_keeps_stopped_front_stopped`, `unknown_front_state_changes_nothing` |
| `6a66373b` | `off` web'i ön kapının `--listen` adresinde bekliyordu | `off_verifies_web_on_its_own_port_when_front_listen_differs`, `web_addr_follows_web_unit_flags` |
| `6a66373b` | `on` web'in iç porta geçtiğini doğrulamıyordu | `fix_c_on_web_not_on_internal_is_rolled_back` |
| `6a66373b` | çalışan ön kapı yeni birimle yeniden başlamıyordu | `on_restarts_an_already_running_front_so_the_new_unit_applies` |
| `6a66373b` | göreli `--bin` birime göreli yazılıyordu; stdout flush hatası yutuluyordu | `relative_bin_is_a_blocker` |
| `81e5bc7f` | `COPS_RS_DEPTH` uzun ömürlü süreçlere sızıp birikiyordu (`<n>:<pid>`) | `depth_counts_only_in_own_lineage`, `leaked_depth_from_other_lineage_is_ignored` |
| `22348088` | gizli kilidi için iki dilli test yoktu; argparse kâhini belgesi | `secret_lock_contract_with_python` |

TBD#371/4: (a) `listen_and_internal_parsing`, `fix_a_*`, `bad_internal_is_blocked_before_any_side_effect`; (b) `fix_b_*`;
(c) `fix_c_*`, `on_apply_with_failing_systemctl_rolls_back_files`.

## Bilinen açıklar

- `bin/cops-py` ve `cops-rs`yi hiçbir kurulum yazmıyor: `COPS_PY` ya da elle `ln -s <depo>/py/cops <durum>/bin/cops-py` yoksa
  devir 125 ile düşer. Kurulum betiği (`scripts/`) bu izin yolları dışında; CANLIYA ALMADAN ÖNCE gerekli.
- `web_addr` argparse kısaltmalarını (`--po`) ve ExecStart'ı ezen başka drop-in'leri görmez (ön kapı listen'ine düşer).
- `list` yalnız arayüz (`cops-procscan` birleşince bağlanacak).
- `cops-rs --version` Python'a devrediliyor, GIT_SHA yok (ders H11).

## Bilinçli sapmalar

- Geçersiz adres engel olur (ad ör. `localhost:` reddedilir, `--internal` yalnız IPv4); `status` "geçersiz adres" + rc 1.
- Ek engeller: `listen`/`internal` çakışması, ikili çalıştırılamaz, yolda denetim karakteri, web birimi okunamaz/UTF-8 değil,
  göreli `--bin`, drop-in varken iç port başkasında.
- Geri alma, doğrulama beklemeleri, `is-active/is-enabled` sorguları, çalışan ön kapıya `restart`.
- Birim dosyaları atomik; boşluklu/özel karakterli `bin` ve `dist` tırnaklı.
- Gizli: ortam değişkeni dosya üretimini engellemez; kilit 30 sn ile sınırlı; 64 KiB üstü kullanılamaz.
- Göreli `HOME`/`CLAUDEOPS_DIR` açık hata; göreli `--bin` `status`ta çağıranın dizinine göre.
- `self` Rust'ta (karşılığı bash `cmd_self`, Python'da yok); kendi uid'imizde canlı olmayan pid kaydı atlanır.
- `front on` planı Python deposunu bulamazsa 125.

## Python hatası? (Python değiştirilmedi; sahip sorusu TBD#393)

1. `front_cmd.py:71-90`: `--internal 28765` bozuk birim yazar; sayı olmayan port döküm verir; `[::1]` hata.
2. `front_cmd.py:102,136`: drop-in varken yabancı süreç iç portta ise ön kapı ona vekil olur.
3. `front_cmd.py:143-163`: geri alma yok; `off` `disable --now` sonucunu yok sayıyor.
4. `front_cmd.py:141-142`: çalışan ön kapıda yalnız `enable --now`; değişen birim uygulanmaz.
5. `front_cmd.py:96,138`: göreli `--bin` birime göreli yazılır, systemd reddeder.
6. `front_cmd.py:63`: `bin`/`dist` tırnaksız; boşluklu yol ExecStart'ı böler.
7. `front.py:44`: `CLAUDEOPS_FRONT_SECRET` doluyken `ensure_secret` dosya üretmez; servisler gizlisiz kalır.
8. `paths.py:45` + `py/cops:5`: göreli `CLAUDEOPS_DIR` `py/` altına çözülür.
9. bash `claudeops:57-66` (silinecek araç): `self` ölü pid'li bayat kaydı seçebilir; düzeltme önerilmiyor.

## Ders listesi (bölüm 3) karşılığı

| madde | karşılık |
|---|---|
| 1 (H7) | cgroup ile tam birim adı: `fake_proc_tree_unit_detection`, `real_listener_is_found_with_our_pid`; `state_dir_link_and_self_loop_is_refused` |
| 2 (H2) | `write_snapshot_restore_roundtrip`, `failed_write_leaves_no_temp_and_keeps_target`, `concurrent_threads_agree_on_disk_value`, `secret_lock_contract_with_python` |
| 3 (H9/H10/H13) | `unknown_front_state_changes_nothing`; okunamayan dinleyici "bizim değil" (`fix_b_*`) |
| 4 (H9) | `fix_c_front_not_listening_is_rolled_back`, `fix_c_on_web_not_on_internal_is_rolled_back`, `fix_c_off_web_not_back_outside_is_rolled_back` |
| 5 | kalan `let _` yalnız geçici dosya temizliği; `unwrap/expect/panic` crate düzeyinde `deny` |
| 6 (H3) | önbellek yok, her çağrıda okunur |
| 7 (H8) | `lock_wait_is_bounded`; `wait_for` süreli, ata zinciri 64 adım |
| 8 (H4) | sahte systemctl ile sabit çıkış kodları |
| 9 (H1) | `exec`/`status()` bekler; uzun ömürlü süreç yok |
| 10 (H5) | adres ayrıştırma testleri, `depth_guard_and_argv_are_exact` |
| 11, 12 (H6/H14) | `rust_parse_agrees_with_python_argparse`, `parity_*`, `paths_follow_python_pathlib` |
| 13 (H12) | gizli yazdırılmaz; `unit_template_has_no_secret_and_passes_state_dir_quoted` |
| 14 (H17) | `control_characters_in_paths_block`, `relative_bin_is_a_blocker` |
| 15, 16, 18 | vekil/WS, route tablosu, uzak host yok: uygulanamaz |
| 17 (H16) | e2e `Sandbox` (`env_clear`, geçici HOME/CLAUDEOPS_DIR, sahte systemctl) |
| 19 (H11) | AÇIK: GIT_SHA yok |
| 20 (H21) | `plan_only_changes_nothing`, `parity_front_on_plans` |

`rust/Cargo.lock` commit'siz (izin verilen yollar dışında; `cargo build` yeniden üretir).
