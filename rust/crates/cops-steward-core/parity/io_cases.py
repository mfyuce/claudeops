#!/usr/bin/env python3
"""G/Ç işlevlerinin içindeki saf mantık (grup 7): Python işlevi GERÇEK dosyalarla (yalıtılmış geçici dizin) çalıştırılır,
girdisi (G/Ç'nin döndürdüğü değerler) ve sonucu `fixtures/io/<işlev>.json.gz`a yazılır; `tests/parity/iocore.rs` aynı
girdileri Rust çekirdeğine geri çağrı/parametre olarak verip sonucu karşılaştırır. Yollar göreli (çalışma dizini geçici
dizin) ve git tarihleri sabit: çıktı belirlenimli. Kullanım: `python3 -I parity/io_cases.py`."""
import dataclasses, glob, gzip, json, os, subprocess, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402
TMP = env.isolate()
from claudeops import steward as sw, review_remote, settings as settings_mod, periodic  # noqa: E402

NOW = 1_795_700_000.5
sw._now = lambda: NOW
OUT = {}
WORK = os.path.join(TMP, "work")
os.makedirs(WORK)
os.chdir(WORK)
LONG = "çğışöü İ 😀 " * 80


def enc(v):
    if dataclasses.is_dataclass(v):
        return {k: enc(x) for k, x in dataclasses.asdict(v).items()}
    if isinstance(v, dict):
        return {k: enc(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [enc(x) for x in v]
    if isinstance(v, (set, frozenset)):
        return sorted(enc(x) for x in v)
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return {"__float__": str(v)}       # JSON'da NaN/inf yok
    return v


def err(e):
    return {"__error__": type(e).__name__, "msg": str(e)}


def add(name, rec):
    OUT.setdefault(name, []).append(json.loads(json.dumps(enc(rec), ensure_ascii=False)))


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def read(path):
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()
    except OSError:
        return None


# ── persona_text ──
real_persona = sw.BUNDLED_PERSONA
for bundled in (real_persona, os.path.join(TMP, "yok.md")):
    sw.BUNDLED_PERSONA = bundled
    for ov in ["", "  ", "\n\t", "  özel  ", "\u00a0x\u2028", "a\nb", "😀", "\u001cç\u001f", " İ\r\n"]:
        add("persona_text", {"override": ov, "bundled": read(bundled), "ret": sw.persona_text(ov)})
sw.BUNDLED_PERSONA = real_persona

# ── tour_delivery ──
n_case = 0
for prompt in ["", "kısa", "x" * sw.TOUR_INLINE_MAX_CHARS, "x" * (sw.TOUR_INLINE_MAX_CHARS + 1), "😀" * sw.TOUR_INLINE_MAX_CHARS,
               "😀" * (sw.TOUR_INLINE_MAX_CHARS + 1), LONG * 5]:
    for now, lang, pre in [(1000.0, "tr", []), (1000.9, "en", ["tour-1.md", "tour-2.md"]), (-5.5, "de", []),
                           (1e20, "tr", ["a", "b", "c", "d", "e", "f", "tour-999.md"]), (-0.4, "en", ["z"]),
                           (1000.0, "tr", ["tour-1000.md"]), (float("nan"), "tr", []), (float("inf"), "en", [])]:
        n_case += 1
        ws = f"ws{n_case}"
        for p in pre:
            write(os.path.join(ws, "tours", p), "eski")
        try:
            ret = sw.tour_delivery(prompt, ws, now, lang)
        except (ValueError, OverflowError) as e:
            ret = err(e)
        d = os.path.join(ws, "tours")
        left = sorted(os.listdir(d)) if os.path.isdir(d) else None
        add("tour_delivery", {"prompt": prompt, "workspace": ws, "now": now if now == now and abs(now) != float("inf") else str(now),
                              "lang": lang, "pre": pre, "ret": ret, "left": left})

# ── _git_recent (sahte alt süreç) ──
os.makedirs(os.path.join("repo", ".git"), exist_ok=True)
os.makedirs("plain", exist_ok=True)
real_run = sw.subprocess.run
for cwd in ["repo", "plain", ""]:
    for n in (5, 1):
        for rc, stdout in [(0, "abc1234\t1700000000\t2023-11-14\tilk commit\n"),
                           (0, "a\t1\t2020-01-01\tkonu\tsekme\tiçinde\nkısa\tsatır\nb\tnan\t2020-01-02\tnan zaman\n"
                               "c\t  12_5  \t2020-01-03\t\nd\tinf\t2020-01-04\tsonsuz\ne\t-7\t2020\tnegatif"),
                           (0, "x\t5\td\tönce\u2028sonra\ty\r\nz\t1e3\td\tbilimsel\x1c\n\n"), (0, ""), (128, "a\t1\td\ts\n"),
                           (0, "ç\t１２\tğ\tUnicode rakam\n"), (0, "r\t3\tday\tsubj\r\nq\t9\tday\tsubj2\r")]:
            calls = []

            def fake(argv, **kw):
                calls.append(list(argv))
                return subprocess.CompletedProcess(argv, rc, stdout, "")
            sw.subprocess.run = fake
            ret = sw._git_recent(cwd, n)
            add("_git_recent", {"cwd": cwd, "n": n, "has_git": os.path.exists(os.path.join(cwd, ".git")) if cwd else False,
                                "rc": rc, "stdout": stdout, "argv": calls[0] if calls else None, "ret": ret})
    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 5)
    sw.subprocess.run = boom
    add("_git_recent", {"cwd": cwd, "n": 5, "has_git": bool(cwd) and os.path.exists(os.path.join(cwd, ".git")), "rc": None,
                        "stdout": None, "argv": None, "ret": sw._git_recent(cwd)})
sw.subprocess.run = real_run

# ── build_raw_card (gerçek belge ve git) ──
GIT_ENV = dict(os.environ, GIT_AUTHOR_DATE="2026-01-02T03:04:05+00:00", GIT_COMMITTER_DATE="2026-01-02T03:04:05+00:00",
               GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, "-c", "user.email=t@t", "-c", "user.name=t", "-c", "init.defaultBranch=main", *args],
                   check=True, capture_output=True, text=True, env=GIT_ENV)


