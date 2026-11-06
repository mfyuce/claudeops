import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import chat_index as I


class IndexTest(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as t:
            rel = "local/claude-projects/-p1/s1.jsonl"
            os.makedirs(os.path.join(t, os.path.dirname(rel)))
            with open(os.path.join(t, rel), "w") as f:
                f.write(json.dumps({"type": "user", "cwd": "/x/p1", "timestamp": "2026-10-01T10:00:00Z", "message": {"content": "merhaba dunya"}}) + "\n")
                f.write(json.dumps({"type": "assistant", "timestamp": "2026-10-02T11:00:00Z"}) + "\n")
            mem = "memory/h1/claude/-p1/a.md"
            os.makedirs(os.path.join(t, os.path.dirname(mem)))
            open(os.path.join(t, mem), "w").write("x")
            idx = I.write_index(t, [rel, mem, "README.md"], "h1")
            self.assertEqual(idx, ["INDEX.jsonl", "INDEX.md"])
            ents = [json.loads(l) for l in open(os.path.join(t, "INDEX.jsonl"))]
            self.assertEqual(len(ents), 2)
            c = [e for e in ents if e["kind"] == "chat"][0]
            self.assertEqual((c["cwd"], c["title"], c["first"][:10], c["last"][:10]), ("/x/p1", "merhaba dunya", "2026-10-01", "2026-10-02"))
            self.assertEqual([e for e in ents if e["kind"] == "memory"][0]["host"], "h1")
            self.assertIn("| claude | -p1 | 1 |", open(os.path.join(t, "INDEX.md")).read())

    def test_gemini_summary_row(self):
        with tempfile.TemporaryDirectory() as t:
            rel = "local/gemini-dump/antigravity/w-proj/2026-07-01/c1.jsonl"
            os.makedirs(os.path.join(t, os.path.dirname(rel)))
            with open(os.path.join(t, rel), "w") as f:
                f.write(json.dumps({"summary": {"title": "Baslik", "workspace": "/w/proj", "last_modified": "2026-07-01 10:00:00"}}) + "\n")
            e = I.entry(t, rel, "h1")
            self.assertEqual((e["title"], e["cwd"]), ("Baslik", "/w/proj"))

    def test_classify_remote_host(self):
        c = I.classify("local/claude-ulak_31-projects/-home-x/s1.jsonl")
        self.assertEqual((c["cli"], c["host"], c["project"], c["session"]), ("claude", "ulak_31", "-home-x", "s1"))
        c = I.classify("local/codex-ulak_31-sessions/2026/11/06/rollout-a.jsonl")
        self.assertEqual((c["cli"], c["host"]), ("codex", "ulak_31"))


if __name__ == "__main__":
    unittest.main()
