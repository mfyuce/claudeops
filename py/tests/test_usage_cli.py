"""`py/cops usage` CLI + `/api/status` `usage_total` alanı. Gerçek transkriptlere DOKUNMAZ (geçici dizin, jsonl_path_for yamalı)."""
import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import session_usage as su  # noqa: E402
from claudeops.commands import usage as usage_cmd  # noqa: E402
from claudeops.commands import web  # noqa: E402
from claudeops.commands import web_hosts  # noqa: E402
from claudeops.session import Session  # noqa: E402


def _row(mid, model="claude-sonnet-5-5", i=10, cw=100, cr=1000, out=5):
    return json.dumps({"type": "assistant", "uuid": f"u{mid}", "requestId": f"r{mid}",
                       "message": {"id": mid, "model": model, "usage": {
                           "input_tokens": i, "cache_creation_input_tokens": cw,
                           "cache_read_input_tokens": cr, "output_tokens": out}}}) + "\n"


class Base(unittest.TestCase):
    def setUp(self):
        su._files.clear()
        su._summaries.clear()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths = {}
        for name, n in (("big", 3), ("small", 1)):
            p = os.path.join(tmp.name, f"{name}.jsonl")
            with open(p, "w") as f:
                for k in range(n):
                    f.write(_row(f"{name}{k}", cr=1_000_000))
            self.paths[name] = p
        os.makedirs(os.path.join(tmp.name, "big", "subagents"))
        with open(os.path.join(tmp.name, "big", "subagents", "agent-1.jsonl"), "w") as f:
            f.write(_row("sub1", i=5, cw=0, cr=0, out=7))
        self.sessions = [Session(name="small", pid=1, cwd="/w/s", sid="small", cli="claude"),
                         Session(name="big", pid=2, cwd="/w/b", sid="big", cli="claude"),
                         Session(name="cx", pid=3, cwd="/w/c", sid="cx", cli="codex")]


class UsageCliTests(Base):
    def run_cli(self, *argv):
        ns = argparse.Namespace(names=[a for a in argv if not a.startswith("--")], json="--json" in argv, top=15)
        buf = io.StringIO()
        with mock.patch.object(usage_cmd, "find_sessions", lambda measure_cpu=False: self.sessions), \
                mock.patch.object(usage_cmd, "jsonl_path_for", lambda cwd, sid: self.paths.get(sid)), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(usage_cmd.run(ns), 0)
        return buf.getvalue()

    def test_table_sorted_by_spend_and_skips_non_claude(self):
        out = self.run_cli()
        self.assertLess(out.index("big"), out.index("small"))
        self.assertNotIn("cx ", out)
        self.assertIn("3.00M", out)          # big: 3 tur x 1M önbellek okuma
        self.assertIn("2 oturum", out)

    def test_json_and_name_filter(self):
        data = json.loads(self.run_cli("small", "--json"))
        self.assertEqual(list(data), ["small"])
        self.assertEqual(data["small"]["cache_read"], 1_000_000)
        big = json.loads(self.run_cli("big", "--json"))["big"]
        self.assertEqual((big["turns"], big["subagents"]["n"], big["subagents"]["out"]), (3, 1, 7))

    def test_command_is_registered(self):
        from claudeops import cli
        self.assertIn(usage_cmd, cli.COMMANDS)


class StatusUsageTotalTests(Base):
    def test_status_rows_carry_usage_total_without_blocking(self):
        live = [self.sessions[1], self.sessions[2]]
        fleet = {"big": {"cwd": "/w/b", "model": "sonnet", "cli": "claude", "state": "active"}}
        patches = (
            mock.patch.object(web, "find_sessions", lambda measure_cpu=True, mirrors_out=None: live),
            mock.patch.object(web, "_fleet_status", lambda: fleet),
            mock.patch.object(web, "PROVIDERS", {}),
            mock.patch.object(web, "is_tmux_backed", lambda pid: False),
            mock.patch.object(web, "_needs_ho_cached", lambda s: None),
            mock.patch.object(web, "_live_usage", lambda s: {"prompt_tokens": 1}),   # ucli `usage` bozulmasın
            mock.patch.object(web, "_cache_info_cached", lambda s: None),
            mock.patch.object(web, "_context_info_cached", lambda s: None),
            mock.patch.object(web, "jsonl_path_for", lambda cwd, sid: self.paths.get(sid)),
            mock.patch.object(web.inst_mod, "load_instances", lambda: {}),
            mock.patch.object(web_hosts.hosts_mod, "load_hosts", lambda: []),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        def rows():
            return {r["name"]: r for r in web._status_payload()["sessions"] if r["host"] == web.LOCAL_HOST_NAME}

        first = rows()
        self.assertIsNone(first["big"]["usage_total"])       # ilk çağrı beklemez: arka plan başladı
        deadline, got = time.time() + 5, None
        while got is None and time.time() < deadline:
            time.sleep(0.02)
            got = rows()["big"]["usage_total"]
        self.assertEqual((got["turns"], got["cache_read"], got["subagents"]["n"]), (3, 3_000_000, 1))
        self.assertIn("sonnet", got["by_family"])
        r = rows()
        self.assertEqual(r["big"]["usage"], {"prompt_tokens": 1})
        self.assertIsNone(r["cx"]["usage_total"])             # claude olmayan satır: bilinmiyor


if __name__ == "__main__":
    unittest.main()
