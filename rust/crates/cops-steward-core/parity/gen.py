#!/usr/bin/env python3
"""`py/claudeops/steward.py` sabitleri ve veri sınıfları -> `src/consts_gen.rs`, `src/types_gen.rs`.
Kullanım: `python3 parity/gen.py [--check]` (--check: dosyalar güncel değilse çıkış 1)."""
import dataclasses, os, re, sys, types

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402
env.isolate()
from claudeops import steward as sw  # noqa: E402

# Yol ya da çalışma zamanı nesnesi: bu crate'e ait değil (G/Ç).
SKIP = {"CLAUDEOPS_DIR", "STEWARD_DIR", "PROJECTS_JSON", "IDEAS_JSON", "QUESTIONS_JSON", "STATE_JSON", "LOG_JSONL",
        "WORKSPACE_DIR", "BUNDLED_PERSONA", "_HELD", "_OWN_CACHE", "_LOG_LOCK", "_LOG_SEEN", "_NO_LOG_DAYS",
        "LOCK_TIMEOUT", "_LOCK_POLL", "annotations"}


def rs(s):
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "\\": out.append("\\\\")
        elif ch == '"': out.append('\\"')
        elif ch == "\n": out.append("\\n")
        elif ch == "\t": out.append("\\t")
        elif ch == "\r": out.append("\\r")
        elif o < 32 or o == 127: out.append("\\u{%x}" % o)
        else: out.append(ch)
    return '"' + "".join(out) + '"'


def rname(n):
    return n.lstrip("_").upper() if not n.startswith("_") else "P_" + n.lstrip("_").upper()


def is_const(n, v):
    return not n.startswith("__") and n not in SKIP and isinstance(v, (str, int, float, tuple, list, set, frozenset, dict, re.Pattern))


def module_constants():
    import ast
    tree = ast.parse(open(sw.__file__, encoding="utf-8").read())
    names = []
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for t in targets:
            for x in ast.walk(t):
                if isinstance(x, ast.Name) and x.id not in names:
                    names.append(x.id)
    return names


def consts():
    L = ["// ÜRETİLDİ: parity/gen.py (py/claudeops/steward.py). Elle düzenleme.", "#![allow(clippy::all)]",
         "use std::sync::LazyLock;", "use serde_json::Value;", ""]
    for n in module_constants():
        v = getattr(sw, n)
        if not is_const(n, v):
            continue
        r = rname(n)
        if isinstance(v, re.Pattern):
            flags = "".join(c for f, c in ((re.I, "i"), (re.M, "m"), (re.S, "s"), (re.X, "x")) if v.flags & f)
            pat = (f"(?{flags})" if flags else "") + v.pattern
            fancy = bool(re.search(r"\(\?<?[=!]|(?<!\\)\\[1-9]|\(\?P=", v.pattern))
            ty, ctor = ("fancy_regex::Regex", "fancy_regex::Regex::new") if fancy else ("regex::Regex", "regex::Regex::new")
            L.append(f"pub static {r}: LazyLock<{ty}> = LazyLock::new(|| {ctor}({rs(pat)}).expect({rs(n)}));")
        elif isinstance(v, bool):
            L.append(f"pub const {r}: bool = {str(v).lower()};")
        elif isinstance(v, str):
            L.append(f"pub const {r}: &str = {rs(v)};")
        elif isinstance(v, int):
            L.append(f"pub const {r}: i64 = {v};")
        elif isinstance(v, float):
            L.append(f"pub const {r}: f64 = {v!r};")
        elif isinstance(v, (tuple, list, set, frozenset)):
            items = list(v) if isinstance(v, (tuple, list)) else sorted(v)
            if all(isinstance(x, str) for x in items):
                L.append(f"pub const {r}: &[&str] = &[{', '.join(map(rs, items))}];")
            elif all(isinstance(x, int) for x in items):
                L.append(f"pub const {r}: &[i64] = &[{', '.join(map(str, items))}];")
            elif all(isinstance(x, float) for x in items):
                L.append(f"pub const {r}: &[f64] = &[{', '.join(map(repr, items))}];")
            else:
                raise SystemExit(f"desteklenmeyen sabit: {n} {v!r}")
        else:   # dict: sıra korunur
            import json
            js = json.dumps(v, ensure_ascii=False)
            L.append(f"pub static {r}: LazyLock<Value> = LazyLock::new(|| serde_json::from_str({rs(js)}).expect({rs(n)}));")
    return "\n".join(L) + "\n"


TYPES = {"str": "String", "int": "i64", "float": "f64", "bool": "bool", "Optional[str]": "Option<String>",
         "Optional[bool]": "Option<bool>", "Optional[int]": "Option<i64>", "List[str]": "Vec<String>",
         "List[Dict[str, Any]]": "Vec<Value>", "Dict[str, Any]": "Map<String, Value>", "Dict[str, str]": "IndexMap<String, String>",
         "Dict[str, Dict[str, Any]]": "IndexMap<String, Value>", "frozenset": "BTreeSet<String>"}


def rval(v, ty):
    if v is None: return "None"
    if ty.startswith("Option<"): return f"Some({rval(v, ty[7:-1])})"
    if ty == "String": return "String::new()" if v == "" else f"{rs(v)}.to_string()"
    if ty == "bool": return str(v).lower()
    if ty == "i64": return str(int(v))
    if ty == "f64": return repr(float(v))
    if not v: return "Default::default()"
    raise SystemExit(f"varsayılan çevrilemedi: {v!r}")


def structs():
    L = ["// ÜRETİLDİ: parity/gen.py (py/claudeops/steward.py veri sınıfları). Elle düzenleme.", "#![allow(clippy::all)]",
         "use indexmap::IndexMap;", "use serde::{Deserialize, Serialize};", "use serde_json::{Map, Value};",
         "use std::collections::BTreeSet;", ""]
    for cname in ("Project", "Idea", "Question", "SessionView", "Action", "World", "Config"):
        cls = getattr(sw, cname)
        L += ["#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]", "#[serde(default)]", f"pub struct {cname} {{"]
        defaults = []
        for f in dataclasses.fields(cls):
            ty = TYPES[str(f.type)]
            L.append(f"    pub {f.name}: {ty},")
            if f.default is not dataclasses.MISSING:
                defaults.append((f.name, rval(f.default, ty)))
            elif f.default_factory is not dataclasses.MISSING:
                defaults.append((f.name, rval(f.default_factory(), ty)))
            else:
                defaults.append((f.name, "Default::default()"))
        L += ["}", "", f"impl Default for {cname} {{", "    fn default() -> Self {", f"        {cname} {{"]
        L += [f"            {n}: {v}," for n, v in defaults]
        L += ["        }", "    }", "}", ""]
    return "\n".join(L)


def main():
    out = {"src/consts_gen.rs": consts(), "src/types_gen.rs": structs()}
    bad = []
    for rel, text in out.items():
        p = os.path.join(env.CRATE, rel)
        old = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        if "--check" in sys.argv:
            if old != text: bad.append(rel)
        else:
            open(p, "w", encoding="utf-8").write(text)
    if bad:
        print("güncel değil:", ", ".join(bad), file=sys.stderr); sys.exit(1)


main()
