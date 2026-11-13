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
import time
from typing import Any, Dict, List, Optional, Tuple

PROJECTS_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "projects")
MIRROR_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "claudeops", "backups", "chat-mirror", "claude-projects")
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
    """Proje dizinindeki *.jsonl transkriptlerin ilk satırlarından `cwd` (en yeni dosya önce). Yoksa sohbet aynasındaki
    (`MIRROR_ROOT/<aynı kodlanmış ad>`) transkriptlerden; o da yoksa ""."""
    c = _cwd_from_dir(projdir)
    if c:
        return c
    mirror = os.path.join(MIRROR_ROOT, os.path.basename(projdir.rstrip(os.sep)))
    if os.path.isdir(mirror):       # ayna yolu dizin olarak doğrulanır; yoksa denenmez
        return _cwd_from_dir(mirror)
    return ""


def _cwd_from_dir(projdir: str) -> str:
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


def visibility_of(kind: str, path: str) -> Optional[str]:
    """"private" | "public" | None (sorgu başarısız/belirsiz: sahibe bildir)."""
    if kind == "github":
        rc, out = _run(["gh", "repo", "view", path, "--json", "visibility"])
    else:
        rc, out = _run(["glab", "repo", "view", path, "-F", "json"])
    if rc != 0:
        return None
    try:
        v = json.loads(out).get("visibility")
    except (ValueError, AttributeError):
        return None
    v = str(v or "").strip().lower()
    if v == "internal":             # GitLab internal = kuruluş içi, public DEĞİL
        return "private"
    return v if v in ("private", "public") else None


def public_marks() -> Dict[str, str]:
    """Ayardan: roster adı -> "on" | özel -prv adı ("ileride public olacak" işareti)."""
    try:
        from ..settings import load_settings
        raw = load_settings().get("memory_prv_public") or {}
    except Exception:
        return {}
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


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
    if not texts:                   # yedeklenecek *.md yok (README hariç): README-only commit açma
        ent["reason"] = "kaynak boş"
        return ent
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
    br = ent["branch"]
    bad = []
    pushable = []
    for rn in ent["remotes"]:       # 1) fetch + gerekirse merge (rebase YOK: başka remote'a giden hash değişmesin)
        rc, _ = _run(["git", "fetch", rn, br], cwd=repo, timeout=120)
        if rc != 0:                 # uzak dal yok/erişilemiyor: push kendi başına sonucu söyler
            pushable.append(rn)
            continue
        rc, _ = _run(["git", "merge-base", "--is-ancestor", f"{rn}/{br}", "HEAD"], cwd=repo)
        if rc != 1:                 # 0 = zaten atası, başka = uzak ref çözülemedi: birleştirmeye gerek yok
            pushable.append(rn)
            continue
        rc, dirty = _run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo)
        if rc != 0 or dirty.strip():
            bad.append(f"{rn}: uzak ileride, elle birleştir (çalışma ağacı kirli)")
            continue
        rc, _ = _run(["git", "merge", "--no-edit", f"{rn}/{br}"], cwd=repo, timeout=120)
        if rc != 0:
            _run(["git", "merge", "--abort"], cwd=repo)
            bad.append(f"{rn}: uzak ileride, elle birleştir (merge çakıştı)")
            continue
        pushable.append(rn)
    rc, head = _run(["git", "rev-parse", "HEAD"], cwd=repo)
    head = head.strip()
    for rn in pushable:
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
    p.add_argument("--mark-public", default="", metavar="AD[=PRV_AD]", dest="mark_public",
                   help="projeyi 'ileride public olacak' işaretle (hafızası -prv'ye gider); roster adı, isteğe bağlı özel -prv adı")
    p.add_argument("--unmark-public", default="", metavar="AD", dest="unmark_public", help="işareti kaldır")
    p.add_argument("--legacy-repo", action="store_true", dest="legacy_repo",
                   help="ESKİ kip: hafızayı projenin ANA reposuna commit'ler (13 Kas kararıyla artık varsayılan DEĞİL, -prv kipi varsayılan)")
    p.set_defaults(func=run)


