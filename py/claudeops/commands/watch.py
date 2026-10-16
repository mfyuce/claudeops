"""`py/cops watch <host>:<ad>` — bir session'ın terminalini masaüstündeki GERÇEK bir terminal
penceresinde canlı gösteren ince görüntüleyici; varsayılan olarak izler, istenirse mesaj/tuş yollar
(TODO.md "Uzak host'lardaki ... masaüstünde", 2026-10-08 tasarım notu; TBD#74 kararı: Faz 0 + Faz 1;
TBD#79 kararı, 2026-10-13: yazı satırı + kısa tuşlar + ham geçiş).

Yalnız YEREL panelle konuşur (`127.0.0.1:<port>`): host seçimi, tier (rest/ws/grpc), uzak host'un
token'ı ve fallback zaten panelde; görüntüleyicinin uzak host'a SSH'ı ya da kendi token'ı yok.
Taşıyıcı: panelin `/ws/term?...&lite=1&viewport=1&interval=1` push'u (kare ~4 KB; `interval`: uzak host'u 1 sn'de bir
yoklatır, 0,2 sn değil, bkz. `WS_POLL_INTERVAL_SECONDS`); `websockets` yoksa ya da WS
kurulamıyorsa `/api/term/output?...&lite=1` REST yoklaması. Yetki `Authorization: Bearer`
başlığıyla gider (token URL'ye girmez).

Bu bir tmux client DEĞİL, canlı bir resim:
  - Tuşlar oturuma kendiliğinden GİTMEZ; normalde yazılan hiçbir şey yankılanmaz. `q` ya da Ctrl-C çıkar,
    `x` sorun kutusunu gizler (aşağıda), üç açık kip girdi yollar (hepsi yerel panelin
    `/api/term/{input,key,raw}` uçlarından, yani uzak host'a da panel yönlendirir; bkz. `InputController`):
      * `i` yazı satırı: alt çubuk girdi satırına döner (yankı yerelde), Enter `/api/term/input` ile
        yollar (metin + Enter), Esc iptal. Tek satırdır: yapıştırılan satır sonları boşluğa çevrilir.
      * `k` kısa tuş: sonraki TEK tuş oturuma gider (Enter, Esc, yön tuşları, Tab, Shift-Tab; onay
        diyaloglarında gezinmek için), kip kapanır; 8 sn içinde tuş basılmazsa ya da başka tuşa basılırsa
        yollamadan kapanır.
      * `R` ham geçiş: Enter ile onaylanırsa her tuş (Ctrl-C dahil) `/api/term/raw` ile gider; kırmızı çubuk,
        Ctrl-] çıkar, 60 sn tuşsuz kalınca kendiliğinden kilitlenir.
      * `a` işlem (TODO.md 2026-10-16): sonraki TEK harf bir pencere eylemi seçer: h handover, y durdur + yeni isimle
        başlat, d durdur, n yeni chat, r sıfırla (panelin Çalışan sekmesindeki eylemlerle aynı; `window_actions.py`).
        Yıkıcı üçü (y, d, r) ayrıca `y` onayı ister. Eylem arka planda koşar (çubukta ilerleme), sürerken `q` çıkarmaz.
        Çubukta satır sayısı da görünür ("1542/2000 satır"; Ayarlar'daki `history_warn_at`'i aşınca amber).
    Bağlantı canlı değilken ya da pane maskeli girişteyse (parola istemi) hiçbir şey yollanmaz.
    `--read-only` bu kipleri tümden kapatır.
  - Geçmişe kaydırma: Yukarı/PgUp/Home (ve alt ekranda ok tuşuna çevrilen fare tekerleği) geçmiş kipini açar; sayfalar
    panelin `GET /api/term/history` ucundan küçük aralıklarla gelir (tam 2000 satır DEĞİL), PgUp/PgDn/yön tuşları gezer,
    End/Esc/q canlıya döner (uzak tmux'a dokunulmaz, copy-mode YOK). Kare yalnız görünür `rows` satırıdır.
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

Sorun `POPUP_GRACE_SECONDS`'tan uzun sürerse son karenin ÜSTÜNE sarı "!" rozetli küçük bir kutu
çizilir (başlık + hata metni + ipucu): çubuk her zaman görünür, ama sorunun ne olduğu ve içeriğin
bayat olduğu pencereye bakan biri için kutuda daha belirgindir. Kutu üstte durur (en değerli satırlar
alttadır: istem, durum), `x` kutuyu o sorun bitene dek gizler. Kısa kopuşlar kutu çıkarmaz.

Görüntüleyici çalışırken terminale hiçbir şey SIZMAZ (`quiet_terminal`): `websockets` kütüphanesi
hatayı kendi thread'inde `logging` ile stderr'e (traceback dahil) basar ve alt-ekrandaki mutlak
konumlu çizimin üstüne biner; gövde yalnız DEĞİŞİNCE yeniden çizildiği için sessiz bir pane'de o
çöp, son durumun yerinde kalıyordu. Günlükler `diag.log`'a gider.

`--once`: tek kare basıp çıkar (REST; `cops peek` ihtiyacı, ayrıca TTY'siz doğrulama için).
"""
from __future__ import annotations

import argparse
import codecs
import contextlib
import json
import logging
import math
import os
import queue
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
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from ..diaglog import diag_log
from ..hosts import LOCAL_HOST_NAME
from ..tmux_backend import HISTORY_LIMIT
from ..window_actions import ACTIONS, BY_ID, BY_KEY, ActionBusy, ActionLock, PanelClient, Result, run_action
from .web import DEFAULT_PORT, TOKEN_FILE

TICK_SECONDS = 0.25            # tuş/saat/yeniden-çizim granülü; WS recv ve REST bekleme bu aralıkla uyanır
HTTP_TIMEOUT_SECONDS = 20.0    # panelin uzak host proxy'si 12 sn'ye kadar bekleyebilir (TERM_READ_TIMEOUT_SECONDS)
REST_LIVE_INTERVAL_SECONDS = 1.0
REST_WAITING_INTERVAL_SECONDS = 5.0     # host tamam, session yok: rc/handover aynı isimle geri getirebilir
REST_FALLBACK_SECONDS = 60.0            # auto modda WS kurulamayınca bu süre REST, sonra WS tekrar denenir
WS_SILENCE_SECONDS = 75.0               # sunucu en geç 30 sn'de bir heartbeat kare yollar (web_ws._HEARTBEAT_SECONDS)
WS_MAX_MESSAGE_BYTES = 16 * 1024 * 1024  # `lite`'ı yok sayan eski bir panel TAM kare (yüzlerce KB) yollar
# Panelden istenen yoklama aralığı (`/ws/term?interval=`): salt-izleyen pencere 0,2 sn'lik sıklığa ihtiyaç duymaz ve
# uzak host'ta her yoklama 3 tmux alt süreci + 2000 satırlık capture demektir (25 mirror uzak panelleri %148-211 CPU'ya
# çıkardı, TODO.md 2026-10-13 (2)). `interval`'ı bilmeyen eski bir panel/host parametreyi yok sayar. Oturuma girdi
# yazılınca (popup, API) uzak döngü zaten hemen uyanır; ekranda bir değişiklik en geç bu kadar sonra görünür.
WS_POLL_INTERVAL_SECONDS = 1.0
# `close()` sunucunun TCP'yi kapatmasını bu kadar bekler. Varsayılan 10 sn; panelin elle yazılmış WS sunucusu
# (web_ws) kapanış el sıkışmasında istemci EOF'unu beklediği için `q` ile çıkış 10 sn takılıyordu
# (web_hosts._probe_ws aynı sebeple 1 sn kullanıyor).
WS_CLOSE_TIMEOUT_SECONDS = 1.0
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 15.0
# Sorun bu kadar sürmeden popup çıkmaz: yeniden bağlanma ilk denemede (~1 sn) çözülen kısa kopuşlar
# gövdeyi titretmesin, çubuk yetsin.
POPUP_GRACE_SECONDS = 3.0
POPUP_MAX_COLS = 64
POPUP_MIN_COLS = 30
# Girdi kipleri (yazı satırı / kısa tuş / ham geçiş, TBD#79). Normalde döngü 0,25 sn'de bir uyanır; bir girdi kipi
# açıkken tuş yankısı ve ham geçiş bu kadar sıklıkla işlenir (yoksa yazarken harfler çeyrek saniye geriden gelir).
INPUT_TICK_SECONDS = 0.05
KEYS_MODE_SECONDS = 8.0          # `k` sonrası tuş beklemesi; dolunca hiçbir şey yollamadan kapanır
ACTION_MODE_SECONDS = 10.0       # `a` sonrası eylem harfi beklemesi; dolunca hiçbir şey yapmadan kapanır
ACTION_CONFIRM_SECONDS = 8.0     # yıkıcı eylemde `y` onayı beklemesi
ACTION_RESULT_SECONDS = 8.0      # eylem sonucu ("✓ durduruldu · yeni chat: …") çubukta bu kadar kalır (okunması gerekir)
ACTION_EXIT_WAIT_SECONDS = 60.0  # çıkışta yarım kalmış bileşik eylemi (durdur → yeni chat) bu kadar bekle
RAW_CONFIRM_SECONDS = 8.0        # `R` sonrası onay (Enter) beklemesi
RAW_IDLE_LOCK_SECONDS = 60.0     # ham geçişte bu kadar tuşsuz kalınırsa kip kendiliğinden kapanır
RAW_COUNTDOWN_SECONDS = 15.0     # kilide bu kadar kala çubukta geri sayım görünür
RAW_EXIT_KEY = "\x1d"            # Ctrl-]: ham geçişten çıkış (oturumda kullanılan bir tuş değil, telnet geleneği)
FLASH_OK_SECONDS = 2.0           # "gönderildi" bildirimi çubukta bu kadar kalır
FLASH_ERR_SECONDS = 6.0          # hata bildirimi (gönderilemedi, bağlantı yok, maskeli giriş)
COMPOSE_MAX_CHARS = 4000         # yazı satırı sınırı; fazlası sessizce yok sayılır
HISTORY_MAX_REQUEST_LINES = 500  # sunucunun tek istekte verdiği en çok satır (web.TERM_HISTORY_MAX_LINES ile aynı)
# Canlı karedeki history_size bilinen değerden bu kadar süredir KÜÇÜKSE geçmiş gerçekten temizlenmiştir (clear-history);
# daha kısa süren düşüş bayat bir karedir (bir sayfa yanıtı canlı kareden daha yeni olabilir) ve yok sayılır.
HISTORY_SHRINK_GRACE_SECONDS = 3.0
PASTE_MAX_CHARS = 1 << 20        # bracketed paste tamponu sınırı (aşan yapıştırma atılır)

