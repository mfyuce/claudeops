"""Periyodik işler (cops periodic) — claudeops servisi içinde, kendi ayarlarıyla çalışan günlük/saatlik işler.

Sahip isteği (2026-11-05, "todo:"): "cops periodic jobs; günlük uzak/yakın tüm biten/değişen chatleri alıp gh/glab prv repoya
atan; kendi ayarları olur; başlama ayarları bizim seçeneklere benzer; copschats-prv repo". crontab KULLANILMAZ (sınıflandırıcı
'persistence' diye engeller); servis içi thread, `model_freshness` ile aynı desen.

Ayar dosyası `CLAUDEOPS_DIR/periodic.json` (settings.json'a DOKUNMAZ):
  {"jobs": {"chat_backup": {"enabled": "off", "start": "03:30", "interval_hours": 24, ...}}}
`enabled`: "on" | "off" (varsayılan KAPALI; `_OFF_WORDS` kapatır). Durum `periodic_state.json` (son başlangıç, sonuç, manifest).
Görev işleyicileri `JOBS`'ta; yeni iş = bir `Job` kaydı eklemek.

chat_backup: `~/.claude/projects/**/*.jsonl` + `history.jsonl` içinde YENİ/DEĞİŞEN dosyaları sır-maskeleyip ham (gzip yok) olarak, gün başına ayrı commit ile
`repo_dir` (varsayılan ~/work/projects/tmp/copschats-prv) altına koyar, YALNIZ o açık yolları `git add` + commit + push eder
(tüm remote'lar, ikisi de PRIVATE doğrulanır, push sonrası ls-remote). Uzak host kaynakları `sources`ta tanımlıdır
(şimdilik yalnız "local"; uzak = TODO).
"""
from __future__ import annotations

import datetime
import fcntl
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .atomic_json import atomic_write_json
from .diaglog import diag_log
from .paths import CLAUDEOPS_DIR

CONFIG_JSON = os.path.join(CLAUDEOPS_DIR, "periodic.json")
STATE_JSON = os.path.join(CLAUDEOPS_DIR, "periodic_state.json")
_OFF_WORDS = {"off", "0", "false", "no", "hayir", "hayır", "kapali", "kapalı", "none", ""}
_WAKE_SECONDS = 60
_REDACT = "[GİZLİ-MASKELENDİ]"

# memory_backup.SECRET_PATTERNS ile AYNI sınıflar (tek kaynak değil: o modül komut katmanında, bu servis katmanında).
SECRET_RES = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-or-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{24,}"),
    re.compile(r"(?i)((?:password|passwd|pwd|parola|şifre)['\"]?\s*[=:]\s*['\"]?)[^\s'\"<>$*,}\\]{4,}"),
]

DEFAULT_CHAT_BACKUP: Dict[str, Any] = {
    "enabled": "off",
    "schedule": "",              # 5 alanlı cron ("30 3 * * *"); doluysa start/interval_hours YOK SAYILIR
    "start": "03:30",            # günlük işlerde en erken başlama saati (yerel)
    "interval_hours": 24,        # >=24: günde bir (start sonrası); <24: son başlangıçtan bu kadar saat sonra
    "repo_dir": os.path.join("~", "work", "projects", "tmp", "copschats-prv"),
    "repo_name": "copschats-prv",
    "repos": {"claude": "", "codex": os.path.join("~", "work", "projects", "tmp", "copschats-codex-prv"),
              "gemini": os.path.join("~", "work", "projects", "tmp", "copschats-gemini-prv")},  # claude boşsa repo_dir
    "raw_remote": "gdrive:chat-raw",   # ham .db/.sqlite buraya (rclone); boş = yükleme yok
    "dump_db": True,             # codex/gemini .db -> JSONL döküm (chat_dump)
    "sources": ["local"],
    "remote_pull": {},           # {host: shell_oturum_adı}, örn {"yuhem": "shell_yuhem"}; boş = uzak çekme KAPALI (chat_remote)
    "max_file_mb": 50,           # tek ham dosya sınırı (GitHub blob 100 MB); aşan atlanır, günlüğe yazılır
    "max_repo_mb": 8000,         # çalışma ağacı sınırı; aşılırsa iş durur (sahibe sorulur)
}


def _is_on(v: Any) -> bool:
    return str(v).strip().lower() not in _OFF_WORDS


# ------------------------------------------------------------------ ayar/durum
CUSTOM_DEFAULTS: Dict[str, Any] = {
    "name": "", "kind": "command",   # kind: command (argv, kabuksuz) | prompt (claude -p ile tek seferlik soru)
    "enabled": "off", "schedule": "", "start": "03:30", "interval_hours": 24,
    "command": "", "prompt": "", "cli": "claude", "model": "", "effort": "low",
    "cwd": "", "timeout_s": 900, "skip_when_quota_blocked": "on",
}
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def _read_raw() -> Dict[str, Any]:
    try:
        with open(CONFIG_JSON, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def load_config() -> Dict[str, Dict[str, Any]]:
    """Her iş için varsayılanlarla birleşmiş tam ayar (yerleşik + kullanıcı tanımlı). Bozuk/eksik dosya = varsayılanlar (KAPALI)."""
    raw = _read_raw()
    stored = raw.get("jobs") if isinstance(raw.get("jobs"), dict) else {}
    out: Dict[str, Dict[str, Any]] = {}
    for name, job in JOBS.items():
        cfg = dict(job.defaults)
        s = stored.get(name)
        if isinstance(s, dict):
            cfg.update({k: v for k, v in s.items() if k in job.defaults})
        cfg["_builtin"] = True
        out[name] = cfg
    custom = raw.get("custom") if isinstance(raw.get("custom"), dict) else {}
    for cid, c in custom.items():
        if not _ID_RE.match(str(cid)) or not isinstance(c, dict) or cid in out:
            continue
        cfg = dict(CUSTOM_DEFAULTS)
        cfg.update({k: v for k, v in c.items() if k in CUSTOM_DEFAULTS})
        cfg["_builtin"] = False
        out[cid] = cfg
    return out


def _validate(cfg: Dict[str, Any]) -> None:
    if "start" in cfg and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(cfg["start"])):
        raise ValueError("start HH:MM olmalı")
    if str(cfg.get("schedule") or "").strip() and parse_cron(str(cfg["schedule"])) is None:
        raise ValueError("schedule geçerli 5 alanlı cron değil (örn. '30 3 * * *')")
    if cfg.get("kind") not in (None, "command", "prompt"):
        raise ValueError("kind command|prompt olmalı")
    if cfg.get("cli") not in (None, "claude"):
        raise ValueError("prompt işleri şimdilik yalnız cli=claude (kota bekçisine bağlı)")


