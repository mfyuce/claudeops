"""Değnekçi motoru — `steward.plan_tick`'in kararlarını CANLI filoya uygular; `py/cops web`
içinde bir daemon thread olarak döner (`start_loop`), `/api/steward/*` uçlarını sunar.

`web_orch.py` ile AYNI yerleşim: `web.py` bizi import eder, biz onu ETMEYİZ (döngüsel import).
Oturum başlat/durdur/handover/kayıt gibi işler `web.py`'nin kendi fonksiyonlarıdır (guard_lock,
`_wait_stable`, instance kaydı, TSV yazımı hep orada) — `configure()` ile callback olarak alınır,
burada yeniden yazılmaz. `if cli == ...` YOK: provider arayüzü.

Döngü tek bir tick'te ASLA ölmez: her tick try/except + diag_log; bir eylem patlarsa kalanlar yine
uygulanır. Her eylem `steward/log.jsonl`'a düşer (ne yapıldı, neden) — kullanıcı "değnekçi ne yaptı"
sorusunu `py/cops steward log` ile görür.
"""
from __future__ import annotations
import dataclasses
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import psutil

from .. import instances as inst_mod
from .. import steward as sw
from ..diaglog import diag_log
from ..discovery import find_sessions
from ..guard import guard_lock
from ..hosts import LOCAL_HOST_NAME
from ..paths import CLAUDEOPS_DIR
from ..providers import PROVIDERS, DEFAULT_CLI, get_provider
from ..providers.base import McpServerSpec, OneshotError
from ..settings import default_effort_for, default_model_for, load_settings, steward_config
from ..spawn import spawn_session, detect_display
from ..stuck import find_stuck
from ..tmux_backend import is_tmux_backed, strip_ansi, tmux_capture, tmux_has_session, tmux_send_keys
from ..turns import is_busy_now
from . import web_ws

NTFY_TOPIC_FILE = os.path.join(CLAUDEOPS_DIR, "ntfy_topic.txt")
TUNNEL_URL_FILE = os.path.join(CLAUDEOPS_DIR, "tunnel_url.txt")
MAX_FORM_BYTES = 16 * 1024
GUARD_LOCK_ACQUIRE_TIMEOUT = 60.0
READY_TIMEOUT_SECONDS = 60.0
READY_MIN_SECONDS = 6.0
DOC_HEAD_CHARS = 1500
DOCS = ("PLAN.md", "TODO.md", "TOBEDECIDED.md", "GOAL.md")
MAX_RESOURCE_BYTES = 50 * 1024 * 1024
MAX_FILE_READ_CHARS = 20000
RECENT_ACTIONS = 12

_LOCK = threading.Lock()          # tick'ler ve elle tetiklenen eylemler sıralı
_ACTIONS: Dict[str, Callable[..., Any]] = {}
_RECENT: List[Dict[str, Any]] = []
_LAST_TICK: Dict[str, Any] = {"at": 0.0, "trigger": "", "actions": 0, "dry": 0, "error": ""}
_loop_started = False
_CARD_LOCK = threading.Lock()      # aynı anda tek kart yenileme işi (tick'in arka plan işi / elle tetiklenen)
_CARD_BACKGROUND = True            # testler False yapıp işi satır içi koşturur
CARD_TIMEOUT_SECONDS = 120.0


def configure(**callbacks: Callable[..., Any]) -> None:
    """`web.py` `run()`'da verir: status_payload(), fleet_status(), start(name, model, effort, fresh, lang),
    stop(name, lang), handover(name, lang), register_project(name, cwd, model, cli, lang)."""
    _ACTIONS.update(callbacks)


def _act(name: str, *args: Any, **kw: Any) -> Any:
    fn = _ACTIONS.get(name)
    if fn is None:
        return {"ok": False, "error": f"steward engine not configured ({name})"}
    return fn(*args, **kw)


def _remember(action: sw.Action, result: Any) -> None:
    entry = {"ts": time.time(), "kind": action.kind, "name": action.name, "reason": action.reason,
             "ok": bool(result.get("ok")) if isinstance(result, dict) else bool(result),
             "detail": (result.get("error") or result.get("detail") or "") if isinstance(result, dict) else ""}
    _RECENT.insert(0, entry)
    del _RECENT[RECENT_ACTIONS:]
    sw.log_event("action", kind=action.kind, name=action.name, reason=action.reason,
                 ok=entry["ok"], detail=entry["detail"])


def _remember_dry(action: sw.Action) -> None:
    """observe kipi: eylem UYGULANMADI. `_RECENT`e `dry=True` ile, log'a `would:<kind>` olayı olarak yazılır."""
    detail = f"{len(action.payload.get('items') or [])} madde" if action.kind == "tour" else str(action.payload.get("text") or "")[:200]
    _RECENT.insert(0, {"ts": time.time(), "kind": action.kind, "name": action.name, "reason": action.reason,
                       "ok": True, "dry": True, "detail": detail})
    del _RECENT[RECENT_ACTIONS:]
    extra = {"question_id": action.payload["question_id"]} if action.payload.get("question_id") else {}
    sw.log_event("would:" + action.kind, name=action.name, reason=action.reason, detail=detail, **extra)


def _brain_dry(kind: str, data: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """observe kipinde BEYNİN (`actor: brain`, MCP aracı) oturuma dokunan çağrıları da uygulanmaz: aynı `would:`
    kaydı düşer, beyne başarılı-ama-kuru yanıt döner. İnsanın elle çağırdığı CLI/API (`actor` yok) her zaman uygulanır."""
    if data.get("actor") != "brain" or steward_config().mode != "observe":
        return None
    _remember_dry(sw.Action(kind, name, "brain: " + str(data.get("reason") or "")[:200], {"text": str(data.get("text") or "")}))
    return {"ok": True, "dry": True, "note": f"observe mode: recorded as would:{kind}, not applied"}


# ── telefon bildirimi (ntfy) ──────────────────────────────────────────────────

def notify_phone(text: str, click: str = "", title: str = "claudeops degnekci") -> bool:
    """`py/cops service notify` ile kurulmuş ntfy topic'i varsa oraya POST (arka planda, best-effort).
    Yoksa False — soru yine de `questions.json`'da bekler, panel/CLI'dan görülür. `click`: bildirime dokununca
    açılacak adres (ntfy `Click` başlığı; soru sayfası `/q/<id>?k=`)."""
    try:
        with open(NTFY_TOPIC_FILE, encoding="utf-8") as f:
            topic = f.read().strip()
    except OSError:
        return False
    if not topic:
        return False

    def _post() -> None:
        try:
            headers = {"Title": title}
            if click:
                headers["Click"] = click
            req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=text.encode("utf-8"),
                                         headers=headers, method="POST")
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:
            diag_log("steward_notify_failed", error=str(e))

    threading.Thread(target=_post, daemon=True, name="steward-ntfy").start()
    return True


def public_base() -> str:
    """Telefondan ulaşılabilen panel adresi: `tunnel_url.txt` (quick tunnel her restart'ta yeni URL yazar) ya da "".
    Soru bağlantısı panel token'ını DEĞİL sorunun kendi anahtarını taşır (`steward.question_link`)."""
    try:
        with open(TUNNEL_URL_FILE, encoding="utf-8") as f:
            url = f.read().strip()
    except OSError:
        return ""
    return url if url.startswith("http") else ""


# ── proje klasörü yardımcıları ────────────────────────────────────────────────

def _project_cwd(name: str) -> str:
    fleet = _act("fleet_status") or {}
    info = fleet.get(name) if isinstance(fleet, dict) else None
    if info and info.get("cwd"):
        return info["cwd"]
    rec = inst_mod.get_instance(name)
    if rec and rec.get("cwd"):
        return rec["cwd"]
    for s in find_sessions(measure_cpu=False):
        if s.name == name and s.cwd:
            return s.cwd
    return ""


def _project_cli(name: str) -> str:
    fleet = _act("fleet_status") or {}
    info = fleet.get(name) if isinstance(fleet, dict) else None
    if info and info.get("cli") in PROVIDERS:
        return info["cli"]
    rec = inst_mod.get_instance(name)
    if rec and rec.get("cli") in PROVIDERS:
        return rec["cli"]
    return DEFAULT_CLI


