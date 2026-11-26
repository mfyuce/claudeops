"""TBD#373 (6): `spawn_session(dry_run=True)` yan etkisizdir (dosya yazmaz/silmez, `ucli mcp add`/docker koşturmaz, token
üretmez) ve komut satırı gerçek koşununkiyle AYNIDIR.

Her senaryo ayrı bir Python sürecinde, geçici HOME/CLAUDEOPS_DIR ve sahte ikililerle koşar (yollar içe aktarmada
çözülür). Süreç taraması sahtedir (tek bir sahte agy süreci), tmux/gnome gerçekten çağrılmaz."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

PY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

HELP = " ".join("--" + f for f in (
    "search-url allow-fetch request-timeout-secs max-history-kib effort stream metrics-file interactive state-dir with-mcp "
    "allow-agents usage-log provider ask-dir cache-ttl instructions-auto max-session-usd max-output-tokens").split())

SCRIPT = r'''
import json, os, sys
from unittest import mock
from claudeops import spawn, discovery, ucli_agents
from claudeops.providers.base import McpServerSpec

home, work, cli, opts = sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4])

class FakeProc:
    pid = 999999
    info = {"pid": 999999, "uids": type("U", (), {"real": os.getuid()})(),
            "cmdline": ["agy", "--conversation", "c0ffee"]}
    def cwd(self): return work
    def environ(self): return {"COPS_NAME": "komsu"}

def tree():
    out = {}
    for root in (home, work):
        for d, dirs, files in os.walk(root):
            for n in [""] + files:
                p = os.path.join(d, n) if n else d
                st = os.lstat(p)
                body = open(p, "rb").read().decode("latin-1") if n else None
                out[p] = [st.st_mode, st.st_ino, st.st_mtime_ns, body]
    return out

ucli_agents.set_panel_port(1)
spec = McpServerSpec(name="s", command="/bin/true", args=("x",), allowed_tools=("t",))
kw = dict(name="s1", cwd=work, model="m", display=":9", permission_mode="auto", effort="medium", cli=cli,
          mcp_server=spec, cli_opts=opts or None)
with mock.patch.object(discovery.psutil, "process_iter", return_value=[FakeProc()]), \
        mock.patch.object(discovery, "_sessions_from_json", return_value={}), \
        mock.patch.object(spawn, "DRY_RUN_PREVIEW_MAX", 10**6):
    before = tree()
    dry = spawn.spawn_session(dry_run=True, **kw)
    after = tree()
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
    calls = open(os.environ["CALLS"]).read() if os.path.exists(os.environ["CALLS"]) else ""
    inner = []
    with mock.patch.object(spawn, "tmux_available", return_value=True), \
            mock.patch.object(spawn, "_reclaim_ghost_session"), \
            mock.patch.object(spawn, "tmux_spawn_direct", side_effect=lambda n, c, i, e: inner.append(i) or True):
        spawn.spawn_session(hidden=True, **kw)
    real_changed = sorted(p for p, v in tree().items() if after.get(p) != v)
print(json.dumps({"changed": changed, "calls": calls, "dry": dry.split("cmd: ", 1)[1], "real": inner[0],
                  "real_changed": real_changed}))
'''


class DryRunPureTest(unittest.TestCase):
    def _run(self, cli, opts=None, settings=None, seed=()):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        home, work, bindir = (os.path.join(d.name, x) for x in ("home", "work", "bin"))
        state = os.path.join(home, ".claude", "claudeops")
        for p in (state, os.path.join(home, ".copilot"), os.path.join(work, ".ucli"), bindir):
            os.makedirs(p)
        calls = os.path.join(d.name, "calls.log")
        for name in ("claude", "agy", "codex", "copilot", "ucli", "docker"):
            with open(os.path.join(bindir, name), "w") as f:
                f.write('#!/bin/sh\ncase "$*" in *--help*) echo "%s"; exit 0;; esac\n'
                        'echo "%s $*" >> "$CALLS"\n%s\n' % (HELP, name, "exit 1" if name == "docker" else "exit 0"))
            os.chmod(os.path.join(bindir, name), 0o755)
        base = {"spawn_nice": "off", "routing_guidance_text": "yonerge",
                "provider_bin": {"ucli": os.path.join(bindir, "ucli")},
                "byok": {"ucli": {"UCLI_API_KEY": "k1", "ANTHROPIC_API_KEY": "k2"},
                         "copilot": {"COPILOT_PROVIDER_API_KEY": "k3"}}}
        base.update(settings or {})
        for n in seed:
            open(os.path.join(state, n), "w").close()
        for path, text in ((os.path.join(state, "settings.json"), json.dumps(base)),
                           (os.path.join(home, ".copilot", "config.json"), '{"trustedFolders": []}'),
                           (os.path.join(work, ".ucli", "mcp.json"), '{"eski": 1}')):
            with open(path, "w") as f:
                f.write(text)
        env = {"HOME": home, "CLAUDEOPS_DIR": state, "PATH": bindir + ":/usr/bin:/bin", "PYTHONPATH": PY_DIR,
               "CLAUDEOPS_EXTENSIONS": "off", "CALLS": calls, "PYTHONDONTWRITEBYTECODE": "1"}
        res = subprocess.run([sys.executable, "-c", SCRIPT, home, work, cli, json.dumps(opts or {})], env=env,
                             cwd=d.name, capture_output=True, text=True, timeout=90)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = json.loads(res.stdout.strip().splitlines()[-1])
        out["state"], out["home"], out["work"] = state, home, work
        return out

    def _assert_pure(self, out):
        self.assertEqual(out["changed"], [])
        self.assertNotIn("mcp add", out["calls"])
        self.assertNotIn("docker ", out["calls"])
        self.assertEqual(out["dry"], out["real"])

    def test_claude(self):
        out = self._run("claude")
        self._assert_pure(out)
        self.assertIn("--mcp-config", out["dry"])
        self.assertIn("--append-system-prompt-file", out["dry"])
        # gerçek koşu davranışı değişmedi: dosyalar yazılır
        self.assertIn(os.path.join(out["state"], "routing-guidance.md"), out["real_changed"])
        self.assertIn(os.path.join(out["state"], "orchestration", "mcp_config.json"), out["real_changed"])

    def test_copilot(self):
        out = self._run("copilot")
        self._assert_pure(out)
        self.assertIn("copilot_byok_env", out["dry"])
        self.assertIn(os.path.join(out["home"], ".copilot", "config.json"), out["real_changed"])

    def test_agy_and_codex(self):
        for cli in ("agy", "codex"):
            with self.subTest(cli=cli):
                self._assert_pure(self._run(cli))

    def test_ucli_default_service(self):
        out = self._run("ucli")
        self._assert_pure(out)
        for part in ("--with-mcp", "--metrics-file", "--allow-agents", "UCLI_AGENT_TOKEN", "ucli_api_key"):
            self.assertIn(part, out["dry"])
        for rel in ("ucli_api_key", "ucli_agent_tokens/s1", "ucli_metrics"):
            self.assertTrue(any(rel in p for p in out["real_changed"]), (rel, out["real_changed"]))
        self.assertIn(os.path.join(out["work"], ".ucli"), out["real_changed"])

    def test_ucli_claude_service_with_ask_dir(self):
        out = self._run("ucli", opts={"service": "claude", "ask_dir": True})
        self._assert_pure(out)
        for part in ("ucli_key_claude", "--ask-dir", "--usage-log"):
            self.assertIn(part, out["dry"])
        for rel in ("ucli_key_claude", "ucli_ask/s1"):
            self.assertTrue(any(rel in p for p in out["real_changed"]), (rel, out["real_changed"]))

    def test_ucli_removed_key_is_not_deleted_by_dry_run(self):
        # Ayarlardan anahtar silinmiş, yönetilen dosya duruyor: gerçek koşu siler, kuru koşu dokunmaz ve aynı komutu kurar.
        out = self._run("ucli", settings={"byok": {}}, seed=("ucli_api_key", "ucli_api_key.managed"))
        self._assert_pure(out)
        self.assertNotIn("UCLI_API_KEY", out["dry"])
        self.assertFalse(os.path.exists(os.path.join(out["state"], "ucli_api_key")))


if __name__ == "__main__":
    unittest.main()
