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

TEK-KULLANICI ARAÇ (TOBEDECIDED#23, 2026-09-10 karar: kapsam GENEL — sadece
claude değil, hangi provider olursa olsun): token bir "paylaşım" mekanizması
DEĞİL — onu bilen HERKES panele/`/v1/*`'e girip session'larını (dolayısıyla
arkalarındaki provider hesabını) tam sürebilir. Çoğu provider'ın kullanım
şartları tek-kullanıcı hesabın fiilen çok-kullanıcılı bir servise
dönüşmesine izin vermeyebilir — token'ı KİMSEYLE paylaşma, tünel URL'ini
public duyurma (bkz. `run()`'ın startup uyarısı + README'nin tepesindeki not).

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
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Dict, Optional
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

import psutil

from ..config import validate_config
from ..diaglog import diag_log, diag_log_tail, diag_log_recent_fallback_count
from ..discovery import find_sessions, duplicates
from ..guard import guard_lock
from ..handover import HANDOVER_MSG_DEFAULT, HANDOVER_MSG_DEFAULT_EN
from ..hosts import LOCAL_HOST_NAME, save_host, remove_host, list_hosts_public
from ..kill import kill_session, kill_session_and_parent, KILL_GRACE_SECONDS
from ..needs_ho import needs_ho
from .. import files as files_mod
from .. import instances as inst_mod
from .. import remote_desktop
from ..session import Session
from ..paths import CLAUDEOPS_DIR, MODELS_TSV, REPO_DIR, ROSTER_TSV
from ..settings import default_model_for, load_settings, save_settings
from ..snapshot import save_snapshot, load_snapshot
from ..spawn import spawn_session, detect_display, find_latest_jsonl, open_window
from ..providers.claude_provider import jsonl_path_for
from ..providers import PROVIDERS, DEFAULT_CLI, get_provider
from .. import turns
from ..tmux_backend import (
    is_tmux_backed, tmux_has_session, tmux_capture, tmux_client_count, tmux_send_keys, tmux_send_raw,
    tmux_send_special_key, tmux_pane_size, pane_is_masked_input, ALLOWED_SPECIAL_KEYS, strip_ansi,
)
from .web_static import DIST_DIR, resolve_static_path
from . import web_grpc
from . import web_hosts
from . import web_orch
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
    "newchat_start_failed": {"tr": "{new_name}: instance olarak kaydedildi ama başlatılamadı "
                                    "(gnome-terminal/DISPLAY sorunu olabilir) — Geçmiş sekmesinden 'Devam ettir' ile "
                                    "tekrar deneyin — kind={kind}",
                              "en": "{new_name}: recorded as an instance but failed to start "
                                    "(could be a gnome-terminal/DISPLAY issue) — retry with 'Resume' in the History "
                                    "tab — kind={kind}"},
    "unknown_instance": {"tr": "{name}: instance kaydında yok", "en": "{name}: not in the instance registry"},
    "forget_running": {"tr": "{name}: çalışıyor — önce durdurun, sonra unutun",
                        "en": "{name}: running — stop it first, then forget it"},
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
    "ambiguous_name": {"tr": "{name}: birden fazla çalışan session bu isme indirgeniyor ({candidates}) — "
                              "hangisi hedeflenecek belirsiz, tam ismini kullanın",
                        "en": "{name}: more than one running session reduces to this name ({candidates}) — "
                              "ambiguous which one to target, use the exact name"},
    "unknown_host": {"tr": "{name}: kayıtlı bir uzak host değil", "en": "{name}: not a registered remote host"},
    "undefined": {"tr": "{name}: tanımsız", "en": "{name}: undefined"},
    "already_retired": {"tr": "{name}: zaten emekli", "en": "{name}: already retired"},
    "already_closed": {"tr": "{name}: zaten devre dışı", "en": "{name}: already disabled"},
    "retired_needs_reactivate": {"tr": "{name}: emekli — önce 'tekrar işe al', sonra kapatın",
                                  "en": "{name}: retired — reactivate first, then close"},
    "handover_reopen_failed": {"tr": "{name}: kapatıldı ama yeniden açılamadı "
                                      "(gnome-terminal/DISPLAY/kilit ekranı sorunu olabilir) — kind={kind}",
                                "en": "{name}: closed but couldn't reopen "
                                      "(could be a gnome-terminal/DISPLAY issue) — kind={kind}"},
    "name_in_use": {"tr": "{new_name}: zaten kullanılıyor (roster'da, instance kaydında ya da çalışıyor)",
                     "en": "{new_name}: already in use (in roster, in the instance registry, or currently running)"},
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
    "window_already_attached": {"tr": "{name}: zaten bağlı {count} pencere var — ikincisi yeni bir session AÇMAZ, "
                                       "aynı ekranı aynalar (tmux pane'i istemcilere göre yeniden boyutlandırır). "
                                       "Pencereyi bulamıyorsanız önce masaüstlerine bakın; yine de istiyorsanız "
                                       "istek `force` ile gönderilmeli",
                                "en": "{name}: {count} window(s) already attached — a second one does NOT open a new "
                                      "session, it mirrors the same screen (and tmux resizes the pane to fit the "
                                      "clients). Check your other desktops first; send the request with `force` if "
                                      "you really want another one"},
    "term_raw_too_long": {"tr": "canlı yazma: tek seferde en fazla {limit} karakter gönderilebilir",
                           "en": "live typing: at most {limit} characters can be sent at once"},
    "mode_cycle_unsupported": {"tr": "{name}: {cli} CLI'ında canlı izin-modu değiştirme yok "
                                      "(Shift+Tab döngüsü sadece claude'da tanımlı)",
                               "en": "{name}: the {cli} CLI has no live permission-mode switching "
                                     "(the Shift+Tab cycle is only defined for claude)"},
    "mode_not_cyclable": {"tr": "{mode}: Shift+Tab döngüsüyle hedeflenemez (canlıyken sadece şunlar: {modes}) — "
                                 "diğer modlar için session'ı o modla yeniden başlatın",
                          "en": "{mode}: not reachable via the Shift+Tab cycle (live-changeable ones: {modes}) — "
                                "for other modes, restart the session with that mode"},
    "mode_cycle_unreachable": {"tr": "{name}: {mode} bu session'ın Shift+Tab döngüsünde yok — tam tur atıldı, "
                                      "başlangıç moduna ({current}) geri dönüldü, hiçbir şey değişmedi",
                               "en": "{name}: {mode} isn't in this session's Shift+Tab cycle — went a full loop and "
                                     "came back to the starting mode ({current}), nothing changed"},
    "mode_cycle_failed": {"tr": "{name}: {mode} moduna ulaşılamadı (şu an: {current}) — CLI'nin döngüsü bu "
                                 "session için farklı olabilir, terminalden elle Shift+Tab deneyin",
                           "en": "{name}: couldn't reach {mode} mode (currently: {current}) — this session's "
                                 "cycle may differ, try Shift+Tab manually from the terminal"},
    "gt_not_found": {"tr": "gnome-terminal-server çalışmıyor (zaten kapalı) — bir sonraki spawn otomatik açacak",
                      "en": "gnome-terminal-server isn't running (already down) — the next spawn will start it automatically"},
    "compact_unsupported_cli": {"tr": "{name}: compact şu an sadece claude CLI için destekleniyor",
                                 "en": "{name}: compact is currently only supported for the claude CLI"},
    "compact_no_jsonl": {"tr": "{name}: sıkıştıracak bir konuşma bulunamadı (jsonl yok)",
                          "en": "{name}: no conversation found to compact (no jsonl)"},
    "compact_send_failed": {"tr": "{name}: compact komutu gönderilemedi (tmux session gitmiş olabilir)",
                             "en": "{name}: failed to send the compact command (tmux session may be gone)"},
    "handover_send_failed": {"tr": "{name}: wrap-up mesajı gönderilemedi (tmux session gitmiş olabilir)",
                              "en": "{name}: failed to send the wrap-up message (tmux session may be gone)"},
    "compact_timeout": {"tr": "{name}: compact {timeout:.0f}s içinde tamamlanmadı — session meşgul/kuyrukta "
                               "kalmış olabilir, birazdan kendiliğinden bitebilir, terminalden kontrol edin",
                         "en": "{name}: compact didn't finish within {timeout:.0f}s — the session may still be "
                               "busy/queued and finish on its own shortly, check its terminal"},
    "invalid_theme": {"tr": "geçersiz tema — system/light/dark olmalı",
                       "en": "invalid theme — must be system/light/dark"},
    "path_required": {"tr": "path gerekli", "en": "path is required"},
    "files_no_roots": {"tr": "{name}: bu session için erişilebilir bir klasör bulunamadı",
                        "en": "{name}: no accessible folder found for this session"},
    "files_forbidden": {"tr": "{name}: bu yol izin verilen klasörlerin dışında",
                         "en": "{name}: that path is outside the allowed folders"},
    "files_not_found": {"tr": "{name}: yol bulunamadı", "en": "{name}: path not found"},
    "files_too_large": {"tr": "{name}: dosya indirme sınırını aşıyor (>{limit_mb:.0f}MB)",
                         "en": "{name}: file exceeds the download size limit (>{limit_mb:.0f}MB)"},
    "vscode_not_found": {"tr": "VS Code CLI (`code`) bu makinede bulunamadı",
                          "en": "VS Code CLI (`code`) not found on this machine"},
    "not_registered": {"tr": "{name}: roster'da kayıtlı değil", "en": "{name}: not in the roster"},
    "edit_while_running": {"tr": "{name}: çalışırken düzenlenemez — önce durdurun, sonra tekrar deneyin",
                            "en": "{name}: can't edit while running — stop it first, then try again"},
    "edit_warn_dir_not_found": {"tr": "'{cwd}' şu an mevcut değil — session bu klasörde başlatılmaya çalışıldığında başarısız olur",
                                 "en": "'{cwd}' doesn't exist yet — starting the session will fail until it does"},
    "edit_warn_orphans_history": {"tr": "eski klasörde ('{cwd}') gerçek bir konuşma geçmişi var — klasörü değiştirmek onu TAŞIMAZ, "
                                         "yeni klasörde sıfırdan başlar ve eski geçmiş bu proje adından bir daha erişilemez olur",
                                   "en": "the old folder ('{cwd}') has real conversation history — changing the folder does NOT move it, "
                                         "the new folder starts fresh and the old history becomes unreachable from this project name"},
    "no_snapshot": {"tr": "kaydedilmiş bir snapshot yok — önce 'Snapshot kaydet'e basın",
                     "en": "no saved snapshot yet — click 'Save snapshot' first"},
}


def _err(lang: str, key: str, **kwargs) -> dict:
    tpl = ERR[key]["en" if lang == "en" else "tr"]
    return {"ok": False, "error": tpl.format(**kwargs)}


def _msg(lang: str, key: str, **kwargs) -> str:
    """`_err()` ile AYNI şablon katalogunu (ERR) kullanan, ama `ok:False`
    sarmalamayan düz metin — engellemeyen/bilgilendirici uyarılar için
    (ör. `_edit_project()`'in `warnings` listesi)."""
    tpl = ERR[key]["en" if lang == "en" else "tr"]
    return tpl.format(**kwargs)


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
    """Tam isim VEYA base eşleşmesiyle çalışan session'ları bul — sadece salt-okunur
    metadata çözümlemesi için (`_files_resolve`: aynı base'i paylaşanların cwd/cli'si
    aynı). Yıkıcı/tekil-hedefli çağrılar `_find_running_for_action` kullanmalı;
    "zaten çalışıyor"/"açıldı mı" soruları ise TAM isme bakar (`_start`, `_wait_stable`).
    """
    return [s for s in find_sessions(measure_cpu=False) if s.name == name or s.base == name]


def _find_running_for_action(name: str, cli: Optional[str] = None) -> tuple:
    """`_find_running`'in TEKİL-HEDEFLİ/yıkıcı çağrılar (stop/retire/close/
    handover/compact/adopt/terminal-routing) için güvenli hâli.

    KRİTİK CANLI OLAY (2026-09-14): `_find_running`'in base-fallback'i
    (yukarıdaki docstring — `hc58`+`hc` gibi geçiş durumlarında BİLEREK var)
    bu çağırıcılarda YANLIŞ araç oldu — bir session'ı ("cops") kapatmak, base'i
    AYNI "cops"a indirgenen BAMBAŞKA canlı bir session'ı ("cops20260914_1",
    tarih+çakışma suffix'i, o an açık bir konuşmanın kendisi) da öldürdü.
    Coexistence-suffix (aynı base'i BİLEREK aynı anda YAŞATMAK için var) ile
    base-collapsing (aynı base'i AYNI proje SAYMAK için var) burada doğrudan
    çelişiyordu — ikisi birlikte yaşarken birini hedeflemek ikisini de hedef
    seçiyordu.

    Fark: ÖNCE tam-isim eşleşmesi denenir (varsa TEK doğru cevap budur, base'e
    hiç bakılmaz). Tam eşleşme yoksa base'e düşülür — AMA birden fazla canlı
    proc AYNI base'e düşüyorsa (asıl belirsizlik) sessizce hepsini/birini
    seçmek yerine "ambiguous" döner, çağıran kullanıcıya tam isim sorar.

    Returns: (kind, sessions) — kind: "exact" | "unique_base" | "ambiguous" | "none".
    "ambiguous" hariç HER zaman `sessions` güvenle hedeflenebilir (tam liste,
    tek bir proje/başka bir session'ı KARIŞTIRMADAN)."""
    sessions = find_sessions(measure_cpu=False)
    if cli:
        sessions = [s for s in sessions if s.cli == cli]
    exact = [s for s in sessions if s.name == name]
    if exact:
        return "exact", exact
    base_matches = [s for s in sessions if s.base == name]
    if len(base_matches) > 1:
        return "ambiguous", base_matches
    if base_matches:
        return "unique_base", base_matches
    return "none", []


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
        # Tam isim: base'e bakılsaydı blueprint açılırken çalışan kendi instance'ı
        # (cops20260918) "cops açıldı" sayılırdı.
        if any(s.name == name for s in find_sessions(measure_cpu=False)):
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
        # roster.tsv'ye elle/register edilirken trailing slash'lı girilmiş olabilir
        # (`.../XX_rust_unified_cli_design/`); canlı bir instance'ın cwd'si ise
        # `find_sessions()`'ın `os.readlink(/proc/pid/cwd)`'inden gelir ve trailing
        # slash HİÇBİR ZAMAN taşımaz. Aynı gerçek dizin iki FARKLI string olarak
        # panele gidiyordu — Running tab'ın `groupByCwd`'i (webui, saf string eşitliği)
        # blueprint'in kendi satırını instance'larından AYRI bir "klasör" grubuna
        # düşürüyordu (canlı bulundu, 2026-09-19: "rustagentppr" ve
        # "rustagentppr20260919"/"_1" aynı dizinde ama Running'de iki ayrı grup
        # gibi görünüyordu). Tek kaynakta normalize etmek (`os.path.normpath`,
        # dosyaya DOKUNMUYOR, sadece string) bu fonksiyonun HER çağıranını düzeltir.
        if cwd:
            cwd = os.path.normpath(cwd)
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
    names |= set(inst_mod.load_instances())
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


def _atomic_write_text(path: str, content: str) -> None:
    """`roster.tsv`/`models.tsv` gibi kritik config dosyalarını YARIM/bozuk
    yazımdan korur (VERİ KAYBI RİSKİ, 2026-09-14 fix — bkz. TODO.md): eskiden
    her çağıran kendi `open(path, "w")`'unu doğrudan yapıyordu, bu TRUNCATE-
    ÖNCE-YAZ deseni `ThreadingHTTPServer` altında eşzamanlı iki istek ya da
    yazma ortasında kesilen bir process karşısında dosyayı bozuk/yarım
    bırakabilirdi. Geçici dosyaya aynı dizinde yazıp `os.replace` ile atomik
    taşır (POSIX'te `rename(2)` — ya eski içerik ya yeni içerik görülür,
    ARADA hiçbir okuyucu yarım dosya görmez)."""
    d = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".tsv")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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
    _atomic_write_text(path, content)


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
    if inst_mod.get_instance(name) is not None:
        return _err(lang, "name_in_use", new_name=name)
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


