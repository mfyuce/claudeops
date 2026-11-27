"""rs/prov §3.7 (S5 = b): günlük tavan açılış denetimi her harcama dosyasını TEK geçişte okur; ret kuralı, hata metni,
günlük olayları ve toplamlar eskisiyle AYNI. Eski davranışın kahini bu dosyadaki dondurulmuş eski tarayıcı (`_old_scan`) ve
eski çağrı sırası (`_old_gate`). Her şey geçici dizinde."""
from __future__ import annotations

import json
import math
import os
import random
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import paths, ucli_cost  # noqa: E402
from claudeops import review as rv  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402


def _old_scan(path, model, since_ms, write_mult):
    """`review._scan_usage`ın 285c91e4'teki hâli (tek pencere); karşılaştırma için DONDURULMUŞ, güncellenmez."""
    pi, po, pr, pw = rv.anthropic_price(model or "opus-5-5")
    tot = 0.0
    problem = ""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                os.close(fd)
                return 0.0, "normal dosya değil"
            f = os.fdopen(fd, "rb")
        except OSError:
            os.close(fd)
            raise
        with f:
            for raw in f:
                try:
                    line = raw.decode("utf-8")
                except UnicodeDecodeError:
                    rv._log_bad("usage.line", path)
                    continue
                try:
                    rec = json.loads(line)
                    if not isinstance(rec, dict):
                        continue
                except (ValueError, RecursionError):
                    continue
                if not model and rec.get("event") == "task_start" and rec.get("model"):
                    pi, po, pr, pw = rv.anthropic_price(str(rec["model"]))
                    continue
                try:
                    t_rec = float(rec.get("t") or 0)
                    t_ok = True
                except (TypeError, ValueError):
                    t_rec, t_ok = 0.0, False
                except OverflowError:
                    t_rec, t_ok = math.inf, False
                u = rec.get("usage")
                if (not t_ok or not math.isfinite(t_rec)) and isinstance(u, dict):
                    problem = "geçersiz zaman damgası"
                if not math.isfinite(t_rec):
                    rv._log_bad("usage.record", path)
                    continue
                if since_ms and t_rec < since_ms:
                    continue
                if not isinstance(u, dict) or rec.get("event") == "task_end":
                    continue
                if any(u.get(n) is not None and not rv._usage_number(u[n]) for n in rv._USAGE_COUNT_KEYS):
                    problem = "geçersiz sayaç"
                if not all(rv._finite(v) for v in u.values() if isinstance(v, (int, float))):
                    rv._log_bad("usage.record", path)
                    continue

                def g(*names):
                    for n in names:
                        if rv._usage_number(u.get(n)):
                            return float(u[n])
                    return 0.0
                cr = g("cache_read_input_tokens", "cached_tokens", "cache_read_tokens")
                cw = g("cache_creation_input_tokens", "cache_write_tokens")
                if rv._usage_number(u.get("input_tokens")):
                    inp = max(0.0, float(u["input_tokens"]) - (0 if "cache_read_input_tokens" in u else cr) - (0 if "cache_creation_input_tokens" in u else cw))
                else:
                    inp = max(0.0, g("prompt_tokens") - cr - cw)
                if "cached_tokens" in u and "cache_creation_input_tokens" not in u:
                    inp_price = pw
                else:
                    inp_price = pi
                out_price, read_price, write_price = po, pr, pw
                if (pi, po, pr, pw) == rv.ANTHROPIC_PRICES["haiku-5-5"] and inp + cr + cw > rv.HAIKU_LONG_PROMPT:
                    long_in, out_price, read_price, write_price = rv.HAIKU_LONG_PRICE
                    inp_price = long_in if inp_price == pi else write_price
                tot += (inp * inp_price + g("output_tokens", "completion_tokens") * out_price + cr * read_price
                        + cw * write_price * write_mult) / 1e6
    except FileNotFoundError:
        pass
    except OSError:
        problem = "okunamadı"
    return tot, problem


def _old_gate(session):
    """`_claude_service_flags`ın eski kapısı: üç ayrı çağrı, her biri dosyaları kendi okur."""
    if ucli_cost.cap_exceeded():
        st = ucli_cost.state(use_cache=False)
        raise ucli_cost.DailyCapExceeded(st['today_usd'], st['cap_usd'])
    ucli_cost.reserve(session)


