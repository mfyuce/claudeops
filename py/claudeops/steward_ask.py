"""ASK kapısı (25 Kas 2026, direktif e30d51b17d2b): değnekçi beyni STEWARD-ASK (sahibe sorulmuş) soruları da görür; cevabı
eklentinin `register_answer_gate` kancasından geçerse sahip adına yazılır. Burada yalnız BELİRLENİMCİ kısım: hangi soru HER
ZAMAN sahibe kalır, hangisi tura girer, kancanın yanıtı yeterli mi, sahibin kalıcı kararları. Fazla eşleşme güvenli taraftır."""
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Optional

from . import steward as sw

MODES = ("off", "shadow", "on")
SEEN_MAX_TOURS = 2                 # aynı soru en çok bu kadar turda beyne gösterilir
SEEN_GAP_SECONDS = 30 * 60
DECISIONS_FILE = "owner_decisions.md"
DECISIONS_MAX_CHARS = 8000
# Sahibe kalan kaynaklar: uzak review yeri, üst model onayı, ölçüm raporu, gönderilemeyen iş isteği
OWNER_SOURCES = frozenset({"reviewer-where", "upper_model", "dry-report", "job-red"})

_CLASSES = (
    ("credentials", r"parola|şifre|password|credential|kimlik|api[\s_-]*(?:key|anahtar)|\banahtar|secret|\btoken|"
                    r"giriş yap|\blog[\s-]?in\b|\bsign[\s-]?(?:in|up)\b|hesap aç|oturum aç(?:ar|abilir)\s*m[ıi]s[ıi]n|\b2fa\b|captcha"),
    ("spend", r"harca|\bspend|kredi|ücretli|satın|\bbuy\b|purchase|\bpaid\b|licen[cs]e|lisans|abonelik|subscri|ödeme|ödey|"
              r"\busd\b|\$\s?\d|\bdolar|\beuro?\b|€|\d\s?tl\b|fatura"),
    ("destructive", r"sıfırla|\bwipe\b|\bdrop\b|reset --hard|kalıcı olarak kald|geri alınamaz|irreversib"),
    ("external", r"\bform(?:u|un|unu|a|da|lar\w*)?\b|e-?posta|e-?mail|\bmail|yay[ıi]n|yay[ıi]ml|publi(?:sh|c)|submi(?:t|ssion)|arxiv|"
                 r"zenodo|başvur|dergiye|editöre|yazara|dışarı(?:ya)? (?:beyan|gönder)"),
    ("owner_hands", r"dene(?:r|yebilir)\s*m[ıi]s[ıi]n|sen(?:in)? dene|elle dene|fiziksel|telefon(?:da|dan|unda)|okur\s*musun|"
                    r"okuyup|okuma onay|okuduktan|bakar\s*m[ıi]s[ıi]n|can you (?:try|test|read|check)"),
)
_CLASS_RES = tuple((name, re.compile(rx, re.I)) for name, rx in _CLASSES)
_ASK_OWNER_NOTE_RE = re.compile(r"sahibe sor|sahibine sor|ask the owner", re.I)


def owner_class(q: "sw.Question", owner_projects: str = "", note: str = "", now: Optional[float] = None) -> str:
    """SAF. Soru HER ZAMAN sahibe kalıyorsa sınıf adı, beyne gidebiliyorsa ""."""
    if not q.project:
        return "no_project"
    if q.source in OWNER_SOURCES:
        return "source"
    if (q.text or "").startswith(sw.JOB_REQUEST_PREFIX):
        return "job_request"
    if q.extra_texts:
        return "combined"
    if q.deferred_until and q.deferred_until > (now or time.time()):
        return "deferred"
    if q.project in {x.strip() for x in str(owner_projects or "").split(",") if x.strip()}:
        return "owner_project"
    if _ASK_OWNER_NOTE_RE.search(note or ""):
        return "owner_project"
    blob = "\n".join([q.text or "", *(q.options or []), q.detail or "", *(q.prev_texts or [])])
    if sw.OWNER_ONLY_RE.search(blob):
        return "owner_only"
    for name, rx in _CLASS_RES:
        if rx.search(blob):
            return name
    return ""


def blocked_reason(q: "sw.Question", projects: Dict[str, Any], cfg: "sw.Config", now: Optional[float] = None) -> str:
    """SAF. `owner_class` + proje durumu: kayıtsız proje ve bitmiş/duraklatılmış proje (cevap projeyi yeniden açardı) sahibindir."""
    p = projects.get(q.project)
    if p is None:
        return "no_project"
    if p.phase in ("done", "paused"):
        return "paused"
    return owner_class(q, cfg.ask_gate_owner_projects, p.notes, now)


def tour_eligible(q: "sw.Question", projects: Dict[str, Any], cfg: "sw.Config", state: Dict[str, Any], now: float) -> bool:
    """SAF. Açık sahip sorusu bu turda beyne gösterilsin mi."""
    if q.status != "open" or q.routine or q.id in (state.get("ask_gated") or {}):
        return False
    seen = (state.get("ask_seen") or {}).get(q.id) or {}
    if int(seen.get("n") or 0) >= SEEN_MAX_TOURS or (seen and now - float(seen.get("at") or 0) < SEEN_GAP_SECONDS):
        return False
    return not blocked_reason(q, projects, cfg, now)


def passes(reply: Any, threshold: float) -> bool:
    """SAF. Kanca "izin" dese de çekirdek üç koşulu yeniden denetler: uyuşma, güven >= eşik, rutin risk."""
    if not isinstance(reply, dict):
        return False
    conf = reply.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        return False
    return reply.get("allow") is True and reply.get("agree") is True and reply.get("risk") == "routine" and conf >= threshold


def decisions_path() -> str:
    return os.path.join(str(sw.paths_for("default").root), DECISIONS_FILE)


def decisions_section(lang: str = "tr") -> str:
    """Sahibin elle düzenlediği kalıcı kararlar dosyası beyin CLAUDE.md'sine eklenecek bölüm olarak; dosya yoksa ""."""
    try:
        with open(decisions_path(), encoding="utf-8", errors="replace") as f:
            body = f.read(DECISIONS_MAX_CHARS).strip()
    except OSError:
        return ""
    if not body:
        return ""
    title = "## Owner's standing decisions" if lang == "en" else "## Sahibin güncel kalıcı kararları (owner_decisions.md)"
    return f"\n{title}\n{body}\n"