def add_custom(cid: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Kullanıcı tanımlı iş ekler (KAPALI açılır; sahip `enabled=on` yapar). Kimlik `[a-z][a-z0-9_]{1,31}`, yerleşik adlarla çakışmaz."""
    if not _ID_RE.match(cid) or cid in JOBS:
        raise ValueError("geçersiz ya da çakışan iş kimliği")
    raw = _read_raw()
    custom = raw.get("custom") if isinstance(raw.get("custom"), dict) else {}
    if cid in custom:
        raise ValueError("bu kimlik zaten var")
    cfg = {k: v for k, v in fields.items() if k in CUSTOM_DEFAULTS}
    bad = [k for k in fields if k not in CUSTOM_DEFAULTS]
    if bad:
        raise KeyError("bilinmeyen alan: " + ",".join(bad))
    cfg["enabled"] = "off"
    _validate(cfg)
    kind = cfg.get("kind", "command")
    if kind == "command" and not str(cfg.get("command") or "").strip():
        raise ValueError("command işi için command gerekli")
    if kind == "prompt" and not str(cfg.get("prompt") or "").strip():
        raise ValueError("prompt işi için prompt gerekli")
    custom[cid] = cfg
    raw["custom"] = custom
    atomic_write_json(CONFIG_JSON, raw, mode=0o600)
    return load_config()[cid]


def remove_custom(cid: str) -> bool:
    raw = _read_raw()
    custom = raw.get("custom") if isinstance(raw.get("custom"), dict) else {}
    if cid not in custom:
        return False
    custom.pop(cid)
    raw["custom"] = custom
    atomic_write_json(CONFIG_JSON, raw, mode=0o600)
    return True


def set_config(name: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Alan-bazlı merge (`ucli_limits` deseni): boş string o alanı varsayılana döndürür. Bilinmeyen iş/alan reddedilir."""
    cfgs = load_config()
    if name not in cfgs:
        raise KeyError(f"bilinmeyen iş: {name}")
    builtin = bool(cfgs[name].get("_builtin"))
    allowed = JOBS[name].defaults if builtin else CUSTOM_DEFAULTS
    raw = _read_raw()
    bucket_key = "jobs" if builtin else "custom"
    bucket = raw.get(bucket_key) if isinstance(raw.get(bucket_key), dict) else {}
    cur = dict(bucket.get(name) or {})
    for k, v in patch.items():
        if k not in allowed:
            raise KeyError(f"bilinmeyen alan: {k}")
        if v == "" and builtin:
            cur.pop(k, None)
        else:
            cur[k] = v
    _validate({**cfgs[name], **cur})
    bucket[name] = cur
    raw[bucket_key] = bucket
    atomic_write_json(CONFIG_JSON, raw, mode=0o600)
    return load_config()[name]


def load_state() -> Dict[str, Any]:
    try:
        with open(STATE_JSON, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: Dict[str, Any]) -> None:
    atomic_write_json(STATE_JSON, state, mode=0o600)


# ------------------------------------------------------------------ zamanlama
def _cron_field(spec: str, lo: int, hi: int) -> Optional[set]:
    """Tek cron alanı -> değer kümesi (`*`, `*/n`, `a-b`, `a-b/n`, `a,b`). Geçersizse None."""
    out: set = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, st = part.split("/", 1)
            if not st.isdigit() or int(st) < 1:
                return None
            step = int(st)
        if part == "*":
            a, b = lo, hi
        elif re.fullmatch(r"\d+-\d+", part):
            a, b = (int(x) for x in part.split("-"))
        elif part.isdigit():
            a = int(part)
            b = hi if step > 1 else a
        else:
            return None
        if a < lo or b > hi or a > b:
            return None
        out.update(range(a, b + 1, step))
    return out


def parse_cron(expr: str) -> Optional[Tuple[set, set, set, set, set]]:
    """'dk saat gün ay haftagünü' (haftagünü 0-6, 0=pazar; 7 de pazar). Geçersiz = None. Gün VE haftagünü ikisi de kısıtlıysa VEYA (cron kuralı)."""
    f = str(expr or "").split()
    if len(f) != 5:
        return None
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
    sets = [_cron_field(x, *r) for x, r in zip(f, ranges)]
    if any(x is None or not x for x in sets):
        return None
    if 7 in sets[4]:
        sets[4] = (sets[4] - {7}) | {0}
    return (sets[0], sets[1], sets[2], sets[3], sets[4])


def cron_match(c: Tuple[set, set, set, set, set], dt: datetime.datetime) -> bool:
    mi, ho, dom, mon, dow = c
    if dt.minute not in mi or dt.hour not in ho or dt.month not in mon:
        return False
    wd = (dt.weekday() + 1) % 7
    dom_star = len(dom) == 31
    dow_star = len(dow) == 7
    if dom_star or dow_star:
        return (dt.day in dom) and (wd in dow)
    return (dt.day in dom) or (wd in dow)


def cron_due(expr: str, last_dt: Optional[datetime.datetime], now: datetime.datetime) -> bool:
    """(son başlangıç, şimdi] aralığında cron'a uyan bir dakika var mı (en çok 36 saat geriye bakar; ilk çalıştırmada yalnız son dakika)."""
    c = parse_cron(expr)
    if c is None:
        return False
    t = now.replace(second=0, microsecond=0)
    floor = t - datetime.timedelta(hours=36)
    if last_dt is not None:
        floor = max(floor, last_dt.replace(second=0, microsecond=0))
    else:
        floor = t - datetime.timedelta(minutes=1)
    while t > floor:
        if cron_match(c, t):
            return True
        t -= datetime.timedelta(minutes=1)
    return False


def is_due(cfg: Dict[str, Any], st: Dict[str, Any], now: Optional[datetime.datetime] = None) -> bool:
    """Açık mı + zamanı geldi mi. Saf fonksiyon (testlenir)."""
    if not _is_on(cfg.get("enabled")):
        return False
    now = now or datetime.datetime.now()
    last = st.get("last_start")
    last_dt = datetime.datetime.fromtimestamp(float(last)) if last else None
    if str(cfg.get("schedule") or "").strip():
        return cron_due(str(cfg["schedule"]), last_dt, now)
    try:
        hours = float(cfg.get("interval_hours") or 24)
    except (TypeError, ValueError):
        hours = 24.0
    if hours >= 24:
        hh, mm = (int(x) for x in str(cfg.get("start") or "03:30").split(":"))
        today_start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < today_start:
            return False
        return last_dt is None or last_dt < today_start
    return last_dt is None or (now - last_dt).total_seconds() >= hours * 3600


# ------------------------------------------------------------------ chat_backup
def redact(text: str) -> Tuple[str, int]:
    """Sır örüntülerini maskeler; (yeni metin, değişen yer sayısı). Gruplu örüntülerde ön ek korunur (parola=… -> parola=MASKE)."""
    n = 0
    for rx in SECRET_RES:
        def sub(m: "re.Match[str]") -> str:
            nonlocal n
            n += 1
            return (m.group(1) + _REDACT) if rx.groups else _REDACT
        text = rx.sub(sub, text)
    return text, n


def _git(repo: str, *args: str, timeout: int = 300, env: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    """Tek git çıkış kapısı (testlerde yamalanır)."""
    env = dict(env if env is not None else os.environ, GIT_TERMINAL_PROMPT="0")    # parola/hostkey sorusunda askıda kalma yok
    try:
        p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


CHUNK_MB = 45          # bundan büyük ikili dosya <ad>.partNNN parçalara bölünür (GitHub blob 100 MB; birleştir: cat <ad>.part* > <ad>)
TEXT_EXT = (".jsonl", ".jsonl.zst")      # .zst = codex sıkıştırılmış oturum: ham (ikili) yedeklenir, maskelenemez
BIN_EXT = (".db", ".sqlite", ".pb", ".json")
MEM_SKIP = ("-shm", ".tmp", ".lock", ".swp")


STAGE_DIR = os.path.join(CLAUDEOPS_DIR, "backups", "chat-dump")


def _local_sources() -> List[Tuple[str, ...]]:
    """(kaynak yol, repo içi hedef öneki[, tür]) demetleri. tür: "text" (jsonl, sır maskelenir) | "bin" (ham, büyükse parçalanır).
    Ayna (chat-mirror) canlı dizinden SİLİNMİŞ eski sohbetleri de taşır; aynı hedef yolda mtime'ı yeni olan kazanır.
    Hedef yol = özgün göreli yol (tarih/oturum/proje yolu korunur). Grup = önekin ikinci parçası (claude|codex|gemini) -> kendi repo'su."""
    home = os.path.expanduser("~")
    mir = os.path.join(home, ".claude", "claudeops", "backups", "chat-mirror")
    out: List[Tuple[str, ...]] = [
        (os.path.join(mir, "claude-projects"), os.path.join("local", "claude-projects"), "text"),
        (os.path.join(home, ".claude", "projects"), os.path.join("local", "claude-projects"), "text"),
        (os.path.join(home, ".claude", "history.jsonl"), os.path.join("local", "claude-history"), "text"),
        (os.path.join(mir, "codex", "sessions"), os.path.join("local", "codex-sessions"), "text"),
        (os.path.join(home, ".codex", "sessions"), os.path.join("local", "codex-sessions"), "text"),
        (os.path.join(STAGE_DIR, "codex"), os.path.join("local", "codex-dump"), "text"),    # .db dökümü (chat_dump); ham .db gdrive'a
        (os.path.join(STAGE_DIR, "gemini"), os.path.join("local", "gemini-dump"), "text"),
        (os.path.join(mir, "ucli"), os.path.join("local", "claude-ucli"), "text"),
    ]
    for hdir in sorted(glob.glob(os.path.join(mir, "*", "extract"))):          # uzak host sohbetleri: local/<cli>-<host>-... (grup = cli)
        rh = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(os.path.dirname(hdir)))
        for pr in (os.path.join(hdir, ".claude", "projects"), os.path.join(hdir, "projects")):
            out.append((pr, os.path.join("local", f"claude-{rh}-projects"), "text"))
        out.append((os.path.join(hdir, ".claude", "history.jsonl"), os.path.join("local", f"claude-{rh}-history"), "text"))
        out.append((os.path.join(hdir, ".codex", "sessions"), os.path.join("local", f"codex-{rh}-sessions"), "text"))
    out.extend(_memory_sources(home, mir))
    return out


def _memory_sources(home: str, mir: str) -> List[Tuple[str, ...]]:
    """HAFIZA grubu: memory/<host>/<cli>/<proje>/... Canlı + ayna (canlıdan silinmişler); aynı hedefte mtime'ı yeni olan kazanır.
    Şirket GitLab'lı 6 proje DAHİL (sahip kararı TBD#158), hariç tutma yok."""
    import glob
    import socket
    host = re.sub(r"[^A-Za-z0-9._-]+", "-", socket.gethostname()) or "host"
    out: List[Tuple[str, ...]] = []
    for base in (os.path.join(home, ".claude", "projects"), os.path.join(mir, "claude-projects")):
        for d in sorted(glob.glob(os.path.join(base, "*", "memory"))):
            proj = os.path.basename(os.path.dirname(d))
            out.append((d, os.path.join("memory", host, "claude", proj), "mem"))
    for base in (home, os.path.join(mir, "codex")):
        sub = ".codex" if base == home else ""
        root = os.path.join(base, sub) if sub else base
        out.append((os.path.join(root, "memories"), os.path.join("memory", host, "codex", "memories"), "mem"))
        out.append((os.path.join(root, "memories_1.sqlite"), os.path.join("memory", host, "codex", "memories"), "mem"))
    for base in (os.path.join(home, ".gemini"), os.path.join(mir, "gemini")):
        for sub in ("antigravity", "antigravity-cli", "antigravity-ide", "antigravity-backup"):
            out.append((os.path.join(base, sub, "knowledge"), os.path.join("memory", host, "gemini", sub + "-knowledge"), "mem"))
        out.append((os.path.join(base, "GEMINI.md"), os.path.join("memory", host, "gemini", "GEMINI"), "mem"))
    for hdir in sorted(glob.glob(os.path.join(mir, "*", "extract"))):          # uzak host arşivleri (chat_dump.ingest_remote_archives)
        rh = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(os.path.dirname(hdir)))
        for pr in (os.path.join(hdir, ".claude", "projects"), os.path.join(hdir, "projects")):
            for d in sorted(glob.glob(os.path.join(pr, "*", "memory"))):
                out.append((d, os.path.join("memory", rh, "claude", os.path.basename(os.path.dirname(d))), "mem"))
        out.append((os.path.join(hdir, ".codex", "memories"), os.path.join("memory", rh, "codex", "memories"), "mem"))
    cop = os.path.join(mir, "copilot")
    out.append((os.path.join(cop, "data.db"), os.path.join("memory", host, "copilot", "data"), "mem"))
    out.append((os.path.join(cop, "command-history-state.json"), os.path.join("memory", host, "copilot", "data"), "mem"))
    return out