def raw_case(cwd):
    heads = {d: sw._read_doc_head(cwd, d) for d in sw.CARD_DOCS} if cwd else {}
    add("build_raw_card", {"cwd": cwd, "heads": heads, "git": sw._git_recent(cwd), "ret": sw.build_raw_card(cwd)})


raw_case("")
os.makedirs("bos")
raw_case("bos")
docs = {"GOAL.md": "# amaç\nBir kitap yazmak\n", "TODO.md": "- [ ] bölüm 3\r\n", "PLAN.md": "   \n\t", "DONE.md": LONG * 3,
        "STEWARD_BRIEF.md": "\u00a0brief\u2028", "TOBEDECIDED.md": "😀 TBD#1"}
os.makedirs("r1")
for fn, body in docs.items():
    write(os.path.join("r1", fn), body)
with open(os.path.join("r1", "CLAUDE.md"), "w") as f:
    f.write("gizli")
raw_case("r1")      # git deposu değil: yalnız belgeler
git("r1", "init", "-q")
git("r1", "add", "-A")
git("r1", "commit", "-q", "-m", "ilk commit")
raw_case("r1")
git("r1", "commit", "-q", "--allow-empty", "-m", "ikinci\tsekme çğ")
raw_case("r1")
with open(os.path.join("r1", "GOAL.md"), "wb") as f:
    f.write(b"bozuk \xff\xfe utf8\n")
raw_case("r1")
os.makedirs(os.path.join("r1", "alt"))
raw_case(os.path.join("r1", "alt"))   # .git yok: üst deponun geçmişi alınmaz

# ── transfer_project ──
STEWARDS = ["default", "aa", "bb", "rv"]
REVIEWERS = frozenset({"rv"})
sw.reviewer_ids = lambda: REVIEWERS
real_ids = settings_mod.steward_ids


def jobs_path(sid):
    return sw._pp(sid).jobs


