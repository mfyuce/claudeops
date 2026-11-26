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
import time
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


def _plan_on(listen: str, internal: str, binp: str, web_unit_text: str, read_err: Optional[str] = None) -> dict:
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
    if read_err is not None:
        blockers.append(f"claudeops-web.service okunamadı: {read_err}")
    elif new is None:
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
    for u in (FRONT_UNIT, DROPIN):
        if os.path.islink(u):           # atomik yazım bağı düz dosyaya çevirirdi: kapalı yön, elle düzenlensin
            blockers.append(f"birim dosyası sembolik bağ: {u} (yazım bağı düz dosyaya çevirir; bağı kaldırın)")
    steps = [f"gizli: {front_mod.secret_path()} (0600, yoksa üret)",
             f"yaz: {FRONT_UNIT} ({binp} --listen {listen} --upstream {internal} --dist {DIST_DIR} "
             f"--state-dir {front_mod.paths.CLAUDEOPS_DIR})",
             f"yaz: {DROPIN} (Python -> {internal})",
             "systemctl --user daemon-reload", "systemctl --user restart claudeops-web.service (Python iç porta geçer, dış port boşalır)",
             "systemctl --user enable --now claudeops-front.service"]
    return {"steps": steps, "blockers": blockers, "reapply": reapply, "new_execstart": new, "la": la, "ia": ia}


_TIMING = {"front_up": 15.0, "port_free": 10.0, "web_up": 30.0, "poll": 0.2}    # sn (Rust `Timing`; testler kısaltır)


class _ScError(Exception):
    """systemctl başlatılamadı (çıkış kodu yok)."""


def _sc(*a: str) -> int:
    """`systemctl --user ...` çıkış kodu (sinyalle biterse 128+sinyal); başlatılamazsa `_ScError`."""
    try:
        rc = subprocess.run(["systemctl", "--user", *a]).returncode
    except OSError as e:
        raise _ScError(f"systemctl başlatılamadı: {e}") from None
    return 128 - rc if rc < 0 else rc


def _show(cmd) -> str:
    return "systemctl --user " + " ".join(cmd)


def _run_sc(cmd) -> Optional[str]:
    """Başarıda None, yoksa neden."""
    try:
        rc = _sc(*cmd)
    except _ScError as e:
        return str(e)
    return None if rc == 0 else f"çıkış {rc}"


def _read_web_unit() -> Tuple[str, Optional[str]]:
    """(metin, okuma hatası): yoksa ("", None); okunamaz ya da UTF-8 değilse hata metni (Rust `read_web_unit`)."""
    try:
        b = WEB_UNIT.read_bytes()
    except FileNotFoundError:
        return "", None
    except OSError as e:
        return "", f"{WEB_UNIT}: {e}"
    try:
        return b.decode("utf-8"), None
    except UnicodeDecodeError:
        return "", f"{WEB_UNIT}: UTF-8 değil"


def _snapshot(p: Path):
    """Yazmadan önceki durum: yoksa None, sembolik bağsa hedefi (str), dosyaysa (içerik, izin bitleri); okunamazsa OSError
    (geri alınamayacak dosyaya yazılmaz)."""
    if os.path.islink(p):
        return os.readlink(p)
    try:
        with open(p, "rb") as fh:
            data = fh.read()
            mode = os.fstat(fh.fileno()).st_mode & 0o7777
    except FileNotFoundError:
        return None
    return data, mode