def _read_head(cwd: str, rel: str, max_chars: int = DOC_HEAD_CHARS) -> str:
    try:
        with open(os.path.join(cwd, rel), encoding="utf-8", errors="replace") as f:
            return f.read(max_chars + 1)[:max_chars]
    except OSError:
        return ""


def _git_short(cwd: str) -> str:
    if not cwd or not os.path.isdir(os.path.join(cwd, ".git")):
        return ""
    try:
        r = subprocess.run(["git", "-C", cwd, "status", "--short", "--branch"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().splitlines()
        return "\n".join(lines[:20])
    except Exception:
        return ""


def _safe_project_file(cwd: str, rel: str) -> Optional[str]:
    """Proje klasörü içinde kalan, mutlak hale getirilmiş yol — dışarı çıkıyorsa None (`files.py` ilkesi)."""
    if not cwd or not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return None
    root = os.path.realpath(cwd)
    full = os.path.realpath(os.path.join(root, rel))
    if full != root and not full.startswith(root + os.sep):
        return None
    return full


# ── görünümler ────────────────────────────────────────────────────────────────

def context_tokens_for(cwd: str, sid: Optional[str]) -> Optional[int]:
    """Claude transkriptinin SON asistan turunun bağlam boyutu: girdi + cache okuma + cache yazma token'ı (her
    turda yeniden okunan bağlamın boyutu). Dosyanın yalnız sonundan okur (~256 KB); bulunamazsa None."""
    from ..providers.claude_provider import jsonl_path_for
    path = jsonl_path_for(cwd, sid)
    if not path or not os.path.isfile(path):
        return None
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - 262144))
        tail = f.read().decode("utf-8", "replace")
    for line in reversed(tail.splitlines()):
        if '"usage"' not in line or '"assistant"' not in line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        m = o.get("message") or {}
        u = m.get("usage") if m.get("role") == "assistant" else None
        if u:
            return int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0))
    return None


def _collect_views(cfg: sw.Config) -> List[sw.SessionView]:
    payload = _act("status_payload") or {}
    rows = [r for r in (payload.get("sessions") or []) if r.get("host", LOCAL_HOST_NAME) == LOCAL_HOST_NAME]
    live = {s.name: s for s in find_sessions(measure_cpu=False)}
    stuck_names = set()
    try:
        stuck_names = {i.session.name for i in find_stuck(list(live.values()))}
    except Exception:
        pass
    views: List[sw.SessionView] = []
    for r in rows:
        name = r.get("name") or ""
        s = live.get(name)
        v = sw.SessionView(
            name=name, running=bool(r.get("running")), cwd=r.get("cwd") or "", cli=r.get("cli") or DEFAULT_CLI,
            blueprint=r.get("blueprint") if r.get("instance") else None,
            busy=r.get("busy"), history_size=r.get("history_size"), needs_ho=r.get("needs_ho"),
            tmux=bool(r.get("tmux")), stuck=name in stuck_names, model=str(r.get("model") or ""),
        )
        if v.running and s is not None:
            provider = get_provider(s.cli)
            try:
                ex = provider.last_exchange(s.cwd, s.sid) or {}
                v.last_assistant = ex.get("assistant") or ""
            except Exception:
                v.last_assistant = ""
            try:
                v.last_activity = float(provider.last_request_epoch(s.cwd, s.sid, s.pid) or 0.0)
            except Exception:
                v.last_activity = 0.0
            if s.cli == "claude":
                try:
                    v.context_tokens = context_tokens_for(s.cwd, s.sid)
                except Exception:
                    v.context_tokens = None
            try:
                v.started_at = float(psutil.Process(s.pid).create_time())
            except Exception:
                v.started_at = 0.0
        views.append(v)
    return views


# ── oturuma metin gönderme ────────────────────────────────────────────────────

def _wait_ready(name: str, cli: str, timeout: float = READY_TIMEOUT_SECONDS) -> bool:
    """Yeni açılan oturum input alacak hale gelene kadar bekle: pane var, içinde bir şey var, busy
    deseni (varsa) art arda 3 yoklamada yok. Garanti değil — claude meşgulken gelen input'u zaten
    KUYRUĞA alıyor (canlı doğrulanmış, bkz. `turns.py`), bu yüzden en kötü durumda direktif gecikir, kaybolmaz."""
    provider = get_provider(cli)
    pattern = provider.busy_status_pattern()
    t0 = time.monotonic()
    calm = 0
    while time.monotonic() - t0 < timeout:
        time.sleep(1.0)
        if not tmux_has_session(name):
            calm = 0
            continue
        text = strip_ansi(tmux_capture(name, lines=20) or "").strip()
        if not text:
            calm = 0
            continue
        if pattern and is_busy_now(name, pattern):
            calm = 0
            continue
        calm += 1
        if calm >= 3 and time.monotonic() - t0 >= READY_MIN_SECONDS:
            return True
    return False


def _send(name: str, cli: str, text: str) -> bool:
    provider = get_provider(cli)
    if not provider.has_conversation():
        return False
    return tmux_send_keys(name, text, settle_delay=provider.input_settle_delay())


def _running(name: str):
    for s in find_sessions(measure_cpu=False):
        if s.name == name:
            return s
    return None


def _project_for_session(name: str, projects: Dict[str, sw.Project]) -> Optional[sw.Project]:
    """Oturum adı → değnekçi projesi: tam ad, yoksa instance kaydının blueprint'i, yoksa base adı."""
    if name in projects:
        return projects[name]
    rec = inst_mod.get_instance(name)
    if rec and rec.get("blueprint") in projects:
        return projects[rec["blueprint"]]
    from ..session import Session
    base = Session(name=name, pid=0).base
    if base in projects:
        return projects[base]
    m = inst_mod.DERIVED_NAME_RE.match(name)     # rakamlı proje adı (wifi5gppr20261019): Session.base çözemez
    return projects.get(m.group(1)) if m else None


def _ensure_running(name: str, model: str = "", effort: str = "", lang: str = "tr", fresh: bool = False) -> Dict[str, Any]:
    s = _running(name)
    if s is not None:
        return {"ok": True, "started": False, "cli": s.cli}
    res = _act("start", name, model=model, effort=effort, fresh=fresh, lang=lang)
    if not res.get("ok"):
        return res
    cli = _project_cli(name)
    ready = _wait_ready(name, cli)
    return {"ok": True, "started": True, "ready": ready, "cli": cli}


def _give_directive(project: sw.Project, text: str, *, model: str = "", effort: str = "",
                    answer: Optional[sw.Question] = None, start_if_stopped: bool = True,
                    reason: str = "", session_name: str = "") -> Dict[str, Any]:
    """`project`'e (ya da onun `session_name` adlı çalışan instance'ına) direktif gönder; kapalıysa aç.
    Proje değnekçi kaydında değilse (ad hoc oturum) sadece gönderir, kayıt açmaz."""
    cfg = steward_config()
    lang = cfg.lang
    target = session_name or project.name
    if not model and not effort:
        model, effort = sw.phase_model_effort(project, cfg)
    s = _running(target)
    if s is None:
        if not start_if_stopped:
            return {"ok": False, "error": "not running"}
        res = _ensure_running(target, model=model, effort=effort, lang=lang)
        if not res.get("ok"):
            return res
        s = _running(target)
        if s is None:
            return {"ok": False, "error": "start reported ok but no process found"}
    if not is_tmux_backed(s.pid):
        return {"ok": False, "error": "not tmux-backed (cannot inject)"}
    message = sw.build_directive(project, lang=lang, extra=text, answer=answer)
    if not _send(s.name, s.cli, message):
        return {"ok": False, "error": "send failed"}
    if project.name in sw.load_projects():
        sw.upsert_project(project.name, last_visit=time.time(),
                          last_directive=(text or f"[{project.phase} şablonu]")[:400], visits=project.visits + 1)
    state = sw.load_state()
    state.setdefault("last_directive_at", {})[s.name] = time.time()
    sw.save_state(state)
    if answer is not None:
        sw.mark_delivered(answer.id)
    sw.log_event("directive", name=project.name, reason=reason, chars=len(message))
    return {"ok": True, "name": s.name, "chars": len(message)}


