"""Panel bundle'ı tutarlılık denetimi: py/webui/dist/index.html'in referans verdiği /assets/ dosyaları diskte var mı.
(test_dist_consistent ile aynı mantık: `(src|href)="/assets/..."`.) Yalnız okur."""
import os
import re
from typing import Dict, List, Optional

DEFAULT_DIST = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "webui", "dist"))
_REF_RE = re.compile(r'(?:src|href)="(/assets/[^"]+)"')


def referenced_assets(index_text: str) -> List[str]:
    return [r.lstrip("/") for r in _REF_RE.findall(index_text)]


def check_dist(dist: Optional[str] = None) -> Dict[str, object]:
    """{ok, missing: [...], reason}. index.html yoksa/okunamazsa missing=['index.html']."""
    dist = dist or DEFAULT_DIST
    index = os.path.join(dist, "index.html")
    try:
        with open(index, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {"ok": False, "missing": ["index.html"], "reason": "index.html okunamadı"}
    missing = [r for r in referenced_assets(text) if not os.path.isfile(os.path.join(dist, r))]
    return {"ok": not missing, "missing": missing, "reason": "" if not missing else "bundle dosyası eksik"}


def log_if_missing(log, dist: Optional[str] = None) -> Dict[str, object]:
    """Eksikse `log("dist-eksik", missing=[...])` çağırır; sonucu döner."""
    res = check_dist(dist)
    if not res["ok"]:
        log("dist-eksik", missing=res["missing"], reason=res["reason"])
    return res
