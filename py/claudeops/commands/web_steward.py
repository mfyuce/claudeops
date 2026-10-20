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
from ..settings import default_effort_for, default_model_for, load_settings, steward_config, steward_ids
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

# Kimlik başına motor durumu (docs/multi-steward-plan.md K3): kilit, son eylemler, son tick, özet önbelleği.
# `default` bağlamı modül globallerinin KENDİSİNİ taşır (`_LOCK`, `_RECENT`, `_LAST_TICK`, `_SUMMARY_CACHE` aynı
# nesneler): argümansız eski çağrılar ve eski testler değişmeden default'a gider.
# Kilit YENİDEN GİRİŞLİ: `http_restart` kilit altındayken `http_directive`i çağırır (düz Lock'ta kendini kilitliyordu).
_LOCK = threading.RLock()         # bir kimliğin tick'i ve elle tetiklenen eylemleri sıralı (başka kimliği beklemez)
_ACTIONS: Dict[str, Callable[..., Any]] = {}
_RECENT: List[Dict[str, Any]] = []
_LAST_TICK: Dict[str, Any] = {"at": 0.0, "trigger": "", "actions": 0, "dry": 0, "error": ""}
_SUMMARY_CACHE: Dict[str, Any] = {"until": 0.0, "value": None}
_loop_started = False
_CARD_LOCK = threading.Lock()      # aynı anda tek kart yenileme işi, TÜM kimlikler için ortak (K7)
_CARD_BACKGROUND = True            # testler False yapıp işi satır içi koşturur
CARD_TIMEOUT_SECONDS = 120.0


@dataclasses.dataclass
class StewardContext:
    """Bir değnekçi kimliğinin süreç içi motor durumu. Dosya yolları ÇAĞRI ANINDA (`paths`), testler `STEWARD_DIR`'i
    patch'ler. `conflicts`: son tick'te bu kimliğin `projects.json`'unda görülen sahiplik çakışmaları (status uyarısı);
    `conflict_logged`: {proje: gün} `ownership_conflict` olayı günde bir."""
    sid: str
    lock: Any = dataclasses.field(default_factory=threading.RLock)
    recent: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    last_tick: Dict[str, Any] = dataclasses.field(
        default_factory=lambda: {"at": 0.0, "trigger": "", "actions": 0, "dry": 0, "error": ""})
    summary_cache: Dict[str, Any] = dataclasses.field(default_factory=lambda: {"until": 0.0, "value": None})
    conflicts: List[str] = dataclasses.field(default_factory=list)
    conflict_logged: Dict[str, str] = dataclasses.field(default_factory=dict)

    @property
    def paths(self) -> sw.StewardPaths:
        return sw.paths_for(self.sid)


_CTX: Dict[str, StewardContext] = {
    "default": StewardContext("default", lock=_LOCK, recent=_RECENT, last_tick=_LAST_TICK, summary_cache=_SUMMARY_CACHE)}
_CTX_GUARD = threading.Lock()


def _ctx(sid: str = "default") -> StewardContext:
    """Kimliğin bağlamı (ilk istekte açılır). Geçersiz kimlik `ValueError` (sessizce default'a DÜŞMEZ)."""
    sid = sid or "default"
    with _CTX_GUARD:
        ctx = _CTX.get(sid)
        if ctx is None:
            if not sw.valid_steward_id(sid):
                raise ValueError(f"invalid steward id: {sid!r}")
            ctx = _CTX[sid] = StewardContext(sid)
        return ctx


def _reset_contexts() -> None:
    """Testler: default DIŞI bağlamları at (default'unkiler modül globalleri, testler onları kendisi temizler)."""
    with _CTX_GUARD:
        for sid in [s for s in _CTX if s != "default"]:
            del _CTX[sid]


def _ownership_index(fresh: bool = False) -> Dict[str, Any]:
    """Ayardaki kimlikler + etkin beyin adları (default'un `brain_name` ezmesi dahil) ile sahiplik indeksi."""
    ids = steward_ids()
    brains: Dict[str, str] = {}
    for s in ids:
        try:
            brains[s] = steward_config(s).brain_name
        except ValueError:
            continue
    return sw.ownership_index(ids, brains=brains, fresh=fresh)


def _world(sid: str = "default", cfg: Optional[sw.Config] = None, starts_left: Optional[int] = None,
           index: Optional[Dict[str, Any]] = None) -> sw.World:
    cfg = cfg or steward_config(sid)
    return sw.world_for(sid, index if index is not None else _ownership_index(), cfg.brain_name, starts_left)


def configure(**callbacks: Callable[..., Any]) -> None:
    """`web.py` `run()`'da verir: status_payload(), fleet_status(), start(name, model, effort, fresh, lang),
    stop(name, lang), handover(name, lang), register_project(name, cwd, model, cli, lang)."""
    _ACTIONS.update(callbacks)


def _act(name: str, *args: Any, **kw: Any) -> Any:
    fn = _ACTIONS.get(name)
    if fn is None:
        return {"ok": False, "error": f"steward engine not configured ({name})"}
    return fn(*args, **kw)


def _remember(action: sw.Action, result: Any, ctx: Optional[StewardContext] = None) -> None:
    ctx = ctx or _ctx()
    entry = {"ts": time.time(), "kind": action.kind, "name": action.name, "reason": action.reason,
             "ok": bool(result.get("ok")) if isinstance(result, dict) else bool(result),
             "detail": (result.get("error") or result.get("detail") or "") if isinstance(result, dict) else ""}
    ctx.recent.insert(0, entry)
    del ctx.recent[RECENT_ACTIONS:]
    sw.log_event("action", paths=ctx.paths, kind=action.kind, name=action.name, reason=action.reason,
                 ok=entry["ok"], detail=entry["detail"])


def _remember_dry(action: sw.Action, ctx: Optional[StewardContext] = None) -> None:
    """observe kipi: eylem UYGULANMADI. `recent`e `dry=True` ile, log'a `would:<kind>` olayı olarak yazılır."""
    ctx = ctx or _ctx()
    detail = f"{len(action.payload.get('items') or [])} madde" if action.kind == "tour" else str(action.payload.get("text") or "")[:200]
    ctx.recent.insert(0, {"ts": time.time(), "kind": action.kind, "name": action.name, "reason": action.reason,
                          "ok": True, "dry": True, "detail": detail})
    del ctx.recent[RECENT_ACTIONS:]
    extra = {"question_id": action.payload["question_id"]} if action.payload.get("question_id") else {}
    sw.log_event("would:" + action.kind, paths=ctx.paths, name=action.name, reason=action.reason, detail=detail, **extra)


def _brain_dry(kind: str, data: Dict[str, Any], name: str, sid: str = "default") -> Optional[Dict[str, Any]]:
    """observe kipinde BEYNİN (`actor: brain`, MCP aracı) oturuma dokunan çağrıları da uygulanmaz: aynı `would:`
    kaydı düşer, beyne başarılı-ama-kuru yanıt döner. İnsanın elle çağırdığı CLI/API (`actor` yok) her zaman uygulanır."""
    if data.get("actor") != "brain" or steward_config(sid).mode != "observe":
        return None
    _remember_dry(sw.Action(kind, name, "brain: " + str(data.get("reason") or "")[:200], {"text": str(data.get("text") or "")}),
                  _ctx(sid))
    return {"ok": True, "dry": True, "note": f"observe mode: recorded as would:{kind}, not applied"}


