"""cops-providers parite koşucusu (Python tarafı). `tests/parity.rs` tarafından alt süreçte çalıştırılır.

Ortam ÇAĞIRAN tarafından yalıtılmış gelir (HOME, CLAUDEOPS_DIR geçici; PATH yalnız geçici sahte ikili dizini;
CLAUDEOPS_EXTENSIONS=0). Burada claudeops import edilmeden önce bu doğrulanır. Dış olgular (alt süreç, ağ, tmux, docker,
kota, token, araç zinciri) sahte değerlerle değiştirilir; GERÇEK süreç başlatılmaz (subprocess.run/Popen sahte).

Protokol: stdin'den satır başına bir JSON vaka, stdout'a satır başına bir JSON sonuç. Dosya düzenini (fixture) ve
anlık görüntüyü Rust tarafı kurar/alır; bu süreç yalnız çağrıyı yapar.
"""
import json
import os
import sys
import time
import types

_ROOT = os.environ.get("COPS_PARITY_ROOT", "")
assert _ROOT and os.path.isabs(_ROOT), "COPS_PARITY_ROOT yok"
for _k in ("HOME", "CLAUDEOPS_DIR"):
    assert os.environ.get(_k, "").startswith(_ROOT + "/"), f"{_k} geçici kökte değil"
assert os.environ.get("CLAUDEOPS_EXTENSIONS") == "0", "eklenti yükleme kapalı olmalı"
assert os.path.expanduser("~").startswith(_ROOT + "/")

_BASE_ENV = {k: os.environ[k] for k in ("HOME", "CLAUDEOPS_DIR", "PATH", "CLAUDEOPS_EXTENSIONS", "COPS_PARITY_ROOT")}

import subprocess  # noqa: E402

FACTS = {}
CALLS = {"popen": [], "run": [], "direct": []}


class _Done:
    def __init__(self, argv, rc, out, err):
        self.args, self.returncode, self.stdout, self.stderr = argv, rc, out, err


def _fake_run(argv, *a, **kw):
    argv = [str(x) for x in argv]
    CALLS["run"].append(argv)
    if len(argv) == 2 and argv[1] == "--help":
        return _Done(argv, 0, FACTS.get("claude_help", ""), "")
    if argv[1:3] == ["chat", "--help"]:
        return _Done(argv, 0, FACTS.get("ucli_help", ""), "")
    if argv[3:5] == ["mcp", "add"]:
        r = FACTS.get("mcp_register") or {"rc": 0}
        if "raise" in r:
            raise OSError(r["raise"])
        return _Done(argv, r.get("rc", 0), r.get("stdout", ""), r.get("stderr", ""))
    if argv[1:2] == ["models"]:
        return _Done(argv, 0, FACTS.get("agy_models_output", ""), "")
    raise AssertionError(f"beklenmeyen alt süreç: {argv!r}")


class _FakePopen:
    def __init__(self, argv, env=None, **kw):
        CALLS["popen"].append({"argv": [str(x) for x in argv], "env": [[k, v] for k, v in (env or {}).items()]})
        self.returncode = 0

    def wait(self, *a, **k):
        return 0


subprocess.run = _fake_run
subprocess.Popen = _FakePopen
subprocess.call = subprocess.check_call = subprocess.check_output = _fake_run

import claudeops.paths as paths  # noqa: E402

