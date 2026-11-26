#!/usr/bin/env python3
"""EK 2 eşleme tablosu: `steward.py`nin HER işlev/metot/sınıf/modül ataması ve ilgili HER `test_*` metodu bir satır.
Rust eşi kaynakta `/// py: <ad>` doc satırından, parite testi `parity!("<ad>", <test>` çağrısından bulunur; kapsam dışı
nedenleri `parity/out_of_scope.json`. Test satırı: kayıtlı saf çağrılarının parite testleri; çağrısı yoksa `/// py: <dosya.Sınıf.test>`
taşıyan Rust testi ve/ya `parity/test_reasons.json` gerekçesi (`AÇIK: ` ile başlayan gerekçe tabloda ve özet sayıda açık kalır;
EKSİK sayılmaz). Çıktı `docs/rs-stew.md` içindeki işaretli bloğa yazılır.
Kullanım: `python3 parity/map.py [--check]` (--check: EKSİK satır varsa ya da blok güncel değilse çıkış 1)."""
import ast, glob, json, os, re, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402

CRATE, PY = env.CRATE, env.PY
REPO = os.path.dirname(PY)
DOC = os.path.join(REPO, "docs", "rs-stew.md")
BEGIN, END = "<!-- MAP:BEGIN (parity/map.py üretir) -->", "<!-- MAP:END -->"
# steward.py'nin dışarıdan kullandığı saf yardımcılar (modüllerinin geri kalanı başka izlerde)
DEPS = {"needs_ho.py": ["rfh_marker_in"], "textutil.py": ["collapse_ws"], "steward_ask.py": ["owner_class", "blocked_reason", "tour_eligible"]}


# değnekçi ailesinin hiçbir dalda Rust karşılığı olmayan modülleri: parite ile bağlı bir test bunları da çağırıyorsa satır açık kalır
UNPORTED = ("steward_keepwarm", "steward_nowork", "steward_advance", "steward_lessons", "steward_quota", "steward_jobs",
            "trust_dialog", "question_detail", "labels")


def load(name):
    with open(os.path.join(CRATE, "parity", name), encoding="utf-8") as f:
        return json.load(f)


