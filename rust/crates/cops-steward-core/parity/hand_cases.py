#!/usr/bin/env python3
"""Kayıtlı vektörlerin kapsamadığı dallar/kenar durumları (gruplar C ve D): girdiler burada elle yazılır, beklenen değer
Python işlevi çalıştırılarak alınır. Çıktı `fixtures/hand/<işlev>.jsonl.gz` (aynı satır biçimi; `harness::cases` ikisini de
oynatır). Kullanım: `python3 -I parity/hand_cases.py`."""
import dataclasses, functools, glob, gzip, itertools, json, os, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402
env.isolate()
from claudeops import steward as sw  # noqa: E402

NOW = 1_795_700_000.5
sw._now = lambda: NOW
OUT = {}


def enc(v):
    if dataclasses.is_dataclass(v):
        return {k: enc(x) for k, x in dataclasses.asdict(v).items()}
    if isinstance(v, dict):
        return {k: enc(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [enc(x) for x in v]
    if isinstance(v, (set, frozenset)):
        return sorted(enc(x) for x in v)
    return v


def add(name, args, call=None, extra=None):
    """`args`: Python parametre adları; `call` verilmezse `sw.<name>(**args)`."""
    before = json.loads(json.dumps(enc(args)))
    ret = call() if call else getattr(sw, name)(**args)
    rec = {"args": {**before, **(extra or {})}, "ret": enc(ret), "now": NOW}
    after = {k: enc(v) for k, v in args.items() if enc(v) != before[k]}
    if after:
        rec["after"] = after
    OUT.setdefault(name, []).append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))


P, V, C = sw.Project, sw.SessionView, sw.Config
Q = functools.partial(sw.Question, created_at=0.0)
LONG = "çğışöü İ 😀 " * 80

# ── kartlar ──
for t in ["", " ", "{", "}{", "{}", "[]", "x {\"a\": 1} y", "{\"goal\": null}", "{\"goal\": 5, \"phase_guess\": \" PLANNED \"}",
          "{\"goal\": [1, 2.5, true, null, {\"k\": \"v'\"}], \"next_step\": false}", "{\"open_tbds\": \"tek\", \"blockers\": 3, \"recent_done\": [0, \"\", \"  \", null, \"a\\n b\", 7, false, \"c\", \"d\", \"e\", \"f\", \"g\", \"h\", \"i\", \"j\"]}",
          "önce\n```json\n{\"goal\": \"çit {iç}\"}\n```\nsonra {\"goal\": \"dış\"}", "```\u001c{\"next_step\": \"a\"}\u001f```", "``` json {\"goal\": \"x\"} ```",
          "```json\n{\"goal\": \"a\"}\n```\n```json\n{\"goal\": \"b\"}\n```", "{\"goal\": \"a\"} {\"goal\": \"b\"}", "{\"goal\": \"a\", \"goal\": \"b\"}",
          "{'goal': 'x'}", "{\"goal\": \"x\",}", "{\"goal\": \"satır\nsonu\"}", "\u00a0{\"goal\": \"" + LONG + "\", \"phase_guess\": \"İDEA\"}\u2028",
          "{\"phase_guess\": \"done\", \"open_tbds\": [\"" + LONG + "\"]}", "{\"goal\": 1.50, \"next_step\": 1e22}"]:
    add("parse_card_json", {"text": t})
for text, n in [("", 5), ("abc", 3), ("abcd", 3), ("ab   cd", 4), ("😀😀😀😀", 3), ("a b c", 0), ("", 0), (" x ", 1), ("xy", 1), (LONG, 400), (LONG, 7)]:
    add("_clip", {"text": text, "n": n})
    add("_short", {"text": text, "n": n})
for v in [None, 0, 5, True, [], {}, {"a": 1}, "", "  ", "x", [None, "", 0, False, " ", 1.5, ["a"], {"b": None}], [LONG] * 10]:
    add("_str_list", {"v": v})
    add("_short", {"text": v})
