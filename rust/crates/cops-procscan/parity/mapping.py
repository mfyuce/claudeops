"""Eşleme tablosu (sahip eki "İŞLEVCE EŞLİK"): `docs/rs-proc-mapping.md` üretir ve denetler.

Koşum (repo kökünden):
  python3 -I rust/crates/cops-procscan/parity/mapping.py            tabloyu yazar
  python3 -I rust/crates/cops-procscan/parity/mapping.py --check    tabloyu `ast` çıktısı ve Rust kaynağıyla karşılaştırır

`py/` modülleri İÇE AKTARILMAZ: yalnız dosya okunup `ast` ile ayrıştırılır. Yazılan tek dosya tablodur.
`--check` sıfırdan farklı çıkar: `ast`te olup tabloda olmayan satır, tabloda olup `ast`te olmayan satır, boş hücre,
kaynakta bulunmayan Rust adı, bayat tablo ya da bayat eşleme verisi. EKSİK satırlar `--check`i düşürmez
(sayılır ve listelenir); `--check --strict` EKSİK varsa da düşer.

Eşleme verisi ELLE girilir:
- tanımlar: her `ast` adı tek tek yazılır;
- kapsanan davranışa değen testler tek tek yazılır;
- bu crate'in davranışını sınamayan test dosyaları dosya başına (gerekçe, iz, sayı, ad özeti) yazılır. Dosyaya test
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
OUT = REPO / "docs" / "rs-proc-mapping.md"

OK, OOS, GAP = "karşılandı", "kapsam dışı", "EKSİK"

# ── kapsam ───────────────────────────────────────────────────────────────────
FULL = ["discovery.py", "session.py", "session_usage.py", "mirrors.py", "needs_ho.py", "commands/ls.py"]
PARTIAL = ["providers/__init__.py", "providers/base.py", "providers/claude_provider.py", "providers/codex_provider.py",
           "providers/copilot_provider.py", "providers/agy_provider.py", "providers/shell_provider.py",
           "providers/ucli_provider.py", "commands/usage.py", "model_usage.py", "orphan_watch.py", "paths.py"]
# yalnız crate'in üstlendiği tanımlar ve doğrudan yardımcıları
SUBSET = {
    "commands/web.py": ["_usage_total", "_process_started_at", "_UCLI_FLAGS_CACHE", "_ucli_flags", "_with_ucli_tools",
                        "_find_gnome_terminal_server", "_diag_status"],
    "tmux_backend.py": ["TMUX_SOCKET", "_ANCESTOR_WALK_LIMIT", "is_tmux_backed"],
}
TEST_IMPORT = re.compile(r"claudeops\.(discovery|session|session_usage|mirrors|needs_ho|commands\.ls|providers|"
                         r"commands\.usage|model_usage|orphan_watch|paths)(\.|$)")
TEST_SYMBOL = re.compile(r"\b(_ucli_flags|_usage_total|_process_started_at|is_tmux_backed)\b")

# ── izler ────────────────────────────────────────────────────────────────────
W0A = "W0-a durum (rs/state)"
W0B = "W0-b tmux (rs/tmux)"
SAG = "W1-pre sağlayıcı (rs/prov); canlıya T4"
T1, T2, T3 = "T1 (durum)", "T2 (terminal)", "T3 (dosya)"
T4, T5, T6 = "T4 (yaşam döngüsü)", "T5 (federasyon)", "T6 (CLI)"
T7, T9, T10 = "T7 (periyodik+kullanım)", "T9 (enterprise)", "T10 (değnekçi)"
T8 = "T8 (reviewer)"
# sağlayıcı kodunu üstlenen iz rs/prov (dal `rs/prov` `docs/rs-prov.md` grupları); canlı uca bağlama T1/T4
CHAT = "rs/prov (G2 `chat.rs`; `sid_for_stopped_session` G1, açık); canlı bağlantı T1"
LIVE = "rs/prov (G3 transkript okuma); canlı bağlantı T1"
RESUME = "rs/prov (G1, açık); canlı bağlantı T4"


def ok(names, rust, tests, note=""):
    return (names.split(), OK, rust, tests, note)


def oos(names, why, track):
    return (names.split(), OOS, "", "", f"{why}. İz: {track}")


def gap(names, why, rust="", tests=""):
    return (names.split(), GAP, rust, tests, why)


G_INFO = "G:provider_detect_and_info"
DISC = "U:providers.rs::detect G:provider_detect_and_info I:fake_proc.rs::discovers_each_cli_and_names"

# ── tanım eşlemesi ───────────────────────────────────────────────────────────
DEFS: dict = {}

DEFS["discovery.py"] = [
    ok("_sessions_from_json", "discovery.rs::sessions_from_json discovery.rs::json_pid discovery.rs::JsonPid",
       "I:fake_proc.rs::json_source_merges_with_proc_scan I:fake_proc.rs::broken_proc_fields "
       "I:fake_proc.rs::bad_session_files_are_skipped_and_counted I:fake_proc.rs::overflowing_pids_are_skipped_and_counted "
       "P:scan_sessions",
       "sapma 5; bozuk dosya ve sıfır/negatif pid atlanır (TBD#365). Python düzeltildi: 6ae5da3. `pid_t`ye sığmayan pid "
       "(2**31+, `Infinity`) atlanır ve sayılır (`Infinity`/`1e400` Rust'ta geçersiz dosya). Python düzeltildi: 35a1eb78"),
    ok("_skipped", "discovery.rs::ScanDiag.session_files_bad", "I:fake_proc.rs::bad_session_files_are_skipped_and_counted",
       "Python sayacı süreç geneli, Rust tarama başına. Python düzeltildi: 6ae5da3. Tanılama `diag.skipped`ta görünür "
       "(Rust `scan` çıktısında `diag`). Python düzeltildi: 1af088ef"),
    ok("fold_background", "session.rs::fold_background",
       "U:session.rs::background_folds_into_single_front U:session.rs::background_fold_edge_cases_like_python "
       "I:fake_proc.rs::background_session_folds"),
    ok("_ancestors", "discovery.rs::ancestors", "I:real_proc.rs::real_background_subshell_is_one_session",
       "sapma 2 (başka kullanıcının sürecinde durur)"),
    ok("fold_subshells", "session.rs::fold_subshells",
       "U:session.rs::subshell_tree_like_python U:session.rs::subshells_fold_only_for_shell "
       "I:real_proc.rs::real_background_subshell_is_one_session"),
    ok("fallback_name", "discovery.rs::fallback_name",
       "U:discovery.rs::fallback_names G:names_paths_and_token_format I:fake_proc.rs::discovers_each_cli_and_names"),
    ok("terminal_lost", "procfs.rs::OwnProc::terminal_lost status.rs::Probe::terminal_lost",
       "I:fake_proc.rs::tmux_terminal_and_orphans I:fake_proc.rs::mirrors_terminal_and_ucli_flag_edges P:scan_sessions"),
    ok("IDLE_SPIN_CPU", "status.rs::IDLE_SPIN_CPU", "I:fake_proc.rs::tmux_terminal_and_orphans"),
    ok("idle_spin", "status.rs::Probe::idle_spin", "I:fake_proc.rs::tmux_terminal_and_orphans P:scan_sessions",
       "Rust `tmux`i parametre almaz, kendisi hesaplar"),
    ok("_SPIN_SINCE", "status.rs::OrphanTracker.since", "I:fake_proc.rs::tmux_terminal_and_orphans",
       "modül sözlüğü yerine çağıranın tuttuğu örnek"),
    ok("SPIN_SECONDS", "status.rs::SPIN_SECONDS", "I:fake_proc.rs::tmux_terminal_and_orphans"),
    ok("orphan_report", "status.rs::OrphanTracker::report",
       "I:fake_proc.rs::tmux_terminal_and_orphans P:scan_orphans",
       "cpu yeniden yuvarlanmaz (taramada zaten tek ondalık)"),
    ok("find_sessions", "discovery.rs::find_sessions discovery.rs::Scan discovery.rs::CpuMode",
       "I:fake_proc.rs::json_source_merges_with_proc_scan I:fake_proc.rs::json_sid_merge_rules_like_python "
       "I:fake_proc.rs::cpu_from_two_samples I:fake_proc.rs::discovers_each_cli_and_names P:scan_sessions",
       "CPU yolu yalnız sahte `/proc` ile sınanır (canlı parite `--no-cpu`); cmdline yalnız kendi süreçte okunur. Python düzeltildi: 6ae5da3"),
    ok("find_by_name", "discovery.rs::find_by_name",
       "I:fake_proc.rs::find_by_name_is_exact_and_returns_every_process"),
    ok("duplicates", "session.rs::duplicates",
       "U:session.rs::subshells_fold_only_for_shell U:list.rs::table_matches_python_layout P:scan_duplicates"),
]

DEFS["session.py"] = [
    ok("_NAME_RE", "session.rs::base_name",
       "U:session.rs::base_matches_python_regex G:names_paths_and_token_format"),
    ok("Session", "session.rs::Session", "P:scan_sessions I:fake_proc.rs::discovers_each_cli_and_names",
       "ek alan `proc_id` (JSON'a yazılmaz)"),
    ok("Session.name", "session.rs::Session.name", "P:scan_sessions I:fake_proc.rs::discovers_each_cli_and_names"),
    ok("Session.pid", "session.rs::Session.pid", "P:scan_sessions I:fake_proc.rs::background_session_folds"),
    ok("Session.cwd", "session.rs::Session.cwd", "P:scan_sessions I:fake_proc.rs::json_source_merges_with_proc_scan"),
    ok("Session.sid", "session.rs::Session.sid", "P:scan_sessions I:fake_proc.rs::json_sid_merge_rules_like_python"),
    ok("Session.model", "session.rs::Session.model", "P:scan_sessions U:providers.rs::claude_info"),
    ok("Session.permission_mode", "session.rs::Session.permission_mode", "P:scan_sessions U:providers.rs::codex_info"),
    ok("Session.effort", "session.rs::Session.effort", "P:scan_sessions U:providers.rs::ucli_effort_presets"),
    ok("Session.cpu", "session.rs::Session.cpu", "I:fake_proc.rs::cpu_from_two_samples"),
    ok("Session.cli", "session.rs::Session.cli", "P:scan_sessions I:fake_proc.rs::json_sid_merge_rules_like_python"),
    ok("Session.resumed", "session.rs::Session.resumed",
       "P:scan_sessions I:fake_proc.rs::json_source_merges_with_proc_scan"),
    ok("Session.kind", "session.rs::Session.kind", "P:scan_sessions I:fake_proc.rs::background_session_folds"),
    ok("Session.job_id", "session.rs::Session.job_id", "P:scan_sessions I:fake_proc.rs::background_session_folds"),
    ok("Session.parked_job_id", "session.rs::Session.parked_job_id",
       "P:scan_sessions I:fake_proc.rs::background_session_folds"),
    ok("Session.bg_pid", "session.rs::Session.bg_pid", "P:scan_sessions I:fake_proc.rs::background_session_folds"),
    ok("Session.is_fresh", "session.rs::Session::is_fresh",
       "P:scan_sessions I:fake_proc.rs::json_source_merges_with_proc_scan "
       "U:session.rs::is_fresh_flag_and_sid_combinations I:fake_proc.rs::is_fresh_without_json_entry_for_every_cli"),
    ok("Session.base", "session.rs::Session::base session.rs::base_name",
       "U:session.rs::base_matches_python_regex G:names_paths_and_token_format P:scan_sessions"),
    ok("Session.model_short", "session.rs::Session::model_short", "U:session.rs::model_short P:list_json"),
    ok("Session.active", "session.rs::Session::active",
       "U:session.rs::active_above_two_percent I:fake_proc.rs::find_by_name_is_exact_and_returns_every_process"),
]

DEFS["session_usage.py"] = [
    ok("CACHE_SECONDS", "usage.rs::CACHE_TTL", "U:usage.rs::cache_respects_ttl",
       "test TTL kuralını sınar, 30 sn değerini değil"),
    ok("_MAX_CACHED_FILES", "usage.rs::MAX_CACHED_FILES usage.rs::Ordered",
       "U:usage.rs::file_cache_evicts_in_insertion_order U:usage.rs::summary_cache_evicts_oldest_200",
       "ekleme sırasıyla tahliye (dosya durumu 1, özet 200), Python gibi; küçülen dosya yer açtırmaz. Python düzeltildi: 6ae5da3"),
    ok("_ZERO", "usage.rs::Totals::add", "G:usage_totals_two_calls", "alan sırası sabit dizi"),
    ok("_lock", "usage.rs::lock usage.rs::UsageCache",
       "U:usage.rs::cache_first_none_then_value_and_error_keeps_last_good"),
    ok("_files", "usage.rs::UsageReader.files usage.rs::FileState",
       "U:usage.rs::bad_row_is_skipped_and_counted G:usage_totals_two_calls"),
    ok("_summaries", "usage.rs::UsageCache.summaries usage.rs::Summary",
       "U:usage.rs::cache_first_none_then_value_and_error_keeps_last_good"),
    ok("_int", "usage.rs::count", "G:usage_totals_two_calls P:usage_real U:usage.rs::overflowing_count_row_does_not_blank_total",
       "sapma 4 ve 6; u64'te doyar. `int(inf)` OverflowError toplamı None yapıyordu, artık 0; Rust'ta serde o satırı "
       "ayrıştırmaz (sapma 4). Python düzeltildi: 35a1eb78"),
    ok("_parse _from_row", "usage.rs::parse usage.rs::py_key",
       "G:usage_totals_two_calls U:usage.rs::python_key_equality U:usage.rs::bad_row_is_skipped_and_counted "
       "P:usage_real", "sapma 4; dizgi olmayan model ve hashlenemeyen anahtar atlanır, sayılır. Python düzeltildi: 6ae5da3"),
    ok("_skipped", "usage.rs::FileState.bad usage.rs::Usage.skipped_rows", "U:usage.rs::bad_row_is_skipped_and_counted "
       "U:usage.rs::long_lines_are_skipped_and_counted G:usage_totals_two_calls P:usage_real",
       "Python süreç geneli sayaç, Rust dosya başına. Python düzeltildi: 6ae5da3. Rust `skipped_rows` artık JSON'da; "
       "altın vektör ve parite koşucusu Python artışıyla kıyaslar; Python Tanılama `diag.skipped`. Python düzeltildi: 1af088ef"),
    ok("_MAX_LINE_BYTES _SKIP_CHUNK", "transcript.rs::MAX_LINE_BYTES transcript.rs::read_line transcript.rs::Line "
       "usage.rs::FileState.skip", "U:usage.rs::long_lines_are_skipped_and_counted",
       "64 MiB (ölçülen en uzun satır 13.234.801 bayt); tampon sınır+1'i aşmaz, kalan parça parça atılır; dosya sonundaki "
       "yarım uzun satır bir kez sayılır. Python düzeltildi: 66b47a37"),
    ok("_merge", "usage.rs::UsageReader::update", "I:fake_proc.rs::usage_dedups_subagents_and_increments "
       "G:usage_totals_two_calls"),
    ok("_update_file", "usage.rs::UsageReader::update",
       "I:fake_proc.rs::usage_dedups_subagents_and_increments U:usage.rs::bad_row_is_skipped_and_counted "
       "U:usage.rs::file_cache_evicts_in_insertion_order",
       "`mtime` tutulmaz (okuyanı yok); küçülen dosya yerinde sıfırlanır. Python düzeltildi: 6ae5da3. Satır sınırı. "
       "Python düzeltildi: 66b47a37"),
    ok("_sum", "usage.rs::sum usage.rs::Totals::add", "G:usage_totals_two_calls P:usage_real"),
    ok("usage_for_path", "usage.rs::UsageReader::usage_for_path usage.rs::Usage",
       "I:fake_proc.rs::usage_dedups_subagents_and_increments G:usage_totals_two_calls P:usage_real "
       "U:usage.rs::bad_row_is_skipped_and_counted", "alt ajan dosyasındaki bozuk satır toplamı boşaltmaz. Python düzeltildi: 6ae5da3"),
    ok("_refresh", "usage.rs::UsageCache::refresh",
       "U:usage.rs::cache_first_none_then_value_and_error_keeps_last_good"),
    ok("cached_usage_for_path", "usage.rs::UsageCache::get",
       "U:usage.rs::cache_first_none_then_value_and_error_keeps_last_good U:usage.rs::cache_respects_ttl "
       "U:usage.rs::spawn_failure_does_not_lock_the_path",
       "başlatılamayan iş parçacığı bayrağı geri alınır (eski sapma 10). Python düzeltildi: 6ae5da3"),
    ok("fmt_tokens", "usage.rs::fmt_tokens", "U:usage.rs::fmt_tokens_python_examples G:names_paths_and_token_format"),
]

DEFS["mirrors.py"] = [
    ok("LOCAL_HOST", "mirrors.rs::LOCAL_HOST", "U:mirrors.rs::specs G:provider_detect_and_info"),
    ok("_VALUE_FLAGS", "mirrors.rs::VALUE_FLAGS", "U:mirrors.rs::specs G:provider_detect_and_info"),
    ok("spec_from_cmdline", "mirrors.rs::spec_from_cmdline", "U:mirrors.rs::specs G:provider_detect_and_info"),
    ok("note_mirror", "mirrors.rs::note_mirror", "U:mirrors.rs::notes_accumulate P:scan_mirrors"),
    ok("running_mirrors", "mirrors.rs::running_mirrors",
       "I:fake_proc.rs::mirrors_terminal_and_ucli_flag_edges I:real_proc.rs::real_viewer_process_is_seen",
       "cmdline yalnız uid süzgecinden sonra. Python düzeltildi: 6ae5da3"),
    ok("focus_window", "mirrors.rs::focus_window mirrors.rs::focus_with",
       "U:mirrors.rs::focus_reports_exit_status_and_passes_exact_args U:proc_cmd.rs::output_status_and_timeout",
       "test iç `focus_with`i sahte programla çağırır"),
]

DEFS["needs_ho.py"] = [
    ok("_BASELINE_DIR", "needs_ho.rs::NeedsHo::baseline_get needs_ho.rs::NeedsHo.state_dir",
       "I:needs_ho_git.rs::git_signals_and_baseline P:needs_ho_repos"),
    ok("_git", "needs_ho.rs::git needs_ho.rs::GIT_TIMEOUT proc_cmd.rs::run",
       "I:needs_ho_git.rs::git_signals_and_baseline U:proc_cmd.rs::output_status_and_timeout"),
    ok("_is_git_repo", "needs_ho.rs::is_git_repo", "I:needs_ho_git.rs::git_signals_and_baseline P:needs_ho_repos"),
    ok("repo_dirty", "needs_ho.rs::repo_dirty", "I:needs_ho_git.rs::git_signals_and_baseline P:needs_ho_repos"),
    ok("repo_untracked_count", "needs_ho.rs::repo_untracked_count",
       "I:needs_ho_git.rs::git_signals_and_baseline P:needs_ho_repos"),
    ok("_repo_key", "needs_ho.rs::repo_key", "P:needs_ho_repos I:needs_ho_git.rs::git_signals_and_baseline",
       "Python'un yazdığı baseline'ı Rust okur (aynı sha1 adı)"),
    ok("_repo_baseline_get", "needs_ho.rs::NeedsHo::baseline_get",
       "I:needs_ho_git.rs::git_signals_and_baseline P:needs_ho_repos"),
    ok("repo_baseline_set", "needs_ho.rs::NeedsHo::repo_baseline_set needs_ho.rs::write_atomic",
       "I:needs_ho_git.rs::git_signals_and_baseline U:needs_ho.rs::baseline_is_written_atomically",
       "atomik (geçici dosya + rename). Python düzeltildi: 6ae5da3"),
    ok("repo_committed_since", "needs_ho.rs::NeedsHo::repo_committed_since needs_ho.rs::committed_after "
       "needs_ho.rs::from_iso", "I:needs_ho_git.rs::git_signals_and_baseline G:committed_after_iso_rules "
       "U:needs_ho.rs::iso_times_compare_as_instants P:needs_ho_repos", "sapma 7"),
    ok("_RFH", "needs_ho.rs::RFH", "G:rfh_marker"),
    ok("rfh_marker_in rfh_marker_in::re1", "needs_ho.rs::rfh_marker_in",
       "G:rfh_marker U:needs_ho.rs::prose_mention_is_not_a_marker U:needs_ho.rs::heading_and_bare_line_count "
       "U:needs_ho.rs::code_block_and_quote_do_not_count"),
    ok("_skipped", "needs_ho.rs::Checked.skipped", "U:needs_ho.rs::broken_input_is_skipped_and_counted "
       "U:needs_ho.rs::long_lines_are_skipped_and_counted",
       "Python süreç geneli sayaç, Rust çağrı başına (sınırı aşan satır da aynı sayaçta; Python ayrı anahtar "
       "`transcript_line_too_long`). Python düzeltildi: 6ae5da3. Tanılama `diag.skipped`. Python düzeltildi: 1af088ef"),
    ok("_MAX_LINE_BYTES _SKIP_CHUNK _lines", "transcript.rs::MAX_LINE_BYTES transcript.rs::read_line needs_ho.rs::each_row",
       "U:needs_ho.rs::long_lines_are_skipped_and_counted G:transcripts_needs_ho P:needs_ho_transcripts",
       "64 MiB; metin kipi satır sonları (`\\r`) ve U+FFFD aynı (altın vektörler değişmedi). Python düzeltildi: 66b47a37"),
    ok("_text_blocks", "needs_ho.rs::text_blocks",
       "U:needs_ho.rs::broken_input_is_skipped_and_counted G:transcripts_needs_ho",
       "dizgi olmayan `text` yok sayılır ve sayılır. Python düzeltildi: 6ae5da3"),
    ok("handover_done", "needs_ho.rs::handover_done needs_ho.rs::each_row needs_ho.rs::Checked",
       "G:transcripts_needs_ho U:needs_ho.rs::only_assistant_rows_carry_the_marker "
       "U:needs_ho.rs::broken_input_is_skipped_and_counted P:needs_ho_transcripts",
       "sapma 4; beklenmeyen tipte kayıt atlanır ve sayılır. Python düzeltildi: 6ae5da3"),
    ok("has_real_user_turn", "needs_ho.rs::has_real_user_turn needs_ho.rs::each_row",
       "G:transcripts_needs_ho U:needs_ho.rs::real_user_turn_filters U:needs_ho.rs::broken_input_is_skipped_and_counted "
       "P:needs_ho_transcripts", "nesne olmayan `message` atlanır ve sayılır. Python düzeltildi: 6ae5da3"),
    ok("needs_ho", "needs_ho.rs::NeedsHo::needs_ho",
       "I:needs_ho_git.rs::git_signals_and_baseline U:needs_ho.rs::needs_ho_decides_with_bad_rows P:needs_ho_repos",
       "kullanılmayan `sid` parametresi alınmadı; bozuk satırda istisna yok. Python düzeltildi: 6ae5da3"),
]

DEFS["commands/ls.py"] = [
    ok("register", "bin/cops-procscan.rs::run", "P:list_json P:list_table",
       "`--base` ayrıştırması ve `ls` takma adı ikili düzeyinde sınanmıyor; `cops list` komutuna bağlama T6"),
    ok("run", "list.rs::render bin/cops-procscan.rs::run",
       "U:list.rs::json_is_sorted_valid_and_has_no_table U:list.rs::table_matches_python_layout P:list_json "
       "P:list_table"),
]

DEFS["providers/__init__.py"] = [
    oos("DEFAULT_CLI", "yeni oturum açılışının varsayılan sağlayıcısı", SAG),
    ok("PROVIDERS", "providers.rs::Cli providers.rs::Cli::detect", f"{DISC}",
       "bir argv en çok bir sağlayıcıya uyduğundan sıra önemsiz"),
    oos("get_provider", "ada göre sağlayıcı nesnesi (açılış ve durum alanları); taramada gerekmiyor", SAG),
]

DEFS["providers/base.py"] = [
    ok("cmd_arg", "providers.rs::arg", f"{G_INFO} U:providers.rs::claude_info"),
    ok("CliProvider", "providers.rs::Cli", DISC, "yalnız tanıma/ayrıştırma yüzeyi; kalan metotlar kendi satırında"),
    ok("CliProvider.name", "providers.rs::Cli::as_str", G_INFO),
    ok("CliProvider.matches_proc", "providers.rs::Cli::detect", DISC),
    ok("CliProvider.extract_name", "providers.rs::Cli::extract_name",
       "I:fake_proc.rs::discovers_each_cli_and_names I:fake_proc.rs::broken_proc_fields"),
    ok("CliProvider.extract_info", "providers.rs::Cli::extract_info providers.rs::Info", G_INFO),
    oos("OneshotError CliProvider.oneshot_argv CliProvider.oneshot", "tek atımlık model çağrısı", f"{SAG}; {T10}"),
    oos("McpServerSpec McpServerSpec.name McpServerSpec.command McpServerSpec.args McpServerSpec.allowed_tools "
        "CliProvider.mcp_needs_cwd CliProvider.mcp_launch_args CliProvider.mcp_setup_command",
        "MCP kaydı ve açılış argümanları", SAG),
    oos("CliProvider.accepts_cli_opts CliProvider.validate_cli_opts CliProvider.build_inner_command "
        "CliProvider.env_overrides CliProvider.model_choices CliProvider.refresh_stored_model "
        "CliProvider.permission_modes CliProvider.effort_levels CliProvider.model_effort_levels "
        "CliProvider.effort_levels_for CliProvider.default_permission_mode CliProvider.preferred_default_model "
        "CliProvider.default_effort CliProvider.resolve_effort",
        "açılış argv/env ve model/effort/izin kuralları", SAG),
    oos("CliProvider.resolve_resume_id CliProvider.has_conversation CliProvider.wants_handover_wrapup "
        "CliProvider.wants_stuck_recovery CliProvider.handover_model_downgrade CliProvider.apply_live_model_switch "
        "CliProvider.handover_effort_downgrade CliProvider.apply_live_effort_switch CliProvider.compact_command "
        "CliProvider.effort_switch_keeps_cache CliProvider.snapshot_for_live_sid CliProvider.discover_live_sid",
        "devam/devir/canlı model değiştirme", T4),
    oos("CliProvider.last_exchange CliProvider.full_history CliProvider.sid_for_stopped_session "
        "CliProvider.last_message_role", "sohbet geçmişi okuma", CHAT),
    oos("CliProvider.prompt_cache_ttl_seconds CliProvider.last_request_epoch CliProvider.live_busy "
        "CliProvider.live_tools CliProvider.live_context CliProvider.live_usage CliProvider.live_failed_turns "
        "CliProvider.live_phase", "`/api/status` satır alanları (durum dosyası/transkript)", T1),
    oos("CliProvider.dismiss_stray_dialog CliProvider.input_settle_delay CliProvider.prepare_input "
        "CliProvider.context_needs_dismiss CliProvider.usage_needs_dismiss CliProvider.mode_status_patterns "
        "CliProvider.busy_status_pattern CliProvider.background_work CliProvider.cyclable_modes",
        "tmux ekranı okuma ve tuş gönderme", f"{T2}; {W0B}"),
    oos("CliProvider.usage_fresh_argv CliProvider.usage_fresh_tui_argv CliProvider.usage_auth_missing "
        "CliProvider.parse_fresh_usage CliProvider.usage_command CliProvider.parse_usage_text "
        "CliProvider.context_command CliProvider.parse_context_text", "kota/bağlam okuma ve ayrıştırma", T7),
    oos("CliProvider.extra_file_roots", "dosya gezgini kökleri", T3),
]

C = "ClaudeProvider."
DEFS["providers/claude_provider.py"] = [
    ok("_encode_cwd _encode_cwd::re1", "transcript.rs::encode_cwd",
       "U:transcript.rs::encodes_non_ascii_per_char G:names_paths_and_token_format"),
    ok("jsonl_path_for", "transcript.rs::jsonl_path_for", "I:fake_proc.rs::transcript_requires_exact_sid "
       "P:scan_sessions", "sapma 1: yalnız tam sid; en yeni dosyaya düşüş yok; `/`/NUL içeren sid yok sayılır. Python düzeltildi: 6ae5da3. "
       "Sid VARKEN Python da yalnız tam dosya, yoksa None (sözleşme: None = transkript yok). Python düzeltildi: 43753998. "
       "Kalan kasıtlı fark: sid YOKKEN Python tahmini (koşucu `KNOWN_DEVIATIONS`, `python_guess_without_sid`)"),
    oos("_safe_mtime find_latest_jsonl",
        "cwd'deki en yeni transkript düşüşü BİLEREK taşınmadı (sapma 1); düşüşe dayanan Python çağıranları taşınırken "
        "yeniden karar gerekir", f"{T1}; {T4}"),
    ok("ClaudeProvider", "providers.rs::Cli", DISC, "yalnız tanıma/ayrıştırma; kalan metotlar kendi satırında"),
    ok(C + "name", "providers.rs::Cli::as_str", G_INFO),
    ok(C + "matches_proc", "providers.rs::Cli::detect", DISC),
    ok(C + "extract_name", "providers.rs::Cli::extract_name", "I:fake_proc.rs::discovers_each_cli_and_names"),
    ok(C + "extract_info", "providers.rs::Cli::extract_info", f"{G_INFO} U:providers.rs::claude_info"),
    oos("MODEL_CHOICES PERMISSION_MODES EFFORT_LEVELS _SONNET_PIN_RE _sonnet_version _EFFORT_BUSTS_CACHE_RE "
        "MCP_CONFIG_PATH _mcp_config_path _write_mcp_config_file _HELP_CACHE _HELP_TIMEOUT_SECONDS claude_help_text "
        "claude_supports_flag claude_supports_flag::re1 "
        + " ".join(C + n for n in
                   "build_inner_command oneshot_argv mcp_launch_args preferred_default_model default_effort "
                   "model_choices refresh_stored_model permission_modes effort_levels".split()),
        "açılış argv'si, MCP, model/effort/izin kuralları", SAG),
    oos("_META_HEAD_LINES _RESUME_SCAN_LIMIT _jsonl_meta _same_path _META_CACHE _META_CACHE_MAX _jsonl_meta_cached "
        "_STUB_MAX_BYTES _has_chat_rows "
        + " ".join(C + n for n in
                   "compact_command handover_model_downgrade _MODEL_SWITCH_TIMEOUT_SECONDS "
                   "_MODEL_SWITCH_POLL_SECONDS apply_live_model_switch handover_effort_downgrade "
                   "effort_switch_keeps_cache _EFFORT_SWITCH_TIMEOUT_SECONDS _EFFORT_SWITCH_POLL_SECONDS "
                   "_EFFORT_SWITCH_DONE_MARKERS apply_live_effort_switch".split()),
        "devam kimliği, devir ve canlı model/effort değiştirme", T4),
    oos("session_file_sid " + C + "resolve_resume_id", "oturum kimliği ve devam kimliği", RESUME),
    oos("_LAST_MODEL_CHUNK_BYTES _LAST_MODEL_MAX_BYTES _row_epoch _last_assistant_value last_assistant_model "
        "last_assistant_effort PROMPT_CACHE_TTL_SECONDS _real_request_epoch last_real_request_epoch "
        "live_or_spawn_model live_or_spawn_effort " + C + "prompt_cache_ttl_seconds " + C + "last_request_epoch",
        "transkriptten canlı model/effort ve önbellek yaşı", LIVE),
    oos("_extract_text _is_real_user_text "
        + " ".join(C + n for n in "_transcript_lines last_exchange full_history sid_for_stopped_session".split()),
        "sohbet geçmişi okuma", CHAT),
    oos("MODE_STATUS_PATTERNS CYCLABLE_MODES BUSY_STATUS_PATTERN "
        + " ".join(C + n for n in
                   "usage_needs_dismiss context_needs_dismiss _STRAY_DIALOG_TIMEOUT_SECONDS "
                   "_STRAY_DIALOG_POLL_SECONDS dismiss_stray_dialog mode_status_patterns background_work "
                   "busy_status_pattern cyclable_modes".split()),
        "tmux ekranı okuma ve tuş gönderme", f"{T2}; {W0B}"),
    oos("_USAGE_HEADER_RE _USAGE_PERCENT_RE _USAGE_RESETS_RE _USAGE_FRESH_RE _CONTEXT_TOTAL_RE _CONTEXT_CATEGORY_RE "
        + " ".join(C + n for n in
                   "usage_command parse_usage_text usage_fresh_argv parse_fresh_usage context_command "
                   "parse_context_text".split()), "kota/bağlam okuma ve ayrıştırma", T7),
    oos(C + "extra_file_roots", "dosya gezgini kökleri", T3),
]

X = "CodexProvider."
DEFS["providers/codex_provider.py"] = [
    ok("_NON_SESSION_SUBCOMMANDS", "providers.rs::CODEX_NON_SESSION", f"{G_INFO} U:providers.rs::detect",
       "iki liste 25 öğeyle eşit (elle karşılaştırıldı); testler yalnız birkaç öğeyi sınar"),
    ok("_PERMISSION_FLAGS", "providers.rs::codex_mode", f"{G_INFO} U:providers.rs::codex_info",
       f"yalnız ters eşleme (argv -> mod); açılış yönü {SAG}"),
    ok("_config_value", "providers.rs::codex_config", f"{G_INFO} U:providers.rs::codex_info"),
    ok("CodexProvider", "providers.rs::Cli", DISC, "yalnız tanıma/ayrıştırma"),
    ok(X + "name", "providers.rs::Cli::as_str", G_INFO),
    ok(X + "matches_proc", "providers.rs::Cli::detect", f"{G_INFO} U:providers.rs::detect"),
    ok(X + "extract_name", "providers.rs::Cli::extract_name",
       "I:fake_proc.rs::discovers_each_cli_and_names I:fake_proc.rs::broken_proc_fields"),
    ok(X + "extract_info", "providers.rs::Cli::extract_info", f"{G_INFO} U:providers.rs::codex_info"),
    oos("CODEX_HOME MODELS_CACHE PERMISSION_MODES EFFORT_LEVELS FALLBACK_MODELS _MODELS_TTL "
        + " ".join(X + n for n in "__init__ build_inner_command mcp_launch_args env_overrides model_choices "
                   "permission_modes effort_levels model_effort_levels".split()),
        "açılış argv/env, model/effort/izin kuralları", SAG),
    oos(X + "resolve_resume_id _session_meta", "devam kimliği", T4),
    oos("SESSIONS_DIR _ROLLOUT_UUID_RE _MAX_ROLLOUT_SCAN _safe_mtime _codex_text _is_real_codex_user_text "
        + " ".join(X + n for n in "_rollout_path _transcript_lines last_exchange full_history".split()),
        "rollout dosyası ve sohbet geçmişi", CHAT),
    oos("BUSY_STATUS_PATTERN " + X + "busy_status_pattern " + X + "input_settle_delay " + X + "background_work",
        "tmux ekranı okuma ve tuş gönderme", f"{T2}; {W0B}"),
    oos(X + "live_context", "`/api/status` bağlam alanı", T1),
]

P_ = "CopilotProvider."
DEFS["providers/copilot_provider.py"] = [
    ok("CopilotProvider", "providers.rs::Cli", DISC, "yalnız tanıma/ayrıştırma"),
    ok(P_ + "name", "providers.rs::Cli::as_str", G_INFO),
    ok(P_ + "matches_proc", "providers.rs::Cli::detect", f"{G_INFO} U:providers.rs::detect"),
    ok(P_ + "extract_name", "providers.rs::Cli::extract_name", "I:fake_proc.rs::discovers_each_cli_and_names",
       "agy/codex ile aynı kol; copilot'a özel ad testi yok"),
    ok(P_ + "extract_info", "providers.rs::Cli::extract_info", f"{G_INFO} U:providers.rs::copilot_info"),
    oos("_BYOK_ENV_FILE _BYOK_ENV_MANAGED_MARKER _sync_byok_env_file MODEL_CHOICES PERMISSION_MODES EFFORT_LEVELS "
        "_PERMISSION_FLAGS "
        + " ".join(P_ + n for n in "build_inner_command env_overrides model_choices permission_modes "
                   "effort_levels".split()), "açılış argv/env, model/effort/izin kuralları", SAG),
    oos("_RESUME_SCAN_LIMIT trust_folder trust_folder::re1 " + P_ + "resolve_resume_id",
        "devam kimliği ve klasöre güven kaydı", T4),
    oos("SESSION_STORE_DB _connect_ro " + " ".join(P_ + n for n in "_turns last_exchange full_history".split()),
        "oturum deposu ve sohbet geçmişi", CHAT),
    oos("MODE_STATUS_PATTERNS BUSY_STATUS_PATTERN " + P_ + "mode_status_patterns " + P_ + "busy_status_pattern",
        "tmux ekranı okuma", f"{T2}; {W0B}"),
    oos("_USAGE_PLAN_RE _USAGE_FRACTION_RE _USAGE_RESET_RE "
        + " ".join(P_ + n for n in "usage_command parse_usage_text usage_fresh_tui_argv".split()),
        "kota okuma ve ayrıştırma", T7),
    oos(P_ + "live_context", "`/api/status` bağlam alanı", T1),
]

A = "AgyProvider."
DEFS["providers/agy_provider.py"] = [
    ok("CONVERSATIONS_CACHE", "lib.rs::Config.agy_cache lib.rs::Config::from_env",
       "I:fake_proc.rs::broken_agy_files P:scan_sessions"),
    ok("AGY_SIDS_JSON", "lib.rs::Config.agy_sids lib.rs::Config::from_env",
       "I:fake_proc.rs::broken_agy_files P:scan_agy_learned"),
    ok("_load_agy_sids", "providers.rs::AgyState::load providers.rs::read_object",
       "I:fake_proc.rs::broken_agy_files P:scan_agy_learned",
       "sapma 3: DB yerine dosya aynası okunur (DB okuma W0-a)"),
    ok("_remember_agy_sid", "providers.rs::AgyState::resolve providers.rs::AgyState.learned",
       "U:providers.rs::agy_sid_rules I:fake_proc.rs::broken_agy_files P:scan_agy_learned",
       f"yalnız 'yazılacak mı' kararı; KİLİTLİ YAZIM TAŞINMADI ({W0A}; {T1} bağlanmadan şart, sapma 3)"),
    ok("_sid_claimed_by_other", "providers.rs::AgyState::resolve",
       "U:providers.rs::agy_sid_rules I:fake_proc.rs::broken_agy_files"),
    ok("AgyProvider", "providers.rs::Cli", DISC, "yalnız tanıma/ayrıştırma"),
    ok(A + "name", "providers.rs::Cli::as_str", G_INFO),
    ok(A + "matches_proc", "providers.rs::Cli::detect", DISC),
    ok(A + "extract_name", "providers.rs::Cli::extract_name", "I:fake_proc.rs::discovers_each_cli_and_names"),
    ok(A + "extract_info", "providers.rs::Cli::extract_info providers.rs::AgyState::resolve",
       f"{G_INFO} U:providers.rs::agy_sid_rules I:fake_proc.rs::broken_agy_files"),
    oos("PERMISSION_MODES EFFORT_LEVELS _PERMISSION_FLAGS _MODELS_TTL "
        + " ".join(A + n for n in "__init__ build_inner_command env_overrides mcp_setup_command _fetch_models "
                   "model_choices permission_modes effort_levels model_effort_levels".split()),
        "açılış argv/env, model/effort/izin kuralları", SAG),
    oos(" ".join(A + n for n in "resolve_resume_id snapshot_for_live_sid discover_live_sid".split()),
        "devam kimliği ve canlı sid keşfi", T4),
    oos("CONVERSATIONS_DIR _STEP_TYPE_USER _STEP_TYPE_ASSISTANT _STEP_TYPE_CHECKPOINT _read_varint _iter_fields "
        "_get_bytes_field _get_text_field _step_user_text _step_assistant_text _conversation_ids "
        + " ".join(A + n for n in "_transcript_steps _steps_desc last_exchange full_history "
                   "sid_for_stopped_session".split()), "protobuf sohbet deposu okuma", CHAT),
    oos("BUSY_STATUS_PATTERN " + A + "busy_status_pattern " + A + "usage_needs_dismiss",
        "tmux ekranı okuma ve tuş gönderme", f"{T2}; {W0B}"),
    oos(" ".join(A + n for n in "usage_command usage_fresh_argv usage_auth_missing parse_fresh_usage "
                 "parse_usage_text".split()), "kota okuma ve ayrıştırma", T7),
]

S = "ShellProvider."
DEFS["providers/shell_provider.py"] = [
    ok("PROC_TAG", "providers.rs::Cli::detect", f"{G_INFO} U:providers.rs::detect"),
    ok("ShellProvider", "providers.rs::Cli", DISC, "yalnız tanıma/ayrıştırma"),
    ok(S + "name", "providers.rs::Cli::as_str", G_INFO),
    ok(S + "matches_proc", "providers.rs::Cli::detect", DISC),
    ok(S + "extract_name", "providers.rs::Cli::extract_name",
       "I:fake_proc.rs::discovers_each_cli_and_names I:fake_proc.rs::other_users_processes_are_never_read"),
    ok(S + "extract_info", "providers.rs::Cli::extract_info providers.rs::Info", G_INFO),
    oos("_SENTINEL " + " ".join(S + n for n in "has_conversation resolve_resume_id build_inner_command env_overrides "
                                "model_choices permission_modes effort_levels".split()), "açılış kuralları", SAG),
]

U_ = "UcliProvider."
DEFS["providers/ucli_provider.py"] = [
    ok("_EFFORT_LIMITS", "providers.rs::UCLI_EFFORT", f"{G_INFO} U:providers.rs::ucli_effort_presets",
       f"yalnız ters eşleme; açılış yönü {SAG}"),
    ok("_READ_ONLY _ALLOW_EDIT _ALLOW_CREATE", "providers.rs::ucli_info",
       f"{G_INFO} U:providers.rs::ucli_effort_presets"),
    ok("UcliProvider", "providers.rs::Cli", DISC, "yalnız tanıma/ayrıştırma"),
    ok(U_ + "name", "providers.rs::Cli::as_str", G_INFO),
    ok(U_ + "matches_proc", "providers.rs::Cli::detect", f"{G_INFO} U:providers.rs::detect"),
    ok(U_ + "_parse_session", "providers.rs::arg", f"{G_INFO} I:fake_proc.rs::mirrors_terminal_and_ucli_flag_edges"),
    ok(U_ + "extract_name", "providers.rs::Cli::extract_name",
       "I:fake_proc.rs::mirrors_terminal_and_ucli_flag_edges P:scan_sessions"),
    ok(U_ + "extract_info", "providers.rs::ucli_info", f"{G_INFO} U:providers.rs::ucli_effort_presets"),
    oos("_EFFORT_LEVELS _REQUEST_TIMEOUT_SECS _MAX_HISTORY_KIB _PERMISSION_MODES _MODEL_CHOICES DEFAULT_ENDPOINT "
        "_ENDPOINT endpoint _MODELS_TTL _LIVE_MODEL_CACHE _LIVE_MODEL_CACHE_TS _LIVE_CAPS _fetch_live_models "
        "_live_models reasoning_effort_for _API_KEY_FILE _API_KEY_MANAGED_MARKER _sync_api_key_file _web_args "
        "_script_args _stream_args _reasoning_display_args _metrics_file_args _interactive_args _state_dir_args "
        "_timeout_args _history_args _effort_args _set_flag_value _service_key_file _INSTRUCTIONS_MAX_BYTES "
        "_instructions_too_big instructions_check _claude_service_flags _PRICED_MODELS _claudeops_price _argv_model "
        "_has_price _default_session_cap _with_price _effective_session_cap _unpriced_cap_reason session_cap_refusal "
        "_max_cost_args _MCP_NAME_BAD _MCP_TOOL_RE _MCP_ADD_TIMEOUT mcp_server_name mcp_add_argv register_mcp "
        "_apply_cli_opts _agent_setup "
        + " ".join(U_ + n for n in "accepts_cli_opts mcp_needs_cwd validate_cli_opts mcp_launch_args "
                   "build_inner_command env_overrides model_choices default_permission_mode permission_modes "
                   "effort_levels".split()), "açılış argv/env, MCP, model/effort/izin kuralları", SAG),
    oos(" ".join(U_ + n for n in "has_conversation wants_handover_wrapup resolve_resume_id oneshot".split()),
        "devam/devir ve tek atımlık çağrı", T4),
    oos(U_ + "prepare_input " + U_ + "background_work", "tmux girişi ve arka plan işi", f"{T2}; {W0B}"),
    oos("_USAGE_FIELDS _PHASE_INT_FIELDS "
        + " ".join(U_ + n for n in "live_busy live_tools live_context live_usage live_failed_turns live_phase".split()),
        "durum dosyasından `/api/status` alanları", T1),
    oos(" ".join(U_ + n for n in "full_history sid_for_stopped_session last_exchange".split()),
        "sohbet geçmişi okuma", CHAT),
]

DEFS["commands/usage.py"] = [
    oos("register run run_day render_account render_account.age render render_day collect _weight",
        "`cops usage` komutu (toplama çekirdeği `usage.rs`te; tablo/seçim/gün dökümü taşınmadı)", f"{T6}; {T7}"),
]

DEFS["model_usage.py"] = [
    ok("_FAMILIES _family", "usage.rs::family", "G:usage_totals_two_calls P:usage_real"),
    oos("PROJECTS_DIR WINDOW_MINUTES CACHE_SECONDS _BLOCK _lock _state _iter_recent_lines _sub_effort scan _refresh "
        "summary", "son 60 dakika model kullanım çubuğu", T7),
]

DEFS["orphan_watch.py"] = [
    oos("MIN_AGE_S SOCKET_PREFIXES KILLABLE_PREFIXES CLI_NAMES _sock_dir _pid_alive _server_alive scan_sockets "
        "scan_sockets::re1 _pane_pids _is_app_server _ancestor_cmd scan_procs check HOG_PCT HOG_MIN_SPAN_S "
        "scan_cpu_hogs _own _attr", "sahipsiz tmux soketi/süreç ve CPU yakan süreç denetimi (periyodik iş; yıkıcı adım "
        "içerir). uid süzgeci içerikten (cmdline/cwd/ad, ata cmdline'ı) ÖNCE (Python düzeltildi: f51a442f); Rust karşılığı YOK, "
        "en yakın yol `status.rs::OrphanTracker::report` yalnız kendi oturumlarını görür ve içeriği `OwnProc` ile okur "
        "(kanıt `fake_proc.rs::other_users_processes_are_never_read`)", T7),
]

DEFS["paths.py"] = [
    ok("HOME CLAUDE_DIR", "lib.rs::Config.claude_dir lib.rs::Config::from_env", "P:scan_sessions",
       "`HOME` yoksa Rust `None` (Python parola veritabanına düşer)"),
    ok("CLAUDEOPS_DIR", "lib.rs::Config::from_env", "P:scan_agy_learned",
       "yalnız canlı parite `CLAUDEOPS_DIR` ile koşar; test yalıtımı kuralı `_under_test_runner` satırında"),
    ok("STATE_DIR", "needs_ho.rs::NeedsHo.state_dir needs_ho.rs::NeedsHo::new",
       "I:needs_ho_git.rs::git_signals_and_baseline P:needs_ho_repos", "dizini çağıran verir"),
    ok("SESSIONS_DIR", "discovery.rs::sessions_from_json", "I:fake_proc.rs::json_source_merges_with_proc_scan"),
    ok("PROJECTS_DIR", "transcript.rs::jsonl_path_for", "I:fake_proc.rs::transcript_requires_exact_sid"),
    ok("parse_proc_stat", "procfs.rs::parse_stat", "U:procfs.rs::stat_with_parens_in_comm",
       "dört alan döner; `)` yoksa istisna yerine `None`"),
    ok("proc_stat_fields", "procfs.rs::OwnProc::try_stat procfs.rs::OwnProc::stat",
       "I:fake_proc.rs::broken_proc_fields", "yalnız kendi kullanıcımızın süreci"),
    ok("proc_ppid", "procfs.rs::Stat.ppid", "I:fake_proc.rs::own_ppid_from_real_proc"),
    oos("_test_code_loaded _under_test_runner ensure_private_state_dir ROSTER_TSV MODELS_TSV CLAUDE_MODELS_JSON",
        "durum dizini çözümü, test yalıtımı ve durum dosyaları", W0A),
    oos("ucli_key_file", "ucli anahtar dosyası yolu", SAG),
    oos("shared_write_allowed", "ikinci örnekte ortak anahtar/kullanım yazma yasağı (TBD#412)", f"{SAG}; {W0A}"),
    oos("REPO_DIR CONFIG_JSON GUARD_LOCK", "açılış/koruma yolu sabitleri", T4),
]

DEFS["commands/web.py"] = [
    ok("_usage_total", "status.rs::Probe::usage_total",
       "I:fake_proc.rs::probe_usage_total_claude_exact_sid_without_blocking", "sapma 1; durum yükü bağlantısı T1"),
    ok("_process_started_at", "status.rs::Probe::started_at", "I:fake_proc.rs::tmux_terminal_and_orphans",
       "yalnız kendi kullanıcımızın süreci"),
    oos("_UCLI_FLAGS_CACHE", "pid başına önbellek (sapma 9)", T1),
    ok("_ucli_flags", "status.rs::Probe::ucli_flags status.rs::UcliFlags",
       "I:fake_proc.rs::ucli_flags I:fake_proc.rs::ucli_flags_all_set "
       "I:fake_proc.rs::ucli_flags_lost_process_is_none_and_not_cached "
       "I:fake_proc.rs::mirrors_terminal_and_ucli_flag_edges P:scan_sessions", "`tools` ve önbellek T1"),
    oos("_with_ucli_tools", "rozete durum dosyasından araç listesi ekler", T1),
    oos("_find_gnome_terminal_server", "gnome-terminal sunucusu araması; uid denetimi cmdline'dan ÖNCE (Python düzeltildi: "
        "f51a442f); Rust karşılığı yok (crate'te gnome-terminal araması yok; tüm süreç içeriği `OwnProc` kapısından)", T1),
    oos("_diag_status", "Tanılama yükü; `skipped` sözlüğü discovery/needs_ho/session_usage sayaçlarını toplar (Python "
        "düzeltildi: 1af088ef); Rust karşılıkları `ScanDiag`, `Usage.skipped_rows`, `Checked.skipped` (JSON'da)", T1),
]

DEFS["tmux_backend.py"] = [
    ok("TMUX_SOCKET", "status.rs::TMUX_SOCKET", "I:fake_proc.rs::tmux_terminal_and_orphans P:scan_sessions"),
    ok("_ANCESTOR_WALK_LIMIT", "status.rs::ANCESTOR_WALK_LIMIT", "I:fake_proc.rs::tmux_terminal_and_orphans",
       "6 adım sınırının ucu sınanmıyor"),
    ok("is_tmux_backed", "status.rs::Probe::is_tmux_backed",
       "I:fake_proc.rs::tmux_terminal_and_orphans I:fake_proc.rs::other_users_processes_are_never_read "
       "P:scan_sessions", "başka kullanıcının atasında durur, içeriğini okumaz. Python düzeltildi: 6ae5da3"),
]

# ── test eşlemesi: tek tek ───────────────────────────────────────────────────


def t_ok(names, tests, note=""):
    return (names.split(), OK, tests, note)


def t_oos(names, why, track):
    return (names.split(), OOS, "", f"{why}. İz: {track}")


def t_gap(names, why, tests=""):
    return (names.split(), GAP, tests, why)


CASES: dict = {}


def cls(name, methods):
    return " ".join(f"{name}.{m}" for m in methods.split())


k = "FindSessionsSidTests"
CASES["test_discovery_sid.py"] = [
    t_ok(cls(k, "test_a_fresh_session_gets_the_live_sid_from_the_json_entry"),
         "I:fake_proc.rs::json_source_merges_with_proc_scan"),
    t_ok(cls(k, "test_a_resumed_session_keeps_its_sid_and_stays_resumed"),
         "I:fake_proc.rs::json_sid_merge_rules_like_python I:fake_proc.rs::discovers_each_cli_and_names"),
    t_ok(cls(k, "test_the_live_json_sid_wins_over_a_stale_cmdline_sid "
                "test_a_json_entry_without_a_sid_never_blanks_the_cmdline_sid "
                "test_each_session_gets_its_own_sid_by_pid test_a_json_entry_of_another_cli_never_donates_its_sid"),
         "I:fake_proc.rs::json_sid_merge_rules_like_python"),
    t_ok(cls(k, "test_a_tui_renamed_session_is_listed_once_under_its_spawn_name"),
         "I:fake_proc.rs::json_source_merges_with_proc_scan"),
    t_ok(cls(k, "test_without_a_json_entry_the_cmdline_value_is_used_exactly_as_before"),
         "I:fake_proc.rs::is_fresh_without_json_entry_for_every_cli"),
    t_ok(cls(k, "test_a_non_claude_cli_keeps_its_cmdline_sid_and_its_old_is_fresh"),
         "I:fake_proc.rs::is_fresh_without_json_entry_for_every_cli", "sahte sağlayıcı yerine ucli ve codex"),
    t_ok("IsFreshTests.test_flag_unknown_falls_back_to_the_sid "
         "IsFreshTests.test_flag_known_wins_over_the_sid", "U:session.rs::is_fresh_flag_and_sid_combinations"),
]

k = "FoldTests"
CASES["test_discovery_bg_fold.py"] = [
    t_ok(cls(k, "test_bg_folds_into_front_and_front_reads_bg_sid test_fallback_single_front_same_cwd_without_parked_id "
                "test_two_fronts_without_link_is_ambiguous_bg_kept test_parked_id_picks_the_right_front"),
         "U:session.rs::background_folds_into_single_front"),
    t_ok(cls(k, "test_order_independent test_orphan_bg_is_kept test_other_name_not_folded "
                "test_second_bg_stays_visible test_non_bg_sessions_untouched"),
         "U:session.rs::background_fold_edge_cases_like_python"),
    t_oos(cls("KillBgTests", "test_stop_kills_folded_bg_after_front test_stop_without_bg_kills_only_front"),
          "durdurma (kill) yolu", T4),
]

CASES["test_discovery_subshell.py"] = [
    t_ok("FoldSubshellTests.test_descendants_drop_independent_and_other_cli_stay",
         "U:session.rs::subshell_tree_like_python"),
    t_ok("RealSubshellTests.test_background_subshell_is_one_session",
         "I:real_proc.rs::real_background_subshell_is_one_session"),
]

CASES["test_ls_json.py"] = [
    t_ok("LsJson.test_json_is_sorted_valid_and_has_no_table",
         "U:list.rs::json_is_sorted_valid_and_has_no_table P:list_json"),
    t_ok("LsJson.test_table_unchanged_without_flag", "U:list.rs::table_matches_python_layout P:list_table"),
]

k = "FindSessionsMirrorsOutTests"
CASES["test_mirror_marker.py"] = [
    t_ok(cls("NoteMirrorTests", "test_records_the_pid_under_the_spec test_same_spec_accumulates_pids "
             "test_anything_else_leaves_the_dict_alone"), "U:mirrors.rs::notes_accumulate"),
    t_ok(cls(k, "test_viewers_are_collected_in_the_same_pass"),
         "I:fake_proc.rs::discovers_each_cli_and_names I:real_proc.rs::real_viewer_process_is_seen",
         "tek tarama yapısal (`find_sessions` içinde `note_mirror`)"),
    t_ok(cls(k, "test_viewers_are_not_sessions_and_fleet_result_is_unchanged "
                "test_a_real_viewer_process_is_seen_by_the_real_scan"),
         "I:real_proc.rs::real_viewer_process_is_seen"),
    t_oos(cls(k, "test_default_does_not_collect_anything"),
          "Rust'ta isteğe bağlı toplama yok: `Scan.mirrors` her taramada dolar (bilinçli davranış farkı)", T1),
    t_oos(cls("MergeStatusMarkerTests",
              "test_open_and_closed_are_stamped_per_remote_row test_same_name_on_two_hosts_is_told_apart "
              "test_match_is_exact_not_a_prefix test_cached_rows_are_copied_not_mutated "
              "test_stale_value_from_upstream_is_overwritten test_no_marker_at_all_when_the_state_is_unknown "
              "test_empty_set_means_known_and_closed test_local_closed_and_retired_rows_are_not_stamped "
              "test_a_dict_works_as_the_container_like_find_sessions_hands_it_over "
              "test_unpolled_host_adds_no_rows_and_no_crash"), "uzak satırlara `mirror_open` işareti", f"{T1}; {T5}"),
    t_oos(cls("StatusPayloadWiringTests",
              "test_remote_rows_carry_the_marker_from_the_fleet_scan test_exactly_one_scan_carries_the_collector "
              "test_a_closed_window_flips_the_marker_on_the_next_tick"), "durum yayını bağlantısı", T1),
]

k = "SpecFromCmdlineTests"
b = "OpenMirrorWindowBackendTests"
CASES["test_mirror_window.py"] = [
    t_ok(cls(k, "test_host_and_name test_bare_name_is_local test_value_of_a_flag_is_not_mistaken_for_the_target "
                "test_once_is_not_a_window test_other_commands_do_not_match test_watch_without_a_target "
                "test_empty_parts"), "U:mirrors.rs::specs G:provider_detect_and_info"),
    t_ok(cls(k, "test_flags_before_or_after_the_target"), "U:mirrors.rs::specs G:provider_detect_and_info",
         "`--port=9000` biçimi ayrıca yok; aynı tire kuralı sınanıyor"),
    t_ok(cls("RunningMirrorsTests", "test_collects_pids_per_spec"),
         "U:mirrors.rs::notes_accumulate I:fake_proc.rs::mirrors_terminal_and_ucli_flag_edges"),
    t_ok(cls("RunningMirrorsTests", "test_other_users_processes_are_ignored test_unreadable_processes_are_skipped "
             "test_a_process_vanishing_mid_scan_is_skipped"), "I:fake_proc.rs::mirrors_terminal_and_ucli_flag_edges"),
    t_ok(cls("RunningMirrorsTests", "test_default_uid_is_the_current_user"),
         "I:real_proc.rs::real_viewer_process_is_seen"),
    t_ok(cls("FocusWindowTests", "test_uses_exact_title_matching_and_the_given_display"),
         "U:mirrors.rs::focus_reports_exit_status_and_passes_exact_args"),
    t_ok(cls("FocusWindowTests", "test_failures_are_false_not_exceptions"),
         "U:mirrors.rs::focus_reports_exit_status_and_passes_exact_args U:proc_cmd.rs::output_status_and_timeout"),
    t_oos(cls("OpenMirrorWindowSpawnTests",
              "test_gnome_terminal_argv test_the_command_runs_cops_watch_against_this_panels_port "
              "test_a_failing_viewer_keeps_the_window_open_and_a_clean_exit_closes_it test_arguments_are_shell_quoted "
              "test_environment test_popen_failure_is_false"), "görüntüleyici penceresi açma", T2),
    t_oos(cls(b, "test_success_spawns_once_with_the_panels_port test_local_sessions_are_rejected "
                 "test_bad_characters_never_reach_the_command_line test_unknown_host "
                 "test_session_must_be_in_the_hosts_last_known_state "
                 "test_a_session_without_tmux_has_no_terminal_to_mirror test_no_x11_display "
                 "test_an_open_mirror_is_focused_not_duplicated test_force_opens_a_second_one "
                 "test_another_sessions_mirror_does_not_count test_launch_failure test_messages_follow_the_language"),
          "pencere açma uç mantığı", f"{T2}; {T5}"),
    t_oos(cls("MirrorRouteHttpTests", "test_route_is_declared_local_only "
              "test_post_with_a_remote_host_field_is_handled_locally test_force_flag_is_passed_through "
              "test_name_is_required test_token_is_required"), "HTTP ucu", T2),
    t_oos(cls("LayoutRecognisesMirrorWindowsTests", "test_a_mirror_window_is_tiled_once_its_spec_is_known "
              "test_without_the_spec_it_is_skipped_as_before test_title_from_the_viewer_survives_list_windows_cleaning"),
          "pencere döşeme (`cops layout`)", T6),
]

CASES["test_orphan_cli.py"] = [
    t_ok("OrphanTests.test_fallback_name", "U:discovery.rs::fallback_names G:names_paths_and_token_format"),
    t_ok("OrphanTests.test_terminal_lost",
         "I:fake_proc.rs::tmux_terminal_and_orphans I:fake_proc.rs::mirrors_terminal_and_ucli_flag_edges"),
    t_ok(cls("OrphanTests", "test_idle_spin") + " OrphanReportTests.test_spin_after_ten_minutes",
         "I:fake_proc.rs::tmux_terminal_and_orphans"),
]

CASES["test_proc_stat_parse.py"] = [
    t_ok(cls("ProcStatTest", "test_plain test_comm_with_space_and_paren test_starttime_index test_no_paren_raises"),
         "U:procfs.rs::stat_with_parens_in_comm"),
    t_ok("ProcStatTest.test_own_ppid", "I:fake_proc.rs::own_ppid_from_real_proc"),
    t_oos("ProcStatTest.test_no_inline_copies", "Python kaynağında kopya ayrıştırıcı yasağı (Rust'ta karşılığı yok)",
          "yalnız Python"),
]

CASES["test_rfh_marker.py"] = [
    t_ok("RfhMarkerTests.test_prose_mention_is_not_a_marker",
         "U:needs_ho.rs::prose_mention_is_not_a_marker G:rfh_marker"),
    t_ok("RfhMarkerTests.test_heading_and_bare_line_count",
         "U:needs_ho.rs::heading_and_bare_line_count G:rfh_marker"),
    t_ok("RfhMarkerTests.test_code_block_and_quote_do_not_count",
         "U:needs_ho.rs::code_block_and_quote_do_not_count G:rfh_marker"),
]

k = "HandoverDoneUserMessageTest"
CASES["test_triage_fixes_20261107.py"] = [
    t_ok(cls(k, "test_user_message_with_rfh_text_does_not_count test_assistant_rfh_counts "
                "test_non_assistant_row_types_with_rfh_do_not_count test_real_rfh_after_blob_row_counts"),
         "U:needs_ho.rs::only_assistant_rows_carry_the_marker G:transcripts_needs_ho"),
    t_oos(cls("RunDirTest", "test_rejects_traversal test_normal_id_ok"), "orkestrasyon koşu dizini", T7),
    t_oos("HostsDbNonListTest.test_db_mode_non_list_is_corrupt", "host kaydı okuma", f"{W0A}; {T5}"),
]

CASES["test_review_fixes_2026_11_04.py"] = [
    t_ok(cls("CommittedSinceTimeCompare", "test_offsets_compared_as_instants "
             "test_unparseable_baseline_means_unknown_so_do_ho test_no_commit_is_not_new"),
         "U:needs_ho.rs::iso_times_compare_as_instants G:committed_after_iso_rules"),
    t_oos(cls("HandoverBatchFixes", "test_dry_run_does_not_write_baseline_and_shows_skip "
              "test_real_run_writes_baseline_atomically test_sidless_session_in_shared_cwd_is_not_skipped"),
          "toplu devir akışı", T4),
    t_oos(cls("GuardExitCode", "test_spawn_error_gives_nonzero_exit test_all_ok_exit_zero"), "guard komutu",
          f"{T4}; {T6}"),
    t_oos(cls("UploadNoOverwriteRace", "test_file_appearing_after_check_is_not_clobbered "
              "test_no_overwrite_creates_new_file test_dir_is_fsynced_after_write"), "dosya yükleme", T3),
    t_oos(cls("CliStatusOverride", "test_stale_override_is_not_found test_valid_override_is_found"),
          "CLI ikilisi bulma ayarı", T7),
    t_oos("SeedNonDict.test_list_content_is_left_alone", "oturum açılışında ayar tohumlama", T4),
    t_oos("FileLockPathNormalizationTest.test_spellings_of_one_path_share_one_lock_entry", "durum dosyası kilidi",
          W0A),
]

k = "SessionUsageTest"
CASES["test_session_usage.py"] = [
    t_ok(cls(k, "test_main_and_subagents_separate_with_family_breakdown test_split_rows_of_one_reply_counted_once_and_max_kept "
                "test_incremental_append_truncate_and_partial_last_line test_missing_file_returns_none_never_raises"),
         "I:fake_proc.rs::usage_dedups_subagents_and_increments G:usage_totals_two_calls"),
    t_ok(cls(k, "test_synthetic_rows_are_not_turns_nor_a_family"),
         "G:usage_totals_two_calls I:fake_proc.rs::usage_dedups_subagents_and_increments"),
    t_ok(cls(k, "test_bad_lines_skipped"),
         "I:fake_proc.rs::usage_dedups_subagents_and_increments G:usage_totals_two_calls"),
    t_ok(cls(k, "test_cached_returns_none_first_then_value_after_background_refresh"),
         "U:usage.rs::cache_first_none_then_value_and_error_keeps_last_good"),
    t_ok(cls(k, "test_fmt_tokens"), "U:usage.rs::fmt_tokens_python_examples G:names_paths_and_token_format"),
]

CASES["test_procscan_tbd365.py"] = [
    t_ok("SessionFilesTest.test_bad_files_are_skipped_and_counted SessionFilesTest.test_negative_or_zero_pid_never_reaches_kill",
         "I:fake_proc.rs::bad_session_files_are_skipped_and_counted", "Python düzeltildi: 6ae5da3"),
    t_ok("ForeignCmdlineTest.test_find_sessions_reads_only_own_cmdline "
         "ForeignCmdlineTest.test_running_mirrors_reads_only_own_cmdline",
         "I:fake_proc.rs::other_users_processes_are_never_read I:fake_proc.rs::mirrors_terminal_and_ucli_flag_edges",
         "Python düzeltildi: 6ae5da3"),
    t_ok("TmuxAncestorTest.test_foreign_ancestor_stops_walk_without_reading_it",
         "I:fake_proc.rs::other_users_processes_are_never_read I:fake_proc.rs::tmux_terminal_and_orphans", "Python düzeltildi: 6ae5da3"),
    t_ok("TranscriptRowsTest.test_bad_rows_skipped",
         "U:needs_ho.rs::broken_input_is_skipped_and_counted G:transcripts_needs_ho", "Python düzeltildi: 6ae5da3"),
    t_ok("TranscriptRowsTest.test_needs_ho_decides_instead_of_raising", "U:needs_ho.rs::needs_ho_decides_with_bad_rows",
         "Python düzeltildi: 6ae5da3"),
    t_ok("BaselineAtomicTest.test_baseline_written_via_replace", "U:needs_ho.rs::baseline_is_written_atomically", "Python düzeltildi: 6ae5da3"),
    t_ok("SidPathTest.test_sid_with_path_parts_is_not_joined", "I:fake_proc.rs::transcript_requires_exact_sid", "Python düzeltildi: 6ae5da3"),
    t_ok("SidPathTest.test_invalid_or_missing_sid_file_never_guesses", "I:fake_proc.rs::transcript_requires_exact_sid",
         "Python düzeltildi: 43753998"),
    t_ok("SessionFilesTest.test_overflowing_pid_is_skipped_and_counted",
         "I:fake_proc.rs::overflowing_pids_are_skipped_and_counted", "Python düzeltildi: 35a1eb78"),
    t_ok("UsageRowsTest.test_overflowing_token_count_does_not_blank_total",
         "U:usage.rs::overflowing_count_row_does_not_blank_total", "Rust'ta satır serde'de ayrıştırılmaz (sapma 4). Python düzeltildi: 35a1eb78"),
    t_ok("ForeignProcessContentTest.test_orphans_only_own_and_foreign_ancestor_not_read "
         "ForeignProcessContentTest.test_cpu_hogs_only_own", "I:fake_proc.rs::other_users_processes_are_never_read",
         "orphan_watch'ın Rust karşılığı yok (T7); en yakın yol OrphanTracker, kanıt testi. Python düzeltildi: f51a442f"),
    t_oos("ForeignProcessContentTest.test_gnome_terminal_server_cmdline_read_only_for_own",
          "gnome-terminal sunucusu araması, Rust karşılığı yok. Python düzeltildi: f51a442f", T1),
    t_ok("LongLineTest.test_usage_limit_boundary_and_partial_tail LongLineTest.test_usage_memory_is_bounded",
         "U:usage.rs::long_lines_are_skipped_and_counted", "Python düzeltildi: 66b47a37"),
    t_ok("LongLineTest.test_needs_ho_long_line_skipped_and_counted", "U:needs_ho.rs::long_lines_are_skipped_and_counted",
         "Python düzeltildi: 66b47a37"),
    t_ok("DiagSkippedTest.test_diag_carries_all_skip_counters",
         "U:usage.rs::bad_row_is_skipped_and_counted I:fake_proc.rs::bad_session_files_are_skipped_and_counted",
         "Rust sayaçları JSON'da (`Usage.skipped_rows`, `ScanDiag`); Tanılama yükü T1. Python düzeltildi: 1af088ef"),
    t_oos("DiagSkippedTest.test_diag_survives_counter_growing_while_read",
          "Python'a özgü: iplikler arası paylaşılan `Counter` dolaşımı; Rust sayaçları çağrı/tarama başına değer, paylaşılmaz",
          "T1"),
    t_ok("UsageRowsTest.test_bad_rows_skipped_on_first_call UsageRowsTest.test_bad_subagent_row_does_not_blank_total",
         "U:usage.rs::bad_row_is_skipped_and_counted G:usage_totals_two_calls", "Python düzeltildi: 6ae5da3"),
    t_oos("UsageRowsTest.test_day_usage_file_survives_bad_row",
          "gün bazlı döküm (`day_usage`); ortak `_from_row` düzeltmesi `usage.rs::parse` satırında", T7),
    t_ok("UsageRowsTest.test_thread_start_failure_does_not_lock_path", "U:usage.rs::spawn_failure_does_not_lock_the_path",
         "Python düzeltildi: 6ae5da3"),
    t_ok("UsageRowsTest.test_shrinking_file_does_not_evict_another_when_full",
         "U:usage.rs::file_cache_evicts_in_insertion_order", "Python düzeltildi: 6ae5da3"),
]

CASES["test_usage_cli.py"] = [
    t_oos(cls("UsageCliTests", "test_table_sorted_by_spend_and_skips_non_claude test_json_and_name_filter "
              "test_command_is_registered"), "`cops usage` komutu (toplam hesabı `usage.rs` satırlarında)", T6),
    t_ok("StatusUsageTotalTests.test_status_rows_carry_usage_total_without_blocking",
         "I:fake_proc.rs::probe_usage_total_claude_exact_sid_without_blocking",
         "`Probe::usage_total` düzeyinde; durum yükü bağlantısı ve ucli `usage` alanı T1"),
]

CASES["test_proc07_io_ucli_not_fleet.py"] = [
    t_ok(cls("MatchesProcTest", "test_repl_is_fleet test_oneshot_and_reviewer_are_not_fleet"),
         "U:providers.rs::detect G:provider_detect_and_info"),
    t_oos(cls("IoAskLiveNameTest", "test_rejects_live_same_name test_other_name_goes_through"),
          "tek atımlık ucli sorusu ucu", T7),
]

k = "UcliFlagsTest"
CASES["test_web_ucli_flags.py"] = [
    t_ok(cls(k, "test_non_ucli_and_none"), "I:fake_proc.rs::mirrors_terminal_and_ucli_flag_edges",
         "`None` girdisi Rust tipinde yok"),
    t_ok(cls(k, "test_all_flags"), "I:fake_proc.rs::ucli_flags_all_set"),
    t_ok(cls(k, "test_no_flags test_bad_cost_value"), "I:fake_proc.rs::mirrors_terminal_and_ucli_flag_edges"),
    t_ok(cls(k, "test_process_error_returns_none_and_not_cached"),
         "I:fake_proc.rs::ucli_flags_lost_process_is_none_and_not_cached", "Rust'ta pid önbelleği yok (sapma 9)"),
    t_oos(cls(k, "test_tools_from_status_file_are_read_each_time test_cached_per_pid"),
          "durum dosyasından araç listesi ve pid önbelleği (sapma 9)", T1),
]

CASES["test_close_base_name.py"] = [
    t_ok("BaseName.test_date_and_conflict_suffixes_reduce",
         "U:session.rs::base_matches_python_regex G:names_paths_and_token_format", "`close` komutunun kendisi T4"),
    t_oos("BaseName.test_single_source", "Python modülleri arası aynı regex nesnesi denetimi", T4),
    t_oos("TsvFinder.test_find_and_edit", "roster/models dosyası düzenleme", f"{W0A}; {T4}"),
]

CASES["test_agy_sids_store.py"] = [
    t_ok("AgySidsStoreTest.test_unchanged_value_does_not_rewrite", "U:providers.rs::agy_sid_rules",
         f"yalnız 'yeni kayıt yok' kararı; yazım {W0A}"),
    t_oos(cls("AgySidsStoreTest", "test_db_ready test_remember_writes_db_and_mirror "
              "test_concurrent_remembers_lose_nothing"), "kilitli DB+ayna yazımı", f"{W0A}; {T1}"),
]

u = "BuildInnerCommandTests"
for _f in ("test_ucli_effort.py", "test_ucli_request_timeout.py"):
    CASES[_f] = [
        t_ok(f"{u}.test_every_effort_preset_still_round_trips_through_the_running_command",
             "U:providers.rs::ucli_effort_presets G:provider_detect_and_info",
             f"yalnız ayrıştırma yönü; argv üretimi {SAG}"),
        t_ok(f"{u}.test_the_command_is_still_recognised_as_a_ucli_process",
             "U:providers.rs::detect I:fake_proc.rs::mirrors_terminal_and_ucli_flag_edges",
             f"yalnız tanıma/ad; argv üretimi {SAG}"),
    ]
CASES["test_ucli_web.py"] = [
    t_ok(f"{u}.test_running_command_parsing_is_unaffected_by_the_new_flags",
         "G:provider_detect_and_info U:providers.rs::ucli_effort_presets "
         "I:fake_proc.rs::mirrors_terminal_and_ucli_flag_edges", f"yalnız ayrıştırma yönü; argv üretimi {SAG}"),
    t_ok(f"{u}.test_every_effort_preset_round_trips_through_the_running_command",
         "U:providers.rs::ucli_effort_presets G:provider_detect_and_info",
         f"yalnız ayrıştırma yönü; argv üretimi {SAG}"),
    t_ok(f"{u}.test_effort_stays_unknown_when_a_limit_was_changed_by_hand_or_is_missing",
         "U:providers.rs::ucli_effort_unknown_when_any_limit_changed_or_missing"),
    t_ok("AutoContextTests.test_deriving_binary_gets_no_context_flag_and_effort_round_trips",
         "U:providers.rs::ucli_every_preset_without_context_flag", f"yalnız ayrıştırma yönü; argv üretimi {SAG}"),
    t_ok("AutoContextTests.test_legacy_session_with_other_context_value_is_unknown",
         "U:providers.rs::ucli_effort_presets"),
]
CASES["test_ucli_resolve_binary.py"] = [
    t_ok("OwnCopyLocationTests.test_a_session_started_from_the_own_copy_is_still_recognised_as_ucli",
         "U:providers.rs::detect", "ikilinin adının `ucli` olması kuralı; yol seçimi " + SAG),
]
CASES["test_ucli_script.py"] = [
    t_ok("BuildCommandTests.test_permission_modes_list_and_round_trip_from_the_running_command",
         "G:provider_detect_and_info U:providers.rs::ucli_effort_presets",
         f"yalnız ayrıştırma yönü; mod listesi ve argv üretimi {SAG}"),
]

# ── test eşlemesi: crate davranışını sınamayan dosyalar ya da dosyanın kalanı ─
# dosya (test_ ve .py olmadan) -> (adet, ad özeti, gerekçe, iz). Yukarıda tek tek yazılan adlar sayıya girmez.
_BUILD = "açılış argv/env/model kuralları"
_HIST = "sohbet geçmişi"
_STEW = "değnekçi mantığı (crate işlevleri yalnız sahte/fikstür)"
_PATHS = "durum dosyası/DB deposu ve durum dizini"
FILES = {
    "agy_binary_resolution": ("agy ikili yolu ve alıntılama", SAG),
    "agy_compaction_view": (_HIST, CHAT),
    "agy_last_exchange": (_HIST, CHAT),
    "agy_models_swr": ("agy model listesi önbelleği", SAG),
    "bg_work": ("arka plan işi tespiti (ekran + transkript)", f"{T2}; {T1}"),
    "brain_permission_ucli": ("değnekçi beyninin ucli izinleri", f"{T10}; {SAG}"),
    "cache_info": ("`cache` satır alanı", T1),
    "chat_backup_instance_dirs": ("ikinci örnek günlük ve durum dizinleri sohbet yedeğinde (TBD#412)", T7),
    "chat_compaction_view": (_HIST, CHAT),
    "check_cmd": ("`cops check` komutu", T6),
    "claude_models_store": ("model listesi belgesi", f"{W0A}; {SAG}"),
    "context_mask_unknown": ("`/context` maske denetimi (TBD#367)", f"{T2}; {W0B}"),
    "copilot_trust": ("klasöre güven kaydı", T4),
    "cpu_hogs": ("CPU yakan süreç uyarısı", T7),
    "diag_log_isolation": (_PATHS, W0A),
    "directive_delivery": ("direktif teslimi", T10),
    "effort_by_model": ("model bazlı effort kuralları", SAG),
    "extensions_mcp": ("eklenti MCP kaydı", f"{SAG}; {T9}"),
    "files_resolve_exact_first": ("dosya uçlarında oturum adı çözümü", T3),
    "guard_lock_safety": ("guard kilidi", T4),
    "handover_session_wait": ("diyalogda bekleyen oturuma devir yazılmaz (süreç kaydı ve transkript)", f"{T4}; {T10}"),
    "handover_cache_policy": ("devirde model/effort düşürme ve önbellek yaşı", f"{T4}; {T1}"),
    "input_box_typed": ("giriş kutusu ekran okuma", T2),
    "kill_access_denied": ("kill yolu", T4),
    "live_model_effort": ("transkriptten canlı model/effort", T1),
    "model_usage": ("son 60 dakika model kullanım taraması", T7),
    "needs_ho_transcript": ("web/toplu devirde transkript seçimi (en yeni dosyaya düşüş Rust'ta yok, sapma 1; sid var "
                            "dosya yok artık Python'da da None, Python düzeltildi: 43753998)",
                            f"{T1}; {T4}"),
    "orch_store_db": (_PATHS, f"{W0A}; {T7}"),
    "orphan_watch": ("sahipsiz kaynak denetimi", T7),
    "paths_isolation": (_PATHS, W0A),
    "proc08_model_switch_no_blind_enter": ("canlı model değiştirme tuşları", T4),
    "provider_live_context": ("`live_context` satır alanı", T1),
    "provider_wants_split": ("devir/kurtarma bayrakları", T4),
    "review_self_verify": ("reviewer doğrulaması", T8),
    "routing_guidance": ("model yönergesi ve varsayılanlar", SAG),
    "shared_state_readonly": ("ikinci örnekte ortak dosya yazma yasağı (TBD#412)", f"{SAG}; {W0A}"),
    "snapshot_db": (_PATHS, W0A),
    "split_names": ("CLI ad listesi ayrıştırma", T6),
    "state_backend_last_good": (_PATHS, W0A),
    "state_instances_cache_copy": (_PATHS, W0A),
    "state_instances_corrupt_mirror": (_PATHS, W0A),
    "state_instances_db_version_cache": (_PATHS, W0A),
    "statedocs": (_PATHS, W0A),
    "statedocs_hosts_diag": (_PATHS, W0A),
    "statedocs_writers": (_PATHS, W0A),
    "steward_api_recovery": (_STEW, T10),
    "steward_audit_p9": (_STEW, T10),
    "steward_brain": (_STEW, T10),
    "steward_core_a": (_STEW, T10),
    "steward_core_b": (_STEW, T10),
    "steward_ctx": (_STEW, T10),
    "steward_generic": (_STEW, T10),
    "steward_ho_on_open": (_STEW, f"{T10}; {T4}"),
    "steward_http": (_STEW, T10),
    "steward_job_gate_and_qcap": (_STEW, T10),
    "steward_open_dialog": (_STEW, f"{T10}; {T1}"),
    "steward_owned": (_STEW, T10),
    "steward_remote_facts": (_STEW + " ve uzak olgu ucu", f"{T10}; {T5}"),
    "steward_ucli_idle": (_STEW, T10),
    "steward_ucli_send": ("ucli'ye metin gönderimi", f"{T2}; {T10}"),
    "steward_ui_api": ("değnekçi panel uçları", T10),
    "stop_with_handover": ("devir + kapatma", T4),
    "stopped_session_chat": ("durmuş oturumun sohbeti", CHAT),
    "store_tsv": (_PATHS, W0A),
    "stuck_kills_parent": ("takılan oturumu kurtarma", T4),
    "tmux_list_utf8": ("tmux liste sorgularında UTF-8 (TBD#366 P5)", W0B),
    "ucli_agents": ("ucli alt ajan bayrak/env", SAG),
    "ucli_ask_dir": ("ucli `--ask-dir`", SAG),
    "ucli_unpriced_model_cap": ("fiyatsız modelde USD tavanı", SAG),
    "ucli_brain_mcp": ("ucli MCP kaydı ve beyin argv'si", f"{SAG}; {T10}"),
    "ucli_broad_glob_and_instr_check": (_BUILD, SAG),
    "ucli_capability_flags": (_BUILD, SAG),
    "ucli_checkpoint_flag": (_BUILD, SAG),
    "ucli_checks_isolation": ("kontrol kaydı dizini yazma yasağı", f"{T3}; {T7}"),
    "ucli_checks_opts": (_BUILD, SAG),
    "ucli_cost_cap_refusal": ("günlük tavan reddi", f"{SAG}; {T7}"),
    "ucli_default_permission_mode": (_BUILD, SAG),
    "ucli_effort": (_BUILD, SAG),
    "ucli_endpoint": ("ucli uç noktası ayarı", SAG),
    "ucli_evren_no_default_cap": (_BUILD, SAG),
    "ucli_failed_turns": ("başarısız tur satır alanı", T1),
    "ucli_fresh_handover": ("ucli devri", T4),
    "ucli_git_flags": (_BUILD, SAG),
    "ucli_instructions_flags": (_BUILD, SAG),
    "ucli_interactive_flag": (_BUILD, SAG),
    "ucli_key_path": ("ucli anahtar dosyası yolu", SAG),
    "ucli_last_exchange_pairing": (_HIST, CHAT),
    "ucli_limit_flags": (_BUILD, SAG),
    "ucli_live_context": ("`live_context` satır alanı", T1),
    "ucli_max_session_usd": (_BUILD, SAG),
    "ucli_metrics_file_arg": (_BUILD, SAG),
    "ucli_multiline_flatten": ("ucli giriş metni düzleştirme", T2),
    "ucli_phase": ("`phase` satır alanı", T1),
    "ucli_quota_warn": ("token rozeti eşikleri", T1),
    "ucli_request_timeout": (_BUILD, SAG),
    "ucli_resolve_binary": ("ucli ikilisi seçimi", SAG),
    "ucli_script": (_BUILD, SAG),
    "ucli_search_token_env": (_BUILD, SAG),
    "ucli_show_reasoning": (_BUILD, SAG),
    "ucli_start_opts": ("başlatma seçenekleri", f"{SAG}; {T4}"),
    "ucli_state_dir": ("ucli durum dizini bayrağı ve okuyucuları", f"{SAG}; {T1}"),
    "ucli_stream": (_BUILD, SAG),
    "ucli_unpriced_model_cap": ("fiyatsız modelde USD tavanı: `--price` ya da spawn reddi", SAG),
    "ucli_usage": ("`usage` satır alanı", T1),
    "ucli_web": ("ucli web bayrakları ve ayarları", SAG),
    "usage_category": ("`cops usage` gün/kategori dökümü", f"{T6}; {T7}"),
    "usage_fresh": ("oturumsuz kota okuma", T7),
    "usage_fresh_tui": ("copilot TUI kota okuma", T7),
    "usage_state": ("kota durum kaydı", T7),
    "web_review_runner": ("reviewer koşucusu", T8),
}

# dosya -> (adet, ad özeti). Dosya değişince betik yeni değeri basar; gözden geçirmeden GÜNCELLEME.
PINS: dict = {}
PIN_FILE_MARK = "<!-- pin "


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
                    # sabitin doğrudan değeri olan `re.compile(...)` ayrı satır değildir
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
        if seen[q] == 1:               # aynı ada ikinci atama aynı tanımdır
            uniq.append((q, kind, line))
        elif kind != "sabit":
            uniq.append((f"{q}#{seen[q]}", kind, line))
    return uniq


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
    """Kapsam modüllerini içe aktaran (ya da dizgiyle yamalayan) veya üstlenilen web/tmux adlarını anan test dosyaları."""
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
    if "." in file[file.find(".rs") + 3:] or "." in sym:
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
    if kind == "P":
        run = (HERE / "run.py").read_text(encoding="utf-8")
        keys = set(re.findall(r'REPORT\["(\w+)"\]\s*=', run))
        m = re.search(r"for k in \(([^)]*)\):\n\s+norm", run)
        if m:
            keys |= {f"scan_{k}" for k in re.findall(r'"(\w+)"', m.group(1))}
        return body in keys
    if kind == "G":
        rel, name = "tests/golden.rs", body
    else:
        file, _, name = body.partition("::")
        rel = f"{'src' if kind == 'U' else 'tests'}/{file}"
    text = _read(rel)
    return text is not None and re.search(
        rf"#\[test\]\s*\n(\s*(#\[[^\n]*\]|//[^\n]*)\n)*\s*fn {re.escape(name)}\s*\(", text) is not None


def show_test(ref: str) -> str:
    kind, _, body = ref.partition(":")
    if kind == "G":
        return f"golden.rs::{body}"
    if kind == "P":
        return f"run.py:{body}"
    return body if kind == "U" else f"tests/{body}"


def parse_shown_test(shown: str):
    if shown.startswith("golden.rs::"):
        return "G", shown[len("golden.rs::"):]
    if shown.startswith("run.py:"):
        return "P", shown[len("run.py:"):]
    if shown.startswith("tests/"):
        return "I", shown[len("tests/"):]
    return "U", shown


# ── üretim ───────────────────────────────────────────────────────────────────
def cell(items) -> str:
    return "<br>".join(f"`{x}`" for x in items) if items else "yok"


def build():
    errors: list = []
    def_rows: dict = {}
    for mod in FULL + PARTIAL + list(SUBSET):
        defs = definitions(PKG / mod)
        if mod in SUBSET:
            missing = set(SUBSET[mod]) - {d[0] for d in defs}
            errors += [f"{mod}: SUBSET adı ast'te yok: {n}" for n in sorted(missing)]
            defs = [d for d in defs if d[0] in SUBSET[mod]]
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
    out = [
        "# rs/proc eşleme tablosu (Python -> cops-procscan)",
        "",
        "ÜRETİLMİŞ DOSYA, elle düzenleme. Kaynak: `rust/crates/cops-procscan/parity/mapping.py`.",
        "Denetim: `python3 -I rust/crates/cops-procscan/parity/mapping.py --check` (EKSİK varsa da düşsün: `--strict`).",
        "",
        "Durumlar: **karşılandı** = Rust karşılığı ve onu sınayan test/parite adımı var (not sütunu sınırı söyler); "
        "**kapsam dışı** = bu crate'in işi değil, gerekçe ve iz yazılı; **EKSİK** = kapsamda olduğu hâlde davranış ya "
        "da test karşılığı yok.",
        "",
        "Rust yolları `rust/crates/cops-procscan/src/` altındadır; `tests/...` ve `golden.rs` crate'in `tests/` dizini, "
        "`run.py:<ad>` canlı parite koşucusunun rapor bölümü. Denetim adların kaynakta VARLIĞINI sınar, testin o "
        "davranışı gerçekten kapsadığı elle değerlendirilmiştir. Bu betik testleri koşturmaz. \"Sapma N\": "
        "`docs/rs-proc.md`. Modül kapsamı: TAM ve KISMİ modüllerde her `ast` tanımı (işlev, sınıf, metot, modül/sınıf "
        "sabiti, `re.*` çağrısı) bir satırdır; `commands/web.py` ve `tmux_backend.py`de yalnız crate'in üstlendikleri. "
        "Test kapsamı: kapsam modüllerini içe aktaran/yamalayan ya da üstlenilen web/tmux adlarını anan her "
        "`py/tests` dosyasının her `test*` metodu.",
        "",
        "## Özet",
        "",
        "| Küme | Toplam | karşılandı | kapsam dışı | EKSİK |",
        "|---|---|---|---|---|",
        f"| tanım | {len(all_defs)} | {dc[OK]} | {dc[OOS]} | {dc[GAP]} |",
        f"| test durumu ({len(test_rows)} dosya) | {len(all_tests)} | {tc[OK]} | {tc[OOS]} | {tc[GAP]} |",
        "",
        "| Modül | Kapsam | Toplam | karşılandı | kapsam dışı | EKSİK |",
        "|---|---|---|---|---|---|",
    ]
    for mod, rows in def_rows.items():
        c = count(rows, 3)
        scope = "TAM" if mod in FULL else "KISMİ" if mod in PARTIAL else "seçili"
        out.append(f"| `{mod}` | {scope} | {len(rows)} | {c[OK]} | {c[OOS]} | {c[GAP]} |")
    out += ["", "## EKSİK satırlar", ""]
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
    for mod in FULL + PARTIAL + list(SUBSET):
        names = [d[0] for d in definitions(PKG / mod)]
        if mod in SUBSET:
            names = [n for n in SUBSET[mod] if n in names]
        expected |= {f"{mod}::{n}" for n in names}
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
                errors.append(f"satır {number}: EKSİK ama açıklama yok: {key}")
        errors += [f"satır {number}: Rust adı kaynakta yok: {r}"
                   for r in re.findall(r"`([^`]+)`", rust) if not rust_symbol_exists(r)]
        errors += [f"satır {number}: Rust testi yok: {t}"
                   for t in re.findall(r"`([^`]+)`", tests) if not rust_test_exists(*parse_shown_test(t))]
    errors += [f"ast'te var, tabloda yok: {k}" for k in sorted(expected - set(seen))]
    errors += [f"tabloda var, ast'te yok: {k}" for k in sorted(set(seen) - expected)]
    return errors, len(seen), gaps


def load_pins():
    """Dosya özetleri `PIN_DATA`dan."""
    for line in PIN_DATA.split():
        key, n, h = line.split(":")
        PINS[key] = (int(n), h)


PIN_DATA = """
agy_binary_resolution:2:aa240fa19e
agy_compaction_view:1:704b29a853
agy_last_exchange:4:04faca6617
agy_models_swr:1:9166783f75
bg_work:25:8b21f13e5c
brain_permission_ucli:2:d5d3096328
cache_info:12:9f2b8b4e3c
chat_backup_instance_dirs:6:da9a8c9292
chat_compaction_view:3:ada23aaf33
check_cmd:5:c6cf1fda88
claude_models_store:4:967306188a
context_mask_unknown:3:9d143dbe0c
copilot_trust:4:005b70de22
cpu_hogs:3:887f0c1e4a
diag_log_isolation:2:5ecbb7a6c7
directive_delivery:19:57e6111f92
effort_by_model:36:73ae9d3c95
extensions_mcp:6:26026f92d2
files_resolve_exact_first:5:c3607abfa1
guard_lock_safety:4:60456de9ae
handover_cache_policy:50:05c65be290
handover_session_wait:13:5a3e9ebf0d
input_box_typed:13:ae087dd291
kill_access_denied:1:916993d907
live_model_effort:17:c5a05da63a
model_usage:3:46df4bab8c
needs_ho_transcript:4:270118e250
orch_store_db:5:647ecdf3af
orphan_watch:12:e645fcc095
paths_isolation:5:5103a70284
proc08_model_switch_no_blind_enter:3:7cba6c87a9
provider_live_context:7:8fdef1d7cc
provider_wants_split:3:2d8ab8759a
review_self_verify:18:4b125a8002
routing_guidance:13:964131411b
snapshot_db:5:b46cde3ad1
split_names:3:3580026783
state_backend_last_good:3:5531228f00
state_instances_cache_copy:2:22e22aae4c
state_instances_corrupt_mirror:6:27e0a53c31
state_instances_db_version_cache:5:aeb31a0dc5
statedocs:15:dbd456badd
statedocs_hosts_diag:4:a184027db4
statedocs_writers:7:817e74b52a
steward_api_recovery:17:f79402b74c
steward_audit_p9:24:36a9eb8914
steward_brain:34:b4c732deb9
steward_core_a:122:f4f49eaa0c
steward_core_b:77:5bbaded29d
steward_ctx:21:12df78f872
steward_generic:25:f4969150e9
steward_ho_on_open:9:d3f0301c62
steward_http:55:d144bd3c53
steward_open_dialog:16:cb4f15474e
steward_job_gate_and_qcap:17:3a0173c206
steward_owned:17:c39a25372d
steward_remote_facts:19:8999b83aa6
steward_ucli_idle:49:3d78a38764
steward_ucli_send:16:193aaaa4bf
steward_ui_api:19:922b3bb2a8
stop_with_handover:34:841cd91175
stopped_session_chat:29:b4c521a883
store_tsv:6:310f8c657f
stuck_kills_parent:4:f6dcaf3ebf
tmux_list_utf8:3:1f73edfe38
ucli_agents:14:5ef9105ef1
ucli_ask_dir:6:78468c20fd
ucli_brain_mcp:26:f5509e6d5a
ucli_broad_glob_and_instr_check:11:ea6a9ab95d
ucli_capability_flags:10:7f0e89e70c
ucli_checkpoint_flag:6:5d9d0f9632
ucli_checks_isolation:3:82e57898d3
ucli_checks_opts:13:35384bf277
ucli_cost_cap_refusal:3:a396643893
ucli_default_permission_mode:3:ae4885e482
ucli_effort:27:b0ffbae640
ucli_endpoint:4:f9abf5df56
ucli_evren_no_default_cap:2:d4342e7d8b
ucli_failed_turns:7:ce38ec06b6
ucli_fresh_handover:6:431565fe78
ucli_git_flags:8:7cac81f63b
ucli_instructions_flags:6:a070b15a2a
ucli_interactive_flag:2:ad40a48be5
ucli_key_path:2:7de357e5a9
ucli_last_exchange_pairing:3:32c4fc6ff3
ucli_limit_flags:11:412a670c9a
ucli_live_context:4:cf3fb8ae39
ucli_max_session_usd:6:72691a7043
ucli_metrics_file_arg:3:67ebeb61ff
ucli_multiline_flatten:7:1d88beea22
ucli_phase:30:6588d1ea97
ucli_quota_warn:21:5d3f74a1d5
ucli_request_timeout:12:8db5693b1e
ucli_resolve_binary:9:02512466b3
ucli_script:12:8e5e524edb
ucli_search_token_env:7:fe35ffaa52
ucli_show_reasoning:3:88a88fc6d4
shared_state_readonly:7:a71ec45fbf
ucli_start_opts:32:4f29133f96
ucli_state_dir:9:83e53ca259
ucli_stream:12:0b0c264c8d
ucli_unpriced_model_cap:13:5b791b5481
ucli_usage:13:adc8be28ee
ucli_web:53:808f4112d7
usage_category:3:b1ec7bddf6
usage_fresh:16:fce08fa8ed
usage_fresh_tui:11:2314d470a9
usage_state:7:3bd573887b
web_review_runner:55:f8e1922a1d
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
        print(f"satır {n}, EKSİK {len(gaps)}, hata {len(errors)}")
        return 1 if errors or ("--strict" in argv and gaps) else 0
    if errors:
        print("\n".join(errors))
        print(f"hata {len(errors)}; tablo yazılmadı")
        return 1
    OUT.write_text(text, encoding="utf-8")
    gaps = sum(r[3] == GAP for rows in def_rows.values() for r in rows)
    tgaps = sum(r[2] == GAP for rows in test_rows.values() for r in rows)
    print(f"yazıldı: {OUT.relative_to(REPO)}; tanım {sum(map(len, def_rows.values()))} (EKSİK {gaps}), "
          f"test {sum(map(len, test_rows.values()))} (EKSİK {tgaps})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
