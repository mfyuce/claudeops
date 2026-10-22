"""Panel: GET /api/steward/digests ve /digest/file (günlük özet + uzun tur dosyaları). Salt okunur; ağ/oturum YOK."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import settings, steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


def _w(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TestDigests(_Tmp):
    def setUp(self):
        super().setUp()
        self.p = sw.paths_for("default")
        self.lst = lambda sid=None: ws.http_get("/api/steward/digests", {"steward": [sid]} if sid else {})
        self.get = lambda kind, name, sid=None: ws.http_get("/api/steward/digest/file", dict({"kind": [kind], "name": [name]}, **({"steward": [sid]} if sid else {})))

    def test_empty(self):
        r = self.lst()
        self.assertEqual((r["ok"], r["daily"], r["tours"]), (True, [], []))

    def test_order_and_cap(self):
        for i in range(1, 71):
            _w(os.path.join(self.p.daily, "2026-01-%02d.md" % (i % 28 + 1) if False else "2026-%02d-%02d.md" % (1 + (i - 1) // 28, (i - 1) % 28 + 1)))
        _w(os.path.join(self.p.daily, "notes.txt"))
        _w(os.path.join(self.p.daily, "2026-1-1.md"))
        for ts in (5, 100, 20):
            _w(os.path.join(self.p.workspace, "tours", "tour-%d.md" % ts))
        _w(os.path.join(self.p.workspace, "tours", "other.md"))
        r = self.lst()
        self.assertEqual(len(r["daily"]), 60)
        dates = [x["date"] for x in r["daily"]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual([x["ts"] for x in r["tours"]], [100, 20, 5])
        self.assertEqual(set(r["tours"][0]), {"file", "size", "mtime", "ts"})

    def test_read_and_redact(self):
        _w(os.path.join(self.p.daily, "2026-02-03.md"), "merhaba\nAuthorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789\n")
        r = self.get("daily", "2026-02-03.md")
        self.assertTrue(r["ok"])
        self.assertIn("merhaba", r["text"])
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz0123456789", r["text"])

    def test_size_cap(self):
        _w(os.path.join(self.p.workspace, "tours", "tour-7.md"), "a" * (ws.DIGEST_FILE_MAX + 500))
        r = self.get("tours", "tour-7.md")
        self.assertTrue(r["ok"] and r["truncated"])
        self.assertEqual(len(r["text"]), ws.DIGEST_FILE_MAX)

    def test_path_safety(self):
        _w(os.path.join(self.p.daily, "2026-02-03.md"))
        secret = os.path.join(self.dir.name, "secret.md")
        _w(secret, "TOP")
        os.symlink(secret, os.path.join(self.p.daily, "2026-02-04.md"))
        for kind, name in (("daily", "../steward/state.json"), ("daily", "/etc/passwd"), ("daily", "..%2f2026-02-03.md"),
                           ("daily", "2026-02-03.md/../x"), ("tours", "2026-02-03.md"), ("nope", "2026-02-03.md"),
                           ("daily", "2026-02-04.md"), ("daily", ""), ("daily", "2026-02-09.md")):
            r = self.get(kind, name)
            self.assertFalse(r["ok"], (kind, name))
        self.assertEqual([x["date"] for x in self.lst()["daily"]], ["2026-02-03"])      # symlink listelenmez

    def test_other_identity_and_reviewer(self):
        settings.save_settings({"stewards": {"kitap": {"enabled": "on"}, "rev": {"enabled": "on", "role": "reviewer"}}})
        pk = sw.paths_for("kitap")
        _w(os.path.join(pk.daily, "2026-03-01.md"), "kitap")
        _w(os.path.join(self.p.daily, "2026-03-02.md"), "default")
        self.assertEqual([x["date"] for x in self.lst("kitap")["daily"]], ["2026-03-01"])
        self.assertEqual(self.get("daily", "2026-03-01.md", "kitap")["text"], "kitap")
        self.assertFalse(self.get("daily", "2026-03-02.md", "kitap")["ok"])
        pr = sw.paths_for("rev")
        _w(os.path.join(pr.daily, "2026-03-03.md"), "r")
        r = self.lst("rev")
        self.assertEqual((r["ok"], r["daily"], r["tours"]), (True, [], []))
        self.assertFalse(self.get("daily", "2026-03-03.md", "rev")["ok"])


if __name__ == "__main__":
    unittest.main()
