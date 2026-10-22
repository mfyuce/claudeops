"""Son N dakikanın model bazlı token kullanımı (claude transkriptlerinden; YALNIZ izleme, hiçbir karara bağlanmaz).

Ana oturumlar ve alt ajanlar (`<oturum>/subagents/agent-*.jsonl`) dahil `~/.claude/projects/**.jsonl` taranır; dosyalar
sondan okunur (pencere dışına çıkınca durur), bu yüzden dev transkriptler de ucuz. Sonuç 60 sn önbellekli ve ARKA PLAN
iş parçacığında yenilenir: `/api/status` hiç beklemez, ilk çağrıda `None` döner (UI gizler). Asla fırlatmaz."""

import glob
import json
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
WINDOW_MINUTES = 60
CACHE_SECONDS = 60
_BLOCK = 1 << 20          # 1 MiB'lık bloklarla sondan oku
_FAMILIES = ("fable", "opus", "sonnet", "haiku")

_lock = threading.Lock()
_state: Dict[str, Any] = {"at": 0.0, "value": None, "running": False}


def _family(model: str) -> str:
    m = (model or "").lower()
    for f in _FAMILIES:
        if f in m:
            return f
    return "other"


def _iter_recent_lines(path: str, cutoff: float):
    """Dosyayı sondan blok blok okur; satırları (yeniden eskiye) verir. Bir satırın zaman damgası `cutoff`ten eskiyse durur."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        carry = b""
        while pos > 0:
            step = min(_BLOCK, pos)
            pos -= step
            f.seek(pos)
            chunk = f.read(step) + carry
            parts = chunk.split(b"\n")
            carry = parts[0] if pos > 0 else b""
            lines = parts[1:] if pos > 0 else parts
            for raw in reversed(lines):
                if not raw.strip():
                    continue
                yield raw
            # En eski satırın zaman damgası pencere dışındaysa dur (bir sonraki blok daha da eski).
            if lines:
                try:
                    ts = json.loads(lines[0]).get("timestamp")
                    if ts and datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() < cutoff:
                        return
                except (ValueError, TypeError):
                    pass


def _sub_effort(path: str) -> str:
    """Alt ajan transkriptinin yanındaki `.meta.json`dan effort ("" = kayıtlı değil). Ana oturumda effort transkriptte YOK."""
    try:
        with open(path[:-len(".jsonl")] + ".meta.json", encoding="utf-8") as f:
            return str((json.load(f) or {}).get("effort") or "").lower()
    except (OSError, ValueError, AttributeError):
        return ""


def scan(minutes: int = WINDOW_MINUTES, now: Optional[float] = None) -> Dict[str, Any]:
    """{window_minutes, families: {fam: {calls, fresh, read, out}}, fable_top: [{label, calls, fresh, read}], efforts: {"fam/effort": {...}}, fable_agents: N} (token sayıları)."""
    now = now or time.time()
    cutoff = now - minutes * 60
    fam: Dict[str, Dict[str, int]] = {}
    fable: Dict[str, Dict[str, Any]] = {}
    efforts: Dict[str, Dict[str, int]] = {}      # "<aile>/<effort>" → sayaçlar (yalnız effort'u bilinen alt ajanlar)
    fable_agents: set = set()                    # penceredeki Fable alt ajan transkriptleri ("en çok 1 Fable ajanı" denetimi)
    for path in glob.glob(os.path.join(PROJECTS_DIR, "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(path) < cutoff:
                continue
            is_sub = "/subagents/" in path
            proj = os.path.relpath(path, PROJECTS_DIR).split(os.sep)[0]
            effort = _sub_effort(path) if is_sub else ""
            turns: Dict[Any, list] = {}
            for raw in _iter_recent_lines(path, cutoff):
                if b'"usage"' not in raw:
                    continue
                try:
                    r = json.loads(raw)
                except ValueError:
                    continue
                m = r.get("message") or {}
                u = m.get("usage")
                if r.get("type") != "assistant" or not isinstance(u, dict):
                    continue
                try:
                    ts = datetime.fromisoformat(str(r.get("timestamp", "")).replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                f = _family(m.get("model", ""))
                if f == "other" and not m.get("model"):
                    continue
                fresh = int(u.get("input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0))
                read = int(u.get("cache_read_input_tokens", 0))
                out = int(u.get("output_tokens", 0))
                # Aynı API cevabı içerik bloğu başına birden çok satıra bölünür (aynı message.id + requestId): tur başına bir kez say,
                # tekrarlarda alan başına en büyük değer (session_usage ile aynı kural). Kimliksiz satır tek başına sayılır.
                mid = m.get("id")
                key = (mid, r.get("requestId")) if mid else ("row", len(turns))
                prev = turns.get(key)
                if prev:
                    prev[1], prev[2], prev[3] = max(prev[1], fresh), max(prev[2], read), max(prev[3], out)
                else:
                    turns[key] = [f, fresh, read, out]
            for f, fresh, read, out in turns.values():
                a = fam.setdefault(f, {"calls": 0, "fresh": 0, "read": 0, "out": 0})
                a["calls"] += 1
                a["fresh"] += fresh
                a["read"] += read
                a["out"] += out
                if effort:
                    e = efforts.setdefault(f"{f}/{effort}", {"calls": 0, "fresh": 0, "read": 0})
                    e["calls"] += 1
                    e["fresh"] += fresh
                    e["read"] += read
                if f == "fable" and is_sub:
                    fable_agents.add(path)
                if f == "fable":
                    label = proj.replace("-home-fatihyuce-work-", "").replace("academic-yeterlilik2-belge-backups-", "")[-34:]
                    label += " (alt ajan)" if is_sub else ""
                    b = fable.setdefault(label, {"label": label, "calls": 0, "fresh": 0, "read": 0})
                    b["calls"] += 1
                    b["fresh"] += fresh
                    b["read"] += read
        except OSError:
            continue
    top = sorted(fable.values(), key=lambda x: -(x["read"] + 12 * x["fresh"]))[:5]
    return {"window_minutes": minutes, "at": now, "families": fam, "fable_top": top,
            "efforts": efforts, "fable_agents": len(fable_agents)}


def _refresh() -> None:
    try:
        value = scan()
    except Exception:
        value = None
    with _lock:
        _state["value"], _state["at"], _state["running"] = value, time.time(), False


def summary() -> Optional[Dict[str, Any]]:
    """Önbellekteki özet; bayatsa arka planda yenilemeyi başlatır ve eskiyi (ya da ilk seferde None) hemen döner."""
    with _lock:
        stale = time.time() - _state["at"] >= CACHE_SECONDS
        if stale and not _state["running"]:
            _state["running"] = True
            threading.Thread(target=_refresh, name="model-usage", daemon=True).start()
        return _state["value"]
