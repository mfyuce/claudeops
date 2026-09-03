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
from ..handover import HANDOVER_MSG_DEFAULT, HANDOVER_MSG_DEFAULT_EN, default_handover_effort
from ..kill import kill_session, kill_session_and_parent, KILL_GRACE_SECONDS
from ..needs_ho import needs_ho
from ..session import Session
from ..paths import CLAUDEOPS_DIR, MODELS_TSV, REPO_DIR, ROSTER_TSV
from ..settings import default_model_for, load_settings, save_settings
from ..spawn import spawn_session, detect_display, find_latest_jsonl, open_window
from ..providers import PROVIDERS, DEFAULT_CLI, get_provider
from ..tmux_backend import (
    is_tmux_backed, tmux_has_session, tmux_capture, tmux_send_keys,
    tmux_send_special_key, tmux_pane_size, ALLOWED_SPECIAL_KEYS,
)
from .web_static import DIST_DIR, resolve_static_path
from . import web_ws

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"
TOKEN_FILE = os.path.join(CLAUDEOPS_DIR, "web.token")
TUNNEL_LOG = os.path.join(CLAUDEOPS_DIR, "tunnel.log")
_TUNNEL_URL_RE = re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com")

# [[spawn-zombie-child-degrades-web-server]] — bu process'in kendi yaşı ("Tanı"
# sekmesinde gösterilir) iki bilinen sessiz-spawn-başarısızlığı sebebinden biri.
_WEB_PROC_START_MONO = time.monotonic()
# Client'ın "sunucu benim yüklediğimden FARKLI bir process mi" (yeni deploy sonrası
# restart) tespiti için — wall-clock, monotonic'in aksine YENİDEN BAŞLATILAN bir
# process'in DEĞERİ öncekiyle basitçe karşılaştırılabilir bir sayı olsun diye.
# 2026-08-31, kullanıcı: "yenilenince de auto refresh" — deploy sonrası açık kalan
# sekmeler manuel yenilemeye gerek kalmadan yeni sürümü göstersin (useStatus.ts).
_WEB_PROC_START_EPOCH = time.time()

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
    "compact_unsupported_cli": {"tr": "{name}: compact şu an sadece claude CLI için destekleniyor",
                                 "en": "{name}: compact is currently only supported for the claude CLI"},
    "compact_no_jsonl": {"tr": "{name}: sıkıştıracak bir konuşma bulunamadı (jsonl yok)",
                          "en": "{name}: no conversation found to compact (no jsonl)"},
    "invalid_theme": {"tr": "geçersiz tema — system/light/dark olmalı",
                       "en": "invalid theme — must be system/light/dark"},
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
    chosen_model = model.strip() or default_model_for(get_provider(chosen_cli))
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
    # bkz. _start()'taki aynı fix'in yorumu — cli değiştiyse eski info["model"]
    # yanlış provider'ın modeli olur, yeni cli'nin kendi varsayılanına düşülmeli.
    chosen_model = model.strip() or (info["model"] if chosen_cli == info["cli"] else default_model_for(get_provider(chosen_cli)))
    _append_tsv_line(ROSTER_TSV, [new_name, info["cwd"], chosen_model, chosen_cli])
    _append_tsv_line(MODELS_TSV, [new_name, chosen_model])
    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
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
    model = default_model_for(provider)

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
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
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

    failed_wids: list = []
    if not dry_run:
        failed_wids = apply_layout(plan, display=display)

    return {"ok": True, "total": plan.total, "skipped": plan.skipped,
            "assignments": assignments, "applied": not dry_run,
            "failed": len(failed_wids)}


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
    ok, config_code, config_detail = validate_config()

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
        "config_code": config_code,
        "config_detail": config_detail,
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
        "server_started_at": _WEB_PROC_START_EPOCH,
        # TODO L85 (2026-09-01, kullanıcı): "Handover textini o an hangi dil
        # seçili ise o dilde göster, oradan copy paste yaparız, ayrı cli
        # açmadan." _handover() zaten bu iki sabitten `lang`'a göre birini
        # seçip gönderiyor (yukarıda) — burada ikisini de dönüp seçimi
        # frontend'e bırakıyoruz (payload'ın geri kalanıyla aynı desen:
        # backend ham veri, React yerelleştirir).
        "handover_msg": {"tr": HANDOVER_MSG_DEFAULT, "en": HANDOVER_MSG_DEFAULT_EN},
        # TODO L73 (2026-09-02, kullanıcı kararı: sunucu-taraflı ~/.claude/claudeops/
        # settings.json — roster.tsv/models.tsv'yle aynı desen, tüm cihaz/tarayıcılardan
        # aynı görünür). Her /api/status poll'unda taze okunuyor — /api/settings'e yapılan
        # bir POST'un notify_status_changed() ile diğer açık tab'lara ANINDA yansıması için.
        "settings": load_settings(),
    }


