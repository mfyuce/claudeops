"""Ortak atomik JSON yazım yardımcısı.

`hosts.py`/`settings.py`/`orch_store.py` üçü de bağımsız olarak AYNI
"tmp + os.replace" desenini taşıyordu — ve üçünde de AYNI bug vardı: tmp
dosyasının adı sabitti (`<path>.tmp`). `ThreadingHTTPServer`'ın istek-başına-
thread modelinde AYNI path'e eşzamanlı iki yazım (ör. Ekip/Team tab'ının
lineup editörü her checkbox değişiminde `/api/orch/draft`'a otomatik-kaydediyor
— hızlı ardışık iki toggle iki thread'i aynı anda tetikleyebiliyor) birbirinin
tmp dosyasını YEDİ: thread A `tmp`'ı açıp yazarken thread B AYNI `tmp`'ı
O_TRUNC ile yeniden açıp kendi içeriğini yazdı, sonra B önce `os.replace`
çağırıp tmp'ı tüketti — A'nın `os.replace`'i artık var olmayan bir dosyayı
rename etmeye çalışıp `FileNotFoundError` fırlattı (2026-09-10, canlı serviste
`orch_store.save_draft` üzerinden 4 kez tekrarlandı, log kanıtı DONE.md'de).

Fix: tmp adına çağıranın pid+thread-id'sini ekle — aynı thread HER ZAMAN
kendi tmp dosyasını kullanır (gerçek eşzamanlılık aynı thread içinde zaten
imkansız), `os.replace`'in atomikliği aynen korunur. Leaf modül — stdlib
dışında hiçbir şeye bağımlı değil, `paths.py`'nin bile ALTINDA (üç çağıranın
hepsi zaten "sadece paths'e bağımlı" leaf disiplinini takip ediyor).
"""
from __future__ import annotations
import json
import os
import threading
from typing import Any, Optional


def atomic_write_json(path: str, obj: Any, *, mode: Optional[int] = None) -> None:
    """`mode=None` → düz `open()` (umask varsayılanı, ör. `settings.json`).
    `mode=0o600` gibi verilirse → `os.open()` ile İLK OLUŞTURMADAN itibaren o
    izinle (ör. `hosts.json`/`orchestration/*.json` — `os.replace` hedefi
    KAYNAĞIN izinleriyle değiştirir, sonradan chmod'lamak yerine baştan doğru
    açmak gerekir)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"
    if mode is None:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    else:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # atomik — eşzamanlı okuyan yarım dosya görmez
