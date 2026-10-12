"""`py/cops watch <host>:<ad>` — bir session'ın terminalini masaüstündeki GERÇEK bir terminal
penceresinde canlı gösteren ince, SALT-OKUNUR görüntüleyici (TODO.md "Uzak host'lardaki ...
masaüstünde", 2026-10-08 tasarım notu; TBD#74 kararı: Faz 0 + Faz 1).

Yalnız YEREL panelle konuşur (`127.0.0.1:<port>`): host seçimi, tier (rest/ws/grpc), uzak host'un
token'ı ve fallback zaten panelde; görüntüleyicinin uzak host'a SSH'ı ya da kendi token'ı yok.
Taşıyıcı: panelin `/ws/term?...&lite=1` push'u (kare ~4 KB); `websockets` yoksa ya da WS
kurulamıyorsa `/api/term/output?...&lite=1` REST yoklaması. Yetki `Authorization: Bearer`
başlığıyla gider (token URL'ye girmez).

Bu bir tmux client DEĞİL, canlı bir resim:
  - Yazı yazmaz (yazmak panel popup'ında). Yazılan tuşlar yankılanmaz; `q` ya da Ctrl-C çıkar.
  - Yerel kaydırma yok (geçmiş popup'taki `history`'de). Kare yalnız görünür `rows` satırıdır.
  - İmleç konumu karede YOK, imleç gizlenir.
  - Altta 1 satırlık durum çubuğu var; pencere pane'in `cols × (rows+1)` boyutuna istenir
    (VTE'nin `CSI 8 ; r ; c t` kaçışı; tiling/maximize ya da başka terminal yok sayarsa görüntü
    kırpılır: dipten `rows-1` satır, sağdan `cols` sütun).
  - Pencere başlığı TAM `host:ad` (yerel session için `local:ad`, gerçek pencereyle çakışmasın),
    durum bilgisi başlığa DEĞİL çubuğa yazılır: `layout.py` pencereyi başlığın `known_names` ile
    tam eşleşmesine göre bulur (Faz 2).

Görüntüleyici kendiliğinden ASLA çıkmaz (çıkarsa gnome-terminal penceresi de kapanır). Durumlar:
canlı / yeniden bağlanıyor (yerel panel ya da host ulaşılamıyor: 1→2→4…15 sn üstel + jitter,
token her denemede dosyadan tazelenir) / bekliyor (host tamam, session yok; rc/handover aynı
isimle yeniden başlatabilir). Son kare ekranda kalır, çubukta "son güncelleme N sn önce" görünür.
Panel host sorunlarını HTTP 200 + `ok:false` ile döndürdüğü için sınıflama HTTP koduna değil
gövdedeki hata metnine bakar (`classify_frame`; kalıcı çözüm: yanıta `code` alanı, TODO).

`--once`: tek kare basıp çıkar (REST; `cops peek` ihtiyacı, ayrıca TTY'siz doğrulama için).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import select
import shutil
import signal
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterator, List, Optional, Tuple

from ..diaglog import diag_log
from ..hosts import LOCAL_HOST_NAME
from .web import DEFAULT_PORT, TOKEN_FILE

TICK_SECONDS = 0.25            # tuş/saat/yeniden-çizim granülü; WS recv ve REST bekleme bu aralıkla uyanır
HTTP_TIMEOUT_SECONDS = 20.0    # panelin uzak host proxy'si 12 sn'ye kadar bekleyebilir (TERM_READ_TIMEOUT_SECONDS)
REST_LIVE_INTERVAL_SECONDS = 1.0
REST_WAITING_INTERVAL_SECONDS = 5.0     # host tamam, session yok: rc/handover aynı isimle geri getirebilir
REST_FALLBACK_SECONDS = 60.0            # auto modda WS kurulamayınca bu süre REST, sonra WS tekrar denenir
WS_SILENCE_SECONDS = 75.0               # sunucu en geç 30 sn'de bir heartbeat kare yollar (web_ws._HEARTBEAT_SECONDS)
WS_MAX_MESSAGE_BYTES = 16 * 1024 * 1024  # `lite`'ı yok sayan eski bir panel TAM kare (yüzlerce KB) yollar
# `close()` sunucunun TCP'yi kapatmasını bu kadar bekler. Varsayılan 10 sn; panelin elle yazılmış WS sunucusu
# (web_ws) kapanış el sıkışmasında istemci EOF'unu beklediği için `q` ile çıkış 10 sn takılıyordu
# (web_hosts._probe_ws aynı sebeple 1 sn kullanıyor).
WS_CLOSE_TIMEOUT_SECONDS = 1.0
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 15.0

# Durum çubuğu renkleri (256 renk; gnome-terminal ve tmux'ta ortak).
STYLE_LIVE = "\x1b[0;48;5;22;38;5;252m"
STYLE_WAITING = "\x1b[0;48;5;24;38;5;255m"
STYLE_RECONNECTING = "\x1b[0;48;5;130;38;5;255m"
STYLE_SEVERE = "\x1b[0;48;5;88;38;5;255m"

_STATES = {
    "connecting": ("◌", "bağlanıyor", STYLE_WAITING),
    "live": ("●", "canlı", STYLE_LIVE),
    "waiting": ("◌", "bekliyor", STYLE_WAITING),
    "reconnecting": ("◌", "yeniden bağlanıyor", STYLE_RECONNECTING),
}


class TransportError(Exception):
    """Panele ulaşılamadı / bağlantı koptu. `auth`: token reddedildi ya da okunamadı (REST'e
    düşmek aynı sonucu verir, çubuk kırmızı olur)."""

    def __init__(self, detail: str, *, auth: bool = False):
        super().__init__(detail)
        self.detail = detail
        self.auth = auth


# ── hedef, token, kare sınıflama ───────────────────────────────────────────────────────────

def parse_target(spec: str) -> Tuple[str, str]:
    """`host:ad` → (host, ad); yalnız `ad` → (local, ad). Boş parça ya da boşluk/denetim karakteri
    ValueError."""
    spec = (spec or "").strip()
    host, sep, name = spec.partition(":")
    if not sep:
        host, name = LOCAL_HOST_NAME, spec
    host, name = host.strip(), name.strip()
    if not host or not name:
        raise ValueError(f"geçersiz hedef {spec!r}: beklenen biçim host:ad (yerel session için yalnız ad)")
    for part in (host, name):
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in part):
            raise ValueError(f"geçersiz hedef {spec!r}: boşluk/denetim karakteri var")
    return host, name


def read_token(path: str = TOKEN_FILE) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
    except OSError as e:
        raise TransportError(f"{path} okunamadı: {e.strerror or e} (panel bu kullanıcıyla hiç çalıştı mı?)", auth=True)
    if not token:
        raise TransportError(f"{path} boş", auth=True)
    return token


def classify_frame(frame: Any) -> Tuple[str, str]:
    """Panelin `_term_output`-şekilli karesi → (durum, ayrıntı). Durum: live | waiting | reconnecting.

    `ok:false` iki türlü: host/relay bacağı kopuk (`"<host> unreachable: ..."` ya da `relay: ...`),
    yani YENİDEN BAĞLANIYOR; ya da host tamam ama session yok / host tanımsız
    (`"<ad>: not running"`, `unknown host: ...`), yani BEKLİYOR. İstek `lang=en` ile gider, böylece
    metinler yerelleşmeden bağımsız kalır."""
    if not isinstance(frame, dict):
        return "reconnecting", "beklenmeyen kare"
    if frame.get("ok"):
        if isinstance(frame.get("text"), str):
            return "live", ""
        return "reconnecting", "metinsiz kare"
    err = str(frame.get("error") or "bilinmeyen hata")
    low = err.lower()
    if "unreachable" in low or low.startswith("relay:"):
        return "reconnecting", err
    return "waiting", err


# ── metin genişliği, ANSI-farkında kırpma ───────────────────────────────────────────────────

# CSI, OSC (BEL ya da ST ile biten), tek karakterli ESC dizileri ve karakter kümesi seçimi.
_SEQ_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"
    r"|\x1b[()][0-9A-Za-z]"
    r"|\x1b[@-Z\\-_78=>]"
)


def char_width(ch: str) -> int:
    o = ord(ch)
    if o < 32 or o == 127:
        return 0
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(s: str) -> int:
    return sum(char_width(c) for c in _SEQ_RE.sub("", s))


def truncate_ansi(s: str, width: int) -> str:
    """`s`i görünür genişliği en çok `width` olacak şekilde keser; kaçış dizilerini (renkler)
    aynen korur, kesilen kısımdaki dizileri atar. Çağıran satır sonuna SGR sıfırlaması ekler.

    Otomatik satır sarma kapalıyken (DECAWM) sığmayan karakterler son sütunu ÜSTÜNE yazar,
    terminal pane'den dar olduğunda görüntü bozulur; kırpma bunu önler."""
    if width <= 0:
        return ""
    out: List[str] = []
    used = 0
    i = 0
    n = len(s)
    while i < n:
        m = _SEQ_RE.match(s, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        cw = char_width(s[i])
        if used + cw > width:
            break
        out.append(s[i])
        used += cw
        i += 1
    return "".join(out)


def frame_rows(text: str, lite: bool) -> List[str]:
    """Karenin satırları. Tam karede `capture-pane` her satırı "\\n" ile bitirir, sondaki o newline
    satır AYIRACI değil terminatördür ve atılır. Lite karede (`web_term_lite.viewport_text`) terminatör
    zaten atılmıştır: metin tam `rows` satırdır ve son pane satırı boşsa "\\n" ile BİTER, o newline
    boş son satırın ayıracıdır, atılırsa satır kaybolur ve dipten kırpma bir satır kayar."""
    if not lite and text.endswith("\n"):
        text = text[:-1]
    return text.split("\n")


def fit_lines(text: str, width: int, height: int, lite: bool = False) -> List[str]:
    """Karenin metnini `width`×`height` alana sığdırır: dipten `height` satır (istem ve durum
    satırı pane'in altındadır), her satır sağdan `width` sütuna kırpılı."""
    if height <= 0:
        return []
    return [truncate_ansi(ln, width) for ln in frame_rows(text, lite)[-height:]]


def fmt_age(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return f"{s} sn"
    if s < 3600:
        return f"{s // 60} dk"
    return f"{s // 3600} sa"


def build_body(lines: List[str], body_rows: int) -> str:
    """Her gövde satırını MUTLAK konumla yazar (hiç newline yok: son satırda kaydırma olmaz) ve
    satır sonunu siler; `lines`tan az satır varsa kalanlar boşaltılır."""
    parts = []
    for i in range(max(body_rows, 0)):
        line = lines[i] if i < len(lines) else ""
        parts.append(f"\x1b[{i + 1};1H{line}\x1b[0m\x1b[K")
    return "".join(parts)


def build_status(text: str, style: str, cols: int, row: int) -> str:
    """Durum çubuğu: `row`. satırda, `cols` sütunu dolduran renkli şerit."""
    text = truncate_ansi(text, cols)
    pad = max(cols - display_width(text), 0)
    return f"\x1b[{row};1H{style}{text}{' ' * pad}\x1b[0m"


# ── yeniden bağlanma gecikmesi ─────────────────────────────────────────────────────────────

class Backoff:
    """1→2→4→8→15→15… sn; jitter yalnız AŞAĞI yönlü (%80-100), yani tavan aşılmaz."""

    def __init__(self, base: float = BACKOFF_BASE_SECONDS, cap: float = BACKOFF_CAP_SECONDS,
                 rand: Callable[[], float] = random.random):
        self._base, self._cap, self._rand = base, cap, rand
        self._n = 0

    def next(self) -> float:
        delay = min(self._cap, self._base * (2 ** self._n))
        self._n += 1
        return delay * (0.8 + 0.2 * self._rand())

    def reset(self) -> None:
        self._n = 0


# ── taşıyıcılar ──────────────────────────────────────────────────────────────────────────

def _query(host: str, name: str) -> str:
    return urllib.parse.urlencode({"name": name, "host": host, "lang": "en", "lite": "1"})


def _parse_term_message(raw: Any) -> Optional[dict]:
    """`/ws/term`'ün `{"type":"term","data":{...}}` zarfı → data; başka her şey None (yok sayılır)."""
    if not isinstance(raw, (str, bytes, bytearray)):
        return None
    try:
        msg = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if isinstance(msg, dict) and msg.get("type") == "term" and isinstance(msg.get("data"), dict):
        return msg["data"]
    return None


def _ws_error(exc: BaseException) -> TransportError:
    status = getattr(getattr(exc, "response", None), "status_code", None) or getattr(exc, "status_code", None)
    if status in (401, 403):
        return TransportError(f"http {status}: web.token bu panelle eşleşmiyor", auth=True)
    if status:
        return TransportError(f"ws el sıkışması http {status}")
    msg = str(exc)
    return TransportError(f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__)


def import_ws_connect() -> Optional[Callable[..., Any]]:
    try:
        from websockets.sync.client import connect
    except ImportError:
        return None
    return connect


class WsTransport:
    """Panelin `/ws/term?...&lite=1` push'u. `frames()` bir üreteçtir: kare (dict), sessiz tick'te
    None verir; bağlantı kurulamaz/koparsa TransportError fırlatır."""

    name = "ws"

    def __init__(self, port: int, host: str, session: str, *, connect: Callable[..., Any],
                 read_token: Optional[Callable[[], str]] = None, clock: Callable[[], float] = time.monotonic):
        self.url = f"ws://127.0.0.1:{port}/ws/term?{_query(host, session)}"
        self._connect = connect
        self._read_token = read_token  # None: modül düzeyindeki `read_token` (çağrı anında çözülür)
        self._clock = clock

    def frames(self, stop: threading.Event, tick: float) -> Iterator[Optional[dict]]:
        token = (self._read_token or read_token)()
        try:
            conn = self._connect(self.url, additional_headers={"Authorization": f"Bearer {token}"},
                                 open_timeout=HTTP_TIMEOUT_SECONDS, close_timeout=WS_CLOSE_TIMEOUT_SECONDS,
                                 max_size=WS_MAX_MESSAGE_BYTES)
        except Exception as e:
            raise _ws_error(e) from e
        last_rx = self._clock()
        try:
            while not stop.is_set():
                try:
                    raw = conn.recv(timeout=tick)
                except TimeoutError:
                    if self._clock() - last_rx > WS_SILENCE_SECONDS:
                        raise TransportError(f"sunucudan {WS_SILENCE_SECONDS:.0f} sn ses yok")
                    yield None
                    continue
                last_rx = self._clock()
                yield _parse_term_message(raw)
        except TransportError:
            raise
        except Exception as e:
            raise _ws_error(e) from e
        finally:
            try:
                conn.close()
            except Exception:
                pass


class RestTransport:
    """`/api/term/output?...&lite=1` yoklaması: canlıyken saniyede 1, bekleyişte 5 sn'de 1."""

    name = "rest"

    def __init__(self, port: int, host: str, session: str, *, read_token: Optional[Callable[[], str]] = None,
                 urlopen: Callable[..., Any] = urllib.request.urlopen, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.url = f"http://127.0.0.1:{port}/api/term/output?{_query(host, session)}"
        self.port = port
        self._read_token = read_token  # None: modül düzeyindeki `read_token` (çağrı anında çözülür)
        self._urlopen = urlopen
        self._clock = clock
        self._sleep = sleep

    def fetch(self) -> dict:
        token = (self._read_token or read_token)()
        req = urllib.request.Request(self.url, headers={"Authorization": f"Bearer {token}"})
        try:
            with self._urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            e.close()  # HTTPError aynı zamanda açık bir yanıt nesnesi; yeniden bağlanma döngüsünde birikmesin
            if e.code in (401, 403):
                raise TransportError(f"http {e.code}: web.token {self.port} portundaki panelle eşleşmiyor", auth=True)
            raise TransportError(f"http {e.code}")
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise TransportError(str(getattr(e, "reason", None) or e))
        try:
            frame = json.loads(body)
        except ValueError:
            raise TransportError("panel JSON olmayan yanıt verdi")
        if not isinstance(frame, dict):
            raise TransportError("panel beklenmeyen yanıt verdi")
        return frame

    def frames(self, stop: threading.Event, tick: float) -> Iterator[Optional[dict]]:
        while not stop.is_set():
            started = self._clock()
            frame = self.fetch()
            yield frame
            interval = REST_LIVE_INTERVAL_SECONDS if frame.get("ok") else REST_WAITING_INTERVAL_SECONDS
            while not stop.is_set() and self._clock() - started < interval:
                self._sleep(tick)
                yield None


# ── ekran ───────────────────────────────────────────────────────────────────────────────

class Screen:
    """Gerçek terminale yazan ince katman. Alternatif ekran + gizli imleç + otomatik sarma kapalı;
    `leave()` hepsini geri alır. Yazma hatası (pencere kapandı) `dead`i işaretler, raise etmez."""

    def __init__(self, out, title: str, size_fn: Optional[Callable[[], Tuple[int, int]]] = None):
        self._out = out
        self._title = "".join(c for c in title if ord(c) >= 32 and ord(c) != 127)
        self._size_fn = size_fn
        self.dead = False

    def write(self, data: str) -> None:
        if self.dead or not data:
            return
        try:
            self._out.write(data)
            self._out.flush()
        except (OSError, ValueError):
            self.dead = True

    def size(self) -> Tuple[int, int]:
        if self._size_fn is not None:
            return self._size_fn()
        try:
            sz = os.get_terminal_size(self._out.fileno())
            return sz.columns, sz.lines
        except (OSError, ValueError, AttributeError):
            sz = shutil.get_terminal_size((80, 24))
            return sz.columns, sz.lines

    def title_seq(self) -> str:
        return f"\x1b]0;{self._title}\x07"

    def enter(self) -> None:
        self.write("\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[2J" + self.title_seq())

    def leave(self) -> None:
        self.write("\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l")


class Viewer:
    """Son kareyi ve durumu tutar, `render()` yalnız DEĞİŞENİ çizer (gövde: yeni kare ya da
    boyut değişimi; çubuk: metin değişimi, yani saniyede en çok bir kez)."""

    def __init__(self, host: str, session: str, screen: Screen, *, resize: bool = True,
                 clock: Callable[[], float] = time.monotonic):
        self.host, self.session = host, session
        self.screen = screen
        self._resize = resize
        self._clock = clock
        self.state = "connecting"
        self.detail = ""
        self.severe = False
        self.retry_in: Optional[float] = None
        self.transport_name = ""
        self.frame: Optional[dict] = None
        # Ekrandaki içeriğin GÜNCEL olduğunun son doğrulandığı an: canlı kare geldiğinde ve canlıyken
        # sağlıklı bağlantıda geçen her sessiz tick'te tazelenir (WS yalnız DEĞİŞİNCE kare yollar,
        # sessiz bir pane'de "son kare" yaşı yanıltırdı). Bağlantı kopunca ya da session gidince
        # tazelenmeyi bırakır, yani çubuktaki yaş "ne zamandır güncel değil"i verir.
        self.fresh_at: Optional[float] = None
        self._frame_key: Any = None
        self._body_dirty = True
        self._status_key: Any = None
        self._last_size: Optional[Tuple[int, int]] = None
        self._resized_for: Optional[Tuple[int, int]] = None

    def apply_frame(self, frame: Any) -> None:
        state, detail = classify_frame(frame)
        if state == "live":
            key = (frame["text"], frame.get("cols"), frame.get("rows"))
            if key != self._frame_key:
                self._frame_key = key
                self.frame = frame
                self._body_dirty = True
            self.fresh_at = self._clock()
        self.state, self.detail, self.severe, self.retry_in = state, detail, False, None

    def confirm_fresh(self) -> None:
        """Sağlıklı bir bağlantıda yeni kare gelmedi (pane değişmedi): canlıyken bu, içeriğin hâlâ güncel olduğu demek."""
        if self.state == "live":
            self.fresh_at = self._clock()

    def apply_failure(self, detail: str, *, severe: bool = False) -> None:
        self.state, self.detail, self.severe = "reconnecting", detail, severe

    def set_retry_in(self, seconds: Optional[float]) -> None:
        self.retry_in = seconds

    def status(self) -> Tuple[str, str]:
        icon, label, style = _STATES[self.state]
        if self.severe:
            style = STYLE_SEVERE
        head = f"{icon} {label}"
        if self.retry_in is not None and self.retry_in > 0:
            head += f" ({math.ceil(self.retry_in)} sn)"
        parts = [head]
        if self.state != "live" and self.fresh_at is not None:
            parts.append(f"son güncelleme {fmt_age(self._clock() - self.fresh_at)} önce")
        if self.detail:
            parts.append(self.detail)
        size = self._pane_size()
        if size:
            parts.append(f"{size[0]}×{size[1]}")
        if self.transport_name:
            parts.append(self.transport_name)
        return " " + " · ".join(parts), style

    def _pane_size(self) -> Optional[Tuple[int, int]]:
        if not self.frame:
            return None
        cols, rows = self.frame.get("cols"), self.frame.get("rows")
        ok = all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (cols, rows))
        return (cols, rows) if ok else None

    def render(self) -> None:
        cols, rows = self.screen.size()
        out: List[str] = []
        pane = self._pane_size()
        if self._resize and pane and pane != self._resized_for:
            # Pencereyi pane'e (+1 çubuk satırı) boyutlandırmayı iste; yalnız pane boyutu DEĞİŞİNCE,
            # kullanıcı pencereyi elle büyütürse onunla savaşılmaz. Yok sayan terminal kırpar.
            out.append(f"\x1b[8;{pane[1] + 1};{pane[0]}t")
            self._resized_for = pane
        if (cols, rows) != self._last_size:
            self._last_size = (cols, rows)
            self._body_dirty = True
            self._status_key = None
            out.append(self.screen.title_seq())
        if self._body_dirty:
            lines = (fit_lines(self.frame["text"], cols, rows - 1, lite=bool(self.frame.get("lite")))
                     if self.frame else [])
            out.append(build_body(lines, rows - 1))
            self._body_dirty = False
        text, style = self.status()
        key = (text, style, cols, rows)
        if key != self._status_key:
            out.append(build_status(text, style, cols, rows))
            self._status_key = key
        self.screen.write("".join(out))


class Keys:
    """stdin'i cbreak'e alır (yazılan tuşlar yankılanıp gövdeyi bozmasın; ISIG açık kalır, Ctrl-C
    çalışır). TTY değilse hiçbir şey yapmaz."""

    def __init__(self, stream=None):
        self._stream = stream if stream is not None else sys.stdin
        self._fd: Optional[int] = None
        self._saved = None

    def __enter__(self) -> "Keys":
        try:
            if self._stream.isatty():
                import termios
                import tty
                self._fd = self._stream.fileno()
                self._saved = termios.tcgetattr(self._fd)
                tty.setcbreak(self._fd)
        except Exception:
            self._fd = None
        return self

    def __exit__(self, *exc) -> None:
        if self._fd is not None and self._saved is not None:
            try:
                import termios
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
            except Exception:
                pass

    def poll(self) -> str:
        if self._fd is None:
            return ""
        out = b""
        try:
            while select.select([self._fd], [], [], 0)[0]:
                chunk = os.read(self._fd, 64)
                if not chunk:
                    break
                out += chunk
        except OSError:
            pass
        return out.decode("utf-8", "ignore")


# ── denetleyici döngü ───────────────────────────────────────────────────────────────────────

# Tuş kaçış dizileri: CSI (oklar, `ESC[1;2Q`), SS3 (F1-F4: `ESC O P..S`; F2 = `ESC O Q`) ve diğer ESC çiftleri.
_KEY_SEQ_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1bO.|\x1b.", re.DOTALL)


def wants_quit(chunk: str) -> bool:
    """`q`/`Q` basıldı mı. Tuş dizilerinin İÇİNDEKİ q sayılmaz (F2 tuşu `ESC O Q` gönderir)."""
    return "q" in _KEY_SEQ_RE.sub("", chunk).lower()


def _quit_requested(keys: Optional[Any], stop: threading.Event) -> bool:
    if keys is not None and wants_quit(keys.poll()):
        stop.set()
    return stop.is_set()


def _wait_with_ticks(viewer: Viewer, seconds: float, *, stop: threading.Event, keys: Optional[Any],
                     clock: Callable[[], float], sleep: Callable[[float], None]) -> None:
    """Yeniden bağlanma beklemesi: bekleme boyunca çubuk geri sayımı ve saat güncellenir, `q` dinlenir."""
    end = clock() + seconds
    while not _quit_requested(keys, stop) and not viewer.screen.dead:
        remaining = end - clock()
        if remaining <= 0:
            break
        viewer.set_retry_in(remaining)
        viewer.render()
        sleep(min(TICK_SECONDS, remaining))
    viewer.set_retry_in(None)


def watch_loop(viewer: Viewer, ws: Optional[WsTransport], rest: RestTransport, *, mode: str = "auto",
               stop: threading.Event, keys: Optional[Any] = None, backoff: Optional[Backoff] = None,
               clock: Callable[[], float] = time.monotonic,
               sleep: Callable[[float], None] = time.sleep) -> None:
    """Kendiliğinden ASLA çıkmaz: yalnız `stop` (q / sinyal) ya da pencerenin kapanması bitirir.

    auto: önce WS. WS hiç kare vermeden kurulamazsa (panel WS'siz/eski ya da WS yolu bozuksa) hemen
    REST denenir ve `REST_FALLBACK_SECONDS` boyunca REST'te kalınır, sonra WS tekrar denenir. Panel
    gerçekten kapalıysa REST de hata verir ve üstel bekleme (`Backoff`) devreye girer."""
    backoff = backoff or Backoff()
    use_rest_until = 0.0
    while not stop.is_set() and not viewer.screen.dead:
        if mode == "rest" or ws is None:
            transport: Any = rest
        elif mode == "ws":
            transport = ws
        else:
            transport = rest if clock() < use_rest_until else ws
        viewer.transport_name = transport.name
        got_frame = False
        failure: Optional[TransportError] = None
        gen = None
        try:
            gen = transport.frames(stop, TICK_SECONDS)
            for frame in gen:
                if _quit_requested(keys, stop) or viewer.screen.dead:
                    break
                if frame is not None:
                    got_frame = True
                    viewer.apply_frame(frame)
                    backoff.reset()
                else:
                    viewer.confirm_fresh()
                viewer.render()
                if transport is rest and mode == "auto" and ws is not None and clock() >= use_rest_until:
                    break  # REST penceresi doldu: WS'i tekrar dene (hata değil, bekleme yok)
        except TransportError as e:
            failure = e
        except Exception as e:  # beklenmeyen hata görüntüleyiciyi öldürmesin (pencere kapanır)
            diag_log("watch_internal_error", target=f"{viewer.host}:{viewer.session}", error=repr(e))
            failure = TransportError(f"iç hata: {type(e).__name__}")
        finally:
            if gen is not None:
                gen.close()
        if stop.is_set() or viewer.screen.dead:
            break
        if failure is None:
            if transport is rest and mode == "auto" and ws is not None:
                continue
            failure = TransportError("bağlantı kapandı")
        viewer.apply_failure(failure.detail, severe=failure.auth)
        if transport is ws and mode == "auto" and not got_frame and not failure.auth:
            use_rest_until = clock() + REST_FALLBACK_SECONDS
            continue
        viewer.render()
        _wait_with_ticks(viewer, backoff.next(), stop=stop, keys=keys, clock=clock, sleep=sleep)


# ── CLI ─────────────────────────────────────────────────────────────────────────────────

def register(sub) -> None:
    p = sub.add_parser("watch", help="bir session'ın terminalini bu pencerede canlı (salt-okunur) göster: watch [host:]ad")
    p.add_argument("target", help="host:ad (yerel session için yalnız ad). host, panelde kayıtlı host adı")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"yerel panelin portu (varsayılan {DEFAULT_PORT}); `py/cops web [--port]` ile aynı olmalı")
    p.add_argument("--transport", choices=("auto", "ws", "rest"), default="auto",
                   help="auto: WS, kurulamazsa REST (varsayılan); ws / rest: yalnız o")
    p.add_argument("--once", action="store_true", help="tek kare bas ve çık (REST; TTY gerekmez)")
    p.add_argument("--plain", action="store_true", help="--once ile: renk kaçışlarını at")
    p.add_argument("--no-resize", action="store_true", help="pencereyi pane boyutuna istemeyi kapat")
    p.set_defaults(func=run)


def run_once(host: str, name: str, port: int, plain: bool) -> int:
    from ..tmux_backend import strip_ansi
    rest = RestTransport(port, host, name)
    try:
        frame = rest.fetch()
    except TransportError as e:
        print(f"cops watch: {e.detail}", file=sys.stderr)
        return 1
    state, detail = classify_frame(frame)
    if state != "live":
        print(f"cops watch: {host}:{name}: {detail}", file=sys.stderr)
        return 1
    text = "\n".join(frame_rows(frame["text"], bool(frame.get("lite"))))
    print(strip_ansi(text) if plain else text)
    return 0


def run(args: argparse.Namespace) -> int:
    try:
        host, name = parse_target(args.target)
    except ValueError as e:
        print(f"cops watch: {e}", file=sys.stderr)
        return 2
    if args.once:
        return run_once(host, name, args.port, args.plain)
    if not sys.stdout.isatty():
        print("cops watch: stdout bir terminal değil (tek kare için --once kullanın)", file=sys.stderr)
        return 2
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())

    connect = import_ws_connect() if args.transport != "rest" else None
    if args.transport == "ws" and connect is None:
        print("cops watch: --transport ws için `websockets` paketi gerekli", file=sys.stderr)
        return 2
    ws = WsTransport(args.port, host, name, connect=connect) if connect is not None else None
    rest = RestTransport(args.port, host, name)

    screen = Screen(sys.stdout, title=f"{host}:{name}")
    viewer = Viewer(host, name, screen, resize=not args.no_resize)
    screen.enter()
    try:
        with Keys() as keys:
            watch_loop(viewer, ws, rest, mode=args.transport, stop=stop, keys=keys)
    except KeyboardInterrupt:
        pass
    finally:
        screen.leave()
    return 0
