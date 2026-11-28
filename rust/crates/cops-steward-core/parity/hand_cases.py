#!/usr/bin/env python3
"""Kayıtlı vektörlerin kapsamadığı dallar/kenar durumları (gruplar C ve D): girdiler burada elle yazılır, beklenen değer
Python işlevi çalıştırılarak alınır. Çıktı `fixtures/hand/<işlev>.jsonl.gz` (aynı satır biçimi; `harness::cases` ikisini de
oynatır). Kullanım: `python3 -I parity/hand_cases.py`."""
import dataclasses, functools, glob, gzip, hashlib, itertools, json, os, random, sys, time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402
env.isolate()
from claudeops import steward as sw, steward_ask  # noqa: E402

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
    b |= set(sorted(a)[:rnd.randint(0, 5)])      # küme sırası süreçten sürece değişir: sıralı al
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

# ── grup 2: World, devir/kapatma, iş kapıları, tur maddeleri ──
rnd = random.Random(2)
sw._now = lambda: NOW
G2 = ["token", "Token", "TOKENS", "token'ı", "tokenı", "bütçe", "BÜTÇE", "limit", "eşik", "bağlam", "BAĞLAM", "baglam", "context", "5", "٣", "sil", "SİL", "sıl", "silin", "silsile",
      "silindi", "silme", "silecek", "delete", "force", "force-push", "force push", "enforce", "workforce", "install", "kurulum", "KURULUM", "kurulsun", "kuruldu", "kurulacak", "apt", "chapter",
      "sudo", "harca", "spend", "parola", "password", "yetki", "credential", "bu oturumda", "BU OTURUMDA", "this session", "devir", "DEVİR", "devır", "yeni oturum", "handover", "new session",
      "commit", "committed", "push", "merge", "deploy", "toparla", "wrap up", "wrap-up", "wrapup", "READY FOR HANDOVER", "ready  for\nhandover", "bitti", "BİTTİ", "bitmedi", "bitmiş", "tamam",
      "tamamdır", "kapat", "evet", "EVET", "done", "yes", "no", "not", "değil", "hayır", "HAYIR", "hayir", "devam", "sürdür", "ama", "ancak", "fakat", "hariç", "kaldı", "KALDI", "kalan", "eksik",
      "henüz", "but", "except", "remaining", "still", "unless", "only", "?", "araçlar yok", "araçlarım mevcut değil", "ARAÇLAR YOK", "steward_answer aracı yok", "steward_directive bulunamadı",
      "no tools", "no matching deferred tool", "tools are unavailable", "cops-steward mcp server is not connected", "karar veremedim", "KARAR VEREMEDİM", "sürüyor", "SÜRÜYOR", "çalışıyor",
      "bitince", "döneceğim", "hazır olunca", "arka planda", "in progress", "when it's done", "when done", "will report", "yok", "none", "n/a", "na", "sormuyorum", "soru yok", "bekliyorum",
      "olursa", "gelirse", "yaparsa", "geçerse", "bitmezse", "varsa", "eğer", "if", "once", "after", "koşullu", "bekle", "sıradaki:", "şifre", "kimlik", "API key", "api_anahtar", "secret",
      "giriş yap", "log in", "signup", "hesap aç", "oturum açar mısın", "2FA", "captcha", "kredi", "ücretli", "satın", "buy", "paid", "lisans", "licence", "abonelik", "ödeme", "usd", "$ 5", "€",
      "10 TL", "fatura", "sıfırla", "wipe", "drop", "reset --hard", "geri alınamaz", "form", "formu", "formlarını", "format", "e-posta", "email", "mail", "yayın", "yayımla", "publish", "public",
      "submit", "arxiv", "zenodo", "başvur", "editöre", "yazara", "dener misin", "sen dene", "elle dene", "telefonda", "okur musun", "okuyup", "bakar mısın", "can you test", "sahibe sor",
      "SAHİBİNE SOR", "ask the owner", "opus", "x\u001cy", "\u001c", "é", "İ", "ı", "ſil", "toKen", "_sil", "sil_", "sil̇", ".", ":", ",", "\n", "-", "`", "  ", "STEWARD-NEXT: raporu yaz",
      "STEWARD-NEXT: yok", "çğışöü"]
G2S = lambda n: " ".join(rnd.choice(G2) for _ in range(rnd.randint(0, n)))
for t in G2 + [G2S(7) for _ in range(900)]:
    for fn in ("is_context_question", "is_wrap_up_directive", "brain_tools_missing_text", "is_conditional_note", "marker_next_work", "_ask_is_status_line", "is_readonly_job_request"):
        key = "q" if fn == "_ask_is_status_line" else "text"
        add(fn, {key: t})
    add("brain_may_answer", {"q": Q("q", "p", t, routine=rnd.random() < 0.85)})
    add("clip_words", {"text": t, "limit": rnd.choice([0, 1, 3, 8, 20, 200])})
for t in G2:
    for w in ("yok", "hayır", "no", "n/a", "bitti", "soru yok"):
        add("_ask_is_status_line", {"q": f"{w} {t}"})
for n in (69, 70, 71):
    add("_ask_is_status_line", {"q": "yok " + "x" * (n - 4)})
for t in ["STEWARD-NEXT: " + G2S(5) for _ in range(250)] + ["STEWARD-NEXT: " + "uzun kelime " * 40, "STEWARD-NEXT: `Yok.`"]:
    add("marker_next_work", {"text": t})
for t in ["İŞ İSTEĞİ (STEWARD-JOB): sql_readonly x sil", "İŞ İSTEĞİ (STEWARD-JOB): SQL_READONLY\u001cx", "İŞ İSTEĞİ (STEWARD-JOB): embed sil", "İŞ İSTEĞİ (STEWARD-JOB): ", "iş sql_readonly"]:
    add("is_readonly_job_request", {"text": t})
    add("brain_may_answer", {"q": Q("q", "p", t, routine=True)})
# 28 Kas: motorun "aç ya da atla" maddesi (önekle başlar) sahibin cevabındaki sahip-yetkisi sözcükleriyle reddedilmez; önek
# ortada/sonda ise eski kapı geçerli
for t in [sw._HELD_ANSWER_PREFIX + " p projesi done/paused. Cevap: eski taslakları sil, kurulum notunu güncelle",
          sw._HELD_ANSWER_PREFIX + " p: parola ve token yenilensin, sudo apt install yap",
          "dosyayı sileyim mi? " + sw._HELD_ANSWER_PREFIX, " " + sw._HELD_ANSWER_PREFIX + " sil", sw._HELD_ANSWER_PREFIX]:
    add("brain_may_answer", {"q": Q("q", "p", t, routine=True)})
    add("brain_may_answer", {"q": Q("q", "p", t, routine=False)})
for _ in range(500):
    qs = [Q(f"q{i}", rnd.choice(["p", "p", "z"]), rnd.choice(["STEWARD-DONE-CONFIRMED çelişti", "başka"]), status=rnd.choice(["answered", "answered", "open"]),
            answer=G2S(4), answered_at=rnd.choice([0.0, NOW - 5, NOW - 86399, NOW - 86400, NOW - 100]), ) for i in range(rnd.randint(0, 3))]
    for q in qs:
        q.created_at = rnd.choice([0.0, NOW - 50, NOW - 90000])
    add("done_conflict_answer", {"questions": qs, "proj": "p", "now": NOW})
for body in ["", "  ", "embed a.txt", "`embed` a", "embed", "Embed a", "a b sürüyor", "a ARKA PLANDA", "a bitince", "a when its done", "a\u001cb", "a\n\nbitince dönerim", "x" * 64, "x" * 65,
             "e_1.2-3 f", "yok", "1a b", "embed\tdosya (in progress)"] + [rnd.choice(["embed", "ocr", "A", "`x`"]) + " " + G2S(4) for _ in range(200)]:
    add("job_marker_verdict", {"body": body, "known_kinds": rnd.choice([None, [], ["embed"], ["ocr", 5]]), "services_registered": rnd.random() < 0.9})
jt = sw.JOB_REQUEST_PREFIX
for text, ans, jobs in itertools.product([jt + "embed a", "başka"], ["", "devam", "RED: kısa", "red - dosya yok çünkü silinmiş", "  Red:  on iki karakter! ", "REDDEDİLDİ uzun uzun uzun", "RED\nçok satırlı\ngerekçe burada", "RED— gerekçe yeterince uzun"],
                                         [[], [{"project": "p", "created_at": 100.0}], [{"project": "p", "created_at": 94.9}], [{"project": "p", "created_at": "95"}], [{"project": "z", "created_at": "x"}], [{"project": None}]]):
    add("job_request_gate", {"q": Q("q", "p", text, created_at=100.0), "answer": ans, "jobs": jobs})
for busy, last, gap in itertools.product([None, True, False], [0.0, NOW - 89.9, NOW - 90, NOW], [90.0, 0.0, 5.0]):
    add("directive_defer_reason", {"busy": busy, "last_directive_at": last, "now": NOW, "gap": gap})
for _ in range(120):
    qs = [Q(f"q{i}", rnd.choice(["", "p", "z"]), "t", source=rnd.choice(["", "p1", "z1"]), status=rnd.choice(["open", "open", "answered"])) for i in range(rnd.randint(0, 4))]
    add("owner_pending_block", {"keys": set(rnd.sample(["", "p", "p1", "z"], rnd.randint(0, 3))), "questions": qs, "denied": {f"q{i}": 1.0 for i in rnd.sample(range(4), rnd.randint(0, 4))}})
for prev, call, text, n, tours in itertools.product([0.0, NOW - 179, NOW - 180, NOW - 600], [None, 0.0, NOW - 600, NOW - 601], ["", "karar veremedim", "tamam"], [0, 2], [0, 1, 3]):
    add("brain_notools_verdict", {"prev_tour": prev, "mcp": {} if call is None else {"call_at": call}, "last_text": text, "nocall": n, "cfg": C(brain_nocall_tours=tours), "now": NOW})

# generic
for m, e in itertools.product(["", "claude-opus-4", " Claude-FABLE ", "OPUS", "claude-sonnet-5-5", "gpt", "claude-", "xclaude-opus"], ["", "medium", " HIGH ", "xhigh", "max", "maxx", "hıgh"]):
    add("is_upper_tier", {"model": m, "effort": e})
    add("is_claude_model", {"model": m})
    for lang in ("tr", "en"):
        add("upper_main_text", {"project": "p", "model": m, "effort": e, "lang": lang})
        add("upper_tier_question_text", {"project": "p", "model": m, "effort": e, "lang": lang})
    tag = sw.upper_tier_tag("p", m, e)
    for ans, st, src in [(" Onayla! ", "answered", "upper_model"), ("EVET..!", "answered", "upper_model"), ("onaylıyorum", "open", "upper_model"), ("yes", "answered", "x"),
                         ("ONAYLIYORUM", "answered", "upper_model"), ("evet.\n", "answered", "upper_model"), ("evet tamam", "answered", "upper_model")]:
        add("upper_tier_approved", {"questions": [Q("q", "p", tag + " ?", answer=ans, status=st, source=src)], "project": "p", "model": m, "effort": e})
for role in ["", "generic", "reviewer"]:
    add("is_generic", {"cfg": C(role=role)})
marks = ["- ", "* ", "+ ", "1. ", "12) ", "٣. ", "-", "", "  - ", "1.", "# ", "• ", "-\t"]
boxes = ["", "[ ] ", "[x] ", "[X]", "[✓] ", "[  ] ", "[ ]", "~~eski~~ "]
for _ in range(250):
    todo = rnd.choice(["\n", "\r\n", "\u001c"]).join(rnd.choice(marks) + rnd.choice(boxes) + G2S(4) + rnd.choice(["", " DONE", " BİTTİ", " bitti", " Done", "x" * 400]) for _ in range(rnd.randint(0, 12)))
    tbd = "\n".join(rnd.choice(["", "# ", "  ## ", "- ", "• ", "-*+ "]) + rnd.choice(["TBD#1 ", "TBD ", "tbd ", ""]) + G2S(3) + rnd.choice(["", " Karar: A", " KARAR = b", " cevap : x", " ✓", " kapandı:", " KAPANDI:", " decision no"]) for _ in range(rnd.randint(0, 9)))
    card = rnd.choice([None, {}, {"open_tbds": None}, {"open_tbds": "ab"}, {"open_tbds": [G2S(3), 5, "TBD#9 karar: evet"]}, {"open_tbds": {"k": 1}}])
    add("generic_backlog", {"todo_text": todo, "tbd_text": tbd, "card": card})

# World ve izlenen oturumlar
PN = ["a", "ab", "mkt", "ncs", "ncs2", "kitap"]
SN = ["", "a", "ab", "a20261126", "a20261126_2", "a_3", "ab20260101", "mkt", "mkt2", "mkt20261301", "ncs20261019", "ncs2x", "ncs2", "degnekci", "degnekci_kitap", "degnekci_x", "varaka", "varaka2", "zed", "zed1", "adhoc", "kitap"]


def rworld(sid=None):
    sid = sid or rnd.choice(["default", "ab"])
    owners = {p: rnd.choice(["default", "ab", "cd", ""]) for p in rnd.sample(PN, rnd.randint(0, 5))}
    conflicts = frozenset(rnd.sample(PN, rnd.choice([0, 0, 1, 2])))
    return sw.World(sid=sid, owners=owners, conflicts=conflicts, brains={"degnekci": "default", **rnd.choice([{}, {"degnekci_kitap": "ab"}, {"a": "ab"}])},
                    services=rnd.choice([{}, {"varaka": {"match": "prefix"}, "zed": {"match": "exact"}}, {"ncs": None, "mkt": {}}]), is_adhoc_owner=sid == "default",
                    hosts={p: rnd.choice(["h1", "h2", ""]) for p in rnd.sample(PN, rnd.randint(0, 2))}, owned={p: rnd.choice(SN) for p in rnd.sample(PN, rnd.randint(0, 3))},
                    unavailable=frozenset(rnd.sample(PN, rnd.choice([0, 0, 1]))), quota_held=frozenset(rnd.sample(PN, rnd.choice([0, 1]))))


