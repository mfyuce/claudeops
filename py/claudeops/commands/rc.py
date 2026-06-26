"""`rc` — session'ları öldür ve yeniden başlat (Faz 2 handover için).

Kullanım:
  # SABİT İSİM (varsayılan — --suffix verme): girdideki isim aynen (hc58→hc58)
  py/cops rc hc58 hcr58 mo58 --new --kill-first \\
    --model='claude-sonnet-4-6' --permission-mode=auto --effort=max --one-by-one

  # SUFFIX-BUMP (isim bumplanır hc53→hc54): --suffix=YENİ ekle
  py/cops rc hc53 hcr53 mo53 --suffix=54 --new --kill-first \\
    --model='claude-sonnet-4-6' --permission-mode=auto --effort=max --one-by-one

  (--prompt verilmez → session'lar boş/idle başlar)

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
from ..roster import read_models, roster_by_name, read_suffix
from ..spawn import spawn_session, detect_display

_NAME_RE = re.compile(r"^([a-z]+)(\d+)$")


def register(sub):
    p = sub.add_parser("rc", help="session'ları öldür ve yeniden aç (Faz 2 handover)")
    p.add_argument("names", nargs="+", metavar="NAME",
                   help="eski suffix'li isimler (ör. hc53 hcr53) veya base (ör. hc hcr)")
    p.add_argument("--suffix", type=int, default=None, metavar="N",
                   help="yeni suffix (ör. 54) → isim bumplanır (hc58→hc54). "
                        "VERİLMEZSE: girdideki isim AYNEN kullanılır (hc58→hc58, suffix bump yok).")
    p.add_argument("--new", dest="fresh", action="store_true",
                   help="--new ile başlat (resume değil)")
    p.add_argument("--kill-first", action="store_true",
                   help="spawn'dan önce mevcut session'ı öldür")
    p.add_argument("--model", default=None,
                   help="model override (varsayılan: models.tsv)")
    p.add_argument("--permission-mode", default="auto")
    p.add_argument("--effort", default="max")
    p.add_argument("--prompt", default=None, metavar="MSG",
                   help="opsiyonel ilk mesaj --new ile (varsayılan YOK → boş/idle başlar)")
    p.add_argument("--one-by-one", action="store_true",
                   help="proc görünene kadar bekle, sonra sonraki (rate-limit önlemi)")
    p.add_argument("--proc-wait", type=float, default=15.0, metavar="SEC",
                   help="--one-by-one proc bekleme süresi (varsayılan: 15s)")
    p.add_argument("--grace", type=float, default=KILL_GRACE_SECONDS, metavar="SEC",
                   help=f"SIGKILL grace süresi (varsayılan: {KILL_GRACE_SECONDS:.0f}s)")
    p.add_argument("--kill-settle", type=float, default=3.0, metavar="SEC",
                   help="kill sonrası bridge deregister için bekleme (varsayılan: 3.0s)")
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


def _run_inner(args, display, models, roster, cur_suffix) -> int:
    errors = 0

    for full_name in args.names:
        # base + optional old suffix
        m = _NAME_RE.match(full_name)
        if m:
            base, old_sfx = m.group(1), m.group(2)
        elif re.match(r"^[a-z]+$", full_name):
            base, old_sfx = full_name, None
        else:
            print(f"  {full_name}: isim parse edilemedi")
            errors += 1
            continue

        # co + ulaksec'e asla dokunma
        if base in HO_EXCLUDE_BASES:
            print(f"  {base}: ho-exclude (co/ulaksec'e dokunma)")
            errors += 1
            continue

        # İsim hesabı:
        #   --suffix verilmiş → bump (hc58 → hc{suffix})
        #   --suffix yok + girdide suffix var → girdiyi AYNEN kullan (hc58 → hc58)
        #   --suffix yok + base-only (hc) → mevcut suffix dosyasından tamamla (hc → hc58)
        if args.suffix is not None:
            new_name = f"{base}{args.suffix}"
        elif old_sfx is not None:
            new_name = full_name
        elif cur_suffix is not None:
            new_name = f"{base}{cur_suffix}"
        else:
            new_name = base

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
                        if result != "already_dead" and args.kill_settle > 0:
                            time.sleep(args.kill_settle)
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

    # --suffix yoksa (sabit-isim modu): base-only girdileri tamamlamak için mevcut suffix
    # (guard ile aynı kaynak). --suffix varsa bump → mevcut değere gerek yok.
    cur_suffix = read_suffix() if args.suffix is None else None

    # guard.lock: kill-first sırasında guard cron ile DUP spawn önle
    try:
        with guard_lock(timeout=5.0):
            errors = _run_inner(args, display, models, roster, cur_suffix)
    except TimeoutError as e:
        print(f"✗ guard.lock alınamadı: {e}", file=sys.stderr)
        return 1

    # Suffix dosyasını güncelle — guard yeni nesli bilsin.
    # --suffix yoksa (sabit isim): isim/suffix değişmedi → dosyaya DOKUNMA, guard mevcut
    # değerle devam etsin (bump yok = bu modun amacı).
    if not args.dry_run and args.suffix is not None:
        from ..paths import SUFFIX_FILE
        import os
        os.makedirs(os.path.dirname(SUFFIX_FILE), exist_ok=True)
        with open(SUFFIX_FILE, "w") as f:
            f.write(str(args.suffix))
        print(f"  suffix → {args.suffix}")

    return errors
