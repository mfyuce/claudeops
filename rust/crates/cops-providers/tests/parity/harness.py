"""cops-providers parite koşucusu (Python tarafı). `tests/parity.rs` tarafından alt süreçte çalıştırılır.

Ortam ÇAĞIRAN tarafından yalıtılmış gelir (HOME, CLAUDEOPS_DIR geçici; PATH yalnız geçici sahte ikili dizini;
CLAUDEOPS_EXTENSIONS=0). Burada claudeops import edilmeden önce bu doğrulanır. Dış olgular (alt süreç, ağ, tmux, docker,
kota, token, araç zinciri) sahte değerlerle değiştirilir; GERÇEK süreç başlatılmaz (subprocess.run/Popen sahte).

Protokol: stdin'den satır başına bir JSON vaka, stdout'a satır başına bir JSON sonuç. Dosya düzenini (fixture) ve
anlık görüntüyü Rust tarafı kurar/alır; bu süreç yalnız çağrıyı yapar.
"""
import json
import os
import pathlib
import re
import shutil
import socket
import struct
import sys
import time
import threading
import types

_ROOT = os.environ.get("COPS_PARITY_ROOT", "")
assert _ROOT and os.path.isabs(_ROOT), "COPS_PARITY_ROOT yok"
for _k in ("HOME", "CLAUDEOPS_DIR"):
    assert os.environ.get(_k, "").startswith(_ROOT + "/"), f"{_k} geçici kökte değil"
assert os.environ.get("CLAUDEOPS_EXTENSIONS") == "0", "eklenti yükleme kapalı olmalı"
assert os.path.expanduser("~").startswith(_ROOT + "/")

_BASE_ENV = {k: os.environ[k] for k in ("HOME", "CLAUDEOPS_DIR", "PATH", "CLAUDEOPS_EXTENSIONS", "COPS_PARITY_ROOT")}

import subprocess  # noqa: E402


def _no_network(*a, **kw):
    """Parite koşucusu ağa ÇIKMAZ: unutulan bir sahte, gerçek isteğe değil görünür hataya dönsün."""
    raise AssertionError("parite koşucusunda gerçek ağ erişimi")


socket.getaddrinfo = socket.create_connection = _no_network
socket.socket.connect = socket.socket.connect_ex = _no_network

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


_REAL_RUN, _REAL_POPEN = subprocess.run, subprocess.Popen      # yalnız `g8_*` işlemleri: geçici ağaçtaki sahte betikler
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
import claudeops.startup_desktop as startup_desktop  # noqa: E402
import claudeops.review as review  # noqa: E402
import claudeops.tmux_backend as tmux_backend  # noqa: E402
import claudeops.extensions as extensions  # noqa: E402
import claudeops.authz as authz  # noqa: E402
import claudeops.searxng as searxng  # noqa: E402
import claudeops.ucli_agents as ucli_agents  # noqa: E402
import claudeops.ucli_approval as ucli_approval  # noqa: E402
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
from claudeops.providers.base import McpServerSpec, OneshotError  # noqa: E402

assert "claudeops_enterprise" not in sys.modules, "eklenti yüklendi"

DIAGS = []
# Yardımcı alt süreç geçidi (`childgroup._run_grouped`) da aynı sahteden / `_RealProcesses`te gerçek `subprocess.run`dan
# geçer; grup davranışı parite konusu değil (`py/tests/test_rsprov_child_group.py`, Rust `tests/real_process.rs`).
for _m in (searxng, ucli_client, claude_p, ucli_p, agy_p, sys.modules["claudeops.providers.base"]):
    assert hasattr(_m, "_run_grouped"), _m.__name__
    _m._run_grouped = lambda argv, **kw: subprocess.run(argv, **kw)

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


_ORIG_PATH_EXEC, _ORIG_TOOLCHAIN, _ORIG_REGISTRY = uso.path_executables, uso.rust_toolchain, ucli_checks.load_registry
_ORIG_ENSURE = searxng.ensure_search_url
searxng.ensure_search_url = _fake_ensure_search_url
ucli_agents.issue_token = _fake_issue_token
uso.rust_toolchain = _fake_toolchain
uso.path_executables = _fake_path_exec
ucli_p.path_executables = _fake_path_exec
# gerçekleri `ledger` ve `searxng` aileleri çağırır (`op_g8x_*`)
_ORIG_COST = (ucli_cost.cap_exceeded, ucli_cost.state, ucli_cost.reserve)
ucli_cost.cap_exceeded = _fake_cap_exceeded
ucli_cost.state = _fake_cost_state
ucli_cost.reserve = lambda *a, **k: None
ucli_checks.load_registry = _fake_load_registry
_ORIG_SPAWN_ENV, _ORIG_EXT_MCP = authz.spawn_env, extensions.session_mcp_spec     # gerçekleri `g9_*` işlemleri
authz.spawn_env = _fake_spawn_env
extensions.session_mcp_spec = _fake_ext_mcp
_ORIG_IDS_HELD = spawn._ids_held_by_others
_SPAWN_ENV_TOKEN = "0123456789abcdef"      # S4 sır ortam dosyası adı; Rust `FsProbe::spawn_env_token` aynı sabit
spawn._spawn_env_token = lambda: _SPAWN_ENV_TOKEN
spawn._ids_held_by_others = lambda name: frozenset()      # spawn ailesi; gerçeği `resume` ailesinde
# Parite koşucusu X sunucusuna ve `wmctrl`e DOKUNMAZ: masaüstü yönlendirmesi varsayılan kapalı; `g9_*` işlemleri gerçeğini
# yalnız sahte `count_fn`/`send_fn` ile çağırır.
_ORIG_STARTUP_ENV = startup_desktop.startup_env
startup_desktop.startup_env = lambda env, name: env


