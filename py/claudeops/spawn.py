"""Session spawn — gnome-terminal + bir CLI provider (claude, agy, ...).

Bash spawn pattern'inin yerine:
  gnome-terminal -- bash -c "cd CWD && <cli> ... < /dev/null; exec bash"
  < /dev/null zorunlu (stdin/pty reject olmaz).
  DISPLAY env değişkeni gerekli (headless cron'da otomatik tespit).

Hangi CLI'ın nasıl başlatılacağı (komut satırı, resume-lookup, isimlendirme env'i)
TAMAMEN `providers/` paketinde — burada `cli` string'ine göre dallanma YOK, sadece
`get_provider(cli)` ile arayüz üzerinden çağrı var.
"""
from __future__ import annotations
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from .diaglog import diag_log
from .providers import get_provider
from .providers.claude_provider import find_latest_jsonl  # geriye-uyum: diğer modüller import ediyor
from .tmux_backend import tmux_available, tmux_has_session, tmux_new_session_shell_fragment, tmux_spawn_direct

# gnome-terminal-server sessizce pencere açamadığında ([[spawn-zombie-child-degrades-web-server]],
# kendi D-Bus/uzun-yaşam state bozulması — spawn'a özel değil, bare `gnome-terminal`
# CLI'da bile canlı tekrarlandı 2026-08-27) bu kadar bekleyip tmux session hâlâ
# yoksa gnome-terminal'siz DOĞRUDAN tmux'a düş. Normal (sağlıklı) durumda session
# çoktan bundan önce görünür — fallback'in gerçekten TETİKLENMESİ nadir olmalı.
FALLBACK_WAIT_SECONDS = 6.0


def detect_display() -> str:
    """DISPLAY'i tespit et: env → :1 → :0 sırasıyla."""
    env = os.environ.get("DISPLAY", "")
    if env:
        return env
    for d in (":1", ":0"):
        if Path(f"/tmp/.X{d[1:]}-lock").exists():
            return d
    return ":1"


