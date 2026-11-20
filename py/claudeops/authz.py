"""Kimlik/yetki KANCALARI (çekirdek, OSS, davranışsız): docs/multi-user-plan.md Bölüm 5 (K1, K2, K3, K9) ve Bölüm 7 A1.

Çekirdek yalnız SÖZLEŞMEYİ tanımlar (`Principal`, `Resource`, eylem adları, kayıt noktaları); doldurma `claudeops_enterprise`'ta,
yalnız `extensions.ExtensionAPI` üzerinden. Hiçbir kanca kayıtlı değilken çekirdek BİR BAYT değişmez: kimlik = bugünkü `web.token`
(`LEGACY` principal, her eyleme yetkili), `customized()` False olduğundan `web.py` hiçbir ek iş yapmaz.

Fail closed: kayıtlı authenticator istisna atarsa istek 401, kayıtlı authorizer istisna atarsa ya da False dönerse 403 (+ diag).
Paket kayıtlıyken eksik eylem adı (`UNMAPPED`) yalnız admin rolüne açılır: authorizer'ın sorumluluğu, ama `action_for` yeni ucu
sessizce "genel" saymaz (test: web.py'deki her uç `ACTIONS`ta adlandırılmış olmalı).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

AUTHZ_API_VERSION = 1       # kanca sözleşmesi; EXTENSION_API_VERSION'dan ayrı (eklenti `api.authz_api_version` ile sorar)
UNMAPPED = "admin.unmapped"


@dataclass(frozen=True)
class Principal:
    uid: str
    roles: Tuple[str, ...] = ()
    kind: str = "human"            # human | agent | legacy
    ticket_id: str = ""

    def has_role(self, role: str) -> bool:
        return role in self.roles


LEGACY = Principal(uid="owner", roles=("admin",), kind="legacy")


@dataclass(frozen=True)
class Resource:
    kind: str = "global"           # session | project | host | global
    host: str = ""
    name: str = ""
    cwd: str = ""
    steward: str = ""              # değnekçi kimliği (`/api/steward/*`, `/q/`: kind steward/project)


@dataclass
class RequestView:
    """Authenticator'a verilen SALT-OKUNUR istek görünümü (handler'ın ham iç yapısı verilmez)."""
    method: str
    path: str
    query: Dict[str, str]
    headers: Mapping[str, str]
    cookies: Dict[str, str]
    client_addr: str = ""
    # Gövdeyi TEMBEL okuyan sağlayıcı (imzalı kimlik iletimi gövde bağlama): çağrılırsa gövde okunur ve handler'a da aynen kalır;
    # sınırı aşan/okunamayan gövde için None. Çağıran yalnız imza doğrulandıktan sonra ister.
    body_fn: Optional[Callable[[], Optional[bytes]]] = None


# Ön ek -> eylem. SIRA ÖNEMLİ (ilk eşleşen kazanır; daha özel önek önce). GET ve POST aynı tablo (yöntem ayrımı eylem adında değil).
_ACTION_TABLE: List[Tuple[str, str]] = [
    ("/api/auth/", "auth.login"),
    ("/api/ws-ticket", "status.read"),
    ("/api/status", "status.read"),
    ("/api/ui/", "status.read"),
    ("/api/usage", "usage.read"),
    ("/api/context", "usage.read"),
    ("/ws/term", "term.read"),
    ("/ws/desktop", "desktop.use"),
    ("/ws", "status.read"),
    ("/api/term/open-window", "admin.desktop"),
    ("/api/term/mirror-window", "admin.desktop"),
    ("/api/term/input", "term.write"),
    ("/api/term/key", "term.write"),
    ("/api/term/raw", "term.write"),
    ("/api/term/resize", "term.write"),
    ("/api/term/set-mode", "term.write"),
    ("/api/term/", "term.read"),
    ("/api/files/upload", "files.write"),
    ("/api/files/write", "files.write"),
    ("/api/files/delete", "files.write"),
    ("/api/files/rename", "files.write"),
    ("/api/files/mkdir", "files.write"),
    ("/api/files/", "files.read"),
    ("/api/orch/", "orch.run"),
    ("/api/ucli/ask", "session.chat"),
    ("/api/_internal/", "admin.config"),            # Rust ön kapı iç uçları: kimlik doğrulamadan ÖNCE gizli+loopback ile korunur (front.py); eşleme yalnız emniyet
    ("/api/chat-backup", "admin.config"),
    ("/api/ucli/checks-mode", "session.control"),   # kaynak = oturum (`name`); ÖNCE: "/api/ucli/checks" öneki bunu da yakalar
    ("/api/ucli/checks", "admin.config"),           # kontrol kaydı bir güvenlik izni (docs/ucli-run-checks-design.md 4.5)
    ("/api/ucli/approvals", "session.chat"),     # GET listesi `action_for`'da status.read (yanıt sahibine göre süzülür)
    ("/api/agents/", "agents.use"),
    ("/api/register", "session.create"),
    ("/api/adopt", "fleet.admin"),
    ("/api/instances/", "fleet.admin"),
    ("/api/snapshot", "fleet.admin"),
    ("/api/start", "session.control"),
    ("/api/stop", "session.control"),
    ("/api/retire", "session.control"),
    ("/api/reactivate", "session.control"),
    ("/api/close", "session.control"),
    ("/api/handover", "session.control"),
    ("/api/compact", "session.control"),
    ("/api/new-chat", "session.control"),
    ("/api/edit", "session.control"),
    ("/api/session/activate", "session.control"),
    ("/api/live-model", "session.control"),
    ("/api/live-effort", "session.control"),
    ("/api/hosts", "admin.hosts"),
    ("/api/steward/", "steward.use"),
    ("/api/layout", "admin.desktop"),
    ("/api/vscode/", "admin.desktop"),
    ("/api/desktop/", "desktop.use"),
    ("/api/audio/", "desktop.use"),
    ("/api/settings", "admin.config"),
    ("/api/cli/", "admin.config"),
    ("/api/diag/", "admin.config"),
    ("/api/io/", "admin.config"),
    ("/api/labels", "admin.config"),
    ("/api/periodic", "admin.config"),
    ("/api/session/facts", "status.read"),
    ("/api/session/graphical", "admin.desktop"),
    ("/api/ucli/", "admin.config"),
    ("/desktop/", "desktop.use"),
    ("/api/session/lock", "admin.config"),
    ("/api/session/unlock", "admin.config"),
    ("/v1/", "session.chat"),
    ("/q/", "steward.answer"),
    ("/", "status.read"),       # panel kabuğu ("/" tam eşleşme ayrı işlenir, aşağıda)
]
ACTIONS = tuple(sorted({a for _, a in _ACTION_TABLE} | {UNMAPPED}))


_EXT_ACTIONS: List[Tuple[str, str]] = []      # K12: eklenti API önekı -> eylem (en uzun önek önce)


def register_action(prefix: str, action: str) -> None:
    """Eklenti API'sinin eylem adı (yalnız `/api/enterprise/` önekli). `action_for` ÖNCE bunu okur; sabit `ACTIONS` değişmez."""
    if not prefix.startswith("/api/enterprise/"):
        raise ValueError(f"extension action prefix must start with /api/enterprise/: {prefix!r}")
    with _LOCK:
        _EXT_ACTIONS[:] = [(p, a) for p, a in _EXT_ACTIONS if p != prefix] + [(prefix, action)]
        _EXT_ACTIONS.sort(key=lambda t: -len(t[0]))