assert paths.CLAUDEOPS_DIR == os.environ["CLAUDEOPS_DIR"], "CLAUDEOPS_DIR yalıtılamadı"
import claudeops.bg_work as bg_work  # noqa: E402
import claudeops.diaglog as diaglog  # noqa: E402
import claudeops.preview as preview  # noqa: E402
import claudeops.settings as settings  # noqa: E402
import claudeops.effort as effort  # noqa: E402
import claudeops.routing as routing  # noqa: E402
import claudeops.spawn as spawn  # noqa: E402
import claudeops.steward as steward  # noqa: E402
import claudeops.extensions as extensions  # noqa: E402
import claudeops.authz as authz  # noqa: E402
import claudeops.searxng as searxng  # noqa: E402
import claudeops.ucli_agents as ucli_agents  # noqa: E402
import claudeops.ucli_ask as ucli_ask  # noqa: E402
import claudeops.ucli_checks as ucli_checks  # noqa: E402
import claudeops.ucli_cost as ucli_cost  # noqa: E402
import claudeops.ucli_metrics as ucli_metrics  # noqa: E402
import claudeops.ucli_client as ucli_client  # noqa: E402
import claudeops.ucli_session_opts as uso  # noqa: E402
import claudeops.providers as providers  # noqa: E402
import claudeops.providers.claude_provider as claude_p  # noqa: E402
import claudeops.providers.ucli_provider as ucli_p  # noqa: E402
import claudeops.providers.copilot_provider as copilot_p  # noqa: E402
import claudeops.providers.agy_provider as agy_p  # noqa: E402
import claudeops.providers.codex_provider as codex_p  # noqa: E402
from claudeops.providers.base import McpServerSpec  # noqa: E402

assert "claudeops_enterprise" not in sys.modules, "eklenti yüklendi"

DIAGS = []
_ORIG_DIAG = diaglog.diag_log


def _rec_diag(event, **kw):
    if not preview.active():      # gerçek `diag_log` gibi: kuru çalıştırmada günlük yok
        DIAGS.append([event, kw])


for _m in list(sys.modules.values()):
    if getattr(_m, "__name__", "").startswith("claudeops") and getattr(_m, "diag_log", None) is _ORIG_DIAG:
        _m.diag_log = _rec_diag
diaglog.diag_log = _rec_diag


def _fake_ensure_search_url(session_name=""):
    return FACTS.get("searxng_url")


_ORIG_ISSUE = ucli_agents.issue_token


def _fake_issue_token(session_name):
    if preview.active():      # kuru yol gerçek koddan: token üretmez
        return _ORIG_ISSUE(session_name)
    t = FACTS.get("agent_token") or {}
    if "error" in t:
        raise OSError(t["error"])
    return t.get("path", "")


def _fake_toolchain():
    tc = FACTS.get("toolchain")
    if isinstance(tc, dict):
        return dict(tc), ""
    return {}, str(tc or "Rust araç zinciri bulunamadı: <sahte>")


def _fake_path_exec(path_env=None):
    return list(FACTS.get("path_executables") or [])


def _fake_cap_exceeded(*a, **k):
    return bool(FACTS.get("cost_exceeded"))


def _fake_cost_state(*a, **k):
    return {"today_usd": 1.5, "cap_usd": 1.0}


def _fake_load_registry(owner=""):
    err = FACTS.get("checks_err") or ""
    return ({} if err else {"check": []}), err


def _fake_spawn_env(cli, name, cwd):
    return {k: v for k, v in (FACTS.get("hook_env") or [])}


def _fake_ext_mcp(cwd):
    s = FACTS.get("extension_mcp")
    return _spec(s) if s else None


searxng.ensure_search_url = _fake_ensure_search_url
ucli_agents.issue_token = _fake_issue_token
uso.rust_toolchain = _fake_toolchain
uso.path_executables = _fake_path_exec
ucli_p.path_executables = _fake_path_exec
ucli_cost.cap_exceeded = _fake_cap_exceeded
ucli_cost.state = _fake_cost_state
ucli_cost.reserve = lambda *a, **k: None
ucli_checks.load_registry = _fake_load_registry
authz.spawn_env = _fake_spawn_env
extensions.session_mcp_spec = _fake_ext_mcp
spawn._ids_held_by_others = lambda name: frozenset()


def _spec(d):
    return McpServerSpec(name=d["name"], command=d["command"], args=tuple(d.get("args") or ()),
                         allowed_tools=tuple(d.get("allowed_tools") or ()))


