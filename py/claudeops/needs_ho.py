"""needs_ho — session handover gerektiriyor mu?

Bash'teki needs_ho() ve yardımcıları buraya port edildi.
4 sinyal: repo_dirty | untracked | committed_since_baseline | jsonl-no-RFH.
BİRİ pozitifse → ho gerek (return True).
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Optional

_STATE_DIR = Path.home() / ".claude" / "claudeops"
_BASELINE_DIR = _STATE_DIR / "baselines"


# ── Git helpers ──────────────────────────────────────────────────────────────

def _git(cwd: str, *args: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True, text=True, timeout=15
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _is_git_repo(cwd: str) -> bool:
    return bool(_git(cwd, "rev-parse", "--git-dir"))


def repo_dirty(cwd: str) -> bool:
    """Tracked modified/staged VEYA unpushed VEYA remote ileride mi?

    Bash'te olduğu gibi untracked (??) sayılmaz.
    """
    if not _is_git_repo(cwd):
        return False
    porcelain = _git(cwd, "status", "--porcelain")
    tracked = sum(1 for l in porcelain.splitlines() if not l.startswith("??"))
    if tracked > 0:
        return True
    br = _git(cwd, "branch", "--show-current")
    if not br:
        return False  # detached HEAD → temiz say
    remotes = _git(cwd, "remote").splitlines()
    for r in remotes:
        r = r.strip()
        if not r:
            continue
        ref = f"{r}/{br}"
        exists = _git(cwd, "rev-parse", "--verify", ref)
        if not exists:
            continue
        ahead = _git(cwd, "rev-list", "--count", f"{ref}..HEAD")
        behind = _git(cwd, "rev-list", "--count", f"HEAD..{ref}")
        if int(ahead or "0") > 0 or int(behind or "0") > 0:
            return True
    return False


def repo_untracked_count(cwd: str) -> int:
    if not _is_git_repo(cwd):
        return 0
    out = _git(cwd, "ls-files", "--others", "--exclude-standard")
    return len([l for l in out.splitlines() if l.strip()])


def _repo_key(cwd: str) -> str:
    import hashlib
    toplevel = _git(cwd, "rev-parse", "--show-toplevel")
    return hashlib.sha1(toplevel.encode()).hexdigest() if toplevel else ""


def _repo_baseline_get(cwd: str) -> str:
    k = _repo_key(cwd)
    if not k:
        return ""
    p = _BASELINE_DIR / k
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def repo_baseline_set(cwd: str) -> None:
    """Ho sonrası HEAD'i baseline yap."""
    k = _repo_key(cwd)
    h = _git(cwd, "rev-parse", "HEAD")
    if k and h:
        _BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        (_BASELINE_DIR / k).write_text(h)


def repo_committed_since(cwd: str) -> bool:
    """Son ho baseline'ından beri yeni commit var mı?"""
    if not _is_git_repo(cwd):
        return False
    bid = _repo_baseline_get(cwd)
    if bid:
        head = _git(cwd, "rev-parse", "HEAD")
        return bool(head) and head != bid
    # Baseline yoksa (ilk kurulum): son ho timestamp ile karşılaştır
    ts_file = _STATE_DIR / "last-handover.ts"
    try:
        base_ts = ts_file.read_text().strip()
    except OSError:
        return False
    ci = _git(cwd, "log", "-1", "--format=%cI")
    return bool(ci) and ci > base_ts


# ── jsonl helpers ─────────────────────────────────────────────────────────────

def handover_done(jsonl_path: str) -> bool:
    """jsonl'de RFH var mı ve sonrasında yeni user isteği yok mu?

    Bash handover_done() port: last_rfh >= last_user AND last_rfh > 0.
    """
    last_rfh = -1
    last_user = -1
    i = 0
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                i += 1
                t = o.get("type")
                msg = o.get("message", {})
                content = msg.get("content") if isinstance(msg, dict) else None
                text = ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = " ".join(
                        c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    )
                if "READY FOR HANDOVER" in text:
                    last_rfh = i
                if t == "user":
                    if isinstance(content, list):
                        is_tool = any(
                            isinstance(c, dict) and c.get("type") == "tool_result"
                            for c in content
                        )
                        if not is_tool and text.strip():
                            last_user = i
                    elif isinstance(content, str) and content.strip():
                        last_user = i
    except OSError:
        return False
    return last_rfh > 0 and last_rfh >= last_user


# ── Main entry ────────────────────────────────────────────────────────────────

def needs_ho(sid: str, cwd: str, jsonl_path: Optional[str] = None) -> bool:
    """Session ho gerektiriyor mu? True = ho gerek, False = atla.

    4 sinyal (bash needs_ho port):
      1. repo_dirty (tracked-mod/staged/unpushed/behind)
      2. untracked dosya var
      3. baseline'dan beri yeni commit
      4. jsonl var ama RFH yok / RFH sonrası yeni istek
    """
    if repo_dirty(cwd):
        return True
    if repo_untracked_count(cwd) > 0:
        return True
    if repo_committed_since(cwd):
        return True
    if jsonl_path and not handover_done(jsonl_path):
        return True
    return False
