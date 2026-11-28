# rs/proc eşleme tablosu (Python -> cops-procscan)

ÜRETİLMİŞ DOSYA, elle düzenleme. Kaynak: `rust/crates/cops-procscan/parity/mapping.py`.
Denetim: `python3 -I rust/crates/cops-procscan/parity/mapping.py --check` (EKSİK varsa da düşsün: `--strict`).

Durumlar: **karşılandı** = Rust karşılığı ve onu sınayan test/parite adımı var (not sütunu sınırı söyler); **kapsam dışı** = bu crate'in işi değil, gerekçe ve iz yazılı; **EKSİK** = kapsamda olduğu hâlde davranış ya da test karşılığı yok.

Rust yolları `rust/crates/cops-procscan/src/` altındadır; `tests/...` ve `golden.rs` crate'in `tests/` dizini, `run.py:<ad>` canlı parite koşucusunun rapor bölümü. Denetim adların kaynakta VARLIĞINI sınar, testin o davranışı gerçekten kapsadığı elle değerlendirilmiştir. Bu betik testleri koşturmaz. "Sapma N": `docs/rs-proc.md`. Modül kapsamı: TAM ve KISMİ modüllerde her `ast` tanımı (işlev, sınıf, metot, modül/sınıf sabiti, `re.*` çağrısı) bir satırdır; `commands/web.py` ve `tmux_backend.py`de yalnız crate'in üstlendikleri. Test kapsamı: kapsam modüllerini içe aktaran/yamalayan ya da üstlenilen web/tmux adlarını anan her `py/tests` dosyasının her `test*` metodu.

## Özet

| Küme | Toplam | karşılandı | kapsam dışı | EKSİK |
|---|---|---|---|---|
| tanım | 564 | 153 | 411 | 0 |
| test durumu (129 dosya) | 1723 | 115 | 1608 | 0 |

| Modül | Kapsam | Toplam | karşılandı | kapsam dışı | EKSİK |
|---|---|---|---|---|---|
| `discovery.py` | TAM | 15 | 15 | 0 | 0 |
| `session.py` | TAM | 20 | 20 | 0 | 0 |
| `session_usage.py` | TAM | 19 | 19 | 0 | 0 |
| `mirrors.py` | TAM | 6 | 6 | 0 | 0 |
| `needs_ho.py` | TAM | 20 | 20 | 0 | 0 |
| `commands/ls.py` | TAM | 2 | 2 | 0 | 0 |
| `providers/__init__.py` | KISMİ | 3 | 1 | 2 | 0 |
| `providers/base.py` | KISMİ | 73 | 6 | 67 | 0 |
| `providers/claude_provider.py` | KISMİ | 99 | 8 | 91 | 0 |
| `providers/codex_provider.py` | KISMİ | 39 | 8 | 31 | 0 |
| `providers/copilot_provider.py` | KISMİ | 38 | 5 | 33 | 0 |
| `providers/agy_provider.py` | KISMİ | 50 | 10 | 40 | 0 |
| `providers/shell_provider.py` | KISMİ | 14 | 6 | 8 | 0 |
| `providers/ucli_provider.py` | KISMİ | 89 | 10 | 79 | 0 |
| `commands/usage.py` | KISMİ | 9 | 0 | 9 | 0 |
| `model_usage.py` | KISMİ | 13 | 2 | 11 | 0 |
| `orphan_watch.py` | KISMİ | 19 | 0 | 19 | 0 |
| `paths.py` | KISMİ | 26 | 9 | 17 | 0 |
| `commands/web.py` | seçili | 7 | 3 | 4 | 0 |
| `tmux_backend.py` | seçili | 3 | 3 | 0 | 0 |

## EKSİK satırlar

Yok.

## Tanımlar

