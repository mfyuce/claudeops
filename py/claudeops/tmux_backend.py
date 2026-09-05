"""tmux-backed sessions — dedicated socket ("-L cops"), isolated from any other
tmux usage on the machine.

Every helper here is best-effort: on any failure (tmux missing, session gone,
subprocess timeout) it returns None/False/[] rather than raising — a hung/missing
tmux must never hang or crash a caller, especially once capture/send-keys is
polled every ~150-250ms from a ThreadingHTTPServer request thread ([[tmux-backed
web CLI plan]]).
"""
from __future__ import annotations
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional

TMUX_SOCKET = "cops"
_TIMEOUT = 5.0
_ANCESTOR_WALK_LIMIT = 6


def tmux_available() -> bool:
    return shutil.which("tmux") is not None


def tmux_conf_path() -> str:
    return str(Path(__file__).resolve().parent / "data" / "tmux.conf")


def _base_argv() -> List[str]:
    return ["tmux", "-L", TMUX_SOCKET]


def tmux_new_session_shell_fragment(name: str, cwd: str, inner: str) -> str:
    """Bash-fragment (NOT executed here) spawn.py splices into its gnome-terminal
    command: `tmux -L cops -f <conf> new-session -A -s NAME -c CWD -x 100 -y 30 INNER`.

    -A = attach-if-exists-else-create (idempotent — safe to reopen the same window
    without creating a duplicate session). `inner` is spawn.py's own already
    shlex-quoted command string; shlex.quote nests safely over it.
    """
    return (
        f"{shlex.join(_base_argv())} -f {shlex.quote(tmux_conf_path())} "
        f"new-session -A -s {shlex.quote(name)} -c {shlex.quote(cwd)} "
        f"-x 100 -y 30 {shlex.quote(inner)}"
    )


def tmux_attach_shell_fragment(name: str) -> str:
    """Bash-fragment (NOT executed here) spawn.py splices into a gnome-terminal
    command to bind a NEW window to an EXISTING tmux session, without touching
    the CLI process inside it (used by spawn.py's `open_window` — the one-click
    fix for a session that ended up windowless)."""
    return f"{shlex.join(_base_argv())} -f {shlex.quote(tmux_conf_path())} attach-session -t {shlex.quote(name)}"


def tmux_spawn_direct(name: str, cwd: str, inner: str, env: dict) -> bool:
    """gnome-terminal'siz DOĞRUDAN tmux session aç — spawn.py'nin gnome-terminal
    fallback'ı ([[spawn-zombie-child-degrades-web-server]], gnome-terminal-server
    kendi D-Bus state'iyle bozulunca hiç pencere açmıyor, sessizce). `-A` sayesinde
    idempotent: session zaten varsa (gnome-terminal aslında başarmış, biz sadece
    geç kontrol ettiysek) no-op — ikinci bir claude başlatmaz.

    `inner` TEK bir argv elemanı olarak geçiriliyor (subprocess shell=False) — tmux
    bunu kendi `$SHELL -c` çağrısına verir, `tmux_new_session_shell_fragment`'ın
    dolaylı yolunun (outer bash -c → bu fragment) ürettiğiyle AYNI tek-geçişli
    shell-parse sonucunu verir, çift-quote uyumsuzluğu olmaz."""
    cmd = _base_argv() + [
        "-f", tmux_conf_path(), "new-session", "-d", "-A",
        "-s", name, "-c", cwd, "-x", "100", "-y", "30",
        f"{inner}; exec bash",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT, env=env)
        return r.returncode == 0
    except Exception:
        return False


def tmux_has_session(name: str) -> bool:
    try:
        r = subprocess.run(_base_argv() + ["has-session", "-t", name],
                            capture_output=True, timeout=_TIMEOUT)
        return r.returncode == 0
    except Exception:
        return False


