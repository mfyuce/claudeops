"""`web_grpc` — `host_bridge.proto`'nun sunucu+istemci tarafı. TODO.md'nin
gRPC maddesindeki karara göre kapsam DAR: sadece streaming'in gerçekten
kazandırdığı 2 operasyon (+ bir `Ping` probe RPC'si) — `StreamStatus`
(`web_hosts.py`'nin poller'ının tekrar tekrar `fetch_remote_status()`
çağırmasının yerini alır) ve `StreamTermOutput` (`web_ws._term_poll_loop`'un
REMOTE dalının yerini alır). 14 aksiyon route'u (start/stop/close/...)
BİLEREK burada YOK — tek-seferlik/kullanıcı-tetiklemeli çağrılar streaming'den
kazanmaz, REST'te kalıyorlar (`/ws/term`'ün kendisi için de aynı kapsam kararı
zaten verilmişti).

`web_ws.py`'nin `handle_ws(handler, status_payload_fn)` DI deseniyle AYNI ilke:
bu modül `web.py`'nin iş mantığına ASLA geri-import ETMEZ — `run()`
`_status_payload`/`_term_output`'u enjekte eder.

**Sunucu:** `grpc.server(ThreadPoolExecutor)` — `grpc.aio` DEĞİL, bu kod
tabanının her yerdeki all-threading tarzıyla (asyncio hiçbir yerde
kullanılmıyor) tutarlı. Loopback bind (`127.0.0.1`) — TLS sonlandırma zaten
tünelin işi, mevcut HTTP server'ın duruşuyla aynı. Başlatma **asla fatal
DEĞİL** — bind başarısız olursa (port çakışması vb.) `None` döner, `cops web`
REST/WS'le sorunsuz çalışmaya devam eder; bu katman KATIKSIZ opsiyonel bir
iyileştirme.

**Auth:** mesaj alanı DEĞİL, call metadata'sında `authorization: Bearer
<token>` — REST'in `_authorized()`'ının zaten desteklediği `Authorization:
Bearer` yolunun gRPC-native eşdeğeri, AYNI token/AYNI `secrets.compare_digest`
sabit-zamanlı kontrolü. `_AuthInterceptor` reddedilen çağrıyı gerçek servicer'a
HİÇ sokmadan `UNAUTHENTICATED` ile abort eder — unary (`Ping`) ve streaming
(`StreamStatus`/`StreamTermOutput`) FARKLI handler tipleri gerektirdiği için,
gerçek handler'ın kardinalitesi ÖNCE `continuation()` ile öğrenilip SONRA aynı
şekilde bir "deny" handler'ı döndürülüyor (gerçek servicer kodu reddedilen bir
çağrıda hiç çalışmaz, sadece handler lookup'ı yapılır).

**İstemci:** host başına TEK kalıcı `grpc.Channel` (keepalive açık) —
`web_hosts.py`'nin REST katmanındaki `_conn_is_alive()`/connection-pool
dersinin (bkz. o dosyanın docstring'i — "ölü bir bağlantı sessizce gömülü
kalabilir" canlı olayı) burada BEDAVA gelmesi: gRPC'nin kendi keepalive/
channel-state makinesi bunu hallediyor, hand-rolled bir eşdeğeri gerekmiyor.
"""
from __future__ import annotations
import secrets
import threading
import time
import urllib.parse
from concurrent import futures
from typing import Any, Callable, Dict, Iterator, Optional

import grpc

from . import web_ws
from ..proto import host_bridge_pb2 as pb2
from ..proto import host_bridge_pb2_grpc as pb2_grpc

# Streaming RPC'ler bağlantı ömrü boyunca bir worker tutar (unary'nin aksine)
# — ThreadingHTTPServer'ın bağlantı-başına-thread'inden DAHA kısıtlı bir
# model, bu yüzden cömert boyutlandırılmalı.
_GRPC_MAX_WORKERS = 64

_STATUS_TICK_SECONDS = web_ws._BROADCAST_TICK_SECONDS  # yerel broadcaster'la aynı kadans


# ── proto <-> dict dönüşümleri ──────────────────────────────────────────────

_OPTIONAL_SESSION_FIELDS = ("pid", "cpu", "needs_ho", "busy", "history_size", "live_model", "live_effort")
_OPTIONAL_TERM_FIELDS = ("cols", "rows", "history_size")

