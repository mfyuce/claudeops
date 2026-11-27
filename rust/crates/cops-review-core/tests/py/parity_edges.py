"""Ek kenar durumları: boş/bozuk/Unicode/eksik alan. Karşılaştırmayı `parity_hook` yapar; burada yalnız çağrılır.
`COPS_REV_PARITY_DATA` = canlı reviewer deposunun KOPYASI (findings.json, review_history.json, review_pool.json, reviews/):
verilirse gerçek veri de iki yönlü okunup yazılır."""
import copy
import json
import os
import random
import shutil
import tempfile
import time
import unittest

import parity_hook as hook
from claudeops import review as rv
from claudeops import steward as sw

NOW = 1_800_000_000.0

TEXTS = [
    "", " ", "\n", "abc", None, "İŞLEM ışık", "ISLEM işlem Straße ẞ ﬁ K ſ", "a\u2028b\x1cc\x0bd\u0085e\r\nf\rg",
    "429", "x 4290", "HTTP 503 SERVICE UNAVAILABLE", "SERVİCE UNAVAİLABLE", "rate-limit", "RATE LIMIT", "Retry-After: 12",
    "retry after=99999", "retry-after: ٤٥٠", "model_capacity_exhausted", "daily_token_limit_exceeded",
    "You have exceeded your monthly quota", "RESOURCE_EXHAUSTED (code 429): Individual quota reached. Resets in 107h49m47s.",
    "Resets in 0s", "resets in 99999d", "reset in 1d 2h 3m 4s", "RESETS İN 5H",
    "You've hit your usage limit. try again at Nov 20th, 2026 6:37 PM.", "try again at Foo 1st, 2026 1:00 AM",
    "try again at Feb 30, 2026 1:00 AM then try again at March 1 2027 12:05am",
    "try again at jan 1, 2027 0:00 AM", "try again at Dec 31st 2026 12:00 PM",
    "## R-1 | P2 | a.py:3 | başlık\ngövde\n```\n## R-2 | P1 | b | c\n~~~\n```\n## Üst\nx",
    "###   R-3|P1| [a.py:3](file:///x) |  T  \n\n   \n#### R-3 | P3 | y | z\n# kes\n## R-4 | P4 | y | z",
    "~~~\n## R-1 | P1 | a | b\n", "## R-١ | P1 | a | b\x1c", "## R-1 | P1 |  | b", "## R-1 | P1 | a | b | c |", "##R-1|P1|a|b",
    "BULGU YOK", "araç bütçesi tükendi", "ARAÇ ÇAĞRISI BÜTÇESİ (14 ÇAĞRI) TÜKENDİ", "İNCELEME TAMAMLANMADI",
    "inceleme durumu: tamamlanmadı", "tool-call budget was exhausted\n## R-1 | P1 | a | b", "## R-1 | P1 | a | b\n...",
    "## R-1 | P1 | a | b\naaa", "## R-1 | P1 | a | b\nok", "## R-1 | P1 | a | b\nßs", "tests/ denetlenmemiştir",
    "STEWARD-REVIEW-VERDICT: p:x:R-1 verified neden\n  STEWARD-REVIEW-VERDICT: p:x:R-1 refuted   yeni  \n",
    "> STEWARD-REVIEW-VERDICT: a verified x\n`STEWARD-REVIEW-VERDICT: b verified x`\n- STEWARD-REVIEW-VERDICT: c verified x",
    "```\nSTEWARD-REVIEW-VERDICT: d verified x\n```\nSTEWARD-REVIEW-VERDICT: e unclear <tek cümlelik gerekçe>",
    "STEWARD-REVIEW-VERDICT:f verified <a> b\nSTEWARD-REVIEW-VERDICT: g verified\nSTEWARD-REVIEW-VERDICT: h verifiedx",
    "STEWARD-REVIEW-VERDICT: i verified " + "ğ" * 600,
    "postgres://u:parola123@host/db ve parola123 tekrar", "HTTP://a:b@c@d@host x", "x://u:abc@h", "x://u:ab@h",
    "x://u:abcd@@h", "x://u:abcd@/ x://u:abcd@h.x", "redis://:pw@h", "a://u:pass w@h", "mysql://İ:şifre1@h şifre1 aşifre1",
    "db://u:abcde@h /abcde abcde. (abcde) abcde", "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
    "sk-proj-" + "A" * 30, "ghp_" + "a" * 36, "hf_" + "b" * 30, "AKIA" + "A" * 16, "xoxb-" + "1" * 12,
    "Authorization: Bearer abcdefghijklmnop.qrst", "BEARER  ABCDEFGHİJKLMNOPQR", "AIza" + "c" * 35, "glpat-" + "d" * 20,
    "eyJabcdefgh.abcdefgh.abcdefgh", "tk_" + "e" * 20, 'db_password = "supersecret1"', "API_KEY:'abcdefgh12'",
    '{\\"api_key\\": \\"abcdefghij\\"}', "token=short", "APİ_KEY=abcdefghij", "AUTHORİZATİON: abcdefghij",
    "--password hunter22 --token=abcd1234 --APİ-KEY zzzzzz", "secrets_file_path: /etc/very/long",
    "\x1b[0m Propagating selected model override to server label=\"Gemini 4 Argon\"",
    "Propagating selected model override label=a\nPropagating selected model override x label='gemini-3-pro-high' y",
    "- [ ] (review a) x\n  - [ ] (review b)\n- [x] (review c)\n\x1c- [ ] (review d)", "quota",
    "x" * 700, "## R- uzun " + "y" * 10, json.dumps({"partial_turn": "RESOURCE_EXHAUSTED", "error": "boom", "n": 1.5}),
    "[1, 2]", "{bozuk", '{"a": NaN, "answer": "q"}', "Gemini Models\tWeekly Limit\t40%\t2026-11-22T10:00:00Z",
    "Claude and GPT models\tFive Hour Limit\t0%\t2026-11-22T1:2:3Z\nGemini 4 Argon\tWeekly\t0%%\t2026-13-01T00:00:00Z\n"
    "Gemini Models\tFive hour\tx%\t2026-11-22T10:00:00Z\nOther\tWeekly\t1%\t2026-11-22T10:00:00Z\n"
    "Gemini Models\t5 hour\t10\t2026-02-30T10:00:00Z\ngemini\tweekly\t7%\t2026-11-22t10:00:60z",
]