for _ in range(600):
    w = rworld()
    name, p, bp = rnd.choice(SN), rnd.choice(PN + [""]), rnd.choice([None, "", *PN, "degnekci", "varaka", "a"])
    for meth in ("start_held", "host_of", "owner_of", "owns", "_owner_tag"):
        add(f"World.{meth}", {"self": w, "project": p}, call=lambda: getattr(w, meth)(p))
    for meth in ("resolve", "name_class", "project_key"):
        add(f"World.{meth}", {"self": w, "name": name}, call=lambda: getattr(w, meth)(name))
    for meth in ("session_class", "owned_key", "is_manual"):
        add(f"World.{meth}", {"self": w, "name": name, "blueprint": bp}, call=lambda: getattr(w, meth)(name, bp))


def rview(names=SN):
    return V(rnd.choice(names), rnd.random() < 0.85, blueprint=rnd.choice([None, None, "", "a", "mkt"]), busy=rnd.choice([None, True, False, False]),
             subagent_active=rnd.random() < 0.15, subagent_unknown=rnd.random() < 0.1,
             last_activity=rnd.choice([0.0, NOW - 30, NOW - 59.9, NOW - 60, NOW - 599, NOW - 600, NOW - 5400, NOW + 5]),
             started_at=rnd.choice([0.0, NOW - 299, NOW - 300, NOW - 7000]),
             last_assistant=rnd.choice(["", "iş", "READY FOR HANDOVER", "# READY FOR HANDOVER x", "READY FOR HANDOVER demiyorum`", "a READY FOR HANDOVER", "bitti\nSTEWARD-NEXT: raporu yaz",
                                        "STEWARD-NEXT: yok", "STEWARD-NEXT: veri gelirse çiz", "soru\nSTEWARD-ASK: hangisi?\nSTEWARD-DETAIL: d", "STEWARD-ASK: yok\nSTEWARD-ROUTINE: x?\nSTEWARD-IDEA: f",
                                        "STEWARD-BLOCKED: pdf\nSTEWARD-JOB: embed a\nSTEWARD-LESSON: abc", "ok"]),
             live_model=rnd.choice(["", "claude-opus-4", "claude-sonnet-5-5", "deepseek"]), live_effort=rnd.choice(["", "high", "medium"]))


def rproj():
    return {p: P(p, phase=rnd.choice(["planned", "planned", "planning", "done", "paused", "idea"]), model=rnd.choice(["", "", "claude-opus-4"]), effort=rnd.choice(["", "high"]),
                 notes=rnd.choice(["", "", "sahibe sor", "BEKLEME"])) for p in rnd.sample(PN, rnd.randint(0, 5))}


for _ in range(400):
    w = rworld()
    views = [rview() for _ in range(rnd.randint(0, 6))]
    projects = rproj()
    cfg = C(brain_name=rnd.choice(["degnekci", "a", ""]))
    name = rnd.choice(SN)
    wo = rnd.choice([None, w])
    add("_sibling_running", {"views": views, "name": name, "projects": projects, "cfg": cfg, "world": wo})
    add("update_owned", {"owned": {p: rnd.choice(SN) for p in rnd.sample(PN, rnd.randint(0, 2))}, "views": views, "world": w, "projects": projects, "now": NOW, "seeding": rnd.random() < 0.5})
    add("upper_main_views", {"views": views, "projects": projects, "cfg": C(role=rnd.choice(["", "reviewer"]), planned_effort=rnd.choice(["", "max"])), "world": wo})
    add("pick_delivery_view", {"views": views, "project": rnd.choice(PN), "source": rnd.choice(["", "a", "a20261126"])})
    if views:
        add("holds_total_slot", {"v": views[0], "now": NOW, "last_directive_at": rnd.choice([0.0, NOW - 10, NOW - 300])})
    rows = [{k: v for k, v in {"name": rnd.choice(SN + [None, 5]), "cli": rnd.choice(["claude", "shell", None]), "host": rnd.choice([None, "", "local", " h1 ", "h2", "h3", 0]),
                               "instance": rnd.choice([True, False, None, 1]), "blueprint": rnd.choice([None, "a", "mkt", "ncs", "", 3])}.items() if rnd.random() < 0.85} for _ in range(rnd.randint(0, 6))]
    add("select_rows", {"rows": rows, "world": w, "fresh_hosts": rnd.choice([[], ["h1"], ["h1", "h2"]])})
    entries = [[rnd.choice(PN), rnd.choice(["directive", "nudge"])] for _ in range(rnd.randint(0, 4))]
    taken = set(rnd.sample(SN, rnd.choice([0, 2])))
    state = rnd.choice([{}, {"last_directive_at": None, "x": 1}, {"x": 1, "last_directive_at": {"a": 1.0}, "z": 2}])
    limit = rnd.choice([0, 1, 2, 9])
    mine = views + [V(p, True, busy=False) for p in rnd.sample(PN, 2)]
    add("plan_deliveries", {"entries": entries, "mine": mine, "taken": taken, "state": state, "now": NOW, "limit": limit},
        call=lambda: sw.plan_deliveries([(p, lambda v, p=p, k=k: sw.Action(k, v.name, p)) for p, k in entries], mine, taken, state, NOW, limit))

for ts in ["2026-11-10T13:19:29", "2026-1-5T1:2:3", "2026-02-30T00:00:00", "2024-02-29T00:00:00", "2026-11-10t13:19:29", "2026-11-10T13:19:60", "2026-11-10T13:19:61", "2026-11-10T13:19:62",
           "0000-01-01T00:00:00", "2026-11- 5T13:19:29", "2026-13-01T00:00:00", "2026-11-10T24:00:00", "2026-11-10 13:19:29", "2026-11-10T13:19:29.5+03:00", "2026-11-10T13:19",
           "２０２６-11-10T13:19:29", "2026-11-1٠T13:19:29", "", "x", None, 5]:
    for started in (0.0, 1.0, 1767578523.0, 1794316769.0, 1794316770.0, 1794316771.0, 1794316830.0):
        ev = [{"event": "directive", "name": "p", "ts": ts}]
        add("owned_evidence", {"events": ev, "name": "p20261110", "project": "p", "started_at": started})
for _ in range(300):
    ev = [{k: v for k, v in {"event": rnd.choice(["action", "directive", "outcome", "stop", "restart", "would:keepwarm", None]), "name": rnd.choice(["p", "p1", "", None]),
                             "ok": rnd.choice([True, False, 0, None]), "kind": rnd.choice(["start", "nudge", "keepwarm", None]), "result": rnd.choice(["changed", "same", None]),
                             "ts": "2026-11-10T13:19:29"}.items() if rnd.random() < 0.85} for _ in range(rnd.randint(0, 3))]
    add("owned_evidence", {"events": ev, "name": "p1", "project": "p", "started_at": rnd.choice([0.0, 1.0, 2e9])})

# devir / kapatma
for model, f, a in itertools.product(["", "claude-FABLE-5", "claude-opus"], [0, 150000, 400000], [0, 300000]):
    add("context_threshold", {"cfg": C(context_warn_tokens_fable=f, context_warn_tokens=a), "model": model})
for busy, sa, su, mx, ratio, since, tokens, warn in itertools.product([None, True, False], [False, True], [False, True], [0, 30], [0.0, 1.3, 2.0, 1e-7, 1234567.0, 0.30000000000000004],
                                                                      [None, NOW - 1799.5, NOW - 1800, NOW - 3600.0001], [None, 0, 390000, 10 ** 13], [0, 300000]):
    if rnd.random() < 0.12:
        add("handover_defer_decision", {"v": V("a", True, busy=busy, subagent_active=sa, subagent_unknown=su), "cfg": C(handover_defer_max_minutes=mx, handover_force_ratio=ratio),
                                        "now": NOW, "since": since, "tokens": tokens, "warn": warn})
for tokens, warn, ratio, lang in itertools.product([-1500, -1, 0, 25, 35, 999, 1000, 209999, 210000, 305000], [0, 200, 1000, 300000], [0.0, 0.7, 1.0], ["tr", "en"]):
    add("context_answer", {"tokens": tokens, "warn": warn, "ratio": ratio, "lang": lang})
for kind, res, fails in itertools.product(["handover", "stop"], [{}, {"ok": True}, {"ok": 0}, {"code": "destructive_budget"}, {"error": "e" * 300}, {"error": None, "ok": False}], [None, 0, 3, 4, "4", 7.9]):
    add("shutdown_note_result", {"it": {"stage": "closed", "fails": fails, "at": 1.0, "z": 2}, "kind": kind, "res": res, "now": NOW})
for _ in range(1200):
    names = ["a", "ab", "mkt", "degnekci", "a20261126"]
    views = [rview(names) for _ in range(rnd.randint(0, 5))]
    sd = {}
    if rnd.random() < 0.8:
        items = {n: {k: v for k, v in {"stage": rnd.choice(["wait", "wait", "ho", "ho", "closed", "kept", "gone", "busy_left", "ho_timeout", "ho_failed"]),
                                       "at": rnd.choice([NOW - 1, NOW - 599, NOW - 600, NOW - 6000]), "ho_at": rnd.choice([NOW - 700, NOW - 40, NOW]), "blocked": "eski",
                                       "fails": 1}.items() if k in ("stage", "at") or rnd.random() < 0.5} for n in rnd.sample(names, rnd.randint(0, 4))}
        sd = {k: v for k, v in {"started": rnd.choice([NOW - 10, NOW - 2699, NOW - 2700, NOW - 9000]), "init": rnd.random() < 0.6, "items": items,
                                "modes": rnd.choice([None, {}, {"a": "keep", "mkt": "stop"}]), "only": rnd.choice([None, [], ["a"], ["mkt", "ab"]]), "other": 1}.items() if rnd.random() < 0.85}
    add("plan_shutdown", {"views": views, "projects": rproj(), "sd": sd, "cfg": C(brain_name=rnd.choice(["degnekci", "degnekci", ""])), "now": NOW,
                          "world": rnd.choice([None, None, rworld("default")]), "blockers": rnd.choice([None, {}, {"a": "iş açık", "degnekci": "x"}])})

# tur maddeleri ve kayıt eylemleri
for name in ["", "a", "abc1", "mecdtfl20261031_3", "a-b2026_1_2", "a_b1", "1abc", "abc\n", "abc1\n", "abc\n\n", "abç1", "x٣", "x_", "x_1x", "-a", "a-", "A2B"]:
    add("_ask_base", {"name": name})
for _ in range(400):
    last = rview().last_assistant
    if rnd.random() < 0.5:
        last = "\n".join(f"STEWARD-{rnd.choice(['ASK', 'ROUTINE', 'DETAIL', 'IDEA', 'BLOCKED', 'JOB', 'LESSON', 'NEXT'])}: {G2S(4)}{rnd.choice(['', '?'])}" for _ in range(rnd.randint(0, 6)))
    m = sw.scan_markers(last)
    name, proj = rnd.choice(SN), rnd.choice(["", "a"])
    add("marker_record_actions", {"name": name, "proj": proj, "m": m})
    add("note_project_next", {"st": rnd.choice([{}, {"project_next": None}, {"x": 1, "project_next": {"a": {"text": "e"}}, "z": 2}]), "proj": proj, "session": name, "m": m, "now": NOW})
for allowed, sb in itertools.product([[], [("start", "b", "due"), ("start", "a", "due"), ("start", "a", "due"), ("start", "c", "answer"), ("stop", "d", "due")]],
                                     [None, {}, {"projects": ["z", "a"], "reason": "r", "active": 1, "max_active_total": None, "x": 2}, {"projects": [], "reason": "r", "active": 1},
                                      {"projects": ["q"], "reason": 0, "bekleme_projects": []}]):
    add("start_decision_event", {"actions": [sw.Action(*a) for a in allowed], "state": {"start_blocked": sb}})


def rq2(i):
    return Q(f"q{i}", rnd.choice(["", *PN, "degnekci", "gone"]), rnd.choice(["", "Bölümleri sırayla mı yazayım?", sw.JOB_REQUEST_PREFIX + "x", G2S(5)]),
             created_at=rnd.choice([0.0, NOW - 60, NOW - 1199, NOW - 1200, NOW - 30000, NOW + 100]), status=rnd.choice(["open", "open", "answered"]),
             routine=rnd.random() < 0.25, source=rnd.choice(["", "", "a", "mkt", "upper_model", "job-red"]), answer=rnd.choice(["", "evet"]),
             answered_at=rnd.choice([0.0, NOW - 60, NOW - 90000]), delivered_at=rnd.choice([0.0, 0.0, 5.0]),
             options=rnd.choice([[], [], ["a", "b"], ["x" * 100, "y" * 100], [G2S(2)]]), detail=rnd.choice(["", "", "", G2S(3)]), prev_texts=rnd.choice([[], [], [], [G2S(3)]]),
             extra_texts=rnd.choice([[], [], [], [], ["e"]]), deferred_until=rnd.choice([0.0, 0.0, 0.0, NOW - 1, NOW, NOW + 1]))


for _ in range(900):
    q = rq2(0)
    q.status, q.routine = rnd.choice([("open", False)] * 8 + [("answered", False), ("open", True)])
    if rnd.random() < 0.6:
        q.project, q.source, q.extra_texts, q.deferred_until = rnd.choice(["a", "mkt"]), "", [], 0.0
        q.text, q.options, q.detail, q.prev_texts = "Soru " + (G2S(2) if rnd.random() < 0.8 else ""), [], "", []
    owners = rnd.choice(["", "", "a", " mkt , a ", ",,", "zz"])
    projects = {p: P(p, phase=rnd.choice(["planned", "planned", "planned", "done", "paused"]), notes=rnd.choice(["", "", "", G2S(3), "Sahibine sor."])) for p in ["a", "mkt", "ncs"]}
    note = rnd.choice(["", "", G2S(3), "SAHİBE SOR"])
    cfg = C(ask_gate="shadow", ask_gate_owner_projects=owners)
    add("owner_class", {"q": q, "owner_projects": owners, "note": note, "now": NOW}, call=lambda: steward_ask.owner_class(q, owners, note, NOW))
    add("blocked_reason", {"q": q, "projects": projects, "cfg": cfg, "now": NOW}, call=lambda: steward_ask.blocked_reason(q, projects, cfg, NOW))
    state = rnd.choice([{}, {}, {"ask_gated": None, "ask_seen": None}, {"ask_gated": {q.id: 1}}, {"ask_gated": [q.id]}, {"ask_gated": {"z": 1}},
                        {"ask_seen": {q.id: {"n": 1, "at": NOW - 1800}}}, {"ask_seen": {q.id: {"n": 1, "at": NOW - 1799}}}, {"ask_seen": {q.id: {"n": 2, "at": 0}}},
                        {"ask_seen": {q.id: {"n": "1", "at": None}}}, {"ask_seen": {q.id: {}}}, {"ask_seen": {q.id: None}}])
    add("tour_eligible", {"q": q, "projects": projects, "cfg": cfg, "state": state, "now": NOW}, call=lambda: steward_ask.tour_eligible(q, projects, cfg, state, NOW))
