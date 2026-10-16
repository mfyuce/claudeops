"""Yerel SearXNG (docker) = ucli'nin `web_search` aracı için OTOMATİK arama arka ucu.

Kullanıcı kararı (2026-10-16, "ucli web search yapacaksa docker da oto olsun şimdilik"): bir ucli oturumu
açılırken `providers/ucli_provider._web_args` buradaki `ensure_search_url()`ı çağırır, dönen adres
`--search-url` olur; kapsayıcıyı elle kurmak/başlatmak GEREKMEZ. `settings.json`'da `ucli_web.search_url`
varsa o kazanır (docker'a dokunulmaz); `ucli_web.search_docker = "off"` otomatiği kapatır.

⚠ GEÇİCİ KÖPRÜ (TOBEDECIDED.md TBD#88; kullanıcı: "ucli kendi icinde search u halledene kadar ... ucli
implemente ettiginde bizde artik baslatmayalim"): ucli aramayı Docker'sız kendi içine alınca claudeops
docker'ı ARTIK BAŞLATMAZ ve bu modül kalkar. Çıkış kontrol listesi TBD#88'de; silmeden ÖNCE `py/cops searxng rm`.

Tasarım (neden böyle):
- SPAWN YOLU HİÇBİR ZAMAN İMAJ ÇEKMEZ ve uzun beklemez (panel isteği bir `docker pull`a asılı kalmasın).
  Hızlı yol: kayıtlı portta `/healthz` cevap veriyorsa adres hazırdır (docker CLI'ya bile dokunmadan, ms).
  Kapsayıcı var ama duruyorsa `docker start` + en çok birkaç sn bekleme. Hiç yoksa kurulum (imaj çekmek dakikalar
  sürebilir) AYRI bir süreçte başlar (`provision`); o spawn aramasız açılır, sonrakiler adresi alır.
- Tek kapsayıcı, kullanıcıya özel ad (`claudeops-searxng-<kullanıcı>`: docker daemon makine-geneli, makine
  çok-kullanıcılı) ve `claudeops.managed=searxng` etiketiyle. Etiketsiz aynı adlı bir kapsayıcıya DOKUNULMAZ.
  `start/stop/rm` yalnız bu TAM ada uygulanır (asla `ps | xargs`, `prune` ya da desen eşleşmesi).
- Yalnız loopback'te yayınlanır (`127.0.0.1:PORT`), root'suz (imajın `searxng` kullanıcısı 977), tüm Linux
  yetenekleri kapalı, `no-new-privileges`, bellek/süreç sınırlı. Yeniden başlatma ilkesi `no`: kapsayıcı YALNIZ
  bir ucli oturumu açılırken (`ensure_search_url`) başlatılır, makine/docker yeniden açılınca kendiliğinden
  GELMEZ ("ucli varsa docker"; ayrıca özellik kalkınca geride kendiliğinden dönen bir kalıntı kalmaz).
  Boştayken ~110 MiB bellek, ~%0.2 CPU ölçüldü (2026-10-16).
- `settings.yml` (`search.formats`ta `json` ŞART: yoksa SearXNG `format=json` isteğine 403 döner) imaja `:ro`
  bağlanır, gizli anahtarı dosyada kalır; hiçbir sır argv'ye girmez. Üst dizin (`~/.claude/claudeops`) 0700
  olduğu için dosya 0644 olsa da başka kullanıcılar ona ulaşamaz; kapsayıcı kullanıcısı (977) yalnız bağlanan
  `etc/` alt dizinini görür (durum/kilit/günlük dosyaları bir üstte kalır).
- Ağa çıkan tek şey imaj çekimi (Docker Hub) ve SearXNG'nin arama motorlarına yaptığı sorgulardır.
"""
from __future__ import annotations
import contextlib
import fcntl
import getpass
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from .atomic_json import atomic_write_json
from .diaglog import diag_log
from .paths import CLAUDE_DIR, CLAUDEOPS_DIR