def _fake_proc_stat(pid):
    """`/proc` hiç okunmaz: vaka olgusu (yoksa OSError)."""
    raw = (FACTS.get("proc_stat") or {}).get(str(pid))
    if raw is None:
        raise OSError("sahte /proc: yok")
    return paths.parse_proc_stat(raw)


claude_p.proc_stat_fields = _fake_proc_stat


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
    claude_p._META_CACHE.clear()
    claude_p._HELP_CACHE.clear()
    ucli_client._HELP_CACHE.clear()
    os.environ.clear()
    os.environ.update(_BASE_ENV)
    os.environ["CLAUDEOPS_STORE_BACKEND"] = "files"      # agy_sids okuması geçici dizinde DB yaratmasın
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


def op_resolve_ucli_own(a):
    old = ucli_client.OWN_UCLI
    ucli_client.OWN_UCLI = pathlib.Path(_ROOT) / "work" / "repo" / "bin" / "ucli"
    try:
        return ucli_client.resolve_binary()
    finally:
        ucli_client.OWN_UCLI = old


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

    old = ucli_p._open_no_redirect
    ucli_p._open_no_redirect = lambda *x, **k: _R()
    ucli_p._LIVE_CAPS = {}
    try:
        ids = ucli_p._fetch_live_models()
    finally:
        ucli_p._open_no_redirect = old
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
    saved_time = bg_work.time
    bg_work.time = types.SimpleNamespace(time=lambda: a["now"])
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
        bg_work.time = saved_time


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


def op_transcript(a):
    """claude transkripti okuyucuları."""
    os.environ["TZ"] = a.get("tz") or "UTC0"
    time.tzset()
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
    out["live"] = [[_safe(lambda: claude_p.live_or_spawn_model(q["cli"], q["cwd"], q.get("sid"), q["fallback"],
                                                               pid=q.get("pid"))),
                    _safe(lambda: claude_p.live_or_spawn_effort(q["cli"], q["cwd"], q.get("sid"), q["fallback"],
                                                                pid=q.get("pid")))]
                   for q in a.get("live") or []]
    out["requests"] = [_safe(lambda: providers.get_provider(q["cli"]).last_request_epoch(
        q["cwd"], q.get("sid"), q.get("pid"))) for q in a.get("requests") or []]
    out["constants"] = [claude_p._LAST_MODEL_CHUNK_BYTES, claude_p._LAST_MODEL_MAX_BYTES,
                        claude_p.PROMPT_CACHE_TTL_SECONDS]
    return _chat_out(out)


def op_sources(a):
    """Model kaynakları (G7): adım dizisi, sahte saat/süreç/HTTP; arka plan iş parçacığı adım isterse (`run_bg`) koşar."""
    import urllib.error
    src = a["source"]
    clock = {"mono": 0.0, "wall": 0.0}
    calls, pending, current = [], [], {}

    def _payload():
        r = current.get("resp") or {"raise": "os"}
        kind = r.get("raise")
        if kind == "os":
            raise OSError("sahte")
        if kind == "http":
            raise urllib.error.HTTPError("http://sahte.invalid", 401, "sahte", {}, None)
        if kind == "timeout":
            raise subprocess.TimeoutExpired("agy", 5) if src == "agy" else TimeoutError("sahte")
        if "rep" in r:
            return bytes.fromhex(r["rep"][0]) * r["rep"][1]
        return bytes.fromhex(r["hex"])

    def _run(argv, **kw):
        assert kw.get("capture_output") and kw.get("text")
        calls.append(["run", [str(x) for x in argv], kw.get("timeout")])
        out = _payload().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")      # metin kipi
        return _Done(argv, current["resp"].get("rc", 0), out, "")

    class _Resp:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *x):
            return False

        def read(self):
            return self.data

    def _open(req, timeout=None):
        calls.append(["get", req.full_url, sorted([k.lower(), v] for k, v in req.header_items()), float(timeout)])
        return _Resp(_payload())

    class _Thread:
        def __init__(self, target=None, daemon=None, name=None):
            assert daemon is True
            self.target, self.name = target, name

        def start(self):
            calls.append(["bg", self.name])
            pending.append(self.target)

    fake_time = types.SimpleNamespace(monotonic=lambda: clock["mono"], time=lambda: clock["wall"])
    saved = (agy_p.time, agy_p.threading, agy_p._run_grouped, codex_p.time, ucli_p.time, ucli_p._open_no_redirect,
             uso._open_no_redirect)
    agy_p.time = codex_p.time = ucli_p.time = fake_time
    agy_p.threading = types.SimpleNamespace(Thread=_Thread, Lock=threading.Lock)
    agy_p._run_grouped = _run
    ucli_p._open_no_redirect = uso._open_no_redirect = _open
    agy, codex = agy_p.AgyProvider(), codex_p.CodexProvider()
    ucli_p._LIVE_MODEL_CACHE, ucli_p._LIVE_MODEL_CACHE_TS, ucli_p._LIVE_CAPS = None, 0.0, {}
    uso._MODELS_CACHE.clear()
    out = []
    try:
        for step in a["steps"]:
            current.clear()
            current.update(step)
            calls.clear()
            clock["mono"] = clock["wall"] = float(step["t"])
            if "settings" in step:
                with open(os.path.join(paths.CLAUDEOPS_DIR, "settings.json"), "w", encoding="utf-8") as f:
                    f.write(step["settings"])
                settings._LOAD_CACHE.update(sig=None, val=None)
            if "file" in step:
                path = codex_p.MODELS_CACHE
                if step["file"] is None:
                    if os.path.exists(path):
                        os.remove(path)
                else:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "wb") as f:
                        f.write(bytes.fromhex(step["file"]))
            row = {"ret": None, "exc": None}
            try:
                if src == "agy":
                    row["ret"] = list(agy.model_choices())
                elif src == "codex":
                    row["ret"] = list(codex.model_choices())
                elif src == "ucli":
                    row["ret"] = _jsonable(ucli_p.UcliProvider().model_choices())
                    row["caps"] = _jsonable(ucli_p._LIVE_CAPS)
                else:
                    row["ret"] = [x if x.isprintable() or x.encode("utf-8", "ignore").decode() == x else repr(x)      # eşlenmemiş vekil
                                  for x in uso.service_models(step["service"], step["key"], now=lambda: clock["wall"])]
            except Exception as e:      # noqa: BLE001
                row["exc"] = type(e).__name__
            if step.get("run_bg"):
                while pending:
                    pending.pop(0)()
            row["calls"] = list(calls)
            out.append(row)
    finally:
        (agy_p.time, agy_p.threading, agy_p._run_grouped, codex_p.time, ucli_p.time, ucli_p._open_no_redirect,
         uso._open_no_redirect) = saved
    return out