def actions() -> Tuple[str, ...]:
    with _LOCK:
        return tuple(sorted(set(ACTIONS) | {a for _, a in _EXT_ACTIONS}))


def action_for(method: str, path: str) -> str:
    """Yol -> eylem adı. Tablo dışı yol `UNMAPPED` (varsayılan RED yalnız admin). `method` şimdilik ayrım yapmaz (ileriye uyum)."""
    if path == "/":
        return "status.read"
    if path == "/api/ucli/approvals" and method.upper() == "GET":
        return "status.read"
    with _LOCK:
        for prefix, action in _EXT_ACTIONS:
            if path == prefix.rstrip("/") or path.startswith(prefix):
                return action
    for prefix, action in _ACTION_TABLE:
        if prefix != "/" and (path == prefix.rstrip("/") or path.startswith(prefix)):
            return action
    return UNMAPPED


# ── kayıt noktaları ───────────────────────────────────────────────────────────

_LOCK = threading.RLock()
_AUTHENTICATOR: Optional[Callable[[RequestView], Optional[Principal]]] = None
_AUTHORIZER: Optional[Callable[[Principal, str, Resource], bool]] = None
_STATUS_FILTER: Optional[Callable[[Principal, dict], dict]] = None
_AUDIT_SINKS: List[Callable[[Principal, str, Resource, int], None]] = []


