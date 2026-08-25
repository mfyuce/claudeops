"""Session veri modeli — bir çalışan claude CLI session'ı."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import re

# İsimler base-name (suffix YOK): hc, anomaly, co... Geçiş savunması: eski
# suffix'li adlar (hc58) da base'e (hc) indirgensin diye sondaki rakamlar opsiyonel.
# 2026-08-25: tarih+çakışma suffix'leri de (cops20260824_1, mo20260813_1) base'e
# indirgenir — aksi halde `_1`li adlar roster'daki base kaydına eşleşmiyor,
# panel onları "kayıtsız" sanıyordu.
_NAME_RE = re.compile(r"^([a-z]+)\d*(?:_\d+)*$")


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
        """Taban isim. Normalde isim = base (hc). Geçiş savunması: suffix'li eski
        ad gelirse (hc58) sondaki rakamlar atılır → hc. Böylece guard/handover
        karışık dönemde (hc58 + hc) ikisini de aynı base görür, DUP açmaz."""
        if not self.name:
            return ""
        m = _NAME_RE.match(self.name)
        return m.group(1) if m else self.name

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
