"""İşi olmayan oturumu devir + kapat + paused (sahip 13 Kas 23:4x): sıradaki işi (TODO'da sahipsiz açık madde, gerçek STEWARD-NEXT, notta
`sıradaki:`) YOK ve hiçbir şeyi BEKLEMEYEN oturumun önbelleğini sıcak tutmak da, boş oturumu açık bırakmak da boşa kota. Kural (hepsi birden):
  - claude, yerel tmux, değnekçinin KENDİ (own) oturumu; beyin/`line`/`copsdev`/manual/ho_pending hariç; proje done/paused değil
  - boşta (busy False), alt ajan yok/bilinmiyor değil, en az `no_work_close_minutes` (30) dk
  - iş yok: no_next_work ya da next_none (gerçek STEWARD-NEXT yok, TODO'da sahipsiz açık madde ve notta `sıradaki:` yok / oturum "yok" diyor)
  - BEKLEMİYOR: oturumun/projenin cevapsız sorusu (sahibe ya da beyne, ROUTINE dahil), iletilmemiş cevap, son yanıtta ASK/BLOCKED/ROUTINE/JOB işareti,
    kapıda bekleme, sahipte bekleme; onaylı/doğrulanmış ama iletilmemiş review bulgusu, gönderilmemiş/onaysız ders, koşan review, açık varaka işi
Kapanış mevcut yolla (`idle_close`: devir -> kapat -> phase=paused, gerekçe "iş yok"). Yeniden açılış: sahip cevabı, TODO sha değişimi, review
bulgusu/ders iletimi ya da direktif -> paused -> planned + `start` (--new, devir notuyla). Saf planlayıcı; uygulama `web_steward`."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from . import steward as sw

NO_WORK_REASON = "iş yok"
EXEMPT_NAMES = ("line", "copsdev")
SESSION_ASK_MARKERS = ("STEWARD-ASK", "STEWARD-BLOCKED", "STEWARD-ROUTINE", "STEWARD-JOB")


def check_session(v: Any, proj: Any, state: Dict[str, Any], cfg: sw.Config, now: float,
                  open_work: Optional[Callable[[str], Optional[int]]], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """SAF. Bir oturum için kural denetimleri: `{close: bool, why: str, checks: {...}}`. `checks` değerleri True = KAPATMAYA engel YOK.
    `ctx`: {open_q: {proje}, answer_pending: {proje}, review: {proje: neden}, jobs: {proje}}."""
    txt = getattr(v, "last_assistant", "") or ""
    proj_name = v.project
    sn = sw.marker_next_work(txt)
    try:
        n_open = int(open_work(proj_name) or 0) if open_work is not None else 0
    except Exception:
        n_open = 0
    note_hint = sw.next_work_hint(proj, None, real_only=True) if proj is not None else ""
    none_stated = sw.next_none_stated(txt)
    no_work = (not sn) and ((n_open <= 0 and not note_hint) or none_stated)
    since = float(getattr(v, "last_activity", 0) or 0)
    idle_min = (now - since) / 60.0 if since > 0 else 0.0
    min_idle = float(getattr(cfg, "no_work_close_minutes", 30) or 30)
    review_why = (ctx.get("review") or {}).get(proj_name, "")
    session_asked = any(m in txt for m in SESSION_ASK_MARKERS)
    checks = {
        "no_work": no_work,                                                                  # iş yok (no_next_work/next_none)
        "idle": v.busy is False and since > 0 and idle_min >= min_idle,                      # boşta >= 30 dk
        "no_subagent": not (getattr(v, "subagent_active", False) or getattr(v, "subagent_unknown", False)),
        "no_question": (proj_name not in (ctx.get("open_q") or ()) and proj_name not in (ctx.get("answer_pending") or ())
                        and not session_asked and not sw.waiting_for_gate(txt) and not sw.owner_wait(txt) and not sw.turn_failed(txt)),
        "no_review_item": not review_why and proj_name not in (ctx.get("jobs") or ()),       # bulgu/ders/koşan review/açık varaka işi YOK
    }
    why = ""
    for k in ("no_work", "idle", "no_subagent", "no_question", "no_review_item"):
        if not checks[k]:
            why = k
            break
    if why == "no_review_item" and review_why:
        why = "no_review_item:" + review_why
    return {"close": not why, "why": why, "checks": checks, "idle_min": round(idle_min, 1), "next": sn,
            "open_todo": n_open}


def plan_no_work_close(views: List[Any], projects: Dict[str, Any], state: Dict[str, Any], cfg: sw.Config, now: float,
                       planned: List[sw.Action], world: Optional[sw.World] = None,
                       open_work: Optional[Callable[[str], Optional[int]]] = None,
                       ctx: Optional[Dict[str, Any]] = None) -> Tuple[List[sw.Action], Dict[str, Any]]:
    """Kapatılacak oturumlar için `idle_close` (marker `no_work`) + güncellenmiş state. `no_work_close=off` iken hiçbir şey. Her tick
    ADAY oturumların kontrol sonucu `state["no_work_report"][ad]`a yazılır (dry listesi/panel). `act` kipinde devir kuyruğu (`ho_pending/
    ho_close/ho_pause`) keepwarm zinciriyle AYNI. SAF."""
    mode = getattr(cfg, "no_work_close", "off")
    if mode not in ("dry", "act") or cfg.drain:
        return [], state
    ctx = ctx or {}
    if world is not None:
        projects = world.own_projects(projects)
    touched = {a.name for a in planned}
    rec_all: Dict[str, Any] = dict(state.get("no_work_close") or {})
    report: Dict[str, Any] = {}
    ho_pending: Dict[str, float] = dict(state.get("ho_pending") or {})
    ho_close: Dict[str, str] = dict(state.get("ho_close") or {})
    ho_pause: Dict[str, str] = dict(state.get("ho_pause") or {})
    out: List[sw.Action] = []
    exempt = set(EXEMPT_NAMES)
    for v in views:
        if v.cli != "claude" or not v.running or not v.tmux or getattr(v, "host", "local") not in ("local", ""):
            continue
        if v.name == cfg.brain_name or v.name in touched or v.name in ho_pending or v.project in exempt or v.name in exempt:
            continue
        proj = projects.get(v.project)
        if proj is None or proj.phase in ("done", "paused"):
            continue
        if world is not None and world.session_class(v.name, v.blueprint) != "own":
            continue
        res = check_session(v, proj, state, cfg, now, open_work, ctx)
        report[v.name] = dict(res, project=v.project, at=now, mode=mode)
        if not res["close"]:
            continue
        rec = rec_all.get(v.name) or {}
        if rec.get("mode") == mode and float(rec.get("at") or 0) >= float(v.last_activity or 0):
            continue            # bu boşta dönem için zaten karar verildi (dry'da son etkinlik değişmez)
        out.append(sw.Action("idle_close", v.name, f"iş yok: {int(res['idle_min'])} dk boşta, bekleyen bir şey yok",
                             {"project": v.project, "idle_secs": int(res["idle_min"] * 60), "threshold": int(float(cfg.no_work_close_minutes) * 60),
                              "n": 0, "mode": "handover", "pause": False, "marker": "no_work", "next": "", "pause_reason": NO_WORK_REASON,
                              "checks": res["checks"]}))
        rec_all[v.name] = {"at": now, "mode": mode}
        if mode == "act" and cfg.mode != "observe" and v.tmux:
            ho_pending[v.name] = now
            ho_close[v.name] = v.project
            ho_pause[v.name] = NO_WORK_REASON
    st = dict(state)
    if report or "no_work_report" in st:        # boş rapor yazılmaz (state altın testleri/gürültü)
        st["no_work_report"] = report
    if out:
        st["no_work_close"] = rec_all
        if mode == "act" and cfg.mode != "observe":
            st["ho_pending"], st["ho_close"], st["ho_pause"] = ho_pending, ho_close, ho_pause
    return out, st


def plan_no_work_reopen(projects: Dict[str, Any], state: Dict[str, Any], now: float, ctx: Dict[str, Any],
                        todo_sha: Optional[Callable[[str], str]] = None) -> List[sw.Action]:
    """`iş yok` ile paused edilmiş projeleri yeniden açma kararı (`state["no_work_paused"][proje] = {at, sha}`): (1) sahip cevabı
    (iletilmemiş cevap), (2) TODO sha değişimi (sahibin yeni todo'su), (3) projeye review bulgusu/ders iletilecek. Direktif tetikleyicisi
    `http_directive` yolunda. Eylem `no_work_reopen` (paused -> planned + start --new). SAF."""
    paused = dict(state.get("no_work_paused") or {})
    out: List[sw.Action] = []
    for name, rec in sorted(paused.items()):
        p = projects.get(name)
        if p is None or p.phase != "paused":
            continue
        trig = ""
        qid = ""
        if name in (ctx.get("answer_pending") or {}):
            trig, qid = "answer", str((ctx.get("answer_pending") or {}).get(name) or "")
        elif (ctx.get("review") or {}).get(name):
            trig = "review:" + str(ctx["review"][name])
        elif todo_sha is not None:
            try:
                cur = str(todo_sha(name) or "")
            except Exception:
                cur = ""
            if cur and rec.get("sha") and cur != rec.get("sha"):
                trig = "todo_changed"
        if trig:
            out.append(sw.Action("no_work_reopen", name, f"iş yok durdurması kalktı: {trig}", {"project": name, "trigger": trig, "question_id": qid}))
    return out