def run(args) -> int:
    mk, um = getattr(args, "mark_public", ""), getattr(args, "unmark_public", "")
    if mk or um:
        from ..settings import save_settings
        if mk:
            nm, _, prv = mk.partition("=")
            save_settings({"memory_prv_public": {nm.strip(): (prv.strip() or "on")}})
            print(f"işaretlendi: {nm.strip()} (public olacak" + (f", -prv adı {prv.strip()}" if prv.strip() else "") + ")")
        if um:
            save_settings({"memory_prv_public": {um.strip(): ""}})
            print(f"işaret kaldırıldı: {um.strip()}")
        return 0
    apply = bool(getattr(args, "apply", False)) and not getattr(args, "dry_run", False)
    only = [x.strip() for x in (getattr(args, "only", "") or "").split(",") if x.strip()]
    if getattr(args, "legacy_repo", False):
        ents, failed = run_backup(PROJECTS_ROOT, apply, only)
        print(render(ents, apply))
        return 1 if failed else 0
    ents, failed = run_prv(PROJECTS_ROOT, apply, only)
    print(render_prv(ents, apply))
    return 1 if failed else 0


# ───────────────────────── -prv kipi (13 Kas 2026, sahip kararı: HAFIZA -> -prv GENEL KURALI) ─────────────────────────
# Kayıtlı (roster) HER projenin Claude hafızası, repo public/private fark etmeksizin KİŞİSEL private `<ad>-prv` reposuna gider
# (claudeops düzeni: `~/.<ad>-docs.git` + paylaşımlı work-tree = proje dizini, yalnız açık yolla add, iki remote). Ana repoya
# GİRMEZ (`.git/info/exclude` `/memory/`); eski araç ana repoya commit'lediyse `git rm --cached` (geçmiş kalır). Şirket remote'lu
# projelerde şirket reposuna ASLA yazılmaz (yalnız kişisel -prv). `-prv` yoksa oluşturulur (private, GitHub+GitLab).
OWNER = "mfyuce"
ROSTER_TSV = os.path.join(os.path.expanduser("~"), ".claude", "claudeops", "roster.tsv")
CREATED_LOG = os.path.join(os.path.expanduser("~"), ".claude", "claudeops", "memory-prv-created.log")
PRV_README = """# Claude hafıza yedeği ({name})

Bu dizin Claude'un bu projeye ait hafıza dosyalarının (`*.md`) YEDEĞİDİR; `py/cops memory-backup --apply` yazar.
Asıl yol (kaynak): `{src}`

Geri yükleme: `mkdir -p "{src}" && cp memory/*.md "{src}/"` (README.md hariç). Sır içermez (yedekleme öncesi taranır).
"""


def roster_cwds(path: Optional[str] = None) -> Dict[str, str]:
    """roster.tsv: realpath(cwd) -> ad. Bozuk/eksik dosya = boş."""
    res: Dict[str, str] = {}
    try:
        with open(path or ROSTER_TSV, encoding="utf-8") as f:
            for ln in f:
                if ln.startswith("#") or not ln.strip():
                    continue
                parts = ln.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[1].strip():
                    res[os.path.realpath(os.path.expanduser(parts[1].strip()))] = parts[0].strip()
    except OSError:
        pass
    return res


GITLAB_ONLY = {"iggy"}      # sahip kuralı (hafıza feedback-prv-repos-push-free): iggy -prv YALNIZ GitLab, GitHub'a asla


