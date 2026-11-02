"""TBD#65: web.py do_POST izinli yol listesi ile web_hosts.HOST_ROUTED_PATHS arasındaki küme farkı denetimi.

- Her host-routed yol do_POST allowlist'inde olmalı (yoksa 404'e düşer, proxy'ye hiç ulaşmaz).
- Allowlist'te olup host-routed OLMAYAN yollar `KNOWN_LOCAL_ONLY`'de açıkça listelenmeli: yeni bir POST yolu eklenince
  bilinçli karar gerekir (host-routed mı, yerel-only mi); yerel-only ise bu listeye eklenir.
- `KNOWN_LOCAL_ONLY` içinde allowlist'ten düşmüş eski kayıt kalmamalı.

Çalıştırma:  python3 py/tests/test_post_routes_vs_host_routed.py -v
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web_hosts  # noqa: E402

WEB_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claudeops", "commands", "web.py")

# Bilerek yerel-only (HOST_ROUTED_PATHS'a EKLENMEZ); gerekçeler web.py yorumlarında.
KNOWN_LOCAL_ONLY = {
    "/api/layout", "/api/term/mirror-window", "/api/settings", "/api/usage",
    "/api/diag/spawn-test", "/api/diag/restart-gt", "/api/diag/ask", "/api/io/ask",
    "/api/desktop/start", "/api/desktop/stop", "/api/files/validate", "/api/vscode/open",
    "/api/hosts", "/api/hosts/remove", "/api/hosts/test",
    "/api/orch/start", "/api/orch/cancel", "/api/orch/draft", "/api/orch/result",
    "/api/snapshot/save", "/api/snapshot/resume", "/api/snapshot/list",
    "/v1/chat/completions",
}


def _post_allowlist() -> set:
    src = open(WEB_PY, encoding="utf-8").read()
    start = src.index("    def do_POST(self):")
    m = re.search(r'path not in \((.*?)\):\n\s+self\._json\(\{"error": "not found"\}', src[start:], re.S)
    assert m, "do_POST allowlist bulunamadı (web.py yapısı değişti: testi güncelle)"
    return set(re.findall(r'"(/[^"]+)"', m.group(1)))


class PostRoutesVsHostRouted(unittest.TestCase):
    def test_allowlist_parsed(self):
        al = _post_allowlist()
        self.assertGreater(len(al), 30)
        self.assertIn("/api/start", al)

    def test_every_host_routed_path_is_in_post_allowlist(self):
        missing = web_hosts.HOST_ROUTED_PATHS - _post_allowlist()
        self.assertEqual(missing, set(), f"host-routed ama do_POST allowlist'inde yok: {sorted(missing)}")

    def test_unrouted_post_paths_are_explicit_exceptions(self):
        unrouted = _post_allowlist() - web_hosts.HOST_ROUTED_PATHS
        new = unrouted - KNOWN_LOCAL_ONLY
        self.assertEqual(new, set(),
                         f"host-routed değil ve KNOWN_LOCAL_ONLY'de yok (karar ver: HOST_ROUTED_PATHS ya da listeye ekle): {sorted(new)}")

    def test_known_local_only_has_no_stale_entries(self):
        al = _post_allowlist()
        stale = KNOWN_LOCAL_ONLY - al
        self.assertEqual(stale, set(), f"KNOWN_LOCAL_ONLY'de allowlist'te olmayan kayıt: {sorted(stale)}")
        overlap = KNOWN_LOCAL_ONLY & web_hosts.HOST_ROUTED_PATHS
        self.assertEqual(overlap, set(), f"hem yerel-only hem host-routed: {sorted(overlap)}")


if __name__ == "__main__":
    unittest.main()
