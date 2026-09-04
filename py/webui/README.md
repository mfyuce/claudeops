# claudeops web panel — frontend

React + TypeScript + Vite. Replaces the old `PAGE_HTML` string constant that
used to live in `py/claudeops/commands/web.py` (~1600 lines of embedded
HTML/CSS/JS) — see `dynamic-crunching-lemon.md` (the plan this rewrite
followed) for the full history/rationale. The backend (`py/claudeops/`) is
unchanged Python; this directory is purely the browser client.

## Dev workflow — two modes

**1. Day-to-day (HMR against a real backend)**

```
py/cops web                 # real backend, real fleet, port 8765 by default
cd py/webui && npm run dev  # Vite dev server, port 5173, proxies /api and /ws to 127.0.0.1:8765
```

Visit `http://localhost:5173/?token=<the real token>` (same token
`py/cops web --print-token` prints, or read `~/.claude/claudeops/web.token`
directly). The dev server's proxy (`vite.config.ts`) forwards the query
string along with every proxied request, so token auth works with zero
dev-only bypass. Edits to anything under `src/` hot-reload in place.

**2. End-to-end validation (the real production request path)**

```
cd py/webui && npm run build   # writes dist/ (committed to the repo, see below)
py/cops web                    # serves dist/ directly — no Vite involved at all
```

This is the *only* mode that exercises the real static-file-serving code
(`py/claudeops/commands/web_static.py`) and the `/assets/*` auth carve-out
in `web.py`'s `do_GET` — mode 1 never touches either, since Vite's own dev
server serves the page there. Do at least one full pass in this mode before
considering a change done.

## Other scripts

```
npm run typecheck   # tsc -b — strict, zero warnings tolerated; run before every build
npm run build       # vite build → dist/ (sourcemaps on, see vite.config.ts)
npm run preview     # vite's own static preview of a built dist/ (rarely needed — mode 2 above is more representative)
npm run lint        # oxlint
```

## Why `dist/` is committed

The deployed `claudeops-web.service` systemd unit has **no build step** —
its `ExecStart` is a plain `python3 -m claudeops web` (see
`py/claudeops/commands/service.py`'s docstring for why that's load-bearing:
PATH/`KillMode` gotchas already bitten this project once). Shipping a
prebuilt `dist/` (including `*.js.map`/`*.css.map`) means deploying this
frontend needs zero new runtime dependency and zero build infrastructure on
the machine actually running the panel — `git pull` + restart the service is
enough. Always run `npm run build` and commit the result together with the
source change that caused it.

## Structure

- `src/api/` — typed `fetch()` wrapper (`client.ts`) + `StatusPayload`/route
  payload types (`types.ts`).
- `src/hooks/useStatus.ts` — the status feed: WS-primary
  (`/ws?token=...`, exponential-backoff reconnect) with an independent slow
  REST poll as a correctness backstop. The highest-risk piece of this
  frontend; see its own header comment for the full design and
  `py/claudeops/commands/web_ws.py`'s docstring for the server side it talks
  to.
- Per-session terminal/chat output polling lives inline in
  `src/components/TerminalModal/` (`TerminalView.tsx`/`ChatView.tsx`) —
  deliberately plain REST polling, not WS (no fan-out benefit for
  per-session data, keeps the WS code's blast radius limited to the status
  feed).
- `src/i18n/` — `strings.ts` (TR/EN, both checked against one `Strings`
  interface at compile time) + `LangContext.tsx`.
- `src/state/` — `StatusContext.tsx` (wraps `useStatus()`), `selection.ts`
  (the shared multi-row-select `Set`, used by both Running and Registered
  tabs), `tabs.ts`.
- `src/components/` — one subfolder per tab (`RunningTab/`,
  `RegisteredTab/`, `TerminalModal/`) plus shared pieces (`TabBar.tsx`,
  `Banners.tsx`, `GroupTable.tsx`, `LayoutTab.tsx`, `DiagnosticsTab.tsx`,
  `DesktopTab.tsx`).
- `src/styles/global.css` — one global stylesheet, ported 1:1 from the old
  `PAGE_HTML`'s `<style>` block. No CSS Modules/Tailwind/CSS-in-JS.

No test framework (Jest/Vitest/Playwright) is wired into `npm test` or CI —
this is a single-operator personal tool with no existing test
infrastructure; `tsc -b` is the automated safety net. Interaction-level
verification (does a background status update preserve an open terminal/an
in-progress form field, does the WS reconnect after a real network drop,
etc.) has been done by hand, repeatedly, with a real headless-Chromium
Playwright session driving the real backend — see the git log for the
specifics of what was checked at each stage.
