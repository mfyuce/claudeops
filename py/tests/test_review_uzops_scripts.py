"""review uzops R-25/R-26/R-27: kabuk betikleri (sahte curl/sudo/logger/sleep/id ile)."""
import os, stat, subprocess, tempfile, unittest

DATA = os.path.join(os.path.dirname(__file__), "..", "claudeops", "data")
SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..", "scripts")


def _stub(d, name, body):
    p = os.path.join(d, name)
    with open(p, "w") as f:
        f.write("#!/bin/bash\n" + body + "\n")
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)


class Scripts(unittest.TestCase):
    def _resume(self, curl_body):
        with tempfile.TemporaryDirectory() as d:
            _stub(d, "curl", curl_body)
            _stub(d, "sleep", "exit 0")
            _stub(d, "id", "echo 1000")
            _stub(d, "cat", "echo https://x.trycloudflare.com")
            _stub(d, "logger", 'echo "LOG $*" >> "%s/log"' % d)
            _stub(d, "sudo", 'echo "SUDO $*" >> "%s/log"' % d)
            env = dict(os.environ, PATH=d + ":" + os.environ["PATH"])
            subprocess.run(["bash", os.path.join(DATA, "tunnel-resume-check.sh"), "post"], env=env, check=True, timeout=20)
            try:
                return open(os.path.join(d, "log")).read()
            except FileNotFoundError:
                return ""

    def test_resume_hook_treats_530_as_dead(self):
        log = self._resume("printf 530; exit 0")
        self.assertIn("SUDO", log)
        self.assertIn("restarting", log)

    def test_resume_hook_keeps_healthy_401(self):
        log = self._resume("printf 401; exit 0")
        self.assertNotIn("SUDO", log)
        self.assertIn("no action", log)

    def test_resume_hook_connect_failure_dead(self):
        self.assertIn("SUDO", self._resume("printf 000; exit 6"))

    def test_run_tunnel_state_dir_honours_claudeops_dir(self):
        src = open(os.path.join(DATA, "run-tunnel.sh")).read()
        self.assertIn('STATE_DIR="${CLAUDEOPS_DIR:-$HOME/.claude/claudeops}"', src)

    def test_provision_root_prints_runuser(self):
        src = open(os.path.join(SCRIPTS, "provision-user.sh")).read()
        self.assertIn("runuser -l $NEW_USER", src)
        self.assertIn('if [ -n "$SUDO" ]; then\n    echo "  $SUDO -iu', src)   # sudo dalı korundu, root dalı ayrı


if __name__ == "__main__":
    unittest.main()
