# Using menzil with claudeops

[menzil](https://menzil.dev) is a self-hosted tunnel (Apache-2.0 OR MIT). claudeops does not depend on it and has no menzil-specific code. Everything below uses mechanisms claudeops already has: a host's `base_url`, its fallback `extra_urls`, and the panel listening on `127.0.0.1:8765`.

Two uses are covered:

1. reach another machine's claudeops panel (federation) through menzil instead of devtunnel or a quick tunnel;
2. give this machine's panel a fixed public address instead of a rotating `trycloudflare.com` one.

## Before you start

- Every machine involved runs `menzil node` and has joined the same menzil network (`menzil init`, then `menzil admit` / `menzil join`; see the menzil README).
- The machine whose panel you want to reach serves it as a menzil service named, for example, `panel`, pointing at `127.0.0.1:8765`.
- The network owner has granted your device access to that service (`menzil grant`).
- Check the relay is reachable from where you are. Some corporate networks block newly registered domains: if `menzil node` keeps logging `Connection refused`, test the relay's port 443 from another network before debugging claudeops.

## 1. Reach a remote panel (federation)

On the machine running your local claudeops, carry a local port to the remote panel:

```bash
menzil reach <remote-device>/panel --listen 127.0.0.1:18766
```

A TCP listen port is open to every user of this machine and carries your menzil grants (like `ssh -L`). The panel token still guards the panel, but on a shared machine keep that in mind.

To keep it running, use a user unit (the node must start first):

```ini
# ~/.config/systemd/user/menzil-reach-<remote>.service
[Unit]
Description=menzil reach <remote>
After=menzil-node.service
[Service]
ExecStart=%h/.local/bin/menzil reach <remote-device>/panel --listen 127.0.0.1:18766
Restart=always
RestartSec=5
[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now menzil-node.service menzil-reach-<remote>.service
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18766/api/ping   # 401 = reached the panel
```

Then point the host at it in the panel (Settings > Hosts), keeping the old address as a fallback:

- **Base URL:** `http://127.0.0.1:18766`
- **Extra URLs:** your previous address (for example the devtunnel URL), one per line

If the menzil path fails, claudeops' host poller tries the extra URLs in order and promotes the first one that answers, so the panel keeps working while menzil is down. Change hosts through the panel (or `POST /api/hosts`), not by editing `hosts.json`: the database is the source of truth and edits to the file are not read back.

## 2. Fixed public address for this panel

The panel speaks plain HTTP, so it needs menzil's `terminated` mode (the relay ends TLS and forwards plain HTTP/1.1; your tenant must have `terminated` enabled):

```bash
menzil expose 8765 --name <name> --mode terminated   # https://<name>.<relay share domain>
menzil expose list                                   # shows whether the relay accepted it
```

In `terminated` mode the relay can read the traffic, so use a relay you run yourself. The default `blind` mode keeps the relay from reading anything, but then the panel would have to serve TLS with a certificate for the public name, which claudeops does not do today. The panel's own token still protects every request either way. Unlike a quick tunnel, the address does not change when the service restarts, so phones and bookmarks keep working.

The quick tunnel (`run-tunnel.sh`) can stay as a backup. Its health watchdog only manages cloudflared and does not touch menzil.

## Removing it

Stop and disable the menzil units, and set the host's base URL back to the fallback address. Nothing else in claudeops changes.
