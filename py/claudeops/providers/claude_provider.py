"""claude CLI provider — bugüne kadarki tek/varsayılan davranış, aynen taşındı."""
from __future__ import annotations
import json
import os
import re
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from .base import CliProvider, McpServerSpec, _Switch, cmd_arg as _arg, _path_part_ok
from ..paths import CLAUDE_MODELS_JSON, CLAUDEOPS_DIR, PROJECTS_DIR, SESSIONS_DIR, proc_stat_fields
from .. import preview
from ..childgroup import _run_grouped
from ..diaglog import diag_log
from ..routing import claude_guidance_path
from ..settings import resolved_binary

MODEL_CHOICES = [
    "claude-sonnet-5-5",
    "claude-opus-5-5",
    "claude-fable-5-2",
    "claude-haiku-5-5",
]
PERMISSION_MODES = ["auto", "acceptEdits", "bypassPermissions", "manual", "dontAsk", "plan"]
EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]
# Sabitlenmiş (pinned) sonnet id'si: `claude-sonnet-5`, `claude-sonnet-5-5`,
# opsiyonel `[1m]` benzeri bağlam eki. Takma ad (`sonnet`, `sonnet[1m]`),
# tarihli id'ler (`...-20250929`) ve diğer aileler BİLEREK eşleşmez.
_SONNET_PIN_RE = re.compile(r"^(claude-sonnet-)(\d{1,2}(?:-\d{1,2})?)(\[[^\]]*\])?$")


def _sonnet_version(model_id: str) -> Tuple[int, ...]:
    m = _SONNET_PIN_RE.match(model_id)
    return tuple(int(p) for p in m.group(2).split("-")) if m else ()


# `/usage`'ın çıktısını `parse_usage_text()`'in ayrıştırdığı desen — o metodun
# kendi docstring'ine bkz. gerçek örnek metin için.
_USAGE_HEADER_RE = re.compile(r"^(Current (?:session|week(?:\s*\([^)]+\))?))$")
_USAGE_PERCENT_RE = re.compile(r"([0-9]+)%\s*used")       # yalnız ASCII rakam (`\d` Unicode ondalık rakamı da sayıyordu)
_USAGE_RESETS_RE = re.compile(r"^(Resets\s.+)$")
# `claude -p /usage` (oturumsuz) tek satır biçimi: "Current week (all models): 48% used · resets Nov 16, 6pm (Europe/Istanbul)"
_USAGE_FRESH_RE = re.compile(r"^(Current (?:session|week(?:\s*\([^)]+\))?)):\s*([0-9]+)%\s*used(?:\s*[·•]\s*(?:[Rr]esets?\s+)?(.+))?$")
# `/context`'in çıktısını `parse_context_text()`'in ayrıştırdığı desen — o
# metodun docstring'inde gerçek örnek metin var. `re.search` ile satır
# İÇİNDE aranır (`match` DEĞİL): soldaki blok-glif bar-chart pane genişliğine
# göre farklı yerde sarabilir, sabit bir kolon pozisyonuna güvenilemez.
_CONTEXT_TOTAL_RE = re.compile(r"([0-9.]+[kKmM]?)\s*/\s*([0-9.]+[kKmM]?)\s*tokens\s*\(([0-9]+(?:\.[0-9]+)?)%\)")
_CONTEXT_CATEGORY_RE = re.compile(r"([A-Za-z][A-Za-z ]*?):\s*([0-9.]+[kKmM]?)\s*(?:tokens?)?\s*\(([0-9]+(?:\.[0-9]+)?)%\)")
# Claude Code'un durum çubuğunda gösterdiği metinler (claude-code-guide ajanının
# resmi dokümantasyondan doğruladığı 3 mod, 2026-09-07) — SADECE bunlar Shift+Tab
# döngüsüyle GÜVENİLİR şekilde hedeflenebilir. `bypassPermissions` sadece session
# başlangıcında ayrıca etkinleştirilmişse döngüde belirir (metni doğrulanmadı);
# `dontAsk` döngüde HİÇ yer almaz (resmi doküman: sadece başlatma flag'iyle
# set edilebilir) — ikisi de bilerek dışarıda, ikisi de PERMISSION_MODES'ta var
# (başlatırken verilebiliyorlar, canlıyken değiştirilemiyorlar).
# 2026-09-08'de izole bir scratch session'da CANLI haritalandı (tmux capture,
# Shift+Tab'a arka arkaya basılarak): her durumun kendi metni VAR, "işaretsiz"
# bir mod yok — eskiden varsayılan kabul edilen "default" aslında ekranda
# "manual mode on" olarak görünüyor.
MODE_STATUS_PATTERNS = {
    "plan": r"plan mode on",
    "acceptEdits": r"accept edits on",
    "auto": r"auto mode on",
    "manual": r"manual mode on",
}
# Döngünün BİLEŞİMİ session'a göre DEĞİŞİYOR (aynı canlı haritalamada:
# manual'da başlayan bir session manual→acceptEdits→plan üçlüsünü dönüyor,
# auto'da olan bir session'ın durum çubuğu da "auto mode on (shift+tab to
# cycle)" diyor) — bu yüzden burası "hedeflenebilir modlar" listesi, sabit bir
# döngü SIRASI değil; `_term_set_mode` her basıştan sonra durumu yeniden okur ve
# başlangıç moduna geri dönerse "bu session'ın döngüsünde yok" diye durur.
CYCLABLE_MODES = ["manual", "acceptEdits", "plan", "auto"]
# Session bir turu işlerken (thinking VEYA bir tool çalışırken) durum çubuğuna
# eklenen, idle'da kaybolan metin — mod adının/döngü ipucunun tersine bu KISIM
# hep AYNI (2026-09-09'da canlı doğrulandı: auto VE acceptEdits modlarında,
# hem "thinking" hem bir Bash tool çalışırken aynı "esc to interrupt" ekleniyor,
# idle'a dönünce kayboluyor). `web.py`'nin `_is_busy_cached`'i bunu `strip_ansi`
# uygulanmış tail'de arar (mod tespitiyle AYNI 2026-09-08 ANSI dersi).
BUSY_STATUS_PATTERN = r"esc to interrupt"


# ── canlı model/effort geçişi: ekran tanıma (TBD#399). Kural: EMİN OLUNAMAYAN EKRANDA TUŞ GÖNDERİLMEZ. ──────────────
# Diyalog metinleri 2.1.332 ikilisindeki bileşenden: başlık "Switch model?" / "Change effort level?", seçenekler
# "Yes, switch to <ad>" ve "No, go back" (kutuda taslak varken açılırsa numarasız: tanınmaz, tuş gitmez).
_SWITCH_CAPTURE_LINES = 200        # geçmiş dahil: komuttan ÖNCEKİ sonuç satırları sayılıp yeni sayılmasın
_SWITCH_TITLES = ("Switch model?", "Change effort level?")
_SWITCH_YES_RE = re.compile(r"^(?P<ptr>\u276f\s*)?1\.\s*Yes, switch to (?P<label>\S.*)$")
_SWITCH_NO_RE = re.compile(r"^(?P<ptr>\u276f\s*)?2\.\s*No, go back$")
_SWITCH_GUIDE_RE = re.compile(r"enter to confirm|esc to cancel", re.IGNORECASE)
_SWITCH_GUIDE_MAX = 2              # seçeneklerin altında en çok bu kadar yardım satırı
_SWITCH_TITLE_WINDOW = 15          # başlık seçeneklerin en çok bu kadar dolu satır üstünde
_SCREEN_FRAME = "\u2502\u256d\u256e\u2570\u256f\u2500"       # │╭╮╰╯─
_BOX_FOOTER_MAX = 12               # giriş kutusunun altındaki en çok dolu satır
_FOOTER_MENU_RE = re.compile(r"^(?:\u276f|[>\u203a]?\s*\d\.\s)")
_BUSY_TAIL_LINES = 12


def _screen_rows(text: str) -> List[str]:
    """ANSI'siz ekranın dolu satırları: kenar çizgisi atılmış; yalnız çerçeveden oluşan satır sayılmaz."""
    rows = (line.strip().strip("\u2502").strip() for line in text.split("\n"))
    return [r for r in rows if r.strip(_SCREEN_FRAME + " ")]


def _open_switch_dialog(text: str) -> Optional[Tuple[str, str, bool]]:
    """ANSI'siz ekranın SONUNDA açık duran geçiş diyaloğu: `(başlık, hedef adı, imleç "No"da mı)`, yoksa None. İki
    seçenek ardışık, tam olarak birinde imleç, altlarında yalnız yardım satırı; konuşmada geçen aynı yazı diyalog değil."""
    rows = _screen_rows(text)
    guides = 0
    while rows and guides < _SWITCH_GUIDE_MAX and _SWITCH_GUIDE_RE.search(rows[-1]) \
            and not _FOOTER_MENU_RE.match(rows[-1]):
        rows.pop()
        guides += 1
    if len(rows) < 3:
        return None
    yes, no = _SWITCH_YES_RE.match(rows[-2]), _SWITCH_NO_RE.match(rows[-1])
    if not yes or not no or bool(yes.group("ptr")) == bool(no.group("ptr")):
        return None
    for row in reversed(rows[:-2][-_SWITCH_TITLE_WINDOW:]):
        if row in _SWITCH_TITLES:
            return row, yes.group("label"), bool(no.group("ptr"))
        if row.startswith("\u276f"):
            break
    return None


