"""Detaysız sahip sorusuna ucuz modelle otomatik "Detay" (Markdown) üretimi.

Kurallar: model en ucuz yeterli (Haiku; Opus/Fable YOK); aynı soru (metin+seçenek) için TEK üretim, sonuç (başarısız deneme de)
önbellekte; günlük üretim tavanı; her hata SESSİZCE detaysız düşer (soru akışı asla bozulmaz). Ağır iş değil: tek `claude -p`
çağrısı `nice -n 19`/`ionice -c3` ile, arka plan iş parçacığında (çağıran bloklanmaz)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from typing import Any, Callable, Optional

MODEL = "claude-haiku-4-5-20251001"
DAILY_CAP = 20
TIMEOUT = 90
MAX_DETAIL = 3000
_LOCK = threading.Lock()

_PROMPT = (
    "Aşağıdaki değnekçi sorusunu sahibe, bağlamı hatırlamadığını varsayarak, düz Türkçeyle ve KISA Markdown ile açıkla. "
    "Başlıklar: **Durum** (ne oluyor, neden soruluyor), **Seçenekler** (her birinin sonucu/bedeli; seçenek yoksa makul yollar), "
    "**Öneri** (tek öneri + gerekçe). Jargon/kısaltmaları aç. Soruda olmayan olgu UYDURMA; bilmediğini 'soruda belirtilmemiş' de. "
    "En çok 250 kelime. Yalnız Markdown gövdesini yaz.\n\nProje: {project}\nSoru: {text}\nSeçenekler: {options}\n")


def _key(q: Any) -> str:
    raw = f"{q.text}\x00{'|'.join(q.options or [])}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write(path: str, d: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def _claude_runner(prompt: str) -> str:
    cmd = ["claude", "-p", prompt, "--model", MODEL]
    for pre in (["ionice", "-c3"], ["nice", "-n", "19"]):
        if subprocess.run(["which", pre[0]], capture_output=True).returncode == 0:
            cmd = pre + cmd
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, env={**os.environ, "OMP_NUM_THREADS": "4"})
    if out.returncode != 0:
        raise RuntimeError(out.stderr[:200])
    return out.stdout


def generate_detail(q: Any, runner: Optional[Callable[[str], str]] = None, cache_path: str = "", daily_cap: int = DAILY_CAP,
                    now: Optional[float] = None) -> str:
    """Soru için detay döndürür ("" = yok). Önbellekte varsa model çağrılmaz; tavan dolduysa ya da hata olursa "" (sessiz)."""
    now = time.time() if now is None else now
    runner = runner or _claude_runner
    key = _key(q)
    day = str(int(now // 86400))
    with _LOCK:
        d = _read(str(cache_path))
        ent = (d.get("entries") or {}).get(key)
        if ent is not None:
            return str(ent.get("detail") or "")
        days = d.get("days") or {}
        if int(days.get(day, 0)) >= daily_cap:
            return ""
        days = {day: int(days.get(day, 0)) + 1}      # yalnız bugünün sayacı kalır
        d["days"] = days
        _write(str(cache_path), d)                   # deneme ÖNCE sayılır: çökse de tavan korunur
    detail = ""
    try:
        detail = str(runner(_PROMPT.format(project=q.project or "degnekci", text=q.text,
                                           options="; ".join(q.options or []) or "(yok, serbest metin)"))).strip()[:MAX_DETAIL]
    except Exception:
        detail = ""
    with _LOCK:
        d = _read(str(cache_path))
        d.setdefault("entries", {})[key] = {"detail": detail, "at": now}
        _write(str(cache_path), d)
    return detail


def cache_path_for(questions_path: str) -> str:
    return os.path.join(os.path.dirname(str(questions_path)), "question_detail_cache.json")


def ensure_async(q: Any, paths: Any, runner: Optional[Callable[[str], str]] = None) -> None:
    """Açık, sahibe giden, detaysız soru için arka planda üret ve soruya yaz (çağıranı bloklamaz; her hata sessiz)."""
    from . import steward as sw
    if q.detail or q.routine or q.status != "open":
        return

    def work() -> None:
        try:
            det = generate_detail(q, runner=runner, cache_path=cache_path_for(sw._pp(paths).questions))
            if det:
                sw.set_question_detail(q.id, det, paths)
        except Exception:
            pass
    threading.Thread(target=work, name="qdetail", daemon=True).start()
