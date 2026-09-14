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

Bu repo'da requests/httpx YOK — buradaki proxy HTTP çağrıları (`_http_json`/
`_http_raw`) 2026-09-14'ten beri `http.client`'ı DOĞRUDAN kullanıyor (garantili
bağlantı-kapatma için, bkz. `_http_json` docstring'i) VE (aynı gün, ikinci bir
fix turu) host başına küçük bir keep-alive HAVUZU tutuyor (bkz. `_pool_checkout`/
`_pool_checkin`) — VS Code'un aynı devtunnel relay'ine açtığı TEK kalıcı
bağlantıyı sonsuza kadar yeniden kullanmasıyla AYNI ilke, "her poll/proxy
çağrısı kendi taze TCP+TLS handshake'ini açsın" yerine; `_ensure_cloudflared()`
ise ayrıca `urllib.request` kullanıyor (binary indirme) — aynı stdlib-only
disiplin, iki farklı stdlib HTTP arayüzü.
"""
from __future__ import annotations
import http.client
import json
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from .. import hosts as hosts_mod
from ..hosts import LOCAL_HOST_NAME

# 14 session/host-scoped POST route — do_POST'un geri kalan 9 route'u
# (settings, diag/*, desktop/*, layout, files/validate, vscode/open) aggregator-
# local-only, asla proxy'lenmez (o makinenin GUI/config'ine bağlı, "hangi host"
# sorusu anlamsız).
HOST_ROUTED_PATHS = {
    "/api/start", "/api/stop", "/api/retire", "/api/reactivate", "/api/close",
    "/api/handover", "/api/compact", "/api/adopt", "/api/new-chat", "/api/register", "/api/edit",
    "/api/term/input", "/api/term/key", "/api/term/raw", "/api/term/open-window", "/api/term/set-mode",
}

# Terminal/Dosya GÖRÜNTÜLEME (GET, read-only) route'ları — POST'un aksiyon
# proxy'sinden AYRI çünkü query-string tabanlar (JSON body yok) + biri
# (files/download) JSON değil ham binary dönüyor. TODO.md'nin bilerek
# ERTELEDİĞİ parça buydu (TOBEDECIDED #16 kapanışı) — artık uygulandı.
GET_HOST_ROUTED_PATHS = {"/api/term/output", "/api/term/chat", "/api/files/list", "/api/files/read"}
FILE_DOWNLOAD_PATH = "/api/files/download"  # ayrı tutulmasının sebebi yukarıda

# Status polling sık (3sn'de bir) ve HAFİF olmalı — kısa timeout, poller
# thread'inin bir sonraki host'a hızlı geçebilmesi için de önemli.
#
# 2026-09-14 güncelleme: 4.0 → 8.0. Canlı bulgu — TAM OLARAK
# TERM_READ_TIMEOUT_SECONDS'ın altındaki 2026-09-07 notuyla AYNI sınıf sorun,
# ama BU sabit o zaman atlanmış: yuhem "gitti" göründüğü anda kullanıcının
# AYNI makineye VS Code'un KENDİ remote tunnel'ı (kalıcı/zaten-kurulu bir
# kanal, her istekte yeniden TLS handshake YAPMIYOR) üzerinden kesintisiz
# eriştiği doğrulandı — buna karşılık bu poll'un `_http_json` çağrısı HER
# 3 saniyede bir TAZE bir bağlantı/TLS handshake açıyor. Sonuç: devtunnel
# relay'inin SÜRDÜRÜLEN/zaten-açık bağlantılarda sorunu yok, YENİ bağlantı
# kurma gecikmesi ARA SIRA 4sn'yi aşıyor — servisin kendisi (claudeops-web)
# sağlıklı, sadece bu poll'un penceresi dar. Aynı anda elle yapılan bir
# `curl` (8sn'lik varsayılan timeout'la) BAŞARILI oldu, gerçek 401 + gerçek
# Microsoft devtunnel header'larıyla (`x-served-by: tunnels-prod-...`) —
# bağlantı çöktü değil, sadece bu poll'un 4sn'si bazen yetmiyordu.
# 12.0 (TERM_READ_TIMEOUT_SECONDS) kadar cömert YAPILMADI — bu poll sürekli/
# sonsuz döngüde ve (şimdilik) tek host'lu bile olsa "tek thread/sıralı"
# tasarımı gereği gerçekten ÇÖKMÜŞ bir host'ta HER turda tam timeout kadar
# beklenmesi demek; 8.0 iki ucu da dengelemeye çalışan bir orta nokta.
STATUS_TIMEOUT_SECONDS = 8.0
# Terminal/Dosya GET'leri (yukarıdaki proxy_get/proxy_get_raw) — frontend'in
# kendisi zaten 200ms'de bir dener, bu yüzden burada 4sn'lik dar pencereden
# çok daha CÖMERT olmak ucuz: bir devtunnel/VPN'in tipik geçici gecikmesini
# gereksiz "unreachable"a çevirmez, frontend'in kendi ardışık-hata sayacıyla
# (CONSECUTIVE_FAILURES_BEFORE_ERROR, TerminalView.tsx) birlikte çalışır —
# canlı rapor 2026-09-07: yuhem'in devtunnel'ı isolated blip'ler yaşıyor,
# 4sn bunları gereksiz yere "okunamadı" hatasına çeviriyordu.
TERM_READ_TIMEOUT_SECONDS = 12.0
# web.py'nin COMPACT_TIMEOUT_SECONDS=180.0 — proxy edilen bir compact isteği
# uzak tarafta TAM olarak o kadar sürebilir (busy bir session'da kuyruğa
# girip mevcut turn bitene kadar bekler); güvenli marjla üstünde.
ACTION_TIMEOUT_SECONDS = 200.0
POLL_INTERVAL_SECONDS = 3.0

_EMPTY_REMOTE: Dict[str, Any] = {
    "sessions": [], "closed": [], "retired": [], "cli_list": [], "cli_options": {}, "dups": [],
}


# Host başına küçük bir keep-alive HAVUZU — VS Code'un aynı devtunnel relay'ine
# AÇTIĞI TEK kalıcı bağlantıyı sonsuza kadar yeniden kullanmasıyla AYNI ilke.
# Yukarıdaki (2026-09-14) fix SADECE "bazen hiç kapanmıyor" bug'ını düzeltti —
# "her çağrı (poller'ın HER 3sn'lik turu + panel açıkken her terminal/action
# proxy'si) kendi taze TCP+TLS handshake'ini açıp TEK istekte kullanıp atıyor"
# hiç ele alınmamıştı (pooling YOK: requests/httpx kullanılmıyor, stdlib
# http.client'ın kendi persistent-connection desteği de kullanılmamıştı — bu
# BİLİNÇLİ bir tercih değildi, sadece hiç düşünülmemişti). Canlı kanıt
# (2026-09-14): yuhem'in "yavaş handshake"le bilinen devtunnel relay'ine karşı
# her 3 saniyede taze bir handshake açmak muhtemelen "yuhem koptu" döngüsünü
# besliyordu — VS Code aynı relay'e TEK bağlantıyla (asla yeniden handshake
# yapmadan) kesintisiz çalışabiliyorken.
#
# Havuz host+port+scheme bazlı (registry adı DEĞİL) — bir host'un base_url'i
# değişirse/host silinirse eski bucket sadece kullanılmaz kalır, temizlik
# YAPILMIYOR (birkaç idle soket, bounded by `_CONN_POOL_MAX_IDLE`, önemsiz).
_CONN_POOL_MAX_IDLE = 4
_conn_pool_lock = threading.Lock()
_conn_pool: Dict[str, List[http.client.HTTPConnection]] = {}

# Tek-uçuş (single-flight) dedup — havuzun KAPSAMADIĞI ayrı bir sorun için:
# host YAVAŞ/ÇÖKMÜŞken her deneme BAŞARISIZ olur, başarısız bir bağlantı asla
# havuza dönmez (`reusable=False`), yani her retry/poll kendi taze bağlantısını
# açmak ZORUNDA kalır — pooling bu durumda hiç yardım etmez. Canlı kanıt
# (2026-09-14, aynı gün üçüncü tur): yuhem'in devtunnel'ı gerçekten yavaşken
# (status poll "The read operation timed out" aldı) fd sayısı yine 69'a çıktı
# + `/api/term/output`'ta ~14 saniyede ~30 "Broken pipe" (frontend'in kendi
# ~200ms'lik poll'u, ÖNCEKİ istek hâlâ yuhem'den yanıt beklerken YENİ bir istek
# daha açıyor — üst üste binen onlarca eşzamanlı deneme).
#
# Bu YÜZDEN scope'u DAR tutulmalı: SADECE poll/okuma çağrıları (`fetch_remote_
# status`, `proxy_get`/`proxy_get_raw`) dedup'lanır — `proxy_action` KESİNLİKLE
# DEDUP'LANMAZ, çünkü her aksiyon çağrısı (özellikle `/api/term/input` —
# kullanıcının bastığı HER tuş) kendi başına anlamlı/tekrar-edilemez bir
# yan etki taşır; "zaten aynı URL'e bir istek uçuşta" diye onu sessizce
# atlamak bir tuş vuruşunu SESSİZCE KAYBETMEK olurdu. Poll/okuma çağrıları
# ise ZATEN idempotent (aynı endpoint'i bir sonraki tick'te tekrar soracağız)
# — bouncing hiçbir bilgi kaybettirmez, sadece gereksiz eşzamanlı denemeyi
# önler. Dedup key = TAM url (host+path+query) — `proxy_get`'in query'sinde
# `name` (session) zaten var, yani farklı session'lar birbirini ASLA
# bloklamaz, sadece AYNI endpoint'e üst üste binen tekrarlar bloklanır.
#
# `_last_good` — bounce'un KENDİSİ kullanıcıya HİÇ görünmemesi için: canlı
# ekran görüntüsüyle yakalandı (2026-09-14, aynı gün DÖRDÜNCÜ tur) —
# `TerminalView.tsx` bir `ok:false` aldığında pane'in İÇERİĞİNİ o hata
# metniyle EZİYOR ("✗ yuhem unreachable: busy: ..." pane'de gerçek terminal
# çıktısı gibi göründü). Bounce olunca hata DEĞİL, o URL'in son BAŞARILI
# sonucu döner — frontend hiçbir şeyin olmadığını, sadece bir tick'in
# atlandığını hiç fark etmez. `_http_raw`'a (files/download, tek-seferlik
# kullanıcı aksiyonu, sürekli poll'lanmıyor) BİLEREK eklenmedi — büyük
# binary body'leri belleğe süresiz cachelemek gereksiz risk.
_inflight_lock = threading.Lock()
_inflight_urls: set = set()
_last_good: Dict[str, Tuple[int, dict]] = {}


def _split_url(url: str) -> Tuple[Any, str]:
    """`_http_json()`/`_http_raw()` ortak URL ayrıştırma: `conn.request()`'in
    beklediği path(+query)'i üretir, `urlsplit` sonucunu (host/port/scheme)
    olduğu gibi döner."""
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return parsed, path


def _pool_key(parsed: Any) -> str:
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{parsed.scheme}://{parsed.hostname}:{port}"


def _pool_checkout(key: str, conn_cls: type, hostname: Optional[str], port: Optional[int],
                    timeout: float) -> Tuple[http.client.HTTPConnection, bool]:
    """Havuzda boşta bir bağlantı varsa onu (soket zaten açıksa timeout'unu BU
    çağrıya göre güncelleyerek — her çağrı STATUS/TERM_READ/ACTION'ın farklı
    bir timeout'unu taşıyabilir) döner, yoksa taze açar. İkinci dönüş değeri
    `from_pool` — havuzdaki bağlantı relay tarafından sessizce kapatılmış
    olabilir (idle timeout), bunu burada KONTROL ETMEYİZ; çağıran taraf
    `conn.request()`/`getresponse()` patlarsa SADECE `from_pool=True` iken
    taze bir bağlantıyla tek sefer retry eder (bkz. `_http_json` docstring'i)
    — taze açılmış bir bağlantının patlaması gerçek bir sorun demektir (host
    çökmüş), onu tekrar denemek sadece zaten-dolmuş bir timeout'u ikiye katlar."""
    with _conn_pool_lock:
        bucket = _conn_pool.get(key)
        conn = bucket.pop() if bucket else None
    if conn is not None:
        conn.timeout = timeout
        if conn.sock is not None:
            conn.sock.settimeout(timeout)
        return conn, True
    return conn_cls(hostname, port, timeout=timeout), False


def _pool_checkin(key: str, conn: http.client.HTTPConnection, reusable: bool) -> None:
    """`reusable=False` (istek/yanıt sırasında hata oldu) ise bağlantı ASLA
    havuza dönmez, direkt kapanır — bozuk bir soketi bir sonraki çağırana
    miras bırakmamak için. Havuz zaten `_CONN_POOL_MAX_IDLE` kadar doluysa
    fazlası da kapatılır (sınırsız idle-soket birikmesin)."""
    if reusable:
        with _conn_pool_lock:
            bucket = _conn_pool.setdefault(key, [])
            if len(bucket) < _CONN_POOL_MAX_IDLE:
                bucket.append(conn)
                return
    try:
        conn.close()
    except Exception:
        pass


def _http_json(method: str, url: str, body: Optional[dict], timeout: float, dedup: bool = False) -> Tuple[int, Optional[dict], Optional[str]]:
    """Küçük stdlib-only HTTP+JSON yardımcısı — hiçbir zaman raise ETMEZ, her
    hata (status, None, kısa okunur mesaj) olarak döner; çağıranın exception
    yakalamasına gerek kalmaz.

    2026-09-14: `urllib.request.urlopen()` YERİNE `http.client` DOĞRUDAN
    kullanılıyor — CANLI BAĞLANTI SIZINTISI fix'i. Eski `with urlopen(...)
    as resp:` deseni SADECE `urlopen()` başarıyla dönüp `resp`'i bağladığında
    bağlantıyı kapatma garantisi verir; bağlantı KURULURKEN (TCP connect/TLS
    handshake) timeout olursa `resp` hiç var olmaz, `with`in `__exit__`'i hiç
    çalışmaz, ve altındaki `except` bloğu soketi kapatmadan sadece hata
    tuple'ı döner — temizlik tamamen GC'ye kalır. Canlı kanıt: yuhem'in
    devtunnel relay IP'sine `ss -tanpo` ile 65 ESTABLISHED + 322 TIME-WAIT
    bağlantı bulundu, TÜMÜ claudeops-web'in kendi PID'inden (aynı hosta VS
    Code'un AÇIK kalan bağlantısı sadece 6) — STATUS_TIMEOUT_SECONDS'ı
    büyütmek (yukarıdaki not) belirtiyi seyreltti ama kaynağı düzeltmedi: her
    poll turunda tekrarlayan timeout'lar soket sızdırmaya devam ediyordu.
    Fix: bağlantıyı biz açıp `finally` içinde HANGİ aşama patlarsa patlasın
    (connect/send/read) `conn.close()` çağırıyoruz. Yan etki: `http.client`
    (urlopen'ın aksine) 4xx/5xx için exception FIRLATMAZ — `getresponse()`
    her zaman normal döner, bu da eski HTTPError-özel-durumunu gereksiz
    kılıyor (body zaten aynı şekilde okunuyor).

    2026-09-14 (aynı gün, ikinci tur): yukarıdaki fix bağlantıyı GÜVENLE
    kapatmayı garantiledi ama HER çağrı hâlâ kendi taze TCP+TLS handshake'ini
    açıyordu — VS Code'un AYNI relay'e TEK kalıcı bağlantıyla çalışmasının tam
    tersi. Artık `_pool_checkout`/`_pool_checkin` ile host başına küçük bir
    keep-alive havuzu kullanılıyor; havuzdaki bağlantı bayatlamışsa
    (`from_pool=True` iken patlarsa) TEK SEFER taze bir bağlantıyla retry
    edilir — taze açılmış bir bağlantının patlaması (`from_pool=False`)
    gerçek bir sorun demektir, onu tekrar denemek SADECE zaten-dolmuş bir
    timeout'u ikiye katlardı, o yüzden orada anında hata dönülür.

    `dedup=True` (bkz. `_inflight_urls` üstündeki not) — SADECE poll/okuma
    çağrıları (`fetch_remote_status`, `proxy_get`) verir, `proxy_action`
    HİÇBİR ZAMAN vermez: aynı URL'e zaten uçuşta bir istek varsa YENİ bağlantı
    hiç açılmadan anında dönülür — host yavaşken üst üste binen onlarca
    eşzamanlı deneme yerine TEK bir deneme bekleniyor olur. Bounce'ta hata
    DEĞİL o URL'in son BAŞARILI sonucu (`_last_good`) döner (varsa) — bkz.
    `_last_good` üstündeki not, çağıran/frontend bir tick'in atlandığını
    hiç fark etmemeli. Hiç önceki başarı yoksa (host'a eklendiği ANDA
    eşzamanlı ilk iki istek gibi) yine de busy hatası döner."""
    if dedup:
        with _inflight_lock:
            if url in _inflight_urls:
                cached = _last_good.get(url)
                if cached is not None:
                    return cached[0], cached[1], None
                return 0, None, "busy: an earlier request to this same endpoint is still in flight"
            _inflight_urls.add(url)
    try:
        url_parts, path = _split_url(url)
        key = _pool_key(url_parts)
        conn_cls = http.client.HTTPSConnection if url_parts.scheme == "https" else http.client.HTTPConnection
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        last_err = ""
        for _ in (1, 2):
            conn, from_pool = _pool_checkout(key, conn_cls, url_parts.hostname, url_parts.port, timeout)
            try:
                conn.request(method, path, body=data, headers=headers)
                resp = conn.getresponse()
                status = resp.status
                raw = resp.read()
            except (OSError, http.client.HTTPException) as e:
                _pool_checkin(key, conn, reusable=False)
                if from_pool:
                    last_err = str(e)
                    continue
                return 0, None, str(e)
            _pool_checkin(key, conn, reusable=True)
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return status, None, "bad response (not JSON)"
            if not isinstance(parsed, dict):
                return status, None, "bad response (not an object)"
            if dedup:
                with _inflight_lock:
                    _last_good[url] = (status, parsed)
            return status, parsed, None
        return 0, None, last_err
    finally:
        if dedup:
            with _inflight_lock:
                _inflight_urls.discard(url)


# Frontend'in `CliOptions` tipi (api/types.ts) bu 4 alanın HER cli girdisinde
# HEP var olduğunu varsayıyor — ör. `TerminalView.tsx`'in mod seçicisi hiç
# kontrolsüz `cliOpts.cyclable_modes.length` okur. Uzak host bizden eski bir
# claudeops sürümü çalıştırıyorsa (`cyclable_modes` eb5c258'de eklendi) kendi
# `/api/status`'unda bu alanı hiç döndürmez → normalize edilmeden geçirilirse
# frontend'de TypeError ile panel çöküyor (2026-09-08 canlı rapor, yuhem).
_CLI_OPTIONS_FIELDS = ("models", "permission_modes", "effort_levels", "cyclable_modes")


def _normalize_cli_options(raw: Any) -> Dict[str, Dict[str, list]]:
    """Uzak host'un ham `cli_options`'ını frontend'in her zaman beklediği
    tam şekle tamamlar — eksik/bozuk alanlar sessizce `[]` olur."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, list]] = {}
    for cli, opts in raw.items():
        opts = opts if isinstance(opts, dict) else {}
        out[cli] = {field: opts[field] if isinstance(opts.get(field), list) else [] for field in _CLI_OPTIONS_FIELDS}
    return out


def fetch_remote_status(host_record: Dict[str, str]) -> Dict[str, Any]:
    """Bir host'un `/api/status`'unu çek. Başarı/hata HER İKİ durumda da aynı
    anahtar setiyle döner (sadece `ok`/`error` farklılaşır) — çağıran
    (`merge_status`/poller) iki dalı ayrım yapmadan aynı şekilde işleyebilir."""
    name = host_record["name"]
    url = f"{host_record['base_url']}/api/status?token={host_record['token']}"
    status, parsed, err = _http_json("GET", url, None, STATUS_TIMEOUT_SECONDS, dedup=True)
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
        "cli_options": _normalize_cli_options(parsed.get("cli_options")),
        "dups": parsed.get("dups") or [],
    }


_cache_lock = threading.Lock()
_cache: Dict[str, Dict[str, Any]] = {}  # host adı -> fetch_remote_status() sonucu


def _apply_stale_while_error(prev: Optional[Dict[str, Any]], result: Dict[str, Any]) -> Dict[str, Any]:
    """Bir poll/test sonucunu cache'e yazmadan ÖNCE "stale-while-error" uygular:
    `result` başarısızsa VE öncesinde BAŞARILI bir `prev` varsa, sessions/
    closed/retired/cli_list/cli_options/dups eskisinden KORUNUR (sadece ok/
    error güncellenir) — yuhem-tarzı "isolated blip" (TOBEDECIDED #19) tek
    kötü bir pollda o host'un TÜM session satırlarını/terminal effort-mode-
    model kutularını sessizce kaybetmesin diye (2026-09-09 canlı rapor:
    "ancient-script-pipeline-fd" (yuhem) terminalinde effort/perm kutuları
    gitmişti — kök sebep TAM buydu: host'un normal blip'i sırasında
    `merge_status()`'un `data.sessions`'a eklediği satır TAMAMEN siliniyordu,
    sadece cli_options boş kalmıyordu — `TerminalView.tsx`'in `session =
    data?.sessions.find(...)` bulamayınca hem effort hem mode/perm kutusu
    BİRLİKTE kayboluyordu). Kalıcı/gerçek bir kopuşta `ok`/`error` yine de HER
    ZAMAN taze/doğru kalır (Hosts UI'ının bağlı/erişilemez rozeti hiç
    yanılmaz) — sadece session LİSTESİ bir sonraki başarılı poll'a kadar
    bayatlar. Hiç önceki başarılı cache yoksa (host hiç bağlanamadı/zaten
    başarısızdı) korunacak bir şey yok, `result` olduğu gibi kullanılır."""
    if not result["ok"] and prev is not None and prev.get("ok"):
        return {**prev, "ok": False, "error": result["error"]}
    return result


# `TerminalView.tsx`'in kendi `CONSECUTIVE_FAILURES_BEFORE_ERROR` sabiti/deseniyle
# AYNI eşik+gerekçe (yuhem'in "isolated blip"leri — TOBEDECIDED #19): tek bir
# başarısız poll'u ANINDA "bağlı değil" saymak, VS Code'un kendi (uzun ömürlü,
# tekrar-handshake gerektirmeyen) bağlantısıyla hiç kopmayan kullanıcıya karşı
# panelin rozetini gereksiz/yanıltıcı biçimde kırmızıya çeviriyordu (2026-09-09
# canlı rapor: "vscode'da hiç kopmuyorum ama UI'de yuhem hep kopmuş görünüyor").
# 3sn'lik poll periyoduyla 5 ardışık hata ~15sn'lik bir tolerans penceresi
# demek — gerçek/uzun süren bir kopuşu hâlâ doğru şekilde yakalar, sadece
# tek-seferlik blip'leri rozete hiç yansıtmaz.
CONSECUTIVE_FAILURES_BEFORE_ERROR = 5
_fail_streak: Dict[str, int] = {}  # host adı -> ardışık başarısız poll sayısı


def _record_poll_result(name: str, result: Dict[str, Any]) -> None:
    """`_apply_stale_while_error`'ın ÜSTÜNE, ardışık-hata toleransı ekler:
    eşiğin ALTINDA bir başarısızlık (önceki cache zaten `ok:true` olduğu
    sürece) `_cache`'e HİÇ yazılmaz — o tick sanki hiç olmamış gibi, önceki
    başarılı durum aynen kalır (TerminalView.tsx'in aynı isimli deseninde
    olduğu gibi, aşağıya "return" ile atlama). Eşik aşılınca (ya da hiç
    önceki başarılı cache yoksa — YENİ eklenmiş/gerçekten bozuk bir host'un
    İLK hatası ANINDA görünsün diye, orada tolerans YOK) `_apply_stale_while_
    error`'a düşer. `test_now()` de BUNU çağırır ama kendi HTTP yanıtı için
    hep `result`'ın (bu fonksiyonun değil) taze/gerçek `ok`/`error`'ını
    kullanır — kullanıcının bilerek bastığı "şimdi test et" bir blip'in
    arkasına gizlenmemeli, sadece PAYLAŞILAN arka-plan sayacını besler."""
    with _cache_lock:
        if result["ok"]:
            _fail_streak[name] = 0
            _cache[name] = result
            return
        streak = _fail_streak.get(name, 0) + 1
        _fail_streak[name] = streak
        prev = _cache.get(name)
        if streak < CONSECUTIVE_FAILURES_BEFORE_ERROR and prev is not None and prev.get("ok"):
            return
        _cache[name] = _apply_stale_while_error(prev, result)


def _poll_once() -> None:
    current = hosts_mod.load_hosts()
    current_names = {h["name"] for h in current}
    for h in current:
        result = fetch_remote_status(h)
        _record_poll_result(h["name"], result)
    # Silinmiş host'ları cache'ten temizle (merge_status zaten load_hosts()'a
    # göre iterate ediyor, bu sadece belleğin büyümemesi için).
    with _cache_lock:
        for stale in list(_cache):
            if stale not in current_names:
                del _cache[stale]
                _fail_streak.pop(stale, None)


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


def test_now(name: str) -> Optional[Dict[str, Any]]:
    """Bir host'u arka plan poller'ının bir sonraki 3sn'lik tur'unu (ya da,
    az önce eklenmiş bir host için, HİÇ poll edilmemiş olma durumunu — `ok:
    false, "not polled yet"`) beklemeden HEMEN test eder — Settings/Hosts'un
    "şimdi test et" düğmesi + host ekleme akışı bunu çağırır. `fetch_remote_status`
    ile AYNI senkron/never-raise garantisini taşır (ağ çağrısı burada, çağıran
    thread'i STATUS_TIMEOUT_SECONDS'a kadar bloklar). Sonucu `_cache`'e de yazar
    ki (a) bu çağrıdan hemen sonraki bir `merge_status()`/`/api/hosts` GET taze
    veriyi görsün, (b) arka plan poller'ının BİR SONRAKİ tur'u bunun üstüne
    yazsa bile (aynı sonucu tekrar bulacağı için) kayıp/gerileme olmaz. Host
    kayıtlı değilse `None` (çağıran "unknown host" hatası üretir). Cache
    yazımı `_record_poll_result()`'a (stale-while-error + ardışık-hata
    toleransı, arka plan poller'ıyla PAYLAŞILAN aynı state) devredilir, AMA
    dönüş değeri HER ZAMAN bu çağrının kendi taze `result`'ı — kullanıcının
    bilerek bastığı "şimdi test et" düğmesi paylaşılan toleransın arkasına
    gizlenmemeli, gerçek/anlık sonucu görmeli (sadece arka plandaki PAYLAŞILAN
    sayacı besler, kendi yanıtını yumuşatmaz)."""
    host_record = hosts_mod.get_host(name)
    if host_record is None:
        return None
    result = fetch_remote_status(host_record)
    _record_poll_result(name, result)
    return result


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


def _http_raw(url: str, timeout: float, dedup: bool = False) -> Tuple[int, Optional[bytes], Optional[Dict[str, str]], Optional[str]]:
    """`_http_json()`'ın binary-passthrough kardeşi — `/api/files/download`
    proxy'si için JSON parse ETMEDEN ham body + seçili header'ları
    (content-type, content-disposition) döner. Aynı 'hiçbir zaman raise
    etmez' disiplini + aynı garantili-kapatma fix'i + aynı keep-alive havuzu
    + aynı tek-uçuş dedup'ı (bkz. `_http_json` docstring'i, 2026-09-14
    bağlantı sızıntısı + pooling + dedup fix'leri)."""
    if dedup:
        with _inflight_lock:
            if url in _inflight_urls:
                return 0, None, None, "busy: an earlier request to this same endpoint is still in flight"
            _inflight_urls.add(url)
    try:
        url_parts, path = _split_url(url)
        key = _pool_key(url_parts)
        conn_cls = http.client.HTTPSConnection if url_parts.scheme == "https" else http.client.HTTPConnection
        last_err = ""
        for _ in (1, 2):
            conn, from_pool = _pool_checkout(key, conn_cls, url_parts.hostname, url_parts.port, timeout)
            try:
                conn.request("GET", path)
                resp = conn.getresponse()
                status = resp.status
                body = resp.read()
                headers = {k: v for k, v in resp.getheaders() if k.lower() in ("content-type", "content-disposition")}
            except (OSError, http.client.HTTPException) as e:
                _pool_checkin(key, conn, reusable=False)
                if from_pool:
                    last_err = str(e)
                    continue
                return 0, None, None, str(e)
            _pool_checkin(key, conn, reusable=True)
            return status, body, headers, None
        return 0, None, None, last_err
    finally:
        if dedup:
            with _inflight_lock:
                _inflight_urls.discard(url)


def proxy_get(path: str, host_name: str, query: Dict[str, str]) -> Tuple[Dict[str, Any], int]:
    """4 JSON GET route (`GET_HOST_ROUTED_PATHS`) için — `proxy_action()`'ın
    query-string kardeşi, aynı hata/status konvansiyonu."""
    host = hosts_mod.get_host(host_name)
    if host is None:
        return {"ok": False, "error": f"unknown host: {host_name}"}, 200
    q = {k: v for k, v in query.items() if k != "host"}
    q["token"] = host["token"]
    url = f"{host['base_url']}{path}?{urllib.parse.urlencode(q)}"
    status, parsed, err = _http_json("GET", url, None, TERM_READ_TIMEOUT_SECONDS, dedup=True)
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
    status, body, headers, err = _http_raw(url, ACTION_TIMEOUT_SECONDS, dedup=True)
    if err is not None:
        return None, 200, None, f"{host_name} unreachable: {err}"
    return body, status, headers, None