### `py/claudeops/discovery.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `discovery.py::_skipped` | sabit:33 | karşılandı | `discovery.rs::ScanDiag.session_files_bad` | `tests/fake_proc.rs::bad_session_files_are_skipped_and_counted` | Python sayacı süreç geneli, Rust tarama başına. Python düzeltildi: 6ae5da3. Tanılama `diag.skipped`ta görünür (Rust `scan` çıktısında `diag`). Python düzeltildi: 1af088ef |
| `discovery.py::_sessions_from_json` | işlev:36 | karşılandı | `discovery.rs::sessions_from_json`<br>`discovery.rs::json_pid`<br>`discovery.rs::JsonPid` | `tests/fake_proc.rs::json_source_merges_with_proc_scan`<br>`tests/fake_proc.rs::broken_proc_fields`<br>`tests/fake_proc.rs::bad_session_files_are_skipped_and_counted`<br>`tests/fake_proc.rs::overflowing_pids_are_skipped_and_counted`<br>`run.py:scan_sessions` | sapma 5; bozuk dosya ve sıfır/negatif pid atlanır (TBD#365). Python düzeltildi: 6ae5da3. `pid_t`ye sığmayan pid (2**31+, `Infinity`) atlanır ve sayılır (`Infinity`/`1e400` Rust'ta geçersiz dosya). Python düzeltildi: 35a1eb78 |
| `discovery.py::fold_background` | işlev:114 | karşılandı | `session.rs::fold_background` | `session.rs::background_folds_into_single_front`<br>`session.rs::background_fold_edge_cases_like_python`<br>`tests/fake_proc.rs::background_session_folds` | yok |
| `discovery.py::_ancestors` | işlev:142 | karşılandı | `discovery.rs::ancestors` | `tests/real_proc.rs::real_background_subshell_is_one_session` | sapma 2 (başka kullanıcının sürecinde durur) |
| `discovery.py::fold_subshells` | işlev:156 | karşılandı | `session.rs::fold_subshells` | `session.rs::subshell_tree_like_python`<br>`session.rs::subshells_fold_only_for_shell`<br>`tests/real_proc.rs::real_background_subshell_is_one_session` | yok |
| `discovery.py::fallback_name` | işlev:169 | karşılandı | `discovery.rs::fallback_name` | `discovery.rs::fallback_names`<br>`golden.rs::names_paths_and_token_format`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yok |
| `discovery.py::terminal_lost` | işlev:175 | karşılandı | `procfs.rs::OwnProc::terminal_lost`<br>`status.rs::Probe::terminal_lost` | `tests/fake_proc.rs::tmux_terminal_and_orphans`<br>`tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges`<br>`run.py:scan_sessions` | yok |
| `discovery.py::IDLE_SPIN_CPU` | sabit:184 | karşılandı | `status.rs::IDLE_SPIN_CPU` | `tests/fake_proc.rs::tmux_terminal_and_orphans` | yok |
| `discovery.py::idle_spin` | işlev:187 | karşılandı | `status.rs::Probe::idle_spin` | `tests/fake_proc.rs::tmux_terminal_and_orphans`<br>`run.py:scan_sessions` | Rust `tmux`i parametre almaz, kendisi hesaplar |
| `discovery.py::_SPIN_SINCE` | sabit:192 | karşılandı | `status.rs::OrphanTracker.since` | `tests/fake_proc.rs::tmux_terminal_and_orphans` | modül sözlüğü yerine çağıranın tuttuğu örnek |
| `discovery.py::SPIN_SECONDS` | sabit:193 | karşılandı | `status.rs::SPIN_SECONDS` | `tests/fake_proc.rs::tmux_terminal_and_orphans` | yok |
| `discovery.py::orphan_report` | işlev:196 | karşılandı | `status.rs::OrphanTracker::report` | `tests/fake_proc.rs::tmux_terminal_and_orphans`<br>`run.py:scan_orphans` | cpu yeniden yuvarlanmaz (taramada zaten tek ondalık) |
| `discovery.py::find_sessions` | işlev:219 | karşılandı | `discovery.rs::find_sessions`<br>`discovery.rs::Scan`<br>`discovery.rs::CpuMode` | `tests/fake_proc.rs::json_source_merges_with_proc_scan`<br>`tests/fake_proc.rs::json_sid_merge_rules_like_python`<br>`tests/fake_proc.rs::cpu_from_two_samples`<br>`tests/fake_proc.rs::discovers_each_cli_and_names`<br>`run.py:scan_sessions` | CPU yolu yalnız sahte `/proc` ile sınanır (canlı parite `--no-cpu`); cmdline yalnız kendi süreçte okunur. Python düzeltildi: 6ae5da3 |
| `discovery.py::find_by_name` | işlev:361 | karşılandı | `discovery.rs::find_by_name` | `tests/fake_proc.rs::find_by_name_is_exact_and_returns_every_process` | yok |
| `discovery.py::duplicates` | işlev:366 | karşılandı | `session.rs::duplicates` | `session.rs::subshells_fold_only_for_shell`<br>`list.rs::table_matches_python_layout`<br>`run.py:scan_duplicates` | yok |

### `py/claudeops/session.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `session.py::_NAME_RE` | sabit:12 | karşılandı | `session.rs::base_name` | `session.rs::base_matches_python_regex`<br>`golden.rs::names_paths_and_token_format` | yok |
| `session.py::Session` | sınıf:16 | karşılandı | `session.rs::Session` | `run.py:scan_sessions`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | ek alan `proc_id` (JSON'a yazılmaz) |
| `session.py::Session.name` | sabit:17 | karşılandı | `session.rs::Session.name` | `run.py:scan_sessions`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yok |
| `session.py::Session.pid` | sabit:18 | karşılandı | `session.rs::Session.pid` | `run.py:scan_sessions`<br>`tests/fake_proc.rs::background_session_folds` | yok |
| `session.py::Session.cwd` | sabit:19 | karşılandı | `session.rs::Session.cwd` | `run.py:scan_sessions`<br>`tests/fake_proc.rs::json_source_merges_with_proc_scan` | yok |
| `session.py::Session.sid` | sabit:20 | karşılandı | `session.rs::Session.sid` | `run.py:scan_sessions`<br>`tests/fake_proc.rs::json_sid_merge_rules_like_python` | yok |
| `session.py::Session.model` | sabit:21 | karşılandı | `session.rs::Session.model` | `run.py:scan_sessions`<br>`providers.rs::claude_info` | yok |
| `session.py::Session.permission_mode` | sabit:22 | karşılandı | `session.rs::Session.permission_mode` | `run.py:scan_sessions`<br>`providers.rs::codex_info` | yok |
| `session.py::Session.effort` | sabit:23 | karşılandı | `session.rs::Session.effort` | `run.py:scan_sessions`<br>`providers.rs::ucli_effort_presets` | yok |
| `session.py::Session.cpu` | sabit:24 | karşılandı | `session.rs::Session.cpu` | `tests/fake_proc.rs::cpu_from_two_samples` | yok |
| `session.py::Session.cli` | sabit:25 | karşılandı | `session.rs::Session.cli` | `run.py:scan_sessions`<br>`tests/fake_proc.rs::json_sid_merge_rules_like_python` | yok |
| `session.py::Session.resumed` | sabit:26 | karşılandı | `session.rs::Session.resumed` | `run.py:scan_sessions`<br>`tests/fake_proc.rs::json_source_merges_with_proc_scan` | yok |
| `session.py::Session.kind` | sabit:29 | karşılandı | `session.rs::Session.kind` | `run.py:scan_sessions`<br>`tests/fake_proc.rs::background_session_folds` | yok |
| `session.py::Session.job_id` | sabit:30 | karşılandı | `session.rs::Session.job_id` | `run.py:scan_sessions`<br>`tests/fake_proc.rs::background_session_folds` | yok |
| `session.py::Session.parked_job_id` | sabit:31 | karşılandı | `session.rs::Session.parked_job_id` | `run.py:scan_sessions`<br>`tests/fake_proc.rs::background_session_folds` | yok |
| `session.py::Session.bg_pid` | sabit:32 | karşılandı | `session.rs::Session.bg_pid` | `run.py:scan_sessions`<br>`tests/fake_proc.rs::background_session_folds` | yok |
| `session.py::Session.is_fresh` | işlev:35 | karşılandı | `session.rs::Session::is_fresh` | `run.py:scan_sessions`<br>`tests/fake_proc.rs::json_source_merges_with_proc_scan`<br>`session.rs::is_fresh_flag_and_sid_combinations`<br>`tests/fake_proc.rs::is_fresh_without_json_entry_for_every_cli` | yok |
| `session.py::Session.base` | işlev:43 | karşılandı | `session.rs::Session::base`<br>`session.rs::base_name` | `session.rs::base_matches_python_regex`<br>`golden.rs::names_paths_and_token_format`<br>`run.py:scan_sessions` | yok |
| `session.py::Session.model_short` | işlev:53 | karşılandı | `session.rs::Session::model_short` | `session.rs::model_short`<br>`run.py:list_json` | yok |
| `session.py::Session.active` | işlev:65 | karşılandı | `session.rs::Session::active` | `session.rs::active_above_two_percent`<br>`tests/fake_proc.rs::find_by_name_is_exact_and_returns_every_process` | yok |

### `py/claudeops/session_usage.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `session_usage.py::CACHE_SECONDS` | sabit:25 | karşılandı | `usage.rs::CACHE_TTL` | `usage.rs::cache_respects_ttl` | test TTL kuralını sınar, 30 sn değerini değil |
| `session_usage.py::_MAX_CACHED_FILES` | sabit:26 | karşılandı | `usage.rs::MAX_CACHED_FILES`<br>`usage.rs::Ordered` | `usage.rs::file_cache_evicts_in_insertion_order`<br>`usage.rs::summary_cache_evicts_oldest_200` | ekleme sırasıyla tahliye (dosya durumu 1, özet 200), Python gibi; küçülen dosya yer açtırmaz. Python düzeltildi: 6ae5da3 |
| `session_usage.py::_ZERO` | sabit:27 | karşılandı | `usage.rs::Totals::add` | `golden.rs::usage_totals_two_calls` | alan sırası sabit dizi |
| `session_usage.py::_lock` | sabit:29 | karşılandı | `usage.rs::lock`<br>`usage.rs::UsageCache` | `usage.rs::cache_first_none_then_value_and_error_keeps_last_good` | yok |
| `session_usage.py::_files` | sabit:31 | karşılandı | `usage.rs::UsageReader.files`<br>`usage.rs::FileState` | `usage.rs::bad_row_is_skipped_and_counted`<br>`golden.rs::usage_totals_two_calls` | yok |
| `session_usage.py::_summaries` | sabit:33 | karşılandı | `usage.rs::UsageCache.summaries`<br>`usage.rs::Summary` | `usage.rs::cache_first_none_then_value_and_error_keeps_last_good` | yok |
| `session_usage.py::_skipped` | sabit:36 | karşılandı | `usage.rs::FileState.bad`<br>`usage.rs::Usage.skipped_rows` | `usage.rs::bad_row_is_skipped_and_counted`<br>`usage.rs::long_lines_are_skipped_and_counted`<br>`golden.rs::usage_totals_two_calls`<br>`run.py:usage_real` | Python süreç geneli sayaç, Rust dosya başına. Python düzeltildi: 6ae5da3. Rust `skipped_rows` artık JSON'da; altın vektör ve parite koşucusu Python artışıyla kıyaslar; Python Tanılama `diag.skipped`. Python düzeltildi: 1af088ef |
| `session_usage.py::_MAX_LINE_BYTES` | sabit:41 | karşılandı | `transcript.rs::MAX_LINE_BYTES`<br>`transcript.rs::read_line`<br>`transcript.rs::Line`<br>`usage.rs::FileState.skip` | `usage.rs::long_lines_are_skipped_and_counted` | 64 MiB (ölçülen en uzun satır 13.234.801 bayt); tampon sınır+1'i aşmaz, kalan parça parça atılır; dosya sonundaki yarım uzun satır bir kez sayılır. Python düzeltildi: 66b47a37 |
| `session_usage.py::_SKIP_CHUNK` | sabit:42 | karşılandı | `transcript.rs::MAX_LINE_BYTES`<br>`transcript.rs::read_line`<br>`transcript.rs::Line`<br>`usage.rs::FileState.skip` | `usage.rs::long_lines_are_skipped_and_counted` | 64 MiB (ölçülen en uzun satır 13.234.801 bayt); tampon sınır+1'i aşmaz, kalan parça parça atılır; dosya sonundaki yarım uzun satır bir kez sayılır. Python düzeltildi: 66b47a37 |
| `session_usage.py::_int` | işlev:45 | karşılandı | `usage.rs::count` | `golden.rs::usage_totals_two_calls`<br>`run.py:usage_real`<br>`usage.rs::overflowing_count_row_does_not_blank_total` | sapma 4 ve 6; u64'te doyar. `int(inf)` OverflowError toplamı None yapıyordu, artık 0; Rust'ta serde o satırı ayrıştırmaz (sapma 4). Python düzeltildi: 35a1eb78 |
| `session_usage.py::_parse` | işlev:52 | karşılandı | `usage.rs::parse`<br>`usage.rs::py_key` | `golden.rs::usage_totals_two_calls`<br>`usage.rs::python_key_equality`<br>`usage.rs::bad_row_is_skipped_and_counted`<br>`run.py:usage_real` | sapma 4; dizgi olmayan model ve hashlenemeyen anahtar atlanır, sayılır. Python düzeltildi: 6ae5da3 |
| `session_usage.py::_from_row` | işlev:63 | karşılandı | `usage.rs::parse`<br>`usage.rs::py_key` | `golden.rs::usage_totals_two_calls`<br>`usage.rs::python_key_equality`<br>`usage.rs::bad_row_is_skipped_and_counted`<br>`run.py:usage_real` | sapma 4; dizgi olmayan model ve hashlenemeyen anahtar atlanır, sayılır. Python düzeltildi: 6ae5da3 |
| `session_usage.py::_merge` | işlev:88 | karşılandı | `usage.rs::UsageReader::update` | `tests/fake_proc.rs::usage_dedups_subagents_and_increments`<br>`golden.rs::usage_totals_two_calls` | yok |
| `session_usage.py::_update_file` | işlev:93 | karşılandı | `usage.rs::UsageReader::update` | `tests/fake_proc.rs::usage_dedups_subagents_and_increments`<br>`usage.rs::bad_row_is_skipped_and_counted`<br>`usage.rs::file_cache_evicts_in_insertion_order` | `mtime` tutulmaz (okuyanı yok); küçülen dosya yerinde sıfırlanır. Python düzeltildi: 6ae5da3. Satır sınırı. Python düzeltildi: 66b47a37 |
| `session_usage.py::_sum` | işlev:144 | karşılandı | `usage.rs::sum`<br>`usage.rs::Totals::add` | `golden.rs::usage_totals_two_calls`<br>`run.py:usage_real` | yok |
| `session_usage.py::usage_for_path` | işlev:161 | karşılandı | `usage.rs::UsageReader::usage_for_path`<br>`usage.rs::Usage` | `tests/fake_proc.rs::usage_dedups_subagents_and_increments`<br>`golden.rs::usage_totals_two_calls`<br>`run.py:usage_real`<br>`usage.rs::bad_row_is_skipped_and_counted` | alt ajan dosyasındaki bozuk satır toplamı boşaltmaz. Python düzeltildi: 6ae5da3 |
| `session_usage.py::_refresh` | işlev:189 | karşılandı | `usage.rs::UsageCache::refresh` | `usage.rs::cache_first_none_then_value_and_error_keeps_last_good` | yok |
| `session_usage.py::cached_usage_for_path` | işlev:198 | karşılandı | `usage.rs::UsageCache::get` | `usage.rs::cache_first_none_then_value_and_error_keeps_last_good`<br>`usage.rs::cache_respects_ttl`<br>`usage.rs::spawn_failure_does_not_lock_the_path` | başlatılamayan iş parçacığı bayrağı geri alınır (eski sapma 10). Python düzeltildi: 6ae5da3 |
| `session_usage.py::fmt_tokens` | işlev:219 | karşılandı | `usage.rs::fmt_tokens` | `usage.rs::fmt_tokens_python_examples`<br>`golden.rs::names_paths_and_token_format` | yok |

### `py/claudeops/mirrors.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `mirrors.py::LOCAL_HOST` | sabit:20 | karşılandı | `mirrors.rs::LOCAL_HOST` | `mirrors.rs::specs`<br>`golden.rs::provider_detect_and_info` | yok |
| `mirrors.py::_VALUE_FLAGS` | sabit:23 | karşılandı | `mirrors.rs::VALUE_FLAGS` | `mirrors.rs::specs`<br>`golden.rs::provider_detect_and_info` | yok |
| `mirrors.py::spec_from_cmdline` | işlev:26 | karşılandı | `mirrors.rs::spec_from_cmdline` | `mirrors.rs::specs`<br>`golden.rs::provider_detect_and_info` | yok |
| `mirrors.py::note_mirror` | işlev:61 | karşılandı | `mirrors.rs::note_mirror` | `mirrors.rs::notes_accumulate`<br>`run.py:scan_mirrors` | yok |
| `mirrors.py::running_mirrors` | işlev:72 | karşılandı | `mirrors.rs::running_mirrors` | `tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges`<br>`tests/real_proc.rs::real_viewer_process_is_seen` | cmdline yalnız uid süzgecinden sonra. Python düzeltildi: 6ae5da3 |
| `mirrors.py::focus_window` | işlev:88 | karşılandı | `mirrors.rs::focus_window`<br>`mirrors.rs::focus_with` | `mirrors.rs::focus_reports_exit_status_and_passes_exact_args`<br>`proc_cmd.rs::output_status_and_timeout` | test iç `focus_with`i sahte programla çağırır |

### `py/claudeops/needs_ho.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `needs_ho.py::_BASELINE_DIR` | sabit:16 | karşılandı | `needs_ho.rs::NeedsHo::baseline_get`<br>`needs_ho.rs::NeedsHo.state_dir` | `tests/needs_ho_git.rs::git_signals_and_baseline`<br>`run.py:needs_ho_repos` | yok |
| `needs_ho.py::_skipped` | sabit:19 | karşılandı | `needs_ho.rs::Checked.skipped` | `needs_ho.rs::broken_input_is_skipped_and_counted`<br>`needs_ho.rs::long_lines_are_skipped_and_counted` | Python süreç geneli sayaç, Rust çağrı başına (sınırı aşan satır da aynı sayaçta; Python ayrı anahtar `transcript_line_too_long`). Python düzeltildi: 6ae5da3. Tanılama `diag.skipped`. Python düzeltildi: 1af088ef |
| `needs_ho.py::_MAX_LINE_BYTES` | sabit:25 | karşılandı | `transcript.rs::MAX_LINE_BYTES`<br>`transcript.rs::read_line`<br>`needs_ho.rs::each_row` | `needs_ho.rs::long_lines_are_skipped_and_counted`<br>`golden.rs::transcripts_needs_ho`<br>`run.py:needs_ho_transcripts` | 64 MiB; metin kipi satır sonları (`\r`) ve U+FFFD aynı (altın vektörler değişmedi). Python düzeltildi: 66b47a37 |
| `needs_ho.py::_SKIP_CHUNK` | sabit:26 | karşılandı | `transcript.rs::MAX_LINE_BYTES`<br>`transcript.rs::read_line`<br>`needs_ho.rs::each_row` | `needs_ho.rs::long_lines_are_skipped_and_counted`<br>`golden.rs::transcripts_needs_ho`<br>`run.py:needs_ho_transcripts` | 64 MiB; metin kipi satır sonları (`\r`) ve U+FFFD aynı (altın vektörler değişmedi). Python düzeltildi: 66b47a37 |
| `needs_ho.py::_lines` | işlev:29 | karşılandı | `transcript.rs::MAX_LINE_BYTES`<br>`transcript.rs::read_line`<br>`needs_ho.rs::each_row` | `needs_ho.rs::long_lines_are_skipped_and_counted`<br>`golden.rs::transcripts_needs_ho`<br>`run.py:needs_ho_transcripts` | 64 MiB; metin kipi satır sonları (`\r`) ve U+FFFD aynı (altın vektörler değişmedi). Python düzeltildi: 66b47a37 |
| `needs_ho.py::_git` | işlev:48 | karşılandı | `needs_ho.rs::git`<br>`needs_ho.rs::GIT_TIMEOUT`<br>`proc_cmd.rs::run` | `tests/needs_ho_git.rs::git_signals_and_baseline`<br>`proc_cmd.rs::output_status_and_timeout` | yok |
| `needs_ho.py::_is_git_repo` | işlev:59 | karşılandı | `needs_ho.rs::is_git_repo` | `tests/needs_ho_git.rs::git_signals_and_baseline`<br>`run.py:needs_ho_repos` | yok |
| `needs_ho.py::repo_dirty` | işlev:63 | karşılandı | `needs_ho.rs::repo_dirty` | `tests/needs_ho_git.rs::git_signals_and_baseline`<br>`run.py:needs_ho_repos` | yok |
| `needs_ho.py::repo_untracked_count` | işlev:93 | karşılandı | `needs_ho.rs::repo_untracked_count` | `tests/needs_ho_git.rs::git_signals_and_baseline`<br>`run.py:needs_ho_repos` | yok |
| `needs_ho.py::_repo_key` | işlev:100 | karşılandı | `needs_ho.rs::repo_key` | `run.py:needs_ho_repos`<br>`tests/needs_ho_git.rs::git_signals_and_baseline` | Python'un yazdığı baseline'ı Rust okur (aynı sha1 adı) |
| `needs_ho.py::_repo_baseline_get` | işlev:106 | karşılandı | `needs_ho.rs::NeedsHo::baseline_get` | `tests/needs_ho_git.rs::git_signals_and_baseline`<br>`run.py:needs_ho_repos` | yok |
| `needs_ho.py::repo_baseline_set` | işlev:117 | karşılandı | `needs_ho.rs::NeedsHo::repo_baseline_set`<br>`needs_ho.rs::write_atomic` | `tests/needs_ho_git.rs::git_signals_and_baseline`<br>`needs_ho.rs::baseline_is_written_atomically` | atomik (geçici dosya + rename). Python düzeltildi: 6ae5da3 |
| `needs_ho.py::repo_committed_since` | işlev:126 | karşılandı | `needs_ho.rs::NeedsHo::repo_committed_since`<br>`needs_ho.rs::committed_after`<br>`needs_ho.rs::from_iso` | `tests/needs_ho_git.rs::git_signals_and_baseline`<br>`golden.rs::committed_after_iso_rules`<br>`needs_ho.rs::iso_times_compare_as_instants`<br>`run.py:needs_ho_repos` | sapma 7 |
| `needs_ho.py::_RFH` | sabit:161 | karşılandı | `needs_ho.rs::RFH` | `golden.rs::rfh_marker` | yok |
| `needs_ho.py::rfh_marker_in` | işlev:164 | karşılandı | `needs_ho.rs::rfh_marker_in` | `golden.rs::rfh_marker`<br>`needs_ho.rs::prose_mention_is_not_a_marker`<br>`needs_ho.rs::heading_and_bare_line_count`<br>`needs_ho.rs::code_block_and_quote_do_not_count` | yok |
| `needs_ho.py::rfh_marker_in::re1` | regex:174 | karşılandı | `needs_ho.rs::rfh_marker_in` | `golden.rs::rfh_marker`<br>`needs_ho.rs::prose_mention_is_not_a_marker`<br>`needs_ho.rs::heading_and_bare_line_count`<br>`needs_ho.rs::code_block_and_quote_do_not_count` | yok |
| `needs_ho.py::_text_blocks` | işlev:179 | karşılandı | `needs_ho.rs::text_blocks` | `needs_ho.rs::broken_input_is_skipped_and_counted`<br>`golden.rs::transcripts_needs_ho` | dizgi olmayan `text` yok sayılır ve sayılır. Python düzeltildi: 6ae5da3 |
| `needs_ho.py::handover_done` | işlev:192 | karşılandı | `needs_ho.rs::handover_done`<br>`needs_ho.rs::each_row`<br>`needs_ho.rs::Checked` | `golden.rs::transcripts_needs_ho`<br>`needs_ho.rs::only_assistant_rows_carry_the_marker`<br>`needs_ho.rs::broken_input_is_skipped_and_counted`<br>`run.py:needs_ho_transcripts` | sapma 4; beklenmeyen tipte kayıt atlanır ve sayılır. Python düzeltildi: 6ae5da3 |
| `needs_ho.py::has_real_user_turn` | işlev:239 | karşılandı | `needs_ho.rs::has_real_user_turn`<br>`needs_ho.rs::each_row` | `golden.rs::transcripts_needs_ho`<br>`needs_ho.rs::real_user_turn_filters`<br>`needs_ho.rs::broken_input_is_skipped_and_counted`<br>`run.py:needs_ho_transcripts` | nesne olmayan `message` atlanır ve sayılır. Python düzeltildi: 6ae5da3 |
| `needs_ho.py::needs_ho` | işlev:287 | karşılandı | `needs_ho.rs::NeedsHo::needs_ho` | `tests/needs_ho_git.rs::git_signals_and_baseline`<br>`needs_ho.rs::needs_ho_decides_with_bad_rows`<br>`run.py:needs_ho_repos` | kullanılmayan `sid` parametresi alınmadı; bozuk satırda istisna yok. Python düzeltildi: 6ae5da3 |

### `py/claudeops/commands/ls.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `commands/ls.py::register` | işlev:11 | karşılandı | `bin/cops-procscan.rs::run` | `run.py:list_json`<br>`run.py:list_table` | `--base` ayrıştırması ve `ls` takma adı ikili düzeyinde sınanmıyor; `cops list` komutuna bağlama T6 |
| `commands/ls.py::run` | işlev:19 | karşılandı | `list.rs::render`<br>`bin/cops-procscan.rs::run` | `list.rs::json_is_sorted_valid_and_has_no_table`<br>`list.rs::table_matches_python_layout`<br>`run.py:list_json`<br>`run.py:list_table` | yok |

### `py/claudeops/providers/__init__.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `providers/__init__.py::DEFAULT_CLI` | sabit:14 | kapsam dışı | yok | yok | yeni oturum açılışının varsayılan sağlayıcısı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/__init__.py::PROVIDERS` | sabit:16 | karşılandı | `providers.rs::Cli`<br>`providers.rs::Cli::detect` | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | bir argv en çok bir sağlayıcıya uyduğundan sıra önemsiz |
| `providers/__init__.py::get_provider` | işlev:26 | kapsam dışı | yok | yok | ada göre sağlayıcı nesnesi (açılış ve durum alanları); taramada gerekmiyor. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/claudeops/providers/base.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `providers/base.py::cmd_arg` | işlev:20 | karşılandı | `providers.rs::arg` | `golden.rs::provider_detect_and_info`<br>`providers.rs::claude_info` | yok |
| `providers/base.py::OneshotError` | sınıf:28 | kapsam dışı | yok | yok | tek atımlık model çağrısı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `providers/base.py::McpServerSpec` | sınıf:33 | kapsam dışı | yok | yok | MCP kaydı ve açılış argümanları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::McpServerSpec.name` | sabit:44 | kapsam dışı | yok | yok | MCP kaydı ve açılış argümanları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::McpServerSpec.command` | sabit:45 | kapsam dışı | yok | yok | MCP kaydı ve açılış argümanları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::McpServerSpec.args` | sabit:46 | kapsam dışı | yok | yok | MCP kaydı ve açılış argümanları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::McpServerSpec.allowed_tools` | sabit:49 | kapsam dışı | yok | yok | MCP kaydı ve açılış argümanları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider` | sınıf:52 | karşılandı | `providers.rs::Cli` | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yalnız tanıma/ayrıştırma yüzeyi; kalan metotlar kendi satırında |
| `providers/base.py::CliProvider.name` | sabit:53 | karşılandı | `providers.rs::Cli::as_str` | `golden.rs::provider_detect_and_info` | yok |
| `providers/base.py::CliProvider.accepts_cli_opts` | sabit:57 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.mcp_needs_cwd` | sabit:61 | kapsam dışı | yok | yok | MCP kaydı ve açılış argümanları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.validate_cli_opts` | işlev:63 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.resolve_resume_id` | işlev:70 | kapsam dışı | yok | yok | devam/devir/canlı model değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/base.py::CliProvider.build_inner_command` | işlev:92 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.has_conversation` | işlev:113 | kapsam dışı | yok | yok | devam/devir/canlı model değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/base.py::CliProvider.wants_handover_wrapup` | işlev:121 | kapsam dışı | yok | yok | devam/devir/canlı model değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/base.py::CliProvider.wants_stuck_recovery` | işlev:125 | kapsam dışı | yok | yok | devam/devir/canlı model değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/base.py::CliProvider.last_exchange` | işlev:129 | kapsam dışı | yok | yok | sohbet geçmişi okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/base.py::CliProvider.full_history` | işlev:138 | kapsam dışı | yok | yok | sohbet geçmişi okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/base.py::CliProvider.sid_for_stopped_session` | işlev:147 | kapsam dışı | yok | yok | sohbet geçmişi okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/base.py::CliProvider.last_message_role` | işlev:162 | kapsam dışı | yok | yok | sohbet geçmişi okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/base.py::CliProvider.handover_model_downgrade` | işlev:175 | kapsam dışı | yok | yok | devam/devir/canlı model değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/base.py::CliProvider.apply_live_model_switch` | işlev:185 | kapsam dışı | yok | yok | devam/devir/canlı model değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/base.py::CliProvider.handover_effort_downgrade` | işlev:193 | kapsam dışı | yok | yok | devam/devir/canlı model değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/base.py::CliProvider.apply_live_effort_switch` | işlev:200 | kapsam dışı | yok | yok | devam/devir/canlı model değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/base.py::CliProvider.prompt_cache_ttl_seconds` | işlev:206 | kapsam dışı | yok | yok | `/api/status` satır alanları (durum dosyası/transkript). İz: T1 (durum) |
| `providers/base.py::CliProvider.last_request_epoch` | işlev:218 | kapsam dışı | yok | yok | `/api/status` satır alanları (durum dosyası/transkript). İz: T1 (durum) |
| `providers/base.py::CliProvider.effort_switch_keeps_cache` | işlev:226 | kapsam dışı | yok | yok | devam/devir/canlı model değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/base.py::CliProvider.dismiss_stray_dialog` | işlev:233 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/base.py::CliProvider.input_settle_delay` | işlev:252 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/base.py::CliProvider.prepare_input` | işlev:264 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/base.py::CliProvider.compact_command` | işlev:269 | kapsam dışı | yok | yok | devam/devir/canlı model değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/base.py::CliProvider.usage_fresh_argv` | işlev:284 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/base.py::CliProvider.usage_fresh_tui_argv` | işlev:290 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/base.py::CliProvider.usage_auth_missing` | işlev:295 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/base.py::CliProvider.parse_fresh_usage` | işlev:299 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/base.py::CliProvider.usage_command` | işlev:303 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/base.py::CliProvider.parse_usage_text` | işlev:319 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/base.py::CliProvider.context_command` | işlev:330 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/base.py::CliProvider.parse_context_text` | işlev:344 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/base.py::CliProvider.context_needs_dismiss` | işlev:356 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/base.py::CliProvider.usage_needs_dismiss` | işlev:367 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/base.py::CliProvider.extra_file_roots` | işlev:379 | kapsam dışı | yok | yok | dosya gezgini kökleri. İz: T3 (dosya) |
| `providers/base.py::CliProvider.env_overrides` | işlev:394 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.mcp_launch_args` | işlev:410 | kapsam dışı | yok | yok | MCP kaydı ve açılış argümanları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.mcp_setup_command` | işlev:421 | kapsam dışı | yok | yok | MCP kaydı ve açılış argümanları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.oneshot_argv` | işlev:433 | kapsam dışı | yok | yok | tek atımlık model çağrısı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `providers/base.py::CliProvider.oneshot` | işlev:440 | kapsam dışı | yok | yok | tek atımlık model çağrısı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `providers/base.py::CliProvider.matches_proc` | işlev:464 | karşılandı | `providers.rs::Cli::detect` | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yok |
| `providers/base.py::CliProvider.extract_name` | işlev:468 | karşılandı | `providers.rs::Cli::extract_name` | `tests/fake_proc.rs::discovers_each_cli_and_names`<br>`tests/fake_proc.rs::broken_proc_fields` | yok |
| `providers/base.py::CliProvider.extract_info` | işlev:473 | karşılandı | `providers.rs::Cli::extract_info`<br>`providers.rs::Info` | `golden.rs::provider_detect_and_info` | yok |
| `providers/base.py::CliProvider.model_choices` | işlev:485 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.refresh_stored_model` | işlev:488 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.permission_modes` | işlev:497 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.effort_levels` | işlev:501 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.model_effort_levels` | işlev:504 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.effort_levels_for` | işlev:514 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.default_permission_mode` | işlev:520 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.preferred_default_model` | işlev:525 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.default_effort` | işlev:530 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.resolve_effort` | işlev:536 | kapsam dışı | yok | yok | açılış argv/env ve model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/base.py::CliProvider.mode_status_patterns` | işlev:548 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/base.py::CliProvider.busy_status_pattern` | işlev:555 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/base.py::CliProvider.background_work` | işlev:565 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/base.py::CliProvider.live_busy` | işlev:571 | kapsam dışı | yok | yok | `/api/status` satır alanları (durum dosyası/transkript). İz: T1 (durum) |
| `providers/base.py::CliProvider.live_tools` | işlev:584 | kapsam dışı | yok | yok | `/api/status` satır alanları (durum dosyası/transkript). İz: T1 (durum) |
| `providers/base.py::CliProvider.live_context` | işlev:589 | kapsam dışı | yok | yok | `/api/status` satır alanları (durum dosyası/transkript). İz: T1 (durum) |
| `providers/base.py::CliProvider.live_usage` | işlev:596 | kapsam dışı | yok | yok | `/api/status` satır alanları (durum dosyası/transkript). İz: T1 (durum) |
| `providers/base.py::CliProvider.live_failed_turns` | işlev:606 | kapsam dışı | yok | yok | `/api/status` satır alanları (durum dosyası/transkript). İz: T1 (durum) |
| `providers/base.py::CliProvider.live_phase` | işlev:611 | kapsam dışı | yok | yok | `/api/status` satır alanları (durum dosyası/transkript). İz: T1 (durum) |
| `providers/base.py::CliProvider.cyclable_modes` | işlev:620 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/base.py::CliProvider.snapshot_for_live_sid` | işlev:629 | kapsam dışı | yok | yok | devam/devir/canlı model değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/base.py::CliProvider.discover_live_sid` | işlev:650 | kapsam dışı | yok | yok | devam/devir/canlı model değiştirme. İz: T4 (yaşam döngüsü) |

### `py/claudeops/providers/claude_provider.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `providers/claude_provider.py::MODEL_CHOICES` | sabit:18 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::PERMISSION_MODES` | sabit:24 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::EFFORT_LEVELS` | sabit:25 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::_SONNET_PIN_RE` | sabit:29 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::_sonnet_version` | işlev:32 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::_USAGE_HEADER_RE` | sabit:39 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/claude_provider.py::_USAGE_PERCENT_RE` | sabit:40 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/claude_provider.py::_USAGE_RESETS_RE` | sabit:41 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/claude_provider.py::_USAGE_FRESH_RE` | sabit:43 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/claude_provider.py::_CONTEXT_TOTAL_RE` | sabit:48 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/claude_provider.py::_CONTEXT_CATEGORY_RE` | sabit:49 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/claude_provider.py::MODE_STATUS_PATTERNS` | sabit:61 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/claude_provider.py::CYCLABLE_MODES` | sabit:73 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/claude_provider.py::BUSY_STATUS_PATTERN` | sabit:80 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/claude_provider.py::_encode_cwd` | işlev:83 | karşılandı | `transcript.rs::encode_cwd` | `transcript.rs::encodes_non_ascii_per_char`<br>`golden.rs::names_paths_and_token_format` | yok |
| `providers/claude_provider.py::_encode_cwd::re1` | regex:99 | karşılandı | `transcript.rs::encode_cwd` | `transcript.rs::encodes_non_ascii_per_char`<br>`golden.rs::names_paths_and_token_format` | yok |
| `providers/claude_provider.py::_safe_mtime` | işlev:102 | kapsam dışı | yok | yok | cwd'deki en yeni transkript düşüşü BİLEREK taşınmadı (sapma 1); düşüşe dayanan Python çağıranları taşınırken yeniden karar gerekir. İz: T1 (durum); T4 (yaşam döngüsü) |
| `providers/claude_provider.py::jsonl_path_for` | işlev:110 | karşılandı | `transcript.rs::jsonl_path_for` | `tests/fake_proc.rs::transcript_requires_exact_sid`<br>`run.py:scan_sessions` | sapma 1: yalnız tam sid; en yeni dosyaya düşüş yok; `/`/NUL içeren sid yok sayılır. Python düzeltildi: 6ae5da3. Sid VARKEN Python da yalnız tam dosya, yoksa None (sözleşme: None = transkript yok). Python düzeltildi: 43753998. Kalan kasıtlı fark: sid YOKKEN Python tahmini (koşucu `KNOWN_DEVIATIONS`, `python_guess_without_sid`) |
| `providers/claude_provider.py::find_latest_jsonl` | işlev:131 | kapsam dışı | yok | yok | cwd'deki en yeni transkript düşüşü BİLEREK taşınmadı (sapma 1); düşüşe dayanan Python çağıranları taşınırken yeniden karar gerekir. İz: T1 (durum); T4 (yaşam döngüsü) |
| `providers/claude_provider.py::_LAST_MODEL_CHUNK_BYTES` | sabit:149 | kapsam dışı | yok | yok | transkriptten canlı model/effort ve önbellek yaşı. İz: rs/prov (G3 transkript okuma); canlı bağlantı T1 |
| `providers/claude_provider.py::_LAST_MODEL_MAX_BYTES` | sabit:150 | kapsam dışı | yok | yok | transkriptten canlı model/effort ve önbellek yaşı. İz: rs/prov (G3 transkript okuma); canlı bağlantı T1 |
| `providers/claude_provider.py::_row_epoch` | işlev:153 | kapsam dışı | yok | yok | transkriptten canlı model/effort ve önbellek yaşı. İz: rs/prov (G3 transkript okuma); canlı bağlantı T1 |
| `providers/claude_provider.py::_last_assistant_value` | işlev:164 | kapsam dışı | yok | yok | transkriptten canlı model/effort ve önbellek yaşı. İz: rs/prov (G3 transkript okuma); canlı bağlantı T1 |
| `providers/claude_provider.py::last_assistant_model` | işlev:214 | kapsam dışı | yok | yok | transkriptten canlı model/effort ve önbellek yaşı. İz: rs/prov (G3 transkript okuma); canlı bağlantı T1 |
| `providers/claude_provider.py::last_assistant_effort` | işlev:220 | kapsam dışı | yok | yok | transkriptten canlı model/effort ve önbellek yaşı. İz: rs/prov (G3 transkript okuma); canlı bağlantı T1 |
| `providers/claude_provider.py::PROMPT_CACHE_TTL_SECONDS` | sabit:234 | kapsam dışı | yok | yok | transkriptten canlı model/effort ve önbellek yaşı. İz: rs/prov (G3 transkript okuma); canlı bağlantı T1 |
| `providers/claude_provider.py::_real_request_epoch` | işlev:237 | kapsam dışı | yok | yok | transkriptten canlı model/effort ve önbellek yaşı. İz: rs/prov (G3 transkript okuma); canlı bağlantı T1 |
| `providers/claude_provider.py::last_real_request_epoch` | işlev:260 | kapsam dışı | yok | yok | transkriptten canlı model/effort ve önbellek yaşı. İz: rs/prov (G3 transkript okuma); canlı bağlantı T1 |
| `providers/claude_provider.py::session_file_sid` | işlev:266 | kapsam dışı | yok | yok | oturum kimliği ve devam kimliği. İz: rs/prov (G1, açık); canlı bağlantı T4 |
| `providers/claude_provider.py::_EFFORT_BUSTS_CACHE_RE` | sabit:299 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::live_or_spawn_model` | işlev:302 | kapsam dışı | yok | yok | transkriptten canlı model/effort ve önbellek yaşı. İz: rs/prov (G3 transkript okuma); canlı bağlantı T1 |
| `providers/claude_provider.py::live_or_spawn_effort` | işlev:321 | kapsam dışı | yok | yok | transkriptten canlı model/effort ve önbellek yaşı. İz: rs/prov (G3 transkript okuma); canlı bağlantı T1 |
| `providers/claude_provider.py::_META_HEAD_LINES` | sabit:337 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::_RESUME_SCAN_LIMIT` | sabit:340 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::_jsonl_meta` | işlev:343 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::_same_path` | işlev:370 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::_META_CACHE` | sabit:378 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::_META_CACHE_MAX` | sabit:379 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::_jsonl_meta_cached` | işlev:382 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::_STUB_MAX_BYTES` | sabit:397 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::_has_chat_rows` | işlev:400 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::MCP_CONFIG_PATH` | sabit:420 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::_mcp_config_path` | işlev:423 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::_write_mcp_config_file` | işlev:437 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::_extract_text` | işlev:446 | kapsam dışı | yok | yok | sohbet geçmişi okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/claude_provider.py::_is_real_user_text` | işlev:458 | kapsam dışı | yok | yok | sohbet geçmişi okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/claude_provider.py::_HELP_CACHE` | sabit:472 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::_HELP_TIMEOUT_SECONDS` | sabit:473 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::claude_help_text` | işlev:476 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::claude_supports_flag` | işlev:498 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::claude_supports_flag::re1` | regex:501 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::ClaudeProvider` | sınıf:504 | karşılandı | `providers.rs::Cli` | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yalnız tanıma/ayrıştırma; kalan metotlar kendi satırında |
| `providers/claude_provider.py::ClaudeProvider.name` | sabit:505 | karşılandı | `providers.rs::Cli::as_str` | `golden.rs::provider_detect_and_info` | yok |
| `providers/claude_provider.py::ClaudeProvider.resolve_resume_id` | işlev:507 | kapsam dışı | yok | yok | oturum kimliği ve devam kimliği. İz: rs/prov (G1, açık); canlı bağlantı T4 |
| `providers/claude_provider.py::ClaudeProvider.build_inner_command` | işlev:551 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::ClaudeProvider.oneshot_argv` | işlev:592 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::ClaudeProvider.mcp_launch_args` | işlev:608 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::ClaudeProvider.compact_command` | işlev:616 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::ClaudeProvider.usage_command` | işlev:619 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/claude_provider.py::ClaudeProvider.usage_needs_dismiss` | işlev:622 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/claude_provider.py::ClaudeProvider.parse_usage_text` | işlev:630 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/claude_provider.py::ClaudeProvider.usage_fresh_argv` | işlev:672 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/claude_provider.py::ClaudeProvider.parse_fresh_usage` | işlev:675 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/claude_provider.py::ClaudeProvider.context_command` | işlev:684 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/claude_provider.py::ClaudeProvider.context_needs_dismiss` | işlev:687 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/claude_provider.py::ClaudeProvider.parse_context_text` | işlev:693 | kapsam dışı | yok | yok | kota/bağlam okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/claude_provider.py::ClaudeProvider.handover_model_downgrade` | işlev:750 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::ClaudeProvider._MODEL_SWITCH_TIMEOUT_SECONDS` | sabit:767 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::ClaudeProvider._MODEL_SWITCH_POLL_SECONDS` | sabit:768 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::ClaudeProvider.apply_live_model_switch` | işlev:770 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::ClaudeProvider.handover_effort_downgrade` | işlev:830 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::ClaudeProvider.prompt_cache_ttl_seconds` | işlev:843 | kapsam dışı | yok | yok | transkriptten canlı model/effort ve önbellek yaşı. İz: rs/prov (G3 transkript okuma); canlı bağlantı T1 |
| `providers/claude_provider.py::ClaudeProvider.last_request_epoch` | işlev:846 | kapsam dışı | yok | yok | transkriptten canlı model/effort ve önbellek yaşı. İz: rs/prov (G3 transkript okuma); canlı bağlantı T1 |
| `providers/claude_provider.py::ClaudeProvider.effort_switch_keeps_cache` | işlev:865 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::ClaudeProvider._EFFORT_SWITCH_TIMEOUT_SECONDS` | sabit:868 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::ClaudeProvider._EFFORT_SWITCH_POLL_SECONDS` | sabit:869 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::ClaudeProvider._EFFORT_SWITCH_DONE_MARKERS` | sabit:870 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::ClaudeProvider.apply_live_effort_switch` | işlev:873 | kapsam dışı | yok | yok | devam kimliği, devir ve canlı model/effort değiştirme. İz: T4 (yaşam döngüsü) |
| `providers/claude_provider.py::ClaudeProvider._STRAY_DIALOG_TIMEOUT_SECONDS` | sabit:932 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/claude_provider.py::ClaudeProvider._STRAY_DIALOG_POLL_SECONDS` | sabit:933 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/claude_provider.py::ClaudeProvider.dismiss_stray_dialog` | işlev:935 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/claude_provider.py::ClaudeProvider.matches_proc` | işlev:976 | karşılandı | `providers.rs::Cli::detect` | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yok |
| `providers/claude_provider.py::ClaudeProvider.extract_name` | işlev:981 | karşılandı | `providers.rs::Cli::extract_name` | `tests/fake_proc.rs::discovers_each_cli_and_names` | yok |
| `providers/claude_provider.py::ClaudeProvider.extract_info` | işlev:984 | karşılandı | `providers.rs::Cli::extract_info` | `golden.rs::provider_detect_and_info`<br>`providers.rs::claude_info` | yok |
| `providers/claude_provider.py::ClaudeProvider.preferred_default_model` | işlev:992 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::ClaudeProvider.default_effort` | işlev:998 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::ClaudeProvider.model_choices` | işlev:1001 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::ClaudeProvider.refresh_stored_model` | işlev:1016 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::ClaudeProvider.permission_modes` | işlev:1035 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::ClaudeProvider.effort_levels` | işlev:1038 | kapsam dışı | yok | yok | açılış argv'si, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/claude_provider.py::ClaudeProvider.mode_status_patterns` | işlev:1041 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/claude_provider.py::ClaudeProvider.background_work` | işlev:1044 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/claude_provider.py::ClaudeProvider.busy_status_pattern` | işlev:1058 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/claude_provider.py::ClaudeProvider.cyclable_modes` | işlev:1061 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/claude_provider.py::ClaudeProvider._transcript_lines` | işlev:1064 | kapsam dışı | yok | yok | sohbet geçmişi okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/claude_provider.py::ClaudeProvider.last_exchange` | işlev:1090 | kapsam dışı | yok | yok | sohbet geçmişi okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/claude_provider.py::ClaudeProvider.extra_file_roots` | işlev:1120 | kapsam dışı | yok | yok | dosya gezgini kökleri. İz: T3 (dosya) |
| `providers/claude_provider.py::ClaudeProvider.full_history` | işlev:1125 | kapsam dışı | yok | yok | sohbet geçmişi okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/claude_provider.py::ClaudeProvider.sid_for_stopped_session` | işlev:1154 | kapsam dışı | yok | yok | sohbet geçmişi okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |

### `py/claudeops/providers/codex_provider.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `providers/codex_provider.py::CODEX_HOME` | sabit:42 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::SESSIONS_DIR` | sabit:43 | kapsam dışı | yok | yok | rollout dosyası ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/codex_provider.py::MODELS_CACHE` | sabit:44 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::PERMISSION_MODES` | sabit:46 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::EFFORT_LEVELS` | sabit:47 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::BUSY_STATUS_PATTERN` | sabit:58 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/codex_provider.py::FALLBACK_MODELS` | sabit:62 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::_NON_SESSION_SUBCOMMANDS` | sabit:77 | karşılandı | `providers.rs::CODEX_NON_SESSION` | `golden.rs::provider_detect_and_info`<br>`providers.rs::detect` | iki liste 25 öğeyle eşit (elle karşılaştırıldı); testler yalnız birkaç öğeyi sınar |
| `providers/codex_provider.py::_PERMISSION_FLAGS` | sabit:84 | karşılandı | `providers.rs::codex_mode` | `golden.rs::provider_detect_and_info`<br>`providers.rs::codex_info` | yalnız ters eşleme (argv -> mod); açılış yönü W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::_MODELS_TTL` | sabit:91 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::_ROLLOUT_UUID_RE` | sabit:92 | kapsam dışı | yok | yok | rollout dosyası ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/codex_provider.py::_MAX_ROLLOUT_SCAN` | sabit:93 | kapsam dışı | yok | yok | rollout dosyası ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/codex_provider.py::_config_value` | işlev:96 | karşılandı | `providers.rs::codex_config` | `golden.rs::provider_detect_and_info`<br>`providers.rs::codex_info` | yok |
| `providers/codex_provider.py::_safe_mtime` | işlev:104 | kapsam dışı | yok | yok | rollout dosyası ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/codex_provider.py::_session_meta` | işlev:111 | kapsam dışı | yok | yok | devam kimliği. İz: T4 (yaşam döngüsü) |
| `providers/codex_provider.py::_codex_text` | işlev:125 | kapsam dışı | yok | yok | rollout dosyası ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/codex_provider.py::_is_real_codex_user_text` | işlev:139 | kapsam dışı | yok | yok | rollout dosyası ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/codex_provider.py::CodexProvider` | sınıf:148 | karşılandı | `providers.rs::Cli` | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yalnız tanıma/ayrıştırma |
| `providers/codex_provider.py::CodexProvider.name` | sabit:149 | karşılandı | `providers.rs::Cli::as_str` | `golden.rs::provider_detect_and_info` | yok |
| `providers/codex_provider.py::CodexProvider.__init__` | işlev:151 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::CodexProvider.resolve_resume_id` | işlev:155 | kapsam dışı | yok | yok | devam kimliği. İz: T4 (yaşam döngüsü) |
| `providers/codex_provider.py::CodexProvider.build_inner_command` | işlev:178 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::CodexProvider.mcp_launch_args` | işlev:196 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::CodexProvider.env_overrides` | işlev:207 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::CodexProvider.matches_proc` | işlev:210 | karşılandı | `providers.rs::Cli::detect` | `golden.rs::provider_detect_and_info`<br>`providers.rs::detect` | yok |
| `providers/codex_provider.py::CodexProvider.extract_name` | işlev:218 | karşılandı | `providers.rs::Cli::extract_name` | `tests/fake_proc.rs::discovers_each_cli_and_names`<br>`tests/fake_proc.rs::broken_proc_fields` | yok |
| `providers/codex_provider.py::CodexProvider.extract_info` | işlev:225 | karşılandı | `providers.rs::Cli::extract_info` | `golden.rs::provider_detect_and_info`<br>`providers.rs::codex_info` | yok |
| `providers/codex_provider.py::CodexProvider.model_choices` | işlev:246 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::CodexProvider.permission_modes` | işlev:265 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::CodexProvider.effort_levels` | işlev:268 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::CodexProvider.model_effort_levels` | işlev:271 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/codex_provider.py::CodexProvider.busy_status_pattern` | işlev:292 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/codex_provider.py::CodexProvider.input_settle_delay` | işlev:295 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/codex_provider.py::CodexProvider.background_work` | işlev:306 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/codex_provider.py::CodexProvider._rollout_path` | işlev:317 | kapsam dışı | yok | yok | rollout dosyası ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/codex_provider.py::CodexProvider._transcript_lines` | işlev:336 | kapsam dışı | yok | yok | rollout dosyası ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/codex_provider.py::CodexProvider.live_context` | işlev:358 | kapsam dışı | yok | yok | `/api/status` bağlam alanı. İz: T1 (durum) |
| `providers/codex_provider.py::CodexProvider.last_exchange` | işlev:385 | kapsam dışı | yok | yok | rollout dosyası ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/codex_provider.py::CodexProvider.full_history` | işlev:410 | kapsam dışı | yok | yok | rollout dosyası ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |

### `py/claudeops/providers/copilot_provider.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `providers/copilot_provider.py::SESSION_STORE_DB` | sabit:109 | kapsam dışı | yok | yok | oturum deposu ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/copilot_provider.py::_BYOK_ENV_FILE` | sabit:121 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/copilot_provider.py::_BYOK_ENV_MANAGED_MARKER` | sabit:122 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/copilot_provider.py::_sync_byok_env_file` | işlev:125 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/copilot_provider.py::MODEL_CHOICES` | sabit:170 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/copilot_provider.py::PERMISSION_MODES` | sabit:189 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/copilot_provider.py::EFFORT_LEVELS` | sabit:190 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/copilot_provider.py::MODE_STATUS_PATTERNS` | sabit:196 | kapsam dışı | yok | yok | tmux ekranı okuma. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/copilot_provider.py::BUSY_STATUS_PATTERN` | sabit:200 | kapsam dışı | yok | yok | tmux ekranı okuma. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/copilot_provider.py::_PERMISSION_FLAGS` | sabit:202 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/copilot_provider.py::_RESUME_SCAN_LIMIT` | sabit:209 | kapsam dışı | yok | yok | devam kimliği ve klasöre güven kaydı. İz: T4 (yaşam döngüsü) |
| `providers/copilot_provider.py::_USAGE_PLAN_RE` | sabit:218 | kapsam dışı | yok | yok | kota okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/copilot_provider.py::_USAGE_FRACTION_RE` | sabit:219 | kapsam dışı | yok | yok | kota okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/copilot_provider.py::_USAGE_RESET_RE` | sabit:220 | kapsam dışı | yok | yok | kota okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/copilot_provider.py::trust_folder` | işlev:223 | kapsam dışı | yok | yok | devam kimliği ve klasöre güven kaydı. İz: T4 (yaşam döngüsü) |
| `providers/copilot_provider.py::trust_folder::re1` | regex:233 | kapsam dışı | yok | yok | devam kimliği ve klasöre güven kaydı. İz: T4 (yaşam döngüsü) |
| `providers/copilot_provider.py::trust_folder::re2` | regex:238 | kapsam dışı | yok | yok | devam kimliği ve klasöre güven kaydı. İz: T4 (yaşam döngüsü) |
| `providers/copilot_provider.py::_connect_ro` | işlev:247 | kapsam dışı | yok | yok | oturum deposu ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/copilot_provider.py::CopilotProvider` | sınıf:254 | karşılandı | `providers.rs::Cli` | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yalnız tanıma/ayrıştırma |
| `providers/copilot_provider.py::CopilotProvider.name` | sabit:255 | karşılandı | `providers.rs::Cli::as_str` | `golden.rs::provider_detect_and_info` | yok |
| `providers/copilot_provider.py::CopilotProvider.resolve_resume_id` | işlev:257 | kapsam dışı | yok | yok | devam kimliği ve klasöre güven kaydı. İz: T4 (yaşam döngüsü) |
| `providers/copilot_provider.py::CopilotProvider.build_inner_command` | işlev:285 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/copilot_provider.py::CopilotProvider.env_overrides` | işlev:312 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/copilot_provider.py::CopilotProvider.matches_proc` | işlev:318 | karşılandı | `providers.rs::Cli::detect` | `golden.rs::provider_detect_and_info`<br>`providers.rs::detect` | yok |
| `providers/copilot_provider.py::CopilotProvider.extract_name` | işlev:337 | karşılandı | `providers.rs::Cli::extract_name` | `tests/fake_proc.rs::discovers_each_cli_and_names` | agy/codex ile aynı kol; copilot'a özel ad testi yok |
| `providers/copilot_provider.py::CopilotProvider.extract_info` | işlev:344 | karşılandı | `providers.rs::Cli::extract_info` | `golden.rs::provider_detect_and_info`<br>`providers.rs::copilot_info` | yok |
| `providers/copilot_provider.py::CopilotProvider.model_choices` | işlev:360 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/copilot_provider.py::CopilotProvider.permission_modes` | işlev:363 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/copilot_provider.py::CopilotProvider.effort_levels` | işlev:366 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/copilot_provider.py::CopilotProvider.mode_status_patterns` | işlev:369 | kapsam dışı | yok | yok | tmux ekranı okuma. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/copilot_provider.py::CopilotProvider.busy_status_pattern` | işlev:372 | kapsam dışı | yok | yok | tmux ekranı okuma. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/copilot_provider.py::CopilotProvider.usage_command` | işlev:375 | kapsam dışı | yok | yok | kota okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/copilot_provider.py::CopilotProvider.parse_usage_text` | işlev:384 | kapsam dışı | yok | yok | kota okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/copilot_provider.py::CopilotProvider.usage_fresh_tui_argv` | işlev:395 | kapsam dışı | yok | yok | kota okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/copilot_provider.py::CopilotProvider._turns` | işlev:399 | kapsam dışı | yok | yok | oturum deposu ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/copilot_provider.py::CopilotProvider.live_context` | işlev:422 | kapsam dışı | yok | yok | `/api/status` bağlam alanı. İz: T1 (durum) |
| `providers/copilot_provider.py::CopilotProvider.last_exchange` | işlev:440 | kapsam dışı | yok | yok | oturum deposu ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/copilot_provider.py::CopilotProvider.full_history` | işlev:449 | kapsam dışı | yok | yok | oturum deposu ve sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |

### `py/claudeops/providers/agy_provider.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `providers/agy_provider.py::CONVERSATIONS_CACHE` | sabit:85 | karşılandı | `lib.rs::Config.agy_cache`<br>`lib.rs::Config::from_env` | `tests/fake_proc.rs::broken_agy_files`<br>`run.py:scan_sessions` | yok |
| `providers/agy_provider.py::CONVERSATIONS_DIR` | sabit:86 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::AGY_SIDS_JSON` | sabit:95 | karşılandı | `lib.rs::Config.agy_sids`<br>`lib.rs::Config::from_env` | `tests/fake_proc.rs::broken_agy_files`<br>`run.py:scan_agy_learned` | yok |
| `providers/agy_provider.py::_STEP_TYPE_USER` | sabit:99 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::_STEP_TYPE_ASSISTANT` | sabit:100 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::_STEP_TYPE_CHECKPOINT` | sabit:102 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::_read_varint` | işlev:105 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::_iter_fields` | işlev:117 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::_get_bytes_field` | işlev:145 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::_get_text_field` | işlev:161 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::_step_user_text` | işlev:166 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::_step_assistant_text` | işlev:173 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::_conversation_ids` | işlev:180 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::PERMISSION_MODES` | sabit:188 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/agy_provider.py::EFFORT_LEVELS` | sabit:189 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/agy_provider.py::BUSY_STATUS_PATTERN` | sabit:196 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/agy_provider.py::_PERMISSION_FLAGS` | sabit:198 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/agy_provider.py::_MODELS_TTL` | sabit:204 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/agy_provider.py::_load_agy_sids` | işlev:207 | karşılandı | `providers.rs::AgyState::load`<br>`providers.rs::read_object` | `tests/fake_proc.rs::broken_agy_files`<br>`run.py:scan_agy_learned` | sapma 3: DB yerine dosya aynası okunur (DB okuma W0-a) |
| `providers/agy_provider.py::_remember_agy_sid` | işlev:216 | karşılandı | `providers.rs::AgyState::resolve`<br>`providers.rs::AgyState.learned` | `providers.rs::agy_sid_rules`<br>`tests/fake_proc.rs::broken_agy_files`<br>`run.py:scan_agy_learned` | yalnız 'yazılacak mı' kararı; KİLİTLİ YAZIM TAŞINMADI (W0-a durum (rs/state); T1 (durum) bağlanmadan şart, sapma 3) |
| `providers/agy_provider.py::_sid_claimed_by_other` | işlev:234 | karşılandı | `providers.rs::AgyState::resolve` | `providers.rs::agy_sid_rules`<br>`tests/fake_proc.rs::broken_agy_files` | yok |
| `providers/agy_provider.py::AgyProvider` | sınıf:241 | karşılandı | `providers.rs::Cli` | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yalnız tanıma/ayrıştırma |
| `providers/agy_provider.py::AgyProvider.name` | sabit:242 | karşılandı | `providers.rs::Cli::as_str` | `golden.rs::provider_detect_and_info` | yok |
| `providers/agy_provider.py::AgyProvider.__init__` | işlev:244 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/agy_provider.py::AgyProvider.resolve_resume_id` | işlev:248 | kapsam dışı | yok | yok | devam kimliği ve canlı sid keşfi. İz: T4 (yaşam döngüsü) |
| `providers/agy_provider.py::AgyProvider.build_inner_command` | işlev:275 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/agy_provider.py::AgyProvider.env_overrides` | işlev:324 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/agy_provider.py::AgyProvider.mcp_setup_command` | işlev:327 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/agy_provider.py::AgyProvider.matches_proc` | işlev:337 | karşılandı | `providers.rs::Cli::detect` | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yok |
| `providers/agy_provider.py::AgyProvider.extract_name` | işlev:340 | karşılandı | `providers.rs::Cli::extract_name` | `tests/fake_proc.rs::discovers_each_cli_and_names` | yok |
| `providers/agy_provider.py::AgyProvider.extract_info` | işlev:347 | karşılandı | `providers.rs::Cli::extract_info`<br>`providers.rs::AgyState::resolve` | `golden.rs::provider_detect_and_info`<br>`providers.rs::agy_sid_rules`<br>`tests/fake_proc.rs::broken_agy_files` | yok |
| `providers/agy_provider.py::AgyProvider._fetch_models` | işlev:384 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/agy_provider.py::AgyProvider.model_choices` | işlev:398 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/agy_provider.py::AgyProvider.permission_modes` | işlev:415 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/agy_provider.py::AgyProvider.effort_levels` | işlev:418 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/agy_provider.py::AgyProvider.model_effort_levels` | işlev:421 | kapsam dışı | yok | yok | açılış argv/env, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/agy_provider.py::AgyProvider.busy_status_pattern` | işlev:434 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/agy_provider.py::AgyProvider.usage_command` | işlev:437 | kapsam dışı | yok | yok | kota okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/agy_provider.py::AgyProvider.usage_fresh_argv` | işlev:448 | kapsam dışı | yok | yok | kota okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/agy_provider.py::AgyProvider.usage_auth_missing` | işlev:453 | kapsam dışı | yok | yok | kota okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/agy_provider.py::AgyProvider.parse_fresh_usage` | işlev:458 | kapsam dışı | yok | yok | kota okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/agy_provider.py::AgyProvider.usage_needs_dismiss` | işlev:461 | kapsam dışı | yok | yok | tmux ekranı okuma ve tuş gönderme. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/agy_provider.py::AgyProvider.parse_usage_text` | işlev:471 | kapsam dışı | yok | yok | kota okuma ve ayrıştırma. İz: T7 (periyodik+kullanım) |
| `providers/agy_provider.py::AgyProvider._transcript_steps` | işlev:502 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::AgyProvider._steps_desc` | işlev:532 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::AgyProvider.last_exchange` | işlev:558 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::AgyProvider.full_history` | işlev:577 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::AgyProvider.sid_for_stopped_session` | işlev:595 | kapsam dışı | yok | yok | protobuf sohbet deposu okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/agy_provider.py::AgyProvider.snapshot_for_live_sid` | işlev:605 | kapsam dışı | yok | yok | devam kimliği ve canlı sid keşfi. İz: T4 (yaşam döngüsü) |
| `providers/agy_provider.py::AgyProvider.discover_live_sid` | işlev:615 | kapsam dışı | yok | yok | devam kimliği ve canlı sid keşfi. İz: T4 (yaşam döngüsü) |

### `py/claudeops/providers/shell_provider.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `providers/shell_provider.py::PROC_TAG` | sabit:31 | karşılandı | `providers.rs::Cli::detect` | `golden.rs::provider_detect_and_info`<br>`providers.rs::detect` | yok |
| `providers/shell_provider.py::_SENTINEL` | sabit:38 | kapsam dışı | yok | yok | açılış kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/shell_provider.py::ShellProvider` | sınıf:41 | karşılandı | `providers.rs::Cli` | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yalnız tanıma/ayrıştırma |
| `providers/shell_provider.py::ShellProvider.name` | sabit:42 | karşılandı | `providers.rs::Cli::as_str` | `golden.rs::provider_detect_and_info` | yok |
| `providers/shell_provider.py::ShellProvider.has_conversation` | işlev:44 | kapsam dışı | yok | yok | açılış kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/shell_provider.py::ShellProvider.resolve_resume_id` | işlev:47 | kapsam dışı | yok | yok | açılış kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/shell_provider.py::ShellProvider.build_inner_command` | işlev:51 | kapsam dışı | yok | yok | açılış kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/shell_provider.py::ShellProvider.env_overrides` | işlev:58 | kapsam dışı | yok | yok | açılış kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/shell_provider.py::ShellProvider.matches_proc` | işlev:61 | karşılandı | `providers.rs::Cli::detect` | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yok |
| `providers/shell_provider.py::ShellProvider.extract_name` | işlev:64 | karşılandı | `providers.rs::Cli::extract_name` | `tests/fake_proc.rs::discovers_each_cli_and_names`<br>`tests/fake_proc.rs::other_users_processes_are_never_read` | yok |
| `providers/shell_provider.py::ShellProvider.extract_info` | işlev:70 | karşılandı | `providers.rs::Cli::extract_info`<br>`providers.rs::Info` | `golden.rs::provider_detect_and_info` | yok |
| `providers/shell_provider.py::ShellProvider.model_choices` | işlev:73 | kapsam dışı | yok | yok | açılış kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/shell_provider.py::ShellProvider.permission_modes` | işlev:76 | kapsam dışı | yok | yok | açılış kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/shell_provider.py::ShellProvider.effort_levels` | işlev:79 | kapsam dışı | yok | yok | açılış kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/claudeops/providers/ucli_provider.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `providers/ucli_provider.py::_EFFORT_LIMITS` | sabit:153 | karşılandı | `providers.rs::UCLI_EFFORT` | `golden.rs::provider_detect_and_info`<br>`providers.rs::ucli_effort_presets` | yalnız ters eşleme; açılış yönü W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_EFFORT_LEVELS` | sabit:157 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_REQUEST_TIMEOUT_SECS` | sabit:167 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_MAX_HISTORY_KIB` | sabit:173 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_USAGE_FIELDS` | sabit:178 | kapsam dışı | yok | yok | durum dosyasından `/api/status` alanları. İz: T1 (durum) |
| `providers/ucli_provider.py::_PHASE_INT_FIELDS` | sabit:182 | kapsam dışı | yok | yok | durum dosyasından `/api/status` alanları. İz: T1 (durum) |
| `providers/ucli_provider.py::_READ_ONLY` | sabit:187 | karşılandı | `providers.rs::ucli_info` | `golden.rs::provider_detect_and_info`<br>`providers.rs::ucli_effort_presets` | yok |
| `providers/ucli_provider.py::_ALLOW_EDIT` | sabit:188 | karşılandı | `providers.rs::ucli_info` | `golden.rs::provider_detect_and_info`<br>`providers.rs::ucli_effort_presets` | yok |
| `providers/ucli_provider.py::_ALLOW_CREATE` | sabit:192 | karşılandı | `providers.rs::ucli_info` | `golden.rs::provider_detect_and_info`<br>`providers.rs::ucli_effort_presets` | yok |
| `providers/ucli_provider.py::_PERMISSION_MODES` | sabit:193 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_MODEL_CHOICES` | sabit:201 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::DEFAULT_ENDPOINT` | sabit:202 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_ENDPOINT` | sabit:203 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::endpoint` | işlev:206 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_MODELS_TTL` | sabit:221 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_LIVE_MODEL_CACHE` | sabit:222 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_LIVE_MODEL_CACHE_TS` | sabit:223 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_LIVE_CAPS` | sabit:226 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_fetch_live_models` | işlev:229 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_live_models` | işlev:266 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::reasoning_effort_for` | işlev:283 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_API_KEY_FILE` | sabit:307 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_API_KEY_MANAGED_MARKER` | sabit:313 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_sync_api_key_file` | işlev:316 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_web_args` | işlev:359 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_script_args` | işlev:397 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_stream_args` | işlev:411 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_reasoning_display_args` | işlev:423 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_metrics_file_args` | işlev:434 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_interactive_args` | işlev:456 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_state_dir_args` | işlev:465 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_timeout_args` | işlev:482 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_history_args` | işlev:492 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_effort_args` | işlev:509 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_set_flag_value` | işlev:527 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_service_key_file` | işlev:539 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_INSTRUCTIONS_MAX_BYTES` | sabit:543 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_instructions_too_big` | işlev:546 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::instructions_check` | işlev:557 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_claude_service_flags` | işlev:578 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_PRICED_MODELS` | sabit:612 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_claudeops_price` | işlev:614 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_argv_model` | işlev:623 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_has_price` | işlev:627 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_with_price` | işlev:631 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_effective_session_cap` | işlev:643 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_unpriced_cap_reason` | işlev:648 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::session_cap_refusal` | işlev:658 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_default_session_cap` | işlev:666 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_max_cost_args` | işlev:675 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_MCP_NAME_BAD` | sabit:690 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_MCP_TOOL_RE` | sabit:691 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_MCP_ADD_TIMEOUT` | sabit:692 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::mcp_server_name` | işlev:695 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::mcp_add_argv` | işlev:699 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::register_mcp` | işlev:708 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_apply_cli_opts` | işlev:738 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::_agent_setup` | işlev:916 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::UcliProvider` | sınıf:938 | karşılandı | `providers.rs::Cli` | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yalnız tanıma/ayrıştırma |
| `providers/ucli_provider.py::UcliProvider.name` | sabit:939 | karşılandı | `providers.rs::Cli::as_str` | `golden.rs::provider_detect_and_info` | yok |
| `providers/ucli_provider.py::UcliProvider.prepare_input` | işlev:941 | kapsam dışı | yok | yok | tmux girişi ve arka plan işi. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/ucli_provider.py::UcliProvider.has_conversation` | işlev:949 | kapsam dışı | yok | yok | devam/devir ve tek atımlık çağrı. İz: T4 (yaşam döngüsü) |
| `providers/ucli_provider.py::UcliProvider.wants_handover_wrapup` | işlev:952 | kapsam dışı | yok | yok | devam/devir ve tek atımlık çağrı. İz: T4 (yaşam döngüsü) |
| `providers/ucli_provider.py::UcliProvider.resolve_resume_id` | işlev:955 | kapsam dışı | yok | yok | devam/devir ve tek atımlık çağrı. İz: T4 (yaşam döngüsü) |
| `providers/ucli_provider.py::UcliProvider.accepts_cli_opts` | sabit:959 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::UcliProvider.mcp_needs_cwd` | sabit:960 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::UcliProvider.validate_cli_opts` | işlev:962 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::UcliProvider.mcp_launch_args` | işlev:965 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::UcliProvider.build_inner_command` | işlev:988 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::UcliProvider.oneshot` | işlev:1068 | kapsam dışı | yok | yok | devam/devir ve tek atımlık çağrı. İz: T4 (yaşam döngüsü) |
| `providers/ucli_provider.py::UcliProvider.env_overrides` | işlev:1088 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::UcliProvider.matches_proc` | işlev:1093 | karşılandı | `providers.rs::Cli::detect` | `golden.rs::provider_detect_and_info`<br>`providers.rs::detect` | yok |
| `providers/ucli_provider.py::UcliProvider._parse_session` | işlev:1098 | karşılandı | `providers.rs::arg` | `golden.rs::provider_detect_and_info`<br>`tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | yok |
| `providers/ucli_provider.py::UcliProvider.extract_name` | işlev:1104 | karşılandı | `providers.rs::Cli::extract_name` | `tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges`<br>`run.py:scan_sessions` | yok |
| `providers/ucli_provider.py::UcliProvider.extract_info` | işlev:1107 | karşılandı | `providers.rs::ucli_info` | `golden.rs::provider_detect_and_info`<br>`providers.rs::ucli_effort_presets` | yok |
| `providers/ucli_provider.py::UcliProvider.model_choices` | işlev:1143 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::UcliProvider.default_permission_mode` | işlev:1146 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::UcliProvider.permission_modes` | işlev:1151 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::UcliProvider.effort_levels` | işlev:1154 | kapsam dışı | yok | yok | açılış argv/env, MCP, model/effort/izin kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `providers/ucli_provider.py::UcliProvider.full_history` | işlev:1157 | kapsam dışı | yok | yok | sohbet geçmişi okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/ucli_provider.py::UcliProvider.sid_for_stopped_session` | işlev:1162 | kapsam dışı | yok | yok | sohbet geçmişi okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `providers/ucli_provider.py::UcliProvider.live_busy` | işlev:1168 | kapsam dışı | yok | yok | durum dosyasından `/api/status` alanları. İz: T1 (durum) |
| `providers/ucli_provider.py::UcliProvider.background_work` | işlev:1183 | kapsam dışı | yok | yok | tmux girişi ve arka plan işi. İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `providers/ucli_provider.py::UcliProvider.live_tools` | işlev:1198 | kapsam dışı | yok | yok | durum dosyasından `/api/status` alanları. İz: T1 (durum) |
| `providers/ucli_provider.py::UcliProvider.live_context` | işlev:1212 | kapsam dışı | yok | yok | durum dosyasından `/api/status` alanları. İz: T1 (durum) |
| `providers/ucli_provider.py::UcliProvider.live_usage` | işlev:1227 | kapsam dışı | yok | yok | durum dosyasından `/api/status` alanları. İz: T1 (durum) |
| `providers/ucli_provider.py::UcliProvider.live_failed_turns` | işlev:1244 | kapsam dışı | yok | yok | durum dosyasından `/api/status` alanları. İz: T1 (durum) |
| `providers/ucli_provider.py::UcliProvider.live_phase` | işlev:1267 | kapsam dışı | yok | yok | durum dosyasından `/api/status` alanları. İz: T1 (durum) |
| `providers/ucli_provider.py::UcliProvider.last_exchange` | işlev:1297 | kapsam dışı | yok | yok | sohbet geçmişi okuma. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |

### `py/claudeops/commands/usage.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `commands/usage.py::register` | işlev:20 | kapsam dışı | yok | yok | `cops usage` komutu (toplama çekirdeği `usage.rs`te; tablo/seçim/gün dökümü taşınmadı). İz: T6 (CLI); T7 (periyodik+kullanım) |
| `commands/usage.py::_weight` | işlev:33 | kapsam dışı | yok | yok | `cops usage` komutu (toplama çekirdeği `usage.rs`te; tablo/seçim/gün dökümü taşınmadı). İz: T6 (CLI); T7 (periyodik+kullanım) |
| `commands/usage.py::collect` | işlev:39 | kapsam dışı | yok | yok | `cops usage` komutu (toplama çekirdeği `usage.rs`te; tablo/seçim/gün dökümü taşınmadı). İz: T6 (CLI); T7 (periyodik+kullanım) |
| `commands/usage.py::render` | işlev:55 | kapsam dışı | yok | yok | `cops usage` komutu (toplama çekirdeği `usage.rs`te; tablo/seçim/gün dökümü taşınmadı). İz: T6 (CLI); T7 (periyodik+kullanım) |
| `commands/usage.py::render_day` | işlev:67 | kapsam dışı | yok | yok | `cops usage` komutu (toplama çekirdeği `usage.rs`te; tablo/seçim/gün dökümü taşınmadı). İz: T6 (CLI); T7 (periyodik+kullanım) |
| `commands/usage.py::run_day` | işlev:81 | kapsam dışı | yok | yok | `cops usage` komutu (toplama çekirdeği `usage.rs`te; tablo/seçim/gün dökümü taşınmadı). İz: T6 (CLI); T7 (periyodik+kullanım) |
| `commands/usage.py::render_account` | işlev:92 | kapsam dışı | yok | yok | `cops usage` komutu (toplama çekirdeği `usage.rs`te; tablo/seçim/gün dökümü taşınmadı). İz: T6 (CLI); T7 (periyodik+kullanım) |
| `commands/usage.py::render_account.age` | işlev:93 | kapsam dışı | yok | yok | `cops usage` komutu (toplama çekirdeği `usage.rs`te; tablo/seçim/gün dökümü taşınmadı). İz: T6 (CLI); T7 (periyodik+kullanım) |
| `commands/usage.py::run` | işlev:110 | kapsam dışı | yok | yok | `cops usage` komutu (toplama çekirdeği `usage.rs`te; tablo/seçim/gün dökümü taşınmadı). İz: T6 (CLI); T7 (periyodik+kullanım) |

### `py/claudeops/model_usage.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `model_usage.py::PROJECTS_DIR` | sabit:15 | kapsam dışı | yok | yok | son 60 dakika model kullanım çubuğu. İz: T7 (periyodik+kullanım) |
| `model_usage.py::WINDOW_MINUTES` | sabit:16 | kapsam dışı | yok | yok | son 60 dakika model kullanım çubuğu. İz: T7 (periyodik+kullanım) |
| `model_usage.py::CACHE_SECONDS` | sabit:17 | kapsam dışı | yok | yok | son 60 dakika model kullanım çubuğu. İz: T7 (periyodik+kullanım) |
| `model_usage.py::_BLOCK` | sabit:18 | kapsam dışı | yok | yok | son 60 dakika model kullanım çubuğu. İz: T7 (periyodik+kullanım) |
| `model_usage.py::_FAMILIES` | sabit:19 | karşılandı | `usage.rs::family` | `golden.rs::usage_totals_two_calls`<br>`run.py:usage_real` | yok |
| `model_usage.py::_lock` | sabit:21 | kapsam dışı | yok | yok | son 60 dakika model kullanım çubuğu. İz: T7 (periyodik+kullanım) |
| `model_usage.py::_state` | sabit:22 | kapsam dışı | yok | yok | son 60 dakika model kullanım çubuğu. İz: T7 (periyodik+kullanım) |
| `model_usage.py::_family` | işlev:25 | karşılandı | `usage.rs::family` | `golden.rs::usage_totals_two_calls`<br>`run.py:usage_real` | yok |
| `model_usage.py::_iter_recent_lines` | işlev:33 | kapsam dışı | yok | yok | son 60 dakika model kullanım çubuğu. İz: T7 (periyodik+kullanım) |
| `model_usage.py::_sub_effort` | işlev:61 | kapsam dışı | yok | yok | son 60 dakika model kullanım çubuğu. İz: T7 (periyodik+kullanım) |
| `model_usage.py::scan` | işlev:70 | kapsam dışı | yok | yok | son 60 dakika model kullanım çubuğu. İz: T7 (periyodik+kullanım) |
| `model_usage.py::_refresh` | işlev:145 | kapsam dışı | yok | yok | son 60 dakika model kullanım çubuğu. İz: T7 (periyodik+kullanım) |
| `model_usage.py::summary` | işlev:154 | kapsam dışı | yok | yok | son 60 dakika model kullanım çubuğu. İz: T7 (periyodik+kullanım) |

### `py/claudeops/orphan_watch.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `orphan_watch.py::MIN_AGE_S` | sabit:19 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::SOCKET_PREFIXES` | sabit:20 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::KILLABLE_PREFIXES` | sabit:21 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::CLI_NAMES` | sabit:22 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::_sock_dir` | işlev:25 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::_pid_alive` | işlev:29 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::_server_alive` | işlev:39 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::scan_sockets` | işlev:47 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::scan_sockets::re1` | regex:73 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::_pane_pids` | işlev:90 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::_is_app_server` | işlev:100 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::_own` | işlev:104 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::_attr` | işlev:114 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::_ancestor_cmd` | işlev:119 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::scan_procs` | işlev:131 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::check` | işlev:181 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::HOG_PCT` | sabit:195 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::HOG_MIN_SPAN_S` | sabit:196 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |
| `orphan_watch.py::scan_cpu_hogs` | işlev:199 | kapsam dışı | yok | yok | sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur (kanıt `fake_proc.rs::other_users_processes_are_never_read`). İz: T7 (periyodik+kullanım) |

### `py/claudeops/paths.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `paths.py::HOME` | sabit:6 | karşılandı | `lib.rs::Config.claude_dir`<br>`lib.rs::Config::from_env` | `run.py:scan_sessions` | `HOME` yoksa Rust `None` (Python parola veritabanına düşer) |
| `paths.py::CLAUDE_DIR` | sabit:7 | karşılandı | `lib.rs::Config.claude_dir`<br>`lib.rs::Config::from_env` | `run.py:scan_sessions` | `HOME` yoksa Rust `None` (Python parola veritabanına düşer) |
| `paths.py::_test_code_loaded` | işlev:10 | kapsam dışı | yok | yok | durum dizini çözümü, test yalıtımı ve durum dosyaları. İz: W0-a durum (rs/state) |
| `paths.py::_under_test_runner` | işlev:25 | kapsam dışı | yok | yok | durum dizini çözümü, test yalıtımı ve durum dosyaları. İz: W0-a durum (rs/state) |
| `paths.py::CLAUDEOPS_DIR` | sabit:46 | karşılandı | `lib.rs::Config::from_env` | `run.py:scan_agy_learned` | yalnız canlı parite `CLAUDEOPS_DIR` ile koşar; test yalıtımı kuralı `_under_test_runner` satırında |
| `paths.py::STATE_DIR` | sabit:52 | karşılandı | `needs_ho.rs::NeedsHo.state_dir`<br>`needs_ho.rs::NeedsHo::new` | `tests/needs_ho_git.rs::git_signals_and_baseline`<br>`run.py:needs_ho_repos` | dizini çağıran verir |
| `paths.py::_LateTestImportGuard` | sınıf:55 | kapsam dışı | yok | yok | durum dizini çözümü, test yalıtımı ve durum dosyaları. İz: W0-a durum (rs/state) |
| `paths.py::_LateTestImportGuard.__init__` | işlev:61 | kapsam dışı | yok | yok | durum dizini çözümü, test yalıtımı ve durum dosyaları. İz: W0-a durum (rs/state) |
| `paths.py::_LateTestImportGuard.find_spec` | işlev:64 | kapsam dışı | yok | yok | durum dizini çözümü, test yalıtımı ve durum dosyaları. İz: W0-a durum (rs/state) |
| `paths.py::_install_late_test_guard` | işlev:77 | kapsam dışı | yok | yok | durum dizini çözümü, test yalıtımı ve durum dosyaları. İz: W0-a durum (rs/state) |
| `paths.py::REPO_DIR` | sabit:93 | kapsam dışı | yok | yok | açılış/koruma yolu sabitleri. İz: T4 (yaşam döngüsü) |
| `paths.py::ROSTER_TSV` | sabit:95 | kapsam dışı | yok | yok | durum dizini çözümü, test yalıtımı ve durum dosyaları. İz: W0-a durum (rs/state) |
| `paths.py::MODELS_TSV` | sabit:96 | kapsam dışı | yok | yok | durum dizini çözümü, test yalıtımı ve durum dosyaları. İz: W0-a durum (rs/state) |
| `paths.py::CLAUDE_MODELS_JSON` | sabit:97 | kapsam dışı | yok | yok | durum dizini çözümü, test yalıtımı ve durum dosyaları. İz: W0-a durum (rs/state) |
| `paths.py::SESSIONS_DIR` | sabit:99 | karşılandı | `discovery.rs::sessions_from_json` | `tests/fake_proc.rs::json_source_merges_with_proc_scan` | yok |
| `paths.py::PROJECTS_DIR` | sabit:100 | karşılandı | `transcript.rs::jsonl_path_for` | `tests/fake_proc.rs::transcript_requires_exact_sid` | yok |
| `paths.py::CONFIG_JSON` | sabit:101 | kapsam dışı | yok | yok | açılış/koruma yolu sabitleri. İz: T4 (yaşam döngüsü) |
| `paths.py::parse_proc_stat` | işlev:103 | karşılandı | `procfs.rs::parse_stat` | `procfs.rs::stat_with_parens_in_comm` | dört alan döner; `)` yoksa istisna yerine `None` |
| `paths.py::proc_stat_fields` | işlev:109 | karşılandı | `procfs.rs::OwnProc::try_stat`<br>`procfs.rs::OwnProc::stat` | `tests/fake_proc.rs::broken_proc_fields` | yalnız kendi kullanıcımızın süreci |
| `paths.py::proc_ppid` | işlev:115 | karşılandı | `procfs.rs::Stat.ppid` | `tests/fake_proc.rs::own_ppid_from_real_proc` | yok |
| `paths.py::ucli_key_file` | işlev:119 | kapsam dışı | yok | yok | ucli anahtar dosyası yolu. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `paths.py::shared_write_allowed` | işlev:126 | kapsam dışı | yok | yok | ikinci örnekte ortak anahtar/kullanım yazma yasağı (TBD#412). İz: W1-pre sağlayıcı (rs/prov); canlıya T4; W0-a durum (rs/state) |
| `paths.py::GUARD_LOCK` | sabit:140 | kapsam dışı | yok | yok | açılış/koruma yolu sabitleri. İz: T4 (yaşam döngüsü) |
| `paths.py::ensure_private_state_dir` | işlev:143 | kapsam dışı | yok | yok | durum dizini çözümü, test yalıtımı ve durum dosyaları. İz: W0-a durum (rs/state) |
| `paths.py::trusted_path_env` | işlev:158 | kapsam dışı | yok | yok | süreç girişinde güvenilmeyen PATH girdisi süzgeci (P2-2, TBD#450); Rust eşi `cops_state::paths` (copsd, cops-cli girişi), test `paths.rs::trusted_path_env_drops_untrusted`. İz: W0-a durum (rs/state) |
| `paths.py::secure_path_environ` | işlev:177 | kapsam dışı | yok | yok | süreç girişinde güvenilmeyen PATH girdisi süzgeci (P2-2, TBD#450); Rust eşi `cops_state::paths` (copsd, cops-cli girişi), test `paths.rs::trusted_path_env_drops_untrusted`. İz: W0-a durum (rs/state) |

### `py/claudeops/commands/web.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `commands/web.py::_find_gnome_terminal_server` | işlev:1135 | kapsam dışı | yok | yok | gnome-terminal sunucusu araması; uid denetimi cmdline'dan ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı yok (crate'te gnome-terminal araması yok; tüm süreç içeriği `OwnProc` kapısından). İz: T1 (durum) |
| `commands/web.py::_diag_status` | işlev:1151 | kapsam dışı | yok | yok | Tanılama yükü; `skipped` sözlüğü discovery/needs_ho/session_usage sayaçlarını toplar (Python düzeltildi: 1af088ef); Rust karşılıkları `ScanDiag`, `Usage.skipped_rows`, `Checked.skipped` (JSON'da). İz: T1 (durum) |
| `commands/web.py::_usage_total` | işlev:1642 | karşılandı | `status.rs::Probe::usage_total` | `tests/fake_proc.rs::probe_usage_total_claude_exact_sid_without_blocking` | sapma 1; durum yükü bağlantısı T1 |
| `commands/web.py::_process_started_at` | işlev:1694 | karşılandı | `status.rs::Probe::started_at` | `tests/fake_proc.rs::tmux_terminal_and_orphans` | yalnız kendi kullanıcımızın süreci |
| `commands/web.py::_UCLI_FLAGS_CACHE` | sabit:1701 | kapsam dışı | yok | yok | pid başına önbellek (sapma 9). İz: T1 (durum) |
| `commands/web.py::_ucli_flags` | işlev:1704 | karşılandı | `status.rs::Probe::ucli_flags`<br>`status.rs::UcliFlags` | `tests/fake_proc.rs::ucli_flags`<br>`tests/fake_proc.rs::ucli_flags_all_set`<br>`tests/fake_proc.rs::ucli_flags_lost_process_is_none_and_not_cached`<br>`tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges`<br>`run.py:scan_sessions` | `tools` ve önbellek T1 |
| `commands/web.py::_with_ucli_tools` | işlev:1733 | kapsam dışı | yok | yok | rozete durum dosyasından araç listesi ekler. İz: T1 (durum) |

### `py/claudeops/tmux_backend.py`

| Python | Tür:satır | Durum | Rust | Parite testi | Not / gerekçe ve iz |
|---|---|---|---|---|---|
| `tmux_backend.py::TMUX_SOCKET` | sabit:25 | karşılandı | `status.rs::TMUX_SOCKET` | `tests/fake_proc.rs::tmux_terminal_and_orphans`<br>`run.py:scan_sessions` | yok |
| `tmux_backend.py::_ANCESTOR_WALK_LIMIT` | sabit:27 | karşılandı | `status.rs::ANCESTOR_WALK_LIMIT` | `tests/fake_proc.rs::tmux_terminal_and_orphans` | 6 adım sınırının ucu sınanmıyor |
| `tmux_backend.py::is_tmux_backed` | işlev:916 | karşılandı | `status.rs::Probe::is_tmux_backed` | `tests/fake_proc.rs::tmux_terminal_and_orphans`<br>`tests/fake_proc.rs::other_users_processes_are_never_read`<br>`run.py:scan_sessions` | başka kullanıcının atasında durur, içeriğini okumaz. Python düzeltildi: 6ae5da3 |

## Python test durumları

### `py/tests/test_agy_binary_resolution.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_agy_binary_resolution.py::AgyBinaryTest.test_inner_command_quotes_a_path_with_spaces` | 14 | kapsam dışı | yok | agy ikili yolu ve alıntılama. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_agy_binary_resolution.py::AgyBinaryTest.test_model_choices_uses_the_resolved_binary` | 19 | kapsam dışı | yok | agy ikili yolu ve alıntılama. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_agy_compaction_view.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_agy_compaction_view.py::AgyCompactionViewTests.test_checkpoint_becomes_boundary_and_plain_type23_is_ignored` | 21 | kapsam dışı | yok | sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |

### `py/tests/test_agy_last_exchange.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_agy_last_exchange.py::AgyLastExchange.test_last_pair_skips_empty_assistant_steps` | 33 | kapsam dışı | yok | sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_agy_last_exchange.py::AgyLastExchange.test_empty_conversation_and_no_assistant` | 37 | kapsam dışı | yok | sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_agy_last_exchange.py::AgyLastExchange.test_checkpoint_between_does_not_break_pairing` | 41 | kapsam dışı | yok | sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_agy_last_exchange.py::AgyLastExchange.test_missing_db_is_empty` | 45 | kapsam dışı | yok | sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |

### `py/tests/test_agy_models_swr.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_agy_models_swr.py::AgyModelsSwr.test_cold_blocks_then_stale_returns_old_immediately_and_refreshes_in_background` | 19 | kapsam dışı | yok | agy model listesi önbelleği. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_agy_sids_store.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_agy_sids_store.py::AgySidsStoreTest.test_db_ready` | 31 | kapsam dışı | yok | kilitli DB+ayna yazımı. İz: W0-a durum (rs/state); T1 (durum) |
| `test_agy_sids_store.py::AgySidsStoreTest.test_remember_writes_db_and_mirror` | 34 | kapsam dışı | yok | kilitli DB+ayna yazımı. İz: W0-a durum (rs/state); T1 (durum) |
| `test_agy_sids_store.py::AgySidsStoreTest.test_unchanged_value_does_not_rewrite` | 42 | karşılandı | `providers.rs::agy_sid_rules` | yalnız 'yeni kayıt yok' kararı; yazım W0-a durum (rs/state) |
| `test_agy_sids_store.py::AgySidsStoreTest.test_concurrent_remembers_lose_nothing` | 48 | kapsam dışı | yok | kilitli DB+ayna yazımı. İz: W0-a durum (rs/state); T1 (durum) |

### `py/tests/test_bg_work.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_bg_work.py::ScreenFixture.test_busy_screens` | 39 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::ScreenFixture.test_idle_screen_with_prose_numbers` | 43 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::TranscriptFixture.test_pending_without_notification` | 69 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::TranscriptFixture.test_completed_by_tool_use_id_or_task_id` | 72 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::TranscriptFixture.test_foreground_and_stale` | 77 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::TranscriptFixture.test_errored_call_is_not_pending` | 81 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::TranscriptFixture.test_one_of_two_pending` | 87 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::StoppedAndMidTurnNotifications.test_stopped_task_is_not_pending` | 105 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::StoppedAndMidTurnNotifications.test_failed_stop_or_other_task_stays_pending` | 110 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::StoppedAndMidTurnNotifications.test_notification_delivered_mid_turn` | 115 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::StoppedAndMidTurnNotifications.test_quoted_notification_in_queued_user_text_does_not_count` | 121 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::NavigationHintAndRequestCopies.test_agent_view_hint_is_not_background_work` | 134 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::NavigationHintAndRequestCopies.test_real_counts_beside_the_hint_still_count` | 138 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::NavigationHintAndRequestCopies.test_request_copy_does_not_revive_refused_call` | 151 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::NavigationHintAndRequestCopies.test_request_copy_alone_is_not_a_job` | 156 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::NavigationHintAndRequestCopies.test_typed_assistant_record_is_still_pending_and_expires` | 159 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::SessionRecordSignal.test_live_footers` | 199 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::SessionRecordSignal.test_record_of_dead_reused_or_other_session_is_ignored` | 205 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::SessionRecordSignal.test_idle_record_overrides_transcript_history` | 224 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::SessionRecordSignal.test_idle_record_does_not_hide_the_screen_counter` | 228 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::SessionRecordSignal.test_transcript_still_used_when_record_cannot_decide` | 232 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::SessionRecordSignal.test_any_active_record_of_the_conversation_wins_over_idle` | 241 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::SessionRecordSignal.test_broken_record_and_missing_dir` | 251 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::SubagentActiveForUsesBoth.test_screen_makes_active_even_without_subagent_files` | 262 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::SubagentActiveForUsesBoth.test_transcript_pending_makes_active` | 268 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::ProviderBackgroundWork.test_base_unknown_and_claude_counts` | 283 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::UcliBackgroundWork.test_reads_status_field_never_guesses` | 296 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::CodexBackgroundWork.test_screen_and_rollout` | 320 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |
| `test_bg_work.py::CodexBackgroundWork.test_provider_sums_screen_and_missing_rollout` | 327 | kapsam dışı | yok | arka plan işi tespiti (ekran + transkript). İz: T2 (terminal); T1 (durum) |

### `py/tests/test_brain_permission_ucli.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_brain_permission_ucli.py::BrainPermission.test_default_allow_edit_is_a_valid_ucli_mode` | 11 | kapsam dışı | yok | değnekçi beyninin ucli izinleri. İz: T10 (değnekçi); W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_brain_permission_ucli.py::BrainPermission.test_applied_only_for_ucli` | 15 | kapsam dışı | yok | değnekçi beyninin ucli izinleri. İz: T10 (değnekçi); W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_cache_info.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_cache_info.py::CacheInfoTests.test_a_recent_request_gives_its_age_and_the_one_hour_ttl` | 68 | kapsam dışı | yok | `cache` satır alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_a_cli_without_a_cache_lifetime_has_no_info_and_is_never_probed` | 73 | kapsam dışı | yok | `cache` satır alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_no_matching_transcript_is_unknown_not_cold` | 78 | kapsam dışı | yok | `cache` satır alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_an_expired_cache_still_reports_so_the_ui_can_show_cold` | 81 | kapsam dışı | yok | `cache` satır alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_the_probe_is_cached_but_the_age_keeps_advancing` | 84 | kapsam dışı | yok | `cache` satır alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_the_probe_is_repeated_after_the_ttl_and_sees_a_new_request` | 91 | kapsam dışı | yok | `cache` satır alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_a_failing_provider_is_unknown_never_an_error_and_is_not_hammered` | 99 | kapsam dışı | yok | `cache` satır alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_a_clock_skew_never_gives_a_negative_age` | 105 | kapsam dışı | yok | `cache` satır alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_a_restarted_session_with_a_new_pid_is_probed_afresh` | 108 | kapsam dışı | yok | `cache` satır alanı. İz: T1 (durum) |
| `test_cache_info.py::CacheInfoTests.test_retired_sessions_do_not_pile_up_in_the_cache` | 114 | kapsam dışı | yok | `cache` satır alanı. İz: T1 (durum) |
| `test_cache_info.py::StatusPayloadCacheTests.test_both_running_row_builders_carry_the_cache_info` | 146 | kapsam dışı | yok | `cache` satır alanı. İz: T1 (durum) |
| `test_cache_info.py::StatusPayloadCacheTests.test_a_stopped_row_has_none` | 151 | kapsam dışı | yok | `cache` satır alanı. İz: T1 (durum) |

### `py/tests/test_chat_backup_instance_dirs.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_chat_backup_instance_dirs.py::InstanceDirsTest.test_second_instance_files_are_backed_up_apart_from_shared_ones` | 57 | kapsam dışı | yok | ikinci örnek günlük ve durum dizinleri sohbet yedeğinde (TBD#412). İz: T7 (periyodik+kullanım) |
| `test_chat_backup_instance_dirs.py::InstanceDirsTest.test_default_instance_backs_up_shared_state_once` | 74 | kapsam dışı | yok | ikinci örnek günlük ve durum dizinleri sohbet yedeğinde (TBD#412). İz: T7 (periyodik+kullanım) |
| `test_chat_backup_instance_dirs.py::InstanceDirsTest.test_deleted_state_chat_comes_from_the_mirror` | 84 | kapsam dışı | yok | ikinci örnek günlük ve durum dizinleri sohbet yedeğinde (TBD#412). İz: T7 (periyodik+kullanım) |
| `test_chat_backup_instance_dirs.py::InstanceDirsTest.test_linked_state_child_is_not_followed` | 89 | kapsam dışı | yok | ikinci örnek günlük ve durum dizinleri sohbet yedeğinde (TBD#412). İz: T7 (periyodik+kullanım) |
| `test_chat_backup_instance_dirs.py::InstanceDirsTest.test_mirror_script_copies_shared_state_dir` | 96 | kapsam dışı | yok | ikinci örnek günlük ve durum dizinleri sohbet yedeğinde (TBD#412). İz: T7 (periyodik+kullanım) |
| `test_chat_backup_instance_dirs.py::InstanceDirsTest.test_second_instance_does_not_write_shared_mirror_script_or_unit` | 102 | kapsam dışı | yok | ikinci örnek günlük ve durum dizinleri sohbet yedeğinde (TBD#412). İz: T7 (periyodik+kullanım) |

### `py/tests/test_chat_compaction_view.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_chat_compaction_view.py::CompactionViewTests.test_boundary_and_summary_roles_keep_pre_compaction_messages` | 21 | kapsam dışı | yok | sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_chat_compaction_view.py::CompactionViewTests.test_no_boundary_unchanged` | 34 | kapsam dışı | yok | sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_chat_compaction_view.py::CompactionViewTests.test_sidechain_summary_ignored` | 38 | kapsam dışı | yok | sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |

### `py/tests/test_check_cmd.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_check_cmd.py::CheckTest.test_compile_detects_syntax_error` | 11 | kapsam dışı | yok | `cops check` komutu. İz: T6 (CLI) |
| `test_check_cmd.py::CheckTest.test_real_tree_compiles_and_imports` | 19 | kapsam dışı | yok | `cops check` komutu. İz: T6 (CLI) |
| `test_check_cmd.py::CheckTest.test_gate_missing_binary_warns` | 35 | kapsam dışı | yok | `cops check` komutu. İz: T6 (CLI) |
| `test_check_cmd.py::CheckTest.test_gate_clean_is_silent_and_gets_core_arg` | 38 | kapsam dışı | yok | `cops check` komutu. İz: T6 (CLI) |
| `test_check_cmd.py::CheckTest.test_gate_failure_lines_become_warnings` | 41 | kapsam dışı | yok | `cops check` komutu. İz: T6 (CLI) |

### `py/tests/test_claude_models_store.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_claude_models_store.py::ClaudeModelsStoreTest.test_is_db_ready` | 32 | kapsam dışı | yok | model listesi belgesi. İz: W0-a durum (rs/state); W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_claude_models_store.py::ClaudeModelsStoreTest.test_write_goes_to_db_and_mirror_and_reads_from_db` | 35 | kapsam dışı | yok | model listesi belgesi. İz: W0-a durum (rs/state); W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_claude_models_store.py::ClaudeModelsStoreTest.test_db_wins_over_corrupt_or_missing_file` | 42 | kapsam dışı | yok | model listesi belgesi. İz: W0-a durum (rs/state); W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_claude_models_store.py::ClaudeModelsStoreTest.test_fallback_to_hardcoded_when_empty` | 50 | kapsam dışı | yok | model listesi belgesi. İz: W0-a durum (rs/state); W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_close_base_name.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_close_base_name.py::BaseName.test_single_source` | 12 | kapsam dışı | yok | Python modülleri arası aynı regex nesnesi denetimi. İz: T4 (yaşam döngüsü) |
| `test_close_base_name.py::BaseName.test_date_and_conflict_suffixes_reduce` | 16 | karşılandı | `session.rs::base_matches_python_regex`<br>`golden.rs::names_paths_and_token_format` | `close` komutunun kendisi T4 |
| `test_close_base_name.py::TsvFinder.test_find_and_edit` | 28 | kapsam dışı | yok | roster/models dosyası düzenleme. İz: W0-a durum (rs/state); T4 (yaşam döngüsü) |

### `py/tests/test_context_mask_unknown.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_context_mask_unknown.py::ContextMaskGuardTests.test_unknown_mask_state_sends_nothing_and_says_why` | 32 | kapsam dışı | yok | `/context` maske denetimi (TBD#367). İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `test_context_mask_unknown.py::ContextMaskGuardTests.test_masked_still_refused` | 37 | kapsam dışı | yok | `/context` maske denetimi (TBD#367). İz: T2 (terminal); W0-b tmux (rs/tmux) |
| `test_context_mask_unknown.py::ContextMaskGuardTests.test_known_unmasked_pane_gets_the_command` | 42 | kapsam dışı | yok | `/context` maske denetimi (TBD#367). İz: T2 (terminal); W0-b tmux (rs/tmux) |

### `py/tests/test_copilot_trust.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_copilot_trust.py::TrustFolder.test_adds_and_keeps_comments` | 14 | kapsam dışı | yok | klasöre güven kaydı. İz: T4 (yaşam döngüsü) |
| `test_copilot_trust.py::TrustFolder.test_empty_list` | 21 | kapsam dışı | yok | klasöre güven kaydı. İz: T4 (yaşam döngüsü) |
| `test_copilot_trust.py::TrustFolder.test_comment_only_list_gets_no_trailing_comma` | 26 | kapsam dışı | yok | klasöre güven kaydı. İz: T4 (yaşam döngüsü) |
| `test_copilot_trust.py::TrustFolder.test_slashes_inside_a_string_are_not_a_comment` | 33 | kapsam dışı | yok | klasöre güven kaydı. İz: T4 (yaşam döngüsü) |
| `test_copilot_trust.py::TrustFolder.test_keeps_private_mode` | 38 | kapsam dışı | yok | klasöre güven kaydı. İz: T4 (yaşam döngüsü) |
| `test_copilot_trust.py::TrustFolder.test_idempotent_and_missing` | 46 | kapsam dışı | yok | klasöre güven kaydı. İz: T4 (yaşam döngüsü) |

### `py/tests/test_cpu_hogs.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_cpu_hogs.py::Hogs.test_hog_detected_after_window` | 21 | kapsam dışı | yok | CPU yakan süreç uyarısı. İz: T7 (periyodik+kullanım) |
| `test_cpu_hogs.py::Hogs.test_short_window_keeps_old_sample_and_no_alarm` | 28 | kapsam dışı | yok | CPU yakan süreç uyarısı. İz: T7 (periyodik+kullanım) |
| `test_cpu_hogs.py::Hogs.test_pid_reuse_not_counted` | 34 | kapsam dışı | yok | CPU yakan süreç uyarısı. İz: T7 (periyodik+kullanım) |

### `py/tests/test_diag_log_isolation.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_diag_log_isolation.py::DiagLogIsolation.test_diag_log_path_is_not_the_real_one` | 31 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_diag_log_isolation.py::DiagLogIsolation.test_real_diag_log_hash_unchanged` | 36 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |

### `py/tests/test_directive_delivery.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_directive_delivery.py::SendVerified.test_delivered_when_message_appears` | 51 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::SendVerified.test_old_identical_header_does_not_fake_delivery` | 56 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::SendVerified.test_pasted_text_in_box_gets_enter` | 61 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::SendVerified.test_pasted_text_ignoring_enter_gets_space_then_enter` | 66 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::SendVerified.test_permanently_stuck_paste_fails_without_resend` | 82 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::SendVerified.test_text_unsent_in_input_box_is_not_delivered` | 95 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::SendVerified.test_text_stuck_in_input_box_forever_fails_without_resend` | 108 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::SendVerified.test_placeholder_text_in_transcript_does_not_trigger_enter` | 117 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::SendVerified.test_pasted_placeholder_in_input_box_gets_enter` | 123 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::SendVerified.test_grey_suggestion_in_box_is_not_unsent_text` | 134 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::SendVerified.test_colored_typed_text_in_box_counts_as_unsent` | 142 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::SendVerified.test_resend_when_nothing_arrived` | 148 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::SendVerified.test_ucli_unverified_skip` | 158 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::Queue.test_start_path_returns_queued_immediately_then_delivered` | 199 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::Queue.test_failure_is_visible_with_reason_and_notifies` | 206 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::Queue.test_brain_actor_stays_synchronous` | 212 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::HoDoneFresh.test_ho_done_live_session_stopped_exact_and_started_fresh` | 219 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::ClosedHoDoneAndPersistence.test_closed_ho_done_conversation_starts_fresh` | 267 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |
| `test_directive_delivery.py::ClosedHoDoneAndPersistence.test_deliveries_survive_restart_and_queued_becomes_failed` | 286 | kapsam dışı | yok | direktif teslimi. İz: T10 (değnekçi) |

### `py/tests/test_discovery_bg_fold.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_discovery_bg_fold.py::FoldTests.test_bg_folds_into_front_and_front_reads_bg_sid` | 29 | karşılandı | `session.rs::background_folds_into_single_front` | yok |
| `test_discovery_bg_fold.py::FoldTests.test_order_independent` | 37 | karşılandı | `session.rs::background_fold_edge_cases_like_python` | yok |
| `test_discovery_bg_fold.py::FoldTests.test_orphan_bg_is_kept` | 41 | karşılandı | `session.rs::background_fold_edge_cases_like_python` | yok |
| `test_discovery_bg_fold.py::FoldTests.test_other_name_not_folded` | 45 | karşılandı | `session.rs::background_fold_edge_cases_like_python` | yok |
| `test_discovery_bg_fold.py::FoldTests.test_fallback_single_front_same_cwd_without_parked_id` | 49 | karşılandı | `session.rs::background_folds_into_single_front` | yok |
| `test_discovery_bg_fold.py::FoldTests.test_two_fronts_without_link_is_ambiguous_bg_kept` | 53 | karşılandı | `session.rs::background_folds_into_single_front` | yok |
| `test_discovery_bg_fold.py::FoldTests.test_parked_id_picks_the_right_front` | 57 | karşılandı | `session.rs::background_folds_into_single_front` | yok |
| `test_discovery_bg_fold.py::FoldTests.test_second_bg_stays_visible` | 64 | karşılandı | `session.rs::background_fold_edge_cases_like_python` | yok |
| `test_discovery_bg_fold.py::FoldTests.test_non_bg_sessions_untouched` | 69 | karşılandı | `session.rs::background_fold_edge_cases_like_python` | yok |
| `test_discovery_bg_fold.py::KillBgTests.test_stop_kills_folded_bg_after_front` | 84 | kapsam dışı | yok | durdurma (kill) yolu. İz: T4 (yaşam döngüsü) |
| `test_discovery_bg_fold.py::KillBgTests.test_stop_without_bg_kills_only_front` | 90 | kapsam dışı | yok | durdurma (kill) yolu. İz: T4 (yaşam döngüsü) |

### `py/tests/test_discovery_sid.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_discovery_sid.py::FindSessionsSidTests.test_a_fresh_session_gets_the_live_sid_from_the_json_entry` | 80 | karşılandı | `tests/fake_proc.rs::json_source_merges_with_proc_scan` | yok |
| `test_discovery_sid.py::FindSessionsSidTests.test_a_resumed_session_keeps_its_sid_and_stays_resumed` | 88 | karşılandı | `tests/fake_proc.rs::json_sid_merge_rules_like_python`<br>`tests/fake_proc.rs::discovers_each_cli_and_names` | yok |
| `test_discovery_sid.py::FindSessionsSidTests.test_the_live_json_sid_wins_over_a_stale_cmdline_sid` | 95 | karşılandı | `tests/fake_proc.rs::json_sid_merge_rules_like_python` | yok |
| `test_discovery_sid.py::FindSessionsSidTests.test_without_a_json_entry_the_cmdline_value_is_used_exactly_as_before` | 104 | karşılandı | `tests/fake_proc.rs::is_fresh_without_json_entry_for_every_cli` | yok |
| `test_discovery_sid.py::FindSessionsSidTests.test_a_json_entry_without_a_sid_never_blanks_the_cmdline_sid` | 109 | karşılandı | `tests/fake_proc.rs::json_sid_merge_rules_like_python` | yok |
| `test_discovery_sid.py::FindSessionsSidTests.test_a_tui_renamed_session_is_listed_once_under_its_spawn_name` | 113 | karşılandı | `tests/fake_proc.rs::json_source_merges_with_proc_scan` | yok |
| `test_discovery_sid.py::FindSessionsSidTests.test_each_session_gets_its_own_sid_by_pid` | 119 | karşılandı | `tests/fake_proc.rs::json_sid_merge_rules_like_python` | yok |
| `test_discovery_sid.py::FindSessionsSidTests.test_a_json_entry_of_another_cli_never_donates_its_sid` | 124 | karşılandı | `tests/fake_proc.rs::json_sid_merge_rules_like_python` | yok |
| `test_discovery_sid.py::FindSessionsSidTests.test_a_non_claude_cli_keeps_its_cmdline_sid_and_its_old_is_fresh` | 132 | karşılandı | `tests/fake_proc.rs::is_fresh_without_json_entry_for_every_cli` | sahte sağlayıcı yerine ucli ve codex |
| `test_discovery_sid.py::IsFreshTests.test_flag_unknown_falls_back_to_the_sid` | 141 | karşılandı | `session.rs::is_fresh_flag_and_sid_combinations` | yok |
| `test_discovery_sid.py::IsFreshTests.test_flag_known_wins_over_the_sid` | 146 | karşılandı | `session.rs::is_fresh_flag_and_sid_combinations` | yok |

### `py/tests/test_discovery_subshell.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_discovery_subshell.py::FoldSubshellTests.test_descendants_drop_independent_and_other_cli_stay` | 22 | karşılandı | `session.rs::subshell_tree_like_python` | yok |
| `test_discovery_subshell.py::RealSubshellTests.test_background_subshell_is_one_session` | 32 | karşılandı | `tests/real_proc.rs::real_background_subshell_is_one_session` | yok |

### `py/tests/test_effort_by_model.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_effort_by_model.py::SplitTierTests.test_tiered_ids` | 56 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SplitTierTests.test_untiered_ids_are_untouched` | 62 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SplitTierTests.test_non_string` | 66 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SortAndNearestTests.test_sort_levels_orders_dedupes_keeps_unknown_last` | 71 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SortAndNearestTests.test_requested_in_levels_is_returned_as_is` | 75 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SortAndNearestTests.test_too_high_goes_to_the_top_supported` | 78 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SortAndNearestTests.test_prefers_below_over_equally_near_above` | 81 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SortAndNearestTests.test_nothing_below_takes_lowest_above` | 85 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SortAndNearestTests.test_empty_request_uses_default` | 88 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SortAndNearestTests.test_unknown_request_falls_back_via_default_rank` | 92 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SortAndNearestTests.test_empty_levels` | 95 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SortAndNearestTests.test_all_unknown_level_names` | 98 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::AgyEffortTests.test_tier_in_id_fixes_the_levels` | 103 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::AgyEffortTests.test_untiered_non_gemini_has_no_info` | 109 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::AgyEffortTests.test_base_name_uses_live_siblings` | 114 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::AgyEffortTests.test_base_name_without_siblings_is_unknown` | 118 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::AgyEffortTests.test_empty_model` | 122 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::AgyEffortTests.test_panel_default_max_no_longer_conflicts_with_tiered_id` | 127 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::AgyEffortTests.test_empty_effort_no_longer_defaults_to_medium_against_a_high_id` | 134 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::AgyEffortTests.test_requested_effort_follows_the_id_not_the_other_way` | 140 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::AgyEffortTests.test_matching_effort_is_unchanged` | 145 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::AgyEffortTests.test_non_gemini_still_gets_no_effort_flag` | 151 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::AgyEffortTests.test_argon_ids_are_consistent_with_their_tier` | 159 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::AgyEffortTests.test_gemini_base_name_clamps_to_live_tiers` | 166 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::AgyEffortTests.test_gemini_base_name_without_info_keeps_old_behaviour` | 171 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::CodexEffortTests.test_reads_per_model_levels` | 195 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::CodexEffortTests.test_unknown_model_or_empty_list_is_no_info` | 199 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::CodexEffortTests.test_missing_or_corrupt_cache_is_no_info` | 204 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::CodexEffortTests.test_unsupported_effort_is_clamped_supported_is_untouched` | 211 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::CodexEffortTests.test_model_missing_from_cache_passes_through` | 216 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::OtherProvidersPassThroughTests.test_fleet_values_pass_through_unchanged` | 237 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::OtherProvidersPassThroughTests.test_unknown_values_are_not_rewritten_either` | 244 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::OtherProvidersPassThroughTests.test_only_agy_and_codex_override_model_levels` | 249 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SpawnWiringTests.test_adjusted_effort_reaches_the_command_and_is_logged` | 268 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SpawnWiringTests.test_unchanged_effort_is_not_logged` | 275 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_effort_by_model.py::SpawnWiringTests.test_resolver_failure_never_blocks_the_spawn` | 280 | kapsam dışı | yok | model bazlı effort kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_extensions_mcp.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_extensions_mcp.py::McpHook.test_validation` | 22 | kapsam dışı | yok | eklenti MCP kaydı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T9 (enterprise) |
| `test_extensions_mcp.py::McpHook.test_stdio_roundtrip` | 34 | kapsam dışı | yok | eklenti MCP kaydı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T9 (enterprise) |
| `test_extensions_mcp.py::McpHook.test_unknown_server_exit_2` | 51 | kapsam dışı | yok | eklenti MCP kaydı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T9 (enterprise) |
| `test_extensions_mcp.py::SessionAttach.test_attach_predicate_and_spec` | 68 | kapsam dışı | yok | eklenti MCP kaydı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T9 (enterprise) |
| `test_extensions_mcp.py::SessionAttach.test_claude_config_path_per_ext_and_spawn_wiring` | 82 | kapsam dışı | yok | eklenti MCP kaydı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T9 (enterprise) |
| `test_extensions_mcp.py::SessionAttach.test_spawn_attaches_only_matching_cwd_and_claude` | 89 | kapsam dışı | yok | eklenti MCP kaydı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T9 (enterprise) |

### `py/tests/test_files_resolve_exact_first.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_files_resolve_exact_first.py::FilesResolveTests.test_exact_wins_over_base_siblings` | 23 | kapsam dışı | yok | dosya uçlarında oturum adı çözümü. İz: T3 (dosya) |
| `test_files_resolve_exact_first.py::FilesResolveTests.test_single_base_fallback` | 30 | kapsam dışı | yok | dosya uçlarında oturum adı çözümü. İz: T3 (dosya) |
| `test_files_resolve_exact_first.py::FilesResolveTests.test_two_base_candidates_is_ambiguous` | 36 | kapsam dışı | yok | dosya uçlarında oturum adı çözümü. İz: T3 (dosya) |
| `test_files_resolve_exact_first.py::FilesResolveTests.test_unknown_is_not_running` | 44 | kapsam dışı | yok | dosya uçlarında oturum adı çözümü. İz: T3 (dosya) |
| `test_files_resolve_exact_first.py::FilesResolveTests.test_mutation_wrappers_return_409_when_ambiguous` | 50 | kapsam dışı | yok | dosya uçlarında oturum adı çözümü. İz: T3 (dosya) |

### `py/tests/test_guard_lock_safety.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_guard_lock_safety.py::GuardLockSafetyTest.test_default_lock_path_is_per_user` | 20 | kapsam dışı | yok | guard kilidi. İz: T4 (yaşam döngüsü) |
| `test_guard_lock_safety.py::GuardLockSafetyTest.test_normal_lock_and_reentry_timeout` | 24 | kapsam dışı | yok | guard kilidi. İz: T4 (yaşam döngüsü) |
| `test_guard_lock_safety.py::GuardLockSafetyTest.test_symlink_lock_not_truncated` | 31 | kapsam dışı | yok | guard kilidi. İz: T4 (yaşam döngüsü) |
| `test_guard_lock_safety.py::GuardLockSafetyTest.test_symlinked_or_foreign_dir_refused` | 41 | kapsam dışı | yok | guard kilidi. İz: T4 (yaşam döngüsü) |

### `py/tests/test_handover_cache_policy.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_handover_cache_policy.py::LastRealRequestEpochTests.test_returns_the_time_of_the_latest_real_request` | 76 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::LastRealRequestEpochTests.test_synthetic_placeholder_after_a_real_request_does_not_refresh_the_cache` | 80 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::LastRealRequestEpochTests.test_subagent_rows_are_a_separate_context_and_do_not_count` | 86 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::LastRealRequestEpochTests.test_rows_without_any_usage_tokens_do_not_count` | 90 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::LastRealRequestEpochTests.test_user_rows_are_ignored_and_no_assistant_means_unknown` | 96 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::LastRealRequestEpochTests.test_missing_file_is_unknown` | 100 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::LastRealRequestEpochTests.test_large_file_is_read_from_the_tail` | 103 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ClaudeProviderCacheHookTests.test_ttl_is_one_hour` | 110 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ClaudeProviderCacheHookTests.test_last_request_epoch_reads_only_the_exact_sid_file` | 113 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ClaudeProviderCacheHookTests.test_no_sid_or_no_matching_file_is_unknown_never_the_newest_sibling` | 123 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ClaudeProviderCacheHookTests.test_effort_switch_keeps_cache_by_model` | 135 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ClaudeProviderCacheHookTests.test_other_providers_keep_the_old_behaviour` | 148 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::SessionFileSidTests.test_verified_file_gives_the_session_id` | 177 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::SessionFileSidTests.test_a_reused_pid_is_rejected_by_proc_start` | 182 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::SessionFileSidTests.test_unverifiable_or_inconsistent_files_are_not_trusted` | 186 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::SessionFileSidTests.test_dead_process_and_missing_file_and_no_pid` | 202 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::LastRequestEpochByPidTests.test_fresh_session_without_cmdline_sid_is_found_through_its_pid` | 234 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::LastRequestEpochByPidTests.test_without_a_pid_the_sidless_session_stays_unknown` | 239 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::LastRequestEpochByPidTests.test_the_newest_request_of_the_two_candidate_files_wins` | 245 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::LastRequestEpochByPidTests.test_a_missing_candidate_file_falls_back_to_the_other_one` | 255 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::LastRequestEpochByPidTests.test_a_sibling_session_in_the_same_directory_is_never_picked_up` | 260 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::LastRequestEpochByPidTests.test_empty_conversation_file_is_unknown` | 266 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::PromptCacheIsWarmTests.test_margin_is_five_minutes` | 288 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::PromptCacheIsWarmTests.test_fresh_request_is_warm` | 291 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::PromptCacheIsWarmTests.test_boundary_and_older_is_cold` | 296 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::PromptCacheIsWarmTests.test_future_timestamp_from_clock_skew_counts_as_warm` | 301 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::PromptCacheIsWarmTests.test_unknown_when_provider_has_no_ttl_or_no_transcript` | 304 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::PromptCacheIsWarmTests.test_now_defaults_to_the_wall_clock` | 309 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::PromptCacheIsWarmTests.test_the_process_id_reaches_the_provider` | 314 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ModelDowngradeTests.test_warm_opus_keeps_its_model_but_still_lowers_effort` | 373 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ModelDowngradeTests.test_cold_opus_goes_down_to_sonnet_then_effort_in_that_order` | 385 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ModelDowngradeTests.test_fable_follows_the_same_rule` | 395 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ModelDowngradeTests.test_boundary_is_the_ttl_minus_margin` | 403 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ModelDowngradeTests.test_models_that_are_not_downgrade_candidates_never_get_a_model_command` | 411 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ModelDowngradeTests.test_unknown_warmth_keeps_the_old_always_downgrade_behaviour` | 420 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ModelDowngradeTests.test_a_failing_cache_probe_never_blocks_the_wrap_up` | 427 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ModelDowngradeTests.test_escape_hatch_restores_the_old_behaviour_and_never_probes` | 434 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ModelDowngradeTests.test_missing_setting_defaults_to_cache_aware` | 442 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::ModelDowngradeTests.test_provider_without_a_cache_ttl_keeps_the_old_behaviour` | 448 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::EffortDowngradeTests.test_warm_sonnet_55_gets_the_cache_safe_effort_drop` | 459 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::EffortDowngradeTests.test_warm_sonnet_5_skips_the_effort_drop_that_would_rewrite_the_cache` | 466 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::EffortDowngradeTests.test_cold_sonnet_5_gets_the_effort_drop_because_the_cache_is_gone_anyway` | 476 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::EffortDowngradeTests.test_unknown_warmth_on_sonnet_5_keeps_the_old_behaviour` | 482 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::EffortDowngradeTests.test_effort_already_at_or_below_the_target_is_left_alone` | 487 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::EffortDowngradeTests.test_effort_command_failure_is_swallowed` | 493 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::EffortDowngradeTests.test_public_wrapper_keeps_its_old_positional_signature` | 500 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::CallSiteWiringTests.test_cli_path_calls_the_shared_policy_once_per_target` | 520 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::CallSiteWiringTests.test_web_path_calls_the_shared_policy_with_the_spawn_time_values` | 534 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::CallSiteWiringTests.test_web_path_targets_the_resolved_session_for_unique_base` | 547 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |
| `test_handover_cache_policy.py::CallSiteWiringTests.test_real_policy_runs_end_to_end_through_the_web_path` | 564 | kapsam dışı | yok | devirde model/effort düşürme ve önbellek yaşı. İz: T4 (yaşam döngüsü); T1 (durum) |

### `py/tests/test_handover_session_wait.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_handover_session_wait.py::WebHandover.test_waiting_session_gets_no_keys_even_if_transcript_is_silent` | 52 | kapsam dışı | yok | diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript). İz: T4 (yaşam döngüsü); T10 (değnekçi) |
| `test_handover_session_wait.py::WebHandover.test_other_states_do_not_block` | 59 | kapsam dışı | yok | diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript). İz: T4 (yaşam döngüsü); T10 (değnekçi) |
| `test_handover_session_wait.py::SteerView.test_waiting_for_input_counts_as_open_question` | 71 | kapsam dışı | yok | diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript). İz: T4 (yaşam döngüsü); T10 (değnekçi) |
| `test_handover_session_wait.py::SteerView.test_other_waits_do_not_freeze_the_planner` | 76 | kapsam dışı | yok | diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript). İz: T4 (yaşam döngüsü); T10 (değnekçi) |
| `test_handover_session_wait.py::BatchHandover.test_batch_skips_waiting_session` | 95 | kapsam dışı | yok | diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript). İz: T4 (yaşam döngüsü); T10 (değnekçi) |
| `test_handover_session_wait.py::BatchHandover.test_batch_skips_open_question_in_transcript` | 99 | kapsam dışı | yok | diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript). İz: T4 (yaşam döngüsü); T10 (değnekçi) |
| `test_handover_session_wait.py::EngineDelivery.test_directive` | 129 | kapsam dışı | yok | diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript). İz: T4 (yaşam döngüsü); T10 (değnekçi) |
| `test_handover_session_wait.py::EngineDelivery.test_directive_goes_through_when_idle` | 132 | kapsam dışı | yok | diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript). İz: T4 (yaşam döngüsü); T10 (değnekçi) |
| `test_handover_session_wait.py::EngineDelivery.test_nudges` | 137 | kapsam dışı | yok | diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript). İz: T4 (yaşam döngüsü); T10 (değnekçi) |
| `test_handover_session_wait.py::EngineDelivery.test_brain_tour` | 143 | kapsam dışı | yok | diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript). İz: T4 (yaşam döngüsü); T10 (değnekçi) |
| `test_handover_session_wait.py::EngineDelivery.test_refusal_does_not_use_up_lesson_or_job_attempts` | 148 | kapsam dışı | yok | diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript). İz: T4 (yaşam döngüsü); T10 (değnekçi) |
| `test_handover_session_wait.py::EngineDelivery.test_unregistered_answer_is_kept_and_not_reported` | 161 | kapsam dışı | yok | diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript). İz: T4 (yaşam döngüsü); T10 (değnekçi) |
| `test_handover_session_wait.py::TermInput.test_engine_input_is_refused_but_owner_typing_is_not` | 183 | kapsam dışı | yok | diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript). İz: T4 (yaşam döngüsü); T10 (değnekçi) |