def _edit_project(name: str, new_name: str, new_cwd: str, new_model: str = "",
                   new_cli: str = "", lang: str = "tr") -> dict:
    """Kayıtlı (DURMUŞ) bir projenin isim/klasör/model'ini roster.tsv+models.tsv'de
    YERİNDE değiştirir (aktif/kapalı/emekli `#` durumu KORUNUR, `_replace_tsv_line`).

    Kullanıcı kararı (2026-09-08): proje ÇALIŞIYORSA reddedilir — canlı process'in
    cwd/isim'i kill+respawn olmadan değişemez, önce durdursun. İsim için
    `_register_project` ile AYNI yapısal kontroller (geçerlilik + çakışma —
    uniqueness sistem genelinde `(host,name)` kimliğinin temeli, esnetilemez).
    Klasör için YAPISAL bir kısıt YOK — "ne isterse yapsın" — sadece olmayan
    klasör ya da eski klasördeki artık erişilemez hale gelecek konuşma geçmişi
    (provider-agnostic `resolve_resume_id()` ile tespit) `warnings` listesinde
    dönüyor, kaydı ENGELLEMİYOR."""
    name = name.strip()
    roster_rows = {r["name"]: r for r in _read_tsv_raw(ROSTER_TSV) if r["name"] != "name"}
    old = roster_rows.get(name)
    if old is None:
        return _err(lang, "not_registered", name=name)
    for s in find_sessions(measure_cpu=False):
        if name in (s.name, s.base):
            return _err(lang, "edit_while_running", name=name)

    new_name = new_name.strip()
    if not _NAME_VALID_RE.match(new_name):
        return _err(lang, "invalid_name")
    if new_name != name:
        if new_name in roster_rows:
            return _err(lang, "already_registered", name=new_name)
        if inst_mod.get_instance(new_name) is not None:
            return _err(lang, "name_in_use", new_name=new_name)
        for s in find_sessions(measure_cpu=False):
            if new_name in (s.name, s.base):
                return _err(lang, "conflicts_running", name=new_name, other=s.name)

    new_cwd = os.path.expanduser(new_cwd.strip())
    if not new_cwd:
        return _err(lang, "dir_not_found", cwd="(boş)" if lang != "en" else "(empty)")
    if "\t" in new_cwd or "\n" in new_cwd:
        return _err(lang, "cwd_bad_chars")

    old_cwd = old["rest"][0] if old["rest"] else ""
    old_cli = old["rest"][2] if len(old["rest"]) >= 3 and old["rest"][2] in PROVIDERS else DEFAULT_CLI
    chosen_cli = new_cli.strip() if new_cli.strip() in PROVIDERS else old_cli
    chosen_model = new_model.strip() or default_model_for(get_provider(chosen_cli))

    warnings = []
    if not os.path.isdir(new_cwd):
        warnings.append(_msg(lang, "edit_warn_dir_not_found", cwd=new_cwd))
    if new_cwd != old_cwd:
        try:
            has_history = bool(get_provider(old_cli).resolve_resume_id(old_cwd))
        except Exception:
            has_history = False
        if has_history:
            warnings.append(_msg(lang, "edit_warn_orphans_history", cwd=old_cwd))

    _replace_tsv_line(ROSTER_TSV, name, [new_name, new_cwd, chosen_model, chosen_cli])
    _replace_tsv_line(MODELS_TSV, name, [new_name, chosen_model])
    if new_name != name:
        inst_mod.rename_blueprint(name, new_name)
    return {"ok": True, "name": new_name, "warnings": warnings}


def _blueprint_cwds(fleet: dict) -> Dict[str, str]:
    """Blueprint adayı roster satırları (tarihli/türev isimli eski instance satırları hariç)."""
    return {n: i["cwd"] for n, i in fleet.items() if not inst_mod.DERIVED_NAME_RE.match(n)}


def _new_chat_source(name: str, fleet: dict) -> Optional[tuple]:
    """(blueprint|None, önek, cwd, cli, model) — yeni sohbetin neyden türeyeceği.

    Bir instance satırından tıklanırsa onun blueprint'inden türer; tarihi olduğu gibi
    soneke eklemek kendi üstüne katlanırdı ("saseppr20260827_120260827", 2026-08-27)."""
    rec = None if name in fleet else inst_mod.get_instance(name)
    if rec is not None:
        bp = rec.get("blueprint")
        info = fleet.get(bp) if bp else None
        if info:
            return bp, bp, info["cwd"], info["cli"], info["model"]
        return bp, Session(name=name, pid=0).base or name, rec["cwd"], rec["cli"], rec["model"]
    info = fleet.get(name)
    if info is None:
        return None
    if inst_mod.DERIVED_NAME_RE.match(name):
        bp = inst_mod.infer_blueprint(name, info["cwd"], _blueprint_cwds(fleet))
        if bp:
            b = fleet[bp]
            return bp, bp, b["cwd"], b["cli"], b["model"]
        return None, Session(name=name, pid=0).base or name, info["cwd"], info["cli"], info["model"]
    return name, name, info["cwd"], info["cli"], info["model"]


def _new_chat(base: str, model: str = "", permission_mode: str = "", effort: str = "",
              cli: str = "", lang: str = "tr") -> dict:
    """`base`'in blueprint'inden YENİ, otomatik-isimli (tarih[+_N]) bir instance başlat.

    Var olan session'lara DOKUNMAZ. Roster'a satır YAZMAZ — instance kaydına girer,
    durdurulunca Kayıtlı'ya değil Geçmiş'e düşer."""
    src = _new_chat_source(base, _fleet_status())
    if src is None:
        return _err(lang, "base_not_in_roster", base=base)
    blueprint, prefix, cwd, src_cli, src_model = src
    new_name = _generate_new_chat_name(prefix)
    chosen_cli = cli.strip() if cli.strip() in PROVIDERS else src_cli
    # bkz. _start()'taki aynı fix'in yorumu — cli değiştiyse eski model
    # yanlış provider'ın modeli olur, yeni cli'nin kendi varsayılanına düşülmeli.
    chosen_model = model.strip() or (src_model if chosen_cli == src_cli else default_model_for(get_provider(chosen_cli)))
    chosen_mode = permission_mode.strip() or "auto"
    chosen_effort = effort.strip() or "max"
    inst_mod.record_instance(new_name, blueprint=blueprint, cwd=cwd, cli=chosen_cli, model=chosen_model,
                             permission_mode=chosen_mode, effort=chosen_effort, origin="new_chat")
    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
            kind = spawn_session(
                name=new_name,
                cwd=cwd,
                model=chosen_model,
                display=detect_display(),
                permission_mode=chosen_mode,
                effort=chosen_effort,
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
        _atomic_write_text(path, "".join(lines))
    return found


def _replace_tsv_line(path: str, name: str, fields: list) -> bool:
    """`_toggle_comment()` ile AYNI find-by-first-field deseni, ama `#` durumunu
    değiştirmek yerine satırın ALANLARINI `fields` ile değiştirir (aktif/kapalı/emekli
    durumu KORUNUR). `fields[0]` eskisinden FARKLI olabilir — bu, tek bir çağrıda
    rename'i de kapsar (satır hâlâ ESKİ `name`'e göre bulunur, sadece içeriği değişir)."""
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
            new_core = "\t".join(fields)
            lines[i] = ("#" + new_core if is_commented else new_core) + "\n"
            found = True
            break
    if found:
        _atomic_write_text(path, "".join(lines))
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

    2026-09-14 canlı bug: `awk '{print $1; exit}'` `loginctl list-sessions`'ın
    İLK SATIRINI (herhangi bir kullanıcı/seat filtresi olmadan) alıyordu — bu
    makine ÇOK-KULLANICILI (ikinci bir hesap, `ahmet`, ayrı bir X11 seat'te
    login olmuş durumda) ve `list-sessions`'ın sırası bu ikinci kullanıcının
    KİLİTLİ session'ını fatihyuce'nin kendi AÇIK/aktif session'ından ÖNCE
    listeliyordu — layout, fatihyuce'nin ekranı hiç kilitli olmamasına rağmen
    "kilitli" sanıp reddediyordu (canlı doğrulandı: `loginctl show-session`
    ile session 4 (`fatihyuce`, tty2) `LockedHint=no`/`Active=yes` iken,
    session 1445 (`ahmet`, tty3) `LockedHint=yes` — eski kod ikincisini
    yakalıyordu). Fix: satırı KULLANICI ADINA göre süz (`whoami` — bu süreç
    HER ZAMAN hesap sahibi olarak çalışıyor, [[co-ulaksec-guard-yes-ho-no]]'nun
    tek-kullanıcı varsayımıyla AYNI), pozisyonel "ilk satır" varsayımı YOK."""
    try:
        out = subprocess.run(
            ["bash", "-c",
             "loginctl show-session "
             "$(loginctl --no-legend list-sessions | awk -v u=\"$(whoami)\" '$3==u {print $1; exit}') "
             "-p LockedHint"],
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

    # "windowless" = tmux-backed ama hiçbir terminal istemcisi bağlı DEĞİL — ya
    # spawn.py'nin fallback'ı devrede (gnome-terminal o an bozuktu) ya da
    # pencere sonradan kapandı/kayboldu.
    #
    # Kaynak tmux'un KENDİ istemci listesi (`list-clients`), pencere BAŞLIKLARI
    # değil (2026-09-07 kullanıcı raporu: "biraz önce açtığım tüm pencereler
    # pencereli olduğu halde windowless görüyor" — ve o yanlış uyarıya uyup
    # "pencere aç"a basınca session'ın zaten bağlı penceresinin YANINA ikinci
    # bir istemci bağlanıyor, aynı pane iki pencerede aynalanıyor). Başlık
    # eşleştirmesi doğası gereği kırılgan: pencere yeni açılmışken başlık henüz
    # gelmemiş olabiliyor, CLI'ın TUI'si başlığı eski bir adda bırakabiliyor
    # ([[stale-tui-title-cross-suffix-resume]], layout'ta da aynı sorun var,
    # TODO #46) — ikisi de "penceresi VAR ama başlığı tutmuyor" demek.
    # None = bilinmiyor (tmux yok/hata), boş liste ile karıştırılmamalı.
    windowless = None
    try:
        rows = [(s.name, tmux_client_count(s.name)) for s in find_sessions(measure_cpu=False)
                if is_tmux_backed(s.pid)]
        windowless = [n for n, c in rows if c == 0]
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
    session'ında sor — blueprint'siz bir instance olarak kaydedilir, "Terminal"
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

    mode, effort = provider.permission_modes()[0], provider.effort_levels()[-1]
    inst_mod.record_instance(new_name, blueprint=None, cwd=REPO_DIR, cli=chosen_cli, model=model,
                             permission_mode=mode, effort=effort, origin="diag")
    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
            kind = spawn_session(
                name=new_name, cwd=REPO_DIR, model=model, display=detect_display(),
                permission_mode=mode,
                effort=effort,
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

    from ..layout import GRID, _get_screen, _list_windows, build_layout_plan, apply_layout

    pinned = [n.strip() for n in pin.split(",") if n.strip()] if pin else []
    group_lists = [[b.strip() for b in g.split(",") if b.strip()] for g in groups if g.strip()]
    grid = load_settings().get("layout_grid") or GRID

    windows = _list_windows(display)
    screen = _get_screen(display, screen_y=screen_y, grid=grid)
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


_BUSY_CACHE: dict = {}  # name -> (expires_monotonic, bool | None)
# needs_ho'nun 30s'inden ÇOK daha kısa: busy/idle SANİYELER içinde değişir,
# kullanıcı satırın bunu "canlı" yansıtmasını bekler (2026-08-28 istek: "eger
# cli de is varsa calisior gorunsun yoksa calsmiyor gibi"). Yine de HER
# poll'da tmux capture-pane koşmasın diye kısa bir TTL var.
_BUSY_TTL = 2.0


def _is_busy_cached(s) -> Optional[bool]:
    """Çalışan session GERÇEKTEN bir tur işliyor mu (thinking/tool-çalışırken) —
    `cpu%` güvenilir bir sinyal DEĞİL (API yanıtı beklerken network-bound,
    CPU düşük kalabilir, bkz. TODO). `provider.busy_status_pattern()` yoksa
    (bu CLI'da böyle bir sinyal tanımlanmamış) veya session tmux-backed
    değilse (canlı capture imkânsız) None — needs_ho'daki AYNI "bilinmiyor ≠
    False" sözleşmesi, UI '?' gösterir."""
    if not is_tmux_backed(s.pid):
        return None
    pattern = get_provider(s.cli).busy_status_pattern()
    if not pattern:
        return None
    now = time.monotonic()
    hit = _BUSY_CACHE.get(s.name)
    if hit and hit[0] > now:
        return hit[1]
    # `lines=8` (durum çubuğu her zaman ekranın en altında) `_detect_mode_in_text`'in
    # 2000-satırlık capture'ının aksine zaten dar — eski/kaydırılmış bir eşleşme
    # riski yok, ekstra tail-filtreleme gerekmiyor.
    text = tmux_capture(s.name, lines=8)
    val = bool(re.search(pattern, strip_ansi(text))) if text is not None else None
    _BUSY_CACHE[s.name] = (now + _BUSY_TTL, val)
    return val


_HISTORY_CACHE: dict = {}  # name -> (expires_monotonic, int | None)
# `_needs_ho_cached`'in 30s'iyle AYNI (busy'nin 2s'inden ÇOK daha uzun kalabilir) —
# tmux scrollback boyutu saniyeler içinde önemli ölçüde değişmez, ana tabloda HER
# session için ekstra bir `list-panes` çağrısı gerektirdiğinden (2026-09-15,
# "1900-2000 olanları seç" butonu için eklendi) kısa bir TTL'e gerek yok.
_HISTORY_TTL = 30.0


def _history_size_cached(s) -> Optional[int]:
    """Ana tablodaki her satır için pane'in gerçek tmux scrollback boyutu —
    `TerminalView.tsx`'in Terminal modal'ı içindeki AYNI `tmux_pane_size()`'ın
    (`#{history_size}`) 30s-cache'li hâli, bulk-select butonunun (2026-09-15,
    kullanıcı: "1900-2000 olanları... seç butonu") tüm satırlara karşı
    çalışabilmesi için. tmux-backed değilse (capture imkânsız) None."""
    if not is_tmux_backed(s.pid):
        return None
    now = time.monotonic()
    hit = _HISTORY_CACHE.get(s.name)
    if hit and hit[0] > now:
        return hit[1]
    size = tmux_pane_size(s.name)
    val = size[2] if size else None
    _HISTORY_CACHE[s.name] = (now + _HISTORY_TTL, val)
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
    registry = inst_mod.load_instances()
    assigned = {}
    for s in all_live:
        if s.name in active_names:
            assigned[s.name] = s
    # Base-fallback sadece kayıtsız eski proc'lar için; kayıtlı instance kendi satırında görünür.
    for s in all_live:
        if (s.name not in active_names and s.name not in registry
                and s.base in active_names and s.base not in assigned):
            assigned[s.base] = s
    assigned_pids = {s.pid for s in assigned.values()}

    sessions, closed, retired = [], [], []
    for name in sorted(fleet):
        info = fleet[name]
        if info["state"] == "retired":
            retired.append({"name": name, "cwd": info["cwd"], "model": info["model"], "cli": info["cli"],
                             "host": LOCAL_HOST_NAME})
            continue
        if info["state"] == "closed":
            closed.append({"name": name, "cwd": info["cwd"], "model": info["model"], "cli": info["cli"],
                            "host": LOCAL_HOST_NAME})
            continue
        s = assigned.get(name)
        sessions.append({
            "name": name,
            "model": info["model"],
            "cwd": info["cwd"],
            # `info["cli"]` (roster.tsv'nin KAYITLI değeri) DEĞİL, çalışıyorsa
            # `s.cli` (proc-scan'in canlı tespiti) — 2026-09-13 canlı bug:
            # "Start"tan roster'dakinden FARKLI bir cli seçilip başlatılınca
            # (`_start()`'ın `chosen_cli` override'ı) roster.tsv'nin 4. kolonu
            # GÜNCELLENMİYOR, bu satır hep info["cli"]'ye bakınca panel session
            # GERÇEKTEN codex çalışırken "claude" gösteriyordu (canlı örnek:
            # rustagentppr — roster "claude" diyor, proc `codex --model
            # gpt-6-astra` çalıştırıyor, `find_sessions()` doğru "codex"
            # döndürüyor ama bu satır onu hiç kullanmıyordu). `model`/`live_model`
            # ayrımıyla KARIŞTIRILMAMALI: model kasıtlı olarak roster'ın "bir
            # sonraki başlatmada kullanılacak" değerini gösteriyor (ayrı bir
            # `live_model` alanı var), ama `cli` provider-spesifik TÜM UI'ın
            # (mode/model seçenekleri, terminal parse'ı) dayandığı tek alan —
            # yanlış olması kozmetik değil, session'a YANLIŞ provider'ın
            # arayüzünü gösterir. Çalışmıyorsa (s=None) roster'ın kaydı zaten
            # TEK kaynak (bir sonraki başlatmada kullanılacak olan).
            "cli": s.cli if s else info["cli"],
            "running": s is not None,
            "pid": s.pid if s else None,
            "cpu": round(s.cpu, 1) if s else None,
            "kind": ("fresh" if s.is_fresh else "resume") if s else None,
            "needs_ho": _needs_ho_cached(s) if s else None,
            "busy": _is_busy_cached(s) if s else None,
            "history_size": _history_size_cached(s) if s else None,
            "registered": True,
            "instance": False,
            "blueprint": name,
            "tmux": is_tmux_backed(s.pid) if s else False,
            "host": LOCAL_HOST_NAME,
            # `model` roster/models.tsv'nin KAYITLI değeri (durmuş satırlarda da
            # dolu, "bir sonraki başlatmada bu kullanılacak" anlamında). Bunlar ise
            # ÇALIŞAN process'in kendi komut satırından: panelin bir session'ın
            # GERÇEKTEN hangi modelle/effort'la açıldığını gösterebilmesi için —
            # ikisi ayrışabiliyor, çünkü panelden tek seferlik bir modelle
            # başlatmak models.tsv'yi DEĞİŞTİRMİYOR. Çalışmıyorsa/bilinmiyorsa None.
            "live_model": (s.model if s else None),
            "live_effort": (s.effort if s else None),
        })

    # Hiçbir AKTİF roster satırına bağlanamayan canlı session'lar (elle açılmış
    # ad-hoc bir şey, ya da adı sadece kapalı/emekli bir satıra denk gelen proc) —
    # "kayıtsız" olarak göster; hiçbir canlı proc panelde görünmez kalmasın.
    # instances.json'daki instance'lar da buradan, kayıtlı (registered+instance) olarak gelir.
    for s in all_live:
        if s.pid in assigned_pids:
            continue
        rec = registry.get(s.name)
        sessions.append({
            "name": s.name,
            "model": (rec.get("model") if rec else None) or s.model or "?",
            "cwd": s.cwd,
            "cli": s.cli,
            "running": True,
            "pid": s.pid,
            "cpu": round(s.cpu, 1),
            "kind": "fresh" if s.is_fresh else "resume",
            "needs_ho": _needs_ho_cached(s),
            "busy": _is_busy_cached(s),
            "history_size": _history_size_cached(s),
            "registered": rec is not None,
            "instance": rec is not None,
            "blueprint": rec.get("blueprint") if rec else None,
            "tmux": is_tmux_backed(s.pid),
            "host": LOCAL_HOST_NAME,
            "live_model": s.model,
            "live_effort": s.effort,
        })

    payload = {
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
                # permission_modes()'ın DAR alt kümesi: session çalışırken
                # (Shift+Tab ile) gerçekten değiştirilebilenler. Boş liste →
                # panel Terminal'de mod seçicisini hiç göstermez.
                "cyclable_modes": p.cyclable_modes(),
            }
            for name, p in PROVIDERS.items()
        },
        "layout_missing_deps": _missing_layout_deps(),
        "diag": _diag_status(),
        "server_started_at": _WEB_PROC_START_EPOCH,
        # Salt-okunur — `py/cops service install --label` (varsa) tarafından yazılan
        # tunnel URL/label dosyaları. service.py'yi İMPORT ETMİYORUZ (o modül tunnel.log'u
        # da web.py'den bağımsız kendi tarafında tanımlıyor, aynı hafif-tekrar deseni) —
        # sadece dosya yoksa None, hiçbir zaman hata.
        "tunnel": _tunnel_info(),
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
        # 2026-09-04, "Uzak Masaüstü" sekmesi: remote_desktop.py'nin daemon
        # lifecycle durumu — diğer açık tab/cihazlar da (WS push ile) canlı
        # görsün diye buraya eklendi, ayrı bir polling endpoint'i değil.
        "remote_desktop": remote_desktop.status(),
        # TOBEDECIDED#15 Phase 1 — HAFİF görünüm (2s WS/poll cadence'ine
        # biniyor, tam sonuç metni YOK): taslak kadro + aktif run özeti +
        # son birkaç run. Local-only, `web_hosts.merge_status`'a hiç girmez.
        "orch": {"draft": web_orch.get_draft(), "active": web_orch.active_summary(),
                 "recent": web_orch.list_runs(5)},
        # 2026-09-17, "son snapshot" — bkz. aşağıdaki "Fleet snapshot" bölümü.
        # `orch` gibi local-only, `web_hosts.merge_status`'a hiç girmez (bu
        # makinenin KENDİ fleet'inin anlık görüntüsü, uzak host'unkiyle
        # karışmamalı).
        "snapshot": _snapshot_info(),
    }
    # Uzak host'ların sessions/closed/retired'ini merge eder + "hosts" ekler —
    # SADECE web_hosts'un arka-plan poller cache'ini okur, asla burada network'e
    # gitmez (bkz. web_hosts.py modül docstring'i — neden burada fan-out YAPILMADIĞI).
    return web_hosts.merge_status(payload)