def set_authenticator(fn: Optional[Callable[[RequestView], Optional[Principal]]]) -> None:
    global _AUTHENTICATOR
    with _LOCK:
        _AUTHENTICATOR = fn


def set_authorizer(fn: Optional[Callable[[Principal, str, Resource], bool]]) -> None:
    global _AUTHORIZER
    with _LOCK:
        _AUTHORIZER = fn


def set_status_filter(fn: Optional[Callable[[Principal, dict], dict]]) -> None:
    global _STATUS_FILTER
    with _LOCK:
        _STATUS_FILTER = fn


def add_audit_sink(fn: Callable[[Principal, str, Resource, int], None]) -> None:
    with _LOCK:
        if fn not in _AUDIT_SINKS:
            _AUDIT_SINKS.append(fn)


def reset() -> None:
    """Test/yeniden yükleme: tüm kancaları sil (çekirdek varsayılanına dön)."""
    with _LOCK:
        global _AUTHENTICATOR, _AUTHORIZER, _STATUS_FILTER, _SPAWN_HOOK, _OUTBOUND_SIGNER
        _AUTHENTICATOR = _AUTHORIZER = _STATUS_FILTER = _SPAWN_HOOK = _OUTBOUND_SIGNER = None
        _AUDIT_SINKS.clear()
        _STATUS_EXTRAS.clear()
        _EVENT_SINKS.clear()
        _EXT_ACTIONS.clear()


def has_authenticator() -> bool:
    return _AUTHENTICATOR is not None


def has_authorizer() -> bool:
    return _AUTHORIZER is not None


_STATUS_EXTRAS: Dict[str, Callable[[], Any]] = {}


def set_status_extra(key: str, fn: Optional[Callable[[], Any]]) -> None:
    """`/api/status` köküne `key: fn()` ekler (eklenti ilanı, ör. `fwd`). `fn` None döndürürse ya da istisna atarsa anahtar eklenmez."""
    with _LOCK:
        if fn is None:
            _STATUS_EXTRAS.pop(key, None)
        else:
            _STATUS_EXTRAS[key] = fn


def status_extras() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, fn in list(_STATUS_EXTRAS.items()):
        try:
            v = fn()
        except Exception as e:      # noqa: BLE001
            _log("authz_status_extra_failed", key=k, error=f"{type(e).__name__}: {e}"[:200])
            continue
        if v is not None:
            out[k] = v
    return out


def outbound_service_headers(host_name: str, method: str, path: str) -> Dict[str, str]:
    """Panelin KENDİ adına (kullanıcı değil) imza: paylaşılan WS aktarıcıları (durum akışı, terminal relay) için; kimlik = LEGACY
    (yerel panel). Kullanıcı yetkisi yerel kapıda uygulanmıştır. Kanca yoksa {}; `OutboundRefused` aynen yükselir."""
    fn = _OUTBOUND_SIGNER
    if fn is None:
        return {}
    try:
        out = fn(LEGACY, host_name, method, path, None)
    except OutboundRefused:
        raise
    except Exception as e:      # noqa: BLE001
        _log("authz_outbound_signer_failed", error=f"{type(e).__name__}: {e}"[:200], host=host_name)
        return {}
    return {str(k): str(v) for k, v in (out or {}).items()}


