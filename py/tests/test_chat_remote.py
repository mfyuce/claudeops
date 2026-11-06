import os, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import chat_remote as R


class FakeRemote:
    """Gerçek tuhaflıkları taklit eder: ilk karakter kaybı + files kökü = canlı cwd."""
    def __init__(self, lose_first=True, cwd="/live"):
        self.cwd, self.files, self.lose_first, self.sent = cwd, {}, lose_first, []
        self.ran = []

    def send(self, cmd):
        self.sent.append(cmd)
        got = cmd[1:] if self.lose_first else cmd           # ilk karakter kayboldu
        self.ran.append(got)
        if got.startswith("nice "):                          # komut bozulmadıysa çalışır
            self.files[".chatpull-yuhem-20261107.tgz"] = b"x" * 10
            self.files[".chatpull-yuhem-20261107.done"] = b""
            assert "cd " not in got                           # cwd (files kökü) değişmemeli
        elif got.startswith("rm "):
            for k in list(self.files):
                assert k.startswith(".chatpull-")             # yalnız kendi dosyası
                del self.files[k]

    def listing(self):
        return list(self.files)

    def download(self, name, dest):
        return len(self.files.get(name, b""))


class RemotePullTest(unittest.TestCase):
    def test_commands_start_with_space_so_first_char_loss_is_harmless(self):
        for c in (R.pack_command("yuhem", "20261107"), R.cleanup_command("yuhem", "20261107")):
            self.assertTrue(c.startswith(" "))
            self.assertNotIn(" cd ", c)                       # cwd'ye dokunma
            self.assertNotIn("/live", c)                      # mutlak çıktı yolu yok

    def test_pull_with_first_char_loss(self):
        fr = FakeRemote(lose_first=True)
        r = R.pull(fr, "yuhem", "20261107", "/tmp/x", sleep=lambda s: None)
        self.assertTrue(r["ok"], r)
        self.assertEqual(fr.files, {})                        # kendi geçici dosyaları silindi

    def test_without_leading_space_would_break(self):
        fr = FakeRemote(lose_first=True)
        fr.send(R.pack_command("yuhem", "20261107").lstrip())  # kanıt: boşluksuz komut bozulur
        self.assertEqual(fr.files, {})

    def test_timeout_and_bad_tag(self):
        class Never(FakeRemote):
            def send(self, cmd):
                self.sent.append(cmd)
        t = [0.0]
        r = R.pull(Never(), "yuhem", "20261107", "/tmp/x", wait_s=30, poll_s=10,
                   sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0])
        self.assertFalse(r["ok"])
        self.assertFalse(R.pull(FakeRemote(), "Bad Tag", "20261107", "/tmp/x")["ok"])


if __name__ == "__main__":
    unittest.main()
