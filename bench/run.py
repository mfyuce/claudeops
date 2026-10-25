#!/usr/bin/env python3
"""ucli vs rival AI CLIs on a small deterministic task set (see bench/PLAN.md).

    python3 bench/run.py --cli ucli|claude|agy|codex|gemini [--tasks 1,2] [--reps 2] [--smoke] [--no-empty]

Each run copies bench/fixture/ into a fresh temp dir, runs the CLI headless with write
permission, samples the process tree every ~50 ms (peak RSS, peak concurrent processes,
total processes spawned), extracts the final answer + token usage from the CLI's own
JSON output, verifies, and appends one JSON line per run to bench/results.jsonl.
--smoke = `--version` timing + task 1, one rep (no empty-task startup run).

Secrets: the ucli key is read from ~/.claude/claudeops/ucli_api_key into the child's
environment only; it is never printed, logged or put on argv.
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tasks as T  # noqa: E402

try:
    import psutil
except ImportError:  # /proc fallback
    psutil = None

RESULTS = os.path.join(HERE, "results.jsonl")
RUNS_DIR = os.environ.get(
    "BENCH_RUNS_DIR",
    "/tmp/claude-1000/-home-fatihyuce-work-projects-tmp-claudeops-wt-revdev/"
    "63b21fa4-ca74-4c18-a7f9-2b2d497912de/scratchpad/bench_runs")
REPO = os.path.dirname(HERE)
UCLI_BIN = os.environ.get("BENCH_UCLI_BIN", os.path.expanduser("~/work/projects/tmp/unified-cli/target/release/ucli"))
UCLI_KEY_FILE = os.path.expanduser("~/.claude/claudeops/ucli_api_key")
TIMEOUT = int(os.environ.get("BENCH_TIMEOUT", "600"))
UNMEASURED = "ölçülemedi"


# ---------------------------------------------------------------- process-tree sampling
def _proc_children_map():
    kids = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
            kids.setdefault(ppid, []).append(int(name))
        except (OSError, IndexError, ValueError):
            pass
    return kids


def _proc_rss(pid):
    try:
        with open(f"/proc/{pid}/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, IndexError, ValueError):
        return 0


def tree(pid):
    """[(pid, rss_bytes)] for pid and all descendants."""
    if psutil:
        try:
            root = psutil.Process(pid)
            procs = [root] + root.children(recursive=True)
        except psutil.Error:
            return []
        out = []
        for p in procs:
            try:
                out.append((p.pid, p.memory_info().rss))
            except psutil.Error:
                pass
        return out
    kids = _proc_children_map()
    stack, out = [pid], []
    while stack:
        p = stack.pop()
        out.append((p, _proc_rss(p)))
        stack.extend(kids.get(p, []))
    return out


class Sampler(threading.Thread):
    def __init__(self, pid, interval=0.05):
        super().__init__(daemon=True)
        self.pid, self.interval = pid, interval
        self.peak_rss = 0
        self.peak_procs = 0
        self.seen = set()
        self.samples = 0
        self._ev = threading.Event()

    def run(self):
        while not self._ev.is_set():
            t = tree(self.pid)
            if t:
                self.samples += 1
                self.peak_rss = max(self.peak_rss, sum(r for _, r in t))
                self.peak_procs = max(self.peak_procs, len(t))
                self.seen.update(p for p, _ in t)
            self._ev.wait(self.interval)

    def stop(self):
        self._ev.set()
        self.join(1)


def run_measured(argv, cwd, env, timeout=TIMEOUT):
    t0 = time.monotonic()
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, start_new_session=True)
    s = Sampler(p.pid)
    s.start()
    timed_out = False
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except OSError:
            pass
        out, err = p.communicate()
    dt = time.monotonic() - t0
    s.stop()
    return {"rc": p.returncode, "stdout": out or "", "stderr": err or "", "secs": round(dt, 3),
            "timed_out": timed_out, "peak_rss_mib": round(s.peak_rss / 2**20, 1) if s.samples else UNMEASURED,
            "peak_procs": s.peak_procs, "procs_spawned": len(s.seen), "samples": s.samples}


# ---------------------------------------------------------------- helpers
def _json_objs(text):
    """Parse stdout as one JSON doc, else as JSONL; returns list of dicts."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        d = json.loads(text)
        return d if isinstance(d, list) else [d]
    except ValueError:
        pass
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def _tok(inp=None, out=None, cached=None, total=None, raw=None):
    if total is None and (inp is not None or out is not None):
        total = (inp or 0) + (out or 0)
    return {"input": inp, "output": out, "cached": cached, "total": total, "raw": raw}