def has_outbound_signer() -> bool:
    return _OUTBOUND_SIGNER is not None


def has_status_filter() -> bool:
    return _STATUS_FILTER is not None


def customized() -> bool:
    """Herhangi bir kimlik/yetki kancası kayıtlı mı? False = çekirdek bugünkü davranışı, hiçbir ek iş yapılmaz."""
    return _AUTHENTICATOR is not None or _AUTHORIZER is not None


def _log(event: str, **kw: Any) -> None:
    try:
        from .diaglog import diag_log
        diag_log(event, **kw)
    except Exception:
        pass


# ── karar işlevleri (fail closed) ─────────────────────────────────────────────

def authenticate(view: RequestView) -> Optional[Principal]:
    """Kayıtlı authenticator ile kimlik çöz; istisna ya da geçersiz dönüş = None (401). Kayıtlı değilse çağıran
    bugünkü `web.token` yoluna düşer (bu işlev yalnız `has_authenticator()` iken çağrılır)."""
    fn = _AUTHENTICATOR
    if fn is None:
        return None
    try:
        p = fn(view)
    except Exception as e:      # noqa: BLE001
        _log("authz_authenticator_failed", error=f"{type(e).__name__}: {e}"[:200], path=view.path)
        return None
    return p if isinstance(p, Principal) else None


def _audit(p: Principal, action: str, res: Resource, status: int) -> None:
    for sink in list(_AUDIT_SINKS):
        try:
            sink(p, action, res, status)
        except Exception as e:      # noqa: BLE001  denetim hatası kararı değiştirmez ama görünür olur
            _log("authz_audit_failed", error=f"{type(e).__name__}: {e}"[:200])


def check(p: Optional[Principal], action: str, res: Resource) -> bool:
    """Yetki kararı. Authorizer kayıtlı değilse True (çekirdek varsayılanı); kayıtlıysa ve istisna/False ise False.
    `p` None ve authorizer kayıtlıysa False. Her karar denetim kancalarına düşer (200/403)."""
    fn = _AUTHORIZER
    if fn is None:
        return True
    if p is None:
        return False
    try:
        ok = bool(fn(p, action, res))
    except Exception as e:      # noqa: BLE001
        _log("authz_authorizer_failed", error=f"{type(e).__name__}: {e}"[:200], action=action)
        ok = False
    _audit(p, action, res, 200 if ok else 403)
    return ok


def filter_status(p: Optional[Principal], payload: dict) -> dict:
    """K3: durum yayınını principal'a göre süz. Kanca yoksa AYNI nesne döner. Kanca istisna atarsa BOŞ görünüm (fail closed)."""
    fn = _STATUS_FILTER
    if fn is None:
        return payload
    if p is None:
        return {"sessions": []}
    try:
        out = fn(p, payload)
        return out if isinstance(out, dict) else {"sessions": []}
    except Exception as e:      # noqa: BLE001
        _log("authz_status_filter_failed", error=f"{type(e).__name__}: {e}"[:200])
        return {"sessions": []}


# ── K5: oturum olayları ───────────────────────────────────────────────────────

_EVENT_SINKS: List[Callable[..., None]] = []
# mutasyon ucu -> olay adı (`web.py` `_json_notify` ok:true dönünce yayar)
EVENT_PATHS = {"/api/register": "created", "/api/new-chat": "created", "/api/close": "closed", "/api/stop": "closed",
               "/api/retire": "retired", "/api/adopt": "adopted", "/api/edit": "renamed", "/api/reactivate": "reactivated"}


