"""Bir claude oturumunun KÜMÜLATİF token harcaması (transkriptten; YALNIZ izleme, hiçbir karara bağlanmaz).

Ana transkript (`<proje>/<sid>.jsonl`) ve alt ajan transkriptleri (`<proje>/<sid>/subagents/agent-*.jsonl`) AYRI toplanır.
Gerçek transkriptte (2026-10-21 doğrulandı) aynı API cevabı içerik bloğu başına BİRDEN ÇOK `assistant` satırına bölünür
(thinking/text/tool_use ayrı satır, hepsi aynı `message.id` + `requestId`, aynı `usage`); düz toplama 2-3 kat şişirir.
Bu yüzden tur `(message.id, requestId)` ile tekilleştirilir; alt ajan dosyalarında tekrarlar arasında sayılar kısmen
farklı olabildiğinden (akış sırasında artan çıktı) alan başına EN BÜYÜK değer tutulur. (`model_usage.py` tekilleştirmez:
son-60-dk görünümü olduğu gibi kalır, bkz. TODO.)

Okuma ARTIMLIDIR: dosya başına (offset, boyut, mtime, tur tablosu) bellek önbelleği; yalnız eklenen kısım okunur, dosya
küçüldüyse baştan. Yarım son satır (yazım sürüyor) okunmaz, offset son tam satırda kalır. `usage_for_path` senkron
(CLI, testler), `cached_usage_for_path` ise `/api/status` içindir: HİÇ beklemez, bayatsa arka plan thread'i yeniler,
ilk çağrıda None döner. Asla fırlatmaz (bilinmiyorsa None)."""

import glob
import json
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

from .model_usage import _family

CACHE_SECONDS = 30
_MAX_CACHED_FILES = 2000            # bellek sınırı: emekli oturumların dosya durumları birikmesin
_ZERO = ("in", "out", "cache_write", "cache_read")

_lock = threading.RLock()
# yol -> {"offset", "size", "mtime", "turns": {anahtar: (aile, in, out, cache_write, cache_read)}}
_files: Dict[str, Dict[str, Any]] = {}
# ana transkript yolu -> {"at", "value", "running"}
_summaries: Dict[str, Dict[str, Any]] = {}


def _int(v: Any) -> int:
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


def _parse(raw: bytes) -> Optional[Tuple[Any, Tuple[str, int, int, int, int]]]:
    """Bir satırdan (tur anahtarı, (aile, in, out, cache_write, cache_read)) ya da None (usage yok / bozuk)."""
    if b'"usage"' not in raw:
        return None
    try:
        r = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(r, dict) or r.get("type") != "assistant":
        return None
    m = r.get("message")
    u = m.get("usage") if isinstance(m, dict) else None
    if not isinstance(u, dict):
        return None
    mid = m.get("id")
    # id yoksa tekilleştirilemez: satırın kendi uuid'si (o da yoksa her satır ayrı tur sayılır)
    key = (mid, r.get("requestId")) if mid else ("row", r.get("uuid") or object())
    return key, (_family(m.get("model", "")), _int(u.get("input_tokens")), _int(u.get("output_tokens")),
                 _int(u.get("cache_creation_input_tokens")), _int(u.get("cache_read_input_tokens")))


def _merge(old: Tuple, new: Tuple) -> Tuple:
    """Aynı turun tekrar satırı: alan başına büyük olan (akışta çıktı sayısı artar, hiçbir alan azalmaz)."""
    return (new[0],) + tuple(max(a, b) for a, b in zip(old[1:], new[1:]))


