#!/usr/bin/env python3
"""Kayıtlı vektörlerin kapsamadığı dallar/kenar durumları (gruplar C ve D): girdiler burada elle yazılır, beklenen değer
Python işlevi çalıştırılarak alınır. Çıktı `fixtures/hand/<işlev>.jsonl.gz` (aynı satır biçimi; `harness::cases` ikisini de
oynatır). Kullanım: `python3 -I parity/hand_cases.py`."""
import dataclasses, functools, glob, gzip, hashlib, itertools, json, os, random, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402
env.isolate()
from claudeops import steward as sw  # noqa: E402

NOW = 1_795_700_000.5
REAL_LOAD_QUESTIONS = sw.load_questions     # aşağıda bazı bölümler sahtesiyle değiştirir
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
    try:
        ret = call() if call else getattr(sw, name)(**args)
    except (TypeError, ValueError) as e:      # istisna da vektördür
        ret = {"__error__": type(e).__name__, "msg": str(e)}
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

# ── TBD#370: satır sonlu adlar ve DONE-CONFIRMED anması ──
for s in ("ab", "ab\n", "ab\r\n", "ab\n\n", "default", "default\n", "all\n", "degnekci\n", "a-b\n", "a" * 16 + "\n", "a" * 47 + "\n"):
    add("valid_name", {"name": s})
    add("valid_custom_id", {"sid": s})
    add("valid_steward_id", {"sid": s})
for pre, mid, post in itertools.product(
        ["", "- ", "## ", "**", "`", "1. ", "2) ", "✅ ", "Teyit: ", "Bitti. ", "kalan 0 değil, ", "zlkrn: "],
        ["", ":", " :", "：", "**:", ":**", "**", "`", "."],
        ["", " abc1234 kalan açık iş 0", " — abc1234 0", " (abc1234) 0", " `abc1234` 0", "\u001f abc1234 0", " \u001fyazmıyorum", " yazmıyorum, iş kaldı", " geldi (\"abc1234 0\")",
         " sonrası e80e77e iş 0", " abc12 0", " abc1234x 0", " ABC1234 0", " - yok", " <hash> 0", " bitti", " *_ .!"]):
    add("scan_markers", {"text": pre + "STEWARD-DONE-CONFIRMED" + mid + post})

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

# ── grup 1: soru/fikir ──
rnd = random.Random(1)
WORDS = ["Gedik", "Stripe", "G8", "a3-5", "TBD#12", "Q-2", "STR-19", "#4", "opus", "HIGH", "HİGH", "haıku", "medium", "max", "ſonnet", "ab12",
         "ab12_x", "G8-3x", "ẋG9", "`py/a b.py`", "`web.py.`", "``", "`  x  `", "bekle", "BEKLE", "Beklet", "sorma", "akşam", "AKŞAM",
         "wait", "waıt", "WAİT", "later", "don't ask", "anlamadım", "14", "açık", "madde", "decision", "findings", "commit", "edeyim", "mi?",
         "push", "var.", "Açayım", "mı?", "İstanbul", "ılık", "ŞU", "ß", "ék", "x\u001cy", " ", "(TBD", "dosya", "kayıtları", "birinci?"]
SENT = lambda n: " ".join(rnd.choice(WORDS) for _ in range(n))
for o in [None, 0, "tek", "", [], [True, False, None, 0, 1.5, "  a \n b ", "a b", "", LONG, ["x"], {"k": 1}, "c", "d", "e", "f", "g"], {"a": 1}]:
    add("normalize_options", {"options": o})
opt_sets = [[], ["evet", "hayır"], ["Straße", "İPTAL", "ﬁnal", "sonra", "ΣΣ"], ["a", "b", "c", "d", "e", "f"]]
for o, raw in itertools.product(opt_sets, ["", "1", " 2 ", "0", "9", "01", "٢", "²", "①", "1²", "99999999999999999999999", "a", "B", "f", "z", "ç", "ß", "ﬁ", "ŉ", "ǰ", "ª",
                                           "ⅰ", "+1", "STRASSE", "iptal", "i̇ptal", "FINAL", "σς", " EVET ", "serbest  metin"]):
    add("resolve_answer", {"q": Q("q", "p", "t", options=o), "raw": raw})
