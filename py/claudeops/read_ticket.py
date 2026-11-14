"""Kısa ömürlü, imzalı OKUMA bileti: tek bir dosya (host + oturum adı + yol) için, panel token'ı URL'e GİRMEDEN, aynı kökenden
okunabilir bağlantı (`/readfile/<bilet>/<ad>`). Kullanım: panel Dosyalar'dan "Reader'da oku" (hcr `?file-url=` same-origin fetch).
Bilet = base64url(json{n,p,h,e}) + "." + HMAC-SHA256(token). Süre dolunca ya da imza tutmazsa geçersiz; yalnız OKUMA, yalnız o dosya."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import os
from typing import Any, Dict, Optional
from urllib.parse import unquote

TTL_SECONDS = 1800
MAX_TICKET = 2048


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sig(token: str, body: str) -> str:
    return _b64(hmac.new(token.encode("utf-8"), b"claudeops-read-ticket:" + body.encode("ascii"), hashlib.sha256).digest())


def issue(token: str, name: str, path: str, host: str, now: Optional[float] = None, ttl: int = TTL_SECONDS) -> str:
    body = _b64(json.dumps({"n": name, "p": path, "h": host, "e": int((now if now is not None else time.time()) + ttl)},
                           separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    return body + "." + _sig(token, body)


def verify(token: str, ticket: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Geçerliyse {name, path, host}; değilse None (hata ayrıntısı verilmez)."""
    if not token or not ticket or len(ticket) > MAX_TICKET or "." not in ticket:
        return None
    body, _, sig = ticket.partition(".")
    try:
        if not hmac.compare_digest(sig.encode("ascii"), _sig(token, body).encode("ascii")):
            return None
        d = json.loads(_unb64(body).decode("utf-8"))
        if int(d["e"]) < (now if now is not None else time.time()):
            return None
        name, path, host = str(d["n"]), str(d["p"]), str(d["h"])
    except (ValueError, KeyError, TypeError, UnicodeError):
        return None
    if not name or not path:
        return None
    return {"name": name, "path": path, "host": host}


# Dizin kapsamı (14 Kas): belgeyle AYNI dizin ağacındaki RESİMLER de okunabilir (reader'ın LaTeX/MD resimleri: `\includegraphics{figs/a.png}`,
# `![](a.png)` belge URL'sine göre `/readfile/<bilet>/figs/a.png` olur). Yalnız resim uzantıları, yalnız belge dizininin ALTI
# (`..`, mutlak yol, boş/`.` parça, ters bölü, NUL yok); kök/izin denetimi çağıranın `resolve_download`'ında yine geçerli.
IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif"})


def resolve_url_path(doc_path: str, url_rest: str) -> Optional[str]:
    """`/readfile/<bilet>/<url_rest>`: belgenin kendi adıysa `doc_path`; belge dizininin altındaki resim yoluysa o yol; aksi halde None."""
    rel = unquote(url_rest or "")
    if rel == os.path.basename(doc_path):
        return doc_path
    if not rel or "\x00" in rel or "\\" in rel or rel.startswith("/"):
        return None
    segs = rel.split("/")
    if any(s in ("", ".", "..") for s in segs):
        return None
    if os.path.splitext(segs[-1])[1].lower() not in IMAGE_EXTS:
        return None
    return os.path.join(os.path.dirname(doc_path), *segs)