# fetch_remote_status()'un ZATEN indirgediği alan seti (web_hosts.py'nin
# _EMPTY_REMOTE'uyla AYNI 6 anahtar) — buradan import ETMİYORUZ (web_hosts.py
# bu modülü kendisi import edecek, tersi döngüsel import olurdu), sadece aynı
# sabit listeyi tekrarlıyoruz — bu bir MANTIK değil, bir isim listesi, drift
# riski close.py/kill.py'nin kill-mekanizması tekrarından farklı bir sınıf.
_STATUS_DICT_KEYS = ("sessions", "closed", "retired", "cli_list", "cli_options", "dups")


def _reduce_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sessions": payload.get("sessions") or [],
        "closed": payload.get("closed") or [],
        "retired": payload.get("retired") or [],
        "cli_list": payload.get("cli_list") or [],
        "cli_options": payload.get("cli_options") or {},
        "dups": payload.get("dups") or [],
    }


def _dict_to_session_row(d: Dict[str, Any]) -> pb2.SessionRow:
    kwargs: Dict[str, Any] = {
        "name": d.get("name") or "",
        "host": d.get("host") or "",
        "model": d.get("model") or "",
        "cwd": d.get("cwd") or "",
        "cli": d.get("cli") or "",
        "running": bool(d.get("running")),
        "kind": d.get("kind") or "",
        "registered": bool(d.get("registered")),
        "tmux": bool(d.get("tmux")),
    }
    for f in _OPTIONAL_SESSION_FIELDS:
        v = d.get(f)
        if v is not None:
            kwargs[f] = v
    return pb2.SessionRow(**kwargs)


def _session_row_to_dict(row: pb2.SessionRow) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "name": row.name, "host": row.host, "model": row.model, "cwd": row.cwd,
        "cli": row.cli, "running": row.running, "kind": row.kind or None,
        "registered": row.registered, "tmux": row.tmux,
    }
    for f in _OPTIONAL_SESSION_FIELDS:
        d[f] = getattr(row, f) if row.HasField(f) else None
    return d


def _cli_options_to_proto(raw: Dict[str, Any]) -> Dict[str, pb2.CliOptions]:
    return {
        cli: pb2.CliOptions(
            models=opts.get("models") or [],
            permission_modes=opts.get("permission_modes") or [],
            effort_levels=opts.get("effort_levels") or [],
            cyclable_modes=opts.get("cyclable_modes") or [],
        )
        for cli, opts in (raw or {}).items()
    }


def _cli_options_from_proto(raw) -> Dict[str, Any]:
    return {
        cli: {
            "models": list(opts.models),
            "permission_modes": list(opts.permission_modes),
            "effort_levels": list(opts.effort_levels),
            "cyclable_modes": list(opts.cyclable_modes),
        }
        for cli, opts in raw.items()
    }


def _status_dict_to_proto(d: Dict[str, Any]) -> pb2.StatusUpdate:
    return pb2.StatusUpdate(
        ok=True,
        error="",
        sessions=[_dict_to_session_row(s) for s in d.get("sessions") or []],
        closed=[_dict_to_session_row(s) for s in d.get("closed") or []],
        retired=[_dict_to_session_row(s) for s in d.get("retired") or []],
        cli_list=d.get("cli_list") or [],
        cli_options=_cli_options_to_proto(d.get("cli_options")),
        dups=d.get("dups") or [],
    )


def _status_proto_to_dict(msg: pb2.StatusUpdate) -> Dict[str, Any]:
    """Dönen şekil `fetch_remote_status()`'un BAŞARILI dönüş şekliyle birebir
    aynı — bir mesajın bu stream'den gelmesi zaten "ok" demek (stream canlıysa
    veri akıyordur); `ok`/`error` proto alanları `TermUpdate` ile ŞEKİL
    simetrisi için var, status'ta pratikte hep True/boş."""
    return {
        "ok": True,
        "error": None,
        "sessions": [_session_row_to_dict(s) for s in msg.sessions],
        "closed": [_session_row_to_dict(s) for s in msg.closed],
        "retired": [_session_row_to_dict(s) for s in msg.retired],
        "cli_list": list(msg.cli_list),
        "cli_options": _cli_options_from_proto(msg.cli_options),
        "dups": list(msg.dups),
    }


