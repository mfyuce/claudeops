/**
 * Değnekçi (steward) tab — phase 3 of `docs/degnekci-plan.md`: three numbers, question cards
 * (answer by tapping an option or typing), the project list with each card's next step, and
 * the idea inbox. Self-contained like `OrchTab`: the light `data.steward` slice rides the
 * existing WS push; the full `/api/steward/state` is fetched only while this tab is mounted and
 * re-fetched when the pushed counts/last tick change (no polling timer of its own). Every write
 * goes through `/api/steward/*` (local-only, same data as `py/cops steward`).
 */

import { useCallback, useEffect, useState } from "react";
import {
  apiStewardAnswer,
  apiStewardAsk,
  apiStewardIdea,
  apiStewardIdeaUpdate,
  apiStewardTick,
  getStewardState,
} from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import { showToast } from "../state/toast";
import type { StewardQuestion, StewardStateResult } from "../api/types";

function ago(ts: number | undefined, never: string): string {
  if (!ts) return never;
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

const tile: React.CSSProperties = {
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: ".5rem .8rem",
  minWidth: "6rem",
  background: "var(--panel)",
};
const card: React.CSSProperties = { border: "1px solid var(--border)", borderRadius: 8, padding: ".6rem .8rem", background: "var(--panel)" };

function QuestionCard({ q, onAnswered }: { q: StewardQuestion; onAnswered: () => void }) {
  const { t } = useLang();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(answer: string) {
    const a = answer.trim();
    if (!a || busy) return;
    setBusy(true);
    try {
      const res = await apiStewardAnswer(q.id, a);
      if (!res.ok) showToast(res.error || t.requestFailed);
      else {
        showToast(`${t.stewardAnswered}: ${res.question?.answer ?? a}`, "success");
        onAnswered();
      }
    } catch (e) {
      showToast(describeApiError(e, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={card}>
      <div className="legend" style={{ margin: 0 }}>
        <b>{q.project || "degnekci"}</b> · {ago(q.created_at, t.stewardNever)}
        {q.source ? ` · ${q.source}` : ""}
      </div>
      <div style={{ whiteSpace: "pre-wrap", margin: ".3rem 0 .5rem" }}>{q.text}</div>
      {q.options && q.options.length > 0 && (
        <div className="opts" style={{ marginBottom: ".4rem" }}>
          {q.options.map((o, i) => (
            <button key={o} type="button" className="go" disabled={busy} onClick={() => void send(o)}>
              {i + 1}) {o}
            </button>
          ))}
        </div>
      )}
      <div className="opts">
        <input
          type="text"
          value={text}
          placeholder={t.stewardAnswerPlaceholder}
          style={{ flex: 1, minWidth: "12rem" }}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void send(text);
          }}
        />
        <button type="button" disabled={busy || !text.trim()} onClick={() => void send(text)}>
          {t.stewardAnswerBtn}
        </button>
      </div>
    </div>
  );
}

export function StewardTab() {
  const { t } = useLang();
  const { data, refresh } = useStatusContext();
  const [state, setState] = useState<StewardStateResult | null>(null);
  const [error, setError] = useState("");
  const [askText, setAskText] = useState("");
  const [askOptions, setAskOptions] = useState("");
  const [ideaText, setIdeaText] = useState("");
  const [busy, setBusy] = useState(false);

  // Same shape as `OrchTab`'s detail fetch: the promise's `.then` updates state (never synchronously in the effect).
  const load = useCallback(
    () =>
      getStewardState().then(
        (res) => {
          if (res.ok) {
            setState(res);
            setError("");
          } else setError(t.requestFailed);
        },
        (e: unknown) => setError(describeApiError(e, t)),
      ),
    [t],
  );

  // Re-fetch on the pushed light slice changing (counts / last tick), never on a timer.
  const sum = data?.steward;
  const key = `${sum?.open_questions ?? 0}|${sum?.ideas_new ?? 0}|${sum?.pending_items ?? 0}|${sum?.last_tick?.at ?? 0}|${sum?.mode ?? ""}|${sum?.enabled ?? ""}`;
  useEffect(() => {
    void load();
  }, [load, key]);

  async function run<T extends { ok: boolean; error?: string }>(fn: () => Promise<T>, after?: (r: T) => void) {
    if (busy) return;
    setBusy(true);
    try {
      const r = await fn();
      if (!r.ok) showToast(r.error || t.requestFailed);
      else after?.(r);
    } catch (e) {
      showToast(describeApiError(e, t));
    } finally {
      setBusy(false);
      void load();
      refresh();
    }
  }

  if (!data) return null;
  const s = state?.summary ?? data.steward;
  const projectsTotal = Object.values(s.projects || {}).reduce((a, b) => a + b, 0);
  const phases = Object.entries(s.projects || {})
    .filter(([, n]) => n > 0)
    .map(([ph, n]) => `${ph} ${n}`)
    .join(", ");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ".8rem" }}>
      <span className="opts-hint">{t.stewardDesc}</span>
      {!s.enabled && <div className="warn-banner">{t.stewardOff}</div>}
      {error && <div className="warn-banner">{error}</div>}

      <div className="opts">
        <span className="cli-badge">{t.stewardMode(s.mode)}</span>
        <span className="legend" style={{ margin: 0 }}>
          {s.last_tick?.at ? t.stewardLastTick(ago(s.last_tick.at, t.stewardNever)) : t.stewardNoTick}
          {s.last_tick?.error ? ` ⚠ ${s.last_tick.error}` : ""}
        </span>
        <span className="legend" style={{ margin: 0 }}>
          <span className={`dot ${s.brain?.running ? "on" : "off"}`} />
          {t.stewardBrain} {s.brain?.name}
        </span>
        <button type="button" disabled={busy} onClick={() => void run(apiStewardTick)}>
          {t.stewardTickBtn}
        </button>
      </div>

      <div className="opts">
        <div style={tile}>
          <div style={{ fontSize: "1.4rem", fontWeight: 600 }}>{s.open_questions}</div>
          <div className="legend" style={{ margin: 0 }}>{t.stewardStatQuestions}</div>
        </div>
        <div style={tile}>
          <div style={{ fontSize: "1.4rem", fontWeight: 600 }}>{s.ideas_new}</div>
          <div className="legend" style={{ margin: 0 }}>{t.stewardStatIdeas}</div>
        </div>
        <div style={tile}>
          <div style={{ fontSize: "1.4rem", fontWeight: 600 }}>{s.pending_items}</div>
          <div className="legend" style={{ margin: 0 }}>{t.stewardStatPending}</div>
        </div>
        <div style={tile}>
          <div style={{ fontSize: "1.4rem", fontWeight: 600 }}>{projectsTotal}</div>
          <div className="legend" style={{ margin: 0 }}>
            {t.stewardStatProjects}
            {phases ? ` (${phases})` : ""}
          </div>
        </div>
      </div>

      <h3 style={{ margin: ".4rem 0 0" }}>{t.stewardQuestionsTitle}</h3>
      {state && state.questions.length === 0 && <span className="opts-hint">{t.stewardNoQuestions}</span>}
      {state?.questions.map((q) => (
        <QuestionCard key={q.id} q={q} onAnswered={() => void load().then(refresh)} />
      ))}
      <details>
        <summary className="legend" style={{ cursor: "pointer", margin: 0 }}>{t.stewardAskTitle}</summary>
        <div className="opts" style={{ marginTop: ".4rem" }}>
          <input
            type="text"
            value={askText}
            placeholder={t.stewardAskPlaceholder}
            style={{ flex: 2, minWidth: "14rem" }}
            onChange={(e) => setAskText(e.target.value)}
          />
          <input
            type="text"
            value={askOptions}
            placeholder={t.stewardAskOptionsPlaceholder}
            style={{ flex: 2, minWidth: "14rem" }}
            onChange={(e) => setAskOptions(e.target.value)}
          />
          <button
            type="button"
            disabled={busy || !askText.trim()}
            onClick={() =>
              void run(
                () =>
                  apiStewardAsk(
                    "",
                    askText,
                    askOptions
                      .split(",")
                      .map((o) => o.trim())
                      .filter(Boolean),
                  ),
                () => {
                  setAskText("");
                  setAskOptions("");
                },
              )
            }
          >
            {t.stewardAskBtn}
          </button>
        </div>
      </details>

      <h3 style={{ margin: ".4rem 0 0" }}>{t.stewardProjectsTitle}</h3>
      {state && state.projects.length === 0 && <span className="opts-hint">{t.stewardNoProjects}</span>}
      {state && state.projects.length > 0 && (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>{t.stewardColProject}</th>
                <th>{t.stewardColPhase}</th>
                <th>{t.stewardColPriority}</th>
                <th>{t.stewardColNext}</th>
                <th>{t.stewardColVisit}</th>
              </tr>
            </thead>
            <tbody>
              {state.projects.map((p) => (
                <tr key={p.name}>
                  <td>
                    <span className={`dot ${p.running ? "on" : "off"}`} />
                    {p.name}
                    {p.kind && p.kind !== "other" ? <span className="cli-badge" style={{ marginLeft: ".3rem" }}>{p.kind}</span> : null}
                  </td>
                  <td>
                    <span className="phase-badge">{p.phase}</span>
                  </td>
                  <td>{p.priority}</td>
                  <td className="cwd" title={p.goal}>
                    {p.next_step || p.goal || "—"}
                  </td>
                  <td>{ago(p.last_visit, t.stewardNever)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 style={{ margin: ".4rem 0 0" }}>{t.stewardIdeasTitle}</h3>
      {state && state.ideas.length === 0 && <span className="opts-hint">{t.stewardNoIdeas}</span>}
      {state?.ideas.map((i) => (
        <div key={i.id} className="opts" style={card}>
          <span style={{ flex: 1, minWidth: "12rem" }}>
            {i.text} <span className="legend">({ago(i.created_at, t.stewardNever)}{i.source ? `, ${i.source}` : ""})</span>
          </span>
          <button type="button" className="retire" disabled={busy} onClick={() => void run(() => apiStewardIdeaUpdate(i.id, "later"))}>
            {t.stewardIdeaLater}
          </button>
          <button type="button" className="closebtn" disabled={busy} onClick={() => void run(() => apiStewardIdeaUpdate(i.id, "dropped"))}>
            {t.stewardIdeaDrop}
          </button>
        </div>
      ))}
      <div className="opts">
        <input
          type="text"
          value={ideaText}
          placeholder={t.stewardIdeaPlaceholder}
          style={{ flex: 1, minWidth: "14rem" }}
          onChange={(e) => setIdeaText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && ideaText.trim()) void run(() => apiStewardIdea(ideaText), () => setIdeaText(""));
          }}
        />
        <button type="button" disabled={busy || !ideaText.trim()} onClick={() => void run(() => apiStewardIdea(ideaText), () => setIdeaText(""))}>
          {t.stewardIdeaAddBtn}
        </button>
      </div>

      {s.recent && s.recent.length > 0 && (
        <>
          <h3 style={{ margin: ".4rem 0 0" }}>{t.stewardRecentTitle}</h3>
          <div className="legend" style={{ margin: 0 }}>
            {(state?.recent ?? s.recent).slice(0, 12).map((r, idx) => (
              <div key={`${r.ts}-${idx}`}>
                {ago(r.ts, t.stewardNever)} · {r.kind} {r.name}
                {r.dry ? ` (${t.stewardDry})` : ""}
                {r.ok === false ? ` ✗ ${r.detail ?? ""}` : ""}
                {r.reason ? ` — ${r.reason}` : ""}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
