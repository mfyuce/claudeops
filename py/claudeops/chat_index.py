"""chat_backup: repo başına INDEX.jsonl + INDEX.md (cli, host, proje, cwd, oturum, başlık, ilk/son tarih).
Yalnız dosyanın başı (64 KB) ve sonu (16 KB) okunur (bellek/IO dostu). Bulunamayan alan boş bırakılır, uydurulmaz."""
import datetime
import json
import os
import re
from typing import Any, Dict, Iterator, List, Optional

HEAD, TAIL = 64 * 1024, 16 * 1024
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _lines(path: str, size: int) -> Iterator[Dict[str, Any]]:
    """Başın tam satırları + sonun tam satırları (JSON olanlar)."""
    with open(path, "rb") as f:
        head = f.read(HEAD)
        tail = b""
        if size > HEAD:
            f.seek(max(HEAD, size - TAIL))
            tail = f.read()
    chunks = [head.rsplit(b"\n", 1)[0] if size > HEAD else head]
    if tail:
        chunks.append(tail.split(b"\n", 1)[-1])
    for ch in chunks:
        for ln in ch.splitlines():
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if isinstance(d, dict):
                yield d


def _text_of(msg: Any) -> str:
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        return _text_of(msg.get("content") or msg.get("text") or "")
    if isinstance(msg, list):
        return " ".join(_text_of(x) for x in msg if isinstance(x, (str, dict)))
    return ""


def _iso(v: Any) -> str:
    if isinstance(v, (int, float)) and v > 0:
        v = v / 1000 if v > 1e11 else v
        try:
            return datetime.datetime.fromtimestamp(v).strftime("%Y-%m-%dT%H:%M:%S")
        except (OverflowError, OSError, ValueError):   # taşan/geçersiz zaman damgası INDEX üretimini durdurmasın
            return ""
    return v[:19] if isinstance(v, str) and len(v) >= 10 and v[:4].isdigit() else ""