_VALID_THEMES = ("system", "light", "dark")


def _save_settings(patch: dict, lang: str = "tr") -> dict:
    """`/api/settings` — kısmi patch alır (gönderilmeyen anahtarlar dokunulmadan
    kalır, bkz. `settings.save_settings`'in merge mantığı). Tek doğrulama: tema
    3 değerden biri olmalı (geri kalanı — handover_effort/default_model — geçersiz
    bir değer sadece "otomatiğe düş" anlamına gelir, sert bir hata değil)."""
    theme = patch.get("theme")
    if theme is not None and theme not in _VALID_THEMES:
        return _err(lang, "invalid_theme")
    new = save_settings(patch)
    return {"ok": True, "settings": new}


def _start(name: str, model: str = "", permission_mode: str = "", effort: str = "", fresh: bool = False,
           cli: str = "", lang: str = "tr") -> dict:
    fleet = _fleet_status()
    info = fleet.get(name)
    if not info or info["state"] != "active":
        return _err(lang, "not_active", name=name)
    chosen_cli = cli.strip() if cli.strip() in PROVIDERS else info["cli"]
    if _find_running(name, cli=chosen_cli):
        return _err(lang, "already_running", name=name)
    # info["model"] eski cli'nin modeli — kullanıcı cli'yi DEĞİŞTİRİP model alanını
    # boş bırakırsa (react: useState("") "kullan varsayılanı" anlamına gelir) burada
    # YANLIŞ cli'nin modeliyle spawn oluyordu (ör. codex'e geçip boş bırakınca "codex
    # --model claude-sonnet-5" gibi geçersiz bir çağrı — canlı kullanıcı raporu,
    # 2026-09-01). cli değişmediyse eski davranış (info["model"]) aynen korunur.
    fallback_model = info["model"] if chosen_cli == info["cli"] else default_model_for(get_provider(chosen_cli))
    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
            kind = spawn_session(
                name=name,
                cwd=info["cwd"],
                model=model.strip() or fallback_model,
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
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
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


def _term_chat(name: str, lang: str = "tr", mode: str = "last") -> dict:
    """Terminal popup'ının 'Sohbet' sekmesi: capture-pane/ANSI yerine provider'ın
    kendi transcript'inden (jsonl vb.) STRUCTURED metin döndürür — xterm.js'in
    mobilde scroll/render sorunlarını tamamen bypass eder. Desteklemeyen
    provider'lar (agy/shell, henüz) için supported:false döner, hata değil —
    panel bunu "henüz yok" olarak gösterir.

    `mode="last"` (varsayılan): son user+assistant çifti (eski davranış, aynen).
    `mode="full"` (2026-09-01, kullanıcı isteği): TÜM konuşma geçmişi, sırayla
    [{"role":"user"|"assistant","text":...}, ...] — `last_exchange`'le AYNI
    destekleniyor/desteklenmiyor sözleşmesi (`full_history` None → supported:False)."""
    s, err = _term_resolve(name, lang)
    if err:
        return err
    provider = get_provider(s.cli)
    if mode == "full":
        messages = provider.full_history(s.cwd, s.sid)
        if messages is None:
            return {"ok": True, "supported": False}
        return {"ok": True, "supported": True, "messages": messages}
    exchange = provider.last_exchange(s.cwd, s.sid)
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
            with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
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
            with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
                for s in procs:
                    kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS, name=s.name)
        except TimeoutError as e:
            return {"ok": False, "error": str(e)}
    _toggle_comment(MODELS_TSV, name, want_active=False)
    return {"ok": True}


