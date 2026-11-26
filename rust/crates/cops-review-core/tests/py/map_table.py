"""`docs/rs-rev.md` "Eşleme tablosu" bölümünü üretir (sahip: işlevce eşlik). `claudeops`u import ETMEZ, yalnız `ast`.

    cd rust && COPS_REV_PARITY_REPORT=<dosya> cargo test -p cops-review-core --test parity
    python3 rust/crates/cops-review-core/tests/py/map_table.py <dosya> [--check]

Elle yazılan eşlemeler aşağıdaki sözlüklerdedir. rc != 0: eşlemesi olmayan ad ya da test sınıfı, kaynakta bulunmayan Rust
adı, parite sunucusunun çağırmadığı eşleme, değeri farklı sabit, hiçbir kanıtı olmayan satır ya da `--check`te bayat belge.
"EKSİK" durumlu satır da rc != 0 verir. `cargo test` sonucu bu betiğin işi değildir (birim testlerinin yalnız ADI denetlenir).
"""
import ast
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CRATE = os.path.abspath(os.path.join(HERE, "..", ".."))
REPO = os.path.abspath(os.path.join(CRATE, "..", "..", ".."))
REVIEW = os.path.join(REPO, "py", "claudeops", "review.py")
DOC = os.path.join(REPO, "docs", "rs-rev.md")
BEGIN, END = "<!-- eşleme tablosu: map_table.py üretir, elle düzenlenmez -->", "<!-- eşleme tablosu sonu -->"

# ── (A) Python adı -> Rust adları. Biçim: `dosya.rs::ad`, `Tip::üye`, `Tip.alan`, `işlev::STATIC` ─────────────────────

def _m(file, *names):
    return [f"{file}.rs::{n}" for n in names]


def _same(file, names):
    """Python adı = Rust adı (baştaki `_` atılır)."""
    return {n: _m(file, n.lstrip("_")) for n in names.split()}


MAP = {
    **_same("targets", """WINDOW_SECONDS HISTORY_VERSION HISTORY_RUNS_MAX MAX_ATTEMPTS MODE_MAX_ATTEMPTS CAPACITY_ERROR_PREFIX
        CAPACITY_RETRY_MIN CAPACITY_RETRY_MAX CAPACITY_MAX_TRIES _CAPACITY_RE _RETRY_AFTER_RE is_capacity_error
        capacity_retry_seconds UNCOUNTED_ERRORS counts_as_attempt max_attempts MODES UCLI_MODES ANTHROPIC_ENDPOINT
        ANTHROPIC_PRICES parse_slots PAIR_STATUSES SEVERITIES FINDING_STATES FORBIDDEN_PATHS ReviewTarget slug_model
        split_spec _split_models excluded_keys toggle_excluded SUBSCRIPTION_FABLE_EFFORTS claude_specs
        claude_is_subscription targets_from_config review_title"""),
    "claude_catalog": _m("targets", "claude_catalog_from"),
    **{f"ReviewTarget.{n}": _m("targets", f"ReviewTarget.{n}") for n in "mode model slug effort lens".split()},
    **{f"ReviewTarget.{n}": _m("targets", f"ReviewTarget::{n}") for n in "pslug key spec".split()},
    "_num": _m("py", "num"),
    **_same("planner", """pair_key _pairs window_seconds _fresh project_complete pool_enabled agy_pool model_family
        _blocked_targets next_review BACKLOG_FILES open_review_lines backlogged_projects pool_focus pool_sync"""),
    "_OPEN_REVIEW_LINE_RE": _m("planner", "open_review_lines::RE"),
    "LENSES": _m("prompts", "BUILTIN_LENS", "LensRegistry::lenses"),
    "_LENS_NAME_RE": _m("prompts", "register_lens::NAME"),
    "_LENS_DEFECTS_RE": _m("prompts", "build_review_prompt::EN", "build_review_prompt::TR"),
    "_LENS_TEXT": _m("prompts", "LENS_TEXT_DRY_EN", "LENS_TEXT_DRY_TR", "LensRegistry"),
    "_LENS_FORMAT": _m("prompts", "LENS_FORMAT_EN", "LENS_FORMAT_TR"),
    "_LENS_FORMAT_EXTRA": _m("prompts", "LensRegistry"),
    "register_lens": _m("prompts", "LensRegistry::register_lens"),
    "lenses": _m("prompts", "LensRegistry::lenses"),
    "build_review_prompt": _m("prompts", "LensRegistry::build_review_prompt"),
    "_build_general_prompt": _m("prompts", "general_prompt"),
    "_FINDING_RE": _m("parse", "parse_findings::HEAD"),
    **_same("parse", "_fence_step parse_findings VERDICT_MARK VERDICTS VERDICT_REASON_MAX scan_verdicts"),
    "_VERDICT_RE": _m("parse", "scan_verdicts::LINE"),
    "_PLACEHOLDER_RE": _m("parse", "scan_verdicts::PLACEHOLDER"),
    "_DSN_RE": _m("redact", "DSN_PREFIX", "dsn_matches"),
    "_SECRET_RES": _m("redact", "SECRETS"),
    **_same("redact", "LEARNED_MIN LEARNED_PLAIN_MIN dsn_passwords redact_secrets"),
    **_same("agy", "AGY_ALLOW_DEFAULT agy_allow_list agy_settings _norm_label agy_label_ok"),
    "_LABEL_RE": _m("agy", "agy_label_ok::LABEL"),
    **_same("paths", "effort_for review_path draft_path partial_path error_path finding_path finding_paths draft_prompt_suffix"),
    "FINDING_FILE_RE": _m("paths", "FINDING_FILE"),
    **_same("limits", """_LIMIT_RE is_daily_limit next_utc_midnight next_utc_month_start block_until_for_limit BANNER_MAX_CHARS
        limit_scan_texts is_short_banner _QUOTA_RE _USAGE_LIMIT_RE _TRY_AT_RE _RESET_RE QUOTA_FALLBACK_SECONDS
        QUOTA_MAX_SECONDS is_quota_exhausted is_usage_limit reset_at reset_seconds quota_block_until COPILOT_BLOCK_REASON
        COPILOT_FALLBACK_SECONDS parse_copilot_entries reconcile_copilot_blocks parse_agy_entries parse_agy_usage
        agy_pool_blocked_until AGY_BLOCK_GRACE reconcile_agy_blocks _agy_block_cleared blocked_modes _MODEL_TEXT_KEYS"""),
    "_UNIT_SECONDS": _m("limits", "unit_seconds"),
    **_same("store", """set_block load_pool save_pool R10_SUB_SINCE R10_MARK migrate_r10_sub load_history save_history
        _run_seconds update_pair load_findings save_findings _fold finding_key _canon_rank add_findings mark_verify_sent
        decide_finding"""),
    "set_block": _m("store", "ReviewStore::set_block"),
    **{n: _m("store", f"ReviewStore::{n}") for n in """load_pool save_pool load_history save_history update_pair
        load_findings save_findings add_findings mark_verify_sent decide_finding""".split()},
    **_same("flow", """VERIFIABLE_STATES APPROVABLE_STATES REJECTABLE_STATES VERIFY_MAX_FINDINGS text_hash reviewer_slug_of
        apply_verdicts VERIFY_REQUEUE_SECONDS VERIFY_MAX_TRIES requeue_stale_verify build_verify_message
        build_self_verify_prompt"""),
    **_same("report", """usage_summary HEALTH_DAYS HEALTH_MIN_RUNS HEALTH_MAX_RATE model_health health_digest duration_summary
        report_incomplete report_bodyless anthropic_price usage_cost_usd anthropic_spent_usd"""),
    "_INCOMPLETE_RE": _m("report", "report_incomplete::INCOMPLETE"),
    "_HAS_FINDING_RE": _m("report", "HAS_FINDING"),
    **_same("export", """EXPORT_HEADING is_decision where_text where_relpath has_quoted_names stale_reason_text stale_reason
        changed_after_review _worktree_main row_in_repo export_root export_lines appended_export _where_file"""),
    "_DECISION_RE": _m("export", "is_decision::DECISION"),
    "_BACKTICK_RE": _m("export", "BACKTICK"),
    "_WHERE_FILE_RE": _m("export", "where_path::FILE"),
    "_WHERE_MD_LINK_RE": _m("export", "where_text::LINK"),
}

