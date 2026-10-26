"""Bir günün (yerel saat) assistant turlarının token kullanımı, kategoriye göre (YALNIZ okur; hiçbir karara bağlanmaz).

Kategori: `subagent` (`<sid>/subagents/` altındaki dosyalar), `brain` (proje dizini adı bir değnekçi beynine ait:
`degnekci[_*]` ya da `.../steward[/stewards/<kimlik>]/workspace`), `project` (kalan ana oturumlar). Tur ayrıştırma ve `(message.id, requestId)`
tekilleştirmesi `session_usage` ile AYNI kuraldır (tekrarlarda alan başına en büyük değer); tur günü satırın `timestamp`
alanından (ISO, UTC) yerel güne çevrilir. Okunamayan dosya/satır sessizce atlanır, asla fırlatmaz."""
import glob
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from .session_usage import _from_row, _merge

CATEGORIES = ("project", "brain", "subagent")
FIELDS = ("in", "out", "cache_write", "cache_read")
# girdi x1 + çıktı x5 + önbellek yazımı x1.25 + önbellek okuma x0.1
WEIGHTS = {"in": 1.0, "out": 5.0, "cache_write": 1.25, "cache_read": 0.1}


def weighted(u: Dict[str, Any]) -> float:
    return sum(u.get(k, 0) * w for k, w in WEIGHTS.items())


def day_bounds(day: Optional[str]) -> Tuple[datetime, datetime]:
    """YYYY-MM-DD (boşsa bugün, yerel saat) -> [başlangıç, bitiş) saf (naive) yerel zamanlar. Geçersizse ValueError."""
    d = datetime.strptime(day, "%Y-%m-%d") if day else datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return d, d + timedelta(days=1)


def _local(ts: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def category_of(path: str, root: str) -> str:
    rel = os.path.relpath(path, root).split(os.sep)
    if "subagents" in rel[1:]:
        return "subagent"
    d = rel[0].lower()
    # beyin çalışma alanı: cwd kodlamasında `degnekci[_*]` ya da `...-steward[-stewards-<kimlik>]-workspace` (gerçek yerleşim)
    return "brain" if "degnekci" in d or ("-steward-" in d and d.endswith("-workspace")) else "project"


def _file_turns(path: str, lo: datetime, hi: datetime) -> Dict[Any, Tuple]:
    turns: Dict[Any, Tuple] = {}
    try:
        with open(path, "rb") as f:
            for line in f:
                if b'"usage"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                t = _local(r.get("timestamp")) if isinstance(r, dict) else None
                if t is None or not (lo <= t < hi):
                    continue
                got = _from_row(r)
                if got:
                    key, val = got
                    prev = turns.get(key)
                    turns[key] = _merge(prev, val) if prev else val
    except OSError:
        pass
    return turns


def collect_day(day: Optional[str] = None, root: Optional[str] = None) -> Dict[str, Any]:
    """{day, categories: {kat: {turns,in,out,cache_write,cache_read,weighted}}, total: {...}}. root = ~/.claude/projects."""
    root = root or os.path.expanduser("~/.claude/projects")
    lo, hi = day_bounds(day)
    cats = {c: {"turns": 0, **{k: 0 for k in FIELDS}} for c in CATEGORIES}
    paths = glob.glob(os.path.join(root, "*", "*.jsonl")) + glob.glob(os.path.join(root, "*", "*", "subagents", "*.jsonl"))
    seen: Dict[Tuple[str, Any], Tuple] = {}
    for p in sorted(paths):
        try:
            if datetime.fromtimestamp(os.path.getmtime(p)) < lo:
                continue                       # gün başlamadan beri dokunulmamış: o güne tur düşmez
            cat = category_of(p, root)
            for key, val in _file_turns(p, lo, hi).items():
                k = (cat, key)                 # aynı cevap dosyalar arası da tekrarlanabilir (kopya/resume): kategori içinde bir kez
                seen[k] = _merge(seen[k], val) if k in seen else val
        except Exception:
            continue
    for (cat, _key), (_fam, i, o, cw, cr) in seen.items():
        c = cats[cat]
        c["turns"] += 1
        c["in"] += i
        c["out"] += o
        c["cache_write"] += cw
        c["cache_read"] += cr
    total = {"turns": 0, **{k: 0 for k in FIELDS}}
    for c in cats.values():
        c["weighted"] = weighted(c)
        for k in ("turns", *FIELDS):
            total[k] += c[k]
    total["weighted"] = weighted(total)
    return {"day": lo.strftime("%Y-%m-%d"), "categories": cats, "total": total}
