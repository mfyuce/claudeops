"""Review IO günlüğü (.io.jsonl) + History entegrasyonu: artımlı/kalıcı yazım, redact, kırpma, yol güvenliği,
sohbet dönüşümü, başlık/rozet saf fonksiyonları. Gerçek süreç YOK."""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_web_review_runner import Base, FakeProc, EV  # noqa: E402
from test_steward_review_api import _Api, T1  # noqa: E402
from claudeops import review as rv, steward as sw  # noqa: E402
from claudeops.commands import web_review as wr, web_steward as ws  # noqa: E402

SECRET = "sk-" + "B" * 40


def events(path):
    with open(path) as f:
        return [json.loads(x) for x in f if x.strip()]


class TestIoLog(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "r", "x.io.jsonl")

    def test_incremental_and_roles(self):
        lg = wr.IoLog(self.p)
        lg.event("user", "prompt metni", "prompt")
        self.assertEqual(len(events(self.p)), 1)            # kapatılmadan diskte
        lg.feed_err("UnifiedCLI tool: read_file(a.py)\nUnifiedCLI model: bakiyorum\nmerhaba ")
        lg.feed_err("dunya\nUnifiedCLI reasoning: dusun\n")
        lg.out('{"answer": "x"}')
        lg.close()
        ev = events(self.p)
        self.assertEqual([(e["role"], e.get("kind")) for e in ev][:3], [("user", "prompt"), ("tool", "call"), ("assistant", "model")])
        self.assertIn(("assistant", "reasoning"), [(e["role"], e.get("kind")) for e in ev])
        deltas = "".join(e["text"] for e in ev if e.get("kind") == "delta")
        self.assertEqual(deltas, "merhaba dunya\n")

    def test_plain_stderr_is_system_when_not_a_delta_stream(self):
        """claude/codex/agy/copilot: öneksiz stderr (hata/uyarı) assistant cevabı sayılmaz."""
        lg = wr.IoLog(self.p, err_as_delta=False)
        lg.feed_err("Warning: kota ya")
        lg.feed_err("kin\nikinci satir")
        lg.close()
        ev = events(self.p)
        self.assertEqual([(e["role"], e.get("kind"), e["text"]) for e in ev],
                         [("system", "stderr", "Warning: kota yakin"), ("system", "stderr", "ikinci satir")])
        self.assertEqual(lg.streamed_report(), "")
        msgs = wr.io_to_messages(ev)
        self.assertTrue(all(m["role"] != "assistant" for m in msgs))

    def test_split_prefix_and_secret(self):
        lg = wr.IoLog(self.p)
        lg.feed_err("Unified")
        lg.feed_err("CLI tool: t()\n")
        lg.feed_err("anahtar " + SECRET[:20])
        lg.feed_err(SECRET[20:] + " son\n")
        lg.close()
        ev = events(self.p)
        self.assertEqual(ev[0]["role"], "tool")
        blob = json.dumps(ev)
        self.assertNotIn(SECRET, blob)
        self.assertNotIn(SECRET[:20], blob)
        self.assertIn("[REDACTED]", blob)

    def test_trim_note(self):
        lg = wr.IoLog(self.p, max_bytes=4000, head=500, tail=1500)
        for i in range(200):
            lg.event("assistant", f"satir {i} " + "x" * 30, "delta")
        ev = events(self.p)
        self.assertTrue(any(e.get("kind") == "trim" for e in ev))
        self.assertLess(os.path.getsize(self.p), 6000)
        self.assertEqual(ev[0]["text"].split()[1], "0")

    def test_bad_line_tolerated(self):
        os.makedirs(os.path.dirname(self.p))
        with open(self.p, "w") as f:
            f.write('{"role":"user","text":"a"}\nNOT JSON\n')
        r = wr._read_io_file(self.p, 0)
        self.assertEqual([e["role"] for e in r["events"]], ["user", "system"])