def _tunnel_info() -> dict:
    def _read(fname: str) -> Optional[str]:
        try:
            return (Path(CLAUDEOPS_DIR) / fname).read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
    return {"url": _read("tunnel_url.txt"), "label": _read("tunnel_label.txt")}


def _snapshot_info() -> dict:
    """`/api/status` payload'ının "snapshot" alanı — sadece meta (ne zaman,
    kaç session), tam liste `results`/resume akışının işine yarar ama Settings
    panelinin "Son snapshot: X, N session" gösterimi için gereksiz büyük."""
    snap = load_snapshot()
    return {"saved_at": snap.get("saved_at"), "count": len(snap.get("sessions") or [])}


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
           cli: str = "", hidden: bool = False, lang: str = "tr") -> dict:
    """Aktif bir blueprint'i ya da (Geçmiş'ten) durmuş bir instance'ı başlat/devam ettir."""
    fleet = _fleet_status()
    info = fleet.get(name)
    rec = None if info else inst_mod.get_instance(name)
    if rec is None and (not info or info["state"] != "active"):
        return _err(lang, "not_active", name=name)
    src = info or rec
    chosen_cli = cli.strip() if cli.strip() in PROVIDERS else src["cli"]
    # Tam isim, cli'dan bağımsız: blueprint'in kendi instance'larıyla yan yana açılabilmesi
    # için base'e bakılmaz; aynı isimli ikinci spawn ise `tmux new-session -A` yüzünden
    # yeni session açmaz, var olana bağlanırdı.
    if any(s.name == name for s in find_sessions(measure_cpu=False)):
        return _err(lang, "already_running", name=name)
    # src["model"] eski cli'nin modeli — kullanıcı cli'yi DEĞİŞTİRİP model alanını
    # boş bırakırsa (react: useState("") "kullan varsayılanı" anlamına gelir) burada
    # YANLIŞ cli'nin modeliyle spawn oluyordu (ör. codex'e geçip boş bırakınca "codex
    # --model claude-sonnet-5" gibi geçersiz bir çağrı — canlı kullanıcı raporu,
    # 2026-09-01). cli değişmediyse eski davranış (src["model"]) aynen korunur.
    fallback_model = src["model"] if chosen_cli == src["cli"] else default_model_for(get_provider(chosen_cli))
    chosen_model = model.strip() or fallback_model
    chosen_mode = permission_mode.strip() or (rec or {}).get("permission_mode") or "auto"
    chosen_effort = effort.strip() or (rec or {}).get("effort") or "max"
    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
            kind = spawn_session(
                name=name,
                cwd=src["cwd"],
                model=chosen_model,
                display=detect_display(),
                permission_mode=chosen_mode,
                effort=chosen_effort,
                force_new=bool(fresh),
                cli=chosen_cli,
                hidden=hidden,
            )
            opened = _wait_stable(name, timeout=HANDOVER_PROC_WAIT_SECONDS)
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    if not opened:
        return _err(lang, "start_no_proc", name=name, kind=kind)
    if rec is not None:
        inst_mod.mark_started(name, cli=chosen_cli, model=chosen_model,
                              permission_mode=chosen_mode, effort=chosen_effort)
    return {"ok": True, "kind": kind}


def _stop(name: str, lang: str = "tr") -> dict:
    kind, procs = _find_running_for_action(name)
    if kind == "none":
        return _err(lang, "not_running", name=name)
    if kind == "ambiguous":
        return _err(lang, "ambiguous_name", name=name, candidates=", ".join(s.name for s in procs))
    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
            results = [kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS, name=s.name) for s in procs]
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "result": results}


def _term_resolve(name: str, lang: str = "tr"):
    """Terminal endpoint'lerinin ortak çözümlemesi: name → tek, canlı, tmux-backed
    Session, yoksa (None, err-dict) döner.

    2026-09-14 fix: eskiden `_find_running` kullanıyordu ve birden fazla aynı-
    base eşleşme varsa SESSİZCE `procs[0]`'ı (sıralamaya bağlı, rastgele
    hangisi) seçiyordu — input/output YANLIŞ session'a gidebilirdi (kill değil
    ama fark edilmesi zor bir yanlış-yönlendirme). `_find_running_for_action`
    artık bu belirsizliği açıkça reddediyor."""
    kind, procs = _find_running_for_action(name)
    if kind == "none":
        return None, _err(lang, "not_running", name=name)
    if kind == "ambiguous":
        return None, _err(lang, "ambiguous_name", name=name, candidates=", ".join(s.name for s in procs))
    s = procs[0]
    if not is_tmux_backed(s.pid):
        return None, _err(lang, "not_tmux_backed", name=name)
    if not tmux_has_session(s.name):
        return None, _err(lang, "term_session_gone", name=name)
    return s, None


# `_term_output`'a ÖZEL, ucuz çözümleme yolu (2026-09-16, kullanıcı: "hala
# bizden kaynaklı gecikmeler var... lokalde bile hissedilebiliyor" —
# terminal popup'ın xterm-preload'dan SONRA da hâlâ yavaş hissettirmesi
# üzerine ölçüldü). `_term_resolve`'un `find_sessions()`'ı — bu makinede
# ~35ms, 700+ proc'u TÜM sistem genelinde tarayan bir psutil taraması —
# `/ws/term`'ün poll döngüsünde HER tick'te (200ms'de bir, açık her
# terminal için ayrı ayrı) tekrar çalışıyordu. Gereksizdi: `tmux_capture`/
# `tmux_pane_size`/`pane_is_masked_input` (hemen altta, `_term_output`)
# ZATEN isim-bazlı — tmux session'ı yaşadığı sürece İÇİNDE HANGİ PID
# çalışıyor olursa olsun doğru cevabı verirler, dolayısıyla PID-seviyesi
# kimliği her tick'te tazelemenin gerçek bir karşılığı yok. Kısa bir TTL'le
# son çözümleme cache'leniyor; tam `_term_resolve` (ambiguous/
# is_tmux_backed dahil) sadece cache boşken/süresi geçmişken çalışır.
# Mutasyon uç noktaları (`_term_input` vb.) bu cache'i KULLANMIYOR — onlar
# tek-atım kullanıcı aksiyonu, her seferinde tam/taze doğrulama ucuz
# olmasa da daha değerli.
_TERM_OUTPUT_RESOLVE_TTL = 2.0  # saniye
_term_output_resolve_cache: Dict[str, tuple] = {}  # name -> (Session, resolved_at)


def _term_resolve_for_output(name: str, lang: str = "tr"):
    cached = _term_output_resolve_cache.get(name)
    now = time.monotonic()
    if cached is not None and (now - cached[1]) < _TERM_OUTPUT_RESOLVE_TTL:
        return cached[0], None
    s, err = _term_resolve(name, lang)
    if err:
        _term_output_resolve_cache.pop(name, None)
        return None, err
    _term_output_resolve_cache[name] = (s, now)
    return s, None


_MAX_VALIDATE_CANDIDATES = 20  # bir terminal-metni taramasından gelen aday listesini sınırla — her aday bir stat() çağrısı, sınırsız liste kabul etmeye gerek yok


def _files_resolve(name: str, lang: str = "tr"):
    """Dosya-gezgini endpoint'lerinin ortak çözümlemesi: name → Session (canlı
    ise gerçek proc, değilse roster'dan sentetik). `_term_resolve`'dan farkı:
    tmux-backed olması GEREKMEZ — dosya listeleme/indirme bir pty'e değil,
    sadece cwd/cli bilgisine ihtiyaç duyar (proc-presence yeterli,
    [[TODO-k]]'nın aynı kriteri).

    2026-09-14: durmuş (Devre Dışı/Emekli dahil) bir roster kaydı için de
    çalışır — `pid=0` sentetik `Session` (bu dosyada zaten `Session(name=base,
    pid=0)` deseni var, ör. `_generate_new_chat_name`'in kullandığı). Aşağıdaki
    `files_mod.list_dir`/`read_text`/`validate_candidates` SADECE `s.cwd`/
    `s.cli`'ye bakıyor, `s.pid`'e hiç dokunmuyor — canlı doğrulandı (kod
    okuması + gerçek bir kapalı roster girdisine karşı test)."""
    procs = _find_running(name)
    if procs:
        return procs[0], None
    info = _fleet_status().get(name) or inst_mod.get_instance(name)
    if info:
        return Session(name=name, pid=0, cwd=info["cwd"], cli=info["cli"]), None
    return None, _err(lang, "not_running", name=name)


def _files_list(name: str, path: Optional[str], lang: str = "tr") -> dict:
    s, err = _files_resolve(name, lang)
    if err:
        return err
    result = files_mod.list_dir(s, path)
    if result["ok"]:
        return result
    return _err(lang, f"files_{result['error']}", name=name)


def _files_read(name: str, path: str, lang: str = "tr") -> dict:
    s, err = _files_resolve(name, lang)
    if err:
        return err
    text, code = files_mod.read_text(s, path)
    if code:
        limit_mb = files_mod.MAX_VIEW_BYTES / (1024 * 1024)
        return _err(lang, f"files_{code}", name=name, limit_mb=limit_mb)
    return {"ok": True, "text": text}


def _files_validate(name: str, paths: list, lang: str = "tr") -> dict:
    s, err = _files_resolve(name, lang)
    if err:
        return err
    if not isinstance(paths, list):
        return {"ok": True, "valid": []}
    candidates = [p for p in paths if isinstance(p, str)][:_MAX_VALIDATE_CANDIDATES]
    return {"ok": True, "valid": files_mod.validate_candidates(s, candidates)}


