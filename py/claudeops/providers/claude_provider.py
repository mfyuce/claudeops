"""claude CLI provider — bugüne kadarki tek/varsayılan davranış, aynen taşındı."""
from __future__ import annotations
import os
import shlex
from pathlib import Path
from typing import Dict, List, Optional

from .base import CliProvider
from ..paths import PROJECTS_DIR

MODEL_CHOICES = [
    "claude-sonnet-5",
    "claude-opus-5",
    "claude-fable-5",
    "claude-haiku-4-5-20251001",
]
PERMISSION_MODES = ["auto", "acceptEdits", "bypassPermissions", "manual", "dontAsk", "plan"]
EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]


def _encode_cwd(cwd: str) -> str:
    """CWD'yi project-dir encoding'e çevir: / ve _ → - ."""
    return cwd.replace("/", "-").replace("_", "-")


def _safe_mtime(p: Path) -> float:
    """stat().st_mtime — concurrent deletion'a karşı fallback 0.0."""
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def find_latest_jsonl(cwd: str) -> Optional[Path]:
    """CWD için en son değiştirilen jsonl dosyasını döndür (resume sid için)."""
    encoded = _encode_cwd(cwd)
    proj_dir = Path(PROJECTS_DIR) / encoded
    if not proj_dir.exists():
        return None
    jsonls = [p for p in proj_dir.iterdir() if p.suffix == ".jsonl" and p.is_file()]
    return max(jsonls, key=_safe_mtime) if jsonls else None


def _arg(cmd: List[str], flag: str) -> Optional[str]:
    """cmdline listesinde `flag`'ten SONRAKİ değeri döndür (yoksa None)."""
    try:
        i = cmd.index(flag)
    except ValueError:
        return None
    return cmd[i + 1] if i + 1 < len(cmd) else None


class ClaudeProvider(CliProvider):
    name = "claude"

    def resolve_resume_id(self, cwd: str) -> Optional[str]:
        jsonl = find_latest_jsonl(cwd)
        return jsonl.stem if jsonl else None

    def build_inner_command(self, cwd, model, permission_mode, effort,
                             resume_id, prompt, session_name) -> str:
        resume_arg = f"--resume {shlex.quote(resume_id)} " if resume_id else ""
        prompt_arg = f" {shlex.quote(prompt)}" if prompt else ""
        return (
            f"claude {resume_arg}"
            f"--model {shlex.quote(model)} "
            f"--permission-mode {shlex.quote(permission_mode)} "
            f"--effort {shlex.quote(effort)} "
            f"-n {shlex.quote(session_name)} "
            f"--remote-control {shlex.quote(session_name)}"
            f"{prompt_arg}"
        )

    def matches_proc(self, cmd: List[str]) -> bool:
        """Bash `^claude` anchor'ının karşılığı: argv[0]'ın basename'i 'claude'.
        'bash -c "claude ..."' wrapper'ında argv[0]='bash' → eler."""
        return bool(cmd) and os.path.basename(cmd[0]) == "claude"

    def extract_name(self, proc, cmd: List[str]) -> Optional[str]:
        return _arg(cmd, "--remote-control")

    def extract_info(self, cmd: List[str]) -> Dict[str, Optional[str]]:
        return {
            "sid": _arg(cmd, "--resume"),
            "model": _arg(cmd, "--model"),
            "permission_mode": _arg(cmd, "--permission-mode"),
            "effort": _arg(cmd, "--effort"),
        }

    def model_choices(self) -> List[str]:
        return MODEL_CHOICES

    def permission_modes(self) -> List[str]:
        return PERMISSION_MODES

    def effort_levels(self) -> List[str]:
        return EFFORT_LEVELS
