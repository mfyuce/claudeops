"""`web_ws` — `/ws` broadcaster/registry (React rewrite, dynamic-crunching-
lemon.md Sequencing step 10). Handshake spike'ın (step 3) yerini alıyor:
artık sabit-kodlu tek mesaj yok, gerçek çoklu-client `_status_payload()`
push'u var.

**Neden `websockets.server.ServerProtocol` (Sans-I/O) ve neden
`websockets.sync.server.serve()` DEĞİL**: `--tunnel` cloudflared'e TEK
`http://127.0.0.1:{port}` forward eder — REST API'nin zaten kullandığı
8765. `websockets.sync.server.serve()` KENDİ dinleme soketini açardı
(ikinci port, tünelden erişilemez). Bunun yerine Sans-I/O `ServerProtocol`'ü
`_Handler.do_GET`'in KENDİ thread'i + KENDİ soketine (`ThreadingHTTPServer`
zaten connection-başına-thread) gömüyoruz — plan'ın kararı.

**Neden `protocol.receive_data(ham_baytlar)` ile el-parse DEĞİL**:
`BaseHTTPRequestHandler` istek satırını ve header'ları `do_GET`'e gelmeden
ÖNCE kendi `parse_request()`'iyle zaten soketten okuyup tüketmiş oluyor —
o baytlar bir daha okunamaz. `ServerProtocol.receive_data()` + dahili
`parse()` bunları YENİDEN parse etmeyi bekler (ham HTTP request line'dan
başlayarak), ki elimizde o ham baytlar yok. Çözüm: zaten-parse-edilmiş
`self.headers`'tan bir `websockets.http11.Request` ELLE inşa edip
`protocol.accept()`'e direkt veriyoruz — bu `websockets`'in sansio howto
dokümanının ("framework isteği kendisi parse ediyorsa") tam senaryosu
(websockets.readthedocs.io/en/stable/howto/sansio.html).

**Neden handshake sonrası `self.rfile.read1()`/`self.wfile.write()`,
`self.connection.recv()`/`.sendall()` DEĞİL**: `self.rfile` zaten soketi
saran bir `io.BufferedReader` (`socketserver.StreamRequestHandler.setup()`
— `rbufsize=-1` → buffered). Ham soketten `recv()` ile okumaya geçmek,
handshake sırasında `rfile`'ın iç buffer'ına ÇEKİLMİŞ ama henüz bize
teslim edilmemiş baytları (client'ın erken gönderdiği ilk WS frame'i gibi)
sessizce atlayabilirdi. `read1(n)` aynı "en fazla n bayt, buffer boşsa tek
syscall'la doldur" semantiğini verir (`recv()` gibi davranır) ama önce
buffer'ı doğru şekilde tüketir. `self.wfile` zaten unbuffered
(`wbufsize=0` → `_SocketWriter`, her `.write()` doğrudan `sock.sendall()`).

Doğrulanan gerçek API (bu ortama pip'le kurulu `websockets==16.0`
kaynağından okunarak, tahmin edilmeden — bkz. `protocol.py`):
  - `websockets.server.ServerProtocol()` — sıfır-argümanla geçerli.
  - `.accept(request) -> Response` — asla raise ETMEZ, geçersiz handshake'i
    uygun 4xx/426 `Response` olarak döner.
  - `.send_response(response)` / `.data_to_send()` / `.receive_data(bytes)`
    / `.receive_eof()` / `.events_received()` — spike'taki gibi.
  - `.send_text(bytes)` — **state `OPEN` değilse `InvalidState` RAISE EDER**
    (protocol.py:333) — sessizce yutmaz, çağıran taraf state'i ÖNCEDEN
    kontrol etmek ZORUNDA (aşağıdaki `_pump_locked` bunu yapıyor).
  - `data_to_send()`/`events_received()` içeride sadece `self.writes`/
    `self.events`'i `[]`'le swap'lıyor (protocol.py:497-513) — **kendi
    içinde HİÇBİR kilitleme yok**. Yani `ServerProtocol` instance'ı thread-
    safe DEĞİL: `receive_*()`/`send_*()`/`data_to_send()`'i iki thread'den
    senkronizasyonsuz çağırmak iç state'i (aynı `self.writes` listesi vb.)
    yarışa sokar. Bu yüzden connection başına TEK `client.lock` var ve
    protokolle etkileşen HER şey (reader'ın receive+flush'ı, writer'ın
    send+flush'ı) o kilit altında.

## Registry / broadcaster tasarımı

- `_WS_REGISTRY`: bağlı client'ların `set`'i (`_REGISTRY_LOCK` korur).
  Her `_WSClient`: sınırlı kuyruk (`maxsize=2`, doluysa en-eskiyi-at —
  `_push()`), bir `threading.Event` (`closed`) ve bir `threading.Lock`
  (`lock` — yukarıdaki protokol-thread-safety notu).
- Bağlantı başına: **isteğin kendi thread'i YAZAR** (`handle_ws()`'i
  çağıran thread — `queue.get()` → `_send()` → soket yazımı), ayrıca bir
  **READER thread** spawn edilir (client'ın kapanışını/EOF'unu tespit
  etmek + gelen ping/close frame'lerin protokolün OTOMATİK ürettiği
  pong/close-ack yanıtlarını akıtmak için — bu ikincisi olmadan bir
  tarayıcının close-handshake'i sunucu tarafında hiç yanıtlanmaz).
  Reader kendi başına REGISTRY'ye dokunmaz — sadece `client.closed`'ı set
  eder; hem writer (queue.get timeout'unda kontrol eder) hem de
  `handle_ws()`'in `finally`'i bunu görüp gerçek `_unregister()`'ı YAPAR
  (registry mutasyonu tek yerden, iki thread'in yarışmasına gerek yok).
- Tek bir **broadcaster daemon thread**'i, `run()`'da BİR KEZ başlar: her
  `event.wait(timeout=2.0)` tick'inde `_WS_REGISTRY` boşsa hiçbir şey
  yapmaz (sıfır dinleyici için `_status_payload()` hesaplamaz); doluysa
  hesaplar, son gönderilen server-side snapshot'a göre diff'ler (eski
  client-side `comparableKey`/`LAST_JSON`'ın sunucu tarafı eşdeğeri — TÜM
  client'lar arasında PAYLAŞILAN tek snapshot, eskiden her sekmenin kendi
  kopyası vardı), değiştiyse push eder. ~30s'de bir hiçbir şey
  değişmemiş olsa bile yine de push eder (heartbeat/resync — bkz.
  `_HEARTBEAT_SECONDS`). Yeni bağlantılar `handle_ws()` içinde ayrıca
  kendi anlık push'unu alır (broadcaster'ın son-snapshot'ından bağımsız).
- `notify_status_changed()`: `web.py`'nin `do_POST`'undan (aksiyon
  fonksiyonlarının İÇİNDEN DEĞİL) mutasyon `ok: True` dönünce çağrılır.
  Sadece `_WAKE` event'ini set eder — broadcaster'ı UYANDIRIR, kendisi
  `_status_payload()` HESAPLAMAZ (bu iş hep broadcaster thread'inde,
  registry-boş kontrolünden SONRA olur).
"""
from __future__ import annotations

