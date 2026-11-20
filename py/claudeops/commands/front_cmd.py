"""`front` — Rust ön kapı (copsd) aç/kapat (docs/rust-strangler-plan.md bölüm 3, -prv).

  py/cops front status                 # gizli, ikili, birimler, portlar
  py/cops front on  [--apply] [--listen 127.0.0.1:8765] [--internal 127.0.0.1:28765] [--bin YOL]
  py/cops front off [--apply]

Varsayılan PLAN yazdırır, hiçbir şey değiştirmez; `--apply` gerçekten uygular. `on`: gizli (0600) üretir, `claudeops-front.service`
kullanıcı birimini yazar, `claudeops-web.service.d/front.conf` drop-in'i ile Python'u iç porta alır, `daemon-reload`, web restart,
front start (Python restart'ı bugünkü normal restart kadar keser; oturumlar KillMode=process ile yaşar). `off`: tersi. Sudo gerekmez.
İç port varsayılanı 28765 (18765/18766 menzil'de kullanımda).
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from .. import front as front_mod
from ..paths import CLAUDEOPS_DIR, HOME

UNIT_DIR = Path(HOME) / ".config" / "systemd" / "user"
FRONT_UNIT = UNIT_DIR / "claudeops-front.service"
WEB_UNIT = UNIT_DIR / "claudeops-web.service"
DROPIN = UNIT_DIR / "claudeops-web.service.d" / "front.conf"
DEFAULT_BIN = Path(CLAUDEOPS_DIR) / "bin" / "copsd"
DEFAULT_LISTEN = "127.0.0.1:8765"
DEFAULT_INTERNAL = "127.0.0.1:28765"

FRONT_UNIT_TEMPLATE = """[Unit]
Description=claudeops front (copsd, Rust vekil)
# Python birimine bağımlı DEĞİL: Python düşükken ön kapı ayakta kalır (vekil uçlar 502 verir).

[Service]
ExecStart={bin} --listen {listen} --upstream {internal}
Restart=always
RestartSec=2
UMask=0077

[Install]
WantedBy=default.target
"""


def register(sub):
    p = sub.add_parser("front", help="Rust ön kapı: front status | on [--apply] | off [--apply]")
    p.add_argument("action", choices=["status", "on", "off"])
    p.add_argument("--apply", action="store_true")
    p.add_argument("--listen", default=DEFAULT_LISTEN)
    p.add_argument("--internal", default=DEFAULT_INTERNAL)
    p.add_argument("--bin", default=str(DEFAULT_BIN))
    p.set_defaults(func=run)


def web_execstart(unit_text: str) -> Optional[str]:
    m = re.search(r"^ExecStart=(.*)$", unit_text, re.M)
    return m.group(1).strip() if m else None


def with_internal_port(execstart: str, internal: str) -> Optional[str]:
    """`... claudeops web'` -> `... claudeops web --host H --port P'` (bash -c tırnağı içine); tanınmayan biçim None."""
    host, _, port = internal.rpartition(":")
    flags = f" --host {host} --port {port}"
    if execstart.endswith("web'"):
        return execstart[:-1] + flags + "'"
    if execstart.endswith(" web"):
        return execstart + flags
    return None


def dropin_text(execstart: str) -> str:
    return f"[Service]\nExecStart=\nExecStart={execstart}\n"


def port_busy(hostport: str) -> bool:
    host, _, port = hostport.rpartition(":")
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, int(port))) == 0


def plan_on(listen: str, internal: str, binp: str, web_unit_text: str) -> Tuple[List[str], List[str]]:
    """(adımlar, engeller)."""
    blockers: List[str] = []
    if not os.path.exists(binp):
        blockers.append(f"ikili yok: {binp} (rust/ altında `cargo build --release`, sonra kopyala)")
    es = web_execstart(web_unit_text)
    new = with_internal_port(es, internal) if es else None
    if new is None:
        blockers.append("claudeops-web.service ExecStart biçimi tanınmadı (…claudeops web); elle drop-in gerekir")
    if port_busy(internal):
        blockers.append(f"iç port dolu: {internal}")
    steps = [f"gizli: {front_mod.secret_path()} (0600, yoksa üret)",
             f"yaz: {FRONT_UNIT} ({binp} --listen {listen} --upstream {internal})",
             f"yaz: {DROPIN} (Python -> {internal})",
             "systemctl --user daemon-reload", "systemctl --user restart claudeops-web.service (Python iç porta geçer, dış port boşalır)",
             "systemctl --user enable --now claudeops-front.service"]
    return steps, blockers


def _sc(*a: str) -> int:
    return subprocess.run(["systemctl", "--user", *a]).returncode


def run(args) -> int:
    if args.action == "status":
        sec = front_mod.read_secret()
        print(f"gizli: {'var' if sec else 'YOK'} ({front_mod.secret_path()})")
        print(f"ikili: {'var' if os.path.exists(args.bin) else 'YOK'} ({args.bin})")
        print(f"front birimi: {'yazılı' if FRONT_UNIT.exists() else 'yok'}; drop-in: {'yazılı' if DROPIN.exists() else 'yok'}")
        for hp in (args.listen, args.internal):
            print(f"port {hp}: {'dolu' if port_busy(hp) else 'boş'}")
        return 0
    if args.action == "on":
        text = WEB_UNIT.read_text() if WEB_UNIT.exists() else ""
        steps, blockers = plan_on(args.listen, args.internal, args.bin, text)
        print("PLAN:\n  " + "\n  ".join(steps))
        if blockers:
            print("ENGEL:\n  " + "\n  ".join(blockers))
            return 1
        if not args.apply:
            print("(plan; uygulamak için --apply)")
            return 0
        front_mod.ensure_secret()
        FRONT_UNIT.write_text(FRONT_UNIT_TEMPLATE.format(bin=args.bin, listen=args.listen, internal=args.internal))
        DROPIN.parent.mkdir(parents=True, exist_ok=True)
        DROPIN.write_text(dropin_text(with_internal_port(web_execstart(text) or "", args.internal) or ""))
        for cmd in (("daemon-reload",), ("restart", "claudeops-web.service"), ("enable", "--now", "claudeops-front.service")):
            if _sc(*cmd) != 0:
                print(f"HATA: systemctl --user {' '.join(cmd)}")
                return 1
        print("açıldı: dış", args.listen, "-> iç", args.internal)
        return 0
    # off
    steps = ["systemctl --user disable --now claudeops-front.service", f"sil: {DROPIN}", "systemctl --user daemon-reload",
             "systemctl --user restart claudeops-web.service (Python dış porta döner)"]
    print("PLAN:\n  " + "\n  ".join(steps))
    if not args.apply:
        print("(plan; uygulamak için --apply)")
        return 0
    _sc("disable", "--now", "claudeops-front.service")
    try:
        DROPIN.unlink()
    except FileNotFoundError:
        pass
    _sc("daemon-reload")
    rc = _sc("restart", "claudeops-web.service")
    print("kapandı" if rc == 0 else "HATA: web restart")
    return rc
