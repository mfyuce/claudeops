"""TOBEDECIDED#15 Phase 2 — run engine: bir görevi worker session'lara
dağıt (opsiyonel olarak önce bir controller'a brief yazdırıp), yanıtları
bekle, consensus'u çöz (opsiyonel olarak bir decider'a bırakarak), bitince
controller'a handoff mesajı gönder. MCP (Phase 3) hâlâ yok, bkz. onaylanmış
plan `~/.claude/plans/idempotent-riding-key.md`.

`web.py`'nin `_v1_eligible_sessions()`'ıyla AYNI uygunluk üçlüsünü
(çalışıyor + tmux-backed + `has_conversation()`) kendi başına tekrar
uyguluyor — `web.py`'yi import ETMİYORUZ (o bizi import ediyor, döngüsel
import riski). `if cli == ...` YOK: provider arayüzünden geçiyor.
"""
from __future__ import annotations
import concurrent.futures
import dataclasses
import itertools
import os
import re
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import hosts as hosts_mod
from .. import orchestration as orch
from .. import orch_store
from .. import turns
from ..diaglog import diag_log
from ..discovery import find_sessions
from ..providers import get_provider
from ..tmux_backend import is_tmux_backed, strip_ansi, tmux_send_keys
from . import web_hosts
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

# Phase 3 (TOBEDECIDED#15, MCP server) — `cops_result_push` bir katılımcının
# kendi yanıtını pane-tail okumaktansa doğrudan bildirmesi için. `_run_turn`
# turunu BAŞLATIRKEN kendi (run_id,name) anahtarını `_WAITING`'e ekler, turns.
# wait_for_reply'ın her poll'unda `_push_result`'ın yazdığı bir giriş var mı diye
# bakar (bkz. `turns.wait_for_reply`'ın `push_check` parametresi). `_WAITING`'de
# OLMAYAN bir push (yanlış run_id/name, ya da tur zaten bitmiş) REDDEDİLİR —
# `http_result` bunu düz bir hata olarak yansıtır, sessizce yutulmaz.
_PUSH_LOCK = threading.Lock()
_WAITING: set = set()          # {(run_id, name)}
_PUSHED: Dict[Tuple[str, str], str] = {}  # (run_id, name) -> formatted reply text


def _new_run_id() -> str:
    return "r" + time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)


@dataclasses.dataclass
class _RemoteRef:
    """Uzak-host session'ları için `discovery.Session`'ın yerine geçen minimal
    stand-in. `_run_turn`'ün ihtiyaç duyduğu TEK ŞEY host/name/cli/cwd — uzak
    session'ın turn-mekaniğinin TAMAMI (`_send_prompt`/`_fetch_exchange`)
    `web_hosts` proxy'sinden HTTP ile geçtiği için lokal bir dosya yolu/pid
    hiç gerekmiyor. `sid` her zaman None (agy'nin fresh-session/live_snapshot
    kavramı tamamen local, uzak katılımcılara hiç uygulanmıyor)."""
    host: str
    name: str
    cli: str
    cwd: str
    sid: Optional[str] = None


def _eligible_index() -> Dict[Tuple[str, str], Any]:
    """(host, name) → canlı Session (local) ya da _RemoteRef (uzak host).

    Local: `_v1_eligible_sessions()` (web.py) ile AYNI üçlü şart (çalışıyor +
    tmux-backed + has_conversation()).

    Uzak (TOBEDECIDED#20, 2026-09-11): `web_hosts`'un arka-plan poller
    cache'i (`get_cached()`, asla network'e gitmez) — host `ok:true`
    DEĞİLSE ya da bir satır `tmux:false` İSE tamamen atlanır.
    `has_conversation()`'ın uzak eşdeğeri BURADA AYRICA kontrol EDİLMİYOR
    (ekstra bir proxy round-trip'i gerektirirdi, preflight'ı N-katlı ağ
    çağrısına çevirirdi) — o kontrol `_run_turn`'ün baseline-fetch adımına
    ERTELENMİŞ (`_fetch_exchange` None dönerse zaten "unreachable" statüsüne
    düşer, aynı sonuç, sadece preflight yerine dispatch anında fark edilir)."""
    out: Dict[Tuple[str, str], Any] = {}
    for s in find_sessions(measure_cpu=False):
        if not is_tmux_backed(s.pid):
            continue
        if not get_provider(s.cli).has_conversation():
            continue
        out[("local", s.name)] = s
    for host_record in hosts_mod.load_hosts():
        host_name = host_record["name"]
        cached = web_hosts.get_cached(host_name)
        if cached is None or not cached.get("ok"):
            continue
        for row in cached.get("sessions", []):
            name = row.get("name")
            if not name or not row.get("tmux"):
                continue
            out[(host_name, name)] = _RemoteRef(
                host=host_name, name=name, cli=row.get("cli") or "", cwd=row.get("cwd") or "",
            )
    return out


