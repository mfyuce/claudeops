"""`web_hosts` — uzak host'ları arka planda poll'layıp cache'leyen daemon +
status-merge + aksiyon-proxy katmanı.

`web_ws.py`'nin `start_broadcaster()`'ıyla BİREBİR AYNI desen (start-once,
daemon, süreç ömrü boyunca tek thread) — ama BİLEREK `_status_payload()`'ın
İÇİNDE fan-out YAPMIYORUZ: `web_ws._broadcaster_loop()` herhangi bir WS
client'ı bağlıyken her 2 saniyede bir `_status_payload()`'ı ÇAĞIRIYOR (bkz. o
dosyanın docstring'i) — fan-out'u oraya gömseydik o thread N uzak host'a
network I/O'suyla SÜREKLİ bloklanırdı. Bunun yerine ayrı bir poller thread'i
host'ları kendi ~3sn periyodunda çeker ve cache'ler; `merge_status()` SADECE
bu cache'i okur, asla network'te beklemez.

Proxy zinciri TEK hop'la sınırlı (kasıtlı, güvenlik/doğruluk gereği):
`proxy_action()` giden body'deki `host` alanını hep "local"a ZORLAR — uzak
host'un KENDİ do_POST'u asla non-local bir host görmez, dolayısıyla kendi
hosts.json'ında ne olursa olsun ikinci bir proxy hop'u asla oluşamaz. BU
ZORLAMAYI KALDIRMA — 2. hop'u yapısal olarak imkansız kılan tek şey bu.

Bu repo'da requests/httpx YOK (tek yerde zaten `urllib.request` kullanılıyor,
_ensure_cloudflared()'ın binary indirmesi) — aynı stdlib-only disiplin.
"""
from __future__ import annotations
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .. import hosts as hosts_mod
from ..hosts import LOCAL_HOST_NAME

# 13 session/host-scoped POST route — do_POST'un geri kalan 9 route'u
# (settings, diag/*, desktop/*, layout, files/validate, vscode/open) aggregator-
# local-only, asla proxy'lenmez (o makinenin GUI/config'ine bağlı, "hangi host"
# sorusu anlamsız).
HOST_ROUTED_PATHS = {
    "/api/start", "/api/stop", "/api/retire", "/api/reactivate", "/api/close",
    "/api/handover", "/api/compact", "/api/adopt", "/api/new-chat", "/api/register",
    "/api/term/input", "/api/term/key", "/api/term/open-window",
}

# Terminal/Dosya GÖRÜNTÜLEME (GET, read-only) route'ları — POST'un aksiyon
# proxy'sinden AYRI çünkü query-string tabanlar (JSON body yok) + biri
# (files/download) JSON değil ham binary dönüyor. TODO.md'nin bilerek
# ERTELEDİĞİ parça buydu (TOBEDECIDED #16 kapanışı) — artık uygulandı.
GET_HOST_ROUTED_PATHS = {"/api/term/output", "/api/term/chat", "/api/files/list", "/api/files/read"}
FILE_DOWNLOAD_PATH = "/api/files/download"  # ayrı tutulmasının sebebi yukarıda

# Status polling sık (3sn'de bir) ve HAFİF olmalı — kısa timeout.
STATUS_TIMEOUT_SECONDS = 4.0
# web.py'nin COMPACT_TIMEOUT_SECONDS=180.0 — proxy edilen bir compact isteği
# uzak tarafta TAM olarak o kadar sürebilir (busy bir session'da kuyruğa
# girip mevcut turn bitene kadar bekler); güvenli marjla üstünde.
ACTION_TIMEOUT_SECONDS = 200.0
POLL_INTERVAL_SECONDS = 3.0

_EMPTY_REMOTE: Dict[str, Any] = {
    "sessions": [], "closed": [], "retired": [], "cli_list": [], "cli_options": {}, "dups": [],
}