def _reset(case):
    FACTS.clear()
    FACTS.update(case.get("facts") or {})
    DIAGS.clear()
    for k in CALLS:
        CALLS[k].clear()
    settings._LOAD_CACHE.update(sig=None, val=None)
    claude_p._HELP_CACHE.clear()
    ucli_client._HELP_CACHE.clear()
    os.environ.clear()
    os.environ.update(_BASE_ENV)
    for k, v in case.get("env") or []:
        os.environ[k] = v
    ucli_agents._PANEL_PORT = FACTS.get("panel_port")
    live = FACTS.get("ucli_live") or {}
    ucli_p._LIVE_MODEL_CACHE = list(live.get("ids") or []) or list(ucli_p._MODEL_CHOICES)
    ucli_p._LIVE_MODEL_CACHE_TS = time.monotonic()
    ucli_p._LIVE_CAPS = dict(live.get("caps") or {})
    agy = providers.get_provider("agy")
    agy._cache_models = list(FACTS.get("agy_models") or [])
    agy._cache_ts = time.monotonic()
    codex = providers.get_provider("codex")
    codex._cache_ts = 0.0
    codex._cache_models = []


def _jsonable(v):
    if isinstance(v, float):
        if v != v:
            return {"$float": "nan"}
        if v in (float("inf"), float("-inf")):
            return {"$float": "inf" if v > 0 else "-inf"}
        return v
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, frozenset):
        return sorted(_jsonable(x) for x in v)
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if v is None or isinstance(v, (bool, int, str)):
        return v
    return {"$repr": repr(v)}


# ---------------------------------------------------------------------------------------------------------------- işlemler

def op_build(a):
    p = providers.get_provider(a["cli"])
    kw = {}
    if a.get("cli_opts") is not None and getattr(p, "accepts_cli_opts", False):
        kw["cli_opts"] = a["cli_opts"]
    if a.get("validate"):
        clean, err = p.validate_cli_opts(a.get("raw_opts"))
        if err:
            return {"validate_err": err}
        if clean:
            kw["cli_opts"] = clean
    return p.build_inner_command(a["cwd"], a["model"], a["perm"], a["effort"], a.get("resume"), a.get("prompt"),
                                 a["name"], extra_args=list(a.get("extra") or []), **kw)


def op_spawn(a):
    p = providers.get_provider(a["cli"])
    p.resolve_resume_id = lambda *x, **k: a.get("resume")
    mode = a["mode"]
    direct = []

    def _direct(name, cwd, inner, env):
        direct.append({"name": name, "cwd": cwd, "inner": inner, "env": [[k, v] for k, v in env.items()]})
        return True

    spawn.tmux_available = lambda: mode == "gt_tmux" or mode == "hidden"
    spawn.tmux_spawn_direct = _direct
    spawn.tmux_has_session = lambda name: True
    spawn.tmux_new_session_shell_fragment = lambda n, c, i: f"TMUXFRAG<{n}|{c}|{i}>"
    import claudeops.tmux_backend as tb
    tb.tmux_ghost_session = lambda *x, **k: False
    real_which = __import__("shutil").which
    spawn.shutil = types.SimpleNamespace(
        which=lambda n: (None if mode == "hidden" else "/usr/bin/gnome-terminal") if n == "gnome-terminal" else real_which(n))
    try:
        ret = spawn.spawn_session(a["name"], a["cwd"], a["model"], display=a.get("display", ":7"),
                                  permission_mode=a["perm"], effort=a["effort"], force_new=False,
                                  prompt=a.get("prompt"), dry_run=(mode == "dry"), cli=a["cli"],
                                  mcp_server=_spec(a["mcp"]) if a.get("mcp") else None,
                                  hidden=(mode == "hidden"), cli_opts=a.get("cli_opts"))
    finally:
        del p.resolve_resume_id
    return {"ret": ret, "direct": direct}


def _prov(a):
    return providers.get_provider(a["cli"])