def add_event_sink(fn: Callable[..., None]) -> None:
    with _LOCK:
        if fn not in _EVENT_SINKS:
            _EVENT_SINKS.append(fn)


def emit_event(path: str, host: str, name: str, p: Optional[Principal]) -> None:
    """K5: kayıtlı alıcılara `fn(event, host, name, principal)`; sahiplik belgesi bunlarla tutulur. Alıcı hatası yutulur (log)."""
    ev = EVENT_PATHS.get(path)
    if not ev or not _EVENT_SINKS:
        return
    for fn in list(_EVENT_SINKS):
        try:
            fn(ev, host, name, p)
        except Exception as e:      # noqa: BLE001
            _log("authz_event_sink_failed", error=f"{type(e).__name__}: {e}"[:200], event=ev)


_CHILD_SINKS: List[Callable[..., None]] = []


def add_child_sink(fn: Callable[..., None]) -> None:
    """Ajan çocuk oturum (ucli alt ajan) açılmadan ÖNCE `fn(host, parent, child)` çağrılır: sahiplik çocuğa taşınır, böylece istek
    dışı iş parçacığındaki spawn kancası (principal yok) çocuğun sahibini bulur."""
    with _LOCK:
        if fn not in _CHILD_SINKS:
            _CHILD_SINKS.append(fn)


def emit_child(host: str, parent: str, child: str) -> None:
    for fn in list(_CHILD_SINKS):
        try:
            fn(host, parent, child)
        except Exception as e:      # noqa: BLE001
            _log("authz_child_sink_failed", error=f"{type(e).__name__}: {e}"[:200])


def resources_from(path: str, qs: Mapping[str, Any], data: Optional[dict]) -> List[Resource]:
    """İsteğin dokunduğu TÜM kaynaklar: `name`/`host` (sorgu+gövde), `/v1/*` `model` (= oturum adı), `participants[]`
    (`/api/orch/*`: {host,name}), `names[]`. Hiçbiri yoksa tek `global`. Authorizer hepsi için True demeli (biri red = 403)."""
    def _q(k: str) -> str:
        v = qs.get(k) or [""]
        return str(v[0] if isinstance(v, (list, tuple)) else v)
    src = data or {}
    if path.startswith("/api/steward/"):         # `name` burada PROJE adıdır, oturum değil: kaynak değnekçi kimliği
        sid = src.get("steward") or _q("steward") or "default"
        return [Resource(kind="steward", steward=str(sid).strip() or "default")]
    if path == "/api/ucli/approvals":            # kaynak = koşunun oturumu (kayıttan); oturumsuz/bilinmeyen koşu = global (yalnız admin)
        from . import ucli_approval
        rec = ucli_approval.get(str(src.get("run_key") or _q("run_key"))) or {}
        sess = str(rec.get("session") or "")
        return [Resource(kind="session", host="", name=sess)] if sess else [Resource(kind="global", host="")]
    host = str(src.get("host") or _q("host") or "")
    out: List[Resource] = []
    seen = set()

    def add(h: str, n: str) -> None:
        n = str(n or "").strip()
        if n and (h, n) not in seen:
            seen.add((h, n))
            out.append(Resource(kind="session", host=h, name=n))
    add(host, src.get("name") or _q("name"))
    if path.startswith("/v1/"):
        add("", src.get("model"))
    parts = src.get("participants")
    if isinstance(parts, list):
        for it in parts:
            if isinstance(it, dict):
                add(str(it.get("host") or ""), it.get("name"))
    names = src.get("names")
    if isinstance(names, list):
        for n in names:
            add(host, n)
    qv = qs.get("names") or []         # GET: `?names=a,b` (virgüllü; birden çok `names=` değeri de olabilir): her ad AYRI kaynak
    for chunk in (qv if isinstance(qv, (list, tuple)) else [qv]):
        for n in str(chunk).split(","):
            add(host, n)
    return out or [Resource(kind="global", host=host)]


