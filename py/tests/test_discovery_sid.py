"""`discovery.find_sessions`ın `sid` birleştirmesi ve `Session.is_fresh` (stdlib unittest).

Hata (TODO.md 2026-10-16 (6)): proc-scan girdisi, aynı (isim, pid) anahtarındaki sessions/<pid>.json girdisini
`sid=None` ile eziyordu; taze `--new` claude oturumlarında cmdline'da `--resume` yok, bu yüzden canlı sid
kayboluyor ve model/effort, kapanış anlık görüntüsü, transkript seçimi cwd'deki "en yeni dosya" tahminine
düşüyordu (filoda 37 claude oturumunun 9'u, hepsi etkin olanlar). Düzeltme: sid = json'daki CANLI sessionId,
yoksa cmdline; "taze mi" sorusu ayrı `resumed` bayrağından okunur (sid dolunca `is_fresh` kaymasın).

Çalıştırma:  python3 py/tests/test_discovery_sid.py -v

Canlı süreçleri taramaz (psutil sahte), dosya okumaz (json kaynağı sahte), ağa çıkmaz.
"""
import os
import sys
import unittest
from collections import namedtuple
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import discovery  # noqa: E402
from claudeops.providers.claude_provider import ClaudeProvider  # noqa: E402
from claudeops.session import Session  # noqa: E402

UIDS = namedtuple("UIDS", "real effective saved")
ME = os.getuid()


class FakeProc:
    """`psutil.Process`ın `find_sessions`ın dokunduğu yüzeyi: `.pid`, `.info`, `.cwd()`, `.cpu_percent()`."""

    def __init__(self, pid, cmdline, cwd="/w/proj"):
        self.pid = pid
        self.info = {"pid": pid, "cmdline": cmdline, "uids": UIDS(ME, ME, ME)}
        self._cwd = cwd

    def cwd(self):
        return self._cwd

    def cpu_percent(self, interval=None):
        return 0.0


class FakeProvider:
    """claude olmayan, kendi sid'ini cmdline'dan alan bir CLI (ucli gibi)."""

    def __init__(self, name="fakecli", sid=None):
        self.name = name
        self._sid = sid

    def matches_proc(self, cmd):
        return bool(cmd) and cmd[0] == self.name

    def extract_name(self, proc, cmd):
        return cmd[1]

    def extract_info(self, cmd, cwd="", session_name=""):
        return {"sid": self._sid, "model": None, "permission_mode": None, "effort": None}


def claude_cmd(name, resume=None):
    return ["claude", "--remote-control", name, "--model", "claude-sonnet-5-5"] + (["--resume", resume] if resume else [])


def json_entry(name, pid, sid, cli="claude"):
    """`_sessions_from_json`ın döndürdüğü girdinin şekli."""
    return {(name, pid): Session(name=name, pid=pid, cwd="/w/proj", sid=sid, cli=cli)}


