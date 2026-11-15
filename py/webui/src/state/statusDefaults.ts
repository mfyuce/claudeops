/**
 * Multi-user mode (K3 status filter) hides machine/fleet keys from non-admin principals: `orch`, `remote_desktop`, `diag`, `settings`,
 * `steward`, `tunnel`... The panel reads several of them unguarded (`data.orch.active`, `data.diag.fallback_alert`), so a missing key
 * blanked the whole page for a `user` login (found in the 15 Nov browser check). Fill neutral values for every key the types call
 * required; a payload that already has the key is returned untouched. Hidden data stays hidden: the defaults carry no information.
 */
import type { Settings, StatusPayload, StewardSummary } from "../api/types";

const EMPTY_STEWARD: StewardSummary = {
  enabled: false, mode: "", tick_seconds: 0, projects: {}, open_questions: 0, ideas_new: 0, pending_items: 0,
  last_tick: {}, last_tour: 0, brain: { name: "", running: false }, recent: [],
};

export function withStatusDefaults(d: StatusPayload): StatusPayload {
  const p = d as Partial<StatusPayload>;
  if (p.orch && p.remote_desktop && p.diag && p.settings && p.steward && p.tunnel && p.dups && p.layout_missing_deps && p.handover_msg) return d;
  return {
    ...d,
    dups: p.dups ?? [],
    layout_missing_deps: p.layout_missing_deps ?? [],
    diag: p.diag ?? { web_pid: 0, web_uptime_seconds: 0, gt: null, windowless: null, recent_fallback_count: 0, fallback_alert: false, fallback_alert_window_minutes: 0 },
    handover_msg: p.handover_msg ?? { tr: "", en: "" },
    settings: p.settings ?? ({} as Settings),
    remote_desktop: p.remote_desktop ?? { running: false, port: null },
    tunnel: p.tunnel ?? { url: null, label: null },
    orch: p.orch ?? { draft: [], active: null, recent: [] },
    steward: p.steward ?? EMPTY_STEWARD,
  };
}