# Durum çubuğu renkleri (256 renk; gnome-terminal ve tmux'ta ortak).
STYLE_LIVE = "\x1b[0;48;5;22;38;5;252m"
STYLE_WAITING = "\x1b[0;48;5;24;38;5;255m"
STYLE_RECONNECTING = "\x1b[0;48;5;130;38;5;255m"
STYLE_SEVERE = "\x1b[0;48;5;88;38;5;255m"
STYLE_BADGE = "\x1b[1;48;5;226;38;5;16m"   # popup'taki "!" rozeti: kalın siyah, sarı zemin
STYLE_INPUT = "\x1b[0;48;5;54;38;5;255m"   # yazı satırı / kısa tuş: mor zemin (canlı yeşil, bekliyor mavi ile karışmaz)
STYLE_RAW = "\x1b[1;48;5;160;38;5;255m"    # ham geçiş: kalın beyaz, parlak kırmızı zemin (durum çubuğunun SEVERE'inden belirgin)
STYLE_HISTORY = "\x1b[0;48;5;94;38;5;255m"  # geçmiş kipi: kahverengi/turuncu zemin (canlı değil, geçmişe bakıyorsun)
STYLE_WARN_TEXT = "\x1b[1;38;5;214m"   # çubuk İÇİNDE tek parça vurgu (satır sayısı eşiği aştı): kalın amber, zemin değişmez
DEFAULT_HISTORY_WARN_AT = 1900         # settings.DEFAULT_SETTINGS["history_warn_at"] ile aynı (ayar okunamazsa)

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


# ── sorun popup'ı ────────────────────────────────────────────────────────────────────────────

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]+")


def clean_text(s: str) -> str:
    """Panelden/uzak host'tan gelen hata metnini tek satıra indirir: denetim karakterleri (ESC dahil)
    boşluğa çevrilir. Durum çubuğu ve popup bu metni olduğu gibi basar; ham kaçış dizisi terminale
    (başlık, pano, imleç) ulaşmasın."""
    return _CONTROL_RE.sub(" ", s).strip()


def wrap_text(text: str, width: int, max_lines: int) -> List[str]:
    """Düz metni görünür genişliğe göre satırlara böler (kelime sınırında; tek başına sığmayan kelimeyi
    genişlikte keser). `max_lines`a sığmayan kısım son satırın sonunda "…" ile işaretlenir."""
    if width <= 1 or max_lines <= 0:
        return []
    lines: List[str] = []
    cur = ""
    for word in text.split():
        while display_width(word) > width:
            head = truncate_ansi(word, width) or word[:1]
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(head)
            word = word[len(head):]
        if not word:
            continue
        if not cur:
            cur = word
        elif display_width(cur) + 1 + display_width(word) <= width:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = truncate_ansi(lines[-1], width - 1) + "…"
    return lines


# (küçük harfli alt dizeler, başlık): ilk eşleşen kazanır. Metinler `TransportError.detail`/`classify_frame`
# çıktısından gelir; tanınmayan her şey "Bağlantı sorunu" olur, ham metin kutuda yine görünür.
_RECONNECT_TITLES = (
    (("unreachable",), "Host'a ulaşılamıyor"),
    (("relay:",), "Uzak host bağlantısı koptu"),
    (("keepalive", "no close frame", "connectionclosed"), "Panelle bağlantı koptu"),
    (("sunucudan",), "Panelden haber gelmiyor"),
    (("refused", "errno 111", "connection reset", "connectionreset", "remote end closed", "timed out"),
     "Panele ulaşılamıyor"),
)


def describe_problem(state: str, detail: str, severe: bool) -> Tuple[str, str]:
    """(başlık, ipucu): popup'ın ilk ve son satırı. `state`: reconnecting | waiting."""
    low = detail.lower()
    if state == "waiting":
        if "unknown host" in low:
            return "Host tanımsız", "Bu host panelde kayıtlı değil"
        return "Session çalışmıyor", "Aynı isimle başlarsa otomatik bağlanır"
    if severe:
        return "Yetki hatası", "web.token bu panelle eşleşmiyor olabilir"
    for needles, title in _RECONNECT_TITLES:
        if any(n in low for n in needles):
            hint = "Panel kapalı ya da yeniden başlıyor olabilir" if title == "Panele ulaşılamıyor" \
                else "Otomatik yeniden denenir"
            return title, hint
    return "Bağlantı sorunu", "Otomatik yeniden denenir"


def popup_layout(title: str, detail: str, hint: str, style: str, cols: int, body_rows: int
                 ) -> Optional[Tuple[int, int, Tuple[str, ...]]]:
    """Gövdenin üstüne binecek kutu: (ilk satır, ilk sütun, hazır SGR'li satırlar) ya da sığmıyorsa None.

        ┌──────────────────────────────────────┐
        │ ! Panelle bağlantı koptu             │   rozet + kalın başlık
        │   hata metni (en çok 2 satır)        │
        │   Otomatik yeniden denenir · x: gizle│   soluk ipucu
        └──────────────────────────────────────┘

    Yatayda ortalı, 1. satırın altından (2. satır) başlar: en değerli satırlar gövdenin altındadır
    (istem, durum), üstü kapatmak "son hali görme" amacına en az zarar verir. Her satırın görünür
    genişliği `box_w`dir."""
    box_w = min(cols, POPUP_MAX_COLS)
    if box_w < POPUP_MIN_COLS:
        return None
    tw = box_w - 8   # `│` + boşluk + rozet(3) + boşluk | metin | boşluk + `│`
    shown_title = truncate_ansi(title, tw)
    detail_lines = wrap_text(detail, tw, 2)
    key_hint = " · x: gizle"   # gizleme tuşu ipucun kırpılsa bile görünür kalır
    shown_hint = truncate_ansi(hint, tw - len(key_hint)) + key_hint

    def pad(text: str) -> str:
        return " " * max(tw - display_width(text), 0)

    reset = "\x1b[0m"
    rows = [f"{style}┌{'─' * (box_w - 2)}┐{reset}",
            f"{style}│ {STYLE_BADGE} ! {style} \x1b[1m{shown_title}\x1b[22m{pad(shown_title)} │{reset}"]
    rows += [f"{style}│     {ln}{pad(ln)} │{reset}" for ln in detail_lines]
    rows += [f"{style}│     \x1b[2m{shown_hint}\x1b[22m{pad(shown_hint)} │{reset}",
             f"{style}└{'─' * (box_w - 2)}┘{reset}"]
    if body_rows < len(rows):
        return None
    top = 2 if body_rows >= len(rows) + 2 else 1
    return top, (cols - box_w) // 2 + 1, tuple(rows)


def build_popup(layout: Tuple[int, int, Tuple[str, ...]]) -> str:
    """`popup_layout` çıktısını MUTLAK konumla yazar (gövdeden SONRA, üstüne)."""
    top, left, rows = layout
    return "".join(f"\x1b[{top + i};{left}H{row}" for i, row in enumerate(rows))


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

def _tick_seconds(tick: Any) -> float:
    """Taşıyıcıların uyanma aralığı: sabit bir sayı ya da her çağrıda çözülen bir işlev. İşlev, girdi kipi
    açılınca döngüyü 0,25 sn yerine `INPUT_TICK_SECONDS`'ta uyandırmak içindir (yazarken yankı gecikmesin)."""
    return tick() if callable(tick) else tick


def _query(host: str, name: str) -> str:
    # `viewport=1`: bu pencere yalnız görünür ekranı çizer, `urls`/`paths`/`mode` okumaz; panel tek tmux süreciyle
    # yalnız görünür ekranı çeker (TBD#80 A: tick başına ~29 ms → ~5 ms toplam CPU). Bilmeyen eski panel yok sayar.
    return urllib.parse.urlencode({"name": name, "host": host, "lang": "en", "lite": "1", "viewport": "1"})


def _ws_query(host: str, name: str) -> str:
    """`_query` + seyrek yoklama isteği; yalnız WS için (REST yedeği kendi 1 sn'lik döngüsünü kullanır)."""
    return urllib.parse.urlencode({"name": name, "host": host, "lang": "en", "lite": "1", "viewport": "1",
                                   "interval": f"{WS_POLL_INTERVAL_SECONDS:g}"})


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
    """Panelin `/ws/term?...&lite=1&interval=1` push'u. `frames()` bir üreteçtir: kare (dict), sessiz tick'te
    None verir; bağlantı kurulamaz/koparsa TransportError fırlatır."""

    name = "ws"

    def __init__(self, port: int, host: str, session: str, *, connect: Callable[..., Any],
                 read_token: Optional[Callable[[], str]] = None, clock: Callable[[], float] = time.monotonic):
        self.url = f"ws://127.0.0.1:{port}/ws/term?{_ws_query(host, session)}"
        self._connect = connect
        self._read_token = read_token  # None: modül düzeyindeki `read_token` (çağrı anında çözülür)
        self._clock = clock

    def frames(self, stop: threading.Event, tick: float) -> Iterator[Optional[dict]]:
        token = (self._read_token or read_token)()
        try:
            # ping_interval=None: canlılığı görüntüleyici kendisi izler (sunucu en geç 30 sn'de bir kare yollar,
            # `WS_SILENCE_SECONDS` sessizlikte bağlantı yenilenir). Kütüphanenin keepalive'ı ikinci, gürültülü bir
            # mekanizma: kendi thread'inde hata verince traceback basar (bkz. `quiet_terminal`) ve web_hosts'taki
            # panel istemcileri de aynı sebeple kapalı tutuyor.
            conn = self._connect(self.url, additional_headers={"Authorization": f"Bearer {token}"},
                                 open_timeout=HTTP_TIMEOUT_SECONDS, close_timeout=WS_CLOSE_TIMEOUT_SECONDS,
                                 max_size=WS_MAX_MESSAGE_BYTES, ping_interval=None)
        except Exception as e:
            raise _ws_error(e) from e
        last_rx = self._clock()
        try:
            while not stop.is_set():
                try:
                    raw = conn.recv(timeout=_tick_seconds(tick))
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
                self._sleep(_tick_seconds(tick))
                yield None