def py_items(path, only=None):
    """[(ad, satır, tür)]: işlevler, sınıflar, metotlar, iç içe işlevler, modül atamaları."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    out = []

    def walk(node, prefix, in_func):
        for n in ast.iter_child_nodes(node):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + n.name
                out.append((name, n.lineno, "sınıf" if isinstance(n, ast.ClassDef) else "iç işlev" if in_func else "işlev"))
                walk(n, name + ".", not isinstance(n, ast.ClassDef))
                continue
            if not in_func and not prefix and isinstance(n, (ast.Assign, ast.AnnAssign)):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    for x in ast.walk(t):
                        if isinstance(x, ast.Name):
                            out.append((x.id, n.lineno, "atama"))
            walk(n, prefix, in_func)

    walk(tree, "", False)
    if only is not None:
        out = [i for i in out if i[0].split(".")[0] in only]
    return out


def rust_index():
    targets, tests = {}, {}
    for p in sorted(glob.glob(os.path.join(CRATE, "src", "*.rs"))):
        mod = os.path.splitext(os.path.basename(p))[0]
        pending, impl = [], None
        for line in open(p, encoding="utf-8"):
            m = re.match(r"\s*///\s*py:\s*(.+?)\s*$", line)
            if m:
                pending += [x.strip(" `") for x in m.group(1).split(",") if x.strip(" `")]
                continue
            m = re.match(r"impl(?:<[^>]*>)?\s+(\w+)", line)
            if m: impl = m.group(1)
            elif line.startswith("}"): impl = None
            m = re.match(r"\s*(?:pub(?:\([^)]*\))?\s+)?(?:fn|struct|enum|const|static|type)\s+(\w+)", line)
            if m and pending:
                path = f"{mod}::{impl + '::' if impl and line.startswith(' ') else ''}{m.group(1)}"
                for n in pending: targets[n] = path
                pending = []
    # üretilen sabitler ve veri sınıfları
    for line in open(os.path.join(CRATE, "src", "consts_gen.rs"), encoding="utf-8"):
        m = re.match(r"pub (?:const|static) (\w+):", line)
        if m:
            r = m.group(1)
            targets.setdefault(("_" + r[2:]) if r.startswith("P_") else r, f"consts_gen::{r}")
    for line in open(os.path.join(CRATE, "src", "types_gen.rs"), encoding="utf-8"):
        m = re.match(r"pub struct (\w+)", line)
        if m: targets.setdefault(m.group(1), f"types::{m.group(1)}")
    for p in sorted(glob.glob(os.path.join(CRATE, "tests", "**", "*.rs"), recursive=True)):
        mod = os.path.splitext(os.path.basename(p))[0]
        text = open(p, encoding="utf-8").read()
        for m in re.finditer(r'parity!\(\s*"([^"]+)",\s*(\w+)', text):
            tests.setdefault(m.group(1), []).append(f"{mod}::{m.group(2)}")
        # elle yazılmış testler: `/// py: ad` + #[test] fn
        for m in re.finditer(r"///\s*py:\s*([^\n]+)\n(?:\s*(?:///[^\n]*|#\[[^\]]*\])\n)*\s*fn\s+(\w+)", text):
            for n in m.group(1).split(","):
                tests.setdefault(n.strip(" `"), []).append(f"{mod}::{m.group(2)}")
    return targets, tests


def test_methods():
    out = []
    for p in sorted(glob.glob(os.path.join(PY, "tests", "test_*.py"))):
        s = open(p, encoding="utf-8").read()
        if not (os.path.basename(p).startswith("test_steward") or "steward as sw" in s or "import steward" in s):
            continue
        for c in ast.walk(ast.parse(s)):
            if isinstance(c, ast.ClassDef):
                for n in c.body:
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
                        out.append((os.path.basename(p)[:-3], c.name, n.name, n.lineno))
    return out


def outside_calls():
    """{test kimliği: testin (ve çağırdığı sınıf/modül yardımcılarının) bu crate DIŞINDAN çağırdığı claudeops işlevleri}."""
    out = {}
    for p in sorted(glob.glob(os.path.join(PY, "tests", "test_*.py"))):
        tree = ast.parse(open(p, encoding="utf-8").read())
        alias = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module in ("claudeops", "claudeops.commands", "claudeops.providers"):
                for a in n.names:
                    alias[a.asname or a.name] = a.name
        helpers = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for c in ast.walk(tree):
            if not isinstance(c, ast.ClassDef): continue
            methods = {n.name: n for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for name, m in methods.items():
                if not name.startswith("test"): continue
                todo, seen, found = [m], set(), set()
                while todo:
                    for x in ast.walk(todo.pop()):
                        if not isinstance(x, ast.Call): continue
                        f = x.func
                        if isinstance(f, ast.Name) and f.id in helpers and f.id not in seen:
                            seen.add(f.id); todo.append(helpers[f.id])
                        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)): continue
                        if f.value.id == "self" and f.attr in methods and "self." + f.attr not in seen:
                            seen.add("self." + f.attr); todo.append(methods[f.attr])
                        elif f.value.id in alias:
                            found.add((alias[f.value.id], f.attr))
                out[f"{os.path.basename(p)[:-3]}.{c.name}.{name}"] = found
    return out


def build():
    targets, tests = rust_index()
    oos = load("out_of_scope.json")         # {"gerekçe": [ad, ...]}
    why = {n: reason for reason, names in oos.items() for n in names}
    const_test = "generated::generated_files_are_current"
    rows, missing, partial, indirect = [], [], [], []
    items = [("steward.py", i) for i in py_items(os.path.join(PY, "claudeops", "steward.py"))]
    for mod, names in DEPS.items():
        items += [(mod, i) for i in py_items(os.path.join(PY, "claudeops", mod), only=set(names))]
    for mod, (name, line, kind) in items:
        target, ptest, status = targets.get(name, ""), tests.get(name, []), ""
        parts = name.split(".")
        parent = next((".".join(parts[:k]) for k in range(len(parts) - 1, 0, -1)
                       if targets.get(".".join(parts[:k])) or ".".join(parts[:k]) in why), None)
        if name in why:
            status = f"kapsam dışı: {why[name]}"
        elif target.startswith(("consts_gen::", "types::")):
            status, ptest = "tamam", ptest or [const_test]
        elif target:
            if not ptest: status = "EKSİK: parite testi yok"
            else: status = "tamam"
        elif kind == "iç işlev" and parent and parts[0] not in why:
            ptest = tests.get(parent, [])
            if targets.get(parent) and ptest:
                target, status = f"{targets[parent]} (içinde)", "tamam"
            else:
                status = "EKSİK"
        elif parent and parent in why:
            status = f"kapsam dışı: {why[parent]}"
        else:
            status = "EKSİK"
        if status.startswith("EKSİK"): missing.append(f"{mod}:{line} {name}")
        rows.append(f"| `{name}` ({mod}:{line}) | {('`' + target + '`') if target else '-'} | "
                    f"{', '.join(sorted(set(ptest))[:3]) or '-'} | {status} |")
    calls = json.load(open(os.path.join(CRATE, "fixtures", "test_calls.json"), encoding="utf-8"))
    manual = load("test_reasons.json")      # {"dosya" | "dosya.Sınıf.test": gerekçe}
    trows, opened, used = [], [], set()
    outside = outside_calls()
    io_names = set(load("io_functions.json"))
    for f, c, t, line in test_methods():
        key = f"{f}.{c}.{t}"
        called = calls.get(key, [])
        covered = sorted({x for fn in called for x in tests.get(fn, [])})
        uncovered = sorted(fn for fn in called if fn not in tests)
        direct = sorted(set(tests.get(key, [])))
        # doğrudan Rust testi olan satıra yalnız kendi adına yazılmış gerekçe eklenir (sınıf/dosya gerekçesi sızmaz)
        rkey = next((k for k in ((key,) if direct else (key, f"{f}.{c}", f)) if k in manual), None)
        reason = manual.get(rkey) if rkey and (direct or not called) else None
        if reason: used.add(rkey)
        is_open = bool(reason) and reason.startswith("AÇIK: ")
        if called and not uncovered:
            res = ", ".join(covered[:4]) + (f" (+{len(covered) - 4})" if len(covered) > 4 else "")
            other = sorted({f"{m}.{a}" for m, a in outside.get(key, ())
                            if (m != "steward" and a not in targets) or (m == "steward" and a in io_names)})
            if other:
                res += ("; testin bu crate dışındaki çağrıları (bu satır onları sınamaz): " + ", ".join(other[:5])
                        + (f" (+{len(other) - 5})" if len(other) > 5 else ""))
                partial.append(key)
            lost = sorted(f"{m}.{a}" for m, a in outside.get(key, ()) if m in UNPORTED)
            if lost:
                res += "; AÇIK (Rust'ta yok): " + ", ".join(lost)
                indirect.append(key)
        elif called:
            res = "EKSİK: parite testi olmayan " + ", ".join(uncovered[:4])
        elif direct or reason:
            parts_ = [f"Rust testi: {', '.join(direct)}"] if direct else []
            if is_open:
                parts_.append("AÇIK (taşınmadı ya da kısmen): " + reason[len("AÇIK: "):])
                opened.append(key)
            elif reason:
                parts_.append(reason if direct else f"gereksiz (bu crate'te sınanacak saf çağrı yok): {reason}")
            res = "; ".join(parts_)
        else:
            res = "EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı"
        if res.startswith("EKSİK"): missing.append(key)
        trows.append(f"| `{key}` | {res} |")
    for k in sorted(set(manual) - used):
        missing.append(f"test_reasons.json: kullanılmayan anahtar {k}")
    count = (f"Test satırı özeti: {len(trows)} satır; doğrudan açık (aşağıda `AÇIK`) {len(opened)}; parite ile bağlı olup "
             f"crate dışı çağrısı da olan {len(partial)}, bunlardan Rust'ta hiç olmayan değnekçi modülünü de çağıran (`AÇIK (Rust'ta yok)`) "
             f"{len(indirect)}.")
    block = "\n".join([BEGIN, "", f"### Python öğeleri ({len(rows)} satır)", "", "| Python adı (dosya:satır) | Rust karşılığı | parite testi | durum |",
                       "|---|---|---|---|", *rows, "", f"### Python testleri ({len(trows)} satır)", "",
                       "| Python testi | Rust karşılığı / gerekçe |", "|---|---|", *trows, "", END])
    block = block.replace(f"### Python testleri ({len(trows)} satır)\n", f"### Python testleri ({len(trows)} satır)\n\n{count}\n")
    return block, missing, count


def main():
    block, missing, count = build()
    doc = open(DOC, encoding="utf-8").read() if os.path.exists(DOC) else f"# İz: rs/stew\n\n{BEGIN}\n{END}\n"
    new = doc[:doc.index(BEGIN)] + block + doc[doc.index(END) + len(END):]
    if "--check" not in sys.argv:
        open(DOC, "w", encoding="utf-8").write(new)
    print(f"EKSİK satır: {len(missing)}")
    print(count)
    for m in missing[:int(os.environ.get("MAP_SHOW", "20"))]:
        print("  ", m)
    if "--check" in sys.argv and (missing or new != doc):
        if new != doc: print("docs/rs-stew.md eşleme bloğu güncel değil")
        sys.exit(1)


main()
