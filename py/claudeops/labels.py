"""Proje etiketleri (label): "insan bakmadan ilerleyemeyen" gibi durumları listede işaretlemek ve aramak için.

Depo: `<CLAUDEOPS_DIR>/labels.json` (makine geneli, yalnız YEREL)
    {"version": 1, "defs": {ad: {"color", "desc"}}, "assign": {proje: [etiket, ...]}}
Anahtar = blueprint/proje adı; tarihli oturum satırı etiketini blueprint'inden alır (`key_for`).
Sistem etiketleri koddadır (`SYSTEM`): dosyaya yazılmaz, silinemez, rengi/açıklaması sabit.
Yalnız İNSAN atar (panel/CLI). Değnekçi yalnız KALDIRIR (`auto_remove`, projeye girince); otomatik ekleme yok.

Yazım: `atomic_write_json` + `file_lock` (süreçler arası, okuma-değiştirme-yazma bütün kilit altında).
`statedocs`/DB aynasına BİLEREK girmez: tek kaynak dosya, SQL göçünde gerekirse eklenir.
"""
from __future__ import annotations
import os
import re
from typing import Any, Dict, Iterable, List, Optional

from .atomic_json import atomic_write_json, file_lock
from . import paths

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_DERIVED_RE = re.compile(r"^([a-z][a-z0-9]*?)(\d{8})([a-z0-9_]*)$")
DEFAULT_COLOR = "#6b7280"
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Az ve anlamlı: hepsi "insan/dış engel" ekseninde, ayrıntı `desc`te. Renkler açık ve koyu temada okunur orta tonlar.
SYSTEM: Dict[str, Dict[str, Any]] = {
    "stuck": {"color": "#dc2626", "system": True,
              "desc": "Sahip girdisi olmadan ilerleyemez (karar, onay, bilgi bekliyor). Değnekçi projeye girince kalkar."},
    "waiting-owner": {"color": "#d97706", "system": True,
                      "desc": "Sahibin yanıtını/incelemesini bekliyor. Değnekçi projeye girince kalkar."},
    "waiting-external": {"color": "#7c3aed", "system": True,
                         "desc": "Dış taraf bekleniyor (hukukçu, kurum, veri, üçüncü kişi); sahibin yapacağı bir şey yok."},
    "blocked-budget": {"color": "#0e7490", "system": True,
                       "desc": "Kota/bütçe yüzünden duruyor; sahip kararı ya da kota sıfırlanması gerekir."},
    "needs-review": {"color": "#2563eb", "system": True,
                     "desc": "Çıktı hazır, sahibin gözden geçirmesi gerekiyor."},
    "paused-by-owner": {"color": "#6b7280", "system": True,
                        "desc": "Sahip bilerek durdurdu; kendiliğinden devam etmez."},
}
# Değnekçi projeye girince kaldırılan etiketler (insan engeli: girdi artık geldi ya da proje çalışmaya döndü).
AUTO_REMOVE_ON_ENTER = ("stuck", "waiting-owner")

MAX_LABELS_PER_PROJECT = 24
MAX_DEFS = 64


def _path() -> str:
    return os.path.join(paths.CLAUDEOPS_DIR, "labels.json")


def valid_name(name: Any) -> bool:
    return isinstance(name, str) and bool(NAME_RE.match(name))


def key_for(name: str, blueprint: Optional[str] = None) -> str:
    """Etiket anahtarı: blueprint varsa o; yoksa tarihli türev adın önü (`ae20261101` -> `ae`); yoksa ad."""
    if blueprint:
        return blueprint
    m = _DERIVED_RE.match(name or "")
    return m.group(1) if m else (name or "")


def _empty() -> Dict[str, Any]:
    return {"version": 1, "defs": {}, "assign": {}}


def _read_raw() -> Dict[str, Any]:
    import json
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(d, dict):
        return _empty()
    defs = d.get("defs") if isinstance(d.get("defs"), dict) else {}
    assign = d.get("assign") if isinstance(d.get("assign"), dict) else {}
    # Bozuk girdileri sessizce ayıkla (elle düzenleme).
    defs = {k: v for k, v in defs.items() if valid_name(k) and k not in SYSTEM and isinstance(v, dict)}
    assign = {k: [x for x in v if valid_name(x)] for k, v in assign.items()
              if isinstance(k, str) and k and isinstance(v, list)}
    return {"version": 1, "defs": defs, "assign": {k: v for k, v in assign.items() if v}}


def _write(d: Dict[str, Any]) -> None:
    os.makedirs(paths.CLAUDEOPS_DIR, exist_ok=True)
    atomic_write_json(_path(), d, mode=0o600)


def definitions() -> Dict[str, Dict[str, Any]]:
    """Sistem + kullanıcı tanımları: {ad: {color, desc, system}} (sistem önce)."""
    out: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in SYSTEM.items()}
    for k, v in _read_raw()["defs"].items():
        color = v.get("color") if isinstance(v.get("color"), str) and _COLOR_RE.match(v["color"]) else DEFAULT_COLOR
        out[k] = {"color": color, "desc": str(v.get("desc") or "")[:200], "system": False}
    return out


def assignments() -> Dict[str, List[str]]:
    return {k: list(v) for k, v in _read_raw()["assign"].items()}


def labels_of(key: str, _assign: Optional[Dict[str, List[str]]] = None) -> List[str]:
    a = _assign if _assign is not None else _read_raw()["assign"]
    return list(a.get(key, []))