import json
import queue
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from websockets.datastructures import Headers as WSHeaders
from websockets.http11 import Request as WSRequest
from websockets.protocol import CLOSING, OPEN
from websockets.server import ServerProtocol

# Broadcaster tick — plan'ın önerdiği değer, değiştirmek için somut bir
# sebep bulunmadı. `event.wait(timeout=...)`: `notify_status_changed()`
# bir aksiyondan hemen sonra ANINDA uyandırır, bu sadece "hiç notify
# gelmese bile en geç ne kadar sonra tekrar bakarım" üst sınırı (ör. dıştan
# başlatılmış bir proc'un CPU/pid'i gibi POST'tan bağımsız değişimler).
_BROADCAST_TICK_SECONDS = 2.0

# Değişiklik olmasa bile bu kadar sürede bir yine de push et — bağlantıyı
# (özellikle cloudflared tüneli/mobil NAT üzerinden) sıcak tutan heartbeat +
# client'ın kaçırdığı bir diff varsa (olmaması gerekir, ama bedava) resync.
_HEARTBEAT_SECONDS = 30.0

# Bir connection'ın WRITER'ı (`_writer_loop`) kuyruktan en az bu sıklıkta
# uyanıp `client.closed`'a bakar — broadcaster tick'iyle aynı değer
# tesadüfen aynı ama kavramsal olarak ayrı (biri "ne zaman yeniden
# hesaplarım", öbürü "kendi reader'ım kapandı mı diye ne zaman bakarım").
_WRITER_POLL_SECONDS = 2.0