def _switch_label_matches(label: str, target: str) -> bool:
    """Diyaloğun adı istenen hedef mi ("Sonnet 5.5" ~ `sonnet`, "high" ~ `high`; "xhigh" `high` DEĞİL)."""
    a, b = (re.sub(r"[^a-z0-9]", "", x.lower()) for x in (label, target))
    a, b = (x[len("claude"):] if x.startswith("claude") else x for x in (a, b))
    return bool(a and b) and (a.startswith(b) or b.endswith(a))


def _switch_pane_state(raw: Optional[str]) -> str:
    """`capture-pane -e` ekranı: "ready" (boş giriş kutusu en altta), "busy", "draft", "dialog" ya da "unreadable".
    Soluk/gri öneri yazılı metin sayılmaz (`input_box`)."""
    from ..tmux_backend import input_box, strip_ansi
    if not raw:
        return "unreadable"
    text = strip_ansi(raw)
    if _open_switch_dialog(text):
        return "dialog"
    box = input_box(raw)
    if box is None:
        return "unreadable"
    lines = text.split("\n")
    last_rule = max((i for i, line in enumerate(lines) if "\u2500" * 4 in line), default=None)
    if last_rule is None:
        return "unreadable"
    footer = _screen_rows("\n".join(lines[last_rule + 1:]))
    if len(footer) > _BOX_FOOTER_MAX or any(_FOOTER_MENU_RE.match(r) or _SWITCH_GUIDE_RE.search(r) for r in footer):
        return "unreadable"        # kutu eski bir kare: altında başka bir menü/diyalog var
    if box[1].replace("\u276f", "").replace("\u2502", "").strip():
        return "draft"
    if re.search(BUSY_STATUS_PATTERN, "\n".join(_screen_rows(text)[-_BUSY_TAIL_LINES:])):
        return "busy"
    return "ready"


def _live_switch(tmux_name: str, command: str, title: str, target: str, markers: Tuple[str, ...],
                 timeout: float, poll: float) -> _Switch:
    """`command`i yalnız boş ve boşta bir giriş kutusuna yazar; yalnız BEKLENEN diyalog (başlık + hedef + imleç "Yes"te)
    görülünce BİR kez Enter basar. `DONE`: komuttan SONRA yeni bir sonuç satırı ve hazır giriş kutusu."""
    from ..tmux_backend import tmux_capture, tmux_send_keys, tmux_send_special_key, strip_ansi

    def _count(raw: str) -> int:
        text = strip_ansi(raw)
        return sum(text.count(m) for m in markers)

    def _give_up(result: _Switch, stage: str) -> _Switch:
        diag_log("live_switch_not_done", name=tmux_name, command=command, result=result.value, stage=stage)
        return result

    before = tmux_capture(tmux_name, lines=_SWITCH_CAPTURE_LINES)
    state = _switch_pane_state(before)
    if state != "ready":
        return _give_up(_Switch(state), "precheck")
    seen = _count(before or "")
    if not tmux_send_keys(tmux_name, command):
        return _give_up(_Switch.SEND_FAILED, "command")
    confirmed = False

    def _look() -> Optional[_Switch]:
        nonlocal confirmed
        raw = tmux_capture(tmux_name, lines=_SWITCH_CAPTURE_LINES)
        if raw is None:
            return None
        dialog = _open_switch_dialog(strip_ansi(raw))
        if dialog:
            if not confirmed and dialog[0] == title and not dialog[2] and _switch_label_matches(dialog[1], target):
                confirmed = True
                if not tmux_send_special_key(tmux_name, "Enter"):
                    return _give_up(_Switch.UNCONFIRMED, "confirm_key")
            return None
        if _count(raw) > seen and _switch_pane_state(raw) in ("ready", "busy"):
            return _Switch.DONE
        return None

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(poll)
        result = _look()
        if result:
            return result
    was_confirmed = confirmed
    result = _look()      # son bakış: diyalog tam şimdi açıldıysa onayla ve sonucunu bir kez daha oku
    if result is None and confirmed and not was_confirmed:
        time.sleep(poll)
        result = _look()
    return result or _give_up(_Switch.UNCONFIRMED, "timeout")


def _encode_cwd(cwd: str) -> str:
    """CWD'yi project-dir encoding'e çevir — claude CLI'nın KENDİSİNİN
    `~/.claude/projects/` altında kullandığı adlandırma şemasını taklit eder.

    2026-09-05'te bulundu: eski hâli (sadece `/` ve `_` → `-`) ASCII-only
    cwd'ler için (yanlışlıkla) doğru sonuç veriyordu ama genel kural bu
    DEĞİLMİŞ — gerçek `~/.claude/projects/` dizin adlarıyla çapraz kontrol
    edilince (7 canlı örnek, bkz. commit) kuralın "harf/rakam OLMAYAN HER
    karakter → tek bir `-`" olduğu doğrulandı (Türkçe ğ/ü/ş/ı/ö/ç DAHİL —
    ör. ".../BLM308_veri_madenciliği" → ".../BLM308-veri-madencili-i", "ğ"
    de "-"e dönüşüyor). Eski hâli bu tür cwd'lerde (bu ortamda YAYGIN —
    Türkçe akademik proje klasörleri) YANLIŞ dizin adı üretip jsonl'ı hiç
    bulamıyordu — `find_latest_jsonl`/`resolve_resume_id`/`last_exchange`/
    `full_history`/`extra_file_roots`'un HEPSİ bunu kullandığı için sessizce
    etkileniyordu (resume-tespiti + Sohbet sekmesi + needs_ho + yeni dosya-
    gezgini kökü)."""
    return re.sub(r"[^a-zA-Z0-9]", "-", cwd)


def _safe_mtime(p: Path) -> float:
    """stat().st_mtime — concurrent deletion'a karşı fallback 0.0."""
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def jsonl_path_for(cwd: str, sid: Optional[str]) -> Optional[Path]:
    """`sid` biliniyorsa (--resume ile başladıysa) TAM o dosyanın yolu —
    `_transcript_lines`'ın "aynı cwd'yi paylaşan session'lar mtime tahminiyle
    karışabilir" düzeltmesini (bkz. o docstring) dışarıya da açar. `web.py`'nin
    `_compact()`'i 2026-09-14'e kadar bunun yerine düz `find_latest_jsonl(cwd)`
    kullanıyordu — aynı cwd'de birden fazla session çalışırken (COMPACT HATASI,
    bkz. TODO.md) yanlış session'ın jsonl'ını izleyip 180s timeout'a düşüyordu.
    `sid` YOKSA (fresh --new, henüz atanmamış) mtime fallback'e düşer.

    Sözleşme (TBD#365, birleştirme kapısı): `sid` verildiyse YALNIZ `<sid>.jsonl`; geçersiz sid (`/`, NUL) ya da dosyası
    olmayan sid doğrudan `None` (= transkript yok). Tahmin ortak cwd'de BAŞKA oturumun transkriptini döndürür (needs_ho,
    usage yanlış), bu yüzden yalnız sid gerçekten yokken yapılır. Rust `transcript::jsonl_path_for` hiç tahmin etmez."""
    if sid:
        s = str(sid)
        if "/" in s or "\0" in s:       # tek yol parçası olmalı: `../x` dizinin dışına çıkarır, NUL is_file'ı düşürür
            return None
        candidate = Path(PROJECTS_DIR) / _encode_cwd(cwd) / f"{s}.jsonl"
        try:
            return candidate if candidate.is_file() else None
        except OSError:                 # dosya adı sınırını aşan sid (`ENAMETOOLONG`): transkript yok
            return None
    return find_latest_jsonl(cwd)


def find_latest_jsonl(cwd: str) -> Optional[Path]:
    """CWD için en son değiştirilen jsonl dosyasını döndür (resume sid için)."""
    encoded = _encode_cwd(cwd)
    proj_dir = Path(PROJECTS_DIR) / encoded
    try:
        jsonls = [p for p in proj_dir.iterdir() if p.suffix == ".jsonl" and p.is_file()]
    except OSError:                     # yok, dizin yerinde dosya, okunamıyor: transkript yok
        return None
    return max(jsonls, key=_safe_mtime) if jsonls else None


# TODO.md 2026-09-17: web.py'nin `live_model`i spawn anındaki cmdline'dan
# (`--model X`) okunuyor, terminale doğrudan yazılan bir `/model` hiçbir yerde
# yansımıyordu. jsonl'ın kendi `message.model`'i (her assistant turn'de
# GERÇEK kullanılan modeli taşır) tek non-destructive kaynak — ama bazı
# jsonl'lar 20MB+ olabiliyor (needs_ho.py'nin `for line in f` deseni burada
# uygun değil). Kuyruktan büyüyen bir pencereyle okur: çoğu dosyada ilk
# (en küçük) pencerede bulunur, sadece çok uzun tool-only turn dizilerinde
# genişler.
_LAST_MODEL_CHUNK_BYTES = 65_536
_LAST_MODEL_MAX_BYTES = 4_194_304


