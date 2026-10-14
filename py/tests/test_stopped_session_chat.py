"""Durmuş session'ın sohbet görünümü testleri (stdlib unittest): `CliProvider.sid_for_stopped_session`
(claude/agy/ucli + varsayılan), `ucli_client.read_chat_history`'nin şema-başlığı toleransı ve
`web._term_chat`'in bunları bağlaması.

Çalıştırma:  python3 py/tests/test_stopped_session_chat.py -v

Kapsadığı hata (2026-10-14, kullanıcı: "history de goruntule de chat gorunmuyor"): Geçmiş/Devre dışı/
Emekli'deki "görüntüle", `pid=0` sentetik bir `Session` kurar ve `sid` vermezdi; `sid=None` "cwd'deki EN YENİ
konuşma" demek. Bir blueprint'in tarihli instance'ları AYNI cwd'yi paylaştığından modal başka bir konuşmayı,
çoğu zaman yeni açılmış boş bir stub'ı gösteriyordu ("Sen: (boş) / Asistan: (boş)"). Ayrıca ucli'nin yeni
sohbet dosyaları `{"ucli_session_schema_version":1}` başlığıyla başlıyor ve `read_chat_history` onu bozuk
dosya sanıp "desteklenmiyor" döndürüyordu. Gerçek ~/.claude, agy/ucli dizinlerine DOKUNMAZ (hepsi geçici dizin).
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_client  # noqa: E402
from claudeops.commands import web  # noqa: E402
from claudeops.providers import agy_provider, get_provider  # noqa: E402
from claudeops.providers import claude_provider as cp  # noqa: E402
from claudeops.session import Session  # noqa: E402

CWD = "/work/proj/shared"  # blueprint'in ve tüm instance'larının ortak klasörü


def user_row(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def assistant_row(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


class ClaudeTranscriptCase(unittest.TestCase):
    """Geçici bir PROJECTS_DIR; `write()` ile başlıklı/başlıksız jsonl'lar kurar."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.projects = Path(self._tmp.name)
        patcher = mock.patch.object(cp, "PROJECTS_DIR", str(self.projects))
        patcher.start()
        self.addCleanup(patcher.stop)
        cp._META_CACHE.clear()
        self.addCleanup(cp._META_CACHE.clear)
        self.provider = cp.ClaudeProvider()
        self._seq = 0

    def proj_dir(self, cwd=CWD):
        d = self.projects / cp._encode_cwd(cwd)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write(self, sid, title, chat=(), mtime=1_800_000_000, cwd=CWD, file_cwd=None, pad=0):
        """Başlık satırı (+ cwd satırı) + sohbet satırları. `file_cwd`: dosyanın KENDİ `cwd` alanı
        (encoding çakışması senaryosu); `pad`: sohbet olmayan dolgu baytı (büyük-dosya senaryosu)."""
        rows = []
        if title is not None:
            rows.append({"type": "custom-title", "customTitle": title, "sessionId": sid})
        rows.append({"type": "system", "subtype": "bridge_status", "cwd": file_cwd or cwd, "sessionId": sid})
        if pad:
            rows.append({"type": "file-history-snapshot", "pad": "x" * pad})
        rows.extend(chat)
        path = self.proj_dir(cwd) / f"{sid}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        os.utime(path, (mtime, mtime))
        return path