for t in ["", "TBD", "- TBD#1 a\n* tbd\n  ### • TBD#2   b  \n#-*TBD\n\n- - \nx", "TBD " + LONG, "\n".join(f"- TBD#{i}" for i in range(12)),
          "a\u2028TBD u\u000bTBD v", "-\u00a0TBD nbsp", "- \u00a0- TBD iç"]:
    add("_tbd_lines", {"text": t})
for d in [{}, {"GOAL.md": ""}, {"GOAL.md": "# a\n\n   # b\n"}, {"GOAL.md": "# a\r\n  amaç   bu \nikinci"}, {"GOAL.md": LONG}, {"TODO.md": "x"}]:
    add("_goal_from_docs", {"docs": d})
    for proj in [None, P("p", goal="", phase="bozuk"), P("p", goal="  kayıtlı\namaç ", phase="paused"), P("p", goal=" ")]:
        raw = {"docs": d, "git_log": ["abc 2026-01-01 konu  bir", "iki parça", "a b ", "a  b c", "x y z w", "q w e"], "last_commit": 0.0, "source_hash": "h"}
        add("raw_card_fields", {"raw": raw, "project": proj})
        for lang in ("tr", "en", "de"):
            add("build_card_prompt", {"name": "pr", "raw": raw, "project": proj, "lang": lang})
for lang in ("tr", "en"):
    for raw in [{"docs": {}, "git_log": [], "last_commit": 0.0, "source_hash": ""},
                {"docs": {}, "git_log": [], "last_commit": 0.0, "git_unknown": True, "source_hash": ""},
                {"docs": {"DONE.md": "d", "GOAL.md": "g"}, "git_log": [], "last_commit": 0.0, "source_hash": ""},
                {"docs": {}, "git_log": ["a b c"], "last_commit": 1.0, "source_hash": ""}]:
        add("build_card_prompt", {"name": "boş", "raw": raw, "project": P("boş", goal=LONG * 2), "lang": lang})
for docs in [{}, {"x.md": "yok"}, {"DONE.md": "d", "GOAL.md": "ğ" * 100, "STEWARD_BRIEF.md": "", "zz": "1"}]:
    add("raw_card_from_docs", {"docs": docs})
for cfgd, ch in [("  ", []), ("  m  ", ["haiku"]), ("", ["b-HAIKU-1", "a-haiku-9", "opus"]), ("", ["claude-haiku-4-5", "claude-haiku-3"]), ("", ["opus"])]:
    add("pick_card_model", {"configured": cfgd, "choices": ch, "fallback": "f"})
for card, running, reason in itertools.product(
        [None, {}, {"last_activity": NOW - 86399}, {"last_activity": NOW - 86400}, {"last_activity": "0", "next_step": " "},
         {"next_step": "x"}, {"next_step": "x", "blockers": ["b"]}, {"open_tbds": ["t"], "blockers": []}, {"next_step": 0, "open_tbds": []}],
        [False, True], ["", " \u001c", "bitti"]):
    add("brain_pause_verdict", {"card": card, "running": running, "reason": reason})
for card, hours in itertools.product(
        [None, {}, {"stale": True}, {"source_hash": "h"}, {"source_hash": "h", "stale": 1}, {"source_hash": "h", "updated_at": NOW - 7200},
         {"source_hash": "h", "updated_at": NOW - 7200, "attempt_at": NOW - 10}, {"source_hash": "h", "updated_at": NOW - 10, "attempt_at": NOW - 7200},
         {"attempt_hash": "h", "attempt_at": NOW - 10}, {"attempt_hash": "h", "attempt_at": NOW - 7200, "stale": True},
         {"attempt_hash": "z", "source_hash": "z"}, {"source_hash": None, "updated_at": "5"}], [0, 1, 24]):
    add("card_refresh_reason", {"card": card, "source_hash": "h", "now": NOW, "max_age_hours": hours})
for card in [None, {}, {"next_step": ""}, {"next_step": None}, {"next_step": "x"}, {"next_step": 3}, {"next_step": ["a", None]}]:
    add("card_one_liner", {"card": card})