def _group_of(prefix: str) -> str:
    parts = prefix.replace("\\", "/").split("/")
    if parts[0] == "memory" and len(parts) > 2:        # memory/<host>/<cli>/<proje>: grup = cli; copilot claude reposuna gider
        return "claude" if parts[2] == "copilot" else parts[2]
    return (parts[1] if len(parts) > 1 else parts[0]).split("-")[0]


def _group_repo(cfg: Dict[str, Any], group: str) -> str:
    repos = cfg.get("repos") if isinstance(cfg.get("repos"), dict) else {}
    r = repos.get(group) or (cfg.get("repo_dir") if group == "claude" else "")
    return os.path.expanduser(str(r)) if r else ""


def _walk_files(src: str, kind: str) -> List[str]:
    if os.path.isfile(src):
        return [src]
    exts = TEXT_EXT if kind == "text" else BIN_EXT + TEXT_EXT
    out: List[str] = []
    for root, _d, files in os.walk(src):
        if kind == "mem":      # hafıza: her dosya (md/json/sqlite...), geçici/yedek/shm hariç
            out.extend(os.path.join(root, f) for f in files if not f.endswith(MEM_SKIP) and ".pre-update-backup" not in f and ".bak-" not in f)
        else:
            out.extend(os.path.join(root, f) for f in files if f.endswith(exts))
    return sorted(out)


