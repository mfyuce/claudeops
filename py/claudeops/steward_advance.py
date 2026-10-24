"""İlerletme değnekçisi (`advance_findings=on` kimliği): sahibin onayladığı (`exported`) review bulgularını, kimliğin KENDİ
projesinin çalışan oturumuna direktifle iletir. Tasarım: `docs/ilerlet-plan.md` (özel notlar).

Saf planlayıcı + mesaj + gönderilenleri işaretleme. Commit/push/restart YAPMAZ; mesaj oturuma bunun için projenin notunda
açık izin aranmasını söyler. Başka kimliğin projesine, uzak host'a, kapalı oturuma dokunmaz (oturum AÇILMAZ)."""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import steward as sw

BATCH_MAX = 3                  # bir direktifte en çok bu kadar bulgu
RESEND_SECONDS = 12 * 3600     # aynı bulgu en sık bu aralıkla yeniden iletilir (TODO satırı hâlâ açıksa)
SEND_MAX = 3                   # bir bulgu en çok bu kadar iletilir
SENT_KEEP = 1000
TODO_MAX_BYTES = 2_000_000
_SEV = {"P1": 0, "P2": 1, "P3": 2}
# Parola/gizli değer içeren düzeltmeler (rotasyon, kodda sabit parola ...) sahibin kararıdır: ilerletme bunları ASLA
# iletmez (sahip 2026-10-24: "parola içeren düzeltmeleri ilk iş yapma"); TODO/TBD'de kalır, sahip elle yönlendirir.
_SENSITIVE_RE = re.compile(r"parola|şifre|sifre|password|passwd|credential|secret|api[ _-]?key|\bdsn\b|gizli (?:değer|anahtar)",
                           re.IGNORECASE)


def is_sensitive(rec: Dict[str, Any]) -> bool:
    return bool(_SENSITIVE_RE.search(f"{rec.get('title') or ''} {rec.get('where') or ''}"))