# ── ekran ───────────────────────────────────────────────────────────────────────────────

class Screen:
    """Gerçek terminale yazan ince katman. Alternatif ekran + gizli imleç + otomatik sarma kapalı;
    `leave()` hepsini geri alır. Yazma hatası (pencere kapandı) `dead`i işaretler, raise etmez."""

    def __init__(self, out, title: str, size_fn: Optional[Callable[[], Tuple[int, int]]] = None,
                 bracketed_paste: bool = False):
        self._out = out
        self._title = "".join(c for c in title if ord(c) >= 32 and ord(c) != 127)
        self._size_fn = size_fn
        # Bracketed paste (DECSET 2004): terminal yapıştırmayı `ESC[200~ ... ESC[201~` ile sarar, böylece
        # yapıştırılan metindeki `q`/`i`/`k` komut sayılmaz ve satır sonları Enter'a dönüşmez. Yalnız girdi
        # kipleri açıksa (salt-okunur modda yapıştırma zaten hiçbir şey yapmıyor) istenir.
        self._bracketed_paste = bracketed_paste
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
        self.write("\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[2J" + ("\x1b[?2004h" if self._bracketed_paste else "")
                   + self.title_seq())

    def leave(self) -> None:
        self.write(("\x1b[?2004l" if self._bracketed_paste else "") + "\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l")


class Viewer:
    """Son kareyi ve durumu tutar, `render()` yalnız DEĞİŞENİ çizer (gövde: yeni kare, boyut değişimi ya da
    popup'ın çıkması/kalkması/değişmesi; çubuk: metin değişimi, yani saniyede en çok bir kez)."""

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
        self.hint = ""   # durum çubuğunun sonuna eklenen tuş ipucu (girdi kipleri açıksa `INPUT_HINT`)
        self.history_warn_at = DEFAULT_HISTORY_WARN_AT   # satır sayısı bu sayıdan sonra amber (Ayarlar: history_warn_at)
        self.frame: Optional[dict] = None
        # Ekrandaki içeriğin GÜNCEL olduğunun son doğrulandığı an: canlı kare geldiğinde ve canlıyken
        # sağlıklı bağlantıda geçen her sessiz tick'te tazelenir (WS yalnız DEĞİŞİNCE kare yollar,
        # sessiz bir pane'de "son kare" yaşı yanıltırdı). Bağlantı kopunca ya da session gidince
        # tazelenmeyi bırakır, yani çubuktaki yaş "ne zamandır güncel değil"i verir.
        self.fresh_at: Optional[float] = None
        # Canlı olmayan durumun BAŞLADIĞI an (popup gecikmesi için); canlıya dönünce sıfırlanır. `popup_hidden`:
        # kullanıcı `x` ile kutuyu gizledi, bu sorun bitene dek (canlıya dönene dek) geri gelmez.
        self.trouble_since: Optional[float] = None
        self.popup_hidden = False
        self._frame_key: Any = None
        self._body_dirty = True
        self._status_key: Any = None
        self._popup_key: Any = None
        self._last_size: Optional[Tuple[int, int]] = None
        self._resized_for: Optional[Tuple[int, int]] = None
        # Girdi kipleri çubuğu devralır: `overlay(cols)` (metin, stil) döndürürse durum çubuğunun yerine o çizilir
        # (yazı satırı, kısa tuş ipucu, ham geçiş uyarısı, gönderim sonucu); None = normal durum çubuğu.
        self.overlay: Optional[Callable[[int], Optional[Tuple[str, str]]]] = None
        # Geçmiş kipi canlı kare yerine kendi satırlarını çizdirir (None = canlı kare); canlı kareler gelmeye
        # devam eder (durum, maskeli bayrağı, history_size için) ama gövdeyi bozmaz.
        self._body_override: Optional[List[str]] = None

    def set_body_override(self, lines: Optional[List[str]]) -> None:
        if lines != self._body_override:
            self._body_override = None if lines is None else list(lines)
            self._body_dirty = True

    def apply_frame(self, frame: Any) -> None:
        state, detail = classify_frame(frame)
        if state == "live":
            key = (frame["text"], frame.get("cols"), frame.get("rows"))
            if key != self._frame_key:
                self._frame_key = key
                self.frame = frame
                self._body_dirty = True
            else:
                # Aynı görünür metin: gövde yeniden çizilmez ama kare sözlüğü yine de tazelenir. `masked` ve
                # `history_size` gibi alanlar metin değişmeden de değişebilir (aynı satırı basan bir döngüde geçmiş
                # büyür); girdi kapısı ve geçmiş kipi bu alanlara güvenir, bayat kalmasınlar.
                self.frame = frame
            self.fresh_at = self._clock()
            self.trouble_since, self.popup_hidden = None, False
        else:
            self._note_trouble()
        self.state, self.detail, self.severe, self.retry_in = state, clean_text(detail), False, None

    def confirm_fresh(self) -> None:
        """Sağlıklı bir bağlantıda yeni kare gelmedi (pane değişmedi): canlıyken bu, içeriğin hâlâ güncel olduğu demek."""
        if self.state == "live":
            self.fresh_at = self._clock()

    def apply_failure(self, detail: str, *, severe: bool = False) -> None:
        self._note_trouble()
        self.state, self.detail, self.severe = "reconnecting", clean_text(detail), severe

    def _note_trouble(self) -> None:
        if self.trouble_since is None:
            self.trouble_since = self._clock()

    def dismiss_popup(self) -> None:
        if self.trouble_since is not None:   # sorun yokken basılan `x`, sonraki kesintinin kutusunu bastırmasın
            self.popup_hidden = True

    def popup_visible(self) -> bool:
        return (self.state in ("reconnecting", "waiting") and not self.popup_hidden
                and self.trouble_since is not None
                and self._clock() - self.trouble_since >= POPUP_GRACE_SECONDS)

    def _popup(self, cols: int, body_rows: int) -> Optional[Tuple[int, int, Tuple[str, ...]]]:
        if not self.popup_visible():
            return None
        title, hint = describe_problem(self.state, self.detail, self.severe)
        style = STYLE_SEVERE if self.severe else _STATES[self.state][2]
        return popup_layout(title, self.detail, hint, style, cols, body_rows)

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
        lines = self._lines_part(style)
        if lines:
            parts.append(lines)
        if self.transport_name:
            parts.append(self.transport_name)
        if self.hint:
            parts.append(self.hint)
        return " " + " · ".join(parts), style

    def _lines_part(self, style: str) -> Optional[str]:
        """Satır sayısı ("1542/2000 satır"): panelin Terminal göstergesiyle AYNI veri (kare `history_size`, tmux
        history-limit). Alternate-screen'de `history_size` yapısal olarak ~0'da donar ve panel o durumda göstergeyi
        gizliyor (tmux_backend.tmux_pane_size): burada da yazılmaz. `history_warn_at`'i aşınca kalın amber (panelin amber'ı
        ile aynı dil); amberin ardından çubuğun kendi stili geri yüklenir ki sonraki parçalar boyanmasın."""
        frame = self.frame
        if not frame or frame.get("alternate_screen"):
            return None
        hist = frame.get("history_size")
        if isinstance(hist, bool) or not isinstance(hist, int) or hist < 0:
            return None
        text = f"{hist}/{HISTORY_LIMIT} satır"
        return f"{STYLE_WARN_TEXT}{text}{style}" if hist >= self.history_warn_at else text

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
        popup = self._popup(cols, rows - 1)
        if (popup, cols, rows) != self._popup_key:
            # Kutu çıktı/değişti/kalktı: altındaki gövde yeniden çizilir (kalkınca üstü böyle silinir).
            # Geri sayım gibi saniyelik değişenler çubukta, kutuda değil, yani bu nadiren tetiklenir.
            self._popup_key = (popup, cols, rows)
            self._body_dirty = True
        if self._body_dirty:
            if self._body_override is not None:
                lines = [truncate_ansi(ln, cols) for ln in self._body_override[:max(rows - 1, 0)]]
            else:
                lines = (fit_lines(self.frame["text"], cols, rows - 1, lite=bool(self.frame.get("lite")))
                         if self.frame else [])
            out.append(build_body(lines, rows - 1))
            if popup:
                out.append(build_popup(popup))
            self._body_dirty = False
        text, style = self.status()
        if self.overlay is not None:
            taken = self.overlay(cols)
            if taken:
                text, style = taken
        key = (text, style, cols, rows)
        if key != self._status_key:
            out.append(build_status(text, style, cols, rows))
            self._status_key = key
        self.screen.write("".join(out))


class Keys:
    """stdin'i cbreak'e alır (yazılan tuşlar yankılanıp gövdeyi bozmasın; ISIG açık kalır, Ctrl-C
    çalışır). TTY değilse hiçbir şey yapmaz.

    `set_passthrough(True)` ham geçiş kipi içindir: terminal sürücüsünün tuş yorumlarını (Ctrl-C/Z/\\ sinyalleri,
    Ctrl-V, Ctrl-S/Q akış denetimi, Enter'ın `\\n`e çevrilmesi) kapatır, böylece oturuma gidecek her bayt olduğu gibi
    okunur. Açıkken Ctrl-C görüntüleyiciyi ÖLDÜRMEZ; çıkış `RAW_EXIT_KEY`."""

    def __init__(self, stream=None):
        self._stream = stream if stream is not None else sys.stdin
        self._fd: Optional[int] = None
        self._saved = None
        self._cbreak = None   # cbreak'teki nitelikler: ham geçişten dönüş buraya
        # Çok baytlı bir UTF-8 karakter iki okumaya bölünürse yarım bayt atılmasın.
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="ignore")

    def __enter__(self) -> "Keys":
        try:
            if self._stream.isatty():
                import termios
                import tty
                self._fd = self._stream.fileno()
                self._saved = termios.tcgetattr(self._fd)
                tty.setcbreak(self._fd)
                self._cbreak = termios.tcgetattr(self._fd)
        except Exception:
            self._fd = None
        return self

    def set_passthrough(self, on: bool) -> None:
        if self._fd is None or self._cbreak is None:
            return
        try:
            import termios
            attrs = list(self._cbreak)
            if on:
                attrs[0] &= ~(termios.ICRNL | termios.INLCR | termios.IGNCR | termios.IXON | termios.IXOFF)
                attrs[3] &= ~(termios.ISIG | termios.IEXTEN)
            termios.tcsetattr(self._fd, termios.TCSADRAIN, attrs)
        except Exception:
            pass

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
        return self._decoder.decode(out) if out else ""


