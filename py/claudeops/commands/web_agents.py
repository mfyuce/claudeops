"""`/api/agents/*` — ucli oturumlarının ALT AJAN açması (unified-cli `--allow-agents`, sahip isteği 2026-11-04).

Sözleşme (ucli istemcisiyle BİREBİR; hata her zaman `{ok:false, error}`):
  GET  /api/agents/models            -> {ok, models:[{id, service, efforts:[low|medium|high...]}]}
  POST /api/agents/start {model, effort, task, mode: read|edit}   -> {ok, name}
  POST /api/agents/send  {name, text}                              -> {ok}
  GET  /api/agents/status?name=      -> {ok, state: busy|idle|stopped, cost_usd, turns}
  GET  /api/agents/result?name=      -> {ok, state, answer}
  POST /api/agents/stop  {name}                                    -> {ok}

Kimlik (web.py `_agents_caller`): `Authorization: Bearer <ajan token'ı>` -> çağıran = o token'ın ÜST oturumu, yalnız kendi
çocuklarına dokunur; panel token'ı = insan (`start` için gövdede `parent` gerekir, öteki uçlar kayıtlı herhangi bir çocuğa).
Yalnız YEREL (`HOST_ROUTED_PATHS`'a eklenmez). Bu modül web.py'yi içe aktarmaz: filo eylemleri `ops` nesnesiyle enjekte edilir
(`sessions()`, `register()`, `forget()`, `name_taken()`, `start()`, `stop()`, `send()`), bu yüzden testte gerçek spawn/tmux yok.

Sınırlar: üst başına en çok 2 canlı çocuk, derinlik 1 (çocuk ajan açamaz, token almaz), çocuk başına USD tavanı
(`ucli_agents_max_cost_usd`, varsayılan 2), üst kapanınca çocuklar da kapanır (`parent_closed` + `reap`).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import ucli_agents as ag
from .. import ucli_client as uc
from ..diaglog import diag_log
from ..settings import byok_env_for, ucli_services

Caller = Tuple[str, str]        # ("human", "") | ("agent", <üst oturum adı>)
Reply = Tuple[Dict[str, Any], int]

_MODES = {"read": "read-only", "edit": "allow-edit"}
_EFFORT_CHOICES = ("low", "medium", "high")
_RECENT_INPUT_SECONDS = 4.0                 # girdi gönderdikten hemen sonra durum dosyası henüz "idle" diyebilir
_MAX_ANSWER_CHARS = 256 * 1024
_MISSES: Dict[str, int] = {}                # üst oturum -> art arda "çalışmıyor" gözlemi (reap geçici keşif hatasına dayanıklı)
_REAP_MISSES = 2


def _err(msg: str, status: int = 400) -> Reply:
    return {"ok": False, "error": msg}, status


# -- model kataloğu --------------------------------------------------------------------------------------------------

def _efforts_for(service: str, model: str) -> List[str]:
    from ..ucli_session_opts import effort_levels_for
    lv = effort_levels_for(service, model) if service != "evren" else None
    got = [x for x in (lv or []) if x in _EFFORT_CHOICES]
    from ..providers.ucli_provider import _EFFORT_LEVELS     # tek kaynak: ucli presetleri (`_EFFORT_LIMITS` anahtarları)
    return got or list(_EFFORT_LEVELS)


def models_catalog() -> List[Dict[str, Any]]:
    """ucli_provider kataloğu: Evren'in canlı sohbet modelleri + anahtarı girili hizmetlerin modelleri. effort yalnız
    low|medium|high. Anahtarsız hizmet listelenmez (başlatma zaten reddedilirdi)."""
    from ..providers import ucli_provider as up
    out: List[Dict[str, Any]] = []
    seen = set()
    keys = byok_env_for("ucli")
    for d in ucli_services():
        sid = d["id"]
        if sid == "evren":
            ids = list(up._live_models())
        elif (keys.get(d["env"]) or "").strip():
            ids = list(d.get("models") or [])
        else:
            continue
        for m in ids:
            if not m or m in seen:
                continue
            seen.add(m)
            out.append({"id": m, "service": sid, "efforts": _efforts_for(sid, m)})
    return out


# -- yardımcılar -----------------------------------------------------------------------------------------------------

def _running(ops) -> Dict[str, Any]:
    try:
        return {s.name: s for s in ops.sessions()}
    except Exception:
        return {}


def _history(cwd: str, name: str) -> List[Dict[str, str]]:
    try:
        return uc.read_chat_history(cwd, name) or []
    except Exception:
        return []


def _status_file(cwd: str, name: str) -> Optional[Dict[str, Any]]:
    try:
        return uc.read_status_file(cwd, name)
    except Exception:
        return None


def _last_answer(turns: List[Dict[str, Any]]) -> str:
    """Son kullanıcı turundan SONRAki son boş-olmayan asistan metni; yoksa "" (eski cevap yeni turun cevabı sanılmasın)."""
    for t in reversed(turns):
        role = t.get("role")
        if role == "assistant":
            text = t.get("text")
            if isinstance(text, str) and text.strip():
                return text[:_MAX_ANSWER_CHARS]
        elif role == "user":
            break
    return ""


def _cost_usd(name: str) -> float:
    """Çocuğun harcadığı USD (alt sınır): yalnız Claude/Anthropic hizmetinde `--usage-log` günlüğü var; öteki hizmetler 0."""
    try:
        from .. import review as rv
        from .. import ucli_cost
        return round(float(rv.usage_cost_usd(ucli_cost.log_path(name), "", write_mult=ucli_cost.write_mult())), 4)
    except Exception:
        return 0.0


def _state(name: str, rec: Dict[str, Any], running: Dict[str, Any], now: float) -> str:
    if not ag.is_live(rec, set(running), name, now):
        return "stopped"
    cwd = str(rec.get("cwd") or "")
    st = _status_file(cwd, name)
    turns = _history(cwd, name)
    if st is not None:
        from ..providers.ucli_provider import busy_from_status    # tek kaynak (live_busy ile aynı kural)
        busy = busy_from_status(st)
        if not busy and now - float(rec.get("last_input_at") or 0) < _RECENT_INPUT_SECONDS:
            busy = True
    else:       # durum dosyası yok (başlangıç ya da eski ikili): cevaplanmamış kullanıcı turu varsa meşgul
        busy = (not turns) or turns[-1].get("role") == "user" or name not in running
    return "busy" if busy else "idle"


def _child_for(name: Any, caller: Optional[Caller]) -> Tuple[Optional[Dict[str, Any]], Optional[Reply]]:
    if not isinstance(name, str) or not name.strip():
        return None, _err("name required")
    name = name.strip()
    rec = ag.get_child(name)
    if rec is None or (caller and caller[0] == "agent" and rec.get("parent") != caller[1]):
        return None, _err("unknown agent", 404)          # başkasının çocuğu varlığı da sızdırmaz
    return rec, None


# -- uç noktalar -----------------------------------------------------------------------------------------------------

def handle_get(path: str, query: Dict[str, List[str]], caller: Optional[Caller], ops) -> Reply:
    if not ag.enabled():
        return _err("agents are disabled (settings ucli_agents=off)", 403)
    if path == "/api/agents/models":
        return {"ok": True, "models": models_catalog()}, 200
    if path in ("/api/agents/status", "/api/agents/result"):
        name = (query.get("name") or [""])[0]
        rec, bad = _child_for(name, caller)
        if bad:
            return bad
        name = name.strip()
        running = _running(ops)
        state = _state(name, rec, running, time.time())
        if path == "/api/agents/status":
            st = _status_file(str(rec.get("cwd") or ""), name) or {}
            turns = st.get("turns")
            if not isinstance(turns, int) or isinstance(turns, bool):
                turns = sum(1 for t in _history(str(rec.get("cwd") or ""), name) if t.get("role") == "user")
            return {"ok": True, "state": state, "cost_usd": _cost_usd(name), "turns": turns}, 200
        return {"ok": True, "state": state, "answer": _last_answer(_history(str(rec.get("cwd") or ""), name))}, 200
    return _err("not found", 404)


def handle_post(path: str, data: Dict[str, Any], caller: Optional[Caller], ops) -> Reply:
    if not ag.enabled():
        return _err("agents are disabled (settings ucli_agents=off)", 403)
    if path == "/api/agents/start":
        return _start(data, caller, ops)
    if path == "/api/agents/send":
        rec, bad = _child_for(data.get("name"), caller)
        if bad:
            return bad
        name = str(data["name"]).strip()
        text = ag.fold_text(data.get("text"))
        if not text:
            return _err("text required")
        if _state(name, rec, _running(ops), time.time()) == "stopped":
            return _err("agent is stopped", 409)
        res = ops.send(name, text)
        if not res.get("ok"):
            return _err(str(res.get("error") or "send failed"), 502)
        ag.update_child(name, last_input_at=time.time())
        return {"ok": True}, 200
    if path == "/api/agents/stop":
        rec, bad = _child_for(data.get("name"), caller)
        if bad:
            return bad
        name = str(data["name"]).strip()
        if name in _running(ops):
            res = ops.stop(name)
            if not res.get("ok") and res.get("error") != "not_running":
                return _err(str(res.get("error") or "stop failed"), 502)
        ag.mark_stopped(name, "stopped_by_request")
        return {"ok": True}, 200
    return _err("not found", 404)


def _start(data: Dict[str, Any], caller: Optional[Caller], ops) -> Reply:
    model = str(data.get("model") or "").strip()
    effort = str(data.get("effort") or "").strip().lower() or "medium"
    mode = str(data.get("mode") or "").strip().lower()
    task = ag.fold_text(data.get("task"))
    if not model:
        return _err("model required")
    if mode not in _MODES:
        return _err("mode must be read or edit")
    if not task:
        return _err("task required")
    entry = next((m for m in models_catalog() if m["id"] == model), None)
    if entry is None:
        return _err(f"unknown model: {model}")
    if effort not in entry["efforts"]:
        return _err(f"effort {effort!r} not supported for {model} (use one of {', '.join(entry['efforts'])})")
    if caller and caller[0] == "agent":
        parent = caller[1]
    else:
        parent = str(data.get("parent") or "").strip()
        if not parent:
            return _err("parent required (panel token callers must name the parent ucli session)")
    if ag.is_child_name(parent):
        return _err("an agent cannot start agents (depth limit 1)", 403)
    running = _running(ops)
    psess = running.get(parent)
    if psess is None or getattr(psess, "cli", "") != "ucli":
        return _err("parent session is not running", 409)
    if mode == "edit" and getattr(psess, "permission_mode", None) != "allow-edit":
        return _err("mode edit requires a parent started with allow-edit", 403)
    cwd = str(getattr(psess, "cwd", "") or "")
    if not cwd:
        return _err("parent working directory unknown", 409)

    cap = ag.max_cost_usd()
    cli_opts: Dict[str, Any] = {"service": entry["service"]}
    if cap > 0:
        cli_opts["max_cost_usd"] = cap
    name, why = ag.reserve_child(parent, set(running), ops.name_taken,
                                 {"cwd": cwd, "model": model, "service": entry["service"], "effort": effort,
                                  "mode": mode, "max_cost_usd": cap})
    if name is None:
        return _err(why, 429)
    try:
        ops.register(name, cwd, model, _MODES[mode], effort)
        res = ops.start(name, model=model, permission_mode=_MODES[mode], effort=effort, cli_opts=cli_opts)
    except Exception as e:      # spawn beklenmedik şekilde patladı: ayrılan ad serbest kalsın
        res = {"ok": False, "error": f"start failed: {e.__class__.__name__}"}
    if not res.get("ok"):
        _discard(name, ops)
        return _err(str(res.get("error") or "start failed"), 502)
    ag.update_child(name, status="running", last_input_at=time.time())
    sent = ops.send(name, task)
    if not sent.get("ok"):
        try:
            ops.stop(name)
        except Exception:
            pass
        ag.mark_stopped(name, "task_not_delivered")
        return _err("agent started but the task could not be delivered", 502)
    diag_log("ucli_agent_started", name=name, parent=parent, model=model, mode=mode)
    return {"ok": True, "name": name}, 200


def _discard(name: str, ops) -> None:
    ag.mark_stopped(name, "start_failed")
    try:
        ops.forget(name)
    except Exception:
        pass


# -- yaşam döngüsü ---------------------------------------------------------------------------------------------------

def _stop_children(parent: str, ops, reason: str) -> List[str]:
    running = _running(ops)
    stopped: List[str] = []
    for name, rec in ag.children_of(parent).items():
        if rec.get("status") == "stopped":
            continue
        if name in running:
            try:
                ops.stop(name)
            except Exception as e:
                diag_log("ucli_agent_stop_failed", name=name, error=e.__class__.__name__)
                continue
        ag.mark_stopped(name, reason)
        stopped.append(name)
    return stopped


def parent_closed(name: str, ops) -> List[str]:
    """Üst oturum KAPATILDI (panel Durdur / kapat): çocuklarını tam adla durdur, token'ı geçersiz kıl. Asla fırlatmaz."""
    try:
        if ag.is_child_name(name):
            ag.mark_stopped(name, "stopped")
            return []
        stopped = _stop_children(name, ops, "parent_closed")
        ag.revoke_parent(name)
        _MISSES.pop(name, None)
        if stopped:
            diag_log("ucli_agents_parent_closed", parent=name, children=stopped)
        return stopped
    except Exception as e:
        diag_log("ucli_agents_parent_close_failed", parent=name, error=e.__class__.__name__)
        return []


