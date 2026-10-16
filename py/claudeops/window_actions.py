"""Pencere eylemleri: handover / durdur + yeni isim / durdur / yeni chat / sıfırla (TODO.md 2026-10-16).

Aynı beş eylem iki tür pencerede kullanılır:
  - YEREL session penceresi (gerçek tmux client'ı): tmux şeridindeki menü (`C-b a` ya da şerit düğmesi,
    `data/tmux-strip.conf`) `py/cops winact` komutunu çağırır;
  - `cops watch` penceresi (uzak host ya da `local:` mirror): `a` tuşu bu modülü arka plan thread'inde çağırır.

Panelin Çalışan sekmesi bu bileşimi arayüzde kendisi kuruyor (webui BulkBar.tsx `handleBulk`, OptionsRow.tsx `handleGo`):
sunucuda toplu uç YOK, yalnız ilkel uçlar var. Burada aynı dizi, yerel panelin HTTP API'si üzerinden kurulur. İlkel
uçların hepsi `web_hosts.HOST_ROUTED_PATHS`'ta olduğundan uzak host'a panel yönlendirir: uzak host'a yeni bir uç
DAĞITMAK gerekmez. Arayüzdeki varsayılanlar (model: canlı model, izin: auto, effort: CLI'nin en yükseği) burada
tekrarlanır; arayüzdeki bu mantık değişirse buradaki de değişmeli.

Güvenlik duruşu (CLAUDE.md): öldürme YALNIZ panelin `/api/stop` yolundan (kill.py), asla PID/süreç ağacıyla; token argv'ye
ve URL'ye girmez (`Authorization: Bearer`); yıkıcı bileşik eylemlerde (durdur + yeniden başlat) hiçbir şey durdurulmadan
ÖNCE yeniden başlatılabilirlik denetlenir, yani "durdurdu ama geri açamadı" yarım kalması kayıtsız oturumlarda olmaz.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .paths import CLAUDEOPS_DIR

LOCAL_HOST = "local"                # hosts.LOCAL_HOST_NAME ile aynı (bu modül yaprak kalsın diye yinelenir)
DEFAULT_PERMISSION_MODE = "auto"    # webui RunningTab/cliDefaults.ts DEFAULT_PERMISSION_MODE
STATUS_TIMEOUT_SECONDS = 30.0
# start / new-chat yeni sürecin 5 sn KESİNTİSİZ ayakta kalmasını bekler (web._wait_stable); uzak host proxy'si
# web_hosts.ACTION_TIMEOUT_SECONDS=200 sn'ye kadar sürebilir.
ACTION_TIMEOUT_SECONDS = 240.0
LANG = "tr"


@dataclass(frozen=True)
class Action:
    id: str        # `py/cops winact <id>` ve panel eylem adı
    key: str       # menü kısayolu (tek küçük harf)
    label: str     # panelle AYNI ad (strings.ts)
    short: str     # dar çubuklar için kısa ad
    confirm: bool  # geri alınamaz/yıkıcı: ikinci bir onay ister
    does: str      # onay satırında "ne olacak"


# Sıra kullanıcının sayış sırası: handover / durdur + yeni isim / durdur / yeni / sıfırla.
ACTIONS: Tuple[Action, ...] = (
    Action("handover", "h", "Handover", "handover", False, "devir (handover) mesajı oturuma yazılır"),
    Action("restart", "y", "Durdur + yeni isimle başlat", "durdur+yeni isim", True,
           "durdurulur, aynı projeden YENİ adla taze chat açılır"),
    Action("stop", "d", "Durdur", "durdur", True, "oturum durdurulur"),
    Action("newchat", "n", "Yeni chat aç", "yeni chat", False, "bu oturuma dokunmadan AYRI, ek bir chat açılır"),
    Action("reset", "r", "Sıfırla", "sıfırla", True,
           "durdurulur, AYNI adla sıfırdan (--new) başlatılır; konuşma bir daha görünmez"),
)
BY_ID: Dict[str, Action] = {a.id: a for a in ACTIONS}
BY_KEY: Dict[str, Action] = {a.key: a for a in ACTIONS}

# Hedefte oturum yalnız yeniden başlatılabiliyorsa (panelde kayıtlı blueprint/instance) durdurulur.
_NEEDS_REGISTERED = ("restart", "newchat", "reset")
_NEEDS_RUNNING = ("handover", "stop")


class PanelError(Exception):
    """Yerel panele ulaşılamadı / panel anlamsız yanıt verdi. `auth`: token reddedildi ya da okunamadı."""

    def __init__(self, detail: str, *, auth: bool = False):
        super().__init__(detail)
        self.detail = detail
        self.auth = auth


@dataclass(frozen=True)
class Result:
    ok: bool
    message: str      # tek satır; çubukta / tmux mesajında gösterilir
    name: str = ""    # yeni açılan chat'in adı (varsa)


class PanelClient:
    """Yerel panelin JSON API'si (`127.0.0.1:<port>`). `read_token` çağrı anında token'ı döndürür (dosyadan tazelenir);
    hata verirse `.detail`li bir istisna fırlatabilir."""

    def __init__(self, port: int, read_token: Callable[[], str], *,
                 urlopen: Callable[..., Any] = urllib.request.urlopen):
        self.port = port
        self._read_token = read_token
        self._urlopen = urlopen

    def get(self, path: str, timeout: float = STATUS_TIMEOUT_SECONDS) -> dict:
        return self._call("GET", path, None, timeout)

    def post(self, path: str, payload: dict, timeout: float = ACTION_TIMEOUT_SECONDS) -> dict:
        return self._call("POST", path, payload, timeout)

    def _call(self, method: str, path: str, payload: Optional[dict], timeout: float) -> dict:
        try:
            token = self._read_token()
        except Exception as e:   # TransportError (watch.read_token) ya da OSError: nedeni olduğu gibi taşı
            raise PanelError(str(getattr(e, "detail", None) or e) or "token okunamadı", auth=True)
        headers = {"Authorization": f"Bearer {token}"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body, method=method, headers=headers)
        try:
            with self._urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            e.close()
            if e.code in (401, 403):
                raise PanelError(f"http {e.code}: web.token {self.port} portundaki panelle eşleşmiyor", auth=True)
            raise PanelError(f"http {e.code}")
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise PanelError(str(getattr(e, "reason", None) or e))
        try:
            data = json.loads(raw)
        except ValueError:
            raise PanelError("panel JSON olmayan yanıt verdi")
        if not isinstance(data, dict):
            raise PanelError("panel beklenmeyen yanıt verdi")
        return data


class ActionBusy(Exception):
    """Aynı oturumda başka bir pencere eylemi sürüyor."""


class ActionLock:
    """(host, ad) başına süreçler arası KİLİT (`flock`, bloklamaz). Neden: durdur + yeni isim ~10 sn sürer; bu sürede
    ikinci bir tetik (çift tıklama, bir tmux menüsü ve bir mirror penceresi aynı anda) oturum henüz durmamışken ikinci
    bir `stop` ya da, durduktan sonra, İKİNCİ bir yeni chat açardı. Kilit dosyası `$XDG_RUNTIME_DIR`de (tmpfs, oturum
    kapanınca silinir); yoksa durum dizininde. Kilit dosyası AÇILAMAZSA eylem kilitsiz sürer (kilit eylemi engellemesin)."""

    def __init__(self, host: str, name: str, *, directory: Optional[str] = None):
        base = directory or os.environ.get("XDG_RUNTIME_DIR") or CLAUDEOPS_DIR
        digest = hashlib.sha1(f"{host}\0{name}".encode("utf-8")).hexdigest()[:10]   # farklı adlar aynı güvenli ada inmesin
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{host}.{name}")[:60]
        self.path = os.path.join(base, f"claudeops-winact.{safe}.{digest}.lock")
        self._fd: Optional[int] = None

    def acquire(self) -> None:
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        except OSError:
            return   # kilitsiz sür
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:   # YALNIZ "kilit başkasında" eylemi engeller
            os.close(fd)
            raise ActionBusy("bu oturumda başka bir pencere eylemi sürüyor")
        except OSError:           # ENOLCK vb.: kilit kurulamadı, eylemi engelleme (açılamayan dosyayla aynı kural)
            os.close(fd)
            return
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def __enter__(self) -> "ActionLock":
        self.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


# ── hedef ve satır çözümleme ─────────────────────────────────────────────────────────────────

def check_target(host: str, name: str) -> None:
    """Boş parça ya da boşluk/denetim karakteri ValueError (komut satırından ya da tmux biçiminden gelen değerler)."""
    for label, part in (("host", host), ("ad", name)):
        if not part or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in part):
            raise ValueError(f"geçersiz {label}: {part!r}")


def find_row(status: dict, host: str, name: str) -> Optional[dict]:
    """`/api/status` toplu yanıtında (host, ad) satırı. Aynı ad birden çok host'ta olabilir (`mgw…` yerelde ve uzakta)."""
    for s in status.get("sessions") or []:
        if s.get("name") == name and (s.get("host") or LOCAL_HOST) == host:
            return s
    return None


