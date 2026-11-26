"""Sohbet geçmişi okuyucuları (rs/prov G2): tek bozuk girdi bütün okumayı düşürmez; belirsizlikte uydurma değer yok.

Çalıştırma:  python3 -m unittest discover -s py/tests -p test_rsprov_chat_readers.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings, ucli_client  # noqa: E402
from claudeops.providers import claude_provider as cp  # noqa: E402
from claudeops.providers import codex_provider as xp  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402


def c_row(kind, content, **extra):
    return json.dumps(dict({"type": kind, "message": {"content": content}}, **extra), ensure_ascii=False)


def x_row(role, text):
    kind = "output_text" if role == "assistant" else "input_text"
    return json.dumps({"type": "response_item", "payload": {"type": "message", "role": role,
                                                           "content": [{"type": kind, "text": text}]}}, ensure_ascii=False)


PAIR = [{"role": "user", "text": "soru"}, {"role": "assistant", "text": "cevap"}]
EXCHANGE = {"user": "soru", "assistant": "cevap"}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def claude(self, *rows):
        path = self._write("claude.jsonl", rows)
        patch = mock.patch.object(cp, "jsonl_path_for", return_value=path)
        patch.start()
        self.addCleanup(patch.stop)
        return cp.ClaudeProvider()

    def codex(self, *rows):
        path = self._write("codex.jsonl", rows)
        patch = mock.patch.object(xp.CodexProvider, "_rollout_path", return_value=str(path))
        patch.start()
        self.addCleanup(patch.stop)
        return xp.CodexProvider()

    def ucli(self, data: bytes):
        chat = self.root / ".ucli" / "chat"
        chat.mkdir(parents=True, exist_ok=True)
        (chat / "s.jsonl").write_bytes(data)
        for patch in (mock.patch.object(settings, "ucli_state_dir_enabled", return_value=False),
                      mock.patch.object(ucli_client, "state_dir_for", return_value=str(self.root / "yok"))):
            patch.start()
            self.addCleanup(patch.stop)
        return up.UcliProvider()

    def _write(self, name, rows):
        """`rows`: metin satır (sonuna `\\n` eklenir) ya da ham bayt (olduğu gibi)."""
        path = self.root / name
        path.write_bytes(b"".join(r if isinstance(r, bytes) else r.encode("utf-8") + b"\n" for r in rows))
        return path

    def pairs(self):
        return ((self.claude, c_row("user", "soru"), c_row("assistant", [{"type": "text", "text": "cevap"}])),
                (self.codex, x_row("user", "soru"), x_row("assistant", "cevap")))


class BadByteTest(Base):
    def test_one_bad_line_does_not_drop_the_history(self):
        cut = b'{"x":"\xe2\x82'                  # yazım sürerken yarım kalan çok baytlı karakter
        mid = b'{"type":"user","x":"\xff"}\n'
        for make, q, a in self.pairs():
            for name, rows in (("sonda", (q, a, cut)), ("ortada", (q, mid, a))):
                with self.subTest(cli=make.__name__, yer=name):
                    p = make(*rows)
                    self.assertEqual(p.full_history("/x", "s"), PAIR)
                    self.assertEqual(p.last_exchange("/x", "s"), EXCHANGE)

    def test_unreadable_tail_leaves_the_last_role_unknown(self):
        for make, q, _a in self.pairs():
            with self.subTest(cli=make.__name__):
                # son satır okunamıyor: takılma tespiti (öldür + yeniden aç) için "bilinmiyor"
                self.assertIsNone(make(q, b'{"x":"\xff"}\n').last_message_role("/x", "s"))
                self.assertIsNone(make(q, b'{"x":"\xff"}\n', "", "  ").last_message_role("/x", "s"))
                # okunamayan satır geride kaldıysa rol yine okunur; yarım ASCII satırda davranış eskisi gibi
                self.assertEqual(make(b'{"x":"\xff"}\n', q).last_message_role("/x", "s"), "user")
                self.assertEqual(make(q, b'{"type":"ass').last_message_role("/x", "s"), "user")

    def test_ucli_bad_byte_means_unreadable(self):
        p = self.ucli(b'{"role":"user","content":"soru"}\n\xff\n')
        self.assertIsNone(p.full_history(str(self.root), "s"))
        self.assertIsNone(p.last_exchange(str(self.root), "s"))
        self.assertIsNone(p.last_message_role(str(self.root), "s"))

class UcliHalfLineTest(Base):
    DONE = b'{"ucli_session_schema_version":1}\n{"role":"user","content":"soru"}\n{"role":"assistant","content":"cevap"}\n'

    def test_half_written_last_line_is_skipped(self):
        for tail in (b'{"role":"assistant","cont', b'{"role":"user","content":"\xc4'):
            with self.subTest(tail=tail):
                p = self.ucli(self.DONE + tail)
                self.assertEqual(p.full_history(str(self.root), "s"), PAIR)
                self.assertEqual(p.last_exchange(str(self.root), "s"), EXCHANGE)
                # yarım satır varken son rol bilinmiyor (eskisi gibi): takılma tespiti oturumu yeniden açmaz
                self.assertIsNone(p.last_message_role(str(self.root), "s"))

    def test_complete_but_broken_line_is_still_unreadable(self):
        for body in (self.DONE + b'{bozuk\n', b'{"role":"user","cont\n' + self.DONE,
                     self.DONE + b'{"role":"user"}'):          # tamamlanmış ama `content`siz satır
            with self.subTest(body=body):
                self.assertIsNone(self.ucli(body).full_history(str(self.root), "s"))

    def test_complete_unterminated_line_still_counts(self):
        p = self.ucli(self.DONE + b'{"role":"user","content":"yeni"}')
        self.assertEqual(p.full_history(str(self.root), "s")[-1], {"role": "user", "text": "yeni"})
        self.assertEqual(p.last_message_role(str(self.root), "s"), "user")

class BadShapeTest(Base):
    DEEP = '{"type":"x","d":' + "[" * 100000 + "]" * 100000 + "}"
    HUGE = '{"type":"x","n":' + "9" * 5000 + "}"

    def check(self, make, *rows, history=PAIR, exchange=EXCHANGE):
        p = make(*rows)
        self.assertEqual(p.full_history("/x", "s"), history)
        self.assertEqual(p.last_exchange("/x", "s"), exchange)

    def test_unexpected_lines_are_skipped(self):
        for make, q, a in self.pairs():
            for bad in ("[1,2]", '"x"', "5", "null", "true", self.DEEP, self.HUGE):
                with self.subTest(cli=make.__name__, bad=bad[:30]):
                    self.check(make, q, a, bad)

    def test_non_object_tail_leaves_the_last_role_unknown(self):
        for make, q, _a in self.pairs():
            with self.subTest(cli=make.__name__):
                self.assertIsNone(make(q, "[1]").last_message_role("/x", "s"))
                self.assertEqual(make("[1]", q).last_message_role("/x", "s"), "user")

    def test_claude_non_object_message_is_skipped(self):
        q, a = c_row("user", "soru"), c_row("assistant", [{"type": "text", "text": "cevap"}])
        for bad in ('{"type":"user","message":null}', '{"type":"user","message":"x"}', '{"type":"user","message":[1]}',
                    '{"type":"user","isCompactSummary":true,"message":null}'):
            with self.subTest(bad=bad):
                self.check(self.claude, q, bad, a)
        # son asistan satırının `message`i bozuksa yanıt boş: önceki yanıt güncel yanıt diye sunulmaz
        self.check(self.claude, q, a, '{"type":"assistant","message":5}',
                   exchange={"user": "soru", "assistant": ""})

    def test_non_text_block_is_skipped(self):
        for value in (5, {"a": 1}, True, ["x"]):
            with self.subTest(value=value):
                blocks = [{"type": "text", "text": value}, {"type": "text", "text": "cevap"}]
                self.check(self.claude, c_row("user", "soru"), c_row("assistant", blocks))
                row = json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": value}, {"type": "output_text", "text": "cevap"}]}})
                self.check(self.codex, x_row("user", "soru"), row)

    def test_claude_non_object_compact_metadata(self):
        meta = '{"type":"system","subtype":"compact_boundary","compactMetadata":"x"}'
        p = self.claude(c_row("user", "soru"), meta)
        self.assertEqual(p.full_history("/x", "s")[-1], {"role": "boundary", "text": ", "})

    def test_codex_non_object_payload_is_skipped(self):
        for bad in ('{"type":"response_item","payload":null}', '{"type":"response_item","payload":"x"}',
                    '{"type":"response_item","payload":[1]}'):
            with self.subTest(bad=bad):
                self.check(self.codex, x_row("user", "soru"), bad, x_row("assistant", "cevap"), bad)

    def test_ucli_deep_or_huge_line_means_unreadable(self):
        for bad in (self.DEEP, self.HUGE):
            with self.subTest(bad=bad[:30]):
                self.assertIsNone(self.ucli((bad + "\n").encode()).full_history(str(self.root), "s"))


if __name__ == "__main__":
    unittest.main()
