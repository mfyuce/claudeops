"""Değişen dosya -> ilgili test (tam koşu ~4 dk; geliştirirken önce ilgili alt küme).

Bir test dosyası bir modülle "ilgili" sayılır: modülü import ediyorsa (`from claudeops.x import y`, `from claudeops
import x as y`, `import claudeops.x`) ya da metninde `"claudeops.x...."` dizesi geçiyorsa (`mock.patch` hedefi).
`deep=True`: paket içi ters-import kapanışı (değişen modülü import eden modülleri import eden testler de). Saf mantık;
git ve unittest çalıştırma `commands/test_cmd.py`de. Bu yalnız HIZLI geri bildirim: commit öncesi tam koşu yine şart."""
from __future__ import annotations

import ast
import os
import re
from typing import Dict, Iterable, List, Optional, Set

PKG = "claudeops"
_STR_RE = re.compile(r"""["'](claudeops(?:\.[A-Za-z_][A-Za-z0-9_]*)+)""")


def module_of(path: str, py_root: str) -> Optional[str]:
    """`py/claudeops/commands/web.py` -> `claudeops.commands.web`; paket dışı / .py değilse None."""
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(py_root))
    if rel.startswith("..") or not rel.endswith(".py"):
        return None
    parts = rel[:-3].split(os.sep)
    if parts[0] != PKG:
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _known(name: str, modules: Set[str]) -> Optional[str]:
    """`claudeops.a.b.Sym` -> en uzun bilinen modül öneki."""
    parts = name.split(".")
    for i in range(len(parts), 0, -1):
        cand = ".".join(parts[:i])
        if cand in modules:
            return cand
    return None


def imports_of(source: str, modules: Set[str], self_mod: str = "") -> Set[str]:
    """Kaynaktaki `claudeops.*` bağımlılıkları (bilinen modüllere indirgenmiş). Göreli import `self_mod`a göre çözülür."""
    out: Set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    pkg = self_mod.rsplit(".", 1)[0] if self_mod else ""
    for node in ast.walk(tree) if tree is not None else ():
        if isinstance(node, ast.Import):
            for a in node.names:
                m = _known(a.name, modules)
                if m:
                    out.add(m)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = pkg.split(".") if pkg else []
                anchor = anchor[:len(anchor) - (node.level - 1)] if node.level > 1 else anchor
                base = ".".join(anchor + ([base] if base else []))
            for a in node.names:
                m = _known(f"{base}.{a.name}", modules) or _known(base, modules)
                if m:
                    out.add(m)
    for s in _STR_RE.findall(source):
        m = _known(s, modules)
        if m:
            out.add(m)
    out.discard(self_mod)
    return out


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def package_modules(py_root: str) -> Dict[str, str]:
    """modül adı -> dosya yolu (`py_root/claudeops` altı)."""
    out: Dict[str, str] = {}
    for d, dirs, files in os.walk(os.path.join(py_root, PKG)):
        dirs[:] = [x for x in dirs if x not in ("__pycache__", ".venv")]
        for f in files:
            if f.endswith(".py"):
                p = os.path.join(d, f)
                m = module_of(p, py_root)
                if m:
                    out[m] = p
    return out


def related_tests(changed: Iterable[str], py_root: str, tests_dir: Optional[str] = None,
                  deep: bool = False) -> Dict[str, List[str]]:
    """{test modül adı: [onu seçtiren değişen modül(ler)]}. Değişen test dosyasının kendisi de seçilir."""
    tests_dir = tests_dir or os.path.join(py_root, "tests")
    mods = package_modules(py_root)
    names = set(mods)
    targets: Dict[str, Set[str]] = {}          # modül -> onu tetikleyen değişen modüller
    direct_tests: Set[str] = set()
    for c in changed:
        ap = os.path.abspath(c)
        if os.path.dirname(ap) == os.path.abspath(tests_dir) and os.path.basename(ap).startswith("test") and ap.endswith(".py"):
            direct_tests.add(os.path.basename(ap)[:-3])
            continue
        m = module_of(ap, py_root)
        if m:
            targets.setdefault(m, set()).add(m)
    if deep and targets:
        rdeps: Dict[str, Set[str]] = {}
        for m, p in mods.items():
            for d in imports_of(_read(p), names, m):
                rdeps.setdefault(d, set()).add(m)
        queue = list(targets)
        while queue:
            cur = queue.pop()
            for user in rdeps.get(cur, ()):
                if user not in targets:
                    targets[user] = set(targets[cur])
                    queue.append(user)
                elif not targets[cur] <= targets[user]:
                    targets[user] |= targets[cur]
                    queue.append(user)
    out: Dict[str, Set[str]] = {t: {"(test)"} for t in direct_tests}
    if targets:
        for f in sorted(os.listdir(tests_dir)):
            if not (f.startswith("test") and f.endswith(".py")):
                continue
            hit = imports_of(_read(os.path.join(tests_dir, f)), names) & set(targets)
            if hit:
                out.setdefault(f[:-3], set()).update(*(targets[h] for h in hit))
    return {k: sorted(v) for k, v in sorted(out.items())}