def _cli_options(status: dict, host: str, cli: str) -> dict:
    if host == LOCAL_HOST:
        return (status.get("cli_options") or {}).get(cli) or {}
    for h in status.get("hosts") or []:
        if h.get("name") == host:
            return (h.get("cli_options") or {}).get(cli) or {}
    return {}


_MODEL_RE = re.compile(r"^[\w.\-:/\[\]]+$")


def _plausible_model(model: str) -> bool:
    """Panel kayıtsız satırlara model yerine "?" yazıyor; böyle bir değer spawn'a `--model ?` diye gitmesin."""
    return bool(model) and bool(_MODEL_RE.match(model))


def spawn_fields(status: dict, row: dict, host: str) -> Dict[str, str]:
    """Arayüzün OptionsRow.tsx başlangıç durumunun karşılığı: hiçbir şeyi değiştirmeden "Devam" demek.
      - model: yalnız YEREL session için (uzak host kendi varsayılanını uygular); çalışıyorsa CANLI model
        (`effectiveModel`: live_model || kayıtlı model), değilse ayarlardaki varsayılan;
      - izin: auto;  effort: CLI'nin en yüksek seviyesi (`defaultEffort`, listenin sonuncusu);  cli: satırın kendisi.
    Boş alan = sunucunun kendi varsayılanı."""
    cli = str(row.get("cli") or "")
    model = ""
    if host == LOCAL_HOST:
        if row.get("running"):
            model = str(row.get("live_model") or row.get("model") or "")
        else:
            model = str(((status.get("settings") or {}).get("default_model") or {}).get(cli) or "")
    levels: List[str] = _cli_options(status, host, cli).get("effort_levels") or []
    return {
        "model": model if _plausible_model(model) else "",
        "permission_mode": DEFAULT_PERMISSION_MODE,
        "effort": str(levels[-1]) if levels else "",
        "cli": cli,
        "lang": LANG,
    }


