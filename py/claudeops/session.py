"""Session veri modeli — bir çalışan claude CLI session'ı."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import re

# isim = harfler + suffix rakamları (hc54, anomaly54, gencmuh54, co53...)
_NAME_RE = re.compile(r"^([a-z]+)(\d+)$")


@dataclass
class Session:
    name: str                              # --remote-control değeri (ör. "hc54")
    pid: int
    cwd: str = ""
    sid: Optional[str] = None              # --resume değeri (fresh --new'de None)
    model: Optional[str] = None            # --model değeri
    permission_mode: Optional[str] = None
    effort: Optional[str] = None
    cpu: float = 0.0                       # anlık %CPU (güvenilir aktiflik sinyali)

    @property
    def is_fresh(self) -> bool:
        """Fresh session = --resume YOK (Faz 2 --new ile açılan). Resumed'da sid var.
        (claude'a --new geçmiyor; ayırt edici tek şey --resume'un olmaması.)"""
        return self.sid is None

    @property
    def base(self) -> str:
        """Suffix'siz taban isim (hc54 -> hc)."""
        if not self.name:
            return ""
        m = _NAME_RE.match(self.name)
        return m.group(1) if m else self.name

    @property
    def suffix(self) -> Optional[int]:
        """Nesil suffix'i (hc54 -> 54)."""
        if not self.name:
            return None
        m = _NAME_RE.match(self.name)
        return int(m.group(2)) if m else None

    @property
    def model_short(self) -> str:
        m = self.model or ""
        for k in ("sonnet", "opus", "haiku", "fable"):
            if k in m:
                return k
        return m or "?"

    @property
    def active(self) -> bool:
        """CPU > 2% = işliyor. (session.json status'u GECİKMELİ — ona güvenme.)"""
        return self.cpu > 2.0
