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
import mimetypes
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

import psutil

from ..config import validate_config
from ..diaglog import diag_log, diag_log_tail, diag_log_recent_fallback_count
from ..discovery import find_sessions, duplicates
from ..guard import guard_lock
from ..handover import HANDOVER_MSG_DEFAULT, HANDOVER_MSG_DEFAULT_EN
from ..kill import kill_session, kill_session_and_parent, KILL_GRACE_SECONDS
from ..needs_ho import needs_ho
from ..session import Session
from ..paths import CLAUDEOPS_DIR, MODELS_TSV, REPO_DIR, ROSTER_TSV, VENDOR_DIR
from ..spawn import spawn_session, detect_display, find_latest_jsonl, open_window
from ..providers import PROVIDERS, DEFAULT_CLI, get_provider
from ..tmux_backend import (
    is_tmux_backed, tmux_has_session, tmux_capture, tmux_send_keys,
    tmux_send_special_key, tmux_pane_size, ALLOWED_SPECIAL_KEYS,
)
from .web_static import resolve_static_path
from . import web_ws

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"
TOKEN_FILE = os.path.join(CLAUDEOPS_DIR, "web.token")
TUNNEL_LOG = os.path.join(CLAUDEOPS_DIR, "tunnel.log")
_TUNNEL_URL_RE = re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com")

# [[spawn-zombie-child-degrades-web-server]] — bu process'in kendi yaşı ("Tanı"
# sekmesinde gösterilir) iki bilinen sessiz-spawn-başarısızlığı sebebinden biri.
_WEB_PROC_START_MONO = time.monotonic()

# Model/permission-mode/effort seçenekleri artık HER provider kendi
# model_choices()/permission_modes()/effort_levels()'ından geliyor — burada
# sabit bir liste/`if cli==...` YOK, bkz. _status_payload()'daki "cli_options".

# API hata mesajları TR/EN — panel dili EN'de olsa da backend hataları hep TR geliyordu
# (2026-08-25, kullanıcı: "uyarılar tr geliyor hep, ing seçilsin seçilmesin gibi"). do_POST
# artık `lang` alanını her isteğin body'sinden okuyup ilgili fonksiyona geçiyor; frontend her
# fetch çağrısına `lang: LANG` ekliyor.
ERR = {
    "invalid_name": {"tr": "geçersiz isim — küçük harf ile başlamalı, sadece a-z 0-9 _ içerebilir",
                      "en": "invalid name — must start with a lowercase letter, only a-z 0-9 _ allowed"},
    "already_registered": {"tr": "{name}: zaten kayıtlı (aktif/kapalı/emekli)",
                            "en": "{name}: already registered (active/closed/retired)"},
    "conflicts_running": {"tr": "{name}: çalışan '{other}' session'ıyla çakışıyor "
                                 "(tarih-suffix'li isimler taban isme indirgenir: {other} → {name}) — "
                                 "farklı bir isim seçin ya da önce o session'ı devral/yeniden adlandırın",
                           "en": "{name}: conflicts with running session '{other}' "
                                 "(date-suffixed names reduce to their base: {other} → {name}) — "
                                 "pick a different name, or adopt/rename that session first"},
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
    "already_closed": {"tr": "{name}: zaten devre dışı", "en": "{name}: already disabled"},
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
    "not_tmux_backed": {"tr": "{name}: tmux-backed değil (eski/bare session) — "
                              "terminal görünümü için handover/devral ile yeniden açın",
                         "en": "{name}: not tmux-backed (old/bare session) — "
                               "handover/adopt it to get a terminal view"},
    "term_session_gone": {"tr": "{name}: tmux session artık yok (kapanmış olabilir)",
                           "en": "{name}: tmux session no longer exists (may have closed)"},
    "invalid_key": {"tr": "geçersiz tuş", "en": "invalid key"},
    "gt_not_found": {"tr": "gnome-terminal-server çalışmıyor (zaten kapalı) — bir sonraki spawn otomatik açacak",
                      "en": "gnome-terminal-server isn't running (already down) — the next spawn will start it automatically"},
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


XTERM_VERSION = "5.3.0"  # jsdelivr'de mevcut en son stabil sürüm (5.5.0 yok — 404) — pinned, "latest" değil
XTERM_FILES = {
    "xterm.js": f"https://cdn.jsdelivr.net/npm/xterm@{XTERM_VERSION}/lib/xterm.js",
    "xterm.css": f"https://cdn.jsdelivr.net/npm/xterm@{XTERM_VERSION}/css/xterm.css",
}


def _ensure_xterm_assets() -> Optional[str]:
    """xterm.js/css'i VENDOR_DIR'e indir+önbelleğe al (ilk terminal-görünümü isteğinde).

    _ensure_cloudflared() ile aynı desen. Offline/indirilemezse None — çağıran taraf
    (frontend) düz-<pre> fallback'e düşer, hard error VERMEZ.
    """
    os.makedirs(VENDOR_DIR, exist_ok=True)
    ok = True
    for fname, url in XTERM_FILES.items():
        dest = os.path.join(VENDOR_DIR, fname)
        if os.path.exists(dest):
            continue
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as e:
            print(f"✗ xterm.js asset indirilemedi ({fname}: {e}) — terminal görünümü "
                  f"düz metne (fallback) düşecek")
            ok = False
    return VENDOR_DIR if ok else None


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


def _find_running(name: str, cli: Optional[str] = None) -> list:
    """Tam isim VEYA base eşleşmesiyle çalışan session'ları bul.

    rc.py'nin kill-first mantığıyla aynı desen ([[stale-tui-title-cross-suffix-resume]]
    tarzı): elle/eski tarih-suffix'li açılmış bir proc (`trino20260823`) roster'a
    temiz base isimle (`trino`) kaydedilse bile Session.base regex'i onu doğru
    eşler — çıplak `find_by_name` (tam isim) bunu KAÇIRIR → yanlışlıkla "duruyor"
    sanılıp ikinci bir proc spawn edilebilir.

    `cli` VERİLİRSE sadece o CLI'daki eşleşmeler sayılır (2026-08-28, kullanıcı:
    "agy de resume kendi içinde, claude de resume kendi içinde olmalı, ikisi farklı
    dosyalara bakıyor") — `Session.base` CLI'DAN BAĞIMSIZ regex'le indirgendiği için
    (`saseppr20260828`+`saseppr20260828_2` ikisi de base="saseppr"), cli-filtresiz hâli
    farklı CLI'ların aynı proje-base'ini yanlışlıkla ÇAKIŞMA sayar: claude çalışırken
    aynı base'e agy `resume` denince "zaten çalışıyor" derdi — oysa ikisi bağımsız
    süreç+geçmiş (claude: jsonl, agy: conversations-cache). Sadece `_start`'ın
    "zaten çalışıyor" KAPISI cli'ya duyarlı olmalı; stop/retire/handover/adopt gibi
    "burada ne varsa bul" çağrıları cli-agnostik KALMALI (o proc hangi cli'daysa onu
    bulmalılar) — bu yüzden `cli` opsiyonel, sadece `_start` geçiyor.
    """
    sessions = find_sessions(measure_cpu=False)
    if cli:
        sessions = [s for s in sessions if s.cli == cli]
    return [s for s in sessions if s.name == name or s.base == name]


# saniye — bir kere "çalışıyor" görülmek YETMEZ, o kadar süre KESİNTİSİZ ayakta
# kalmalı sayılsın. 2026-08-27 saseppr'da canlı bulundu: eski kod tek bir anlık
# görüşü "opened=True" sayıyordu — resume-guard hatasıyla saniyeler içinde ölen
# bir proc'u (bkz. [[resume-deferred-tool-marker]]) YANLIŞLIKLA başarı sayabilirdi
# (poll aralığı 1s'yle tam çakışırsa). Kullanıcı: "açıldı 5sn durmadan gitti ise
# yine hata desin."
STABLE_SECONDS = 5.0


def _wait_stable(name: str, timeout: float, stable_for: float = STABLE_SECONDS) -> bool:
    """`name` `timeout` saniye içinde belirip en az `stable_for` saniye KESİNTİSİZ
    çalışır durumda kalırsa True. Görünüp kaybolmayı (flash-then-die) sıfırlar,
    hiç kaybolmadan sonuna kadar giderse de True döner (deadline erken kesmesin)."""
    deadline = time.monotonic() + timeout
    first_seen = None
    while True:
        now = time.monotonic()
        if _find_running(name):
            if first_seen is None:
                first_seen = now
            elif now - first_seen >= stable_for:
                return True
        else:
            first_seen = None
        if now >= deadline:
            return False
        time.sleep(1.0)


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
        cli = rrow["rest"][2] if len(rrow["rest"]) >= 3 and rrow["rest"][2] in PROVIDERS else DEFAULT_CLI
        if mrow["active"] and rrow["active"]:
            state = "active"
        elif not mrow["active"] and not rrow["active"]:
            state = "retired"
        else:
            state = "closed"
        result[name] = {"cwd": cwd, "model": model, "cli": cli, "state": state}
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


def _register_project(name: str, cwd: str, model: str = "", cli: str = "", lang: str = "tr") -> dict:
    """UI'den yeni proje kaydı — roster.tsv+models.tsv'ye ekler, SPAWN ETMEZ.

    Sonra normal "+ Ekle" listesinden başlatılır (mevcut trino/oiso/line elle-ekleme
    akışının UI karşılığı).
    """
    name = name.strip()
    if not _NAME_VALID_RE.match(name):
        return _err(lang, "invalid_name")
    # Çakışma kaynağını AYIRT ET (2026-08-25): "cops" kaydı, o an çalışan
    # "cops20260824" yüzünden reddedilmişti (Session.base tarih-suffix'i indirger)
    # ama genel "zaten kayıtlı (aktif/kapalı/emekli)" mesajı kullanıcıyı roster'da
    # olmayan bir kaydı aramaya yolladı. Roster-çakışması ile çalışan-proc
    # çakışması artık ayrı mesajlar.
    roster_names = {r["name"] for r in _read_tsv_raw(ROSTER_TSV) if r["name"] != "name"}
    if name in roster_names:
        return _err(lang, "already_registered", name=name)
    for s in find_sessions(measure_cpu=False):
        if name in (s.name, s.base):
            return _err(lang, "conflicts_running", name=name, other=s.name)
    cwd = os.path.expanduser(cwd.strip())
    if not cwd or not os.path.isdir(cwd):
        return _err(lang, "dir_not_found", cwd=cwd or ("(boş)" if lang != "en" else "(empty)"))
    if "\t" in cwd or "\n" in cwd:
        return _err(lang, "cwd_bad_chars")
    chosen_cli = cli.strip() if cli.strip() in PROVIDERS else DEFAULT_CLI
    chosen_model = model.strip() or get_provider(chosen_cli).model_choices()[0]
    _append_tsv_line(ROSTER_TSV, [name, cwd, chosen_model, chosen_cli])
    _append_tsv_line(MODELS_TSV, [name, chosen_model])
    return {"ok": True}


def _new_chat(base: str, model: str = "", permission_mode: str = "", effort: str = "",
              cli: str = "", lang: str = "tr") -> dict:
    """`base`'in cwd'sinde YENİ, otomatik-isimli (tarih[+_N]) bir chat başlat.

    Var olan `base` session'ına DOKUNMAZ (çalışıyorsa bile) — ayrı, ek bir kayıt.
    Roster/models.tsv'ye hemen upsert edilir (görünür/yönetilebilir kalsın).
    """
    fleet = _fleet_status()
    info = fleet.get(base)
    if not info:
        return _err(lang, "base_not_in_roster", base=base)
    # base zaten tarih-suffix'li bir satırdan tıklanmışsa (ör. "saseppr20260827_1"
    # satırında "yeni sohbet"), tarihi olduğu gibi soneke eklemek KENDİ ÜSTÜNE
    # katlanır ("saseppr20260827_120260827", tekrarında daha da uzar). Session.base
    # ile aynı indirgeme (hc58→hc, cops20260824_1→cops) burada da uygulanıp gerçek
    # kısa base'e dönülür — 2026-08-27 saseppr'da canlı bulundu.
    new_name = _generate_new_chat_name(Session(name=base, pid=0).base or base)
    chosen_cli = cli.strip() if cli.strip() in PROVIDERS else info["cli"]
    chosen_model = model.strip() or info["model"]
    _append_tsv_line(ROSTER_TSV, [new_name, info["cwd"], chosen_model, chosen_cli])
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
                cli=chosen_cli,
            )
            opened = _wait_stable(new_name, timeout=HANDOVER_PROC_WAIT_SECONDS)
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


# ── Tanı (diagnostics) — [[spawn-zombie-child-degrades-web-server]] ─────────
# İki BAĞIMSIZ sessiz-spawn-başarısızlığı kaynağı canlı doğrulandı (2026-08-27):
# (a) bu web process'in kendi yaşı, (b) gnome-terminal-server'ın kendi yaşı
# (D-Bus-activated, TÜM `gnome-terminal` çağrılarının konuştuğu tek paylaşımlı
# server — spawn_session()'daki Popen bunu DEVNULL'a gizliyor, panelde sadece
# sessiz "start_no_proc" görünüyor). Bu sekme ikisini de görünür kılıp ikinci
# sebebi (a) sistem/hesaplama pahalı OLMAYAN pasif metriklerle (her /api/status
# poll'unda) ve (b) gerçek bir pencere açıp DEVNULL'suz hatayı yakalayan, SADECE
# tıklanınca çalışan aktif bir test'le ayırt eder.

# 2026-08-28: spawn.py artık gnome-terminal'i FALLBACK_RETRY_COUNT kez tekrar
# deniyor — tek bir fallback artık "ara sıra" bir flake sayılır (retry çoğunu
# sessizce yutar). Ama KISA sürede ARKA ARKAYA birden fazla tam-fallback (retry'lar
# DAHİL hepsi başarısız oldu demek) gnome-terminal-server'ın o an gerçekten
# sorunlu olduğuna işaret eder — kullanıcıya restart ÖNER (asla otomatik yapma,
# TÜM açık pencereleri kapatan yıkıcı bir işlem).
FALLBACK_ALERT_THRESHOLD = 2
FALLBACK_ALERT_WINDOW_MINUTES = 15.0