# ── spawn kancası (A2: kullanıcı başına sağlayıcı yapılandırma dizini + kimliksiz başlatmayı reddet) ──────────

class SpawnRefused(ValueError):
    """Oturum başlatılamaz (ör. kullanıcının o sağlayıcıda kendi girişi yok). `reason` kısa makine kodu."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


_TL = threading.local()
_SPAWN_HOOK: Optional[Callable[[Optional[Principal], str, str, str], Dict[str, str]]] = None


def bind_principal(p: Optional[Principal]) -> None:
    """İstek iş parçacığına kimliği bağla (`web.py` `_principal`); istek bitince `bind_principal(None)`. Değnekçi/guard gibi istek dışı
    iş parçacıklarında kimlik YOKTUR (spawn kancası oturum adından sahibi çözer)."""
    _TL.p = p


def current_principal() -> Optional[Principal]:
    return getattr(_TL, "p", None)


def set_spawn_hook(fn: Optional[Callable[[Optional[Principal], str, str, str], Dict[str, str]]]) -> None:
    global _SPAWN_HOOK
    with _LOCK:
        _SPAWN_HOOK = fn


class OutboundRefused(Exception):
    """Giden uzak-host isteği imzalanamaz ve politika bunu yasaklıyor (`fwd_policy=strict`). `reason` kısa makine kodu."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# Giden imza kancası (imzalı kimlik iletimi, enterprise docs/SIGNED-IDENTITY-FORWARDING.md): fn(principal, host_name, method,
# path, body) -> {başlık: değer}. `body` None = akış/gövdesiz. Kanca yoksa {} (davranış aynı).
_OUTBOUND_SIGNER: Optional[Callable[[Principal, str, str, str, Optional[bytes]], Dict[str, str]]] = None


def set_outbound_signer(fn: Optional[Callable[[Principal, str, str, str, Optional[bytes]], Dict[str, str]]]) -> None:
    global _OUTBOUND_SIGNER
    with _LOCK:
        _OUTBOUND_SIGNER = fn


def outbound_headers(host_name: str, method: str, path: str, body: Optional[bytes]) -> Dict[str, str]:
    """Uzak host'a giden istek için ek (imza) başlıkları. Kanca yoksa ya da bu iş parçacığında kimlik bağlı değilse
    (durum yoklaması, değnekçi) {}. `OutboundRefused` aynen yükselir; başka istisna günlüğe düşer ve {} döner (imzasız gönderim
    kararı enterprise politikasındadır: strict ise kanca kendisi OutboundRefused atar). Her çağrı yeni imza üretir (nonce):
    yeniden denemede de yeniden çağrılmalı."""
    fn = _OUTBOUND_SIGNER
    p = current_principal()
    if fn is None or p is None:
        return {}
    try:
        out = fn(p, host_name, method, path, body)
    except OutboundRefused:
        raise
    except Exception as e:      # noqa: BLE001
        _log("authz_outbound_signer_failed", error=f"{type(e).__name__}: {e}"[:200], host=host_name)
        return {}
    return {str(k): str(v) for k, v in (out or {}).items()}


def spawn_env(cli: str, name: str, cwd: str) -> Dict[str, str]:
    """`spawn_session` çağırır: kanca yoksa {} (davranış aynı). Kanca `fn(principal|None, cli, name, cwd) -> {ENV: değer}`;
    `SpawnRefused` aynen yükselir, başka istisna = FAIL CLOSED (SpawnRefused hook_error)."""
    fn = _SPAWN_HOOK
    if fn is None:
        return {}
    try:
        out = fn(current_principal(), cli, name, cwd)
    except SpawnRefused:
        raise
    except Exception as e:      # noqa: BLE001
        _log("authz_spawn_hook_failed", error=f"{type(e).__name__}: {e}"[:200], cli=cli)
        raise SpawnRefused("hook_error") from e
    return {str(k): str(v) for k, v in (out or {}).items()}
