"""chat_backup: .db -> gün/oturum bazlı JSONL döküm (ham .db gdrive:chat-raw/'a gider, git'e girmez).
Codex: thread_items (+threads.cwd=proje). Gemini/agy: steps/gen_metadata protobuf BLOB'ları şemasız çözülür;
tarih = steps.metadata içindeki ilk makul unix-saniye alanı, bulunamazsa 'bilinmiyor'. Proje alanı doğrulanmadı -> 'bilinmiyor'."""
import json, os, re, sqlite3, datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple

UNKNOWN = "bilinmiyor"


def _ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect("file:" + path + "?mode=ro", uri=True)


def _varint(b: bytes, i: int) -> Tuple[int, int]:
    n = s = 0
    while True:
        c = b[i]; i += 1
        n |= (c & 0x7F) << s; s += 7
        if not c & 0x80:
            return n, i


def pb_decode(b: bytes, depth: int = 0) -> Optional[List[Any]]:
    """Şemasız protobuf: [(alan, değer)]; çözülemezse None. Değer: int | str | list(iç mesaj) | 'hex:..'"""
    out: List[Any] = []
    i = 0
    try:
        while i < len(b):
            key, i = _varint(b, i)
            f, wt = key >> 3, key & 7
            if f == 0:
                return None
            if wt == 0:
                v, i = _varint(b, i)
            elif wt == 2:
                ln, i = _varint(b, i)
                raw = b[i:i + ln]
                if len(raw) != ln:
                    return None
                i += ln
                v = _bytes_val(raw, depth)
            elif wt == 1:
                v = int.from_bytes(b[i:i + 8], "little"); i += 8
            elif wt == 5:
                v = int.from_bytes(b[i:i + 4], "little"); i += 4
            else:
                return None
            out.append((f, v))
    except IndexError:
        return None
    return out


def _bytes_val(raw: bytes, depth: int) -> Any:
    try:
        t = raw.decode("utf-8")
        if t and all(c.isprintable() or c in "\n\r\t" for c in t):
            return t
    except UnicodeDecodeError:
        pass
    if depth < 8 and raw:
        sub = pb_decode(raw, depth + 1)
        if sub:
            return sub
    return "hex:" + raw[:64].hex() + ("…" if len(raw) > 64 else "")


def _jsonable(x: Any) -> Any:
    if isinstance(x, list):
        d: Dict[str, Any] = {}
        for f, v in x:
            d.setdefault(str(f), []).append(_jsonable(v))
        return {k: (v[0] if len(v) == 1 else v) for k, v in d.items()}
    return x


def _first_ts(x: Any) -> Optional[int]:
    """İç içe ilk makul unix-saniye (2015..2035)."""
    if isinstance(x, list):
        for _f, v in x:
            if isinstance(v, int) and 1420070400 <= v <= 2051222400:
                return v
            r = _first_ts(v) if isinstance(v, list) else None
            if r:
                return r
    return None


def _day(ts: Optional[float]) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%F") if ts else UNKNOWN


def dump_codex(thread_db: str, state_db: str) -> Iterator[Tuple[str, str, str, Dict[str, Any]]]:
    """(proje, gün, oturum, satır). Proje = threads.cwd."""
    st = _ro(state_db)
    meta = {r[0]: (r[1], r[2]) for r in st.execute("select id,cwd,title from threads")}
    c = _ro(thread_db)
    for tid, turn, iid, ordn, ms, js, typ in c.execute(
            "select thread_id,turn_id,item_id,rollout_ordinal,created_at_ms,item_json,item_type from thread_items order by thread_id,rollout_ordinal"):
        cwd, title = meta.get(tid, (UNKNOWN, ""))
        try:
            item = json.loads(js)
        except ValueError:
            item = js
        yield (cwd or UNKNOWN, _day(ms / 1000 if ms else None), tid,
               {"ordinal": ordn, "ts_ms": ms, "turn": turn, "item": iid, "type": typ, "title": title, "data": item})


_CWD_RE = re.compile(r'"11": "\\n.(/(?:home|tmp|root)/[^"\\]+)"')


