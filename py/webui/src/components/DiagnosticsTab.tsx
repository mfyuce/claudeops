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
 */

import { useCallback, useEffect, useState } from "react";
import { apiDiagAsk, apiDiagRestartGt, apiDiagSpawnTest, ApiError, getDiagLog } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";

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

  const [testBusy, setTestBusy] = useState(false);
  const [restartBusy, setRestartBusy] = useState(false);
  const [diagResult, setDiagResult] = useState("");

  const [askCli, setAskCli] = useState<string | null>(null);
  const [askQuestion, setAskQuestion] = useState("");
  const [askBusy, setAskBusy] = useState(false);
  const [askResult, setAskResult] = useState("");

  const [logLines, setLogLines] = useState<string[] | null>(null);

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

  return (
    <>
      <div className="opts-hint">{t.diagDesc}</div>
      <div className="opts" id="diagPanel">
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
      <div className="opts-hint">{t.diagLogTitle}</div>
      <pre className="layout-result">{logLines === null ? t.diagLogLoading : logLines.length ? logLines.join("\n") : t.empty}</pre>
      <div className="opts-hint">{t.diagRefreshHint}</div>
    </>
  );
}
