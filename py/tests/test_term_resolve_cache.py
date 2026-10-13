"""`web._term_resolve_for_output` önbelleği testleri (stdlib unittest, ek bağımlılık yok; ağa / tmux'a DOKUNMAZ).

Çalıştırma:  python3 py/tests/test_term_resolve_cache.py -v

Kapsadığı hata (TODO.md 2026-10-13 (2)): önbellek 2 sn'ydi; her dolduğunda tüm sistemin psutil taraması bu oturum
için yeniden koşuyordu (yuhem'de 1746 süreç: 69 ms, ulak_31'de 1080 süreç: 106 ms) ve bu, yoklama sıklığından
BAĞIMSIZ oturum başına 0,5 tarama/sn demekti. 17 mirror ulak_31 panelini %148, 7 mirror yuhem panelini %211 CPU'ya
çıkardı; tick'ler önbellekten uzun sürmeye başlayınca her tick tarama yapıp kendini besledi. İzole yeniden üretimde
(17 oturum) yalnız TTL 2 → 30: panel CPU %181 → %14.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web  # noqa: E402


class _ResolveBase(unittest.TestCase):
    def setUp(self):
        web._term_output_resolve_cache.clear()
        self.addCleanup(web._term_output_resolve_cache.clear)
        self.now = [1000.0]
        self.resolves = []          # tam (taramalı) `_term_resolve` çağrıları
        self.next_result = None     # (session, err) ile geçersiz kıl

        def fake_resolve(name, lang="tr"):
            self.resolves.append(name)
            if self.next_result is not None:
                return self.next_result
            return SimpleNamespace(name=name, cli="shell"), None

        for p in (mock.patch.object(web, "_term_resolve", fake_resolve),
                  mock.patch.object(web, "time", SimpleNamespace(monotonic=lambda: self.now[0]))):
            p.start()
            self.addCleanup(p.stop)

    def tick(self, name="s1", seconds=0.0):
        self.now[0] += seconds
        return web._term_resolve_for_output(name, "en")


class ResolveCacheTests(_ResolveBase):
    def test_one_resolution_serves_every_tick_inside_the_ttl(self):
        for _ in range(125):        # 25 sn'lik 0,2 sn'lik poll döngüsü
            s, err = self.tick(seconds=0.2)
            self.assertIsNone(err)
            self.assertEqual(s.name, "s1")
        self.assertEqual(self.resolves, ["s1"])

    def test_resolution_count_does_not_depend_on_the_poll_rate(self):
        for step in (0.2, 1.0):
            web._term_output_resolve_cache.clear()
            self.resolves.clear()
            for _ in range(int(60 / step)):
                self.tick(seconds=step)
            self.assertLessEqual(len(self.resolves), 3, f"poll adımı {step} sn")   # 60 sn / 30 sn TTL ≈ 2

    def test_resolution_is_refreshed_after_the_ttl(self):
        self.tick()
        self.tick(seconds=web._TERM_OUTPUT_RESOLVE_TTL - 0.1)
        self.assertEqual(len(self.resolves), 1)
        self.tick(seconds=0.2)
        self.assertEqual(len(self.resolves), 2)

    def test_each_session_is_resolved_independently(self):
        for name in ("a", "b", "a", "b"):
            self.tick(name)
        self.assertEqual(sorted(self.resolves), ["a", "b"])

    def test_errors_are_not_cached_so_a_session_that_starts_is_found_at_once(self):
        self.next_result = (None, {"ok": False, "error": "gone"})
        self.assertIsNotNone(self.tick(seconds=0.2)[1])
        self.assertIsNotNone(self.tick(seconds=0.2)[1])
        self.assertEqual(len(self.resolves), 2)             # her tick yeniden çözümledi
        self.next_result = None
        self.assertIsNone(self.tick(seconds=0.2)[1])        # başladı: hemen bulundu
        self.tick(seconds=0.2)
        self.assertEqual(len(self.resolves), 3)             # ve şimdi önbellekte

    def test_ttl_is_long_enough_for_the_scan_to_be_rare(self):
        # 2 sn'de kalırsa oturum başına 0,5 tarama/sn geri gelir (bkz. dosya başı); bilerek bir alt sınır
        self.assertGreaterEqual(web._TERM_OUTPUT_RESOLVE_TTL, 10.0)


class CaptureFailureTests(_ResolveBase):
    def test_gone_tmux_session_drops_the_entry_so_a_respawn_is_found_next_tick(self):
        self.tick()
        self.assertIn("s1", web._term_output_resolve_cache)
        with mock.patch.object(web, "tmux_capture", lambda name, lines=2000: None):
            out = web._term_output("s1", lang="en")
        self.assertFalse(out["ok"])
        self.assertNotIn("s1", web._term_output_resolve_cache)
        self.tick(seconds=0.2)
        self.assertEqual(self.resolves, ["s1", "s1"])       # eski girdiden değil, yeniden çözümlendi


if __name__ == "__main__":
    unittest.main()
