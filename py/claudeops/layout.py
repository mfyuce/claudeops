"""Layout — claude session pencerelerini xdotool ile desktop'lara dağıt.

Bash `claudeops layout grid 4 --claude-only --pin=... --group=...` karşılığı.
Wayland'da xdotool çalışmaz → X11 (DISPLAY) gerekli.

Algoritma:
  1. Tüm gnome-terminal pencerelerini bul (xdotool search)
  2. Her pencereyi session ismine eşle (window title → session name)
  3. Pinned session'lar → ws0 sabit
  4. Group session'lar → aynı desktop'a yan yana
  5. Kalanlar → ws1, ws2, ... artan sırayla (4'er pencere)
  6. Her pencere: set_desktop_for_window + windowmove + windowsize
"""
from __future__ import annotations
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple


# Varsayılan grid: 4 pencere/desktop, 2x2 quad
GRID = 4
_QUAD_COLS = 2   # sabit 2 sütun


@dataclass
class ScreenGeometry:
    x: int
    y: int
    w: int
    h: int

    @property
    def quad_w(self) -> int:
        return self.w // _QUAD_COLS

    @property
    def quad_h(self) -> int:
        return self.h // (GRID // _QUAD_COLS)

    def quad_pos(self, idx: int) -> Tuple[int, int]:
        """idx (0-3) → (x, y) başlangıç koordinatı."""
        col = idx % _QUAD_COLS
        row = idx // _QUAD_COLS
        return self.x + col * self.quad_w, self.y + row * self.quad_h


def _run(cmd: List[str], display: str = ":1") -> str:
    """xdotool/wmctrl komutunu çalıştır, stdout döndür."""
    import os
    env = {"DISPLAY": display, "HOME": os.environ.get("HOME", ""), "PATH": os.environ.get("PATH", "")}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=10)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


@dataclass
class Monitor:
    name: str
    x: int
    y: int
    w: int
    h: int
    primary: bool


def _list_monitors(display: str) -> List[Monitor]:
    """xrandr --query'den HER connected monitörün gerçek WxH+X+Y'sini parse et.

    Eski kod `xdotool getdisplaygeometry` (TÜM monitörlerin BİRLEŞİK sanal masaüstü
    boyutu) ile xrandr'dan çekilen bir tek Y offset'ini karıştırıyordu → dikey-istiflenmiş
    kurulumda (bu makine: HDMI-1 üstte 0,0, eDP-1 altta 0,1080) combined h (2130) + ikincil
    monitörün y'si (1080) toplanınca ekran sınırının 1080px DIŞINA taşan bir quad üretiyordu;
    Mutter alt satırı ekrana geri sıkıştırıp üst satırın üstüne bindiriyordu (kullanıcının
    gördüğü "HDMI sol altta üst üste yığılma", 2026-08-28/09-02/09-03 canlı tekrarlandı).
    Yatay (yan-yana, ikisi de y=0) kurulumda da aynı kök sebep — combined w tek monitörün
    genişliğinden büyük. Fix: xdotool'a hiç bakma, monitörü KENDİ dikdörtgeniyle döndür.
    """
    out = _run(["xrandr", "--query"], display)
    monitors = []
    for line in out.splitlines():
        m = re.match(r"^(\S+) connected (primary )?(\d+)x(\d+)\+(\d+)\+(\d+)", line)
        if not m:
            continue
        name, primary, w, h, x, y = m.groups()
        monitors.append(Monitor(name=name, x=int(x), y=int(y), w=int(w), h=int(h),
                                 primary=bool(primary)))
    return monitors


def _get_screen(display: str, screen_y: Optional[int] = None) -> ScreenGeometry:
    """Hedef monitörün gerçek dikdörtgenini xrandr'dan al.

    Seçim: screen_y verilirse o Y'de başlayan monitör (manuel override, ör. dikey
    kurulumda ikincil monitörü hedeflemek için); yoksa xrandr'ın "primary" işaretlediği
    monitör; o da yoksa ilk connected monitör. xrandr hiç okunamazsa (nadir) eski
    xdotool-combined + tek-monitör varsayımına düşer.
    """
    monitors = _list_monitors(display)
    target: Optional[Monitor] = None
    if screen_y is not None:
        target = next((m for m in monitors if m.y == screen_y), None)
    if target is None:
        target = next((m for m in monitors if m.primary), None)
    if target is None and monitors:
        target = monitors[0]
    if target is not None:
        return ScreenGeometry(target.x, target.y, target.w, target.h)

    out = _run(["xdotool", "getdisplaygeometry"], display)
    parts = out.split()
    w, h = 1680, 1050
    if len(parts) == 2:
        try:
            w, h = int(parts[0]), int(parts[1])
        except ValueError:
            pass
    return ScreenGeometry(0, screen_y or 0, w, h)


