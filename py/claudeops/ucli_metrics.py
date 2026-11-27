"""ucli oturumlarının kaynak metrikleri: zaman serisi örnekleyici + SQLite depo + salt-okunur API gövdesi.

Her `interval_s` (varsayılan 15 sn) çalışan ucli oturumlarının süreç AĞACI (kök pid + tüm torunlar; kafes/bwrap altı dahil)
için /proc'tan RSS (KiB, statm), CPU% (utime+stime tik farkı / geçen süre), /proc/<pid>/io read_bytes/write_bytes (okunamazsa 0;
`io_r`/`io_w` ağaçtaki canlı süreçlerin ANLIK kümülatif toplamı) ve süreç sayısını `samples` tablosuna yazar. Çalışma dizini
(worktree) disk kullanımı pahalıdır: oturum başına en çok 5 dakikada bir, kendi `os.scandir` yürüyüşümüzle 3 sn zaman aşımı +
en çok 200k dosya; aşılırsa `disk_b` NULL. Diğer turlarda `disk_b` NULL'dır.

Boşta maliyet: çalışan ucli oturumu yoksa tur yalnız bir bellek denetimi yapar; oturum keşfi (`discovery.find_sessions`) her durumda en çok
60 sn'de bir koşar (bilinen oturum varken de, yeni açılanlar kaçmasın), bilinen kök pid'ler her turda /proc/<pid> varlığıyla doğrulanır. `settings.ucli_metrics.enabled` kapalıysa
iş parçacığı hiç başlamaz. Yazma YALNIZ bu modülün fonksiyonlarıyla, tek yazıcı iş parçacığı + `_DB_LOCK`; WAL.

ÖLÇÜLEN MALİYET (21 Kas 2026, bu makine, ~650 süreçli sistem, 10 sahte `sleep` çocuğu; `tests/test_ucli_metrics.py::Cost`):
bir `sample_once` turu ~29 ms duvar saati ve ~26 ms CPU (15 sn aralıkta ~%0,17 tek çekirdek); tur süresi sistemdeki toplam süreç
sayısıyla doğrusal (her tur /proc'u bir kez tarar: ppid haritası için süreç başına bir stat okuması). Ölçümler testin çıktısında yazılır.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

DB_NAME = "ucli_metrics.db"
DEFAULTS = {"enabled": True, "interval_s": 15.0, "retention_days": 30.0}
DISK_EVERY_S = 300.0
DISK_TIMEOUT_S = 3.0
DISK_MAX_FILES = 200_000
DISCOVER_EVERY_S = 60.0
SLOW_EVERY_S = 60.0       # claude CLI oturumları (SLOW_NAMES) en çok dakikada bir örneklenir: depo büyümesi ~4x az
SLOW_NAMES: set = set()
MAX_LIMIT = 2000
_CLK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
_PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
_DB_LOCK = threading.Lock()


# ── ayarlar ───────────────────────────────────────────────────────────────────

def _num(v: Any, default: float, lo: float, hi: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f:          # NaN sınırlanamaz (`max(nan, lo)` = nan): örnekleyici `sleep(nan)` yapardı
        return default
    return min(max(f, lo), hi)


def get_config(raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """`settings.ucli_metrics` (değerler save_settings'ten dizge gelebilir: "on"/"off"/"15") -> {enabled, interval_s, retention_days}."""
    if raw is None:
        try:
            from .settings import load_settings
            raw = load_settings().get("ucli_metrics") or {}
        except Exception:
            raw = {}
    en = raw.get("enabled", DEFAULTS["enabled"]) if isinstance(raw, dict) else DEFAULTS["enabled"]
    if isinstance(en, str):
        en = en.strip().lower() not in ("off", "false", "0", "no", "hayır")
    raw = raw if isinstance(raw, dict) else {}
    return {"enabled": bool(en),
            "interval_s": _num(raw.get("interval_s"), DEFAULTS["interval_s"], 1.0, 3600.0),
            "retention_days": _num(raw.get("retention_days"), DEFAULTS["retention_days"], 1.0, 3650.0)}


# ── depo ──────────────────────────────────────────────────────────────────────

def db_path() -> str:
    from .paths import CLAUDEOPS_DIR
    return os.path.join(CLAUDEOPS_DIR, DB_NAME)


def _connect(path: Optional[str] = None) -> sqlite3.Connection:
    p = path or db_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    c = sqlite3.connect(p, timeout=10.0)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("CREATE TABLE IF NOT EXISTS samples(session TEXT NOT NULL, ts REAL NOT NULL, rss_kib INT, cpu_pct REAL, "
              "io_r INT, io_w INT, procs INT, disk_b INT NULL)")
    c.execute("CREATE INDEX IF NOT EXISTS samples_session_ts ON samples(session, ts)")
    return c


def write_samples(rows: List[Tuple[str, float, int, float, int, int, int, Optional[int]]], path: Optional[str] = None) -> int:
    if not rows:
        return 0
    with _DB_LOCK:
        c = _connect(path)
        try:
            with c:
                c.executemany("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?)", rows)
        finally:
            c.close()
    return len(rows)


def prune(retention_days: float, now: Optional[float] = None, path: Optional[str] = None) -> int:
    cutoff = (time.time() if now is None else now) - retention_days * 86400.0
    with _DB_LOCK:
        c = _connect(path)
        try:
            with c:
                n = c.execute("DELETE FROM samples WHERE ts < ?", (cutoff,)).rowcount
        finally:
            c.close()
    return n


def _read_conn(path: Optional[str] = None) -> sqlite3.Connection:
    p = path or db_path()
    if not os.path.exists(p):
        raise FileNotFoundError(p)
    c = sqlite3.connect("file:" + p + "?mode=ro", uri=True, timeout=10.0)
    return c


def query(name: str, since: float = 0.0, limit: int = 500, path: Optional[str] = None) -> Dict[str, Any]:
    limit = max(1, min(int(limit), MAX_LIMIT))
    try:
        c = _read_conn(path)
    except (FileNotFoundError, sqlite3.Error):
        return {"ok": True, "samples": [], "summary": _summary([])}
    try:
        rows = c.execute("SELECT session,ts,rss_kib,cpu_pct,io_r,io_w,procs,disk_b FROM samples WHERE session=? AND ts>=? "
                         "ORDER BY ts DESC LIMIT ?", (name, since, limit)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        c.close()
    rows.reverse()
    samples = [{"session": r[0], "ts": r[1], "rss_kib": r[2], "cpu_pct": r[3], "io_r": r[4], "io_w": r[5], "procs": r[6], "disk_b": r[7]}
               for r in rows]
    return {"ok": True, "samples": samples, "summary": _summary(samples)}


def _summary(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not samples:
        return {"rss_max_kib": 0, "cpu_avg": 0.0, "io_r": 0, "io_w": 0, "n": 0}
    cpu = [s["cpu_pct"] or 0.0 for s in samples]
    ior = [s["io_r"] or 0 for s in samples]
    iow = [s["io_w"] or 0 for s in samples]
    return {"rss_max_kib": max(s["rss_kib"] or 0 for s in samples), "cpu_avg": round(sum(cpu) / len(cpu), 2),
            "io_r": max(0, max(ior) - min(ior)), "io_w": max(0, max(iow) - min(iow)), "n": len(samples)}   # io = pencere içi artış


def list_sessions(path: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        c = _read_conn(path)
    except (FileNotFoundError, sqlite3.Error):
        return []
    try:
        rows = c.execute("SELECT session, MAX(ts), COUNT(*) FROM samples GROUP BY session ORDER BY MAX(ts) DESC").fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        c.close()
    return [{"name": r[0], "last_ts": r[1], "n": r[2]} for r in rows]


def api_get(path: str, qs: Dict[str, List[str]]) -> Dict[str, Any]:
    """GET /api/ucli/metrics?name=&since=&limit= ve GET /api/ucli/metrics/sessions gövdesi."""
    def one(k: str) -> str:
        return str((qs.get(k) or [""])[0])
    if path.rstrip("/").endswith("/sessions"):
        return {"ok": True, "sessions": list_sessions()}
    name = one("name")
    if not name:
        return {"ok": False, "error": "name gerekli"}
    try:
        since = float(one("since") or 0)
        limit = int(one("limit") or 500)
    except ValueError:
        return {"ok": False, "error": "since/limit sayı olmalı"}
    return query(name, since, limit)


# ── /proc örnekleme ───────────────────────────────────────────────────────────

def _read(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


def parse_stat(txt: str) -> Optional[Tuple[int, int]]:
    """/proc/<pid>/stat -> (ppid, utime+stime tik). comm parantez/boşluk içerebilir: son ')' sonrası bölünür."""
    try:
        rest = txt[txt.rindex(")") + 2:].split()
        return int(rest[1]), int(rest[11]) + int(rest[12])
    except (ValueError, IndexError):
        return None


def tree_pids(roots: List[int], ppid_of: Dict[int, int]) -> Dict[int, int]:
    """Her kök için torunlar dahil pid -> kök haritası (kök kendisi dahil)."""
    kids: Dict[int, List[int]] = {}
    for pid, pp in ppid_of.items():
        kids.setdefault(pp, []).append(pid)
    owner: Dict[int, int] = {}
    for r in roots:
        if r not in ppid_of:
            continue
        stack = [r]
        while stack:
            p = stack.pop()
            if p in owner:
                continue
            owner[p] = r
            stack.extend(kids.get(p, ()))
    return owner


def scan_procs(proc_root: str = "/proc") -> Dict[int, Tuple[int, int]]:
    """Tüm süreçler: pid -> (ppid, cpu tikleri). Okunamayan/ölen atlanır."""
    out: Dict[int, Tuple[int, int]] = {}
    try:
        names = os.listdir(proc_root)
    except OSError:
        return out
    for n in names:
        if not n.isdigit():
            continue
        try:
            st = parse_stat(_read(f"{proc_root}/{n}/stat"))
        except OSError:
            continue
        if st:
            out[int(n)] = st
    return out


def proc_mem_io(pid: int, proc_root: str = "/proc") -> Tuple[int, int, int]:
    """(rss_kib, read_bytes, write_bytes); okunamayan parça 0."""
    rss = rb = wb = 0
    try:
        rss = int(_read(f"{proc_root}/{pid}/statm").split()[1]) * _PAGE // 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        for ln in _read(f"{proc_root}/{pid}/io").splitlines():
            if ln.startswith("read_bytes:"):
                rb = int(ln.split()[1])
            elif ln.startswith("write_bytes:"):
                wb = int(ln.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return rss, rb, wb


def disk_usage(root: str, timeout: float = DISK_TIMEOUT_S, max_files: int = DISK_MAX_FILES,
               clock: Callable[[], float] = time.monotonic) -> Optional[int]:
    """`du -sb` benzeri (dosya boyutları toplamı, sembolik bağlar izlenmez). Zaman aşımı/dosya sınırı aşılırsa None."""
    if not root or not os.path.isdir(root):
        return None
    t0, files, total = clock(), 0, 0
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    files += 1
                    if files > max_files or clock() - t0 > timeout:
                        return None
                    try:
                        if e.is_symlink():
                            total += e.stat(follow_symlinks=False).st_size
                        elif e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


class Sampler:
    """Durumlu örnekleyici (önceki tikler + disk önbelleği). `discover() -> [(ad, kök_pid, cwd)]` enjekte edilebilir."""

    def __init__(self, discover: Optional[Callable[[], List[Tuple[str, int, str]]]] = None, proc_root: str = "/proc",
                 path: Optional[str] = None, now: Callable[[], float] = time.time, disk: Callable[[str], Optional[int]] = disk_usage):
        self.discover = discover or default_discover
        self.proc_root, self.path, self.now, self.disk = proc_root, path, now, disk
        self.known: List[Tuple[str, int, str]] = []
        self.last_discover = -1e18
        self.prev_ticks: Dict[str, Dict[int, int]] = {}
        self.prev_ts: Dict[str, float] = {}
        self.disk_ts: Dict[str, float] = {}
        self.last_prune = 0.0
        self.discovers = 0

    def _alive(self) -> List[Tuple[str, int, str]]:
        return [k for k in self.known if os.path.isdir(f"{self.proc_root}/{k[1]}")]

    def sample_once(self, retention_days: float = 30.0) -> int:
        """Bir tur. Çalışan oturum yoksa (keşif 60 sn'de bir) hiçbir /proc taraması/DB işi yapmaz. Yazılan satır sayısı."""
        t = self.now()
        self.known = self._alive()
        if t - self.last_discover >= DISCOVER_EVERY_S:           # bilinen oturum varken de: sonradan açılan oturumlar kaçmasın
            self.last_discover = t
            self.discovers += 1
            try:
                self.known = list(self.discover())
            except Exception:
                pass                                              # keşif hatasında canlı olan bilinenlerle sürer
        if not self.known:
            return 0
        procs = scan_procs(self.proc_root)
        owner = tree_pids([k[1] for k in self.known], {p: v[0] for p, v in procs.items()})
        rows = []
        for name, root, cwd in self.known:
            pids = [p for p, r in owner.items() if r == root]
            if not pids:
                continue
            if name in SLOW_NAMES and t - self.prev_ts.get(name, -1e18) < SLOW_EVERY_S:
                continue                                          # önceki tik/zaman korunur: CPU% sonraki örnekte tüm aralığı kapsar
            rss = rb = wb = 0
            ticks: Dict[int, int] = {}
            for p in pids:
                m, r, w = proc_mem_io(p, self.proc_root)
                rss, rb, wb = rss + m, rb + r, wb + w
                ticks[p] = procs[p][1]
            prev, pts = self.prev_ticks.get(name), self.prev_ts.get(name)
            cpu = 0.0
            if prev is not None and pts is not None and t > pts:
                d = sum(max(0, tk - prev.get(p, 0)) for p, tk in ticks.items())   # yeni süreç: tüm tikleri aralıkta harcanmış sayılır
                cpu = round(d / _CLK / (t - pts) * 100.0, 2)
            self.prev_ticks[name], self.prev_ts[name] = ticks, t
            disk_b = None
            if cwd and t - self.disk_ts.get(name, -1e18) >= DISK_EVERY_S:
                self.disk_ts[name] = t
                disk_b = self.disk(cwd)
            rows.append((name, t, rss, cpu, rb, wb, len(pids), disk_b))
        gone = set(self.prev_ticks) - {k[0] for k in self.known}
        for g in gone:
            self.prev_ticks.pop(g, None)
            self.prev_ts.pop(g, None)
            self.disk_ts.pop(g, None)
        n = write_samples(rows, self.path)
        if t - self.last_prune >= 86400.0:
            self.last_prune = t
            prune(retention_days, t, self.path)
        return n


def default_discover() -> List[Tuple[str, int, str]]:
    """ucli oturumları + claude CLI oturumları (22 Kas: karşılaştırma tablosu claude CLI'yı da kaynak sütunlarıyla göstersin)."""
    from . import discovery
    found = [s for s in discovery.find_sessions(measure_cpu=False) if s.cli in ("ucli", "claude") and s.pid]
    SLOW_NAMES.clear()
    SLOW_NAMES.update(s.name for s in found if s.cli == "claude")
    return [(s.name, s.pid, s.cwd or "") for s in found]


# ── arka plan iş parçacığı ────────────────────────────────────────────────────

_THREAD: Optional[threading.Thread] = None
_STOP = threading.Event()


def start_background(cfg: Optional[Dict[str, Any]] = None, sampler: Optional[Sampler] = None) -> Optional[threading.Thread]:
    """`enabled=false` ise hiç başlatmaz (None). Tek örnek: zaten çalışıyorsa onu döner."""
    global _THREAD
    cfg = cfg or get_config()
    if not cfg["enabled"]:
        return None
    if _THREAD is not None and _THREAD.is_alive():
        return _THREAD
    _STOP.clear()
    s = sampler or Sampler()

    def loop() -> None:
        while not _STOP.wait(cfg["interval_s"]):
            try:
                s.sample_once(cfg["retention_days"])
            except Exception:
                pass

    _THREAD = threading.Thread(target=loop, daemon=True, name="ucli-metrics")
    _THREAD.start()
    return _THREAD


def stop_background() -> None:
    _STOP.set()