def _open_in_vscode(target: str) -> None:
    """Fire-and-forget, `_launch_gnome_terminal`'daki AYNI desen (`spawn.py`) —
    `-n`/`--new-window` her zaman AYRI bir pencere açar (kullanıcı: "ayrı
    pencerede açsa"). `.wait()` senkron çağrılmıyor (VS Code kendi window'unu
    yönetir, HTTP isteğini bloklamamalı); global SIGCHLD=SIG_IGN YERİNE sadece
    BU child'ı arka planda reap eden bir daemon thread — aksi halde uzun
    yaşayan `py/cops web`'de zombie birikir (aynı ders, spawn.py'nin gnome-
    terminal çağrısıyla)."""
    proc = subprocess.Popen(["code", "-n", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Thread(target=proc.wait, daemon=True).start()


def _vscode_open(name: str, path: Optional[str], lang: str = "tr") -> dict:
    """Sadece fiziksel olarak makinenin başındaysan (ya da Uzak Masaüstü'yle o
    pencereyi görebiliyorsan) işe yarar — VS Code gerçek bir X11 penceresi
    açar, panelin kendisinden görüntülenemez/kontrol edilemez (bilerek, TODO.md).
    `path` verilmezse session'ın proje kökü (tüm proje) açılır."""
    s, err = _files_resolve(name, lang)
    if err:
        return err
    real, code = files_mod.resolve_path(s, path)
    if code:
        return _err(lang, f"files_{code}", name=name)
    if not shutil.which("code"):
        return _err(lang, "vscode_not_found")
    _open_in_vscode(real)
    return {"ok": True}


def _term_output(name: str, lang: str = "tr") -> dict:
    s, err = _term_resolve_for_output(name, lang)
    if err:
        return err
    text = tmux_capture(s.name, lines=2000)
    if text is None:
        _term_output_resolve_cache.pop(name, None)  # respawn/gone — sıradaki tick taze çözümlesin
        return _err(lang, "term_session_gone", name=name)
    size = tmux_pane_size(s.name)
    masked = pane_is_masked_input(s.name)
    # `mode`/`masked` ikisi de bu ZATEN çekilmiş metne/pane'e biniyor — 200ms'lik
    # poll'a ek bir tmux çağrısı EKLEMİYORLAR. mode None = bu CLI'da canlı izin
    # modu diye bir şey yok (panel seçiciyi hiç göstermez). `history_size` de
    # AYNI `tmux_pane_size` çağrısına biniyor (2026-09-14, TODO.md'nin "terminalde
    # kaç satır olduğu gösterilsin" maddesi) — pane'in gerçek scrollback boyutu,
    # `HISTORY_LIMIT`'e (2000) yaklaşınca frontend'in vurgulaması için.
    return {"ok": True, "text": text, "cols": size[0] if size else None,
            "rows": size[1] if size else None, "history_size": size[2] if size else None,
            "masked": bool(masked), "mode": _detect_mode_in_text(text, get_provider(s.cli))}


def _term_input(name: str, text: str, lang: str = "tr") -> dict:
    s, err = _term_resolve(name, lang)
    if err:
        return err
    ok = tmux_send_keys(s.name, text, settle_delay=get_provider(s.cli).input_settle_delay())
    return {"ok": True} if ok else _err(lang, "term_session_gone", name=name)


def _term_key(name: str, key: str, lang: str = "tr") -> dict:
    if key not in ALLOWED_SPECIAL_KEYS:
        return _err(lang, "invalid_key")
    s, err = _term_resolve(name, lang)
    if err:
        return err
    ok = tmux_send_special_key(s.name, key)
    return {"ok": True} if ok else _err(lang, "term_session_gone", name=name)


# Tek bir canlı-yazma isteğinin taşıyabileceği en fazla karakter. Normal
# yazımda 1-2 karakter, yapıştırmada bir blok gelir — frontend zaten kendi
# tamponunu her ~25ms'de boşaltıyor, yani bu sınıra ancak GERÇEKTEN büyük bir
# yapıştırma çarpar. Amacı pane'i korumak değil (aynı metin komut kutusundan
# da gönderilebilirdi), kazara/hatalı bir istemcinin megabaytlık bir gövdeyi
# tmux argv'sine akıtmasını engellemek.
MAX_TERM_RAW_CHARS = 8192


def _term_raw(name: str, data: str, lang: str = "tr") -> dict:
    """Terminal görünümünün "canlı yazma" modu (2026-09-08, kullanıcı: "neden
    direk terminale yazamiyorum da text box a yazmaya mecbur kaliorum") —
    xterm.js'in `onData` callback'inden gelen ham tuş verisini pane'e olduğu
    gibi iletir.

    `/api/term/key`'in (sabit `ALLOWED_SPECIAL_KEYS` listesi) aksine keyfi
    kontrol dizilerine izin verir; `/api/term/input`'un aksine sonuna Enter
    EKLEMEZ. Yeni bir yetki açmıyor — aynı pane'e aynı metni göndermenin
    zaten iki yolu vardı, bu üçüncüsü sadece "tuş tuş" olanı."""
    if not data:
        return {"ok": True}
    if len(data) > MAX_TERM_RAW_CHARS:
        return _err(lang, "term_raw_too_long", limit=MAX_TERM_RAW_CHARS)
    s, err = _term_resolve(name, lang)
    if err:
        return err
    ok = tmux_send_raw(s.name, data)
    return {"ok": True} if ok else _err(lang, "term_session_gone", name=name)


_MODE_CYCLE_MAX_PRESSES = 8  # döngü uzunluğundan (≤4 bilinen mod) cömert marj
_MODE_CYCLE_POLL_DELAY = 0.6  # BTab sonrası TUI'nin yeniden çizilmesini bekle
# provider adı → {mod: derlenmiş regex}. Desenlerin KENDİSİ provider'ın
# (`mode_status_patterns()`), derleme sadece burada — `_term_output` her 200ms'de
# bir çağrıldığı için her seferinde yeniden derlemeye gerek yok.
_MODE_PATTERN_CACHE: Dict[str, Dict[str, "re.Pattern"]] = {}


def _mode_patterns(provider) -> Dict[str, "re.Pattern"]:
    cached = _MODE_PATTERN_CACHE.get(provider.name)
    if cached is None:
        cached = {m: re.compile(pat, re.IGNORECASE) for m, pat in provider.mode_status_patterns().items()}
        _MODE_PATTERN_CACHE[provider.name] = cached
    return cached


def _detect_mode_in_text(text: str, provider) -> Optional[str]:
    """Durum çubuğundan aktif izin modunu okur — TÜM capture'da değil (eski,
    kaydırılmış bir 'plan mode on' metnine yanlışlıkla yakalanmasın diye),
    sadece en sondaki birkaç DOLU satırda arar. None döner ↔ ya bu CLI'da canlı
    mod kavramı yok (provider hiç desen tanımlamamış) ya da o an ekranda hiçbir
    mod metni görünmüyor (TUI henüz açılıyor, ekran başka bir şeyle dolu) —
    HİÇBİRİ "şu modda" diye YORUMLANMAZ; bir mod varsayıp yanlış göstermektense
    "bilinmiyor" demek doğru (eski kod burada "default" varsayıyordu)."""
    patterns = _mode_patterns(provider)
    if not patterns:
        return None
    tail_lines = [ln for ln in strip_ansi(text).splitlines() if ln.strip()][-8:]
    tail = "\n".join(tail_lines)
    for mode, pattern in patterns.items():
        if pattern.search(tail):
            return mode
    return None


def _detect_current_mode(name: str, provider) -> Optional[str]:
    """`_detect_mode_in_text`'in kendi capture'ını çeken hâli — `_term_set_mode`'un
    döngüsü için (orada elde hazır bir metin yok). `_term_output` bu yolu KULLANMAZ,
    zaten çektiği metni doğrudan `_detect_mode_in_text`'e verir (200ms'lik poll'a
    ikinci bir `capture-pane` eklememek için)."""
    text = tmux_capture(name, lines=2000)
    if text is None:
        return None
    return _detect_mode_in_text(text, provider)


def _term_set_mode(name: str, target_mode: str, lang: str = "tr") -> dict:
    """Çalışan bir session'ın izin modunu Shift+Tab (`BTab`) döngüsüyle
    hedeflenen moda getirir — claude CLI'nin izin modunu doğrudan set eden bir
    slash komutu YOK (claude-code-guide ajanının resmi dokümandan doğrulaması,
    2026-09-07), TEK resmi/önerilen canlı-değiştirme yolu bu tuş döngüsü.
    Sabit bir döngü SIRASI/uzunluğu VARSAYMAZ — her basıştan sonra durumu
    yeniden okuyup hedefe ulaşılıp ulaşılmadığını kontrol eder (uyarlanabilir,
    session'a göre değişebilecek döngü kompozisyonuna dayanıklı).

    Döngü listesi provider'dan gelir: boşsa (claude dışındaki CLI'lar) İSTEK
    BAŞTAN REDDEDİLİR — eskiden bu yol, mod diye bir kavramı olmayan bir TUI'ye
    de 8 kez Shift+Tab basıp ne olduğu belirsiz bir şey tetikleyebilirdi."""
    s, err = _term_resolve(name, lang)
    if err:
        return err
    provider = get_provider(s.cli)
    cyclable = provider.cyclable_modes()
    if not cyclable:
        return _err(lang, "mode_cycle_unsupported", name=name, cli=s.cli)
    if target_mode not in cyclable:
        return _err(lang, "mode_not_cyclable", name=name, mode=target_mode, modes="/".join(cyclable))
    start_mode = _detect_current_mode(s.name, provider)
    if start_mode == target_mode:
        return {"ok": True, "mode": start_mode, "presses": 0}
    current = start_mode
    for i in range(_MODE_CYCLE_MAX_PRESSES):
        if not tmux_send_special_key(s.name, "BTab"):
            return _err(lang, "term_session_gone", name=name)
        time.sleep(_MODE_CYCLE_POLL_DELAY)
        current = _detect_current_mode(s.name, provider)
        if current == target_mode:
            return {"ok": True, "mode": current, "presses": i + 1}
        if start_mode is not None and current == start_mode:
            # Tam tur atıldı: hedef bu session'ın döngüsünde YOK. Kritik olan
            # şu an BAŞLANGIÇ modunda olmamız — hiçbir şey değişmedi. (Eskiden
            # burada kör kör 8 kez basılıyordu: 3'lük bir döngüde bu, session'ı
            # istenmeyen bir moda taşıyıp üstüne "başarısız" demek demekti.)
            return _err(lang, "mode_cycle_unreachable", name=name, mode=target_mode, current=current)
    return _err(lang, "mode_cycle_failed", name=name, mode=target_mode, current=current or "?")


def _term_chat(name: str, lang: str = "tr", mode: str = "last", since: int = 0) -> dict:
    """Terminal popup'ının 'Sohbet' sekmesi: capture-pane/ANSI yerine provider'ın
    kendi transcript'inden (jsonl vb.) STRUCTURED metin döndürür — xterm.js'in
    mobilde scroll/render sorunlarını tamamen bypass eder. Desteklemeyen
    provider'lar (agy/shell, henüz) için supported:false döner, hata değil —
    panel bunu "henüz yok" olarak gösterir.

    `mode="last"` (varsayılan): son user+assistant çifti (eski davranış, aynen).
    `mode="full"` (2026-09-01, kullanıcı isteği): TÜM konuşma geçmişi, sırayla
    [{"role":"user"|"assistant","text":...}, ...] — `last_exchange`'le AYNI
    destekleniyor/desteklenmiyor sözleşmesi (`full_history` None → supported:False).

    `since` (2026-09-17, kullanıcı: "chat bilgisini alirken full almama lazim...
    once ust alindi ise bir daha ustu almamalisin sadece kalanlari almalisin") —
    `mode="full"`'da: client'ın ZATEN sahip olduğu mesaj sayısı. `ChatView.tsx`
    her ~2.5s'de bir poll ediyor (`CHAT_POLL_INTERVAL_MS`) — `since` olmadan her
    poll TÜM geçmişi (uzun bir konuşmada potansiyel binlerce mesaj) yeniden
    ağdan gönderiyordu, halbuki jsonl append-only olduğu için ÇOĞU poll'da HİÇBİR
    ŞEY değişmiyor. Artık sadece `since`'ten SONRAKİ mesajlar dönüyor + her zaman
    `total` (client'ın bir SONRAKİ `since`'i hesaplaması için). `since`, mevcut
    `total`'dan BÜYÜKSE (konuşma resetlenmiş/handover ile yeni sid'e geçilmiş —
    jsonl KÜÇÜLMÜŞ demektir) 0'a clamp edilip TAM liste dönülür; client bunu ayrı
    bir bayrağa gerek KALMADAN `messages.length === total` kontrolüyle ayırt edip
    (eşitse tam liste geldi demektir → replace, değilse → append) kendini
    yeniden-eşitliyor (bkz. `ChatView.tsx`).

    2026-09-14: `_term_resolve` (canlı+tmux-backed ŞART) DEĞİL, `_files_resolve`
    kullanıyor — sohbet geçmişi `provider.last_exchange`/`full_history` üzerinden
    DİSKTEKİ transcript'ten okunuyor (bkz. o metodların kendi sözleşmesi), pty'e
    hiç ihtiyaç yok. Bu, durmuş/Devre Dışı/Emekli bir session'ın "son mesajları"
    salt-okunur görüntülemeyi (terminal olmadan) mümkün kılıyor — `_files_resolve`
    zaten roster-fallback'ini yapıyor, burada tekrar yazmaya gerek yok."""
    s, err = _files_resolve(name, lang)
    if err:
        return err
    provider = get_provider(s.cli)
    if mode == "full":
        messages = provider.full_history(s.cwd, s.sid)
        if messages is None:
            return {"ok": True, "supported": False}
        total = len(messages)
        start = since if 0 <= since <= total else 0
        return {"ok": True, "supported": True, "messages": messages[start:], "total": total}
    exchange = provider.last_exchange(s.cwd, s.sid)
    if exchange is None:
        return {"ok": True, "supported": False}
    return {"ok": True, "supported": True, "user": exchange["user"], "assistant": exchange["assistant"]}


def _open_window(name: str, lang: str = "tr", force: bool = False) -> dict:
    """Windowless (tmux-only) kalmış bir session'a YENİ bir gnome-terminal penceresi
    bağlar — CLI'ı yeniden başlatmadan. `_diag_status()`'un `windowless` listesindeki
    satırlara panelde tek-tık telafi butonu için (2026-08-28)."""
    s, err = _term_resolve(name, lang)
    if err:
        return err
    # Zaten bağlı bir istemci varsa İKİNCİ bir pencere açmak session'ı
    # "çoğaltmaz", aynı pane'i aynalar — iki pencere aynı ekranı gösterir, tmux
    # pane boyutunu istemcilere göre yeniden ayarlar ve kullanıcı hangisinin
    # "gerçek" olduğunu bilemez (2026-09-07 canlı raporun ikinci yarısı tam
    # buydu). Yanlış bir windowless tespiti düzeltildi ama buton yine de bir
    # yarışta/eski veriyle basılabilir — asıl koruma burada, `force` ile
    # bilerek istenirse yine mümkün.
    if not force:
        clients = tmux_client_count(s.name)
        if clients:
            return _err(lang, "window_already_attached", name=name, count=clients)
    ok = open_window(s.name, s.cwd, display=detect_display())
    return {"ok": True} if ok else _err(lang, "term_session_gone", name=name)


def _stop_instance(name: str, lang: str = "tr") -> dict:
    """Instance'ın kapalı/emekli hâli yok: Kapat/Emekli = durdur (durmuşsa no-op)."""
    kind, procs = _find_running_for_action(name)
    if kind == "ambiguous":
        return _err(lang, "ambiguous_name", name=name, candidates=", ".join(s.name for s in procs))
    if procs:
        try:
            with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
                for s in procs:
                    kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS, name=s.name)
        except TimeoutError as e:
            return {"ok": False, "error": str(e)}
    return {"ok": True, "instance": True}


def _retire(name: str, lang: str = "tr") -> dict:
    fleet = _fleet_status()
    info = fleet.get(name)
    if not info and inst_mod.get_instance(name) is not None:
        return _stop_instance(name, lang)
    if not info:
        return _err(lang, "undefined", name=name)
    if info["state"] == "retired":
        return _err(lang, "already_retired", name=name)
    kind, procs = _find_running_for_action(name)
    if kind == "ambiguous":
        return _err(lang, "ambiguous_name", name=name, candidates=", ".join(s.name for s in procs))
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
    if not info and inst_mod.get_instance(name) is not None:
        return _stop_instance(name, lang)
    if not info:
        return _err(lang, "undefined", name=name)
    if info["state"] == "closed":
        return _err(lang, "already_closed", name=name)
    if info["state"] == "retired":
        return _err(lang, "retired_needs_reactivate", name=name)
    # 2026-09-14 KRİTİK FIX: eskiden `_find_running` (base-fallback) kullanıyordu
    # — bu isim base'i AYNI olan BAMBAŞKA canlı bir session'ı da (ör. tarih+
    # çakışma suffix'li bir "aynı isimde YENİ session") yakalayıp onu da
    # öldürüyordu (canlı olay: "cops" kapatılırken "cops20260914_1" da gitti).
    kind, procs = _find_running_for_action(name)
    if kind == "ambiguous":
        return _err(lang, "ambiguous_name", name=name, candidates=", ".join(s.name for s in procs))
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
    """Wrap-up mesajını CANLI session'a enjekte eder — py/cops handover'ın TEK-session
    web karşılığı. kill/respawn YOK.

    2026-09-04 REWRITE (kullanıcı: "ho için ama fazladan bir ekran açıyorsun...
    sadece ho gonder yeter") — `_compact()`'in AYNI turdaki rewrite'ıyla AYNI
    mekanizma+gerekçe (bkz. o docstring + `handover.py`'nin modül docstring'i,
    ikisi de canlı doğrulandı). needs_ho/batch YOK (kullanıcı elle, bilerek
    tetikliyor) — sadece mesajı gönder. Roster GEREKMEZ — kayıtlı değilse proc
    `_find_running`'den bulunur. guard_lock/kill_settle/proc-presence-doğrulama'nın
    HİÇBİRİ kalmadı — hepsi kill-ile-respawn arası bir pencereyi/riski korumak
    içindi, session hiç ölmediği için o pencere yok.

    Aynı gün ikinci bir istek eklendi: "handover komutu öncesi model sonnet'e
    ve sonrası eski modele" — `handover.py`'nin `handover_faz1()`'iyle AYNI
    mantık/kod yolu (`provider.handover_model_downgrade`/`apply_live_model_switch`).

    2026-09-11 GÜNCELLEME: restore ("sonrası eski modele") adımı KALDIRILDI —
    bkz. `handover.py`'nin `handover_faz1()` içindeki 2026-09-11 yorumu. Kök
    sebep: `/model <ad>` session-scope değil, claude CLI'nin GLOBAL varsayılan
    modelini de değiştiriyor ("saved as your default for new sessions") — bir
    fable/opus session'ı restore etmek fleet'in varsayılanını (sonnet olması
    gerekirken) sessizce o modele kaydırıyordu. Artık sadece downgrade (ucuz
    modele geçiş) yapılıyor; session bir sonraki restart'ta `--model` (global'i
    kirletmeyen spawn-time yol) ile kendi gerçek modeline dönüyor.
    """
    kind, procs = _find_running_for_action(name)
    if kind == "none":
        return _err(lang, "not_running", name=name)
    if kind == "ambiguous":
        return _err(lang, "ambiguous_name", name=name, candidates=", ".join(s.name for s in procs))
    if not is_tmux_backed(procs[0].pid):
        return _err(lang, "not_tmux_backed", name=name)
    provider = get_provider(procs[0].cli)
    message = HANDOVER_MSG_DEFAULT_EN if lang == "en" else HANDOVER_MSG_DEFAULT
    diag_log("handover_start", name=name)

    downgrade = provider.handover_model_downgrade(procs[0].model or "")
    if downgrade:
        provider.apply_live_model_switch(name, downgrade)

    sent = tmux_send_keys(name, message, settle_delay=provider.input_settle_delay())

    if not sent:
        diag_log("handover_send_failed", name=name)
        return _err(lang, "handover_send_failed", name=name)
    diag_log("handover_done", name=name)
    return {"ok": True}


# Canlı session'a enjekte edilen compact komutunun tamamlanmasını (jsonl'e yeni
# bir isCompactSummary düşmesini) en fazla bu kadar bekle — sınırsız uzayıp
# panelin "bitti" haberini sonsuza kadar geciktirmesin. bash cmd_compact'ın
# 300s'inden daha kısa (2026-09-02); 2026-09-04 rewrite'ından sonra da aynı
# değer korundu (busy bir session'daki /compact KUYRUĞA girip mevcut turn
# bitene kadar bekleyebilir — canlı doğrulandı, bkz. `_compact()` docstring'i).
COMPACT_TIMEOUT_SECONDS = 180.0
COMPACT_POLL_INTERVAL_SECONDS = 2.0


def _count_compact_summaries(jsonl: Path) -> int:
    """jsonl'deki `"isCompactSummary":true` girdi sayısı — `_compact()`'in
    tamamlanma sinyali (TUI'nin dönen/kırılgan spinner metnini parse etmek
    yerine yapısal bir dosya-içi işaret, bkz. `_compact()` docstring'i)."""
    try:
        return jsonl.read_text(encoding="utf-8", errors="ignore").count('"isCompactSummary":true')
    except OSError:
        return 0


def _compact(name: str, lang: str = "tr") -> dict:
    """`provider.compact_command()`'ı (bugün sadece claude'un `/compact`'ı) CANLI
    session'a `tmux_send_keys` ile enjekte eder — kill/respawn YOK.

    2026-09-04 REWRITE (kullanıcı: "artık tmux ile çalışıyoruz, kapatmadan
    compact olur gibi geliyor" — throwaway test session'larında CANLI
    doğrulandı, iki senaryo). Eski mekanizmanın (kill + headless `-p
    '/compact'` + resume, 2026-09-02) iki gerekçesi de artık geçersiz:
      (a) "aynı jsonl'e eşzamanlı iki process yazmasın diye kill şart"
          ([[claude-2183-conversation-truncation]] sınıfı risk) — ama
          `tmux_send_keys` AYRI bir process başlatmıyor, insan gibi AYNI canlı
          process'in pty'sine tuş basıyor; o risk sınıfı hiç yok.
      (b) "CLI-argümanı bir ilk mesajın slash-command mi düz metin mi
          işlendiği doğrulanmamıştı" — ama panelin "mesaj gönder" özelliği
          (Terminal view) ZATEN aynı `tmux_send_keys` yolunu kullanıyor,
          insan input'undan ayırt edilemez; slash-command olarak doğru
          işlendiği canlı doğrulandı.
    Canlı doğrulanan 2 senaryo (throwaway `compacttest0904`/`busycompact0904`,
    gerçek fleet'e dokunulmadan, iş bitince kill edildi):
      1. IDLE session'a enjekte edilince direkt çalışıyor ("⎿ Compacted").
      2. BUSY (bir turn ortasında) session'a enjekte edilince CLI onu
         OTOMATİK KUYRUĞA ALIYOR ("Press up to edit queued messages") —
         mevcut işi kesmiyor/bozmuyor, iş bitince kendiliğinden işleniyor.
         (Bu yüzden `COMPACT_TIMEOUT_SECONDS` cömert tutuldu — kuyrukta
         beklerken mevcut turn'ün süresi de bu pencereye dahil.)

    Kill/respawn gitmesiyle `guard_lock`'a da gerek KALMADI — `guard_lock`'un
    TEK amacı kill-ile-respawn arası "session hiç yok" penceresinde guard
    cron'un araya girip dup açmasını önlemekti (bkz. eski implementasyonun
    docstring'i); artık session hiç ölmüyor, öyle bir pencere yok. Pencere de
    HİÇ kapanmıyor/açılmıyor (2026-09-04'ün asıl sorusu tam buydu — compact
    için cevap: artık hayır).

    Sadece `provider.compact_command()` destekleyenler kullanabilir — bugün
    sadece `claude`. `resolve_resume_id`'nin claude-özel `find_latest_jsonl`'a
    dayanması da zaten aynı sınırlamayı taşıyor; başka bir provider gerçekten
    compact kazanırsa (kendi tmux-injection sözdizimiyle) O ZAMAN genellenir.
    """
    kind, procs = _find_running_for_action(name)
    if kind == "none":
        return _err(lang, "not_running", name=name)
    if kind == "ambiguous":
        return _err(lang, "ambiguous_name", name=name, candidates=", ".join(s.name for s in procs))
    fleet = _fleet_status()
    info = fleet.get(name)
    chosen_cli = info["cli"] if info else procs[0].cli
    provider = get_provider(chosen_cli)
    command = provider.compact_command()
    if command is None:
        return _err(lang, "compact_unsupported_cli", name=name)
    cwd = info["cwd"] if info else procs[0].cwd

    # `find_latest_jsonl(cwd)` (mtime tahmini) DEĞİL: aynı cwd'yi paylaşan
    # başka bir session varken yanlış dosyayı izlemeye başlayıp 180s timeout'a
    # düşen COMPACT HATASI buradaydı (2026-09-14 fix, bkz. TODO.md). Bilinen
    # sid varsa `jsonl_path_for` TAM o dosyayı hedefler, yoksa aynı mtime
    # fallback'e düşer (davranış fresh/--new session'lar için değişmedi).
    jsonl = jsonl_path_for(cwd, procs[0].sid)
    if jsonl is None:
        diag_log("compact_no_jsonl", name=name)
        return _err(lang, "compact_no_jsonl", name=name)
    baseline = _count_compact_summaries(jsonl)

    diag_log("compact_start", name=name)
    if not tmux_send_keys(name, command, settle_delay=provider.input_settle_delay()):
        diag_log("compact_send_failed", name=name)
        return _err(lang, "compact_send_failed", name=name)

    deadline = time.monotonic() + COMPACT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(COMPACT_POLL_INTERVAL_SECONDS)
        if _count_compact_summaries(jsonl) > baseline:
            diag_log("compact_done", name=name)
            return {"ok": True}
    diag_log("compact_timeout", name=name)
    return _err(lang, "compact_timeout", name=name, timeout=COMPACT_TIMEOUT_SECONDS)


# `/usage`'ın çıktısı jsonl'e YAZILMIYOR (account/billing meta-verisi, bir
# konuşma turu DEĞİL) — `_compact()`'in yapısal "isCompactSummary" imzasının
# muadili yok, o yüzden burada sabit bir bekleme + pane-capture yeterli
# (`TerminalView`'in kendi 200ms poll'undan çok daha seyrek çağrılan, kullanıcı
# Ayarlar>Kullanım sekmesini AÇTIĞINDA tetiklenen bir aksiyon, sürekli poll
# EDİLMİYOR — bkz. `_usage_all()`'ın çağrıldığı yer).
USAGE_SETTLE_SECONDS = 3.0


def _usage_for_session(s, provider) -> dict:
    """Tek bir CANLI session'a `usage_command()`'ı enjekte edip sonucu
    parse eder. `provider.usage_command()`'ın None DÖNMEDİĞİ (çağıran taraf
    zaten kontrol etmiş) durumda çağrılır."""
    command = provider.usage_command()
    if not tmux_send_keys(s.name, command, settle_delay=provider.input_settle_delay()):
        return {"available": False, "reason": "send_failed"}
    time.sleep(USAGE_SETTLE_SECONDS)
    text = strip_ansi(tmux_capture(s.name, lines=100) or "")
    entries = provider.parse_usage_text(text)
    if provider.usage_needs_dismiss():
        tmux_send_special_key(s.name, "Escape")
    if not entries:
        return {"available": False, "reason": "parse_failed", "checked_via": s.name}
    return {"available": True, "checked_via": s.name, "entries": entries}


def _usage_all() -> dict:
    """Ayarlar>Kullanım sekmesi için — HER provider'ı sırayla kontrol eder.

    Kapsam bilerek "hesap" seviyesinde: session-BAZLI bir aksiyon değil (bir
    `name` almıyor), bir provider için ŞU AN çalışan İLK tmux-backed session
    üzerinden sorar (kullanım/kota o CLI'nın hesabına ait, hangi session
    olduğu önemsiz). O provider'ın hiç çalışan session'ı yoksa şu an
    kontrol EDİLEMEZ (yeni bir session açmak sırf kontrol için gereksiz/
    müdahaleci olurdu) — `available:false, reason:"no_running_session"`.

    `usage_command()` None dönen provider'lar (2026-09-13 canlı doğrulandı:
    agy, codex — ikisinde de gerçek bir mekanizma BULUNAMADI, icat
    edilmedi) `supported:false` ile döner, `shell` zaten `PROVIDERS`'ta var
    ama `has_conversation()==False` olduğundan burada da anlamsız — yine de
    listelenir (`supported:false`, tutarlılık için, "gizlice atlanan" bir
    provider olmasın diye) `if cli=="shell"` YOK, sadece `usage_command()`
    None dönüyor olması yeterli ayrım."""
    running = find_sessions(measure_cpu=False)
    out: Dict[str, dict] = {}
    for cli_name, provider in PROVIDERS.items():
        command = provider.usage_command()
        if command is None:
            out[cli_name] = {"supported": False}
            continue
        raw_candidates = [s for s in running if s.cli == cli_name and is_tmux_backed(s.pid)]
        # busy/masked adaylar KESİNLİKLE elenir (2026-09-14 fix — KRİTİK
        # OPERASYONEL RİSK, bkz. TODO.md): eskiden bu filtre yoktu, bir turn
        # işleyen (`_is_busy_cached`==True) ya da sudo/parola bekleyen
        # (`pane_is_masked_input`==True) session'a `/usage` enjekte edilip 3sn
        # sonra Escape gönderilebiliyordu — Escape çalışan bir görevi ANINDA
        # kesip iptal ediyor, masked'a enjekte edilen `/usage` metni de parola
        # prompt'una karışıyordu. `_is_busy_cached`'in `None` (bilinmiyor)
        # dönüşü BİLEREK eleme kapsamı DIŞINDA — needs_ho/client_count'un aynı
        # "bilinmiyor ≠ kesin risk" sözleşmesi, tamamen ölçülemeyen bir CLI'da
        # (busy_status_pattern tanımsız) hiçbir aday kalmamasını önler.
        candidates = [s for s in raw_candidates if not _is_busy_cached(s) and not pane_is_masked_input(s.name)]
        if not candidates:
            reason = "all_sessions_busy" if raw_candidates else "no_running_session"
            out[cli_name] = {"supported": True, "available": False, "reason": reason}
            continue
        # Birden fazla aday varsa, kimsenin İZLEMEDİĞİ birini TERCİH et
        # (`tmux_client_count()==0`) — canlı doğrulandı (2026-09-13, bu
        # fonksiyonun İLK sürümü rastgele bir aday seçiyordu ve GERÇEKTEN
        # ATTACHED bir fleet session'ına `/usage` enjekte edip ekranını anlık
        # değiştirdi, sonra Escape'le geri döndü — veri kaybı YOK ama görünür
        # bir kesinti oldu). Ölçülemeyen (`None`) "izleniyor olabilir" gibi
        # TEDBİRLİ ele alınır, "kesin boş" (0) DEĞİLDİR — sadece kesin-boş
        # bilinenler öne alınır.
        candidates.sort(key=lambda s: 0 if tmux_client_count(s.name) == 0 else 1)
        out[cli_name] = {"supported": True, **_usage_for_session(candidates[0], provider)}
    return {"ok": True, "providers": out}


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
    kind, procs = _find_running_for_action(old_name)
    if kind == "none":
        return _err(lang, "not_running", name=old_name)
    if kind == "ambiguous":
        return _err(lang, "ambiguous_name", name=old_name, candidates=", ".join(s.name for s in procs))
    if new_name != old_name and new_name in _all_known_names():
        return _err(lang, "name_in_use", new_name=new_name)
    cwd = procs[0].cwd
    # cli EĞİLMEZ/override edilmez — devralınan proc'un kimliği zaten hangi provider'ın
    # tanıdığıysa odur (bir claude proc'u "agy olarak devral" diye bir şey yok).
    chosen_cli = procs[0].cli
    provider = get_provider(chosen_cli)
    chosen_model = model.strip() or procs[0].model or default_model_for(provider)
    chosen_mode = permission_mode.strip() or provider.permission_modes()[0]
    chosen_effort = effort.strip() or provider.effort_levels()[-1]
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
                permission_mode=chosen_mode,
                effort=chosen_effort,
                force_new=False,
                cli=chosen_cli,
            )
            reopened = _wait_stable(new_name, timeout=HANDOVER_PROC_WAIT_SECONDS)
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    if not reopened:
        return _err(lang, "adopt_reopen_failed", old_name=old_name, new_name=new_name, kind=kind)
    fleet = _fleet_status()
    if new_name not in fleet and inst_mod.get_instance(new_name) is None:
        bp_cwds = _blueprint_cwds(fleet)
        bp = inst_mod.infer_blueprint(new_name, cwd, bp_cwds) if inst_mod.AUTO_NAME_RE.match(new_name) else None
        if bp and os.path.normpath(bp_cwds[bp]) == os.path.normpath(cwd):
            inst_mod.record_instance(new_name, blueprint=bp, cwd=cwd, cli=chosen_cli, model=chosen_model,
                                     permission_mode=chosen_mode, effort=chosen_effort, origin="adopt")
        else:
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


