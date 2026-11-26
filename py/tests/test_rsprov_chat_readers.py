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


if __name__ == "__main__":
    unittest.main()