# Tanım olmayan modül düzeyi ifadeler: kaynak metni -> gerekçe.
STATEMENTS = {"_ext.load()": "kapsam dışı: Python eklenti yükleyicisi (`extensions.py`); Rust'ta `LensRegistry` çağırandan gelir, "
                             "eklenti kaydı T9 (enterprise) / T8 (koşucu `web_review.py`)"}

NOTES = {
    "claude_catalog": "çekirdek payı; `claude_models` belgesini okumak çağıranda (T8)",
    "_LENS_FORMAT_EXTRA": "modül genel sözlüğü yerine kayıt nesnesinin alanı",
    "finding_key": "`casefold` sapması: \"Bilinen küçük sapmalar\"",
}

# Özel yardımcıların / değerlerin Rust birim testleri (`tests/helpers.rs`).
UNIT = {"_num": ["num_tolerates_corrupt_values"], "_run_seconds": ["run_seconds_cases"],
        "_fence_step": ["fence_closes_only_with_own_kind"], "_canon_rank": ["canonical_record_by_tier_then_age"],
        "ReviewTarget.lens": ["planner_targets_have_no_lens"]}

# Parite sunucusunda adı farklı çağrılan işlevler (kanca adı).
HOOK_NAME = {**{f"ReviewTarget.{n}": "target_props" for n in ("pslug", "key", "spec")}}


# Değer karşılaştırması: Python değeri -> Rust sabit(ler)inin beklenen değeri. Listede olmayan BÜYÜK_HARF adlar birebir.
def _expect(name, v):
    if name == "LENSES":
        return {"BUILTIN_LENS": v[0]} if len(v) == 1 else None
    if name == "_LENS_TEXT":
        return {"LENS_TEXT_DRY_EN": v[("dry", "en")], "LENS_TEXT_DRY_TR": v[("dry", "tr")]} if len(v) == 2 else None
    if name == "_LENS_FORMAT":
        return {"LENS_FORMAT_EN": v["en"], "LENS_FORMAT_TR": v["tr"]} if len(v) == 2 else None
    return {name.lstrip("_"): v}


# ── (B) test sınıfları. CORE = test çekirdek işlevini sınar; ("dışı", iz, neden) = sınadığı şey bu crate'te yok ──────

