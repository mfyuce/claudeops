"""TBD#367 (sahip, 26 Kas: "ikisi de göndermesin, kapalı yön"): otomatik enjeksiyon öncesi maske denetimi parola
durumu BİLİNMİYORKEN (`pane_is_masked_input` None: pane'in tty'si okunamadı, tmux cevap vermedi, oturum gitti)
gönderiyordu. Python'da bu denetimi yapan tek otomatik gönderici `web._context` (`/context` komutu): bilinmeyen
durumda göndermez, "gönderildi" de saymaz; nedeni `mask_unknown` olarak döner."""
import unittest
from types import SimpleNamespace
from unittest import mock

from claudeops.commands import web


class ContextMaskGuardTests(unittest.TestCase):
    def run_context(self, masked):
        sent = []
        provider = mock.Mock()
        provider.context_command.return_value = "/context"
        provider.input_settle_delay.return_value = 0.0
        provider.parse_context_text.return_value = [{"label": "x"}]
        provider.context_needs_dismiss.return_value = False
        s = SimpleNamespace(name="k", pid=123, cli="claude")
        with mock.patch.object(web, "_find_running_for_action", lambda n: ("exact", [s])), \
                mock.patch.object(web, "_fleet_status", lambda: {}), \
                mock.patch.object(web, "get_provider", lambda cli: provider), \
                mock.patch.object(web, "is_tmux_backed", lambda pid: True), \
                mock.patch.object(web, "_is_busy_cached", lambda s: False), \
                mock.patch.object(web, "pane_is_masked_input", lambda n: masked), \
                mock.patch.object(web, "tmux_send_keys", lambda *a, **kw: sent.append(a) or True), \
                mock.patch.object(web, "tmux_capture", lambda n: "ekran"), \
                mock.patch.object(web.time, "sleep", lambda s: None):
            return web._context("k"), sent

    def test_unknown_mask_state_sends_nothing_and_says_why(self):
        res, sent = self.run_context(None)
        self.assertEqual(sent, [])
        self.assertEqual(res, {"ok": True, "available": False, "reason": "mask_unknown"})

    def test_masked_still_refused(self):
        res, sent = self.run_context(True)
        self.assertEqual(sent, [])
        self.assertEqual(res["reason"], "masked")

    def test_known_unmasked_pane_gets_the_command(self):
        res, sent = self.run_context(False)
        self.assertEqual(sent, [("k", "/context")])
        self.assertTrue(res["available"])


if __name__ == "__main__":
    unittest.main()
