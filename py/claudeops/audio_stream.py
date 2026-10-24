"""Bilgisayarın ÇIKIŞ sesini (varsayılan hoparlör/kulaklığın monitörü) panele MP3 akışı olarak verir (Masaüstü sekmesi).

`parec <varsayılan çıkış>.monitor | ffmpeg -> mp3`, bağlantı başına bir boru hattı; dinleyen yoksa süreç yok (başlat/durdur =
tarayıcıda `<audio>`ı bağlamak/kesmek). Auth panelin kendi `?token=`'ı (web.py `_authorized`), ayrı port/tünel YOK.
Dinleyen sayısı sınırlı; istemci koptuğunda ya da `MAX_SECONDS` dolunca boru hattı kapanır. Yalnız YEREL makine.

Tuzak: `parec -d @DEFAULT_SINK@.monitor` takma adı "Invalid argument" verir; gerçek ad `pactl get-default-sink` + ".monitor"
(kulaklık takılıp çıkınca varsayılan değişir, o yüzden her akış başında yeniden okunur)."""
from __future__ import annotations
import select
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

MAX_LISTENERS = 2
MAX_SECONDS = 6 * 3600          # unutulan sekme sesi sonsuza dek taşımasın
CHUNK = 4096
POLL_SECONDS = 5.0
BITRATE = "64k"
TOOLS = ("pactl", "parec", "ffmpeg")

_LOCK = threading.Lock()
_listeners = 0


def missing_tools() -> List[str]:
    return [t for t in TOOLS if shutil.which(t) is None]


def default_monitor() -> str:
    """Varsayılan çıkışın monitör kaynağı adı; bulunamazsa ""."""
    try:
        r = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    sink = (r.stdout or "").strip()
    return f"{sink}.monitor" if r.returncode == 0 and sink else ""


def status() -> Dict[str, Any]:
    miss = missing_tools()
    return {"ok": True, "available": not miss, "missing": miss, "listeners": _listeners, "max_listeners": MAX_LISTENERS,
            "source": default_monitor() if not miss else ""}


def _acquire() -> bool:
    global _listeners
    with _LOCK:
        if _listeners >= MAX_LISTENERS:
            return False
        _listeners += 1
        return True


def _release() -> None:
    global _listeners
    with _LOCK:
        _listeners = max(0, _listeners - 1)


def _client_gone(conn: Any) -> bool:
    """İstemci soketi kapandı mı (okunabilir ve 0 bayt = karşı taraf kapattı)."""
    try:
        r, _w, _x = select.select([conn], [], [], 0)
        if not r:
            return False
        return conn.recv(1, 2) == b""      # MSG_PEEK = 2
    except (OSError, ValueError):
        return True


def stream(handler: Any) -> None:
    """GET /api/audio/live.mp3 gövdesi. Hata durumunda (araç yok / dolu / kaynak yok) JSON ile döner."""
    miss = missing_tools()
    if miss:
        handler._json({"ok": False, "error": "audio tools missing: " + ", ".join(miss)}, status=503)
        return
    source = default_monitor()
    if not source:
        handler._json({"ok": False, "error": "no default audio output"}, status=503)
        return
    if not _acquire():
        handler._json({"ok": False, "error": "too many listeners"}, status=429)
        return
    rec: Optional[subprocess.Popen] = None
    enc: Optional[subprocess.Popen] = None
    try:
        rec = subprocess.Popen(["parec", "-d", source, "--format=s16le", "--rate=44100", "--channels=2", "--latency-msec=100"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        enc = subprocess.Popen(["ffmpeg", "-loglevel", "quiet", "-f", "s16le", "-ar", "44100", "-ac", "2", "-i", "-",
                                "-c:a", "libmp3lame", "-b:a", BITRATE, "-flush_packets", "1", "-f", "mp3", "-"],
                               stdin=rec.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        rec.stdout.close()
        handler.close_connection = True
        handler.send_response(200)
        handler.send_header("Content-Type", "audio/mpeg")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")
        handler.end_headers()
        deadline = time.time() + MAX_SECONDS
        while time.time() < deadline:
            ready, _w, _x = select.select([enc.stdout], [], [], POLL_SECONDS)
            if not ready:
                if _client_gone(handler.connection):
                    break
                continue
            data = enc.stdout.read1(CHUNK)
            if not data:
                break
            handler.wfile.write(data)
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        for p in (enc, rec):
            if p is not None:
                try:
                    p.terminate()
                    p.wait(timeout=3)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
        _release()
