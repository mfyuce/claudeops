"""`py/cops mcp-steward` — değnekçinin beyni olan CLI oturumunun (varsayılan ad `degnekci`) filoyu
sürdüğü MCP stdio sunucusu. `mcp_queue.py` ile AYNI yerleşim: hiç kendi durumu yok, panelin zaten
çalışan `/api/steward/*` yüzeyine 127.0.0.1 üzerinden ince bir adaptör; JSON-RPC 2.0 elle
(`mcp` pip paketi YOK — requirements.txt sadece psutil+websockets).

Beyin bu araçlarla: filoya bakar, bir projenin bağlamını okur, oturuma sıradaki işi verir, boş iş
yapanı daha iyi direktifle yeniden açar, durdurur, sahibine soru açar, proje kaydını/fazını günceller,
fikirleri projeye çevirir. Araç çağırmadan verilen karar KAYDA GEÇMEZ (persona bunu da söyler).

Protokol döngüsü (`_handle`/`run_server`) `mcp_queue.py`'den paylaşılır — ikinci bir kopya yok.
"""
from __future__ import annotations
import os
import sys
from typing import Any, Callable, Dict, List

from ..paths import REPO_DIR
from ..providers.base import McpServerSpec
from ..steward import valid_steward_id
from . import mcp_queue

SERVER_NAME = "cops-steward"
DEFAULT_PORT = mcp_queue.DEFAULT_PORT


def default_spec(sid: str = "default") -> McpServerSpec:
    """`default`: argümansız komut satırı (eski beyin/eski config birebir aynı). Diğer kimlikler: `--steward <sid>`."""
    args = ("mcp-steward",) if sid == "default" else ("mcp-steward", "--steward", sid)
    return McpServerSpec(name=SERVER_NAME, command=os.path.join(REPO_DIR, "py", "cops"), args=args)


# Bu MCP sunucusunun kimliği (`--steward`, süreç başına BİR KEZ; `run_server` ayarlar). "default" = parametre EKLENMEZ
# (eski sunucu/eski beyin davranışı). Araç argümanlarından gelmez: beyin kimliğini değiştiremez.
_STEWARD = "default"


def _api(port: int, method: str, path: str, body: dict = None) -> dict:
    """`mcp_queue._api` + kimlik: default dışında GET'e `steward=` sorgusu, POST gövdesine `steward` (varsa EZİLİR)."""
    if _STEWARD != "default":
        if method == "GET":
            path += ("&" if "?" in path else "?") + "steward=" + _STEWARD
        else:
            body = dict(body or {}, steward=_STEWARD)
    return mcp_queue._api(port, method, path, body)


def _q(params: Dict[str, Any]) -> str:
    import urllib.parse
    return "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})


def _pick(args: dict, *keys: str) -> Dict[str, Any]:
    return {k: args[k] for k in keys if k in args and args[k] not in (None, "")}


# ── araç handler'ları: (port, arguments) → dict ──────────────────────────────

def _overview(port: int, args: dict) -> dict:
    return _api(port, "GET", "/api/steward/state")


def _context(port: int, args: dict) -> dict:
    name = str(args.get("name") or "")
    if not name:
        return {"ok": False, "error": "name is required"}
    return _api(port, "GET", "/api/steward/context" + _q({"name": name, "docs": "1" if args.get("docs") else ""}))


def _read_file(port: int, args: dict) -> dict:
    name, path = str(args.get("name") or ""), str(args.get("path") or "")
    if not name or not path:
        return {"ok": False, "error": "name and path are required"}
    return _api(port, "GET", "/api/steward/file" + _q({"name": name, "path": path, "max": args.get("max_chars")}))


def _directive(port: int, args: dict) -> dict:
    if not args.get("name") or not args.get("text"):
        return {"ok": False, "error": "name and text are required"}
    body = _pick(args, "name", "text", "model", "effort", "reason")
    body["start_if_stopped"] = bool(args.get("start_if_stopped", True))
    body["source"] = os.environ.get("COPS_NAME") or "brain"
    body["actor"] = "brain"   # observe kipinde uygulanmaz, `would:directive` olarak kaydedilir
    return _api(port, "POST", "/api/steward/directive", body)


def _restart(port: int, args: dict) -> dict:
    if not args.get("name") or not args.get("directive"):
        return {"ok": False, "error": "name and directive are required"}
    body = _pick(args, "name", "model", "effort", "reason")
    body["text"] = args["directive"]
    body["actor"] = "brain"
    return _api(port, "POST", "/api/steward/restart", body)


