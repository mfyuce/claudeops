"""Uzak host (yuhem, ulak_31) sohbet arşivini çekme adımları: saf mantık + enjekte edilebilir aktarım.

Bilinen uzak tuhaflıklar (canlı oturumda gözlendi, chats/CLAUDE.md):
  1. Shell oturumuna gönderilen komutun İLK KARAKTERİ kaybolabiliyor: komut BOŞLUK ile başlar (kaybolan boşluktur).
  2. files API kökü = shell oturumunun CANLI cwd'si: arşiv, mutlak yol değil, GÖRELİ adla (cwd'ye) yazılır ve oradan indirilir.
Yıkıcı komut yok: yalnız kendi geçici dosyasını (`.chatpull-<etiket>.*`) siler; kullanıcı dosyalarına dokunmaz.
"""
from __future__ import annotations

import re
import shlex
import time
from typing import Any, Callable, Dict, List, Optional, Protocol

_TAG = re.compile(r"^[a-z0-9_]{1,24}$")
DEFAULT_PATHS = [".claude/projects", ".claude/history.jsonl", ".codex", ".gemini"]


class Transport(Protocol):
    def send(self, cmd: str) -> None: ...                  # shell oturumuna tek satır yaz
    def listing(self) -> List[str]: ...                    # files API kökündeki dosya adları
    def download(self, name: str, dest: str) -> int: ...   # bayt sayısı


def names(tag: str, day: str) -> Dict[str, str]:
    if not _TAG.match(tag) or not re.match(r"^\d{8}$", day):
        raise ValueError("etiket/gün geçersiz")
    base = f".chatpull-{tag}-{day}"
    return {"tmp": base + ".tgz.part", "tgz": base + ".tgz", "done": base + ".done"}


def pack_command(tag: str, day: str, paths: Optional[List[str]] = None) -> str:
    """BOŞLUK-önekli, düşük öncelikli tar; bitince `.done` işareti. Kaynaklar `-C ~` ile (cwd DEĞİŞMEZ: files kökü bozulmaz); çıktı cwd'ye göreli."""
    n = names(tag, day)
    ps = " ".join(shlex.quote(p) for p in (paths or DEFAULT_PATHS))
    return (f" nice -n 19 ionice -c3 tar czf {n['tmp']} --ignore-failed-read -C ~ {ps} 2>/dev/null; "
            f"mv {n['tmp']} {n['tgz']} && touch {n['done']}")


def cleanup_command(tag: str, day: str) -> str:
    n = names(tag, day)
    return f" rm -f -- {n['tmp']} {n['tgz']} {n['done']}"     # yalnız kendi üç geçici dosyası


def pull(tx: Transport, tag: str, day: str, dest: str, paths: Optional[List[str]] = None,
         wait_s: float = 3600, poll_s: float = 15, sleep: Callable[[float], None] = time.sleep,
         clock: Callable[[], float] = time.monotonic) -> Dict[str, Any]:
    """pack -> `.done` bekle -> indir -> kendi geçici dosyalarını sil. Asla fırlatmaz; dönüş {ok, msg, bytes}."""
    try:
        n = names(tag, day)
        tx.send(pack_command(tag, day, paths))
        t0 = clock()
        while n["done"] not in tx.listing():
            if clock() - t0 > wait_s:
                return {"ok": False, "msg": "uzak arşiv zaman aşımı (.done yok)", "bytes": 0}
            sleep(poll_s)
        size = tx.download(n["tgz"], dest)
        if size <= 0:
            return {"ok": False, "msg": "indirilen arşiv boş", "bytes": 0}
        tx.send(cleanup_command(tag, day))
        return {"ok": True, "msg": f"{tag}: {size} bayt", "bytes": size}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"{type(e).__name__}: {e}"[:200], "bytes": 0}
