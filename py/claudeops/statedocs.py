"""Dosya-tabanlı JSON state'ten SQLite deposuna GEÇİŞ adaptörü (K5): `store_backend` = files | dual | db.

  files (varsayılan, bugünkü davranış): yalnız dosya. DB'ye dokunulmaz.
  dual : yaz = DB + dosya; oku = DB, belge DB'de yoksa dosyadan okunur ve DB'ye alınır (tembel içe aktarma).
  db   : yaz = yalnız DB; oku = DB (yoksa dosyadan tek seferlik içe aktarma). Dosya artık güncellenmez.
Kip seçimi: ortam `CLAUDEOPS_STORE_BACKEND`, yoksa settings.json `store_backend` (ham okunur: settings.py de ileride
bu modülü kullanabilsin diye döngüsel içe aktarma YOK), yoksa `files`. DB hatası (kilit/bozuk) dosya yoluna düşer ve
diag.log'a yazılır: geçiş hiçbir zaman okumayı/yazmayı kırmasın. Geri dönüş = kipi `files` yapmak.
"""
from __future__ import annotations
import json
import os
import threading
import time
from typing import Any, Optional

from . import atomic_json

MODES = ("files", "dual", "db")
_CACHE = {"at": 0.0, "mode": "files"}
_LOCK = threading.Lock()


def backend() -> str:
    env = (os.environ.get("CLAUDEOPS_STORE_BACKEND") or "").strip().lower()
    if env in MODES:
        return env
    now = time.time()
    with _LOCK:
        if now - _CACHE["at"] < 5.0:
            return _CACHE["mode"]
        mode = "files"
        try:
            from .paths import CLAUDEOPS_DIR
            with open(os.path.join(CLAUDEOPS_DIR, "settings.json"), encoding="utf-8") as f:
                v = str((json.load(f) or {}).get("store_backend") or "").strip().lower()
            if v in MODES:
                mode = v
        except (OSError, ValueError, AttributeError):
            pass
        _CACHE.update(at=now, mode=mode)
        return mode


def _db_ok(path: str) -> bool:
    """DB YALNIZ `CLAUDEOPS_DIR` altındaki yollar için kullanılır: testlerin geçici yolları (ya da başka dizin) gerçek
    DB'yi kirletmesin; dışarıdaki yol her zaman `files` gibi davranır."""
    try:
        from .paths import CLAUDEOPS_DIR
        root = os.path.realpath(CLAUDEOPS_DIR) + os.sep
        return (os.path.realpath(path) + os.sep).startswith(root)
    except Exception:
        return False


def _log(msg: str) -> None:
    try:
        from .diaglog import diag_log
        diag_log("statedocs " + msg)
    except Exception:
        pass


def _file_read(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


_MISSING = object()


def read_json(name: str, path: str, default: Any = None, *, file_truth: bool = False) -> Any:
    """`file_truth=True` (elle düzenlenebilen/token'lı belgeler): `dual` kipinde DOSYA doğruluk kaynağıdır; DB ile fark
    varsa loglanır ve DB dosyaya uydurulur. `db` kipinde her zaman DB."""
    mode = backend()
    if mode == "files" or not _db_ok(path):
        return _file_read(path, default)
    try:
        from .store import default_store
        st = default_store()
        if file_truth and mode == "dual":
            v = _file_read(path, _MISSING)
            if v is not _MISSING:
                if st.get_doc(name, _MISSING) != v:
                    _log(f"drift {name}: DB dosyaya uyduruldu")
                    st.set_doc(name, v)
                return v
        v = st.get_doc(name, _MISSING)
        if v is not _MISSING:
            return v
        v = _file_read(path, _MISSING)          # DB'de yok: dosyadan tembel içe aktarma
        if v is not _MISSING:
            st.set_doc(name, v)
            return v
        return default
    except Exception as e:                       # DB sorunu geçişi kırmasın
        _log(f"read {name}: {e!r} -> dosya")
        return _file_read(path, default)


def write_json(name: str, path: str, obj: Any, *, mode: Optional[int] = None) -> None:
    be = backend()
    if not _db_ok(path):
        be = "files"
    if be != "files":
        try:
            from .store import default_store
            default_store().set_doc(name, obj)
        except Exception as e:
            _log(f"write {name}: {e!r}")
            if be == "db":
                atomic_json.atomic_write_json(path, obj, mode=mode)   # DB yazılamadıysa veri kaybolmasın
                return
    if be in ("files", "dual"):
        atomic_json.atomic_write_json(path, obj, mode=mode)


_MIRROR_N = {}
_MIRROR_KEEP = 200000
_MIRROR_EVERY = 2000


def mirror_log(stream: str, path: str, entry: Any) -> None:
    """Dosya günlüğüne yazılan satırı DB `log` akışına da ekle (dual/db). SESSİZ: hata yutulur (günlük best-effort;
    `_log` ÇAĞRILMAZ: diag_log -> mirror_log -> _log -> diag_log döngüsü olmasın). Akış `_MIRROR_EVERY` eklemede bir kırpılır."""
    try:
        if backend() == "files" or not _db_ok(path):
            return
        from .store import default_store
        st = default_store()
        st.append_log(stream, entry)
        n = _MIRROR_N.get(stream, 0) + 1
        _MIRROR_N[stream] = n
        if n % _MIRROR_EVERY == 0:
            st.trim_log(stream, _MIRROR_KEEP)
    except Exception:
        pass