def slug(name: str) -> str:
    """Repo/gitdir adı için güvenli ad: boşluk ve alışılmadık karakterler `-`."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "proje"


def targets_for(name: str) -> Tuple[str, ...]:
    return ("gitlab",) if name in GITLAB_ONLY else ("origin", "gitlab")


def gitdir_of(name: str) -> str:
    return os.path.join(os.path.expanduser("~"), f".{name}-docs.git")


def _g(gitdir: str, *args: str, cwd: Optional[str] = None, timeout: int = 120) -> Tuple[int, str]:
    return _run(["git", f"--git-dir={gitdir}", *args], cwd=cwd, timeout=timeout)


def _remote_repo_exists(kind: str, name: str) -> Optional[bool]:
    """True/False; sorgu başarısızsa None (belirsiz: oluşturma denemez, rapor edilir)."""
    if kind == "github":
        rc, out = _run(["gh", "repo", "view", f"{OWNER}/{name}", "--json", "name"])
    else:
        rc, out = _run(["glab", "repo", "view", f"{OWNER}/{name}", "-F", "json"])
    if rc == 0 and out.strip():
        return True
    rc2, out2 = _run(["gh", "api", "user", "-q", ".login"]) if kind == "github" else _run(["glab", "api", "user"])
    return False if rc2 == 0 and out2.strip() else None


def plan_prv(memdir: str, roster: Dict[str, str], marks: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Salt-okunur planlama. `status`: ok | skip | remote; `actions`: yapılacaklar (sıralı, insan okunur)."""
    projdir = os.path.dirname(memdir)
    ent: Dict[str, Any] = {"proj": os.path.basename(projdir), "memdir": memdir, "status": "skip", "reason": "", "actions": []}
    cwd = read_cwd(projdir)
    if not cwd:
        ent["reason"] = "cwd bulunamadı"
        return ent
    ent["cwd"] = cwd
    rcwd = os.path.realpath(cwd)
    if rcwd not in roster:
        ent["reason"] = "roster dışı"
        return ent
    ent["roster_name"] = roster[rcwd]
    if not os.path.isdir(cwd):
        ent["status"], ent["reason"] = "remote", "uzak proje (dizin bu makinede yok): hafıza oradaki ~/.claude/projects altında"
        return ent
    texts, _ = changed_files(memdir, os.path.join(cwd, "memory"))
    if not texts:
        ent["reason"] = "kaynak boş"
        return ent
    rc, top = _run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    has_repo = rc == 0 and bool(top.strip())
    marks = public_marks() if marks is None else marks
    mark = marks.get(ent["roster_name"])
    flagged = mark is not None
    ent["flagged"] = flagged
    if not flagged:
        # Sahip kuralı (13 Kas revizyonu): -prv YALNIZ public repolar ve "public olacak" işaretliler için; private repoda hafıza
        # o repoda kalabilir, DOKUNULMAZ (ne kopya, ne untrack, ne repo oluşturma).
        vis: List[str] = []
        if has_repo:
            for rn, url in remotes_of(rcwd).items():
                pr = parse_remote(url)
                if pr is None:
                    vis.append("private")           # şirket içi/bilinmeyen host: şirket reposu, hafıza ona yazılmaz, dokunulmaz
                else:
                    vis.append(visibility_of(*pr) or "belirsiz")
        if "belirsiz" in vis:
            ent["reason"] = "görünürlük doğrulanamadı (gh/glab): sahibe bildir"
            return ent
        if "public" not in vis:
            ent["status"], ent["reason"] = "private", "private/yerel repo: -prv gerekmez, hafıza repoda kalır (dokunulmaz)"
            return ent
        ent["why"] = "public repo"
    else:
        ent["why"] = "public olacak işareti"
    hits = scan_secrets(texts)
    if hits:
        ent["reason"] = "sır taraması: " + "; ".join(hits) + " (sahibe bildir)"
        return ent
    name = slug(os.path.basename(rcwd))
    if flagged and mark not in ("", "on"):
        name = slug(mark[:-4] if mark.endswith("-prv") else mark)       # özel -prv adı (ad çakışmasını önler, ör. mecdtfl)
    elif flagged and name in ("v1", "v2"):
        name = slug(ent["roster_name"])
    if has_repo and os.path.realpath(top.strip()) != rcwd:
        ent["reason"] = "cwd repo kökü değil (üst repo var): sahibe bildir"
        return ent
    ent.update(name=name, repo=rcwd, has_repo=has_repo, prv=f"{name}-prv", gitdir=gitdir_of(name), targets=targets_for(name))
    acts: List[str] = []
    company = False
    if has_repo:
        rems = remotes_of(rcwd)
        ent["remotes"] = rems
        company = any(parse_remote(u) is None for u in rems.values())
        ent["company"] = company
        exc = os.path.join(rcwd, ".git", "info", "exclude")
        try:
            excluded = any(ln.strip() in ("/memory/", "/memory", "memory/") for ln in open(exc, encoding="utf-8"))
        except OSError:
            excluded = False
        if not excluded:
            acts.append("exclude /memory/")
        rc, tracked = _run(["git", "ls-files", "--", "memory"], cwd=rcwd)
        ent["tracked"] = [x for x in tracked.splitlines() if x] if rc == 0 else []
        if ent["tracked"]:
            acts.append(f"git rm --cached memory ({len(ent['tracked'])} dosya; geçmiş kalır" + (", ŞİRKET repo: itme YOK" if company else ", push") + ")")
    gd = ent["gitdir"]
    if os.path.isdir(gd):
        rc, wt = _g(gd, "config", "core.worktree")
        if rc != 0 or os.path.realpath(wt.strip()) != rcwd:
            ent["reason"] = f"{gd} başka bir work-tree'ye bağlı: sahibe bildir"
            return ent
        rc, rem = _g(gd, "remote")
        if not set(ent["targets"]) <= set(rem.split()):
            ent["reason"] = f"{gd} gerekli remote'lara ({'+'.join(ent['targets'])}) sahip değil: sahibe bildir"
            return ent
        ent["prv_state"] = "var"
    else:
        ent["prv_state"] = "yeni"
        acts.append(f"gitdir {gd}")
        for kind in [k for k in ("github", "gitlab") if not (k == "github" and "origin" not in ent["targets"])]:
            ex = _remote_repo_exists(kind, ent["prv"])
            if ex is None:
                ent["reason"] = f"{kind} oturumu/durumu doğrulanamadı (oluşturma denenmez)"
                return ent
            acts.append(f"{kind} {OWNER}/{ent['prv']} " + ("mevcut: remote ekle" if ex else "OLUŞTUR (private)"))
            ent.setdefault("creates", []).append((kind, ent["prv"], ex))
    dest = os.path.join(rcwd, "memory")
    _, changed = changed_files(memdir, dest)
    ent["changed"] = changed
    ent["readme_changed"] = not os.path.isfile(os.path.join(dest, "README.md"))
    if changed or ent["readme_changed"]:
        acts.append(f"{len(changed)} dosya" + (" + README" if ent["readme_changed"] else "") + " -> commit + push (iki remote)")
    ent["actions"] = acts
    ent["status"] = "ok"
    return ent


