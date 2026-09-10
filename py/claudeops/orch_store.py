"""Orkestrasyon run kalıcılığı — ~/.claude/claudeops/orchestration/
{draft.json, runs/<run_id>.json}. roster.tsv/models.tsv/web.token/hosts.json
ile AYNI "repo DIŞI, kaynak-of-truth" deseni; `hosts.py`'nin atomik-yazım
(tmp + os.replace) + 0600 disiplinini birebir uyguluyor — bu dizinde token
YOK ama tutarlılık için aynı kalıp korunuyor (ör. ileride bir run'a bir
API-anahtarı/secret eklenirse dosya izinleri zaten hazır).

Leaf modül (`paths`'e bağımlı, `commands/` paketine bağımlı DEĞİL) —
`orchestration.py`/`commands/web_orch.py` bunu import eder, tersi olmaz.
"""
from __future__ import annotations
import dataclasses
import json
import os
from typing import Any, Dict, List, Optional

from .atomic_json import atomic_write_json
from .paths import CLAUDEOPS_DIR

ORCH_DIR = os.path.join(CLAUDEOPS_DIR, "orchestration")
RUNS_DIR = os.path.join(ORCH_DIR, "runs")
DRAFT_JSON = os.path.join(ORCH_DIR, "draft.json")


def _atomic_write_json(path: str, obj: Any) -> None:
    atomic_write_json(path, obj, mode=0o600)


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _run_path(run_id: str) -> Optional[str]:
    # Path-traversal koruması — `run_id` her zaman `_new_run_id()`'den gelir
    # ama HTTP katmanından (query param) da okunuyor, kullanıcı girdisi kadar
    # dikkatli davran (`files.py`'nin `_resolve_within_roots`'uyla AYNI ilke).
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        return None
    return os.path.join(RUNS_DIR, f"{run_id}.json")


def save_run(run: Any) -> None:
    """`run`: `orchestration.Run` dataclass'ı YA DA zaten dict (kısmi
    güncellemeler `web_orch.py`'de dict üzerinde yapılıp buraya öyle
    geliyor). `dataclasses.asdict` iç içe dataclass'ları (Participant/
    RunResult/Outcome, listelerin İÇİNDEKİLER dahil) otomatik dict'e çevirir."""
    data = dataclasses.asdict(run) if dataclasses.is_dataclass(run) else run
    path = _run_path(data["id"])
    if path is None:
        raise ValueError(f"invalid run id: {data.get('id')!r}")
    _atomic_write_json(path, data)


def load_run(run_id: str) -> Optional[Dict[str, Any]]:
    path = _run_path(run_id)
    if path is None:
        return None
    data = _load_json(path, None)
    return data if isinstance(data, dict) else None


def list_runs(limit: int = 20) -> List[Dict[str, Any]]:
    """En yeni N run özeti — dosya adı `r<YYYYMMDD_HHMMSS>_<hex>.json`
    formatında ZAMAN-SIRALI üretildiği için (`web_orch._new_run_id`)
    ters-alfabetik sıralama = en yeniden en eskiye, ayrı bir index dosyasına
    gerek yok."""
    try:
        names = sorted(os.listdir(RUNS_DIR), reverse=True)
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for n in names:
        if not n.endswith(".json"):
            continue
        data = _load_json(os.path.join(RUNS_DIR, n), None)
        if isinstance(data, dict):
            out.append(data)
        if len(out) >= limit:
            break
    return out


def save_draft(participants: List[Dict[str, Any]]) -> None:
    _atomic_write_json(DRAFT_JSON, {"participants": participants})


def load_draft() -> List[Dict[str, Any]]:
    data = _load_json(DRAFT_JSON, {})
    p = data.get("participants") if isinstance(data, dict) else None
    return p if isinstance(p, list) else []


def run_dir(run_id: str) -> str:
    """Bu run'a özel ek dosyalar için dizin (ör. >4000 karakterlik prompt'un
    dosya-fallback'i, `web_orch._build_dispatch_prompt`). Var olduğunu
    GARANTİ ETMEZ — çağıran gerektiğinde `os.makedirs(..., exist_ok=True)`
    çağırır; burada dosya sistemine dokunulmadan sadece yol hesaplanır."""
    return os.path.join(RUNS_DIR, run_id)
