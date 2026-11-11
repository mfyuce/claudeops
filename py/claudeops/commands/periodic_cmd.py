"""`periodic` — periyodik işler (servis içi zamanlayıcı; crontab DEĞİL). Ayrıntı: `claudeops/periodic.py`.

Kullanım:
  py/cops periodic                       # iş listesi: açık/kapalı, zamanlama, son sonuç
  py/cops periodic run chat_backup       # PLAN (yazmaz); --apply gerçekten çalıştırır
  py/cops periodic set chat_backup enabled=on schedule="30 3 * * *"
  py/cops periodic add yedek_kontrol --kind command command="du -sh ~/.claude" schedule="0 9 * * *"
  py/cops periodic add ozet --kind prompt prompt="Dünkü commit'leri özetle" cwd=~/work/projects/tmp/claudeops schedule="0 8 * * 1-5"
  py/cops periodic rm yedek_kontrol      # yalnız kullanıcı tanımlı işler
Yeni eklenen iş KAPALI açılır; `set <id> enabled=on` ile açılır. Servis çalışıyorsa değişiklik 60 sn içinde alınır.
"""
from __future__ import annotations

import datetime
import json

from .. import periodic as P


def register(sub):
    p = sub.add_parser("periodic", help="periyodik işler: liste/ekle/ayarla/çalıştır (servis içi, crontab değil)")
    sp = p.add_subparsers(dest="pcmd")
    sp.add_parser("list")
    r = sp.add_parser("run")
    r.add_argument("id")
    r.add_argument("--apply", action="store_true")
    s = sp.add_parser("set")
    s.add_argument("id")
    s.add_argument("kv", nargs="+", metavar="ALAN=DEĞER")
    a = sp.add_parser("add")
    a.add_argument("id")
    a.add_argument("--kind", default="command", choices=["command", "prompt"])
    a.add_argument("kv", nargs="*", metavar="ALAN=DEĞER")
    d = sp.add_parser("rm")
    d.add_argument("id")
    p.set_defaults(func=run)


def _kv(items):
    out = {}
    for it in items:
        if "=" not in it:
            raise ValueError(f"ALAN=DEĞER bekleniyordu: {it}")
        k, v = it.split("=", 1)
        if v[:1] in "{[":                       # sözlük/liste (örn. remote_pull={"yuhem":"shell_yuhem"}) JSON
            try:
                out[k] = json.loads(v)
                continue
            except ValueError:
                raise ValueError(f"{k}: geçersiz JSON")
        out[k] = int(v) if v.isdigit() and k in ("interval_hours", "timeout_s", "max_file_mb", "max_repo_mb") else v
    return out


def _fmt(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "-"


def run(args) -> int:
    cmd = getattr(args, "pcmd", None) or "list"
    try:
        if cmd == "list":
            ov = P.overview()
            print(f"{'iş':16} {'açık':5} {'zamanlama':22} {'son başlangıç':14} {'sonuç'}")
            for n, j in ov["jobs"].items():
                c, st = j["config"], j["state"]
                sched = c.get("schedule") or (f"günlük {c.get('start')}" if float(c.get("interval_hours") or 24) >= 24 else f"{c.get('interval_hours')} saatte bir")
                res = "-" if "last_ok" not in st else ("ok " if st["last_ok"] else "HATA ") + str(st.get("last_msg", ""))[:70]
                print(f"{n:16} {str(c.get('enabled')):5} {sched:22} {_fmt(st.get('last_start')):14} {res}")
            return 0
        if cmd == "run":
            print(json.dumps(P.run_job(args.id, apply=args.apply), ensure_ascii=False, indent=2))
            return 0
        if cmd == "set":
            print(json.dumps(P.set_config(args.id, _kv(args.kv)), ensure_ascii=False, indent=2))
            return 0
        if cmd == "add":
            f = _kv(args.kv)
            f["kind"] = args.kind
            print(json.dumps(P.add_custom(args.id, f), ensure_ascii=False, indent=2))
            return 0
        if cmd == "rm":
            ok = P.remove_custom(args.id)
            print("silindi" if ok else "yok ya da yerleşik")
            return 0 if ok else 1
    except (KeyError, ValueError) as e:
        print(f"hata: {e}")
        return 1
    return 1