_ROLES = ("worker", "controller", "decider")


def _preflight(participants: List[dict]) -> Optional[str]:
    """None = OK, aksi halde düz-metin hata (henüz TR/EN localize edilmedi —
    bu geçiş backend-only, tüketen bir UI yok; frontend eklenince ERR
    tablosuna taşınabilir, bkz. plan'ın listelediği `orch_*` anahtarları).
    Hiçbir ihlalde KISMİ başlatma yok — ya hepsi geçer ya hiçbir mesaj gitmez.

    Phase 2: controller/decider artık kabul ediliyor (≤1'er) — plan'ın
    aynen istediği kural. Çakışma kontrolü (aynı (host,cli,cwd)) ÜÇ rolün
    TAMAMINA uygulanıyor, sadece worker'lara değil (2026-09-07
    `resolve_resume_id` collision incident'ının AYNISI bir controller/
    decider için de geçerli).

    Uzak-host katılımcılar (TOBEDECIDED#20, 2026-09-11) artık kabul
    ediliyor — eskiden burada host!=local kategorik olarak reddediliyordu,
    şimdi `_eligible_index()` zaten uzak session'ları da taşıdığı için tek
    kontrol aşağıdaki "eligible mi" lookup'u, host'a göre AYRI bir dal yok."""
    if not participants:
        return "no participants given"
    for p in participants:
        if p.get("role") not in _ROLES:
            return f"unknown role: {p.get('role')!r}"
    workers = [p for p in participants if p.get("role") == "worker"]
    controllers = [p for p in participants if p.get("role") == "controller"]
    deciders = [p for p in participants if p.get("role") == "decider"]
    if not workers:
        return "at least one worker is required"
    if len(controllers) > 1:
        return "at most one controller is allowed"
    if len(deciders) > 1:
        return "at most one decider is allowed"

    index = _eligible_index()
    seen_triples = set()
    for p in workers + controllers + deciders:
        host = str(p.get("host") or "local")
        name = str(p.get("name") or "").strip()
        if not name:
            return "a participant is missing a name"
        s = index.get((host, name))
        if s is None:
            return f"'{name}': not an eligible running session (must be running, tmux-backed, and hold a conversation)"
        triple = (host, s.cli, s.cwd)
        if triple in seen_triples:
            return f"'{name}': shares (host, cli, cwd) with another participant — their replies would be indistinguishable"
        seen_triples.add(triple)
    return None


def _inline_or_file(run_id: str, full_prompt: str, head_source: str, contract_tail: str, filename: str) -> str:
    """`full_prompt` boyu `INLINE_LIMIT_CHARS`'ı aşarsa TAMAMI run dizinine
    dosya olarak yazılır + `head_source`'un kısaltılmış başı + İŞARETÇİ +
    `contract_tail` enjekte edilir (contract HER ZAMAN bütün kalır —
    kesinlikle kısaltılmaz, aksi halde alıcı kendi yanıt biçimini hiç
    görmez). Worker-dispatch (Phase 1) VE brief-dispatch (Phase 2) AYNI
    şekle sahip olduğu için paylaşılıyor; decider-dispatch'in "head" anlamı
    farklı (bkz. `_build_decider_dispatch` — kendi ayrı fallback'i var)."""
    if len(full_prompt) <= INLINE_LIMIT_CHARS:
        return full_prompt
    d = orch_store.run_dir(run_id)
    os.makedirs(d, exist_ok=True)
    fpath = os.path.join(d, filename)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(full_prompt)
    head = head_source.strip()[:INLINE_HEAD_CHARS]
    return (
        f"{head}\n\n[... truncated for delivery size (a large paste has been observed to crash "
        f"one of this fleet's CLIs) — the complete text is at {fpath}, read it if you need the rest "
        f"before answering ...]\n\n{contract_tail}"
    )


