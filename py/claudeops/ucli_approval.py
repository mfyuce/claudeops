"""ucli kalıcı onay (`--approval-dir` / `--resume-approval`) dosya kanalı ve kayıt defteri. Yaprak modül (web/provider içe aktarmaz).
Tasarım: docs/ucli-approval-design.md. ucli sözleşmesi (unified-cli `approval.rs`): `DIR/pending/<id>.json` (arayüzün göstereceği özet),
`DIR/suspended/<id>.json` (görev durumu: claudeops OKUMAZ), `DIR/answers/<id>.json` (cevap: `{id, decision, edited_arguments?, note?}`).

Güvenlik duruşu:
- Dizin `<CLAUDEOPS_DIR>/ucli_approval/<run_key>` (0700), çalışma kökünün DIŞINDA.
- Sürdürme argv'si KAYIT DEFTERİNDEN gelir, istekten değil: cevap yazan kökü/izni değiştiremez.
- Cevap yalnız bekleyen kaydın `id`'siyle eşleşirse, `decision` listede ve süre dolmamışsa yazılır; `edited_arguments` en çok 64 KiB.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .atomic_json import atomic_write_json, file_lock
from .paths import CLAUDEOPS_DIR

ROOT = os.path.join(CLAUDEOPS_DIR, "ucli_approval")
MAX_EDITED_BYTES = 64 * 1024
MAX_NOTE_BYTES = 4 * 1024
DECISIONS = ("approve", "approve_session", "reject", "edit")
STATES = ("running", "suspended", "resuming", "done", "expired")
_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


def _index_path() -> str:
    return os.path.join(ROOT, "index.json")


def dir_for(run_key: str, create: bool = False) -> str:
    if not _KEY.match(run_key or ""):
        raise ValueError("geçersiz run_key")
    d = os.path.join(ROOT, run_key)
    if create:
        os.makedirs(ROOT, mode=0o700, exist_ok=True)
        for sub in ("", "pending", "suspended", "answers"):
            p = os.path.join(d, sub) if sub else d
            os.makedirs(p, mode=0o700, exist_ok=True)
            os.chmod(p, 0o700)
    return d


def _load_index() -> Dict[str, Dict[str, Any]]:
    try:
        with open(_index_path(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def register(run_key: str, cwd: str, session: str, argv_resume: List[str], owner: str = "") -> str:
    """Koşuyu kayda alır (`running`) ve dizinini açar. Döner: dizin."""
    d = dir_for(run_key, create=True)
    with file_lock(_index_path()):
        idx = _load_index()
        idx[run_key] = {"cwd": cwd, "session": session, "argv_resume": [str(a) for a in argv_resume],
                        "owner": owner, "created_at": time.time(), "state": "running"}
        atomic_write_json(_index_path(), idx, mode=0o600)
    return d


def get(run_key: str) -> Optional[Dict[str, Any]]:
    rec = _load_index().get(run_key)
    return rec if isinstance(rec, dict) else None


def set_state(run_key: str, state: str) -> bool:
    if state not in STATES:
        raise ValueError("geçersiz durum")
    with file_lock(_index_path()):
        idx = _load_index()
        if run_key not in idx:
            return False
        idx[run_key]["state"] = state
        atomic_write_json(_index_path(), idx, mode=0o600)
    return True


def parse_suspended(stdout: str) -> Optional[Dict[str, Any]]:
    """ucli stdout'unda `{"suspended":{id,state,resume}}` satırı (sondan arar); yoksa None."""
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        s = d.get("suspended") if isinstance(d, dict) else None
        if isinstance(s, dict) and isinstance(s.get("id"), str) and _ID.match(s["id"]):
            return {"id": s["id"]}
    return None


def pending(run_key: str, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Bekleyen onaylar (`pending/*.json`): yalnız arayüzde gösterilecek alanlar; `expired` süre dolduysa true.
    `suspended/` (transkript) ASLA okunmaz. Bozuk dosya atlanır."""
    now = time.time() if now is None else now
    out: List[Dict[str, Any]] = []
    pdir = os.path.join(dir_for(run_key), "pending")
    try:
        names = sorted(os.listdir(pdir))
    except OSError:
        return out
    for fn in names:
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(pdir, fn), encoding="utf-8") as f:
                q = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(q, dict) or not isinstance(q.get("id"), str) or not _ID.match(q["id"]):
            continue
        exp = q.get("expires_at")
        out.append({"id": q["id"], "kind": str(q.get("kind") or ""), "tool": str(q.get("tool") or ""),
                    "summary": str(q.get("summary") or ""), "created_at": q.get("created_at"),
                    "expires_at": exp, "expired": isinstance(exp, (int, float)) and exp <= now})
    return out


def answer(run_key: str, approval_id: str, decision: str, edited_arguments: Any = None, note: str = "",
           now: Optional[float] = None) -> Tuple[bool, str]:
    """Cevabı yazar. (ok, hata). Bekleyen kayıt yoksa, kimlik uyuşmazsa, süre dolduysa ya da girdi geçersizse reddeder."""
    if decision not in DECISIONS:
        return False, "invalid decision"
    if (decision == "edit") != (edited_arguments is not None):
        return False, "edited_arguments only with decision edit"
    if edited_arguments is not None:
        if not isinstance(edited_arguments, dict):
            return False, "edited_arguments must be an object"
        if len(json.dumps(edited_arguments).encode("utf-8")) > MAX_EDITED_BYTES:
            return False, "edited_arguments too large"
    if len((note or "").encode("utf-8")) > MAX_NOTE_BYTES:
        return False, "note too large"
    if not _ID.match(approval_id or ""):
        return False, "invalid id"
    match = [p for p in pending(run_key, now) if p["id"] == approval_id]
    if not match:
        return False, "no such pending approval"
    if match[0]["expired"]:
        return False, "approval expired"
    body: Dict[str, Any] = {"id": approval_id, "decision": decision}
    if edited_arguments is not None:
        body["edited_arguments"] = edited_arguments
    if note:
        body["note"] = note
    atomic_write_json(os.path.join(dir_for(run_key), "answers", approval_id + ".json"), body, mode=0o600)
    return True, ""