def _term_dict_to_proto(d: Dict[str, Any]) -> pb2.TermUpdate:
    kwargs: Dict[str, Any] = {
        "ok": bool(d.get("ok")),
        "error": d.get("error") or "",
        "text": d.get("text") or "",
        "masked": bool(d.get("masked")),
        "mode": d.get("mode") or "",
    }
    for f in _OPTIONAL_TERM_FIELDS:
        v = d.get(f)
        if v is not None:
            kwargs[f] = v
    return pb2.TermUpdate(**kwargs)


def _term_proto_to_dict(msg: pb2.TermUpdate) -> Dict[str, Any]:
    if not msg.ok:
        return {"ok": False, "error": msg.error or None}
    d: Dict[str, Any] = {"ok": True, "text": msg.text, "masked": msg.masked, "mode": msg.mode or None}
    for f in _OPTIONAL_TERM_FIELDS:
        d[f] = getattr(msg, f) if msg.HasField(f) else None
    return d


# ── Sunucu ───────────────────────────────────────────────────────────────


class _AuthInterceptor(grpc.ServerInterceptor):
    def __init__(self, token: str):
        self._token = token

    def _authorized(self, handler_call_details) -> bool:
        for k, v in handler_call_details.invocation_metadata or ():
            if k == "authorization" and v.startswith("Bearer "):
                try:
                    return secrets.compare_digest(v[len("Bearer "):], self._token)
                except TypeError:
                    return False
        return False

    def intercept_service(self, continuation, handler_call_details):
        handler = continuation(handler_call_details)
        if handler is None or self._authorized(handler_call_details):
            return handler
        if handler.response_streaming:
            return grpc.unary_stream_rpc_method_handler(_deny_stream)
        return grpc.unary_unary_rpc_method_handler(_deny_unary)


def _deny_unary(request, context):
    context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid token")


def _deny_stream(request, context):
    context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid token")


class _HostBridgeServicer(pb2_grpc.HostBridgeServicer):
    def __init__(self, status_payload_fn: Callable[[], dict], term_output_fn: Callable[[str, str], dict]):
        self._status_payload_fn = status_payload_fn
        self._term_output_fn = term_output_fn

    def Ping(self, request, context):
        return pb2.PingResponse(claudeops_version="")

    def StreamStatus(self, request, context):
        """`web_ws._comparable()`'ı DOĞRUDAN reuse ediyor (yeniden türetmek
        yerine) — aynı diff mantığı, aynı gürültü-alan filtresi (cpu vb)."""
        last_snapshot: Optional[str] = None
        last_sent = 0.0
        while context.is_active():
            try:
                payload = _reduce_status(self._status_payload_fn())
                snapshot = web_ws._comparable(payload)
            except Exception:
                time.sleep(_STATUS_TICK_SECONDS)
                continue
            now = time.monotonic()
            if snapshot != last_snapshot or (now - last_sent) >= web_ws._HEARTBEAT_SECONDS:
                yield _status_dict_to_proto(payload)
                last_snapshot = snapshot
                last_sent = now
            time.sleep(_STATUS_TICK_SECONDS)

    def StreamTermOutput(self, request, context):
        """`web_ws._term_poll_loop()`'un AYNI dedup-key deseni + AYNI
        `_TERM_POLL_SECONDS` kadansı — burada da yeniden türetmek yerine
        modül sabitlerini reuse ediyoruz."""
        last_key: Any = None
        last_sent = 0.0
        while context.is_active():
            try:
                payload = self._term_output_fn(request.name, request.lang or "tr")
            except Exception:
                payload = None
            if payload is not None:
                key = (payload.get("ok"), payload.get("text"), payload.get("cols"),
                       payload.get("rows"), payload.get("error"))
                now = time.monotonic()
                if key != last_key or (now - last_sent) >= web_ws._HEARTBEAT_SECONDS:
                    yield _term_dict_to_proto(payload)
                    last_key = key
                    last_sent = now
            time.sleep(web_ws._TERM_POLL_SECONDS)