HANDOVER_KILL_SETTLE_SECONDS = 6.0
HANDOVER_PROC_WAIT_SECONDS = 25.0

# guard_lock() ACQUIRE etmek için bekleme süresi — spawn+kill yapan HER handler'ın
# ortak sabiti (aşağıdaki 8 `with guard_lock(timeout=...)` çağrısının hepsi bunu
# kullanır). Kilidi TUTMA süresi (kill grace ~10s + HANDOVER_KILL_SETTLE_SECONDS 6s
# + spawn + HANDOVER_PROC_WAIT_SECONDS 25s = worst-case ~45-50s+, bkz. _handover)
# eskiden 5.0s'lik bir ACQUIRE timeout'uyla KIYASLANAMAYACAK kadar uzundu — bulk
# handover'da item 1 hâlâ kilidi tutarken item 2 sadece 5s bekleyip TimeoutError
# alıyordu (item 1 BAŞARIYLA bitmiş olsa bile, sadece HTTP yanıtı istemciye zamanında
# ulaşmamıştı) → "ilk item yapıldı, diğerleri hiç dokunulmadan hata verdi" (canlı
# bulundu, 2026-08-31, 4'lü bulk handover, main'de düzeltildi + buraya port edildi).
# Worst-case'in güvenle üstünde tek bir ortak değer — istemci taraf zaten her item
# için ayrı ayrı ilerleme/hata gösteriyor, sırada bekleyen bir item için birkaç
# saniye yerine biraz daha uzun beklemek zararsız.
GUARD_LOCK_ACQUIRE_TIMEOUT = 60.0


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
        cwd, model = procs[0].cwd, (procs[0].model or default_model_for(provider))
    message = HANDOVER_MSG_DEFAULT_EN if lang == "en" else HANDOVER_MSG_DEFAULT
    # TODO L9 instrumentation (2026-08-31 bulk-handover investigation: the
    # guard_lock-acquire-timeout fix above was found+applied, but a residual
    # symptom — two BrokenPipeErrors not explained by that timing — was
    # never root-caused; main's own diag_log instrumentation for this never
    # made it into this tree before the PAGE_HTML panel it was written
    # against was retired). Best-effort (diag_log never raises) — if bulk
    # handover misbehaves again, `diag.log`/the Tanı tab's log panel should
    # show exactly which phase a given name got stuck in.
    diag_log("handover_start", name=name, cli=chosen_cli)
    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
            diag_log("handover_lock_acquired", name=name)
            kill_results = [kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS, name=s.name) for s in procs]
            if HANDOVER_KILL_SETTLE_SECONDS > 0 and any(r != "already_dead" for r in kill_results):
                time.sleep(HANDOVER_KILL_SETTLE_SECONDS)
            diag_log("handover_killed", name=name, kill_results=kill_results)
            kind = spawn_session(
                name=name,
                cwd=cwd,
                model=model,
                display=detect_display(),
                permission_mode=provider.permission_modes()[0],
                effort=default_handover_effort(provider),
                force_new=False,
                prompt=message,
                cli=chosen_cli,
            )
            diag_log("handover_spawned", name=name, kind=kind)
            reopened = _wait_stable(name, timeout=HANDOVER_PROC_WAIT_SECONDS)
    except TimeoutError as e:
        diag_log("handover_lock_timeout", name=name, error=str(e))
        return {"ok": False, "error": str(e)}
    if not reopened:
        diag_log("handover_reopen_failed", name=name, kind=kind)
        return _err(lang, "handover_reopen_failed", name=name, kind=kind)
    diag_log("handover_done", name=name, kind=kind)
    return {"ok": True, "kind": kind}


# bash cmd_compact'ın 300s'i yerine daha kısa — bu adım guard_lock DIŞINDA
# çalışıyor olsa da sınırsız uzayıp panelin "bitti" haberini sonsuza kadar
# geciktirmesin.
COMPACT_TIMEOUT_SECONDS = 180.0