def snapshot():
    return {sid: {"projects": sw.load_projects(sid), "questions": sw.load_questions(sid),
                  "jobs": sw._load_json(jobs_path(sid), [])} for sid in STEWARDS}


def reset(layout):
    for sid in STEWARDS:
        spec = layout.get(sid, {})
        sw.save_projects({n: sw.Project(name=n, phase="planned", goal=f"{n} amacı") for n in spec.get("projects", [])}, sid)
        sw.save_questions([sw.Question(**q) for q in spec.get("questions", [])], sid)
        if "jobs" in spec:
            sw._save_json(jobs_path(sid), spec["jobs"])
        elif os.path.exists(jobs_path(sid)):
            os.remove(jobs_path(sid))


QS = [dict(id="q1", project="p", text="açık", created_at=1.0, status="open"),
      dict(id="q2", project="p", text="cevaplı iletildi", created_at=2.0, status="answered", answer="a", delivered_at=5.0),
      dict(id="q3", project="p", text="cevaplı iletilmedi", created_at=3.0, status="answered", answer="b"),
      dict(id="q4", project="başka", text="başka proje", created_at=4.0, status="open"),
      dict(id="q5", project="p", text="iptal", created_at=5.0, status="dismissed", delivered_at=0.0)]
JOBS = [{"id": 1, "project": "p"}, {"id": 2, "project": "başka"}, "metin", {"id": 3, "project": "p", "n": 1.0}, {"id": 4}]
LAYOUTS = [
    {"aa": {"projects": ["p", "başka"], "questions": QS, "jobs": JOBS}, "bb": {"projects": ["x"], "jobs": [{"id": 9, "project": "x"}]}},
    {"aa": {"projects": ["p"], "questions": QS, "jobs": JOBS}},                         # hedefte iş dosyası yok
    {"aa": {"projects": ["p"], "jobs": {"bozuk": True}}, "bb": {"jobs": []}},          # liste değil: iş taşınmaz
    {"aa": {"projects": ["p"], "jobs": [{"id": 2, "project": "başka"}]}, "bb": {"jobs": [{"id": 7, "project": "p"}]}},
    {"default": {"projects": ["p"], "questions": QS}},
    {"aa": {"projects": ["p"]}, "bb": {"projects": ["p"]}},                              # iki yerde (çakışma)
    {"rv": {"projects": ["p"]}},                                                         # yalnız reviewer'da
    {"aa": {"projects": ["çğ"]}},
    {},
]
for layout in LAYOUTS:
    for ids in (["default", "aa", "bb", "rv"], ["default", "aa"]):
        settings_mod.steward_ids = lambda ids=ids: list(ids)
        for name in ["p", "çğ", "yok"]:
            for to in ["bb", "aa", "default", "rv", "zz", "Bad!", "default\n"]:
                reset(layout)
                sw._LOG_SEEN.clear()
                before = snapshot()
                owner = sw.project_owner(name)
                try:
                    ret = sw.transfer_project(name, to)
                except (ValueError, sw.ReviewerRefused) as e:
                    ret = err(e)
                after = snapshot()
                logs = {sid: [{k: v for k, v in e.items() if k != "ts"} for e in sw.tail_log(50, sid) if e.get("event") == "transfer"]
                        for sid in STEWARDS}
                for sid in STEWARDS:
                    try:
                        os.remove(sw._pp(sid).log)
                    except OSError:
                        pass
                add("transfer_project", {"name": name, "to_sid": to, "steward_ids": ids, "reviewers": sorted(REVIEWERS),
                                         "owner": owner, "before": before, "after": after, "ret": ret, "logs": logs})
settings_mod.steward_ids = real_ids

# ── günlük: log_entries_for_date, compact_log, dry_report, missed_summary_dates ──
LOG = sw._pp(None).log
D = "2026-11-20"


def tick(ts, **kw):
    return json.dumps({"ts": ts, "event": "tick", **kw}, ensure_ascii=False) + "\n"