# Reader'ın bloklayan `read1()`'i bu kadar sürede bir timeout'la geri döner
# (client sessizce hiçbir şey göndermiyorsa NORMAL — tarayıcı WS client'ı
# pratikte kendiliğinden bir şey yollamaz). Salt bir timeout KAPANIŞ
# SAYILMAZ (aksi halde tamamen sağlıklı ama sessiz bağlantıları gereksiz
# yere reconnect'e zorlardık) — sadece döngünün `client.closed`'ı tekrar
# kontrol etmesi için bir uyanma noktası. Gerçek "sessiz yarı-açık TCP"
# tespiti bilinçli olarak burada YOK — plan bunu client'ın kendi 10-15s
# arka-plan poll backstop'una bırakıyor (`useStatus.ts`), sunucu tarafında
# aktif ping/TCP-keepalive taraması eklemek bu aşamanın kapsamı dışında.
_READER_IDLE_TIMEOUT_SECONDS = 30.0

_QUEUE_MAXSIZE = 2


@dataclass(eq=False)  # kimlik-bazlı eşitlik/hash ŞART: bir `set`'e girecek,
# alan-bazlı (queue/Lock/Event karşılaştırılamaz) varsayılan dataclass
# eq/hash'i burada YANLIŞ olurdu.
class _WSClient:
    protocol: ServerProtocol
    handler: Any  # `web.py._Handler` instance'ı — döngüsel import'tan kaçınmak için Any
    queue: "queue.Queue[bytes]" = field(default_factory=lambda: queue.Queue(maxsize=_QUEUE_MAXSIZE))
    closed: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)


_REGISTRY_LOCK = threading.Lock()
_WS_REGISTRY: "set[_WSClient]" = set()

_WAKE = threading.Event()


def notify_status_changed() -> None:
    """`web.py`'nin `do_POST`'u bir mutasyon `ok: True` dönünce çağırır.
    Sadece broadcaster'ı uyandırır — `_status_payload()` burada DEĞİL,
    broadcaster thread'inde (registry boşsa hiç) hesaplanır."""
    _WAKE.set()


def _register(client: _WSClient) -> None:
    with _REGISTRY_LOCK:
        _WS_REGISTRY.add(client)


def _unregister(client: _WSClient) -> None:
    with _REGISTRY_LOCK:
        _WS_REGISTRY.discard(client)


def _push(client: _WSClient, data: bytes) -> None:
    """`client.queue`'ya `data` koy; doluysa (maxsize=2) en eskiyi at, yeniyi
    koy — "her zaman en taze durumu göster" (ara adımları biriktirmenin
    hiçbir faydası yok, status her zaman TAM anlık görüntü)."""
    try:
        client.queue.put_nowait(data)
    except queue.Full:
        try:
            client.queue.get_nowait()
        except queue.Empty:
            pass
        try:
            client.queue.put_nowait(data)
        except queue.Full:
            pass  # son derece nadir yarış (aynı anda başka biri de doldurdu) — bir sonraki tick telafi eder


def _pump_locked(client: _WSClient, text_payload: Optional[bytes]) -> bool:
    """`client.lock` TUTULUYORKEN çağrılmalı. `text_payload` verilmişse yeni
    bir text frame kuyruğa alır (state OPEN değilse `InvalidState` yerine
    sessizce False döner — bkz. modül docstring'i), sonra `ServerProtocol`'ün
    biriktirdiği HER ŞEYİ (yeni frame VE/VEYA reader'ın işlediği bir
    ping/close'a otomatik üretilmiş pong/close-ack) soket'e yazar. Soket
    yazımı başarısız olursa False döner (çağıran bağlantıyı ölü saysın)."""
    try:
        if text_payload is not None:
            if client.protocol.state is not OPEN:
                return False
            client.protocol.send_text(text_payload)
        for chunk in client.protocol.data_to_send():
            if chunk == b"":  # SEND_EOF sentineli
                try:
                    client.handler.connection.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
            else:
                client.handler.wfile.write(chunk)
    except (BrokenPipeError, ConnectionResetError, OSError):
        return False
    return True