# ── denetleyici döngü ───────────────────────────────────────────────────────────────────────

# Tuş kaçış dizileri: CSI (oklar, `ESC[1;2Q`), SS3 (F1-F4: `ESC O P..S`; F2 = `ESC O Q`) ve diğer ESC çiftleri.
_KEY_SEQ_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1bO.|\x1b.", re.DOTALL)


def wants_quit(chunk: str) -> bool:
    """`q`/`Q` basıldı mı. Tuş dizilerinin İÇİNDEKİ q sayılmaz (F2 tuşu `ESC O Q` gönderir)."""
    return "q" in _KEY_SEQ_RE.sub("", chunk).lower()


def wants_dismiss(chunk: str) -> bool:
    """`x`/`X` basıldı mı (sorun kutusunu gizle). `wants_quit` ile aynı kural: tuş dizilerinin içindeki x sayılmaz."""
    return "x" in _KEY_SEQ_RE.sub("", chunk).lower()


# ── girdi: tuş ayrıştırma, gönderim, kip makinesi (TBD#79) ───────────────────────────────────

# Kaydırma tuşları (xterm/VTE; tekerlek alt ekranda ok tuşuna çevrilir: VTE "alternate scroll").
_UP = ("\x1b[A", "\x1bOA")
_DOWN = ("\x1b[B", "\x1bOB")
_PGUP = ("\x1b[5~",)
_PGDN = ("\x1b[6~",)
_HOME = ("\x1b[H", "\x1bOH", "\x1b[1~", "\x1b[7~")
_END = ("\x1b[F", "\x1bOF", "\x1b[4~", "\x1b[8~")

_PASTE_START = "\x1b[200~"
_PASTE_END = "\x1b[201~"
PASTE_STALE_SECONDS = 3.0   # bitiş işareti gelmeyen yapıştırma bu süre sonra atılır (sonraki tuşları yutmasın)
INPUT_HINT = "i yaz · k tuş · R ham · a işlem · ↑ geçmiş"   # normal durum çubuğunun sonunda


class Paste(str):
    """Bracketed paste bloğunun içeriği (işaretler atılmış). Düz `str` tuş jetonlarından `isinstance` ile ayrılır."""


class KeyParser:
    """`Keys.poll()` çıktısını jetonlara böler: tek karakter, kaçış dizisi (`ESC [ A`, `ESC O P`, `ESC x`), tek başına
    ESC ve `Paste` bloğu. Yapıştırma birden çok okumaya yayılabildiği için durum tutar; bitiş işareti hiç gelmezse
    `PASTE_STALE_SECONDS` sonra atılır (aksi halde sonraki bütün tuşlar, `q` dahil, yapıştırma içeriği sanılırdı)."""

    def __init__(self) -> None:
        self._paste: Optional[List[str]] = None
        self._paste_len = 0
        self._paste_since = 0.0

    def feed(self, chunk: str, now: float = 0.0) -> List[str]:
        if self._paste is not None and now - self._paste_since > PASTE_STALE_SECONDS:
            self._paste, self._paste_len = None, 0
        out: List[str] = []
        i, n = 0, len(chunk)
        while i < n:
            if self._paste is not None:
                j = chunk.find(_PASTE_END, i)
                part = chunk[i:] if j < 0 else chunk[i:j]
                self._paste_len += len(part)
                if self._paste_len <= PASTE_MAX_CHARS:
                    self._paste.append(part)
                if j < 0:
                    break
                if self._paste_len <= PASTE_MAX_CHARS:   # sınırı aşan yapıştırma bütünüyle atılır (kırpılmış gitmez)
                    out.append(Paste("".join(self._paste)))
                self._paste, self._paste_len = None, 0
                i = j + len(_PASTE_END)
                continue
            if chunk.startswith(_PASTE_START, i):
                self._paste, self._paste_len, self._paste_since = [], 0, now
                i += len(_PASTE_START)
                continue
            if chunk[i] == "\x1b":
                m = _KEY_SEQ_RE.match(chunk, i)
                if m:
                    out.append(m.group())
                    i = m.end()
                else:   # dizinin başı yok: tek başına Esc tuşu
                    out.append("\x1b")
                    i += 1
                continue
            out.append(chunk[i])
            i += 1
        return out


def _printable(ch: str) -> bool:
    o = ord(ch)
    return o >= 32 and o != 127 and not 0x80 <= o < 0xA0


def one_line(text: str) -> str:
    """Yazı satırına giren metin tek satırdır: satır sonu ve sekme boşluğa çevrilir, diğer denetim karakterleri atılır
    (satır sonu `/api/term/input`un otomatik Enter'ından önce mesajı kesip bir sonraki satırı ayrı mesaj yapardı)."""
    return "".join(" " if c in "\r\n\t" else c for c in text if c in "\r\n\t" or _printable(c))


def drop_last_char(s: str) -> str:
    """Son karakteri (ve ona bağlı birleşik işaretleri) siler."""
    i = len(s)
    while i > 0 and char_width(s[i - 1]) == 0:
        i -= 1
    return s[:max(i - 1, 0)]


def drop_last_word(s: str) -> str:
    s = s.rstrip()
    i = len(s)
    while i > 0 and not s[i - 1].isspace():
        i -= 1
    return s[:i]


def tail_fit(s: str, width: int) -> str:
    """`s`in SONUNU görünür genişliği en çok `width` olacak biçimde alır; kesildiyse başa "…" koyar (imleç sonda durur,
    yazılan son harfler görünür kalsın)."""
    if width <= 0:
        return ""
    if display_width(s) <= width:
        return s
    kept: List[str] = []
    used = 1   # baştaki "…"
    for ch in reversed(s):
        cw = char_width(ch)
        if used + cw > width:
            break
        kept.append(ch)
        used += cw
    return "…" + "".join(reversed(kept))


class InputSender:
    """Mirror'dan session'a giden girdi: yerel panelin `/api/term/{input,key,raw}` uçlarına (üçü de `HOST_ROUTED_PATHS`'ta,
    yani uzak host'a panel yönlendirir; görüntüleyicinin uzak host'a kendi yolu yok) SIRALI POST. HTTP bir arka plan
    thread'inde koşar: uzak host'ta bir istek 12 sn'ye kadar sürebilir, çizim ve tuş döngüsü hiç beklemez. Tek thread
    olduğundan sıra korunur (ham geçişte iki yığın ters gitmez). Sonuçlar `take_results()` ile alınır."""

    ENDPOINTS = {"text": ("/api/term/input", "text"), "key": ("/api/term/key", "key"), "raw": ("/api/term/raw", "data")}

    def __init__(self, port: int, host: str, session: str, *, read_token: Optional[Callable[[], str]] = None,
                 urlopen: Callable[..., Any] = urllib.request.urlopen):
        self.port, self.host, self.session = port, host, session
        self._read_token = read_token  # None: modül düzeyindeki `read_token` (çağrı anında çözülür)
        self._urlopen = urlopen
        self._jobs: "queue.Queue[Optional[Tuple[int, str, str]]]" = queue.Queue()
        self._results: List[Tuple[int, str, bool, str]] = []
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._seq = 0
        self._inflight = 0

    def submit(self, kind: str, payload: str) -> int:
        """Gönderimi sıraya koyar, hemen döner. Dönen sayı `take_results()` kaydıyla eşleşir."""
        if kind not in self.ENDPOINTS:
            raise ValueError(f"bilinmeyen girdi türü: {kind!r}")
        with self._lock:
            self._seq += 1
            seq = self._seq
            self._inflight += 1
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="watch-input", daemon=True)
                self._thread.start()
        self._jobs.put((seq, kind, payload))
        return seq

    def inflight(self) -> int:
        with self._lock:
            return self._inflight

    def take_results(self) -> List[Tuple[int, str, bool, str]]:
        """Biten gönderimler: (seq, tür, başarılı mı, hata metni). Bir kez alınır."""
        with self._lock:
            out, self._results = self._results, []
        return out

    def close(self, wait: float = 2.0) -> None:
        """Bekleyen gönderimleri bitirir (en çok `wait` sn): `q` ile çıkıştan hemen önce yollanan mesaj kaybolmasın."""
        thread = self._thread
        if thread is None:
            return
        self._jobs.put(None)
        thread.join(wait)

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            seq, kind, payload = job
            try:
                ok, err = self._post(kind, payload)
            except Exception as e:   # hiçbir hata gönderim thread'ini öldürmesin: sonraki tuşlar da gitsin
                ok, err = False, f"iç hata: {type(e).__name__}"
            with self._lock:
                self._inflight -= 1
                self._results.append((seq, kind, ok, err))

    def _post(self, kind: str, payload: str) -> Tuple[bool, str]:
        path, field = self.ENDPOINTS[kind]
        try:
            token = (self._read_token or read_token)()
        except TransportError as e:
            return False, e.detail
        body = json.dumps({"name": self.session, "host": self.host, field: payload, "lang": "en"}).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with self._urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            e.close()
            if e.code in (401, 403):
                return False, f"http {e.code}: web.token {self.port} portundaki panelle eşleşmiyor"
            return False, f"http {e.code}"
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            return False, str(getattr(e, "reason", None) or e)
        try:
            data = json.loads(raw)
        except ValueError:
            return False, "panel JSON olmayan yanıt verdi"
        if isinstance(data, dict) and data.get("ok"):
            return True, ""
        return False, str((data.get("error") if isinstance(data, dict) else None) or "panel reddetti")


