"""Özel Xvfb için X11 yardımcısı (yalnız `tests/real_x11.rs` koşar; gerçek ekrana DOKUNMAZ).

`listen <ekran> <adet>`: kök pencerede YALNIZ PropertyChangeMask seçer, "ready" basar, gelen ClientMessage olaylarını ham
`XEvent` baytlarından (64 bit Xlib konumları) okuyup JSON basar. `send <ekran> <onaltılık ileti>`: Python
`startup_desktop.send_startup_x11`.
"""
import ctypes
import ctypes.util
import json
import os
import struct
import sys
import time

CLIENT_MESSAGE = 33
PROPERTY_CHANGE_MASK = 1 << 22


def listen(display: str, want: int) -> None:
    x = ctypes.CDLL(ctypes.util.find_library("X11"))
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
    x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x.XPending.argtypes = [ctypes.c_void_p]
    x.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    x.XGetAtomName.restype = ctypes.c_void_p
    x.XGetAtomName.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    d = x.XOpenDisplay(display.encode())
    if not d:
        sys.exit(2)
    x.XSelectInput(d, x.XDefaultRootWindow(d), PROPERTY_CHANGE_MASK)
    x.XSync(d, 0)
    print("ready", flush=True)
    out = []
    buf = ctypes.create_string_buffer(192)
    deadline = time.monotonic() + 10
    while len(out) < want and time.monotonic() < deadline:
        if not x.XPending(d):
            time.sleep(0.01)
            continue
        x.XNextEvent(d, buf)
        raw = buf.raw
        kind = struct.unpack_from("i", raw, 0)[0]
        if kind != CLIENT_MESSAGE:
            continue
        send_event = struct.unpack_from("i", raw, 16)[0]
        window, atom = struct.unpack_from("LL", raw, 32)
        fmt = struct.unpack_from("i", raw, 48)[0]
        name = ctypes.string_at(x.XGetAtomName(d, atom)).decode()
        out.append({"atom": name, "format": fmt, "send_event": send_event, "window": window,
                    "data": raw[56:76].hex()})
    print(json.dumps(out), flush=True)


if __name__ == "__main__":
    mode, display, arg = sys.argv[1:4]
    if mode == "listen":
        listen(display, int(arg))
    else:
        sys.path.insert(0, os.environ["COPS_PY"])
        from claudeops.startup_desktop import send_startup_x11
        print(json.dumps(send_startup_x11(display, bytes.fromhex(arg))))
