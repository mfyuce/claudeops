"""remote_desktop — web panelin "Uzak Masaüstü" sekmesi: `rust/screenshare`
Rust daemon'ını on-demand spawn/kill eder; WS bağlantısını proxy'lemek
`commands/web.py`'nin işi (bu modül sadece process lifecycle).

2026-09-04, kullanıcı: "bir yeni tab da remote desktoplar için çalışmaya
başlayalım. gerekirse rust kodu yazalım."

Neden ayrı bir Rust process (Python içinde değil): X11 `GetImage` + JPEG
encode + per-frame gönderim sürekli çalışan CPU-yoğun bir döngü — Rust
seçildi çünkü (a) bu makinede zaten kurulu (b) `x11rb` (pure-Rust X11
protokolü) SIFIR ek sistem paketi gerektiriyor — ilk denenen `xcap` (cross-
platform, Wayland/PipeWire portal'ı da destekleyen bir crate) bu makinede
kurulu olmayan `libpipewire-0.3` dev paketini build-time ZORUNLU kılıyordu;
bu makine X11 (Wayland portal'a hiç ihtiyaç yok), `x11rb`'ye geçilince o
sorun tamamen ortadan kalktı.

Auth: daemon'ın KENDİSİ auth yapmaz — SADECE 127.0.0.1'e bind olur, dışarıdan
hiç erişilemez. Token kontrolü zaten `web.py`'nin proxy route'unda (panelin
TEK auth mekanizması, `_authorized()`) yapılıyor, PROXY token'ı doğruladıktan
SONRA bu daemon'a bağlanıyor — daemon'ın token/HTTP header ayrıştırmayı hiç
bilmesine gerek yok.

View-only (v1): sadece ekran GÖRÜNTÜSÜ akıyor, mouse/keyboard enjeksiyonu
YOK (`x11rb`'nin `xtest` feature'ı ekli ama kullanılmıyor — bilerek, ayrı/
daha yüksek riskli bir fast-follow: kilitli bir ekranın GÖRÜNTÜSÜNÜ almak
zararsız olduğu canlı doğrulandı, ama input enjekte etmek fiilen kilit
ekranını uzaktan açabilmek demek — daha dikkatli bir tasarım ister).

Binary DOĞRUDAN spawn edilir (`cargo run` ile SARMALANMAZ): `cargo run`'ı
`Popen.terminate()`'lemek sinyali gerçek `screenshare` child'ına iletir mi
garanti değil (orphan kalıp arka planda ekran yakalamaya devam etme riski
— bu özelliğin hassasiyeti düşünülünce kabul edilemez); bunun yerine ÖNCE
`cargo build --release` (zaten güncelse near-instant) SONRA `cargo
metadata`'dan çözülen gerçek binary yolu doğrudan `Popen`'lanır — kill
kesin, ambiguity yok.
"""
from __future__ import annotations
import json
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from .paths import REPO_DIR

MANIFEST_PATH = str(Path(REPO_DIR) / "rust" / "screenshare" / "Cargo.toml")
DEFAULT_PORT = 8877
BUILD_TIMEOUT_SECONDS = 120.0  # ilk derleme (soğuk cache) birkaç on saniye sürebilir
PORT_WAIT_SECONDS = 5.0

_lock = threading.Lock()
_proc: Optional[subprocess.Popen] = None
_port: Optional[int] = None


def _port_open(port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _resolve_binary() -> Optional[Path]:
    try:
        result = subprocess.run(
            ["cargo", "metadata", "--manifest-path", MANIFEST_PATH, "--format-version=1", "--no-deps"],
            capture_output=True, text=True, timeout=15.0, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    try:
        target_dir = Path(json.loads(result.stdout)["target_directory"])
    except (json.JSONDecodeError, KeyError):
        return None
    return target_dir / "release" / "screenshare"


def status() -> dict:
    with _lock:
        running = _proc is not None and _proc.poll() is None
        return {"running": running, "port": _port if running else None}


def start(port: int = DEFAULT_PORT) -> dict:
    """Zaten çalışıyorsa no-op. Yoksa: `cargo build --release` (near-instant
    kaynak değişmemişse) → gerçek binary'yi doğrudan spawn et → portu açana
    kadar kısa bekle. Tüm bu süre boyunca lock TUTULUR — eşzamanlı ikinci bir
    `start()` çağrısı (ör. çift tık) paralel bir build/spawn YARIŞMAZ, sırada
    bekler (bu, tek-admin/düşük-trafikli bir özellik için basit ve yeterli)."""
    global _proc, _port
    with _lock:
        if _proc is not None and _proc.poll() is None:
            return {"ok": True, "already_running": True, "port": _port}

        try:
            build = subprocess.run(
                ["cargo", "build", "--release", "--manifest-path", MANIFEST_PATH],
                capture_output=True, text=True, timeout=BUILD_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "cargo build zaman aşımına uğradı"}
        except OSError as e:
            return {"ok": False, "error": f"cargo çalıştırılamadı: {e}"}
        if build.returncode != 0:
            return {"ok": False, "error": f"cargo build başarısız:\n{build.stderr[-2000:]}"}

        binary = _resolve_binary()
        if binary is None or not binary.exists():
            return {"ok": False, "error": f"binary bulunamadı ({binary})"}

        proc = subprocess.Popen(
            [str(binary), str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )
        _proc, _port = proc, port

        deadline = time.monotonic() + PORT_WAIT_SECONDS
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                _proc, _port = None, None
                return {"ok": False, "error": f"screenshare hemen çöktü (exit={proc.returncode})"}
            if _port_open(port):
                return {"ok": True, "port": port}
            time.sleep(0.1)
        return {"ok": False, "error": "screenshare port'u açmadı (timeout)"}


def stop() -> dict:
    global _proc, _port
    with _lock:
        if _proc is None:
            return {"ok": True, "already_stopped": True}
        proc, _proc, _port = _proc, None, None
    proc.terminate()
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
    return {"ok": True}


def current_port() -> Optional[int]:
    with _lock:
        return _port if (_proc is not None and _proc.poll() is None) else None