def op_model(a):
    p = _prov(a)
    out = {
        "model_choices": p.model_choices(),
        "default_model_for": settings.default_model_for(p),
        "default_effort_for": settings.default_effort_for(p),
        "preferred_default_model": p.preferred_default_model(),
        "default_effort": p.default_effort(),
        "effort_levels": p.effort_levels(),
        "permission_modes": p.permission_modes(),
        "default_permission_mode": p.default_permission_mode(),
        "env_overrides": [[k, v] for k, v in p.env_overrides(a.get("name", "s1")).items()],
        "accepts_cli_opts": bool(getattr(p, "accepts_cli_opts", False)),
        "mcp_needs_cwd": bool(getattr(p, "mcp_needs_cwd", False)),
    }
    for m in a.get("models") or []:
        out.setdefault("model_effort_levels", []).append(p.model_effort_levels(m))
        out.setdefault("effort_levels_for", []).append(p.effort_levels_for(m))
        out.setdefault("refresh_stored_model", []).append(p.refresh_stored_model(m))
        out.setdefault("resolved_model_for", []).append(settings.resolved_model_for(p, m))
        out.setdefault("resolve_effort", []).append([p.resolve_effort(m, e) for e in a.get("efforts") or []])
    return out


def op_mcp(a):
    p = _prov(a)
    spec = _spec(a["spec"])
    if getattr(p, "mcp_needs_cwd", False):
        args = p.mcp_launch_args(spec, cwd=a.get("cwd", ""))
    else:
        args = p.mcp_launch_args(spec)
    return {"launch": args, "setup": p.mcp_setup_command(spec)}


def op_oneshot(a):
    return _prov(a).oneshot_argv(a["prompt"], a.get("model"))


def op_validate(a):
    clean, err = uso.validate_opts(a["raw"])
    return {"ok": clean, "err": err}


def op_exec_flags(a):
    return uso.exec_flags(a["opts"])


def op_expand(a):
    names, err = uso.expand_exec_cmds(a["items"], a["available"])
    return {"ok": names, "err": err}


def op_hook_cap(a):
    env = {k: v for k, v in a["hook_env"]}
    opts = spawn._apply_hook_session_cap(env, a.get("cli_opts"), _prov(a))
    return {"opts": opts, "env": [[k, v] for k, v in env.items()]}


def op_prefix(a):
    return spawn.spawn_priority_prefix(a["name"])


def op_preview(a):
    return spawn._dry_run_preview(a["cwd"], {k: v for k, v in a["overrides"]}, a["inv"])


def op_filter_env(a):
    return [[k, v] for k, v in spawn._filter_env_overrides({k: v for k, v in a["overrides"]}).items()]


def op_detect_display(a):
    return spawn.detect_display()


def op_mirror(a):
    ok = spawn.open_mirror_window(a["host"], a["name"], a["port"], display=a.get("display", ":7"))
    return {"ok": ok}


def op_main_session(a):
    return list(steward.main_session_model_effort(a["model"], a["effort"], a["cli"], a["sonnet"]))


def op_with_block(a):
    return routing._with_block(a["existing"], a.get("body"))


def op_sync_one(a):
    return routing._sync_one(a["path"], a["create"])


def op_guidance(a):
    return {"path": claude_p.claude_guidance_path(), "text": routing.routing_text()}


def op_effort(a):
    return {
        "rank": [effort.effort_rank(x) for x in a["levels"]],
        "split": [list(effort.split_tier(x)) for x in a["models"]],
        "sort": effort.sort_levels(a["levels"]),
        "nearest": [effort.nearest_effort(r, a["levels"]) for r in a["requests"]],
    }


