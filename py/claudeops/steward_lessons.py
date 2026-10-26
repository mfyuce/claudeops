"""ucli dersleri köprüsü: reviewer kimliğinin `ucli-lessons.md` satırları, ucli projesinin ÇALIŞAN oturumuna direktifle
iletilir (başka reponun dosyasına YAZILMAZ: o repoyu başka oturum auto-commit'ler; sahip kararı 2026-10-24).

Saf planlayıcı (`plan_lesson_deliveries`) + gönderilenleri işaretleme. Gönderilen satırlar ALICI kimliğin `state.json`unda
satır özetiyle tutulur (`lessons_sent`): aynı satır iki kez gitmez. Kapı `deliver_job` ile aynı: oturum meşgul ya da alt
ajanı çalışıyorsa sonraki tick; çalışmıyorsa BEKLER (yalnız ders için oturum AÇILMAZ)."""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import steward as sw

LESSONS_FILE = "ucli-lessons.md"
AUTO_TAG = "- [otomatik] "   # reviewer'ın kendi yazdığı satırlar; elle/başka oturumun eklediği notlar iletilmez
SENT_MAX = 500          # `lessons_sent` üst sınırı (en eskiler düşer)
BATCH_MAX = 5           # bir mesajda en çok bu kadar ders
FAIL_MAX = 5            # bir ders bu kadar başarısız iletimden sonra bırakılır
LINE_CHARS = 700        # mesajdaki ders satırı üst sınırı
FILE_MAX = 200          # dosyada tutulan `AUTO_TAG` satırı üst sınırı (en eskiler düşer; elle notlara dokunulmaz)


def target_project(value: Any) -> str:
    """`lessons_project` ayarından hedef proje adı; kapalı = "". Ayarlarda boş değer anahtarı SİLER (varsayılana döner), bu
    yüzden kapatmak için `off` (ya da `none`/`-`) yazılır."""
    v = str(value or "").strip()
    return "" if v.lower() in ("", "off", "none", "-", "kapalı") else v


def line_hash(line: str) -> str:
    return hashlib.sha1(" ".join(str(line).split()).encode("utf-8")).hexdigest()[:12]


