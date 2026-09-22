/**
 * Replaces `renderDiagBox()` + `fmtUptime()` + `doDiagTest`/
 * `doDiagRestartGt`/`doDiagAsk`/`loadDiagLog()` (web.py ~2577-2721).
 *
 * `loadDiagLog()` in the original fires once per `renderDiagBox()` call,
 * i.e. once per tab-entry (the 4s `render()` poll only rebuilds the diag
 * tab's HTML while it's the active tab, and each rebuild re-triggers the
 * load) — never on a timer of its own. Here that's a mount effect: `App`
 * only mounts this component while `activeTab === 'diag'` (conditional
 * render, unmounted otherwise), so "runs once on mount" already matches
 * "runs once per tab-entry" without tying it to `StatusContext` at all.
 *
 * `#diag-result` is ONE `<pre>` shared by both the spawn-test and
 * restart-gt actions in the original (each just overwrites whatever the
 * other last wrote) — reproduced here as a single `diagResult` state used
 * by both `handleTest`/`handleRestartGt`, even though each action still
 * tracks its OWN busy/disabled state independently (matches
 * `btn.disabled`/`btn.textContent` being per-button in the original).
 * `#diag-ask-result` and the log tail are genuinely separate state.
 *
 * 2026-09-17: split into 3 sub-tabs (user: "settingsve diagnostics i
 * tablara veya parcalara bolelim") - "status" (handover-msg copy + web/gt
 * uptime + test/restart, i.e. "check/fix the panel's own health"), "ask"
 * (start a diagnostic CLI session), "log" (the raw diag.log tail). Each
 * was already visually separate; this just stops them all sharing one
 * long scroll. `logLines`/`loadLog` stay mount-effect-driven regardless of
 * which sub-tab is active (matches this file's existing "runs once per
 * tab-entry" reasoning above) rather than only fetching once "log" is
 * selected, so the log is already warm if the user switches to it.
 */

import { useCallback, useEffect, useState } from "react";
import { apiDiagAsk, apiDiagRestartGt, apiDiagSpawnTest, apiUcliAsk, ApiError, getDiagLog } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import { TabHint } from "./shared/TabHint";

type DiagSubTab = "status" | "ask" | "ucli" | "log";

/** Original: `fmtUptime(sec)` (web.py ~2577-2584). */
function fmtUptime(sec: number | null | undefined, unknownLabel: string): string {
  if (sec == null) return unknownLabel;
  const total = Math.max(0, Math.floor(sec));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
}

interface DiagnosticsTabProps {
  /** Original: `doDiagAsk()` success → `setTab('running'); await refresh();
   * toggleTerm(d.name)`. `App` owns both the active tab and
   * `openTerminalFor`, so it composes those two calls into this one
   * callback — see `App.tsx`'s `handleDiagAskSuccess`. */
  onAskSuccess: (name: string) => void;
}