def op_settings(a):
    svc = settings.ucli_services()
    return {
        "ucli_endpoint": settings.ucli_endpoint(),
        "ucli_web": settings.ucli_web_config(),
        "ucli_services": [{"id": d["id"], "label": d["label"], "wire": d["wire"], "endpoint": d["endpoint"],
                           "env": d["env"], "models": d["models"],
                           "efforts": [[k, v] for k, v in (d.get("efforts") or {}).items()]} for d in svc],
        "ucli_limit_overrides": [[k, v] for k, v in settings.ucli_limit_overrides().items()],
        "ucli_reasoning_mode": settings.ucli_reasoning_mode(),
        "ucli_stream": settings.ucli_stream_enabled(),
        "ucli_show_reasoning": settings.ucli_show_reasoning_enabled(),
        "ucli_state_dir": settings.ucli_state_dir_enabled(),
        "ucli_script_mode": settings.ucli_script_mode(),
        "ucli_cache_ttl": settings.ucli_cost_config()["cache_ttl"],
        "default_max_session_usd": uso.default_max_session_usd(),
        "ucli_metrics_enabled": bool(ucli_metrics.get_config().get("enabled")),
        "ucli_agents_enabled": ucli_agents.enabled(),
        "routing_guidance_enabled": settings.routing_guidance_enabled(),
        "routing_guidance_text": str(settings.load_settings().get("routing_guidance_text") or "").strip(),
        "byok_copilot": [[k, v] for k, v in settings.byok_env_for("copilot").items()],
        "byok_ucli": [[k, v] for k, v in settings.byok_env_for("ucli").items()],
        "priority_prefix": spawn.spawn_priority_prefix("s1"),
        "effort_levels_for": [uso.effort_levels_for(s, m) for s, m in a.get("svc_models") or []],
    }


def op_valid_url(a):
    return [settings._valid_http_url(u) for u in a["urls"]]


def op_ucli_misc(a):
    return {
        "state_dir_for": [ucli_client.state_dir_for(c) for c in a.get("cwds") or []],
        "is_child_name": [ucli_agents.is_child_name(n) for n in a.get("names") or []],
        "mcp_server_name": [ucli_p.mcp_server_name(n) for n in a.get("names") or []],
        "log_path": [ucli_cost.log_path(n) for n in a.get("names") or []],
        "flag_values": [ucli_client.binary_flag_values(a["binary"], f) for f in a.get("flags") or []],
        "supports": [ucli_client.binary_supports_flag(a["binary"], f) for f in a.get("flags") or []],
        "derives": ucli_client.binary_derives_context(a["binary"]),
        "reasoning": [ucli_p.reasoning_effort_for(m, lv) for m, lv in a.get("reasoning") or []],
        "forbidden": [uso.is_forbidden_cmd(n) for n in a.get("names") or []],
    }


def op_resolve_ucli(a):
    return ucli_client.resolve_binary()


def op_resolved_binary(a):
    return settings.resolved_binary(a["cli"])


def op_live_models(a):
    payload = a["payload"]

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *x):
            return False

        def read(self):
            return payload.encode("utf-8")

    import urllib.request
    old = urllib.request.urlopen
    urllib.request.urlopen = lambda *x, **k: _R()
    ucli_p._LIVE_CAPS = {}
    try:
        ids = ucli_p._fetch_live_models()
    finally:
        urllib.request.urlopen = old
    return {"ids": ids, "caps": ucli_p._LIVE_CAPS}


def op_agy_parse(a):
    FACTS["agy_models_output"] = a["output"]
    p = providers.get_provider("agy")
    p._cache_models = []
    p._fetch_models()
    return p._cache_models


def op_trust(a):
    return copilot_p.trust_folder(a["cwd"], a.get("config_path"))


def op_pyfmt(a):
    import shlex
    return {
        "quote": [shlex.quote(s) for s in a.get("strs") or []],
        "strip": [s.strip() for s in a.get("strs") or []],
        "json": [json.dumps(s) for s in a.get("strs") or []],
        "g": [f"{x:g}" for x in a.get("floats") or []],
        "str": [str(v) for v in a.get("values") or []],
        "int": [_try(lambda s=s: int(s)) for s in a.get("strs") or []],
        "float": [_try(lambda s=s: _jsonable(float(s))) for s in a.get("strs") or []],
    }


def _try(fn):
    try:
        return fn()
    except (ValueError, OverflowError):
        return None


def op_usage(a):
    p = _prov(a)
    texts = a.get("texts") or []
    return {
        "usage_command": p.usage_command(),
        "usage_needs_dismiss": p.usage_needs_dismiss(),
        "context_command": p.context_command(),
        "context_needs_dismiss": p.context_needs_dismiss(),
        "usage_fresh_argv": p.usage_fresh_argv(),
        "usage_fresh_tui_argv": p.usage_fresh_tui_argv(),
        "parse_usage_text": [p.parse_usage_text(t) for t in texts],
        "parse_fresh_usage": [p.parse_fresh_usage(t) for t in texts],
        "parse_context_text": [p.parse_context_text(t) for t in texts],
        "usage_auth_missing": [p.usage_auth_missing(t) for t in texts],
    }


