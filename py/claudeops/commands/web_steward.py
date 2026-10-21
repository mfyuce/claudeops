"""Değnekçi motoru — `steward.plan_tick`'in kararlarını CANLI filoya uygular; `py/cops web`
içinde bir daemon thread olarak döner (`start_loop`), `/api/steward/*` uçlarını sunar.

`web_orch.py` ile AYNI yerleşim: `web.py` bizi import eder, biz onu ETMEYİZ (döngüsel import).
Oturum başlat/durdur/handover/kayıt gibi işler `web.py`'nin kendi fonksiyonlarıdır (guard_lock,
`_wait_stable`, instance kaydı, TSV yazımı hep orada) — `configure()` ile callback olarak alınır,
burada yeniden yazılmaz. `if cli == ...` YOK: provider arayüzü.

Döngü tek bir tick'te ASLA ölmez: her tick try/except + diag_log; bir eylem patlarsa kalanlar yine
uygulanır. Her eylem `steward/log.jsonl`'a düşer (ne yapıldı, neden) — kullanıcı "değnekçi ne yaptı"
sorusunu `py/cops steward log` ile görür.
"""
from __future__ import annotations
import dataclasses
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import psutil

from .. import hosts as hosts_mod
from .. import instances as inst_mod
from .. import steward as sw
from .. import steward_jobs as sj
from ..diaglog import diag_log
from ..discovery import find_sessions
from ..guard import guard_lock
from ..hosts import LOCAL_HOST_NAME
from ..paths import CLAUDEOPS_DIR
from ..providers import PROVIDERS, DEFAULT_CLI, get_provider
from ..providers.base import McpServerSpec, OneshotError
from ..settings import default_effort_for, default_model_for, load_settings, steward_config, steward_ids
from ..spawn import spawn_session, detect_display
from ..stuck import find_stuck
from ..tmux_backend import is_tmux_backed, strip_ansi, tmux_capture, tmux_has_session, tmux_send_keys
from ..turns import is_busy_now
from . import web_ws

NTFY_TOPIC_FILE = os.path.join(CLAUDEOPS_DIR, "ntfy_topic.txt")
TUNNEL_URL_FILE = os.path.join(CLAUDEOPS_DIR, "tunnel_url.txt")
MAX_FORM_BYTES = 16 * 1024
GUARD_LOCK_ACQUIRE_TIMEOUT = 60.0
READY_TIMEOUT_SECONDS = 60.0
READY_MIN_SECONDS = 6.0
DOC_HEAD_CHARS = 1500
DOCS = ("PLAN.md", "TODO.md", "TOBEDECIDED.md", "GOAL.md")
MAX_RESOURCE_BYTES = 50 * 1024 * 1024
MAX_FILE_READ_CHARS = 20000
RECENT_ACTIONS = 12

# Kimlik başına motor durumu (docs/multi-steward-plan.md K3): kilit, son eylemler, son tick, özet önbelleği.
# `default` bağlamı modül globallerinin KENDİSİNİ taşır (`_LOCK`, `_RECENT`, `_LAST_TICK`, `_SUMMARY_CACHE` aynı
# nesneler): argümansız eski çağrılar ve eski testler değişmeden default'a gider.
# Kilit YENİDEN GİRİŞLİ: `http_restart` kilit altındayken `http_directive`i çağırır (düz Lock'ta kendini kilitliyordu).
_LOCK = threading.RLock()         # bir kimliğin tick'i ve elle tetiklenen eylemleri sıralı (başka kimliği beklemez)
_ACTIONS: Dict[str, Callable[..., Any]] = {}
_RECENT: List[Dict[str, Any]] = []
_LAST_TICK: Dict[str, Any] = {"at": 0.0, "trigger": "", "actions": 0, "dry": 0, "error": ""}
_SUMMARY_CACHE: Dict[str, Any] = {"until": 0.0, "value": None}
_loop_started = False
_CARD_LOCK = threading.Lock()      # aynı anda tek kart yenileme işi, TÜM kimlikler için ortak (K7)
_CARD_BACKGROUND = True            # testler False yapıp işi satır içi koşturur
CARD_TIMEOUT_SECONDS = 120.0


@dataclasses.dataclass
class StewardContext:
    """Bir değnekçi kimliğinin süreç içi motor durumu. Dosya yolları ÇAĞRI ANINDA (`paths`), testler `STEWARD_DIR`'i
    patch'ler. `conflicts`: son tick'te bu kimliğin `projects.json`'unda görülen sahiplik çakışmaları (status uyarısı);
    `conflict_logged`: {proje: gün} `ownership_conflict` olayı günde bir."""
    sid: str
    lock: Any = dataclasses.field(default_factory=threading.RLock)
    recent: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    last_tick: Dict[str, Any] = dataclasses.field(
        default_factory=lambda: {"at": 0.0, "trigger": "", "actions": 0, "dry": 0, "error": ""})
    summary_cache: Dict[str, Any] = dataclasses.field(default_factory=lambda: {"until": 0.0, "value": None})
    conflicts: List[str] = dataclasses.field(default_factory=list)
    conflict_logged: Dict[str, str] = dataclasses.field(default_factory=dict)

    @property
    def paths(self) -> sw.StewardPaths:
        return sw.paths_for(self.sid)


_CTX: Dict[str, StewardContext] = {
    "default": StewardContext("default", lock=_LOCK, recent=_RECENT, last_tick=_LAST_TICK, summary_cache=_SUMMARY_CACHE)}
_CTX_GUARD = threading.Lock()


def _ctx(sid: str = "default") -> StewardContext:
    """Kimliğin bağlamı (ilk istekte açılır). Geçersiz kimlik `ValueError` (sessizce default'a DÜŞMEZ)."""
    sid = sid or "default"
    with _CTX_GUARD:
        ctx = _CTX.get(sid)
        if ctx is None:
            if not sw.valid_steward_id(sid):
                raise ValueError(f"invalid steward id: {sid!r}")
            ctx = _CTX[sid] = StewardContext(sid)
        return ctx


def _reset_contexts() -> None:
    """Testler: default DIŞI bağlamları at (default'unkiler modül globalleri, testler onları kendisi temizler)."""
    with _CTX_GUARD:
        for sid in [s for s in _CTX if s != "default"]:
            del _CTX[sid]


def _ownership_index(fresh: bool = False) -> Dict[str, Any]:
    """Ayardaki kimlikler + etkin beyin adları (default'un `brain_name` ezmesi dahil) ile sahiplik indeksi."""
    ids = steward_ids()
    brains: Dict[str, str] = {}
    for s in ids:
        try:
            brains[s] = steward_config(s).brain_name
        except ValueError:
            continue
    return sw.ownership_index(ids, brains=brains, fresh=fresh)


def _world(sid: str = "default", cfg: Optional[sw.Config] = None, starts_left: Optional[int] = None,
           index: Optional[Dict[str, Any]] = None) -> sw.World:
    cfg = cfg or steward_config(sid)
    return sw.world_for(sid, index if index is not None else _ownership_index(), cfg.brain_name, starts_left)


# ── uzak host'lar (TODO 2026-10-20 (14); A1 okuma + gözlem, A3 yıkıcı olmayan eylemler) ──────────────────────
#
# Proje kaydının `host` alanı uzak bir `hosts.json` adıysa oturumları o host'ta yaşar: değnekçi onları `/api/status`
# önbelleğinden (`web_hosts` poller'ı, ağa gitmez) ve `/api/term/chat` okumasından görür. Uzak G/Ç'nin TEK arayüzü
# `_remote` (testler sahte host'la değiştirir). `web_hosts` TEMBEL içe aktarılır: grpc/websockets yalnız uzak proje
# varken yüklenir (CLI/mcp süreçlerine taşınmasın).
# A3: uzak hedefe YALNIZ yıkıcı olmayan eylemler (handover, yönerge/cevap/iş iletimi = `/api/term/input`, başlatma)
# ve yalnız `_target`ın uzak kapıları geçilirse (`steward.remote_actions`, kayıtlı + taze host, proje host'u = hedef
# host).
# A4: YIKICI uzak eylemler (durdurma, yeniden açmanın ve restart'ın durdurma adımı) aynı kapılara EK olarak: host
# `exact_target` bildiriyor (yoksa `remote_too_old`, uygulanmaz), ön denetimde taze satırlarda adı TAM eşleşen, çalışan,
# bu kimliğin kayıtlı proje oturumu ("own"; beyin/servis/kayıtsız DEĞİL) ve tick'te host başına en çok
# `MAX_DESTRUCTIVE_PER_HOST` (yarış/yanlış hedef riski: bir host'ta aynı tick'te ikinci durdurma yok). Gönderim
# `POST /api/stop {"name", "exact": true}`: uzak taraf unique_base'e düşmez, tam ad yoksa `no_exact_match`.

REMOTE_STALE_SECONDS = 60.0          # son başarılı poll bundan eskiyse host "kapalı": bayat satırlarla karar verilmez
REMOTE_READ_BUDGET_SECONDS = 10.0    # tick başına uzak okumaların (term/chat) TOPLAM süresi
REMOTE_DESTRUCTIVE_KINDS = ("stop", "respawn", "restart")   # uzakta YALNIZ exact_target + tam ad ön denetimiyle (A4)
MAX_DESTRUCTIVE_PER_HOST = 1             # tick başına bir host'a en çok bu kadar yıkıcı eylem (fazlası ertelenir)
REMOTE_STOP_TIMEOUT_SECONDS = 60.0       # `/api/stop` (uzak tarafta guard_lock + kill_session_and_parent)
REMOTE_INPUT_TIMEOUT_SECONDS = 60.0      # `/api/term/input` (yönerge/cevap/iş sonucu)
REMOTE_HANDOVER_TIMEOUT_SECONDS = 60.0   # `/api/handover` (canlı devir mesajı; kill/respawn yok)
REMOTE_START_TIMEOUT_SECONDS = 120.0     # `/api/start` (uzak spawn)
REMOTE_READY_POLL_SECONDS = 2.0          # uzak başlatmadan sonra hazır bekleme: poller ÖNBELLEĞİNE bakış aralığı (ağ YOK)
REMOTE_BORN_TOLERANCE_SECONDS = 5.0      # facts yaşından hesaplanan başlangıç her okumada gecikme kadar oynar
REMOTE_BACKOFF_TICKS = 3                 # art arda bu kadar tick'te taşıma hatası → host geri çekilmeye girer
REMOTE_BACKOFF_SECONDS = 600.0           # geri çekilme süresi: host "kapalı" sayılır (görünüm yok, eylem yok)
REMOTE_DENIED_DEDUP_SECONDS = 3600.0     # aynı (kimlik, aktör, ad, sebep) uzak reddi bu sürede bir kez loglanır


def _wh():
    from . import web_hosts      # TEMBEL (yukarıdaki not)
    return web_hosts


class _RemoteIO:
    """Uzak host G/Ç'si: `status(host)` poller önbelleği + `last_ok_at` (ağa gitmez; yoksa None), `get(path, host, q)`
    salt okuma proxy'si (`proxy_get`), `post(path, host, body, timeout)` eylem proxy'si (`proxy_action`; yalnız
    `_remote_post` çağırır, A3)."""

    def status(self, host: str) -> Optional[Dict[str, Any]]:
        wh = _wh()
        cached = wh.get_cached(host)
        if cached is None:
            return None
        cached["last_ok_at"] = wh.last_ok_at(host)
        return cached

    def get(self, path: str, host: str, query: Dict[str, str], timeout: Optional[float] = None) -> Tuple[Dict[str, Any], int]:
        return _wh().proxy_get(path, host, query, timeout=timeout)

    def post(self, path: str, host: str, body: Dict[str, Any], timeout: Optional[float] = None) -> Tuple[Dict[str, Any], int]:
        return _wh().proxy_action(path, host, body, timeout=timeout)


_remote = _RemoteIO()


def _host_fresh(st: Optional[Dict[str, Any]], now: Optional[float] = None) -> bool:
    """Önbellek kaydı taze mi: `ok` ve son başarılı poll `REMOTE_STALE_SECONDS` içinde (stale-while-error'ın koruduğu
    bayat satır taze SAYILMAZ)."""
    if not st or not st.get("ok"):
        return False
    last = float(st.get("last_ok_at") or 0.0)
    return bool(last) and ((time.time() if now is None else now) - last) <= REMOTE_STALE_SECONDS


def _fresh_hosts(hosts: Any, now: Optional[float] = None) -> set:
    return {h for h in hosts if _host_fresh(_remote.status(h), now)}


# Host sağlığı (A3), host başına, süreç içi (kimlikler arasında ortak: host aynı makine): `streak` = taşıma hatası alan
# ardışık tick sayısı, `until` = geri çekilme bitişi (epoch), `down` = son bildirilen durum (`remote_unreachable` olayı
# YALNIZ bu değişince yazılır). Geri çekilmedeki host taze SAYILMAZ: görünümü düşer, projeleri `unavailable`, eylem yok.
_HOST_HEALTH: Dict[str, Dict[str, Any]] = {}
_HEALTH_LOCK = threading.Lock()


def _backing_off(host: str, now: float) -> bool:
    with _HEALTH_LOCK:
        return float((_HOST_HEALTH.get(host) or {}).get("until") or 0.0) > now


@dataclasses.dataclass
class _RemoteTick:
    """Bir tick'in uzak host durumu. `statuses`/`fresh`: tick başında BİR KEZ alınan tazelik anlık görüntüsü
    (`unavailable`, görünümler ve eylem ön denetimleri AYNI görüntüyü kullanır; A1'deki iki ayrı okuma arasındaki yarış
    kapanır). `failed`/`succeeded`: bu tick'te eylem gönderilen host'lar (devre kesici + geri çekilme sayacı).
    `destructive`: {host: bu tick'te gönderilen yıkıcı eylem sayısı} (`MAX_DESTRUCTIVE_PER_HOST`, A4)."""
    now: float
    statuses: Dict[str, Optional[Dict[str, Any]]] = dataclasses.field(default_factory=dict)
    fresh: frozenset = frozenset()
    failed: set = dataclasses.field(default_factory=set)
    succeeded: set = dataclasses.field(default_factory=set)
    destructive: Dict[str, int] = dataclasses.field(default_factory=dict)

    def blocked(self, host: str) -> bool:
        """Devre kesici: bu tick'te host'a ilk taşıma hatasından sonra kalan eylemler DENENMEZ."""
        return host in self.failed

    def refresh(self, host: str) -> None:
        """Host'un durumunu bu tick'te BİZ değiştirdik (durdurma/başlatma): görüntünün o host'luk kısmı önbellekten
        yenilenir (ağa gitmez). Yoksa sonraki adım (yeniden açmada başlatma, yönerge) tick başındaki "çalışıyor"
        satırını görüp kapanmış oturumu açık sanırdı ya da ikinci bir başlatma gönderirdi."""
        st = _remote.status(host)
        self.statuses[host] = st
        t = time.time()
        ok = _host_fresh(st, t) and not _backing_off(host, t)
        self.fresh = frozenset(self.fresh | {host}) if ok else frozenset(self.fresh - {host})


def _remote_snapshot(hosts: Any, now: Optional[float] = None) -> _RemoteTick:
    """`hosts`un poller önbelleği kayıtları (ağa gitmez) + taze olanlar (geri çekilmedekiler hariç)."""
    now = time.time() if now is None else now
    statuses = {h: _remote.status(h) for h in sorted({x for x in hosts if x})}
    fresh = frozenset(h for h, st in statuses.items() if _host_fresh(st, now) and not _backing_off(h, now))
    return _RemoteTick(now=now, statuses=statuses, fresh=fresh)


def _with_availability(world: sw.World, cfg: sw.Config, now: Optional[float] = None,
                       rt: Optional[_RemoteTick] = None) -> sw.World:
    """`world.unavailable`: host'u taze olmayan (kapalı, bayat ya da geri çekilmede) uzak projeler. act kipinde
    `steward.remote_actions` kapalıysa TÜM uzak projeler: başlatma planına girip her tick reddedilmesinler, yerel
    başlatma bütçesini yemesinler (observe'da `would:start` görünmeye devam eder). Uzak proje yoksa `world` aynen döner.
    `rt` verilirse tazelik onun anlık görüntüsünden (tick başında bir kez)."""
    if not world.hosts:
        return world
    fresh = rt.fresh if rt is not None else _fresh_hosts(set(world.hosts.values()), now)
    down = {p for p, h in world.hosts.items() if h not in fresh}
    if cfg.mode != "observe" and not cfg.remote_actions:
        down |= set(world.hosts)
    return dataclasses.replace(world, unavailable=frozenset(down))


def _remote_tick_done(rt: _RemoteTick, paths: Any) -> None:
    """Tick sonu: host başına geri çekilme sayacı. Taşıma hatası alan tick `streak`i artırır (`REMOTE_BACKOFF_TICKS`a
    varınca `REMOTE_BACKOFF_SECONDS` geri çekilme), hatasız başarılı tick sıfırlar; eylem gönderilmeyen tick sayılmaz.
    `remote_unreachable` olayı YALNIZ durum değişiminde (`state: down|up`), telefon bildirimi YOK."""
    changes: List[Tuple[str, str, int]] = []
    with _HEALTH_LOCK:
        for h in sorted(rt.failed | rt.succeeded):
            hh = _HOST_HEALTH.setdefault(h, {"streak": 0, "until": 0.0, "down": False})
            if h in rt.failed:
                hh["streak"] = int(hh["streak"]) + 1
                if hh["streak"] >= REMOTE_BACKOFF_TICKS:
                    hh["until"] = rt.now + REMOTE_BACKOFF_SECONDS
                    if not hh["down"]:
                        hh["down"] = True
                        changes.append((h, "down", hh["streak"]))
            else:
                hh["streak"], hh["until"] = 0, 0.0
                if hh["down"]:
                    hh["down"] = False
                    changes.append((h, "up", 0))
    for h, state, streak in changes:
        extra = {"backoff_seconds": REMOTE_BACKOFF_SECONDS, "ticks": streak} if state == "down" else {}
        sw.log_event("remote_unreachable", paths=paths, host=h, state=state, **extra)


def _is_transport_error(host: str, parsed: Any, status: int) -> bool:
    """Taşıma (host düzeyi) hatası mı: `proxy_action`ın ağ/zaman aşımı/HTTP-gövdesiz yanıt kalıbı (`<host> unreachable:`)
    ya da ağ geçidi 502/503/504. 404 (eski host, uç yok) ve uygulama düzeyi ret (`ok: false` gövdesi) taşıma hatası
    DEĞİLDİR: devre kesiciyi açmaz."""
    if status in (502, 503, 504):
        return True
    return (status in (0, 200) and isinstance(parsed, dict) and parsed.get("ok") is False
            and str(parsed.get("error") or "").startswith(f"{host} unreachable:"))


def _remote_post(host: str, path: str, body: Dict[str, Any], timeout: float,
                 rt: Optional[_RemoteTick] = None) -> Dict[str, Any]:
    """Uzak eylemin TEK gönderim yolu. Gövdede `host` OLMAZ (hedef host'u `proxy_action` seçer ve gidene `local`
    zorlar: ikinci sıçrama yapısal olarak imkansız). Tick içinde (`rt`) devre kesici: host'a bu tick'te taşıma hatası
    alınmışsa istek ATILMAZ (`host_down`). Dönen sözlük uzak yanıt; 404 `remote_not_found` olarak işaretlenir."""
    if "host" in body:
        raise ValueError("remote action body must not carry 'host'")
    if rt is not None and rt.blocked(host):
        return {"ok": False, "error": "host_down", "host": host}
    try:
        parsed, status = _remote.post(path, host, dict(body), timeout=timeout)
    except Exception as e:      # sahte/gerçek G/Ç'nin beklenmedik istisnası da taşıma hatası sayılır
        parsed, status = {"ok": False, "error": f"{host} unreachable: {e!r}"}, 0
    transport = _is_transport_error(host, parsed, status)
    if rt is not None:
        (rt.failed if transport else rt.succeeded).add(host)
    if status == 404:
        return {"ok": False, "error": f"remote endpoint not found on {host}: {path}", "code": "remote_not_found",
                "host": host}
    out = dict(parsed) if isinstance(parsed, dict) else {"ok": False, "error": f"bad response from {host}"}
    if transport:
        out.update(ok=False, code="host_down", host=host)
    return out


def _locate(name: str, projects: Dict[str, sw.Project], world: Optional[sw.World] = None) -> Tuple[str, Optional[sw.Project]]:
    """Oturum/proje adı → (host, kimliğin projesi). Host GLOBAL çözümden (`World.resolve` + indeksin `hosts`u; kayıt
    `host`u da uzaksa o): "" = yerel. Proje bu kimliğin kaydında değilse None."""
    world = world or _world()
    kind, key = world.resolve(name)
    if kind != "project":
        return "", None
    p = projects.get(key)
    return (world.host_of(key) or (p.host if p is not None else "")), p


def _name_host(name: str) -> str:
    """Ad uzak host'lu bir projeye (herhangi bir kimliğin) çözülüyorsa host'u, değilse "". Yerel dosya sistemi
    korumalarının (`_project_cwd`, kartlar, fikir aktarımı) tek sorusu."""
    try:
        return _locate(name, {})[0]
    except Exception:       # bozuk ayar/indeks: korumayı bozmasın, yerel say
        return ""


