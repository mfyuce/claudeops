"""Sahipsiz kaynak denetimi (sahip 20 Kas: "böyle anomalileri kaçırma"; copilot usage tmux artıkları 1 gün fark edilmedi).

Tanılama'nın orphans'ı yalnız >=%50 CPU yakanı sayar, Dalgıç transkript tabanlıdır: %0 CPU'luk sızıntıyı kimse görmüyordu. Bu modül iki şeye bakar:
  (a) `/tmp/tmux-<uid>/` altında claudeops'un açtığı yardımcı soketler (`cops-usage-*`, `cops_e2e_*`, `ctxprobe*`, `cxtest`, `copusage`,
      `cops-cpusage-probe`): canlı sunucu yoksa soket dosyası silinir; sunucu canlı ama sahibi (addaki pid) ölü ve yaşı > 1 sa ise RAPOR
      edilir; yalnız KENDİ usage soketlerimiz (`cops-usage-*`) için kill-server serbest.
  (b) roster/keşifte tanınmayan (find_sessions'ta olmayan), cops tmux soketinde de olmayan, yaşı > 1 sa CLI süreçleri (CPU'dan bağımsız)
      = "sahipsiz" rozeti. Hiçbir süreç ÖLDÜRÜLMEZ.
Saf/enjekte edilebilir parçalar test için ayrıdır; hiçbir fonksiyon fırlatmaz."""
from __future__ import annotations

import os
import re
import stat
import subprocess
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

MIN_AGE_S = 3600.0
SOCKET_PREFIXES = ("cops-usage-", "cops_e2e_", "ctxprobe", "cxtest", "copusage", "cops-cpusage-probe")
KILLABLE_PREFIXES = ("cops-usage-",)          # yalnız kendi usage soketlerimiz otomatik kapatılır
CLI_NAMES = frozenset({"claude", "copilot", "codex", "agy", "ucli"})


def _sock_dir() -> str:
    return f"/tmp/tmux-{os.getuid()}"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _server_alive(name: str, run: Callable[..., Any] = subprocess.run) -> bool:
    try:
        r = run(["tmux", "-L", name, "list-sessions"], capture_output=True, text=True, timeout=10)
        return getattr(r, "returncode", 1) == 0
    except (OSError, subprocess.SubprocessError):
        return False


def scan_sockets(now: Optional[float] = None, sock_dir: Optional[str] = None, run: Callable[..., Any] = subprocess.run,
                 pid_alive: Callable[[int], bool] = _pid_alive) -> Dict[str, List[Any]]:
    """{deleted: [ad], killed: [ad], orphans: [{name, age_s, owner_pid}]}. Canlı sunucusu olmayan soket dosyası silinir."""
    t = time.time() if now is None else now
    d = sock_dir or _sock_dir()
    out: Dict[str, List[Any]] = {"deleted": [], "killed": [], "orphans": []}
    try:
        names = sorted(x for x in os.listdir(d) if x.startswith(SOCKET_PREFIXES))
    except OSError:
        return out
    for name in names:
        path = os.path.join(d, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        if not stat.S_ISSOCK(st.st_mode) and not os.path.isfile(path):
            continue
        age = t - st.st_mtime
        if not _server_alive(name, run):
            try:
                os.unlink(path)
                out["deleted"].append(name)
            except OSError:
                pass
            continue
        m = re.search(r"(\d+)$", name)
        owner = int(m.group(1)) if m else 0
        owner_dead = not owner or not pid_alive(owner)
        if not owner_dead or age <= MIN_AGE_S:
            continue
        if name.startswith(KILLABLE_PREFIXES):
            try:
                run(["tmux", "-L", name, "kill-server"], capture_output=True, timeout=10)
                os.unlink(path)
                out["killed"].append(name)
                continue
            except (OSError, subprocess.SubprocessError):
                pass
        out["orphans"].append({"name": name, "age_s": int(age), "owner_pid": owner})
    return out


def _pane_pids(run: Callable[..., Any] = subprocess.run) -> Set[int]:
    """cops tmux soketindeki tüm pane süreçleri (ağaçları meşrudur)."""
    try:
        from .tmux_backend import TMUX_SOCKET
        r = run(["tmux", "-L", TMUX_SOCKET, "list-panes", "-a", "-F", "#{pane_pid}"], capture_output=True, text=True, timeout=10)
        return {int(x) for x in (getattr(r, "stdout", "") or "").split() if x.isdigit()}
    except Exception:  # noqa: BLE001
        return set()


def scan_procs(known_pids: Iterable[int], now: Optional[float] = None, procs: Optional[Iterable[Any]] = None,
               pane_pids: Optional[Set[int]] = None) -> List[Dict[str, Any]]:
    """Tanınmayan (known_pids ve cops pane ağaçları dışı), yaşı > 1 sa CLI süreçleri. `procs` testte psutil.Process benzeri enjekte edilir."""
    t = time.time() if now is None else now
    known = set(known_pids)
    try:
        import psutil
        it = procs if procs is not None else psutil.process_iter(["pid", "name", "create_time", "cwd", "cmdline"])
    except Exception:  # noqa: BLE001
        return []
    panes = pane_pids if pane_pids is not None else _pane_pids()
    me = os.getpid()
    out: List[Dict[str, Any]] = []
    for p in it:
        try:
            info = p.info if hasattr(p, "info") else {}
            name = str(info.get("name") or "")
            pid = int(info.get("pid") or 0)
            if name not in CLI_NAMES or not pid or pid in known:
                continue
            age = t - float(info.get("create_time") or t)
            if age <= MIN_AGE_S:
                continue
            cmd = " ".join(info.get("cmdline") or [])
            if "native-host" in cmd or "--chrome" in cmd:       # Chrome eklentisinin köprü süreci, CLI oturumu değil
                continue
            chain: List[int] = []
            q = p
            for _ in range(40):         # ata zinciri: tanınan oturum / cops pane / panelin kendisi altında mı?
                q = q.parent()
                if q is None:
                    break
                chain.append(q.pid)
            if me in chain or any(c in known or c in panes for c in chain):
                continue
            out.append({"pid": pid, "name": name, "age_s": int(age), "cwd": str(info.get("cwd") or "")})
        except Exception:  # noqa: BLE001 — süreç taramada ölebilir
            continue
    return out


def check(known_pids: Optional[Iterable[int]] = None, now: Optional[float] = None) -> Dict[str, Any]:
    """Tek tarama: {sockets: {...}, procs: [...], keys: [kararlı anomali anahtarları]} (anahtar = bildirimde tekrarı önler)."""
    try:
        if known_pids is None:
            from . import discovery
            known_pids = [s.pid for s in discovery.find_sessions(measure_cpu=False) if getattr(s, "pid", None)]
        socks = scan_sockets(now=now)
        procs = scan_procs(known_pids, now=now)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}", "sockets": {}, "procs": [], "keys": []}
    keys = [f"sock:{o['name']}" for o in socks["orphans"]] + [f"proc:{p['pid']}" for p in procs]
    return {"ok": True, "sockets": socks, "procs": procs, "keys": keys}
