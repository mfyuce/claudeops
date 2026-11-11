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
import contextlib
import dataclasses
import hashlib
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

from .. import settings as settings_mod
from .. import hosts as hosts_mod
from .. import instances as inst_mod
from .. import review as rv
from .. import steward as sw
from .. import steward_jobs as sj
from .. import steward_lessons as sl
from .. import steward_keepwarm as skw
from .. import steward_advance as sa
from .. import steward_quota as sq
from ..diaglog import diag_log
from ..discovery import find_sessions
from ..guard import guard_lock
from ..hosts import LOCAL_HOST_NAME
from ..paths import CLAUDEOPS_DIR
from ..providers import PROVIDERS, DEFAULT_CLI, get_provider
from ..providers.base import McpServerSpec, OneshotError
from ..settings import default_effort_for, default_model_for, load_settings, steward_config, steward_ids
from ..spawn import spawn_session, detect_display
from ..tmux_backend import is_tmux_backed, strip_ansi, tmux_capture, tmux_has_session, tmux_send_keys, tmux_send_raw
from ..turns import is_busy_now
from . import web_review, web_ws

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

# Kimlik başına motor durumu (-prv: docs/multi-steward-plan.md K3): kilit, son eylemler, son tick, özet önbelleği.
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
    idle_why: Dict[str, Any] = dataclasses.field(default_factory=dict)     # {"at", "by": {proje: {code,text,detail}}}: son tick'in "neden ilerlemiyor" açıklaması

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
    return sw.world_for(sid, index if index is not None else _ownership_index(), cfg.brain_name, starts_left,
                        owned=_owned_of(sid))


def _owned_of(sid: str) -> Dict[str, str]:
    """L2: kimliğin izlediği oturumlar (`state.owned`: proje → tam oturum adı). Okunamazsa boş (eski davranış)."""
    try:
        return dict(sw.load_state(sid).get("owned") or {})
    except Exception as e:
        diag_log("steward_owned_read_failed", sid=sid, error=repr(e))
        return {}


OWNED_SEED_REQUEST = "owned_seed.request"   # kimlik dizininde varsa sıradaki tick log KANITIYLA tohumlar (L2 canlı geçişi, tek sefer)
OWNED_SEED_LOG_LINES = 20000     # L2 geçiş tohumlamasında taranan son log satırı (kanıt: değnekçinin start/directive olayları)


def _maintain_owned(views: List[sw.SessionView], projects: Dict[str, sw.Project], world: sw.World, paths: Any,
                    sid: str, now: float) -> sw.World:
    """Kaydı olmayan projelere sahiplik kaydı (`sw.update_owned`: ilk görüşte tek oturum benimsenir). Kimlik dizininde
    `OWNED_SEED_REQUEST` varsa (ve daha önce tohumlanmadıysa) bu tur yerine log KANITIYLA tohumlar (sahip 10 Kas). Güncel kayıtla `world` döner. Hata olursa `world` olduğu gibi (eski davranış)."""
    try:
        with sw.steward_lock(paths):
            st = sw.load_state(paths)
            req = os.path.join(os.path.dirname(sw._pp(paths).log), OWNED_SEED_REQUEST)
            seeding = not st.get("owned_seeded") and os.path.exists(req)
            events = sw.tail_log(OWNED_SEED_LOG_LINES, paths) if seeding else []
            new, changes = sw.update_owned(dict(st.get("owned") or {}), views, world, projects, now, seeding=seeding,
                                           evidence=lambda n, p, t: sw.owned_evidence(events, n, p, t))
            if changes or seeding:
                st["owned"] = new
                if seeding:
                    st["owned_seeded"] = True
                sw.save_state(st, paths)
        if seeding:
            with contextlib.suppress(OSError):
                os.unlink(req)
        for c in changes:
            sw.log_event("owned", paths=paths, **c)
        return dataclasses.replace(world, owned=new)
    except Exception as e:
        diag_log("steward_owned_maintain_failed", sid=sid, error=repr(e))
        return world


def _record_owned(sid: str, project: str, name: str, how: str, host: str = "") -> None:
    """L2: değnekçinin izlediği oturumu yaz (start / ilk benimseme / uzak yeniden açılışın yeni adı). Değişmediyse yazmaz."""
    if not project or not name:
        return
    try:
        with sw.steward_lock(sid):
            state = sw.load_state(sid)
            owned = dict(state.get("owned") or {})
            if owned.get(project) == name:
                return
            prev = owned.get(project)
            owned[project] = name
            state["owned"] = owned
            sw.save_state(state, sid)
        sw.log_event("owned", paths=sid, project=project, name=name, how=how, prev=prev or "",
                     **({"host": host} if host else {}))
    except Exception as e:
        diag_log("steward_owned_write_failed", sid=sid, project=project, error=repr(e))


def _owned_project(name: str, sid: str) -> str:
    """Ad (proje ya da oturum adı) → bu kimliğin proje adı, sahiplik kaydına BAKMADAN (manual oturumlar dahil)."""
    try:
        w = dataclasses.replace(_world(sid), owned={})
        p = _project_for_session(name, sw.load_projects(sid), w)
        return p.name if p is not None else ""
    except Exception:
        return ""


def _manual_sessions(name: str, sid: str) -> List[str]:
    """L2: `name`in projesinin sahibin elle açtığı (izlenmeyen) çalışan yerel oturumları."""
    key = _owned_project(name, sid)
    if not key:
        return []
    world = _world(sid)
    if key not in world.owned:
        return []
    out = []
    for x in _scan():
        bp = (inst_mod.get_instance(x.name) or {}).get("blueprint")
        if world.owned_key(x.name, bp) == key and world.session_class(x.name, bp) == "manual":
            out.append(x.name)
    return out


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
MAX_REMOTE_CARDS_PER_TICK = 1            # tick başına (kart işi çağrısı başına) en çok bu kadar uzak proje kartı denetlenir/yenilenir (A6)
REMOTE_CARD_BUDGET_SECONDS = 10.0        # bir kart işi çağrısında uzak belge okumalarının TOPLAM süresi (A6)
REMOTE_DESTRUCTIVE_KINDS = ("stop", "respawn", "restart")   # uzakta YALNIZ exact_target + tam ad ön denetimiyle (A4)
MAX_DESTRUCTIVE_PER_HOST = 1             # tick başına bir host'a en çok bu kadar yıkıcı eylem (fazlası ertelenir)
REMOTE_STOP_TIMEOUT_SECONDS = 60.0       # `/api/stop` (uzak tarafta guard_lock + kill_session_and_parent)
REMOTE_INPUT_TIMEOUT_SECONDS = 60.0      # `/api/term/input` (yönerge/cevap/iş sonucu)
REMOTE_HANDOVER_TIMEOUT_SECONDS = 60.0   # `/api/handover` (canlı devir mesajı; kill/respawn yok)
REMOTE_START_TIMEOUT_SECONDS = 120.0     # `/api/start` (uzak spawn)
REMOTE_READY_UNKNOWN_POLLS = 3            # busy bilinmeyen çalışan satır bu kadar art arda yoklamada hazır sayılır
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

    def probe(self, host: str) -> Optional[bool]:
        """Hafif tek `/api/status` yoklaması (poller ile aynı kayıt yolu; host başına hız sınırlı). None = atlandı."""
        return _wh().probe_host(host)

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


def _clear_backoff(host: str) -> bool:
    """Hafif yoklama host'u taze buldu: devre kesici sayacı ve geri çekilme ANINDA sıfırlanır (2026-10-29: probe başarılıydı
    ama 600 sn geri çekilme sürdü, insan direktifi `host_down` ile reddedildi). Host bildirilmiş `down` durumundaysa True."""
    with _HEALTH_LOCK:
        hh = _HOST_HEALTH.get(host)
        if hh is None:
            return False
        was_down = bool(hh.get("down"))
        hh["streak"], hh["until"], hh["down"] = 0, 0.0, False
    return was_down


@dataclasses.dataclass
class _RemoteTick:
    """Bir tick'in uzak host durumu. `statuses`/`fresh`: tick başında BİR KEZ alınan tazelik anlık görüntüsü
    (`unavailable`, görünümler ve eylem ön denetimleri AYNI görüntüyü kullanır; A1'deki iki ayrı okuma arasındaki yarış
    kapanır). `failed`/`succeeded`: bu tick'te eylem gönderilen host'lar (devre kesici + geri çekilme sayacı).
    `destructive`: {host: bu tick'te gönderilen yıkıcı eylem sayısı} (`MAX_DESTRUCTIVE_PER_HOST`, A4).
    `started`: bu tick'te `/api/start` gönderilen (host, proje) çiftleri: önbellek yeni satırı henüz göstermese de
    aynı tick'te o projeye ikinci başlatma GİTMEZ."""
    now: float
    statuses: Dict[str, Optional[Dict[str, Any]]] = dataclasses.field(default_factory=dict)
    fresh: frozenset = frozenset()
    failed: set = dataclasses.field(default_factory=set)
    succeeded: set = dataclasses.field(default_factory=set)
    destructive: Dict[str, int] = dataclasses.field(default_factory=dict)
    started: set = dataclasses.field(default_factory=set)

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


_RECOVERED_DOWN: set = set()    # probe ile geri çekilmeden çıkan host'lar (olay yazılınca çağıran boşaltır)
REMOTE_PROBES_PER_TICK = 2     # tick başına en çok bu kadar bayat host yoklanır (her yoklama en kötü ~8 sn)


def _probe_stale_hosts(rt: "_RemoteTick") -> List[str]:
    """Tick anlık görüntüsünde taze OLMAYAN host'ları (kapalı/bayat; geri çekilmedekiler dahil) BİR hafif `/api/status` ile
    yoklar: poller ya da push akışı sessiz kalsa bile host dönünce hemen taze olur (2026-10-29: ulak_31 ulaşılabilirken
    18+ dk "kapalı" kaldı). Yoklama poller ile aynı kayıt yolundan geçer; host başına hız sınırı `probe_host`ta. Toparlanan
    host'ların görüntüsü `rt.refresh` ile yenilenir (başarısızlıkta ek önbellek okuması YOK). Toparlananlar döner. Fırlatmaz."""
    recovered: List[str] = []
    tried = 0
    for h in sorted(set(rt.statuses) - set(rt.fresh)):
        if tried >= REMOTE_PROBES_PER_TICK:
            break
        try:
            ok = _remote.probe(h)
        except Exception:
            ok = None
        if ok is None:
            continue
        tried += 1
        if ok:
            recovered.append(h)
            if _clear_backoff(h):
                _RECOVERED_DOWN.add(h)       # çağıran `remote_unreachable state=up` olayını yazar
            rt.refresh(h)
    return recovered


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


def _box_has_typed_input(session_name: str) -> bool:
    """Oturumun giriş kutusunda KULLANICININ/motorun yazdığı ama GÖNDERİLMEMİŞ metin var mı (gri öneri sayılmaz). Pane
    okunamaz ya da kutu bulunamazsa False (eski davranış: dürtme gider). Fırlatmaz."""
    try:
        from .. import tmux_backend as tmb
        snap = tmb.tmux_pane_snapshot(session_name)
        return bool(snap and tmb.typed_input_in_box(snap[1]) is True)
    except Exception:
        return False


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
    if transport:       # geri çekilmeye giden taşıma hatalarının NEDENİ kayıtta olsun (2026-10-29: 3 ardışık düşüşün nedeni bilinmiyordu)
        diag_log("remote_transport_error", host=host, path=path, status=status,
                 error=str((parsed or {}).get("error") if isinstance(parsed, dict) else parsed)[:200])
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


def _remote_last_assistant(targets: List[Tuple[str, str]], budget: float = REMOTE_READ_BUDGET_SECONDS,
                           failed: Optional[set] = None) -> Dict[Tuple[str, str], str]:
    """{(host, ad): son asistan metni}: `GET /api/term/chat?mode=last`, paralel, TOPLAM `budget` sn. Süresi dolan ya da
    hata veren okuma sonuçta YOK (= "" bilinmiyor); süresi dolan iş parçacığı arka planda biter, sonucu atılır. `failed`
    verilirse taşıma hatası/zaman aşımı alan host'lar ona eklenir (devre kesici okuma yavaşlığını da saysın)."""
    out: Dict[Tuple[str, str], str] = {}
    if not targets:
        return out
    lock = threading.Lock()
    deadline = time.monotonic() + budget

    def work(host: str, name: str) -> None:
        try:
            parsed, _status = _remote.get("/api/term/chat", host, {"name": name, "mode": "last"}, timeout=budget)
        except Exception:
            if failed is not None:
                failed.add(host)
            return
        if failed is not None and _is_transport_error(host, parsed, _status):
            failed.add(host)
        if isinstance(parsed, dict) and parsed.get("ok") and parsed.get("supported"):
            with lock:
                out[(host, name)] = str(parsed.get("assistant") or "")

    threads = [threading.Thread(target=work, args=t, daemon=True, name="steward-remote-read") for t in targets]
    for t in threads:
        t.start()
    for t, (h, _n) in zip(threads, targets):
        t.join(max(0.0, deadline - time.monotonic()))
        if t.is_alive() and failed is not None:
            failed.add(h)      # süre doldu, host cevap vermedi
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
        context_tokens=tokens, host=host, subagent_unknown=True,
        live_model=str(r.get("live_model") or ""), live_effort=str(r.get("live_effort") or ""))
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


def _probe_facts(host: str, names: List[str], budget: float, now: Optional[float] = None,
                 failed: Optional[set] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
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
        if failed is not None:
            failed.add(host)
        return cached or {"api": 0, "capabilities": []}, {}
    if failed is not None and _is_transport_error(host, parsed, status):
        failed.add(host)
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
    for v in views:
        # Instance kaydı (blueprint) taşımayan uzak satır: tarih sonekli ad (`oiso20261017`) projesine çözülür, yoksa
        # `SessionView.project` adın kendisi olur ve proje "çalışmıyor" sayılıp ikinci bir başlatma planlanırdı.
        if not v.blueprint:
            key = _remote_key(v.name, v.host, world)
            if key and key != v.name and _derived_of(v.name, key):
                v.blueprint = key
    history = {(r["host"], str(r.get("name") or "")): r.get("history_size") for r in selected}
    deadline = time.monotonic() + REMOTE_READ_BUDGET_SECONDS
    running: Dict[str, List[sw.SessionView]] = {}
    for v in views:
        if v.running:
            running.setdefault(v.host, []).append(v)
    got: Dict[str, Dict[str, Any]] = {}
    lock = threading.Lock()
    read_failed: set = set()      # facts/term-chat okumasında taşıma hatası ya da zaman aşımı alan host'lar (set.add iş parçacığı güvenli)

    def probe(host: str) -> None:
        try:
            caps, facts = _probe_facts(host, [v.name for v in running[host]], max(0.5, deadline - time.monotonic()), now,
                                       failed=read_failed)
        except Exception:
            return
        if "session_facts" in caps["capabilities"]:
            with lock:
                got[host] = facts

    threads = [threading.Thread(target=probe, args=(h,), daemon=True, name="steward-remote-facts") for h in running]
    for t in threads:
        t.start()
    for t, h in zip(threads, list(running)):
        t.join(max(0.0, deadline - time.monotonic()))
        if t.is_alive():
            read_failed.add(h)
    with lock:
        enriched = {h: dict(f) for h, f in got.items()}
    fallback: List[Tuple[str, str]] = []
    for v in views:
        if not v.running:
            continue
        f = (enriched.get(v.host) or {}).get(v.name)
        if isinstance(f, dict) and f.get("running") is not False:
            _apply_facts(v, f, now, history.get((v.host, v.name)))
            if not v.last_assistant:
                # facts yanıtladı ama `last_assistant` BOŞ (ulak_31 iggy, 2026-10-29): boş metin işaret taramasını (STEWARD-DONE-CONFIRMED
                # vb.) sessizce kapatıyordu; olgular (alt ajan, bağlam, yaş) kalır, yalnız METİN term/chat'ten tamamlanır
                fallback.append((v.host, v.name))
        else:
            fallback.append((v.host, v.name))
    left = deadline - time.monotonic()
    texts = _remote_last_assistant(fallback, budget=left, failed=read_failed) if fallback and left > 0 else {}
    if rt is not None and read_failed:
        rt.failed |= read_failed       # yavaş/yanıtsız okuma da devre kesiciyi besler (eskiden yalnız eylem POST'u sayılırdı)
    for v in views:
        if (v.host, v.name) in texts and texts[(v.host, v.name)]:
            v.last_assistant = texts[(v.host, v.name)]
    return views


def configure(**callbacks: Callable[..., Any]) -> None:
    """`web.py` `run()`'da verir: status_payload(), fleet_status(), start(name, model, effort, fresh, lang),
    stop(name, lang), handover(name, lang), register_project(name, cwd, model, cli, lang)."""
    _ACTIONS.update(callbacks)


_SESSION_CHANGING_ACTS = ("start", "stop", "handover", "register_project")


def _act(name: str, *args: Any, **kw: Any) -> Any:
    fn = _ACTIONS.get(name)
    if fn is None:
        return {"ok": False, "error": f"steward engine not configured ({name})"}
    try:
        return fn(*args, **kw)
    finally:
        if name in _SESSION_CHANGING_ACTS:
            _scan_invalidate()      # oturum kümesi değişmiş olabilir: tick içi tarama önbelleği düşer


_FAIL_LOGGED: Dict[Tuple[str, str, str, str], float] = {}
_FAIL_LOGGED_LOCK = threading.Lock()
FAIL_LOG_REPEAT_SECONDS = 30 * 60   # aynı başarısız eylem + aynı neden bu aralıkta tek kez kaydedilir


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
    fkey = (str(ctx.paths.root), action.kind, action.name, entry["detail"])
    with _FAIL_LOGGED_LOCK:       # elle tick/`shutdown_tick` farklı thread'den gelebilir: iterasyon sırasında ekleme RuntimeError verirdi
        if entry["ok"]:
            for k in [k for k in _FAIL_LOGGED if k[:3] == fkey[:3]]:
                _FAIL_LOGGED.pop(k, None)
        elif entry["ts"] - _FAIL_LOGGED.get(fkey, 0.0) < FAIL_LOG_REPEAT_SECONDS:
            return      # aynı eylem aynı nedenle yine düştü (ör. ambiguous_sessions): tick başına log/kayıt gürültüsü yok
        else:
            for k in [k for k, t in _FAIL_LOGGED.items() if entry["ts"] - t >= FAIL_LOG_REPEAT_SECONDS]:
                _FAIL_LOGGED.pop(k, None)     # süresi dolan anahtarlar (detail metni dahil) budanır: sınırsız büyüme yok
            _FAIL_LOGGED[fkey] = entry["ts"]
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
    if action.kind == "deliver_findings":
        detail = f"findings x{len(action.payload.get('rows') or [])} -> {action.payload.get('project')}"
    if action.kind == "deliver_lesson":
        detail = f"lesson x{len(action.payload.get('hashes') or [])} -> {action.payload.get('project')}"
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
                       event: str = "target_denied", **extra: Any) -> None:
    """Uzak red olayı, (kimlik, aktör, ad, sebep) başına `REMOTE_DENIED_DEDUP_SECONDS`te bir. `event`: olay adı
    (`remote_too_old` kendi adıyla düşer: eski host'un yükseltilmesi gerektiğini log'da aramak kolay olsun). `extra`
    olaya eklenir (ör. `sessions`), tekrarsızlık anahtarına girmez."""
    key, now = (sid, actor or "human", name, code), time.time()
    with _DENIED_LOCK:
        if now - _DENIED_LOGGED.get(key, 0.0) < REMOTE_DENIED_DEDUP_SECONDS:
            return
        _DENIED_LOGGED[key] = now
    sw.log_event(event, paths=sid, actor=actor or "human", kind=kind, name=name, host=host, code=code, **extra)


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
    elif (not _host_fresh(_remote.status(host)) if (actor or "human") == "human" else
          not (host in rt.fresh if rt is not None else
               (_host_fresh(_remote.status(host)) and not _backing_off(host, time.time())))):
        # İnsan (CLI/panel) çağrısı geri çekilmeye TAKILMAZ: devre kesici otomatik eylemleri (motor/beyin) korur; host taze
        # ise insanın isteği geçer (2026-10-29: probe 200 dönerken anomaly direktifi reddedildi).
        code, err = "host_down", f"target denied: host {host!r} is unreachable or stale right now"
    else:
        return None
    _log_remote_denied(sid, actor, kind, name, host, code)
    return {"ok": False, "error": err, "code": code, "host": host}


def _target(name: str, actor: str, projects: Optional[Dict[str, sw.Project]] = None,
            kind: str = "", sid: str = "default", world: Optional[sw.World] = None,
            host: Any = None, rt: Optional[_RemoteTick] = None) -> Optional[Dict[str, Any]]:
    """Oturuma dokunan yolların TEK kapısı (-prv: docs/multi-steward-plan.md K5). `None` = izinli, aksi halde red yanıtı.
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
    if sid != "default" and steward_config(sid).role == "reviewer":
        # reviewer kimliği HİÇBİR oturuma dokunamaz (insan dahil): review çalıştırmaları kendi süreçleri, tmux oturumu değil
        sw.log_event("target_denied", paths=sid, actor=actor or "human", kind=kind, name=name, code="reviewer")
        return {"ok": False, "error": "target denied: reviewer stewards never act on sessions", "code": "reviewer"}
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
        if state != "ok":      # kapalıyken NEDEN ve son deneme zamanı (`steward status`)
            tried = _wh().last_try_at(h)
            err = str((st or {}).get("error") or "") if st else "poller kaydı yok"
            out[h]["reason"] = err[:120] or ("geri çekilmede" if state == "backoff" else "son başarılı poll bayat")
            out[h]["last_try"] = int(now - tried) if tried else None
    return out


def _remote_ref(host: str, name: str) -> Tuple[str, str]:
    """Uzak okuma hedefi: (oturumun GERÇEK adı, klasörü); host'un TAZE önbelleğinden, ağa gitmez; bulunamazsa ("", "").
    Sıra: adı TAM `name` olan satır (çalışan ya da kapalı); yoksa ad bu host'taki bir projeye çözülüyorsa (proje adı
    `oiso`, oturum `oiso20261017`) projenin TEK çalışan oturumu; çalışan yoksa projeye çözülen kapalı satırlar (hepsi
    aynı klasördeyse ilki). Projenin iki çalışan oturumu varsa ya da kapalı satırların klasörleri farklıysa tahmin
    edilmez: ("", "")."""
    st = _remote.status(host)
    if not _host_fresh(st) or _backing_off(host, time.time()):
        return "", ""
    rows = {k: [r for r in (st.get(k) or []) if isinstance(r, dict)] for k in ("sessions", "closed")}
    for key in ("sessions", "closed"):
        for r in rows[key]:
            if r.get("name") == name and r.get("cwd"):
                return name, str(r["cwd"])
    world = _world()
    key = _remote_key(name, host, world)
    if not key:
        return "", ""
    live = _remote_project_rows(rows["sessions"], host, key, world)
    if live:
        return (str(live[0].get("name") or ""), str(live[0].get("cwd") or "")) if len(live) == 1 else ("", "")
    closed = [r for r in rows["closed"] + [r for r in rows["sessions"] if not r.get("running")]
              if r.get("cwd") and world.resolve(str(r.get("name") or "")) == ("project", key)]
    if closed and len({str(r["cwd"]) for r in closed}) == 1:
        return str(closed[0].get("name") or ""), str(closed[0]["cwd"])
    return "", ""


def _remote_cwd(host: str, name: str) -> str:
    """Uzak oturumun klasörü (`_remote_ref`: tam ad, yoksa projenin tek oturumu); yoksa ""."""
    return _remote_ref(host, name)[1]


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
    real, cwd = _remote_ref(host, name)
    name = real or name         # okumalar oturumun GERÇEK adıyla (proje adı `oiso`, oturum `oiso20261017`)
    out: Dict[str, Any] = {"last_exchange": _remote_last_exchange(host, name, deadline - time.monotonic()),
                           "docs": {}, "remote_cwd": cwd}
    if want_docs and cwd:
        for d in docs:
            text, _cut, ok = _remote_file_head(host, name, cwd.rstrip("/") + "/" + d, head,
                                               deadline - time.monotonic())
            if ok and text:
                out["docs"][d] = text
    return out


def _remote_files_gate(host: str, sid: str = "default") -> bool:
    """Uzak proje dosyasına (kart okuması, fikir aktarımı) dokunma kapısı (A6): `steward.remote_actions` açık, host
    kayıtlı + TAZE ve geri çekilmede değil. Kapalı/bayat host'a hiç istek atılmaz."""
    if not host or hosts_mod.get_host(host) is None or not steward_config(sid).remote_actions:
        return False
    return _host_fresh(_remote.status(host)) and not _backing_off(host, time.time())


# Uzak kart denetim sırası: {proje: son denetim zamanı}. Her tick yalnız MAX_REMOTE_CARDS_PER_TICK proje okunur; en
# eski denetlenen önce gelir, böylece "kaynağı değişmemiş" bir proje kuyruğun başında diğerlerini aç bırakmaz.
_REMOTE_CARD_CHECKED: Dict[str, float] = {}


def _remote_raw_card(host: str, name: str, budget: float) -> Optional[Dict[str, Any]]:
    """Uzak projenin ham kartı: klasörü host'un taze önbelleğinden, `CARD_DOCS` başları host-routed `files/read`den
    (yerelle aynı liste ve uzunluk), git bilgisi YOK (`sw.raw_card_from_docs`). Yerel dosya sistemine ASLA bakılmaz.
    None = bilinmiyor (klasör yok, bütçe bitti ya da hiçbir belge okunamadı: yoksa yenileme yanlışlıkla "değişti"
    sayılırdı); belgesiz ama okunabilir klasör boş docs ile döner. Fırlatmaz."""
    real, cwd = _remote_ref(host, name)
    if not cwd:
        return None
    name = real or name
    deadline = time.monotonic() + budget
    docs: Dict[str, str] = {}
    reads = 0
    for d in sw.CARD_DOCS:
        left = deadline - time.monotonic()
        if left <= 0.2:
            return None
        text, _cut, ok = _remote_file_head(host, name, cwd.rstrip("/") + "/" + d, sw.CARD_DOC_CHARS,
                                           min(left, REMOTE_CARD_BUDGET_SECONDS))
        if ok:
            reads += 1
            if text.strip():
                docs[d] = text.strip()
    return sw.raw_card_from_docs(docs) if reads else None


# ── görünümler ────────────────────────────────────────────────────────────────

def context_tokens_for(cwd: str, sid: Optional[str]) -> Optional[int]:
    """Claude transkriptinin SON asistan turunun bağlam boyutu: girdi + cache okuma + cache yazma token'ı (her
    turda yeniden okunan bağlamın boyutu). Dosyanın yalnız sonundan okur (~256 KB); bulunamazsa None.
    sid bilinmiyorsa None (bilinmiyor): mtime tahmini ortak cwd'de BAŞKA konuşmanın transkriptini döndürüp taze oturumu
    sahte eşik aşımıyla devir döngüsüne sokmuştu (2026-10-22, ucli: 98K'lık oturuma 312K)."""
    from ..providers.claude_provider import jsonl_path_for
    if not sid:
        return None
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


def _ucli_idle_info(s: Any) -> Tuple[float, str]:
    """(idle_since, cache_ttl) ucli oturumu için. idle_since: durum dosyası `activity=waiting_for_stdin` ise `last_activity_unix`
    (yoksa 0 = boşta değil/bilinmiyor). cache_ttl: çalışan sürecin `--cache-ttl` argümanı; okunamazsa Ayarlar `ucli_cost.cache_ttl`."""
    from ..ucli_client import read_status_file
    idle = 0.0
    try:
        st = read_status_file(s.cwd, s.sid or s.name) or {}
        last = st.get("last_activity_unix")
        if st.get("activity") == "waiting_for_stdin" and isinstance(last, (int, float)) and not isinstance(last, bool):
            idle = float(last)
    except Exception:
        idle = 0.0
    ttl = ""
    try:
        argv = psutil.Process(s.pid).cmdline()
        for i, a in enumerate(argv):
            if a == "--cache-ttl" and i + 1 < len(argv):
                ttl = argv[i + 1]
            elif a.startswith("--cache-ttl="):
                ttl = a.split("=", 1)[1]
    except Exception:
        ttl = ""
    if ttl not in ("5m", "1h"):
        try:
            from ..settings import ucli_cost_config
            ttl = str(ucli_cost_config().get("cache_ttl") or "")
        except Exception:
            ttl = ""
    return idle, ttl