def _find_gnome_terminal_server() -> Optional[psutil.Process]:
    for p in psutil.process_iter(["cmdline"]):
        try:
            cmdline = p.info.get("cmdline") or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if any("gnome-terminal-server" in part for part in cmdline):
            return p
    return None


def _gnome_window_titles() -> set:
    """tmux.conf `set-titles-string '#S'` → tmux-backed pencere başlığı = session
    adının AYNISI (bkz. layout.py'nin aynı `wmctrl -l` deseni)."""
    try:
        r = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=5)
        titles = set()
        for line in r.stdout.splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4:
                titles.add(parts[3])
        return titles
    except Exception:
        return set()


def _diag_status() -> dict:
    """Her /api/status poll'unda (4s) çalışır — subprocess'ler ucuz/hızlı (wmctrl
    tek çağrı, /proc taramalar), aktif spawn-test/restart gibi pencere AÇMAZ."""
    gt = _find_gnome_terminal_server()
    gt_info = None
    if gt is not None:
        try:
            gt_info = {"pid": gt.pid, "uptime_seconds": round(time.time() - gt.create_time())}
        except psutil.NoSuchProcess:
            gt_info = None

    # "windowless" = tmux-backed ama görünür gnome-terminal penceresi YOK — ya
    # spawn.py'nin fallback'ı devrede (gnome-terminal o an bozuktu) ya da
    # gnome-terminal-server o session'ın penceresini kaybetti/kapattı sonradan.
    # wmctrl yoksa (LAYOUT_DEPS'te zaten uyarılıyor) None döner — "bilinmiyor",
    # boş liste (yanlış-pozitif "hepsi windowless") DEĞİL.
    windowless = None
    if shutil.which("wmctrl"):
        try:
            titles = _gnome_window_titles()
            windowless = [s.name for s in find_sessions(measure_cpu=False)
                          if is_tmux_backed(s.pid) and s.name not in titles]
        except Exception:
            windowless = None

    recent_fallbacks = diag_log_recent_fallback_count(FALLBACK_ALERT_WINDOW_MINUTES)
    return {
        "web_pid": os.getpid(),
        "web_uptime_seconds": round(time.monotonic() - _WEB_PROC_START_MONO),
        "gt": gt_info,
        "windowless": windowless,
        "recent_fallback_count": recent_fallbacks,
        "fallback_alert": recent_fallbacks >= FALLBACK_ALERT_THRESHOLD,
        "fallback_alert_window_minutes": FALLBACK_ALERT_WINDOW_MINUTES,
    }


def _diag_spawn_test(lang: str = "tr") -> dict:
    """gnome-terminal'i ÇIPLAK dene (spawn.py'nin DEVNULL'u YOK) — gerçek hatayı
    yakala. `bash -c "sleep 2"` kendi kendine kapanır, temizlik gerekmez."""
    title = f"cops-diag-{secrets.token_hex(4)}"
    try:
        proc = subprocess.run(
            ["gnome-terminal", "--window", f"--title={title}", "--", "bash", "-c", "sleep 2"],
            capture_output=True, text=True, timeout=6,
        )
    except FileNotFoundError:
        diag_log("spawn_test", ok=False, detail="gnome-terminal not installed")
        return {"ok": False, "stderr": "", "window_found": False,
                "detail": {"tr": "gnome-terminal kurulu değil", "en": "gnome-terminal is not installed"}[lang]}
    except subprocess.TimeoutExpired:
        diag_log("spawn_test", ok=False, detail="gnome-terminal hung >6s")
        return {"ok": False, "stderr": "", "window_found": False,
                "detail": {"tr": "gnome-terminal 6s içinde dönmedi (hang)",
                            "en": "gnome-terminal didn't return within 6s (hung)"}[lang]}

    stderr = (proc.stderr or "").strip()
    time.sleep(1.5)  # pencerenin xdotool'a görünmesi için kısa bekleme
    found = False
    try:
        r = subprocess.run(["xdotool", "search", "--name", title],
                            capture_output=True, text=True, timeout=5)
        found = bool(r.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    ok = found and not stderr
    diag_log("spawn_test", ok=ok, window_found=found, stderr=stderr[:500])
    return {"ok": ok, "stderr": stderr, "window_found": found}


def _diag_restart_gt(lang: str = "tr") -> dict:
    """gnome-terminal-server'ı öldür — D-Bus-activated, bir sonraki `gnome-terminal`
    çağrısında OTOMATİK yeniden doğuyor (elle başlatma gerekmez). Açık TÜM
    gnome-terminal pencerelerini kapatır (fleet + varsa ilgisiz başkaları) —
    altındaki tmux session'lar/claude process'leri ETKİLENMEZ (tmux server ayrı,
    bağımsız yaşıyor)."""
    gt = _find_gnome_terminal_server()
    if gt is None:
        return _err(lang, "gt_not_found")
    pid = gt.pid
    result = kill_session(pid, grace=5.0)
    diag_log("gt_restart", pid=pid, result=result)
    return {"ok": True, "result": result, "pid": pid}


def _diag_ask(cli: str, extra_question: str = "", lang: str = "tr") -> dict:
    """Diag bulgusunu, kullanıcının seçtiği desteklenen CLI ile YENİ bir fleet
    session'ında sor — roster'a normal bir session gibi kaydedilir, "Terminal"
    view'ından takip edilir (2026-08-27 kullanıcı isteği: kayıt-dışı bir sohbet
    kutusu DEĞİL, gerçek bir CLI/terminal)."""
    chosen_cli = cli.strip() if cli.strip() in PROVIDERS else DEFAULT_CLI
    provider = get_provider(chosen_cli)
    new_name = _generate_new_chat_name("diag")
    model = provider.model_choices()[0]

    status = _diag_status()
    lines = ["claudeops fleet spawn diagnostic — aşağıdaki canlı durumu incele, "
             "olası kök sebebi ve varsa somut bir fix öner:", ""]
    lines.append(f"- web sunucu: pid={status['web_pid']} uptime={status['web_uptime_seconds']}s")
    if status["gt"]:
        lines.append(f"- gnome-terminal-server: pid={status['gt']['pid']} uptime={status['gt']['uptime_seconds']}s")
    else:
        lines.append("- gnome-terminal-server: çalışmıyor")
    if status.get("windowless"):
        lines.append(f"- şu an penceresiz (tmux-fallback) çalışan session'lar: {', '.join(status['windowless'])}")
    recent = diag_log_tail(10)
    if recent:
        lines.append("- son diag-log kayıtları:")
        lines.extend(f"  {r}" for r in recent)
    lines.append("")
    lines.append(("Kullanıcının sorusu: " + extra_question.strip()) if extra_question.strip()
                  else "Kullanıcı ek bir soru yazmadı — genel bir teşhis/özet yeterli.")
    prompt = "\n".join(lines)

    _append_tsv_line(ROSTER_TSV, [new_name, REPO_DIR, model, chosen_cli])
    _append_tsv_line(MODELS_TSV, [new_name, model])
    try:
        with guard_lock(timeout=5.0):
            kind = spawn_session(
                name=new_name, cwd=REPO_DIR, model=model, display=detect_display(),
                permission_mode=provider.permission_modes()[0],
                effort=provider.effort_levels()[-1],
                force_new=True, prompt=prompt, cli=chosen_cli,
            )
            opened = _wait_stable(new_name, timeout=HANDOVER_PROC_WAIT_SECONDS)
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    if not opened:
        return _err(lang, "newchat_start_failed", new_name=new_name, kind=kind)
    diag_log("ask", name=new_name, cli=chosen_cli)
    return {"ok": True, "name": new_name, "kind": kind}


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


_NEEDSHO_CACHE: dict = {}  # name -> (expires_monotonic, bool)
_NEEDSHO_TTL = 30.0


def _needs_ho_cached(s) -> Optional[bool]:
    """Çalışan session için needs_ho — git-subprocess maliyetli, 30s cache'li.

    Kullanıcı isteği (2026-08-25): 'needs ho kontrolü tabloda olsun'. Hata
    durumunda None (UI '?' gösterir), False'la karıştırma.
    """
    now = time.monotonic()
    hit = _NEEDSHO_CACHE.get(s.name)
    if hit and hit[0] > now:
        return hit[1]
    try:
        val = needs_ho(s.sid or "", s.cwd, find_latest_jsonl(s.cwd))
    except Exception:
        val = None
    _NEEDSHO_CACHE[s.name] = (now + _NEEDSHO_TTL, val)
    return val


def _status_payload() -> dict:
    fleet = _fleet_status()
    all_live = find_sessions(measure_cpu=True)
    dups = duplicates(all_live)
    ok, msg = validate_config()

    # Canlı proc → roster satırı eşleme: önce TAM isim, sonra base (2026-08-26).
    # Eski hali sadece base-keyed dict'ti; iki sorunu vardı: (1) tam-isim satırı
    # olan proc (sase20260826) base satırını (sase) "running" gösteriyordu, kendi
    # satırı "durmuş" görünüyordu; (2) base satırı yeniden adlandırılınca
    # (sase→saseppr) canlı proc panelde tamamen GÖRÜNMEZ kalıyordu. Ayrıca
    # base-dict aynı base'in ikinci proc'unu yuttuğu için duplicates() hiç
    # tetiklenemiyordu — artık tüm canlı liste üzerinden sayılıyor.
    active_names = {n for n, i in fleet.items() if i["state"] == "active"}
    assigned = {}
    for s in all_live:
        if s.name in active_names:
            assigned[s.name] = s
    for s in all_live:
        if s.name not in active_names and s.base in active_names and s.base not in assigned:
            assigned[s.base] = s
    assigned_pids = {s.pid for s in assigned.values()}

    sessions, closed, retired = [], [], []
    for name in sorted(fleet):
        info = fleet[name]
        if info["state"] == "retired":
            retired.append({"name": name, "cwd": info["cwd"], "model": info["model"], "cli": info["cli"]})
            continue
        if info["state"] == "closed":
            closed.append({"name": name, "cwd": info["cwd"], "model": info["model"], "cli": info["cli"]})
            continue
        s = assigned.get(name)
        sessions.append({
            "name": name,
            "model": info["model"],
            "cwd": info["cwd"],
            "cli": info["cli"],
            "running": s is not None,
            "pid": s.pid if s else None,
            "cpu": round(s.cpu, 1) if s else None,
            "kind": ("fresh" if s.is_fresh else "resume") if s else None,
            "needs_ho": _needs_ho_cached(s) if s else None,
            "registered": True,
            "tmux": is_tmux_backed(s.pid) if s else False,
        })

    # Hiçbir AKTİF roster satırına bağlanamayan canlı session'lar (elle açılmış
    # ad-hoc bir şey, ya da adı sadece kapalı/emekli bir satıra denk gelen proc) —
    # "kayıtsız" olarak göster; hiçbir canlı proc panelde görünmez kalmasın.
    for s in all_live:
        if s.pid in assigned_pids:
            continue
        sessions.append({
            "name": s.name,
            "model": s.model or "?",
            "cwd": s.cwd,
            "cli": s.cli,
            "running": True,
            "pid": s.pid,
            "cpu": round(s.cpu, 1),
            "kind": "fresh" if s.is_fresh else "resume",
            "needs_ho": _needs_ho_cached(s),
            "registered": False,
            "tmux": is_tmux_backed(s.pid),
        })

    return {
        "config_ok": ok,
        "config_msg": msg,
        "dups": dups,
        "sessions": sessions,
        "closed": closed,
        "retired": retired,
        "cli_list": list(PROVIDERS.keys()),
        "cli_options": {
            name: {
                "models": p.model_choices(),
                "permission_modes": p.permission_modes(),
                "effort_levels": p.effort_levels(),
            }
            for name, p in PROVIDERS.items()
        },
        "layout_missing_deps": _missing_layout_deps(),
        "diag": _diag_status(),
    }


def _start(name: str, model: str = "", permission_mode: str = "", effort: str = "", fresh: bool = False,
           cli: str = "", lang: str = "tr") -> dict:
    fleet = _fleet_status()
    info = fleet.get(name)
    if not info or info["state"] != "active":
        return _err(lang, "not_active", name=name)
    chosen_cli = cli.strip() if cli.strip() in PROVIDERS else info["cli"]
    if _find_running(name, cli=chosen_cli):
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
                cli=chosen_cli,
            )
            opened = _wait_stable(name, timeout=HANDOVER_PROC_WAIT_SECONDS)
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
            results = [kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS, name=s.name) for s in procs]
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "result": results}


def _term_resolve(name: str, lang: str = "tr"):
    """Terminal endpoint'lerinin ortak çözümlemesi: name → tek, canlı, tmux-backed
    Session, yoksa (None, err-dict) döner."""
    procs = _find_running(name)
    if not procs:
        return None, _err(lang, "not_running", name=name)
    s = procs[0]
    if not is_tmux_backed(s.pid):
        return None, _err(lang, "not_tmux_backed", name=name)
    if not tmux_has_session(s.name):
        return None, _err(lang, "term_session_gone", name=name)
    return s, None


def _term_output(name: str, lang: str = "tr") -> dict:
    s, err = _term_resolve(name, lang)
    if err:
        return err
    text = tmux_capture(s.name, lines=2000)
    if text is None:
        return _err(lang, "term_session_gone", name=name)
    size = tmux_pane_size(s.name)
    return {"ok": True, "text": text, "cols": size[0] if size else None,
            "rows": size[1] if size else None}


def _term_input(name: str, text: str, lang: str = "tr") -> dict:
    s, err = _term_resolve(name, lang)
    if err:
        return err
    ok = tmux_send_keys(s.name, text)
    return {"ok": True} if ok else _err(lang, "term_session_gone", name=name)


def _term_key(name: str, key: str, lang: str = "tr") -> dict:
    if key not in ALLOWED_SPECIAL_KEYS:
        return _err(lang, "invalid_key")
    s, err = _term_resolve(name, lang)
    if err:
        return err
    ok = tmux_send_special_key(s.name, key)
    return {"ok": True} if ok else _err(lang, "term_session_gone", name=name)