def _http_json(method: str, url: str, body: Optional[dict], timeout: float) -> Tuple[int, Optional[dict], Optional[str]]:
    """Küçük stdlib-only HTTP+JSON yardımcısı — hiçbir zaman raise ETMEZ, her
    hata (status, None, kısa okunur mesaj) olarak döner; çağıranın exception
    yakalamasına gerek kalmaz."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    status = 0
    raw = b""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw = resp.read()
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
            status = e.code
        except Exception:
            return e.code, None, f"http {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = e.reason if isinstance(e, urllib.error.URLError) else e
        return 0, None, str(reason)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return status, None, "bad response (not JSON)"
    if not isinstance(parsed, dict):
        return status, None, "bad response (not an object)"
    return status, parsed, None


def fetch_remote_status(host_record: Dict[str, str]) -> Dict[str, Any]:
    """Bir host'un `/api/status`'unu çek. Başarı/hata HER İKİ durumda da aynı
    anahtar setiyle döner (sadece `ok`/`error` farklılaşır) — çağıran
    (`merge_status`/poller) iki dalı ayrım yapmadan aynı şekilde işleyebilir."""
    name = host_record["name"]
    url = f"{host_record['base_url']}/api/status?token={host_record['token']}"
    status, parsed, err = _http_json("GET", url, None, STATUS_TIMEOUT_SECONDS)
    if err is not None or parsed is None:
        return {"ok": False, "error": err or f"http {status}", **_EMPTY_REMOTE}
    if "sessions" not in parsed:
        return {"ok": False, "error": "unexpected response shape", **_EMPTY_REMOTE}

    def _tag(rows: Optional[list]) -> list:
        tagged = []
        for r in (rows or []):
            r2 = dict(r)
            r2["host"] = name  # uzak tarafın kendi "local" etiketini BİZİM tarafımızdan bilinen isimle EZ
            tagged.append(r2)
        return tagged

    return {
        "ok": True,
        "error": None,
        "sessions": _tag(parsed.get("sessions")),
        "closed": _tag(parsed.get("closed")),
        "retired": _tag(parsed.get("retired")),
        "cli_list": parsed.get("cli_list") or [],
        "cli_options": parsed.get("cli_options") or {},
        "dups": parsed.get("dups") or [],
    }


_cache_lock = threading.Lock()
_cache: Dict[str, Dict[str, Any]] = {}  # host adı -> fetch_remote_status() sonucu


def _poll_once() -> None:
    current = hosts_mod.load_hosts()
    current_names = {h["name"] for h in current}
    for h in current:
        result = fetch_remote_status(h)
        with _cache_lock:
            _cache[h["name"]] = result
    # Silinmiş host'ları cache'ten temizle (merge_status zaten load_hosts()'a
    # göre iterate ediyor, bu sadece belleğin büyümemesi için).
    with _cache_lock:
        for stale in list(_cache):
            if stale not in current_names:
                del _cache[stale]


def _poller_loop() -> None:
    while True:
        try:
            _poll_once()
        except Exception:
            # web_ws._broadcaster_loop ile AYNI disiplin: tek kötü bir tur
            # (ör. hosts.json eşzamanlı yazımla yarışır) daemon'ı sonsuza
            # kadar öldürmesin — bir sonraki tick tekrar dener.
            pass
        time.sleep(POLL_INTERVAL_SECONDS)


_poller_lock = threading.Lock()
_poller_started = False


def start_remote_poller() -> None:
    """`run()`'dan BİR KEZ çağrılır (web_ws.start_broadcaster ile aynı yerden,
    aynı desen). İkinci çağrı no-op."""
    global _poller_started
    with _poller_lock:
        if _poller_started:
            return
        _poller_started = True
    threading.Thread(target=_poller_loop, daemon=True, name="host-poller").start()


def get_cached(name: str) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        c = _cache.get(name)
        return dict(c) if c is not None else None


def merge_status(local_payload: Dict[str, Any]) -> Dict[str, Any]:
    """`local_payload` zaten `_status_payload()`'ın hesapladığı, her
    sessions/closed/retired girdisine `"host": LOCAL_HOST_NAME` etiketlenmiş
    dict — burada SADECE poller cache'i okunur, asla network'e gidilmez.
    Her zaman bir `"hosts"` anahtarı ekler (kayıtlı host yoksa bile boş liste
    — frontend tipinin hep-var-olan bir alan bekleyebilmesi için)."""
    registered = hosts_mod.load_hosts()
    hosts_status: List[Dict[str, Any]] = []
    for h in registered:
        name = h["name"]
        cached = get_cached(name)
        if cached is None:
            # Henüz hiç poll edilmedi (yeni eklendi) — sessizce yok sayma,
            # frontend'in "bu host var ama henüz durum bilinmiyor" göstermesi
            # için placeholder.
            hosts_status.append({
                "name": name, "ok": False, "error": "not polled yet",
                "cli_list": [], "cli_options": {}, "dups": [],
            })
            continue
        local_payload["sessions"].extend(cached["sessions"])
        local_payload["closed"].extend(cached["closed"])
        local_payload["retired"].extend(cached["retired"])
        hosts_status.append({
            "name": name, "ok": cached["ok"], "error": cached.get("error"),
            "cli_list": cached["cli_list"], "cli_options": cached["cli_options"],
            "dups": cached["dups"],
        })
    local_payload["hosts"] = hosts_status
    return local_payload


def proxy_action(path: str, host_name: str, body: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """`path`'i `host_name`'e proxy'ler. Giden body'deki `host` hep "local"a
    zorlanır (bkz. modül docstring'i — 2. hop'u yapısal olarak imkansız kılan
    zorlama, KALDIRMA). Transport hatası → (200, ok:false) — bu codebase'in
    zaten kullandığı "aksiyon hatası = 200 + ok:false" konvansiyonuyla aynı
    (bkz. web.py'deki _err() kullanımları — sadece malformed-request'ler 400
    dönüyor, gerçek aksiyon hataları hep 200)."""
    host = hosts_mod.get_host(host_name)
    if host is None:
        return {"ok": False, "error": f"unknown host: {host_name}"}, 200
    outgoing = dict(body)
    outgoing["host"] = LOCAL_HOST_NAME
    url = f"{host['base_url']}{path}?token={host['token']}"
    status, parsed, err = _http_json("POST", url, outgoing, ACTION_TIMEOUT_SECONDS)
    if err is not None or parsed is None:
        return {"ok": False, "error": f"{host_name} unreachable: {err or f'http {status}'}"}, 200
    return parsed, status


def _http_raw(url: str, timeout: float) -> Tuple[int, Optional[bytes], Optional[Dict[str, str]], Optional[str]]:
    """`_http_json()`'ın binary-passthrough kardeşi — `/api/files/download`
    proxy'si için JSON parse ETMEDEN ham body + seçili header'ları
    (content-type, content-disposition) döner. Aynı 'hiçbir zaman raise
    etmez' disiplini."""
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            headers = {k: v for k, v in resp.getheaders() if k.lower() in ("content-type", "content-disposition")}
            return resp.status, body, headers, None
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read(), None, None
        except Exception:
            return e.code, None, None, f"http {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = e.reason if isinstance(e, urllib.error.URLError) else e
        return 0, None, None, str(reason)