LOGS = {
    "boş": "",
    "temel": (tick(f"{D}T00:00:01", trigger="timer", mode="act") + tick(f"{D}T00:02:01", trigger="manual", error="x", mode="observe")
              + json.dumps({"ts": f"{D}T00:03:00", "event": "action", "kind": "start", "ok": True}) + "\n"
              + tick(f"{D}T23:59:00", mode="") + json.dumps({"ts": "2026-11-21T00:00:01", "event": "tick", "trigger": "timer"}) + "\n"
              + tick("2026-11-21T00:02:00", trigger="timer")),
    "sonda": tick(f"{D}T10:00:00", trigger="timer", mode=None) + tick(f"{D}T11:00:00", mode=5, error=0) + "son satır sonsuz",
    "crlf": tick(f"{D}T10:00:00", trigger="timer").replace("\n", "\r\n") + "bozuk\r" + tick(f"{D}T12:00:00", error=[], mode={"a": 1}),
    "bozuk": ('{"ts": "' + D + 'T01:00:00", "event": "tick", bozuk\n' + tick(f"{D}T02:00:00", mode="act\"\\\n\u2028😀")
              + '{"ts":"' + D + 'T03:00:00","event":"tick"}\n' + ' {"ts": "' + D + 'T04:00:00", "event": "tick"}\n'
              + '{"ts": "' + D + 'T05:00:00", "event": "ticks", "n": 3}\n'
              + '{"ts": "2026-11-19T23:00:00", "event": "tick"}\n' + '{"ts": "2026-11-2", "event": "tick"}\n'
              + '{"ts": "' + D + 'T07:00:00", "event": "tick", "error": "", "trigger": null}\n' + "[1, 2]\n"),
    "önce": '{"ts": "2026-11-21T00:00:00", "event": "x"}\n' + tick(f"{D}T05:00:00", trigger="timer"),
    # bilinen fark: Python `json.loads` NaN/Infinity kabul eder, serde_json reddeder (Rust satırı bozuk sayar)
    "nan": (tick(f"{D}T01:00:00", trigger="timer") + '{"ts": "' + D + 'T06:00:00", "event": "tick", "x": NaN}\n'
            + '{"ts": "' + D + 'T07:00:00", "event": "tick", "mode": Infinity}\n' + '{"ts": "2026-11-21T00:00:00", "event": "y"}\n'),
    "unicode": tick(f"{D}T05:00:00", mode="çğış") + '{"ts": "２０２６-11-21T00:00:00", "event": "y"}\n' + '{"ts": "😀😀😀", "event": "z"}\n',
}
for key, text in LOGS.items():
    for date in [D, "2026-11-21", "2026-11", "", "yok", "2026-11-19"]:
        write(LOG, text)
        ret = sw.compact_log(date)
        add("compact_log", {"case": key, "date": date, "text": text, "ret": ret, "after": read(LOG)})
        write(LOG, text)
        add("log_entries_for_date", {"case": key, "date": date, "text": text, "ret": sw.log_entries_for_date(date)})
if os.path.exists(LOG):
    os.remove(LOG)
add("compact_log", {"case": "dosya yok", "date": D, "text": None, "ret": sw.compact_log(D), "after": read(LOG)})


def would(ts, kind="keepwarm", **kw):
    return json.dumps({"ts": ts, "event": f"would:{kind}", **kw}, ensure_ascii=False) + "\n"


