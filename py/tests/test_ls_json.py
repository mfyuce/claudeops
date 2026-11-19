"""`cops list --json`: tablo/özet yok, geçerli JSON listesi."""
import argparse
import contextlib
import io
import json
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from claudeops.commands import ls


def _s(name, pid):
    return NS(name=name, pid=pid, model_short="son", cpu=1.26, is_fresh=True, cwd="/x", base=name)


class LsJson(unittest.TestCase):
    def run_ls(self, **kw):
        a = argparse.Namespace(no_cpu=True, base=None, json=False)
        for k, v in kw.items():
            setattr(a, k, v)
        buf = io.StringIO()
        with mock.patch.object(ls, "find_sessions", return_value=[_s("b", 2), _s("a", 1)]), contextlib.redirect_stdout(buf):
            rc = ls.run(a)
        return rc, buf.getvalue()

    def test_json_is_sorted_valid_and_has_no_table(self):
        rc, out = self.run_ls(json=True)
        self.assertEqual(rc, 0)
        d = json.loads(out)
        self.assertEqual([x["name"] for x in d], ["a", "b"])
        self.assertEqual(d[0], {"name": "a", "pid": 1, "model": "son", "cpu": 1.3, "kind": "fresh", "cwd": "/x"})

    def test_table_unchanged_without_flag(self):
        rc, out = self.run_ls()
        self.assertIn("NAME", out)
        self.assertIn("2 session", out)
