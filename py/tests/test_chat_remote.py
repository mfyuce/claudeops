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
        if got.startswith("bash -c "):
            assert "/live/.chatpull-" in got                          # komut bozulmadıysa çalışır
            self.files[".chatpull-yuhem-20261107.tgz.p000"] = b"x" * 10
            self.files[".chatpull-yuhem-20261107.tgz.p001"] = b"y" * 5
            self.files[".chatpull-yuhem-20261107.done"] = b""
            assert " cd " not in got                          # cwd (files kökü) değişmemeli
        elif got.startswith("rm "):
            pat = got.split()[-1].strip("'\"")                # `<önek>*`: yalnız kendi önekli dosyalar
            assert pat.endswith("*") and ".chatpull-" in pat
            for k in [k for k in self.files if ("/live/" + k).startswith(pat[:-1])]:
                self.files.pop(k)

    busy = False

    def idle(self):
        return not self.busy

    def root(self):
        return self.cwd

    def listing(self, root):
        assert root == "/live"
        return list(self.files)

    def download(self, root, name, dest):
        b = self.files.get(name, b"")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "wb").write(b)
        return len(b)


class RemotePullTest(unittest.TestCase):
    def test_commands_start_with_space_so_first_char_loss_is_harmless(self):
        for c in (R.pack_command("yuhem", "20261107", outdir="/live"), R.cleanup_command("yuhem", "20261107", "/live")):
            self.assertTrue(c.startswith(" "))
            self.assertNotIn(" cd ", c)                       # shell cwd'sine dokunma
            self.assertIn("/live/.chatpull-", c)              # çıktı başta okunan MUTLAK kök (cwd değişse de aynı yer)

    def test_pull_with_first_char_loss(self):
        fr = FakeRemote(lose_first=True)
        d = tempfile.mkdtemp()
        r = R.pull(fr, "yuhem", "20261107", os.path.join(d, "a.tgz"), sleep=lambda s: None)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["bytes"], 15)
        self.assertEqual(open(os.path.join(d, "a.tgz"), "rb").read(), b"x" * 10 + b"y" * 5)      # parçalar sırayla birleşti
        self.assertEqual(sorted(os.listdir(d)), ["a.tgz"])    # ara parçalar temizlendi
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
        fr.files[".chatpull-yuhem-20261106.tgz.p000"] = b"eski"      # önceki günün artığı da silinir
        fr.files[".chatpull-baska-20261106.tgz.p000"] = b"baska"     # başka etiket kalır
        fr.send(R.cleanup_command("yuhem", "20261107", "/live"))
        self.assertEqual(sorted(fr.files), [".chatpull-baska-20261106.tgz.p000", "kullanici.txt"])

    def test_pack_is_private_split_and_excludes_credentials(self):
        c = R.pack_command("yuhem", "20261107", outdir="/live")
        self.assertIn("umask 077", c)
        self.assertIn("split -b 150M", c)
        for e in ("auth.json", "oauth_creds.json"):
            self.assertIn(f"--exclude={e}", c)

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
        r = R.pull(fr, "yuhem", "20261107", os.path.join(tempfile.mkdtemp(), "b.tgz"), poll_s=0, sleep=lambda s: None)
        self.assertTrue(fr.ran[0].strip().startswith("rm "))              # pack'ten önce temizlendi
        self.assertTrue(r["ok"])

    def test_kv_parses_json_values(self):
        from claudeops.commands import periodic_cmd as C
        self.assertEqual(C._kv(['remote_pull={"yuhem":"shell_yuhem"}'])["remote_pull"], {"yuhem": "shell_yuhem"})
        with self.assertRaises(ValueError):
            C._kv(["remote_pull={bozuk"])


if __name__ == "__main__":
    unittest.main()