T0 = 1_800_000_000.0     # 2027-01-15T08:00:00 UTC
DRY = {
    "temel": (would("2027-01-15T07:00:00", name="a", chars=10) + would("2027-01-15T06:00:00", name="a", chars="5")
              + would("2027-01-14T06:00:00", "wake_cap", name="b") + would("2027-01-10T06:00:00", name="eski", chars=99)
              + would("2027-01-15T07:30:00", "x:y", name=None, chars=0) + would("2027-01-15T07:31:00", name="", chars=2.9)
              + json.dumps({"ts": "2027-01-15T07:00:00", "event": "action", "note": "\"would:keepwarm\""}) + "\n"
              + would("2027-01-15T07:59:59", "idle_big_handover", name="c", chars=True)),
    "ts": ("".join(would(t, name=t) for t in ["2027-1-15T7:5:9", "2027-01-15t07:00:00", "2027-01-15T07:00:60", "2027-01-15T07:00:61",
                                                "2027-02-30T00:00:00", "0000-01-01T00:00:00", "2027-01-15 07:00:00", "2027-01-15T07:00:00Z",
                                                "2027-01-15T07:00:00.123", "２０２７-01-15T07:00:00", "2027-01- 5T07:00:00", "", "None",
                                                "2027-01-15T24:00:00", "2027-13-01T00:00:00"])
           + json.dumps({"event": "would:keepwarm", "name": "tsyok"}) + "\n" + json.dumps({"ts": 5, "event": "would:k"}) + "\n"
           + json.dumps({"ts": "2027-01-15T07:00:00", "event": None, "x": "\"would:"}) + "\n"
           + json.dumps({"ts": "2027-01-15T07:00:00"}) + ' "would:\n' + "bozuk \"would: {\n"),
    "liste": would("2027-01-15T07:00:00") + '["\\"would:x"]\n',
    "chars": would("2027-01-15T07:00:00", chars="çok"),
    "chars2": would("2027-01-15T07:00:00", chars=[1]),
    "boş": "",
}
for key, text in DRY.items():
    for rotated in (None, would("2027-01-15T05:00:00", name="d1", chars=1) + would("2027-01-15T07:30:00", name="a")):
        write(LOG, text)
        if rotated is None:
            if os.path.exists(LOG + ".1"):
                os.remove(LOG + ".1")
        else:
            write(LOG + ".1", rotated)
        for hours, now in [(72, T0), (1, T0), (0.5, T0 + 1), (0, T0), (-1, T0)]:
            try:
                ret = sw.dry_report(hours=hours, now=now)
            except Exception as e:       # noqa: BLE001  Python'un yakalamadığı istisna da vektördür
                ret = err(e)
            add("dry_report", {"case": key, "logs": [read(LOG + ".1"), read(LOG)], "hours": hours, "now": now, "ret": ret})
os.remove(LOG)
os.remove(LOG + ".1")
add("dry_report", {"case": "dosya yok", "logs": [None, None], "hours": 72, "now": T0, "ret": sw.dry_report(now=T0)})

DAY0 = 1_795_700_000.5   # 2026-11-27T10:53:20 UTC
for days in [3, 0, -2, 1, 7]:
    for dailies in [[], ["2026-11-25"], ["2026-11-24", "2026-11-26", "2026-11-20"]]:
        for text in [None, "", '{"ts": "2026-11-24T10:00:00", "event": "tick"}\n{"ts": "2026-11-26T23:59:59", "event": "x"}\n'
                     '{"ts": "2026-11-25T00:00:00", bozuk\n{"ts": "2026-11-23", "event": "y"}\n',
                     '{"ts": "2026-11-27T00:00:00", "event": "bugün"}\n']:
            sw._NO_LOG_DAYS.clear()
            for f in os.listdir(sw._pp(None).daily) if os.path.isdir(sw._pp(None).daily) else []:
                os.remove(os.path.join(sw._pp(None).daily, f))
            for dd in dailies:
                sw.write_daily(dd, "x")
            if text is None:
                if os.path.exists(LOG):
                    os.remove(LOG)
            else:
                write(LOG, text)
            add("missed_summary_dates", {"now": DAY0, "days": days, "dailies": dailies, "text": text,
                                         "ret": sw.missed_summary_dates(DAY0, days)})
for bad_now in [float("nan"), float("inf"), 1e300]:
    sw._NO_LOG_DAYS.clear()
    try:
        ret = sw.missed_summary_dates(bad_now, 1)
    except Exception as e:       # noqa: BLE001
        ret = err(e)
    add("missed_summary_dates", {"now": str(bad_now), "days": 1, "dailies": [], "text": None, "ret": ret})

# ── summary_text ──
SQ = [sw.Question(id="s1", project="p", text="açık", created_at=1.0, status="open"),
      sw.Question(id="s2", project="p", text="iletilmedi", created_at=1.0, status="answered", answer="x", answered_by="brain"),
      sw.Question(id="s3", project="p", text="iletildi", created_at=1.0, status="answered", answer="y", delivered_at=4.0,
                  answered_by="owner_phone"),
      sw.Question(id="s1", project="q", text="aynı kimlik", created_at=1.0, status="dismissed", answered_by="cops")]
