"""İzlenen (CANLI) panel derlemesi başsız Chrome'da gerçekten çizilmeli. 27 Kas: `dist` iki React kopyasıyla
paketlendi; Python testleri, `cops check` ve 401 yoklaması geçti, panel boş sayfa açtı (hiçbiri JS'i koşmuyordu).

`dist` yerel bir sunucudan verilir (`/api/*` 401 döner, panel 'token eksik' ekranını çizer); `#root` dolu olmalı ve
konsolda yakalanmamış JS hatası olmamalı. İkinci yol token sonrası ekran: gerçek `web._Handler` süreç içinde
(test altında durum dizini geçici, `paths.py`), ilk durum `/ws` bağlanınca gelir, oturum listesi çizilir; sayfanın
`/api/ws-ticket` dışındaki POST'ları reddedilir (yüklenirken canlı oturuma eylem gitmesin). Chrome yoksa
(`CLAUDEOPS_CHROME` ya da PATH) atlanır."""
import functools
import http.server
import os
import re
import shutil
import subprocess
import tempfile
import threading
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web  # noqa: E402

DIST = Path(__file__).resolve().parents[1] / "webui" / "dist"
CHROME = os.environ.get("CLAUDEOPS_CHROME") or next(
    (p for p in map(shutil.which, ("google-chrome", "chromium", "chromium-browser")) if p), None
)


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/api/"):
            body = b'{"error": "unauthorized"}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.path.startswith("/assets/") and self.path != "/favicon.svg":
            self.path = "/index.html"
        super().do_GET()

    do_POST = do_GET


def _chrome_dom(url: str) -> tuple[str, list[str]]:
    """Başsız Chrome'da açar; (#root iç HTML'i, yakalanmamış JS hata satırları) döner."""
    with tempfile.TemporaryDirectory(prefix="cops-dist-chrome-") as prof:
        out = subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
             f"--user-data-dir={prof}", "--enable-logging=stderr", "--v=0", "--virtual-time-budget=20000",
             "--dump-dom", url],
            capture_output=True, text=True, timeout=120,
        )
    m = re.search(r'<div id="root">(.*)</body>', out.stdout, re.S)
    root = m.group(1).strip() if m else ""
    errors = [ln for ln in out.stderr.splitlines() if "CONSOLE" in ln and "Uncaught" in ln]
    return root, errors


def render(dist: Path) -> tuple[str, list[str]]:
    """`dist`i sunar (/api/* 401), başsız Chrome'da açar."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Handler, directory=str(dist)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        return _chrome_dom(f"http://127.0.0.1:{srv.server_address[1]}/")
    finally:
        srv.shutdown()
        srv.server_close()


@unittest.skipUnless(CHROME, "Chrome yok")
class DistRendersTests(unittest.TestCase):
    def test_tracked_dist_renders_without_js_errors(self):
        root, errors = render(DIST)
        self.assertEqual(errors, [])
        self.assertTrue(root.startswith("<div"), f"#root boş: {root[:200]!r}")

    def test_broken_bundle_is_caught(self):
        # Kapının kendisi: başta hata atan paket boş #root ve yakalanmamış hata olarak görünmeli.
        with tempfile.TemporaryDirectory(prefix="cops-dist-bad-") as tmp:
            bad = Path(tmp) / "dist"
            shutil.copytree(DIST, bad)
            for js in (bad / "assets").glob("index-*.js"):
                js.write_text('throw new Error("KIRIK_PAKET");' + js.read_text(encoding="utf-8"), encoding="utf-8")
            root, errors = render(bad)
        self.assertTrue(any("KIRIK_PAKET" in e for e in errors), errors)
        self.assertFalse(root.startswith("<div"), root[:200])


@unittest.skipUnless(CHROME, "Chrome yok")
class DistRendersWithStatusTests(unittest.TestCase):
    def test_token_screen_renders_status_without_js_errors(self):
        posts: list[str] = []
        real_post = web._Handler.do_POST

        def guarded_post(handler):
            if handler.path.split("?")[0] == "/api/ws-ticket":
                return real_post(handler)
            posts.append(handler.path)
            handler._json({"error": "test: POST kapalı"}, status=403)

        with mock.patch.object(web._Handler, "token", "tok"), \
                mock.patch.object(web._Handler, "do_POST", guarded_post):
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                root, errors = _chrome_dom(f"http://127.0.0.1:{srv.server_address[1]}/?token=tok")
            finally:
                srv.shutdown()
                srv.server_close()
        self.assertEqual(errors, [])
        self.assertEqual(posts, [], "sayfa yüklenirken beklenmeyen POST")
        # Sekmeler yalnız ilk durum (WS) gelince dolar; 401 ve "Yükleniyor" ekranında boş kalır.
        self.assertIn('<div class="tabs"><button', root, root[:600])


if __name__ == "__main__":
    unittest.main()