# ── proje kartları ────────────────────────────────────────────────────────────
#
# Çekirdek (`steward.py`): ham kart, prompt, ayrıştırma, yenileme kuralı. Burada: modeli çağıran tek seferlik
# özet (`summarize_card`), hangi projenin yenileneceği (`refresh_due_cards`) ve arka plan işi. Kart yenileme
# `_LOCK` ALTINDA DEĞİL: bir model çağrısı (10-60 sn) tick'i ve beynin MCP çağrılarını bekletmesin.

def oneshot_cwd() -> str:
    """Tek seferlik çağrıların NÖTR cwd'si (proje klasörü değil): CLAUDE.md/transkript projeye karışmasın."""
    return os.path.join(sw.STEWARD_DIR, "oneshot")


def summarize_card(raw: Dict[str, Any], name: str = "", project: Optional[sw.Project] = None,
                   cfg: Optional[sw.Config] = None) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Ham karttan tek seferlik headless çağrıyla (`provider.oneshot`) özet iste. Dönen: (alanlar | None, meta).
    None = çağrı başarısız ya da yanıt JSON değil (`meta["error"]` nedeni söyler); çağıran ham kartta kalır."""
    cfg = cfg or steward_config()
    cli = cfg.card_cli if cfg.card_cli in PROVIDERS else DEFAULT_CLI
    provider = get_provider(cli)
    model = sw.pick_card_model(cfg.card_model, provider.model_choices(), default_model_for(provider))
    meta: Dict[str, Any] = {"cli": cli, "model": model}
    prompt = sw.build_card_prompt(name, raw, project, lang=cfg.lang)
    t0 = time.time()
    try:
        text = provider.oneshot(prompt, model, oneshot_cwd(), timeout=CARD_TIMEOUT_SECONDS)
    except OneshotError as e:
        meta["error"] = str(e)
        return None, meta
    finally:
        meta["secs"] = round(time.time() - t0, 1)
    if text is None:
        meta["error"] = f"{cli}: tek seferlik çağrı desteklenmiyor"
        return None, meta
    parsed = sw.parse_card_json(text)
    if parsed is None:
        meta["error"] = "yanıt JSON olarak ayrıştırılamadı"
    return parsed, meta


def _cwd_resolver() -> Callable[[str], str]:
    """Proje adı -> cwd, filo anlık görüntüsü bir kez alınarak (160 projede her biri için süreç taraması YOK;
    çalışan projeler zaten kart yenilemeden dışlanır, yalnız roster/instance kayıtlarına bakılır)."""
    fleet = _act("fleet_status") or {}

    def resolve(name: str) -> str:
        info = fleet.get(name) if isinstance(fleet, dict) else None
        if info and info.get("cwd"):
            return info["cwd"]
        rec = inst_mod.get_instance(name)
        return (rec or {}).get("cwd") or ""
    return resolve


def refresh_card(name: str, cfg: Optional[sw.Config] = None, *, cwd: str = "", raw: Optional[Dict[str, Any]] = None,
                 reason: str = "") -> Dict[str, Any]:
    """Tek projenin kartını üret/yenile ve yaz. Özet başarısızsa: kart varsa DOKUNULMAZ (yalnız deneme kaydı),
    yoksa ham kart yazılır. Her çağrı `log.jsonl`'a bir `card` olayı düşer (günlük özet bunu sayar)."""
    cfg = cfg or steward_config()
    project = sw.load_projects().get(name)
    cwd = cwd or _project_cwd(name)
    if not cwd or not os.path.isdir(cwd):
        return {"ok": False, "name": name, "error": "project folder unknown"}
    raw = raw or sw.build_raw_card(cwd)
    parsed, meta = summarize_card(raw, name, project, cfg)
    old = sw.load_card(name)
    if parsed is None and old is not None:
        sw.note_card_failure(name, raw["source_hash"], meta.get("error", ""))
    else:
        sw.save_card(name, sw.make_card(raw, parsed, project, meta={
            **{k: meta[k] for k in ("cli", "model") if k in meta},
            **({"last_error": meta["error"]} if parsed is None and meta.get("error") else {})}))
    ok = parsed is not None
    sw.log_event("card", name=name, ok=ok, reason=reason, model=meta.get("model", ""), cli=meta.get("cli", ""),
                 secs=meta.get("secs", 0), error=meta.get("error", ""))
    return {"ok": ok, "name": name, "error": meta.get("error", ""), "model": meta.get("model", "")}


def _running_names_for(live: List[Any], projects: Dict[str, sw.Project]) -> set:
    """Çalışan oturumların proje adları: tam ad + `Session.base` + değnekçi projesine eşleme. `Session.base` yalnız
    harften oluşan adları çözer (`wifi5gppr20261019` → kendisi), bu yüzden rakamlı proje adları "çalışmıyor" görünür
    ve uğrama sırası ikinci bir oturum açardı; `_project_for_session` blueprint/tarih sonekinden de çözer."""
    out = {s.name for s in live} | {s.base for s in live}
    for s in live:
        p = _project_for_session(s.name, projects)
        if p is not None:
            out.add(p.name)
    return out


def _running_project_names() -> set:
    return _running_names_for(find_sessions(measure_cpu=False), sw.load_projects())


