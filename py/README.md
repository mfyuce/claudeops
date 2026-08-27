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

- **Tabs** — **Running / Registered / Disabled / Retired / Layout** (the active tab persists across
  reloads). Nothing ever starts automatically.
- **Running** — every live session, one **checkbox** per row, and **bulk action buttons above the
  table**: *handover* / *stop* / *disable* / *retire* run on the selected rows one by one, with a
  confirm dialog (listing the names) and per-name progress + error reporting. A short legend under the
  buttons explains each verb. A **ho? column** shows whether a session *needs a handover* (dirty repo /
  untracked files / commits since baseline / no wrap-up yet), and **select needs-ho** picks all of
  those in one click.
- **stop vs disable vs retire** — *stop* kills only the process/window (the project stays registered —
  resume it from the Registered tab); *disable* also keeps automation (guard) from reopening it (moves
  to the Disabled tab, reversible); *retire* archives it (Retired tab, comes back via "reactivate").
- **Terminal** — a **Terminal** button appears on rows backed by `tmux` (`-L cops`, a dedicated socket):
  view the session's live output and send it commands right from the browser (xterm.js render, ~200ms
  poll, plus Ctrl-C/Esc/arrow-key buttons). Requires `tmux` (`sudo apt install tmux`) — without it,
  sessions still start fine, just without the button. Only sessions (re)opened *after* tmux support was
  added get it; a currently-running plain session picks it up the next time it's respawned
  (handover/adopt/stop+start). What you see is tmux's own scrollback, not the CLI's native screen redraw
  — a bit of drift versus scrolling in a real terminal window is expected (rough edge, being improved),
  but the session stays fully reachable and controllable either way. This is also what makes it work for
  **any** CLI backend, even one with no remote-access feature of its own (agy has none) — claudeops's own
  tmux layer is what makes a session reachable, not something the underlying CLI has to support.
- **Registered** — registered-but-stopped projects; start one with **resume** / **reset (--new)** /
  **start a separate new chat** (auto-dated name, with model/permission-mode/effort options). The
  **register new project** form (name + folder + model) lives at the bottom of this tab — adds to the
  roster without editing files by hand.
