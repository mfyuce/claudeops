/**
 * Replaces `unifiedOptsRow()` (web.py ~1971-1999) — and structurally
 * eliminates the `optsChoice` shadow-state dict that existed *only* to
 * survive `render()`'s `innerHTML=` wipe every ~4s. Everything in this
 * row's in-progress selection is plain local `useState`, initialized
 * fresh from `session`/`StatusContext` on mount, full stop — no
 * module-level or parent-level dict keyed by session name anywhere.
 * Reopening the row (the parent unmounts/remounts this component — see
 * `RunningTab`/`RegisteredTab`'s `openOptionsFor === name` conditional
 * render) starts fresh, same as the original's `optsChoice[name] = null`
 * on close.
 *
 * This is THE core regression check the whole rewrite exists for: type
 * into the free-text "other model" input, wait through a background
 * `StatusContext` update (the 4s poll) — since that poll only changes
 * `StatusContext`'s `data` and this component's position in the tree
 * never changes, React never unmounts it, so `modelOther` survives
 * untouched. See the top-level README/handover notes for how this was
 * actually observed against the real backend, not just reasoned about.
 */

import { useState } from "react";
import { apiNewChat, apiStart, apiStop } from "../../api/client";
import { callAction, describeApiError } from "../../api/errors";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { cliListFor, cliOptionsFor, LOCAL_HOST } from "../../state/hosts";
import type { SessionInfo } from "../../api/types";
import type { TabKey } from "../../state/tabs";
import { CliFields, OTHER_MODEL_VALUE } from "./CliFields";
import { DEFAULT_PERMISSION_MODE, defaultEffort } from "./cliDefaults";

type Mode = "resume" | "reset" | "newchat";

interface OptionsRowProps {
  session: SessionInfo;
  colspan: number;
  onClose: () => void;
  /** `runDiagAfterFailure`'s cross-tab jump needs the tab switcher `App`
   * owns — threaded down through `RunningTab`/`RegisteredTab`. */
  onSwitchTab: (tab: TabKey) => void;
}

/** Original: `d.getFullYear() + String(d.getMonth()+1).padStart(2,'0') +
 * String(d.getDate()).padStart(2,'0')` (web.py `todayStr()`). */
function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
}

