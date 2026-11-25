"""Arka plan işi tespiti (claude): oturum "boşta" görünse de bir kabuk işi / Monitor / alt ajan hâlâ çalışıyor olabilir.

İki bağımsız kanıt (23 Kas, derbent kanıtı: alt ajan KENDİ arka plan işini beklerken transkript yazmıyor, 90 sn sonra "bitti" sayılıyordu):
  1. EKRAN: alt durum satırı ("1 shell · esc to interrupt · ← 1 agent", "2 background tasks · ← 1 agent · ↓ to manage") ya da ajan satırı
     ("general-purpose waiting on 1 shell · ... · since 18:08", "waiting on its own background work · 40m").
  2. TRANSKRİPT: `run_in_background` ile başlamış, `<task-notification>` (completed/failed/killed) kaydı gelmemiş iş.
Saf işlevler: tmux/dosya erişimi yalnız `bg_active` sarmalayıcısında."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Iterable, Optional, Set

# Alt durum satırı: sayı + (background task|shell|agent) ve yönetim/kesme ipucu AYNI satırda (düzyazıdaki "2 agents" sayılmasın).
_COUNT_RE = re.compile(r"(?<![\w.])([1-9]\d*) (?:background tasks?|shells?|agents?|monitors?)\b", re.I)
_HINT_RE = re.compile(r"to manage|esc to interrupt|to view|ctrl\+b", re.I)
_WAIT_RE = re.compile(r"\bwaiting on (?:its own background work|[1-9]\d* (?:shells?|agents?|background tasks?|monitors?))", re.I)

SCREEN_TAIL_LINES = 14
TRANSCRIPT_TAIL_BYTES = 8 * 1024 * 1024
PENDING_MAX_AGE_SECONDS = 6 * 3600.0      # bildirimi hiç gelmemiş (öldürülmüş oturum vb.) işi sonsuza dek meşgul sayma

_NOTIF_ID_RE = re.compile(r"<tool-use-id>([^<]+)</tool-use-id>")
_TASK_ID_RE = re.compile(r"<task-id>([^<]+)</task-id>")
_STATUS_RE = re.compile(r"<status>([^<]+)</status>")
_RUNNING_ID_RE = re.compile(r"\bID: ([A-Za-z0-9]+)")
_DONE_STATUSES = {"completed", "failed", "killed", "cancelled", "canceled", "stopped"}


def screen_bg_count(text: str) -> int:
    """Ekrandaki arka plan işi SAYISI (alt durum satırındaki N'lerin toplamı; yalnız 'waiting on' görünürse en az 1); yoksa 0."""
    lines = (text or "").rstrip("\n").split("\n")[-SCREEN_TAIL_LINES:]
    total = 0
    waiting = False
    for ln in lines:
        if _WAIT_RE.search(ln):
            waiting = True
        if _HINT_RE.search(ln):
            total += sum(int(m.group(1)) for m in _COUNT_RE.finditer(ln))
    return max(total, 1) if (total or waiting) else 0


def screen_bg_work(text: str) -> bool:
    """capture-pane metninde (strip_ansi sonrası) arka plan işi göstergesi var mı. Yalnız son `SCREEN_TAIL_LINES` satır."""
    lines = (text or "").rstrip("\n").split("\n")[-SCREEN_TAIL_LINES:]
    for ln in lines:
        if _WAIT_RE.search(ln):
            return True
        if _COUNT_RE.search(ln) and _HINT_RE.search(ln):
            return True
    return False


def transcript_pending(lines: Iterable[str], now: Optional[float] = None) -> bool:
    """Transkript satırlarında bildirimi gelmemiş `run_in_background` işi var mı."""
    now = time.time() if now is None else now
    pending: dict = {}          # tool_use_id -> (epoch, task_id|None)
    done_use: Set[str] = set()
    done_task: Set[str] = set()
    for ln in lines:
        if "run_in_background" not in ln and "task-notification" not in ln and "ackground" not in ln and '"is_error"' not in ln:
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        ts = _epoch(o.get("timestamp"))
        c = (o.get("message") or {}).get("content")
        if isinstance(c, str):
            if "<task-notification>" in c:
                st = _STATUS_RE.search(c)
                if st and st.group(1).strip().lower() in _DONE_STATUSES:
                    for m in _NOTIF_ID_RE.finditer(c):
                        done_use.add(m.group(1))
                    for m in _TASK_ID_RE.finditer(c):
                        done_task.add(m.group(1))
            continue
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and (b.get("input") or {}).get("run_in_background") is True and b.get("id"):
                pending[b["id"]] = [ts or now, None]
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                if b.get("is_error") is True:      # çağrı reddedildi/düştü: iş hiç başlamadı, bildirim de gelmeyecek
                    del pending[b["tool_use_id"]]
                    continue
                m = _RUNNING_ID_RE.search(str(b.get("content"))[:400])
                if m:
                    pending[b["tool_use_id"]][1] = m.group(1)
    for tid, (t, task) in pending.items():
        if tid in done_use or (task and task in done_task):
            continue
        if now - t < PENDING_MAX_AGE_SECONDS:
            return True
    return False


def _epoch(v) -> Optional[float]:
    if not isinstance(v, str):
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def transcript_pending_path(path: Optional[str], now: Optional[float] = None) -> bool:
    """Dosyanın son `TRANSCRIPT_TAIL_BYTES` baytında `transcript_pending`. Okunamazsa False (bilinmiyor = bekletme)."""
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TRANSCRIPT_TAIL_BYTES))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return False
    return transcript_pending(data.split("\n"), now)


_CODEX_BG_RE = re.compile(r"(?<![\w.])([1-9]\d*) background terminals? running", re.I)


def codex_screen_count(text: str) -> int:
    """codex 0.166 alt durum satırı: `N background terminal(s) running · /ps to view · /stop to close` (canlı ölçüldü, docs/bg-work-measurement.md)."""
    lines = (text or "").rstrip("\n").split("\n")[-SCREEN_TAIL_LINES:]
    return sum(int(m.group(1)) for ln in lines for m in _CODEX_BG_RE.finditer(ln))


def codex_subagents_pending(lines: Iterable[str], now: Optional[float] = None) -> int:
    """codex rollout: `item_completed` `SubAgentActivity` `kind:"started"` olup aynı `agent_thread_id` için `completed` gelmemiş ajan sayısı.
    Ekranda alt ajan işareti YOK (ölçüldü): tek kanıt dosyadır. `PENDING_MAX_AGE_SECONDS`ten eski başlangıç sayılmaz."""
    now = time.time() if now is None else now
    started: dict = {}
    done: Set[str] = set()
    for ln in lines:
        if "SubAgentActivity" not in ln:
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        it = (o.get("payload") or {}).get("item") or {}
        if it.get("type") != "SubAgentActivity" or not it.get("agent_thread_id"):
            continue
        aid = str(it["agent_thread_id"])
        if it.get("kind") == "started":
            started[aid] = _epoch(o.get("timestamp")) or now
        elif it.get("kind") in ("completed", "failed", "cancelled", "canceled", "closed"):
            done.add(aid)
    return sum(1 for a, t in started.items() if a not in done and now - t < PENDING_MAX_AGE_SECONDS)


def tail_lines(path: Optional[str]) -> list:
    """Dosyanın son `TRANSCRIPT_TAIL_BYTES` baytının satırları; okunamazsa []."""
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TRANSCRIPT_TAIL_BYTES))
            return f.read().decode("utf-8", "replace").split("\n")
    except OSError:
        return []