for t in G2:
    q = Q("q", "a", t)
    add("owner_class", {"q": q, "owner_projects": "", "note": "", "now": NOW}, call=lambda: steward_ask.owner_class(q, "", "", NOW))
for _ in range(700):
    views = [rview() for _ in range(rnd.randint(0, 5))]
    qs = [rq2(i) for i in range(rnd.choice([0, 0, 1, 3, 6]))]
    ideas = [sw.Idea(f"i{i}", G2S(3), NOW, status=rnd.choice(["new", "done"])) for i in range(rnd.randint(0, 2))]
    cfg = C(brain_name=rnd.choice(["degnekci", "a"]), idle_minutes=rnd.choice([0, 10]), review_minutes=rnd.choice([0, 90]), ask_gate=rnd.choice(["off", "shadow", "on"]))
    projects = {p: P(p, phase=rnd.choice(["planned", "planned", "planned", "done", "paused"])) for p in rnd.sample(PN + ["a20261126"], rnd.randint(2, 6))}
    world = rnd.choice([None, None, None, rworld("default")])
    skip_seen = {}
    for v in views:
        if rnd.random() < 0.35:
            sig = sw.item_signature(v, world.own_projects(projects) if world else projects, qs)
            skip_seen[v.name] = rnd.choice([{"sig": sig, "at": NOW - 10}, {"sig": sig, "at": NOW - 21600}, {"sig": "x", "at": NOW}, {"sig": sig}, "bozuk"])
    sigs = rnd.choice([None, {}, {"önce": "1"}])
    add("review_items", {"views": views, "projects": projects, "cfg": cfg, "now": NOW, "questions": qs, "ideas": ideas,
                         "skip": set(rnd.sample(SN, rnd.choice([0, 0, 4]))), "last_directive_at": {n: rnd.choice([NOW - 10, NOW - 9000]) for n in rnd.sample(SN, 3)},
                         "reviewed_at": {n: rnd.choice([NOW - 10, NOW - 9000]) for n in rnd.sample(SN, 3)}, "world": world, "skip_seen": skip_seen, "sigs_out": sigs,
                         "state": rnd.choice([None, {}, {"ask_seen": {"q0": {"n": 2}}}])})
real_time = sw.time.time
sw.time.time = lambda: NOW
try:
    for _ in range(300):
        views = [rview() for _ in range(rnd.randint(0, 5))]
        seen = {v.name: hashlib.sha1(v.last_assistant.encode()).hexdigest()[:16] for v in views if rnd.random() < 0.2}
        state = rnd.choice([{}, {"seen_assistant": seen, "x": 1}, {"seen_assistant": None, "project_next": {}}])
        add("plan_markers", {"views": views, "projects": rproj(), "state": state, "cfg": C(brain_name=rnd.choice(["degnekci", "a"])), "world": rnd.choice([None, rworld(), rworld("default")])})
finally:
    sw.time.time = real_time

# nadir dalları yoğunlaştır
CTX = (["bu oturum", "BU OTURUMDA", "this session", "bu  oturum"], ["devir", "DEVİR", "devır", "yeni oturum", "Handover", "NEW SESSION", "x"], ["", "mi?", "commit", "PUSH", "sil", "asil", "_sil", "DELETE", "enforce", "deploy"])
WRAP = (["READY FOR HANDOVER", "ready\tfor\nhandover", "Ready For Handover", "ready for hand over"], ["commit", "COMMIT", "committed", "push", "pushed", "toparla", "TOPARLAYIN", "wrap up", "wrapup", "wrap\u001cup", "x", "commıt"])
for a, b, c in itertools.product(*CTX):
    add("is_context_question", {"text": f"{a} {b} {c}"})
for a, b in itertools.product(*WRAP):
    add("is_wrap_up_directive", {"text": f"{a}; {b}"})
    for data in (None, {}, {"keep_phase": True}, {"keep_phase": 1}, {"keep_phase": "true"}):
        add("directive_keeps_phase", {"text": rnd.choice([f"{a} {b}", "yeni iş"]), "data": data})
YES = ["bitti", "BİTTİ", "bıttı", "bitmiş", "tamam", "tamamdır", "tamamladım", "kapatın", "Evet", "done", "finished", "yes", "devam", "x"]
for a, b in itertools.product(YES, ["", "ama X", "değil", "kaldı", "kalanlar", "?", "not", "only", "onlyx", "noted", "eksik", "still"]):
    add("done_conflict_answer", {"questions": [Q("q", "p", "STEWARD-DONE-CONFIRMED", status="answered", answer=f"{a} {b}", answered_at=NOW - 1)], "proj": "p", "now": NOW})
for kind, tail in itertools.product(["sql_readonly", "SQL_Readonly", "`sql_readonly`", "sql_readonlyx"], ["", " a", "\nsil", "\u001csil"]):
    add("is_readonly_job_request", {"text": sw.JOB_REQUEST_PREFIX + kind + tail})
for busy, act, ho_at, last, mode, at in itertools.product([None, True, False], [0.0, NOW - 100, NOW - 10], [None, NOW - 100, NOW - 50], ["", "READY FOR HANDOVER"], [None, "keep", "stop"], [NOW - 100, NOW - 700]):
    it = {"stage": "ho", "at": at, **({} if ho_at is None else {"ho_at": ho_at})}
    add("plan_shutdown", {"views": [V("a", True, busy=busy, last_activity=act, last_assistant=last)], "projects": {"a": P("a")},
                          "sd": {"started": NOW - 800, "init": True, "items": {"a": it}, "modes": {} if mode is None else {"a": mode}},
                          "cfg": C(brain_name="degnekci"), "now": NOW, "world": None, "blockers": None})

# ── grup 3: kurtarma, boşta, neden açıklaması ──
rnd = random.Random(3)
sw._now = lambda: NOW


def add_cb(name, args, fn, callbacks):
    """`callbacks`: {parametre: tablo}; tablo {proje: sonuç}, `"raise"` istisna (vektörde None). Rust aynı tabloyu okur."""
    before = json.loads(json.dumps(enc(args)))
    live, logs = {}, {}
    for p, table in callbacks.items():
        def call(key, table=table):
            v = table[key]
            if v == "raise":
                raise RuntimeError("geri çağrı")
            return v
        live[p] = call
        logs[p] = [[[k], None if v == "raise" else v] for k, v in table.items()]
    try:
        ret = fn(live)
    except (TypeError, ValueError) as e:
        ret = {"__error__": type(e).__name__, "msg": str(e)}
    rec = {"args": before, "ret": enc(ret), "now": NOW}
    if logs:
        rec["callbacks"] = logs
    OUT.setdefault(name, []).append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))


G3 = ["API Error:", "api error:", "APİ ERROR:", "apı error:", " 500", "429", "503x", "٥٠٠", "overloaded", "TİMED OUT", "timed-out", "rate limit", "RATE-LİMİT", "rate_limit", "(429)", "can't reach", "cant reach",
      "EAI_AGAIN", "400 invalid request", "This turn failed", "THIS TURN FAILED", "HTTP 404", "http503", "status code: 500", "status: 429", "error", "errors", "failed", "unavailable", "timeout",
      "kapı onayı bekliyor", "KAPI KARARI BEKLENİYOR", "kapıya haber", "kapi onayi icin bekliyor", "waiting for the gate", "sıradaki:", "SIRADAKİ:", "Sıradaki iş:", "siradaki adim：", "next:", "NEXT STEP:",
      "next task :", "yok", "YOK.", "none", "n/a", "bitti", "done", "-", "—", "`yok`", "nothing", "yoksa", "sonraki turda", "şimdi X'e geçiyorum", "ŞİMDİ rapora başlıyorum", "kalan bağımsız iş", "açık kalan teknik işler",
      "next I'll move on", "I will now start ", "i'll continue ", "hayır", "HAYIR", "hayir", "no", "nope", "açma", "AÇMA", "bekle", "dur", "kalsın", "paused kalsın", "şimdi değil", "sonra", "şimdilik hayır", "gerek yok", "olmasın",
      "aç", "Aç", "AÇILSIN", "başla", "BAŞLAYABİLİRSİN", "evet", "EVET", "planned", "devam", "yes", "start", "ok", "okey", "TBD", "gelene dek", "yapma", "2)", "3.", "1 -", "fable", "FABLE", "cila", "CİLA", "cilası", "nesir cila", "üslup cila",
      "prose polish", "style polish", "olursa", "gelirse", "varsa", "eğer", "if", "after", "sahipte", "SAHİPTE", "sahibin kararı", "sahip kararı bekliyor", "owner's decision", "waiting on the owner", "STEWARD-DONE", "STEWARD-DONE-CONFIRMED",
      "NO-STEWARD-DONE", "STEWARD-DONE yazmıyorum", "STEWARD-NEXT: raporu yaz", "STEWARD-NEXT: yok", "READY FOR HANDOVER", "# READY FOR HANDOVER", "yapacak iş yok", "yapılacak başka iş yok demiyorum", "no work left", "nothing left to do, not true",
      "no more work değil", "STEWARD-ASK: x?", "STEWARD-BLOCKED: y", "STEWARD-ROUTINE: z?", "STEWARD-JOB: embed a", "```", "> ", "- ", "* ", "• ", ". ", ".", "\n", "\n\n", "\r\n", "\u001c", " ", " ", "  ", ":", "：", ";", "`", "!", ")", "]",
      "neden:", "REASON :", "İ", "ı", "ß", "ﬁ", "😀", "çğışöü", "rapor", "modeli", "eğitimi", "ölçüm", "betiğini", "yaz", "kontrol", "et", "5", "TODO.md'deki", "[x]", "[ ]"]
G3S = lambda n: " ".join(rnd.choice(G3) for _ in range(rnd.randint(0, n)))
G3T = lambda n: "".join(rnd.choice(G3) + rnd.choice([" ", " ", "", "\n"]) for _ in range(rnd.randint(0, n)))
TEXTS = G3 + [G3S(6) for _ in range(500)] + [G3T(14) for _ in range(500)]
for t in TEXTS:
    for fn in ("api_error_kind", "next_none_stated", "turn_failed", "waiting_for_gate", "is_negative_answer", "is_open_answer", "is_fable_polish", "next_line", "stated_next_work", "owner_wait", "idle_finish_marker", "_note_words"):
        add(fn, {"text": t})
    add("_done_at_line_end", {"line": t})
    add("one_line", {"text": t, "limit": rnd.choice([0, 1, 5, 40, 400])})
    add("expired_handover_note", {"last_assistant": t, "lang": rnd.choice(["tr", "en"])})
    add("api_error_kind", {"text": "API Error: " + t})
    add("is_open_answer", {"text": rnd.choice(["2) ", "12. ", " 1: ", "3 - ", "٣) "]) + t})
for lead, body in itertools.product(["", "x ", "x" * 299, "x" * 296], ["500", " overloaded", "timeout"]):
    add("api_error_kind", {"text": "API Error: " + lead + body})
for pad, mark in itertools.product([590, 600, 601, 800, 801], ["This turn failed", "kapı onayı bekliyor"]):
    for fn in ("turn_failed", "waiting_for_gate"):
        add(fn, {"text": mark + "x" * (pad - len(mark))})
for t in ["x", "çok uzun " * 200, "a" * 1200, "a" * 1201]:
    add("expired_handover_note", {"last_assistant": t, "lang": "tr"})
for n in (59, 60, 61):
    add("is_negative_answer", {"text": "hayır " + "x" * (n - 6)})
    for prefix, by, routine in itertools.product(["", sw.ON_BEHALF_PREFIX], ["", "brain", "motor", "owner_cli"], [False, True]):
        add("_held_instruction_item", {"q": Q("q1", "p", "t", answer=f" {prefix}{'ö' * n} ", answered_by=by, routine=routine)})
for ttl in ["", "1h", " 1H ", "5m", "1 h"]:
    add("ucli_idle_threshold", {"cfg": C(ucli_idle_nudge_secs=7, ucli_idle_nudge_secs_1h=9), "cache_ttl": ttl})

# TBD#387/2-3: "iş yok" değerleri ve boş "sıradaki:" satırı (rastgele üretici KULLANILMAZ: diğer girdiler kaymasın)
V387 = ["-", "—", "–", "- .", "`-`", "- testleri koş", "- [ ] x", "n/a", "N/A.", "n/a (sahipte)", "n/a değerlerini ayıkla", "bitti", "Bitti.", "**bitti**", "BİTTİ", "bıtti", "bitti (devir)", "bitti, kalan", "bitti - sahipte",
        "bitti — x", "bitti mi bak", "bitti_listesi", "done", "done.", "done.md düzenle", "done: x", "done!x", "done !", "", "   ", "**", "`", "\nF5", "\n\nSTEWARD-DONE", "\n  ", "\r\nyok", "\u2028x", "**\n- a"]
for v, head, tail in itertools.product(V387, ["sıradaki:", "SIRADAKİ :", "**next:** ", "sıradaki\t:"], ["", "\nSTEWARD-DONE", "\nREADY FOR HANDOVER"]):
    t = f"{head} {v}{tail}"
    for fn in ("next_line", "stated_next_work", "idle_finish_marker", "next_none_stated"):
        add(fn, {"text": t})
    add("idle_finish_marker", {"text": f"STEWARD-DONE\nsıradaki: eski\n{t}"})
