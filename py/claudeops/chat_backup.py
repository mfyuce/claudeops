"""Sohbet ayna yedeği: durum + systemd user timer kurulumu (sahip kararı 19 Kas, TBD#223b). Yaprak modül.

Betik `~/.claude/claudeops/backups/chat_mirror.sh` (rsync, --delete YOK). Cron yerine `claudeops-chat-mirror.{service,timer}`
(günlük 03:17). Elle adım gerekirse `manual_command` tek satırlık komutu verir."""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List

HOME = os.path.expanduser("~")
SCRIPT = os.path.join(HOME, ".claude", "claudeops", "backups", "chat_mirror.sh")
DEST = os.path.join(HOME, ".claude", "claudeops", "backups", "chat-mirror")
UNIT_DIR = os.path.join(HOME, ".config", "systemd", "user")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
UNIT = "claudeops-chat-mirror"

SERVICE = f"""[Unit]
Description=claudeops sohbet ayna yedegi (rsync, silme yok)

[Service]
Type=oneshot
ExecStart=/bin/bash {SCRIPT}
Nice=15
IOSchedulingClass=idle
"""
TIMER = f"""[Unit]
Description=claudeops sohbet ayna yedegi (gunluk)

[Timer]
OnCalendar=*-*-* 03:17:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
"""


def _sysctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=30)


def _last_log() -> Dict[str, str]:
    try:
        with open(os.path.join(DEST, "mirror.log"), encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()[-200:]
    except OSError:
        return {"last_done": "", "last_line": ""}
    done = [ln for ln in lines if " done " in ln]
    return {"last_done": done[-1] if done else "", "last_line": lines[-1] if lines else ""}


def _retention() -> Any:
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f).get("cleanupPeriodDays")
    except (OSError, ValueError):
        return None


def manual_command() -> str:
    return (f"mkdir -p ~/.config/systemd/user && cp {UNIT_DIR}/{UNIT}.* ~/.config/systemd/user/ 2>/dev/null; "
            f"systemctl --user daemon-reload && systemctl --user enable --now {UNIT}.timer")


def status() -> Dict[str, Any]:
    en = _sysctl("is-enabled", UNIT + ".timer").stdout.strip() if os.path.exists(os.path.join(UNIT_DIR, UNIT + ".timer")) else "not-installed"
    act = _sysctl("is-active", UNIT + ".timer").stdout.strip() if en != "not-installed" else "inactive"
    out: Dict[str, Any] = {"script_exists": os.path.isfile(SCRIPT), "dest": DEST, "cleanup_period_days": _retention(),
                           "timer_enabled": en, "timer_active": act, "installed": en not in ("not-installed", ""),
                           "manual_command": manual_command()}
    out.update(_last_log())
    return out


def install() -> Dict[str, Any]:
    """Birimleri yazar, timer'ı etkinleştirir. Başarısızlıkta hata + `manual_command` (sahip elle çalıştırır)."""
    from . import chat_sources
    chat_sources.write_mirror_script(SCRIPT)      # D1: betik kayıt yerleri listesinden üretilir (yoksa oluşur, değiştiyse yenilenir)
    os.makedirs(UNIT_DIR, exist_ok=True)
    for name, body in ((UNIT + ".service", SERVICE), (UNIT + ".timer", TIMER)):
        with open(os.path.join(UNIT_DIR, name), "w", encoding="utf-8") as f:
            f.write(body)
    errs: List[str] = []
    for args in (("daemon-reload",), ("enable", "--now", UNIT + ".timer")):
        r = _sysctl(*args)
        if r.returncode:
            errs.append((r.stderr or r.stdout).strip()[:200])
            break
    return {"ok": not errs, "error": "; ".join(errs), "manual_command": manual_command(), "status": status()}


def run_now() -> Dict[str, Any]:
    """Betiği şimdi başlatır (arka planda, bekleme yok)."""
    from . import chat_sources
    chat_sources.write_mirror_script(SCRIPT)
    subprocess.Popen(["/bin/bash", SCRIPT], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return {"ok": True}
