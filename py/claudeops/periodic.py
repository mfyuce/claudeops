"""Periyodik işler (cops periodic) — claudeops servisi içinde, kendi ayarlarıyla çalışan günlük/saatlik işler.

Sahip isteği (2026-11-05, "todo:"): "cops periodic jobs; günlük uzak/yakın tüm biten/değişen chatleri alıp gh/glab prv repoya
atan; kendi ayarları olur; başlama ayarları bizim seçeneklere benzer; copschats-prv repo". crontab KULLANILMAZ (sınıflandırıcı
'persistence' diye engeller); servis içi thread, `model_freshness` ile aynı desen.

Ayar dosyası `CLAUDEOPS_DIR/periodic.json` (settings.json'a DOKUNMAZ):
  {"jobs": {"chat_backup": {"enabled": "off", "start": "03:30", "interval_hours": 24, ...}}}
`enabled`: "on" | "off" (varsayılan KAPALI; `_OFF_WORDS` kapatır). Durum `periodic_state.json` (son başlangıç, sonuç, manifest).
Görev işleyicileri `JOBS`'ta; yeni iş = bir `Job` kaydı eklemek.

chat_backup: `~/.claude/projects/**/*.jsonl` + `history.jsonl` içinde YENİ/DEĞİŞEN dosyaları sır-maskeleyip gzip'leyerek
`repo_dir` (varsayılan ~/work/projects/tmp/copschats-prv) altına koyar, YALNIZ o açık yolları `git add` + commit + push eder
(tüm remote'lar, ikisi de PRIVATE doğrulanır, push sonrası ls-remote). Uzak host kaynakları `sources`ta tanımlıdır
(şimdilik yalnız "local"; uzak = TODO).
"""
from __future__ import annotations

import datetime
import gzip
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
    re.compile(r"(?i)((?:password|passwd|pwd|parola|şifre)\s*[=:]\s*['\"]?)[^\s'\"<>$*,}\\]{4,}"),
]

DEFAULT_CHAT_BACKUP: Dict[str, Any] = {
    "enabled": "off",
    "schedule": "",              # 5 alanlı cron ("30 3 * * *"); doluysa start/interval_hours YOK SAYILIR
    "start": "03:30",            # günlük işlerde en erken başlama saati (yerel)
    "interval_hours": 24,        # >=24: günde bir (start sonrası); <24: son başlangıçtan bu kadar saat sonra
    "repo_dir": os.path.join("~", "work", "projects", "tmp", "copschats-prv"),
    "repo_name": "copschats-prv",
    "sources": ["local"],        # ileride: "yuhem", "ulak_31"
    "max_file_mb": 50,           # gzip SONRASI tek dosya sınırı (GitHub 100 MB); aşan atlanır, günlüğe yazılır
    "max_repo_mb": 3000,         # çalışma ağacı sınırı; aşılırsa iş durur (sahibe sorulur)
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


def _gz(data: bytes) -> bytes:
    """Belirlenimli gzip (mtime=0): aynı içerik = aynı bayt, git gereksiz fark görmez."""
    import io
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=6) as g:
        g.write(data)
    return buf.getvalue()


def _git(repo: str, *args: str, timeout: int = 300) -> Tuple[int, str]:
    """Tek git çıkış kapısı (testlerde yamalanır)."""
    try:
        p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def _local_sources() -> List[Tuple[str, str]]:
    """(kaynak yol, repo içi göreli hedef öneki) çiftleri: yalnız Claude Code transkriptleri + prompt geçmişi."""
    home = os.path.expanduser("~")
    return [(os.path.join(home, ".claude", "projects"), os.path.join("local", "claude-projects")),
            (os.path.join(home, ".claude", "history.jsonl"), os.path.join("local", "claude-history"))]


def _walk_jsonl(src: str) -> List[str]:
    if os.path.isfile(src):
        return [src]
    out: List[str] = []
    for root, _d, files in os.walk(src):
        out.extend(os.path.join(root, f) for f in files if f.endswith(".jsonl"))
    return sorted(out)


def plan_chat_backup(cfg: Dict[str, Any], manifest: Dict[str, str]) -> Dict[str, Any]:
    """Yeni/değişen dosyaları bulur (boyut+mtime imzası). Dosya OKUNMAZ/YAZILMAZ; saf plan."""
    repo = os.path.expanduser(str(cfg["repo_dir"]))
    todo: List[Dict[str, Any]] = []
    seen = 0
    for src, prefix in _local_sources():
        if not os.path.exists(src):
            continue
        for f in _walk_jsonl(src):
            seen += 1
            try:
                stt = os.stat(f)
            except OSError:
                continue
            rel = os.path.relpath(f, src) if os.path.isdir(src) else os.path.basename(f)
            sig = f"{stt.st_size}:{int(stt.st_mtime)}"
            if manifest.get(f) == sig:
                continue
            todo.append({"src": f, "sig": sig, "dest": os.path.join(prefix, rel + ".gz")})
    return {"repo": repo, "seen": seen, "changed": todo}


