"""Arka plan işi tespiti (claude): oturum "boşta" görünse de bir kabuk işi / Monitor / alt ajan hâlâ çalışıyor olabilir.

Bağımsız kanıtlar (23 Kas, derbent kanıtı: alt ajan KENDİ arka plan işini beklerken transkript yazmıyor, 90 sn sonra "bitti" sayılıyordu):
  1. EKRAN: alt durum satırı ("1 shell · esc to interrupt", "2 background tasks · ↓ to manage"; "← N agent" sayılmaz) ya da ajan satırı
     ("general-purpose waiting on 1 shell · ... · since 18:08", "waiting on its own background work · 40m").
  2. TRANSKRİPT: `run_in_background` ile başlamış, `<task-notification>` (completed/failed/killed) kaydı gelmemiş iş.
  3. SÜREÇ KAYDI: claude'un `sessions/<pid>.json` `status` alanı `busy` / `shell` / `idle` (`session_record_status`).
Ayrıştırma işlevleri saftır; dosya erişimi `*_path`, `tail_lines` ve `session_record_status`tadır."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Iterable, Optional, Set

from .paths import _read_session_record
from . import jsonbound as _jsonbound

# Alt durum satırı: sayı + (background task|shell|agent) ve yönetim/kesme ipucu AYNI satırda (düzyazıdaki "2 agents" sayılmasın).
_COUNT_RE = re.compile(r"(?<![\w.])([1-9]\d*) (?:background tasks?|shells?|agents?|monitors?)\b", re.I)
_HINT_RE = re.compile(r"to manage|esc to interrupt|to view|ctrl\+b", re.I)
_WAIT_RE = re.compile(r"\bwaiting on (?:its own background work|[1-9]\d* (?:shells?|agents?|background tasks?|monitors?))", re.I)
_NAV_RE = re.compile(r"←\s*\d+ agents?\b", re.I)       # alt satırdaki ajan görünümü ipucu: boş oturumlarda da var, iş sayısı değil
_RECORD_TYPES = (None, "assistant", "user")      # araç çağrısı yalnız ileti kaydından; `api-request-blob` isteğin kopyasıdır

SCREEN_TAIL_LINES = 14
TRANSCRIPT_TAIL_BYTES = 8 * 1024 * 1024
PENDING_MAX_AGE_SECONDS = 6 * 3600.0      # bildirimi hiç gelmemiş (öldürülmüş oturum vb.) işi sonsuza dek meşgul sayma

_NOTIF_ID_RE = re.compile(r"<tool-use-id>([^<]+)</tool-use-id>")
_TASK_ID_RE = re.compile(r"<task-id>([^<]+)</task-id>")
_STATUS_RE = re.compile(r"<status>([^<]+)</status>")
_RUNNING_ID_RE = re.compile(r"\bID: ([A-Za-z0-9]+)")
_DONE_STATUSES = {"completed", "failed", "killed", "cancelled", "canceled", "stopped"}
_STOP_TOOLS = {"TaskStop", "KillShell"}      # elle durdurulan iş için `<task-notification>` GELMEZ
_LINE_MARKS = ("run_in_background", "task-notification", "ackground", '"is_error"', "TaskStop", "KillShell", "Successfully")


def screen_bg_count(text: str) -> int:
    """Ekrandaki arka plan işi SAYISI (alt durum satırındaki N'lerin toplamı; yalnız 'waiting on' görünürse en az 1); yoksa 0."""
    lines = (text or "").rstrip("\n").split("\n")[-SCREEN_TAIL_LINES:]
    total = 0
    waiting = False
    for ln in lines:
        if _WAIT_RE.search(ln):
            waiting = True
        if _HINT_RE.search(ln):
            total += sum(int(m.group(1)) for m in _COUNT_RE.finditer(_NAV_RE.sub("", ln)))
    return max(total, 1) if (total or waiting) else 0


def screen_bg_work(text: str) -> bool:
    """capture-pane metninde (strip_ansi sonrası) arka plan işi göstergesi var mı. Yalnız son `SCREEN_TAIL_LINES` satır."""
    lines = (text or "").rstrip("\n").split("\n")[-SCREEN_TAIL_LINES:]
    for ln in lines:
        if _WAIT_RE.search(ln):
            return True
        if _COUNT_RE.search(_NAV_RE.sub("", ln)) and _HINT_RE.search(ln):
            return True
    return False


def _notification_text(o: dict) -> str:
    """Kayıttaki iş bildirimi metni ("" = yok). Boşta gelen bildirim `user` metni; tur ortasında gelen `queue-operation` ya da
    `attachment` (`commandMode=task-notification`) kaydıdır. Kuyruktaki kullanıcı yazısı bildirimi alıntılarsa sayılmaz."""
    if o.get("type") == "queue-operation":
        c = o.get("content")
        return c if isinstance(c, str) and c.startswith("<task-notification>") else ""
    a = o.get("attachment")
    if isinstance(a, dict):
        c = a.get("prompt")
        return c if a.get("commandMode") == "task-notification" and isinstance(c, str) else ""
    c = (o.get("message") or {}).get("content")
    return c if isinstance(c, str) and "<task-notification>" in c else ""


def transcript_pending(lines: Iterable[str], now: Optional[float] = None) -> bool:
    """Transkript satırlarında bildirimi gelmemiş `run_in_background` işi var mı."""
    now = time.time() if now is None else now
    pending: dict = {}          # tool_use_id -> (epoch, task_id|None)
    done_use: Set[str] = set()
    done_task: Set[str] = set()
    stops: dict = {}            # durdurma çağrısı tool_use_id -> hedef task_id
    for ln in lines:
        if not any(m in ln for m in _LINE_MARKS):
            continue
        try:
            o = _jsonbound.loads(ln)
        except (ValueError, RecursionError):
            continue
        # Beklenmedik yapıdaki satır/blok yalnız atlanır: istisna bütün taramayı düşürüyordu.
        msg = (o.get("message") or {}) if isinstance(o, dict) else None
        if not isinstance(msg, dict):
            continue
        ts = _epoch(o.get("timestamp"))
        note = _notification_text(o)
        if note:
            st = _STATUS_RE.search(note)
            if st and st.group(1).strip().lower() in _DONE_STATUSES:
                for m in _NOTIF_ID_RE.finditer(note):
                    done_use.add(m.group(1))
                for m in _TASK_ID_RE.finditer(note):
                    done_task.add(m.group(1))
            continue
        if o.get("type") not in _RECORD_TYPES:
            continue
        c = msg.get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                inp = b.get("input")
                inp = inp if isinstance(inp, dict) else {}
                use_id, name = b.get("id"), b.get("name")
                if not use_id or not _hashable(use_id):
                    continue
                if isinstance(name, str) and name in _STOP_TOOLS:
                    stops[use_id] = str(inp.get("task_id") or inp.get("shell_id") or "")
                elif inp.get("run_in_background") is True:
                    pending[use_id] = [ts or now, None]
            elif b.get("type") == "tool_result" and _hashable(b.get("tool_use_id")) and b.get("tool_use_id") in stops:
                target = stops.pop(b["tool_use_id"])
                if target and b.get("is_error") is not True:
                    done_task.add(target)
            elif b.get("type") == "tool_result" and _hashable(b.get("tool_use_id")) and b.get("tool_use_id") in pending:
                if b.get("is_error") is True:      # çağrı reddedildi/düştü: iş hiç başlamadı, bildirim de gelmeyecek
                    del pending[b["tool_use_id"]]
                    continue
                m = _RUNNING_ID_RE.search(_result_text(b.get("content"))[:400])
                if m:
                    pending[b["tool_use_id"]][1] = m.group(1)
    for tid, (t, task) in pending.items():
        if tid in done_use or (task and task in done_task):
            continue
        if now - t < PENDING_MAX_AGE_SECONDS:
            return True
    return False


def _result_text(content) -> str:
    """Araç sonucunun metni. Liste biçiminde yalnız metin blokları, gerçek satır sonlarıyla (`str(liste)` satır sonunu
    `\\n` yazdığı için satır başındaki `ID:` yakalanmıyordu); diğer biçimlerde `str`."""
    if isinstance(content, list):
        return "\n".join(b["text"] for b in content
                         if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    return str(content)


def _hashable(v) -> bool:
    """JSON değeri küme/sözlük anahtarı olabilir mi (liste ve nesne olamaz)."""
    return not isinstance(v, (list, dict))


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


def session_record_status(sessions_dir: str, sid: Optional[str]) -> Optional[str]:
    """claude'un süreç kaydının (`<pid>.json`) bu konuşma için bildirdiği durum: `busy` (tur ya da devredilen ajan), `shell`
    (tur bitti, kabuk/Monitor açık), `idle` (açık iş yok). Aynı konuşmanın birden çok canlı kaydında `busy`/`shell` kazanır,
    sonra tanınmayan durum (ör. `waiting`). Canlı kayıt yoksa, pid yeniden kullanılmışsa ya da kayıt okunamıyorsa None."""
    if not sid:
        return None
    try:
        names = os.listdir(sessions_dir)
    except OSError:
        return None
    found: Set[str] = set()
    for n in names:
        if not n.endswith(".json"):
            continue
        path = os.path.join(sessions_dir, n)
        try:
            d = _jsonbound.loads(_read_session_record(path))
            if d.get("sessionId") != sid:
                continue
            with open(f"/proc/{int(d['pid'])}/stat", encoding="utf-8", errors="replace") as f:
                started = f.read().rsplit(")", 1)[1].split()[19]
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, RecursionError):
            continue
        if str(d.get("procStart")) == started:
            found.add(str(d.get("status") or ""))
    for st in ("busy", "shell"):
        if st in found:
            return st
    other = sorted(found - {"idle"})
    if other:
        return other[0]
    return "idle" if found else None


SHELL_ONLY_DIRECTIVE_SECONDS = 1800     # TBD#442 (a): tur bitmiş, yalnız kabuk/Monitor bu kadar süredir açık = yönerge yine gider


def session_record_shell_since(sessions_dir: str, sid: Optional[str]) -> Optional[float]:
    """Konuşmanın canlı süreç kayıtlarının birleşik durumu `shell` ise (`session_record_status`: tur bitti, yalnız kabuk/Monitor açık)
    o duruma geçiş anı (epoch sn; birden çok kayıtta en yenisi, `statusUpdatedAt` ms). Başka durum, kayıt yok ya da zaman okunamıyorsa None."""
    if session_record_status(sessions_dir, sid) != "shell":
        return None
    try:
        names = os.listdir(sessions_dir)
    except OSError:
        return None
    best: Optional[float] = None
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(sessions_dir, n), encoding="utf-8") as f:
                d = json.load(f)
            if d.get("sessionId") != sid or d.get("status") != "shell":
                continue
            t = float(d["statusUpdatedAt"]) / 1000.0
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
            continue
        if t == t and t > 0 and (best is None or t > best):
            best = t
    return best


def shell_only_stale(sessions_dir: str, sid: Optional[str], now: Optional[float] = None) -> bool:
    """TBD#442 (a): claude turu bitmiş ve `SHELL_ONLY_DIRECTIVE_SECONDS`ten uzun süredir yalnız kabuk/Monitor açık. Yönerge, dürtü ve
    cevap teslimi bunu engel saymaz; devir, kapatma, yeniden açma yine bekler (kabuk öldürülmez). Bilinmiyorsa False."""
    since = session_record_shell_since(sessions_dir, sid)
    t = time.time() if now is None else now
    return since is not None and (t - since) >= SHELL_ONLY_DIRECTIVE_SECONDS


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
            o = _jsonbound.loads(ln)
        except (ValueError, RecursionError):
            continue
        payload = (o.get("payload") or {}) if isinstance(o, dict) else None
        it = (payload.get("item") or {}) if isinstance(payload, dict) else None
        if not isinstance(it, dict):
            continue
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
