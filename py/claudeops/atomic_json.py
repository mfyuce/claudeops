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
import contextlib
import fcntl
import json
import logging
import os
import threading
from typing import Any, Iterator, Optional


def _existing_mode(path: str, mode: Optional[int]) -> Optional[int]:
    """`mode=None` iken hedef zaten varsa (normal dosya) onun izni korunur (0600'lük dosya 0644'e açılmasın)."""
    if mode is not None:
        return mode
    try:
        st = os.stat(path)
    except OSError:
        return None
    import stat as _stat
    return _stat.S_IMODE(st.st_mode) if _stat.S_ISREG(st.st_mode) else None


def _fsync_dir(path: str) -> None:
    """`os.replace` sonrası dizin girdisini kalıcılaştır (best-effort)."""
    try:
        dfd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dfd)
    except OSError:
        pass
    finally:
        os.close(dfd)


def _open_tmp(tmp: str, mode: Optional[int]):
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o666 if mode is None else mode)   # None: umask uygular
    try:
        f = os.fdopen(fd, "w", encoding="utf-8")
    except BaseException:
        os.close(fd)            # fdopen düşerse tanıtıcı sızmasın
        raise
    if mode is not None:
        with contextlib.suppress(OSError):
            os.fchmod(fd, mode)  # umask'ı aşarak istenen/korunan izin
    return f


def atomic_write_json(path: str, obj: Any, *, mode: Optional[int] = None) -> None:
    """`mode=None` → düz `open()` (umask varsayılanı, ör. `settings.json`).
    `mode=0o600` gibi verilirse → `os.open()` ile İLK OLUŞTURMADAN itibaren o
    izinle (ör. `hosts.json`/`orchestration/*.json` — `os.replace` hedefi
    KAYNAĞIN izinleriyle değiştirir, sonradan chmod'lamak yerine baştan doğru
    açmak gerekir). Veri `fsync`lenir (güç kesintisinde boş/yarım dosya kalmasın);
    yazım düşerse geçici dosya silinir (sızmaz). Dizinsiz ad (`x.json`) çalışır."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    mode = _existing_mode(path, mode)
    tmp = f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"
    try:
        with contextlib.suppress(OSError):
            os.remove(tmp)      # önceki çöküşten kalan aynı adlı tmp (ya da yerleştirilmiş symlink) takip edilmesin
        f = _open_tmp(tmp, mode)
        with f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomik — eşzamanlı okuyan yarım dosya görmez
        _fsync_dir(path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: str, text: str, *, mode: Optional[int] = None) -> None:
    """`atomic_write_json`'un düz-metin karşılığı: pid+thread'e özel tmp (sabit `<path>.tmp` yarışı yok), O_EXCL|O_NOFOLLOW,
    `fsync`, `os.replace`. Yazım düşerse tmp silinir. `mode=None` → umask varsayılanı."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    mode = _existing_mode(path, mode)
    tmp = f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"
    try:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        with _open_tmp(tmp, mode) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        _fsync_dir(path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict = {}
_HELD = threading.local()       # iş parçacığı başına {path: iç içe derinlik}
_WARNED_LOCKS: set = set()      # path başına tek uyarı (log taşmasın)


@contextlib.contextmanager
def file_lock(path: str) -> Iterator[None]:
    """`path + ".lock"` üzerinde oku-değiştir-yaz döngüsü için kilit: süreç içi (path başına `RLock`) + süreçler arası
    `flock`. Kilit dosyası `O_NOFOLLOW` ile açılır ve çağıranın kendisine ait normal dosya olmalı (symlink/başkasının
    dosyası = kilit dosyası KULLANILMAZ, yalnız iş parçacığı kilidiyle devam; bir hedefi sessizce yaratmaz/kilitlemez)."""
    with _LOCKS_GUARD:
        tl = _THREAD_LOCKS.setdefault(path, threading.RLock())
    with tl:
        held = getattr(_HELD, "paths", None)
        if held is None:
            held = _HELD.paths = {}
        if held.get(path, 0) > 0:       # aynı iş parçacığı zaten tutuyor: ikinci flock (başka fd) kendini kilitlerdi
            held[path] += 1
            try:
                yield
            finally:
                held[path] -= 1
            return
        held[path] = 1
        try:
            with _file_lock_outer(path):
                yield
        finally:
            held.pop(path, None)


@contextlib.contextmanager
def _file_lock_outer(path: str) -> Iterator[None]:
    fd = None
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        fd = os.open(path + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        st = os.fstat(fd)
        if not os.path.isfile(path + ".lock") or st.st_uid != os.getuid():
            raise OSError("lock file not ours")
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError as e:
        if fd is not None:
            os.close(fd)
        fd = None
        if path not in _WARNED_LOCKS:       # sessiz değil: süreçler arası koruma yok, yalnız iş parçacığı kilidi
            _WARNED_LOCKS.add(path)
            logging.getLogger(__name__).warning("file_lock: %s.lock alınamadı (%s); yalnız iş parçacığı kilidiyle devam", path, e)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)        # kapatmak flock'u bırakır