SI = [sw.Idea(id="i1", text="yeni", created_at=1.0), sw.Idea(id="i2", text="eski", created_at=1.0, status="exported")]
SUM_LOG = (tick(f"{D}T00:00:01", trigger="timer", mode="act")
           + json.dumps({"ts": f"{D}T01:00:00", "event": "ask_gate", "id": "s2", "project": "p", "question": "soru", "answer": "cvp",
                         "applied": True}, ensure_ascii=False) + "\n"
           + json.dumps({"ts": f"{D}T02:00:00", "event": "action", "kind": "directive", "name": "p", "ok": True}) + "\n")
for state in [{}, {"pending_items": 3}, {"pending_items": "4"}, {"pending_items": 2.7}, {"pending_items": None},
              {"pending_items": "x"}, {"pending_items": [1]}]:
    for orph in [None, {"servers": 2, "procs": 0}, {"servers": 0, "procs": 0}, {"servers": "x"}, "metin", {"procs": "3"}, "__raise__"]:
        for date, lang, text in [(D, "tr", SUM_LOG), (D, "en", SUM_LOG), ("2026-11-22", "tr", SUM_LOG), (D, "tr", '["' + '\\"ts\\": \\"' + D + '"]\n')]:
            sw.save_state(state)
            sw.save_questions(SQ)
            sw.save_ideas(SI)
            write(LOG, text)

            def fake_orphans(orph=orph):
                if orph == "__raise__":
                    raise OSError("yok")
                return orph
            periodic.orphan_summary = fake_orphans
            try:
                ret = sw.summary_text(date, lang)
            except Exception as e:       # noqa: BLE001
                ret = err(e)
            add("summary_text", {"date": date, "lang": lang, "state": sw.load_state(), "questions": sw.load_questions(),
                                 "ideas": sw.load_ideas(), "entries": sw.log_entries_for_date(date),
                                 "orphans": orph, "ret": ret})

# ── apply_review_where_answer ──
os.environ["HOME"] = "/home/parity"
for answer in ["yerel", "yerel ~/kod/p", "local /srv/p/", "uzak", "remote please", "vazgeç", "hayır", "no", "~/x", "/abs/yol",
               "bilmiyorum", "", "çğ " * 40, "yerel, /a/b ve uzak"]:
    for local_copy in ["", "/home/parity/src/p"]:
        for exists in (True, False):
            for pname in ["p", "Bad Name!"]:
                sw.save_projects({"p": sw.Project(name="p", phase="planned", review_where="ask")} if exists else {})
                q = sw.Question(id="rq1", project=pname, text="nerede?", created_at=1.0, status="answered", answer=answer)
                sw.save_questions([q, sw.Question(id="rq2", project=pname, text="diğer", created_at=1.0)])
                if os.path.exists(LOG):
                    os.remove(LOG)
                sw._LOG_SEEN.clear()
                review_remote.find_local_copy = lambda name, local_copy=local_copy: local_copy
                before = {"projects": sw.load_projects(), "questions": sw.load_questions()}
                sw.apply_review_where_answer(q)
                events = [e for e in sw.tail_log(50) if str(e.get("event", "")).startswith("review_where")]
                for e in events:
                    e.pop("ts", None)
                add("apply_review_where_answer", {"q": q, "parsed": review_remote.parse_answer(answer), "local_copy": local_copy,
                                                  "home": os.environ["HOME"], "before": before,
                                                  "after": {"projects": sw.load_projects(), "questions": sw.load_questions()},
                                                  "events": events})

dst = os.path.join(env.CRATE, "fixtures", "io")
os.makedirs(dst, exist_ok=True)
for old in glob.glob(os.path.join(dst, "*.json.gz")):
    os.remove(old)
for name, rows in sorted(OUT.items()):
    with open(os.path.join(dst, name + ".json.gz"), "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as f:
        f.write(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode())
print("işlev:", len(OUT), "kayıt:", sum(map(len, OUT.values())))
