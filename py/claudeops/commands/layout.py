"""`layout` — claude pencerelerini desktop'lara dağıt (xdotool, X11 only).

Wayland'da çalışmaz. Bash `claudeops layout grid 4 --claude-only --pin=... --group=...` karşılığı.

Kullanım:
  py/cops layout --pin=co53,rustrino54,anomaly54,iggy54 \\
                 --group=hc,hcr,evolvi --group=vc,vrk
  py/cops layout --dry-run  # sadece planı göster
"""
from __future__ import annotations
import os
from ..discovery import find_sessions
from ..layout import (
    _get_screen, _list_windows, build_layout_plan, apply_layout, _detect_screen_y,
)
from ..spawn import detect_display


def register(sub):
    p = sub.add_parser("layout", help="session pencerelerini desktop'lara dağıt (X11)")
    p.add_argument("--pin", default="", metavar="NAMES",
                   help="ws0'a sabit session'lar, virgülle (ör. co53,rustrino54)")
    p.add_argument("--group", action="append", default=[], metavar="BASES",
                   help="aynı desktop'ta tutulacak base isimler, virgülle (tekrarlanabilir)")
    p.add_argument("--claude-only", action="store_true", default=True,
                   help="sadece claude session pencerelerini tile'la (varsayılan)")
    p.add_argument("--all-windows", action="store_true",
                   help="tüm pencereleri tile'la (claude-only'yi kapat)")
    p.add_argument("--display", default=None)
    p.add_argument("--screen-y", type=int, default=None, metavar="Y",
                   help="monitor Y offset (None=xrandr auto-detect; dual-monitor=1080)")
    p.add_argument("--dry-run", action="store_true",
                   help="sadece planı göster, uygulama")
    p.set_defaults(func=run)


def run(args) -> int:
    display = args.display or detect_display()

    if not os.environ.get("DISPLAY") and not display:
        print("✗ X11 display bulunamadı (Wayland'da çalışmaz)")
        return 1

    pinned = [n.strip() for n in args.pin.split(",") if n.strip()] if args.pin else []
    groups = [[b.strip() for b in g.split(",") if b.strip()] for g in args.group]
    claude_only = not args.all_windows

    print(f"display={display}, pin={pinned or '(yok)'}, groups={groups or '(yok)'}")

    windows = _list_windows(display)
    screen = _get_screen(display, screen_y=args.screen_y)
    # known_names: gerçek claude proc'lar → sahte window eşlemesi önler
    known_names = {s.name for s in find_sessions(measure_cpu=False)} if claude_only else None
    plan, name_to_wid = build_layout_plan(
        windows=windows,
        screen=screen,
        pinned_names=pinned,
        groups=groups,
        claude_only=claude_only,
        known_names=known_names,
    )

    print(f"  {plan.total} pencere yerleştirilecek, {plan.skipped} atlandı")
    for wid, ws, x, y in plan.assignments:
        title = windows.get(wid, wid)
        name = next((n for n, w in name_to_wid.items() if w == wid), title)
        print(f"  {name:<15} → ws{ws}  ({x},{y})")

    if not args.dry_run:
        apply_layout(plan, display=display)
        print("✓ layout uygulandı")

    return 0