def _base_from_name(name: str) -> str:
    """Session adından base'i çıkar: hc54 → hc, anomaly54 → anomaly."""
    m = re.match(r"^([a-z]+)\d+$", name)
    return m.group(1) if m else name


def _gnome_terminal_server_pid() -> str:
    """Bash'ten alındı: ps comm 15-char truncate → 'gnome-terminal-'."""
    import subprocess as _sp
    try:
        r = _sp.run(["ps", "-eo", "pid,comm"], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[1].strip() == "gnome-terminal-":
                return parts[0].strip()
    except Exception:
        pass
    return ""


def _list_windows(display: str) -> Dict[str, str]:
    """gnome-terminal pencerelerini bul → {win_id: title}.

    Bash gibi: wmctrl -l -p | gnome-terminal-server PID filtresi.
    Title: spinner/özel char sıyrılır, ilk kelime session adı.
    """
    gtp = _gnome_terminal_server_pid()
    if not gtp:
        return {}

    out = _run(["wmctrl", "-l", "-p"], display)
    result = {}
    for line in out.splitlines():
        parts = line.split(None, 4)  # WID DESK PID HOST TITLE
        if len(parts) < 5:
            continue
        wid, _desk, pid, _host, title = parts
        if pid != gtp:
            continue
        # Bash: title'ın başındaki spinner/özel char'ı sıyır
        import re as _re
        title_clean = _re.sub(r"^[^A-Za-z0-9~/]+ ?", "", title)
        result[wid] = title_clean
    return result


def _is_claude_window(title: str, known_names: Optional[Set[str]] = None) -> bool:
    """Pencere başlığı bir claude session'ı mı?

    known_names verilirse title TAM OLARAK bir known_name'e eşit mi diye bakılır (regex
    DEĞİL) → ssh/vim gibi yanlış pozitif eşleşmeler elenir. 2026-08-25'e kadar burada
    `[a-z]+\\d+$` regex'i vardı (isim rakamla bitmek ZORUNDA) — ama 2026-06-28'de suffix
    sistemi kaldırıldığından beri roster isimleri çıplak (`trino`, `co`, `hc`...) VEYA
    çakışma-suffix'li (`rustrino20260825_1`, alt çizgi+rakamla biten) olabiliyor; eski
    regex bunların HİÇBİRİNİ yakalamıyordu → layout bu pencereleri sessizce atlıyordu
    (bulundu: trino handover sonrası çıplak "trino" adıyla açılınca layout'a hiç girmedi).
    known_names verilmezse (nadir, geriye dönük uyum) eski regex-sezgisiyle karar verilir.
    """
    if known_names is not None:
        return title in known_names
    return bool(re.search(r"([a-z]+\d+)$", title))


def _session_name_from_title(title: str, known_names: Optional[Set[str]] = None) -> Optional[str]:
    """Pencere başlığından session adını çıkar (ör. '✳ hc54' → 'hc54', ya da çıplak 'trino').

    known_names verilirse title TAM eşleşme ile aranır (bkz. `_is_claude_window` notu).
    """
    if known_names is not None:
        return title if title in known_names else None
    m = re.search(r"([a-z]+\d+)$", title)
    return m.group(1) if m else None


@dataclass
class LayoutPlan:
    assignments: List[Tuple[str, int, int, int]]  # (win_id, desktop, x, y)
    screen: ScreenGeometry
    total: int = 0
    skipped: int = 0


def build_layout_plan(
    windows: Dict[str, str],
    screen: ScreenGeometry,
    pinned_names: Optional[List[str]] = None,
    groups: Optional[List[List[str]]] = None,
    claude_only: bool = True,
    known_names: Optional[Set[str]] = None,
) -> Tuple[LayoutPlan, Dict[str, str]]:
    """Pencere yerleşim planı hesapla.

    Returns: (plan, name_to_winid)
    """
    pinned_names = pinned_names or []
    groups = groups or []

    # 1. Session ismine göre window'ları eşle
    name_to_wid: Dict[str, str] = {}
    skipped = 0
    for wid, title in windows.items():
        if claude_only and not _is_claude_window(title, known_names=known_names):
            skipped += 1
            continue
        name = _session_name_from_title(title, known_names=known_names)
        if name:
            name_to_wid[name] = wid

    plan = LayoutPlan(assignments=[], screen=screen, total=len(name_to_wid), skipped=skipped)

    # 2. Pinned → ws0
    ws0_names = [n for n in pinned_names if n in name_to_wid]
    for idx, name in enumerate(ws0_names[:GRID]):
        wid = name_to_wid[name]
        x, y = screen.quad_pos(idx)
        plan.assignments.append((wid, 0, x, y))

    # 3. Kalanları sıraya al: önce group'lar, sonra tekler
    placed: Set[str] = set(ws0_names)
    ordered: List[str] = []

    # Group'lar — base eşleşmesi (startswith değil: hc ≠ hcr54); dedup ile çakışan grp atla
    group_flat: List[str] = []
    group_seen: Set[str] = set()
    for grp in groups:
        grp_set = set(grp)
        for n in name_to_wid:
            if _base_from_name(n) in grp_set and n not in placed and n not in group_seen:
                group_flat.append(n)
                group_seen.add(n)
    ordered.extend(group_flat)

    # Tekler (ne pinned ne group)
    placed_in_ordered = set(placed) | set(group_flat)
    singles = sorted(n for n in name_to_wid if n not in placed_in_ordered)
    ordered.extend(singles)

    # 4. ws1, ws2, ... artan sırayla (GRID adet/desktop)
    ws = 1
    slot = 0
    for name in ordered:
        if name in placed:
            continue
        wid = name_to_wid[name]
        x, y = screen.quad_pos(slot)
        plan.assignments.append((wid, ws, x, y))
        slot += 1
        if slot >= GRID:
            slot = 0
            ws += 1

    return plan, name_to_wid


def _place_window(wid: str, x: int, y: int, w: int, h: int, display: str) -> bool:
    """Bash `_place_win` karşılığı: un-maximize + move + resize, read-back ile doğrula, 3 deneme.

    Tek seferlik `xdotool windowmove` bazen sessizce uygulanmıyor (2026-09-03 canlı: 10
    pencereden 1'i ilk denemede oturmadı, konumu bozuk kaldı) — bash'in retry+read-back'i
    PORT edilmeden python tarafı bunu hiç yakalamıyordu, sessizce yanlış yerde bırakıyordu.
    """
    pos = ""
    for _attempt in range(3):
        pos = _run(["xdotool", "getwindowgeometry", wid], display)
        m = re.search(r"Position: (-?\d+),(-?\d+)", pos)
        if m:
            px, py = int(m.group(1)), int(m.group(2))
            if abs(px - x) <= 80 and abs(py - y) <= 80:
                return True
        _run(["wmctrl", "-i", "-r", wid, "-b", "remove,maximized_vert,maximized_horz"], display)
        _run(["xdotool", "windowmove", wid, str(x), str(y)], display)
        _run(["xdotool", "windowsize", wid, str(w), str(h)], display)
        time.sleep(0.3)
    return False


def apply_layout(plan: LayoutPlan, display: str = ":1") -> List[str]:
    """Planı xdotool ile uygula. Oturmayan pencerelerin id listesini döndürür.

    Bash gibi: her desktop'a switch et, sonra o desktop'taki pencereleri taşı.
    windowmove aktif desktop dışındaki pencerelerde çalışmıyor (Mutter).
    """
    from collections import defaultdict

    by_ws: Dict[int, list] = defaultdict(list)
    for wid, ws, x, y in plan.assignments:
        by_ws[ws].append((wid, x, y))

    failed: List[str] = []
    for ws in sorted(by_ws):
        # Bash _ensure_desktop: desktop'a geç, yerleştikten sonra 0.35s bekle
        _run(["wmctrl", "-s", str(ws)], display)
        time.sleep(0.35)

        for wid, x, y in by_ws[ws]:
            _run(["xdotool", "set_desktop_for_window", wid, str(ws)], display)
            if not _place_window(wid, x, y, plan.screen.quad_w, plan.screen.quad_h, display):
                failed.append(wid)

    _run(["wmctrl", "-s", "0"], display)
    return failed