CARDS = [{}, {"updated_at": 0}, {"updated_at": NOW - 7300, "stale": True}, {"updated_at": NOW + 99999, "summarized": False},
         {"updated_at": str(NOW - 3600), "stale": 0, "summarized": 0}, {"summarized": None, "goal": "g"},
         {"goal": LONG, "phase_guess": "planned", "next_step": " n ", "open_tbds": [LONG, "", None, "d", "e", "f"], "blockers": "abcdefg", "recent_done": []}]
for card, tr in itertools.product(CARDS, [True, False]):
    add("card_lines", {"card": card, "tr": tr, "now": NOW})

# ── direktif ──
STORE = [Q(f"q{i}", "p", f"  soru {i} " + ("uzun😀" * 60 if i == 7 else ""), status="answered", answer=f" cevap {i} " + ("ç" * 300 if i == 6 else ""),
           answered_at=float(100 - i if i < 3 else i)) for i in range(9)]
STORE += [Q("open", "p", "açık", answer="x"), Q("blank", "p", "boş", status="answered", answer="  ", answered_at=999.0),
          Q("other", "o", "başka", status="answered", answer="y", answered_at=999.0), Q("cur", "p", "güncel", status="answered", answer="evet", answered_at=999.0)]
ANS = [None, STORE[-1], Q("r", "p", " tekrar ", status="answered", answer=" hayır ", repeats=2)]
sw.load_questions = lambda paths=None: list(STORE)
for lang, phase, answer, compact, extra in itertools.product(("tr", "en"), ("planning", "planned", "paused"), ANS, (False, True), ("", "  ek iş  ")):
    proj = P("p", phase=phase, goal=" amaç \n", notes=" not " if phase != "paused" else "  ")
    for more in ([None] if answer is None else [None, [STORE[8], STORE[1]]]):
        args = {"project": proj, "lang": lang, "extra": extra, "answer": answer, "more": more, "compact": compact}
        add("build_directive", args, extra={"questions": enc(STORE)})
add("build_directive", {"project": P("p", goal="", phase="idea")}, extra={"questions": []})

# ── tur ──
FULL = {"name": "pr", "phase": "planned", "kindp": "kitap", "goal": LONG, "idle_minutes": 12.9, "contradictions": ["ç1", LONG],
        "last_directive": LONG, "last_exchange": {"user": LONG, "assistant": LONG * 2}, "stated_next": LONG,
        "docs": {"TODO.md": LONG, "PLAN.md": "", "X": "kısa"}, "backlog": {"auto": ["a", LONG], "decide": ["d"]}, "text": LONG,
        "similar": [{"project": "p", "text": LONG, "answer": LONG}, {"project": None}, {}]}
KINDS = ["idle", "review", "idea", "due", "blocked", "routine", "ask", "özel ßi", ""]
items = [dict(FULL, kind=k, id=f"i{n}") for n, k in enumerate(KINDS)]
items += [{}, {"kind": "idea"}, {"kind": "idea", "id": None, "text": None}, {"name": "", "id": None}, {"id": 7, "idle_minutes": "3"},
          {"card": {}, "docs": {"A": "b"}}, {"card": CARDS[-1], "docs": {"A": "b"}}, {"card": CARDS[2]}, {"phase": "x", "idle_minutes": 0},
          {"backlog": {}, "last_exchange": None, "contradictions": None, "similar": None, "docs": None},
          {"backlog": {"auto": [], "decide": "xy"}, "contradictions": "ab"}]
OPEN = [Q(f"o{i}", "" if i % 3 == 0 else "p", LONG if i == 1 else f"s{i}", routine=i % 4 == 2) for i in range(16)]
for lang, open_qs, now, sub in itertools.product(("tr", "en"), (None, [], OPEN), (None, 0, 1_000_000_059.9), (items, items[:2], [])):
    add("build_tour_prompt", {"items": sub, "lang": lang, "open_qs": open_qs, "now": now})

