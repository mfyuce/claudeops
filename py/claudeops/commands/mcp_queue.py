"""`py/cops mcp-queue` — TOBEDECIDED#15 Phase 3: MCP server adapter.

Onaylanmış plan (`~/.claude/plans/idempotent-riding-key.md`, "MCP server (phase
3)"): stdio transport, HİÇ kendi durumu yok — panelin zaten çalışan `/api/orch/*`
(+ `/v1/models`) yüzeyine 127.0.0.1 üzerinden ince bir adaptör. Hand-rolled
JSON-RPC 2.0/stdio (resmi `mcp` pip paketi YOK): bu repo'da web-framework
bağımlılığı yok (requirements.txt sadece psutil+websockets) — SDK'nın stdio
transport'u bile starlette/uvicorn'u kullanılmadan sürükler, oysa gereken
protokol yüzeyi (initialize/tools-list/tools-call/ping) elle yazılamayacak
kadar büyük değil.

Panelin kendisi asıl koordinatör olmaya devam ediyor (bkz. plan'ın "key
architectural insight"i) — bu sadece bir CLI session'ının (insan değil) aynı
`/api/orch/*` işlevlerini kendi tool-call'larıyla sürebilmesi için.
"""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from ..paths import CLAUDEOPS_DIR, REPO_DIR
from ..providers.base import McpServerSpec

TOKEN_FILE = os.path.join(CLAUDEOPS_DIR, "web.token")
DEFAULT_PORT = 8765
PROTOCOL_VERSION_FALLBACK = "2025-06-18"
SERVER_NAME = "cops-queue"

WAIT_POLL_SECONDS = 1.0
WAIT_DEFAULT_TIMEOUT_SECONDS = 60.0
# `cops_run_wait`'in üst sınırı — sonsuz/aşırı-uzun bir long-poll bir MCP
# tool-call'unu istemci tarafında asılı bırakabilir, çağıran gerekirse tekrar
# çağırıp devam eder (bounded long-poll, plan'ın kendi tabiriyle).
WAIT_MAX_TIMEOUT_SECONDS = 600.0

# Terminal (>=terminal) bir run durumu — `cops_run_wait` bunlardan birine
# ulaşınca döner, `orchestration.Run.status`'un olası değerleri (bkz.
# `orchestration.py`'nin kendi dataclass docstring'i).
_TERMINAL_STATUSES = frozenset({"done", "needs_human", "failed", "cancelled"})


def default_spec() -> McpServerSpec:
    """`py/cops mcp-queue`'yu KENDİSİ çağıran standart spec — `py/cops` wrapper'ının
    mutlak yolu (`REPO_DIR/py/cops`, script zaten `cd $(dirname $0) && exec python3
    -m claudeops "$@"`), python3/modül-yolu çözümlemesini burada TEKRARLAMAZ."""
    return McpServerSpec(name=SERVER_NAME, command=os.path.join(REPO_DIR, "py", "cops"), args=("mcp-queue",))


def _log(msg: str) -> None:
    # MCP stdio kuralı: stdout'a protokol DIŞI tek bir bayt bile yazılamaz —
    # istemci onu bir JSON-RPC mesajı sanıp parse etmeye çalışır. Her şey stderr'e.
    print(msg, file=sys.stderr, flush=True)


class ApiError(Exception):
    pass


def _read_token() -> str:
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            token = f.read().strip()
    except OSError as e:
        raise ApiError(f"cannot read {TOKEN_FILE}: {e} — is `py/cops web` running at least once?")
    if not token:
        raise ApiError(f"{TOKEN_FILE} is empty")
    return token