def _build_dispatch_prompt(run_id: str, task: str, verdict_hint: str) -> str:
    full = orch.build_worker_prompt(task, verdict_hint)
    return _inline_or_file(run_id, full, task, orch.verdict_contract(), "task.md")


def _build_brief_dispatch(run_id: str, task: str) -> str:
    full = orch.build_brief_prompt(task)
    return _inline_or_file(run_id, full, task, orch.brief_contract(), "brief_task.md")


def _build_decider_dispatch(run_id: str, task: str, verdict_hint: str, bundle: str) -> str:
    """Decider'ın kendi fallback'i `_inline_or_file`'ı KULLANMIYOR: burada
    kısaltılacak/dosyaya taşınacak şey `task` değil `bundle` (worker
    yanıtlarının toplamı) — task+hint genelde kısa, olduğu gibi kalıyor."""
    full = orch.build_decider_prompt(task, verdict_hint, bundle)
    if len(full) <= INLINE_LIMIT_CHARS:
        return full
    d = orch_store.run_dir(run_id)
    os.makedirs(d, exist_ok=True)
    fpath = os.path.join(d, "decider_bundle.md")
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(bundle)
    hint = f"\n\nVerdict format hint: {verdict_hint.strip()}" if verdict_hint.strip() else ""
    return (
        f"You are the decider for a team task. Task:\n{task.strip()}{hint}\n\n"
        f"[... worker answers too large to inline (a large paste has been observed to crash one of "
        f"this fleet's CLIs) — read them from {fpath} before answering ...]\n\n{orch.verdict_contract()}"
    )


def _push_result(run_id: str, name: str, verdict: str, text: str) -> bool:
    """`http_result()`'tan çağrılır (MCP `cops_result_push`). Sadece o
    (run_id,name) İÇİN GERÇEKTEN bekleyen bir `_run_turn` varsa kabul eder
    (True) — aksi halde (yanlış run_id, henüz dispatch edilmemiş, ya da tur
    zaten bitmiş) False, `http_result` bunu düz bir hataya çevirir. Kabul
    edilen metin `_with_verdict`'in `parse_verdict()`'inin ZATEN anladığı
    tail-sözleşmesine (`COPS-VERDICT:`/`COPS-END`) sarılır — bu sayede
    `_one_worker`/`_run_decider`'ın geri kalanı push'un pane-tail'den mi yoksa
    bu yoldan mı geldiğini AYIRT ETMEK ZORUNDA KALMAZ, tek bir parse yolu."""
    envelope = f"{orch.VERDICT_MARKER} {verdict.strip()}\n{orch.END_MARKER}"
    formatted = f"{text.strip()}\n\n{envelope}" if text.strip() else envelope
    key = (run_id, name)
    with _PUSH_LOCK:
        if key not in _WAITING:
            return False
        _PUSHED[key] = formatted
    return True


def _send_prompt(host: str, name: str, cli: str, prompt: str) -> bool:
    """Bir katılımcıya (worker/controller/decider fark etmez) tek bir mesaj
    gönder — local ise doğrudan tmux, uzak ise `web_hosts` proxy'si
    (`/api/term/input`, Terminal view'ın zaten kullandığı AYNI yol, TODO.md
    2026-09-07 "DONE"). `_run_turn`'ün dispatch adımı VE `_run_thread`'in
    controller-handoff'u bu TEK fonksiyonu paylaşır — ikisi de aynı işlem
    (birine bir metin yolla), host dalı tekrarlanmasın diye."""
    if host == "local":
        return tmux_send_keys(name, prompt, settle_delay=get_provider(cli).input_settle_delay())
    result, _status = web_hosts.proxy_action("/api/term/input", host, {"name": name, "text": prompt})
    return bool(result.get("ok"))


def _fetch_exchange(host: str, name: str, cwd: str, sid: Optional[str], provider) -> Optional[dict]:
    """Bir katılımcının GÜNCEL son user/assistant çiftini oku — `_run_turn`'ün
    hem BAŞLANGIÇ baseline'ı hem `_wait_for_reply_remote`'un her poll'undaki
    "şimdiki durum" için AYNI fonksiyon (tıpkı local yolun `provider.
    last_exchange()`'i ikisi için de kullanması gibi). Local: doğrudan
    `provider.last_exchange(cwd, sid)`. Uzak: `/api/term/chat` (mode=last) —
    `_term_chat`'in döndürdüğü `{"user","assistant"}` şekli local'inkiyle
    BİREBİR AYNI olduğu için çağıranın karşılaştırma mantığı (değişti mi/
    marker var mı) host'a göre hiç dallanmıyor, sadece BU fonksiyon dallanıyor."""
    if host == "local":
        return provider.last_exchange(cwd, sid)
    result, _status = web_hosts.proxy_get("/api/term/chat", host, {"name": name, "mode": "last"})
    if not result.get("ok") or not result.get("supported"):
        return None
    return {"user": result.get("user", ""), "assistant": result.get("assistant", "")}