CORE = "çekirdek"


def out(track, why):
    return ("dışı", track, why)


WR = "T8 koşucu `commands/web_review.py`"
WS = "T8/T10 `commands/web_steward.py`"
RS = "T8 review deposu aktarımı `review_store.py`"
ST = "T10 / rs/stew `steward.py`"
CLI = "T6 CLI `commands/steward.py`"
ADV = "T10 `steward_advance.py`"
LES = "T10 `steward_lessons.py`"
EXT = "T9 eklenti yükleyicisi `extensions.py`"
QUO = "T10 `steward_quota.py` / `web_steward.py`"

_runner = out(WR, "koşucunun süreç/tick/dosya davranışını sınar")
_flow = out(WS + " + " + WR, "doğrulama/onay/aktarım akışının orkestrasyonu (HTTP ucu, direktif, dosya yazımı)")
_adv = out(ADV, "onaylı bulgunun oturuma iletim planı")
_les = out(LES, "ders teslimi")
_store = out(RS, "git deposu görünürlüğü, sır taraması ve commit kapısı")

TESTS = {}


def classes(module, value, names):
    for n in names.split():
        TESTS[f"{module}.{n}"] = value


def tests(prefix, value, names):
    for n in names.split():
        TESTS[f"{prefix}.test_{n}"] = value


classes("test_body_sensitive_c", out(ADV + " + " + WR, "gövdeye göre hassas bulgu elemesi (iletim/otomatik onay)"),
        "BodySensitive AutoApprove")
classes("test_empty_fleet_p0", out(ST, "boş filo / \"iş yok\" reddi kuralları"), "NoneRejected")
classes("test_empty_fleet_p0", out(QUO, "kota sonrası yeniden açma"), "QuotaReopen")
classes("test_extensions", CORE, "RegistryTest")
classes("test_extensions", out(EXT, "eklenti keşfi/yükleme (Rust'ta derleme zamanı bağımlılığı)"),
        "LoaderTest AutoloadInTestsTest")
classes("test_extensions", out("T9", "Python import yönü denetimi; Rust'ta crate bağımlılık yönü"), "OneWayDependencyTest")
classes("test_owner_claim_nudge", out(ST, "sahip beyanı dürtmesi / `steward_nowork.py`"), "OwnerClaim")
classes("test_owner_claim_nudge", out(RS, "kullanım dosyalarında sır taraması (`secret_hits`)"), "UsageScan")
classes("test_pool_focus_action", out(WR, "havuz eylem ucu (`pool_action`)"), "TestPoolFocusAction")
classes("test_pool_only_action", out(WR, "havuz eylem ucu (`pool_action`)"), "TestPoolOnly")
classes("test_recover_draft_precedence", out(WR, "kurtarmada taslak/stdout önceliği"), "Precedence")
classes("test_review", CORE, """TestSlugTargets TestPlanner TestUncountedAttempts TestPoolSync TestParse TestRedactLabel
    TestPathsAndStores TestCopilotMode TestRequeueStaleVerify TestUsageSummary TestRedactLeaks TestDsnRedact TestEffortPairs
    TestReviewSmallFixes TestDsnEdgeCases TestLearnedPasswordLength ExportNoLocalPathTest R10SubMigrationTest""")
tests("test_review.TestPathsAndStores", out(ST, "`steward.paths_for` düzeni ve `valid_custom_id`; review yollarının payı "
                                            "`store.rs::ReviewPaths::for_sid`, `helpers::review_paths_layout_per_identity`"),
      "paths")
tests("test_review.TestCopilotMode", out(WR, "copilot argv'si"), "argv_read_only_and_prompt")
tests("test_review.TestDsnRedact", out(WR, "`IoLog` olaylar arası parola öğrenme"), "iolog_learns_across_events")
classes("test_review", out("rs/state + " + ST, "`settings.steward_config` okuma ve varsayılanlar"), "TestConfigRole")
classes("test_review", _runner, "TestClaudeArgv TestCodexArgv TerminateReapsTest")
classes("test_review_anthropic", CORE, "TestAnthropicCost")
classes("test_review_anthropic", _runner, "TestTrialComplete")
classes("test_review_backlog", CORE, "BacklogTest")
tests("test_review_backlog.BacklogTest", out(WR, "TODO/RTODO dosya okuma önbelleği"),
      "review_backlog_reads_todo_and_rtodo_with_cache")