_DEST_PFX = "dest:"


def _dest_marks(ents: List[Dict[str, Any]]) -> Dict[str, str]:
    """Hedef başına en yeni yedeklenen kaynak mtime'ı (manifestte `dest:<yol>`): canlı kaynak silinince eski ayna kopyası repodaki yeni sürümü ezmesin."""
    return {_DEST_PFX + e["dest"]: str(int(e["mt"])) for e in ents}


def plan_chat_backup(cfg: Dict[str, Any], manifest: Dict[str, str]) -> Dict[str, Any]:
    """Yeni/değişen dosyaları bulur (boyut+mtime imzası). Dosya OKUNMAZ/YAZILMAZ; saf plan."""
    best: Dict[str, Dict[str, Any]] = {}
    seen = 0
    for srcdef in _local_sources():
        src, prefix = srcdef[0], srcdef[1]
        kind = srcdef[2] if len(srcdef) > 2 else "text"
        if not os.path.exists(src):
            continue
        for f in _walk_files(src, kind):
            try:
                stt = os.stat(f)
            except OSError:
                continue
            seen += 1
            rel = os.path.relpath(f, src) if os.path.isdir(src) else os.path.basename(f)
            dest = os.path.join(prefix, rel)
            cur = best.get(dest)
            if cur is not None and (cur["mt"], cur["size"]) >= (stt.st_mtime, stt.st_size):
                continue
            best[dest] = {"src": f, "sig": f"{stt.st_size}:{int(stt.st_mtime)}", "dest": dest, "mt": stt.st_mtime,
                          "size": stt.st_size, "kind": kind,
                          "group": _group_of(prefix),
                          "day": datetime.datetime.fromtimestamp(stt.st_mtime).strftime("%F")}
    def _regress(e: Dict[str, Any]) -> bool:
        try:
            return int(e["mt"]) < int(manifest.get(_DEST_PFX + e["dest"], "0"))
        except ValueError:
            return False
    todo = [e for _d, e in sorted(best.items()) if manifest.get(e["src"]) != e["sig"] and not _regress(e)]
    return {"repo": _group_repo(cfg, "claude"), "seen": seen, "changed": todo,
            "marks": _dest_marks([e for e in best.values() if manifest.get(e["src"]) == e["sig"]])}


def _put(dest: str, blob: bytes) -> bool:
    """Atomik, 0600 yazar; içerik aynıysa dokunmaz. True = yazıldı."""
    if os.path.exists(dest):
        try:
            with open(dest, "rb") as f:
                if hashlib.sha256(f.read()).digest() == hashlib.sha256(blob).digest():
                    return False
        except OSError:
            pass
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(blob)
    os.replace(tmp, dest)
    return True


