"""OPS-03: bash `claudeops` guard.lock'u symlink'i izleyip hedefi truncate etmemeli (Python guard_lock ile aynı güvenlik + aynı yol)."""
import os
import re
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "claudeops")


def _func():
    src = open(SCRIPT, encoding="utf-8").read()
    m = re.search(r"^guard_lock_fd9\(\) \{.*?^\}\n", src, re.S | re.M)
    return m.group(0) if m else ""


class BashGuardLockTest(unittest.TestCase):
    def run_fn(self, lockdir):
        code = f'GUARD_LOCK_DIR="{lockdir}"\n{_func()}\nguard_lock_fd9; echo rc=$?'
        return subprocess.run(["bash", "-c", code], capture_output=True, text=True, timeout=20)

    def test_function_exists_and_creates_lock(self):
        with tempfile.TemporaryDirectory() as d:
            ld = os.path.join(d, "l")
            r = self.run_fn(ld)
            self.assertIn("rc=0", r.stdout, r.stderr)
            self.assertTrue(os.path.isfile(os.path.join(ld, "guard.lock")))

    def test_symlinked_lock_is_refused_and_target_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            ld = os.path.join(d, "l")
            os.makedirs(ld)
            victim = os.path.join(d, "victim")
            open(victim, "w").write("KEEP")
            os.symlink(victim, os.path.join(ld, "guard.lock"))
            r = self.run_fn(ld)
            self.assertNotIn("rc=0", r.stdout)
            self.assertEqual(open(victim).read(), "KEEP")

    def test_symlinked_dir_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            real = os.path.join(d, "real")
            os.makedirs(real)
            ld = os.path.join(d, "l")
            os.symlink(real, ld)
            r = self.run_fn(ld)
            self.assertNotIn("rc=0", r.stdout)

    def test_script_uses_helper_not_raw_exec(self):
        src = open(SCRIPT, encoding="utf-8").read()
        self.assertNotIn('exec 9>"$LOG_DIR/guard.lock"', src)