def _row_epoch(ts: Any) -> Optional[float]:
    """jsonl satırının ISO-8601 `timestamp`'i ("2026-10-09T05:16:41.123Z") → epoch
    saniye; yoksa/ayrıştırılamazsa None."""
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _last_assistant_value(jsonl_path: Path, extract, since: Optional[float] = None) -> Optional[str]:
    """Dosyanın SONUNDAN geriye okuyarak `extract(obj)`'in doğru (truthy)
    döndürdüğü en son `type:"assistant"` satırının değerini verir, bulamazsa
    None. Asla tüm dosyayı baştan okumaz (kuyruktan büyüyen pencere,
    `_LAST_MODEL_MAX_BYTES`'ta durur).

    `since` (epoch saniye, genelde süreç başlangıcı) verilirse yalnız o andan
    SONRA yazılmış satırlar sayılır ve bundan eski ilk satırda okuma DURUR
    (geriye doğru okunduğu için ondan öncekilerin hepsi daha da eski). Neden:
    yeniden başlatılan (resume) bir sürecin jsonl'ında, ilk turuna kadar "son
    assistant satırı" ÖNCEKİ sürecin satırıdır ve o sürecin modeli/effort'u
    şimdiki sürecinkiyle aynı olmak zorunda değil (resume `--model`'i yeniden
    uyguluyor). Zaman damgası olmayan satır eski sayılmaz (kararsız kalınca
    eskisi gibi davranılır)."""
    try:
        size = os.path.getsize(jsonl_path)
    except OSError:
        return None
    read_size = _LAST_MODEL_CHUNK_BYTES
    try:
        with open(jsonl_path, "rb") as f:
            while True:
                start = max(0, size - read_size)
                f.seek(start)
                chunk = f.read(size - start)
                text = chunk.decode("utf-8", errors="replace")
                for line in reversed(text.split("\n")):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    # Geçerli JSON ama nesne olmayan satır yalnız atlanır (`obj.get` istisnası okumayı düşürmesin).
                    if not isinstance(obj, dict) or obj.get("type") != "assistant":
                        continue
                    if since is not None:
                        ts = _row_epoch(obj.get("timestamp"))
                        if ts is not None and ts < since:
                            return None
                    value = extract(obj)
                    if value:
                        return value
                if start == 0 or read_size >= _LAST_MODEL_MAX_BYTES:
                    return None
                read_size *= 4
    except OSError:
        return None


def last_assistant_model(jsonl_path: Path, since: Optional[float] = None) -> Optional[str]:
    """En son gerçek model taşıyan `type:"assistant"` satırının `message.model`'i, yoksa None.
    `since`: bkz. `_last_assistant_value`."""
    return _last_assistant_value(jsonl_path, _row_model, since)


def _row_model(obj: Dict[str, Any]) -> Optional[str]:
    """Satırın `message.model`'i; alt ajan satırı (`isSidechain`), nesne olmayan `message`, metin olmayan model ya da
    `<synthetic>` yer tutucusu (hata/iptal satırı) None: hiçbiri yeniden açılışa `--model` diye taşınmasın."""
    if obj.get("isSidechain"):
        return None
    msg = obj.get("message")
    model = msg.get("model") if isinstance(msg, dict) else None
    return model if isinstance(model, str) and model != "<synthetic>" else None


def _row_effort(obj: Dict[str, Any]) -> Optional[str]:
    """Satırın üst düzey `effort`u; alt ajan satırı ya da metin olmayan değer None."""
    effort = obj.get("effort")
    return effort if isinstance(effort, str) and not obj.get("isSidechain") else None


def last_assistant_effort(jsonl_path: Path, since: Optional[float] = None) -> Optional[str]:
    """En son `type:"assistant"` satırının TOP-LEVEL `effort`'u (her assistant
    satırı o API çağrısının effort seviyesini taşıyor — 2.1.293'te canlı
    doğrulandı, ör. `"effort":"max"`), yoksa None. Sadece string kabul edilir:
    CLI sayısal/özel effort da tanıyor, onlar "bilinmiyor" sayılıp çağırana
    düşer."""
    return _last_assistant_value(jsonl_path, _row_effort, since)


# TBD#87 (2026-10-16): Claude Code istem önbelleğini 1 saatlik sınıfta yazıyor
# (usage.cache_creation.ephemeral_1h_input_tokens). 338 gerçek devir turunda ölçüldü:
# aynı modelde önceki istek <60 dk önceyse ilk istekte bağlamın %0,2'si, >=60 dk
# önceyse %91'i yeniden yazılmış; yani ömür 3600 sn ve bir UÇURUM.
PROMPT_CACHE_TTL_SECONDS = 3600


def _real_request_epoch(obj: Dict[str, Any]) -> Optional[float]:
    """assistant satırı bir API isteğinin GERÇEK yanıtıysa zaman damgası (epoch),
    değilse None. Önbelleği tazeleyen şey gerçek bir istek: `<synthetic>` yer
    tutucular (hata/iptal), alt-ajan satırları (`isSidechain`: ayrı bir bağlam)
    ve kullanım sayısı olmayan/sıfır satırlar sayılmaz."""
    if obj.get("isSidechain"):
        return None
    msg = obj.get("message")
    if not isinstance(msg, dict) or msg.get("model") in (None, "", "<synthetic>"):
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None
    tokens = 0
    for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        val = usage.get(key)
        if isinstance(val, int) and not isinstance(val, bool):
            tokens += val
    if tokens <= 0:
        return None
    return _row_epoch(obj.get("timestamp"))


def last_real_request_epoch(jsonl_path: Path) -> Optional[float]:
    """Dosyadaki son GERÇEK model isteğinin zamanı (epoch), yoksa None. Sondan
    büyüyen pencereyle okur (`_last_assistant_value`), tüm dosyayı taramaz."""
    return _last_assistant_value(jsonl_path, _real_request_epoch)


def session_file_sid(pid: Optional[int]) -> Optional[str]:
    """`~/.claude/sessions/<pid>.json`ın `sessionId`si. Taze `--new` oturumlar cmdline'da
    `--resume <sid>` taşımıyor, dosyada var. Pid-reuse koruması `discovery`deki gibi:
    dosyadaki `pid` alanı eşleşmeli ve `procStart` /proc/<pid>/stat'ın starttime alanıyla
    (rest[19]) tutmalı. `discovery`den FARKLI olarak doğrulanamayan (okunamayan) kayıt
    kullanılmaz: yanlış oturumun sid'ini sıcaklık kararına sokmaktansa None."""
    record = _session_record(pid)
    return record[0] if record else None