def _resume_one(q):
    """Oturum kimliği ve devam (G1): tek sorgu."""
    f, cwd, name = q["f"], q.get("cwd"), q.get("name") or ""
    if f == "resolve":
        return providers.get_provider(q["cli"]).resolve_resume_id(cwd, in_use=frozenset(q.get("in_use") or []),
                                                                  session_name=name)
    if f == "stopped":
        return providers.get_provider(q["cli"]).sid_for_stopped_session(cwd, name)
    if f == "jsonl":
        p = claude_p.jsonl_path_for(cwd, q.get("sid"))
        return None if p is None else str(p)
    if f == "latest":
        p = claude_p.find_latest_jsonl(cwd)
        return None if p is None else str(p)
    if f == "rollout":
        return providers.get_provider("codex")._rollout_path(cwd, q.get("sid"))
    if f == "session_sid":
        return claude_p.session_file_sid(q.get("pid"))
    if f == "meta":
        m = claude_p._jsonl_meta(claude_p.Path(q["path"]))
        return [m["title"], m["cwd"]]
    if f == "chat_rows":
        return claude_p._has_chat_rows(claude_p.Path(q["path"]))
    if f == "snapshot":
        snap = providers.get_provider(q["cli"]).snapshot_for_live_sid(cwd)
        return None if snap is None else sorted(snap)
    if f == "discover":
        before = q.get("before")
        return providers.get_provider(q["cli"]).discover_live_sid(cwd, None if before is None else frozenset(before))
    if f == "held":
        live = q.get("live")

        def _find(**_kw):
            if live is None:
                raise RuntimeError("tarama patladı")
            return [types.SimpleNamespace(name=n, sid=s) for n, s in live]
        saved, spawn.find_sessions = spawn.find_sessions, _find
        try:
            return sorted(_ORIG_IDS_HELD(name))
        finally:
            spawn.find_sessions = saved
    if f == "claimed":
        return agy_p._sid_claimed_by_other(q["known"], q["sid"], name)
    if f == "remember":
        agy_p._remember_agy_sid(name, q["sid"])
        return agy_p._load_agy_sids()
    if f == "constants":
        return [claude_p._META_HEAD_LINES, claude_p._RESUME_SCAN_LIMIT, claude_p._STUB_MAX_BYTES, claude_p._META_CACHE_MAX,
                codex_p._MAX_ROLLOUT_SCAN, copilot_p._RESUME_SCAN_LIMIT,
                [agy_p.CONVERSATIONS_CACHE, agy_p.CONVERSATIONS_DIR, claude_p.SESSIONS_DIR, codex_p.SESSIONS_DIR]]
    raise AssertionError(f"bilinmeyen sorgu: {f}")


def op_resume(a):
    out = _chat_out([_safe(lambda: _resume_one(q)) for q in a["queries"]])
    # Yazım vakaları: belge dönüşte karşılaştırıldı; dosya ve kilit ağaç görüntüsüne girmez.
    if any(q["f"] == "remember" for q in a["queries"]):
        for p in (agy_p.AGY_SIDS_JSON, agy_p.AGY_SIDS_JSON + ".lock"):
            if os.path.exists(p):
                os.remove(p)
    return out


# ---------------------------------------------------------------------------------------------- G4: TUI girdisi, canlı geçiş

def _bits(x):
    """Float bit düzeyinde karşılaştırılır (JSON metni iki dilde farklı yuvarlanabilir)."""
    return struct.unpack("<q", struct.pack("<d", float(x)))[0]


def op_g4_static(a):
    p = _prov(a)
    return {
        "has_conversation": p.has_conversation(),
        "wants_handover_wrapup": p.wants_handover_wrapup(),
        "wants_stuck_recovery": p.wants_stuck_recovery(),
        "input_settle_delay": _bits(p.input_settle_delay()),
        "compact_command": p.compact_command(),
        "mode_status_patterns": [[k, v] for k, v in p.mode_status_patterns().items()],
        "cyclable_modes": list(p.cyclable_modes()),
        "prepare_input": [p.prepare_input(t) for t in a["texts"]],
        "model_downgrade": [p.handover_model_downgrade(m) for m in a["models"]],
        "effort_downgrade": [p.handover_effort_downgrade(c, t) for c, t in a["efforts"]],
    }


