"""Önbellek canlı tutma (keep-warm, 2026-10-27): claude önbelleği 1 SAAT TTL'li ve uçurum gibidir (60 dk sonrası ~%97 soğuk, 5-55 dk
arası %0: `py/cops cache` + transkript ölçümü). Boşta ama YAKINDA kullanılacak, büyük bağlamlı oturuma TTL dolmadan hafif bir
dürtme (bağlam x0,1 okuma + birkaç çıktı tokeni) soğuk açılışı (bağlam x1,25 yazma) önler.

Sahip kuralı: kesinlikle ÇALIŞMAYAN oturuma dürtme YOK (çok harcama). Bu yüzden: iş fazında olmayan (done/paused/kayıtsız), drain'de
olan, küçük bağlamlı, alt ajanı çalışan ya da meşgul oturum atlanır; dürtmeye rağmen gerçek etkinlik gelmiyorsa zincir
`keepwarm_max_consecutive` dürtmede KESİLİR. Saf planlayıcı; `keepwarm=dry` yalnız `would:keepwarm` olayı üretir."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import steward as sw

TTL_SECONDS = 60 * 60            # ölçülen önbellek ömrü
DEADLINE_SECONDS = 58 * 60       # bundan sonra dürtmek geç (uçurum 60. dk)
RENOTICE_SECONDS = 10 * 60       # aynı oturum için iki keepwarm kaydı arası en az (pencere 52-58 dk, tick 2 dk)
REAL_ACTIVITY_SLACK = 300        # dürtmenin kendi turu bu kadar içinde biter: sonrası GERÇEK etkinlik sayılır
KEEPWARM_TEXT = "[keepwarm] Yalnızca 'ok' yaz; başka hiçbir şey yapma, araç çağırma."
SKIP_PHASES = ("done", "paused")


def _skip_reason(v: Any, projects: Dict[str, Any], cfg: sw.Config, now: float) -> str:
    if not v.running or v.cli != "claude" or not v.tmux or getattr(v, "host", "local") not in ("local", ""):
        return "not_local_claude"
    if v.busy is not False or getattr(v, "subagent_active", False) or getattr(v, "subagent_unknown", False):
        return "busy"
    if v.project not in projects:
        return "not_project"
    if projects[v.project].phase in SKIP_PHASES:
        return "phase"
    tok = v.context_tokens
    if tok is None or tok < cfg.keepwarm_min_tokens:
        return "small_context"
    if not v.last_activity:
        return "unknown_age"
    age = now - v.last_activity
    if age < cfg.keepwarm_after_minutes * 60 or age >= DEADLINE_SECONDS:
        return "not_due"
    return ""


def plan_keepwarm(views: List[Any], projects: Dict[str, Any], state: Dict[str, Any], cfg: sw.Config, now: float,
                  planned: List[sw.Action], world: Optional[sw.World] = None) -> Tuple[List[sw.Action], Dict[str, Any]]:
    """Dürtülecek oturumlar için `keepwarm` eylemleri + güncellenmiş state (`state["keepwarm"][ad] = {at, n}`). `off`/drain: hiçbir
    şey. Aynı boşta dönemi için bir kez (`at` > son etkinlik); dürtmeye rağmen gerçek etkinlik yoksa en çok
    `keepwarm_max_consecutive` ardışık dürtme. `planned` aynı oturuma dokunuyorsa atlanır. SAF."""
    if cfg.keepwarm not in ("dry", "act") or cfg.drain:
        return [], state
    if world is not None:
        projects = world.own_projects(projects)
    rec_all: Dict[str, Any] = dict(state.get("keepwarm") or {})
    touched = {a.name for a in planned}
    out: List[sw.Action] = []
    for v in views:
        if v.name in touched or _skip_reason(v, projects, cfg, now):
            continue
        if world is not None and world.session_class(v.name, v.blueprint) != "own":
            continue
        rec = rec_all.get(v.name) or {}
        at, n = float(rec.get("at") or 0), int(rec.get("n") or 0)
        if at and now - at < RENOTICE_SECONDS:
            continue    # bu boşta dönem için zaten dürtüldü/kaydedildi (dry'da son etkinlik değişmez, pencerede yeniden yazma)
        real = v.last_activity > at + REAL_ACTIVITY_SLACK
        chain = 0 if real else n
        if chain >= cfg.keepwarm_max_consecutive:
            continue
        rec_all[v.name] = {"at": now, "n": chain + 1}
        out.append(sw.Action("keepwarm", v.name, "keepwarm",
                             {"project": v.project, "age_min": round((now - v.last_activity) / 60, 1),
                              "tokens": v.context_tokens, "n": chain + 1}))
    if not out:
        return [], state
    st = dict(state)
    st["keepwarm"] = rec_all
    return out, st
