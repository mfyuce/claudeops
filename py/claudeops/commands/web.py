"""`web` — yerel kontrol paneli: fleet durumunu göster, tek tek başlat/durdur.

Kullanıcı isteği: "hepsini açmam ama gerektiğinde web'den başlatırım, görürüm" +
seçenekli başlatma (model/permission-mode/effort/fresh) + tünelden (cf tunnel)
uzaktan erişim. Bu yüzden mass-start YOK — sadece roster'ı listele + her
satırda Start (seçeneklerle) / Stop.

Auth: token zorunlu (query param `?token=...`, sayfa + tüm /api/* istekleri).
Sebep: localhost-only için önemsizdi, ama tünelle internete açılabildiği için
(kullanıcı: "cf tunnel ile web'e ulaşırım") token ŞART — token yoksa herkes
fleet'i başlatıp durdurabilir. Token ~/.claude/claudeops/web.token'da persist
edilir (ilk çalıştırmada random üretilir, chmod 600).

Start = spawn_session(force_new=<UI seçimi>) — varsayılan resume (--new değil).
Stop = kill_session_and_parent(grace=KILL_GRACE_SECONDS) — aynı 10s
truncation-safe kural ([[claude-2183-conversation-truncation]]) + parent bash'i
de öldürür (orphan terminal bırakmaz, TODO-b kök sebep fix).
"""
from __future__ import annotations
import datetime
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import time
import urllib.request
from typing import Optional
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from ..config import validate_config
from ..discovery import find_sessions, duplicates
from ..guard import guard_lock
from ..handover import HANDOVER_MSG_DEFAULT, HANDOVER_MSG_DEFAULT_EN
from ..kill import kill_session_and_parent, KILL_GRACE_SECONDS
from ..paths import CLAUDEOPS_DIR, MODELS_TSV, ROSTER_TSV
from ..spawn import spawn_session, detect_display

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"
TOKEN_FILE = os.path.join(CLAUDEOPS_DIR, "web.token")
TUNNEL_LOG = os.path.join(CLAUDEOPS_DIR, "tunnel.log")
_TUNNEL_URL_RE = re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com")

MODEL_CHOICES = [
    "claude-sonnet-5",
    "claude-opus-5",
    "claude-fable-5",
    "claude-haiku-4-5-20251001",
]
PERMISSION_MODES = ["auto", "acceptEdits", "bypassPermissions", "manual", "dontAsk", "plan"]
EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]

# API hata mesajları TR/EN — panel dili EN'de olsa da backend hataları hep TR geliyordu
# (2026-08-25, kullanıcı: "uyarılar tr geliyor hep, ing seçilsin seçilmesin gibi"). do_POST
# artık `lang` alanını her isteğin body'sinden okuyup ilgili fonksiyona geçiyor; frontend her
# fetch çağrısına `lang: LANG` ekliyor.
ERR = {
    "invalid_name": {"tr": "geçersiz isim — küçük harf ile başlamalı, sadece a-z 0-9 _ içerebilir",
                      "en": "invalid name — must start with a lowercase letter, only a-z 0-9 _ allowed"},
    "already_registered": {"tr": "{name}: zaten kayıtlı (aktif/kapalı/emekli)",
                            "en": "{name}: already registered (active/closed/retired)"},
    "dir_not_found": {"tr": "{cwd}: dizin bulunamadı", "en": "{cwd}: directory not found"},
    "cwd_bad_chars": {"tr": "cwd geçersiz karakter içeriyor", "en": "cwd contains invalid characters"},
    "base_not_in_roster": {"tr": "{base}: roster'da yok — önce ana ismi ekleyin",
                            "en": "{base}: not in roster — register the base name first"},
    "newchat_start_failed": {"tr": "{new_name}: roster'a kaydedildi ama başlatılamadı "
                                    "(gnome-terminal/DISPLAY sorunu olabilir) — '+ Ekle'den tekrar deneyin — kind={kind}",
                              "en": "{new_name}: registered but failed to start "
                                    "(could be a gnome-terminal/DISPLAY issue) — retry from '+ Add' — kind={kind}"},
    "missing_deps": {"tr": "eksik bağımlılık: {missing} — Ubuntu/Debian'da kurmak için: sudo apt install -y {missing}",
                      "en": "missing dependency: {missing} — install on Ubuntu/Debian with: sudo apt install -y {missing}"},
    "screen_locked_layout": {"tr": "ekran KİLİTLİ — layout kilitli ekranda bozuk çalışır (Mutter). "
                                    "Önce ekranın kilidini açın, sonra tekrar deneyin.",
                              "en": "screen is LOCKED — layout misbehaves on a locked screen (Mutter). "
                                    "Unlock the screen first, then retry."},
    "no_x11": {"tr": "X11 display bulunamadı (Wayland'da çalışmaz)",
               "en": "X11 display not found (doesn't work on Wayland)"},
    "not_active": {"tr": "{name}: roster/models.tsv'de aktif değil",
                    "en": "{name}: not active in roster/models.tsv"},
    "already_running": {"tr": "{name}: zaten çalışıyor", "en": "{name}: already running"},
    "start_no_proc": {"tr": "{name}: başlatma denendi ama proc görünmedi "
                             "(gnome-terminal/DISPLAY/kilit ekranı sorunu olabilir, tekrar deneyin) — kind={kind}",
                       "en": "{name}: start attempted but no process appeared "
                             "(could be gnome-terminal/DISPLAY, retry) — kind={kind}"},
    "not_running": {"tr": "{name}: çalışmıyor", "en": "{name}: not running"},
    "undefined": {"tr": "{name}: tanımsız", "en": "{name}: undefined"},
    "already_retired": {"tr": "{name}: zaten emekli", "en": "{name}: already retired"},
    "already_closed": {"tr": "{name}: zaten kapalı", "en": "{name}: already closed"},
    "retired_needs_reactivate": {"tr": "{name}: emekli — önce 'tekrar işe al', sonra kapatın",
                                  "en": "{name}: retired — reactivate first, then close"},
    "handover_reopen_failed": {"tr": "{name}: kapatıldı ama yeniden açılamadı "
                                      "(gnome-terminal/DISPLAY/kilit ekranı sorunu olabilir) — kind={kind}",
                                "en": "{name}: closed but couldn't reopen "
                                      "(could be a gnome-terminal/DISPLAY issue) — kind={kind}"},
    "name_in_use": {"tr": "{new_name}: zaten kullanılıyor (roster'da ya da çalışıyor)",
                     "en": "{new_name}: already in use (in roster or currently running)"},
    "adopt_reopen_failed": {"tr": "{old_name}: kapatıldı ama '{new_name}' olarak yeniden açılamadı "
                                   "(gnome-terminal/DISPLAY/kilit ekranı sorunu olabilir) — kind={kind}",
                             "en": "{old_name}: closed but couldn't reopen as '{new_name}' "
                                   "(could be a gnome-terminal/DISPLAY issue) — kind={kind}"},
    "already_active": {"tr": "{name}: zaten aktif", "en": "{name}: already active"},
    "invalid_json": {"tr": "geçersiz JSON", "en": "invalid JSON"},
    "base_required": {"tr": "base gerekli", "en": "base is required"},
    "name_required": {"tr": "name gerekli", "en": "name is required"},
}


def _err(lang: str, key: str, **kwargs) -> dict:
    tpl = ERR[key]["en" if lang == "en" else "tr"]
    return {"ok": False, "error": tpl.format(**kwargs)}


def _load_or_create_token() -> str:
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            tok = f.read().strip()
            if tok:
                return tok
    except FileNotFoundError:
        pass
    tok = secrets.token_hex(24)
    os.makedirs(CLAUDEOPS_DIR, exist_ok=True)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok)
    return tok


def _ensure_cloudflared() -> Optional[str]:
    """cloudflared'ı PATH'te bul; yoksa ~/.local/bin'e resmi binary'yi indir (Linux only —
    claudeops zaten gnome-terminal'e bağımlı, Mac/Windows kapsam dışı).

    Returns: çözümlenmiş binary yolu, ya da indirilemezse None.
    """
    found = shutil.which("cloudflared")
    if found:
        return found

    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if platform.system() != "Linux" or not arch:
        print(f"✗ cloudflared otomatik kurulamıyor ({platform.system()}/{machine}) — elle kurun: "
              "https://github.com/cloudflare/cloudflared/releases")
        return None

    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
    dest_dir = os.path.expanduser("~/.local/bin")
    dest = os.path.join(dest_dir, "cloudflared")
    print(f"cloudflared bulunamadı — indiriliyor: {url}")
    try:
        os.makedirs(dest_dir, exist_ok=True)
        urllib.request.urlretrieve(url, dest)
        os.chmod(dest, 0o755)
        print(f"✓ cloudflared kuruldu: {dest}")
        return dest
    except Exception as e:
        print(f"✗ cloudflared indirilemedi ({e}) — elle kurun: https://github.com/cloudflare/cloudflared/releases")
        return None


