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
    found = _find_targets(roots)
    out = []
    for d in found:
        size, newest, ours = tree_info(d, newer_than=cutoff)
        out.append({"kind": "cargo", "path": d, "bytes": size, "newest": newest, "idle_days": round((now - newest) / 86400, 1),
                    "eligible": newest <= cutoff and ours, "why": "" if newest <= cutoff and ours else
                    ("başkasının dosyası var" if not ours else f"son {idle_days:g} günde değişmiş")})
    return out


def _find_targets(roots: List[str]) -> List[str]:
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
    return sorted(set(found))


def _norm(x: str) -> str:
    return x.replace("-", "_")


def _unit_age(fp_dir: str) -> float:
    """Birimin son KULLANIM zamanı: cargo her çağrıda `invoked.timestamp`i dokunur (değişmeyen bağımlılığın artifact mtime'ı
    eski kalır, yaş ölçüsü o OLAMAZ); yoksa parmak izi dizinindeki en yeni dosya."""
    ts = os.path.join(fp_dir, "invoked.timestamp")
    try:
        return os.lstat(ts).st_mtime
    except OSError:
        pass
    newest = 0.0
    try:
        for e in os.scandir(fp_dir):
            try:
                newest = max(newest, e.stat(follow_symlinks=False).st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return newest or os.lstat(fp_dir).st_mtime


def _path_bytes(p: str) -> int:
    try:
        if os.path.isdir(p) and not os.path.islink(p):
            return tree_info(p)[0]
        return os.lstat(p).st_size
    except OSError:
        return 0


def _profile_dirs(target: str) -> List[str]:
    """`target/<profil>` ve `target/<üçlü>/<profil>`: içinde `.fingerprint` olan dizinler (derinlik <= 2)."""
    out = []
    try:
        for e in os.scandir(target):
            if not e.is_dir(follow_symlinks=False):
                continue
            if os.path.isdir(os.path.join(e.path, ".fingerprint")):
                out.append(e.path)
                continue
            try:
                for e2 in os.scandir(e.path):
                    if e2.is_dir(follow_symlinks=False) and os.path.isdir(os.path.join(e2.path, ".fingerprint")):
                        out.append(e2.path)
            except OSError:
                continue
    except OSError:
        pass
    return sorted(out)


def cargo_sweep_candidates(roots: List[str], idle_days: float, now: float) -> List[Dict[str, Any]]:
    """ARTIFACT düzeyi (cargo-sweep benzeri): aktif target'larda her profil için `.fingerprint/<birim>` yaşı `idle_days`ten büyük
    birimlerin parmak izi + deps/build/examples çıktıları. Hedef dizinin tamamı yaşlanmasa da çalışır (her gün kullanılan
    `~/.cargo-target`te biriken eski sürümler). Profil başına TEK aday (`paths` listesi); yalnız kendi uid'imizin dosyaları."""
    cutoff = now - idle_days * 86400
    me = uid()
    out: List[Dict[str, Any]] = []
    for t in _find_targets(roots):
        for prof in _profile_dirs(t):
            fp = os.path.join(prof, ".fingerprint")
            stale: List[str] = []
            try:
                entries = [e for e in os.scandir(fp) if e.is_dir(follow_symlinks=False)]
            except OSError:
                continue
            for e in entries:
                try:
                    if e.stat(follow_symlinks=False).st_uid != me:
                        continue
                except OSError:
                    continue
                if _unit_age(e.path) <= cutoff:
                    stale.append(e.name)
            if not stale:
                continue
            want = {_norm(u) for u in stale}
            paths = [os.path.join(fp, u) for u in stale]
            for sub in ("deps", "build", "examples"):
                d = os.path.join(prof, sub)
                try:
                    it = list(os.scandir(d))
                except OSError:
                    continue
                for e in it:
                    base = e.name.split(".")[0]
                    cand = base[3:] if base.startswith("lib") and _norm(base[3:]) in want else base
                    if _norm(cand) in want and not e.is_symlink():
                        paths.append(e.path)
            out.append({"kind": "cargo_sweep", "path": prof, "paths": paths, "units": len(stale),
                        "bytes": sum(_path_bytes(p) for p in paths), "eligible": True, "why": ""})
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


def scratch_cargo_candidates(idle_days: float, now: float, tmp_root: str = "/tmp", held=None) -> List[Dict[str, Any]]:
    """/tmp/claude-<uid>/<proje>/<oturum>/scratchpad/<dizin> içinde CACHEDIR.TAG'li cargo derleme dizinleri (oturumların ortak
    target-dir'i DELEN çapraz derleme/profil dizinleri: tgt-*, tprof, bench). Yeniden üretilebilir önbellek: 3 günlük scratch kuralını
    BEKLEMEZ, `idle_days` (varsayılan 1) boşta + süreç tutmuyorsa aday. Oturum dizininin geri kalanına dokunulmaz."""
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
            sp = os.path.join(pdir, sess, "scratchpad")
            if os.path.islink(sp) or not os.path.isdir(sp):
                continue
            tagged: List[str] = []
            base_depth = sp.rstrip(os.sep).count(os.sep)
            for dp, dirs, files in os.walk(sp, followlinks=False):
                if "CACHEDIR.TAG" in files and dp != sp:
                    tagged.append(dp)
                    dirs[:] = []                 # etiketli dizinin içine inme
                    continue
                if dp.count(os.sep) - base_depth >= 3:
                    dirs[:] = []
                dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(dp, x))]
            for d in sorted(tagged):
                size, newest, ours = tree_info(d, newer_than=cutoff)
                elig, why = newest <= cutoff and ours, ""
                if not ours:
                    why = "başkasının dosyası var"
                elif newest > cutoff:
                    why = f"son {idle_days:g} günde değişmiş"
                elif held(d):
                    elig, why = False, "bir süreç içinde çalışıyor"
                out.append({"kind": "scratch_cargo", "path": d, "bytes": size, "newest": newest,
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


def _remove_file(path: str) -> Tuple[bool, str]:
    if os.path.islink(path):
        return False, "sembolik bağ"
    try:
        os.unlink(path)
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
    sweep = str(cfg.get("cargo_sweep", "dry")).lower()      # artifact düzeyi süpürme: ÖNCE dry (ölçüm günlüğe), sonra on
    if sweep not in ("off", "0", "false") and not compilers():
        roots = [p for r in (cfg.get("cargo_roots") or []) for p in _glob(r)]
        for it in cargo_sweep_candidates(roots, float(cfg.get("cargo_idle_days") or 14), now):
            if sweep == "dry":
                it["eligible_dry"] = True      # ölçüm: silinmez, ama aday baytı günlüğe/özete girer
                it["dry_only"] = True
            items.append(it)
    if sweep not in ("off", "0", "false") and not compilers():
        for it in scratch_cargo_candidates(float(cfg.get("scratch_cargo_idle_days") or 1), now, tmp_root):
            if sweep == "dry":
                it["dry_only"] = True      # ölçüm: silinmez, aday baytı günlüğe girer
            items.append(it)
    if str(cfg.get("scratch", "on")).lower() not in ("off", "0", "false"):
        items += scratch_candidates(float(cfg.get("scratch_idle_days") or 3), now, tmp_root)
    freed, removed = 0, 0
    for it in items:
        it["removed"] = False
        if it.get("dry_only"):
            continue
        if it["eligible"] and do and it["kind"] == "cargo_sweep":
            n_ok = 0
            for pth in it["paths"]:
                ok, _w = _remove(pth) if os.path.isdir(pth) else _remove_file(pth)
                n_ok += 1 if ok else 0
            it["removed"] = n_ok > 0
            if n_ok:
                freed += it["bytes"]
                removed += 1
            continue
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
    _log({**res, "items": [{k: v for k, v in i.items() if k not in ("newest", "paths")} for i in items
                           if i.get("eligible") or i.get("dry_only") or i["kind"] == "docker"]})
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