def find(label: str) -> List[str]:
    """Bu etiketi taşıyan proje anahtarları (sıralı)."""
    return sorted(k for k, v in _read_raw()["assign"].items() if label in v)


def update(key: str, add: Iterable[str] = (), remove: Iterable[str] = (), *, create_missing: bool = True) -> Dict[str, Any]:
    """Projeye etiket ekle/çıkar. Bilinmeyen etiket adı geçerliyse (create_missing) otomatik tanımlanır.
    Döner: {ok, labels, error?}. Aynı etiket hem add hem remove'daysa remove kazanır."""
    key = (key or "").strip()
    add, remove = [str(x) for x in add], [str(x) for x in remove]
    if not key:
        return {"ok": False, "error": "proje adı boş"}
    bad = [x for x in add + remove if not valid_name(x)]
    if bad:
        return {"ok": False, "error": f"geçersiz etiket adı: {bad[0]} (a-z 0-9 _ -, en çok 32, harf/rakamla başlar)"}
    with file_lock(_path()):
        d = _read_raw()
        cur = d["assign"].get(key, [])
        for x in add:
            if x not in cur:
                if x not in SYSTEM and x not in d["defs"]:
                    if not create_missing:
                        return {"ok": False, "error": f"tanımsız etiket: {x}"}
                    if len(d["defs"]) >= MAX_DEFS:
                        return {"ok": False, "error": "çok fazla etiket tanımı"}
                    d["defs"][x] = {"color": DEFAULT_COLOR, "desc": ""}
                cur.append(x)
        cur = [x for x in cur if x not in remove]
        if len(cur) > MAX_LABELS_PER_PROJECT:
            return {"ok": False, "error": "projede çok fazla etiket"}
        if cur:
            d["assign"][key] = cur
        else:
            d["assign"].pop(key, None)
        _write(d)
    return {"ok": True, "labels": cur}


def define(name: str, color: str = "", desc: str = "") -> Dict[str, Any]:
    """Etiket tanımı ekle/güncelle (sistem etiketi DEĞİŞTİRİLEMEZ)."""
    if not valid_name(name):
        return {"ok": False, "error": "geçersiz etiket adı (a-z 0-9 _ -, en çok 32)"}
    if name in SYSTEM:
        return {"ok": False, "error": f"{name} sistem etiketi, değiştirilemez"}
    color = (color or "").strip() or DEFAULT_COLOR
    if not _COLOR_RE.match(color):
        return {"ok": False, "error": "renk #rrggbb olmalı"}
    with file_lock(_path()):
        d = _read_raw()
        if name not in d["defs"] and len(d["defs"]) >= MAX_DEFS:
            return {"ok": False, "error": "çok fazla etiket tanımı"}
        d["defs"][name] = {"color": color, "desc": (desc or "")[:200]}
        _write(d)
    return {"ok": True}


def delete_def(name: str) -> Dict[str, Any]:
    """Etiket tanımını sil ve tüm projelerden çıkar (sistem etiketi silinemez)."""
    if name in SYSTEM:
        return {"ok": False, "error": f"{name} sistem etiketi, silinemez"}
    if not valid_name(name):
        return {"ok": False, "error": "geçersiz etiket adı"}
    with file_lock(_path()):
        d = _read_raw()
        existed = name in d["defs"] or any(name in v for v in d["assign"].values())
        d["defs"].pop(name, None)
        d["assign"] = {k: [x for x in v if x != name] for k, v in d["assign"].items()}
        d["assign"] = {k: v for k, v in d["assign"].items() if v}
        if existed:
            _write(d)
    return {"ok": existed, "error": "" if existed else f"etiket yok: {name}"}


def auto_remove(key: str, which: Iterable[str] = AUTO_REMOVE_ON_ENTER) -> List[str]:
    """Değnekçi projeye girince: `which` içindeki etiketleri kaldır; gerçekten kaldırılanları döner (yoksa [], dosya yazılmaz)."""
    which = set(which)
    if not key or not (which & set(labels_of(key))):
        return []                       # ucuz yol: her tick'te kilit/yazım yok
    with file_lock(_path()):
        d = _read_raw()
        cur = d["assign"].get(key, [])
        gone = [x for x in cur if x in which]
        if not gone:
            return []
        left = [x for x in cur if x not in which]
        if left:
            d["assign"][key] = left
        else:
            d["assign"].pop(key, None)
        _write(d)
    return gone


def attach(rows: List[Dict[str, Any]], *, key_of=None) -> None:
    """Durum satırlarına `labels` alanı ekle (yerinde; çağıran yalnız YEREL satırları verir). Tek dosya okuması."""
    assign = _read_raw()["assign"]
    for r in rows:
        k = key_of(r) if key_of else key_for(r.get("name", ""), r.get("blueprint"))
        r["labels"] = list(assign.get(k, []))
        r["label_key"] = k


def api_action(data: Dict[str, Any]) -> Dict[str, Any]:
    """`POST /api/labels` gövdesi: {name, add:[], remove:[]} | {define:{name,color,desc}} | {delete:"ad"}."""
    if isinstance(data.get("define"), dict):
        d = data["define"]
        return define(str(d.get("name") or ""), str(d.get("color") or ""), str(d.get("desc") or ""))
    if data.get("delete"):
        return delete_def(str(data["delete"]))
    add, remove = data.get("add") or [], data.get("remove") or []
    if not isinstance(add, list) or not isinstance(remove, list):
        return {"ok": False, "error": "add/remove liste olmalı"}
    return update(str(data.get("name") or ""), add, remove)
