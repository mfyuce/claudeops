"""`test` — değişen dosyalara göre ilgili testleri seç ve koş (hızlı geri bildirim; commit öncesi tam koşu yine şart).

  py/cops test                 # git: HEAD'e göre değişen + izlenmeyen dosyalar -> ilgili testler koşulur
  py/cops test --base main     # dal farkı (main...HEAD) + çalışma ağacı
  py/cops test --list          # yalnız listele (neden seçildiğiyle)
  py/cops test --deep          # paket içi ters-import kapanışı da (daha geniş)
  py/cops test py/claudeops/review.py   # dosyaları elle ver
Testler `py/tests` içinden `python3 -m unittest <modüller>` ile koşar (discover ile aynı sys.path)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .. import related_tests as rt


def changed_files(repo: Path, base: str = "") -> list:
    def git(*a, strict=False):
        r = subprocess.run(["git", *a], cwd=str(repo), capture_output=True, text=True, timeout=30)
        if r.returncode != 0 and strict:     # sessizce boş dönmek "ilgili test yok" (çıkış 0) demekti
            raise ValueError(f"taban okunamadı: {base} (git diff çıkış {r.returncode})")
        return [x for x in r.stdout.splitlines() if x.strip()] if r.returncode == 0 else []
    files = git("diff", "--name-only", "HEAD") + git("ls-files", "--others", "--exclude-standard")
    if base:
        branch = git("diff", "--name-only", f"{base}...HEAD", strict=True)
        files += branch
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
    try:
        files = [_res(f) for f in args.files] if args.files else changed_files(repo, args.base)
    except ValueError as e:
        print(f"HATA: {e}")
        return 2
    sel = rt.related_tests(files, str(py_root), deep=args.deep)
    dist = str(py_root / "webui" / "dist") + os.sep     # dist dosyaları seçime girer (`related_tests`)
    others = [f for f in files if not f.endswith(".py") and not f.startswith(dist)]
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
    # cwd=tests: `sys.path`e yer eklemeyen test dosyaları `claudeops`i bulamaz; paket kökünü PYTHONPATH'e koy
    env = dict(os.environ)
    env["PYTHONPATH"] = str(py_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    # `test_000_diag_env` ilk: mkdtemp/mkstemp ağını (`tmp_tracking`) ve geçici diag.log'u kurar (discover'daki gibi)
    mods = ["test_000_diag_env", *[m for m in sel if m != "test_000_diag_env"]]
    r = subprocess.run([sys.executable, "-m", "unittest", *mods], cwd=str(py_root / "tests"), env=env)
    return r.returncode
