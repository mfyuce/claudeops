"""Review 25 Kas: erken biten uzak yükleme gövdesi hata verir; eşzamanlı new-chat aynı adı seçmez."""
import contextlib
import io
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web, web_hosts  # noqa: E402


class BoundedReader(unittest.TestCase):
    def test_full_body(self):
        r = web_hosts._BoundedReader(io.BytesIO(b"abcd-fazlasi"), 4)
        self.assertEqual((r.read(8192), r.read(8192)), (b"abcd", b""))

    def test_early_eof_raises(self):
        r = web_hosts._BoundedReader(io.BytesIO(b"ab"), 4)
        self.assertEqual(r.read(8192), b"ab")
        with self.assertRaises(OSError):
            r.read(8192)


class NewChatNames(unittest.TestCase):
    def test_concurrent_calls_get_distinct_names(self):
        taken = []

        def name(prefix):
            n = len(taken)
            time.sleep(0.05)          # ad seçimi ile kayıt arasındaki pencere
            return f"{prefix}_{n}"

        prov = mock.Mock(accepts_cli_opts=False)
        with mock.patch.object(web, "_new_chat_source", lambda b, f: ("bp", "p", "/tmp", "claude", "m")), \
                mock.patch.object(web, "_fleet_status", lambda: {}), \
                mock.patch.object(web, "_generate_new_chat_name", name), \
                mock.patch.object(web, "get_provider", lambda c: prov), \
                mock.patch.object(web, "resolved_model_for", lambda p, m: m), \
                mock.patch.object(web, "default_effort_for", lambda p: "medium"), \
                mock.patch.object(web.inst_mod, "record_instance", lambda n, **kw: taken.append(n)), \
                mock.patch.object(web, "guard_lock", lambda timeout=None: contextlib.nullcontext()), \
                mock.patch.object(web, "detect_display", lambda: ""), \
                mock.patch.object(web, "spawn_session", lambda **kw: "new"), \
                mock.patch.object(web, "_wait_stable", lambda n, timeout=0: True):
            ts = [threading.Thread(target=web._new_chat, args=("p",)) for _ in range(2)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(10)
        self.assertEqual(sorted(taken), ["p_0", "p_1"])


if __name__ == "__main__":
    unittest.main()
