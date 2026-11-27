"""Salt okunur SQLite URI'si. Yaprak modül."""
from __future__ import annotations

import os
from urllib.parse import quote


def ro_sqlite_uri(path: str) -> str:
    """`path`i salt okunur açan SQLite URI'si. Yol kaçışlanır: ham `#`/`?`/`%` başka bir dosya açtırıyor, `mode=ro`yu
    düşürüp boş dosya yarattırıyordu."""
    quoted = quote(os.fsencode(path))
    prefix = "//" if quoted.startswith("//") else ""      # `//x` yolu URI'de sunucu adı sanılmasın
    return f"file:{prefix}{quoted}?mode=ro"
