"""claudeops GENEL KULLANIM DURUMU: tüm sağlayıcıların kota/kullanım okumasının TEK kaynağı (sahip 18 Kas, "kullanım claudeops genel durumu").

Yazıcı: `periodic.py` öntanımlı işi `usage_refresh` (5 dk, açık) ve panelin "Kullanımı kontrol et" düğmesi AYNI işi (`web.usage_refresh`) çalıştırır;
oturumsuz yolları (claude `-p /usage`, agy `--print /usage`, Evren /v1/quota, API anahtarlıları) okuyup `set_all` ile buraya yazar.
Okuyucular (reviewer agy engelleri, değnekçi kota bekçisi, `py/cops usage --account`, MCP aracı, `/api/status` dilimi) BURADAN okur, kendi ölçmez.
`STALE_SECONDS` (10 dk) geçtiyse durum 'bayat' diye işaretlenir (okuyucu karar verir; sessizce eski değeri doğru sanma).
Dosya `CLAUDEOPS_DIR/usage_state.json` (atomik, 0600). Yaprak modül: web/provider içe aktarmaz."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional, Set

from .atomic_json import atomic_write_json, file_lock
from .paths import CLAUDEOPS_DIR

STATE_PATH = os.path.join(CLAUDEOPS_DIR, "usage_state.json")
STALE_SECONDS = 600.0       # 10 dk: 5 dk'lık iki tur kaçarsa bayat (sahip 18 Kas)
REFRESH_SECONDS = 300.0       # periodic işi aralığı: 5 dk (en eski veri 5 dk)
AUTH_RETRY_SECONDS = 3600.0   # girişsiz CLI periyodik okumada saatte bir denenir (okuma OAuth kodu bekleyip zaman aşımına düşer)


def _load() -> Dict[str, Any]:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def set_all(providers: Dict[str, Any], now: Optional[float] = None, source: str = "") -> None:
    """Okumanın sonucunu yazar. Okunamayan sağlayıcı (`available` false) eski BAŞARILI değeri EZMEZ, yalnız yeni durumu ve nedenini
    tutar; her sağlayıcının kendi `at` zamanı vardır (bir sağlayıcı bayat kalıp ötekiler taze olabilir)."""
    t = time.time() if now is None else now
    with file_lock(STATE_PATH):
        cur = _load()
        provs = dict(cur.get("providers") or {})
        for name, res in (providers or {}).items():
            if not isinstance(res, dict):
                continue
            old = provs.get(name) or {}
            if res.get("available"):
                provs[name] = {**res, "at": t}
            else:
                keep = {k: old[k] for k in ("entries", "checked_via") if old.get("available") and k in old}
                provs[name] = {**res, **keep, "at": t, "ok_at": old.get("ok_at") or (old.get("at") if old.get("available") else None),
                               "stale_data": bool(keep)}
            if res.get("available"):
                provs[name]["ok_at"] = t
        atomic_write_json(STATE_PATH, {"at": t, "source": source, "providers": provs}, mode=0o600)


def auth_backoff(now: Optional[float] = None, retry_after: float = AUTH_RETRY_SECONDS) -> Set[str]:
    """Son denemesi "giriş yok" ile biten ve yeniden deneme vadesi DOLMAMIŞ sağlayıcılar: periyodik okuyucular bunları atlar
    (atlanan okuma kayda dokunmaz, `at` son gerçek denemede kalır). Panel düğmesi bu listeye bakmaz, hemen okur."""
    t = time.time() if now is None else now
    return {name for name, res in (_load().get("providers") or {}).items()
            if isinstance(res, dict) and not res.get("available") and res.get("reason") == "auth_required"
            and 0 <= t - float(res.get("at") or 0) < retry_after}


def get(now: Optional[float] = None, stale_after: float = STALE_SECONDS) -> Dict[str, Any]:
    """{at, age_secs, stale, providers{ad: {... , age_secs, stale}}}. Hiç okuma yoksa at=0, stale=True."""
    t = time.time() if now is None else now
    d = _load()
    at = float(d.get("at") or 0)
    provs: Dict[str, Any] = {}
    for name, res in (d.get("providers") or {}).items():
        if not isinstance(res, dict):
            continue
        ok_at = float(res.get("ok_at") or 0)
        provs[name] = {**res, "age_secs": int(t - ok_at) if ok_at else None,
                       "stale": (not ok_at) or t - ok_at > stale_after}
    return {"at": at, "age_secs": int(t - at) if at else None, "stale": (not at) or t - at > stale_after,
            "source": d.get("source") or "", "providers": provs}


def provider(name: str, now: Optional[float] = None, stale_after: float = STALE_SECONDS) -> Optional[Dict[str, Any]]:
    """Tek sağlayıcının kaydı (bayat bayrağıyla) ya da hiç okunmadıysa None."""
    return get(now, stale_after)["providers"].get(name)