def _remote_busy_now(host: str, name: str, pattern: str) -> bool:
    """`turns.is_busy_now`'ın uzak eşdeğeri — `/api/term/output`'un ham
    (ANSI'li) pane metni üstünde AYNI `strip_ansi`+regex disiplini."""
    result, _status = web_hosts.proxy_get("/api/term/output", host, {"name": name})
    if not result.get("ok"):
        return False
    return bool(re.search(pattern, strip_ansi(result.get("text") or "")))


def _wait_for_reply_remote(host: str, name: str, provider, baseline: dict, *, timeout: float, poll: float,
                            stable_polls: int, require_marker: Optional[str], cancel: threading.Event,
                            push_check) -> Optional[str]:
    """`turns.wait_for_reply`'nin uzak-host eşdeğeri — AYNI iki strateji
    (busy-pattern varsa onu, yoksa stable-debounce'u kullan), sadece pane/
    transcript okuması local yerine `web_hosts` proxy'sinden geliyor.

    `turns.py`'ye TAŞINMADI/BİRLEŞTİRİLMEDİ (bilerek): o modül host/proxy
    kavramını hiç bilmeyen paylaşımlı bir primitif — `/v1/chat/completions`
    (TOBEDECIDED#21) de kullanıyor ve o ASLA remote olmayacak (kendi "açık
    kalan" listesinin #1 maddesi). Uzak-host mantığını sadece ona ihtiyaç
    duyan TEK çağıran (orkestrasyon) taşısın diye burada, ayrı tutuldu.
    `live_snapshot`/sid-discovery YOK — agy'nin fresh-session tespiti
    tamamen local bir kavram, uzak katılımcılara hiç uygulanmıyor."""
    pattern = provider.busy_status_pattern()
    previous: Optional[dict] = None
    stable_count = 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancel is not None and cancel.is_set():
            return None
        time.sleep(poll)
        if cancel is not None and cancel.is_set():
            return None

        if push_check is not None:
            pushed = push_check()
            if pushed is not None:
                return pushed

        exchange = _fetch_exchange(host, name, "", None, provider)
        if exchange is None:
            return None
        changed = exchange != baseline
        assistant_text = exchange.get("assistant", "")
        marker_ok = (require_marker is None) or (require_marker in assistant_text)

        if pattern:
            if not _remote_busy_now(host, name, pattern) and changed and marker_ok:
                return assistant_text
        else:
            if changed and exchange == previous:
                stable_count += 1
            else:
                stable_count = 1 if changed else 0
            previous = exchange
            if changed and marker_ok and stable_count >= stable_polls:
                return assistant_text
    return None


