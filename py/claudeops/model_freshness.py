"""Claude model listesi tazeleme — günde bir / servis her başladığında.

[[kullanıcı 2026-10-01]]: `providers/claude_provider.py`nin `MODEL_CHOICES`'ı
elle güncellenen statik bir liste; agy/codex/ucli zaten canlı sorguluyor
(bkz. o dosyalar) ama `claude` CLI'si "mevcut modeller" döndüren bir
API/bayrak sunmuyor. Tek CANLI kaynak: HER Claude Code session'ının system
prompt'unda taze gelen "Model IDs" satırı — ucuz bir `claude -p --model
<haiku>` self-report'uyla okunuyor (panelde GÖRÜNMEZ, fleet'e hiç spawn
edilmiyor, `instances.json`/roster'a dokunmuyor).

BİLEREK basit tutuldu (kullanıcı: "basit bişi... dosyaya kaydet"): koda
DOKUNMAZ, commit/push ATMAZ — `roster.tsv`/`models.tsv` ile AYNI "repo DIŞI
state" deseni, sadece `CLAUDE_MODELS_JSON`'a yazar (`atomic_json` ile).
Artık görülmeyen modeller SİLİNMEZ, `disabled` işaretlenir (historic kayıt
kalır); şu an görülenler `enabled` (yeni session'lar için seçenek).
`claude_provider.model_choices()` bu dosyayı okur, yoksa/boşsa sessizce
hardcoded `MODEL_CHOICES`'a düşer — ilk kurulumda ya da bu modül hiç
çalışmadıysa panel ASLA boş seçenek listesiyle kalmaz.

Tetik: `web.py::run()`'da (`web_ws.start_broadcaster` ile aynı yerden, aynı
desen) başlatılan bir arka plan thread'i — saatte bir uyanır (ucuz: tek
dosya okuma), ama pahalı iş (gerçek `claude -p` çağrısı) sadece
`MIN_HOURS_BETWEEN_CHECKS` gerçekten dolmuşsa tetiklenir. İlk uyanış
`run()` başlar başlamaz olur (= "başlarken"), ayrı bir cron/systemd-timer
gerekmiyor.
"""
from __future__ import annotations
import datetime
import json
import re
import subprocess
import threading
import time
from typing import Optional

from .atomic_json import atomic_write_json
from .diaglog import diag_log
from .paths import CLAUDE_MODELS_JSON, REPO_DIR

_WAKE_INTERVAL_SECONDS = 3600
MIN_HOURS_BETWEEN_CHECKS = 24

_CHECK_PROMPT = (
    "List the current Claude model IDs you were given in your system prompt "
    "(the 'Model IDs' line under Environment), as compact JSON only, no prose. "
    'Format: {"sonnet":"...","opus":"...","haiku":"...","fable":"..."}. '
    "If you don't have such a line, output {}."
)

# live[key]'nin kabul edilmesi için başlaması GEREKEN önek — bozuk/hallüsine
# bir yanıtın state dosyasına rastgele bir id yazmasını engeller.
_EXPECTED_PREFIX = {
    "sonnet": "claude-sonnet-",
    "opus": "claude-opus-",
    "haiku": "claude-haiku-",
    "fable": "claude-fable-",
}


def _read_state() -> dict:
    try:
        with open(CLAUDE_MODELS_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _is_due(state: dict) -> bool:
    last = state.get("checked_at")
    if not last:
        return True
    try:
        last_dt = datetime.datetime.fromisoformat(last)
    except Exception:
        return True
    return (datetime.datetime.now() - last_dt) >= datetime.timedelta(hours=MIN_HOURS_BETWEEN_CHECKS)


def _fetch_live_models() -> Optional[dict]:
    """Ucuz/tek-seferlik `claude -p` çağrısı — fleet'e hiç görünmez."""
    try:
        out = subprocess.run(
            ["claude", "-p", _CHECK_PROMPT, "--model", "claude-haiku-4-5-20251001"],
            capture_output=True, text=True, timeout=90, cwd=REPO_DIR,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    m = re.search(r"\{.*\}", out.stdout.strip(), re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    return data if isinstance(data, dict) and data else None


def _run_check_once() -> None:
    live = _fetch_live_models()
    if not live:
        diag_log("model_check_fetch_failed")
        return  # checked_at GÜNCELLENMEZ — bir sonraki uyanışta (≤1s içinde) tekrar dener

    live_ids = set()
    for key, prefix in _EXPECTED_PREFIX.items():
        mid = live.get(key)
        if isinstance(mid, str) and mid.startswith(prefix):
            live_ids.add(mid)
    if not live_ids:
        diag_log("model_check_empty_response", raw=live)
        return

    prev_models = _read_state().get("models", {})
    all_ids = set(prev_models.keys()) | live_ids
    models = {mid: ("enabled" if mid in live_ids else "disabled") for mid in sorted(all_ids)}

    prev_enabled = {m for m, s in prev_models.items() if s == "enabled"}
    newly_enabled = live_ids - prev_enabled
    newly_disabled = prev_enabled - live_ids
    if newly_enabled or newly_disabled:
        diag_log("model_list_changed", enabled=sorted(newly_enabled), disabled=sorted(newly_disabled))

    atomic_write_json(CLAUDE_MODELS_JSON, {
        "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "models": models,
    })


def _loop() -> None:
    while True:
        try:
            if _is_due(_read_state()):
                _run_check_once()
        except Exception:
            pass  # web_hosts._poller_loop ile AYNI disiplin — tek kötü tur daemon'ı öldürmesin
        time.sleep(_WAKE_INTERVAL_SECONDS)


_lock = threading.Lock()
_started = False


def start_daily_check() -> None:
    """`run()`'dan BİR KEZ çağrılır (`web_ws.start_broadcaster`/
    `web_hosts.start_remote_poller` ile aynı yerden, aynı desen). İkinci
    çağrı no-op."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, daemon=True, name="model-freshness").start()
