"""TBD#264: /api/ucli/checks ve checks-mode uzak hosta yönlenir (GET query host, POST gövde host)."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops.commands import web_hosts  # noqa: E402

WEB = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claudeops", "commands", "web.py"), encoding="utf-8").read()


class Routing(unittest.TestCase):
    def test_sets(self):
        for p in ("/api/ucli/checks", "/api/ucli/checks-mode"):
            self.assertIn(p, web_hosts.HOST_ROUTED_PATHS)
            self.assertIn(p, web_hosts.GET_HOST_ROUTED_PATHS)

    def test_get_branches_proxy_when_host_given(self):
        for p in ('elif path == "/api/ucli/checks-mode":', 'elif path == "/api/ucli/checks":'):
            i = WEB.index(p)
            self.assertIn("web_hosts.proxy_get(path, _host", WEB[i:i + 900], p)

    def test_metrics_routed(self):
        for p in ("/api/ucli/metrics", "/api/ucli/metrics/sessions"):
            self.assertIn(p, web_hosts.GET_HOST_ROUTED_PATHS)
        i = WEB.index('elif path in ("/api/ucli/metrics", "/api/ucli/metrics/sessions"):')
        self.assertIn("web_hosts.proxy_get(path, _host", WEB[i:i + 900])

    def test_compare_routed(self):
        self.assertIn("/api/ucli/compare", web_hosts.GET_HOST_ROUTED_PATHS)
        i = WEB.index('elif path == "/api/ucli/compare":')
        self.assertIn("web_hosts.proxy_get(path, _host", WEB[i:i + 900])


if __name__ == "__main__":
    unittest.main()