export function DiagnosticsTab({ onAskSuccess }: DiagnosticsTabProps) {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();

  const [subTab, setSubTab] = useState<DiagSubTab>("status");
  const [testBusy, setTestBusy] = useState(false);
  const [restartBusy, setRestartBusy] = useState(false);
  const [diagResult, setDiagResult] = useState("");

  const [askCli, setAskCli] = useState<string | null>(null);
  const [askQuestion, setAskQuestion] = useState("");
  const [askBusy, setAskBusy] = useState(false);
  const [askResult, setAskResult] = useState("");

  const [ucliPrompt, setUcliPrompt] = useState("");
  const [ucliModel, setUcliModel] = useState("");
  const [ucliEndpoint, setUcliEndpoint] = useState("");
  const [ucliApiKey, setUcliApiKey] = useState("");
  const [ucliSession, setUcliSession] = useState("");
  const [ucliBusy, setUcliBusy] = useState(false);
  const [ucliResult, setUcliResult] = useState("");

  const [logLines, setLogLines] = useState<string[] | null>(null);

  const [handoverCopyLabel, setHandoverCopyLabel] = useState<string | null>(null);

  const loadLog = useCallback(async () => {
    try {
      const d = await getDiagLog();
      setLogLines(d.lines || []);
    } catch {
      setLogLines([]);
    }
  }, []);

  useEffect(() => {
    void loadLog();
  }, [loadLog]);

  if (!data) return null;

  const cliList = data.cli_list;
  const effectiveAskCli = askCli ?? cliList[0] ?? "";
  const runningCount = data.sessions.filter((s) => s.running).length;
  const diag = data.diag;
  const gtLine = diag.gt
    ? `${t.diagGtUptime}: pid ${diag.gt.pid} — ${fmtUptime(diag.gt.uptime_seconds, t.diagUptimeUnknown)}`
    : `${t.diagGtUptime}: ${t.diagGtNotFound}`;
  const webLine = `${t.diagWebUptime}: pid ${diag.web_pid ?? "?"} — ${fmtUptime(diag.web_uptime_seconds, t.diagUptimeUnknown)}`;
  const windowless = diag.windowless ?? [];

  async function handleTest() {
    setTestBusy(true);
    setDiagResult("");
    try {
      const res = await apiDiagSpawnTest(lang);
      if (res.ok) setDiagResult(t.diagTestOk);
      else if ("stderr" in res && res.stderr) setDiagResult(t.diagTestFailStderr(res.stderr));
      else if ("detail" in res && res.detail) setDiagResult(`✗ ${res.detail}`);
      else setDiagResult(t.diagTestFailWindow);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) window.alert(t.authErrorShort);
      else setDiagResult(`✗ ${describeApiError(e, t)}`);
    }
    setTestBusy(false);
    void loadLog();
    refresh();
  }

  async function handleRestartGt() {
    if (!window.confirm(t.diagRestartConfirm(runningCount))) return;
    setRestartBusy(true);
    setDiagResult("");
    try {
      const res = await apiDiagRestartGt(lang);
      setDiagResult(res.ok ? t.diagRestartDone(res.result) : `✗ ${res.error}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) window.alert(t.authErrorShort);
      else setDiagResult(`✗ ${describeApiError(e, t)}`);
    }
    setRestartBusy(false);
    void loadLog();
    refresh();
  }

  // TODO L85 (2026-09-01, user: "UI'ye Handover textini o an hangi dil
  // seçili ise o dilde göster, oradan copy paste yaparız, ayrı cli
  // açmadan" — show the handover text in whichever language is currently
  // selected, so it can be copy-pasted from there without opening a
  // separate CLI). `data.handover_msg` carries both languages (same text
  // `_handover()` actually sends) — this just picks the active one and
  // copies it, same clipboard pattern as `UrlBanner`'s copy button.
  async function handleCopyHandoverMsg() {
    if (!data) return; // narrowing from the top-level `if (!data) return null;` guard doesn't carry into this closure
    try {
      await navigator.clipboard.writeText(data.handover_msg[lang]);
      setHandoverCopyLabel(t.termCopied);
      window.setTimeout(() => setHandoverCopyLabel(null), 1200);
    } catch (e) {
      window.alert(t.requestFailed + (e instanceof Error ? e.message : String(e)));
    }
  }

  async function handleAsk() {
    setAskBusy(true);
    setAskResult("");
    try {
      const res = await apiDiagAsk({ cli: effectiveAskCli, extra_question: askQuestion, lang });
      if (res.ok) {
        setAskResult(t.diagAskStarted(res.name));
        refresh();
        onAskSuccess(res.name);
      } else {
        setAskResult(`✗ ${res.error}`);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) window.alert(t.authErrorShort);
      else setAskResult(`✗ ${describeApiError(e, t)}`);
    }
    setAskBusy(false);
    void loadLog();
    refresh();
  }

  async function handleUcliAsk() {
    setUcliBusy(true);
    setUcliResult("");
    try {
      const res = await apiUcliAsk({
        prompt: ucliPrompt,
        model: ucliModel,
        endpoint: ucliEndpoint,
        api_key: ucliApiKey,
        session: ucliSession,
      });
      setUcliResult(res.ok ? t.diagUcliResult(res.answer, res.model_rounds, res.tool_calls) : `✗ ${res.error}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) window.alert(t.authErrorShort);
      else setUcliResult(`✗ ${describeApiError(e, t)}`);
    }
    setUcliBusy(false);
  }

  return (
    <>
      <div className="tabs">
        <button type="button" className={subTab === "status" ? "active" : ""} onClick={() => setSubTab("status")}>
          {t.tabDiagStatus}
        </button>
        <button type="button" className={subTab === "ask" ? "active" : ""} onClick={() => setSubTab("ask")}>
          {t.tabDiagAsk}
        </button>
        <button type="button" className={subTab === "ucli" ? "active" : ""} onClick={() => setSubTab("ucli")}>
          {t.tabDiagUcli}
        </button>
        <button type="button" className={subTab === "log" ? "active" : ""} onClick={() => setSubTab("log")}>
          {t.tabDiagLog}
        </button>
      </div>
      {subTab === "status" && (
        <>
          <div className="opts-hint">{t.handoverMsgTitle}</div>
          <TabHint>{t.handoverMsgHint}</TabHint>
          <pre className="layout-result" style={{ maxHeight: "12rem", overflowY: "auto", border: "1px solid var(--border)", borderRadius: "4px", padding: ".5rem" }}>
            {data.handover_msg[lang]}
          </pre>
          <div className="opts" style={{ marginBottom: ".6rem" }}>
            <button type="button" onClick={() => void handleCopyHandoverMsg()}>
              {handoverCopyLabel ?? t.termCopyBtn}
            </button>
          </div>
          <div className="opts" id="diagPanel">
            <TabHint>{t.diagDesc}</TabHint>
            <div style={{ flexBasis: "100%" }}>
              {webLine}
              <br />
              {gtLine}
            </div>
            {windowless.length > 0 && (
              <div className="opts-hint" style={{ color: "var(--amber)", flexBasis: "100%" }}>
                {t.diagWindowless(windowless.join(", "))}
              </div>
            )}
            <button type="button" className="go" disabled={testBusy} onClick={() => void handleTest()}>
              {testBusy ? t.diagTesting : t.diagTestBtn}
            </button>
            <button type="button" className="stop" disabled={restartBusy} onClick={() => void handleRestartGt()}>
              {restartBusy ? t.diagRestarting : t.diagRestartBtn}
            </button>
          </div>
          <pre className="layout-result">{diagResult}</pre>
        </>
      )}
      {subTab === "ask" && (
        <>
          <div className="opts" id="diagAskPanel">
            <label>
              {t.diagAskCliLabel}
              <select value={effectiveAskCli} onChange={(e) => setAskCli(e.target.value)}>
                {cliList.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ flexBasis: "100%" }}>
              {t.diagAskQuestionLabel}
              <input
                type="text"
                placeholder={t.diagAskQuestionPlaceholder}
                value={askQuestion}
                onChange={(e) => setAskQuestion(e.target.value)}
              />
            </label>
            <button type="button" className="go" disabled={askBusy} onClick={() => void handleAsk()}>
              {askBusy ? t.diagAsking : t.diagAskBtn}
            </button>
          </div>
          <pre className="layout-result">{askResult}</pre>
        </>
      )}
      {subTab === "ucli" && (
        <>
          <div className="opts" id="ucliAskPanel">
            <TabHint>{t.diagUcliHint}</TabHint>
            <label style={{ flexBasis: "100%" }}>
              {t.diagUcliPromptLabel}
              <input
                type="text"
                placeholder={t.diagUcliPromptPlaceholder}
                value={ucliPrompt}
                onChange={(e) => setUcliPrompt(e.target.value)}
              />
            </label>
            <label>
              {t.diagUcliModelLabel}
              <input
                type="text"
                placeholder="deepseek-v4-flash"
                value={ucliModel}
                onChange={(e) => setUcliModel(e.target.value)}
              />
            </label>
            <label>
              {t.diagUcliEndpointLabel}
              <input
                type="text"
                placeholder={t.diagUcliEndpointPlaceholder}
                value={ucliEndpoint}
                onChange={(e) => setUcliEndpoint(e.target.value)}
              />
            </label>
            <label>
              {t.diagUcliApiKeyLabel}
              <input
                type="password"
                autoComplete="off"
                value={ucliApiKey}
                onChange={(e) => setUcliApiKey(e.target.value)}
              />
            </label>
            <label>
              {t.diagUcliSessionLabel}
              <input
                type="text"
                placeholder={t.diagUcliSessionPlaceholder}
                value={ucliSession}
                onChange={(e) => setUcliSession(e.target.value)}
              />
            </label>
            <button type="button" className="go" disabled={ucliBusy || !ucliPrompt.trim()} onClick={() => void handleUcliAsk()}>
              {ucliBusy ? t.diagUcliAsking : t.diagUcliBtn}
            </button>
          </div>
          <pre className="layout-result">{ucliResult}</pre>
        </>
      )}
      {subTab === "log" && (
        <>
          <div className="opts-hint">{t.diagLogTitle}</div>
          <pre className="layout-result">{logLines === null ? t.diagLogLoading : logLines.length ? logLines.join("\n") : t.empty}</pre>
          <div className="opts-hint">{t.diagRefreshHint}</div>
        </>
      )}
    </>
  );
}