def _stop(port: int, args: dict) -> dict:
    if not args.get("name"):
        return {"ok": False, "error": "name is required"}
    return _api(port, "POST", "/api/steward/stop", dict(_pick(args, "name", "reason"), actor="brain"))


def _handover(port: int, args: dict) -> dict:
    if not args.get("name"):
        return {"ok": False, "error": "name is required"}
    return _api(port, "POST", "/api/steward/handover", dict(_pick(args, "name"), actor="brain"))


def _set_project(port: int, args: dict) -> dict:
    if not args.get("name"):
        return {"ok": False, "error": "name is required"}
    return _api(port, "POST", "/api/steward/project",
                dict(_pick(args, "name", "phase", "kind", "goal", "priority", "cadence_minutes", "notes", "model", "effort"),
                     actor="brain"))


def _register(port: int, args: dict) -> dict:
    if not args.get("name") or not args.get("cwd"):
        return {"ok": False, "error": "name and cwd are required"}
    body = _pick(args, "name", "cwd", "goal", "kind", "phase", "cli", "model", "priority", "cadence_minutes", "idea_id")
    if args.get("resources"):
        body["resources"] = args["resources"]
    return _api(port, "POST", "/api/steward/register", body)


def _ask(port: int, args: dict) -> dict:
    if not args.get("question"):
        return {"ok": False, "error": "question is required"}
    return _api(port, "POST", "/api/steward/ask",
                          {"project": args.get("project") or "", "text": args["question"],
                           "options": args.get("options") or [],
                           "source": os.environ.get("COPS_NAME") or "brain"})


def _answer(port: int, args: dict) -> dict:
    if not args.get("id") or not args.get("answer"):
        return {"ok": False, "error": "id and answer are required"}
    return _api(port, "POST", "/api/steward/answer", {"id": args["id"], "answer": args["answer"], "actor": "brain"})


def _note(port: int, args: dict) -> dict:
    if not args.get("project") or not args.get("text"):
        return {"ok": False, "error": "project and text are required"}
    return _api(port, "POST", "/api/steward/note", _pick(args, "project", "text"))


def _idea(port: int, args: dict) -> dict:
    if not args.get("text"):
        return {"ok": False, "error": "text is required"}
    return _api(port, "POST", "/api/steward/idea", {"text": args["text"], "source": os.environ.get("COPS_NAME") or "brain"})


def _idea_update(port: int, args: dict) -> dict:
    if not args.get("id") or not args.get("status"):
        return {"ok": False, "error": "id and status are required"}
    return _api(port, "POST", "/api/steward/idea", _pick(args, "id", "status", "project"))


def _questions(port: int, args: dict) -> dict:
    return _api(port, "GET", "/api/steward/questions" + _q({"status": args.get("status") or "open"}))


def _log(port: int, args: dict) -> dict:
    return _api(port, "GET", "/api/steward/log" + _q({"n": args.get("n") or 30}))


def _skip(port: int, args: dict) -> dict:
    if not args.get("name"):
        return {"ok": False, "error": "name is required"}
    return _api(port, "POST", "/api/steward/skip", _pick(args, "name", "reason"))


def _job_submit(port: int, args: dict) -> dict:
    if not args.get("project") or not args.get("kind"):
        return {"ok": False, "error": "project and kind are required"}
    body = _pick(args, "project", "kind", "params", "spec_text", "files", "priority", "approval_ref")
    body["actor"] = "brain"    # observe kipinde servise dokunulmaz, `would:job_submit` olarak kaydedilir
    return _api(port, "POST", "/api/steward/job/submit", body)


def _jobs(port: int, args: dict) -> dict:
    return _api(port, "GET", "/api/steward/jobs" + _q({
        "state": args.get("status") or "open", "project": args.get("project"), "id": args.get("id"),
        "refresh": "1" if args.get("refresh") else "", "kinds": "1" if args.get("kinds") else ""}))


