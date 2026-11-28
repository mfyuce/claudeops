"""TODO rs-prov "512-1000 iç içe JSON ve eşlenmemiş vekil eşlik farkı" (28 Kas): sağlayıcı okuyucuları Rust
`pyjson` kurallarıyla okur (`claudeops.jsonbound`). Yalnız geçici dizin."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import jsonbound, ucli_client  # noqa: E402
from claudeops.providers import claude_provider  # noqa: E402


def nested(n: int) -> str:
    return "[" * n + "]" * n


class LoadsTest(unittest.TestCase):
    def test_depth_limit_is_rusts(self):
        self.assertIsInstance(jsonbound.loads(nested(512)), list)
        for n in (513, 600, 1200, 100_000):
            with self.assertRaises(json.JSONDecodeError):
                jsonbound.loads(nested(n))

    def test_brackets_inside_strings_do_not_count(self):
        self.assertEqual(jsonbound.loads(json.dumps("[" * 2000)), "[" * 2000)
        self.assertEqual(jsonbound.loads(b'{"a": "' + b"{" * 900 + b'"}'), {"a": "{" * 900})

    def test_lone_surrogates_become_replacement_char(self):
        v = jsonbound.loads(r'{"k\ud800": ["x\udc00 😀", {"y": "\ud83d"}], "z": 1}')
        self.assertEqual(v, {"k�": ["x� \U0001F600", {"y": "�"}], "z": 1})
        self.assertEqual(list(v), ["k�", "z"])
        self.assertEqual(jsonbound.loads(r'"\udfff"'), "�")

    def test_colliding_keys_keep_first_place_last_value(self):
        v = jsonbound.loads(r'{"a\ud800": 1, "b": 2, "a\udbff": 3}')
        self.assertEqual(list(v.items()), [("a�", 3), ("b", 2)])

    def test_bytes_are_accepted(self):
        self.assertEqual(jsonbound.loads('{"a": 1}'.encode("utf-16")), {"a": 1})


class ReadersTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = d.name

    def test_claude_meta_skips_a_600_deep_line(self):
        p = Path(self.root, "m.jsonl")
        p.write_text('{"customTitle":"t","d":' + nested(600) + "}\n", encoding="utf-8")
        self.assertEqual(claude_provider._jsonl_meta(p), {"title": None, "cwd": None})

    def test_ucli_status_file_too_deep_is_unreadable(self):
        os.makedirs(os.path.join(self.root, ".ucli", "chat"))
        with open(os.path.join(self.root, ".ucli", "chat", "s1.status.json"), "w") as f:
            f.write('{"activity":"running_tool","d":' + nested(600) + "}")
        self.assertIsNone(ucli_client.read_status_file(self.root, "s1"))


if __name__ == "__main__":
    unittest.main()