for raw in ["sonra", "SONRA!", " Sonra. ", "şimdi değil", "ŞİMDİ DEĞİL", "simdi degil", "BEKLE", "beklė", "̇bekle", "_sonra", "sonra_", "tbd", "TBD?", "not  now", "ſonra",
            "sonra bakarım", "SONRA BAKARIM", "sonra bakarim", "SONRA BAKARİM", "kararları şimdi vereceğim", "KARARLARI SONRA VERECEĞİM", "later 1", "…later…", "", "!!", "daha  sonra\n"]:
    add("is_defer_answer", {"raw": raw})
texts = [SENT(rnd.randint(0, 9)) for _ in range(70)] + ["Commit edeyim mi? Durum şu.", "Durum bu. Commit edeyim mi?", "a;b: Bu soru çok uzun mu?)\nİkinci soru da var mı?`",
         "x?\u001c Yeni satır soru mu bu? ", "pr duraklatılmış, TODO.md'sinde 3 açık madde var. Açayım mı?", "pr duraklatılmış, TODO.md'sinde ٣ açık madde var. Açayım mı?\n",
         "TODO'da 14 açık madde kaldı, ne yapayım şimdi?", "TODO'da 9 açık madde kaldı, ne yapayım şimdi?", "TBD#14 maddesi 2 karar bekliyor, sürdüreyim mi?",
         "Gedik ile Stripe için `a.py` ve G8 kararı?", "sonra Chrome ile Gedik, STR-19 `x/y.md` konusu"]
for t in texts:
    for fn, arg in (("_words", "text"), ("_salient", "text"), ("topic_tokens", "text"), ("_question_sentences", "text")):
        add(fn, {arg: t})
for tok in ["", "a", "a1", "a.b", "a_b", "a-b", "²", "½", "x"]:
    add("_strong_topic", {"tok": tok})
for _ in range(60):
    a, b = (set(sw.topic_tokens(rnd.choice(texts))) for _ in range(2))
    b |= set(list(a)[:rnd.randint(0, 5)])
    add("topic_match", {"a": a, "b": b})


def rq(i, pool):
    st = rnd.choice(["open", "answered", "answered"])
    return Q(f"q{i}", rnd.choice(["p", "p", "z"]), rnd.choice(pool), created_at=NOW - rnd.choice([0, 100, 3600 * 23, 3600 * 24, 3600 * 71, 3600 * 73]),
             status=st, answer=rnd.choice(["", "evet", "bekle", "sorma artık", "anlamadım, bekle", "Wait please", "AKŞAM"]) if st == "answered" else "",
             answered_at=rnd.choice([0.0, NOW - 60, NOW - 3600 * 12, NOW - 3600 * 13, NOW - 3600 * 72, NOW - 3600 * 73]) if st == "answered" else 0.0,
             routine=rnd.random() < 0.2)


near = [texts[0] + " aynı konu uzun cümle nedir?", texts[0] + " aynı konu uzun cümle midir?", "TODO'da 14 açık madde kaldı, ne yapayım şimdi?",
        "TODO'da 9 açık madde kaldı, ne yapayım şimdi?", "Gedik Stripe `a.py` G8 opus high sürsün mü?", "G8 opus high sonra Gedik Stripe `a.py` olsun?",
        "pr duraklatılmış, TODO.md'sinde 3 açık madde var. Açayım mı?", "Durum bu. Commit edeyim mi şimdi hemen?", "Commit edeyim mi şimdi hemen? Durum bu."]
for _ in range(250):
    pool = rnd.sample(near, 3) + rnd.sample(texts, 3)
    qs = [rq(i, pool) for i in range(rnd.randint(0, 7))]
    text = rnd.choice(pool)
    for fn in ("find_answered_duplicate", "find_open_similar", "find_open_topic", "find_open_same_ask", "find_answered_hold"):
        add(fn, {"questions": qs, "project": "p", "text": text, "now": NOW})
    add("similar_answers", {"text": text, "questions": qs, "project": rnd.choice(["", "p"]), "exclude_id": rnd.choice(["", "q0"]), "limit": rnd.choice([6, 1, 0, -1])})
    add("recent_answers", {"project": "p", "exclude_id": rnd.choice(["", "q0"]), "limit": rnd.choice([5, 1, 0, -2, 99]), "questions": qs})
    add("handover_questions_note", {"questions": qs, "name": rnd.choice(["p", "x", ""]), "lang": rnd.choice(["tr", "en"]), "project": rnd.choice(["", "z"])})