def apply_prv(ent: Dict[str, Any]) -> str:
    """Planı uygular. Sonuç metni; hata `HATA:` ile başlar. Yalnız açık yollar `add` edilir (asla -A)."""
    repo, gd, name = ent["repo"], ent["gitdir"], ent["name"]
    msgs: List[str] = []
    if ent.get("has_repo"):
        exc_dir = os.path.join(repo, ".git", "info")
        if "exclude /memory/" in ent["actions"]:
            os.makedirs(exc_dir, exist_ok=True)
            with open(os.path.join(exc_dir, "exclude"), "a", encoding="utf-8") as f:
                f.write("\n/memory/\n")
        if ent.get("tracked"):
            rc, staged = _run(["git", "diff", "--cached", "--name-only"], cwd=repo)
            if rc != 0 or staged.strip():       # başkasının hazırladığı değişiklik bu commit'e karışmasın
                return "HATA: ana repoda hazırlanmış (staged) değişiklik var, untrack yapılmadı (sahibe bildir)"
            rc, _ = _run(["git", "rm", "-r", "--cached", "-q", "--", "memory"], cwd=repo)
            if rc != 0:
                return "HATA: git rm --cached"
            rc, _ = _run(["git", "commit", "-m", "chore: Claude hafızası artık -prv reposunda (git rm --cached; geçmiş kalır)"], cwd=repo)
            if rc != 0:
                return "HATA: untrack commit"
            if not ent.get("company"):
                rc, br = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
                for rn in ent.get("remotes", {}):
                    _run(["git", "push", rn, f"HEAD:refs/heads/{br.strip()}"], cwd=repo, timeout=120)
            else:
                msgs.append("şirket repo: untrack commit YEREL, itilmedi (sahibe bildir)")
    if ent["prv_state"] == "yeni":
        for kind, rname, exists in ent.get("creates", []):
            if not exists:
                argv = (["gh", "repo", "create", f"{OWNER}/{rname}", "--private"] if kind == "github"
                        else ["glab", "repo", "create", rname, "--private"])
                rc, _ = _run(argv, timeout=120)
                if rc != 0:
                    return f"HATA: {kind} repo oluşturulamadı"
                try:
                    os.makedirs(os.path.dirname(CREATED_LOG), exist_ok=True)
                    with open(CREATED_LOG, "a", encoding="utf-8") as f:
                        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {kind} {OWNER}/{rname}\n")
                except OSError:
                    pass
        rc, _ = _run(["git", "init", "-q", "--bare", "-b", "main", gd])
        if rc != 0:
            return "HATA: git init"
        _g(gd, "config", "core.bare", "false")
        _g(gd, "config", "core.worktree", repo)
        _g(gd, "config", "status.showUntrackedFiles", "no")
        if "origin" in ent["targets"]:
            _g(gd, "remote", "add", "origin", f"git@github.com:{OWNER}/{ent['prv']}.git")
        _g(gd, "remote", "add", "gitlab", f"git@gitlab.com:{OWNER}/{ent['prv']}.git")
        first = ent["targets"][0]
        rc, _ = _g(gd, "fetch", "-q", first, "main", cwd=repo, timeout=120)
        if rc == 0:         # repo zaten vardı ve main'i var: geçmişini koru (mixed reset: çalışma ağacına dokunmaz)
            _g(gd, "reset", "-q", f"{first}/main", cwd=repo)
    dest = os.path.join(repo, "memory")
    os.makedirs(dest, exist_ok=True)
    files = list(ent.get("changed") or [])
    for f in files:
        shutil.copyfile(os.path.join(ent["memdir"], f), os.path.join(dest, f))
    paths = [f"memory/{f}" for f in files]
    if ent.get("readme_changed"):
        with open(os.path.join(dest, "README.md"), "w", encoding="utf-8") as fh:
            fh.write(PRV_README.format(name=name, src=ent["memdir"]))
        paths.append("memory/README.md")
    if not paths:
        return "değişiklik yok" + ("; " + "; ".join(msgs) if msgs else "")
    env_cwd = repo
    rc, _ = _g(gd, "add", "--", *paths, cwd=env_cwd)
    if rc != 0:
        return "HATA: git add"
    rc, _ = _g(gd, "commit", "-m", "chore(memory): Claude hafıza yedeği", "--", *paths, cwd=env_cwd)
    if rc != 0:
        return "HATA: git commit"
    rc, head = _g(gd, "rev-parse", "HEAD", cwd=env_cwd)
    head = head.strip()
    bad = []
    for rn in ent["targets"]:
        rc, _ = _g(gd, "push", rn, "HEAD:refs/heads/main", cwd=env_cwd, timeout=180)
        if rc != 0:
            bad.append(f"{rn}: push")
            continue
        rc, out = _g(gd, "ls-remote", rn, "refs/heads/main", cwd=env_cwd, timeout=60)
        if rc != 0 or not out.split() or out.split()[0] != head:
            bad.append(f"{rn}: ls-remote uyuşmadı")
    if bad:
        return "HATA: " + ", ".join(bad)
    return f"yedeklendi ({len(paths)} dosya, {len(ent['targets'])} remote doğrulandı)" + ("; " + "; ".join(msgs) if msgs else "")


