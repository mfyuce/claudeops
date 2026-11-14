"""Önbellek canlı tutma (keep-warm, 2026-10-27): claude önbelleği 1 SAAT TTL'li ve uçurum gibidir (60 dk sonrası ~%97 soğuk, 5-55 dk
arası %0: `py/cops cache` + transkript ölçümü). Boşta ama YAKINDA kullanılacak, büyük bağlamlı oturuma TTL dolmadan hafif bir
dürtme (bağlam x0,1 okuma + birkaç çıktı tokeni) soğuk açılışı (bağlam x1,25 yazma) önler.

Sahip kuralı: kesinlikle ÇALIŞMAYAN oturuma dürtme YOK (çok harcama). Bu yüzden: iş fazında olmayan (done/paused/kayıtsız), drain'de
olan, küçük bağlamlı, alt ajanı çalışan ya da meşgul oturum atlanır; dürtmeye rağmen gerçek etkinlik gelmiyorsa zincir
`keepwarm_max_consecutive` dürtmede KESİLİR. Saf planlayıcı; `keepwarm=dry` yalnız `would:keepwarm` olayı üretir."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

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


def _waits_on_owner(v: Any, owner_projects: Optional[Any]) -> bool:
    """Zincir kapanışı YALNIZ iş SAHİPTE bekliyorsa (sahip kararı TBD#169, 7 Kas): projenin açık sahip sorusu (`STEWARD-ASK`, işleyiş
    sorusu değil) VAR ya da son cevap sahip beklentisini söylüyor. Başka projeyi/teslimi/dış işi (ör. menzilui: tunnel GetUsage) bekleyen
    oturum KAPANMAZ. SAF."""
    return v.project in set(owner_projects or ()) or sw.owner_wait(getattr(v, "last_assistant", "") or "")


CHAIN_PAUSE_REASON = "keepwarm zinciri: {n} dürtmede iş yok"


def chain_exempt(proj: Any, cfg: sw.Config) -> bool:
    """Zincir dolsa da paused OLMAYAN proje (TBD#163 b): `keepwarm_pause_exempt` listesi ya da notta "devam etmeli" işareti."""
    names = {x.strip() for x in str(cfg.keepwarm_pause_exempt or "").split(",") if x.strip()}
    return getattr(proj, "name", "") in names or "devam etmeli" in (getattr(proj, "notes", "") or "").lower()


def keepwarm_text(proj: Any, v: Any, open_work: Optional[Callable[[str], Optional[int]]] = None) -> str:
    """Dürtme metni: oturum yanıtında gerçek STEWARD-NEXT bildirdiyse `devam: <o iş>`; yoksa projenin sıradaki işi var VE son cevap bitti demiyorsa TEK satır `devam: <iş>`; yoksa (ya da
    last_assistant boşsa bitti sayılmaz) iş varsa yine devam; iş yoksa eski KEEPWARM_TEXT. SAF."""
    sn = sw.marker_next_work(getattr(v, "last_assistant", "") or "")
    if sn and not sw.turn_failed(getattr(v, "last_assistant", "") or ""):
        return sw.one_line(f"devam: {sn}")      # oturum kendi sahipsiz işini bildirdi: 'yalnızca ok yaz' o işi durdururdu (prompti 13 Kas)
    hint = sw.next_work_hint(proj, open_work, real_only=True) if proj is not None else ""
    if not hint:
        return KEEPWARM_TEXT
    marker, _ready = sw.idle_finish_marker(getattr(v, "last_assistant", "") or "")
    if marker:
        return KEEPWARM_TEXT
    return sw.one_line(f"devam: {hint}")


def has_work(proj: Any, v: Any, open_work: Optional[Callable[[str], Optional[int]]] = None,
             answer_pending: Optional[Any] = None) -> bool:
    """Keepwarm YALNIZ iş sürecek oturuma: (a) oturumun son yanıtında gerçek STEWARD-NEXT, (b) cevabı yakında gelecek/iletilecek
    (`answer_pending`: cevaplanmış ama oturuma iletilmemiş soru), (c) sahipsiz açık TODO maddesi ya da notta `sıradaki: <iş>` VE oturum
    "sıradaki: yok"/"sahipte" demiyor. no_next_work / next_none / owner_wait'te False. SAF."""
    txt = getattr(v, "last_assistant", "") or ""
    if sw.marker_next_work(txt):
        return True
    if v.project in set(answer_pending or ()):
        return True
    if sw.next_none_stated(txt) or sw.owner_wait(txt):
        return False
    if proj is not None and sw.next_work_hint(proj, None, real_only=True):
        return True
    try:
        return bool(open_work is not None and int(open_work(v.project) or 0) > 0)
    except Exception:
        return False


def plan_keepwarm(views: List[Any], projects: Dict[str, Any], state: Dict[str, Any], cfg: sw.Config, now: float,
                  planned: List[sw.Action], world: Optional[sw.World] = None,
                  open_work: Optional[Callable[[str], Optional[int]]] = None,
                  owner_projects: Optional[Any] = None, answer_pending: Optional[Any] = None) -> Tuple[List[sw.Action], Dict[str, Any]]:
    """Dürtülecek oturumlar için `keepwarm` eylemleri + güncellenmiş state (`state["keepwarm"][ad] = {at, n}`). `off`/drain: hiçbir
    şey. Aynı boşta dönemi için bir kez (`at` > son etkinlik); dürtmeye rağmen gerçek etkinlik yoksa en çok
    `keepwarm_max_consecutive` ardışık dürtme. `planned` aynı oturuma dokunuyorsa atlanır. SAF."""
    if cfg.keepwarm not in ("dry", "act") or cfg.drain:
        return [], state
    if world is not None:
        projects = world.own_projects(projects)
    rec_all: Dict[str, Any] = dict(state.get("keepwarm") or {})
    touched = {a.name for a in planned}
    ho_pending: Dict[str, float] = dict(state.get("ho_pending") or {})
    ho_close: Dict[str, str] = dict(state.get("ho_close") or {})
    ho_pause: Dict[str, str] = dict(state.get("ho_pause") or {})
    out: List[sw.Action] = []
    for v in views:
        if v.name in touched or v.name in ho_pending:
            continue    # devir/kapanış sürecindeki oturuma dürtme YOK (ho_pending: devir notu bekleniyor, dürtme turu araya girer)
        rec = rec_all.get(v.name) or {}
        at, n = float(rec.get("at") or 0), int(rec.get("n") or 0)
        skip = _skip_reason(v, projects, cfg, now)
        # Zincir dolduysa (n >= max, dürtmeden sonra gerçek etkinlik yok) kapanış `not_due` penceresini BEKLEMEZ: son dürtme
        # pencereyi yeniden açar, bir sonraki 52 dk'lık eşik ~1 sa sonradır ve önbellek o zamana soğur (mtsyn 7 Kas 16:02 n=3,
        # would:idle_close ancak ~16:55'te çıkacaktı). Önbellek SICAKKEN devir ucuz: hemen değerlendir.
        chain_full = bool(skip == "not_due" and v.last_activity and n >= cfg.keepwarm_max_consecutive
                          and not v.last_activity > at + REAL_ACTIVITY_SLACK)
        if skip and not chain_full:
            continue
        if world is not None and world.session_class(v.name, v.blueprint) != "own":
            continue
        if at and now - at < RENOTICE_SECONDS:
            continue    # bu boşta dönem için zaten dürtüldü/kaydedildi (dry'da son etkinlik değişmez, pencerede yeniden yazma)
        real = v.last_activity > at + REAL_ACTIVITY_SLACK
        chain = 0 if real else n
        if chain >= cfg.keepwarm_max_consecutive:
            proj = projects.get(v.project)
            if (cfg.keepwarm_chain_close in ("dry", "act") and not (rec.get("closed_at") and rec.get("mode") == cfg.keepwarm_chain_close) and proj is not None
                    and not chain_exempt(proj, cfg) and _waits_on_owner(v, owner_projects) and v.tmux and v.name not in (state.get("ho_pending") or {})):
                reason = CHAIN_PAUSE_REASON.format(n=chain)
                out.append(sw.Action("idle_close", v.name, f"keepwarm zinciri doldu ({chain} dürtme, gerçek etkinlik yok)",
                                     {"project": v.project, "idle_secs": int(now - v.last_activity), "threshold": cfg.keepwarm_after_minutes * 60,
                                      "n": chain, "mode": "handover", "pause": False, "marker": "keepwarm_chain", "next": "",
                                      "pause_reason": reason}))
                rec_all[v.name] = dict(rec, closed_at=now, mode=cfg.keepwarm_chain_close)
                if cfg.keepwarm_chain_close == "act" and cfg.mode != "observe":
                    ho_pending[v.name] = now
                    ho_close[v.name] = v.project
                    ho_pause[v.name] = reason
            continue
        if not has_work(projects.get(v.project), v, open_work, answer_pending):
            continue    # işi olmayan oturumun önbelleği SOĞUSUN (sahip 13 Kas: her ping ~100-300K okuma; cevap gelince tek soğuk uyanış daha ucuz)
        rec_all[v.name] = {"at": now, "n": chain + 1}
        out.append(sw.Action("keepwarm", v.name, "keepwarm",
                             {"project": v.project, "age_min": round((now - v.last_activity) / 60, 1),
                              "tokens": v.context_tokens, "n": chain + 1,
                              "text": keepwarm_text(projects.get(v.project), v, open_work)}))
    if not out:
        return [], state
    st = dict(state)
    st["keepwarm"] = rec_all
    if ho_pause:
        st["ho_pending"], st["ho_close"], st["ho_pause"] = ho_pending, ho_close, ho_pause
    return out, st