def op_g4_strip(a):
    return [tmux_backend.strip_ansi(t) for t in a["texts"]]


def op_g4_modes(a):
    """`web._detect_mode_in_text`in desen kullanımı: IGNORECASE, sözlük sırasında ilk eşleşen."""
    p = _prov(a)
    pats = [(m, re.compile(v, re.IGNORECASE)) for m, v in p.mode_status_patterns().items()]
    return [next((m for m, r in pats if r.search(t)), None) for t in a["texts"]]


def op_g4_pane(a):
    """Sahte pane + sahte saat: her tmux çağrısı, uyku ve okunan an sırayla kaydedilir."""
    log, now = [], [float(a["t0"])]
    screens = list(a["screens"])
    keys = list(a.get("keys") or [])
    seen = [0, 0]      # capture, tuş sayacı

    def send_keys(name, text, settle_delay=0.0):
        log.append(["send_text", name, text, _bits(settle_delay)])
        now[0] += a.get("send_cost", 0.0)
        return a.get("send_ok", True)

    def send_key(name, key):
        log.append(["key", name, key])
        i = seen[1]
        seen[1] += 1
        return keys[i] if i < len(keys) else True

    def capture(name, lines=2000):
        log.append(["capture", name, lines, _bits(now[0])])
        i = seen[0]
        seen[0] += 1
        assert i < 5000, "bitmeyen bekleme"
        now[0] += a.get("capture_cost", 0.0)
        return screens[min(i, len(screens) - 1)] if screens else None

    def sleep(secs):
        log.append(["sleep", _bits(secs)])
        now[0] += secs

    saved = (tmux_backend.tmux_send_keys, tmux_backend.tmux_send_special_key, tmux_backend.tmux_capture, claude_p.time)
    tmux_backend.tmux_send_keys, tmux_backend.tmux_send_special_key = send_keys, send_key
    tmux_backend.tmux_capture = capture
    claude_p.time = types.SimpleNamespace(monotonic=lambda: now[0], sleep=sleep, time=time.time)
    try:
        p = _prov(a)
        which = a["which"]
        if which == "model":
            ret = p.apply_live_model_switch(a["name"], a["target"])
        elif which == "effort":
            ret = p.apply_live_effort_switch(a["name"], a["target"])
        else:
            ret = p.dismiss_stray_dialog(a["name"])
    finally:
        (tmux_backend.tmux_send_keys, tmux_backend.tmux_send_special_key, tmux_backend.tmux_capture,
         claude_p.time) = saved
    return {"log": log, "end": _bits(now[0]), "outcome": getattr(ret, "value", ret)}


OPS = {k[3:]: v for k, v in globals().items() if k.startswith("op_")}


class _RealProcesses:
    """Gerçek alt süreç (yalnız vaka ağacındaki sahte betik): `with` süresince sahteler kaldırılır."""

    def __enter__(self):
        subprocess.run, subprocess.Popen = _REAL_RUN, _REAL_POPEN

    def __exit__(self, *exc):
        subprocess.run, subprocess.Popen = _fake_run, _FakePopen


def op_g8_paths(a):
    return {"which": [shutil.which(n) for n in a["which"]],
            "real": [os.path.realpath(p) for p in a["real"]],
            "exec": _ORIG_PATH_EXEC()}


def op_g8_toolchain(a):
    tc, err = _ORIG_TOOLCHAIN()
    return [tc or None, err]


def op_g8_checks(a):
    out = []
    for owner in a["owners"]:
        data, err = _ORIG_REGISTRY(owner)
        out.append([err, None if err else data])
    return out


def op_g8_agents(a):
    seq = iter(range(1, 1000))
    saved = ucli_agents.secrets.token_hex, ucli_agents.time
    ucli_agents.secrets.token_hex = lambda n: (bytes([next(seq)]) * n).hex()
    ucli_agents.time = types.SimpleNamespace(time=lambda: a["now"])
    out = []
    try:
        for step, name in a["steps"]:
            try:
                if step == "issue":
                    out.append(["ok", _ORIG_ISSUE(name)])
                elif step == "revoke":
                    ucli_agents.revoke_parent(name)
                    out.append(["ok", None])
                else:
                    out.append(["ok", ucli_agents.parent_for_token((bytes([int(name)]) * 32).hex())])
            except Exception as e:      # noqa: BLE001
                out.append(["err", type(e).__name__])
    finally:
        ucli_agents.secrets.token_hex, ucli_agents.time = saved
    return out


def _fix_ts(path):
    import re
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(re.sub(r'"ts": "\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d"', '"ts": "T"', text))


def op_g8_diag(a):
    for event, fields in a["events"]:
        _ORIG_DIAG(event, **dict(fields))
    _fix_ts(diaglog.diag_log_path())
    return None


def op_g8_agy(a):
    for name, sid in a["writes"]:
        agy_p._remember_agy_sid(name, sid)
    return agy_p._load_agy_sids()


def op_g8_help(a):
    claude_p._HELP_UNREADABLE.clear()          # her vaka yeni süreç gibi
    ucli_client._HELP_UNREADABLE.clear()
    out = []
    with _RealProcesses():
        for kind, binary in a["calls"]:
            fn = claude_p.claude_help_text if kind == "claude" else ucli_client.chat_help_text
            out.append(fn(binary))
    return out


