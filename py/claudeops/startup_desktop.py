"""Yeni CLI penceresini doğrudan hedef masaüstünde açtır (TBD#409, Python istisnası, 27 Kas 2026).

gnome-terminal'in masaüstü bayrağı yok. Yöntem: açılıştan ÖNCE X11 başlangıç bildirimi
(`_NET_STARTUP_INFO`, "new: ID=... DESKTOP=N") kök pencereye gönderilir ve gnome-terminal
`DESKTOP_STARTUP_ID=ID` ile başlatılır; Mutter pencereyi eşlemeden önce N'ye koyar. Pencere bakılan
masaüstünde HİÇ görünmez, bakılan masaüstü değişmez (sunum sırasında önemli; 27 Kas canlı denendi).

Ayar `settings.spawn_desktop` (0 tabanlı; varsayılan 1 = 2. masaüstü; negatif = kapalı). Hedef yoksa
1'e, o da yoksa 0'a düşer. Masaüstü sayısı okunamazsa ya da X'e ulaşılamazsa özellik sessizce devre dışı
kalır, pencere eskisi gibi açılır: açılışı ASLA engellemez, fırlatmaz.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import subprocess
import time
from typing import Callable, Dict, List, Optional

DEFAULT_DESKTOP = 1


def resolve_desktop(want: Optional[int], count: Optional[int]) -> Optional[int]:
    """İstenen masaüstü (0 tabanlı) + mevcut sayı -> kullanılacak masaüstü; None = özellik kapalı/uygulanamaz."""
    if want is None or count is None or count <= 0:
        return None
    try:
        want = int(want)
    except (TypeError, ValueError):
        return None
    if want < 0:
        return None
    if want < count:
        return want
    return 1 if count > 1 else 0


def wanted_desktop(settings: Dict) -> Optional[int]:
    v = settings.get("spawn_desktop", DEFAULT_DESKTOP)
    if isinstance(v, bool):
        return None
    try:
        v = int(v)
    except (TypeError, ValueError):
        return DEFAULT_DESKTOP
    return v if v >= 0 else None


def desktop_count(display: str, run: Callable = subprocess.run) -> Optional[int]:
    """`wmctrl -d` satır sayısı; okunamazsa None."""
    try:
        r = run(["wmctrl", "-d"], env=dict(os.environ, DISPLAY=display), capture_output=True,
                text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    n = sum(1 for ln in r.stdout.splitlines() if ln.strip())
    return n or None


def _quote(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_message(sid: str, name: str, desktop: int) -> bytes:
    return ("new: ID=%s NAME=%s SCREEN=0 DESKTOP=%d\0" % (_quote(sid), _quote(name), desktop)).encode("utf-8")


def chunks(msg: bytes) -> List[bytes]:
    """20 baytlık ClientMessage parçaları (sonuncusu NUL ile doldurulur)."""
    return [msg[i:i + 20].ljust(20, b"\0") for i in range(0, len(msg), 20)]


def new_startup_id(now: Optional[float] = None) -> str:
    t = time.time() if now is None else now
    return "claudeops-%d-%d_TIME%d" % (os.getpid(), int(t * 1000), int(t * 1000) & 0xFFFFFFFF)


class _XClientData(ctypes.Union):
    # Xlib'deki union {char b[20]; short s[10]; long l[5];}: long hizalaması verinin konumunu belirler
    # (yalnız char[20] yazılırsa 64 bitte 4 bayt kayar ve mesaj bozulur).
    _fields_ = [("b", ctypes.c_char * 20), ("l", ctypes.c_long * 5)]


class _XClientMessageEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("data", _XClientData)]


class _XEvent(ctypes.Union):
    _fields_ = [("xclient", _XClientMessageEvent), ("pad", ctypes.c_long * 24)]


_CLIENT_MESSAGE = 33
_PROPERTY_CHANGE_MASK = 1 << 22


def send_startup_x11(display: str, msg: bytes) -> bool:
    """Başlangıç bildirimini kök pencereye gönder (libX11, ctypes). Hata = False."""
    path = ctypes.util.find_library("X11")
    if not path:
        return False
    x = ctypes.CDLL(path)
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XCreateSimpleWindow.restype = ctypes.c_ulong
    x.XCreateSimpleWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                                      ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_ulong]
    x.XInternAtom.restype = ctypes.c_ulong
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.POINTER(_XEvent)]
    x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x.XDestroyWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    d = x.XOpenDisplay(display.encode())
    if not d:
        return False
    try:
        root = x.XDefaultRootWindow(d)
        w = x.XCreateSimpleWindow(d, root, -100, -100, 1, 1, 0, 0, 0)
        begin = x.XInternAtom(d, b"_NET_STARTUP_INFO_BEGIN", 0)
        cont = x.XInternAtom(d, b"_NET_STARTUP_INFO", 0)
        for i, part in enumerate(chunks(msg)):
            ev = _XEvent()
            ev.xclient.type = _CLIENT_MESSAGE
            ev.xclient.send_event = 1
            ev.xclient.display = d
            ev.xclient.window = w
            ev.xclient.message_type = begin if i == 0 else cont
            ev.xclient.format = 8
            ctypes.memmove(ctypes.addressof(ev.xclient.data), part, 20)
            x.XSendEvent(d, root, 0, _PROPERTY_CHANGE_MASK, ctypes.byref(ev))
        x.XSync(d, 0)
        x.XDestroyWindow(d, w)
        x.XSync(d, 0)
        return True
    finally:
        x.XCloseDisplay(d)


def startup_env(env: Dict[str, str], name: str, *, settings: Optional[Dict] = None,
                count_fn: Callable[[str], Optional[int]] = desktop_count,
                send_fn: Callable[[str, bytes], bool] = send_startup_x11) -> Dict[str, str]:
    """`env` + `DESKTOP_STARTUP_ID` (hedef masaüstüne yönlendirilmiş). Uygulanamazsa `env` aynen döner."""
    # Test koşusunda gerçek masaüstüne bildirim gitmesin (Popen'ı sahteleyen eski testler bu yolu da
    # çağırır): sahte fonksiyon VERİLMEDİYSE ve unittest/pytest yüklüyse kapalı.
    import sys
    if (send_fn is send_startup_x11 or count_fn is desktop_count) and (
            "unittest" in sys.modules or "pytest" in sys.modules):
        return env
    try:
        if settings is None:
            from .settings import load_settings
            settings = load_settings()
        want = wanted_desktop(settings)
        display = env.get("DISPLAY") or ""
        if want is None or not display:
            return env
        desk = resolve_desktop(want, count_fn(display))
        if desk is None:
            return env
        sid = new_startup_id()
        if not send_fn(display, build_message(sid, name, desk)):
            return env
        out = dict(env)
        out["DESKTOP_STARTUP_ID"] = sid
        return out
    except Exception as e:      # açılışı ASLA engellemesin
        try:
            from .diaglog import diag_log
            diag_log("startup_desktop_error", name=name, error=str(e)[:200])
        except Exception:
            pass
        return env
