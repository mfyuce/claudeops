# WEBUI-TODO (panel developer experience)

Scope: whole worktree (`py/webui/src`, `py/claudeops`). No commits from the assistant; `tsc` is run by the owner.
Status: [ ] open, [x] done.

1. [x] Empty states: GroupTable + HistoryTab `emptyHint`; Review/ucli lists keep their own text.
2. [x] Error messages: `friendlyUcliError` + generic `friendlyError` in `api/ucliErrors.ts`; applied to Diagnostics, Layout, Snapshot, Settings, Orch, Review. Open: toast-only call sites (GroupTable, HostsSection, StewardTab...) still raw.
3. [x] Keyboard shortcuts: Alt+1..9, `/` (`shared/useTabShortcuts.ts`). `?` help: `shared/ShortcutHelp.tsx` (inline TR/EN, mounted in App.tsx).
4. [x] Loading states: first status fetch (App.tsx). Added "…" loading rows in ReviewPanel and StewardTab (state null). Busy buttons were already everywhere (`disabled={busy}`), no change needed.
5. [x] Mobile layout: appended block at end of `styles/global.css` (36px tap targets, wrapping). Not verified in a browser; the cli column (with badges) is hidden <=640px by the existing query.
6. [x] ucli session row info: effort badge + write (✎) / exec / `≤$cap` badges. Backend: `web.py` `_ucli_flags(s)` (cmdline parse, per-pid cache) -> `ucli_flags` on sessions (local host only; gRPC remote rows don't carry it). No unittest yet.

## Resume point
Done this round: `?` help (3), per-tab loading rows (4).
Next: 7. unittest for `_ucli_flags` (py/tests); 8. toast-only call sites of 2 (GroupTable, HostsSection, StewardTab) -> friendlyError; 9. verify mobile CSS + ucli badges <=640px in a browser (owner).

## Done log
- friendlyError applied to 6 tabs; effort badge on ucli rows.
- ucli_flags backend + badges; mobile CSS block.
