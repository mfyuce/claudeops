"""Okuma bileti (`read_ticket`) + `/api/files/ticket` + `/readfile/` güvenliği. Canlı servis/ağ YOK."""
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import read_ticket as rt  # noqa: E402
from claudeops import extensions as ext  # noqa: E402
from claudeops.commands import web  # noqa: E402

TOKEN = "tok123"


class Ticket(unittest.TestCase):
    def test_roundtrip(self):
        t = rt.issue(TOKEN, "proj", "docs/a b.pdf", "local", now=1000)
        self.assertEqual(rt.verify(TOKEN, t, now=1001), {"name": "proj", "path": "docs/a b.pdf", "host": "local"})

    def test_expiry_tamper_wrong_token(self):
        t = rt.issue(TOKEN, "p", "x.md", "local", now=1000)
        self.assertIsNone(rt.verify(TOKEN, t, now=1000 + rt.TTL_SECONDS + 1))
        body, sig = t.split(".")
        forged = rt.issue(TOKEN, "p", "../../etc/passwd", "local", now=1000).split(".")[0] + "." + sig      # imza başka gövdeye
        self.assertIsNone(rt.verify(TOKEN, forged, now=1001))
        self.assertIsNone(rt.verify("other", t, now=1001))
        self.assertIsNone(rt.verify("", t, now=1001))
        for bad in ("", "x", "a.b", "." + sig, body + ".", "A" * 5000 + ".x"):
            self.assertIsNone(rt.verify(TOKEN, bad, now=1001), bad)

    def test_empty_name_or_path_invalid(self):
        self.assertIsNone(rt.verify(TOKEN, rt.issue(TOKEN, "", "x", "local", now=1), now=2))
        self.assertIsNone(rt.verify(TOKEN, rt.issue(TOKEN, "p", "", "local", now=1), now=2))


class Headers(unittest.TestCase):
    def test_active_types_become_plain_text_and_sandbox(self):
        for f in ("a.html", "a.svg", "a.xml", "a.js", "a.json", "a.md", "a.tex", "a.txt", "a.py"):
            h = web._ticket_file_headers(f)
            self.assertTrue(h["Content-Type"].startswith("text/plain"), f)
            self.assertEqual(h["Content-Security-Policy"], "sandbox")
            self.assertEqual(h["Content-Disposition"], "inline")
            self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertEqual(web._ticket_file_headers("a.pdf")["Content-Type"], "application/pdf")
        self.assertEqual(web._ticket_file_headers("a.bin")["Content-Type"], "application/octet-stream")