class TestRunWritesIo(Base):
    def test_persisted_after_done_and_cancel(self):
        res = self.ev(popen=self.popen(out=json.dumps({"answer": "## R-1 | P2 | t | a.py:1\nb"}),
                                       err="UnifiedCLI tool: read_file(x)\n"))
        io = wr.io_path_for(res["file"])
        self.assertTrue(os.path.isfile(io))
        ev = events(io)
        self.assertEqual(ev[0]["role"], "user")
        self.assertTrue(any(e["role"] == "tool" for e in ev))
        self.assertTrue(any("bitti: done" in e["text"] for e in ev))
        self.assertEqual(self.pair(EV)["io_file"], io)

    def test_error_keeps_io_and_redacts_stdout(self):
        res = self.ev(popen=self.popen(out="", err=f"hata {SECRET}\n", rc=2))
        io = wr.io_path_for(res["file"])
        self.assertTrue(os.path.isfile(io))
        self.assertNotIn(SECRET, open(io).read())

    def test_stream_flags_gated(self):
        self.ev()
        argv = FakeProc.instances[0].argv
        self.assertIn("--stream", argv)
        self.assertNotIn("--allow-edit", argv)
        FakeProc.instances = []
        self.ev(supports_flag=lambda b, f: f == "--max-io-mib")
        self.assertNotIn("--stream", FakeProc.instances[0].argv)

    def test_real_pipes_stream_and_heartbeat(self):
        import subprocess
        code = "\n".join([
            "import sys, time, json",
            "sys.stderr.write('UnifiedCLI tool: t(1)\\nhal '); sys.stderr.flush(); time.sleep(0.5)",
            "sys.stderr.write('devam\\n')",
            "sys.stdout.write(json.dumps({'answer': '## R-1 | P2 | t | a.py:1\\nb'}))"])
        old = wr.HEARTBEAT_SECONDS
        wr.HEARTBEAT_SECONDS = 0.2
        self.addCleanup(setattr, wr, "HEARTBEAT_SECONDS", old)
        res = self.ev(popen=lambda argv, **k: subprocess.Popen([sys.executable, "-c", code], **k))
        ev = events(wr.io_path_for(res["file"]))
        self.assertTrue(any(e["role"] == "tool" for e in ev))
        self.assertEqual("".join(e["text"] for e in ev if e.get("kind") == "delta"), "hal devam\n")
        self.assertTrue(any("çalışıyor" in e["text"] for e in ev))
        self.assertEqual(self.pair(EV)["status"], "done")

    def test_budget_flags_gated_and_configurable(self):
        self.ev()
        a = FakeProc.instances[0].argv
        self.assertEqual(a[a.index("--max-context-kib") + 1], "768")
        self.assertEqual(a[a.index("--max-compactions") + 1], "24")
        self.assertEqual(a[a.index("--max-io-mib") + 1], "2048")
        self.assertNotIn("--session", a)
        FakeProc.instances = []
        self.cfg.review_max_context_kib = 1024
        self.ev(supports_flag=lambda b, f: f != "--max-compactions")
        a = FakeProc.instances[0].argv
        self.assertEqual(a[a.index("--max-context-kib") + 1], "1024")
        self.assertNotIn("--max-compactions", a)

    def test_create_dir_flag_and_draft_recovery(self):
        # --allow-create-dir yalnız ikili destekliyorsa; model taslağı yazıp stdout boş kalırsa taslak rapor olur (maskeli)
        self.ev(supports_flag=lambda b, f: f != "--allow-create-dir")
        self.assertNotIn("--allow-create-dir", FakeProc.instances[0].argv)
        self.assertNotIn(".model.md", FakeProc.instances[0].argv[-1])
        FakeProc.instances = []
        report = "## R-1 | P2 | a.py:1 | taslak\ngövde " + SECRET

        def popen(argv, **k):
            m = [w for w in argv[-1].split() if w.endswith(".model.md")][0]
            self.assertTrue(m.startswith(argv[argv.index("--allow-create-dir") + 1]))
            with open(m, "w", encoding="utf-8") as f:
                f.write(report)
            return FakeProc(argv, out="", err="", rc=1, **k)
        res = self.ev(popen=popen)
        draft = rv.draft_path(res["file"])
        self.assertTrue(os.path.isfile(draft))
        self.assertNotIn(SECRET, open(draft).read())           # ham taslak diskte maskelenir
        self.assertIn("taslak", open(res["file"]).read())
        self.assertNotIn(SECRET, open(res["file"]).read())
        self.assertEqual(len(rv.parse_findings(open(res["file"]).read())), 1)
        self.assertNotEqual(self.pair(EV)["status"], "running")

    def test_streamed_report_recovery_on_empty_stdout(self):
        # stdout boş (zaman aşımı/çökme) ama rapor akışta (--stream delta) geldi: son R-1 başlığından itibaren kurtarılır
        rep = ("tarıyorum\n## R-1 | P3 | eski:1 | ilk taslak\nvazgeçtim\n"
               "## R-1 | P2 | a.py:1 | gerçek\ngövde " + SECRET + "\n## R-2 | P3 | b.py:2 | ikinci\ngövde iki\n")
        res = self.ev(popen=self.popen(out="", err="UnifiedCLI tool: read_file(a.py)\n" + rep, rc=1))
        txt = open(res["file"]).read()
        self.assertTrue(txt.startswith("## R-1 | P2 | a.py:1 | gerçek"))
        self.assertNotIn(SECRET, txt)
        self.assertNotIn("ilk taslak", txt)
        self.assertEqual([f["ref"] for f in rv.parse_findings(txt)], ["R-1", "R-2"])
        self.assertEqual(self.pair(EV)["status"], "partial")
        lg = wr.IoLog(os.path.join(tempfile.mkdtemp(), "x.io.jsonl"))
        lg.feed_err("sadece sohbet\n")
        self.assertEqual(lg.streamed_report(), "")

    def test_report_and_draft_mask_password_learned_from_stream(self):
        # parola akışta DSN içinde görüldü (öğrenildi); rapor/taslakta yalnız çıplak geçer: ikisi de maskelenmeli
        pw = "zq8Pw0rdXyz"
        stream = f"UnifiedCLI tool: read_file(x.py)\nUnifiedCLI model: postgresql://u:{pw}@h:5/d\n"
        answer = json.dumps({"answer": f"## R-1 | P1 | x.py:6 | gömülü parola\ngövde parola={pw} düz yazılmış"})
        res = self.ev(popen=self.popen(out=answer, err=stream, rc=0))
        self.assertNotIn(pw, open(res["file"]).read())
        FakeProc.instances = []

        def popen(argv, **k):
            m = [w for w in argv[-1].split() if w.endswith(".model.md")][0]
            with open(m, "w", encoding="utf-8") as f:
                f.write(f"## R-1 | P1 | x.py:6 | taslak\ngövde {pw} burada")
            return FakeProc(argv, out="", err=stream, rc=1, **k)
        res = self.ev(popen=popen)
        self.assertNotIn(pw, open(res["file"]).read())
        self.assertNotIn(pw, open(rv.draft_path(res["file"])).read())

    def test_recovered_text_with_clean_exit_is_partial_not_done(self):
        # stdout boş + rc 0 + akıştan kurtarılan rapor: tam sonuç sayılmaz
        rep = "UnifiedCLI tool: t()\n## R-1 | P2 | a.py:1 | kurtarılan\ngövde\n"
        self.ev(popen=self.popen(out="", err=rep, rc=0))
        self.assertEqual(self.pair(EV)["status"], "partial")

    def test_no_findings_report_recovered_from_stream(self):
        self.ev(popen=self.popen(out="", err="UnifiedCLI tool: t()\ninceledim\nBULGU YOK\n", rc=1))
        p = self.pair(EV)
        self.assertEqual(p["status"], "partial")
        self.assertIn("BULGU YOK", open(p["file"]).read())
        lg = wr.IoLog(os.path.join(tempfile.mkdtemp(), "y.io.jsonl"))
        lg.feed_err("BULGU YOK bu bir sohbet cümlesi değil mi\ndevam ediyorum\n")
        self.assertEqual(lg.streamed_report(), "")                                   # tek başına sohbet satırı sayılmaz

    def test_deltas_memory_bounded_keeps_tail_report(self):
        old = wr.DELTA_KEEP_CHARS
        wr.DELTA_KEEP_CHARS = 3000
        self.addCleanup(setattr, wr, "DELTA_KEEP_CHARS", old)
        lg = wr.IoLog(os.path.join(tempfile.mkdtemp(), "z.io.jsonl"))
        for i in range(400):
            lg.feed_err(f"sohbet satiri {i} " + "x" * 30 + "\n")
        lg.feed_err("## R-1 | P2 | a.py:1 | son\ngövde\n")
        self.assertLess(sum(len(d) for d in lg._deltas), 3000 + 200)
        self.assertTrue(lg.streamed_report().startswith("## R-1 | P2 | a.py:1 | son"))

    def test_recover_draft_atomic_and_ignores_symlink(self):
        d = tempfile.mkdtemp()
        md = os.path.join(d, "20261024000000.md")
        dp = rv.draft_path(md)
        open(dp, "w").write("## R-1 | P2 | a:1 | t\nparola=" + SECRET)
        text, rec = wr._recover_draft(md, "", [])
        self.assertTrue(rec)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(SECRET, open(dp).read())
        self.assertEqual(os.listdir(d), [os.path.basename(dp)])                         # .tmp kalmaz
        victim = os.path.join(d, "victim.txt")
        open(victim, "w").write("ONEMLI " + SECRET)
        os.remove(dp)
        os.symlink(victim, dp)
        self.assertEqual(wr._recover_draft(md, "", []), ("", False))
        self.assertIn(SECRET, open(victim).read())                                     # symlink hedefine dokunulmadı

    def test_tool_call_cap_and_usage_log_flags(self):
        res = self.ev()
        a = FakeProc.instances[0].argv
        self.assertEqual(a[a.index("--max-tool-calls") + 1], "30")
        self.assertEqual(a[a.index("--usage-log") + 1], res["file"][:-3] + ".usage.jsonl")
        self.assertNotIn("--show-usage", a)                  # stderr'i kirletir (akış kurtarma): yalnız usage-log
        FakeProc.instances = []
        self.cfg.review_max_tool_calls = 40
        self.ev(supports_flag=lambda b, f: f not in ("--usage-log", "--max-tool-calls"))
        a = FakeProc.instances[0].argv
        self.assertNotIn("--usage-log", a)
        self.assertNotIn("--max-tool-calls", a)
        FakeProc.instances = []
        self.ev()
        self.assertEqual(FakeProc.instances[0].argv[FakeProc.instances[0].argv.index("--max-tool-calls") + 1], "40")

    def test_script_read_flag_is_opt_in_and_read_only(self):
        self.ev()
        self.assertFalse([x for x in FakeProc.instances[0].argv if x.startswith("--allow-script")])   # varsayılan KAPALI
        FakeProc.instances = []
        self.cfg.review_evren_script = "read"
        self.ev()
        a = FakeProc.instances[0].argv
        self.assertIn("--allow-script=read", a)
        self.assertNotIn("--allow-script=full", a)
        self.assertFalse([x for x in a if x.startswith("--allow-edit") or x.startswith("--allow-fetch") or x == "--allow-exec"])
        FakeProc.instances = []
        self.ev(supports_flag=lambda b, f: f != "--allow-script")          # eski ikili: bayrak gitmez
        self.assertFalse([x for x in FakeProc.instances[0].argv if x.startswith("--allow-script")])

    def test_wall_and_request_timeout_flags(self):
        # ae/mimo-v2.6-pro 20 dk duvarda bitmemişti: ucli kendi duvar/istek süresini bilsin (ayarlı, varsayılan 900/300)
        self.ev()
        a = FakeProc.instances[0].argv
        self.assertEqual(a[a.index("--max-wall-secs") + 1], "900")
        self.assertEqual(a[a.index("--request-timeout-secs") + 1], "300")
        FakeProc.instances = []
        self.cfg.review_max_wall_secs = 600
        self.cfg.review_request_timeout_secs = 120
        self.ev()
        a = FakeProc.instances[0].argv
        self.assertEqual((a[a.index("--max-wall-secs") + 1], a[a.index("--request-timeout-secs") + 1]), ("600", "120"))
        for off in (0,):                                    # 0 = geri al: bayrak hiç gitmez
            FakeProc.instances = []
            self.cfg.review_max_wall_secs = off
            self.cfg.review_request_timeout_secs = off
            self.ev()
            a = FakeProc.instances[0].argv
            self.assertNotIn("--max-wall-secs", a)
            self.assertNotIn("--request-timeout-secs", a)
        FakeProc.instances = []
        self.cfg.review_max_wall_secs = 900
        self.cfg.review_request_timeout_secs = 300
        self.ev(supports_flag=lambda b, f: f not in ("--max-wall-secs", "--request-timeout-secs"))   # eski ikili: bayrak yok
        a = FakeProc.instances[0].argv
        self.assertNotIn("--max-wall-secs", a)
        self.assertNotIn("--request-timeout-secs", a)

    def test_recover_leaves_io(self):
        res = self.ev()
        io = wr.io_path_for(res["file"])
        before = open(io).read()
        rv.update_pair(self.paths, "proj", EV, status="running")
        wr.recover_on_start(self.paths)
        self.assertEqual(open(io).read(), before)