def reap(ops) -> List[str]:
    """Periyodik süpürme: (1) çalışmayan (art arda `_REAP_MISSES` gözlem) üstün çocukları kapatılır; (2) süresi dolmuş "running"
    kaydı olan ama oturumu kaybolan çocuk "stopped" işaretlenir; (3) USD tavanını aşan çocuk durdurulur. Asla fırlatmaz."""
    closed: List[str] = []
    try:
        try:
            running = {s.name: s for s in ops.sessions()}
        except Exception:
            return closed           # keşif başarısız: "üst çalışmıyor" sanıp çocukları kapatma
        if not running and not ag.all_children():
            return closed
        now = time.time()
        by_parent: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for n, r in ag.all_children().items():
            if r.get("status") != "stopped":
                by_parent.setdefault(str(r.get("parent")), {})[n] = r
        for parent, kids in by_parent.items():
            if parent in running:
                _MISSES.pop(parent, None)
            else:
                _MISSES[parent] = _MISSES.get(parent, 0) + 1
                if _MISSES[parent] >= _REAP_MISSES:
                    closed += parent_closed(parent, ops)
                    continue
            for n, r in kids.items():
                if not ag.is_live(r, set(running), n, now):
                    ag.mark_stopped(n, "exited")
                    continue
                cap = float(r.get("max_cost_usd") or 0)
                if cap > 0 and _cost_usd(n) >= cap:
                    try:
                        ops.stop(n)
                    except Exception:
                        continue
                    ag.mark_stopped(n, "cost_cap")
                    diag_log("ucli_agent_cost_cap", name=n, cap=cap)
                    closed.append(n)
    except Exception as e:
        diag_log("ucli_agents_reap_failed", error=e.__class__.__name__)
    return closed


def start_reaper(ops, interval: float = 30.0) -> threading.Thread:
    """Arka plan süpürücüsü (daemon thread): `reap(ops)` her `interval` sn'de."""
    def loop() -> None:
        while True:
            time.sleep(interval)
            if ag.enabled():
                reap(ops)
    t = threading.Thread(target=loop, name="ucli-agents-reaper", daemon=True)
    t.start()
    return t