def _gemini_cwd(c: sqlite3.Connection) -> str:
    """Proje = ilk adımların payload'ındaki 11. alan (çalışma dizini); bulunamazsa 'bilinmiyor' (örnekte ~%40 bulunuyor)."""
    for (pl,) in c.execute("select step_payload from steps where step_payload is not null order by idx limit 15"):
        d = pb_decode(pl)
        if d:
            m = _CWD_RE.search(json.dumps(_jsonable(d), ensure_ascii=False))
            if m:
                return m.group(1)
    return UNKNOWN


_SUMM: Dict[str, Dict[str, Any]] = {}


def _summary(db: str) -> Dict[str, Any]:
    """conversation_summaries.db (konuşma dizininin kardeşi): workspace_uris -> proje, title, last_modified. Yoksa {}."""
    sdb = os.path.join(os.path.dirname(os.path.dirname(db)), "conversation_summaries.db")
    if sdb not in _SUMM:
        m: Dict[str, Any] = {}
        try:
            for cid, title, uris, lm in _ro(sdb).execute("select conversation_id,title,workspace_uris,last_modified_time from conversation_summaries"):
                try:
                    u = next(iter(json.loads(uris or "[]")), "")
                except ValueError:
                    u = ""
                m[cid] = {"project": u[7:] if u.startswith("file://") else u, "title": title or "", "last_modified": lm}
        except sqlite3.Error:
            pass
        _SUMM[sdb] = m
    return _SUMM[sdb].get(os.path.basename(db)[:-3], {})


def dump_gemini(db: str) -> Iterator[Tuple[str, str, str, Dict[str, Any]]]:
    sess = os.path.basename(db)[:-3]
    c = _ro(db)
    summ = _summary(db)
    proj = summ.get("project") or _gemini_cwd(c)      # önce özet tablosu (workspace_uris), yoksa payload alan 11
    if summ:
        yield proj, UNKNOWN if not summ.get("last_modified") else str(summ["last_modified"])[:10], sess, {
            "summary": {"title": summ.get("title"), "workspace": summ.get("project"), "last_modified": summ.get("last_modified")}}
    for idx, stype, status, md, pl, ri in c.execute("select idx,step_type,status,metadata,step_payload,render_info from steps order by idx"):
        mdd = pb_decode(md) if md else None
        ts = _first_ts(mdd)
        pld = pb_decode(pl) if pl else None
        if pld and mdd:                       # payload alan 5, metadata'nın kopyası: yineleme (boyut)
            pld = [(f, v) for f, v in pld if not (f == 5 and v == mdd)]
        row = {"idx": idx, "step_type": stype, "status": status, "ts": ts,
               "metadata": _jsonable(mdd) if mdd else None,
               "payload": _jsonable(pld) if pld else (pl.hex()[:200] if pl else None)}
        yield proj, _day(ts), sess, row
    for idx, data, _sz in c.execute("select idx,data,size from gen_metadata order by idx"):
        d = pb_decode(data) if data else None
        yield proj, _day(_first_ts(d)), sess, {"gen_metadata_idx": idx, "data": _jsonable(d) if d else None}


