"""Benchmark task set (bench/PLAN.md, tasks 1-6).

Each task: {id, name, prompt, verify(workdir, answer) -> bool, needs_shell}.
`answer` is the CLI's final answer text as extracted by the adapter (for a
plain-text CLI that is its stdout). Verification is exact-match on the answer
or a check of file contents / the pytest result in the fresh workdir.
"""
import os
import re
import subprocess
import sys

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixture")


def norm(answer: str) -> str:
    """Exact match after trimming whitespace, surrounding backticks/quotes and one trailing period."""
    s = (answer or "").strip()
    if s.endswith("."):
        s = s[:-1]
    return s.strip().strip("`'\"").strip()


def _read(workdir, rel):
    try:
        with open(os.path.join(workdir, rel), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _orig(rel):
    return _read(FIXTURE, rel)


def pytest_outcome(workdir):
    """Return (returncode, set of failed test function names)."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rf", "-p", "no:cacheprovider"],
                       cwd=workdir, capture_output=True, text=True, timeout=120, env=env)
    failed = set(re.findall(r"^FAILED \S+::(\w+)", p.stdout, re.M))
    return p.returncode, failed


def _py_files(workdir):
    for d, dirs, files in os.walk(workdir):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(d, f)


def v1(workdir, answer):
    return norm(answer) == "7"


def v2(workdir, answer):
    return norm(answer) == "3"


def v3(workdir, answer):
    want = _orig("calc/config.py").replace("TIMEOUT_SECONDS = 30", "TIMEOUT_SECONDS = 45")
    return _read(workdir, "calc/config.py") == want


def v4(workdir, answer):
    for path in _py_files(workdir):
        with open(path, encoding="utf-8") as f:
            if re.search(r"\bcompute_total\b", f.read()):      # kelime sınırı: test_compute_total başka bir tanımlayıcıdır
                return False
    if "def sum_all(" not in (_read(workdir, "calc/mathops.py") or ""):
        return False
    rc, failed = pytest_outcome(workdir)
    return failed == {"test_mean"}          # rename must not break anything else; the planted bug stays


def v5(workdir, answer):
    return norm(answer) in ("test_mean", "tests/test_mathops.py::test_mean")


def v6(workdir, answer):
    for rel in ("tests/test_mathops.py", "tests/test_report.py"):
        if _read(workdir, rel) != _orig(rel):
            return False
    rc, failed = pytest_outcome(workdir)
    return rc == 0 and not failed


TASKS = [
    {"id": 1, "name": "read", "needs_shell": False, "verify": v1,
     "prompt": "What is the value of the constant MAX_RETRIES defined in calc/config.py? "
               "Reply with only the number, nothing else."},
    {"id": 2, "name": "grep", "needs_shell": False, "verify": v2,
     "prompt": "How many files in this repository contain the string TODO? "
               "Reply with only the number, nothing else."},
    {"id": 3, "name": "edit", "needs_shell": False, "verify": v3,
     "prompt": "In calc/config.py change the value of TIMEOUT_SECONDS from 30 to 45. "
               "Change nothing else. Reply with only DONE when finished."},
    {"id": 4, "name": "rename", "needs_shell": False, "verify": v4,
     "prompt": "Rename the function compute_total to sum_all everywhere in this repository "
               "(its definition, imports and all call sites, including tests). Change nothing else. "
               "Reply with only DONE when finished."},
    {"id": 5, "name": "run_tests", "needs_shell": True, "verify": v5,
     "prompt": "Run the test suite with `python3 -m pytest -q`. Exactly one test fails. "
               "Reply with only the name of the failing test function, nothing else."},
    {"id": 6, "name": "fix_bug", "needs_shell": True, "verify": v6,
     "prompt": "One test in this repository fails because of a bug in the source code under calc/. "
               "Fix the bug in the source (do not modify the tests) so that `python3 -m pytest -q` passes. "
               "Reply with only DONE when finished."},
]

EMPTY_PROMPT = "Reply with only the word OK."

BY_ID = {t["id"]: t for t in TASKS}
