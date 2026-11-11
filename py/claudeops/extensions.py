"""Çekirdek GENİŞLEME NOKTALARI (open-core, docs/sql-gocu-plani.md Bölüm 0): çekirdek kanca tanımlar, `claudeops_enterprise`
(ayrı, özel paket) doldurur. Bağımlılık TEK YÖNLÜDÜR: çekirdek bu paketi ASLA doğrudan içe aktarmaz; yalnız `load()` adıyla,
yüklüyse, dener. Paket yoksa çekirdek davranışı DEĞİŞMEZ (sessiz geçer). Eklenti hatası çekirdeği düşürmez (diag + kayıt).

Sözleşme: eklenti `register(api)` tanımlar (`api` = `ExtensionAPI`), isteğe bağlı `REQUIRES_CORE_API` (tamsayı; çekirdeğin
`EXTENSION_API_VERSION`ıyla EŞİT olmalı, değilse yükleme reddedilir). Bugünkü kanca: `api.register_lens(...)` (reviewer merceği).
"""
from __future__ import annotations

import importlib
import threading
from typing import Any, Dict, List

EXTENSION_API_VERSION = 1
PACKAGE = "claudeops_enterprise"

_LOCK = threading.RLock()
_STATE: Dict[str, Any] = {"loaded": False, "status": "not_loaded", "detail": "", "lenses": []}


class ExtensionAPI:
    """Eklentiye verilen yüzey (yalnız kayıt işlevleri; çekirdek iç durumuna doğrudan erişim yok)."""
    api_version = EXTENSION_API_VERSION

    def register_lens(self, name: str, tr: str, en: str, format_tr: str = "", format_en: str = "") -> None:
        from . import review as rv
        if name in _STATE["lenses"]:
            return                          # aynı eklenti yeniden yüklenirse (force) idempotent; yerleşik/başkasının adını ezmek review'da reddedilir
        rv.register_lens(name, tr, en, format_tr, format_en)
        _STATE["lenses"].append(name)


def _log(event: str, **kw: Any) -> None:
    try:
        from .diaglog import diag_log
        diag_log(event, **kw)
    except Exception:
        pass


def load(force: bool = False) -> Dict[str, Any]:
    """`claudeops_enterprise` import edilebiliyorsa `register(api)` çağırır; yoksa sessizce geçer. Idempotent (`force` yeniden dener).
    Döner: {status: absent|loaded|incompatible|error, detail, lenses}."""
    with _LOCK:
        if _STATE["loaded"] and not force:
            return status()
        _STATE.update(loaded=True, status="absent", detail="")      # lenses KORUNUR: kayıtlı mercek yeniden yüklemede silinmez
        try:
            mod = importlib.import_module(PACKAGE)
        except ModuleNotFoundError as e:
            if e.name != PACKAGE:         # paket VAR ama kendi bağımlılığı eksik: sessiz geçme, söyle
                _STATE.update(status="error", detail=f"{type(e).__name__}: {e}"[:200])
                _log("extension_load_failed", package=PACKAGE, error=_STATE["detail"])
            return status()
        except Exception as e:            # noqa: BLE001
            _STATE.update(status="error", detail=f"{type(e).__name__}: {e}"[:200])
            _log("extension_load_failed", package=PACKAGE, error=_STATE["detail"])
            return status()
        req = getattr(mod, "REQUIRES_CORE_API", EXTENSION_API_VERSION)
        if req != EXTENSION_API_VERSION:
            _STATE.update(status="incompatible", detail=f"requires core api {req}, core has {EXTENSION_API_VERSION}")
            _log("extension_incompatible", package=PACKAGE, detail=_STATE["detail"])
            return status()
        try:
            mod.register(ExtensionAPI())
            _STATE.update(status="loaded", detail=str(getattr(mod, "__version__", "")))
        except Exception as e:            # noqa: BLE001  kısmi kayıt kalabilir; çekirdek çalışır
            _STATE.update(status="error", detail=f"register: {type(e).__name__}: {e}"[:200])
            _log("extension_load_failed", package=PACKAGE, error=_STATE["detail"])
        return status()


def status() -> Dict[str, Any]:
    return {"status": _STATE["status"], "detail": _STATE["detail"], "lenses": list(_STATE["lenses"]), "package": PACKAGE,
            "core_api": EXTENSION_API_VERSION}


def lens_sources() -> List[str]:
    return list(_STATE["lenses"])