def _target(name: str, actor: str, projects: Optional[Dict[str, sw.Project]] = None,
            kind: str = "", sid: str = "default", world: Optional[sw.World] = None) -> Optional[Dict[str, Any]]:
    """Oturuma dokunan yolların TEK kapısı (docs/multi-steward-plan.md K5). `None` = izinli, aksi halde red yanıtı.
    Beyin (`actor: brain`, MCP) ve motor (`actor: engine`, `_apply`) YALNIZ KENDİ kimliğinin (`sid`) beyin oturumunu ve
    kayıtlı proje oturumlarını hedefleyebilir: başka kimliğin projesi/beyni, servis, çakışmalı proje ve kayıtsız (ad hoc)
    oturum reddedilir (çözüm global, `World.session_class`). İnsanın CLI/panel çağrısı (`actor` yok): `default` bağlamında
    kısıtsız (kayıtsız oturuma da yazabilir, bugünkü ad hoc davranış); diğer bağlamlarda yalnız o kimliğin kendi
    projeleri/beyni (plan (e) insan geçidi)."""
    if actor not in ("brain", "engine") and sid == "default":
        return None
    if name == steward_config(sid).brain_name:
        return None
    if sw.valid_name(name):
        if projects is None:
            projects = sw.load_projects(sid)
        if world is None:
            world = _world(sid)
        if _project_for_session(name, projects, world) is not None:
            return None
    sw.log_event("target_denied", paths=sid, actor=actor or "human", kind=kind, name=name)
    return {"ok": False, "error": "target denied: not the brain session or a registered steward project"}


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


# Kimliğin dokunamayacağı oturum sınıfları (`World.session_class`): başka kimliğin projesi, çakışmalı proje, servis, beyinler.
_FOREIGN = ("other", "conflict", "service", "brain_other", "brain_own")


def _project_for_session(name: str, projects: Dict[str, sw.Project],
                         world: Optional[sw.World] = None) -> Optional[sw.Project]:
    """Oturum adı → değnekçi projesi: tam ad, yoksa instance kaydının blueprint'i, yoksa base adı.
    `world` verilirse çözüm GLOBAL süzgeçten geçer (K4): ad (ya da blueprint) başka kimliğin projesine, çakışmalı
    projeye, servise ya da bir beyne çözülüyorsa None (`ncs` A'nın, `ncs2` B'nin iken `ncs2` oturumu `Session.base`
    ile A'nın `ncs`'ine İNMEZ). Tek kimlikte sonuç eskisiyle aynı."""
    rec = inst_mod.get_instance(name)
    p = None
    if name in projects:
        p = projects[name]
    elif rec and rec.get("blueprint") in projects:
        p = projects[rec["blueprint"]]
    else:
        from ..session import Session
        base = Session(name=name, pid=0).base
        if base in projects:
            p = projects[base]
        else:
            m = inst_mod.DERIVED_NAME_RE.match(name)     # rakamlı proje adı (wifi5gppr20261019): Session.base çözemez
            p = projects.get(m.group(1)) if m else None
    if p is None or world is None:
        return p
    return None if world.session_class(name, (rec or {}).get("blueprint")) in _FOREIGN else p


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
                    reason: str = "", session_name: str = "", cfg: Optional[sw.Config] = None) -> Dict[str, Any]:
    """`project`'e (ya da onun `session_name` adlı çalışan instance'ına) direktif gönder; kapalıysa aç.
    Proje değnekçi kaydında değilse (ad hoc oturum) sadece gönderir, kayıt açmaz. Kayıtlar `cfg.sid`'in deposuna."""
    cfg = cfg or steward_config()
    paths = sw.paths_for(cfg.sid)
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
    if project.name in sw.load_projects(paths):
        try:
            sw.upsert_project(project.name, paths=paths, last_visit=time.time(),
                              last_directive=(text or f"[{project.phase} şablonu]")[:400], visits=project.visits + 1)
        except ValueError as e:   # OwnedElsewhere: ad elle iki kimliğe yazılmış (çakışma); mesaj gitti, kayıt yazılmaz
            sw.log_event("directive_unrecorded", paths=paths, name=project.name, error=str(e))
    with sw.steward_lock(paths):
        state = sw.load_state(paths)
        state.setdefault("last_directive_at", {})[s.name] = time.time()
        sw.save_state(state, paths)
    if answer is not None:
        sw.mark_delivered(answer.id, paths)
    sw.log_event("directive", paths=paths, name=project.name, reason=reason, chars=len(message))
    return {"ok": True, "name": s.name, "chars": len(message)}


# ── proje kartları ────────────────────────────────────────────────────────────
#
# Çekirdek (`steward.py`): ham kart, prompt, ayrıştırma, yenileme kuralı. Burada: modeli çağıran tek seferlik
# özet (`summarize_card`), hangi projenin yenileneceği (`refresh_due_cards`) ve arka plan işi. Kart yenileme
# `_LOCK` ALTINDA DEĞİL: bir model çağrısı (10-60 sn) tick'i ve beynin MCP çağrılarını bekletmesin.

def oneshot_cwd() -> str:
    """Tek seferlik çağrıların NÖTR cwd'si (proje klasörü değil): CLAUDE.md/transkript projeye karışmasın."""
    return sw.paths_for().oneshot


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
    project = sw.load_projects(cfg.sid).get(name)
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
    sw.log_event("card", paths=cfg.sid, name=name, ok=ok, reason=reason, model=meta.get("model", ""),
                 cli=meta.get("cli", ""), secs=meta.get("secs", 0), error=meta.get("error", ""))
    return {"ok": ok, "name": name, "error": meta.get("error", ""), "model": meta.get("model", "")}


def _running_names_for(live: List[Any], projects: Dict[str, sw.Project], world: Optional[sw.World] = None) -> set:
    """Çalışan oturumların proje adları: tam ad + `Session.base` + değnekçi projesine eşleme. `Session.base` yalnız
    harften oluşan adları çözer (`wifi5gppr20261019` → kendisi), bu yüzden rakamlı proje adları "çalışmıyor" görünür
    ve uğrama sırası ikinci bir oturum açardı; `_project_for_session` blueprint/tarih sonekinden de çözer.
    `world` verilirse global çözümle uyumlu: oturum başka kimliğe çözülüyorsa (`ncs2` B'nin) tabanı (`ncs`, A'nın)
    "çalışıyor" sayılmaz."""
    out = {s.name for s in live}
    known = (set(world.owners) | set(world.conflicts)) if world is not None else set()
    for s in live:
        if world is None or s.base not in known or world.session_class(s.name) not in _FOREIGN:
            out.add(s.base)
        p = _project_for_session(s.name, projects, world)
        if p is not None:
            out.add(p.name)
    return out


def _running_project_names(sid: str = "default") -> set:
    return _running_names_for(find_sessions(measure_cpu=False), sw.load_projects(sid), _world(sid))


