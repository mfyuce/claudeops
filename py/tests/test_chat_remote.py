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
        if got.startswith("nice "):
            assert "/live/.chatpull-" in got                          # komut bozulmadıysa çalışır
            self.files[".chatpull-yuhem-20261107.tgz"] = b"x" * 10
            self.files[".chatpull-yuhem-20261107.done"] = b""
            assert "cd " not in got                           # cwd (files kökü) değişmemeli
        elif got.startswith("rm "):
            for a in got.split()[3:]:                         # yalnız adı verilen dosyaları siler (joker yok)
                self.files.pop(a.strip("'").split("/")[-1], None)

    busy = False

    def idle(self):
        return not self.busy

    def root(self):
        return self.cwd

    def listing(self, root):
        assert root == "/live"
        return list(self.files)

    def download(self, root, name, dest):
        return len(self.files.get(name, b""))


class RemotePullTest(unittest.TestCase):
    def test_commands_start_with_space_so_first_char_loss_is_harmless(self):
        for c in (R.pack_command("yuhem", "20261107", outdir="/live"), R.cleanup_command("yuhem", "20261107", "/live")):
            self.assertTrue(c.startswith(" "))
            self.assertNotIn(" cd ", c)                       # shell cwd'sine dokunma
            self.assertIn("/live/.chatpull-", c)              # çıktı başta okunan MUTLAK kök (cwd değişse de aynı yer)

    def test_pull_with_first_char_loss(self):
        fr = FakeRemote(lose_first=True)
        r = R.pull(fr, "yuhem", "20261107", "/tmp/x", sleep=lambda s: None)
        self.assertTrue(r["ok"], r)
        self.assertEqual(fr.files, {})                        # kendi geçici dosyaları silindi

    def test_without_leading_space_would_break(self):
        fr = FakeRemote(lose_first=True)
        fr.send(R.pack_command("yuhem", "20261107", outdir="/live").lstrip())  # kanıt: boşluksuz komut bozulur
        self.assertEqual(fr.files, {})

    def test_busy_shell_backs_off_cleanly(self):
        fr = FakeRemote()
        fr.busy = True
        r = R.pull(fr, "yuhem", "20261107", "/tmp/x", sleep=lambda s: None)
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("skipped"))
        self.assertEqual(fr.sent, [])                          # hiçbir şey gönderilmedi

    def test_cleanup_touches_only_own_files(self):
        fr = FakeRemote()
        fr.files["kullanici.txt"] = b"onemli"
        fr.send(R.cleanup_command("yuhem", "20261107", "/live"))
        self.assertIn("kullanici.txt", fr.files)
        c = R.cleanup_command("yuhem", "20261107", "/live")
        self.assertNotIn("*", c)                               # joker yok
        self.assertEqual(sorted(a.split("/")[-1] for a in c.split()[3:]), sorted(R.names("yuhem", "20261107").values()))

    def test_timeout_and_bad_tag(self):
        class Never(FakeRemote):
            def send(self, cmd):
                self.sent.append(cmd)
        t = [0.0]
        r = R.pull(Never(), "yuhem", "20261107", "/tmp/x", wait_s=30, poll_s=10,
                   sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0])
        self.assertFalse(r["ok"])
        self.assertFalse(R.pull(FakeRemote(), "Bad Tag", "20261107", "/tmp/x")["ok"])

    def test_dashed_host_tag_and_stale_done_preclean(self):
        self.assertIn(".chatpull-my-host-20261111.done", R.names("my-host", "20261111")["done"])
        fr = FakeRemote()
        fr.files[".chatpull-yuhem-20261107.done"] = b""          # bayat işaret
        r = R.pull(fr, "yuhem", "20261107", "/tmp/x", poll_s=0, sleep=lambda s: None)
        self.assertTrue(fr.ran[0].strip().startswith("rm "))              # pack'ten önce temizlendi
        self.assertTrue(r["ok"])

    def test_kv_parses_json_values(self):
        from claudeops.commands import periodic_cmd as C
        self.assertEqual(C._kv(['remote_pull={"yuhem":"shell_yuhem"}'])["remote_pull"], {"yuhem": "shell_yuhem"})
        with self.assertRaises(ValueError):
            C._kv(["remote_pull={bozuk"])


if __name__ == "__main__":
    unittest.main()