def op_g8_mcp(a):
    saved = ucli_p._MCP_ADD_TIMEOUT
    ucli_p._MCP_ADD_TIMEOUT = a.get("timeout", 20)
    try:
        with _RealProcesses():
            return providers.get_provider("ucli").mcp_launch_args(_spec(a["spec"]), a["cwd"])
    finally:
        ucli_p._MCP_ADD_TIMEOUT = saved


def op_g8_proxy(a):
    import urllib.request as ur
    out = []
    for env, url in a["cases"]:
        os.environ.clear()
        os.environ.update(dict(env))
        proxies = ur.getproxies_environment()
        req = ur.Request(url)
        if req.type not in proxies:
            out.append(["direct"])
            continue
        handler = ur.ProxyHandler(proxies)
        handler.parent = types.SimpleNamespace(open=lambda r, timeout=None: None)
        orig = req.type
        req.timeout = None      # `OpenerDirector.open` atar
        try:
            handler.proxy_open(req, proxies[orig], orig)
        except Exception:      # noqa: BLE001
            out.append(["unusable"])
            continue
        if not (req._tunnel_host is not None or req.has_proxy()):
            out.append(["direct"])
        elif (orig == "http" and req.type not in ("http", "https")) or not req.host:
            out.append(["unusable"])
        else:
            out.append(["proxy", req.host, orig == "http" and req.type == "https", req.get_header("Proxy-authorization")])
    return out


def op_g8x_ledger(a):
    base = os.path.expanduser("~/.claude/claudeops/ucli_usage")
    assert base == ucli_cost.USAGE_DIR and base.startswith(_ROOT + "/")
    for rel, at in a.get("mtimes") or []:
        os.utime(os.path.join(_ROOT, rel), (at, at))
    fakes = (ucli_cost.cap_exceeded, ucli_cost.state, ucli_cost.reserve)
    ucli_cost.cap_exceeded, ucli_cost.state, ucli_cost.reserve = _ORIG_COST
    ucli_cost.invalidate()
    ucli_cost._RESERVED.clear()
    review._BAD_SEEN.clear()          # her vaka yeni süreç gibi
    mult = lambda: ucli_cost.write_mult()
    out = []
    try:
        for step in a["steps"]:
            op, args = step[0], step[1:]
            try:
                if op == "state":
                    r = ucli_cost.state(args[0], base=base, use_cache=args[1])
                elif op == "per":
                    r = sorted([k, repr(v)] for k, v in ucli_cost.per_session_usd(args[0], base, mult()).items())
                elif op == "today":
                    r = repr(float(ucli_cost.today_usd(args[0], base, mult())))
                elif op == "rate":
                    r = [sorted([k, repr(v)] for k, v in ucli_cost.rate_by_session(args[0], args[1], base, mult()).items()),
                         repr(float(ucli_cost.rate_usd_per_hour(args[0], args[1], base, mult())))]
                elif op == "total":
                    r = repr(float(ucli_cost.total_usd(base, mult(), args[0])))
                elif op == "scan":
                    usd, why = ucli_cost.rv._scan_usage(os.path.join(base, args[0]), args[1], args[2], args[3])
                    r = [repr(float(usd)), why]
                elif op == "problem":
                    r = ucli_cost._ledger_problem(args[0], base, mult())
                elif op == "gate":       # `_claude_service_flags`in kapısı
                    with ucli_cost._one_read():
                        if ucli_cost.cap_exceeded(args[1], base):
                            st = ucli_cost.state(args[1], base=base, use_cache=False)
                            raise ucli_cost.DailyCapExceeded(st["today_usd"], st["cap_usd"])
                        r = ucli_cost.reserve(args[0], args[1], base)
                elif op == "cap":
                    r = ucli_cost.cap_exceeded(args[0], base)
                elif op == "reserve":
                    r = ucli_cost.reserve(args[0], args[1], base)
                elif op == "release":
                    r = ucli_cost.release(args[0])
                elif op == "held":
                    r = list(ucli_cost._RESERVED)
                elif op == "invalidate":
                    r = ucli_cost.invalidate()
                elif op == "write":      # dosya ekle (önbellek davranışı)
                    with open(os.path.join(base, args[0]), "a", encoding="utf-8") as f:
                        f.write(args[1])
                    r = None
                elif op == "days":
                    r = [repr(ucli_cost._day_start_ms(args[0])), [repr(ucli_cost._date_ms(d, end=e)) for d, e in args[1]]]
                elif op == "window":
                    r = ucli_cost.credit_window(args[0], args[1], args[2])
                else:
                    raise AssertionError(op)
                out.append(["ok", r])
            except ValueError as e:
                out.append(["err", ucli_cost.refusal(e)])
    finally:
        ucli_cost.cap_exceeded, ucli_cost.state, ucli_cost.reserve = fakes
        ucli_cost.invalidate()
        ucli_cost._RESERVED.clear()
    return out


