"""`py/cops ucli-push <host> --session <oturum>`: yerel `ucli` ikilisini uzak host'a, host-yönlendirmeli `/api/files/upload`
ile SAHNELEME adıyla (`ucli.new`, `overwrite=0`) gönderir ve geri indirip sha256'sını doğrular. Çalışan `ucli`yi EZMEZ,
uzakta komut çalıştırmaz, ANAHTAR göndermez; son adımı (taşıma/`chmod +x`) sahibin kabuğuna bırakır ve komutları yazdırır.
`--dry-run`: yalnız plan (yerel sha256/boyut, hedef). Hedef dizin uzak oturumun izinli köklerinden biri olmak zorunda.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import urllib.parse
from typing import Any, Dict, Optional, Tuple

from . import mcp_queue
from .. import ucli_client

CHUNK = 1 << 20


def sha256_file(path: str) -> Tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
            n += len(b)
    return h.hexdigest(), n


def _conn(port: int) -> http.client.HTTPConnection:
    return http.client.HTTPConnection("127.0.0.1", port, timeout=600)


def upload(port: int, host: str, session: str, directory: str, filename: str, binary: str, size: int) -> Dict[str, Any]:
    q = {"name": session, "host": host, "filename": filename, "overwrite": "0"}
    if directory:
        q["path"] = directory
    conn = _conn(port)
    try:
        with open(binary, "rb") as f:
            conn.request("POST", "/api/files/upload?" + urllib.parse.urlencode(q), body=f,
                         headers={"Authorization": f"Bearer {mcp_queue._read_token()}",
                                  "Content-Type": "application/octet-stream", "Content-Length": str(size)})
            resp = conn.getresponse()
            raw = resp.read()
        return json.loads(raw.decode("utf-8", "replace"))
    except (OSError, ValueError, http.client.HTTPException) as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        conn.close()


def remote_sha256(port: int, host: str, session: str, remote_path: str) -> Tuple[str, int, str]:
    """Yüklenen dosyayı host-yönlendirmeli indirip (sha256, bayt, hata)."""
    q = {"name": session, "host": host, "path": remote_path}
    conn = _conn(port)
    try:
        conn.request("GET", "/api/files/download?" + urllib.parse.urlencode(q),
                     headers={"Authorization": f"Bearer {mcp_queue._read_token()}"})
        resp = conn.getresponse()
        if resp.status != 200:
            return "", 0, f"HTTP {resp.status}: {resp.read(300).decode('utf-8', 'replace')}"
        h = hashlib.sha256()
        n = 0
        for b in iter(lambda: resp.read(CHUNK), b""):
            h.update(b)
            n += len(b)
        return h.hexdigest(), n, ""
    except (OSError, http.client.HTTPException) as e:
        return "", 0, f"{type(e).__name__}: {e}"
    finally:
        conn.close()


def push(port: int, host: str, session: str, directory: str = "", filename: str = "ucli.new", binary: str = "",
         dry: bool = False) -> Dict[str, Any]:
    try:
        binary = binary or ucli_client.resolve_binary()
    except ucli_client.UcliError as e:
        return {"ok": False, "error": str(e)[:300]}
    if not os.path.isfile(binary):
        return {"ok": False, "error": f"ucli ikilisi bulunamadı: {binary}"}
    if "/" in filename or filename in ("", ".", "..") or filename == "ucli":
        return {"ok": False, "error": "filename sahneleme adı olmalı (yol yok, çalışan 'ucli' adı yasak)"}
    digest, size = sha256_file(binary)
    out: Dict[str, Any] = {"ok": True, "host": host, "session": session, "binary": binary, "sha256": digest[:12],
                           "size": size, "dir": directory or "(oturumun ilk kökü)", "filename": filename, "dry": dry}
    if dry:
        return out
    up = upload(port, host, session, directory, filename, binary, size)
    if not up.get("ok"):
        return dict(out, ok=False, error=str(up.get("error") or up)[:300])
    rpath = str(up.get("path") or "")
    got, n, err = remote_sha256(port, host, session, rpath)
    if err or got != digest:
        return dict(out, ok=False, remote_path=rpath, error=err or f"sha256 uyuşmadı: yerel {digest[:12]} uzak {got[:12]} ({n} bayt)")
    out.update(remote_path=rpath, verified=True,
               next_steps=[f"chmod +x {rpath}", f"{rpath} --version  # sha256 {digest[:12]} ile eşleşmeli",
                           f"mv ~/.local/bin/ucli ~/.local/bin/ucli.old && mv {rpath} ~/.local/bin/ucli  # yol makineye göre; sahibin işi"])
    return out


def register(sub) -> None:
    p = sub.add_parser("ucli-push", help="yerel ucli ikilisini uzak host'a sahneleme adıyla gönder + sha256 doğrula "
                                         "(çalışan ucli'yi ezmez, uzakta komut çalıştırmaz, anahtar göndermez)")
    p.add_argument("host", help="hosts.json'daki uzak host adı (örn. ulak_31)")
    p.add_argument("--session", required=True, help="o host'ta çalışan/kayıtlı bir oturum adı (izinli kökleri belirler)")
    p.add_argument("--dir", default="", help="uzak hedef dizin (oturumun izinli köklerinden biri; boş = ilk kök)")
    p.add_argument("--filename", default="ucli.new", help="sahneleme adı (varsayılan ucli.new)")
    p.add_argument("--binary", default="", help="yerel ucli yolu (varsayılan: ayarlardaki/PATH'teki)")
    p.add_argument("--port", type=int, default=mcp_queue.DEFAULT_PORT)
    p.add_argument("--dry-run", action="store_true", help="yalnız plan: yerel sha256/boyut ve hedef")
    p.set_defaults(func=run)


def run(args) -> int:
    out = push(args.port, args.host, args.session, args.dir, args.filename, args.binary, args.dry_run)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1