classes("test_review_canonical", CORE, "CanonRankTest")
classes("test_review_capacity_backoff", CORE, "CapacityBackoffTests")
classes("test_review_claude_subscription", CORE, "ClaudeSubscriptionTargets SeparateKeysAndSameModel")
classes("test_review_cleanup_fixes", CORE, "FindingKeyTest")
classes("test_review_cleanup_fixes", out(ST, "`steward.is_conditional_note`"), "ConditionalNoteTest")
classes("test_review_codex_usage_limit", CORE, "CodexUsageLimit")
classes("test_review_copilot_quota", CORE, "ParseTests ReconcileTests")
classes("test_review_copilot_quota", out(WR, "`usage_state` okuyup blok tazeleme ve kota görünümü"), "RefreshTests")
classes("test_review_duration_summary", CORE, "DurationTest StaleTextTest")
classes("test_review_duration_summary", out(WR, "claude/codex JSON çıktısı ve kullanım ayrıştırma"), "ClaudeJsonTest CodexUsageTest")
tests("test_review_duration_summary.CodexUsageTest", CORE, "summary_totals_without_invented_split")
classes("test_review_duration_summary", out(CLI, "süre biçimlendirme `_run_dur`"), "RunDurTest")
classes("test_review_export_target_repo", CORE, "TestExportRootPure TestComboWorktree")
classes("test_review_export_target_repo", _flow, "TestExportRoutesByPath")
classes("test_review_fence_kinds", CORE, "FenceKindTest")
classes("test_review_findings_flow", _flow, """TestAutoFindings TestExportStaleCheck TestVerify TestVerdicts
    TestExportUnverifiedToRtodo TestDecideExport TestRemoteExport TestRemoteExportRealDriver TestGates
    TestEvrenRemoteExportE2E TestAutoApprove TestAutoExport TestAutoVerify TestBeforeTbd""")
tests("test_review_findings_flow.TestExportStaleCheck", CORE, "stale_reason_pure")
classes("test_review_findings_flow", CORE, "TestScanVerdicts")
classes("test_review_findings_flow", out(CLI, "CLI argümanından API'ye eşleme"), "TestCli")
classes("test_review_findings_flow", out(WR, "rapor ve kullanım dosyalarını depoya kopyalama"), "StoreReportsTest")
classes("test_review_io_history", out(WR, "`IoLog`, canlı akış, bayraklar ve kurtarma"), "TestIoLog TestRunWritesIo")
classes("test_review_io_history", out(WR + " + " + WS, "sohbet/koşu geçmişi API'si"), "TestChatApi")
classes("test_review_io_history", CORE, "TestNaming ReportIncompleteTests")
tests("test_review_io_history.TestNaming", out(ST, "değnekçi başlığı ve rozet"), "steward_title_and_badge")
classes("test_review_lens", CORE, "LensPromptTest LensPathKeyTest")
classes("test_review_lens", out(WR, "elle koşuda mercek doğrulaması (`manual_run`)"), "ManualRunLensTest")
classes("test_review_limit_effort", CORE, "TestEffortAndLimit LimitScanTextsTests")
classes("test_review_model_health", CORE, "TestHealth TestExclusion")
classes("test_review_model_health", out(WS, "HTTP ucu yetki ve girdi denetimi"), "TestHttp")
classes("test_review_modes_pinned", CORE, "TestReviewModesPinned")
tests("test_review_modes_pinned.TestReviewModesPinned", out(WR, "`web_review.py` kaynağındaki hata metnini denetler"),
      "run_error_message_not_hardcoded")
classes("test_review_p12_misc", CORE, "DsnRedactionTest CountsAsAttemptTest")
classes("test_review_remote_verify", out(WR + " + " + WS, "uzak doğrulama sürücüsü"), "RemoteVerifyTest")
classes("test_review_self_verify", out(WR, "kendi kendine doğrulama süreci, kurtarma, toplu onay"), "SelfVerifyTest")
classes("test_review_slots", CORE, "TestParseSlots AgyBlockClearedBySuccessTest AgyUsageBlocksTest")
tests("test_review_slots.AgyUsageBlocksTest", out(WR, "`usage_state` ölçümünü okuma/tazeleme"),
      "fetch_reads_shared_usage_state_not_own_measure refresh_skips_without_agy_targets")
classes("test_review_slots", _runner, "TestTakeSlot TestSlotsTick TestAgyHomeTokenPrivate TestReportFilesPrivateUtf8 TestClaudeIsError")
classes("test_review_store", _store, "PureTest CommitTest StoreCommitGateTest ParseRemotePortTest")
tests("test_review_store.StoreCommitGateTest", out(WR + " + " + RS, "commit kapısının tick'teki off/dry/act sırası"),
      "off_dry_first_then_act_daily")
classes("test_review_timeout_kismi", _runner, "TestTimeoutKismi")
classes("test_review_window_hours", CORE, "ReviewWindowHoursTests")
classes("test_steward_advance", _adv, "TodoStatusTest PlanTest RemoteAdvanceTest TickE2E")
classes("test_steward_bridges_e2e", _les, "LessonsBridge")
classes("test_steward_bridges_e2e", out(ST + " + " + WS, "devirde soru taşıma, bildirim, oturum adı çözümü"), "HandoverQuestions")
classes("test_steward_lessons", _les, "ReadTest DuplicateSignatureTest PruneTest PlanTest DeliverTest AckTest AckStateTest")
classes("test_steward_review_api", out(WS, "reviewer HTTP uçları"), "TestPool TestRunCancel TestReads")
classes("test_steward_review_api", out(CLI, "CLI argümanından API'ye eşleme ve çıktı"), "TestCli")
classes("test_usage_cost_prompt_tokens", CORE, "UsageCost")
classes("test_usage_cost_robust", CORE, "UsageCostRobustTest")
classes("test_web_review_runner", _runner, "TestEvren TestCancel TestAgy TestBannerLimit TestBodyless TestRecover TestDetached")
tests("test_web_review_runner.TestBannerLimit", CORE, "month_start_helper")
tests("test_web_review_runner.TestBodyless", CORE, "report_bodyless_rule")
classes("test_web_review_tick", _runner, "TestReviewerSmalls TestTick TestModelsFailure")

