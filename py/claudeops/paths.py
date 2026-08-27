"""Sabit yollar — tek kaynak (bash claudeops'taki dağınık path'lerin yerine)."""
import os
from pathlib import Path

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")
CLAUDEOPS_DIR = os.path.join(CLAUDE_DIR, "claudeops")
STATE_DIR = Path(CLAUDEOPS_DIR)   # needs_ho / handover timestamp için Path API

ROSTER_TSV = os.path.join(CLAUDEOPS_DIR, "roster.tsv")   # name<TAB>cwd<TAB>model
MODELS_TSV = os.path.join(CLAUDEOPS_DIR, "models.tsv")   # name<TAB>model

VENDOR_DIR = os.path.join(CLAUDEOPS_DIR, "vendor")       # xterm.js/css cache (ilk kullanımda indirilir)

SESSIONS_DIR = os.path.join(CLAUDE_DIR, "sessions")      # <pid>.json (gecikmeli yazılır!)
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")      # <encoded-cwd>/<sid>.jsonl
CONFIG_JSON = os.path.join(HOME, ".claude.json")         # bozulursa resume-hang

GUARD_LOCK = "/tmp/claudeops/guard.lock"