def proxy_get(path: str, host_name: str, query: Dict[str, str]) -> Tuple[Dict[str, Any], int]:
    """4 JSON GET route (`GET_HOST_ROUTED_PATHS`) için — `proxy_action()`'ın
    query-string kardeşi, aynı hata/status konvansiyonu."""
    host = hosts_mod.get_host(host_name)
    if host is None:
        return {"ok": False, "error": f"unknown host: {host_name}"}, 200
    q = {k: v for k, v in query.items() if k != "host"}
    q["token"] = host["token"]
    url = f"{host['base_url']}{path}?{urllib.parse.urlencode(q)}"
    status, parsed, err = _http_json("GET", url, None, STATUS_TIMEOUT_SECONDS)
    if err is not None or parsed is None:
        return {"ok": False, "error": f"{host_name} unreachable: {err or f'http {status}'}"}, 200
    return parsed, status


def proxy_get_raw(path: str, host_name: str, query: Dict[str, str]) -> Tuple[Optional[bytes], int, Optional[Dict[str, str]], Optional[str]]:
    """`/api/files/download` için — `proxy_get()`'in binary kardeşi."""
    host = hosts_mod.get_host(host_name)
    if host is None:
        return None, 200, None, f"unknown host: {host_name}"
    q = {k: v for k, v in query.items() if k != "host"}
    q["token"] = host["token"]
    url = f"{host['base_url']}{path}?{urllib.parse.urlencode(q)}"
    status, body, headers, err = _http_raw(url, ACTION_TIMEOUT_SECONDS)
    if err is not None:
        return None, 200, None, f"{host_name} unreachable: {err}"
    return body, status, headers, None