# ── beyin CLAUDE.md ──
for lang, sid, remote, role in itertools.product(("tr", "en"), ("default", "abc"), (False, True), ("steward", "generic")):
    add("build_workspace_claude_md", {"persona": "# p\n\n \u001c\n", "lang": lang, "sid": sid, "label": "Etiket" if remote else "", "remote": remote, "role": role})
for sid, label, lang in itertools.product(("default", "ab"), ("", "L"), ("tr", "en", "x")):
    add("identity_section", {"sid": sid, "label": label, "lang": lang})

# ── motor yardımcıları ──
for model, effort, cli, sonnet in itertools.product(("", " Claude-Opus ", "gpt", "claude-fable"), ("", "high"), ("", "claude", "codex"), ("", "claude-sonnet-x")):
    add("main_session_model_effort", {"model": model, "effort": effort, "cli": cli, "sonnet": sonnet})
for last, bp, src in itertools.product(["", "ok", " OK. ", "Tamam.", "tamam..", "oK\n", "o\u212a", "ok bitti", LONG], [None, "", "bp"], ["p1", "x"]):
    v = V("p1", True, blueprint=bp, last_assistant=last)
    qs = [Q('qı"\\\n\u007f😀', "bp", "t", source="z"), Q("a", "p1", "t", status="answered"), Q("b", "zz", "t", source=src), Q("a0", "", "t", source="p1")]
    add("item_signature", {"v": v, "projects": {"bp": P("bp", phase="planning"), "p1": P("p1", phase="idea")}, "questions": qs})
for notes in ["", "PID 1", "PID 12 pid:34 Pid=#5 PID # 56 PID123456789 xPID 77", "PİD 4567 pıd 89", "PID \u0661\u0662\u0663 PID \U0001d7d9\U0001d7da PID \uff14\uff15",
              "KAPIDA BEKLİYOR", "KAPİDA bekliyor", "kapıda  bekl", "Waiting AT the Gate", "waıtıng in the gate", "kapida\nbekliyor PID 99 PID 099 PID 100"]:
    add("note_claims", {"notes": notes})
base = {"p": P("p")}
qs = []
for i, (proj, src, at, st, dl) in enumerate(itertools.product(("", "p", "gone", "brain"), ("", "live1", "dead"), (0.0, NOW - 21600, NOW - 21599), ("answered", "open"), (0.0, 5.0))):
    qs.append(Q(f"s{i}", proj, "t", status=st, source=src, answered_at=at, created_at=NOW - 30000 if at == 0 else 0.0, delivered_at=dl))
for brain, live in itertools.product(("", "brain"), (None, set(), {"live1"}, {"brain"}, {"gone", "brain"})):
    add("stale_answers", {"questions": qs, "projects": base, "cfg": C(brain_name=brain), "now": NOW, "live": live})
mix = [{"kind": k, "id": i} for i, k in enumerate(["idle", "ask", "blocked", "routine", None, "due"] * 8)] + [{"id": "x"}]
for gate in ("off", "shadow", "on", ""):
    add("cut_tour_items", {"items": mix, "ask_gate": gate})
for state in [{}, {"ask_seen": None}, {"ask_seen": {"a": {"n": "4", "at": 1}, "b": None, "c": {"n": 2.9}, "z": 1}, "k": 1}]:
    add("mark_ask_seen", {"state": state, "items": [{"kind": "ask", "id": i} for i in ("a", "b", "c", "a", None, 5)] + [{"kind": "idle", "id": "z"}], "now": NOW})

dst = os.path.join(env.CRATE, "fixtures", "hand")
os.makedirs(dst, exist_ok=True)
for old in glob.glob(os.path.join(dst, "*.jsonl.gz")):
    os.remove(old)
for name, lines in sorted(OUT.items()):
    with open(os.path.join(dst, name + ".jsonl.gz"), "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as f:
        f.write("".join(x + "\n" for x in lines).encode())
print("işlev:", len(OUT), "kayıt:", sum(map(len, OUT.values())))