def _start_tunnel(port: int, cloudflared_path: str = "cloudflared", timeout: float = 20.0):
    """cloudflared quick tunnel başlat (login gerekmez, URL her seferinde random).

    Returns (proc, url_or_None). Süreç kalıcıdır — çağıran server_close/finally'de
    terminate etmeli, yoksa cloudflared orphan kalır.
    """
    os.makedirs(CLAUDEOPS_DIR, exist_ok=True)
    log_f = open(TUNNEL_LOG, "w")
    proc = subprocess.Popen(
        [cloudflared_path, "tunnel", "--url", f"http://127.0.0.1:{port}"],
        stdout=log_f, stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + timeout
    url = None
    while time.monotonic() < deadline:
        try:
            with open(TUNNEL_LOG) as f:
                m = _TUNNEL_URL_RE.search(f.read())
                if m:
                    url = m.group(0)
                    break
        except FileNotFoundError:
            pass
        if proc.poll() is not None:
            break  # cloudflared erken çıktı — muhtemelen hata
        time.sleep(0.5)
    return proc, url


def _find_running(name: str) -> list:
    """Tam isim VEYA base eşleşmesiyle çalışan session'ları bul.

    rc.py'nin kill-first mantığıyla aynı desen ([[stale-tui-title-cross-suffix-resume]]
    tarzı): elle/eski tarih-suffix'li açılmış bir proc (`trino20260823`) roster'a
    temiz base isimle (`trino`) kaydedilse bile Session.base regex'i onu doğru
    eşler — çıplak `find_by_name` (tam isim) bunu KAÇIRIR → yanlışlıkla "duruyor"
    sanılıp ikinci bir proc spawn edilebilir.
    """
    return [s for s in find_sessions(measure_cpu=False) if s.name == name or s.base == name]


def _read_tsv_raw(path: str) -> list:
    """path'i YORUM DAHİL satır listesi olarak oku: [{"name","rest":[...],"active":bool}].

    models.tsv/roster.tsv'de kapalı/emekli girdiler `#isim\\t...` şeklinde yorumlanır
    (guard/roster.py bunları hiç görmez) — retire/reactivate için ham erişim gerekiyor.
    """
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return rows
    for line in lines:
        core = line.rstrip("\n")
        stripped = core.strip()
        if not stripped:
            continue
        active = not stripped.startswith("#")
        bare = stripped[1:] if not active else stripped
        parts = bare.strip().split("\t")
        if not parts or not parts[0]:
            continue
        rows.append({"name": parts[0], "rest": parts[1:], "active": active})
    return rows


def _fleet_status() -> dict:
    """İsim → {"cwd","model","state"} — state: active / closed (KAPALI) / retired (EMEKLİ).

    KAPALI  = roster.tsv'de aktif ama models.tsv'de yorumlu (guard açmaz, cwd hâlâ bilinir).
    EMEKLİ  = ikisinde de yorumlu (eski suffix-döneminden tam çıkarılmış isimler).
    """
    models_raw = {r["name"]: r for r in _read_tsv_raw(MODELS_TSV) if r["name"] != "name"}
    roster_raw = {r["name"]: r for r in _read_tsv_raw(ROSTER_TSV) if r["name"] != "name"}

    result = {}
    for name, mrow in models_raw.items():
        rrow = roster_raw.get(name)
        if rrow is None:
            continue  # cwd bilinmiyor — gösterilemez
        cwd = rrow["rest"][0] if rrow["rest"] else ""
        model = mrow["rest"][0] if mrow["rest"] else ""
        if mrow["active"] and rrow["active"]:
            state = "active"
        elif not mrow["active"] and not rrow["active"]:
            state = "retired"
        else:
            state = "closed"
        result[name] = {"cwd": cwd, "model": model, "state": state}
    return result


def _all_known_names() -> set:
    """roster.tsv'deki (aktif/kapalı/emekli FARK ETMEZ) TÜM isimler + şu an çalışan
    TÜM proc isimleri/base'leri — yeni chat ismi üretirken çakışma kontrolü için."""
    names = {r["name"] for r in _read_tsv_raw(ROSTER_TSV) if r["name"] != "name"}
    for s in find_sessions(measure_cpu=False):
        names.add(s.name)
        names.add(s.base)
    return names


def _generate_new_chat_name(base: str) -> str:
    """`<base><bugünün tarihi>`, çakışırsa `_1`, `_2`... ekler.

    Kullanıcının kendi elle-açma alışkanlığıyla aynı desen (trino20260823,
    mo20260813_1 gibi — ListAgents'ta görülen). Fark: burada OTOMATİK üretilip
    roster.tsv'ye de kaydediliyor → artık invisible/unmanaged kalmıyor.
    """
    date_suffix = datetime.date.today().strftime("%Y%m%d")
    known = _all_known_names()
    candidate = f"{base}{date_suffix}"
    if candidate not in known:
        return candidate
    i = 1
    while f"{candidate}_{i}" in known:
        i += 1
    return f"{candidate}_{i}"


def _append_tsv_line(path: str, fields: list) -> None:
    """path'e yeni bir satır ekle (trailing-newline güvenli)."""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = ""
    if content and not content.endswith("\n"):
        content += "\n"
    content += "\t".join(fields) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


_NAME_VALID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _register_project(name: str, cwd: str, model: str = "", lang: str = "tr") -> dict:
    """UI'den yeni proje kaydı — roster.tsv+models.tsv'ye ekler, SPAWN ETMEZ.

    Sonra normal "+ Ekle" listesinden başlatılır (mevcut trino/oiso/line elle-ekleme
    akışının UI karşılığı).
    """
    name = name.strip()
    if not _NAME_VALID_RE.match(name):
        return _err(lang, "invalid_name")
    if name in _all_known_names():
        return _err(lang, "already_registered", name=name)
    cwd = os.path.expanduser(cwd.strip())
    if not cwd or not os.path.isdir(cwd):
        return _err(lang, "dir_not_found", cwd=cwd or ("(boş)" if lang != "en" else "(empty)"))
    if "\t" in cwd or "\n" in cwd:
        return _err(lang, "cwd_bad_chars")
    chosen_model = model.strip() or MODEL_CHOICES[0]
    _append_tsv_line(ROSTER_TSV, [name, cwd, chosen_model])
    _append_tsv_line(MODELS_TSV, [name, chosen_model])
    return {"ok": True}


def _new_chat(base: str, model: str = "", permission_mode: str = "", effort: str = "", lang: str = "tr") -> dict:
    """`base`'in cwd'sinde YENİ, otomatik-isimli (tarih[+_N]) bir chat başlat.

    Var olan `base` session'ına DOKUNMAZ (çalışıyorsa bile) — ayrı, ek bir kayıt.
    Roster/models.tsv'ye hemen upsert edilir (görünür/yönetilebilir kalsın).
    """
    fleet = _fleet_status()
    info = fleet.get(base)
    if not info:
        return _err(lang, "base_not_in_roster", base=base)
    new_name = _generate_new_chat_name(base)
    chosen_model = model.strip() or info["model"]
    _append_tsv_line(ROSTER_TSV, [new_name, info["cwd"], chosen_model])
    _append_tsv_line(MODELS_TSV, [new_name, chosen_model])
    try:
        with guard_lock(timeout=5.0):
            kind = spawn_session(
                name=new_name,
                cwd=info["cwd"],
                model=chosen_model,
                display=detect_display(),
                permission_mode=permission_mode.strip() or "auto",
                effort=effort.strip() or "max",
                force_new=True,
            )
            deadline = time.monotonic() + HANDOVER_PROC_WAIT_SECONDS
            opened = False
            while time.monotonic() < deadline:
                if _find_running(new_name):
                    opened = True
                    break
                time.sleep(1.0)
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    if not opened:
        return _err(lang, "newchat_start_failed", new_name=new_name, kind=kind)
    return {"ok": True, "name": new_name, "kind": kind}


def _toggle_comment(path: str, name: str, want_active: bool) -> bool:
    """path'te `name` girdisinin satırını bul, want_active'e göre baştaki '#' ekle/kaldır.

    Satır bulunup değiştirildiyse True. Diğer satırlara/whitespace'e dokunmaz.
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return False
    found = False
    for i, line in enumerate(lines):
        core = line.rstrip("\n")
        is_commented = core.startswith("#")
        bare = core[1:] if is_commented else core
        first_field = bare.strip().split("\t", 1)[0]
        if first_field == name:
            lines[i] = (bare if want_active else "#" + bare) + "\n"
            found = True
            break
    if found:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    return found


LAYOUT_DEPS = ["wmctrl", "xdotool"]


def _missing_layout_deps() -> list:
    return [d for d in LAYOUT_DEPS if shutil.which(d) is None]


def _screen_locked() -> Optional[bool]:
    """loginctl LockedHint kontrolü. True=kilitli, False=unlocked, None=belirlenemedi.

    [[layout-needs-unlocked-screen]] — kilitli ekranda Mutter pencere-move BOZUK
    (sola yığılma, xdotool red, wmctrl 2×-offset) — SAATLERCE kaybettirilmiş bir ders.
    Web'den (telefondan tünelle) layout tetiklenebildiği için bu artık otomatik kontrol
    ŞART (TODO'da elle-doğrula notuydu, web bunu code'a taşıyor).
    """
    try:
        out = subprocess.run(
            ["bash", "-c",
             "loginctl show-session $(loginctl --no-legend list-sessions | awk '{print $1; exit}') -p LockedHint"],
            capture_output=True, text=True, timeout=5,
        )
        if "LockedHint=yes" in out.stdout:
            return True
        if "LockedHint=no" in out.stdout:
            return False
    except Exception:
        pass
    return None


def _run_layout(pin: str, groups: list, claude_only: bool = True,
                 screen_y: Optional[int] = None, dry_run: bool = False, lang: str = "tr") -> dict:
    missing = _missing_layout_deps()
    if missing:
        return _err(lang, "missing_deps", missing=", ".join(missing))
    if _screen_locked():
        return _err(lang, "screen_locked_layout")

    display = detect_display()
    if not os.environ.get("DISPLAY") and not display:
        return _err(lang, "no_x11")

    from ..layout import _get_screen, _list_windows, build_layout_plan, apply_layout

    pinned = [n.strip() for n in pin.split(",") if n.strip()] if pin else []
    group_lists = [[b.strip() for b in g.split(",") if b.strip()] for g in groups if g.strip()]

    windows = _list_windows(display)
    screen = _get_screen(display, screen_y=screen_y)
    known_names = {s.name for s in find_sessions(measure_cpu=False)} if claude_only else None
    plan, name_to_wid = build_layout_plan(
        windows=windows, screen=screen, pinned_names=pinned,
        groups=group_lists, claude_only=claude_only, known_names=known_names,
    )

    assignments = []
    for wid, ws, x, y in plan.assignments:
        title = windows.get(wid, wid)
        name = next((n for n, w in name_to_wid.items() if w == wid), title)
        assignments.append({"name": name, "ws": ws, "x": x, "y": y})

    if not dry_run:
        apply_layout(plan, display=display)

    return {"ok": True, "total": plan.total, "skipped": plan.skipped,
            "assignments": assignments, "applied": not dry_run}


def _status_payload() -> dict:
    fleet = _fleet_status()
    all_live = find_sessions(measure_cpu=True)
    running = {s.base: s for s in all_live}
    dups = duplicates(list(running.values()))
    ok, msg = validate_config()

    sessions, closed, retired = [], [], []
    for name in sorted(fleet):
        info = fleet[name]
        if info["state"] == "retired":
            retired.append({"name": name, "cwd": info["cwd"], "model": info["model"]})
            continue
        if info["state"] == "closed":
            closed.append({"name": name, "cwd": info["cwd"], "model": info["model"]})
            continue
        s = running.get(name)
        sessions.append({
            "name": name,
            "model": info["model"],
            "cwd": info["cwd"],
            "running": s is not None,
            "pid": s.pid if s else None,
            "cpu": round(s.cpu, 1) if s else None,
            "kind": ("fresh" if s.is_fresh else "resume") if s else None,
            "registered": True,
        })

    # Canlı ama roster'da HİÇ olmayan session'lar (ör. bu panelin kendisi, ya da
    # elle `--remote-control X` ile açılmış ad-hoc bir şey) — "kayıtsız" olarak
    # göster, register edilene kadar sadece durdur/handover mümkün (start/close/
    # retire roster satırı gerektirir). Kullanıcı: "cops... (bu session) web'den
    # de yapabilmeliyim" isteğiyle eklendi.
    for s in all_live:
        if s.name in fleet or s.base in fleet:
            continue
        sessions.append({
            "name": s.name,
            "model": s.model or "?",
            "cwd": s.cwd,
            "running": True,
            "pid": s.pid,
            "cpu": round(s.cpu, 1),
            "kind": "fresh" if s.is_fresh else "resume",
            "registered": False,
        })

    return {
        "config_ok": ok,
        "config_msg": msg,
        "dups": dups,
        "sessions": sessions,
        "closed": closed,
        "retired": retired,
        "model_choices": MODEL_CHOICES,
        "permission_modes": PERMISSION_MODES,
        "effort_levels": EFFORT_LEVELS,
        "layout_missing_deps": _missing_layout_deps(),
    }


def _start(name: str, model: str = "", permission_mode: str = "", effort: str = "", fresh: bool = False,
           lang: str = "tr") -> dict:
    fleet = _fleet_status()
    info = fleet.get(name)
    if not info or info["state"] != "active":
        return _err(lang, "not_active", name=name)
    if _find_running(name):
        return _err(lang, "already_running", name=name)
    try:
        with guard_lock(timeout=5.0):
            kind = spawn_session(
                name=name,
                cwd=info["cwd"],
                model=model.strip() or info["model"],
                display=detect_display(),
                permission_mode=permission_mode.strip() or "auto",
                effort=effort.strip() or "max",
                force_new=bool(fresh),
            )
            deadline = time.monotonic() + HANDOVER_PROC_WAIT_SECONDS
            opened = False
            while time.monotonic() < deadline:
                if _find_running(name):
                    opened = True
                    break
                time.sleep(1.0)
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    if not opened:
        return _err(lang, "start_no_proc", name=name, kind=kind)
    return {"ok": True, "kind": kind}


def _stop(name: str, lang: str = "tr") -> dict:
    procs = _find_running(name)
    if not procs:
        return _err(lang, "not_running", name=name)
    try:
        with guard_lock(timeout=5.0):
            results = [kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS) for s in procs]
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "result": results}


def _retire(name: str, lang: str = "tr") -> dict:
    fleet = _fleet_status()
    info = fleet.get(name)
    if not info:
        return _err(lang, "undefined", name=name)
    if info["state"] == "retired":
        return _err(lang, "already_retired", name=name)
    procs = _find_running(name)
    if procs:
        try:
            with guard_lock(timeout=5.0):
                for s in procs:
                    kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS)
        except TimeoutError as e:
            return {"ok": False, "error": str(e)}
    _toggle_comment(MODELS_TSV, name, want_active=False)
    _toggle_comment(ROSTER_TSV, name, want_active=False)
    return {"ok": True}


def _close_project(name: str, lang: str = "tr") -> dict:
    """Hafif kapat: sadece models.tsv yorumla (roster.tsv AKTİF kalır, cwd hatırlanır).

    Emekli'den fark: roster.tsv dokunulmaz — "geçici durduruldu, sonra bakılacak"
    (carla/mecdtfl'nin haziran'daki "KAPALI, revizyon bekler" kullanımıyla aynı).
    py/cops close CLI komutuyla aynı mekanizma, web panelinden erişim.
    """
    fleet = _fleet_status()
    info = fleet.get(name)
    if not info:
        return _err(lang, "undefined", name=name)
    if info["state"] == "closed":
        return _err(lang, "already_closed", name=name)
    if info["state"] == "retired":
        return _err(lang, "retired_needs_reactivate", name=name)
    procs = _find_running(name)
    if procs:
        try:
            with guard_lock(timeout=5.0):
                for s in procs:
                    kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS)
        except TimeoutError as e:
            return {"ok": False, "error": str(e)}
    _toggle_comment(MODELS_TSV, name, want_active=False)
    return {"ok": True}


HANDOVER_KILL_SETTLE_SECONDS = 6.0
HANDOVER_PROC_WAIT_SECONDS = 25.0


def _handover(name: str, lang: str = "tr") -> dict:
    """Wrap-up mesajıyla kill+resume — py/cops handover'ın TEK-session web karşılığı.

    needs_ho/batch YOK (kullanıcı elle, bilerek tetikliyor) — sadece kill+resume+prompt,
    handover.py'deki _spawn_faz1 ile AYNI spawn_session() çağrısı (env-leak fix dahil).
    Roster GEREKMEZ (CLI'nin isimli-hedefleme mantığıyla aynı, [[handover]] 2026-08-25) —
    kayıtlı değilse cwd/model canlı proc'tan (_find_running) alınır.

    handover.py'deki handover_faz1() ile AYNI iki güvenlik adımı burada da şart, yoksa
    "kapattı, bir daha açmadı" olur (2026-08-25 bulundu, cops20260824 üzerinde canlı test):
    1. kill_settle: kill sonrası respawn'dan ÖNCE bekleme — server-side RC bridge eski
       ismi hemen bırakmıyor, settle olmadan aynı isimle respawn çakışabilir
       ([[handover-edge-cases]] bridge trap).
    2. proc-presence doğrulama: spawn_session() gnome-terminal'i Popen ile FIRE-AND-FORGET
       açıyor (dönüş değeri başarı garantisi DEĞİL) — respawn gerçekten proc üretti mi
       kontrol etmeden ok:True dönmek, sessiz başarısızlığı UI'da "başarılı" gibi gösterir.
    """
    procs = _find_running(name)
    if not procs:
        return _err(lang, "not_running", name=name)
    fleet = _fleet_status()
    info = fleet.get(name)
    if info:
        cwd, model = info["cwd"], info["model"]
    else:
        cwd, model = procs[0].cwd, (procs[0].model or "claude-sonnet-5")
    message = HANDOVER_MSG_DEFAULT_EN if lang == "en" else HANDOVER_MSG_DEFAULT
    try:
        with guard_lock(timeout=5.0):
            kill_results = [kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS) for s in procs]
            if HANDOVER_KILL_SETTLE_SECONDS > 0 and any(r != "already_dead" for r in kill_results):
                time.sleep(HANDOVER_KILL_SETTLE_SECONDS)
            kind = spawn_session(
                name=name,
                cwd=cwd,
                model=model,
                display=detect_display(),
                permission_mode="auto",
                effort="max",
                force_new=False,
                prompt=message,
            )
            deadline = time.monotonic() + HANDOVER_PROC_WAIT_SECONDS
            reopened = False
            while time.monotonic() < deadline:
                if _find_running(name):
                    reopened = True
                    break
                time.sleep(1.0)
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    if not reopened:
        return _err(lang, "handover_reopen_failed", name=name, kind=kind)
    return {"ok": True, "kind": kind}


def _adopt(old_name: str, new_name: str = "", model: str = "",
           permission_mode: str = "", effort: str = "", lang: str = "tr") -> dict:
    """claudeops'un AÇMADIĞI (kayıtsız/foreign) canlı bir session'ı devral.

    2026-08-25, kullanıcı: "açmadığı pencereleri de yönetme özelliği ekleyelim, istediğine
    remote eklesin istediğini rename etsin". Örnek: "cops" (bu chat'in kendisi) — bare
    `claude` proc'u, --remote-control HİÇ almamış ama claude 2.1.245 yine de kendi
    ~/.claude/sessions/<pid>.json'ına bridgeSessionId yazıyor (name/bridge kaydı flag'den
    bağımsız). claudeops'un normal kill+respawn'ı (handover/start) TAM OLARAK bu iş için
    var, tek fark: burada respawn AYRI, YENİ bir pencerede olur — "bu pencere geri geldi"
    DEĞİL, "bu pencere kapandı, başka bir pencere seçtiğiniz isimle açıldı" (UI bunu net
    uyarıyor, adoptWarn). new_name boşsa/old_name ile aynıysa sadece --remote-control
    EKLENMİŞ olur (isim değişmez). Başarılı respawn'dan sonra roster'a da upsert edilir
    (aksi halde bir sonraki oturumda yine "kayıtsız" görünür).
    """
    old_name = old_name.strip()
    new_name = (new_name or old_name).strip()
    if not _NAME_VALID_RE.match(new_name):
        return _err(lang, "invalid_name")
    procs = _find_running(old_name)
    if not procs:
        return _err(lang, "not_running", name=old_name)
    if new_name != old_name and new_name in _all_known_names():
        return _err(lang, "name_in_use", new_name=new_name)
    cwd = procs[0].cwd
    chosen_model = model.strip() or procs[0].model or "claude-sonnet-5"
    try:
        with guard_lock(timeout=5.0):
            kill_results = [kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS) for s in procs]
            if HANDOVER_KILL_SETTLE_SECONDS > 0 and any(r != "already_dead" for r in kill_results):
                time.sleep(HANDOVER_KILL_SETTLE_SECONDS)
            kind = spawn_session(
                name=new_name,
                cwd=cwd,
                model=chosen_model,
                display=detect_display(),
                permission_mode=permission_mode.strip() or "auto",
                effort=effort.strip() or "max",
                force_new=False,
            )
            deadline = time.monotonic() + HANDOVER_PROC_WAIT_SECONDS
            reopened = False
            while time.monotonic() < deadline:
                if _find_running(new_name):
                    reopened = True
                    break
                time.sleep(1.0)
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    if not reopened:
        return _err(lang, "adopt_reopen_failed", old_name=old_name, new_name=new_name, kind=kind)
    if new_name not in _fleet_status():
        _append_tsv_line(ROSTER_TSV, [new_name, cwd, chosen_model])
        _append_tsv_line(MODELS_TSV, [new_name, chosen_model])
    return {"ok": True, "kind": kind, "new_name": new_name}


def _reactivate_and_start(name: str, lang: str = "tr") -> dict:
    fleet = _fleet_status()
    info = fleet.get(name)
    if not info:
        return _err(lang, "undefined", name=name)
    if info["state"] == "active":
        return _err(lang, "already_active", name=name)
    _toggle_comment(MODELS_TSV, name, want_active=True)
    _toggle_comment(ROSTER_TSV, name, want_active=True)
    return _start(name, lang=lang)


PAGE_HTML = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>claudeops</title>
<style>
  :root {
    --bg: #0d1117; --panel: #161b22; --panel2: #1c2129; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e;
    --green: #3fb950; --red: #f85149; --amber: #d29922;
    --accent: #58a6ff;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #f6f8fa; --panel: #ffffff; --panel2: #eef1f4; --border: #d0d7de;
      --text: #1f2328; --muted: #59636e;
      --green: #1a7f37; --red: #cf222e; --amber: #9a6700;
      --accent: #0969da;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 2rem 1.5rem 4rem;
    background: var(--bg); color: var(--text);
    font: 14px/1.5 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  }
  .wrap { max-width: 960px; margin: 0 auto; }
  h1 { font-size: 1.1rem; margin: 0; letter-spacing: .02em; }
  .topbar { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; margin-bottom: .25rem; }
  .langsw { display: flex; gap: .3rem; flex-shrink: 0; }
  .langsw button { padding: .15rem .5rem; font-size: .72rem; border-color: var(--border); color: var(--muted); }
  .langsw button.active { border-color: var(--accent); color: var(--accent); }
  .sub { color: var(--muted); margin-bottom: 1.25rem; }
  .banner {
    padding: .5rem .75rem; border-radius: 6px; margin-bottom: .6rem;
    font-size: .85rem; border: 1px solid transparent;
  }
  .banner.bad { background: rgba(248,81,73,.12); border-color: var(--red); color: var(--red); }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; color: var(--muted); font-weight: 500; font-size: .75rem;
       text-transform: uppercase; letter-spacing: .04em; padding: .4rem .5rem;
       border-bottom: 1px solid var(--border); }
  td { padding: .4rem .5rem; border-bottom: 1px solid var(--border); vertical-align: middle; }
  td.cwd { color: var(--muted); font-size: .78rem; overflow: hidden; text-overflow: ellipsis;
           white-space: nowrap; max-width: 1px; cursor: pointer; }
  td.cwd.expanded { white-space: normal; word-break: break-all; max-width: none; overflow: visible; }
  .tablewrap { overflow-x: auto; }
  @media (max-width: 640px) {
    /* dar ekranda model/tür sütunlarını gizle, cwd'yi kısalt — action butonları
       kaydırmadan görünsün (telefonda test edildi: bunlar olmadan sağdaki
       stop/options/close/retire ekran dışına taşıyordu) */
    th:nth-child(2), td:nth-child(2), th:nth-child(5), td:nth-child(5) { display: none; }
    td.cwd { max-width: 70px; }
    h1 { font-size: 1rem; }
  }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: .4rem; }
  .dot.on { background: var(--green); }
  .dot.off { background: var(--muted); opacity: .5; }
  button, select, input[type=text] {
    font: inherit; padding: .3rem .6rem; border-radius: 6px; cursor: pointer;
    border: 1px solid var(--border); background: var(--panel); color: var(--text);
  }
  select, input[type=text] { cursor: default; }
  button.start { border-color: var(--green); color: var(--green); }
  button.stop { border-color: var(--red); color: var(--red); }
  button.go { border-color: var(--accent); color: var(--accent); }
  button.retire { border-color: var(--amber); color: var(--amber); font-size: .78rem; padding: .3rem .5rem; }
  button.closebtn { border-color: var(--muted); color: var(--muted); font-size: .78rem; padding: .3rem .5rem; }
  button.handover { border-color: var(--accent); color: var(--accent); font-size: .78rem; padding: .3rem .5rem; }
  .unreg-badge { font-size: .65rem; color: var(--amber); border: 1px solid var(--amber);
                 border-radius: 4px; padding: 1px 4px; margin-left: .3rem; cursor: help; }
  button.reactivate { border-color: var(--green); color: var(--green); }
  button.addtoggle { display: block; width: 100%; text-align: left; border-color: var(--accent); color: var(--accent); margin: .5rem 0; }
  button:disabled { opacity: .5; cursor: default; }
  .actioncell { display: flex; gap: .35rem; flex-wrap: wrap; }
  .opts-row td { background: var(--panel2); padding: .6rem .5rem; }
  .opts { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
  .modes { flex-basis: 100%; display: flex; flex-wrap: wrap; gap: .25rem 1.2rem; margin-bottom: .3rem; }
  .mode-radio { display: flex; align-items: center; gap: .3rem; font-size: .82rem; color: var(--text); }
  .opts-hint { flex-basis: 100%; font-size: .78rem; color: var(--muted); min-height: 1em; }
  .opts label { color: var(--muted); font-size: .75rem; display: flex; flex-direction: column; gap: .15rem; }
  #layoutPanel { background: var(--panel2); border-radius: 6px; padding: .7rem; margin-bottom: .5rem; }
  #layoutPanel input[type=text] { min-width: 220px; }
  .layout-result { font-size: .78rem; color: var(--muted); white-space: pre-wrap; margin: 0; }
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <h1 id="pageTitle">claudeops</h1>
    <div class="langsw">
      <button id="langTr" onclick="setLang('tr')">TR</button>
      <button id="langEn" onclick="setLang('en')">EN</button>
    </div>
  </div>
  <div class="sub" id="summary">…</div>
  <div id="banners"></div>
  <div class="tablewrap">
  <table>
    <thead><tr>
      <th style="width:11%" id="thName">–</th>
      <th style="width:15%">model</th>
      <th style="width:9%" id="thStatus">–</th>
      <th style="width:6%">cpu%</th>
      <th style="width:8%" id="thKind">–</th>
      <th>cwd</th>
      <th style="width:9%"></th>
    </tr></thead>
    <tbody id="rows"><tr><td colspan="7">…</td></tr></tbody>
  </table>
  </div>

  <button class="addtoggle" onclick="toggleAddPanel()"><span id="addToggleLabel">…</span></button>
  <div id="addBox"></div>

  <button class="addtoggle" onclick="toggleClosedPanel()"><span id="closedToggleLabel">…</span></button>
  <div id="closedBox"></div>

  <button class="addtoggle" onclick="toggleRetiredPanel()"><span id="retiredToggleLabel">…</span></button>
  <div id="retiredBox"></div>

  <button class="addtoggle" onclick="toggleLayoutPanel()"><span id="layoutToggleLabel">…</span> <span id="layoutDesc"></span></button>
  <div id="layoutBox"></div>
</div>
<script>
const T = {
  tr: {
    title: 'claudeops — filo kontrolü',
    loading: 'yükleniyor…',
    colName: 'isim', colStatus: 'durum', colKind: 'tür',
    serverUnreachable: 'sunucuya ulaşılamadı: ',
    authError: `401 — token eksik/yanlış (URL'ye doğru ?token=... ekleyin)`,
    authErrorShort: '401 — token eksik/yanlış',
    unexpectedResponse: (code) => `beklenmeyen yanıt (http ${code}) — bu tünel/URL artık geçerli olmayabilir, güncel linki kontrol edin`,
    runningWord: 'çalışıyor', configWord: 'config',
    dupWarn: '⚠ DUP: ',
    pidWord: 'pid ', stoppedWord: 'durdu',
    optionsBtn: 'seçenekler ▾', startBtn: 'başlat ▾', stopBtn: 'durdur',
    closeBtn: 'kapat', retireBtn: 'emekli et', handoverBtn: 'handover',
    handoverConfirm: (name) => `${name}: handover yapılsın mı? Session'a wrap-up mesajı gönderilir (CLAUDE.md/TODO.md/DONE.md güncellensin, commit+push edilsin diye), önce durdurulur sonra AYNI geçmişle (--resume) bu mesajla yeniden açılır. Yanıtı bekleyin, TAMAMLANMADAN tekrar durdurmayın.`,
    handingOver: 'handover gönderiliyor…',
    registerBtn: 'kaydet', unregBadge: 'kayıtsız',
    unregHint: 'roster.tsv\\'de kayıtlı değil (proc-scan\\'den bulundu) — claudeops\\'un açmadığı bir pencere; "devral"a basarsanız remote-control eklenip roster\\'a kalıcı kaydedilir',
    cwdHint: 'tıkla: tam yolu göster/gizle',
    adoptBtn: 'devral (remote ekle)',
    adoptWarn: (name) => `⚠ ${name} claudeops'un açmadığı bir pencere (elle/başka yerden açılmış). "devral" bu pencereyi KAPATIR ve seçtiğiniz isimle AYRI, YENİ bir pencerede --remote-control ile açar (aynı geçmişle, --resume) — şu an baktığınız pencerenin kendisi değil, yeni bir pencere.`,
    adoptNameLabel: 'yeni isim (remote-control adı)',
    adopting: 'devralınıyor… (~10-20s)',
    adopted: 'devralındı, yeni isim: ',
    nothingRunning: `Hiçbir şey çalışmıyor — aşağıdaki "+ Ekle"den başlatın.`,
    addToggle: '+ Ekle', registeredClosed: 'kayıtlı, kapalı',
    closedToggle: 'Kapalı', retiredToggle: 'Emekli', layoutToggle: 'Layout',
    layoutDesc: `X11 masaüstü — Wayland'da/kilitli ekranda çalışmaz`,
    layoutMissingPrefix: '⚠ eksik: ', layoutMissingSuffix: ' — kurmak için: sudo apt install -y ',
    layoutPinLabel: `pin (ws0'a sabit, virgülle)`,
    layoutGroupsLabel: `group'lar ( | ile ayrılmış birden fazla grup, her grup virgüllü)`,
    layoutClaudeOnly: 'sadece claude pencereleri',
    layoutDryRun: 'sadece planı göster (uygulama)',
    layoutApply: 'layout uygula', layoutApplying: 'uygulanıyor…',
    windowsWord: 'pencere', skippedWord: 'atlandı',
    requestFailed: 'istek başarısız: ',
    noneRegisteredClosed: `Kayıtlı-ama-kapalı proje yok.`,
    registerTitle: '+ Yeni proje kaydet',
    registerDesc: `(klasörü roster'a ekler, başlatmaz — sonra "+Ekle" listesinden başlatırsınız)`,
    registerNameLabel: 'isim (küçük harf, rakam, _)',
    registerCwdLabel: 'klasör (tam yol)',
    registerSave: 'kaydet', registerSaving: 'kaydediliyor…',
    empty: 'Boş.', reactivateBtn: 'tekrar işe al + başlat',
    modeResume: 'devam ettir', modeReset: 'sıfırla ve başlat', modeNewchat: 'yeni chat aç',
    modeChoiceNewchatOnly: 'Ayrı yeni chat aç (mevcuduna dokunmaz)',
    modeChoiceResume: 'Devam ettir (kaldığı yerden)',
    modeChoiceReset: `Bu ismi SIFIRLA (--new, geçmiş bir daha görünmez)`,
    modeChoiceNewchat: 'Ayrı yeni chat aç (yeni isimle, mevcuduna dokunmaz)',
    runningNote: (name) => `⚠ ${name} şu an ÇALIŞIYOR — devam ettirmek/sıfırlamak için önce "durdur"a basın. Buradaki tek seçenek AYRI, ek bir chat açar, mevcut ${name}'a dokunmaz.`,
    pmLabel: 'permission-mode', effortLabel: 'effort', modelLabel: 'model',
    cancelBtn: 'vazgeç',
    autoNameHint: (name, date) => `isim otomatik: ${name}${date} (çakışırsa _1, _2…)`,
    starting: 'başlıyor…', newChatStarted: 'yeni chat başlatıldı: ',
    stopping: 'durduruluyor… (~10s)',
    retireConfirm: (name) => `${name}: emekli edilsin mi? (çalışıyorsa önce durdurulur, models.tsv+roster.tsv'de yorumlanır — geri almak için "tekrar işe al" ile mümkün)`,
    retiring: 'emekli ediliyor…',
    closeConfirm: (name) => `${name}: kapatılsın mı? (çalışıyorsa önce durdurulur, sadece models.tsv yorumlanır — cwd hatırlanır, "tekrar işe al" ile kolayca geri gelir)`,
    closing: 'kapatılıyor…',
  },
  en: {
    title: 'claudeops — fleet control',
    loading: 'loading…',
    colName: 'name', colStatus: 'status', colKind: 'kind',
    serverUnreachable: 'server unreachable: ',
    authError: `401 — token missing/invalid (add ?token=... to the URL)`,
    authErrorShort: '401 — token missing/invalid',
    unexpectedResponse: (code) => `unexpected response (http ${code}) — this tunnel/URL may no longer be valid, check the current link`,
    runningWord: 'running', configWord: 'config',
    dupWarn: '⚠ DUP: ',
    pidWord: 'pid ', stoppedWord: 'stopped',
    optionsBtn: 'options ▾', startBtn: 'start ▾', stopBtn: 'stop',
    closeBtn: 'close', retireBtn: 'retire', handoverBtn: 'handover',
    handoverConfirm: (name) => `${name}: run handover? Sends the session a wrap-up prompt (to update CLAUDE.md/TODO.md/DONE.md and commit+push), stopping it first and reopening it with the SAME history (--resume) plus this message. Wait for its reply — don't stop it again before it finishes.`,
    handingOver: 'sending handover…',
    registerBtn: 'register', unregBadge: 'unregistered',
    unregHint: 'not in roster.tsv (found via proc-scan) — a window claudeops didn\\'t open; click "adopt" to attach remote-control and register it permanently',
    cwdHint: 'click: show/hide full path',
    adoptBtn: 'adopt (attach remote)',
    adoptWarn: (name) => `⚠ ${name} is a window claudeops didn't open (started by hand/elsewhere). "adopt" will CLOSE this window and open a SEPARATE, NEW window under the name you choose, with --remote-control (same history, --resume) — not this exact window, a new one.`,
    adoptNameLabel: 'new name (remote-control name)',
    adopting: 'adopting… (~10-20s)',
    adopted: 'adopted, new name: ',
    nothingRunning: `Nothing running — start something from "+ Add" below.`,
    addToggle: '+ Add', registeredClosed: 'registered, stopped',
    closedToggle: 'Closed', retiredToggle: 'Retired', layoutToggle: 'Layout',
    layoutDesc: `X11 desktop — does not work on Wayland/locked screen`,
    layoutMissingPrefix: '⚠ missing: ', layoutMissingSuffix: ' — install with: sudo apt install -y ',
    layoutPinLabel: 'pin (fixed to ws0, comma-separated)',
    layoutGroupsLabel: 'groups ( | -separated, each group comma-separated)',
    layoutClaudeOnly: 'claude windows only',
    layoutDryRun: 'show plan only (no changes)',
    layoutApply: 'apply layout', layoutApplying: 'applying…',
    windowsWord: 'windows', skippedWord: 'skipped',
    requestFailed: 'request failed: ',
    noneRegisteredClosed: 'No registered-but-closed projects.',
    registerTitle: '+ Register new project',
    registerDesc: `(adds the folder to the roster, does not start it — start it later from the "+ Add" list)`,
    registerNameLabel: 'name (lowercase, digits, _)',
    registerCwdLabel: 'folder (full path)',
    registerSave: 'save', registerSaving: 'saving…',
    empty: 'Empty.', reactivateBtn: 'reactivate + start',
    modeResume: 'resume', modeReset: 'reset and start', modeNewchat: 'start new chat',
    modeChoiceNewchatOnly: 'Start a separate new chat (does not touch the existing one)',
    modeChoiceResume: 'Resume (from where it left off)',
    modeChoiceReset: 'RESET this name (--new, previous history no longer shown)',
    modeChoiceNewchat: 'Start a separate new chat (new name, does not touch the existing one)',
    runningNote: (name) => `⚠ ${name} is currently RUNNING — click "stop" first to resume/reset. The only option here starts a SEPARATE extra chat, it does not touch the existing ${name}.`,
    pmLabel: 'permission-mode', effortLabel: 'effort', modelLabel: 'model',
    cancelBtn: 'cancel',
    autoNameHint: (name, date) => `name auto-generated: ${name}${date} (adds _1, _2… on conflict)`,
    starting: 'starting…', newChatStarted: 'new chat started: ',
    stopping: 'stopping… (~10s)',
    retireConfirm: (name) => `${name}: retire it? (stopped first if running, comments out models.tsv+roster.tsv — reversible via "reactivate")`,
    retiring: 'retiring…',
    closeConfirm: (name) => `${name}: close it? (stopped first if running, only comments out models.tsv — cwd is remembered, easy to bring back with "reactivate")`,
    closing: 'closing…',
  },
};
let LANG = localStorage.getItem('cops_lang') || (navigator.language.toLowerCase().startsWith('tr') ? 'tr' : 'en');
function t(key) { return T[LANG][key]; }
function setLang(lang) {
  LANG = lang;
  try { localStorage.setItem('cops_lang', lang); } catch (e) {}
  applyStaticText();
  render(LAST);
}
function applyStaticText() {
  document.title = t('title');
  document.getElementById('pageTitle').textContent = t('title');
  document.getElementById('thName').textContent = t('colName');
  document.getElementById('thStatus').textContent = t('colStatus');
  document.getElementById('thKind').textContent = t('colKind');
  document.getElementById('layoutDesc').textContent = '(' + t('layoutDesc') + ')';
  document.getElementById('langTr').classList.toggle('active', LANG === 'tr');
  document.getElementById('langEn').classList.toggle('active', LANG === 'en');
}

const TOKEN = new URLSearchParams(location.search).get('token') || '';
function withToken(url) {
  return url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN);
}
let LAST = null;
let LAST_JSON = null;
let optsFor = null;
let adoptFor = null;
let showAddPanel = false;
let showLayoutPanel = false;
let showClosedPanel = false;
let showRetiredPanel = false;

async function refresh() {
  let r;
  try {
    r = await fetch(withToken('/api/status'));
  } catch (e) {
    document.getElementById('summary').textContent = t('serverUnreachable') + e;
    return;
  }
  if (r.status === 401) {
    document.getElementById('summary').textContent = t('authError');
    return;
  }
  if (!r.ok || !(r.headers.get('content-type') || '').includes('application/json')) {
    document.getElementById('summary').textContent = t('unexpectedResponse')(r.status);
    return;
  }
  const d = await r.json();
  const dJson = comparableKey(d);
  if (dJson === LAST_JSON) return;  // veri değişmedi (cpu hariç) — DOM'a dokunma, açık panel/form korunur
  LAST_JSON = dJson;
  LAST = d;
  render(d);
}

function comparableKey(d) {
  // cpu sürekli kıpırdar (round(1) olsa da) — onu hariç tutmazsak "değişmedi" hemen hiç tetiklenmez.
  return JSON.stringify({...d, sessions: d.sessions.map(({cpu, ...rest}) => rest)});
}

function render(d) {
  const running = d.sessions.filter(s => s.running).length;
  document.getElementById('summary').textContent =
    running + '/' + d.sessions.length + ' ' + t('runningWord') + '  ·  ' + t('configWord') + ': ' + d.config_msg;

  const banners = [];
  if (!d.config_ok) banners.push('<div class="banner bad">⚠ ' + d.config_msg + '</div>');
  if (d.dups.length) banners.push('<div class="banner bad">' + t('dupWarn') + d.dups.join(', ') + '</div>');
  document.getElementById('banners').innerHTML = banners.join('');

  const runningSessions = d.sessions.filter(s => s.running);
  const stoppedSessions = d.sessions.filter(s => !s.running);

  const rows = [];
  for (const s of runningSessions) rows.push(...sessionRow(s, d));
  if (!runningSessions.length) {
    rows.push('<tr><td colspan="7" style="color:var(--muted)">' + t('nothingRunning') + '</td></tr>');
  }
  document.getElementById('rows').innerHTML = rows.join('');

  document.getElementById('addToggleLabel').textContent =
    (showAddPanel ? '▾' : '▸') + ' ' + t('addToggle') + ' (' + stoppedSessions.length + ' ' + t('registeredClosed') + ')';
  document.getElementById('addBox').innerHTML = showAddPanel ? renderAddBox(stoppedSessions, d) : '';

  document.getElementById('closedToggleLabel').textContent =
    (showClosedPanel ? '▾' : '▸') + ' ' + t('closedToggle') + ' (' + d.closed.length + ')';
  document.getElementById('closedBox').innerHTML = showClosedPanel ? groupTable(d.closed) : '';

  document.getElementById('retiredToggleLabel').textContent =
    (showRetiredPanel ? '▾' : '▸') + ' ' + t('retiredToggle') + ' (' + d.retired.length + ')';
  document.getElementById('retiredBox').innerHTML = showRetiredPanel ? groupTable(d.retired) : '';

  document.getElementById('layoutToggleLabel').textContent = (showLayoutPanel ? '▾ ' : '▸ ') + t('layoutToggle');
  document.getElementById('layoutBox').innerHTML = showLayoutPanel ? renderLayoutBox(d) : '';
}

function sessionRow(s, d) {
  const actions = s.registered === false
    ? `<button class="stop" onclick="act('${s.name}','stop',this)">${t('stopBtn')}</button>
       <button class="handover" onclick="doHandover('${s.name}', this)">${t('handoverBtn')}</button>
       <button class="start" onclick="toggleAdopt('${s.name}')">${t('adoptBtn')}</button>`
    : `${s.running ? `<button class="stop" onclick="act('${s.name}','stop',this)">${t('stopBtn')}</button>` : ''}
       <button class="start" onclick="toggleOpts('${s.name}')">${s.running ? t('optionsBtn') : t('startBtn')}</button>
       ${s.running ? `<button class="handover" onclick="doHandover('${s.name}', this)">${t('handoverBtn')}</button>` : ''}
       <button class="closebtn" onclick="doClose('${s.name}', this)">${t('closeBtn')}</button>
       <button class="retire" onclick="doRetire('${s.name}', this)">${t('retireBtn')}</button>`;
  const nameCell = s.registered === false
    ? `${s.name} <span class="unreg-badge" title="${t('unregHint')}">${t('unregBadge')}</span>`
    : s.name;
  const row = `
    <tr>
      <td>${nameCell}</td>
      <td>${s.model || ''}</td>
      <td><span class="dot ${s.running ? 'on' : 'off'}"></span>${s.running ? t('pidWord') + s.pid : t('stoppedWord')}</td>
      <td>${s.running ? s.cpu.toFixed(1) : '—'}</td>
      <td>${s.kind || '—'}</td>
      <td class="cwd" title="${t('cwdHint')}" onclick="this.classList.toggle('expanded')">${s.cwd}</td>
      <td><div class="actioncell">${actions}</div></td>
    </tr>`;
  if (s.registered === false && adoptFor === s.name) return [row, adoptOptsRow(s, d)];
  return (s.registered !== false && optsFor === s.name) ? [row, unifiedOptsRow(s, d)] : [row];
}

function toggleAdopt(name) {
  adoptFor = (adoptFor === name) ? null : name;
  render(LAST);
}

function adoptOptsRow(s, d) {
  const modelOpts = ['(' + (s.model || 'claude-sonnet-5') + ')', ...d.model_choices, '…']
    .map(m => `<option value="${m.startsWith('(') ? '' : m}">${m}</option>`).join('');
  const pmOpts = d.permission_modes.map(m => `<option ${m==='auto'?'selected':''}>${m}</option>`).join('');
  const efOpts = d.effort_levels.map(m => `<option ${m==='max'?'selected':''}>${m}</option>`).join('');
  return `
    <tr class="opts-row"><td colspan="7"><div class="opts">
      <span class="opts-hint">${t('adoptWarn')(s.name)}</span>
      <label>${t('adoptNameLabel')}
        <input type="text" id="adopt-name-${s.name}" value="${s.name}">
      </label>
      <label>${t('modelLabel')}
        <select id="adopt-model-${s.name}" onchange="this.nextElementSibling.style.display = this.value==='__other__' ? '' : 'none'">
          ${modelOpts.replace('value="…"', 'value="__other__"')}
        </select>
      </label>
      <input type="text" id="adopt-model-other-${s.name}" placeholder="model id" style="display:none">
      <label>${t('pmLabel')}
        <select id="adopt-pm-${s.name}">${pmOpts}</select>
      </label>
      <label>${t('effortLabel')}
        <select id="adopt-effort-${s.name}">${efOpts}</select>
      </label>
      <button class="go" onclick="doAdopt('${s.name}', this)">${t('adoptBtn')}</button>
      <button onclick="adoptFor=null; render(LAST)">${t('cancelBtn')}</button>
    </div></td></tr>`;
}

async function doAdopt(oldName, btn) {
  const newName = document.getElementById('adopt-name-' + oldName).value.trim();
  const modelSel = document.getElementById('adopt-model-' + oldName).value;
  const modelOther = document.getElementById('adopt-model-other-' + oldName).value;
  const model = modelSel === '__other__' ? modelOther : modelSel;
  const permission_mode = document.getElementById('adopt-pm-' + oldName).value;
  const effort = document.getElementById('adopt-effort-' + oldName).value;
  if (!confirm(t('adoptWarn')(oldName))) return;
  btn.disabled = true;
  btn.textContent = t('adopting');
  try {
    const r = await fetch(withToken('/api/adopt'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: oldName, new_name: newName, model, permission_mode, effort, lang: LANG}),
    });
    if (r.status === 401) { alert(t('authErrorShort')); }
    else {
      const d = await safeJson(r);
      if (!d.ok) alert(oldName + ': ' + d.error);
      else alert(t('adopted') + d.new_name);
    }
  } catch (e) {
    alert(t('requestFailed') + e.message);
  }
  adoptFor = null;
  refresh();
}

function toggleAddPanel() {
  showAddPanel = !showAddPanel;
  render(LAST);
}

function toggleLayoutPanel() {
  showLayoutPanel = !showLayoutPanel;
  render(LAST);
}

function toggleClosedPanel() {
  showClosedPanel = !showClosedPanel;
  render(LAST);
}

function toggleRetiredPanel() {
  showRetiredPanel = !showRetiredPanel;
  render(LAST);
}

function renderLayoutBox(d) {
  const missing = d.layout_missing_deps || [];
  const warn = missing.length
    ? `<span class="opts-hint" style="color:var(--red)">${t('layoutMissingPrefix')}${missing.join(', ')}${t('layoutMissingSuffix')}${missing.join(' ')}</span>`
    : '<span class="opts-hint"></span>';
  return `
    <div class="opts" id="layoutPanel">
      ${warn}
      <label>${t('layoutPinLabel')}
        <input type="text" id="layout-pin" placeholder="co,rustrino,anomaly,iggy">
      </label>
      <label>${t('layoutGroupsLabel')}
        <input type="text" id="layout-groups" placeholder="hc,hcr,evolvi | vc,vrk">
      </label>
      <label class="fresh-toggle"><input type="checkbox" id="layout-claude-only" checked> ${t('layoutClaudeOnly')}</label>
      <label class="fresh-toggle"><input type="checkbox" id="layout-dry"> ${t('layoutDryRun')}</label>
      <button class="go" id="layout-go" ${missing.length ? 'disabled' : ''} onclick="doLayout(this)">${t('layoutApply')}</button>
    </div>
    <pre id="layout-result" class="layout-result"></pre>`;
}

function renderAddBox(stoppedSessions, d) {
  const rows = [];
  for (const s of stoppedSessions) rows.push(...sessionRow(s, d));
  const table = stoppedSessions.length
    ? `<div class="tablewrap"><table><tbody>${rows.join('')}</tbody></table></div>`
    : `<div class="opts-hint">${t('noneRegisteredClosed')}</div>`;
  return `<div id="addBoxInner">${table}${newProjectForm(d)}</div>`;
}

function newProjectForm(d) {
  const modelOpts = d.model_choices.map(m => `<option>${m}</option>`).join('');
  return `
    <div class="opts" style="margin-top:.5rem">
      <span class="opts-hint"><b>${t('registerTitle')}</b> ${t('registerDesc')}</span>
      <label>${t('registerNameLabel')}
        <input type="text" id="reg-name" placeholder="myproject">
      </label>
      <label>${t('registerCwdLabel')}
        <input type="text" id="reg-cwd" placeholder="/home/user/work/myproject">
      </label>
      <label>${t('modelLabel')}
        <select id="reg-model">${modelOpts}</select>
      </label>
      <button class="go" onclick="doRegister(this)">${t('registerSave')}</button>
    </div>`;
}

async function doRegister(btn) {
  const name = document.getElementById('reg-name').value.trim();
  const cwd = document.getElementById('reg-cwd').value.trim();
  const model = document.getElementById('reg-model').value;
  btn.disabled = true;
  btn.textContent = t('registerSaving');
  try {
    const r = await fetch(withToken('/api/register'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, cwd, model, lang: LANG}),
    });
    if (r.status === 401) { alert(t('authErrorShort')); }
    else {
      const d = await safeJson(r);
      if (!d.ok) alert(name + ': ' + d.error);
    }
  } catch (e) {
    alert(t('requestFailed') + e.message);
  }
  btn.disabled = false;
  btn.textContent = t('registerSave');
  refresh();
}

function groupTable(items) {
  if (!items.length) return `<div class="opts-hint">${t('empty')}</div>`;
  const rows = items.map(it => `
    <tr>
      <td style="width:14%">${it.name}</td>
      <td style="width:20%">${it.model || ''}</td>
      <td class="cwd" title="${t('cwdHint')}" onclick="this.classList.toggle('expanded')">${it.cwd}</td>
      <td style="width:16%"><button class="reactivate" onclick="doReactivate('${it.name}', this)">${t('reactivateBtn')}</button></td>
    </tr>`).join('');
  return `<div class="tablewrap"><table><tbody>${rows}</tbody></table></div>`;
}

function modeLabels() { return {resume: t('modeResume'), reset: t('modeReset'), newchat: t('modeNewchat')}; }

function unifiedOptsRow(s, d) {
  const modelOpts = ['(' + s.model + ')', ...d.model_choices, '…']
    .map(m => `<option value="${m.startsWith('(') ? '' : m}">${m}</option>`).join('');
  const pmOpts = d.permission_modes.map(m => `<option ${m==='auto'?'selected':''}>${m}</option>`).join('');
  const efOpts = d.effort_levels.map(m => `<option ${m==='max'?'selected':''}>${m}</option>`).join('');
  const modeChoices = s.running
    ? [['newchat', t('modeChoiceNewchatOnly')]]
    : [
        ['resume', t('modeChoiceResume')],
        ['reset', t('modeChoiceReset')],
        ['newchat', t('modeChoiceNewchat')],
      ];
  const radios = modeChoices.map(([val, label], i) => `
      <label class="mode-radio"><input type="radio" name="mode-${s.name}" value="${val}" ${i===0?'checked':''} onchange="updateGoLabel('${s.name}')"> ${label}</label>`).join('');
  const runningNote = s.running
    ? `<span class="opts-hint">${t('runningNote')(s.name)}</span>`
    : '';
  return `
    <tr class="opts-row"><td colspan="7"><div class="opts">
      ${runningNote}
      <div class="modes">${radios}</div>
      <span class="opts-hint" id="opt-hint-${s.name}"></span>
      <label>${t('modelLabel')}
        <select id="opt-model-${s.name}" onchange="this.nextElementSibling.style.display = this.value==='__other__' ? '' : 'none'">
          ${modelOpts.replace('value="…"', 'value="__other__"')}
        </select>
      </label>
      <input type="text" id="opt-model-other-${s.name}" placeholder="model id" style="display:none">
      <label>${t('pmLabel')}
        <select id="opt-pm-${s.name}">${pmOpts}</select>
      </label>
      <label>${t('effortLabel')}
        <select id="opt-effort-${s.name}">${efOpts}</select>
      </label>
      <button class="go" id="opt-go-${s.name}" onclick="doAction('${s.name}', this)">${modeLabels()[modeChoices[0][0]]}</button>
      <button onclick="optsFor=null; render(LAST)">${t('cancelBtn')}</button>
    </div></td></tr>`;
}

function toggleOpts(name) {
  optsFor = (optsFor === name) ? null : name;
  render(LAST);
  if (optsFor === name) updateGoLabel(name);
}

function updateGoLabel(name) {
  const checked = document.querySelector(`input[name="mode-${name}"]:checked`);
  const mode = checked ? checked.value : 'resume';
  document.getElementById('opt-go-' + name).textContent = modeLabels()[mode];
  const hint = document.getElementById('opt-hint-' + name);
  hint.textContent = mode === 'newchat' ? t('autoNameHint')(name, todayStr()) : '';
}

function todayStr() {
  const d = new Date();
  return d.getFullYear() + String(d.getMonth()+1).padStart(2,'0') + String(d.getDate()).padStart(2,'0');
}

async function doAction(name, btn) {
  const checked = document.querySelector(`input[name="mode-${name}"]:checked`);
  const mode = checked ? checked.value : 'resume';
  const modelSel = document.getElementById('opt-model-' + name).value;
  const modelOther = document.getElementById('opt-model-other-' + name).value;
  const model = modelSel === '__other__' ? modelOther : modelSel;
  const permission_mode = document.getElementById('opt-pm-' + name).value;
  const effort = document.getElementById('opt-effort-' + name).value;
  btn.disabled = true;
  btn.textContent = t('starting');
  if (mode === 'newchat') {
    try {
      const r = await fetch(withToken('/api/new-chat'), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({base: name, model, permission_mode, effort, lang: LANG}),
      });
      if (r.status === 401) { alert(t('authErrorShort')); }
      else {
        const d = await safeJson(r);
        if (d.ok) alert(t('newChatStarted') + d.name);
        else alert(name + ': ' + d.error);
      }
    } catch (e) {
      alert(t('requestFailed') + e.message);
    }
  } else {
    await call('start', {name, model, permission_mode, effort, fresh: mode === 'reset'});
  }
  optsFor = null;
  refresh();
}

async function act(name, action, btn) {
  btn.disabled = true;
  btn.textContent = action === 'start' ? t('starting') : t('stopping');
  await call(action, {name});
  refresh();
}

async function doRetire(name, btn) {
  if (!confirm(t('retireConfirm')(name))) return;
  btn.disabled = true;
  btn.textContent = t('retiring');
  await call('retire', {name});
  refresh();
}

async function doClose(name, btn) {
  if (!confirm(t('closeConfirm')(name))) return;
  btn.disabled = true;
  btn.textContent = t('closing');
  await call('close', {name});
  refresh();
}

async function doHandover(name, btn) {
  if (!confirm(t('handoverConfirm')(name))) return;
  btn.disabled = true;
  btn.textContent = t('handingOver');
  await call('handover', {name, lang: LANG});
  refresh();
}

async function doReactivate(name, btn) {
  btn.disabled = true;
  btn.textContent = t('starting');
  await call('reactivate', {name});
  refresh();
}

async function safeJson(r) {
  if (!r.ok || !(r.headers.get('content-type') || '').includes('application/json')) {
    throw new Error(t('unexpectedResponse')(r.status));
  }
  return r.json();
}

async function call(action, payload) {
  try {
    const r = await fetch(withToken('/api/' + action), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({...payload, lang: LANG}),
    });
    if (r.status === 401) { alert(t('authErrorShort')); return; }
    const d = await safeJson(r);
    if (!d.ok) alert(payload.name + ': ' + d.error);
  } catch (e) {
    alert(t('requestFailed') + e.message);
  }
}

async function doLayout(btn) {
  const pin = document.getElementById('layout-pin').value.trim();
  const groups = document.getElementById('layout-groups').value
    .split('|').map(g => g.trim()).filter(g => g);
  const claude_only = document.getElementById('layout-claude-only').checked;
  const dry_run = document.getElementById('layout-dry').checked;
  const resultBox = document.getElementById('layout-result');
  btn.disabled = true;
  btn.textContent = t('layoutApplying');
  resultBox.textContent = '';
  try {
    const r = await fetch(withToken('/api/layout'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pin, groups, claude_only, dry_run, lang: LANG}),
    });
    if (r.status === 401) { alert(t('authErrorShort')); }
    else {
      const d = await safeJson(r);
      if (d.ok) {
        const lines = [(dry_run ? '[dry-run] ' : '') + d.total + ' ' + t('windowsWord') + ', ' + d.skipped + ' ' + t('skippedWord')];
        for (const a of d.assignments) lines.push('  ' + a.name + ' → ws' + a.ws + ' (' + a.x + ',' + a.y + ')');
        resultBox.textContent = lines.join('\\n');
      } else {
        resultBox.textContent = '✗ ' + d.error;
      }
    }
  } catch (e) {
    resultBox.textContent = '✗ ' + t('requestFailed') + e.message;
  }
  btn.disabled = false;
  btn.textContent = t('layoutApply');
}

applyStaticText();
refresh();
setInterval(refresh, 4000);
</script>
</body>
</html>
"""

UNAUTHORIZED_HTML = (
    b"<!doctype html><meta charset=utf-8><body style='font:14px monospace;padding:2rem'>"
    b"401 &mdash; token eksik/yanlis. URL'ye <code>?token=...</code> ekleyin.<br>"
    b"401 &mdash; token missing/invalid. Add <code>?token=...</code> to the URL.</body>"
)


class _Handler(BaseHTTPRequestHandler):
    server_version = "claudeops-web/1"
    token = ""  # run() içinde atanır

    def log_message(self, fmt, *a):
        pass  # stdout'u kirletme — sessiz

    def _authorized(self) -> bool:
        qs = parse_qs(urlparse(self.path).query)
        given = (qs.get("token") or [""])[0]
        return secrets.compare_digest(given, self.token)

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _unauthorized(self):
        self.send_response(401)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(UNAUTHORIZED_HTML)))
        self.end_headers()
        self.wfile.write(UNAUTHORIZED_HTML)

    def do_GET(self):
        if not self._authorized():
            self._unauthorized()
            return
        path = urlparse(self.path).path
        if path == "/":
            body = PAGE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/status":
            self._json(_status_payload())
        else:
            self._json({"error": "not found"}, status=404)

    def do_POST(self):
        if not self._authorized():
            self._unauthorized()
            return
        path = urlparse(self.path).path
        if path not in ("/api/start", "/api/stop", "/api/retire", "/api/reactivate",
                         "/api/new-chat", "/api/layout", "/api/register", "/api/close",
                         "/api/handover", "/api/adopt"):
            self._json({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            # lang bilinemiyor (body hiç parse edilemedi) — iki dilde birden göster
            self._json({"ok": False, "error": "geçersiz JSON / invalid JSON"}, status=400)
            return

        lang = "en" if data.get("lang") == "en" else "tr"

        if path == "/api/layout":
            groups = data.get("groups", [])
            if not isinstance(groups, list):
                groups = [str(groups)]
            self._json(_run_layout(
                pin=str(data.get("pin", "")),
                groups=[str(g) for g in groups],
                claude_only=bool(data.get("claude_only", True)),
                dry_run=bool(data.get("dry_run", False)),
                lang=lang,
            ))
            return

        if path == "/api/new-chat":
            base = str(data.get("base", "")).strip()
            if not base:
                self._json(_err(lang, "base_required"), status=400)
                return
            self._json(_new_chat(
                base,
                model=str(data.get("model", "")),
                permission_mode=str(data.get("permission_mode", "")),
                effort=str(data.get("effort", "")),
                lang=lang,
            ))
            return

        if path == "/api/register":
            self._json(_register_project(
                name=str(data.get("name", "")),
                cwd=str(data.get("cwd", "")),
                model=str(data.get("model", "")),
                lang=lang,
            ))
            return

        if path == "/api/adopt":
            old_name = str(data.get("name", "")).strip()
            if not old_name:
                self._json(_err(lang, "name_required"), status=400)
                return
            self._json(_adopt(
                old_name,
                new_name=str(data.get("new_name", "")),
                model=str(data.get("model", "")),
                permission_mode=str(data.get("permission_mode", "")),
                effort=str(data.get("effort", "")),
                lang=lang,
            ))
            return

        name = str(data.get("name", "")).strip()
        if not name:
            self._json(_err(lang, "name_required"), status=400)
            return
        if path == "/api/start":
            result = _start(
                name,
                model=str(data.get("model", "")),
                permission_mode=str(data.get("permission_mode", "")),
                effort=str(data.get("effort", "")),
                fresh=bool(data.get("fresh", False)),
                lang=lang,
            )
        elif path == "/api/stop":
            result = _stop(name, lang=lang)
        elif path == "/api/retire":
            result = _retire(name, lang=lang)
        elif path == "/api/close":
            result = _close_project(name, lang=lang)
        elif path == "/api/handover":
            result = _handover(name, lang=lang)
        else:
            result = _reactivate_and_start(name, lang=lang)
        self._json(result)


def register(sub):
    p = sub.add_parser("web", help="yerel kontrol paneli (fleet'i tarayıcıdan/tünelden başlat-durdur)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--host", default=DEFAULT_HOST,
                   help=f"varsayılan {DEFAULT_HOST} (localhost). Tünel (cloudflared/ssh -L vb.) "
                        "için değiştirmeye gerek yok — tünel zaten localhost'a proxy eder.")
    p.add_argument("--print-token", action="store_true", help="sadece token'ı yazdır ve çık")
    p.add_argument("--tunnel", action="store_true",
                   help="cloudflared quick tunnel ile de dışarı aç (login gerekmez, URL her başlatmada değişir)")
    p.set_defaults(func=run)


def run(args) -> int:
    token = _load_or_create_token()
    if args.print_token:
        print(token)
        return 0

    tunnel_proc = None
    if args.tunnel:
        cloudflared_path = _ensure_cloudflared()
        if not cloudflared_path:
            return 1
        print("cloudflared tünel başlatılıyor…")
        tunnel_proc, tunnel_url = _start_tunnel(args.port, cloudflared_path)
        if tunnel_url:
            print(f"  tünel  →  {tunnel_url}/?token={token}")
        else:
            print(f"  ⚠ tünel URL'i {TUNNEL_LOG} içinde bulunamadı (20s) — log'a bak, süreç yine de ayakta olabilir.")

    _Handler.token = token
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    url = f"http://{args.host}:{args.port}/?token={token}"
    print(f"claudeops web  →  {url}")
    print(f"  token dosyası: {TOKEN_FILE} (chmod 600)")
    print("  Ctrl-C ile durdur.")
    if args.host not in ("127.0.0.1", "localhost"):
        print(f"  ⚠ {args.host}: localhost dışına bind — token olsa bile gereksiz risk, gerekmedikçe kullanma.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nkapatılıyor…")
    finally:
        server.server_close()
        if tunnel_proc is not None:
            tunnel_proc.terminate()
    return 0
