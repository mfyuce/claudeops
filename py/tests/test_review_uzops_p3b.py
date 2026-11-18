"""review uzops R-12/R-18/R-19/R-15: diag.log sınırı+kuyruk, push tüketici erken stop, endpoint değişimi."""
import os, sys, tempfile, threading, time, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import diaglog
from claudeops.commands import web_hosts


class P3b(unittest.TestCase):
    def test_diag_log_rotates_and_tail_reads_window(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "diag.log")
            with mock.patch.object(diaglog, "diag_log_path", return_value=p), mock.patch.object(diaglog, "MAX_BYTES", 2000):
                for i in range(100):
                    diaglog.diag_log("e", i=i, pad="x" * 50)
                self.assertTrue(os.path.exists(p + ".1"))
                self.assertLess(os.path.getsize(p), 4000)
                tail = diaglog.diag_log_tail(5)
                self.assertEqual(len(tail), 5)
                self.assertIn('"i": 99', tail[-1])

    def test_stop_before_connect_closes_call(self):
        gate = threading.Event()
        closed = []

        class Call:
            def __iter__(self): return iter([])
            def close(self): closed.append(1)

        def make_call():
            gate.wait(2)
            return Call()
        c = web_hosts._PushConsumer("ws", make_call, lambda r: None, lambda i: None, label="t")
        c.stop()           # make_call henüz dönmedi
        gate.set()
        c._thread.join(3)
        self.assertEqual(closed, [1])
        self.assertFalse(c.is_alive())

    def test_status_consumer_replaced_when_endpoint_changes(self):
        made = []

        class Fake:
            tier = "ws"; has_data = True
            def __init__(self): self.stopped = False
            def is_alive(self): return not self.stopped
            def silent_seconds(self): return 0
            def stop(self): self.stopped = True

        def start(host, tier):
            f = Fake(); made.append(f); return f
        h = {"name": "h1", "token": "t", "base_url": "http://a", "grpc_url": ""}
        with mock.patch.object(web_hosts, "get_tier", return_value="ws"), mock.patch.object(web_hosts, "_start_status_consumer", side_effect=start):
            web_hosts._status_consumers.clear()
            web_hosts._ensure_status_consumer(h)
            web_hosts._ensure_status_consumer(h)
            self.assertEqual(len(made), 1)
            web_hosts._ensure_status_consumer(dict(h, base_url="http://b"))
            self.assertEqual(len(made), 2)
            self.assertTrue(made[0].stopped)
            web_hosts._status_consumers.clear()


if __name__ == "__main__":
    unittest.main()
