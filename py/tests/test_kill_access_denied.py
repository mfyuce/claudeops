"""kill_session_and_parent: psutil.AccessDenied temizliği yarıda bırakmaz (tmux kill-session + dış pencere yine çalışır)."""
import pytest
import psutil

from claudeops import kill, tmux_backend


class _Outer:
    def __init__(self):
        self.killed = False

    def create_time(self):
        return 5.0

    def kill(self):
        self.killed = True


def test_access_denied_still_cleans_up(monkeypatch):
    outer = _Outer()
    cleaned = []

    class _Main:
        def create_time(self):
            return 1.0

    def fake_process(pid):
        return outer if pid == 777 else _Main()

    def denied(*a, **k):
        raise psutil.AccessDenied(1234)

    monkeypatch.setattr(kill.psutil, "Process", fake_process)
    monkeypatch.setattr(kill, "kill_session", denied)
    monkeypatch.setattr(tmux_backend, "is_tmux_backed", lambda pid: True)
    monkeypatch.setattr(tmux_backend, "find_outer_bash_pids", lambda name: [(777, 5.0)])
    monkeypatch.setattr(tmux_backend, "tmux_kill_session", lambda name: cleaned.append(name))

    with pytest.raises(psutil.AccessDenied):
        kill.kill_session_and_parent(1234, grace=0.1, name="foo")
    assert cleaned == ["foo"]
    assert outer.killed is True