def tmux_capture(name: str, lines: int = 2000) -> Optional[str]:
    try:
        r = subprocess.run(
            _base_argv() + ["capture-pane", "-t", name, "-e", "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if r.returncode != 0:
            return None
        return r.stdout
    except Exception:
        return None


def tmux_send_keys(name: str, text: str, settle_delay: float = 0.0) -> bool:
    """`settle_delay` — literal metni gönderdikten SONRA, Enter'ı göndermeden
    ÖNCE bekle (saniye). Varsayılan 0.0: claude/agy/shell zaten anlık Enter'ı
    doğru işliyor. codex GEREKTİRİYOR (2026-09-05, canlı bulundu: literal metin +
    AYNI anda ayrı bir Enter kombinasyonu mesajı input kutusunda gönderilmemiş
    bırakıyor — codex bunu ikinci, gecikmeli bir Enter'la işliyor, muhtemelen
    kendi input-render döngüsünün metni "görmesi" için bir an gerektirdiği için;
    150ms hem tek-satır hem çok-satırlı/Türkçe-karakterli mesajlarla izole bir
    tmux-only test session'ında güvenilir şekilde doğrulandı). Çağıran taraf
    `CliProvider.input_settle_delay()` ile provider-bazlı değeri geçer — burada
    `if cli==...` YOK, sadece parametrenin kendisi."""
    try:
        r1 = subprocess.run(_base_argv() + ["send-keys", "-t", name, "-l", text],
                             capture_output=True, timeout=_TIMEOUT)
        if r1.returncode != 0:
            return False
        if settle_delay > 0:
            time.sleep(settle_delay)
        r2 = subprocess.run(_base_argv() + ["send-keys", "-t", name, "Enter"],
                             capture_output=True, timeout=_TIMEOUT)
        return r2.returncode == 0
    except Exception:
        return False


# Only these key-names may go through non-literal send-keys (never pass arbitrary
# strings this way — literal text always goes through tmux_send_keys's `-l` path).
ALLOWED_SPECIAL_KEYS = {"C-c", "C-d", "Escape", "Up", "Down", "Left", "Right", "Tab", "Enter"}


def tmux_send_special_key(name: str, key: str) -> bool:
    if key not in ALLOWED_SPECIAL_KEYS:
        return False
    try:
        r = subprocess.run(_base_argv() + ["send-keys", "-t", name, key],
                            capture_output=True, timeout=_TIMEOUT)
        return r.returncode == 0
    except Exception:
        return False


def tmux_pane_size(name: str) -> Optional[tuple]:
    """Panelin GERÇEK boyutu — new-session'daki -x/-y sadece istemci hiç bağlanmamışsa
    geçerli; attach eden bir client (bizim gnome-terminal penceremiz) varsa tmux paneli
    o client'ın gerçek boyutuna göre yeniden boyutlandırır (örn. -x 100 -y 30 istense
    bile pencere gerçekte 211x23 olabilir) — xterm.js'in doğru sarmalama/hizalama
    göstermesi için gerçek boyutu döndürüp frontend'in `term.resize()` çağırması gerekir."""
    try:
        r = subprocess.run(
            _base_argv() + ["list-panes", "-t", name, "-F", "#{pane_width} #{pane_height}"],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        w, h = r.stdout.strip().splitlines()[0].split()
        return int(w), int(h)
    except Exception:
        return None


def tmux_kill_session(name: str) -> None:
    try:
        subprocess.run(_base_argv() + ["kill-session", "-t", name],
                        capture_output=True, timeout=_TIMEOUT)
    except Exception:
        pass


def find_outer_bash_pids(name: str) -> List[tuple]:
    """Find gnome-terminal-launched `bash -c "... ; exec bash"` windows attached
    to tmux session `name`, BEFORE tearing it down (TODO: tmux-backed "stop"
    leaves an orphan window).

    spawn.py opens a window with `bash -c "tmux -L cops ... new-session -A -s
    NAME ...; exec bash"` (no `-d` — the window itself IS the attached tmux
    client); `open_window()`'s one-click "pencere aç" adds more windows the
    same way via `attach-session -t NAME; exec bash`. Neither is an ancestor
    of the pane's own claude/agy pid (both reach the pane only through the
    shared tmux SERVER, never through the OS process tree — see
    `kill_session_and_parent`'s docstring), so they can't be found by walking
    up from `pid`; they must be matched by cmdline instead.

    That cmdline is only readable in this window: once the session dies (the
    pane's command exiting already ends it by default, before an explicit
    `tmux kill-session` even runs) the attached client returns and `exec
    bash` REPLACES this process's argv, permanently erasing the `-s NAME`/
    `-t NAME` text `cmdline()` would otherwise match on. Callers must call
    this BEFORE killing the pane's process, not just before `tmux_kill_session`.

    Returns a list of (pid, create_time) — create_time lets a caller that
    kills later re-check it's still the same process, not a reused pid
    (mirrors kill_session_and_parent's own parent-pid-before-kill pattern).
    A session can have more than one attached window (original + "pencere
    aç" extras), so this returns every match rather than just the first.
    """
    import psutil

    needles = (
        f"-s {shlex.quote(name)} -c ",              # spawn.py's initial window
        f"attach-session -t {shlex.quote(name)};",  # open_window()'s extra window(s)
    )
    found: List[tuple] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] != "bash":
                continue
            cmdline = proc.cmdline()
            if len(cmdline) < 3 or cmdline[1] != "-c":
                continue
            script = cmdline[2]
            if any(needle in script for needle in needles):
                found.append((proc.pid, proc.create_time()))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return found


def is_tmux_backed(pid: int) -> bool:
    """Walk the psutil ancestor chain (bounded) looking for our tmux server.

    Conservative: any lookup failure (NoSuchProcess/AccessDenied/zombie) at any
    hop stops the walk and returns False — uncertain means "treat as a legacy
    bare session", never over-claims tmux-backed status. This is what keeps
    already-running plain sessions correctly untouched by the tmux-aware kill
    path until they're naturally respawned.
    """
    import psutil

    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return False

    want = ["tmux", "-L", TMUX_SOCKET]
    for _ in range(_ANCESTOR_WALK_LIMIT):
        try:
            proc = proc.parent()
            if proc is None:
                return False
            cmd = proc.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False
        if not cmd:
            continue
        if os.path.basename(cmd[0]) == "tmux" and cmd[1:3] == want[1:3]:
            return True
    return False