class FakeH:
    token = TOKEN

    def __init__(self, body=b"", path="/api/files/ticket"):
        self.path = path
        self.headers = {"Content-Length": str(len(body))}
        self._body = body
        self.status = None
        self.sent = {}
        self.wfile = io.BytesIO()
        self.close_connection = False
        self.json_out = None

    def _read_body(self, n):
        return self._body

    def _json(self, obj, status=200):
        self.json_out, self.status = obj, status

    def send_response(self, s):
        self.status = s

    def send_header(self, k, v):
        self.sent[k] = v

    def end_headers(self):
        pass


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.f = os.path.join(self.d, "r.md")
        open(self.f, "w").write("# x")
        self._res = web._files_resolve
        self._rd = web.files_mod.resolve_download
        web._files_resolve = lambda name, lang: ((self.d, None), None) if name == "ok" else (None, {"ok": False, "error": "nope"})
        web.files_mod.resolve_download = lambda s, p: (self.f, None) if p == "r.md" else ("", "not_found")

    def tearDown(self):
        web._files_resolve = self._res
        web.files_mod.resolve_download = self._rd

    def test_ticket_issued_with_cookie_and_no_token_in_url(self):
        h = FakeH(json.dumps({"name": "ok", "path": "r.md"}).encode())
        web._Handler._files_ticket(h)
        self.assertEqual(h.status, 200)
        out = json.loads(h.wfile.getvalue())
        self.assertTrue(out["url"].startswith("/readfile/") and out["url"].endswith("/r.md"))
        self.assertNotIn(TOKEN, out["url"])
        tk = out["url"].split("/")[2]
        self.assertEqual(rt.verify(TOKEN, tk), {"name": "ok", "path": "r.md", "host": "local"})
        self.assertTrue(ext.cookie_ok(h.sent["Set-Cookie"].split(";")[0], TOKEN))

    def test_missing_file_gets_no_ticket(self):
        h = FakeH(json.dumps({"name": "ok", "path": "nope.md"}).encode())
        web._Handler._files_ticket(h)
        self.assertEqual(h.status, 404)
        h = FakeH(json.dumps({"name": "zzz", "path": "r.md"}).encode())
        web._Handler._files_ticket(h)
        self.assertNotEqual(h.status, 200)

    def test_bad_input(self):
        for body in (b"", b"[]", b"{}", json.dumps({"name": "ok"}).encode()):
            h = FakeH(body)
            web._Handler._files_ticket(h)
            self.assertEqual(h.status, 400)
        h = FakeH(b"x" * 9000)
        web._Handler._files_ticket(h)
        self.assertEqual(h.status, 400)

    def test_download_in_ticket_mode_is_inline_sandboxed(self):
        h = FakeH(path="/readfile/x/r.md")
        h._json = lambda o, status=200: None
        web._Handler._handle_files_download(h, params={"name": "ok", "path": "r.md", "host": "local"})
        self.assertEqual(h.status, 200)
        self.assertEqual(h.wfile.getvalue(), b"# x")
        self.assertEqual(h.sent["Content-Security-Policy"], "sandbox")
        self.assertTrue(h.sent["Content-Type"].startswith("text/plain"))
        self.assertEqual(h.sent["Content-Disposition"], "inline")

    ISPARTA = os.path.expanduser("~/work/academic/yeterlilik2/belge/backups/isparta/isparta")

    def test_real_isparta_images_via_ticket_dir_scope(self):
        """Gerçek isparta belge dizini: bilet ek_matris.tex için, /readfile/<bilet>/Bronze-age-collapse.png|svg gerçek resmi inline verir."""
        if not os.path.isfile(os.path.join(self.ISPARTA, "Bronze-age-collapse.png")):
            self.skipTest("isparta dizini yok")
        doc = os.path.join(self.ISPARTA, "ek_matris.tex")
        web.files_mod.resolve_download = lambda s, p: (p, None) if os.path.isfile(p) else ("", "not_found")
        tk = {"name": "ok", "path": doc, "host": "local"}
        for img, ctype in (("Bronze-age-collapse.png", "image/png"), ("Bronze-age-collapse.svg", "image/svg")):
            tgt = rt.resolve_url_path(doc, img)
            self.assertEqual(tgt, os.path.join(self.ISPARTA, img))
            h = FakeH(path="/readfile/x/" + img)
            h._json = lambda o, status=200: None
            web._Handler._handle_files_download(h, params=dict(tk, path=tgt, img="1"))
            self.assertEqual(h.status, 200)
            self.assertTrue(h.sent["Content-Type"].startswith(ctype), h.sent["Content-Type"])
            self.assertEqual(h.wfile.getvalue(), open(tgt, "rb").read())
        self.assertIsNone(rt.resolve_url_path(doc, "main.aux"))
        self.assertIsNone(rt.resolve_url_path(doc, "../x.png"))


class HttpLevel(unittest.TestCase):
    """Gerçek ThreadingHTTPServer üzerinde `/readfile/<bilet>/<yol>`: belge 200 text/plain, resim 200 image/*, `..`/.txt/uzantısız 404, bozuk bilet 404."""
    PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452")

    def setUp(self):
        import http.server
        import threading
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "figs"))
        self.doc = os.path.join(self.d, "doc.tex")
        open(self.doc, "w").write("\\includegraphics{figs/a.png}")
        open(os.path.join(self.d, "figs", "a.png"), "wb").write(self.PNG)
        open(os.path.join(self.d, "figs", "n.txt"), "w").write("gizli")
        open(os.path.join(os.path.dirname(self.d), "out.png"), "wb").write(self.PNG)
        self._res, self._rd = web._files_resolve, web.files_mod.resolve_download
        web._files_resolve = lambda name, lang: ((self.d, None), None)
        web.files_mod.resolve_download = lambda s, p: (p, None) if os.path.isfile(p) else ("", "not_found")
        self._tok = getattr(web._Handler, "token", None)
        web._Handler.token = TOKEN
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.tk = rt.issue(TOKEN, "ok", self.doc, "local")

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        web._files_resolve, web.files_mod.resolve_download = self._res, self._rd
        web._Handler.token = self._tok

    def get(self, rest, tk=None):
        import http.client
        c = http.client.HTTPConnection(*self.srv.server_address, timeout=5)
        c.request("GET", f"/readfile/{tk or self.tk}/{rest}")
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, r.getheader("Content-Type") or "", body

    def test_document_and_image(self):
        st, ct, body = self.get("doc.tex")
        self.assertEqual(st, 200)
        self.assertTrue(ct.startswith("text/plain"), ct)
        st, ct, body = self.get("figs/a.png")
        self.assertEqual((st, ct, body), (200, "image/png", self.PNG))

    def test_traversal_wrong_ext_and_bad_ticket_404(self):
        for rest in ("figs/n.txt", "../out.png", "%2e%2e/out.png", "figs/yok.png", "figs//a.png", "figs%5Ca.png", "doc.tex.png"):
            self.assertEqual(self.get(rest)[0], 404, rest)
        self.assertEqual(self.get("doc.tex", tk="bozuk.bilet")[0], 404)
        self.assertEqual(self.get("figs/a.png", tk=rt.issue("baska", "ok", self.doc, "local"))[0], 404)


if __name__ == "__main__":
    unittest.main()
