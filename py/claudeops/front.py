"""Rust ön kapı (copsd) ile Python arasındaki geçiş eki (docs/rust-strangler-plan.md bölüm 3-4, -prv).

- Ön kapı gizlisi: `<durum dizini>/front.secret` (`CLAUDEOPS_DIR`, yoksa `~/.claude/claudeops`; 0600) ya da `CLAUDEOPS_FRONT_SECRET`. `X-Cops-Front` başlığı bununla eşleşmeden
  ve eş loopback değilken `X-Forwarded-For` ile iç uçlara GÜVENİLMEZ. Gizli commit'e girmez (dosya kullanıcı dizininde).
- İç uçlar: `/api/_internal/authz` (Rust'un yerel uçları için kimlik + yetki sorusu), `/api/_internal/ws-ticket/consume`.
"""
from __future__ import annotations

import fcntl
import hmac
import os
import secrets
import tempfile
from typing import Any, Dict, Mapping, Optional

from . import paths

LOOPBACK = ("127.0.0.1", "::1")


def secret_path() -> str:
    return os.path.join(paths.CLAUDEOPS_DIR, "front.secret")   # deneme paneli canlı gizliyi kullanmaz (copsd `secret_file` ile aynı)


def read_secret() -> str:
    """Ortam değişkeni, yoksa dosya; ikisi de yoksa boş (özellik kapalı: hiçbir başlığa güvenilmez)."""
    env = os.environ.get("CLAUDEOPS_FRONT_SECRET", "")
    if env:
        return env
    return _file_secret()


def _file_secret() -> str:
    """Yalnız dosya (0600, UTF-8); kullanılamazsa boş."""
    try:
        st = os.stat(secret_path())
        if st.st_mode & 0o077:          # grup/diğer okuyabiliyorsa güvenme (sızmış sayılır)
            return ""
        with open(secret_path(), encoding="utf-8") as fh:
            return fh.read().strip()
    except (OSError, UnicodeError):     # bozuk (UTF-8 olmayan) dosya = gizli yok (kapalı yön)
        return ""


def ensure_secret() -> str:
    """Geçerli gizli varsa onu döner; yoksa (dosya yok, boş, bozuk ya da izni gevşemiş = sızmış sayılır) YENİ gizli üretir.
    Kilit altında, 0600 geçici dosya + `os.replace`: eşzamanlı çağıranlar diskteki tek değeri döner, okuyan yarım dosya görmez.
    `CLAUDEOPS_FRONT_SECRET` dosya üretimini ENGELLEMEZ (yalnız çağıranın kabuğunda olur; copsd ve web birimleri dosyayı okur)."""
    p = secret_path()
    cur = _file_secret()
    if cur:
        return cur
    d = os.path.dirname(p)
    os.makedirs(d, mode=0o700, exist_ok=True)
    with os.fdopen(os.open(p + ".lock", os.O_WRONLY | os.O_CREAT, 0o600), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)          # dosya kapanınca bırakılır
        cur = _file_secret()
        if cur:
            return cur
        val = secrets.token_hex(32)
        fd, tmp = tempfile.mkstemp(prefix=".front.secret.", dir=d)    # mkstemp 0600 açar
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(val + "\n")
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return val


def trusted_front(peer: str, headers: Mapping[str, str], secret: Optional[str] = None) -> bool:
    sec = read_secret() if secret is None else secret
    if not sec or peer not in LOOPBACK:
        return False
    got = headers.get("X-Cops-Front") or ""
    try:
        return hmac.compare_digest(got.encode(), sec.encode())
    except Exception:       # noqa: BLE001
        return False


def internal_authz(payload: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Rust'un sorusu: {method, path, query, headers{cookie, authorization}, client_ip, resource?{kind,host,name,steward}} ->
    {ok, authenticated, principal?{uid,roles,kind,ticket_id}, allowed?, action}. Karar Python'un bugünkü kurallarıyla aynı."""
    from . import authz
    method = str(payload.get("method") or "GET").upper()
    path = str(payload.get("path") or "")
    query = {str(k): str(v) for k, v in (payload.get("query") or {}).items()}
    hdr = {str(k).lower(): str(v) for k, v in (payload.get("headers") or {}).items()}
    cookies: Dict[str, str] = {}
    for part in (hdr.get("cookie") or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k:
            cookies[k] = v

    class _H(dict):
        def get(self, k, d=None):          # başlık adları büyük/küçük harf duyarsız (http.server.Message gibi)
            return super().get(str(k).lower(), d)

    view = authz.RequestView(method=method, path=path, query=query, headers=_H(hdr), cookies=cookies,
                             client_addr=str(payload.get("client_ip") or ""))
    if authz.has_authenticator():
        p = authz.authenticate(view)
        if p is None and path in ("/ws", "/ws/term") and query.get("ticket"):
            from . import ws_ticket
            p = ws_ticket.consume_principal(query["ticket"])
    else:
        p = None
        if token:
            cands = [query.get("token", "")]
            auth = hdr.get("authorization", "")
            if auth.startswith("Bearer "):
                cands.append(auth[len("Bearer "):].strip())
            for c in cands:
                try:
                    if secrets.compare_digest(c, token):
                        p = authz.LEGACY
                        break
                except TypeError:
                    continue
    action = authz.action_for(method, path)
    out: Dict[str, Any] = {"ok": True, "authenticated": p is not None, "action": action}
    if p is not None:
        out["principal"] = {"uid": p.uid, "roles": list(p.roles), "kind": p.kind, "ticket_id": p.ticket_id}
        r = payload.get("resource") or {}
        res = authz.Resource(kind=str(r.get("kind") or "global"), host=str(r.get("host") or ""), name=str(r.get("name") or ""),
                             steward=str(r.get("steward") or ""))
        out["allowed"] = bool(authz.check(p, action, res))
    return out


def ws_ticket_consume(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Tek kullanımlık WS bileti tüketir: {ticket} -> {ok, valid, principal?}. Bilet her durumda tüketilir."""
    from . import ws_ticket
    t = str(payload.get("ticket") or "")
    ok, p = ws_ticket.consume_full(t)
    if not ok:
        return {"ok": True, "valid": False, "principal": None}
    return {"ok": True, "valid": True,
            "principal": ({"uid": p.uid, "roles": list(p.roles), "kind": p.kind, "ticket_id": p.ticket_id} if p is not None else None)}