class TestChatApi(_Api):
    def mk(self, lines, status="done"):
        p = sw.paths_for("rev")
        md = rv.review_path(p.reviews, "a", T1, 1_700_000_000)
        os.makedirs(os.path.dirname(md), exist_ok=True)
        with open(md, "w") as f:
            f.write("x")
        io = wr.io_path_for(md)
        with open(io, "w") as f:
            f.write("".join(json.dumps(x) + "\n" for x in lines))
        rv.update_pair(p, "a", T1, status=status, started_at=1_700_000_000.0, finished_at=1_700_000_100.0, file=md, io_file=io)
        return p, md, io

    def test_chat_conversion_and_runs_row(self):
        p, md, io = self.mk([
            {"role": "user", "text": "P", "kind": "prompt"},
            {"role": "tool", "text": "read_file(a)", "kind": "call"},
            {"role": "assistant", "text": "he", "kind": "delta"}, {"role": "assistant", "text": "llo", "kind": "delta"},
            {"role": "assistant", "text": '{"answer":"hello"}', "kind": "result"}])
        rel = os.path.relpath(io, p.reviews)
        r = ws.http_get("/api/steward/review/chat", {"steward": ["rev"], "path": [rel]})
        self.assertTrue(r["ok"])
        self.assertEqual([(m["role"]) for m in r["messages"]], ["user", "tool", "assistant"])
        self.assertEqual(r["messages"][2]["text"], "hello")
        self.assertFalse(r["running"])
        r2 = ws.http_get("/api/steward/review/chat", {"steward": ["rev"], "path": [os.path.relpath(md, p.reviews)]})
        self.assertTrue(r2["ok"])                                # .md eşi de kabul
        runs = ws.http_get("/api/steward/review/runs", {})["runs"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["project"], "a")
        self.assertTrue(runs[0]["title"].startswith("review · a · evren/m1 · 20"))
        self.assertEqual(runs[0]["duration"], 100.0)

    def test_runs_are_newest_first_across_projects(self):
        """Sıra koşu zamanı: yol sırası (`a/...` < `z/...`) yeni koşuyu eski projenin arkasına atmaz."""
        p = sw.paths_for("rev")
        for proj, ts in (("z", 1_700_000_000), ("a", 1_700_005_000), ("m", 1_700_002_000)):
            md = rv.review_path(p.reviews, proj, T1, ts)
            os.makedirs(os.path.dirname(md), exist_ok=True)
            with open(md, "w") as f:
                f.write("x")
            io = wr.io_path_for(md)
            with open(io, "w") as f:
                f.write('{"role":"user","text":"x"}\n')
            rv.update_pair(p, proj, T1, status="done", started_at=float(ts), finished_at=ts + 10.0, file=md, io_file=io)
        runs = ws.http_get("/api/steward/review/runs", {})["runs"]
        self.assertEqual([r["project"] for r in runs], ["a", "m", "z"])

    def test_result_without_stream_is_answer(self):
        self.assertEqual(wr.io_to_messages([{"role": "assistant", "kind": "result", "text": '{"answer":"A"}'}])[0]["text"], "A")

    def test_path_security(self):
        p, md, io = self.mk([{"role": "user", "text": "x"}])
        secret = os.path.join(p.root, "findings.json.io.jsonl")
        with open(secret, "w") as f:
            f.write('{"role":"user","text":"s"}\n')
        os.symlink(secret, os.path.join(p.reviews, "link.io.jsonl"))
        for bad in ("../findings.json.io.jsonl", secret, "/etc/passwd", "link.io.jsonl", "", "x\x00.io.jsonl", "a.txt"):
            for ep in ("chat", "io"):
                self.assertFalse(ws.http_get(f"/api/steward/review/{ep}", {"steward": ["rev"], "path": [bad]})["ok"], bad)

    def test_needs_reviewer(self):
        self.assertFalse(ws.http_get("/api/steward/review/chat", {"path": ["x.io.jsonl"]})["ok"])
        self.assertFalse(ws.http_get("/api/steward/review/live", {"project": ["a"], "target": ["evren/m1"]})["ok"])

    def test_live_by_pair_no_client_path(self):
        self.mk([{"role": "user", "text": "x"}])
        r = ws.http_get("/api/steward/review/live", {"steward": ["rev"], "project": ["a"], "target": ["evren/m1"]})
        self.assertTrue(r["ok"] and r["exists"])
        self.assertFalse(ws.http_get("/api/steward/review/live", {"steward": ["rev"], "project": ["a"], "target": ["../x"]})["ok"])


