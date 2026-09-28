"""Sabit yollar — tek kaynak (bash claudeops'taki dağınık path'lerin yerine)."""
import os
from pathlib import Path

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")
# Env override sadece izole test için (canlı roster yerine bir config kopyası); normalde set edilmez.
CLAUDEOPS_DIR = os.environ.get("CLAUDEOPS_DIR") or os.path.join(CLAUDE_DIR, "claudeops")
STATE_DIR = Path(CLAUDEOPS_DIR)   # needs_ho / handover timestamp için Path API

# claudeops repo'nun kendi kökü (bu dosyadan: claudeops/py/claudeops/paths.py → 2 parent yukarı).
# "LLM'e sor" diag session'ı için cwd — sorulan şey bu repo'nun kendi spawn koduysa mantıklı.
REPO_DIR = str(Path(__file__).resolve().parents[2])

ROSTER_TSV = os.path.join(CLAUDEOPS_DIR, "roster.tsv")   # name<TAB>cwd<TAB>model
MODELS_TSV = os.path.join(CLAUDEOPS_DIR, "models.tsv")   # name<TAB>model

SESSIONS_DIR = os.path.join(CLAUDE_DIR, "sessions")      # <pid>.json (gecikmeli yazılır!)
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")      # <encoded-cwd>/<sid>.jsonl
CONFIG_JSON = os.path.join(HOME, ".claude.json")         # bozulursa resume-hang

GUARD_LOCK = os.path.join(CLAUDEOPS_DIR, "guard.lock")


def ensure_private_state_dir() -> None:
    """`CLAUDEOPS_DIR` (roster.tsv/models.tsv/settings.json/hosts.json/
    web.token/guard.lock/instances.json/ucli_api_key — every piece of this
    tool's own state) must not be readable/traversable by another local
    account: this machine is multi-user (see project CLAUDE.md), and several
    of these files carry bearer tokens/API keys. A single `chmod 0700` on the
    directory covers every file inside it regardless of each file's own mode
    bits (a non-owner can't even `stat` a filename inside a 0700 dir) — cheaper
    and more robust than chasing down every individual writer. Call at the
    start of each long-lived entrypoint (`cops web`, guard) — idempotent,
    a plain `os.chmod` on an already-0700 dir is a no-op."""
    os.makedirs(CLAUDEOPS_DIR, exist_ok=True)
    os.chmod(CLAUDEOPS_DIR, 0o700)
