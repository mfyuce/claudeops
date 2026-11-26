"""Gerçek tmux gerektiren testler için yalıtılmış sunucu: geçici `TMUX_TMPDIR` (kısa yol, soket adı sınırı) + rastgele
soket + `-f /dev/null`. `tmux_backend.TMUX_SOCKET` ve çevre test süresince bu sunucuya çevrilir; canlı `-L cops`
sunucusuna ve varsayılan sokete hiçbir komut gitmez."""
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from unittest import mock

from claudeops import tmux_backend as tb

HAVE_TMUX = shutil.which("tmux") is not None


class IsoTmux:
    def __init__(self, extra_env=None):
        self.dir = tempfile.mkdtemp(prefix="cxpy", dir="/tmp")
        self.socket = "cxpy" + uuid.uuid4().hex[:12]
        env = {k: v for k, v in os.environ.items() if k != "TMUX"}
        env["TMUX_TMPDIR"] = self.dir
        env.update(extra_env or {})
        self.env = env
        self._patches = [mock.patch.dict(os.environ, env, clear=True),
                         mock.patch.object(tb, "TMUX_SOCKET", self.socket)]

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        subprocess.run(["tmux", "-L", self.socket, "kill-server"], capture_output=True, env=self.env)
        for p in reversed(self._patches):
            p.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def raw(self, *args, check=True) -> str:
        r = subprocess.run(["tmux", "-u", "-L", self.socket, "-f", "/dev/null", *args],
                           capture_output=True, text=True, env=self.env)
        if check and r.returncode != 0:
            raise AssertionError(f"tmux {args}: {r.stderr}")
        return r.stdout

    def spawn(self, name: str, command: str = "exec sleep 120") -> None:
        self.raw("new-session", "-d", "-s", name, "-x", "80", "-y", "24", "-c", self.dir, command)

    def sessions(self):
        return sorted(self.raw("list-sessions", "-F", "#{session_name}", check=False).splitlines())

    def wait(self, cond, what: str, timeout: float = 10.0):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return
            time.sleep(0.05)
        raise AssertionError(f"beklenen olmadı: {what}")