def op_cost_config(a):
    return settings.ucli_cost_config()


def op_metrics_config(a):
    return ucli_metrics.get_config(a["raw"]) if "raw" in a else ucli_metrics.get_config()


def op_instr_check(a):
    return ucli_p.instructions_check(a["cwd"])


def _safe(fn):
    try:
        return fn()
    except Exception as e:      # noqa: BLE001
        return {"$exc": type(e).__name__}


def op_live(a):
    p = _prov(a)
    cwd, sid, pane = a["cwd"], a.get("sid"), a.get("pane") or ""
    saved_time, saved_resume = bg_work.time, copilot_p.CopilotProvider.resolve_resume_id
    bg_work.time = types.SimpleNamespace(time=lambda: a["now"])
    copilot_p.CopilotProvider.resolve_resume_id = lambda self, cwd, *x, **k: FACTS.get("copilot_resume")
    try:
        out = {
            "busy_status_pattern": p.busy_status_pattern(),
            "background_work": _safe(lambda: p.background_work(pane, cwd, sid)),
            "live_busy": _safe(lambda: p.live_busy(cwd, sid)),
            "live_tools": _safe(lambda: p.live_tools(cwd, sid)),
            "live_context": _safe(lambda: p.live_context(cwd, sid)),
            "live_usage": _safe(lambda: p.live_usage(cwd, sid)),
            "live_failed_turns": _safe(lambda: p.live_failed_turns(cwd, sid)),
            "live_phase": _safe(lambda: p.live_phase(cwd, sid)),
        }
        if a["cli"] == "ucli":
            out["dirs"] = ucli_client.chat_session_dirs(cwd)
            out["status_path"] = ucli_client.find_chat_file(cwd, f"{sid}.status.json")
            out["records"] = _safe(lambda: ucli_client.failed_turn_records(cwd, sid or ""))
        return out
    finally:
        bg_work.time, copilot_p.CopilotProvider.resolve_resume_id = saved_time, saved_resume


def op_bg(a):
    os.environ["TZ"] = a["tz"]
    time.tzset()
    now = a["now"]
    texts = a.get("texts") or []
    transcripts = a.get("transcripts") or []
    files = a.get("files") or []
    saved = bg_work.TRANSCRIPT_TAIL_BYTES
    return {
        "screen_bg_count": [_safe(lambda: bg_work.screen_bg_count(t)) for t in texts],
        "screen_bg_work": [bg_work.screen_bg_work(t) for t in texts],
        "codex_screen_count": [_safe(lambda: bg_work.codex_screen_count(t)) for t in texts],
        "transcript_pending": [_safe(lambda: bg_work.transcript_pending(ls, now)) for ls in transcripts],
        "codex_subagents_pending": [_safe(lambda: bg_work.codex_subagents_pending(ls, now)) for ls in transcripts],
        "transcript_pending_path": [_safe(lambda: bg_work.transcript_pending_path(f, now)) for f in files],
        "tail_lines": [bg_work.tail_lines(f) for f in files],
        "tail_bytes": saved,
        "epochs": [_safe(lambda: bg_work._epoch(x)) for x in (a.get("stamps") or [])],
    }


def _chat_out(v):
    """Eşlenmemiş vekil (UTF-8'e yazılamaz) işaretlenir: Rust U+FFFD verdiği için fark olarak görünür."""
    if isinstance(v, str):
        return "<vekil>" if any("\ud800" <= c <= "\udfff" for c in v) else v
    if isinstance(v, list):
        return [_chat_out(x) for x in v]
    if isinstance(v, dict):
        return {k: _chat_out(x) for k, x in v.items()}
    return v


