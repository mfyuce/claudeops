"""Canlı parite koşucusu: `py/claudeops` (salt okunur) ile `cops-procscan` ikilisini aynı makinede karşılaştırır.

Koşum (repo kökünden):  python3 -I rust/crates/cops-procscan/parity/run.py [--bin YOL] [--sample N] [--seed S]

- `list`/`scan`: bu kullanıcının CANLI süreçlerini salt okur. Süreç kümesi iki koşu arasında değişebildiği için Rust
  Python'dan önce ve sonra koşar; bir fark ancak İKİ Rust anlık görüntüsünde de varsa "kalıcı" sayılır.
- usage / needs_ho: geçici dizinde fikstür + gerçek transkriptlerden (yalnız `~/.claude/projects`, bu kullanıcının)
  salt okuma; gerçek depolarda git `GIT_OPTIONAL_LOCKS=0` ile koşar (indeks yazılmaz).
- Python tarafı `pyenv` korumasında: CLAUDEOPS_DIR geçici, eklenti yok, geçici dizin dışına yazım/sqlite/sinyal
  engelli; `_remember_agy_sid` yazmaz, yalnız "yazacağı" kaydı toplar (Rust `agy_learned` ile karşılaştırılır).
- Çıktı yalnız SAYI ve ALAN ADI: transkript içeriği, oturum adı, yol, sid basılmaz.
Çıkış kodu: kalıcı fark varsa 1.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pyenv  # noqa: E402

HOME = Path(os.path.expanduser("~"))
LIVE_STATE = Path(os.environ.get("CLAUDEOPS_DIR") or HOME / ".claude" / "claudeops")

ap = argparse.ArgumentParser()
ap.add_argument("--bin", default=None, help="cops-procscan ikilisi (yoksa cargo build)")
ap.add_argument("--sample", type=int, default=120, help="usage/needs_ho için gerçek transkript örneği")
ap.add_argument("--seed", type=int, default=26)
ARGS = ap.parse_args()

if ARGS.bin:
    BIN = ARGS.bin
else:
    subprocess.run(["cargo", "build", "-q", "-p", "cops-procscan"], cwd=pyenv.REPO / "rust", check=True)
    target = os.environ.get("CARGO_TARGET_DIR") or str(HOME / ".cargo-target")
    BIN = os.path.join(target, "debug", "cops-procscan")

# canlı agy_sids aynasını (salt okunur) geçici dizine kopyala: iki taraf aynı girdiyi görsün
_agy_live = (LIVE_STATE / "agy_sids.json").read_bytes() if (LIVE_STATE / "agy_sids.json").is_file() else None
TMP = pyenv.setup()
if _agy_live is not None:
    Path(TMP, "agy_sids.json").write_bytes(_agy_live)
pyenv.install_psutil_guard()

import psutil  # noqa: E402

from claudeops import discovery, needs_ho, session_usage as su, tmux_backend  # noqa: E402
from claudeops.commands import ls as ls_cmd  # noqa: E402
from claudeops.providers import agy_provider  # noqa: E402
from claudeops.providers.claude_provider import jsonl_path_for  # noqa: E402

AGY_WOULD_WRITE: list = []


def _remember_dry(session_name, sid):
    if agy_provider._load_agy_sids().get(session_name) != sid:
        AGY_WOULD_WRITE.append((session_name, sid))


agy_provider._remember_agy_sid = _remember_dry
UCLI_FLAGS = pyenv.web_function("_ucli_flags", {"psutil": psutil, "_UCLI_FLAGS_CACHE": {},
                                                "_with_ucli_tools": lambda s, flags: flags, "Optional": None})
RUST_ENV = dict(os.environ, CLAUDEOPS_DIR=TMP, GIT_OPTIONAL_LOCKS="0")
REPORT: dict = {}
FAIL = []


def rust(*args) -> str:
    return subprocess.run([BIN, *args], env=RUST_ENV, capture_output=True, text=True, check=True).stdout


def cmp_rows(py_rows, rust_snaps, key, fields):
    """Satırları anahtara göre eşler. Fark yalnız TÜM Rust görüntülerinde varsa kalıcı."""
    def diff(snap):
        pr = {key(r): r for r in py_rows}
        rr = {key(r): r for r in snap}
        out = Counter()
        out["only_python"] = len(pr.keys() - rr.keys())
        out["only_rust"] = len(rr.keys() - pr.keys())
        for k in pr.keys() & rr.keys():
            for f in fields:
                if pr[k].get(f) != rr[k].get(f):
                    out[f"field:{f}"] += 1
        return out
    ds = [diff(s) for s in rust_snaps]
    stable = Counter({k: min(d.get(k, 0) for d in ds) for k in set().union(*ds)})
    return {"python_rows": len(py_rows), "rust_rows": [len(s) for s in rust_snaps],
            "stable_diffs": {k: v for k, v in stable.items() if v}, "any_diffs": dict(sum(ds, Counter()))}


# ── list ─────────────────────────────────────────────────────────────────────
def py_list(as_json: bool) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ls_cmd.run(argparse.Namespace(no_cpu=True, base=None, json=as_json))
    return buf.getvalue()


r1 = json.loads(rust("list", "--json", "--no-cpu"))
p = json.loads(py_list(True))
r2 = json.loads(rust("list", "--json", "--no-cpu"))
REPORT["list_json"] = cmp_rows(p, [r1, r2], lambda r: (r["name"], r["pid"]), ["model", "cpu", "kind", "cwd"])
t1, tp, t2 = rust("list", "--no-cpu"), py_list(False), rust("list", "--no-cpu")
REPORT["list_table"] = {"identical_to_a_rust_snapshot": tp in (t1, t2), "lines": len(tp.splitlines())}
if not REPORT["list_table"]["identical_to_a_rust_snapshot"]:
    FAIL.append("list_table")

# ── scan ─────────────────────────────────────────────────────────────────────
SESSION_FIELDS = ["cwd", "sid", "model", "permission_mode", "effort", "cli", "resumed", "kind", "job_id",
                  "parked_job_id", "bg_pid"]
DERIVED = ["base", "fresh", "tmux", "no_terminal", "idle_spin", "ucli_flags", "usage_total", "transcript"]


def py_scan():
    mirrors_out: dict = {}
    AGY_WOULD_WRITE.clear()
    sessions = discovery.find_sessions(measure_cpu=False, mirrors_out=mirrors_out)
    rows, fallback = [], 0
    for s in sessions:
        tmux = tmux_backend.is_tmux_backed(s.pid)
        exact = None
        if s.cli == "claude" and s.sid:
            path = jsonl_path_for(s.cwd, s.sid)
            if path is not None and path.name == f"{s.sid}.jsonl":
                exact = str(path)
            elif path is not None:
                fallback += 1          # Python "cwd'deki en yeni dosya" düşüşü (Rust sapması 1): karşılaştırılmaz
        su._files.clear()
        row = {f: getattr(s, f) for f in ["name", "pid"] + SESSION_FIELDS}
        row.update(base=s.base, fresh=s.is_fresh, tmux=tmux, no_terminal=(not tmux) and discovery.terminal_lost(s.pid),
                   idle_spin=discovery.idle_spin(s.pid, s.cpu, tmux), ucli_flags=UCLI_FLAGS(s),
                   usage_total=su.usage_for_path(exact) if exact else None, transcript=exact)
        rows.append(row)
    orphans = discovery.orphan_report(sessions, tmux_backend.is_tmux_backed, 0.0, since={})
    return {"sessions": rows, "duplicates": discovery.duplicates(sessions), "mirrors": mirrors_out,
            "orphans": orphans, "agy_learned": sorted(AGY_WOULD_WRITE), "fallback": fallback}


s1 = json.loads(rust("scan", "--no-cpu"))
ps = py_scan()
s2 = json.loads(rust("scan", "--no-cpu"))
REPORT["scan_sessions"] = cmp_rows(ps["sessions"], [s1["sessions"], s2["sessions"]], lambda r: (r["name"], r["pid"]),
                                   SESSION_FIELDS + DERIVED)
REPORT["scan_sessions"]["python_newest_file_fallback"] = ps["fallback"]
for k in ("duplicates", "mirrors", "orphans", "agy_learned"):
    norm = lambda v: json.dumps(v, sort_keys=True)  # noqa: E731
    py_v = [list(x) for x in ps[k]] if k == "agy_learned" else ps[k]
    rs = [[list(x) for x in sorted(map(tuple, s[k]))] if k == "agy_learned" else s[k] for s in (s1, s2)]
    REPORT[f"scan_{k}"] = {"equal_to_a_rust_snapshot": norm(py_v) in {norm(x) for x in rs},
                           "python_count": len(py_v)}
REPORT["scan_rust_diag"] = {k: v for k, v in s1["diag"].items() if v}
for sec in ("list_json", "scan_sessions"):
    if REPORT[sec]["stable_diffs"]:
        FAIL.append(sec)
FAIL += [f"scan_{k}" for k in ("duplicates", "mirrors", "orphans", "agy_learned")
         if not REPORT[f"scan_{k}"]["equal_to_a_rust_snapshot"]]

# ── usage + transkript işaretleri (gerçek transkriptler, salt okuma) ──────────
projects = HOME / ".claude" / "projects"
live_paths = sorted({r["transcript"] for r in ps["sessions"] if r["transcript"]})
all_files = sorted(projects.glob("*/*.jsonl")) if projects.is_dir() else []
all_files = [f for f in all_files if f.is_file() and f.stat().st_uid == os.getuid()]
rnd = random.Random(ARGS.seed)
recent = sorted(all_files, key=lambda f: f.stat().st_mtime, reverse=True)[: ARGS.sample // 2]
others = [f for f in all_files if f not in set(recent)]
sample = sorted({*live_paths, *map(str, recent), *map(str, rnd.sample(others, min(len(others), ARGS.sample // 2)))})


def py_flag(fn, path):
    try:
        return fn(path)
    except Exception:
        return "error"


usage_diff, usage_none, marks = Counter(), 0, Counter()
for path in sample:
    su._files.clear()
    want = su.usage_for_path(path)
    got = json.loads(rust("usage", path))
    usage_none += want is None
    if want != got:
        usage_diff["files"] += 1
        for k in set(want or {}) | set(got or {}):
            if (want or {}).get(k) != (got or {}).get(k):
                usage_diff[f"field:{k}"] += 1
    # needs_ho transkript sinyalleri: git'siz dizinde (TMP) yalnız transkript dalı
    r = json.loads(rust("needs-ho", TMP, TMP, path))
    for fn in ("has_real_user_turn", "handover_done"):
        pv = py_flag(getattr(needs_ho, fn), path)
        rv = r[fn] if not isinstance(r[fn], dict) else "error"
        marks[f"{fn}:{'eq' if pv == rv else 'diff'}"] += 1
    pv = py_flag(lambda p: needs_ho.needs_ho("", TMP, p), path)
    rv = r["needs_ho"] if not isinstance(r["needs_ho"], dict) else "error"
    marks[f"needs_ho:{'eq' if pv == rv else 'diff'}"] += 1
REPORT["usage_real"] = {"files": len(sample), "python_none": usage_none, "diffs": dict(usage_diff)}
REPORT["needs_ho_transcripts"] = dict(marks)
if usage_diff:
    FAIL.append("usage_real")
if any(k.endswith(":diff") for k in marks):
    FAIL.append("needs_ho_transcripts")


# ── needs_ho: fikstür depoları (geçici dizin) + canlı oturum cwd'leri ───────
def git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@invalid", "-c", "commit.gpgsign=false",
                    "-c", "core.hooksPath=/dev/null", "-C", str(cwd), *a], check=True, capture_output=True,
                   env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))


def fixture_repos():
    base = Path(TMP, "repos")
    remote = base / "remote.git"
    remote.mkdir(parents=True)
    git(remote, "init", "-q", "--bare", "-b", "main")
    made = {}

    def repo(name):
        d = base / name
        d.mkdir()
        git(d, "init", "-q", "-b", "main")
        (d / "a").write_text("1")
        git(d, "add", "a")
        git(d, "commit", "-qm", "1")
        made[name] = d
        return d

    (base / "plain").mkdir()
    made["not_repo"] = base / "plain"
    repo("clean")
    (repo("untracked") / "u").write_text("x")
    (repo("modified") / "a").write_text("2")
    d = repo("staged")
    (d / "b").write_text("x")
    git(d, "add", "b")
    d = repo("pushed")
    git(d, "remote", "add", "origin", str(remote))
    git(d, "push", "-q", "origin", "main")
    d = repo("ahead")
    git(d, "remote", "add", "origin", str(remote))
    git(d, "fetch", "-q", "origin")
    git(d, "reset", "-q", "--hard", "origin/main")
    (d / "c").write_text("x")
    git(d, "add", "c")
    git(d, "commit", "-qm", "c")
    d = repo("behind")
    git(d, "remote", "add", "origin", str(remote))
    git(d, "fetch", "-q", "origin")
    git(d, "reset", "-q", "--hard", "origin/main")
    git(made["pushed"], "commit", "-q", "--allow-empty", "-m", "e")
    git(made["pushed"], "push", "-q", "origin", "main")
    git(d, "fetch", "-q", "origin")
    d = repo("detached")
    git(d, "checkout", "-q", "--detach")
    # Baseline'ı Python'un ad/içerik kuralıyla (`_repo_key`, `rev-parse HEAD`) yazar, Rust okur. `repo_baseline_set`
    # artık `atomic_write_text` (os.open + os.fdopen) kullanıyor; pyenv koruması fd sarmayı da yazma sayıp engellediği
    # için koruma gevşetilmedi, aynı dosya burada düz yazılır (yine geçici dizinde). Atomiklik py/tests'te sınanır.
    def baseline(d):
        k, h = needs_ho._repo_key(str(d)), needs_ho._git(str(d), "rev-parse", "HEAD")
        needs_ho._BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        (needs_ho._BASELINE_DIR / k).write_text(h)
    d = repo("baseline_head")
    baseline(d)
    d = repo("baseline_old")
    baseline(d)
    git(d, "commit", "-q", "--allow-empty", "-m", "yeni")
    return made


# Bilinen sapma (docs/rs-proc.md, sapma 4): serde NaN satırını reddeder, Python kabul eder. Ayrı sayılır.
KNOWN_TRANSCRIPTS = {"nan_line.jsonl"}
transcripts = [None] + sorted(str(p) for p in (pyenv.HERE.parent / "tests" / "golden" / "transcripts").glob("*.jsonl"))
repos = fixture_repos()
ts_file = Path(TMP, "last-handover.ts")
nho = Counter()
for ts in (None, "2000-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00", "bozuk"):
    if ts is None:
        ts_file.unlink(missing_ok=True)
    else:
        ts_file.write_text(ts + "\n")
    for name, cwd in repos.items():
        for tr in transcripts:
            r = json.loads(rust("needs-ho", TMP, str(cwd), *([tr] if tr else [])))
            py = {"needs_ho": py_flag(lambda c: needs_ho.needs_ho("", c, tr), str(cwd)),
                  "dirty": needs_ho.repo_dirty(str(cwd)), "untracked": needs_ho.repo_untracked_count(str(cwd)),
                  "committed_since": needs_ho.repo_committed_since(str(cwd))}
            known = tr is not None and Path(tr).name in KNOWN_TRANSCRIPTS
            for k, pv in py.items():
                rv = "error" if isinstance(r[k], dict) else r[k]
                nho[f"{k}:{'eq' if pv == rv else ('known_deviation' if known else 'diff')}"] += 1
ts_file.unlink(missing_ok=True)
live_cwds = sorted({(r["cwd"], r["transcript"]) for r in ps["sessions"] if r["cli"] == "claude"}, key=str)
for cwd, tr in live_cwds:
    r = json.loads(rust("needs-ho", TMP, cwd, *([tr] if tr else [])))
    py = {"needs_ho": py_flag(lambda c: needs_ho.needs_ho("", c, tr), cwd), "dirty": needs_ho.repo_dirty(cwd),
          "untracked": needs_ho.repo_untracked_count(cwd), "committed_since": needs_ho.repo_committed_since(cwd)}
    for k, pv in py.items():
        rv = "error" if isinstance(r[k], dict) else r[k]
        nho[f"live_{k}:{'eq' if pv == rv else 'diff'}"] += 1
REPORT["needs_ho_repos"] = {"fixture_cases": len(repos) * len(transcripts) * 4, "live_cwds": len(live_cwds),
                            "results": dict(sorted(nho.items()))}
if any(k.endswith(":diff") for k in nho):
    FAIL.append("needs_ho_repos")

REPORT["python_writes_blocked"] = len(pyenv.blocked())
REPORT["fail"] = FAIL
pyenv.rmtree(TMP)
print(json.dumps(REPORT, indent=1, ensure_ascii=False, sort_keys=True))
sys.exit(1 if FAIL else 0)
