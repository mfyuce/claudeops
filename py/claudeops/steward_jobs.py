"""Değnekçi tarafı: paylaşımlı servislerin (varaka) pasif kaydı ve dış iş kuyruğu İSTEMCİSİ (çoklu değnekçi P8b).

Sözleşme varaka'nın KENDİ planıdır (`varaka/PLAN_is_kuyrugu_api.md` §5-§10, §14, §16-17); `docs/multi-steward-plan.md` (f)
taslağının ÜSTÜNDE: kimlik başlığı YOK (auth = mevcut JWT/Bearer ya da iç servis anahtarı, burada Bearer token DOSYASI), iş
sahibi (`owner`) varaka'da doğrulanmış kullanıcıdır (gövdeden alınmaz), değnekçi onay VERMEZ (`/approve` yalnız insan admin),
varaka kimseye mesaj/push göndermez: değnekçi POLL eder. Başkasının işi 404.

Bu modül `web.py`/`web_steward.py`'yi import ETMEZ (CLI de kullanır). İçerik:

- `services.json` (makine geneli, `STEWARD_DIR` altında): `{ad: {url, auth: {kind: bearer, token_file}, match, label,
  watch: true, passive: true, added_at}}`. TOKEN kayda/loga/argv'ye GİRMEZ: yalnız dosya yolu saklanır, her istekte okunur.
- `jobs.json` (kimlik başına, `StewardPaths.jobs`; `transfer_project` `project` alanıyla taşır): bu kimliğin varaka'ya
  gönderdiği işlerin yerel kaydı (varaka'daki iş kopyası değil, özeti).
- HTTP istemcisi (`urllib`, yönlendirme/proxy YOK: Authorization başka host'a sızmasın), çok parçalı (multipart) akışlı yükleme.
- SAF kararlar: `pending_stage`, `plan_job_deliveries` (iletim eylemi `deliver_job`), `apply_remote`, `build_job_message`.
"""
from __future__ import annotations
import hashlib
import json
import mimetypes
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import steward as sw

OPEN_STATES = ("awaiting_approval", "queued", "running")
TERMINAL_STATES = ("done", "failed", "cancelled", "lost")   # `lost`: varaka işi 404 verdi (silinmiş/yetkisiz)

JOB_POLL_SECONDS = 45          # açık iş başına en sık yoklama (varaka önerisi 30-60 sn)
POLL_MAX_PER_RUN = 20          # bir poll turunda en çok bu kadar iş yoklanır (iş parçacığı süresi sınırlı kalsın)
HTTP_TIMEOUT = 5.0             # poll/GET zaman aşımı (kısa; hata yutulur, loglanır)
SUBMIT_TIMEOUT = 120.0         # gönderim (dosya yükleme) zaman aşımı
SUMMARY_CHARS = 2000           # result_summary üst sınırı (varaka sözleşmesi ≤2000)
ERROR_CHARS = 400
MAX_FILES = 50                 # varaka varsayılanı (JOBS_MAX_FILES)
BACKOFF_BASE = 30.0            # servis erişilemezse: 30, 60, 120 … en çok 600 sn
BACKOFF_MAX = 600.0
DELIVER_MAX_ATTEMPTS = 5       # iletim gönderimi bu kadar başarısız olursa bırakılır (kayıt jobs.json'da kalır)
DEFAULT_SERVICE = "varaka"


class ServiceError(Exception):
    """Servis çağrısı başarısız. `kind`: `unreachable` (ağ/zaman aşımı) | `unavailable` (5xx) | `auth` (401/403) |
    `config` (kayıt/token dosyası) | `bad_response`. Mesaj token İÇERMEZ."""
    def __init__(self, kind: str, message: str, status: int = 0):
        super().__init__(message)
        self.kind = kind
        self.status = status


# ── servis kaydı (services.json) ──────────────────────────────────────────────

def load_services() -> Dict[str, Dict[str, Any]]:
    raw = sw._load_json(sw.services_path(), {})
    if not isinstance(raw, dict):
        return {}
    return {str(n): dict(r) for n, r in raw.items() if sw.valid_name(str(n)) and isinstance(r, dict)}


def token_file_path(svc: Dict[str, Any]) -> str:
    auth = svc.get("auth") if isinstance(svc.get("auth"), dict) else {}
    return os.path.expanduser(str(auth.get("token_file") or ""))