for v in V387:
    add("marker_next_work", {"text": f"STEWARD-NEXT: {v}"})
    add("next_work_hint", {"proj": P("p", notes=f"sıradaki: {v}"), "real_only": True})
    add("next_work_hint", {"proj": P("p", notes=f"sıradaki: {v}\nsıradaki: F5"), "real_only": False})

NOTE_BITS = ["sıradaki:", "Sıradaki iş:", "SIRADAKİ:", "next:", "siradaki", "sıradaki", "BEKLEME", "model", "eğitimi", "ölçüm", "betiğini", "yaz", "rapor", "tabloyu", "güncelle", "yok", "YOK.", "none", "-", "fable cila", "veri gelirse", "olursa",
             "çiz", "TODO.md", "632", "için", "next", "neden: eski", ";", ",", ".", "reason :", "İŞ", "ılık", "x", "ab"]
NOTE = lambda: "\n".join(" ".join(rnd.choice(NOTE_BITS) for _ in range(rnd.randint(0, 9))) for _ in range(rnd.randint(0, 4)))
LONGNOTE = "sıradaki: model eğitimi ölçüm betiğini yaz rapor tabloyu güncelle"
WORDS5 = ["model", "eğitimi", "ölçüm", "betiğini", "yaz", "rapor", "tabloyu", "güncelle", "başka", "konu"]


def todo_text():
    out = []
    for _ in range(rnd.randint(0, 5)):
        lead = rnd.choice(["- [x] ", "- [X] ", "- [ ] ", "- [~] ", "* [x] ", "1. [x] ", "12) [ ] ", "- ", "+ ", "", "-[x]", "  - [x]", "- [y] ", "# ", "- [  ] "])
        out.append(lead + " ".join(rnd.sample(WORDS5, rnd.randint(0, 10))))
    return "\n".join(out)


for _ in range(1200):
    notes = rnd.choice([NOTE(), NOTE(), LONGNOTE, LONGNOTE + rnd.choice(["; neden: x", ". Reason: y", "\nsıradaki: yok", " (olursa)"]), "x\n" + LONGNOTE + "\ny", "notlarda sıradaki var", "sıradaki olursa"])
    todo, done = todo_text(), todo_text()
    add("stale_next_note", {"notes": notes, "todo_text": todo, "done_text": done})
    proj = P("p", notes=notes)
    add("without_stale_note", {"proj": proj, "todo_text": todo, "lang": rnd.choice(["tr", "en"]), "done_text": done})
    real = rnd.random() < 0.4
    table = {"p": rnd.choice([None, 0, 1, -1, 5, "raise"])}
    if rnd.random() < 0.8:
        add_cb("next_work_hint", {"proj": proj, "real_only": real}, lambda c: sw.next_work_hint(proj, c["open_work"], real), {"open_work": table})
    else:
        add("next_work_hint", {"proj": proj, "real_only": real})
    add("notes_wait", {"proj": P("p", notes=rnd.choice(["", " ", "-", "# ", "[(", "\t", " ", "> "]) + rnd.choice(["BEKLEME x", "bekleme", "BEKLEMİYOR", "Bekle", notes]))})
for text in [None, "", "  ", "madde", "uzun " * 100, "raise"]:
    add_cb("_forced_open_nudge", {"proj": "p", "n_open": 3}, lambda c: sw._forced_open_nudge(c["oldest_open"], "p", 3), {"oldest_open": {"p": text}})

# döngü kesici, sonuç doğrulama, API kurtarma
LK = ["start", "stop", "tour", "deliver_answer", "directive", "restart", "nudge", "keepwarm", "ask_user", "idea", "loop_break", "idle_nudge"]
NAMES = ["", "a", "ab", "a20261126", "a20261126_2", "a_3", "mkt", "hc", "hc20261120", "hcr20261120", "x_1\n", "a2026112", "p_12_3"]


def aview(names=NAMES):
    return V(rnd.choice(names), rnd.random() < 0.8, blueprint=rnd.choice([None, None, "", "a", "mkt", "hc"]), busy=rnd.choice([None, True, False, False]),
             subagent_active=rnd.random() < 0.1, subagent_unknown=rnd.random() < 0.08,
             last_activity=rnd.choice([0.0, NOW - 30, NOW - 59.9, NOW - 60, NOW - 599, NOW - 5400, NOW + 5]), started_at=rnd.choice([0.0, NOW - 29, NOW - 30, NOW - 700, NOW - 7000]),
             last_assistant=rnd.choice(["", "iş", "API Error: 500 x", "API Error: 529 overloaded", "API Error: 400 bad", "api error: timeout", "ok"]))


for _ in range(1500):
    views = [aview() for _ in range(rnd.randint(0, 4))]
    actions = []
    for _ in range(rnd.randint(0, 4)):
        kind = rnd.choice(LK)
        items = rnd.choice([None, [], "ab", {"k": 1}, [{"kind": "ask", "id": "q1"}], [{"kind": "idle", "name": "a"}, 5, {"id": 0, "name": None}], [{}, {"kind": None, "id": [1, "x"]}]])
        actions.append(sw.Action(kind, rnd.choice(NAMES[:5]), rnd.choice(["neden", "u" * 250]), {} if items is None else {"items": items}))
    guard = {}
    for a in actions:
        if rnd.random() < 0.8:
            sig = sw._loop_sig(a.name, views)
            its = a.payload.get("items") or []
            fp = hashlib.sha1("|".join(sorted(f"{i.get('kind')}:{i.get('id') or i.get('name')}" for i in its if isinstance(i, dict))).encode()).hexdigest()[:8]
            full = sig + ":" + fp if a.kind == "tour" else sig
            guard[f"{a.kind}|{a.name}"] = rnd.choice([{"n": rnd.choice([1, 7, 8, 9]), "sig": full, "first": rnd.choice([NOW - 10, NOW - 86399, NOW - 86400, 0, None])},
                                                      {"n": 8, "sig": full, "first": NOW - 5, "fp": rnd.choice([fp, "eski", "", None])}, {"until": rnd.choice([NOW + 5, NOW, NOW - 5, None]), "first": NOW - 5},
                                                      {"n": "8", "sig": full, "first": str(NOW - 5)}, {"n": 3, "sig": "x", "first": NOW - 90000}, {}, "bozuk", {"until": NOW - 1, "first": NOW - 90000}])
    if rnd.random() < 0.3:
        guard[rnd.choice(["start|zz", "yalnız", "|", "a|b|c"])] = rnd.choice([{"until": NOW + 100}, {"first": NOW - 5}, {"until": "x"} if rnd.random() < 0.2 else {}, 7])
    st = rnd.choice([{}, {"x": 1}, {"x": 1, "loop_guard": guard, "z": 2}, {"loop_guard": guard}, {"loop_guard": None}])
    if rnd.random() < 0.2:
        st = {"loop_guard": guard}
    add("loop_guard", {"actions": actions, "views": views, "st": st, "now": NOW})
    add("loop_paused", {"st": st, "now": NOW})
    name = rnd.choice(NAMES)
    add("_loop_sig", {"name": name, "views": views})
    add("_outcome_views", {"name": name, "views": views})
    add("_outcome_project", {"name": name, "views": rnd.choice([views, []])})
    kind = rnd.choice(["start", "respawn", "directive", "nudge"])
    add("outcome_baseline", {"kind": kind, "name": name, "views": views, "now": NOW})
    pending = {}
    for i in range(rnd.randint(0, 5)):
        n = rnd.choice(NAMES[1:])
        rec = sw.outcome_baseline(rnd.choice(["start", "respawn", "directive", "nudge", ""]), n, views, rnd.choice([NOW, NOW - 599, NOW - 600, NOW - 6000, NOW + 40]))
        if rnd.random() < 0.3:
            rec["sigs"] = rnd.choice([None, {}, {n: "x"}])
        if rnd.random() < 0.3:
            rec["via"] = rnd.choice(["panel", "", 5, None])
        pending[f"k{i}"] = rnd.choice([rec, rec, rec, rec, {}, None, 0, []])
    add("check_outcomes", {"pending": pending, "views": views, "now": NOW})
    add("_via", {"rec": rnd.choice([{}, {"via": 0}, {"via": "m"}, {"via": 2.5}, {"via": [1, "a"]}])})
add("check_outcomes", {"pending": {f"k{i}": {"kind": "nudge", "name": "a", "at": NOW - (i * 37 % 205)} for i in range(215)}, "views": [], "now": NOW})
for _ in range(2500):
    views = [aview() for _ in range(rnd.randint(0, 6))]
    st_err = {}
    for v in views:
        if rnd.random() < 0.7:
            h = hashlib.sha1(v.last_assistant.encode()).hexdigest()[:10]
            rec = {"hash": rnd.choice([h, h, h, "x"]), "since": rnd.choice([NOW - 59, NOW - 60, NOW - 5000]), "nudges": rnd.choice([0, 0, 1, 2, 3, 3, 4, -1, "2"]),
                   "last_nudge": rnd.choice([0.0, NOW - 179, NOW - 180, NOW - 600, NOW - 599]), "gave_up": rnd.random() < 0.2}
            for k in ("since", "last_nudge"):
                if rnd.random() < 0.03:
                    rec.pop(k)
            st_err[v.name] = rnd.choice([rec] * 8 + [{}, None, 5])
    probe = rnd.choice(["", "a", "ab", "mkt"])
    st_out = rnd.choice([{}, {}, None, "x", {"since": NOW - 100, "probe": probe, "probe_at": rnd.choice([0.0, NOW, NOW + 5]), "woken": rnd.choice([[], ["a"], ["a", "ab", "zz"], "ab", None, [5]]), "recovered": rnd.random() < 0.5},
                         {"x": 1}, {"recovered": True, "woken": ["a", "mkt", "hc"]}])
    table = {v.name: rnd.random() < 0.9 for v in views}
    skip = set(rnd.sample(NAMES, rnd.choice([0, 0, 1])))
    before = json.loads(json.dumps(enc({"views": views, "skip": skip, "st_err": st_err, "st_out": st_out, "now": NOW})))
    log = []

    def eligible(v):
        log.append([[enc(v)], table[v.name]])
        return table[v.name]
    try:
        ret = enc(sw.plan_api_recovery(views, eligible, skip, st_err, st_out, NOW))
    except (KeyError, IndexError, TypeError, ValueError):
        continue
    OUT.setdefault("plan_api_recovery", []).append(json.dumps({"args": before, "ret": ret, "now": NOW, "callbacks": {"eligible": log}}, ensure_ascii=False, separators=(",", ":")))
    add("api_error_brief", {"st": rnd.choice([{}, {"api_err": None}, {"api_err": st_err}])})
for _ in range(100):
    kind = rnd.choice(["deliver_findings", "deliver_lesson", "start"])
    add("_observe_cluster", {"a": sw.Action(kind, "p", "", rnd.choice([{}, {"rows": [{"id": 5}, {"id": "b"}, "x", {}], "hashes": ["b", "a", 3, None]}, {"rows": None, "hashes": []}]))})

# boşta planları ve neden açıklaması
INAMES = ["a", "ab", "mkt", "ncs", "kitap", "degnekci", "a_aj1", "a_aj12\n", "a20261126", "ncs2"]
ILAST = ["", "iş sürüyor", "READY FOR HANDOVER", "bitti\nSTEWARD-DONE", "yapacak iş yok", "This turn failed", "API Error: 500", "kapı onayı bekliyor", "STEWARD-NEXT: raporu yaz", "STEWARD-NEXT: raporu yaz\nSTEWARD-ASK: x?", "STEWARD-NEXT: yok",
         "sıradaki: yok", "iş sahipte", "sahip kararı bekliyorum", "sıradaki: yok, kalanlar sahipte", "STEWARD-ASK: hangisi?", "STEWARD-JOB: embed a", "sahipte ama STEWARD-DONE", "sıradaki: testleri koş", "soru: STEWARD-BLOCKED pdf"]
INOTES = ["", "", "sıradaki: veri temizliği", "sıradaki: yok", "BEKLEME: dış girdi", "sıradaki: veri gelirse çiz", "notlarda sıradaki var", "sıradaki: fable cila"]
MODES = ["dry", "act", "act", "act", "off"]


def iview(cli):
    return V(rnd.choice(INAMES), rnd.random() < 0.95, cli=rnd.choice([cli] * 9 + ["codex"]), tmux=rnd.random() < 0.95, host=rnd.choice(["local"] * 9 + ["", "yuhem"]),
             blueprint=rnd.choice([None] * 6 + ["", "a", "mkt"]), busy=rnd.choice([False] * 8 + [True, None]), subagent_active=rnd.random() < 0.04, subagent_unknown=rnd.random() < 0.03,
             idle_since=rnd.choice([0.0, NOW - 100, NOW - 700, NOW - 700, NOW - 4000, NOW - 90000]), last_activity=rnd.choice([0.0, NOW - 100, NOW - 700, NOW - 700, NOW - 4000, NOW - 90000]),
             cache_ttl=rnd.choice(["", "1h", "5m"]), last_assistant=rnd.choice(ILAST))


def iproj():
    return {p: P(p, phase=rnd.choice(["planned"] * 6 + ["planning", "done", "paused"]), notes=rnd.choice(INOTES), cadence_minutes=rnd.choice([0, 60, 240]),
                 last_visit=rnd.choice([0.0, NOW - 100, NOW - 14400, NOW - 90000]), host=rnd.choice(["", "yuhem"])) for p in rnd.sample(["a", "ab", "mkt", "ncs", "kitap", "degnekci"], rnd.randint(2, 6))}


def iworld():
    if rnd.random() < 0.6:
        return None
    return sw.World(sid="default", owners={p: rnd.choice(["default"] * 5 + ["ab"]) for p in ["a", "ab", "mkt", "ncs", "kitap", "degnekci"]}, brains={"degnekci": "default"},
                    owned=rnd.choice([{}, {"a": "a"}, {"a": "a20261126", "mkt": "zz"}]), unavailable=frozenset(rnd.choice([[], [], ["a"], ["mkt"]])))