# ══ Fleet snapshot (TODO.md 2026-09-16) ═════════════════════════════════════
# Kullanıcı: "last running snapshot gibi bisi olmali... once save snapshot
# olur... makine baslayinca resume snapshot denir hepsini resume eder" —
# guard kasıtlı kapalı ([[feedback-manual-fleet-control]]) olduğu için reboot
# sonrası fleet'i geri açmak TAMAMEN kullanıcı-tetiklemeli 3 adım (kaydet →
# görüntüle → geri-yükle), [[reboot-recovery]]'nin otomatik jsonl-resume
# mekanizmasından AYRI. 2026-09-17 netleştirmeleri (kullanıcı): (1) her session
# kaydedildiği ANDAKİ GERÇEK model/permission-mode/effort/cli ile geri
# açılmalı — roster.tsv'nin "bir sonraki başlatmada kullanılacak" varsayılanı
# DEĞİL, `find_sessions()`'ın canlı proc cmdline'ından çıkardığı GERÇEK değer
# (`Session.model`/`.permission_mode`/`.effort` zaten bunu okur, bkz.
# discovery.py/providers/*.extract_info) — bu yüzden snapshot roster'a hiç
# bakmadan doğrudan bu alanları saklıyor. (2) pencereler varsayılan AÇIK,
# `hidden=True` istenirse tmux-arkaplanda (spawn_session'ın `hidden` param'ı,
# 2026-09-17) — sonradan normal "pencere aç" (`_open_window`) ile telafi
# edilebilir.


