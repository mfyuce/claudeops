"""İşe göre model/effort yönlendirme yönergesi (TBD#91, 2026-10-19).

Tek kaynak: paketlenmiş `data/routing.md`, ya da Ayarlar'daki `routing_guidance_text` doluysa o metin.
Teslim:
- claude: her açılışta `--append-system-prompt-file <yol>` (`claude_guidance_path`); proje CLAUDE.md'lerine dokunulmaz.
- codex: `~/.codex/AGENTS.md` içinde işaretli bir blok (`sync_global_files`); işaretin DIŞINA dokunmaz, ilk yazımda `.bak-routing` yedeği alır.
- agy/copilot: küresel talimat dosyası konumu DOĞRULANMADI (hafıza `cli-instruction-files-canary`); şimdilik yok.
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


def sync_global_files(codex_path: str = CODEX_AGENTS) -> Dict[str, str]:
    """Yönergeyi codex'in küresel `AGENTS.md`sine işaretli blok olarak yaz (kapalıysa bloğu kaldır). Sonuç:
    {"codex": "written|removed|unchanged|skipped:<neden>"}. Dosya yoksa oluşturmaz (codex kurulu değilse dokunma)."""
    out: Dict[str, str] = {}
    if not os.path.isfile(codex_path):
        return {"codex": "skipped:no AGENTS.md"}
    try:
        with open(codex_path, encoding="utf-8") as f:
            current = f.read()
        body = routing_text() if routing_guidance_enabled() else ""
        new = _with_block(current, body if body.strip() else None)
        if new == current:
            return {"codex": "unchanged"}
        backup = codex_path + ".bak-routing"
        if not os.path.exists(backup):
            shutil.copy2(codex_path, backup)
        tmp = codex_path + ".tmp-routing"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, codex_path)
        out["codex"] = "written" if body.strip() else "removed"
    except OSError as e:
        out["codex"] = f"skipped:{e.__class__.__name__}"
    return out
