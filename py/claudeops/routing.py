"""İşe göre model/effort yönlendirme yönergesi (TBD#91, 2026-10-19).

Tek kaynak: paketlenmiş `data/routing.md`, ya da Ayarlar'daki `routing_guidance_text` doluysa o metin.
Teslim:
- claude: her açılışta `--append-system-prompt-file <yol>` (`claude_guidance_path`); proje CLAUDE.md'lerine dokunulmaz.
- codex: `~/.codex/AGENTS.md` içinde işaretli bir blok (`sync_global_files`); işaretin DIŞINA dokunmaz, ilk yazımda `.bak-routing` yedeği alır.
- agy: `~/.gemini/GEMINI.md` (canary ile doğrulandı 2026-10-19; dosya yoksa YALNIZ bu blokla oluşturulur, blok kalkınca
  dosya yalnız bloktan ibaretse silinir).
- copilot: küresel dosya yolu DOĞRULANAMADI (hesap aylık kotası dolu, canary çalışmadı); şimdilik yok.
Açık oturumlar yönergeyi ancak yeniden açılınca alır.
"""
from __future__ import annotations
import os
import shutil
from typing import Dict, Optional

from .paths import CLAUDEOPS_DIR
from .settings import load_settings, routing_guidance_enabled

BUNDLED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "routing.md")
OVERRIDE_PATH = os.path.join(CLAUDEOPS_DIR, "routing-guidance.md")
BLOCK_BEGIN = "<!-- claudeops-routing:begin -->"
BLOCK_END = "<!-- claudeops-routing:end -->"
CODEX_AGENTS = os.path.expanduser("~/.codex/AGENTS.md")
AGY_GEMINI = os.path.expanduser("~/.gemini/GEMINI.md")


def routing_text() -> str:
    """Etkin yönerge metni: Ayarlar'daki override doluysa o, yoksa paketlenmiş dosya. Okunamazsa boş."""
    override = str(load_settings().get("routing_guidance_text") or "").strip()
    if override:
        return override + "\n"
    try:
        with open(BUNDLED_PATH, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def claude_guidance_path() -> Optional[str]:
    """`--append-system-prompt-file` için yol; kapalıysa ya da metin boşsa None. Override varsa `CLAUDEOPS_DIR`e yazılır
    (içerik değişmediyse yeniden yazılmaz). Asla fırlatmaz: spawn yolu bir yönerge yüzünden ASLA başarısız olmamalı."""
    try:
        if not routing_guidance_enabled():
            return None
        text = routing_text()
        if not text.strip():
            return None
        if not str(load_settings().get("routing_guidance_text") or "").strip():
            return BUNDLED_PATH
        try:
            with open(OVERRIDE_PATH, encoding="utf-8") as f:
                if f.read() == text:
                    return OVERRIDE_PATH
        except OSError:
            pass
        os.makedirs(CLAUDEOPS_DIR, exist_ok=True)
        with open(OVERRIDE_PATH, "w", encoding="utf-8") as f:
            f.write(text)
        return OVERRIDE_PATH
    except Exception:
        return None


def _with_block(existing: str, block_body: Optional[str]) -> str:
    """`existing` içindeki işaretli bloğu `block_body` ile değiştir (None = bloğu kaldır); blok yoksa sona ekle."""
    begin, end = existing.find(BLOCK_BEGIN), existing.find(BLOCK_END)
    if begin != -1 and end > begin:
        head, tail = existing[:begin].rstrip("\n"), existing[end + len(BLOCK_END):].lstrip("\n")
        rest = (head + ("\n\n" if head and tail else "") + tail) if (head or tail) else ""
        existing = rest
    if block_body is None:
        return existing if not existing or existing.endswith("\n") else existing + "\n"
    block = f"{BLOCK_BEGIN}\n{block_body.rstrip()}\n{BLOCK_END}\n"
    return (existing.rstrip("\n") + "\n\n" if existing.strip() else "") + block


def _sync_one(path: str, create: bool) -> str:
    """Tek dosyada işaretli bloğu Ayarlar'a göre yaz/kaldır. `create`: dosya yoksa yalnız bu blokla oluştur (agy);
    değilse dosya yokken dokunma (codex kurulu değilse yeni dosya açma). Sonuç: written|removed|unchanged|skipped:<neden>."""
    exists = os.path.isfile(path)
    if not exists and not create:
        return "skipped:no file"
    try:
        current = ""
        if exists:
            with open(path, encoding="utf-8") as f:
                current = f.read()
        body = routing_text() if routing_guidance_enabled() else ""
        new = _with_block(current, body if body.strip() else None)
        if new == current:
            return "unchanged"
        if exists and new.strip() == "" and create:
            os.remove(path)   # biz oluşturduk ve içinde başka bir şey kalmadı
            return "removed"
        backup = path + ".bak-routing"
        if exists and not os.path.exists(backup):
            shutil.copy2(path, backup)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp-routing"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, path)
        return "written" if body.strip() else "removed"
    except OSError as e:
        return f"skipped:{e.__class__.__name__}"


def sync_global_files(codex_path: str = CODEX_AGENTS, agy_path: str = AGY_GEMINI) -> Dict[str, str]:
    """Yönergeyi codex'in `AGENTS.md`sine ve agy'nin `GEMINI.md`sine işaretli blok olarak yaz (kapalıysa kaldır).
    Sonuç: {"codex": ..., "agy": ...}. codex dosyası yoksa oluşturulmaz; agy dosyası yoksa oluşturulur."""
    return {"codex": _sync_one(codex_path, create=False), "agy": _sync_one(agy_path, create=True)}
