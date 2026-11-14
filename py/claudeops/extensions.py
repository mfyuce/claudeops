"""Çekirdek GENİŞLEME NOKTALARI (open-core, docs/sql-gocu-plani.md Bölüm 0): çekirdek kanca tanımlar, `claudeops_enterprise`
(ayrı, özel paket) doldurur. Bağımlılık TEK YÖNLÜDÜR: çekirdek bu paketi ASLA doğrudan içe aktarmaz; yalnız `load()` adıyla,
yüklüyse, dener. Paket yoksa çekirdek davranışı DEĞİŞMEZ (sessiz geçer). Eklenti hatası çekirdeği düşürmez (diag + kayıt).

Sözleşme: eklenti `register(api)` tanımlar (`api` = `ExtensionAPI`), isteğe bağlı `REQUIRES_CORE_API` (tamsayı; çekirdeğin
`EXTENSION_API_VERSION`ıyla EŞİT olmalı, değilse yükleme reddedilir). Kancalar: `api.register_lens(...)` (reviewer merceği),
`api.register_route(prefix, fn, methods)` (panel sunucusuna yol öneki; yetki = panel token'ı YA DA token'la girişte verilen oturum çerezi),
`api.projects()`, `api.send_directive(...)`, `api.settings(key)` (çekirdek okuma/eylem yüzeyi, yalnız bunlar).
"""
from __future__ import annotations

import hmac
import hashlib
import importlib
import json
import threading
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

EXTENSION_API_VERSION = 1
PACKAGE = "claudeops_enterprise"

_LOCK = threading.RLock()
_STATE: Dict[str, Any] = {"loaded": False, "status": "not_loaded", "detail": "", "lenses": []}
_ROUTES: List[Dict[str, Any]] = []
UI_EXTENSION_API = 1
_UI_EXTS: Dict[str, Dict[str, Any]] = {}     # K10: id -> {title, assets_dir, roles, entry}
COOKIE_NAME = "cops_ext"
MAX_BODY = 1_000_000


class ExtensionAPI:
    """Eklentiye verilen yüzey (yalnız kayıt işlevleri; çekirdek iç durumuna doğrudan erişim yok)."""
    api_version = EXTENSION_API_VERSION

    def register_lens(self, name: str, tr: str, en: str, format_tr: str = "", format_en: str = "") -> None:
        from . import review as rv
        if name in _STATE["lenses"]:
            return                          # aynı eklenti yeniden yüklenirse (force) idempotent; yerleşik/başkasının adını ezmek review'da reddedilir
        rv.register_lens(name, tr, en, format_tr, format_en)
        _STATE["lenses"].append(name)


    def register_route(self, prefix: str, fn: Callable[["RouteRequest"], None], methods: Any = ("GET",)) -> None:
        """`prefix` ("/reader/") ile başlayan yollar `fn(req)`e gider. Aynı önek yeniden kaydedilirse idempotent (üzerine yazar)."""
        if not isinstance(prefix, str) or not prefix.startswith("/") or prefix in ("/", "/api/", "/ws"):
            raise ValueError(f"invalid route prefix: {prefix!r}")
        if prefix.startswith(("/api/", "/ws", "/v1/", "/q/", "/assets/")):
            raise ValueError(f"route prefix collides with core surface: {prefix!r}")
        ms = tuple(str(m).upper() for m in methods)
        with _LOCK:
            _ROUTES[:] = [r for r in _ROUTES if r["prefix"] != prefix]
            _ROUTES.append({"prefix": prefix, "fn": fn, "methods": ms})

    authz_api_version = 1       # `claudeops.authz.AUTHZ_API_VERSION` (kimlik/yetki kancaları; çekirdekte davranışsız)

    def register_public_route(self, prefix: str, fn: Callable[["RouteRequest"], None], methods: Any = ("GET", "POST")) -> None:
        """Giriş ucu: YALNIZ `/api/auth/` önekine izinli; panel kimliği ARANMADAN çağrılır (kimlik doğrulamanın kendisi)."""
        if prefix != "/api/auth/":
            raise ValueError(f"public route only allowed for /api/auth/: {prefix!r}")
        ms = tuple(str(m).upper() for m in methods)
        with _LOCK:
            _ROUTES[:] = [r for r in _ROUTES if r["prefix"] != prefix]
            _ROUTES.append({"prefix": prefix, "fn": fn, "methods": ms, "public": True})

    def on_session_event(self, fn: Callable[..., None]) -> None:
        """K5: `fn(event, host, name, principal)` (created, closed, retired, adopted, renamed, reactivated; mutasyon başarılıysa)."""
        from . import authz
        authz.add_event_sink(fn)

    def register_doc_prefix(self, prefix: str) -> None:
        """K8: `prefix` ("auth/") altındaki belgeler `db` kipinde DB-tek-kaynak olur."""
        from . import statedocs
        statedocs.register_doc_prefix(prefix)

    def register_ui_extension(self, ext_id: str, assets_dir: str, roles: Any = ("admin",), title: str = "", entry: str = "index.js") -> None:
        """K10: panel sekmesi. `GET /api/ui/extensions` rolüne uyan kullanıcıya listeler; dosyalar `/api/ui/ext/<id>/<dosya>`
        (kimlik + yetki kapısından geçer; traversal/symlink korumalı). `UI_EXTENSION_API = 1`."""
        import os
        if not isinstance(ext_id, str) or not ext_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"invalid ui extension id: {ext_id!r}")
        with _LOCK:
            _UI_EXTS[ext_id] = {"id": ext_id, "title": title or ext_id, "assets_dir": os.path.realpath(assets_dir),
                                "roles": tuple(str(r) for r in roles), "entry": entry}

    def set_authenticator(self, fn: Callable[[Any], Any]) -> None:
        """K1: `fn(RequestView) -> Principal | None` (None = 401). Kayıtlıyken `web.token` yolu KAPANIR (eklenti çözer)."""
        from . import authz
        authz.set_authenticator(fn)

    def set_spawn_hook(self, fn: Callable[..., Dict[str, str]]) -> None:
        """`fn(principal|None, cli, name, cwd) -> {ENV: değer}` oturum başlatılırken; `authz.SpawnRefused` fırlatırsa başlatma reddedilir."""
        from . import authz
        authz.set_spawn_hook(fn)

    def set_authorizer(self, fn: Callable[[Any, str, Any], bool]) -> None:
        """K2: `fn(Principal, action, Resource) -> bool` (istisna/False = 403)."""
        from . import authz
        authz.set_authorizer(fn)

    def set_status_filter(self, fn: Callable[[Any, dict], dict]) -> None:
        """K3: `/api/status` ve `/ws` yayını principal başına süzülür."""
        from . import authz
        authz.set_status_filter(fn)

    def register_audit_sink(self, fn: Callable[[Any, str, Any, int], None]) -> None:
        """K9: her yetki kararından sonra `fn(Principal, action, Resource, status)`."""
        from . import authz
        authz.add_audit_sink(fn)

    def projects(self) -> List[Dict[str, str]]:
        return core_projects()

    def send_directive(self, name: str, text: str) -> Dict[str, Any]:
        return core_send_directive(name, text)

    def settings(self, key: str) -> Any:
        from . import settings as st
        return st.load_settings().get(key)