def _api(port: int, method: str, path: str, body: Optional[dict] = None) -> dict:
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": f"Bearer {_read_token()}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ApiError(f"HTTP {e.code} from claudeops panel: {e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e:
        raise ApiError(f"cannot reach claudeops panel on 127.0.0.1:{port} ({e.reason}) — is `py/cops web` running?")
    except (TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ApiError(f"bad response from claudeops panel: {e}")


def _run_query(run_id: str) -> str:
    return "/api/orch/run?id=" + urllib.parse.quote(run_id, safe="")


# ── tool handler'ları — her biri (port, arguments) alır, sonuç dict'i döner ──

def _tool_cops_sessions(port: int, args: dict) -> dict:
    result = _api(port, "GET", "/v1/models")
    names = [m["id"] for m in result.get("data", []) if isinstance(m, dict) and "id" in m]
    return {"ok": True, "sessions": names}


def _tool_cops_run_start(port: int, args: dict) -> dict:
    body: Dict[str, Any] = {
        "participants": args.get("participants") or [],
        "task": args.get("task") or "",
        "verdict_hint": args.get("verdict_hint") or "",
    }
    if args.get("worker_timeout") is not None:
        body["worker_timeout"] = args["worker_timeout"]
    return _api(port, "POST", "/api/orch/start", body)


def _tool_cops_run_status(port: int, args: dict) -> dict:
    run_id = str(args.get("run_id") or "")
    if not run_id:
        return {"ok": False, "error": "run_id is required"}
    return _api(port, "GET", _run_query(run_id))


def _tool_cops_run_results(port: int, args: dict) -> dict:
    run_id = str(args.get("run_id") or "")
    if not run_id:
        return {"ok": False, "error": "run_id is required"}
    result = _api(port, "GET", _run_query(run_id))
    if not result.get("ok"):
        return result
    results = (result.get("run") or {}).get("results", [])
    kind = args.get("kind")
    role = args.get("role")
    if kind:
        results = [r for r in results if r.get("kind") == kind]
    if role:
        results = [r for r in results if r.get("role") == role]
    return {"ok": True, "results": results}


def _tool_cops_run_wait(port: int, args: dict) -> dict:
    run_id = str(args.get("run_id") or "")
    if not run_id:
        return {"ok": False, "error": "run_id is required"}
    try:
        timeout = float(args.get("timeout") or WAIT_DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        timeout = WAIT_DEFAULT_TIMEOUT_SECONDS
    timeout = max(0.0, min(timeout, WAIT_MAX_TIMEOUT_SECONDS))
    deadline = time.monotonic() + timeout
    last: Optional[dict] = None
    while True:
        result = _api(port, "GET", _run_query(run_id))
        if not result.get("ok"):
            return result
        last = result
        if (result.get("run") or {}).get("status") in _TERMINAL_STATUSES:
            return result
        if time.monotonic() >= deadline:
            return last
        time.sleep(WAIT_POLL_SECONDS)


def _tool_cops_result_push(port: int, args: dict) -> dict:
    run_id = str(args.get("run_id") or "")
    verdict = str(args.get("verdict") or "")
    if not run_id or not verdict:
        return {"ok": False, "error": "run_id and verdict are required"}
    # Kendi isminizi genelde belirtmenize gerek yok: spawn'ın env_overrides()'ı
    # HER üç CLI'da da COPS_NAME'i set ediyor (bkz. providers/*.py), MCP
    # server'ı çağıran CLI'nın kendi çocuk-process env'i bunu miras alır —
    # varsayım budur, doğrulaması build-order'ın 4. adımında.
    name = str(args.get("name") or os.environ.get("COPS_NAME") or "")
    if not name:
        return {"ok": False, "error": "name is required (and $COPS_NAME isn't set in this process's env)"}
    body = {"run_id": run_id, "name": name, "verdict": verdict, "text": str(args.get("text") or "")}
    return _api(port, "POST", "/api/orch/result", body)


def _tool_cops_run_cancel(port: int, args: dict) -> dict:
    run_id = str(args.get("run_id") or "")
    if not run_id:
        return {"ok": False, "error": "run_id is required"}
    return _api(port, "POST", "/api/orch/cancel", {"run_id": run_id})


TOOLS: List[Dict[str, Any]] = [
    {
        "name": "cops_sessions",
        "description": "List claudeops fleet sessions addressable as orchestration participants "
                        "(mirrors GET /v1/models).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "cops_run_start",
        "description": "Start a new orchestration run: dispatch a task to worker sessions (optionally with a "
                        "controller for briefing and/or a decider for the final verdict). Returns immediately "
                        "with a run_id — never blocks until the run finishes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "participants": {
                    "type": "array",
                    "description": "Each: {host:'local', name:<addressable session name>, role:'worker'|'controller'|'decider'}.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "host": {"type": "string", "default": "local"},
                            "name": {"type": "string"},
                            "role": {"type": "string", "enum": ["worker", "controller", "decider"]},
                        },
                        "required": ["name", "role"],
                    },
                },
                "task": {"type": "string", "description": "Task text sent to workers (or to the controller, if any, for briefing)."},
                "verdict_hint": {"type": "string", "description": "Optional hint about the expected verdict shape, e.g. 'answer yes or no'."},
                "worker_timeout": {"type": "number", "description": "Seconds to wait per worker before recording a timeout (default 900)."},
            },
            "required": ["participants", "task"],
        },
    },
    {
        "name": "cops_run_status",
        "description": "Get the current full record (status, participants, results so far, outcome if done) of a run by id.",
        "inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}},
                         "required": ["run_id"], "additionalProperties": False},
    },
    {
        "name": "cops_run_results",
        "description": "Peek at a run's results, optionally filtered by kind (brief|worker_result|decision|final) "
                        "or role (worker|controller|decider). Non-destructive — nothing is consumed/removed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "kind": {"type": "string", "enum": ["brief", "worker_result", "decision", "final"]},
                "role": {"type": "string", "enum": ["worker", "controller", "decider"]},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "cops_run_wait",
        "description": "Bounded long-poll: block until the run reaches a terminal status "
                        "(done/needs_human/failed/cancelled) or the timeout elapses, then return its current record.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "timeout": {"type": "number",
                            "description": f"Max seconds to wait (default {WAIT_DEFAULT_TIMEOUT_SECONDS:.0f}, "
                                            f"capped at {WAIT_MAX_TIMEOUT_SECONDS:.0f})."},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "cops_result_push",
        "description": "Submit YOUR OWN structured result for a run directly, instead of relying on the engine "
                        "reading your visible reply back for the COPS-VERDICT/COPS-END tail. Authoritative when "
                        "present. Only accepted while the engine is actively waiting on your turn for this run "
                        "(already answered/timed-out turns refuse a late push).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "name": {"type": "string", "description": "Your own session name — defaults to $COPS_NAME if omitted."},
                "verdict": {"type": "string", "description": "Short verdict, max 200 chars — same contract as the COPS-VERDICT tail."},
                "text": {"type": "string", "description": "Optional fuller free-text answer."},
            },
            "required": ["run_id", "verdict"],
        },
    },
    {
        "name": "cops_run_cancel",
        "description": "Cancel an active run. Cannot un-send messages already delivered to participants — only stops further waiting.",
        "inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}},
                         "required": ["run_id"], "additionalProperties": False},
    },
]