class HistoryClient:
    """Geçmiş sayfalarını (`GET /api/term/history`, TBD#79) arka plan thread'inde çeker; uzak host'ta bir istek 12 sn'ye
    kadar sürebilir, çizim ve tuş döngüsü beklemez. En SON istek kazanır: PgUp'a basılı tutarken araya giren eski
    istekler beklenmez (bekleyen istek yenisiyle değiştirilir; yola çıkmış olan biter ve sonucu atılmaz, önbelleğe
    girer). Sonuçlar `take_results()` ile alınır: (start, end, yanıt ya da None, hata metni)."""

    def __init__(self, port: int, host: str, session: str, *, read_token: Optional[Callable[[], str]] = None,
                 urlopen: Callable[..., Any] = urllib.request.urlopen):
        self.port, self.host, self.session = port, host, session
        self._read_token = read_token  # None: modül düzeyindeki `read_token` (çağrı anında çözülür)
        self._urlopen = urlopen
        self._cv = threading.Condition()
        self._pending: Optional[Tuple[int, int]] = None
        self._inflight = False
        self._results: List[Tuple[int, int, Optional[dict], str]] = []
        self._thread: Optional[threading.Thread] = None
        self._closed = False

    def request(self, start: int, end: int) -> None:
        with self._cv:
            if self._closed:
                return
            self._pending = (start, end)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="watch-history", daemon=True)
                self._thread.start()
            self._cv.notify()

    def busy(self) -> bool:
        with self._cv:
            return self._pending is not None or self._inflight

    def take_results(self) -> List[Tuple[int, int, Optional[dict], str]]:
        with self._cv:
            out, self._results = self._results, []
        return out

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._pending = None
            self._cv.notify()

    def _run(self) -> None:
        while True:
            with self._cv:
                while self._pending is None and not self._closed:
                    self._cv.wait()
                if self._closed:
                    return
                start, end = self._pending
                self._pending = None
                self._inflight = True
            try:
                payload, err = self._get(start, end)
            except Exception as e:   # hiçbir hata thread'i öldürmesin: sonraki sayfa yine çekilebilsin
                payload, err = None, f"iç hata: {type(e).__name__}"
            with self._cv:
                self._inflight = False
                self._results.append((start, end, payload, err))

    def _get(self, start: int, end: int) -> Tuple[Optional[dict], str]:
        try:
            token = (self._read_token or read_token)()
        except TransportError as e:
            return None, e.detail
        query = urllib.parse.urlencode({"name": self.session, "host": self.host, "lang": "en",
                                        "start": start, "end": end})
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/term/history?{query}",
                                     headers={"Authorization": f"Bearer {token}"})
        try:
            with self._urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            e.close()
            if e.code in (401, 403):
                return None, f"http {e.code}: web.token {self.port} portundaki panelle eşleşmiyor"
            if e.code == 404:   # uzak host'un paneli bu uçtan önceki bir sürümde
                return None, "bu host'un paneli eski, geçmiş ucu yok"
            return None, f"http {e.code}"
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            return None, str(getattr(e, "reason", None) or e)
        try:
            data = json.loads(raw)
        except ValueError:
            return None, "panel JSON olmayan yanıt verdi"
        if (isinstance(data, dict) and data.get("ok") and isinstance(data.get("text"), str)
                and isinstance(data.get("start"), int) and isinstance(data.get("history_size"), int)):
            return data, ""
        return None, str((data.get("error") if isinstance(data, dict) else None) or "panel reddetti")


class ActionRunner:
    """Pencere eylemini (`window_actions.run_action`: handover / durdur + yeni isim / durdur / yeni chat / sıfırla) arka
    plan thread'inde koşturur: bileşik eylem ~10 sn, uzak host'ta daha çok sürer; çizim ve tuş döngüsü hiç beklemez.
    Aynı anda TEK eylem. (host, ad) kilidi (`ActionLock`) başka bir pencereden / tmux şeridinden gelen eşzamanlı eylemi
    de dışlar. `close()` çıkışta yarım kalmış bileşik eylemi (durdurdu ama yeni chat'i henüz açmadı) bekler: görüntüleyici
    ölünce eylem de ölürdü."""

    def __init__(self, port: int, host: str, session: str, *, read_token_fn: Optional[Callable[[], str]] = None,
                 run: Callable[..., Result] = run_action, lock_factory: Callable[[str, str], Any] = ActionLock):
        self.port, self.host, self.session = port, host, session
        self._read_token = read_token_fn   # None: modül düzeyindeki `read_token` (çağrı anında çözülür)
        self._run = run
        self._lock_factory = lock_factory
        self._mutex = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._active: Optional[Tuple[str, str]] = None   # (eylem no, son adım metni)
        self._done: Optional[Tuple[str, Result]] = None

    def busy(self) -> bool:
        with self._mutex:
            return self._active is not None

    def start(self, action_id: str) -> bool:
        """Eylemi başlatır; zaten biri sürüyorsa False."""
        with self._mutex:
            if self._active is not None:
                return False
            self._active, self._done = (action_id, "başlıyor…"), None
        self._thread = threading.Thread(target=self._work, args=(action_id,), name="watch-action", daemon=True)
        self._thread.start()
        return True

    def progress(self) -> Tuple[str, str]:
        """(eylemin görünen adı, son adım) — sürmüyorsa ("", "")."""
        with self._mutex:
            if self._active is None:
                return "", ""
            action = BY_ID.get(self._active[0])
            return (action.label if action else self._active[0]), self._active[1]

    def take_result(self) -> Optional[Tuple[str, Result]]:
        """Biten eylem (eylem no, sonuç); bir kez alınır."""
        with self._mutex:
            done, self._done = self._done, None
        return done

    def close(self, wait: float = ACTION_EXIT_WAIT_SECONDS) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(wait)

    def _set_step(self, text: str) -> None:
        with self._mutex:
            if self._active is not None:
                self._active = (self._active[0], text)

    def _work(self, action_id: str) -> None:
        target = f"{self.host}:{self.session}"
        lock = None
        try:
            lock = self._lock_factory(self.host, self.session)
            lock.acquire()
            diag_log("watch_action_begin", action=action_id, target=target)
            result = self._run(PanelClient(self.port, self._read_token or read_token), action_id, self.host,
                               self.session, on_step=self._set_step)
        except ActionBusy as e:
            result = Result(False, f"✗ {e}")
        except Exception as e:   # hiçbir hata thread'i sessizce öldürmesin: çubukta görünsün
            diag_log("watch_action_error", action=action_id, target=target, error=f"{type(e).__name__}: {e}"[:200])
            result = Result(False, f"✗ iç hata: {type(e).__name__}")
        finally:
            if lock is not None:
                try:
                    lock.release()
                except Exception:
                    pass
        diag_log("watch_action_end", action=action_id, target=target, ok=result.ok, message=result.message[:200],
                 new=result.name)
        with self._mutex:
            self._done, self._active = (action_id, result), None


