"""TBD#373 (7): ucli anahtar dosyasının yolu `$(cat …)` içinde tırnaklanır: boşluklu / tek tırnaklı HOME'da anahtar okunur.

Yollar içe aktarmada çözüldüğü için komut ayrı bir Python sürecinde (geçici HOME + CLAUDEOPS_DIR) kurulur ve `bash`le
GERÇEKTEN koşulur; `ucli` yerine ortamındaki anahtarı dosyaya yazan sahte betik. Gerçek HOME'a/docker'a dokunmaz."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

PY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
BUILD = ("from claudeops.providers import get_provider\n"
         "print(get_provider('ucli').build_inner_command({cwd!r}, 'm', 'read-only', 'medium', None, None, 's'))\n")


class KeyPathQuotingTest(unittest.TestCase):
    def test_key_is_read_from_home_with_space_and_quote(self):
        for name in ("duz", "a bosluk", "a b'c", 'd"e $(false) `x`'):
            with self.subTest(home=name), tempfile.TemporaryDirectory() as d:
                home = os.path.join(d, name)
                state = os.path.join(home, ".claude", "claudeops")
                os.makedirs(state)
                out = os.path.join(d, "anahtar.out")
                fake = os.path.join(d, "ucli")
                with open(fake, "w") as f:
                    f.write('#!/bin/sh\n[ "$2" = "--help" ] && exit 0\nprintf %s "$UCLI_API_KEY" > "$OUT"\n')
                os.chmod(fake, 0o755)
                with open(os.path.join(state, "settings.json"), "w") as f:
                    json.dump({"byok": {"ucli": {"UCLI_API_KEY": "gizli-anahtar"}}, "provider_bin": {"ucli": fake},
                               "ucli_web": {"search_docker": "off"}}, f)
                env = {"HOME": home, "CLAUDEOPS_DIR": state, "PATH": "/usr/bin:/bin", "PYTHONPATH": PY_DIR,
                       "CLAUDEOPS_EXTENSIONS": "off", "OUT": out}
                built = subprocess.run([sys.executable, "-c", BUILD.format(cwd=d)], env=env, cwd=d,
                                       capture_output=True, text=True, timeout=60)
                self.assertEqual(built.returncode, 0, built.stderr)
                cmd = built.stdout.strip()
                self.assertNotIn("gizli-anahtar", cmd)
                run = subprocess.run(["bash", "-c", cmd], env=env, cwd=d, capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, 0, run.stderr)
                with open(out) as f:
                    self.assertEqual(f.read(), "gizli-anahtar", run.stderr)


if __name__ == "__main__":
    unittest.main()