# Çekirdek testinin sınadığı adlar kaynaktan (`rv.<ad>`) çıkarılır; çıkarılamayan ya da yanıltanlar elle:
SUBJECT = {
    "test_review_lens.LensPathKeyTest.test_lens_never_in_planner_targets": ["ReviewTarget.lens"],
    "test_review_modes_pinned.TestReviewModesPinned.test_modes_pinned": ["MODES"],
}

# ── kaynak okuma ─────────────────────────────────────────────────────────────────────────────────────────────────────

errors = []


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def code_only(rust):
    return "\n".join("" if ln.lstrip().startswith("//") else ln for ln in rust.split("\n"))


def block(src, opener):
    """`opener` eşleşmesinden sonraki ilk `{...}` bloğu (kaba parantez sayımı)."""
    for m in re.finditer(opener, src):
        i = src.find("{", m.end() - 1)
        depth = 0
        for j in range(i, len(src)):
            depth += {"{": 1, "}": -1}.get(src[j], 0)
            if depth == 0:
                yield src[i:j + 1]
                break


def rust_exists(ref):
    file, item = ref.split(".rs::")
    src = code_only(read(os.path.join(CRATE, "src", file + ".rs")))

    def defined(text, name):
        n = re.escape(name)
        return bool(re.search(rf"\b(fn|const|static|struct|enum|type)\s+{n}\b|\bre!\({n},", text))

    if "." in item:
        typ, field = item.split(".")
        return any(re.search(rf"\bpub\s+{field}\s*:", b) for b in block(src, rf"\bstruct\s+{typ}\b"))
    if "::" in item:
        owner, name = item.split("::")
        if owner[0].isupper():
            return any(defined(b, name) for b in block(src, rf"\bimpl(?:<[^>]*>)?\s+{owner}\b[^{{;]*\{{"))
        return any(defined(b, name) for b in block(src, rf"\bfn\s+{owner}\b"))
    return defined(src, item)


