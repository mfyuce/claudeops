"""Son modül: kancanın topladığı sonucu rapor dosyasına yazar."""
import unittest

import parity_hook


class TestZReport(unittest.TestCase):
    def test_write(self):
        parity_hook.write_report()