def _remote_last_assistant(targets: List[Tuple[str, str]], budget: float = REMOTE_READ_BUDGET_SECONDS) -> Dict[Tuple[str, str], str]:
    """{(host, ad): son asistan metni}: `GET /api/term/chat?mode=last`, paralel, TOPLAM `budget` sn. Süresi dolan ya da
    hata veren okuma sonuçta YOK (= "" bilinmiyor); süresi dolan iş parçacığı arka planda biter, sonucu atılır."""
    out: Dict[Tuple[str, str], str] = {}
    if not targets:
        return out
    lock = threading.Lock()
    deadline = time.monotonic() + budget

    def work(host: str, name: str) -> None:
        try:
            parsed, _status = _remote.get("/api/term/chat", host, {"name": name, "mode": "last"}, timeout=budget)
        except Exception:
            return
        if isinstance(parsed, dict) and parsed.get("ok") and parsed.get("supported"):
            with lock:
                out[(host, name)] = str(parsed.get("assistant") or "")

    threads = [threading.Thread(target=work, args=t, daemon=True, name="steward-remote-read") for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    with lock:
        return dict(out)


def _remote_view(r: Dict[str, Any], host: str, now: float) -> sw.SessionView:
    """Uzak `/api/status` satırı → görünüm. Bağlam = satırın `context.tokens` (yoksa None ve satır sayısı da None: yaşı
    bilinmeyen oturum satır eşiğiyle devre sokulmasın); son aktivite = `now - cache.age` (göreli, saat kayması yok; yoksa
    0 = bilinmiyor); başlangıç bilinmiyor (0); alt ajan durumu bilinmiyor (`subagent_unknown`)."""
    ctx = r.get("context") if isinstance(r.get("context"), dict) else {}
    cache = r.get("cache") if isinstance(r.get("cache"), dict) else {}
    tokens = ctx.get("tokens")
    tokens = int(tokens) if isinstance(tokens, (int, float)) and not isinstance(tokens, bool) and tokens > 0 else None
    age = cache.get("age")
    v = sw.SessionView(
        name=str(r.get("name") or ""), running=bool(r.get("running")), cwd=r.get("cwd") or "",
        cli=r.get("cli") or DEFAULT_CLI, blueprint=r.get("blueprint") if r.get("instance") else None,
        busy=r.get("busy"), history_size=r.get("history_size") if tokens is not None else None,
        needs_ho=r.get("needs_ho"), tmux=bool(r.get("tmux")), model=str(r.get("model") or ""),
        context_tokens=tokens, host=host, subagent_unknown=True)
    if v.running and isinstance(age, (int, float)) and not isinstance(age, bool) and age >= 0:
        v.last_activity = now - float(age)
    return v


# Uzak host yetenek önbelleği (A2): host -> (yoklama zamanı, {"api": int, "capabilities": [..]}). `api` 0 = eski host
# (`/api/session/facts` 404): started/subagent bilinmez, yalnız status + term/chat yolu; 10 dk'da bir yeniden yoklanır.
REMOTE_CAPS_RECHECK_SECONDS = 600.0
_CAPS: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CAPS_LOCK = threading.Lock()


def _caps_put(host: str, api: int, capabilities: Any, now: float) -> Dict[str, Any]:
    caps = {"api": int(api), "capabilities": [str(c) for c in (capabilities or [])]}
    with _CAPS_LOCK:
        _CAPS[host] = (now, caps)
    return caps


def _caps_cached(host: str, now: float) -> Optional[Dict[str, Any]]:
    """Önbellekteki yetenek ya da None (hiç yok / api 0 kaydı 10 dk'dan eski: yeniden yoklanmalı)."""
    with _CAPS_LOCK:
        hit = _CAPS.get(host)
    if hit is None:
        return None
    if hit[1]["api"] == 0 and now - hit[0] >= REMOTE_CAPS_RECHECK_SECONDS:
        return None
    return dict(hit[1])


def _probe_facts(host: str, names: List[str], budget: float, now: Optional[float] = None
                 ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Host'un `GET /api/session/facts` ucu: (yetenek, {ad: olgular}). Tek istek hem yetenek yoklaması hem veri okumasıdır.
    404 = eski host: önbelleğe api 0 yazılır, taşıma hatası SAYILMAZ. Ağ/zaman aşımı/başka HTTP hatası: önbelleğe
    YAZILMAZ (geçici arıza yeteneği silmesin), yetenek önbellekteki (yoksa api 0) döner ve olgu boştur. Önbellekte taze
    api 0 kaydı varsa hiç istek atılmaz."""
    now = time.time() if now is None else now
    cached = _caps_cached(host, now)
    if cached is not None and cached["api"] == 0:
        return cached, {}
    try:
        parsed, status = _remote.get("/api/session/facts", host, {"names": ",".join(names)}, timeout=budget)
    except Exception:
        return cached or {"api": 0, "capabilities": []}, {}
    if status == 404:
        return _caps_put(host, 0, [], now), {}
    if status == 200 and isinstance(parsed, dict) and parsed.get("ok") is not False \
            and isinstance(parsed.get("api"), int) and not isinstance(parsed.get("api"), bool):
        caps = _caps_put(host, parsed["api"], parsed.get("capabilities"), now)
        sess = parsed.get("sessions")
        return caps, (sess if isinstance(sess, dict) else {})
    return cached or {"api": 0, "capabilities": []}, {}


def host_capabilities(host: str, now: Optional[float] = None, budget: float = 5.0) -> Dict[str, Any]:
    """Host başına {"api", "capabilities"}: önbellekten, yoksa (ya da api 0 kaydı 10 dk'dan eskiyse) ad listesiz facts
    yoklamasıyla. Ağ hatasında önbelleğe yazılmaz; bilinmeyen = api 0, boş yetenek."""
    now = time.time() if now is None else now
    cached = _caps_cached(host, now)
    if cached is not None:
        return cached
    return _probe_facts(host, [], budget, now)[0]


def _apply_facts(v: sw.SessionView, f: Dict[str, Any], now: float, row_history: Any) -> None:
    """Uzak olguları görünüme işler: başlangıç (yaş saniyesinden, saat kayması yok), alt ajan (gerçek değer, artık
    bilinmiyor DEĞİL), bağlam, son asistan metni."""
    age = f.get("started_age_s")
    if isinstance(age, (int, float)) and not isinstance(age, bool) and age >= 0:
        v.started_at = now - float(age)
    v.subagent_active = f.get("subagent_active") is True
    v.subagent_unknown = False
    tok = f.get("context_tokens")
    if isinstance(tok, (int, float)) and not isinstance(tok, bool) and tok > 0:
        v.context_tokens = int(tok)
        if v.history_size is None:
            v.history_size = row_history
    v.last_assistant = str(f.get("last_assistant") or "")


def _remote_views(world: sw.World, now: Optional[float] = None, rt: Optional[_RemoteTick] = None) -> List[sw.SessionView]:
    """Uzak projelerin (tüm kimliklerin: `max_active_total` sayımı için) taze host'lardaki oturum görünümleri.
    Satır seçimi `sw.select_rows` (saf). Zenginleştirme: host `session_facts` bildiriyorsa host başına TEK facts isteği
    (started/subagent/bağlam/son asistan); bildirmeyen (eski) host ve olgusu gelmeyen oturum için A1 yolu (term/chat).
    Tüm uzak okumalar TOPLAM `REMOTE_READ_BUDGET_SECONDS` içinde. `rt` verilirse satırlar ve tazelik onun anlık
    görüntüsünden (tick'in `unavailable`ı ile AYNI); verilmezse önbellek şimdi okunur (geri çekilmedeki host taze değil)."""
    hosts = sorted(set(world.hosts.values()))
    if not hosts:
        return []
    if rt is None:
        rt = _remote_snapshot(hosts, now)
    now = rt.now if now is None else now
    fresh: set = set()
    rows: List[Dict[str, Any]] = []
    for h in hosts:
        st = rt.statuses.get(h)
        if h not in rt.fresh or not st:
            continue
        fresh.add(h)
        rows.extend(dict(r, host=h) for r in (st.get("sessions") or []) if isinstance(r, dict))
    selected = sw.select_rows(rows, world, fresh)
    views = [_remote_view(r, r["host"], now) for r in selected]
    history = {(r["host"], str(r.get("name") or "")): r.get("history_size") for r in selected}
    deadline = time.monotonic() + REMOTE_READ_BUDGET_SECONDS
    running: Dict[str, List[sw.SessionView]] = {}
    for v in views:
        if v.running:
            running.setdefault(v.host, []).append(v)
    got: Dict[str, Dict[str, Any]] = {}
    lock = threading.Lock()

    def probe(host: str) -> None:
        try:
            caps, facts = _probe_facts(host, [v.name for v in running[host]], max(0.5, deadline - time.monotonic()), now)
        except Exception:
            return
        if "session_facts" in caps["capabilities"]:
            with lock:
                got[host] = facts

    threads = [threading.Thread(target=probe, args=(h,), daemon=True, name="steward-remote-facts") for h in running]
    for t in threads:
        t.start()
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    with lock:
        enriched = {h: dict(f) for h, f in got.items()}
    fallback: List[Tuple[str, str]] = []
    for v in views:
        if not v.running:
            continue
        f = (enriched.get(v.host) or {}).get(v.name)
        if isinstance(f, dict) and f.get("running") is not False:
            _apply_facts(v, f, now, history.get((v.host, v.name)))
        else:
            fallback.append((v.host, v.name))
    left = deadline - time.monotonic()
    texts = _remote_last_assistant(fallback, budget=left) if fallback and left > 0 else {}
    for v in views:
        if (v.host, v.name) in texts:
            v.last_assistant = texts[(v.host, v.name)]
    return views


def configure(**callbacks: Callable[..., Any]) -> None:
    """`web.py` `run()`'da verir: status_payload(), fleet_status(), start(name, model, effort, fresh, lang),
    stop(name, lang), handover(name, lang), register_project(name, cwd, model, cli, lang)."""
    _ACTIONS.update(callbacks)


def _act(name: str, *args: Any, **kw: Any) -> Any:
    fn = _ACTIONS.get(name)
    if fn is None:
        return {"ok": False, "error": f"steward engine not configured ({name})"}
    return fn(*args, **kw)


def _remember(action: sw.Action, result: Any, ctx: Optional[StewardContext] = None, host: str = "") -> None:
    """Uygulanan eylemin kaydı. `host`: uzak projeye yapılan eylemde host adı (verilmezse uzak sonucun `host`u; yerelde
    alan HİÇ yazılmaz: kayıt biçimi eskisiyle aynı)."""
    ctx = ctx or _ctx()
    if not host and isinstance(result, dict):
        host = sw.normalize_host(result.get("host"))
    entry = {"ts": time.time(), "kind": action.kind, "name": action.name, "reason": action.reason,
             "ok": bool(result.get("ok")) if isinstance(result, dict) else bool(result),
             "detail": (result.get("error") or result.get("detail") or "") if isinstance(result, dict) else ""}
    if host:
        entry["host"] = host
    ctx.recent.insert(0, entry)
    del ctx.recent[RECENT_ACTIONS:]
    sw.log_event("action", paths=ctx.paths, kind=action.kind, name=action.name, reason=action.reason,
                 ok=entry["ok"], detail=entry["detail"], **({"host": host} if host else {}))


def _remember_dry(action: sw.Action, ctx: Optional[StewardContext] = None, host: str = "") -> None:
    """observe kipi: eylem UYGULANMADI. `recent`e `dry=True` ile, log'a `would:<kind>` olayı olarak yazılır. `host`:
    hedef uzak bir projedeyse host adı (yerelde alan HİÇ yazılmaz: kayıt biçimi eskisiyle aynı)."""
    ctx = ctx or _ctx()
    detail = f"{len(action.payload.get('items') or [])} madde" if action.kind == "tour" else str(action.payload.get("text") or "")[:200]
    if action.kind == "deliver_job":
        detail = f"job {action.payload.get('service')}#{action.payload.get('job_id')} {action.payload.get('stage')}"
    entry = {"ts": time.time(), "kind": action.kind, "name": action.name, "reason": action.reason,
             "ok": True, "dry": True, "detail": detail}
    if host:
        entry["host"] = host
    ctx.recent.insert(0, entry)
    del ctx.recent[RECENT_ACTIONS:]
    extra = {"question_id": action.payload["question_id"]} if action.payload.get("question_id") else {}
    if action.payload.get("job_id") is not None:
        extra["job_id"] = action.payload["job_id"]
    if host:
        extra["host"] = host
    sw.log_event("would:" + action.kind, paths=ctx.paths, name=action.name, reason=action.reason, detail=detail, **extra)


def _brain_dry(kind: str, data: Dict[str, Any], name: str, sid: str = "default", host: str = "") -> Optional[Dict[str, Any]]:
    """observe kipinde BEYNİN (`actor: brain`, MCP aracı) oturuma dokunan çağrıları da uygulanmaz: aynı `would:`
    kaydı düşer, beyne başarılı-ama-kuru yanıt döner. İnsanın elle çağırdığı CLI/API (`actor` yok) her zaman uygulanır."""
    if data.get("actor") != "brain" or steward_config(sid).mode != "observe":
        return None
    _remember_dry(sw.Action(kind, name, "brain: " + str(data.get("reason") or "")[:200], {"text": str(data.get("text") or "")}),
                  _ctx(sid), host=host)
    out = {"ok": True, "dry": True, "note": f"observe mode: recorded as would:{kind}, not applied"}
    if host:
        out["host"] = host
    return out


# Uzak hedefin "şu an uygulanamaz" redleri: observe kipindeki beyne red yerine kuru (`would:`) yanıt döner (nasılsa
# hiçbir şey uygulanmayacaktı). Host uyuşmazlığı/bilinmeyen host gerçek hatadır, kuruya çevrilmez.
_DRYABLE_REMOTE = ("remote_disabled", "host_down")


def _gate(name: str, data: Dict[str, Any], kind: str, sid: str = "default") -> Optional[Dict[str, Any]]:
    """HTTP eylem uçlarının ortak kapısı: `_target` (istekteki opsiyonel `host` ile) sonra `_brain_dry`. Uzak hedef
    "şu an uygulanamaz" sebebiyle (`_DRYABLE_REMOTE`) reddedildiyse ve çağıran observe kipindeki beyinse red yerine
    `would:<kind>` (host alanlı) kaydı döner: beyin observe'da yerelde de kuru yanıt alıyor. İzinli uzak hedefte de
    observe beyninin kuru kaydı host alanını taşır."""
    actor = str(data.get("actor") or "")
    denied = _target(name, actor, kind=kind, sid=sid, host=data.get("host"))
    if denied is not None:
        if denied.get("code") in _DRYABLE_REMOTE and actor == "brain":
            return _brain_dry(kind, data, name, sid, host=str(denied.get("host") or "")) or denied
        return denied
    host = (sw.normalize_host(data.get("host")) or _name_host(name)) if actor == "brain" else ""
    return _brain_dry(kind, data, name, sid, host=host)


def _service_session(name: str) -> str:
    """Oturum adı kayıtlı bir pasif servise (`services.json`, tam ad ya da önek) çözülüyorsa servis adı, değilse ""."""
    for s, rec in sj.load_services().items():
        if name == s or (rec.get("match") != "exact" and name.startswith(s)):
            return s
    return ""


# Uzak red log'u tekrarsız: {(kimlik, aktör, ad, sebep): son log zamanı}. act kipinde `remote_actions` kapalıyken motor
# aynı reddi her tick üretir (devir/cevap iletimi planlanmaya devam eder); log'a saatte bir düşer, yanıt her seferinde döner.
_DENIED_LOGGED: Dict[Tuple[str, str, str, str], float] = {}
_DENIED_LOCK = threading.Lock()


def _log_remote_denied(sid: str, actor: str, kind: str, name: str, host: str, code: str,
                       event: str = "target_denied") -> None:
    """Uzak red olayı, (kimlik, aktör, ad, sebep) başına `REMOTE_DENIED_DEDUP_SECONDS`te bir. `event`: olay adı
    (`remote_too_old` kendi adıyla düşer: eski host'un yükseltilmesi gerektiğini log'da aramak kolay olsun)."""
    key, now = (sid, actor or "human", name, code), time.time()
    with _DENIED_LOCK:
        if now - _DENIED_LOGGED.get(key, 0.0) < REMOTE_DENIED_DEDUP_SECONDS:
            return
        _DENIED_LOGGED[key] = now
    sw.log_event(event, paths=sid, actor=actor or "human", kind=kind, name=name, host=host, code=code)


def _remote_denied(name: str, actor: str, kind: str, sid: str, want: str, proj_host: str,
                   rt: Optional[_RemoteTick] = None) -> Optional[Dict[str, Any]]:
    """Uzak hedef kapıları; None = izinli. Sıra: bilinmeyen host → host uyuşmazlığı (istenen host ile adın çözüldüğü
    projenin host'u; "" = yerel) → `remote_actions` kapalı → host taze değil (kapalı, bayat ya da geri çekilmede; `rt`
    verilirse tick'in anlık görüntüsü, yoksa önbellek şimdi). Yerel hedef (ikisi de "") hiç buraya gelmez. Yıkıcı
    türlerin EK koşulları (exact_target, tam ad + "own" ön denetimi, host başına tick bütçesi) gönderim anında
    `_remote_stop`ta (A4): kapı yalnız hedefin kimliğine/host'una bakar, satırın o anki durumuna değil."""
    host = want or proj_host
    if want and hosts_mod.get_host(want) is None:
        code, err = "unknown_host", f"target denied: unknown host {want!r} (not in hosts.json)"
    elif want != proj_host:
        code, err = "host_mismatch", (f"target denied: {name!r} belongs to a project on {proj_host or 'local'!r}, "
                                      f"not {want or 'local'!r}")
    elif not steward_config(sid).remote_actions:
        code, err = "remote_disabled", "target denied: remote actions are disabled (steward.remote_actions is off)"
    elif not (host in rt.fresh if rt is not None else
              (_host_fresh(_remote.status(host)) and not _backing_off(host, time.time()))):
        code, err = "host_down", f"target denied: host {host!r} is unreachable or stale right now"
    else:
        return None
    _log_remote_denied(sid, actor, kind, name, host, code)
    return {"ok": False, "error": err, "code": code, "host": host}


def _target(name: str, actor: str, projects: Optional[Dict[str, sw.Project]] = None,
            kind: str = "", sid: str = "default", world: Optional[sw.World] = None,
            host: Any = None, rt: Optional[_RemoteTick] = None) -> Optional[Dict[str, Any]]:
    """Oturuma dokunan yolların TEK kapısı (docs/multi-steward-plan.md K5). `None` = izinli, aksi halde red yanıtı.
    Beyin (`actor: brain`, MCP) ve motor (`actor: engine`, `_apply`) YALNIZ KENDİ kimliğinin (`sid`) beyin oturumunu ve
    kayıtlı proje oturumlarını hedefleyebilir: başka kimliğin projesi/beyni, servis, çakışmalı proje ve kayıtsız (ad hoc)
    oturum reddedilir (çözüm global, `World.session_class`). İnsanın CLI/panel çağrısı (`actor` yok): `default` bağlamında
    kısıtsız (kayıtsız oturuma da yazabilir, bugünkü ad hoc davranış); diğer bağlamlarda yalnız o kimliğin kendi
    projeleri/beyni (plan (e) insan geçidi).

    Host (uzak proje): verilmezse adın çözüldüğü projenin host'u (beyin/motor host vermez: proje kaydından); verilirse
    ("local" = yerel) o host'la aynı olmalı, aksi halde red (insan default bağlamında bile: `host=local` ile uzaktaki
    `oiso` projesinin yerel adaşına, `host=ulak31` ile kayıtsız uzak oturuma dokunulmaz). Uzak hedef ayrıca
    `steward.remote_actions` açık, host kayıtlı ve taze (`rt`: tick'in anlık görüntüsü) ister (`_remote_denied`; A3);
    yıkıcı türün ek koşulları gönderim anında (`_remote_stop`, A4). Kimlik reddi (başka kimliğin projesi vb.) uzak
    reddinden önce gelir."""
    svc = _service_session(name)
    if svc:     # pasif servis (varaka): HİÇBİR eylemin hedefi olamaz (insan dahil; `steward service` kaydı watch/passive)
        sw.log_event("target_denied", paths=sid, actor=actor or "human", kind=kind, name=name, service=svc)
        return {"ok": False, "error": "target denied: passive shared service session"}
    if projects is None:
        projects = sw.load_projects(sid)
    if world is None:
        world = _world(sid)
    proj_host = _locate(name, projects, world)[0] if sw.valid_name(name) else ""
    want = proj_host if host is None or host == "" else sw.normalize_host(host)    # verilmeyen host = projenin host'u

    def remote() -> Optional[Dict[str, Any]]:      # kimlik kapısı geçildiyse: yerel hedef serbest, uzak hedef kapılardan
        return _remote_denied(name, actor, kind, sid, want, proj_host, rt) if (want or proj_host) else None

    if actor not in ("brain", "engine") and sid == "default":
        return remote()
    if name == steward_config(sid).brain_name:
        return remote()
    if sw.valid_name(name):
        if _project_for_session(name, projects, world) is not None:
            return remote()
    sw.log_event("target_denied", paths=sid, actor=actor or "human", kind=kind, name=name)
    return {"ok": False, "error": "target denied: not the brain session or a registered steward project"}


# ── telefon bildirimi (ntfy) ──────────────────────────────────────────────────

def notify_phone(text: str, click: str = "", title: str = "claudeops degnekci", topic: str = "") -> bool:
    """`py/cops service notify` ile kurulmuş ntfy topic'i varsa oraya POST (arka planda, best-effort).
    Yoksa False — soru yine de `questions.json`'da bekler, panel/CLI'dan görülür. `click`: bildirime dokununca
    açılacak adres (ntfy `Click` başlığı; soru sayfası `/q/<id>?k=`). `topic`: kimliğe özel topic (boş = ortak
    `ntfy_topic.txt`)."""
    topic = (topic or "").strip()
    if not topic:
        try:
            with open(NTFY_TOPIC_FILE, encoding="utf-8") as f:
                topic = f.read().strip()
        except OSError:
            return False
    if not topic:
        return False

    def _post() -> None:
        try:
            headers = {"Title": title}
            if click:
                headers["Click"] = click
            req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=text.encode("utf-8"),
                                         headers=headers, method="POST")
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:
            diag_log("steward_notify_failed", error=str(e))

    threading.Thread(target=_post, daemon=True, name="steward-ntfy").start()
    return True


def _ask_prefix(project: str, sid: str) -> str:
    """ntfy önek: uzak projede `[proje@host]` (hangi makinedeki oturum olduğu telefondan okunsun)."""
    return sw.ask_prefix(project, sid, _name_host(project) if project else "")


def _notify(cfg: sw.Config, text: str, click: str = "") -> bool:
    """Kimliğe göre ntfy: default için `notify_phone(text[, click])` BUGÜNKÜ çağrı (başlık/topic/gövde aynı); diğer
    kimlikte başlık `claudeops degnekci:<sid>`, `ntfy_topic` doluysa o topic, aksi halde ortak topic. Gövde önekini
    (`[<sid>/<proje>]`) çağıran kurar (`sw.ask_prefix`)."""
    kw: Dict[str, Any] = {"click": click} if click else {}
    if cfg.sid != "default":
        kw["title"] = f"claudeops degnekci:{cfg.sid}"
        if cfg.ntfy_topic:
            kw["topic"] = cfg.ntfy_topic
    return notify_phone(text, **kw)


def public_base() -> str:
    """Telefondan ulaşılabilen panel adresi: `tunnel_url.txt` (quick tunnel her restart'ta yeni URL yazar) ya da "".
    Soru bağlantısı panel token'ını DEĞİL sorunun kendi anahtarını taşır (`steward.question_link`)."""
    try:
        with open(TUNNEL_URL_FILE, encoding="utf-8") as f:
            url = f.read().strip()
    except OSError:
        return ""
    return url if url.startswith("http") else ""


# ── proje klasörü yardımcıları ────────────────────────────────────────────────

def _project_cwd(name: str) -> str:
    """Projenin YEREL klasörü. Ad uzak host'lu bir projeye çözülüyorsa "" (uzak projede yerel dosya sistemi ASLA
    okunmaz/yazılmaz: aynı yolda yerel bir klasör, roster satırı ya da adaş oturum o projenin değildir)."""
    if _name_host(name):
        return ""
    fleet = _act("fleet_status") or {}
    info = fleet.get(name) if isinstance(fleet, dict) else None
    if info and info.get("cwd"):
        return info["cwd"]
    rec = inst_mod.get_instance(name)
    if rec and rec.get("cwd"):
        return rec["cwd"]
    for s in find_sessions(measure_cpu=False):
        if s.name == name and s.cwd:
            return s.cwd
    return ""


def _project_cli(name: str) -> str:
    fleet = _act("fleet_status") or {}
    info = fleet.get(name) if isinstance(fleet, dict) else None
    if info and info.get("cli") in PROVIDERS:
        return info["cli"]
    rec = inst_mod.get_instance(name)
    if rec and rec.get("cli") in PROVIDERS:
        return rec["cli"]
    return DEFAULT_CLI


def _read_head(cwd: str, rel: str, max_chars: int = DOC_HEAD_CHARS) -> str:
    try:
        with open(os.path.join(cwd, rel), encoding="utf-8", errors="replace") as f:
            return f.read(max_chars + 1)[:max_chars]
    except OSError:
        return ""


def _git_short(cwd: str) -> str:
    if not cwd or not os.path.isdir(os.path.join(cwd, ".git")):
        return ""
    try:
        r = subprocess.run(["git", "-C", cwd, "status", "--short", "--branch"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().splitlines()
        return "\n".join(lines[:20])
    except Exception:
        return ""


def _safe_project_file(cwd: str, rel: str) -> Optional[str]:
    """Proje klasörü içinde kalan, mutlak hale getirilmiş yol — dışarı çıkıyorsa None (`files.py` ilkesi)."""
    if not cwd or not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return None
    root = os.path.realpath(cwd)
    full = os.path.realpath(os.path.join(root, rel))
    if full != root and not full.startswith(root + os.sep):
        return None
    return full


# ── uzak projenin okuma yüzeyi (A5): context/file/state; ağ yalnız host-routed salt-okuma uçlarına ───────────

REMOTE_GIT_UNKNOWN = "remote: bilinmiyor"       # uzak klasörün git durumu okunmaz (yerel `git` uzak yola bakamaz)


def _remote_running_listing(world: Optional[sw.World]) -> List[Dict[str, Any]]:
    """Taze host'lardaki ÇALIŞAN uzak proje oturumları (`http_state.running` ve çalışıyor sayımı): yalnızca poller
    önbelleği (ağa gitmez), satır seçimi `sw.select_rows` (yerel adaş, uzak beyin/servis/kayıtsız satır düşer). Her
    öğede `host`. Dünya ya da uzak proje yoksa boş."""
    if world is None or not world.hosts:
        return []
    now = time.time()
    fresh: set = set()
    rows: List[Dict[str, Any]] = []
    for h in sorted(set(world.hosts.values())):
        st = _remote.status(h)
        if not _host_fresh(st, now) or _backing_off(h, now):
            continue
        fresh.add(h)
        rows.extend(dict(r, host=h) for r in (st.get("sessions") or []) if isinstance(r, dict) and r.get("running"))
    return [{"name": r.get("name"), "cwd": r.get("cwd") or "", "cli": r.get("cli") or "", "model": r.get("model") or "",
             "host": r["host"]} for r in sw.select_rows(rows, world, fresh)]


def remote_health(hosts: Any, now: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """Host başına sağlık özeti (panel rozeti + `steward status`): `state` = ok (taze) | down (kapalı/bayat) | backoff
    (geri çekilmede); `api` = yetenek önbelleğindeki sürüm (0 eski host, None henüz yoklanmadı); `age` = son başarılı
    poll'dan beri saniye (None: hiç). Yalnız önbelleğe bakar, ağa gitmez."""
    now = time.time() if now is None else now
    out: Dict[str, Dict[str, Any]] = {}
    for h in sorted({x for x in hosts if x}):
        st = _remote.status(h)
        last = float((st or {}).get("last_ok_at") or 0.0)
        state = "backoff" if _backing_off(h, now) else ("ok" if _host_fresh(st, now) else "down")
        caps = _caps_cached(h, now)
        out[h] = {"state": state, "api": caps["api"] if caps else None, "age": int(now - last) if last else None}
    return out


def _remote_cwd(host: str, name: str) -> str:
    """Uzak oturumun klasörü: host'un TAZE önbelleğinde (çalışan ya da kapalı satır) adı TAM `name` olan satırdan; yoksa
    ""."""
    st = _remote.status(host)
    if not _host_fresh(st) or _backing_off(host, time.time()):
        return ""
    for key in ("sessions", "closed"):
        for r in (st.get(key) or []):
            if isinstance(r, dict) and r.get("name") == name and r.get("cwd"):
                return str(r["cwd"])
    return ""


def _remote_file_head(host: str, name: str, path: str, max_chars: int, budget: float) -> Tuple[str, bool, bool]:
    """Host-routed `GET /api/files/read` (name = oturum adı, path = MUTLAK uzak yol): (metin, kesildi mi, okundu mu).
    Ağ/zaman aşımı/uygulama hatası fırlatmaz: okundu=False (boş metin). Yerel dosya sistemine ASLA bakılmaz."""
    if budget <= 0.2:
        return "", False, False
    try:
        parsed, _status = _remote.get("/api/files/read", host, {"name": name, "path": path}, timeout=budget)
    except Exception:
        return "", False, False
    if not isinstance(parsed, dict) or not parsed.get("ok") or not isinstance(parsed.get("text"), str):
        return "", False, False
    text = parsed["text"]
    return text[:max_chars], len(text) > max_chars, True


def _remote_last_exchange(host: str, name: str, budget: float) -> Dict[str, Any]:
    """Uzak oturumun son konuşması: `GET /api/term/chat?mode=last` → {"user", "assistant"}; okunamazsa {} (bilinmiyor)."""
    if budget <= 0.2:
        return {}
    try:
        parsed, _status = _remote.get("/api/term/chat", host, {"name": name, "mode": "last"}, timeout=budget)
    except Exception:
        return {}
    if not isinstance(parsed, dict) or not parsed.get("ok") or not parsed.get("supported"):
        return {}
    return {"user": str(parsed.get("user") or ""), "assistant": str(parsed.get("assistant") or "")}


def _remote_read_context(host: str, name: str, want_docs: bool, docs: Tuple[str, ...] = DOCS,
                         head: int = DOC_HEAD_CHARS) -> Dict[str, Any]:
    """`http_context`in uzak karşılığı: son konuşma + (istenirse) belge başları, TOPLAM `REMOTE_READ_BUDGET_SECONDS`.
    Hata/zaman aşımı boş döner, fırlatmaz. Çıktı: {"last_exchange", "docs", "remote_cwd"}."""
    deadline = time.monotonic() + REMOTE_READ_BUDGET_SECONDS
    cwd = _remote_cwd(host, name)
    out: Dict[str, Any] = {"last_exchange": _remote_last_exchange(host, name, deadline - time.monotonic()),
                           "docs": {}, "remote_cwd": cwd}
    if want_docs and cwd:
        for d in docs:
            text, _cut, ok = _remote_file_head(host, name, cwd.rstrip("/") + "/" + d, head,
                                               deadline - time.monotonic())
            if ok and text:
                out["docs"][d] = text
    return out


# ── görünümler ────────────────────────────────────────────────────────────────

def context_tokens_for(cwd: str, sid: Optional[str]) -> Optional[int]:
    """Claude transkriptinin SON asistan turunun bağlam boyutu: girdi + cache okuma + cache yazma token'ı (her
    turda yeniden okunan bağlamın boyutu). Dosyanın yalnız sonundan okur (~256 KB); bulunamazsa None."""
    from ..providers.claude_provider import jsonl_path_for
    path = jsonl_path_for(cwd, sid)
    if not path or not os.path.isfile(path):
        return None
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - 262144))
        tail = f.read().decode("utf-8", "replace")
    for line in reversed(tail.splitlines()):
        if '"usage"' not in line or '"assistant"' not in line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        m = o.get("message") or {}
        u = m.get("usage") if m.get("role") == "assistant" else None
        if u:
            return int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0))
    return None


def subagent_active_for(cwd: str, sid: Optional[str], now: Optional[float] = None) -> bool:
    """Oturumun alt ajanı (`<oturum>/subagents/agent-*.jsonl`) hâlâ yazıyor mu: son `SUBAGENT_QUIET_SECONDS` içinde
    değişen bir dosya varsa True. Transkript bulunamazsa False (bilinmiyor = bekletme)."""
    from ..providers.claude_provider import jsonl_path_for
    path = jsonl_path_for(cwd, sid)
    if not path or not path.endswith(".jsonl"):
        return False
    d = os.path.join(path[:-len(".jsonl")], "subagents")
    try:
        names = os.listdir(d)
    except OSError:
        return False
    t = time.time() if now is None else now
    for n in names:
        if n.startswith("agent-") and n.endswith(".jsonl"):
            try:
                if t - os.path.getmtime(os.path.join(d, n)) < sw.SUBAGENT_QUIET_SECONDS:
                    return True
            except OSError:
                continue
    return False


def _collect_views(cfg: sw.Config, rt: Optional[_RemoteTick] = None) -> List[sw.SessionView]:
    """Tick'in oturum görünümleri: yerel `/api/status` satırları (+ provider okumaları) ve uzak projelerin taze
    host'lardaki satırları (`_remote_views`, `rt`: tick'in tazelik anlık görüntüsü). Satır seçimi `sw.select_rows`: adı
    uzak projeye çözülen yerel satır düşer."""
    payload = _act("status_payload") or {}
    world = _world(cfg.sid, cfg)
    rows = sw.select_rows([r for r in (payload.get("sessions") or []) if not sw.normalize_host(r.get("host"))], world)
    live = {s.name: s for s in find_sessions(measure_cpu=False)}
    stuck_names = set()
    try:
        stuck_names = {i.session.name for i in find_stuck(list(live.values()))}
    except Exception:
        pass
    views: List[sw.SessionView] = []
    for r in rows:
        name = r.get("name") or ""
        s = live.get(name)
        v = sw.SessionView(
            name=name, running=bool(r.get("running")), cwd=r.get("cwd") or "", cli=r.get("cli") or DEFAULT_CLI,
            blueprint=r.get("blueprint") if r.get("instance") else None,
            busy=r.get("busy"), history_size=r.get("history_size"), needs_ho=r.get("needs_ho"),
            tmux=bool(r.get("tmux")), stuck=name in stuck_names, model=str(r.get("model") or ""),
        )
        if v.running and s is not None:
            provider = get_provider(s.cli)
            try:
                ex = provider.last_exchange(s.cwd, s.sid) or {}
                v.last_assistant = ex.get("assistant") or ""
            except Exception:
                v.last_assistant = ""
            try:
                v.last_activity = float(provider.last_request_epoch(s.cwd, s.sid, s.pid) or 0.0)
            except Exception:
                v.last_activity = 0.0
            if s.cli == "claude":
                try:
                    v.context_tokens = context_tokens_for(s.cwd, s.sid)
                except Exception:
                    v.context_tokens = None
                try:
                    v.subagent_active = subagent_active_for(s.cwd, s.sid)
                except Exception:
                    v.subagent_active = False
            try:
                v.started_at = float(psutil.Process(s.pid).create_time())
            except Exception:
                v.started_at = 0.0
        views.append(v)
    if world.hosts:
        try:
            views.extend(_remote_views(world, rt=rt))
        except Exception as e:      # uzak okuma yerel görünümleri düşürmesin
            diag_log("steward_remote_views_failed", sid=cfg.sid, error=repr(e))
    return views


# ── oturuma metin gönderme ────────────────────────────────────────────────────

def _wait_ready(name: str, cli: str, timeout: float = READY_TIMEOUT_SECONDS) -> bool:
    """Yeni açılan oturum input alacak hale gelene kadar bekle: pane var, içinde bir şey var, busy
    deseni (varsa) art arda 3 yoklamada yok. Garanti değil — claude meşgulken gelen input'u zaten
    KUYRUĞA alıyor (canlı doğrulanmış, bkz. `turns.py`), bu yüzden en kötü durumda direktif gecikir, kaybolmaz."""
    provider = get_provider(cli)
    pattern = provider.busy_status_pattern()
    t0 = time.monotonic()
    calm = 0
    while time.monotonic() - t0 < timeout:
        time.sleep(1.0)
        if not tmux_has_session(name):
            calm = 0
            continue
        text = strip_ansi(tmux_capture(name, lines=20) or "").strip()
        if not text:
            calm = 0
            continue
        if pattern and is_busy_now(name, pattern):
            calm = 0
            continue
        calm += 1
        if calm >= 3 and time.monotonic() - t0 >= READY_MIN_SECONDS:
            return True
    return False


def _send(name: str, cli: str, text: str) -> bool:
    provider = get_provider(cli)
    if not provider.has_conversation():
        return False
    return tmux_send_keys(name, text, settle_delay=provider.input_settle_delay())


def _running(name: str):
    for s in find_sessions(measure_cpu=False):
        if s.name == name:
            return s
    return None


# Kimliğin dokunamayacağı oturum sınıfları (`World.session_class`): başka kimliğin projesi, çakışmalı proje, servis, beyinler.
_FOREIGN = ("other", "conflict", "service", "brain_other", "brain_own")


def _project_for_session(name: str, projects: Dict[str, sw.Project],
                         world: Optional[sw.World] = None) -> Optional[sw.Project]:
    """Oturum adı → değnekçi projesi: tam ad, yoksa instance kaydının blueprint'i, yoksa base adı.
    `world` verilirse çözüm GLOBAL süzgeçten geçer (K4): ad (ya da blueprint) başka kimliğin projesine, çakışmalı
    projeye, servise ya da bir beyne çözülüyorsa None (`ncs` A'nın, `ncs2` B'nin iken `ncs2` oturumu `Session.base`
    ile A'nın `ncs`'ine İNMEZ). Tek kimlikte sonuç eskisiyle aynı.
    Ad UZAK host'lu bir projeye çözülüyorsa yerel instance kaydına BAKILMAZ (o kayıt buradaki adaş oturumun)."""
    if world is not None:
        kind, key = world.resolve(name)
        if kind == "project" and world.host_of(key):
            p = projects.get(key)
            return None if p is None or world.name_class(name) in _FOREIGN else p
    else:
        key = sw._project_key(name, projects)
        if key and projects[key].host:
            return projects[key]
    rec = inst_mod.get_instance(name)
    p = None
    if name in projects:
        p = projects[name]
    elif rec and rec.get("blueprint") in projects:
        p = projects[rec["blueprint"]]
    else:
        from ..session import Session
        base = Session(name=name, pid=0).base
        if base in projects:
            p = projects[base]
        else:
            m = inst_mod.DERIVED_NAME_RE.match(name)     # rakamlı proje adı (wifi5gppr20261019): Session.base çözemez
            p = projects.get(m.group(1)) if m else None
    if p is None or world is None:
        return p
    return None if world.session_class(name, (rec or {}).get("blueprint")) in _FOREIGN else p


def _remote_rows(host: str, rt: Optional[_RemoteTick] = None) -> Optional[List[Dict[str, Any]]]:
    """Host'un oturum satırları; host taze değilse None (bayat satırla karar verilmez). `rt` verilirse (ve host onun
    görüntüsündeyse) tick başındaki görüntüden, yoksa poller önbelleğinden ŞİMDİ (ağa gitmez)."""
    if rt is not None and host in rt.statuses:
        st = rt.statuses[host] if host in rt.fresh else None
    else:
        st = _remote.status(host)
        if not _host_fresh(st) or _backing_off(host, time.time()):
            st = None
    if not st:
        return None
    return [r for r in (st.get("sessions") or []) if isinstance(r, dict)]


def _remote_running_row(host: str, name: str, rt: Optional[_RemoteTick] = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """(host taze mi, adı TAM `name` olan ÇALIŞAN satır ya da None). Ön ek/base eşleşmesi YOK: uzak tarafın
    unique_base çözümüne güvenilmez (yanlış adaş oturum)."""
    rows = _remote_rows(host, rt)
    if rows is None:
        return False, None
    return True, next((r for r in rows if r.get("name") == name and r.get("running")), None)


_remote_sleep = time.sleep      # testler no-op yapar (hazır bekleme yoklaması)


def _remote_wait_ready(host: str, name: str, timeout: float = READY_TIMEOUT_SECONDS) -> bool:
    """Uzak başlatmadan sonra hazır bekleme. AĞ ÇAĞRISI YAPMAZ: poller önbelleğine `REMOTE_READY_POLL_SECONDS`te bir
    bakar; satır çalışıyor ve `busy is False` (bilinmiyor = hazır değil) olunca True, en çok `timeout`. Yerel
    `_wait_ready` gibi garanti değil: claude meşgulken gelen girdiyi kuyruğa alır, en kötü durumda yönerge gecikir."""
    for i in range(max(1, int(timeout / REMOTE_READY_POLL_SECONDS))):
        if i:
            _remote_sleep(REMOTE_READY_POLL_SECONDS)
        _fresh, r = _remote_running_row(host, name)
        if r is not None and r.get("busy") is False:
            return True
    return False


def _ensure_running_remote(name: str, host: str, model: str, effort: str, fresh: bool,
                           rt: Optional[_RemoteTick] = None) -> Dict[str, Any]:
    """Uzak `_ensure_running`: taze satırda TAM adla çalışıyorsa dokunmaz; değilse `POST /api/start` (gövdede host YOK,
    `REMOTE_START_TIMEOUT_SECONDS`) ve önbellekten hazır bekleme. Host taze değilse başlatma DENENMEZ."""
    fresh_host, r = _remote_running_row(host, name, rt)
    if not fresh_host:
        return {"ok": False, "error": "host_down", "code": "host_down", "host": host}
    if r is not None:
        return {"ok": True, "started": False, "cli": r.get("cli") or DEFAULT_CLI, "host": host}
    res = _remote_post(host, "/api/start", {"name": name, "model": model, "effort": effort, "fresh": bool(fresh)},
                       REMOTE_START_TIMEOUT_SECONDS, rt)
    if not res.get("ok"):
        return res
    ready = _remote_wait_ready(host, name)
    _f, r = _remote_running_row(host, name)
    return {"ok": True, "started": True, "ready": ready, "cli": (r or {}).get("cli") or DEFAULT_CLI, "host": host}


def _ensure_running(name: str, model: str = "", effort: str = "", lang: str = "tr", fresh: bool = False,
                    host: str = "", rt: Optional[_RemoteTick] = None) -> Dict[str, Any]:
    if host:
        return _ensure_running_remote(name, host, model, effort, fresh, rt)
    s = _running(name)
    if s is not None:
        return {"ok": True, "started": False, "cli": s.cli}
    res = _act("start", name, model=model, effort=effort, fresh=fresh, lang=lang)
    if not res.get("ok"):
        return res
    cli = _project_cli(name)
    ready = _wait_ready(name, cli)
    return {"ok": True, "started": True, "ready": ready, "cli": cli}


def _proc_born(pid: int) -> float:
    """Sürecin başlangıç zamanı (epoch); oturumun yaşam kimliği. Bilinmiyorsa 0."""
    try:
        return round(float(psutil.Process(pid).create_time()), 2)
    except Exception:
        return 0.0


def _remote_born(host: str, name: str, rt: Optional[_RemoteTick] = None) -> float:
    """Uzak oturumun yaşam kimliği: `now - facts.started_age_s` (yaş, saat kayması yok). Bilinmiyorsa (eski host 404,
    olgu yok, ağ hatası, devre açık) 0: çağıran tam önsöz gönderir ve `preamble_sent` yazmaz."""
    if rt is not None and rt.blocked(host):
        return 0.0
    try:
        _caps, facts = _probe_facts(host, [name], 5.0)
    except Exception:
        return 0.0
    age = (facts.get(name) or {}).get("started_age_s") if isinstance(facts.get(name), dict) else None
    if not isinstance(age, (int, float)) or isinstance(age, bool) or age < 0:
        return 0.0
    return round(time.time() - float(age), 2)


def _same_life(stored: float, born: float, remote: bool) -> bool:
    """`preamble_sent` kaydı bu süreç yaşamının mı: yerelde tam eşitlik (`create_time`), uzakta yaş okumasının gecikmesi
    kadar oynar (`REMOTE_BORN_TOLERANCE_SECONDS`)."""
    if not stored or not born:
        return False
    return abs(stored - born) <= REMOTE_BORN_TOLERANCE_SECONDS if remote else stored == born


def _give_directive(project: sw.Project, text: str, *, model: str = "", effort: str = "",
                    answer: Optional[sw.Question] = None, more: Optional[List[sw.Question]] = None,
                    start_if_stopped: bool = True,
                    reason: str = "", session_name: str = "", cfg: Optional[sw.Config] = None,
                    host: Optional[str] = None, rt: Optional[_RemoteTick] = None) -> Dict[str, Any]:
    """`project`'e (ya da onun `session_name` adlı çalışan instance'ına) direktif gönder; kapalıysa aç.
    Proje değnekçi kaydında değilse (ad hoc oturum) sadece gönderir, kayıt açmaz. Kayıtlar `cfg.sid`'in deposuna.

    Uzak hedef (`host`; None = addan çözülür, yerel yola ASLA düşmez): oturum taze satırdan TAM adla (running/tmux/cli),
    kapalıysa `_ensure_running_remote`, gönderim `POST /api/term/input` (`exact: true`), yaşam kimliği facts yaşından,
    `preamble_sent` anahtarı `host:ad` (aynı adlı yerel oturumun kaydına karışmaz)."""
    cfg = cfg or steward_config()
    paths = sw.paths_for(cfg.sid)
    lang = cfg.lang
    target = session_name or project.name
    if host is None:
        host = _name_host(target)
    if answer is not None and _already_sent(lambda: sw.mark_delivered(answer.id, paths), cfg.sid, "answer", answer.id):
        return {"ok": True, "name": target, "skipped": "already sent"}       # önceki turda gitti, işareti yazılamamıştı
    if not model and not effort:
        model, effort = sw.phase_model_effort(project, cfg)
    if host:
        fresh_host, row = _remote_running_row(host, target, rt)
        if not fresh_host:
            return {"ok": False, "error": "host_down", "code": "host_down", "host": host}
        if row is None:
            if not start_if_stopped:
                return {"ok": False, "error": "not running", "host": host}
            res = _ensure_running(target, model=model, effort=effort, lang=lang, host=host, rt=rt)
            if not res.get("ok"):
                return res
            _f, row = _remote_running_row(host, target)        # başlatmadan sonra: tick görüntüsü değil, önbellek şimdi
            if row is None:
                return {"ok": False, "error": "start reported ok but no session row on the host", "host": host}
        if not row.get("tmux"):
            return {"ok": False, "error": "not tmux-backed (cannot inject)", "host": host}
        sname, scli = target, str(row.get("cli") or DEFAULT_CLI)
        born, pkey = _remote_born(host, target, rt), f"{host}:{target}"
    else:
        s = _running(target)
        if s is None:
            if not start_if_stopped:
                return {"ok": False, "error": "not running"}
            res = _ensure_running(target, model=model, effort=effort, lang=lang)
            if not res.get("ok"):
                return res
            s = _running(target)
            if s is None:
                return {"ok": False, "error": "start reported ok but no process found"}
        if not is_tmux_backed(s.pid):
            return {"ok": False, "error": "not tmux-backed (cannot inject)"}
        sname, scli = s.name, s.cli
        born, pkey = _proc_born(s.pid), s.name
    compact = False
    if answer is not None and born:
        try:     # bu süreç yaşamında tam başlık (amaç/not/protokol) zaten gitti mi?
            stored = float(sw.load_state(paths).get("preamble_sent", {}).get(pkey) or 0.0)
            compact = _same_life(stored, born, bool(host))
        except Exception:
            compact = False
    message = sw.build_directive(project, lang=lang, extra=text, answer=answer, more=more, compact=compact)
    if host:
        try:
            conversational = get_provider(scli).has_conversation()
        except Exception:
            conversational = False
        if not conversational:
            return {"ok": False, "error": "send failed", "host": host}
        sent = _remote_post(host, "/api/term/input", {"name": sname, "text": message, "exact": True},
                            REMOTE_INPUT_TIMEOUT_SECONDS, rt)
        if not sent.get("ok"):
            return dict(sent, ok=False, error=str(sent.get("error") or "send failed"), host=host)
    elif not _send(sname, scli, message):
        return {"ok": False, "error": "send failed"}
    # Mesaj GİTTİ: bundan sonrası kayıt tutmadır. Hiçbir kayıt hatası (ör. kilit zaman aşımı) çağırana "başarısız" demez ve
    # cevabın İKİNCİ KEZ iletilmesine yol açmaz: yinelenmeyi engelleyen `delivered` işareti ÖNCE ve yeniden denemeli yazılır.
    unrecorded = False
    if answer is not None:
        unrecorded = not _mark_after_send(lambda: sw.mark_delivered(answer.id, paths), cfg.sid, "answer", answer.id)
        for m in more or []:
            unrecorded |= not _mark_after_send(lambda m=m: sw.mark_delivered(m.id, paths), cfg.sid, "answer", m.id)
    if project.name in sw.load_projects(paths):
        try:
            sw.upsert_project(project.name, paths=paths, last_visit=time.time(),
                              last_directive=(text or f"[{project.phase} şablonu]")[:400], visits=project.visits + 1)
        except (ValueError, sw.LockTimeout) as e:   # OwnedElsewhere: ad elle iki kimliğe yazılmış (çakışma) / kilit zaman aşımı; mesaj gitti, kayıt yazılmaz
            sw.log_event("directive_unrecorded", paths=paths, name=project.name, error=str(e))
    try:
        with sw.steward_lock(paths):
            state = sw.load_state(paths)
            state.setdefault("last_directive_at", {})[sname] = time.time()   # plan_tick adla okur (ad host'lar arası tekil)
            if born and not compact:
                state.setdefault("preamble_sent", {})[pkey] = born
            sw.save_state(state, paths)
    except sw.LockTimeout as e:
        sw.log_event("directive_unrecorded", paths=paths, name=project.name, error=str(e))
    sw.log_event("directive", paths=paths, name=project.name, reason=reason, chars=len(message),
                 **({"host": host} if host else {}))
    out = {"ok": True, "name": sname, "chars": len(message)}
    if host:
        out["host"] = host
    if unrecorded:
        out["unrecorded"] = True
    return out


# Mesajı GİDEN ama `delivered` işareti kilit zaman aşımıyla yazılamayan öğeler (süreç içi): {(kimlik, tür, id)}. Sonraki tick
# aynı cevabı/işi YENİDEN GÖNDERMEZ, yalnız işareti yeniden yazmayı dener. Süreç yeniden başlarsa küme kaybolur (nadir iki
# olayın çakışması: kilit zaman aşımı + restart); o durumda tek bir yinelenen iletim mümkündür.
_SENT_UNMARKED: set = set()


def _mark_after_send(mark, sid: str, what: str, ident: Any, attempts: int = 2) -> bool:
    """Mesaj GİTTİKTEN sonra `delivered` işaretini yaz; `LockTimeout`ta yeniden dene. Yine olmazsa `delivery_unrecorded`
    loglanır, öğe `_SENT_UNMARKED`a girer (yinelenen iletim olmasın) ve istisna YUKARI ÇIKMAZ: mesaj gitti, çağıran işi
    başarısız saymasın. Dönen: işaret yazıldı mı."""
    key = (sid, what, str(ident))
    last = ""
    for _ in range(max(1, attempts)):
        try:
            mark()
            _SENT_UNMARKED.discard(key)
            return True
        except sw.LockTimeout as e:
            last = str(e)
    _SENT_UNMARKED.add(key)
    sw.log_event("delivery_unrecorded", paths=sid, what=what, id=ident, error=last)
    return False


def _already_sent(mark, sid: str, what: str, ident: Any) -> bool:
    """Önceki turda mesajı gitmiş ama işareti yazılamamış öğe mi? Öyleyse işareti bir kez daha yazmayı dener ve True döner
    (çağıran YENİDEN GÖNDERMEZ)."""
    if (sid, what, str(ident)) not in _SENT_UNMARKED:
        return False
    _mark_after_send(mark, sid, what, ident, attempts=1)
    return True


# ── proje kartları ────────────────────────────────────────────────────────────
#
# Çekirdek (`steward.py`): ham kart, prompt, ayrıştırma, yenileme kuralı. Burada: modeli çağıran tek seferlik
# özet (`summarize_card`), hangi projenin yenileneceği (`refresh_due_cards`) ve arka plan işi. Kart yenileme
# `_LOCK` ALTINDA DEĞİL: bir model çağrısı (10-60 sn) tick'i ve beynin MCP çağrılarını bekletmesin.

def oneshot_cwd() -> str:
    """Tek seferlik çağrıların NÖTR cwd'si (proje klasörü değil): CLAUDE.md/transkript projeye karışmasın."""
    return sw.paths_for().oneshot


def summarize_card(raw: Dict[str, Any], name: str = "", project: Optional[sw.Project] = None,
                   cfg: Optional[sw.Config] = None) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Ham karttan tek seferlik headless çağrıyla (`provider.oneshot`) özet iste. Dönen: (alanlar | None, meta).
    None = çağrı başarısız ya da yanıt JSON değil (`meta["error"]` nedeni söyler); çağıran ham kartta kalır."""
    cfg = cfg or steward_config()
    cli = cfg.card_cli if cfg.card_cli in PROVIDERS else DEFAULT_CLI
    provider = get_provider(cli)
    model = sw.pick_card_model(cfg.card_model, provider.model_choices(), default_model_for(provider))
    meta: Dict[str, Any] = {"cli": cli, "model": model}
    prompt = sw.build_card_prompt(name, raw, project, lang=cfg.lang)
    t0 = time.time()
    try:
        text = provider.oneshot(prompt, model, oneshot_cwd(), timeout=CARD_TIMEOUT_SECONDS)
    except OneshotError as e:
        meta["error"] = str(e)
        return None, meta
    finally:
        meta["secs"] = round(time.time() - t0, 1)
    if text is None:
        meta["error"] = f"{cli}: tek seferlik çağrı desteklenmiyor"
        return None, meta
    parsed = sw.parse_card_json(text)
    if parsed is None:
        meta["error"] = "yanıt JSON olarak ayrıştırılamadı"
    return parsed, meta


def _cwd_resolver() -> Callable[[str], str]:
    """Proje adı -> cwd, filo anlık görüntüsü bir kez alınarak (160 projede her biri için süreç taraması YOK;
    çalışan projeler zaten kart yenilemeden dışlanır, yalnız roster/instance kayıtlarına bakılır)."""
    fleet = _act("fleet_status") or {}
    try:
        hosts = _ownership_index().get("hosts") or {}
    except Exception:
        hosts = {}

    def resolve(name: str) -> str:
        if hosts.get(name):     # uzak proje: yerel klasör YOK (aynı yoldaki yerel klasör onun değil)
            return ""
        info = fleet.get(name) if isinstance(fleet, dict) else None
        if info and info.get("cwd"):
            return info["cwd"]
        rec = inst_mod.get_instance(name)
        return (rec or {}).get("cwd") or ""
    return resolve


def refresh_card(name: str, cfg: Optional[sw.Config] = None, *, cwd: str = "", raw: Optional[Dict[str, Any]] = None,
                 reason: str = "") -> Dict[str, Any]:
    """Tek projenin kartını üret/yenile ve yaz. Özet başarısızsa: kart varsa DOKUNULMAZ (yalnız deneme kaydı),
    yoksa ham kart yazılır. Her çağrı `log.jsonl`'a bir `card` olayı düşer (günlük özet bunu sayar)."""
    cfg = cfg or steward_config()
    project = sw.load_projects(cfg.sid).get(name)
    if (project is not None and project.host) or _name_host(name):
        return {"ok": False, "name": name, "error": "remote project: cards are not built from a remote folder yet"}
    cwd = cwd or _project_cwd(name)
    if not cwd or not os.path.isdir(cwd):
        return {"ok": False, "name": name, "error": "project folder unknown"}
    raw = raw or sw.build_raw_card(cwd)
    parsed, meta = summarize_card(raw, name, project, cfg)
    old = sw.load_card(name)
    if parsed is None and old is not None:
        sw.note_card_failure(name, raw["source_hash"], meta.get("error", ""))
    else:
        sw.save_card(name, sw.make_card(raw, parsed, project, meta={
            **{k: meta[k] for k in ("cli", "model") if k in meta},
            **({"last_error": meta["error"]} if parsed is None and meta.get("error") else {})}))
    ok = parsed is not None
    sw.log_event("card", paths=cfg.sid, name=name, ok=ok, reason=reason, model=meta.get("model", ""),
                 cli=meta.get("cli", ""), secs=meta.get("secs", 0), error=meta.get("error", ""))
    return {"ok": ok, "name": name, "error": meta.get("error", ""), "model": meta.get("model", "")}


def _running_names_for(live: List[Any], projects: Dict[str, sw.Project], world: Optional[sw.World] = None,
                       remote: Optional[List[Dict[str, Any]]] = None) -> set:
    """Çalışan oturumların proje adları: tam ad + `Session.base` + değnekçi projesine eşleme. `Session.base` yalnız
    harften oluşan adları çözer (`wifi5gppr20261019` → kendisi), bu yüzden rakamlı proje adları "çalışmıyor" görünür
    ve uğrama sırası ikinci bir oturum açardı; `_project_for_session` blueprint/tarih sonekinden de çözer.
    `world` verilirse global çözümle uyumlu: oturum başka kimliğe çözülüyorsa (`ncs2` B'nin) tabanı (`ncs`, A'nın)
    "çalışıyor" sayılmaz."""
    if world is not None and world.hosts:       # uzak projenin YEREL adaşı o projenin çalıştığını göstermez
        live = [s for s in live if not _name_host_in(s.name, projects, world)]
    out = {s.name for s in live}
    known = (set(world.owners) | set(world.conflicts)) if world is not None else set()
    for s in live:
        if world is None or s.base not in known or world.session_class(s.name) not in _FOREIGN:
            out.add(s.base)
        p = _project_for_session(s.name, projects, world)
        if p is not None:
            out.add(p.name)
    for r in (remote or ()):       # taze host'lardaki uzak proje oturumları (A5): aynı ad kümeye iki kez girmez (set)
        out.add(str(r.get("name") or ""))
        p = _project_for_session(str(r.get("name") or ""), projects, world)
        if p is not None:
            out.add(p.name)
    return out


def _name_host_in(name: str, projects: Dict[str, sw.Project], world: sw.World) -> str:
    """Ad world'e göre uzak host'lu bir projeye çözülüyorsa host'u, değilse ""."""
    return _locate(name, projects, world)[0]


def _running_project_names(sid: str = "default") -> set:
    world = _world(sid)
    return _running_names_for(find_sessions(measure_cpu=False), sw.load_projects(sid), world,
                              remote=_remote_running_listing(world))


def refresh_due_cards(cfg: Optional[sw.Config] = None, limit: Optional[int] = None,
                      now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Kartı olmayan / bayat / kaynağı değişmiş / eskimiş, ÇALIŞMAYAN, aktif fazdaki projeleri yenile (en çok
    `limit`; None = `cards_per_tick`). Önce kartı hiç olmayanlar, sonra en eski kart. Çalışan proje atlanır:
    oturum yazarken kaynak zaten değişiyor (handover'dan sonra `mark_card_stale` ile işaretlenir).
    Projeler `cfg.sid`'in deposundan; default dışı kimlikte çakışmalı projeler atlanır (kimse yönetmez)."""
    cfg = cfg or steward_config()
    limit = cfg.cards_per_tick if limit is None else limit
    if limit <= 0:
        return []
    now = now if now is not None else time.time()
    projects = sw.load_projects(cfg.sid)
    if cfg.sid == "default":
        running = _running_project_names()
    else:
        projects = _world(cfg.sid, cfg).own_projects(projects)
        running = _running_project_names(cfg.sid)
    cards = sw.load_cards()
    cwd_of = _cwd_resolver()
    due = []
    for p in projects.values():
        if p.phase not in sw.ACTIVE_PHASES or p.name in running or p.host:
            continue     # uzak proje: kartı uzak klasörden üretilmez (A1: atlanır)
        cwd = cwd_of(p.name)
        if not cwd or not os.path.isdir(cwd):
            continue
        raw = sw.build_raw_card(cwd)
        reason = sw.card_refresh_reason(cards.get(p.name), raw["source_hash"], now, cfg.card_max_age_hours)
        if reason:
            old = cards.get(p.name)
            due.append(((old is not None, float((old or {}).get("updated_at") or 0.0), p.priority, p.name), p, cwd, raw, reason))
    due.sort(key=lambda x: x[0])
    results = []
    for _, p, cwd, raw, reason in due[:limit]:
        try:
            results.append(refresh_card(p.name, cfg, cwd=cwd, raw=raw, reason=reason))
        except Exception as e:  # tek kart döngüyü düşürmesin
            diag_log("steward_card_crashed", name=p.name, error=repr(e))
            results.append({"ok": False, "name": p.name, "error": repr(e)})
    return results


def _run_cards_job(job: Callable[[], Any]) -> bool:
    """Kart işini arka planda koştur; zaten bir iş sürüyorsa False (üst üste binmesin)."""
    if not _CARD_LOCK.acquire(blocking=False):
        return False

    def _work() -> None:
        try:
            job()
        except Exception as e:
            diag_log("steward_card_job_crashed", error=repr(e))
        finally:
            _CARD_LOCK.release()

    if _CARD_BACKGROUND:
        threading.Thread(target=_work, daemon=True, name="steward-cards").start()
    else:
        _work()
    return True


def card_tick(cfg: sw.Config) -> bool:
    """tick_once'ın kart adımı: `card_refresh` açıksa ve `cards_per_tick` > 0 ise arka planda bir tur."""
    if not cfg.card_refresh or cfg.cards_per_tick <= 0:
        return False
    return _run_cards_job(lambda: refresh_due_cards(cfg))


def cards_round(cfgs: List[sw.Config]) -> bool:
    """Döngü turunun TEK kart işi (K7): kimlikler sırayla, `cards_per_tick` (makine geneli) bütçesi TÜM kimliklerde
    ortak. Tek kimlikte `card_tick(cfg)` ile aynı. İş zaten sürüyorsa False."""
    if not cfgs or not cfgs[0].card_refresh or cfgs[0].cards_per_tick <= 0:
        return False
    if len(cfgs) == 1:
        return card_tick(cfgs[0])

    def job() -> None:
        left = cfgs[0].cards_per_tick
        for c in cfgs:
            if left <= 0:
                break
            try:
                left -= len(refresh_due_cards(c, limit=left))
            except Exception as e:  # bir kimliğin kart adımı diğerlerini düşürmesin
                diag_log("steward_card_round_crashed", sid=c.sid, error=repr(e))
    return _run_cards_job(job)


# ── beyin ─────────────────────────────────────────────────────────────────────

def brain_spec(sid: str = "default") -> McpServerSpec:
    """Beynin MCP sunucusu: default argümansız (eski komut satırı), diğer kimlikler `--steward <sid>`."""
    from . import mcp_steward
    return mcp_steward.default_spec(sid)


def ensure_workspace(cfg: Optional[sw.Config] = None) -> str:
    """Kimliğin beyin cwd'sini (`paths_for(sid).workspace`) ve CLAUDE.md'sini hazırla. Persona: default `steward_persona_text`
    (yoksa paketlenmiş); diğer kimlik kendi `persona_text`i, boşsa ortak `steward_persona_text`. Default dışında kimlik
    bölümü eklenir, `MODEL_RULE_*` her kimliğin CLAUDE.md'sine girer."""
    cfg = cfg or steward_config()
    workspace = sw.paths_for(cfg.sid).workspace
    os.makedirs(workspace, exist_ok=True)
    shared = str(load_settings().get("steward_persona_text") or "")
    persona = sw.persona_text(shared if cfg.sid == "default" else (cfg.persona_text or shared))
    has_remote = any(pr.host for pr in sw.load_projects(cfg.sid).values())
    text = sw.build_workspace_claude_md(persona, lang=cfg.lang, sid=cfg.sid, label=cfg.label, remote=has_remote)
    path = os.path.join(workspace, "CLAUDE.md")
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return path
    except OSError:
        pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def brain_start(cfg: Optional[sw.Config] = None, fresh: bool = False) -> Dict[str, Any]:
    """Kimliğin beynini aç (kendi workspace'i, `mcp-steward --steward <sid>`). Default dışı kimlik YALNIZ `enabled` iken
    açılır (hiçbir yeni kimlik kendiliğinden beyin açmaz; ayar varsayılan KAPALI); default'un davranışı eskisiyle aynı."""
    cfg = cfg or steward_config()
    if cfg.sid != "default" and not cfg.enabled:
        return {"ok": False, "error": f"steward {cfg.sid} is disabled; its brain is not started"}
    if _running(cfg.brain_name) is not None:
        return {"ok": True, "started": False, "name": cfg.brain_name}
    ensure_workspace(cfg)
    workspace = sw.paths_for(cfg.sid).workspace
    cli = cfg.brain_cli if cfg.brain_cli in PROVIDERS else DEFAULT_CLI
    provider = get_provider(cli)
    model = cfg.brain_model or default_model_for(provider)
    effort = cfg.brain_effort or default_effort_for(provider)
    mode = provider.permission_modes()[0] if provider.permission_modes() else "auto"
    inst_mod.record_instance(cfg.brain_name, blueprint=None, cwd=workspace, cli=cli, model=model,
                             permission_mode=mode, effort=effort, origin="steward")
    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
            kind = spawn_session(name=cfg.brain_name, cwd=workspace, model=model, display=detect_display(),
                                 permission_mode=mode, effort=effort, force_new=bool(fresh), cli=cli,
                                 mcp_server=brain_spec(cfg.sid))
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    inst_mod.mark_started(cfg.brain_name, cli=cli, model=model, permission_mode=mode, effort=effort)
    ready = _wait_ready(cfg.brain_name, cli)
    sw.log_event("brain_start", paths=cfg.sid, name=cfg.brain_name, kind=kind, ready=ready)
    return {"ok": True, "started": True, "name": cfg.brain_name, "kind": kind, "ready": ready}


def brain_stop(cfg: Optional[sw.Config] = None) -> Dict[str, Any]:
    cfg = cfg or steward_config()
    if _running(cfg.brain_name) is None:
        return {"ok": True, "stopped": False}
    res = _act("stop", cfg.brain_name, lang=cfg.lang)
    sw.log_event("brain_stop", paths=cfg.sid, name=cfg.brain_name, ok=bool(res.get("ok")))
    return res


def _enrich_item(it: Dict[str, Any], projects: Dict[str, sw.Project],
                 world: Optional[sw.World] = None) -> Dict[str, Any]:
    if it.get("kind") == "idea":
        return it
    name = it.get("name") or ""
    p = projects.get(name)
    remote = _name_host(name) if sw.valid_name(name) else ""
    s = None if remote else _running(name)        # uzak projede yerel adaş oturum/klasör okunmaz
    proj = p or (_project_for_session(s.name, projects, world) if s is not None else None)
    if proj is None and remote:
        proj = _locate(name, projects, world)[1]
    out = dict(it)
    if proj is not None:
        out.update({"phase": proj.phase, "kindp": proj.kind, "goal": proj.goal, "last_directive": proj.last_directive})
    if remote:
        out["host"] = remote
    cwd = "" if remote else ((s.cwd if s is not None else "") or _project_cwd(name))
    card = sw.load_card(proj.name) if proj is not None else None
    if remote:      # uzak: son konuşma term/chat'ten, belge başları host-routed files/read'den (yerel dosya sistemi yok)
        rd = _remote_read_context(remote, name, card is None, ("TODO.md", "PLAN.md"), 600)
        out["last_exchange"] = rd["last_exchange"]
        if card is None and rd["docs"]:
            out["docs"] = rd["docs"]
    elif s is not None:
        try:
            out["last_exchange"] = get_provider(s.cli).last_exchange(s.cwd, s.sid) or {}
        except Exception:
            out["last_exchange"] = {}
    if card is not None:
        out["card"] = card    # beyin 160 repoyu değil kartları okur; ham belge başı yalnız kart yokken
        return out
    if remote:
        return out
    docs = {}
    for d in ("TODO.md", "PLAN.md"):
        head = _read_head(cwd, d, 600) if cwd else ""
        if head:
            docs[d] = head
    if docs:
        out["docs"] = docs
    return out


TOUR_FAILS_BEFORE_RESTART = 2    # art arda bu kadar tur gönderimi başarısızsa beyin oturumu yeniden açılır


def brain_restart_for_stuck_input(cfg: sw.Config) -> Dict[str, Any]:
    """Beyin oturumunu durdurup yeniden aç (konuşma `--resume` ile sürer; giriş kutusu temizlenir)."""
    stop = _act("stop", cfg.brain_name, lang=cfg.lang)
    if not stop.get("ok"):
        return stop
    time.sleep(3)
    return brain_start(cfg)


def run_tour(items: Optional[List[Dict[str, Any]]] = None, force: bool = False,
             cfg: Optional[sw.Config] = None, world: Optional[sw.World] = None) -> Dict[str, Any]:
    """Beyne bir tur prompt'u gönder. `items` None ise şu anki gözden-geçirme maddeleri `review_items`'tan
    alınır (`force`: tour_minutes/beyin-boşta şartına bakılmaz, madde yoksa yine de "tur" gönderilir —
    kullanıcı bilerek istedi; beyin `steward_overview` ile kendi bakar). Beyin kapalıysa açılır.
    `cfg`/`world`: kimlik (verilmezse default); maddeler yalnız o kimliğin projelerinden."""
    cfg = cfg or steward_config()
    paths = sw.paths_for(cfg.sid)
    projects = sw.load_projects(paths)
    if world is None:
        world = _world(cfg.sid, cfg)
    if items is None:
        state = sw.load_state(paths)
        views = _collect_views(cfg)
        items = sw.review_items(views, projects, cfg, time.time(), sw.load_questions(paths), sw.load_ideas(paths),
                                skip=set(state.get("ho_pending") or {}),
                                last_directive_at=state.get("last_directive_at") or {},
                                reviewed_at=state.get("reviewed_at") or {}, world=world)
        if not items and not force:
            return {"ok": False, "error": "no review items right now"}
    res = brain_start(cfg)
    if not res.get("ok"):
        return res
    s = _running(cfg.brain_name)
    if s is None or not is_tmux_backed(s.pid):
        return {"ok": False, "error": "brain session not reachable"}
    enriched = [_enrich_item(it, projects, world) for it in items]
    answered = [q for q in sw.load_questions(paths) if q.status == "answered"]
    for it in enriched:     # karar hafızası: rutin/takılma maddelerine sahibin benzer geçmiş cevapları
        if it.get("kind") in ("routine", "blocked") and it.get("text") and answered:
            sims = sw.similar_answers(it["text"], answered, project=it.get("name") if it.get("name") != "-" else "",
                                      exclude_id=str(it.get("id") or ""))
            if sims:
                it["similar"] = [{"project": q.project, "text": q.text, "answer": q.answer} for q in sims]
    prompt = sw.build_tour_prompt(enriched, lang=cfg.lang, open_qs=sw.open_questions(paths=paths), now=time.time())
    if not _send(s.name, s.cli, prompt):
        return {"ok": False, "error": "send failed"}
    with sw.steward_lock(paths):
        state = sw.load_state(paths)
        state["last_tour"] = time.time()
        sw.save_state(state, paths)
    sw.log_event("tour", paths=paths, items=len(enriched), chars=len(prompt))
    return {"ok": True, "items": len(enriched), "chars": len(prompt)}


# ── günlük özet ───────────────────────────────────────────────────────────────

NTFY_SUMMARY_CHARS = 1500


def _write_summary(date: str, cfg: sw.Config, late: bool = False) -> str:
    """Bir günün özetini yaz + telefona gönder + logla; ardından o günün `tick` satırlarını tek toplama katla
    (`compact_log`; özet sayıları aynı kalır) ve dosya büyüdüyse devir (`rotate_log`)."""
    text = sw.summary_text(date, cfg.lang, cfg.sid)
    path = sw.write_daily(date, text, cfg.sid)
    note = ("(gecikmiş özet) " if cfg.lang != "en" else "(late summary) ") if late else ""
    paths = sw.paths_for(cfg.sid)
    body = (note + text)[:NTFY_SUMMARY_CHARS]
    notified = _notify(cfg, body if cfg.sid == "default" else f"[{cfg.sid}] {body}"[:NTFY_SUMMARY_CHARS])
    sw.log_event("summary", paths=paths, date=date, path=path, notified=notified, chars=len(text), late=late)
    folded = sw.compact_log(date, paths)
    rotated = sw.rotate_log(paths=paths)
    if folded or rotated:
        sw.log_event("log_compact", paths=paths, date=date, ticks=folded, rotated=rotated)
    return path


def maybe_daily_summary(cfg: sw.Config, now: float) -> Optional[str]:
    """`summary_hour`u geçtiyse ve bugünün özeti yazılmadıysa: `steward/daily/<tarih>.md` yaz, ntfy ile telefona
    gönder (kuruluysa), `summary` olayını logla, `state.summary_date`i işaretle. Önce KAÇAN günler
    (`missed_summary_dates`: panel `summary_hour`da kapalıysa o gün özetlenmemişti) saat beklemeden tamamlanır.
    Dönen: yazılan son dosyanın yolu; yazılacak bir şey yoksa None."""
    path: Optional[str] = None
    paths = sw.paths_for(cfg.sid)       # özet/log/daily/state KİMLİK BAŞINA (default: bugünkü yerler)
    for date in sw.missed_summary_dates(now, paths=paths):
        path = _write_summary(date, cfg, late=True)
    state = sw.load_state(paths)
    date = sw.summary_due(state, now, cfg.summary_hour)
    if not date:
        return path
    path = _write_summary(date, cfg)
    with sw.steward_lock(paths):
        state = sw.load_state(paths)
        state["summary_date"] = date
        sw.save_state(state, paths)
    return path


def http_summary(date: str = "", lang: str = "", sid: str = "default") -> Dict[str, Any]:
    cfg = steward_config(sid)
    date = date or time.strftime("%Y-%m-%d")
    try:
        time.strptime(date, "%Y-%m-%d")
    except ValueError:
        return {"ok": False, "error": "date must be YYYY-MM-DD"}
    path = sw.daily_path(date, sid)
    return {"ok": True, "date": date, "text": sw.summary_text(date, lang if lang in ("tr", "en") else cfg.lang, sid),
            "saved": os.path.isfile(path), "path": path if os.path.isfile(path) else ""}


# ── eylem uygulama ────────────────────────────────────────────────────────────

# Oturuma dokunan eylem türleri (observe'da uygulanmayanlar, beynin turu hariç: beyin hep yerel).
_SESSION_KINDS = tuple(k for k in sw.OBSERVE_SKIPPED if k != "tour")


def _remote_handover(name: str, host: str, rt: Optional[_RemoteTick] = None) -> Dict[str, Any]:
    """Uzak devir: ön denetim (taze satırlarda TAM ad, çalışıyor) sonra `POST /api/handover` (`exact: true`: eski host
    alanı yok sayar, yeni host unique_base'e düşmez; gövdede host YOK). Canlı mesaj; kill/respawn uzak tarafta da yok."""
    fresh_host, row = _remote_running_row(host, name, rt)
    if not fresh_host:
        return {"ok": False, "error": "host_down", "code": "host_down", "host": host}
    if row is None:
        return {"ok": False, "error": "not running (no exact running row on the host)", "host": host}
    return dict(_remote_post(host, "/api/handover", {"name": name, "exact": True}, REMOTE_HANDOVER_TIMEOUT_SECONDS, rt),
                host=host)


def _remote_stop(name: str, host: str, world: sw.World, sid: str, actor: str,
                 rt: Optional[_RemoteTick] = None) -> Dict[str, Any]:
    """Uzak durdurmanın TEK yolu (A4; `_target` kapıları çağırandan önce geçildi). Sıra:
    1. host taze, satırlarda adı TAM `name` olan ÇALIŞAN satır var (ön ek/base yok);
    2. satır bu kimliğin kayıtlı proje oturumu: `sw.select_rows` onu bu host için seçiyor VE sınıfı "own" (uzak beyin,
       servis, kayıtsız ya da başka kimliğin oturumu DEĞİL);
    3. host `exact_target` bildiriyor (`host_capabilities`); bildirmeyen eski host'ta (api 0) `remote_too_old` olayı
       (tekrarsız) ve eylem YOK. Yetenek bilinemediyse (yoklama ağ hatası, önbellek yok) de uygulanmaz;
    4. tick içinde (`rt`) host başına `MAX_DESTRUCTIVE_PER_HOST` (`destructive_budget`: ertelenir, gönderilmez);
    5. `POST /api/stop {"name", "exact": true}` (`REMOTE_STOP_TIMEOUT_SECONDS`, gövdede host YOK).
    Yanıt `ok: false` (ör. `no_exact_match`: uzakta tam ad yok) uygulanmış SAYILMAZ, `remote_stop_rejected` loglanır;
    uygulama düzeyi ret devre kesiciyi açmaz (taşıma hatası `_remote_post`ta A3 kuralıyla açar). Sayaç gönderimden
    ÖNCE artar: yanıtı ne olursa olsun bu tick'te host'a ikinci yıkıcı istek gitmez."""
    fresh_host, row = _remote_running_row(host, name, rt)
    if not fresh_host:
        return {"ok": False, "error": "host_down", "code": "host_down", "host": host}
    if row is None:
        return {"ok": False, "error": "not running (no exact running row on the host)", "code": "no_exact_row",
                "host": host}
    bp = row.get("blueprint") if row.get("instance") else None
    if not sw.select_rows([dict(row, host=host)], world, {host}) or world.session_class(name, bp) != "own":
        _log_remote_denied(sid, actor, "stop", name, host, "not_own")
        return {"ok": False, "error": "target denied: the remote row is not this steward's registered project session",
                "code": "not_own", "host": host}
    if rt is not None and rt.blocked(host):
        return {"ok": False, "error": "host_down", "code": "host_down", "host": host}
    caps = host_capabilities(host)
    if "exact_target" not in caps["capabilities"]:
        known = _caps_cached(host, time.time()) is not None      # önbellekte kayıt = host gerçekten bildirmiyor
        code = "remote_too_old" if known else "caps_unknown"
        _log_remote_denied(sid, actor, "stop", name, host, code, event="remote_too_old" if known else "target_denied")
        return {"ok": False, "error": (f"{host} does not support exact targeting (upgrade claudeops there)" if known
                                       else f"{host} capabilities unknown right now"), "code": code, "host": host}
    if rt is not None:
        if rt.destructive.get(host, 0) >= MAX_DESTRUCTIVE_PER_HOST:
            return {"ok": False, "error": f"one destructive action per host per tick ({host})",
                    "code": "destructive_budget", "host": host}
        rt.destructive[host] = rt.destructive.get(host, 0) + 1
    res = dict(_remote_post(host, "/api/stop", {"name": name, "exact": True}, REMOTE_STOP_TIMEOUT_SECONDS, rt),
               host=host)
    if not res.get("ok"):
        sw.log_event("remote_stop_rejected", paths=sid, name=name, host=host, actor=actor or "human",
                     error=str(res.get("error") or ""), code=str(res.get("code") or ""))
        res["ok"] = False
    return res


def _remote_wait_closed(host: str, name: str, timeout: float = READY_TIMEOUT_SECONDS) -> bool:
    """Uzak durdurmadan sonra satırın kapanmasını bekle. AĞ ÇAĞRISI YAPMAZ: poller önbelleğine
    `REMOTE_READY_POLL_SECONDS`te bir bakar; host taze VE adı TAM `name` olan çalışan satır yoksa True, en çok
    `timeout`. Host bayatsa kapanma DOĞRULANAMAZ (beklemeye devam)."""
    for i in range(max(1, int(timeout / REMOTE_READY_POLL_SECONDS))):
        if i:
            _remote_sleep(REMOTE_READY_POLL_SECONDS)
        fresh_host, r = _remote_running_row(host, name)
        if fresh_host and r is None:
            return True
    return False


def _remote_stop_and_wait(name: str, host: str, world: sw.World, sid: str, actor: str,
                          rt: Optional[_RemoteTick] = None) -> Optional[Dict[str, Any]]:
    """Yeniden açmanın ve restart'ın durdurma adımı: oturum TAM adla çalışıyorsa `_remote_stop` + kapanma beklemesi
    (`READY_TIMEOUT_SECONDS`). None = devam edilebilir (durdu ya da zaten kapalıydı); aksi halde başarısızlık yanıtı
    (çağıran sonraki adıma GEÇMEZ). Durdurmadan sonra tick görüntüsü o host için yenilenir (`rt.refresh`)."""
    fresh_host, row = _remote_running_row(host, name, rt)
    if not fresh_host:
        return {"ok": False, "error": "host_down", "code": "host_down", "host": host}
    if row is None:
        return None          # zaten kapalı (devir sonrası oturum kendisi çıkmış): durdurulacak bir şey yok
    res = _remote_stop(name, host, world, sid, actor, rt)
    if not res.get("ok"):
        return res
    closed = _remote_wait_closed(host, name)
    if rt is not None:
        rt.refresh(host)
    if not closed:
        return {"ok": False, "error": f"stop sent but {name!r} still running on {host} after "
                                      f"{int(READY_TIMEOUT_SECONDS)} s", "code": "stop_not_confirmed", "host": host}
    return None


def _remote_respawn(name: str, host: str, project: Optional[sw.Project], cfg: sw.Config, world: sw.World,
                    rt: Optional[_RemoteTick] = None) -> Dict[str, Any]:
    """Uzak yeniden açma (devirden sonra READY / süre doldu / oturum gitti): durdur (`_remote_stop_and_wait`) → YENİ
    konuşmayla başlat (`_ensure_running_remote`, `fresh=True`) → yönerge (`_give_directive`, `start_if_stopped=False`:
    ikinci bir başlatma asla gitmez). Bir adım başarısızsa sonrakine GEÇİLMEZ, `remote_respawn` olayı adımı söyler.
    Yarım kalan yeniden açmada oturum kapalı kalırsa proje sonraki tick'lerde normal `start` yolundan açılır (proje
    aktif fazdaysa). Kart işaretlenmez (uzak projenin kartı yok, A1)."""
    paths = sw.paths_for(cfg.sid)
    if project is None:
        return {"ok": False, "error": "not a steward project", "host": host}

    def failed(step: str, res: Dict[str, Any]) -> Dict[str, Any]:
        sw.log_event("remote_respawn", paths=paths, name=name, host=host, step=step, ok=False,
                     error=str(res.get("error") or ""), code=str(res.get("code") or ""))
        return dict(res, ok=False, step=step, host=host)

    stopped = _remote_stop_and_wait(name, host, world, cfg.sid, "engine", rt)
    if stopped is not None:
        return failed("stop", stopped)
    model, effort = sw.phase_model_effort(project, cfg)
    res = _ensure_running_remote(name, host, model, effort, True, rt)
    if not res.get("ok"):
        return failed("start", res)
    if rt is not None:
        rt.refresh(host)
    res = _give_directive(project, "", reason="respawn", session_name=name, cfg=cfg, start_if_stopped=False,
                          host=host, rt=rt)
    if not res.get("ok"):
        return failed("directive", res)
    sw.log_event("remote_respawn", paths=paths, name=name, host=host, step="done", ok=True)
    return dict(res, host=host)


def _defer_destructive(action: sw.Action, paths: Any, world: Optional[sw.World]) -> bool:
    """Host'un tick bütçesine takılan (`destructive_budget`) uzak eylemi bir SONRAKİ tick'e bırak: `plan_tick` onu
    planlarken izini (`ho_pending` / `done_pending`) silmişti, yeniden yazılmazsa eylem kaybolurdu. Karar yine saf
    çekirdekte: yeniden açma `ho_pending`e süresi dolmuş damgayla döner (READY/süre kuralı yeniden değerlendirilir),
    STEWARD-DONE durdurması `done_pending`e. Diğer durdurmalar (boşta durdurma) zaten kendiliğinden yeniden planlanır;
    kapatma (`shutdown`) durdurması geri yazılmaz. Dönen: iz yeniden yazıldı mı."""
    try:
        with sw.steward_lock(paths):
            state = sw.load_state(paths)
            if action.kind == "respawn":
                state.setdefault("ho_pending", {})[action.name] = 0.0      # 0 = süre çoktan doldu
            elif action.kind == "stop" and action.reason.startswith("STEWARD-DONE"):
                proj = (world.project_key(action.name) if world is not None else "") or action.name
                state.setdefault("done_pending", {})[action.name] = proj
            else:
                return False
            sw.save_state(state, paths)
    except sw.LockTimeout as e:
        sw.log_event("remote_deferred", paths=paths, kind=action.kind, name=action.name, requeued=False, error=str(e))
        return False
    sw.log_event("remote_deferred", paths=paths, kind=action.kind, name=action.name, requeued=True)
    return True


def _apply(action: sw.Action, cfg: sw.Config, projects: Dict[str, sw.Project],
           world: Optional[sw.World] = None, rt: Optional[_RemoteTick] = None) -> Dict[str, Any]:
    """Tek eylemi uygula. Kayıtlar `cfg.sid`'in deposuna; oturuma dokunan eylemler `_target` kapısından (kimlikli).
    Hedef UZAK bir projedeyse (`_locate`) oturuma dokunan HER tür (`start`/`deliver_answer` dahil) `_target`ın host
    kapılarından geçer (`rt`: tick'in tazelik görüntüsü + devre kesici) ve uzak yoldan uygulanır; yerel yola (yerel
    adaş oturuma) ASLA düşmez. Yıkıcı türler (stop/respawn) uzakta `_remote_stop`un ek koşullarıyla (A4)."""
    k = action.kind
    name = action.name
    paths = sw.paths_for(cfg.sid)
    host = ""
    if k in _SESSION_KINDS:
        host = _locate(name, projects, world or _world(cfg.sid, cfg))[0]
        if host:
            denied = _target(name, "engine", projects, k, sid=cfg.sid, world=world, host=host, rt=rt)
            if denied is not None:
                return denied
    if k in ("handover", "respawn", "stop") and not host:   # deliver_answer kayıtsız oturuma da gider (cevap kaynağına); start zaten projects'e bağlı
        denied = _target(name, "engine", projects, k, sid=cfg.sid, world=world)
        if denied is not None:
            return denied
    if k == "handover":
        return _remote_handover(name, host, rt) if host else _act("handover", name, lang=cfg.lang)
    if host and k in ("stop", "respawn"):      # uzak yıkıcı: yerel yola (yerel adaşı öldüren `_act("stop")`) düşmez
        w = world or _world(cfg.sid, cfg)
        if k == "stop":
            return _remote_stop(name, host, w, cfg.sid, "engine", rt)
        return _remote_respawn(name, host, _project_for_session(name, projects, w), cfg, w, rt)
    if k == "respawn":
        if _running(name) is not None:
            res = _act("stop", name, lang=cfg.lang)
            if not res.get("ok"):
                return res
        if name == cfg.brain_name:
            return brain_start(cfg, fresh=True)   # devirden sonra YENİ konuşma (aynı şişmiş bağlam taşınmasın; notlar NOTLAR.md'de)
        p = _project_for_session(name, projects, world)
        model, effort = sw.phase_model_effort(p, cfg) if p else ("", "")
        # Devirden sonra YENİ konuşma (`--new`): `--resume` aynı şişmiş bağlamı (her tur yeniden okunan ~400K token)
        # ve eski modelin önbelleğini taşırdı. Devir özeti CLAUDE.md'de, yeni oturum onu kendisi okur.
        res = _ensure_running(name, model=model, effort=effort, lang=cfg.lang, fresh=True)
        if not res.get("ok") or p is None:
            return res
        sw.mark_card_stale(p.name)   # handover'da oturum işini yazdı: kart, proje durunca yeniden özetlensin
        return _give_directive(p, "", reason="respawn", session_name=name, cfg=cfg, host="")
    if k == "start":
        p = projects.get(name)
        if p is None:
            return {"ok": False, "error": "not a steward project"}
        q = None
        if action.payload.get("question_id"):
            q = next((x for x in sw.load_questions(paths) if x.id == action.payload["question_id"]), None)
        return _give_directive(p, "", answer=q, reason=action.reason, cfg=cfg, host=host, rt=rt)
    if k == "stop":
        return _act("stop", name, lang=cfg.lang)
    if k == "deliver_answer":
        q = next((x for x in sw.load_questions(paths) if x.id == action.payload.get("question_id")), None)
        if q is None:
            return {"ok": False, "error": "question gone"}
        p = projects.get(q.project) or sw.Project(name=q.project)
        extra = "Cevaba göre devam et." if cfg.lang != "en" else "Continue according to the answer."
        by_id = {x.id: x for x in sw.load_questions(paths)}
        more = [by_id[i] for i in action.payload.get("more_ids") or []
                if i in by_id and by_id[i].answer and not by_id[i].delivered_at]
        res = _give_directive(p, extra, answer=q, more=more, start_if_stopped=False, reason="answer", session_name=name, cfg=cfg,
                              host=host, rt=rt)
        if not res.get("ok") and q.project not in projects:
            # Kayıtlı proje olmayan (ad hoc) oturum kapanmış ya da yazı kabul etmiyor: her tick yeniden deneme,
            # bırak (cevap kayıtta durur, kimse beklemiyor).
            sw.mark_delivered(q.id, paths)
            sw.log_event("answer_undeliverable", paths=paths, id=q.id, session=name, error=res.get("error", ""))
        return res
    if k == "deliver_job":
        if not host:      # uzak hedef yukarıda (host kapılarıyla) denetlendi
            denied = _target(name, "engine", projects, k, sid=cfg.sid, world=world)
            if denied is not None:
                return denied
        return _deliver_job(action, cfg, projects, host=host, rt=rt)
    if k == "ask_user":
        q = sw.add_question(action.payload.get("project") or name, action.payload.get("text") or "", source=name,
                            routine=bool(action.payload.get("routine")), paths=paths)
        if q.status == "open" and q.routine:   # işleyiş sorusu: telefona gitmez, beynin turunda cevaplanır
            return {"ok": True, "id": q.id, "notified": False, "routine": True}
        if q.status != "open":   # yakın zamanda cevaplanmış soru yeniden soruldu: telefona yeni soru gitmez, cevap yeniden iletilir
            return {"ok": True, "id": q.id, "notified": False, "reasked": True}
        notified = _notify(cfg, f"{_ask_prefix(q.project, cfg.sid)} {q.text}\n→ {sw.ask_hint(q.id, cfg.sid)}")
        return {"ok": True, "id": q.id, "notified": notified}
    if k == "escalate_routine":
        q = sw.escalate_routine(action.payload.get("question_id") or "", paths)
        if q is None:
            return {"ok": False, "error": "not an open routine question"}
        notified = _notify(cfg, f"{_ask_prefix(q.project, cfg.sid)} {q.text}\n→ {sw.ask_hint(q.id, cfg.sid)}")
        return {"ok": True, "id": q.id, "notified": notified}
    if k == "idea":
        i = sw.add_idea(action.payload.get("text") or "", source=name, paths=paths)
        return {"ok": True, "id": i.id}
    if k == "set_phase":
        sw.upsert_project(name, paths=paths, phase=action.payload.get("phase"))
        return {"ok": True}
    if k == "tour":
        # default: eski çağrı biçimi; diğer kimlikte kimliğin cfg/world'ü açıkça verilir (kendi beyni, kendi projeleri)
        res = run_tour(action.payload.get("items") or [], **({} if cfg.sid == "default" else {"cfg": cfg, "world": world}))
        with sw.steward_lock(paths):
            state = sw.load_state(paths)
            if res.get("ok"):
                if state.get("tour_fail"):
                    state["tour_fail"] = 0
                    sw.save_state(state, paths)
                return res
            fails = int(state.get("tour_fail") or 0) + 1
            state["tour_fail"] = fails
            sw.save_state(state, paths)
        if fails >= TOUR_FAILS_BEFORE_RESTART:
            # Beynin giriş kutusu takılı (gönderilmemiş yapıştırma birikir): oturumu yeniden aç, sayacı sıfırla.
            sw.log_event("brain_unstick", paths=paths, fails=fails, error=res.get("error", ""))
            rb = brain_restart_for_stuck_input(cfg)
            with sw.steward_lock(paths):
                state = sw.load_state(paths)
                state["tour_fail"] = 0
                sw.save_state(state, paths)
            res = dict(res, restarted=bool(rb.get("ok")))
        return res
    return {"ok": False, "error": f"unknown action {k}"}


def _deliver_job(action: sw.Action, cfg: sw.Config, projects: Dict[str, sw.Project], host: Optional[str] = None,
                 rt: Optional[_RemoteTick] = None) -> Dict[str, Any]:
    """`deliver_job`: iş sonucu (ya da onay bekliyor bildirimi) projenin ÇALIŞAN oturumuna, `deliver_answer` ile aynı
    güvenli yoldan (`_give_directive`, `start_if_stopped=False`) iletilir. Başarıda `delivered`/`notified` işaretlenir
    (aynı iş iki kez iletilmez); başarısızlıkta deneme sayacı (üst sınırda bırakılır, kayıt jobs.json'da kalır)."""
    paths = sw.paths_for(cfg.sid)
    jid, svc, stage = action.payload.get("job_id"), str(action.payload.get("service") or ""), str(action.payload.get("stage") or "result")
    job = sj.find_job(sj.load_jobs(paths), jid, svc)
    if job is None:
        return {"ok": False, "error": "job gone"}
    if sj.pending_stage(job) != stage:
        return {"ok": True, "skipped": "already delivered"}
    p = projects.get(str(job.get("project") or ""))
    if p is None:
        return {"ok": False, "error": "not a steward project"}
    mark = lambda: sj.mark_delivered(jid, svc, stage, paths=paths)   # noqa: E731
    if _already_sent(mark, cfg.sid, f"job:{stage}", f"{svc}#{jid}"):
        return {"ok": True, "skipped": "already sent"}
    res = _give_directive(p, sj.build_job_message(job, stage, cfg.lang), start_if_stopped=False, reason="job",
                          session_name=action.name, cfg=cfg, host=host or None, rt=rt)
    if res.get("ok"):
        _mark_after_send(mark, cfg.sid, f"job:{stage}", f"{svc}#{jid}")      # mesaj gitti: kilit zaman aşımı yinelenmeye yol açmasın
        sw.log_event("job_delivered", paths=paths, service=svc, id=jid, project=p.name, stage=stage, session=action.name)
    elif sj.mark_attempt(jid, svc, paths) >= sj.DELIVER_MAX_ATTEMPTS:
        sw.log_event("job_undeliverable", paths=paths, service=svc, id=jid, project=p.name, error=str(res.get("error") or ""))
    return res


def _note_conflicts(ctx: StewardContext, index: Dict[str, Any], own_names: set, now: float) -> None:
    """Bu kimliğin `projects.json`'unda olup başka kimlikte de görünen adlar (elle düzenleme): ikisi de yönetmez
    (`World.own_projects` süzer). `ownership_conflict` olayı ad başına GÜNDE BİR; `ctx.conflicts` status uyarısı."""
    conflicts = index.get("conflicts") or {}
    mine = sorted(n for n in own_names if n in conflicts)
    ctx.conflicts = mine
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    for n in mine:
        if ctx.conflict_logged.get(n) != day:
            ctx.conflict_logged[n] = day
            sw.log_event("ownership_conflict", paths=ctx.paths, name=n, stewards=list(conflicts[n]))
            diag_log("steward_ownership_conflict", sid=ctx.sid, name=n, stewards=list(conflicts[n]))


# ── dış iş kuyruğu (varaka) poll ──────────────────────────────────────────────
#
# Açık işler kimlik başına küçük bir arka plan thread'inde yoklanır (`_CTX.lock` / `_LOCK` DIŞINDA: bir servis
# gecikmesi tick'i ve beynin MCP çağrılarını bekletmesin). Zaman aşımı kısa, hata yutulur ve loglanır.
# İletim kararı bir SONRAKİ tick'in saf `plan_job_deliveries`ında (observe'da `would:deliver_job`).

_JOBS_BACKGROUND = True            # testler False yapıp işi satır içi koşturur
_JOBS_LOCKS: Dict[str, threading.Lock] = {}
_JOBS_GUARD = threading.Lock()


def _notify_approvals(cfg: sw.Config) -> int:
    """Onay bekleyen ve sahibine henüz bildirilmemiş işler için TEK telefon bildirimi (onay yalnız insan adminde,
    varaka'da). Bildirim kaydı `approval_phone` bayrağı; proje oturumuna bildirim ayrı (`deliver_job`)."""
    paths = sw.paths_for(cfg.sid)
    n = 0
    for j in sj.load_jobs(paths):
        if j.get("state") != "awaiting_approval" or j.get("approval_phone"):
            continue
        text = (f"{_ask_prefix(str(j.get('project') or ''), cfg.sid)} {j.get('service')} işi #{j.get('id')} "
                f"({j.get('kind')}) ONAY BEKLİYOR: varaka'da insan yönetici onaylamalı")
        if _notify(cfg, text):
            n += 1
        sj.update_records({(str(j.get("service")), str(j.get("id"))): {"approval_phone": True}}, paths)
    return n


def _poll_job(cfg: sw.Config, force: bool = False) -> Dict[str, Any]:
    res = sj.poll_jobs(cfg.sid, force=force)
    _notify_approvals(cfg)
    return res


def jobs_tick(cfg: sw.Config, force: bool = False) -> bool:
    """tick_once'ın iş kuyruğu adımı: yoklanacak açık iş varsa (ya da onay bildirimi bekliyorsa) arka planda bir poll.
    Kimlik başına tek iş (üst üste binmez). İş yoksa dosya okumaktan başka bir şey yapmaz."""
    paths = sw.paths_for(cfg.sid)
    jobs = sj.load_jobs(paths)
    if not jobs:
        return False
    now = time.time()
    if not (sj.due_jobs(jobs, now, force=force)
            or any(j.get("state") == "awaiting_approval" and not j.get("approval_phone") for j in jobs)):
        return False
    with _JOBS_GUARD:
        lock = _JOBS_LOCKS.setdefault(cfg.sid, threading.Lock())
    if not lock.acquire(blocking=False):
        return False

    def _work() -> None:
        try:
            _poll_job(cfg, force)
        except Exception as e:
            diag_log("steward_jobs_poll_crashed", sid=cfg.sid, error=repr(e))
        finally:
            lock.release()

    if _JOBS_BACKGROUND:
        threading.Thread(target=_work, daemon=True, name=f"steward-jobs-{cfg.sid}").start()
    else:
        _work()
    return True


_FABLE_WARN_AT: Dict[str, float] = {}


def _audit_fable_rule(sid: str, paths: Any) -> None:
    """Model kuralı denetimi: penceredeki Fable alt ajan sayısı 1'i aşarsa `fable_rule` olayı loglanır (10 dk'da bir).
    Yalnız izleme; `model_usage` önbelleği boşsa (ilk çağrı) sessizce geçer."""
    try:
        from .. import model_usage
        mu = model_usage.summary() or {}
    except Exception:
        return
    n = int(mu.get("fable_agents") or 0)
    if n > 1 and time.time() - _FABLE_WARN_AT.get(sid, 0.0) > 600:
        _FABLE_WARN_AT[sid] = time.time()
        sw.log_event("fable_rule", paths=paths, fable_agents=n, window_minutes=mu.get("window_minutes"),
                     top=[x.get("label") for x in (mu.get("fable_top") or [])[:3]])


def tick_once(trigger: str = "timer", sid: str = "default", *, starts_left: Optional[int] = None,
              cards: bool = True, index: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """`sid` kimliği için bir tick: görünümleri topla → kararlar (`plan_tick(world=...)`) → uygula → state kaydet.
    Elle (`/api/steward/tick`, `py/cops steward tick`) de çağrılır; döngü kapalıyken bile çalışır (kullanıcı bilerek
    istedi). Kilit KİMLİK BAŞINA (`ctx.lock`): A'nın tick'i B'nin elle eylemini bekletmez. Okuma/yazma yalnız
    `paths_for(sid)` yollarında. `starts_left`: döngü turunun kalan makine geneli başlatma hakkı (None = sınırsız,
    elle tick). `cards=False`: kart adımını çağıran yapar (döngü turu tek kart işi koşturur)."""
    ctx = _ctx(sid)
    with ctx.lock:
        cfg = steward_config(sid)
        paths = ctx.paths
        t0 = time.time()
        applied: List[Dict[str, Any]] = []
        dry_applied: List[Dict[str, Any]] = []
        started = 0
        error = ""
        try:
            projects = sw.load_projects(paths)
            idx = index if index is not None else _ownership_index()
            world = _world(sid, cfg, starts_left, idx)
            # Uzak tazelik anlık görüntüsü tick başında BİR KEZ: `unavailable`, görünümler ve eylem ön denetimleri aynı
            # görüntüden (iki ayrı önbellek okuması arasında host düşerse proje "çalışmıyor" sanılıp başlatılmasın).
            rt = _remote_snapshot(set(world.hosts.values()), t0)
            world = _with_availability(world, cfg, t0, rt)
            # Uzak proje yoksa çağrı biçimi eskisiyle AYNI (altın testler `_collect_views`/`_apply`ı bu biçimle değiştirir).
            rkw: Dict[str, Any] = {"rt": rt} if world.hosts else {}
            _note_conflicts(ctx, idx, set(projects), t0)
            views = _collect_views(cfg, **rkw)
            with sw.steward_lock(paths):     # state RMW atomik (CLI süreci de aynı dosyaya yazar)
                actions, new_state = sw.plan_tick(views, projects, sw.load_state(paths), cfg, t0,
                                                  sw.load_questions(paths), sw.load_ideas(paths), world=world)
                job_actions, new_state = sj.plan_job_deliveries(views, projects, sj.load_jobs(paths), actions, new_state, t0, world)
                actions = actions + job_actions     # iş sonucu iletimi (varaka kuyruğu): `plan_tick`e DOKUNMAZ, aynı observe/_target yolundan
                actions, dry, new_state = sw.observe_filter(actions, cfg.mode, new_state, t0)
                sw.save_state(new_state, paths)
            for a in dry:
                host = _locate(a.name, projects, world)[0] if a.kind in _SESSION_KINDS else ""
                _remember_dry(a, ctx, host=host)
                dry_applied.append(dict({"kind": a.kind, "name": a.name, "reason": a.reason, "dry": True},
                                        **({"host": host} if host else {})))
            for a in actions:
                if a.kind == "start":
                    started += 1      # deneme sayılır (başarısız açılış da bir spawn dalgası olabilir)
                try:
                    res = _apply(a, cfg, projects, world, **rkw)
                except Exception as e:  # tek eylem tick'i düşürmesin
                    res = {"ok": False, "error": repr(e)}
                    diag_log("steward_action_crashed", sid=sid, kind=a.kind, name=a.name, error=repr(e))
                if isinstance(res, dict) and res.get("code") == "destructive_budget":
                    _defer_destructive(a, paths, world)     # host'un bu tick'lik yıkıcı hakkı doldu: sonraki tick'e
                _remember(a, res, ctx)
                applied.append({"kind": a.kind, "name": a.name, "reason": a.reason, "ok": bool(res.get("ok")),
                                "detail": res.get("error") or ""})
                if res.get("host"):
                    applied[-1]["host"] = res["host"]
            _remote_tick_done(rt, paths)
        except Exception as e:
            error = repr(e)
            diag_log("steward_tick_crashed", sid=sid, error=repr(e))
        ctx.last_tick.update({"at": t0, "trigger": trigger, "actions": len(applied), "dry": len(dry_applied), "error": error})
        sw.log_event("tick", paths=paths, trigger=trigger, mode=cfg.mode, n=len(applied), dry=len(dry_applied), error=error)
        if applied:
            web_ws.notify_status_changed()
        if cfg.enabled:    # günlük özet + log sıkıştırma kimlik başına (kendi logu, kendi daily/'i)
            _audit_fable_rule(sid, paths)
            try:
                maybe_daily_summary(cfg, t0)
            except Exception as e:
                diag_log("steward_summary_crashed", error=repr(e))
    if cards:
        try:
            card_tick(cfg)
        except Exception as e:
            diag_log("steward_card_tick_crashed", sid=sid, error=repr(e))
    try:
        jobs_tick(cfg)
    except Exception as e:
        diag_log("steward_jobs_tick_crashed", sid=sid, error=repr(e))
    return {"ok": not error, "error": error, "actions": applied, "dry": dry_applied, "mode": cfg.mode, "at": t0,
            "started": started}


def passive_scan(sid: str = "default", *, views: Optional[List[sw.SessionView]] = None,
                 index: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Değnekçi KAPALIYKEN salt kayıt: proje oturumlarının yanıtlarındaki STEWARD-ASK/-ROUTINE/-BLOCKED/-IDEA satırları
    soru/fikir olarak kaydedilir (`sw.plan_markers`); oturuma HİÇBİR şey gönderilmez, faz/durdurma/başlatma yok.
    Kapalıyken düşen soru kaybolmasın, açınca cevap iletimi çalışsın."""
    ctx = _ctx(sid)
    with ctx.lock:
        cfg = steward_config(sid)
        paths = ctx.paths
        try:
            projects = sw.load_projects(paths)
            if not projects and sid != "default":
                return {"ok": True, "recorded": 0}
            world = _world(sid, cfg, 0, index if index is not None else _ownership_index())
            vs = views if views is not None else _collect_views(cfg)
            with sw.steward_lock(paths):
                actions, new_state = sw.plan_markers(vs, projects, sw.load_state(paths), cfg, world=world)
                sw.save_state(new_state, paths)
            recorded = 0
            for a in actions:
                try:
                    res = _apply(a, cfg, projects, world)
                except Exception as e:
                    res = {"ok": False, "error": repr(e)}
                    diag_log("steward_action_crashed", sid=sid, kind=a.kind, name=a.name, error=repr(e))
                _remember(a, res, ctx)
                recorded += 1 if res.get("ok") else 0
            if recorded:
                sw.log_event("passive_scan", paths=paths, n=recorded)
                web_ws.notify_status_changed()
            return {"ok": True, "recorded": recorded}
        except Exception as e:
            diag_log("steward_passive_scan_crashed", sid=sid, error=repr(e))
            return {"ok": False, "error": repr(e)}


# ── kontrollü kapatma (`py/cops steward shutdown`) ────────────────────────────

def shutdown_start(sid: str = "default", *, stop_loop: bool = True) -> Dict[str, Any]:
    """Kapatmayı başlat: döngüyü kapat (yeni iş/direktif/açılış olmasın) ve `state["shutdown"]` yaz. Adımları döngü her
    tick'te `shutdown_tick` ile ilerletir (kapalı kimlikte de çalışır). Zaten sürüyorsa yeniden başlatmaz."""
    from ..settings import save_settings
    ctx = _ctx(sid)
    with ctx.lock, sw.steward_lock(ctx.paths):
        state = sw.load_state(ctx.paths)
        if state.get("shutdown") and not state["shutdown"].get("done"):
            return {"ok": True, "already": True, "shutdown": state["shutdown"]}
        state["shutdown"] = {"started": time.time(), "items": {}}
        sw.save_state(state, ctx.paths)
    if stop_loop:
        save_settings({"steward": {"enabled": "off"}} if sid == "default" else {"stewards": {sid: {"enabled": "off"}}})
    sw.log_event("shutdown_start", paths=ctx.paths)
    return {"ok": True, "started": True}


def shutdown_tick(sid: str = "default", views: Optional[List[sw.SessionView]] = None) -> Optional[Dict[str, Any]]:
    """Süren kapatmayı bir adım ilerlet (yoksa None). Eylemler `_apply` ile (observe kipi ATLANIR: kullanıcı açıkça kapatıyor),
    yine de `_target` kapısından geçer (yalnız kimliğin kendi projeleri + beyni)."""
    ctx = _ctx(sid)
    with ctx.lock:
        cfg = steward_config(sid)
        paths = ctx.paths
        state0 = sw.load_state(paths)
        sd0 = state0.get("shutdown")
        if not sd0 or sd0.get("done"):
            return None
        if cfg.enabled:    # kapatma başlayınca döngü kapatılmıştı; yeniden açılmışsa (`steward up`) kapatma İPTAL
            with sw.steward_lock(paths):
                state = sw.load_state(paths)
                state["shutdown"] = dict(sd0, done=time.time(), cancelled=True)
                sw.save_state(state, paths)
            sw.log_event("shutdown_cancelled", paths=paths)
            return None
        projects = sw.load_projects(paths)
        world = _world(sid, cfg, 0, _ownership_index())
        vs = views if views is not None else _collect_views(cfg)
        now = time.time()
        actions, sd, done = sw.plan_shutdown(vs, projects, sd0, cfg, now, world=world)
        for a in actions:
            try:
                res = _apply(a, cfg, projects, world)
            except Exception as e:
                res = {"ok": False, "error": repr(e)}
                diag_log("steward_action_crashed", sid=sid, kind=a.kind, name=a.name, error=repr(e))
            _remember(a, res, ctx)
            if not res.get("ok"):                      # eylem başarısız: adımı bir sonraki tick'te yeniden dene
                it = (sd.get("items") or {}).get(a.name)
                if it is not None:
                    it["stage"] = "wait" if a.kind == "handover" else "ho"
                    done = False
        if done:
            sd["done"] = now
        with sw.steward_lock(paths):
            state = sw.load_state(paths)
            state["shutdown"] = sd
            sw.save_state(state, paths)
        if done:
            sw.log_event("shutdown_done", paths=paths, items={n: i["stage"] for n, i in sd["items"].items()})
        web_ws.notify_status_changed()
        return {"ok": True, "done": done, "items": {n: i["stage"] for n, i in sd["items"].items()}}


def http_shutdown(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    if data.get("actor") == "brain":
        return {"ok": False, "error": "brain cannot shut the steward down"}
    if data.get("status"):
        sd = sw.load_state(sid).get("shutdown") or {}
        return {"ok": True, "shutdown": sd, "items": {n: i.get("stage") for n, i in (sd.get("items") or {}).items()},
                "done": bool(sd.get("done"))}
    return shutdown_start(sid)


def tick_round(trigger: str = "timer") -> List[Dict[str, Any]]:
    """Döngünün bir turu: `steward_ids()` sırasıyla, YALNIZ `enabled` kimlikler SIRAYLA tick'lenir (aynı anda tek spawn
    dalgası). Bir kimliğin hatası yutulup loglanır, diğerleri yine tick'lenir. Makine geneli `max_starts_total` bütçesi
    kimlikler arasında taşınır (`starts_left`); `max_active_total` her tick'in kendi görünümünden (diğer kimliklerin
    çalışan projeleri dahil) `plan_tick`'te uygulanır. Kart işi turda bir kez, tüm etkin kimlikler için."""
    base = steward_config()
    starts_left = max(0, base.max_starts_total)
    results: List[Dict[str, Any]] = []
    enabled: List[sw.Config] = []
    disabled: List[str] = []
    for sid in steward_ids():
        try:
            cfg = steward_config(sid)
            if not cfg.enabled:
                disabled.append(sid)
                continue
            enabled.append(cfg)
            res = tick_once(trigger, sid, starts_left=starts_left, cards=False)
            starts_left = max(0, starts_left - int(res.get("started") or 0))
            results.append(dict(res, sid=sid))
        except Exception as e:   # bir kimlik diğerlerini atlatmasın
            diag_log("steward_tick_round_crashed", sid=sid, error=repr(e))
            results.append({"ok": False, "sid": sid, "error": repr(e)})
    try:
        cards_round(enabled)
    except Exception as e:
        diag_log("steward_card_tick_crashed", error=repr(e))
    for sid in steward_ids():    # süren kontrollü kapatmalar (kapalı kimlikte de ilerler)
        try:
            shutdown_tick(sid)
        except Exception as e:
            diag_log("steward_shutdown_crashed", sid=sid, error=repr(e))
    if disabled:    # kapalı kimlikler: yalnız soru/fikir kaydı (oturuma dokunmaz)
        try:
            views = _collect_views(steward_config(disabled[0]))
            idx = _ownership_index()
            for sid in disabled:
                passive_scan(sid, views=views, index=idx)
        except Exception as e:
            diag_log("steward_passive_scan_crashed", error=repr(e))
    return results


def _loop() -> None:
    while True:
        cfg = steward_config()
        time.sleep(max(15, cfg.tick_seconds))
        try:
            tick_round("timer")
        except Exception as e:
            diag_log("steward_loop_crashed", error=repr(e))


def start_loop() -> None:
    global _loop_started
    if _loop_started:
        return
    _loop_started = True
    threading.Thread(target=_loop, daemon=True, name="steward-loop").start()


# ── özet / HTTP ───────────────────────────────────────────────────────────────

_SUMMARY_TTL = 5.0


def summary(running_names: Optional[set] = None, sid: str = "default") -> Dict[str, Any]:
    """`/api/status`'a giden HAFİF alan (`orch` gibi local-only). ~2 sn'lik WS/poll cadence'ine bindiği için
    5 sn önbellekli (kimlik başına); `running_names` verilirse (status payload'ın kendi taraması) ayrıca proc taranmaz.
    `ownership_conflicts` yalnız çakışma varken eklenir (status uyarısı; tek kimlikte anahtarlar aynı kalır)."""
    ctx = _ctx(sid)
    cache = ctx.summary_cache
    now = time.monotonic()
    hit = cache["value"]
    if hit is not None and cache["until"] > now:
        return hit
    cfg = steward_config(sid)
    paths = ctx.paths
    projects = sw.load_projects(paths)
    questions = sw.load_questions(paths)
    state = sw.load_state(paths)
    brain_running = (cfg.brain_name in running_names) if running_names is not None else (_running(cfg.brain_name) is not None)
    value = {
        "enabled": cfg.enabled,
        "mode": cfg.mode,
        "tick_seconds": cfg.tick_seconds,
        "projects": sw.summarize_projects(projects),
        "open_questions": len(sw.open_questions(questions)),
        "ideas_new": sum(1 for i in sw.load_ideas(paths) if i.status == "new"),
        "pending_items": int(state.get("pending_items") or 0),
        "last_tick": dict(ctx.last_tick),
        "last_tour": state.get("last_tour") or 0.0,
        "brain": {"name": cfg.brain_name, "running": brain_running},
        "recent": ctx.recent[:5],
    }
    if ctx.conflicts:
        value["ownership_conflicts"] = list(ctx.conflicts)
    cache.update(until=now + _SUMMARY_TTL, value=value)
    return value


def stewards_summary(running_names: Optional[set] = None) -> List[Dict[str, Any]]:
    """`/api/status` `stewards` dilimi ve `/api/steward/list`: her kimlik için hafif özet (kimlik, ad, açık/kapalı, kip,
    proje/soru/fikir sayıları, beyin). `summary()` kimlik başına 5 sn önbellekli. Default'un ALANLARI `/api/status`
    `steward` diliminde AYNEN durur (eski panel bozulmaz); burası yenidir."""
    out: List[Dict[str, Any]] = []
    for sid in steward_ids():
        try:
            cfg = steward_config(sid)
            sm = summary(running_names, sid)
        except Exception as e:        # bozuk bir kimlik listeyi düşürmesin
            diag_log("steward_list_failed", sid=sid, error=repr(e))
            continue
        row = {"id": sid, "label": cfg.label, "enabled": sm["enabled"], "mode": sm["mode"],
               "projects": sm["projects"], "project_count": sum(sm["projects"].values()),
               "open_questions": sm["open_questions"], "ideas_new": sm["ideas_new"],
               "pending_items": sm["pending_items"], "brain": sm["brain"]}
        if sm.get("ownership_conflicts"):
            row["ownership_conflicts"] = sm["ownership_conflicts"]
        out.append(row)
    return out


def http_list() -> Dict[str, Any]:
    return {"ok": True, "stewards": stewards_summary()}


def invalidate_summary(sid: Optional[str] = None) -> None:
    """`sid` verilmezse TÜM kimliklerin özet önbelleği."""
    if sid:
        ctxs = [_ctx(sid)]
    else:
        with _CTX_GUARD:
            ctxs = list(_CTX.values())
    for ctx in ctxs:
        ctx.summary_cache["until"] = 0.0


def _project_dict(p: sw.Project, running: Optional[set] = None,
                  cards: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    d = dataclasses.asdict(p)
    if running is not None:
        d["running"] = p.name in running
    card = (cards if cards is not None else {p.name: sw.load_card(p.name)}).get(p.name) or {}
    d["next_step"] = sw.card_one_liner(card)
    d["card_updated_at"] = float(card.get("updated_at") or 0.0)
    return d


def http_state(sid: str = "default") -> Dict[str, Any]:
    ctx = _ctx(sid)
    cfg = steward_config(sid)
    paths = ctx.paths
    projects = sw.load_projects(paths)
    live = find_sessions(measure_cpu=False)
    world = _world(sid, cfg)
    remote_running = _remote_running_listing(world)
    running_projects = _running_names_for(live, projects, world, remote=remote_running)
    cards = sw.load_cards()
    questions = [dataclasses.asdict(q) for q in sw.open_questions(paths=paths)]
    for q in questions:       # uzak projenin sorusu host'u taşır (panel rozeti); yerelde alan HİÇ eklenmez
        if world.host_of(str(q.get("project") or "")):
            q["host"] = world.host_of(str(q["project"]))
    out = {
        "ok": True,
        "config": dataclasses.asdict(cfg),
        "summary": summary(sid=sid),
        "projects": [_project_dict(p, running_projects, cards)
                     for p in sorted(projects.values(), key=lambda p: (p.priority, p.name))],
        "running": [{"name": s.name, "cwd": s.cwd, "cli": s.cli, "model": s.model} for s in live] + remote_running,
        "questions": questions,
        "ideas": [dataclasses.asdict(i) for i in sw.load_ideas(paths) if i.status == "new"],
        "recent": ctx.recent,
    }
    if any(p.host for p in projects.values()):       # uzak proje yoksa anahtar HİÇ eklenmez (yerel çıktı aynı)
        out["remote_hosts"] = remote_health({p.host for p in projects.values() if p.host})
    return out


def http_projects(sid: str = "default") -> Dict[str, Any]:
    cards = sw.load_cards()
    return {"ok": True, "projects": [_project_dict(p, None, cards) for p in sw.load_projects(sid).values()]}


def http_questions(status: str = "open", sid: str = "default") -> Dict[str, Any]:
    qs = sw.load_questions(sid)
    if status == "open":
        qs = [q for q in qs if q.status == "open"]
    elif status == "answered":
        qs = [q for q in qs if q.status == "answered"]
    return {"ok": True, "questions": [dataclasses.asdict(q) for q in qs]}


def http_ideas(status: str = "new", sid: str = "default") -> Dict[str, Any]:
    ideas = sw.load_ideas(sid)
    if status and status != "all":
        ideas = [i for i in ideas if i.status == status]
    return {"ok": True, "ideas": [dataclasses.asdict(i) for i in ideas]}


_EXPORT_FILES = {"todo": "TODO.md", "tbd": "TOBEDECIDED.md"}
_EXPORT_HEADING = "## Değnekçi fikirleri"


def _idea_project(idea: "sw.Idea", projects: Dict[str, "sw.Project"]) -> str:
    """Fikrin bağlı olduğu değnekçi projesi: `project`/`source` ya doğrudan proje adıdır ya da tarih sonekli oturum adı."""
    for cand in (idea.project, idea.source):
        cand = str(cand or "")
        if cand in projects:
            return cand
        m = re.match(r"^(.*?)\d{8}(?:_\d+)?$", cand)
        if m and m.group(1) in projects:
            return m.group(1)
    return ""


def _append_idea_item(path: str, idea: "sw.Idea", stamp: str) -> bool:
    """Fikri `path`in sonuna `- [ ]` maddesi olarak ekler (aynı fikir kimliği varsa dokunmaz). True = yazıldı."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    if idea.id in text:
        return False
    line = f"- [ ] (değnekçi fikri {idea.id}) {' '.join(idea.text.split())}"
    last_head = next((ln for ln in reversed(text.splitlines()) if ln.startswith("## ")), "")
    body = text.rstrip("\n")
    if last_head.startswith(_EXPORT_HEADING):
        new = f"{body}\n{line}\n"
    else:
        new = (f"{body}\n\n" if body else "") + f"{_EXPORT_HEADING} ({stamp})\n{line}\n"
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, path)
    return True


def http_idea_export(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Fikri projenin `TODO.md`/`TOBEDECIDED.md` dosyasına yazar. `kind`: todo|tbd; `target`: project (fikrin projesi) |
    all (kayıtlı tüm değnekçi projeleri). Fikir `exported` olur (listeden kalkar), kayıt fikrin üstünde durur."""
    kind = str(data.get("kind") or "")
    target = str(data.get("target") or "project")
    fname = _EXPORT_FILES.get(kind)
    if fname is None:
        return {"ok": False, "error": "kind must be todo or tbd"}
    if target not in ("project", "all"):
        return {"ok": False, "error": "target must be project or all"}
    idea = next((i for i in sw.load_ideas(sid) if i.id == str(data.get("id") or "")), None)
    if idea is None:
        return {"ok": False, "error": "unknown idea id"}
    projects = sw.load_projects(sid)
    names = [n for n in (_idea_project(idea, projects),) if n] if target == "project" else sorted(projects)
    if not names:
        return {"ok": False, "error": "idea has no steward project; choose target=all"}
    stamp = time.strftime("%Y-%m-%d")
    written: List[str] = []
    present: List[str] = []
    skipped: List[str] = []
    for n in names:
        if projects[n].host:      # uzak proje: yerel klasöre YAZILMAZ (aynı yolda yerel klasör olsa bile)
            skipped.append(n)
            continue
        cwd = _project_cwd(n)
        if not cwd or not os.path.isdir(cwd):
            skipped.append(n)
            continue
        try:
            (written if _append_idea_item(os.path.join(cwd, fname), idea, stamp) else present).append(n)
        except OSError as e:
            diag_log("steward_idea_export_failed", project=n, error=repr(e))
            skipped.append(n)
    if not written and not present:
        return {"ok": False, "error": "no project directory found", "skipped": skipped}
    sw.record_idea_export(idea.id, {"kind": kind, "target": target, "file": fname, "projects": written + present, "at": time.time()},
                          sid)
    sw.log_event("idea_export", paths=sid, id=idea.id, kind=kind, target=target, written=written, present=present, skipped=skipped)
    return {"ok": True, "written": written, "already": present, "skipped": skipped}


def http_log(n: int = 50, sid: str = "default") -> Dict[str, Any]:
    return {"ok": True, "entries": sw.tail_log(max(1, min(500, n)), sid)}


_NOT_OWN_PROJECT = {"ok": False, "error": "not a project of this steward"}


def _read_denied(name: str, sid: str) -> Optional[Dict[str, Any]]:
    """Okuma kapısı (plan (k)5): default dışı kimlik yalnız KENDİ projelerini okur (başka kimliğin projesi, servis,
    beyin, kayıtsız oturum red). `default` bugünkü gibi kısıtsız (insan/eski beyin)."""
    if sid == "default":
        return None
    if _project_for_session(name, sw.load_projects(sid), _world(sid)) is None:
        return dict(_NOT_OWN_PROJECT)
    return None


def http_context(name: str, docs: bool = False, sid: str = "default") -> Dict[str, Any]:
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    denied = _read_denied(name, sid)
    if denied is not None:
        return denied
    projects = sw.load_projects(sid)
    p = projects.get(name)
    remote = _name_host(name)
    s = None if remote else _running(name)       # uzak projede yerel adaş oturum/klasör/git okunmaz
    cwd = "" if remote else ((s.cwd if s is not None else "") or _project_cwd(name))
    out: Dict[str, Any] = {"ok": True, "name": name, "project": _project_dict(p) if p else None, "cwd": cwd,
                           "running": s is not None}
    if remote:
        out["host"] = remote
    if s is not None:
        provider = get_provider(s.cli)
        try:
            out["last_exchange"] = provider.last_exchange(s.cwd, s.sid) or {}
        except Exception:
            out["last_exchange"] = {}
        out["cli"], out["model"] = s.cli, s.model
    owner = _project_for_session(name, projects, _world(sid))
    card = sw.load_card(owner.name if owner is not None else name)
    if card is not None:
        out["card"] = card
        out["card_stale"] = bool(card.get("stale"))
    want_docs = card is None or docs     # kart varsa ham belge başları yerine kart; `docs=1` ikisini birden ister
    if remote:      # uzak: yalnız host-routed okumalar (term/chat + files/read), bütçeli; hata = boş/bilinmiyor
        rd = _remote_read_context(remote, name, want_docs)
        out["last_exchange"], out["remote_cwd"] = rd["last_exchange"], rd["remote_cwd"]
        if want_docs:
            out["docs"] = rd["docs"]
        out["git"] = REMOTE_GIT_UNKNOWN
        out["running"] = any(r["name"] == name for r in _remote_running_listing(_world(sid)))
    else:
        if want_docs:
            out["docs"] = {d: _read_head(cwd, d) for d in DOCS if cwd} if cwd else {}
            out["docs"] = {k: v for k, v in out["docs"].items() if v}
        out["git"] = _git_short(cwd)
    out["questions"] = [dataclasses.asdict(q) for q in sw.load_questions(sid) if q.project == name and q.status == "open"]
    return out


def http_file(name: str, rel: str, max_chars: int = MAX_FILE_READ_CHARS, sid: str = "default") -> Dict[str, Any]:
    denied = _read_denied(name, sid) if sw.valid_name(name) else None
    if denied is not None:
        return denied
    remote = _name_host(name) if sw.valid_name(name) else ""
    if remote:      # host-routed files/read: mutlak uzak yol = oturumun uzak klasörü + güvenli göreli yol; yerel dosya yok
        cwd = _remote_cwd(remote, name)
        if not cwd or not rel or "\x00" in rel or rel.startswith("/") or ".." in Path(rel).parts:    # yalnız sözcük denetimi
            return {"ok": False, "error": "unknown remote project folder or path outside project", "host": remote}
        text, truncated, ok = _remote_file_head(remote, name, cwd.rstrip("/") + "/" + rel, max_chars,
                                                REMOTE_READ_BUDGET_SECONDS)
        if not ok:
            return {"ok": False, "error": f"could not read {rel} on {remote}", "host": remote}
        return {"ok": True, "path": rel, "text": text, "truncated": truncated, "host": remote}
    cwd = _project_cwd(name)
    full = _safe_project_file(cwd, rel) if cwd else None
    if full is None:
        return {"ok": False, "error": "unknown project or path outside project"}
    try:
        with open(full, encoding="utf-8", errors="replace") as f:
            text = f.read(max_chars + 1)
    except OSError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "path": rel, "text": text[:max_chars], "truncated": len(text) > max_chars}


def _in_roster(name: str) -> bool:
    from .. import roster as roster_mod
    return name in {e.name for e in roster_mod.read_roster()}


def _in_remote_roster(name: str, host: str) -> bool:
    """Uzak projenin roster'ı: host'un TAZE `/api/status` önbelleğinde `registered` ve adı tam `name` olan satır
    (çalışan ya da kapalı; ağa gidilmez). Host kapalı/bilinmiyorsa False."""
    st = _remote.status(host)
    if not _host_fresh(st):
        return False
    rows = list(st.get("sessions") or []) + list(st.get("closed") or [])
    return any(isinstance(r, dict) and r.get("name") == name and r.get("registered", True) for r in rows)


def _project_running_anywhere(name: str, hosts: Any = ()) -> Optional[bool]:
    """Projenin (adı `name`e çözülen) bir oturumu çalışıyor mu: yerel süreç taraması + `hosts`taki uzak önbellek
    satırları. True = çalışıyor; False = hiçbir yerde çalışmıyor; None = bir host'un durumu bilinmiyor (kapalı/bayat)."""
    only = {name: None}
    if any(sw._project_key(s.name, only) == name for s in find_sessions(measure_cpu=False)):
        return True
    unknown = False
    for h in sorted({x for x in hosts if x}):
        st = _remote.status(h)
        rows = (st or {}).get("sessions") or []
        if any(isinstance(r, dict) and r.get("running") and sw._project_key(str(r.get("name") or ""), only) == name
               for r in rows):
            return True
        if not _host_fresh(st):
            unknown = True
    return None if unknown else False


def http_project_upsert(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    if data.get("actor") == "brain" and name not in sw.load_projects(sid):
        # Beyin yeni ad AÇAMAZ (mevcut kaydı günceller): ad bir kez kayda girince `_target` onu "kayıtlı proje" sayar ve
        # kullanıcının ad hoc oturumu iki çağrıyla hedeflenebilirdi. Yeni proje yalnız `steward_register_project` ya da insan.
        sw.log_event("project_denied", paths=sid, actor="brain", name=name)
        return {"ok": False, "error": "brain cannot create a new project with steward_set_project; "
                                      "use steward_register_project (or ask the owner)"}
    fields = {k: data.get(k) for k in ("phase", "kind", "goal", "priority", "cadence_minutes", "notes", "model", "effort",
                                        "host") if k in data}
    old = sw.load_projects(sid).get(name)
    old_host = old.host if old is not None else ""
    if "host" in fields:
        if data.get("actor") == "brain":
            # Projenin hangi makinede yaşadığı sahibin kararı: beyin host'u değiştiremez (yanlış host = yanlış adaş oturum).
            sw.log_event("project_denied", paths=sid, actor="brain", name=name, field="host")
            return {"ok": False, "error": "brain cannot change a project's host (ask the owner)"}
        fields["host"] = sw.normalize_host(fields["host"])
    new_host = fields.get("host", old_host)
    if fields.get("phase") in sw.ACTIVE_PHASES:
        # Roster'da olmayan projeyi AKTİF faza alma/kaydetme (idea→planned dahil): her tick başarısız `start` üretirdi (CLI zaten uyarıyordu).
        # `idea/paused/done` serbest; önce `steward_register_project`/panel kaydı. Uzak projede roster = o host'un satırları.
        if new_host:
            if not _in_remote_roster(name, new_host):
                return {"ok": False, "error": f"'{name}' is not in the roster of host {new_host!r} (or the host is not "
                                              "reachable right now); register it there first or use phase idea/paused"}
        elif not _in_roster(name):
            return {"ok": False, "error": f"'{name}' is not in the roster; register it first "
                                          "(panel / steward_register_project) or use phase idea/paused"}
    running = None
    if old is not None and "host" in fields and new_host != old_host:
        busy = _project_running_anywhere(name, (old_host, new_host))
        running = lambda: busy      # noqa: E731 — kilit altında ağ/süreç taraması yapılmasın: önceden hesaplandı
    try:
        p = sw.upsert_project(name, paths=sid, force=bool(data.get("force")), running=running, **fields)
    except ValueError as e:      # OwnedElsewhere / ReservedName / HostChangeRefused mesajı olduğu gibi
        return {"ok": False, "error": str(e)}
    sw.log_event("project_set", paths=sid, name=name, fields=sorted(fields))
    out = {"ok": True, "project": _project_dict(p)}
    warning = _prefix_warning(name, sid)
    if warning:
        out["warning"] = warning
    return out


def _prefix_warning(name: str, sid: str = "default", index: Optional[Dict[str, Any]] = None) -> str:
    """Ad başka kimliğin bir proje adının öneki/uzantısıysa (`ncs` / `ncs2`) uyarı metni, değilse "". Kabul edilir
    (oturum adları tüm kimliklerde en uzun önekle GLOBAL çözülür, K4) ama kullanıcı karışıklığı bilsin."""
    idx = index if index is not None else _ownership_index()
    hits = sorted(f"{p} ({s})" for p, s in (idx.get("owners") or {}).items()
                  if s != sid and p != name and (p.startswith(name) or name.startswith(p)))
    if not hits:
        return ""
    return ("name shares a prefix with project(s) of other stewards: " + ", ".join(hits)
            + "; sessions resolve to the longest matching project name across all stewards")


def http_project_remove(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    return {"ok": sw.remove_project(name, sid)}


def http_register(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Yeni proje: klasör (yoksa oluştur + git init), GOAL.md (amaç + kaynaklar), yerel kaynak dosyalarını
    `kaynaklar/`a kopyala, roster'a kaydet (`web._register_project`), değnekçi kaydını aç."""
    cfg = steward_config(sid)
    name = str(data.get("name") or "").strip()
    cwd = os.path.expanduser(str(data.get("cwd") or "").strip())
    goal = str(data.get("goal") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    known = sw.load_projects(cfg.sid).get(name)
    if sw.normalize_host(data.get("host")) or (known is not None and known.host) or _name_host(name):
        # Uzak proje burada AÇILMAZ (klasör/GOAL.md/roster bu makineye yazılırdı): uzak host'ta kayıtlı roster satırı
        # `steward set NAME --host H` ile benimsenir.
        return {"ok": False, "error": "remote project: register it on its host, then adopt it with "
                                      "`py/cops steward set NAME --host HOST`"}
    if not cwd or not os.path.isabs(cwd):
        return {"ok": False, "error": "cwd must be an absolute path"}
    # Talep ÖNCE denetlenir (klasör/GOAL.md/roster yan etkilerinden önce): başka kimliğin adı ya da rezerve ad reddedilir.
    paths = sw.paths_for(cfg.sid)
    other = sw.project_owner(name, exclude=cfg.sid)
    if other:
        return {"ok": False, "error": str(sw.OwnedElsewhere(name, other))}
    idx = _ownership_index(fresh=True)
    if name not in sw.load_projects(paths):
        why = sw.reserved_reason(name, idx)
        if why:
            return {"ok": False, "error": str(sw.ReservedName(name, why))}
    warning = _prefix_warning(name, cfg.sid, idx)
    try:
        os.makedirs(cwd, exist_ok=True)
    except OSError as e:
        return {"ok": False, "error": f"cannot create {cwd}: {e}"}
    if not os.path.isdir(os.path.join(cwd, ".git")):
        try:
            subprocess.run(["git", "init", "-q"], cwd=cwd, capture_output=True, text=True, timeout=10)
        except Exception:
            pass
    resources = data.get("resources") or []
    if isinstance(resources, str):
        resources = [x.strip() for x in resources.replace("\n", ",").split(",") if x.strip()]
    copied, listed = [], []
    for r in resources[:50]:
        r = str(r).strip()
        if not r:
            continue
        src = os.path.expanduser(r)
        if os.path.isfile(src):
            try:
                if os.path.getsize(src) <= MAX_RESOURCE_BYTES:
                    dst_dir = os.path.join(cwd, "kaynaklar")
                    os.makedirs(dst_dir, exist_ok=True)
                    shutil.copy2(src, os.path.join(dst_dir, os.path.basename(src)))
                    copied.append(os.path.basename(src))
                    continue
            except OSError:
                pass
        listed.append(r)
    goal_path = os.path.join(cwd, "GOAL.md")
    if goal or copied or listed:
        lines = [f"# {name} — amaç" if cfg.lang != "en" else f"# {name} — goal", "", goal or "", ""]
        if copied or listed:
            lines.append("## Kaynaklar" if cfg.lang != "en" else "## Resources")
            lines += [f"- kaynaklar/{c}" for c in copied] + [f"- {l}" for l in listed]
        try:
            mode = "a" if os.path.exists(goal_path) else "w"
            with open(goal_path, mode, encoding="utf-8") as f:
                f.write(("\n" if mode == "a" else "") + "\n".join(lines).rstrip() + "\n")
        except OSError as e:
            return {"ok": False, "error": f"cannot write GOAL.md: {e}"}
    cli = str(data.get("cli") or "").strip()
    model = str(data.get("model") or "").strip()
    fleet = _act("fleet_status") or {}
    reg: Dict[str, Any] = {"ok": True, "skipped": True}
    if name not in fleet:
        reg = _act("register_project", name, cwd, model=model, cli=cli, lang=cfg.lang)
        if not reg.get("ok"):
            return reg
    phase = data.get("phase") if data.get("phase") in sw.PHASES else "planning"
    try:
        p = sw.upsert_project(name, paths=paths, phase=phase, kind=data.get("kind") or "", goal=goal,
                              priority=data.get("priority"), cadence_minutes=data.get("cadence_minutes"))
    except ValueError as e:     # yarış: denetimden sonra başka kimlik talep etti (OwnedElsewhere) ya da rezerve
        return {"ok": False, "error": str(e), "cwd": cwd, "copied": copied, "roster": reg}
    idea_id = str(data.get("idea_id") or "")
    if idea_id:
        sw.update_idea(idea_id, status="project", project=name, paths=paths)
    sw.log_event("project_register", paths=paths, name=name, cwd=cwd, copied=copied, listed=len(listed))
    out = {"ok": True, "project": _project_dict(p), "cwd": cwd, "copied": copied, "roster": reg}
    if warning:
        out["warning"] = warning
    return out


def http_ask(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Soru aç (+ `options`: en çok 6 kısa seçenek) → ntfy: metin + numaralı seçenekler + `/q/<id>?k=` bağlantısı
    (tünel varsa; bildirime dokunmak sayfayı açar). Aynı açık soru ikinci kez bildirilmez (`add_question` dedup)."""
    cfg = steward_config(sid)
    try:
        q = sw.add_question(str(data.get("project") or ""), str(data.get("text") or ""),
                            source=str(data.get("source") or "api"), options=data.get("options"), paths=sid)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    link = sw.question_link(q, public_base(), cfg.sid)
    if q.notified_at:
        return {"ok": True, "id": q.id, "notified": False, "link": link, "dup": True}
    notified = _notify(cfg, sw.question_notification(q, link, cfg.lang, cfg.sid, host=_name_host(q.project) if q.project else ""), click=link)
    if notified:
        sw.mark_notified(q.id, sid)
    sw.log_event("ask", paths=sid, id=q.id, project=q.project, notified=notified, options=len(q.options))
    return {"ok": True, "id": q.id, "notified": notified, "link": link}


def _known_sids() -> List[str]:
    """Ayardaki + diskte dizini olan kimlikler (default önce)."""
    return list(dict.fromkeys(["default"] + list(steward_ids()) + sw.discover_steward_ids()))


def _find_question_any(qid: str, key: str, sid: str = "") -> Tuple[str, Optional["sw.Question"]]:
    """(kimlik, soru). `sid` verildiyse önce YALNIZ o kimliğin deposu; yoksa (eski bağlantılar) tüm kimlikler, default önce.
    Aynı id birden fazla depoda varsa (çok nadir) anahtarı eşleşen kazanır. `sid` deposunda bulunamazsa ve `key` verildiyse
    (soru devirle başka kimliğe taşınmış olabilir: ntfy bağlantısındaki `s=` eski sahibi gösterir) tüm depolarda ANAHTAR
    eşleşmesiyle aranır (anahtar depolar arası benzersiz, `_unique_question_key`); anahtarsız geri düşüş YOK."""
    cands = [sid] if sid else _known_sids()
    hits = [(s, q) for s in cands if (q := sw.find_question(qid, s)) is not None]
    for s, q in hits:
        if key and q.key and secrets.compare_digest(key.encode("utf-8", "replace"), q.key.encode("utf-8")):
            return s, q
    if hits:
        return hits[0]
    if sid and key:
        for s in _known_sids():
            if s == sid:
                continue
            q = sw.find_question(qid, s)
            if q is not None and q.key and secrets.compare_digest(key.encode("utf-8", "replace"), q.key.encode("utf-8")):
                return s, q
    return "", None


def http_question_page(qid: str, key: str, token_ok: bool, form: Optional[Dict[str, Any]] = None,
                       sid: str = "") -> Tuple[int, str]:
    """`/q/<id>` (GET: sayfa, POST: `form["answer"]`). Yetki: panel token'ı YA DA sorunun kendi anahtarı (`k`,
    sabit zamanlı karşılaştırma; anahtarsız eski kayıt yalnız token'la). `sid` (`?s=`): soru o kimliğin deposunda
    aranır; yoksa tüm kimliklerde. Dönen: (HTTP durumu, HTML)."""
    sid = (sid or "").strip()
    if sid and (not sw.valid_steward_id(sid) or sid not in _known_sids()):
        return 404, sw.question_page_html(None, steward_config().lang, "missing")
    found_sid, q = _find_question_any(qid, key, sid) if qid else ("", None)
    cfg = steward_config(found_sid or "default")
    lang = cfg.lang
    if q is None:
        return 404, sw.question_page_html(None, lang, "missing")
    key_ok = bool(key and q.key) and secrets.compare_digest(key.encode("utf-8", "replace"), q.key.encode("utf-8"))
    if not token_ok and not key_ok:
        return 401, sw.question_page_html(None, lang, "denied")
    suffix = "" if found_sid == "default" else f"s={found_sid}"
    action = f"/q/{q.id}?k={q.key}" if q.key else f"/q/{q.id}"   # token'la gelen tarayıcı formu da anahtarla POST eder
    if suffix:
        action += ("&" if "?" in action else "?") + suffix
    if q.status != "open":
        return 200, sw.question_page_html(q, lang, "already", action=action)
    if form is None:
        return 200, sw.question_page_html(q, lang, "ask", action=action)
    try:
        answered = sw.answer_question(q.id, str(form.get("answer") or ""), found_sid)
    except ValueError:
        return 400, sw.question_page_html(q, lang, "ask", error=sw._QPAGE_TXT["en" if lang == "en" else "tr"]["empty"],
                                          action=action)
    sw.log_event("answer", paths=found_sid, id=q.id, project=q.project, source="phone")
    invalidate_summary()
    web_ws.notify_status_changed()
    return 200, sw.question_page_html(answered, lang, "done", action=action)


def http_answer(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    try:
        q = sw.answer_question(str(data.get("id") or ""), str(data.get("answer") or ""), sid)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if q is None:
        return {"ok": False, "error": "unknown question id"}
    sw.log_event("answer", paths=sid, id=q.id, project=q.project)
    return {"ok": True, "question": dataclasses.asdict(q)}


def http_idea(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    if data.get("id"):
        i = sw.update_idea(str(data["id"]), status=data.get("status"), project=data.get("project"), paths=sid)
        if i is None:
            return {"ok": False, "error": "unknown idea id"}
        sw.log_event("idea_update", paths=sid, id=i.id, status=i.status, project=i.project)
        return {"ok": True, "idea": dataclasses.asdict(i)}
    try:
        i = sw.add_idea(str(data.get("text") or ""), source=str(data.get("source") or "api"), paths=sid)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    sw.log_event("idea", paths=sid, id=i.id)
    return {"ok": True, "idea": dataclasses.asdict(i)}


def http_note(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("project") or data.get("name") or "").strip()
    text = str(data.get("text") or "").strip()
    if not sw.valid_name(name) or not text:
        return {"ok": False, "error": "project and text are required"}
    p = sw.load_projects(sid).get(name)
    if p is None:
        return {"ok": False, "error": "not a steward project"}
    sw.upsert_project(name, paths=sid, notes=text)
    sw.log_event("note", paths=sid, name=name, chars=len(text))
    return {"ok": True}


def http_directive(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    text = str(data.get("text") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    gated = _gate(name, data, "directive", sid)
    if gated is not None:
        return gated
    with _ctx(sid).lock:
        projects = sw.load_projects(sid)
        p = _project_for_session(name, projects, _world(sid))
        if p is None:
            if _running(name) is None and not inst_mod.get_instance(name) and name not in (_act("fleet_status") or {}):
                return {"ok": False, "error": "unknown session/project"}
            p = sw.Project(name=name)   # ad hoc: kayıt açmadan sadece gönder
        return _give_directive(p, text, model=str(data.get("model") or ""), effort=str(data.get("effort") or ""),
                               start_if_stopped=bool(data.get("start_if_stopped", True)),
                               reason=str(data.get("reason") or "brain"), session_name=name, cfg=steward_config(sid))


def http_restart(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    cfg = steward_config(sid)
    gated = _gate(name, data, "restart", sid)
    if gated is not None:
        return gated
    host = _name_host(name)      # `_gate` istekteki host'u projeninkiyle zaten eşledi
    with _ctx(sid).lock:      # yeniden girişli: içerideki http_directive aynı kilidi yeniden alır
        if host:
            # Uzak restart = durdurma (`_remote_stop` koşulları + kapanma beklemesi) + yönerge (kapalıysa uzak başlatma).
            # Durdurma doğrulanmadıysa yönerge GÖNDERİLMEZ: kapanmakta olan oturuma yazılır ya da ikinci oturum açılırdı.
            stopped = _remote_stop_and_wait(name, host, _world(sid), sid, str(data.get("actor") or ""))
            if stopped is not None:
                sw.log_event("restart", paths=sid, name=name, host=host, ok=False, step="stop",
                             error=str(stopped.get("error") or ""), reason=str(data.get("reason") or ""))
                return stopped
            sw.log_event("restart", paths=sid, name=name, host=host, reason=str(data.get("reason") or ""))
            return http_directive(dict(data, start_if_stopped=True, reason="restart: " + str(data.get("reason") or "")), sid)
        if _running(name) is not None:
            res = _act("stop", name, lang=cfg.lang)
            if not res.get("ok"):
                return res
        sw.log_event("restart", paths=sid, name=name, reason=str(data.get("reason") or ""))
        return http_directive(dict(data, start_if_stopped=True, reason="restart: " + str(data.get("reason") or "")), sid)


def http_stop(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    cfg = steward_config(sid)
    gated = _gate(name, data, "stop", sid)
    if gated is not None:
        return gated
    host = _name_host(name)      # `_gate` istekteki host'u projeninkiyle zaten eşledi
    with _ctx(sid).lock:
        if host:     # uzak: yalnız `_remote_stop`un koşullarıyla (exact_target, tam ad, "own"); yerel `_act` ASLA
            res = _remote_stop(name, host, _world(sid), sid, str(data.get("actor") or ""))
        else:
            res = _act("stop", name, lang=cfg.lang)
    sw.log_event("stop", paths=sid, name=name, reason=str(data.get("reason") or ""), ok=bool(res.get("ok")),
                 **({"host": host} if host else {}))
    return res


def http_handover(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    cfg = steward_config(sid)
    gated = _gate(name, data, "handover", sid)
    if gated is not None:
        return gated
    host = _name_host(name)      # `_gate` istekteki host'u projeninkiyle zaten eşledi
    with _ctx(sid).lock:
        res = _remote_handover(name, host) if host else _act("handover", name, lang=cfg.lang)
        if res.get("ok"):
            with sw.steward_lock(sid):
                state = sw.load_state(sid)
                state.setdefault("ho_pending", {})[name] = time.time()
                sw.save_state(state, sid)
    sw.log_event("handover", paths=sid, name=name, ok=bool(res.get("ok")), **({"host": host} if host else {}))
    return res


def http_skip(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    sw.log_event("skip", paths=sid, name=name, reason=str(data.get("reason") or ""))
    with sw.steward_lock(sid):
        state = sw.load_state(sid)
        state.setdefault("last_directive_at", {})[name] = time.time()   # bir sonraki `idle` maddesini erteler
        sw.save_state(state, sid)
    return {"ok": True}


def http_brain(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    action = str(data.get("action") or "start")
    cfg = steward_config(sid)
    with _ctx(sid).lock:
        return brain_start(cfg) if action == "start" else brain_stop(cfg)


def http_cards(sid: str = "default") -> Dict[str, Any]:
    projects = sw.load_projects(sid)
    cards = sw.load_cards()
    return {"ok": True, "cards": [dict(c, name=n) for n, c in sorted(cards.items())],
            "missing": sorted(n for n, p in projects.items() if p.phase in sw.ACTIVE_PHASES and n not in cards),
            "busy": _CARD_LOCK.locked()}


def http_card(name: str, sid: str = "default") -> Dict[str, Any]:
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    if sid != "default" and name not in sw.load_projects(sid):
        return dict(_NOT_OWN_PROJECT)
    card = sw.load_card(name)
    return {"ok": True, "name": name, "card": card} if card is not None else {"ok": False, "error": "no card"}


def http_cards_refresh(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Kartları şimdi yenile (arka planda; model çağrısı panelin 15 sn'lik API zaman aşımını aşabilir, sonuç
    `py/cops steward cards` / `log`ta). `name` verilirse O proje (çalışıyor olsa da, kaynak değişmemiş olsa da);
    verilmezse yenilemesi GEREKEN tüm çalışmayan aktif projeler (tick başına sınırı yok)."""
    cfg = steward_config(sid)
    name = str(data.get("name") or "").strip()
    if name:
        if not sw.valid_name(name):
            return {"ok": False, "error": "invalid name"}
        if name not in sw.load_projects(sid):
            return {"ok": False, "error": "not a steward project"}
        job = lambda: refresh_card(name, cfg, reason="manual")   # noqa: E731
    else:
        job = lambda: refresh_due_cards(cfg, limit=10 ** 6)   # noqa: E731
    if not _run_cards_job(job):
        return {"ok": False, "error": "a card refresh is already running"}
    return {"ok": True, "queued": name or "due"}


# ── dış iş kuyruğu (varaka): gönderim ve liste ────────────────────────────────

_KIND_RE = re.compile(r"[a-z][a-z0-9_]{0,47}")
MAX_SPEC_CHARS = 200_000
JOBS_LIST_MAX = 100


def _owns_project(project: str, sid: str) -> bool:
    """Proje bu kimliğin KAYITLI ve çakışmasız projesi mi (sahiplik dosyalardan, `World`)."""
    return project in sw.load_projects(sid) and _world(sid).owns(project)


def http_job_submit(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Beynin (ya da insanın) KENDİ projesi adına varaka'ya iş eklemesi. Kapılar: proje sahipliği, servis kaydı, yerel
    dosya yolları PROJE DİZİNİ içinde. Onay gerektiren iş `awaiting_approval` döner; değnekçi ASLA approve/reject çağırmaz.
    Idempotency anahtarı otomatik (kimlik+proje+özellik özeti). observe + `actor: brain` → `would:job_submit`, servise
    dokunulmaz."""
    project = str(data.get("project") or "").strip()
    kind = str(data.get("kind") or "").strip()
    if not sw.valid_name(project):
        return {"ok": False, "error": "invalid project"}
    if not _KIND_RE.fullmatch(kind):
        return {"ok": False, "error": "invalid kind"}
    if not _owns_project(project, sid):
        sw.log_event("target_denied", paths=sid, actor=str(data.get("actor") or "human"), kind="job_submit", name=project)
        return {"ok": False, "error": "not a project of this steward"}
    params = data.get("params") if data.get("params") is not None else {}
    spec_text = data.get("spec_text") if data.get("spec_text") is not None else ""
    files = data.get("files") if data.get("files") is not None else []
    if not isinstance(params, dict) or not isinstance(spec_text, str) or not isinstance(files, list):
        return {"ok": False, "error": "params must be an object, spec_text a string, files a list"}
    if len(spec_text) > MAX_SPEC_CHARS:
        return {"ok": False, "error": f"spec_text too long (max {MAX_SPEC_CHARS})"}
    service = str(data.get("service") or "").strip() or sj.default_service()
    if not service or service not in sj.load_services():
        return {"ok": False, "error": "no such registered service (a human registers one: py/cops steward service add)"}
    try:
        resolved = sj.resolve_local_files(_project_cwd(project), files) if files else []
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    dry = _brain_dry("job_submit", dict(data, text=f"{service}: {kind} for {project} ({len(resolved)} files)"), project, sid)
    if dry is not None:
        return dry
    priority = data.get("priority")
    res = sj.submit_job(sid, project, kind, params, spec_text, resolved, service=service,
                        priority=int(priority) if isinstance(priority, int) and not isinstance(priority, bool) else None,
                        approval_ref=str(data.get("approval_ref") or ""),
                        host=_name_host(project) or LOCAL_HOST_NAME)     # uzak projede işin host'u proje host'u
    if res.get("ok") and res.get("state") == "awaiting_approval":
        res["awaiting_approval"] = True
        res["message"] = ("job is awaiting approval by a HUMAN admin in varaka: do not approve/reject it yourself; "
                          "the owner has been notified and the project session will be told")
        try:
            _notify_approvals(steward_config(sid))
        except Exception as e:
            diag_log("steward_job_notify_failed", sid=sid, error=repr(e))
    return res


def http_jobs(sid: str = "default", state: str = "open", project: str = "", job_id: str = "", refresh: bool = False,
              kinds: bool = False) -> Dict[str, Any]:
    """Bu kimliğin iş kayıtları (yerel `jobs.json`). `refresh`: önce açık işleri hemen yokla; `kinds`: varaka'nın iş türü
    kataloğu (`GET /api/jobs/kinds`, salt okuma). Başka kimliğin işi görünmez (dosya kimliğe özel)."""
    if kinds:
        name = sj.default_service()
        svc = sj.load_services().get(name)
        if svc is None:
            return {"ok": False, "error": "no registered service"}
        try:
            status, body = sj.request_json(svc, "GET", "/api/jobs/kinds")
        except sj.ServiceError as e:
            return {"ok": False, "error": f"{name}: {e}"}
        return {"ok": status == 200, "service": name, "status": status, "kinds": body}
    if refresh:
        sj.poll_jobs(sid, force=True)
        try:
            _notify_approvals(steward_config(sid))
        except Exception as e:
            diag_log("steward_job_notify_failed", sid=sid, error=repr(e))
    jobs = sj.load_jobs(sid)
    if job_id:
        jobs = [j for j in jobs if str(j.get("id")) == str(job_id)]
    if project:
        jobs = [j for j in jobs if j.get("project") == project]
    if state == "open":
        jobs = [j for j in jobs if sj.is_open(j)]
    elif state not in ("", "all"):
        jobs = [j for j in jobs if j.get("state") == state]
    jobs = sorted(jobs, key=lambda j: -float(j.get("created_at") or 0))[:JOBS_LIST_MAX]
    return {"ok": True, "jobs": [sj.job_view(j) for j in jobs], "services": sorted(sj.load_services())}


class UnknownSteward(ValueError):
    """İstekte verilen `steward` kimliği geçersiz ya da ayarda tanımlı değil."""


def _ctx_for(src: Any) -> StewardContext:
    """HTTP isteğinin değnekçi bağlamı. `src`: JSON gövdesi (dict) ya da sorgu (`{anahtar: [değer]}`). `steward` yoksa/boşsa
    `default` (eski MCP/UI/CLI aynen çalışır). Geçersiz biçim ya da ayarda tanımlı olmayan kimlik `UnknownSteward`
    (sessizce `default`a DÜŞMEZ: başka değnekçinin deposuna yazılmasın)."""
    raw = src.get("steward") if isinstance(src, dict) else None
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if raw is None or raw == "":
        return _ctx("default")
    if not isinstance(raw, str):
        raise UnknownSteward("unknown steward")
    sid = raw.strip()
    if sid != "default" and (not sw.valid_steward_id(sid) or sid not in steward_ids()):
        raise UnknownSteward("unknown steward")
    return _ctx(sid)


def _unknown_steward() -> Dict[str, Any]:
    return {"ok": False, "error": "unknown steward"}


_GET_PATHS = frozenset(("state", "projects", "questions", "ideas", "log", "context", "summary", "cards", "card", "file", "list",
                        "jobs"))


def http_get(path: str, qs: Dict[str, List[str]]) -> Optional[Dict[str, Any]]:
    """`web.py` do_GET: `/api/steward/*` → dict (bilinmeyen alt yol → None = 404). `?steward=<sid>` kimliği seçer
    (yoksa `default`); bilinmeyen kimlik `{"ok": false, "error": "unknown steward"}`."""
    g = lambda k, d="": (qs.get(k) or [d])[0]
    if not path.startswith("/api/steward/") or path[len("/api/steward/"):] not in _GET_PATHS:
        return None
    if path == "/api/steward/list":
        return http_list()
    try:
        sid = _ctx_for(qs).sid
    except UnknownSteward:
        return _unknown_steward()
    if path == "/api/steward/state":
        return http_state(sid)
    if path == "/api/steward/projects":
        return http_projects(sid)
    if path == "/api/steward/questions":
        return http_questions(g("status", "open"), sid)
    if path == "/api/steward/ideas":
        return http_ideas(g("status", "new"), sid)
    if path == "/api/steward/log":
        try:
            return http_log(int(g("n", "50")), sid)
        except ValueError:
            return http_log(sid=sid)
    if path == "/api/steward/context":
        return http_context(g("name").strip(), docs=g("docs") in ("1", "true"), sid=sid)
    if path == "/api/steward/summary":
        return http_summary(g("date").strip(), g("lang").strip(), sid)
    if path == "/api/steward/jobs":
        return http_jobs(sid, g("state", "open"), g("project").strip(), g("id").strip(), g("refresh") in ("1", "true"),
                         g("kinds") in ("1", "true"))
    if path == "/api/steward/cards":
        return http_cards(sid)
    if path == "/api/steward/card":
        return http_card(g("name").strip(), sid)
    if path == "/api/steward/file":
        try:
            mx = int(g("max", str(MAX_FILE_READ_CHARS)))
        except ValueError:
            mx = MAX_FILE_READ_CHARS
        return http_file(g("name").strip(), g("path").strip(), max(1, min(mx, MAX_FILE_READ_CHARS)), sid)
    return None


POST_PATHS = {
    "/api/steward/project": http_project_upsert,
    "/api/steward/project/remove": http_project_remove,
    "/api/steward/register": http_register,
    "/api/steward/ask": http_ask,
    "/api/steward/answer": http_answer,
    "/api/steward/idea": http_idea,
    "/api/steward/idea/export": http_idea_export,
    "/api/steward/note": http_note,
    "/api/steward/directive": http_directive,
    "/api/steward/restart": http_restart,
    "/api/steward/stop": http_stop,
    "/api/steward/handover": http_handover,
    "/api/steward/skip": http_skip,
    "/api/steward/cards/refresh": http_cards_refresh,
    "/api/steward/job/submit": http_job_submit,
    "/api/steward/brain": http_brain,
    "/api/steward/shutdown": http_shutdown,
    "/api/steward/tick": lambda data, sid="default": tick_once("manual", sid),
    "/api/steward/tour": lambda data, sid="default": run_tour(force=True, cfg=steward_config(sid)),
}


def http_post(path: str, data: Dict[str, Any], qs: Optional[Dict[str, List[str]]] = None) -> Optional[Dict[str, Any]]:
    """`steward` kimliği JSON gövdesinden, yoksa sorgudan (`qs`, `web.py` verir); ikisi de yoksa `default`."""
    fn = POST_PATHS.get(path)
    if fn is None:
        return None
    data = data if isinstance(data, dict) else {}
    try:
        try:
            sid = _ctx_for(data if data.get("steward") not in (None, "") else (qs or {})).sid
        except UnknownSteward:
            return _unknown_steward()
        return fn(data, sid=sid)
    finally:
        invalidate_summary()