def _term_chat(name: str, lang: str = "tr") -> dict:
    """Terminal popup'ının 'Sohbet' sekmesi: capture-pane/ANSI yerine provider'ın
    kendi transcript'inden (jsonl vb.) son user+assistant metnini STRUCTURED
    döndürür — xterm.js'in mobilde scroll/render sorunlarını tamamen bypass eder.
    Desteklemeyen provider'lar (agy/shell, henüz) için supported:false döner,
    hata değil — panel bunu "henüz yok" olarak gösterir."""
    s, err = _term_resolve(name, lang)
    if err:
        return err
    exchange = get_provider(s.cli).last_exchange(s.cwd, s.sid)
    if exchange is None:
        return {"ok": True, "supported": False}
    return {"ok": True, "supported": True, "user": exchange["user"], "assistant": exchange["assistant"]}


def _open_window(name: str, lang: str = "tr") -> dict:
    """Windowless (tmux-only) kalmış bir session'a YENİ bir gnome-terminal penceresi
    bağlar — CLI'ı yeniden başlatmadan. `_diag_status()`'un `windowless` listesindeki
    satırlara panelde tek-tık telafi butonu için (2026-08-28)."""
    s, err = _term_resolve(name, lang)
    if err:
        return err
    ok = open_window(s.name, s.cwd, display=detect_display())
    return {"ok": True} if ok else _err(lang, "term_session_gone", name=name)


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
                    kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS, name=s.name)
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
                    kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS, name=s.name)
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
    chosen_cli = info["cli"] if info else procs[0].cli
    provider = get_provider(chosen_cli)
    if info:
        cwd, model = info["cwd"], info["model"]
    else:
        cwd, model = procs[0].cwd, (procs[0].model or provider.model_choices()[0])
    message = HANDOVER_MSG_DEFAULT_EN if lang == "en" else HANDOVER_MSG_DEFAULT
    try:
        with guard_lock(timeout=5.0):
            kill_results = [kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS, name=s.name) for s in procs]
            if HANDOVER_KILL_SETTLE_SECONDS > 0 and any(r != "already_dead" for r in kill_results):
                time.sleep(HANDOVER_KILL_SETTLE_SECONDS)
            kind = spawn_session(
                name=name,
                cwd=cwd,
                model=model,
                display=detect_display(),
                permission_mode=provider.permission_modes()[0],
                effort=provider.effort_levels()[-1],
                force_new=False,
                prompt=message,
                cli=chosen_cli,
            )
            reopened = _wait_stable(name, timeout=HANDOVER_PROC_WAIT_SECONDS)
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
    # cli EĞİLMEZ/override edilmez — devralınan proc'un kimliği zaten hangi provider'ın
    # tanıdığıysa odur (bir claude proc'u "agy olarak devral" diye bir şey yok).
    chosen_cli = procs[0].cli
    provider = get_provider(chosen_cli)
    chosen_model = model.strip() or procs[0].model or provider.model_choices()[0]
    try:
        with guard_lock(timeout=5.0):
            kill_results = [kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS, name=s.name) for s in procs]
            if HANDOVER_KILL_SETTLE_SECONDS > 0 and any(r != "already_dead" for r in kill_results):
                time.sleep(HANDOVER_KILL_SETTLE_SECONDS)
            kind = spawn_session(
                name=new_name,
                cwd=cwd,
                model=chosen_model,
                display=detect_display(),
                permission_mode=permission_mode.strip() or provider.permission_modes()[0],
                effort=effort.strip() or provider.effort_levels()[-1],
                force_new=False,
                cli=chosen_cli,
            )
            reopened = _wait_stable(new_name, timeout=HANDOVER_PROC_WAIT_SECONDS)
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    if not reopened:
        return _err(lang, "adopt_reopen_failed", old_name=old_name, new_name=new_name, kind=kind)
    if new_name not in _fleet_status():
        _append_tsv_line(ROSTER_TSV, [new_name, cwd, chosen_model, chosen_cli])
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
  .sub { color: var(--muted); margin-bottom: 1rem; }
  .banner {
    padding: .5rem .75rem; border-radius: 6px; margin-bottom: .6rem;
    font-size: .85rem; border: 1px solid transparent;
  }
  .banner.bad { background: rgba(248,81,73,.12); border-color: var(--red); color: var(--red); }
  .tabs { display: flex; gap: .25rem; flex-wrap: wrap; border-bottom: 1px solid var(--border); margin-bottom: .6rem; }
  .tabs button { border: 1px solid transparent; border-bottom: none; border-radius: 6px 6px 0 0;
                 background: transparent; color: var(--muted); padding: .35rem .7rem; font-size: .82rem; }
  .tabs button.active { border-color: var(--border); background: var(--panel); color: var(--text); }
  .bulkbar { display: flex; gap: .4rem; align-items: center; flex-wrap: wrap; margin: .4rem 0 .2rem; }
  .bulkbar .selcount { font-size: .78rem; color: var(--muted); }
  .bulkmsg { font-size: .78rem; color: var(--muted); flex-basis: 100%; white-space: pre-wrap; }
  .legend { font-size: .72rem; color: var(--muted); margin: .2rem 0 .6rem; line-height: 1.6; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; color: var(--muted); font-weight: 500; font-size: .75rem;
       text-transform: uppercase; letter-spacing: .04em; padding: .4rem .5rem;
       border-bottom: 1px solid var(--border); }
  td { padding: .4rem .5rem; border-bottom: 1px solid var(--border); vertical-align: middle; }
  th.selcell, td.selcell { width: 1.6rem; text-align: center; padding-left: .2rem; padding-right: .2rem; }
  td.cwd { color: var(--muted); font-size: .78rem; overflow: hidden; text-overflow: ellipsis;
           white-space: nowrap; max-width: 1px; cursor: pointer; }
  td.cwd.expanded { white-space: normal; word-break: break-all; max-width: none; overflow: visible; }
  td.hocell { font-size: .78rem; }
  .ho-yes { color: var(--amber); font-weight: 600; cursor: help; }
  .ho-no { color: var(--muted); opacity: .6; cursor: help; }
  .tablewrap { overflow-x: auto; }
  @media (max-width: 640px) {
    /* dar ekranda model/tür sütunlarını gizle, cwd'yi kısalt — action butonları
       kaydırmadan görünsün (telefonda test edildi) */
    .runtab th:nth-child(3), .runtab td:nth-child(3),
    .runtab th:nth-child(7), .runtab td:nth-child(7),
    .regtab th:nth-child(3), .regtab td:nth-child(3) { display: none; }
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
  button.selho { border-color: var(--amber); color: var(--amber); font-size: .78rem; padding: .3rem .5rem; }
  .unreg-badge { font-size: .65rem; color: var(--amber); border: 1px solid var(--amber);
                 border-radius: 4px; padding: 1px 4px; margin-left: .3rem; cursor: help; }
  .cli-badge { font-size: .65rem; color: var(--muted); border: 1px solid var(--border);
               border-radius: 4px; padding: 1px 5px; }
  button.reactivate { border-color: var(--green); color: var(--green); }
  button:disabled { opacity: .5; cursor: default; }
  .actioncell { display: flex; gap: .35rem; flex-wrap: wrap; }
  .opts-row td { background: var(--panel2); padding: .6rem .5rem; }
  .opts { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
  .modes { flex-basis: 100%; display: flex; flex-direction: column; gap: .25rem; margin-bottom: .3rem; }
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
  <div class="tabs" id="tabbar"></div>
  <div id="tabContent"></div>
</div>
<script>
const T = {
  tr: {
    title: 'claudeops — filo kontrolü',
    colName: 'isim', colStatus: 'durum', colKind: 'tür',
    serverUnreachable: 'sunucuya ulaşılamadı: ',
    authError: `401 — token eksik/yanlış (URL'ye doğru ?token=... ekleyin)`,
    authErrorShort: '401 — token eksik/yanlış',
    unexpectedResponse: (code) => `beklenmeyen yanıt (http ${code}) — bu tünel/URL artık geçerli olmayabilir, güncel linki kontrol edin`,
    runningWord: 'çalışıyor', configWord: 'config',
    dupWarn: '⚠ DUP: ',
    fallbackAlertMsg: (n, mins) => `⚠ son ${mins} dakikada ${n} kez pencere açma tüm denemelere (retry dahil) rağmen başarısız oldu (CLI'lar yine de çalışıyor, sadece penceresiz) — gnome-terminal-server gerçekten sorunlu olabilir.`,
    fallbackAlertBtn: 'Tanı sekmesine git',
    pidWord: 'pid ', stoppedWord: 'durdu',
    cwdHint: 'tıkla: tam yolu göster/gizle',
    requestFailed: 'istek başarısız: ',
    empty: 'Boş.', cancelBtn: 'vazgeç',
    tabRunning: 'Çalışanlar', tabRegistered: 'Kayıtlı', tabDisabled: 'Devre dışı',
    tabRetired: 'Emekli', tabLayout: 'Layout', tabDiag: 'Tanı',
    selWord: 'seçili',
    selectNeedsHo: 'needs-ho seç',
    hoCol: 'ho?',
    hoHint: `handover gerekli mi? (repo kirli / untracked / baseline'dan beri commit / RFH yok — sinyallerden biri)`,
    hoUnknown: '?',
    stopBtn: 'durdur', disableBtn: 'devre dışı bırak', retireBtn: 'emekli et', handoverBtn: 'handover',
    legendStop: `sadece process/pencereyi kapatır — kayıt AKTİF kalır, "Kayıtlı" sekmesinden devam ettirilir`,
    legendDisable: `durdurur + otomasyon (guard) bir daha AÇMAZ — "Devre dışı" sekmesine taşınır, oradan geri alınır`,
    legendRetire: `durdurur + arşive kaldırır — "Emekli" sekmesine taşınır, "tekrar işe al" ile döner`,
    legendHandover: `wrap-up mesajı gönderip AYNI geçmişle yeniden açar (kapat+devam) — commit/push + not düşme için`,
    bulkConfirm: (label, expl, names) => `${label} — ${expl}\\n\\nseçili (${names.length}): ${names.join(', ')}\\n\\nDevam edilsin mi?`,
    bulkSkippedUnreg: 'kayıtsız olduğu için atlanacak: ',
    bulkDone: (ok, fail) => `bitti — ${ok} tamam` + (fail ? `, ${fail} hata` : ''),
    optionsBtn: 'seçenekler ▾', startBtn: 'başlat ▾', terminalBtn: 'terminal',
    termPlaceholder: 'komut yaz, Enter/Gönder ile yolla…', termSend: 'gönder',
    termGone: (err) => `✗ ${err}`,
    termScrolledHint: '⏸ yukarı kaydırdınız — canlı akış duraklatıldı, dibe dönünce devam eder',
    termCopyBtn: 'kopyala', termCopied: '✓ kopyalandı',
    termCopyHint: 'görünen çıktıyı panoya kopyala (mobilde dokunarak seçim güvenilir değil)',
    termOpen: 'aç',
    tabTermView: 'terminal', tabChatView: 'sohbet',
    chatYou: 'Sen', chatAssistant: 'Asistan',
    chatEmpty: '(boş)',
    chatUnsupported: 'bu CLI için sohbet görünümü henüz yok — terminal sekmesini kullanın',
    chatLoadError: 'yüklenemedi: ',
    nothingRunning: `Hiçbir şey çalışmıyor — "Kayıtlı" sekmesinden başlatın.`,
    unregBadge: 'kayıtsız',
    unregHint: `roster.tsv'de kayıtlı değil (proc-scan'den bulundu) — claudeops'un açmadığı bir pencere; "devral"a basarsanız remote-control eklenip roster'a kalıcı kaydedilir`,
    adoptBtn: 'devral (remote ekle)',
    adoptWarn: (name) => `⚠ ${name} claudeops'un açmadığı bir pencere (elle/başka yerden açılmış). "devral" bu pencereyi KAPATIR ve seçtiğiniz isimle AYRI, YENİ bir pencerede --remote-control ile açar (aynı geçmişle, --resume) — şu an baktığınız pencerenin kendisi değil, yeni bir pencere.`,
    adoptNameLabel: 'yeni isim (remote-control adı)',
    adopting: 'devralınıyor… (~10-20s)',
    adopted: 'devralındı, yeni isim: ',
    noneRegistered: 'Durdurulmuş kayıtlı proje yok — hepsi çalışıyor ya da liste boş.',
    registerTitle: '+ Yeni proje kaydet',
    registerDesc: `(klasörü roster'a ekler, başlatmaz — sonra yukarıdaki listeden başlatırsınız)`,
    registerNameLabel: 'isim (küçük harf, rakam, _)',
    registerCwdLabel: 'klasör (tam yol)',
    registerSave: 'kaydet', registerSaving: 'kaydediliyor…',
    reactivateBtn: 'tekrar işe al + başlat',
    modeResume: 'devam ettir', modeReset: 'sıfırla ve başlat', modeNewchat: 'yeni chat aç',
    modeChoiceNewchatOnly: 'Ayrı yeni chat aç (mevcuduna dokunmaz)',
    modeChoiceResume: 'Devam ettir (kaldığı yerden)',
    modeChoiceReset: `Bu ismi SIFIRLA (--new, geçmiş bir daha görünmez)`,
    modeChoiceNewchat: 'Ayrı yeni chat aç (yeni isimle, mevcuduna dokunmaz)',
    runningNote: (name) => `⚠ ${name} şu an ÇALIŞIYOR — devam ettirmek/sıfırlamak için önce "durdur"a basın. Buradaki tek seçenek AYRI, ek bir chat açar, mevcut ${name}'a dokunmaz.`,
    pmLabel: 'permission-mode', effortLabel: 'effort', modelLabel: 'model', cliLabel: 'CLI',
    autoNameHint: (name, date) => `isim otomatik: ${name}${date} (çakışırsa _1, _2…)`,
    starting: 'başlıyor…', newChatStarted: 'yeni chat başlatıldı: ',
    layoutDesc: `X11 masaüstü — Wayland'da/kilitli ekranda çalışmaz`,
    layoutMissingPrefix: '⚠ eksik: ', layoutMissingSuffix: ' — kurmak için: sudo apt install -y ',
    layoutPinLabel: `pin (ws0'a sabit, virgülle)`,
    layoutGroupsLabel: `group'lar ( | ile ayrılmış birden fazla grup, her grup virgüllü)`,
    layoutClaudeOnly: 'sadece claude pencereleri',
    layoutDryRun: 'sadece planı göster (uygulama)',
    layoutApply: 'layout uygula', layoutApplying: 'uygulanıyor…',
    windowsWord: 'pencere', skippedWord: 'atlandı',
    diagDesc: `Fleet'in tüm "start"ları sessizce başarısız olabiliyor — iki bağımsız, birbirinden ayrı sebepten (web sunucu ya da gnome-terminal-server'ın kendi uzun çalışma süresi). Aşağıda ikisinin durumu + tek-tıkla test/fix.`,
    diagWebUptime: 'web sunucu (bu panel)', diagGtUptime: 'gnome-terminal-server',
    diagUptimeUnknown: 'bilinmiyor', diagGtNotFound: 'çalışmıyor (henüz hiç pencere açılmamış olabilir — sorun değil)',
    diagTestBtn: 'spawn sağlık testi', diagTesting: 'test ediliyor… (~2s, kısa bir pencere açılıp kendi kendine kapanacak)',
    diagTestOk: '✓ gnome-terminal sağlıklı — test penceresi başarıyla açıldı ve doğrulandı',
    diagTestFailWindow: '✗ pencere açılmadı/doğrulanamadı',
    diagTestFailStderr: (e) => `✗ gnome-terminal hata verdi:\\n${e}`,
    diagRestartBtn: `gnome-terminal-server'ı yeniden başlat`,
    diagRestartConfirm: (n) => `Açık TÜM gnome-terminal pencereleri kapanacak (fleet'in ${n} çalışan penceresi dahil, varsa filoyla ilgisiz başka terminal pencereleri de) — tmux session'lar/claude process'leri ETKİLENMEZ, sadece görünür pencereler kaybolur. Bir sonraki pencere açma isteğinde otomatik yeniden doğar. Devam edilsin mi?`,
    diagRestarting: 'yeniden başlatılıyor…',
    diagRestartDone: (r) => `✓ kapatıldı (${r}) — bir sonraki spawn'da otomatik yeniden doğacak`,
    diagRefreshHint: 'çalışma süreleri her 4s otomatik güncellenir',
    diagWindowless: (names) => `⚠ penceresiz çalışıyor (gnome-terminal fallback, tmux-only): ${names} — panelde görünmezler, sadece "terminal" butonuyla erişilir`,
    windowlessBadge: 'penceresiz', windowlessHint: 'gnome-terminal penceresi yok (tmux-only fallback) — CLI çalışıyor, sadece görünür pencere yok. "pencere aç" ile CLI yeniden başlamadan bir pencere bağlayabilirsin.',
    openWindowBtn: 'pencere aç', openingWindow: 'pencere açılıyor…',
    diagAskCliLabel: 'CLI', diagAskQuestionLabel: 'ek soru (opsiyonel)',
    diagAskQuestionPlaceholder: 'boş bırakılırsa genel teşhis istenir',
    diagAskBtn: 'bu CLI ile sor', diagAsking: 'açılıyor… (~10-20s)',
    diagAskStarted: (name) => `✓ açıldı: ${name} — terminal'de canlı yanıt görünecek`,
    diagLogTitle: 'son diag-log kayıtları', diagLogLoading: 'yükleniyor…',
    diagRunAfterFail: 'Tanı sekmesine geçip spawn sağlık testi çalıştırılsın mı?',
  },
  en: {
    title: 'claudeops — fleet control',
    colName: 'name', colStatus: 'status', colKind: 'kind',
    serverUnreachable: 'server unreachable: ',
    authError: `401 — token missing/invalid (add ?token=... to the URL)`,
    authErrorShort: '401 — token missing/invalid',
    unexpectedResponse: (code) => `unexpected response (http ${code}) — this tunnel/URL may no longer be valid, check the current link`,
    runningWord: 'running', configWord: 'config',
    dupWarn: '⚠ DUP: ',
    fallbackAlertMsg: (n, mins) => `⚠ in the last ${mins} minutes, opening a window failed ${n} times despite all retries (the CLIs are still running, just windowless) — gnome-terminal-server may genuinely be having trouble.`,
    fallbackAlertBtn: 'go to Diagnostics tab',
    pidWord: 'pid ', stoppedWord: 'stopped',
    cwdHint: 'click: show/hide full path',
    requestFailed: 'request failed: ',
    empty: 'Empty.', cancelBtn: 'cancel',
    tabRunning: 'Running', tabRegistered: 'Registered', tabDisabled: 'Disabled',
    tabRetired: 'Retired', tabLayout: 'Layout', tabDiag: 'Diagnostics',
    selWord: 'selected',
    selectNeedsHo: 'select needs-ho',
    hoCol: 'ho?',
    hoHint: 'needs handover? (dirty repo / untracked / commits since baseline / no RFH — any one signal)',
    hoUnknown: '?',
    stopBtn: 'stop', disableBtn: 'disable', retireBtn: 'retire', handoverBtn: 'handover',
    legendStop: 'kills only the process/window — stays REGISTERED, resume it from the "Registered" tab',
    legendDisable: 'stop + automation (guard) will NOT reopen it — moves to the "Disabled" tab, reversible there',
    legendRetire: 'stop + archive — moves to the "Retired" tab, comes back via "reactivate"',
    legendHandover: 'sends a wrap-up prompt and reopens with the SAME history (close+continue) — for commit/push + notes',
    bulkConfirm: (label, expl, names) => `${label} — ${expl}\\n\\nselected (${names.length}): ${names.join(', ')}\\n\\nProceed?`,
    bulkSkippedUnreg: 'skipped (unregistered): ',
    bulkDone: (ok, fail) => `done — ${ok} ok` + (fail ? `, ${fail} failed` : ''),
    optionsBtn: 'options ▾', startBtn: 'start ▾', terminalBtn: 'terminal',
    termPlaceholder: 'type a command, Enter/Send to submit…', termSend: 'send',
    termGone: (err) => `✗ ${err}`,
    termScrolledHint: '⏸ scrolled up — live updates paused, resumes when you scroll back to bottom',
    termCopyBtn: 'copy', termCopied: '✓ copied',
    termCopyHint: 'copy visible output to clipboard (touch-selection is unreliable on mobile)',
    termOpen: 'open',
    tabTermView: 'terminal', tabChatView: 'chat',
    chatYou: 'You', chatAssistant: 'Assistant',
    chatEmpty: '(empty)',
    chatUnsupported: "chat view isn't available for this CLI yet — use the terminal tab",
    chatLoadError: 'failed to load: ',
    nothingRunning: 'Nothing running — start from the "Registered" tab.',
    unregBadge: 'unregistered',
    unregHint: `not in roster.tsv (found via proc-scan) — a window claudeops didn't open; click "adopt" to attach remote-control and register it permanently`,
    adoptBtn: 'adopt (attach remote)',
    adoptWarn: (name) => `⚠ ${name} is a window claudeops didn't open (started by hand/elsewhere). "adopt" will CLOSE this window and open a SEPARATE, NEW window under the name you choose, with --remote-control (same history, --resume) — not this exact window, a new one.`,
    adoptNameLabel: 'new name (remote-control name)',
    adopting: 'adopting… (~10-20s)',
    adopted: 'adopted, new name: ',
    noneRegistered: 'No stopped registered projects — everything is running, or the list is empty.',
    registerTitle: '+ Register new project',
    registerDesc: '(adds the folder to the roster, does not start it — start it from the list above)',
    registerNameLabel: 'name (lowercase, digits, _)',
    registerCwdLabel: 'folder (full path)',
    registerSave: 'save', registerSaving: 'saving…',
    reactivateBtn: 'reactivate + start',
    modeResume: 'resume', modeReset: 'reset and start', modeNewchat: 'start new chat',
    modeChoiceNewchatOnly: 'Start a separate new chat (does not touch the existing one)',
    modeChoiceResume: 'Resume (from where it left off)',
    modeChoiceReset: 'RESET this name (--new, previous history no longer shown)',
    modeChoiceNewchat: 'Start a separate new chat (new name, does not touch the existing one)',
    runningNote: (name) => `⚠ ${name} is currently RUNNING — click "stop" first to resume/reset. The only option here starts a SEPARATE extra chat, it does not touch the existing ${name}.`,
    pmLabel: 'permission-mode', effortLabel: 'effort', modelLabel: 'model', cliLabel: 'CLI',
    autoNameHint: (name, date) => `name auto-generated: ${name}${date} (adds _1, _2… on conflict)`,
    starting: 'starting…', newChatStarted: 'new chat started: ',
    layoutDesc: `X11 desktop — does not work on Wayland/locked screen`,
    layoutMissingPrefix: '⚠ missing: ', layoutMissingSuffix: ' — install with: sudo apt install -y ',
    layoutPinLabel: 'pin (fixed to ws0, comma-separated)',
    layoutGroupsLabel: 'groups ( | -separated, each group comma-separated)',
    layoutClaudeOnly: 'claude windows only',
    layoutDryRun: 'show plan only (no changes)',
    layoutApply: 'apply layout', layoutApplying: 'applying…',
    windowsWord: 'windows', skippedWord: 'skipped',
    diagDesc: `Any/all of the fleet's "start"s can silently fail — from two independent causes (either the web server's or gnome-terminal-server's own long uptime). Status of both below, plus a one-click test/fix.`,
    diagWebUptime: 'web server (this panel)', diagGtUptime: 'gnome-terminal-server',
    diagUptimeUnknown: 'unknown', diagGtNotFound: 'not running (may just be that no window has opened yet — not a problem)',
    diagTestBtn: 'spawn health test', diagTesting: 'testing… (~2s, a brief window will open and close itself)',
    diagTestOk: '✓ gnome-terminal is healthy — the test window opened and was verified',
    diagTestFailWindow: '✗ window did not open / could not be verified',
    diagTestFailStderr: (e) => `✗ gnome-terminal reported an error:\\n${e}`,
    diagRestartBtn: 'restart gnome-terminal-server',
    diagRestartConfirm: (n) => `ALL open gnome-terminal windows will close (including the fleet's ${n} running window(s), plus any unrelated terminal windows you may have open) — tmux sessions/claude processes are NOT affected, only the visible windows disappear. It respawns automatically on the next window-open request. Proceed?`,
    diagRestarting: 'restarting…',
    diagRestartDone: (r) => `✓ stopped (${r}) — will respawn automatically on the next spawn`,
    diagRefreshHint: 'uptimes auto-refresh every 4s',
    diagWindowless: (names) => `⚠ running windowless (gnome-terminal fallback, tmux-only): ${names} — won't show a window, only reachable via the "terminal" button`,
    windowlessBadge: 'windowless', windowlessHint: `no gnome-terminal window (tmux-only fallback) — the CLI is running, it just has no visible window. "open window" attaches one without restarting the CLI.`,
    openWindowBtn: 'open window', openingWindow: 'opening window…',
    diagAskCliLabel: 'CLI', diagAskQuestionLabel: 'extra question (optional)',
    diagAskQuestionPlaceholder: 'leave empty for a general diagnosis',
    diagAskBtn: 'ask with this CLI', diagAsking: 'opening… (~10-20s)',
    diagAskStarted: (name) => `✓ opened: ${name} — the live answer will appear in the terminal`,
    diagLogTitle: 'recent diag-log entries', diagLogLoading: 'loading…',
    diagRunAfterFail: 'Switch to the Diagnostics tab and run the spawn health test?',
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
let termFor = null;
let termTab = 'term';  // 'term'|'chat' — hangi sekme açık; render()'ın her 4s'lik tam
                        // yeniden kuruşunda termRow() hep 'term'e dönüyor, bunu geri
                        // uygulamak (applyTermTabVisual) render()'ın sonunda gerekiyor.
let termPollTimer = null;
let TAB = localStorage.getItem('cops_tab') || 'running';
const SEL = new Set();
let BULK_MSG = '';
let BULK_BUSY = false;
let CUR_TAB_NAMES = [];

function setTab(tab) {
  TAB = tab;
  try { localStorage.setItem('cops_tab', tab); } catch (e) {}
  render(LAST);
  if (tab === 'diag') loadDiagLog();
}

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
  if (!d) return;
  const running = d.sessions.filter(s => s.running);
  const stopped = d.sessions.filter(s => !s.running);
  document.getElementById('summary').textContent =
    running.length + '/' + d.sessions.length + ' ' + t('runningWord') + '  ·  ' + t('configWord') + ': ' + d.config_msg;

  const banners = [];
  if (!d.config_ok) banners.push('<div class="banner bad">⚠ ' + d.config_msg + '</div>');
  if (d.dups.length) banners.push('<div class="banner bad">' + t('dupWarn') + d.dups.join(', ') + '</div>');
  if (d.diag && d.diag.fallback_alert) {
    banners.push('<div class="banner bad">' +
      t('fallbackAlertMsg')(d.diag.recent_fallback_count, d.diag.fallback_alert_window_minutes) +
      ` <button class="start" onclick="setTab('diag')">${t('fallbackAlertBtn')}</button></div>`);
  }
  document.getElementById('banners').innerHTML = banners.join('');

  const tabs = [
    ['running', t('tabRunning') + ' (' + running.length + ')'],
    ['registered', t('tabRegistered') + ' (' + stopped.length + ')'],
    ['disabled', t('tabDisabled') + ' (' + d.closed.length + ')'],
    ['retired', t('tabRetired') + ' (' + d.retired.length + ')'],
    ['layout', t('tabLayout')],
    ['diag', t('tabDiag')],
  ];
  document.getElementById('tabbar').innerHTML = tabs.map(([k, lbl]) =>
    `<button class="${TAB === k ? 'active' : ''}" onclick="setTab('${k}')">${lbl}</button>`).join('');

  let html = '';
  if (TAB === 'running') html = bulkBar('running', running) + runningTable(running, d);
  else if (TAB === 'registered') html = bulkBar('registered', stopped) + registeredTable(stopped, d) + newProjectForm(d);
  else if (TAB === 'disabled') html = groupTable(d.closed);
  else if (TAB === 'retired') html = groupTable(d.retired);
  else if (TAB === 'layout') html = renderLayoutBox(d);
  else html = renderDiagBox(d, running.length);
  // `refresh()` her 4s'de render(LAST) çağırıyor — bu innerHTML= ataması açık bir
  // terminal varsa onun DOM'unu (xterm.js'in içine gerçekten yazdığı satırları)
  // YOK EDİP termRow()'un ürettiği BOŞ bir placeholder div'le değiştiriyordu.
  // xtermInstances[name] JS tarafında hâlâ "var" göründüğü için ensureXtermFor bir
  // daha HİÇ çağrılmıyor (guard: `if (xtermInstances[name]) return`) → terminal kalıcı
  // olarak boş/küçük bir kutuya (childCount 0, ~11x11px) çöküyor — canlı Playwright
  // testiyle doğrulandı (2026-08-28, diag20260827'de: içerik ~2s sonra tamamen kayboldu,
  // tam bir sonraki refresh() tetiklemesiyle örtüşüyor). Fix: eski (içerik dolu) node'u
  // sakla, innerHTML= sonrası taze (boş) placeholder'ın YERİNE eskisini geri koy —
  // xterm'in kendi DOM'u/state'i hiç bozulmadan, geri kalan tablo normal güncellenir.
  //
  // Aynı yok-etme term-in-${name} input'unu da vuruyordu: kullanıcı bir şey yazıp
  // Enter'a basmadan bu tetiklenirse yeni (boş) input eskisinin yerine geçiyor —
  // yazdığı metin sessizce kayboluyor, VE input o an odaktaysa DOM'dan sökülmesi
  // odağı düşürüyor → mobilde ekran klavyesi aniden kapanıyor (canlı kullanıcı
  // raporu, 2026-08-29: "yazdıklarım kayboluyor" + "sürekli scroll oluyor/kaymış").
  // Fix: aynı sakla/geri-koy deseni + odak input'taysa açıkça .focus()+imleç konumu
  // geri yükle (DOM'dan sökülme tarayıcıda senkron blur tetikliyor, reinsert'in
  // kendisi odağı geri getirmiyor — ama capture→reinsert→focus hepsi AYNI senkron
  // render() çağrısı içinde olduğu için tarayıcı klavyeyi kapatacak zamanı bulamıyor).
  const openXterm = termFor ? document.getElementById('xterm-' + termFor) : null;
  const openInput = termFor ? document.getElementById('term-in-' + termFor) : null;
  const openInputFocused = !!openInput && document.activeElement === openInput;
  const openInputSel = openInputFocused ? [openInput.selectionStart, openInput.selectionEnd] : null;
  document.getElementById('tabContent').innerHTML = html;
  if (openXterm) {
    const freshPlaceholder = document.getElementById('xterm-' + termFor);
    if (freshPlaceholder && freshPlaceholder !== openXterm) freshPlaceholder.replaceWith(openXterm);
  }
  if (openInput) {
    const freshInput = document.getElementById('term-in-' + termFor);
    if (freshInput && freshInput !== openInput) {
      freshInput.replaceWith(openInput);
      if (openInputFocused) {
        openInput.focus();
        openInput.setSelectionRange(openInputSel[0], openInputSel[1]);
      }
    }
  }
  // termRow() her zaman 'term' sekmesi aktif üretir (üstteki xterm/input rescue'unun
  // yakalamadığı bir state) — kullanıcı 'sohbet'teyse her 4s'lik refresh'te sessizce
  // 'terminal'e geri döndürüyordu (canlı rapor, 2026-08-31: "sohbete basıyorum, 2sn
  // sonra tekrar terminale geçiyor"). Aynı innerHTML sonrası geri-uygula deseni.
  if (termFor) applyTermTabVisual(termFor, termTab);
}

// ── seçim + toplu işlemler ──────────────────────────────────────────────────

function toggleSel(name, on) {
  if (on) SEL.add(name); else SEL.delete(name);
  render(LAST);
}
function toggleSelAll(on) {
  for (const n of CUR_TAB_NAMES) { if (on) SEL.add(n); else SEL.delete(n); }
  render(LAST);
}
function selectNeedsHo() {
  if (!LAST) return;
  SEL.clear();
  for (const s of LAST.sessions) if (s.running && s.needs_ho === true) SEL.add(s.name);
  render(LAST);
}

function bulkBar(tab, rows) {
  const sel = rows.filter(r => SEL.has(r.name));
  const dis = (sel.length && !BULK_BUSY) ? '' : 'disabled';
  const btn = (action, cls, label, title) =>
    `<button class="${cls}" ${dis} title="${title}" onclick="bulkAct('${action}')">${label}</button>`;
  const buttons = tab === 'running'
    ? btn('handover', 'handover', t('handoverBtn'), t('legendHandover'))
      + btn('stop', 'stop', t('stopBtn'), t('legendStop'))
      + btn('close', 'closebtn', t('disableBtn'), t('legendDisable'))
      + btn('retire', 'retire', t('retireBtn'), t('legendRetire'))
      + `<button class="selho" ${BULK_BUSY ? 'disabled' : ''} title="${t('hoHint')}" onclick="selectNeedsHo()">${t('selectNeedsHo')}</button>`
    : btn('close', 'closebtn', t('disableBtn'), t('legendDisable'))
      + btn('retire', 'retire', t('retireBtn'), t('legendRetire'));
  const legendRows = tab === 'running'
    ? [[t('handoverBtn'), t('legendHandover')], [t('stopBtn'), t('legendStop')],
       [t('disableBtn'), t('legendDisable')], [t('retireBtn'), t('legendRetire')]]
    : [[t('disableBtn'), t('legendDisable')], [t('retireBtn'), t('legendRetire')]];
  return `<div class="bulkbar">
      <span class="selcount">${t('selWord')}: ${sel.length}</span>${buttons}
      <span class="bulkmsg" id="bulkMsg">${BULK_MSG}</span>
    </div>
    <div class="legend">${legendRows.map(([k, v]) => `<b>${k}</b> — ${v}`).join('<br>')}</div>`;
}

function setBulkMsg(msg) {
  BULK_MSG = msg;
  const el = document.getElementById('bulkMsg');
  if (el) el.textContent = msg;
}

async function bulkAct(action) {
  if (!LAST || BULK_BUSY) return;
  const rows = TAB === 'running'
    ? LAST.sessions.filter(s => s.running)
    : LAST.sessions.filter(s => !s.running);
  let picked = rows.filter(s => SEL.has(s.name));
  let note = '';
  if (action === 'close' || action === 'retire') {
    // kayıtsız (roster'da olmayan) satırlara close/retire uygulanamaz — atla + söyle
    const unreg = picked.filter(s => s.registered === false).map(s => s.name);
    if (unreg.length) {
      picked = picked.filter(s => s.registered !== false);
      note = '\\n\\n' + t('bulkSkippedUnreg') + unreg.join(', ');
    }
  }
  const names = picked.map(s => s.name);
  if (!names.length) { if (note) alert(note.trim()); return; }
  const expl = {handover: t('legendHandover'), stop: t('legendStop'), close: t('legendDisable'), retire: t('legendRetire')}[action];
  const label = {handover: t('handoverBtn'), stop: t('stopBtn'), close: t('disableBtn'), retire: t('retireBtn')}[action];
  if (!confirm(t('bulkConfirm')(label, expl, names) + note)) return;
  BULK_BUSY = true;
  const errs = [];
  let done = 0;
  for (const name of names) {
    setBulkMsg(label + ': ' + (done + 1) + '/' + names.length + ' — ' + name + '…');
    try {
      const r = await fetch(withToken('/api/' + action), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, lang: LANG}),
      });
      if (r.status === 401) { errs.push(name + ': 401'); }
      else {
        const res = await safeJson(r);
        if (!res.ok) errs.push(name + ': ' + res.error);
      }
    } catch (e) {
      errs.push(name + ': ' + e.message);
    }
    done++;
  }
  BULK_BUSY = false;
  BULK_MSG = t('bulkDone')(names.length - errs.length, errs.length)
    + (errs.length ? '\\n' + errs.join('\\n') : '');
  SEL.clear();
  LAST_JSON = null;  // sonucu ve yeni durumu kesin yeniden çiz
  refresh();
}