def _run_turn(p: orch.Participant, seq: int, kind: str, index: Dict[Tuple[str, str], Any],
              prompt: str, timeout: float, cancel_event: threading.Event, require_marker: str,
              run_id: str) -> orch.RunResult:
    """Tek bir katılımcıya (rolü ne olursa olsun — worker/controller/decider)
    tek bir tur: enjekte et, tur bitene kadar bekle. Verdict PARSE ETMEZ
    (`.text`'i ham bırakır) — `_one_worker`/`_run_decider` kendi
    `parse_verdict()`'lerini `dataclasses.replace` ile üstüne biner, brief
    çağıranı `orch.parse_brief()`'i kendi tarafında çağırır. `kind`/`role`
    dışında `_one_worker`'ın Phase 1'deki gövdesiyle BİREBİR AYNI mekanizma.

    `run_id` (Phase 3): SADECE `_push_result`'ın (run_id,name) anahtarını
    kaydetmek/silmek için — turun geri kalanında kullanılmıyor.

    `p.host` (TOBEDECIDED#20, 2026-09-11): local ile uzak arasındaki TEK
    fark `_send_prompt`/`_fetch_exchange`/wait-fonksiyonu seçimi — geri
    kalan gövde (push-key/finally/elapsed/RunResult inşası) host'a göre
    hiç dallanmıyor."""
    created_at = time.time()
    s = index.get((p.host, p.name))
    if s is None:
        return orch.RunResult(seq=seq, kind=kind, role=p.role, host=p.host, name=p.name,
                               cli=p.cli, created_at=created_at, status="unreachable")
    provider = get_provider(s.cli)
    baseline = _fetch_exchange(p.host, s.name, s.cwd, s.sid, provider)
    if baseline is None:
        return orch.RunResult(seq=seq, kind=kind, role=p.role, host=p.host, name=p.name,
                               cli=p.cli, created_at=created_at, status="unreachable")
    # Fresh/hiç resume edilmemiş agy session'ı — 2026-09-09 commit `1356edc`
    # ile AYNI fallback (bkz. `turns.wait_for_reply` docstring'i). Uzak
    # katılımcılar için ASLA (yukarıdaki `_RemoteRef.sid` hep None).
    live_snapshot = provider.snapshot_for_live_sid(s.cwd) if (p.host == "local" and s.sid is None) else None

    # `_WAITING`'e send_keys'ten ÖNCE eklenir (send başarısız da olsa `finally`
    # temizler) — aradaki pencerede (mesaj gitti ama henüz kayıtlı değildik)
    # bir push'un reddedilme riskini TAMAMEN kapatır (pratikte imkansız kadar
    # dar bir pencere olsa da, bunu "yapısal olarak" kapatmak bedelsiz).
    push_key = (run_id, p.name)
    with _PUSH_LOCK:
        _WAITING.add(push_key)
    try:
        t0 = time.monotonic()
        diag_log("orch_turn_dispatch", name=s.name, host=p.host, seq=seq, kind=kind, chars=len(prompt))
        if not _send_prompt(p.host, s.name, s.cli, prompt):
            return orch.RunResult(seq=seq, kind=kind, role=p.role, host=p.host, name=p.name,
                                   cli=p.cli, created_at=created_at, status="send_failed")

        def _push_check() -> Optional[str]:
            with _PUSH_LOCK:
                return _PUSHED.pop(push_key, None)

        if p.host == "local":
            reply = turns.wait_for_reply(
                s, provider, baseline, live_snapshot,
                timeout=timeout, poll=1.0, stable_polls=3,
                require_marker=require_marker, cancel=cancel_event,
                push_check=_push_check,
            )
        else:
            reply = _wait_for_reply_remote(
                p.host, s.name, provider, baseline,
                timeout=timeout, poll=1.0, stable_polls=3,
                require_marker=require_marker, cancel=cancel_event,
                push_check=_push_check,
            )
    finally:
        with _PUSH_LOCK:
            _WAITING.discard(push_key)
            _PUSHED.pop(push_key, None)  # bu tur ASLA tüketmediyse de birikmesin
    elapsed = time.monotonic() - t0
    if reply is None:
        # `wait_for_reply` returns None for BOTH real timeout and cancel
        # (bkz. kendi docstring'i, "tek bir 'bitmedi' sonucu yeterli") — ama
        # burada, run bittikten SONRA turn-seviyesi status'u UI'a göstermek
        # için ikisini ayırmak ucuz: cancel_event zaten set'liyse sebep
        # kesin cancel'dır (timeout ayrıca dolmuş olabilir, ama kullanıcı
        # aksiyonu daha bilgilendirici).
        status = "cancelled" if cancel_event.is_set() else "timeout"
        return orch.RunResult(seq=seq, kind=kind, role=p.role, host=p.host, name=p.name,
                               cli=p.cli, created_at=created_at, status=status, elapsed=elapsed)
    return orch.RunResult(seq=seq, kind=kind, role=p.role, host=p.host, name=p.name,
                           cli=p.cli, created_at=created_at, status="ok", text=reply, elapsed=elapsed)


def _with_verdict(r: orch.RunResult) -> orch.RunResult:
    """`_run_turn`'ün ham `.text`'inden verdict çıkar (worker VE decider
    AYNI sözleşmeyi paylaşıyor, bkz. `orch.build_decider_prompt`'un kendi
    docstring'i) — `status != "ok"` ise dokunmadan olduğu gibi döner."""
    if r.status != "ok":
        return r
    verdict_raw = orch.parse_verdict(r.text)
    if verdict_raw is None:
        return dataclasses.replace(r, status="no_envelope")
    return dataclasses.replace(r, verdict=verdict_raw, verdict_key=orch.normalize_verdict(verdict_raw))