class RouteRequest:
    """Eklenti yoluna verilen İSTEK yüzeyi (web handler'ın ham iç yapısı eklentiye verilmez)."""

    def __init__(self, handler: Any, method: str, path: str, extra_headers: Optional[Dict[str, str]] = None) -> None:
        self._h = handler
        self.method = method
        self.path = path
        self.query: Dict[str, str] = {k: v[0] for k, v in parse_qs(urlparse(handler.path).query).items()}
        self._extra = dict(extra_headers or {})
        self.sent = False
        self.client_addr = str(handler.client_address[0]) if getattr(handler, "client_address", None) else ""

    def header(self, name: str) -> str:
        return str(self._h.headers.get(name) or "")

    def body(self, limit: int = MAX_BODY) -> bytes:
        try:
            n = int(self.header("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > min(limit, MAX_BODY):
            self._h.close_connection = True
            raise ValueError("body too large or invalid")
        return self._h._read_body(n) if n else b""

    def send(self, status: int, body: bytes, content_type: str = "application/octet-stream",
             headers: Optional[Dict[str, str]] = None, head_only: bool = False) -> None:
        h = self._h
        h.send_response(status)
        h.send_header("Content-Type", content_type)
        h.send_header("Content-Length", str(len(body)))
        h.send_header("X-Content-Type-Options", "nosniff")
        allh = {**self._extra, **(headers or {})}
        for k, v in allh.items():
            h.send_header(k, v)
        # eklenti kendi CSP'sini verdiyse çekirdeğin sabit CSP/XFO'su eklenmez (iki CSP kesişir, gevşetilemez)
        h._ext_own_csp = any(k.lower() == "content-security-policy" for k in allh)
        h.end_headers()
        if not head_only and self.method != "HEAD":
            h.wfile.write(body)
        self.sent = True

    def json(self, obj: Any, status: int = 200) -> None:
        self.send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8",
                  {"Cache-Control": "no-store"})


def cookie_value(token: str) -> str:
    """Oturum çerezi değeri: token'ın HMAC'i (token'ın kendisi çereze girmez)."""
    return hmac.new(token.encode("utf-8"), b"claudeops-ext-session", hashlib.sha256).hexdigest()


def cookie_ok(cookie_header: str, token: str) -> bool:
    if not token or not cookie_header:
        return False
    want = cookie_value(token)
    for part in cookie_header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE_NAME and hmac.compare_digest(v.encode("utf-8", "replace"), want.encode("ascii")):
            return True
    return False


def match_route(method: str, path: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        for r in _ROUTES:
            if path.startswith(r["prefix"]) or path == r["prefix"].rstrip("/"):
                if method.upper() in r["methods"] or (method.upper() == "HEAD" and "GET" in r["methods"]):
                    return r
    return None


def dispatch(route: Dict[str, Any], req: RouteRequest) -> None:
    """Eklenti işleyicisini çalıştırır; hata çekirdeği düşürmez (500, diag)."""
    try:
        route["fn"](req)
    except Exception as e:            # noqa: BLE001
        _log("extension_route_failed", prefix=route["prefix"], error=f"{type(e).__name__}: {e}"[:200])
        if not req.sent:
            try:
                req.json({"ok": False, "error": "extension error"}, status=500)
            except Exception:
                pass


def core_projects() -> List[Dict[str, str]]:
    """Kayıtlı proje adı + yerel klasör (uzak proje: cwd "")."""
    from . import steward as sw
    from .commands import web_steward as ws
    projs = sw.load_projects()
    res = ws._cwd_resolver()
    out: List[Dict[str, str]] = []
    for name, p in sorted(projs.items()):
        try:
            cwd = "" if getattr(p, "host", "") else str(res(name) or "")
        except Exception:
            cwd = ""
        out.append({"name": name, "cwd": cwd})
    return out


def core_send_directive(name: str, text: str) -> Dict[str, Any]:
    """Proje oturumuna direktif (`http_directive` ile AYNI kapılar)."""
    from .commands import web_steward as ws
    return ws.http_directive({"name": name, "text": text, "actor": "extension"})


def ui_extensions(roles: Any = None) -> List[Dict[str, Any]]:
    """K10 listesi (`assets_dir` sızdırılmaz). `roles` None = hepsi (yetki kapısı yok); verilirse kesişen roller."""
    with _LOCK:
        exts = list(_UI_EXTS.values())
    rs = set(roles or ())
    return [{"id": e["id"], "title": e["title"], "roles": list(e["roles"]), "entry": f"/api/ui/ext/{e['id']}/{e['entry']}"}
            for e in exts if roles is None or rs & set(e["roles"])]


def ui_extension_file(ext_id: str, rel: str, roles: Any = None) -> Optional[str]:
    """Dosyanın gerçek yolu ya da None (yok/rol uymuyor/traversal/symlink dışarı)."""
    import os
    with _LOCK:
        e = _UI_EXTS.get(ext_id)
    if e is None or (roles is not None and not (set(roles) & set(e["roles"]))):
        return None
    root = e["assets_dir"]
    real = os.path.realpath(os.path.join(root, rel))
    return real if real.startswith(root + os.sep) and os.path.isfile(real) else None


def routes() -> List[str]:
    with _LOCK:
        return [r["prefix"] for r in _ROUTES]


def _log(event: str, **kw: Any) -> None:
    try:
        from .diaglog import diag_log
        diag_log(event, **kw)
    except Exception:
        pass


def load(force: bool = False) -> Dict[str, Any]:
    """`claudeops_enterprise` import edilebiliyorsa `register(api)` çağırır; yoksa sessizce geçer. Idempotent (`force` yeniden dener).
    Döner: {status: absent|loaded|incompatible|error, detail, lenses}."""
    with _LOCK:
        if _STATE["loaded"] and not force:
            return status()
        _STATE.update(loaded=True, status="absent", detail="")      # lenses KORUNUR: kayıtlı mercek yeniden yüklemede silinmez
        try:
            mod = importlib.import_module(PACKAGE)
        except ModuleNotFoundError as e:
            if e.name != PACKAGE:         # paket VAR ama kendi bağımlılığı eksik: sessiz geçme, söyle
                _STATE.update(status="error", detail=f"{type(e).__name__}: {e}"[:200])
                _log("extension_load_failed", package=PACKAGE, error=_STATE["detail"])
            return status()
        except Exception as e:            # noqa: BLE001
            _STATE.update(status="error", detail=f"{type(e).__name__}: {e}"[:200])
            _log("extension_load_failed", package=PACKAGE, error=_STATE["detail"])
            return status()
        req = getattr(mod, "REQUIRES_CORE_API", EXTENSION_API_VERSION)
        if req != EXTENSION_API_VERSION:
            _STATE.update(status="incompatible", detail=f"requires core api {req}, core has {EXTENSION_API_VERSION}")
            _log("extension_incompatible", package=PACKAGE, detail=_STATE["detail"])
            return status()
        try:
            mod.register(ExtensionAPI())
            _STATE.update(status="loaded", detail=str(getattr(mod, "__version__", "")))
        except Exception as e:            # noqa: BLE001  kısmi kayıt kalabilir; çekirdek çalışır
            _STATE.update(status="error", detail=f"register: {type(e).__name__}: {e}"[:200])
            _log("extension_load_failed", package=PACKAGE, error=_STATE["detail"])
        return status()


def status() -> Dict[str, Any]:
    return {"status": _STATE["status"], "detail": _STATE["detail"], "lenses": list(_STATE["lenses"]), "package": PACKAGE,
            "core_api": EXTENSION_API_VERSION}


def lens_sources() -> List[str]:
    return list(_STATE["lenses"])