def preflight(action: Action, row: Optional[dict], host: str, name: str) -> str:
    """Boş = tamam; değilse çubukta gösterilecek neden. HİÇBİR şey durdurulmadan ÖNCE koşar."""
    target = name if host == LOCAL_HOST else f"{host}:{name}"
    if row is None:
        return f"{target} panelde yok"
    if action.id in _NEEDS_RUNNING and not row.get("running"):
        return f"{target} çalışmıyor"
    if action.id in _NEEDS_REGISTERED and row.get("registered") is False:
        why = "bundan yeni chat türetilemez" if action.id == "newchat" else \
            "yeniden başlatılamaz, bu yüzden HİÇBİR şey durdurulmadı"
        return f"{target} kayıtsız (roster/instances.json'da yok): {why}"
    return ""


# ── eylemler ─────────────────────────────────────────────────────────────────────────────────

def _post(client: PanelClient, path: str, payload: dict) -> Tuple[bool, str, dict]:
    try:
        data = client.post(path, payload)
    except PanelError as e:
        return False, e.detail, {}
    if data.get("ok"):
        return True, "", data
    return False, str(data.get("error") or "panel reddetti"), data


def run_action(client: PanelClient, action_id: str, host: str, name: str, *,
               on_step: Optional[Callable[[str], None]] = None) -> Result:
    """`host`'taki `name` oturumuna eylemi uygular. Bloklar (yeni süreç ayakta kalana dek ~10 sn, uzak host'ta daha
    çok): arka plan thread'inden çağırın. `on_step` ilerleme metnini bildirir ("durduruluyor…")."""
    action = BY_ID.get(action_id)
    if action is None:
        return Result(False, f"✗ bilinmeyen eylem: {action_id}")
    try:
        check_target(host, name)
    except ValueError as e:
        return Result(False, f"✗ {action.label}: {e}")

    def step(text: str) -> None:
        if on_step is not None:
            on_step(text)

    step("panel durumu okunuyor…")
    try:
        status = client.get("/api/status")
    except PanelError as e:
        return Result(False, f"✗ {action.label}: panel durumu alınamadı: {e.detail}")
    row = find_row(status, host, name)
    problem = preflight(action, row, host, name)
    if problem:
        return Result(False, f"✗ {action.label}: {problem}")
    assert row is not None
    base = {"name": name, "host": host, "lang": LANG}

    if action.id == "handover":
        step("handover gönderiliyor…")
        ok, err, _ = _post(client, "/api/handover", base)
        return Result(True, "✓ handover mesajı yazıldı") if ok else Result(False, f"✗ handover: {err}")

    if action.id == "stop":
        step("durduruluyor…")
        ok, err, _ = _post(client, "/api/stop", base)
        return Result(True, "✓ durduruldu") if ok else Result(False, f"✗ durdurulamadı: {err}")

    fields = spawn_fields(status, row, host)

    if action.id == "newchat":
        step("yeni chat açılıyor…")
        ok, err, data = _post(client, "/api/new-chat", {"base": name, "host": host, **fields})
        if not ok:
            return Result(False, f"✗ yeni chat açılamadı: {err}")
        new = str(data.get("name") or "")
        return Result(True, f"✓ yeni chat: {new}" if new else "✓ yeni chat açıldı", name=new)

    # restart / reset: çalışıyorsa önce durdur (durmuşsa yalnız başlatma yarısı; toplu eylemle AYNI kural)
    if row.get("running"):
        step("durduruluyor…")
        ok, err, _ = _post(client, "/api/stop", base)
        if not ok:
            return Result(False, f"✗ durdurulamadı, yeni bir şey başlatılmadı: {err}")

    if action.id == "restart":
        step("durduruldu · yeni chat açılıyor…")
        ok, err, data = _post(client, "/api/new-chat", {"base": name, "host": host, **fields})
        if not ok:
            return Result(False, f"✗ durduruldu ama yeni chat açılamadı: {err}")
        new = str(data.get("name") or "")
        return Result(True, f"✓ durduruldu · yeni chat: {new}" if new else "✓ durduruldu · yeni chat açıldı", name=new)

    step("durduruldu · sıfırdan başlatılıyor…")
    ok, err, _ = _post(client, "/api/start", {"name": name, "host": host, "fresh": True, **fields})
    if not ok:
        return Result(False, f"✗ durduruldu ama sıfırdan başlatılamadı: {err}")
    return Result(True, "✓ sıfırlandı: aynı adla taze başlatıldı")