SPECS = ["", "off", "OFF ", "agy=5,evren=1,codex=1,copilot=0", "agy = 2 , nope=3, evren=x", "agy=-1", "agy=١", "=3",
         "agy", "evren=0,evren=4", "a@b@c", " m @ e ", "@x", "ls, grep ,rm -rf,x;y", ",,", "../../etc", "-a-", "..", "a  b//c",
         "İ/ş", "a---b", "agy/x,evren/y,agy/x", None]


class TestEdges(unittest.TestCase):
    def test_claude_catalog_documents(self):
        """Dolu, bozuk ve tipi yanlış `claude_models` belgesi (yol parite koşusunun geçici `CLAUDEOPS_DIR`i altında)."""
        from claudeops.paths import CLAUDE_MODELS_JSON as path
        self.assertTrue(path.startswith(os.environ["CLAUDEOPS_DIR"] + os.sep))
        self.assertFalse(os.path.exists(path))
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        full = '{"models": {"claude-fable-5-2": "enabled", "claude-opus-5-5": "disabled", "n": 3, "b": true, "z": null}}'
        for text in (full, '{"models": {}}', '{"models": []}', '{"models": ["a"]}', '{"models": "x"}', '{"models": 0}',
                     "{}", "[]", '"x"', "null", "bozuk{"):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            got = rv.claude_catalog()
            if text == full:
                self.assertEqual(got["claude-fable-5-2"], "enabled")

    def test_text_functions(self):
        for t in TEXTS:
            rv.is_capacity_error(t, "z")
            rv.capacity_retry_seconds(None, t)
            rv.is_daily_limit(t)
            rv.is_quota_exhausted(t)
            rv.is_usage_limit(t)
            rv.reset_at(t)
            rv.reset_seconds(t)
            rv.quota_block_until(NOW, t)
            rv.quota_block_until(1_700_000_000.0, t)
            rv.block_until_for_limit(NOW, t)
            rv.is_short_banner(t)
            for flag in (False, True):
                rv.limit_scan_texts(t, t, "j", flag)
                rv.limit_scan_texts(t, "kısa", t, flag)
            rv.parse_findings(t)
            rv.scan_verdicts(t)
            rv.report_incomplete(t)
            rv.report_bodyless(t)
            rv.open_review_lines(t or "")
            rv.parse_agy_usage(t)
            rv.dsn_passwords(t)
            rv.redact_secrets(t)
            rv.redact_secrets(t, ["parola123", "abcde", "ab", "", "kod"])
            rv.agy_label_ok(t, "Gemini 4 Argon")
            rv.agy_label_ok(t, "gemini-3-pro-high")
            rv.text_hash(t)
            rv.where_text({"where": t})
            rv.where_relpath({"where": t})
            rv.has_quoted_names({"title": t})
            rv.is_decision({"title": t, "body": "x"})
            rv.reviewer_slug_of(t)
            rv.anthropic_price(t)
            hook.check_collapse(t)

    def test_fuzz_redact_and_findings(self):
        rnd = random.Random(7)
        atoms = ["a", "B", "1", " ", "\n", ":", "/", "@", '"', "'", "\\", "=", "-", "_", ".", "|", "#", "`", "~", "İ", "ı",
                 "ş", "://", "R-1", "P1", "## ", "token", "pass", "api", "secret", "sk-", "Bearer ", "x://u:", "@h",
                 "--password ", "[", "]", "(", ")", "\x1c", "\u2028", "\r", "```", "~~~", "<", ">",
                 "STEWARD-REVIEW-VERDICT:", " verified ", "abcdefgh"]
        for _ in range(4000):
            t = "".join(rnd.choice(atoms) for _ in range(rnd.randint(0, 30)))
            rv.redact_secrets(t)
            rv.redact_secrets(t, ["abcdefgh", "token"])
            rv.dsn_passwords(t)
            rv.parse_findings("## R-1 | P1 | " + t)
            rv.parse_findings(t)
            rv.scan_verdicts("STEWARD-REVIEW-VERDICT: " + t)
            rv.finding_key("p", t, t)
            rv.slug_model(t)
            rv.where_text({"where": t})
            rv.where_relpath({"where": t})
            rv.report_bodyless("## R-1 | P1 | a | b\n" + t)

    def test_unicode_finding_key(self):
        for cp in list(range(0, 0x3100)) + list(range(0xFB00, 0xFFF0, 3)) + list(range(0x1D400, 0x1D800, 7)):
            c = chr(cp)
            rv.finding_key("p", "a.py:1", "x" + c + "y " + c)
        for w in (None, "", "`a.py`:3", "./a.py#L1", "file://x/y:2", "[a.py:3](file:///z#L1)", " ` a ` : 1", "[x](y"):
            for t in (None, "", "İşlem", "ISLEM", "  --  ", 5):
                rv.finding_key("proj", w, t)

    def test_specs_and_targets(self):
        for s in SPECS:
            rv.parse_slots(s)
            rv.slug_model(s)
            rv.split_spec(s)
            rv.agy_allow_list(s)
            rv.toggle_excluded(s, "agy/x", True)
            rv.toggle_excluded(s, "agy/x", False)
            rv.window_seconds(s)
        for h in (0, -1, 1, 1.5, "2", " 3 ", "1_000", "inf", "nan", None, [], True, "x"):
            rv.window_seconds(h)
        cat = {"claude-fable-5-2": "enabled", "claude-fable-5-1": "disabled", "claude-a-fable": "enabled", "m": "enabled"}
        for auth in ("api", "subscription", " Subscription ", ""):
            for models in ("", "m@low, m@high,claude-fable-5-1@low,@x"):
                cfg = sw.Config()
                cfg.review_claude_auth, cfg.review_claude_models = auth, models
                cfg.review_agy_models, cfg.review_excluded = "g1,g2,yok", "agy/g2,codex/c"
                cfg.review_codex_models, cfg.review_copilot_models = "c, c@high", "p"
                cfg.review_anthropic_models, cfg.review_evren_models = "claude-haiku-5-5@low", ""
                rv.claude_specs(cfg, cat)
                rv.claude_is_subscription(cfg)
                rv.excluded_keys(cfg)
                for t in rv.targets_from_config(cfg, ["g1", "g2", "g1"], ["x/y", "x-y"], ) if False else rv.targets_from_config(cfg, ["g1", "g2", "g1"], ["x/y", "x-y"]):
                    hook.check_target(t)
                    rv.pair_key("p|q", t)
                    rv.model_family(t)
                    for eff in ("", "x y"):
                        rv.effort_for(cfg, t.mode, t)
                        rv.review_path("/r", "p/../q", t, "20261126010203", eff, "")
                        rv.review_path("/r/", "p", t, NOW, eff, "dry")
                for m in rv.MODES:
                    rv.effort_for(cfg, m, None)
                    rv.max_attempts(m)
        rv.claude_catalog()
        for ts in (None, "", "20261126010203", "2026", NOW, 0, "abc", 1e30, float("nan"), "1800000000"):
            rv.review_title("p", "agy", "m", ts)
        for m in ("Gemini 4 Argon", "gemini-3", "claude-x", "GPT-oss", "other", "", None):
            rv.agy_pool(m)
        for model in ("org/qwen3.8", "glm-5.3", "3x", "", "A/B/cd9"):
            rv.model_family(rv.ReviewTarget("evren", model, "s"))
        hook.check_target(rv.ReviewTarget("agy", "m", "s", "a b", "dry"))

    def test_paths(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        md = os.path.join(d, "20261126010203.md")
        for n in ("20261126010203.f01.md", "20261126010203.f12.md", "20261126010203.f1.md", "20261126010203.f123.md",
                  "other.f01.md", "20261126010203.model.f02.md"):
            open(os.path.join(d, n), "w").close()
        os.symlink(md, os.path.join(d, "20261126010203.f03.md"))
        for p in (md, md[:-3], os.path.join(d, "yok", "a.md"), "a.md", ""):
            rv.finding_paths(p)
            rv.draft_path(p)
            rv.partial_path(p)
            rv.error_path(p)
            for n in (0, 1, 12, 123, -1):
                rv.finding_path(p, n)
            for lang in ("tr", "en"):
                rv.draft_prompt_suffix(rv.draft_path(p), lang)
                rv.draft_prompt_suffix(p, lang)
        for lang in ("tr", "en", "de"):
            rv.build_review_prompt("p{x}", "/c w", lang)
            rv.build_review_prompt("p", "/c", lang, "dry")
            with self.assertRaises(ValueError):
                rv.build_review_prompt("p", "/c", lang, "yok")

    def test_lens_registry(self):
        saved = (rv.LENSES, dict(rv._LENS_TEXT), dict(rv._LENS_FORMAT_EXTRA))
        try:
            rv.register_lens("sec", "güvenlik \\1 \\g<0>", "security\n", "ek", "")
            rv.register_lens("plain", "t", "e")
            rv.register_lens("nl\n", "t", "e")
            for bad in ("", "Sec", "sec", "dry", "a" * 25, "1a", "a b"):
                with self.assertRaises(ValueError):
                    rv.register_lens(bad, "t", "e")
            with self.assertRaises(ValueError):
                rv.register_lens("empty", "  ", "e")
            rv.lenses()
            for lg in ("tr", "en"):
                for n in ("sec", "plain", "dry"):
                    rv.build_review_prompt("p", "/c", lg, n)
        finally:
            rv.LENSES = saved[0]
            rv._LENS_TEXT.clear()
            rv._LENS_TEXT.update(saved[1])
            rv._LENS_FORMAT_EXTRA.clear()
            rv._LENS_FORMAT_EXTRA.update(saved[2])

    def test_planner_random(self):
        rnd = random.Random(11)
        targets = [rv.ReviewTarget("agy", "gemini-3", "gemini-3"), rv.ReviewTarget("agy", "claude-x", "claude-x"),
                   rv.ReviewTarget("agy", "gpt-oss", "gpt-oss", "high"), rv.ReviewTarget("evren", "glm-5", "glm-5"),
                   rv.ReviewTarget("evren", "qwen3", "qwen3"), rv.ReviewTarget("codex", "gpt-6", "gpt-6", "", "dry")]
        statuses = ["running", "done", "partial", "error", "model_fallback", "limit", None, "?"]
        errors = ["", "cancelled", "spawn: x", "yeniden başlatma", "capacity: y", "timeout", None, 5]
        vals = [None, 0, NOW - 10, NOW - 86400 * 20, NOW + 100, "x", "12", True, [], {}]
        for _ in range(2500):
            pool = {"projects": {}}
            for n in ("a", "b", "c", "ç"):
                if rnd.random() < 0.8:
                    pool["projects"][n] = rnd.choice([
                        {"enabled": True}, {"enabled": True, "focus": True}, {"enabled": False}, {"enabled": 1, "removed_at": 5},
                        {"enabled": True, "removed_at": None, "source": "auto"}, {"source": "auto", "removed_at": 3},
                        {"source": "manual"}, "bozuk", {}])
            pairs, blocks = {}, {}
            for n in ("a", "b", "c", "ç"):
                for t in targets:
                    if rnd.random() < 0.5:
                        rec = {"status": rnd.choice(statuses), "started_at": rnd.choice(vals), "finished_at": rnd.choice(vals),
                               "attempts": rnd.choice([0, 1, 3, 7, "2", None, "x"]), "error": rnd.choice(errors),
                               "retry_at": rnd.choice(vals), "head": rnd.choice(["", "h1", None])}
                        pairs[rv.pair_key(n, t)] = rec if rnd.random() < 0.95 else "bozuk"
            for k in ("agy", "evren", "agy/gemini-3", "agy/claude-x", "agy/gpt-oss@high", "evren/glm-5", "copilot"):
                if rnd.random() < 0.15:
                    blocks[k] = rnd.choice([{"until": NOW + 50}, {"until": NOW + 50, "set_at": NOW - 100}, {"until": 0}, {},
                                            "x", {"until": "bad"} if rnd.random() < 0.2 else {"until": str(NOW + 9)}])
            h = {"pairs": pairs, "blocks": blocks, "runs": []}
            heads = {"a": "h1", "b": "h2", "c": ""}
            rec = rnd.choice(list(pairs.values()) or [None])
            rv.counts_as_attempt(rec)
            try:
                rv.blocked_modes(h, NOW)
                rv.next_review(pool, h, targets, NOW, busy_projects=rnd.sample(["a", "b"], rnd.randint(0, 1)),
                               head_of=rnd.choice([None, heads.get]), window=rnd.choice([86400.0, rv.WINDOW_SECONDS]),
                               skip_pairs=[rv.pair_key("a", targets[0])] if rnd.random() < 0.3 else [])
            except ValueError:
                pass
            rv.project_complete(h, "a", targets[:2], NOW)
            rv.pool_enabled(pool)
            rv.pool_focus(pool)
            rv.pool_sync(pool, rnd.sample(["a", "b", "d", "", "ç"], rnd.randint(0, 4)), NOW)
            rv.backlogged_projects(pool, {"a": 5, "b": 60, "c": "70"}.get, rnd.choice([0, -1, 50]))
        for bad in (None, [], {}, {"projects": []}):
            rv.pool_enabled(bad)
            rv.pool_focus(bad)
            rv.pool_sync(bad, ["x"], NOW)
        rv.window_seconds(None)

    def test_blocks_agy_copilot(self):
        rnd = random.Random(3)
        for _ in range(600):
            usage = {}
            for pool in ("argon", "gemini", "claude_gpt"):
                if rnd.random() < 0.6:
                    usage[pool] = {k: (float(rnd.choice([0, 5])), NOW + rnd.choice([-5.0, 500.0, 9000.0]))
                                   for k in ("weekly", "five") if rnd.random() < 0.7}
                    rv.agy_pool_blocked_until(usage, pool, NOW)
            rv.agy_pool_blocked_until(usage, "yok", NOW)
            blocks = {k: rnd.choice([{"until": NOW + 500.0, "set_at": NOW - 5000}, {"until": NOW + 500.0, "set_at": NOW},
                                     {}, "x", {"until": NOW + 9000.0}])
                      for k in ("agy/gemini-3", "agy/claude-x~dry", "evren", "agy/other") if rnd.random() < 0.5}
            h = {"blocks": blocks, "pairs": {"p|agy/gemini-3": {"status": rnd.choice(["done", "limit"]),
                 "finished_at": NOW - rnd.choice([10, 100000])}, "q|agy/gemini-3@low": {"status": "done", "finished_at": NOW - 1}}}
            rv.blocked_modes(h, NOW)
            rv.reconcile_agy_blocks(copy.deepcopy(h), usage, ["agy/gemini-3", "codex/x", "agy/gpt-oss"], NOW)
            info = rnd.choice([None, (96.0, NOW + 1000, "d"), (50.0, NOW + 1000, "d"), (95.5, NOW + 1e6, "x · y")])
            ch = {"blocks": rnd.choice([{}, {"copilot": {"until": NOW + 5000.0, "reason": "monthly"}},
                                        {"copilot": {"until": NOW, "reason": "copilot usage_state: x"}}, {"copilot": {}}])}
            if rnd.random() < 0.5:
                del ch["blocks"]
            rv.reconcile_copilot_blocks(ch, info, rnd.choice([95.0, 0.0, 99.5]), NOW)
        entries = [
            [], None, [1, None], [{"label": "Plan (AI Credits)", "percent": "35%", "detail": "530 / 1,500 AIC · resets in 8 days"}],
            [{"label": "credit", "percent": None}], [{"label": "Plan", "percent": 12.5, "detail": "Reset in 2 hours 5 min"}],
            [{"label": "plan", "percent": " 7 ", "detail": "resets in soon"}], [{"label": "x", "percent": 1}],
            [{"label": "AI CREDİTS PLAN", "percent": "nan"}], [{"label": "Plan", "percent": 3, "detail": "RESETS İN 3 DAYS 4 H 2 MİNUTES"}],
            [{"label": "Gemini Models — Weekly Limit", "percent": 0, "detail": "Resets 2027-01-02T03:04:05Z"},
             {"label": "Claude and GPT models — Five Hour Limit", "percent": "55", "detail": "Resets 2027-01-02T03:04:05Z"}],
        ]
        for e in entries:
            rv.parse_copilot_entries(e, NOW)
            rv.parse_copilot_entries(e, NOW, NOW - 100)
            rv.parse_agy_entries(e)
        for t in (0.0, 86399.9, NOW, 1_798_761_599.0, -5.0):
            rv.next_utc_midnight(t)
            rv.next_utc_month_start(t)

    def test_history_functions(self):
        runs = [{"pair": "p|agy/m", "status": s, "at": NOW - d, "seconds": sec}
                for s in ("done", "partial", "error", "limit", "model_fallback", None)
                for d in (10, 8 * 86400) for sec in (None, 5, 2.55, -1, True, "3")]
        runs += [{"pair": "bozuk"}, "x", {}, {"pair": "q|evren/n", "status": "error", "at": NOW}] * 3
        for h in ({"runs": runs}, {"runs": None}, {}, None):
            rows = rv.model_health(h, NOW)
            rv.model_health(h, NOW, days=30, min_runs=1, max_rate=1.0)
            rv.duration_summary(h)
            rv.duration_summary(h, "p")
            for lang in ("tr", "en"):
                rv.health_digest(rv.model_health(h, NOW, min_runs=1, max_rate=0.9), ["agy/m"], 7, lang)
                rv.health_digest(rows, [], 2.5, lang)
        hs = {"pairs": {"p|claude/m": {"started_at": rv.R10_SUB_SINCE + 1}, "p|claude/m@low": {"started_at": rv.R10_SUB_SINCE + 1},
                        "p|claude/m-sub@low": {}, "q|claude/o": {"started_at": 5}, "claude/x": {}, "r|agy/z": {"started_at": 9e9},
                        "s|claude/k-sub": {"started_at": 9e9}, "t|claude/b": "x"}}
        rv.migrate_r10_sub(copy.deepcopy(hs))
        rv.migrate_r10_sub({"pairs": {}, rv.R10_MARK: True})
        rv.migrate_r10_sub({"pairs": {"p|claude/m": {"started_at": "x"}}})

    def test_flow_functions(self):
        base = {"project": "p", "state": "verify_sent", "review_file": "/r/p/claude/m-sub/low/1/1.md"}
        findings = {"a": dict(base), "b": dict(base, verify_baseline="h"), "c": dict(base, verdict_src="h"),
                    "d": dict(base, state="new"), "e": "x", "f": dict(base, project="q")}
        verdicts = [(k, "verified", "g" * 520) for k in findings] + [("a", "bad", ""), ("z", "refuted", "")]
        for verifier in ("", "m", "other"):
            rv.apply_verdicts(copy.deepcopy(findings), "p", verdicts, "h", "s", NOW, verifier)
            rv.apply_verdicts(copy.deepcopy(findings), "p", verdicts, "h2", "s", NOW, verifier)
        for sent in (None, 0, NOW - 10, NOW - 90000, "5"):
            for tries in (None, 0, 1, 2, 5, "1", 1.7):
                rv.requeue_stale_verify({"a": dict(base, verify_sent_at=sent, verify_tries=tries),
                                         "b": dict(base, verify_session="self"), "c": 4}, NOW)
        for bad in ({"verify_sent_at": "x"}, {"verify_tries": "1.5"}):
            rv.requeue_stale_verify({"a": dict(base, **bad)}, NOW)
        rows = [{"id": "p:1:R-1", "severity": "P1", "where": "a:1", "title": "  çok \n satır  " + "ş" * 300},
                {"id": 5, "severity": "", "where": None, "title": None}]
        for lang in ("tr", "en"):
            rv.build_verify_message(rows, lang)
            rv.build_self_verify_prompt(rows, lang)
            rv.build_verify_message([], lang)
            with self.assertRaises(KeyError):
                rv.build_verify_message([{}], lang)
        for p in ("", "a", "/x/p/agy/m/ts/ts.md", "agy/m", "agy/m/x", "C:\\r\\evren\\m-sub\\t.md", "codex"):
            rv.reviewer_slug_of(p)

    def test_export_functions(self):
        d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(d + "/repo/.git/worktrees/w")
        os.makedirs(d + "/combo/sub")
        os.makedirs(d + "/combo/plain")
        os.makedirs(d + "/other/.git")
        with open(d + "/combo/sub/.git", "w") as f:
            f.write(f"gitdir: {d}/repo/.git/worktrees/w\n")
        with open(d + "/other/a.py", "w") as f:
            f.write("def foo():\r\n    pass\n")
        with open(d + "/report.md", "w") as f:
            f.write("r")
        os.utime(d + "/report.md", (1000, 1000))
        os.symlink("/etc/hostname", d + "/other/link.py")
        wheres = ["a.py:1", "`a.py`:2", "other/a.py:3", "sub/x.py:1", "plain/x.py", "nope/x.py", "/etc/x.py", "../a.py",
                  "[a.py:3](file:///q)", "`[sub/x.py](y)`", "link.py", "", None, "noext:3", "combo/a.py"]
        titles = ["`foo` bozuk", "`bar.baz` ve `qux`", "alıntısız", "`pkg.foo`", None, "karar gerekli", "KARAR GEREKLİ",
                  "BELİRSİZ davranış", "Sahip karar vermeli", "undefined behavior", "Should it retry?", "tradeoff", "Seçenekler"]
        resolve = {"other": d + "/other", "sub": "", "plain": d + "/combo/plain"}.get
        for w in wheres:
            for cwd in (d + "/other", d + "/combo", d + "/repo", d + "/yok"):
                row = {"where": w, "title": "`foo` x", "review_file": d + "/report.md"}
                rv.export_root(row, "combo", cwd, lambda p: resolve(p) or "")
                rv.export_root(row, "other", cwd, lambda p: resolve(p) or "")
                rv.row_in_repo(row, d + "/repo", cwd)
                rv.row_in_repo(row, "", cwd)
                rv.row_in_repo(row, cwd + "/.", cwd)
                rv.stale_reason(row, cwd)
                rv.changed_after_review(row, cwd)
        for t in titles:
            rv.is_decision({"title": t, "body": "ğ" * 590 + " karar"})
            rv.is_decision({"title": "x", "body": t})
            for src in (None, "", "def foo(): qux", "baz"):
                rv.stale_reason_text({"title": t}, src)
            rv.stale_reason({"where": "a.py:1", "title": t}, d + "/other")
        rv.changed_after_review({"where": "a.py", "review_file": ""}, d + "/other")
        rv.changed_after_review({"where": "a.py", "review_file": d + "/yok"}, d + "/other")
        for p in (d + "/combo/sub", d + "/repo", d + "/yok", d + "/combo/plain"):
            rv._worktree_main(p)
        rows = [{"id": "p:1", "severity": "P1", "where": "a:1", "title": "t\n  u", "review_file": d + "/reviews/p/a/m/t/t.md"},
                {"id": "p:2", "review_file": "/başka/yer/a/b/c/d/e.md/", "note": "not"},
                {"id": "p:3", "review_file": "göreli.md", "severity": None, "note": ""},
                {"id": "p:4", "review_file": d + "/reviews", "title": 5}]
        for root in (d + "/reviews", d + "/reviews/", ""):
            rv.export_lines(rows, root)
            for text in ("", "# T\n\n", "x (review p:1) y", "## Review bulguları (a)\n- eski\n\n\n",
                         "## Review bulguları (a)\n## Başka\n", "a\r\n## Review bulguları\r\n"):
                rv.appended_export(text, rows, root, "2026-11-26")
                rv.appended_export(text, [], root, "s")
        with self.assertRaises(KeyError):
            rv.export_lines([{}], "")

    def test_git_changed_after_review(self):
        """Gerçek git deposu: commit zamanı mtime'ı ezer; yol harfi harfine (`--literal-pathspecs`): `[a].py` `a.py`ye uymaz."""
        import subprocess
        d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        g = d + "/g"
        os.makedirs(g)

        def git(*a, when=None):
            env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
            if when is not None:
                env.update(GIT_AUTHOR_DATE=f"@{when} +0000", GIT_COMMITTER_DATE=f"@{when} +0000")
            subprocess.run(["git", "-C", g, "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True,
                           capture_output=True, env=env, timeout=30)

        for n in ("a.py", "[a].py", "b.py", "c.py", "d e.py"):
            with open(os.path.join(g, n), "w") as f:
                f.write("x")
        git("init", "-q")
        git("add", "--", "a.py", "d e.py")
        git("commit", "-qm", "ileri", when=2_000_000_000)
        git("add", "b.py")
        git("commit", "-qm", "eski", when=1000)
        rep = d + "/r.md"
        with open(rep, "w") as f:
            f.write("r")
        os.utime(rep, (1_900_000_000, 1_900_000_000))
        for n, t in (("a.py", 1000), ("[a].py", 1000), ("b.py", 1_950_000_000), ("c.py", 1_950_000_000), ("d e.py", 1000)):
            os.utime(os.path.join(g, n), (t, t))
        got = {n: rv.changed_after_review({"where": n + ":1", "review_file": rep}, g)
               for n in ("a.py", "[a].py", "b.py", "c.py", "d e.py")}
        self.assertEqual(got, {"a.py": True, "[a].py": False, "b.py": False, "c.py": True, "d e.py": False})
        rv.changed_after_review({"where": "a.py", "review_file": rep}, d)     # .git yok: yalnız mtime

    def test_usage_files(self):
        d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        recs = [
            {"event": "task_start", "model": "claude-haiku-5-5"},
            {"event": "request", "t": 5000, "seconds": 1.25, "usage": {"prompt_tokens": 100, "completion_tokens": 7,
             "cached_tokens": 40, "reasoning_tokens": True, "total_tokens": 107.9}},
            {"event": "request", "t": "x", "seconds": None, "usage": {"input_tokens": 50, "output_tokens": 3,
             "cache_read_input_tokens": 10, "cache_creation_input_tokens": 5}},
            {"event": "request", "usage": {"input_tokens": 50, "cached_tokens": 60, "cache_write_tokens": 2}},
            {"event": "request", "usage": {"input_tokens": True, "output_tokens": "9", "cache_read_tokens": 4}},
            {"usage": {"prompt_tokens": 10, "cache_creation_input_tokens": 3}}, {"event": "request", "usage": "x"}, [1], 5,
        ]
        body = "".join(json.dumps(r) + "\n" for r in recs) + "bozuk\r\n" + json.dumps(recs[1]) + "\r" + json.dumps(recs[2])
        paths = ["p/anthropic/claude-sonnet-5-5/low/ts/ts.usage.jsonl", "p/anthropic/claude-sonnet-5-5/ts.usage.jsonl",
                 "p/anthropic/x.usage.jsonl", "q/evren/glm/ts/ts.usage.jsonl", ".h/anthropic/m/t/a.usage.jsonl",
                 "q/anthropic/claude-fable-5-1/a/b/c/d.usage.jsonl", "r/codex/short.usage.jsonl"]
        for rel in paths:
            os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
            with open(os.path.join(d, rel), "w", encoding="utf-8", newline="") as f:
                f.write(body)
        with open(os.path.join(d, "q/evren/glm/ts/bad.usage.jsonl"), "wb") as f:
            f.write(b'\xff\xfe\n{"event": "request", "usage": {"total_tokens": 4}}\n')
        rv.usage_summary(d)
        rv.usage_summary(d, "q")
        rv.usage_summary(d + "/yok")
        rv.anthropic_spent_usd(d)
        rv.anthropic_spent_usd(d + "/yok")
        for model in ("", "claude-opus-5-5", "bilinmeyen"):
            for since in (0.0, 4000.0):
                for mult in (1.0, 1.6):
                    rv.usage_cost_usd(os.path.join(d, paths[0]), model, since, mult)
        rv.usage_cost_usd(d + "/yok", "m")
        rv.usage_cost_usd(os.path.join(d, "q/evren/glm/ts/bad.usage.jsonl"), "m")
        odd = ['{"event": "request", "seconds": %s, "usage": {"prompt_tokens": %s}}' % x
               for x in (('"x"', 1), ("[1]", 1), ("1", "Infinity"), ("1", "NaN"), ("2", "2.5"), ("{}", 3), ('"3"', 4))]
        with open(os.path.join(d, "q/evren/glm/ts/bad.usage.jsonl"), "wb") as f:
            f.write(("\n".join(odd) + "\n").encode() + b"\xff\n" + odd[4].encode() + b"\r\n")
        rv.usage_summary(d, "q")
        rv.usage_cost_usd(os.path.join(d, "q/evren/glm/ts/bad.usage.jsonl"), "m")


class TestStoreEdges(unittest.TestCase):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        base = sw.paths_for("reviewer")
        import dataclasses
        self.p = dataclasses.replace(base, root=self.d, reviews=self.d + "/reviews", review_pool=self.d + "/review_pool.json",
                                     review_history=self.d + "/review_history.json", findings=self.d + "/findings.json",
                                     lock=self.d + "/.lock")

    def put(self, path, data):
        with open(path, "wb") as f:
            f.write(data)

    def test_broken_files(self):
        for data in (b"", b"{", b"[]", b"5", b"null", b'"x"', b'{"projects": []}', b'{"a": NaN, "b": 1e400}',
                     b'{"pairs": [], "runs": {}, "x": 12345678901234567890123}', b'{"a": 1, "a": 2}',
                     '{"ü": "\u2028\u001f\\u0000 / \\\\"}'.encode()):
            for path, load in ((self.p.review_pool, rv.load_pool), (self.p.review_history, rv.load_history),
                               (self.p.findings, rv.load_findings)):
                self.put(path, data)
                load(self.p)
        os.remove(self.p.findings)
        rv.load_findings(self.p)

    def test_corrupt_store_write_refused(self):
        for data in (b"{", b"[]", b"5", b"null", b'{"projects": []}', b'{"pairs": 3}', b'{"runs": {}}', b"\xff\xfe"):
            for path, save, value in ((self.p.review_pool, rv.save_pool, {"projects": {}}),
                                      (self.p.review_history, rv.save_history, {"pairs": {}, "runs": []}),
                                      (self.p.findings, rv.save_findings, {})):
                self.put(path, data)
                try:
                    save(self.p, value)
                except rv.StoreCorrupt:
                    pass

    def test_bad_records(self):
        hist = {"pairs": {"a|claude/s": {"started_at": "x"}, "b|claude/s": {"started_at": [1]},
                          "c|claude/s": {"started_at": str(rv.R10_SUB_SINCE + 5)}},
                "blocks": {"evren": {"until": "x"}, "codex": {"until": {"a": 1}}, "copilot": {"until": [2]},
                           "agy/gemini-3": {"until": "x"}}}
        rv.migrate_r10_sub(json.loads(json.dumps(hist)))
        rv.blocked_modes(hist, NOW)
        rv.reconcile_copilot_blocks(json.loads(json.dumps(hist)), (99.0, NOW + 500, "d"), 95.0, NOW)
        rv.reconcile_agy_blocks(json.loads(json.dumps(hist)), {"gemini": {"weekly": (0.0, NOW + 900)}}, [], NOW)
        base = {"state": "verify_sent", "verify_session": "s"}
        rv.requeue_stale_verify({"a": dict(base, verify_sent_at="x"), "b": dict(base, verify_sent_at=1, verify_tries="y"),
                                 "c": dict(base, verify_sent_at=1, verify_tries=float("inf")),
                                 "d": dict(base, verify_sent_at=1, verify_tries="1.5"), "e": dict(base, verify_sent_at=[])}, NOW)
        for rec in ("x", 5, [1], True):
            rv.counts_as_attempt(rec)

    def test_roundtrip_formats(self):
        values = {"f": [0.0, -0.0, 1.0, 1e16, 1e15, 1.5e-5, 1e-4, 123456789.125, 1794908485.0, 5e-324, 1.7976931348623157e308,
                        float("inf"), float("-inf"), float("nan"), 0.1 + 0.2], "i": [0, -1, 2 ** 63 - 1, 2 ** 80],
                  "s": ["", "\x00\x01\x1f\x7f\u2028\u2029\"\\/\b\f\n\r\t", "İğ 🎉"], "e": [{}, [], None, True, False]}
        rv.save_pool(self.p, {"projects": values})
        rv.load_pool(self.p)
        rv.save_findings(self.p, values)
        rv.load_findings(self.p)
        rv.save_history(self.p, {"pairs": {}, "runs": list(range(250)), "version": 1})
        rv.load_history(self.p)
        rv.save_history(self.p, {"runs": None})

    def test_pair_lifecycle(self):
        t = rv.ReviewTarget("agy", "m", "m", "high")
        rv.update_pair(self.p, "p", t, status="running", started_at=NOW, pid=1)
        rv.update_pair(self.p, "p", t, status="error", finished_at=NOW + 12.345, error="x", file=None, io_file="i")
        rv.update_pair(self.p, "p", t, status="running", started_at=NOW + 20)
        rv.update_pair(self.p, "p", t, status="done", finished_at=NOW + 21)
        rv.update_pair(self.p, "p", t, status="running", started_at=NOW + 30)
        rv.update_pair(self.p, "p", t, status="running", started_at=NOW + 30 + rv.WINDOW_SECONDS)
        rv.update_pair(self.p, "p", t, status="running")
        rv.update_pair(self.p, "p", t, status="running", attempts=9, started_at="x")
        rv.update_pair(self.p, "p", t, label_seen="l")
        rv.update_pair(self.p, "p", t, status=None)
        rv.update_pair(self.p, "p", t, status="limit", finished_at=NOW - 10 ** 9)
        with self.assertRaises(ValueError):
            rv.update_pair(self.p, "p", t, status="nope")
        rv.set_block(self.p, "agy/m", NOW + 5, "r")
        rv.set_block(self.p, "evren", NOW + 5)
        self.put(self.p.review_history, b'{"pairs": {"p|agy/m@high": "x"}, "runs": []}')
        rv.update_pair(self.p, "p", t, status="done")
        self.put(self.p.review_history, b'{"blocks": []}')
        with self.assertRaises(TypeError):
            rv.set_block(self.p, "evren", NOW)

    def test_findings_lifecycle(self):
        f = lambda ref, sev, where, title: {"ref": ref, "severity": sev, "where": where, "title": title, "body": "b"}
        r1 = self.d + "/reviews/p/agy/m/1/1.md"
        r2 = self.d + "/reviews/p/evren/n/2/2.md"
        r3 = self.d + "/reviews2/x.md"
        ids = rv.add_findings(self.p, "p", r1, [f("R-1", "P3", "a.py:1", "İşlem"), f("R-2", "P2", "a.py:9", "İşlem")])
        rv.add_findings(self.p, "p", r1, [f("R-1", "P3", "a.py:1", "İşlem")])
        rv.add_findings(self.p, "p", r2, [f("R-1", "P1", "`a.py`:7", "islem!"), f("R-2", "P3", "b.py", "yeni")])
        rv.add_findings(self.p, "q q", r3, [f("R-1", "P1", "a.py:1", "İşlem")])
        rv.add_findings(self.p, "p", r1.replace("/1/1.md", "/11.md"), [f("R-1", "P1", "c", "d")])
        rv.add_findings(self.p, "p", r1.replace("/1/1.md", "/1-1.md"), [f("R-1", "P1", "e", "f")])
        rv.add_findings(self.p, "p", r2, [])
        rv.mark_verify_sent(self.p, ids + ["yok"], "s", "h", NOW)
        rv.mark_verify_sent(self.p, [], "s", "h", NOW)
        dup = [k for k, v in rv.load_findings(self.p).items() if v["state"] == "dup"]
        for fid in ids + dup + ["yok"]:
            for action in ("approve", "reject", "approve", "undup", "undup", "reject", "x"):
                rv.decide_finding(self.p, fid, action, NOW, "owner_cli")
        data = rv.load_findings(self.p)
        data["str"] = "x"
        data["noproj"] = {"state": "new"}
        data["old"] = {"project": "p", "where": "z:1", "title": "Z", "state": "refuted", "created_at": "x", "review_file": "o"}
        data["old2"] = {"project": "p", "where": "z", "title": "z", "state": "verified", "severity": None, "review_file": "o"}
        rv.save_findings(self.p, data)
        rv.add_findings(self.p, "p", r3, [f("R-9", "P1", "z:5", "z")])
        rv.decide_finding(self.p, "str", "approve", NOW)
        for odd in ({"state": None}, {"state": 5}, {}):
            rv.save_findings(self.p, {"o": odd})
            rv.decide_finding(self.p, "o", "approve", NOW)
            rv.decide_finding(self.p, "o", "undup", NOW)


T = rv.ReviewTarget("evren", "m1", "m1")


class TestNonFinite(unittest.TestCase):
    """Sonlu olmayan sayılar (TBD#368 b): iki tarafta aynı sonuç."""

    def test_non_finite_numbers(self):
        d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        bad = (float("inf"), float("-inf"), float("nan"), 10 ** 400, 10 ** 30, "inf", "nan", "1e999", "x", True)
        path = d + "/u.usage.jsonl"
        with open(path, "w") as f:
            for b in bad:
                for rec in ({"t": b, "usage": {"input_tokens": 100}}, {"t": 9, "usage": {"input_tokens": b}},
                            {"t": 9, "usage": {"output_tokens": 7, "other": b}}):
                    f.write(json.dumps(rec) + "\n")
        for since in (0.0, 5.0):
            rv.usage_cost_usd(path, "sonnet-5-5", since_ms=since)
        rv.duration_summary({"runs": [{"pair": "p|a/m", "seconds": b} for b in bad]})
        for b in bad:
            rv.counts_as_attempt({"error": rv.CAPACITY_ERROR_PREFIX, "attempts": b})
            rv._run_seconds({"started_at": 5.0, "finished_at": b})
            rv.blocked_modes({"blocks": {"evren": {"until": b}}}, 1.0)
            if b != 10 ** 30:     # i64 dışı sonlu sayaç: Rust sınıra kırpar (docs/rs-rev.md "Bilinen küçük sapmalar")
                rv.requeue_stale_verify({"f": {"state": "verify_sent", "verify_session": "s", "verify_sent_at": 1,
                                               "verify_tries": b}}, 10.0 ** 9)
            rv.next_review({"projects": {"p": {"enabled": True}}},
                           {"pairs": {rv.pair_key("p", T): {"status": "error", "attempts": b, "started_at": b,
                                                            "finished_at": b, "retry_at": b}}}, [T], 200.0)

    def test_usage_counter_bounds(self):
        """Geçersiz sayaç (`_usage_number`: bool, negatif, 1e15 üstü) toplanmaz; sınır değerleri ve FIFO iki tarafta aynı."""
        d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        vals = (True, False, -1, -0.0, 0, 1e15, 10 ** 15, 10 ** 15 + 1, 1e15 * 1.0000001, 2 ** 63, 12.5, None, [1], {"a": 1})
        path = d + "/u.usage.jsonl"
        with open(path, "w") as f:
            for v in vals:
                for k in ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens", "cache_read_input_tokens",
                          "cached_tokens", "cache_creation_input_tokens", "cache_write_tokens"):
                    f.write(json.dumps({"t": 9, "usage": {k: v, "output_tokens": 3}}) + "\n")
                    f.write(json.dumps({"t": 9, "usage": {k: v, "prompt_tokens": 50, "cached_tokens": 10}}) + "\n")
        for model in ("", "sonnet-5-5"):
            rv.usage_cost_usd(path, model)
        os.mkfifo(d + "/p.usage.jsonl")
        rv.usage_cost_usd(d + "/p.usage.jsonl", "m")
        os.mkdir(d + "/dir.usage.jsonl")
        rv.usage_cost_usd(d + "/dir.usage.jsonl", "m")


class TestRealData(unittest.TestCase):
    """Canlı deponun KOPYASI üzerinde okuma-yazma ve türetme; veri yoksa atlanır."""

    def setUp(self):
        src = os.environ.get("COPS_REV_PARITY_DATA")
        if not src:
            self.skipTest("COPS_REV_PARITY_DATA yok")
        self.src = src
        self.d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        for n in ("findings.json", "review_history.json", "review_pool.json"):
            shutil.copy(os.path.join(src, n), self.d)
        import dataclasses
        self.p = dataclasses.replace(sw.paths_for("reviewer"), root=self.d, reviews=src + "/reviews",
                                     review_pool=self.d + "/review_pool.json", review_history=self.d + "/review_history.json",
                                     findings=self.d + "/findings.json", lock=self.d + "/.lock")

    def test_stores(self):
        pool, hist, found = rv.load_pool(self.p), rv.load_history(self.p), rv.load_findings(self.p)
        rv.save_pool(self.p, pool)
        rv.save_history(self.p, hist)
        rv.save_findings(self.p, found)
        now = time.time()
        for k, r in found.items():
            rv.finding_key(r.get("project"), r.get("where"), r.get("title"))
            rv.redact_secrets(r.get("body") or "")
            rv.is_decision(r)
            rv.where_text(r)
            rv.where_relpath(r)
            rv.reviewer_slug_of(r.get("review_file") or "")
        rows = [dict(r, id=k) for k, r in list(found.items())[:400]]
        rv.export_lines(rows, self.p.reviews)
        rv.build_verify_message(rows[:20])
        rv.requeue_stale_verify(copy.deepcopy(found), now)
        for t in (now, now - 86400 * 10):
            rv.blocked_modes(hist, t)
            rv.model_health(hist, t)
        rv.duration_summary(hist)
        cfg = sw.Config()
        keys = sorted({k.split("|", 1)[1] for k in hist["pairs"] if "|" in k})
        targets = [rv.ReviewTarget(k.split("/")[0], k.split("/", 1)[1].split("@")[0], k.split("/", 1)[1].split("@")[0],
                                   k.split("@")[1].split("~")[0] if "@" in k else "") for k in keys]
        for n in range(0, len(targets), 7):
            rv.next_review(pool, hist, targets[n:n + 12], now)
        rv.next_review(pool, hist, targets, now)
        for proj in rv.pool_enabled(pool):
            rv.project_complete(hist, proj, targets[:5], now)
        ids = [k for k, r in found.items() if r.get("state") == "verified"][:2]
        for fid in ids:
            rv.decide_finding(self.p, fid, "approve", now)
        rv.add_findings(self.p, "claudeops", self.src + "/reviews/claudeops/x/y/1/1.md",
                        [{"ref": "R-1", "severity": "P1", "where": r.get("where"), "title": r.get("title"), "body": ""}
                         for r in list(found.values())[:1] if r.get("project") == "claudeops"] or
                        [{"ref": "R-1", "severity": "P1", "where": "a", "title": "b", "body": ""}])
        rv.update_pair(self.p, "claudeops", targets[0], status="running", started_at=now)

    def test_reports(self):
        root = self.src + "/reviews"
        n = 0
        for dp, _d, files in os.walk(root):
            for fn in sorted(files):
                if fn.endswith(".md") and n < 1500:
                    with open(os.path.join(dp, fn), encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    n += 1
                    rv.parse_findings(text)
                    rv.redact_secrets(text)
                    rv.report_incomplete(text)
                    rv.report_bodyless(text)
                    rv.scan_verdicts(text)
        rv.usage_summary(root)
        rv.anthropic_spent_usd(root)