def _write_changed(plan: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[List[str], Dict[str, str], Dict[str, Any]]:
    """Değişenleri repo çalışma ağacına yazar: metin = sır maskeli ham (gzip yok; git sıkıştırır), ikili = olduğu gibi
    (büyükse CHUNK_MB parçalara). Dönüş: (yazılan göreli yollar, yeni manifest girdileri, istatistik: days[grup][gün] = yollar)."""
    limit = int(float(cfg.get("max_file_mb") or 50) * 1024 * 1024)
    chunk = CHUNK_MB * 1024 * 1024
    written: List[str] = []
    sigs: Dict[str, str] = {}
    stats: Dict[str, Any] = {"redacted": 0, "skipped_big": [], "unchanged": 0, "days": {}, "skipped_group": {}}
    for ent in plan["changed"]:
        group = ent.get("group", "claude")
        repo = _group_repo(cfg, group)
        if not repo or not os.path.exists(os.path.join(repo, ".git")):
            stats["skipped_group"][group] = stats["skipped_group"].get(group, 0) + 1
            continue
        try:
            with open(ent["src"], "rb") as f:
                raw = f.read()
        except OSError:
            continue
        if ent.get("kind") == "mem":
            ent = dict(ent, kind="bin" if b"\0" in raw[:8192] else "text")
        elif ent["src"].endswith(".zst"):
            ent = dict(ent, kind="bin")
        if ent.get("kind") == "bin":
            blobs = [(ent["dest"], raw)] if len(raw) <= chunk else [
                (f"{ent['dest']}.part{i // chunk:03d}", raw[i:i + chunk]) for i in range(0, len(raw), chunk)]
        else:
            text, n = redact(raw.decode("utf-8", errors="replace"))
            stats["redacted"] += n
            blob = text.encode("utf-8")
            if len(blob) > limit:
                blobs = [(f"{ent['dest']}.part{i // chunk:03d}", blob[i:i + chunk]) for i in range(0, len(blob), chunk)]
            else:
                blobs = [(ent["dest"], blob)]
        changed = False
        keep = {rel for rel, _d in blobs}
        base = ent["dest"]
        for stale in [base] + [os.path.relpath(x, repo) for x in sorted(glob.glob(glob.escape(os.path.join(repo, base)) + ".part*"))]:
            if stale not in keep and os.path.isfile(os.path.join(repo, stale)):   # boyut sınıfı değişti: eski parça/bütün dosya kalmasın (birleştirme bozulur)
                os.remove(os.path.join(repo, stale))
                written.append(stale)
                stats["days"].setdefault(group, {}).setdefault(ent["day"], []).append(stale)
                changed = True
        for rel, data in blobs:
            if _put(os.path.join(repo, rel), data):
                changed = True
                written.append(rel)
                stats["days"].setdefault(group, {}).setdefault(ent["day"], []).append(rel)
        if not changed:
            stats["unchanged"] += 1
        sigs[ent["src"]] = ent["sig"]
        sigs[_DEST_PFX + ent["dest"]] = str(int(ent["mt"]))
    return written, sigs, stats


def _tree_mb(repo: str) -> float:
    """Repo'nun GERÇEK boyutu = .git (sıkıştırılmış); çalışma ağacı ham olduğu için ölçüt o değil."""
    total = 0
    for root, dirs, files in os.walk(os.path.join(repo, ".git")):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / (1024 * 1024)


def _private_remotes(repo: str) -> Tuple[Dict[str, str], List[str]]:
    """Remote'lar (ad -> url) ve private OLMAYAN/doğrulanamayanların listesi (memory_backup ile aynı kural)."""
    from .commands import memory_backup as mb
    rems = mb.remotes_of(repo)
    bad: List[str] = []
    for name, url in rems.items():
        pr = mb.parse_remote(url)
        if pr is None or not mb.is_private(*pr):
            bad.append(name)
    return rems, bad


def _git_dated(repo: str, day: str, *args: str) -> Tuple[int, str]:
    """Commit tarihi = dosyaların son değişme günü (öğlen), geçmiş gün sırasıyla görünür."""
    return _git(repo, *args, env=dict(os.environ, GIT_AUTHOR_DATE=f"{day}T12:00:00", GIT_COMMITTER_DATE=f"{day}T12:00:00"))


def _check_repo(repo: str, cfg: Dict[str, Any]) -> Tuple[Optional[Dict[str, str]], str]:
    """(remote'lar, hata). hata boşsa repo kullanılabilir: git var, remote var, hepsi private, boyut sınırı aşılmamış."""
    if not repo or not os.path.exists(os.path.join(repo, ".git")):
        return None, f"repo yok: {repo or '(ayarsız)'}"
    rems, bad = _private_remotes(repo)
    if not rems:
        return None, f"remote yok: {repo}"
    if bad:
        return None, "private doğrulanamadı: " + ", ".join(bad)
    return rems, ""


def _porcelain_z_paths(por: str) -> list:
    """`git status --porcelain -z` çıktısından YENİ yollar. Rename/kopya (`R`/`C`) girdisi iki kayıttır (`XY yeni\0eski`): ikinci
    kayıt durum öneki taşımaz, `ln[3:]` onu bozardı; eski yol atlanır."""
    out = []
    parts = por.split("\0")
    i = 0
    while i < len(parts):
        ln = parts[i]
        i += 1
        if len(ln) < 4:
            continue
        if "R" in ln[:2] or "C" in ln[:2]:
            i += 1                      # sonraki kayıt eski yol
        out.append(ln[3:])
    return out


def run_chat_backup(cfg: Dict[str, Any], apply: bool, state: Dict[str, Any]) -> Dict[str, Any]:
    """Plan (apply=False) ya da uygula. Sonuç dict'i: ok, msg, written, ... Asla fırlatmaz.
    Her grup (claude|codex|gemini) kendi repo'suna gider; repo'su henüz olmayan grup ATLANIR (manifeste yazılmaz, sonra denenir)."""
    manifest: Dict[str, str] = dict((state.get("chat_backup") or {}).get("manifest") or {})
    dump_info: Dict[str, Any] = {}
    rp = cfg.get("remote_pull")
    if apply and isinstance(rp, dict) and rp:
        from . import chat_remote
        mirr = os.path.join(CLAUDEOPS_DIR, "backups", "chat-mirror")
        day = datetime.date.today().strftime("%Y%m%d")
        for host, sess in sorted(rp.items()):
            dest = os.path.join(mirr, str(host), f"{host}-chat-backup-{day}.tgz")
            if os.path.exists(dest):
                continue                   # bugün zaten çekildi
            r = chat_remote.pull(chat_remote.PanelTransport(str(host), str(sess)), str(host), day, dest)
            diag_log(f"periodic chat_backup: remote_pull {host}: {r.get('msg')}" + ("" if r.get("ok") else " HATA"))
    if apply and "local" in (cfg.get("sources") or []):
        try:                               # uzak host arşivlerini (yuhem, ulak_31 tgz) güvenle aç
            from . import chat_dump
            ing = chat_dump.ingest_remote_archives(os.path.join(CLAUDEOPS_DIR, "backups", "chat-mirror"))
            diag_log(f"periodic chat_backup: uzak arşiv {ing}")
        except Exception as e:  # noqa: BLE001
            diag_log(f"periodic chat_backup: uzak arşiv hatası {type(e).__name__}: {e}")
    if apply and "local" in (cfg.get("sources") or []) and str(cfg.get("dump_db", True)).lower() not in ("off", "0", "false", "no", ""):
        from . import chat_dump
        stamps: Dict[str, str] = dict((state.get("chat_backup") or {}).get("dump_stamps") or {})
        try:
            dump_info = chat_dump.stage_dumps(STAGE_DIR, stamps)
        except Exception as e:  # noqa: BLE001 — döküm hatası sohbet/hafıza yedeğini durdurmasın
            dump_info = {"dumped": 0, "skipped": 0, "files": 0, "errors": [f"stage_dumps: {type(e).__name__}: {e}"[:200]]}
        state.setdefault("chat_backup", {})["dump_stamps"] = stamps
        if cfg.get("raw_remote"):
            dump_info["raw_err"] = chat_dump.raw_to_remote(str(cfg["raw_remote"]))
    plan = plan_chat_backup(cfg, manifest)
    res: Dict[str, Any] = {"ok": True, "seen": plan["seen"], "changed": len(plan["changed"]), "repo": plan["repo"], "applied": False}
    if "local" not in (cfg.get("sources") or []):
        res.update(ok=False, msg="kaynak listesinde 'local' yok")
        return res
    groups = sorted({e["group"] for e in plan["changed"]} | {"claude"})
    remotes: Dict[str, Dict[str, str]] = {}
    missing: Dict[str, str] = {}
    for g in groups:
        rems, err = _check_repo(_group_repo(cfg, g), cfg)
        if rems is None:
            missing[g] = err
        else:
            remotes[g] = rems
    if "claude" in missing and not remotes:
        res.update(ok=False, msg=missing["claude"] + f" (önce private {cfg.get('repo_name')} oluştur: gh/glab, iki remote)")
        return res
    per = {g: sum(1 for e in plan["changed"] if e["group"] == g) for g in groups}
    if not apply:
        res["msg"] = f"plan: {len(plan['changed'])} yeni/değişen dosya ({plan['seen']} taranan); yazılmadı; gruplar {per}" + (
            f"; repo'suz atlanacak: {sorted(missing)}" if missing else "")
        res["missing"] = missing
        return res
    for g, rems in remotes.items():
        repo = _group_repo(cfg, g)
        if _tree_mb(repo) > float(cfg.get("max_repo_mb") or 3000):
            res.update(ok=False, msg=f"{g}: .git {int(_tree_mb(repo))} MB > sınır {cfg.get('max_repo_mb')} MB: sahibe sor")
            return res
    wcfg = dict(cfg, repos={g: _group_repo(cfg, g) for g in remotes})
    if "claude" not in remotes:
        wcfg["repo_dir"] = ""             # doğrulanmamış (public olabilir) repo_dir'e ASLA yazma
    written, sigs, stats = _write_changed(plan, wcfg)
    res.update(applied=True, written=len(written), redacted=stats["redacted"], skipped_big=stats["skipped_big"], missing=missing)
    for g in sorted(remotes):
        stats["days"].setdefault(g, {})
    for g, days in sorted(stats["days"].items()):
        if g not in remotes:
            continue
        repo, rems = _group_repo(cfg, g), remotes[g]
        rc, por = _git(repo, "status", "--porcelain", "-z", "--untracked-files=all", "--", "local", "memory")
        if rc == 0:                       # önceki yarım çalışmadan kalan (içerik aynı olduğu için _put'un yazmadığı) dosyaları da commit'le
            for rel in _porcelain_z_paths(por):   # -z: Türkçe/boşluklu adlar tırnaksız gelir
                if rel and not any(rel in v for v in days.values()):
                    try:
                        d = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(repo, rel))).strftime("%F")
                    except OSError:
                        d = datetime.date.today().isoformat()
                    days.setdefault(d, []).append(rel)
        for day in sorted(days):          # her takvim günü ayrı commit, eskiden yeniye
            files = days[day]
            rc, out = _git(repo, "add", "--", *files)
            if rc != 0:
                res.update(ok=False, msg=f"{g} git add: " + out[-200:])
                return res
            rc, out = _git_dated(repo, day, "commit", "-q", "-m", f"sohbet yedegi {day}: {len(files)} dosya", "--", *files)
            if rc != 0:
                res.update(ok=False, msg=f"{g} git commit: " + out[-200:])
                return res
        try:                              # INDEX.jsonl/INDEX.md (yalnız açık yollar); hata yedeği durdurmaz
            from . import chat_index
            import socket
            rc, lst = _git(repo, "ls-files", "-z", "--", "local", "memory")
            if rc == 0:
                idx = chat_index.write_index(repo, [x for x in lst.split("\0") if x], re.sub(r"[^A-Za-z0-9._-]+", "-", socket.gethostname()))
                _git(repo, "add", "--", *idx)
                _git_dated(repo, datetime.date.today().isoformat(), "commit", "-q", "-m", "INDEX guncellendi", "--", *idx)
        except Exception as e:  # noqa: BLE001
            diag_log(f"periodic chat_backup: INDEX hatası {type(e).__name__}: {e}")
        head = _git(repo, "rev-parse", "HEAD")[1].strip()
        for name in rems:
            if not days:                  # bu çalışmada yeni commit yok: yalnız uzak geride ise it (yarım kalan itmeyi tamamlar)
                rc0, o0 = _git(repo, "ls-remote", name, "HEAD")
                if rc0 == 0 and o0.startswith(head[:12]):
                    continue
            args = ["push", "-q", name, "HEAD"]
            if "github.com" in rems[name]:
                args = ["-c", "credential.helper=!gh auth git-credential", *args]
            rc, out = _git(repo, *args, timeout=3600)
            if rc != 0:
                res.update(ok=False, msg=f"{g} push {name}: " + out[-200:])
                return res
            rc, out = _git(repo, "ls-remote", name, "HEAD")
            if rc != 0 or not out.startswith(head[:12]):
                res.update(ok=False, msg=f"{g} ls-remote {name} eşleşmedi")
                return res
    done = {e["src"]: sigs[e["src"]] for e in plan["changed"] if e["src"] in sigs}
    for k, v in (plan.get("marks") or {}).items():       # zaten yedekli (değişmemiş) hedefler için işareti geriye dönük yaz
        if int(manifest.get(k, "0") or 0) < int(v):
            done[k] = v
    done.update({_DEST_PFX + e["dest"]: sigs[_DEST_PFX + e["dest"]] for e in plan["changed"] if _DEST_PFX + e["dest"] in sigs})
    manifest.update(done)
    state.setdefault("chat_backup", {})["manifest"] = manifest
    if dump_info:
        res["dump"] = dump_info
        if dump_info.get("errors") or dump_info.get("raw_err"):
            res["ok"] = False
    res["msg"] = f"{len(written)} dosya yazıldı/gönderildi, {stats['redacted']} sır maskelendi" + (
        f"; db dökümü {dump_info.get('dumped', 0)} db/{dump_info.get('files', 0)} dosya" if dump_info else "") + (
        f"; DÖKÜM HATASI {(dump_info.get('errors') or [dump_info.get('raw_err')])[0]}" if dump_info and not res["ok"] else "") + (
        f"; repo'suz atlanan: {stats['skipped_group']}" if stats["skipped_group"] else "")
    return res