def irec(views, mode):
    out = {}
    for v in views:
        if rnd.random() < 0.5:
            since = max(v.idle_since, v.last_activity)
            rec = {"at": rnd.choice([0, since - 1, since, since + 1, NOW - 10, NOW - 90000]), "n": rnd.choice([0, 1, 2, 3, 9]), "mode": rnd.choice([mode, mode, mode, "dry"]),
                   "text": rnd.choice(["", "devam: veri temizliği" + sw.IDLE_STALE_NOTE_ESCAPE, "devam: TODO.md'deki ilk açık iş"]), "failed_closed": rnd.random() < 0.2}
            if rnd.random() < 0.15:
                rec.pop("mode")
            out[v.name] = rec
    return out


PKEYS = ["a", "ab", "mkt", "ncs", "kitap", "degnekci"]
for _ in range(2500):
    views = [iview("ucli") for _ in range(rnd.randint(0, 4))]
    mode = rnd.choice(MODES)
    cfg = C(ucli_idle=mode, ucli_idle_nudge_secs=rnd.choice([0, 600, 600, 600]), ucli_idle_nudge_secs_1h=rnd.choice([0, 3000]), drain=rnd.random() < 0.03, mode=rnd.choice(["act", "act", "observe"]),
            ucli_idle_max_consecutive=rnd.choice([1, 3]), brain_name="degnekci")
    projects, world = iproj(), iworld()
    state = rnd.choice([{}, {"x": 1, "ucli_idle": irec(views, mode)}, {"ucli_idle": irec(views, mode), "ho_pending": rnd.choice([{}, {"a": 1.0}, None]), "ho_close": rnd.choice([{}, {"zz": "p"}])}])
    planned = [sw.Action("start", rnd.choice(INAMES))] if rnd.random() < 0.15 else []
    args = {"views": views, "projects": projects, "state": state, "cfg": cfg, "now": NOW, "planned": planned, "world": world}
    table = {p: rnd.choice([None, 0, 2, "raise"]) for p in PKEYS}
    add_cb("plan_ucli_idle", args, lambda c: sw.plan_ucli_idle(views, projects, state, cfg, NOW, planned, world, c["open_work"]), {"open_work": table})
for _ in range(4000):
    views = [iview("claude") for _ in range(rnd.randint(0, 4))]
    mode = rnd.choice(MODES)
    cfg = C(claude_idle=mode, claude_idle_nudge_secs=rnd.choice([0, 600, 600, 600]), drain=rnd.random() < 0.03, ucli_idle_max_consecutive=rnd.choice([1, 3, 3]), brain_name="degnekci")
    projects, world = iproj(), iworld()
    state = {}
    if rnd.random() < 0.8:
        state["claude_idle"] = irec(views, mode)
    for p in PKEYS:
        if rnd.random() < 0.15:
            state.setdefault("owner_todo_move", {})[p] = {"at": rnd.choice([NOW - 10, NOW - 86400]), "mode": rnd.choice([mode, "dry"])}
        if rnd.random() < 0.25:
            state.setdefault("todo_triage", {})[p] = {"sha": rnd.choice(["abc", "abcdefabcdef999", "x"]), "mode": rnd.choice([mode, mode, "dry"])}
        if rnd.random() < 0.15:
            state.setdefault("owner_claim_nudge", {})[p] = {"session": rnd.choice([p, "a"]), "at": rnd.choice([0, NOW - 10, NOW - 90000])}
        if rnd.random() < 0.25:
            state.setdefault("next_none", {})[p] = {"open": rnd.choice([0, 2, "2"]), "session": rnd.choice([p, p, "x"]), "at": 1.0}
    if rnd.random() < 0.1:
        state["ho_pending"] = {"a": 1.0}
    planned = [sw.Action("start", rnd.choice(INAMES))] if rnd.random() < 0.15 else []
    args = {"views": views, "projects": projects, "state": state, "cfg": cfg, "now": NOW, "planned": planned, "world": world}
    tables = {"open_work": {p: rnd.choice([None, 0, 2, 2, "raise"]) for p in PKEYS}, "owner_todo": {p: rnd.choice([None, 0, 0, 0, 3, "raise"]) for p in PKEYS},
              "todo_sha": {p: rnd.choice(["abc", "abcdefabcdef999", "", None, "raise"]) for p in PKEYS}, "oldest_open": {p: rnd.choice(["", None, "ilk madde " * rnd.randint(1, 60), "raise"]) for p in PKEYS},
              "has_question": {p: rnd.choice([True, False, False, "raise"]) for p in PKEYS}}
    tables = {k: v for k, v in tables.items() if rnd.random() < 0.85}
    add_cb("plan_claude_idle", args, lambda c: sw.plan_claude_idle(views, projects, state, cfg, NOW, planned, world, c.get("open_work"), c.get("owner_todo"), c.get("todo_sha"), c.get("oldest_open"), c.get("has_question")), tables)
for code, lang in itertools.product([*sw._WHY_TR, "bilinmeyen"], ["tr", "en", "de"]):
    detail, extra = rnd.choice(["", "d"]), rnd.choice([{}, {"until": 1.5, "kind": "x"}])
    add("_why", {"code": code, "lang": lang, "detail": detail, "extra": extra}, call=lambda: sw._why(code, lang, detail, **extra))
for i in range(5000):
    cli = rnd.choice(["claude", "claude", "claude", "ucli"])
    views = [iview(cli) for _ in range(rnd.choice([0, 0, 1, 1, 1, 2, 3]))]
    projects = iproj()
    name = rnd.choice(list(projects))
    proj = projects[name]
    if views and rnd.random() < 0.7:
        views[0].name, views[0].blueprint, views[0].running = name, None, True
        views = views[:1] if rnd.random() < 0.85 else views
    if rnd.random() < 0.75:
        proj.phase, proj.notes = "planned", rnd.choice([n for n in INOTES if not n.startswith("BEKLEME")])
    cfg = C(lang=rnd.choice(["tr", "en"]), claude_idle=rnd.choice(MODES), claude_idle_nudge_secs=rnd.choice([0, 600, 600, 600]), drain=rnd.random() < 0.04, auto_start=rnd.random() < 0.8,
            ucli_idle_max_consecutive=rnd.choice([1, 3]), brain_name="degnekci")
    questions = []
    if rnd.random() < 0.2:
        questions = [Q(f"q{j}", rnd.choice([name, name, "zz"]), rnd.choice(["soru\n metni", "u " * 120]), status=rnd.choice(["open", "answered", "closed"]), routine=rnd.random() < 0.3,
                       delivered_at=rnd.choice([0.0, 5.0]), undeliverable=rnd.choice(["", "yok"])) for j in range(rnd.randint(1, 3))]
    state = {}
    if rnd.random() < 0.12:
        state["loop_guard"] = {rnd.choice([f"start|{name}", f"nudge|{name}20261126", "tour|degnekci", name]): rnd.choice([{"until": NOW + 3600}, {"until": NOW - 1}, 5, {}])}
    if rnd.random() < 0.15:
        state["brain_stopped"] = {rnd.choice([name, name + "20261126", "zz"]): rnd.choice([NOW - 10, NOW - 14399, NOW - 14400, 0, None])}
    if rnd.random() < 0.15:
        state["observed_visit"] = {name: rnd.choice([NOW - 10, 0, None, NOW - 3599.5])}
    if rnd.random() < 0.15:
        state["start_blocked"] = rnd.choice([{"projects": [name], "reason": rnd.choice(["max_starts", "max_active", "başka", "", None])}, {"projects": [], "reason": "x"}, {"projects": None}, {"projects": name + "x", "reason": "auto_start_off"}, {}])
    vname = views[0].name if views else name
    if rnd.random() < 0.08:
        state["dialog_stuck"] = {vname: rnd.choice([{"kind": "trust", "head": "H" * 250, "since": NOW}, {}, {"kind": None, "head": 5, "since": None}, "x"])}
    if rnd.random() < 0.1:
        state["send_fail"] = {vname: rnd.choice([{"n": 3, "error": "e" * 250, "since": NOW}, {"n": 2}, {"n": "4"}, {"n": 5, "error": None}, 1])}
    if views and rnd.random() < 0.5:
        state["claude_idle"] = irec(views, cfg.claude_idle)
    if rnd.random() < 0.3:
        state["todo_triage"] = {name: rnd.choice([{"sha": "a"}, {}, None])}
    if rnd.random() < 0.3:
        state["next_none"] = {name: rnd.choice([{"open": 0}, {"open": 2}, {"x": 1}, {}])}
    if rnd.random() < 0.3:
        state["project_next"] = {name: rnd.choice([{"text": "T" * 250, "none": 1, "at": NOW, "session": "s"}, {"text": ""}, {"text": 5}, "x", {"text": "t", "at": None}])}
    actions = []
    if rnd.random() < 0.2:
        actions = [sw.Action(rnd.choice(["start", "idle_nudge"]), rnd.choice([name, vname]), "neden", rnd.choice([{}, {"next": "n" * 200}, {"next": None}, {"next": 7}]))]
    world = iworld()
    args = {"proj": proj, "views": views, "projects": projects, "state": state, "cfg": cfg, "now": NOW, "questions": questions, "actions": actions, "world": world}
    table = {p: rnd.choice([None, 0, 0, 2, "raise"]) for p in PKEYS}
    add_cb("explain_idle", args, lambda c: sw.explain_idle(proj, views, projects, state, cfg, NOW, questions, actions, world, c["open_work"]), {"open_work": table})
    if i % 5 == 0:
        args = {k: v for k, v in args.items() if k != "proj"}
        owner = {p: rnd.choice([None, 0, 3, "raise"]) for p in PKEYS}
        add_cb("explain_idle_all", args, lambda c: sw.explain_idle_all(views, projects, state, cfg, NOW, questions, actions, world, c["open_work"], c["owner_todo"]), {"open_work": table, "owner_todo": owner})

# nadir boşta dalları: tek uygun oturum, yoğun durum
for i in range(2500):
    cli = rnd.choice(["claude", "ucli"])
    since = NOW - rnd.choice([700, 3600, 3601, 90000])
    txt = rnd.choice(["sıradaki: yok", "sıradaki: yok", "iş sahipte", "This turn failed", "iş sürüyor", "yapacak iş yok", "sıradaki: yok\niş sahipte"])
    v = V("a", True, cli=cli, tmux=True, busy=False, idle_since=since, last_activity=since, last_assistant=txt, cache_ttl=rnd.choice(["", "1h"]))
    projects = {"a": P("a", phase="planned", notes=rnd.choice(INOTES))}
    mode = rnd.choice(["dry", "act"])
    rec = {"at": rnd.choice([since - 1, since, since + 1]), "n": rnd.choice([0, 1, 2, 3]), "mode": rnd.choice([mode, mode, "dry"]), "failed_closed": rnd.random() < 0.2,
           "text": rnd.choice(["", "devam: veri temizliği" + sw.IDLE_STALE_NOTE_ESCAPE])}
    n_open = rnd.choice([0, 2])
    state = {"claude_idle": {"a": rec}, "ucli_idle": {"a": rec}}
    if rnd.random() < 0.6:
        state["next_none"] = {"a": {"open": rnd.choice([n_open, n_open, 7]), "session": rnd.choice(["a", "a", "x"]), "at": 1.0}}
    if rnd.random() < 0.4:
        state["todo_triage"] = {"a": {"sha": rnd.choice(["abc", "x"]), "mode": rnd.choice([mode, "dry"])}}
    cfg = C(claude_idle=mode, claude_idle_nudge_secs=600, ucli_idle=mode, ucli_idle_nudge_secs=600, ucli_idle_nudge_secs_1h=600, ucli_idle_max_consecutive=rnd.choice([1, 3]), mode=rnd.choice(["act", "observe"]), brain_name="degnekci")
    views = [v]
    args = {"views": views, "projects": projects, "state": state, "cfg": cfg, "now": NOW, "planned": [], "world": None}
    tables = {"open_work": {"a": n_open}}
    if cli == "claude":
        if rnd.random() < 0.5:
            tables["todo_sha"] = {"a": rnd.choice(["abc", "raise"])}
        if rnd.random() < 0.8:
            tables["oldest_open"] = {"a": rnd.choice(["ilk açık madde", "uzun madde " * 90, "", "raise"])}
        if rnd.random() < 0.5:
            tables["has_question"] = {"a": rnd.choice([True, False, "raise"])}
        add_cb("plan_claude_idle", args, lambda c: sw.plan_claude_idle(views, projects, state, cfg, NOW, [], None, c.get("open_work"), c.get("owner_todo"), c.get("todo_sha"), c.get("oldest_open"), c.get("has_question")), tables)
        eargs = {"proj": projects["a"], "views": views, "projects": projects, "state": state, "cfg": cfg, "now": NOW, "questions": [], "actions": [], "world": None}
        add_cb("explain_idle", eargs, lambda c: sw.explain_idle(projects["a"], views, projects, state, cfg, NOW, [], [], None, c["open_work"]), {"open_work": {"a": n_open}})
    else:
        add_cb("plan_ucli_idle", args, lambda c: sw.plan_ucli_idle(views, projects, state, cfg, NOW, [], None, c["open_work"]), tables)