def run_prv(root: str, apply: bool, only: List[str], roster: Optional[Dict[str, str]] = None, marks: Optional[Dict[str, str]] = None) -> Tuple[List[Dict[str, Any]], int]:
    roster = roster_cwds() if roster is None else roster
    ents: List[Dict[str, Any]] = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    seen: set = set()
    names_seen: Dict[str, str] = {}
    for n in names:
        memdir = os.path.join(root, n, "memory")
        if not os.path.isdir(memdir):
            continue
        ent = plan_prv(memdir, roster, marks)
        if ent.get("repo") in seen:         # aynı cwd'ye giden birden çok proje dizini: ilki
            continue
        if ent["status"] == "ok" and ent["name"] in names_seen:
            ent["status"], ent["reason"], ent["actions"] = "skip", f"ad çakışması: '{ent['name']}' başka bir projede de var ({names_seen[ent['name']]}); sahibe bildir", []
        elif ent["status"] == "ok":
            names_seen[ent["name"]] = ent["repo"]
        if only and not ({ent.get("name", ""), ent["proj"], ent.get("roster_name", "")} & set(only)):
            continue
        if ent.get("repo"):
            seen.add(ent["repo"])
        if apply and ent["status"] == "ok":
            ent["result"] = apply_prv(ent)
        ents.append(ent)
    failed = sum(1 for e in ents if str(e.get("result", "")).startswith("HATA"))
    return ents, failed


def render_prv(ents: List[Dict[str, Any]], apply: bool) -> str:
    out = [f"memory-backup -prv kipi ({'APPLY' if apply else 'DRY-RUN: hiçbir şey yazılmadı, hiçbir repo oluşturulmadı'})", ""]
    ok = [e for e in ents if e["status"] == "ok"]
    priv = [e for e in ents if e["status"] == "private"]
    out.append(f"{'PROJE':28s} {'PRV':10s} {'NEDEN':18s} {'REMOTE':8s} PLAN")
    for e in ok:
        plan = e.get("result") or ("; ".join(e["actions"]) or "değişiklik yok")
        out.append(f"{e['name']:28s} {e['prv_state']:10s} {e.get('why',''):18s} {'ŞİRKET' if e.get('company') else 'kişisel':8s} {plan}")
    if priv:
        out += ["", f"DOKUNULMAYAN private/yerel repolar ({len(priv)}): " + ", ".join(sorted((e.get('roster_name') or e['proj']) for e in priv))]
    rest = [e for e in ents if e["status"] not in ("ok", "private")]
    if rest:
        out += ["", "ATLANAN / BİLDİRİLECEK:"]
        for e in rest:
            out.append(f"  {(e.get('roster_name') or e['proj'])[:60]:60s} {e['reason']}")
    created = [(k, n) for e in ok for (k, n, ex) in e.get("creates", []) if not ex]
    if created:
        out += ["", f"OLUŞTURULACAK repo sayısı: {len(created)} (" + ", ".join(sorted({n for _, n in created})) + ")"]
    return "\n".join(out)
