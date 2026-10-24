"""İlerletme değnekçisi (`advance_findings=on` kimliği): sahibin onayladığı (`exported`) review bulgularını, kimliğin KENDİ
projesinin çalışan oturumuna direktifle iletir. Tasarım: `docs/ilerlet-plan.md` (özel notlar).

Saf planlayıcı + mesaj + gönderilenleri işaretleme. Commit/push/restart YAPMAZ; mesaj oturuma bunun için projenin notunda
açık izin aranmasını söyler. Başka kimliğin projesine, kapalı oturuma dokunmaz (oturum AÇILMAZ).

UZAK proje (TBD#117 ek 3): export uzakta kapalı olduğundan aday `approved` bulgudur (TODO denetimi atlanır, `todo=open`
sayılır); mesaj bulgu ayrıntısını taşır ve uzak oturumdan satırı kendi TODO.md'sine eklemesini ister. İletim `_give_directive`
+ host ile gider, `advance_sent` takibi YERELDE (beyin yerel kalır). Uzakta geri bildirim (TODO `[x]`) okunamadığından
bulgu bir kez iletilir (`SEND_MAX_REMOTE`)."""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import steward as sw

BATCH_MAX = 3                  # bir direktifte en çok bu kadar bulgu
RESEND_SECONDS = 12 * 3600     # aynı bulgu en sık bu aralıkla yeniden iletilir (TODO satırı hâlâ açıksa)
SEND_MAX = 3                   # bir bulgu en çok bu kadar iletilir
SEND_MAX_REMOTE = 1            # uzak TODO okunamazsa (yeniden gönderme kararı verilemez): tek iletim; okunup satır yoksa SEND_MAX
BODY_MAX = 700                 # uzak mesajda bulgu başına gövde sınırı
SENT_KEEP = 1000
TODO_MAX_BYTES = 2_000_000
_SEV = {"P1": 0, "P2": 1, "P3": 2}
# Parola/gizli değer içeren düzeltmeler (rotasyon, kodda sabit parola ...) sahibin kararıdır: ilerletme bunları ASLA
# iletmez (sahip 2026-10-24: "parola içeren düzeltmeleri ilk iş yapma"); TODO/TBD'de kalır, sahip elle yönlendirir.
_SENSITIVE_RE = re.compile(r"parola|şifre|sifre|password|passwd|credential|secret|api[ _-]?key|\bdsn\b|gizli (?:değer|anahtar)",
                           re.IGNORECASE)


def is_sensitive(rec: Dict[str, Any], body: bool = False) -> bool:
    """`body=True` (uzak aday): gövde de iletildiği için o da taranır."""
    return bool(_SENSITIVE_RE.search(f"{rec.get('title') or ''} {rec.get('where') or ''}" + (f" {rec.get('body') or ''}" if body else "")))


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
    return todo_status_text(text, fid)


def todo_status_text(text: str, fid: str) -> str:
    """`todo_status`un saf çekirdeği: metindeki `(review <fid>)` satırı -> open | done | missing."""
    mark = f"(review {fid})"
    for ln in text.splitlines():
        if mark in ln:
            m = re.match(r"\s*[-*]\s*\[([ xX])\]", ln)
            return "done" if m and m.group(1).lower() == "x" else "open"
    return "missing"


