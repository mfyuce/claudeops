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


if __name__ == "__main__":
    unittest.main()
