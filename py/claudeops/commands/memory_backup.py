"""`memory-backup` — Claude hafıza dizinlerini (`~/.claude/projects/*/memory`) PROJE REPOSUNA yedekle.

Kullanım:
  py/cops memory-backup                       # varsayılan --dry-run: plan tablosu, hiçbir şey yazılmaz
  py/cops memory-backup --apply               # yazar: kopyala, README, commit, push, ls-remote doğrulaması
  py/cops memory-backup --only wifi5g_ppr,cli # yalnız bu repo/dizin adları (repo kök adı ya da kodlanmış proje adı)

Kurallar: cwd KODLANMIŞ addan tahmin edilmez, transkriptlerin (*.jsonl) ilk satırlarındaki "cwd" alanından okunur. cwd bir git
reposunun KÖKÜ olmalı. Her remote github.com/gitlab.com olmalı ve HEPSİ private olmalı (gh/glab ile sorulur); şirket içi remote
ya da private olmayan = ATLA ("sahibe sor"). Sır taraması eşleşirse repo atlanır. `git add` yalnız memory/ altındaki açık dosya
yolları (asla -A); commit yalnız o yollarla.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

PROJECTS_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "projects")
SECRET_PATTERNS = [
    ("BEGIN PRIVATE KEY", re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")),
    ("sk-ant-", re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")),
    ("ghp_", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("glpat-", re.compile(r"glpat-[A-Za-z0-9_\-]{10,}")),
    ("AKIA", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("password=", re.compile(r"(?i)(?:password|passwd|pwd)\s*[=:]\s*['\"]?[^\s'\"<>$*]{4,}")),
]
README_TEXT = """# Claude hafıza yedeği

Bu dizin, Claude'un bu projeye ait hafıza dosyalarının (`*.md`) YEDEĞİDİR; `py/cops memory-backup --apply` yazar.
Asıl yol (kaynak): `{src}`

