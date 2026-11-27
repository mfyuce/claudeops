"""İzlenen (CANLI) panel derlemesine her paket TEK kopya girer. 27 Kas: `ae36d07a` derlemesinde React iki ayrı
`node_modules`tan paketlendi; `tsc` ve `vite build` geçti, panel boş sayfa açtı (`useState` of null)."""
import json
import unittest
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "webui" / "dist" / "assets"


class DistSingleCopyTests(unittest.TestCase):
    def test_every_bundled_package_file_comes_from_one_node_modules(self):
        maps = sorted(ASSETS.glob("*.js.map"))
        self.assertTrue(maps, "dist kaynak haritası yok")
        origins: dict[str, set[str]] = {}
        for path in maps:
            for source in json.loads(path.read_text(encoding="utf-8"))["sources"]:
                prefix, sep, inside = source.rpartition("node_modules/")
                if sep:
                    origins.setdefault(inside, set()).add(prefix)
        self.assertIn("react/cjs/react.production.js", origins)
        self.assertEqual({k: sorted(v) for k, v in origins.items() if len(v) > 1}, {})


if __name__ == "__main__":
    unittest.main()