def _one_worker(w: orch.Participant, seq: int, index: Dict[Tuple[str, str], Any],
                 prompt: str, worker_timeout: float, cancel_event: threading.Event, run_id: str) -> orch.RunResult:
    return _with_verdict(_run_turn(w, seq, "worker_result", index, prompt, worker_timeout, cancel_event,
                                    orch.END_MARKER, run_id))


def _run_decider(decider: orch.Participant, seq: int, index: Dict[Tuple[str, str], Any],
                  prompt: str, timeout: float, cancel_event: threading.Event, run_id: str) -> orch.RunResult:
    return _with_verdict(_run_turn(decider, seq, "decision", index, prompt, timeout, cancel_event,
                                    orch.END_MARKER, run_id))


def _set_status(run_id: str, status: str) -> None:
    """Sadece faz geçişi (`briefing`→`working`→`deciding`) — `results`/
    `outcome`'a dokunmaz, `_save_progress`/`_save_final`'dan AYRI çünkü bir
    fazın BAŞLANGICINDA (henüz bir RunResult yokken) da çağrılıyor."""
    run = orch_store.load_run(run_id)
    if run is None:
        return
    run["status"] = status
    run["updated_at"] = time.time()
    orch_store.save_run(run)
    web_ws.notify_status_changed()


def _set_brief(run_id: str, brief: str) -> None:
    run = orch_store.load_run(run_id)
    if run is None:
        return
    run["brief"] = brief
    run["updated_at"] = time.time()
    orch_store.save_run(run)
    web_ws.notify_status_changed()


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