def _write_changed(plan: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[List[str], Dict[str, str], Dict[str, Any]]:
    """Değişenleri maskeleyip gzip'leyerek repo çalışma ağacına yazar. (yazılan göreli yollar, yeni manifest girdileri, istatistik)."""
    repo = plan["repo"]
    limit = int(float(cfg.get("max_file_mb") or 50) * 1024 * 1024)
    written: List[str] = []
    sigs: Dict[str, str] = {}
    stats = {"redacted": 0, "skipped_big": [], "unchanged": 0}
    for ent in plan["changed"]:
        try:
            with open(ent["src"], "rb") as f:
                raw = f.read()
        except OSError:
            continue
        text, n = redact(raw.decode("utf-8", errors="replace"))
        stats["redacted"] += n
        blob = _gz(text.encode("utf-8"))
        if len(blob) > limit:
            stats["skipped_big"].append(ent["src"])
            continue
        dest = os.path.join(repo, ent["dest"])
        if os.path.exists(dest):
            try:
                with open(dest, "rb") as f:
                    if hashlib.sha256(f.read()).digest() == hashlib.sha256(blob).digest():
                        sigs[ent["src"]] = ent["sig"]
                        stats["unchanged"] += 1
                        continue
            except OSError:
                pass
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        os.replace(tmp, dest)
        written.append(ent["dest"])
        sigs[ent["src"]] = ent["sig"]
    return written, sigs, stats


def _tree_mb(repo: str) -> float:
    total = 0
    for root, dirs, files in os.walk(repo):
        if ".git" in dirs:
            dirs.remove(".git")
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


def run_chat_backup(cfg: Dict[str, Any], apply: bool, state: Dict[str, Any]) -> Dict[str, Any]:
    """Plan (apply=False) ya da uygula. Sonuç dict'i: ok, msg, written, ... Asla fırlatmaz."""
    manifest: Dict[str, str] = dict((state.get("chat_backup") or {}).get("manifest") or {})
    plan = plan_chat_backup(cfg, manifest)
    repo = plan["repo"]
    res: Dict[str, Any] = {"ok": True, "seen": plan["seen"], "changed": len(plan["changed"]), "repo": repo, "applied": False}
    if "local" not in (cfg.get("sources") or []):
        res.update(ok=False, msg="kaynak listesinde 'local' yok")
        return res
    if not os.path.isdir(os.path.join(repo, ".git")):
        res.update(ok=False, msg=f"repo yok: {repo} (önce private {cfg.get('repo_name')} oluştur: gh/glab, iki remote; sahip onayı)")
        return res
    rems, bad = _private_remotes(repo)
    if not rems:
        res.update(ok=False, msg="repoda remote yok")
        return res
    if bad:
        res.update(ok=False, msg="private doğrulanamadı: " + ", ".join(bad))
        return res
    if not apply:
        res["msg"] = f"plan: {len(plan['changed'])} yeni/değişen dosya ({plan['seen']} taranan); yazılmadı"
        return res
    if _tree_mb(repo) > float(cfg.get("max_repo_mb") or 3000):
        res.update(ok=False, msg=f"repo {int(_tree_mb(repo))} MB > sınır {cfg.get('max_repo_mb')} MB: sahibe sor")
        return res
    written, sigs, stats = _write_changed(plan, cfg)
    res.update(applied=True, written=len(written), redacted=stats["redacted"], skipped_big=stats["skipped_big"])
    if written:
        rc, out = _git(repo, "add", "--", *written)
        if rc != 0:
            res.update(ok=False, msg="git add: " + out[-200:])
            return res
        stamp = datetime.datetime.now().strftime("%F %H:%M")
        rc, out = _git(repo, "commit", "-q", "-m", f"sohbet yedegi {stamp}: {len(written)} dosya", "--", *written)
        if rc != 0:
            res.update(ok=False, msg="git commit: " + out[-200:])
            return res
        head = _git(repo, "rev-parse", "HEAD")[1].strip()
        for name in rems:
            args = ["push", "-q", name, "HEAD"]
            if "github.com" in rems[name]:
                args = ["-c", "credential.helper=!gh auth git-credential", *args]
            rc, out = _git(repo, *args, timeout=900)
            if rc != 0:
                res.update(ok=False, msg=f"push {name}: " + out[-200:])
                return res
            rc, out = _git(repo, "ls-remote", name, "HEAD")
            if rc != 0 or not out.startswith(head[:12]):
                res.update(ok=False, msg=f"ls-remote {name} eşleşmedi")
                return res
    manifest.update(sigs)
    st = state.setdefault("chat_backup", {})
    st["manifest"] = manifest
    res["msg"] = f"{len(written)} dosya yazıldı/gönderildi, {stats['redacted']} sır maskelendi" + (
        f", {len(stats['skipped_big'])} büyük dosya atlandı" if stats["skipped_big"] else "")
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


JOBS: Dict[str, Job] = {"chat_backup": Job("chat_backup", DEFAULT_CHAT_BACKUP, run_chat_backup)}
_LOCK = threading.Lock()


def run_job(name: str, apply: bool = True) -> Dict[str, Any]:
    """Tek işi çalıştırır, durumu yazar. Aynı anda tek iş (kilit); asla fırlatmaz."""
    if name not in load_config():
        return {"ok": False, "msg": f"bilinmeyen iş: {name}"}
    if not _LOCK.acquire(blocking=False):
        return {"ok": False, "msg": "başka bir periyodik iş çalışıyor"}
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
            save_state(state)
            diag_log(f"periodic {name}: {'ok' if res.get('ok') else 'HATA'} {res.get('msg', '')}")
        return res
    finally:
        _LOCK.release()


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