def _noon():
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))


NOW = _noon()


def _random_line(rng):
    ms = NOW * 1000.0
    numbers = [0, 1, 7, 1234, 999999, 2.5, -1, -0.0, float("nan"), float("inf"), 1e300, 1e15, 10 ** 15 + 1, True, "7", None,
               10 ** 400, [], {}, 99999, 100001]
    keys = list(rv._USAGE_COUNT_KEYS) + ["baska"]
    roll = rng.randrange(14)
    if roll == 0:
        return rng.choice([b"", b"{bozuk", b"[]", b"5", b"null", b'{"usage": 1}', b"\xff\xfe", b'{"t": 1, "x": "\xc4'])
    if roll == 1:
        model = rng.choice(["claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1", "x", 5, "", None, ["sonnet-5-5"], "\ud800"])
        return json.dumps({"event": "task_start", "model": model, "t": ms}).encode()
    if roll == 2:      # nesneyle birlikte 511-513 katlı satır: Python okur (daha derinini rs/rev kopyası saymaz; koşucusu bu çağrıları da görür)
        depth = rng.choice([510, 511, 512])
        return ('{"t": %r, "usage": {"input_tokens": 1000}, "x": %s%s}' % (ms, "[" * depth, "]" * depth)).encode()
    if roll == 3:      # eşi olmayan vekil
        return ('{"t": %r, "n": "\\ud800", "usage": {"input_tokens": 500000}}' % ms).encode()
    t = rng.choice([ms, ms - 5 * 60_000, ms - 30 * 60_000, ms - 3 * 3600_000, ms - 3 * 86400_000, ms - 40 * 86400_000,
                    ms, ms, ms, str(ms)])
    if rng.randrange(8) == 0:
        t = rng.choice(["abc", "", None, 0, float("nan"), float("inf"), -float("inf"), True, [1], {}, "nan", 10 ** 400])
    usage = {}
    for _ in range(rng.randrange(5)):
        usage[rng.choice(keys)] = rng.randrange(5_000_000) if rng.randrange(3) else rng.choice(numbers)
    rec = {"t": t, "usage": usage}
    if rng.randrange(10) == 0:
        rec["event"] = rng.choice(["task_end", "request", "task_start"])
    return json.dumps(rec).encode()


def _good_line(ms, tokens=100_000):
    return json.dumps({"t": ms, "usage": {"input_tokens": tokens, "output_tokens": 10}}).encode()