class ClaudeSidForStoppedSessionTests(ClaudeTranscriptCase):
    def test_own_conversation_wins_over_a_newer_sibling_stub(self):
        """ae20261013: aynı cwd'deki bugünün instance'ı henüz mesajsız (en yeni dosya), kendi konuşması eski."""
        self.write("own", "inst20261013", chat=[user_row("selam"), assistant_row("merhaba")], mtime=1000)
        self.write("stub", "inst20261014", mtime=2000)  # en yeni, başlık-yalnız
        self.assertEqual(self.provider.sid_for_stopped_session(CWD, "inst20261013"), "own")

    def test_each_sibling_resolves_to_its_own_file(self):
        self.write("a", "inst_a", chat=[user_row("a")], mtime=1000)
        self.write("b", "inst_b", chat=[user_row("b")], mtime=3000)
        self.write("c", "inst_c", chat=[user_row("c")], mtime=2000)
        self.assertEqual(
            [self.provider.sid_for_stopped_session(CWD, n) for n in ("inst_a", "inst_b", "inst_c")],
            ["a", "b", "c"],
        )

    def test_same_title_prefers_the_real_conversation_over_a_newer_stub(self):
        """hcr20260908_1: yeniden açılış başlık-yalnız stub bıraktı ve o gerçek konuşmadan DAHA yeni."""
        self.write("real", "hcr", chat=[user_row("devam"), assistant_row("tamam")], mtime=1000)
        self.write("stub", "hcr", mtime=1001)
        self.assertEqual(self.provider.sid_for_stopped_session(CWD, "hcr"), "real")

    def test_same_title_picks_the_newest_real_conversation_even_when_it_is_the_smaller_one(self):
        """Handover AYNI adla YENİ (daha kısa) konuşma başlatır; en yeni gerçek olan seçilir, en büyük değil."""
        self.write("old", "qve", chat=[user_row("u%d" % i) for i in range(50)], mtime=1000)
        self.write("new", "qve", chat=[user_row("yeni"), assistant_row("ok")], mtime=2000)
        self.assertEqual(self.provider.sid_for_stopped_session(CWD, "qve"), "new")

    def test_all_stubs_returns_the_newest_one(self):
        self.write("s1", "idle", mtime=1000)
        self.write("s2", "idle", mtime=2000)
        self.assertEqual(self.provider.sid_for_stopped_session(CWD, "idle"), "s2")

    def test_a_large_file_counts_as_real_without_being_scanned(self):
        """`_STUB_MAX_BYTES` ve üstü doğrudan gerçek sayılır (içine bakılmaz)."""
        self.write("small", "big", chat=[user_row("x")], mtime=1000)
        self.write("large", "big", mtime=2000, pad=cp._STUB_MAX_BYTES)
        with mock.patch.object(cp, "_has_chat_rows", side_effect=AssertionError("taranmamalıydı")):
            self.assertEqual(self.provider.sid_for_stopped_session(CWD, "big"), "large")

    def test_no_title_match_returns_none(self):
        self.write("x", "somebody_else", chat=[user_row("x")])
        self.assertIsNone(self.provider.sid_for_stopped_session(CWD, "inst"))

    def test_title_is_an_exact_match_not_a_prefix(self):
        self.write("x", "inst20261013_1", chat=[user_row("x")])
        self.assertIsNone(self.provider.sid_for_stopped_session(CWD, "inst20261013"))

    def test_untitled_files_never_match(self):
        self.write("x", None, chat=[user_row("x")])
        self.assertIsNone(self.provider.sid_for_stopped_session(CWD, "inst"))

    def test_missing_project_dir_and_empty_name_return_none(self):
        self.assertIsNone(self.provider.sid_for_stopped_session("/no/such/cwd", "inst"))
        self.write("x", "inst", chat=[user_row("x")])
        self.assertIsNone(self.provider.sid_for_stopped_session(CWD, ""))

    def test_file_recording_a_different_cwd_is_ignored(self):
        """Proje-dizini encoding'i `_` ile `-`yi birleştirir: aynı dizine düşen BAŞKA bir projenin dosyası eşleşmemeli."""
        self.write("other", "inst", chat=[user_row("x")], file_cwd="/work/proj-shared-elsewhere")
        self.assertIsNone(self.provider.sid_for_stopped_session(CWD, "inst"))

    def test_finds_a_file_older_than_the_resume_scan_limit(self):
        """`resolve_resume_id` en yeni 25 dosyaya bakar; 3 haftalık bir instance'ın dosyası bunun dışında kalır."""
        self.write("oldest", "inst", chat=[user_row("x")], mtime=1000)
        for i in range(cp._RESUME_SCAN_LIMIT + 5):
            self.write(f"n{i}", f"newer{i}", chat=[user_row("x")], mtime=2000 + i)
        self.assertEqual(self.provider.sid_for_stopped_session(CWD, "inst"), "oldest")
        self.assertNotEqual(self.provider.resolve_resume_id(CWD, session_name="inst"), "oldest")  # eski sınırın kanıtı

    def test_unchanged_files_are_not_reread_but_changed_ones_are(self):
        path = self.write("x", "inst", chat=[user_row("x")], mtime=1000)
        real_meta = cp._jsonl_meta
        with mock.patch.object(cp, "_jsonl_meta", side_effect=real_meta) as spy:
            self.provider.sid_for_stopped_session(CWD, "inst")
            self.provider.sid_for_stopped_session(CWD, "inst")
            self.assertEqual(spy.call_count, 1)
            self.write("x", "renamed", chat=[user_row("x")], mtime=2000)  # imza değişti
            self.assertIsNone(self.provider.sid_for_stopped_session(CWD, "inst"))
            self.assertEqual(self.provider.sid_for_stopped_session(CWD, "renamed"), "x")
            self.assertEqual(spy.call_count, 2)
        self.assertTrue(path.exists())