- **CLI choice (claude / agy)** — every start/register/new-chat option row has a **CLI** selector: pick
  `claude` or `agy` (Google's Antigravity CLI, if installed at `~/.local/bin/agy`) per session. Model/permission-mode/effort options switch to that CLI's own list
  automatically (agy's model list is fetched live from `agy models`, not hardcoded). A session's CLI is
  fixed once running — shown as a small badge, not editable (adopting a foreign process keeps whatever
  CLI it already was; you can't "adopt a claude process as agy"). A bare `agy` process with no name
  claudeops gave it shows up as `agy-<pid>`, adoptable like any other unregistered session. Today's
  choices are `claude` and `agy`; the provider architecture behind this (see "How it works" below) is
  what makes adding a future backend — say, GitHub Copilot CLI, or any other CLI-based coding agent —
  a matter of writing one more provider file, not a rewrite.
- **Disabled / Retired** — temporarily stopped / fully abandoned projects; come back with "reactivate".
- **Handover** — sends the selected running sessions a wrap-up prompt (update their docs, commit, push),
  restarting each with `--resume` (same history) plus that message as the first turn. Uses the message
  in whichever language the panel is currently set to, and whichever model is set for that project in
  the roster (not necessarily whatever model the live session happened to be switched to interactively).
  There is no hardcoded exclude list — what you select is what runs; the only built-in protection is
  that a session can never kill the CLI it itself is being driven from.
- **Sessions outside the roster show up too** — anything running that claudeops didn't open (e.g. a
  plain `claude` you started by hand in a project folder) appears tagged "unregistered", with an
  **adopt** action (attach `--remote-control` under a name of your choice and register it — closes that
  window and reopens a new one with the same history, since claudeops didn't own it to begin with).
  Stop/handover work on them through the checkboxes like any other row.
- **Layout** — its own tab; arranges windows across desktops (`wmctrl`+`xdotool`, X11 only). Known to
  misbehave on a locked screen or under Wayland, so there's an **automatic pre-flight check** — it
  refuses if the screen is locked. Warns (doesn't install, since that needs sudo) if a dependency is
  missing (Ubuntu/Debian: `sudo apt install -y wmctrl xdotool`). This is the *only* action that needs
  an unlocked screen — start/stop/handover/adopt/new-chat all work fine on a locked screen too (handy
  if you're driving the panel from your phone while your desktop is locked).
- **TR/EN** — auto-selected from the browser's language (`navigator.language`), can be switched manually
  with the buttons in the top corner and stays persisted (localStorage).
- **Token protected** (`~/.claude/claudeops/web.token`, randomly generated on first run) — both the page
  and the API return 401 without it. `--tunnel` opens a `cloudflared` quick tunnel (auto-downloaded to
  `~/.local/bin` if missing, Linux amd64/arm64).

### Access from your phone

<img src="../docs/web-panel-mobile.png" alt="claudeops web panel on mobile" width="320">

The table adapts on narrow screens (model/kind columns hide, action buttons stay reachable without
scrolling).

```bash
py/cops web --tunnel
```

This prints two URLs:

```
claudeops web  →  http://127.0.0.1:8765/?token=<token>
  tunnel  →  https://random-words-here.trycloudflare.com/?token=<token>
```

The **second one** (`trycloudflare.com`) works from anywhere with internet — no VPN, no need to be on
the same Wi-Fi as the machine running it. Get that exact URL onto your phone (send it to yourself via
notes/chat, or print a scannable QR code for it right in your terminal with
`qrencode -t ansiutf8 "<url>"` (Ubuntu/Debian: `sudo apt install -y qrencode`) — everything stays local,
nothing sends the URL to a third party) and open it in your phone's browser.

A few things worth knowing:
- The **token** is stable across restarts (same `~/.claude/claudeops/web.token` file every time), but the
  **tunnel URL changes** on every `--tunnel` run — it's a Cloudflare "quick tunnel", no account or
  domain needed, but also no fixed address. Keep the terminal open (or run it detached, e.g. under
  `tmux`/`nohup`) for the tunnel to stay up.
- Treat the full URL (with `?token=...`) like a password — anyone who has it can start/stop your
  sessions. Don't post it publicly, don't leave it visible in a screen share, and don't put it in this
  screenshot's URL bar if you ever take one for yourself (this README's screenshot is viewport-only, no
  address bar, on purpose).
- Want a URL that doesn't change every time? That needs a Cloudflare **named tunnel** on your own domain
  instead of `--tunnel`'s quick tunnel — not set up by claudeops by default.
- The quick tunnel is today's only way to reach the panel from outside your LAN; a self-hosted/persistent
  server option may be added later.

**There's a second, independent way to reach a session from your phone:** every session claudeops opens
uses `--remote-control`, which is Claude Code's own built-in feature — so it also shows up in the
official **Claude mobile app**, under the **Code** tab, as a live connection you can tap into and chat
with directly (no claudeops, no tunnel involved, that's Anthropic's own infrastructure). The claudeops
web panel is for managing *which sessions exist* (start/stop/register/layout); the Claude app's Code tab
is for *talking to one that's already running*. Handy to use together.

## CLI commands

```
py/cops list      # list running sessions
py/cops kill      # gently stop one/several sessions (SIGTERM + grace + SIGKILL if needed)
py/cops close     # close for good (kill + mark so guard won't reopen it)
py/cops guard     # detect missing sessions from the roster and open them (crash-recovery; cron-able)
py/cops rc        # kill + reopen (one at a time or in bulk; for handover/respawn)
py/cops handover  # close a session with a wrap-up message, reopen under the same name
                   #   no args = whole fleet (batch, skips co/ulaksec); NAME = single
                   #   session, roster not required, co/ulaksec included; --lang=en
py/cops stuck     # detect stuck sessions (idle but showing "busy")
py/cops layout    # arrange windows across desktops (X11)
py/cops web       # the control panel (above)
```

Every command has its own `--help`.

## How it works

- The **roster** is two TSV files, outside the repo (`~/.claude/claudeops/`, personal, never
  committed): `roster.tsv` (`name<TAB>folder<TAB>model`, plus an optional 4th column `cli` —
  `claude` or `agy`, defaults to `claude` if missing/old-format) and `models.tsv` (`name<TAB>model` —
  a line starting with `#` means that name is closed/retired, guard won't open it).
- Sessions are opened inside `gnome-terminal`, wrapped in a dedicated `tmux` session when `tmux` is
  installed (falls back to plain, un-wrapped `gnome-terminal` otherwise — spawning never fails just
  because `tmux` is missing). A `claude` session runs `claude -n NAME --remote-control NAME` — Claude
  Code's own Remote Control feature (also reachable from claude.ai/code or the mobile app). An `agy`
  session has no equivalent naming flag, so its name is carried via a `COPS_NAME` environment variable
  instead.
- Support for a second CLI backend (`agy`, Google's Antigravity CLI) is implemented as a **provider**:
  a small `CliProvider` interface (`py/claudeops/providers/base.py`) that `claude_provider.py` and
  `agy_provider.py` each implement; the rest of the codebase (spawn/discovery/web panel) only ever
  calls through that interface and never branches on which CLI is in use — adding a third backend
  means writing one more provider file, not touching existing code.
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
  tmux_backend.py                       # tmux helpers (dedicated -L cops socket), fail-soft if no tmux
  providers/                            # CliProvider ABC + one file per CLI backend + registry
    base.py, claude_provider.py, agy_provider.py, __init__.py
  data/                                  # bundled static assets: tmux.conf, vendored xterm.js
  commands/                             # one file per CLI command (web.py is the largest)
cops                                    # entry point → python3 -m claudeops
```

## Design notes

- **psutil, not `ps|grep`** — cmdline comes back as a list, no quoting/anchor/substring traps.
- **CPU as the primary "is it alive" signal** — Claude Code's own `status`/bridge fields update with a
  delay, CPU%>2 is a more reliable "actually running" indicator.
- **Bash `claudeops`** (repo root) is still around but only for old/legacy commands now — all live fleet
  management (guard, rc, handover, web) is fully in this Python version.
