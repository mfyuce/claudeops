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

import ipaddress
import os
import re
import shutil
import socket
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple

from .. import front as front_mod
from .web_static import DIST_DIR
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
ExecStart={bin} --listen {listen} --upstream {internal} --dist {dist} --state-dir {state}
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


def _sd_quote(v: str) -> str:
    """systemd tırnağı: `\\`, `"`, `%`, `$` kaçışlı, çift tırnak içinde."""
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def _sd_quote_if_needed(v: str) -> str:
    """`bin`/`dist`: boşluk ya da systemd için anlamlı karakter varsa tırnaklı (boşluklu yol ExecStart'ı bölmesin)."""
    return _sd_quote(v) if any(c.isspace() or c in "\"'\\%$" for c in v) else v


def _unit_text(binp: str, listen: str, internal: str) -> str:
    """Birim metni. copsd'nin durum dizini Python'un gizliyi yazdığı dizinle (`front.secret_path`) aynı olsun; systemd tırnağı."""
    state = _sd_quote(os.path.abspath(front_mod.paths.CLAUDEOPS_DIR))
    return FRONT_UNIT_TEMPLATE.format(bin=_sd_quote_if_needed(binp), listen=listen, internal=internal,
                                      dist=_sd_quote_if_needed(str(DIST_DIR)), state=state)


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


def _rdbg(s: str) -> str:
    """Rust `{:?}` (str) biçimi: hata metinleri Rust `cops-cli` ile aynı olsun."""
    out = []
    for i, c in enumerate(s):
        esc = {"\0": "\\0", "\t": "\\t", "\r": "\\r", "\n": "\\n", "\\": "\\\\", '"': '\\"'}.get(c)
        cat = unicodedata.category(c)
        if esc:
            out.append(esc)
        elif cat in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp") or (cat == "Zs" and c != " ") or (i == 0 and cat in ("Mn", "Me")):
            out.append("\\u{%x}" % ord(c))
        else:
            out.append(c)
    return '"' + "".join(out) + '"'


def _parse_port(p: str) -> int:
    if not p or len(p.encode()) > 5 or not all("0" <= c <= "9" for c in p):
        raise ValueError(f"port sayı değil: {_rdbg(p)}")
    n = int(p)
    if not 1 <= n <= 65535:
        raise ValueError(f"port aralık dışı (1-65535): {p}")
    return n


def _parse_listen(s: str):
    """`IPv4:port` ya da `[IPv6]:port` -> (ipaddress, port); geçersizse ValueError (Rust `net::parse_listen` ile aynı kural ve
    metin). Ad (`localhost`) kabul edilmez: copsd `SocketAddr` ister. Port yalnız ASCII rakam, 1-65535."""
    host, sep, port = s.rpartition(":")
    if not sep:
        raise ValueError(f"{_rdbg(s)}: IP:port biçiminde değil (iki nokta yok)")
    try:
        n = _parse_port(port)
    except ValueError as e:
        raise ValueError(f"{_rdbg(s)}: {e}") from None
    if host.startswith("[") and host.endswith("]") and len(host) >= 2:
        inner = host[1:-1]
        try:
            if "%" in inner:
                raise ValueError(inner)
            return ipaddress.IPv6Address(inner), n
        except ValueError:
            raise ValueError(f"{_rdbg(s)}: geçersiz IPv6 adresi") from None
    try:
        if not all(c in "0123456789." for c in host):
            raise ValueError(host)
        return ipaddress.IPv4Address(host), n
    except ValueError:
        raise ValueError(f"{_rdbg(s)}: adres IPv4 ya da [IPv6] olmalı (ad kabul edilmez, copsd SocketAddr ister)") from None


def _parse_internal(s: str):
    """Yalnız `IPv4:port` (Python web `ThreadingHTTPServer` AF_INET ile dinler)."""
    a = _parse_listen(s)
    if a[0].version == 6:
        raise ValueError(f"{_rdbg(s)}: iç adres IPv6 olamaz (Python web yalnız IPv4 dinler: ThreadingHTTPServer AF_INET)")
    return a


def _fmt(a) -> str:
    """Rust `SocketAddr` gösterimi."""
    ip, port = a
    return f"[{ip}]:{port}" if ip.version == 6 else f"{ip}:{port}"


def port_busy(hostport: str) -> bool:
    ip, port = _parse_listen(hostport)
    with socket.socket(socket.AF_INET6 if ip.version == 6 else socket.AF_INET) as s:
        s.settimeout(0.5)
        return s.connect_ex((str(ip), port)) == 0


FRONT_UNIT_NAME = "claudeops-front.service"
WEB_UNIT_NAME = "claudeops-web.service"
_PROC = "/proc"


def _hex_addr(s: str):
    """`/proc/net/tcp` adres alanı (`0100007F:1F90`): çekirdek her 32 bitlik sözcüğü konak bayt sırasıyla yazar."""
    ip, sep, port = s.partition(":")
    try:
        if not sep:
            return None
        pn = int(port, 16)
        if not 0 <= pn <= 65535:
            return None
        if len(ip) == 8:
            return ipaddress.IPv4Address(int(ip, 16).to_bytes(4, sys.byteorder)), pn
        if len(ip) == 32:
            return ipaddress.IPv6Address(b"".join(int(ip[i:i + 8], 16).to_bytes(4, sys.byteorder) for i in range(0, 32, 8))), pn
    except ValueError:
        return None
    return None


