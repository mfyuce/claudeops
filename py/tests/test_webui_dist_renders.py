"""İzlenen (CANLI) panel derlemesi başsız Chrome'da gerçekten çizilmeli. 27 Kas: `dist` iki React kopyasıyla
paketlendi; Python testleri, `cops check` ve 401 yoklaması geçti, panel boş sayfa açtı (hiçbiri JS'i koşmuyordu).

`dist` yerel bir sunucudan verilir (`/api/*` 401 döner, panel 'token eksik' ekranını çizer); `#root` dolu olmalı ve
konsolda yakalanmamış JS hatası olmamalı. Chrome yoksa (`CLAUDEOPS_CHROME` ya da PATH) atlanır."""
import functools
import http.server
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

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


def render(dist: Path) -> tuple[str, list[str]]:
    """`dist`i sunar, başsız Chrome'da açar; (#root iç HTML'i, yakalanmamış JS hata satırları) döner."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Handler, directory=str(dist)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="cops-dist-chrome-") as prof:
            out = subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
                 f"--user-data-dir={prof}", "--enable-logging=stderr", "--v=0", "--virtual-time-budget=8000",
                 "--dump-dom", f"http://127.0.0.1:{srv.server_address[1]}/"],
                capture_output=True, text=True, timeout=90,
            )
    finally:
        srv.shutdown()
        srv.server_close()
    m = re.search(r'<div id="root">(.*)</body>', out.stdout, re.S)
    root = m.group(1).strip() if m else ""
    errors = [ln for ln in out.stderr.splitlines() if "CONSOLE" in ln and "Uncaught" in ln]
    return root, errors


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


if __name__ == "__main__":
    unittest.main()
