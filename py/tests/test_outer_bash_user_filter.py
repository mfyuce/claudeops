"""TBD#366 P7: `find_outer_bash_pids`in yedek taraması (istemci listesi boşken tüm süreçlerin `bash -c` betiği)
kullanıcıya göre süzmüyordu: çok kullanıcılı makinede başka kullanıcının aynı adlı penceresi listeye girer (ve
kapatma yolu ona dokunmaya çalışırdı). Yalnız bu sürecin gerçek kullanıcısına (`os.getuid()`) ait süreçler sayılır."""
import os
import shlex
import subprocess
import time
import unittest
import uuid
from unittest import mock

from claudeops import tmux_backend as tb


class FallbackScanUserTests(unittest.TestCase):
    def setUp(self):
        self.name = "cxpy-p7-" + uuid.uuid4().hex[:8]
        script = f"cat # -s {shlex.quote(self.name)} -c /x\ntrue"
        self.proc = subprocess.Popen(["bash", "-c", script], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
        self.addCleanup(self._stop)
        # İstemci listesi yok (canlı sokete hiç gidilmez): yalnız yedek tarama.
        p = mock.patch.object(tb, "_outer_bash_via_list_clients", lambda name: [])
        p.start()
        self.addCleanup(p.stop)

    def _stop(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)

    def scan(self):
        end = time.time() + 10
        while time.time() < end:
            found = tb.find_outer_bash_pids(self.name)
            if found:
                return found
            time.sleep(0.05)
        return []

    def test_own_window_is_found(self):
        self.assertEqual([pid for pid, _ in self.scan()], [self.proc.pid])

    def test_another_users_window_with_the_same_name_is_not(self):
        self.assertTrue(self.scan())       # süreç hazır
        other = os.getuid() + 4242
        with mock.patch.object(tb.os, "getuid", lambda: other):
            self.assertEqual(tb.find_outer_bash_pids(self.name), [])


if __name__ == "__main__":
    unittest.main()
