"""bin/ucli gerideyse uyar: scripts/install-ucli.sh `bin/ucli.info` icine `source_git=<kisa sha>` yazar;
unified-cli HEAD'i ondan ilerideyse (git rev-list --count) "N commit geride" der. Saf, enjekte edilebilir git."""
from __future__ import annotations

import os
import subprocess
from typing import Callable, Dict, Optional

_DEFAULT_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "bin", "ucli")


def read_info(bin_path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        with open(bin_path + ".info", encoding="utf-8") as f:
            for ln in f:
                k, sep, v = ln.strip().partition("=")
                if sep and k:
                    out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def _git(src: str, *args: str) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", src, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def freshness(bin_path: str = "", src_dir: str = "", git: Callable[..., Optional[str]] = _git) -> Dict[str, object]:
    """{ok, stale, behind, built, head, message}. Bilgi eksikse stale=False (yanlis alarm yok), message dolu olabilir."""
    bin_path = bin_path or os.environ.get("UCLI_BIN") or _DEFAULT_BIN
    src = src_dir or os.environ.get("UNIFIED_CLI_DIR") or os.path.expanduser("~/work/projects/tmp/unified-cli")
    res: Dict[str, object] = {"ok": True, "stale": False, "behind": 0, "built": "", "head": "", "message": ""}
    info = read_info(bin_path)
    built = info.get("source_git", "")
    if built == "-":
        built = ""
    res["built"] = built
    if not built:
        res["message"] = "bin/ucli.info yok ya da source_git yok: ikili kaynaktan ayrisik olabilir (scripts/install-ucli.sh release --build)"
        return res
    if not src or not os.path.isdir(src):
        return res
    head = git(src, "rev-parse", "--short", "HEAD") or ""
    res["head"] = head
    if not head or head == built:
        return res
    n = git(src, "rev-list", "--count", f"{built}..HEAD")
    try:
        behind = int(n or "0")
    except ValueError:
        behind = 0
    res["behind"] = behind
    if behind > 0:
        res["stale"] = True
        res["message"] = (f"bin/ucli {behind} commit geride (derlenen {built}, HEAD {head}): "
                          "scripts/install-ucli.sh release --build")
    return res