def _send(client: _WSClient, text_payload: bytes) -> bool:
    with client.lock:
        return _pump_locked(client, text_payload)


def _writer_loop(client: _WSClient) -> None:
    """`handle_ws()`'i çağıran thread'in KENDİSİ — bu bağlantının WRITER'ı.
    Kuyruktan al → `_send()` → soket. `client.closed` set edilene (reader
    kapanış tespit etti) ya da bir `_send()` başarısız olana kadar döner."""
    while not client.closed.is_set():
        try:
            item = client.queue.get(timeout=_WRITER_POLL_SECONDS)
        except queue.Empty:
            continue
        if not _send(client, item):
            return


def _reader_loop(client: _WSClient) -> None:
    """Bağımsız thread — TEK görevi client kapanışını/EOF'unu tespit edip
    `client.closed`'ı set etmek (registry temizliği `handle_ws()`'in
    `finally`'inde, tek yerden). Yol boyunca gelen frame'leri protokole
    besleyip (`receive_data`/`receive_eof`) otomatik üretilen pong/close-ack
    yanıtlarını da akıtır (`_pump_locked`) — ki bir tarayıcının close-
    handshake'i sunucu tarafında hiç yanıtsız kalmasın."""
    handler = client.handler
    try:
        handler.connection.settimeout(_READER_IDLE_TIMEOUT_SECONDS)
        while client.protocol.state in (OPEN, CLOSING) and not client.closed.is_set():
            try:
                data = handler.rfile.read1(65536)
            except socket.timeout:
                continue  # normal — client sessiz, kapanış DEĞİL
            except OSError:
                break
            with client.lock:
                if data:
                    client.protocol.receive_data(data)
                else:
                    client.protocol.receive_eof()
                client.protocol.events_received()  # içerik işlenmiyor, sadece tüket (leak önleme)
                ok = _pump_locked(client, None)
            if not ok or not data:
                break
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        client.closed.set()


def handle_ws(handler: Any, status_payload_fn: Callable[[], dict]) -> None:
    """`/ws` isteğini WebSocket'e yükselt. `handler` bir `_Handler`
    (`http.server.BaseHTTPRequestHandler`) instance'ı — `do_GET` bunu
    `_authorized()` kontrolünden GEÇMİŞ bir `/ws` isteği için çağırır
    (döngüsel import'tan kaçınmak için tip burada elle yazılmadı).
    `status_payload_fn` — genelde `web.py._status_payload` — connect anında
    tek seferlik anlık push için (aynı fonksiyon `run()`'dan
    `start_broadcaster()`'a da geçiriliyor, modül burada state TUTMUYOR).

    Handshake'i kurar, registry'ye kaydolur, bağlantı canlıyken bir reader
    thread + bu thread'in kendisi writer olarak çalışır; bağlantı kapanınca
    (registry temizliği dahil) döner.
    """
    protocol = ServerProtocol()
    request = WSRequest(path=handler.path, headers=WSHeaders(handler.headers.items()))
    response = protocol.accept(request)
    protocol.send_response(response)
    for chunk in protocol.data_to_send():
        if chunk:
            handler.wfile.write(chunk)

    # Bu soket artık ya WS-framed ya da reddedildi (kapatıldı) — iki
    # durumda da BaseHTTPRequestHandler'ın aynı bağlantıda bir sonraki HTTP
    # isteğini beklememesi gerekiyor (protocol_version artık HTTP/1.1 —
    # keep-alive varsayılan AÇIK, burada AÇIKÇA kapatmazsak framework bu
    # soketi bir sonraki "normal" HTTP isteği için tutmaya çalışırdı).
    handler.close_connection = True

    if protocol.state is not OPEN:
        # accept() reddetti (ör. tarayıcıdan doğrudan GET /ws — Upgrade
        # header'ı yok). Red yanıtı yukarıda zaten yazıldı, çıkıyoruz.
        return

    client = _WSClient(protocol=protocol, handler=handler)
    _register(client)
    reader = threading.Thread(
        target=_reader_loop, args=(client,), daemon=True, name=f"ws-reader-{id(client):x}"
    )
    reader.start()
    try:
        try:
            _send(client, _encode(status_payload_fn()))
        except Exception:
            pass  # best-effort — bir sonraki broadcaster tick'i (≤2s) zaten telafi eder
        _writer_loop(client)
    finally:
        client.closed.set()
        _unregister(client)


