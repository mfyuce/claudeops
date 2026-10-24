"""ucli dersleri köprüsü: reviewer kimliğinin `ucli-lessons.md` satırları, ucli projesinin ÇALIŞAN oturumuna direktifle
iletilir (başka reponun dosyasına YAZILMAZ: o repoyu başka oturum auto-commit'ler; sahip kararı 2026-10-24).

Saf planlayıcı (`plan_lesson_deliveries`) + gönderilenleri işaretleme. Gönderilen satırlar ALICI kimliğin `state.json`unda
satır özetiyle tutulur (`lessons_sent`): aynı satır iki kez gitmez. Kapı `deliver_job` ile aynı: oturum meşgul ya da alt
ajanı çalışıyorsa sonraki tick; çalışmıyorsa BEKLER (yalnız ders için oturum AÇILMAZ)."""
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import steward as sw

LESSONS_FILE = "ucli-lessons.md"
AUTO_TAG = "- [otomatik] "   # reviewer'ın kendi yazdığı satırlar; elle/başka oturumun eklediği notlar iletilmez
SENT_MAX = 500          # `lessons_sent` üst sınırı (en eskiler düşer)
BATCH_MAX = 5           # bir mesajda en çok bu kadar ders
FAIL_MAX = 5            # bir ders bu kadar başarısız iletimden sonra bırakılır
LINE_CHARS = 700        # mesajdaki ders satırı üst sınırı


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


def build_lesson_message(lines: List[str], lang: str = "tr") -> str:
    """Proje oturumuna gidecek ders bildirimi (`extra` olarak direktif şablonuna gömülür)."""
    body = "\n".join(ln[:LINE_CHARS] for ln in lines)
    if lang == "en":
        return ("[reviewer lessons] The reviewer could not finish these model/project pairs with ucli. For each: find the "
                "cause, write it to TODO/TBD and fix it. Do not re-open lessons already handled.\n" + body)
    return ("[reviewer dersleri] Reviewer aşağıdaki model/proje çiftlerinde ucli ile review'u bitiremedi. Her biri için: "
            "nedenini bul, TODO/TBD'ye yaz ve düzelt. Zaten işlenmiş dersi yeniden açma.\n" + body)


def mark_sent(hashes: List[str], paths: Any = None) -> None:
    """İletim BAŞARILI: özetler `lessons_sent`e eklenir (üst sınır SENT_MAX), başarısızlık sayaçları temizlenir."""
    with sw.steward_lock(paths):
        st = sw.load_state(paths)
        sent = [h for h in (st.get("lessons_sent") or []) if h not in hashes] + list(hashes)
        st["lessons_sent"] = sent[-SENT_MAX:]
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
