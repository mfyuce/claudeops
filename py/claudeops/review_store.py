"""Rapor saklama koruması + repo görünürlüğü tespiti (özel/herkese açık repoda rapor saklama kararı). Saf yardımcılar; ağ yalnız `gh`/`glab` çağrısıyla
(zaman aşımlı, hata = "unknown", sonuç süreç içinde önbelleğe alınır). Git'e YAZMAZ."""
import json
import os
import re
import subprocess
import time
from typing import Callable, Dict, List, Optional, Tuple

CACHE_SECONDS = 3600
CACHE_MAX = 256       # sınırsız büyümesin (en eski girdi atılır)
_CACHE: Dict[str, Tuple[float, str]] = {}
# ssh.github.com / altssh.gitlab.com (443 üzerinden ssh) aynı depoya çıkar: ana ada normalize edilir
_URL_RE = re.compile(r"^(?:git@|ssh://git@|https?://(?:[^@/]+@)?)(?:ssh\.|altssh\.)?(github\.com|gitlab\.com)[:/](.+?)(?:\.git)?/?$")
_SSH_PORT_RE = re.compile(r"^(ssh://[^@/]+@[^:/]+):\d+/")


def parse_remote(url: str) -> Tuple[str, str]:
    """Remote URL -> (host, "sahip/ad"); tanınmazsa ("", "")."""
    u = _SSH_PORT_RE.sub(r"\1/", str(url or "").strip())   # yalnız ssh:// biçiminde `:port` var (scp biçiminde `:` yoldur)
    m = _URL_RE.match(u)
    return (m.group(1), m.group(2)) if m else ("", "")


def _run(argv: List[str], timeout: float = 15.0, run: Optional[Callable] = None) -> Tuple[int, str]:
    kw: Dict[str, object] = {}
    if run is None:
        run = subprocess.run
        kw["env"] = dict(os.environ, LC_ALL="C")      # git iletileri İngilizce: "not a git repository" ayrımı yerel dile bağlı olmasın
    try:
        r = run(argv, capture_output=True, text=True, timeout=timeout, **kw)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, ("timeout" if isinstance(e, subprocess.TimeoutExpired) else "oserror")
    out = (r.stdout or "").strip()
    if int(r.returncode) != 0 and (r.stderr or "").strip():
        out = (out + "\n" + r.stderr.strip()).strip()
    return int(r.returncode), out


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
        return "public" if vis == "public" else ("private" if vis == "private" else "unknown")  # internal = girişli herkese açık: private SAYILMAZ
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
    unparsed = False
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) >= 2:
            h, slug = parse_remote(parts[1])
            if h:
                seen.add((h, slug))
            elif not _is_local_remote(parts[1]):
                unparsed = True      # tanınmayan (github/gitlab dışı) uzak: görünürlüğü bilinemez, "private" sayılmasın (review cliops 17 Kas)
    vis = [remote_visibility(h, s, run=run) for h, s in sorted(seen)] + (["unknown"] if unparsed else [])
    res = "public" if "public" in vis else ("unknown" if (not vis or "unknown" in vis) else "private")
    if res != "unknown":       # geçici hata (ağ, gh/glab girişi) 1 saat boyunca "unknown" olarak takılı kalmasın
        if len(_CACHE) >= CACHE_MAX and path not in _CACHE:
            _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k][0]), None)
        _CACHE[path] = (t, res)
    return res


def _is_local_remote(url: str) -> bool:
    u = str(url or "").strip()
    return u.startswith(("/", "./", "../", "~", "file://"))


def gitdir_visibility(git_dir: str, run: Optional[Callable] = None) -> str:
    """Ayrı `--git-dir` deposunun (ör. `-prv`) remote'larının görünürlüğü, HER ÇAĞRIDA taze (önbellek YOK: push öncesi kapı).
    `public` (herhangi biri public) > `unknown` (tanınan sunucuda doğrulanamadı ya da tanınmayan ağ adresi) > `private`
    (hepsi private; yerel yol/file:// remote'u ve remote'suz depo dışarı açılamaz, private sayılır)."""
    rc, out = _run(["git", f"--git-dir={git_dir}", "remote", "-v"], run=run)
    if rc != 0:
        return "unknown"
    seen = set()
    other_net = False
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) < 2:
            continue
        h, slug = parse_remote(parts[1])
        if h:
            seen.add((h, slug))
        elif not _is_local_remote(parts[1]):
            other_net = True        # github/gitlab dışı ağ adresi: görünürlüğü bilemeyiz
    vis = [remote_visibility(h, s, run=run) for h, s in sorted(seen)]
    if "public" in vis:
        return "public"
    return "unknown" if (other_net or "unknown" in vis) else "private"