# ---------------------------------------------------------------- adapters
class Adapter:
    name = ""
    binary = ""
    model = ""
    has_shell = True
    token_note = ""

    def available(self):
        return shutil.which(self.binary) or (os.path.isfile(self.binary) and os.access(self.binary, os.X_OK))

    def version_argv(self):
        return [self.binary, "--version"]

    def env(self, rundir):
        return dict(os.environ, PYTHONDONTWRITEBYTECODE="1", NO_COLOR="1")

    def argv(self, workdir, prompt, rundir):
        raise NotImplementedError

    def parse(self, res, rundir):
        """-> (answer_text, tokens dict or None, error string or None)"""
        raise NotImplementedError

    def redacted(self, argv):
        return [a if len(a) < 300 else a[:60] + "…" for a in argv]


class UcliAdapter(Adapter):
    name = "ucli"
    binary = UCLI_BIN
    model = os.environ.get("BENCH_UCLI_MODEL", "deepseek-v4-flash")
    has_shell = False   # native tools only: find/search/read/loc/outline/git/edit/write/delete/move, no shell

    def endpoint(self):
        if os.environ.get("BENCH_UCLI_ENDPOINT"):
            return os.environ["BENCH_UCLI_ENDPOINT"]
        # same default as py/claudeops/providers/ucli_provider.py endpoint() (DEFAULT_ENDPOINT)
        src = open(os.path.join(REPO, "py/claudeops/providers/ucli_provider.py"), encoding="utf-8").read()
        return re.search(r'^DEFAULT_ENDPOINT\s*=\s*"([^"]+)"', src, re.M).group(1)

    def env(self, rundir):
        e = super().env(rundir)
        try:
            with open(UCLI_KEY_FILE, encoding="utf-8") as f:
                e["UCLI_API_KEY"] = f.read().strip()     # process env only, never printed
        except OSError:
            pass
        return e

    def argv(self, workdir, prompt, rundir):
        return [self.binary, "--root", workdir, "chat", "--model", self.model, "--endpoint", self.endpoint(),
                "--api-key-env", "UCLI_API_KEY", "--max-steps", "20", "--allow-edit",
                "--state-dir", os.path.join(rundir, "ucli_state"),
                "--usage-log", os.path.join(rundir, "usage.jsonl"), prompt]

    def parse(self, res, rundir):
        objs = _json_objs(res["stdout"])
        d = objs[-1] if objs else {}
        if not isinstance(d, dict):
            d = {}
        ans = d.get("answer") if isinstance(d.get("answer"), str) else ""
        err = d.get("error")
        tok = None
        u = d.get("usage") if isinstance(d.get("usage"), dict) else None
        if u:
            tok = _tok(u.get("prompt_tokens"), u.get("completion_tokens"), u.get("cached_tokens"),
                       u.get("total_tokens"), u)
        log = os.path.join(rundir, "usage.jsonl")
        if os.path.exists(log):
            pi = co = ca = 0
            n = 0
            for o in _json_objs(open(log, encoding="utf-8").read()):
                uu = o.get("usage") if isinstance(o.get("usage"), dict) else {}
                if o.get("event") == "request" and uu:
                    n += 1
                    pi += uu.get("prompt_tokens") or 0
                    co += uu.get("completion_tokens") or 0
                    ca += uu.get("cached_tokens") or (uu.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            if n and tok is None:
                tok = _tok(pi, co, ca, None, {"usage_log_requests": n})
            elif tok is not None:
                tok["usage_log"] = {"requests": n, "prompt": pi, "completion": co, "cached": ca}
        return ans, tok, (str(err)[:300] if err else None)


class ClaudeAdapter(Adapter):
    name = "claude"
    binary = "claude"
    model = os.environ.get("BENCH_CLAUDE_MODEL", "claude-haiku-5-5")

    def env(self, rundir):
        return dict(super().env(rundir), DISABLE_AUTOUPDATER="1")

    def argv(self, workdir, prompt, rundir):
        return [self.binary, "-p", prompt, "--model", self.model, "--effort", "low", "--output-format", "json",
                "--permission-mode", "bypassPermissions", "--no-session-persistence",
                "--setting-sources", "project",
                "--settings", json.dumps({"claudeMdExcludes": ["**/CLAUDE.md"], "autoMemoryEnabled": False}),
                "--tools", "Bash,Read,Edit,Write,Glob,Grep",
                # smoke 2026-10-24 without these two: 110k-token context (user MCP servers/connectors/skills), 220k tokens for task 1
                "--strict-mcp-config", "--disable-slash-commands"]

    def parse(self, res, rundir):
        objs = _json_objs(res["stdout"])
        d = next((o for o in reversed(objs) if isinstance(o, dict) and o.get("type") == "result"), objs[-1] if objs else {})
        ans = d.get("result") or ""
        u = d.get("usage") or {}
        tok = None
        if u:
            inp = (u.get("input_tokens") or 0)
            cached = (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
            tok = _tok(inp + cached, u.get("output_tokens"), cached, None,
                       {"usage": u, "total_cost_usd": d.get("total_cost_usd"), "num_turns": d.get("num_turns")})
        err = ans if d.get("is_error") else None
        return ans, tok, err


class CodexAdapter(Adapter):
    name = "codex"
    binary = "codex"
    model = os.environ.get("BENCH_CODEX_MODEL", "gpt-5.6-luna")

    def argv(self, workdir, prompt, rundir):
        return [self.binary, "exec", "--json", "--ephemeral", "--skip-git-repo-check", "-s", "workspace-write",
                "-C", workdir, "-m", self.model, "-c", "model_reasoning_effort=low",
                "-o", os.path.join(rundir, "last_message.txt"), prompt]

    def parse(self, res, rundir):
        lm = os.path.join(rundir, "last_message.txt")
        ans = open(lm, encoding="utf-8").read() if os.path.exists(lm) else ""
        inp = out = cached = 0
        seen = False
        err = None
        for o in _json_objs(res["stdout"]):
            u = o.get("usage") if isinstance(o, dict) else None
            if isinstance(u, dict):
                seen = True
                inp += u.get("input_tokens") or 0
                out += u.get("output_tokens") or 0
                cached += u.get("cached_input_tokens") or 0
            if isinstance(o, dict) and o.get("type") in ("error", "turn.failed"):
                err = json.dumps(o)[:300]
        return ans, (_tok(inp, out, cached) if seen else None), err


class GeminiAdapter(Adapter):
    name = "gemini"
    binary = "gemini"
    model = os.environ.get("BENCH_GEMINI_MODEL", "gemini-2.5-flash")   # bundle's DEFAULT_GEMINI_FLASH_MODEL
    has_shell = False   # auto_edit: edit tools auto-approved, shell needs approval (none in headless); yolo was refused by the auto-mode classifier

    def argv(self, workdir, prompt, rundir):
        return [self.binary, "-p", prompt, "-m", self.model, "-o", "json", "--approval-mode", "auto_edit", "--skip-trust"]

    def parse(self, res, rundir):
        objs = _json_objs(res["stdout"])
        d = objs[-1] if objs else {}
        ans = d.get("response") or ""
        tok = None
        models = ((d.get("stats") or {}).get("models") or {})
        if models:
            inp = out = cached = tot = 0
            for m in models.values():
                t = m.get("tokens") or {}
                inp += t.get("prompt") or t.get("input") or 0
                out += t.get("candidates") or 0
                cached += t.get("cached") or 0
                tot += t.get("total") or 0
            tok = _tok(inp, out, cached, tot or None, {"models": list(models)})
        err = d.get("error")
        return ans, tok, (json.dumps(err)[:300] if err else None)


class AgyAdapter(Adapter):
    name = "agy"
    binary = "agy"
    model = os.environ.get("BENCH_AGY_MODEL", "gemini-3.8-flash-low")

    def argv(self, workdir, prompt, rundir):
        return [self.binary, "-p", prompt, "--model", self.model, "--effort", "low", "--output-format", "json",
                "--dangerously-skip-permissions", "--disable-slash-commands", "--print-timeout", f"{TIMEOUT}s"]

    def parse(self, res, rundir):
        objs = _json_objs(res["stdout"])
        d = objs[-1] if objs and isinstance(objs[-1], dict) else {}
        ans = ""
        for k in ("result", "response", "text", "output", "message"):
            if isinstance(d.get(k), str):
                ans = d[k]
                break
        if not objs:
            ans = res["stdout"]
        tok = None
        u = d.get("usage") or d.get("stats")
        if isinstance(u, dict) and u:
            tok = _tok(u.get("input_tokens") or u.get("prompt_tokens"), u.get("output_tokens") or u.get("completion_tokens"),
                       u.get("cached_tokens") or u.get("cache_read_input_tokens"), u.get("total_tokens"), u)
        err = d.get("error") or (d.get("result") if d.get("is_error") else None)
        return ans, tok, (str(err)[:300] if err else None)


ADAPTERS = {a.name: a for a in (UcliAdapter(), ClaudeAdapter(), CodexAdapter(), GeminiAdapter(), AgyAdapter())}


# ---------------------------------------------------------------- driver
def fresh_workdir():
    wd = tempfile.mkdtemp(prefix="wd_", dir=RUNS_DIR)
    shutil.copytree(T.FIXTURE, wd, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return wd


def record(row):
    with open(RESULTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def base_row(ad, kind):
    return {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "cli": ad.name, "model": ad.model, "kind": kind,
            "loadavg": [round(x, 2) for x in os.getloadavg()]}


def run_version(ad):
    row = base_row(ad, "version")
    res = run_measured(ad.version_argv(), cwd=RUNS_DIR, env=ad.env(RUNS_DIR), timeout=60)
    row.update(cmd=ad.version_argv(), secs=res["secs"], rc=res["rc"], peak_rss_mib=res["peak_rss_mib"],
               peak_procs=res["peak_procs"], procs_spawned=res["procs_spawned"], samples=res["samples"],
               version=(res["stdout"] or res["stderr"]).strip().splitlines()[:1])
    record(row)
    return row


def run_task(ad, task, rep):
    row = base_row(ad, "task" if task else "empty")
    rundir = tempfile.mkdtemp(prefix=f"{ad.name}_t{task['id'] if task else 0}_r{rep}_", dir=RUNS_DIR)
    wd = fresh_workdir()
    prompt = task["prompt"] if task else T.EMPTY_PROMPT
    argv = ad.argv(wd, prompt, rundir)
    row.update(task=task["id"] if task else 0, task_name=task["name"] if task else "empty", rep=rep,
               cmd=ad.redacted(argv), workdir=wd, rundir=rundir)
    if task and task["needs_shell"] and not ad.has_shell:
        row.update(status="yetenek yok", passed=None, note="no shell tool in this CLI; not counted as fail")
        record(row)
        return row
    res = run_measured(argv, cwd=wd, env=ad.env(rundir))
    for k in ("stdout", "stderr"):
        with open(os.path.join(rundir, k + ".txt"), "w", encoding="utf-8") as f:
            f.write(res[k])
    ans, tok, err = ad.parse(res, rundir)
    if task:
        try:
            passed = bool(task["verify"](wd, ans))
        except Exception as e:  # verification bug must not kill the run
            passed, err = False, f"verify error: {e}"
    else:
        passed = T.norm(ans).upper() == "OK"
    row.update(secs=res["secs"], rc=res["rc"], timed_out=res["timed_out"], peak_rss_mib=res["peak_rss_mib"],
               peak_procs=res["peak_procs"], procs_spawned=res["procs_spawned"], samples=res["samples"],
               answer=(ans or "")[:200], tokens=tok if tok else UNMEASURED, error=err,
               stderr_tail=res["stderr"][-400:] if (res["rc"] or not passed) else "",
               passed=passed, status="pass" if passed else "fail")
    record(row)
    return row


def summarize(rows):
    print(f"\n== summary ({len(rows)} rows) ==")
    for r in rows:
        if r["kind"] == "version":
            print(f"{r['cli']:7} version  {r['secs']:6.2f}s rc={r['rc']} rss={r['peak_rss_mib']}MiB {r.get('version')}")
            continue
        tok = r.get("tokens")
        tt = tok.get("total") if isinstance(tok, dict) else tok
        print(f"{r['cli']:7} t{r['task']} r{r['rep']} {r['status']:11} {r.get('secs', 0) or 0:6.1f}s "
              f"rss={r.get('peak_rss_mib')}MiB procs={r.get('peak_procs')}/{r.get('procs_spawned')} "
              f"tok={tt} load={r['loadavg'][0]} ans={r.get('answer', '')!r:.40} err={(r.get('error') or '')[:80]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", required=True, choices=sorted(ADAPTERS))
    ap.add_argument("--tasks", default="1,2,3,4,5,6")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--smoke", action="store_true", help="--version + task 1 once")
    ap.add_argument("--no-empty", action="store_true", help="skip the empty-task startup run")
    a = ap.parse_args()
    ad = ADAPTERS[a.cli]
    os.makedirs(RUNS_DIR, exist_ok=True)
    if not ad.available():
        row = dict(base_row(ad, "skip"), status="not installed")
        record(row)
        print(json.dumps(row))
        return 2
    if a.cli == "ucli" and not os.path.exists(UCLI_KEY_FILE):
        print("ucli key file missing; UCLI_API_KEY not set")
    ids = [1] if a.smoke else [int(x) for x in a.tasks.split(",") if x.strip()]
    reps = 1 if a.smoke else a.reps
    rows = [run_version(ad)]
    if not a.smoke and not a.no_empty:
        rows.append(run_task(ad, None, 1))
    for tid in ids:
        for rep in range(1, reps + 1):
            rows.append(run_task(ad, T.BY_ID[tid], rep))
    summarize(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
