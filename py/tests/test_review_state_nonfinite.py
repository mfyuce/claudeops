"""GET review durum ve bulgu yanıtları geçerli JSON olmalı: depodaki NaN/Infinity yanıttan atılır ve loglanır (TBD#383 kuralı)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_web_review_tick import _Tick, NOW  # noqa: E402
from claudeops import review  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402


def _strict(obj):
    def _reject(name):
        raise ValueError(name)
    return json.loads(json.dumps(obj), parse_constant=_reject)


class FindingsNonFiniteTest(unittest.TestCase):
    def setUp(self):
        getattr(review, "_BAD_SEEN", set()).clear()
        p = mock.patch.object(review, "diag_log", create=True)
        self.log = p.start()
        self.addCleanup(p.stop)

    def test_list_findings_drops_non_finite_values(self):
        data = {"a": {"project": "p", "state": "new", "verify_sent_at": float("nan"), "line": 3,
                      "extra": {"x": float("inf"), "ys": [1.0, float("-inf")]}}}
        with mock.patch.object(wr.rv, "load_findings", return_value=data), \
                mock.patch.object(wr.sw, "paths_for"):
            out = wr.list_findings(mock.Mock(sid="default"))
        row = _strict(out)["findings"][0]
        self.assertEqual(row, {"id": "a", "project": "p", "state": "new", "line": 3, "extra": {"ys": [1.0, None]}})
        self.assertEqual({c.kwargs.get("what") for c in self.log.call_args_list}, {"view.nonfinite"})


class StateNonFiniteTest(_Tick):
    def test_review_state_is_strict_json_with_non_finite_run_records(self):
        self.own("a")
        paths = wr.sw.paths_for(self.cfg().sid)
        review.save_history(paths, {"pairs": {}, "runs": [{"project": "a", "seconds": float("inf")}]})
        out = wr.review_state(self.cfg(), now=NOW)
        self.assertEqual(_strict(out)["runs"], [{"project": "a"}])


if __name__ == "__main__":
    unittest.main()
