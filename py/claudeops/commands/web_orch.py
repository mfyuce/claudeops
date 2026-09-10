"""TOBEDECIDED#15 Phase 1 — run engine: bir görevi worker session'lara
dağıt, yanıtları bekle, consensus'u çöz. Bu geçişte SADECE worker rolü var
(controller/decider/briefing/handoff/MCP — Phase 2/3, bkz. onaylanmış plan
`~/.claude/plans/idempotent-riding-key.md`).

`web.py`'nin `_v1_eligible_sessions()`'ıyla AYNI uygunluk üçlüsünü
(çalışıyor + tmux-backed + `has_conversation()`) kendi başına tekrar
uyguluyor — `web.py`'yi import ETMİYORUZ (o bizi import ediyor, döngüsel
import riski). `if cli == ...` YOK: provider arayüzünden geçiyor.
"""
from __future__ import annotations
import concurrent.futures
import dataclasses
import os
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import orchestration as orch
from .. import orch_store
from .. import turns
from ..diaglog import diag_log
from ..discovery import find_sessions
from ..providers import get_provider
from ..tmux_backend import is_tmux_backed, tmux_send_keys
from . import web_ws

MAX_PARALLEL_WORKERS = 4
DEFAULT_WORKER_TIMEOUT_SECONDS = 900.0
# Phase 0 spike'ının bulduğu GERÇEK bir sınır (spekülatif değil): ~4150
# karakterlik bir prompt codex'i ÇÖKERTİYOR (4 denemede 4/4, 2 model) — küçük
# çok-satırlı prompt'lar sorunsuz, kırılma SADECE boyutla ilgili. Bu yüzden
# bu eşik worker-dispatch prompt'unun KENDİSİNE uygulanıyor, sadece plan'ın
# bahsettiği ileriki bir decider-bundle'a değil.
INLINE_LIMIT_CHARS = 4000
INLINE_HEAD_CHARS = 2000

_LOCK = threading.Lock()
_ACTIVE_RUN_ID: Optional[str] = None
_CANCEL_EVENTS: Dict[str, threading.Event] = {}


def _new_run_id() -> str:
    return "r" + time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)


def _eligible_index() -> Dict[Tuple[str, str], Any]:
    """(host, name) → canlı Session. `_v1_eligible_sessions()` (web.py) ile
    AYNI üçlü, sadece SÖZLÜK olarak (participant çözümlemesi isim-bazlı) —
    v1 kapsamı: SADECE local (uzak host session'ları burada asla görünmez,
    `_preflight` ayrıca host!=local'ı erken/net bir mesajla reddeder)."""
    out: Dict[Tuple[str, str], Any] = {}
    for s in find_sessions(measure_cpu=False):
        if not is_tmux_backed(s.pid):
            continue
        if not get_provider(s.cli).has_conversation():
            continue
        out[("local", s.name)] = s
    return out


def _preflight(participants: List[dict]) -> Optional[str]:
    """None = OK, aksi halde düz-metin hata (henüz TR/EN localize edilmedi —
    bu geçiş backend-only, tüketen bir UI yok; frontend eklenince ERR
    tablosuna taşınabilir, bkz. plan'ın listelediği `orch_*` anahtarları).
    Hiçbir ihlalde KISMİ başlatma yok — ya hepsi geçer ya hiçbir mesaj gitmez."""
    if not participants:
        return "no participants given"
    workers = [p for p in participants if p.get("role") == "worker"]
    controllers = [p for p in participants if p.get("role") == "controller"]
    deciders = [p for p in participants if p.get("role") == "decider"]
    if controllers or deciders:
        return "controller/decider roles aren't wired up yet — Phase 1 supports workers only"
    if not workers:
        return "at least one worker is required"

    index = _eligible_index()
    seen_triples = set()
    for p in workers:
        host = str(p.get("host") or "local")
        name = str(p.get("name") or "").strip()
        if not name:
            return "a participant is missing a name"
        if host != "local":
            return f"'{name}': remote-host participants aren't supported yet (TOBEDECIDED#20)"
        s = index.get((host, name))
        if s is None:
            return f"'{name}': not an eligible running session (must be running, tmux-backed, and hold a conversation)"
        triple = (host, s.cli, s.cwd)
        if triple in seen_triples:
            return f"'{name}': shares (host, cli, cwd) with another participant — their replies would be indistinguishable"
        seen_triples.add(triple)
    return None


def _build_dispatch_prompt(run_id: str, task: str, verdict_hint: str) -> str:
    """Tam prompt (task+hint+contract) `INLINE_LIMIT_CHARS`'ı aşarsa TAMAMI
    run dizinine dosya olarak yazılır + kısa bir baş kısım + İŞARETÇİ +
    contract enjekte edilir (contract HER ZAMAN bütün kalır — kesinlikle
    kısaltılmaz, aksi halde worker kendi verdict biçimini hiç görmez)."""
    full = orch.build_worker_prompt(task, verdict_hint)
    if len(full) <= INLINE_LIMIT_CHARS:
        return full
    d = orch_store.run_dir(run_id)
    os.makedirs(d, exist_ok=True)
    fpath = os.path.join(d, "task.md")
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(full)
    head = task.strip()[:INLINE_HEAD_CHARS]
    return (
        f"{head}\n\n[... task truncated for delivery size (a large paste has been observed to crash "
        f"one of this fleet's CLIs) — the complete text is at {fpath}, read it if you need the rest "
        f"before answering ...]\n\n{orch.verdict_contract()}"
    )


