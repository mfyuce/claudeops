"""`rc` — session'ları öldür ve yeniden başlat (Faz 2 handover için).

Kullanım:
  py/cops rc hc53 hcr53 mo53 --suffix=54 --new --kill-first \\
    --model='claude-sonnet-4-6' --permission-mode=auto --effort=max \\
    --prompt='devam' --one-by-one

Bash claudeops'taki `rc` komutunun doğrudan karşılığı.
Throttle: --one-by-one proc görünene kadar bekler → rate-limit olmaz
([[mass-faz1-ratelimit-stuck]] dersi).
"""
from __future__ import annotations
import re
import sys
import time
from typing import Optional

from ..discovery import find_by_name, find_sessions
from ..guard import guard_lock
from ..handover import HO_EXCLUDE_BASES
from ..kill import kill_session, KILL_GRACE_SECONDS
from ..needs_ho import repo_baseline_set
from ..roster import read_models, roster_by_name
from ..spawn import spawn_session, detect_display

_NAME_RE = re.compile(r"^([a-z]+)(\d+)$")


def register(sub):
    p = sub.add_parser("rc", help="session'ları öldür ve yeniden aç (Faz 2 handover)")
    p.add_argument("names", nargs="+", metavar="NAME",
                   help="eski suffix'li isimler (ör. hc53 hcr53) veya base (ör. hc hcr)")
    p.add_argument("--suffix", type=int, required=True, metavar="N",
                   help="yeni suffix (ör. 54)")
    p.add_argument("--new", dest="fresh", action="store_true",
                   help="--new ile başlat (resume değil)")
    p.add_argument("--kill-first", action="store_true",
                   help="spawn'dan önce mevcut session'ı öldür")
    p.add_argument("--model", default=None,
                   help="model override (varsayılan: models.tsv)")
    p.add_argument("--permission-mode", default="auto")
    p.add_argument("--effort", default="max")
    p.add_argument("--prompt", default=None, metavar="MSG",
                   help="ilk mesaj --new ile (ör. 'devam')")
    p.add_argument("--one-by-one", action="store_true",
                   help="proc görünene kadar bekle, sonra sonraki (rate-limit önlemi)")
    p.add_argument("--proc-wait", type=float, default=15.0, metavar="SEC",
                   help="--one-by-one proc bekleme süresi (varsayılan: 15s)")
    p.add_argument("--grace", type=float, default=KILL_GRACE_SECONDS, metavar="SEC",
                   help=f"SIGKILL grace süresi (varsayılan: {KILL_GRACE_SECONDS:.0f}s)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--display", default=None)
    p.set_defaults(func=run)


def _wait_proc(name: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if find_by_name(name, measure_cpu=False):
            return True
        time.sleep(1.0)
    return False


def _run_inner(args, display, models, roster) -> int:
    errors = 0

    for full_name in args.names:
        # base + optional old suffix
        m = _NAME_RE.match(full_name)
        if m:
            base, _old_sfx = m.group(1), m.group(2)
        elif re.match(r"^[a-z]+$", full_name):
            base = full_name
        else:
            print(f"  {full_name}: isim parse edilemedi")
            errors += 1
            continue

        # co + ulaksec'e asla dokunma
        if base in HO_EXCLUDE_BASES:
            print(f"  {base}: ho-exclude (co/ulaksec'e dokunma)")
            errors += 1
            continue

        new_name = f"{base}{args.suffix}"
        model = args.model or models.get(base, "claude-sonnet-4-6")

        entry = roster.get(base)
        if not entry:
            print(f"  {base}: roster.tsv'de bulunamadı")
            errors += 1
            continue
        cwd = entry.cwd

        # 1. Kill — tam isim VEYA base ile eşleşenleri öldür (suffix verilmeden çağrıda DUP önlemi)
        if args.kill_first:
            all_sessions = find_sessions(measure_cpu=False)
            procs = [s for s in all_sessions if s.name == full_name or s.base == base]
            if procs:
                for s in procs:
                    if args.dry_run:
                        print(f"  [dry-run] kill {s.name} pid={s.pid}")
                    else:
                        print(f"  kill {s.name} pid={s.pid}...", end="", flush=True)
                        result = kill_session(s.pid, grace=args.grace)
                        print(f" {result}")
            else:
                print(f"  {full_name}: zaten çalışmıyor")

        # 2. Spawn
        kind = spawn_session(
            name=new_name,
            cwd=cwd,
            model=model,
            display=display,
            permission_mode=args.permission_mode,
            effort=args.effort,
            force_new=args.fresh,
            prompt=args.prompt,
            dry_run=args.dry_run,
        )
        print(f"  {new_name} → {kind}")

        # Baseline: respawn sonrası HEAD'i kaydet → needs_ho doğru çalışsın (bash _repo_baseline_set)
        if not args.dry_run:
            try:
                repo_baseline_set(cwd)
            except Exception:
                pass

        # 3. One-by-one: proc görünene dek bekle
        if args.one_by_one and not args.dry_run:
            found = _wait_proc(new_name, timeout=args.proc_wait)
            if not found:
                print(f"  ⚠ {new_name} proc {args.proc_wait:.0f}s içinde görünmedi")
                errors += 1

    return errors


def run(args) -> int:
    display = args.display or detect_display()
    models = read_models()
    roster = roster_by_name()

    # guard.lock: kill-first sırasında guard cron ile DUP spawn önle
    try:
        with guard_lock(timeout=5.0):
            errors = _run_inner(args, display, models, roster)
    except TimeoutError as e:
        print(f"✗ guard.lock alınamadı: {e}", file=sys.stderr)
        return 1

    # Suffix dosyasını güncelle — guard yeni nesli bilsin
    if not args.dry_run:
        from ..paths import SUFFIX_FILE
        import os
        os.makedirs(os.path.dirname(SUFFIX_FILE), exist_ok=True)
        with open(SUFFIX_FILE, "w") as f:
            f.write(str(args.suffix))
        print(f"  suffix → {args.suffix}")

    return errors
