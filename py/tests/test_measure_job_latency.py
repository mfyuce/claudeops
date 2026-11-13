"""scripts/measure_job_latency.py: --log/--since/--until/-n ayrıştırma + aşama hesabı (13 Kas: --since ValueError veriyordu)."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

_P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts", "measure_job_latency.py")
_spec = importlib.util.spec_from_file_location("measure_job_latency", _P)
mjl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mjl)


def _log(rows):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for r in rows:
        f.write(json.dumps(r) + "\n")
    f.close()
    return f.name


def _job(jid, t0, proj="p"):
    d = lambda s: f"2026-11-13T20:{(t0 + s) // 60:02d}:{(t0 + s) % 60:02d}"   # noqa: E731
    return [{"ts": d(0), "event": "action", "kind": "ask_user", "name": proj, "reason": "STEWARD-JOB"},
            {"ts": d(10), "event": "job_submit", "service": "v", "id": jid, "project": proj, "kind": "sql_readonly"},
            {"ts": d(14), "event": "job_state", "service": "v", "id": jid, "project": proj, "to": "done"},
            {"ts": d(30), "event": "job_delivered", "service": "v", "id": jid, "project": proj, "stage": "result"}]


class MeasureTest(unittest.TestCase):
    def test_stages(self):
        p = _log(_job(1, 0) + _job(2, 600))
        self.addCleanup(os.unlink, p)
        r = mjl.measure(mjl.load_events([p]), 40)
        self.assertEqual(r["isaret -> submit"][:2], (2, 10))
        self.assertEqual(r["submit -> done"][:2], (2, 4))
        self.assertEqual(r["done -> teslim"][:2], (2, 16))
        self.assertEqual(r["isaret -> teslim (uctan uca)"][:2], (2, 30))

    def test_since_until_and_cli(self):
        p = _log(_job(1, 0) + _job(2, 600))
        self.addCleanup(os.unlink, p)
        self.assertEqual(len(mjl.load_events([p], since="2026-11-13T20:05:00")), 4)
        self.assertEqual(len(mjl.load_events([p], until="2026-11-13T20:05:00")), 4)
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            mjl.main(["--log", p, "--since", "2026-11-13T20:05:00", "-n", "5"])      # eskiden ValueError
        self.assertIn("isaret -> submit", buf.getvalue())

    def test_multiple_logs_merged_in_time_order(self):
        a, b = _log(_job(1, 0)), _log(_job(2, 600))
        self.addCleanup(os.unlink, a)
        self.addCleanup(os.unlink, b)
        ev = mjl.load_events([b, a])
        self.assertEqual([e["ts"] for e in ev], sorted(e["ts"] for e in ev))


if __name__ == "__main__":
    unittest.main()