export function OptionsRow({ session, colspan, onClose, onSwitchTab }: OptionsRowProps) {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();

  // 2026-09-15 fix: a RUNNING session used to offer only "newchat" here — the
  // only way to get the BulkBar-equivalent of "reset" (stop + restart fresh,
  // same name) on a single row was the separate bulk button. A user reaching
  // for "restart this" via Options (the natural place to look, e.g. right
  // after a session hits READY FOR HANDOVER) had no such option and picked
  // "newchat" instead, leaving the old conversation dangling AND creating a
  // needless "<name>_1" sibling — the mechanism behind years of accumulated
  // "_1.._N" roster clutter on the SAME base (live user report, not a guess:
  // "stop and start da cli ismi eski cli ismi artı _1 şeklinde geliyor").
  // "resume" still makes no sense while running (nothing to resume into).
  const [mode, setMode] = useState<Mode>(() => (session.running ? "reset" : "resume"));
  const [cli, setCli] = useState(session.cli);
  // "" = use the backend's own default (`provider.model_choices()[0]`, or the
  // session's current model on resume). TODO L73 (2026-09-02): pre-fill from
  // the user's persisted per-CLI default if they've set one — still just an
  // initial suggestion, not a lock-in; changing the dropdown overrides it for
  // this one invocation same as before.
  // Settings' `default_model` is the AGGREGATOR's own preference — a remote
  // host has no visibility into it (and vice versa), so only pre-fill for a
  // local session; a remote one starts blank and lets that host's own
  // backend default (`fallback_model` in `_start()`) take over.
  const [model, setModel] = useState(() =>
    session.host === LOCAL_HOST ? (data?.settings.default_model[session.cli] ?? "") : "",
  );
  const [modelOther, setModelOther] = useState("");
  const [permissionMode, setPermissionMode] = useState(DEFAULT_PERMISSION_MODE);
  const [effort, setEffort] = useState(() => defaultEffort(cliOptionsFor(data, session.host, session.cli)));
  const [busy, setBusy] = useState(false);

  // `cliListFor` can come back empty for a not-yet-known/unreachable remote
  // host — always fall back to at least the session's own current cli, same
  // as the original single-host `data?.cli_list ?? [session.cli]` fallback.
  const cliListRaw = cliListFor(data, session.host);
  const cliList = cliListRaw.length ? cliListRaw : [session.cli];
  const cliOptions = cliOptionsFor(data, session.host, cli);
  const currentModelLabel =
    cli === session.cli ? session.model || cliOptions.models[0] || "" : cliOptions.models[0] || "";

  const modeChoices: [Mode, string][] = session.running
    ? [
        ["reset", t.modeChoiceReset],
        ["newchat", t.modeChoiceNewchatOnly],
      ]
    : [
        ["resume", t.modeChoiceResume],
        ["reset", t.modeChoiceReset],
        ["newchat", t.modeChoiceNewchat],
      ];
  const modeLabels: Record<Mode, string> = { resume: t.modeResume, reset: t.modeReset, newchat: t.modeNewchat };

  // Deliberate, minor improvement over the original's onCliChange(): that
  // one kept whatever model/pm/effort had been chosen for the PREVIOUS
  // CLI and re-rendered the new CLI's option lists against them, which
  // usually matches nothing (a claude permission-mode string is unlikely
  // to also be a valid agy one) and silently falls back to the browser's
  // native first-option default anyway. Resetting explicitly here reaches
  // the same end state without carrying stale, CLI-incompatible values
  // through local state in between.
  function handleCliChange(newCli: string) {
    setCli(newCli);
    setModel(session.host === LOCAL_HOST ? (data?.settings.default_model[newCli] ?? "") : "");
    setModelOther("");
    setPermissionMode(DEFAULT_PERMISSION_MODE);
    setEffort(defaultEffort(cliOptionsFor(data, session.host, newCli)));
  }

  /** Replaces `runDiagAfterFailure(msg)` (web.py ~2723-2730) minus the
   * parts of it that reach into the Diagnostics tab's own internals
   * (`loadDiagLog()`/`doDiagTest()`) — that tab doesn't exist yet this
   * stage (plan Sequencing step 7), so this just offers the tab switch,
   * which is the structural reason `activeTab` lives in `App`. */
  function confirmDiagFollowup(message: string) {
    if (window.confirm(message + "\n\n" + t.diagRunAfterFail)) {
      onSwitchTab("diag");
    }
  }

  async function handleGo() {
    setBusy(true);
    const resolvedModel = model === OTHER_MODEL_VALUE ? modelOther : model;
    if (mode === "newchat") {
      try {
        const res = await apiNewChat({
          base: session.name,
          host: session.host,
          model: resolvedModel,
          permission_mode: permissionMode,
          effort,
          cli,
          lang,
        });
        if (res.ok) window.alert(t.newChatStarted + res.name);
        else confirmDiagFollowup(`${session.name}: ${res.error}`);
      } catch (e) {
        window.alert(describeApiError(e, t));
      }
    } else {
      // "reset" while still running (modeChoices above) needs the same
      // stop-then-fresh-start sequence BulkBar's bulk "reset" already does —
      // `/api/start` alone would just fail with "already_running".
      await callAction(
        async () => {
          if (session.running) {
            const stopRes = await apiStop({ name: session.name, host: session.host, lang });
            if (!stopRes.ok) return stopRes;
          }
          return apiStart({
            name: session.name,
            host: session.host,
            model: resolvedModel,
            permission_mode: permissionMode,
            effort,
            cli,
            fresh: mode === "reset",
            lang,
          });
        },
        session.name,
        t,
        confirmDiagFollowup,
      );
    }
    // Original: unconditionally closes + refreshes after the request
    // settles, success or failure alike (`optsFor = null;
    // optsChoice[name] = null; refresh();` right after the try/catch).
    onClose();
    refresh();
  }

  return (
    <tr className="opts-row">
      <td colSpan={colspan}>
        <div className="opts">
          {session.running && <span className="opts-hint">{t.runningNote(session.name)}</span>}
          <div className="modes">
            {modeChoices.map(([value, label]) => (
              <label className="mode-radio" key={value}>
                <input
                  type="radio"
                  name={`mode-${session.name}`}
                  value={value}
                  checked={mode === value}
                  onChange={() => setMode(value)}
                />{" "}
                {label}
              </label>
            ))}
          </div>
          <span className="opts-hint">{mode === "newchat" ? t.autoNameHint((session.instance && session.blueprint) || session.name, todayStr()) : ""}</span>
          <label>
            {t.cliLabel}
            <select value={cli} onChange={(e) => handleCliChange(e.target.value)}>
              {cliList.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <CliFields
            currentModelLabel={currentModelLabel}
            model={model}
            modelOther={modelOther}
            permissionMode={permissionMode}
            effort={effort}
            cliOptions={cliOptions}
            onModelChange={setModel}
            onModelOtherChange={setModelOther}
            onPermissionModeChange={setPermissionMode}
            onEffortChange={setEffort}
          />
          <button type="button" className="go" disabled={busy} onClick={() => void handleGo()}>
            {busy ? t.starting : modeLabels[mode]}
          </button>
          <button type="button" onClick={onClose}>
            {t.cancelBtn}
          </button>
        </div>
      </td>
    </tr>
  );
}
