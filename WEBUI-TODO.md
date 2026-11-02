# WEBUI-TODO (panel developer experience)

Scope: whole worktree (`py/webui/src`, `py/claudeops`). No commits from the assistant; `tsc` is run by the owner.
Status: [ ] open, [x] done.

1. [x] Empty states: GroupTable + HistoryTab `emptyHint`; Review/ucli lists keep their own text.
2. [x] Error messages: `friendlyUcliError` + generic `friendlyError` in `api/ucliErrors.ts`; applied to Diagnostics, Layout, Snapshot, Settings, Orch, Review. Open: toast-only call sites (GroupTable, HostsSection, StewardTab...) still raw.
3. [x] Keyboard shortcuts: Alt+1..9, `/` (`shared/useTabShortcuts.ts`). `?` help: `shared/ShortcutHelp.tsx` (inline TR/EN, mounted in App.tsx).
4. [x] Loading states: first status fetch (App.tsx). Added "…" loading rows in ReviewPanel and StewardTab (state null). Busy buttons were already everywhere (`disabled={busy}`), no change needed.
5. [x] Mobile layout: appended block at end of `styles/global.css` (36px tap targets, wrapping). Not verified in a browser; the cli column (with badges) is hidden <=640px by the existing query.
6. [x] ucli session row info: effort badge + write (✎) / exec / `≤$cap` badges. Backend: `web.py` `_ucli_flags(s)` (cmdline parse, per-pid cache) -> `ucli_flags` on sessions (local host only; gRPC remote rows don't carry it). No unittest yet.

7. [x] unittest for `_ucli_flags`: `py/tests/test_web_ucli_flags.py` (not run by the assistant).
8. [x] toast-only call sites (GroupTable, HostsSection, StewardTab) now use `friendlyError`.
9. [ ] Owner: verify mobile CSS + ucli badges <=640px in a browser; run `tsc` and `python3 py/tests/test_web_ucli_flags.py -v`.
10. [x] ucli badges (effort/✎/exec/≤$) moved from the cli cell into the name cell of `RunningTab/SessionRow.tsx`, so they show <=640px.
11. [x] Expandable error detail + copy: `shared/ErrorBox.tsx` (first line visible, raw message in <details>, copy button). Used in ReviewPanel.
12. [x] `ErrorBox` in Review, Steward, Settings, Snapshot, Orch. Layout/Diagnostics left as-is on purpose: their `<pre>` strings mix success and failure results.
13. [x] Copy buttons: `CwdCell` (shown when expanded) copies path and name. ucli session id: checked `ucli_provider.py` (~l.864): for ucli `sid` = the session name itself, so the "copy name" button already covers it; no new field needed.
14. [x] `ucli_flags` over gRPC: `host_bridge.proto` SessionRow fields 19-21 (`ucli_write`, `ucli_exec`, `ucli_max_cost_usd`); `web_grpc.py` maps them both ways, guarded by `_PB_HAS_UCLI_FLAGS`. OWNER: regenerate `host_bridge_pb2.py` (protoc not available to the assistant); until then remote rows have no badges, nothing breaks. No unittest for the mapping yet.
15. [ ] SKIPPED (cannot be done here): ucli service badge. The service is not in the cmdline, and it needs ucli to record it in the session record first.

Round 2 (picked from `claudeops-TODO-ui.md`; short):
16. [x] `friendlyError` 5xx rule matched any 5xx number; now only "http 5xx"/"status 5xx"/"bad gateway"... (`ucliErrors.ts`).
17. [x] GroupTable reactivate: "already active" shows as info toast, not an error, no double name.
18. [x] ReviewPanel "Only this": enable target first, then disable others; a mid-way failure says what is left half-done.
19. [x] Start window exec hint rewritten in plain words (built-in tools first, exec last resort). The bind-dirs field already existed.
20. [x] RunningTab toasts (SessionRow, OptionsRow, AdoptRow) use `friendlyError` for thrown errors.
21. [x] Backend `ucli_cost_watch` (`web_steward.py`): warn/stop flags reset when the cap changes, so raising the cap re-arms the watch. Tests: `py/tests/test_ucli_cost_watch.py` (existing file, +2 tests; not run).
22. [x] `web.py` SIGTERM handler: cloudflared tunnel is terminated before `os._exit` (was left orphaned). `_TUNNEL_PROC` + `_terminate_tunnel()`; tests `py/tests/test_web_sigterm_tunnel.py` (not run).
23. [x] `web_orch.py` push key now `(run_id, host, name)`; `http_result` takes optional `host`; without it a push is accepted only if exactly one waiting match exists. Tests `py/tests/test_web_orch_push_key.py` (not run). Optional: MCP `cops_result_push` could send `host`.

Round 3 (P2 review findings; all tests in `py/tests/test_p2_atomic_writes.py`, NOT run):
24. [x] New `atomic_json.atomic_write_text` (per-thread tmp, O_EXCL, fsync). `web_review.py`: `_write_lesson` (was fixed `path.tmp`, now `file_lock` + atomic) and the draft redaction rewrite (also fixed `dp.tmp`).
25. [x] `close.py` models.tsv: read-modify-write now under `file_lock` + atomic write (was bare open/write). Note: `web.py` `_atomic_write_text` still does not take that lock.
26. [x] `files.write_text`: fsync before `os.replace`.
27. [x] `steward_quota.py`: `_parse_reset` returned/raised ValueError on bad day or Feb 29 rollover -> now None; `_num` rejects nan/inf. (The TODO's :123/:49 line numbers were stale; I fixed what the current code showed. Check against the original finding text.)
28. [x] 22 (SIGTERM tunnel) already done with its test.
29. [x] `py/tests/test_web_grpc_ucli_flags.py`: mapping test for 14 (flag round-trip tests skip until pb2 is regenerated).

Round 4:
30. [x] `web_review.claude_argv`: every `rv.FORBIDDEN_PATHS` entry is now denied at tool level (`Read(**/pat)`, `Bash(*pat*)`), not only in the prompt (was CLAUDE.md only). Test in `py/tests/test_review.py` (not run). Caveat: Grep/Glob rely on Claude's Read-deny matching; not verified live.

Round 5:
31. [x] `review_store.dest_guard`: `check-ignore` exit codes other than 0/1 now fail closed; default git runs use `LC_ALL=C` so the "not a git repository" check is locale-independent. 2 tests in `py/tests/test_review_store.py` (not run).

Round 6:
32. [x] Checked, no change needed: `agy_label_ok` (exact normalised match, no substring), `commit_reviews` (no remote or `git remote` failure -> `ok=False` with error), `file_lock` (logs a one-time warning when the lock file cannot be taken; falls back to the thread lock). Stale entries in the TODO; owner may strike them.

Round 7:
33. [x] `snapshot.py:140` concurrent write: checked, `save_snapshot` already runs under `file_lock` + atomic write; stale entry.
34. [x] `web_review.py` module docstring rewritten (said "step 2: skeleton only"). Docs only, no test.
Open and larger (not started): multi-line message flattening for ucli targets (TODO line 30, touches tmux_send_keys, /api/term/input, steward directive, handover, web_orch).

## Resume point
Next: nothing open for the assistant. Owner: item 9 (also `tsc`, py tests: test_p2_atomic_writes, test_web_grpc_ucli_flags, test_web_sigterm_tunnel, test_web_orch_push_key, test_ucli_cost_watch), regenerate `host_bridge_pb2.py` (14). 15 has no UI work left: it needs ucli to record the service in the session record first.

## Done log
- friendlyError applied to 6 tabs; effort badge on ucli rows.
- ucli_flags backend + badges; mobile CSS block.

## Round 8 (uipol2)

35. [x] ReviewPanel reviewer ODAK (FOCUS) toggle: `review.pool_focus(pool)` + `next_review` sorts focus projects first; `web_review.pool_action` accepts `focus`/`unfocus` (focus needs an enabled project; `disable`/`remove` clear it); `review_state` rows carry `focus`; `types.ts` `ReviewPoolRow.focus?`, `client.ts` `apiReviewPool` action type, ReviewPanel ★/☆ button (TR/EN title). Test: `test_focus_project_goes_first` (`py/tests/test_review.py`). `pool_sync` copies entries so `focus` is kept. `http_review_pool` docstring updated.
    - GAPS (not done): no dedicated `pool_action` focus/unfocus test (budget ran out); CLI `steward.py` `pool` act (~line 716) does not know focus; ReviewPanel summary / "only this" interaction with focus untouched.
36. [x] UcliSpendPanel improved (`UcliSpendPanel.tsx`): remaining USD, plain state line (>=80% "close to the cap", >=100% "cap reached: new Claude ucli sessions refused"), bar colour, inline daily-cap editor (same `apiSaveSettings({ucli_cost:{daily_cap_usd}})` as Model keys, then `refresh()`), "lower-bound estimate" note. No quota-percentage was added (Evren quota badge stays in `UsageBadge.tsx`). Needs owner `tsc`. Note: `ucli_cost` 30 s cache is not invalidated when the cap is saved, so the new value shows after up to 30 s (not fixed).
37. [x] P3 `py/claudeops/files.py:55` `_resolve_within_roots`: root `/` made prefix `//` and matched nothing -> prefix normalised.
38. [x] P3 `steward_quota`: day boundaries used fixed 86400 s, shifting 1 h in DST weeks (wrong day label/cap) -> new `_week_day_index` uses wall-clock calendar days (used by `day_label`, `day_cap`).
39. [x] P3 `atomic_json.file_lock` reentrant: a nested call in the same thread opened a 2nd fd and `flock` self-deadlocked -> thread-local held-depth per path, nested calls skip flock (`_file_lock_outer` holds the real lock). Code is slightly awkward (`if True:` kept to avoid re-indenting) — owner may tidy.
    - Tests for 37-39: new `py/tests/test_p3_fixes.py`.
    - Not touched: the other P3/P2 items in `claudeops-TODO-ui.md` (e.g. `dest_guard`, `file_lock` silent-fallback warning stays as is).

## KALDIGIM YER (devir, uipol2)
Durum: yeni madde ACILMADI; hicbir edit yarim degil (son edit bitti).
Yapilan (hepsi commit'siz, hicbiri CALISTIRILMADI: tsc/test yok):
- 16-21: ucliErrors.ts, GroupTable.tsx, ReviewPanel.tsx, UcliStartOpts.tsx, RunningTab/{SessionRow,OptionsRow,AdoptRow}.tsx, web_steward.py (cost watch)
- 14: host_bridge.proto (19-21), web_grpc.py
- 22-34: web.py (SIGTERM tunel), web_orch.py (push key), atomic_json.py, web_review.py, close.py, files.py, steward_quota.py, review_store.py
- 35-39: review.py, web_review.py, ReviewPanel.tsx, types.ts, client.ts, UcliSpendPanel.tsx, files.py, steward_quota.py, atomic_json.py
Yarim kalan: item 35 GAPS (pool_action focus/unfocus testi yok; CLI steward.py `pool` (~l.716) focus bilmiyor; ozet/"yalniz bu" ile focus etkilesimi). atomic_json.py'de `if True:` girinti artigi.
Siradaki 3 madde:
1. 35 GAPS: pool_action focus/unfocus testi + steward.py pool focus.
2. ucli hedefinde cok satirli mesaji tek satira indirme (TODO l.30; tmux_send_keys, /api/term/input, steward directive, handover, web_orch).
3. ucli_cost 30 sn onbellegini tavan kaydedilince temizle (madde 36 notu) + test.
Test durumu: yazilan testler calistirilmadi: test_ucli_cost_watch, test_web_sigterm_tunnel, test_web_orch_push_key, test_p2_atomic_writes, test_web_grpc_ucli_flags (pb2 yenilenene dek atlanir), test_review, test_review_store, test_p3_fixes, test_steward_quota*. tsc calistirilmadi.
Not: git status'ta py/webui/dist degismis (yeni index-CTsxur94.js, eskisi silinmis); bunu ben yapmadim, sahibin build'i gorunuyor. dist'e dokunma.
Sahip: madde 9 (tsc/test/tarayici), host_bridge_pb2.py yeniden uretimi (14); 15 ucli'nin servisi oturum kaydina yazmasini bekliyor.