def refresh_due_cards(cfg: Optional[sw.Config] = None, limit: Optional[int] = None,
                      now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Kartı olmayan / bayat / kaynağı değişmiş / eskimiş, ÇALIŞMAYAN, aktif fazdaki projeleri yenile (en çok
    `limit`; None = `cards_per_tick`). Önce kartı hiç olmayanlar, sonra en eski kart. Çalışan proje atlanır:
    oturum yazarken kaynak zaten değişiyor (handover'dan sonra `mark_card_stale` ile işaretlenir).
    Projeler `cfg.sid`'in deposundan; default dışı kimlikte çakışmalı projeler atlanır (kimse yönetmez)."""
    cfg = cfg or steward_config()
    limit = cfg.cards_per_tick if limit is None else limit
    if limit <= 0:
        return []
    now = now if now is not None else time.time()
    projects = sw.load_projects(cfg.sid)
    if cfg.sid == "default":
        running = _running_project_names()
    else:
        projects = _world(cfg.sid, cfg).own_projects(projects)
        running = _running_project_names(cfg.sid)
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


def cards_round(cfgs: List[sw.Config]) -> bool:
    """Döngü turunun TEK kart işi (K7): kimlikler sırayla, `cards_per_tick` (makine geneli) bütçesi TÜM kimliklerde
    ortak. Tek kimlikte `card_tick(cfg)` ile aynı. İş zaten sürüyorsa False."""
    if not cfgs or not cfgs[0].card_refresh or cfgs[0].cards_per_tick <= 0:
        return False
    if len(cfgs) == 1:
        return card_tick(cfgs[0])

    def job() -> None:
        left = cfgs[0].cards_per_tick
        for c in cfgs:
            if left <= 0:
                break
            try:
                left -= len(refresh_due_cards(c, limit=left))
            except Exception as e:  # bir kimliğin kart adımı diğerlerini düşürmesin
                diag_log("steward_card_round_crashed", sid=c.sid, error=repr(e))
    return _run_cards_job(job)


# ── beyin ─────────────────────────────────────────────────────────────────────

def brain_spec(sid: str = "default") -> McpServerSpec:
    """Beynin MCP sunucusu: default argümansız (eski komut satırı), diğer kimlikler `--steward <sid>`."""
    from . import mcp_steward
    return mcp_steward.default_spec(sid)


def ensure_workspace(cfg: Optional[sw.Config] = None) -> str:
    """Kimliğin beyin cwd'sini (`paths_for(sid).workspace`) ve CLAUDE.md'sini hazırla. Persona: default `steward_persona_text`
    (yoksa paketlenmiş); diğer kimlik kendi `persona_text`i, boşsa ortak `steward_persona_text`. Default dışında kimlik
    bölümü eklenir, `MODEL_RULE_*` her kimliğin CLAUDE.md'sine girer."""
    cfg = cfg or steward_config()
    workspace = sw.paths_for(cfg.sid).workspace
    os.makedirs(workspace, exist_ok=True)
    shared = str(load_settings().get("steward_persona_text") or "")
    persona = sw.persona_text(shared if cfg.sid == "default" else (cfg.persona_text or shared))
    text = sw.build_workspace_claude_md(persona, lang=cfg.lang, sid=cfg.sid, label=cfg.label)
    path = os.path.join(workspace, "CLAUDE.md")
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
    """Kimliğin beynini aç (kendi workspace'i, `mcp-steward --steward <sid>`). Default dışı kimlik YALNIZ `enabled` iken
    açılır (hiçbir yeni kimlik kendiliğinden beyin açmaz; ayar varsayılan KAPALI); default'un davranışı eskisiyle aynı."""
    cfg = cfg or steward_config()
    if cfg.sid != "default" and not cfg.enabled:
        return {"ok": False, "error": f"steward {cfg.sid} is disabled; its brain is not started"}
    if _running(cfg.brain_name) is not None:
        return {"ok": True, "started": False, "name": cfg.brain_name}
    ensure_workspace(cfg)
    workspace = sw.paths_for(cfg.sid).workspace
    cli = cfg.brain_cli if cfg.brain_cli in PROVIDERS else DEFAULT_CLI
    provider = get_provider(cli)
    model = cfg.brain_model or default_model_for(provider)
    effort = cfg.brain_effort or default_effort_for(provider)
    mode = provider.permission_modes()[0] if provider.permission_modes() else "auto"
    inst_mod.record_instance(cfg.brain_name, blueprint=None, cwd=workspace, cli=cli, model=model,
                             permission_mode=mode, effort=effort, origin="steward")
    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
            kind = spawn_session(name=cfg.brain_name, cwd=workspace, model=model, display=detect_display(),
                                 permission_mode=mode, effort=effort, force_new=bool(fresh), cli=cli,
                                 mcp_server=brain_spec(cfg.sid))
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    inst_mod.mark_started(cfg.brain_name, cli=cli, model=model, permission_mode=mode, effort=effort)
    ready = _wait_ready(cfg.brain_name, cli)
    sw.log_event("brain_start", paths=cfg.sid, name=cfg.brain_name, kind=kind, ready=ready)
    return {"ok": True, "started": True, "name": cfg.brain_name, "kind": kind, "ready": ready}


def brain_stop(cfg: Optional[sw.Config] = None) -> Dict[str, Any]:
    cfg = cfg or steward_config()
    if _running(cfg.brain_name) is None:
        return {"ok": True, "stopped": False}
    res = _act("stop", cfg.brain_name, lang=cfg.lang)
    sw.log_event("brain_stop", paths=cfg.sid, name=cfg.brain_name, ok=bool(res.get("ok")))
    return res


def _enrich_item(it: Dict[str, Any], projects: Dict[str, sw.Project],
                 world: Optional[sw.World] = None) -> Dict[str, Any]:
    if it.get("kind") == "idea":
        return it
    name = it.get("name") or ""
    p = projects.get(name)
    s = _running(name)
    proj = p or (_project_for_session(s.name, projects, world) if s is not None else None)
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


def run_tour(items: Optional[List[Dict[str, Any]]] = None, force: bool = False,
             cfg: Optional[sw.Config] = None, world: Optional[sw.World] = None) -> Dict[str, Any]:
    """Beyne bir tur prompt'u gönder. `items` None ise şu anki gözden-geçirme maddeleri `review_items`'tan
    alınır (`force`: tour_minutes/beyin-boşta şartına bakılmaz, madde yoksa yine de "tur" gönderilir —
    kullanıcı bilerek istedi; beyin `steward_overview` ile kendi bakar). Beyin kapalıysa açılır.
    `cfg`/`world`: kimlik (verilmezse default); maddeler yalnız o kimliğin projelerinden."""
    cfg = cfg or steward_config()
    paths = sw.paths_for(cfg.sid)
    projects = sw.load_projects(paths)
    if world is None:
        world = _world(cfg.sid, cfg)
    if items is None:
        state = sw.load_state(paths)
        views = _collect_views(cfg)
        items = sw.review_items(views, projects, cfg, time.time(), sw.load_questions(paths), sw.load_ideas(paths),
                                skip=set(state.get("ho_pending") or {}),
                                last_directive_at=state.get("last_directive_at") or {},
                                reviewed_at=state.get("reviewed_at") or {}, world=world)
        if not items and not force:
            return {"ok": False, "error": "no review items right now"}
    res = brain_start(cfg)
    if not res.get("ok"):
        return res
    s = _running(cfg.brain_name)
    if s is None or not is_tmux_backed(s.pid):
        return {"ok": False, "error": "brain session not reachable"}
    enriched = [_enrich_item(it, projects, world) for it in items]
    prompt = sw.build_tour_prompt(enriched, lang=cfg.lang, open_qs=sw.open_questions(paths=paths), now=time.time())
    if not _send(s.name, s.cli, prompt):
        return {"ok": False, "error": "send failed"}
    with sw.steward_lock(paths):
        state = sw.load_state(paths)
        state["last_tour"] = time.time()
        sw.save_state(state, paths)
    sw.log_event("tour", paths=paths, items=len(enriched), chars=len(prompt))
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


def http_summary(date: str = "", lang: str = "", sid: str = "default") -> Dict[str, Any]:
    cfg = steward_config(sid)
    date = date or time.strftime("%Y-%m-%d")
    try:
        time.strptime(date, "%Y-%m-%d")
    except ValueError:
        return {"ok": False, "error": "date must be YYYY-MM-DD"}
    path = sw.daily_path(date, sid)
    return {"ok": True, "date": date, "text": sw.summary_text(date, lang if lang in ("tr", "en") else cfg.lang, sid),
            "saved": os.path.isfile(path), "path": path if os.path.isfile(path) else ""}


# ── eylem uygulama ────────────────────────────────────────────────────────────

def _apply(action: sw.Action, cfg: sw.Config, projects: Dict[str, sw.Project],
           world: Optional[sw.World] = None) -> Dict[str, Any]:
    """Tek eylemi uygula. Kayıtlar `cfg.sid`'in deposuna; oturuma dokunan eylemler `_target` kapısından (kimlikli)."""
    k = action.kind
    name = action.name
    paths = sw.paths_for(cfg.sid)
    if k in ("handover", "respawn", "stop"):   # deliver_answer kayıtsız oturuma da gider (cevap kaynağına); start zaten projects'e bağlı
        denied = _target(name, "engine", projects, k, sid=cfg.sid, world=world)
        if denied is not None:
            return denied
    if k == "handover":
        return _act("handover", name, lang=cfg.lang)
    if k == "respawn":
        if _running(name) is not None:
            res = _act("stop", name, lang=cfg.lang)
            if not res.get("ok"):
                return res
        if name == cfg.brain_name:
            return brain_start(cfg, fresh=True)   # devirden sonra YENİ konuşma (aynı şişmiş bağlam taşınmasın; notlar NOTLAR.md'de)
        p = _project_for_session(name, projects, world)
        model, effort = sw.phase_model_effort(p, cfg) if p else ("", "")
        # Devirden sonra YENİ konuşma (`--new`): `--resume` aynı şişmiş bağlamı (her tur yeniden okunan ~400K token)
        # ve eski modelin önbelleğini taşırdı. Devir özeti CLAUDE.md'de, yeni oturum onu kendisi okur.
        res = _ensure_running(name, model=model, effort=effort, lang=cfg.lang, fresh=True)
        if not res.get("ok") or p is None:
            return res
        sw.mark_card_stale(p.name)   # handover'da oturum işini yazdı: kart, proje durunca yeniden özetlensin
        return _give_directive(p, "", reason="respawn", session_name=name, cfg=cfg)
    if k == "start":
        p = projects.get(name)
        if p is None:
            return {"ok": False, "error": "not a steward project"}
        q = None
        if action.payload.get("question_id"):
            q = next((x for x in sw.load_questions(paths) if x.id == action.payload["question_id"]), None)
        return _give_directive(p, "", answer=q, reason=action.reason, cfg=cfg)
    if k == "stop":
        return _act("stop", name, lang=cfg.lang)
    if k == "deliver_answer":
        q = next((x for x in sw.load_questions(paths) if x.id == action.payload.get("question_id")), None)
        if q is None:
            return {"ok": False, "error": "question gone"}
        p = projects.get(q.project) or sw.Project(name=q.project)
        extra = "Cevaba göre devam et." if cfg.lang != "en" else "Continue according to the answer."
        res = _give_directive(p, extra, answer=q, start_if_stopped=False, reason="answer", session_name=name, cfg=cfg)
        if not res.get("ok") and q.project not in projects:
            # Kayıtlı proje olmayan (ad hoc) oturum kapanmış ya da yazı kabul etmiyor: her tick yeniden deneme,
            # bırak (cevap kayıtta durur, kimse beklemiyor).
            sw.mark_delivered(q.id, paths)
            sw.log_event("answer_undeliverable", paths=paths, id=q.id, session=name, error=res.get("error", ""))
        return res
    if k == "ask_user":
        q = sw.add_question(action.payload.get("project") or name, action.payload.get("text") or "", source=name,
                            routine=bool(action.payload.get("routine")), paths=paths)
        if q.status == "open" and q.routine:   # işleyiş sorusu: telefona gitmez, beynin turunda cevaplanır
            return {"ok": True, "id": q.id, "notified": False, "routine": True}
        if q.status != "open":   # yakın zamanda cevaplanmış soru yeniden soruldu: telefona yeni soru gitmez, cevap yeniden iletilir
            return {"ok": True, "id": q.id, "notified": False, "reasked": True}
        notified = notify_phone(f"[{q.project}] {q.text}\n→ py/cops steward answer {q.id} \"...\"")
        return {"ok": True, "id": q.id, "notified": notified}
    if k == "escalate_routine":
        q = sw.escalate_routine(action.payload.get("question_id") or "", paths)
        if q is None:
            return {"ok": False, "error": "not an open routine question"}
        notified = notify_phone(f"[{q.project}] {q.text}\n→ py/cops steward answer {q.id} \"...\"")
        return {"ok": True, "id": q.id, "notified": notified}
    if k == "idea":
        i = sw.add_idea(action.payload.get("text") or "", source=name, paths=paths)
        return {"ok": True, "id": i.id}
    if k == "set_phase":
        sw.upsert_project(name, paths=paths, phase=action.payload.get("phase"))
        return {"ok": True}
    if k == "tour":
        # default: eski çağrı biçimi; diğer kimlikte kimliğin cfg/world'ü açıkça verilir (kendi beyni, kendi projeleri)
        res = run_tour(action.payload.get("items") or [], **({} if cfg.sid == "default" else {"cfg": cfg, "world": world}))
        with sw.steward_lock(paths):
            state = sw.load_state(paths)
            if res.get("ok"):
                if state.get("tour_fail"):
                    state["tour_fail"] = 0
                    sw.save_state(state, paths)
                return res
            fails = int(state.get("tour_fail") or 0) + 1
            state["tour_fail"] = fails
            sw.save_state(state, paths)
        if fails >= TOUR_FAILS_BEFORE_RESTART:
            # Beynin giriş kutusu takılı (gönderilmemiş yapıştırma birikir): oturumu yeniden aç, sayacı sıfırla.
            sw.log_event("brain_unstick", paths=paths, fails=fails, error=res.get("error", ""))
            rb = brain_restart_for_stuck_input(cfg)
            with sw.steward_lock(paths):
                state = sw.load_state(paths)
                state["tour_fail"] = 0
                sw.save_state(state, paths)
            res = dict(res, restarted=bool(rb.get("ok")))
        return res
    return {"ok": False, "error": f"unknown action {k}"}


def _note_conflicts(ctx: StewardContext, index: Dict[str, Any], own_names: set, now: float) -> None:
    """Bu kimliğin `projects.json`'unda olup başka kimlikte de görünen adlar (elle düzenleme): ikisi de yönetmez
    (`World.own_projects` süzer). `ownership_conflict` olayı ad başına GÜNDE BİR; `ctx.conflicts` status uyarısı."""
    conflicts = index.get("conflicts") or {}
    mine = sorted(n for n in own_names if n in conflicts)
    ctx.conflicts = mine
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    for n in mine:
        if ctx.conflict_logged.get(n) != day:
            ctx.conflict_logged[n] = day
            sw.log_event("ownership_conflict", paths=ctx.paths, name=n, stewards=list(conflicts[n]))
            diag_log("steward_ownership_conflict", sid=ctx.sid, name=n, stewards=list(conflicts[n]))


def tick_once(trigger: str = "timer", sid: str = "default", *, starts_left: Optional[int] = None,
              cards: bool = True, index: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """`sid` kimliği için bir tick: görünümleri topla → kararlar (`plan_tick(world=...)`) → uygula → state kaydet.
    Elle (`/api/steward/tick`, `py/cops steward tick`) de çağrılır; döngü kapalıyken bile çalışır (kullanıcı bilerek
    istedi). Kilit KİMLİK BAŞINA (`ctx.lock`): A'nın tick'i B'nin elle eylemini bekletmez. Okuma/yazma yalnız
    `paths_for(sid)` yollarında. `starts_left`: döngü turunun kalan makine geneli başlatma hakkı (None = sınırsız,
    elle tick). `cards=False`: kart adımını çağıran yapar (döngü turu tek kart işi koşturur)."""
    ctx = _ctx(sid)
    with ctx.lock:
        cfg = steward_config(sid)
        paths = ctx.paths
        t0 = time.time()
        applied: List[Dict[str, Any]] = []
        dry_applied: List[Dict[str, Any]] = []
        started = 0
        error = ""
        try:
            projects = sw.load_projects(paths)
            idx = index if index is not None else _ownership_index()
            world = _world(sid, cfg, starts_left, idx)
            _note_conflicts(ctx, idx, set(projects), t0)
            views = _collect_views(cfg)
            with sw.steward_lock(paths):     # state RMW atomik (CLI süreci de aynı dosyaya yazar)
                actions, new_state = sw.plan_tick(views, projects, sw.load_state(paths), cfg, t0,
                                                  sw.load_questions(paths), sw.load_ideas(paths), world=world)
                actions, dry, new_state = sw.observe_filter(actions, cfg.mode, new_state, t0)
                sw.save_state(new_state, paths)
            for a in dry:
                _remember_dry(a, ctx)
                dry_applied.append({"kind": a.kind, "name": a.name, "reason": a.reason, "dry": True})
            for a in actions:
                if a.kind == "start":
                    started += 1      # deneme sayılır (başarısız açılış da bir spawn dalgası olabilir)
                try:
                    res = _apply(a, cfg, projects, world)
                except Exception as e:  # tek eylem tick'i düşürmesin
                    res = {"ok": False, "error": repr(e)}
                    diag_log("steward_action_crashed", sid=sid, kind=a.kind, name=a.name, error=repr(e))
                _remember(a, res, ctx)
                applied.append({"kind": a.kind, "name": a.name, "reason": a.reason, "ok": bool(res.get("ok")),
                                "detail": res.get("error") or ""})
        except Exception as e:
            error = repr(e)
            diag_log("steward_tick_crashed", sid=sid, error=repr(e))
        ctx.last_tick.update({"at": t0, "trigger": trigger, "actions": len(applied), "dry": len(dry_applied), "error": error})
        sw.log_event("tick", paths=paths, trigger=trigger, mode=cfg.mode, n=len(applied), dry=len(dry_applied), error=error)
        if applied:
            web_ws.notify_status_changed()
        if cfg.enabled and sid == "default":   # kimlik başına özet/compact P6'da
            try:
                maybe_daily_summary(cfg, t0)
            except Exception as e:
                diag_log("steward_summary_crashed", error=repr(e))
    if cards:
        try:
            card_tick(cfg)
        except Exception as e:
            diag_log("steward_card_tick_crashed", sid=sid, error=repr(e))
    return {"ok": not error, "error": error, "actions": applied, "dry": dry_applied, "mode": cfg.mode, "at": t0,
            "started": started}


def tick_round(trigger: str = "timer") -> List[Dict[str, Any]]:
    """Döngünün bir turu: `steward_ids()` sırasıyla, YALNIZ `enabled` kimlikler SIRAYLA tick'lenir (aynı anda tek spawn
    dalgası). Bir kimliğin hatası yutulup loglanır, diğerleri yine tick'lenir. Makine geneli `max_starts_total` bütçesi
    kimlikler arasında taşınır (`starts_left`); `max_active_total` her tick'in kendi görünümünden (diğer kimliklerin
    çalışan projeleri dahil) `plan_tick`'te uygulanır. Kart işi turda bir kez, tüm etkin kimlikler için."""
    base = steward_config()
    starts_left = max(0, base.max_starts_total)
    results: List[Dict[str, Any]] = []
    enabled: List[sw.Config] = []
    for sid in steward_ids():
        try:
            cfg = steward_config(sid)
            if not cfg.enabled:
                continue
            enabled.append(cfg)
            res = tick_once(trigger, sid, starts_left=starts_left, cards=False)
            starts_left = max(0, starts_left - int(res.get("started") or 0))
            results.append(dict(res, sid=sid))
        except Exception as e:   # bir kimlik diğerlerini atlatmasın
            diag_log("steward_tick_round_crashed", sid=sid, error=repr(e))
            results.append({"ok": False, "sid": sid, "error": repr(e)})
    try:
        cards_round(enabled)
    except Exception as e:
        diag_log("steward_card_tick_crashed", error=repr(e))
    return results


def _loop() -> None:
    while True:
        cfg = steward_config()
        time.sleep(max(15, cfg.tick_seconds))
        try:
            tick_round("timer")
        except Exception as e:
            diag_log("steward_loop_crashed", error=repr(e))


def start_loop() -> None:
    global _loop_started
    if _loop_started:
        return
    _loop_started = True
    threading.Thread(target=_loop, daemon=True, name="steward-loop").start()


# ── özet / HTTP ───────────────────────────────────────────────────────────────

_SUMMARY_TTL = 5.0


def summary(running_names: Optional[set] = None, sid: str = "default") -> Dict[str, Any]:
    """`/api/status`'a giden HAFİF alan (`orch` gibi local-only). ~2 sn'lik WS/poll cadence'ine bindiği için
    5 sn önbellekli (kimlik başına); `running_names` verilirse (status payload'ın kendi taraması) ayrıca proc taranmaz.
    `ownership_conflicts` yalnız çakışma varken eklenir (status uyarısı; tek kimlikte anahtarlar aynı kalır)."""
    ctx = _ctx(sid)
    cache = ctx.summary_cache
    now = time.monotonic()
    hit = cache["value"]
    if hit is not None and cache["until"] > now:
        return hit
    cfg = steward_config(sid)
    paths = ctx.paths
    projects = sw.load_projects(paths)
    questions = sw.load_questions(paths)
    state = sw.load_state(paths)
    brain_running = (cfg.brain_name in running_names) if running_names is not None else (_running(cfg.brain_name) is not None)
    value = {
        "enabled": cfg.enabled,
        "mode": cfg.mode,
        "tick_seconds": cfg.tick_seconds,
        "projects": sw.summarize_projects(projects),
        "open_questions": len(sw.open_questions(questions)),
        "ideas_new": sum(1 for i in sw.load_ideas(paths) if i.status == "new"),
        "pending_items": int(state.get("pending_items") or 0),
        "last_tick": dict(ctx.last_tick),
        "last_tour": state.get("last_tour") or 0.0,
        "brain": {"name": cfg.brain_name, "running": brain_running},
        "recent": ctx.recent[:5],
    }
    if ctx.conflicts:
        value["ownership_conflicts"] = list(ctx.conflicts)
    cache.update(until=now + _SUMMARY_TTL, value=value)
    return value


def invalidate_summary(sid: Optional[str] = None) -> None:
    """`sid` verilmezse TÜM kimliklerin özet önbelleği."""
    if sid:
        ctxs = [_ctx(sid)]
    else:
        with _CTX_GUARD:
            ctxs = list(_CTX.values())
    for ctx in ctxs:
        ctx.summary_cache["until"] = 0.0


def _project_dict(p: sw.Project, running: Optional[set] = None,
                  cards: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    d = dataclasses.asdict(p)
    if running is not None:
        d["running"] = p.name in running
    card = (cards if cards is not None else {p.name: sw.load_card(p.name)}).get(p.name) or {}
    d["next_step"] = sw.card_one_liner(card)
    d["card_updated_at"] = float(card.get("updated_at") or 0.0)
    return d


def http_state(sid: str = "default") -> Dict[str, Any]:
    ctx = _ctx(sid)
    cfg = steward_config(sid)
    paths = ctx.paths
    projects = sw.load_projects(paths)
    live = find_sessions(measure_cpu=False)
    running_projects = _running_names_for(live, projects, _world(sid, cfg))
    cards = sw.load_cards()
    return {
        "ok": True,
        "config": dataclasses.asdict(cfg),
        "summary": summary(sid=sid),
        "projects": [_project_dict(p, running_projects, cards)
                     for p in sorted(projects.values(), key=lambda p: (p.priority, p.name))],
        "running": [{"name": s.name, "cwd": s.cwd, "cli": s.cli, "model": s.model} for s in live],
        "questions": [dataclasses.asdict(q) for q in sw.open_questions(paths=paths)],
        "ideas": [dataclasses.asdict(i) for i in sw.load_ideas(paths) if i.status == "new"],
        "recent": ctx.recent,
    }


def http_projects(sid: str = "default") -> Dict[str, Any]:
    cards = sw.load_cards()
    return {"ok": True, "projects": [_project_dict(p, None, cards) for p in sw.load_projects(sid).values()]}


def http_questions(status: str = "open", sid: str = "default") -> Dict[str, Any]:
    qs = sw.load_questions(sid)
    if status == "open":
        qs = [q for q in qs if q.status == "open"]
    elif status == "answered":
        qs = [q for q in qs if q.status == "answered"]
    return {"ok": True, "questions": [dataclasses.asdict(q) for q in qs]}


def http_ideas(status: str = "new", sid: str = "default") -> Dict[str, Any]:
    ideas = sw.load_ideas(sid)
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


def http_idea_export(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Fikri projenin `TODO.md`/`TOBEDECIDED.md` dosyasına yazar. `kind`: todo|tbd; `target`: project (fikrin projesi) |
    all (kayıtlı tüm değnekçi projeleri). Fikir `exported` olur (listeden kalkar), kayıt fikrin üstünde durur."""
    kind = str(data.get("kind") or "")
    target = str(data.get("target") or "project")
    fname = _EXPORT_FILES.get(kind)
    if fname is None:
        return {"ok": False, "error": "kind must be todo or tbd"}
    if target not in ("project", "all"):
        return {"ok": False, "error": "target must be project or all"}
    idea = next((i for i in sw.load_ideas(sid) if i.id == str(data.get("id") or "")), None)
    if idea is None:
        return {"ok": False, "error": "unknown idea id"}
    projects = sw.load_projects(sid)
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
    sw.record_idea_export(idea.id, {"kind": kind, "target": target, "file": fname, "projects": written + present, "at": time.time()},
                          sid)
    sw.log_event("idea_export", paths=sid, id=idea.id, kind=kind, target=target, written=written, present=present, skipped=skipped)
    return {"ok": True, "written": written, "already": present, "skipped": skipped}


def http_log(n: int = 50, sid: str = "default") -> Dict[str, Any]:
    return {"ok": True, "entries": sw.tail_log(max(1, min(500, n)), sid)}


_NOT_OWN_PROJECT = {"ok": False, "error": "not a project of this steward"}


def _read_denied(name: str, sid: str) -> Optional[Dict[str, Any]]:
    """Okuma kapısı (plan (k)5): default dışı kimlik yalnız KENDİ projelerini okur (başka kimliğin projesi, servis,
    beyin, kayıtsız oturum red). `default` bugünkü gibi kısıtsız (insan/eski beyin)."""
    if sid == "default":
        return None
    if _project_for_session(name, sw.load_projects(sid), _world(sid)) is None:
        return dict(_NOT_OWN_PROJECT)
    return None


def http_context(name: str, docs: bool = False, sid: str = "default") -> Dict[str, Any]:
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    denied = _read_denied(name, sid)
    if denied is not None:
        return denied
    projects = sw.load_projects(sid)
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
    owner = _project_for_session(name, projects, _world(sid))
    card = sw.load_card(owner.name if owner is not None else name)
    if card is not None:
        out["card"] = card
        out["card_stale"] = bool(card.get("stale"))
    if card is None or docs:    # kart varsa ham belge başları yerine kart; `docs=1` ikisini birden ister
        out["docs"] = {d: _read_head(cwd, d) for d in DOCS if cwd} if cwd else {}
        out["docs"] = {k: v for k, v in out["docs"].items() if v}
    out["git"] = _git_short(cwd)
    out["questions"] = [dataclasses.asdict(q) for q in sw.load_questions(sid) if q.project == name and q.status == "open"]
    return out


def http_file(name: str, rel: str, max_chars: int = MAX_FILE_READ_CHARS, sid: str = "default") -> Dict[str, Any]:
    denied = _read_denied(name, sid) if sw.valid_name(name) else None
    if denied is not None:
        return denied
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


def http_project_upsert(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    fields = {k: data.get(k) for k in ("phase", "kind", "goal", "priority", "cadence_minutes", "notes", "model", "effort")
              if k in data}
    try:
        p = sw.upsert_project(name, paths=sid, **fields)
    except ValueError as e:      # OwnedElsewhere / ReservedName mesajı olduğu gibi
        return {"ok": False, "error": str(e)}
    sw.log_event("project_set", paths=sid, name=name, fields=sorted(fields))
    out = {"ok": True, "project": _project_dict(p)}
    warning = _prefix_warning(name, sid)
    if warning:
        out["warning"] = warning
    return out


def _prefix_warning(name: str, sid: str = "default", index: Optional[Dict[str, Any]] = None) -> str:
    """Ad başka kimliğin bir proje adının öneki/uzantısıysa (`ncs` / `ncs2`) uyarı metni, değilse "". Kabul edilir
    (oturum adları tüm kimliklerde en uzun önekle GLOBAL çözülür, K4) ama kullanıcı karışıklığı bilsin."""
    idx = index if index is not None else _ownership_index()
    hits = sorted(f"{p} ({s})" for p, s in (idx.get("owners") or {}).items()
                  if s != sid and p != name and (p.startswith(name) or name.startswith(p)))
    if not hits:
        return ""
    return ("name shares a prefix with project(s) of other stewards: " + ", ".join(hits)
            + "; sessions resolve to the longest matching project name across all stewards")


def http_project_remove(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    return {"ok": sw.remove_project(name, sid)}


def http_register(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Yeni proje: klasör (yoksa oluştur + git init), GOAL.md (amaç + kaynaklar), yerel kaynak dosyalarını
    `kaynaklar/`a kopyala, roster'a kaydet (`web._register_project`), değnekçi kaydını aç."""
    cfg = steward_config(sid)
    name = str(data.get("name") or "").strip()
    cwd = os.path.expanduser(str(data.get("cwd") or "").strip())
    goal = str(data.get("goal") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    if not cwd or not os.path.isabs(cwd):
        return {"ok": False, "error": "cwd must be an absolute path"}
    # Talep ÖNCE denetlenir (klasör/GOAL.md/roster yan etkilerinden önce): başka kimliğin adı ya da rezerve ad reddedilir.
    paths = sw.paths_for(cfg.sid)
    other = sw.project_owner(name, exclude=cfg.sid)
    if other:
        return {"ok": False, "error": str(sw.OwnedElsewhere(name, other))}
    idx = _ownership_index(fresh=True)
    if name not in sw.load_projects(paths):
        why = sw.reserved_reason(name, idx)
        if why:
            return {"ok": False, "error": str(sw.ReservedName(name, why))}
    warning = _prefix_warning(name, cfg.sid, idx)
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
    try:
        p = sw.upsert_project(name, paths=paths, phase=phase, kind=data.get("kind") or "", goal=goal,
                              priority=data.get("priority"), cadence_minutes=data.get("cadence_minutes"))
    except ValueError as e:     # yarış: denetimden sonra başka kimlik talep etti (OwnedElsewhere) ya da rezerve
        return {"ok": False, "error": str(e), "cwd": cwd, "copied": copied, "roster": reg}
    idea_id = str(data.get("idea_id") or "")
    if idea_id:
        sw.update_idea(idea_id, status="project", project=name, paths=paths)
    sw.log_event("project_register", paths=paths, name=name, cwd=cwd, copied=copied, listed=len(listed))
    out = {"ok": True, "project": _project_dict(p), "cwd": cwd, "copied": copied, "roster": reg}
    if warning:
        out["warning"] = warning
    return out


def http_ask(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Soru aç (+ `options`: en çok 6 kısa seçenek) → ntfy: metin + numaralı seçenekler + `/q/<id>?k=` bağlantısı
    (tünel varsa; bildirime dokunmak sayfayı açar). Aynı açık soru ikinci kez bildirilmez (`add_question` dedup)."""
    cfg = steward_config(sid)
    try:
        q = sw.add_question(str(data.get("project") or ""), str(data.get("text") or ""),
                            source=str(data.get("source") or "api"), options=data.get("options"), paths=sid)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    link = sw.question_link(q, public_base())
    if q.notified_at:
        return {"ok": True, "id": q.id, "notified": False, "link": link, "dup": True}
    notified = notify_phone(sw.question_notification(q, link, cfg.lang), click=link)
    if notified:
        sw.mark_notified(q.id, sid)
    sw.log_event("ask", paths=sid, id=q.id, project=q.project, notified=notified, options=len(q.options))
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


def http_answer(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    try:
        q = sw.answer_question(str(data.get("id") or ""), str(data.get("answer") or ""), sid)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if q is None:
        return {"ok": False, "error": "unknown question id"}
    sw.log_event("answer", paths=sid, id=q.id, project=q.project)
    return {"ok": True, "question": dataclasses.asdict(q)}


def http_idea(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    if data.get("id"):
        i = sw.update_idea(str(data["id"]), status=data.get("status"), project=data.get("project"), paths=sid)
        if i is None:
            return {"ok": False, "error": "unknown idea id"}
        sw.log_event("idea_update", paths=sid, id=i.id, status=i.status, project=i.project)
        return {"ok": True, "idea": dataclasses.asdict(i)}
    try:
        i = sw.add_idea(str(data.get("text") or ""), source=str(data.get("source") or "api"), paths=sid)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    sw.log_event("idea", paths=sid, id=i.id)
    return {"ok": True, "idea": dataclasses.asdict(i)}


def http_note(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("project") or data.get("name") or "").strip()
    text = str(data.get("text") or "").strip()
    if not sw.valid_name(name) or not text:
        return {"ok": False, "error": "project and text are required"}
    p = sw.load_projects(sid).get(name)
    if p is None:
        return {"ok": False, "error": "not a steward project"}
    sw.upsert_project(name, paths=sid, notes=text)
    sw.log_event("note", paths=sid, name=name, chars=len(text))
    return {"ok": True}


def http_directive(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    text = str(data.get("text") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    denied = _target(name, str(data.get("actor") or ""), kind="directive", sid=sid)
    if denied is not None:
        return denied
    dry = _brain_dry("directive", data, name, sid)
    if dry is not None:
        return dry
    with _ctx(sid).lock:
        projects = sw.load_projects(sid)
        p = _project_for_session(name, projects, _world(sid))
        if p is None:
            if _running(name) is None and not inst_mod.get_instance(name) and name not in (_act("fleet_status") or {}):
                return {"ok": False, "error": "unknown session/project"}
            p = sw.Project(name=name)   # ad hoc: kayıt açmadan sadece gönder
        return _give_directive(p, text, model=str(data.get("model") or ""), effort=str(data.get("effort") or ""),
                               start_if_stopped=bool(data.get("start_if_stopped", True)),
                               reason=str(data.get("reason") or "brain"), session_name=name, cfg=steward_config(sid))


def http_restart(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    cfg = steward_config(sid)
    denied = _target(name, str(data.get("actor") or ""), kind="restart", sid=sid)
    if denied is not None:
        return denied
    dry = _brain_dry("restart", data, name, sid)
    if dry is not None:
        return dry
    with _ctx(sid).lock:      # yeniden girişli: içerideki http_directive aynı kilidi yeniden alır
        if _running(name) is not None:
            res = _act("stop", name, lang=cfg.lang)
            if not res.get("ok"):
                return res
        sw.log_event("restart", paths=sid, name=name, reason=str(data.get("reason") or ""))
        return http_directive(dict(data, start_if_stopped=True, reason="restart: " + str(data.get("reason") or "")), sid)


def http_stop(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    cfg = steward_config(sid)
    denied = _target(name, str(data.get("actor") or ""), kind="stop", sid=sid)
    if denied is not None:
        return denied
    dry = _brain_dry("stop", data, name, sid)
    if dry is not None:
        return dry
    with _ctx(sid).lock:
        res = _act("stop", name, lang=cfg.lang)
    sw.log_event("stop", paths=sid, name=name, reason=str(data.get("reason") or ""), ok=bool(res.get("ok")))
    return res


def http_handover(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    cfg = steward_config(sid)
    denied = _target(name, str(data.get("actor") or ""), kind="handover", sid=sid)
    if denied is not None:
        return denied
    dry = _brain_dry("handover", data, name, sid)
    if dry is not None:
        return dry
    with _ctx(sid).lock:
        res = _act("handover", name, lang=cfg.lang)
        if res.get("ok"):
            with sw.steward_lock(sid):
                state = sw.load_state(sid)
                state.setdefault("ho_pending", {})[name] = time.time()
                sw.save_state(state, sid)
    sw.log_event("handover", paths=sid, name=name, ok=bool(res.get("ok")))
    return res


def http_skip(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    sw.log_event("skip", paths=sid, name=name, reason=str(data.get("reason") or ""))
    with sw.steward_lock(sid):
        state = sw.load_state(sid)
        state.setdefault("last_directive_at", {})[name] = time.time()   # bir sonraki `idle` maddesini erteler
        sw.save_state(state, sid)
    return {"ok": True}


def http_brain(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    action = str(data.get("action") or "start")
    cfg = steward_config(sid)
    with _ctx(sid).lock:
        return brain_start(cfg) if action == "start" else brain_stop(cfg)


def http_cards(sid: str = "default") -> Dict[str, Any]:
    projects = sw.load_projects(sid)
    cards = sw.load_cards()
    return {"ok": True, "cards": [dict(c, name=n) for n, c in sorted(cards.items())],
            "missing": sorted(n for n, p in projects.items() if p.phase in sw.ACTIVE_PHASES and n not in cards),
            "busy": _CARD_LOCK.locked()}


def http_card(name: str, sid: str = "default") -> Dict[str, Any]:
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    if sid != "default" and name not in sw.load_projects(sid):
        return dict(_NOT_OWN_PROJECT)
    card = sw.load_card(name)
    return {"ok": True, "name": name, "card": card} if card is not None else {"ok": False, "error": "no card"}


def http_cards_refresh(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Kartları şimdi yenile (arka planda; model çağrısı panelin 15 sn'lik API zaman aşımını aşabilir, sonuç
    `py/cops steward cards` / `log`ta). `name` verilirse O proje (çalışıyor olsa da, kaynak değişmemiş olsa da);
    verilmezse yenilemesi GEREKEN tüm çalışmayan aktif projeler (tick başına sınırı yok)."""
    cfg = steward_config(sid)
    name = str(data.get("name") or "").strip()
    if name:
        if not sw.valid_name(name):
            return {"ok": False, "error": "invalid name"}
        if name not in sw.load_projects(sid):
            return {"ok": False, "error": "not a steward project"}
        job = lambda: refresh_card(name, cfg, reason="manual")   # noqa: E731
    else:
        job = lambda: refresh_due_cards(cfg, limit=10 ** 6)   # noqa: E731
    if not _run_cards_job(job):
        return {"ok": False, "error": "a card refresh is already running"}
    return {"ok": True, "queued": name or "due"}


class UnknownSteward(ValueError):
    """İstekte verilen `steward` kimliği geçersiz ya da ayarda tanımlı değil."""


def _ctx_for(src: Any) -> StewardContext:
    """HTTP isteğinin değnekçi bağlamı. `src`: JSON gövdesi (dict) ya da sorgu (`{anahtar: [değer]}`). `steward` yoksa/boşsa
    `default` (eski MCP/UI/CLI aynen çalışır). Geçersiz biçim ya da ayarda tanımlı olmayan kimlik `UnknownSteward`
    (sessizce `default`a DÜŞMEZ: başka değnekçinin deposuna yazılmasın)."""
    raw = src.get("steward") if isinstance(src, dict) else None
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if raw is None or raw == "":
        return _ctx("default")
    if not isinstance(raw, str):
        raise UnknownSteward("unknown steward")
    sid = raw.strip()
    if sid != "default" and (not sw.valid_steward_id(sid) or sid not in steward_ids()):
        raise UnknownSteward("unknown steward")
    return _ctx(sid)


def _unknown_steward() -> Dict[str, Any]:
    return {"ok": False, "error": "unknown steward"}


_GET_PATHS = frozenset(("state", "projects", "questions", "ideas", "log", "context", "summary", "cards", "card", "file"))


def http_get(path: str, qs: Dict[str, List[str]]) -> Optional[Dict[str, Any]]:
    """`web.py` do_GET: `/api/steward/*` → dict (bilinmeyen alt yol → None = 404). `?steward=<sid>` kimliği seçer
    (yoksa `default`); bilinmeyen kimlik `{"ok": false, "error": "unknown steward"}`."""
    g = lambda k, d="": (qs.get(k) or [d])[0]
    if not path.startswith("/api/steward/") or path[len("/api/steward/"):] not in _GET_PATHS:
        return None
    try:
        sid = _ctx_for(qs).sid
    except UnknownSteward:
        return _unknown_steward()
    if path == "/api/steward/state":
        return http_state(sid)
    if path == "/api/steward/projects":
        return http_projects(sid)
    if path == "/api/steward/questions":
        return http_questions(g("status", "open"), sid)
    if path == "/api/steward/ideas":
        return http_ideas(g("status", "new"), sid)
    if path == "/api/steward/log":
        try:
            return http_log(int(g("n", "50")), sid)
        except ValueError:
            return http_log(sid=sid)
    if path == "/api/steward/context":
        return http_context(g("name").strip(), docs=g("docs") in ("1", "true"), sid=sid)
    if path == "/api/steward/summary":
        return http_summary(g("date").strip(), g("lang").strip(), sid)
    if path == "/api/steward/cards":
        return http_cards(sid)
    if path == "/api/steward/card":
        return http_card(g("name").strip(), sid)
    if path == "/api/steward/file":
        try:
            mx = int(g("max", str(MAX_FILE_READ_CHARS)))
        except ValueError:
            mx = MAX_FILE_READ_CHARS
        return http_file(g("name").strip(), g("path").strip(), max(1, min(mx, MAX_FILE_READ_CHARS)), sid)
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
    "/api/steward/tick": lambda data, sid="default": tick_once("manual", sid),
    "/api/steward/tour": lambda data, sid="default": run_tour(force=True, cfg=steward_config(sid)),
}


def http_post(path: str, data: Dict[str, Any], qs: Optional[Dict[str, List[str]]] = None) -> Optional[Dict[str, Any]]:
    """`steward` kimliği JSON gövdesinden, yoksa sorgudan (`qs`, `web.py` verir); ikisi de yoksa `default`."""
    fn = POST_PATHS.get(path)
    if fn is None:
        return None
    data = data if isinstance(data, dict) else {}
    try:
        try:
            sid = _ctx_for(data if data.get("steward") not in (None, "") else (qs or {})).sid
        except UnknownSteward:
            return _unknown_steward()
        return fn(data, sid=sid)
    finally:
        invalidate_summary()