def _session_record(pid: Optional[int]) -> Optional[Tuple[str, Optional[str]]]:
    """`session_file_sid`in doğruladığı kayıt: (sid, kaydın bildirdiği cwd ya da None)."""
    if not pid:
        return None
    try:
        pid = int(pid)
        with open(os.path.join(SESSIONS_DIR, f"{pid}.json"), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or int(data.get("pid") or 0) != pid:
            return None
        sid = data.get("sessionId")
        if not isinstance(sid, str) or not sid.strip():
            return None
        want = str(data.get("procStart", "")).strip()
        if not want:
            return None
        if proc_stat_fields(pid)[19] != want:
            return None
        cwd = data.get("cwd")
        return sid.strip(), cwd if isinstance(cwd, str) and cwd else None
    except (OSError, ValueError, TypeError, IndexError, OverflowError):     # OverflowError: `pid: Infinity`
        return None


# Effort değişimi önbelleği bozan modeller (ölçüm: claude-sonnet-5'te sıcakken 6/6
# yeniden yazma, claude-sonnet-5-5'te 0/30; belge: istek-başı effort yalnız
# Fable 5.1, Mythos 5.1, Opus 5.5, Opus 5, Sonnet 5.5, Haiku 5.5'te var). Sürümsüz
# takma adlar (`sonnet`, `opus`, `fable`) en yeni nesli gösterir, güvenli sayılır.
# `-5` sonrası tek haneli küçük sürüm (`-5-5`, `-5-1`) güvenli; tarihli sabitleme
# (`-5-20260401`) küçük sürüm DEĞİL, ana sürümün kendisi sayılır.
_EFFORT_BUSTS_CACHE_RE = re.compile(r"claude-(?:(?:sonnet|fable|mythos)-5(?!-\d(?!\d))|(?:opus|sonnet|haiku)-4|3)")


def _live_transcript(cwd: str, sid: Optional[str], pid: Optional[int]) -> Optional[Path]:
    """`live_or_spawn_*`ın okuyacağı transkript. `sid` biliniyorsa tam `<sid>.jsonl`. Bilinmiyorsa YALNIZ sürecin kendi
    `sessions/<pid>.json` kaydındaki kimlik (`session_file_sid` doğrulaması); kaydın ya da transkriptin bildirdiği cwd
    hedeften farklıysa kabul edilmez (`resolve_resume_id`'nin kuralı). cwd'deki en yeni dosya HİÇ okunmaz: ortak
    dizinde kardeş oturumunkidir (rs/prov S1, sahip onayı 27 Kas)."""
    if sid:
        return jsonl_path_for(cwd, sid)
    record = _session_record(pid)
    if record is None:
        return None
    own, record_cwd = record
    if record_cwd and not _same_path(record_cwd, cwd):
        return None
    path = jsonl_path_for(cwd, own)
    if path is None:
        return None
    file_cwd = _jsonl_meta(path)["cwd"]
    if file_cwd and not _same_path(file_cwd, cwd):
        return None
    return path


def live_or_spawn_model(cli: str, cwd: str, sid: Optional[str], fallback: str,
                        pid: Optional[int] = None) -> str:
    """TODO.md 2026-09-17/2026-10-06: handover's model-downgrade decision
    (`handover_model_downgrade`) used `session.model` — the spawn-time
    `--model` cmdline argument — which goes stale the moment someone types
    `/model` directly into the terminal (claudeops' own dropdown isn't the
    only way to switch). The downgrade then silently never fires for a
    session that's actually running fable/opus but was spawned as sonnet.
    Prefers the jsonl-verified live model (`last_assistant_model`, same
    source `_live_model()`/the Terminal view's "Bilgi" tab already trust);
    falls back to the spawn-time value whenever live can't be determined
    (non-claude provider, no jsonl yet, no assistant turn written, or neither
    `sid` nor `pid`'s own session record identifies the conversation:
    `_live_transcript`)."""
    if cli != "claude":
        return fallback
    jsonl = _live_transcript(cwd, sid, pid)
    if jsonl is None:
        return fallback
    return last_assistant_model(jsonl) or fallback


def live_or_spawn_effort(cli: str, cwd: str, sid: Optional[str], fallback: str,
                         pid: Optional[int] = None) -> str:
    """`live_or_spawn_model`'in effort karşılığı: cmdline'daki `--effort` spawn
    anında donuyor, terminale yazılan bir `/effort` onu hiç yansıtmıyor — jsonl'ın
    son assistant satırındaki `effort` canlı kaynak. Canlı değer belirlenemezse
    (claude değil, jsonl yok, assistant turu yok, konuşma kimliği çözülemiyor:
    `_live_transcript`) spawn-time değere düşer."""
    if cli != "claude":
        return fallback
    jsonl = _live_transcript(cwd, sid, pid)
    if jsonl is None:
        return fallback
    return last_assistant_effort(jsonl) or fallback


# Bir konuşmanın "kimlik" satırları dosyanın EN BAŞINDA: `customTitle` (session'ın
# `-n NAME` adı) 1. satırda, ilk `cwd` alanı ~6. satırda görülüyor (canlı örneklerde
# doğrulandı, 2026-09-08) — tüm dosyayı okumaya gerek yok.
_META_HEAD_LINES = 15
# Bir proje dizininde taranacak en yeni jsonl sayısı — eski/arşiv konuşmalar için
# sınırsız dosya açmamak adına.
_RESUME_SCAN_LIMIT = 25


def _jsonl_meta(path: Path) -> Dict[str, Optional[str]]:
    """{'title': <customTitle|None>, 'cwd': <ilk cwd alanı|None>} — dosyanın sadece
    ilk birkaç satırını okur, bozuk/okunamayan satırları sessizce atlar (bir arşiv
    dosyasının biçimi beklenmedik diye resume TAMAMEN başarısız olmamalı)."""
    title = cwd = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= _META_HEAD_LINES:
                    break
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(row, dict):
                    continue
                if title is None and isinstance(row.get("customTitle"), str):
                    title = row["customTitle"]
                if cwd is None and isinstance(row.get("cwd"), str):
                    cwd = row["cwd"]
                if title and cwd:
                    break
    except OSError:
        pass
    return {"title": title, "cwd": cwd}


def _same_path(a: str, b: str) -> bool:
    return os.path.normpath(os.path.abspath(a)) == os.path.normpath(os.path.abspath(b))


# `_jsonl_meta`'nın önbelleği: dosya yolu → ((mtime_ns, boyut), meta). `sid_for_stopped_session`
# bir proje dizinindeki TÜM jsonl'ların başlığına bakar (claudeops'ta 70+ dosya) ve panelin sohbet
# görünümü her ~2,5 sn yoklar; imza değişmedikçe dosyayı yeniden açmaya gerek yok. Yazılmakta olan
# dosyanın imzası değişir ve yeniden okunur (15 satır, ucuz).
_META_CACHE: Dict[str, Tuple[Tuple[int, int], Dict[str, Optional[str]]]] = {}
_META_CACHE_MAX = 20_000


def _jsonl_meta_cached(path: Path, mtime_ns: int, size: int) -> Dict[str, Optional[str]]:
    key = str(path)
    hit = _META_CACHE.get(key)
    if hit is not None and hit[0] == (mtime_ns, size):
        return hit[1]
    meta = _jsonl_meta(path)
    if len(_META_CACHE) >= _META_CACHE_MAX:
        _META_CACHE.clear()
    _META_CACHE[key] = ((mtime_ns, size), meta)
    return meta


# Açılıp hiç mesaj almamış bir oturum yalnız başlık/bridge satırlarından ibaret 1-3 KB'lık bir
# "stub" jsonl bırakır; bundan küçük dosyalar gerçekten stub mu diye içeriğine bakılır, büyükler
# doğrudan gerçek sayılır.
_STUB_MAX_BYTES = 64 * 1024


def _has_chat_rows(path: Path) -> bool:
    """Dosyada en az bir user/assistant satırı var mı (başlık/bridge satırlarından ibaret bir stub değil mi)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                try:
                    row = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(row, dict) and row.get("type") in ("user", "assistant"):
                    return True
    except OSError:
        pass
    return False


# Phase 3 (TOBEDECIDED#15) — `--mcp-config`'in beklediği dosya, roster.tsv/
# web.token ile AYNI "repo DIŞI, kaynak-of-truth" dizininde. İÇERİK invariant
# (her zaman `spec`'ten üretilir) olduğu için paylaşımlı/idempotent — birden
# fazla session aynı anda spawn olsa bile hepsi AYNI içeriği yazar.
MCP_CONFIG_PATH = os.path.join(CLAUDEOPS_DIR, "orchestration", "mcp_config.json")


def _mcp_config_path(spec: McpServerSpec) -> str:
    """Paylaşımlı dosya (`MCP_CONFIG_PATH`); `--steward <sid>` taşıyan spec (çoklu değnekçi beyni) kimlik başına KENDİ
    dosyasını alır (`mcp_config_<sid>.json`): içerik kimlik başına invariant kalır, bir kimliğin açılışı başka kimliğin
    beyninin henüz okumadığı yapılandırmayı ezip onu yanlış kimlikle bağlamaz."""
    args = list(spec.args)
    if "--steward" in args and args.index("--steward") + 1 < len(args):
        sid = str(args[args.index("--steward") + 1])
        if sid.isalpha() and sid.islower():
            return MCP_CONFIG_PATH[:-len(".json")] + f"_{sid}.json"
    if len(args) >= 2 and args[0] == "mcp-ext" and str(args[1]).replace("-", "").replace("_", "").isalnum():
        return MCP_CONFIG_PATH[:-len(".json")] + f"_ext_{args[1]}.json"      # eklenti sunucusu kendi dosyasını alır (paylaşılan dosyayı ezmez)
    return MCP_CONFIG_PATH


def _write_mcp_config_file(spec: McpServerSpec) -> str:
    path = _mcp_config_path(spec)
    if preview.active():
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"mcpServers": {spec.name: {"command": spec.command, "args": list(spec.args)}}}
    from claudeops.atomic_json import atomic_write_json     # benzersiz tmp adı: eşzamanlı spawn'lar aynı .tmp'yi ezmesin
    atomic_write_json(path, payload)
    return path


def _extract_text(content) -> str:
    """message.content'ten düz metni çıkar — ya bir string ya da [{'type':'text',...},
    {'type':'tool_use',...}, ...] gibi bloklar listesi (tool_use/tool_result/image
    blokları YOK sayılır, sadece 'Sohbet' sekmesinde okunabilir metin göstermek için)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n\n".join(p for p in parts if isinstance(p, str) and p)
    return ""


def _row_content(row: Dict[str, Any]):
    """Satırın `message.content`i; `message` nesne değilse None."""
    msg = row.get("message")
    return msg.get("content") if isinstance(msg, dict) else None


def _is_real_user_text(content) -> bool:
    """Bir 'user' jsonl satırı gerçekten kullanıcının yazdığı bir mesaj mı, yoksa
    tool_result'un (bir önceki assistant tool_use'una otomatik cevap) 'user' rolüyle
    kodlanmış hali mi? tool_result bloğu varsa insan yazmamıştır, atla."""
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return False


# `claude --help` çıktısı, (yol, mtime_ns, boyut) başına (ucli_client.chat_help_text ile AYNI disiplin): bayrak
# yoklaması her çağrıda alt süreç açmasın, ama güncellenen ikili (mtime/boyut değişir) yoklamayı kendiliğinden
# tazelesin. Çalıştırılamayan/çıktısız ikili ÖNBELLEĞE ALINMAZ ("" döner, bayrak yok sayılır: güvenli taraf).
_HELP_CACHE: Dict[Tuple[str, int, int], str] = {}
_HELP_UNREADABLE: set = set()       # UTF-8 olmayan çıktısı günlüğe girmiş (yol, mtime_ns, boyut): yoklama başına tekrar yazılmaz
_HELP_TIMEOUT_SECONDS = 10.0