class TermChatWiringTests(ClaudeTranscriptCase):
    def stopped(self, name, cli="claude"):
        return Session(name=name, pid=0, cwd=CWD, cli=cli)

    def chat(self, session, mode):
        with mock.patch.object(web, "_files_resolve", return_value=(session, None)):
            return web._term_chat(session.name, "tr", mode)

    def setUp(self):
        super().setUp()
        self.write("own", "inst20261013", chat=[user_row("soru 1"), assistant_row("cevap 1"),
                                                user_row("soru 2"), assistant_row("cevap 2")], mtime=1000)
        self.write("stub", "inst20261014", mtime=2000)

    def test_stopped_session_shows_its_own_full_history_not_the_newest_stub(self):
        res = self.chat(self.stopped("inst20261013"), "full")
        self.assertEqual([m["text"] for m in res["messages"]], ["soru 1", "cevap 1", "soru 2", "cevap 2"])
        self.assertEqual(res["total"], 4)

    def test_stopped_session_last_exchange_is_its_own(self):
        res = self.chat(self.stopped("inst20261013"), "last")
        self.assertEqual((res["user"], res["assistant"]), ("soru 2", "cevap 2"))

    def test_incremental_since_still_works_on_the_resolved_conversation(self):
        with mock.patch.object(web, "_files_resolve", return_value=(self.stopped("inst20261013"), None)):
            res = web._term_chat("inst20261013", "tr", "full", since=3)
        self.assertEqual([m["text"] for m in res["messages"]], ["cevap 2"])
        self.assertEqual(res["total"], 4)

    def test_unmatched_stopped_session_keeps_the_old_newest_in_cwd_behavior(self):
        """Adından bulunamayan (ör. eski `migrated` kayıt): eskiden olduğu gibi cwd'deki en yeni konuşma."""
        res = self.chat(self.stopped("never_titled"), "full")
        self.assertEqual(res["messages"], [])  # en yeni dosya = boş stub (2000)
        self.write("fresh", "someone", chat=[user_row("en yeni")], mtime=3000)
        res = self.chat(self.stopped("never_titled"), "full")
        self.assertEqual([m["text"] for m in res["messages"]], ["en yeni"])

    def test_live_session_never_consults_the_name_lookup(self):
        live = Session(name="inst20261013", pid=4242, cwd=CWD, cli="claude", sid="stub")
        with mock.patch.object(cp.ClaudeProvider, "sid_for_stopped_session",
                               side_effect=AssertionError("canlı session'da çağrılmamalı")):
            res = self.chat(live, "full")
        self.assertEqual(res["messages"], [])  # kendi (canlı) sid'i = stub; isim araması devreye girmedi

    def test_live_session_without_sid_is_left_alone_too(self):
        """sid'siz CANLI session'ın davranışı bu düzeltmenin kapsamı DIŞINDA (yalnız pid=0 durmuşlar)."""
        live = Session(name="inst20261013", pid=4242, cwd=CWD, cli="claude")
        with mock.patch.object(cp.ClaudeProvider, "sid_for_stopped_session",
                               side_effect=AssertionError("canlı session'da çağrılmamalı")):
            self.chat(live, "last")

    def test_unsupported_cli_still_reports_supported_false(self):
        res = self.chat(self.stopped("inst", cli="shell"), "full")
        self.assertEqual(res, {"ok": True, "supported": False})