def dest_guard(dst_root: str, run: Optional[Callable] = None) -> Tuple[bool, str]:
    """`dst_root` (…/reviews) git deposu içinde mi: değilse ya da `.gitignore` ile yok sayılıyorsa (girmez) güvenli;
    izlenebilirse ve depo public/unknown ise REDDEDİLİR (public repoya review çıktısı girmesin)."""
    probe = os.path.join(dst_root, "x", "x.md")
    d = dst_root
    while d and not os.path.isdir(d):
        d = os.path.dirname(d)
    rc, top = _run(["git", "-C", d or "/", "rev-parse", "--show-toplevel"], run=run)
    if rc != 0 or not top:
        if "not a git repository" in (top or "").lower():
            return True, ""
        return False, "git durumu belirlenemedi (zaman aşımı/hata): güvenli tarafta reddedildi"
    rc, _ = _run(["git", "-C", top, "check-ignore", "-q", probe], run=run)
    if rc == 0:
        return True, ""
    if rc != 1:         # 1 = "yok sayılmıyor"; başka kod (128 hata, zaman aşımı) = belirlenemedi: fail-closed
        return False, "git check-ignore belirlenemedi (hata/zaman aşımı): güvenli tarafta reddedildi"
    vis = repo_visibility(top, run=run)
    if vis == "private":
        return True, ""
    return False, f"hedef git deposu ({top}) izlenebilir ve görünürlük {vis}: public repoya review çıktısı girmez"


# ── -prv repoya günlük commit+push (TBD#118 ek) ─────────────────────────────────────────────────────────────────

STORE_COMMIT_INTERVAL = 24 * 3600


def _git(base: List[str], *args: str, run: Optional[Callable] = None, timeout: float = 120.0) -> Tuple[int, str]:
    return _run([*base, *args], timeout=timeout, run=run)


_USAGE_COUNTER_RE = re.compile(r'("[A-Za-z_]*(?:tokens|_count|count)"\s*:\s*)-?\d+(?:\.\d+)?')


def scan_text(rel: str, txt: str, scan: Callable[[str], str]) -> str:
    """Gizli değer taraması (maskelenmiş metni döndürür). `.usage.jsonl` yalnız sayılar içerir ve `"cached_tokens": 1022713` gibi
    sayaç alanları `token` + sayı olarak SIR deseniyle eşleşiyordu (52/1513 dosya boşuna dışarıda kalıyordu, 21 Kas teşhis):
    önce bu sayaç değerleri nötrlenir; başka her şey (gerçek sır) eskisi gibi yakalanır, dönen metin özgün metinle karşılaştırılır."""
    if not rel.endswith(".usage.jsonl"):
        return scan(txt)
    neutral = _USAGE_COUNTER_RE.sub(lambda m: m.group(1) + "0", txt)
    return txt if scan(neutral) == neutral else scan(txt)