def _obj(props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


_S = {"type": "string"}
_I = {"type": "integer"}
# Uzak proje notu (A5): araç imzaları DEĞİŞMEZ; host proje kaydından çözülür, çıktıda yalnız uzak projede `host` görünür.
_REMOTE = (" The project may live on a REMOTE host: its rows then carry a `host` field (local rows do not); the host is "
           "resolved from the project record, never pass one.")
_MODEL = {"type": "string", "description": "Only when (re)starting the session; ignored while it already runs."}
_EFFORT = {"type": "string", "description": "low|medium|high|max… per CLI; applied at (re)start only."}

TOOLS: List[Dict[str, Any]] = [
    {"name": "steward_overview",
     "description": "Fleet + steward projects (phase/priority/last directive/next_step from the project card) + open questions + new ideas + recent actions + the steward `mode` (in `observe` your directive/restart/stop/handover calls are recorded as would:<kind> but NOT applied; ask_user/idea/set_project still work). Call at the start of every tour." + _REMOTE,
     "inputSchema": _obj({}, [])},
    {"name": "steward_project_context",
     "description": "One project's steward record, last user/assistant exchange of its session, its project CARD (goal, phase guess, next step, open TBDs, blockers, recently done; refreshed by the engine) — or the heads of PLAN.md/TODO.md/TOBEDECIDED.md/GOAL.md when there is no card yet (docs=true gives both) — short git status, its open questions." + _REMOTE + " On a remote project the exchange and document heads are read over the host and the git status is `remote: bilinmiyor` (unknown).",
     "inputSchema": _obj({"name": _S, "docs": {"type": "boolean", "description": "Also include the raw document heads next to the card."}}, ["name"])},
    {"name": "steward_read_file",
     "description": "Read a file inside the project folder (read-only, path relative to the project root)." + _REMOTE,
     "inputSchema": _obj({"name": _S, "path": _S, "max_chars": _I}, ["name", "path"])},
    {"name": "steward_directive",
     "description": "Send the next task to a project session (starts it if stopped, same conversation). The text is wrapped with the project's goal/notes and the steward protocol tail." + _REMOTE,
     "inputSchema": _obj({"name": _S, "text": _S, "model": _MODEL, "effort": _EFFORT, "reason": _S,
                          "start_if_stopped": {"type": "boolean", "default": True}}, ["name", "text"])},
    {"name": "steward_restart",
     "description": "Stop the session (idle/wrong work/needs another model) and reopen it with the same conversation plus a new, narrower directive.",
     "inputSchema": _obj({"name": _S, "directive": _S, "reason": _S, "model": _MODEL, "effort": _EFFORT}, ["name", "directive", "reason"])},
    {"name": "steward_stop",
     "description": "Stop a session for now (project stays registered; slot freed).",
     "inputSchema": _obj({"name": _S, "reason": _S}, ["name", "reason"])},
    {"name": "steward_handover",
     "description": "Send the wrap-up (handover) message to a session whose context looks exhausted. The engine already does this on its own at the scrollback threshold.",
     "inputSchema": _obj({"name": _S}, ["name"])},
    {"name": "steward_set_project",
     "description": "Update an EXISTING project's steward record (a new name is refused: use steward_register_project): phase (idea|planning|planned|paused|done), kind (book|article|software|other), goal, priority 1-5, cadence_minutes (0 = manual only), notes, model, effort.",
     "inputSchema": _obj({"name": _S, "phase": _S, "kind": _S, "goal": _S, "priority": _I, "cadence_minutes": _I,
                          "notes": _S, "model": _S, "effort": _S}, ["name"])},
    {"name": "steward_register_project",
     "description": "Create+register a new project: folder (created + git init if missing), GOAL.md with goal and resources (local files are copied into kaynaklar/, URLs listed), roster entry, steward record (default phase planning).",
     "inputSchema": _obj({"name": _S, "cwd": _S, "goal": _S, "kind": _S, "phase": _S, "cli": _S, "model": _S,
                          "priority": _I, "cadence_minutes": _I, "idea_id": _S,
                          "resources": {"type": "array", "items": _S}}, ["name", "cwd", "goal"])},
    {"name": "steward_ask_user",
     "description": "Ask the owner a question (one sentence, easy to answer). Give `options` whenever the answer can be a pick (yes/no, A/B/C, 'later'): up to 6 short strings, answered with one tap on the phone page. Pushes a phone notification if ntfy is set up; the engine delivers the answer to the project's session.",
     "inputSchema": _obj({"project": _S, "question": _S,
                          "options": {"type": "array", "items": _S, "description": "Up to 6 short choices; omit for a free-text question."}},
                         ["question"])},
    {"name": "steward_answer",
     "description": "Answer a ROUTINE QUESTION (a project session's process question: when to reopen, which order, which model, with the handover note?) yourself; the engine delivers the answer to the session. Never use it for owner decisions (copyright, spending, commit/push): those stay with the owner.",
     "inputSchema": _obj({"id": _S, "answer": _S}, ["id", "answer"])},
    {"name": "steward_note",
     "description": "Your own note on a project (replaces the previous one; included in the next directive).",
     "inputSchema": _obj({"project": _S, "text": _S}, ["project", "text"])},
    {"name": "steward_idea",
     "description": "Record a new idea in the inbox.",
     "inputSchema": _obj({"text": _S}, ["text"])},
    {"name": "steward_idea_update",
     "description": "Triage an idea: status project|later|dropped (+ project name when it became one).",
     "inputSchema": _obj({"id": _S, "status": _S, "project": _S}, ["id", "status"])},
    {"name": "steward_questions",
     "description": "List questions (status open|answered|all).",
     "inputSchema": _obj({"status": _S}, [])},
    {"name": "steward_log",
     "description": "Recent steward events (what the engine/you did and why).",
     "inputSchema": _obj({"n": _I}, [])},
    {"name": "steward_job_submit",
     "description": "Queue a job in the shared service's job queue (varaka: import/embed/regression work) on behalf of ONE OF YOUR OWN projects. `kind` is a queue job kind (see steward_jobs kinds=true), `params` its parameters, `spec_text` an optional request text, `files` optional local file paths INSIDE that project's folder (uploaded multipart; paths outside the folder are refused). The idempotency key is automatic: the same request returns the same job. A job that needs approval comes back `awaiting_approval`: only a HUMAN admin can approve it in varaka, NEVER try to approve/reject it yourself; tell the owner (the engine also pushes a phone notification and tells the project session). The result is delivered to the project session by the engine when the job finishes; you do not need to poll. In observe mode nothing is sent (recorded as would:job_submit).",
     "inputSchema": _obj({"project": _S, "kind": _S, "params": {"type": "object"}, "spec_text": _S,
                          "files": {"type": "array", "items": _S}, "priority": _I, "approval_ref": _S}, ["project", "kind"])},
    {"name": "steward_jobs",
     "description": "Your queued jobs (local record of what you submitted): state, result summary, error, artifacts. `status`: open (default) | all | queued | running | awaiting_approval | done | failed | cancelled. `refresh=true` polls the queue right now; `kinds=true` returns the queue's job kind catalogue instead. Read-only.",
     "inputSchema": _obj({"status": _S, "project": _S, "id": _S, "refresh": {"type": "boolean"}, "kinds": {"type": "boolean"}}, [])},
    {"name": "steward_skip",
     "description": "Explicitly leave a listed item alone this tour (recorded; defers the next idle check).",
     "inputSchema": _obj({"name": _S, "reason": _S}, ["name", "reason"])},
]

DISPATCH: Dict[str, Callable[[int, dict], dict]] = {
    "steward_overview": _overview,
    "steward_project_context": _context,
    "steward_read_file": _read_file,
    "steward_directive": _directive,
    "steward_restart": _restart,
    "steward_stop": _stop,
    "steward_handover": _handover,
    "steward_set_project": _set_project,
    "steward_register_project": _register,
    "steward_ask_user": _ask,
    "steward_answer": _answer,
    "steward_note": _note,
    "steward_idea": _idea,
    "steward_idea_update": _idea_update,
    "steward_questions": _questions,
    "steward_log": _log,
    "steward_skip": _skip,
    "steward_job_submit": _job_submit,
    "steward_jobs": _jobs,
}


def run_server(port: int, steward: str = "default") -> None:
    global _STEWARD
    _STEWARD = steward or "default"
    mcp_queue.run_server(port, tools=TOOLS, dispatch=DISPATCH, server_name=SERVER_NAME)


def register(sub) -> None:
    p = sub.add_parser("mcp-steward", help="MCP stdio server: değnekçi beyninin filoyu sürdüğü araçlar (/api/steward/* adaptörü)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"claudeops web panel's port (default {DEFAULT_PORT}) — must match the running `py/cops web [--port]`")
    p.add_argument("--steward", default="default",
                   help="değnekçi kimliği (varsayılan default); her API çağrısına bu sunucu ekler, beyin değiştiremez")
    p.set_defaults(func=run)


def run(args) -> int:
    sid = getattr(args, "steward", "default") or "default"
    if not valid_steward_id(sid):
        print(f"geçersiz değnekçi kimliği: {sid!r}", file=sys.stderr)
        return 2
    run_server(args.port, sid)
    return 0