class TestNaming(unittest.TestCase):
    def test_review_title(self):
        self.assertEqual(rv.review_title("ncs", "evren", "glm-5.3", "20261022214000"), "review · ncs · evren/glm-5.3 · 2026-10-22 21:40")
        self.assertEqual(rv.review_title("ncs", "agy", "m", None), "review · ncs · agy/m")

    def test_steward_title_and_badge(self):
        self.assertEqual(sw.steward_title("kitap", "brain"), "değnekçi · kitap · beyin")
        self.assertEqual(sw.steward_title("iso", "project", "oiso2026"), "oiso2026 (değnekçi: iso)")
        idx = {"owners": {"ncs": "iso"}, "brains": {"degnekci_iso": "iso", "degnekci": "default"}}
        self.assertEqual(sw.steward_badge("degnekci_iso", idx)["role"], "brain")
        self.assertEqual(sw.steward_badge("degnekci_zzz", idx)["sid"], "zzz")
        b = sw.steward_badge("ncs20261019", idx)
        self.assertEqual((b["role"], b["sid"], b["title"]), ("project", "iso", "ncs20261019 (değnekçi: iso)"))
        self.assertIsNone(sw.steward_badge("other", idx))


if __name__ == "__main__":
    unittest.main()


class ReportIncompleteTests(unittest.TestCase):
    def test_budget_exhausted_without_finding_is_incomplete(self):
        from claudeops import review as rv
        self.assertTrue(rv.report_incomplete("... tool-call budget exhausted ...\n\n## Bulgular\n\nBULGU YOK"))
        self.assertTrue(rv.report_incomplete("## İncelemenin durumu: tamamlanmadı (araç bütçesi tükendi)"))

    def test_real_findings_or_clean_reports_are_not(self):
        from claudeops import review as rv
        self.assertFalse(rv.report_incomplete("budget exhausted\n\n## R-1 | P1 | a.py:1 | x"))
        self.assertFalse(rv.report_incomplete("## Bulgular\n\nBULGU YOK"))
        self.assertFalse(rv.report_incomplete(""))
