"""`web_term_lite` — terminal karesinin "lite" biçimi (TODO.md 2026-10-08 "Terminal karesi çok büyük").

Sorun: `web._term_output` her kareye `capture-pane -S -2000`'in TAMAMINI (scrollback +
görünür ekran) koyuyor; ulak_31'de ~197 KB, oysa görünür bölge bunun yalnız %4-17'si. Tek bir
spinner karakteri bile tüm metni yeniden yollatıyor ve tarayıcı her seferinde 2000 satırı
xterm'e baştan yazıyor.

Lite kare: `text` yalnız GÖRÜNÜR `rows` satırı; scrollback istemci kaydırınca ayrıca, tam
(lite'sız) `/api/term/output` ile bir kez çekilir. Eskiden tam metinden türeyen iki şey
KAYBOLMASIN diye sunucuda hesaplanıp kareye eklenir:
  - `urls` / `paths`: `UrlBanner.tsx`'in `extractTermUrls` / `extractTermPathCandidates`'ının
    AYNISI (en yeni 3 URL, en yeni 8 yol adayı). Login URL'si bir süre sonra ekrandan kayar
    ama şeritte durmalı; tam metin artık istemcide olmadığı için çıkarım burada yapılır.
  - `lite: True` işareti: işaretsiz kare (eski backend) istemcide eski yoldan işlenir, yani
    ön yüz ile backend'in deploy sırası önemsizdir.

Kırpma kayıpsızdır: `tmux capture-pane -e` her satırı kendi içinde kapatır (satır sonunda SGR
sıfırlanır) ve tam capture'ın son `rows` satırı, görünür-ekran capture'ına birebir eşittir
(tmux 3.2a'da özel soketle doğrulandı; `py/tests/test_web_term_lite.py` aynısını gerçek tmux ile
tekrar eder).

Saf fonksiyonlar: I/O yok, `web.py`'yi geri-import ETMEZ (`web_ws.py` ile aynı ilke). Yerel
`_term_output`, `web_hosts.proxy_get` ve relay (`term_output_relay`) kaynaklı karelerin
HEPSİ aynı dönüşümden geçsin diye çağıran taraf rotadır, `_term_output` değil.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..tmux_backend import strip_ansi

MAX_URLS = 3
MAX_PATH_CANDIDATES = 8

# `UrlBanner.tsx`'in TERM_URL_RE / TERM_PATH_RE / sondaki-noktalama kırpıcısıyla AYNI diller.
# Biri değişirse diğeri de değişmeli, yoksa lite karedeki şerit tam karedekinden sapar.
# `_PATH_RE`, UrlBanner'daki `(?:~|\.{1,2})?/...` ile AYNI dilin (`~/`, `./`, `../`, `/` önekleri)
# hızlı yazımı: isteğe bağlı grup her konumda denenince `re` ~7x yavaşlıyordu (190 KB'lık
# capture'da 14 ms, bu şekilde ~2 ms). Eşdeğerlik testle kilitli
# (`test_path_regex_equals_ui_banner_pattern`).
_URL_RE = re.compile(r"https?://[^\s<>\"'\x1b\x07]+")
_PATH_RE = re.compile(r"(?:~/|\.\.?/|/)[^\s<>\"'\x1b\x07]+")
_TRAILING_PUNCT_RE = re.compile(r"[.,;:)\]}>'\"]+$")


def _newest_first(matches: List[str], cap: int, min_len: int = 1) -> List[str]:
    """Sondan başa, tekilleştirilmiş, `cap` ile sınırlı, sondaki noktalaması kırpılmış."""
    seen = set()
    out: List[str] = []
    for m in reversed(matches):
        if len(out) >= cap:
            break
        cand = _TRAILING_PUNCT_RE.sub("", m)
        if len(cand) >= min_len and cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out


def extract_urls(text: str) -> List[str]:
    return _newest_first(_URL_RE.findall(strip_ansi(text)), MAX_URLS)


def extract_path_candidates(text: str) -> List[str]:
    # `p.length > 1` (UrlBanner): tek "/" aday değil. Gerçek süzme sunucuda (`_files_validate`).
    return _newest_first(_PATH_RE.findall(strip_ansi(text)), MAX_PATH_CANDIDATES, min_len=2)


def _scan_lines(text: str, cache: Optional[Dict[str, Tuple[List[str], List[str]]]]):
    """`text`teki URL ve yol eşleşmelerini SATIR SATIR toplar: (urls, paths, fresh).

    Eşleşmeler boşluk (dolayısıyla newline) içeremediği için sonuç, tüm metni tek seferde
    taramakla (`extract_*`) AYNI; fark yalnız hız: scrollback satırları kareler arasında
    değişmez, yeni olan çoğunlukla görünür satırlar. Önceki taramada görülen satır `cache`ten
    gelir; tüm metni baştan taramak (yol deseni ~10 ms) meşgul bir pane'de her tick'e
    biniyordu, bu yolla ~3 ms. `fresh` yalnız BU metindeki satırları tutar, cache'e geri
    verilir ve böylece sınırsız büyüyemez (en çok HISTORY_LIMIT+rows girdi).

    Tek sapma: bitmemiş bir OSC dizisi (`\\x1b]...` BEL'siz) tam metin taramasında sonraki
    satırları yutabilirdi, satır satırda yutamaz. `tmux capture-pane -e` böyle bir çıktı
    üretmez (köprüleri BEL'siz `ST` ile kapanır ve zaten eşleşmez)."""
    fresh: Dict[str, Tuple[List[str], List[str]]] = {}
    urls: List[str] = []
    paths: List[str] = []
    for line in text.split("\n"):
        hit = fresh.get(line)
        if hit is None:
            hit = cache.get(line) if cache else None
            if hit is None:
                clean = strip_ansi(line)
                hit = (_URL_RE.findall(clean), _PATH_RE.findall(clean))
            fresh[line] = hit
        if hit[0]:
            urls += hit[0]
        if hit[1]:
            paths += hit[1]
    return urls, paths, fresh


def viewport_text(text: str, rows: int) -> str:
    """Tam capture'ın son `rows` satırı, SONDAKİ newline'sız.

    `capture-pane -p` çıktısı "\\n" ile biter; xterm'e olduğu gibi yazılırsa son satırdaki "\\n"
    ekranı bir satır kaydırır (üst satır kaybolur, altta boş satır kalır). Newline'ı atınca
    `rows` satır tam `rows` satırlık ekrana oturur."""
    body = text[:-1] if text.endswith("\n") else text
    return "\n".join(body.split("\n")[-rows:])


def to_lite(payload: Dict[str, Any], memo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """`_term_output`-şekilli tam bir kareyi lite kareye çevirir; çevrilemezse AYNEN döndürür.

    `ok:false` kareler ve `rows`'u bilinmeyen kareler (tmux boyutu okunamadı) kırpılmaz, `lite`
    işareti de taşımaz: istemci onları eski yoldan işler. Zaten `lite` işaretli bir kare de
    AYNEN döner (yeniden kırpmak tam metindeki URL'leri kaybettirirdi).

    `memo` çağıranın tuttuğu (bağlantı başına) bir sözlük, iki işe yarar: aynı tam metin art
    arda gelirse (sessiz pane, tick'lerin çoğu) çıkarım hiç tekrarlanmaz; metin değiştiyse yalnız
    YENİ satırlar taranır (`_scan_lines`). Memo'suz çağrı (REST) tam metni tek geçişte tarar:
    soğuk durumda satır satır tarama ondan ~2× yavaş. Girdi sözlüğü DEĞİŞTİRİLMEZ (relay kareyi
    paylaşabilir)."""
    if not isinstance(payload, dict) or not payload.get("ok") or payload.get("lite"):
        return payload
    text = payload.get("text")
    rows = payload.get("rows")
    if not isinstance(text, str) or isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
        return payload
    if memo is None:
        urls, paths = extract_urls(text), extract_path_candidates(text)
    elif memo.get("text") == text:
        urls, paths = memo["urls"], memo["paths"]
    else:
        raw_urls, raw_paths, fresh = _scan_lines(text, memo.get("lines"))
        urls = _newest_first(raw_urls, MAX_URLS)
        paths = _newest_first(raw_paths, MAX_PATH_CANDIDATES, min_len=2)
        memo.update(text=text, urls=urls, paths=paths, lines=fresh)
    out = dict(payload)
    out["text"] = viewport_text(text, rows)
    out["lite"] = True
    out["urls"] = urls
    out["paths"] = paths
    return out
