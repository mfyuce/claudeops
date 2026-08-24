# claudeops

*English · [Türkçe](README_TR.md)*

Manage your open Claude Code sessions across multiple project folders from one place: see what's
running, start/stop with one click, even from your phone.

![claudeops web panel](docs/web-panel.png)

```bash
git clone https://github.com/mfyuce/claudeops.git && cd claudeops
pip install -r py/requirements.txt
py/cops web            # → http://127.0.0.1:8765
```

Full install instructions, all `web` panel features, and the command list: **[`py/README.md`](py/README.md)**.

MIT licensed — see [`LICENSE`](LICENSE).

---

The repo also contains an older **bash** script called `claudeops` (described below) — that was the
original version, now kept only for a handful of legacy commands. All live fleet management
(`guard`/`rc`/`handover`/`web`) lives in the Python version now; if you're just getting started, use
`py/cops` above.

## Install (bash `claudeops`, legacy)

```bash
chmod +x ./claudeops
# optional: add to PATH
ln -s "$(pwd)/claudeops" ~/.local/bin/claudeops
```

Requirements:
- `bash`, `python3` (always)
- `claude` (always — `~/.local/bin/claude` or global npm install)
- `gnome-terminal` (visible mode only)
- `wmctrl` (only for the `layout` command)
- `gsettings` (only for the `desktops` command)
- `xdotool` (Mutter snap workaround + initial prompt auto-submit)

Install (Ubuntu):
```
sudo apt install -y wmctrl xdotool
```

**Why xdotool?**
- Mutter's X11 `wmctrl -t` and `xprop _NET_WM_DESKTOP` ClientMessages are sometimes ignored → window
  placement is flaky
- The interactive `claude --remote-control NAME prompt` positional prompt pre-fills the input box but
  does NOT submit it → Enter has to be sent manually
- `xdotool`'s `windowactivate + type + key Return` fixes both

## Quick start

```bash
claudeops self                       # this conversation's pid, sid, bridge URL
claudeops list                       # all sessions
claudeops list all-but-self          # everything except self (recommended)

claudeops desktops 5                 # fix 5 workspaces
claudeops layout grid 4 --pin=rustrino13,sqli13  # pinned ones go to ws=0, 4-up grid

claudeops kill all-but-self          # SIGTERM everything
claudeops compact all-but-self --backup
claudeops rc all-but-self            # open in gnome-terminal with RC
claudeops rc rve13 --rename=rve14    # same sessionId, new name
claudeops rc all-but-self --suffix=14  # bulk suffix change
claudeops rc emrgence13 --new        # fresh empty session
claudeops send all-but-self -- "/clear"   # slash command
claudeops send hms13 -- "should we get back to the paper tomorrow?"

claudeops batch all-but-self         # full pipeline
claudeops new myname /home/youruser/work/projects/xyz
```

## Target syntax

| Form | Meaning |
|---|---|
| `all` | **All** sessions (self INCLUDED — careful!) |
| `all-but-self` / `notself` | Everything except self (default & safe) |
| `<name1> <name2> ...` | Matches in the TSV `name` field (self auto-excluded) |

## Notable lessons (real bugs and their fixes)

1. **stdin leak**: inside a `while read ... do ... done < file` loop, `claude -p` calls inherit stdin,
   and the TSV content leaks into the prompt. Fix: `claude ... < /dev/null` (already in the script).
2. **Slash commands work in `-p` mode**: `claude -p "/compact"` really does compact. Disk size doesn't
   shrink, but **token usage drops**, because on resume it counts forward from the
   `"isCompactSummary":true`-marked entry.
3. **Self protection**: `find_self_claude_pid` walks the ancestor chain from `$$` and finds the first
   `claude` binary. No hardcoded pid.
4. **Detached vs Visible**: detached uses `nohup setsid script -qfc 'claude ...' /tmp/log </dev/null >/dev/null 2>&1 &`.
   Visible uses `gnome-terminal --window --title=... -- bash -c "claude ...; exec bash"` (the `exec bash`
   keeps the window open even after claude exits).
5. **Rate limit**: the 5-hour usage limit shows up as `"You've hit your limit · resets ..."` in the
   assistant's reply. The compact loop stops on this pattern.
6. **Bridge URL is fixed per session**: after kill+resume, the same URL (bridgeSessionId) stays valid.

## Repo layout

- `py/` — the actively developed Python version (`py/cops`), see [`py/README.md`](py/README.md)
- `claudeops` — old/legacy single-file bash script
- `LICENSE` — MIT
- `README.md` / `README_TR.md` — English / Turkish
- `CLAUDE.md` — project context (for future Claude sessions)
- `TODO.md` — open work items
- `DONE.md` — changelog
- `TOBEDECIDED.md` — questions awaiting a user decision

## Recovery

To back up: `claudeops compact ... --backup` or `claudeops batch ...` (batch already backs up). Each
jsonl gets a `.bak.YYYYMMDD-HHMMSS` sibling. To roll back: `mv <sid>.jsonl.bak.X <sid>.jsonl`.