class InputController:
    """Mirror'ın klavye kip makinesi (TBD#79): normal / yazı satırı / kısa tuş / ham geçiş onayı / ham geçiş / eylem.

    `Viewer` yalnız çizer, `watch_loop` yalnız taşıyıcıyı sürer; tuşların ne anlama geldiği ve "şu an oturuma bir şey
    yollanabilir mi" kararı burada. Çıkış yolu `sender` (arka plan thread'li HTTP); çubuğu `Viewer.overlay = bar` ile
    devralır. Kurallar (CLAUDE.md tmux kuralı + TBD#79):
      - bağlantı canlı değilken ya da pane maskeli girişteyse (parola istemi) HİÇBİR şey yollanmaz;
      - yazı satırı Enter'a kadar yalnız yerelde durur; kısa tuş ve ham geçiş açıkça açılır, kendiliğinden kapanır;
      - ham geçiş yalnız Enter onayıyla açılır, Ctrl-] ile kapanır, `RAW_IDLE_LOCK_SECONDS` tuşsuz kalınca kilitlenir;
      - eylem (TODO.md 2026-10-16): `a` + harf (handover, durdur + yeni isim, durdur, yeni chat, sıfırla); yıkıcı olanlar
        (durdur, durdur + yeni isim, sıfırla) ayrıca `y` ister; hepsi yerel panelin API'sinden gider, oturuma tuş
        göndermez (handover'ın metni hariç: o da maskeli girişte engellenir). Eylem sürerken `q` çıkarmaz.
    """

    # Kısa tuş kipi (Orta set): terminalden okunan jeton → panelin `ALLOWED_SPECIAL_KEYS` adı. Ctrl-C/Ctrl-D yok.
    SHORT_KEYS = {
        "\r": "Enter", "\n": "Enter", "\x1b": "Escape", "\t": "Tab", "\x1b[Z": "BTab",
        "\x1b[A": "Up", "\x1bOA": "Up", "\x1b[B": "Down", "\x1bOB": "Down",
        "\x1b[C": "Right", "\x1bOC": "Right", "\x1b[D": "Left", "\x1bOD": "Left",
    }
    KEY_LABELS = {"Enter": "Enter", "Escape": "Esc", "Tab": "Tab", "BTab": "Shift-Tab",
                  "Up": "↑", "Down": "↓", "Left": "←", "Right": "→"}
    _FLASH_STYLES = {"ok": STYLE_LIVE, "err": STYLE_SEVERE, "info": STYLE_INPUT}
    RAW_CHUNK_CHARS = 8000   # `/api/term/raw` tek istekte en çok 8192 karakter alır (web.MAX_TERM_RAW_CHARS)

    def __init__(self, viewer: Viewer, sender: Any, *, history: Optional[Any] = None, keys: Optional[Any] = None,
                 actions: Optional[Any] = None, clock: Callable[[], float] = time.monotonic):
        self.viewer = viewer
        self.sender = sender
        self._history = history   # HistoryClient; None = geçmişte kaydırma kapalı
        self._keys = keys
        self._actions = actions   # ActionRunner; None = eylem kipi (`a`) kapalı
        self._pending: Optional[Any] = None   # onay bekleyen yıkıcı eylem (window_actions.Action)
        self._clock = clock
        self._parser = KeyParser()
        self.mode = "normal"          # normal | compose | keys | rawask | raw | history | actions | confirm
        self.buf = ""                 # yazı satırı
        self._mode_until: Optional[float] = None   # keys / rawask zaman aşımı
        self._last_input = 0.0        # ham geçişte son tuşun anı
        self._raw_buf: List[str] = []
        self._flash: Optional[Tuple[str, str, float]] = None   # (metin, "ok"|"err"|"info", bitiş anı)
        self._labels: Dict[int, str] = {}   # gönderim no → çubukta görünecek ad
        # Geçmiş kipi: `_h_top` görünen ilk satırın tmux numarası (0 = pane'in ilk görünür satırı, negatifler scrollback),
        # `_h_ref` bu numaralamanın dayandığı history_size (yeni çıktı geldikçe büyür, önbellek ve `_h_top` buna göre
        # kaydırılır, böylece ekrandaki içerik yerinde kalır), `_h_lines` satır no → ANSI'li metin.
        self._h_top = 0
        self._h_ref = 0
        self._h_lines: Dict[int, str] = {}
        self._h_wanted: Optional[Tuple[int, int]] = None   # son istenen aralık (aynı aralık tekrar istenmesin)
        self._h_error = ""
        self._h_loading = False
        self._h_low_since: Optional[float] = None   # canlı kare bilinen geçmişten küçük history_size bildirmeye ne zaman başladı

    # ── dış arayüz ──

    def tick_seconds(self) -> float:
        """Döngünün uyanma aralığı: bir girdi kipi açıkken sık (yankı gecikmesin), değilken seyrek (boşta CPU)."""
        return TICK_SECONDS if self.mode == "normal" else INPUT_TICK_SECONDS

    def handle(self, chunk: str) -> bool:
        """`Keys.poll()` çıktısını işler (boş olabilir: zaman aşımları ve gönderim sonuçları da burada işlenir).
        True = görüntüleyiciden çık."""
        now = self._clock()
        self._collect_results(now)
        self._collect_action(now)
        self._expire(now)
        quit_requested = False
        for tok in self._parser.feed(chunk, now):
            if self.mode == "raw":
                self._on_raw(tok, now)
            elif self.mode == "actions":
                self._on_actions(tok, now)
            elif self.mode == "confirm":
                self._on_confirm(tok, now)
            elif self.mode == "compose":
                self._on_compose(tok, now)
            elif self.mode == "keys":
                self._on_keys(tok, now)
            elif self.mode == "rawask":
                self._on_rawask(tok, now)
            elif self.mode == "history":
                self._on_history(tok, now)
            elif self._on_normal(tok, now):
                quit_requested = True
                break
        self._flush_raw()
        if self.mode == "history":
            self._history_tick(now)
        return quit_requested

    def shutdown(self) -> None:
        """Çıkışta: ham geçiş açıksa terminal ayarlarını geri alır; bekleyen gönderimleri bitirir."""
        if self.mode == "raw":
            self._leave_raw(None, self._clock())
        if self.mode == "history":
            self._leave_history()
        if self._history is not None:
            self._history.close()
        self.sender.close()
        if self._actions is not None:
            self._actions.close()   # yarım kalmış bileşik eylem (durdurdu, yeni chat'i açmadı) bitsin

    def bar(self, cols: int) -> Optional[Tuple[str, str]]:
        """Durum çubuğunun yerine geçecek (metin, stil); None = normal durum çubuğu."""
        now = self._clock()
        flash = self._live_flash(now)
        if self.mode == "normal" and self._actions is not None and self._actions.busy():
            label, step = self._actions.progress()
            return (f" … {label}: {step}", STYLE_INPUT)
        if self.mode == "actions":
            menu = " · ".join(f"{a.key} {a.short}" for a in ACTIONS)
            return (f" ⚙ işlem ▸ {menu}    (başka tuş: iptal)", STYLE_INPUT)
        if self.mode == "confirm" and self._pending is not None:
            return (f" ⚠ {self._pending.label}: {self._target()}? {self._pending.does} · y: onayla · başka tuş: vazgeç",
                    STYLE_RAW)
        if self.mode == "compose":
            return self._compose_bar(cols, flash)
        if self.mode == "history":
            return self._history_bar()
        if self.mode == "keys":
            return (" ⌨ kısa tuş ▸ Enter · Esc · ↑ ↓ ← → · Tab · Shift-Tab    (başka tuş ya da k: iptal)", STYLE_INPUT)
        if self.mode == "rawask":
            return (" ⚠ HAM GEÇİŞ açılsın mı? Her tuş (Ctrl-C dahil) oturuma gider · Enter: onayla · Esc: vazgeç", STYLE_RAW)
        if self.mode == "raw":
            text = " ⚠ HAM GEÇİŞ · her tuş oturuma gider · Ctrl-] çıkış"
            if flash and flash[1] == "err":
                text += f" · {flash[0]}"
            remaining = RAW_IDLE_LOCK_SECONDS - (now - self._last_input)
            if remaining <= RAW_COUNTDOWN_SECONDS:
                text += f" · {max(math.ceil(remaining), 0)} sn sonra kilitlenir"
            return (text, STYLE_RAW)
        if flash:
            return (" " + flash[0], self._FLASH_STYLES[flash[1]])
        return None

    # ── bildirim, gönderim sonuçları, zaman aşımları ──

    def _set_flash(self, text: str, kind: str, until: float) -> None:
        self._flash = (clean_text(text), kind, until)

    def _error(self, text: str, now: float) -> None:
        self._set_flash(text, "err", now + FLASH_ERR_SECONDS)

    def _live_flash(self, now: float) -> Optional[Tuple[str, str, float]]:
        if self._flash is not None and now >= self._flash[2]:
            self._flash = None
        return self._flash

    def _collect_results(self, now: float) -> None:
        for seq, _kind, ok, err in self.sender.take_results():
            label = self._labels.pop(seq, None)
            if ok:
                if label:   # ham geçişin yığınları etiketsiz: her tuşta "gönderildi" yanıp sönmesin
                    self._set_flash(f"✓ {label} gönderildi", "ok", now + FLASH_OK_SECONDS)
            else:
                self._error(f"✗ {label or 'tuş'} gönderilemedi: {err}", now)

    def _expire(self, now: float) -> None:
        if self.mode in ("keys", "rawask", "actions", "confirm") and self._mode_until is not None and now >= self._mode_until:
            self._to_normal()
        elif self.mode == "raw" and now - self._last_input >= RAW_IDLE_LOCK_SECONDS:
            self._leave_raw("ham geçiş boşta kilitlendi", now)

    def _gate(self) -> Optional[str]:
        """None = şimdi yollanabilir; aksi halde çubukta gösterilecek neden."""
        v = self.viewer
        if v.state != "live" or v.frame is None:
            return "✗ bağlantı canlı değil: gönderilmedi"
        if v.frame.get("masked"):
            return "✗ pane maskeli girişte (parola istemi?): buradan gönderilmez, web popup'ını kullanın"
        return None

    def _send(self, kind: str, payload: str, label: Optional[str], now: float) -> None:
        seq = self.sender.submit(kind, payload)
        if label:
            self._labels[seq] = label
            self._set_flash(f"… {label} gönderiliyor", "info", now + HTTP_TIMEOUT_SECONDS)

    # ── normal ──

    def _to_normal(self) -> None:
        self.mode, self.buf, self._mode_until, self._pending = "normal", "", None, None

    def _on_normal(self, tok: str, now: float) -> bool:
        if isinstance(tok, Paste):   # yapıştırılan metindeki harfler komut sayılmaz
            return False
        if tok in _UP:
            self._enter_history("up1", now)
            return False
        if tok in _PGUP:
            self._enter_history("pgup", now)
            return False
        if tok in _HOME:
            self._enter_history("home", now)
            return False
        low = tok.lower()
        if low == "q":
            if self._actions is not None and self._actions.busy():   # çıkış, bileşik eylemi yarıda keserdi
                self._error("✗ eylem sürüyor: bitince çıkın", now)
                return False
            return True
        if low == "a" and self._actions is not None:
            if self._actions.busy():
                self._error("✗ başka bir eylem sürüyor", now)
            else:
                self.mode, self._mode_until = "actions", now + ACTION_MODE_SECONDS
            return False
        if low == "x":
            self.viewer.dismiss_popup()
        elif low == "i":
            self.mode, self.buf = "compose", ""
        elif low == "k":
            self.mode, self._mode_until = "keys", now + KEYS_MODE_SECONDS
        elif tok == "R":   # ham geçiş bilerek yalnız büyük harf: kazara `r` yetmesin
            self.mode, self._mode_until = "rawask", now + RAW_CONFIRM_SECONDS
        return False

    # ── eylemler (TODO.md 2026-10-16) ──

    def _target(self) -> str:
        v = self.viewer
        return v.session if v.host == LOCAL_HOST_NAME else f"{v.host}:{v.session}"

    def _collect_action(self, now: float) -> None:
        if self._actions is None:
            return
        done = self._actions.take_result()
        if done is not None:
            _action_id, result = done
            self._set_flash(result.message, "ok" if result.ok else "err", now + ACTION_RESULT_SECONDS)

    def _on_actions(self, tok: str, now: float) -> None:
        """`a` sonrası TEK harf: eylemi seçer (yıkıcıysa önce onay ister); başka her tuş iptaldir."""
        action = None if isinstance(tok, Paste) else BY_KEY.get(tok.lower())
        self._to_normal()
        if action is None:
            return
        if action.confirm:
            self.mode, self._pending, self._mode_until = "confirm", action, now + ACTION_CONFIRM_SECONDS
            return
        self._start_action(action, now)

    def _on_confirm(self, tok: str, now: float) -> None:
        """Yıkıcı eylem: yalnız `y` onaylar, başka her tuş (Enter dahil) vazgeçer."""
        action = self._pending
        self._to_normal()
        if action is not None and not isinstance(tok, Paste) and tok in ("y", "Y"):
            self._start_action(action, now)

    def _start_action(self, action: Any, now: float) -> None:
        if self._actions is None:
            return
        if action.id == "handover":   # oturuma metin yazar: maskeli girişe (parola istemi) YAZILMAZ, bağlantı canlı olmalı
            reason = self._gate()
            if reason:
                self._error(reason, now)
                return
        if not self._actions.start(action.id):
            self._error("✗ başka bir eylem sürüyor", now)
            return
        self._flash = None

    # ── yazı satırı ──

    def _insert(self, text: str) -> None:
        self.buf = (self.buf + text)[:COMPOSE_MAX_CHARS]

    def _on_compose(self, tok: str, now: float) -> None:
        self._flash = None   # düzenlemeye devam eden kişi hata bildirimini görmüş sayılır
        if isinstance(tok, Paste):
            self._insert(one_line(tok))
        elif tok in ("\r", "\n"):
            self._submit_compose(now)
        elif tok == "\x1b":
            self._to_normal()
        elif tok in ("\x7f", "\x08"):
            self.buf = drop_last_char(self.buf)
        elif tok == "\x15":   # Ctrl-U
            self.buf = ""
        elif tok == "\x17":   # Ctrl-W
            self.buf = drop_last_word(self.buf)
        elif len(tok) == 1 and _printable(tok):
            self._insert(tok)
        # diğer denetim karakterleri ve kaçış dizileri (oklar, F tuşları, Alt+x) yok sayılır

    def _submit_compose(self, now: float) -> None:
        text = self.buf.strip()
        if not text:
            return
        reason = self._gate()
        if reason:   # satır korunur: bağlantı gelince ya da düzeltilince aynı Enter yollar
            self._error(reason, now)
            return
        self._send("text", text, "mesaj", now)
        self._to_normal()

    def _compose_bar(self, cols: int, flash: Optional[Tuple[str, str, float]]) -> Tuple[str, str]:
        if flash and flash[1] == "err":   # neden yollanmadığı satırdan önemli; ilk tuşta kalkar
            return (" " + flash[0], STYLE_SEVERE)
        hint = "⏎ gönder · Esc iptal" if self.viewer.state == "live" else "bağlantı canlı değil: gönderilmez"
        prefix, cursor = " ✎ ▸ ", "█"
        room = cols - display_width(prefix) - display_width(cursor) - 1
        hint_w = display_width(hint) + 2
        if room < hint_w + 12:   # dar pencerede ipucu yazının yerini yemesin
            hint, hint_w = "", 0
        body = tail_fit(self.buf, room - hint_w)
        left = prefix + body + cursor
        gap = max(cols - display_width(left) - display_width(hint) - 1, 1) if hint else 0
        return (left + " " * gap + hint, STYLE_INPUT)

    # ── kısa tuş ──

    def _on_keys(self, tok: str, now: float) -> None:
        name = None if isinstance(tok, Paste) else self.SHORT_KEYS.get(tok)
        self._to_normal()   # tek tuş: ne basılırsa kip kapanır (`k`, bilinmeyen tuş, Esc dahil)
        if name is None:
            return
        reason = self._gate()
        if reason:
            self._error(reason, now)
            return
        self._send("key", name, self.KEY_LABELS[name], now)

    # ── geçmişte kaydırma (TBD#79) ──

    def _geometry(self) -> Optional[Tuple[int, int, int]]:
        """(görünen satır sayısı, pane satırı, history_size); kare yoksa None. Görünen satır: pencerenin gövdesi
        (çubuk hariç), pane'den uzun olamaz."""
        frame = self.viewer.frame
        if not frame:
            return None
        rows, hist = frame.get("rows"), frame.get("history_size")
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (rows, hist)) or rows < 1:
            return None
        return min(max(self.viewer.screen.size()[1] - 1, 1), rows), rows, max(hist, 0)

    def _enter_history(self, how: str, now: float) -> None:
        if self._history is None:
            return
        geo = self._geometry()
        if self.viewer.state != "live" or geo is None:
            self._error("✗ bağlantı canlı değil: geçmiş alınamaz", now)
            return
        view, rows, hist = geo
        if hist <= 0 and rows <= view:
            self._set_flash("kaydırılacak geçmiş yok", "info", now + FLASH_ERR_SECONDS)
            return
        self.mode = "history"
        self._h_ref, self._h_lines, self._h_error, self._h_wanted, self._h_loading = hist, {}, "", None, True
        self._h_low_since = None
        self._h_top = rows - view   # canlı konum
        self._scroll(how)

    def _scroll(self, how: str) -> None:
        geo = self._geometry()
        if geo is None:
            self._leave_history()
            return
        view, _rows, _ = geo
        page = max(view - 1, 1)
        top = {"up1": self._h_top - 1, "down1": self._h_top + 1, "pgup": self._h_top - page,
               "pgdn": self._h_top + page, "home": -self._h_ref}[how]
        self._h_top = max(top, -self._h_ref)   # canlı konuma inildiyse `_history_tick` kipten çıkarır (tek kaynak)

    def _leave_history(self, why: Optional[str] = None) -> None:
        self.mode, self._h_lines, self._h_wanted, self._h_error, self._h_loading = "normal", {}, None, "", False
        self.viewer.set_body_override(None)
        if why:
            self._set_flash(why, "info", self._clock() + FLASH_ERR_SECONDS)

    def _sync_ref(self, hist: int) -> None:
        """Geçmiş büyüdüyse (yeni çıktı) numaralamayı hizalar: eski satırlar `-büyüme` kadar kayar, görünen sayfa aynı
        içerikte kalır. Yalnız BÜYÜME işlenir: bilinenden küçük bir değer ya daha eski bir numaralamadır (sayfa yanıtı
        büyümeden önce hesaplanmıştı, `_merge` aradaki farkı kendisi telafi eder) ya da bayat bir canlı karedir;
        gerçekten temizlenmiş geçmiş `_history_tick`te süreyle ayırt edilir. Tavanda (tmux'un `HISTORY_LIMIT`i)
        satırlar sessizce düşer ve history_size sabit kalır: orada kayma ölçülemez, sayfa kayabilir."""
        if hist <= self._h_ref:
            return
        grew = hist - self._h_ref
        self._h_lines = {k - grew: v for k, v in self._h_lines.items()}
        self._h_top -= grew
        self._h_ref = hist
        self._h_wanted = None

    def _merge(self, payload: dict) -> None:
        self._sync_ref(payload["history_size"])
        if self.mode != "history":
            return
        shift = self._h_ref - payload["history_size"]   # yanıt daha eski bir numaralamayla geldiyse
        start = payload["start"]
        lines = payload["text"].split("\n")
        for i, line in enumerate(lines):
            self._h_lines[start + i - shift] = line
        end = payload.get("end")
        if isinstance(end, int):   # sunucu daha az satır verdiyse eksikler boş sayılır (sonsuz yeniden istek olmasın)
            for k in range(start + len(lines), end + 1):
                self._h_lines[k - shift] = ""

    def _history_tick(self, now: float) -> None:
        """Her turda: canlı karedeki history_size ile hizala, gelen sayfaları önbelleğe al, eksik satır varsa tek
        istek yolla, görünen sayfa tamamsa gövdeye ver."""
        geo = self._geometry()
        if geo is None or self._history is None:
            self._leave_history()
            return
        view, rows, hist = geo
        self._sync_ref(hist)
        if hist < self._h_ref:
            if self._h_low_since is None:
                self._h_low_since = now
            elif now - self._h_low_since > HISTORY_SHRINK_GRACE_SECONDS:
                self._leave_history("geçmiş değişti, canlıya dönüldü")
                return
        else:
            self._h_low_since = None
        for _start, _end, payload, err in self._history.take_results():
            if payload is None:
                self._h_error = clean_text(err)
            else:
                self._h_error = ""
                self._merge(payload)
                if self.mode != "history":
                    return
        top = max(self._h_top, -self._h_ref)
        if top >= rows - view:
            self._leave_history()
            return
        self._h_top = top
        lo = -self._h_ref
        near = range(max(lo, top - view // 2), min(rows - 1, top + view - 1 + view // 2) + 1)
        want = (max(lo, top - view), min(rows - 1, top + 2 * view - 1))
        if any(k not in self._h_lines for k in near) and want != self._h_wanted:
            want = (want[0], min(want[1], want[0] + HISTORY_MAX_REQUEST_LINES - 1))
            self._h_wanted = want
            self._history.request(*want)
        self._h_loading = any(top + i not in self._h_lines for i in range(view))
        if not self._h_loading:
            self.viewer.set_body_override([self._h_lines[top + i] for i in range(view)])

    def _on_history(self, tok: str, now: float) -> None:
        if isinstance(tok, Paste):
            return
        self._h_wanted = None   # her tuş (örneğin hata sonrası) yeniden deneme hakkıdır
        if tok in _UP:
            self._scroll("up1")
        elif tok in _DOWN:
            self._scroll("down1")
        elif tok in _PGUP:
            self._scroll("pgup")
        elif tok in _PGDN:
            self._scroll("pgdn")
        elif tok in _HOME or tok == "g":
            self._scroll("home")
        elif tok in _END or tok in ("G", "\x1b", "q", "Q"):   # q burada çıkış değil, canlıya dönüş
            self._leave_history()
        elif tok.lower() in ("i", "k", "x") or tok == "R":    # diğer kipler canlı ekranda açılır
            self._leave_history()
            self._on_normal(tok, now)

    def _history_bar(self) -> Tuple[str, str]:
        geo = self._geometry()
        view, rows, _ = geo if geo else (1, 1, 0)
        back, total = (rows - view) - self._h_top, self._h_ref + (rows - view)
        head = f" ⇡ GEÇMİŞ {back}/{total}"
        if self._h_error:   # hata varken tuş ipuçları çubuktan çıkar: dar pencerede mesaj kesilmesin
            return f"{head} · ✗ {self._h_error} · End: canlı", STYLE_HISTORY
        text = f"{head} satır · PgUp/PgDn ↑↓ gez · Home başa · End/Esc/q canlı"
        if self._h_loading:
            text += " · yükleniyor…"
        return text, STYLE_HISTORY

    # ── ham geçiş ──

    def _on_rawask(self, tok: str, now: float) -> None:
        if not isinstance(tok, Paste) and tok in ("\r", "\n"):   # yapıştırılan bir satır sonu onay değildir
            self.mode, self._mode_until, self._last_input, self._raw_buf = "raw", None, now, []
            if self._keys is not None:
                self._keys.set_passthrough(True)
        else:
            self._to_normal()

    def _leave_raw(self, why: Optional[str], now: float) -> None:
        self._flush_raw()
        self._to_normal()
        if self._keys is not None:
            self._keys.set_passthrough(False)
        if why:
            self._set_flash(why, "info", now + FLASH_ERR_SECONDS)

    def _on_raw(self, tok: str, now: float) -> None:
        self._last_input = now
        if not isinstance(tok, Paste) and tok == RAW_EXIT_KEY:   # yapıştırılan Ctrl-] çıkış tuşu değil, veridir
            self._leave_raw("ham geçiş kapandı", now)
            return
        if isinstance(tok, Paste):
            if "\n" in tok or "\r" in tok:   # çok satırlı yapıştırma satır satır Enter'a dönüşüp hepsini yollardı
                self._error("✗ çok satırlı yapıştırma ham geçişte gönderilmez: yazı satırını (i) kullanın", now)
                return
            data = str(tok)
        else:
            data = tok
        reason = self._gate()
        if reason:
            self._error(reason, now)
            return
        self._raw_buf.append(data)

    def _flush_raw(self) -> None:
        """Bu turda biriken ham tuşlar tek istekte (sıra korunur); `/api/term/raw` sınırına göre parçalanır."""
        if not self._raw_buf:
            return
        data, self._raw_buf = "".join(self._raw_buf), []
        for i in range(0, len(data), self.RAW_CHUNK_CHARS):
            self._send("raw", data[i:i + self.RAW_CHUNK_CHARS], None, self._clock())


def _quit_requested(keys: Optional[Any], stop: threading.Event, viewer: Optional[Viewer] = None,
                    controller: Optional[InputController] = None) -> bool:
    """Tuşları okur. `controller` yoksa: `q` çıkış, `x` (viewer verilmişse) sorun kutusunu gizler. `controller` varsa
    tuşlar ona gider (girdi kipleri dahil). Çıkış istendi mi döner."""
    if keys is not None:
        chunk = keys.poll()
        if controller is not None:
            if controller.handle(chunk):
                stop.set()
        elif wants_quit(chunk):
            stop.set()
        elif viewer is not None and wants_dismiss(chunk):
            viewer.dismiss_popup()
    return stop.is_set()


def _wait_with_ticks(viewer: Viewer, seconds: float, *, stop: threading.Event, keys: Optional[Any],
                     clock: Callable[[], float], sleep: Callable[[float], None],
                     controller: Optional[InputController] = None) -> None:
    """Yeniden bağlanma beklemesi: bekleme boyunca çubuk geri sayımı ve saat güncellenir, `q` dinlenir."""
    end = clock() + seconds
    while not _quit_requested(keys, stop, viewer, controller) and not viewer.screen.dead:
        remaining = end - clock()
        if remaining <= 0:
            break
        viewer.set_retry_in(remaining)
        viewer.render()
        sleep(min(controller.tick_seconds() if controller is not None else TICK_SECONDS, remaining))
    viewer.set_retry_in(None)


def watch_loop(viewer: Viewer, ws: Optional[WsTransport], rest: RestTransport, *, mode: str = "auto",
               stop: threading.Event, keys: Optional[Any] = None, backoff: Optional[Backoff] = None,
               clock: Callable[[], float] = time.monotonic,
               sleep: Callable[[float], None] = time.sleep,
               controller: Optional[InputController] = None) -> None:
    """Kendiliğinden ASLA çıkmaz: yalnız `stop` (q / sinyal) ya da pencerenin kapanması bitirir.

    auto: önce WS. WS hiç kare vermeden kurulamazsa (panel WS'siz/eski ya da WS yolu bozuksa) hemen
    REST denenir ve `REST_FALLBACK_SECONDS` boyunca REST'te kalınır, sonra WS tekrar denenir. Panel
    gerçekten kapalıysa REST de hata verir ve üstel bekleme (`Backoff`) devreye girer.

    `controller` (girdi kipleri) verilirse tuşlar ona gider ve döngü, bir kip açıkken `INPUT_TICK_SECONDS`'ta uyanır."""
    backoff = backoff or Backoff()
    use_rest_until = 0.0
    tick: Any = controller.tick_seconds if controller is not None else TICK_SECONDS
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
            gen = transport.frames(stop, tick)
            for frame in gen:
                if _quit_requested(keys, stop, viewer, controller) or viewer.screen.dead:
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
        _wait_with_ticks(viewer, backoff.next(), stop=stop, keys=keys, clock=clock, sleep=sleep,
                         controller=controller)


# ── terminale sızıntıyı kes ─────────────────────────────────────────────────────────────────

class _DiagLogHandler(logging.Handler):
    """`logging` kayıtlarını (WARNING+) terminale değil `diag.log`'a yazar; titreyen bir bağlantı
    dosyayı doldurmasın diye `MIN_INTERVAL_SECONDS`te en çok bir satır."""

    MIN_INTERVAL_SECONDS = 5.0

    def __init__(self, target: str, clock: Callable[[], float] = time.monotonic):
        super().__init__(level=logging.WARNING)
        self._target = target
        self._clock = clock
        self._last: Optional[float] = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            now = self._clock()
            if self._last is not None and now - self._last < self.MIN_INTERVAL_SECONDS:
                return
            self._last = now
            exc = record.exc_info[1] if record.exc_info else None
            diag_log("watch_lib_log", target=self._target, logger=record.name, level=record.levelname,
                     msg=record.getMessage()[:200], error=f"{type(exc).__name__}: {exc}"[:200] if exc else "")
        except Exception:
            pass


@contextlib.contextmanager
def quiet_terminal(target: str) -> Iterator[None]:
    """Blok boyunca terminale (stderr) hiçbir kütüphane çıktısı sızmaz: kök `logging` logger'ına bir
    handler konur (böylece `logging.lastResort`un stderr çıktısı hiç devreye girmez) ve thread'lerde
    yakalanmamış istisnalar `threading.excepthook` yerine `diag.log`'a yazılır. Neden: `websockets`'in
    keepalive thread'i hata verince `logger.error(..., exc_info=True)` ile traceback basar; görüntüleyici
    alt-ekranda mutlak konumla çizdiği için o satırlar gövdenin üstüne biner ve gövde yalnız DEĞİŞİNCE
    yeniden çizildiğinden sessiz bir pane'de çöp, son durumun yerinde kalır."""
    handler = _DiagLogHandler(target)
    root = logging.getLogger()
    root.addHandler(handler)
    old_hook = threading.excepthook

    def hook(args: Any) -> None:
        if args.exc_type is SystemExit:
            return
        diag_log("watch_thread_error", target=target, thread=getattr(args.thread, "name", "?"),
                 error=f"{getattr(args.exc_type, '__name__', '?')}: {args.exc_value}"[:200])

    threading.excepthook = hook
    try:
        yield
    finally:
        threading.excepthook = old_hook
        root.removeHandler(handler)


# ── CLI ─────────────────────────────────────────────────────────────────────────────────

def register(sub) -> None:
    p = sub.add_parser("watch", help="bir session'ın terminalini bu pencerede canlı göster (i: mesaj yaz, k: kısa tuş, "
                                     "R: ham geçiş, a: işlem; --read-only ile yalnız izle): watch [host:]ad")
    p.add_argument("target", help="host:ad (yerel session için yalnız ad). host, panelde kayıtlı host adı")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"yerel panelin portu (varsayılan {DEFAULT_PORT}); `py/cops web [--port]` ile aynı olmalı")
    p.add_argument("--transport", choices=("auto", "ws", "rest"), default="auto",
                   help="auto: WS, kurulamazsa REST (varsayılan); ws / rest: yalnız o")
    p.add_argument("--once", action="store_true", help="tek kare bas ve çık (REST; TTY gerekmez)")
    p.add_argument("--plain", action="store_true", help="--once ile: renk kaçışlarını at")
    p.add_argument("--no-resize", action="store_true", help="pencereyi pane boyutuna istemeyi kapat")
    p.add_argument("--read-only", action="store_true",
                   help="girdi kiplerini (i yazı satırı, k kısa tuş, R ham geçiş, a işlem) kapat: oturuma hiçbir tuş gitmez")
    p.set_defaults(func=run)


def history_warn_at() -> int:
    """Ayarlar'daki `history_warn_at` (panelin Terminal göstergesi ve "dikkat gerekenleri seç" düğmesiyle AYNI eşik);
    okunamazsa varsayılan. Görüntüleyici yerel makinede koşar, ayar dosyası aggregator'ın kendisidir."""
    try:
        from ..settings import load_settings
        value = load_settings().get("history_warn_at")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    except Exception:
        pass
    return DEFAULT_HISTORY_WARN_AT


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

    screen = Screen(sys.stdout, title=f"{host}:{name}", bracketed_paste=not args.read_only)
    viewer = Viewer(host, name, screen, resize=not args.no_resize)
    viewer.history_warn_at = history_warn_at()
    screen.enter()
    try:
        with Keys() as keys, quiet_terminal(f"{host}:{name}"):
            controller: Optional[InputController] = None
            if not args.read_only:
                controller = InputController(viewer, InputSender(args.port, host, name),
                                             history=HistoryClient(args.port, host, name), keys=keys,
                                             actions=ActionRunner(args.port, host, name))
                viewer.overlay = controller.bar
                viewer.hint = INPUT_HINT
            try:
                watch_loop(viewer, ws, rest, mode=args.transport, stop=stop, keys=keys, controller=controller)
            finally:
                if controller is not None:
                    controller.shutdown()   # ham geçiş açıksa terminal ayarlarını geri al, bekleyen gönderimleri bitir
    except KeyboardInterrupt:
        pass
    finally:
        screen.leave()
    return 0
