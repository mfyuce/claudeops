"""ucli `--ask-dir` kanalı: oturumun soruları (`ask_user`) ve düzenleme onayları (`--ask-edit`) terminal yerine dosyaya gider;
panel okuyup cevaplar. Yaprak modül (web/provider içe aktarmaz).

Dosya sözleşmesi (unified-cli `ask_user.rs`): işçi `question.json` = `{id, header, question, options}` yazar ve AYNI SÜREÇTE
`answer.json` = `{id, text}` bekler (100 ms yoklama); cevap gelince ikisi de silinir. Süreç ölürse bekleyen soru kaybolur.

Güvenlik duruşu:
- Dizin `<CLAUDEOPS_DIR>/ucli_ask/<oturum>` (0700), oturum çalışma kökünün DIŞINDA: modelin kendi araçları erişemez (ucli de bunu ister).
- Varsayılan KAPALI (`ask_dir` başlatma seçeneği): açılınca o oturumun soruları terminalde GÖRÜNMEZ, yalnız panelden cevaplanır.
- Cevap yalnız bekleyen sorunun `id`'siyle eşleşirse yazılır (bayat/yanlış kimlik reddedilir); en çok 64 KiB (ucli sınırı).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional, Tuple

from .atomic_json import atomic_write_json
from .paths import CLAUDEOPS_DIR

ROOT = os.path.join(CLAUDEOPS_DIR, "ucli_ask")
MAX_ANSWER_BYTES = 64 * 1024
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


def dir_for(name: str, create: bool = False) -> str:
    if not _SAFE.match(name or ""):
        raise ValueError("geçersiz oturum adı")
    d = os.path.join(ROOT, name)
    if create:
        os.makedirs(ROOT, mode=0o700, exist_ok=True)
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
    return d


def pending(name: str) -> Optional[Dict[str, Any]]:
    """Bekleyen soru (`{id, header, question, options}`) ya da None. Bozuk/yarım dosya = None."""
    try:
        with open(os.path.join(dir_for(name), "question.json"), encoding="utf-8") as f:
            q = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(q, dict) or not isinstance(q.get("id"), int):
        return None
    opts = q.get("options")
    return {"id": q["id"], "header": str(q.get("header") or ""), "question": str(q.get("question") or ""),
            "options": [str(o) for o in opts] if isinstance(opts, list) else []}


def answer(name: str, qid: int, text: str) -> Tuple[bool, str]: 
    """Cevabı yazar. (ok, hata). Bekleyen soru yoksa ya da kimlik uyuşmazsa reddeder."""
    q = pending(name)
    if q is None:
        return False, "no pending question"
    if q["id"] != qid:
        return False, "stale question id"
    if len(text.encode("utf-8")) > MAX_ANSWER_BYTES:
        return False, "answer too large"
    atomic_write_json(os.path.join(dir_for(name), "answer.json"), {"id": qid, "text": text}, mode=0o600)
    return True, ""