# `latest` kayan bir etiket: imaj YALNIZ yerelde yoksa çekilir (kendiliğinden güncellenmez); çekilen imajın
# kimliği `state.json`a ve günlüğe yazılır (hangi sürümün çalıştığı sonradan görülebilsin).
IMAGE = "docker.io/searxng/searxng:latest"
IMAGE_USER = "977:977"            # imajdaki `searxng` kullanıcısı (id çıktısı: uid=977 gid=977)
LABEL = "claudeops.managed=searxng"
CONTAINER_PORT = 8080
PREFERRED_PORT = 8888
PORT_SPAN = 100
STATE_DIR = os.path.join(CLAUDEOPS_DIR, "searxng")

DOCKER_PROBE_TIMEOUT = 4.0        # spawn yolundaki docker çağrıları kısa tutulur
INSPECT_TIMEOUT = 5.0
START_TIMEOUT = 15.0
READY_WAIT_S = 8.0                # spawn yolunda `docker start` sonrası en çok bu kadar beklenir
PROVISION_WAIT_S = 45.0
PULL_TIMEOUT = 900.0
FAIL_COOLDOWN_S = 600.0           # başarısız kurulumdan sonra bu süre yenisi başlatılmaz
DOCKER_DOWN_TTL_S = 60.0          # docker kullanılamıyorsa bu süre tekrar yoklanmaz

KICK_WINDOW_S = 20.0              # ayrık kurulum süreci kilidi alana dek (Python açılışı) ikinci süreç başlatılmaz

_now = time.monotonic             # testlerde sahte saatle değiştirilir
_wall = time.time
_sleep = time.sleep


class DockerUnavailable(Exception):
    """docker CLI yok / daemon'a ulaşılamıyor / izin yok / zaman aşımı."""


class Busy(Exception):
    """Başka bir süreç kurulumu yürütüyor."""


# ── adlar ve yollar ──────────────────────────────────────────────────────────────────────────────────

def _owner() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return str(os.getuid())


def container_name() -> str:
    """`claudeops-searxng-<kullanıcı>`. CLAUDEOPS_DIR varsayılandan farklıysa (izole e2e / test kopyası)
    dizinin özeti eklenir: izole bir panel canlı kapsayıcıyı paylaşmaz, silmez."""
    safe = re.sub(r"[^a-z0-9_.-]+", "-", _owner().lower()).strip("-_.") or str(os.getuid())
    name = f"claudeops-searxng-{safe}"
    default = os.path.realpath(os.path.join(CLAUDE_DIR, "claudeops"))
    actual = os.path.realpath(CLAUDEOPS_DIR)
    if actual != default:
        name += "-" + hashlib.sha1(actual.encode("utf-8")).hexdigest()[:8]
    return name


def search_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/search"


def _conf_dir() -> str:
    return os.path.join(STATE_DIR, "etc")          # kapsayıcıya bağlanan TEK dizin


def _state_path() -> str:
    return os.path.join(STATE_DIR, "state.json")


def _lock_path() -> str:
    return os.path.join(STATE_DIR, ".lock")


def _log_path() -> str:
    return os.path.join(STATE_DIR, "provision.log")


def _tail(text: Optional[str], n: int = 240) -> str:
    lines = [ln.strip() for ln in (text or "").strip().splitlines() if ln.strip()]
    return (lines[-1] if lines else "")[:n]


def _int(v: Any) -> Optional[int]:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 0 < n < 65536 else None


# ── docker (TEK dış çağrı noktası) ───────────────────────────────────────────────────────────────────

_down_until = 0.0
_down_reason = ""