def _canon(ip):
    return ip.ipv4_mapped if ip.version == 6 and ip.ipv4_mapped else ip


def _accepts(local, a) -> bool:
    """`a`'ya gelen bağlantıyı `local` dinleyicisi kabul eder mi (joker ya da kesin IP; IPv4 eşlemeli IPv6 dahil)."""
    a = _canon(a)
    return local.is_unspecified or local == a or _canon(local) == a


def _unit_of(proc: str, pid: int) -> Optional[str]:
    """`/proc/<pid>/cgroup` birim adı: birleşik ağaç `0::<yol>`, yoksa v1 `name=systemd` satırı (denetleyici satırları
    kullanıcı yöneticisini gösterir, bakılmaz); yolun son parçası `.service`/`.scope` ise."""
    try:
        with open(os.path.join(proc, str(pid), "cgroup"), encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeError):
        return None
    lines = [x[:-1] if x.endswith("\r") else x for x in text.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()

    def _path_of(want):
        for line in lines:
            parts = line.split(":", 2)
            if len(parts) == 3 and want(parts[0], parts[1]):
                return parts[2]
        return None
    path = _path_of(lambda i, c: i == "0" and c == "")
    if path == "/":
        path = None
    if path is None:
        path = _path_of(lambda i, c: c == "name=systemd")
    if path is None:
        return None
    last = path.rsplit("/", 1)[-1]
    return last if last.endswith(".service") or last.endswith(".scope") else None


def _port_owner(hostport: str):
    """Portu dinleyen: ("none",) | ("other_user", uid) | ("unknown",) | ("holders", [(pid, birim|None)]) (Rust
    `net::port_owner`). Soket `/proc/net/tcp{,6}` LISTEN satırından, tutan süreçler yalnız kendi uid'imizin
    `/proc/<pid>/fd` bağlantılarından, birim cgroup'tan. Bulunamayan/başkasının/okunamayan dinleyici "bizim değil"."""
    ip, port = _parse_listen(hostport)
    uid = os.getuid()
    socks = []
    for name in ("net/tcp", "net/tcp6"):
        try:
            with open(os.path.join(_PROC, name), encoding="utf-8", errors="replace") as fh:
                rows = fh.read().splitlines()[1:]
        except OSError:
            continue
        for line in rows:
            c = line.split()
            if len(c) < 10 or c[3] != "0A":
                continue
            la = _hex_addr(c[1])
            if la is None or la[1] != port or not _accepts(la[0], ip):
                continue
            if c[7].isascii() and c[7].isdigit() and c[9].isascii() and c[9].isdigit():
                socks.append((int(c[9]), int(c[7])))
    if not socks:
        return ("none",)
    for _, u in socks:
        if u != uid:
            return ("other_user", u)
    want = {f"socket:[{i}]" for i, _ in socks}
    holders = []
    try:
        entries = os.listdir(_PROC)
    except OSError:
        return ("unknown",)
    for e in entries:
        if not (e.isascii() and e.isdigit()):
            continue
        d = os.path.join(_PROC, e)
        try:
            if os.lstat(d).st_uid != uid:
                continue
            fds = os.listdir(os.path.join(d, "fd"))
        except OSError:
            continue
        held = False
        for fd in fds:
            try:
                if os.readlink(os.path.join(d, "fd", fd)) in want:
                    held = True
                    break
            except OSError:
                continue
        if held:
            holders.append((int(e), _unit_of(_PROC, int(e))))
    if not holders:
        return ("unknown",)
    holders.sort(key=lambda h: (h[0], h[1] is not None, h[1] or ""))
    return ("holders", holders)


def _is_unit(o, unit: str) -> bool:
    """Soketi tutan HER süreç `unit` biriminde mi."""
    return o[0] == "holders" and bool(o[1]) and all(u == unit for _, u in o[1])


def _describe(o) -> str:
    if o[0] == "none":
        return "dinleyen soket bulunamadı"
    if o[0] == "other_user":
        return f"başka kullanıcının soketi (uid {o[1]})"
    if o[0] == "unknown":
        return "soketi tutan süreç bulunamadı"
    return ", ".join(f"pid {p} ({u or 'birimsiz'})" for p, u in o[1])


def plan_on(listen: str, internal: str, binp: str, web_unit_text: str) -> Tuple[List[str], List[str]]:
    """(adımlar, engeller)."""
    p = _plan_on(listen, internal, binp, web_unit_text)
    return p["steps"], p["blockers"]


def _plan_on(listen: str, internal: str, binp: str, web_unit_text: str) -> dict:
    """Plan kararı (Rust `plan_on` ile aynı engel sırası ve metni): steps, blockers, reapply (drop-in var ve iç portu
    bizim web birimimiz tutuyor), new_execstart, la, ia. Geçersiz/çakışan adres ENGEL; drop-in varken iç portu başka bir
    süreç tutuyorsa ENGEL (eskiden "yeniden uygulama" sayılıp ön kapı yabancı porta vekil oluyordu)."""
    blockers: List[str] = []
    if not os.path.exists(binp):
        blockers.append(f"ikili yok: {binp} (rust/ altında `cargo build --release`, sonra kopyala)")
    elif not (os.path.isfile(binp) and os.stat(binp).st_mode & 0o111):
        blockers.append(f"ikili çalıştırılabilir dosya değil: {binp}")
    if not binp.startswith("/"):        # systemd ExecStart= göreli yolu reddeder; py/cops `cd py/` da yolu kaydırır
        blockers.append(f"ikili yolu mutlak değil: {binp} (systemd ExecStart mutlak yol ister)")
    es = web_execstart(web_unit_text)
    new = with_internal_port(es, internal) if es else None
    if new is None:
        blockers.append("claudeops-web.service ExecStart biçimi tanınmadı (…claudeops web); elle drop-in gerekir")
    for what, v in (("ikili", binp), ("dist", str(DIST_DIR)), ("durum dizini", front_mod.paths.CLAUDEOPS_DIR)):
        if any(unicodedata.category(c) == "Cc" for c in v):
            blockers.append(f"{what} yolu denetim karakteri içeriyor (birim dosyasını bozar): {_rdbg(v)}")
    la = ia = None
    try:
        la = _parse_listen(listen)
    except ValueError as e:
        blockers.append(f"geçersiz --listen: {e}")
    try:
        ia = _parse_internal(internal)
    except ValueError as e:
        blockers.append(f"geçersiz --internal: {e}")
    if la and ia and la[1] == ia[1] and (la[0] == ia[0] or la[0].is_unspecified):
        blockers.append(f"dış ve iç adres çakışıyor: {listen} / {internal}")
    reapply = False
    if ia and port_busy(_fmt(ia)):
        if not DROPIN.exists():
            blockers.append(f"iç port dolu: {internal}")
        else:
            o = _port_owner(_fmt(ia))
            if _is_unit(o, WEB_UNIT_NAME):
                reapply = True          # zaten açık: Python'a dokunma, yalnız front birimini yenile
            else:
                blockers.append(f"iç port başka bir süreçte: {internal} ({_describe(o)}); drop-in var ama dinleyen "
                                f"{WEB_UNIT_NAME} değil")
    steps = [f"gizli: {front_mod.secret_path()} (0600, yoksa üret)",
             f"yaz: {FRONT_UNIT} ({binp} --listen {listen} --upstream {internal} --dist {DIST_DIR} "
             f"--state-dir {front_mod.paths.CLAUDEOPS_DIR})",
             f"yaz: {DROPIN} (Python -> {internal})",
             "systemctl --user daemon-reload", "systemctl --user restart claudeops-web.service (Python iç porta geçer, dış port boşalır)",
             "systemctl --user enable --now claudeops-front.service"]
    return {"steps": steps, "blockers": blockers, "reapply": reapply, "new_execstart": new, "la": la, "ia": ia}


def _sc(*a: str) -> int:
    return subprocess.run(["systemctl", "--user", *a]).returncode


def run(args) -> int:
    if args.action == "status":
        sec = front_mod.read_secret()
        print(f"gizli: {'var' if sec else 'YOK'} ({front_mod.secret_path()})")
        print(f"ikili: {'var' if os.path.exists(args.bin) else 'YOK'} ({args.bin})")
        print(f"front birimi: {'yazılı' if FRONT_UNIT.exists() else 'yok'}; drop-in: {'yazılı' if DROPIN.exists() else 'yok'}")
        rc = 0
        for hp in (args.listen, args.internal):
            try:
                a = _parse_listen(hp)
            except ValueError as e:
                print(f"port {hp}: geçersiz adres ({e})")
                rc = 1
                continue
            print(f"port {hp}: {'dolu' if port_busy(_fmt(a)) else 'boş'}")
        return rc
    if args.action == "on":
        text = WEB_UNIT.read_text() if WEB_UNIT.exists() else ""
        plan = _plan_on(args.listen, args.internal, args.bin, text)
        steps, blockers = plan["steps"], plan["blockers"]
        print("PLAN:\n  " + "\n  ".join(steps))
        if blockers:
            print("ENGEL:\n  " + "\n  ".join(blockers))
            return 1
        if not args.apply:
            print("(plan; uygulamak için --apply)")
            return 0
        reapply = plan["reapply"]
        front_mod.ensure_secret()
        FRONT_UNIT.write_text(_unit_text(args.bin, args.listen, args.internal))
        DROPIN.parent.mkdir(parents=True, exist_ok=True)
        DROPIN.write_text(dropin_text(with_internal_port(web_execstart(text) or "", args.internal) or ""))
        cmds = (("daemon-reload",), ("enable", "--now", "claudeops-front.service"), ("restart", "claudeops-front.service")) if reapply else \
               (("daemon-reload",), ("restart", "claudeops-web.service"), ("enable", "--now", "claudeops-front.service"))
        for cmd in cmds:
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