def write_jsonl(rows: Iterator[Tuple[str, str, str, Dict[str, Any]]], out_root: str, cli: str) -> List[str]:
    """<out_root>/<cli>/<proje-slug>/<gün>/<oturum>.jsonl; dönüş: yazılan göreli yollar. Dosya başına tek geçiş (append)."""
    written: Dict[str, None] = {}
    handles: Dict[str, Any] = {}
    cur = None
    try:
        for proj, day, sess, row in rows:
            if sess != cur:                       # satırlar oturum bazlı gruplu gelir; fd sınırı için öncekini kapat
                for h in handles.values():
                    h.close()
                handles.clear()
                cur = sess
            slug = re.sub(r"[^A-Za-z0-9._-]+", "-", proj).strip("-") or UNKNOWN
            rel = os.path.join(cli, slug, day, sess + ".jsonl")
            if rel not in handles:
                p = os.path.join(out_root, rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                handles[rel] = open(p, "a" if rel in written else "w", encoding="utf-8")
                written[rel] = None
            handles[rel].write(json.dumps(row, ensure_ascii=False) + "\n")
    finally:
        for h in handles.values():
            h.close()
    return list(written)


# ------------------------------------------------------------------ periodic entegrasyonu
def _db_sources(home: str) -> List[Tuple[str, str, str]]:
    """(cli, alt, db yolu). Canlı önce; ayna yalnız canlıda olmayan (silinmiş) oturumlar için."""
    import glob
    mir = os.path.join(home, ".claude", "claudeops", "backups", "chat-mirror")
    out: List[Tuple[str, str, str]] = []
    seen = set()
    for base in (os.path.join(home, ".gemini"), os.path.join(mir, "gemini")):
        for p in sorted(glob.glob(os.path.join(base, "*", "conversations", "*.db"))):
            key = (os.path.basename(os.path.dirname(os.path.dirname(p))), os.path.basename(p))
            if key not in seen:
                seen.add(key)
                out.append(("gemini", key[0], p))
    for base in (os.path.join(home, ".codex"), os.path.join(mir, "codex")):
        th, st = os.path.join(base, "thread_history_1.sqlite"), os.path.join(base, "state_5.sqlite")
        if os.path.exists(th) and os.path.exists(st):
            out.append(("codex", "", th))
            break
    return out


def stage_dumps(stage: str, stamps: Dict[str, str], home: Optional[str] = None) -> Dict[str, Any]:
    """Değişen db'leri stage/<cli>/... altına JSONL döker; dosya mtime'ı = içerik günü (commit tarihi için). Hata db başına yutulur."""
    home = home or os.path.expanduser("~")
    st = {"dumped": 0, "skipped": 0, "errors": [], "files": 0}
    for cli, sub, p in _db_sources(home):
        try:
            s = os.stat(p)
        except OSError:
            continue
        sig = f"{s.st_size}:{int(s.st_mtime)}"
        if stamps.get(p) == sig:
            st["skipped"] += 1
            continue
        try:
            if cli == "codex":
                rows = dump_codex(p, os.path.join(os.path.dirname(p), "state_5.sqlite"))
                rels = write_jsonl(rows, stage, "codex")
            else:
                rels = write_jsonl(dump_gemini(p), stage, os.path.join("gemini", sub))
        except Exception as e:  # noqa: BLE001 — bozuk/kilitli db diğerlerini durdurmasın
            st["errors"].append(f"{p}: {type(e).__name__}: {e}"[:200])
            continue
        for rel in rels:
            day = rel.split(os.sep)[-2]
            if day != UNKNOWN:
                t = datetime.datetime.strptime(day, "%Y-%m-%d").replace(hour=12).timestamp()
                os.utime(os.path.join(stage, rel), (t, t))
        stamps[p] = sig
        st["dumped"] += 1
        st["files"] += len(rels)
    return st


def raw_to_remote(remote: str, home: Optional[str] = None, timeout: int = 10800) -> str:
    """Ham .db/.sqlite -> rclone remote (git'e girmez). '' = ok, aksi hata metni."""
    import socket, subprocess
    home = home or os.path.expanduser("~")
    host = socket.gethostname()
    mir = os.path.join(home, ".claude", "claudeops", "backups", "chat-mirror")
    jobs = [(os.path.join(home, ".gemini"), "gemini", ["*/conversations/*.db", "*/conversation_summaries.db"]),
            (os.path.join(mir, "gemini"), "gemini", ["*/conversations/*.db", "*/conversation_summaries.db"]),
            (os.path.join(home, ".codex"), "codex", ["*.sqlite", "*.sqlite-wal"]),
            (os.path.join(mir, "codex"), "codex", ["*.sqlite", "*.sqlite-wal"])]
    errs = []
    for src, name, inc in jobs:
        if not os.path.isdir(src):
            continue
        cmd = ["rclone", "copy", "--update", "--transfers", "4", src, f"{remote.rstrip('/')}/{host}/{name}"]
        for i in inc:
            cmd += ["--include", i]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0:
                errs.append(f"{name}: rc={r.returncode} {r.stderr[-150:]}")
        except (OSError, subprocess.TimeoutExpired) as e:
            errs.append(f"{name}: {type(e).__name__}")
    return "; ".join(errs)