def _docker(*args: str, timeout: float = 10.0) -> "subprocess.CompletedProcess[str]":
    """docker CLI'yı çalıştırır. Bu modüldeki TEK `subprocess` çağrısı noktası (testler burayı yamalar).
    CLI yok / daemon'a erişilemiyor / zaman aşımı → `DockerUnavailable`; komutun kendi hatası (rc != 0)
    istisna DEĞİL, çağıran `returncode`a bakar."""
    exe = shutil.which("docker")
    if not exe:
        raise DockerUnavailable("docker PATH'te yok")
    try:
        return subprocess.run([exe, *args], capture_output=True, text=True, errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise DockerUnavailable(f"docker {args[0] if args else ''} {timeout:g} sn içinde bitmedi")
    except OSError as e:
        raise DockerUnavailable(str(e))


def _mark_down(reason: str) -> None:
    global _down_until, _down_reason
    _down_until = _now() + DOCKER_DOWN_TTL_S
    _down_reason = reason


def docker_usable(force: bool = False) -> Tuple[bool, str]:
    """(kullanılabilir mi, sürüm ya da neden). Olumsuz sonuç `DOCKER_DOWN_TTL_S` önbelleğe alınır."""
    global _down_until
    if not force and _now() < _down_until:
        return False, _down_reason
    try:
        res = _docker("version", "--format", "{{.Server.Version}}", timeout=DOCKER_PROBE_TIMEOUT)
    except DockerUnavailable as e:
        _mark_down(str(e))
        return False, str(e)
    if res.returncode == 0 and res.stdout.strip():
        _down_until = 0.0
        return True, res.stdout.strip()
    reason = _tail(res.stderr or res.stdout) or f"docker version rc={res.returncode}"
    _mark_down(reason)
    return False, reason


@dataclass
class Box:
    exists: bool = False
    ours: bool = False        # `claudeops.managed=searxng` etiketi var mı (yoksa DOKUNMA)
    running: bool = False
    status: str = ""
    port: Optional[int] = None


def inspect_box() -> Box:
    """Kapsayıcının durumu. Yok → `Box()` (exists=False). docker hatası → `DockerUnavailable`."""
    res = _docker("container", "inspect", container_name(), timeout=INSPECT_TIMEOUT)
    if res.returncode != 0:
        if "no such" in ((res.stderr or "") + (res.stdout or "")).lower():
            return Box()
        raise DockerUnavailable(_tail(res.stderr or res.stdout) or f"inspect rc={res.returncode}")
    try:
        info = json.loads(res.stdout)[0]
        labels = (info.get("Config") or {}).get("Labels") or {}
        state = info.get("State") or {}
        binds = ((info.get("HostConfig") or {}).get("PortBindings") or {}).get(f"{CONTAINER_PORT}/tcp") or [{}]
    except (ValueError, IndexError, TypeError, AttributeError):
        raise DockerUnavailable("inspect çıktısı ayrıştırılamadı")
    key, _, val = LABEL.partition("=")
    return Box(exists=True, ours=labels.get(key) == val, running=bool(state.get("Running")),
               status=str(state.get("Status") or ""), port=_int((binds[0] or {}).get("HostPort")))


# ── HTTP yoklamaları (docker'sız) ────────────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: float) -> Tuple[int, bytes]:
    # ortam proxy'si (http_proxy) loopback'e girmesin: urllib 127.0.0.1'i kendiliğinden proxy dışı SAYMAZ
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as r:
            return r.status, r.read(2_000_000)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, OSError, ValueError):
        return 0, b""


def healthy(port: int, timeout: float = 1.5) -> bool:
    """SearXNG'nin `/healthz`i (200 "OK"). Arama motorlarına SORGU ATMAZ (hızlı yol her spawn'da çalışır)."""
    return _http_get(f"http://127.0.0.1:{port}/healthz", timeout)[0] == 200


def json_search_works(port: int, timeout: float = 25.0) -> Tuple[bool, str]:
    """Kurulum sonrası TEK gerçek sorgu: `format=json` açık mı (kapalıysa 403) ve gövde ayrıştırılıyor mu."""
    status, body = _http_get(f"http://127.0.0.1:{port}/search?q=claudeops&format=json", timeout)
    if status == 403:
        return False, "json_disabled"
    if status != 200:
        return False, f"http_{status}"
    try:
        ok = isinstance(json.loads(body).get("results"), list)
    except (ValueError, AttributeError):
        ok = False
    return ok, "" if ok else "bad_json"