# ── grup 4: gözlem süzgeci ve raporlar ──
rnd = random.Random(4)
OK_KINDS = ["start", "stop", "tour", "deliver_answer", "deliver_findings", "deliver_lesson", "deliver_job", "directive", "nudge", "ask_user", "idea", "set_phase", "loop_break", "notify", "keepwarm", "idle_nudge", "handover"]
for _ in range(2000):
    actions = []
    for _ in range(rnd.randint(0, 5)):
        kind = rnd.choice(OK_KINDS)
        payload = rnd.choice([{}, {"question_id": "q1"}, {"question_id": "", "job_id": "j1"}, {"job_id": 7}, {"rows": [{"id": 1}, {"id": "b"}]}, {"hashes": ["h2", "h1"]},
                              {"items": [{"kind": "blocked", "id": "q1"}, {"kind": "blocked", "id": "q2"}, {"kind": "ask", "id": "q1"}, {"kind": "blocked"}]},
                              {"items": [{"kind": "blocked", "id": "q1"}, {"kind": "blocked", "id": "q1"}]}, {"items": None}, {"question_id": 0, "items": []}])
        actions.append(sw.Action(kind, rnd.choice(["a", "b", ""]), "r", payload))
    state = {}
    if rnd.random() < 0.6:
        state["observed"] = rnd.choice([{}, None, {"start:a:": NOW - 21599, "stop:b:": NOW - 21600, "tour:a:": str(NOW - 5), "start:b:q1": NOW}, {"start:a:": "x"}])
    if rnd.random() < 0.5:
        state["observed_visit"] = rnd.choice([{}, {"z": 1.0}, None])
    if rnd.random() < 0.7:
        state["blocked_tours"] = rnd.choice([{}, None, {"q1": 1, "q2": 3}, {"q1": 2, "None": 1}, {"q1": "2"}, {"q1": 0}, {"q1": None}, {"zz": 5}])
    state["x"] = 1
    add("observe_filter", {"actions": actions, "mode": rnd.choice(["observe", "observe", "observe", "act", ""]), "state": state, "now": NOW})
for _ in range(500):
    rep = {}
    for kind in rnd.sample(["wake_repeat", "wake_cap", "brain_wake_cap", "keepwarm", "idle_big_handover", "start", "stop"], rnd.randint(0, 6)):
        rep[kind] = {"count": rnd.randint(0, 5), "names": {n: rnd.randint(1, 3) for n in rnd.sample(["a", "b", "c", "d", "-"], rnd.randint(0, 5))}, "chars": rnd.choice([0, 0, 12, 3.5]),
                     "first": rnd.choice([NOW - 10, NOW - 259200, NOW - 259199, NOW - 900000]), "last": NOW}
    hours = rnd.choice([72, 1, 1.5, 0.0])
    add("dry_report_text", {"rep": rep, "hours": hours})
    add("dry_report_text", {"rep": rep, "hours": hours, "lang": "en"})
    add("dry_ask_due", {"rep": rep, "asked": rnd.choice([None, [], ["wake_gate"], ["keepwarm", "x"], "keepwarm"]), "now": NOW, "hours": hours})
for hour, offset, sd in itertools.product([0, 8, 19, 20, 23, 24], [0, 3600 * 5, -3600 * 7, 86400 * 40], [None, "", "x", "bugün"]):
    t = NOW + offset
    today = time.strftime("%Y-%m-%d", time.localtime(t))
    add("summary_due", {"state": {} if sd is None else {"summary_date": today if sd == "bugün" else sd}, "now": t, "hour": hour})
for names, n in itertools.product([[], [""], ["a"], ["a", "a", "b", "", "c", "d", "e", "f", "g"], list("abcdefghij")], [0, 1, 5, 8]):
    add("_names", {"names": names, "n": n})
VALS = [None, "", "a", "b", 0, 1, True, False, 2.5, ["x"], {"k": "v"}]


def entry():
    e = {"ts": rnd.choice(["2026-11-26T10:00:00", "2026-11-26T23:59:59", "2026-11-25T10:00:00"] + ["2026-11-26T01:00:00"] * 3),
         "event": rnd.choice(["tick", "tick", "ticks", "action", "action", "action", "would:start", "would:keepwarm", "would:a:b", "would:", "ask", "idea", "answer", "card", "handover", "directive", "tour", "skip", "review_store_held", "ask_gate", "ask_gate", "x"])}
    opt = {"kind": rnd.choice(["ask_user", "idea", "set_phase", "handover", "start", "nudge", "", None, 5]), "ok": rnd.choice([True, True, False, 0, None]), "name": rnd.choice(["a", "b", "c", "d", "e", "f", "g", "", None, 3]),
           "mode": rnd.choice(["act", "observe", "shadow", "shadow", "on", "", None]), "n": rnd.choice([0, 1, 40, None, "3"]), "manual": rnd.choice([0, 2, None]), "errors": rnd.choice([0, 1, None]),
           "trigger": rnd.choice(["timer", "timer", "manual", None]), "error": rnd.choice(["", "boom", None]), "reason": rnd.choice(["done", "", None, "paused " * 30]), "files": rnd.choice([[], None, ["f1", "f2", "f1", 3, "f4", "f5", "f6"], "ab"]),
           "applied": rnd.choice([True, False, None]), "allow": rnd.choice([True, False]), "id": rnd.choice(["q1", "q2", "q3", None, 5]), "project": rnd.choice(["p", None]), "question": rnd.choice(["soru?", "u " * 100, None, "", " x\ny "]),
           "answer": rnd.choice(["evet", "😀" * 150, None, ""])}
    for k, v in opt.items():
        if rnd.random() < 0.7:
            e[k] = v
    return e


for _ in range(1500):
    entries = [entry() for _ in range(rnd.randint(0, 14))]
    answered = rnd.choice([None, {}, {"q1": "brain", "q2": "owner_panel", "q3": "", "None": "motor", "5": "cops"}])
    args = {"entries": entries, "date": rnd.choice(["2026-11-26"] * 5 + ["2026-11-25", "2026", ""]), "lang": rnd.choice(["tr", "en", "de"]),
            "pending": rnd.choice([None, {}, {"open_questions": 2, "ideas_new": 0, "pending_items": 5, "undelivered_answers": 1}]),
            "orphans": rnd.choice([None, {}, {"servers": 0, "procs": 0}, {"servers": 2}, {"procs": 3, "servers": 1}]), "answered_by": answered}
    add("daily_summary", args)
    add("_kind_counts", {"entries": entries, "key": rnd.choice(["kind", "event", "ok", "name"])})
    gate = [e for e in entries if e.get("event") == "ask_gate"] or ([entry()] if rnd.random() < 0.5 else [])
    add("_ask_gate_lines", {"events": gate, "answered_by": answered or {}, "en": rnd.random() < 0.5})
for v in [None, "", "x", " 12 ", "1_0", "1.5", 0, -3, 2.9, True, False, [], [1], {}, {"a": 1}]:
    add("_count_or_zero", {"value": v})
for _ in range(60):
    add("summarize_projects", {"projects": {f"p{i}": P(f"p{i}", phase=rnd.choice(["idea", "planning", "planned", "paused", "done", "bozuk", ""])) for i in range(rnd.randint(0, 8))}})
for date, sid in itertools.product(["2026-11-26", "", "a/b", "/kök"], [None, "default", "iso"]):
    base = "/s/steward"
    paths = None if sid is None else sw.paths_for(sid)
    # Rust'ta kök parametredir: vektördeki yol `STEWARD_DIR` yerine verilen köke taşınır
    add("daily_path", {"base": base, "date": date, "sid": sid}, call=lambda: sw.daily_path(date, paths).replace(sw.STEWARD_DIR, base))

# ── grup 5: plan_tick (kaydın kapsamadığı dallar; 3 tick'lik zincirler, durum bir sonrakine geçer) ──
rnd = random.Random(5)
sw._now = lambda: NOW
TP = ["alfa", "beta", "gama", "delta", "eps"]
T_SESS = [p + suf for p in TP for suf in ("", "20261126", "20261126_2")] + ["degnekci", "degnekci_x", "adhoc1", "yok20261001"]
T_TEXTS = ["", "çalışıyorum", "devir notu\nREADY FOR HANDOVER", "STEWARD-DONE", "STEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt",
           "STEWARD-DONE-CONFIRMED: kanıt yok", "STEWARD-DONE-CONFIRMED: abc1234 kalan 2", "STEWARD-PLAN-READY", "STEWARD-ASK: hangisi?",
           "STEWARD-ROUTINE: ne zaman?", "STEWARD-BLOCKED: pdf yok", "STEWARD-IDEA: fikir", "STEWARD-NEXT: raporu yaz", "STEWARD-NEXT: yok",
           "STEWARD-ASK: Which one should I pick for the report?", "API Error: 500 overloaded", "API Error: 400 bad request",
           "STEWARD-LESSON: ders", "STEWARD-JOB: embed a.txt", "uzun cevap " * 30]
T_QTEXTS = ["Bu oturumda mı devam edeyim, yoksa devir ile yeni oturumda mı?", "Should I continue in this session or do a handover?",
            "bu oturumda mı sürdüreyim, devir mi? commit atayım mı?", "x: STEWARD-DONE-CONFIRMED geldi ama çelişti", "hangisi?",
            sw.BLOCKED_TEXT_PREFIX + "pdf yok", "rutin soru?"]
T_ANS = ["evet", "aç", "Aç", "hayır", "paused kalsın", "bitti", "bitmedi", "bitti ama testler kaldı", "devam et lütfen, " + "uzun talimat " * 8, ""]
T_TIMES = [0.0, NOW - 30, NOW - 61, NOW - 600, NOW - 1799, NOW - 1801, NOW - 3000, NOW - 4000, NOW - 7300, NOW - 15000, NOW - 90000]


def t_proj():
    out = {}
    for name in rnd.sample(TP, rnd.randint(1, 5)):
        out[name] = P(name, phase=rnd.choice(["planning", "planned", "planned", "done", "paused", "idea"]), priority=rnd.randint(1, 4),
                      cadence_minutes=rnd.choice([0, 30, 60, 60]), last_visit=rnd.choice([0.0, NOW - 600, NOW - 4000, NOW - 90000]),
                      notes=rnd.choice(["", "", "", "BEKLEME: veri", sw.NO_DONE_TAG]), model=rnd.choice(["", "claude-fable-5-1"]))
    return out


def t_view(name):
    return V(name, rnd.random() < 0.85, tmux=rnd.random() < 0.9, blueprint=rnd.choice([None, None, None, "", rnd.choice(TP)]),
             busy=rnd.choice([None, True, False, False, False]), history_size=rnd.choice([None, 10, 1950, 5000]),
             context_tokens=rnd.choice([None, None, 0, 50000, 160000, 250000, 310000, 450000]),
             model=rnd.choice(["", "claude-opus-4", "claude-fable-5-1"]), last_assistant=rnd.choice(T_TEXTS) + rnd.choice(["", "\n" + rnd.choice(T_TEXTS)]),
             last_activity=rnd.choice(T_TIMES), started_at=rnd.choice(T_TIMES), subagent_active=rnd.random() < 0.15,
             subagent_unknown=rnd.random() < 0.15, host=rnd.choice(["", "", "h1"]))


def t_question(i, projects):
    proj = rnd.choice(list(projects) + ["", "degnekci", "yok", "adhoc1"])
    status = rnd.choice(["open", "answered", "answered"])
    text = rnd.choice(T_QTEXTS)
    if "STEWARD-DONE" in text:
        text = f"{proj}: " + text
    return sw.Question(f"q{i}", proj, text, created_at=rnd.choice(T_TIMES), status=status, answer=rnd.choice(T_ANS) if status == "answered" else "",
                       answered_at=rnd.choice(T_TIMES) if status == "answered" else 0.0, delivered_at=rnd.choice([0.0, 0.0, 0.0, NOW - 5]),
                       source=rnd.choice(T_SESS + [""]), routine=rnd.random() < 0.3, notified_at=rnd.choice([0.0, NOW - 50]),
                       answered_by=rnd.choice(["", "owner_panel", "brain", "motor"]))


def t_state(projects, names):
    st = {}
    pick = lambda xs, k: rnd.sample(xs, min(len(xs), rnd.randint(0, k)))   # noqa: E731
    opt = lambda key, val: st.__setitem__(key, val) if rnd.random() < 0.35 else None   # noqa: E731
    opt("ho_pending", {n: rnd.choice([NOW - 60, NOW - 2000, NOW - 99999]) for n in pick(names + ["oldgone"], 3)})
    opt("ho_close", {n: rnd.choice(TP) for n in pick(names, 2)})
    opt("ho_pause", {n: rnd.choice(["keepwarm", ""]) for n in pick(names, 2)})
    opt("done_pending", {n: rnd.choice(TP + ["yok"]) for n in pick(names, 2)})
    opt("done_confirm", {p: rnd.choice([NOW - 60, NOW - 30000]) for p in pick(TP, 2)})
    opt("ho_deferred", {n: rnd.choice([{"since": NOW - 60, "why": "busy"}, {"since": NOW - 4000, "why": "subagent_active"}, {"why": "busy"}, "eski"])
                        for n in pick(names, 3)})
    opt("pause_close", {p: rnd.choice([NOW - 60, NOW - 30000]) for p in pick(TP, 2)})
    opt("last_directive_at", {n: rnd.choice([NOW - 30, NOW - 5000]) for n in pick(names, 3)})
    opt("reviewed_at", {n: NOW - 9000 for n in pick(names, 2)})
    opt("observed_visit", {p: rnd.choice([NOW - 30, 0]) for p in pick(TP, 2)})
    opt("tbd_asked", {p: rnd.choice([NOW - 30, NOW - 30000]) for p in pick(TP, 2)})
    opt("todo_seen", {p: rnd.choice(["s1", "s2"]) for p in pick(TP, 3)})
    opt("todo_swept", {p: rnd.choice([NOW - 30, NOW - 90000]) for p in pick(TP, 2)})
    opt("todo_paused_asked", {p: rnd.choice([NOW - 30, NOW - 90000]) for p in pick(TP, 2)})
    opt("brain_stopped", {n: rnd.choice([NOW - 30, NOW - 90000, None]) for n in pick(names, 2)})
    opt("skip_seen", {n: rnd.choice([{"at": NOW - 30, "sig": "x"}, {"at": NOW - 90000}, "bozuk"]) for n in pick(names, 2)})
    opt("blocked_tours", {f"q{i}": rnd.choice([0, 1, 2, 3]) for i in pick(list(range(6)), 3)})
    opt("last_tour", rnd.choice([0.0, NOW - 30, NOW - 4000]))
    opt("tour_deferred", rnd.choice([True, 0]))
    opt("ask_seen", {f"q{i}": {"n": 1, "at": NOW - 30} for i in pick(list(range(6)), 2)})
    opt("ask_gated", {f"q{i}": 1 for i in pick(list(range(6)), 2)})
    opt("no_work_paused", rnd.choice([{p: NOW for p in pick(TP, 2)}, [rnd.choice(TP)], {}]))
    opt("api_err", {n: {"since": NOW - 900, "nudges": rnd.randint(0, 3), "last_nudge": NOW - 700, "gave_up": False, "hash": "x"} for n in pick(names, 2)})
    opt("api_outage", {"since": NOW - 900, "probe": rnd.choice(["", names[0] if names else ""]), "probe_at": NOW - 10, "woken": [], "recovered": rnd.random() < 0.5})
    opt("seen_assistant", {n: "0" * 16 for n in pick(names, 2)})
    opt("owned", {p: rnd.choice(names) for p in pick(TP, 2)} if names else {})
    return st