def _collect_views(cfg: sw.Config, rt: Optional[_RemoteTick] = None) -> List[sw.SessionView]:
    """Tick'in oturum görünümleri: yerel `/api/status` satırları (+ provider okumaları) ve uzak projelerin taze
    host'lardaki satırları (`_remote_views`, `rt`: tick'in tazelik anlık görüntüsü). Satır seçimi `sw.select_rows`: adı
    uzak projeye çözülen yerel satır düşer."""
    payload = _act("status_payload") or {}
    world = _world(cfg.sid, cfg)
    rows = sw.select_rows([r for r in (payload.get("sessions") or []) if not sw.normalize_host(r.get("host"))], world)
    live = {s.name: s for s in _scan()}
    views: List[sw.SessionView] = []
    for r in rows:
        name = r.get("name") or ""
        s = live.get(name)
        v = sw.SessionView(
            name=name, running=bool(r.get("running")), cwd=r.get("cwd") or "", cli=r.get("cli") or DEFAULT_CLI,
            blueprint=r.get("blueprint") if r.get("instance") else None,
            busy=r.get("busy"), history_size=r.get("history_size"), needs_ho=r.get("needs_ho"),
            tmux=bool(r.get("tmux")), model=str(r.get("model") or ""),
            live_model=str(r.get("live_model") or ""), live_effort=str(r.get("live_effort") or ""),
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
            elif s.cli == "ucli":     # durum dosyası context_bytes/4 (kaba); None = bilinmiyor -> satır yedeği
                try:
                    v.context_tokens = provider.live_context(s.cwd, s.sid)
                except Exception:
                    v.context_tokens = None
            if s.cli == "claude":
                try:
                    v.subagent_active = subagent_active_for(s.cwd, s.sid)
                except Exception:
                    v.subagent_active = False
            try:
                v.started_at = float(psutil.Process(s.pid).create_time())
            except Exception:
                v.started_at = 0.0
            if s.cli == "ucli":
                v.idle_since, v.cache_ttl = _ucli_idle_info(s)
        if not v.blueprint:
            # Instance kaydı (blueprint) taşımayan yerel tarihli oturum (`ncs20261029`): uzak yoldaki `_derived_of` düzeltmesinin
            # yerel karşılığı; yoksa `SessionView.project` adın kendisi olur, proje "çalışmıyor" sayılıp her cadence şablon
            # uyandırması + sahte `start` (bütçeyi yer) üretilirdi.
            key = world.project_key(name)
            if key and key != name and _derived_of(name, key):
                v.blueprint = key
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


ANSWER_FAIL_ALERT = 3      # art arda bu kadar başarısız cevap iletimi: olay + bildirim
_ANSWER_FAILS: Dict[str, int] = {}


def _send(name: str, cli: str, text: str) -> bool:
    provider = get_provider(cli)
    if not provider.has_conversation():
        return False
    if cli == "claude":
        # İlk açılışta güven diyaloğu açıksa metin + Enter varsayılan "No, exit"i seçip oturumu öldürür (7 Kas: animallangppr, vesuviusppr)
        from .. import trust_dialog
        if trust_dialog.is_trust_dialog(strip_ansi(tmux_capture(name) or "")):
            diag_log("send_blocked_trust_dialog", name=name)
            return False
    # ucli çok satırı ayrı tur sayar: tek satıra katlama + kesmeme TEK yerde, `UcliProvider.prepare_input`
    ok = tmux_send_keys(name, provider.prepare_input(text), settle_delay=provider.input_settle_delay())
    if ok and cli == "ucli":
        _ucli_box_recheck(name)
    return ok


UCLI_BOX_CHECK_DELAY = 0.8
UCLI_BOX_POLLS = 20         # en çok yoklama (~16 sn): geç çizilen uzun metni de yakala
UCLI_BOX_EMPTY_OK = 5       # art arda boş yoklama = gerçekten gönderildi
UCLI_BOX_MAX_ENTERS = 3
_UCLI_PROMPT = "ucli>"
# İstemden sonra bunlar varsa kutu boştur (tur sürüyor/bitmiş): metin kayması değil, çıktı.
_UCLI_TURN_RE = re.compile(r"waiting for response|^\s*(?:\[[^\]]*\]\s*$|[●⏺▸→•]|tool\b)", re.IGNORECASE)


def _ucli_box_text(name: str) -> str:
    """Son 10 satırda `ucli>` içeren SON satırı bul (başında `[model | turn N | ...]` öneki olabilir); metin = istemden
    sonrası + onu izleyen (pane genişliğinde kaymış) satırlar. İstemden sonra `waiting for response`/tur çıktısı varsa ''."""
    lines = strip_ansi(tmux_capture(name, lines=10) or "").splitlines()
    idx = -1
    for i, l in enumerate(lines):
        if _UCLI_PROMPT in l:
            idx = i
    if idx < 0:
        return ""
    parts = [lines[idx].rsplit(_UCLI_PROMPT, 1)[1].strip()]
    for l in lines[idx + 1:]:
        if not l.strip():
            continue
        if _UCLI_TURN_RE.search(l):
            return ""
        parts.append(l.strip())
    return " ".join(p for p in parts if p)


def _ucli_box_recheck(name: str) -> None:
    """Gönderimden sonra ucli giriş kutusunu İZLE: metin kaldıysa Enter (en çok `UCLI_BOX_MAX_ENTERS`), kutu art arda
    `UCLI_BOX_EMPTY_OK` yoklamada boşsa bitir; hâlâ doluysa `ucli_send_stuck` olayı. Tek yoklama yetmez (5 Kas 05:40: uzun metin
    ~20 sn sonra çizildi, boş kutu "gönderildi" sanıldı, Enter hiç gitmedi). Asla fırlatmaz."""
    try:
        enters = empties = 0
        left = ""
        for _ in range(UCLI_BOX_POLLS):
            time.sleep(UCLI_BOX_CHECK_DELAY)
            left = _ucli_box_text(name)
            if not left:
                empties += 1
                if empties >= UCLI_BOX_EMPTY_OK:
                    return
                continue
            empties = 0
            if enters >= UCLI_BOX_MAX_ENTERS:
                break
            tmux_send_raw(name, "\r")          # yalnız Enter
            enters += 1
        if left:
            sw.log_event("ucli_send_stuck", paths=sw.paths_for("default"), name=name, left=left[:120], enters=enters)
    except Exception:
        pass


_SCAN = threading.local()


@contextlib.contextmanager
def _scan_scope():
    """Bir tick boyunca `find_sessions` sonucunu önbellekle (~35 ms/tarama, 700+ süreç; tick başına ~15 tarama): oturum değiştiren her
    eylem (`_act` start/stop/handover/register, beyin spawn) `_scan_invalidate` ile önbelleği düşürür. Kapsam DIŞINDA (HTTP, CLI,
    testler) her çağrı taze tarar: eski davranış."""
    outer = getattr(_SCAN, "cache", None)
    if outer is None:
        _SCAN.cache = {"live": None}
    try:
        yield
    finally:
        if outer is None:
            _SCAN.cache = None


def _scan_invalidate() -> None:
    c = getattr(_SCAN, "cache", None)
    if c is not None:
        c["live"] = None


def _scan() -> List[Any]:
    c = getattr(_SCAN, "cache", None)
    if c is None:
        return find_sessions(measure_cpu=False)
    if c["live"] is None:
        c["live"] = list(find_sessions(measure_cpu=False))
    return list(c["live"])


def _running(name: str):
    for s in _scan():
        if s.name == name:
            return s
    return None


def _live_sessions(name: str, sid: str = "default") -> List[Any]:
    """`name` (oturum ya da PROJE adı) için çalışan yerel oturumlar: tam ad eşleşirse o; yoksa aynı projeye çözülenler
    (`cli` projesi → `cli20261021`). Ad eşitliği tarihli oturumda HİÇ tutmaz: direktif `cli`ye gidince "kapalı" sanılıp
    ikinci oturum açılmıştı (2026-10-22, ucli). Boş liste = çalışan yok."""
    s = _running(name)
    if s is not None:
        return [s]
    projects = sw.load_projects(sid)
    world = _world(sid)
    p = _project_for_session(name, projects, world)
    if p is None:
        # Kayıtsız (ad hoc) proje: `mecdtfl` direktifi `mecdtfl20261031_1`i bulamayıp ikinci oturum açıyordu (2026-10-31).
        # Kayıt yoksa da tarihli/_N'li çalışan oturum, adı BLUEPRINT ya da taban ad olarak taşıyorsa o projenin oturumudur.
        from ..session import Session
        return [x for x in _scan()
                if x.name != name and name in ((inst_mod.get_instance(x.name) or {}).get("blueprint"), Session(name=x.name, pid=0).base)]
    return [x for x in _scan()
            if (q := _project_for_session(x.name, projects, world)) is not None and q.name == p.name]


def _resolved_local_name(name: str, sid: str = "default") -> str:
    """Proje adı (`oiso`) -> tek canlı yerel oturumun GERÇEK adı (`oiso20261017`); 0 ya da 2+ canlı oturumda `name`
    olduğu gibi kalır (çözüm eylemin kendi denetimine bırakılır). `plan_tick` durumu (ho_pending, last_directive_at)
    görünüm adıyla okur: anahtar proje adı olursa tarihli oturumda hiç tutmaz."""
    live = _live_sessions(name, sid)
    return live[0].name if len(live) == 1 else name


# Kimliğin dokunamayacağı oturum sınıfları (`World.session_class`): başka kimliğin projesi, çakışmalı proje, servis, beyinler.
_FOREIGN = ("other", "conflict", "service", "brain_other", "brain_own", "manual")   # manual: L2, sahibin elle açtığı


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
        key = sw._project_key(name, projects)     # TEK KURAL `sw.derived_of` (eskiden Session.base + DERIVED_NAME_RE: `mtsyn20260909review` → mtsyn)
        p = projects.get(key) if key else None
    if p is None or world is None:
        return p
    cls = world.session_class(name, (rec or {}).get("blueprint"))
    if cls == "manual" and name == p.name:
        return p    # L2: PROJE ADININ kendisi (direktif/start hedefi) oturum değil, proje tanımlayıcısı: manual süzgeci yok
    return None if cls in _FOREIGN else p


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
    unique_base çözümüne güvenilmez (yanlış adaş oturum). Yalnız gerçek adı BİLİNEN oturumun kapanma beklemesi
    (`_remote_wait_closed`) bunu kullanır; proje → oturum çözümü `_remote_session`da."""
    rows = _remote_rows(host, rt)
    if rows is None:
        return False, None
    return True, next((r for r in rows if r.get("name") == name and r.get("running")), None)


def _remote_key(name: str, host: str, world: sw.World) -> str:
    """Ad (proje adı ya da tarih/_N sonekli oturum adı) `host`taki bir projeye çözülüyorsa proje adı, değilse ""."""
    kind, key = world.resolve(name)
    return key if kind == "project" and key and world.host_of(key) == host else ""


_derived_of = sw.derived_of     # TEK KURAL steward.py'de (L2 c)


def _remote_project_rows(rows: List[Dict[str, Any]], host: str, key: str, world: sw.World) -> List[Dict[str, Any]]:
    """`rows` içinden `key` projesinin ÇALIŞAN oturumları: adı `key`e çözülen (tam ad, `oiso20261017`, `oiso20261017_1`)
    ve `sw.select_rows`un bu host için seçtiği satırlar (uzak beyin/servis/kayıtsız düşer). Başka projenin öneki
    karışmaz (`World.resolve` en uzun proje adını seçer). Sıra satır sırası; dönen satırlar özgün sözlüklerdir."""
    running = [r for r in rows if r.get("running") and world.resolve(str(r.get("name") or "")) == ("project", key)
               and _derived_of(str(r.get("name") or ""), key)]
    keep = {str(r.get("name") or "") for r in sw.select_rows([dict(r, host=host) for r in running], world, {host})}
    return [r for r in running if str(r.get("name") or "") in keep]


def _remote_session(host: str, name: str, rt: Optional[_RemoteTick] = None, world: Optional[sw.World] = None,
                    *, sid: str = "default", actor: str = "", kind: str = ""
                    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Uzak "proje → çalışan oturum" çözümü: (host taze mi, hedef satır ya da None, red ya da None). Oturum adı proje
    adı + tarih soneki (+ `_N`) ve her yeni açılışta DEĞİŞİR; proje başına TEK canlı oturum olmalı. `name` proje adı
    (`oiso`) ya da tam oturum adı (`oiso20261017`) olabilir; çözüm `rt` verilirse tick görüntüsünden, yoksa önbellekten
    ŞİMDİ (ağa gitmez):
    - projenin çalışan oturumu yok → (True, None, None): çağıran (izin veriyorsa) PROJE adıyla başlatabilir;
    - tek oturum → o satır (gerçek tam adıyla); `name` tam oturum adıysa o satır OLMALI, değilse
      `other_session_running` reddi (kapanmış eski ada yazılmaz, yanına ikinci oturum da açılmaz);
    - iki ya da daha çok → `ambiguous_sessions` reddi (tekrarsız log): hiçbir eylem, ASLA başlatma.
    Ad bu host'taki bir projeye çözülmüyorsa (uzak beyin/servis/kayıtsız) eski kural: yalnız TAM adlı çalışan satır."""
    rows = _remote_rows(host, rt)
    if rows is None:
        return False, None, None
    # L2: kayıt tick içinde değişebilir (az önce başlatılan oturumun adı yazıldı): tick'in `world`ü bayat kalmasın
    world = dataclasses.replace(world, owned=_owned_of(sid)) if world is not None and world.owned else (world or _world(sid))
    key = _remote_key(name, host, world)
    if not key:
        return True, next((r for r in rows if r.get("name") == name and r.get("running")), None), None
    mine = _remote_project_rows(rows, host, key, world)
    manual = [str(r.get("name") or "") for r in mine
              if world.session_class(str(r.get("name") or ""), r.get("blueprint") if r.get("instance") else None) == "manual"]
    mine = [r for r in mine if str(r.get("name") or "") not in manual]
    if manual and not mine:     # L2: sahibin elle açtığı uzak oturum; değnekçi dokunmaz, yanına da açmaz
        _log_remote_denied(sid, actor, kind, name, host, "manual_session_running", event="manual_hold",
                           project=key, sessions=manual)
        return True, None, {"ok": False, "code": "manual_session_running", "host": host, "sessions": manual,
                            "error": f"project {key!r} runs in the owner's own session on {host} ({', '.join(manual)})",
                            "project": key}
    names = [str(r.get("name") or "") for r in mine]
    if len(mine) >= 2:
        _log_remote_denied(sid, actor, kind, name, host, "ambiguous_sessions", event="remote_ambiguous",
                           project=key, sessions=names)
        return True, None, {"ok": False, "code": "ambiguous_sessions", "host": host, "sessions": names,
                            "error": (f"target denied: project {key!r} has {len(mine)} running sessions on {host} "
                                      f"({', '.join(names)}); refusing to guess"), "project": key}
    if not mine:
        return True, None, None
    row = mine[0]
    if name not in (key, names[0]):
        return True, None, {"ok": False, "code": "other_session_running", "host": host, "sessions": names,
                            "error": (f"{name!r} is not running on {host}; project {key!r} runs as {names[0]!r}"),
                            "project": key}
    return True, row, None


_remote_sleep = time.sleep      # testler no-op yapar (hazır bekleme yoklaması)


def _remote_wait_ready(host: str, name: str, timeout: float = READY_TIMEOUT_SECONDS) -> bool:
    """Uzak başlatmadan sonra hazır bekleme. AĞ ÇAĞRISI YAPMAZ: poller önbelleğine `REMOTE_READY_POLL_SECONDS`te bir
    bakar; satır çalışıyor ve `busy is False` (bilinmiyor = hazır değil) olunca True, en çok `timeout`. Yerel
    `_wait_ready` gibi garanti değil: claude meşgulken gelen girdiyi kuyruğa alır, en kötü durumda yönerge gecikir.
    `name` proje adıdır: uzak taraf yeni oturuma tarihli ad verir, satır `_remote_session` ile projeden çözülür.
    Sahiplik kaydı (L2) burada YOK sayılır: yeni oturumun adı henüz kayıtta değil (çağıran yazar)."""
    world = dataclasses.replace(_world(), owned={})
    unknown = 0
    for i in range(max(1, int(timeout / REMOTE_READY_POLL_SECONDS))):
        if i:
            _remote_sleep(REMOTE_READY_POLL_SECONDS)
        _fresh, r, _err = _remote_session(host, name, world=world)
        if r is not None and r.get("busy") is False:
            return True
        # `busy` hiç bildirilmeyen CLI'da (None) her uzak başlatma tam `timeout` bekleyip kilidi tutardı: satır art arda
        # REMOTE_READY_UNKNOWN_POLLS yoklamada çalışıyor ve busy bilinmiyorsa hazır say (girdi kuyruğa alınır, kaybolmaz)
        unknown = unknown + 1 if (r is not None and r.get("running") is not False and r.get("busy") is None) else 0
        if unknown >= REMOTE_READY_UNKNOWN_POLLS:
            return True
    return False


def _ensure_running_remote(name: str, host: str, model: str, effort: str, fresh: bool,
                           rt: Optional[_RemoteTick] = None, *, sid: str = "default", actor: str = "",
                           kind: str = "start") -> Dict[str, Any]:
    """Uzak `_ensure_running`: projenin (`_remote_session`) tek çalışan oturumu varsa dokunmaz (yanıtta gerçek `name`);
    iki ya da daha çoksa ya da `name` kapanmış eski bir oturum adıyken başka oturum çalışıyorsa red (başlatma YOK);
    hiç yoksa PROJE adıyla `POST /api/start` (gövdede host YOK, `REMOTE_START_TIMEOUT_SECONDS`), önbellekten hazır
    bekleme ve tick görüntüsünün yenilenmesi (`rt.refresh`; aynı tick'te o projeye ikinci başlatma `rt.started` ile de
    kesilir). Host taze değilse başlatma DENENMEZ."""
    world = _world(sid)
    fresh_host, r, err = _remote_session(host, name, rt, world, sid=sid, actor=actor, kind=kind)
    if not fresh_host:
        return {"ok": False, "error": "host_down", "code": "host_down", "host": host}
    if err is not None:
        return err
    if r is not None:
        key = _remote_key(name, host, world)
        if key and key not in world.owned:
            _record_owned(sid, key, str(r.get("name") or ""), "adopt", host)     # L2: ilk açılışta benimseme
        return {"ok": True, "started": False, "cli": r.get("cli") or DEFAULT_CLI, "host": host, "name": r.get("name")}
    start_name = _remote_key(name, host, world) or name
    if rt is not None and (host, start_name) in rt.started:
        return {"ok": False, "error": f"start already sent for {start_name!r} on {host} this tick",
                "code": "start_pending", "host": host}
    warn = remote_resume_warning(start_name, host, bool(fresh), steward_config(sid))
    if warn:
        sw.log_event("remote_start_resume_unknown_context", paths=sw.paths_for(sid), name=start_name, host=host)
    res = _remote_post(host, "/api/start", {"name": start_name, "model": model, "effort": effort, "fresh": bool(fresh)},
                       REMOTE_START_TIMEOUT_SECONDS, rt)
    if not res.get("ok"):
        return res
    if warn:
        res = dict(res, warning=warn)
    if rt is not None:
        rt.started.add((host, start_name))
    ready = _remote_wait_ready(host, start_name)
    if rt is not None:
        rt.refresh(host)        # aynı tick'in sonraki adımları yeni satırı görsün (A4 deseni)
    _f, r, _err = _remote_session(host, start_name, world=dataclasses.replace(world, owned={}))
    out = {"ok": True, "started": True, "ready": ready, "cli": (r or {}).get("cli") or DEFAULT_CLI, "host": host,
           "name": (r or {}).get("name") or start_name}
    _record_owned(sid, start_name, str(out["name"]), "start", host)     # L2: uzak taraf yeni oturuma tarihli ad verir
    if warn:
        out["warning"] = warn
    return out


def remote_resume_warning(name: str, host: str, fresh: bool, cfg: sw.Config) -> str:
    """TBD#123 (uzak): host API'si konuşmanın bağlam boyutunu vermiyor, bu yüzden büyük bağlamlı `--resume` ÖNLENEMEZ.
    Yapılabilen kısım: `fresh` verilmediyse ve eşik açıksa uyarı metni (çağıran `fresh=True` ile taze açabilir).
    Host'ta token sayımı için API gerekir (TODO'da kalır)."""
    if fresh or int(cfg.resume_max_context_tokens or 0) <= 0:
        return ""
    return (f"{name}@{host}: uzak başlatma durmuş konuşmayı --resume edebilir; bağlam boyutu host'ta bilinmiyor "
            f"(eşik {int(cfg.resume_max_context_tokens)} token uygulanamadı). Büyükse fresh=True ile taze açın.")


def _oversized_resume(name: str, cfg: sw.Config) -> int:
    """TBD#123: `--resume` edilecek konuşma (spawn'ın seçeceği jsonl) son turda `cfg.resume_max_context_tokens`ten büyük bağlam
    taşıyorsa o token sayısı, değilse 0. Yalnız claude ailesi (jsonl bilinir); bilinmiyorsa 0 (davranış değişmez)."""
    limit = int(cfg.resume_max_context_tokens or 0)
    if limit <= 0:
        return 0
    try:
        cwd = _cwd_resolver()(name)
        cli = _project_cli(name)
        if not cwd or cli != "claude":
            return 0
        rid = get_provider(cli).resolve_resume_id(cwd, session_name=name)
        tokens = context_tokens_for(cwd, rid) if rid else None
    except Exception:
        return 0
    return int(tokens) if tokens and tokens > limit else 0


def _closed_in_models(name: str) -> bool:
    """`cops close` ile models.tsv'de `# CLOSED` bırakılmış mı (hata olursa False: start akışı bozulmaz)."""
    try:
        from .close import is_closed_in_models
        return bool(is_closed_in_models(name))
    except Exception:
        return False


def _last_launch(name: str) -> Optional[Dict[str, Any]]:
    """`instances.json`daki SON başlatma kaydı (TBD#156): `name`in kendi kaydı, yoksa blueprint'i `name` olan en son
    başlatılan/oluşturulan unutulmamış kayıt. Yoksa None (çağıran roster/varsayılana düşer). Fırlatmaz."""
    try:
        recs = inst_mod.load_instances()
    except Exception:
        return None
    rec = recs.get(name)
    if not isinstance(rec, dict) or rec.get("forgotten"):
        cands = [r for r in recs.values()
                 if isinstance(r, dict) and r.get("blueprint") == name and not r.get("forgotten")]
        rec = max(cands, key=lambda r: float(r.get("last_started_at") or r.get("created_at") or 0), default=None)
    return rec if isinstance(rec, dict) and rec.get("cli") in PROVIDERS else None


def _launch_kwargs(name: str, model: str, effort: str) -> Dict[str, Any]:
    """Devir/yeniden açma/başlatmada oturumu BAŞLADIĞI cli + `cli_opts` ile açmak için `start` ek argümanları (TBD#156).
    Kayıt yoksa ya da kayıtlı cli claude ve roster/fleet cli'si de claude ise {} (eski davranış birebir). Kayıtlı cli
    claude DEĞİLSE (ucli kodcu) model/effort da kayıttan gelir: değnekçinin Claude model/effort'u o cli'de geçersiz olur."""
    rec = _last_launch(name)
    if rec is None or rec.get("cli") not in ("ucli", DEFAULT_CLI):
        # ucli kodcular (TBD#156'nın amacı) ve claude. agy/codex/copilot kaydı roster'ı geçemez: projenin yardımcı agy
        # oturumu (`vc20260929_1`) ana claude oturumundan birkaç sn sonra başlatılmış olabilir ve "en son kayıt"
        # olur; 5 Kas 01:1x'te vc böyle agy (krediSİZ) açıldı.
        return {}
    cli = str(rec["cli"])
    opts = rec.get("cli_opts") if isinstance(rec.get("cli_opts"), dict) else None
    if cli == DEFAULT_CLI and not opts and cli == _project_cli(name):
        return {}
    out: Dict[str, Any] = {"cli": cli}
    if opts:
        out["cli_opts"] = dict(opts)
    if rec.get("permission_mode"):      # örn. ucli `allow-edit`: yoksa respawn salt okunur açılırdı (5 Kas copsdev); `_start(permission_mode=)` kayda önceliklidir
        out["permission_mode"] = str(rec["permission_mode"])
    if cli != DEFAULT_CLI:
        if rec.get("model"):
            out["model"] = str(rec["model"])
        if rec.get("effort"):
            out["effort"] = str(rec["effort"])
    return out


def _model_endpoint_mismatch(name: str) -> Optional[Dict[str, Any]]:
    """Tarihten BAĞIMSIZ yapılandırma denetimi: kayıt ucli + `claude-*` modeli ama hizmet claude/anthropic DEĞİL (boş `cli_opts` =
    varsayılan Evren) ise oturum her turda 404 `model_not_found` döngüsüne girer (danisppr, 6 Kas: 157 tur). Açılış
    REDDEDİLİR (`model_endpoint_mismatch`). Kayıt yok / claude CLI / başka model -> None. Fırlatmaz."""
    try:
        rec = _last_launch(name)
        if not rec or rec.get("cli") != "ucli" or not str(rec.get("model") or "").lower().startswith("claude"):
            return None
        opts = rec.get("cli_opts") if isinstance(rec.get("cli_opts"), dict) else {}
        blob = " ".join(str(opts.get(k) or "") for k in ("service", "endpoint", "base_url", "url")).lower()
        if "claude" in blob or "anthropic" in blob:
            return None
        return {"ok": False, "code": "model_endpoint_mismatch",
                "error": f"{name}: kayıt ucli + {rec.get('model')} ama hizmet/uç nokta Anthropic değil (Evren claude modelini "
                         "tanımaz, 404 döngüsü). Kaydı claude CLI'ye çevir ya da cli_opts.service=claude ver; açılmadı."}
    except Exception:
        return None


def _api_blocked(name: str, today: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """API yasağı kapısı (sahip, 2026-11-05): `settings.anthropic_api_block_until` (YYYY-MM-DD) henüz gelmediyse ve `name`in
    başlatma kaydı ucli + Anthropic hizmeti (`cli_opts.service` claude/anthropic ya da uç nokta anthropic) ise açılış
    REDDEDİLİR. Kayıt yok / claude CLI / tarih boş ya da geçmiş -> None. Fırlatmaz."""
    try:
        until = str(settings_mod.load_settings().get("anthropic_api_block_until") or "").strip()
        if not until or (today or time.strftime("%Y-%m-%d")) >= until:
            return None
        rec = _last_launch(name)
        if not rec or rec.get("cli") != "ucli":
            return None
        opts = rec.get("cli_opts") if isinstance(rec.get("cli_opts"), dict) else {}
        blob = " ".join(str(opts.get(k) or "") for k in ("service", "endpoint", "base_url", "url")).lower()
        if "claude" in blob or "anthropic" in blob:
            return {"ok": False, "code": "anthropic_api_blocked",
                    "error": f"{name}: Anthropic API yasağı {until} tarihine kadar; kayıt ucli+Anthropic, açılmadı "
                             "(instances.json kaydını claude CLI'ye çevir ya da yasağı kaldır)"}
    except Exception:
        return None
    return None


_START_FAILS: Dict[str, Tuple[int, float]] = {}          # oturum/proje adı -> (art arda başarısız sayısı, son başarısızlık zamanı)
_START_BACKOFF_STEPS = (600.0, 3600.0, 21600.0)          # 10 dk / 1 sa / 6 sa


def _start_backoff_remaining(name: str, now: Optional[float] = None) -> float:
    """Son başarısız başlatmadan sonra beklenecek kalan saniye (0 = denenebilir). Bellek içi: servis restart'ında sıfırlanır."""
    n, at = _START_FAILS.get(name, (0, 0.0))
    if n <= 0:
        return 0.0
    step = _START_BACKOFF_STEPS[min(n, len(_START_BACKOFF_STEPS)) - 1]
    return max(0.0, at + step - (time.time() if now is None else now))


def _start_backoff_note(name: str, ok: bool, now: Optional[float] = None) -> None:
    if ok:
        _START_FAILS.pop(name, None)
        return
    n, _at = _START_FAILS.get(name, (0, 0.0))
    _START_FAILS[name] = (n + 1, time.time() if now is None else now)


def _ensure_running(name: str, model: str = "", effort: str = "", lang: str = "tr", fresh: bool = False,
                    host: str = "", rt: Optional[_RemoteTick] = None, sid: str = "default",
                    actor: str = "", exact: bool = False) -> Dict[str, Any]:
    if host:     # `sid`/`actor` yalnız uzak yolun red log'u için; yerel yol değişmedi
        return _ensure_running_remote(name, host, model, effort, fresh, rt, sid=sid, actor=actor)
    # exact: çağıran TAM oturum adını verir (respawn: az önce durdurulan oturumun adı); proje çözümü yapılmaz.
    live = [_running(name)] if exact and _running(name) is not None else ([] if exact else _live_sessions(name, sid))
    if live:
        if not exact and len(live) == 1:
            proj = _owned_project(name, sid)
            if proj and proj not in _owned_of(sid):
                _record_owned(sid, proj, live[0].name, "adopt")       # L2: ilk açılışta çalışan tek oturum benimsenir
        return {"ok": True, "started": False, "cli": live[0].cli}
    manual = [] if exact else _manual_sessions(name, sid)
    if manual:      # L2: sahip projede elle açtığı oturumla çalışıyor; yanına oturum AÇILMAZ, ona da dokunulmaz
        sw.log_event("manual_hold", paths=sw.paths_for(sid), name=name, sessions=manual)
        return {"ok": False, "code": "manual_session_running", "sessions": manual,
                "error": f"{name!r}: the owner's own session is running ({', '.join(manual)}); steward does not touch it"}
    blocked = _model_endpoint_mismatch(name) or _api_blocked(name)
    if blocked is not None:
        sw.log_event("api_blocked", paths=sw.paths_for(sid), name=name)
        return blocked
    wait = _start_backoff_remaining(name)
    if wait > 0:        # D2: başarısız başlatmadan sonra üstel geri çekilme (vc: 26 başarısız start); her tick yeniden denemez
        return {"ok": False, "error": f"start backoff: retry in {int(wait)}s", "code": "start_backoff", "retry_in": int(wait)}
    closed = _closed_in_models(name)
    if closed:   # `cops close` bıraktı: guard/cron bu oturumu yeniden AÇMAZ; elle başlatma sessiz geçmesin
        sw.log_event("start_closed_project", paths=sw.paths_for(sid), name=name)
    ho_jsonl = "" if fresh else _resume_lacks_ho(name, steward_config(sid))
    big = 0
    if ho_jsonl:     # sahip kuralı: eski konuşma devirsiz kapanmış -> önce o konuşmayla aç, devir al, motor taze yeniden açar
        sw.log_event("ho_on_open", paths=sw.paths_for(sid), name=name, step="resume", jsonl=os.path.basename(ho_jsonl))
    elif not fresh:
        big = _oversized_resume(name, steward_config(sid))
        if big:      # soğuk büyük konuşmayı yeniden okutup hemen devir almak yerine taze aç (ysf 386K örneği); özet kartta/CLAUDE.md'de
            fresh = True
    kw = {"model": model, "effort": effort, "fresh": fresh, "lang": lang}
    kw.update(_launch_kwargs(name, model, effort))      # kayıtlı cli/cli_opts/model/effort (varsa) başlatma değerlerini geçer
    res = _act("start", name, **kw)
    if not res.get("ok"):
        _start_backoff_note(name, False)
        return dict(res, closed_in_models=True) if closed else res
    _record_owned(sid, _owned_project(name, sid) or name, name, "start")      # L2: değnekçinin açtığı oturum (görünür olmadan önce)
    if big:          # D2: yalnız GERÇEK başlatmada yaz (eskiden her denemede: vc 1-2 Kas 582 satır)
        sw.log_event("start_fresh_big_context", paths=sw.paths_for(sid), name=name, tokens=big)
    if not _start_appeared(name, sid):
        _start_backoff_note(name, False)
        return {"ok": False, "code": "start_not_visible", "name": name,
                "error": f"start for {name!r} returned ok but no session appeared within {START_APPEAR_SECONDS:g}s"}
    _start_backoff_note(name, True)
    cli = kw.get("cli") or _project_cli(name)
    ready = _wait_ready(name, cli)
    if ho_jsonl:
        h = _local_handover(name, sid, lang)
        real = _resolved_local_name(name, sid)
        if h.get("ok"):
            with sw.steward_lock(sid):      # READY FOR HANDOVER gelince motor `respawn` (stop + taze `--new`, aynı cli/cli_opts)
                state = sw.load_state(sid)
                state.setdefault("ho_pending", {})[real] = time.time()
                sw.save_state(state, sid)
        sw.log_event("ho_on_open", paths=sw.paths_for(sid), name=name, session=real, step="handover", ok=bool(h.get("ok")),
                     **({} if h.get("ok") else {"error": str(h.get("error") or "")[:200]}))
        return {"ok": True, "started": True, "ready": ready, "cli": cli, "ho_on_open": bool(h.get("ok"))}
    return {"ok": True, "started": True, "ready": ready, "cli": cli}


def _resume_lacks_ho(name: str, cfg: sw.Config) -> str:
    """Sahip kuralı (2026-11-05, "açarken ho yapılmamışsa yapıp kapatıp açmalı"): `start`ın `--resume` edeceği konuşma
    gerçek bir iş turu taşıyıp READY FOR HANDOVER olmadan bitmişse o jsonl'in yolu, değilse "". Yalnız claude (jsonl
    bilinir) ve `cfg.ho_on_open == "act"`; bilinmiyor/hata = "" (davranış değişmez). TBD#123 (büyük bağlam taze aç)
    bundan SONRA gelir: devir notu soğuk okumanın bedelinden önemli (TBD#162)."""
    if str(getattr(cfg, "ho_on_open", "act") or "act") != "act":
        return ""
    try:
        cwd = _cwd_resolver()(name)
        if not cwd or _project_cli(name) != "claude" or _launch_kwargs(name, "", "").get("cli") not in (None, "claude"):
            return ""
        from ..providers.claude_provider import jsonl_path_for
        from ..needs_ho import handover_done, has_real_user_turn
        rid = get_provider("claude").resolve_resume_id(cwd, session_name=name)
        path = jsonl_path_for(cwd, rid) if rid else None
        if not path or not os.path.isfile(path):
            return ""
        return "" if (not has_real_user_turn(path) or handover_done(path)) else str(path)
    except Exception:
        return ""

START_APPEAR_SECONDS = 6.0       # `start` ok döndükten sonra oturumun görünmesini bekleme üst sınırı (kısa poll)
START_APPEAR_POLL_SECONDS = 0.5


def _start_appeared(name: str, sid: str = "default", timeout: Optional[float] = None,
                    sleep: Callable[[float], None] = time.sleep) -> bool:
    """`start` 'ok' döndü: oturum GERÇEKTEN çalışanlar arasında mı (`danisppr` 2026-11: ok dönüp oturum açılmıyordu).
    Her yoklamada tarama önbelleği düşer (bayat önbellek yeni oturumu gizlerdi)."""
    limit = START_APPEAR_SECONDS if timeout is None else timeout
    waited = 0.0
    while True:
        _scan_invalidate()
        if _live_sessions(name, sid):
            return True
        if waited >= limit:
            return False
        sleep(START_APPEAR_POLL_SECONDS)
        waited += START_APPEAR_POLL_SECONDS


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


WAKE_GATED_REASONS = ("due",)    # motorun kendiliğinden ürettiği şablon uyandırması (cevap/iş/bulgu/devir/respawn/elle DEĞİL; `idle`/`review` direktif nedeni DEĞİL, madde türü); beyin direktifi ayrıca (`_wake_kind`)


def _wake_kind(reason: str, answer: Any, actor: str) -> str:
    """Kapıya giren uyandırma türü: "auto" (motorun `due` şablonu), "brain" (beyin direktifi, TBD#138) ya da ""."""
    if answer is not None:
        return ""
    if reason in WAKE_GATED_REASONS:
        return "auto"
    return "brain" if (reason == "brain" and actor == "brain") else ""


def _wake_sha(message: str) -> str:
    return hashlib.sha1(message.encode("utf-8", "replace")).hexdigest()[:12]


def _wake_gate(cfg: sw.Config, paths: Any, sname: str, reason: str, answer: Any, message: str, actor: str = "") -> bool:
    """TBD#121/125 uyandırma kapısı (yalnız otomatik şablon nedenleri; cevap/iş/bulgu/devir/elle ASLA): (1) aynı oturuma AYNI metin
    son `wake_repeat_minutes` dakikada gittiyse ("Plan hazır, SIRADAKİ işi al" tekrarı; her uyandırma tüm bağlamı yeniden okutur);
    (2) son 24 saatte `wake_max_per_day` otomatik uyandırma zaten gittiyse (3.sü yeni girdi/cevap ister). `dry`: yalnız
    `would:wake_repeat` / `would:wake_cap` olayı (False döner, direktif gider; ölçüm); `act`: True (gönderilmez)."""
    kind = _wake_kind(reason, answer, actor)
    if cfg.wake_gate not in ("dry", "act") or not kind:
        return False
    try:
        st = sw.load_state(paths)
    except Exception:
        return False
    now = time.time()
    rec = (st.get("wake_sent") or {}).get(sname) or {}
    age = now - float(rec.get("at") or 0)
    why = ""
    if cfg.wake_repeat_minutes > 0 and rec.get("sha") == _wake_sha(message) and age < cfg.wake_repeat_minutes * 60:
        why = "wake_repeat"
    elif kind == "auto" and cfg.wake_max_per_day > 0 and len([t for t in (st.get("auto_wake") or {}).get(sname, []) if now - float(t) < 86400]) >= cfg.wake_max_per_day:
        why = "wake_cap"
    elif kind == "brain" and cfg.brain_wake_max_per_day > 0 and len([t for t in (st.get("brain_wake") or {}).get(sname, []) if now - float(t) < 86400]) >= cfg.brain_wake_max_per_day:
        why = "brain_wake_cap"
    if not why:
        return False
    sw.log_event(f"would:{why}" if cfg.wake_gate == "dry" else f"{why}_skipped", paths=paths, name=sname, reason=reason,
                 minutes=round(age / 60, 1), chars=len(message))
    return cfg.wake_gate == "act"


def _wake_record(cfg: sw.Config, paths: Any, sname: str, reason: str, answer: Any, message: str, actor: str = "") -> None:
    kind = _wake_kind(reason, answer, actor)
    gated = bool(kind)
    if cfg.wake_gate not in ("dry", "act") or not (gated or reason == "answer" or answer is not None):
        return
    try:
        with sw.steward_lock(paths):
            state = sw.load_state(paths)
            if gated:
                now = time.time()
                state.setdefault("wake_sent", {})[sname] = {"sha": _wake_sha(message), "at": now}
                key = "brain_wake" if kind == "brain" else "auto_wake"
                aw = state.setdefault(key, {})
                aw[sname] = [t for t in aw.get(sname, []) if now - float(t) < 86400] + [now]
            else:      # cevap gitti = yeni girdi: günlük sayaçlar sıfırlanır
                (state.get("auto_wake") or {}).pop(sname, None)
                (state.get("brain_wake") or {}).pop(sname, None)
            sw.save_state(state, paths)
    except sw.LockTimeout:
        pass


# Yalnız bilgi/iş teslimatı: sahip girdisi değil, projeye "giriş" sayılmaz (etiketler kalır).
_NON_ENTRY_REASONS = frozenset({"job", "lesson", "advance", "upper_main", "job-red"})


def _give_directive(project: sw.Project, text: str, **kw: Any) -> Dict[str, Any]:
    """`_give_directive_impl` + etiket kuralı: başarılı girişten (start/cevap/direktif/yeniden açma; hepsi buradan geçer)
    sonra projenin `stuck`/`waiting-owner` etiketleri kalkar (`sw.auto_remove_labels`)."""
    res = _give_directive_impl(project, text, **kw)
    if isinstance(res, dict) and res.get("ok") and str(kw.get("reason") or "") not in _NON_ENTRY_REASONS:
        cfg = kw.get("cfg") or steward_config()
        sw.auto_remove_labels(project.name, sw.paths_for(cfg.sid), via=str(kw.get("reason") or "directive"))
    return res


def _give_directive_impl(project: sw.Project, text: str, *, model: str = "", effort: str = "",
                    answer: Optional[sw.Question] = None, more: Optional[List[sw.Question]] = None,
                    start_if_stopped: bool = True,
                    reason: str = "", session_name: str = "", cfg: Optional[sw.Config] = None,
                    host: Optional[str] = None, rt: Optional[_RemoteTick] = None, actor: str = "") -> Dict[str, Any]:
    """`project`'e (ya da onun `session_name` adlı çalışan instance'ına) direktif gönder; kapalıysa aç.
    Proje değnekçi kaydında değilse (ad hoc oturum) sadece gönderir, kayıt açmaz. Kayıtlar `cfg.sid`'in deposuna.

    Uzak hedef (`host`; None = addan çözülür, yerel yola ASLA düşmez): hedef ad (proje adı ya da tam oturum adı)
    `_remote_session` ile projenin TEK çalışan oturumuna çözülür (tarihli/_N'li ad dahil; iki oturum = red, başlatma
    yok); oturum yoksa `_ensure_running_remote` PROJE adıyla başlatır. Gönderim `POST /api/term/input` (`exact: true`,
    satırın GERÇEK adı), yaşam kimliği facts yaşından, `preamble_sent` anahtarı `host:<gerçek ad>` (aynı adlı yerel
    oturumun kaydına karışmaz). `actor` yalnız uzak red log'u için."""
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
    started_here = False      # bu çağrıda oturum AÇILDI: yeni yaşam, eski yaşamın `wake_sent` kaydı "tekrar" sayılmaz
    if host:
        world = _world(cfg.sid, cfg)
        fresh_host, row, err = _remote_session(host, target, rt, world, sid=cfg.sid, actor=actor, kind="directive")
        if not fresh_host:
            return {"ok": False, "error": "host_down", "code": "host_down", "host": host}
        if err is not None:
            return err
        if row is None:
            if not start_if_stopped:
                return {"ok": False, "error": "not running", "host": host}
            res = _ensure_running(target, model=model, effort=effort, lang=lang, host=host, rt=rt, sid=cfg.sid,
                                  actor=actor)
            if not res.get("ok"):
                return res
            started_here = bool(res.get("started"))
            # başlatmadan sonra: tick görüntüsü değil, önbellek şimdi; yeni oturumun adı tarihli (projeden çözülür)
            after = str(res.get("name") or "") or _remote_key(target, host, world) or target
            _f, row, err = _remote_session(host, after, world=world, sid=cfg.sid, actor=actor, kind="directive")
            if err is not None:
                return err
            if row is None:
                return {"ok": False, "error": "start reported ok but no session row on the host", "host": host}
        if not row.get("tmux"):
            return {"ok": False, "error": "not tmux-backed (cannot inject)", "host": host}
        sname, scli = str(row.get("name") or target), str(row.get("cli") or DEFAULT_CLI)
        born, pkey = _remote_born(host, sname, rt), f"{host}:{sname}"
    else:
        live = _live_sessions(target, cfg.sid)
        if len(live) > 1:     # hangisi? tahmin etme, üçüncüyü de açma
            return {"ok": False, "error": "ambiguous_sessions", "code": "ambiguous_sessions", "sessions": [x.name for x in live]}
        s = live[0] if live else None
        if s is None:
            if not start_if_stopped:
                return {"ok": False, "error": "not running"}
            res = _ensure_running(target, model=model, effort=effort, lang=lang, sid=cfg.sid)
            if not res.get("ok"):
                return res
            if res.get("ho_on_open"):    # açılışta devir gitti: direktif/cevap devirden sonraki TAZE oturuma (respawn) gider
                return {"ok": True, "name": target, "skipped": "ho_on_open", "started": True}
            started_here = bool(res.get("started"))
            live = _live_sessions(target, cfg.sid)
            s = live[0] if len(live) == 1 else _running(target)
            if s is None:
                return {"ok": False, "error": "start reported ok but no process found"}
        if not is_tmux_backed(s.pid):
            return {"ok": False, "error": "not tmux-backed (cannot inject)"}
        sname, scli = s.name, s.cli
        born, pkey = _proc_born(s.pid), s.name
    compact = False
    if born:
        try:     # bu süreç yaşamında tam başlık (amaç/not/protokol) zaten gitti mi?
            stored = float(sw.load_state(paths).get("preamble_sent", {}).get(pkey) or 0.0)
            compact = _same_life(stored, born, bool(host))
        except Exception:
            compact = False
    message = sw.build_directive(project, lang=lang, extra=text, answer=answer, more=more, compact=compact,
                                paths=paths)
    if not started_here and _wake_gate(cfg, paths, sname, reason, answer, message, actor):
        return {"ok": True, "name": sname, "skipped": "wake_repeat"}
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
    _wake_record(cfg, paths, sname, reason, answer, message, actor)
    sw.log_event("directive", paths=paths, name=project.name, reason=reason, chars=len(message),
                 **({"host": host} if host else {}))
    try:
        from .. import qa_log
        qa_log.append_qa(getattr(project, "local_path", ""), "directive", actor or "brain", message, ref=reason)
    except Exception:
        pass
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
    host = (project.host if project is not None else "") or _name_host(name)
    if host:
        # Uzak proje (A6): ham kart uzak belge başlarından; YEREL klasör/git ASLA (aynı yoldaki yerel klasör onun değil).
        if raw is None:
            if not _remote_files_gate(host, cfg.sid):
                return {"ok": False, "name": name, "error": "remote host unavailable or remote actions off", "host": host}
            raw = _remote_raw_card(host, name, REMOTE_CARD_BUDGET_SECONDS)
            if raw is None:
                return {"ok": False, "name": name, "error": "remote project documents unreadable", "host": host}
    else:
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
                      now: Optional[float] = None, remote_limit: int = MAX_REMOTE_CARDS_PER_TICK,
                      remote_budget: float = REMOTE_CARD_BUDGET_SECONDS) -> List[Dict[str, Any]]:
    """Kartı olmayan / bayat / kaynağı değişmiş / eskimiş, ÇALIŞMAYAN, aktif fazdaki projeleri yenile (en çok
    `limit`; None = `cards_per_tick`). Önce kartı hiç olmayanlar, sonra en eski kart. Çalışan proje atlanır:
    oturum yazarken kaynak zaten değişiyor (handover'dan sonra `mark_card_stale` ile işaretlenir).
    Projeler `cfg.sid`'in deposundan; default dışı kimlikte çakışmalı projeler atlanır (kimse yönetmez).
    Uzak proje (A6): `remote_actions` açık + host taze iken belge başları host-routed okunur (tick başına en çok
    `remote_limit` proje, TOPLAM `remote_budget` sn; en eski denetlenen önce); host kapalı/okuma hatası = atlanır,
    kart YEREL `steward/cards/`a yazılır (uzağa hiçbir şey yazılmaz)."""
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
    remote_projects: List[sw.Project] = []
    for p in projects.values():
        if p.phase not in sw.ACTIVE_PHASES or p.name in running:
            continue
        if p.host:       # uzak proje: aşağıda, uzak okumayla (yerel cwd çözümü bu projeye HİÇ uygulanmaz)
            remote_projects.append(p)
            continue
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
    if remote_projects and remote_limit > 0 and len(results) < limit:
        results += _refresh_remote_cards(cfg, remote_projects, cards, now, min(remote_limit, limit - len(results)),
                                         remote_budget)
    return results


def _refresh_remote_cards(cfg: sw.Config, projects: List[sw.Project], cards: Dict[str, Any], now: float,
                          limit: int, budget: float) -> List[Dict[str, Any]]:
    """`refresh_due_cards`ın uzak kolu: kapı geçen (remote_actions + taze host) projelerden en eski denetlenen
    `limit` tanesinin belgelerini okur, yenilemesi gerekiyorsa kartı üretir. Okunamayan proje sessizce atlanır
    (kart/deneme kaydı DEĞİŞMEZ); fırlatmaz."""
    deadline = time.monotonic() + budget
    results: List[Dict[str, Any]] = []
    gated = [p for p in projects if _remote_files_gate(p.host, cfg.sid)]
    gated.sort(key=lambda p: (_REMOTE_CARD_CHECKED.get(p.name, 0.0), p.priority, p.name))
    for p in gated[:limit]:
        _REMOTE_CARD_CHECKED[p.name] = now
        try:
            raw = _remote_raw_card(p.host, p.name, deadline - time.monotonic())
            if raw is None:
                continue
            reason = sw.card_refresh_reason(cards.get(p.name), raw["source_hash"], now, cfg.card_max_age_hours)
            if reason:
                results.append(refresh_card(p.name, cfg, raw=raw, reason=reason))
        except Exception as e:
            diag_log("steward_card_crashed", name=p.name, error=repr(e), host=p.host)
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
    text = sw.build_workspace_claude_md(persona, lang=cfg.lang, sid=cfg.sid, label=cfg.label, remote=has_remote, role=cfg.role)
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


def _verify_brain_mcp(cfg: sw.Config, since: float) -> bool:
    """Açılıştan (`since`) sonra cops-steward MCP `initialize` aldı mı: `brain_mcp_wait_seconds` içinde bekler. Kapalı ayar = True."""
    if not cfg.brain_mcp_check:
        return True
    paths = sw.paths_for(cfg.sid)
    deadline = time.time() + max(0, int(cfg.brain_mcp_wait_seconds))
    while True:
        if sw.read_brain_mcp(paths)["connected_at"] >= since:
            return True
        if time.time() >= deadline:
            return False
        time.sleep(1.0)


def _brain_ucli_opts(cfg: sw.Config, provider, model: str, workspace: str) -> Tuple[Dict[str, Any], str, str]:
    """`brain_cli=ucli` beyninin başlatma seçenekleri -> (temiz `cli_opts`, model, hata). Hizmet `brain_service` (varsayılan
    claude = Anthropic API), tur başına USD tavanı `brain_max_cost_usd`; ikisi de ucli başlat penceresinin doğrulayıcısından
    (`validate_cli_opts`) geçer. `brain_model` boşsa ve hizmet Evren değilse model hizmetin ilk modeli (Evren kataloğu modeli
    Anthropic'te yok). Talimat dosyası (CLAUDE.md) ucli'nin 40 KiB sınırını aşarsa `--instructions-auto` zaten atlanır:
    burada yalnız uyarı kaydı düşülür (beyin personasız açılır)."""
    raw: Dict[str, Any] = {"service": (cfg.brain_service or "claude").strip().lower()}
    if cfg.brain_max_cost_usd > 0:
        raw["max_cost_usd"] = cfg.brain_max_cost_usd
    opts, err = provider.validate_cli_opts(raw)
    if err:
        return {}, model, f"beyin ucli seçenekleri geçersiz: {err}"
    service = opts.get("service") or ""
    if not model and service and service != "evren":
        from ..settings import ucli_services
        models = next((d.get("models") or [] for d in ucli_services() if d["id"] == service), [])
        if not models:
            return {}, model, f"beyin: {service} hizmetinde model yok; brain_model ayarla"
        model = models[0]
    elif not model:
        model = default_model_for(provider)
    try:
        from ..providers.ucli_provider import instructions_check
        if any(f.get("over") for f in instructions_check(workspace).get("files", [])):
            sw.log_event("brain_instructions_too_big", paths=cfg.sid, name=cfg.brain_name, workspace=workspace)
    except Exception:
        pass
    return opts, model, ""


def brain_start(cfg: Optional[sw.Config] = None, fresh: bool = True, _mcp_retry: bool = False) -> Dict[str, Any]:
    """Kimliğin beynini aç (kendi workspace'i, `mcp-steward --steward <sid>`). VARSAYILAN YENİ konuşma (`fresh`; sahip kararı
    2026-11-05: beynin hafızası konuşmada değil dosyalarda: state/kartlar/NOTLAR.md; eski konuşmayı `--resume` etmek şişmiş,
    bayat ve soğuk önbellekte pahalı bağlam taşır). Default dışı kimlik YALNIZ `enabled` iken
    açılır (hiçbir yeni kimlik kendiliğinden beyin açmaz; ayar varsayılan KAPALI); default'un davranışı eskisiyle aynı."""
    cfg = cfg or steward_config()
    if cfg.role == "reviewer":      # reviewer'ın beyni yok (review_tick kendi çalıştırıcısıyla iş görür)
        return {"ok": False, "error": f"steward {cfg.sid} is a reviewer; it has no brain session"}
    if cfg.sid != "default" and not cfg.enabled:
        return {"ok": False, "error": f"steward {cfg.sid} is disabled; its brain is not started"}
    if _running(cfg.brain_name) is not None:
        return {"ok": True, "started": False, "name": cfg.brain_name}
    ensure_workspace(cfg)
    workspace = sw.paths_for(cfg.sid).workspace
    cli = cfg.brain_cli if cfg.brain_cli in PROVIDERS else DEFAULT_CLI
    provider = get_provider(cli)
    # ucli: model hizmete bağlı (Evren kataloğu Anthropic'te yok), `_brain_ucli_opts` seçer (Evren'e ağ isteği atmadan)
    model = cfg.brain_model or ("" if cli == "ucli" else default_model_for(provider))
    effort = cfg.brain_effort or default_effort_for(provider)
    mode = provider.permission_modes()[0] if provider.permission_modes() else "auto"
    if cli == "ucli" and cfg.brain_permission in (provider.permission_modes() or []):
        mode = cfg.brain_permission     # ucli beyni devir notunu workspace'e yazabilsin (aksi halde salt-okunur: 2 Kas gözlemi B1)
    extra: Dict[str, Any] = {}
    if cli == "ucli":     # Anthropic API (dolar) ile beyin: başlat penceresiyle AYNI `cli_opts` yolu; claude yolu birebir aynı kalır
        opts, model, err = _brain_ucli_opts(cfg, provider, model, workspace)
        if err:
            sw.log_event("brain_start_refused", paths=cfg.sid, name=cfg.brain_name, error=err)
            return {"ok": False, "error": err}
        extra["cli_opts"] = opts or None
    t_spawn = time.time()
    inst_mod.record_instance(cfg.brain_name, blueprint=None, cwd=workspace, cli=cli, model=model,
                             permission_mode=mode, effort=effort, origin="steward")
    try:
        with guard_lock(timeout=GUARD_LOCK_ACQUIRE_TIMEOUT):
            _scan_invalidate()
            kind = spawn_session(name=cfg.brain_name, cwd=workspace, model=model, display=detect_display(),
                                 permission_mode=mode, effort=effort, force_new=bool(fresh), cli=cli,
                                 mcp_server=brain_spec(cfg.sid), **extra)
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    except ValueError as e:     # ucli `_apply_cli_opts` reddi (anahtar yok, günlük USD tavanı aşıldı, bayrak yok)
        if cli != "ucli":
            raise
        sw.log_event("brain_start_refused", paths=cfg.sid, name=cfg.brain_name, error=str(e))
        return {"ok": False, "error": str(e)}
    inst_mod.mark_started(cfg.brain_name, cli=cli, model=model, permission_mode=mode, effort=effort)
    ready = _wait_ready(cfg.brain_name, cli)
    sw.log_event("brain_start", paths=cfg.sid, name=cfg.brain_name, kind=kind, ready=ready)
    if not _verify_brain_mcp(cfg, t_spawn):
        sw.log_event("brain_mcp_missing", paths=cfg.sid, name=cfg.brain_name, retry=_mcp_retry)
        if not _mcp_retry:        # BİR kez yeniden aç (döngü yok)
            _notify(cfg, f"[{cfg.sid}] Beyin açıldı ama cops-steward araçları bağlanmadı; bir kez yeniden açılıyor.")
            brain_stop(cfg)
            time.sleep(3)
            return dict(brain_start(cfg, fresh=fresh, _mcp_retry=True), mcp_retried=True)
        _notify(cfg, f"[{cfg.sid}] Beyin yeniden açıldı ama cops-steward araçları hâlâ bağlanmadı; elle bakmak gerek.")
    return {"ok": True, "started": True, "name": cfg.brain_name, "kind": kind, "ready": ready}


def brain_stop(cfg: Optional[sw.Config] = None) -> Dict[str, Any]:
    cfg = cfg or steward_config()
    if _running(cfg.brain_name) is None:
        return {"ok": True, "stopped": False}
    note = _brain_close_note(cfg)        # model turu YOK: motor kapanış notunu NOTLAR.md'ye yazar (yeni beyin açılışta okur)
    res = _act("stop", cfg.brain_name, lang=cfg.lang)
    sw.log_event("brain_stop", paths=cfg.sid, name=cfg.brain_name, ok=bool(res.get("ok")), note=bool(note))
    return res


def _brain_close_note(cfg: sw.Config) -> bool:
    """Beyin kapanırken `NOTLAR.md` sonuna kısa, belirlenimli bir kapanış bloğu ekler (açık sorular, bekleyen ho). Asla fırlatmaz."""
    try:
        paths = sw.paths_for(cfg.sid)
        ws = paths.workspace
        state = sw.load_state(paths)
        qs = [q for q in sw.load_questions(paths) if q.status == "open"]
        lines = [f"\n## Kapanış notu {time.strftime('%Y-%m-%d %H:%M')} (motor yazdı, model turu yok)",
                 f"- açık soru sayısı: {len(qs)}; ho bekleyen: {sorted((state.get('ho_pending') or {}))}",
                 "- yeni açılışta durumu `steward_*` araçlarıyla taze oku; bu not yalnız izdir."]
        os.makedirs(ws, exist_ok=True)
        with open(os.path.join(ws, "NOTLAR.md"), "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return True
    except Exception:
        return False


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


GENERIC_DOC_CHARS = 6000     # generic iş listesi için TODO.md/TOBEDECIDED.md başından okunan en çok karakter


def _attach_backlog(it: Dict[str, Any], projects: Dict[str, sw.Project]) -> None:
    """generic tur maddesine `backlog` ({auto, decide}) ekle: kart + YEREL TODO.md/TOBEDECIDED.md başı. Uzak projede
    yerel dosya sistemi okunmaz (yalnız kart). Proje dışı madde (fikir, genel soru) dokunulmaz."""
    if it.get("kind") in ("idea", "routine") or it.get("name") not in projects:
        return
    name = str(it["name"])
    todo = tbd = ""
    cwd = "" if (it.get("host") or _name_host(name)) else _project_cwd(name)
    if cwd:
        todo = _read_head(cwd, "TODO.md", GENERIC_DOC_CHARS)
        tbd = _read_head(cwd, "TOBEDECIDED.md", GENERIC_DOC_CHARS)
    bl = sw.generic_backlog(todo, tbd, it.get("card"))
    if bl["auto"] or bl["decide"]:
        it["backlog"] = bl


TOUR_FAILS_BEFORE_RESTART = 2    # art arda bu kadar tur gönderimi başarısızsa beyin oturumu yeniden açılır


def brain_restart_for_stuck_input(cfg: sw.Config) -> Dict[str, Any]:
    """Beyin oturumunu durdurup yeniden aç (konuşma `--resume` ile sürer; giriş kutusu temizlenir)."""
    stop = _act("stop", cfg.brain_name, lang=cfg.lang)
    if not stop.get("ok"):
        return stop
    time.sleep(3)
    return brain_start(cfg)


def _brain_last_text(cfg: sw.Config) -> str:
    """Beynin son asistan metni (okunamazsa "")."""
    try:
        v = next((x for x in _collect_views(cfg) if x.name == cfg.brain_name), None)
        return (v.last_assistant or "") if v is not None else ""
    except Exception:
        return ""


def _brain_notools_recover(cfg: sw.Config, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Tur göndermeden önce: önceki tur araçsız mı geçti ("araçlar yok" metni ya da art arda N turda hiç steward_* çağrısı
    yok)? Öyleyse beyni BİR kez yeniden aç (log + ntfy; `BRAIN_MCP_RESTART_COOLDOWN` içinde ikinci kez açma). None = müdahale yok;
    dict = yeniden açma sonucu (ok değilse tur gönderilmez)."""
    t = time.time() if now is None else now
    paths = sw.paths_for(cfg.sid)
    state = sw.load_state(paths)
    prev = float(state.get("last_tour") or 0.0)
    nocall, why = sw.brain_notools_verdict(prev, sw.read_brain_mcp(paths), _brain_last_text(cfg) if prev else "",
                                           int(state.get("tour_nocall") or 0), cfg, t)
    last_restart = float(state.get("brain_mcp_restart_at") or 0.0)
    if why and last_restart and t - last_restart < sw.BRAIN_MCP_RESTART_COOLDOWN:
        sw.log_event("brain_notools_cooldown", paths=paths, why=why)
        nocall, why = 0, ""
    with sw.steward_lock(paths):
        state = sw.load_state(paths)
        if nocall:
            state["tour_nocall"] = nocall
        else:
            state.pop("tour_nocall", None)
        if why:
            state["brain_mcp_restart_at"] = t
        sw.save_state(state, paths)
    if not why:
        return None
    sw.log_event("brain_notools_restart", paths=paths, why=why)
    _notify(cfg, f"[{cfg.sid}] Beyin araçsız kaldı ({why}); bir kez yeniden açılıyor.")
    rb = brain_restart_for_stuck_input(cfg)
    return dict(rb, notools_restart=True)


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
    if res.get("started") is False:      # beyin zaten çalışıyordu: önceki turun sonucuna bak (araçsız mı kaldı)
        rb = _brain_notools_recover(cfg)
        if rb is not None and not rb.get("ok"):
            return rb
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
    if sw.is_generic(cfg):      # generic: her proje maddesine otonom/karar-gerekir iş listesi (beyin karar-gerekiri ATLAR)
        for it in enriched:
            _attach_backlog(it, projects)
    prompt = sw.build_tour_prompt(enriched, lang=cfg.lang, open_qs=sw.open_questions(paths=paths), now=time.time())
    try:
        message, tour_file = sw.tour_delivery(prompt, paths.workspace, time.time(), cfg.lang)
    except OSError:
        message, tour_file = prompt, ""      # dosya yazılamadı: eski yol (tmux'e gömülü)
    if not _send(s.name, s.cli, message):
        return {"ok": False, "error": "send failed"}
    with sw.steward_lock(paths):
        state = sw.load_state(paths)
        state["last_tour"] = time.time()
        sw.save_state(state, paths)
    sw.log_event("tour", paths=paths, items=len(enriched), chars=len(prompt), **({"file": tour_file} if tour_file else {}))
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


def maybe_pending_digest(cfg: sw.Config, now: float) -> bool:
    """D4: `PENDING_DIGEST_HOURS` dilimlerinde (günde 2) bekleyen sahip soruları için TEK ntfy özeti; dilim başına bir kez
    (`state.pending_digest_slot`), soru yoksa gönderilmez ve dilim yine işaretlenir. True = gönderildi."""
    paths = sw.paths_for(cfg.sid)
    slot = sw.pending_digest_slot(now)
    if not slot:
        return False
    state = sw.load_state(paths)
    if state.get("pending_digest_slot") == slot:
        return False
    text = sw.pending_digest_text(sw.load_questions(paths), now, cfg.lang, cfg.sid)
    sent = bool(text) and _notify(cfg, text[:NTFY_SUMMARY_CHARS])
    with sw.steward_lock(paths):
        state = sw.load_state(paths)
        state["pending_digest_slot"] = slot
        sw.save_state(state, paths)
    if text:
        sw.log_event("pending_digest", paths=paths, slot=slot, notified=sent)
    return sent


def maybe_dry_ask(cfg: sw.Config, now: float) -> Optional[str]:
    """TBD#138 a: bir ölçüm (dry) kipi `DRY_REPORT_HOURS` saattir olay üretiyorsa sahibe TEK "act?" sorusu (kip başına bir kez,
    `state.dry_asked`). Kip hâlâ dry değilse sorulmaz (sahip zaten karar verdi). Dönen: açılan sorunun kimliği ya da None."""
    paths = sw.paths_for(cfg.sid)
    state = sw.load_state(paths)
    cur = {"wake_gate": cfg.wake_gate, "keepwarm": cfg.keepwarm, "idle_big_handover": "dry"}
    long_rep = sw.dry_report(paths, hours=7 * 24, now=now)      # "ne zamandır olay üretiyor" için uzun pencere (72 sa pencere `first`i kırpardı)
    due = [k for k in sw.dry_ask_due(long_rep, state.get("dry_asked"), now) if cur.get(k) == "dry"]
    if not due:
        return None
    rep = sw.dry_report(paths, now=now)
    text = (f"Ölçüm (dry) kipleri {sw.DRY_REPORT_HOURS} saattir çalışıyor, act'e geçelim mi? Kipler: {', '.join(due)}.\n"
            + sw.dry_report_text(rep) + "Rapor: py/cops steward dry-report. Öneri: sayılar makulse act, değilse dry kalsın.")
    q, how = sw.add_question_ex("", text, source="dry-report", options=["act aç", "dry kalsın"], paths=paths)
    with sw.steward_lock(paths):
        state = sw.load_state(paths)
        state["dry_asked"] = sorted(set(state.get("dry_asked") or []) | set(due))
        sw.save_state(state, paths)
    if how in ("new", "promoted"):
        _notify(cfg, f"{_ask_prefix(q.project, cfg.sid)} {q.text}\n→ {sw.ask_hint(q.id, cfg.sid)}"[:NTFY_SUMMARY_CHARS])
        sw.mark_notified(q.id, paths)
    sw.log_event("dry_ask", paths=paths, kips=due)
    return q.id


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


def _remote_nudge(name: str, host: str, action: sw.Action, cfg: sw.Config, paths: Any, world: sw.World,
                  rt: Optional[_RemoteTick]) -> Dict[str, Any]:
    """Uzak host'ta API hatasında takılan oturuma tek satır "devam" (`nudge`). `_target` kapıları (`remote_actions`, taze host,
    kayıtlı proje) `_apply`da zaten geçildi; burada oturum host'ta TAM adla bulunur (`_remote_session`: 2+ oturum = red,
    başlatma YOK), tmux'lu olmalı ve gönderim `/api/term/input {"exact": true}` (yönerge yoluyla aynı, yıkıcı değil)."""
    fresh_host, row, err = _remote_session(host, name, rt, world, sid=cfg.sid, actor="engine", kind="nudge")
    if not fresh_host:
        return {"ok": False, "error": "host_down", "code": "host_down", "host": host}
    if err is not None:
        return err
    if row is None:
        return {"ok": False, "error": "not running", "host": host}
    if not row.get("tmux"):
        return {"ok": False, "error": "not tmux-backed (cannot inject)", "host": host}
    sname = str(row.get("name") or name)
    sent = _remote_post(host, "/api/term/input", {"name": sname, "text": str(action.payload.get("text") or sw.API_NUDGE_TEXT),
                                                   "exact": True}, REMOTE_INPUT_TIMEOUT_SECONDS, rt)
    ok = bool(sent.get("ok"))
    sw.log_event("done_confirm_asked" if action.payload.get("confirm") else "api_nudge", paths=paths, name=sname, host=host,
                 n=action.payload.get("n"), reason=action.reason, ok=ok)
    return {"ok": True, "host": host} if ok else dict(sent, ok=False, error=str(sent.get("error") or "send failed"), host=host)