def op_g8x_searxng(a):
    exe = shutil.which("docker")
    assert exe is None or exe.startswith(_ROOT + "/"), "gerçek docker PATH'te"
    health = list(a.get("health") or [])
    spawned = []

    def spawn_child():
        os.makedirs(searxng.STATE_DIR, exist_ok=True)
        open(searxng._log_path(), "ab").close()
        spawned.append(1)
        return True

    saved = (searxng.healthy, searxng._spawn_provision_child, searxng._wall, searxng.READY_WAIT_S, searxng._down_until)
    searxng.healthy = lambda port, timeout=1.5: health.pop(0) if health else False
    searxng._spawn_provision_child = spawn_child
    searxng._wall = lambda: a["now"]
    searxng.READY_WAIT_S = 0.0
    searxng._down_until = 0.0
    out = []
    try:
        with _RealProcesses():
            for session, dry in a["calls"]:
                if dry:
                    with preview.preview_only():
                        out.append(_ORIG_ENSURE(session))
                else:
                    out.append(_ORIG_ENSURE(session))
    finally:
        searxng.healthy, searxng._spawn_provision_child, searxng._wall, searxng.READY_WAIT_S, searxng._down_until = saved
    diags = [[ev, [[k, _jsonable(v)] for k, v in kw.items()]] for ev, kw in DIAGS]
    DIAGS.clear()
    return {"urls": out, "diags": diags, "name": searxng.container_name()}


def op_g8x_netguard(a):
    """Ağ engeli HÂLÂ tutuyor mu: sahtesi olmayan her çıkış yolu görünür hata vermeli."""
    import urllib.request as ur
    tries = {
        "searxng": lambda: searxng._http_get("http://127.0.0.1:9/healthz", 0.2),
        "servis": lambda: uso._open_no_redirect(ur.Request("http://127.0.0.1:9/"), timeout=0.2),
        "saglayici": lambda: ucli_p._open_no_redirect(ur.Request("http://127.0.0.1:9/"), timeout=0.2),
        "urlopen": lambda: ur.urlopen("http://example.invalid/", timeout=0.2),
        "soket": lambda: socket.socket().connect(("127.0.0.1", 9)),
        "ad": lambda: socket.getaddrinfo("example.invalid", 80),
    }
    out = []
    for name, call in tries.items():
        try:
            call()
            out.append([name, "AÇIK"])
        except AssertionError:
            out.append([name, "engelli"])
    return out


# ------------------------------------------------------------------------------------------------- G10: tek atımlık çağrı, onay

def _g10_guard():
    """G10 işlemleri gerçek alt süreç koşar: ikili YALNIZ geçici ağaçtan gelebilir, onay kökü de ağaçta olmalı."""
    ucli_client.OWN_UCLI = pathlib.Path(_ROOT) / "yok" / "ucli"
    assert ucli_approval.ROOT.startswith(_ROOT + "/") and ucli_client.STATE_ROOT.startswith(_ROOT + "/")
    assert ucli_p._API_KEY_FILE.startswith(_ROOT + "/")


class _G10:
    """Gerçek alt süreç + gerçek `diag_log` + sabit saat."""

    def __init__(self, now=0.0):
        self.now = now

    def __enter__(self):
        _g10_guard()
        self.saved = diaglog.diag_log, ucli_approval.time
        diaglog.diag_log = _ORIG_DIAG
        ucli_approval.time = types.SimpleNamespace(time=lambda: self.now)
        subprocess.run, subprocess.Popen = _REAL_RUN, _REAL_POPEN

    def __exit__(self, *exc):
        subprocess.run, subprocess.Popen = _fake_run, _FakePopen
        diaglog.diag_log, ucli_approval.time = self.saved
        if os.path.isfile(diaglog.diag_log_path()):
            _fix_ts(diaglog.diag_log_path())


def _g10_text(msg):
    """JSON ayrıştırma ayrıntısı (`JSONDecodeError` metni) taşınmaz."""
    return re.sub(r"\Aucli çıktısı JSON değildi: [^\n]*\nstdout=", "ucli çıktısı JSON değildi\nstdout=",
                  re.sub(r"\Aucli: ucli çıktısı JSON değildi: [^\n]*\nstdout=", "ucli: ucli çıktısı JSON değildi\nstdout=", msg))


def op_g10_chat(a):
    out = []
    with _G10(a.get("now", 0.0)):
        for call in a["calls"]:
            try:
                out.append(["ok", ucli_client.ucli_chat_once(call["root"], call["prompt"], **call.get("kw", {}))])
            except ucli_client.UcliError as e:
                out.append(["err", _g10_text(str(e))])
    return out


def op_g10_oneshot(a):
    out = []
    with _G10():
        for call in a["calls"]:
            prov = providers.get_provider(call["cli"])
            if call.get("argv") is not None:
                prov.oneshot_argv = lambda prompt, model, argv=call["argv"]: argv
            try:
                out.append(["ok", prov.oneshot(call["prompt"], call.get("model"), call["cwd"], timeout=call["timeout"])])
            except OneshotError as e:
                out.append(["err", _g10_text(str(e))])
            finally:
                prov.__dict__.pop("oneshot_argv", None)
    return out


def op_g10_approval(a):
    out = []
    with _G10(a["now"]):
        for step, *args in a["steps"]:
            try:
                if step == "register":
                    key, cwd, session, argv, owner = args
                    out.append(["ok", ucli_approval.register(key, cwd, session, argv, owner=owner)])
                elif step == "set_state":
                    out.append(["ok", ucli_approval.set_state(*args)])
                elif step == "dir_for":
                    out.append(["ok", ucli_approval.dir_for(args[0], create=args[1])])
                else:
                    out.append(["ok", ucli_approval._slot_free(ucli_approval._load_index(), args[0])])
            except TypeError:
                out.append(["err", "TypeError", ""])
            except Exception as e:      # noqa: BLE001
                out.append(["err", type(e).__name__, str(e)])
    return out