many = [Q(f"q{i}", "p", LONG if i % 2 else f"s {i}", created_at=float(20 - i), asked_again=i % 3) for i in range(11)]
for lang in ("tr", "en"):
    add("handover_questions_note", {"questions": many, "name": "p", "lang": lang, "project": ""})
for hrs in [(0.5, 1.5, 2.5, 3.5)]:
    for h, lang in itertools.product(hrs, ("tr", "en")):
        qs = [Q("a", "", "t", created_at=NOW - h * 3600, notified_at=1.0), Q("b", "z", "t", created_at=NOW), Q("c", "y", "t", created_at=NOW, deferred_until=NOW + 1),
              Q("d", "x", "t", created_at=NOW, routine=True)] + [Q(f"e{i}", f"p{i % 7}", "t", created_at=NOW, deferred_until=NOW) for i in range(12)]
        add("pending_digest_text", {"questions": qs, "now": NOW, "lang": lang, "sid": "ab"})
nasty = Q("i<1>", "p&'\"", "<b>&\"'", created_at=NOW, options=["a'<\">", "b&"], detail="<d>", extra_texts=["<e>", "f'"], prev_texts=["\"p\""], source="s<", answer="<a>")
for q, state, lang in itertools.product([None, nasty, Q("x", "", "t")], ["ask", "done", "already", "missing", "denied"], ["tr", "en", "de"]):
    add("question_page_html", {"q": q, "lang": lang, "state": state, "error": "<err>", "action": "/q/x?k='\""})
docs = ["", "\n\n", "# TBD\n\n## TBD#3 konu\n- alt\n  - iç\n\n\n- TBD 31 başka\n\n", "- [ ] TBD #3: x\r\n  devam\u001c\n1) y\n", "a\n  * TBD#4\n   ek\n  - z\n  - w", "tbd3\nTBD٣ x\n"]
for text, q_text, qid in itertools.product(docs, ["", "TBD#3 için?", "tbd 99 ve TBD#4", "TBD\u001c#\u001c31", "TBD٣", "yok"], ["", "q1"]):
    add("tbd_insert_answer", {"text": text, "qid": qid, "q_text": q_text, "answer": "  evet\n yap " + (LONG if qid else ""), "date": "2026-11-26"})
for a in ["", "evet", "a b c", "a b c d", "x" * 39, "x" * 40, "ç" * 40, "a\u001cb\u001cc\u001cd"]:
    add("answer_has_action", {"answer": a})
bodies = ["", "x", "x\n", "- [ ] (t, direktif ab12) özet  metni\n", "- [x] (t, direktif ab12) özet metni", "- [ ] (t, direktif ff) özet metni y", "- [ ] (sahip cevabı q1, t) z\n\n\n"]
for b, did, sm in itertools.product(bodies, ["ab12", "cd"], ["özet metni", "başka"]):
    add("todo_insert_directive", {"body": b, "did": did, "summary": sm, "date": "2026-11-26"})
    add("todo_insert_answer", {"text": b, "qid": rnd.choice(["", "q1", "q2"]), "answer": rnd.choice(["a  b", LONG, ""]), "date": "d"})

# durumlu: rastgele soru/cevap dizisi, gerçek depo (geçici dizin), belirlenimli saat ve kimlik
sw.load_questions = REAL_LOAD_QUESTIONS
counter = itertools.count()
sw._new_id = lambda prefix: f"{prefix}{next(counter)}"
sw._unique_question_key = lambda sid: f"k{next(counter)}"


def stateful(name, fn_args, call):
    before = enc(sw.load_questions())
    ids, keys = [], []
    orig_id, orig_key = sw._new_id, sw._unique_question_key
    sw._new_id = lambda p: ids.append(orig_id(p)) or ids[-1]
    sw._unique_question_key = lambda s: keys.append(orig_key(s)) or keys[-1]
    try:
        try:
            ret = enc(call())
        except (TypeError, ValueError) as e:
            ret = {"__error__": type(e).__name__, "msg": str(e)}
    finally:
        sw._new_id, sw._unique_question_key = orig_id, orig_key
    rec = {"args": {**fn_args, "questions": before, "_ids": ids, "_keys": keys}, "ret": ret, "now": sw._now(), "after": {"questions": enc(sw.load_questions())}}
    OUT.setdefault(name, []).append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))


pool = near + ["İŞ İSTEĞİ (STEWARD-JOB): embed a.txt", "CEVAP OTURUM AÇMADI: x y z w?", "farklı bir soru daha var mı acaba?", "bambaşka konu: rapor nereye yazılsın?",
               "dördüncü iş: veritabanı şeması nasıl olsun?", "beşinci: lisans metni hangisi olacak?"] + texts[:12]
