"""`handover` — Faz 1 wrap-up (eski session kapat, mesajla yeniden aç).

Kullanım:
  py/cops handover [--dry-run]                    # batch: tüm fleet (self hariç)
  py/cops handover --batch-size=5 --batch-delay=30
  py/cops handover --message='özel mesaj'
  py/cops handover --message-file=/path/to/msg.txt
  py/cops handover cops20260824                    # TEK isim: roster gerekmez (proc-scan),
                                                     # needs_ho BYPASS (self yine korunur)
  py/cops handover co --lang=en                     # isimle hedeflenince co dahi mümkün

İsimler base-name (suffix yok). İsim VERİLMEZSE tüm aktif fleet hedef (self hariç).
İsim VERİLİRSE roster'da olmasa da (proc-scan'den bulunur) çalışır; self yine atlanır.
Faz 2 için: py/cops rc hc hcr ... --new --kill-first --one-by-one
Faz 3 için: claudeops layout grid 4 --claude-only --pin=...
"""
from __future__ import annotations
import os
import sys
from typing import Optional
from ..guard import guard_lock
from ..handover import handover_faz1, HANDOVER_MSG_DEFAULT, HANDOVER_MSG_DEFAULT_EN
from ..spawn import detect_display

# TODO-p / [[reboot-no-handover]]: taze reboot üstüne elle handover = boot-recovery
# zaten toparlarken race + post-boot artefakt + context kaybı (2026-06-18 mo50 olayı).
REBOOT_GUARD_SECONDS = 1800.0  # 30 dk


def _seconds_since_boot() -> Optional[float]:
    """`/proc/uptime`'ın ilk alanı — `uptime -s`'i parse etmekten daha ucuz/sağlam
    (locale/tarih-format riski yok, subprocess yok)."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def register(sub):
    p = sub.add_parser("handover", help="Faz 1: wrap-up mesajı gönder (eski kapat, yeni aç)")
    p.add_argument("names", nargs="*", metavar="NAME",
                   help="opsiyonel: belirli isim(ler) — verilmezse tüm fleet (batch). "
                        "Verilirse roster gerekmez, needs_ho bypass (self yine korunur).")
    p.add_argument("--lang", choices=["tr", "en"], default="tr",
                   help="varsayılan mesaj dili (--message/--message-file verilmemişse, varsayılan: tr)")
    p.add_argument("--message", default=None, metavar="MSG",
                   help="wrap-up mesajı (varsayılan: HANDOVER_MSG_DEFAULT, --lang=en ile İngilizce)")
    p.add_argument("--message-file", default=None, metavar="FILE",
                   help="mesajı dosyadan oku")
    p.add_argument("--batch-size", type=int, default=5, metavar="N",
                   help="grup büyüklüğü — rate-limit önlemi (varsayılan: 5)")
    p.add_argument("--batch-delay", type=float, default=30.0, metavar="SEC",
                   help="gruplar arası bekleme sn (varsayılan: 30)")
    p.add_argument("--proc-wait", type=float, default=15.0, metavar="SEC",
                   help="proc görünme bekleme sn (varsayılan: 15)")
    p.add_argument("--grace", type=float, default=10.0, metavar="SEC",
                   help="kill grace süresi (varsayılan: 10)")
    p.add_argument("--kill-settle", type=float, default=3.0, metavar="SEC",
                   help="kill SONRASI respawn ÖNCESİ bekleme — server eski RC ismini "
                        "bıraksın (aynı-isim bridge çakışması/inactive flicker önlemi, "
                        "varsayılan: 3)")
    p.add_argument("--display", default=None)
    p.add_argument("--dry-run", action="store_true",
                   help="sadece göster, gerçek kill/spawn yapma")
    p.add_argument("--force", action="store_true",
                   help="taze-reboot uyarısını (≤30dk) baypas et")
    p.set_defaults(func=run)


def run(args) -> int:
    uptime = _seconds_since_boot()
    if uptime is not None and uptime < REBOOT_GUARD_SECONDS and not args.force:
        mins = uptime / 60.0
        print(f"⚠ makine ~{mins:.0f} dk önce reboot oldu.", file=sys.stderr)
        print("  boot-recovery/cron zaten en son hâlden toparlıyor olabilir — taze", file=sys.stderr)
        print("  reboot üstüne elle handover post-boot artefakt + race + context", file=sys.stderr)
        print("  kaybı riski taşır ([[reboot-no-handover]]). Baypas: --force", file=sys.stderr)
        return 1

    # Mesajı belirle
    if args.message_file:
        try:
            with open(args.message_file) as f:
                message = f.read()
        except Exception as e:
            print(f"✗ mesaj dosyası okunamadı: {e}", file=sys.stderr)
            return 1
    elif args.message:
        message = args.message
    else:
        message = HANDOVER_MSG_DEFAULT_EN if args.lang == "en" else HANDOVER_MSG_DEFAULT

    display = args.display or detect_display()

    print(f"=== handover faz1{' (dry-run)' if args.dry_run else ''} ===")
    if args.names:
        print(f"  hedef: {', '.join(args.names)}  (isimle seçildi — needs_ho bypass, self korunur)")
    else:
        print(f"  batch={args.batch_size}, delay={args.batch_delay:.0f}s, "
              f"display={display}")
    print()

    # guard.lock: guard cron'u dışarıda tut (Faz1 kill sırasında dup spawn önle, TODO-j/r)
    try:
        with guard_lock(timeout=5.0):
            summary = handover_faz1(
                message=message,
                display=display,
                dry_run=args.dry_run,
                batch_size=args.batch_size,
                batch_delay=args.batch_delay,
                proc_wait=args.proc_wait,
                grace=args.grace,
                kill_settle=args.kill_settle,
                names=args.names or None,
            )
    except TimeoutError as e:
        print(f"✗ guard.lock alınamadı: {e}", file=sys.stderr)
        print("  guard cron çalışıyor olabilir. 10s bekleyip tekrar dene.", file=sys.stderr)
        return 1

    print()
    print("═" * 50)
    print(f"  opened={summary.opened}  failed={summary.failed}  skipped={summary.skipped}"
          f"  toplam={len(summary.results)}")

    if summary.failed:
        print("\n  ⚠ Başarısız session'lar:")
        for r in summary.results:
            if r.status.startswith("failed"):
                print(f"    {r.name}: {r.status} {r.detail}")

    if summary.failed == 0 and not args.dry_run and not args.names:
        print()
        print("  Sonraki adım (Faz 2 — base-name, suffix yok):")
        print(f"  py/cops rc hc hcr mo vrk rustrino anomaly evolvi done mamut hof iggy vc asp \\")
        print(f"    --new --kill-first --one-by-one")
        print(f"  (--prompt verme → session'lar boş/idle başlar)")

    return 1 if summary.failed else 0
