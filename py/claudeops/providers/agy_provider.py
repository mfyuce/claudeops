"""agy (Google Antigravity CLI) provider.

Farklar (claude'a göre):
- `--remote-control NAME` muadili YOK → isimlendirme `COPS_NAME` env değişkeniyle
  (spawn'da set edilir, discovery'de `psutil.Process.environ()` ile okunur).
- Resume kaynağı `~/.gemini/antigravity-cli/cache/last_conversations.json`
  (cwd → conversation-id sözlüğü), claude'un jsonl-tabanlı `find_latest_jsonl`'ının
  muadili.
- Model listesi CANLI çekilir (`agy models`, TTL'li cache) — sabit kodlanmaz,
  liste zaten 2 günde bir kez değişti.
- effort için ayrı bir `--effort low|medium|high` flag'i var (model id'sinden
  bağımsız) — permission ise TEK bir `--permission-mode`-benzeri flag değil,
  ya `--dangerously-skip-permissions` ya da `--mode accept-edits|plan`.
- COPS_NAME yoksa (elle başlatılmış bare `agy`) isim `agy-<pid>` placeholder'ı
  olur — claude'daki bare-session/"kayıtsız" davranışıyla paralel; ASLA None
  dönmez (agy'nin claude'un sessions/*.json'ı gibi kendi self-registration'ı yok).
- `last_exchange`/`full_history` (2026-09-05): gerçek konuşma verisi
  `~/.gemini/antigravity-cli/conversations/<conversation-id>.db` (SQLite,
  `resolve_resume_id`'nin okuduğu AYNI id) içindeki `steps` tablosunun
  `step_payload` BLOB kolonunda — protobuf, ŞEMASI YOK/public değil (binary
  string taraması `jetski_cortex_go_proto`/`gemini_coder.Step` gibi Google-içi
  paket adları buldu ama gerçek bir `.proto` dosyası yok). Resmi şema
  OLMADAN, GERÇEK konuşmalara karşı ampirik olarak reverse-engineer edildi —
  aşağıdaki `_iter_fields`/`_get_field` bkz. Bulunan (kod DEĞİL, sadece VERİ
  gözlemiyle doğrulanmış) alan haritası:
    - `steps.step_type` SQLite kolonu == blob'un kendi üst-seviye alan `1`'i
      (aynı değer iki yerde de duruyor, çapraz doğrulandı).
    - `step_type==14` (user): üst-seviye alan `19`, onun alt-alanı `2` = KULLANICININ
      YAZDIĞI DÜZ METİN. Enjekte edilen sistem/tool/skill bağlamı (codex'in
      `<environment_context>` sarmalayıcısının muadili) AYRI bir alanda
      (`19.12`) — yani metnin KENDİSİ zaten temiz, codex'teki gibi bir prefix
      filtresi GEREKMİYOR.
    - `step_type==15` (assistant): üst-seviye alan `20`, alt-alan `1` =
      KULLANICIYA GÖSTERİLEN gerçek yanıt metni (alan `8` bunun birebir
      kopyası — hangisi kullanılsa fark etmez, `1` seçildi). Alt-alan `3` =
      İÇSEL düşünce/reasoning özeti (ör. "**Analyzing Tool Utilization**...") —
      BİLEREK KULLANILMIYOR, claude'un `thinking` bloklarını/`tool_use`'u
      dışladığı ilkeyle AYNI (sadece görünür sohbet metni). Sadece tool-call
      yapıp henüz görünür metin üretmemiş bir adımda `20.1` YOK — bu adımlar
      `full_history`'de haklı olarak atlanıyor (claude/codex'in "boş metin
      hariç" kuralıyla aynı).
    - `step_type==132` (tool RESULT) ve `step_type==101` (`agent_message` —
      subagent'tan parent'a mesaj, claude'un `isSidechain` ile dışladığı
      Task-subagent transkriptinin doğrudan muadili) BİLEREK OKUNMUYOR bile
      (SQL sorgusu `step_type IN (14,15)` ile filtreliyor) — ne asıl
      kullanıcı+görünür-asistan sohbetinin bir parçası.
    - `google.protobuf`/`protoc` bağımlılığı EKLENMEDİ — sadece yukarıdaki 2
      alan-yolunu (üst-seviye N → onun alt-alanı M) okumak için minimal, saf
      Python bir varint/wire-format okuyucu yeterli (`_iter_fields`), tam
      şema/deserializer gerekmiyor. İki BAĞIMSIZ gerçek conversation'a karşı
      (biri ağır tool-kullanımlı bir "research subagent" görevi, diğeri
      sıradan çok-turlu bir Türkçe sohbet) ayrı ayrı doğrulandı — ikisinde de
      TÜM user/assistant turn'leri doğru sırada, doğru metinle, doğru
      filtrelenmiş (iç düşünce/tool-noise YOK) çıktı verdi.
    - **Kırılganlık:** bu ŞEMASIZ/resmi-olmayan bir formatın alan NUMARASI
      seviyesinde reverse-engineer edilmiş hâli — agy'nin bir güncellemesi
      alan numaralarını (protobuf'ta nadir ama İMKANSIZ değil) ya da genel
      mesaj yapısını değiştirirse bu sessizce YANLIŞ/boş sonuç dönebilir
      (crash değil — `_iter_fields`/`get_str` her adımda best-effort, hata
      yutup "" döner). TODO.md'nin "CLI'lar sabit durmuyor" ilkesiyle aynı
      risk sınıfı; bir sonraki agy güncellemesinde `last_exchange`/
      `full_history`'nin çıktısı BOŞ/saçma görünürse önce burası şüphelenilmeli.
"""
from __future__ import annotations
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import time
from typing import Dict, List, Optional, Tuple