for run in range(60):
    sw.save_questions([])
    clock = [NOW]
    sw._now = lambda: clock[0]
    for step in range(rnd.randint(6, 22)):
        clock[0] += rnd.choice([1, 60, 3600, 3600 * 13, 3600 * 25])
        qs = sw.load_questions()
        qid = rnd.choice([q.id for q in qs] + ["yok"])
        op = rnd.choice(["add"] * 6 + ["ans"] * 3 + ["misc"])
        if op == "add":
            a = {"project": rnd.choice(["p", "p", "p", "z"]), "text": rnd.choice(pool + ["", "  "]), "source": rnd.choice(["", "s1", "s2", "reviewer-where"]),
                 "options": rnd.choice([None, ["evet", "hayır"], ["a", "b"]]), "routine": rnd.random() < 0.2, "detail": rnd.choice(["", "", "ayrıntı", LONG * 9])}
            stateful("add_question_ex", a, lambda: sw.add_question_ex(**a))
        elif op == "ans":
            a = {"question_id": qid, "answer": rnd.choice(["evet", "sonra", "a", "(B)", "c.", "bekle", "yeniden sorma", "1", "²", "ß", "", LONG * 4]),
                 "by": rnd.choice(["", "cops", "brain", "x"]), "only_open": rnd.random() < 0.3, "prefix": rnd.choice(["", "", "ön: "])}
            q = next((x for x in qs if x.id == qid), None)
            if q is not None and q.source == "reviewer-where":
                a["question_id"] = "yok"
            stateful("answer_question", a, lambda: sw.answer_question(**a))
        else:
            fn, a = rnd.choice([("set_question_detail", {"question_id": qid, "detail": rnd.choice(["", " d ", LONG * 9])}),
                                ("set_answered_by", {"ids": [qid, "yok"], "by": rnd.choice(["cops", "bad", "motor"])}),
                                ("mark_notified", {"question_id": qid}), ("escalate_routine", {"question_id": qid}), ("mark_delivered", {"question_id": qid}),
                                ("mark_undeliverable", {"question_id": qid, "reason": rnd.choice(["", "r", LONG])})])
            stateful(fn, a, lambda: getattr(sw, fn)(**a))
sw._now = lambda: NOW

seen_now = NOW
sw._LOG_SEEN.clear()
for step in range(120):
    seen_now += rnd.choice([0, 1, 899, 900, 901])
    event = rnd.choice(["a", "a", "b", "tick", "ticks", "x_denied", "denied_x"])
    data = rnd.choice([{"name": "n", "v": 1}, {"v": 1, "name": "n"}, {"name": "n", "v": 1.0}, {"name": "n", "v": True}, {"name": "", "project": "pp", "l": [1, {"b": 2, "a": 1}]},
                       {"project": "pp", "l": [1, {"a": 1, "b": 2}]}, {"name": 0, "project": None}, {}])
    key = ("<log>", event, str(data.get("name") or data.get("project") or ""))
    prev = list(sw._LOG_SEEN[key]) if key in sw._LOG_SEEN else None
    digest = hashlib.sha1(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]
    ret = sw._log_dedup("<log>", event, data, seen_now)
    post = sw._LOG_SEEN.get(key)
    args = {"log": "<log>", "event": event, "data": data, "now": seen_now,
            "seen": None if prev is None else {"same": prev[0] == digest, "at": prev[1], "suppressed": prev[2]}}
    OUT.setdefault("_log_dedup", []).append(json.dumps({"args": args, "ret": ret, "now": seen_now,
        "after": {"seen": None if post is None else {"at": post[1], "suppressed": post[2]}}}, ensure_ascii=False, separators=(",", ":")))

# ── grup 1: kart kaydı ve proje güncelleme (gerçek depo) ──
CARD_STATES = [None, {}, {"stale": True}, {"stale": 0, "goal": "g"}, {"stale": "", "attempt_at": 1}]
for card in CARD_STATES:
    path = sw.card_path("pr")
    for fn, extra in [("mark_card_stale", {}), ("note_card_failure", {"source_hash": "h", "error": ""}),
                      ("note_card_failure", {"source_hash": "h2", "error": "  uzun\n " + LONG, "now": 5.0}), ("note_card_failure", {"source_hash": "h", "error": None})]:
        if os.path.exists(path):
            os.remove(path)
        if card is not None:
            sw.save_card("pr", card)
        before = sw.load_card("pr")
        ret = getattr(sw, fn)("pr", **extra)
        OUT.setdefault(fn, []).append(json.dumps({"args": {"name": "pr", **extra, "card": before}, "ret": ret, "now": NOW,
                                                  "after": {"card": sw.load_card("pr")}}, ensure_ascii=False, separators=(",", ":")))