def _local_handover(name: str, sid: str, lang: str) -> Any:
    """Yerel canlı devir. Oturumun/projenin AÇIK soruları devir mesajına eklenir (yeni oturum aynı soruyu yeniden
    açmasın; `sw.handover_questions_note`). Soru okunamazsa ya da yoksa mesaj eskisi gibi gider. Uzak devirde yok."""
    real = _resolved_local_name(name, sid)
    try:
        p = _project_for_session(real, sw.load_projects(sid), _world(sid))
        extra = sw.handover_questions_note(sw.load_questions(sw.paths_for(sid)), real, lang,
                                           project=p.name if p is not None else name)
    except Exception:       # soru dosyası okunamadı: devir yine de gitmeli
        extra = ""
    return _act("handover", real, lang=lang, extra=extra) if extra else _act("handover", real, lang=lang)


def _remote_handover(name: str, host: str, rt: Optional[_RemoteTick] = None, *, sid: str = "default",
                     actor: str = "") -> Dict[str, Any]:
    """Uzak devir: ön denetim (`_remote_session`: projenin TEK çalışan oturumu, tarihli ad dahil; iki oturum = red)
    sonra `POST /api/handover` satırın GERÇEK adıyla (`exact: true`: eski host alanı yok sayar, yeni host unique_base'e
    düşmez; gövdede host YOK). Canlı mesaj; kill/respawn uzak tarafta da yok. Yanıtta `name` = gerçek ad."""
    fresh_host, row, err = _remote_session(host, name, rt, sid=sid, actor=actor, kind="handover")
    if not fresh_host:
        return {"ok": False, "error": "host_down", "code": "host_down", "host": host}
    if err is not None:
        return err
    if row is None:
        return {"ok": False, "error": "not running (no running session of the project on the host)", "host": host}
    real = str(row.get("name") or name)
    return dict(_remote_post(host, "/api/handover", {"name": real, "exact": True}, REMOTE_HANDOVER_TIMEOUT_SECONDS, rt),
                host=host, name=real)


def _remote_stop(name: str, host: str, world: sw.World, sid: str, actor: str,
                 rt: Optional[_RemoteTick] = None) -> Dict[str, Any]:
    """Uzak durdurmanın TEK yolu (A4; `_target` kapıları çağırandan önce geçildi). Sıra:
    1. host taze, `_remote_session` adı projenin TEK çalışan oturumuna çözüyor (tarihli/_N'li ad dahil; iki oturum =
       `ambiguous_sessions`); bundan sonra her şey o satırın GERÇEK adıyla;
    2. satır bu kimliğin kayıtlı proje oturumu: `sw.select_rows` onu bu host için seçiyor VE sınıfı "own" (uzak beyin,
       servis, kayıtsız ya da başka kimliğin oturumu DEĞİL);
    3. host `exact_target` bildiriyor (`host_capabilities`); bildirmeyen eski host'ta (api 0) `remote_too_old` olayı
       (tekrarsız) ve eylem YOK. Yetenek bilinemediyse (yoklama ağ hatası, önbellek yok) de uygulanmaz;
    4. tick içinde (`rt`) host başına `MAX_DESTRUCTIVE_PER_HOST` (`destructive_budget`: ertelenir, gönderilmez);
    5. `POST /api/stop {"name", "exact": true}` (`REMOTE_STOP_TIMEOUT_SECONDS`, gövdede host YOK).
    Yanıt `ok: false` (ör. `no_exact_match`: uzakta tam ad yok) uygulanmış SAYILMAZ, `remote_stop_rejected` loglanır;
    uygulama düzeyi ret devre kesiciyi açmaz (taşıma hatası `_remote_post`ta A3 kuralıyla açar). Sayaç gönderimden
    ÖNCE artar: yanıtı ne olursa olsun bu tick'te host'a ikinci yıkıcı istek gitmez. Yanıtta `name` = gerçek ad."""
    fresh_host, row, err = _remote_session(host, name, rt, world, sid=sid, actor=actor, kind="stop")
    if not fresh_host:
        return {"ok": False, "error": "host_down", "code": "host_down", "host": host}
    if err is not None:
        return err
    if row is None:
        return {"ok": False, "error": "not running (no running session of the project on the host)",
                "code": "no_exact_row", "host": host}
    name = str(row.get("name") or name)
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
               host=host, name=name)
    if not res.get("ok"):
        sw.log_event("remote_stop_rejected", paths=sid, name=name, host=host, actor=actor or "human",
                     error=str(res.get("error") or ""), code=str(res.get("code") or ""))
        res["ok"] = False
    return res


