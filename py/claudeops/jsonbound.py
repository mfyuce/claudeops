"""Sağlayıcı okuyucularının `json.loads`u, Rust `cops-providers::pyjson` kurallarıyla (TODO rs-prov "512-1000 iç içe JSON
ve eşlenmemiş vekil eşlik farkı", 28 Kas):

- 512'den çok iç içe dizi/nesne açan belge AYRIŞTIRILMAZ (`pyjson::MAX_DEPTH`; sayım dize içindeki ayraçları saymaz).
  Eskiden Python 512-1000 arasını okuyor, ~1000 üstünde `RecursionError` atıyordu (çoğu okuyucu yakalamıyordu).
- Eşlenmemiş vekil kaçışı (`"\\ud83d"`, kesilmiş emoji) U+FFFD olur: Python dizede vekil taşıyordu, sonraki UTF-8
  yazımı `UnicodeEncodeError` verebiliyordu.

Hata `json.JSONDecodeError` (bir `ValueError`): JSON hatasını yakalayan her çağıran bunu da yakalar."""
from __future__ import annotations

import json
import re
from typing import Any

MAX_DEPTH = 512      # Rust `pyjson::MAX_DEPTH`
_TOKEN_RE = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"?|[\[\]{}]', re.S)      # dize (yarım da olur) içindeki ayraç sayılmaz
_LONE_RE = re.compile("[\ud800-\udfff]")


def too_deep(text: str) -> bool:
    """`MAX_DEPTH`ten çok kapsayıcı aynı anda açık mı (özyinelemesiz, belgeyi ayrıştırmadan)."""
    if text.count("[") + text.count("{") <= MAX_DEPTH:
        return False
    depth = 0
    for m in _TOKEN_RE.finditer(text):
        t = m.group()
        if t in ("[", "{"):
            depth += 1
            if depth > MAX_DEPTH:
                return True
        elif t in ("]", "}"):
            depth = max(0, depth - 1)
    return False


def _fix_str(s: str) -> str:
    return _LONE_RE.sub("\ufffd", s) if _LONE_RE.search(s) else s


def _replace_lone_surrogates(obj: Any) -> Any:
    """Ayrıştırılmış değerdeki (anahtar dahil) eşlenmemiş vekilleri U+FFFD yapar; özyinelemesiz, yerinde."""
    if isinstance(obj, str):
        return _fix_str(obj)
    stack = [obj]
    while stack:
        v = stack.pop()
        if isinstance(v, dict):
            if any(isinstance(k, str) and _LONE_RE.search(k) for k in v):
                items = list(v.items())     # sıra korunur; düzeltmeyle çakışan anahtarda ilk yer, son değer (Rust gibi)
                v.clear()
                for k, c in items:
                    v[_fix_str(k) if isinstance(k, str) else k] = c
            for k, c in v.items():
                if isinstance(c, str):
                    v[k] = _fix_str(c)
                elif isinstance(c, (dict, list)):
                    stack.append(c)
        elif isinstance(v, list):
            for i, c in enumerate(v):
                if isinstance(c, str):
                    v[i] = _fix_str(c)
                elif isinstance(c, (dict, list)):
                    stack.append(c)
    return obj


def loads(s: Any, **kw: Any) -> Any:
    """`json.loads` + derinlik sınırı + vekil düzeltmesi. `bytes` da kabul edilir (`json.loads` gibi kodlama sezilir)."""
    text = s.decode(json.detect_encoding(s), "surrogatepass") if isinstance(s, (bytes, bytearray)) else s
    if isinstance(text, str) and too_deep(text):
        raise json.JSONDecodeError(f"{MAX_DEPTH} kattan derin", text, 0)
    try:
        val = json.loads(text, **kw)
    except RecursionError:
        raise json.JSONDecodeError("çok derin", text if isinstance(text, str) else "", 0) from None
    return _replace_lone_surrogates(val)


def load(fp: Any, **kw: Any) -> Any:
    return loads(fp.read(), **kw)
