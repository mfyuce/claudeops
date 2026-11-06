import os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import chat_dump as D


def _pb_varint(f, v):
    out = bytearray([f << 3]); 
    while True:
        b = v & 0x7F; v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


class DumpTest(unittest.TestCase):
    def test_pb_and_ts(self):
        msg = _pb_varint(1, 1790000000) + bytes([0x12, 5]) + b"hello"
        d = D.pb_decode(msg)
        self.assertEqual(d, [(1, 1790000000), (2, "hello")])
        self.assertEqual(D._first_ts(d), 1790000000)
        self.assertEqual(D._first_ts([(1, 5)]), None)

    def test_gemini_cwd(self):
        with tempfile.TemporaryDirectory() as t:
            c = sqlite3.connect(os.path.join(t, "s.db"))
            c.execute("create table steps(idx integer,step_type int,status int,metadata blob,step_payload blob,render_info blob)")
            path = b"/tmp/" + b"a" * 31                      # uzunluk 36 = "$" (yazdırılabilir)
            val = b"\n$" + path
            c.execute("insert into steps values(0,1,1,NULL,?,NULL)", (bytes([0x5a, len(val)]) + val,))
            self.assertEqual(D._gemini_cwd(c), path.decode())

    def test_gemini_summary_project(self):
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(os.path.join(t, "conversations"))
            sdb = sqlite3.connect(os.path.join(t, "conversation_summaries.db"))
            sdb.execute("create table conversation_summaries(conversation_id text,title text,workspace_uris text,last_modified_time text)")
            sdb.execute("insert into conversation_summaries values('abc','Baslik','[\"file:///w/proj\"]','2026-07-01 10:00:00')")
            sdb.commit(); sdb.close()
            db = os.path.join(t, "conversations", "abc.db")
            c = sqlite3.connect(db)
            c.execute("create table steps(idx integer,step_type int,status int,metadata blob,step_payload blob,render_info blob)")
            c.execute("create table gen_metadata(idx integer,data blob,size int)")
            c.execute("insert into steps values(0,1,1,?,NULL,NULL)", (_pb_varint(1, 1790000000),))
            c.commit(); c.close()
            D._SUMM.clear()
            w = D.write_jsonl(D.dump_gemini(db), t, "gemini")
            self.assertTrue(all(x.startswith("gemini/w-proj/") for x in w), w)
            self.assertIn("gemini/w-proj/2026-07-01/abc.jsonl", w)

    def test_valid_day(self):
        self.assertEqual(D._valid_day("0000-00-00"), D.UNKNOWN)
        self.assertEqual(D._valid_day("0001-01-01"), D.UNKNOWN)
        self.assertEqual(D._valid_day("2026-11-05"), "2026-11-05")
        self.assertEqual(D._day(1e15), D.UNKNOWN)

    def test_gemini_and_codex(self):
        with tempfile.TemporaryDirectory() as t:
            g = os.path.join(t, "abc.db")
            c = sqlite3.connect(g)
            c.execute("create table steps(idx integer,step_type int,status int,metadata blob,step_payload blob,render_info blob)")
            c.execute("create table gen_metadata(idx integer,data blob,size int)")
            c.execute("insert into steps values(0,14,3,?,NULL,NULL)", (_pb_varint(1, 1790000000),))
            c.execute("insert into steps values(1,14,3,NULL,NULL,NULL)")
            c.commit(); c.close()
            w = D.write_jsonl(D.dump_gemini(g), t, "gemini")
            self.assertEqual(sorted(w), sorted(["gemini/bilinmiyor/2026-09-21/abc.jsonl", "gemini/bilinmiyor/bilinmiyor/abc.jsonl"]))
            th, st = os.path.join(t, "th.db"), os.path.join(t, "st.db")
            sqlite3.connect(st).executescript("create table threads(id text,cwd text,title text);insert into threads values('T1','/x/y','t');")
            sqlite3.connect(th).executescript("create table thread_items(thread_id,turn_id,item_id,rollout_ordinal,created_at_ms,item_json,item_type);"
                                              "insert into thread_items values('T1','u','i',1,1790000000000,'{\"a\":1}','userMessage');")
            w = D.write_jsonl(D.dump_codex(th, st), t, "codex")
            self.assertEqual(w, ["codex/x-y/2026-09-21/T1.jsonl"])

    def test_stage_dumps_incremental(self):
        with tempfile.TemporaryDirectory() as t:
            conv = os.path.join(t, ".gemini", "antigravity", "conversations")
            os.makedirs(conv)
            c = sqlite3.connect(os.path.join(conv, "s1.db"))
            c.execute("create table steps(idx integer,step_type int,status int,metadata blob,step_payload blob,render_info blob)")
            c.execute("create table gen_metadata(idx integer,data blob,size int)")
            c.execute("insert into steps values(0,1,1,?,NULL,NULL)", (_pb_varint(1, 1790000000),))
            c.commit(); c.close()
            stamps, stage = {}, os.path.join(t, "stage")
            a = D.stage_dumps(stage, stamps, home=t)
            self.assertEqual((a["dumped"], a["files"], a["errors"]), (1, 1, []))
            f = os.path.join(stage, "gemini", "antigravity", "bilinmiyor", "2026-09-21", "s1.jsonl")
            self.assertTrue(os.path.exists(f))
            self.assertEqual(__import__("datetime").datetime.fromtimestamp(os.path.getmtime(f)).strftime("%F"), "2026-09-21")
            self.assertEqual(D.stage_dumps(stage, stamps, home=t)["skipped"], 1)

    def test_ingest_remote_archives(self):
        import io, tarfile
        with tempfile.TemporaryDirectory() as t:
            hd = os.path.join(t, "h1")
            os.makedirs(hd)
            with tarfile.open(os.path.join(hd, "a.tgz"), "w:gz") as tf:
                for name, data in ((".claude/projects/-p/s.jsonl", b"{}\n"), ("../evil.txt", b"x"), ("/abs.txt", b"x")):
                    ti = tarfile.TarInfo(name); ti.size = len(data)
                    tf.addfile(ti, io.BytesIO(data))
            r = D.ingest_remote_archives(t)
            self.assertEqual(r, {"h1": 1})
            self.assertTrue(os.path.exists(os.path.join(hd, "extract", ".claude/projects/-p/s.jsonl")))
            self.assertFalse(os.path.exists(os.path.join(t, "evil.txt")))
            self.assertEqual(D.ingest_remote_archives(t), {"h1": "atlandı"})

    def test_ingest_rejects_dangerous_members(self):
        import io, tarfile
        with tempfile.TemporaryDirectory() as t:
            hd = os.path.join(t, "h2")
            os.makedirs(hd)
            secret = os.path.join(t, "outside.txt")
            with tarfile.open(os.path.join(hd, "b.tgz"), "w:gz") as tf:
                for name, data in (("ok/a.jsonl", b"{}\n"), ("a/../../escape.txt", b"x"), ("..", b"x"), ("./../x2", b"x")):
                    ti = tarfile.TarInfo(name); ti.size = len(data)
                    tf.addfile(ti, io.BytesIO(data))
                sl = tarfile.TarInfo("link"); sl.type = tarfile.SYMTYPE; sl.linkname = secret
                tf.addfile(sl)
                hl = tarfile.TarInfo("hard"); hl.type = tarfile.LNKTYPE; hl.linkname = "ok/a.jsonl"
                tf.addfile(hl)
                dv = tarfile.TarInfo("dev"); dv.type = tarfile.CHRTYPE
                tf.addfile(dv)
            r = D.ingest_remote_archives(t)
            self.assertEqual(r, {"h2": 1})
            ex = os.path.join(hd, "extract")
            self.assertEqual(sorted(x for x in os.listdir(ex) if x != ".done"), ["ok"])
            self.assertFalse(os.path.lexists(os.path.join(ex, "link")))
            self.assertFalse(os.path.exists(os.path.join(t, "escape.txt")) or os.path.exists(os.path.join(hd, "escape.txt")))
            self.assertEqual(oct(os.stat(os.path.join(ex, "ok", "a.jsonl")).st_mode & 0o777), "0o600")

    def test_ingest_corrupt_archive(self):
        with tempfile.TemporaryDirectory() as t:
            hd = os.path.join(t, "h3")
            os.makedirs(hd)
            open(os.path.join(hd, "c.tgz"), "wb").write(b"bu bir tgz degil")
            r = D.ingest_remote_archives(t)
            self.assertTrue(str(r["h3"]).startswith("HATA"), r)
            self.assertFalse(os.path.exists(os.path.join(hd, "extract", ".done")))      # bozuk arşiv bir daha denenir


if __name__ == "__main__":
    unittest.main()