def token_file_warning(path: str) -> str:
    """Token dosyası grup/diğer okunabilirse uyarı metni, sorun yoksa ""."""
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        return ""
    if mode & 0o077:
        return f"token dosyası {oct(mode)} izinli (başkaları okuyabilir): chmod 600 {path}"
    return ""


def validate_url(url: str) -> str:
    """Kök adres (yol öneki olabilir): http/https, host var, kullanıcı bilgisi/sorgu/parça YOK. Düzeltilmiş adres ya
    da `ValueError`."""
    u = urllib.parse.urlsplit((url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("url http:// ya da https:// ile başlamalı ve host içermeli")
    if u.username or u.password or u.query or u.fragment:
        raise ValueError("url kullanıcı bilgisi/sorgu/parça içeremez (token DOSYASI kullanın)")
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path.rstrip("/"), "", ""))


def add_service(name: str, url: str, token_file: str, match: str = "prefix", label: str = "") -> Dict[str, Any]:
    """Pasif servis kaydı ekle (YALNIZ insan; beyin aracı yok). Ad rezerve/proje çakışması reddedilir. Sahiplik kilidi
    altında. `ValueError` ya da `sw.LockTimeout`."""
    name = (name or "").strip()
    if not sw.valid_name(name):
        raise ValueError(f"geçersiz servis adı {name!r} (küçük harf/rakam/_, harfle başlar)")
    if match not in ("prefix", "exact"):
        raise ValueError("match 'prefix' ya da 'exact' olmalı")
    url = validate_url(url)
    tf = os.path.abspath(os.path.expanduser(token_file or ""))
    if not token_file or not os.path.isfile(tf):
        raise ValueError(f"token dosyası bulunamadı: {token_file!r}")
    rec = {"url": url, "auth": {"kind": "bearer", "token_file": tf}, "match": match, "label": label or name,
           "watch": True, "passive": True, "added_at": time.time()}
    with sw.ownership_lock():
        svcs = load_services()
        if name in svcs:
            raise ValueError(f"servis {name!r} zaten kayıtlı (önce: steward service rm {name})")
        idx = sw.ownership_index(fresh=True)
        reason = sw.reserved_reason(name, idx)
        if reason:
            raise ValueError(f"ad {name!r} rezerve ({reason})")
        clash = sorted(p for p in idx.get("owners", {}) if p == name or (match != "exact" and p.startswith(name)))
        clash += sorted(p for p in idx.get("conflicts", {}) if p == name or (match != "exact" and p.startswith(name)))
        if clash:
            raise ValueError(f"ad {name!r} mevcut projeyle çakışır: {', '.join(clash[:5])}")
        svcs[name] = rec
        sw._save_json(sw.services_path(), svcs)
    return rec


def remove_service(name: str) -> bool:
    with sw.ownership_lock():
        svcs = load_services()
        if name not in svcs:
            return False
        del svcs[name]
        sw._save_json(sw.services_path(), svcs)
    return True


def default_service() -> str:
    """`varaka` kayıtlıysa o, değilse tek kayıtlı servis, yoksa ""."""
    svcs = load_services()
    if DEFAULT_SERVICE in svcs:
        return DEFAULT_SERVICE
    return next(iter(svcs)) if len(svcs) == 1 else ""


# ── HTTP istemcisi ─────────────────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):   # Authorization başka adrese taşınmasın
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def read_token(svc: Dict[str, Any]) -> str:
    path = token_file_path(svc)
    if not path:
        raise ServiceError("config", "servis kaydında token_file yok")
    try:
        with open(path, encoding="utf-8") as f:
            tok = f.read().strip()
    except OSError as e:
        raise ServiceError("config", f"token dosyası okunamadı ({type(e).__name__})") from None
    if not tok or "\n" in tok or "\r" in tok:
        raise ServiceError("config", "token dosyası boş ya da çok satırlı")
    return tok