Geri yükleme: bu dizindeki `*.md` dosyalarını (README.md hariç) asıl yola kopyala:

    mkdir -p "{src}" && cp memory/*.md "{src}/"

Elle düzenleme sonraki yedekte ezilir. Sır içermez (yedekleme öncesi taranır).
"""


def _run(argv: List[str], cwd: Optional[str] = None, timeout: int = 60) -> Tuple[int, str]:
    """Tek çıkış kapısı (testlerde yamalanır). Asla fırlatmaz: (rc, stdout); başlatılamazsa (127, "")."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def read_cwd(projdir: str) -> str:
    """Proje dizinindeki *.jsonl transkriptlerin ilk satırlarından `cwd` (en yeni dosya önce). Yoksa ""."""
    try:
        files = sorted((os.path.join(projdir, f) for f in os.listdir(projdir) if f.endswith(".jsonl")),
                       key=lambda p: os.path.getmtime(p), reverse=True)
    except OSError:
        return ""
    for fp in files:
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                for _ in range(30):
                    line = f.readline()
                    if not line:
                        break
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    c = obj.get("cwd") if isinstance(obj, dict) else None
                    if isinstance(c, str) and c.strip():
                        return c.strip()
        except OSError:
            continue
    return ""


def parse_remote(url: str) -> Optional[Tuple[str, str]]:
    """(`github`|`gitlab`, `sahip/ad`) ya da None (başka host = şirket içi/bilinmeyen)."""
    m = re.match(r"^(?:https?://(?:[^@/]+@)?|ssh://git@|git@)(github\.com|gitlab\.com)[:/]+(.+?)(?:\.git)?/?$", url.strip())
    if not m:
        return None
    return ("github" if m.group(1) == "github.com" else "gitlab"), m.group(2)


def remotes_of(repo: str) -> Dict[str, str]:
    rc, out = _run(["git", "remote", "-v"], cwd=repo)
    res: Dict[str, str] = {}
    if rc == 0:
        for ln in out.splitlines():
            parts = ln.split()
            if len(parts) >= 2 and ln.rstrip().endswith("(push)"):
                res[parts[0]] = parts[1]
    return res


def is_private(kind: str, path: str) -> bool:
    if kind == "github":
        rc, out = _run(["gh", "repo", "view", path, "--json", "visibility"])
    else:
        rc, out = _run(["glab", "repo", "view", path, "-F", "json"])
    if rc != 0:
        return False
    try:
        v = json.loads(out).get("visibility")
    except (ValueError, AttributeError):
        return False
    return isinstance(v, str) and v.strip().lower() == "private"


def scan_secrets(texts: Dict[str, str]) -> List[str]:
    hits = []
    for name, text in sorted(texts.items()):
        for label, rx in SECRET_PATTERNS:
            if rx.search(text):
                hits.append(f"{name}: {label}")
    return hits


def changed_files(memdir: str, dest: str) -> Tuple[Dict[str, str], List[str]]:
    """(kaynak *.md -> metin, değişen/yeni dosya adları). README.md kaynaktan alınmaz (hedefte bizimki)."""
    texts: Dict[str, str] = {}
    changed: List[str] = []
    for f in sorted(os.listdir(memdir)):
        if not f.endswith(".md") or f == "README.md" or not os.path.isfile(os.path.join(memdir, f)):
            continue
        with open(os.path.join(memdir, f), encoding="utf-8", errors="replace") as fh:
            texts[f] = fh.read()
        try:
            with open(os.path.join(dest, f), "rb") as fh:
                same = fh.read() == open(os.path.join(memdir, f), "rb").read()
        except OSError:
            same = False
        if not same:
            changed.append(f)
    return texts, changed


def plan_one(memdir: str) -> Dict[str, Any]:
    """Salt-okunur planlama. `status`: ok | skip; `reason` atlama nedeni."""
    projdir = os.path.dirname(memdir)
    ent: Dict[str, Any] = {"proj": os.path.basename(projdir), "memdir": memdir, "status": "skip", "reason": "", "remotes": {}}
    cwd = read_cwd(projdir)
    if not cwd:
        ent["reason"] = "cwd bulunamadı"
        return ent
    ent["cwd"] = cwd
    if not os.path.isdir(cwd):
        ent["reason"] = "cwd dizini yok"
        return ent
    rc, top = _run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    if rc != 0 or not top.strip():
        ent["reason"] = "git repo yok"
        return ent
    if os.path.realpath(top.strip()) != os.path.realpath(cwd):
        ent["reason"] = "cwd repo kökü değil"
        return ent
    repo = os.path.realpath(cwd)
    ent["repo"], ent["name"] = repo, os.path.basename(repo)
    rems = remotes_of(repo)
    ent["remotes"] = rems
    if not rems:
        ent["reason"] = "remote yok"
        return ent
    for rn, url in rems.items():
        pr = parse_remote(url)
        if pr is None:
            ent["reason"] = f"sahibe sor: şirket içi/bilinmeyen remote ({rn})"
            return ent
        if not is_private(*pr):
            ent["reason"] = f"sahibe sor: {rn} private değil/doğrulanamadı"
            return ent
    rc, br = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    if rc != 0 or br.strip() in ("", "HEAD"):
        ent["reason"] = "detached HEAD"
        return ent
    ent["branch"] = br.strip()
    dest = os.path.join(repo, "memory")
    texts, changed = changed_files(memdir, dest)
    hits = scan_secrets(texts)
    if hits:
        ent["reason"] = "sır taraması: " + "; ".join(hits)
        return ent
    ent["changed"] = changed
    readme = README_TEXT.format(src=memdir)
    try:
        with open(os.path.join(dest, "README.md"), encoding="utf-8") as fh:
            ent["readme_changed"] = fh.read() != readme
    except OSError:
        ent["readme_changed"] = True
    ent["status"] = "ok"
    return ent


def apply_one(ent: Dict[str, Any]) -> str:
    """Kopyala + README + add (açık yollar) + commit + push + ls-remote doğrula. Sonuç metni."""
    repo, dest = ent["repo"], os.path.join(ent["repo"], "memory")
    files = list(ent.get("changed") or [])
    if not files and not ent.get("readme_changed"):
        return "değişiklik yok"
    os.makedirs(dest, exist_ok=True)
    for f in files:
        shutil.copyfile(os.path.join(ent["memdir"], f), os.path.join(dest, f))
    paths = [f"memory/{f}" for f in files]
    if ent.get("readme_changed"):
        with open(os.path.join(dest, "README.md"), "w", encoding="utf-8") as fh:
            fh.write(README_TEXT.format(src=ent["memdir"]))
        paths.append("memory/README.md")
    rc, _ = _run(["git", "add", "--"] + paths, cwd=repo)
    if rc != 0:
        return "HATA: git add"
    rc, _ = _run(["git", "commit", "-m", "chore(memory): Claude hafıza yedeği", "--"] + paths, cwd=repo)
    if rc != 0:
        return "HATA: git commit"
    rc, head = _run(["git", "rev-parse", "HEAD"], cwd=repo)
    head = head.strip()
    bad = []
    for rn in ent["remotes"]:
        rc, _ = _run(["git", "push", rn, f"HEAD:refs/heads/{ent['branch']}"], cwd=repo, timeout=120)
        if rc != 0:
            bad.append(f"{rn}: push")
            continue
        rc, out = _run(["git", "ls-remote", rn, f"refs/heads/{ent['branch']}"], cwd=repo, timeout=60)
        if rc != 0 or not out.split() or out.split()[0] != head:
            bad.append(f"{rn}: ls-remote uyuşmadı")
    return "HATA: " + ", ".join(bad) if bad else f"yedeklendi ({len(paths)} dosya), {len(ent['remotes'])} remote doğrulandı"


def run_backup(root: str, apply: bool, only: List[str]) -> Tuple[List[Dict[str, Any]], int]:
    ents: List[Dict[str, Any]] = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    for n in names:
        memdir = os.path.join(root, n, "memory")
        if not os.path.isdir(memdir):
            continue
        ent = plan_one(memdir)
        if only and not ({ent.get("name", ""), ent["proj"]} & set(only)):
            continue
        if apply and ent["status"] == "ok":
            ent["result"] = apply_one(ent)
        ents.append(ent)
    failed = sum(1 for e in ents if str(e.get("result", "")).startswith("HATA"))
    return ents, failed


def render(ents: List[Dict[str, Any]], apply: bool) -> str:
    out = [f"memory-backup ({'APPLY' if apply else 'DRY-RUN: hiçbir şey yazılmadı'})", ""]
    for e in ents:
        label = e.get("name") or e["proj"]
        if e["status"] == "ok":
            n = len(e.get("changed") or [])
            note = e.get("result") or f"{n} dosya değişecek" + (", README" if e.get("readme_changed") else "")
            out.append(f"  OK    {label:30s} {note}")
        else:
            out.append(f"  ATLA  {label:30s} {e['reason']}")
    if not ents:
        out.append("  (hafıza dizini bulunamadı)")
    ask = [e for e in ents if e["reason"].startswith("sahibe sor")]
    if ask:
        out += ["", "Sahibe sor: " + ", ".join(e.get("name") or e["proj"] for e in ask)]
    return "\n".join(out)


def register(sub):
    p = sub.add_parser("memory-backup", help="Claude hafızasını (~/.claude/projects/*/memory) private proje reposuna yedekle (varsayılan dry-run)")
    p.add_argument("--apply", action="store_true", help="gerçekten yaz/commit/push (yoksa yalnız plan)")
    p.add_argument("--dry-run", action="store_true", help="varsayılan; plan tablosu (--apply ile birlikte verilirse --apply kazanmaz)")
    p.add_argument("--only", default="", metavar="AD,AD", help="yalnız bu repo/proje adları")
    p.set_defaults(func=run)


def run(args) -> int:
    apply = bool(getattr(args, "apply", False)) and not getattr(args, "dry_run", False)
    only = [x.strip() for x in (getattr(args, "only", "") or "").split(",") if x.strip()]
    ents, failed = run_backup(PROJECTS_ROOT, apply, only)
    print(render(ents, apply))
    return 1 if failed else 0