def op_g10_pure(a):
    return {
        "suspended": [ucli_approval.parse_suspended(s) for s in a.get("suspended") or []],
        "run_key": [bool(ucli_approval._KEY.match(s)) for s in a.get("keys") or []],
        "id": [bool(ucli_approval._ID.match(s)) for s in a.get("ids") or []],
        "env_name": [bool(ucli_client._SAFE_ENV_NAME_RE.fullmatch(s)) for s in a.get("env_names") or []],
        "budget": [ucli_client.mark_budget_exhausted(json.loads(s)) for s in a.get("budget") or []],
        "redact": [ucli_client._redact(t, k) for t, k in a.get("redact") or []],
        "argv": [ucli_client.build_chat_argv(
            c["binary"], c["root"], repl=c["repl"], session=c["session"], model=c["model"], endpoint=c["endpoint"],
            api_key_env=c["api_key_env"], with_mcp=c["with_mcp"], max_steps=c["max_steps"],
            extra_args=c["extra_args"]) for c in a.get("argv") or []],
    }




# ------------------------------------------------------------------------------------------------ G9: spawn yürütme
# tmux, gnome-terminal (`Popen`), saat, süreç taraması, devam çözümü sahte; kanca ve eklenti MCP'si GERÇEK (`authz.spawn_env`,
# `extensions.session_mcp_spec`) ama kayıtları vakadan. İş parçacıkları `start()`ta EŞZAMANLI koşar (Rust bekçiyi join eder);
# bekçideki istisna Python'da yalnız iş parçacığını öldürür: burada yutulur.

class _G9:
    def __init__(self, a):
        self.calls = []
        f = FACTS
        self.has = list(f.get("has_session") or [])
        self.popen = list(f.get("popen") or [])
        self.t = 100.0
        self.saved = []

    def _set(self, obj, name, value):
        own = isinstance(obj, types.ModuleType) or name in vars(obj)
        self.saved.append((obj, name, getattr(obj, name), own))
        setattr(obj, name, value)

    def __enter__(self):
        c, f = self.calls, FACTS
        g9 = self

        def avail():
            c.append(["tmux_available"])
            return bool(f.get("tmux", True))

        def frag(n, cwd, inner):
            c.append(["frag", n, cwd, inner])
            if f.get("bad_name"):
                raise ValueError("tmux hedefi olamayan oturum adı")
            return f"TMUXFRAG<{n}|{cwd}|{inner}>"

        def attach(n):
            c.append(["attach", n])
            if f.get("bad_name"):
                raise ValueError("tmux hedefi olamayan oturum adı")
            return f"TMUXATTACH<{n}>"

        def direct(n, cwd, inner, env):
            c.append(["direct", n, cwd, inner, [[k, v] for k, v in env.items()]])
            return bool(f.get("direct_ok", True))

        def has_session(n):
            c.append(["has", n])
            return bool(self.has.pop(0)) if self.has else bool(f.get("has_default", True))

        def ghost(n):
            c.append(["ghost", n])
            return bool(f.get("ghost"))

        def capture(n, lines=2000):
            c.append(["capture", n, lines])
            return f.get("capture")

        def kill(n):
            c.append(["kill", n])

        class Popen:
            def __init__(self, argv, env=None, **kw):
                c.append(["launch", [str(x) for x in argv], [[k, v] for k, v in (env or {}).items()]])
                r = g9.popen.pop(0) if g9.popen else "ok"
                if r == "oserror":
                    raise FileNotFoundError(2, "No such file or directory")
                if r == "value":
                    raise ValueError("embedded null byte")

            def wait(self, *a, **k):
                return 0

        class Thread:
            def __init__(self, target=None, args=(), daemon=None, **kw):
                self.target, self.args = target, args

            def start(self):
                try:
                    self.target(*self.args)
                except Exception:      # noqa: BLE001
                    pass

        def which(n):
            if n == "gnome-terminal":
                c.append(["gt_available"])
                return "/usr/bin/gnome-terminal" if f.get("gt", True) else None
            return shutil.which(n)

        def sleep(s):
            c.append(["sleep", s])
            self.t += s

        live = f.get("live")

        def find_sessions(**kw):
            from claudeops import preview as _preview
            c.append(["scan", _preview.active()])
            if live == "raise":
                raise RuntimeError("tarama düştü")
            return [types.SimpleNamespace(name=n, sid=s) for n, s in (live or [])]

        def resolve(cwd, in_use=frozenset(), session_name=""):
            c.append(["resolve", cwd, sorted(in_use), session_name])
            return f.get("resume")

        import claudeops.tmux_backend as tb
        for name, v in (("tmux_available", avail), ("tmux_new_session_shell_fragment", frag),
                        ("tmux_attach_shell_fragment", attach), ("tmux_spawn_direct", direct),
                        ("tmux_has_session", has_session), ("find_sessions", find_sessions),
                        ("_ids_held_by_others", _ORIG_IDS_HELD)):
            self._set(spawn, name, v)
        for name, v in (("tmux_ghost_session", ghost), ("tmux_capture", capture), ("tmux_kill_session", kill)):
            self._set(tb, name, v)
        windows = list(f.get("windows") or [])

        def run(argv, env=None, timeout=None, encoding=None, errors=None, **kw):
            # `_window_titled`in `wmctrl -l`i: bayt çıktı, gerçek kodun verdiği `encoding`/`errors` ile çözülür.
            c.append(["window_list", list(argv), (env or {}).get("DISPLAY")])
            a = windows.pop(0) if windows else {"error": "oserror"}
            if a.get("error") == "oserror":
                raise FileNotFoundError(2, "No such file or directory")
            if a.get("error") == "timeout":
                raise subprocess.TimeoutExpired(argv, timeout)
            if a.get("error") == "value":
                raise ValueError("embedded null byte")
            out = bytes.fromhex(a.get("out") or "").decode(encoding or "ascii", errors or "strict")
            return subprocess.CompletedProcess(argv, a.get("rc", 0), stdout=out, stderr="")

        self._set(spawn, "subprocess", types.SimpleNamespace(
            Popen=Popen, DEVNULL=subprocess.DEVNULL, run=run, SubprocessError=subprocess.SubprocessError,
            TimeoutExpired=subprocess.TimeoutExpired))

        def count_fn(display):
            c.append(["desktop_count", display])
            v = f.get("desktop_count")
            if v == "raise":
                raise RuntimeError("wmctrl okunamadı")
            return v

        def send_fn(display, msg):
            c.append(["desktop_send", display, msg.decode("utf-8")])
            v = f.get("desktop_send", True)
            if v == "raise":
                raise RuntimeError("x" * 300)
            return v

        self._set(startup_desktop, "startup_env", lambda env, name: _ORIG_STARTUP_ENV(
            env, name, count_fn=count_fn, send_fn=send_fn))
        self._set(startup_desktop, "new_startup_id", lambda now=None: "SID")
        self._set(spawn, "threading", types.SimpleNamespace(Thread=Thread))
        self._set(spawn, "shutil", types.SimpleNamespace(which=which))
        self._set(spawn, "time", types.SimpleNamespace(monotonic=lambda: self.t, sleep=sleep))
        self._set(authz, "spawn_env", _ORIG_SPAWN_ENV)
        self._set(extensions, "session_mcp_spec", _ORIG_EXT_MCP)
        cli = (self.args_cli or "claude")
        self._set(providers.get_provider(cli), "resolve_resume_id", resolve)

        hook = f.get("hook")
        if hook is not None:
            def spawn_hook(principal, cli, name, cwd):
                c.append(["hook", cli, name, cwd])
                if "refuse" in hook:
                    raise authz.SpawnRefused(*hook["refuse"])
                if "raise" in hook:
                    raise RuntimeError(hook["raise"])
                return {k: v for k, v in hook.get("env") or []}
            authz.set_spawn_hook(spawn_hook)
        self.sess = dict(extensions._SESSION_MCP)
        self.mcp = dict(extensions._MCP)
        extensions._SESSION_MCP.clear()
        extensions._MCP.clear()
        for e in f.get("ext") or []:
            def pred(cwd, e=e):
                c.append(["pred", e["sid"], cwd])
                if e["cwd"] == "raise":
                    raise RuntimeError("koşul")
                return e["cwd"] == "*" or e["cwd"] == cwd
            extensions._SESSION_MCP[e["sid"]] = pred
            if e.get("tools") == "bozuk":
                extensions._MCP[e["sid"]] = {"tools": [{"yok": 1}]}
            elif e.get("tools") is not None:
                extensions._MCP[e["sid"]] = {"tools": [{"name": t} for t in e["tools"]]}
        return self

    def __exit__(self, *exc):
        authz.set_spawn_hook(None)
        extensions._SESSION_MCP.clear(); extensions._SESSION_MCP.update(self.sess)
        extensions._MCP.clear(); extensions._MCP.update(self.mcp)
        for obj, name, v, own in reversed(self.saved):
            if own:
                setattr(obj, name, v)
            else:
                delattr(obj, name)
        return False