class OtherProvidersTests(unittest.TestCase):
    def test_default_providers_do_not_guess(self):
        for cli in ("codex", "copilot", "shell"):
            self.assertIsNone(get_provider(cli).sid_for_stopped_session(CWD, "inst"), cli)

    def test_agy_uses_the_learned_name_to_sid_map_when_the_db_exists(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "conv-1.db").write_bytes(b"")
            with mock.patch.object(agy_provider, "CONVERSATIONS_DIR", d), \
                    mock.patch.object(agy_provider, "_load_agy_sids",
                                      return_value={"inst": "conv-1", "gone": "conv-9", "weird": 7}):
                p = agy_provider.AgyProvider()
                self.assertEqual(p.sid_for_stopped_session(CWD, "inst"), "conv-1")
                self.assertIsNone(p.sid_for_stopped_session(CWD, "gone"))      # dosyası silinmiş
                self.assertIsNone(p.sid_for_stopped_session(CWD, "weird"))     # str olmayan değer
                self.assertIsNone(p.sid_for_stopped_session(CWD, "unlearned"))  # öğrenilmemiş
                self.assertIsNone(p.sid_for_stopped_session(CWD, ""))

    def test_ucli_sid_is_the_session_name(self):
        p = get_provider("ucli")
        self.assertEqual(p.sid_for_stopped_session(CWD, "inst"), "inst")
        self.assertIsNone(p.sid_for_stopped_session(CWD, ""))


class UcliChatTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cwd = self._tmp.name

    def write_chat(self, session, lines):
        d = Path(ucli_client.chat_session_dir(self.cwd))
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{session}.jsonl").write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    HEADER = json.dumps({"ucli_session_schema_version": 1})
    USER = json.dumps({"role": "user", "content": "soru"})
    ASSISTANT = json.dumps({"role": "assistant", "content": "cevap"})

    def test_schema_header_row_is_skipped(self):
        self.write_chat("s", [self.HEADER, self.USER, self.ASSISTANT])
        self.assertEqual(ucli_client.read_chat_history(self.cwd, "s"),
                         [{"role": "user", "text": "soru"}, {"role": "assistant", "text": "cevap"}])

    def test_header_only_file_means_no_messages_yet_not_unsupported(self):
        self.write_chat("s", [self.HEADER])
        self.assertEqual(ucli_client.read_chat_history(self.cwd, "s"), [])

    def test_old_files_without_a_header_still_parse(self):
        self.write_chat("s", [self.USER, self.ASSISTANT])
        self.assertEqual(len(ucli_client.read_chat_history(self.cwd, "s")), 2)

    def test_corrupt_files_are_still_reported_as_unreadable(self):
        self.write_chat("bad_json", [self.HEADER, "{not json"])
        self.assertIsNone(ucli_client.read_chat_history(self.cwd, "bad_json"))
        self.write_chat("no_content", [self.HEADER, json.dumps({"role": "user"})])
        self.assertIsNone(ucli_client.read_chat_history(self.cwd, "no_content"))

    def test_missing_file_is_an_empty_history(self):
        self.assertEqual(ucli_client.read_chat_history(self.cwd, "nope"), [])

    def test_stopped_ucli_instance_chat_is_served_through_term_chat(self):
        self.write_chat("inst_a", [self.HEADER, self.USER, self.ASSISTANT])
        self.write_chat("inst_b", [self.HEADER, json.dumps({"role": "user", "content": "b-soru"}),
                                   json.dumps({"role": "assistant", "content": "b-cevap"})])
        for name, expect in (("inst_a", ("soru", "cevap")), ("inst_b", ("b-soru", "b-cevap"))):
            s = Session(name=name, pid=0, cwd=self.cwd, cli="ucli")
            with mock.patch.object(web, "_files_resolve", return_value=(s, None)):
                res = web._term_chat(name, "tr", "last")
            self.assertEqual((res["user"], res["assistant"]), expect, name)


if __name__ == "__main__":
    unittest.main()