from .base import CliProvider

CONVERSATIONS_CACHE = os.path.expanduser("~/.gemini/antigravity-cli/cache/last_conversations.json")
CONVERSATIONS_DIR = os.path.expanduser("~/.gemini/antigravity-cli/conversations")

# step_type'ın bilinen anlamları (yukarıdaki modül docstring'inin veri kaynağı) —
# sadece bu ikisi kullanıcı-görünür user/assistant turn'lerini taşıyor.
_STEP_TYPE_USER = 14
_STEP_TYPE_ASSISTANT = 15


def _read_varint(data: bytes, i: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while True:
        b = data[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7


def _iter_fields(data: bytes):
    """Şemasız minimal protobuf wire-format okuyucu — sadece TOP-LEVEL alanları
    (field_no, wire_type, value) olarak sırayla üretir; length-delimited (wire
    type 2) alanlar ham `bytes` olarak döner (string mi yoksa iç içe bir mesaj
    mı — çağıran zaten hangi alan numarasını aradığını bildiği için karar
    verir, burada şema YOK). `google.protobuf` paketine bağımlılık YOK —
    modül docstring'indeki bulguya göre sadece 2 sabit alan-yolu okunuyor,
    tam bir deserializer'a gerek yok."""
    i = 0
    n = len(data)
    while i < n:
        tag, i = _read_varint(data, i)
        wire_type = tag & 0x7
        field_no = tag >> 3
        if wire_type == 0:
            val, i = _read_varint(data, i)
        elif wire_type == 1:
            val, i = data[i:i + 8], i + 8
        elif wire_type == 2:
            length, i = _read_varint(data, i)
            val, i = data[i:i + length], i + length
        elif wire_type == 5:
            val, i = data[i:i + 4], i + 4
        else:
            return  # bilinmeyen/desteklenmeyen wire type — geri kalanı güvenilir parse edilemez, sessizce dur
        yield field_no, wire_type, val


def _get_bytes_field(data: bytes, field_no: int) -> Optional[bytes]:
    """Belirtilen alan numarasının SON (protobuf'un "tekil alanda son yazan
    kazanır" birleştirme kuralı) length-delimited değerini döndürür — bulunamazsa
    None. Hatalı/bozuk bayt dizisi ASLA fırlatmaz (best-effort, claude_provider.py/
    codex_provider.py'nin `except (OSError, json.JSONDecodeError): pass` deseniyle
    AYNI tolerans), sadece None döner."""
    found: Optional[bytes] = None
    try:
        for field_no_i, wire_type, val in _iter_fields(data):
            if field_no_i == field_no and wire_type == 2:
                found = val
    except (IndexError, ValueError):
        return found
    return found


def _get_text_field(data: bytes, field_no: int) -> str:
    v = _get_bytes_field(data, field_no)
    return v.decode("utf-8", errors="replace") if v is not None else ""


def _step_user_text(payload: bytes) -> str:
    """`step_type==14` adımının alan `19` alt-mesajının alan `2`'si — bkz.
    modül docstring'i."""
    f19 = _get_bytes_field(payload, 19)
    return _get_text_field(f19, 2) if f19 is not None else ""


def _step_assistant_text(payload: bytes) -> str:
    """`step_type==15` adımının alan `20` alt-mesajının alan `1`'i (görünür
    yanıt) — alan `3` (iç düşünce) BİLEREK atlanıyor, bkz. modül docstring'i."""
    f20 = _get_bytes_field(payload, 20)
    return _get_text_field(f20, 1) if f20 is not None else ""


PERMISSION_MODES = ["auto", "acceptEdits", "plan"]
EFFORT_LEVELS = ["low", "medium", "high"]

_PERMISSION_FLAGS = {
    "auto": ["--dangerously-skip-permissions"],
    "acceptEdits": ["--mode", "accept-edits"],
    "plan": ["--mode", "plan"],
}

_MODELS_TTL = 300.0  # agy models sabit değil (2 günde bir kez değişti) — canlı çek, ama her 4s status poll'unda değil


def _arg(cmd: List[str], flag: str) -> Optional[str]:
    try:
        i = cmd.index(flag)
    except ValueError:
        return None
    return cmd[i + 1] if i + 1 < len(cmd) else None


class AgyProvider(CliProvider):
    name = "agy"

    def __init__(self) -> None:
        self._cache_ts = 0.0
        self._cache_models: List[str] = []

    def resolve_resume_id(self, cwd: str) -> Optional[str]:
        try:
            with open(CONVERSATIONS_CACHE, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        val = data.get(cwd) or data.get(os.path.normpath(os.path.abspath(cwd)))
        return val.strip() if isinstance(val, str) and val.strip() else None

    def build_inner_command(self, cwd, model, permission_mode, effort,
                             resume_id, prompt, session_name) -> str:
        # Mutlak yol — bkz. claude_provider.py'deki aynı fix'in yorumu (pane'in kendi
        # PATH'i tmux server'ın miras kaldığından farklı/eksik olabilir).
        parts = [shutil.which("agy") or "agy"]
        if resume_id:
            parts += ["--conversation", shlex.quote(resume_id)]
        parts += ["--model", shlex.quote(model)]
        parts += ["--effort", shlex.quote(effort or "medium")]
        parts += _PERMISSION_FLAGS.get(permission_mode or "auto", _PERMISSION_FLAGS["auto"])
        if prompt:
            parts += ["-i", shlex.quote(prompt)]
        return " ".join(parts)

    def env_overrides(self, session_name: str) -> Dict[str, str]:
        return {"COPS_NAME": session_name}

    def matches_proc(self, cmd: List[str]) -> bool:
        return bool(cmd) and os.path.basename(cmd[0]) == "agy"

    def extract_name(self, proc, cmd: List[str]) -> Optional[str]:
        try:
            name = proc.environ().get("COPS_NAME")
        except Exception:
            name = None
        return name or f"agy-{proc.pid}"

    def extract_info(self, cmd: List[str]) -> Dict[str, Optional[str]]:
        if "--dangerously-skip-permissions" in cmd:
            permission_mode = "auto"
        else:
            mode = _arg(cmd, "--mode")
            permission_mode = {"accept-edits": "acceptEdits", "plan": "plan"}.get(mode)
        return {
            "sid": _arg(cmd, "--conversation"),
            "model": _arg(cmd, "--model"),
            "permission_mode": permission_mode,
            "effort": _arg(cmd, "--effort"),
        }

    def model_choices(self) -> List[str]:
        now = time.monotonic()
        if now - self._cache_ts > _MODELS_TTL:
            # Denemeyi başarısız/boş olsa BİLE damgala — yoksa (agy sign-out/hata
            # durumunda) `if models:` hiç tetiklenmez, _cache_ts sabit kalır ve TTL
            # asla dolmadığı için panel her 4s status poll'unda yeniden subprocess
            # çalıştırır (canlı yaşandı: agy sign-out olunca her poll'da ~1s'lik
            # `agy models` çağrısı — TTL'nin var oluş amacını boşa çıkarıyordu).
            self._cache_ts = now
            try:
                out = subprocess.run(["agy", "models"], capture_output=True, text=True,
                                      timeout=5).stdout
                # "agy models" gerçek satırlardan ÖNCE bir durum satırı basıyor
                # ("Fetching available models..." — tab YOK) — sadece gerçek
                # `id\tLabel` satırlarını al, yoksa bu satır ilk "model" gibi görünüp
                # panelde "Fetching available models..." diye anlamsız bir seçenek çıkıyordu.
                models = [ln.split("\t", 1)[0].strip() for ln in out.splitlines() if "\t" in ln]
                if models:
                    self._cache_models = models
            except Exception:
                pass  # eski (belki boş) cache kalır — status endpoint'i asla patlamasın
        return self._cache_models

    def permission_modes(self) -> List[str]:
        return PERMISSION_MODES

    def effort_levels(self) -> List[str]:
        return EFFORT_LEVELS

    def _transcript_steps(self, cwd: str, sid: Optional[str]) -> List[Tuple[int, bytes]]:
        """claude/codex provider'larının `_transcript_lines`'ıyla AYNI sözleşme:
        bulunamazsa/okunamazsa boş liste — 'desteklenmiyor' ile 'henüz mesaj yok'
        ayrımı ÇAĞIRAN tarafın işi, burada değil. `sid` yoksa (fresh/`--new`
        muadili) `resolve_resume_id` ile cwd'den çözülür (aynı `--conversation`
        argümanının spawn-zamanındaki çözümü)."""
        conv_id = sid or self.resolve_resume_id(cwd)
        if not conv_id:
            return []
        db_path = os.path.join(CONVERSATIONS_DIR, f"{conv_id}.db")
        if not os.path.isfile(db_path):
            return []
        try:
            # mode=ro: SADECE okuma — agy'nin kendi canlı DB'sine (WAL modunda,
            # aktif yazılıyor olabilir) yanlışlıkla dokunmak/var-olmayan bir
            # dosya yaratmak İSTENMİYOR (sqlite3.connect normal modda dosya
            # yoksa SESSİZCE boş bir dosya YARATIR — ro modu bunu da engeller).
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
            try:
                rows = conn.execute(
                    "SELECT step_type, step_payload FROM steps WHERE step_type IN (?, ?) ORDER BY idx",
                    (_STEP_TYPE_USER, _STEP_TYPE_ASSISTANT),
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return []
        return [(t, p) for t, p in rows if isinstance(p, (bytes, bytearray))]

    def last_exchange(self, cwd: str, sid: Optional[str]) -> Optional[Dict[str, str]]:
        # claude/codex provider'larıyla AYNI "her zaman dict, None değil" sözleşmesi
        # (None SADECE base.py'nin "desteklenmiyor" varsayılanında kalsın diye).
        empty = {"user": "", "assistant": ""}
        steps = self._transcript_steps(cwd, sid)
        ai_idx: Optional[int] = None
        ai_text = ""
        for i in range(len(steps) - 1, -1, -1):
            step_type, payload = steps[i]
            if step_type == _STEP_TYPE_ASSISTANT:
                text = _step_assistant_text(payload)
                if text:
                    ai_text, ai_idx = text, i
                    break
        if ai_idx is None:
            return empty
        user_text = ""
        for i in range(ai_idx - 1, -1, -1):
            step_type, payload = steps[i]
            if step_type == _STEP_TYPE_USER:
                user_text = _step_user_text(payload)
                break
        return {"user": user_text, "assistant": ai_text}

    def full_history(self, cwd: str, sid: Optional[str]) -> Optional[List[Dict[str, str]]]:
        # last_exchange'in tek-son-çift filtreleriyle AYNI kurallar (boş metin
        # hariç) — SADECE SONUNCUYU almak yerine sırayla HEPSİNİ biriktirir.
        out: List[Dict[str, str]] = []
        for step_type, payload in self._transcript_steps(cwd, sid):
            if step_type == _STEP_TYPE_USER:
                text = _step_user_text(payload)
                if text:
                    out.append({"role": "user", "text": text})
            elif step_type == _STEP_TYPE_ASSISTANT:
                text = _step_assistant_text(payload)
                if text:
                    out.append({"role": "assistant", "text": text})
        return out