def t_world(projects, cfg):
    sid = rnd.choice(["default", "default", "iso"])
    owners = {p: rnd.choice([sid, sid, sid, "default", "iso", ""]) for p in projects}
    owners = {p: o for p, o in owners.items() if o}
    return sw.World(sid=sid, owners=owners, conflicts=frozenset(rnd.sample(list(projects), rnd.choice([0, 0, 0, 1])) if projects else []),
                    brains={cfg.brain_name or "degnekci": sid}, is_adhoc_owner=sid == "default", starts_left=rnd.choice([None, None, 0, 1, 3]),
                    owned={p: rnd.choice(T_SESS) for p in rnd.sample(list(projects), rnd.choice([0, 0, 1]))},
                    unavailable=frozenset(rnd.sample(list(projects), rnd.choice([0, 0, 0, 1]))),
                    quota_held=frozenset(rnd.sample(list(projects), rnd.choice([0, 0, 0, 1]))))


def t_cfg():
    return C(enabled=True, max_active=rnd.choice([0, 1, 2, 4]), max_starts_per_tick=rnd.choice([0, 1, 2]), auto_start=rnd.random() < 0.8,
             drain=rnd.random() < 0.1, auto_context_answer=rnd.random() < 0.8, done_handover=rnd.random() < 0.6,
             done_handover_min_ratio=rnd.choice([0.0, 0.3]), max_active_total=rnd.choice([0, 2, 6]), lang=rnd.choice(["tr", "tr", "en"]),
             history_min_age_minutes=rnd.choice([0, 15]), context_warn_tokens=rnd.choice([0, 300000, 300000]),
             handover_defer_max_minutes=rnd.choice([0, 30]), ask_gate=rnd.choice(["off", "on", "shadow"]), tour_minutes=rnd.choice([1, 15]),
             stop_idle_minutes=rnd.choice([30, 45]), brain_name=rnd.choice(["degnekci", "degnekci", ""]))


def t_callbacks(projects):
    keys = list(projects)
    cbs = {}
    if rnd.random() < 0.7:
        cbs["open_work"] = {p: rnd.choice([None, 0, 0, 2]) for p in keys}
    if rnd.random() < 0.6:
        cbs["open_tbd"] = {p: rnd.choice([None, 0, 1]) for p in keys}
    if rnd.random() < 0.5:
        cbs["open_work_real"] = {p: rnd.choice([None, 0, 3]) for p in keys}
    if rnd.random() < 0.5:
        cbs["todo_sha"] = {p: rnd.choice(["s1", "s2", "", None, "raise"]) for p in keys}
    if rnd.random() < 0.4:
        cbs["claim_check"] = {p: rnd.choice([[], [], ["not çelişkisi"]]) for p in keys}
    return cbs


def t_tick(views, projects, state, cfg, questions, ideas, world, cbs):
    args = {"views": views, "projects": projects, "state": state, "cfg": cfg, "now": NOW, "questions": questions, "ideas": ideas, "world": world}
    holder = []

    def run(live):
        ret = sw.plan_tick(**args, **live)
        holder.append(ret)
        return ret
    add_cb("plan_tick", args, run, cbs)
    return holder[0][1] if holder else state


for _ in range(220):
    projects = t_proj()
    cfg = t_cfg()
    names = rnd.sample(T_SESS, rnd.randint(0, 7))
    state = t_state(projects, names)
    questions = [t_question(i, projects) for i in range(rnd.randint(0, 6))]
    ideas = [sw.Idea(id="i1", text="fikir", created_at=NOW - 100)] if rnd.random() < 0.3 else []
    world = t_world(projects, cfg) if rnd.random() < 0.5 else None
    cbs = t_callbacks(projects)
    views = [t_view(n) for n in names]
    for step in range(3):
        state = t_tick(views, projects, state, cfg, questions, ideas, world, cbs)
        # sonraki tick: bazı oturumlar devir notu yazdı, kapandı ya da boşaldı
        for v in views:
            r = rnd.random()
            if r < 0.25:
                v.last_assistant = "devir notu\nREADY FOR HANDOVER"
            elif r < 0.35:
                v.running = False
            elif r < 0.5:
                v.busy = False
            elif r < 0.6:
                v.last_assistant = rnd.choice(T_TEXTS)
# rastgele zincirlerin ulaşmadığı dallar (tick_cover.py): erişilemeyen host'ta erteleme/DONE izi korunur; keepwarm zinciri kapatması
W_UN = sw.World(sid="default", owners={"alfa": "default"}, brains={"degnekci": "default"}, unavailable=frozenset({"alfa"}))
for st in [{"ho_deferred": {"alfa20261126": {"since": NOW - 60, "why": "busy"}}, "done_pending": {"alfa20261126": "alfa"}},
           {"ho_deferred": {"alfa20261126": "eski", "beta": {"why": "x"}}, "done_pending": {"alfa20261126": "yok", "beta": "alfa"}}]:
    t_tick([], {"alfa": P("alfa", phase="planned")}, st, C(enabled=True), [], [], W_UN, {})
for why, lang in [("keepwarm", "tr"), ("", "tr"), ("keepwarm zinciri", "en")]:
    t_tick([V("beta", True, tmux=True, busy=False, last_assistant="not\nREADY FOR HANDOVER")], {"beta": P("beta", phase="planned")},
           {"ho_pending": {"beta": NOW - 60}, "ho_close": {"beta": "beta"}, "ho_pause": {"beta": why}}, C(enabled=True, lang=lang), [], [], None, {})
# bozuk tipli durum alanları: Python TypeError/ValueError -> Rust hata
for key, val in [("done_confirm", {"alfa": "x"}), ("blocked_tours", {"q1": None}), ("ho_pending", {"alfa": "x"}), ("tbd_asked", {"alfa": "x"}),
                 ("skip_seen", {"a": {"at": "x"}}), ("last_tour", "x"), ("observed_visit", {"alfa": "x"}), ("todo_swept", {"alfa": None})]:
    projects = {"alfa": P("alfa", phase="planned", cadence_minutes=30)}
    views = [V("alfa", True, tmux=True, busy=False, context_tokens=400000)]
    add_cb("plan_tick", {"views": views, "projects": projects, "state": {key: val}, "cfg": C(enabled=True), "now": NOW, "questions": [], "ideas": [], "world": None},
           lambda live: sw.plan_tick(views, projects, {key: val}, C(enabled=True), NOW, [], [], **live),
           {"open_work": {"alfa": 1}, "todo_sha": {"alfa": "s"}})

# ── TBD#377 / TBD#382 düzeltmeleri (sabit girdiler: yukarıdaki rastgele üreticilerin dizisini bozmasın diye sonda) ──
sw._now = lambda: NOW
TAIL = " Bu oturumda mı sürdüreyim, devir notuyla yeni oturuma mı bırakayım?"
CTXQ = ["Bağlam 210K token oldu.", "~910K token'lık okuma.", "Bağlam 210K/300K token.", "180 bin token.", "(250.000 token)", "1,5 milyon tokens", "210000+ tokens", "200K'lık token",
        "Token sayısı yüksek.", "TOKEN SAYISI yüksek.", "Token usage is high.", "token count 5", "Context: tokens: 200K.", "tokens = ~1.5m", "Bağlam token'ı doldu.",
        "Context is at 200k tokens.", "API token'ı gerek.", "2 token lazım.", "2025 token'ı.", "210Ktoken", "v2.210K token", "x210K token", "210 km token", "210K token; yeni token üret.",
        "HF_TOKEN yok.", "parola gerek", "PAROLA", "kurulum gerek", "kurulacak", "yetki gerek", "harcama 20 USD", "This will spend money.", "password", "credentials", "sudo apt", "install it",
        "٢١٠K token", "２１０,０００ tokens", "210K TOKENS", "210K tokenı", "100,00 token", "tokens: 200", "token usageX", ""]
for a in CTXQ:
    add("_context_owner_topic", {"text": a})
    add("is_context_question", {"text": a + TAIL})
for extra in [{"options": ["paketi kur (sudo)", "bırak"]}, {"options": ["210K token sonra", "şimdi"]}, {"detail": "Durum: API harcaması."}, {"detail": "Bağlam 210K token."},
              {"extra_texts": ["Parola dosyasını okuyayım mı?"]}, {"prev_texts": ["Yetki vereyim mi?"]}, {"options": ["commit et"]}, {}]:
    for tokens in (1000, 290000):
        views = [V("alfa", True, tmux=True, busy=False, context_tokens=tokens, model="claude-sonnet-5-5", started_at=1.0, last_activity=NOW)]
        projects = {"alfa": P("alfa", phase="planned")}
        qs = [Q("q1", "alfa", TAIL.strip(), created_at=NOW - 60, source="alfa", **extra)]
        cfg = C(enabled=True, context_warn_tokens=300000)
        add("plan_tick", {"views": views, "projects": projects, "state": {}, "cfg": cfg, "now": NOW, "questions": qs, "ideas": [], "world": None})
for t in ["no tools needed", "No tool is needed.", "no tools are required", "no tools were needed", "No tool calls needed.", "no tool calls are necessary", "no deferred tools needed",
          "No tool use required.", "no tools will be needed", "no-tool use needed", "no tools\nneeded", "no tools; needed later", "no tools needednt", "no tools, which are needed",
          "No matching deferred tools found", "no tools available", "I have no tools.", "no tool calls", "NO TOOLS NECESSARY", "no tools needed, tools unavailable"]:
    add("brain_tools_missing_text", {"text": t})
tag = sw.upper_tier_tag("p", "opus", "high")
for ans in ["evet .", "onayla !", "Evet . !", "approve  !!", "yes ...", "evet\n.", "evet .", "evet\u001c!", "hayır .", "evet değil .", ". evet", "onaylamıyorum .", " . ", "!", "evet ?", "evet,"]:
    add("upper_tier_approved", {"questions": [Q("q", "p", tag + " ?", answer=ans, status="answered", source=sw.UPPER_MODEL_SOURCE)], "project": "p", "model": "opus", "effort": "high"})
for limit in (-3, -1, 0, 1):
    mine, taken = [V("a", True, busy=False)], set()
    add("plan_deliveries", {"entries": [["a", "nudge"]], "mine": mine, "taken": taken, "state": {"x": 1}, "now": NOW, "limit": limit},
        call=lambda: sw.plan_deliveries([("a", lambda v: sw.Action("nudge", v.name, "a"))], mine, taken, {"x": 1}, NOW, limit))
for deferred in (0.0, -1.0, 1.0):
    q = Q("q", "a", "hangi sıra?", deferred_until=deferred)
    add("owner_class", {"q": q, "owner_projects": "", "note": "", "now": 0.0}, call=lambda: steward_ask.owner_class(q, "", "", 0.0))
for lang in ("tr", "en"):
    views = [V("alfa", True, tmux=True, busy=False, blueprint="alfa", started_at=1.0, last_activity=1.0, last_assistant="STEWARD-NEXT: testi yaz")]
    projects = {"alfa": P("alfa"), "mkt": P("mkt")}
    qs = [Q("r1", "alfa", "hangi sıra?", created_at=NOW - 3600, routine=True), Q("r2", "alfa", "hangi model?", created_at=NOW - 60, routine=True),
          Q("o1", "mkt", "Hangi ad olsun?", created_at=NOW - 90000, options=["x", "y"]), Q("d1", "yok", "bitti mi?", status="answered", answer="evet", answered_at=NOW - 30)]
    add("review_items", {"views": views, "projects": projects, "cfg": C(ask_gate="shadow", lang=lang), "now": NOW, "questions": qs, "ideas": [], "skip": set(),
                         "last_directive_at": {}, "reviewed_at": {}, "world": None, "skip_seen": {}, "sigs_out": None, "state": {"ask_seen": {"o1": {"n": 2, "at": 0}}}})
for raw in ["²", "①", "³", "ß", "ﬁ", "ŉ", "ǰ", "²²", "٢", "ª", "b", "C"]:
    add("resolve_answer", {"q": Q("q", "p", "t", options=["bir", "iki", "üç"]), "raw": raw})
for raw in ["simdi verecegim", "Simdi verecegim.", "kararlari simdi verecegim", "kararlari sonra verecegim", "SİMDİ VERECEGİM", "sımdı verecegım", "simdi verecegim: b", "verecegim", "sonra verecegim"]:
    add("is_defer_answer", {"raw": raw})
# aynı projeye iki cevap: tek `start`, yuva öteki projeye kalır (uzops R-13)
for phase in ("planned", "paused", "done"):
    projects = {"alfa": P("alfa", phase=phase), "beta": P("beta", phase="planned")}
    qs = [Q(i, p, "hangi ad?", status="answered", answer="evet, aç", answered_at=NOW - 30, created_at=NOW - 90) for i, p in (("q1", "alfa"), ("q2", "alfa"), ("q3", "beta"))]
    cfg = C(enabled=True, max_active=2, max_starts_per_tick=2)
    add("plan_tick", {"views": [], "projects": projects, "state": {}, "cfg": cfg, "now": NOW, "questions": qs, "ideas": [], "world": None})
# diyalog yüzünden ertelenen done/paused kapanışı (2b): işaretle kayıt, eskimeme, cevap sessizliği, alt ajan, el oturumu
_DONE = "STEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt"
for phase in ("planned", "paused", "done"):
    views = [V("alfa", True, tmux=True, busy=False, question_open=True, last_assistant=_DONE)]
    add("plan_tick", {"views": views, "projects": {"alfa": P("alfa", phase=phase)}, "state": {}, "cfg": C(enabled=True), "now": NOW, "questions": [], "ideas": [], "world": None})