def _one_worker(w: orch.Participant, seq: int, index: Dict[Tuple[str, str], Any],
                 prompt: str, worker_timeout: float, cancel_event: threading.Event) -> orch.RunResult:
    created_at = time.time()
    s = index.get((w.host, w.name))
    if s is None:
        return orch.RunResult(seq=seq, kind="worker_result", role="worker", host=w.host, name=w.name,
                               cli=w.cli, created_at=created_at, status="unreachable")
    provider = get_provider(s.cli)
    baseline = provider.last_exchange(s.cwd, s.sid)
    if baseline is None:
        return orch.RunResult(seq=seq, kind="worker_result", role="worker", host=w.host, name=w.name,
                               cli=w.cli, created_at=created_at, status="unreachable")
    # Fresh/hiç resume edilmemiş agy session'ı — 2026-09-09 commit `1356edc`
    # ile AYNI fallback (bkz. `turns.wait_for_reply` docstring'i).
    live_snapshot = provider.snapshot_for_live_sid(s.cwd) if s.sid is None else None

    t0 = time.monotonic()
    diag_log("orch_worker_dispatch", name=s.name, seq=seq, chars=len(prompt))
    if not tmux_send_keys(s.name, prompt, settle_delay=provider.input_settle_delay()):
        return orch.RunResult(seq=seq, kind="worker_result", role="worker", host=w.host, name=w.name,
                               cli=w.cli, created_at=created_at, status="send_failed")

    reply = turns.wait_for_reply(
        s, provider, baseline, live_snapshot,
        timeout=worker_timeout, poll=1.0, stable_polls=3,
        require_marker=orch.END_MARKER, cancel=cancel_event,
    )
    elapsed = time.monotonic() - t0
    if reply is None:
        return orch.RunResult(seq=seq, kind="worker_result", role="worker", host=w.host, name=w.name,
                               cli=w.cli, created_at=created_at, status="timeout", elapsed=elapsed)

    verdict_raw = orch.parse_verdict(reply)
    if verdict_raw is None:
        return orch.RunResult(seq=seq, kind="worker_result", role="worker", host=w.host, name=w.name,
                               cli=w.cli, created_at=created_at, status="no_envelope", text=reply, elapsed=elapsed)
    return orch.RunResult(seq=seq, kind="worker_result", role="worker", host=w.host, name=w.name,
                           cli=w.cli, created_at=created_at, status="ok", text=reply, elapsed=elapsed,
                           verdict=verdict_raw, verdict_key=orch.normalize_verdict(verdict_raw))


def _save_progress(run_id: str, results: List[orch.RunResult]) -> None:
    run = orch_store.load_run(run_id)
    if run is None:
        return
    run["results"] = [dataclasses.asdict(r) for r in sorted(results, key=lambda r: r.seq)]
    run["updated_at"] = time.time()
    orch_store.save_run(run)
    web_ws.notify_status_changed()


def _save_final(run_id: str, results: List[orch.RunResult], outcome: orch.Outcome, status: str) -> None:
    run = orch_store.load_run(run_id) or {"id": run_id}
    run["results"] = [dataclasses.asdict(r) for r in sorted(results, key=lambda r: r.seq)]
    run["outcome"] = dataclasses.asdict(outcome)
    run["status"] = status
    run["updated_at"] = time.time()
    orch_store.save_run(run)
    web_ws.notify_status_changed()


def _run_thread(run_id: str, workers: List[orch.Participant], task: str, verdict_hint: str,
                 worker_timeout: float, cancel_event: threading.Event) -> None:
    global _ACTIVE_RUN_ID
    try:
        prompt = _build_dispatch_prompt(run_id, task, verdict_hint)
        index = _eligible_index()
        results: List[orch.RunResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_WORKERS, len(workers))) as ex:
            futures = {ex.submit(_one_worker, w, i + 1, index, prompt, worker_timeout, cancel_event): w
                       for i, w in enumerate(workers)}
            for fut in concurrent.futures.as_completed(futures):
                results.append(fut.result())
                _save_progress(run_id, results)
        outcome = orch.resolve_outcome(results, has_decider=False)
        status = "cancelled" if cancel_event.is_set() else (
            "done" if outcome.method in ("unanimous", "majority", "single_worker") else "needs_human"
        )
        _save_final(run_id, results, outcome, status)
    except Exception as e:
        # Thread'in sessizce ölmesi `_ACTIVE_RUN_ID`'yi SONSUZA kadar meşgul
        # bırakırdı (bir sonraki `start_run` hep "zaten aktif" derdi) — bu
        # yüzden geniş bir yakalama burada BİLEREK var, engine'in geri
        # kalanında YOK.
        diag_log("orch_run_crashed", run_id=run_id, error=str(e))
        _save_final(run_id, [], orch.Outcome(method="none", note=f"internal error: {e}"), "failed")
    finally:
        with _LOCK:
            if _ACTIVE_RUN_ID == run_id:
                _ACTIVE_RUN_ID = None
            _CANCEL_EVENTS.pop(run_id, None)


