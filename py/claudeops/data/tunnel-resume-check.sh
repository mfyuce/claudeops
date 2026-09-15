#!/usr/bin/env bash
# claudeops tunnel resume-hook (bundled template, NOT installed automatically —
# TOBEDECIDED.md #31 tracks the open "install it or not" decision; matches the
# `run-tunnel.sh`/`tmux.conf` "bundled in-repo, static" pattern in this same
# `data/` dir). Meant to be copied to `/usr/lib/systemd/system-sleep/` (root-
# owned, system-wide — systemd-logind calls every executable there around
# suspend/resume as: <script> (pre|post) (suspend|hibernate|...)).
#
# Why this exists (2026-09-15, live-diagnosed): cloudflared's quick-tunnel
# registration does not survive a suspend/resume cycle — the server side
# forgets it during the gap, and on wake cloudflared tries to resume the SAME
# (now-dead) registration instead of requesting a new one, then retries that
# dead ID forever ("Unauthorized: Tunnel not found", never self-recovers).
# Confirmed live: suspend at 15:09:58 UTC, first such error at 15:19:07 UTC —
# every prior "tunnel gitti" report this project has logged traces back to
# this exact class of registration loss, only ever fixed by a manual
# `systemctl --user restart claudeops-tunnel.service`.
#
# Deliberately NOT an unconditional restart-every-resume: that would rotate a
# perfectly fine URL for no reason on every suspend, breaking bookmarks for
# nothing (observed live, same session: the URL can already rotate on its own
# within seconds of a restart, no need to add MORE unnecessary churn). Instead:
# give cloudflared's own reconnect attempt a grace window, then actually test
# whether the CURRENT url still works, and only force a restart if it doesn't.

[ "$1" = "post" ] || exit 0

CLAUDEOPS_USER="fatihyuce"
STATE_DIR="/home/$CLAUDEOPS_USER/.claude/claudeops"
# Canonical current URL — same file `run-tunnel.sh` itself writes on every
# (re)registration (its own header: "Güncel URL her zaman: .../tunnel_url.txt").
# NOT parsed from tunnel.log: that file gets rotated/truncated by fresh
# launches, so "last URL line in the log" isn't reliably the CURRENT one
# (caught live in this same debugging session).
URL_FILE="$STATE_DIR/tunnel_url.txt"

UID_NUM="$(id -u "$CLAUDEOPS_USER" 2>/dev/null)" || exit 0
[ -n "$UID_NUM" ] || exit 0

# Grace window: let networking (DHCP/DNS) and cloudflared's own reconnect
# settle before judging anything broken — a fresh-out-of-suspend "can't
# resolve" blip is expected and NOT the bug this hook targets.
sleep 15

URL="$(cat "$URL_FILE" 2>/dev/null)"

# No `-f`: curl exits 0 as long as it got ANY HTTP response, including the
# panel's normal 401-without-auth — that still proves DNS+TLS+routing are all
# fine. A non-zero exit (resolve/connect/timeout failure) is the real "still
# dead" signal.
if [ -z "$URL" ] || ! curl -sS -o /dev/null --max-time 8 "$URL/api/status"; then
    logger -t claudeops-resume-hook "claudeops-tunnel unreachable after resume (url=${URL:-none}), restarting"
    sudo -u "$CLAUDEOPS_USER" XDG_RUNTIME_DIR="/run/user/$UID_NUM" \
        systemctl --user restart claudeops-tunnel.service
else
    logger -t claudeops-resume-hook "claudeops-tunnel reachable after resume, no action"
fi
exit 0
