"""Sağlayıcı model kataloğu izleyicisi (TODO: reviewer model kataloğu, sahip 13 Kas): günlük `model_choices()` taraması (agy canlı
`agy models`, codex `models_cache.json`, ucli/Evren `/v1/models`, claude `claude_models.json`); daha önce görülmeyen model SAHİBE
bildirilir (periodic özeti + diag.log), OTOMATİK EKLENMEZ (planda olmayan model sessizce başka modele düşebilir: önce elle tek
'Reply OK' yoklaması + agy log `label=` kanıtı). İlk koşu yalnız taban çizgisi yazar (bildirim yok). Kaybolan model silinmez, `gone` olur."""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional

from .atomic_json import atomic_write_json
from .diaglog import diag_log
from .paths import CLAUDEOPS_DIR

CATALOG_JSON = os.path.join(CLAUDEOPS_DIR, "model_catalog.json")
SCAN_PROVIDERS = ("agy", "codex", "ucli", "claude")


def compare(prev: Optional[Dict[str, Any]], current: Dict[str, List[str]], now: float) -> Dict[str, Any]:
    """SAF: (önceki katalog, bu tarama) -> {catalog, new: {sağlayıcı: [model]}, gone: {...}}. prev None = taban çizgisi (new boş).
    Boş tarama (sağlayıcı yanıt vermedi) o sağlayıcının kaydını DEĞİŞTİRMEZ: geçici arıza 'tüm modeller kayboldu' sayılmasın."""
    cat: Dict[str, Any] = {"checked_at": now, "providers": {}}
    new: Dict[str, List[str]] = {}
    gone: Dict[str, List[str]] = {}
    old_provs = (prev or {}).get("providers") or {}
    for prov, models in current.items():
        old = old_provs.get(prov) or {}
        known = dict(old.get("models") or {})
        if not models:
            cat["providers"][prov] = {"models": known, "ok": False}
            continue
        seen = sorted(set(models))
        if prev is not None and old:
            fresh = [m for m in seen if m not in known]
            if fresh:
                new[prov] = fresh
            lost = sorted(m for m, st in known.items() if st == "present" and m not in seen)
            if lost:
                gone[prov] = lost
        merged = {m: ("present" if m in seen else "gone") for m in set(known) | set(seen)}
        cat["providers"][prov] = {"models": merged, "ok": True}
    return {"catalog": cat, "new": new, "gone": gone}


def scan(fetch: Optional[Callable[[str], List[str]]] = None) -> Dict[str, List[str]]:
    """Sağlayıcı başına güncel model listesi; hata/boş = []."""
    if fetch is None:
        from .providers import get_provider

        def fetch(name: str) -> List[str]:
            return list(get_provider(name).model_choices() or [])
    out: Dict[str, List[str]] = {}
    for name in SCAN_PROVIDERS:
        try:
            out[name] = [str(m) for m in fetch(name) if m]
        except Exception:
            out[name] = []
    return out


def run(path: str = CATALOG_JSON, fetch: Optional[Callable[[str], List[str]]] = None, now: Optional[float] = None,
        apply: bool = True) -> Dict[str, Any]:
    import json
    now = time.time() if now is None else now
    try:
        with open(path, encoding="utf-8") as f:
            prev = json.load(f)
    except (OSError, ValueError):
        prev = None
    res = compare(prev, scan(fetch), now)
    if apply:
        try:
            atomic_write_json(path, res["catalog"], mode=0o600)
        except Exception as e:
            diag_log("model_watch_write_failed", error=repr(e)[:200])
    if apply and path == CATALOG_JSON:      # yalnız gerçek katalog: testlerin geçici yolu canlı instances.json'a dokunmasın
        try:
            from . import instances
            live = {c: {m for m, st in (v.get("models") or {}).items() if st == "present"}
                    for c, v in res["catalog"]["providers"].items() if v.get("ok") and c == "ucli"}   # yalnız Evren: claude/agy/codex takma ad ve nesil adları yanlış işaret üretir
            n = instances.mark_models_gone(live)
            if n:
                diag_log("model_watch_instances_marked", changed=n)
        except Exception as e:
            diag_log("model_watch_instances_failed", error=repr(e)[:200])
    if res["new"]:
        diag_log("model_watch_new", new=res["new"])
    return {"new": res["new"], "gone": res["gone"], "baseline": prev is None}
