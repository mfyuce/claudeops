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
from .tmux_backend import (
    tmux_attach_shell_fragment, tmux_available, tmux_has_session,
    tmux_new_session_shell_fragment, tmux_spawn_direct,
)

# gnome-terminal-server sessizce pencere açamadığında ([[spawn-zombie-child-degrades-web-server]],
# kendi D-Bus/uzun-yaşam state bozulması — spawn'a özel değil, bare `gnome-terminal`
# CLI'da bile canlı tekrarlandı 2026-08-27) bir süre bekleyip tmux session hâlâ
# yoksa gnome-terminal'i BİR KAÇ KEZ DAHA dener (2026-08-28 canlı doğrulandı: reboot
# sonrası TAZE bir gnome-terminal-server'la bile TEK SEFERLİK bu şekilde başarısız
# olabiliyor — "ara sıra" flake, kalıcı bozukluk değil; bkz. TODO.md saseppr/agy
# maddesi). Retry'ların hepsi biterse ANCAK O ZAMAN gnome-terminal'siz DOĞRUDAN
# tmux'a düş. Normal (sağlıklı) durumda session ilk denemede görünür — retry/fallback
# gerçekten TETİKLENMESİ nadir olmalı. Toplam bütçe (3×4=12s + fallback) web.py'nin
# `_wait_stable(..., timeout=HANDOVER_PROC_WAIT_SECONDS=25.0)` beklemesinin İÇİNDE
# kalacak şekilde seçildi — üstüne çıkarsa kullanıcı "başlatılamadı" görür, session
# birkaç saniye sonra yine de ayağa kalkar.
FALLBACK_ATTEMPT_WAIT_SECONDS = 4.0
FALLBACK_RETRY_COUNT = 2  # ilk deneme (spawn_session'da zaten atıldı) HARİÇ ek deneme sayısı


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

    _launch_gnome_terminal(name, cwd, window_cmd, env)

    if tmux_available():
        # spawn_session() kendisi hâlâ ANINDA döner (guard_lock hold süresini UZATMAZ,
        # web.py'de zaten spawn_session sonrası AYRI bir _wait_stable bekleme adımı var).
        # AMA bu thread daemon=FALSE OLMALI: rc.py/handover.py/stuck.py gibi kısa-ömürlü
        # CLI çağıranlar spawn_session() döner dönmez döngüdeki sıradaki isme geçip
        # saniyeler içinde process'i TAMAMEN kapatıyor — daemon=True olsaydı interpreter
        # çıkışında thread ANINDA öldürülür, fallback HİÇ TETİKLENMEZ (canlı test 2026-08-27:
        # kısa ömürlü bir python3 -c script'inde tam bunu doğruladım). daemon=False →
        # Python, ana thread bitse bile TÜM non-daemon thread'ler tamamlanana kadar
        # process'i canlı tutar — worst-case ek gecikim ~(FALLBACK_RETRY_COUNT+1)×
        # FALLBACK_ATTEMPT_WAIT_SECONDS + tmux timeout'u (sınırlı, asla hang etmez),
        # py/cops web gibi zaten uzun-yaşayan çağıranlarda hiç fark edilmez.
        threading.Thread(target=_fallback_watchdog, args=(name, cwd, inner, env, window_cmd),
                          daemon=False).start()
    return kind


def _launch_gnome_terminal(name: str, cwd: str, window_cmd: str, env: dict) -> None:
    """Fire-and-forget bir `gnome-terminal --window` çağrısı — spawn_session'ın ilk
    denemesi VE `_fallback_watchdog`'un retry'ları AYNI fonksiyonu kullanır (tmux
    tarafındaki `-A` idempotency'si sayesinde retry güvenli: session zaten varsa
    yeni bir CLI proc'u başlatmaz, sadece yeni bir pencere/client bağlar)."""
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


def _fallback_watchdog(name: str, cwd: str, inner: str, env: dict, window_cmd: str) -> None:
    """İlk gnome-terminal denemesi (spawn_session'da zaten atıldı) tmux session'ı
    getirmezse, aynı komutu FALLBACK_RETRY_COUNT kez daha dener (ara sıra tek
    seferlik D-Bus flake'i çoğunlukla bir sonraki denemede geçer — 2026-08-28
    canlı doğrulandı, reboot sonrası taze bir gnome-terminal-server'da bile
    tekrarladı). Hepsi de başarısız olursa ANCAK O ZAMAN gnome-terminal'siz
    doğrudan headless tmux'a düşer."""
    for attempt in range(FALLBACK_RETRY_COUNT + 1):
        deadline = time.monotonic() + FALLBACK_ATTEMPT_WAIT_SECONDS
        while time.monotonic() < deadline:
            if tmux_has_session(name):
                if attempt > 0:
                    diag_log("spawn_retry_succeeded", name=name, cwd=cwd, attempt=attempt)
                return  # gnome-terminal (bu denemede ya da önceki bir çağrıda) başardı
            time.sleep(0.5)
        if attempt < FALLBACK_RETRY_COUNT:
            diag_log("spawn_retry", name=name, cwd=cwd, attempt=attempt + 1)
            _launch_gnome_terminal(name, cwd, window_cmd, env)
    if tmux_has_session(name):
        return
    ok = tmux_spawn_direct(name, cwd, inner, env)
    diag_log("spawn_fallback_used", name=name, cwd=cwd, ok=ok)


def open_window(name: str, cwd: str, display: Optional[str] = None) -> bool:
    """Var olan (headless/windowless) bir tmux-backed session'a YENİ bir
    gnome-terminal penceresi bağla — CLI'ı yeniden başlatmadan, dup riski olmadan.
    `saseppr20260828_2` gibi sessiz-fallback sonrası kullanıcının tek tıkla telafi
    etmesi için (2026-08-28). Session yoksa False döner — çağıran önce
    `tmux_has_session`/`is_tmux_backed` ile doğrulamış olmalı."""
    if not tmux_has_session(name):
        return False
    if display is None:
        display = detect_display()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GEMINI", "ANTIGRAVITY"))}
    env["DISPLAY"] = display
    window_cmd = f"{tmux_attach_shell_fragment(name)}; exec bash"
    _launch_gnome_terminal(name, cwd, window_cmd, env)
    return True