def _g9_call(a, fn):
    g = _G9(a)
    g.args_cli = a.get("cli")
    with g:
        try:
            ret = fn()
        except Exception as e:      # noqa: BLE001
            kind = "refused" if isinstance(e, ValueError) else type(e).__name__
            return {"exc": [kind, str(e)], "calls": g.calls}
    return {"ret": ret, "calls": g.calls}


def op_g9_spawn(a):
    mcp = _spec(a["mcp"]) if a.get("mcp") else None
    return _g9_call(a, lambda: spawn.spawn_session(
        a["name"], a["cwd"], a.get("model", "m"), display=a.get("display"), permission_mode=a.get("perm", "auto"),
        effort=a.get("effort", "max"), force_new=bool(a.get("force_new")), prompt=a.get("prompt"),
        dry_run=bool(a.get("dry_run")), cli=a.get("cli", "claude"), mcp_server=mcp, hidden=bool(a.get("hidden")),
        cli_opts=a.get("cli_opts"), resume_id=a.get("resume_id")))


def op_g9_window(a):
    return _g9_call(a, lambda: spawn.open_window(a["name"], a["cwd"], display=a.get("display")))


def op_g9_mirror(a):
    return _g9_call(a, lambda: spawn.open_mirror_window(a["host"], a["name"], a["port"], display=a.get("display")))


def op_g9_reclaim(a):
    return _g9_call(a, lambda: spawn._reclaim_ghost_session(a["name"], a["cli"]))


def op_g9_sync(a):
    return routing.sync_global_files(a["codex"], a["agy"])


def op_g9_repo_dir(a):
    return paths.REPO_DIR


OPS.update({k[3:]: v for k, v in list(globals().items()) if k.startswith(("op_g8_", "op_g8x_", "op_g10_", "op_g9_"))})


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