class MultipartBody:
    """Akışlı `multipart/form-data` gövdesi (dosya belleğe alınmaz). `http.client` `read(n)` ile okur;
    `length` önceden hesaplanır (Content-Length). Parçalar: ("meta", None, "application/json", bytes) /
    ("file", ad, tür, yol)."""

    def __init__(self, parts: List[Tuple[str, Optional[str], str, Any]]):
        self.boundary = "cops" + secrets.token_hex(16)
        self._segs: List[Any] = []
        self.length = 0
        for field, filename, ctype, payload in parts:
            disp = f'form-data; name="{field}"'
            if filename is not None:
                disp += f'; filename="{_safe_filename(filename)}"'
            head = (f"--{self.boundary}\r\nContent-Disposition: {disp}\r\nContent-Type: {ctype}\r\n\r\n").encode("utf-8")
            self._segs.append(head)
            self.length += len(head)
            if isinstance(payload, bytes):
                self._segs.append(payload)
                self.length += len(payload)
            else:
                self._segs.append(str(payload))
                self.length += os.path.getsize(payload)
            self._segs.append(b"\r\n")
            self.length += 2
        tail = f"--{self.boundary}--\r\n".encode("ascii")
        self._segs.append(tail)
        self.length += len(tail)
        self._i = 0
        self._fh = None

    @property
    def content_type(self) -> str:
        return f"multipart/form-data; boundary={self.boundary}"

    def read(self, n: int = -1) -> bytes:
        out = b""
        want = n if n and n > 0 else 1 << 20
        while len(out) < want and self._i < len(self._segs):
            seg = self._segs[self._i]
            if isinstance(seg, bytes):
                take = seg[:want - len(out)]
                out += take
                rest = seg[len(take):]
                if rest:
                    self._segs[self._i] = rest
                else:
                    self._i += 1
            else:
                if self._fh is None:
                    self._fh = open(seg, "rb")
                chunk = self._fh.read(want - len(out))
                if chunk:
                    out += chunk
                else:
                    self._fh.close()
                    self._fh = None
                    self._i += 1
        return out

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def _safe_filename(name: str) -> str:
    base = os.path.basename(name or "file")
    base = re.sub(r'[\x00-\x1f\x7f"\\]', "_", base)
    return base[:255] or "file"


def _parse_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def request_json(svc: Dict[str, Any], method: str, path: str, *, body: Any = None,
                 stream: Optional[MultipartBody] = None, timeout: float = HTTP_TIMEOUT) -> Tuple[int, Any]:
    """Servise tek istek. 2xx/4xx → `(durum, gövde)` (gövde JSON; değilse {}); ağ/zaman aşımı/5xx/401/403 →
    `ServiceError` (`kind`). Authorization her istekte token DOSYASINDAN okunur; yönlendirme izlenmez."""
    base = str(svc.get("url") or "")
    if not base:
        raise ServiceError("config", "servis kaydında url yok")
    headers = {"Authorization": "Bearer " + read_token(svc), "Accept": "application/json"}
    data: Any = None
    if stream is not None:
        headers["Content-Type"] = stream.content_type
        headers["Content-Length"] = str(stream.length)
        data = stream
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status, _parse_json(resp.read(4 * 1024 * 1024))
    except urllib.error.HTTPError as e:
        raw = e.read(64 * 1024) if e.fp else b""
        e.close()
        if e.code in (401, 403):
            raise ServiceError("auth", f"HTTP {e.code} (kimlik/yetki)", e.code) from None
        if e.code >= 500:
            raise ServiceError("unavailable", f"HTTP {e.code}", e.code) from None
        if 300 <= e.code < 400:
            raise ServiceError("bad_response", f"HTTP {e.code} yönlendirme (izlenmez)", e.code) from None
        return e.code, _parse_json(raw)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise ServiceError("unreachable", f"erişilemiyor ({type(reason).__name__})") from None
    finally:
        if stream is not None:
            stream.close()


# ── iş kaydı (jobs.json) ───────────────────────────────────────────────────────

def load_jobs(paths: Any = None) -> List[Dict[str, Any]]:
    raw = sw._load_json(sw._pp(paths).jobs, [])
    return [j for j in raw if isinstance(j, dict)] if isinstance(raw, list) else []


def _save_jobs(jobs: List[Dict[str, Any]], paths: Any = None) -> None:
    sw._save_json(sw._pp(paths).jobs, jobs)