sw.hosts_mod.get_host = lambda h: object() if h == "uzak" else None
FIELDS = [{}, {"phase": "paused"}, {"phase": "bozuk", "kind": "yok", "priority": 99, "cadence_minutes": -5, "visits": "x"}, {"kind": "", "priority": "-3", "visits": " ٣ ", "cadence_minutes": 2.9},
          {"priority": True, "notes": LONG * 20, "goal": "g", "model": "m", "effort": "e", "last_directive": "d", "last_visit": 3.5}, {"notes": 5}, {"review_where": "local", "local_path": " /a/b "},
          {"review_where": "başka", "local_path": "göreli/yol"}, {"local_path": ""}, {"host": "uzak"}, {"host": " local "}, {"host": "yok"}, {"host": None, "goal": None},
          {"created_at": 1.0, "bilinmeyen": 3, "updated_at": 2.0}, {"phase": "planning"}, {"phase": "planned"}]
for existing, fields, running, force in itertools.product(
        [None, P("pr", phase="paused", created_at=1.0), P("pr", phase="done", host="uzak"), P("pr")], FIELDS, ["yok", False, True, None], [False, True]):
    if running != "yok" and "host" not in fields:
        continue
    sw.save_projects({} if existing is None else {"pr": existing, "z": P("z")})
    before = enc(sw.load_projects())
    kw = dict(fields)
    run = None if running == "yok" else (lambda r=running: r)
    via, cleared = [], []
    orig_labels, orig_clear = sw.auto_remove_labels, sw._clear_project_state
    sw.auto_remove_labels = lambda name, paths=None, via_=via, **k: via_.append(k.get("via"))
    sw._clear_project_state = lambda *a: cleared.append(1) or []
    try:
        try:
            ret = enc(sw.upsert_project("pr", force=force, running=run, **kw))
        except (TypeError, ValueError) as e:
            ret = {"__error__": type(e).__name__, "msg": str(e)}
    finally:
        sw.auto_remove_labels, sw._clear_project_state = orig_labels, orig_clear
    args = {"name": "pr", "force": force, "fields": fields, "projects": before, "sid": "default", "reviewer": False, "host_known": fields.get("host") != "yok",
            "owner_elsewhere": None, "index": None, "running_given": run is not None, "running": None if running == "yok" else running}
    OUT.setdefault("upsert_project", []).append(json.dumps({"args": args, "ret": ret, "now": NOW,
        "after": {"projects": enc(sw.load_projects()), "cleared": bool(cleared), "auto_label_via": via[-1] if via else None}}, ensure_ascii=False, separators=(",", ":")))
st_projects = {"a": P("a"), "a2026": P("a2026"), "pr": P("pr")}
for name in ["a", "pr", "yok", "a2026"]:
    state = {k: {"pr": 1, "uzak:pr20261126": 2, "a": 3, "a20261126_2": 4, "x:y:a": 5, "other": name, "z": "pr"} for k in sw._HOST_STATE_KEYS[:3] + ("done_pending",)}
    state["preamble_sent"] = ["pr"]
    state["untouched"] = {"pr": 1}
    sw.save_state(state)
    before = enc(sw.load_state())
    ret = sw._clear_project_state(name, st_projects)
    OUT.setdefault("_clear_project_state", []).append(json.dumps({"args": {"name": name, "projects": enc(st_projects), "state": before}, "ret": ret, "now": NOW,
        "after": {"state": enc(sw.load_state())}}, ensure_ascii=False, separators=(",", ":")))

dst = os.path.join(env.CRATE, "fixtures", "hand")
os.makedirs(dst, exist_ok=True)
for old in glob.glob(os.path.join(dst, "*.jsonl.gz")):
    os.remove(old)
for name, lines in sorted(OUT.items()):
    with open(os.path.join(dst, name + ".jsonl.gz"), "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as f:
        f.write("".join(x + "\n" for x in lines).encode())
print("işlev:", len(OUT), "kayıt:", sum(map(len, OUT.values())))
