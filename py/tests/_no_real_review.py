"""Test koruması: review testleri GERÇEK süreç (ucli/agy) başlatamaz.

`NoRealReviewMixin` (ya da `install()`), `web_review._default_popen`'u çağrılınca kaydeden ve AssertionError fırlatan
sahteyle değiştirir; ayrıca test sonunda (thread içinde yutulmuş olsa bile) deneme olduysa testi başarısız kılar.
Kendi `popen=` / `_RUN_KW` / `start_job` sahtesini enjekte eden testler etkilenmez (onlar `_default_popen`e varmaz).
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock


MSG = "test gerçek review süreci başlatmaya çalıştı"


def install(testcase: unittest.TestCase) -> list:
    """Korumayı kurar; `testcase` bitince geri alınır ve deneme olduysa başarısız sayılır. Deneme listesini döner."""
    from claudeops.commands import web_review as wr
    attempts: list = []

    def _blocked(*a, **k):
        attempts.append((a, k))
        raise AssertionError(MSG)

    p = mock.patch.object(wr, "_default_popen", _blocked)
    p.start()
    testcase.addCleanup(p.stop)
    testcase.addCleanup(lambda: testcase.assertEqual(attempts, [], MSG))
    return attempts


class NoRealReviewMixin:
    """`class T(NoRealReviewMixin, _Engine)`: setUp'ta korumayı kurar (MRO'da `super().setUp()` çağırır)."""

    def setUp(self):  # noqa: D401
        super().setUp()
        self.real_review_attempts = install(self)
