"""TBD#383 (3): kilit alınamayınca `cops` komutları hata dökümü değil kısa ileti bassın."""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import cli  # noqa: E402
from claudeops.atomic_json import LockError  # noqa: E402


class CliLockError(unittest.TestCase):
    def test_close_label_periodic_print_short_message(self):
        busy = LockError("x.lock alınamadı")

        def boom(args):
            raise busy

        for argv in (["close", "ad"], ["label", "ad"], ["periodic", "list"]):
            parser = mock.Mock()
            parser.parse_args.return_value = mock.Mock(command=argv[0], func=boom)
            err = io.StringIO()
            with mock.patch.object(cli, "build_parser", return_value=parser), contextlib.redirect_stderr(err):
                rc = cli.main(argv)
            self.assertEqual(rc, 1, argv)
            self.assertIn("x.lock alınamadı", err.getvalue())
            self.assertEqual(len(err.getvalue().strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