def _snapshot_save(lang: str = "tr") -> dict:
    """Şu an çalışan TÜM session'ları (registered olsun olmasın — "çalışanları
    kaydet" literal) last_snapshot.json'a yaz. Hiç canlı session yoksa da boş
    bir snapshot kaydedilir (kullanıcı bilerek "her şeyi kapattım" durumunu da
    kaydedebilmeli — burada bir hata/engel yok)."""
    live = find_sessions(measure_cpu=False)
    entries = [
        {"name": s.name, "cwd": s.cwd, "model": s.model, "permission_mode": s.permission_mode,
         "effort": s.effort, "cli": s.cli}
        for s in live
    ]
    data = save_snapshot(entries)
    return {"ok": True, "saved_at": data["saved_at"], "count": len(entries)}


def _snapshot_resume(hidden: bool = False, lang: str = "tr") -> dict:
    """Kaydedilmiş snapshot'taki her isim için: zaten çalışıyorsa atla; blueprint
    değilse ve instance kaydında da yoksa tarihli/türev isimleri instance olarak
    kaydet (roster'a YAZMA), diğerlerini `_register_project` ile blueprint olarak
    ekle; kapalı/emekli blueprint'i aktive et; sonra snapshot'ın kendi (kayıt
    anındaki GERÇEK) model/permission_mode/effort/cli alanlarıyla `_start` eder —
    [[add-session-to-fleet]]'in kanıtlanmış deseni. `_run_layout` gibi (aynı "N
    session için tek POST'ta sırayla işle" deseni) senkron — her `_start` zaten
    kendi `_wait_stable`'ıyla doğal olarak aralanır, ayrı bir throttle eklemeye
    gerek yok."""
    snap = load_snapshot()
    entries = snap.get("sessions") or []
    if not entries:
        return _err(lang, "no_snapshot")
    fleet = _fleet_status()
    live_names = {s.name for s in find_sessions(measure_cpu=False)}
    results = []
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        if name in live_names:
            results.append({"name": name, "status": "already_running"})
            continue
        cwd = str(entry.get("cwd") or "")
        cli = str(entry.get("cli") or "")
        model = str(entry.get("model") or "")
        info = fleet.get(name)
        if info is None and inst_mod.get_instance(name) is None:
            derived = inst_mod.DERIVED_NAME_RE.match(name)
            if derived:
                bp = None if derived.group(1) == inst_mod.DIAG_PREFIX else \
                    inst_mod.infer_blueprint(name, cwd, _blueprint_cwds(fleet))
                inst_mod.record_instance(
                    name, blueprint=bp, cwd=cwd, cli=cli if cli in PROVIDERS else DEFAULT_CLI,
                    model=model, permission_mode=str(entry.get("permission_mode") or ""),
                    effort=str(entry.get("effort") or ""), origin="snapshot")
            else:
                reg = _register_project(name, cwd=cwd, model=model, cli=cli, lang=lang)
                if not reg.get("ok"):
                    results.append({"name": name, "status": "failed", "error": reg.get("error")})
                    continue
        elif info is not None and info["state"] != "active":
            _toggle_comment(MODELS_TSV, name, want_active=True)
            _toggle_comment(ROSTER_TSV, name, want_active=True)
        r = _start(
            name,
            model=model,
            permission_mode=str(entry.get("permission_mode") or ""),
            effort=str(entry.get("effort") or ""),
            cli=cli,
            hidden=hidden,
            lang=lang,
        )
        if r.get("ok"):
            results.append({"name": name, "status": "started"})
        else:
            results.append({"name": name, "status": "failed", "error": r.get("error")})
    return {
        "ok": True,
        "results": results,
        "started": sum(1 for r in results if r["status"] == "started"),
        "already_running": sum(1 for r in results if r["status"] == "already_running"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
    }


def _instances_list() -> dict:
    """Geçmiş sekmesi: tüm instance kayıtları + şu an çalışıp çalışmadığı, en yeni önce."""
    live = {s.name for s in find_sessions(measure_cpu=False)}
    items = [dict(rec, name=name, running=name in live, host=LOCAL_HOST_NAME)
             for name, rec in inst_mod.load_instances().items() if not rec.get("forgotten")]
    items.sort(key=lambda r: r.get("last_started_at") or r.get("created_at") or 0, reverse=True)
    return {"ok": True, "instances": items}


def _instance_forget(name: str, lang: str = "tr") -> dict:
    """Geçmiş'ten gizler (isim rezerve kalır); konuşma geçmişine (jsonl vb.) DOKUNMAZ."""
    rec = inst_mod.get_instance(name)
    if rec is None or rec.get("forgotten"):
        return _err(lang, "unknown_instance", name=name)
    if any(s.name == name for s in find_sessions(measure_cpu=False)):
        return _err(lang, "forget_running", name=name)
    inst_mod.forget_instance(name)
    return {"ok": True}


# ══ OpenAI-uyumlu katman (`/v1/*`) ══════════════════════════════════════════
# TOBEDECIDED #21 (2026-09-09, kullanıcı: "insanlar bizim apiye değilde open
# apiye alılıklar. boylece kendi max modelimizi openai ye uyumlu çalıştırma
# imkanı da") — OpenAI'nin API ŞEKLİNİ konuşan hazır araçlar (LangChain, aider,
# çeşitli sohbet UI'ları, agent SDK'ları) base_url'lerini buraya çevirip
# kullanıcının KENDİ çalışan claudeops fleet session'larını backend olarak
# kullanabilsin. Native `/api/*` yüzeyi HİÇ DEĞİŞMEDİ — bu onun YANINA eklenen,
# ince bir çeviri katmanı.
#
# v1 kapsamı BİLEREK dar: sadece `POST /v1/chat/completions` + `GET /v1/models`.
# YOK (ve bugün gerekmiyor): `/v1/completions`, embeddings, streaming
# (aşağıda açıkça REDDEDİLİYOR), uzak-host proxy'si (`web_hosts`), durmuş bir
# session'ı ilk istekte otomatik başlatma. Hepsi doğal birer devam adımı —
# ilgili yerlerde tek tek not düşüldü.
#
# ⚠ TEK-KULLANICI (TOBEDECIDED#23, bkz. Kapatılmış #23): bu katman panele
# erişen HERKESİN senin çalışan session'larını (dolayısıyla altındaki
# provider hesabını) sürmesini teknik olarak KOLAYLAŞTIRIR — Anthropic dahil
# çoğu provider'ın ToS'u tek-kullanıcı hesap paylaşımını yasaklıyor olabilir.
# #21'in ship kararı bu riski BİLEREK kabul etti; token-gate zaten var olan
# tek korumadır (üstte tarif edildi) — paylaşma.

# `model` = claudeops session ADI. Ayrı bir eşleme tablosu YOK: çağıran, kendi
# çalışan session'larından hangisiyle konuşacağını OpenAI'nin `model` alanına
# adını yazarak seçer ("co", "cops20260909"...), `GET /v1/models` de o an
# uygun olanları "model" listesi olarak döndürür. Bu, katmanı kullanışlı kılan
# şeyin ta kendisi: karşıdaki "model" durağan bir ağırlık dosyası değil, saatler/
# günlerdir çalışan, kendi hafızası olan CANLI bir asistan.
V1_OWNED_BY = "claudeops"  # `/v1/models` satırlarının `owned_by`'ı (OpenAI'de "openai")

# Enjekte edilen kullanıcı mesajının yanıtlanmasını en fazla ne kadar bekleyeceği
# (ve poll aralığı) artık BURADA tutulmuyor — `turns.wait_for_reply()`'nin
# `timeout`/`poll` varsayılanları hiç override edilmeden kullanılıyor (bkz.
# `turns.TIMEOUT_SECONDS`/`turns.POLL_INTERVAL_SECONDS`'ın kendi yorumu, tek
# kaynak orası). `COMPACT_TIMEOUT_SECONDS` (yukarıda) AYRI bir sabit — o
# `_compact()`'in kendi dosya-içi sayaç beklemesi için, bu ikisiyle karışmaz.


def _v1_error(message: str, err_type: str = "invalid_request_error") -> dict:
    """OpenAI'nin hata zarfı. Bu katman claudeops'un native `{"ok": False,
    "error": ...}` şeklini KULLANMAZ: gerçek OpenAI istemcileri (openai-python,
    LangChain, aider...) gövdeyi ayrıştırırken ÖZELLİKLE `error.message`'a
    bakar — native şekil onlarda "boş/anlamsız hata" olarak görünürdü."""
    return {"error": {"message": message, "type": err_type, "code": None}}


def _v1_eligible_sessions() -> list:
    """`/v1/models`'in listelediği session'lar. Uygunluk kriteri `/v1/chat/
    completions`'ınkiyle AYNI üçlü (o, listeye değil TEK bir ada baktığı için
    aynı üçlüyü `_term_resolve` + `has_conversation()` ile uygular):

      (a) ŞU AN çalışıyor  (durmuş bir session'ı bu katman BAŞLATMAZ — v1 kapsamı
          dışı, doğal bir devam adımı: ilk istekte otomatik `_start`),
      (b) tmux-backed      (`capture-pane`/`send-keys` SADECE orada mümkün —
          eski/çıplak bir session'a ne mesaj gönderilebilir ne durumu okunabilir),
      (c) provider'ı bir konuşma sürdürüyor (`has_conversation()`) — düz `shell`
          session'ında "asistan yanıtı" diye bir şey YOKTUR, elenir.

    `if cli == "shell"` YOK: eleme provider arayüzünden geçiyor (CLAUDE.md'nin
    provider-registry disiplini)."""
    out = []
    for s in find_sessions(measure_cpu=False):
        if not is_tmux_backed(s.pid):
            continue
        if not get_provider(s.cli).has_conversation():
            continue
        out.append(s)
    return out


def _v1_models() -> dict:
    """`GET /v1/models` — uygun her session bir "model" satırı. İsme göre
    SIRALI (determinizm: aynı fleet aynı listeyi versin; `find_sessions`'ın
    proc-tarama sırası garantili değil). `created: 0` — OpenAI'de modelin
    yayın zamanı; burada karşılığı yok, uydurmak yerine sabit 0."""
    names = sorted({s.name for s in _v1_eligible_sessions()})
    return {"object": "list",
            "data": [{"id": n, "object": "model", "created": 0, "owned_by": V1_OWNED_BY} for n in names]}


def _v1_message_text(content) -> str:
    """OpenAI `content` iki şekilde gelebilir: düz string, ya da parça listesi
    ([{"type": "text", "text": ...}, ...] — çok-parçalı/vision istemciler).
    İkisi de kabul edilir; metin OLMAYAN parçalar (image_url vb.) atlanır —
    bir tmux pane'ine yazılabilecek tek şey metindir."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p["text"] for p in content
                          if isinstance(p, dict) and isinstance(p.get("text"), str))
    return ""


def _v1_last_user_text(messages: list) -> str:
    """BİLEREK "son user mesajı" — statelessness uyuşmazlığının kasıtlı çözümü.

    OpenAI'nin API'si STATELESS: istemci HER çağrıda TÜM geçmişi baştan yollar.
    claudeops session'ları tam TERSİ: pane'in içindeki CLI process'i konuşmayı
    ZATEN kendisi hatırlıyor (saatler/günlerdir çalışan tek bir konuşma). Bu
    yüzden gelen `messages` dizisinden SADECE son `"role": "user"` mesajı alınıp
    session'a yeni input olarak enjekte edilir; dizinin geri kalanı SESSİZCE YOK
    SAYILIR (o, session'ın zaten sahip olduğu varsayılan geçmiştir).

    Bu bir eksiklik/uyum kusuru DEĞİL, özelliğin ta kendisi: "zaten ısınmış,
    durum sahibi bir asistanı, stateless şekilli bir API'den adresleme". Spec'e
    harfiyen uymak (tüm geçmişi her seferinde yeniden oynatmak) hem imkânsız
    (canlı bir TUI'ye geçmiş "yüklenemez") hem de istenmeyen olurdu — session'ın
    KENDİ hafızasını her çağrıda çöpe atmak demekti."""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            return _v1_message_text(m.get("content")).strip()
    return ""


# `_v1_is_busy_now`/`_v1_wait_for_reply`'in gövdeleri 2026-09-09'da
# `turns.py`'ye TAŞINDI (`turns.is_busy_now`/`turns.wait_for_reply`) —
# TOBEDECIDED#15'in orkestrasyon motoru AYNI mekanizmaya ihtiyaç duyunca.
# Bu iki isim artık burada YOK, `_v1_chat_completion` doğrudan `turns.*`
# çağırıyor; davranış (varsayılan `stable_polls=2`, marker/cancel yok)
# BİREBİR AYNI kaldı.


def _v1_chat_completion(data) -> tuple:
    """`POST /v1/chat/completions` → (gövde, HTTP durum kodu).

    SADECE YEREL session'lar: `web_hosts`'un çoklu-makine proxy'sine BİLEREK
    bağlanmadı (v1 kapsamı) — uzak host desteği doğal bir devam adımı, burada
    yapılmadı.

    Session başına SERİLEŞTİRME YOK: aynı session'a AYNI ANDA iki istek gelirse
    (ThreadingHTTPServer istek-başına-thread) ikisi de mesajını gönderir, CLI
    ikincisini kuyruğa alır ve iki bekleme döngüsü aynı "bitti" sinyalini
    görüp AYNI metni döndürebilir. Panelin kendi "mesaj gönder" kutusu da hep
    böyleydi (aynı pane, aynı yarış) — burada da yeni bir sorun değil, sadece
    tek-çağıran varsayımı. Gerçekten paralel kullanılacaksa session başına bir
    kilit doğal devam adımı."""
    if not isinstance(data, dict):
        return _v1_error("request body must be a JSON object"), 400

    # `stream` EN BAŞTA: v1'de streaming yok ve bunu SESSİZCE yok sayıp
    # streaming-olmayan bir yanıt döndürmek en kötüsü olurdu — istemci SSE
    # chunk'ları bekleyip asılı kalır/çöker. Açık, okunabilir bir red daha iyi.
    if data.get("stream"):
        return _v1_error("streaming is not supported yet — retry with \"stream\": false "
                          "(the session's reply is returned as a single, complete message)"), 400

    model = str(data.get("model") or "").strip()
    if not model:
        return _v1_error("'model' is required — use the name of a running claudeops "
                          "session (see GET /v1/models)"), 400

    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        return _v1_error("'messages' must be a non-empty array"), 400
    user_text = _v1_last_user_text(messages)
    if not user_text:
        return _v1_error("no message with role 'user' (with non-empty text content) in 'messages'"), 400

    # `_term_resolve` AYNEN yeniden kullanılıyor (isim → tek, canlı, tmux-backed
    # Session) — session arama mantığı burada tekrar YAZILMADI. `lang="en"`:
    # OpenAI-şekilli isteğin `lang` alanı yok ve bu yüzeyin izleyicisi panelin
    # Türkçe kullanıcısı değil, İngilizce hata metni bekleyen bir SDK/araç.
    s, err = _term_resolve(model, lang="en")
    if err:
        return _v1_error(f"{err.get('error') or model}. 'model' must name a running, tmux-backed "
                          "claudeops session (see GET /v1/models)"), 404
    provider = get_provider(s.cli)
    if not provider.has_conversation():
        return _v1_error(f"'{model}' has no conversation to talk to (its CLI is a plain shell) — "
                          "see GET /v1/models for addressable sessions"), 404

    # Baseline gönderimden ÖNCE: "yeni yanıt geldi mi" sorusunun tek referansı.
    # None = bu provider'ın okunabilir bir transcript'i yok → yanıtı hiçbir zaman
    # geri okuyamayız; mesajı GÖNDERMEDEN reddet (aksi halde kullanıcının mesajı
    # session'a düşer ama çağıran timeout alır).
    baseline = provider.last_exchange(s.cwd, s.sid)
    if baseline is None:
        return _v1_error(f"'{model}' runs a CLI whose transcript can't be read back, so its reply "
                          "can't be returned over this API"), 404

    # `s.sid` bilinmiyorsa (fresh/hiç resume edilmemiş session — 2026-09-09
    # canlı bulundu: agy'nin cwd→id cache'i tam olarak bu durumda session
    # ölene kadar boş kalıyor, `baseline` yukarıda YİNE de boş bir dict olarak
    # geldiği için 404 DEĞİL sessiz bir 504'e düşüyordu) mesajı göndermeden
    # ÖNCE ucuz bir "durum" yakala — provider desteklemiyorsa (claude/codex)
    # None, davranış değişmez. `discover_live_sid()` ile eşleşen çift, bkz.
    # `_v1_wait_for_reply` docstring'i.
    live_snapshot = provider.snapshot_for_live_sid(s.cwd) if s.sid is None else None

    diag_log("v1_chat_start", name=s.name, chars=len(user_text))
    if not tmux_send_keys(s.name, user_text, settle_delay=provider.input_settle_delay()):
        diag_log("v1_chat_send_failed", name=s.name)
        return _v1_error(f"failed to deliver the message to session '{s.name}'", "server_error"), 500

    reply = turns.wait_for_reply(s, provider, baseline, live_snapshot)
    if reply is None:
        diag_log("v1_chat_timeout", name=s.name)
        return _v1_error(
            f"'{model}' did not finish a reply within {turns.TIMEOUT_SECONDS:.0f}s. The message WAS "
            "delivered and may still be processing — check the session, or read the result later.",
            "timeout_error"), 504
    diag_log("v1_chat_done", name=s.name, chars=len(reply))
    return {
        "id": "chatcmpl-" + secrets.token_hex(12),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,  # çağıranın YAZDIĞI ad (base-eşleşmede `s.name`den farklı olabilir)
        "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
        # Gerçek token sayıları burada UCUZA elde edilemiyor: sayan taraf pane'in
        # içindeki CLI ve bize o sayıyı veren bir arayüz yok. Sıfır bırakmak,
        # sahte-hassas bir tahmin uydurmaktan iyidir (istemciler alanın VARLIĞINI
        # bekler, doğruluğuna genelde bağımlı değildir).
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }, 200


def _proxy_desktop_ws(handler: "_Handler") -> None:
    """`/ws/desktop` — `remote_desktop`'un Rust daemon'ına RAW BYTE proxy.

    `web_ws.py`'nin JSON-broadcast WS'inden BİLEREK TAMAMEN AYRI bir mekanizma:
    o modül `websockets.server.ServerProtocol` ile WS FRAMING'İ Python
    tarafında anlıyor/üretiyor (JSON status diff'lemek için buna ihtiyacı
    var). Burada buna hiç gerek yok — Rust daemon zaten kendi TAM WebSocket
    sunucusu (`tungstenite::accept`); Python'un tek işi, tarayıcının ORİJİNAL
    HTTP upgrade isteğini (method/path/header'lar, zaten `BaseHTTPRequestHandler.
    parse_request()` tarafından ayrıştırılmış durumda) OLDUĞU GİBİ backend'e
    ilet, sonra iki soket arasında ham bayt pompalamaya geç. Backend'in 101
    yanıtı (ve sonrasındaki TÜM WS frame'leri — video + ileride eklenirse
    input) bu boru üzerinden DEĞİŞTİRİLMEDEN akar; tarayıcı doğrudan
    bağlanmışçasına davranır.

    Auth burada olur (bu fonksiyon `do_GET`'in `_authorized()` KONTROLÜNDEN
    GEÇMİŞ bir istek için çağrılır) — backend'in (`remote_desktop`'un Rust
    daemon'ı) token/header ayrıştırmayı hiç bilmesine gerek yok, sadece
    127.0.0.1'e bağlı, dışarıdan zaten erişilemez.

    `handler.rfile.read1()` (`handler.connection.recv()` DEĞİL) client
    tarafını okumak için — `web_ws.py`'nin kendi docstring'indeki AYNI ders:
    `rfile` handshake sırasında soketten önceden okumuş olabilir, ham
    `recv()`'e geçmek o buffer'daki baytları (erken gönderilmiş ilk WS
    frame'i gibi) sessizce kaybedebilirdi.
    """
    port = remote_desktop.current_port()
    if port is None:
        handler.send_response(503)
        handler.send_header("Content-Type", "text/plain; charset=utf-8")
        body = b"remote desktop daemon calismiyor - once /api/desktop/start"
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return

    handler.close_connection = True
    try:
        backend = socket.create_connection(("127.0.0.1", port), timeout=5.0)
    except OSError as e:
        diag_log("desktop_ws_backend_unreachable", error=str(e))
        handler.send_response(502)
        handler.end_headers()
        return

    try:
        request_lines = [f"{handler.command} {handler.path} HTTP/1.1\r\n"]
        for k, v in handler.headers.items():
            request_lines.append(f"{k}: {v}\r\n")
        request_lines.append("\r\n")
        backend.sendall("".join(request_lines).encode("iso-8859-1"))

        def pump_backend_to_client() -> None:
            try:
                while True:
                    data = backend.recv(65536)
                    if not data:
                        break
                    handler.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                try:
                    backend.shutdown(socket.SHUT_RD)
                except OSError:
                    pass

        reader = threading.Thread(target=pump_backend_to_client, daemon=True, name="desktop-ws-b2c")
        reader.start()
        try:
            while True:
                data = handler.rfile.read1(65536)
                if not data:
                    break
                backend.sendall(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            try:
                backend.shutdown(socket.SHUT_WR)
            except OSError:
                pass
        reader.join(timeout=2.0)
    finally:
        backend.close()


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
        """Token İKİ yoldan gelebilir — ikisi de AYNI `self.token`'a, AYNI
        `secrets.compare_digest` ile (sabit-zamanlı) bakar; ikinci bir auth
        mekanizması/anahtarı YOK:

          1. `?token=...` query param — panelin ve native `/api/*` yüzeyinin
             HER ZAMANKİ yolu, aynen korundu. Tarayıcı üst-seviye navigasyonu
             query taşıyabilir, header taşıyamaz — bu yol vazgeçilmez.
          2. `Authorization: Bearer <token>` header — OpenAI-uyumlu katman
             (`/v1/*`, TOBEDECIDED #21) için ŞART: gerçek OpenAI istemcileri
             (openai-python, LangChain, aider...) API anahtarını HER ZAMAN bu
             header'la yollar ve anahtarı bir URL query string'ine koyacak
             şekilde yapılandırılamazlar — bu yol olmadan katman gerçek
             istemcilerce KULLANILAMAZ olurdu. `/v1/*`'a özel değil (ayrı bir
             kod yolu açmamak için tüm istekler için geçerli), sadece oradaki
             ihtiyaçtan doğdu.

        `compare_digest` str yolunda SADECE ASCII kabul eder; ASCII olmayan bir
        aday (yanlış yapıştırılmış bir anahtar, latin-1 çözülen bir header)
        TypeError fırlatır. Bizim token'ımız her zaman hex (`secrets.token_hex`)
        yani böyle bir aday ZATEN eşleşemez — 500 yerine düz "yetkisiz" doğru
        cevap."""
        qs = parse_qs(urlparse(self.path).query)
        candidates = [(qs.get("token") or [""])[0]]
        auth = self.headers.get("Authorization") or ""
        if auth.startswith("Bearer "):
            candidates.append(auth[len("Bearer "):].strip())
        for given in candidates:
            try:
                if secrets.compare_digest(given, self.token):
                    return True
            except TypeError:
                continue
        return False

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
        settings/diag-restart-gt/snapshot-save/snapshot-resume) — bu
        route'ların do_POST dispatch'i bu helper'ı kullanır, geri kalanı
        (layout/term-input/term-key/diag-spawn-test/diag-ask gibi) düz
        `_json()` kullanmaya devam eder."""
        self._json(result, status=status)
        if result.get("ok"):
            web_ws.notify_status_changed()

    def _unauthorized(self):
        # `/v1/*` (OpenAI-uyumlu katman) HTML DEĞİL JSON almalı: bir OpenAI
        # istemcisi 401 gövdesini de `error.message` diye ayrıştırır, HTML
        # sayfası orada "boş hata"ya dönüşür. Panelin kendi 401'i (tarayıcıda
        # AÇILAN bir sayfa) aynen HTML kalıyor — kullanıcıya ne yapacağını
        # anlatan tek şey o.
        if urlparse(self.path).path.startswith("/v1/"):
            self._json(_v1_error("missing or invalid token — send it as "
                                  "'Authorization: Bearer <token>' (or ?token=...)",
                                  "invalid_request_error"), status=401)
            return
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

    def _handle_files_download(self):
        """`/api/files/download` — `_json()`/`_serve_static()`'ten AYRI: hem
        dinamik/kullanıcı-seçtiği bir yolu servis ediyor (public bundle değil,
        auth zaten `do_GET`'in başında geçildi) hem `Content-Disposition:
        attachment` taşıyor (tarayıcı sekmede AÇMAK yerine İNDİRSİN diye —
        `_serve_static`'in webui bundle'ı içindir, burada dosya adı/tipi
        keyfi). `_serve_static` gibi `read_bytes()` — büyük-dosya reddi
        `files_mod.resolve_download`'ın `MAX_DOWNLOAD_BYTES` kontrolüyle zaten
        `read_bytes()`'TEN ÖNCE yapılıyor."""
        qs = parse_qs(urlparse(self.path).query)
        name = (qs.get("name") or [""])[0].strip()
        lang = "en" if (qs.get("lang") or [""])[0] == "en" else "tr"
        fpath = (qs.get("path") or [""])[0].strip()
        host = (qs.get("host") or [LOCAL_HOST_NAME])[0].strip() or LOCAL_HOST_NAME
        if not name:
            self._json(_err(lang, "name_required"), status=400)
            return
        if not fpath:
            self._json(_err(lang, "path_required"), status=400)
            return
        if host != LOCAL_HOST_NAME:
            body, status, headers, err_msg = web_hosts.proxy_get_raw(
                web_hosts.FILE_DOWNLOAD_PATH, host, {"name": name, "lang": lang, "path": fpath}
            )
            if err_msg is not None:
                self._json({"ok": False, "error": err_msg}, status=200)
                return
            try:
                self.send_response(status)
                for hk, hv in (headers or {}).items():
                    self.send_header(hk, hv)
                self.send_header("Content-Length", str(len(body or b"")))
                self.end_headers()
                self.wfile.write(body or b"")
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                diag_log("response_write_failed", path="/api/files/download", error=str(e))
            return
        s, err = _files_resolve(name, lang)
        if err:
            self._json(err, status=404)
            return
        real, code = files_mod.resolve_download(s, fpath)
        if code:
            status = 403 if code == "forbidden" else 404
            limit_mb = files_mod.MAX_DOWNLOAD_BYTES / (1024 * 1024)
            self._json(_err(lang, f"files_{code}", name=name, limit_mb=limit_mb), status=status)
            return
        try:
            body = Path(real).read_bytes()
        except OSError as e:
            diag_log("files_download_read_failed", path=real, error=str(e))
            self._json(_err(lang, "files_not_found", name=name), status=404)
            return
        ctype, _ = mimetypes.guess_type(real)
        ctype = ctype or "application/octet-stream"
        filename = os.path.basename(real)
        # RFC 6266: ASCII fallback (tırnak/CR/LF temizlenmiş, eski tarayıcılar
        # için) + UTF-8 filename* (bu ortamda sık olan Türkçe dosya adları için
        # ŞART — salt ASCII filename= onları ya kırpardı ya bozardı).
        ascii_name = filename.replace('"', "").replace("\r", "").replace("\n", "")
        disposition = f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", disposition)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            diag_log("response_write_failed", path=urlparse(self.path).path, error=str(e))

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
        elif path == "/ws/desktop":
            # `web_ws.py`'nin JSON-broadcast WS'inden TAMAMEN AYRI bir yol —
            # burada Python WS framing'e hiç dokunmuyor, sadece raw byte
            # proxy'liyor (bkz. `_proxy_desktop_ws` docstring'i). Aynı sebep:
            # kendi response'unu (101/hata) doğrudan yazıyor.
            _proxy_desktop_ws(self)
            return
        elif path == "/ws/term":
            # `/api/term/output`'un AYNI name/lang/host çözümlemesi (satır
            # ~2568) — tek fark local/remote seçimine göre hangi `fetch_fn`'in
            # `web_ws.handle_ws_term`'e geçirileceği: `web_ws.py` local/remote
            # (ya da tier) ayrımını hiç bilmiyor (business-logic'e geri-import
            # ETMEME ilkesi, `handle_ws`'in `status_payload_fn` enjeksiyonuyla
            # aynı desen). Remote için 3 tier (2026-09-16, kullanıcı: "grpc,
            # desteklenmezse websocket, desteklenmezse poll"): `web_hosts.
            # get_tier()` "rest"se BUGÜNKÜ REST-proxy closure'ı DEĞİŞMEDEN
            # kalıyor; "ws"/"grpc"se `web_hosts.term_output_relay()` — local↔
            # remote hop'u o zaman da REST/WS/gRPC'den hangisiyse odur, burada
            # DEĞİŞEN tek şey browser↔local hop'unun HER ZAMAN push olması.
            qs = parse_qs(urlparse(self.path).query)
            name = (qs.get("name") or [""])[0].strip()
            lang = "en" if (qs.get("lang") or [""])[0] == "en" else "tr"
            host = (qs.get("host") or [LOCAL_HOST_NAME])[0].strip() or LOCAL_HOST_NAME
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            if host != LOCAL_HOST_NAME and web_hosts.get_tier(host) != "rest":
                fetch_fn = web_hosts.term_output_relay(host, name, lang)
            elif host != LOCAL_HOST_NAME:
                fetch_fn = lambda: web_hosts.proxy_get("/api/term/output", host, {"name": name, "lang": lang})[0]
            else:
                fetch_fn = lambda: _term_output(name, lang=lang)
            web_ws.handle_ws_term(self, fetch_fn)
            return
        elif path == "/api/status":
            self._json(_status_payload())
        elif path == "/v1/models":
            # OpenAI-uyumlu katman (TOBEDECIDED #21) — "model" = adreslenebilir
            # canlı session adı. Auth yukarıda ZATEN geçildi (query-param ya da
            # yeni `Authorization: Bearer` yolu, bkz. `_authorized`).
            self._json(_v1_models())
        elif path == "/api/orch/runs":
            # TOBEDECIDED#15 Phase 1 — local-only (host-routed'a eklenmedi,
            # /v1/* ile AYNI ilke), yeni-eskiye sıralı son 20 run özeti.
            self._json(web_orch.http_runs())
        elif path == "/api/orch/run":
            qs = parse_qs(urlparse(self.path).query)
            run_id = (qs.get("id") or [""])[0].strip()
            self._json(web_orch.http_run(run_id))
        elif path == "/api/hosts":
            # Settings/Hosts UI için — /api/status'un yalın "hosts" alanından
            # (badge/routing) farklı, base_url/has_token de taşıyan tam liste.
            rows = []
            for h in list_hosts_public():
                cached = web_hosts.get_cached(h["name"])
                rows.append({
                    **h,
                    "ok": cached["ok"] if cached else False,
                    "error": (cached.get("error") if cached else "not polled yet"),
                    "tier": web_hosts.get_tier(h["name"]),  # capability prober'ın son bildiği "rest"|"ws"|"grpc"
                })
            self._json({"ok": True, "hosts": rows})
        elif path == "/api/diag/log":
            self._json({"lines": diag_log_tail(30)})
        elif path == "/api/instances":
            qs = parse_qs(urlparse(self.path).query)
            lang = "en" if (qs.get("lang") or [""])[0] == "en" else "tr"
            host = (qs.get("host") or [LOCAL_HOST_NAME])[0].strip() or LOCAL_HOST_NAME
            if host != LOCAL_HOST_NAME:
                result, status = web_hosts.proxy_get(path, host, {"lang": lang})
                # Uzak host kendi kayıtlarını "local" etiketler; aksiyonlar doğru host'a gitsin.
                for item in result.get("instances") or []:
                    if isinstance(item, dict):
                        item["host"] = host
                self._json(result, status=status)
                return
            self._json(_instances_list())
        elif path == "/api/term/output":
            qs = parse_qs(urlparse(self.path).query)
            name = (qs.get("name") or [""])[0].strip()
            lang = "en" if (qs.get("lang") or [""])[0] == "en" else "tr"
            host = (qs.get("host") or [LOCAL_HOST_NAME])[0].strip() or LOCAL_HOST_NAME
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            if host != LOCAL_HOST_NAME:
                result, status = web_hosts.proxy_get(path, host, {"name": name, "lang": lang})
                self._json(result, status=status)
                return
            self._json(_term_output(name, lang=lang))
        elif path == "/api/term/chat":
            qs = parse_qs(urlparse(self.path).query)
            name = (qs.get("name") or [""])[0].strip()
            lang = "en" if (qs.get("lang") or [""])[0] == "en" else "tr"
            mode = "full" if (qs.get("mode") or [""])[0] == "full" else "last"
            host = (qs.get("host") or [LOCAL_HOST_NAME])[0].strip() or LOCAL_HOST_NAME
            try:
                since = int((qs.get("since") or ["0"])[0])
            except ValueError:
                since = 0
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            if host != LOCAL_HOST_NAME:
                result, status = web_hosts.proxy_get(
                    path, host, {"name": name, "lang": lang, "mode": mode, "since": str(since)})
                self._json(result, status=status)
                return
            self._json(_term_chat(name, lang=lang, mode=mode, since=since))
        elif path == "/api/files/list":
            qs = parse_qs(urlparse(self.path).query)
            name = (qs.get("name") or [""])[0].strip()
            lang = "en" if (qs.get("lang") or [""])[0] == "en" else "tr"
            fpath = (qs.get("path") or [""])[0].strip() or None
            host = (qs.get("host") or [LOCAL_HOST_NAME])[0].strip() or LOCAL_HOST_NAME
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            if host != LOCAL_HOST_NAME:
                q = {"name": name, "lang": lang}
                if fpath:
                    q["path"] = fpath
                result, status = web_hosts.proxy_get(path, host, q)
                self._json(result, status=status)
                return
            self._json(_files_list(name, fpath, lang=lang))
        elif path == "/api/files/read":
            qs = parse_qs(urlparse(self.path).query)
            name = (qs.get("name") or [""])[0].strip()
            lang = "en" if (qs.get("lang") or [""])[0] == "en" else "tr"
            fpath = (qs.get("path") or [""])[0].strip()
            host = (qs.get("host") or [LOCAL_HOST_NAME])[0].strip() or LOCAL_HOST_NAME
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            if not fpath:
                self._json(_err(lang, "path_required"), status=400)
                return
            if host != LOCAL_HOST_NAME:
                result, status = web_hosts.proxy_get(path, host, {"name": name, "lang": lang, "path": fpath})
                self._json(result, status=status)
                return
            self._json(_files_read(name, fpath, lang=lang))
        elif path == "/api/files/download":
            self._handle_files_download()
        else:
            if not self._serve_static(path):
                self._json({"error": "not found"}, status=404)

    def do_POST(self):
        if not self._authorized():
            self._unauthorized()
            return
        path = urlparse(self.path).path
        if path not in ("/api/start", "/api/stop", "/api/retire", "/api/reactivate",
                         "/api/new-chat", "/api/layout", "/api/register", "/api/edit", "/api/close",
                         "/api/handover", "/api/compact", "/api/adopt", "/api/term/input", "/api/term/key",
                         "/api/term/raw", "/api/term/set-mode",
                         "/api/term/open-window", "/api/settings", "/api/usage",
                         "/api/diag/spawn-test", "/api/diag/restart-gt", "/api/diag/ask",
                         "/api/desktop/start", "/api/desktop/stop", "/api/files/validate",
                         "/api/vscode/open", "/api/hosts", "/api/hosts/remove", "/api/hosts/test",
                         "/api/orch/start", "/api/orch/cancel", "/api/orch/draft", "/api/orch/result",
                         "/api/snapshot/save", "/api/snapshot/resume", "/api/instances/forget",
                         "/v1/chat/completions"):
            self._json({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            if path.startswith("/v1/"):
                # OpenAI-uyumlu katman native `ok:False` şeklini KULLANMAZ —
                # istemciler `error.message`'a bakar (bkz. `_v1_error`).
                self._json(_v1_error("request body is not valid JSON"), status=400)
                return
            # lang bilinemiyor (body hiç parse edilemedi) — iki dilde birden göster
            self._json({"ok": False, "error": "geçersiz JSON / invalid JSON"}, status=400)
            return

        # OpenAI-uyumlu katman (TOBEDECIDED #21) — host-routing bloğundan ÖNCE ve
        # ondan BAĞIMSIZ: `/v1/*` BİLEREK sadece YEREL session'lara bakar
        # (`web_hosts.HOST_ROUTED_PATHS`'a eklenmedi). Uzak-host desteği doğal bir
        # devam adımı, v1'de yapılmadı. `lang` alanı da yok — bu yüzeyin hataları
        # `_v1_error` üzerinden İngilizce (bkz. `_v1_chat_completion`).
        if path == "/v1/chat/completions":
            result, status = _v1_chat_completion(data)
            self._json(result, status=status)
            return

        # TOBEDECIDED#15 Phase 1 — `/v1/*` ile AYNI ilke: host-routing
        # bloğundan ÖNCE ve ondan BAĞIMSIZ, BİLEREK sadece YEREL session'lara
        # bakar (`web_hosts.HOST_ROUTED_PATHS`'a eklenmedi — uzak-host desteği
        # TOBEDECIDED#20, burada yapılmadı). Henüz TR/EN yerelleştirilmedi
        # (tüketen bir frontend yok, backend-only geçiş).
        if path == "/api/orch/start":
            self._json_notify(web_orch.http_start(data))
            return
        if path == "/api/orch/cancel":
            self._json_notify(web_orch.http_cancel(data))
            return
        if path == "/api/orch/draft":
            self._json_notify(web_orch.http_draft(data))
            return
        if path == "/api/orch/result":
            # Phase 3 (MCP `cops_result_push`) — `/api/orch/*`'in geri kalanıyla
            # AYNI ilke: host-routing'den ÖNCE/bağımsız, sadece yerel run'lara
            # bakar. `_json_notify` DEĞİL düz `_json`: bu bir katılımcının
            # (insan değil) arka-plan bildirimi, WS'e ayrı bir "notify" gerekmiyor
            # — `_run_turn` zaten tur bitince normal `_save_progress` yoluyla
            # `notify_status_changed()`'i tetikleyecek.
            self._json(web_orch.http_result(data))
            return

        lang = "en" if data.get("lang") == "en" else "tr"

        # Host-routing: 13 session-scoped route (bkz. web_hosts.HOST_ROUTED_PATHS) için
        # body'de host!=local varsa isteği o host'a proxy'le, aşağıdaki mevcut dispatch
        # zincirine HİÇ girme. host alanı yoksa/eskiyse (host==local) davranış birebir
        # aşağıdaki gibi devam eder — bu blok SADECE ek bir erken-çıkış, mevcut hiçbir
        # dal DEĞİŞMEDİ.
        if path in web_hosts.HOST_ROUTED_PATHS:
            host = str(data.get("host") or LOCAL_HOST_NAME).strip() or LOCAL_HOST_NAME
            if host != LOCAL_HOST_NAME:
                result, proxy_status = web_hosts.proxy_action(path, host, data)
                self._json_notify(result, status=proxy_status)
                return

        if path == "/api/diag/spawn-test":
            self._json(_diag_spawn_test(lang=lang))
            return

        if path == "/api/diag/restart-gt":
            self._json_notify(_diag_restart_gt(lang=lang))
            return

        if path == "/api/desktop/start":
            self._json_notify(remote_desktop.start())
            return

        if path == "/api/desktop/stop":
            self._json_notify(remote_desktop.stop())
            return

        if path == "/api/files/validate":
            name = (data.get("name") or "").strip()
            paths = data.get("paths") or []
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            self._json(_files_validate(name, paths, lang=lang))
            return

        if path == "/api/vscode/open":
            name = (data.get("name") or "").strip()
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            self._json(_vscode_open(name, data.get("path") or None, lang=lang))
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

        if path == "/api/usage":
            # İsim/host GEREKMEZ — hesap-seviyesinde, provider başına ilk uygun
            # çalışan session'ı kendisi bulur (bkz. `_usage_all()`'ın docstring'i).
            # Çoklu-host federasyonuna henüz BAĞLANMADI (`web_hosts.proxy_action`'ın
            # HOST_ROUTED_PATHS'ine eklenmedi) — bugün sadece LOKAL fleet'in
            # kullanımını gösterir, TODO.md'ye not düşüldü.
            self._json(_usage_all())
            return

        if path == "/api/hosts":
            self._json_notify(save_host(
                name=str(data.get("name", "")),
                base_url=str(data.get("base_url", "")),
                token=str(data.get("token", "")),
                grpc_url=str(data.get("grpc_url", "")),
                lang=lang,
            ))
            return

        if path == "/api/hosts/remove":
            self._json_notify(remove_host(str(data.get("name", "")), lang=lang))
            return

        if path == "/api/hosts/test":
            # Arka plan poller'ının 3sn'lik turunu (ya da yeni eklenmiş bir
            # host için hiç poll edilmemiş olmayı) beklemeden HEMEN test eder
            # — Hosts UI'ının "şimdi test et" düğmesi + host ekleme akışının
            # ardından çağrılır. `ThreadingHTTPServer` sayesinde bu isteğin
            # kendi thread'inde (ağ timeout'u kadar, STATUS_TIMEOUT_SECONDS)
            # bloklanması diğer istekleri/arka plan poller'ı ETKİLEMEZ.
            name = str(data.get("name", ""))
            result = web_hosts.test_now(name)
            if result is None:
                self._json(_err(lang, "unknown_host", name=name), status=400)
                return
            # `ok` burada "istek başarıyla çalıştı mı" demek, "host şu an
            # erişilebilir mi" DEĞİL (o `host_ok`) — `fetch_remote_status` hiç
            # raise ETMEDİĞİ için test HER ZAMAN "başarıyla çalışır", host'un
            # o an offline çıkması bunu başarısız bir istek yapmaz. Bu ayrım
            # önemli çünkü `_json_notify` broadcaster'ı SADECE `ok:true`
            # dönünce uyandırıyor — host online→offline geçişini de diğer
            # sekmelere anında itmek istiyoruz, sadece offline→online'ı değil.
            self._json_notify({
                "ok": True, "host_ok": result["ok"], "error": result.get("error"),
                "tier": result.get("tier"),  # test_now()'un hysteresis-BYPASS eden taze probe'u
            })
            return

        if path == "/api/snapshot/save":
            self._json_notify(_snapshot_save(lang=lang))
            return

        if path == "/api/snapshot/resume":
            self._json_notify(_snapshot_resume(hidden=bool(data.get("hidden", False)), lang=lang))
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

        if path == "/api/edit":
            self._json_notify(_edit_project(
                name=str(data.get("name", "")),
                new_name=str(data.get("new_name", "")),
                new_cwd=str(data.get("new_cwd", "")),
                new_model=str(data.get("new_model", "")),
                new_cli=str(data.get("new_cli", "")),
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

        if path == "/api/term/raw":
            name = str(data.get("name", "")).strip()
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            self._json(_term_raw(name, data=str(data.get("data", "")), lang=lang))
            return

        if path == "/api/term/set-mode":
            name = str(data.get("name", "")).strip()
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            self._json(_term_set_mode(name, target_mode=str(data.get("mode", "")), lang=lang))
            return

        if path == "/api/term/open-window":
            name = str(data.get("name", "")).strip()
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            self._json_notify(_open_window(name, lang=lang, force=bool(data.get("force", False))))
            return

        if path == "/api/instances/forget":
            name = str(data.get("name", "")).strip()
            if not name:
                self._json(_err(lang, "name_required"), status=400)
                return
            self._json_notify(_instance_forget(name, lang=lang))
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
    p.add_argument("--grpc-port", type=int, default=None,
                   help="local<->remote host köprüsü için gRPC server portu (varsayılan: --port + 1). "
                        "Bağlanamazsa (port çakışması vb.) sadece bu katman devre dışı kalır, "
                        "REST/WebSocket etkilenmez.")
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
    web_hosts.start_remote_poller()  # aynı desen — uzak host'ları arka planda poll'layan daemon thread
    web_hosts.start_capability_prober()  # aynı desen — her host için grpc/ws/rest tier'ini arka planda dener
    grpc_port = args.grpc_port if args.grpc_port is not None else args.port + 1
    grpc_server = web_grpc.start_grpc_server(grpc_port, token, _status_payload, _term_output)
    if grpc_server is not None:
        print(f"  gRPC köprüsü  →  127.0.0.1:{grpc_port} (sadece local↔remote host bağlantısı için — "
              "tarayıcı buna DEĞİL, /ws'e bağlanıyor)")
    # start_grpc_server() zaten bind hatasını KENDİSİ yutup None döner (yukarıda
    # kendi uyarısını basar) — burada AYRICA bir hata/çıkış YOK, bu katman
    # opsiyonel, `cops web`'in kendisi asla bundan etkilenmemeli.
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    url = f"http://{args.host}:{args.port}/?token={token}"
    print(f"claudeops web  →  {url}")
    print(f"  token dosyası: {TOKEN_FILE} (chmod 600)")
    print("  ⚠ Bu token'ı KİMSEYLE paylaşma — panele/API'ye erişen herkes senin CLI")
    print("    session'larını (ve arkalarındaki provider hesabını) sürebilir; çoğu")
    print("    provider'ın ToS'u tek-kullanıcı hesap paylaşımına izin vermeyebilir.")
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
