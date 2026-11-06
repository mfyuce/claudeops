"""`kill` — session'ı nazikçe kapat (SIGTERM + 8s grace + sadece canlıysa SIGKILL)."""
from __future__ import annotations
from ..discovery import find_by_name
from ..kill import kill_session_and_parent
from . import mcp_queue


def register(sub):
    p = sub.add_parser("kill", help="session'ı nazikçe kapat (SIGTERM + 8s grace)")
    p.add_argument("names", nargs="+", metavar="NAME",
                   help="session adları (ör. hc54 sase54)")
    p.add_argument("--grace", type=float, default=8.0, metavar="SEC",
                   help="SIGKILL öncesi bekleme sn (varsayılan: 8)")
    p.add_argument("--dry-run", action="store_true",
                   help="sadece göster, öldürme")
    p.add_argument("--force", action="store_true",
                   help="ho'suz doğrudan öldür (varsayılan: panel /api/stop; kayıtlı proje oturumu önce devirle kapanır)")
    p.add_argument("--port", type=int, default=mcp_queue.DEFAULT_PORT, help="panel portu (ho yolu)")
    p.set_defaults(func=run)


def _via_panel(port: int, name: str):
    """Panel `/api/stop` (ho kuralı: act + kayıtlı proje oturumu önce devir). Panel yanıt vermezse None (doğrudan kapatmaya düşer)."""
    try:
        return mcp_queue._api(port, "POST", "/api/stop", {"name": name})
    except mcp_queue.ApiError as e:
        if str(e).startswith("cannot reach"):
            return None
        return {"ok": False, "error": str(e)}


def run(args) -> int:
    errors = 0
    for name in args.names:
        if not args.dry_run and not args.force:
            res = _via_panel(args.port, name)
            if res is not None:
                if res.get("ok"):
                    print(f"  {name}: panel üzerinden durduruldu" + (f" ({res['note']})" if res.get("note") else ""))
                else:
                    print(f"  {name}: {res.get('error')}")
                    errors += 1
                continue
            print(f"  {name}: panel yanıt vermedi, doğrudan kapatılıyor (ho'suz)")
        procs = find_by_name(name, measure_cpu=False)
        if not procs:
            print(f"  {name}: proc bulunamadı")
            errors += 1
            continue
        for s in procs:
            if args.dry_run:
                print(f"  [dry-run] {name} pid={s.pid} — öldürülmeyecek")
                continue
            print(f"  {name} pid={s.pid} → SIGTERM + {args.grace:.0f}s grace...",
                  end="", flush=True)
            result = kill_session_and_parent(s.pid, grace=args.grace, name=s.name)
            print(f" {result}")
    return errors
