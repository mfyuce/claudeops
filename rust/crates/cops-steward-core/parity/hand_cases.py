#!/usr/bin/env python3
"""Kayıtlı vektörlerin kapsamadığı dallar/kenar durumları (gruplar C ve D): girdiler burada elle yazılır, beklenen değer
Python işlevi çalıştırılarak alınır. Çıktı `fixtures/hand/<işlev>.jsonl.gz` (aynı satır biçimi; `harness::cases` ikisini de
oynatır). Kullanım: `python3 -I parity/hand_cases.py`."""
import dataclasses, functools, glob, gzip, hashlib, itertools, json, os, random, sys

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

dst = os.path.join(env.CRATE, "fixtures", "hand")
os.makedirs(dst, exist_ok=True)
for old in glob.glob(os.path.join(dst, "*.jsonl.gz")):
    os.remove(old)
for name, lines in sorted(OUT.items()):
    with open(os.path.join(dst, name + ".jsonl.gz"), "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as f:
        f.write("".join(x + "\n" for x in lines).encode())
print("işlev:", len(OUT), "kayıt:", sum(map(len, OUT.values())))
