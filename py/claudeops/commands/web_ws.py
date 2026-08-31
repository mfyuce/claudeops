"""`web_ws` — `/ws` handshake spike (React rewrite, dynamic-crunching-lemon.md
Sequencing step 3).

Sadece: handshake + sabit-kodlu TEK test mesajı + bağlantı kapanana kadar
idle loop. Gerçek broadcaster/registry (`_status_payload()` push,
`notify_status_changed()`, çoklu-client diff) SONRAKİ aşama — burada YOK.

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
kaynağından okunarak, tahmin edilmeden):
  - `websockets.server.ServerProtocol()` — sıfır-argümanla geçerli
    (extensions/subprotocols/origins hepsi opsiyonel, None = kısıtlama yok).
  - `.accept(request) -> Response` — asla raise ETMEZ, geçersiz handshake'i
    (ör. eksik `Sec-WebSocket-Key`) uygun 4xx/426 `Response` olarak döner.
  - `.send_response(response)` — `response`'u `self.writes`'e serialize eder
    (101 ise `state` OPEN'a geçer).
  - `.data_to_send() -> list[bytes]` — yazılacak baytları POP'lar; boş
    bytestring (`b""`) `SEND_EOF` sentineli = soketin yazma tarafını
    yarı-kapat.
  - `.receive_data(bytes)` / `.receive_eof()` — gelen baytları/EOF'u besle.
  - `.events_received()` — parse edilen event'leri POP'lar (bu spike'ta
    içerik işlenmiyor, sadece dahili listenin şişmemesi için tüketiliyor).
  - `.send_text(bytes)` — DİKKAT: imzası `BytesLike` (`bytes|bytearray|
    memoryview`) bekler, `str` DEĞİL — `.encode("utf-8")` şart.
  - `.state` / `websockets.protocol.{OPEN,CLOSING,CLOSED}` — bağlantı durumu.
"""
from __future__ import annotations
import json
import socket
from typing import Any

from websockets.datastructures import Headers as WSHeaders
from websockets.http11 import Request as WSRequest
from websockets.protocol import CLOSING, OPEN
from websockets.server import ServerProtocol

# Spike-only: sızan/idle bir test bağlantısı handler thread'ini sonsuza
# kilitlemesin (ThreadingHTTPServer connection-başına-thread — kalıcı hang
# tek bir thread'i yer ama yine de temiz değil). Gerçek broadcaster
# aşamasında bu muhtemelen kalkacak / farklı yönetilecek.
_IDLE_SOCKET_TIMEOUT = 60.0

_HELLO_MESSAGE = json.dumps({"type": "status", "data": {"hello": "world"}}).encode("utf-8")


def handle_ws(handler: Any) -> None:
    """`/ws` isteğini WebSocket'e yükselt. `handler` bir `_Handler`
    (`http.server.BaseHTTPRequestHandler`) instance'ı — `do_GET` bunu
    `_authorized()` kontrolünden GEÇMİŞ bir `/ws` isteği için çağırır
    (döngüsel import'tan kaçınmak için tip burada elle yazılmadı).

    Handshake'i kurar, bir kez sabit test mesajı yollar, bağlantı kapanana
    (client close-frame göndersin/EOF/timeout) kadar idle döner. Gelen
    frame'lerin İÇERİĞİ bu aşamada işlenmiyor — sadece protokolün kendi
    otomatik davranışlarının (PING'e PONG, close-handshake echo'su) doğru
    sırayla soket üzerine akıtılması garanti ediliyor.
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
    # isteğini beklememesi gerekiyor. protocol_version hâlâ HTTP/1.0
    # (bu spike'ta değişmedi) olduğu için close_connection zaten default
    # True olurdu, ama ileride HTTP/1.1'e geçilirse sessizce kırılmasın
    # diye burada AÇIKÇA True set ediyoruz.
    handler.close_connection = True

    if protocol.state is not OPEN:
        # accept() reddetti (ör. tarayıcıdan doğrudan GET /ws — Upgrade
        # header'ı yok). Red yanıtı yukarıda zaten yazıldı, çıkıyoruz.
        return

    protocol.send_text(_HELLO_MESSAGE)
    for chunk in protocol.data_to_send():
        if chunk:
            handler.wfile.write(chunk)

    handler.connection.settimeout(_IDLE_SOCKET_TIMEOUT)
    try:
        while protocol.state is OPEN or protocol.state is CLOSING:
            try:
                data = handler.rfile.read1(65536)
            except (socket.timeout, OSError):
                break
            if data:
                protocol.receive_data(data)
            else:
                protocol.receive_eof()
            protocol.events_received()  # spike: içerik yok, sadece tüket (leak önleme)
            for chunk in protocol.data_to_send():
                if chunk == b"":  # SEND_EOF sentineli
                    try:
                        handler.connection.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                else:
                    handler.wfile.write(chunk)
            if not data:
                break
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
