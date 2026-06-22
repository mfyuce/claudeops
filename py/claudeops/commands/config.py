"""`config` — ~/.claude.json doğrula (bozuksa resume-hang olur)."""
from __future__ import annotations
from ..config import validate_config


def register(sub):
    p = sub.add_parser("config", help="~/.claude.json doğrula (bozuksa resume-hang eder)")
    p.set_defaults(func=run)


def run(args) -> int:
    ok, msg = validate_config()
    status = "✓" if ok else "✗"
    print(f"{status} {msg}")
    return 0 if ok else 1
