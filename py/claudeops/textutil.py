"""Küçük SAF metin yardımcıları (bağımlılıksız; her modülden içe alınabilir)."""
from __future__ import annotations

from typing import Any


def collapse_ws(text: Any) -> str:
    """Tüm boşluk/satır sonu dizilerini tek boşluğa indirir, baş/sonu kırpar; None/boş -> ''. (`" ".join(str(x or "").split())` kopyalarının tek yeri.)"""
    return " ".join(str(text or "").split())


def split_names(items: Any) -> list:
    """CLI hedef adları: boşlukla ayrı argümanlar VE virgüllü listeler (`a,b c`) -> ['a','b','c'] (sırayı korur, tekrarı atar)."""
    out: list = []
    for it in items or []:
        for n in str(it).split(","):
            n = n.strip()
            if n and n not in out:
                out.append(n)
    return out
