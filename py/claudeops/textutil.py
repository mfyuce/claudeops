"""Küçük SAF metin yardımcıları (bağımlılıksız; her modülden içe alınabilir)."""
from __future__ import annotations

from typing import Any


def collapse_ws(text: Any) -> str:
    """Tüm boşluk/satır sonu dizilerini tek boşluğa indirir, baş/sonu kırpar; None/boş -> ''. (`" ".join(str(x or "").split())` kopyalarının tek yeri.)"""
    return " ".join(str(text or "").split())
