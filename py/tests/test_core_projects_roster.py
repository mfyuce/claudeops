"""core_projects: değnekçi kümesinde olmayan roster projeleri de klasörüyle gelir (okuma listesi TBD taraması, 19 Kas teşhisi)."""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops import extensions as ext  # noqa: E402
from claudeops.roster import RosterEntry  # noqa: E402


class T(unittest.TestCase):
    def test_roster_projects_included_with_cwd(self):
        proj = mock.Mock(host="")
        remote = mock.Mock(host="ulak_31")
        with mock.patch("claudeops.steward.load_projects", return_value={"a": proj, "r": remote}), \
             mock.patch("claudeops.commands.web_steward._cwd_resolver", return_value=lambda n: {"a": "/live/a"}.get(n, "")), \
             mock.patch("claudeops.roster.read_roster", return_value=[RosterEntry("a", "/ros/a", "m"), RosterEntry("b", "/ros/b", "m"), RosterEntry("r", "/ros/r", "m")]):
            got = {p["name"]: p["cwd"] for p in ext.core_projects()}
        self.assertEqual(got, {"a": "/live/a", "b": "/ros/b", "r": ""})   # a: canlı kayıt önde; b: yalnız roster; r: uzak = ""


if __name__ == "__main__":
    unittest.main()