def _valid_day(d: Any) -> str:
    """Yol parçasındaki gün 'YYYY-MM-DD' değilse ('bilinmiyor' vb.) boş: tarih sütununu ve sıralamayı bozmasın."""
    return d if isinstance(d, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", d) else ""


def classify(rel: str) -> Optional[Dict[str, str]]:
    """Göreli yoldan {kind, cli, host, project, session} ya da None (dizin dışı)."""
    p = rel.replace("\\", "/").split("/")
    if p[0] == "memory" and len(p) >= 5:
        return {"kind": "memory", "host": p[1], "cli": p[2], "project": p[3], "session": "/".join(p[4:])}
    if p[0] != "local" or len(p) < 3:
        return None
    area = p[1]
    m = re.match(r"^(claude|codex)-(.+)-(projects|sessions)$", area)
    if m and m.group(2):                       # uzak host: local/claude-<host>-projects, local/codex-<host>-sessions
        return {"kind": "chat", "cli": m.group(1), "host": m.group(2), "project": p[2] if m.group(3) == "projects" and len(p) > 3 else "",
                "session": os.path.splitext(p[-1])[0]}
    if area == "claude-ucli":                  # local/claude-ucli/<proje>/<oturum>.jsonl
        return {"kind": "chat", "cli": "claude-ucli", "project": p[2], "session": os.path.splitext(p[-1])[0]}
    if area == "claude-projects":
        return {"kind": "chat", "cli": "claude", "project": p[2], "session": os.path.splitext(p[-1])[0]}
    if area == "codex-dump" and len(p) >= 5:
        return {"kind": "chat", "cli": "codex", "project": p[2], "session": os.path.splitext(p[-1])[0], "day": p[3]}
    if area == "gemini-dump" and len(p) >= 6:
        return {"kind": "chat", "cli": "gemini/" + p[2], "project": p[3], "session": os.path.splitext(p[-1])[0], "day": p[4]}
    if area == "codex-sessions":
        return {"kind": "chat", "cli": "codex", "project": "", "session": os.path.splitext(p[-1])[0]}
    return {"kind": "other", "cli": area, "project": "", "session": os.path.splitext(p[-1])[0]}


def entry(repo: str, rel: str, host: str) -> Optional[Dict[str, Any]]:
    c = classify(rel)
    if not c:
        return None
    full = os.path.join(repo, rel)
    try:
        size = os.path.getsize(full)
    except OSError:
        return None
    e: Dict[str, Any] = {"kind": c["kind"], "cli": c["cli"], "host": c.get("host", host), "project": c["project"],
                         "cwd": "", "session": c["session"], "title": "", "first": _valid_day(c.get("day", "")), "last": _valid_day(c.get("day", "")),
                         "bytes": size, "path": rel}
    if c["kind"] != "chat" or not rel.endswith(".jsonl"):
        return e
    first = last = ""
    try:
        for d in _lines(full, size):
            ts = _iso(d.get("timestamp") or d.get("ts") or d.get("ts_ms"))
            if ts:
                first = first if first and first <= ts else ts
                last = last if last >= ts else ts
            pl = d.get("payload") if isinstance(d.get("payload"), dict) else {}
            sm = d.get("summary") if isinstance(d.get("summary"), dict) else {}     # gemini döküm özet satırı
            cwd = d.get("cwd") or pl.get("cwd") or sm.get("workspace")
            if cwd and not e["cwd"]:
                e["cwd"] = str(cwd)
            t = d.get("customTitle") or d.get("title") or sm.get("title") or (d.get("summary") if isinstance(d.get("summary"), str) else "") or pl.get("title")
            if isinstance(t, str) and t and not e["title"]:
                e["title"] = t[:100]
            if not e["title"] and d.get("type") == "user":
                tx = _text_of(d.get("message")).strip().replace("\n", " ")
                if tx and not tx.startswith("<"):
                    e["title"] = tx[:100]
    except OSError:
        pass
    if first:
        e["first"] = first
    if last:
        e["last"] = last
    return e


def build(repo: str, files: List[str], host: str) -> List[Dict[str, Any]]:
    out = [x for x in (entry(repo, r, host) for r in files) if x]
    out.sort(key=lambda x: (x["kind"], x["cli"], x["project"], x["first"], x["session"]))
    return out


def render_md(entries: List[Dict[str, Any]], name: str) -> str:
    agg: Dict[Any, Dict[str, Any]] = {}
    for e in entries:
        a = agg.setdefault((e["kind"], e["cli"], e["project"]), {"n": 0, "first": "", "last": "", "bytes": 0})
        a["n"] += 1
        a["bytes"] += e["bytes"]
        if e["first"] and (not a["first"] or e["first"] < a["first"]):
            a["first"] = e["first"]
        if e["last"] and e["last"] > a["last"]:
            a["last"] = e["last"]
    lines = [f"# {name} INDEX", "", f"{len(entries)} dosya; ayrıntı: INDEX.jsonl (alanlar: kind, cli, host, project, cwd, session, title, first, last, bytes, path).", ""]
    for kind in ("chat", "memory", "other"):
        rows = [(k, v) for k, v in sorted(agg.items()) if k[0] == kind]
        if not rows:
            continue
        lines += [f"## {kind}", "", "| cli | proje | dosya | ilk | son | KB |", "|---|---|---:|---|---|---:|"]
        for (_k, cli, proj), v in rows:
            lines.append(f"| {cli} | {proj or '-'} | {v['n']} | {v['first'][:10] or '?'} | {v['last'][:10] or '?'} | {v['bytes'] // 1024} |")
        lines.append("")
    return "\n".join(lines)


def write_index(repo: str, files: List[str], host: str) -> List[str]:
    """INDEX.jsonl + INDEX.md yazar; dönüş: göreli yollar (git add için)."""
    ents = build(repo, files, host)
    with open(os.path.join(repo, "INDEX.jsonl"), "w", encoding="utf-8") as f:
        for e in ents:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(os.path.join(repo, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write(render_md(ents, os.path.basename(repo.rstrip("/"))))
    return ["INDEX.jsonl", "INDEX.md"]
