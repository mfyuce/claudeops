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

v1 (ilk sürüm) view-only'ydu. v2 (2026-09-04, aynı gün) `enigo` ile mouse/
klavye/scroll enjeksiyonunu EKLEDİ (Rust tarafı + frontend `DesktopTab.tsx`
"Kontrolü Al" anahtarı canlı doğrulandı) — bu modülde (`remote_desktop.py`)
o yüzden HİÇBİR değişiklik gerekmedi, lifecycle zaten protokol-agnostik.
Kilitli bir ekranın GÖRÜNTÜSÜNÜ almak zararsızken (canlı doğrulandı), input
enjekte etmek fiilen kilit ekranını uzaktan açabilmek demektir — bu hâlâ
geçerli/canlı bir risk, "Kontrolü Al" varsayılan KAPALI olması ve makinenin
GERÇEK fare/klavyesiyle aynı input yolunu paylaşması (fiziksel kullanıcıyla
çakışabilir) bu yüzden — bkz. `DesktopTab.tsx`'in dosya başı yorumu.

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
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from .paths import CLAUDEOPS_DIR, REPO_DIR

MANIFEST_PATH = str(Path(REPO_DIR) / "rust" / "screenshare" / "Cargo.toml")
DEFAULT_PORT = 8877
BUILD_TIMEOUT_SECONDS = 120.0  # ilk derleme (soğuk cache) birkaç on saniye sürebilir
PORT_WAIT_SECONDS = 5.0

# web.py servisi restart edilince (her deploy sonrası rutin) `KillMode=process`
# bu child'ı YAŞATIR (kasıtlı — tmux-backed session'larla aynı sebep) ama bu
# modülün bellek-içi _proc/_port'u sıfırlanır → orphan hem "çalışmıyor" görünür
# HEM yeni bir start() aynı porta ikinci bir binary spawn edip (port çakışması
# yüzünden anında çöker ama _port_open() eski orphan'ı gördüğü için YANLIŞLIKLA
# "ok:true" döner — 2026-09-07 canlı tekrarlandı) PID-exact kill imkanını
# kaybeder. PID_FILE bunu köprüler: spawn'da yazılır, status()/start()/stop()
# önce burayı okuyup canlılığı+portu doğrulayarak "adopt" eder — pattern-match
# pkill YOK (CLAUDE.md), sadece diskten okunan tam PID.
PID_FILE = os.path.join(CLAUDEOPS_DIR, "remote_desktop.pid")

_lock = threading.Lock()
_proc: Optional[subprocess.Popen] = None
_port: Optional[int] = None
_adopted_pid: Optional[int] = None  # spawn etmediğimiz ama PID_FILE'dan tanıdığımız canlı orphan


def _port_open(port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # var ama bize ait değil (EPERM) — yine de canlı say
    return True


def _write_pid_file(pid: int, port: int) -> None:
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(f"{pid} {port}\n")
    except OSError:
        pass


def _clear_pid_file() -> None:
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def _adopt_if_orphaned() -> None:
    """`_lock` TUTULUYORKEN çağrılmalı. Elimizde ne canlı bir Popen ne de zaten
    adopt edilmiş bir PID varsa, PID_FILE'daki kaydı dene: PID hâlâ yaşıyor VE
    o port hâlâ açıksa bu bizim eski child'ımız (restart'ı atlatmış) — adopt
    et. Değilse (biri öldü/temizlendi) dosyayı sil, bir daha denenmesin."""
    global _adopted_pid, _port
    if _proc is not None or _adopted_pid is not None:
        return
    try:
        with open(PID_FILE, encoding="utf-8") as f:
            pid_str, port_str = f.read().split()
        pid, port = int(pid_str), int(port_str)
    except (OSError, ValueError):
        return
    if _pid_alive(pid) and _port_open(port):
        _adopted_pid, _port = pid, port
    else:
        _clear_pid_file()


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
        _adopt_if_orphaned()
        running = (_proc is not None and _proc.poll() is None) or _adopted_pid is not None
        return {"running": running, "port": _port if running else None}


def start(port: int = DEFAULT_PORT) -> dict:
    """Zaten çalışıyorsa no-op. Yoksa: `cargo build --release` (near-instant
    kaynak değişmemişse) → gerçek binary'yi doğrudan spawn et → portu açana
    kadar kısa bekle. Tüm bu süre boyunca lock TUTULUR — eşzamanlı ikinci bir
    `start()` çağrısı (ör. çift tık) paralel bir build/spawn YARIŞMAZ, sırada
    bekler (bu, tek-admin/düşük-trafikli bir özellik için basit ve yeterli)."""
    global _proc, _port, _adopted_pid
    with _lock:
        _adopt_if_orphaned()
        if _proc is not None and _proc.poll() is None:
            return {"ok": True, "already_running": True, "port": _port}
        if _adopted_pid is not None:
            return {"ok": True, "already_running": True, "port": _port, "adopted": True}

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
                _write_pid_file(proc.pid, port)
                return {"ok": True, "port": port}
            time.sleep(0.1)
        return {"ok": False, "error": "screenshare port'u açmadı (timeout)"}


def stop() -> dict:
    global _proc, _port, _adopted_pid
    with _lock:
        _adopt_if_orphaned()
        if _proc is None and _adopted_pid is None:
            return {"ok": True, "already_stopped": True}
        proc, adopted_pid = _proc, _adopted_pid
        _proc, _port, _adopted_pid = None, None, None
    _clear_pid_file()
    if proc is not None:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        return {"ok": True}
    # Adopted orphan — hiç Popen handle'ımız yok, PID-exact sinyal (pattern-match YOK, CLAUDE.md).
    try:
        os.kill(adopted_pid, signal.SIGTERM)
    except ProcessLookupError:
        return {"ok": True}
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _pid_alive(adopted_pid):
            return {"ok": True}
        time.sleep(0.1)
    try:
        os.kill(adopted_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return {"ok": True}


def current_port() -> Optional[int]:
    with _lock:
        _adopt_if_orphaned()
        if (_proc is not None and _proc.poll() is None) or _adopted_pid is not None:
            return _port
        return None
