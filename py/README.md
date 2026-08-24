# claudeops — Python (`py/cops`)

*English · [Türkçe](README_TR.md)*

A small CLI + local web panel for managing multiple Claude Code sessions across multiple project
folders from one place. Each project is a "roster" entry (name → folder → model); `py/cops web` shows
that roster and lets you start/stop entries one at a time.

Requires Linux + X11 (depends on `gnome-terminal`) — WSL/headless/macOS/Windows are not supported.

## Install

```bash
git clone https://github.com/mfyuce/claudeops.git
cd claudeops
pip install -r py/requirements.txt   # single dependency: psutil
```

Python 3.10+. The `claude` CLI must be installed and on PATH.

## Quick start

```bash
py/cops list          # show currently running sessions
py/cops web            # control panel → http://127.0.0.1:8765
py/cops web --tunnel   # + access from your phone/remotely (cloudflared, auto-installed on first run)
```

## `py/cops web` — the control panel

The easiest way to use this; everything from the browser:

![claudeops web panel](../docs/web-panel.png)

- **Main page** — only **running** sessions (no noise; nothing starts automatically).
- **+ Add** — lists registered-but-stopped projects; pick one and start it with **resume** /
  **reset (--new)** / **start a separate new chat** (auto-dated name, with model/permission-mode/effort
  options). The same panel has a **register new project** form (name + folder + model) at the bottom —
  adds to the roster without editing files by hand.
- **Closed / Retired** — temporarily stopped / fully abandoned projects; come back with "reactivate".
  An active project can be **closed** (temporary) or **retired** (permanent).
- **Layout** — arranges windows across desktops (`wmctrl`+`xdotool`, X11 only). Known to misbehave on a
  locked screen or under Wayland, so there's an **automatic pre-flight check** — it refuses if the
  screen is locked. Warns (doesn't install, since that needs sudo) if a dependency is missing
  (Ubuntu/Debian: `sudo apt install -y wmctrl xdotool`).
- **TR/EN** — auto-selected from the browser's language (`navigator.language`), can be switched manually
  with the buttons in the top corner and stays persisted (localStorage).
- **Token protected** (`~/.claude/claudeops/web.token`, randomly generated on first run) — both the page
  and the API return 401 without it. `--tunnel` opens a `cloudflared` quick tunnel (auto-downloaded to
  `~/.local/bin` if missing, Linux amd64/arm64).

## CLI commands

```
py/cops list      # list running sessions
py/cops kill      # gently stop one/several sessions (SIGTERM + grace + SIGKILL if needed)
py/cops close     # close for good (kill + mark so guard won't reopen it)
py/cops guard     # detect missing sessions from the roster and open them (crash-recovery; cron-able)
py/cops rc        # kill + reopen (one at a time or in bulk; for handover/respawn)
py/cops handover  # close an old session with a wrap-up message, reopen under the same name
py/cops stuck     # detect stuck sessions (idle but showing "busy")
py/cops layout    # arrange windows across desktops (X11)
py/cops web       # the control panel (above)
```

Every command has its own `--help`.

## How it works

- The **roster** is two TSV files, outside the repo (`~/.claude/claudeops/`, personal, never
  committed): `roster.tsv` (`name<TAB>folder<TAB>model`) and `models.tsv` (`name<TAB>model` — a line
  starting with `#` means that name is closed/retired, guard won't open it).
- Sessions are opened inside `gnome-terminal` with `claude -n NAME --remote-control NAME` — Claude
  Code's own Remote Control feature (also reachable from claude.ai/code or the mobile app).
- Kill is always **SIGTERM + ~10 second wait + SIGKILL if still alive** — since Claude Code's transcript
  is written to disk lazily (checkpoint by checkpoint), a too-fast `SIGKILL` can cut off conversation
  history.
- `guard` is optional — don't set it up if you don't want it, manage everything by hand from
  `py/cops web` instead.

## Folder structure

```
py/claudeops/
  paths.py, session.py, discovery.py   # foundation: paths, data model, proc discovery (psutil)
  spawn.py, kill.py, guard.py, layout.py, roster.py, handover.py, needs_ho.py, config.py, stuck.py
  commands/                             # one file per CLI command (web.py is the largest)
cops                                    # entry point → python3 -m claudeops
```

## Design notes

- **psutil, not `ps|grep`** — cmdline comes back as a list, no quoting/anchor/substring traps.
- **CPU as the primary "is it alive" signal** — Claude Code's own `status`/bridge fields update with a
  delay, CPU%>2 is a more reliable "actually running" indicator.
- **Bash `claudeops`** (repo root) is still around but only for old/legacy commands now — all live fleet
  management (guard, rc, handover, web) is fully in this Python version.
