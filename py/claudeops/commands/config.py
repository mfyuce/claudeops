"""`config` — ~/.claude.json doğrula (bozuksa resume-hang olur)."""
from __future__ import annotations
from ..config import validate_config


def register(sub):
    p = sub.add_parser("config", help="~/.claude.json doğrula (bozuksa resume-hang eder)")
    p.set_defaults(func=run)


_MSG = {
    "valid": "~/.claude.json geçerli",
    "not_found": "~/.claude.json bulunamadı",
    "corrupt": "~/.claude.json BOZUK ({detail}) — ~/.claude/backups/'tan geri yükle",
    "unreadable": "~/.claude.json okunamadı: {detail}",
}


def run(args) -> int:
    ok, code, detail = validate_config()
    status = "✓" if ok else "✗"
    print(f"{status} {_MSG[code].format(detail=detail)}")
    return 0 if ok else 1