def dispatch_arms():
    """`tests/support/mod.rs` `call` eşlemesi: kanca adı -> kolun metni."""
    src = read(os.path.join(CRATE, "tests", "support", "mod.rs"))
    body = src[src.index("pub fn call("):]
    parts = re.split(r'^        "([A-Za-z_0-9]+)" =>', body, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def rust_tests(file):
    return set(re.findall(r"#\[test\]\s*(?:#\[[^\]]*\]\s*)*fn\s+(\w+)", read(os.path.join(CRATE, "tests", file))))


# ── Python: review.py ────────────────────────────────────────────────────────────────────────────────────────────────

def review_items():
    """[(ad, satır, tür, düğüm)] modül düzeyi her tanım, sınıf üyesi ve diğer ifade."""
    tree = ast.parse(read(REVIEW))
    items = []

    def walk(body, prefix=""):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                items.append((prefix + n.name, n.lineno, "yöntem" if prefix else "işlev", n))
            elif isinstance(n, ast.ClassDef):
                items.append((prefix + n.name, n.lineno, "sınıf", n))
                walk(n.body, prefix + n.name + ".")
            elif isinstance(n, (ast.Assign, ast.AnnAssign)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in targets:
                    for name in ([t] if not isinstance(t, ast.Tuple) else t.elts):
                        if not isinstance(name, ast.Name):
                            errors.append(f"review.py:{n.lineno}: beklenmeyen atama hedefi {ast.dump(name)[:60]}")
                            continue
                        is_re = "re.compile(" in (ast.unparse(n.value) if n.value else "")
                        kind = "alan" if prefix else "regex" if is_re else "sabit"
                        items.append((prefix + name.id, n.lineno, kind, n))
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                continue
            elif isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
                continue
            elif not prefix and ast.unparse(n) in STATEMENTS:
                items.append((ast.unparse(n), n.lineno, "ifade", n))
            else:
                errors.append(f"review.py:{n.lineno}: eşlemesi olmayan ifade {ast.unparse(n)[:80]}")

    walk(tree.body)
    return items


def python_values(items):
    ns = {}
    for name, _, kind, node in items:
        if kind == "sabit" and node.value is not None:
            try:
                ns[name] = eval(compile(ast.Expression(node.value), REVIEW, "eval"), {"__builtins__": {}}, dict(ns))
            except Exception:
                pass
    return ns


def rust_values():
    ns, todo = {}, []
    for path in sorted(glob.glob(os.path.join(CRATE, "src", "*.rs"))):
        src = code_only(read(path))
        for m in re.finditer(r"^(?:pub(?:\([a-z]+\))?\s+)?const\s+([A-Z0-9_]+)\s*:[^=]*=\s*(.*?);[ \t]*$", src, re.M | re.S):
            todo.append((m.group(1), m.group(2)))
    for _ in range(3):                                   # sabit başka sabite başvurabilir
        for name, expr in todo:
            try:
                ns[name] = eval(expr.strip().lstrip("&"), {"__builtins__": {}}, dict(ns))
            except Exception:
                pass
    return ns


def plain(v):
    if isinstance(v, dict):
        return [[k, plain(x)] for k, x in v.items()]
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    return v


# ── Python: testler ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_modules():
    mods = {}
    for f in sorted(glob.glob(os.path.join(REPO, "py", "tests", "test_*.py"))):
        src = read(f)
        # `run_parity.py` ile AYNI seçim
        if re.search(r"claudeops import[^\n]*\breview\b(?!_)|claudeops\.review\b(?!_)", src):
            mods[os.path.basename(f)[:-3]] = ast.parse(src)
    parity_src = read(os.path.join(HERE, "run_parity.py"))
    if r'claudeops import[^\n]*\breview\b(?!_)|claudeops\.review\b(?!_)' not in parity_src:
        errors.append("run_parity.py seçim regex'i değişmiş: map_table.py ile eşitle")
    return mods


def review_tests(mods, review_names):
    """[(kimlik, dosya, satır, doğrudan başvurulan review adları)]; kalıtılan testler dahil."""
    classes_ = {(m, c.name): c for m, t in mods.items() for c in t.body if isinstance(c, ast.ClassDef)}
    rows, defined, seen_defs = [], set(), set()
    for m, tree in mods.items():
        aliases = {a.asname or a.name for x in ast.walk(tree) if isinstance(x, ast.ImportFrom) and x.module == "claudeops"
                   for a in x.names if a.name == "review"}
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        defined |= {f"{m}.py:{n.lineno}" for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")}

        def mro(c):
            yield c
            for b in c.bases:
                if (m, ast.unparse(b)) in classes_:
                    yield from mro(classes_[(m, ast.unparse(b))])

        for c in [x for x in tree.body if isinstance(x, ast.ClassDef)]:
            methods = {}
            for k in mro(c):
                for fn in k.body:
                    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.setdefault(fn.name, fn)
            for name, fn in methods.items():
                if not name.startswith("test_"):
                    continue
                refs, stack, seen = set(), [fn], set()
                while stack:
                    for x in ast.walk(stack.pop()):
                        if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name):
                            if x.value.id in aliases and x.attr in review_names:
                                refs.add(x.attr)
                            elif x.value.id == "self" and x.attr in methods and x.attr not in seen \
                                    and not x.attr.startswith("test_"):
                                seen.add(x.attr)
                                stack.append(methods[x.attr])
                        elif isinstance(x, ast.Name) and x.id in funcs and x.id not in seen:
                            seen.add(x.id)
                            stack.append(funcs[x.id])
                seen_defs.add(f"{m}.py:{fn.lineno}")
                rows.append((f"{m}.{c.name}.{name}", f"{m}.py", fn.lineno, refs))
    for lost in sorted(defined - seen_defs):
        errors.append(f"tabloya girmeyen test tanımı: {lost}")
    return rows


# ── tablolar ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def cell(text):
    return text.replace("|", "\\|").replace("\n", " ")


def short(test_id):
    mod, _, name = test_id.rpartition(".")
    return f"{mod}::{name}"


def build(report):
    items = review_items()
    names = {i[0] for i in items}
    calls, by_test = report["calls"], report["by_test"]
    if report["mismatches"]:
        errors.append(f"parite raporunda {len(report['mismatches'])} fark var")
    for name in sorted((set(MAP) | set(UNIT) | set(NOTES)) - names):
        errors.append(f"eşlemede olup review.py'de olmayan ad: {name}")
    arms, helpers = dispatch_arms(), rust_tests("helpers.rs")
    pyv, rsv = python_values(items), rust_values()

    # kullanım grafiği: ad -> onu anan tanımlar
    users = {n: set() for n in names}
    for name, _, kind, node in items:
        if kind in ("sınıf", "ifade"):
            continue
        value = node if kind in ("işlev", "yöntem") else node.value
        for x in ast.walk(value) if value is not None else ():
            if isinstance(x, ast.Name) and x.id in users and x.id != name:
                users[x.id].add(name)

    def hook(name):
        return HOOK_NAME.get(name, name)

    def compared_callers(name):
        found, seen, stack = [], {name}, [name]
        while stack:
            for u in sorted(users.get(stack.pop(), ())):
                if u in seen:
                    continue
                seen.add(u)
                if calls.get(hook(u)):
                    found.append(u)
                else:
                    stack.append(u)
        return sorted(found)

    inverse = {}
    for test, fns in by_test.items():
        for fn in fns:
            inverse.setdefault(fn, []).append(test)

    def evidence(fn):
        found = sorted(inverse.get(fn, []))
        edge = [t for t in found if t.startswith("parity_edges.")]
        own = [t for t in found if not t.startswith(("parity_edges.", "(modül)"))]
        sample = [short(t) for t in own[:1] + edge[:1]]
        return f"`{fn}`: {calls[fn]} çağrı, {len(found)} test" + (f" (ör. {', '.join(sample)})" if sample else "")

    a_rows, a_status = [], {}
    for name, line, kind, _ in items:
        if kind == "ifade":
            status, rust, proof = "kapsam dışı", "yok", STATEMENTS[name]
        elif name not in MAP:
            errors.append(f"review.py:{line}: eşlemesi olmayan ad {name}")
            continue
        else:
            refs = MAP[name]
            missing = [r for r in refs if not rust_exists(r)]
            rust = ", ".join(f"`{r}`" for r in refs)
            proof, status = [], ""
            if missing:
                status = "EKSİK"
                proof.append("kaynakta yok: " + ", ".join(missing))
            h = hook(name)
            if kind in ("işlev", "yöntem") and calls.get(h):
                arm = arms.get(h, "")
                for r in refs:
                    item = r.split(".rs::")[1].split("::")[-1]
                    if not re.search(rf"\b{item}\b", arm):
                        errors.append(f"parite sunucusu `{h}` kolu `{item}` çağırmıyor ({name})")
                proof.append(evidence(h))
                status = status or "karşılandı (parite)"
            else:
                if kind in ("sabit", "regex") and name in pyv:
                    want = _expect(name, pyv[name])
                    if want and all(k in rsv for k in want):
                        bad = [k for k, v in want.items() if plain(v) != plain(rsv[k])]
                        if bad:
                            status = "EKSİK"
                            errors.append(f"{name}: Rust değeri farklı: {bad}")
                        else:
                            proof.append("betik: değer Rust sabitiyle eşit")
                            status = status or "karşılandı (değer eşit)"
                    elif name.isupper() and not name.startswith("_"):
                        errors.append(f"{name}: değer karşılaştırılamadı")
                via = ([u for u in ("targets_from_config", "target_props") if calls.get(u)]
                       if kind in ("sınıf", "alan") else compared_callers(name))
                if via:
                    shown = ", ".join(f"`{u}` ({calls[hook(u)]})" for u in via[:4])
                    proof.append(f"parite, şu çağrılar üzerinden: {shown}" + (f" +{len(via) - 4}" if len(via) > 4 else ""))
                    status = status or "karşılandı (dolaylı parite)"
                for t in UNIT.get(name, ()):
                    if t not in helpers:
                        errors.append(f"birim testi yok: helpers::{t}")
                    proof.append(f"`helpers::{t}`")
                    status = status or "karşılandı (birim testi)"
            if not status:
                status = "EKSİK"
                proof.append("hiçbir test ya da değer denetimi yok")
            if name in NOTES:
                proof.append(NOTES[name])
            proof = "; ".join(proof)
        a_status[name] = status
        a_rows.append(f"| `{cell(name)}` ({kind}, review.py:{line}) | {cell(rust)} | {cell(proof)} | {status} |")

    mods = test_modules()
    trs = review_tests(mods, names)
    ids = {t[0] for t in trs}
    for t in sorted(set(by_test) - ids):
        if not t.startswith(("parity_edges.", "(modül)")):
            errors.append(f"parite raporundaki test tabloda yok: {t}")
    used = set()
    b_rows = []
    for tid, file, line, refs in trs:
        mod, cls, fn = tid.split(".")
        key = tid if tid in TESTS else f"{mod}.{cls}"
        if key not in TESTS:
            errors.append(f"eşlemesi olmayan test sınıfı: {mod}.{cls}")
            continue
        used.add(key)
        value = TESTS[key]
        got = sorted(by_test.get(tid, []))
        label = f"`{file}:{line}` `{cls}.{fn}`"
        if value == CORE:
            subject = SUBJECT.get(tid) or sorted(refs - {"ReviewTarget"})
            if not subject:
                errors.append(f"çekirdek testi için sınanan ad bulunamadı: {tid}")
                continue
            rust, proof, bad = [], [], []
            for s in subject:
                rust += [r for r in MAP.get(s, []) if r not in rust]
                node_kind = next((k for n, _, k, _ in items if n == s), "")
                if node_kind in ("sabit", "regex", "alan"):
                    ok = a_status.get(s, "").startswith("karşılandı")
                    proof.append(f"`{s}`: {a_status.get(s)} (bölüm A)")
                elif s in got:
                    ok = True
                    proof.append(f"parite (bu test): `{s}`")
                elif s in UNIT and all(t in helpers for t in UNIT[s]):
                    ok = True
                    proof.append("birim: " + ", ".join(f"`helpers::{t}`" for t in UNIT[s]) + f" (`{s}` kancada sarılı değil)")
                elif calls.get(s):
                    ok = True
                    proof.append(f"`{s}` bu testte karşılaştırılmadı (review işlevi taklit edilmiş); başka testlerde: {evidence(s)}")
                else:
                    ok = False
                if not ok:
                    bad.append(s)
            extra = [g for g in got if g not in subject]
            if extra:
                proof.append("ayrıca bu testte: " + ", ".join(f"`{g}`" for g in extra))
            if bad:
                errors.append(f"{tid}: kanıtsız ad {bad}")
            if any(s in got for s in subject):
                status = "karşılandı" if not bad else "EKSİK"
            else:
                status = "karşılandı (başka test)" if not bad else "EKSİK"
            b_rows.append(f"| {label} | {cell(', '.join(f'`{s}`' for s in subject))} | "
                          f"{cell(', '.join(f'`{r}`' for r in rust))}; {cell('; '.join(proof))} | {status} |")
        else:
            _, track, why = value
            direct = sorted(refs - {"ReviewTarget"})
            text = f"kapsam dışı: {why}; iz {track}"
            if got:
                text += "; bu testte yan çağrı olarak parite altında: " + ", ".join(f"`{g}`" for g in got)
            skipped = [d for d in direct if d not in got and any(n == d and k == "işlev" for n, _, k, _ in items)]
            for s in skipped:
                if not calls.get(s):
                    errors.append(f"{tid}: `{s}` hiçbir testte karşılaştırılmadı")
            if skipped:
                text += "; burada karşılaştırılmayan (taklit/yalnız anılan), başka testlerde karşılaştırılan: " + \
                        ", ".join(f"`{s}` ({calls.get(s, 0)})" for s in skipped)
            seen_funcs = [g for g in sorted(set(got) | set(direct))]
            b_rows.append(f"| {label} | {cell(', '.join(f'`{g}`' for g in seen_funcs) or 'yok')} | {cell(text)} | kapsam dışı |")
    for key in sorted(set(TESTS) - used):
        errors.append(f"kullanılmayan test eşlemesi: {key}")
    for key in sorted(set(SUBJECT) - ids):
        errors.append(f"SUBJECT'te olmayan test: {key}")

    skipped = {}
    for k, n in report["skipped"].items():
        fn, why = k.split(": ", 1)
        skipped.setdefault(fn, []).append((why, n))
    s_rows = []
    for fn in sorted(skipped):
        if not calls.get(fn):
            errors.append(f"atlanan `{fn}` başka hiçbir yerde karşılaştırılmadı")
        why = "; ".join(f"{w}: {n}" for w, n in skipped[fn])
        s_rows.append(f"| `{fn}` | {cell(why)} | {cell(evidence(fn) if calls.get(fn) else 'yok')} |")

    def counts(rows):
        c = {}
        for r in rows:
            s = r.rstrip(" |").rsplit("| ", 1)[1]
            c[s] = c.get(s, 0) + 1
            if s == "EKSİK":
                errors.append("EKSİK satır: " + r.split(" | ")[0].lstrip("| "))
        return ", ".join(f"{k}: {v}" for k, v in sorted(c.items()))

    ac, bc = counts(a_rows), counts(b_rows)
    n_files = len({t[1] for t in trs})
    summary = f"A: {len(a_rows)} satır ({ac})\nB: {len(b_rows)} satır, {n_files} dosya ({bc})\natlanan işlev: {len(s_rows)}"
    text = "\n".join([
        BEGIN,
        "## Eşleme tablosu",
        "",
        "Üretim: `tests/py/map_table.py <parite raporu>` (rapor: `COPS_REV_PARITY_REPORT=<dosya> cargo test -p "
        "cops-review-core --test parity`). Rust yolları `rust/crates/cops-review-core/src/`e göredir.",
        "",
        "Durumlar: **karşılandı (parite)** işlevin kendisi Python ile aynı girdide karşılaştırıldı; **(dolaylı parite)** "
        "özel tanım, onu kullanan karşılaştırılan işlevler üzerinden (her dalının ayrı ayrı sınandığı iddiası değildir); "
        "**(değer eşit)** betik Python ve Rust sabit değerini karşılaştırdı; **(birim testi)** `tests/helpers.rs`; "
        "**karşılandı (başka test)** testin sınadığı ad o testte karşılaştırılamadı, başka kanıt satırda yazılı; "
        "**kapsam dışı** testin asıl iddiası bu crate'te olmayan koda ait (iz adı plan eşlemesidir, o izde yapıldığı "
        "anlamına gelmez). Parite, testin Python `assert`lerini Rust'ta koşmaz: aynı çağrıların aynı sonucu verdiğini gösterir.",
        "",
        "```", summary, "```",
        "",
        "### A. `py/claudeops/review.py` tanımları",
        "",
        "| Python | Rust | Parite / birim testi | Durum |",
        "|---|---|---|---|",
        *a_rows,
        "",
        "### B. Python testleri (`py/tests`, `run_parity.py` seçimi; kalıtılan testler dahil)",
        "",
        "| Python testi | Sınadığı / çağırdığı review adları | Rust karşılığı + kanıt, ya da gerekçe + iz | Durum |",
        "|---|---|---|---|",
        *b_rows,
        "",
        "### Kancanın atladığı çağrılar",
        "",
        "Bu çağrılar karşılaştırılmadı; son sütun aynı işlevin başka çağrılarda karşılaştırıldığını gösterir.",
        "",
        "| İşlev | Atlanma nedeni: sayı | Karşılaştırıldığı yer |",
        "|---|---|---|",
        *s_rows,
        END,
    ])
    return text, summary


def main():
    args = [a for a in sys.argv[1:] if a != "--check"]
    path = args[0] if args else os.environ.get("COPS_REV_PARITY_REPORT")
    if not path or not os.path.isfile(path):
        sys.exit("kullanım: map_table.py <parite raporu.json> [--check]")
    table, summary = build(json.loads(read(path)))
    print(summary)
    if errors:
        for e in errors:
            print("HATA:", e, file=sys.stderr)
        sys.exit(1)
    doc = read(DOC)
    if BEGIN in doc:
        new = doc[:doc.index(BEGIN)] + table + doc[doc.index(END) + len(END):]
    else:
        new = doc.rstrip("\n") + "\n\n" + table + "\n"
    if "--check" in sys.argv:
        # çağrı sayıları koşudan koşuya oynayabilir: sayılar dışarıda karşılaştırılır
        strip = lambda s: re.sub(r"\d+ çağrı|\(\d+\)|: \d+(?=[;|\s])", "N", s)
        sys.exit(0 if strip(new) == strip(doc) else "docs/rs-rev.md eşleme tablosu bayat")
    with open(DOC, "w", encoding="utf-8") as f:
        f.write(new)


if __name__ == "__main__":
    main()