def find_job(jobs: Iterable[Dict[str, Any]], job_id: Any, service: str = "") -> Optional[Dict[str, Any]]:
    for j in jobs:
        if str(j.get("id")) == str(job_id) and (not service or j.get("service") == service):
            return j
    return None


def is_open(job: Dict[str, Any]) -> bool:
    """Açık = bilinen açık durum YA DA bilinmeyen (boş olmayan) durum: varaka ileride yeni bir ara durum (`paused`,
    `retrying`) dönerse iş yoklanmaya devam eder (donup kalmaz). Yalnız `TERMINAL_STATES` ve durumsuz kayıt kapalıdır."""
    st = job.get("state")
    return st in OPEN_STATES or (isinstance(st, str) and bool(st) and st not in TERMINAL_STATES)


def is_known_state(state: Any) -> bool:
    return state in OPEN_STATES or state in TERMINAL_STATES


def make_idempotency_key(sid: str, project: str, kind: str, params: Any, spec_text: str,
                         file_shas: Iterable[str]) -> str:
    """Kimlik + proje + özellik (tür, parametre, spec, dosya sha256'ları) özeti: aynı istek aynı anahtar (varaka aynı işi
    döner), farklı istek farklı anahtar (varaka `idempotency_conflict` vermez)."""
    canon = json.dumps({"sid": sid, "project": project, "kind": kind, "params": params, "spec": spec_text or "",
                        "files": sorted(file_shas)}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"cops:{sid}:{project}:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:32]


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def new_record(service: str, remote_id: Any, project: str, kind: str, state: str, idem_key: str,
               now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    return {"id": remote_id, "service": service, "project": project, "requester": project, "kind": kind,
            "state": state, "created_at": now, "last_polled": 0.0, "delivered": False,
            "idempotency_key": idem_key, "result_summary": "", "notified": [], "attempts": 0}


def save_record(rec: Dict[str, Any], paths: Any = None) -> Dict[str, Any]:
    """(servis, id) ile ekle ya da var olanı koru (aynı iş ikinci kez gönderilirse kayıt çoğalmaz). Dönen: saklanan kayıt."""
    with sw.steward_lock(paths):
        jobs = load_jobs(paths)
        cur = find_job(jobs, rec["id"], rec["service"])
        if cur is not None:
            return cur
        jobs.append(rec)
        _save_jobs(jobs, paths)
    return rec


def update_records(updates: Dict[Tuple[str, str], Dict[str, Any]], paths: Any = None) -> int:
    """{(servis, str(id)): alan güncellemesi}. Kilit altında yeniden okur; kayıt artık yoksa (devredildi) atlanır."""
    n = 0
    with sw.steward_lock(paths):
        jobs = load_jobs(paths)
        for j in jobs:
            u = updates.get((str(j.get("service")), str(j.get("id"))))
            if u:
                j.update(u)
                n += 1
        if n:
            _save_jobs(jobs, paths)
    return n


def job_view(j: Dict[str, Any]) -> Dict[str, Any]:
    """Beyin/CLI'ya gösterilen kayıt (iç alanlar atlanır)."""
    keys = ("id", "service", "project", "kind", "state", "created_at", "last_polled", "delivered", "idempotency_key",
            "result_summary", "approval_state", "error_code", "error", "artifacts", "position", "wait_reason")
    out = {k: j[k] for k in keys if k in j and j[k] not in (None, "", [])}
    out["open"] = is_open(j)
    if j.get("state") == "awaiting_approval":
        out["note"] = "waiting for a HUMAN admin to approve in varaka; do not try to approve it, tell the owner"
    return out


# ── SAF: uzak yanıt → kayıt güncellemesi ───────────────────────────────────────

def _approval_state(remote: Dict[str, Any]) -> str:
    a = remote.get("approval")
    if isinstance(a, dict):
        a = a.get("state") or a.get("approval_state")
    return str(remote.get("approval_state") or a or "")


def apply_remote(rec: Dict[str, Any], remote: Dict[str, Any], now: float) -> Dict[str, Any]:
    """`GET /api/jobs/{id}` gövdesinden kaydın GÜNCELLENECEK alanları. SAF. Gövde hiç bilinmeyen alan içerse yok sayılır;
    `state` yoksa yalnız `last_polled` ilerler."""
    upd: Dict[str, Any] = {"last_polled": now}
    state = str(remote.get("state") or "")
    if state:
        upd["state"] = state
    res = remote.get("result")
    summary = ""
    if isinstance(res, dict):
        summary = str(res.get("summary") or "")
        if not summary and res:
            summary = json.dumps(res, ensure_ascii=False)[:500]
    elif res:
        summary = str(res)
    if summary:
        upd["result_summary"] = summary[:SUMMARY_CHARS]
    if remote.get("error_code"):
        upd["error_code"] = str(remote["error_code"])[:48]
    if remote.get("error"):
        upd["error"] = str(remote["error"])[:ERROR_CHARS]
    ap = _approval_state(remote)
    if ap:
        upd["approval_state"] = ap
    arts = remote.get("artifacts")
    if isinstance(arts, list):
        names = [str(a.get("name") if isinstance(a, dict) else a) for a in arts][:10]
        if names:
            upd["artifacts"] = names
    if remote.get("position") is not None:
        upd["position"] = remote.get("position")
    if remote.get("wait_reason"):
        upd["wait_reason"] = str(remote["wait_reason"])[:80]
    if state and state != rec.get("state"):
        upd["updated_at"] = now
    return upd


def requester_mismatch(rec: Dict[str, Any], remote: Dict[str, Any]) -> bool:
    """Varaka yanıtı farklı bir `requester` taşıyorsa (varaka hatasına karşı savunma) iş bu kayda ait SAYILMAZ."""
    r = remote.get("requester")
    return isinstance(r, str) and bool(r) and r != rec.get("requester")


# ── SAF: iletim kararı ─────────────────────────────────────────────────────────

def pending_stage(job: Dict[str, Any]) -> str:
    """İletilecek aşama: "result" (bitmiş/başarısız/iptal, iletilmemiş), "approval" (onay bekliyor, bu bildirim
    iletilmemiş), yoksa "". Onay beklerken iletilen bildirim sonucu İLETİLDİ saymaz."""
    if job.get("delivered"):
        return ""
    if int(job.get("attempts") or 0) >= DELIVER_MAX_ATTEMPTS:
        return ""
    st = job.get("state")
    if st in TERMINAL_STATES:
        return "result"
    if st == "awaiting_approval" and "awaiting_approval" not in (job.get("notified") or []):
        return "approval"
    return ""


def plan_job_deliveries(views: List[Any], projects: Dict[str, Any], jobs: List[Dict[str, Any]],
                        planned: List[sw.Action], state: Dict[str, Any], now: float,
                        world: Optional[sw.World] = None, limit: int = 3) -> Tuple[List[sw.Action], Dict[str, Any]]:
    """Bitmiş/onay bekleyen işlerin sonucunu İLGİLİ PROJENİN çalışan, boşta oturumuna iletecek `deliver_job` eylemleri.
    `deliver_answer` ile AYNI kural: oturum meşgulse sonraki tick; çalışmıyorsa BEKLER (yalnız sonuç için oturum
    AÇILMAZ). Yalnız bu kimliğin projeleri (`world` varsa sahiplik süzgeci); servis/başka kimlik/beyin oturumuna asla.
    `planned`: aynı tick'te `plan_tick`in zaten dokunduğu oturumlar atlanır. SAF."""
    if not jobs:
        return [], state
    if world is not None:
        projects = world.own_projects(projects)
    mine = [v for v in views if sw._is_project_session(v, projects)
            and (world is None or world.session_class(v.name, v.blueprint) == "own")]
    taken = {a.name for a in planned}
    out: List[sw.Action] = []
    lda: Optional[Dict[str, float]] = None
    for j in sorted(jobs, key=lambda x: float(x.get("created_at") or 0)):
        stage = pending_stage(j)
        proj = str(j.get("project") or "")
        if not stage or proj not in projects:
            continue
        v = sw.pick_delivery_view(mine, proj, "")
        if v is None or v.busy or v.name in taken:
            continue
        out.append(sw.Action("deliver_job", v.name, "job", {"job_id": j.get("id"), "service": j.get("service"), "stage": stage}))
        taken.add(v.name)
        if lda is None:
            lda = dict(state.get("last_directive_at") or {})
        lda[v.name] = now
        if len(out) >= limit:
            break
    if lda is None:
        return [], state
    st = dict(state)
    st["last_directive_at"] = lda
    return out, st


def build_job_message(job: Dict[str, Any], stage: str, lang: str = "tr") -> str:
    """Proje oturumuna gidecek iş bildirimi (kısa; ayrıntı varaka'da). `extra` olarak direktif şablonuna gömülür."""
    tr = lang != "en"
    jid, kind, state = job.get("id"), job.get("kind") or "?", job.get("state") or ""
    svc = job.get("service") or DEFAULT_SERVICE
    lines: List[str] = []
    if stage == "approval":
        lines.append(f"[{svc} iş kuyruğu] İş #{jid} ({kind}) ONAY BEKLİYOR." if tr else
                     f"[{svc} job queue] Job #{jid} ({kind}) is AWAITING APPROVAL.")
        lines.append("Yalnız insan yönetici varaka'da onaylayabilir; sen onaylama/onay çağrısı yapma, sahibine haber verildi. "
                     "Onaylanınca iş kendiliğinden başlar; sonucunu ayrıca ileteceğim." if tr else
                     "Only a human admin can approve it in varaka; do not try to approve it, the owner has been told. "
                     "It starts on its own once approved; I will report the result separately.")
        return "\n".join(lines)
    label = {"done": "BİTTİ", "failed": "BAŞARISIZ", "cancelled": "İPTAL EDİLDİ", "lost": "KAYIP (varaka 404)"} if tr else \
            {"done": "DONE", "failed": "FAILED", "cancelled": "CANCELLED", "lost": "LOST (varaka 404)"}
    lines.append(f"[{svc} iş kuyruğu] İş #{jid} ({kind}): {label.get(state, state)}." if tr else
                 f"[{svc} job queue] Job #{jid} ({kind}): {label.get(state, state)}.")
    if job.get("result_summary"):
        lines.append(("Özet: " if tr else "Summary: ") + str(job["result_summary"])[:SUMMARY_CHARS])
    if job.get("error_code") or job.get("error"):
        lines.append(("Hata: " if tr else "Error: ") + " ".join(x for x in (str(job.get("error_code") or ""), str(job.get("error") or "")) if x))
    if job.get("artifacts"):
        lines.append(("Çıktılar: " if tr else "Artifacts: ") + ", ".join(job["artifacts"][:10])
                     + (f"  (GET /api/jobs/{jid}/artifacts/<ad>)" if tr else f"  (GET /api/jobs/{jid}/artifacts/<name>)"))
    return "\n".join(lines)


def mark_delivered(job_id: Any, service: str, stage: str, now: Optional[float] = None, paths: Any = None) -> bool:
    """İletim BAŞARILI: `result` → `delivered`, `approval` → `notified` listesine eklenir."""
    now = time.time() if now is None else now
    with sw.steward_lock(paths):
        jobs = load_jobs(paths)
        j = find_job(jobs, job_id, service)
        if j is None:
            return False
        if stage == "approval":
            j["notified"] = sorted(set(j.get("notified") or []) | {"awaiting_approval"})
        else:
            j["delivered"] = True
            j["delivered_at"] = now
        j["attempts"] = 0
        _save_jobs(jobs, paths)
    return True


def mark_attempt(job_id: Any, service: str, paths: Any = None) -> int:
    """Başarısız iletim denemesi sayacı (üst sınırda `pending_stage` "" döner). Dönen: yeni sayaç."""
    with sw.steward_lock(paths):
        jobs = load_jobs(paths)
        j = find_job(jobs, job_id, service)
        if j is None:
            return 0
        j["attempts"] = int(j.get("attempts") or 0) + 1
        _save_jobs(jobs, paths)
        return j["attempts"]


# ── poll ───────────────────────────────────────────────────────────────────────

# Servis başına geri çekilme (süreç içi): {(kimlik, servis): {"fails", "next", "logged"}}. Erişilemezlik TEK olay olarak
# loglanır (kesinti başına bir `service_unreachable`, toparlanınca bir `service_recovered`).
_BACKOFF: Dict[Tuple[str, str], Dict[str, Any]] = {}


def reset_backoff() -> None:
    _BACKOFF.clear()


def due_jobs(jobs: List[Dict[str, Any]], now: float, interval: float = JOB_POLL_SECONDS, force: bool = False
             ) -> List[Dict[str, Any]]:
    return [j for j in jobs if is_open(j) and (force or now - float(j.get("last_polled") or 0) >= interval)]


def poll_jobs(sid: str = "default", now: Optional[float] = None, force: bool = False,
              fetch=None) -> Dict[str, Any]:
    """Açık işleri `GET /api/jobs/{id}` ile yokla, kayıtları güncelle. Hata YUTULUR ve loglanır (kimse etkilenmez).
    `fetch(svc, path) -> (status, body)` testler/özel taşıyıcı için; varsayılan `request_json`. Dönen:
    `{polled, changed, errors, skipped}`. Servis kayıtlı değilse o servisin işleri atlanır (kayıt dokunulmaz)."""
    now = time.time() if now is None else now
    fetch = fetch or (lambda svc, path: request_json(svc, "GET", path, timeout=HTTP_TIMEOUT))
    paths = sw.paths_for(sid)
    jobs = load_jobs(paths)
    todo = due_jobs(jobs, now, force=force)[:POLL_MAX_PER_RUN]
    res = {"polled": 0, "changed": 0, "errors": 0, "skipped": 0}
    if not todo:
        return res
    svcs = load_services()
    updates: Dict[Tuple[str, str], Dict[str, Any]] = {}
    down: Dict[str, bool] = {}
    for j in todo:
        name = str(j.get("service") or "")
        svc = svcs.get(name)
        key = (sid, name)
        if svc is None or down.get(name):
            res["skipped"] += 1
            continue
        bo = _BACKOFF.get(key)
        if bo and now < bo["next"] and not force:
            res["skipped"] += 1
            continue
        try:
            status, body = fetch(svc, f"/api/jobs/{urllib.parse.quote(str(j.get('id')), safe='')}")
        except ServiceError as e:
            res["errors"] += 1
            down[name] = True
            fails = (bo or {}).get("fails", 0) + 1
            logged = bool((bo or {}).get("logged"))
            _BACKOFF[key] = {"fails": fails, "next": now + min(BACKOFF_MAX, BACKOFF_BASE * 2 ** (fails - 1)), "logged": True}
            if not logged:
                sw.log_event("service_unreachable", paths=paths, service=name, kind=e.kind, detail=str(e)[:160])
            continue
        except Exception as e:      # beklenmeyen: poll thread'i ölmesin
            res["errors"] += 1
            down[name] = True
            sw.log_event("service_poll_error", paths=paths, service=name, error=type(e).__name__)
            continue
        if _BACKOFF.pop(key, None) and (bo or {}).get("logged"):
            sw.log_event("service_recovered", paths=paths, service=name)
        res["polled"] += 1
        k = (name, str(j.get("id")))
        if status == 404:
            updates[k] = {"state": "lost", "last_polled": now, "updated_at": now, "error_code": "not_found"}
            res["changed"] += 1
            continue
        if status != 200 or not isinstance(body, dict):
            updates[k] = {"last_polled": now}
            res["errors"] += 1
            continue
        if requester_mismatch(j, body):
            sw.log_event("job_requester_mismatch", paths=paths, service=name, id=j.get("id"))
            updates[k] = {"last_polled": now}
            res["errors"] += 1
            continue
        upd = apply_remote(j, body, now)
        if upd.get("state", j.get("state")) != j.get("state"):
            res["changed"] += 1
            if not is_known_state(upd.get("state")):     # kayıt artık bu durumda: sonraki yoklamalar aynı durumu görüp bir daha loglamaz
                sw.log_event("job_unknown_state", paths=paths, service=name, id=j.get("id"), project=j.get("project"),
                             state=str(upd.get("state"))[:40])
            sw.log_event("job_state", paths=paths, service=name, id=j.get("id"), project=j.get("project"),
                         frm=j.get("state"), to=upd.get("state"))
        updates[k] = upd
    update_records(updates, paths)
    return res


# ── gönderim ───────────────────────────────────────────────────────────────────

def submit_job(sid: str, project: str, kind: str, params: Dict[str, Any], spec_text: str, files: List[str],
               service: str = "", priority: Optional[int] = None, approval_ref: str = "", host: str = "",
               post=None) -> Dict[str, Any]:
    """İşi varaka'ya gönder (JSON ya da multipart) ve yerel kayda yaz. Çağıran sahiplik/yol kapılarını GEÇMİŞTİR
    (`web_steward.http_job_submit`); `files` doğrulanmış mutlak yollardır. `post(svc, path, body, stream)` testler için.
    Dönen: `{ok, id, state, deduplicated, job}` ya da `{ok: False, error, ...}`."""
    paths = sw.paths_for(sid)
    service = service or default_service()
    svcs = load_services()
    svc = svcs.get(service)
    if svc is None:
        return {"ok": False, "error": f"service {service!r} is not registered (human: py/cops steward service add)"}
    shas = [file_sha256(p) for p in files]
    key = make_idempotency_key(sid, project, kind, params, spec_text, shas)
    with sw.steward_lock(paths):
        for j in load_jobs(paths):
            if j.get("idempotency_key") == key and j.get("service") == service:
                return {"ok": True, "id": j.get("id"), "state": j.get("state"), "deduplicated": True, "job": job_view(j)}
    meta: Dict[str, Any] = {"kind": kind, "requester": project, "params": params or {}, "idempotency_key": key,
                            "meta": {"steward": sid, "host": host, "project": project}}
    if spec_text:
        meta["spec_text"] = spec_text
    if priority is not None:
        meta["priority"] = int(priority)
    if approval_ref:
        meta["approval_ref"] = approval_ref[:400]
    stream = None
    if files:
        parts: List[Tuple[str, Optional[str], str, Any]] = [("meta", None, "application/json",
                                                              json.dumps(meta, ensure_ascii=False).encode("utf-8"))]
        for p in files:
            parts.append(("file", os.path.basename(p), mimetypes.guess_type(p)[0] or "application/octet-stream", p))
        stream = MultipartBody(parts)
    try:
        if post is not None:
            status, body = post(svc, "/api/jobs", None if stream else meta, stream)
        else:
            status, body = request_json(svc, "POST", "/api/jobs", body=None if stream else meta, stream=stream,
                                        timeout=SUBMIT_TIMEOUT)
    except ServiceError as e:
        sw.log_event("job_submit_failed", paths=paths, service=service, project=project, kind=kind, error=e.kind)
        return {"ok": False, "error": f"{service}: {e}", "kind": e.kind}
    if status not in (200, 201) or not isinstance(body, dict) or body.get("id") in (None, ""):
        code = body.get("error") if isinstance(body, dict) else ""
        detail = body.get("detail") if isinstance(body, dict) else ""
        sw.log_event("job_submit_rejected", paths=paths, service=service, project=project, kind=kind, status=status, code=str(code))
        return {"ok": False, "error": f"{service}: HTTP {status} {code} {str(detail)[:200]}".strip(), "status": status}
    rec = new_record(service, body["id"], project, kind, str(body.get("state") or "queued"), key)
    rec = save_record(rec, paths)
    sw.log_event("job_submit", paths=paths, service=service, id=body["id"], project=project, kind=kind,
                 state=rec.get("state"), deduplicated=bool(body.get("deduplicated")), files=len(files))
    return {"ok": True, "id": body["id"], "state": rec.get("state"), "deduplicated": bool(body.get("deduplicated")),
            "job": job_view(rec)}


def resolve_local_files(cwd: str, files: Iterable[str]) -> List[str]:
    """Yerel dosya yollarını PROJE DİZİNİNE kilitle: mutlak ya da göreli, `realpath` (symlink dahil) `cwd` altında,
    düzenli dosya olmalı. İhlal `ValueError` (tümü reddedilir)."""
    if not cwd or not os.path.isdir(cwd):
        raise ValueError("project directory unknown")
    root = os.path.realpath(cwd)
    out: List[str] = []
    for f in files:
        if not isinstance(f, str) or not f or "\x00" in f:
            raise ValueError("invalid file path")
        full = os.path.realpath(f if os.path.isabs(f) else os.path.join(root, f))
        if full != root and not full.startswith(root + os.sep):
            raise ValueError(f"path outside the project directory: {f}")
        if not os.path.isfile(full):
            raise ValueError(f"not a regular file: {f}")
        if full not in out:
            out.append(full)
    if len(out) > MAX_FILES:
        raise ValueError(f"too many files (max {MAX_FILES})")
    return out