// ── tablolar ────────────────────────────────────────────────────────────────

function selCell(s) {
  return `<td class="selcell"><input type="checkbox" ${SEL.has(s.name) ? 'checked' : ''} onchange="toggleSel('${s.name}', this.checked)"></td>`;
}

function hoCell(s) {
  if (s.needs_ho === true) return `<td class="hocell"><span class="ho-yes" title="${t('hoHint')}">ho!</span></td>`;
  if (s.needs_ho === false) return `<td class="hocell"><span class="ho-no" title="${t('hoHint')}">—</span></td>`;
  return `<td class="hocell"><span class="ho-no" title="${t('hoHint')}">${t('hoUnknown')}</span></td>`;
}

function runningTable(rows, d) {
  CUR_TAB_NAMES = rows.map(s => s.name);
  const allOn = rows.length && rows.every(s => SEL.has(s.name));
  const body = [];
  for (const s of rows) body.push(...runningRow(s, d));
  if (!rows.length) body.push(`<tr><td colspan="10" style="color:var(--muted)">${t('nothingRunning')}</td></tr>`);
  return `<div class="tablewrap"><table class="runtab">
    <thead><tr>
      <th class="selcell"><input type="checkbox" ${allOn ? 'checked' : ''} onchange="toggleSelAll(this.checked)"></th>
      <th style="width:12%">${t('colName')}</th>
      <th style="width:14%">model</th>
      <th style="width:6%">${t('cliLabel')}</th>
      <th style="width:9%">${t('colStatus')}</th>
      <th style="width:6%">cpu%</th>
      <th style="width:5%" title="${t('hoHint')}">${t('hoCol')}</th>
      <th style="width:8%">${t('colKind')}</th>
      <th>cwd</th>
      <th style="width:10%"></th>
    </tr></thead><tbody>${body.join('')}</tbody></table></div>`;
}

