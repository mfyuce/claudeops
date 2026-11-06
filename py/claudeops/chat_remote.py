"""Uzak host (yuhem, ulak_31) sohbet arşivini çekme adımları: saf mantık + enjekte edilebilir aktarım.

Bilinen uzak tuhaflıklar (canlı oturumda gözlendi, chats/CLAUDE.md):
  1. Shell oturumuna gönderilen komutun İLK KARAKTERİ kaybolabiliyor: komut BOŞLUK ile başlar (kaybolan boşluktur).
  2. files API kökü = shell oturumunun CANLI cwd'si ve başka biri aynı shell'i kullanırken cwd DEĞİŞEBİLİR (yuhem'de gözlendi:
     iki okuma arasında e3 -> e3p): başta kök (`root()`) bir kez okunur, arşiv o MUTLAK dizine yazılır, listeleme/indirme `path=root` ile yapılır.
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
    def idle(self) -> bool: ...                            # shell komut bekliyor mu (prompt satırı); başkası çalıştırıyorsa False
    def root(self) -> str: ...                             # files API kökü (shell'in o anki cwd'si, mutlak)
    def listing(self, root: str) -> List[str]: ...         # root dizinindeki dosya adları
    def download(self, root: str, name: str, dest: str) -> int: ...   # bayt sayısı


def names(tag: str, day: str) -> Dict[str, str]:
    if not _TAG.match(tag) or not re.match(r"^\d{8}$", day):
        raise ValueError("etiket/gün geçersiz")
    base = f".chatpull-{tag}-{day}"
    return {"tmp": base + ".tgz.part", "tgz": base + ".tgz", "done": base + ".done"}


def _o(outdir: str, name: str) -> str:
    return shlex.quote(outdir.rstrip("/") + "/" + name) if outdir else name


def pack_command(tag: str, day: str, paths: Optional[List[str]] = None, outdir: str = "") -> str:
    """BOŞLUK-önekli, düşük öncelikli tar; bitince `.done` işareti. Kaynaklar `-C ~` ile (cwd DEĞİŞMEZ: files kökü bozulmaz); çıktı cwd'ye göreli."""
    n = names(tag, day)
    ps = " ".join(shlex.quote(p) for p in (paths or DEFAULT_PATHS))
    return (f" nice -n 19 ionice -c3 tar czf {_o(outdir, n['tmp'])} --ignore-failed-read -C ~ {ps} 2>/dev/null; "
            f"mv {_o(outdir, n['tmp'])} {_o(outdir, n['tgz'])} && touch {_o(outdir, n['done'])}")


def cleanup_command(tag: str, day: str, outdir: str = "") -> str:
    n = names(tag, day)
    return f" rm -f -- {_o(outdir, n['tmp'])} {_o(outdir, n['tgz'])} {_o(outdir, n['done'])}"     # yalnız kendi üç geçici dosyası


def pull(tx: Transport, tag: str, day: str, dest: str, paths: Optional[List[str]] = None,
         wait_s: float = 3600, poll_s: float = 15, sleep: Callable[[float], None] = time.sleep,
         clock: Callable[[], float] = time.monotonic) -> Dict[str, Any]:
    """pack -> `.done` bekle -> indir -> kendi geçici dosyalarını sil. Asla fırlatmaz; dönüş {ok, msg, bytes}."""
    try:
        n = names(tag, day)
        if not tx.idle():                  # paylaşımlı shell: başkası bir iş çalıştırıyor/yazıyor -> TEMİZ vazgeç, hiçbir şey gönderme
            return {"ok": False, "skipped": True, "msg": "shell meşgul, vazgeçildi (sonraki koşuda denenir)", "bytes": 0}
        root = tx.root()
        tx.send(pack_command(tag, day, paths, root))
        t0 = clock()
        while n["done"] not in tx.listing(root):
            if clock() - t0 > wait_s:
                return {"ok": False, "msg": "uzak arşiv zaman aşımı (.done yok)", "bytes": 0}
            sleep(poll_s)
        size = tx.download(root, n["tgz"], dest)
        if size <= 0:
            return {"ok": False, "msg": "indirilen arşiv boş", "bytes": 0}
        tx.send(cleanup_command(tag, day, root))
        return {"ok": True, "msg": f"{tag}: {size} bayt", "bytes": size}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"{type(e).__name__}: {e}"[:200], "bytes": 0}


class PanelTransport:
    """Panel API üzerinden canlı uzak shell oturumu (`/api/term/input`, `/api/files/*`, host=<ad>); istek zaman aşımı 90 sn."""
    TO = 90.0

    def __init__(self, host: str, session: str):
        self.host, self.session = host, session

    def send(self, cmd: str) -> None:
        from .commands import web_hosts as H
        r, _s = H.proxy_action("/api/term/input", self.host, {"name": self.session, "text": cmd}, timeout=self.TO)
        if not r.get("ok"):
            raise RuntimeError(f"term/input: {r}"[:150])

    def idle(self) -> bool:
        from .commands import web_hosts as H
        r, _s = H.proxy_get("/api/term/output", self.host, {"name": self.session, "lang": "en"}, dedup=False, timeout=self.TO)
        lines = [ln for ln in str(r.get("text", "")).rstrip().split("\n") if ln.strip()]
        return bool(r.get("ok")) and bool(lines) and bool(re.search(r"[$#%>] ?$", lines[-1].rstrip() + " "))

    def _list(self, path: str = "") -> Dict[str, Any]:
        from .commands import web_hosts as H
        q = {"name": self.session, "lang": "en"}
        if path:
            q["path"] = path
        r, _s = H.proxy_get("/api/files/list", self.host, q, dedup=False, timeout=self.TO)
        if not r.get("ok"):
            raise RuntimeError(f"files/list: {r}"[:150])
        return r

    def root(self) -> str:
        return str(self._list()["path"])

    def listing(self, root: str) -> List[str]:
        return [e["name"] for e in self._list(root).get("entries", []) if not e.get("is_dir")]

    def download(self, root: str, name: str, dest: str) -> int:
        from .commands import web_hosts as H
        body, _st, _h, err = H.proxy_get_raw("/api/files/download", self.host,
                                             {"name": self.session, "path": root.rstrip("/") + "/" + name, "lang": "en"})
        if err or not body:
            raise RuntimeError(f"files/download: {err}"[:150])
        import os
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, dest)
        return len(body)