def _atomic_write(p: Path, data: bytes, mode: Optional[int] = None) -> None:
    """Aynı dizinde O_EXCL geçici dosya, dosya + dizin fsync, rename (yarıda kalırsa yarım birim kalmaz). `mode` None ise
    yeni dosya umask'e göre (eski `write_text` gibi)."""
    d = os.path.dirname(str(p)) or "."
    n = 0
    while True:
        tmp = os.path.join(d, f".cops-py.{os.getpid()}.{n}.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            break
        except FileExistsError:
            if n >= 64:
                raise
            n += 1
    try:
        with os.fdopen(fd, "wb") as fh:
            if mode is not None:
                os.fchmod(fh.fileno(), mode)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.rename(tmp, p)
        dfd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _restore(p: Path, prev) -> None:
    if prev is None:
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass
    elif isinstance(prev, str):         # yalnız `off` bir bağı siler (`on` bağlı birimi reddeder)
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass
        os.symlink(prev, p)
    else:
        _atomic_write(p, prev[0], prev[1])


class _Undo:
    """Geri alma günlüğü (Rust `Undo`; metinler aynı)."""

    def __init__(self):
        self.lines: List[str] = []
        self.failed = False

    def file(self, p: Path, prev) -> None:
        if prev is None:
            what = f"sil: {p} (önceden yoktu)"
        else:
            what = f"geri yaz: {p} (önceki {'sembolik bağ' if isinstance(prev, str) else 'içerik'})"
        try:
            _restore(p, prev)
            self.lines.append(f"  {what}: tamam")
        except OSError as e:
            self.failed = True
            self.lines.append(f"  {what}: HATA ({e})")

    def sc(self, *cmd: str) -> None:
        try:
            rc = _sc(*cmd)
        except _ScError as e:
            self.failed = True
            self.lines.append(f"  {_show(cmd)}: HATA ({e})")
            return
        if rc == 0:
            self.lines.append(f"  {_show(cmd)}: tamam")
        else:
            self.failed = True
            self.lines.append(f"  {_show(cmd)}: HATA (çıkış {rc})")

    def front_stop(self, prev) -> None:
        """Önceden çalışmayan ön kapıyı durdurur; etkinlik önceki gibi kalır."""
        if prev["enabled"]:
            self.sc("stop", FRONT_UNIT_NAME)
        else:
            self.sc("disable", "--now", FRONT_UNIT_NAME)

    def front_back(self, prev) -> None:
        """Durdurulmuş ön kapının önceki etkin/çalışır durumunu geri kurar."""
        en, ac = prev["enabled"], prev["active"]
        if en and ac:
            self.sc("enable", "--now", FRONT_UNIT_NAME)
        elif ac:
            self.sc("start", FRONT_UNIT_NAME)
        elif en:
            self.sc("enable", FRONT_UNIT_NAME)

    def report(self) -> None:
        print("GERİ ALMA:")
        for x in self.lines:
            print(x)
        if self.failed:
            print("GERİ ALMA BAŞARISIZ: yukarıda HATA yazan adımları elle tamamlayın (`py/cops front status` ile denetleyin)")
        else:
            print("geri alındı: birim dosyaları ve servisler önceki durumda")


def _wait_for(limit: float, cond) -> bool:
    start = time.monotonic()
    while True:
        if cond():
            return True
        if time.monotonic() - start >= limit:
            return False
        time.sleep(_TIMING["poll"])


def _front_state():
    """Ön kapının değişiklikten önceki durumu (`is-active/is-enabled --quiet`, 0 = evet). Port sahibine bakılmaz (`--listen`
    değişebilir). Okunamazsa `_ScError`: durum bilinmeden hiçbir şey değiştirilmez."""
    return {"active": _sc("is-active", "--quiet", FRONT_UNIT_NAME) == 0,
            "enabled": _sc("is-enabled", "--quiet", FRONT_UNIT_NAME) == 0}


def _front_listen(fallback: str) -> str:
    """Ön kapı biriminin `--listen` değeri (varsa), yoksa `fallback`."""
    try:
        text = FRONT_UNIT.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return fallback
    es = web_execstart(text)
    if es is None:
        return fallback
    toks = es.split()
    if "--listen" in toks:
        i = toks.index("--listen")
        if i + 1 < len(toks):
            return toks[i + 1]
    return fallback


def _web_addr(web_unit_text: str):
    """`off` sonrası web'in döneceği adres: web biriminin ExecStart'ındaki `--host`/`--port` (ya da `=`li), yoksa web
    varsayılanı 127.0.0.1:8765; joker ya da ad olan host loopback'ten yoklanır. Biçim tanınmazsa None."""
    es = web_execstart(web_unit_text)
    if es is None:
        return None
    if es.endswith("'"):
        es = es[:-1]
    toks = es.split()
    host, port = "127.0.0.1", "8765"
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in ("--host", "--port"):
            if i + 1 < len(toks):
                if t == "--host":
                    host = toks[i + 1]
                else:
                    port = toks[i + 1]
                i += 1
        elif t.startswith("--host="):
            host = t[len("--host="):]
        elif t.startswith("--port="):
            port = t[len("--port="):]
        i += 1
    try:
        ip = ipaddress.IPv4Address(host) if all(c in "0123456789." for c in host) else None
    except ValueError:
        ip = None
    if ip is None or ip.is_unspecified:
        ip = ipaddress.IPv4Address("127.0.0.1")
    try:
        return _parse_listen(f"{ip}:{port}")
    except ValueError:
        return None


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
        return _on(args)
    return _off(args)


def _on(args) -> int:
    """`on`: yarıda kalırsa (yazım, systemctl, ön kapının dinlememesi, web'in iç adrese geçmemesi) önceki dosya ve birim
    durumuna dönülür; her dönüş adımı yazılır (Rust `front::on`)."""
    text, read_err = _read_web_unit()
    plan = _plan_on(args.listen, args.internal, args.bin, text, read_err)
    print("PLAN:\n  " + "\n  ".join(plan["steps"]))
    if plan["blockers"]:
        print("ENGEL:\n  " + "\n  ".join(plan["blockers"]))
        return 1
    if not args.apply:
        print("(plan; uygulamak için --apply)")
        return 0
    new_es, la, ia = plan["new_execstart"], plan["la"], plan["ia"]
    if new_es is None or la is None or ia is None:
        print("HATA: plan eksik (iç hata)")
        return 1
    try:
        prev = _front_state()
    except _ScError as e:
        print(f"HATA: {FRONT_UNIT_NAME} durumu okunamadı: {e} (hiçbir şey değişmedi)")
        return 1
    try:
        front_mod.ensure_secret()
    except OSError as e:
        print(f"HATA: gizli üretilemedi: {front_mod.secret_path()}: {e}")
        return 1
    snaps = []
    for p in (FRONT_UNIT, DROPIN):
        try:
            snaps.append(_snapshot(p))
        except OSError as e:
            print(f"HATA: okunamadı: {p}: {e} (hiçbir şey değişmedi)")
            return 1
    prev_front, prev_drop = snaps
    writes = ((FRONT_UNIT, _unit_text(args.bin, args.listen, args.internal)), (DROPIN, dropin_text(new_es)))
    for i, (p, body) in enumerate(writes):
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(p, body.encode())
        except OSError as e:
            print(f"HATA: yazılamadı: {p}: {e}")
            u = _Undo()
            if i == 1:
                u.file(FRONT_UNIT, prev_front)
            u.file(DROPIN, prev_drop)
            u.report()
            return 1
    if plan["reapply"]:         # zaten açık: Python'a dokunma, yalnız front birimini yenile
        cmds = [("daemon-reload",), ("enable", "--now", FRONT_UNIT_NAME), ("restart", FRONT_UNIT_NAME)]
    else:
        cmds = [("daemon-reload",), ("restart", WEB_UNIT_NAME), ("enable", "--now", FRONT_UNIT_NAME)]
        if prev["active"]:      # `enable --now` çalışan birimi yeniden başlatmaz: yeni birim metni ancak restart ile uygulanır
            cmds.append(("restart", FRONT_UNIT_NAME))
    ran, failure = 0, None
    for cmd in cmds:
        ran += 1
        failure = _run_sc(cmd)
        if failure is not None:
            print(f"HATA: {_show(cmd)}")
            print(f"  neden: {failure}")
            break
    if failure is None:
        web_needed = not plan["reapply"]
        lk, ik = _fmt(la), _fmt(ia)

        def ok():
            return _is_unit(_port_owner(lk), FRONT_UNIT_NAME) and (not web_needed or _is_unit(_port_owner(ik), WEB_UNIT_NAME))
        # web yeniden başlatıldıysa açılışı ön kapınınkinden uzun sürer: `off` ile aynı pay
        limit = max(_TIMING["front_up"], _TIMING["web_up"]) if web_needed else _TIMING["front_up"]
        if not _wait_for(limit, ok):
            secs = int(limit)
            if not _is_unit(_port_owner(lk), FRONT_UNIT_NAME):
                print(f"HATA: ön kapı {args.listen} üzerinde dinlemiyor ({secs} sn içinde {FRONT_UNIT_NAME} görülmedi: "
                      f"{_describe(_port_owner(lk))})")
            else:
                print(f"HATA: web iç adreste {args.internal} doğrulanamadı ({secs} sn içinde {WEB_UNIT_NAME} görülmedi: "
                      f"{_describe(_port_owner(ik))})")
            failure = "doğrulama"
    if failure is None:
        print(f"açıldı: dış {args.listen} -> iç {args.internal}")
        return 0
    # Geri alma: önceden çalışmayan ön kapıyı durdur, dosyaları geri koy, yeniden yükle, web'i eski portuna, önceden çalışan
    # ön kapıyı eski birimiyle yeniden başlat; etkinlik durumu önceki gibi.
    done = cmds[:ran]
    front_touched = any(c[-1] == FRONT_UNIT_NAME for c in done)
    web_restarted = ("restart", WEB_UNIT_NAME) in done
    u = _Undo()
    if front_touched and not prev["active"]:
        u.front_stop(prev)
    u.file(FRONT_UNIT, prev_front)
    u.file(DROPIN, prev_drop)
    u.sc("daemon-reload")
    if web_restarted:
        u.sc("restart", WEB_UNIT_NAME)
    if front_touched and prev["active"]:
        u.sc("restart", FRONT_UNIT_NAME)
        if not prev["enabled"]:
            u.sc("disable", FRONT_UNIT_NAME)
    u.report()
    return 1


def _off(args) -> int:
    """`off`: ön kapı durur ve dış portu bırakır, drop-in silinir, web kendi adresine döner ve orada doğrulanır; yarıda
    kalırsa önceki duruma dönülür (Rust `front::off`). Ön kapı birimi yoksa durdurma hatası yok sayılır (eski davranış)."""
    steps = [f"systemctl --user disable --now {FRONT_UNIT_NAME}", f"sil: {DROPIN}", "systemctl --user daemon-reload",
             f"systemctl --user restart {WEB_UNIT_NAME} (Python dış porta döner)"]
    print("PLAN:\n  " + "\n  ".join(steps))
    if not args.apply:
        print("(plan; uygulamak için --apply)")
        return 0
    text, read_err = _read_web_unit()
    wa = _web_addr(text) if read_err is None else None
    if wa is None:
        try:
            wa = _parse_listen(_front_listen(args.listen))
        except ValueError as e:
            print(f"HATA: geçersiz dış adres: {e} (hiçbir şey değişmedi)")
            return 1
    wk = _fmt(wa)
    try:
        prev = _front_state()
    except _ScError as e:
        print(f"HATA: {FRONT_UNIT_NAME} durumu okunamadı: {e} (hiçbir şey değişmedi)")
        return 1
    try:
        prev_drop = _snapshot(DROPIN)
    except OSError as e:
        print(f"HATA: okunamadı: {DROPIN}: {e} (hiçbir şey değişmedi)")
        return 1
    unit_exists = FRONT_UNIT.exists()
    disable = ("disable", "--now", FRONT_UNIT_NAME)
    err = _run_sc(disable)
    if err is not None:
        if unit_exists:
            print(f"HATA: {_show(disable)}\n  neden: {err}")
            u = _Undo()
            u.front_back(prev)
            u.report()
            return 1
        print(f"(not: {FRONT_UNIT_NAME} birimi yok; durdurma hatası yok sayıldı)")

    def freed():
        o = _port_owner(wk)
        return not _is_unit(o, FRONT_UNIT_NAME) and (_is_unit(o, WEB_UNIT_NAME) or not port_busy(wk))
    if not _wait_for(_TIMING["port_free"], freed):
        print(f"HATA: dış port {wk} boşalmadı ({_describe(_port_owner(wk))}); web oraya dönemez")
        u = _Undo()
        u.front_back(prev)
        u.report()
        return 1

    def full_undo(web: bool) -> None:
        u = _Undo()
        u.file(DROPIN, prev_drop)
        u.sc("daemon-reload")
        if web:
            u.sc("restart", WEB_UNIT_NAME)
        u.front_back(prev)
        u.report()
    try:
        _restore(DROPIN, None)
    except OSError as e:
        print(f"HATA: silinemedi: {DROPIN}: {e}")
        full_undo(False)
        return 1
    err = _run_sc(("daemon-reload",))
    if err is not None:
        print(f"HATA: systemctl --user daemon-reload\n  neden: {err}")
        full_undo(False)
        return 1
    try:
        rc = _sc("restart", WEB_UNIT_NAME)
    except _ScError as e:
        print(f"  neden: {e}")
        rc = 127
    if rc != 0:
        print("HATA: web restart")
        full_undo(True)
        return rc
    if not _wait_for(_TIMING["web_up"], lambda: _is_unit(_port_owner(wk), WEB_UNIT_NAME)):
        print(f"HATA: web {wk} üzerinde doğrulanamadı ({int(_TIMING['web_up'])} sn: {_describe(_port_owner(wk))})")
        full_undo(True)
        return 1
    print("kapandı")
    return 0