def op_chat(a):
    p = _prov(a)
    cwd, sid = a["cwd"], a.get("sid")
    classes = (agy_p.AgyProvider, copilot_p.CopilotProvider)
    saved = [c.resolve_resume_id for c in classes]
    classes[0].resolve_resume_id = lambda self, cwd, *x, **k: FACTS.get("agy_resume")
    classes[1].resolve_resume_id = lambda self, cwd, *x, **k: FACTS.get("copilot_resume")
    try:
        out = {
            "last_exchange": _safe(lambda: p.last_exchange(cwd, sid)),
            "full_history": _safe(lambda: p.full_history(cwd, sid)),
            "last_message_role": _safe(lambda: p.last_message_role(cwd, sid)),
            "extra_file_roots": p.extra_file_roots(cwd),
        }
        if a["cli"] == "ucli":
            out["read_chat_history"] = _safe(lambda: ucli_client.read_chat_history(cwd, sid or ""))
        out["roots"] = [codex_p.SESSIONS_DIR, agy_p.CONVERSATIONS_DIR, copilot_p.SESSION_STORE_DB]
        return _chat_out(out)
    finally:
        for c, f in zip(classes, saved):
            c.resolve_resume_id = f


def op_transcript(a):
    """claude transkripti okuyucuları. `session_file_sid` (G1) sahte: vaka olgusu."""
    os.environ["TZ"] = a.get("tz") or "UTC0"
    time.tzset()
    saved = claude_p.session_file_sid
    claude_p.session_file_sid = lambda pid: (FACTS.get("session_sid") or {}).get(str(pid)) if pid else None
    try:
        out = {}
        out["reads"] = [{
            "model": _safe(lambda: claude_p.last_assistant_model(claude_p.Path(r["path"]), since=r.get("since"))),
            "effort": _safe(lambda: claude_p.last_assistant_effort(claude_p.Path(r["path"]), since=r.get("since"))),
            "request": _safe(lambda: claude_p.last_real_request_epoch(claude_p.Path(r["path"]))),
        } for r in a.get("reads") or []]
        out["stamps"] = [_safe(lambda: claude_p._row_epoch(x)) for x in a.get("stamps") or []]
        out["keeps"] = [[providers.get_provider(c).effort_switch_keeps_cache(m) for c in a.get("clis") or []]
                        for m in a.get("models") or []]
        out["ttl"] = [providers.get_provider(c).prompt_cache_ttl_seconds() for c in a.get("clis") or []]
        out["live"] = [[_safe(lambda: claude_p.live_or_spawn_model(q["cli"], q["cwd"], q.get("sid"), q["fallback"])),
                        _safe(lambda: claude_p.live_or_spawn_effort(q["cli"], q["cwd"], q.get("sid"), q["fallback"]))]
                       for q in a.get("live") or []]
        out["requests"] = [_safe(lambda: providers.get_provider(q["cli"]).last_request_epoch(
            q["cwd"], q.get("sid"), q.get("pid"))) for q in a.get("requests") or []]
        out["constants"] = [claude_p._LAST_MODEL_CHUNK_BYTES, claude_p._LAST_MODEL_MAX_BYTES,
                            claude_p.PROMPT_CACHE_TTL_SECONDS]
        return _chat_out(out)
    finally:
        claude_p.session_file_sid = saved


OPS = {k[3:]: v for k, v in globals().items() if k.startswith("op_")}


def main():
    for line in sys.stdin:
        case = json.loads(line)
        _reset(case)
        out = {"id": case.get("id")}
        try:
            out["ret"] = _jsonable(OPS[case["op"]](case.get("args") or {}))
            out["exc"] = None
        except Exception as e:      # noqa: BLE001
            out["ret"] = None
            out["exc"] = [type(e).__name__, str(e), isinstance(e, OSError)]
        out["diags"] = [[ev, [[k, _jsonable(v)] for k, v in kw.items()]] for ev, kw in DIAGS]
        out["popen"] = list(CALLS["popen"])
        out["run"] = list(CALLS["run"])
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        sys.stdout.flush()


main()