function runningRow(s, d) {
  const windowless = s.tmux && ((d.diag && d.diag.windowless) || []).includes(s.name);
  const actions = (s.registered === false
    ? `<button class="start" onclick="toggleAdopt('${s.name}')">${t('adoptBtn')}</button>`
    : `<button class="start" onclick="toggleOpts('${s.name}')">${t('optionsBtn')}</button>`)
    + (s.tmux ? `<button class="start" onclick="toggleTerm('${s.name}')">${t('terminalBtn')}</button>` : '')
    + (windowless ? `<button class="start" onclick="doOpenWindow('${s.name}', this)" title="${t('windowlessHint')}">${t('openWindowBtn')}</button>` : '');
  const unregBadge = s.registered === false
    ? ` <span class="unreg-badge" title="${t('unregHint')}">${t('unregBadge')}</span>` : '';
  const windowlessBadge = windowless
    ? ` <span class="unreg-badge" title="${t('windowlessHint')}">${t('windowlessBadge')}</span>` : '';
  const nameCell = `${s.name}${unregBadge}${windowlessBadge}`;
  const row = `
    <tr>
      ${selCell(s)}
      <td>${nameCell}</td>
      <td>${s.model || ''}</td>
      <td><span class="cli-badge">${s.cli}</span></td>
      <td><span class="dot on"></span>${t('pidWord')}${s.pid}</td>
      <td>${s.cpu != null ? s.cpu.toFixed(1) : '—'}</td>
      ${hoCell(s)}
      <td>${s.kind || '—'}</td>
      <td class="cwd" title="${t('cwdHint')}" onclick="this.classList.toggle('expanded')">${s.cwd}</td>
      <td><div class="actioncell">${actions}</div></td>
    </tr>`;
  const extra = [];
  if (s.registered === false && adoptFor === s.name) extra.push(adoptOptsRow(s, d, 10));
  if (s.registered !== false && optsFor === s.name) extra.push(unifiedOptsRow(s, d, 10));
  if (s.tmux && termFor === s.name) extra.push(termRow(s, 10));
  return [row, ...extra];
}

function registeredTable(rows, d) {
  CUR_TAB_NAMES = rows.map(s => s.name);
  const allOn = rows.length && rows.every(s => SEL.has(s.name));
  const body = [];
  for (const s of rows) body.push(...registeredRow(s, d));
  if (!rows.length) body.push(`<tr><td colspan="6" style="color:var(--muted)">${t('noneRegistered')}</td></tr>`);
  return `<div class="tablewrap"><table class="regtab">
    <thead><tr>
      <th class="selcell"><input type="checkbox" ${allOn ? 'checked' : ''} onchange="toggleSelAll(this.checked)"></th>
      <th style="width:14%">${t('colName')}</th>
      <th style="width:16%">model</th>
      <th style="width:6%">${t('cliLabel')}</th>
      <th>cwd</th>
      <th style="width:12%"></th>
    </tr></thead><tbody>${body.join('')}</tbody></table></div>`;
}

function registeredRow(s, d) {
  const row = `
    <tr>
      ${selCell(s)}
      <td>${s.name}</td>
      <td>${s.model || ''}</td>
      <td><span class="cli-badge">${s.cli}</span></td>
      <td class="cwd" title="${t('cwdHint')}" onclick="this.classList.toggle('expanded')">${s.cwd}</td>
      <td><div class="actioncell"><button class="start" onclick="toggleOpts('${s.name}')">${t('startBtn')}</button></div></td>
    </tr>`;
  return (optsFor === s.name) ? [row, unifiedOptsRow(s, d, 6)] : [row];
}

function groupTable(items) {
  if (!items.length) return `<div class="opts-hint">${t('empty')}</div>`;
  const rows = items.map(it => `
    <tr>
      <td style="width:14%">${it.name}</td>
      <td style="width:18%">${it.model || ''}</td>
      <td style="width:6%"><span class="cli-badge">${it.cli}</span></td>
      <td class="cwd" title="${t('cwdHint')}" onclick="this.classList.toggle('expanded')">${it.cwd}</td>
      <td style="width:16%"><button class="reactivate" onclick="doReactivate('${it.name}', this)">${t('reactivateBtn')}</button></td>
    </tr>`).join('');
  return `<div class="tablewrap"><table><tbody>${rows}</tbody></table></div>`;
}

// ── devral (adopt) ──────────────────────────────────────────────────────────

let adoptChoice = {};   // aynı "refresh açık formu siliyor" bug'ı — bkz. optsChoice notu

