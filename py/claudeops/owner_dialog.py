"""Claude transkriptinden "sahip diyaloğu açık mı" ve "kullanıcı en son ne zaman cevap verdi" (SAF).

Açık diyalog = cevabı (`tool_result`) gelmemiş `AskUserQuestion` / `ExitPlanMode` çağrısı. O sırada oturuma tuş basılırsa mesaj
diyaloğa yazılır; oturum kapatılırsa kullanıcı konuşmanın ortasında kalır. İzin diyalogları transkriptten görünmez."""
from __future__ import annotations
import json
from datetime import datetime
from typing import Dict, Iterable, Tuple

DIALOG_TOOLS = ("AskUserQuestion", "ExitPlanMode")


def _epoch(v: object) -> float:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def owner_dialog_state(lines: Iterable[str]) -> Tuple[bool, float]:
    """(diyalog açık mı, son kullanıcı girdisi epoch'u; 0 = görülmedi). Kullanıcı girdisi: diyalog cevabı (reddi dahil) ya da
    yazılan ileti (`origin.kind == "human"`). Sonraki tur ya da yazılan ileti cevapsız kalmış eski çağrıyı kapatır. Alt ajan
    (sidechain) kayıtları sayılmaz."""
    pending: Dict[str, str] = {}        # tool_use_id -> ileti kimliği
    last = 0.0
    for ln in lines:
        try:
            o = json.loads(ln)
            kind = o.get("type")
            if kind not in ("assistant", "user") or o.get("isSidechain"):
                continue
            msg = o.get("message") or {}
            blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
            if kind == "assistant":
                mid = str(msg.get("id") or "")
                pending = {t: m for t, m in pending.items() if m == mid}
                for b in blocks:
                    if b.get("type") == "tool_use" and b.get("name") in DIALOG_TOOLS and b.get("id"):
                        pending[str(b["id"])] = mid
                continue
            for b in blocks:
                if b.get("type") == "tool_result" and pending.pop(str(b.get("tool_use_id")), None) is not None:
                    last = max(last, _epoch(o.get("timestamp")))
            if (o.get("origin") or {}).get("kind") == "human" and not o.get("isMeta"):
                pending.clear()
                last = max(last, _epoch(o.get("timestamp")))
        except (ValueError, AttributeError, TypeError):
            continue
    return bool(pending), last
