"""CLI giriş noktası — argparse + komut dağıtımı.

Her komut modülü bir `register(subparsers)` sunar (parser ekler + func atar).
Yeni komut devralındıkça commands/ altına eklenir + COMMANDS'e kaydedilir.
"""
from __future__ import annotations
import argparse
import sys

from . import __version__
from .commands import ls, kill, close, config, guard, rc, handover, stuck, layout, web, service, mcp_queue, migrate_instances, watch, winact, searxng, cache, usage, routing, steward, mcp_steward, ucli_push, cleanup_backups, ucli_cost_cmd, memory_backup, periodic_cmd, db_cmd, check, test_cmd, label_cmd

# devralındıkça büyüyecek: handover, rc, guard, layout, needs_ho, ...
COMMANDS = [ls, kill, close, config, guard, rc, handover, stuck, layout, web, service, mcp_queue, migrate_instances, watch, winact, searxng, cache, usage, routing, steward, mcp_steward, ucli_push, cleanup_backups, ucli_cost_cmd, memory_backup, periodic_cmd, db_cmd, check, test_cmd, label_cmd]


def build_parser(argv=None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claudeops",
        description="claudeops (Python rewrite, TBD#8) — açık claude CLI session'larını yönet",
    )
    parser.add_argument("--version", action="version", version=f"claudeops-py {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<komut>")
    for mod in COMMANDS:
        mod.register(sub)
    _register_extension_commands(sub, argv)
    return parser


def _register_extension_commands(sub, argv) -> None:
    """K11: eklenti komutları (`extensions.register_command`). Eklenti YALNIZ ilk argüman çekirdek komutu değilse yüklenir
    (çekirdek komutlarının açılışı eklenti import'u ödemez); çekirdek adlarını ezemez."""
    first = next((a for a in (argv if argv is not None else sys.argv[1:]) if not a.startswith("-")), "")
    if first in sub.choices or not first:
        return
    from . import extensions
    extensions.load()
    for name, ent in extensions.commands().items():
        if name in sub.choices:
            continue
        p = sub.add_parser(name, help=ent["help"] or None, add_help=False)
        p.add_argument("rest", nargs=argparse.REMAINDER)
        p.set_defaults(func=lambda a, _fn=ent["fn"]: _fn(list(a.rest)))


def main(argv=None) -> int:
    parser = build_parser(argv)
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
