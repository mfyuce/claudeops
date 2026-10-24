"""TBD#118 devam: rapor saklama koruması + repo görünürlüğü tespiti. Saf yardımcılar; ağ yalnız `gh`/`glab` çağrısıyla
(zaman aşımlı, hata = "unknown", sonuç süreç içinde önbelleğe alınır). Git'e YAZMAZ."""
import json
import os
import re
import subprocess
import time
from typing import Callable, Dict, List, Optional, Tuple

CACHE_SECONDS = 3600
_CACHE: Dict[str, Tuple[float, str]] = {}
_URL_RE = re.compile(r"^(?:git@|ssh://git@|https?://(?:[^@/]+@)?)(github\.com|gitlab\.com)[:/](.+?)(?:\.git)?/?$")


def parse_remote(url: str) -> Tuple[str, str]:
    """Remote URL -> (host, "sahip/ad"); tanınmazsa ("", "")."""
    m = _URL_RE.match(str(url or "").strip())
    return (m.group(1), m.group(2)) if m else ("", "")


def _run(argv: List[str], timeout: float = 15.0, run: Optional[Callable] = None) -> Tuple[int, str]:
    run = run or subprocess.run
    try:
        r = run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return int(r.returncode), (r.stdout or "").strip()


def remote_visibility(host: str, slug: str, run: Optional[Callable] = None) -> str:
    """`private` | `public` | `unknown` (gh/glab yok, giriş yok, ağ hatası, tanınmayan çıktı)."""
    if host == "github.com":
        rc, out = _run(["gh", "repo", "view", slug, "--json", "isPrivate", "-q", ".isPrivate"], run=run)
        return "private" if rc == 0 and out == "true" else ("public" if rc == 0 and out == "false" else "unknown")
    if host == "gitlab.com":
        rc, out = _run(["glab", "api", "projects/" + slug.replace("/", "%2F")], run=run)
        if rc != 0:
            return "unknown"
        try:
            vis = str(json.loads(out).get("visibility") or "")
        except ValueError:
            return "unknown"
        return "public" if vis == "public" else ("private" if vis in ("private", "internal") else "unknown")
    return "unknown"


def repo_visibility(path: str, run: Optional[Callable] = None, now: Optional[float] = None) -> str:
    """Klasörün git depo(lar)ının görünürlüğü: HERHANGİ bir remote public ise `public`; hepsi private ise `private`;
    remote yok/bilinmiyor `unknown` (çağıran bilinmiyoru public sayar). Önbellekli (1 saat)."""
    t = time.time() if now is None else now
    hit = _CACHE.get(path)
    if hit and t - hit[0] < CACHE_SECONDS:
        return hit[1]
    rc, out = _run(["git", "-C", path, "remote", "-v"], run=run)
    seen = set()
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) >= 2:
            h, slug = parse_remote(parts[1])
            if h:
                seen.add((h, slug))
    vis = [remote_visibility(h, s, run=run) for h, s in sorted(seen)]
    res = "public" if "public" in vis else ("unknown" if (not vis or "unknown" in vis) else "private")
    _CACHE[path] = (t, res)
    return res


def dest_guard(dst_root: str, run: Optional[Callable] = None) -> Tuple[bool, str]:
    """`dst_root` (…/reviews) git deposu içinde mi: değilse ya da `.gitignore` ile yok sayılıyorsa (girmez) güvenli;
    izlenebilirse ve depo public/unknown ise REDDEDİLİR (public repoya review çıktısı girmesin)."""
    probe = os.path.join(dst_root, "x", "x.md")
    d = dst_root
    while d and not os.path.isdir(d):
        d = os.path.dirname(d)
    rc, top = _run(["git", "-C", d or "/", "rev-parse", "--show-toplevel"], run=run)
    if rc != 0 or not top:
        return True, ""
    rc, _ = _run(["git", "-C", top, "check-ignore", "-q", probe], run=run)
    if rc == 0:
        return True, ""
    vis = repo_visibility(top, run=run)
    if vis == "private":
        return True, ""
    return False, f"hedef git deposu ({top}) izlenebilir ve görünürlük {vis}: public repoya review çıktısı girmez"


# ── -prv repoya günlük commit+push (TBD#118 ek) ─────────────────────────────────────────────────────────────────

STORE_COMMIT_INTERVAL = 24 * 3600


def _git(base: List[str], *args: str, run: Optional[Callable] = None, timeout: float = 120.0) -> Tuple[int, str]:
    return _run([*base, *args], timeout=timeout, run=run)


def commit_reviews(root: str, git_dir: str, scan: Callable[[str], str], dry: bool = True,
                   run: Optional[Callable] = None) -> Dict[str, object]:
    """`root/reviews/` altındaki, `-prv` deposunda HENÜZ izlenmeyen dosyaları (yalnız bu yol, `add -A` YOK; `-f`: ana
    `.gitignore` reviews/ i yok sayar) açık yol listesiyle ekleyip commit + her remote'a push eder. Depo hep `--git-dir`
    ile seçilir: ana repo (`root/.git`) ASLA kullanılmaz. `scan(metin)` maskelenmiş metni döndürür; farklıysa (gizli değer)
    dosya dışarıda kalır (`held`). `dry=True`: yalnız `would` listesi. Sonuç: {ok, would, held, committed, pushed, error}."""
    res: Dict[str, object] = {"ok": False, "would": [], "held": [], "committed": 0, "pushed": [], "error": ""}
    rroot = os.path.realpath(root)
    gd = os.path.expanduser(git_dir)
    if not git_dir or not os.path.isdir(gd) or os.path.realpath(gd) == os.path.realpath(os.path.join(rroot, ".git")):
        res["error"] = "git_dir yok ya da ana repo .git'i (yalnız ayrı -prv git-dir kabul edilir)"
        return res
    base = ["git", f"--git-dir={gd}", f"--work-tree={rroot}"]
    rc, out = _git(base, "ls-files", "-z", "--", "reviews/", run=run)
    if rc != 0:
        res["error"] = "git ls-files başarısız"
        return res
    tracked = {x for x in out.split("\0") if x}
    would: List[str] = []
    held: List[str] = []
    rdir = os.path.join(rroot, "reviews")
    for dirpath, _d, files in os.walk(rdir):
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, rroot).replace(os.sep, "/")
            if rel in tracked or os.path.islink(full) or not rel.startswith("reviews/"):
                continue
            try:
                with open(full, encoding="utf-8", errors="replace") as f:
                    txt = f.read()
            except OSError:
                held.append(rel)
                continue
            (held if scan(txt) != txt else would).append(rel)
    res.update(would=would, held=held, ok=True)
    if dry or not would:
        return res
    rc, out = _git(base, "add", "-f", "--", *would, run=run)
    if rc != 0:
        res.update(ok=False, error="git add başarısız: " + out[-200:])
        return res
    rc, out = _git(base, "commit", "-m", f"reviews: {len(would)} yeni dosya (otomatik)", "--only", "--", *would, run=run)
    if rc != 0:
        res.update(ok=False, error="git commit başarısız: " + out[-200:])
        return res
    res["committed"] = len(would)
    rc, remotes = _git(base, "remote", run=run)
    for rem in remotes.split():
        rc, out = _git(base, "push", rem, "HEAD", run=run, timeout=180.0)
        if rc == 0:
            res["pushed"].append(rem)         # type: ignore[union-attr]
        else:
            res["error"] = f"push {rem} başarısız: {out[-200:]}"
    res["ok"] = bool(res["pushed"]) and not res["error"]
    return res