def refresh_due_cards(cfg: Optional[sw.Config] = None, limit: Optional[int] = None,
                      now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Kartı olmayan / bayat / kaynağı değişmiş / eskimiş, ÇALIŞMAYAN, aktif fazdaki projeleri yenile (en çok
    `limit`; None = `cards_per_tick`). Önce kartı hiç olmayanlar, sonra en eski kart. Çalışan proje atlanır:
    oturum yazarken kaynak zaten değişiyor (handover'dan sonra `mark_card_stale` ile işaretlenir)."""
    cfg = cfg or steward_config()
    limit = cfg.cards_per_tick if limit is None else limit
    if limit <= 0:
        return []
    now = now if now is not None else time.time()
    projects = sw.load_projects()
    running = _running_project_names()
    cards = sw.load_cards()
    cwd_of = _cwd_resolver()
    due = []
    for p in projects.values():
        if p.phase not in sw.ACTIVE_PHASES or p.name in running:
            continue
        cwd = cwd_of(p.name)
        if not cwd or not os.path.isdir(cwd):
            continue
        raw = sw.build_raw_card(cwd)
        reason = sw.card_refresh_reason(cards.get(p.name), raw["source_hash"], now, cfg.card_max_age_hours)
        if reason:
            old = cards.get(p.name)
            due.append(((old is not None, float((old or {}).get("updated_at") or 0.0), p.priority, p.name), p, cwd, raw, reason))
    due.sort(key=lambda x: x[0])
    results = []
    for _, p, cwd, raw, reason in due[:limit]:
        try:
            results.append(refresh_card(p.name, cfg, cwd=cwd, raw=raw, reason=reason))
        except Exception as e:  # tek kart döngüyü düşürmesin
            diag_log("steward_card_crashed", name=p.name, error=repr(e))
            results.append({"ok": False, "name": p.name, "error": repr(e)})
    return results


def _run_cards_job(job: Callable[[], Any]) -> bool:
    """Kart işini arka planda koştur; zaten bir iş sürüyorsa False (üst üste binmesin)."""
    if not _CARD_LOCK.acquire(blocking=False):
        return False

    def _work() -> None:
        try:
            job()
        except Exception as e:
            diag_log("steward_card_job_crashed", error=repr(e))
        finally:
            _CARD_LOCK.release()

    if _CARD_BACKGROUND:
        threading.Thread(target=_work, daemon=True, name="steward-cards").start()
    else:
        _work()
    return True


def card_tick(cfg: sw.Config) -> bool:
    """tick_once'ın kart adımı: `card_refresh` açıksa ve `cards_per_tick` > 0 ise arka planda bir tur."""
    if not cfg.card_refresh or cfg.cards_per_tick <= 0:
        return False
    return _run_cards_job(lambda: refresh_due_cards(cfg))


# ── beyin ─────────────────────────────────────────────────────────────────────

def brain_spec() -> McpServerSpec:
    from . import mcp_steward
    return mcp_steward.default_spec()


def ensure_workspace(cfg: Optional[sw.Config] = None) -> str:
    cfg = cfg or steward_config()
    os.makedirs(sw.WORKSPACE_DIR, exist_ok=True)
    persona = sw.persona_text(str(load_settings().get("steward_persona_text") or ""))
    text = sw.build_workspace_claude_md(persona, lang=cfg.lang)
    path = os.path.join(sw.WORKSPACE_DIR, "CLAUDE.md")
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return path
    except OSError:
        pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def brain_start(cfg: Optional[sw.Config] = None, fresh: bool = False) -> Dict[str, Any]:
    cfg = cfg or steward_config()
    if _running(cfg.brain_name) is not None:
        return {"ok": True, "started": False, "name": cfg.brain_name}
    ensure_workspace(cfg)
    cli = cfg.brain_cli if cfg.brain_cli in PROVIDERS else DEFAULT_CLI
    provider = get_provider(cli)
    model = cfg.brain_model or default_model_for(provider)
    effort = cfg.brain_effort or default_effort_for(provider)
    mode = provider.permission_modes()[0] if provider.permission_modes() else "auto"
    inst_mod.record_instance(cfg.brain_name, blueprint=None, cwd=sw.WORKSPACE_DIR, cli=cli, model=model,
                             permission_mode=mode, effort=effort, origin="steward")
    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
            kind = spawn_session(name=cfg.brain_name, cwd=sw.WORKSPACE_DIR, model=model, display=detect_display(),
                                 permission_mode=mode, effort=effort, force_new=bool(fresh), cli=cli,
                                 mcp_server=brain_spec())
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    inst_mod.mark_started(cfg.brain_name, cli=cli, model=model, permission_mode=mode, effort=effort)
    ready = _wait_ready(cfg.brain_name, cli)
    sw.log_event("brain_start", name=cfg.brain_name, kind=kind, ready=ready)
    return {"ok": True, "started": True, "name": cfg.brain_name, "kind": kind, "ready": ready}


def brain_stop(cfg: Optional[sw.Config] = None) -> Dict[str, Any]:
    cfg = cfg or steward_config()
    if _running(cfg.brain_name) is None:
        return {"ok": True, "stopped": False}
    res = _act("stop", cfg.brain_name, lang=cfg.lang)
    sw.log_event("brain_stop", name=cfg.brain_name, ok=bool(res.get("ok")))
    return res


def _enrich_item(it: Dict[str, Any], projects: Dict[str, sw.Project]) -> Dict[str, Any]:
    if it.get("kind") == "idea":
        return it
    name = it.get("name") or ""
    p = projects.get(name)
    s = _running(name)
    proj = p or (_project_for_session(s.name, projects) if s is not None else None)
    out = dict(it)
    if proj is not None:
        out.update({"phase": proj.phase, "kindp": proj.kind, "goal": proj.goal, "last_directive": proj.last_directive})
    cwd = (s.cwd if s is not None else "") or _project_cwd(name)
    if s is not None:
        try:
            out["last_exchange"] = get_provider(s.cli).last_exchange(s.cwd, s.sid) or {}
        except Exception:
            out["last_exchange"] = {}
    card = sw.load_card(proj.name) if proj is not None else None
    if card is not None:
        out["card"] = card    # beyin 160 repoyu değil kartları okur; ham belge başı yalnız kart yokken
        return out
    docs = {}
    for d in ("TODO.md", "PLAN.md"):
        head = _read_head(cwd, d, 600) if cwd else ""
        if head:
            docs[d] = head
    if docs:
        out["docs"] = docs
    return out


TOUR_FAILS_BEFORE_RESTART = 2    # art arda bu kadar tur gönderimi başarısızsa beyin oturumu yeniden açılır


def brain_restart_for_stuck_input(cfg: sw.Config) -> Dict[str, Any]:
    """Beyin oturumunu durdurup yeniden aç (konuşma `--resume` ile sürer; giriş kutusu temizlenir)."""
    stop = _act("stop", cfg.brain_name, lang=cfg.lang)
    if not stop.get("ok"):
        return stop
    time.sleep(3)
    return brain_start(cfg)


def run_tour(items: Optional[List[Dict[str, Any]]] = None, force: bool = False) -> Dict[str, Any]:
    """Beyne bir tur prompt'u gönder. `items` None ise şu anki gözden-geçirme maddeleri `review_items`'tan
    alınır (`force`: tour_minutes/beyin-boşta şartına bakılmaz, madde yoksa yine de "tur" gönderilir —
    kullanıcı bilerek istedi; beyin `steward_overview` ile kendi bakar). Beyin kapalıysa açılır."""
    cfg = steward_config()
    projects = sw.load_projects()
    if items is None:
        state = sw.load_state()
        views = _collect_views(cfg)
        items = sw.review_items(views, projects, cfg, time.time(), sw.load_questions(), sw.load_ideas(),
                                skip=set(state.get("ho_pending") or {}),
                                last_directive_at=state.get("last_directive_at") or {},
                                reviewed_at=state.get("reviewed_at") or {})
        if not items and not force:
            return {"ok": False, "error": "no review items right now"}
    res = brain_start(cfg)
    if not res.get("ok"):
        return res
    s = _running(cfg.brain_name)
    if s is None or not is_tmux_backed(s.pid):
        return {"ok": False, "error": "brain session not reachable"}
    enriched = [_enrich_item(it, projects) for it in items]
    prompt = sw.build_tour_prompt(enriched, lang=cfg.lang, open_qs=sw.open_questions(), now=time.time())
    if not _send(s.name, s.cli, prompt):
        return {"ok": False, "error": "send failed"}
    state = sw.load_state()
    state["last_tour"] = time.time()
    sw.save_state(state)
    sw.log_event("tour", items=len(enriched), chars=len(prompt))
    return {"ok": True, "items": len(enriched), "chars": len(prompt)}


# ── günlük özet ───────────────────────────────────────────────────────────────

NTFY_SUMMARY_CHARS = 1500


def _write_summary(date: str, cfg: sw.Config, late: bool = False) -> str:
    """Bir günün özetini yaz + telefona gönder + logla; ardından o günün `tick` satırlarını tek toplama katla
    (`compact_log`; özet sayıları aynı kalır) ve dosya büyüdüyse devir (`rotate_log`)."""
    text = sw.summary_text(date, cfg.lang)
    path = sw.write_daily(date, text)
    note = ("(gecikmiş özet) " if cfg.lang != "en" else "(late summary) ") if late else ""
    notified = notify_phone((note + text)[:NTFY_SUMMARY_CHARS])
    sw.log_event("summary", date=date, path=path, notified=notified, chars=len(text), late=late)
    folded = sw.compact_log(date)
    rotated = sw.rotate_log()
    if folded or rotated:
        sw.log_event("log_compact", date=date, ticks=folded, rotated=rotated)
    return path


def maybe_daily_summary(cfg: sw.Config, now: float) -> Optional[str]:
    """`summary_hour`u geçtiyse ve bugünün özeti yazılmadıysa: `steward/daily/<tarih>.md` yaz, ntfy ile telefona
    gönder (kuruluysa), `summary` olayını logla, `state.summary_date`i işaretle. Önce KAÇAN günler
    (`missed_summary_dates`: panel `summary_hour`da kapalıysa o gün özetlenmemişti) saat beklemeden tamamlanır.
    Dönen: yazılan son dosyanın yolu; yazılacak bir şey yoksa None."""
    path: Optional[str] = None
    for date in sw.missed_summary_dates(now):
        path = _write_summary(date, cfg, late=True)
    state = sw.load_state()
    date = sw.summary_due(state, now, cfg.summary_hour)
    if not date:
        return path
    path = _write_summary(date, cfg)
    state = sw.load_state()
    state["summary_date"] = date
    sw.save_state(state)
    return path


def http_summary(date: str = "", lang: str = "") -> Dict[str, Any]:
    cfg = steward_config()
    date = date or time.strftime("%Y-%m-%d")
    try:
        time.strptime(date, "%Y-%m-%d")
    except ValueError:
        return {"ok": False, "error": "date must be YYYY-MM-DD"}
    path = sw.daily_path(date)
    return {"ok": True, "date": date, "text": sw.summary_text(date, lang if lang in ("tr", "en") else cfg.lang),
            "saved": os.path.isfile(path), "path": path if os.path.isfile(path) else ""}


# ── eylem uygulama ────────────────────────────────────────────────────────────

def _apply(action: sw.Action, cfg: sw.Config, projects: Dict[str, sw.Project]) -> Dict[str, Any]:
    k = action.kind
    name = action.name
    if k == "handover":
        return _act("handover", name, lang=cfg.lang)
    if k == "respawn":
        if _running(name) is not None:
            res = _act("stop", name, lang=cfg.lang)
            if not res.get("ok"):
                return res
        if name == cfg.brain_name:
            return brain_start(cfg, fresh=True)   # devirden sonra YENİ konuşma (aynı şişmiş bağlam taşınmasın; notlar NOTLAR.md'de)
        p = _project_for_session(name, projects)
        model, effort = sw.phase_model_effort(p, cfg) if p else ("", "")
        # Devirden sonra YENİ konuşma (`--new`): `--resume` aynı şişmiş bağlamı (her tur yeniden okunan ~400K token)
        # ve eski modelin önbelleğini taşırdı. Devir özeti CLAUDE.md'de, yeni oturum onu kendisi okur.
        res = _ensure_running(name, model=model, effort=effort, lang=cfg.lang, fresh=True)
        if not res.get("ok") or p is None:
            return res
        sw.mark_card_stale(p.name)   # handover'da oturum işini yazdı: kart, proje durunca yeniden özetlensin
        return _give_directive(p, "", reason="respawn", session_name=name)
    if k == "start":
        p = projects.get(name)
        if p is None:
            return {"ok": False, "error": "not a steward project"}
        q = None
        if action.payload.get("question_id"):
            q = next((x for x in sw.load_questions() if x.id == action.payload["question_id"]), None)
        return _give_directive(p, "", answer=q, reason=action.reason)
    if k == "stop":
        return _act("stop", name, lang=cfg.lang)
    if k == "deliver_answer":
        q = next((x for x in sw.load_questions() if x.id == action.payload.get("question_id")), None)
        if q is None:
            return {"ok": False, "error": "question gone"}
        p = projects.get(q.project) or sw.Project(name=q.project)
        extra = "Cevaba göre devam et." if cfg.lang != "en" else "Continue according to the answer."
        res = _give_directive(p, extra, answer=q, start_if_stopped=False, reason="answer", session_name=name)
        if not res.get("ok") and q.project not in projects:
            # Kayıtlı proje olmayan (ad hoc) oturum kapanmış ya da yazı kabul etmiyor: her tick yeniden deneme,
            # bırak (cevap kayıtta durur, kimse beklemiyor).
            sw.mark_delivered(q.id)
            sw.log_event("answer_undeliverable", id=q.id, session=name, error=res.get("error", ""))
        return res
    if k == "ask_user":
        q = sw.add_question(action.payload.get("project") or name, action.payload.get("text") or "", source=name,
                            routine=bool(action.payload.get("routine")))
        if q.status == "open" and q.routine:   # işleyiş sorusu: telefona gitmez, beynin turunda cevaplanır
            return {"ok": True, "id": q.id, "notified": False, "routine": True}
        if q.status != "open":   # yakın zamanda cevaplanmış soru yeniden soruldu: telefona yeni soru gitmez, cevap yeniden iletilir
            return {"ok": True, "id": q.id, "notified": False, "reasked": True}
        notified = notify_phone(f"[{q.project}] {q.text}\n→ py/cops steward answer {q.id} \"...\"")
        return {"ok": True, "id": q.id, "notified": notified}
    if k == "escalate_routine":
        q = sw.escalate_routine(action.payload.get("question_id") or "")
        if q is None:
            return {"ok": False, "error": "not an open routine question"}
        notified = notify_phone(f"[{q.project}] {q.text}\n→ py/cops steward answer {q.id} \"...\"")
        return {"ok": True, "id": q.id, "notified": notified}
    if k == "idea":
        i = sw.add_idea(action.payload.get("text") or "", source=name)
        return {"ok": True, "id": i.id}
    if k == "set_phase":
        sw.upsert_project(name, phase=action.payload.get("phase"))
        return {"ok": True}
    if k == "tour":
        res = run_tour(action.payload.get("items") or [])
        state = sw.load_state()
        if res.get("ok"):
            if state.get("tour_fail"):
                state["tour_fail"] = 0
                sw.save_state(state)
            return res
        fails = int(state.get("tour_fail") or 0) + 1
        state["tour_fail"] = fails
        sw.save_state(state)
        if fails >= TOUR_FAILS_BEFORE_RESTART:
            # Beynin giriş kutusu takılı (gönderilmemiş yapıştırma birikir): oturumu yeniden aç, sayacı sıfırla.
            sw.log_event("brain_unstick", fails=fails, error=res.get("error", ""))
            rb = brain_restart_for_stuck_input(cfg)
            state = sw.load_state()
            state["tour_fail"] = 0
            sw.save_state(state)
            res = dict(res, restarted=bool(rb.get("ok")))
        return res
    return {"ok": False, "error": f"unknown action {k}"}


def tick_once(trigger: str = "timer") -> Dict[str, Any]:
    """Bir tick: görünümleri topla → kararlar → uygula → state kaydet. Elle (`/api/steward/tick`,
    `py/cops steward tick`) de çağrılır; döngü kapalıyken bile çalışır (kullanıcı bilerek istedi)."""
    with _LOCK:
        cfg = steward_config()
        t0 = time.time()
        applied: List[Dict[str, Any]] = []
        dry_applied: List[Dict[str, Any]] = []
        error = ""
        try:
            projects = sw.load_projects()
            views = _collect_views(cfg)
            actions, new_state = sw.plan_tick(views, projects, sw.load_state(), cfg, t0,
                                              sw.load_questions(), sw.load_ideas())
            actions, dry, new_state = sw.observe_filter(actions, cfg.mode, new_state, t0)
            sw.save_state(new_state)
            for a in dry:
                _remember_dry(a)
                dry_applied.append({"kind": a.kind, "name": a.name, "reason": a.reason, "dry": True})
            for a in actions:
                try:
                    res = _apply(a, cfg, projects)
                except Exception as e:  # tek eylem tick'i düşürmesin
                    res = {"ok": False, "error": repr(e)}
                    diag_log("steward_action_crashed", kind=a.kind, name=a.name, error=repr(e))
                _remember(a, res)
                applied.append({"kind": a.kind, "name": a.name, "reason": a.reason, "ok": bool(res.get("ok")),
                                "detail": res.get("error") or ""})
        except Exception as e:
            error = repr(e)
            diag_log("steward_tick_crashed", error=repr(e))
        _LAST_TICK.update({"at": t0, "trigger": trigger, "actions": len(applied), "dry": len(dry_applied), "error": error})
        sw.log_event("tick", trigger=trigger, mode=cfg.mode, n=len(applied), dry=len(dry_applied), error=error)
        if applied:
            web_ws.notify_status_changed()
        if cfg.enabled:
            try:
                maybe_daily_summary(cfg, t0)
            except Exception as e:
                diag_log("steward_summary_crashed", error=repr(e))
    try:
        card_tick(cfg)
    except Exception as e:
        diag_log("steward_card_tick_crashed", error=repr(e))
    return {"ok": not error, "error": error, "actions": applied, "dry": dry_applied, "mode": cfg.mode, "at": t0}


def _loop() -> None:
    while True:
        cfg = steward_config()
        time.sleep(max(15, cfg.tick_seconds))
        if not steward_config().enabled:
            continue
        try:
            tick_once("timer")
        except Exception as e:
            diag_log("steward_loop_crashed", error=repr(e))


def start_loop() -> None:
    global _loop_started
    if _loop_started:
        return
    _loop_started = True
    threading.Thread(target=_loop, daemon=True, name="steward-loop").start()


# ── özet / HTTP ───────────────────────────────────────────────────────────────

_SUMMARY_CACHE: Dict[str, Any] = {"until": 0.0, "value": None}
_SUMMARY_TTL = 5.0


def summary(running_names: Optional[set] = None) -> Dict[str, Any]:
    """`/api/status`'a giden HAFİF alan (`orch` gibi local-only). ~2 sn'lik WS/poll cadence'ine bindiği için
    5 sn önbellekli; `running_names` verilirse (status payload'ın kendi taraması) ayrıca proc taranmaz."""
    now = time.monotonic()
    hit = _SUMMARY_CACHE["value"]
    if hit is not None and _SUMMARY_CACHE["until"] > now:
        return hit
    cfg = steward_config()
    projects = sw.load_projects()
    questions = sw.load_questions()
    state = sw.load_state()
    brain_running = (cfg.brain_name in running_names) if running_names is not None else (_running(cfg.brain_name) is not None)
    value = {
        "enabled": cfg.enabled,
        "mode": cfg.mode,
        "tick_seconds": cfg.tick_seconds,
        "projects": sw.summarize_projects(projects),
        "open_questions": len(sw.open_questions(questions)),
        "ideas_new": sum(1 for i in sw.load_ideas() if i.status == "new"),
        "pending_items": int(state.get("pending_items") or 0),
        "last_tick": dict(_LAST_TICK),
        "last_tour": state.get("last_tour") or 0.0,
        "brain": {"name": cfg.brain_name, "running": brain_running},
        "recent": _RECENT[:5],
    }
    _SUMMARY_CACHE.update(until=now + _SUMMARY_TTL, value=value)
    return value


def invalidate_summary() -> None:
    _SUMMARY_CACHE["until"] = 0.0


def _project_dict(p: sw.Project, running: Optional[set] = None,
                  cards: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    d = dataclasses.asdict(p)
    if running is not None:
        d["running"] = p.name in running
    card = (cards if cards is not None else {p.name: sw.load_card(p.name)}).get(p.name) or {}
    d["next_step"] = sw.card_one_liner(card)
    d["card_updated_at"] = float(card.get("updated_at") or 0.0)
    return d


def http_state() -> Dict[str, Any]:
    cfg = steward_config()
    projects = sw.load_projects()
    live = find_sessions(measure_cpu=False)
    running_projects = _running_names_for(live, projects)
    cards = sw.load_cards()
    return {
        "ok": True,
        "config": dataclasses.asdict(cfg),
        "summary": summary(),
        "projects": [_project_dict(p, running_projects, cards)
                     for p in sorted(projects.values(), key=lambda p: (p.priority, p.name))],
        "running": [{"name": s.name, "cwd": s.cwd, "cli": s.cli, "model": s.model} for s in live],
        "questions": [dataclasses.asdict(q) for q in sw.open_questions()],
        "ideas": [dataclasses.asdict(i) for i in sw.load_ideas() if i.status == "new"],
        "recent": _RECENT,
    }


def http_projects() -> Dict[str, Any]:
    cards = sw.load_cards()
    return {"ok": True, "projects": [_project_dict(p, None, cards) for p in sw.load_projects().values()]}


def http_questions(status: str = "open") -> Dict[str, Any]:
    qs = sw.load_questions()
    if status == "open":
        qs = [q for q in qs if q.status == "open"]
    elif status == "answered":
        qs = [q for q in qs if q.status == "answered"]
    return {"ok": True, "questions": [dataclasses.asdict(q) for q in qs]}


def http_ideas(status: str = "new") -> Dict[str, Any]:
    ideas = sw.load_ideas()
    if status and status != "all":
        ideas = [i for i in ideas if i.status == status]
    return {"ok": True, "ideas": [dataclasses.asdict(i) for i in ideas]}


_EXPORT_FILES = {"todo": "TODO.md", "tbd": "TOBEDECIDED.md"}
_EXPORT_HEADING = "## Değnekçi fikirleri"


def _idea_project(idea: "sw.Idea", projects: Dict[str, "sw.Project"]) -> str:
    """Fikrin bağlı olduğu değnekçi projesi: `project`/`source` ya doğrudan proje adıdır ya da tarih sonekli oturum adı."""
    for cand in (idea.project, idea.source):
        cand = str(cand or "")
        if cand in projects:
            return cand
        m = re.match(r"^(.*?)\d{8}(?:_\d+)?$", cand)
        if m and m.group(1) in projects:
            return m.group(1)
    return ""


def _append_idea_item(path: str, idea: "sw.Idea", stamp: str) -> bool:
    """Fikri `path`in sonuna `- [ ]` maddesi olarak ekler (aynı fikir kimliği varsa dokunmaz). True = yazıldı."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    if idea.id in text:
        return False
    line = f"- [ ] (değnekçi fikri {idea.id}) {' '.join(idea.text.split())}"
    last_head = next((ln for ln in reversed(text.splitlines()) if ln.startswith("## ")), "")
    body = text.rstrip("\n")
    if last_head.startswith(_EXPORT_HEADING):
        new = f"{body}\n{line}\n"
    else:
        new = (f"{body}\n\n" if body else "") + f"{_EXPORT_HEADING} ({stamp})\n{line}\n"
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, path)
    return True


def http_idea_export(data: Dict[str, Any]) -> Dict[str, Any]:
    """Fikri projenin `TODO.md`/`TOBEDECIDED.md` dosyasına yazar. `kind`: todo|tbd; `target`: project (fikrin projesi) |
    all (kayıtlı tüm değnekçi projeleri). Fikir `exported` olur (listeden kalkar), kayıt fikrin üstünde durur."""
    kind = str(data.get("kind") or "")
    target = str(data.get("target") or "project")
    fname = _EXPORT_FILES.get(kind)
    if fname is None:
        return {"ok": False, "error": "kind must be todo or tbd"}
    if target not in ("project", "all"):
        return {"ok": False, "error": "target must be project or all"}
    idea = next((i for i in sw.load_ideas() if i.id == str(data.get("id") or "")), None)
    if idea is None:
        return {"ok": False, "error": "unknown idea id"}
    projects = sw.load_projects()
    names = [n for n in (_idea_project(idea, projects),) if n] if target == "project" else sorted(projects)
    if not names:
        return {"ok": False, "error": "idea has no steward project; choose target=all"}
    stamp = time.strftime("%Y-%m-%d")
    written: List[str] = []
    present: List[str] = []
    skipped: List[str] = []
    for n in names:
        cwd = _project_cwd(n)
        if not cwd or not os.path.isdir(cwd):
            skipped.append(n)
            continue
        try:
            (written if _append_idea_item(os.path.join(cwd, fname), idea, stamp) else present).append(n)
        except OSError as e:
            diag_log("steward_idea_export_failed", project=n, error=repr(e))
            skipped.append(n)
    if not written and not present:
        return {"ok": False, "error": "no project directory found", "skipped": skipped}
    sw.record_idea_export(idea.id, {"kind": kind, "target": target, "file": fname, "projects": written + present, "at": time.time()})
    sw.log_event("idea_export", id=idea.id, kind=kind, target=target, written=written, present=present, skipped=skipped)
    return {"ok": True, "written": written, "already": present, "skipped": skipped}


def http_log(n: int = 50) -> Dict[str, Any]:
    return {"ok": True, "entries": sw.tail_log(max(1, min(500, n)))}


def http_context(name: str, docs: bool = False) -> Dict[str, Any]:
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    projects = sw.load_projects()
    p = projects.get(name)
    s = _running(name)
    cwd = (s.cwd if s is not None else "") or _project_cwd(name)
    out: Dict[str, Any] = {"ok": True, "name": name, "project": _project_dict(p) if p else None, "cwd": cwd,
                           "running": s is not None}
    if s is not None:
        provider = get_provider(s.cli)
        try:
            out["last_exchange"] = provider.last_exchange(s.cwd, s.sid) or {}
        except Exception:
            out["last_exchange"] = {}
        out["cli"], out["model"] = s.cli, s.model
    owner = _project_for_session(name, projects)
    card = sw.load_card(owner.name if owner is not None else name)
    if card is not None:
        out["card"] = card
        out["card_stale"] = bool(card.get("stale"))
    if card is None or docs:    # kart varsa ham belge başları yerine kart; `docs=1` ikisini birden ister
        out["docs"] = {d: _read_head(cwd, d) for d in DOCS if cwd} if cwd else {}
        out["docs"] = {k: v for k, v in out["docs"].items() if v}
    out["git"] = _git_short(cwd)
    out["questions"] = [dataclasses.asdict(q) for q in sw.load_questions() if q.project == name and q.status == "open"]
    return out


def http_file(name: str, rel: str, max_chars: int = MAX_FILE_READ_CHARS) -> Dict[str, Any]:
    cwd = _project_cwd(name)
    full = _safe_project_file(cwd, rel) if cwd else None
    if full is None:
        return {"ok": False, "error": "unknown project or path outside project"}
    try:
        with open(full, encoding="utf-8", errors="replace") as f:
            text = f.read(max_chars + 1)
    except OSError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "path": rel, "text": text[:max_chars], "truncated": len(text) > max_chars}


def http_project_upsert(data: Dict[str, Any]) -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    fields = {k: data.get(k) for k in ("phase", "kind", "goal", "priority", "cadence_minutes", "notes", "model", "effort")
              if k in data}
    try:
        p = sw.upsert_project(name, **fields)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    sw.log_event("project_set", name=name, fields=sorted(fields))
    return {"ok": True, "project": _project_dict(p)}


def http_project_remove(data: Dict[str, Any]) -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    return {"ok": sw.remove_project(name)}


def http_register(data: Dict[str, Any]) -> Dict[str, Any]:
    """Yeni proje: klasör (yoksa oluştur + git init), GOAL.md (amaç + kaynaklar), yerel kaynak dosyalarını
    `kaynaklar/`a kopyala, roster'a kaydet (`web._register_project`), değnekçi kaydını aç."""
    cfg = steward_config()
    name = str(data.get("name") or "").strip()
    cwd = os.path.expanduser(str(data.get("cwd") or "").strip())
    goal = str(data.get("goal") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    if not cwd or not os.path.isabs(cwd):
        return {"ok": False, "error": "cwd must be an absolute path"}
    try:
        os.makedirs(cwd, exist_ok=True)
    except OSError as e:
        return {"ok": False, "error": f"cannot create {cwd}: {e}"}
    if not os.path.isdir(os.path.join(cwd, ".git")):
        try:
            subprocess.run(["git", "init", "-q"], cwd=cwd, capture_output=True, text=True, timeout=10)
        except Exception:
            pass
    resources = data.get("resources") or []
    if isinstance(resources, str):
        resources = [x.strip() for x in resources.replace("\n", ",").split(",") if x.strip()]
    copied, listed = [], []
    for r in resources[:50]:
        r = str(r).strip()
        if not r:
            continue
        src = os.path.expanduser(r)
        if os.path.isfile(src):
            try:
                if os.path.getsize(src) <= MAX_RESOURCE_BYTES:
                    dst_dir = os.path.join(cwd, "kaynaklar")
                    os.makedirs(dst_dir, exist_ok=True)
                    shutil.copy2(src, os.path.join(dst_dir, os.path.basename(src)))
                    copied.append(os.path.basename(src))
                    continue
            except OSError:
                pass
        listed.append(r)
    goal_path = os.path.join(cwd, "GOAL.md")
    if goal or copied or listed:
        lines = [f"# {name} — amaç" if cfg.lang != "en" else f"# {name} — goal", "", goal or "", ""]
        if copied or listed:
            lines.append("## Kaynaklar" if cfg.lang != "en" else "## Resources")
            lines += [f"- kaynaklar/{c}" for c in copied] + [f"- {l}" for l in listed]
        try:
            mode = "a" if os.path.exists(goal_path) else "w"
            with open(goal_path, mode, encoding="utf-8") as f:
                f.write(("\n" if mode == "a" else "") + "\n".join(lines).rstrip() + "\n")
        except OSError as e:
            return {"ok": False, "error": f"cannot write GOAL.md: {e}"}
    cli = str(data.get("cli") or "").strip()
    model = str(data.get("model") or "").strip()
    fleet = _act("fleet_status") or {}
    reg: Dict[str, Any] = {"ok": True, "skipped": True}
    if name not in fleet:
        reg = _act("register_project", name, cwd, model=model, cli=cli, lang=cfg.lang)
        if not reg.get("ok"):
            return reg
    phase = data.get("phase") if data.get("phase") in sw.PHASES else "planning"
    p = sw.upsert_project(name, phase=phase, kind=data.get("kind") or "", goal=goal,
                          priority=data.get("priority"), cadence_minutes=data.get("cadence_minutes"))
    idea_id = str(data.get("idea_id") or "")
    if idea_id:
        sw.update_idea(idea_id, status="project", project=name)
    sw.log_event("project_register", name=name, cwd=cwd, copied=copied, listed=len(listed))
    return {"ok": True, "project": _project_dict(p), "cwd": cwd, "copied": copied, "roster": reg}


def http_ask(data: Dict[str, Any]) -> Dict[str, Any]:
    """Soru aç (+ `options`: en çok 6 kısa seçenek) → ntfy: metin + numaralı seçenekler + `/q/<id>?k=` bağlantısı
    (tünel varsa; bildirime dokunmak sayfayı açar). Aynı açık soru ikinci kez bildirilmez (`add_question` dedup)."""
    cfg = steward_config()
    try:
        q = sw.add_question(str(data.get("project") or ""), str(data.get("text") or ""),
                            source=str(data.get("source") or "api"), options=data.get("options"))
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    link = sw.question_link(q, public_base())
    if q.notified_at:
        return {"ok": True, "id": q.id, "notified": False, "link": link, "dup": True}
    notified = notify_phone(sw.question_notification(q, link, cfg.lang), click=link)
    if notified:
        sw.mark_notified(q.id)
    sw.log_event("ask", id=q.id, project=q.project, notified=notified, options=len(q.options))
    return {"ok": True, "id": q.id, "notified": notified, "link": link}


def http_question_page(qid: str, key: str, token_ok: bool, form: Optional[Dict[str, Any]] = None) -> Tuple[int, str]:
    """`/q/<id>` (GET: sayfa, POST: `form["answer"]`). Yetki: panel token'ı YA DA sorunun kendi anahtarı (`k`,
    sabit zamanlı karşılaştırma; anahtarsız eski kayıt yalnız token'la). Dönen: (HTTP durumu, HTML)."""
    cfg = steward_config()
    lang = cfg.lang
    q = sw.find_question(qid) if qid else None
    if q is None:
        return 404, sw.question_page_html(None, lang, "missing")
    key_ok = bool(key and q.key) and secrets.compare_digest(key.encode("utf-8", "replace"), q.key.encode("utf-8"))
    if not token_ok and not key_ok:
        return 401, sw.question_page_html(None, lang, "denied")
    action = f"/q/{q.id}?k={q.key}" if q.key else f"/q/{q.id}"   # token'la gelen tarayıcı formu da anahtarla POST eder
    if q.status != "open":
        return 200, sw.question_page_html(q, lang, "already", action=action)
    if form is None:
        return 200, sw.question_page_html(q, lang, "ask", action=action)
    try:
        answered = sw.answer_question(q.id, str(form.get("answer") or ""))
    except ValueError:
        return 400, sw.question_page_html(q, lang, "ask", error=sw._QPAGE_TXT["en" if lang == "en" else "tr"]["empty"],
                                          action=action)
    sw.log_event("answer", id=q.id, project=q.project, source="phone")
    invalidate_summary()
    web_ws.notify_status_changed()
    return 200, sw.question_page_html(answered, lang, "done", action=action)


def http_answer(data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        q = sw.answer_question(str(data.get("id") or ""), str(data.get("answer") or ""))
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if q is None:
        return {"ok": False, "error": "unknown question id"}
    sw.log_event("answer", id=q.id, project=q.project)
    return {"ok": True, "question": dataclasses.asdict(q)}


def http_idea(data: Dict[str, Any]) -> Dict[str, Any]:
    if data.get("id"):
        i = sw.update_idea(str(data["id"]), status=data.get("status"), project=data.get("project"))
        if i is None:
            return {"ok": False, "error": "unknown idea id"}
        sw.log_event("idea_update", id=i.id, status=i.status, project=i.project)
        return {"ok": True, "idea": dataclasses.asdict(i)}
    try:
        i = sw.add_idea(str(data.get("text") or ""), source=str(data.get("source") or "api"))
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    sw.log_event("idea", id=i.id)
    return {"ok": True, "idea": dataclasses.asdict(i)}


def http_note(data: Dict[str, Any]) -> Dict[str, Any]:
    name = str(data.get("project") or data.get("name") or "").strip()
    text = str(data.get("text") or "").strip()
    if not sw.valid_name(name) or not text:
        return {"ok": False, "error": "project and text are required"}
    p = sw.load_projects().get(name)
    if p is None:
        return {"ok": False, "error": "not a steward project"}
    sw.upsert_project(name, notes=text)
    sw.log_event("note", name=name, chars=len(text))
    return {"ok": True}


def http_directive(data: Dict[str, Any]) -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    text = str(data.get("text") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    dry = _brain_dry("directive", data, name)
    if dry is not None:
        return dry
    with _LOCK:
        projects = sw.load_projects()
        p = _project_for_session(name, projects)
        if p is None:
            if _running(name) is None and not inst_mod.get_instance(name) and name not in (_act("fleet_status") or {}):
                return {"ok": False, "error": "unknown session/project"}
            p = sw.Project(name=name)   # ad hoc: kayıt açmadan sadece gönder
        return _give_directive(p, text, model=str(data.get("model") or ""), effort=str(data.get("effort") or ""),
                               start_if_stopped=bool(data.get("start_if_stopped", True)),
                               reason=str(data.get("reason") or "brain"), session_name=name)


def http_restart(data: Dict[str, Any]) -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    cfg = steward_config()
    dry = _brain_dry("restart", data, name)
    if dry is not None:
        return dry
    with _LOCK:
        if _running(name) is not None:
            res = _act("stop", name, lang=cfg.lang)
            if not res.get("ok"):
                return res
        sw.log_event("restart", name=name, reason=str(data.get("reason") or ""))
        return http_directive(dict(data, start_if_stopped=True, reason="restart: " + str(data.get("reason") or "")))


def http_stop(data: Dict[str, Any]) -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    cfg = steward_config()
    dry = _brain_dry("stop", data, name)
    if dry is not None:
        return dry
    with _LOCK:
        res = _act("stop", name, lang=cfg.lang)
    sw.log_event("stop", name=name, reason=str(data.get("reason") or ""), ok=bool(res.get("ok")))
    return res


def http_handover(data: Dict[str, Any]) -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    cfg = steward_config()
    dry = _brain_dry("handover", data, name)
    if dry is not None:
        return dry
    with _LOCK:
        res = _act("handover", name, lang=cfg.lang)
        if res.get("ok"):
            state = sw.load_state()
            state.setdefault("ho_pending", {})[name] = time.time()
            sw.save_state(state)
    sw.log_event("handover", name=name, ok=bool(res.get("ok")))
    return res


def http_skip(data: Dict[str, Any]) -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    sw.log_event("skip", name=name, reason=str(data.get("reason") or ""))
    state = sw.load_state()
    state.setdefault("last_directive_at", {})[name] = time.time()   # bir sonraki `idle` maddesini erteler
    sw.save_state(state)
    return {"ok": True}


def http_brain(data: Dict[str, Any]) -> Dict[str, Any]:
    action = str(data.get("action") or "start")
    with _LOCK:
        return brain_start() if action == "start" else brain_stop()


def http_cards() -> Dict[str, Any]:
    projects = sw.load_projects()
    cards = sw.load_cards()
    return {"ok": True, "cards": [dict(c, name=n) for n, c in sorted(cards.items())],
            "missing": sorted(n for n, p in projects.items() if p.phase in sw.ACTIVE_PHASES and n not in cards),
            "busy": _CARD_LOCK.locked()}


def http_card(name: str) -> Dict[str, Any]:
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    card = sw.load_card(name)
    return {"ok": True, "name": name, "card": card} if card is not None else {"ok": False, "error": "no card"}


def http_cards_refresh(data: Dict[str, Any]) -> Dict[str, Any]:
    """Kartları şimdi yenile (arka planda; model çağrısı panelin 15 sn'lik API zaman aşımını aşabilir, sonuç
    `py/cops steward cards` / `log`ta). `name` verilirse O proje (çalışıyor olsa da, kaynak değişmemiş olsa da);
    verilmezse yenilemesi GEREKEN tüm çalışmayan aktif projeler (tick başına sınırı yok)."""
    cfg = steward_config()
    name = str(data.get("name") or "").strip()
    if name:
        if not sw.valid_name(name):
            return {"ok": False, "error": "invalid name"}
        if name not in sw.load_projects():
            return {"ok": False, "error": "not a steward project"}
        job = lambda: refresh_card(name, cfg, reason="manual")   # noqa: E731
    else:
        job = lambda: refresh_due_cards(cfg, limit=10 ** 6)   # noqa: E731
    if not _run_cards_job(job):
        return {"ok": False, "error": "a card refresh is already running"}
    return {"ok": True, "queued": name or "due"}


def http_get(path: str, qs: Dict[str, List[str]]) -> Optional[Dict[str, Any]]:
    """`web.py` do_GET: `/api/steward/*` → dict (bilinmeyen alt yol → None = 404)."""
    g = lambda k, d="": (qs.get(k) or [d])[0]
    if path == "/api/steward/state":
        return http_state()
    if path == "/api/steward/projects":
        return http_projects()
    if path == "/api/steward/questions":
        return http_questions(g("status", "open"))
    if path == "/api/steward/ideas":
        return http_ideas(g("status", "new"))
    if path == "/api/steward/log":
        try:
            return http_log(int(g("n", "50")))
        except ValueError:
            return http_log()
    if path == "/api/steward/context":
        return http_context(g("name").strip(), docs=g("docs") in ("1", "true"))
    if path == "/api/steward/summary":
        return http_summary(g("date").strip(), g("lang").strip())
    if path == "/api/steward/cards":
        return http_cards()
    if path == "/api/steward/card":
        return http_card(g("name").strip())
    if path == "/api/steward/file":
        try:
            mx = int(g("max", str(MAX_FILE_READ_CHARS)))
        except ValueError:
            mx = MAX_FILE_READ_CHARS
        return http_file(g("name").strip(), g("path").strip(), max(1, min(mx, MAX_FILE_READ_CHARS)))
    return None


POST_PATHS = {
    "/api/steward/project": http_project_upsert,
    "/api/steward/project/remove": http_project_remove,
    "/api/steward/register": http_register,
    "/api/steward/ask": http_ask,
    "/api/steward/answer": http_answer,
    "/api/steward/idea": http_idea,
    "/api/steward/idea/export": http_idea_export,
    "/api/steward/note": http_note,
    "/api/steward/directive": http_directive,
    "/api/steward/restart": http_restart,
    "/api/steward/stop": http_stop,
    "/api/steward/handover": http_handover,
    "/api/steward/skip": http_skip,
    "/api/steward/cards/refresh": http_cards_refresh,
    "/api/steward/brain": http_brain,
    "/api/steward/tick": lambda data: tick_once("manual"),
    "/api/steward/tour": lambda data: run_tour(force=True),
}


def http_post(path: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fn = POST_PATHS.get(path)
    if fn is None:
        return None
    try:
        return fn(data if isinstance(data, dict) else {})
    finally:
        invalidate_summary()
