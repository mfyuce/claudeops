"""kill_session: create_time uyuşmazsa (PID yeniden kullanımı) sinyal gönderilmez."""
from claudeops import kill


class _Proc:
    def __init__(self, ct):
        self._ct = ct
        self.signals = []

    def create_time(self):
        return self._ct

    def send_signal(self, sig):
        self.signals.append(sig)

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.signals.append("KILL")


def test_mismatched_create_time_skips_signal(monkeypatch):
    p = _Proc(100.0)
    monkeypatch.setattr(kill.psutil, "Process", lambda pid: p)
    assert kill.kill_session(1234, grace=0.1, create_time=999.0) == "already_dead"
    assert p.signals == []


def test_matching_create_time_signals(monkeypatch):
    p = _Proc(100.0)
    monkeypatch.setattr(kill.psutil, "Process", lambda pid: p)
    assert kill.kill_session(1234, grace=0.1, create_time=100.0) == "clean"
    assert len(p.signals) == 1


def test_no_create_time_is_legacy(monkeypatch):
    p = _Proc(100.0)
    monkeypatch.setattr(kill.psutil, "Process", lambda pid: p)
    assert kill.kill_session(1234, grace=0.1) == "clean"