# ------------------------------------------------------------------ kullanıcı tanımlı işler
RUNS_DIR = os.path.join(CLAUDEOPS_DIR, "periodic_runs")


def _save_output(name: str, text: str) -> str:
    d = os.path.join(RUNS_DIR, name)
    os.makedirs(d, mode=0o700, exist_ok=True)
    path = os.path.join(d, datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    runs = sorted(os.listdir(d))
    for old in runs[:-30]:          # son 30 çıktı
        try:
            os.remove(os.path.join(d, old))
        except OSError:
            pass
    return path


def _quota_blocked() -> bool:
    try:
        from .commands import web_steward
        return bool(web_steward.quota_blocking())
    except Exception:  # noqa: BLE001 — kota durumu okunamazsa engelleme yok (bekçi kapalıysa zaten karar yok)
        return False


def run_custom(cfg: Dict[str, Any], apply: bool, state: Dict[str, Any]) -> Dict[str, Any]:
    """command: kabuksuz argv; prompt: `claude -p` (tek tur, oturum kalıcılığı yok, CLAUDE* ortamı süzülür). Çıktı periodic_runs/<ad>/."""
    name = str(cfg.get("_name") or "job")
    kind = cfg.get("kind")
    if not apply:
        return {"ok": True, "msg": f"plan: {kind} işi çalışırdı", "applied": False}
    timeout = int(float(cfg.get("timeout_s") or 900))
    cwd = os.path.expanduser(str(cfg.get("cwd") or "")) or os.path.join(CLAUDEOPS_DIR, "periodic_runs")
    os.makedirs(cwd, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    if kind == "prompt":
        if _is_on(cfg.get("skip_when_quota_blocked")) and _quota_blocked():
            return {"ok": True, "msg": "kota engelli (drain/shutdown): atlandı", "applied": False, "skipped": True}
        exe = shutil.which("claude")
        if not exe:
            return {"ok": False, "msg": "claude bulunamadı"}
        argv = [exe, "-p", str(cfg.get("prompt") or ""), "--no-session-persistence"]
        if cfg.get("model"):
            argv += ["--model", str(cfg["model"])]
        if cfg.get("effort"):
            argv += ["--effort", str(cfg["effort"])]
    else:
        try:
            argv = shlex.split(str(cfg.get("command") or ""))
        except ValueError as e:
            return {"ok": False, "msg": f"command ayrıştırılamadı: {e}"}
        if not argv:
            return {"ok": False, "msg": "command boş"}
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "msg": f"zaman aşımı ({timeout} sn)"}
    except OSError as e:
        return {"ok": False, "msg": f"başlatılamadı: {e}"}
    out_path = _save_output(name, (p.stdout or "") + ("\n--- stderr ---\n" + p.stderr if p.stderr else ""))
    tail = (p.stdout or p.stderr or "").strip().splitlines()[-1:] or [""]
    return {"ok": p.returncode == 0, "applied": True, "rc": p.returncode, "output": out_path,
            "msg": f"rc={p.returncode} çıktı {os.path.basename(out_path)}: {tail[0][:120]}"}


# ------------------------------------------------------------------ kayıt + döngü
class Job:
    def __init__(self, name: str, defaults: Dict[str, Any], runner: Callable[[Dict[str, Any], bool, Dict[str, Any]], Dict[str, Any]]):
        self.name, self.defaults, self.runner = name, defaults, runner


DEFAULT_MEMORY_PRV: Dict[str, Any] = {
    "enabled": "off",            # sahip `--apply` tablosunu onaylayınca "on" (13 Kas: önce dry-run)
    "schedule": "",
    "start": "04:10",
    "interval_hours": 24,
}


def run_memory_prv(cfg: Dict[str, Any], apply: bool, state: Dict[str, Any]) -> Dict[str, Any]:
    """Hafıza -> -prv (`memory_backup.run_prv`). Oluşturulan repolar günlük özette (msg) bildirilir; sır/çakışma gibi atlananlar sayılır."""
    from .commands import memory_backup as mb
    ents, failed = mb.run_prv(mb.PROJECTS_ROOT, apply, [])
    ok = [e for e in ents if e["status"] == "ok"]
    created = sorted({n for e in ok if apply and str(e.get("result", "")).startswith("yedeklendi") for (_k, n, ex) in e.get("creates", []) if not ex})
    skipped = [e for e in ents if e["status"] != "ok" and "sahibe bildir" in e.get("reason", "")]
    secret = [e.get("roster_name") or e["proj"] for e in ents if e.get("reason", "").startswith("sır taraması")]
    msg = (f"{len(ok)} proje" + (f", {failed} hata" if failed else "") + (f", oluşturulan: {', '.join(created)}" if created else "")
           + (f", SIR TARAMASINDA TAKILAN: {', '.join(secret)}" if secret else "") + ("" if apply else " (plan)"))
    return {"ok": failed == 0, "msg": msg, "applied": apply, "created": created, "secret": secret, "skipped": len(skipped)}


JOBS: Dict[str, Job] = {"chat_backup": Job("chat_backup", DEFAULT_CHAT_BACKUP, run_chat_backup),
                        "memory_prv": Job("memory_prv", DEFAULT_MEMORY_PRV, run_memory_prv)}
_LOCK = threading.Lock()


def _proc_lock_path() -> str:
    return os.path.join(str(CLAUDEOPS_DIR), "periodic.lock")


def _acquire_proc_lock() -> Optional[int]:
    """Süreçler arası (servis + CLI) tek iş: flock; alınamazsa None. Süreç ölünce kilit kendiliğinden düşer."""
    try:
        os.makedirs(os.path.dirname(_proc_lock_path()), exist_ok=True)
        fd = os.open(_proc_lock_path(), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return -1                      # kilit dosyası açılamıyorsa thread kilidiyle devam
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        os.close(fd)
        return None


def run_job(name: str, apply: bool = True) -> Dict[str, Any]:
    """Tek işi çalıştırır, durumu yazar. Aynı anda tek iş (kilit); asla fırlatmaz."""
    if name not in load_config():
        return {"ok": False, "msg": f"bilinmeyen iş: {name}"}
    if not _LOCK.acquire(blocking=False):
        return {"ok": False, "msg": "başka bir periyodik iş çalışıyor"}
    pfd = _acquire_proc_lock()
    if pfd is None:
        _LOCK.release()
        return {"ok": False, "msg": "başka bir süreçte periyodik iş çalışıyor (flock)"}
    try:
        state = load_state()
        cfg = load_config()[name]
        cfg["_name"] = name
        if apply:
            state.setdefault(name, {})["last_start"] = time.time()
        try:
            runner = JOBS[name].runner if name in JOBS else run_custom
            res = runner(cfg, apply, state)
        except Exception as e:  # noqa: BLE001 — servis thread'i hiçbir hatada ölmemeli
            res = {"ok": False, "msg": f"istisna: {type(e).__name__}: {e}"}
        if apply:
            st = state.setdefault(name, {})
            st["last_end"] = time.time()
            st["last_ok"] = bool(res.get("ok"))
            st["last_msg"] = str(res.get("msg") or "")[:300]
            _notify_failure(name, res, st)
            save_state(state)
            diag_log(f"periodic {name}: {'ok' if res.get('ok') else 'HATA'} {res.get('msg', '')}")
        return res
    finally:
        if pfd is not None and pfd >= 0:
            os.close(pfd)              # kapatınca flock düşer
        _LOCK.release()


NOTIFY_COOLDOWN_S = 6 * 3600


def _notify_failure(name: str, res: Dict[str, Any], st: Dict[str, Any], now: Optional[float] = None) -> bool:
    """Başarısız koşuda ntfy (best-effort). Aynı iş için 6 saatte en fazla bir bildirim (spam yok); başarıda sayaç sıfırlanır."""
    now = time.time() if now is None else now
    if res.get("ok"):
        st.pop("last_notify", None)
        return False
    if now - float(st.get("last_notify") or 0) < NOTIFY_COOLDOWN_S:
        return False
    try:
        from .commands import web_steward
        sent = bool(web_steward.notify_phone(f"periodic {name}: HATA {str(res.get('msg') or '')[:200]}", title="claudeops periyodik"))
    except Exception as e:  # noqa: BLE001 — bildirim hatası işi bozmasın
        diag_log(f"periodic {name}: bildirim hatası {type(e).__name__}")
        return False
    if sent:
        st["last_notify"] = now
    return sent


def tick(now: Optional[datetime.datetime] = None) -> List[str]:
    """Zamanı gelen işleri çalıştırır; çalıştırılan iş adları döner."""
    ran: List[str] = []
    cfgs = load_config()
    state = load_state()
    for name in list(cfgs):
        if is_due(cfgs[name], state.get(name) or {}, now):
            run_job(name, apply=True)
            ran.append(name)
            state = load_state()
    return ran


def _loop() -> None:
    time.sleep(30)
    while True:
        try:
            tick()
        except Exception as e:  # noqa: BLE001
            diag_log(f"periodic döngü: {type(e).__name__}: {e}")
        time.sleep(_WAKE_SECONDS)


_started = False


def start() -> None:
    """Servis başlarken bir kez (web.run). Hiçbir iş AÇIK değilse tick ucuzdur (iki küçük dosya okuma)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="periodic").start()


# ------------------------------------------------------------------ API / CLI ortak katmanı
def overview() -> Dict[str, Any]:
    """Panel/CLI için: her iş ayarı + son durum (manifest hariç). Salt okur."""
    cfgs = load_config()
    state = load_state()
    jobs: Dict[str, Any] = {}
    for name, cfg in cfgs.items():
        st = {k: v for k, v in (state.get(name) or {}).items() if k != "manifest"}
        pub = {k: v for k, v in cfg.items() if not k.startswith("_")}
        jobs[name] = {"config": pub, "builtin": bool(cfg.get("_builtin")), "state": st, "due": is_due(cfg, state.get(name) or {})}
    return {"ok": True, "jobs": jobs, "defaults_custom": CUSTOM_DEFAULTS}


def api_action(data: Dict[str, Any]) -> Dict[str, Any]:
    """{action: add|set|remove|run, id, fields?, apply?}. Yalnız insan (web.py ajan çağrısını 403'ler)."""
    act = str(data.get("action") or "")
    cid = str(data.get("id") or "")
    try:
        if act == "add":
            return {"ok": True, "config": add_custom(cid, dict(data.get("fields") or {}))}
        if act == "set":
            return {"ok": True, "config": set_config(cid, dict(data.get("fields") or {}))}
        if act == "remove":
            return {"ok": remove_custom(cid)} if cid not in JOBS else {"ok": False, "error": "yerleşik iş silinmez (enabled=off yap)"}
        if act == "run":
            return run_job(cid, apply=bool(data.get("apply")))
    except (KeyError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "action add|set|remove|run olmalı"}