def spawn_session(
    name: str,
    cwd: str,
    model: str,
    display: Optional[str] = None,
    permission_mode: str = "auto",
    effort: str = "max",
    force_new: bool = False,
    prompt: Optional[str] = None,
    dry_run: bool = False,
    cli: str = "claude",
) -> str:
    """Session'ı gnome-terminal ile aç (hangi CLI: `cli` — provider registry'den çözülür).

    force_new=True → fresh/new (konuşma sıfırdan).
    force_new=False → provider'ın kendi resume-lookup'ı (claude: jsonl, agy:
    conversations-cache), yoksa fresh.
    prompt → fresh açılışta opsiyonel ilk mesaj (verilmezse boş/idle başlar).

    Returns: "resume:<id[:8]>", "new", veya "[dry-run] ..." dry_run modunda.
    """
    provider = get_provider(cli)

    if display is None:
        display = detect_display()

    resume_id = None if force_new else provider.resolve_resume_id(cwd)
    kind = "new" if resume_id is None else f"resume:{resume_id[:8]}"

    cli_invocation = provider.build_inner_command(cwd, model, permission_mode, effort,
                                                   resume_id, prompt, name)

    # env_overrides (ör. agy'nin COPS_NAME'i) Popen'ın env dict'ine DEĞİL, komut
    # satırının kendisine `env KEY=VAL ... <binary>` olarak gömülüyor — tmux zaten
    # çalışan bir server'da yeni session açarken kendi `update-environment`
    # varsayılan listesi (DISPLAY, SSH_AUTH_SOCK, ...) DIŞINDAKİ her şeyi
    # SESSİZCE YOK SAYIYOR (canlı doğrulandı: Popen env'ine COPS_NAME koymak
    # tmux-backed agy session'ında proc'a hiç ulaşmadı). Komut satırına `env` ile
    # gömmek bu env-inheritance tuhaflığını tamamen atlar.
    overrides = provider.env_overrides(name)
    env_prefix = "".join(f"{k}={shlex.quote(v)} " for k, v in overrides.items())
    inner = f"cd {shlex.quote(cwd)} && {env_prefix}{cli_invocation}"

    if dry_run:
        return f"[dry-run] {kind}  cmd: {inner[:80]}..."

    # CLAUDE*/GEMINI*/ANTIGRAVITY*-prefixed env (CLAUDECODE, CLAUDE_CODE_SESSION_ID,
    # CLAUDE_CODE_CHILD_SESSION, messaging socket/token, pinned EXECPATH,
    # CLAUDE_EFFORT/PID...) is THIS process's own session identity. Spawned fleet
    # sessions are independent top-level sessions, not children — inheriting it
    # makes claude/agy think it's a child session and DISABLE TRANSCRIPT SAVING
    # ("Transcript saving is off — inherited CLAUDE_CODE_CHILD_SESSION marker",
    # found 2026-08-24 spawning from within a claude-run Bash tool/py-cops-web).
    # Stripped unconditionally (not just for the CLI being launched) since the
    # contamination source is the CALLING process's env, not the target CLI.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GEMINI", "ANTIGRAVITY"))}
    env["DISPLAY"] = display

    # tmux-backed going forward (spawn is the ONLY launch path, so the tmux server —
    # whenever/wherever first bootstrapped — always inherits this already-scrubbed
    # env for its whole lifetime; no separate scrubbing needed). If tmux isn't
    # installed, degrade silently to today's exact plain-bash spawn — a missing
    # optional binary must never fail the spawn itself.
    if tmux_available():
        window_cmd = f"{tmux_new_session_shell_fragment(name, cwd, inner)}; exec bash"
    else:
        window_cmd = f"{inner}; exec bash"

    proc = subprocess.Popen(
        ["gnome-terminal", "--window", f"--title={name}",
         f"--working-directory={cwd}",
         "--", "bash", "-c", window_cmd],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # gnome-terminal client proc'u pencereyi server'a bildirip hemen çıkar (fire-and-forget).
    # .wait() hiç çağrılmazsa zombie olarak kalır — uzun yaşayan web server'da (py/cops web)
    # her spawn'da bir tane birikir; 2026-08-25'te saatlerce ayakta kalmış bir web server'da
    # bu birikim yeni pencere açma güvenilirliğini SESSİZCE düşürdüğü canlı olarak doğrulandı
    # (taze restart edilen AYNI process anında düzeliyordu). Global SIGCHLD=SIG_IGN YAPMA —
    # layout.py'nin subprocess.run(wmctrl/xdotool) çağrılarının exit code/output'unu bozar;
    # bunun yerine sadece BU child'ı arka planda reap et.
    threading.Thread(target=proc.wait, daemon=True).start()

    if tmux_available():
        # spawn_session() kendisi hâlâ ANINDA döner (guard_lock hold süresini UZATMAZ,
        # web.py'de zaten spawn_session sonrası AYRI bir _wait_stable bekleme adımı var).
        # AMA bu thread daemon=FALSE OLMALI: rc.py/handover.py/stuck.py gibi kısa-ömürlü
        # CLI çağıranlar spawn_session() döner dönmez döngüdeki sıradaki isme geçip
        # saniyeler içinde process'i TAMAMEN kapatıyor — daemon=True olsaydı interpreter
        # çıkışında thread ANINDA öldürülür, fallback HİÇ TETİKLENMEZ (canlı test 2026-08-27:
        # kısa ömürlü bir python3 -c script'inde tam bunu doğruladım). daemon=False →
        # Python, ana thread bitse bile TÜM non-daemon thread'ler tamamlanana kadar
        # process'i canlı tutar — worst-case ek gecikim ~FALLBACK_WAIT_SECONDS + tmux
        # timeout'u (sınırlı, asla hang etmez), py/cops web gibi zaten uzun-yaşayan
        # çağıranlarda hiç fark edilmez.
        threading.Thread(target=_fallback_watchdog, args=(name, cwd, inner, env),
                          daemon=False).start()
    return kind


def _fallback_watchdog(name: str, cwd: str, inner: str, env: dict) -> None:
    deadline = time.monotonic() + FALLBACK_WAIT_SECONDS
    while time.monotonic() < deadline:
        if tmux_has_session(name):
            return  # gnome-terminal (ya da daha önceki bir çağrı) başardı, fallback gereksiz
        time.sleep(0.5)
    if tmux_has_session(name):
        return
    ok = tmux_spawn_direct(name, cwd, inner, env)
    diag_log("spawn_fallback_used", name=name, cwd=cwd, ok=ok)