def start_run(participants: List[dict], task: str, verdict_hint: str = "",
              worker_timeout: float = DEFAULT_WORKER_TIMEOUT_SECONDS, lang: str = "tr") -> Tuple[Optional[str], Optional[str]]:
    """(run_id, None) ya da (None, hata-metni). Preflight'ı geçerse dispatch
    thread'ini başlatıp HEMEN döner — asıl bekleme thread'in içinde olur."""
    global _ACTIVE_RUN_ID
    del lang  # şimdilik kullanılmıyor (yerelleştirme henüz yok, imza ileriye dönük tutuldu)
    task = (task or "").strip()
    if not task:
        return None, "task is required"
    err = _preflight(participants)
    if err:
        return None, err

    with _LOCK:
        if _ACTIVE_RUN_ID is not None:
            active = orch_store.load_run(_ACTIVE_RUN_ID)
            if active and active.get("status") in ("briefing", "working", "deciding"):
                return None, f"a run is already active ({_ACTIVE_RUN_ID}) — cancel it or wait for it to finish"
        run_id = _new_run_id()
        _ACTIVE_RUN_ID = run_id
        cancel_event = threading.Event()
        _CANCEL_EVENTS[run_id] = cancel_event

    index = _eligible_index()
    workers = []
    for p in participants:
        if p.get("role") != "worker":
            continue
        host = str(p.get("host") or "local")
        name = str(p.get("name") or "").strip()
        s = index.get((host, name))
        workers.append(orch.Participant(role="worker", host=host, name=name, cli=(s.cli if s else "")))

    run = orch.Run(id=run_id, created_at=time.time(), updated_at=time.time(), status="working",
                    lang="tr", task=task, verdict_hint=verdict_hint or "", worker_timeout=worker_timeout,
                    participants=workers)
    orch_store.save_run(run)
    web_ws.notify_status_changed()

    t = threading.Thread(target=_run_thread, args=(run_id, workers, task, verdict_hint, worker_timeout, cancel_event),
                          daemon=True, name=f"orch-{run_id}")
    t.start()
    return run_id, None


def cancel_run(run_id: str) -> Tuple[bool, Optional[str]]:
    ev = _CANCEL_EVENTS.get(run_id)
    if ev is None:
        return False, "no active run with that id (already finished, or never started)"
    ev.set()
    return True, None


def get_run(run_id: str) -> Optional[dict]:
    return orch_store.load_run(run_id)


def list_runs(limit: int = 20) -> List[dict]:
    return orch_store.list_runs(limit)


def save_draft(participants: List[dict]) -> None:
    orch_store.save_draft(participants)


def get_draft() -> List[dict]:
    return orch_store.load_draft()


def active_summary() -> Optional[dict]:
    """`_status_payload()`'ın `orch` bloğu için hafif bir görünüm — TAM
    sonuç metni YOK (2s WS/poll cadence'ine biniyor), sadece faz/katılımcı
    özeti."""
    if _ACTIVE_RUN_ID is None:
        return None
    run = orch_store.load_run(_ACTIVE_RUN_ID)
    if run is None:
        return None
    return {
        "id": run.get("id"), "status": run.get("status"), "task_head": (run.get("task") or "")[:120],
        "participants": [{"host": p.get("host"), "name": p.get("name"), "cli": p.get("cli"), "role": p.get("role")}
                          for p in run.get("participants", [])],
        "result_count": len(run.get("results", [])),
    }


# ── HTTP handler'ları (web.py'nin do_GET/do_POST'undan çağrılır) ──────────

def http_start(data: dict) -> dict:
    participants = data.get("participants")
    if not isinstance(participants, list) or not participants:
        return {"ok": False, "error": "participants must be a non-empty array"}
    task = str(data.get("task") or "")
    verdict_hint = str(data.get("verdict_hint") or "")
    try:
        worker_timeout = float(data.get("worker_timeout") or DEFAULT_WORKER_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        worker_timeout = DEFAULT_WORKER_TIMEOUT_SECONDS
    run_id, err = start_run(participants, task, verdict_hint, worker_timeout)
    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "run_id": run_id}


def http_cancel(data: dict) -> dict:
    run_id = str(data.get("run_id") or "")
    if not run_id:
        return {"ok": False, "error": "run_id is required"}
    ok, err = cancel_run(run_id)
    if not ok:
        return {"ok": False, "error": err}
    return {"ok": True}


def http_draft(data: dict) -> dict:
    participants = data.get("participants")
    if not isinstance(participants, list):
        return {"ok": False, "error": "participants must be an array"}
    save_draft(participants)
    return {"ok": True}


def http_runs() -> dict:
    return {"ok": True, "runs": list_runs(20)}


def http_run(run_id: str) -> dict:
    run = get_run(run_id)
    if run is None:
        return {"ok": False, "error": "no such run"}
    return {"ok": True, "run": run}
