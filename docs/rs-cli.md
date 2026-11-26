# rs/cli (İz T6: Rust `cops` CLI)

**Durum (26 Kas 2026 gece): BİRLEŞTİRMEYE HAZIR** (kod + eşlik tablosu + ders listesi). **py/ değişti** ("Python hatası?"
1-8 Python'da düzeltildi): birleşince web restart + uzak deploy (yuhem, ulak_31) gerekir. Canlıda `cops-rs` kullanılmadan ÖNCE `bin/cops-py` kurulumu gerekir (bkz. Bilinen açıklar); `list` `cops-procscan` birleşince bağlanır.

## Doğrulama (26 Kas gece, "Python hatası?" 1-8 sonrası)

`cargo test -p cops-cli`: birim 68, `argparse_parity` 1, `e2e_bin` 7, `py_parity` 13 = 89 geçti 0 kaldı (birim testlerin son
3'ü eklendikten sonra yalnız `--lib` yeniden koşuldu); `cargo clippy -p cops-cli --all-targets -- -D warnings` ve
`cargo fmt -p cops-cli --check` temiz. Python tam paket (`cd py && python3 -m unittest discover -s tests`) 5716 test OK
(23 atlandı); son test eki (`test_off_falls_back_to_front_listen_when_web_unit_is_missing`) sonrası `test_front*.py` 69 OK.
Testler yalıtık HOME/CLAUDEOPS_DIR ve sahte systemctl ile; canlı birimlere ve `front.secret`e dokunulmadı. Önceki koşu
(`22348088`): `cargo test -p cops-cli` 80, workspace 225.

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

Taban `22348088`; Python satırları "Python hatası?" 1-8 düzeltmelerinden sonraki koddan (`f2d1fc02` + belge commit'inin
test eki). Python yolları depo köküne, Rust yolları `rust/crates/cops-cli/` altına görelidir (başka crate adıyla
yazılır). Satır numaraları Python'da `ast`, bash'te `grep` ile alındı. Durum: `karşılandı` = Rust karşılığı var ve adı verilen
test sınıyor (bilinçli fark hücrede); `kapsam dışı` = neden ve iz; `EKSİK` = karşılık ya da onu sınayan test yok. Eşlik
koddan okunarak yazıldı; testler bu tablo için yeniden koşulmadı (koşu kaydı "Doğrulama").

### `py/claudeops/front.py`

| Python adı (satır) | Rust karşılığı | Rust testi | durum |
|---|---|---|---|
| `LOOPBACK` (18) | `cops-cli` kullanmıyor; `cops-proxy` `src/front.rs` `LOOPBACK` (docs/rs-gate-eslik.md 1.1) | `cops-proxy`: `trusted_front_needs_secret_loopback_and_exact_header` | kapsam dışı: CLI kullanmaz, rs/gate'te |
| `secret_path` (21) | `src/front/secret.rs` `secret_path` | `paths_follow_python_pathlib`, `applied_unit_passes_the_secret_state_dir` | karşılandı |
| `read_secret` (25) | `src/front/secret.rs` `read_secret` (dosya kuralı `cops-proxy` `read_secret_file`) | `env_is_ignored_for_the_file_but_wins_for_reading`, `creates_0600_stable_and_replaces_leaked_or_corrupt`, `parity_front_status_variants` | karşılandı |
| `_file_secret` (33) | `src/front/secret.rs` `file_value` (`cops-proxy` `read_secret_file`) | `env_is_ignored_for_the_file_but_wins_for_reading`, `secret_lock_contract_with_python` | karşılandı |
| `ensure_secret` (45) | `src/front/secret.rs` `ensure_secret_file` (ortam yok sayılır, iki tarafta aynı; fark: kilit süreli, `fsync`) | `creates_0600_stable_and_replaces_leaked_or_corrupt`, `concurrent_threads_agree_on_disk_value`, `lock_wait_is_bounded`, `secret_lock_contract_with_python` | karşılandı |
| `trusted_front` (72) | `cops-cli` kullanmıyor; `cops-proxy` `FrontSecret::trusted` (rs-gate 1.1) | `cops-proxy`: `trusted_front_needs_secret_loopback_and_exact_header` | kapsam dışı: CLI kullanmaz, rs/gate'te |
| `internal_authz` (83) | yok (rs-gate 1.1: karar Python'da) | yok | kapsam dışı: iç uç Python'da, T9 |
| `internal_authz._H` (97) | yok | yok | kapsam dışı: `internal_authz` iç yardımcısı, T9 |
| `internal_authz._H.get` (98) | yok | yok | kapsam dışı: `internal_authz` iç yardımcısı, T9 |
| `ws_ticket_consume` (133) | yok (rs-gate 1.1: bilet deposu Python'da) | yok | kapsam dışı: T2 |

### `py/claudeops/commands/front_cmd.py`

| Python adı (satır) | Rust karşılığı | Rust testi | durum |
|---|---|---|---|
| `UNIT_DIR` (30) | `src/front/mod.rs` `Paths.unit_dir` | `paths_follow_python_pathlib` | karşılandı |
| `FRONT_UNIT` (31) | `Paths.front_unit` | `parity_front_status_variants`, `parity_front_on_plans` | karşılandı |
| `WEB_UNIT` (32) | `Paths.web_unit` | `parity_front_on_plans` | karşılandı |
| `DROPIN` (33) | `Paths.dropin` | `parity_front_status_variants`, `parity_front_on_plans` | karşılandı |
| `DEFAULT_BIN` (34) | `Paths.default_bin` | `paths_follow_python_pathlib`, `parity_front_status_variants` (`--bin`siz koşu) | karşılandı |
| `DEFAULT_LISTEN` (35) | `src/front/mod.rs` `DEFAULT_LISTEN` | `default_addresses_match_python_front_cmd` | karşılandı |
| `DEFAULT_INTERNAL` (36) | `src/front/mod.rs` `DEFAULT_INTERNAL` | `default_addresses_match_python_front_cmd` | karşılandı |
| `FRONT_UNIT_TEMPLATE` (38) | `src/front/mod.rs` `FRONT_UNIT_TEMPLATE` | `unit_template_has_no_secret_and_passes_state_dir_quoted` | karşılandı |
| `register` (53) | `src/argp.rs` `parse_front`, `FrontArgs`, `OPTS`; `src/lib.rs` `route` (yardım ve hata Python'a devredilir) | `rust_parse_agrees_with_python_argparse`, `accepted_forms`, `errors_and_help_are_delegated`, `routing`, `parity_delegated_commands_and_argparse_errors` | karşılandı |
| `_sd_quote` (63) | `src/front/mod.rs` `sd_quote` | `unit_template_has_no_secret_and_passes_state_dir_quoted`, `bin_and_dist_with_spaces_are_quoted` | karşılandı |
| `_sd_quote_if_needed` (68) | `src/front/mod.rs` `sd_quote_if_needed` | `bin_and_dist_with_spaces_are_quoted` | karşılandı |
| `_unit_text` (73) | `src/front/mod.rs` `unit_text` | `unit_template_has_no_secret_and_passes_state_dir_quoted`, `bin_and_dist_with_spaces_are_quoted` | karşılandı |
| `web_execstart` (80) | `src/front/mod.rs` `web_execstart` | `execstart_patch` | karşılandı |
| `regex ^ExecStart=(.*)$` (81) | `web_execstart` (regex yerine satır bölme + `strip_prefix`, `py_strip`) | `execstart_patch` (ilk satır, `\r`, satır başı) | karşılandı |
| `with_internal_port` (85) | `src/front/mod.rs` `with_internal_port` | `execstart_patch` | karşılandı |
| `dropin_text` (96) | `src/front/mod.rs` `dropin_text` | `dropin_resets_execstart`, `applied_unit_passes_the_secret_state_dir` | karşılandı |
| `_rdbg` (100) | std `Debug` (`{:?}`) biçimi (hata metinlerinde) | `parity_bad_addresses_are_blockers_on_both_sides`, `parity_control_characters_in_bin_block` | karşılandı |
| `_parse_port` (115) | `src/front/net.rs` `parse_port` | `listen_and_internal_parsing` | karşılandı |
| `_parse_listen` (124) | `src/front/net.rs` `parse_listen` | `listen_and_internal_parsing`, `parity_bad_addresses_are_blockers_on_both_sides` | karşılandı |
| `_parse_internal` (150) | `src/front/net.rs` `parse_internal` | `listen_and_internal_parsing`, `fix_a_bad_internal_addresses_are_blockers_not_crashes`, `parity_bad_addresses_are_blockers_on_both_sides` | karşılandı |
| `_fmt` (158) | std `SocketAddr` `Display` | `fix_c_off_web_not_back_outside_is_rolled_back`, `fix_c_off_port_not_released_stops_before_touching_web` | karşılandı |
| `port_busy` (164) | `src/front/net.rs` `Net::busy` / `RealNet` | `parity_front_status_variants`, `parity_front_on_plans`, `fix_a_status_reports_bad_address_without_crashing` | karşılandı |
| `FRONT_UNIT_NAME` (171) | `src/front/net.rs` `FRONT_UNIT_NAME` | `fake_proc_tree_unit_detection` | karşılandı |
| `WEB_UNIT_NAME` (172) | `src/front/net.rs` `WEB_UNIT_NAME` | `fake_proc_tree_unit_detection` | karşılandı |
| `_PROC` (173) | `RealNet.proc_root` (`src/main.rs` `/proc`) | `fake_proc_tree_unit_detection` | karşılandı |
| `_hex_addr` (176) | `src/front/net.rs` `parse_hex_addr` | `proc_net_hex_addresses` | karşılandı |
| `_canon` (194) | std `IpAddr::to_canonical` (`accepts` içinde) | `proc_net_hex_addresses` | karşılandı |
| `_accepts` (198) | `src/front/net.rs` `accepts` | `proc_net_hex_addresses` | karşılandı |
| `_unit_of` (204) | `src/front/net.rs` `unit_of` | `fake_proc_tree_unit_detection` | karşılandı |
| `_unit_of._path_of` (216) | `unit_of` içindeki `path_of` kapanışı | `fake_proc_tree_unit_detection` | karşılandı |
| `_port_owner` (233) | `src/front/net.rs` `port_owner`, `PortOwner`, `Net::owner` | `real_listener_is_found_with_our_pid`, `fake_proc_tree_unit_detection`, `parity_foreign_internal_port_blocks_on_both_sides` | karşılandı |
| `_is_unit` (292) | `PortOwner::is_unit` | `fake_proc_tree_unit_detection` | karşılandı |
| `_describe` (297) | `PortOwner::describe` | `fix_b_foreign_process_on_internal_port_blocks_even_with_dropin`, `parity_foreign_internal_port_blocks_on_both_sides` | karşılandı |
| `plan_on` (307) | `src/front/mod.rs` `plan_on` (`Plan.steps`, `Plan.blockers`) | `plan_blockers`, `parity_front_on_plans` | karşılandı |
| `_plan_on` (313) | `src/front/mod.rs` `plan_on`, `Plan` (aynı engel sırası ve metni) | `plan_blockers`, `internal_busy_without_dropin_keeps_python_blocker`, `fix_a_bad_listen_is_a_blocker_and_ipv6_listen_is_fine`, `fix_b_foreign_process_on_internal_port_blocks_even_with_dropin`, `relative_bin_is_a_blocker`, `non_executable_bin_is_a_blocker`, `control_characters_in_paths_block`, `unreadable_web_unit_is_a_blocker`, `parity_relative_or_non_executable_bin_is_a_blocker` | karşılandı |
| `_TIMING` (364) | `src/front/mod.rs` `Timing` (`lock` yok: Python kilidi süresiz, sapma) | `fix_c_front_not_listening_is_rolled_back` (testte `fast()`) | karşılandı |
| `_ScError` (367) | `Systemctl::run` `Err` | `unknown_front_state_changes_nothing` | karşılandı |
| `_sc` (371) | `src/front/systemctl.rs` `Systemctl`, `RealSystemctl` | `on_apply_with_failing_systemctl_rolls_back_files`, `parity_apply_rollback_on_systemctl_failure` | karşılandı |
| `_show` (380) | `src/front/systemctl.rs` `show` | `fix_c_on_rolls_back_at_every_systemctl_step` | karşılandı |
| `_run_sc` (384) | `src/front/mod.rs` `run_sc` | `fix_c_on_rolls_back_at_every_systemctl_step` | karşılandı |
| `_read_web_unit` (393) | `src/front/mod.rs` `read_web_unit` | `unreadable_web_unit_is_a_blocker` | karşılandı |
| `_snapshot` (407) | `src/front/fsx.rs` `snapshot`, `Prev` | `write_snapshot_restore_roundtrip` | karşılandı |
| `_atomic_write` (418) | `src/front/fsx.rs` `atomic_write` | `write_snapshot_restore_roundtrip`, `failed_write_leaves_no_temp_and_keeps_target` | karşılandı |
| `_restore` (453) | `src/front/fsx.rs` `restore` | `write_snapshot_restore_roundtrip` | karşılandı |
| `_Undo` (463) | `src/front/mod.rs` `Undo` | `fix_c_on_rolls_back_at_every_systemctl_step` | karşılandı |
| `_Undo.__init__` (466) | `Undo::new` | `fix_c_on_rolls_back_at_every_systemctl_step` | karşılandı |
| `_Undo.file` (470) | `Undo::file` | `fix_c_write_failure_restores_files_without_systemctl` | karşılandı |
| `_Undo.sc` (479) | `Undo::sc` | `fix_c_reapply_failure_restores_previous_unit_and_restarts_old_front` | karşılandı |
| `_Undo.front_stop` (492) | `Undo::front_stop` | `fix_c_on_rollback_keeps_previous_enablement` | karşılandı |
| `_Undo.front_back` (499) | `Undo::front_back` | `fix_c_off_disable_failure_changes_nothing`, `fix_c_off_disable_failure_keeps_stopped_front_stopped` | karşılandı |
| `_Undo.report` (509) | `Undo::report` | `on_apply_with_failing_systemctl_rolls_back_files`, `parity_apply_rollback_on_systemctl_failure` | karşılandı |
| `_wait_for` (519) | `src/front/mod.rs` `wait_for` | `fix_c_front_not_listening_is_rolled_back` | karşılandı |
| `_front_state` (529) | `src/front/mod.rs` `front_state`, `UnitState` | `unknown_front_state_changes_nothing` | karşılandı |
| `_front_listen` (536) | `src/front/mod.rs` `front_listen` | `off_falls_back_to_front_listen_when_web_unit_is_missing` | karşılandı |
| `_web_addr` (553) | `src/front/mod.rs` `web_addr` | `web_addr_follows_web_unit_flags`, `off_verifies_web_on_its_own_port_when_front_listen_differs` | karşılandı |
| `run` (590) | `src/front/mod.rs` `run`, `status`; `src/main.rs` `run_front` | `parity_front_status_variants`, `fix_a_status_reports_bad_address_without_crashing`, `parity_bad_addresses_are_blockers_on_both_sides` | karşılandı |
| `_on` (611) | `src/front/mod.rs` `on` | `plan_only_changes_nothing`, `applied_unit_passes_the_secret_state_dir`, `fix_b_our_web_on_internal_port_is_a_reapply`, `fix_c_on_rolls_back_at_every_systemctl_step`, `on_restarts_an_already_running_front_so_the_new_unit_applies`, `parity_apply_rollback_on_systemctl_failure`, `parity_on_restarts_running_front_then_rolls_back_unverified` | karşılandı |
| `_on.ok` (676) | `on` içindeki `ok` kapanışı | `fix_c_front_not_listening_is_rolled_back`, `fix_c_on_web_not_on_internal_is_rolled_back` | karşılandı |
| `_off` (711) | `src/front/mod.rs` `off` | `off_success_sequence_matches_python_and_verifies_web`, `off_without_front_unit_ignores_disable_error_like_python`, `fix_c_off_web_restart_failure_returns_to_front`, `parity_apply_rollback_on_systemctl_failure` | karşılandı |
| `_off.freed` (751) | `off` içindeki `wait_for` kapanışı | `fix_c_off_port_not_released_stops_before_touching_web` | karşılandı |
| `_off.full_undo` (761) | `off` içindeki `full_undo` kapanışı | `fix_c_off_web_restart_failure_returns_to_front`, `fix_c_off_web_not_back_outside_is_rolled_back` | karşılandı |

İçe aktarılan sabitler (bu modüllerin adı değil, sayıma girmez): `DIST_DIR` -> `dist_dir` (`dist_dir_resolves_from_python_repo`,
`parity_front_on_plans`); `HOME`, `CLAUDEOPS_DIR` -> `src/pyenv.rs` `Roots` (`roots_follow_paths_py`).

### `py/claudeops/paths.py` (yalnız "Python hatası?" 8 satırı)

| Python adı (satır) | Rust karşılığı | Rust testi | durum |
|---|---|---|---|
| göreli `CLAUDEOPS_DIR` reddi (49) | `src/pyenv.rs` `Roots::check_absolute` (aynı metin; Rust `cops-rs: ` önekli) | `roots_follow_paths_py`, `parity_relative_state_dir_is_refused` | karşılandı |

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

### Python testleri: `py/tests/test_front_pyfix.py` ("Python hatası?" 1-8)

| Python adı (satır) | Rust karşılığı / neden | Rust testi | durum |
|---|---|---|---|
| `LIVE` (12) | `src/front/tests.rs` `LIVE` | `execstart_patch` | karşılandı |
| `L` (13) | `src/front/tests.rs` `L` | `fix_c_on_rolls_back_at_every_systemctl_step` | karşılandı |
| `I` (13) | `src/front/tests.rs` `I` | `fix_c_on_rolls_back_at_every_systemctl_step` | karşılandı |
| `REAL_OWNER` (14) | gerçek `net::port_owner` çağrısı | `real_listener_is_found_with_our_pid` | karşılandı |
| `World` (17) | `src/front/tests.rs` `World`, `Fake` | `fix_c_on_rolls_back_at_every_systemctl_step` | karşılandı |
| `World.__init__` (20) | `World` `Default` | `fix_c_on_rolls_back_at_every_systemctl_step` | karşılandı |
| `World.busy` (30) | `impl Net for Fake` `busy` | `internal_busy_without_dropin_keeps_python_blocker` | karşılandı |
| `World.owner` (33) | `impl Net for Fake` `owner` | `fix_b_foreign_process_on_internal_port_blocks_even_with_dropin` | karşılandı |
| `World.sc` (36) | `impl Systemctl for Fake` `run` | `unknown_front_state_changes_nothing` | karşılandı |
| `unit` (53) | `src/front/tests.rs` `unit` | `fix_b_our_web_on_internal_port_is_a_reapply` | karşılandı |
| `Env` (57) | `src/front/tests.rs` `Env`, `env` | alttaki satırlar | karşılandı |
| `Env.setUp` (58) | `env`, `fast` | `plan_only_changes_nothing` | karşılandı |
| `Env.run_front` (79) | `Env::run` | `plan_only_changes_nothing` | karşılandı |
| `Env.web_outside` (87) | `Env::web_outside` | `applied_unit_passes_the_secret_state_dir` | karşılandı |
| `Env.front_on` (94) | `Env::front_on` | `fix_b_our_web_on_internal_port_is_a_reapply` | karşılandı |
| `P1Addresses` (108) | (a) testleri | alttaki satırlar | karşılandı |
| `P1Addresses.test_bad_internal_addresses_are_blockers_not_crashes` (111) | aynı vektörler | `fix_a_bad_internal_addresses_are_blockers_not_crashes`, `bad_internal_is_blocked_before_any_side_effect` | karşılandı |
| `P1Addresses.test_bad_listen_is_a_blocker_and_ipv6_listen_is_fine` (120) | aynı | `fix_a_bad_listen_is_a_blocker_and_ipv6_listen_is_fine` | karşılandı |
| `P1Addresses.test_status_reports_bad_address_without_crashing` (130) | aynı | `fix_a_status_reports_bad_address_without_crashing` | karşılandı |
| `P1Addresses.test_parse_rules_match_rust` (136) | aynı vektörler | `listen_and_internal_parsing`, `parity_bad_addresses_are_blockers_on_both_sides` | karşılandı |
| `P2ForeignInternalPort` (152) | (b) testleri | alttaki satırlar | karşılandı |
| `P2ForeignInternalPort.test_foreign_process_on_internal_port_blocks_even_with_dropin` (155) | aynı | `fix_b_foreign_process_on_internal_port_blocks_even_with_dropin`, `parity_foreign_internal_port_blocks_on_both_sides` | karşılandı |
| `P2ForeignInternalPort.test_our_web_on_internal_port_is_a_reapply` (171) | aynı | `fix_b_our_web_on_internal_port_is_a_reapply` | karşılandı |
| `P2ForeignInternalPort.test_real_listener_is_found_with_our_pid` (178) | aynı | `real_listener_is_found_with_our_pid` | karşılandı |
| `P2ForeignInternalPort.test_fake_proc_tree_unit_detection` (189) | aynı sahte `/proc` | `fake_proc_tree_unit_detection` | karşılandı |
| `P5RelativeBin` (222) | ikili engelleri | alttaki satırlar | karşılandı |
| `P5RelativeBin.test_relative_bin_is_a_blocker` (225) | aynı | `relative_bin_is_a_blocker`, `parity_relative_or_non_executable_bin_is_a_blocker` | karşılandı |
| `P5RelativeBin.test_non_executable_bin_is_a_blocker` (236) | aynı | `non_executable_bin_is_a_blocker`, `parity_relative_or_non_executable_bin_is_a_blocker` | karşılandı |
| `P6Quoting` (245) | tırnak ve denetim karakteri | alttaki satırlar | karşılandı |
| `P6Quoting.test_bin_and_dist_with_spaces_are_quoted` (248) | aynı | `bin_and_dist_with_spaces_are_quoted` | karşılandı |
| `P6Quoting.test_applied_unit_with_spaced_bin_has_one_execstart_word` (257) | `unit_text` üzerinden | `bin_and_dist_with_spaces_are_quoted` | karşılandı |
| `P6Quoting.test_control_characters_in_paths_block` (266) | aynı | `control_characters_in_paths_block`, `parity_control_characters_in_bin_block` | karşılandı |
| `P7SecretEnv` (279) | gizli testleri | alttaki satırlar | karşılandı |
| `P7SecretEnv.test_env_does_not_prevent_the_file` (283) | `ensure_secret_file`, `read_secret` | `env_is_ignored_for_the_file_but_wins_for_reading`, `secret_lock_contract_with_python` | karşılandı |
| `P7SecretEnv.test_front_on_writes_the_file_even_with_env` (293) | `on` gizliyi ortamdan bağımsız üretir | `applied_unit_passes_the_secret_state_dir` | karşılandı |
| `P8RelativeStateDir` (300) | kök denetimi | alttaki satırlar | karşılandı |
| `P8RelativeStateDir.PY` (304) | `tests/common` `repo` | `parity_relative_state_dir_is_refused` | karşılandı |
| `P8RelativeStateDir._env` (306) | `Sandbox::cmd` | `parity_relative_state_dir_is_refused` | karşılandı |
| `P8RelativeStateDir.test_relative_state_dir_is_refused_before_anything_is_written` (311) | `Roots::check_absolute` | `roots_follow_paths_py`, `parity_relative_state_dir_is_refused` | karşılandı |
| `P8RelativeStateDir.test_absolute_state_dir_still_works` (325) | `Roots::from_values` | `roots_follow_paths_py` | karşılandı |
| `P3Rollback` (333) | (c) testleri | alttaki satırlar | karşılandı |
| `P3Rollback.test_applied_on_succeeds_and_verifies` (337) | aynı | `applied_unit_passes_the_secret_state_dir` | karşılandı |
| `P3Rollback.test_on_rolls_back_at_every_systemctl_step` (348) | aynı | `fix_c_on_rolls_back_at_every_systemctl_step` | karşılandı |
| `P3Rollback.test_front_not_listening_is_rolled_back` (365) | aynı | `fix_c_front_not_listening_is_rolled_back` | karşılandı |
| `P3Rollback.test_on_web_not_on_internal_is_rolled_back` (377) | aynı | `fix_c_on_web_not_on_internal_is_rolled_back` | karşılandı |
| `P3Rollback.test_reapply_failure_restores_previous_unit_and_restarts_old_front` (386) | aynı | `fix_c_reapply_failure_restores_previous_unit_and_restarts_old_front` | karşılandı |
| `P3Rollback.test_write_failure_restores_files_without_systemctl` (396) | aynı | `fix_c_write_failure_restores_files_without_systemctl` | karşılandı |
| `P3Rollback.test_on_listen_change_failure_restarts_old_front_instead_of_stopping_it` (411) | aynı | `fix_c_on_listen_change_failure_restarts_old_front_instead_of_stopping_it` | karşılandı |
| `P3Rollback.test_on_rollback_keeps_previous_enablement` (423) | aynı | `fix_c_on_rollback_keeps_previous_enablement` | karşılandı |
| `P3Rollback.test_unknown_front_state_changes_nothing` (439) | aynı | `unknown_front_state_changes_nothing` | karşılandı |
| `P3Rollback.test_unreadable_web_unit_is_a_blocker` (452) | aynı | `unreadable_web_unit_is_a_blocker` | karşılandı |
| `P3Rollback.test_off_success_sequence_and_verifies_web` (459) | aynı | `off_success_sequence_matches_python_and_verifies_web` | karşılandı |
| `P3Rollback.test_off_disable_failure_changes_nothing` (468) | aynı | `fix_c_off_disable_failure_changes_nothing`, `parity_apply_rollback_on_systemctl_failure` | karşılandı |
| `P3Rollback.test_off_disable_failure_keeps_stopped_front_stopped` (477) | aynı | `fix_c_off_disable_failure_keeps_stopped_front_stopped` | karşılandı |
| `P3Rollback.test_off_web_restart_failure_returns_to_front` (486) | aynı | `fix_c_off_web_restart_failure_returns_to_front`, `parity_apply_rollback_on_systemctl_failure` | karşılandı |
| `P3Rollback.test_off_web_not_back_outside_is_rolled_back` (497) | aynı | `fix_c_off_web_not_back_outside_is_rolled_back` | karşılandı |
| `P3Rollback.test_off_port_not_released_stops_before_touching_web` (506) | aynı | `fix_c_off_port_not_released_stops_before_touching_web` | karşılandı |
| `P3Rollback.test_off_without_front_unit_ignores_disable_error` (515) | aynı | `off_without_front_unit_ignores_disable_error_like_python` | karşılandı |
| `P3Rollback.test_off_verifies_web_on_its_own_port_when_front_listen_differs` (522) | aynı | `off_verifies_web_on_its_own_port_when_front_listen_differs` | karşılandı |
| `P3Rollback.test_off_falls_back_to_front_listen_when_web_unit_is_missing` (534) | aynı | `off_falls_back_to_front_listen_when_web_unit_is_missing` | karşılandı |
| `P3Rollback.test_web_addr_follows_web_unit_flags` (547) | aynı vektörler | `web_addr_follows_web_unit_flags` | karşılandı |
| `P3Rollback.test_atomic_write_snapshot_restore_roundtrip` (555) | `fsx` testleri | `write_snapshot_restore_roundtrip`, `failed_write_leaves_no_temp_and_keeps_target` | karşılandı |
| `P4RestartRunningFront` (574) | çalışan ön kapı | alttaki satırlar | karşılandı |
| `P4RestartRunningFront.test_on_restarts_an_already_running_front_so_the_new_unit_applies` (577) | aynı | `on_restarts_an_already_running_front_so_the_new_unit_applies` | karşılandı |
| `P4RestartRunningFront.test_restart_failure_is_rolled_back_with_old_unit` (585) | geri almada eski birimle `restart` | `parity_on_restarts_running_front_then_rolls_back_unverified`, `fix_c_on_listen_change_failure_restarts_old_front_instead_of_stopping_it` | karşılandı |

### Sayım ve denetim

| satır kümesi | toplam | karşılandı | kapsam dışı | EKSİK |
|---|---|---|---|---|
| `ast` öğeleri (`front.py` 10, `front_cmd.py` 61, `test_front_cmd.py` 8, `test_front_internal.py` 29, `test_front_xff.py` 13, `test_front_pyfix.py` 65) | 186 | 149 | 37 | 0 |
| `paths.py` (yalnız değişen satır) | 1 | 1 | 0 | 0 |
| `self` (bash) | 6 | 5 | 1 | 0 |
| `list` (tek satır) | 1 | 0 | 1 | 0 |
| **toplam** | **194** | **155** | **39** | **0** |

`ast` öğesi = işlev, sınıf, metot, iç içe tanım, modül/sınıf düzeyi atama ve sabit metinli `re.*` çağrısı. Denetim betiği
(oturum scratchpad'inde, repoya girmedi): 186 öğenin her biri ad ve satır numarasıyla kendi dosyasının tablosunda bulundu
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
- py/ değişti (`front_cmd.py`, `front.py`, `paths.py`): birleşince `systemctl --user restart claudeops-web.service` + uzak deploy
  (yuhem, ulak_31; CLAUDE.md "Federasyon"). `paths.py` her süreçte yüklenir: göreli `CLAUDEOPS_DIR` artık açılışta hata.

## Bilinçli sapmalar

"Python hatası?" 1-8 Python'da düzeltildikten sonra kalanlar:

- Gizli: kilit 30 sn ile sınırlı (Python süresiz bekler); dosya + dizin `fsync`; 64 KiB üstü dosya kullanılamaz (okuma kuralı
  `cops-proxy`de).
- Göreli `HOME` Rust'ta açık hata (Python `py/cops`un `cd py/` adımıyla `py/`ye göre çözer; görev kapsamı dışında bırakıldı);
  göreli `--bin` `status`ta çağıranın dizinine göre (Python `py/`ye göre; yalnız "ikili: var/YOK" satırı).
- Hata metinlerinin içindeki işletim sistemi hata metni dile göre farklı (`io::Error` / `OSError`); `{:?}` taklidi (`_rdbg`)
  yazdırılamaz karakteri Unicode kategorisiyle seçer (Rust'ın tablosunun yaklaşığı).
- `self` Rust'ta (karşılığı bash `cmd_self`, Python'da yok); kendi uid'imizde canlı olmayan pid kaydı atlanır.
- `front on` planı Python deposunu bulamazsa 125.

## Python hatası? (sahip sorusu TBD#393; 1-8 Python'da düzeltildi, iki taraf aynı davranır)

Python testleri `py/tests/test_front_pyfix.py`; Rust eşlik testleri `tests/py_parity.rs` (aynı girdiyle iki taraf, aynı
stdout/stderr/çıkış kodu ve systemctl sırası).

| # | hata | fix commit'i | Python testi | Rust eşliği |
|---|---|---|---|---|
| 1 | `front_cmd.py`: `--internal 28765` bozuk birim yazar; sayı olmayan port döküm verir; `[::1]` hata | `b754e820` | `P1Addresses` (4 test) | `parity_bad_addresses_are_blockers_on_both_sides` |
| 2 | drop-in varken yabancı süreç iç portta ise ön kapı ona vekil olur | `ec557213` | `P2ForeignInternalPort` (4 test) | `parity_foreign_internal_port_blocks_on_both_sides` (eski `fix_b_diverges_from_python_on_foreign_internal_port`) |
| 3 | geri alma yok; `off` `disable --now` sonucunu yok sayıyor (ek: atomik yazım, doğrulama, okunamayan web birimi engel) | `f25c78cb` | `P3Rollback` (21 test), `test_front_cmd.T.test_applied_unit_passes_the_secret_state_dir` (sahte port sahibi) | `parity_apply_rollback_on_systemctl_failure` |
| 4 | çalışan ön kapıda yalnız `enable --now`; değişen birim uygulanmaz | `f2d1fc02` | `P4RestartRunningFront` (2 test) | `parity_on_restarts_running_front_then_rolls_back_unverified` |
| 5 | göreli `--bin` birime göreli yazılır, systemd reddeder (ek: çalıştırılamaz ikili engel) | `026b2045` | `P5RelativeBin` (2 test) | `parity_relative_or_non_executable_bin_is_a_blocker` |
| 6 | `bin`/`dist` tırnaksız; boşluklu yol ExecStart'ı böler (ek: denetim karakterli yol engel) | `5a4f67f5` | `P6Quoting` (3 test) | `parity_control_characters_in_bin_block` |
| 7 | `front.py`: `CLAUDEOPS_FRONT_SECRET` doluyken `ensure_secret` dosya üretmez | `9ca1bcb9` | `P7SecretEnv` (2 test) | `secret_lock_contract_with_python` (4. adım) |
| 8 | `paths.py` + `py/cops`: göreli `CLAUDEOPS_DIR` `py/` altına çözülür; artık `paths.py` açık hata (`SystemExit`, hiçbir şey yazılmadan; yalnız ortam değeri, göreli `HOME` dokunulmadı); canlı birimlerde, çalışan süreçlerde ve testlerde göreli değer yok (grep + `/proc/<pid>/environ`) | `3e7eb872` | `P8RelativeStateDir` (2 test) | `parity_relative_state_dir_is_refused`, `roots_follow_paths_py` (Rust metni Python'unkiyle eşitlendi) |
| 9 | bash `claudeops:57-66` (silinecek araç): `self` ölü pid'li bayat kaydı seçebilir | düzeltilmedi (TBD#12) | yok | yok |

Commit sırası 1, 2, 5, 6, 7, 8, 3, 4 (3'ün doğrulaması 2'nin port sahibi taramasını kullanır). Her testin önceki kodda
kırıldığı denendi (1, 4, 5, 6, 7, 8: davranış farkı; 2, 3: yeni yardımcılar yokken test modülü/`setUp` kırılır; 2'nin davranış
farkı eski `fix_b_diverges_*` testinin "Python 0 döner" iddiasıyla belgeli). Rust ürün kodunda yalnız `Roots::check_absolute`
metni değişti (Python artık çözmüyor); gerisi belge yorumu ve test.

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