_MANUAL = sw.World(sid="default", owners={"alfa": "default"}, brains={"degnekci": "default"})
for phase in ("planned", "paused", "done"):
    for kw in ({}, {"question_open": True}, {"owner_input_at": NOW - 60}, {"owner_input_at": NOW - 3600}, {"subagent_active": True}, {"busy": True}):
        for req_at in (NOW - 60, NOW - 30000):
            for world in (None, _MANUAL):
                views = [V("alfa", True, **dict({"tmux": True, "busy": False}, **kw))]
                add("plan_tick", {"views": views, "projects": {"alfa": P("alfa", phase=phase)}, "state": {"pause_close": {"alfa": req_at}},
                                  "cfg": C(enabled=True), "now": NOW, "questions": [], "ideas": [], "world": world})
# 28 Kas (uzakgoz, sesotappr): oturum açıkken süpürme sorusunun "Aç" cevabı fazı planned'a çeker; tut cevabı ve başka soru çekmez
for phase in ("planned", "paused", "done"):
    for text in (sw.paused_sweep_text("alfa", 6), sw.paused_sweep_text("alfa", 6) + "\n", "Commit edeyim mi?"):
        for ans in ("1) Aç", "2) Paused kalsın", "evet", "Aç, başlamasın"):
            views = [V("alfa", True, tmux=True, busy=False)]
            qs = [Q("q1", "alfa", text, status="answered", answer=ans, answered_at=NOW - 30, created_at=NOW - 90)]
            add("plan_tick", {"views": views, "projects": {"alfa": P("alfa", phase=phase)}, "state": {}, "cfg": C(enabled=True), "now": NOW,
                              "questions": qs, "ideas": [], "world": None})
# 28 Kas: cevap TBD başlık bölümüne (soru kimliği, `## #N`/`### N)`), bağlanamazsa ayrı bölüme; son başlığın altına düşmesin
_TBD = ("# TBD\n\n## #442 (28 Kas) SORU: kabuk?\nSoru kimliği: q442 (açık).\nmetin\n\n## #429 bütçe\nTBD#441 anılır\n\n### 430) alt\n\n"
        "## #441 codex\nmetin\n\n- Sahip cevabı (x) [qold]: eski\n")
for text in (_TBD, _TBD + "\n" + sw.TBD_UNLINKED_ANSWERS_HEADING + "\n- Sahip cevabı (x) [qu]: u\n\n## #443 yeni\n", "- [ ] x\n", "#yok\n", "", "   ## #5 girintili\n"):
    for qid, q_text in (("q1", "Disk dolu?"), ("q442", "kabuk?"), ("q1", "TBD#441 için?"), ("q1", "TBD #430 ve TBD#429"), ("q1", "TBD#4 ?"), ("", "TBD#5"), ("q1", "TBD#٤٤١")):
        add("tbd_insert_answer", {"text": text, "qid": qid, "q_text": q_text, "answer": "a  b", "date": "2026-11-28"})
    lines = text.split("\n")
    for h in [i for i, ln in enumerate(lines) if sw._TBD_HEAD_RE.match(ln)]:
        add("_tbd_section_end", {"lines": lines, "h": h})
sw.save_questions([])
for t in ["Kapak rengi ne olsun?", "Dergi hangisi seçilsin?", "Sunum tarihi ne zaman?", sw._HELD_ANSWER_PREFIX + " pr projesi done/paused, cevap (q9) oturum açmadı.", "Yazar sırası nasıl olacak?"]:
    a = {"project": "p", "text": t, "source": "motor", "options": None, "routine": False, "detail": ""}
    stateful("add_question_ex", a, lambda: sw.add_question_ex(**a))
for fn, qid in [("mark_notified", "yok"), ("mark_delivered", "yok"), ("mark_notified", sw.load_questions()[0].id)]:
    stateful(fn, {"question_id": qid}, lambda: getattr(sw, fn)(qid))
sw.hosts_mod.get_host = lambda h: None
for field, bad in itertools.product(("goal", "model", "effort", "last_directive"), (5, ["x"])):
    sw.save_projects({"pr": P("pr", created_at=1.0)})
    before = enc(sw.load_projects())
    fields = {"priority": 1, field: bad}
    try:
        ret = enc(sw.upsert_project("pr", **fields))
    except (TypeError, ValueError) as e:
        ret = {"__error__": type(e).__name__, "msg": str(e)}
    args = {"name": "pr", "force": False, "fields": fields, "projects": before, "sid": "default", "reviewer": False, "host_known": True,
            "owner_elsewhere": None, "index": None, "running_given": False, "running": None}
    OUT.setdefault("upsert_project", []).append(json.dumps({"args": args, "ret": ret, "now": NOW,
        "after": {"projects": enc(sw.load_projects()), "cleared": False, "auto_label_via": None}}, ensure_ascii=False, separators=(",", ":")))

# TBD#387/1: olumsuzlanmış açma isteği (rastgele üretici KULLANILMAZ: diğer girdiler kaymasın)
V3871 = ["Başlamasın", "BAŞLAMASIN", "Baslamasin", "başlama", "Başlama.", "başlatma", "başlatmayın", "başlamayın", "başlamayalım",
         "Başlatılmasın", "başlanmasın", "başlamamalı", "başlamıyoruz", "başlamasa", "henüz başlamasın", "2) Başlamasın", "Evet, başlamasın",
         "ok, başlatma", "Başlama, evet diyene dek", "devam etme", "Devam etmesin", "devam etmeyelim", "devam edilmesin", "devam ettirme",
         "bu proje devam etmesin", "start etme", "start verme", "don't start", "Don’t start it yet", "do not start", "never restart",
         "please do not open or start", "DO NOT START", "başlamak için aç", "başlamalı", "devam etmeli", "Aç, eski oturuma devam etme",
         "Başla ama deploy'a devam etme", "Sonnet ile aç, eski kuyruğu başlatma", "(başlama)", "**tamam** başlama", "başlamasın\u0301"]
for t in V3871:
    add("is_open_answer", {"text": t})

# TBD#442 (a): yalnız kabuk/Monitor 30 dk'dan uzun açık (`shell_only_stale`) yönerge/dürtü/teslimi engellemez; ayrı üreteç (diğer girdiler kaymasın)
for sa in (False, True):
    for su in (False, True):
        for so in (False, True):
            add("bg_blocks_message", {"v": V("a", True, subagent_active=sa, subagent_unknown=su, shell_only_stale=so)})
r442 = random.Random(442)
for _ in range(300):
    so, sa, su = r442.random() < 0.6, r442.random() < 0.7, r442.random() < 0.15
    mine, taken = [V("a", True, busy=r442.choice([False, False, None, True]), subagent_active=sa, subagent_unknown=su, shell_only_stale=so)], set()
    add("plan_deliveries", {"entries": [["a", "nudge"]], "mine": mine, "taken": taken, "state": {}, "now": NOW, "limit": 1},
        call=lambda: sw.plan_deliveries([("a", lambda v: sw.Action("nudge", v.name, "a"))], mine, taken, {}, NOW, 1))
    cli = r442.choice(["claude", "ucli"])
    since = NOW - r442.choice([700, 3600])
    v = V("a", True, cli=cli, tmux=True, busy=False, idle_since=since, last_activity=since, last_assistant="STEWARD-NEXT: testi yaz",
          subagent_active=sa, subagent_unknown=su, shell_only_stale=so, cache_ttl="")
    projects = {"a": P("a", phase="planned")}
    state = {}
    cfg = C(claude_idle="act", claude_idle_nudge_secs=600, ucli_idle="act", ucli_idle_nudge_secs=600, ucli_idle_nudge_secs_1h=600, mode="act", brain_name="degnekci")
    views = [v]
    args = {"views": views, "projects": projects, "state": state, "cfg": cfg, "now": NOW, "planned": [], "world": None}
    if cli == "claude":
        add_cb("plan_claude_idle", args, lambda c: sw.plan_claude_idle(views, projects, state, cfg, NOW, [], None, c.get("open_work"), c.get("owner_todo"), c.get("todo_sha"), c.get("oldest_open"), c.get("has_question")), {"open_work": {"a": 2}})
    else:
        add_cb("plan_ucli_idle", args, lambda c: sw.plan_ucli_idle(views, projects, state, cfg, NOW, [], None, c["open_work"]), {"open_work": {"a": 2}})

# L2 bayat izleme (28 Kas, hc): manual_hold_step; ayrı üreteç
rmh = random.Random(4428)
MH = sw.MANUAL_HOLD_ASK_SECONDS
for i in range(600):
    owned = {p: rmh.choice(["", p, p + "20261120", "zz"]) for p in ("hc", "x") if rmh.random() < 0.85}
    w = sw.world_for("default", sw.build_ownership_index({"default": ["hc", "x"]}), "degnekci", owned=owned)
    pool = ["hc", "hc20261123", "hc20261124", "x", "x20261101", "hcr", "degnekci", "zz"]
    views = [V(n, rmh.random() < 0.85, blueprint=rmh.choice([None, None, "hc", "x", ""])) for n in rmh.sample(pool, rmh.randint(0, 4))]
    projects = {p: P(p, phase=rmh.choice(["planned", "planned", "planning", "paused", "done"])) for p in ("hc", "x") if rmh.random() < 0.9}
    hold = {}
    for p in ("hc", "x", "eski"):
        if rmh.random() < 0.5:
            hold[p] = rmh.choice([{"since": NOW - rmh.choice([0, MH - 1, MH, 3 * MH]), "session": rmh.choice(pool), "asked": rmh.choice([False, True, 1, 0, None])},
                                  {"since": NOW - MH, "session": rmh.choice(pool)}, {"session": rmh.choice(pool)}, "bozuk", [1],
                                  {"since": rmh.choice(["x", "12", None, 0, [1]]), "session": rmh.choice(pool)}])
    questions = []
    for j in range(rmh.randint(0, 3)):
        st = rmh.choice(["answered", "answered", "open"])
        questions.append(Q(f"q{j}", rmh.choice(["hc", "x", "yok"]), "soru", status=st, answer=rmh.choice(["evet", "Evet, izlensin", "hayır", "hayır beklesin", "aç", "belki", ""]) if st == "answered" else "",
                           delivered_at=rmh.choice([0.0, 0.0, NOW - 5]), source=rmh.choice([sw.OWNED_ADOPT_SOURCE, sw.OWNED_ADOPT_SOURCE, "hc", "brain"])))
    add("manual_hold_step", {"hold": hold, "views": views, "world": w, "projects": projects, "questions": questions, "now": NOW, "lang": rmh.choice(["tr", "en"])})
for i in range(300):     # yönlendirilmiş: hc kayıtlı, elle açılan tek oturum çalışıyor
    w = sw.world_for("default", sw.build_ownership_index({"default": ["hc", "x"]}), "degnekci", owned={"hc": "hc", "x": "x"})
    views = [V("hc20261123", True, blueprint=rmh.choice(["hc", None]))] + ([V("hc", rmh.random() < 0.5)] if rmh.random() < 0.2 else [])
    projects = {"hc": P("hc", phase=rmh.choice(["planned", "planned", "planned", "paused"])), "x": P("x")}
    hold = {"hc": rmh.choice([{"since": NOW - rmh.choice([10, MH - 1, MH, 5 * MH]), "session": "hc20261123", "asked": rmh.choice([False, True])},
                              {"since": rmh.choice(["x", "12", [1], None, 0, NOW - MH]), "session": "hc20261123"},
                              {"since": NOW - MH, "session": "baska"}])} if rmh.random() < 0.85 else {}
    questions = [Q("q1", "hc", "soru", status="answered", answer=rmh.choice(["evet", "hayır", "evet ama sonra", "aç", "2) beklesin", "izle"]),
                   source=sw.OWNED_ADOPT_SOURCE)] if rmh.random() < 0.5 else []
    add("manual_hold_step", {"hold": hold, "views": views, "world": w, "projects": projects, "questions": questions, "now": NOW, "lang": rmh.choice(["tr", "en"])})

# TBD#442 küçük uç (28 Kas, copsdev): explain_idle arka plan işini (`bg_running`) söylesin, eski yalnız kabuğu `shell_only_stale` ile işaretlesin; ayrı üreteç
rex = random.Random(4429)
for i in range(400):
    so, sa, su = rex.random() < 0.5, rex.random() < 0.6, rex.random() < 0.2
    since = NOW - rex.choice([60, 700, 3600])
    v = V("a", True, cli=rex.choice(["claude", "claude", "ucli"]), busy=rex.choice([False, False, None, True]), last_activity=since,
          last_assistant=rex.choice(["", "STEWARD-NEXT: testi yaz", "STEWARD-ASK: hangisi?", "bitti STEWARD-DONE"]),
          subagent_active=sa, subagent_unknown=su, shell_only_stale=so)
    projects = {"a": P("a", phase="planned")}
    views, state = [v], {}
    cfg = C(claude_idle=rex.choice(["act", "dry", "off"]), claude_idle_nudge_secs=600, lang=rex.choice(["tr", "en"]))
    acts = [sw.Action("idle_nudge", "a", "a", payload={"next": "x"})] if rex.random() < 0.2 else []
    n_open = rex.choice([0, 2])
    add_cb("explain_idle", {"proj": projects["a"], "views": views, "projects": projects, "state": state, "cfg": cfg, "now": NOW, "questions": [], "actions": acts, "world": None},
           lambda c: sw.explain_idle(projects["a"], views, projects, state, cfg, NOW, [], acts, None, c["open_work"]), {"open_work": {"a": n_open}})

dst = os.path.join(env.CRATE, "fixtures", "hand")
os.makedirs(dst, exist_ok=True)
for old in glob.glob(os.path.join(dst, "*.jsonl.gz")):
    os.remove(old)
for name, lines in sorted(OUT.items()):
    with open(os.path.join(dst, name + ".jsonl.gz"), "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as f:
        f.write("".join(x + "\n" for x in lines).encode())
print("işlev:", len(OUT), "kayıt:", sum(map(len, OUT.values())))
