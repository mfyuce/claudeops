"""Parite koşucusu: `python3 -m unittest` ile (yalıtım argv'ye bakar) kanca modülünü, review testlerini ve ek kenar
durumlarını koşar. Ortam (HOME, CLAUDEOPS_DIR, soket) Rust testinden gelir; elle çalıştırılmaz."""
import ast
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.abspath(os.environ["COPS_REV_PY"])
for var in ("CLAUDEOPS_DIR", "COPS_REV_PARITY_SOCK", "COPS_REV_PARITY_REPORT"):
    if not os.environ.get(var):
        sys.exit(f"{var} gerekli (cargo test -p cops-review-core ile koşulur)")
if os.path.realpath(os.environ["CLAUDEOPS_DIR"]).endswith("/.claude/claudeops"):
    sys.exit("canlı durum dizini reddedildi")

mods = []
for f in sorted(glob.glob(os.path.join(PY, "tests", "test_*.py"))):
    src = open(f, encoding="utf-8").read()
    if re.search(r"claudeops import[^\n]*\breview\b(?!_)|claudeops\.review\b(?!_)", src):
        mods.append(os.path.basename(f)[:-3])

env = dict(os.environ, PYTHONPATH=os.pathsep.join([HERE, os.path.join(PY, "tests"), PY]))
p = subprocess.run([sys.executable, "-m", "unittest", "parity_hook", *mods, "parity_edges", "parity_report"],
                   cwd=os.path.join(PY, "tests"), env=env, capture_output=True, text=True, timeout=1200)
rep = json.load(open(os.environ["COPS_REV_PARITY_REPORT"], encoding="utf-8"))
calls = sum(rep["calls"].values())
print(f"modül: {len(mods)}  karşılaştırılan çağrı: {calls}  işlev: {len(rep['calls'])}  fark: {len(rep['mismatches'])}  "
      f"atlanan: {sum(rep['skipped'].values())}  python testleri rc={p.returncode}")
print(p.stderr[-1500:])
for m in rep["mismatches"][:25]:
    print("FARK", json.dumps(m, ensure_ascii=False)[:1500])
print("atlanan:", json.dumps(rep["skipped"], ensure_ascii=False))
missing = sorted(set(rep["wrapped"]) - set(rep["calls"]))
if missing:
    print("HİÇ karşılaştırılmayan işlev:", missing)
sys.exit(1 if rep["mismatches"] or missing or calls == 0 or p.returncode else 0)
