"""Session spawn — gnome-terminal + claude CLI.

Bash spawn pattern'inin yerine:
  gnome-terminal -- bash -c "cd CWD && claude ... < /dev/null; exec bash"
  < /dev/null zorunlu (stdin/pty reject olmaz).
  DISPLAY env değişkeni gerekli (headless cron'da otomatik tespit).
"""
from __future__ import annotations
import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional

from .paths import PROJECTS_DIR


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


def detect_display() -> str:
    """DISPLAY'i tespit et: env → :1 → :0 sırasıyla."""
    env = os.environ.get("DISPLAY", "")
    if env:
        return env
    for d in (":1", ":0"):
        if Path(f"/tmp/.X{d[1:]}-lock").exists():
            return d
    return ":1"


def spawn_session(
    name: str,
    cwd: str,
    model: str,
    display: Optional[str] = None,
    permission_mode: str = "auto",
    effort: str = "max",
    force_new: bool = False,
    prompt: Optional[str] = None,
    dry_run: bool = False,
) -> str:
    """Session'ı gnome-terminal ile aç.

    force_new=True → --new (konuşma sıfırdan).
    force_new=False → en son jsonl'i resume et, yoksa --new.
    prompt → --new ile opsiyonel ilk mesaj (verilmezse boş/idle başlar).

    Returns: "resume:<sid[:8]>", "new", veya "[dry-run] ..." dry_run modunda.
    """
    if display is None:
        display = detect_display()

    if force_new:
        resume_arg = ""   # bash: resume_arg="" for --new; claude has no --new flag
        kind = "new"
    else:
        jsonl = find_latest_jsonl(cwd)
        if jsonl:
            sid = jsonl.stem
            resume_arg = f"--resume {shlex.quote(sid)}"
            kind = f"resume:{sid[:8]}"
        else:
            resume_arg = ""
            kind = "new"

    # shlex.quote: boşluk/özel karakter içeren prompt'u bash -c içinde güvenle geçir
    prompt_arg = f" {shlex.quote(prompt)}" if prompt else ""

    # < /dev/null sadece headless (-p) spawn'da gerekli; gnome-terminal görsel spawn'da KULLANMA
    # --new ile < /dev/null → claude stdin'i okuyamaz → başlamadan çıkıyor
    resume_prefix = f"{resume_arg} " if resume_arg else ""
    inner = (
        f"cd {shlex.quote(cwd)} && "
        f"claude {resume_prefix}"
        f"--model {shlex.quote(model)} "
        f"--permission-mode {shlex.quote(permission_mode)} "
        f"--effort {shlex.quote(effort)} "
        f"-n {shlex.quote(name)} "
        f"--remote-control {shlex.quote(name)}"
        f"{prompt_arg}"
    )

    if dry_run:
        return f"[dry-run] {kind}  cmd: {inner[:80]}..."

    env = os.environ.copy()
    env["DISPLAY"] = display
    subprocess.Popen(
        ["gnome-terminal", "--window", f"--title={name}",
         f"--working-directory={cwd}",
         "--", "bash", "-c", f"{inner}; exec bash"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return kind
