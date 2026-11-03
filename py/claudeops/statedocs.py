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


# `db` kipinde YALNIZ okuyucuları tamamen DB'ye bağlanmış belgeler DB-tek-kaynak olur; diğerleri `db` istense bile `dual`
# (dosya doğruluk kaynağı, DB gölge) davranır. Yeni belgenin okuyucusu DB'ye bağlanınca buraya eklenir.
DB_READY = {"hosts", "steward/quota"}


def name_for(path: str) -> str:
    """`CLAUDEOPS_DIR` altındaki yoldan belge adı: `steward/stewards/rev/questions.json` -> `steward/stewards/rev/questions`."""
    from .paths import CLAUDEOPS_DIR
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(CLAUDEOPS_DIR))
    return rel[:-5] if rel.endswith(".json") else rel


def _effective(name: str) -> str:
    m = backend()
    return "dual" if (m == "db" and name not in DB_READY) else m


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


def _file_read(path: str, default: Any, on_corrupt: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except ValueError:
        if on_corrupt is not None:          # bozuk dosya: çağıranın kanıt yedeği (ör. steward `.corrupt-<ts>`)
            try:
                on_corrupt(path)
            except Exception:
                pass
        return default
    except OSError:
        return default


_MISSING = object()


_SYNCED: dict = {}   # ad -> (mtime_ns, size) en son DB ile eşitlenmiş dosya imzası (büyük dosyada her okumada DB karşılaştırma YOK)


def _sig(path: str):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def read_json(name: str, path: str, default: Any = None, *, file_truth: bool = True, on_corrupt: Any = None) -> Any:
    """`dual`: DOSYA doğruluk kaynağı, DB gölge kopya (uzun yaşayan eski kodlu süreçler yalnız dosyaya yazabilir; elle düzenleme
    ezilmez). Dosya imzası (mtime,size) son eşitlemeden değiştiyse DB ile karşılaştırılır, fark loglanır ve DB uydurulur;
    dosya yoksa DB'den okunur. `db`: DB tek kaynak (dosya yoksa tek seferlik içe aktarma). `file_truth=False`: dual'de de DB önce."""
    mode = _effective(name)
    if mode == "files" or not _db_ok(path):
        return _file_read(path, default, on_corrupt)
    try:
        from .store import default_store
        st = default_store()
        if mode == "dual" and file_truth:
            v = _file_read(path, _MISSING, on_corrupt)
            if v is not _MISSING:
                sg = _sig(path)
                if _SYNCED.get(name) != sg:
                    if st.get_doc(name, _MISSING) != v:
                        _log(f"drift {name}: DB dosyaya uyduruldu")
                        st.set_doc(name, v)
                    _SYNCED[name] = sg
                return v
            v = st.get_doc(name, _MISSING)
            return default if v is _MISSING else v
        v = st.get_doc(name, _MISSING)
        if v is not _MISSING:
            return v
        v = _file_read(path, _MISSING, on_corrupt)          # DB'de yok: dosyadan tembel içe aktarma
        if v is not _MISSING:
            st.set_doc(name, v)
            return v
        return default
    except Exception as e:                       # DB sorunu geçişi kırmasın
        _log(f"read {name}: {e!r} -> dosya")
        return _file_read(path, default, on_corrupt)


def write_json(name: str, path: str, obj: Any, *, mode: Optional[int] = None, writer: Any = None) -> None:
    """`writer`: çağıran modülün KENDİ `atomic_write_json` sembolü. Testler o sembolü taklit eder (gerçek dosyaya yazmasın diye);
    taklit edilmişse (`atomic_json.atomic_write_json` ile aynı nesne DEĞİLSE) DB'ye HİÇ dokunulmaz ve yalnız o yazıcı çağrılır:
    taklit edilen yazımın gerçek DB'yi/ayarı ezmesi (2026-11-03 settings.json kazası) böylece imkânsız."""
    wr = writer if writer is not None else atomic_json.atomic_write_json
    be = _effective(name)
    if not _db_ok(path) or wr is not atomic_json.atomic_write_json:
        be = "files"
    if be != "files":
        try:
            from .store import default_store
            default_store().set_doc(name, obj)
        except Exception as e:
            _log(f"write {name}: {e!r}")
            if be == "db":
                wr(path, obj, mode=mode)   # DB yazılamadıysa veri kaybolmasın
                return
    if be in ("files", "dual"):
        wr(path, obj, mode=mode)
        if be == "dual":
            _SYNCED[name] = _sig(path)         # bu yazımla DB zaten eşit: ilk okumada gereksiz karşılaştırma yok


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


_TSV_FILES = ("roster.tsv", "models.tsv")


def shadow_tsv(path: str, *, force: bool = False) -> None:
    """`roster.tsv`/`models.tsv` dosyasının GÜNCEL içeriğini DB `tsv_rows` tablosuna eşitle (gölge; dosya doğruluk kaynağı).
    Dosya imzası (mtime,size) son eşitlemeden değişmediyse atlanır (okuyucuda ucuz çağrı); `force` = yazımdan hemen sonra.
    Elle/bash/eski kodla yapılan düzenlemeler de bir sonraki okumada yakalanır. SESSİZ: hata yutulur (geçişi kırmasın)."""
    try:
        if backend() == "files" or os.path.basename(path) not in _TSV_FILES or not _db_ok(path):
            return
        sg = _sig(path)
        key = "tsv:" + name_for(path)
        if not force and _SYNCED.get(key) == sg:
            return
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            return
        from .store import default_store
        st = default_store()
        if st.tsv_text(name_for(path)) != text:
            st.replace_tsv(name_for(path), text)
        _SYNCED[key] = sg
    except Exception as e:
        _log(f"shadow_tsv {path}: {e!r}")
