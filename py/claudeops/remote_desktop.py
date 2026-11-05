"""remote_desktop — web panelin "Uzak Masaüstü" sekmesi: `uzakgoz` (eski adı `screenshare`)
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

Auth: daemon `UZAKGOZ_TOKEN` ortam değişkeniyle (start() üretir, argv'ye girmez) bağlantıda `?token=` ister;
127.0.0.1'e bind olsa da çok kullanıcılı makinede başka yerel kullanıcılar bağlanamasın diye. Panelin kendi
auth'u `web.py` proxy route'unda (`_authorized()`) yapılır; proxy istemcinin token/ticket anahtarlarını silip
daemon token'ını ekler (`rewrite_path_with_token`), panel token'ı daemon'a ulaşmaz.

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
import secrets
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from .paths import CLAUDEOPS_DIR, REPO_DIR
from .settings import uzakgoz_config

MANIFEST_PATH = str(Path(REPO_DIR) / "rust" / "screenshare" / "Cargo.toml")   # ESKİ yer (ayrı `uzakgoz` reposu yoksa yedek)


def _manifest_path() -> str:
    """Derlenecek crate: ayardaki/varsayılan `uzakgoz` dizini (ayrı repo), yoksa claudeops içindeki eski kopya."""
    d = uzakgoz_config()["dir"]
    return os.path.join(d, "Cargo.toml") if d else MANIFEST_PATH
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

# Daemon'a özel oturum token'ı (UZAKGOZ_TOKEN): çok kullanıcılı makinede başka yerel kullanıcıların
# 127.0.0.1 portuna doğrudan bağlanmasını engeller. Yalnız ortam değişkeniyle verilir (argv/log'a GİRMEZ),
# 0600 dosyada restart sonrası sahiplenme için saklanır.
TOKEN_FILE = os.path.join(CLAUDEOPS_DIR, "remote_desktop.token")

_lock = threading.Lock()
_token: Optional[str] = None
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
    except PermissionError:
        return False  # OPS-07: EPERM = başka kullanıcının süreci (PID yeniden kullanılmış); bizim daemon'umuz DEĞİL, canlı sayma
    except OSError:
        return False
    return True


DAEMON_NAMES = ("uzakgoz", "screenshare")     # yeni ad + geçiş dönemindeki eski ad (çalışan eski süreç adopt edilir)
LOCAL_BIN = Path(REPO_DIR) / "bin" / "uzakgoz"  # claudeops'un git-dışı kopyası (uzakgoz `scripts/deliver.sh` teslim eder)


def _is_screenshare(pid: int) -> bool:
    """PID hâlâ bizim `uzakgoz` (eski adıyla `screenshare`) ikilisi mi? (PID yeniden kullanımı: orphan öldü, aynı numarayı başka süreç aldı.)
    /proc yoksa (Linux dışı) doğrulanamaz: True (eski davranış)."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            argv0 = f.read().split(b"\0", 1)[0]
    except FileNotFoundError:
        return False
    except OSError:
        return not os.path.isdir("/proc")
    return os.path.basename(argv0.decode("utf-8", "replace")) in DAEMON_NAMES


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


def _write_token_file(token: str) -> None:
    """Token'ı 0600 ile yazar (oluşturulurken bile başkaları okuyamaz). Yazılamazsa OSError yükselir."""
    tmp = TOKEN_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(token)
        os.chmod(tmp, 0o600)
        os.replace(tmp, TOKEN_FILE)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _read_token_file() -> Optional[str]:
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            t = f.read().strip()
    except OSError:
        return None
    return t or None


def _clear_token() -> None:
    global _token
    _token = None
    try:
        os.remove(TOKEN_FILE)
    except OSError:
        pass