def claude_help_text(binary: Optional[str] = None) -> str:
    binary = binary or resolved_binary("claude")
    try:
        st = os.stat(binary)
    except OSError:
        return ""
    key = (binary, st.st_mtime_ns, st.st_size)
    hit = _HELP_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        res = _run_grouped([binary, "--help"], capture_output=True, text=True, timeout=_HELP_TIMEOUT_SECONDS,
                             stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    except UnicodeDecodeError:      # okunamayan yardım = hiçbir bayrak tanınmaz (güvenli yön)
        if key not in _HELP_UNREADABLE and not preview.active():      # kuru kipte günlük yok: işaret de tüketilmez
            _HELP_UNREADABLE.add(key)
            diag_log("help_output_not_utf8", binary=binary)
        return ""
    text = (res.stdout or "") + (res.stderr or "")
    if not text.strip():
        return ""
    _HELP_CACHE[key] = text
    return text


def claude_supports_flag(flag: str, binary: Optional[str] = None) -> bool:
    """`claude --help` `flag`i TAM sözcük olarak listeliyor mu (`--no-session-persistence` için `--no-session`
    'var' sayılmaz)."""
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", claude_help_text(binary)) is not None


class ClaudeProvider(CliProvider):
    name = "claude"

    def resolve_resume_id(self, cwd: str, in_use: FrozenSet[str] = frozenset(),
                          session_name: str = "") -> Optional[str]:
        """Sadece "bu klasörde en son değişen jsonl" DEĞİL (eski hali buydu ve
        2026-09-07'de canlı ısırdı: aynı cwd'yi paylaşan iki session AYNI sid'i
        resume etti). Sırasıyla:

        1. Başka bir canlı session'ın tuttuğu sid'ler ELENİR (`in_use`) —
           tek bir konuşmaya iki process'in yazmasını yapısal olarak engeller.
        2. Kendi `cwd` alanı hedef cwd ile UYUŞMAYAN dosya elenir — proje-dizini
           encoding'i `/` ve `_` karakterlerinin İKİSİNİ de `-` yaptığı için
           `tmp/optical_form/x` ile `tmp/optical-form/x` AYNI dizine düşüyor
           (canlı örnek), yani dizin tek başına "aynı proje" demek değil.
        3. Kalanlar arasında adı bu session'ın adı olan konuşma (jsonl'ın
           `customTitle`'ı = `-n NAME`) TERCİH edilir; yoksa en yenisi. Tercih
           olması önemli: yeniden adlandırılmış bir session eski adlı konuşmasını
           yine de sürdürebilsin."""
        proj_dir = Path(PROJECTS_DIR) / _encode_cwd(cwd)
        try:
            candidates = sorted(
                (p for p in proj_dir.iterdir() if p.suffix == ".jsonl" and p.is_file()),
                key=_safe_mtime, reverse=True,
            )[:_RESUME_SCAN_LIMIT]
        except OSError:                 # yok, dizin yerinde dosya, okunamıyor: devam edilecek konuşma yok
            return None
        fallback = None
        for path in candidates:
            if path.stem in in_use:
                continue
            meta = _jsonl_meta(path)
            if meta["cwd"] and not _same_path(meta["cwd"], cwd):
                continue
            title = meta["title"]
            if title and title != session_name and title in in_use:
                # Bu konuşma ŞU AN çalışan BAŞKA bir session'ın: `--new` ile açılmış
                # bir session'ın sid'i komut satırında görünmez, ama jsonl'ının ilk
                # satırındaki `customTitle` onun `-n NAME` adıdır — sahipliği tespit
                # etmenin tek güvenilir yolu bu (2026-09-07 yuhem vakasında iki
                # session da AYNI konuşmaya yazıyordu).
                continue
            if session_name and title == session_name:
                return path.stem
            if fallback is None:
                fallback = path.stem
        return fallback

    def build_inner_command(self, cwd, model, permission_mode, effort,
                             resume_id, prompt, session_name, extra_args: Sequence[str] = ()) -> str:
        # Mutlak yol (çıplak "claude" DEĞİL): bu string bir tmux pane'inin shell komutu
        # olarak çalışır, o pane'in PATH'i BİZİM PATH'imizden bağımsız — tmux server ilk
        # kez kuruluyorsa onu kuran her neyse (ör. systemd --user servisi, minimal PATH)
        # PATH'i miras kalır ve pane'de "claude: command not found" olur (canlı bulundu,
        # 2026-08-30). shutil.which BURADA (spawn'ı TETİKLEYEN sürecin PATH'inde) çözülüp
        # sonucu string'e gömülünce pane'in kendi PATH'i ne olursa olsun çalışır.
        # resolved_binary(): önce Ayarlar'daki elle-girilmiş override (claude PATH'te
        # değilse — ör. proje-yerel bir node_modules/.bin kurulumu, canlı yuhem vakası
        # 2026-09-07 — ve paylaşımlı bir hesapta ~/.local/bin'e symlink'lemek İSTENMEZ,
        # o hesabı paylaşan herkesin aynı kimlik/credit'i kullanmasına yol açardı),
        # yoksa shutil.which, o da yoksa bare isim.
        binary = resolved_binary("claude")
        resume_arg = f"--resume {shlex.quote(resume_id)} " if resume_id else ""
        # `extra_args` (Phase 3, ör. `--mcp-config <path>`) `--model`'den HEMEN
        # ÖNCE eklenir, PROMPT'tan hemen önce DEĞİL: canlı doğrulandı (2026-09-10,
        # mcpv3claude test session'ı) — `--mcp-config` VARIADIC bir bayrak (claude
        # --help: birden fazla değeri boşlukla ayırıp AÇGÖZLÜ okuyor). Prompt'tan
        # hemen önce bırakılınca prompt METNİNİ kendi değeri sanıp yuttu
        # (`ENAMETOOLONG`, session ANINDA çöktü). Hemen ardından BAŞKA bir
        # `--flag` (`--model`) gelmesi variadic okumayı güvenle bitiriyor — bunu
        # sağlayan TEK şart extra_args'ın kendi değerlerinin `-` ile
        # BAŞLAMAMASI (bizim tek kullanımımız — mutlak dosya yolu/`key=value` —
        # zaten öyle).
        extra_prefix = "".join(f"{shlex.quote(a)} " for a in extra_args)
        prompt_arg = f" {shlex.quote(prompt)}" if prompt else ""
        # İşe göre model/effort yönergesi (TBD#91): sistem isteminin SONUNA eklenir, proje CLAUDE.md'lerine
        # dokunmaz; Ayarlar'dan kapatılabilir. `--model`den ÖNCE, `extra_args` gibi: değeri mutlak dosya yolu.
        guidance = claude_guidance_path()
        guidance_arg = f"--append-system-prompt-file {shlex.quote(guidance)} " if guidance else ""
        return (
            f"{shlex.quote(binary)} {resume_arg}{extra_prefix}{guidance_arg}"
            f"--model {shlex.quote(model)} "
            f"--permission-mode {shlex.quote(permission_mode)} "
            f"--effort {shlex.quote(effort)} "
            f"-n {shlex.quote(session_name)} "
            f"--remote-control {shlex.quote(session_name)}"
            f"{prompt_arg}"
        )

    def oneshot_argv(self, prompt: str, model: Optional[str]) -> Optional[List[str]]:
        # `-p` (print): tek yanıt, metin. `--tools ""` = hiçbir araç yok (dosya okutma yok; içerik prompt'ta).
        # Prompt `-p`den HEMEN SONRA, bayraklardan ÖNCE: `--tools` variadic (bkz. build_inner_command'daki
        # `--mcp-config` notu), arkasına konan prompt'u kendi değeri sanıp yutardı.
        binary = resolved_binary("claude")
        argv = [binary, "-p", prompt]
        if model:
            argv += ["--model", model]
        argv += ["--output-format", "text"]
        # Transkript bırakma (`~/.claude/projects/<nötr cwd>/` altında her kart çağrısı bir jsonl açardı): YALNIZ
        # ikilinin `--help`'i bayrağı tanıyorsa (federasyondaki eski claude sürümü tanımayabilir; tanımayan ikili
        # "unknown option" ile çıkar ve kart hiç üretilmezdi). `--tools ""` variadic olduğundan en sonda kalır.
        if claude_supports_flag("--no-session-persistence", binary):
            argv.append("--no-session-persistence")
        return argv + ["--tools", ""]

    def mcp_launch_args(self, spec: McpServerSpec) -> List[str]:
        # Claude Code'un `--mcp-config` bayrağı bir JSON DOSYA yolu bekliyor
        # (inline JSON'u tmux'un shell komut satırına gömmek `shlex.quote`'un
        # tek-token varsayımını zorlardı) — içerik `spec`'ten deterministik
        # üretildiği için dosya idempotent/paylaşımlı.
        config_path = _write_mcp_config_file(spec)
        return ["--mcp-config", config_path]

    def compact_command(self) -> Optional[str]:
        return "/compact"

    def usage_command(self) -> Optional[str]:
        return "/usage"

    def usage_needs_dismiss(self) -> bool:
        # `/usage` opens a MODAL settings/usage screen (canlı doğrulandı,
        # 2026-09-13, izole scratch session) — Escape olmadan session o
        # ekranda takılı kalır, sonraki poll'ların mode/busy regex'leri
        # normal prompt'u hiç görmez. Escape sonrası "⎿ Settings dialog
        # dismissed" ile normal `❯ ` prompt'a dönüyor, canlı doğrulandı.
        return True

    def parse_usage_text(self, text: str) -> Optional[List[Dict[str, str]]]:
        """`/usage`'ın gerçek çıktısı (canlı doğrulandı, 2026-09-13):
        ```
        Current session
        █  2% used
        Resets 12am (Europe/Istanbul)

        Current week (all models)
        ██████  92% used
        Resets Sep 14, 6pm (Europe/Istanbul)
        +50% weekly limits promo through Sep 13 · clau.de/cc-50-promo

        Current week (Fable)
        █████  75% used
        Resets Sep 14, 6pm (Europe/Istanbul)
        ```
        Hesaba göre "Current week (...)" satırı BİRDEN FAZLA kez tekrarlanabilir
        (her biri farklı bir model-grubu için, ör. "all models" + "Fable") — bu
        yüzden TEK bir sabit satır sayısı varsaymak yerine her "Current ..."
        başlığından SONRAKİ ilk "NN% used" + ilk "Resets ..." satırı eşleştirilir
        (aradaki promo/blank satırlar atlanır, en fazla 3 satır ileri bakılır)."""
        lines = [ln.strip() for ln in text.splitlines()]
        entries: List[Dict[str, str]] = []
        for i, line in enumerate(lines):
            if not _USAGE_HEADER_RE.match(line):
                continue
            percent: Optional[str] = None
            resets = ""
            for j in range(i + 1, min(i + 4, len(lines))):
                if percent is None:
                    pm = _USAGE_PERCENT_RE.search(lines[j])
                    if pm:
                        percent = pm.group(1)
                        continue
                rm = _USAGE_RESETS_RE.match(lines[j])
                if rm:
                    resets = rm.group(1)
                    break
            if percent is not None:
                entries.append({"label": line, "percent": percent, "detail": resets})
        return entries or None

    def usage_fresh_argv(self) -> Optional[List[str]]:
        return [resolved_binary("claude"), "-p", "/usage"]

    def parse_fresh_usage(self, text: str) -> Optional[List[Dict[str, str]]]:
        entries: List[Dict[str, str]] = []
        for ln in text.splitlines():
            m = _USAGE_FRESH_RE.match(ln.strip())
            if m:
                rs = (m.group(3) or "").strip()
                if rs in ("resets", "Resets", "reset", "Reset"):     # `· resets` sonrası metin yok: `Resets resets` olmasın
                    rs = ""
                entries.append({"label": m.group(1), "percent": m.group(2), "detail": ("Resets " + rs) if rs else ""})
        return entries or self.parse_usage_text(text)

    def context_command(self) -> Optional[str]:
        return "/context"

    def context_needs_dismiss(self) -> bool:
        # `/context` normal scrollback'e yazıp doğrudan `❯` prompt'a dönüyor,
        # `/usage`'ın aksine modal AÇMIYOR (canlı doğrulandı, 2026-09-22,
        # throwaway scratch session, v2.1.278) — Escape gerekmiyor.
        return False

    def parse_context_text(self, text: str) -> Optional[List[Dict[str, str]]]:
        """`/context`'in gerçek çıktısı (canlı doğrulandı, 2026-09-22, throwaway
        scratch session, `claude` v2.1.278) — sol taraf blok-glif bar-chart,
        sağ taraf asıl metin:
        ```
          ⎿  Context Usage
             ⛁ ⛁ ⛁ ⛁ ⛁ ⛀ ⛁ ⛁ ⛁ ⛁ ⛀ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶   Fable 5.1
             ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶   claude-fable-5-1
             ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶   42.9k/1m tokens (4%)
             ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶
             ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶   Estimated usage by category
             ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶   ⛁ System prompt: 4.3k tokens (0.4%)
             ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶   ⛁ System tools: 19.2k tokens (1.9%)
                                                        ⛁ MCP tools: 645 tokens (0.1%)
                                                        ⛁ Memory files: 14.4k tokens (1.4%)
                                                        ⛁ Skills: 4.3k tokens (0.4%)
                                                        ⛁ Messages: 10 tokens (0.0%)
                                                        ⛶ Free space: 924.1k (92.4%)
                                                        ⛝ Autocompact buffer: 33k tokens (3.3%)
        ```
        Ardından `MCP tools · /mcp (loaded on-demand)` başlığıyla loaded/
        available tool'ların uzun bir dökümü gelir (bazı fleet session'larında
        100+ satır) — hiçbiri `_CONTEXT_CATEGORY_RE`'nin zorunlu kıldığı
        `(NN%)` kuyruğunu taşımadığı için (o dökümdeki satırlar en fazla
        "isim: N tokens" — yüzdesiz) kendiliğinden elenir, ayrıca kesme/limit
        gerekmez. "Free space" satırında "tokens" kelimesi YOK (`924.1k
        (92.4%)`), o yüzden regex'te opsiyonel. İlk eşleşen "X/Y tokens (Z%)"
        toplam satırı sabit "Context" etiketiyle İLK eleman olur, model
        adı/ID'si (bar-chart'ın üstünde ayrı satırlarda) BİLEREK parse
        EDİLMİYOR — `live_model` zaten panelde var, tekrar etmeye gerek yok.

        `tmux_capture()`'ın varsayılan 2000 satırlık penceresi (uzun MCP-tool
        dökümü tek bir `/context` çıktısını 200+ satıra taşıyabildiği için
        BİLEREK geniş — bkz. `_context()`'in çağırdığı yer) aynı pane'de
        DAHA ÖNCEKİ bir `/context` çalıştırmasının çıktısını da yakalayabilir
        (canlı bulundu, 2026-09-22: aynı throwaway session'da iki kez
        `/context` çalıştırılınca kategoriler İKİŞER kez, eskisi BAYAT
        yüzdelerle döndü). Fix: toplam-satır eşleşmesi `entries`'i DURDURMAK
        yerine SIFIRLAR — metin boyunca en son görülen "X/Y tokens (Z%)"
        satırından SONRAKİ kategoriler kazanır, ondan ÖNCEKİ (eski) blok
        tamamen atılır."""
        lines = [ln.strip() for ln in text.splitlines()]
        entries: List[Dict[str, str]] = []
        for line in lines:
            tm = _CONTEXT_TOTAL_RE.search(line)
            if tm:
                used, limit, percent = tm.groups()
                entries = [{"label": "Context", "percent": percent, "detail": f"{used}/{limit} tokens"}]
                continue
            cm = _CONTEXT_CATEGORY_RE.search(line)
            if cm and cm.start(1) > 0 and line[cm.start(1) - 1].isalpha():
                continue        # ad bir harfin ortasından başlıyor (`Şey` -> `ey`): kırpılmış ad yazılmaz, satır atlanır
            if cm:
                label, amount, percent = cm.groups()
                label = label.strip()
                if label:
                    entries.append({"label": label, "percent": percent, "detail": f"{amount} tokens"})
        return entries or None

    def handover_model_downgrade(self, current_model: str) -> Optional[str]:
        """2026-09-04, kullanıcı: "handover komutu öncesi model sonnet'e ve
        sonrası eski modele. seçili model daha düşükse kalsın." Canlı doğrulanan
        `/model` seçici metni (v2.1.260): Fable ("most capable for your hardest
        and longest-running tasks") ve Opus ("best for everyday, complex tasks")
        İKİSİ de Sonnet'ten ("efficient for routine tasks") YUKARIDA; Haiku
        ("fastest for quick answers") aşağıda. Tanınmayan/boş bir model adı
        GÜVENLİ VARSAYILANLA (dokunma → None) ele alınır — yanlış yönde bir
        swap (ör. gerçekte Sonnet'ten ucuz bir modeli yanlışlıkla Sonnet'e
        YÜKSELTMEK) maliyeti YANLIŞLIKLA artırır, bu asla olmamalı."""
        if not current_model:
            return None
        lowered = current_model.lower()
        if "opus" in lowered or "fable" in lowered:
            return "sonnet"
        return None

    _MODEL_SWITCH_TIMEOUT_SECONDS = 20.0
    _MODEL_SWITCH_POLL_SECONDS = 0.3

    def apply_live_model_switch(self, tmux_name: str, target_model: str) -> _Switch:
        """`/model <target_model>` CANLI session'a gönderilir; bazen (önceden kestirilemez) bir "Switch model?" onay
        diyaloğu açılır (konuşma önbelleği kaybolacağı için). Sabit bekleme + kör Enter canlı testte mesaj kaybettirdi:
        diyalog pencerenin dışında açılınca sonraki mesaj diyaloğa yazıldı. Bu yüzden ekran yoklanır (`_live_switch`;
        yakalama ANSI'li olduğundan eşleştirmeden önce temizlenir: claude başlığı kelime kelime renklendirir).

        TBD#399 (27 Kas): kutuda taslak, açık diyalog, süren tur ya da okunamayan ekranda komut HİÇ gönderilmez;
        yalnız komuttan sonra beliren sonuç satırı "bitti" sayılır; 20 sn'de doğrulanamayan geçiş `UNCONFIRMED`
        döner ve çağıran pane'e başka metin yazmaz."""
        return _live_switch(tmux_name, f"/model {target_model}", "Switch model?", target_model,
                            ("Set model to", "Kept model as"),
                            self._MODEL_SWITCH_TIMEOUT_SECONDS, self._MODEL_SWITCH_POLL_SECONDS)

    def handover_effort_downgrade(self, current_effort: str, target_effort: str) -> Optional[str]:
        """Handover wrap-up turu için `current_effort`, `target_effort`'un
        (Ayarlar'daki `handover_effort`, varsayılan 'high') ÜSTÜNDEYSE
        `target_effort`; eşit/düşükse ya da tanınmıyorsa None (kullanıcı,
        2026-10-07: "high değilse eğer daha düşükse karışma" — yanlış yönde
        bir swap effort'u YÜKSELTİP maliyeti artırırdı, bu asla olmamalı)."""
        levels = self.effort_levels()
        if current_effort not in levels or target_effort not in levels:
            return None
        if levels.index(current_effort) <= levels.index(target_effort):
            return None
        return target_effort

    def prompt_cache_ttl_seconds(self) -> Optional[int]:
        return PROMPT_CACHE_TTL_SECONDS

    def last_request_epoch(self, cwd: str, sid: Optional[str], pid: Optional[int] = None) -> Optional[float]:
        """YALNIZ tam eşleşen `<sid>.jsonl` dosyaları okunur. `jsonl_path_for`un "sid
        yoksa cwd'deki en yeni dosya" yedeği burada YOK: aynı cwd'yi paylaşan kardeş bir
        oturumun yakın zamanlı isteği bu oturumu yanlışlıkla 'sıcak' gösterirdi, ve
        sıcak sanıp pahalı modelde kalmanın bedeli soğuk bir önbellekte en pahalı
        yön (TBD#87). Adaylar: cmdline sid'i (`--resume`) ve sürecin kendi
        `sessions/<pid>.json` sid'i (taze `--new` oturumların sid'i cmdline'da YOK ve
        keşif katmanı bunları doldurmuyor: canlı filoda 37'nin 9'u, hepsi etkin olanlar).
        İkisi de varsa en yeni istek kazanır (konuşma `/clear` ile yeni bir dosyaya
        geçmiş olabilir). Eşleşme yoksa None: çağıran eski davranışa düşer."""
        epochs = []
        for cand in dict.fromkeys(s for s in (sid, session_file_sid(pid)) if s):
            if not _path_part_ok(cand):     # `/` ya da NUL: mutlak/`../` aday proje dizininin dışını açmaz
                continue
            path = Path(PROJECTS_DIR) / _encode_cwd(cwd) / f"{cand}.jsonl"
            try:
                is_file = path.is_file()
            except OSError:             # dosya adı sınırını aşan aday
                continue
            if is_file:
                epoch = last_real_request_epoch(path)
                if epoch is not None:
                    epochs.append(epoch)
        return max(epochs) if epochs else None

    def effort_switch_keeps_cache(self, model: str) -> bool:
        return not _EFFORT_BUSTS_CACHE_RE.match((model or "").lower())

    _EFFORT_SWITCH_TIMEOUT_SECONDS = 8.0
    _EFFORT_SWITCH_POLL_SECONDS = 0.3
    _EFFORT_SWITCH_DONE_MARKERS = ("Set effort level to", "Not applied:", "exceeds the cap",
                                   "Failed to set effort level")

    def apply_live_effort_switch(self, tmux_name: str, target_effort: str) -> _Switch:
        """`/effort <target_effort>` CANLI session'a gönderilir. `/effort` de `/model` gibi onay diyaloğu açabilir
        ("Change effort level?", 2026-10-08: `claude` ikilisinin string tablosu; kullanıcı canlıda soru gördü).
        Akış ve güvenlik kuralları `/model` ile aynı (`_live_switch`, TBD#399). Bu switch bilerek istendiği için
        diyalog onaylanır; reddetmek `dismiss_stray_dialog()`ın işi.

        ⚠ Hangi effort geçişinin diyaloğu açtığı canlı doğrulanmadı."""
        return _live_switch(tmux_name, f"/effort {target_effort}", "Change effort level?", target_effort,
                            self._EFFORT_SWITCH_DONE_MARKERS,
                            self._EFFORT_SWITCH_TIMEOUT_SECONDS, self._EFFORT_SWITCH_POLL_SECONDS)

    _STRAY_DIALOG_TIMEOUT_SECONDS = 6.0
    _STRAY_DIALOG_POLL_SECONDS = 0.5

    def dismiss_stray_dialog(self, tmux_name: str) -> Optional[_Switch]:
        """`base.py`nin docstring'ine bkz. Açık duran geçiş diyaloğunu ("Switch model?" ya da geç açılan "Change effort
        level?") REDDEDER: imleç `Down` ile "No, go back"e indirilir, ekran YENİDEN okunur ve imleç orada ise Enter
        basılır; sonra diyaloğun kapandığı doğrulanır. Herhangi bir adım doğrulanamazsa başka tuş yok.

        Dönen: None (diyalog görülmedi), `DONE` (kapandı), `UNCONFIRMED` (açık kalmış olabilir; günlüğe yazılır).
        6 sn'lik kısa bekleme bilerek: toplu devirde her oturuma eklenir.

        ⚠ Gerçek claude diyaloğuyla uçtan uca doğrulanmadı."""
        from ..tmux_backend import tmux_capture, tmux_send_special_key, strip_ansi

        def _read() -> Tuple[bool, Optional[Tuple[str, str, bool]]]:
            raw = tmux_capture(tmux_name, lines=20)
            return raw is not None, _open_switch_dialog(strip_ansi(raw or ""))

        def _stuck(stage: str) -> _Switch:
            diag_log("stray_dialog_left_open", name=tmux_name, stage=stage)
            return _Switch.UNCONFIRMED

        deadline = time.monotonic() + self._STRAY_DIALOG_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            _, dialog = _read()
            if dialog:
                if not dialog[2]:
                    if not tmux_send_special_key(tmux_name, "Down"):
                        return _stuck("down_key")
                    time.sleep(0.2)
                    _, moved = _read()
                    if not moved or moved[0] != dialog[0] or not moved[2]:
                        return _stuck("cursor")
                if not tmux_send_special_key(tmux_name, "Enter"):
                    return _stuck("enter_key")
                time.sleep(self._STRAY_DIALOG_POLL_SECONDS)
                readable, left = _read()
                return _Switch.DONE if readable and not left else _stuck("still_open")
            time.sleep(self._STRAY_DIALOG_POLL_SECONDS)
        return None

    def matches_proc(self, cmd: List[str]) -> bool:
        """Bash `^claude` anchor'ının karşılığı: argv[0]'ın basename'i 'claude'.
        'bash -c "claude ..."' wrapper'ında argv[0]='bash' → eler."""
        return bool(cmd) and os.path.basename(cmd[0]) == "claude"

    def extract_name(self, proc, cmd: List[str]) -> Optional[str]:
        return _arg(cmd, "--remote-control")

    def extract_info(self, cmd: List[str], cwd: str = "", session_name: str = "") -> Dict[str, Optional[str]]:
        return {
            "sid": _arg(cmd, "--resume"),
            "model": _arg(cmd, "--model"),
            "permission_mode": _arg(cmd, "--permission-mode"),
            "effort": _arg(cmd, "--effort"),
        }

    def preferred_default_model(self) -> Optional[str]:
        """Yeni oturum varsayılanı: en yeni Sonnet (TBD#91, 2026-10-19). Eskiden `model_choices()[0]` = alfabetik
        ilk = `claude-fable-5-1` idi; işe göre yükseltme yönergesi (`routing.py`) düşük başlamayı varsayar."""
        sonnets = [c for c in self.model_choices() if _SONNET_PIN_RE.match(c)]
        return max(sonnets, key=_sonnet_version) if sonnets else None

    def default_effort(self) -> str:
        return "medium" if "medium" in self.effort_levels() else super().default_effort()

    def model_choices(self) -> List[str]:
        """`model_freshness.py`'nin günlük taze listesini okur (`enabled`
        olanlar) — dosya yoksa/boşsa/bozuksa sessizce hardcoded
        `MODEL_CHOICES`'a düşer (agy/ucli'nin live-fetch-with-fallback
        deseniyle AYNI, sadece "canlı" kaynak bir subprocess-cache dosyası)."""
        try:
            from .. import statedocs
            state = statedocs.read_json("claude_models", CLAUDE_MODELS_JSON, {})
            enabled = sorted(m for m, s in state.get("models", {}).items() if s == "enabled")
            if enabled:
                return enabled
        except Exception:
            pass
        return MODEL_CHOICES

    def refresh_stored_model(self, stored: str) -> str:
        """Sabitlenmiş (pinned) bir sonnet id'sini `model_choices()`'taki EN
        YENİ sonnet'e taşır (TODO.md 2026-10-08: "restartlar da sonet 5.5
        gelmiyor"; `models.tsv`'nin yazıcısı yok, `claude-sonnet-5` sonsuza dek
        donuk kalıyordu). Faz-1'in canlı `/model sonnet` takma adıyla AYNI
        felsefe, ama restart'ta literal id gerektiği için çözümü burada yapıyoruz.
        Dokunulmaz: opus/fable/haiku pinleri, `sonnet` gibi takma adlar (zaten
        hep taze), tanınmayan biçimler; `[1m]` eki korunur; stored zaten
        güncel ya da daha yeniyse (elle yeni bir pin) geri DÜŞÜRÜLMEZ."""
        m = _SONNET_PIN_RE.match(stored or "")
        if not m:
            return stored
        fresh = max((c for c in self.model_choices() if _SONNET_PIN_RE.match(c)),
                    key=_sonnet_version, default=None)
        if not fresh or _sonnet_version(fresh) <= _sonnet_version(stored):
            return stored
        fm = _SONNET_PIN_RE.match(fresh)
        return fm.group(1) + fm.group(2) + (m.group(3) or "")

    def permission_modes(self) -> List[str]:
        return PERMISSION_MODES

    def effort_levels(self) -> List[str]:
        return EFFORT_LEVELS

    def mode_status_patterns(self) -> Dict[str, str]:
        return MODE_STATUS_PATTERNS

    def background_work(self, pane_text: str, cwd: str, sid: Optional[str]) -> Optional[int]:
        """Alt durum satırı sayıları ('N shell(s)', 'N background task(s)', 'N agent(s)', ajan satırı 'waiting on'); ekran boşsa
        transkriptte bildirimi gelmemiş `run_in_background` işi (>=1). Bkz. `bg_work`."""
        from .. import bg_work
        n = bg_work.screen_bg_count(pane_text or "")
        if n:
            return n
        path = jsonl_path_for(cwd, sid)
        return 1 if bg_work.transcript_pending_path(path) else 0

    def busy_status_pattern(self) -> Optional[str]:
        return BUSY_STATUS_PATTERN

    def cyclable_modes(self) -> List[str]:
        return CYCLABLE_MODES

    def _transcript_lines(self, cwd: str, sid: Optional[str]) -> List[dict]:
        """`last_exchange`/`full_history`'nin PAYLAŞTIĞI adım: doğru jsonl'ı bul + parse
        edilmiş satırları döndür (bulunamazsa/okunamazsa boş liste — 'desteklenmiyor'
        ile 'henüz mesaj yok' ayrımı ÇAĞIRAN tarafın işi, burada değil).

        sid biliniyorsa (--resume ile başladıysa) TAM o dosya — aynı cwd'de birden fazla
        session paylaşıyorsa find_latest_jsonl (mtime) yanlış dosyayı seçebilir. sid yoksa
        (--new fresh start, Faz 2'nin varsayılanı) mtime fallback şart."""
        path = jsonl_path_for(cwd, sid)
        if path is None:
            return []
        try:
            lines = []
            # Bozuk bayt (ör. yazım sürerken yarım kalan çok baytlı karakter) yalnız KENDİ satırını okunamaz kılar.
            with path.open(encoding="utf-8", errors="surrogateescape") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        raw.encode("utf-8")
                    except UnicodeEncodeError:
                        lines.append({})        # okunamayan satır: içeriği yok, yeri belli (bkz. `last_message_role`)
                        continue
                    try:
                        row = json.loads(raw)
                    except (ValueError, RecursionError):     # bozuk, aşırı derin ya da dev sayılı satır
                        continue
                    lines.append(row if isinstance(row, dict) else {})
            return lines
        except OSError:
            return []

    def last_message_role(self, cwd: str, sid: Optional[str]) -> Optional[str]:
        # Son satır okunamıyorsa rol BİLİNMİYOR: takılma tespiti öncekine bakıp oturumu öldürüp yeniden açmasın.
        rows = self._transcript_lines(cwd, sid)
        if rows and rows[-1] == {}:
            return None
        return super().last_message_role(cwd, sid)

    def last_exchange(self, cwd: str, sid: Optional[str]) -> Optional[Dict[str, str]]:
        # NOT: aşağıdaki "bulamadım" dallarının hepsi None DEĞİL boş dict döner —
        # None SADECE base.py'nin varsayılanında ("bu provider desteklemiyor") kalsın;
        # burada (claude provider'da) her zaman {"user":"","assistant":""} dönmek,
        # panelin "desteklenmiyor" ile "henüz mesaj yok" mesajlarını KARIŞTIRMAMASINI
        # sağlar (canlı bulundu: taze/boş bir session "bu CLI için sohbet görünümü
        # henüz yok" diye yanlış mesaj gösteriyordu — claude'un kendisi destekliyor,
        # sadece bu session'da henüz içerik yok).
        empty = {"user": "", "assistant": ""}
        lines = self._transcript_lines(cwd, sid)
        ai = None
        for i in range(len(lines) - 1, -1, -1):
            d = lines[i]
            if d.get("type") == "assistant" and not d.get("isSidechain"):
                ai = i
                break
        if ai is None:
            return empty
        assistant_text = _extract_text(_row_content(lines[ai]))
        user_text = ""
        for i in range(ai - 1, -1, -1):
            d = lines[i]
            # Sıkıştırma özeti kullanıcının mesajı değildir (`full_history`de `summary`).
            if d.get("type") != "user" or d.get("isSidechain") or d.get("isMeta") or d.get("isCompactSummary"):
                continue
            content = _row_content(d)
            if _is_real_user_text(content):
                user_text = _extract_text(content)
                break
        return {"user": user_text, "assistant": assistant_text}

    def extra_file_roots(self, cwd: str) -> List[Tuple[str, str]]:
        # find_latest_jsonl'ın AYNI encoding'i — dosya-gezginine bu proje için
        # claude'un kendi transcript/meta klasörünü (jsonl'lar dahil) ekler.
        return [("claude-transcripts", os.path.join(PROJECTS_DIR, _encode_cwd(cwd)))]

    def full_history(self, cwd: str, sid: Optional[str]) -> Optional[List[Dict[str, str]]]:
        # `last_exchange`'in tek-son-çift filtreleriyle AYNI kurallar (sidechain/isMeta/
        # tool_result-only hariç, boş metin hariç) — sadece SADECE SONUNCUYU almak yerine
        # sırayla HEPSİNİ biriktiriyor.
        out: List[Dict[str, str]] = []
        for d in self._transcript_lines(cwd, sid):
            t = d.get("type")
            if t == "system" and d.get("subtype") == "compact_boundary":
                # Compaction öncesi mesajlar dosyada durur (arşiv yok, TBD#89): sınır yalnız
                # bir işaret; "text" = "tetikleyen, öncesi token" (arayüz etiketi kendi diliyle).
                meta = d.get("compactMetadata")
                if not isinstance(meta, dict):
                    meta = {}
                out.append({"role": "boundary",
                            "text": f"{meta.get('trigger', '')}, {meta.get('preTokens', '')}"})
            elif t == "user" and d.get("isCompactSummary") and not d.get("isSidechain"):
                text = _extract_text(_row_content(d))
                if text:
                    out.append({"role": "summary", "text": text})
            elif t == "assistant" and not d.get("isSidechain"):
                text = _extract_text(_row_content(d))
                if text:
                    out.append({"role": "assistant", "text": text})
            elif t == "user" and not d.get("isSidechain") and not d.get("isMeta"):
                content = _row_content(d)
                if _is_real_user_text(content):
                    text = _extract_text(content)
                    if text:
                        out.append({"role": "user", "text": text})
        return out

    def sid_for_stopped_session(self, cwd: str, session_name: str) -> Optional[str]:
        """Durmuş session'ın konuşması = jsonl'ın başındaki `customTitle`'ı bu session'ın adı
        (`-n NAME`) olan dosya. `resolve_resume_id`'nin "adı bu session'ın adı olan konuşma"
        tercihiyle AYNI eşleme (aynı cwd uyuşma kuralı dahil), ama (1) TÜM dosyalara bakar:
        resume en yeni 25'e bakıyor, claudeops cwd'sinde 3 haftalık bir instance'ın dosyası
        bunun dışında kalır; (2) eşleşme yoksa "en yenisi"ne DÜŞMEZ, None döner (düşmek
        çağıranın işi). Canlı veride (2026-10-14, 547 claude instance'ı) proje dizini duran
        her `new_chat` kaydı eşleşiyor; eşleşmeyenler eski `migrated` kayıtları.

        Aynı başlığı taşıyan birden çok dosya olabiliyor (handover/yeniden açılış AYNI adla
        YENİ konuşma başlatır; bir de hiç mesaj almamış başlık-yalnız stub'lar var, hcr20260908_1
        örneğinde stub gerçek konuşmadan daha yeni): en yeni GERÇEK konuşma seçilir, hepsi stub
        ise en yenisi."""
        if not session_name:
            return None
        matches: List[Tuple[int, int, Path]] = []
        try:
            with os.scandir(Path(PROJECTS_DIR) / _encode_cwd(cwd)) as entries:
                for entry in entries:
                    if not entry.name.endswith(".jsonl"):
                        continue
                    try:
                        if not entry.is_file():
                            continue
                        st = entry.stat()
                    except OSError:  # tarama sırasında silindi
                        continue
                    path = Path(entry.path)
                    meta = _jsonl_meta_cached(path, st.st_mtime_ns, st.st_size)
                    if meta["title"] != session_name:
                        continue
                    if meta["cwd"] and not _same_path(meta["cwd"], cwd):
                        continue
                    matches.append((st.st_mtime_ns, st.st_size, path))
        except OSError:
            return None
        matches.sort(key=lambda m: m[0], reverse=True)
        for _, size, path in matches:
            if size >= _STUB_MAX_BYTES or _has_chat_rows(path):
                return path.stem
        return matches[0][2].stem if matches else None
