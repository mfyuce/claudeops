"""`check` — deploy öncesi mekanik smoke (ENG-06): derleme + import + panel bundle tutarlılığı.

  py/cops check            # hepsi; hata varsa çıkış 1 (service install restart'tan ÖNCE bunu çalıştırır)
Yalnız okur; servise dokunmaz. Import, servisin kendi python'uyla AYRI süreçte denenir (crash-loop kanıtı)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .. import dist_check

IMPORT_MODULES = ("claudeops.cli", "claudeops.commands.web", "claudeops.commands.service")


def compile_all(pkg_dir: Path) -> list:
    errs = []
    for f in sorted(pkg_dir.rglob("*.py")):
        if "__pycache__" in f.parts or ".venv" in f.parts:
            continue
        try:
            compile(f.read_bytes(), str(f), "exec")
        except (SyntaxError, ValueError, OSError) as e:   # kırık symlink/okunamayan dosya kontrolü çökertmesin
            errs.append(f"{f}: {e}")
    return errs


def import_check(py_root: Path, python: str = None) -> list:
    errs = []
    for m in IMPORT_MODULES:
        r = subprocess.run([python or sys.executable, "-c", f"import {m}"], cwd=str(py_root),
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            tail = (r.stderr.strip().splitlines() or ["?"])[-1]
            errs.append(f"import {m}: {tail}")
    return errs


def run_checks(py_root: Path, python: str = None) -> list:
    errs = compile_all(py_root / "claudeops")
    errs += import_check(py_root, python)
    d = dist_check.check_dist(str(py_root / "webui" / "dist"))
    if not d["ok"]:
        errs.append(f"dist: {d['reason']} {d['missing']}")
    return errs


def register(sub):
    p = sub.add_parser("check", help="deploy öncesi smoke: derleme + import + dist")
    p.set_defaults(func=run)


def run(args) -> int:
    errs = run_checks(Path(__file__).resolve().parents[2])
    for e in errs:
        print(f"✗ {e}", file=sys.stderr)
    if not errs:
        print("✓ check temiz (derleme, import, dist)")
    return 1 if errs else 0