def _run_thread(run_id: str, workers: List[orch.Participant], controller: Optional[orch.Participant],
                 decider: Optional[orch.Participant], task: str, verdict_hint: str,
                 worker_timeout: float, cancel_event: threading.Event) -> None:
    """Phase 2 faz sırası: `briefing` (controller varsa) → `working` → `deciding`
    (decider varsa) → handoff (controller varsa). Controller/decider YOKSA
    bu, Phase 1'in davranışıyla BİREBİR AYNI (briefing/deciding/handoff
    bloklarının HİÇBİRİ çalışmaz, `effective_task` ham `task`, `resolve_outcome`
    AYNI şekilde `has_decider=False` ile çağrılır) — regresyon riski yok."""
    global _ACTIVE_RUN_ID
    try:
        index = _eligible_index()
        results: List[orch.RunResult] = []
        seq_counter = itertools.count(1)
        effective_task = task

        if controller is not None:
            _set_status(run_id, "briefing")
            brief_prompt = _build_brief_dispatch(run_id, task)
            brief_result = _run_turn(controller, next(seq_counter), "brief", index, brief_prompt,
                                      worker_timeout, cancel_event, orch.BRIEF_END_MARKER, run_id)
            results.append(brief_result)
            _save_progress(run_id, results)
            if cancel_event.is_set():
                _save_final(run_id, results, orch.Outcome(method="none", note="cancelled during briefing"), "cancelled")
                return
            if brief_result.status == "ok":
                parsed = orch.parse_brief(brief_result.text)
                if parsed:
                    effective_task = parsed
                    _set_brief(run_id, parsed)
            # timeout/send_failed/no marker in the reply → effective_task stays
            # the raw task (plan: "falls back to the raw task text on timeout
            # rather than failing the run" — treated the same for any brief
            # that didn't come back parseable, not just a literal timeout).
            _set_status(run_id, "working")
            # No controller → status is ALREADY "working" from `start_run`'s
            # initial write; skipping a redundant re-set here keeps a
            # no-controller/no-decider run's write pattern byte-identical to
            # Phase 1's, not just behaviorally equivalent.

        prompt = _build_dispatch_prompt(run_id, effective_task, verdict_hint)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_WORKERS, len(workers))) as ex:
            futures = {ex.submit(_one_worker, w, next(seq_counter), index, prompt, worker_timeout, cancel_event, run_id): w
                       for w in workers}
            for fut in concurrent.futures.as_completed(futures):
                results.append(fut.result())
                _save_progress(run_id, results)
        if cancel_event.is_set():
            _save_final(run_id, results, orch.Outcome(method="none", note="cancelled"), "cancelled")
            return

        worker_results = [r for r in results if r.kind == "worker_result"]

        if decider is not None:
            _set_status(run_id, "deciding")
            bundle = orch.format_worker_bundle(worker_results)
            decider_prompt = _build_decider_dispatch(run_id, task, verdict_hint, bundle)
            decision_result = _run_decider(decider, next(seq_counter), index, decider_prompt, worker_timeout,
                                            cancel_event, run_id)
            results.append(decision_result)
            _save_progress(run_id, results)
            if decision_result.status == "ok" and decision_result.verdict_key:
                abstained = [{"name": r.name, "status": r.status} for r in worker_results if r.status != "ok"]
                outcome = orch.Outcome(
                    method="decider", final=decision_result.verdict,
                    by={"host": decider.host, "name": decider.name, "cli": decider.cli},
                    abstained=abstained, note="decider's own verdict",
                )
            else:
                # Decider yanıt vermedi/format hatası — Phase 1'in TEK yolu
                # olan worker-consensus'a düş, `has_decider=False` (bkz.
                # `orchestration.resolve_outcome`'un kendi docstring'i).
                outcome = orch.resolve_outcome(worker_results, has_decider=False)
                fallback_note = "decider did not produce a usable verdict — fell back to worker consensus"
                outcome.note = f"{outcome.note} ({fallback_note})" if outcome.note else fallback_note
        else:
            outcome = orch.resolve_outcome(worker_results, has_decider=False)

        status = "cancelled" if cancel_event.is_set() else (
            "done" if outcome.method in ("decider", "unanimous", "majority", "single_worker") else "needs_human"
        )

        if controller is not None and not cancel_event.is_set():
            handoff_msg = orch.build_handoff_message(task, outcome)
            sent = _send_prompt(controller.host, controller.name, controller.cli, handoff_msg)
            results.append(orch.RunResult(
                seq=next(seq_counter), kind="final", role="controller", host=controller.host,
                name=controller.name, cli=controller.cli, created_at=time.time(),
                status="ok" if sent else "send_failed", text=handoff_msg,
            ))

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

    def _build(role: str) -> List[orch.Participant]:
        out = []
        for p in participants:
            if p.get("role") != role:
                continue
            host = str(p.get("host") or "local")
            name = str(p.get("name") or "").strip()
            s = index.get((host, name))
            out.append(orch.Participant(role=role, host=host, name=name, cli=(s.cli if s else "")))
        return out

    workers = _build("worker")
    controllers = _build("controller")
    deciders = _build("decider")
    controller = controllers[0] if controllers else None  # _preflight already caps this at ≤1
    decider = deciders[0] if deciders else None  # _preflight already caps this at ≤1
    all_participants = workers + controllers + deciders

    run = orch.Run(id=run_id, created_at=time.time(), updated_at=time.time(),
                    status="briefing" if controller else "working",
                    lang="tr", task=task, verdict_hint=verdict_hint or "", worker_timeout=worker_timeout,
                    participants=all_participants)
    orch_store.save_run(run)
    web_ws.notify_status_changed()

    t = threading.Thread(
        target=_run_thread, args=(run_id, workers, controller, decider, task, verdict_hint, worker_timeout, cancel_event),
        daemon=True, name=f"orch-{run_id}",
    )
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


def http_result(data: dict) -> dict:
    """Phase 3 (MCP `cops_result_push`) — bir katılımcının KENDİ turu için
    yapılan doğrudan/yapılandırılmış bildirim. `run_id`/`name` eşleşen
    GERÇEKTEN bekleyen bir `_run_turn` yoksa (yanlış run, tur zaten
    bitmiş/timeout olmuş, ya da `name` hiç bu run'ın katılımcısı değildi)
    `_push_result` False döner — burada da sessizce yutulmaz, düz bir hata."""
    run_id = str(data.get("run_id") or "")
    name = str(data.get("name") or "")
    verdict = str(data.get("verdict") or "")
    text = str(data.get("text") or "")
    if not run_id or not name:
        return {"ok": False, "error": "run_id and name are required"}
    if not verdict.strip():
        return {"ok": False, "error": "verdict is required"}
    accepted = _push_result(run_id, name, verdict, text)
    if not accepted:
        return {"ok": False, "error": f"no active turn is being waited on for run_id={run_id!r} name={name!r} "
                                       "(already answered, timed out, cancelled, or this run/participant doesn't exist)"}
    return {"ok": True}
