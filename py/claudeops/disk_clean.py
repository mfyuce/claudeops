"""Periyodik GÜVENLİ disk temizliği (çekirdek/OSS; enterprise import YOK). Sahip kararı 20 Kas: yalnız şunlar otomatik:
  1. cargo target: ~/.cargo-target* ve proje `target/` dizinleri, >N gün (14) hiçbir dosyası değişmemiş VE cargo/rustc çalışmıyorken;
  2. `docker builder prune` (paylaşımlı hostta varsayılan KAPALI: ortak daemon, başkasının önbelleğini siler);
  3. /tmp/claude-<kendi uid> altında eski scratchpad: >N gün (3) dokunulmamış ve hiçbir süreç içinde çalışmıyor/dosya tutmuyor.
Yalnız KENDİ uid'inin dosyaları, sembolik bağlar izlenmez/silinmez. `mode=dry`: yalnız hesapla ve günlüğe yaz. Her koşu
`disk_cleanup.jsonl`'e bir satır (aday, bayt, silinen) bırakır; sonuç periodic durumunda ve /api/status'ta görünür."""
import json
import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from .paths import CLAUDEOPS_DIR

LOG = os.path.join(CLAUDEOPS_DIR, "disk_cleanup.jsonl")
_COMPILERS = ("cargo", "rustc")
_SKIP_DIRS = {".git", "node_modules", "target", ".venv", "venv", "__pycache__", ".cache"}


def uid() -> int:
    return os.getuid()


def compilers_running(proc: str = "/proc") -> bool:
    """cargo/rustc (kendi uid'imizin değil, HERHANGİ bir kullanıcının) çalışıyor mu: ortak target'ı kullanıyor olabilir."""
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return True            # okunamıyorsa güvenli taraf: çalışıyor say
    for p in pids:
        try:
            with open(f"{proc}/{p}/comm", encoding="utf-8", errors="replace") as f:
                if f.read().strip() in _COMPILERS:
                    return True
        except OSError:
            continue
    return False


def tree_info(path: str, newer_than: Optional[float] = None) -> Tuple[int, float, bool]:
    """(toplam bayt, en yeni mtime, sahip_hepsi_bizim). `newer_than` verilirse o zamandan yeni dosya görülür görülmez erken çıkar
    (boyut kısmi olur; çağıran zaten reddedecek). Sembolik bağlar izlenmez."""
    total, newest, ours = 0, 0.0, True
    me = uid()
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if st.st_uid != me:
                        ours = False
                    total += st.st_size
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)       # dizin mtime'ı yaş ölçüsü DEĞİL (içerik değişince/oluşunca güncellenir): yalnız dosyalar
                        continue
                    newest = max(newest, st.st_mtime)
                    if newer_than is not None and newest > newer_than:
                        return total, newest, ours
        except OSError:
            continue
    if newest == 0.0:                  # hiç dosya yok: kökün kendi mtime'ı
        try:
            newest = os.lstat(path).st_mtime
        except OSError:
            pass
    return total, newest, ours


def _held_by_process(path: str, proc: str = "/proc") -> bool:
    """Kendi uid'imizin bir süreci cwd'si ya da açık dosyasıyla `path` altında mı (oturum hâlâ içinde çalışıyor)."""
    pre = os.path.realpath(path) + os.sep
    me = uid()
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return True
    for p in pids:
        try:
            if os.stat(f"{proc}/{p}").st_uid != me:
                continue
        except OSError:
            continue
        links = [f"{proc}/{p}/cwd"]
        try:
            links += [f"{proc}/{p}/fd/{fd}" for fd in os.listdir(f"{proc}/{p}/fd")]
        except OSError:
            pass
        for l in links:
            try:
                t = os.readlink(l)
            except OSError:
                continue
            if (t + os.sep).startswith(pre) or t == pre.rstrip(os.sep):
                return True
    return False


def cargo_candidates(roots: List[str], idle_days: float, now: float) -> List[Dict[str, Any]]:
    """`~/.cargo-target*` (kök listesinde glob önceden açılmış) + kök altında (derinlik<=5) `target/` (yanında Cargo.toml ya da
    CACHEDIR.TAG). Yaş: dizindeki EN YENİ dosya mtime'ı."""
    cutoff = now - idle_days * 86400
    found: List[str] = []
    for r in roots:
        r = os.path.expanduser(r)
        if not os.path.isdir(r) or os.path.islink(r):
            continue
        base = os.path.basename(r.rstrip(os.sep))
        if base.startswith(".cargo-target"):
            found.append(r)
            continue
        depth0 = r.rstrip(os.sep).count(os.sep)
        for d, dirs, _files in os.walk(r, followlinks=False):
            if d.count(os.sep) - depth0 > 5:
                dirs[:] = []
                continue
            if "target" in dirs:
                td = os.path.join(d, "target")
                if not os.path.islink(td) and (os.path.isfile(os.path.join(td, "CACHEDIR.TAG")) or os.path.isfile(os.path.join(d, "Cargo.toml"))):
                    found.append(td)
            dirs[:] = [x for x in dirs if x not in _SKIP_DIRS and not os.path.islink(os.path.join(d, x))]
    out = []
    for d in sorted(set(found)):
        size, newest, ours = tree_info(d, newer_than=cutoff)
        out.append({"kind": "cargo", "path": d, "bytes": size, "newest": newest, "idle_days": round((now - newest) / 86400, 1),
                    "eligible": newest <= cutoff and ours, "why": "" if newest <= cutoff and ours else
                    ("başkasının dosyası var" if not ours else f"son {idle_days:g} günde değişmiş")})
    return out