def read_lessons(roots: Iterable[str]) -> List[Tuple[str, str]]:
    """Verilen çalışma alanlarındaki `ucli-lessons.md` satırları: [(özet, satır)], dosya sırasıyla, yinelenen özet tek.
    Okunamayan dosya sessizce atlanır. Yalnız `AUTO_TAG` ile başlayan satırlar ders sayılır."""
    out: List[Tuple[str, str]] = []
    seen = set()
    for root in roots:
        try:
            with open(os.path.join(root, LESSONS_FILE), encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln.startswith(AUTO_TAG):
                continue
            h = line_hash(ln)
            if h not in seen:
                seen.add(h)
                out.append((h, ln))
    return out


def prune_lessons(text: str, keep: int = FILE_MAX) -> str:
    """`AUTO_TAG` satırlarından yalnız SON `keep` tanesini bırakır; başka satırlar (başlık, elle not) olduğu gibi kalır."""
    lines = text.splitlines(keepends=True)
    auto = [i for i, ln in enumerate(lines) if ln.startswith(AUTO_TAG)]
    drop = set(auto[:-keep]) if keep > 0 and len(auto) > keep else set()
    return "".join(ln for i, ln in enumerate(lines) if i not in drop) if drop else text


def pending(lessons: List[Tuple[str, str]], state: Dict[str, Any]) -> List[Tuple[str, str]]:
    sent = set(state.get("lessons_sent") or [])
    fails = state.get("lessons_fail") or {}
    return [(h, ln) for h, ln in lessons if h not in sent and int(fails.get(h) or 0) < FAIL_MAX]


def plan_lesson_deliveries(views: List[Any], projects: Dict[str, Any], lessons: List[Tuple[str, str]],
                           state: Dict[str, Any], now: float, project: str, planned: List[sw.Action],
                           world: Optional[sw.World] = None) -> Tuple[List[sw.Action], Dict[str, Any]]:
    """Gönderilmemiş dersleri `project`in çalışan, boşta oturumuna iletecek TEK `deliver_lesson` eylemi (en çok BATCH_MAX
    ders). Proje bu kimliğin değilse, çalışan oturum yoksa, oturum meşgulse/alt ajanı varsa ya da `planned` aynı oturuma
    dokunmuşsa hiçbir şey. SAF."""
    if not project or not lessons:
        return [], state
    todo = pending(lessons, state)
    if not todo:
        return [], state
    if world is not None:
        projects = world.own_projects(projects)
    if project not in projects:
        return [], state
    mine = [v for v in views if sw._is_project_session(v, projects)
            and (world is None or world.session_class(v.name, v.blueprint) == "own")]
    v = sw.pick_delivery_view(mine, project, "")
    if v is None or v.busy or getattr(v, "subagent_active", False) or getattr(v, "subagent_unknown", False):
        return [], state
    if v.name in {a.name for a in planned}:
        return [], state
    batch = todo[:BATCH_MAX]
    lda = dict(state.get("last_directive_at") or {})
    lda[v.name] = now
    st = dict(state)
    st["last_directive_at"] = lda
    return [sw.Action("deliver_lesson", v.name, "lesson",
                      {"project": project, "hashes": [h for h, _ in batch], "lines": [ln for _, ln in batch]})], st


ACK_STATUSES = ("todo", "tbd", "fixed", "no-action", "duplicate")   # `STEWARD-LESSON: <id> <durum> [not]` durumları
DONE_MAX = 500          # `lessons_done` üst sınırı
STALE_HOURS = 24        # iletildi ama bu kadar süre onaysız kalan ders UI'da "onay yok" uyarısı alır


def build_lesson_message(lines: List[str], lang: str = "tr", ids: Optional[List[str]] = None) -> str:
    """Proje oturumuna gidecek ders bildirimi (`extra` olarak direktif şablonuna gömülür). `ids` verilirse her satır
    `[id]` ile başlar ve oturumdan işleyince onay satırı (`STEWARD-LESSON: <id> <durum> [not]`) istenir."""
    rows = [ln[:LINE_CHARS] for ln in lines]
    if ids and len(ids) == len(rows):
        rows = [f"[{i}] {r}" for i, r in zip(ids, rows)]
    body = "\n".join(rows)
    ack_tr = ("" if not ids else
              f"\nHer ders işlenince yanıtının SONUNDA, satır başında ayrı satır olarak onayla: `{sw.MARK_LESSON} <id> <durum> [kısa not]`; "
              f"durum: {'|'.join(ACK_STATUSES)} (todo/tbd: TODO.md/TOBEDECIDED.md'ye yazdım, fixed: düzelttim, no-action: gerekçeyle işlem yok, duplicate: zaten işlenmiş).")
    ack_en = ("" if not ids else
              f"\nWhen a lesson is handled, confirm it at the END of your reply, one line each, at line start: `{sw.MARK_LESSON} <id> <status> [short note]`; "
              f"status: {'|'.join(ACK_STATUSES)} (todo/tbd: written to TODO.md/TOBEDECIDED.md, fixed: fixed, no-action: nothing to do, with reason, duplicate: already handled).")
    if lang == "en":
        return ("[reviewer lessons] The reviewer could not finish these model/project pairs with ucli. For each: find the "
                "cause, write it to TODO/TBD and fix it. Do not re-open lessons already handled." + ack_en + "\n" + body)
    return ("[reviewer dersleri] Reviewer aşağıdaki model/proje çiftlerinde ucli ile review'u bitiremedi. Her biri için: "
            "nedenini bul, TODO/TBD'ye yaz ve düzelt. Zaten işlenmiş dersi yeniden açma." + ack_tr + "\n" + body)


def parse_ack(text: str) -> Optional[Tuple[str, str, str]]:
    """`<id> <durum> [not]` -> (id, durum, not); biçim/durum geçersizse None. Kimlik 12 onaltılık karakter."""
    parts = str(text or "").strip().strip("`").split(None, 2)
    if len(parts) < 2:
        return None
    hid, status = parts[0].strip("[]`").lower(), parts[1].strip("`,.:;").lower()
    if len(hid) != 12 or any(c not in "0123456789abcdef" for c in hid) or status not in ACK_STATUSES:
        return None
    return hid, status, (parts[2].strip() if len(parts) > 2 else "")[:300]


def mark_done(hid: str, status: str, note: str, session: str, now: float, paths: Any = None) -> bool:
    """Oturumun onayını yazar. Yalnız bu kimliğe GÖNDERİLMİŞ ders onaylanabilir (uydurma kimlik yok sayılır); ilk onay
    kalır (tekrarı değiştirmez). Dönen: yeni kayıt yazıldı mı."""
    with sw.steward_lock(paths):
        st = sw.load_state(paths)
        if hid not in (st.get("lessons_sent") or []):
            return False
        done = dict(st.get("lessons_done") or {})
        if hid in done:
            return False
        done[hid] = {"at": now, "status": status, "note": note, "session": session}
        if len(done) > DONE_MAX:
            done = dict(list(done.items())[-DONE_MAX:])
        st["lessons_done"] = done
        sw.save_state(st, paths)
    return True


def resend(hid: str, paths: Any = None) -> bool:
    """Dersi yeniden iletilebilir yapar: gönderildi/başarısız/onay kayıtlarını siler. Dönen: kayıt vardı mı."""
    with sw.steward_lock(paths):
        st = sw.load_state(paths)
        had = hid in (st.get("lessons_sent") or []) or hid in (st.get("lessons_fail") or {}) or hid in (st.get("lessons_done") or {})
        if not had:
            return False
        st["lessons_sent"] = [h for h in (st.get("lessons_sent") or []) if h != hid]
        for k in ("lessons_fail", "lessons_done", "lessons_sent_at"):
            d = dict(st.get(k) or {})
            d.pop(hid, None)
            st[k] = d
        sw.save_state(st, paths)
    return had


def lesson_rows(lessons: List[Tuple[str, str]], states: List[Dict[str, Any]], now: float) -> List[Dict[str, Any]]:
    """UI satırları: durum = pending (hiç gitmedi) | failed (iletim FAIL_MAX kez başarısız) | sent (iletildi, onay yok) |
    stale (iletildi, STALE_HOURS saattir onay yok) | done (oturum onayladı: `ack` = durum). `states`: alıcı kimliklerin
    state sözlükleri (ders yalnız birinde gönderilmiş olur). `sent_at` yalnız bu sürümden sonra gönderilenlerde var (eskiler hiç `stale` olmaz)."""
    sent, fails, done, sent_at = set(), {}, {}, {}
    for st in states:
        sent |= set(st.get("lessons_sent") or [])
        sent_at.update(st.get("lessons_sent_at") or {})
        for h, n in (st.get("lessons_fail") or {}).items():
            fails[h] = max(int(n or 0), fails.get(h, 0))
        done.update(st.get("lessons_done") or {})
    out = []
    for h, ln in lessons:
        d = done.get(h)
        if d:
            status = "done"
        elif h in sent:
            at = sent_at.get(h)
            status = "stale" if at and now - float(at) > STALE_HOURS * 3600 else "sent"
        elif int(fails.get(h) or 0) >= FAIL_MAX:
            status = "failed"
        else:
            status = "pending"
        out.append({"id": h, "line": ln[len(AUTO_TAG):] if ln.startswith(AUTO_TAG) else ln, "status": status,
                    "fails": int(fails.get(h) or 0), "sent_at": sent_at.get(h), "ack": (d or {}).get("status", ""), "note": (d or {}).get("note", ""),
                    "ack_at": (d or {}).get("at"), "session": (d or {}).get("session", "")})
    return out


def mark_sent(hashes: List[str], paths: Any = None) -> None:
    """İletim BAŞARILI: özetler `lessons_sent`e eklenir (üst sınır SENT_MAX), başarısızlık sayaçları temizlenir."""
    with sw.steward_lock(paths):
        st = sw.load_state(paths)
        sent = [h for h in (st.get("lessons_sent") or []) if h not in hashes] + list(hashes)
        st["lessons_sent"] = sent[-SENT_MAX:]
        at = dict(st.get("lessons_sent_at") or {})
        now = time.time()
        for h in hashes:
            at[h] = now
        st["lessons_sent_at"] = {h: t for h, t in at.items() if h in st["lessons_sent"]}
        fails = dict(st.get("lessons_fail") or {})
        for h in hashes:
            fails.pop(h, None)
        st["lessons_fail"] = fails
        sw.save_state(st, paths)


def mark_failed(hashes: List[str], paths: Any = None) -> None:
    with sw.steward_lock(paths):
        st = sw.load_state(paths)
        fails = dict(st.get("lessons_fail") or {})
        for h in hashes:
            fails[h] = int(fails.get(h) or 0) + 1
        st["lessons_fail"] = fails
        sw.save_state(st, paths)