### `py/tests/test_input_box_typed.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_input_box_typed.py::TypedBoxTest.test_empty_box_is_not_typed` | 20 | kapsam dışı | yok | giriş kutusu ekran okuma. İz: T2 (terminal) |
| `test_input_box_typed.py::TypedBoxTest.test_grey_suggestion_is_not_typed` | 23 | kapsam dışı | yok | giriş kutusu ekran okuma. İz: T2 (terminal) |
| `test_input_box_typed.py::TypedBoxTest.test_default_color_text_is_typed` | 27 | kapsam dışı | yok | giriş kutusu ekran okuma. İz: T2 (terminal) |
| `test_input_box_typed.py::TypedBoxTest.test_whitespace_only_and_borders_ignored` | 32 | kapsam dışı | yok | giriş kutusu ekran okuma. İz: T2 (terminal) |
| `test_input_box_typed.py::TypedBoxTest.test_no_box_is_unknown` | 35 | kapsam dışı | yok | giriş kutusu ekran okuma. İz: T2 (terminal) |
| `test_input_box_typed.py::TypedBoxTest.test_last_box_wins` | 40 | kapsam dışı | yok | giriş kutusu ekran okuma. İz: T2 (terminal) |
| `test_input_box_typed.py::TypedBoxTest.test_ucli_uses_its_own_box_reader` | 44 | kapsam dışı | yok | giriş kutusu ekran okuma. İz: T2 (terminal) |
| `test_input_box_typed.py::TypedBoxTest.test_helper_false_on_error_and_unknown` | 50 | kapsam dışı | yok | giriş kutusu ekran okuma. İz: T2 (terminal) |
| `test_input_box_typed.py::KeepwarmApplyTest.test_box_full_skips_keepwarm` | 72 | kapsam dışı | yok | giriş kutusu ekran okuma. İz: T2 (terminal) |
| `test_input_box_typed.py::KeepwarmApplyTest.test_box_empty_sends_keepwarm` | 78 | kapsam dışı | yok | giriş kutusu ekran okuma. İz: T2 (terminal) |
| `test_input_box_typed.py::ApiNudgeApplyTest.test_box_full_skips_nudge` | 98 | kapsam dışı | yok | giriş kutusu ekran okuma. İz: T2 (terminal) |
| `test_input_box_typed.py::ApiNudgeApplyTest.test_target_denied_skips_nudge` | 104 | kapsam dışı | yok | giriş kutusu ekran okuma. İz: T2 (terminal) |
| `test_input_box_typed.py::ApiNudgeApplyTest.test_box_empty_sends_nudge` | 109 | kapsam dışı | yok | giriş kutusu ekran okuma. İz: T2 (terminal) |

