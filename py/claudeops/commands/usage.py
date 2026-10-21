"""`usage` — claude oturumlarının KÜMÜLATİF token harcaması (ana oturum + alt ajanlar; transkriptten, yalnız okur).

Kullanım:
  py/cops usage                  # en çok harcayan 15 çalışan claude oturumu
  py/cops usage ad1 ad2 --json   # yalnız bu oturumlar, JSON
  py/cops usage --top 30

Sütunlar: IN/OUT/CW (ana oturumun girdi/çıktı/önbellek yazımı), CR (önbellek okuma), TUR, ALT (alt ajan sayısı) ve
alt ajanların IN+OUT+CW toplamı ve ayrıca CR'si; sıralama ana + alt ajan dört sayının toplamıdır. Panel gerekmez, hiçbir oturuma dokunmaz. Yalnız claude: codex/agy/copilot kullanımı
BİLİNMİYOR (kapsam dışı). Aynı API cevabının bölünmüş satırları tekilleştirilir (bkz. `session_usage.py`)."""
from __future__ import annotations
import json

from ..discovery import find_sessions
from ..providers.claude_provider import jsonl_path_for
from ..session_usage import fmt_tokens, usage_for_path


def register(sub):
    p = sub.add_parser("usage", help="oturum başına kümülatif token harcaması (ana + alt ajanlar; yalnız okur)")
    p.add_argument("names", nargs="*", metavar="ad", help="yalnız bu oturumlar (boşsa en çok harcayan --top tane)")
    p.add_argument("--json", action="store_true", help="tablo yerine JSON yaz")
    p.add_argument("--top", type=int, default=15, metavar="N", help="isim verilmezse en çok harcayan N oturum (varsayılan 15)")
    p.set_defaults(func=run)


def _weight(u: dict) -> int:
    """Sıralama ölçütü: ana + alt ajan girdi/çıktı/önbellek yazımı + önbellek okuma."""
    s = u["subagents"]
    return sum(u[k] + s[k] for k in ("in", "out", "cache_write", "cache_read"))


def collect(names):
    """[(ad, kullanım)] — çalışan claude oturumları (bilinmeyen/okunamayan atlanır)."""
    rows = []
    for s in find_sessions(measure_cpu=False):
        if s.cli != "claude" or (names and s.name not in names):
            continue
        try:
            path = jsonl_path_for(s.cwd, s.sid)
        except Exception:
            path = None
        u = usage_for_path(path) if path else None
        if u:
            rows.append((s.name, u))
    return rows


def render(rows) -> str:
    head = f"{'AD':<18}{'IN':>9}{'OUT':>9}{'CW':>9}{'CR':>9}{'TUR':>7}{'ALT':>5}{'ALT-IN+OUT+CW':>15}{'ALT-CR':>9}"
    out = [head, "-" * len(head)]
    for name, u in rows:
        s = u["subagents"]
        sub_total = s["in"] + s["out"] + s["cache_write"]
        out.append(f"{name[:17]:<18}{fmt_tokens(u['in']):>9}{fmt_tokens(u['out']):>9}{fmt_tokens(u['cache_write']):>9}"
                   f"{fmt_tokens(u['cache_read']):>9}{u['turns']:>7}{s['n']:>5}{fmt_tokens(sub_total):>15}{fmt_tokens(s['cache_read']):>9}")
    out.append(f"\n  {len(rows)} oturum (yalnız claude; diğer CLI'ların kullanımı bilinmiyor)")
    return "\n".join(out)


def run(args) -> int:
    rows = collect(set(args.names))
    if not args.names:
        rows = sorted(rows, key=lambda r: -_weight(r[1]))[:max(1, args.top)]
    else:
        rows = sorted(rows, key=lambda r: -_weight(r[1]))
    if args.json:
        print(json.dumps({name: u for name, u in rows}, ensure_ascii=False, indent=2))
    else:
        print(render(rows))
    return 0