def _wait_healthy(port: int, seconds: float) -> bool:
    deadline = _now() + seconds
    while True:
        if healthy(port):
            return True
        if _now() >= deadline:
            return False
        _sleep(0.4)


# ── durum / kilit / yapılandırma ─────────────────────────────────────────────────────────────────────

def _read_state() -> Dict[str, Any]:
    try:
        with open(_state_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _update_state(**kw: Any) -> None:
    """`None` değer o anahtarı siler. Best-effort: durum yazılamazsa akış bozulmaz."""
    st = _read_state()
    for k, v in kw.items():
        if v is None:
            st.pop(k, None)
        else:
            st[k] = v
    try:
        atomic_write_json(_state_path(), st, mode=0o600)
    except OSError:
        pass


@contextlib.contextmanager
def _exclusive() -> Iterator[None]:
    """Süreçler-arası kurulum kilidi (`flock`, bloklamaz): panel + CLI + ayrık kurulum süreci aynı anda
    `docker pull/run` yapmasın. Kapsam bitince fd kapanır, kilit düşer."""
    os.makedirs(STATE_DIR, exist_ok=True)
    fd = os.open(_lock_path(), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy()
        yield
    finally:
        os.close(fd)


_SETTINGS_TEMPLATE = '''# claudeops (searxng.py) üretti. `json` biçimi AÇIK kalmalı: ucli web_search `format=json` ister,
# kapalıysa SearXNG 403 döner. Dosya bozulursa/silinirse bir sonraki kurulumda yeniden üretilir.
use_default_settings: true
server:
  secret_key: "{secret}"
  limiter: false
  image_proxy: false
search:
  formats:
    - html
    - json
'''
_SECRET_RE = re.compile(r'secret_key:\s*"([0-9a-f]{32,})"')
_JSON_FORMAT_RE = re.compile(r"^\s*-\s*json\s*$", re.M)


def ensure_settings_file() -> str:
    """`etc/settings.yml`i üretir (yoksa ya da `json` biçimi kaybolmuşsa; gizli anahtar korunur). Geçerli bir
    dosyaya DOKUNMAZ: elle eklenen motor/ayarlar kalır."""
    conf = _conf_dir()
    os.makedirs(conf, exist_ok=True)
    os.chmod(conf, 0o755)             # kapsayıcı kullanıcısı (977) okuyabilsin; üst dizin 0700 başkalarını dışarıda tutar
    path = os.path.join(conf, "settings.yml")
    secret = None
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        found = _SECRET_RE.search(text)
        if found and _JSON_FORMAT_RE.search(text) and "use_default_settings" in text:
            return path
        secret = found.group(1) if found else None
    except OSError:
        pass
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_SETTINGS_TEMPLATE.format(secret=secret or secrets.token_hex(32)))
    os.chmod(tmp, 0o644)              # umask'tan bağımsız
    os.replace(tmp, path)
    return path


def _port_free(port: int) -> bool:
    """Bu portta DİNLEYEN bir soket yok mu. SO_REUSEADDR ŞART: yoksa eski kapsayıcıdan kalan TIME_WAIT bağlantıları
    portu 'dolu' gösterir ve kayıtlı port (çalışan oturumların argv'sindeki adres) yeniden kurulumda sebepsiz
    değişir (canlı e2e'de görüldü: 8888 → 8889). Dinleyen bir soket varsa (0.0.0.0 dahil) bind yine EADDRINUSE verir."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def pick_port(preferred: Optional[int] = None, skip: Sequence[int] = ()) -> int:
    """Kayıtlı port boşsa o (çalışan oturumların argv'sindeki adres tutarlı kalsın), değilse 8888'den ileri ilk boş."""
    candidates = ([preferred] if preferred else []) + list(range(PREFERRED_PORT, PREFERRED_PORT + PORT_SPAN))
    for p in candidates:
        if p not in skip and _port_free(p):
            return p
    raise RuntimeError(f"{PREFERRED_PORT}-{PREFERRED_PORT + PORT_SPAN - 1} arasında boş port yok")


def run_args(port: int) -> List[str]:
    """`docker run` argümanları (saf fonksiyon, testlerde incelenir). Yayın YALNIZ loopback; sır YOK."""
    return [
        "run", "-d", "--name", container_name(),
        "--label", LABEL, "--label", f"claudeops.owner={_owner()}",
        "--restart", "no",
        "--user", IMAGE_USER, "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--memory", "1g", "--memory-swap", "1g", "--pids-limit", "512",
        "--log-driver", "json-file", "--log-opt", "max-size=2m", "--log-opt", "max-file=2",
        "-p", f"127.0.0.1:{port}:{CONTAINER_PORT}",
        "--mount", f"type=bind,source={_conf_dir()},target=/etc/searxng,readonly",
        # imajın `VOLUME /var/cache/searxng`i anonim bir disk birimi açardı (silinen kapsayıcıdan geriye kalır);
        # önbellek kalıcı olmak zorunda değil → bellek-içi, sahibi imajın kullanıcısı
        "--tmpfs", f"/var/cache/searxng:rw,uid={IMAGE_USER.split(':')[0]},gid={IMAGE_USER.split(':')[1]},mode=0755,size=64m",
        "-e", "FORCE_OWNERSHIP=false",
        IMAGE,
    ]


# ── kurulum (yavaş yol; ayrı süreçte ya da CLI'dan) ──────────────────────────────────────────────────

def _remove_ours() -> None:
    """Yalnız etiketi bizim olan TAM adlı kapsayıcıyı siler (başarısız `run` bir 'Created' kalıntısı bırakabilir)."""
    box = inspect_box()
    if box.exists and box.ours:
        _docker("rm", "-f", "-v", container_name(), timeout=30.0)


def _fail(state: str, detail: str) -> Dict[str, Any]:
    return {"ok": False, "state": state, "detail": detail}


def _finish(port: int) -> Dict[str, Any]:
    ok, why = json_search_works(port)
    image_id = ""
    try:
        res = _docker("image", "inspect", IMAGE, "--format", "{{.Id}}", timeout=INSPECT_TIMEOUT)
        image_id = res.stdout.strip() if res.returncode == 0 else ""
    except DockerUnavailable:
        pass
    if not ok:
        return {**_fail("json_probe_failed", why), "port": port, "image_id": image_id}
    _update_state(port=port, image_id=image_id, provisioned_at=_wall())
    return {"ok": True, "state": "ready", "port": port, "url": search_url(port), "image_id": image_id}


def _provision_locked(wait_s: float, pull_timeout: float) -> Dict[str, Any]:
    usable, why = docker_usable(force=True)
    if not usable:
        return _fail("docker_unavailable", why)
    name = container_name()
    box = inspect_box()
    if box.exists and not box.ours:
        return _fail("name_conflict", f"{name} adlı kapsayıcı claudeops'unki değil (etiket yok); dokunulmadı")
    if box.exists:
        if not box.running:
            started = _docker("start", name, timeout=START_TIMEOUT * 2)
            if started.returncode != 0:
                _remove_ours()        # durumsuz (yapılandırma bind-mount): silip yeniden kurmak güvenli
                box = Box()
        if box.exists and box.port and _wait_healthy(box.port, wait_s):
            return _finish(box.port)
        if box.exists:
            _remove_ours()
    if _docker("image", "inspect", IMAGE, timeout=INSPECT_TIMEOUT * 2).returncode != 0:
        diag_log("searxng_pull_started", image=IMAGE)
        pulled = _docker("pull", IMAGE, timeout=pull_timeout)
        if pulled.returncode != 0:
            return _fail("pull_failed", _tail(pulled.stderr or pulled.stdout))
    ensure_settings_file()
    preferred = _int(_read_state().get("port"))
    tried: List[int] = []
    err = ""
    port = 0
    for _ in range(3):
        port = pick_port(preferred, skip=tried)
        res = _docker(*run_args(port), timeout=60.0)
        if res.returncode == 0:
            break
        err = _tail(res.stderr or res.stdout)
        _remove_ours()
        if not re.search(r"port is already allocated|address already in use", err, re.I):
            return _fail("run_failed", err)
        tried.append(port)
    else:
        return _fail("run_failed", err or "port ayrılamadı")
    if not _wait_healthy(port, wait_s):
        logs = _docker("logs", "--tail", "5", name, timeout=INSPECT_TIMEOUT)
        return {**_fail("not_ready", _tail(logs.stderr or logs.stdout)), "port": port}
    return _finish(port)


def provision(*, wait_s: float = PROVISION_WAIT_S, pull_timeout: float = PULL_TIMEOUT) -> Dict[str, Any]:
    """Idempotent kurulum: imaj (yoksa çek) + yapılandırma + kapsayıcı + sağlık + bir gerçek JSON sorgusu.
    Sonuç sözlüğü `ok/state/detail`. Hiç istisna dışarı çıkmaz. Başarısızlık `FAIL_COOLDOWN_S` boyunca yeni
    otomatik kurulumu engeller (ör. ağ yokken her spawn'da `docker pull` denenmesin)."""
    try:
        with _exclusive():
            res = _provision_locked(wait_s, pull_timeout)
    except Busy:
        return _fail("busy", "başka bir kurulum sürüyor")
    except DockerUnavailable as e:
        res = _fail("docker_unavailable", str(e))
    except Exception as e:
        res = _fail("error", repr(e)[:300])
    if res["ok"]:
        _update_state(provision_failed_at=None, provision_started_at=None)
    elif res["state"] != "busy":
        _update_state(provision_failed_at=_wall(), provision_started_at=None)
    diag_log("searxng_provision", **{k: v for k, v in res.items() if k != "url"})
    return res


def _spawn_provision_child() -> bool:
    """Kurulumu AYRI, bağımsız bir süreçte başlatır (panel/CLI çıksa da sürer). `py/cops` ile aynı: py/ dizininden
    `python -m claudeops searxng provision`."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        log = open(_log_path(), "ab")
    except OSError:
        log = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "claudeops", "searxng", "provision"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            stdin=subprocess.DEVNULL, stdout=log or subprocess.DEVNULL, stderr=log or subprocess.DEVNULL,
            start_new_session=True, close_fds=True)
    except OSError as e:
        diag_log("searxng_provision_spawn_failed", error=str(e)[:200])
        return False
    finally:
        if log is not None:
            log.close()
    threading.Thread(target=proc.wait, daemon=True).start()     # zombi kalmasın
    return True


def _kick_provision(session_name: str) -> bool:
    """Ayrık kurulum sürecini başlatır; zaten sürüyorsa (kilit dolu), yeni başlatıldıysa (işaret) ya da yakın zamanda
    başarısız olduysa (bekleme) başlatmaz. Dönüş: yeni süreç başlatıldı mı."""
    st = _read_state()
    failed, begun = st.get("provision_failed_at"), st.get("provision_started_at")
    if isinstance(failed, (int, float)) and 0 <= _wall() - failed < FAIL_COOLDOWN_S:
        diag_log("searxng_provision_cooldown", name=session_name)
        return False
    if isinstance(begun, (int, float)) and 0 <= _wall() - begun < KICK_WINDOW_S:
        return False
    try:
        with _exclusive():
            pass
    except Busy:
        return False                      # zaten sürüyor
    _update_state(provision_started_at=_wall())
    started = _spawn_provision_child()
    if started:
        diag_log("searxng_provision_started", name=session_name)
    return started


# ── spawn yolu (hızlı; asla fırlatmaz, asla imaj çekmez) ─────────────────────────────────────────────

def ensure_search_url(session_name: str = "") -> Optional[str]:
    """Bir ucli oturumunun `--search-url`ü olacak adres; şu an cevap veren bir SearXNG yoksa `None` (o oturum
    aramasız açılır). Asla fırlatmaz: web araması yüzünden spawn ASLA kırılmaz."""
    try:
        return _ensure(session_name)
    except DockerUnavailable as e:
        _mark_down(str(e))
        diag_log("searxng_unavailable", name=session_name, reason=str(e)[:200])
    except Exception as e:
        diag_log("searxng_ensure_error", name=session_name, error=repr(e)[:200])
    return None


def _ensure(session_name: str) -> Optional[str]:
    port = _int(_read_state().get("port"))
    if port and healthy(port):
        return search_url(port)
    if _now() < _down_until:
        return None                       # docker yakın zamanda kullanılamıyordu; her spawn'da yeniden yoklama
    box = inspect_box()
    if box.exists and not box.ours:
        diag_log("searxng_name_conflict", name=session_name, container=container_name())
        return None
    if not box.exists or not box.port:
        _kick_provision(session_name)
        return None
    if not box.running:
        res = _docker("start", container_name(), timeout=START_TIMEOUT)
        if res.returncode != 0:
            diag_log("searxng_start_failed", name=session_name, error=_tail(res.stderr or res.stdout))
            _kick_provision(session_name)  # ör. yeniden açılışta port başkasına geçti: sil + yeni portla kur
            return None
        diag_log("searxng_started", name=session_name, port=box.port)
    if _wait_healthy(box.port, READY_WAIT_S):
        _update_state(port=box.port)
        return search_url(box.port)
    diag_log("searxng_not_ready", name=session_name, port=box.port, status=box.status)
    if box.status in ("restarting", "dead"):
        _kick_provision(session_name)     # çöküp duran/yeniden başlayıp duran kapsayıcı kendiliğinden düzelmez: sil + yeniden kur
    return None


# ── CLI yardımcıları (`py/cops searxng status|provision|stop|rm`) ───────────────────────────────────

def status() -> Dict[str, Any]:
    st = _read_state()
    out: Dict[str, Any] = {"container": container_name(), "image": IMAGE, "state_dir": STATE_DIR,
                           "port": _int(st.get("port")), "image_id": st.get("image_id") or "",
                           "docker": "", "exists": False, "running": False, "healthy": False, "url": None}
    usable, why = docker_usable(force=True)
    if not usable:
        out["docker"] = f"kullanılamıyor: {why}"
        return out
    out["docker"] = f"sürüm {why}"
    try:
        box = inspect_box()
    except DockerUnavailable as e:
        out["docker"] = f"kullanılamıyor: {e}"
        return out
    out.update(exists=box.exists, running=box.running, ours=box.ours, container_status=box.status)
    if box.port:
        out["port"] = box.port
        out["healthy"] = healthy(box.port)
        out["url"] = search_url(box.port) if out["healthy"] else None
    return out


def _act_on_ours(verb: Sequence[str], timeout: float) -> Dict[str, Any]:
    try:
        box = inspect_box()
        if not box.exists:
            return {"ok": True, "state": "absent", "detail": "kapsayıcı yok"}
        if not box.ours:
            return _fail("name_conflict", f"{container_name()} claudeops'unki değil (etiket yok); dokunulmadı")
        res = _docker(*verb, container_name(), timeout=timeout)
    except DockerUnavailable as e:
        return _fail("docker_unavailable", str(e))
    if res.returncode != 0:
        return _fail("failed", _tail(res.stderr or res.stdout))
    return {"ok": True, "state": "done", "detail": " ".join(verb)}


def stop() -> Dict[str, Any]:
    """Durdurur. Bir sonraki ucli spawn'ı `ensure_search_url` ile yeniden BAŞLATIR (otomatik = istenen);
    kalıcı kapatmak için `ucli_web.search_docker = "off"` ve `rm`. Çalışan ucli oturumlarının araması durdurulduğu
    sürece hata verir (adres argv'lerinde sabit); yeni bir oturum açılınca ya da `searxng provision` ile döner."""
    return _act_on_ours(("stop",), 40.0)


def remove() -> Dict[str, Any]:
    """Kapsayıcıyı siler (yapılandırma ve imaj kalır; sonraki spawn yeniden kurar)."""
    return _act_on_ours(("rm", "-f", "-v"), 30.0)