def _update_file(path: str) -> Optional[Dict[str, Any]]:
    """Dosyanın durumunu artımlı güncelle ve döndür (yoksa/okunamazsa None). Kilit altında çağrılır."""
    try:
        st = os.stat(path)
    except OSError:
        _files.pop(path, None)
        return None
    cur = _files.get(path)
    if cur is None or st.st_size < cur["offset"] or (st.st_size < cur["size"]):
        # yeni dosya ya da KESİLMİŞ (küçüldü): baştan
        cur = {"offset": 0, "size": 0, "mtime": 0.0, "turns": {}}
        if len(_files) >= _MAX_CACHED_FILES:
            _files.pop(next(iter(_files)), None)
        _files[path] = cur
    if st.st_size == cur["offset"]:
        cur["size"], cur["mtime"] = st.st_size, st.st_mtime
        return cur
    try:
        with open(path, "rb") as f:
            f.seek(cur["offset"])
            while True:
                line = f.readline()
                if not line:
                    break
                if not line.endswith(b"\n"):
                    break                     # yarım son satır: offset onun başında kalır, sonra tamamlanınca okunur
                cur["offset"] += len(line)
                got = _parse(line)
                if got:
                    key, val = got
                    prev = cur["turns"].get(key)
                    cur["turns"][key] = _merge(prev, val) if prev else val
    except OSError:
        return None
    cur["size"], cur["mtime"] = st.st_size, st.st_mtime
    return cur


def _sum(turns: Dict[Any, Tuple], fams: Dict[str, Dict[str, int]]) -> Dict[str, int]:
    t = {"in": 0, "out": 0, "cache_write": 0, "cache_read": 0, "turns": 0}
    for fam, i, o, cw, cr in turns.values():
        t["in"] += i
        t["out"] += o
        t["cache_write"] += cw
        t["cache_read"] += cr
        t["turns"] += 1
        f = fams.setdefault(fam, {"in": 0, "out": 0, "cache_write": 0, "cache_read": 0, "turns": 0})
        f["in"] += i
        f["out"] += o
        f["cache_write"] += cw
        f["cache_read"] += cr
        f["turns"] += 1
    return t


def usage_for_path(main_path: Any) -> Optional[Dict[str, Any]]:
    """{in, out, cache_write, cache_read, turns (ANA oturum), subagents: {n, in, out, cache_write, cache_read, turns},
    by_family: {aile: {in, out, cache_write, cache_read, turns}} (ana + alt ajanlar birlikte)}. Ana transkript okunamazsa
    None. Senkron (büyük dosyada ilk çağrı yavaş olabilir); asla fırlatmaz."""
    try:
        main = str(main_path)
        subs = sorted(glob.glob(os.path.join(main[:-len(".jsonl")] if main.endswith(".jsonl") else main,
                                             "subagents", "agent-*.jsonl")))
        fams: Dict[str, Dict[str, int]] = {}
        with _lock:
            st = _update_file(main)
            if st is None:
                return None
            total = _sum(st["turns"], fams)
            sub = {"n": 0, "in": 0, "out": 0, "cache_write": 0, "cache_read": 0, "turns": 0}
            for p in subs:
                s = _update_file(p)
                if s is None:
                    continue
                part = _sum(s["turns"], fams)
                sub["n"] += 1
                for k in (*_ZERO, "turns"):
                    sub[k] += part[k]
        return {**total, "subagents": sub, "by_family": fams}
    except Exception:
        return None


def _refresh(main: str) -> None:
    value = usage_for_path(main)
    with _lock:
        ent = _summaries.setdefault(main, {"at": 0.0, "value": None, "running": False})
        if value is not None or ent["value"] is None:
            ent["value"] = value
        ent["at"], ent["running"] = time.time(), False


def cached_usage_for_path(main_path: Any) -> Optional[Dict[str, Any]]:
    """Önbellekteki toplam; bayatsa arka planda yenilemeyi başlatır ve eskiyi (ilk seferde None) HEMEN döner."""
    try:
        main = str(main_path)
        with _lock:
            ent = _summaries.setdefault(main, {"at": 0.0, "value": None, "running": False})
            if time.time() - ent["at"] >= CACHE_SECONDS and not ent["running"]:
                ent["running"] = True
                if len(_summaries) > _MAX_CACHED_FILES:
                    for k in [k for k, v in _summaries.items() if not v["running"] and k != main][:200]:
                        _summaries.pop(k, None)
                threading.Thread(target=_refresh, args=(main,), name="session-usage", daemon=True).start()
            return ent["value"]
    except Exception:
        return None


def fmt_tokens(n: int) -> str:
    """12345 -> '12.3K', 1234567 -> '1.23M' (CLI tablosu ve ipuçları için)."""
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}K"
    return str(n)
