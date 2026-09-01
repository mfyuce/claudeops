"""`rc` — session'ları öldür ve yeniden başlat (Faz 2 handover için).

Kullanım:
  # İsimler base-name (suffix yok): hc → hc (aynen yeniden açılır)
  py/cops rc hc hcr mo --new --kill-first \\
    --model='claude-sonnet-4-6' --permission-mode=auto --one-by-one
  (--effort verilmezse varsayılan artık 'high' — max/xhigh değil, bkz. handover.default_handover_effort)

  (--prompt verilmez → session'lar boş/idle başlar)
  (Geçiş: hc58 gibi suffix'li girdi de kabul edilir → base'e (hc) indirgenir.)

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
from ..handover import ancestor_pids, default_handover_effort
from ..kill import kill_session_and_parent, KILL_GRACE_SECONDS
from ..needs_ho import repo_baseline_set
from ..providers import get_provider
from ..roster import read_models, roster_by_name
from ..spawn import spawn_session, detect_display

# Geçiş savunması: suffix'li girdiyi (hc58) base'e (hc) indirger. Saf base de eşleşir.
_NAME_RE = re.compile(r"^([a-z]+)\d*(?:_\d+)*$")


def register(sub):
    p = sub.add_parser("rc", help="session'ları öldür ve yeniden aç (Faz 2 handover)")
    p.add_argument("names", nargs="+", metavar="NAME",
                   help="base isimler (ör. hc hcr mo). Suffix'li girdi (hc58) de kabul → base'e indirgenir.")
    p.add_argument("--new", dest="fresh", action="store_true",
                   help="--new ile başlat (resume değil)")
    p.add_argument("--kill-first", action="store_true",
                   help="spawn'dan önce mevcut session'ı öldür")
    p.add_argument("--model", default=None,
                   help="model override (varsayılan: models.tsv)")
    p.add_argument("--permission-mode", default=None,
                   help="permission-mode override (varsayılan: provider'ın ilk seçeneği, ör. 'auto')")
    p.add_argument("--effort", default=None,
                   help="effort override (varsayılan: 'high' — provider'ın listesinde yoksa en yüksek seviye)")
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


def _run_inner(args, display, models, roster) -> int:
    errors = 0

    for full_name in args.names:
        # Girdiyi base'e indirge (hc58→hc, hc→hc). Suffix yok → isim = base.
        m = _NAME_RE.match(full_name)
        if not m:
            print(f"  {full_name}: isim parse edilemedi")
            errors += 1
            continue
        base = m.group(1)

        new_name = base   # suffix yok: session adı = base

        entry = roster.get(base)
        if not entry:
            print(f"  {base}: roster.tsv'de bulunamadı")
            errors += 1
            continue
        cwd = entry.cwd
        # entry.cli spawn.py claude'a mı agy'ye mi göre komut kuracağını belirler — model
        # fallback'i de buna göre seçilmeli (agy'nin "claude-sonnet-4-6" id'si claude'unkiyle
        # AYNI YAZILIR ama İKİ AYRI CLI'nın kendi model listesindendir, tesadüfen çakışıyor —
        # bir sabitte birleştirmeye kalkışma).
        provider = get_provider(entry.cli)
        model = args.model or models.get(base) or provider.model_choices()[0]
        permission_mode = args.permission_mode or provider.permission_modes()[0]
        effort = args.effort or default_handover_effort(provider)

        # 1. Kill — tam isim VEYA base ile eşleşenleri öldür (suffix verilmeden çağrıda DUP önlemi).
        # Self-koruma: bu komutun içinden çalıştığı claude session'ı (ata-proc) asla öldürülmez.
        if args.kill_first:
            all_sessions = find_sessions(measure_cpu=False)
            procs = [s for s in all_sessions if s.name == full_name or s.base == base]
            protected = ancestor_pids()
            self_hits = [s for s in procs if s.pid in protected]
            if self_hits:
                for s in self_hits:
                    print(f"  ⊘ self: {s.name} (pid={s.pid}) — bu komut onun içinden çalışıyor, kill atlandı")
                procs = [s for s in procs if s.pid not in protected]
            if procs:
                for s in procs:
                    if args.dry_run:
                        print(f"  [dry-run] kill {s.name} pid={s.pid}")
                    else:
                        print(f"  kill {s.name} pid={s.pid}...", end="", flush=True)
                        result = kill_session_and_parent(s.pid, grace=args.grace, name=s.name)
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
            permission_mode=permission_mode,
            effort=effort,
            force_new=args.fresh,
            prompt=args.prompt,
            dry_run=args.dry_run,
            cli=entry.cli,
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

    return errors