def scratch_candidates(idle_days: float, now: float, tmp_root: str = "/tmp", held=None) -> List[Dict[str, Any]]:
    """/tmp/claude-<uid>/<proje>/<oturum> dizinleri: >N gün dokunulmamış ve süreç tutmuyor."""
    held = held or _held_by_process
    root = os.path.join(tmp_root, f"claude-{uid()}")
    cutoff = now - idle_days * 86400
    out: List[Dict[str, Any]] = []
    try:
        st = os.lstat(root)
    except OSError:
        return out
    if os.path.islink(root) or st.st_uid != uid():
        return out
    for proj in sorted(os.listdir(root)):
        pdir = os.path.join(root, proj)
        if os.path.islink(pdir) or not os.path.isdir(pdir):
            continue
        for sess in sorted(os.listdir(pdir)):
            sdir = os.path.join(pdir, sess)
            if os.path.islink(sdir) or not os.path.isdir(sdir):
                continue
            size, newest, ours = tree_info(sdir, newer_than=cutoff)
            elig, why = newest <= cutoff and ours, ""
            if not ours:
                why = "başkasının dosyası var"
            elif newest > cutoff:
                why = f"son {idle_days:g} günde değişmiş"
            elif held(sdir):
                elig, why = False, "bir süreç içinde çalışıyor"
            out.append({"kind": "scratch", "path": sdir, "bytes": size, "newest": newest,
                        "idle_days": round((now - newest) / 86400, 1), "eligible": elig, "why": why})
    return out


def _remove(path: str) -> Tuple[bool, str]:
    if os.path.islink(path):
        return False, "sembolik bağ"
    try:
        shutil.rmtree(path)
        return True, ""
    except OSError as e:
        return False, f"{e.__class__.__name__}: {e.strerror or e}"[:120]


def docker_prune(apply: bool, until: str = "72h", runner=subprocess.run) -> Dict[str, Any]:
    if not shutil.which("docker"):
        return {"kind": "docker", "ran": False, "why": "docker yok", "bytes": 0}
    if not apply:
        return {"kind": "docker", "ran": False, "why": "kuru çalıştırma", "bytes": 0}
    try:
        r = runner(["docker", "builder", "prune", "-f", "--filter", f"until={until}"], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return {"kind": "docker", "ran": False, "why": e.__class__.__name__, "bytes": 0}
    freed = 0
    for line in (r.stdout or "").splitlines():
        if line.lower().startswith("total reclaimed space:"):
            freed = _parse_size(line.split(":", 1)[1].strip())
    return {"kind": "docker", "ran": r.returncode == 0, "why": "" if r.returncode == 0 else (r.stderr or "").strip()[:120], "bytes": freed}


def _parse_size(s: str) -> int:
    units = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12, "KIB": 1024, "MIB": 1024 ** 2, "GIB": 1024 ** 3}
    parts = s.replace(",", ".").split()
    try:
        num = float(parts[0].rstrip("BKMGTiIb") or 0) if len(parts) == 1 else float(parts[0])
        unit = parts[1].upper() if len(parts) > 1 else "".join(c for c in parts[0] if c.isalpha()).upper() or "B"
        return int(num * units.get(unit, 1))
    except (ValueError, IndexError):
        return 0


def disk_pct(path: str = "/") -> int:
    u = shutil.disk_usage(path)
    return int(round(u.used * 100 / u.total)) if u.total else 0


def run(cfg: Dict[str, Any], apply: bool, now: Optional[float] = None, *, tmp_root: str = "/tmp",
        compilers=compilers_running) -> Dict[str, Any]:
    """Bir temizlik koşusu. `apply` yanlış ya da cfg.mode=dry ise hiçbir şey silinmez. Sonuç özeti + günlük satırı."""
    now = now or time.time()
    do = bool(apply) and str(cfg.get("mode", "on")).lower() != "dry"
    items: List[Dict[str, Any]] = []
    notes: List[str] = []
    if str(cfg.get("cargo", "on")).lower() not in ("off", "0", "false"):
        if compilers():
            notes.append("cargo/rustc çalışıyor: cargo target atlandı")
        else:
            roots = [p for r in (cfg.get("cargo_roots") or []) for p in _glob(r)]
            items += cargo_candidates(roots, float(cfg.get("cargo_idle_days") or 14), now)
    if str(cfg.get("scratch", "on")).lower() not in ("off", "0", "false"):
        items += scratch_candidates(float(cfg.get("scratch_idle_days") or 3), now, tmp_root)
    freed, removed = 0, 0
    for it in items:
        it["removed"] = False
        if it["eligible"] and do:
            ok, why = _remove(it["path"])
            it["removed"] = ok
            if ok:
                freed += it["bytes"]
                removed += 1
            else:
                it["why"] = why
    if str(cfg.get("docker", "off")).lower() in ("on", "1", "true"):
        d = docker_prune(do)
        items.append(d)
        freed += d["bytes"]
    elig = [i for i in items if i.get("eligible")]
    res = {"ok": True, "applied": do, "mode": "on" if do else "dry", "disk_pct": disk_pct(), "candidates": len(elig),
           "candidate_bytes": sum(i["bytes"] for i in elig), "removed": removed, "freed_bytes": freed, "notes": notes, "at": now}
    _log({**res, "items": [{k: v for k, v in i.items() if k != "newest"} for i in items if i.get("eligible") or i["kind"] == "docker"]})
    return res


def _glob(pattern: str) -> List[str]:
    import glob
    p = os.path.expanduser(pattern)
    return sorted(glob.glob(p)) if any(c in p for c in "*?[") else [p]


def _log(rec: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def fmt_bytes(n: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f} {u}" if u != "B" else f"{n} B"
        n /= 1024.0
    return f"{n} B"