def commit_reviews(root: str, git_dir: str, scan: Callable[[str], str], dry: bool = True,
                   run: Optional[Callable] = None, vis_check: Optional[Callable[[str], str]] = None) -> Dict[str, object]:
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
    # GERÇEK bariyer, çağıranın hafızasına bağlı değil: push edilecek deponun (`dest_guard` dış depoya bakar, burada o değil) remote'ları
    # TAZE olarak private doğrulanmadan hiçbir şey eklenmez/itilmez; public ya da doğrulanamayan = reddedilir (fail-closed).
    vis = (vis_check or (lambda g: gitdir_visibility(g, run=run)))(gd)
    if vis != "private":
        res["error"] = f"-prv git-dir remote'larının görünürlüğü {vis}: private doğrulanamadı, review çıktısı itilmez"
        return res
    base = ["git", "--literal-pathspecs", "-C", rroot, f"--git-dir={gd}", f"--work-tree={rroot}"]   # `[1]`/`*` içeren dosya adı glob sayılmasın
    rc, out = _git(base, "ls-files", "-z", "--", "reviews/", run=run)
    if rc != 0:
        res["error"] = "git ls-files başarısız"
        return res
    tracked = {x for x in out.split("\0") if x}
    would: List[str] = []
    held: List[str] = []
    seen: Dict[str, str] = {}
    rdir = os.path.join(rroot, "reviews")
    for dirpath, dirs, files in os.walk(rdir):
        # tarayıcıdan "farklı kaydet" web sayfası yan dosyaları (`<ad>_files/`) saklanmaz; yalnız ana .html/.md kalır (sahip, TBD A, 2026-10-28)
        dirs[:] = [d for d in dirs if not d.endswith("_files")]
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, rroot).replace(os.sep, "/")
            if rel == "reviews/" + FABLE_INDEX and rel in tracked:       # dizin her yeni raporda değişir: izlenen ama değişmişse yeniden eklenir
                rcs, stat = _git(base, "status", "--porcelain", "--", rel, run=run)
                if rcs != 0 or not stat.strip():
                    continue
            elif rel in tracked or os.path.islink(full) or not rel.startswith("reviews/"):
                continue
            if name.startswith(".") or name.endswith((".tmp", ".lock", "~", ".swp", ".swo")):
                continue        # crash kalıntısı geçici/kilit/editör yedeği commit+push edilmez (review cliops 3 Kas)
            try:
                with open(full, encoding="utf-8", errors="replace") as f:
                    txt = f.read()
            except OSError:
                held.append(rel)
                continue
            (held if scan_text(rel, txt, scan) != txt else would).append(rel)
            if rel in would:
                seen[rel] = txt
    res.update(would=would, held=held, ok=True)
    if dry:
        return res
    if would and not dry:
        # tarama ile ekleme arasında dosya değişmiş olabilir (TOCTOU): değişen dosya yeniden taranır, gizli değer içeriyorsa dışarıda kalır
        for rel in list(would):
            try:
                with open(os.path.join(rroot, rel), encoding="utf-8", errors="replace") as f:
                    now_txt = f.read()
            except OSError:
                would.remove(rel)
                held.append(rel)
                continue
            if now_txt != seen.get(rel) and scan_text(rel, now_txt, scan) != now_txt:
                would.remove(rel)
                held.append(rel)
        res.update(would=would, held=held)
    if would:
        rc, out = _git(base, "add", "-f", "--", *would, run=run)
        if rc != 0:
            _git(base, "reset", "-q", "--", *would, run=run)      # kısmi add: -prv index'i kirli kalmasın (review cops)
            res.update(ok=False, error="git add başarısız: " + out[-200:])
            return res
        # GERÇEK bariyer: tarama ile `git add` arasında değişen içerik için, index'e giren BLOB taranır (çalışma kopyası değil);
        # gizli değer varsa o yol index'ten çıkarılır ve dışarıda kalır (review cliops 3 Kas TOCTOU)
        for rel in list(would):
            rcb, blob = _git(base, "show", ":" + rel, run=run)
            if rcb != 0 or scan_text(rel, blob, scan) != blob:
                _git(base, "reset", "-q", "--", rel, run=run)
                would.remove(rel)
                held.append(rel)
        res.update(would=would, held=held)
        if not would:
            return _push_pending(res, base, run)
        rc, out = _git(base, "commit", "-m", f"reviews: {len(would)} yeni dosya (otomatik)", "--only", "--", *would, run=run)
        if rc != 0:
            _git(base, "reset", "-q", "--", *would, run=run)      # index'te takılı kalmasın
            res.update(ok=False, error="git commit başarısız: " + out[-200:])
            return res
        res["committed"] = len(would)
    else:
        # yeni dosya yok: önceki koşudan commit'lenmiş ama push edilmemiş (push hatası) iş kalmış olabilir -> yine push dene.
        rc, _o = _git(base, "rev-parse", "--verify", "-q", "HEAD", run=run)
        if rc != 0:
            return res          # hiç commit yok, itilecek bir şey yok
    return _push_pending(res, base, run)


def _push_pending(res: Dict[str, object], base: List[str], run: Optional[Callable]) -> Dict[str, object]:
    """Her remote'a push (tek yeniden deneme); sonuç `res`e yazılır."""
    rc, remotes = _git(base, "remote", run=run)
    if rc != 0 or not remotes.split():
        res.update(ok=False, error="remote yok ya da `git remote` başarısız" if rc == 0 else "git remote başarısız: " + remotes[-200:])
        return res
    errs: List[str] = []
    for rem in remotes.split():
        for attempt in (1, 2):                  # tek yeniden deneme (geçici ağ hatası)
            rc, out = _git(base, "push", rem, "HEAD", run=run, timeout=180.0)
            if rc == 0:
                res["pushed"].append(rem)       # type: ignore[union-attr]
                break
        else:
            errs.append(f"push {rem} başarısız: {out[-200:]}")
    res["error"] = "; ".join(errs)
    res["ok"] = bool(res["pushed"]) and not errs
    return res