def todo_status(path: str, cwd: str, fid: str) -> str:
    """Bulgunun `(review <fid>)` satırı: "open" (`- [ ]`), "done" (`- [x]`), "missing" (dosya/satır yok ya da dosya proje
    klasörü DIŞINDA). Yol güvenliği: gerçek yol `cwd` altında olmalı, 2 MB sınırı, okunamazsa "missing"."""
    if not path or not cwd:
        return "missing"
    try:
        real, root = os.path.realpath(path), os.path.realpath(cwd)
        if not real.startswith(root + os.sep) or os.path.getsize(real) > TODO_MAX_BYTES:
            return "missing"
        with open(real, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return "missing"
    mark = f"(review {fid})"
    for ln in text.splitlines():
        if mark in ln:
            m = re.match(r"\s*[-*]\s*\[([ xX])\]", ln)
            return "done" if m and m.group(1).lower() == "x" else "open"
    return "missing"


def candidates(findings_by_sid: Iterable[Dict[str, Any]], cwd_of) -> List[Dict[str, Any]]:
    """Reviewer `findings.json` sözlüklerinden `exported` bulgular + TODO durumu: [{id, project, severity, where, title,
    todo}]. `cwd_of(proje)` proje klasörünü verir ("" = bilinmiyor)."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for data in findings_by_sid:
        for fid, rec in (data.items() if isinstance(data, dict) else []):
            if not isinstance(rec, dict) or rec.get("state") != "exported" or fid in seen or is_sensitive(rec):
                continue
            seen.add(fid)
            proj = str(rec.get("project") or "")
            out.append({"id": fid, "project": proj, "severity": str(rec.get("severity") or ""),
                        "where": str(rec.get("where") or ""), "title": " ".join(str(rec.get("title") or "").split())[:200],
                        "file": str(rec.get("exported_to") or ""),
                        "todo": todo_status(str(rec.get("exported_to") or ""), cwd_of(proj) if proj else "", fid)})
    return out


def plan_advance_deliveries(views: List[Any], projects: Dict[str, Any], cands: List[Dict[str, Any]],
                            state: Dict[str, Any], now: float, planned: List[sw.Action],
                            world: Optional[sw.World] = None, limit: int = 1) -> Tuple[List[sw.Action], Dict[str, Any]]:
    """Açık (`todo=open`) bulguları KİMLİĞİN projesinin çalışan, boşta oturumuna iletecek `deliver_findings` eylemleri.
    P1 önce; proje başına tek eylem, tick başına en çok `limit`. Proje bu kimliğin değilse, oturum yoksa/meşgulse/alt ajanı
    varsa ya da `planned` aynı oturuma dokunmuşsa bekler. SAF."""
    if not cands:
        return [], state
    if world is not None:
        projects = world.own_projects(projects)
    sent = state.get("advance_sent") or {}
    mine = [v for v in views if sw._is_project_session(v, projects)
            and (world is None or world.session_class(v.name, v.blueprint) == "own")]
    taken = {a.name for a in planned}
    by_proj: Dict[str, List[Dict[str, Any]]] = {}
    for c in cands:
        if c["project"] not in projects or c["todo"] != "open":
            continue
        rec = sent.get(c["id"]) or {}
        if int(rec.get("n") or 0) >= SEND_MAX or now - float(rec.get("at") or 0) < RESEND_SECONDS:
            continue
        by_proj.setdefault(c["project"], []).append(c)
    out: List[sw.Action] = []
    lda: Optional[Dict[str, float]] = None
    for proj in sorted(by_proj):
        rows = sorted(by_proj[proj], key=lambda c: (_SEV.get(c["severity"], 9), c["id"]))[:BATCH_MAX]
        v = sw.pick_delivery_view(mine, proj, "")
        if (v is None or v.busy or getattr(v, "subagent_active", False) or getattr(v, "subagent_unknown", False)
                or v.name in taken):
            continue
        out.append(sw.Action("deliver_findings", v.name, "advance", {"project": proj, "rows": rows}))
        taken.add(v.name)
        if lda is None:
            lda = dict(state.get("last_directive_at") or {})
        lda[v.name] = now
        if len(out) >= limit:
            break
    if lda is None:
        return [], state
    st = dict(state)
    st["last_directive_at"] = lda
    return out, st


def build_advance_message(rows: List[Dict[str, Any]], lang: str = "tr") -> str:
    """Proje oturumuna gidecek direktif (`extra`). Yetki sınırı METİNDE: commit/push/restart yalnız proje notundaki izinle."""
    files = sorted({r["file"] for r in rows if r.get("file")})
    where = ", ".join(files)
    items = "\n".join(f"- {r['id']} | {r.get('severity') or '?'} | {r.get('where') or '?'} | {r.get('title') or ''}" for r in rows)
    if lang == "en":
        return ("[review findings] The owner approved these findings; they are in the project's TODO/TBD as `(review <id>)` "
                "lines (unchecked)" + (f", in the file(s): {where}" if where else "") + ". Work them one by one:\n" + items + "\n"
                "1) Re-check the finding against the CURRENT code. If it is wrong, mark the line `[x]` and write why "
                "(\"rejected: ...\"). 2) If it is real, fix it, run the tests, mark the line `[x]` and add one line to DONE.md. "
                "3) Commit, push or restart a service ONLY if this project's notes (CLAUDE.md) explicitly allow it; otherwise "
                "do not, and tell the owner. 4) Touch nothing outside this project.")
    return ("[review bulguları] Sahibin onayladığı bulgular projenin TODO/TBD dosyasında `(review <kimlik>)` satırı olarak "
            "(işaretsiz) duruyor" + (f"; dosya: {where}" if where else "") + ". Sırayla ele al:\n" + items + "\n"
            "1) Bulguyu GÜNCEL koda karşı yeniden doğrula. Yanlışsa satırı `[x]` yap ve nedenini yaz (\"reddedildi: ...\"). "
            "2) Gerçekse düzelt, testleri çalıştır, satırı `[x]` yap, DONE.md'ye tek satır ekle. "
            "3) Commit, push ya da servis restart'ı YALNIZ bu projenin notunda (CLAUDE.md) açıkça izin varsa yap; yoksa "
            "yapma ve sahibine söyle. 4) Bu proje dışındaki hiçbir şeye dokunma.")


def mark_sent(fids: List[str], now: float, paths: Any = None) -> None:
    """İletim BAŞARILI: bulgu başına `{at, n}` (alıcı kimliğin state.json'unda; reviewer'ın findings.json'una YAZILMAZ)."""
    with sw.steward_lock(paths):
        st = sw.load_state(paths)
        sent = dict(st.get("advance_sent") or {})
        for f in fids:
            sent[f] = {"at": now, "n": int((sent.get(f) or {}).get("n") or 0) + 1}
        if len(sent) > SENT_KEEP:
            for k in sorted(sent, key=lambda x: float(sent[x].get("at") or 0))[:len(sent) - SENT_KEEP]:
                sent.pop(k, None)
        st["advance_sent"] = sent
        sw.save_state(st, paths)
