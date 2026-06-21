"""CLI giriş noktası — argparse + komut dağıtımı.

Her komut modülü bir `register(subparsers)` sunar (parser ekler + func atar).
Yeni komut devralındıkça commands/ altına eklenir + COMMANDS'e kaydedilir.
"""
from __future__ import annotations
import argparse
import sys

from . import __version__
from .commands import ls

# devralındıkça büyüyecek: handover, rc, guard, layout, needs_ho, ...
COMMANDS = [ls]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claudeops",
        description="claudeops (Python rewrite, TBD#8) — açık claude CLI session'larını yönet",
    )
    parser.add_argument("--version", action="version", version=f"claudeops-py {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<komut>")
    for mod in COMMANDS:
        mod.register(sub)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
