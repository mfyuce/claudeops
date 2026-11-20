"""TBD#268 (c, sahip 22 Kas): gövdesinde yalnız gizli desen sözcüğü olan bulgu otomatik onaylanır; iletimde/otomatik dışa yazımda GÖVDE çıkar,
başlık + yer gider. Başlık/yerde desen varsa eskisi gibi sahibe kalır."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward_advance as sa  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402


def rec(**kw):
    base = dict(project="p", state="approved", severity="P2", where="a.py:1", title="Sızıntı düzelt", body="body")
    base.update(kw)
    return base


class BodySensitive(unittest.TestCase):
    def test_flags(self):
        self.assertTrue(sa.body_sensitive(rec(body="parola düz metin yazılmış")))
        self.assertFalse(sa.is_sensitive(rec(body="parola düz metin yazılmış")))      # başlık/yer temiz: onay engellenmez
        self.assertTrue(sa.is_sensitive(rec(title="parola sızıyor")))

    def test_remote_candidate_body_omitted_not_skipped(self):
        r = rec(body="api_key değeri kodda")
        rows = sa.candidates([{"F1": r}], lambda _p: "/w", remote_of=lambda _p: "yuhem", remote_todo_of=None)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["body"], "")
        self.assertTrue(rows[0]["body_omitted"])
        self.assertEqual(rows[0]["title"], "Sızıntı düzelt")
        rows = sa.candidates([{"F1": rec(title="parola sızıyor")}], lambda _p: "/w", remote_of=lambda _p: "yuhem")
        self.assertEqual(rows, [])                                                    # başlıkta desen: iletilmez
        rows = sa.candidates([{"F1": rec()}], lambda _p: "/w", remote_of=lambda _p: "yuhem")
        self.assertEqual(rows[0]["body"], "body")

    def test_redacted_row_strips_body_only_for_auto(self):
        r = rec(body="secret yazılmış")
        self.assertEqual(wr._redacted_row(r, "auto")["body"], "")
        self.assertEqual(wr._redacted_row(r, "owner")["body"], "secret yazılmış")
        self.assertEqual(wr._redacted_row(rec(), "auto")["body"], "body")

    def test_export_sensitive_ignores_body_keyword(self):
        self.assertFalse(wr.export_sensitive(rec(body="password var")))


class AutoApprove(unittest.TestCase):
    def test_body_keyword_approved_title_keyword_held(self):
        from types import SimpleNamespace as NS
        from unittest import mock
        from claudeops import review as rv
        from claudeops import steward as sw
        data = {"A": rec(state="verified", body="parola düz metin"), "B": rec(state="verified", title="parola sızıyor"),
                "C": rec(state="verified")}
        called = []
        with mock.patch.object(sw, "paths_for", lambda sid: None), mock.patch.object(sw, "log_event", lambda *a, **k: None), \
                mock.patch.object(rv, "load_findings", lambda p: data), \
                mock.patch.object(rv, "decide_finding", lambda p, fid, act, t, by="": called.append(fid) or {"ok": True}):
            done = wr.auto_approve(NS(sid="rev", review_auto_approve=3), now=1.0)
        self.assertEqual(sorted(done), ["A", "C"])


if __name__ == "__main__":
    unittest.main()