def _encode(payload: dict) -> bytes:
    return json.dumps({"type": "status", "data": payload}).encode("utf-8")


def _comparable(payload: dict) -> str:
    """Eski client-side `comparableKey()`'in (PAGE_HTML JS, artık silindi)
    sunucu tarafı eşdeğeri: `cpu` sürekli kıpırdar (round(1) olsa da), onu
    hariç tutmazsak "değişmedi" hiç tetiklenmez ve heartbeat'ten farksız
    hale gelirdi. `sort_keys=True`: `_status_payload()`'ın dict/list
    sırası tesadüfen değişse bile (bugün değişmiyor, ama garanti değil)
    yanlış-pozitif "değişti" üretmesin diye kanonik JSON.

    **Gerçek bug, bu aşamada bulundu+düzeltildi** (Playwright'la gerçek
    fleet'e karşı canlı test sırasında: bağlı TEK bir client, 2s'de bir
    yeni frame alıyordu — 30s heartbeat DEĞİL, sanki hiç diff yokmuş gibi):
    `payload["diag"]["web_uptime_seconds"]` (ve varsa `diag"]["gt"]
    ["uptime_seconds"]`) saniye-çözünürlüklü sayaçlar — `cpu` ile AYNI
    kategoriden bir alan (sürekli/kesintisiz değişen, "gerçekten bir şey
    değişti mi" anlamında anlamsız). Bunları da hariç tutmazsak diff HER
    tick'te "değişti" der — pratikte "her 2s'de bir zorunlu push"a
    indirgenir, ki tam olarak bu fonksiyonun var olma sebebini (ve mobil/
    kısıtlı bağlantılarda gereksiz trafiği önleme amacını) boşa çıkarır."""
    sessions = payload.get("sessions") or []
    stripped_sessions = [{k: v for k, v in s.items() if k != "cpu"} for s in sessions]
    diag = payload.get("diag") or {}
    stripped_diag = {k: v for k, v in diag.items() if k != "web_uptime_seconds"}
    gt = stripped_diag.get("gt")
    if isinstance(gt, dict):
        stripped_diag["gt"] = {k: v for k, v in gt.items() if k != "uptime_seconds"}
    comparable_payload = {**payload, "sessions": stripped_sessions, "diag": stripped_diag}
    return json.dumps(comparable_payload, sort_keys=True)


def _broadcaster_loop(status_payload_fn: Callable[[], dict]) -> None:
    last_snapshot: Optional[str] = None
    last_sent_mono = 0.0
    while True:
        _WAKE.wait(timeout=_BROADCAST_TICK_SECONDS)
        _WAKE.clear()
        with _REGISTRY_LOCK:
            clients = list(_WS_REGISTRY)
        if not clients:
            continue  # sıfır dinleyici — _status_payload() hesaplama, plan'ın kararı
        try:
            payload = status_payload_fn()
        except Exception:
            # Bir sonraki tick tekrar dener — daemon thread'i tek bir kötü
            # hesaplama (ör. TSV eşzamanlı yazımla yarışır) yüzünden
            # SONSUZA kadar öldürmeyelim (öldüyse bir daha broadcast YOK).
            continue
        snapshot = _comparable(payload)
        now = time.monotonic()
        if snapshot == last_snapshot and (now - last_sent_mono) < _HEARTBEAT_SECONDS:
            continue
        last_snapshot = snapshot
        last_sent_mono = now
        data = _encode(payload)
        for client in clients:
            _push(client, data)


_broadcaster_lock = threading.Lock()
_broadcaster_started = False


def start_broadcaster(status_payload_fn: Callable[[], dict]) -> None:
    """`run()`'dan BİR KEZ çağrılır. İkinci çağrı no-op (savunmacı — `run()`
    zaten süreç ömründe bir kez çalışır, ama ucuz bir garanti)."""
    global _broadcaster_started
    with _broadcaster_lock:
        if _broadcaster_started:
            return
        _broadcaster_started = True
    threading.Thread(
        target=_broadcaster_loop, args=(status_payload_fn,), daemon=True, name="ws-broadcaster"
    ).start()