def _kill_pid(pid: int) -> None:
    """PID-exact sonlandırma (pattern-match YOK): önce SIGTERM, 5 sn sonra hâlâ bizim ikilimizse SIGKILL."""
    if not _is_screenshare(pid):
        return      # PID yeniden kullanılmış: başka sürece sinyal gönderme
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    if _is_screenshare(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _adopt_if_orphaned() -> None:
    """`_lock` TUTULUYORKEN çağrılmalı. Elimizde ne canlı bir Popen ne de zaten
    adopt edilmiş bir PID varsa, PID_FILE'daki kaydı dene: PID hâlâ yaşıyor VE
    o port hâlâ açıksa bu bizim eski child'ımız (restart'ı atlatmış) — adopt
    et. Değilse (biri öldü/temizlendi) dosyayı sil, bir daha denenmesin."""
    global _adopted_pid, _port, _token
    if _adopted_pid is not None:
        # Daha önce adopt ettiğimiz orphan öldü ya da PID başka sürece geçti: bayat kaydı bırak (yoksa `status` hep
        # "çalışıyor" der ve `stop` yeniden kullanılmış bir PID'ye sinyal gönderirdi).
        if not (_pid_alive(_adopted_pid) and _is_screenshare(_adopted_pid)):
            _adopted_pid, _port = None, None
            _clear_pid_file()
            _clear_token()
        return
    if _proc is not None:
        return
    try:
        with open(PID_FILE, encoding="utf-8") as f:
            pid_str, port_str = f.read().split()
        pid, port = int(pid_str), int(port_str)
    except (OSError, ValueError):
        return
    if _pid_alive(pid) and _is_screenshare(pid) and _port_open(port):
        tok = _read_token_file()
        if tok is None:
            # Token'sız eski yetim: herhangi bir yerel kullanıcı bağlanabilir. Sahiplenme, durdur
            # (start() sonra tokenla yeniden başlatır).
            _kill_pid(pid)
            _clear_pid_file()
            return
        _adopted_pid, _port, _token = pid, port, tok
    else:
        _clear_pid_file()


def _resolve_binary(manifest: Optional[str] = None) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["cargo", "metadata", "--manifest-path", manifest or _manifest_path(), "--format-version=1", "--no-deps"],
            capture_output=True, text=True, timeout=15.0, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    try:
        target_dir = Path(json.loads(result.stdout)["target_directory"])
    except (json.JSONDecodeError, KeyError):
        return None
    new = target_dir / "release" / "uzakgoz"
    return new if new.exists() else target_dir / "release" / "screenshare"


def status() -> dict:
    with _lock:
        _adopt_if_orphaned()
        running = (_proc is not None and _proc.poll() is None) or _adopted_pid is not None
        return {"running": running, "port": _port if running else None}


def start(port: Optional[int] = None) -> dict:
    """Zaten çalışıyorsa no-op. Yoksa: `cargo build --release` (near-instant
    kaynak değişmemişse) → gerçek binary'yi doğrudan spawn et → portu açana
    kadar kısa bekle. Tüm bu süre boyunca lock TUTULUR — eşzamanlı ikinci bir
    `start()` çağrısı (ör. çift tık) paralel bir build/spawn YARIŞMAZ, sırada
    bekler (bu, tek-admin/düşük-trafikli bir özellik için basit ve yeterli)."""
    global _proc, _port, _adopted_pid, _token
    cfg = uzakgoz_config()
    port = port or cfg["port"] or DEFAULT_PORT
    with _lock:
        _adopt_if_orphaned()
        if _proc is not None and _proc.poll() is None:
            return {"ok": True, "already_running": True, "port": _port}
        if _adopted_pid is not None:
            return {"ok": True, "already_running": True, "port": _port, "adopted": True}

        if cfg["bin"]:                      # hazır ikili: derleme YOK
            binary: Optional[Path] = Path(cfg["bin"])
        elif LOCAL_BIN.is_file():           # claudeops'un teslim edilmiş kopyası: derleme YOK
            binary = LOCAL_BIN
        else:
            manifest = _manifest_path()
            try:
                build = subprocess.run(
                    ["cargo", "build", "--release", "--manifest-path", manifest],
                    capture_output=True, text=True, timeout=BUILD_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "cargo build zaman aşımına uğradı"}
            except OSError as e:
                return {"ok": False, "error": f"cargo çalıştırılamadı: {e}"}
            if build.returncode != 0:
                return {"ok": False, "error": f"cargo build başarısız:\n{build.stderr[-2000:]}"}
            binary = _resolve_binary(manifest)
        if binary is None or not binary.exists():
            return {"ok": False, "error": f"binary bulunamadı ({binary})"}

        token = secrets.token_hex(32)
        try:
            _write_token_file(token)
        except OSError as e:
            return {"ok": False, "error": f"token dosyası yazılamadı: {e.__class__.__name__}"}
        proc = subprocess.Popen(
            # `--input`: uzakgoz 0.3.0'dan beri fare/klavye enjeksiyonu varsayılan KAPALI (aksi halde panelde "Kontrolü Al"
            # sessizce çalışmaz); panelin kendi kapısı (Kontrolü Al düğmesi) zaten girdiyi ayrıca açar. Eski ikili fazla
            # argümanı yok sayar (yalnız PORT'u okur).
            # Token YALNIZ ortamda (argv başka kullanıcılara /proc'tan görünür).
            [str(binary), str(port), "--input"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            env={**os.environ, "UZAKGOZ_TOKEN": token},
        )
        _proc, _port, _token = proc, port, token

        deadline = time.monotonic() + PORT_WAIT_SECONDS
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                _proc, _port = None, None
                _clear_token()
                return {"ok": False, "error": f"uzakgoz hemen çöktü (exit={proc.returncode})"}
            if _port_open(port):
                _write_pid_file(proc.pid, port)
                return {"ok": True, "port": port}
            time.sleep(0.1)
        # Zaman aşımı: süreç sızmasın, durum "çalışıyor" kalmasın
        _proc, _port = None, None
        _clear_token()
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
        except OSError:
            pass
        return {"ok": False, "error": "uzakgoz port'u açmadı (timeout)"}


def stop() -> dict:
    global _proc, _port, _adopted_pid
    with _lock:
        _adopt_if_orphaned()
        if _proc is None and _adopted_pid is None:
            return {"ok": True, "already_stopped": True}
        proc, adopted_pid = _proc, _adopted_pid
        _proc, _port, _adopted_pid = None, None, None
    _clear_pid_file()
    _clear_token()
    if proc is not None:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        return {"ok": True}
    # Adopted orphan — hiç Popen handle'ımız yok, PID-exact sinyal (pattern-match YOK, CLAUDE.md).
    _kill_pid(adopted_pid)
    return {"ok": True}


def current_token() -> Optional[str]:
    """Çalışan daemon'un token'ı (yoksa None). Yalnız web.py'nin daemon'a giden istekleri için; istemciye ASLA verilmez."""
    with _lock:
        _adopt_if_orphaned()
        if (_proc is not None and _proc.poll() is None) or _adopted_pid is not None:
            return _token
        return None


def rewrite_path_with_token(path: str, token: str) -> str:
    """İstemcinin `token`/`ticket` sorgu anahtarlarını SİL (panel token'ı daemon'a ulaşmasın), `token=<daemon token>` ekle."""
    from urllib.parse import urlsplit, urlencode, parse_qsl
    sp = urlsplit(path)
    q = [(k, v) for k, v in parse_qsl(sp.query, keep_blank_values=True) if k.lower() not in ("token", "ticket")]
    q.append(("token", token))
    return sp._replace(query=urlencode(q)).geturl()


def current_port() -> Optional[int]:
    with _lock:
        _adopt_if_orphaned()
        if (_proc is not None and _proc.poll() is None) or _adopted_pid is not None:
            return _port
        return None