# ── Fable review dizini (17 Kas, sahip: "Fable review'ları çok değerli, hiçbirini kaybetmeyelim") ───────────────────────────
FABLE_INDEX = "FABLE-INDEX.md"
_FABLE_TS_RE = re.compile(r"^\d{14}$")
_FINDING_HEAD_RE = re.compile(r"^##\s+R-\d+\s*\|\s*(P[0-4])\b", re.M)      # `## R-3 | P2 | yol:satır | başlık`
_INDEX_LINE_RE = re.compile(r"^- \[(.)\] .*?\]\(([^)]+)\)\s*$", re.M)


def is_fable_path(rel: str) -> bool:
    """`<proje>/claude|anthropic/claude-fable-*/...` biçimindeki (reviews/ altı göreli) yol bir Fable çıktısı mı."""
    return "/claude-fable" in "/" + rel.replace(os.sep, "/")


def severity_counts(text: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for m in _FINDING_HEAD_RE.finditer(text or ""):
        out[m.group(1)] = out.get(m.group(1), 0) + 1
    return out


def fable_reports(reviews_root: str) -> List[Dict[str, str]]:
    """`reviews_root` (`.../reviews`) altında `<proje>/<mode>/<claude-fable-*>[/<effort>]/<ts>/<ts>.md` raporları (yeniden eskiye)."""
    rows: List[Dict[str, str]] = []
    for dirpath, _dirs, files in os.walk(reviews_root):
        ts = os.path.basename(dirpath)
        if not _FABLE_TS_RE.match(ts) or f"{ts}.md" not in files:
            continue
        rel = os.path.relpath(os.path.join(dirpath, f"{ts}.md"), reviews_root).replace(os.sep, "/")
        if not is_fable_path(rel):
            continue
        parts = rel.split("/")
        model_i = next((i for i, x in enumerate(parts) if x.startswith("claude-fable")), -1)
        effort = parts[model_i + 1] if model_i >= 0 and len(parts) - model_i > 3 else ""
        rows.append({"rel": rel, "project": parts[0], "model": parts[model_i] if model_i >= 0 else "", "effort": effort, "ts": ts})
    rows.sort(key=lambda r: (r["project"], r["ts"]), reverse=False)
    return rows


def build_fable_index(reviews_root: str, previous: str = "") -> str:
    """Okuma dizini (markdown): proje başına rapor satırı `- [ ] <tarih> · <model> <effort> · P1:n P2:n · [ad](yol)`. `previous` (eski dizin metni)
    varsa `[x]` (okundu) işaretleri yoluna göre korunur. Rapor/.io.jsonl ASLA silinmez; dizin her seferinde yeniden üretilir."""
    done = {m.group(2) for m in _INDEX_LINE_RE.finditer(previous or "") if m.group(1).lower() == "x"}
    by_proj: Dict[str, List[Dict[str, str]]] = {}
    for r in fable_reports(reviews_root):
        by_proj.setdefault(r["project"], []).append(r)
    out = ["# Fable review'ları (okuma dizini)", "",
           "Otomatik üretilir (claudeops, her yeni Fable raporunda). Her satır bir rapor; bağlantı raporun kendisi. Rapor ve `.io.jsonl` dosyaları ASLA silinmez; "
           "dup/refuted/rejected bulgular da raporda durur. `[x]` = okundu (elle işaretle, yeniden üretimde korunur).", ""]
    for proj in sorted(by_proj):
        out += [f"## {proj}", ""]
        for r in sorted(by_proj[proj], key=lambda x: x["ts"], reverse=True):
            try:
                with open(os.path.join(reviews_root, r["rel"]), encoding="utf-8", errors="replace") as f:
                    sev = severity_counts(f.read())
            except OSError:
                sev = {}
            ts = r["ts"]
            when = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}"
            sevs = " ".join(f"{k}:{sev[k]}" for k in sorted(sev)) or "bulgu yok"
            mark = "x" if r["rel"] in done else " "
            out.append(f"- [{mark}] {when} · {r['model'].replace('claude-', '')} {r['effort']} · {sevs} · [{ts}.md]({r['rel']})")
        out.append("")
    return "\n".join(out) + "\n"


def write_fable_index(reviews_root: str) -> bool:
    """`<reviews_root>/FABLE-INDEX.md`yi yeniden üretir (içerik aynıysa yazmaz). Fable raporu yoksa yazmaz. Dönen: yazıldı mı."""
    if not fable_reports(reviews_root):
        return False
    path = os.path.join(reviews_root, FABLE_INDEX)
    try:
        with open(path, encoding="utf-8") as f:
            prev = f.read()
    except OSError:
        prev = ""
    new = build_fable_index(reviews_root, prev)
    if new == prev:
        return False
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, path)
    return True