def start_grpc_server(port: int, token: str, status_payload_fn: Callable[[], dict],
                       term_output_fn: Callable[[str, str], dict]) -> Optional[grpc.Server]:
    """`run()`'dan BİR KEZ çağrılır. Bind başarısız olursa (port çakışması vb.)
    `None` döner — `cops web`'in kendisi ASLA bundan etkilenmemeli, bu katman
    tamamen opsiyonel bir iyileştirme, REST/WS zemin olmaya devam eder."""
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=_GRPC_MAX_WORKERS),
        interceptors=(_AuthInterceptor(token),),
    )
    pb2_grpc.add_HostBridgeServicer_to_server(_HostBridgeServicer(status_payload_fn, term_output_fn), server)
    try:
        server.add_insecure_port(f"127.0.0.1:{port}")
        server.start()
    except Exception as e:
        print(f"  ⚠ gRPC server başlatılamadı ({port}): {e} — devre dışı, REST/WS etkilenmedi")
        return None
    return server


# ── İstemci ──────────────────────────────────────────────────────────────

_KEEPALIVE_OPTIONS = [
    ("grpc.keepalive_time_ms", 20_000),
    ("grpc.keepalive_timeout_ms", 5_000),
    ("grpc.keepalive_permit_without_calls", 1),
]

_channel_lock = threading.Lock()
_channels: Dict[str, grpc.Channel] = {}


def _channel_for(grpc_url: str) -> grpc.Channel:
    with _channel_lock:
        ch = _channels.get(grpc_url)
        if ch is not None:
            return ch
        parsed = urllib.parse.urlsplit(grpc_url)
        target = f"{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"
        if parsed.scheme == "https":
            ch = grpc.secure_channel(target, grpc.ssl_channel_credentials(), options=_KEEPALIVE_OPTIONS)
        else:
            ch = grpc.insecure_channel(target, options=_KEEPALIVE_OPTIONS)
        _channels[grpc_url] = ch
        return ch


def _stub_for(grpc_url: str) -> pb2_grpc.HostBridgeStub:
    return pb2_grpc.HostBridgeStub(_channel_for(grpc_url))


def _auth_metadata(token: str):
    return (("authorization", f"Bearer {token}"),)


def probe(grpc_url: str, token: str, timeout: float) -> bool:
    """Hiçbir zaman raise etmez (`_http_json`'un disiplini) — `Ping` RPC'sini
    dener, transport+auth+servicer'ın GERÇEKTEN çalıştığını kanıtlar (sadece
    `channel_ready_future()` gibi transport-only değil)."""
    try:
        _stub_for(grpc_url).Ping(pb2.PingRequest(), metadata=_auth_metadata(token), timeout=timeout)
        return True
    except Exception:
        return False


def open_status_stream(grpc_url: str, token: str):
    """Ham grpc streaming-call nesnesini döner (dict'e ÇEVRİLMEMİŞ proto
    mesajları taşır) — `stream_status()`'un (aşağıda, basit kullanım için
    hazır dict yield eden sarmalayıcı) AKSİNE, dönen nesnenin `.cancel()`'ı
    VAR ve thread-safe: `web_hosts.py`'nin consumer'ı bu nesneyi SAKLAYIP
    BAŞKA bir thread'den (ör. prober bu consumer'ı eskitip yenisini
    başlatırken) bloklu bir okumayı ANINDA kesmek için çağırabilir — bir
    generator'ın `.close()`'u BUNU yapmaz (sadece generator kendi `yield`
    noktasındayken işe yarar, bloklu ağ okuması SIRASINDA değil)."""
    return _stub_for(grpc_url).StreamStatus(pb2.StreamStatusRequest(), metadata=_auth_metadata(token))


def open_term_stream(grpc_url: str, token: str, name: str, lang: str):
    """`open_status_stream()`'in term-output kardeşi — aynı ham/cancellable
    call nesnesi gerekçesi."""
    req = pb2.StreamTermOutputRequest(name=name, lang=lang)
    return _stub_for(grpc_url).StreamTermOutput(req, metadata=_auth_metadata(token))


def stream_status(grpc_url: str, token: str) -> Iterator[dict]:
    """`open_status_stream()`'in dict-yield eden kolaylık sarmalayıcısı —
    basit/tek-seferlik tüketim için (ör. testler). Cancel-edilebilirlik
    gerekiyorsa (web_hosts.py'nin consumer'ı gibi) `open_status_stream()`'i
    doğrudan kullan."""
    for msg in open_status_stream(grpc_url, token):
        yield _status_proto_to_dict(msg)


def stream_term_output(grpc_url: str, token: str, name: str, lang: str) -> Iterator[dict]:
    for msg in open_term_stream(grpc_url, token, name, lang):
        yield _term_proto_to_dict(msg)
