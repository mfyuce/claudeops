/**
 * Small shared helpers for the `(host, name)` composite identity every
 * session/roster row now carries (Faz 3 of the multi-host federation plan,
 * ~/.claude/plans/vectorized-jingling-harp.md) — kept in its own file
 * rather than `api/types.ts` since these are behavior, not types.
 */

import { EMPTY_CLI_OPTIONS, type CliOptions, type StatusPayload } from "../api/types";

/** Must match the backend's `hosts.py` `LOCAL_HOST_NAME` exactly — every
 * session is tagged with this until a remote host is actually registered. */
export const LOCAL_HOST = "local";

/** The identity key used EVERYWHERE a row needs one: React `key=` props,
 * `selection.ts`'s `Set<string>`, and the `openOptionsFor`/`openAdoptFor`/
 * `openTerminalFor` pointer states. Never used inside an API call body —
 * those keep sending `host`/`name` as separate fields. Safe to join with
 * `:` because host names match `^[a-z][a-z0-9_-]*$` (`hosts.py`) and
 * session names match claudeops' own name pattern — neither can contain
 * `:`, so no two distinct (host, name) pairs can ever collide here. */
export function rowKey(s: { host: string; name: string }): string {
  return `${s.host}:${s.name}`;
}

/** A session's own host's CLI list — local sessions read the aggregator's
 * top-level `cli_list` (unchanged from before federation existed); remote
 * sessions read that host's OWN list out of `data.hosts` (never assumed to
 * match local, some CLIs fetch their model list live per host). Falls back
 * to `[]` if `data` hasn't loaded yet or the host isn't found (e.g. it just
 * went unreachable) — `data` is nullable here purely to match the existing
 * `data?.cli_options[cli] ?? EMPTY_CLI_OPTIONS` defensive style every caller
 * already used before this helper existed (components render before
 * `StatusContext`'s first successful load in a couple of edge cases). */
export function cliListFor(data: StatusPayload | null | undefined, host: string): string[] {
  if (!data) return [];
  if (host === LOCAL_HOST) return data.cli_list;
  return data.hosts.find((h) => h.name === host)?.cli_list ?? [];
}

export function cliOptionsFor(data: StatusPayload | null | undefined, host: string, cli: string): CliOptions {
  if (!data) return EMPTY_CLI_OPTIONS;
  if (host === LOCAL_HOST) return data.cli_options[cli] ?? EMPTY_CLI_OPTIONS;
  return data.hosts.find((h) => h.name === host)?.cli_options[cli] ?? EMPTY_CLI_OPTIONS;
}