class _Tree(unittest.TestCase):
    """Ortak dizin + ikinci örneğin kendi dizini; saat sabit; canlı dosya okunmaz."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.base = os.path.join(self.root, ".claude", "claudeops", "ucli_usage")
        self.own = os.path.join(self.root, "own", "ucli_usage")
        os.makedirs(self.base)
        self.settings = os.path.join(self.root, "settings.json")
        self.cfg = {"daily_cap_usd": 1e9, "cache_ttl": "1h", "credit_total_usd": 100.0, "credit_since": "", "credit_until": ""}
        self.clock = [NOW]
        self.events = []
        patches = [
            mock.patch.dict(os.environ, {"HOME": self.root}),
            mock.patch.object(paths, "CLAUDEOPS_DIR", os.path.join(self.root, "own")),
            mock.patch.object(ucli_cost, "USAGE_DIR", self.base),
            mock.patch.object(ucli_cost.state, "__defaults__", (None, self.base, True)),
            mock.patch.object(ucli_cost.cap_exceeded, "__defaults__", (None, self.base)),
            mock.patch.object(ucli_cost.reserve, "__defaults__", (None, self.base)),
            mock.patch.object(ucli_cost, "ucli_cost_config", lambda: dict(self.cfg)),
            mock.patch.object(up, "ucli_cost_config", lambda: dict(self.cfg)),
            mock.patch("claudeops.settings.SETTINGS_JSON", self.settings),
            mock.patch.object(up, "binary_supports_flag", lambda *a: False),
            mock.patch.object(up, "diag_log", lambda *a, **k: None),
            mock.patch.object(rv, "diag_log", lambda event, **k: self.events.append((event, k))),
            mock.patch.object(time, "time", lambda: self.clock[0]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.reset()
        self.addCleanup(self.reset)

    def reset(self):
        ucli_cost.invalidate()
        ucli_cost._RESERVED.clear()
        rv._BAD_SEEN.clear()
        self.events.clear()
        self.clock[0] = NOW

    def put(self, name, lines, own=False, mtime=NOW):
        path = os.path.join(self.own if own else self.base, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"".join(x + b"\n" for x in lines))
        os.utime(path, (mtime, mtime))
        return path

    def run_gate(self, gate, others=()):
        self.reset()
        for name, usd in others:
            ucli_cost._RESERVED[name] = (usd, NOW + 60)
        try:
            gate("s")
            outcome = ("ok",)
        except ValueError as e:
            outcome = (type(e).__name__, str(e), getattr(e, "today_usd", None), getattr(e, "cap_usd", None))
        # `repr`: kayan nokta bit bit, NaN de karşılaştırılabilir
        return repr((outcome, sorted(ucli_cost._CACHE.items()), sorted(ucli_cost._RESERVED.items()), self.events))

    def old(self, others=()):
        with mock.patch.object(rv, "_scan_usage", _old_scan):
            return self.run_gate(_old_gate, others)

    def new(self, others=()):
        return self.run_gate(lambda s: up._claude_service_flags(["ucli"], s), others)

    def opens(self, fn):
        seen: dict = {}
        real = os.open

        def counting(path, *a, **k):
            if str(path).endswith(".jsonl"):
                rel = os.path.relpath(path, self.root)
                seen[rel] = seen.get(rel, 0) + 1
            return real(path, *a, **k)
        with mock.patch.object(os, "open", counting):
            fn()
        return seen

    def full_tree(self):
        ms = NOW * 1000.0
        self.put("good.jsonl", [_good_line(ms), _good_line(ms - 5 * 60_000), _good_line(ms - 30 * 60_000), _good_line(ms - 3 * 86400_000)])
        self.put("good.jsonl", [_good_line(ms, 7000)], own=True)
        self.put("yeni.jsonl", [_good_line(ms - 20 * 60_000)], own=True)
        self.put("eski.jsonl", [_good_line(ms - 3 * 86400_000)], mtime=NOW - 3 * 86400)
        self.put("other/disarida.jsonl", [_good_line(ms)])
        self.put("not.txt", [_good_line(ms)])


class EveryLogIsReadOnce(_Tree):
    WANT = {".claude/claudeops/ucli_usage/good.jsonl": 1, ".claude/claudeops/ucli_usage/eski.jsonl": 1,
            "own/ucli_usage/good.jsonl": 1, "own/ucli_usage/yeni.jsonl": 1}

    def test_allowed_start(self):
        self.full_tree()
        self.assertEqual(self.opens(lambda: up._claude_service_flags(["ucli"], "s")), self.WANT)
        self.assertEqual(list(ucli_cost._RESERVED), ["s"])

    def test_refused_over_the_cap(self):
        self.full_tree()
        self.cfg["daily_cap_usd"] = 0.01

        def go():
            with self.assertRaises(ucli_cost.DailyCapExceeded):
                up._claude_service_flags(["ucli"], "s")
        self.assertEqual(self.opens(go), self.WANT)

    def test_unreadable_ledger_and_cap_off(self):
        self.full_tree()
        self.put("bozuk.jsonl", [b'{"t": %d, "usage": {"input_tokens": -1}}' % int(NOW * 1000)])
        want = dict(self.WANT, **{".claude/claudeops/ucli_usage/bozuk.jsonl": 1})

        def go():
            with self.assertRaisesRegex(ValueError, "bozuk.jsonl: geçersiz sayaç"):
                up._claude_service_flags(["ucli"], "s")
        self.assertEqual(self.opens(go), want)
        self.cfg["daily_cap_usd"] = 0.0
        self.assertEqual(self.opens(lambda: up._claude_service_flags(["ucli"], "s")), want)

    def test_a_moving_clock_does_not_cause_a_second_read(self):
        self.full_tree()

        def ticking():
            self.clock[0] += 7.0
            return self.clock[0]
        with mock.patch.object(time, "time", ticking):
            self.assertEqual(self.opens(lambda: up._claude_service_flags(["ucli"], "s")), self.WANT)
        # payın ömrü eskisi gibi rezervasyon anından sayılır (taramanın saati değil)
        self.assertEqual(ucli_cost._RESERVED["s"][1], self.clock[0] + ucli_cost.RESERVE_TTL)

    def test_credit_period_skips_files_written_before_it(self):
        self.full_tree()
        self.cfg["credit_since"] = time.strftime("%Y-%m-%d", time.localtime(NOW - 86400))
        want = dict(self.WANT)
        del want[".claude/claudeops/ucli_usage/eski.jsonl"]
        self.assertEqual(self.opens(lambda: up._claude_service_flags(["ucli"], "s")), want)

    def test_nothing_is_kept_between_two_starts(self):
        self.full_tree()
        up._claude_service_flags(["ucli"], "s")
        self.put("good.jsonl", [_good_line(NOW * 1000, 10 ** 12)])
        self.cfg["daily_cap_usd"] = 100.0
        with self.assertRaises(ucli_cost.DailyCapExceeded):
            up._claude_service_flags(["ucli"], "s")
        self.assertEqual(self.opens(lambda: ucli_cost.today_usd(NOW, self.base)),
                         {".claude/claudeops/ucli_usage/good.jsonl": 1, "own/ucli_usage/good.jsonl": 1,
                          "own/ucli_usage/yeni.jsonl": 1})

    def test_midnight_between_the_two_checks_reads_the_new_day(self):
        lt = time.localtime(NOW)
        midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, 0, 0, 0, 0, 0, -1))
        self.put("a.jsonl", [_good_line((midnight - 60) * 1000, 10 ** 6)], mtime=midnight - 60)
        self.cfg["daily_cap_usd"] = 1e6
        ticks = iter([midnight - 1])

        def clock():
            return next(ticks, midnight + 1)
        with mock.patch.object(time, "time", clock):
            up._claude_service_flags(["ucli"], "s")
        self.assertEqual(ucli_cost._CACHE["usd"], 0)
        self.assertEqual(ucli_cost._CACHE["day"], time.strftime("%Y-%m-%d", time.localtime(midnight + 1)))


class SameDecisionAsBefore(_Tree):
    def same(self, others=()):
        want, got = self.old(others), self.new(others)
        self.assertEqual(got, want)
        return want

    def test_each_problem_kind(self):
        ms = NOW * 1000.0
        deep = ('{"t": %r, "usage": {"input_tokens": 1000}, "x": %s%s}' % (ms, "[" * 512, "]" * 512)).encode()
        kinds = {
            "bozuk-satir": [b"{yarim", b"\xff\xfe", _good_line(ms)],
            "gecersiz-sayac": [b'{"t": %d, "usage": {"input_tokens": -1, "output_tokens": 5}}' % int(ms)],
            "eski-gecersiz-sayac": [b'{"t": %d, "usage": {"input_tokens": -1}}' % int(ms - 3 * 86400_000), _good_line(ms)],
            "sonsuz-sayac": [b'{"t": %d, "usage": {"input_tokens": Infinity}}' % int(ms)],
            "gecersiz-damga": [b'{"t": "abc", "usage": {"input_tokens": 5}}'],
            "sonsuz-damga": [b'{"t": NaN, "usage": {"input_tokens": 5}}'],
            "iki-sorun": [b'{"t": "abc", "usage": {}}', b'{"t": %d, "usage": {"input_tokens": true}}' % int(ms)],
            "vekil": [b'{"t": %d, "n": "\\ud800", "usage": {"input_tokens": 500000}}' % int(ms)],
            "derin": [deep],
        }
        seen = []
        for name, lines in kinds.items():
            with self.subTest(name):
                path = self.put(f"{name}.jsonl", lines)
                for cap in (0.0, 1e-9, 1e9):
                    self.cfg["daily_cap_usd"] = cap
                    seen.append(self.same())
                os.remove(path)
        text = "\n".join(seen)
        for needle in ("('ok',)", "DailyCapExceeded", "geçersiz sayaç", "geçersiz zaman damgası", "usage.line", "usage.record"):
            self.assertIn(needle, text)

    def test_unreadable_files_and_directory(self):
        os.mkdir(os.path.join(self.base, "dizin.jsonl"))
        os.utime(os.path.join(self.base, "dizin.jsonl"), (NOW, NOW))
        self.assertIn("normal dosya değil", self.same())
        os.rmdir(os.path.join(self.base, "dizin.jsonl"))
        os.mkfifo(os.path.join(self.base, "boru.jsonl"))
        os.utime(os.path.join(self.base, "boru.jsonl"), (NOW, NOW))
        self.assertIn("normal dosya değil", self.same())
        os.remove(os.path.join(self.base, "boru.jsonl"))
        locked = self.put("kilitli.jsonl", [_good_line(NOW * 1000)])
        os.chmod(locked, 0)
        if not os.access(locked, os.R_OK):
            self.assertIn("kilitli.jsonl: okunamadı", self.same())
        os.remove(locked)
        os.makedirs(os.path.dirname(self.own))
        with open(self.own, "w"):      # ikinci örneğin dizini yerine dosya
            pass
        self.assertIn("günlük dizini okunamadı", self.same())

    def test_reservations_and_broken_settings(self):
        self.full_tree()
        self.cfg["daily_cap_usd"] = 1e-9
        self.assertIn("DailyCapExceeded", self.same())
        self.cfg["daily_cap_usd"] = 50.0
        self.assertIn("DailyCapExceeded", self.same(others=[("a", 60.0)]))
        self.assertIn("('ok',)", self.same(others=[("a", 1.0)]))
        with open(self.settings, "w") as f:
            f.write("{bozuk")
        self.cfg["daily_cap_usd"] = 0.0
        self.assertIn("denetlenemiyor", self.same())

    def test_random_trees(self):
        rng = random.Random(20261127)
        outcomes = set()
        for round_no in range(120):
            files = []
            for i in range(rng.randrange(1, 5)):
                own = rng.randrange(3) == 0
                age = rng.choice([0, 0, 0, 600, 3 * 86400, 40 * 86400])
                broken = rng.randrange(3) == 0
                lines = [_random_line(rng) for _ in range(rng.randrange(1, 12))] if broken else \
                    [_good_line(NOW * 1000 - rng.randrange(0, 200) * 60_000, rng.randrange(10 ** 6)) for _ in range(rng.randrange(1, 8))]
                files.append(self.put(f"o{i}.jsonl", lines, own=own, mtime=NOW - age))
            self.cfg["daily_cap_usd"] = rng.choice([0.0, 1e-9, 0.5, 3.0, 1e9])
            self.cfg["cache_ttl"] = rng.choice(["5m", "1h"])
            self.cfg["credit_since"] = rng.choice(["", time.strftime("%Y-%m-%d", time.localtime(NOW - 5 * 86400)), "2001-13-45"])
            with self.subTest(round_no):
                outcomes.add(self.same(others=[("a", rng.choice([0.0, 1.0]))]).split(",")[0])
            for path in files:
                if os.path.exists(path):
                    os.remove(path)
        self.assertGreaterEqual(len(outcomes), 3, outcomes)      # üç sonuç türü de denendi

    def test_the_scanner_matches_the_old_one_for_every_window(self):
        rng = random.Random(7)
        ms = NOW * 1000.0
        windows = (0.0, ms - 12 * 3600_000, ms - 3600_000, ms - 900_000, ms + 1)
        for round_no in range(200):
            path = self.put("t.jsonl", [_random_line(rng) for _ in range(rng.randrange(1, 15))])
            model = rng.choice(["", "", "sonnet-5-5", "haiku-5-5"])
            mult = rng.choice([1.0, 1.6])
            many = rv._scan_usage_windows(path, model, windows, mult)
            for since in windows:
                with self.subTest(round=round_no, since=since):
                    rv._BAD_SEEN.clear()
                    self.events.clear()
                    want = _old_scan(path, model, since, mult)
                    want_events = list(self.events)
                    rv._BAD_SEEN.clear()
                    self.events.clear()
                    self.assertEqual(repr(rv._scan_usage(path, model, since, mult)), repr(want))
                    self.assertEqual(self.events, want_events)
                    self.assertEqual(repr(many[since][:2]), repr(want))
                    self.assertEqual([("review_bad_record", {"what": w, "key": path[:200]}) for w in many[since][2]], want_events)


if __name__ == "__main__":
    unittest.main()