class FindSessionsSidTests(unittest.TestCase):
    def scan(self, procs, json_sessions, providers=None):
        with mock.patch.object(discovery.psutil, "process_iter", lambda attrs=None: iter(procs)), \
                mock.patch.object(discovery, "_sessions_from_json", lambda: dict(json_sessions)), \
                mock.patch.object(discovery, "PROVIDERS", providers or {"claude": ClaudeProvider()}):
            return {(s.name, s.pid): s for s in discovery.find_sessions(measure_cpu=False)}

    def test_a_fresh_session_gets_the_live_sid_from_the_json_entry(self):
        got = self.scan([FakeProc(500, claude_cmd("zz1"))], json_entry("zz1", 500, "live-sid"))
        s = got[("zz1", 500)]
        self.assertEqual(s.sid, "live-sid")
        self.assertFalse(s.resumed)
        self.assertTrue(s.is_fresh)                       # sid dolu olsa da "fresh" kalır (panel "fresh" yazar)
        self.assertEqual((s.model, s.cli), ("claude-sonnet-5-5", "claude"))   # cmdline alanları yine proc-scan'den

    def test_a_resumed_session_keeps_its_sid_and_stays_resumed(self):
        got = self.scan([FakeProc(500, claude_cmd("zz1", resume="sid-a"))], json_entry("zz1", 500, "sid-a"))
        s = got[("zz1", 500)]
        self.assertEqual(s.sid, "sid-a")
        self.assertTrue(s.resumed)
        self.assertFalse(s.is_fresh)

    def test_the_live_json_sid_wins_over_a_stale_cmdline_sid(self):
        """`--resume ESKI` ile açılıp `/clear` ya da TUI'den resume ile başka konuşmaya geçen oturum:
        CLI pid dosyasındaki sessionId'yi yeniden yazar, cmdline hiç değişmez."""
        got = self.scan([FakeProc(500, claude_cmd("zz1", resume="old-sid"))], json_entry("zz1", 500, "new-sid"))
        s = got[("zz1", 500)]
        self.assertEqual(s.sid, "new-sid")
        self.assertTrue(s.resumed)                        # yine "resume" açılmış bir oturum
        self.assertFalse(s.is_fresh)

    def test_without_a_json_entry_the_cmdline_value_is_used_exactly_as_before(self):
        got = self.scan([FakeProc(500, claude_cmd("zz1", resume="sid-a")), FakeProc(501, claude_cmd("zz2"))], {})
        self.assertEqual((got[("zz1", 500)].sid, got[("zz1", 500)].is_fresh), ("sid-a", False))
        self.assertEqual((got[("zz2", 501)].sid, got[("zz2", 501)].is_fresh), (None, True))

    def test_a_json_entry_without_a_sid_never_blanks_the_cmdline_sid(self):
        got = self.scan([FakeProc(500, claude_cmd("zz1", resume="sid-a"))], json_entry("zz1", 500, None))
        self.assertEqual(got[("zz1", 500)].sid, "sid-a")

    def test_each_session_gets_its_own_sid_by_pid(self):
        json_sessions = {**json_entry("zz1", 500, "sid-1"), **json_entry("zz2", 501, "sid-2")}
        got = self.scan([FakeProc(500, claude_cmd("zz1")), FakeProc(501, claude_cmd("zz2"))], json_sessions)
        self.assertEqual((got[("zz1", 500)].sid, got[("zz2", 501)].sid), ("sid-1", "sid-2"))

    def test_a_json_entry_of_another_cli_never_donates_its_sid(self):
        """Eski bir claude json'ının pid'i başka bir CLI'nin sürecine kalmışsa (pid yeniden kullanımı)
        claude sid'i o sürecin üstüne yapışmaz."""
        provider = FakeProvider("fakecli", sid=None)
        got = self.scan([FakeProc(500, ["fakecli", "zz1"])], json_entry("zz1", 500, "claude-sid", cli="claude"),
                        providers={"fakecli": provider})
        self.assertIsNone(got[("zz1", 500)].sid)

    def test_a_non_claude_cli_keeps_its_cmdline_sid_and_its_old_is_fresh(self):
        """ucli'de sid = oturum adı (hep dolu): `is_fresh` bugün hep False, değişmemeli; sid'siz CLI hep True."""
        with_sid = self.scan([FakeProc(500, ["fakecli", "zz1"])], {}, providers={"fakecli": FakeProvider(sid="zz1")})
        self.assertEqual((with_sid[("zz1", 500)].sid, with_sid[("zz1", 500)].is_fresh), ("zz1", False))
        without = self.scan([FakeProc(500, ["fakecli", "zz1"])], {}, providers={"fakecli": FakeProvider(sid=None)})
        self.assertEqual((without[("zz1", 500)].sid, without[("zz1", 500)].is_fresh), (None, True))


class IsFreshTests(unittest.TestCase):
    def test_flag_unknown_falls_back_to_the_sid(self):
        """Sentetik (`pid=0`) ve yalnız json'dan gelen girdiler bayrak taşımaz: eski kural geçerli."""
        self.assertTrue(Session(name="a", pid=1).is_fresh)
        self.assertFalse(Session(name="a", pid=1, sid="x").is_fresh)

    def test_flag_known_wins_over_the_sid(self):
        self.assertTrue(Session(name="a", pid=1, sid="x", resumed=False).is_fresh)
        self.assertFalse(Session(name="a", pid=1, sid=None, resumed=True).is_fresh)


if __name__ == "__main__":
    unittest.main()
