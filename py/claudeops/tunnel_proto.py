"""Tünel protokolü ayarı (`tunnel_protocol`: "" | auto | http2 | quic) -> systemd drop-in + yalnız tünel servisinin yeniden başlaması.

Neden: eduroam gibi ağlar UDP/QUIC'i engelliyor (cloudflared "failed to dial to edge with quic", 530). Eskiden elle
`~/.config/systemd/user/claudeops-tunnel.service.d/protocol.conf` yazılıyordu; ayar artık o dosyayı yazar. `run-tunnel.sh`
`CLAUDEOPS_TUNNEL_PROTOCOL` ortamını okur (boş = bayrak yok = cloudflared auto), betik değişmez.
"" = yönetme (drop-in'e dokunma); auto = ortamı BOŞ yaz (başka bir elle drop-in'i de ezer); http2/quic = o değer.
Yeniden başlatma yalnız drop-in İÇERİĞİ değişince ve yalnız tünel servisi için; web paneli/oturumlar etkilenmez, tünel URL'si döner
(ntfy). Restart gecikmeli ve arka planda: ayarı tünel üzerinden kaydeden istemcinin yanıtı kesilmesin."""
from __future__ import annotations

import os
import subprocess
import threading
from typing import Callable, Optional

VALID = ("", "auto", "http2", "quic")
UNIT = "claudeops-tunnel.service"
RESTART_DELAY = 2.0


def dropin_path(home: Optional[str] = None) -> str:
    h = home or os.path.expanduser("~")
    return os.path.join(h, ".config", "systemd", "user", UNIT + ".d", "protocol.conf")


def normalize(value: object) -> str:
    v = str(value or "").strip().lower()
    return v if v in VALID else ""


def desired_content(value: str) -> Optional[str]:
    """None = yönetme. Aksi halde drop-in metni (auto -> boş ortam)."""
    v = normalize(value)
    if not v:
        return None
    env = "" if v == "auto" else v
    return f"[Service]\nEnvironment=CLAUDEOPS_TUNNEL_PROTOCOL={env}\n"


def _run(*args: str) -> int:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=30).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def apply(value: object, home: Optional[str] = None, restart: Optional[Callable[[], None]] = None) -> dict:
    """Drop-in'i yazar; içerik değiştiyse tüneli (gecikmeli, arka planda) yeniden başlatır. {"changed", "restart"}."""
    content = desired_content(normalize(value))
    if content is None:
        return {"changed": False, "restart": False}
    path = dropin_path(home)
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == content:
                return {"changed": False, "restart": False}
    except OSError:
        pass
    from .atomic_json import atomic_write_text
    atomic_write_text(path, content, mode=0o644)

    def go() -> None:
        _run("daemon-reload")
        _run("restart", UNIT)

    threading.Timer(RESTART_DELAY, restart or go).start()
    return {"changed": True, "restart": True}