function toggleAdopt(name) {
  adoptFor = (adoptFor === name) ? null : name;
  if (adoptFor !== name) adoptChoice[name] = null;
  render(LAST);
}

function adoptOptsRow(s, d, colspan) {
  // cli devralınan proc'un kimliğidir, DEĞİŞTİRİLEMEZ (rozet olarak gösterilir) —
  // bir claude proc'u "agy olarak devral" diye bir şey yok, bkz. backend _adopt().
  const saved = adoptChoice[s.name] || {};
  return `
    <tr class="opts-row"><td colspan="${colspan}"><div class="opts">
      <span class="opts-hint">${t('adoptWarn')(s.name)}</span>
      <label>${t('adoptNameLabel')}
        <input type="text" id="adopt-name-${s.name}" value="${saved.newName ?? s.name}"
          oninput="adoptChoice['${s.name}']={...(adoptChoice['${s.name}']||{}),newName:this.value}">
      </label>
      <label>${t('cliLabel')}<span class="cli-badge">${s.cli}</span></label>
      ${renderCliFields('adopt', s.name, s.cli, d, s.model, saved)}
      <button class="go" onclick="doAdopt('${s.name}', this)">${t('adoptBtn')}</button>
      <button onclick="adoptChoice['${s.name}']=null; adoptFor=null; render(LAST)">${t('cancelBtn')}</button>
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
  adoptChoice[oldName] = null;
  refresh();
}

// ── kayıt formu ─────────────────────────────────────────────────────────────

function newProjectForm(d) {
  const cliOpts = d.cli_list.map(c => `<option value="${c}" ${c === 'claude' ? 'selected' : ''}>${c}</option>`).join('');
  const modelOpts = (d.cli_options['claude'] || {models: []}).models.map(m => `<option>${m}</option>`).join('');
  return `
    <div class="opts" style="margin-top:.7rem">
      <span class="opts-hint"><b>${t('registerTitle')}</b> ${t('registerDesc')}</span>
      <label>${t('registerNameLabel')}
        <input type="text" id="reg-name" placeholder="myproject">
      </label>
      <label>${t('registerCwdLabel')}
        <input type="text" id="reg-cwd" placeholder="/home/user/work/myproject">
      </label>
      <label>${t('cliLabel')}
        <select id="reg-cli" onchange="onRegCliChange()">${cliOpts}</select>
      </label>
      <label>${t('modelLabel')}
        <select id="reg-model">${modelOpts}</select>
      </label>
      <button class="go" onclick="doRegister(this)">${t('registerSave')}</button>
    </div>`;
}

function onRegCliChange() {
  const cli = document.getElementById('reg-cli').value;
  const sel = document.getElementById('reg-model');
  sel.innerHTML = ((LAST.cli_options || {})[cli] || {models: []}).models.map(m => `<option>${m}</option>`).join('');
}

async function doRegister(btn) {
  const name = document.getElementById('reg-name').value.trim();
  const cwd = document.getElementById('reg-cwd').value.trim();
  const cli = document.getElementById('reg-cli').value;
  const model = document.getElementById('reg-model').value;
  btn.disabled = true;
  btn.textContent = t('registerSaving');
  try {
    const r = await fetch(withToken('/api/register'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, cwd, model, cli, lang: LANG}),
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

// ── başlat/seçenekler ───────────────────────────────────────────────────────

function modeLabels() { return {resume: t('modeResume'), reset: t('modeReset'), newchat: t('modeNewchat')}; }

// Model/permission-mode/effort seçenekleri hangi CLI seçiliyse ONA göre değişir
// (agy'nin model listesi/effort seviyeleri claude'unkiyle TAMAMEN farklı) —
// tek bir yerde üretilip hem başlat-seçenekleri hem devral satırında kullanılır.
// Panel her ~4s'de (ya da başka bir satırdaki değişiklikte) TÜM tabloyu yeniden
// çiziyor — açık bir seçenekler satırında kullanıcının henüz GÖNDERMEDİĞİ bir
// seçim (cli/model/pm/effort) varsa, o satır sunucudaki ESKİ değerlerle yeniden
// kurulup kullanıcının seçimini SESSİZCE siliyordu ("agy seçince kayboluyor").
// Fix: kullanıcının her onchange'i burada tutuluyor, render() her çalıştığında
// bu ÖNCELİKLİ okunuyor — submit/iptal'de temizlenir.
let optsChoice = {};   // name -> {cli, model, modelOther, pm, effort}

function renderCliFields(idPrefix, name, cli, d, currentModel, saved) {
  saved = saved || {};
  const opts = (d.cli_options && d.cli_options[cli]) || {models: [], permission_modes: [], effort_levels: []};
  const modelOpts = ['(' + (currentModel || opts.models[0] || '') + ')', ...opts.models, '…']
    .map(m => `<option value="${m.startsWith('(') ? '' : m}" ${m === saved.model ? 'selected' : ''}>${m}</option>`).join('');
  const pmOpts = opts.permission_modes.map(m =>
    `<option ${m === (saved.pm || 'auto') ? 'selected' : ''}>${m}</option>`).join('');
  const defaultEffort = opts.effort_levels[opts.effort_levels.length - 1];
  const efOpts = opts.effort_levels.map(m =>
    `<option ${m === (saved.effort || defaultEffort) ? 'selected' : ''}>${m}</option>`).join('');
  const showOther = saved.model === '__other__';
  return `
      <label>${t('modelLabel')}
        <select id="${idPrefix}-model-${name}"
          onchange="optsChoice['${name}']={...(optsChoice['${name}']||{}),model:this.value}; this.nextElementSibling.style.display = this.value==='__other__' ? '' : 'none'">
          ${modelOpts.replace(/value="…"( selected)?/, 'value="__other__"$1')}
        </select>
      </label>
      <input type="text" id="${idPrefix}-model-other-${name}" placeholder="model id"
        style="display:${showOther ? '' : 'none'}" value="${saved.modelOther || ''}"
        oninput="optsChoice['${name}']={...(optsChoice['${name}']||{}),modelOther:this.value}">
      <label>${t('pmLabel')}
        <select id="${idPrefix}-pm-${name}"
          onchange="optsChoice['${name}']={...(optsChoice['${name}']||{}),pm:this.value}">${pmOpts}</select>
      </label>
      <label>${t('effortLabel')}
        <select id="${idPrefix}-effort-${name}"
          onchange="optsChoice['${name}']={...(optsChoice['${name}']||{}),effort:this.value}">${efOpts}</select>
      </label>`;
}

function onCliChange(idPrefix, name, cli) {
  optsChoice[name] = {...(optsChoice[name] || {}), cli};
  document.getElementById(`${idPrefix}-fields-${name}`).innerHTML =
    renderCliFields(idPrefix, name, cli, LAST, '', optsChoice[name]);
}

function unifiedOptsRow(s, d, colspan) {
  const saved = optsChoice[s.name] || {};
  const cli = saved.cli || s.cli;
  const cliOpts = d.cli_list.map(c => `<option value="${c}" ${c === cli ? 'selected' : ''}>${c}</option>`).join('');
  const modeChoices = s.running
    ? [['newchat', t('modeChoiceNewchatOnly')]]
    : [
        ['resume', t('modeChoiceResume')],
        ['reset', t('modeChoiceReset')],
        ['newchat', t('modeChoiceNewchat')],
      ];
  const radios = modeChoices.map(([val, label], i) => `
      <label class="mode-radio"><input type="radio" name="mode-${s.name}" value="${val}" ${(saved.mode || modeChoices[0][0]) === val ? 'checked' : ''} onchange="optsChoice['${s.name}']={...(optsChoice['${s.name}']||{}),mode:this.value}; updateGoLabel('${s.name}')"> ${label}</label>`).join('');
  const runningNote = s.running
    ? `<span class="opts-hint">${t('runningNote')(s.name)}</span>`
    : '';
  return `
    <tr class="opts-row"><td colspan="${colspan}"><div class="opts">
      ${runningNote}
      <div class="modes">${radios}</div>
      <span class="opts-hint" id="opt-hint-${s.name}"></span>
      <label>${t('cliLabel')}
        <select id="opt-cli-${s.name}" onchange="onCliChange('opt', '${s.name}', this.value)">${cliOpts}</select>
      </label>
      <span id="opt-fields-${s.name}">${renderCliFields('opt', s.name, cli, d, s.model, saved)}</span>
      <button class="go" id="opt-go-${s.name}" onclick="doAction('${s.name}', this)">${modeLabels()[saved.mode || modeChoices[0][0]]}</button>
      <button onclick="optsChoice['${s.name}']=null; optsFor=null; render(LAST)">${t('cancelBtn')}</button>
    </div></td></tr>`;
}

function toggleOpts(name) {
  optsFor = (optsFor === name) ? null : name;
  if (optsFor !== name) optsChoice[name] = null;
  render(LAST);
  if (optsFor === name) updateGoLabel(name);
}

// ── terminal (tmux-backed sessions) ─────────────────────────────────────────
// Ayrı, hızlı (200ms) poll döngüsü — mevcut 4s status refresh()'e KATILMAZ.

let xtermLibPromise = null;   // tek-seferlik lazy-load, başarısız olursa RETRY edilebilir (bkz. loadXtermLib)
const xtermInstances = {};    // name -> {term, cols, rows}
// 'Enter': boş text ile bile göndermek gerekiyor (TUI'lerde "devam için Enter" gibi
// içerik-yazmadan onaylama) — sendTermInput ise boş input'ta ERKEN ÇIKAR (`if (!text) return`),
// bu yüzden düz Enter'ın buradan, tmux_send_special_key ile, ayrı bir buton olarak gitmesi şart
// (canlı rapor: mobilde klavyenin Enter/Git tuşu onkeydown'daki `event.key==='Enter'` kontrolünü
// hiç tetiklemiyor — IME/predictive-text kaynaklı bilinen bir mobil tarayıcı davranışı).
const XTERM_KEYS = [['↵','Enter'], ['ctrl-c','C-c'], ['esc','Escape'], ['↑','Up'], ['↓','Down'], ['←','Left'], ['→','Right'], ['tab','Tab']];

function termRow(s, colspan) {
  const keyBtns = XTERM_KEYS.map(([label, key]) =>
    `<button onclick="sendTermKey('${s.name}','${key}')">${label}</button>`).join('');
  // position:fixed → tablonun içinde olsa da tam ekran overlay olarak render olur
  // (satır kendisi neredeyse yer kaplamaz, fixed çocuğu viewport'u kaplar).
  return `
    <tr class="opts-row"><td colspan="${colspan}" style="padding:0;border:0">
      <div style="position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:1000;
        display:flex;align-items:center;justify-content:center" onclick="if(event.target===this) toggleTerm('${s.name}')">
        <div style="max-width:95vw;max-height:92vh;width:fit-content;background:var(--panel);
          border-radius:8px;display:flex;flex-direction:column;align-items:flex-start;
          padding:.7rem;box-sizing:border-box">
          <div style="display:flex;align-items:center;justify-content:space-between;
            margin-bottom:.4rem;width:100%;box-sizing:border-box">
            <strong>${s.name}</strong>
            <span>
              <button onclick="copyTermText('${s.name}', this)" title="${t('termCopyHint')}">${t('termCopyBtn')}</button>
              <button onclick="toggleTerm('${s.name}')" style="font-size:1rem;line-height:1;padding:.2rem .55rem">✕</button>
            </span>
          </div>
          <div class="tabs" style="margin-bottom:.5rem;width:100%;box-sizing:border-box">
            <button id="tab-termview-${s.name}" class="active" onclick="switchTermTab('${s.name}','term')">${t('tabTermView')}</button>
            <button id="tab-chatview-${s.name}" onclick="switchTermTab('${s.name}','chat')">${t('tabChatView')}</button>
          </div>
          <div id="term-view-${s.name}" style="width:100%">
            <div id="term-urls-${s.name}" hidden style="width:100%;box-sizing:border-box;margin-bottom:.3rem"></div>
            <div id="xterm-${s.name}" style="background:#111;padding:.35rem;border-radius:4px;
              overflow:auto;max-width:calc(95vw - 1.4rem);max-height:calc(92vh - 130px);
              box-sizing:content-box;font-family:monospace;font-size:.8rem;color:#ddd;
              white-space:pre-wrap"></div>
            <div class="opts-hint" id="term-hint-${s.name}" style="width:100%;box-sizing:border-box"></div>
            <div class="opts" style="margin-top:.4rem;width:100%;box-sizing:border-box">
              ${keyBtns}
              <input type="text" id="term-in-${s.name}" placeholder="${t('termPlaceholder')}"
                style="flex:1;min-width:200px" onkeydown="if(event.key==='Enter') sendTermInput('${s.name}')">
              <button class="go" onclick="sendTermInput('${s.name}')">${t('termSend')}</button>
            </div>
          </div>
          <div id="chat-view-${s.name}" hidden style="width:min(560px,85vw);max-height:calc(92vh - 130px);
            overflow:auto;box-sizing:border-box"></div>
        </div>
      </div>
    </td></tr>`;
}

function loadXtermLib() {
  if (xtermLibPromise) return xtermLibPromise;
  xtermLibPromise = (async () => {
    try {
      if (!document.getElementById('xterm-css-link')) {
        const link = document.createElement('link');
        link.id = 'xterm-css-link'; link.rel = 'stylesheet';
        link.href = withToken('/static/xterm.css');
        document.head.appendChild(link);
      }
      await new Promise((resolve, reject) => {
        if (window.Terminal) { resolve(); return; }
        const s = document.createElement('script');
        s.src = withToken('/static/xterm.js');
        s.onload = resolve;
        s.onerror = () => reject(new Error('xterm.js load failed'));
        document.head.appendChild(s);
      });
      return true;
    } catch (e) {
      // Kalıcı bir "xtermFailed=true" bayrağı KOYMA — mobil/hücresel bağlantıda
      // TEK SEFERLİK bir ağ aksaklığı (canlı gözlemlendi: gerçek telefonda xterm.js
      // bir kez yüklenemeyince o sekme SONSUZA dek ham-ANSI-kod fallback'ine
      // kilitleniyordu, sayfa yenilemeden düzelmiyordu). Bunun yerine promise'i
      // sıfırla — bir sonraki "terminal" aç denemesi (aynı ya da başka session)
      // fetch'i baştan dener; `window.Terminal` zaten yüklüyse anında no-op döner.
      xtermLibPromise = null;
      return false;
    }
  })();
  return xtermLibPromise;
}

async function ensureXtermFor(name) {
  if (xtermInstances[name]) return;
  const ok = await loadXtermLib();
  if (!ok || !window.Terminal) return;
  const container = document.getElementById('xterm-' + name);
  if (!container) return;
  container.style.whiteSpace = '';  // xterm.js kendi satır sarmalamasını yapar
  const fontSize = computeFitFontSize(160);
  const term = new Terminal({cols: 160, rows: 45, scrollback: 5000, convertEol: false, disableStdin: true, fontSize});
  term.open(container);
  xtermInstances[name] = {term, cols: 160, rows: 45};
  fitContainerToTerm(name, 160, 45);
}

// Gerçek terminal (masaüstündeki gnome-terminal penceresinin GERÇEK boyutuna göre
// tmux pane'i kaç sütunsa o kadar) DAR bir mobil ekrana asla sabit font-size'la
// SIĞMAZ — metin kırpılır, yatay scroll keşfedilmesi zor/görünmez kalır ("kaymış"
// şikayeti). Doğrusu: gerçek terminal istemcilerinin yaptığı gibi, TÜM sütunlar
// mevcut viewport genişliğine sığacak şekilde font-size'ı KÜÇÜLTMEK — viewport'a
// göre (DOM'a göre DEĞİL, o zaten circular-measurement tuzağına düşürüyordu, bkz.
// fitContainerToTerm'in kendi notu).
function computeFitFontSize(cols) {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  ctx.font = '100px monospace';
  const cellWidthAt100 = ctx.measureText('0').width;
  const available = Math.max(200, window.innerWidth * 0.92 - 40);
  const fit = (available / cols) / cellWidthAt100 * 100;
  return Math.max(7, Math.min(fit, 15));
}

function fitContainerToTerm(name, cols, rows) {
  // container.style genişlik/yükseklik VERMEDEN önce xterm açılırsa .xterm-viewport
  // (position:absolute, parent'a stretch) ölçülür — bu kendi kendine referans veren
  // (circular) bir ölçüm, gerçek karakter-grid boyutunu YANSITMAZ (denendi, işe
  // yaramadı: kutu hep container'ın o anki — genelde stretch edilmiş — boyutuna
  // eşit çıkıyordu). Doğrusu: xterm'in KENDİ kullandığı hücre boyutunu (FitAddon'ın
  // da kullandığı private-ama-stabil `_core._renderService.dimensions`) OKUYUP
  // cols/rows'a çarparak container'ı ÖNCEDEN, DOM'a bakmadan boyutlandırmak.
  const inst = xtermInstances[name];
  const container = document.getElementById('xterm-' + name);
  if (!inst || !container) return;
  requestAnimationFrame(() => {
    try {
      const dims = inst.term._core._renderService.dimensions.css.cell;
      if (dims && dims.width > 0 && dims.height > 0) {
        container.style.width = Math.ceil(cols * dims.width) + 'px';
        container.style.height = Math.ceil(rows * dims.height) + 'px';
        return;
      }
    } catch (e) { /* internal API değişmiş/erişilemez — canvas fallback'e düş */ }
    const cw = measureCharWidthPx();
    container.style.width = Math.ceil(cols * cw) + 'px';
    container.style.height = Math.ceil(rows * cw * 2) + 'px';  // kaba satır-yüksekliği tahmini
  });
}

let _charWidthPx = null;
function measureCharWidthPx() {
  if (_charWidthPx == null) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    ctx.font = '12.8px monospace';  // 0.8rem @ 16px root
    _charWidthPx = ctx.measureText('0'.repeat(100)).width / 100;
  }
  return _charWidthPx;
}

function toggleTerm(name) {
  if (termPollTimer) { clearInterval(termPollTimer); termPollTimer = null; }
  const prev = termFor;
  termFor = (termFor === name) ? null : name;
  // Kapatılan (ya da başka bir session'a geçilirken bırakılan) eski instance'ı
  // dispose+sil — yoksa ensureXtermFor'un `if (xtermInstances[name]) return`
  // guard'ı bir SONRAKİ açılışta "zaten kurulu" sanıp YENİ container'a hiç
  // bağlanmıyor, terminal kalıcı olarak boş/küçük kalıyor (canlı doğrulandı,
  // 2026-08-28: kapat→tekrar aç → childCount 0). Taze aç = taze Terminal().
  if (prev && prev !== termFor && xtermInstances[prev]) {
    try { xtermInstances[prev].term.dispose(); } catch (e) {}
    delete xtermInstances[prev];
  }
  if (prev !== termFor) termTab = 'term';  // taze açılış (ya da kapama) → varsayılana dön
  if (prev && prev !== termFor && chatPollTimers[prev]) {
    clearInterval(chatPollTimers[prev]);
    delete chatPollTimers[prev];
  }
  render(LAST);
  if (termFor) {
    ensureXtermFor(termFor).then(() => pollTerm(termFor));
    termPollTimer = setInterval(() => pollTerm(termFor), 200);
  }
}

async function pollTerm(name) {
  const r = await fetch(withToken(`/api/term/output?name=${encodeURIComponent(name)}`));
  const d = await r.json();
  if (d.ok) renderTermUrls(name, d.text);
  const inst = xtermInstances[name];
  const hint = document.getElementById('term-hint-' + name);
  if (inst) {
    // capture-pane her seferinde TÜM panel durumunu döner (delta değil) — reset+rewrite
    // ŞART, ama kullanıcı yukarı kaydırmışken bunu her 200ms'de yapmak onu hemen dibe
    // geri fırlatıyordu ("yukarı çıkamıyorum" şikayeti) — dipte DEĞİLSE güncellemeyi
    // atla, kullanıcı okumasını bitirip dibe dönünce canlı akış otomatik devam eder.
    const buf = inst.term.buffer.active;
    const atBottom = buf.viewportY >= buf.baseY;
    if (!atBottom) {
      if (hint) hint.textContent = t('termScrolledHint');
      return;
    }
    if (hint) hint.textContent = '';
    const resized = d.cols && d.rows && (d.cols !== inst.cols || d.rows !== inst.rows);
    if (resized) {
      inst.term.options.fontSize = computeFitFontSize(d.cols);
      inst.term.resize(d.cols, d.rows);
      inst.cols = d.cols; inst.rows = d.rows;
      fitContainerToTerm(name, d.cols, d.rows);
    }
    // Ekran içerik olarak AYNIYSA reset+write'ı tamamen atla — spinner/token akışı
    // olmayan sakin anlarda (çoğu 200ms tick) hiçbir görsel titreme/"kayma" olmasın.
    // Boyut değiştiyse (yukarıda resize edildi) yine de tazele — eski buffer artık
    // yanlış genişlikte kalmış olabilir.
    if (d.ok && d.text === inst.lastText && !resized) {
      // no-op
    } else if (d.ok) {
      inst.lastText = d.text;
      inst.term.reset();
      // write()'ın 2. argümanı (callback) yazılan veri GERÇEKTEN işlenip buffer'a
      // girdikten SONRA çağrılır (write() kendisi async — hemen sonra scrollToBottom
      // çağırmak veri henüz parse edilmeden çalışıp yarış durumuna düşebilirdi).
      // ŞART: resize() hemen öncesinde oldu (boyut değiştiyse) ve xterm.js'in kendi
      // "yeni yazımda dipteyse dipte kal" takibi resize+reset ile aynı tick'te bozulup
      // görünüşte donmuş/boş bir ekranda kalabiliyordu (canlı bulundu, diag20260827/
      // windowless-fallback session'da: içerik dolu ama viewport dip DEĞİL) — write
      // BİTTİKTEN sonra AÇIKÇA dibe kaydırmak bu duruma bakılmaksızın doğru son hâli
      // garanti ediyor.
      inst.term.write(d.text, () => inst.term.scrollToBottom());
    } else {
      inst.lastText = null;
      inst.term.reset();
      inst.term.write(t('termGone')(d.error));
    }
    return;
  }
  // xterm.js yüklenemedi (gerçekten offline vb.) — düz metin fallback. capture-pane
  // ham ANSI escape kodlarıyla gelir (`\x1b[38;5;179m` gibi) — xterm.js olmadan bunlar
  // YORUMLANMAZ, harfiyen görünür (canlı doğrulandı: gerçek telefonda xterm.js bir kez
  // yüklenemeyince ekran "[38;5;179m█[38;5;208m..." gibi okunaksız kod çorbasıydı) —
  // en azından okunaklı kalsın diye kodları temizleyip düz metin gösteriyoruz.
  const container = document.getElementById('xterm-' + name);
  if (!container) return;
  container.textContent = d.ok ? stripAnsi(d.text) : t('termGone')(d.error);
}

function stripAnsi(text) {
  // eslint-disable-next-line no-control-regex
  return text.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '').replace(/\x1b\][^\x07]*\x07/g, '');
}

// xterm.js kendi seçimini mouse'la sürükleyerek yapar (CSS'inde `user-select:none`
// var, tarayıcının NATİF seçimi bilerek kapatılmış) — mobilde dokunarak seçim
// tarayıcıdan tarayıcıya güvenilmez/tutarsız çalışıyor (canlı kullanıcı raporu).
// Dokunma-seçimiyle uğraşmak yerine: görünen tüm çıktıyı (ANSI temizlenmiş) tek
// dokunuşla panoya kopyalayan bir buton — platformdan bağımsız çalışır.
async function copyTermText(name, btn) {
  const orig = btn.textContent;
  try {
    const r = await fetch(withToken(`/api/term/output?name=${encodeURIComponent(name)}`));
    const d = await r.json();
    if (!d.ok) { alert(name + ': ' + d.error); return; }
    await navigator.clipboard.writeText(stripAnsi(d.text));
    btn.textContent = t('termCopied');
    setTimeout(() => { btn.textContent = orig; }, 1200);
  } catch (e) {
    alert(t('requestFailed') + e.message);
  }
}

// Login akışları (agy device-code, claude OAuth, ileride codex/deepseek...) çıktıya
// bir URL basıyor — mobilde xterm.js'in içinden dokunarak URL seçmek güvenilmez (bkz.
// termCopyHint), kullanıcı canlı olarak "URL'i metinden elle çıkardım" dedi. Provider-
// bazlı ÖZEL bir kanca YOK — capture-pane metninde regex ile URL ara, bulunca kopyala/aç
// butonlarıyla göster; böylece herhangi bir CLI backend'i için otomatik çalışır.
const TERM_URL_RE = /https?:\/\/[^\s<>"'\x1b\x07]+/g;

function extractTermUrls(rawText) {
  const clean = stripAnsi(rawText);
  const matches = clean.match(TERM_URL_RE) || [];
  const seen = new Set();
  const out = [];
  for (let i = matches.length - 1; i >= 0 && out.length < 3; i--) {
    const u = matches[i].replace(/[.,;:)\]}>'"]+$/, '');
    if (!seen.has(u)) { seen.add(u); out.push(u); }
  }
  return out;
}

async function copyTermUrl(url, btn) {
  const orig = btn.textContent;
  try {
    await navigator.clipboard.writeText(url);
    btn.textContent = t('termCopied');
    setTimeout(() => { btn.textContent = orig; }, 1200);
  } catch (e) {
    alert(t('requestFailed') + e.message);
  }
}

function renderTermUrls(name, rawText) {
  const box = document.getElementById('term-urls-' + name);
  if (!box) return;
  const urls = extractTermUrls(rawText);
  box.textContent = '';
  if (!urls.length) { box.hidden = true; return; }
  box.hidden = false;
  urls.forEach(u => {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:.35rem;align-items:center;margin:.15rem 0;overflow:hidden';
    const span = document.createElement('span');
    span.textContent = u;
    span.style.cssText = 'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;'
      + 'white-space:nowrap;font-family:monospace;font-size:.75rem';
    const a = document.createElement('a');
    a.href = u; a.target = '_blank'; a.rel = 'noopener';
    a.textContent = t('termOpen');
    a.style.whiteSpace = 'nowrap';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = t('termCopyBtn');
    btn.style.whiteSpace = 'nowrap';
    btn.onclick = () => copyTermUrl(u, btn);
    row.appendChild(span); row.appendChild(a); row.appendChild(btn);
    box.appendChild(row);
  });
}

// 'Sohbet' sekmesi: xterm.js/ANSI yerine provider'ın kendi transcript'inden okunan
// STRUCTURED son-mesaj-çifti — canlı kullanıcı raporu (2026-08-31): terminal sekmesi
// mobilde scroll ederken/refresh'te sürekli yanlış yere zıplıyor, "en başta olması
// gereken kaymış" görünüyor. Kök neden xterm.js'in kendi viewport/reset-rewrite
// mekanizması (pollTerm) — o mekanizmaya dokunmadan, PARALEL bir görünüm: düz
// HTML metin, tarayıcının NATİF scroll'u, tartışacak bir "viewport" state'i yok.
const chatPollTimers = {};

async function pollChat(name) {
  let d;
  try {
    const r = await fetch(withToken(`/api/term/chat?name=${encodeURIComponent(name)}`));
    d = await r.json();
  } catch (e) {
    d = {ok: false, error: e.message};
  }
  renderChatView(name, d);
}

function renderChatView(name, d) {
  const box = document.getElementById('chat-view-' + name);
  if (!box) return;
  box.textContent = '';
  if (!d.ok) {
    box.textContent = t('chatLoadError') + (d.error || '');
    return;
  }
  if (!d.supported) {
    box.textContent = t('chatUnsupported');
    return;
  }
  const mk = (label, text) => {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'margin-bottom:.7rem';
    const h = document.createElement('div');
    h.textContent = label;
    h.style.cssText = 'font-weight:600;font-size:.75rem;opacity:.7;margin-bottom:.2rem';
    const body = document.createElement('div');
    body.textContent = text || t('chatEmpty');
    body.style.cssText = 'white-space:pre-wrap;font-size:.85rem;line-height:1.45;'
      + 'background:var(--panel2);border:1px solid var(--border);border-radius:6px;padding:.5rem';
    wrap.appendChild(h); wrap.appendChild(body);
    return wrap;
  };
  box.appendChild(mk(t('chatYou'), d.user));
  box.appendChild(mk(t('chatAssistant'), d.assistant));
}

// Sadece görünürlük/active-class uygular, timer'a DOKUNMAZ — render()'ın 4s'lik
// tam-DOM-yeniden-kuruşundan SONRA "hangi sekmedeydik" state'ini geri uygulamak için
// (chatPollTimers zaten DOM'dan bağımsız arka planda akıyor, ona dokunulursa dup olur).
function applyTermTabVisual(name, tab) {
  const termBtn = document.getElementById('tab-termview-' + name);
  const chatBtn = document.getElementById('tab-chatview-' + name);
  const termView = document.getElementById('term-view-' + name);
  const chatView = document.getElementById('chat-view-' + name);
  if (!termBtn || !chatBtn || !termView || !chatView) return false;
  const isChat = tab === 'chat';
  termBtn.classList.toggle('active', !isChat);
  chatBtn.classList.toggle('active', isChat);
  termView.hidden = isChat;
  chatView.hidden = !isChat;
  return true;
}

function switchTermTab(name, tab) {
  if (!applyTermTabVisual(name, tab)) return;
  termTab = tab;
  const isChat = tab === 'chat';
  if (chatPollTimers[name]) { clearInterval(chatPollTimers[name]); delete chatPollTimers[name]; }
  if (isChat) {
    pollChat(name);
    chatPollTimers[name] = setInterval(() => pollChat(name), 2500);
  }
}

async function sendTermKey(name, key) {
  await fetch(withToken('/api/term/key'), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name, key, lang: LANG}),
  });
}

async function sendTermInput(name) {
  const input = document.getElementById('term-in-' + name);
  if (!input) return;
  const text = input.value;
  if (!text) return;
  input.value = '';
  await fetch(withToken('/api/term/input'), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name, text, lang: LANG}),
  });
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
  const cli = document.getElementById('opt-cli-' + name).value;
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
        body: JSON.stringify({base: name, model, permission_mode, effort, cli, lang: LANG}),
      });
      if (r.status === 401) { alert(t('authErrorShort')); }
      else {
        const d = await safeJson(r);
        if (d.ok) alert(t('newChatStarted') + d.name);
        else runDiagAfterFailure(name + ': ' + d.error);
      }
    } catch (e) {
      alert(t('requestFailed') + e.message);
    }
  } else {
    await call('start', {name, model, permission_mode, effort, cli, fresh: mode === 'reset'});
  }
  optsFor = null;
  optsChoice[name] = null;
  refresh();
}

async function doReactivate(name, btn) {
  btn.disabled = true;
  btn.textContent = t('starting');
  await call('reactivate', {name});
  refresh();
}

async function doOpenWindow(name, btn) {
  btn.disabled = true;
  btn.textContent = t('openingWindow');
  await call('term/open-window', {name});
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
    if (!d.ok) {
      if (action === 'start') runDiagAfterFailure(payload.name + ': ' + d.error);
      else alert(payload.name + ': ' + d.error);
    }
  } catch (e) {
    alert(t('requestFailed') + e.message);
  }
}

// ── layout ──────────────────────────────────────────────────────────────────

function renderLayoutBox(d) {
  const missing = d.layout_missing_deps || [];
  const warn = missing.length
    ? `<span class="opts-hint" style="color:var(--red)">${t('layoutMissingPrefix')}${missing.join(', ')}${t('layoutMissingSuffix')}${missing.join(' ')}</span>`
    : `<span class="opts-hint">(${t('layoutDesc')})</span>`;
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

// ── diag (tanı) ───────────────────────────────────────────────────────────

function fmtUptime(sec) {
  if (sec == null) return t('diagUptimeUnknown');
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
}

let DIAG_LOG_LINES = [];

async function loadDiagLog() {
  try {
    const r = await fetch(withToken('/api/diag/log'));
    const d = await safeJson(r);
    DIAG_LOG_LINES = d.lines || [];
  } catch (e) {
    DIAG_LOG_LINES = [];
  }
  const box = document.getElementById('diag-log-box');
  if (box) box.textContent = DIAG_LOG_LINES.length ? DIAG_LOG_LINES.join('\\n') : t('empty');
}

function renderDiagBox(d, runningCount) {
  const diag = d.diag || {};
  const gt = diag.gt;
  const gtLine = gt
    ? `${t('diagGtUptime')}: pid ${gt.pid} — ${fmtUptime(gt.uptime_seconds)}`
    : `${t('diagGtUptime')}: ${t('diagGtNotFound')}`;
  const webLine = `${t('diagWebUptime')}: pid ${diag.web_pid ?? '?'} — ${fmtUptime(diag.web_uptime_seconds)}`;
  const windowless = diag.windowless || [];
  const windowlessLine = windowless.length
    ? `<div class="opts-hint" style="color:var(--amber);flex-basis:100%">${t('diagWindowless')(windowless.join(', '))}</div>`
    : '';
  const cliOpts = (d.cli_list || []).map(c => `<option value="${c}">${c}</option>`).join('');
  return `
    <div class="opts-hint">${t('diagDesc')}</div>
    <div class="opts" id="diagPanel">
      <div style="flex-basis:100%">${webLine}<br>${gtLine}</div>
      ${windowlessLine}
      <button class="go" id="diag-test-go" onclick="doDiagTest(this)">${t('diagTestBtn')}</button>
      <button class="stop" id="diag-restart-go" onclick="doDiagRestartGt(this, ${runningCount})">${t('diagRestartBtn')}</button>
    </div>
    <pre id="diag-result" class="layout-result"></pre>
    <div class="opts" id="diagAskPanel">
      <label>${t('diagAskCliLabel')}
        <select id="diag-ask-cli">${cliOpts}</select>
      </label>
      <label style="flex-basis:100%">${t('diagAskQuestionLabel')}
        <input type="text" id="diag-ask-q" placeholder="${t('diagAskQuestionPlaceholder')}">
      </label>
      <button class="go" id="diag-ask-go" onclick="doDiagAsk(this, ${runningCount})">${t('diagAskBtn')}</button>
    </div>
    <pre id="diag-ask-result" class="layout-result"></pre>
    <div class="opts-hint">${t('diagLogTitle')}</div>
    <pre id="diag-log-box" class="layout-result">${t('diagLogLoading')}</pre>
    <div class="opts-hint">${t('diagRefreshHint')}</div>`;
}

async function doDiagTest(btn) {
  const resultBox = document.getElementById('diag-result');
  btn.disabled = true;
  btn.textContent = t('diagTesting');
  resultBox.textContent = '';
  try {
    const r = await fetch(withToken('/api/diag/spawn-test'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({lang: LANG}),
    });
    if (r.status === 401) { alert(t('authErrorShort')); }
    else {
      const d = await safeJson(r);
      if (d.ok) resultBox.textContent = t('diagTestOk');
      else if (d.stderr) resultBox.textContent = t('diagTestFailStderr')(d.stderr);
      else resultBox.textContent = d.detail ? ('✗ ' + d.detail) : t('diagTestFailWindow');
    }
  } catch (e) {
    resultBox.textContent = '✗ ' + t('requestFailed') + e.message;
  }
  btn.disabled = false;
  btn.textContent = t('diagTestBtn');
  loadDiagLog();
  refresh();
}

async function doDiagRestartGt(btn, runningCount) {
  if (!confirm(t('diagRestartConfirm')(runningCount))) return;
  const resultBox = document.getElementById('diag-result');
  btn.disabled = true;
  btn.textContent = t('diagRestarting');
  resultBox.textContent = '';
  try {
    const r = await fetch(withToken('/api/diag/restart-gt'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({lang: LANG}),
    });
    if (r.status === 401) { alert(t('authErrorShort')); }
    else {
      const d = await safeJson(r);
      resultBox.textContent = d.ok ? t('diagRestartDone')(d.result) : ('✗ ' + d.error);
    }
  } catch (e) {
    resultBox.textContent = '✗ ' + t('requestFailed') + e.message;
  }
  btn.disabled = false;
  btn.textContent = t('diagRestartBtn');
  loadDiagLog();
  refresh();
}

async function doDiagAsk(btn) {
  const cli = document.getElementById('diag-ask-cli').value;
  const extra_question = document.getElementById('diag-ask-q').value;
  const resultBox = document.getElementById('diag-ask-result');
  btn.disabled = true;
  btn.textContent = t('diagAsking');
  resultBox.textContent = '';
  try {
    const r = await fetch(withToken('/api/diag/ask'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cli, extra_question, lang: LANG}),
    });
    if (r.status === 401) { alert(t('authErrorShort')); }
    else {
      const d = await safeJson(r);
      if (d.ok) {
        resultBox.textContent = t('diagAskStarted')(d.name);
        setTab('running');
        await refresh();      // termFor render'ının bulacağı satır LAST'e girsin
        toggleTerm(d.name);
      } else {
        resultBox.textContent = '✗ ' + d.error;
      }
    }
  } catch (e) {
    resultBox.textContent = '✗ ' + t('requestFailed') + e.message;
  }
  btn.disabled = false;
  btn.textContent = t('diagAskBtn');
  loadDiagLog();
  refresh();
}

function runDiagAfterFailure(msg) {
  if (confirm(msg + '\\n\\n' + t('diagRunAfterFail'))) {
    setTab('diag');
    loadDiagLog();
    const btn = document.getElementById('diag-test-go');
    if (btn) doDiagTest(btn);
  }
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

    def _serve_static(self, path: str) -> bool:
        """`resolve_static_path(path)` bulursa dosyayı yollar (True); bulamazsa
        hiçbir şey yazmaz (caller 404 kararını kendi verir)."""
        fpath = resolve_static_path(path)
        if fpath is None:
            return False
        ctype, _ = mimetypes.guess_type(str(fpath))
        ctype = ctype or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        body = fpath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_GET(self):
        path = urlparse(self.path).path
        # /assets/* token KONTROLÜ OLMADAN erişilebilir olmak ZORUNDA: tarayıcı
        # <script src>/<link> sub-resource isteklerine ?token= ekleyemez (sadece
        # üst-seviye navigasyon URL'i query string taşır) — bu carve-out yoksa
        # build edilmiş app "/" token'la yüklenir ama JS/CSS 401 alır → boş sayfa.
        # Güvenlik regresyonu değil: bundle'da sır yok (public MIT repo), gerçek
        # fleet verisi sadece /api/* ve /ws'de, ikisi de auth'lu kalıyor.
        if path.startswith("/assets/"):
            if not self._serve_static(path):
                self._json({"error": "not found"}, status=404)
            return
        if not self._authorized():
            self._unauthorized()
            return
        if path == "/":
            if not self._serve_static("/"):
                self._json({"error": "not found"}, status=404)
            return
        elif path == "/ws":
            # web_ws.handle_ws kendi response'unu (101 ya da red) doğrudan
            # handler.wfile'a yazar — burada _json/send_response YOK, aksi
            # halde WS handshake baytlarının üstüne normal HTTP baytları
            # biner (bozuk response). Fonksiyon dönene kadar (bağlantı
            # kapanana kadar) bloklar; do_GET bu thread'in kendisi zaten
            # (ThreadingHTTPServer: connection-başına-thread).
            web_ws.handle_ws(self)
            return
        elif path == "/api/status":
            self._json(_status_payload())
        elif path == "/api/diag/log":
            self._json({"lines": diag_log_tail(30)})
        elif path == "/api/term/output":
            qs = parse_qs(urlparse(self.path).query)
            name = (qs.get("name") or [""])[0].strip()
            lang = "en" if (qs.get("lang") or [""])[0] == "en" else "tr"
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            self._json(_term_output(name, lang=lang))
        elif path == "/api/term/chat":
            qs = parse_qs(urlparse(self.path).query)
            name = (qs.get("name") or [""])[0].strip()
            lang = "en" if (qs.get("lang") or [""])[0] == "en" else "tr"
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            self._json(_term_chat(name, lang=lang))
        elif path.startswith("/static/"):
            fname = path[len("/static/"):]
            if fname not in ("xterm.js", "xterm.css"):
                self._json({"error": "not found"}, status=404)
                return
            vendor_dir = _ensure_xterm_assets()
            if not vendor_dir:
                self._json({"error": "unavailable"}, status=503)
                return
            fpath = os.path.join(vendor_dir, fname)
            ctype = "application/javascript" if fname.endswith(".js") else "text/css"
            with open(fpath, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            if not self._serve_static(path):
                self._json({"error": "not found"}, status=404)

    def do_POST(self):
        if not self._authorized():
            self._unauthorized()
            return
        path = urlparse(self.path).path
        if path not in ("/api/start", "/api/stop", "/api/retire", "/api/reactivate",
                         "/api/new-chat", "/api/layout", "/api/register", "/api/close",
                         "/api/handover", "/api/adopt", "/api/term/input", "/api/term/key",
                         "/api/term/open-window",
                         "/api/diag/spawn-test", "/api/diag/restart-gt", "/api/diag/ask"):
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

        if path == "/api/diag/spawn-test":
            self._json(_diag_spawn_test(lang=lang))
            return

        if path == "/api/diag/restart-gt":
            self._json(_diag_restart_gt(lang=lang))
            return

        if path == "/api/diag/ask":
            self._json(_diag_ask(
                cli=str(data.get("cli", "")),
                extra_question=str(data.get("extra_question", "")),
                lang=lang,
            ))
            return

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
                cli=str(data.get("cli", "")),
                lang=lang,
            ))
            return

        if path == "/api/register":
            self._json(_register_project(
                name=str(data.get("name", "")),
                cwd=str(data.get("cwd", "")),
                model=str(data.get("model", "")),
                cli=str(data.get("cli", "")),
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

        if path == "/api/term/input":
            name = str(data.get("name", "")).strip()
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            self._json(_term_input(name, text=str(data.get("text", "")), lang=lang))
            return

        if path == "/api/term/key":
            name = str(data.get("name", "")).strip()
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            self._json(_term_key(name, key=str(data.get("key", "")), lang=lang))
            return

        if path == "/api/term/open-window":
            name = str(data.get("name", "")).strip()
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            self._json(_open_window(name, lang=lang))
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
                cli=str(data.get("cli", "")),
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