def candidates(findings_by_sid: Iterable[Dict[str, Any]], cwd_of, remote_of=None, remote_todo_of=None) -> List[Dict[str, Any]]:
    """Reviewer `findings.json` sözlüklerinden aday bulgular + TODO durumu: [{id, project, severity, where, title, todo,
    remote, body}]. `cwd_of(proje)` proje klasörünü verir ("" = bilinmiyor). Yerel proje: `exported` + TODO satırı denetimi.
    `remote_of(proje)` (host, "" = yerel) uzak ise: `approved` ya da `exported` bulgu, TODO denetimi YOK (`todo=open`),
    gövde mesaja gider (uzak TODO.md'ye bu taraf yazamaz)."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for data in findings_by_sid:
        for fid, rec in (data.items() if isinstance(data, dict) else []):
            if not isinstance(rec, dict) or fid in seen:
                continue
            proj = str(rec.get("project") or "")
            host = (remote_of(proj) if remote_of and proj else "") or ""
            if host:
                if rec.get("state") not in ("approved", "exported") or is_sensitive(rec, body=True):
                    continue
            elif rec.get("state") != "exported" or is_sensitive(rec):
                continue
            seen.add(fid)
            row = {"id": fid, "project": proj, "severity": str(rec.get("severity") or ""),
                   "where": str(rec.get("where") or ""), "title": " ".join(str(rec.get("title") or "").split())[:200],
                   "file": str(rec.get("exported_to") or "")}
            if host:
                row.update(todo="open", remote=host, file="", body=" ".join(str(rec.get("body") or "").split())[:BODY_MAX])
                st = (remote_todo_of(proj, fid) if remote_todo_of else "") or ""
                if st == "done":        # uzak oturum satırı kapattı: aday değil
                    row["todo"] = "done"
                elif st == "open":      # uzak oturum satırı kendi TODO'suna ekledi: izlenir, yeniden gönderme yok
                    row["remote_state"] = "tracked"
                elif st == "missing":   # TODO okundu, satır yok: oturum yok saydı, yeniden gönderilebilir
                    row["remote_state"] = "missing"
            else:
                row["todo"] = todo_status(str(rec.get("exported_to") or ""), cwd_of(proj) if proj else "", fid)
            out.append(row)
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
        if c["project"] not in projects or c["todo"] != "open" or projects[c["project"]].phase == "paused":
            continue
        rec = sent.get(c["id"]) or {}
        if c.get("remote_state") == "tracked":
            continue
        cap = SEND_MAX if (not c.get("remote") or c.get("remote_state") == "missing") else SEND_MAX_REMOTE
        if int(rec.get("n") or 0) >= cap or now - float(rec.get("at") or 0) < RESEND_SECONDS:
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
    if any(r.get("remote") for r in rows):
        return _build_remote_message(rows, lang)
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


def _build_remote_message(rows: List[Dict[str, Any]], lang: str) -> str:
    """Uzak oturum için: bulgular bu projenin TODO'sunda YOK (sahip onayladı, dışa aktarım uzakta kapalı); ayrıntı mesajda."""
    items = "\n".join(f"- {r['id']} | {r.get('severity') or '?'} | {r.get('where') or '?'} | {r.get('title') or ''}"
                      + (f"\n  {r['body']}" if r.get("body") else "") for r in rows)
    if lang == "en":
        return ("[review findings] The owner approved these findings for this project; they are NOT in your TODO yet:\n" + items + "\n"
                "1) Add each to the project's TODO.md as `- [ ] (review <id>) [<severity>] <where>: <title>`. 2) Re-check it "
                "against the CURRENT code. If wrong, mark `[x]` and write why (\"rejected: ...\"). 3) If real, fix it, run the "
                "tests, mark `[x]` and add one line to DONE.md. 4) Commit, push or restart a service ONLY if this project's "
                "notes (CLAUDE.md) explicitly allow it; otherwise do not, and tell the owner. 5) Touch nothing outside this project.")
    return ("[review bulguları] Sahibin bu proje için onayladığı bulgular (henüz TODO'nda YOK):\n" + items + "\n"
            "1) Her birini projenin TODO.md'sine `- [ ] (review <kimlik>) [<önem>] <yer>: <başlık>` satırı olarak ekle. "
            "2) GÜNCEL koda karşı yeniden doğrula; yanlışsa satırı `[x]` yap ve nedenini yaz (\"reddedildi: ...\"). "
            "3) Gerçekse düzelt, testleri çalıştır, satırı `[x]` yap, DONE.md'ye tek satır ekle. "
            "4) Commit, push ya da servis restart'ı YALNIZ bu projenin notunda (CLAUDE.md) açıkça izin varsa yap; yoksa "
            "yapma ve sahibine söyle. 5) Bu proje dışındaki hiçbir şeye dokunma.")


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