def _compact(name: str, lang: str = "tr") -> dict:
    """Kill + headless `-p '/compact'` + resume — 2026-09-02, kullanıcı isteği
    ("terminal de ve listeden seçip onlara compact gonderme iyi olur").

    Bash'in `cmd_compact`'ıyla AYNI mekanizma (headless `-p '/compact'`), YENİDEN
    İCAT EDİLMEDİ: `_handover()`'daki gibi bir interaktif `--resume ... 'PROMPT'`
    ile `/compact`'ı İLK MESAJ olarak göndermek DENENMEDİ — TUI'nin CLI argümanı
    olarak geçirilen bir ilk mesajı slash-command olarak mı yoksa düz metin
    olarak mı işlediği doğrulanmadı; bash'in headless `-p` yaklaşımı ise KANITLI
    çalışıyor (canlı, üretimde). Headless adımın LIVE session'la aynı sid üzerinde
    eşzamanlı çalışmaması için önce kill ŞART ([[claude-2183-conversation-truncation]]
    sınıfı risk).

    guard_lock kill VE respawn için AYRI AYRI KISA pencerelerde tutuluyor —
    headless compact (bash'te olduğu gibi) dakikalarca sürebilir; bunu TEK bir
    guard_lock penceresinin içine almak `GUARD_LOCK_ACQUIRE_TIMEOUT=60.0`
    varsayımıyla ÇAKIŞIRDI (diğer TÜM panel aksiyonları — start/stop/başka bir
    compact/handover — o süre boyunca kilitlenirdi). Guard cron zaten KASITLI
    kapalı (Manuel fleet kontrolü kararı) — iki ayrı pencere arasında guard'ın
    araya girip dup açması bugün pratikte imkansız; guard cron geri açılırsa bu
    varsayım yeniden değerlendirilmeli.

    Sadece `claude` provider'ı destekliyor (`/compact` claude-cli'a özgü bir
    slash-command; `resolve_resume_id`'nin claude-özel `find_latest_jsonl`'a
    dayanması da zaten aynı sınırlamayı taşıyor, [[handover.py's _spawn_faz1]]
    ile aynı bilinçli kapsam daraltması).
    """
    procs = _find_running(name)
    if not procs:
        return _err(lang, "not_running", name=name)
    fleet = _fleet_status()
    info = fleet.get(name)
    chosen_cli = info["cli"] if info else procs[0].cli
    if chosen_cli != "claude":
        return _err(lang, "compact_unsupported_cli", name=name)
    provider = get_provider(chosen_cli)
    if info:
        cwd, model = info["cwd"], info["model"]
    else:
        cwd, model = procs[0].cwd, (procs[0].model or default_model_for(provider))

    diag_log("compact_start", name=name)
    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
            kill_results = [kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS, name=s.name) for s in procs]
            if HANDOVER_KILL_SETTLE_SECONDS > 0 and any(r != "already_dead" for r in kill_results):
                time.sleep(HANDOVER_KILL_SETTLE_SECONDS)
    except TimeoutError as e:
        diag_log("compact_lock_timeout", name=name, phase="kill", error=str(e))
        return {"ok": False, "error": str(e)}
    diag_log("compact_killed", name=name)

    resume_id = provider.resolve_resume_id(cwd)
    if resume_id is None:
        diag_log("compact_no_jsonl", name=name)
        return _err(lang, "compact_no_jsonl", name=name)
    binary = shutil.which("claude") or "claude"
    try:
        subprocess.run(
            [binary, "--resume", resume_id, "-p", "/compact"],
            cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=COMPACT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        # devam et — respawn yine de denenir; compact yarıda kalmış olabilir
        # ama session'ı tamamen kayıp bırakmaktan iyidir.
        diag_log("compact_headless_timeout", name=name)
    except Exception as e:
        diag_log("compact_headless_error", name=name, error=str(e))
    else:
        diag_log("compact_headless_done", name=name)

    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
            kind = spawn_session(
                name=name,
                cwd=cwd,
                model=model,
                display=detect_display(),
                permission_mode=provider.permission_modes()[0],
                effort=default_handover_effort(provider),
                force_new=False,
                prompt=None,
                cli=chosen_cli,
            )
            reopened = _wait_stable(name, timeout=HANDOVER_PROC_WAIT_SECONDS)
    except TimeoutError as e:
        diag_log("compact_lock_timeout", name=name, phase="respawn", error=str(e))
        return {"ok": False, "error": str(e)}
    if not reopened:
        diag_log("compact_reopen_failed", name=name, kind=kind)
        return _err(lang, "handover_reopen_failed", name=name, kind=kind)
    diag_log("compact_done", name=name, kind=kind)
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
    # Sadece GERÇEK bir rename'de (yeni_ad ≠ eski_ad) formatı zorla — isim
    # değişmiyorsa bu zaten çalışan bir proc'un VAROLAN kimliği (adopt formu
    # "yeni ad" alanını old_name ile ön-dolduruyor, kullanıcı dokunmadan
    # "Devral"a basınca new_name==old_name gelir). O ismi kullanıcı seçmedi —
    # süreç zaten öyle başlamış (ör. claudeops DIŞINDA elle `-n wireguard-mayaos-61`
    # ile) — reddetmek "devral" özelliğini tam da var olma amacı olan durumda
    # (isim claudeops'un kendi kuralına uymuyor) kullanılmaz kılardı. Canlı bulundu
    # 2026-09-01: "wireguard-mayaos-61" adopt'ta invalid_name ile reddediliyordu.
    if new_name != old_name and not _NAME_VALID_RE.match(new_name):
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
    chosen_model = model.strip() or procs[0].model or default_model_for(provider)
    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
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


UNAUTHORIZED_HTML = (
    b"<!doctype html><meta charset=utf-8><body style='font:14px monospace;padding:2rem'>"
    b"401 &mdash; token eksik/yanlis. URL'ye <code>?token=...</code> ekleyin.<br>"
    b"401 &mdash; token missing/invalid. Add <code>?token=...</code> to the URL.</body>"
)


class _Handler(BaseHTTPRequestHandler):
    server_version = "claudeops-web/1"
    # HTTP/1.0 (stdlib varsayılanı) her istekte yeni TCP+TLS-yok-ama-yine-de
    # 3-way-handshake demekti — 200ms'lik terminal poll'u (useTerminalOutput)
    # için ölçülebilir bir maliyet. 1.1 = keep-alive varsayılan AÇIK; bunun
    # güvenli olması için HER yanıtın doğru `Content-Length` taşıması ŞART
    # (aksi halde client "yanıt nerede bitiyor" bilemez, hang eder) — `_json`/
    # `_serve_static`/`_unauthorized` zaten hepsi elle `Content-Length` set
    # ediyor (doğrulandı, değiştirilmedi). `/ws` şubesi
    # (web_ws.handle_ws) kendi soketini WS'e yükseltip `close_connection =
    # True` set ediyor — keep-alive'ın WS handshake'ini bir sonraki "normal"
    # HTTP isteği sanıp karıştırma riski YOK.
    protocol_version = "HTTP/1.1"
    token = ""  # run() içinde atanır

    def log_message(self, fmt, *a):
        pass  # stdout'u kirletme — sessiz

    def _authorized(self) -> bool:
        qs = parse_qs(urlparse(self.path).query)
        given = (qs.get("token") or [""])[0]
        return secrets.compare_digest(given, self.token)

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            # TODO L9 residual concern (bulk-handover: "sadece ilki başarılı
            # oluyor, kalanı hataya düşüyor" — two BrokenPipeErrors seen live
            # 2026-08-31 that the guard_lock-timeout fix alone didn't
            # explain): if THIS connection died mid-write (tab closed /
            # navigated away / bulk-loop's fetch already moved on) after the
            # underlying action already succeeded server-side, this used to
            # propagate straight out of do_POST — aborting BEFORE
            # `_json_notify()`'s `notify_status_changed()` call below runs,
            # so no other open tab got the WS push either even though fleet
            # state was fine. Swallow + log instead of crashing the request:
            # the caller that made THIS specific call never sees a response
            # either way, but every other caller of `_json_notify` still
            # gets to run its notify. Best-effort (diag_log never raises).
            diag_log("response_write_failed", path=urlparse(self.path).path, error=str(e))

    def _json_notify(self, result: dict, status=200):
        """`_json()` + mutasyon `ok: True` dönmüşse `web_ws.notify_status_changed()`.
        Plan: notify SADECE do_POST'tan (aksiyon fonksiyonlarının İÇİNDEN
        değil) ve SADECE listelenen route'lardan (start/stop/retire/close/
        handover/compact/adopt/reactivate/new-chat/register/open-window/
        settings/diag-restart-gt) — bu route'ların do_POST dispatch'i bu
        helper'ı kullanır, geri kalanı (layout/term-input/term-key/
        diag-spawn-test/diag-ask gibi) düz `_json()` kullanmaya devam eder."""
        self._json(result, status=status)
        if result.get("ok"):
            web_ws.notify_status_changed()

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
        # Vite'ın content-hash'li dosyaları (`/assets/*`) SONSUZA KADAR güvenle
        # cache'lenebilir (içerik değişirse dosya ADI da değişir) — ama
        # `index.html` (hash'siz, sabit ad) ASLA cache'lenmemeli: aksi halde bir
        # redeploy sonrası tarayıcı önbellekteki ESKİ `index.html`'i sunmaya
        # devam eder, o index.html'in referans verdiği (yeni build'de artık
        # SİLİNMİŞ, farklı hash'li dosyayla değişmiş) eski JS/CSS 404 döner ve
        # sayfa hiç açılmaz — önceden HİÇBİR Cache-Control header'ı yoktu, yani
        # tarayıcının kendi (validator'sız, öngörülemeyen) heuristik cache
        # davranışına kalmıştı. Canlı bulundu (2026-09-02, kullanıcı: "ana
        # sayfa açılırken bir hata var, tüm sayfa gizleniyor") — bu oturumdaki
        # ardışık iki restart arasında yakalanan bir sekmede tam bu senaryo.
        if fpath.is_relative_to(DIST_DIR / "assets"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
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
            # (ThreadingHTTPServer: connection-başına-thread) — bu thread
            # aynı zamanda bağlantının WRITER'ı olur (web_ws.py'nin kendi
            # docstring'inde detay). _status_payload burada geçiliyor ki
            # web_ws.py web.py'nin business logic'ine geri-import ETMESİN
            # (plan: "diff additive kalsın").
            web_ws.handle_ws(self, _status_payload)
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
            mode = "full" if (qs.get("mode") or [""])[0] == "full" else "last"
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            self._json(_term_chat(name, lang=lang, mode=mode))
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
                         "/api/handover", "/api/compact", "/api/adopt", "/api/term/input", "/api/term/key",
                         "/api/term/open-window", "/api/settings",
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
            self._json_notify(_diag_restart_gt(lang=lang))
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

        if path == "/api/settings":
            patch = {k: v for k, v in data.items() if k != "lang"}
            self._json_notify(_save_settings(patch, lang=lang))
            return

        if path == "/api/new-chat":
            base = str(data.get("base", "")).strip()
            if not base:
                self._json(_err(lang, "base_required"), status=400)
                return
            self._json_notify(_new_chat(
                base,
                model=str(data.get("model", "")),
                permission_mode=str(data.get("permission_mode", "")),
                effort=str(data.get("effort", "")),
                cli=str(data.get("cli", "")),
                lang=lang,
            ))
            return

        if path == "/api/register":
            self._json_notify(_register_project(
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
            self._json_notify(_adopt(
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
            self._json_notify(_open_window(name, lang=lang))
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
        elif path == "/api/compact":
            result = _compact(name, lang=lang)
        else:
            result = _reactivate_and_start(name, lang=lang)
        self._json_notify(result)


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
    web_ws.start_broadcaster(_status_payload)  # tek broadcaster daemon thread'i, süreç ömrü boyunca bir kez
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
