"""TBD#142: soru-cevapların CLI'dan bağımsız kalıcı kaydı — projenin `-prv/SORU-CEVAP.md` dosyasına TEK SATIR ekler.

Kurallar: dosya YOKSA oluşturulmaz (yalnız var olana eklenir); yazma hatası asla fırlatmaz (kayıt yardımcıdır, asıl akışı
bozmaz); satır sonları boşluğa indirilir; `O_APPEND` tek `write` (satır atomik). Yol: `<local_path>-prv/SORU-CEVAP.md`
(proje `local_path`'inin kardeş `-prv` dizini); `local_path` boşsa kayıt atlanır.
"""
from __future__ import annotations

import os
import time
from typing import Optional

FILENAME = "SORU-CEVAP.md"
_MAX = 600


def qa_path(local_path: str) -> Optional[str]:
    lp = (local_path or "").strip().rstrip("/")
    if not lp:
        return None
    return os.path.join(lp + "-prv", FILENAME)


def _one_line(s: str) -> str:
    return " ".join(str(s or "").split())


def append_qa(local_path: str, kind: str, actor: str, text: str, *, ref: str = "", now: Optional[float] = None) -> bool:
    """`- <tarih> [kind] actor (ref): text` ekler. True = yazıldı; dosya/dizin yok ya da hata = False."""
    p = qa_path(local_path)
    if not p or not os.path.isfile(p):
        return False
    t = time.localtime(time.time() if now is None else now)
    body = _one_line(text)
    if len(body) > _MAX:
        body = body[:_MAX - 1] + "…"
    line = f"- {time.strftime('%Y-%m-%d %H:%M', t)} [{_one_line(kind) or '?'}] {_one_line(actor) or '?'}"
    if ref:
        line += f" ({_one_line(ref)})"
    line += f": {body}\n"
    try:
        fd = os.open(p, os.O_WRONLY | os.O_APPEND)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except OSError:
        return False