### `py/tests/test_kill_access_denied.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_kill_access_denied.py::KillAccessDeniedTests.test_access_denied_still_cleans_up` | 30 | kapsam dışı | yok | kill yolu. İz: T4 (yaşam döngüsü) |

### `py/tests/test_live_model_effort.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_live_model_effort.py::LastAssistantSinceTests.test_since_returns_only_rows_written_after_the_process_started` | 62 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LastAssistantSinceTests.test_only_previous_incarnation_rows_means_unknown` | 68 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LastAssistantSinceTests.test_without_since_behaviour_is_unchanged` | 74 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LastAssistantSinceTests.test_row_without_timestamp_is_not_treated_as_old` | 79 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LastAssistantSinceTests.test_scan_stops_at_the_first_older_row` | 84 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LiveModelEffortTests.test_live_values_written_by_this_process_replace_cmdline_values` | 107 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LiveModelEffortTests.test_fresh_resume_without_a_turn_keeps_cmdline_values` | 111 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LiveModelEffortTests.test_effort_missing_in_live_rows_falls_back_per_field` | 115 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LiveModelEffortTests.test_another_sessions_file_is_ignored` | 119 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LiveModelEffortTests.test_non_claude_and_sidless_sessions_never_touch_the_file` | 123 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LiveModelEffortTests.test_unknown_process_start_falls_back` | 129 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LiveModelEffortTests.test_unchanged_file_is_not_reread_and_changed_file_is_` | 133 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LiveModelEffortTests.test_read_error_falls_back_and_does_not_raise` | 151 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LiveModelEndpointTests.test_live_model_ignores_previous_incarnation` | 168 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LiveModelEndpointTests.test_live_effort_ignores_previous_incarnation` | 175 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::LiveModelEndpointTests.test_neighbour_transcript_is_not_reported` | 183 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |
| `test_live_model_effort.py::EffortSwitchNoBlindEnter.test_no_dialog_no_enter` | 215 | kapsam dışı | yok | transkriptten canlı model/effort. İz: T1 (durum) |

### `py/tests/test_ls_json.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ls_json.py::LsJson.test_json_is_sorted_valid_and_has_no_table` | 27 | karşılandı | `list.rs::json_is_sorted_valid_and_has_no_table`<br>`run.py:list_json` | yok |
| `test_ls_json.py::LsJson.test_table_unchanged_without_flag` | 34 | karşılandı | `list.rs::table_matches_python_layout`<br>`run.py:list_table` | yok |

### `py/tests/test_mirror_marker.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_mirror_marker.py::NoteMirrorTests.test_records_the_pid_under_the_spec` | 50 | karşılandı | `mirrors.rs::notes_accumulate` | yok |
| `test_mirror_marker.py::NoteMirrorTests.test_same_spec_accumulates_pids` | 55 | karşılandı | `mirrors.rs::notes_accumulate` | yok |
| `test_mirror_marker.py::NoteMirrorTests.test_anything_else_leaves_the_dict_alone` | 61 | karşılandı | `mirrors.rs::notes_accumulate` | yok |
| `test_mirror_marker.py::FindSessionsMirrorsOutTests.test_viewers_are_collected_in_the_same_pass` | 94 | karşılandı | `tests/fake_proc.rs::discovers_each_cli_and_names`<br>`tests/real_proc.rs::real_viewer_process_is_seen` | tek tarama yapısal (`find_sessions` içinde `note_mirror`) |
| `test_mirror_marker.py::FindSessionsMirrorsOutTests.test_viewers_are_not_sessions_and_fleet_result_is_unchanged` | 100 | karşılandı | `tests/real_proc.rs::real_viewer_process_is_seen` | yok |
| `test_mirror_marker.py::FindSessionsMirrorsOutTests.test_default_does_not_collect_anything` | 107 | kapsam dışı | yok | Rust'ta isteğe bağlı toplama yok: `Scan.mirrors` her taramada dolar (bilinçli davranış farkı). İz: T1 (durum) |
| `test_mirror_marker.py::FindSessionsMirrorsOutTests.test_a_real_viewer_process_is_seen_by_the_real_scan` | 113 | karşılandı | `tests/real_proc.rs::real_viewer_process_is_seen` | yok |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_open_and_closed_are_stamped_per_remote_row` | 151 | kapsam dışı | yok | uzak satırlara `mirror_open` işareti. İz: T1 (durum); T5 (federasyon) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_same_name_on_two_hosts_is_told_apart` | 158 | kapsam dışı | yok | uzak satırlara `mirror_open` işareti. İz: T1 (durum); T5 (federasyon) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_match_is_exact_not_a_prefix` | 165 | kapsam dışı | yok | uzak satırlara `mirror_open` işareti. İz: T1 (durum); T5 (federasyon) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_cached_rows_are_copied_not_mutated` | 172 | kapsam dışı | yok | uzak satırlara `mirror_open` işareti. İz: T1 (durum); T5 (federasyon) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_stale_value_from_upstream_is_overwritten` | 180 | kapsam dışı | yok | uzak satırlara `mirror_open` işareti. İz: T1 (durum); T5 (federasyon) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_no_marker_at_all_when_the_state_is_unknown` | 185 | kapsam dışı | yok | uzak satırlara `mirror_open` işareti. İz: T1 (durum); T5 (federasyon) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_empty_set_means_known_and_closed` | 190 | kapsam dışı | yok | uzak satırlara `mirror_open` işareti. İz: T1 (durum); T5 (federasyon) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_local_closed_and_retired_rows_are_not_stamped` | 195 | kapsam dışı | yok | uzak satırlara `mirror_open` işareti. İz: T1 (durum); T5 (federasyon) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_a_dict_works_as_the_container_like_find_sessions_hands_it_over` | 204 | kapsam dışı | yok | uzak satırlara `mirror_open` işareti. İz: T1 (durum); T5 (federasyon) |
| `test_mirror_marker.py::MergeStatusMarkerTests.test_unpolled_host_adds_no_rows_and_no_crash` | 209 | kapsam dışı | yok | uzak satırlara `mirror_open` işareti. İz: T1 (durum); T5 (federasyon) |
| `test_mirror_marker.py::StatusPayloadWiringTests.test_remote_rows_carry_the_marker_from_the_fleet_scan` | 246 | kapsam dışı | yok | durum yayını bağlantısı. İz: T1 (durum) |
| `test_mirror_marker.py::StatusPayloadWiringTests.test_exactly_one_scan_carries_the_collector` | 252 | kapsam dışı | yok | durum yayını bağlantısı. İz: T1 (durum) |
| `test_mirror_marker.py::StatusPayloadWiringTests.test_a_closed_window_flips_the_marker_on_the_next_tick` | 262 | kapsam dışı | yok | durum yayını bağlantısı. İz: T1 (durum) |

### `py/tests/test_mirror_window.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_mirror_window.py::SpecFromCmdlineTests.test_host_and_name` | 33 | karşılandı | `mirrors.rs::specs`<br>`golden.rs::provider_detect_and_info` | yok |
| `test_mirror_window.py::SpecFromCmdlineTests.test_bare_name_is_local` | 36 | karşılandı | `mirrors.rs::specs`<br>`golden.rs::provider_detect_and_info` | yok |
| `test_mirror_window.py::SpecFromCmdlineTests.test_flags_before_or_after_the_target` | 39 | karşılandı | `mirrors.rs::specs`<br>`golden.rs::provider_detect_and_info` | `--port=9000` biçimi ayrıca yok; aynı tire kuralı sınanıyor |
| `test_mirror_window.py::SpecFromCmdlineTests.test_value_of_a_flag_is_not_mistaken_for_the_target` | 44 | karşılandı | `mirrors.rs::specs`<br>`golden.rs::provider_detect_and_info` | yok |
| `test_mirror_window.py::SpecFromCmdlineTests.test_once_is_not_a_window` | 47 | karşılandı | `mirrors.rs::specs`<br>`golden.rs::provider_detect_and_info` | yok |
| `test_mirror_window.py::SpecFromCmdlineTests.test_other_commands_do_not_match` | 50 | karşılandı | `mirrors.rs::specs`<br>`golden.rs::provider_detect_and_info` | yok |
| `test_mirror_window.py::SpecFromCmdlineTests.test_watch_without_a_target` | 56 | karşılandı | `mirrors.rs::specs`<br>`golden.rs::provider_detect_and_info` | yok |
| `test_mirror_window.py::SpecFromCmdlineTests.test_empty_parts` | 60 | karşılandı | `mirrors.rs::specs`<br>`golden.rs::provider_detect_and_info` | yok |
| `test_mirror_window.py::RunningMirrorsTests.test_collects_pids_per_spec` | 81 | karşılandı | `mirrors.rs::notes_accumulate`<br>`tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | yok |
| `test_mirror_window.py::RunningMirrorsTests.test_other_users_processes_are_ignored` | 86 | karşılandı | `tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | yok |
| `test_mirror_window.py::RunningMirrorsTests.test_unreadable_processes_are_skipped` | 89 | karşılandı | `tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | yok |
| `test_mirror_window.py::RunningMirrorsTests.test_default_uid_is_the_current_user` | 92 | karşılandı | `tests/real_proc.rs::real_viewer_process_is_seen` | yok |
| `test_mirror_window.py::RunningMirrorsTests.test_a_process_vanishing_mid_scan_is_skipped` | 97 | karşılandı | `tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | yok |
| `test_mirror_window.py::FocusWindowTests.test_uses_exact_title_matching_and_the_given_display` | 107 | karşılandı | `mirrors.rs::focus_reports_exit_status_and_passes_exact_args` | yok |
| `test_mirror_window.py::FocusWindowTests.test_failures_are_false_not_exceptions` | 120 | karşılandı | `mirrors.rs::focus_reports_exit_status_and_passes_exact_args`<br>`proc_cmd.rs::output_status_and_timeout` | yok |
| `test_mirror_window.py::OpenMirrorWindowSpawnTests.test_gnome_terminal_argv` | 141 | kapsam dışı | yok | görüntüleyici penceresi açma. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowSpawnTests.test_the_command_runs_cops_watch_against_this_panels_port` | 148 | kapsam dışı | yok | görüntüleyici penceresi açma. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowSpawnTests.test_a_failing_viewer_keeps_the_window_open_and_a_clean_exit_closes_it` | 154 | kapsam dışı | yok | görüntüleyici penceresi açma. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowSpawnTests.test_arguments_are_shell_quoted` | 161 | kapsam dışı | yok | görüntüleyici penceresi açma. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowSpawnTests.test_environment` | 165 | kapsam dışı | yok | görüntüleyici penceresi açma. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowSpawnTests.test_popen_failure_is_false` | 173 | kapsam dışı | yok | görüntüleyici penceresi açma. İz: T2 (terminal) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_success_spawns_once_with_the_panels_port` | 214 | kapsam dışı | yok | pencere açma uç mantığı. İz: T2 (terminal); T5 (federasyon) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_local_sessions_are_rejected` | 218 | kapsam dışı | yok | pencere açma uç mantığı. İz: T2 (terminal); T5 (federasyon) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_bad_characters_never_reach_the_command_line` | 225 | kapsam dışı | yok | pencere açma uç mantığı. İz: T2 (terminal); T5 (federasyon) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_unknown_host` | 232 | kapsam dışı | yok | pencere açma uç mantığı. İz: T2 (terminal); T5 (federasyon) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_session_must_be_in_the_hosts_last_known_state` | 237 | kapsam dışı | yok | pencere açma uç mantığı. İz: T2 (terminal); T5 (federasyon) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_a_session_without_tmux_has_no_terminal_to_mirror` | 248 | kapsam dışı | yok | pencere açma uç mantığı. İz: T2 (terminal); T5 (federasyon) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_no_x11_display` | 253 | kapsam dışı | yok | pencere açma uç mantığı. İz: T2 (terminal); T5 (federasyon) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_an_open_mirror_is_focused_not_duplicated` | 260 | kapsam dışı | yok | pencere açma uç mantığı. İz: T2 (terminal); T5 (federasyon) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_force_opens_a_second_one` | 266 | kapsam dışı | yok | pencere açma uç mantığı. İz: T2 (terminal); T5 (federasyon) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_another_sessions_mirror_does_not_count` | 272 | kapsam dışı | yok | pencere açma uç mantığı. İz: T2 (terminal); T5 (federasyon) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_launch_failure` | 277 | kapsam dışı | yok | pencere açma uç mantığı. İz: T2 (terminal); T5 (federasyon) |
| `test_mirror_window.py::OpenMirrorWindowBackendTests.test_messages_follow_the_language` | 283 | kapsam dışı | yok | pencere açma uç mantığı. İz: T2 (terminal); T5 (federasyon) |
| `test_mirror_window.py::MirrorRouteHttpTests.test_route_is_declared_local_only` | 326 | kapsam dışı | yok | HTTP ucu. İz: T2 (terminal) |
| `test_mirror_window.py::MirrorRouteHttpTests.test_post_with_a_remote_host_field_is_handled_locally` | 329 | kapsam dışı | yok | HTTP ucu. İz: T2 (terminal) |
| `test_mirror_window.py::MirrorRouteHttpTests.test_force_flag_is_passed_through` | 334 | kapsam dışı | yok | HTTP ucu. İz: T2 (terminal) |
| `test_mirror_window.py::MirrorRouteHttpTests.test_name_is_required` | 338 | kapsam dışı | yok | HTTP ucu. İz: T2 (terminal) |
| `test_mirror_window.py::MirrorRouteHttpTests.test_token_is_required` | 343 | kapsam dışı | yok | HTTP ucu. İz: T2 (terminal) |
| `test_mirror_window.py::LayoutRecognisesMirrorWindowsTests.test_a_mirror_window_is_tiled_once_its_spec_is_known` | 358 | kapsam dışı | yok | pencere döşeme (`cops layout`). İz: T6 (CLI) |
| `test_mirror_window.py::LayoutRecognisesMirrorWindowsTests.test_without_the_spec_it_is_skipped_as_before` | 363 | kapsam dışı | yok | pencere döşeme (`cops layout`). İz: T6 (CLI) |
| `test_mirror_window.py::LayoutRecognisesMirrorWindowsTests.test_title_from_the_viewer_survives_list_windows_cleaning` | 368 | kapsam dışı | yok | pencere döşeme (`cops layout`). İz: T6 (CLI) |

### `py/tests/test_model_usage.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_model_usage.py::ModelUsageTest.test_split_rows_of_one_api_reply_count_once` | 21 | kapsam dışı | yok | son 60 dakika model kullanım taraması. İz: T7 (periyodik+kullanım) |
| `test_model_usage.py::ModelUsageTest.test_scan_counts_recent_calls_per_family_and_lists_fable_top` | 42 | kapsam dışı | yok | son 60 dakika model kullanım taraması. İz: T7 (periyodik+kullanım) |
| `test_model_usage.py::ModelUsageTest.test_subagent_effort_and_fable_agent_count` | 62 | kapsam dışı | yok | son 60 dakika model kullanım taraması. İz: T7 (periyodik+kullanım) |

### `py/tests/test_needs_ho_transcript.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_needs_ho_transcript.py::WebNeedsHoCachedTests.test_the_sessions_own_transcript_is_used_not_the_newest_in_the_cwd` | 64 | kapsam dışı | yok | web/toplu devirde transkript seçimi (en yeni dosyaya düşüş Rust'ta yok, sapma 1; sid var dosya yok artık Python'da da None, Python düzeltildi: 43753998). İz: T1 (durum); T4 (yaşam döngüsü) |
| `test_needs_ho_transcript.py::WebNeedsHoCachedTests.test_only_without_a_sid_it_falls_back_to_the_newest_file` | 68 | kapsam dışı | yok | web/toplu devirde transkript seçimi (en yeni dosyaya düşüş Rust'ta yok, sapma 1; sid var dosya yok artık Python'da da None, Python düzeltildi: 43753998). İz: T1 (durum); T4 (yaşam döngüsü) |
| `test_needs_ho_transcript.py::HandoverBatchTests.test_the_sessions_own_transcript_is_used_not_the_newest_in_the_cwd` | 90 | kapsam dışı | yok | web/toplu devirde transkript seçimi (en yeni dosyaya düşüş Rust'ta yok, sapma 1; sid var dosya yok artık Python'da da None, Python düzeltildi: 43753998). İz: T1 (durum); T4 (yaşam döngüsü) |
| `test_needs_ho_transcript.py::HandoverBatchTests.test_without_a_sid_it_falls_back_to_the_newest_file` | 94 | kapsam dışı | yok | web/toplu devirde transkript seçimi (en yeni dosyaya düşüş Rust'ta yok, sapma 1; sid var dosya yok artık Python'da da None, Python düzeltildi: 43753998). İz: T1 (durum); T4 (yaşam döngüsü) |

### `py/tests/test_orch_store_db.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_orch_store_db.py::OrchStoreDbTest.test_prefix_is_db_ready` | 28 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state); T7 (periyodik+kullanım) |
| `test_orch_store_db.py::OrchStoreDbTest.test_db_mode_load_from_db_when_file_missing_or_stale` | 32 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state); T7 (periyodik+kullanım) |
| `test_orch_store_db.py::OrchStoreDbTest.test_dual_mode_file_wins` | 42 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state); T7 (periyodik+kullanım) |
| `test_orch_store_db.py::OrchStoreDbTest.test_list_runs_uses_mirror_in_db_mode` | 49 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state); T7 (periyodik+kullanım) |
| `test_orch_store_db.py::OrchStoreDbTest.test_corrupt_file_in_db_mode_returns_db` | 55 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state); T7 (periyodik+kullanım) |

### `py/tests/test_orphan_cli.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_orphan_cli.py::OrphanTests.test_fallback_name` | 7 | karşılandı | `discovery.rs::fallback_names`<br>`golden.rs::names_paths_and_token_format` | yok |
| `test_orphan_cli.py::OrphanTests.test_terminal_lost` | 10 | karşılandı | `tests/fake_proc.rs::tmux_terminal_and_orphans`<br>`tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | yok |
| `test_orphan_cli.py::OrphanTests.test_idle_spin` | 18 | karşılandı | `tests/fake_proc.rs::tmux_terminal_and_orphans` | yok |
| `test_orphan_cli.py::OrphanReportTests.test_spin_after_ten_minutes` | 30 | karşılandı | `tests/fake_proc.rs::tmux_terminal_and_orphans` | yok |

### `py/tests/test_orphan_watch.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_orphan_watch.py::Sockets.test_dead_server_socket_deleted` | 48 | kapsam dışı | yok | sahipsiz kaynak denetimi. İz: T7 (periyodik+kullanım) |
| `test_orphan_watch.py::Sockets.test_live_server_owner_dead_old_reported_not_killed` | 54 | kapsam dışı | yok | sahipsiz kaynak denetimi. İz: T7 (periyodik+kullanım) |
| `test_orphan_watch.py::Sockets.test_young_or_owner_alive_not_reported` | 61 | kapsam dışı | yok | sahipsiz kaynak denetimi. İz: T7 (periyodik+kullanım) |
| `test_orphan_watch.py::Sockets.test_usage_socket_killed_and_removed` | 67 | kapsam dışı | yok | sahipsiz kaynak denetimi. İz: T7 (periyodik+kullanım) |
| `test_orphan_watch.py::Sockets.test_main_and_foreign_sockets_ignored` | 74 | kapsam dışı | yok | sahipsiz kaynak denetimi. İz: T7 (periyodik+kullanım) |
| `test_orphan_watch.py::Procs.test_app_server_child_skipped_when_parent_has_no_info` | 111 | kapsam dışı | yok | sahipsiz kaynak denetimi. İz: T7 (periyodik+kullanım) |
| `test_orphan_watch.py::Procs.test_old_unknown_cli_flagged_young_and_known_not` | 120 | kapsam dışı | yok | sahipsiz kaynak denetimi. İz: T7 (periyodik+kullanım) |
| `test_orphan_watch.py::Procs.test_under_cops_pane_or_known_ancestor_not_flagged` | 124 | kapsam dışı | yok | sahipsiz kaynak denetimi. İz: T7 (periyodik+kullanım) |
| `test_orphan_watch.py::Procs.test_chrome_native_host_ignored` | 130 | kapsam dışı | yok | sahipsiz kaynak denetimi. İz: T7 (periyodik+kullanım) |
| `test_orphan_watch.py::Procs.test_codex_app_server_and_its_children_ignored` | 134 | kapsam dışı | yok | sahipsiz kaynak denetimi. İz: T7 (periyodik+kullanım) |
| `test_orphan_watch.py::Job.test_notifies_only_new_keys_and_forgets_resolved` | 149 | kapsam dışı | yok | sahipsiz kaynak denetimi. İz: T7 (periyodik+kullanım) |
| `test_orphan_watch.py::Job.test_registered_as_light_job` | 161 | kapsam dışı | yok | sahipsiz kaynak denetimi. İz: T7 (periyodik+kullanım) |