def _remote_wait_closed(host: str, name: str, timeout: float = READY_TIMEOUT_SECONDS) -> bool:
    """Uzak durdurmadan sonra satırın kapanmasını bekle. AĞ ÇAĞRISI YAPMAZ: poller önbelleğine
    `REMOTE_READY_POLL_SECONDS`te bir bakar; host taze VE adı TAM `name` olan çalışan satır yoksa True, en çok
    `timeout`. Host bayatsa kapanma DOĞRULANAMAZ (beklemeye devam). `name` durdurulan oturumun GERÇEK adıdır
    (`_remote_stop` yanıtının `name`i), proje adı değil."""
    for i in range(max(1, int(timeout / REMOTE_READY_POLL_SECONDS))):
        if i:
            _remote_sleep(REMOTE_READY_POLL_SECONDS)
        fresh_host, r = _remote_running_row(host, name)
        if fresh_host and r is None:
            return True
    return False


def _remote_stop_and_wait(name: str, host: str, world: sw.World, sid: str, actor: str,
                          rt: Optional[_RemoteTick] = None) -> Optional[Dict[str, Any]]:
    """Yeniden açmanın ve restart'ın durdurma adımı: projenin (`_remote_session`) tek çalışan oturumu varsa
    `_remote_stop` + o GERÇEK adın kapanma beklemesi (`READY_TIMEOUT_SECONDS`). None = devam edilebilir (durdu ya da
    zaten kapalıydı); aksi halde başarısızlık yanıtı (çağıran sonraki adıma GEÇMEZ; iki oturum ya da başka bir oturum
    çalışıyorsa da). Durdurmadan sonra tick görüntüsü o host için yenilenir (`rt.refresh`)."""
    fresh_host, row, err = _remote_session(host, name, rt, world, sid=sid, actor=actor, kind="stop")
    if not fresh_host:
        return {"ok": False, "error": "host_down", "code": "host_down", "host": host}
    if err is not None:
        return err
    if row is None:
        return None          # zaten kapalı (devir sonrası oturum kendisi çıkmış): durdurulacak bir şey yok
    real = str(row.get("name") or name)
    res = _remote_stop(real, host, world, sid, actor, rt)
    if not res.get("ok"):
        return res
    real = str(res.get("name") or real)
    closed = _remote_wait_closed(host, real)
    if rt is not None:
        rt.refresh(host)
    if not closed:
        return {"ok": False, "error": f"stop sent but {real!r} still running on {host} after "
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
    # PROJE adıyla başlat: eski oturumun tarihli adı kapandı, uzak taraf yeni oturuma yeni (tarihli) ad verir
    res = _ensure_running_remote(project.name, host, model, effort, True, rt, sid=cfg.sid, actor="engine",
                                 kind="respawn")
    if not res.get("ok"):
        return failed("start", res)
    if rt is not None:
        rt.refresh(host)
    res = _give_directive(project, "", reason="respawn", session_name=str(res.get("name") or ""), cfg=cfg,
                          start_if_stopped=False, host=host, rt=rt, actor="engine")
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
        return _remote_handover(name, host, rt, sid=cfg.sid, actor="engine") if host else _local_handover(name, cfg.sid, cfg.lang)
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
        res = _ensure_running(name, model=model, effort=effort, lang=cfg.lang, fresh=True, sid=cfg.sid, exact=True)
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
        return _give_directive(p, "", answer=q, reason=action.reason, cfg=cfg, host=host, rt=rt, actor="engine")
    if k == "stop":
        res = _act("stop", name, lang=cfg.lang)
        pz = action.payload.get("pause")
        if isinstance(pz, dict) and pz.get("project") and isinstance(res, dict) and res.get("ok"):
            # keepwarm zinciri: devir BİTTİ ve oturum kapandı; şimdi paused + gerekçe (notlara eklenir, ntfy YOK)
            reason = str(pz.get("reason") or "")
            cur = projects.get(str(pz["project"]))
            note = ((cur.notes + "\n") if cur is not None and cur.notes else "") + f"[paused {time.strftime('%Y-%m-%d %H:%M')}] {reason}"
            sw.upsert_project(str(pz["project"]), paths=paths, phase="paused", notes=note)
            sw.log_event("keepwarm_chain_pause", paths=paths, name=name, project=pz["project"], reason=reason)
        return res
    if k == "auto_answer":
        q = sw.answer_question(action.payload.get("question_id") or "", action.payload.get("answer") or "", paths)
        if q is None:
            return {"ok": False, "error": "question gone"}
        if action.payload.get("handover"):
            sw.mark_delivered(q.id, paths)   # devir mesajı zaten gidiyor: cevap yeni oturuma ayrıca iletilmez
        return {"ok": True, "id": q.id, "handover": bool(action.payload.get("handover"))}
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
                              host=host, rt=rt, actor="engine")
        if not res.get("ok") and q.project not in projects:
            # Kayıtlı proje olmayan (ad hoc) oturum kapanmış ya da yazı kabul etmiyor: her tick yeniden deneme,
            # bırak (cevap kayıtta durur, kimse beklemiyor).
            kept = _preserve_undelivered_answer(q, cfg, paths, projects)
            sw.mark_undeliverable(q.id, str(res.get("error") or "undeliverable") + (f"; TOBEDECIDED.md'ye yazıldı" if kept in ("written", "already") else ""), paths)
            sw.log_event("answer_undeliverable", paths=paths, id=q.id, session=name, error=res.get("error", ""))
            _notify(cfg, (f"Cevabın {name} oturumuna İLETİLEMEDİ ({res.get('error', '')}): [{q.id}] {q.answer[:120]}" if cfg.lang != "en"
                          else f"Your answer could NOT be delivered to {name} ({res.get('error', '')}): [{q.id}] {q.answer[:120]}"))
        if not res.get("ok") and q.project in projects:
            # Kayıtlı proje: cevap kayıtta KALIR ve her tick yeniden denenir (kaybolmaz), ama art arda başarısızlık sessiz
            # kalmasın (7 Kas copsdev: 6 saat "send failed"): eşikte olay + sahibe tek bildirim.
            n = _ANSWER_FAILS.get(q.id, 0) + 1
            _ANSWER_FAILS[q.id] = n
            if n == ANSWER_FAIL_ALERT:
                sw.log_event("answer_delivery_failing", paths=paths, id=q.id, session=name, tries=n, error=res.get("error", ""))
                _notify(cfg, (f"Cevap {name} oturumuna {n} denemedir İLETİLEMİYOR ({res.get('error', '')}): [{q.id}] {q.answer[:120]}" if cfg.lang != "en"
                              else f"Answer to {name} still NOT delivered after {n} tries ({res.get('error', '')}): [{q.id}] {q.answer[:120]}"))
        elif res.get("ok"):
            _ANSWER_FAILS.pop(q.id, None)
        return res
    if k == "deliver_findings":
        if not host:
            denied = _target(name, "engine", projects, k, sid=cfg.sid, world=world)
            if denied is not None:
                return denied
        return _deliver_findings(action, cfg, projects, host=host, rt=rt)
    if k == "deliver_lesson":
        if not host:
            denied = _target(name, "engine", projects, k, sid=cfg.sid, world=world)
            if denied is not None:
                return denied
        return _deliver_lesson(action, cfg, projects, host=host, rt=rt)
    if k == "deliver_job":
        if not host:      # uzak hedef yukarıda (host kapılarıyla) denetlendi
            denied = _target(name, "engine", projects, k, sid=cfg.sid, world=world)
            if denied is not None:
                return denied
        return _deliver_job(action, cfg, projects, host=host, rt=rt)
    if k == "ask_user" and action.reason == "STEWARD-JOB" and action.payload.get("text", "").startswith(sw.JOB_REQUEST_PREFIX):
        gate = _job_marker_gate(action, cfg, name, host, paths)     # gerçek servis iş isteği değilse soru/rutin madde AÇILMAZ
        if gate is not None:
            return gate
    if k == "ask_user":
        q, outcome = sw.add_question_ex(action.payload.get("project") or name, action.payload.get("text") or "", source=name,
                                        routine=bool(action.payload.get("routine")), paths=paths)
        if q.status == "open" and q.routine:   # işleyiş sorusu: telefona gitmez, beynin turunda cevaplanır
            return {"ok": True, "id": q.id, "notified": False, "routine": True}
        if q.status != "open":   # yakın zamanda cevaplanmış soru yeniden soruldu: telefona yeni soru gitmez, cevap yeniden iletilir
            return {"ok": True, "id": q.id, "notified": False, "reasked": True}
        if outcome in ("same", "merged"):   # zaten açık (sahibe bir kez bildirildi): mükerrer bildirim yok
            return {"ok": True, "id": q.id, "notified": False, "merged": True}
        notified = _notify(cfg, f"{_ask_prefix(q.project, cfg.sid)} {q.text}\n→ {sw.ask_hint(q.id, cfg.sid)}")
        return {"ok": True, "id": q.id, "notified": notified}
    if k == "close_stale_answer":      # bayat blokaj kaydı: teslim edilecek proje yok, tekrar tura düşmesin
        why = str(action.payload.get("reason") or "")
        qd = next((x for x in sw.load_questions(paths) if x.id == str(action.payload.get("question_id") or "")), None)
        if qd is not None and qd.answer and not qd.delivered_at:     # cevap KAYBOLMASIN: önce TOBEDECIDED.md'ye (yerel) / sahibe bildirim (uzak)
            kept = _preserve_undelivered_answer(qd, cfg, paths, projects)
            why = (why or "bayat blokaj kaydı") + (f"; cevap TOBEDECIDED.md'ye yazıldı" if kept in ("written", "already") else f"; cevap yazılamadı ({kept})")
        if why:     # neden kayıtlı kalsın: 'iletildi' görünmesin
            sw.mark_undeliverable(str(action.payload.get("question_id") or ""), why, paths)
        else:
            sw.mark_delivered(str(action.payload.get("question_id") or ""), paths)
        sw.log_event("stale_answer_closed", paths=paths, id=action.payload.get("question_id"), project=action.name, **({"reason": why} if why else {}))
        return {"ok": True}
    if k == "escalate_routine":
        q = sw.escalate_routine(action.payload.get("question_id") or "", paths)
        if q is None:
            return {"ok": False, "error": "not an open routine question"}
        lead = "Beyin çözemedi: " if q.text.startswith(sw.BLOCKED_TEXT_PREFIX) else ""
        notified = _notify(cfg, f"{_ask_prefix(q.project, cfg.sid)} {lead}{q.text}\n→ {sw.ask_hint(q.id, cfg.sid)}")
        return {"ok": True, "id": q.id, "notified": notified}
    if k == "lesson_ack":             # oturum dersi işledi: yalnız kayıt (geçersiz biçim/bilinmeyen kimlik sessizce düşer)
        ack = sl.parse_ack(str(action.payload.get("text") or ""))
        if ack is None:
            return {"ok": True, "skipped": "bad ack"}
        wrote = sl.mark_done(ack[0], ack[1], ack[2], name, time.time(), paths)
        if wrote:
            sw.log_event("lesson_acked", paths=paths, id=ack[0], status=ack[1], session=name)
        return {"ok": True, "recorded": wrote}
    if k == "idea":
        i = sw.add_idea(action.payload.get("text") or "", source=name, paths=paths)
        return {"ok": True, "id": i.id}
    if k == "set_phase":
        sw.upsert_project(name, paths=paths, phase=action.payload.get("phase"))
        return {"ok": True}
    if k == "keepwarm":               # TTL dolmadan hafif dürtme: tüm koşullar `plan_keepwarm`de denetlendi, burada yalnız gönder
        if not host:
            denied = _target(name, "engine", projects, k, sid=cfg.sid, world=world)
            if denied is not None:
                return denied
        s = _running(name)
        if host or s is None or not is_tmux_backed(s.pid):
            return {"ok": False, "error": "not a local running tmux session"}
        if _box_has_typed_input(s.name):    # 2026-10-29 danisppr: kutudaki gönderilmemiş direktife "ok" eklenip tek mesaj gitti
            sw.log_event("keepwarm_skipped", paths=paths, name=name, reason="input_box_not_empty")
            return {"ok": False, "error": "input box has unsent text"}
        ok = _send(s.name, s.cli, action.payload.get("text") or skw.KEEPWARM_TEXT)
        sw.log_event("keepwarm", paths=paths, name=name, ok=ok, **{k2: action.payload.get(k2) for k2 in ("project", "age_min", "tokens", "n", "text")})
        return {"ok": ok} if ok else {"ok": False, "error": "send failed"}
    if k in ("idle_nudge", "owner_todo_move"):   # owner_todo_move: aynı yol, olay adı ayrı (TODO'daki sahibe bağlı maddeleri TOBEDECIDED'a taşıt)
        # TBD#156: boşta ucli kodcuya TEK satır "devam: <iş>" (koşullar `plan_ucli_idle`de denetlendi)
        if not host:
            denied = _target(name, "engine", projects, k, sid=cfg.sid, world=world)
            if denied is not None:
                return denied
        s = _running(name)
        if host or s is None or not is_tmux_backed(s.pid):
            return {"ok": False, "error": "not a local running tmux session"}
        if _box_has_typed_input(s.name):
            sw.log_event(k + "_skipped", paths=paths, name=name, reason="input_box_not_empty")
            return {"ok": False, "error": "input box has unsent text"}
        ok = _send(s.name, s.cli, sw.one_line(action.payload.get("text") or "devam"))   # ucli çok satırı ayrı tur sayar: TEK satır
        sw.log_event(k, paths=paths, name=name, ok=ok, **{k2: action.payload.get(k2) for k2 in ("project", "idle_secs", "threshold", "n", "next")})
        return {"ok": ok} if ok else {"ok": False, "error": "send failed"}
    if k == "idle_close":             # TBD#156: handover / respawn / stop (mevcut yollar: `_local_handover`, `respawn` -> `_last_launch` cli_opts korunur)
        mode = str(action.payload.get("mode") or "")
        if mode not in ("handover", "respawn", "stop") or host:
            return {"ok": False, "error": "unsupported idle_close"}
        res = _apply(sw.Action(mode, name, action.reason), cfg, projects, world, rt=rt)
        sw.log_event("idle_close", paths=paths, name=name, ok=bool(res.get("ok")), mode=mode,
                     **{k2: action.payload.get(k2) for k2 in ("project", "idle_secs", "marker", "pause", "next")})
        if res.get("ok") and action.payload.get("pause") and action.payload.get("project"):
            sw.upsert_project(str(action.payload["project"]), paths=paths, phase="paused")   # iş yok: proje paused (devir/kapanıştan SONRA)
        if res.get("ok") and action.payload.get("marker") == "turn_failed" and action.payload.get("project"):
            # D1: ardışık başarısız turlar (örn. HTTP 404): kapatıldı; sahibe TEK soru (model/uç nokta/anahtar sorunu olabilir)
            sw.add_question(str(action.payload["project"]),
                            f"{name} oturumu ardışık {action.payload.get('n')} başarısız model turu verdi (HTTP hatası/'This turn failed'); "
                            "dürtmeyi kestim, oturumu kapattım ve projeyi paused yaptım (aksi halde cadence aynı hatalı oturumu yeniden açardı). "
                            "Model/uç nokta/anahtar ayarı mı bozuk? Öneri: ayarı düzelt, sonra `steward set <proje> --phase planned`.", source="engine", paths=paths)
        return res
    if k == "nudge":                  # API hatasında takılan oturuma tek satır "devam" (alt ajan/etkinlik denetimi plan_tick'te yapıldı)
        if host:
            return _remote_nudge(name, host, action, cfg, paths, world or _world(cfg.sid, cfg), rt)
        s = _running(name)
        if s is None or not is_tmux_backed(s.pid):
            return {"ok": False, "error": "not running or not tmux-backed"}
        ok = _send(s.name, s.cli, str(action.payload.get("text") or sw.API_NUDGE_TEXT))
        sw.log_event("done_confirm_asked" if action.payload.get("confirm") else "api_nudge", paths=paths, name=name,
                     n=action.payload.get("n"), reason=action.reason, ok=ok)
        if name == cfg.brain_name and action.payload.get("n") == 1 and not action.payload.get("confirm"):
            # beyin turu API hatasında kaldı: sahip değnekçiyi "kapandı" sanmasın (9 Kas: 65 dk sessiz bekleme); tek bildirim,
            # sonraki dürtmeler sessiz, 3. dürtmeden sonra da düzelmezse `api_giveup` ayrıca bildirir
            tr = cfg.lang != "en"
            _notify(cfg, (f"[{cfg.sid}] beyin API'ye ulaşamıyor (tur yarım kaldı); otomatik 'devam' deneniyor."
                          if tr else f"[{cfg.sid}] steward brain cannot reach the API (tour cut); retrying with 'devam'."))
        return {"ok": ok} if ok else {"ok": False, "error": "send failed"}
    if k in ("api_outage", "api_recovered", "api_giveup"):      # yalnız bildirim + kayıt (oturuma dokunmaz)
        tr = cfg.lang != "en"
        if k == "api_outage":
            names = ", ".join(action.payload.get("names") or [])
            text = (f"API kesintisi: {names} aynı anda hata veriyor. Tek tek uyandırma yok; 10 dk'da bir tek oturumla yoklanır."
                    if tr else f"API outage: {names} are failing at once. No per-session nudges; probing one session every 10 min.")
        elif k == "api_recovered":
            text = (f"API düzeldi ({name} ilerledi); takılı oturumlar 4'lü gruplarla uyandırılıyor."
                    if tr else f"API recovered ({name} progressed); waking stuck sessions in groups of 4.")
        else:
            text = (f"{name}: API hatasında kaldı, {sw.API_NUDGE_MAX} 'devam' işe yaramadı. Bıraktım; sana kalıyor."
                    if tr else f"{name}: stuck on an API error; {sw.API_NUDGE_MAX} nudges did not help. Giving up; over to you.")
        sw.log_event(k, paths=paths, name=name, reason=action.reason)
        return {"ok": True, "notified": _notify(cfg, text)}
    if k == "loop_break":             # L4: yalnız kayıt + tek bildirim (eylem LOOP_PAUSE boyunca uygulanmaz)
        pl = action.payload
        sw.log_event("loop_break", paths=paths, name=name, kind=pl.get("kind"), n=pl.get("n"), reason=pl.get("last_reason"))
        tr = cfg.lang != "en"
        text = (f"[{cfg.sid}] döngü durduruldu: {name} için '{pl.get('kind')}' {pl.get('n')} kez yapıldı, oturumda değişiklik yok. "
                f"{pl.get('pause_min') or int(pl.get('pause_h') or 0) * 60} dk uygulanmayacak (yeni madde gelirse hemen yeniden denenir). Son gerekçe: {pl.get('last_reason')}"
                if tr else f"[{cfg.sid}] loop stopped: '{pl.get('kind')}' on {name} ran {pl.get('n')} times with no change. "
                f"Paused {pl.get('pause_min') or int(pl.get('pause_h') or 0) * 60} min (a new item resumes at once). Last reason: {pl.get('last_reason')}")
        return {"ok": True, "notified": _notify(cfg, text[:600])}
    if k == "ho_halted":              # yalnız kayıt: devir sonrası proje paused/done, yeniden açma/yönerge YOK (oturum açık kalır)
        sw.log_event("ho_halted", paths=paths, name=name, reason=action.reason,
                     phase=str(action.payload.get("phase") or ""), step=str(action.payload.get("step") or ""))
        return {"ok": True}
    if k == "handover_deferred":      # yalnız kayıt (oturuma dokunmaz): eşik devri meşgul/alt ajan yüzünden ertelendi
        sw.log_event("handover_deferred", paths=paths, name=name, reason=action.reason,
                     handover=str(action.payload.get("handover_reason") or ""))
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


def _register_outcomes(recs: List[Dict[str, Any]], paths: Any) -> None:
    """L5: başarılı eylemleri doğrulama kuyruğuna (`state.outcome_pending`) yaz."""
    try:
        with sw.steward_lock(paths):
            st = sw.load_state(paths)
            pend = dict(st.get("outcome_pending") or {})
            for r in recs:
                pend[f"{r['kind']}|{r['name']}|{int(r['at'])}"] = r
            st["outcome_pending"] = pend
            sw.save_state(st, paths)
    except Exception as e:
        diag_log("steward_outcome_register_failed", error=repr(e))


def _check_outcomes(cfg: sw.Config, views: List[sw.SessionView], paths: Any, now: float) -> None:
    """L5: bekleyen doğrulamaları sonuçlandır; `outcome` olayı (changed|none). Açılmayan `start` sahibe bildirilir."""
    try:
        with sw.steward_lock(paths):
            st = sw.load_state(paths)
            pend = st.get("outcome_pending") or {}
            if not pend:
                return
            done, rest = sw.check_outcomes(pend, views, now)
            if not done:
                return
            if rest:
                st["outcome_pending"] = rest
            else:
                st.pop("outcome_pending", None)
            sw.save_state(st, paths)
        for d in done:
            sw.log_event("outcome", paths=paths, **d)
            if d["result"] == "none" and d["kind"] in ("start", "respawn"):
                tr = cfg.lang != "en"
                _notify(cfg, (f"[{cfg.sid}] {d['name']}: '{d['kind']}' başarılı göründü ama {d['secs'] // 60} dk'da oturum açılmadı "
                              "(güven diyaloğu/çökme olabilir)." if tr else
                              f"[{cfg.sid}] {d['name']}: '{d['kind']}' looked ok but no session appeared in {d['secs'] // 60} min."))
    except Exception as e:
        diag_log("steward_outcome_check_failed", error=repr(e))


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
                          session_name=action.name, cfg=cfg, host=host or None, rt=rt, actor="engine")
    if res.get("ok"):
        _mark_after_send(mark, cfg.sid, f"job:{stage}", f"{svc}#{jid}")      # mesaj gitti: kilit zaman aşımı yinelenmeye yol açmasın
        sw.log_event("job_delivered", paths=paths, service=svc, id=jid, project=p.name, stage=stage, session=action.name)
    elif sj.mark_attempt(jid, svc, paths) >= sj.DELIVER_MAX_ATTEMPTS:
        sw.log_event("job_undeliverable", paths=paths, service=svc, id=jid, project=p.name, error=str(res.get("error") or ""))
    return res


def _deliver_lesson(action: sw.Action, cfg: sw.Config, projects: Dict[str, sw.Project], host: Optional[str] = None,
                    rt: Optional[_RemoteTick] = None) -> Dict[str, Any]:
    """`deliver_lesson`: reviewer'ın ucli dersleri projenin ÇALIŞAN oturumuna `_give_directive` ile (`start_if_stopped=False`)
    iletilir. Başarıda satır özetleri `lessons_sent`e yazılır (aynı ders iki kez gitmez), başarısızlıkta sayaç artar."""
    paths = sw.paths_for(cfg.sid)
    hashes = [str(h) for h in (action.payload.get("hashes") or [])]
    lines = [str(x) for x in (action.payload.get("lines") or [])]
    p = projects.get(str(action.payload.get("project") or ""))
    if p is None or not hashes or not lines:
        return {"ok": False, "error": "not a steward project"}
    mark = lambda: sl.mark_sent(hashes, paths)   # noqa: E731
    ident = ",".join(hashes)
    if _already_sent(mark, cfg.sid, "lesson", ident):
        return {"ok": True, "skipped": "already sent"}
    # Eylem planlandığı anki durumdan çıktı; araya giren başka bir tick/yol aynı dersleri göndermiş olabilir: güncel
    # `lessons_sent`i yeniden oku, hepsi gitmişse gönderme, kısmen gitmişse yalnız kalanları gönder.
    try:
        sent_now = set(sw.load_state(paths).get("lessons_sent") or [])
    except Exception:
        sent_now = set()
    keep = [(h, ln) for h, ln in zip(hashes, lines) if h not in sent_now]
    if not keep:
        return {"ok": True, "skipped": "already sent"}
    if len(keep) != len(hashes):
        hashes, lines = [h for h, _ in keep], [ln for _, ln in keep]
        ident = ",".join(hashes)
        mark = lambda: sl.mark_sent(hashes, paths)   # noqa: E731
    res = _give_directive(p, sl.build_lesson_message(lines, cfg.lang, ids=hashes), start_if_stopped=False, reason="lesson",
                          session_name=action.name, cfg=cfg, host=host or None, rt=rt, actor="engine")
    if res.get("ok"):
        _mark_after_send(mark, cfg.sid, "lesson", ident)
        sw.log_event("lesson_delivered", paths=paths, project=p.name, session=action.name, n=len(hashes))
    else:
        try:
            sl.mark_failed(hashes, paths)
        except sw.LockTimeout as e:      # sayaç yazılamadı: iletim sonucu (res) yine döner, tick düşmesin
            sw.log_event("delivery_unrecorded", paths=paths, what="lesson_fail", id=ident, error=str(e))
    return res


def _deliver_findings(action: sw.Action, cfg: sw.Config, projects: Dict[str, sw.Project], host: Optional[str] = None,
                      rt: Optional[_RemoteTick] = None) -> Dict[str, Any]:
    """`deliver_findings`: onaylı review bulgularını projenin ÇALIŞAN oturumuna `_give_directive` ile (`start_if_stopped=False`)
    iletir. Başarıda bulgu başına `advance_sent` işaretlenir (iki kez/sıkça gitmez). Commit/push yapmaz."""
    paths = sw.paths_for(cfg.sid)
    rows = [r for r in (action.payload.get("rows") or []) if isinstance(r, dict) and r.get("id")]
    p = projects.get(str(action.payload.get("project") or ""))
    if p is None or not rows:
        return {"ok": False, "error": "not a steward project"}
    fids = [str(r["id"]) for r in rows]
    mark = lambda: sa.mark_sent(fids, time.time(), paths)   # noqa: E731
    ident = ",".join(fids)
    if _already_sent(mark, cfg.sid, "advance", ident):
        return {"ok": True, "skipped": "already sent"}
    res = _give_directive(p, sa.build_advance_message(rows, cfg.lang), start_if_stopped=False, reason="advance",
                          session_name=action.name, cfg=cfg, host=host or None, rt=rt, actor="engine")
    if res.get("ok"):
        _mark_after_send(mark, cfg.sid, "advance", ident)
        sw.log_event("findings_advanced", paths=paths, project=p.name, session=action.name, n=len(fids), ids=fids)
    return res


def _doc_path(cwd: str, fname: str) -> str:
    """Proje klasöründeki `fname` yolu; yoksa (git worktree: TODO/TBD ana kopyada) ana worktree klasöründeki. Gerçek yol
    ilgili kökün altında kalmalı; bulunamazsa ""."""
    if not cwd:
        return ""
    roots = [cwd]
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        if out.endswith("/.git"):
            roots.append(out[:-5])
    except (OSError, subprocess.SubprocessError):
        pass
    for root in roots:
        real, rroot = os.path.realpath(os.path.join(root, fname)), os.path.realpath(root)
        if real.startswith(rroot + os.sep) and os.path.isfile(real):
            return real
    return ""


def _scan_todo(projects: Dict[str, sw.Project], proj: str) -> Optional[Tuple[int, int]]:
    """Projenin YEREL TODO.md'si: (açık iş sayısı, sahibe bağlı etiketli açık satır sayısı). Sahibe bağlı satırlar
    (`OWNER_WAIT_LINE_RE`: SAHİPTE, (sahip), DIŞ GİRDİ, "sahip kararı bekliyor"...) açık iş SAYILMAZ. Uzak proje, klasörü bilinmeyen,
    okunamayan ya da 2 MB üstü dosya = None."""
    try:
        p = projects.get(proj)
        if p is None or p.host:
            return None
        cwd = _cwd_resolver()(proj)
        real = _doc_path(cwd, "TODO.md")
        if not real or os.path.getsize(real) > sa.TODO_MAX_BYTES:
            return None
        n_open = n_owner = 0
        with open(real, encoding="utf-8", errors="replace") as f:
            for ln in f:
                if not re.match(r"\s*[-*]\s*\[ \]", ln):
                    continue
                if sw.OWNER_TODO_LINE_RE.search(ln):
                    n_owner += 1
                if not sw.OWNER_WAIT_LINE_RE.search(ln):
                    n_open += 1
        return n_open, n_owner
    except OSError:
        return None


def _open_work_of(projects: Dict[str, sw.Project]) -> Callable[[str], Optional[int]]:
    """`plan_tick` için: projenin YEREL TODO.md'sindeki açık `- [ ]` satırı sayısı (sahibe bağlı etiketliler hariç; `_scan_todo`).
    None = bilinmiyor (ön-kontrol atlanır, teyit kanıta kalır). Yalnız teyit gelince çağrılır."""
    def count(proj: str) -> Optional[int]:
        r = _scan_todo(projects, proj)
        return None if r is None else r[0]
    return count


def _owner_todo_of(projects: Dict[str, sw.Project]) -> Callable[[str], Optional[int]]:
    """Projenin TODO.md'sindeki sahibe bağlı etiketli açık satır sayısı (`owner_in_todo`); uzak/bilinmiyor = None."""
    def count(proj: str) -> Optional[int]:
        r = _scan_todo(projects, proj)
        return None if r is None else r[1]
    return count


def _pid_alive(pid: int) -> Optional[bool]:
    """PID yaşıyor mu (zombi = ölü). Yetki yok (başka kullanıcı) = yaşıyor sayılır; okunamayan = None."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as f:
            return f.read().rpartition(")")[2].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def _gate_ahead(cwd: str) -> Optional[int]:
    """Projenin geçerli dalının `main`den ileri commit sayısı (`git rev-list --count main..HEAD`); main/git yoksa None."""
    try:
        r = subprocess.run(["git", "-C", cwd, "rev-list", "--count", "main..HEAD"], capture_output=True, text=True, timeout=10)
        return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _claim_check_of(projects: Dict[str, sw.Project]) -> Callable[[str], List[str]]:
    """`plan_tick` için: projenin `notes`undaki doğrulanabilir iddiaları (PID / kapıda bekliyor) süreç ve git ile karşılaştırır.
    Uzak proje = boş (yerel süreç/depo hakkında bir şey bilinmez). Hata = boş (tutarsızlık uydurma)."""
    def check(proj: str) -> List[str]:
        try:
            p = projects.get(proj)
            if p is None or p.host or not (p.notes or "").strip():
                return []
            if not sw.note_claims(p.notes)["pids"] and not sw.note_claims(p.notes)["gate"]:
                return []
            cwd = _cwd_resolver()(proj)
            return sw.check_note_claims(p.notes, _pid_alive, lambda: _gate_ahead(cwd) if cwd else None)
        except Exception as e:      # doğrulama beyin turunu hiçbir zaman engellemez
            diag_log("claim_check_failed", project=proj, error=repr(e))
            return []
    return check


def _open_tbd_of(projects: Dict[str, sw.Project]) -> Callable[[str], Optional[int]]:
    """`plan_tick` için: projenin YEREL TOBEDECIDED.md'sindeki açık karar sayısı (`sw.count_open_tbd`). Uzak/okunamayan = None."""
    def count(proj: str) -> Optional[int]:
        try:
            p = projects.get(proj)
            if p is None or p.host:
                return None
            cwd = _cwd_resolver()(proj)
            real = _doc_path(cwd, "TOBEDECIDED.md")
            if not real or os.path.getsize(real) > sa.TODO_MAX_BYTES:
                return None
            with open(real, encoding="utf-8", errors="replace") as f:
                return sw.count_open_tbd(f.read())
        except OSError:
            return None
    return count


def _advance_candidates(cfg: sw.Config) -> List[Dict[str, Any]]:
    """Reviewer kimliklerinin `exported` bulguları + TODO durumu (yalnız `advance_findings=on` kimlikte). Hata = boş."""
    if not cfg.advance_findings:
        return []
    try:
        from .. import review as rv
        data = [rv.load_findings(sw.paths_for(sid)) for sid in sorted(sw.reviewer_ids())]
        cache: List[Callable[[str], str]] = []

        def cwd_of(name: str) -> str:      # filo anlık görüntüsü yalnız gerçekten bir `exported` bulgu varsa ve bir kez alınır
            if not cache:
                cache.append(_cwd_resolver())
            return cache[0](name)
        todo_cache: Dict[str, Optional[str]] = {}

        def remote_todo_of(proj: str, fid: str) -> str:      # uzak TODO.md bir kez okunur; okunamazsa "" (tek iletim kuralı)
            if proj not in todo_cache:
                todo_cache[proj] = None
                try:
                    host = _name_host(proj)
                    real, cwd = _remote_ref(host, proj) if host and _remote_files_gate(host, cfg.sid) else ("", "")
                    if cwd:
                        todo_cache[proj] = _remote_read_full(host, real or proj, cwd.rstrip("/") + "/TODO.md",
                                                             REMOTE_READ_BUDGET_SECONDS)
                except Exception:
                    todo_cache[proj] = None
            text = todo_cache[proj]
            return sa.todo_status_text(text, fid) if text is not None else ""
        return sa.candidates(data, cwd_of, _name_host, remote_todo_of)
    except Exception:
        return []


