"""RTODO.md / RTBD.md `.git/info/exclude` denetimi (GATE-TODO4 madde 4). YALNIZ raporlar; hicbir dosyaya yazmaz.

Her proje deposu icin: bu dosyalar `info/exclude`da mi, git'te izlenen (tracked) kopyasi var mi (public repoda iz).
git yoksa / depo degilse "not_git" olarak raporlanir (hata degil)."""
import os
import subprocess
from typing import Dict, List, Optional, Sequence

FILES = ("RTODO.md", "RTBD.md")


def _git(cwd: str, *args: str) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def exclude_path(cwd: str) -> str:
    """Deponun info/exclude yolu (worktree/ayri git-dir icin `git rev-parse --git-path`); "" = depo degil."""
    out = _git(cwd, "rev-parse", "--git-path", "info/exclude")
    if not out or not out.strip():
        return ""
    p = out.strip()
    return p if os.path.isabs(p) else os.path.join(cwd, p)


def _excluded_names(path: str) -> set:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [ln.strip() for ln in f]
    except OSError:
        return set()
    return {ln.lstrip("/") for ln in lines if ln and not ln.startswith("#") and not ln.startswith("!")}


def check_repo(name: str, cwd: str, files: Sequence[str] = FILES) -> Dict[str, object]:
    """Tek depo: {project, cwd, state: ok|missing_exclude|tracked|not_git|no_dir, not_excluded:[], tracked:[]}."""
    rec: Dict[str, object] = {"project": name, "cwd": cwd, "not_excluded": [], "tracked": []}
    if not cwd or not os.path.isdir(cwd):
        rec["state"] = "no_dir"
        return rec
    ex = exclude_path(cwd)
    if not ex:
        rec["state"] = "not_git"
        return rec
    names = _excluded_names(ex)
    rec["not_excluded"] = [f for f in files if f not in names]
    tracked = _git(cwd, "ls-files", "--", *files) or ""
    rec["tracked"] = [ln for ln in tracked.splitlines() if ln]
    rec["state"] = "tracked" if rec["tracked"] else ("missing_exclude" if rec["not_excluded"] else "ok")
    return rec


def check_all(projects: Dict[str, str]) -> List[Dict[str, object]]:
    """projects: ad -> yerel klasor. Ayni depo kokunu paylasan projeler tekrar raporlanir (ad farkli)."""
    return [check_repo(n, c) for n, c in sorted(projects.items())]


def problems(rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    return [r for r in rows if r.get("state") in ("missing_exclude", "tracked")]


def format_report(rows: Sequence[Dict[str, object]]) -> str:
    out: List[str] = []
    for r in rows:
        st = r["state"]
        if st == "ok":
            continue
        if st == "tracked":
            out.append(f"{r['project']}: IZ VAR, git'te izleniyor: {', '.join(r['tracked'])} (git rm --cached gerekir; otomatik yapilmaz)")
        elif st == "missing_exclude":
            out.append(f"{r['project']}: .git/info/exclude'da yok: {', '.join(r['not_excluded'])} (elle ekleyin; otomatik yazilmaz)")
        else:
            out.append(f"{r['project']}: atlandi ({st})")
    if not out:
        return "tum projelerde RTODO.md/RTBD.md exclude'da, iz yok"
    return "\n".join(out)
