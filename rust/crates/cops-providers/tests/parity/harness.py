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
import claudeops.diaglog as diaglog  # noqa: E402
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
    DIAGS.append([event, kw])


for _m in list(sys.modules.values()):
    if getattr(_m, "__name__", "").startswith("claudeops") and getattr(_m, "diag_log", None) is _ORIG_DIAG:
        _m.diag_log = _rec_diag
diaglog.diag_log = _rec_diag


def _fake_ensure_search_url(session_name=""):
    return FACTS.get("searxng_url")


def _fake_issue_token(session_name):
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
        "ucli_services": [{"id": d["id"], "wire": d["wire"], "endpoint": d["endpoint"], "env": d["env"],
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