def _lessons(cfg: sw.Config) -> List[Tuple[str, str]]:
    """Tüm reviewer kimliklerinin `ucli-lessons.md` satırları (proje bu kimliğin değilse planlayıcı zaten bir şey yapmaz)."""
    if not sl.target_project(cfg.lessons_project):
        return []
    try:
        return sl.read_lessons(sw.paths_for(sid).root for sid in sorted(sw.reviewer_ids()))
    except Exception:
        return []


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


# Ana oturum üst kademe denetimi (TODO 1233/5): (kimlik, oturum adı) -> {model, effort, at, sent}. Süreç içi (fable_rule
# kalıbı); süreç yeniden başlarsa en çok bir yinelenen hatırlatma. Aynı model/effort için bir kez loglanır + bir kez
# hatırlatılır; oturum Sonnet medium'a dönünce kayıt düşer (yeniden yükselirse yine uyarılır).
_UPPER_MAIN_WARNED: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _audit_upper_main(cfg: sw.Config, views: List[sw.SessionView], projects: Dict[str, sw.Project], world: Any,
                      paths: Any, rt: Optional[_RemoteTick] = None) -> None:
    """Proje ANA oturumu fiilen (canlı model/effort) Sonnet medium üstündeyse `upper_main` olayı + oturuma HATIRLATMA
    direktifi (`_give_directive`, `start_if_stopped=False`, model/effort verilmez: hiçbir şey zorlanmaz/değiştirilmez).
    Gönderim kapıları direktif yoluyla aynı: observe kipinde yalnız log; meşgul/alt ajanlı/az önce direktif almış oturum
    beklenir (sonraki tick); uzak oturuma yalnız `remote_actions` açıkken. Başarısız gönderim sonraki tick'te yeniden denenir."""
    if not cfg.upper_main_warn:
        return
    now = time.time()
    flagged = {v.name: v for v in sw.upper_main_views(views, projects, cfg, world)}
    for key in [k for k in _UPPER_MAIN_WARNED if k[0] == cfg.sid and k[1] not in flagged]:
        _UPPER_MAIN_WARNED.pop(key, None)       # kurala döndü ya da kapandı: yeniden yükselirse yeniden uyarılır
    if not flagged:
        return
    lda: Dict[str, Any] = {}
    try:
        lda = sw.load_state(paths).get("last_directive_at") or {}
    except Exception:
        lda = {}
    for name, v in flagged.items():
        key = (cfg.sid, name)
        ent = _UPPER_MAIN_WARNED.get(key)
        if ent is None or (ent["model"], ent["effort"]) != (v.live_model, v.live_effort):
            ent = {"model": v.live_model, "effort": v.live_effort, "at": now, "sent": False}
            _UPPER_MAIN_WARNED[key] = ent
            sw.log_event("upper_main", paths=paths, name=name, project=v.project, model=v.live_model,
                         effort=v.live_effort, **({"host": v.host} if sw.normalize_host(v.host) else {}))
        if ent["sent"] or cfg.mode == "observe":
            continue
        host = sw.normalize_host(v.host)
        if host and not cfg.remote_actions:
            continue
        if v.subagent_active or sw.directive_defer_reason(v.busy, float(lda.get(name) or 0.0), now):
            continue
        p = projects.get(name)
        if p is None:
            continue
        res = _give_directive(p, sw.upper_main_text(name, v.live_model, v.live_effort, cfg.lang),
                              start_if_stopped=False, reason="upper_main", session_name=name, cfg=cfg,
                              host=host or None, rt=rt, actor="engine")
        if isinstance(res, dict) and res.get("ok"):
            ent["sent"] = True
        else:
            diag_log("steward_upper_main_send_failed", sid=cfg.sid, name=name,
                     error=str((res or {}).get("error") if isinstance(res, dict) else res))


_JOURNAL_KINDS = ("ask_user", "idea", "set_phase", "close_stale_answer")   # kaydı sessizce kaybolan tür: tetikleyici (yanıt özeti) tick'te tüketilir


