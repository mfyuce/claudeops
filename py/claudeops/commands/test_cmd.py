"""`test` — değişen dosyalara göre ilgili testleri seç ve koş (hızlı geri bildirim; commit öncesi tam koşu yine şart).

  py/cops test                 # git: HEAD'e göre değişen + izlenmeyen dosyalar -> ilgili testler koşulur
  py/cops test --base main     # dal farkı (main...HEAD) + çalışma ağacı
  py/cops test --list          # yalnız listele (neden seçildiğiyle)
  py/cops test --deep          # paket içi ters-import kapanışı da (daha geniş)
  py/cops test py/claudeops/review.py   # dosyaları elle ver
Testler `py/tests` içinden `python3 -m unittest <modüller>` ile koşar (discover ile aynı sys.path)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .. import related_tests as rt


def changed_files(repo: Path, base: str = "") -> list:
    def git(*a):
        r = subprocess.run(["git", *a], cwd=str(repo), capture_output=True, text=True, timeout=30)
        return [x for x in r.stdout.splitlines() if x.strip()] if r.returncode == 0 else []
    files = git("diff", "--name-only", "HEAD") + git("ls-files", "--others", "--exclude-standard")
    if base:
        files += git("diff", "--name-only", f"{base}...HEAD")
    return sorted({str(repo / f) for f in files})


def register(sub):
    p = sub.add_parser("test", help="değişen dosyalara göre ilgili testleri koş")
    p.add_argument("files", nargs="*", help="dosyalar (boşsa git'ten)")
    p.add_argument("--base", default="", help="dal farkı için taban (ör. main)")
    p.add_argument("--deep", action="store_true", help="ters-import kapanışı")
    p.add_argument("--list", action="store_true", help="yalnız listele, koşma")
    p.set_defaults(func=run)


def run(args) -> int:
    py_root = Path(__file__).resolve().parents[2]
    repo = py_root.parent
    def _res(f: str) -> str:      # `py/cops` py/ dizinine geçer: göreli yol önce oradan, yoksa repo kökünden
        p = Path(f)
        if p.is_absolute() or p.exists():
            return str(p.resolve())
        return str((repo / f).resolve())
    files = [_res(f) for f in args.files] if args.files else changed_files(repo, args.base)
    sel = rt.related_tests(files, str(py_root), deep=args.deep)
    others = [f for f in files if not f.endswith(".py")]
    if not sel:
        print("ilgili test yok" + (f" (python dışı değişiklik: {len(others)} dosya; panel için tsc/dist_check)" if others else ""))
        return 0
    for t, why in sel.items():
        print(f"{t}  <- {', '.join(why)}")
    if others:
        print(f"not: python dışı {len(others)} dosya test seçimine girmedi")
    if args.list:
        return 0
    print(f"{len(sel)} test dosyası koşuluyor…", flush=True)
    r = subprocess.run([sys.executable, "-m", "unittest", *sel], cwd=str(py_root / "tests"))
    return r.returncode