DISPATCH: Dict[str, Callable[[int, dict], dict]] = {
    "cops_sessions": _tool_cops_sessions,
    "cops_run_start": _tool_cops_run_start,
    "cops_run_status": _tool_cops_run_status,
    "cops_run_results": _tool_cops_run_results,
    "cops_run_wait": _tool_cops_run_wait,
    "cops_result_push": _tool_cops_result_push,
    "cops_run_cancel": _tool_cops_run_cancel,
}


def _send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _handle(port: int, msg: dict) -> Optional[dict]:
    """Bir JSON-RPC mesajını işler. İSTEK (id'li) ise yanıt dict'i döner;
    NOTIFICATION (id'siz) ise None döner — JSON-RPC 2.0'da notification'a
    yanıt YAZILMAZ."""
    msg_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION_FALLBACK,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
        }}
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = DISPATCH.get(name)
        if handler is None:
            return {"jsonrpc": "2.0", "id": msg_id,
                     "result": {"content": [{"type": "text", "text": f"unknown tool: {name!r}"}], "isError": True}}
        try:
            result = handler(port, args)
        except ApiError as e:
            return {"jsonrpc": "2.0", "id": msg_id,
                     "result": {"content": [{"type": "text", "text": str(e)}], "isError": True}}
        except Exception as e:  # bu servis TEK bir çağrı yüzünden çökemez — her tur bağımsız
            _log(f"tool_call_crashed name={name} error={e!r}")
            return {"jsonrpc": "2.0", "id": msg_id,
                     "result": {"content": [{"type": "text", "text": f"internal error: {e}"}], "isError": True}}
        return {"jsonrpc": "2.0", "id": msg_id,
                 "result": {"content": [{"type": "text", "text": json.dumps(result)}],
                            "isError": not result.get("ok", True)}}
    if msg_id is None:
        return None  # bilinmeyen bir notification — sessizce yok say, protokolü bozma
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}


def run_server(port: int) -> None:
    _log(f"cops-mcp-queue starting (pid={os.getpid()}), backing panel at 127.0.0.1:{port}")
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            _log(f"bad JSON-RPC line, skipped: {e}")
            continue
        try:
            reply = _handle(port, msg)
        except Exception as e:  # protokol döngüsü TEK bozuk mesaj yüzünden ölemez
            _log(f"handler crashed: {e!r}")
            reply = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": str(e)}}
        if reply is not None:
            _send(reply)
    _log("stdin closed, exiting")


def register(sub) -> None:
    p = sub.add_parser("mcp-queue", help="MCP stdio server adapter over the local orchestration API (TOBEDECIDED#15 Phase 3)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"claudeops web panel's port (default {DEFAULT_PORT}) — must match the running `py/cops web [--port]`")
    p.set_defaults(func=run)


def run(args) -> int:
    run_server(args.port)
    return 0