def _journal_id(a: sw.Action) -> str:
    raw = json.dumps([a.kind, a.name, a.reason, a.payload], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _journal_entries(actions: List[sw.Action], now: float) -> List[Dict[str, Any]]:
    """Kayıt eylemlerinin 'bekliyor' girdileri (state ile AYNI yazımda saklanır; codex R-2: plan_tick sonucu eylemlerden önce
    yazılıyor, çökme penceresinde işaret tüketilip eylem kayboluyordu)."""
    return [{"id": _journal_id(a), "kind": a.kind, "name": a.name, "reason": a.reason, "payload": a.payload, "at": now}
            for a in actions if a.kind in _JOURNAL_KINDS]


def _journal_done(paths: Any, jid: str) -> None:
    """Eylem uygulandı ('tamamlandı'): girdiyi sil. Kilit alınamazsa girdi kalır ve sonraki tick yeniden dener (kayıt eylemleri
    yinelenmeye dayanıklı: aynı açık soru birleşir, set_phase idempotent, fikir kopyası atlanır)."""
    try:
        with sw.steward_lock(paths):
            state = sw.load_state(paths)
            left = [e for e in (state.get("act_journal") or []) if e.get("id") != jid]
            if left:
                state["act_journal"] = left
            else:
                state.pop("act_journal", None)
            sw.save_state(state, paths)
    except sw.LockTimeout:
        pass


def _replay_journal(cfg: sw.Config, projects: Dict[str, sw.Project], world: Any, paths: Any, sid: str) -> int:
    """Önceki tick eylemleri bitirmeden kesildiyse ('bekliyor' girdileri kaldı) onları bir kez uygula. Dönen: uygulanan sayısı."""
    entries = [e for e in (sw.load_state(paths).get("act_journal") or []) if isinstance(e, dict) and e.get("kind") in _JOURNAL_KINDS]
    n = 0
    for e in entries:
        a = sw.Action(str(e["kind"]), str(e.get("name") or ""), str(e.get("reason") or ""), dict(e.get("payload") or {}))
        try:
            if a.kind == "idea" and any(i.text == str(a.payload.get("text") or "").strip()[:2000] and i.source == a.name
                                        for i in sw.load_ideas(paths)):
                res: Dict[str, Any] = {"ok": True, "skipped": "duplicate"}
            else:
                res = _apply(a, cfg, projects, world)
        except Exception as ex:
            res = {"ok": False, "error": repr(ex)}
            diag_log("steward_action_crashed", sid=sid, kind=a.kind, name=a.name, error=repr(ex))
        sw.log_event("action_replayed", paths=paths, kind=a.kind, name=a.name, ok=bool(res.get("ok")))
        _journal_done(paths, str(e.get("id")))
        n += 1
    return n


def tick_once(trigger: str = "timer", sid: str = "default", *, starts_left: Optional[int] = None,
              cards: bool = True, index: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Bir tick; tarama önbelleği kapsamında (`_scan_scope`) `_tick_once_inner`i çalıştırır."""
    with _scan_scope():
        return _tick_once_inner(trigger, sid, starts_left=starts_left, cards=cards, index=index)


def _tick_once_inner(trigger: str = "timer", sid: str = "default", *, starts_left: Optional[int] = None,
              cards: bool = True, index: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """`sid` kimliği için bir tick: görünümleri topla → kararlar (`plan_tick(world=...)`) → uygula → state kaydet.
    Elle (`/api/steward/tick`, `py/cops steward tick`) de çağrılır; döngü kapalıyken bile çalışır (kullanıcı bilerek
    istedi). Kilit KİMLİK BAŞINA (`ctx.lock`): A'nın tick'i B'nin elle eylemini bekletmez. Okuma/yazma yalnız
    `paths_for(sid)` yollarında. `starts_left`: döngü turunun kalan makine geneli başlatma hakkı (None = sınırsız,
    elle tick). `cards=False`: kart adımını çağıran yapar (döngü turu tek kart işi koşturur)."""
    ctx = _ctx(sid)
    with ctx.lock:
        cfg = steward_config(sid)
        if quota_blocking() and not cfg.drain:
            cfg = dataclasses.replace(cfg, drain=True)      # kota bekçisi: yeni iş alınmaz (ayarı değiştirmez, yalnız bu tick)
        if sw.panic_active() and cfg.mode != "observe":
            cfg = dataclasses.replace(cfg, mode="observe", drain=True)   # ACİL DURDURMA: hiçbir oturuma dokunma, yeni iş alma (yalnız kayıt)
        paths = ctx.paths
        t0 = time.time()
        applied: List[Dict[str, Any]] = []
        dry_applied: List[Dict[str, Any]] = []
        verify: List[Dict[str, Any]] = []
        started = 0
        error = ""
        try:
            projects = sw.load_projects(paths)
            idx = index if index is not None else _ownership_index()
            world = _world(sid, cfg, starts_left, idx)
            # Uzak tazelik anlık görüntüsü tick başında BİR KEZ: `unavailable`, görünümler ve eylem ön denetimleri aynı
            # görüntüden (iki ayrı önbellek okuması arasında host düşerse proje "çalışmıyor" sanılıp başlatılmasın).
            rt = _remote_snapshot(set(world.hosts.values()), t0)
            for h_up in _probe_stale_hosts(rt):
                sw.log_event("remote_probe_recovered", paths=paths, host=h_up)
                if h_up in _RECOVERED_DOWN:
                    _RECOVERED_DOWN.discard(h_up)
                    sw.log_event("remote_unreachable", paths=paths, host=h_up, state="up", via="probe")
            world = _with_availability(world, cfg, t0, rt)
            # Uzak proje yoksa çağrı biçimi eskisiyle AYNI (altın testler `_collect_views`/`_apply`ı bu biçimle değiştirir).
            rkw: Dict[str, Any] = {"rt": rt} if world.hosts else {}
            _note_conflicts(ctx, idx, set(projects), t0)
            views = _collect_views(cfg, **rkw)
            world = _maintain_owned(views, projects, world, paths, sid, t0)     # L2: izlenen oturum kaydı (+ tek seferlik tohum)
            _check_outcomes(cfg, views, paths, t0)        # L5: önceki tick'lerin eylemleri gerçekten sonuç verdi mi
            if sw.load_state(paths).get("act_journal"):
                _replay_journal(cfg, projects, world, paths, sid)      # önceki tick yarıda kaldı: bekleyen kayıt eylemleri
            with sw.steward_lock(paths):     # state RMW atomik (CLI süreci de aynı dosyaya yazar)
                prev_state = sw.load_state(paths)
                actions, new_state = sw.plan_tick(views, projects, prev_state, cfg, t0,
                                                  sw.load_questions(paths), sw.load_ideas(paths), world=world,
                                                  open_work=_open_work_of(projects), open_tbd=_open_tbd_of(projects),
                                                  claim_check=_claim_check_of(projects))
                if new_state.get("start_blocked") != (prev_state.get("start_blocked") if "start_blocked" in new_state else None):
                    sw.log_event("start_blocked", paths=paths, **new_state["start_blocked"])   # değişince bir kez
                job_actions, new_state = sj.plan_job_deliveries(views, projects, sj.load_jobs(paths), actions, new_state, t0, world)
                actions = actions + job_actions     # iş sonucu iletimi (varaka kuyruğu): `plan_tick`e DOKUNMAZ, aynı observe/_target yolundan
                lesson_actions, planned_state = sl.plan_lesson_deliveries(views, projects, _lessons(cfg), new_state, t0,
                                                                          sl.target_project(cfg.lessons_project), actions, world)
                if cfg.mode != "observe":   # observe durumu DEĞİŞTİRMEZ (direktif zamanı işaretlenmez): her tick would: üretebilir
                    new_state = planned_state
                actions = actions + lesson_actions  # reviewer'ın ucli dersleri -> ucli projesinin oturumu (iş iletimiyle aynı yol)
                kw_actions, kw_state = skw.plan_keepwarm(views, projects, new_state, cfg, t0, actions, world,
                                                              open_work=_open_work_of(projects),
                                                              owner_projects={q.project for q in sw.open_questions(paths=paths) if not q.routine})
                if kw_actions:
                    new_state = kw_state       # keepwarm kaydı (dry'da da): aynı boşta dönemi için tekrar yazılmaz
                    chain_actions = [a for a in kw_actions if a.kind == "idle_close"]      # zincir doldu: devir + kapat + paused
                    kw_actions = [a for a in kw_actions if a.kind != "idle_close"]
                    for a in chain_actions:
                        if cfg.keepwarm_chain_close == "dry":
                            sw.log_event("would:idle_close", paths=paths, name=a.name,
                                         **{k: a.payload.get(k) for k in ("project", "idle_secs", "threshold", "n", "mode", "marker", "pause_reason")})
                        else:
                            actions = actions + [a]
                    if cfg.keepwarm == "dry":
                        for a in kw_actions:   # YALNIZ ölçüm: oturuma dokunmaz
                            sw.log_event("would:keepwarm", paths=paths, name=a.name, **{k: a.payload.get(k) for k in ("project", "age_min", "tokens", "n", "text")})
                    else:
                        actions = actions + kw_actions   # önbellek canlı tutma dürtmesi (observe kipinde OBSERVE_SKIPPED ile kuru kalır)
                adv_actions, planned_state = sa.plan_advance_deliveries(views, projects, _advance_candidates(cfg), new_state, t0,
                                                                        actions, world)
                if cfg.mode != "observe":
                    new_state = planned_state
                actions = actions + adv_actions     # ilerletme (advance_findings=on): onaylı review bulguları -> kendi projesinin oturumu
                idle_actions, new_state = sw.plan_ucli_idle(views, projects, new_state, cfg, t0, actions, world,
                                                            open_work=_open_work_of(projects))
                if cfg.ucli_idle == "dry":
                    for a in idle_actions:          # YALNIZ ölçüm (act kipinde de): oturuma dokunmaz
                        sw.log_event("would:" + a.kind, paths=paths, name=a.name,
                                     **{k: a.payload.get(k) for k in ("project", "idle_secs", "threshold", "n", "next", "mode", "marker")})
                else:
                    actions = actions + idle_actions    # TBD#156: boşta ucli kodcu (dürtme / kapat+devir); observe'da OBSERVE_SKIPPED ile `would:`
                cl_actions, new_state = sw.plan_claude_idle(views, projects, new_state, cfg, t0, actions, world,
                                                            open_work=_open_work_of(projects), owner_todo=_owner_todo_of(projects))
                if cfg.claude_idle == "dry":
                    for a in cl_actions:            # YALNIZ ölçüm: oturuma dokunmaz
                        sw.log_event("would:" + a.kind, paths=paths, name=a.name,
                                     **{k: a.payload.get(k) for k in ("project", "idle_secs", "threshold", "n", "next", "cli")})
                else:
                    actions = actions + cl_actions  # Claude Code oturumu boşta + sıradaki iş: tek satır `devam:`
                actions, dry, new_state = sw.observe_filter(actions, cfg.mode, new_state, t0)
                actions, new_state = sw.loop_guard(actions, views, new_state, t0)     # L4: hedefte değişiklik yokken tekrar eden eylem durur
                try:        # "neden ilerlemiyor" (panel proje satırı): motorun bu tick'teki kararlarıyla aynı koşullar; hata tick'i düşürmez
                    ctx.idle_why = {"at": t0, "by": sw.explain_idle_all(views, projects, new_state, cfg, t0, sw.load_questions(paths), actions,
                                                                         world, open_work=_open_work_of(projects), owner_todo=_owner_todo_of(projects))}
                except Exception as e_why:
                    diag_log("steward_explain_idle_failed", sid=sid, error=repr(e_why))
                journal = _journal_entries(actions, t0)
                if journal:
                    new_state["act_journal"] = list(new_state.get("act_journal") or []) + journal   # 'bekliyor': state ile aynı yazım
                sw.save_state(new_state, paths)
            for a in dry:
                host = _locate(a.name, projects, world)[0] if a.kind in _SESSION_KINDS else ""
                _remember_dry(a, ctx, host=host)
                dry_applied.append(dict({"kind": a.kind, "name": a.name, "reason": a.reason, "dry": True},
                                        **({"host": host} if host else {})))
            for a in actions:
                try:
                    res = _apply(a, cfg, projects, world, **rkw)
                except Exception as e:  # tek eylem tick'i düşürmesin
                    res = {"ok": False, "error": repr(e)}
                    diag_log("steward_action_crashed", sid=sid, kind=a.kind, name=a.name, error=repr(e))
                if a.kind == "start" and not (isinstance(res, dict) and res.get("started") is False):
                    started += 1      # deneme sayılır (başarısız açılış da bir spawn dalgası olabilir); VAR OLAN oturuma yönlenen start (started=False) sayılmaz
                if a.kind in _JOURNAL_KINDS:
                    _journal_done(paths, _journal_id(a))       # 'tamamlandı' (süreç ölmedi: istisna olsa da yeniden denenmez, hata her tick'te tekrarlanmasın)
                if isinstance(res, dict) and res.get("code") == "destructive_budget":
                    _defer_destructive(a, paths, world)     # host'un bu tick'lik yıkıcı hakkı doldu: sonraki tick'e
                try:
                    _remember(a, res, ctx)
                except Exception as e:      # kayıt hatası kalan eylemleri atlatmasın
                    diag_log("steward_remember_failed", sid=sid, kind=a.kind, name=a.name, error=repr(e))
                applied.append({"kind": a.kind, "name": a.name, "reason": a.reason, "ok": bool(res.get("ok")),
                                "detail": res.get("error") or ""})
                if a.kind in sw.VERIFY_KINDS and isinstance(res, dict) and res.get("ok") and res.get("started") is not False:
                    verify.append(sw.outcome_baseline(a.kind, a.name, views, t0))
                if res.get("host"):
                    applied[-1]["host"] = res["host"]
            if verify:
                _register_outcomes(verify, paths)
            if cfg.enabled:
                try:      # denetim tick'i düşürmesin
                    _audit_upper_main(cfg, views, projects, world, paths, rt)
                except Exception as e:
                    diag_log("steward_upper_main_crashed", sid=sid, error=repr(e))
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
            try:
                maybe_dry_ask(cfg, t0)
            except Exception as e:
                diag_log("steward_dry_ask_crashed", error=repr(e))
            try:
                maybe_pending_digest(cfg, t0)
            except Exception as e:
                diag_log("steward_pending_digest_crashed", error=repr(e))
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

def shutdown_start(sid: str = "default", *, stop_loop: bool = True, modes: Optional[Dict[str, str]] = None,
                   only: Optional[List[str]] = None) -> Dict[str, Any]:
    """Kapatmayı başlat: döngüyü kapat (yeni iş/direktif/açılış olmasın) ve `state["shutdown"]` yaz. Adımları döngü her
    tick'te `shutdown_tick` ile ilerletir (kapalı kimlikte de çalışır). Zaten sürüyorsa yeniden başlatmaz."""
    from ..settings import save_settings
    ctx = _ctx(sid)
    with ctx.lock, sw.steward_lock(ctx.paths):
        state = sw.load_state(ctx.paths)
        if state.get("shutdown") and not state["shutdown"].get("done"):
            return {"ok": True, "already": True, "shutdown": state["shutdown"]}
        state["shutdown"] = {"started": time.time(), "items": {}}
        keep = {str(n): "keep" for n, m in (modes or {}).items() if m == "keep"}     # yalnız "keep" anlamlı; gerisi "stop"
        if keep:
            state["shutdown"]["modes"] = keep
        if only:
            # Kısmi kapatma: döngü AÇIK kalır, diğer projeler sürer; seçilen projeler `paused` (yeni iş/başlatma/teslim yok).
            projs = sw.load_projects(ctx.paths)
            bad = [n for n in only if n not in projs]
            if bad:
                state.pop("shutdown", None)
                return {"ok": False, "error": f"unknown project(s): {', '.join(bad)}"}
            state["shutdown"]["only"] = sorted(only)
            state["shutdown"]["prev_phase"] = {n: projs[n].phase for n in only}
            stop_loop = False
        sw.save_state(state, ctx.paths)
    for n in (only or []):
        sw.upsert_project(n, paths=ctx.paths, phase="paused")
    if stop_loop:
        save_settings({"steward": {"enabled": "off"}} if sid == "default" else {"stewards": {sid: {"enabled": "off"}}})
    sw.log_event("shutdown_start", paths=ctx.paths)
    return {"ok": True, "started": True}


_SHELL_COMMS = {"bash", "sh", "zsh", "dash"}


def bg_shell_running(pid: int) -> bool:
    """claude sürecinin DOĞRUDAN çocuğu olan, Bash aracının başlattığı bir kabuk (`bash -c source …/shell-snapshots/…`) var mı:
    arka planda süren komut (nohup/`run_in_background`/uzun betik). Boştaki claude'un böyle çocuğu yoktur; MCP sunucuları doğrudan
    kabuk değildir. Kapatma bu oturumu "iş bitti" saymaz (yoksa oturum durunca iş de ölür, baştan başlar). Okunamazsa False."""
    try:
        for c in psutil.Process(pid).children():
            try:
                if c.name() in _SHELL_COMMS and any("shell-snapshots" in a for a in c.cmdline()):
                    return True
            except (psutil.Error, OSError):
                continue
    except (psutil.Error, OSError, ValueError):
        pass
    return False


def _shutdown_blockers(views: List[sw.SessionView], projects: Dict[str, sw.Project], world: sw.World,
                       paths: Any) -> Dict[str, str]:
    """Kapatmada "iş bitti" sayılmaması gereken oturumlar: projesinin AÇIK (bitmemiş) varaka işi var. Sessizlik tek başına
    yetmez: oturum işin sonucunu bekliyor olabilir (2026-10-21'de 3 oturum bu yüzden "güm diye" kapandı)."""
    open_by_project: Dict[str, int] = {}
    try:
        for j in sj.load_jobs(paths):
            if sj.is_open(j):
                open_by_project[str(j.get("project") or "")] = open_by_project.get(str(j.get("project") or ""), 0) + 1
    except Exception as e:      # bozuk jobs.json yalnız varaka denetimini düşürür; arka-plan-kabuk denetimi sürer
        diag_log("steward_shutdown_blockers_jobs_failed", error=repr(e))
        open_by_project = {}
    out: Dict[str, str] = {}
    try:
        pids = {s.name: s.pid for s in find_sessions(measure_cpu=False)}     # yalnız YEREL oturumlar (uzakta süreç ağacı okunamaz)
    except Exception:
        pids = {}
    for v in views:
        if not v.running:
            continue
        p = _project_for_session(v.name, projects, world)
        if p is not None and open_by_project.get(p.name):
            out[v.name] = f"open varaka job ({open_by_project[p.name]})"
        elif v.host == LOCAL_HOST_NAME and v.name in pids and bg_shell_running(pids[v.name]):
            out[v.name] = "background shell command running"
    return out


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
        if cfg.enabled and not sd0.get("only"):    # kapatma başlayınca döngü kapatılmıştı; yeniden açılmışsa (`steward up`) kapatma İPTAL
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
        actions, sd, done = sw.plan_shutdown(vs, projects, sd0, cfg, now, world=world,
                                             blockers=_shutdown_blockers(vs, projects, world, paths))
        for a in actions:
            try:
                res = _apply(a, cfg, projects, world)
            except Exception as e:
                res = {"ok": False, "error": repr(e)}
                diag_log("steward_action_crashed", sid=sid, kind=a.kind, name=a.name, error=repr(e))
            _remember(a, res, ctx)
            it = (sd.get("items") or {}).get(a.name)
            if it is not None and sw.shutdown_note_result(it, a.kind, res, now):
                done = False                           # eylem başarısız: adım bir sonraki tick'te yeniden denenir
        if done:
            sd["done"] = now
            if sd.get("only"):      # kısmi kapatma fazı geri YÜKLEMEZ (sahip kararı 2026-10-29): açılmayı unutmasın diye uyar
                pj = sw.load_projects(paths)
                sd["left_paused"] = [n for n in sd["only"] if n in pj and pj[n].phase == "paused"]
        with sw.steward_lock(paths):
            state = sw.load_state(paths)
            state["shutdown"] = sd
            sw.save_state(state, paths)
        if done:
            sw.log_event("shutdown_done", paths=paths, items={n: i["stage"] for n, i in sd["items"].items()},
                         **({"left_paused": sd["left_paused"],
                             "hint": "paused kaldı; açmak için: py/cops steward set <ad> --phase planned (ya da panel)"}
                            if sd.get("left_paused") else {}))
        web_ws.notify_status_changed()
        return {"ok": True, "done": done, "items": {n: i["stage"] for n, i in sd["items"].items()}}


def http_shutdown(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    if data.get("actor") == "brain":
        return {"ok": False, "error": "brain cannot shut the steward down"}
    if data.get("status"):
        sd = sw.load_state(sid).get("shutdown") or {}
        return {"ok": True, "shutdown": sd, "items": {n: i.get("stage") for n, i in (sd.get("items") or {}).items()},
                "done": bool(sd.get("done"))}
    raw = data.get("modes")
    only = [str(n).strip() for n in (data.get("only") or []) if str(n).strip()]
    return shutdown_start(sid, modes=raw if isinstance(raw, dict) else None, only=only or None)


# ── kota bekçisi (TBD#116) ───────────────────────────────────────────────────────────────────────────────────────────
# Claude planının haftalık kullanımını `claude -p /usage` ile (yerel komut, model turu yok) okur; `steward_quota.decide`
# kararına göre: drain = yeni iş alınmaz (çalışan iş sürer), stop = tüm kimlikler kontrollü kapatılır (`--keep`).
# Kapatma KENDİLİĞİNDEN geri açılmaz (`py/cops steward up`): yanlış okuma tüm sistemi sürekli açıp kapatmasın.
_QUOTA: Dict[str, Any] = {"at": 0.0, "busy": False, "usage": None, "decision": None, "stopped": False, "level": 0}
_QUOTA_LOCK = threading.Lock()
QUOTA_FILE = os.path.join(CLAUDEOPS_DIR, "steward", "quota.json")


def quota_config() -> Dict[str, Any]:
    c = load_settings().get("steward_quota") or {}
    return c if isinstance(c, dict) else {}


def quota_read_usage() -> Optional["sq.Usage"]:
    """`claude -p /usage` çıktısı -> Usage; okunamazsa None (karar değişmez). CLAUDE* ortamı süzülür (iç içe oturum sızıntısı)."""
    exe = shutil.which("claude")
    if not exe:
        return None
    cwd = os.path.join(CLAUDEOPS_DIR, "steward", "oneshot")
    os.makedirs(cwd, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    try:
        r = subprocess.run([exe, "-p", "/usage", "--no-session-persistence"], cwd=cwd, env=env, capture_output=True,
                           text=True, timeout=90)
    except (OSError, subprocess.SubprocessError):
        return None
    return sq.parse_usage(r.stdout, time.time())


def quota_blocking() -> bool:
    """Kota kararı yeni iş almayı engelliyor mu (drain ya da stop)."""
    d = _QUOTA.get("decision")
    return bool(d is not None and d.action in ("drain", "shutdown", "stop"))


def _quota_save() -> None:
    d, u = _QUOTA.get("decision"), _QUOTA.get("usage")
    try:
        os.makedirs(os.path.dirname(QUOTA_FILE), exist_ok=True)
        from .. import statedocs
        statedocs.write_json("steward/quota", QUOTA_FILE,
                             {"at": _QUOTA.get("at"), "usage": dataclasses.asdict(u) if u else None,
                              "decision": dataclasses.asdict(d) if d else None, "stopped": bool(_QUOTA.get("stopped"))})
    except OSError:
        pass


def _quota_restore() -> None:
    """Servis açılışında `quota.json`daki son karar seviyesini belleğe al: restart sonrası ilk yoklama aynı seviyeyi YENİ yükseliş
    sanıp kapatma/ntfy'yi yinelemesin (sahip tavanda `steward up` ile açmışsa restart oturumları yeniden kapatırdı).
    Dosya yoksa/bozuksa seviye 0 (eski davranış). Yalnız bir kez."""
    if _QUOTA.get("loaded"):
        return
    _QUOTA["loaded"] = True
    try:
        from .. import statedocs
        saved = statedocs.read_json("steward/quota", QUOTA_FILE, None)
        if saved is None:
            raise ValueError("quota yok")
        act = str(((saved or {}).get("decision") or {}).get("action") or "ok")
        _QUOTA["level"] = {"shutdown": 1, "stop": 2}.get(act, 0)
        _QUOTA["stopped"] = _QUOTA["level"] > 0
    except (OSError, ValueError, AttributeError):
        pass


def _quota_stop(reason: str, hard: bool = False) -> None:
    """Tüm AÇIK kimlikleri kapat: değnekçiler `shutdown_start` (çalışmayana devir, bitince kapat; `hard`: ayrıca kendi
    oturumlarını HEMEN durdur). Reviewer kotadan MUAF (kapatılmaz)."""
    from ..settings import save_settings
    for sid in steward_ids():
        try:
            cfg = steward_config(sid)
            if not cfg.enabled:
                continue
            if cfg.role == "reviewer":
                # Reviewer Anthropic kotası tüketmez (agy/evren/codex; claude modu ayrı API anahtarı): kota bekçisi
                # onu KAPATMAZ (sahip kararı 2026-11-02). Yalnız claude-modlu review açıksa o mod kendi eşiğini taşır.
                continue
            shutdown_start(sid)
            if hard:
                ctx = _ctx(sid)
                projects = sw.load_projects(ctx.paths)
                world = _world(sid, cfg, 0, _ownership_index())
                for v in _collect_views(cfg):
                    if v.running and world.session_class(v.name, v.blueprint) == "own" or (v.running and v.name == cfg.brain_name):
                        try:
                            _apply(sw.Action("stop", v.name, "quota-hard"), cfg, projects, world)
                        except Exception as e:
                            diag_log("steward_quota_hard_stop_failed", sid=sid, name=v.name, error=repr(e))
        except Exception as e:
            diag_log("steward_quota_stop_failed", sid=sid, error=repr(e))
    sw.log_event("quota_hard_stop" if hard else "quota_stop", paths="default", reason=reason)
    notify_phone(f"Kota bekçisi: {'HARD kapanma' if hard else 'devirli kapatma başladı'} ({reason}). Açmak için: py/cops steward up")


def _quota_poll() -> None:
    try:
        u = quota_read_usage()
        if u is None:
            return
        cfg = quota_config()
        d = sq.decide(cfg, u, time.time())
        with _QUOTA_LOCK:
            prev = _QUOTA.get("decision")
            _QUOTA.update(usage=u, decision=d)
            if prev is None or prev.action != d.action:
                sw.log_event("quota_decision", paths="default", action=d.action, used=u.week_pct, cap=d.cap, reason=d.reason)
            lvl = {"shutdown": 1, "stop": 2}.get(d.action, 0)
            go = lvl > int(_QUOTA.get("level") or 0)
            _QUOTA["level"] = lvl if (go or lvl == 0) else _QUOTA.get("level")
            _QUOTA["stopped"] = lvl > 0
        _quota_save()
        if go:
            _quota_stop(d.reason, hard=lvl == 2)
    except Exception as e:
        diag_log("steward_quota_poll_failed", error=repr(e))
    finally:
        _QUOTA["busy"] = False


def quota_tick(now: Optional[float] = None) -> None:
    """Tick başına çağrılır (ucuz): mod kapalıysa hiçbir şey; açıksa aralıkta bir arka plan thread'inde kullanımı okur."""
    cfg = quota_config()
    if str(cfg.get("mode") or "off") not in ("manual", "auto"):
        _QUOTA["decision"] = None
        return
    _quota_restore()
    now = now if now is not None else time.time()
    try:
        poll = max(1.0, float(cfg.get("poll_minutes") or sq.DEFAULT_POLL_MINUTES))
    except ValueError:
        poll = float(sq.DEFAULT_POLL_MINUTES)
    if _QUOTA["busy"] or now - float(_QUOTA["at"]) < poll * 60:
        return
    _QUOTA["busy"] = True
    _QUOTA["at"] = now
    threading.Thread(target=_quota_poll, name="steward-quota", daemon=True).start()


_COST_WATCH: Dict[str, Any] = {"day": "", "warned": False, "stopped": False}


def ucli_cost_watch(base: Optional[sw.Config] = None) -> Dict[str, Any]:
    """ucli (Claude hizmeti) GÜNLÜK dolar harcamasını izler (`ucli_cost.daily_cap_usd`, 0 = tavan yok): %80'de TELEFONA
    uyarı, tavanda bildirim + beyin ucli ile koşuyorsa beyni DURDURUR (sürekli koşan oturum tavanı kendiliğinden
    aşardı; tavan yalnız açılışta denetleniyordu). Gün başına bir kez uyarır/durdurur; yeniden açma elle."""
    from .. import ucli_cost
    st = ucli_cost.state(use_cache=False)
    day = time.strftime("%Y-%m-%d")
    if _COST_WATCH["day"] != day:
        _COST_WATCH.update(day=day, warned=False, stopped=False, notified=False)
    cap, usd = float(st["cap_usd"]), float(st["today_usd"])
    if _COST_WATCH.get("cap") != cap:     # tavan değişti (yükseltildi/düşürüldü): uyarı/durdurma bayrakları yeniden değerlendirilsin
        _COST_WATCH.update(cap=cap, warned=False, stopped=False, notified=False)
    if cap <= 0:
        return {"cap": 0}
    if usd >= cap and not _COST_WATCH["stopped"]:
        _COST_WATCH["stopped"] = True       # durdurulamayan beyin olursa aşağıda geri açılır: sonraki tick yeniden dener
        cfg = base or steward_config()
        brain_note = ""
        targets: List[sw.Config] = [cfg]
        for sid in steward_ids():     # tavan makine geneli: ucli ile koşan TÜM kimliklerin beyni durur (yalnız default değil)
            try:
                c = steward_config(sid)
            except Exception:
                continue
            if c.brain_cli == "ucli":
                targets.append(c)
        failed = 0
        stopped_n = 0
        for c in targets:
            if c.brain_cli != "ucli":
                continue
            try:
                ok = bool(brain_stop(c).get("ok"))
            except Exception:
                ok = False
            stopped_n += ok
            failed += not ok
        if stopped_n or failed:
            brain_note = f" Beyin (ucli) durduruldu ({stopped_n})." + (f" {failed} beyin durdurulamadı!" if failed else "")
        if failed:
            _COST_WATCH["stopped"] = False   # tavan delinmesin: bir sonraki tick durdurmayı yeniden dener (bildirim tekrarlanmaz)
        if not _COST_WATCH.get("notified"):
            _COST_WATCH["notified"] = True
            sw.log_event("ucli_cost_cap", paths="all", usd=round(usd, 2), cap=cap)
            notify_phone(f"ucli günlük harcama TAVANA ulaştı: {usd:.2f}/{cap:.0f} USD.{brain_note} Devam için: Ayarlar ucli_cost.daily_cap_usd yükselt "
                         f"ya da `py/cops steward config brain_cli claude` (kota izin verince).", title="claudeops ucli tavan")
    elif usd >= 0.8 * cap and not _COST_WATCH["warned"] and usd < cap:
        _COST_WATCH["warned"] = True
        notify_phone(f"ucli günlük harcama %80'i geçti: {usd:.2f}/{cap:.0f} USD. Tavanda beyin durur.", title="claudeops ucli tavan")
    return {"cap": cap, "usd": usd}



def _mark_reviewer_tick(sid: str, now: Optional[float] = None) -> None:
    """Reviewer kimliğinin `state.json` `last_tick`i: motor reviewer'da `tick_once` çalıştırmaz, yoksa `steward -s reviewer
    status` "son tick: 8g" gösterir (döngü çalışırken). Hata döngüyü düşürmez."""
    try:
        paths = sw.paths_for(sid)
        st = sw.load_state(paths)
        st["last_tick"] = time.time() if now is None else now
        sw.save_state(st, paths)
    except Exception as e:
        sw.log_event("reviewer_mark_tick_failed", paths=sid, error=repr(e)[:200])


def tick_round(trigger: str = "timer") -> List[Dict[str, Any]]:
    """Bir tur; tüm kimlikler tek tarama önbelleği kapsamında (kimlik başına yeniden taranmaz; eylemler önbelleği düşürür)."""
    with _scan_scope():
        return _tick_round_inner(trigger)


def _tick_round_inner(trigger: str = "timer") -> List[Dict[str, Any]]:
    """Döngünün bir turu: `steward_ids()` sırasıyla, YALNIZ `enabled` kimlikler SIRAYLA tick'lenir (aynı anda tek spawn
    dalgası). Bir kimliğin hatası yutulup loglanır, diğerleri yine tick'lenir. Makine geneli `max_starts_total` bütçesi
    kimlikler arasında taşınır (`starts_left`); `max_active_total` her tick'in kendi görünümünden (diğer kimliklerin
    çalışan projeleri dahil) `plan_tick`'te uygulanır. Kart işi turda bir kez, tüm etkin kimlikler için."""
    base = steward_config()
    quota_tick()
    try:
        ucli_cost_watch(base)
    except Exception as e:      # izleyici döngüyü düşürmesin
        diag_log("ucli_cost_watch_failed", error=repr(e))
    starts_left = max(0, base.max_starts_total)
    results: List[Dict[str, Any]] = []
    enabled: List[sw.Config] = []
    disabled: List[str] = []
    reviewers: set = set()
    for sid in steward_ids():
        try:
            cfg = steward_config(sid)
            if cfg.role == "reviewer":
                # reviewer: tick_once/passive_scan/kart/beyin/kapatma YOK; yalnız kendi planlayıcısı (oturuma dokunmaz)
                reviewers.add(sid)
                if cfg.enabled:
                    results.append(dict(web_review.review_tick(cfg) or {}, sid=sid, role="reviewer"))
                    _mark_reviewer_tick(sid)
                    try:
                        auto_review_verify(cfg)
                    except Exception as e:      # otomatik doğrulama hatası döngüyü düşürmesin
                        sw.log_event("review_auto_verify_failed", paths=sid, error=repr(e)[:200])
                else:
                    web_review.review_disable(cfg)      # kapalı reviewer: koşan iş iptal, hiçbir şey başlamaz
                continue
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
        if sid in reviewers:
            continue
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
        try:
            tick = max(15, steward_config().tick_seconds)
        except Exception as e:      # bozuk ayar thread'i öldürmesin (`_loop_started` True kalır, restart'a dek tick olmazdı)
            diag_log("steward_loop_config_failed", error=repr(e))
            tick = 60
        time.sleep(tick)
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
    api_err = sw.api_error_brief(state)
    if api_err:     # yalnız hata varken (alan yokken eski panel/altın testler aynı)
        value["api_errors"] = api_err
    loops = sw.loop_paused(state, time.time())
    if loops:
        value["loop_paused"] = loops
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
        if sm.get("api_errors"):
            row["api_errors"] = sm["api_errors"]
        if cfg.role != "steward":       # yalnız reviewer/generic'te: sıradan kimliğin satırı (ve altın testler) değişmez
            row["role"] = cfg.role
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
    session_of: Dict[str, Dict[str, str]] = {}      # proje adı -> {name, host}: panelde proje satırından terminali açmak için
    for s_ in live:
        pr = _project_for_session(s_.name, projects, world)
        if pr is not None and pr.name not in session_of and not _name_host_in(s_.name, projects, world):
            session_of[pr.name] = {"name": s_.name, "host": ""}
    for r_ in remote_running:
        pr = _project_for_session(str(r_.get("name") or ""), projects, world)
        if pr is not None and pr.name not in session_of:
            session_of[pr.name] = {"name": str(r_.get("name") or ""), "host": str(r_.get("host") or world.host_of(pr.name) or "")}
    plist = []
    for p_ in sorted(projects.values(), key=lambda p: (p.priority, p.name)):
        d_ = _project_dict(p_, running_projects, cards)
        if p_.name in session_of:
            d_["session"] = session_of[p_.name]
        why_ = (ctx.idle_why.get("by") or {}).get(p_.name)
        if why_:
            d_["why"] = dict(why_, at=ctx.idle_why.get("at") or 0.0)
        plist.append(d_)
    out = {
        "ok": True,
        "config": dataclasses.asdict(cfg),
        "summary": summary(sid=sid),
        "pending": list(sw.load_state(paths).get("pending_list") or []),
        "projects": plist,
        "running": [{"name": s.name, "cwd": s.cwd, "cli": s.cli, "model": s.model} for s in live] + remote_running,
        "questions": questions,
        "ideas": [dataclasses.asdict(i) for i in sw.load_ideas(paths) if i.status == "new"],
        "recent": ctx.recent,
        "loop_guard": loop_guard_list(sid),
    }
    sd_ = sw.load_state(paths).get("shutdown")
    if isinstance(sd_, dict) and sd_:                # kapatma hiç başlamadıysa anahtar HİÇ eklenmez (çıktı aynı)
        out["shutdown"] = {"started": sd_.get("started"), "done": sd_.get("done"), "cancelled": bool(sd_.get("cancelled")),
                           "left_paused": list(sd_.get("left_paused") or []),
                           "items": {n: {"stage": i.get("stage"), "blocked": i.get("blocked", "")}
                                     for n, i in (sd_.get("items") or {}).items() if isinstance(i, dict)}}
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
_REVIEW_UNVERIFIED_FILES = {"rtodo": ("RTODO.md", lambda r: not rv.is_decision(r)), "rtbd": ("RTBD.md", rv.is_decision)}


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


def _idea_appended(text: str, idea: "sw.Idea", stamp: str) -> Optional[str]:
    """`text`in sonuna fikri `- [ ]` maddesi olarak eklenmiş yeni içerik; aynı fikir kimliği zaten varsa None. SAF
    (yerel `_append_idea_item` ile uzak `_remote_append_idea` ortak çekirdeği)."""
    if idea.id in text:
        return None
    line = f"- [ ] (değnekçi fikri {idea.id}) {' '.join(idea.text.split())}"
    last_head = next((ln for ln in reversed(text.splitlines()) if ln.startswith("## ")), "")
    body = text.rstrip("\n")
    if last_head.startswith(_EXPORT_HEADING):
        new = f"{body}\n{line}\n"
    else:
        new = (f"{body}\n\n" if body else "") + f"{_EXPORT_HEADING} ({stamp})\n{line}\n"
    return new


def _append_idea_item(path: str, idea: "sw.Idea", stamp: str) -> bool:
    """Fikri `path`in sonuna `- [ ]` maddesi olarak ekler (aynı fikir kimliği varsa dokunmaz). True = yazıldı."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    new = _idea_appended(text, idea, stamp)
    if new is None:
        return False
    from ..atomic_json import atomic_write_text
    atomic_write_text(path, new)        # pid+thread'e özel tmp (yalnız pid aynı süreçteki thread'leri çakıştırırdı)
    return True


def _remote_read_full(host: str, name: str, path: str, budget: float) -> Optional[str]:
    """Host-routed `GET /api/files/read` ile dosyanın TAMAMI (kırpma YOK: yazılacak içerik buna dayanır); None =
    okunamadı (dosya yok, boyut sınırı, ağ/zaman aşımı, uygulama hatası). Fırlatmaz."""
    try:
        parsed, _status = _remote.get("/api/files/read", host, {"name": name, "path": path}, timeout=budget)
    except Exception:
        return None
    if not isinstance(parsed, dict) or not parsed.get("ok") or not isinstance(parsed.get("text"), str):
        return None
    return parsed["text"]


def _remote_append_idea(host: str, name: str, fname: str, idea: "sw.Idea", stamp: str, dry: bool,
                        sid: str = "default") -> str:
    """Uzak projenin `fname` dosyasının sonuna fikri ekler (A6). Sonuç: written | already | would | denied |
    no_folder | unreadable | remote_conflict | write_failed. Sıra: kapı (remote_actions + taze host) → uzak klasör →
    dosyayı OKU (okunamazsa YAZILMAZ) → madde ekli mi → observe'da dur (`would`) → yazmadan hemen önce TEKRAR oku,
    değiştiyse bırak (`remote_conflict`) → host-routed `files/write` (kök denetimi uzak tarafta). Uzak `files/write`
    yalnız VAR OLAN dosyayı değiştirir, yeni dosya oluşturmaz: dosya yoksa okuma da başarısız olur → `unreadable`."""
    if not _remote_files_gate(host, sid):
        return "denied"
    real, cwd = _remote_ref(host, name)
    if not cwd:
        return "no_folder"
    name = real or name
    if "/" in fname or ".." in fname or "\x00" in fname:      # sözcük denetimi (fname sabit tablodan gelir; yine de)
        return "unreadable"
    path = cwd.rstrip("/") + "/" + fname
    before = _remote_read_full(host, name, path, REMOTE_READ_BUDGET_SECONDS)
    if before is None:
        return "unreadable"
    new = _idea_appended(before, idea, stamp)
    if new is None:
        return "already"
    if dry:
        return "would"
    if _remote_read_full(host, name, path, REMOTE_READ_BUDGET_SECONDS) != before:
        return "remote_conflict"
    res = _remote_post(host, "/api/files/write", {"name": name, "path": path, "content": new}, REMOTE_INPUT_TIMEOUT_SECONDS)
    return "written" if res.get("ok") else "write_failed"


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
    if not names and target == "project" and len(projects) == 1:
        names = sorted(projects)      # fikrin projesi yok (panelden eklenen) ama kimlikte TEK proje var: belirsizlik yok
    if not names:
        return {"ok": False, "error": "idea has no steward project; choose target=all"}
    stamp = time.strftime("%Y-%m-%d")
    written: List[str] = []
    present: List[str] = []
    skipped: List[str] = []
    would: List[str] = []
    problems: Dict[str, str] = {}       # uzak proje → neden yazılamadı (yalnız uzak projeler; yerel çıktı değişmez)
    dry = data.get("actor") == "brain" and steward_config(sid).mode == "observe"    # insan çağrısı observe'da da yazar
    for n in names:
        if projects[n].host:      # uzak proje: yerel klasöre ASLA yazılmaz; host-routed okuma + yazma (A6)
            try:
                st = _remote_append_idea(projects[n].host, n, fname, idea, stamp, dry, sid)
            except Exception as e:
                diag_log("steward_idea_export_failed", project=n, host=projects[n].host, error=repr(e))
                st = "write_failed"
            if st == "written":
                written.append(n)
            elif st == "already":
                present.append(n)
            elif st == "would":
                would.append(n)
            else:
                skipped.append(n)
                problems[n] = st
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
    if would and not written and not present:     # observe + beyin: hiçbir şey yazılmadı, fikir `exported` OLMAZ
        sw.log_event("would:idea_export", paths=sid, id=idea.id, kind=kind, target=target, would=would, skipped=skipped)
        return {"ok": True, "dry": True, "would": would, "skipped": skipped, **({"remote": problems} if problems else {})}
    if not written and not present:
        return {"ok": False, "error": "no project directory found", "skipped": skipped,
                **({"remote": problems} if problems else {})}
    sw.record_idea_export(idea.id, {"kind": kind, "target": target, "file": fname, "projects": written + present, "at": time.time()},
                          sid)
    sw.log_event("idea_export", paths=sid, id=idea.id, kind=kind, target=target, written=written, present=present, skipped=skipped)
    return {"ok": True, "written": written, "already": present, "skipped": skipped,
            **({"remote": problems} if problems else {}), **({"would": would} if would else {})}


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
        world = _world(sid)      # uzak oturum adı tarih sonekli olabilir (`oiso20261017` -> `oiso`): proje çözümüyle karşılaştır
        out["running"] = any(world is not None and world.resolve(str(r["name"] or "")) == ("project", name)
                             for r in _remote_running_listing(world))
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
        real, cwd = _remote_ref(remote, name)
        name = real or name
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
    if "model" in fields or "effort" in fields:
        # yalnız İSTENEN değer denetlenir (sahibin elle verdiği mevcut üst modeli beyin not/faz yazarken bozmaz)
        upper = _upper_model_gate(name, str(fields.get("model") or ""), str(fields.get("effort") or ""), sid,
                                  str(data.get("actor") or ""), project_name=name)
        if upper is not None:
            return upper
    if "host" in fields:
        if data.get("actor") == "brain":
            # Projenin hangi makinede yaşadığı sahibin kararı: beyin host'u değiştiremez (yanlış host = yanlış adaş oturum).
            sw.log_event("project_denied", paths=sid, actor="brain", name=name, field="host")
            return {"ok": False, "error": "brain cannot change a project's host (ask the owner)"}
        fields["host"] = sw.normalize_host(fields["host"])
    if (data.get("actor") == "brain" and old is not None and old.phase in sw.ACTIVE_PHASES
            and fields.get("phase") in ("idea", "paused", "done")):
        # idea/done: sahibin ya da kanıtlı STEWARD-DONE'ın işi (27 Eki: 4 proje paused'a çekilip oturumları kapandı).
        # paused (sahip TBD#163 b, 6 Kas): beyin yalnız gerekçeyle ve `sw.brain_pause_verdict` geçerse; her sonuç günlüğe.
        why = ""
        if fields["phase"] == "paused":
            reason = str(data.get("reason") or "").strip()
            ok, why = sw.brain_pause_verdict(sw.load_card(name), bool(_live_sessions(name, sid)), reason)
            if ok:
                sw.log_event("brain_pause", paths=sid, actor="brain", name=name, reason=reason[:300])
                try:
                    _notify(steward_config(sid), f"{sw.ask_prefix(name, sid)} beyin projeyi paused yaptı: {reason[:200]}")
                except Exception as e:      # bildirim hatası kararı bozmaz
                    diag_log("brain_pause_notify_failed", error=repr(e))
        if fields["phase"] != "paused" or why:
            sw.log_event("brain_pause_refused" if fields["phase"] == "paused" else "project_denied", paths=sid,
                         actor="brain", name=name, field="phase", value=fields["phase"], why=why)
            return {"ok": False, "error": f"brain cannot set phase {fields['phase']}"
                                          + (f" ({why})" if why else " (owner decision)")
                                          + "; owner-blocked work stays 'planned' and the engine asks the owner once "
                                            "instead of opening the session"}
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
    """Projeyi kimliğin kaydından çıkar (oturuma dokunmaz; roster/klasör kalır). Yalnız insan (panel/CLI)."""
    if (d := _human_only(data, "remove a project")):
        return d
    name = str(data.get("name") or "").strip()
    ok = sw.remove_project(name, sid)
    if ok:
        sw.log_event("project_remove", paths=sid, name=name, source=str(data.get("source") or "ui"))
    return {"ok": ok} if ok else {"ok": False, "error": f"not a project of steward {sid}: {name!r}"}


def _register_remote(name: str, host: str, want_host: str, known: Optional["sw.Project"], data: Dict[str, Any],
                     cfg: sw.Config) -> Dict[str, Any]:
    """`http_register`in uzak kolu (A6): uzak host'taki MEVCUT roster satırını benimser (taze `registered` satırında ad
    var mı; `_in_remote_roster`). Uzak klasör/GOAL.md/roster satırı OLUŞTURMAZ ve yerel hiçbir şeye dokunmaz: uzak
    host'ta kayıt yoksa net hata. Proje kaydı `host` alanıyla YEREL tutulur. Kapı: `remote_actions` açık + taze host."""
    paths = sw.paths_for(cfg.sid)
    err = ("remote project: register it on its host first (proxy /api/register on that host), then adopt it with "
           "`py/cops steward set NAME --host HOST`")
    if want_host and known is not None and known.host and known.host != want_host:
        return {"ok": False, "error": f"remote project: {name!r} is registered on host {known.host!r}, not {want_host!r}"}
    if not _remote_files_gate(host, cfg.sid):
        return {"ok": False, "error": err + " (adoption also needs steward.remote_actions on and a fresh host)"}
    if not _in_remote_roster(name, host):
        return {"ok": False, "error": err + f" (no registered row named {name!r} on {host})"}
    other = sw.project_owner(name, exclude=cfg.sid)
    if other:
        return {"ok": False, "error": str(sw.OwnedElsewhere(name, other))}
    if name not in sw.load_projects(paths):
        why = sw.reserved_reason(name, _ownership_index(fresh=True))
        if why:
            return {"ok": False, "error": str(sw.ReservedName(name, why))}
    phase = data.get("phase") if data.get("phase") in sw.PHASES else "planning"
    try:
        p = sw.upsert_project(name, paths=paths, phase=phase, kind=data.get("kind") or "",
                              goal=str(data.get("goal") or "").strip(), priority=data.get("priority"),
                              cadence_minutes=data.get("cadence_minutes"), host=host)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    idea_id = str(data.get("idea_id") or "")
    if idea_id:
        sw.update_idea(idea_id, status="project", project=name, paths=paths)
    sw.log_event("project_register", paths=paths, name=name, host=host, adopted=True)
    return {"ok": True, "project": _project_dict(p), "host": host, "adopted": True}


def http_register(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Yeni proje: klasör (yoksa oluştur + git init), GOAL.md (amaç + kaynaklar), yerel kaynak dosyalarını
    `kaynaklar/`a kopyala, roster'a kaydet (`web._register_project`), değnekçi kaydını aç."""
    cfg = steward_config(sid)
    if cfg.role == "reviewer":      # yan etkiden (klasör/git/roster) ÖNCE: reviewer proje sahibi olamaz
        return {"ok": False, "error": f"steward {cfg.sid} is a reviewer: it cannot own projects"}
    name = str(data.get("name") or "").strip()
    cwd = os.path.expanduser(str(data.get("cwd") or "").strip())
    goal = str(data.get("goal") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    upper = _upper_model_gate(name, str(data.get("model") or ""), "", cfg.sid, str(data.get("actor") or ""),
                              project_name=name)
    if upper is not None:      # yan etkiden ÖNCE: generic beyin roster'a Opus/Fable modelli proje yazamaz
        return upper
    known = sw.load_projects(cfg.sid).get(name)
    want_host = sw.normalize_host(data.get("host"))
    host = want_host or (known.host if known is not None else "") or _name_host(name)
    if host:
        return _register_remote(name, host, want_host, known, data, cfg)
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


_JOB_RED_SEEN: Dict[Tuple[str, str, str], float] = {}   # (kimlik, proje, normalize gerekçe) -> son RED zamanı (süreç içi; restart sıfırlar)
JOB_RED_REPEAT_SECONDS = 24 * 3600


def _job_red_seen(sid: str, project: str, red: str, now: Optional[float] = None) -> bool:
    """Aynı proje için aynı gerekçeli RED 24 sa içinde daha önce geldi mi (geldiyse sahibe soru tekrarlanmaz). Kaydı da günceller."""
    now = time.time() if now is None else now
    key = (sid, project, re.sub(r"[\d\W_]+", " ", red.lower()).strip()[:80])
    prev = _JOB_RED_SEEN.get(key, 0.0)
    for k in [k for k, t in _JOB_RED_SEEN.items() if now - t > JOB_RED_REPEAT_SECONDS]:
        _JOB_RED_SEEN.pop(k, None)
    _JOB_RED_SEEN[key] = now
    return bool(prev) and (now - prev) <= JOB_RED_REPEAT_SECONDS


_JOB_KINDS_CACHE: Dict[str, Tuple[float, Optional[List[str]]]] = {}    # servis -> (zaman, tür listesi | None=ulaşılamadı)
JOB_KINDS_TTL_SECONDS = 600
_JOB_NOTE_SENT: Dict[str, float] = {}      # oturum -> `STEWARD-JOB yalnız servise iş içindir` notunun gittiği zaman (süreç içi; oturum başına BİR kez)


def _registered_job_kinds(now: float) -> Tuple[bool, Optional[set]]:
    """(servis kayıtlı mı, tüm kayıtlı servislerin iş türleri birleşimi | None = hiçbirinin kataloğuna ulaşılamadı). Servis adları
    sabit değil: `services.json`dan okunur; katalog `GET /api/jobs/kinds`, 10 dk önbellekli."""
    svcs = sj.load_services()
    if not svcs:
        return False, None
    union: set = set()
    got = False
    for n, svc in svcs.items():
        hit = _JOB_KINDS_CACHE.get(n)
        if hit is None or now - hit[0] > JOB_KINDS_TTL_SECONDS:
            kinds: Optional[List[str]] = None
            try:
                status, body = sj.request_json(svc, "GET", "/api/jobs/kinds")
                items = body.get("kinds", body) if isinstance(body, dict) else body
                if status == 200 and isinstance(items, dict):
                    kinds = sorted(str(x) for x in items)
                elif status == 200 and isinstance(items, list):
                    kinds = sorted({str(x.get("kind") or x.get("name") or "") if isinstance(x, dict) else str(x) for x in items} - {""})
            except Exception:
                kinds = None
            hit = (now, kinds)
            _JOB_KINDS_CACHE[n] = hit
        if hit[1] is not None:
            got = True
            union.update(hit[1])
    return True, (union if got else None)


def _job_marker_gate(action: "sw.Action", cfg: "sw.Config", name: str, host: str, paths: Any) -> Optional[Dict[str, Any]]:
    """`STEWARD-JOB` işareti yalnız KAYITLI servise gerçek iş isteğiyse soru/rutin madde açar. Değilse (servis yok, tür katalogda yok,
    durum notu) madde AÇILMAZ, olay `job_marker_rejected` yazılır, yerel boştaki tmux oturuma BİR kez not gider. None = geç."""
    body = str(action.payload.get("text") or "")[len(sw.JOB_REQUEST_PREFIX):]
    now = time.time()
    registered, kinds = _registered_job_kinds(now)
    ok, why = sw.job_marker_verdict(body, kinds, registered)
    if ok:
        return None
    noted = False
    note = sw.JOB_NOTE_TEXT + f" {sj.KINDS_HINT}; {sj.file_rule_text()}."
    if why == "unknown_kind" and kinds:
        bad = (body.strip().split(None, 1) or [""])[0].strip("`")
        note += f" `{bad}` geçerli bir tür değil; en yakın 3: {', '.join(sj.closest_kinds(bad, kinds))}."
    if name not in _JOB_NOTE_SENT and not host:
        s = _running(name)
        if s is not None and is_tmux_backed(s.pid) and not _box_has_typed_input(s.name):
            noted = bool(_send(s.name, s.cli, sw.one_line(note, 1200)))
            if noted:
                _JOB_NOTE_SENT[name] = now
    sw.log_event("job_marker_rejected", paths=paths, name=name, project=action.payload.get("project"), reason=why,
                 text=body[:160], noted=noted)
    return {"ok": True, "skipped": "job_marker_" + why, "noted": noted}


def _preserve_undelivered_answer(q: "sw.Question", cfg: "sw.Config", paths: Any, projects: Dict[str, "sw.Project"]) -> str:
    """Oturuma İLETİLEMEYEN sahip cevabı KAYBOLMASIN (hittite/trino/animallang, 11 Kas): proje yerel ve klasörü biliniyorsa projenin
    TOBEDECIDED.md'sine ilgili maddenin altına (yoksa sona) `Sahip cevabı (tarih, değnekçi): ...` yazılır ve YALNIZ o dosya açık yolla commit
    edilir (izleniyorsa; git-dışı/dışlanmışsa yazı kalır). Uzak ya da klasörü bilinmeyen proje: yazılmaz, sahibe telefon bildirimi.
    Sonuç: written | already | remote | no_folder | failed. Fırlatmaz."""
    try:
        proj = projects.get(q.project)
        host = proj.host if proj is not None else ""
        if not host:
            try:
                host = (_ownership_index().get("hosts") or {}).get(q.project, "")
            except Exception:
                host = ""
        cwd = "" if host else _cwd_resolver()(q.project)
        out = "remote" if host else ("no_folder" if not cwd or not os.path.isdir(cwd) else "")
        if not out:
            real = _doc_path(cwd, "TOBEDECIDED.md") or os.path.join(cwd, "TOBEDECIDED.md")
            try:
                with open(real, encoding="utf-8", errors="replace") as f:
                    before = f.read()
            except FileNotFoundError:
                before = ""
            new = sw.tbd_insert_answer(before, q.id, q.text, q.answer, time.strftime("%Y-%m-%d"))
            if new is None:
                out = "already"
            else:
                from ..atomic_json import atomic_write_text
                atomic_write_text(real, new)
                out = "written"
                try:       # yalnız bu dosya, açık yolla; izlenmiyorsa/dışlanmışsa add başarısız olur ve commit atlanır
                    if subprocess.run(["git", "-C", cwd, "add", "--", real], capture_output=True, timeout=20).returncode == 0:
                        subprocess.run(["git", "-C", cwd, "commit", "-q", "-m", f"TOBEDECIDED: sahip cevabı [{q.id}] (değnekçi iletemedi)", "--", real],
                                       capture_output=True, timeout=30)
                except (OSError, subprocess.SubprocessError):
                    pass
        sw.log_event("answer_preserved", paths=paths, id=q.id, project=q.project, result=out)
        if out in ("remote", "no_folder", "failed"):
            reason = "uzak proje" if out == "remote" else "proje klasörü bilinmiyor"
            _notify(cfg, (f"[{cfg.sid}] Cevabın {q.project} projesine İLETİLEMEDİ ve hiçbir dosyaya YAZILMADI ({reason}): [{q.id}] {q.answer[:200]}"
                          if cfg.lang != "en" else
                          f"[{cfg.sid}] Your answer to {q.project} could NOT be delivered and was NOT written anywhere ({reason}): [{q.id}] {q.answer[:200]}"))
        return out
    except Exception as e:
        diag_log("answer_preserve_failed", id=getattr(q, "id", ""), error=repr(e))
        return "failed"


def _job_kinds_list(sid: str) -> List[str]:
    """Varaka iş türü kataloğundaki tür adları (en iyi çaba; servis yoksa/ulaşılamazsa boş liste)."""
    try:
        res = http_jobs(sid, kinds=True)
    except Exception:
        return []
    body = res.get("kinds") if res.get("ok") else None
    items = body.get("kinds", body) if isinstance(body, dict) else body
    if isinstance(items, dict):
        return sorted(str(k) for k in items)[:40]
    if isinstance(items, list):
        return sorted({str(x.get("kind") or x.get("name") or "") if isinstance(x, dict) else str(x) for x in items} - {""})[:40]
    return []


def _job_red_feedback(sid: str, q0: "sw.Question", red: str) -> None:
    """Beyin İŞ İSTEĞİ'ni RED'dedince gerekçeyi (+ geçerli iş türleri) isteği açan proje oturumuna kısa direktif olarak
    gönder; çalışan oturum yoksa açmaz. Hata fırlatmaz."""
    try:
        cfg = steward_config(sid)
        project = sw.load_projects(sid).get(q0.project)
        if project is None:
            return
        kinds = _job_kinds_list(sid)
        text = f"İş isteğin gönderilmedi: {red[:300]}." + (f" Geçerli iş türleri: {', '.join(kinds)}." if kinds else "") + \
               f" {sj.KINDS_HINT}; {sj.file_rule_text()}. İsteği düzeltip yeniden yaz (STEWARD-JOB)."
        _give_directive(project, text, start_if_stopped=False, reason="job-red", cfg=cfg, actor="engine")
    except Exception as e:
        diag_log("job_red_feedback_failed", sid=sid, project=q0.project, error=repr(e))


BRAIN_DENIED_KEEP_SECONDS = 14 * 86400     # kayıt bu kadar sonra düşer (açık soru engeli `owner_pending_block`ta zaten soruya bağlı)


def _record_brain_denied(sid: str, qid: str) -> None:
    """Beynin cevabı `owner_only` ile reddedilen soruyu `state.brain_denied`e yaz (direktifle dolanma engeli için)."""
    paths = sw.paths_for(sid)
    now = time.time()
    with sw.steward_lock(paths):
        state = sw.load_state(paths)
        denied = {k: float(v) for k, v in dict(state.get("brain_denied") or {}).items()
                  if isinstance(v, (int, float)) and now - float(v) < BRAIN_DENIED_KEEP_SECONDS}
        denied[qid] = now
        state["brain_denied"] = denied
        sw.save_state(state, paths)


def http_answer(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    if str(data.get("actor") or "") == "brain":
        q0 = next((q for q in sw.load_questions(sw.paths_for(sid)) if q.id == str(data.get("id") or "")), None)
        if q0 is not None:
            ok, why = sw.brain_may_answer(q0)
            if not ok:
                sw.log_event("answer_denied", paths=sid, id=q0.id, project=q0.project, reason=why)
                _record_brain_denied(sid, q0.id)
                if q0.routine:      # TBD#140: sahip kararı çıkan rutin/blocked madde beyinde 15 tur dönmez, ANINDA sahibe düşer
                    esc = sw.escalate_routine(q0.id, sw.paths_for(sid))
                    if esc is not None:
                        _notify(steward_config(sid), f"{_ask_prefix(esc.project, sid)} Beyin cevaplayamaz (sahip kararı): {esc.text}\n→ {sw.ask_hint(esc.id, sid)}")
                        sw.log_event("escalate_owner_only", paths=sid, id=esc.id, project=esc.project)
                return {"ok": False, "error": why, "code": "owner_only"}
            ok, why, red = sw.job_request_gate(q0, str(data.get("answer") or ""), sj.load_jobs(sw.paths_for(sid)))
            if not ok:
                sw.log_event("answer_denied", paths=sid, id=q0.id, project=q0.project, reason="job_request_unsubmitted")
                return {"ok": False, "error": why, "code": "job_not_submitted"}
            if red:      # iş gönderilmedi (tür yok, dosya belirsiz): istek kaybolmasın, sahibe iletilir
                repeat = _job_red_seen(sid, q0.project, red)
                _job_red_feedback(sid, q0, red)       # proje oturumu kendi yanlışını görsün (ncs 2026-10-29: aynı yanlış türle yineledi)
                if not repeat:                         # ardışık aynı RED sahibe tekrar sorulmaz (yalnız oturuma gider)
                    nq, _how = sw.add_question_ex(q0.project, f"İş isteği gönderilmedi (beyin RED): {red}\nİstek: {q0.text[len(sw.JOB_REQUEST_PREFIX):][:400]}\n"
                                       "Elle varaka oturumuna iletilsin mi, yoksa istek düzeltilsin mi?", source="job-red", paths=sw.paths_for(sid))
                    _notify(steward_config(sid), f"{_ask_prefix(q0.project, sid)} İş isteği gönderilmedi (beyin RED): {red[:200]}\n"
                                                 f"→ {sw.ask_hint(nq.id, sid)}")      # kaydedilen soru telefona da gitsin
                sw.log_event("job_request_red", paths=sid, id=q0.id, project=q0.project, reason=red[:200], repeat=repeat)
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


def _brain_directive_defer(name: str, sid: str) -> Optional[Dict[str, Any]]:
    """Beynin YEREL oturuma direktifi: oturum meşgulse ya da az önce direktif/cevap gittiyse GÖNDERİLMEZ, ertelenir
    (`tour_deferred`: sonraki tur `tour_retry_minutes` sonra). Yanıt `session_busy`; beyin sonraki turda yeniden dener."""
    projects = sw.load_projects(sid)
    world = _world(sid)
    p = _project_for_session(name, projects, world)
    payload = _act("status_payload") or {}
    paths = sw.paths_for(sid)
    lda = sw.load_state(paths).get("last_directive_at") or {}
    busy: Optional[bool] = None
    sub = False
    last = 0.0
    for r in payload.get("sessions") or []:
        rn = str(r.get("name") or "")
        if not r.get("running") or sw.normalize_host(r.get("host")):
            continue
        mine = rn == name
        if not mine and p is not None:
            q = _project_for_session(rn, projects, world)
            mine = q is not None and q.name == p.name
        if not mine:
            continue
        if r.get("busy") is True:
            busy = True
        last = max(last, float(lda.get(rn) or 0.0))
    last = max(last, float(lda.get(name) or 0.0))
    try:    # çalışan alt ajan = ana oturum boşta görünse de iş sürüyor (cevap iletimi de aynı kuralı izler)
        sub = any(subagent_active_for(x.cwd, x.sid) for x in _live_sessions(name, sid))
    except Exception:
        sub = False
    why = "subagent_active" if sub else sw.directive_defer_reason(busy, last, time.time())
    if not why:
        return None
    try:
        with sw.steward_lock(paths):
            state = sw.load_state(paths)
            state["tour_deferred"] = True
            sw.save_state(state, paths)
    except sw.LockTimeout:
        pass
    sw.log_event("directive_deferred", paths=sid, name=name, reason=why)
    return {"ok": False, "code": "session_busy", "error": f"session_busy ({why}): directive not sent; retried on the next tour"}


def _upper_model_gate(name: str, model: str, effort: str, sid: str, actor: str,
                      project_name: str = "") -> Optional[Dict[str, Any]]:
    """generic kimlikte BEYNİN proje ana oturumunu üst kademeye (Opus/Fable ya da high/xhigh/max) çeken isteği: sahibin
    cevaplanmış onay sorusu yoksa red + (yoksa) onay sorusu açılır. İnsan (actor != brain) ve diğer roller serbest.
    Yanıt `upper_model_needs_approval`; onaya kadar beyin modelsiz (Sonnet medium) sürdürür."""
    if actor != "brain" or not sw.is_upper_tier(model, effort):
        return None
    cfg = steward_config(sid)
    if not sw.is_generic(cfg):
        return None
    pname = project_name
    if not pname:
        p = _project_for_session(name, sw.load_projects(sid), _world(sid))
        pname = p.name if p is not None else name
    if sw.upper_tier_approved(sw.load_questions(sid), pname, model, effort):
        return None
    asked = http_ask({"project": "", "text": sw.upper_tier_question_text(pname, model, effort, cfg.lang),
                      "options": ["onayla", "reddet"] if cfg.lang != "en" else ["approve", "reject"],
                      "source": sw.UPPER_MODEL_SOURCE}, sid)
    qid = str(asked.get("id") or "")
    rejected = False
    if qid:
        q = sw.find_question(qid, sid)
        rejected = q is not None and q.status == "answered"
    sw.log_event("upper_model_denied", paths=sid, name=name, project=pname, model=model, effort=effort, question=qid,
                 rejected=rejected)
    why = ("the owner rejected this model/effort for the main session" if rejected else
           "owner approval required; an approval question is open")
    return {"ok": False, "code": "upper_model_needs_approval", "question": qid,
            "error": f"upper_model_needs_approval: {model or '-'}/{effort or '-'} for {pname!r}: {why}. "
                     f"Continue on {sw.GENERIC_MODEL} + {sw.GENERIC_EFFORT} (send without model/effort)."}


def http_panic(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Acil durdurma (`steward/PANIC`): `{"on": true|false}`; alan yoksa yalnız durum. Beyin DEĞİŞTİREMEZ (insan kararı).
    Açıkken tüm kimlikler `observe` gibi davranır: oturuma direktif/devir/başlatma/durdurma gitmez, kayıt (soru/fikir) sürer."""
    if str(data.get("actor") or "") == "brain":
        return {"ok": False, "error": "brain cannot change the panic flag"}
    if "on" in data:
        try:
            sw.set_panic(bool(data.get("on")), str(data.get("reason") or "")[:200])
        except OSError as e:
            return {"ok": False, "error": str(e)}
        sw.log_event("panic", paths=sid, on=bool(data.get("on")), reason=str(data.get("reason") or "")[:200])
    return {"ok": True, "panic": sw.panic_active()}


def http_directive(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    text = str(data.get("text") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    if str(data.get("actor") or "") == "brain" and (steward_config(sid).drain or quota_blocking() or sw.panic_active()):
        return {"ok": False, "error": "draining: the steward takes no new work (human turned 'drain' on)", "code": "draining"}
    gated = _gate(name, data, "directive", sid)
    if gated is not None:
        return gated
    upper = _upper_model_gate(name, str(data.get("model") or ""), str(data.get("effort") or ""), sid,
                              str(data.get("actor") or ""))
    if upper is not None:
        return upper
    if str(data.get("actor") or "") == "brain" and not _name_host(name):
        why = _brain_directive_defer(name, sid)
        if why:
            return why
    with _ctx(sid).lock:
        projects = sw.load_projects(sid)
        p = _project_for_session(name, projects, _world(sid))
        if p is None:
            if _running(name) is None and not inst_mod.get_instance(name) and name not in (_act("fleet_status") or {}):
                return {"ok": False, "error": "unknown session/project"}
            p = sw.Project(name=name)   # ad hoc: kayıt açmadan sadece gönder
        if str(data.get("actor") or "") == "brain":
            denied = sw.load_state(sw.paths_for(sid)).get("brain_denied") or {}
            q = sw.owner_pending_block({name, p.name}, sw.load_questions(sw.paths_for(sid)), denied) if denied else None
            if q is not None:
                sw.log_event("directive_denied", paths=sid, name=name, project=p.name, question=q.id, reason="owner_pending")
                return {"ok": False, "code": "owner_pending",
                        "error": f"owner_pending: question {q.id} for {p.name} was rejected for you (owner_only) and is still open; "
                                 "do not route it via directive, the owner answers it"}
        res = _give_directive(p, text, model=str(data.get("model") or ""), effort=str(data.get("effort") or ""),
                              start_if_stopped=bool(data.get("start_if_stopped", True)),
                              reason=str(data.get("reason") or "brain"), session_name=name, cfg=steward_config(sid),
                              actor=str(data.get("actor") or ""))
    if str(data.get("actor") or "") == "brain":
        _register_brain_outcome(res, name, sid)
    return res


def _register_brain_outcome(res: Any, name: str, sid: str) -> None:
    """L5 boşluğu (L2 kalan b): beynin MCP direktifi de doğrulama kuyruğuna girer (`via: brain`). Taban imza YOK
    (görüntü toplamak HTTP yolunda pahalı): sonuç hedefin `last_activity`siyle verilir. Atlanan/kuru gönderim yazılmaz."""
    if not (isinstance(res, dict) and res.get("ok")) or res.get("skipped") or res.get("dry"):
        return
    _register_outcomes([{"kind": "directive", "name": str(res.get("name") or name), "at": time.time(), "sigs": {},
                         "via": "brain"}], sw.paths_for(sid))


def http_restart(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not sw.valid_name(name):
        return {"ok": False, "error": "invalid name"}
    cfg = steward_config(sid)
    gated = _gate(name, data, "restart", sid)
    if gated is not None:
        return gated
    upper = _upper_model_gate(name, str(data.get("model") or ""), str(data.get("effort") or ""), sid,
                              str(data.get("actor") or ""))
    if upper is not None:      # DURDURMADAN önce: reddedilen restart oturumu kapalı bırakmasın
        return upper
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
        live = _live_sessions(name, sid)
        if live:
            res = _act("stop", live[0].name if len(live) == 1 else name, lang=cfg.lang)
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
            real = _resolved_local_name(name, sid)
            proj = None
            actor = str(data.get("actor") or "")
            force = bool(data.get("force"))      # YALNIZ insan: ho'suz zorla kapat (sahip kuralı 2026-11-05: kapatırken mutlaka ho)
            if real != cfg.brain_name and (actor == "brain" or not force):
                try:
                    proj = _project_for_session(real, sw.load_projects(sid), _world(sid))
                except Exception:
                    proj = None
            if proj is not None and actor == "brain" and str(getattr(proj, "phase", "")) not in ("done", "paused"):
                # İŞİ VAR (planned/planning/idea): beyin kapatamaz. Bitti ise faz done/paused yapılır; kalan iş sahip
                # kararıysa steward_ask_user ile sahibe SORULUR (sorusuz "sahipte" demek kapatma gerekçesi değil).
                res = {"ok": False, "error": f"{proj.name} faz '{proj.phase}': işi var, kapatılamaz. Bitti ise önce "
                       "steward_set_project phase=done|paused; kalan iş sahip kararıysa steward_ask_user ile sor."}
            elif proj is not None:
                # Kayıtlı proje oturumu: GÜM diye öldürme YOK (beyin ya da insan fark etmez). Önce devir, READY FOR HANDOVER
                # gelince motor kapatır (`ho_close`). Zorla kapatmak için `force` (yalnız insan).
                res = _local_handover(name, sid, cfg.lang)
                if res.get("ok"):
                    with sw.steward_lock(sid):
                        state = sw.load_state(sid)
                        state.setdefault("ho_pending", {})[real] = time.time()
                        state.setdefault("ho_close", {})[real] = proj.name
                        sw.save_state(state, sid)
                    res = dict(res, note="devir gönderildi; devir bitince oturum kapanır (anında öldürülmedi)")
            else:
                res = _act("stop", real, lang=cfg.lang)
    sw.log_event("stop", paths=sid, name=name, reason=str(data.get("reason") or ""), ok=bool(res.get("ok")),
                 **({"host": host} if host else {}))
    if res.get("ok") and str(data.get("actor") or "") == "brain":
        # beyin durdurdu: cadence bu projeyi `BRAIN_STOP_COOLDOWN_SECONDS` boyunca yeniden açmaz (faz değişmez)
        with sw.steward_lock(sid):
            state = sw.load_state(sid)
            bs = {k: v for k, v in dict(state.get("brain_stopped") or {}).items()
                  if time.time() - float(v or 0.0) < sw.BRAIN_STOP_COOLDOWN_SECONDS}
            bs[name] = time.time()
            state["brain_stopped"] = bs
            sw.save_state(state, sid)
    return res


def human_stop_with_ho(name: str, sid: str = "default") -> Optional[Dict[str, Any]]:
    """Panel Durdur (`/api/stop`, insan): değnekçi AÇIK (act) ve oturum kayıtlı yerel proje oturumuysa GÜM diye öldürme
    YOK, önce devir (`http_stop` yolu: ho_pending + ho_close). Uygulanmazsa (kapalı/observe, kayıtsız ya da uzak oturum,
    beyin) None: çağıran düz `_stop`a düşer. Ho'suz zorla kapatma: istekte `force` (çağıran bu fonksiyonu hiç çağırmaz)."""
    try:
        cfg = steward_config(sid)
        if not (cfg.enabled and cfg.mode == "act") or _name_host(name):
            return None
        real = _resolved_local_name(name, sid)
        if real == cfg.brain_name:
            return None
        proj = _project_for_session(real, sw.load_projects(sid), _world(sid))
        if proj is None:
            return None
        return http_stop({"name": name, "actor": "human", "reason": "panel"}, sid)
    except Exception:
        return None


def http_handover(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    cfg = steward_config(sid)
    gated = _gate(name, data, "handover", sid)
    if gated is not None:
        return gated
    host = _name_host(name)      # `_gate` istekteki host'u projeninkiyle zaten eşledi
    with _ctx(sid).lock:
        res = (_remote_handover(name, host, sid=sid, actor=str(data.get("actor") or "")) if host
               else _local_handover(name, sid, cfg.lang))
        if res.get("ok"):
            with sw.steward_lock(sid):
                state = sw.load_state(sid)
                # uzak: iz oturumun GERÇEK adıyla (plan_tick görünüm adıyla okur; `oiso` → `oiso20261017`)
                state.setdefault("ho_pending", {})[str(res.get("name") or name) if host
                                                    else _resolved_local_name(name, sid)] = time.time()
                sw.save_state(state, sid)
    # oturumun GERÇEK adı (sid'li, ör. `oiso20261017`): log'daki devrin eski mi yeni oturum mu olduğu ayırt edilsin
    sess = str(res.get("name") or "") or name
    sw.log_event("handover", paths=sid, name=name, session=sess, ok=bool(res.get("ok")),
                 **({"host": host} if host else {}))
    return res


def http_skip(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    sw.log_event("skip", paths=sid, name=name, reason=str(data.get("reason") or ""))
    with sw.steward_lock(sid):
        state = sw.load_state(sid)
        lda = state.setdefault("last_directive_at", {})
        for key in {name, _resolved_local_name(name, sid)}:     # `idle` oturum adıyla okur (proje adı tarihli oturumda tutmaz)
            lda[key] = time.time()                                # bir sonraki `idle` maddesini erteler
        sig = (state.get("tour_sig") or {}).get(name)
        if sig:       # durumu değişmedikçe bu oturum maddesi 6 saat tura girmez (TBD#122)
            state.setdefault("skip_seen", {})[name] = {"at": time.time(), "sig": sig}
        sw.save_state(state, sid)
    return {"ok": True}


# Panelden yazılabilen ayarlar (CLI `steward config` alt kümesi): alan -> (alt, üst) sınır. `mode` ayrıca doğrulanır.
UI_CONFIG_INT = {"tick_seconds": (15, 3600), "tour_minutes": (1, 1440), "tour_retry_minutes": (1, 1440),
                 "idle_minutes": (1, 1440), "review_minutes": (1, 10080), "stop_idle_minutes": (1, 10080),
                 "max_active": (0, 20), "max_starts_per_tick": (0, 10), "review_auto_approve": (0, 3),
                 # "neden ilerlemiyor" kuralları (11 Kas 2026): boşta dürtme eşiği/hakkı + makine geneli başlatma sınırı (0 = başlatma yok)
                 "claude_idle_nudge_secs": (0, 86400), "ucli_idle_max_consecutive": (0, 20), "max_starts_total": (0, 10),
                 # Evren/ucli reviewer bütçeleri (2026-11-04): 0 = ucli modelin /models kaydından türetir; ucli üst sınırı 1536 KiB
                 "review_max_context_kib": (0, 1536), "review_max_read_kib": (0, 1024), "review_max_tool_calls": (1, 500)}


UI_CONFIG_BOOL = ("drain", "review_auto_verify", "review_store_commit", "review_auto_export", "auto_start")

# Seçenek listeli metin ayarlar. `review_evren_script` kapatma değeri "off" (boş değer anahtarı SİLER, varsayılan "read" geri gelir).
UI_CONFIG_CHOICE = {"claude_idle": ("off", "dry", "act"), "keepwarm": ("off", "dry", "act"), "wake_gate": ("off", "dry", "act"),
                    "review_evren_script": ("read", "off"), "review_verify_mode": ("session", "self"),
                    # boş değer = claude (save_settings anahtarı siler)
                    "review_verify_provider": ("", "claude", "codex", "evren", "agy")}

# Serbest metin reviewer ayarları (panel Reviewer formu, 2026-11-08): boş değer anahtarı SİLER = varsayılan
# (yuvalar: TEK iş kipi; model listeleri: katalogdaki tümü). Model listesi virgüllü, dar karakter kümesi.
UI_CONFIG_MODEL_LISTS = ("review_agy_models", "review_evren_models", "review_verify_model")
_MODEL_LIST_RE = re.compile(r"^[A-Za-z0-9_.:/@\[\]-]{1,120}$")


def _normalize_review_slots(value: Any) -> Optional[str]:
    """`review_slots` metni -> kanonik `mod=n,...` (ya da "" / "off"); bozuk/bilinmeyen modda None."""
    from .. import review as rv
    t = str(value or "").strip().lower().replace(" ", "")
    if t in ("", "off"):
        return t
    out = []
    for part in t.split(","):
        k, sep, v = part.partition("=")
        if not sep or k not in rv.MODES or not v.isdigit() or int(v) > 10:
            return None
        out.append(f"{k}={int(v)}")
    return ",".join(out)


def _normalize_model_list(value: Any) -> Optional[str]:
    items = [x.strip() for x in str(value or "").split(",") if x.strip()]
    if len(items) > 40 or any(not _MODEL_LIST_RE.match(x) for x in items):
        return None
    return ",".join(dict.fromkeys(items))


def http_config(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Panelden `steward.<alan>` (ya da `stewards.<sid>.<alan>`) ayarı; CLI `config` ile aynı kurallar, dar alan listesi."""
    if data.get("actor") == "brain":
        return {"ok": False, "error": "brain cannot change steward settings"}
    from ..settings import save_settings
    field = str(data.get("key") or "")
    value = data.get("value")
    if field == "mode":
        if value not in sw.MODES:
            return {"ok": False, "error": "mode must be one of " + ", ".join(sw.MODES)}
    elif field == "brain_model":
        # beyin modeli (TBD sonrası kalem): serbest metin ama dar karakter kümesi; boş = "otomatik" (save_settings anahtarı siler).
        # Çalışan beyni YENİDEN AÇMAZ: sonraki açılış/devir `cfg.brain_model`i okur.
        value = str(value or "").strip()
        if not re.match(r"^[A-Za-z0-9_.:/@\[\]-]{0,80}$", value):
            return {"ok": False, "error": "brain_model has invalid characters"}
    elif field == "brain_effort":
        value = str(value or "").strip().lower()
        if value not in ("", "low", "medium", "high", "xhigh", "max"):
            return {"ok": False, "error": "brain_effort must be one of low, medium, high, xhigh, max (or empty)"}
    elif field in UI_CONFIG_BOOL:
        value = "on" if str(value).strip().lower() in ("on", "1", "true", "yes") else "off"
    elif field in UI_CONFIG_CHOICE:
        value = str(value or "").strip().lower()
        if value not in UI_CONFIG_CHOICE[field]:
            return {"ok": False, "error": f"{field} must be one of " + ", ".join(UI_CONFIG_CHOICE[field])}
    elif field == "review_slots":
        value = _normalize_review_slots(value)
        if value is None:
            return {"ok": False, "error": "review_slots must look like agy=2,evren=1,codex=0 (modes: agy, evren, claude, codex, copilot, anthropic; 0..10) or off/empty"}
    elif field in UI_CONFIG_MODEL_LISTS:
        value = _normalize_model_list(value)
        if field == "review_verify_model" and value and "," in value:
            return {"ok": False, "error": "review_verify_model takes a single model"}
        if value is None:
            return {"ok": False, "error": f"{field} must be a comma-separated model list (letters, digits, . _ - : / @ [ ])"}
    elif field in UI_CONFIG_INT:
        try:
            n = int(value)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"{field} must be an integer"}
        lo, hi = UI_CONFIG_INT[field]
        if not lo <= n <= hi:
            return {"ok": False, "error": f"{field} must be {lo}..{hi}"}
        value = n
    else:
        return {"ok": False, "error": "unknown or not editable field: " + field}
    if sid != "default" and field in sw.MACHINE_KEYS:
        return {"ok": False, "error": f"{field} is machine-wide: set it on the default steward"}
    save_settings({"steward": {field: value}} if sid == "default" else {"stewards": {sid: {field: value}}})
    sw.log_event("config", paths=sid, key=field, value=value, source="ui")
    return {"ok": True, "key": field, "value": getattr(steward_config(sid), field)}


def http_quota() -> Dict[str, Any]:
    """Kota bekçisi (TBD#116) ayarı + son okuma/karar (CLI `steward quota status` ile aynı kaynak). Makine geneli: kimlik seçmez."""
    st: Any = None
    try:
        from .. import statedocs
        st = statedocs.read_json("steward/quota", QUOTA_FILE, None)
    except (OSError, ValueError):
        st = None
    return {"ok": True, "config": dict(quota_config()), "modes": list(sq.MODES), "days": list(sq.DAYS),
            "state": st if isinstance(st, dict) else None}


_QUOTA_NUM_KEYS = {"manual_limit": (0, 100), "shutdown_limit": (0, 100), "final_limit": (0, 100), "budget_pct": (0, 100), "poll_minutes": (1, 1440)}


def http_quota_set(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Panelden kota ayarı (CLI `steward quota mode|limit|shutdown|final|poll|day` ile aynı kurallar). YALNIZ insan (`brain` reddedilir).
    `key`: mode | budget_pct (0 = kapalı) | manual_limit | shutdown_limit | final_limit | poll_minutes | day_<mon..sun>; gün değeri boşsa o günün tavanı silinir."""
    if (d := _human_only(data, "change quota settings")):
        return d
    from ..settings import save_settings
    key = str(data.get("key") or "")
    value = data.get("value")
    if key == "mode":
        if value not in sq.MODES:
            return {"ok": False, "error": "mode must be one of " + ", ".join(sq.MODES)}
        if not data.get("confirm") and sq.enable_needs_confirm(quota_config(), str(value)):
            return {"ok": False, "needs_confirm": True,
                    "error": f"final threshold is above {sq.ENABLE_CONFIRM_ABOVE:g}%: the guard would barely act; "
                             "resend with confirm=true to enable anyway"}
    elif key in _QUOTA_NUM_KEYS or (key.startswith("day_") and key[4:] in sq.DAYS):
        lo, hi = _QUOTA_NUM_KEYS.get(key, (0, 100))
        if key.startswith("day_") and (value is None or str(value).strip() == ""):
            value = ""      # boş = o günün tavanını sil (save_settings boş değeri anahtarı siler)
        else:
            try:
                n = float(value)
            except (TypeError, ValueError):
                return {"ok": False, "error": f"{key} must be a number"}
            if isinstance(value, bool) or not lo <= n <= hi:
                return {"ok": False, "error": f"{key} must be {lo}..{hi}"}
            value = str(int(n)) if n == int(n) else str(n)
    else:
        return {"ok": False, "error": "unknown or not editable field: " + key}
    save_settings({"steward_quota": {key: value}})
    sw.log_event("config", paths=sid, key="quota." + key, value=value, source="ui")
    return {"ok": True, "key": key, "value": value, "config": dict(quota_config())}


def loop_guard_list(sid: str = "default") -> List[Dict[str, Any]]:
    """`state.loop_guard` panel listesi (yalnız duraklatılmış / eşiğe yaklaşan): her (tür|hedef) için sayaç `n`/`max`, ilk görülme ve (duraklatıldıysa) bitiş saati."""
    st = sw.load_state(sid)
    now = time.time()
    out = []
    for key, r in sorted(dict(st.get("loop_guard") or {}).items()):
        if not isinstance(r, dict):
            continue
        kind, _, name = key.partition("|")
        until = float(r.get("until") or 0.0)
        if until <= now and int(r.get("n") or 0) < sw.LOOP_MAX // 2:
            continue        # her eylemin n=1 sayacı gürültü: yalnız duraklatılmış ya da eşiğe yaklaşan (n >= MAX/2) görünür
        out.append({"key": key, "kind": kind, "name": name, "n": int(r.get("n") or 0), "max": sw.LOOP_MAX,
                    "first": float(r.get("first") or 0.0), "until": until, "paused": until > now})
    return out


def http_loop_reset(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Döngü korumasını sıfırla (panel "sıfırla"): `key` (`tür|hedef`) ya da boşsa HEPSİ. YALNIZ insan. Olay `loop_guard_reset`."""
    if (d := _human_only(data, "reset the loop guard")):
        return d
    key = str(data.get("key") or "")
    with sw.steward_lock(sid):
        st = sw.load_state(sid)
        guard = dict(st.get("loop_guard") or {})
        gone = [k for k in guard if not key or k == key]
        if key and not gone:
            return {"ok": False, "error": f"no loop guard entry: {key}"}
        for k in gone:
            guard.pop(k, None)
        if guard:
            st["loop_guard"] = guard
        else:
            st.pop("loop_guard", None)
        sw.save_state(st, sid)
    sw.log_event("loop_guard_reset", paths=sid, keys=gone, source="ui")
    return {"ok": True, "cleared": gone}


def http_enable(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Döngüyü aç/kapat (CLI `steward on|off`)."""
    if data.get("actor") == "brain":
        return {"ok": False, "error": "brain cannot enable or disable the steward"}
    from ..settings import save_settings
    on = bool(data.get("enabled"))
    save_settings({"steward": {"enabled": "on" if on else "off"}} if sid == "default"
                  else {"stewards": {sid: {"enabled": "on" if on else "off"}}})
    sw.log_event("enable" if on else "disable", paths=sid, source="ui")
    return {"ok": True, "enabled": on}


def http_up(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Tek adımda aç (CLI `steward up`): döngüyü aç + projelerin `# CLOSED` models.tsv satırlarını geri aç + beyni başlat.
    `no_brain` beyni atlar. YALNIZ insan (beyin kendini açamaz)."""
    if (d := _human_only(data, "start the steward")):
        return d
    from ..settings import save_settings
    from . import close as close_cmd
    save_settings({"steward": {"enabled": "on"}} if sid == "default" else {"stewards": {sid: {"enabled": "on"}}})
    sw.log_event("enable", paths=sid, source="ui_up")
    restored = [n for n in sorted(sw.load_projects(sid)) if close_cmd.uncomment_models(n) == "restored"]
    brain: Dict[str, Any] = {}
    if not data.get("no_brain"):
        with _ctx(sid).lock:
            brain = brain_start(steward_config(sid))
    return {"ok": True, "restored": restored, "brain": brain}


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
        job = lambda: refresh_due_cards(cfg, limit=10 ** 6, remote_limit=10 ** 6, remote_budget=600.0)   # noqa: E731
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


DIGEST_LIST_MAX = 60
DIGEST_FILE_MAX = 256 * 1024
_DIGEST_NAME_RES = {"daily": re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$"), "tours": re.compile(r"^tour-(\d{1,12})\.md$")}


def _digest_dir(kind: str, sid: str) -> Optional[str]:
    paths = sw.paths_for(sid)
    return paths.daily if kind == "daily" else os.path.join(paths.workspace, "tours") if kind == "tours" else None


def http_digests(sid: str = "default") -> Dict[str, Any]:
    """Panel: günlük özet (`daily/<tarih>.md`) ve beyne giden uzun tur (`workspace/tours/tour-<ts>.md`) dosyaları, yeni -> eski,
    her biri en çok 60. Salt okunur; reviewer kimliğinde boş."""
    out: Dict[str, Any] = {"ok": True, "daily": [], "tours": []}
    if sid != "default" and steward_config(sid).role == "reviewer":
        return out
    for kind in ("daily", "tours"):
        d = _digest_dir(kind, sid)
        rx = _DIGEST_NAME_RES[kind]
        rows = []
        try:
            names = os.listdir(d) if d and os.path.isdir(d) else []
        except OSError:
            names = []
        for name in names:
            m = rx.match(name)
            fp = os.path.join(d, name)
            if not m or os.path.islink(fp) or not os.path.isfile(fp):
                continue
            try:
                st = os.stat(fp)
            except OSError:
                continue
            row = {"file": name, "size": st.st_size, "mtime": st.st_mtime}
            if kind == "daily":
                row["date"] = m.group(1)
                key = m.group(1)
            else:
                row["ts"] = int(m.group(1))
                key = "%020d" % row["ts"]
            rows.append((key, row))
        rows.sort(key=lambda x: x[0], reverse=True)
        out[kind] = [r for _, r in rows[:DIGEST_LIST_MAX]]
    return out


def http_digest_file(kind: str, name: str, sid: str = "default") -> Dict[str, Any]:
    """Tek özet/tur dosyası metni (<=256 KiB, sırlar maskeli). Ad yalnız beklenen desende olmalı; symlink/`..` reddedilir."""
    rx = _DIGEST_NAME_RES.get(kind)
    if rx is None or not rx.match(name or ""):
        return {"ok": False, "error": "bad digest name"}
    if sid != "default" and steward_config(sid).role == "reviewer":
        return {"ok": False, "error": "not found"}
    d = _digest_dir(kind, sid)
    fp = os.path.join(d, name)
    try:
        if os.path.islink(fp) or not os.path.isfile(fp) or os.path.realpath(os.path.dirname(fp)) != os.path.realpath(d):
            return {"ok": False, "error": "not found"}
        with open(fp, "rb") as f:
            raw = f.read(DIGEST_FILE_MAX + 1)
    except OSError:
        return {"ok": False, "error": "not found"}
    truncated = len(raw) > DIGEST_FILE_MAX
    text = raw[:DIGEST_FILE_MAX].decode("utf-8", "replace")
    return {"ok": True, "text": rv.redact_secrets(text), "truncated": truncated}


_GET_PATHS = frozenset(("review/state", "review/file", "review/live", "review/io", "review/chat", "review/runs", "review/findings", "review/lessons", "state", "projects", "questions", "ideas", "log", "context", "summary", "cards", "card", "file", "list",
                        "jobs", "services", "digests", "digest/file", "quota"))


def http_get(path: str, qs: Dict[str, List[str]]) -> Optional[Dict[str, Any]]:
    """`web.py` do_GET: `/api/steward/*` → dict (bilinmeyen alt yol → None = 404). `?steward=<sid>` kimliği seçer
    (yoksa `default`); bilinmeyen kimlik `{"ok": false, "error": "unknown steward"}`."""
    g = lambda k, d="": (qs.get(k) or [d])[0]
    if not path.startswith("/api/steward/") or path[len("/api/steward/"):] not in _GET_PATHS:
        return None
    if path == "/api/steward/list":
        return http_list()
    if path == "/api/steward/services":
        return http_services()
    if path == "/api/steward/quota":
        return http_quota()
    if path == "/api/steward/review/runs":
        return http_review_runs()
    try:
        sid = _ctx_for(qs).sid
    except UnknownSteward:
        return _unknown_steward()
    if path == "/api/steward/review/state":
        return http_review_state(sid)
    if path == "/api/steward/review/file":
        return http_review_file(g("path"), sid)
    if path == "/api/steward/review/live":
        return http_review_live(g("project").strip(), g("target").strip(), g("offset", "0"), sid)
    if path == "/api/steward/review/chat":
        return http_review_chat(g("path"), sid)
    if path == "/api/steward/review/io":
        return http_review_io(g("path"), g("offset", "0"), sid)
    if path == "/api/steward/review/findings":
        return http_review_findings(g("project").strip(), g("state").strip(), sid)
    if path == "/api/steward/review/lessons":
        return http_review_lessons(sid)
    if path == "/api/steward/review/models":
        return http_review_models(sid)
    if path == "/api/steward/digests":
        return http_digests(sid)
    if path == "/api/steward/digest/file":
        return http_digest_file(g("kind").strip(), g("name").strip(), sid)
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


def _human_only(data: Dict[str, Any], what: str) -> Optional[Dict[str, Any]]:
    return {"ok": False, "error": f"brain cannot {what}"} if data.get("actor") == "brain" else None


def http_identity_create(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Yeni kimlik (CLI `steward create`): KAPALI + observe. Kimlik adı `target` alanında (`steward` alanı MEVCUT kimliği seçer)."""
    if (d := _human_only(data, "create a steward")):
        return d
    from ..settings import save_settings
    new = str(data.get("target") or "").strip()
    if not sw.valid_custom_id(new):
        return {"ok": False, "error": f"invalid steward id {new!r}: ^[a-z]{{2,16}}$, not reserved, not 'degnekci*'"}
    if new in steward_ids():
        return {"ok": False, "error": f"steward {new!r} already exists"}
    label = str(data.get("label") or "")
    role = str(data.get("role") or "steward").strip()
    if role not in sw.ROLES:
        return {"ok": False, "error": f"invalid role {role!r}: one of {', '.join(sw.ROLES)}"}
    block = {"label": label, "enabled": "off", "mode": "observe"}
    if role != "steward":
        block["role"] = role        # rol YALNIZ yaratılırken verilir (config ile değişmez)
    save_settings({"stewards": {new: block}})
    os.makedirs(sw.paths_for(new).root, exist_ok=True)
    sw.log_event("create", paths=new, label=label, role=role, source="ui")
    return {"ok": True, "id": new, "role": role}


def http_identity_remove(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Kimliği sil (CLI `steward remove`): `default` silinmez; projesi ya da çalışan beyni varsa reddedilir. Dizin `.removed/`a taşınır."""
    if (d := _human_only(data, "remove a steward")):
        return d
    from ..settings import save_settings
    target = str(data.get("target") or "").strip()
    if target == "default":
        return {"ok": False, "error": "'default' cannot be removed"}
    if target not in steward_ids():
        return {"ok": False, "error": f"unknown steward {target!r}"}
    brain = sw.brain_name_for(target)
    if _running(brain) is not None:
        return {"ok": False, "error": f"brain session {brain!r} is running; stop it first"}
    jobs = web_review.running_keys(target)
    if jobs:      # reviewer'ın çalışan review işi var: dizin taşınırsa koşu rapor/IO dosyasını yitirir
        return {"ok": False, "error": f"steward {target!r} has a running review ({', '.join(jobs[:4])}); cancel it first"}
    with sw.ownership_lock():
        names = sorted(sw.load_projects(target))
        if names:
            return {"ok": False, "error": f"steward {target!r} still has projects: {', '.join(names[:8])}; transfer them first"}
        root = sw.paths_for(target).root
        dest = ""
        if os.path.isdir(root):
            dest = os.path.join(os.path.dirname(root), ".removed", f"{target}-{time.strftime('%Y%m%d_%H%M%S')}")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(root, dest)
    save_settings({"stewards": {target: None}})
    sw.log_event("remove", paths="default", target=target, source="ui")
    return {"ok": True, "removed": target, "dir": dest}


def http_identity_transfer(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Projeyi başka kimliğe devret (CLI `steward transfer`): oturum çalışıyorsa reddedilir (`force` ile geçilir)."""
    if (d := _human_only(data, "transfer a project")):
        return d
    name = str(data.get("project") or "").strip()
    to = str(data.get("to") or "").strip()
    if not name or to not in steward_ids():
        return {"ok": False, "error": f"project and a known target steward required (known: {', '.join(steward_ids())})"}
    if not data.get("force"):
        src = sw.project_owner(name)
        projects = sw.load_projects(src) if src else {}
        for s in find_sessions(measure_cpu=False):
            p = _project_for_session(s.name, projects) if projects else None
            if (p is not None and p.name == name) or s.name == name:
                return {"ok": False, "error": f"session {s.name!r} is running; stop it first", "running": s.name}
    try:
        src = sw.transfer_project(name, to)
    except (ValueError, sw.LockTimeout) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "project": name, "from": src, "to": to}


def http_services() -> Dict[str, Any]:
    """Kayıtlı pasif servisler (makine geneli). Token ASLA dönmez: yalnız dosya yolu + uyarı. `open_jobs`: TÜM kimliklerin açık işleri."""
    open_by: Dict[str, int] = {}
    for k in steward_ids():
        for j in sj.load_jobs(sw.paths_for(k)):
            if sj.is_open(j):
                open_by[str(j.get("service") or "")] = open_by.get(str(j.get("service") or ""), 0) + 1
    rows = []
    for n, r in sorted(sj.load_services().items()):
        tf = sj.token_file_path(r)
        rows.append({"name": n, "url": r.get("url", ""), "match": r.get("match") or "prefix", "label": r.get("label") or n,
                     "token_file": tf, "token_present": bool(tf) and os.path.isfile(tf),
                     "token_warning": sj.token_file_warning(tf) if tf else "", "open_jobs": open_by.get(n, 0),
                     "default": n == sj.default_service()})
    return {"ok": True, "services": rows}


def http_service_add(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Servis ekle (CLI `steward service add`): makine geneli, YALNIZ insan. Token değeri alınmaz, yalnız dosya yolu."""
    if (d := _human_only(data, "register a service")):
        return d
    try:
        rec = sj.add_service(str(data.get("name") or ""), str(data.get("url") or ""), str(data.get("token_file") or ""),
                             str(data.get("match") or "prefix"), str(data.get("label") or ""))
    except (ValueError, sw.LockTimeout) as e:
        return {"ok": False, "error": str(e)}
    sw.log_event("service_add", paths="default", name=str(data.get("name") or ""), source="ui")
    tf = sj.token_file_path(rec)
    return {"ok": True, "warning": sj.token_file_warning(tf) if tf else ""}


def http_service_rm(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Servis sil: HERHANGİ bir kimlikte açık işi varsa reddedilir (sonuç iletimi kopardı)."""
    if (d := _human_only(data, "remove a service")):
        return d
    name = str(data.get("name") or "").strip()
    open_n = next((r["open_jobs"] for r in http_services()["services"] if r["name"] == name), 0)
    if open_n:
        return {"ok": False, "error": f"service {name!r} has {open_n} open job(s); wait for them to finish"}
    try:
        ok = sj.remove_service(name)
    except sw.LockTimeout as e:
        return {"ok": False, "error": str(e)}
    if ok:
        sw.log_event("service_rm", paths="default", name=name, source="ui")
    return {"ok": ok} if ok else {"ok": False, "error": f"service {name!r} is not registered"}


def http_job_ack(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Bitmiş işi iletildi say (CLI `steward jobs ack`): yerel işaret, varaka'ya yazılmaz; açık işe REDDEDİLİR."""
    if (d := _human_only(data, "ack a job")):
        return d
    j = sj.find_job(sj.load_jobs(sid), str(data.get("id") or ""), str(data.get("service") or ""))
    if j is None:
        return {"ok": False, "error": "job not found"}
    if j.get("state") not in sj.TERMINAL_STATES:
        return {"ok": False, "error": f"job is still open ({j.get('state') or '?'})"}
    sj.mark_delivered(j["id"], j.get("service") or "", "result", paths=sid)
    return {"ok": True}


def _reviewer_cfg(sid: str) -> Tuple[Optional[sw.Config], Optional[Dict[str, Any]]]:
    cfg = steward_config(sid)
    if sid == "default" or cfg.role != "reviewer":
        return None, {"ok": False, "error": f"steward {sid} is not a reviewer"}
    return cfg, None


def http_review_state(sid: str = "default") -> Dict[str, Any]:
    cfg, err = _reviewer_cfg(sid)
    return err or web_review.review_state(cfg)


def http_review_file(rel: str, sid: str = "default") -> Dict[str, Any]:
    cfg, err = _reviewer_cfg(sid)
    return err or web_review.read_review_file(cfg, rel)


def http_review_live(project: str, target: str, offset: str = "0", sid: str = "default") -> Dict[str, Any]:
    cfg, err = _reviewer_cfg(sid)
    return err or web_review.read_live(cfg, project, target, offset)


def http_review_runs() -> Dict[str, Any]:
    """History için: TÜM reviewer kimliklerinin koşuları (kimlik başına `review_runs`)."""
    rows: List[Dict[str, Any]] = []
    for sid in sorted(sw.reviewer_ids()):
        try:
            cfg, err = _reviewer_cfg(sid)
            if cfg is not None:
                rows.extend(web_review.review_runs(cfg))
        except Exception:
            continue
    return {"ok": True, "runs": rows}


def http_review_chat(rel: str, sid: str = "default") -> Dict[str, Any]:
    cfg, err = _reviewer_cfg(sid)
    return err or web_review.read_chat(cfg, rel)


def http_review_io(rel: str, offset: str = "0", sid: str = "default") -> Dict[str, Any]:
    cfg, err = _reviewer_cfg(sid)
    return err or web_review.read_io(cfg, rel, offset)


def http_review_findings(project: str = "", state: str = "", sid: str = "default") -> Dict[str, Any]:
    cfg, err = _reviewer_cfg(sid)
    return err or web_review.list_findings(cfg, project, state)


def http_review_lessons(sid: str = "default") -> Dict[str, Any]:
    """Reviewer'ın ucli dersleri ve iletim durumu (pending|failed|sent|stale|done). Alıcı kimlikler `lessons_project` ayarı
    olan TÜM kimlikler; ders bir alıcının state'inde gönderilmiş görünür."""
    cfg, err = _reviewer_cfg(sid)
    if err:
        return err
    try:
        lessons = sl.read_lessons([sw.paths_for(i).root for i in sorted(sw.reviewer_ids())])
        states = [sw.load_state(sw.paths_for(i)) for i in steward_ids()]
    except Exception as e:
        return {"ok": False, "error": str(e)}
    projects = sorted({sl.target_project(steward_config(i).lessons_project) for i in steward_ids()} - {""})
    return {"ok": True, "lessons": sl.lesson_rows(lessons, states, time.time()), "target": projects[0] if projects else ""}


def http_review_lesson(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Dersi yeniden iletilebilir yap (`action: resend`): gönderildi/başarısız/onay kayıtları silinir, sonraki tick'te
    yeniden gider. Yalnız insan."""
    if (d := _human_only(data, "resend a lesson")):
        return d
    cfg, err = _reviewer_cfg(sid)
    if err:
        return err
    hid = str(data.get("id") or "").strip().lower()
    if str(data.get("action") or "") != "resend" or len(hid) != 12:
        return {"ok": False, "error": "action=resend and 12-char id required"}
    n = 0
    for i in steward_ids():
        if sl.resend(hid, sw.paths_for(i)):
            n += 1
    sw.log_event("lesson_resend", paths=sw.paths_for(sid), id=hid, n=n)
    return {"ok": True, "resent": n}


def http_review_pool(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Havuz: add|remove|enable|disable|focus|unfocus (CLI `review pool ...`); yalnız insan."""
    if (d := _human_only(data, "change the review pool")):
        return d
    cfg, err = _reviewer_cfg(sid)
    if err:
        return err
    r = web_review.pool_action(cfg, str(data.get("action") or ""), str(data.get("project") or ""))
    if r.get("ok"):
        sw.log_event("review_pool", paths=sid, action=r.get("action"), project=r.get("project"), source="ui")
    return r


def http_review_where(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Uzak projenin review yeri: ask|local|remote|off (+ `local_path`); yalnız insan."""
    if (d := _human_only(data, "change a project's review location")):
        return d
    return web_review.set_where(str(data.get("project") or ""), str(data.get("where") or ""), str(data.get("local_path") or ""))


def http_review_run(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    if (d := _human_only(data, "start a review")):
        return d
    cfg, err = _reviewer_cfg(sid)
    if err:
        return err
    r = web_review.manual_run(cfg, str(data.get("project") or ""), str(data.get("mode") or ""), str(data.get("model") or ""),
                          str(data.get("lens") or ""))
    if r.get("ok"):
        sw.log_event("review_run", paths=sid, project=data.get("project"), key=r.get("key"), source="ui")
    return r


def http_review_cancel(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    if (d := _human_only(data, "cancel a review")):
        return d
    cfg, err = _reviewer_cfg(sid)
    if err:
        return err
    r = web_review.cancel_action(cfg, str(data.get("project") or ""))
    sw.log_event("review_cancel", paths=sid, project=data.get("project") or "*", cancelled=r["cancelled"], source="ui")
    return r


def _owner_project_views(project: str) -> Tuple[str, List[sw.SessionView], Optional[Dict[str, Any]]]:
    """Reviewer bulgu akışı için projenin SAHİBİNİN yerel çalışan oturum görünümleri (yalnız okuma: `_collect_views`,
    `_target`tan GEÇMEZ, hiçbir şey göndermez). (sahip kimliği, görünümler, hata)."""
    idx = _ownership_index()
    owner = (idx.get("owners") or {}).get(project) or ""
    if not owner:
        return "", [], {"ok": False, "error": f"project {project!r} has no (unique) owner steward", "code": "no_owner"}
    if project in (idx.get("hosts") or {}):
        return owner, [], {"ok": False, "error": "remote projects are not reviewed (v1)", "code": "remote"}
    ocfg = steward_config(owner)
    projects = sw.load_projects(owner)
    world = _world(owner, ocfg)
    out = []
    for v in _collect_views(ocfg):
        if not v.running or sw.normalize_host(v.host):
            continue
        q = _project_for_session(v.name, projects, world)
        if q is not None and q.name == project:
            out.append(v)
    return owner, out, None


def _review_verdict_reader(project: str) -> Optional[Tuple[str, str]]:
    """`web_review.process_verdicts` okuyucusu: sahibin TEK çalışan oturumunun son asistan metni (yoksa/çoksa None)."""
    _owner, views, err = _owner_project_views(project)
    if err is not None or len(views) != 1:
        return None
    return views[0].name, views[0].last_assistant or ""


def http_review_verify(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Bulguları projenin kendi oturumuna doğrulat (CLI `review verify PROJE`): sahibin kimliği üzerinden, İNSAN aktörüyle
    `http_directive` (oturum kapalıysa AÇILMAZ, açık hata). Oturum meşgul / alt ajanı çalışıyor / az önce direktif aldıysa
    gönderilmez (`session_busy`). Gönderilince bulgular `verify_sent`; karar reviewer tick'inde okunur."""
    if (d := _human_only(data, "send a review verification")):
        return d
    cfg, err = _reviewer_cfg(sid)
    if err:
        return err
    project = str(data.get("project") or "").strip()
    if not sw.valid_name(project):
        return {"ok": False, "error": "invalid project name"}
    fids = data.get("fids")
    fids = [str(x) for x in fids] if isinstance(fids, list) else []
    rows = web_review.verify_candidates(cfg, project, fids or None)
    if not rows:
        return {"ok": False, "error": "no findings to verify (state new, or given ids in new|verify_sent|unclear)"}
    rhost = (_ownership_index().get("hosts") or {}).get(project) or ""
    if rhost:     # uzak proje: yerel klasör yok, doğrulama projenin KENDİ host'undaki oturumunda (aç -> sor -> oku -> kapat)
        return web_review.remote_verify(cfg, project, rhost, rows)
    if cfg.review_verify_mode == "self":     # TBD#137 a=A: reviewer'ın kendi salt-okunur süreci; proje oturumu uyanmaz
        return web_review.self_verify(cfg, project, rows)
    owner, views, oerr = _owner_project_views(project)
    if oerr is not None:
        return oerr
    if not views:
        return {"ok": False, "code": "not_running",
                "error": f"project {project!r} has no running session: verification NOT sent (open the session first)"}
    if len(views) > 1:
        return {"ok": False, "code": "ambiguous_sessions", "error": "ambiguous_sessions", "sessions": [v.name for v in views]}
    v = views[0]
    lda = sw.load_state(sw.paths_for(owner)).get("last_directive_at") or {}
    why = "subagent_active" if v.subagent_active else sw.directive_defer_reason(v.busy, float(lda.get(v.name) or 0.0),
                                                                                  time.time())
    if why:
        sw.log_event("review_verify_deferred", paths=sid, project=project, session=v.name, reason=why)
        return {"ok": False, "code": "session_busy", "error": f"session_busy ({why}): verification not sent; try again later"}
    msg = rv.build_verify_message(rows, steward_config(owner).lang)
    res = http_directive({"name": v.name, "text": msg, "start_if_stopped": False, "reason": "review_verify"}, sid=owner)
    if not res.get("ok"):
        return dict(res, ok=False)
    marked = rv.mark_verify_sent(sw.paths_for(sid), [r["id"] for r in rows], v.name, rv.text_hash(v.last_assistant),
                                 time.time())
    sw.log_event("review_verify", paths=sid, project=project, owner=owner, session=v.name, findings=marked, source="ui")
    return {"ok": True, "project": project, "owner": owner, "session": v.name, "findings": marked}


AUTO_VERIFY_STALE_SECONDS = 3600     # bu kadar süredir cevapsız `verify_sent` bulgu projeyi otomatik doğrulamada bloklamaz
AUTO_VERIFY_TRIES = 3                # tick başına en çok bu kadar proje denenir, ilk başarılı gönderimde durulur


def auto_review_verify(cfg: sw.Config, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """`review_auto_verify` açıksa havuzdaki projelerin `new` bulgularını KENDİ oturumlarına doğrulatır (sahibin elle
    Doğrula düğmesiyle aynı yol: `http_review_verify`, oturum AÇILMAZ, meşgulse bekler). Cevap bekleyen (taze
    `verify_sent`) bulgusu olan proje atlanır. Tick başına en çok 1 gönderim. Dönen: {project, ...} ya da None."""
    if not cfg.review_auto_verify:
        return None
    t = time.time() if now is None else now
    p = sw.paths_for(cfg.sid)
    data = rv.load_findings(p)
    enabled = set(rv.pool_enabled(rv.load_pool(p)))
    waiting = {str(v.get("project")) for v in data.values()
               if isinstance(v, dict) and v.get("state") == "verify_sent"
               and t - float(v.get("verify_sent_at") or 0) < AUTO_VERIFY_STALE_SECONDS}
    projects = sorted({str(v.get("project")) for v in data.values()
                       if isinstance(v, dict) and v.get("state") == "new" and v.get("project")} & enabled - waiting)
    for proj in projects[:AUTO_VERIFY_TRIES]:
        if web_review.self_verify_running(proj):
            continue
        res = http_review_verify({"project": proj}, sid=cfg.sid)
        if res.get("ok"):
            sw.log_event("review_auto_verify", paths=p, project=proj, session=res.get("session"), findings=res.get("findings"))
            return {"project": proj, "findings": res.get("findings")}
    return None


def http_review_finding(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Sahibin bulgu kararı (CLI `review approve|reject FID`): approve yalnız verified|unclear bulguya."""
    if (d := _human_only(data, "decide on a review finding")):
        return d
    cfg, err = _reviewer_cfg(sid)
    if err:
        return err
    return web_review.decide(cfg, str(data.get("id") or ""), str(data.get("action") or ""))


def http_review_models(sid: str = "default") -> Dict[str, Any]:
    """Model/mod sağlığı (son 7 gün başarı oranı, `limit` koşuları sayılmaz), çıkarma adayları ve dışlananlar; haftalık özet metni."""
    cfg, err = _reviewer_cfg(sid)
    if err:
        return err
    rows = rv.model_health(rv.load_history(sw.paths_for(sid)), time.time())
    excluded = sorted(rv.excluded_keys(cfg))
    return {"ok": True, "models": rows, "excluded": excluded, "digest": rv.health_digest(rows, excluded)}


def http_review_exclude(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Sahip onaylı çıkarma/geri alma (CLI `review exclude|include <mod/model>`): `target` + `action` exclude|include. Yalnız insan;
    `review_excluded` ayarına yazar, havuz sonraki turdan itibaren o hedefi planlamaz (koşan iş sürer)."""
    if (d := _human_only(data, "exclude a review model")):
        return d
    cfg, err = _reviewer_cfg(sid)
    if err:
        return err
    target = str(data.get("target") or "").strip()
    action = str(data.get("action") or "exclude")
    if action not in ("exclude", "include") or not re.match(r"^[A-Za-z0-9_.:@/\-]+$", target) or "/" not in target:
        return {"ok": False, "error": "target must look like mode/model and action exclude|include"}
    from ..settings import save_settings
    new = rv.toggle_excluded(cfg.review_excluded, target, action == "exclude")
    save_settings({"stewards": {sid: {"review_excluded": new}}})     # boş değer anahtarı siler (varsayılan "")
    sw.log_event("config", paths=sid, key="review_excluded", value=new, source="ui", action=action, target=target)
    return {"ok": True, "excluded": [x for x in new.split(",") if x]}


def http_review_bulk(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Toplu bulgu kararı (CLI `review approve-all`, panel "hepsini onayla"): gövde `action` approve|reject, isteğe bağlı
    `project`, `fids`, `severities`. Yalnız insan (beyin çağıramaz)."""
    if (d := _human_only(data, "decide on review findings in bulk")):
        return d
    cfg, err = _reviewer_cfg(sid)
    if err:
        return err
    fids = data.get("fids")
    sev = data.get("severities")
    return web_review.bulk_decide(cfg, str(data.get("action") or ""), str(data.get("project") or ""),
                                  [str(x) for x in fids] if isinstance(fids, list) else None,
                                  [str(x) for x in sev] if isinstance(sev, list) else None)


def http_review_export(data: Dict[str, Any], sid: str = "default") -> Dict[str, Any]:
    """Onaylı bulguları yerel projenin TODO.md / TOBEDECIDED.md dosyasına yaz (CLI `review export PROJE [--kind]`)."""
    if (d := _human_only(data, "export review findings")):
        return d
    cfg, err = _reviewer_cfg(sid)
    if err:
        return err
    kind = str(data.get("kind") or "todo")
    if kind in _REVIEW_UNVERIFIED_FILES:    # rtodo|rtbd: doğrulanmamış (new/unclear) bulgular, türe göre ayrılır
        fname, only = _REVIEW_UNVERIFIED_FILES[kind]
        return web_review.export_findings(cfg, str(data.get("project") or ""), fname, states=("new", "unclear"),
                                          only=only, note="doğrulanmamış")
    fname = _EXPORT_FILES.get(kind)
    if fname is None:
        return {"ok": False, "error": "kind must be todo, tbd, rtodo or rtbd"}
    return web_review.export_findings(cfg, str(data.get("project") or ""), fname)


class RemoteReviewDriver:
    """Uzak projede review sürücüsü (`review_remote_run` sözleşmesi; TBD#117 ek 3 c, sahip kararı 2026-10-24). Uzak host'ta
    projeden AYRI adlı (`rvw_<proje>`: proje adıyla başlamaz, kayıtsız/ad hoc sayılır, değnekçi dokunmaz) NORMAL bir ucli
    oturumu açar (salt-okunur, taze konuşma), istemi `term/input` ile gönderir, raporu `term/chat` ile okur. Anahtar
    taşınmaz (uzakta kurulu), aynalama yok, uzak ağaca yazma yok. Proje başına TEK canlı review oturumu: artık oturum
    önce kapatılır. Kapılar: projenin SAHİBİ kimliğin `remote_actions`ı + host taze (`_remote_denied`)."""

    POLL_STALE_NONE = None      # host bayatken "çalışıyor mu" bilinmez

    def __init__(self, project: str, host: str) -> None:
        self.project, self.host = project, host
        self.session = ("rvw_" + project)[:48]
        self._cwd = ""

    def _owner(self) -> str:
        ent = web_review.remote_projects().get(self.project)
        return ent[0] if ent else "default"

    def _rows(self) -> Optional[List[Dict[str, Any]]]:
        return _remote_rows(self.host)

    def _project_cwd_remote(self, rows: List[Dict[str, Any]]) -> str:
        for r in rows:
            if r.get("name") == self.project and r.get("cwd"):
                return str(r["cwd"])
        for r in rows:
            if r.get("cwd") and (r.get("blueprint") == self.project or str(r.get("name") or "").startswith(self.project)):
                return str(r["cwd"])
        return ""

    def ready(self) -> Tuple[bool, str]:
        denied = _remote_denied(self.project, "review", "review", self._owner(), self.host, self.host, None)
        if denied is not None:
            return False, str(denied.get("error") or denied.get("code") or "denied")
        rows = self._rows()
        if rows is None:
            return False, f"host {self.host} is stale"
        self._cwd = self._project_cwd_remote(rows)
        if not self._cwd:
            return False, f"remote folder of {self.project} unknown on {self.host}"
        return True, ""

    def cwd(self) -> str:
        if not self._cwd:
            ok, msg = self.ready()
            if not ok:
                raise RuntimeError(msg)
        return self._cwd

    def _wait_closed(self) -> bool:
        return _remote_wait_closed(self.host, self.session)

    def start(self, model: str, effort: str) -> Dict[str, Any]:
        ok, msg = self.ready()
        if not ok:
            return {"ok": False, "error": msg}
        rows = self._rows() or []
        if any(r.get("name") == self.session and r.get("running") for r in rows):     # tek canlı review oturumu: artığı kapat
            self.stop()
            if not self._wait_closed():
                return {"ok": False, "error": "previous review session did not close"}
        if not any(r.get("name") == self.session for r in rows):
            reg = _remote_post(self.host, "/api/register",
                               {"name": self.session, "cwd": self._cwd, "model": model, "cli": "ucli"}, REMOTE_START_TIMEOUT_SECONDS)
            if not reg.get("ok") and "already" not in str(reg.get("error") or "") and "in_use" not in str(reg.get("error") or ""):
                return {"ok": False, "error": f"register: {reg.get('error') or reg.get('code') or 'failed'}"}
        eff = effort if effort in ("low", "medium", "high") else "medium"
        res = _remote_post(self.host, "/api/start",
                           {"name": self.session, "model": model, "effort": eff, "fresh": True, "cli": "ucli",
                            "permission_mode": "read-only"}, REMOTE_START_TIMEOUT_SECONDS)
        if not res.get("ok"):
            return {"ok": False, "error": f"start: {res.get('error') or res.get('code') or 'failed'}"}
        for i in range(max(1, int(READY_TIMEOUT_SECONDS / REMOTE_READY_POLL_SECONDS))):
            if i:
                _remote_sleep(REMOTE_READY_POLL_SECONDS)
            _fresh, r = _remote_running_row(self.host, self.session)
            if r is not None and r.get("busy") is False:
                # ucli `--session rvw_<proje>` önceki koşunun konuşmasını diskten DEVRALIR (`fresh` bunu sıfırlamaz; canlı
                # denemede 146 KiB eski bağlam taşındı): `/clear` bellek içi geçmişi VE oturum dosyasını siler.
                clr = _remote_post(self.host, "/api/term/input", {"name": self.session, "text": "/clear", "exact": True},
                                   REMOTE_INPUT_TIMEOUT_SECONDS)
                if not clr.get("ok"):
                    return {"ok": False, "error": f"clear: {clr.get('error') or clr.get('code') or 'failed'}"}
                _remote_sleep(REMOTE_READY_POLL_SECONDS)
                sw.log_event("review_remote_started", paths=self._owner(), project=self.project, host=self.host, session=self.session)
                return {"ok": True}
        return {"ok": False, "error": "review session did not become ready"}

    def send(self, text: str) -> Dict[str, Any]:
        # Canlı deneme (2026-10-24): `term/input` satır satır girer, ucli REPL her satırı AYRI tur sayıp istemi böler (model
        # yalnız bir parçayı görür). Tek satıra indirilir; başlık biçimi için ayrıca uyarı eklenir.
        text = " ".join(str(text).split()) + " (Her bulgu başlığı cevapta AYRI bir satırda olmalı.)"
        res = _remote_post(self.host, "/api/term/input", {"name": self.session, "text": text, "exact": True},
                           REMOTE_INPUT_TIMEOUT_SECONDS)
        return {"ok": bool(res.get("ok")), "error": str(res.get("error") or res.get("code") or "")}

    def poll(self) -> Dict[str, Any]:
        fresh_host, row = _remote_running_row(self.host, self.session)
        out: Dict[str, Any] = {"running": (row is not None) if fresh_host else None,
                               "busy": (row or {}).get("busy") if row is not None else None, "user": "", "assistant": ""}
        if row is None:
            return out
        try:
            parsed, _status = _remote.get("/api/term/chat", self.host, {"name": self.session, "mode": "last"},
                                          timeout=REMOTE_READ_BUDGET_SECONDS)
        except Exception:
            return out
        if isinstance(parsed, dict) and parsed.get("ok") and parsed.get("supported"):
            out["user"], out["assistant"] = str(parsed.get("user") or ""), str(parsed.get("assistant") or "")
        return out

    def read_rel(self, rel: str) -> Optional[str]:
        """Uzak projenin göreli bir dosyasının metni (eskimiş-bulgu denetimi); None = okunamadı/izin yok. Fırlatmaz."""
        if not rel or rel.startswith("/") or ".." in rel.split("/") or "\x00" in rel:
            return None
        if not _remote_files_gate(self.host, self._owner()):
            return None
        real, cwd = _remote_ref(self.host, self.project)
        if not cwd:
            return None
        return _remote_read_full(self.host, real or self.project, cwd.rstrip("/") + "/" + rel, REMOTE_READ_BUDGET_SECONDS)

    def export_file(self, fname: str, build: Callable[[str], Tuple[Optional[str], List[str]]], notify: str = "") -> Dict[str, Any]:
        """Bulgu dışa aktarımı (uzak proje): `fname`yi host-routed `files/read` ile OKU (yoksa/okunamazsa DUR: uzak
        `files/write` yeni dosya oluşturmaz), `build(metin) -> (yeni | None, yazılan_idler)`, yazmadan hemen önce TEKRAR
        oku (değiştiyse `remote_conflict`), `files/write`, yazılanı geri oku doğrula. Proje oturumu AÇIK ve boştaysa
        `notify` kısa bildirimi `term/input` ile gider (commit/push YOK: uzak kabuk API'si yok). Fırlatmaz."""
        if "/" in fname or ".." in fname or "\x00" in fname or not fname:
            return {"ok": False, "error": "invalid target file"}
        ok, msg = self.ready()
        if not ok:
            return {"ok": False, "error": msg}
        if not _remote_files_gate(self.host, self._owner()):
            return {"ok": False, "error": f"remote files denied for host {self.host}"}
        real, cwd = _remote_ref(self.host, self.project)
        if not cwd:
            return {"ok": False, "error": f"remote folder of {self.project} unknown on {self.host}"}
        name = real or self.project
        path = cwd.rstrip("/") + "/" + fname
        for attempt in (0, 1):      # dosya okuma ile yazma arasında değişirse (proje oturumu aynı anda yazıyor) TEK otomatik yeniden deneme
            before = _remote_read_full(self.host, name, path, REMOTE_READ_BUDGET_SECONDS)
            if before is None:
                return {"ok": False, "error": f"{fname} missing or unreadable on {self.host}: not created", "path": path}
            new, written = build(before)
            out: Dict[str, Any] = {"ok": True, "path": path, "written": written, "host": self.host, "session": name}
            if new is None:
                return out
            if _remote_read_full(self.host, name, path, REMOTE_READ_BUDGET_SECONDS) == before:
                break
            if attempt:
                return {"ok": False, "error": "remote_conflict: file changed while exporting", "path": path}
        res = _remote_post(self.host, "/api/files/write", {"name": name, "path": path, "content": new}, REMOTE_INPUT_TIMEOUT_SECONDS)
        if not res.get("ok"):
            return {"ok": False, "error": f"write_failed: {res.get('error') or res.get('code') or 'failed'}", "path": path}
        if _remote_read_full(self.host, name, path, REMOTE_READ_BUDGET_SECONDS) != new:
            return {"ok": False, "error": "write_unverified: read-back differs", "path": path}
        fresh_host, row = _remote_running_row(self.host, name)
        out["session_open"] = row is not None
        out["notified"] = False
        if notify and row is not None and row.get("busy") is False:
            r = _remote_post(self.host, "/api/term/input", {"name": name, "text": " ".join(notify.split()), "exact": True},
                             REMOTE_INPUT_TIMEOUT_SECONDS)
            out["notified"] = bool(r.get("ok"))
        return out

    def sweep(self) -> bool:
        """Yetim review oturumu süpürücüsü: bu projede çalışan iş YOKKEN uzakta hâlâ `rvw_<proje>` çalışıyorsa (servis
        restart'ı koşuyu öldürüp oturumu bırakır) kapatır. Kapılar kapalı / host bayat ise dokunmaz. Dönen: kapatıldı mı."""
        if not self.ready()[0]:
            return False
        fresh_host, row = _remote_running_row(self.host, self.session)
        if not fresh_host or row is None:
            return False
        self.stop()
        sw.log_event("review_remote_swept", paths=self._owner(), project=self.project, host=self.host, session=self.session)
        return True

    def stop(self) -> None:
        try:
            _remote_post(self.host, "/api/stop", {"name": self.session, "exact": True}, REMOTE_START_TIMEOUT_SECONDS)
        except Exception:
            pass


web_review.set_cwd_resolver(lambda name: _project_cwd(name))
web_review.set_remote_driver(lambda project, host: RemoteReviewDriver(project, host))
web_review.set_verdict_reader(_review_verdict_reader)
web_review.set_notifier(lambda sid, q: _notify(steward_config(sid), f"{_ask_prefix(q.project, sid)} {q.text}\n→ {sw.ask_hint(q.id, sid)}"))


POST_PATHS = {
    "/api/steward/loop-reset": http_loop_reset,
    "/api/steward/review/pool": http_review_pool,
    "/api/steward/review/where": http_review_where,
    "/api/steward/review/run": http_review_run,
    "/api/steward/review/cancel": http_review_cancel,
    "/api/steward/review/verify": http_review_verify,
    "/api/steward/review/finding": http_review_finding,
    "/api/steward/review/bulk": http_review_bulk,
    "/api/steward/review/exclude": http_review_exclude,
    "/api/steward/review/export": http_review_export,
    "/api/steward/review/lesson": http_review_lesson,
    "/api/steward/service/add": http_service_add,
    "/api/steward/service/rm": http_service_rm,
    "/api/steward/job/ack": http_job_ack,
    "/api/steward/identity/create": http_identity_create,
    "/api/steward/identity/remove": http_identity_remove,
    "/api/steward/identity/transfer": http_identity_transfer,
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
    "/api/steward/config": http_config,
    "/api/steward/quota": http_quota_set,
    "/api/steward/enable": http_enable,
    "/api/steward/up": http_up,
    "/api/steward/shutdown": http_shutdown,
    "/api/steward/panic": http_panic,
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
