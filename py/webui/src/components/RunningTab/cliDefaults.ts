/**
 * Small shared defaults used by both `OptionsRow` and `AdoptRow` when
 * initializing their local form state — matches `renderCliFields()`'s
 * defaulting logic in the original (web.py ~1934-1943).
 */

import type { CliOptions } from "../../api/types";

/** Original: `m === (saved.pm || 'auto')` — the literal string "auto",
 * not "first item in the CLI's permission_modes list". */
export const DEFAULT_PERMISSION_MODE = "auto";

/** The server's `default_effort` (Settings override, else the provider's
 * default: claude medium) when it is a valid level; otherwise the LAST entry
 * (every provider's list ends with its highest level, e.g. "max") — the old
 * behaviour, still used for remote hosts whose rows carry no default. */
export function defaultEffort(opts: CliOptions): string {
  if (opts.default_effort && opts.effort_levels.includes(opts.default_effort)) return opts.default_effort;
  return opts.effort_levels[opts.effort_levels.length - 1] ?? "";
}

/** The model the empty "(...)" option stands for: server `default_model`, else the first listed. */
export function defaultModel(opts: CliOptions): string {
  return opts.default_model || opts.models[0] || "";
}
