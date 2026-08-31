"""`web_static` — committed `py/webui/dist/` içeriğini güvenle serve et.

React rewrite'ın (dynamic-crunching-lemon.md) parçası: `web.py` artık
`PAGE_HTML` string sabiti yerine Vite'ın build ettiği statik dosyaları
serve ediyor. Bu modül path-traversal'a kapalı tek fonksiyon:
`resolve_static_path()` — `web.py`'nin diff'ini additive tutmak için
ayrı dosyada (plan'ın kararı).

Kritik: `DIST_DIR` dışına çıkan hiçbir path (`../../etc/passwd` gibi)
resolve edilmemeli — `Path.resolve()` ile normalize edip
`is_relative_to(DIST_DIR)` ile doğrulanıyor.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from ..paths import REPO_DIR

# DİKKAT: REPO_DIR repo KÖKÜ (`py/`nin BİR ÜSTÜ) — paths.py'de
# `parents[2]` (`py/claudeops/paths.py`'den) repo köküne çıkar, `py/`ye değil.
# webui/ ise plan'ın proje layout'unda `py/webui/` (py/claudeops/'ın kardeşi),
# bu yüzden burada "py" segmentini elle eklemek ŞART — REPO_DIR/webui/dist
# YANLIŞ olurdu (var olmayan bir dizine işaret eder, resolve_static_path hep
# None döner — build+serve testiyle canlı doğrulandı).
DIST_DIR = (Path(REPO_DIR) / "py" / "webui" / "dist").resolve()


def resolve_static_path(url_path: str) -> Optional[Path]:
    """`url_path` (`self.path`'in query'siz hali) → `DIST_DIR` altında gerçek dosya, yoksa None.

    `/` veya boş → `index.html`. Bir dizine denk gelirse (örn. gelecekte
    nested route) o dizinin `index.html`'i denenir. `DIST_DIR` dışına
    çıkan her sonuç (traversal veya symlink escape) None döner.
    """
    rel = url_path.lstrip("/") or "index.html"
    candidate = (DIST_DIR / rel).resolve()
    if not candidate.is_relative_to(DIST_DIR):
        return None
    if candidate.is_dir():
        candidate = candidate / "index.html"
        if not candidate.is_relative_to(DIST_DIR):
            return None
    return candidate if candidate.is_file() else None