### `py/tests/test_path_env.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_path_env.py::TrustedPathEnv.test_keeps_trusted_and_order` | 22 | kapsam dışı | yok | PATH süzgeci (TBD#450); Rust eşi `cops_state::paths::trusted_path_env`, test `paths.rs::trusted_path_env_drops_untrusted`. İz: W0-a durum (rs/state) |
| `test_path_env.py::TrustedPathEnv.test_drops_missing_relative_empty` | 26 | kapsam dışı | yok | PATH süzgeci (TBD#450); Rust eşi `cops_state::paths::trusted_path_env`, test `paths.rs::trusted_path_env_drops_untrusted`. İz: W0-a durum (rs/state) |
| `test_path_env.py::TrustedPathEnv.test_drops_file_and_world_writable` | 31 | kapsam dışı | yok | PATH süzgeci (TBD#450); Rust eşi `cops_state::paths::trusted_path_env`, test `paths.rs::trusted_path_env_drops_untrusted`. İz: W0-a durum (rs/state) |
| `test_path_env.py::TrustedPathEnv.test_drops_foreign_owner` | 40 | kapsam dışı | yok | PATH süzgeci (TBD#450); Rust eşi `cops_state::paths::trusted_path_env`, test `paths.rs::trusted_path_env_drops_untrusted`. İz: W0-a durum (rs/state) |
| `test_path_env.py::TrustedPathEnv.test_duplicates_kept_once` | 51 | kapsam dışı | yok | PATH süzgeci (TBD#450); Rust eşi `cops_state::paths::trusted_path_env`, test `paths.rs::trusted_path_env_drops_untrusted`. İz: W0-a durum (rs/state) |
| `test_path_env.py::TrustedPathEnv.test_secure_environ_rewrites_and_reports` | 55 | kapsam dışı | yok | PATH süzgeci (TBD#450); Rust eşi `cops_state::paths::trusted_path_env`, test `paths.rs::trusted_path_env_drops_untrusted`. İz: W0-a durum (rs/state) |

### `py/tests/test_paths_isolation.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_paths_isolation.py::CustomRunnerTest.test_script_that_loaded_unittest_is_isolated` | 32 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_paths_isolation.py::CustomRunnerTest.test_script_that_loaded_a_repo_test_module_is_isolated` | 36 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_paths_isolation.py::CustomRunnerTest.test_plain_script_uses_real_dir` | 42 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_paths_isolation.py::LateTestImportTest.test_unittest_after_live_dir_refused` | 62 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_paths_isolation.py::LateTestImportTest.test_repo_test_module_after_live_dir_refused` | 68 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_paths_isolation.py::LateTestImportTest.test_plain_imports_still_work` | 73 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_paths_isolation.py::LateTestImportTest.test_real_dir_opt_in_allows_unittest` | 78 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_paths_isolation.py::IsolationTest.test_state_dir_is_not_live_under_runner` | 84 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_paths_isolation.py::IsolationTest.test_runner_detection` | 89 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |

### `py/tests/test_proc07_io_ucli_not_fleet.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_proc07_io_ucli_not_fleet.py::MatchesProcTest.test_repl_is_fleet` | 15 | karşılandı | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info` | yok |
| `test_proc07_io_ucli_not_fleet.py::MatchesProcTest.test_oneshot_and_reviewer_are_not_fleet` | 18 | karşılandı | `providers.rs::detect`<br>`golden.rs::provider_detect_and_info` | yok |
| `test_proc07_io_ucli_not_fleet.py::IoAskLiveNameTest.test_rejects_live_same_name` | 28 | kapsam dışı | yok | tek atımlık ucli sorusu ucu. İz: T7 (periyodik+kullanım) |
| `test_proc07_io_ucli_not_fleet.py::IoAskLiveNameTest.test_other_name_goes_through` | 36 | kapsam dışı | yok | tek atımlık ucli sorusu ucu. İz: T7 (periyodik+kullanım) |

### `py/tests/test_proc08_model_switch_no_blind_enter.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_proc08_model_switch_no_blind_enter.py::NoBlindEnterTest.test_permission_dialog_is_not_confirmed` | 33 | kapsam dışı | yok | canlı model değiştirme tuşları. İz: T4 (yaşam döngüsü) |
| `test_proc08_model_switch_no_blind_enter.py::NoBlindEnterTest.test_switch_dialog_confirmed_once` | 36 | kapsam dışı | yok | canlı model değiştirme tuşları. İz: T4 (yaşam döngüsü) |
| `test_proc08_model_switch_no_blind_enter.py::NoBlindEnterTest.test_applied_without_dialog` | 39 | kapsam dışı | yok | canlı model değiştirme tuşları. İz: T4 (yaşam döngüsü) |

### `py/tests/test_proc_stat_parse.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_proc_stat_parse.py::ProcStatTest.test_plain` | 13 | karşılandı | `procfs.rs::stat_with_parens_in_comm` | yok |
| `test_proc_stat_parse.py::ProcStatTest.test_comm_with_space_and_paren` | 18 | karşılandı | `procfs.rs::stat_with_parens_in_comm` | yok |
| `test_proc_stat_parse.py::ProcStatTest.test_starttime_index` | 22 | karşılandı | `procfs.rs::stat_with_parens_in_comm` | yok |
| `test_proc_stat_parse.py::ProcStatTest.test_no_paren_raises` | 26 | karşılandı | `procfs.rs::stat_with_parens_in_comm` | yok |
| `test_proc_stat_parse.py::ProcStatTest.test_own_ppid` | 30 | karşılandı | `tests/fake_proc.rs::own_ppid_from_real_proc` | yok |
| `test_proc_stat_parse.py::ProcStatTest.test_no_inline_copies` | 33 | kapsam dışı | yok | Python kaynağında kopya ayrıştırıcı yasağı (Rust'ta karşılığı yok). İz: yalnız Python |

### `py/tests/test_procscan_tbd365.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_procscan_tbd365.py::SessionFilesTest.test_bad_files_are_skipped_and_counted` | 62 | karşılandı | `tests/fake_proc.rs::bad_session_files_are_skipped_and_counted` | Python düzeltildi: 6ae5da3 |
| `test_procscan_tbd365.py::SessionFilesTest.test_negative_or_zero_pid_never_reaches_kill` | 74 | karşılandı | `tests/fake_proc.rs::bad_session_files_are_skipped_and_counted` | Python düzeltildi: 6ae5da3 |
| `test_procscan_tbd365.py::SessionFilesTest.test_overflowing_pid_is_skipped_and_counted` | 80 | karşılandı | `tests/fake_proc.rs::overflowing_pids_are_skipped_and_counted` | Python düzeltildi: 35a1eb78 |
| `test_procscan_tbd365.py::ForeignCmdlineTest.test_find_sessions_reads_only_own_cmdline` | 128 | karşılandı | `tests/fake_proc.rs::other_users_processes_are_never_read`<br>`tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | Python düzeltildi: 6ae5da3 |
| `test_procscan_tbd365.py::ForeignCmdlineTest.test_running_mirrors_reads_only_own_cmdline` | 135 | karşılandı | `tests/fake_proc.rs::other_users_processes_are_never_read`<br>`tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | Python düzeltildi: 6ae5da3 |
| `test_procscan_tbd365.py::ForeignProcessContentTest.test_orphans_only_own_and_foreign_ancestor_not_read` | 190 | karşılandı | `tests/fake_proc.rs::other_users_processes_are_never_read` | orphan_watch'ın Rust karşılığı yok (T7); en yakın yol OrphanTracker, kanıt testi. Python düzeltildi: f51a442f |
| `test_procscan_tbd365.py::ForeignProcessContentTest.test_cpu_hogs_only_own` | 199 | karşılandı | `tests/fake_proc.rs::other_users_processes_are_never_read` | orphan_watch'ın Rust karşılığı yok (T7); en yakın yol OrphanTracker, kanıt testi. Python düzeltildi: f51a442f |
| `test_procscan_tbd365.py::ForeignProcessContentTest.test_gnome_terminal_server_cmdline_read_only_for_own` | 208 | kapsam dışı | yok | gnome-terminal sunucusu araması, Rust karşılığı yok. Python düzeltildi: f51a442f. İz: T1 (durum) |
| `test_procscan_tbd365.py::TmuxAncestorTest.test_foreign_ancestor_stops_walk_without_reading_it` | 234 | karşılandı | `tests/fake_proc.rs::other_users_processes_are_never_read`<br>`tests/fake_proc.rs::tmux_terminal_and_orphans` | Python düzeltildi: 6ae5da3 |
| `test_procscan_tbd365.py::TranscriptRowsTest.test_bad_rows_skipped` | 261 | karşılandı | `needs_ho.rs::broken_input_is_skipped_and_counted`<br>`golden.rs::transcripts_needs_ho` | Python düzeltildi: 6ae5da3 |
| `test_procscan_tbd365.py::TranscriptRowsTest.test_needs_ho_decides_instead_of_raising` | 286 | karşılandı | `needs_ho.rs::needs_ho_decides_with_bad_rows` | Python düzeltildi: 6ae5da3 |
| `test_procscan_tbd365.py::BaselineAtomicTest.test_baseline_written_via_replace` | 295 | karşılandı | `needs_ho.rs::baseline_is_written_atomically` | Python düzeltildi: 6ae5da3 |
| `test_procscan_tbd365.py::SidPathTest.test_sid_with_path_parts_is_not_joined` | 318 | karşılandı | `tests/fake_proc.rs::transcript_requires_exact_sid` | Python düzeltildi: 6ae5da3 |
| `test_procscan_tbd365.py::SidPathTest.test_invalid_or_missing_sid_file_never_guesses` | 333 | karşılandı | `tests/fake_proc.rs::transcript_requires_exact_sid` | Python düzeltildi: 43753998 |
| `test_procscan_tbd365.py::UsageRowsTest.test_bad_rows_skipped_on_first_call` | 376 | karşılandı | `usage.rs::bad_row_is_skipped_and_counted`<br>`golden.rs::usage_totals_two_calls` | Python düzeltildi: 6ae5da3 |
| `test_procscan_tbd365.py::UsageRowsTest.test_overflowing_token_count_does_not_blank_total` | 393 | karşılandı | `usage.rs::overflowing_count_row_does_not_blank_total` | Rust'ta satır serde'de ayrıştırılmaz (sapma 4). Python düzeltildi: 35a1eb78 |
| `test_procscan_tbd365.py::UsageRowsTest.test_bad_subagent_row_does_not_blank_total` | 401 | karşılandı | `usage.rs::bad_row_is_skipped_and_counted`<br>`golden.rs::usage_totals_two_calls` | Python düzeltildi: 6ae5da3 |
| `test_procscan_tbd365.py::UsageRowsTest.test_day_usage_file_survives_bad_row` | 409 | kapsam dışı | yok | gün bazlı döküm (`day_usage`); ortak `_from_row` düzeltmesi `usage.rs::parse` satırında. İz: T7 (periyodik+kullanım) |
| `test_procscan_tbd365.py::UsageRowsTest.test_thread_start_failure_does_not_lock_path` | 419 | karşılandı | `usage.rs::spawn_failure_does_not_lock_the_path` | Python düzeltildi: 6ae5da3 |
| `test_procscan_tbd365.py::UsageRowsTest.test_shrinking_file_does_not_evict_another_when_full` | 436 | karşılandı | `usage.rs::file_cache_evicts_in_insertion_order` | Python düzeltildi: 6ae5da3 |
| `test_procscan_tbd365.py::LongLineTest.test_usage_limit_boundary_and_partial_tail` | 472 | karşılandı | `usage.rs::long_lines_are_skipped_and_counted` | Python düzeltildi: 66b47a37 |
| `test_procscan_tbd365.py::LongLineTest.test_usage_memory_is_bounded` | 503 | karşılandı | `usage.rs::long_lines_are_skipped_and_counted` | Python düzeltildi: 66b47a37 |
| `test_procscan_tbd365.py::LongLineTest.test_needs_ho_long_line_skipped_and_counted` | 532 | karşılandı | `needs_ho.rs::long_lines_are_skipped_and_counted` | Python düzeltildi: 66b47a37 |
| `test_procscan_tbd365.py::DiagSkippedTest.test_diag_carries_all_skip_counters` | 556 | karşılandı | `usage.rs::bad_row_is_skipped_and_counted`<br>`tests/fake_proc.rs::bad_session_files_are_skipped_and_counted` | Rust sayaçları JSON'da (`Usage.skipped_rows`, `ScanDiag`); Tanılama yükü T1. Python düzeltildi: 1af088ef |
| `test_procscan_tbd365.py::DiagSkippedTest.test_diag_survives_counter_growing_while_read` | 574 | kapsam dışı | yok | Python'a özgü: iplikler arası paylaşılan `Counter` dolaşımı; Rust sayaçları çağrı/tarama başına değer, paylaşılmaz. İz: T1 |

### `py/tests/test_provider_live_context.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_provider_live_context.py::TestBase.test_default_and_unsupported_are_none` | 23 | kapsam dışı | yok | `live_context` satır alanı. İz: T1 (durum) |
| `test_provider_live_context.py::TestCodex.test_last_token_count_input_tokens` | 43 | kapsam dışı | yok | `live_context` satır alanı. İz: T1 (durum) |
| `test_provider_live_context.py::TestCodex.test_no_token_event_or_no_file_is_none` | 47 | kapsam dışı | yok | `live_context` satır alanı. İz: T1 (durum) |
| `test_provider_live_context.py::TestCodex.test_null_info_is_none` | 52 | kapsam dışı | yok | `live_context` satır alanı. İz: T1 (durum) |
| `test_provider_live_context.py::TestCopilot.test_latest_main_agent_row` | 75 | kapsam dışı | yok | `live_context` satır alanı. İz: T1 (durum) |
| `test_provider_live_context.py::TestCopilot.test_unknown_session_or_no_db_is_none` | 78 | kapsam dışı | yok | `live_context` satır alanı. İz: T1 (durum) |
| `test_provider_live_context.py::TestStatusRow.test_context_info_uses_provider_hook_and_hides_unknown` | 89 | kapsam dışı | yok | `live_context` satır alanı. İz: T1 (durum) |

### `py/tests/test_provider_wants_split.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_provider_wants_split.py::WantsSplitTests.test_ucli_no_wrapup_but_has_conversation_and_stuck` | 15 | kapsam dışı | yok | devir/kurtarma bayrakları. İz: T4 (yaşam döngüsü) |
| `test_provider_wants_split.py::WantsSplitTests.test_claude_defaults_follow_has_conversation` | 21 | kapsam dışı | yok | devir/kurtarma bayrakları. İz: T4 (yaşam döngüsü) |
| `test_provider_wants_split.py::WantsSplitTests.test_shell_wants_nothing` | 26 | kapsam dışı | yok | devir/kurtarma bayrakları. İz: T4 (yaşam döngüsü) |

### `py/tests/test_review_fixes_2026_11_04.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_review_fixes_2026_11_04.py::CommittedSinceTimeCompare.test_offsets_compared_as_instants` | 37 | karşılandı | `needs_ho.rs::iso_times_compare_as_instants`<br>`golden.rs::committed_after_iso_rules` | yok |
| `test_review_fixes_2026_11_04.py::CommittedSinceTimeCompare.test_unparseable_baseline_means_unknown_so_do_ho` | 42 | karşılandı | `needs_ho.rs::iso_times_compare_as_instants`<br>`golden.rs::committed_after_iso_rules` | yok |
| `test_review_fixes_2026_11_04.py::CommittedSinceTimeCompare.test_no_commit_is_not_new` | 45 | karşılandı | `needs_ho.rs::iso_times_compare_as_instants`<br>`golden.rs::committed_after_iso_rules` | yok |
| `test_review_fixes_2026_11_04.py::HandoverBatchFixes.test_dry_run_does_not_write_baseline_and_shows_skip` | 64 | kapsam dışı | yok | toplu devir akışı. İz: T4 (yaşam döngüsü) |
| `test_review_fixes_2026_11_04.py::HandoverBatchFixes.test_real_run_writes_baseline_atomically` | 71 | kapsam dışı | yok | toplu devir akışı. İz: T4 (yaşam döngüsü) |
| `test_review_fixes_2026_11_04.py::HandoverBatchFixes.test_sidless_session_in_shared_cwd_is_not_skipped` | 77 | kapsam dışı | yok | toplu devir akışı. İz: T4 (yaşam döngüsü) |
| `test_review_fixes_2026_11_04.py::GuardExitCode.test_spawn_error_gives_nonzero_exit` | 96 | kapsam dışı | yok | guard komutu. İz: T4 (yaşam döngüsü); T6 (CLI) |
| `test_review_fixes_2026_11_04.py::GuardExitCode.test_all_ok_exit_zero` | 101 | kapsam dışı | yok | guard komutu. İz: T4 (yaşam döngüsü); T6 (CLI) |
| `test_review_fixes_2026_11_04.py::UploadNoOverwriteRace.test_file_appearing_after_check_is_not_clobbered` | 107 | kapsam dışı | yok | dosya yükleme. İz: T3 (dosya) |
| `test_review_fixes_2026_11_04.py::UploadNoOverwriteRace.test_no_overwrite_creates_new_file` | 116 | kapsam dışı | yok | dosya yükleme. İz: T3 (dosya) |
| `test_review_fixes_2026_11_04.py::UploadNoOverwriteRace.test_dir_is_fsynced_after_write` | 123 | kapsam dışı | yok | dosya yükleme. İz: T3 (dosya) |
| `test_review_fixes_2026_11_04.py::CliStatusOverride.test_stale_override_is_not_found` | 138 | kapsam dışı | yok | CLI ikilisi bulma ayarı. İz: T7 (periyodik+kullanım) |
| `test_review_fixes_2026_11_04.py::CliStatusOverride.test_valid_override_is_found` | 143 | kapsam dışı | yok | CLI ikilisi bulma ayarı. İz: T7 (periyodik+kullanım) |
| `test_review_fixes_2026_11_04.py::CliStatusOverride.test_non_text_override_or_map_is_ignored` | 149 | kapsam dışı | yok | CLI ikilisi bulma ayarı. İz: T7 (periyodik+kullanım) |
| `test_review_fixes_2026_11_04.py::SeedNonDict.test_list_content_is_left_alone` | 157 | kapsam dışı | yok | oturum açılışında ayar tohumlama. İz: T4 (yaşam döngüsü) |
| `test_review_fixes_2026_11_04.py::FileLockPathNormalizationTest.test_spellings_of_one_path_share_one_lock_entry` | 174 | kapsam dışı | yok | durum dosyası kilidi. İz: W0-a durum (rs/state) |

### `py/tests/test_review_self_verify.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_review_self_verify.py::SelfVerifyTest.test_verdicts_applied_session_not_woken` | 54 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_failure_returns_to_new_then_unclear_after_max_tries` | 69 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_apply_verdicts_exception_requeues_not_stuck` | 78 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_timeout_kills_and_requeues` | 90 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_concurrent_calls_same_project_only_one_starts` | 98 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_missing_verdict_line_requeues_only_that_finding` | 131 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_recover_returns_orphaned_self_verify_to_new` | 138 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_recover_also_returns_orphaned_remote_verify_to_new` | 145 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_recover_leaves_live_remote_verify_alone` | 153 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_process_verdicts_ignores_self_sessions` | 165 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_http_verify_and_auto_verify_use_self_mode` | 174 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_bulk_approve_only_verified_filtered` | 183 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_bulk_endpoint_is_human_only` | 198 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_default_verifier_is_claude_sonnet` | 204 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_codex_verifier_read_only_argv` | 207 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_evren_verifier_waits_for_running_evren_review_and_has_no_allow_flags` | 220 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_missing_model_is_busy_not_marked` | 240 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |
| `test_review_self_verify.py::SelfVerifyTest.test_config_accepts_provider_and_single_model` | 246 | kapsam dışı | yok | reviewer doğrulaması. İz: T8 (reviewer) |

### `py/tests/test_rfh_marker.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_rfh_marker.py::RfhMarkerTests.test_prose_mention_is_not_a_marker` | 6 | karşılandı | `needs_ho.rs::prose_mention_is_not_a_marker`<br>`golden.rs::rfh_marker` | yok |
| `test_rfh_marker.py::RfhMarkerTests.test_heading_and_bare_line_count` | 11 | karşılandı | `needs_ho.rs::heading_and_bare_line_count`<br>`golden.rs::rfh_marker` | yok |
| `test_rfh_marker.py::RfhMarkerTests.test_code_block_and_quote_do_not_count` | 16 | karşılandı | `needs_ho.rs::code_block_and_quote_do_not_count`<br>`golden.rs::rfh_marker` | yok |

### `py/tests/test_routing_guidance.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_routing_guidance.py::DefaultsTest.test_claude_defaults_to_newest_sonnet_medium` | 32 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::DefaultsTest.test_provider_without_model_choices_gives_empty_default` | 38 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::DefaultsTest.test_override_wins_and_invalid_override_falls_back` | 44 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::DefaultsTest.test_other_providers_keep_old_top_level_effort` | 53 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::GuidanceTest.test_enabled_by_default_and_bundled_path_used` | 60 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::GuidanceTest.test_off_disables_flag` | 65 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::GuidanceTest.test_override_text_is_written_and_used` | 71 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::GuidanceTest.test_guidance_failure_never_breaks_spawn` | 80 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::CodexSyncTest.test_agy_file_is_created_with_only_the_block_and_removed_with_it` | 90 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::CodexSyncTest.test_existing_agy_file_keeps_user_text` | 98 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::CodexSyncTest.test_missing_file_is_not_created` | 117 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::CodexSyncTest.test_write_is_idempotent_keeps_rest_and_backs_up` | 122 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::CodexSyncTest.test_text_change_replaces_block_and_off_removes_it` | 131 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::SonnetMainTextTest.test_routing_md_names_sonnet_medium_main` | 147 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_routing_guidance.py::SonnetMainTextTest.test_steward_persona_economy_line` | 154 | kapsam dışı | yok | model yönergesi ve varsayılanlar. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_session_usage.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_session_usage.py::SessionUsageTest.test_main_and_subagents_separate_with_family_breakdown` | 33 | karşılandı | `tests/fake_proc.rs::usage_dedups_subagents_and_increments`<br>`golden.rs::usage_totals_two_calls` | yok |
| `test_session_usage.py::SessionUsageTest.test_synthetic_rows_are_not_turns_nor_a_family` | 47 | karşılandı | `golden.rs::usage_totals_two_calls`<br>`tests/fake_proc.rs::usage_dedups_subagents_and_increments` | yok |
| `test_session_usage.py::SessionUsageTest.test_split_rows_of_one_reply_counted_once_and_max_kept` | 60 | karşılandı | `tests/fake_proc.rs::usage_dedups_subagents_and_increments`<br>`golden.rs::usage_totals_two_calls` | yok |
| `test_session_usage.py::SessionUsageTest.test_bad_lines_skipped` | 69 | karşılandı | `tests/fake_proc.rs::usage_dedups_subagents_and_increments`<br>`golden.rs::usage_totals_two_calls` | yok |
| `test_session_usage.py::SessionUsageTest.test_incremental_append_truncate_and_partial_last_line` | 76 | karşılandı | `tests/fake_proc.rs::usage_dedups_subagents_and_increments`<br>`golden.rs::usage_totals_two_calls` | yok |
| `test_session_usage.py::SessionUsageTest.test_missing_file_returns_none_never_raises` | 111 | karşılandı | `tests/fake_proc.rs::usage_dedups_subagents_and_increments`<br>`golden.rs::usage_totals_two_calls` | yok |
| `test_session_usage.py::SessionUsageTest.test_cached_returns_none_first_then_value_after_background_refresh` | 115 | karşılandı | `usage.rs::cache_first_none_then_value_and_error_keeps_last_good` | yok |
| `test_session_usage.py::SessionUsageTest.test_fmt_tokens` | 126 | karşılandı | `usage.rs::fmt_tokens_python_examples`<br>`golden.rs::names_paths_and_token_format` | yok |

### `py/tests/test_shared_state_readonly.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_shared_state_readonly.py::SharedStateTest.test_allowed_only_outside_shared_or_default_instance` | 58 | kapsam dışı | yok | ikinci örnekte ortak dosya yazma yasağı (TBD#412). İz: W1-pre sağlayıcı (rs/prov); canlıya T4; W0-a durum (rs/state) |
| `test_shared_state_readonly.py::SharedStateTest.test_empty_setting_does_not_delete_shared_keys` | 68 | kapsam dışı | yok | ikinci örnekte ortak dosya yazma yasağı (TBD#412). İz: W1-pre sağlayıcı (rs/prov); canlıya T4; W0-a durum (rs/state) |
| `test_shared_state_readonly.py::SharedStateTest.test_other_setting_neither_written_nor_used` | 78 | kapsam dışı | yok | ikinci örnekte ortak dosya yazma yasağı (TBD#412). İz: W1-pre sağlayıcı (rs/prov); canlıya T4; W0-a durum (rs/state) |
| `test_shared_state_readonly.py::SharedStateTest.test_same_setting_is_used_and_missing_file_not_created` | 86 | kapsam dışı | yok | ikinci örnekte ortak dosya yazma yasağı (TBD#412). İz: W1-pre sağlayıcı (rs/prov); canlıya T4; W0-a durum (rs/state) |
| `test_shared_state_readonly.py::SharedStateTest.test_usage_written_to_own_dir_and_both_counted` | 95 | kapsam dışı | yok | ikinci örnekte ortak dosya yazma yasağı (TBD#412). İz: W1-pre sağlayıcı (rs/prov); canlıya T4; W0-a durum (rs/state) |
| `test_shared_state_readonly.py::SharedStateTest.test_default_instance_uses_shared_usage` | 109 | kapsam dışı | yok | ikinci örnekte ortak dosya yazma yasağı (TBD#412). İz: W1-pre sağlayıcı (rs/prov); canlıya T4; W0-a durum (rs/state) |
| `test_shared_state_readonly.py::SharedStateTest.test_state_dir_own_and_shared_read_last` | 114 | kapsam dışı | yok | ikinci örnekte ortak dosya yazma yasağı (TBD#412). İz: W1-pre sağlayıcı (rs/prov); canlıya T4; W0-a durum (rs/state) |

### `py/tests/test_snapshot_db.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_snapshot_db.py::SnapshotDbTest.test_db_ready` | 29 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_snapshot_db.py::SnapshotDbTest.test_db_wins_over_corrupt_file_and_backs_up_on_write` | 32 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_snapshot_db.py::SnapshotDbTest.test_db_missing_file_missing_legacy_migrates_once` | 41 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_snapshot_db.py::SnapshotDbTest.test_corrupt_file_without_db_is_empty_not_legacy` | 45 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_snapshot_db.py::SnapshotDbTest.test_db_non_list_is_empty` | 53 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |

### `py/tests/test_split_names.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_split_names.py::SplitNames.test_comma_space_mixed_dedup_order` | 10 | kapsam dışı | yok | CLI ad listesi ayrıştırma. İz: T6 (CLI) |
| `test_split_names.py::SplitNames.test_empty` | 13 | kapsam dışı | yok | CLI ad listesi ayrıştırma. İz: T6 (CLI) |
| `test_split_names.py::SplitNames.test_cli_commands_use_it` | 17 | kapsam dışı | yok | CLI ad listesi ayrıştırma. İz: T6 (CLI) |

### `py/tests/test_state_backend_last_good.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_state_backend_last_good.py::BackendLastGood.test_corrupt_or_unreadable_keeps_last_good` | 30 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_state_backend_last_good.py::BackendLastGood.test_missing_file_is_files` | 38 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_state_backend_last_good.py::BackendLastGood.test_corrupt_from_start_is_files` | 43 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |

### `py/tests/test_state_instances_cache_copy.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_state_instances_cache_copy.py::CacheCopy.test_db` | 52 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_state_instances_cache_copy.py::CacheCopy.test_files` | 55 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |

### `py/tests/test_state_instances_corrupt_mirror.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_state_instances_corrupt_mirror.py::CorruptMirror.test_db_row_serves_reads_and_writes_mirror_backed_up` | 57 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_state_instances_corrupt_mirror.py::CorruptMirror.test_no_row_refused` | 70 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_state_instances_corrupt_mirror.py::CorruptMirror.test_dirty_refused` | 74 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_state_instances_corrupt_mirror.py::CorruptMirror.test_db_unreadable_refused` | 80 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_state_instances_corrupt_mirror.py::CorruptMirror.test_bad_db_doc_refused` | 87 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_state_instances_corrupt_mirror.py::CorruptMirrorDual.test_db_row_serves_reads_and_writes_mirror_backed_up` | 97 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |

### `py/tests/test_state_instances_db_version_cache.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_state_instances_db_version_cache.py::DbVersionCache.test_unchanged_doc_parsed_once_and_change_seen` | 49 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_state_instances_db_version_cache.py::DbVersionCache.test_returned_dict_is_a_copy` | 58 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_state_instances_db_version_cache.py::DbVersionCache.test_delete_and_recreate_with_same_version_seen` | 63 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_state_instances_db_version_cache.py::DbVersionCache.test_dirty_mirror_not_cached` | 70 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_state_instances_db_version_cache.py::DbVersionCache.test_db_read_failure_fallback_not_cached` | 78 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |

### `py/tests/test_statedocs.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_statedocs.py::StateDocsTests.test_files_mode_never_touches_db` | 26 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_dual_writes_both_and_reads_db` | 32 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_lazy_import_from_file` | 39 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_db_mode_db_is_truth_file_is_mirror` | 44 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_db_mode_reader_mid_write_sees_db_no_drift` | 52 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_db_write_failure_recovers_from_file_on_next_read` | 61 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_dual_db_write_failure_resyncs_on_next_read` | 69 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_steward_prefix_is_db_ready` | 77 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_db_failure_falls_back_to_file` | 82 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_backend_from_settings_and_default` | 94 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_outside_claudeops_dir_is_files_only` | 100 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_file_truth_dual_heals_drift_and_survives_hand_edit` | 106 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_first_import_is_not_logged_as_drift` | 114 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_dual_skips_db_compare_when_file_unchanged` | 124 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs.py::StateDocsTests.test_mirror_log_modes` | 131 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |

### `py/tests/test_statedocs_hosts_diag.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_statedocs_hosts_diag.py::HostsDiagDual.test_hosts_dual_roundtrip_and_perm` | 21 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs_hosts_diag.py::HostsDiagDual.test_hosts_hand_edit_wins_in_dual` | 27 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs_hosts_diag.py::HostsDiagDual.test_hosts_db_mode_without_file` | 32 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs_hosts_diag.py::HostsDiagDual.test_diag_log_mirrors` | 38 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |

### `py/tests/test_statedocs_writers.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_statedocs_writers.py::WritersShadowTests.test_name_for` | 21 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs_writers.py::WritersShadowTests.test_steward_save_load_shadow` | 25 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs_writers.py::WritersShadowTests.test_steward_corrupt_backup_kept_and_db_recovers` | 31 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs_writers.py::WritersShadowTests.test_non_ready_docs_stay_file_even_in_db_mode` | 39 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs_writers.py::WritersShadowTests.test_ready_docs_db_only_in_db_mode` | 47 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs_writers.py::WritersShadowTests.test_mocked_writer_never_touches_db_or_file` | 53 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_statedocs_writers.py::WritersShadowTests.test_instances_shadow` | 63 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |

### `py/tests/test_steward_api_recovery.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_api_recovery.py::KindTest.test_classification` | 26 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::KindTest.test_network_and_cut_responses_are_retry` | 40 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::KindTest.test_brain_eai_again_gets_nudged` | 53 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::SingleSessionTest.test_backoff_nudges_then_giveup` | 62 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::SingleSessionTest.test_recovery_clears_state_and_new_error_resets` | 84 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::SingleSessionTest.test_untouched_when_busy_subagent_recent_activity_fatal_or_skipped` | 91 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::OutageTest.test_outage_single_notice_probe_then_grouped_wake` | 103 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::OutageTest.test_exhausted_outage_gives_up_instead_of_staying_silent` | 129 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::OutageTest.test_closed_probe_session_is_not_a_recovery` | 140 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::OutageTest.test_two_sessions_is_an_outage_one_is_not` | 148 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::PlanTickIntegrationTest.test_state_keys_absent_when_clean_and_present_when_stuck` | 156 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::PlanTickIntegrationTest.test_observe_mode_does_not_apply_nudge` | 167 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::ApplyTest.test_nudge_sends_devam_to_tmux_session` | 184 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::ApplyTest.test_nudge_refused_when_not_tmux_or_not_running` | 195 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::ApplyTest.test_giveup_and_outage_only_notify` | 205 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::WokenButStuckTest.test_woken_still_stuck_is_renudged_then_gives_up` | 218 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_api_recovery.py::WokenButStuckTest.test_state_clears_after_giveup` | 242 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |

### `py/tests/test_steward_audit_p9.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_audit_p9.py::TestY1TransferredQuestionLink.test_old_link_with_the_previous_identity_still_finds_the_question_by_key` | 92 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestY1TransferredQuestionLink.test_fallback_needs_the_key_not_just_the_id` | 103 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestY1TransferredQuestionLink.test_find_question_any_prefers_the_stated_store` | 109 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestY1TransferredQuestionLink.test_cli_answer_reports_the_other_identity` | 116 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestY2JobsAck.test_ack_on_an_open_job_is_refused_and_the_result_is_still_delivered_later` | 133 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestY2JobsAck.test_ack_on_a_terminal_job_still_works` | 143 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestY2JobsAck.test_ack_on_an_unknown_state_is_refused_too` | 149 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestO1BrainCannotCreateProjects.test_brain_upsert_of_a_new_name_is_refused_but_existing_updates_work` | 158 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestO1BrainCannotCreateProjects.test_human_may_still_create_a_project` | 169 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestO1BrainCannotCreateProjects.test_brain_refusal_applies_in_other_identities_and_the_mcp_tool_marks_the_actor` | 174 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestO2UnknownRemoteState.test_an_unknown_state_stays_open_keeps_polling_and_is_logged_once` | 197 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestO2UnknownRemoteState.test_known_states_unchanged` | 212 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestO3TransferWriteOrder.test_failure_writing_the_destination_leaves_everything_at_the_source` | 242 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestO3TransferWriteOrder.test_failure_writing_the_source_leaves_the_name_in_both_places_and_loses_nothing` | 252 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestO3TransferWriteOrder.test_successful_transfer_unchanged` | 262 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestO4OrphanBrain.test_degnekci_family_without_an_owner_is_another_brain_not_adhoc` | 274 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestO4OrphanBrain.test_remove_refuses_while_the_identity_brain_runs` | 281 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestD5LockTimeoutAfterSend.test_lock_timeout_while_recording_the_directive_does_not_unmark_the_delivery` | 314 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestD5LockTimeoutAfterSend.test_a_single_lock_timeout_on_the_delivery_mark_is_retried` | 324 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestD5LockTimeoutAfterSend.test_persistent_lock_timeout_on_the_mark_is_logged_not_raised` | 338 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestD5LockTimeoutAfterSend.test_next_tick_does_not_resend_what_already_went_out` | 347 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestD5LockTimeoutAfterSend.test_job_delivery_mark_timeout_is_not_raised_either` | 364 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestD8TransferTargetMustBeConfigured.test_unconfigured_target_is_refused_without_creating_a_directory` | 378 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_audit_p9.py::TestD8TransferTargetMustBeConfigured.test_configured_target_and_default_still_work` | 385 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |

### `py/tests/test_steward_brain.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_brain.py::TestDefaultClaudeMdGolden.test_default_output_is_byte_identical_to_pre_p5` | 62 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestDefaultClaudeMdGolden.test_identity_section_only_for_non_default` | 71 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestWorkspace.test_default_workspace_claude_md_is_unchanged_and_not_rewritten` | 144 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestWorkspace.test_default_persona_override_still_applies` | 157 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestWorkspace.test_identity_workspace_is_separate_with_identity_and_model_rule` | 163 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestWorkspace.test_identity_persona_falls_back_to_shared` | 180 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainMcp.test_verify_uses_connect_heartbeat` | 193 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainMcp.test_start_without_mcp_restarts_once_then_gives_up` | 201 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainMcp.test_start_defaults_to_new_conversation` | 216 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainMcp.test_close_note_written_without_model_turn` | 223 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainMcp.test_notools_verdict_pure` | 231 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainMcp.test_recover_restarts_once_with_cooldown` | 249 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainMcp.test_mcp_server_heartbeat_hook` | 265 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainMcp.test_touch_records_call_and_connect` | 274 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainStart.test_brain_spec_default_is_the_old_command_line` | 282 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainStart.test_disabled_identity_never_starts_a_brain` | 289 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainStart.test_enabled_identity_starts_its_own_brain` | 306 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainStart.test_default_brain_start_is_unchanged` | 324 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainStart.test_running_brain_is_not_started_twice` | 338 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestBrainStart.test_brain_stop_uses_only_the_act_stop_path_with_the_exact_name` | 345 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestClaudeMcpConfigFile.test_identity_gets_its_own_config_file` | 353 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestMcpIdentity.test_default_server_adds_nothing` | 379 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestMcpIdentity.test_identity_server_adds_it_to_every_call_and_the_brain_cannot_change_it` | 390 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestMcpIdentity.test_run_validates_the_identity_and_sets_it` | 420 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestMcpIdentity.test_cli_parses_the_flag` | 433 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestCtxFor.test_resolution` | 445 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestCtxFor.test_unknown_identity_is_an_explicit_error_and_writes_nothing` | 456 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestCtxFor.test_no_param_means_default_and_old_callers_work` | 467 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestCtxFor.test_requests_reach_the_right_store` | 475 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestCtxFor.test_manual_tick_and_note_and_skip_use_the_identity` | 501 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestHumanGate.test_human_in_default_context_is_unrestricted` | 532 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestHumanGate.test_human_in_other_context_only_own_projects_and_brain` | 542 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestHumanGate.test_brain_in_identity_context` | 554 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_brain.py::TestHumanGate.test_reads_are_limited_to_own_projects_outside_default` | 563 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |

### `py/tests/test_steward_core_a.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_core_a.py::StoreTest.test_project_roundtrip_and_validation` | 56 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::StoreTest.test_defer_answer_keeps_question_open` | 67 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::StoreTest.test_questions_dedup_answer_deliver` | 76 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::StoreTest.test_ideas_and_log` | 88 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::StoreTest.test_persona_override_and_bundled` | 99 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::MarkerTest.test_scan_markers_ask_ending_with_colon_takes_following_lines` | 105 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::MarkerTest.test_scan_markers_ignores_writing_examples` | 117 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::MarkerTest.test_scan_markers_ignores_inline_code_mention_in_prose` | 126 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::MarkerTest.test_scan_markers_job_line` | 135 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::MarkerTest.test_scan_markers` | 152 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::PromptTest.test_directive_by_phase_and_answer` | 167 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::PromptTest.test_tour_prompt_lists_items_and_end_marker` | 182 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::PromptTest.test_workspace_claude_md` | 192 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_handover_then_respawn` | 206 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_handover_grace_expiry_and_gone_session` | 222 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_markers_once_per_reply` | 230 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_done_marker_stops_session` | 240 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_done_confirmed_with_open_owner_question_pauses_not_done` | 244 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_done_marker_ignored_when_project_notes_have_no_done_tag` | 255 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_due_projects_respect_slots_priority_and_cadence` | 261 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_todo_change_opens_active_project_without_waiting_cadence` | 274 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_todo_change_reopens_done_project_to_planned` | 292 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_todo_change_paused_project_asks_owner_once_per_day` | 303 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_first_observation_done_project_with_open_work_goes_planned` | 318 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_daily_sweep_done_project_with_unchanged_sha` | 327 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_daily_sweep_paused_asks_once` | 339 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_only_fable_cila_open_work_does_not_trigger` | 347 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_drain_starts_nothing_but_keeps_answers_and_running` | 354 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_slot_pressure_stops_idle_session` | 361 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_answer_delivery_running_busy_or_stopped` | 372 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_adhoc_session_answer_goes_to_asking_session_only_if_running` | 382 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_adhoc_session_answer_waits_for_running_subagent` | 394 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_instance_sessions_map_to_blueprint_project` | 401 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_tour_only_when_brain_idle_and_due` | 407 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RulesTest.test_phase_model_effort` | 423 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::CardCoreTest.test_build_raw_card_reads_doc_heads_and_git` | 431 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::CardCoreTest.test_raw_card_without_git_or_docs` | 447 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::CardCoreTest.test_parse_card_json_variants` | 459 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::CardCoreTest.test_make_card_falls_back_to_raw_fields` | 472 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::CardCoreTest.test_refresh_reason_matrix_and_failure_backoff` | 490 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::CardCoreTest.test_store_stale_and_listing` | 513 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::CardCoreTest.test_model_pick_prompt_and_tour_rendering` | 524 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::OneshotProviderTest.test_claude_argv_shape_and_unsupported_default` | 541 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::OneshotProviderTest.test_ucli_oneshot_uses_chat_once_without_key_in_argv` | 567 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::OneshotProviderTest.test_oneshot_runs_argv_and_reports_failures` | 586 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::SimilarAnswersTest.test_ranks_by_similarity_and_excludes_self` | 611 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::SimilarAnswersTest.test_open_or_unanswered_ignored_and_prompt_renders` | 620 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::RosterGateTest.test_active_phase_needs_roster_but_idea_does_not` | 629 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::ScanCacheTest.test_scan_is_cached_inside_a_scope_and_invalidated_by_start` | 643 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::EngineSmallsTest.test_fail_logged_is_pruned_and_thread_safe` | 670 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::EngineSmallsTest.test_shutdown_blockers_survive_corrupt_jobs_file` | 680 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::ShutdownOnlyLeavesPausedTest.test_done_records_left_paused_and_warns` | 692 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::BrainCannotPauseTest.test_brain_cannot_pause_or_done_but_owner_can` | 712 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::ShutdownPlanTest.test_waits_for_quiet_then_handover_then_stop_then_brain` | 728 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::ShutdownPlanTest.test_subagent_blocks_and_timeouts_leave_session_open` | 756 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::ShutdownPlanTest.test_stale_ready_text_before_handover_does_not_count` | 769 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::ReviewFindings20261029Test.test_job_requests_for_different_files_are_not_merged` | 780 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::ReviewFindings20261029Test.test_done_and_plan_ready_in_prose_are_ignored` | 786 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::ReviewFindings20261029Test.test_owner_only_bare_number_after_token_stays_owner` | 794 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::ReviewFindings20261029Test.test_owner_only_false_positives` | 802 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::OpenQuestionMergeTest.test_paraphrased_open_question_is_merged` | 813 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::OpenQuestionMergeTest.test_other_project_or_topic_not_merged` | 823 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::OpenQuestionMergeTest.test_short_distinct_questions_not_merged` | 829 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::OpenQuestionMergeTest.test_routine_question_promoted_when_asked_to_owner` | 834 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::OpenQuestionMergeTest.test_answered_question_not_merged_into_open_path` | 849 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TopicMergeTest.test_topic_tokens` | 866 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TopicMergeTest.test_generic_names_alone_do_not_match` | 871 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TopicMergeTest.test_open_question_rephrased_is_merged_and_keeps_old_text` | 876 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TopicMergeTest.test_hold_answer_suppresses_same_topic` | 888 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TopicMergeTest.test_non_hold_answer_lets_new_decision_open` | 895 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TopicMergeTest.test_old_open_question_outside_window_not_merged` | 902 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TopicMergeTest.test_other_project_not_merged` | 910 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::SalientReaskTest.test_paraphrased_same_topic_is_duplicate` | 920 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::SalientReaskTest.test_different_topic_not_duplicate` | 925 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneDeferralTest.test_done_deferred_while_subagent_then_applied` | 931 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneDeferralTest.test_deferred_done_dropped_when_no_done_tag_added_later` | 942 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneDeferralTest.test_done_immediate_without_subagent` | 953 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::AnswerStartPhaseTest.test_active_phase_starts` | 967 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::AnswerStartPhaseTest.test_owner_answer_reopens_paused_and_done_project` | 970 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::NegativeAnswerTest.test_is_negative_answer` | 978 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::NegativeAnswerTest.test_negative_answer_does_not_reopen` | 990 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::NegativeAnswerTest.test_hold_answers_real_texts_do_not_reopen` | 995 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::NegativeAnswerTest.test_open_answer_to_sweep_with_running_session_sets_planned` | 1006 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::NegativeAnswerTest.test_sweep_question_has_options` | 1021 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::HeldInstructionAnswerTest.test_long_owner_instruction_reaches_brain` | 1048 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::HeldInstructionAnswerTest.test_second_held_instruction_gets_its_own_item` | 1057 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::HeldInstructionAnswerTest.test_later_question_does_not_overwrite_held_item` | 1062 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::HeldInstructionAnswerTest.test_short_hold_brain_and_routine_answers_stay_silent` | 1069 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneHandoverTest.test_done_hands_over_then_stops_never_respawns` | 1093 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneHandoverTest.test_session_gone_during_done_handover_is_not_respawned` | 1104 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneHandoverTest.test_grace_expiry_still_stops` | 1110 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneHandoverTest.test_small_context_skips_handover` | 1117 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneHandoverTest.test_switch_off_is_old_direct_stop` | 1125 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneHandoverTest.test_owner_answer_stops_reasking_and_bitti_closes` | 1131 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneHandoverTest.test_unknown_open_work_symlinked_worktree_accepts_proof` | 1145 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneHandoverTest.test_unanswered_conflict_still_asks` | 1152 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneConfirmTest.test_plain_done_asks_for_confirmation_and_keeps_phase` | 1169 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneConfirmTest.test_second_plain_done_does_not_spam_but_ttl_reasks` | 1177 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneConfirmTest.test_confirmed_with_evidence_sets_done_and_stops` | 1185 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneConfirmTest.test_confirmed_without_evidence_is_not_done` | 1190 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneConfirmTest.test_confirmed_but_local_open_work_asks_owner_not_done` | 1196 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneConfirmTest.test_no_steward_done_tag_ignores_both_markers` | 1208 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneConfirmTest.test_confirm_marker_is_not_plain_done_and_placeholder_ignored` | 1214 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneConfirmTest.test_subagent_active_defers_confirmed` | 1222 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneConfirmTest.test_open_work_of_counts_local_todo` | 1227 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::DoneConfirmTest.test_open_tbd_of_falls_back_to_main_worktree` | 1242 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TourQuietTest.test_skipped_unchanged_item_stays_out_until_state_changes_or_ttl` | 1272 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TourQuietTest.test_plan_tick_records_tour_sig_and_honors_skip_seen` | 1286 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TourQuietTest.test_stale_undelivered_answer_closed_not_toured` | 1300 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TourQuietTest.test_projectless_answer_closes_when_brain_never_runs` | 1315 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TourQuietTest.test_brain_question_answer_goes_to_live_session_named_by_project` | 1329 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TourQuietTest.test_keepwarm_ok_does_not_change_the_item_signature_and_routine_carries_age` | 1339 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TourQuietTest.test_observe_tour_does_not_burn_blocked_tour_budget` | 1353 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TourQuietTest.test_pending_count_is_the_full_list_even_when_a_tour_is_sent` | 1369 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TourQuietTest.test_count_open_tbd_new_format_needs_an_AÇIK_heading` | 1380 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TourQuietTest.test_shutdown_unknown_activity_waits_unless_idle` | 1386 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::TourQuietTest.test_blocked_item_closed_after_max_tours_not_urgent_again` | 1394 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::IdleSkipTest.test_no_idle_item_for_waiting_or_done_projects` | 1419 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::MergedAnswersTest.test_planner_merges_same_session_answers_in_one_action` | 1435 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::MergedAnswersTest.test_answer_waits_while_subagent_active` | 1443 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::MergedAnswersTest.test_subagent_active_for_reads_mtime` | 1451 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::MergedAnswersTest.test_compact_answer_directive_drops_preamble` | 1468 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_a.py::MergedAnswersTest.test_directive_contains_all_answers` | 1484 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |

### `py/tests/test_steward_core_b.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_core_b.py::ScanTicksTest.test_leading_code_tick_in_question_kept` | 56 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ScanTicksTest.test_wrapped_marker_and_wrapped_body` | 60 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::PlanMarkersTest.test_records_asks_and_ideas_only` | 71 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::PlanMarkersTest.test_same_reply_not_rescanned_and_routine_needs_question_mark` | 77 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::PlanMarkersTest.test_matches_plan_tick_marker_actions` | 84 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ObserveCoreTest.test_filter_act_passes_everything_and_clears_traces` | 93 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ObserveCoreTest.test_filter_observe_splits_dedups_and_prunes` | 100 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ObserveCoreTest.test_observed_visit_paces_due_projects_across_ticks` | 117 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::SummaryCoreTest.test_daily_summary_counts_and_filters_by_date` | 138 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::SummaryCoreTest.test_summary_due` | 171 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::SummaryCoreTest.test_log_reader_and_summary_text` | 179 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::SummaryCoreTest.test_compact_log_folds_ticks_and_keeps_summary_identical` | 195 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::SummaryCoreTest.test_missed_summary_dates_and_catch_up` | 236 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::RoutineQuestionTest.test_marker_scan_and_session_reply_opens_routine_ask` | 277 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::RoutineQuestionTest.test_routine_goes_to_brain_tour_not_phone_and_escalates_late` | 288 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::RoutineQuestionTest.test_brain_answer_is_delivered_like_any_answer` | 313 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::OneLiveSessionPerProjectTest.test_finished_handover_of_second_session_stops_it_instead_of_respawn` | 320 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::OneLiveSessionPerProjectTest.test_economy_rules_only_touch_managed_sessions` | 333 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::OneLiveSessionPerProjectTest.test_brain_respawn_after_handover_is_a_new_conversation` | 346 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::OneLiveSessionPerProjectTest.test_context_tokens_trigger_handover` | 354 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::OneLiveSessionPerProjectTest.test_line_count_is_only_a_fallback_and_ignores_young_sessions` | 369 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::OneLiveSessionPerProjectTest.test_workspace_claude_md_carries_the_permanent_model_rule` | 392 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::OneLiveSessionPerProjectTest.test_fable_sessions_use_the_lower_context_threshold` | 401 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::OneLiveSessionPerProjectTest.test_context_tokens_from_transcript_tail` | 417 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::StuckBrainTest.test_status_sentence_is_not_a_routine_question_and_tour_is_capped` | 436 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::StuckBrainTest.test_two_failed_tours_restart_the_brain` | 449 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::StuckBrainTest.test_undeliverable_adhoc_answer_is_given_up` | 464 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::DeliveryTargetTest.test_prefers_asking_session_then_main_over_experiment_sessions` | 477 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ReaskTest.test_similar_answered_question_is_redelivered_not_reopened` | 500 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ReaskTest.test_repeat_cap_other_project_old_and_clarification_open_new` | 510 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ReaskTest.test_answered_routine_question_asked_to_owner_opens_new` | 521 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ReaskTest.test_directive_lists_earlier_answers` | 531 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::QuestionOptionsTest.test_options_normalize_resolve_and_key` | 542 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::QuestionOptionsTest.test_notification_text_and_page_html` | 571 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::SettingsTest.test_defaults_parse_and_clamp` | 596 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::McpTest.test_tools_list_and_dispatch_cover_each_other` | 619 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::McpTest.test_tool_calls_hit_expected_endpoints` | 631 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::JobMarkerParseTest.test_hyphenated_kind_and_malformed_body_are_not_dropped` | 653 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::JobMarkerParseTest.test_prose_mentions_and_placeholders_still_ignored` | 659 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::QuestionPageHttpTest.test_question_page_round_trip` | 693 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::QuestionPageHttpTest.test_notify_phone_sets_click_header` | 716 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::BrainAuthorityAndDeferTest.test_non_routine_question_is_owner_only` | 743 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::BrainAuthorityAndDeferTest.test_routine_owner_only_topics` | 749 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::BrainAuthorityAndDeferTest.test_commit_push_merge_build_deploy_are_not_owner_only` | 756 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::BrainAuthorityAndDeferTest.test_blocked_marker_goes_to_brain_not_owner` | 763 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::BrainAuthorityAndDeferTest.test_rules_text_no_longer_reserves_commit_push_for_owner` | 768 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::BrainAuthorityAndDeferTest.test_readonly_job_request_not_owner_only` | 773 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::BrainAuthorityAndDeferTest.test_held_answer_item_with_owner_words_is_answerable` | 784 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::BrainAuthorityAndDeferTest.test_plain_routine_is_answerable` | 796 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::BrainAuthorityAndDeferTest.test_defer_reason` | 800 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::BrainAuthorityAndDeferTest.test_tour_retry_gap_after_deferral` | 806 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::TourDeliveryTest.test_short_tour_inline` | 811 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::TourDeliveryTest.test_long_tour_goes_to_file_and_old_files_pruned` | 817 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ShutdownKeepModeTest.test_keep_does_not_stop` | 843 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ShutdownKeepModeTest.test_default_stops` | 848 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ShutdownOnlyTest.test_only_closes_selected_project_and_leaves_rest` | 857 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ShutdownBlockersTest.test_quiet_session_without_blocker_gets_handover` | 880 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ShutdownBlockersTest.test_blocked_session_waits_and_records_reason` | 884 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ShutdownBlockersTest.test_blocked_session_left_open_after_wait_max` | 891 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::SmartTickTest.test_count_open_tbd` | 905 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::SmartTickTest.test_routine_question_skips_tour_interval` | 910 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::SmartTickTest.test_done_confirmed_with_open_tbd_asks_owner` | 925 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::SmartTickTest.test_tbd_only_question_counts_once` | 937 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::SmartTickTest.test_tbd_only_project_not_started_owner_asked_once` | 951 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::SmartTickTest.test_brain_stopped_project_not_restarted_by_cadence_until_cooldown` | 961 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::SmartTickTest.test_idle_session_without_open_todo_not_nudged` | 973 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::AskStatusLineTests.test_status_lines_do_not_open_records` | 986 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::AskBaseTests.test_dated_session_name_collapses_to_base` | 996 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::DeferAnswerTests.test_is_defer_answer` | 1007 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::DeferAnswerTests.test_digest_hides_deferred_until_expiry` | 1013 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::StartDecisionEventTests.test_event_shape` | 1021 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ExpiredHandoverNoteTest.test_note_helper` | 1033 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ExpiredHandoverNoteTest.test_expired_without_marker_carries_note` | 1047 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::ExpiredHandoverNoteTest.test_ready_marker_has_no_card_note` | 1052 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::UcliStuckLadderTest.test_shorten_helper` | 1066 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::UcliStuckLadderTest.test_ladder` | 1073 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::RemoteRespawnNoteTest.test_note_reaches_directive` | 1100 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_core_b.py::RemoteRespawnNoteTest.test_no_note_keeps_empty_directive` | 1105 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |

### `py/tests/test_steward_ctx.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_ctx.py::ContextQuestionTest.test_classifier` | 71 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::ContextQuestionTest.test_low_context_continues_without_handover` | 76 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::ContextQuestionTest.test_high_context_hands_over` | 86 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::ContextQuestionTest.test_unknown_context_or_disabled_leaves_question` | 95 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::ContextQuestionTest.test_over_threshold_single_handover` | 101 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::PausedProjectNoContextHandoverTest.test_paused_over_threshold_sends_no_handover_on_any_tick` | 119 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::PausedProjectNoContextHandoverTest.test_done_project_also_gets_no_threshold_handover` | 127 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::PausedProjectNoContextHandoverTest.test_planned_project_still_hands_over_at_threshold` | 131 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::PausedProjectNoContextHandoverTest.test_context_question_on_paused_project_does_not_start_a_handover` | 136 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::HandoverDeferTest.test_pure_decision` | 158 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::HandoverDeferTest.test_subagent_active_defers_then_hands_over_when_quiet` | 172 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::HandoverDeferTest.test_busy_and_unknown_defer` | 195 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::HandoverDeferTest.test_history_fallback_defers_too` | 206 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::HandoverDeferTest.test_force_by_ratio` | 212 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::HandoverDeferTest.test_force_by_time` | 222 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::HandoverDeferTest.test_defer_disabled_keeps_old_behaviour` | 234 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::HandoverDeferTest.test_below_threshold_drops_deferral` | 240 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::HandoverDeferTest.test_brain_same_rule` | 246 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::HandoverDeferTest.test_no_second_action_while_deferred` | 257 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::HandoverDeferTest.test_context_question_path_defers` | 267 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ctx.py::HandoverDeferTest.test_engine_logs_deferral` | 282 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |

### `py/tests/test_steward_generic.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_generic.py::TestConfig.test_generic_defaults_to_sonnet_medium` | 45 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestConfig.test_own_block_is_the_owners_explicit_choice` | 55 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestConfig.test_default_can_never_be_generic` | 61 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestCreate.test_http_create_with_role_generic` | 67 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestCreate.test_cli_create_with_role_generic` | 75 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestCreate.test_list_row_carries_role_generic` | 80 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestBrainMd.test_generic_section_only_for_generic` | 88 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestBrainMd.test_ensure_workspace_writes_generic_section` | 104 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestBacklog.test_classification` | 127 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestBacklog.test_empty_and_dedup_and_cap` | 133 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestBacklog.test_tour_prompt_renders_backlog_only_when_present` | 141 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestUpperTier.test_is_upper_tier` | 155 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestUpperTier.test_approval_is_specific_to_project_model_effort` | 161 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestUpperGate.test_brain_directive_to_opus_refused_and_question_opened_once` | 176 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestUpperGate.test_owner_approval_opens_the_gate` | 196 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestUpperGate.test_owner_rejection_keeps_it_closed` | 205 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestUpperGate.test_human_and_non_generic_are_free` | 213 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestUpperGate.test_restart_refused_before_stop` | 219 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestUpperGate.test_set_project_gate` | 225 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestUpperGate.test_register_gate_before_side_effects` | 237 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestDynamicProjects.test_remove_is_human_only_and_logged` | 246 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestDynamicProjects.test_cli_drop` | 254 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestDynamicProjects.test_panel_add_then_tick_treats_it_as_normal_project` | 260 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestTourBacklog.test_generic_tour_item_has_backlog` | 285 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_generic.py::TestTourBacklog.test_plain_steward_tour_is_unchanged` | 291 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |

### `py/tests/test_steward_ho_on_open.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_ho_on_open.py::ResumeLacksHoTest.test_work_without_ho_is_detected` | 51 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T4 (yaşam döngüsü) |
| `test_steward_ho_on_open.py::ResumeLacksHoTest.test_ho_done_is_clean` | 55 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T4 (yaşam döngüsü) |
| `test_steward_ho_on_open.py::ResumeLacksHoTest.test_new_request_after_ho_needs_ho_again` | 58 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T4 (yaşam döngüsü) |
| `test_steward_ho_on_open.py::ResumeLacksHoTest.test_empty_conversation_is_clean` | 62 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T4 (yaşam döngüsü) |
| `test_steward_ho_on_open.py::ResumeLacksHoTest.test_off_and_non_claude_and_ucli_record` | 65 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T4 (yaşam döngüsü) |
| `test_steward_ho_on_open.py::ResumeLacksHoTest.test_missing_jsonl` | 71 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T4 (yaşam döngüsü) |
| `test_steward_ho_on_open.py::EnsureRunningHoOnOpenTest.test_lacking_ho_resumes_then_hands_over` | 102 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T4 (yaşam döngüsü) |
| `test_steward_ho_on_open.py::EnsureRunningHoOnOpenTest.test_clean_open_no_handover` | 110 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T4 (yaşam döngüsü) |
| `test_steward_ho_on_open.py::EnsureRunningHoOnOpenTest.test_handover_failure_no_pending` | 116 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T4 (yaşam döngüsü) |

### `py/tests/test_steward_http.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_http.py::HttpTest.test_idea_export_project_todo_hides_idea_and_keeps_record` | 99 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_idea_export_all_tbd_and_idempotent` | 113 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_idea_export_appends_under_existing_heading_and_validates` | 123 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_running_names_resolve_digit_in_project_name` | 143 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_project_ask_answer_idea_note` | 156 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_ask_with_options_notifies_with_link_once` | 177 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_question_page_auth_and_answer_flow` | 201 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_register_creates_folder_goal_and_roster` | 229 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_tick_applies_actions_with_mocked_views` | 252 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_refresh_card_writes_summary_and_logs` | 290 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_refresh_card_failure_keeps_old_card_or_writes_raw` | 303 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_refresh_due_cards_rules` | 326 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_tick_runs_card_step_unless_disabled` | 349 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_respawn_marks_card_stale` | 365 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_cards_in_context_projects_and_api` | 378 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_observe_tick_records_would_and_touches_nothing` | 421 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_observe_still_runs_questions_ideas_and_phase_changes` | 443 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_act_mode_applies_and_logs_actions` | 461 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_brain_calls_are_dry_in_observe_but_cli_calls_apply` | 470 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_brain_cannot_touch_unregistered_session` | 502 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_brain_may_touch_brain_and_registered_projects` | 529 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_apply_gate_denies_engine_actions_on_unregistered_sessions` | 545 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_daily_summary_runs_once_after_hour_and_notifies` | 558 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_summary_api_and_cli` | 584 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::HttpTest.test_handover_route_marks_pending` | 609 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::JobRequestGateTest.test_gate_pure` | 622 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::JobRequestGateTest.test_brain_bare_devam_rejected_owner_allowed` | 634 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::JobRequestGateTest.test_brain_red_closes_and_opens_owner_question` | 642 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::JobRequestGateTest.test_red_feedback_to_project_session_and_no_repeat_owner_question` | 654 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::JobRequestGateTest.test_job_kinds_list_shapes` | 678 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::JobRequestGateTest.test_brain_answer_after_submit_ok` | 686 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::SkipMemoryHttpTest.test_skip_records_signature_from_last_tour` | 693 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::SkipMemoryHttpTest.test_close_stale_answer_action_marks_delivered` | 701 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::ActionJournalTest.test_crash_between_state_save_and_apply_replays_once` | 716 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::ActionJournalTest.test_normal_tick_leaves_no_journal_and_no_duplicates` | 734 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::ActionJournalTest.test_replay_skips_duplicate_idea` | 743 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::DryReportTest.test_report_counts_and_window` | 765 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::DryReportTest.test_ask_due_only_known_kip_after_72h_once` | 777 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::DryReportTest.test_maybe_dry_ask_opens_one_question_and_not_again` | 788 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::DryReportTest.test_no_ask_when_kip_already_act` | 798 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::BrainWakeGateTest.test_brain_directive_capped_per_day_separately_from_due` | 808 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::BrainWakeGateTest.test_brain_gate_dry_logs_would_and_sends` | 820 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::WakeGateTest.test_first_send_never_gated_then_repeat_dry_logs_but_sends_act_skips` | 836 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::WakeGateTest.test_gate_is_skipped_when_the_directive_just_opened_the_session` | 847 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::WakeGateTest.test_other_text_other_reason_answer_off_and_window` | 869 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::BigResumeTest.test_oversized_detection` | 904 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::BigResumeTest.test_small_unknown_other_cli_and_off_keep_resume` | 908 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::BigResumeTest.test_ensure_running_starts_fresh_for_big_context` | 919 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::WakeCapPanicTest.test_daily_cap_dry_and_act_and_reset_on_answer` | 935 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::WakeCapPanicTest.test_panic_flag_forces_observe_and_blocks_brain_directive` | 952 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::BlockedEscalationTest.test_blocked_waits_four_hours_routine_thirty_minutes` | 982 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::BlockedEscalationTest.test_owner_only_denial_escalates_routine_immediately` | 989 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::BlockedEscalationTest.test_owner_only_denial_blocks_brain_directive_until_answered` | 997 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::BlockedEscalationTest.test_owner_pending_block_pure` | 1016 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_http.py::BlockedEscalationTest.test_protocol_and_guide_derive_from_owner_topics` | 1023 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |

### `py/tests/test_steward_job_gate_and_qcap.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_job_gate_and_qcap.py::Verdict.test_real_request` | 18 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::Verdict.test_status_notes` | 22 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::Verdict.test_unknown_kind_and_no_service` | 28 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::Verdict.test_catalog_unreachable_skips_kind_check_only` | 32 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::Cap.test_open_question_cap_appends_extra` | 38 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::Cap.test_other_project_job_and_routine_unaffected` | 53 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::Cap.test_bare_choice_answers_only_main_and_reopens_extras` | 66 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::Cap.test_written_answer_closes_extras_too` | 80 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::Cap.test_answered_frees_slot` | 85 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::Gate.test_rejected_without_service_no_question` | 95 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::KindsCatalogue.test_parse_both_shapes` | 116 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::KindsCatalogue.test_closest_three` | 122 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::KindsCatalogue.test_format` | 128 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::KindsCatalogue.test_prompts_mention_catalogue` | 138 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::TourLoopSig.test_changing_items_do_not_trip` | 156 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::TourLoopSig.test_same_items_same_reply_trip` | 159 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_job_gate_and_qcap.py::GateMessage.test_note_has_catalogue_hint_file_rule_and_closest_kinds` | 164 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |

### `py/tests/test_steward_main_model.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_main_model.py::MainSessionModel.test_registered_fable_becomes_sonnet_medium` | 18 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::MainSessionModel.test_opus_and_empty_on_claude` | 21 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::MainSessionModel.test_non_claude_cli_untouched` | 25 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::MainSessionModel.test_remote_unknown_cli_only_claude_models` | 29 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::MainSessionModel.test_non_claude_model_on_claude_cli_untouched` | 34 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::MainSessionModel.test_no_sonnet_known_is_noop` | 37 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::MainModelFromSettings.test_empty_setting_gives_sonnet_medium` | 66 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::MainModelFromSettings.test_setting_wins_and_can_switch_to_opus` | 71 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::MainModelFromSettings.test_invalid_setting_falls_back_to_sonnet` | 75 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::MainModelFromSettings.test_no_sonnet_in_list_falls_back_to_provider_default` | 79 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::RemoteBlankModel.test_blank_model_on_claude_row_sends_main_default` | 109 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::RemoteBlankModel.test_blank_model_with_leftover_effort` | 112 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::RemoteBlankModel.test_settings_can_revert` | 115 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::RemoteBlankModel.test_non_claude_cli_gets_no_claude_model` | 119 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::RemoteBlankModel.test_non_claude_cli_with_claude_record_is_untouched` | 122 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::RemoteBlankModel.test_unknown_cli_keeps_old_behaviour` | 125 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_main_model.py::RemoteBlankModel.test_respawn_sends_main_default` | 129 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |

### `py/tests/test_steward_open_dialog.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_open_dialog.py::Transcript.test_unanswered_question_is_open` | 39 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Transcript.test_answer_or_dismissal_closes_and_is_owner_input` | 46 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Transcript.test_later_turn_or_typed_prompt_closes_an_orphan` | 50 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Transcript.test_noise_is_not_owner_input` | 54 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Plan.test_threshold_handover_is_never_typed_into_a_dialog` | 78 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Plan.test_expired_grace_waits_while_dialog_open_and_records_once` | 84 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Plan.test_grace_restarts_when_the_owner_answers` | 94 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Plan.test_done_close_is_retried_after_the_dialog` | 118 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Plan.test_done_close_is_dropped_when_project_reopens` | 130 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Plan.test_deferred_done_close_survives_a_dialog` | 136 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Plan.test_pause_close_waits_for_the_dialog` | 145 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Plan.test_shutdown_does_not_type_into_a_dialog` | 153 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Plan.test_no_nudge_keepwarm_or_no_work_close` | 157 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Send.test_web_handover_refuses_while_dialog_open` | 170 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Send.test_refused_engine_handover_is_not_left_pending` | 181 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |
| `test_steward_open_dialog.py::Send.test_remote_facts_carry_the_dialog` | 196 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi); T1 (durum) |

### `py/tests/test_steward_owned.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_owned.py::SessionClassTest.test_unrecorded_project_is_own` | 27 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::SessionClassTest.test_recorded_name_own_other_name_manual` | 30 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::SessionClassTest.test_empty_record_means_every_session_is_manual` | 37 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::SessionClassTest.test_brain_never_manual` | 41 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::UpdateOwnedTest.test_first_sight_rules` | 48 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::UpdateOwnedTest.test_two_sessions_ambiguous_hands_off` | 53 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::UpdateOwnedTest.test_recorded_project_untouched` | 57 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::UpdateOwnedTest.test_seeding_needs_evidence` | 61 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::EvidenceTest.test_rules` | 73 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::PlanTickManualTest.test_manual_session_holds_project_no_start_no_handover` | 91 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::PlanTickManualTest.test_owned_dead_and_no_manual_starts` | 101 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::TargetAndEnsureTest.test_target_denies_manual_session` | 114 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::TargetAndEnsureTest.test_ensure_running_refuses_beside_manual_session` | 123 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::TargetAndEnsureTest.test_ensure_running_uses_owned_session` | 129 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::TargetAndEnsureTest.test_start_records_the_new_session` | 138 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::TargetAndEnsureTest.test_seed_request_seeds_by_evidence_once` | 152 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_owned.py::OwnedCliTest.test_set_and_clear` | 166 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |

### `py/tests/test_steward_remote_facts.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_remote_facts.py::TestFactsEndpoint.test_facts_for_exact_names` | 64 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestFactsEndpoint.test_non_claude_has_no_context_or_subagent` | 76 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestFactsEndpoint.test_codex_context_from_provider_live_context` | 81 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestFactsEndpoint.test_codex_background_work_reported` | 97 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestFactsEndpoint.test_no_names_gives_capabilities_only` | 103 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestFactsEndpoint.test_route_is_host_routed` | 107 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestExact.test_stop_exact_requires_full_name` | 132 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestExact.test_stop_without_exact_keeps_unique_base` | 138 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestExact.test_term_input_exact` | 142 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestExact.test_handover_exact_refuses_before_touching_session` | 149 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestExact.test_term_resolve_exact` | 153 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestClient.test_404_caches_api0_and_rechecks_after_ten_minutes` | 202 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestClient.test_404_is_not_a_transport_failure` | 217 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestClient.test_network_error_does_not_write_cache` | 225 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestClient.test_view_enriched_from_facts_single_request` | 235 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestClient.test_empty_facts_last_assistant_falls_back_to_term_chat_but_keeps_facts` | 249 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestClient.test_facts_missing_for_a_session_falls_back_to_term_chat` | 261 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestClient.test_old_host_keeps_a1_behavior` | 267 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |
| `test_steward_remote_facts.py::TestClient.test_enriched_view_clears_subagent_unknown` | 274 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür) ve uzak olgu ucu. İz: T10 (değnekçi); T5 (federasyon) |

### `py/tests/test_steward_ucli_idle.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_ucli_idle.py::IdleModeTest.test_off_produces_nothing` | 43 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::IdleModeTest.test_dry_plans_but_never_writes_handover_state` | 49 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::IdleModeTest.test_default_config_is_dry` | 61 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::FailedTurnChainTest.test_detect` | 68 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::FailedTurnChainTest.test_failed_turn_does_not_reset_chain` | 78 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::FailedTurnChainTest.test_successful_turn_still_resets_chain` | 102 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::GateWaitTest.test_gate_wait_text_detected` | 111 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::GateWaitTest.test_no_nudge_no_close_while_waiting_for_gate` | 118 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::GateWaitTest.test_old_gate_text_far_back_does_not_block` | 126 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::HelpersTest.test_one_line_folds_newlines` | 133 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::HelpersTest.test_threshold_by_cache_ttl` | 136 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::HelpersTest.test_next_work_hint` | 142 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::HelpersTest.test_finish_marker` | 151 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_nudge_with_next_work_single_line` | 160 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_below_threshold_nothing` | 167 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_threshold_follows_cache_ttl` | 170 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_configurable_threshold_and_off` | 175 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_no_work_no_marker_does_nothing` | 179 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_open_todo_alone_sends_no_blind_nudge` | 183 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_open_todo_still_counts_for_close_decisions` | 188 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_close_marker_with_work_requests_handover_then_reopen` | 192 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_close_marker_without_work_pauses_and_closes_after_handover` | 198 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_ready_for_handover_already_written` | 203 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_observe_does_not_touch_handover_state` | 210 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_skips` | 220 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_chain_limit_and_reset_on_activity` | 234 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_dry_counts_do_not_block_act` | 249 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::PlanTest.test_legacy_record_without_mode_counts_as_dry` | 259 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ApplyTest.test_nudge_is_sent_as_one_line` | 289 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ApplyTest.test_every_nudge_kind_carries_reply_language_line` | 294 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ApplyTest.test_long_nudge_keeps_reply_language_line` | 303 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ApplyTest.test_nudge_skipped_when_input_box_has_text` | 307 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ApplyTest.test_close_handover_pauses_project_when_no_work` | 313 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ApplyTest.test_close_handover_keeps_phase_when_work_remains` | 319 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ApplyTest.test_close_stop_and_respawn_use_existing_paths` | 323 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ApplyTest.test_turn_failed_close_stops_and_asks_owner_once` | 331 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ApplyTest.test_close_rejects_unknown_mode` | 340 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::DevamTextTest.test_clip_words_never_cuts_mid_word` | 350 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::DevamTextTest.test_next_hint_long_note_cut_on_word` | 359 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::DevamTextTest.test_same_devam_text_not_resent_after_answer` | 365 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ClaudeIdleTest.test_default_is_dry_and_ucli_untouched` | 393 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ClaudeIdleTest.test_nudges_after_threshold_with_next_work` | 399 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ClaudeIdleTest.test_off_and_zero_do_nothing` | 407 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ClaudeIdleTest.test_skips_busy_subagent_done_questions_no_work_paused` | 412 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ClaudeIdleTest.test_chain_cap` | 420 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::NotesWaitTest.test_notes_wait_detect` | 429 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::NotesWaitTest.test_due_project_with_bekleme_note_not_started_and_reason_recorded` | 434 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ChainPauseFlowTest.test_claude_idle_skips_owner_wait` | 453 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |
| `test_steward_ucli_idle.py::ChainPauseFlowTest.test_pause_written_only_after_handover_finishes` | 456 | kapsam dışı | yok | değnekçi mantığı (crate işlevleri yalnız sahte/fikstür). İz: T10 (değnekçi) |

### `py/tests/test_steward_ucli_send.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_ucli_send.py::UcliSendTest.test_ucli_text_folded_not_truncated` | 31 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::UcliSendTest.test_non_ucli_untouched_and_no_recheck` | 41 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::UcliSendTest.test_claude_trust_dialog_blocks_send` | 48 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::UcliSendTest.test_text_left_in_box_sends_one_more_enter` | 56 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::UcliSendTest.test_still_stuck_logs_error` | 66 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::UcliSendTest.test_stuck_event_uses_caller_sid` | 74 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::UcliSendTest.test_every_steward_send_call_passes_sid` | 82 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::UcliSendTest.test_late_drawn_text_gets_enter` | 92 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::UcliSendTest.test_empty_box_no_extra_enter` | 103 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::BoxTextTest.test_prefixed_empty_prompt` | 118 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::BoxTextTest.test_prefixed_with_text` | 121 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::BoxTextTest.test_text_wrapped_over_two_lines` | 124 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::BoxTextTest.test_waiting_for_response_is_empty` | 128 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::BoxTextTest.test_turn_output_after_prompt_is_empty` | 131 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::BoxTextTest.test_last_prompt_line_wins` | 134 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |
| `test_steward_ucli_send.py::BoxTextTest.test_no_prompt` | 137 | kapsam dışı | yok | ucli'ye metin gönderimi. İz: T2 (terminal); T10 (değnekçi) |

### `py/tests/test_steward_ui_api.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_steward_ui_api.py::UiConfigTest.test_config_writes_valid_int_and_mode` | 35 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiConfigTest.test_config_rejects_bad_values_and_unknown_fields` | 41 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiConfigTest.test_config_review_budgets_and_script_choice` | 47 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiConfigTest.test_brain_cannot_change_config_or_enable` | 60 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiConfigTest.test_drain_toggle_and_brain_directive_gate` | 64 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiConfigTest.test_enable_toggles` | 73 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiUpTest.test_up_enables_restores_and_starts_brain_but_brain_cannot` | 81 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiShutdownStateTest.test_state_exposes_shutdown_only_when_started` | 98 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiIdentityTest.test_create_validates_and_opens_off_observe` | 116 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiIdentityTest.test_brain_cannot_manage_identities` | 125 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiIdentityTest.test_remove_refuses_default_unknown_and_nonempty` | 130 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiIdentityTest.test_remove_refuses_while_review_job_runs` | 139 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiIdentityTest.test_remove_empty_identity` | 148 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiIdentityTest.test_transfer_moves_project_and_refuses_running` | 153 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::DirectiveDatedSessionTest.test_dated_session_gets_the_directive_without_a_start` | 192 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::DirectiveDatedSessionTest.test_two_live_sessions_are_ambiguous_and_nothing_starts` | 197 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiServiceJobTest.test_add_list_hides_token_and_rm` | 213 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiServiceJobTest.test_add_validates_and_brain_refused` | 224 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |
| `test_steward_ui_api.py::UiServiceJobTest.test_rm_refused_with_open_job_and_ack_only_terminal` | 232 | kapsam dışı | yok | değnekçi panel uçları. İz: T10 (değnekçi) |

### `py/tests/test_stop_with_handover.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_stop_with_handover.py::LocalTest.test_success_handover_then_exact_stop` | 62 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::LocalTest.test_handover_send_failure_does_not_stop` | 67 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::LocalTest.test_timeout_does_not_stop` | 73 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::LocalTest.test_unreadable_baseline_does_not_handover_or_stop` | 78 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::LocalTest.test_not_applicable_returns_none` | 88 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::LocalTest.test_english_message` | 94 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::ReaskTest.test_reask_then_ready` | 115 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::ReaskTest.test_reask_still_none_does_not_close` | 122 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_success_handover_then_forced_exact_stop` | 150 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_timeout_does_not_stop` | 157 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_handover_failure_does_not_stop` | 162 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_unreadable_baseline_does_nothing` | 167 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_not_applicable_returns_none` | 172 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_unreadable_host_does_not_stop` | 176 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteTest.test_each_outcome_is_logged` | 182 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteRepollTest.test_stale_cache_recovers_within_the_wait` | 212 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteRepollTest.test_stale_cache_gives_up_after_the_wait` | 217 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteRepollTest.test_twin_rows_are_ambiguous_without_waiting` | 222 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteRepollTest.test_ambiguous_message_in_both_languages` | 227 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RemoteFallbackTest.test_fallback_stop_is_exact_and_logged` | 237 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_without_ho_field_old_behaviour_byte_for_byte` | 312 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_force_with_ho_is_a_400_conflict_never_a_silent_plain_stop` | 318 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_exact_with_ho_still_hands_over_with_the_exact_flag` | 325 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_exact_with_ho_not_applicable_falls_back_to_exact_plain_stop` | 337 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_exact_without_ho_stays_plain_stop` | 345 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_remote_without_ho_goes_straight_to_proxy` | 349 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_ho_returns_pending_immediately_while_job_blocks` | 355 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_ho_failure_is_reported_and_never_plain_stops` | 361 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_ho_success` | 369 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_ho_not_applicable_falls_back_to_plain_stop_inside_the_job` | 376 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_second_ho_while_pending_does_not_start_second_job` | 383 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_remote_ho_runs_remote_helper_in_job` | 391 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_job_exception_becomes_error_with_force_hint` | 397 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |
| `test_stop_with_handover.py::RouteTest.test_status_unknown_after_restart_is_none` | 403 | kapsam dışı | yok | devir + kapatma. İz: T4 (yaşam döngüsü) |

### `py/tests/test_stopped_session_chat.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_stopped_session_chat.py::ClaudeSidForStoppedSessionTests.test_own_conversation_wins_over_a_newer_sibling_stub` | 80 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::ClaudeSidForStoppedSessionTests.test_each_sibling_resolves_to_its_own_file` | 86 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::ClaudeSidForStoppedSessionTests.test_same_title_prefers_the_real_conversation_over_a_newer_stub` | 95 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::ClaudeSidForStoppedSessionTests.test_same_title_picks_the_newest_real_conversation_even_when_it_is_the_smaller_one` | 101 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::ClaudeSidForStoppedSessionTests.test_all_stubs_returns_the_newest_one` | 107 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::ClaudeSidForStoppedSessionTests.test_a_large_file_counts_as_real_without_being_scanned` | 112 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::ClaudeSidForStoppedSessionTests.test_no_title_match_returns_none` | 119 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::ClaudeSidForStoppedSessionTests.test_title_is_an_exact_match_not_a_prefix` | 123 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::ClaudeSidForStoppedSessionTests.test_untitled_files_never_match` | 127 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::ClaudeSidForStoppedSessionTests.test_missing_project_dir_and_empty_name_return_none` | 131 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::ClaudeSidForStoppedSessionTests.test_file_recording_a_different_cwd_is_ignored` | 136 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::ClaudeSidForStoppedSessionTests.test_finds_a_file_older_than_the_resume_scan_limit` | 141 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::ClaudeSidForStoppedSessionTests.test_unchanged_files_are_not_reread_but_changed_ones_are` | 149 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::TermChatWiringTests.test_stopped_session_shows_its_own_full_history_not_the_newest_stub` | 177 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::TermChatWiringTests.test_stopped_session_last_exchange_is_its_own` | 182 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::TermChatWiringTests.test_incremental_since_still_works_on_the_resolved_conversation` | 186 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::TermChatWiringTests.test_unmatched_stopped_session_keeps_the_old_newest_in_cwd_behavior` | 192 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::TermChatWiringTests.test_live_session_never_consults_the_name_lookup` | 200 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::TermChatWiringTests.test_live_session_without_sid_is_left_alone_too` | 207 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::TermChatWiringTests.test_unsupported_cli_still_reports_supported_false` | 214 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::OtherProvidersTests.test_default_providers_do_not_guess` | 220 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::OtherProvidersTests.test_agy_uses_the_learned_name_to_sid_map_when_the_db_exists` | 224 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::OtherProvidersTests.test_ucli_sid_is_the_session_name` | 237 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::UcliChatTests.test_schema_header_row_is_skipped` | 258 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::UcliChatTests.test_header_only_file_means_no_messages_yet_not_unsupported` | 263 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::UcliChatTests.test_old_files_without_a_header_still_parse` | 267 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::UcliChatTests.test_corrupt_files_are_still_reported_as_unreadable` | 271 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::UcliChatTests.test_missing_file_is_an_empty_history` | 277 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_stopped_session_chat.py::UcliChatTests.test_stopped_ucli_instance_chat_is_served_through_term_chat` | 280 | kapsam dışı | yok | durmuş oturumun sohbeti. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |

### `py/tests/test_store_tsv.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_store_tsv.py::TsvTests.test_roundtrip_exact_and_rows` | 24 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_store_tsv.py::TsvTests.test_replace_overwrites_and_files_isolated` | 32 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_store_tsv.py::TsvTests.test_deleted_file_clears_shadow_and_empty_file_not_rewritten` | 38 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_store_tsv.py::TsvTests.test_shadow_syncs_on_change_only` | 50 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_store_tsv.py::TsvTests.test_files_mode_and_outside_dir_and_other_names_skip` | 58 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |
| `test_store_tsv.py::TsvTests.test_web_write_functions_shadow` | 67 | kapsam dışı | yok | durum dosyası/DB deposu ve durum dizini. İz: W0-a durum (rs/state) |

### `py/tests/test_stuck_kills_parent.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_stuck_kills_parent.py::RecoverStuckTest.test_uses_parent_aware_kill` | 13 | kapsam dışı | yok | takılan oturumu kurtarma. İz: T4 (yaşam döngüsü) |
| `test_stuck_kills_parent.py::RecoverStuckTest.test_unknown_permission_uses_provider_default` | 28 | kapsam dışı | yok | takılan oturumu kurtarma. İz: T4 (yaşam döngüsü) |
| `test_stuck_kills_parent.py::RecoverStuckTest.test_dry_run_kills_nothing` | 40 | kapsam dışı | yok | takılan oturumu kurtarma. İz: T4 (yaşam döngüsü) |
| `test_stuck_kills_parent.py::RecoverStuckTest.test_recovery_uses_live_model_and_effort_not_spawn_argv` | 46 | kapsam dışı | yok | takılan oturumu kurtarma. İz: T4 (yaşam döngüsü) |

### `py/tests/test_tmux_list_utf8.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_tmux_list_utf8.py::Utf8FlagArgvTests.test_tab_separated_queries_force_utf8` | 25 | kapsam dışı | yok | tmux liste sorgularında UTF-8 (TBD#366 P5). İz: W0-b tmux (rs/tmux) |
| `test_tmux_list_utf8.py::Utf8FlagArgvTests.test_other_queries_and_the_server_starting_spawn_do_not` | 30 | kapsam dışı | yok | tmux liste sorgularında UTF-8 (TBD#366 P5). İz: W0-b tmux (rs/tmux) |
| `test_tmux_list_utf8.py::CLocaleRealTmuxTests.test_client_session_and_ghost_are_found_in_the_c_locale` | 38 | kapsam dışı | yok | tmux liste sorgularında UTF-8 (TBD#366 P5). İz: W0-b tmux (rs/tmux) |

### `py/tests/test_triage_fixes_20261107.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_triage_fixes_20261107.py::RunDirTest.test_rejects_traversal` | 16 | kapsam dışı | yok | orkestrasyon koşu dizini. İz: T7 (periyodik+kullanım) |
| `test_triage_fixes_20261107.py::RunDirTest.test_normal_id_ok` | 21 | kapsam dışı | yok | orkestrasyon koşu dizini. İz: T7 (periyodik+kullanım) |
| `test_triage_fixes_20261107.py::HandoverDoneUserMessageTest.test_user_message_with_rfh_text_does_not_count` | 34 | karşılandı | `needs_ho.rs::only_assistant_rows_carry_the_marker`<br>`golden.rs::transcripts_needs_ho` | yok |
| `test_triage_fixes_20261107.py::HandoverDoneUserMessageTest.test_assistant_rfh_counts` | 38 | karşılandı | `needs_ho.rs::only_assistant_rows_carry_the_marker`<br>`golden.rs::transcripts_needs_ho` | yok |
| `test_triage_fixes_20261107.py::HandoverDoneUserMessageTest.test_non_assistant_row_types_with_rfh_do_not_count` | 43 | karşılandı | `needs_ho.rs::only_assistant_rows_carry_the_marker`<br>`golden.rs::transcripts_needs_ho` | yok |
| `test_triage_fixes_20261107.py::HandoverDoneUserMessageTest.test_real_rfh_after_blob_row_counts` | 50 | karşılandı | `needs_ho.rs::only_assistant_rows_carry_the_marker`<br>`golden.rs::transcripts_needs_ho` | yok |
| `test_triage_fixes_20261107.py::HostsDbNonListTest.test_db_mode_non_list_is_corrupt` | 56 | kapsam dışı | yok | host kaydı okuma. İz: W0-a durum (rs/state); T5 (federasyon) |

### `py/tests/test_ucli_agents.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_agents.py::TokenTests.test_concurrent_issue_keeps_file_and_digest_consistent` | 29 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::TokenTests.test_issue_writes_0600_file_and_only_hash_in_registry` | 48 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::TokenTests.test_reissue_invalidates_old_token_and_revoke_clears` | 56 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::TokenTests.test_children_get_no_token_and_garbage_rejected` | 65 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::TokenTests.test_trailing_newline_name_is_unsafe` | 71 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::TokenTests.test_revoke_unsafe_name_does_not_touch_files` | 75 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::ReserveTests.test_limit_two_live_and_names_sequential` | 84 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::ReserveTests.test_taken_names_skipped_and_depth_one` | 95 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::ReserveTests.test_fold_text` | 101 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::SettingsTests.test_defaults` | 112 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::SettingsTests.test_off_and_cost` | 117 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::ProviderSetupTests.test_no_port_or_child_or_off_gives_nothing` | 140 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::ProviderSetupTests.test_unsupported_binary_gives_nothing` | 149 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::ProviderSetupTests.test_enabled_returns_flag_and_env_without_token_value` | 155 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_agents.py::ProviderSetupTests.test_build_inner_command_keeps_token_out_of_argv` | 165 | kapsam dışı | yok | ucli alt ajan bayrak/env. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_ask_dir.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_ask_dir.py::AskDirTest.test_opts_default_off_and_ambiguous` | 27 | kapsam dışı | yok | ucli `--ask-dir`. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_ask_dir.py::AskDirTest.test_argv_has_private_dir_outside_workspace` | 33 | kapsam dışı | yok | ucli `--ask-dir`. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_ask_dir.py::AskDirTest.test_unsupported_binary_or_no_name_is_error` | 40 | kapsam dışı | yok | ucli `--ask-dir`. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_ask_dir.py::AskDirTest.test_pending_and_answer_roundtrip_and_stale_id` | 46 | kapsam dışı | yok | ucli `--ask-dir`. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_ask_dir.py::AskDirTest.test_bad_names_rejected` | 58 | kapsam dışı | yok | ucli `--ask-dir`. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_ask_dir.py::AskDirTest.test_broken_question_file_is_none` | 63 | kapsam dışı | yok | ucli `--ask-dir`. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_brain_mcp.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_brain_mcp.py::ValidateMaxCostTests.test_valid_values` | 53 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::ValidateMaxCostTests.test_zero_or_empty_drops_the_key` | 59 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::ValidateMaxCostTests.test_invalid_values_rejected` | 63 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::MaxCostArgsTests.test_priced_model_gets_the_flag_once` | 89 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::MaxCostArgsTests.test_unpriced_model_is_skipped_and_logged` | 95 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::MaxCostArgsTests.test_binary_without_flag_is_skipped` | 100 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::McpRegisterTests.test_server_name_follows_ucli_rule` | 113 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::McpRegisterTests.test_add_argv_shape` | 118 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::McpRegisterTests.test_launch_args_register_then_with_mcp` | 124 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::McpRegisterTests.test_failed_add_means_no_with_mcp` | 144 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::McpRegisterTests.test_nothing_runs_without_tools_workspace_or_flag` | 152 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::McpRegisterTests.test_symlinked_state_dir_is_refused` | 165 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::McpRegisterTests.test_steward_spec_allowlists_exactly_the_steward_tools` | 176 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::BuildWithMcpTests.test_only_with_mcp_is_taken_from_extra_args` | 204 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::BuildWithMcpTests.test_claude_service_with_cost_cap_and_mcp` | 210 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::SpawnCwdWiringTests.test_cwd_only_for_providers_that_ask` | 245 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::SpawnCwdWiringTests.test_dry_run_preview_shows_env_and_command_not_priority_prefix` | 265 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::SpawnCwdWiringTests.test_dry_run_preview_masks_secret_env_values` | 271 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::SpawnCwdWiringTests.test_dry_run_preview_caps_very_long_command` | 277 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::BrainUcliTests.test_default_claude_brain_passes_no_cli_opts` | 284 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::BrainUcliTests.test_ucli_brain_uses_claude_service_and_cost_cap` | 291 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::BrainUcliTests.test_settings_override_service_model_and_cap` | 303 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::BrainUcliTests.test_defaults` | 312 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::BrainUcliTests.test_unknown_service_refuses_without_spawn` | 319 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::BrainUcliTests.test_spawn_refusal_is_reported_not_raised` | 326 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |
| `test_ucli_brain_mcp.py::BrainUcliTests.test_claude_brain_value_error_still_raises` | 332 | kapsam dışı | yok | ucli MCP kaydı ve beyin argv'si. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T10 (değnekçi) |

### `py/tests/test_ucli_broad_glob_and_instr_check.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_broad_glob_and_instr_check.py::BroadGlobTests.test_broad_rejected_without_accept` | 19 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_broad_glob_and_instr_check.py::BroadGlobTests.test_broad_accepted_with_accept` | 26 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_broad_glob_and_instr_check.py::BroadGlobTests.test_narrow_glob_has_no_accept_flag` | 33 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_broad_glob_and_instr_check.py::BroadGlobTests.test_always_rejected_even_when_accepted` | 38 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_broad_glob_and_instr_check.py::BroadGlobTests.test_forbidden_cmds_never_open` | 42 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_broad_glob_and_instr_check.py::BroadGlobTests.test_grant_logged_in_apply` | 46 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_broad_glob_and_instr_check.py::InstructionsCheckTests.test_sizes` | 62 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_broad_glob_and_instr_check.py::InstructionsCheckTests.test_exact_limit_not_over` | 71 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_broad_glob_and_instr_check.py::InstructionsCheckTests.test_no_files_and_bad_cwd` | 76 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_broad_glob_and_instr_check.py::InstructionsCheckTests.test_symlink_escape_ignored` | 82 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_broad_glob_and_instr_check.py::InstructionsCheckTests.test_no_content_returned` | 88 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_capability_flags.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_capability_flags.py::CapabilityFlagsTest.test_default_off` | 27 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_capability_flags.py::CapabilityFlagsTest.test_image_scholar_independent_of_exec` | 36 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_capability_flags.py::CapabilityFlagsTest.test_false_values_dropped` | 43 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_capability_flags.py::CapabilityFlagsTest.test_invalid_value_is_error` | 48 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_capability_flags.py::CapabilityFlagsTest.test_net_and_unbounded_exec_own_not_offered` | 54 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_capability_flags.py::CapabilityFlagsTest.test_ask_edit_needs_write` | 62 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_capability_flags.py::CapabilityFlagsTest.test_exec_argv` | 69 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_capability_flags.py::CapabilityFlagsTest.test_unsupported_binary_refuses` | 76 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_capability_flags.py::CapabilityFlagsTest.test_unsupported_but_off_no_error` | 84 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_capability_flags.py::AskEditWithoutExecTest.test_ask_edit_added_only_with_allow_edit` | 96 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_checkpoint_flag.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_checkpoint_flag.py::CheckpointFlagTest.test_default_off` | 21 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checkpoint_flag.py::CheckpointFlagTest.test_false_values_dropped` | 27 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checkpoint_flag.py::CheckpointFlagTest.test_true_accepted` | 33 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checkpoint_flag.py::CheckpointFlagTest.test_ambiguous_is_error` | 38 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checkpoint_flag.py::CheckpointFlagTest.test_argv_added_once` | 42 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checkpoint_flag.py::CheckpointFlagTest.test_unsupported_binary_skipped_not_rejected` | 46 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_checks_isolation.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_checks_isolation.py::FilesWriteCannotReachChecks.test_write_text_forbidden_outside_project_root` | 17 | kapsam dışı | yok | kontrol kaydı dizini yazma yasağı. İz: T3 (dosya); T7 (periyodik+kullanım) |
| `test_ucli_checks_isolation.py::FilesWriteCannotReachChecks.test_default_root_not_under_any_project` | 30 | kapsam dışı | yok | kontrol kaydı dizini yazma yasağı. İz: T3 (dosya); T7 (periyodik+kullanım) |
| `test_ucli_checks_isolation.py::AgentTokenScope.test_agents_caller_only_for_agents_paths` | 35 | kapsam dışı | yok | kontrol kaydı dizini yazma yasağı. İz: T3 (dosya); T7 (periyodik+kullanım) |

### `py/tests/test_ucli_checks_opts.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_checks_opts.py::Validate.test_off_by_default_and_dropped` | 21 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checks_opts.py::Validate.test_restricted_ok_max_defaults_to_mode` | 26 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checks_opts.py::Validate.test_errors` | 31 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checks_opts.py::Validate.test_full_needs_accept_risk` | 35 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checks_opts.py::Registry.test_missing_loose_mode_and_shape` | 57 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checks_opts.py::Registry.test_symlink_rejected` | 68 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checks_opts.py::ReadModifyWrite.test_set_mode_seq_counts_every_write` | 105 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checks_opts.py::ReadModifyWrite.test_two_deletes_both_stick` | 109 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checks_opts.py::Apply.test_flags_added` | 133 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checks_opts.py::Apply.test_full_adds_accept_risk` | 140 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checks_opts.py::Apply.test_full_refused_when_binary_only_knows_restricted` | 144 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checks_opts.py::Apply.test_unsupported_binary_refused` | 154 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_checks_opts.py::Apply.test_needs_state_dir_and_registry` | 158 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_cost_cap_refusal.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_cost_cap_refusal.py::RefusalTests.test_cap_refusal_has_code_and_amounts` | 13 | kapsam dışı | yok | günlük tavan reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T7 (periyodik+kullanım) |
| `test_ucli_cost_cap_refusal.py::RefusalTests.test_plain_value_error_has_no_code` | 18 | kapsam dışı | yok | günlük tavan reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T7 (periyodik+kullanım) |
| `test_ucli_cost_cap_refusal.py::ProviderRaisesTests.test_claude_service_flags_raises_over_cap` | 25 | kapsam dışı | yok | günlük tavan reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T7 (periyodik+kullanım) |

### `py/tests/test_ucli_default_permission_mode.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_default_permission_mode.py::DefaultPermissionMode.test_ucli_panel_default_is_allow_edit_and_listed` | 12 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_default_permission_mode.py::DefaultPermissionMode.test_ucli_server_internal_default_stays_read_only` | 17 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_default_permission_mode.py::DefaultPermissionMode.test_other_providers_keep_auto` | 21 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_effort.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_effort.py::ReasoningModeTests.test_unset_empty_and_unknown_values_mean_auto` | 105 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::ReasoningModeTests.test_off_words_switch_it_off` | 111 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::ReasoningModeTests.test_a_named_level_forces_that_level_case_insensitively` | 116 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::ReasoningModeTests.test_a_non_dict_ucli_limits_is_tolerated` | 121 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::ReasoningModeTests.test_it_does_not_leak_into_the_numeric_overrides` | 125 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::CatalogTests.test_only_chat_models_are_listed_and_their_capabilities_kept` | 147 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::CatalogTests.test_non_text_ids_are_skipped` | 155 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::CatalogTests.test_a_failed_or_empty_fetch_keeps_the_previous_map` | 161 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::CatalogTests.test_without_a_key_nothing_is_fetched` | 170 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::CatalogTests.test_model_choices_and_the_effort_gate_share_one_fetch` | 176 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::ReasoningEffortForTests.test_a_model_that_declares_support_gets_the_level` | 192 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::ReasoningEffortForTests.test_gemma_which_rejects_the_field_gets_nothing` | 196 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::ReasoningEffortForTests.test_an_unknown_model_or_an_empty_catalog_gets_nothing` | 201 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::ReasoningEffortForTests.test_a_malformed_capabilities_entry_is_tolerated` | 206 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::ReasoningEffortForTests.test_an_allowed_values_list_restricts_the_level_unless_aliased` | 214 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::EffortArgsTests.test_a_capable_model_and_a_new_binary_get_the_session_preset` | 225 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::EffortArgsTests.test_off_is_silent_and_sends_nothing` | 231 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::EffortArgsTests.test_a_named_level_overrides_the_preset_but_not_the_model_gate` | 237 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::EffortArgsTests.test_an_old_binary_gets_nothing_and_the_log_says_why` | 243 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::EffortArgsTests.test_a_model_that_rejects_the_field_is_skipped_and_logged` | 249 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::EffortArgsTests.test_no_model_and_a_missing_binary_give_nothing_instead_of_raising` | 255 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::BuildInnerCommandTests.test_the_preset_name_rides_along_as_the_last_flag` | 286 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::BuildInnerCommandTests.test_an_unknown_or_empty_effort_falls_back_to_medium_for_the_flag_too` | 290 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::BuildInnerCommandTests.test_gemma_gets_the_command_byte_identical_to_before` | 296 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::BuildInnerCommandTests.test_an_old_binary_gets_the_command_byte_identical_to_before` | 300 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::BuildInnerCommandTests.test_off_gets_the_command_byte_identical_to_before` | 304 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::BuildInnerCommandTests.test_the_api_key_wrapper_keeps_the_flag` | 308 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::BuildInnerCommandTests.test_every_effort_preset_still_round_trips_through_the_running_command` | 314 | karşılandı | `providers.rs::ucli_effort_presets`<br>`golden.rs::provider_detect_and_info` | yalnız ayrıştırma yönü; argv üretimi W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::BuildInnerCommandTests.test_the_command_is_still_recognised_as_a_ucli_process` | 324 | karşılandı | `providers.rs::detect`<br>`tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | yalnız tanıma/ad; argv üretimi W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_effort.py::RealBinaryTests.test_the_delivered_binary_knows_the_flag_when_it_is_new_enough` | 331 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_endpoint.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_endpoint.py::UcliEndpointTest.test_default_is_evren` | 23 | kapsam dışı | yok | ucli uç noktası ayarı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_endpoint.py::UcliEndpointTest.test_custom_valid_endpoint_wins_and_trailing_slash_dropped` | 27 | kapsam dışı | yok | ucli uç noktası ayarı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_endpoint.py::UcliEndpointTest.test_invalid_endpoint_falls_back_and_empty_clears` | 31 | kapsam dışı | yok | ucli uç noktası ayarı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_endpoint.py::UcliEndpointTest.test_model_list_fetch_uses_configured_endpoint` | 40 | kapsam dışı | yok | ucli uç noktası ayarı. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_evren_no_default_cap.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_evren_no_default_cap.py::EvrenNoDefaultCapTest.test_evren_has_no_default_cap` | 18 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_evren_no_default_cap.py::EvrenNoDefaultCapTest.test_explicit_cap_on_evren_still_passes` | 22 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_failed_turns.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_failed_turns.py::FailedTurnsTests.test_no_directory_or_no_record_is_none_not_zero` | 28 | kapsam dışı | yok | başarısız tur satır alanı. İz: T1 (durum) |
| `test_ucli_failed_turns.py::FailedTurnsTests.test_counts_this_session_only_and_reports_the_newest_error` | 33 | kapsam dışı | yok | başarısız tur satır alanı. İz: T1 (durum) |
| `test_ucli_failed_turns.py::FailedTurnsTests.test_a_broken_or_errorless_record_still_counts` | 42 | kapsam dışı | yok | başarısız tur satır alanı. İz: T1 (durum) |
| `test_ucli_failed_turns.py::FailedTurnsTests.test_dict_error_uses_its_message` | 46 | kapsam dışı | yok | başarısız tur satır alanı. İz: T1 (durum) |
| `test_ucli_failed_turns.py::FailedTurnsTests.test_no_sid_is_none` | 50 | kapsam dışı | yok | başarısız tur satır alanı. İz: T1 (durum) |
| `test_ucli_failed_turns.py::FailedTurnsTests.test_web_wrapper_never_raises` | 53 | kapsam dışı | yok | başarısız tur satır alanı. İz: T1 (durum) |
| `test_ucli_failed_turns.py::FailedTurnsTests.test_other_cli_has_no_failed_turns` | 58 | kapsam dışı | yok | başarısız tur satır alanı. İz: T1 (durum) |

### `py/tests/test_ucli_fresh_handover.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_fresh_handover.py::ArchiveTest.test_moves_history_and_status_keeps_others` | 31 | kapsam dışı | yok | ucli devri. İz: T4 (yaşam döngüsü) |
| `test_ucli_fresh_handover.py::ArchiveTest.test_second_archive_does_not_overwrite` | 43 | kapsam dışı | yok | ucli devri. İz: T4 (yaşam döngüsü) |
| `test_ucli_fresh_handover.py::ArchiveTest.test_nothing_to_move_and_bad_names` | 50 | kapsam dışı | yok | ucli devri. İz: T4 (yaşam döngüsü) |
| `test_ucli_fresh_handover.py::StartFreshTest.test_fresh_ucli_archives` | 72 | kapsam dışı | yok | ucli devri. İz: T4 (yaşam döngüsü) |
| `test_ucli_fresh_handover.py::StartFreshTest.test_not_fresh_or_not_ucli_or_running_does_not` | 75 | kapsam dışı | yok | ucli devri. İz: T4 (yaşam döngüsü) |
| `test_ucli_fresh_handover.py::HandoverGateTest.test_ucli_handover_sends_message` | 82 | kapsam dışı | yok | ucli devri. İz: T4 (yaşam döngüsü) |

### `py/tests/test_ucli_git_flags.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_git_flags.py::ValidateTests.test_default_off` | 21 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_git_flags.py::ValidateTests.test_on_independent_of_each_other_and_exec` | 26 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_git_flags.py::ValidateTests.test_garbage_is_error` | 32 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_git_flags.py::ArgvTests.test_no_flags_by_default` | 39 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_git_flags.py::ArgvTests.test_only_requested_flag` | 44 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_git_flags.py::ArgvTests.test_both_no_duplicates` | 52 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_git_flags.py::ArgvTests.test_unsupported_binary_refuses` | 57 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_git_flags.py::ArgvTests.test_unsupported_irrelevant_when_off` | 61 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_instructions_flags.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_instructions_flags.py::InstructionsFlagsTest.test_default_off` | 21 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_instructions_flags.py::InstructionsFlagsTest.test_valid` | 30 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_instructions_flags.py::InstructionsFlagsTest.test_zero_and_empty_dropped` | 36 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_instructions_flags.py::InstructionsFlagsTest.test_invalid` | 42 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_instructions_flags.py::InstructionsFlagsTest.test_argv` | 49 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_instructions_flags.py::InstructionsFlagsTest.test_unsupported_binary_skips` | 54 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_interactive_flag.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_interactive_flag.py::InteractiveArgsTest.test_supported_adds_flag` | 12 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_interactive_flag.py::InteractiveArgsTest.test_unsupported_skips_and_logs` | 16 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_key_path.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_key_path.py::UcliKeyPathTest.test_default_and_service` | 14 | kapsam dışı | yok | ucli anahtar dosyası yolu. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_key_path.py::UcliKeyPathTest.test_callers_share_helper` | 19 | kapsam dışı | yok | ucli anahtar dosyası yolu. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_last_exchange_pairing.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_last_exchange_pairing.py::LastExchangePairingTest.test_pending_user_turn_has_empty_assistant` | 17 | kapsam dışı | yok | sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_ucli_last_exchange_pairing.py::LastExchangePairingTest.test_answered_turn_pairs_normally` | 22 | kapsam dışı | yok | sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |
| `test_ucli_last_exchange_pairing.py::LastExchangePairingTest.test_assistant_only_and_empty` | 26 | kapsam dışı | yok | sohbet geçmişi. İz: rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1 |

### `py/tests/test_ucli_limit_flags.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_limit_flags.py::ValidateTests.test_empty_and_zero_drop_key` | 30 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_limit_flags.py::ValidateTests.test_ints_accepted` | 36 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_limit_flags.py::ValidateTests.test_ints_invalid_are_errors` | 41 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_limit_flags.py::ValidateTests.test_bools` | 48 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_limit_flags.py::ValidateTests.test_price_two_and_four` | 55 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_limit_flags.py::ValidateTests.test_price_invalid` | 59 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_limit_flags.py::ArgvTests.test_nothing_by_default` | 67 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_limit_flags.py::ArgvTests.test_int_flags_with_values` | 74 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_limit_flags.py::ArgvTests.test_price_and_bools` | 80 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_limit_flags.py::ArgvTests.test_unsupported_flag_is_skipped_not_fatal` | 86 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_limit_flags.py::ArgvTests.test_only_supported_ones_added` | 90 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_live_context.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_live_context.py::LiveContext.test_bytes_over_four` | 16 | kapsam dışı | yok | `live_context` satır alanı. İz: T1 (durum) |
| `test_ucli_live_context.py::LiveContext.test_zero_is_zero` | 19 | kapsam dışı | yok | `live_context` satır alanı. İz: T1 (durum) |
| `test_ucli_live_context.py::LiveContext.test_unknown_cases_are_none` | 22 | kapsam dışı | yok | `live_context` satır alanı. İz: T1 (durum) |
| `test_ucli_live_context.py::LiveContext.test_reader_error_is_none` | 30 | kapsam dışı | yok | `live_context` satır alanı. İz: T1 (durum) |

### `py/tests/test_ucli_max_session_usd.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_max_session_usd.py::MaxSessionUsd.test_valid_kept_as_float` | 10 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_max_session_usd.py::MaxSessionUsd.test_zero_and_empty_dropped` | 14 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_max_session_usd.py::MaxSessionUsd.test_invalid_rejected` | 18 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_max_session_usd.py::MaxSessionUsd.test_independent_of_per_turn_cap` | 24 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_max_session_usd.py::DefaultCap.test_default_is_8_and_configurable` | 35 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_max_session_usd.py::DefaultCap.test_provider_uses_default_when_record_has_none` | 43 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_metrics_file_arg.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_metrics_file_arg.py::MetricsFileArgs.test_on_and_supported` | 22 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_metrics_file_arg.py::MetricsFileArgs.test_off_unsupported_nameless` | 27 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_metrics_file_arg.py::MetricsFileArgs.test_name_sanitised` | 32 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_multiline_flatten.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_multiline_flatten.py::FlattenTest.test_ucli_flattens` | 15 | kapsam dışı | yok | ucli giriş metni düzleştirme. İz: T2 (terminal) |
| `test_ucli_multiline_flatten.py::FlattenTest.test_ucli_single_line_unchanged` | 19 | kapsam dışı | yok | ucli giriş metni düzleştirme. İz: T2 (terminal) |
| `test_ucli_multiline_flatten.py::FlattenTest.test_ucli_trailing_newline` | 23 | kapsam dışı | yok | ucli giriş metni düzleştirme. İz: T2 (terminal) |
| `test_ucli_multiline_flatten.py::FlattenTest.test_ucli_tab_single_line` | 26 | kapsam dışı | yok | ucli giriş metni düzleştirme. İz: T2 (terminal) |
| `test_ucli_multiline_flatten.py::FlattenTest.test_ucli_long_text_not_truncated` | 29 | kapsam dışı | yok | ucli giriş metni düzleştirme. İz: T2 (terminal) |
| `test_ucli_multiline_flatten.py::FlattenTest.test_single_fold_point_in_callers` | 37 | kapsam dışı | yok | ucli giriş metni düzleştirme. İz: T2 (terminal) |
| `test_ucli_multiline_flatten.py::FlattenTest.test_other_providers_untouched` | 44 | kapsam dışı | yok | ucli giriş metni düzleştirme. İz: T2 (terminal) |

### `py/tests/test_ucli_phase.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_phase.py::LivePhaseTests.test_a_streaming_phase_comes_through` | 36 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseTests.test_the_last_write_time_of_the_file_comes_through_as_last_unix` | 41 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseTests.test_a_missing_or_garbage_last_activity_is_left_out_not_zeroed` | 46 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseTests.test_a_retry_phase_keeps_its_reason` | 54 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseTests.test_no_phase_a_null_phase_or_an_older_binary_mean_none` | 60 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseTests.test_a_phase_without_a_usable_name_is_ignored` | 67 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseTests.test_bad_numbers_are_dropped_never_turned_into_an_invented_zero` | 73 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseTests.test_text_is_trimmed_and_capped` | 79 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseTests.test_a_future_phase_name_passes_through_so_the_badge_does_not_go_silent` | 85 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseTests.test_only_the_known_fields_are_returned` | 89 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseTests.test_no_status_file_no_sid_or_a_broken_file_mean_none` | 93 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseTests.test_every_other_provider_has_no_phase` | 101 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_it_asks_the_sessions_own_provider_with_its_cwd_and_sid` | 122 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_waiting_for_the_response_turns_amber_then_red_on_the_thresholds` | 127 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_retries_and_rate_limits_are_always_amber` | 133 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_a_model_that_is_thinking_or_writing_is_progress_not_a_warning` | 139 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_a_stream_that_goes_quiet_turns_amber_then_red_and_progress_stays_green` | 145 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_a_long_running_stream_that_keeps_writing_is_not_a_warning` | 154 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_idle_is_reported_but_does_not_decide_the_waiting_colour` | 159 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_without_a_last_write_time_a_stream_has_no_idle_and_no_warning` | 163 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_the_internal_last_unix_is_not_leaked_to_the_wire` | 167 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_the_providers_dict_is_not_mutated` | 171 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_a_missing_since_unix_means_no_elapsed_and_no_warning` | 176 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_a_since_in_the_future_never_gives_a_negative_elapsed` | 180 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_no_phase_means_none` | 184 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::LivePhaseHelperTests.test_a_failing_provider_never_breaks_the_panel` | 188 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::StatusPayloadPhaseTests.test_a_registered_running_ucli_row_carries_its_phase` | 226 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::StatusPayloadPhaseTests.test_an_unregistered_running_ucli_row_carries_its_phase_and_the_amber_wait` | 231 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::StatusPayloadPhaseTests.test_a_frozen_stream_row_goes_amber_from_the_file_write_time` | 235 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |
| `test_ucli_phase.py::StatusPayloadPhaseTests.test_a_stopped_row_and_a_phaseless_provider_have_no_phase` | 242 | kapsam dışı | yok | `phase` satır alanı. İz: T1 (durum) |

### `py/tests/test_ucli_quota_warn.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_quota_warn.py::QuotaEquivalentTests.test_a_real_session_prompt_cache_counts_three_percent` | 26 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::QuotaEquivalentTests.test_the_weight_is_the_measured_three_percent` | 31 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::QuotaEquivalentTests.test_uncached_input_and_output_count_in_full` | 34 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::QuotaEquivalentTests.test_a_fully_cached_prompt_costs_three_percent` | 37 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::QuotaEquivalentTests.test_cached_cannot_exceed_the_prompt` | 40 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::QuotaEquivalentTests.test_missing_and_negative_values_are_clamped_to_zero` | 44 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::QuotaEquivalentTests.test_reasoning_tokens_are_not_added_again` | 48 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::WarnLevelTests.test_levels_follow_the_thresholds_and_boundaries_are_inclusive` | 55 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::WarnLevelTests.test_a_zero_threshold_switches_that_level_off` | 61 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::WarnLevelTests.test_a_red_below_amber_typo_still_gives_the_heaviest_level` | 66 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::ThresholdSettingTests.test_unset_means_one_million_and_three_million` | 75 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::ThresholdSettingTests.test_custom_values_win_as_strings_or_numbers_with_separators` | 79 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::ThresholdSettingTests.test_off_words_and_zero_disable_a_level` | 83 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::ThresholdSettingTests.test_garbage_falls_back_to_the_default_of_that_level` | 87 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::ThresholdSettingTests.test_a_non_dict_setting_is_tolerated` | 92 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::ThresholdSettingTests.test_the_setting_is_part_of_the_schema_and_merges_per_field` | 95 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::LiveUsageWarnTests.test_the_row_gets_the_quota_equivalent_and_the_level` | 121 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::LiveUsageWarnTests.test_cached_input_does_not_trip_the_warning_the_way_the_raw_total_would` | 128 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::LiveUsageWarnTests.test_the_providers_own_dict_is_not_mutated` | 133 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::LiveUsageWarnTests.test_a_counter_without_token_fields_passes_through_unchanged` | 139 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |
| `test_ucli_quota_warn.py::LiveUsageWarnTests.test_a_broken_threshold_setting_never_breaks_the_row` | 143 | kapsam dışı | yok | token rozeti eşikleri. İz: T1 (durum) |

### `py/tests/test_ucli_request_timeout.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_request_timeout.py::LimitOverridesTests.test_the_timeout_is_a_valid_override_as_a_string_or_a_number` | 62 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_request_timeout.py::LimitOverridesTests.test_unset_empty_and_invalid_values_fall_back_to_the_default` | 66 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_request_timeout.py::LimitOverridesTests.test_the_other_overrides_are_unaffected` | 72 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_request_timeout.py::TimeoutArgsTests.test_a_binary_that_knows_the_flag_gets_the_600_second_default` | 78 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_request_timeout.py::TimeoutArgsTests.test_the_settings_override_replaces_the_default` | 84 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_request_timeout.py::TimeoutArgsTests.test_an_old_binary_gets_nothing_and_the_log_says_why` | 88 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_request_timeout.py::TimeoutArgsTests.test_a_missing_binary_gets_nothing_instead_of_raising` | 94 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_request_timeout.py::BuildInnerCommandTests.test_the_default_command_ends_with_the_600_second_timeout` | 123 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_request_timeout.py::BuildInnerCommandTests.test_the_settings_override_reaches_the_command` | 126 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_request_timeout.py::BuildInnerCommandTests.test_an_old_binary_gets_the_command_byte_identical_to_before` | 132 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_request_timeout.py::BuildInnerCommandTests.test_the_api_key_wrapper_keeps_the_flag` | 136 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_request_timeout.py::BuildInnerCommandTests.test_every_effort_preset_still_round_trips_through_the_running_command` | 142 | karşılandı | `providers.rs::ucli_effort_presets`<br>`golden.rs::provider_detect_and_info` | yalnız ayrıştırma yönü; argv üretimi W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_request_timeout.py::BuildInnerCommandTests.test_the_command_is_still_recognised_as_a_ucli_process` | 152 | karşılandı | `providers.rs::detect`<br>`tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | yalnız tanıma/ad; argv üretimi W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_request_timeout.py::RealBinaryTests.test_the_delivered_binary_knows_the_flag_when_it_is_new_enough` | 159 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_resolve_binary.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_resolve_binary.py::OwnCopyLocationTests.test_own_copy_lives_in_the_repo_bin_directory_and_is_named_ucli` | 32 | kapsam dışı | yok | ucli ikilisi seçimi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_resolve_binary.py::OwnCopyLocationTests.test_a_session_started_from_the_own_copy_is_still_recognised_as_ucli` | 38 | karşılandı | `providers.rs::detect` | ikilinin adının `ucli` olması kuralı; yol seçimi W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_resolve_binary.py::ResolveBinaryTests.test_own_copy_beats_path_and_the_sibling_builds` | 79 | kapsam dışı | yok | ucli ikilisi seçimi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_resolve_binary.py::ResolveBinaryTests.test_path_beats_the_sibling_builds_when_there_is_no_own_copy` | 85 | kapsam dışı | yok | ucli ikilisi seçimi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_resolve_binary.py::ResolveBinaryTests.test_sibling_release_is_preferred_over_sibling_debug` | 90 | kapsam dışı | yok | ucli ikilisi seçimi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_resolve_binary.py::ResolveBinaryTests.test_sibling_debug_is_the_fallback_when_there_is_no_sibling_release` | 94 | kapsam dışı | yok | ucli ikilisi seçimi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_resolve_binary.py::ResolveBinaryTests.test_sibling_release_alone_is_used` | 98 | kapsam dışı | yok | ucli ikilisi seçimi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_resolve_binary.py::ResolveBinaryTests.test_no_build_raises_a_clear_error_that_names_the_installer` | 102 | kapsam dışı | yok | ucli ikilisi seçimi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_resolve_binary.py::ResolveBinaryTests.test_overrides_beat_the_own_copy_so_debug_can_be_forced` | 109 | kapsam dışı | yok | ucli ikilisi seçimi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_resolve_binary.py::ResolveBinaryTests.test_settings_override_beats_env_and_env_beats_the_own_copy` | 123 | kapsam dışı | yok | ucli ikilisi seçimi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_script.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_script.py::ScriptModeSettingTests.test_default_and_garbage_mean_off` | 42 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_script.py::ScriptModeSettingTests.test_read_and_full_in_any_spelling` | 47 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_script.py::ScriptModeSettingTests.test_default_settings_carry_the_key` | 52 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_script.py::BuildCommandTests.test_off_leaves_the_command_exactly_as_before` | 75 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_script.py::BuildCommandTests.test_read_and_full_append_one_equals_form_flag` | 79 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_script.py::BuildCommandTests.test_old_binary_without_the_flag_is_not_given_it` | 84 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_script.py::BuildCommandTests.test_allow_create_mode_passes_only_that_flag` | 90 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_script.py::BuildCommandTests.test_allow_create_on_a_binary_that_lacks_it_opens_read_only` | 95 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_script.py::BuildCommandTests.test_permission_modes_list_and_round_trip_from_the_running_command` | 102 | karşılandı | `golden.rs::provider_detect_and_info`<br>`providers.rs::ucli_effort_presets` | yalnız ayrıştırma yönü; mod listesi ve argv üretimi W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_script.py::SaveScriptSettingTests.test_mode_round_trips_and_an_empty_one_switches_the_layer_off` | 122 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_script.py::SaveScriptSettingTests.test_saving_the_mode_leaves_the_other_ucli_panels_alone` | 131 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_script.py::SaveScriptSettingTests.test_a_hand_edited_non_dict_value_degrades_to_off` | 139 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_script.py::SaveScriptSettingTests.test_the_panel_endpoint_returns_the_field_on_the_wire` | 144 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_search_token_env.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_search_token_env.py::SearchTokenEnvTest.test_default_absent` | 21 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_search_token_env.py::SearchTokenEnvTest.test_valid_name` | 27 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_search_token_env.py::SearchTokenEnvTest.test_empty_means_not_sent` | 32 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_search_token_env.py::SearchTokenEnvTest.test_invalid_names_error` | 36 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_search_token_env.py::SearchTokenEnvTest.test_argv_with_search_url` | 42 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_search_token_env.py::SearchTokenEnvTest.test_skipped_without_search_url` | 47 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_search_token_env.py::SearchTokenEnvTest.test_unsupported_binary_skips` | 50 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_show_reasoning.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_show_reasoning.py::SettingTests.test_default_off_and_words` | 24 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_show_reasoning.py::BuildTests.test_flag_added_only_when_enabled_and_supported` | 43 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_show_reasoning.py::BuildTests.test_old_binary_never_gets_the_flag_and_it_is_logged` | 47 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_start_opts.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_start_opts.py::ValidateTests.test_empty_is_ok_and_empty` | 29 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::ValidateTests.test_unknown_service_rejected` | 33 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::ValidateTests.test_shells_and_wrappers_rejected` | 36 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::ValidateTests.test_glob_needs_cmds_and_must_be_narrow` | 40 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::ValidateTests.test_timeout_range_and_requires_cmds` | 48 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_no_opts_is_identical_to_before` | 80 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_max_history_kib_is_passed_only_when_the_binary_knows_it_and_the_setting_wins` | 84 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_claude_service_swaps_endpoint_once_and_key_stays_out_of_argv` | 98 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_claude_service_gets_team_flags_and_is_refused_over_the_daily_cap` | 116 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_groq_service_uses_groq_endpoint_and_key_env` | 145 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_service_models_fetches_live_list_with_correct_auth` | 153 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_claude_service_skips_instructions_auto_when_file_over_16kib` | 177 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_missing_service_key_refuses_spawn` | 202 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_evren_service_changes_nothing` | 206 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_exec_flags_appended_and_gated_by_binary` | 209 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_exec_bind_ro` | 219 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_star_expands_on_path_and_write_adds_allow_edit` | 227 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_patterns_validate` | 241 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_star_never_opens_forbidden` | 249 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::BuildTests.test_write_permission_default_off` | 259 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::WiringTests.test_only_ucli_accepts_cli_opts` | 267 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::WiringTests.test_spawn_never_passes_cli_opts_to_other_providers` | 273 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::WiringTests.test_start_rejects_opts_for_non_ucli_and_invalid_opts` | 280 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::WiringTests.test_new_chat_rejects_before_recording_an_instance` | 293 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::WiringTests.test_new_chat_lock_timeout_forgets_instance` | 328 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::WiringTests.test_new_chat_timeout_after_spawn_keeps_instance` | 334 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::WiringTests.test_new_chat_unexpected_error_before_spawn_forgets_instance` | 340 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::CostCapTests.test_today_sums_only_today_and_uses_the_task_model` | 370 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::CostCapTests.test_cap_zero_means_off_and_cap_blocks_when_reached` | 380 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::CostCapTests.test_config_parsing_is_safe` | 391 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::CostCapTests.test_credit_total_parsing_is_safe` | 403 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |
| `test_ucli_start_opts.py::TokioThreadsEnvTests.test_env_overrides_limits_tokio_workers` | 414 | kapsam dışı | yok | başlatma seçenekleri. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T4 (yaşam döngüsü) |

### `py/tests/test_ucli_state_dir.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_state_dir.py::TestSetting.test_default_off_and_words` | 42 | kapsam dışı | yok | ucli durum dizini bayrağı ve okuyucuları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T1 (durum) |
| `test_ucli_state_dir.py::TestChatOnce.test_state_dir_passed_only_when_on_supported_and_session` | 67 | kapsam dışı | yok | ucli durum dizini bayrağı ve okuyucuları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T1 (durum) |
| `test_ucli_state_dir.py::TestPaths.test_dir_is_per_root_and_stable_and_outside_the_repo` | 79 | kapsam dışı | yok | ucli durum dizini bayrağı ve okuyucuları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T1 (durum) |
| `test_ucli_state_dir.py::TestPaths.test_off_reads_only_legacy_until_the_new_dir_exists` | 88 | kapsam dışı | yok | ucli durum dizini bayrağı ve okuyucuları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T1 (durum) |
| `test_ucli_state_dir.py::TestPaths.test_on_prefers_new_then_falls_back_to_legacy_for_files` | 95 | kapsam dışı | yok | ucli durum dizini bayrağı ve okuyucuları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T1 (durum) |
| `test_ucli_state_dir.py::TestSpawnArgv.test_off_by_default_adds_nothing` | 118 | kapsam dışı | yok | ucli durum dizini bayrağı ve okuyucuları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T1 (durum) |
| `test_ucli_state_dir.py::TestSpawnArgv.test_on_adds_flag_for_new_session_only_when_binary_knows_it` | 122 | kapsam dışı | yok | ucli durum dizini bayrağı ve okuyucuları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T1 (durum) |
| `test_ucli_state_dir.py::TestSpawnArgv.test_session_with_legacy_history_keeps_the_legacy_dir` | 127 | kapsam dışı | yok | ucli durum dizini bayrağı ve okuyucuları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T1 (durum) |
| `test_ucli_state_dir.py::TestSpawnArgv.test_session_already_in_new_dir_keeps_it_even_if_setting_turned_off` | 133 | kapsam dışı | yok | ucli durum dizini bayrağı ve okuyucuları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4; T1 (durum) |

### `py/tests/test_ucli_stream.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_stream.py::StreamSettingTests.test_the_shipped_default_is_on` | 38 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_stream.py::StreamSettingTests.test_an_untouched_install_asks_for_the_stream_and_off_still_wins` | 43 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_stream.py::StreamSettingTests.test_missing_empty_and_garbage_fall_back_to_the_default` | 49 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_stream.py::StreamSettingTests.test_on_words_enable_in_any_spelling` | 56 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_stream.py::StreamSettingTests.test_off_words_disable_even_when_the_default_is_on` | 61 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_stream.py::StreamSettingTests.test_the_stream_key_is_not_mistaken_for_a_numeric_limit` | 67 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_stream.py::SaveStreamSettingTests.test_it_round_trips_and_an_empty_value_goes_back_to_the_default` | 82 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_stream.py::SaveStreamSettingTests.test_it_does_not_disturb_the_other_limit_fields` | 90 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_stream.py::SaveStreamSettingTests.test_a_hand_edited_non_dict_value_degrades_to_the_default` | 98 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_stream.py::BuildCommandTests.test_off_leaves_the_command_without_the_flag` | 124 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_stream.py::BuildCommandTests.test_on_adds_exactly_one_bare_flag` | 129 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_stream.py::BuildCommandTests.test_an_old_binary_without_the_flag_is_not_given_it_and_the_skip_is_logged` | 134 | kapsam dışı | yok | açılış argv/env/model kuralları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_unpriced_model_cap.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_unpriced_model_cap.py::UnpricedModelCapTest.test_haiku_gets_highest_tier_price_and_both_caps` | 32 | kapsam dışı | yok | fiyatsız modelde USD tavanı: `--price` ya da spawn reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_unpriced_model_cap.py::UnpricedModelCapTest.test_fable_gets_table_price` | 38 | kapsam dışı | yok | fiyatsız modelde USD tavanı: `--price` ya da spawn reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_unpriced_model_cap.py::UnpricedModelCapTest.test_builtin_priced_model_gets_no_price_flag` | 42 | kapsam dışı | yok | fiyatsız modelde USD tavanı: `--price` ya da spawn reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_unpriced_model_cap.py::UnpricedModelCapTest.test_explicit_price_wins_and_enables_per_turn_cap` | 47 | kapsam dışı | yok | fiyatsız modelde USD tavanı: `--price` ya da spawn reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_unpriced_model_cap.py::UnpricedModelCapTest.test_unknown_price_with_cap_is_refused_with_reason` | 52 | kapsam dışı | yok | fiyatsız modelde USD tavanı: `--price` ya da spawn reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_unpriced_model_cap.py::UnpricedModelCapTest.test_binary_without_price_flag_is_refused` | 58 | kapsam dışı | yok | fiyatsız modelde USD tavanı: `--price` ya da spawn reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_unpriced_model_cap.py::UnpricedModelCapTest.test_no_cap_no_refusal` | 62 | kapsam dışı | yok | fiyatsız modelde USD tavanı: `--price` ya da spawn reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_unpriced_model_cap.py::CatalogMarksUnstartableTest.test_only_unpriced_paid_models_are_marked_with_reason` | 87 | kapsam dışı | yok | fiyatsız modelde USD tavanı: `--price` ya da spawn reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_unpriced_model_cap.py::CatalogMarksUnstartableTest.test_reason_is_the_one_the_launch_refuses_with` | 94 | kapsam dışı | yok | fiyatsız modelde USD tavanı: `--price` ya da spawn reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_unpriced_model_cap.py::CatalogMarksUnstartableTest.test_cap_off_marks_nothing` | 100 | kapsam dışı | yok | fiyatsız modelde USD tavanı: `--price` ya da spawn reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_unpriced_model_cap.py::CatalogMarksUnstartableTest.test_binary_without_session_cap_flag_marks_nothing` | 103 | kapsam dışı | yok | fiyatsız modelde USD tavanı: `--price` ya da spawn reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_unpriced_model_cap.py::CatalogMarksUnstartableTest.test_binary_without_price_flag_marks_table_priced_model_too` | 106 | kapsam dışı | yok | fiyatsız modelde USD tavanı: `--price` ya da spawn reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_unpriced_model_cap.py::CatalogMarksUnstartableTest.test_check_failure_keeps_the_list` | 110 | kapsam dışı | yok | fiyatsız modelde USD tavanı: `--price` ya da spawn reddi. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |

### `py/tests/test_ucli_usage.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_usage.py::LiveUsageTests.test_the_counters_come_through_as_written` | 50 | kapsam dışı | yok | `usage` satır alanı. İz: T1 (durum) |
| `test_ucli_usage.py::LiveUsageTests.test_a_binary_without_usage_means_unknown_not_zero` | 54 | kapsam dışı | yok | `usage` satır alanı. İz: T1 (durum) |
| `test_ucli_usage.py::LiveUsageTests.test_a_usage_that_is_not_an_object_means_unknown` | 58 | kapsam dışı | yok | `usage` satır alanı. İz: T1 (durum) |
| `test_ucli_usage.py::LiveUsageTests.test_no_status_file_no_sid_or_a_broken_file_mean_unknown` | 64 | kapsam dışı | yok | `usage` satır alanı. İz: T1 (durum) |
| `test_ucli_usage.py::LiveUsageTests.test_the_unmetered_fields_of_an_older_binary_count_as_zero` | 72 | kapsam dışı | yok | `usage` satır alanı. İz: T1 (durum) |
| `test_ucli_usage.py::LiveUsageTests.test_garbage_values_become_zero_never_an_invented_number` | 78 | kapsam dışı | yok | `usage` satır alanı. İz: T1 (durum) |
| `test_ucli_usage.py::LiveUsageTests.test_only_the_known_counters_are_returned` | 86 | kapsam dışı | yok | `usage` satır alanı. İz: T1 (durum) |
| `test_ucli_usage.py::LiveUsageTests.test_every_other_provider_has_no_counter` | 92 | kapsam dışı | yok | `usage` satır alanı. İz: T1 (durum) |
| `test_ucli_usage.py::LiveUsageHelperTests.test_it_asks_the_sessions_own_provider_with_its_cwd_and_sid` | 104 | kapsam dışı | yok | `usage` satır alanı. İz: T1 (durum) |
| `test_ucli_usage.py::LiveUsageHelperTests.test_a_failing_provider_never_breaks_the_panel` | 112 | kapsam dışı | yok | `usage` satır alanı. İz: T1 (durum) |
| `test_ucli_usage.py::StatusPayloadUsageTests.test_a_registered_running_ucli_row_carries_its_counters` | 148 | kapsam dışı | yok | `usage` satır alanı. İz: T1 (durum) |
| `test_ucli_usage.py::StatusPayloadUsageTests.test_an_unregistered_running_ucli_row_carries_its_counters` | 153 | kapsam dışı | yok | `usage` satır alanı. İz: T1 (durum) |
| `test_ucli_usage.py::StatusPayloadUsageTests.test_a_stopped_row_and_a_counterless_provider_have_no_usage` | 157 | kapsam dışı | yok | `usage` satır alanı. İz: T1 (durum) |

### `py/tests/test_ucli_web.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_ucli_web.py::UcliWebConfigTests.test_empty_unset_and_garbage_mean_the_defaults_search_via_the_managed_searxng` | 75 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_search_docker_can_be_turned_off_in_every_spelling` | 80 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_search_docker_stays_on_for_on_values_and_for_empty_or_null` | 86 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_an_explicit_address_wins_and_switches_the_managed_one_off` | 91 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_a_filled_but_invalid_address_does_not_fall_back_to_the_managed_searxng` | 96 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_valid_searxng_address_defaults_the_flavor` | 104 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_https_and_explicit_flavor_in_any_case` | 109 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_brave_is_not_supported_yet_and_fails_closed` | 113 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_invalid_addresses_keep_search_off` | 118 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_whitespace_around_the_address_is_trimmed_not_rejected` | 125 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_domains_are_split_lowercased_and_deduplicated_in_order` | 129 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_domains_accept_a_list_too` | 134 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_invalid_domains_are_dropped_not_fixed` | 138 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_whitespace_is_a_separator_not_part_of_a_name` | 144 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_single_label_hosts_are_valid` | 148 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_domain_count_is_capped` | 152 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::UcliWebConfigTests.test_fetch_domains_do_not_need_a_search_address` | 157 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::SaveSettingsTests.test_defaults_are_off_and_cache_aware` | 172 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::SaveSettingsTests.test_ucli_web_merges_per_field_and_empty_removes_the_field` | 177 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::SaveSettingsTests.test_a_boolean_search_docker_round_trips_and_false_does_not_mean_remove` | 185 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::SaveSettingsTests.test_the_off_switch_does_not_disturb_the_other_fields` | 196 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::SaveSettingsTests.test_a_list_value_is_stored_as_a_comma_separated_string` | 201 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::SaveSettingsTests.test_other_dict_settings_are_unaffected_by_the_list_handling` | 206 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::SaveSettingsTests.test_a_non_dict_stored_value_degrades_to_empty` | 212 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::SaveSettingsTests.test_the_escape_hatch_persists` | 218 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BinaryFlagProbeTests.test_exact_flag_matching` | 225 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BinaryFlagProbeTests.test_a_longer_flag_does_not_count_as_its_prefix` | 232 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BinaryFlagProbeTests.test_old_binary_supports_neither` | 237 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BinaryFlagProbeTests.test_probe_runs_once_per_binary_version_and_again_after_a_new_delivery` | 242 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BinaryFlagProbeTests.test_missing_or_non_executable_binary_is_false_and_not_cached` | 252 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BinaryFlagProbeTests.test_empty_help_output_is_not_cached` | 262 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BinaryFlagProbeTests.test_the_real_delivered_binary_knows_the_web_flags_when_it_is_new_enough` | 267 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::WebArgsTests.test_everything_switched_off_adds_nothing_and_never_probes` | 292 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::WebArgsTests.test_auto_search_uses_the_managed_searxng_address_and_names_the_session` | 300 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::WebArgsTests.test_auto_search_not_ready_opens_the_session_without_search_and_without_error` | 307 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::WebArgsTests.test_auto_search_with_an_old_binary_never_touches_docker` | 313 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::WebArgsTests.test_an_explicit_address_never_starts_the_managed_one` | 321 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::WebArgsTests.test_a_filled_invalid_address_neither_searches_nor_starts_docker` | 325 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::WebArgsTests.test_a_crash_in_the_managed_searxng_never_breaks_the_spawn` | 329 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::WebArgsTests.test_auto_search_and_fetch_domains_combine` | 335 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::WebArgsTests.test_both_capabilities_on_a_new_binary` | 341 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::WebArgsTests.test_search_only_adds_no_fetch_flags` | 348 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::WebArgsTests.test_fetch_only_adds_no_search_flags` | 352 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::WebArgsTests.test_a_binary_that_only_has_fetch_drops_search_and_says_so` | 356 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::WebArgsTests.test_an_old_binary_gets_no_web_flags_at_all_so_spawn_cannot_crash` | 362 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BuildInnerCommandTests.test_default_command_is_byte_identical_to_before_when_no_search_backend_is_ready` | 394 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BuildInnerCommandTests.test_default_command_gets_the_managed_search_flags_when_the_backend_is_ready` | 398 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BuildInnerCommandTests.test_web_flags_are_appended_after_everything_else` | 405 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BuildInnerCommandTests.test_url_metacharacters_survive_shell_quoting` | 415 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BuildInnerCommandTests.test_read_only_sessions_get_web_too_and_no_allow_edit` | 420 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BuildInnerCommandTests.test_api_key_wrapper_keeps_the_flags_and_no_secret_enters_argv` | 425 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BuildInnerCommandTests.test_running_command_parsing_is_unaffected_by_the_new_flags` | 433 | karşılandı | `golden.rs::provider_detect_and_info`<br>`providers.rs::ucli_effort_presets`<br>`tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | yalnız ayrıştırma yönü; argv üretimi W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BuildInnerCommandTests.test_every_effort_preset_round_trips_through_the_running_command` | 445 | karşılandı | `providers.rs::ucli_effort_presets`<br>`golden.rs::provider_detect_and_info` | yalnız ayrıştırma yönü; argv üretimi W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::BuildInnerCommandTests.test_effort_stays_unknown_when_a_limit_was_changed_by_hand_or_is_missing` | 458 | karşılandı | `providers.rs::ucli_effort_unknown_when_any_limit_changed_or_missing` | yok |
| `test_ucli_web.py::AutoContextTests.test_deriving_binary_gets_no_context_flag_and_effort_round_trips` | 495 | karşılandı | `providers.rs::ucli_every_preset_without_context_flag` | yalnız ayrıştırma yönü; argv üretimi W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::AutoContextTests.test_old_binary_keeps_preset_context` | 502 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::AutoContextTests.test_explicit_setting_still_wins` | 506 | kapsam dışı | yok | ucli web bayrakları ve ayarları. İz: W1-pre sağlayıcı (rs/prov); canlıya T4 |
| `test_ucli_web.py::AutoContextTests.test_legacy_session_with_other_context_value_is_unknown` | 511 | karşılandı | `providers.rs::ucli_effort_presets` | yok |

### `py/tests/test_usage_category.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_usage_category.py::DayUsageTest.test_categories_dedup_and_day` | 36 | kapsam dışı | yok | `cops usage` gün/kategori dökümü. İz: T6 (CLI); T7 (periyodik+kullanım) |
| `test_usage_category.py::DayUsageTest.test_other_day_empty_and_bad_input` | 54 | kapsam dışı | yok | `cops usage` gün/kategori dökümü. İz: T6 (CLI); T7 (periyodik+kullanım) |
| `test_usage_category.py::DayUsageTest.test_render` | 62 | kapsam dışı | yok | `cops usage` gün/kategori dökümü. İz: T6 (CLI); T7 (periyodik+kullanım) |

### `py/tests/test_usage_cli.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_usage_cli.py::UsageCliTests.test_table_sorted_by_spend_and_skips_non_claude` | 61 | kapsam dışı | yok | `cops usage` komutu (toplam hesabı `usage.rs` satırlarında). İz: T6 (CLI) |
| `test_usage_cli.py::UsageCliTests.test_json_and_name_filter` | 68 | kapsam dışı | yok | `cops usage` komutu (toplam hesabı `usage.rs` satırlarında). İz: T6 (CLI) |
| `test_usage_cli.py::UsageCliTests.test_command_is_registered` | 75 | kapsam dışı | yok | `cops usage` komutu (toplam hesabı `usage.rs` satırlarında). İz: T6 (CLI) |
| `test_usage_cli.py::StatusUsageTotalTests.test_status_rows_carry_usage_total_without_blocking` | 81 | karşılandı | `tests/fake_proc.rs::probe_usage_total_claude_exact_sid_without_blocking` | `Probe::usage_total` düzeyinde; durum yükü bağlantısı ve ucli `usage` alanı T1 |

### `py/tests/test_usage_fresh.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_usage_fresh.py::FreshParse.test_parse_one_line_format` | 21 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::FreshParse.test_parse_falls_back_to_tui_format` | 27 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::FreshParse.test_other_providers_have_no_fresh_path` | 32 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::FreshParse.test_agy_fresh_argv_and_tsv_parse` | 37 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::FreshRun.test_fresh_ok_without_any_session` | 52 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::FreshRun.test_fresh_failure_returns_none` | 60 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::FreshRun.test_signed_out_agy_is_auth_required_not_read_failed` | 66 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::FreshRun.test_missing_binary_is_not_installed` | 77 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::FreshRun.test_usage_all_prefers_fresh_and_skips_sessions` | 84 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::FreshRun.test_usage_never_injects_into_live_sessions` | 94 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::FreshRun.test_api_balance_failure_does_not_break_usage` | 110 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::NoUsageRows.test_codex_and_ucli_explain_instead_of_unsupported` | 123 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::NoUsageRows.test_note_follows_request_language_without_mutating_state` | 131 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::PruneTranscripts.test_only_pure_usage_command_files_after_since_are_removed` | 144 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::ResolvedBinaryFallback.test_claude_found_outside_path` | 162 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh.py::ResolvedBinaryFallback.test_provider_bin_override_used_by_usage_fresh_argv` | 175 | kapsam dışı | yok | oturumsuz kota okuma. İz: T7 (periyodik+kullanım) |

### `py/tests/test_usage_fresh_tui.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_usage_fresh_tui.py::P.test_parse_percent_fraction_reset` | 21 | kapsam dışı | yok | copilot TUI kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh_tui.py::P.test_parse_without_reset_unchanged` | 25 | kapsam dışı | yok | copilot TUI kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh_tui.py::P.test_argv_and_no_print_mode` | 29 | kapsam dışı | yok | copilot TUI kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh_tui.py::Ttl.test_ttl_cache_and_stale` | 40 | kapsam dışı | yok | copilot TUI kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh_tui.py::IsolatedNoRealRead.test_isolated_panel_does_not_launch_real_cli` | 52 | kapsam dışı | yok | copilot TUI kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh_tui.py::IsolatedNoRealRead.test_default_dir_is_not_isolated` | 57 | kapsam dışı | yok | copilot TUI kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh_tui.py::RealTmuxTrustDialog.test_dialog_accepted_before_command_in_private_cwd` | 78 | kapsam dışı | yok | copilot TUI kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh_tui.py::Sweep.test_dead_pid_socket_closed_and_unlinked` | 125 | kapsam dışı | yok | copilot TUI kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh_tui.py::Sweep.test_own_fresh_socket_untouched_but_own_old_one_closed` | 131 | kapsam dışı | yok | copilot TUI kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh_tui.py::Sweep.test_live_other_pid_fresh_untouched_old_closed` | 140 | kapsam dışı | yok | copilot TUI kota okuma. İz: T7 (periyodik+kullanım) |
| `test_usage_fresh_tui.py::Sweep.test_other_sockets_ignored_and_missing_dir_ok` | 147 | kapsam dışı | yok | copilot TUI kota okuma. İz: T7 (periyodik+kullanım) |

### `py/tests/test_usage_state.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_usage_state.py::UsageStateTest.test_cached_view_reads_state_without_polling` | 18 | kapsam dışı | yok | kota durum kaydı. İz: T7 (periyodik+kullanım) |
| `test_usage_state.py::UsageStateTest.test_empty_is_stale` | 31 | kapsam dışı | yok | kota durum kaydı. İz: T7 (periyodik+kullanım) |
| `test_usage_state.py::UsageStateTest.test_set_get_fresh_then_stale_after_10_min` | 37 | kapsam dışı | yok | kota durum kaydı. İz: T7 (periyodik+kullanım) |
| `test_usage_state.py::UsageStateTest.test_failed_read_keeps_last_good_entries_and_old_ok_at` | 46 | kapsam dışı | yok | kota durum kaydı. İz: T7 (periyodik+kullanım) |
| `test_usage_state.py::UsageStateTest.test_auth_backoff_expires_and_ignores_other_failures` | 59 | kapsam dışı | yok | kota durum kaydı. İz: T7 (periyodik+kullanım) |
| `test_usage_state.py::UsageStateTest.test_periodic_and_tick_skip_logged_out_cli_but_button_reads_it` | 67 | kapsam dışı | yok | kota durum kaydı. İz: T7 (periyodik+kullanım) |
| `test_usage_state.py::AccountCli.test_render_account_marks_stale_and_unreadable` | 87 | kapsam dışı | yok | kota durum kaydı. İz: T7 (periyodik+kullanım) |

### `py/tests/test_web_review_runner.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_web_review_runner.py::TestEvren.test_argv_safe_and_key_in_env_only` | 118 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_no_io_flag_when_unsupported` | 133 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_claude_env_filtered` | 137 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_redact_applied_and_answer_extracted` | 145 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_timeout_writes_partial` | 153 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_effort_always_sent_unless_model_rejects_it` | 172 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_partial_file_flag_added_only_when_supported` | 187 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_partial_file_path_is_symlink_free` | 196 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_killed_run_is_recovered_from_partial_file_masked` | 208 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_partial_without_report_heading_is_not_a_report` | 223 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_partial_turn_in_error_json_is_recovered` | 231 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_failed_run_keeps_error_log_masked_0600` | 240 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_successful_run_has_no_error_log` | 253 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_nonzero_no_output_is_error` | 257 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_busy_lock` | 261 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestEvren.test_missing_key_errors_and_releases_lock` | 267 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestCancel.test_cancel_kills_own_group_and_marks_partial` | 276 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestCancel.test_cancel_before_process_exists_is_not_swallowed` | 300 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestCancel.test_cancelled_before_spawn_kills_new_process` | 312 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestAgy.test_isolated_home_with_readonly_allow_list` | 345 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestAgy.test_bwrap_jail_wraps_argv_when_available` | 361 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestAgy.test_no_bwrap_or_jail_off_falls_back_to_allow_list` | 376 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestAgy.test_agy_model_quota_blocks_only_that_model_until_reset` | 394 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestAgy.test_tmpdir_is_writable_home_tmp_and_stale_entries_pruned` | 413 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestAgy.test_allow_override_and_off` | 427 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestAgy.test_ok_done_and_argv` | 458 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestAgy.test_label_mismatch_is_model_fallback_but_file_kept` | 470 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestAgy.test_no_log_is_model_fallback` | 476 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestAgy.test_old_log_not_taken_for_new_run` | 480 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestAgy.test_no_effort_for_non_gemini` | 489 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestAgy.test_model_not_in_agy_list` | 493 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestBannerLimit.test_monthly_quota_banner_with_rc0_is_limit_not_done` | 508 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestBannerLimit.test_real_report_mentioning_quota_stays_done` | 516 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestBannerLimit.test_month_start_helper` | 526 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestBodyless.test_failed_run_with_junk_body_is_error` | 551 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestBodyless.test_successful_exit_with_junk_body_is_error` | 555 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestBodyless.test_report_bodyless_rule` | 559 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestProviderErrorNoLesson.test_provider_errors_write_no_lesson` | 593 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestProviderErrorNoLesson.test_other_failures_still_write_lesson` | 602 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestProviderErrorNoLesson.test_model_quoting_provider_error_in_long_stderr_still_writes_lesson` | 608 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestProviderErrorNoLesson.test_quote_in_long_stderr_is_not_capacity` | 620 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestProviderErrorNoLesson.test_structured_error_with_long_stderr_is_capacity` | 631 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestProviderErrorNoLesson.test_ucli_own_retry_notice_still_backs_off_scaler` | 638 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestRecover.test_recover_on_start` | 647 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestRecover.test_recover_on_start_salvages_draft_report` | 655 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestRecover.test_recover_on_start_salvages_report_from_io_log` | 667 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestRecover.test_recover_on_start_no_report_head_keeps_file_empty` | 685 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestDetached.test_findings_are_saved_before_pair_turns_done` | 724 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestDetached.test_detached_run_writes_files_and_finishes` | 741 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestDetached.test_restart_adopts_live_run_and_finishes_it` | 766 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestDetached.test_run_finished_while_service_down_is_processed` | 781 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestDetached.test_pid_reuse_is_not_adopted_as_alive` | 789 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestDetached.test_adopt_keeps_pre_restart_io_log` | 794 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestDetached.test_adopt_failure_marks_partial_not_stuck_running` | 805 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |
| `test_web_review_runner.py::TestDetached.test_without_cfg_old_behavior_partial` | 816 | kapsam dışı | yok | reviewer koşucusu. İz: T8 (reviewer) |

### `py/tests/test_web_ucli_flags.py`

| Python testi | Satır | Durum | Rust testi / parite | Not / gerekçe ve iz |
|---|---|---|---|---|
| `test_web_ucli_flags.py::UcliFlagsTest.test_non_ucli_and_none` | 32 | karşılandı | `tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | `None` girdisi Rust tipinde yok |
| `test_web_ucli_flags.py::UcliFlagsTest.test_all_flags` | 36 | karşılandı | `tests/fake_proc.rs::ucli_flags_all_set` | yok |
| `test_web_ucli_flags.py::UcliFlagsTest.test_no_flags` | 40 | karşılandı | `tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | yok |
| `test_web_ucli_flags.py::UcliFlagsTest.test_bad_cost_value` | 44 | karşılandı | `tests/fake_proc.rs::mirrors_terminal_and_ucli_flag_edges` | yok |
| `test_web_ucli_flags.py::UcliFlagsTest.test_process_error_returns_none_and_not_cached` | 48 | karşılandı | `tests/fake_proc.rs::ucli_flags_lost_process_is_none_and_not_cached` | Rust'ta pid önbelleği yok (sapma 9) |
| `test_web_ucli_flags.py::UcliFlagsTest.test_tools_from_status_file_are_read_each_time` | 53 | kapsam dışı | yok | durum dosyasından araç listesi ve pid önbelleği (sapma 9). İz: T1 (durum) |
| `test_web_ucli_flags.py::UcliFlagsTest.test_cached_per_pid` | 73 | kapsam dışı | yok | durum dosyasından araç listesi ve pid önbelleği (sapma 9). İz: T1 (durum) |
