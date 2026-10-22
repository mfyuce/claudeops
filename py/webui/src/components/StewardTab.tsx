/**
 * Değnekçi (steward) tab — phase 3 of `docs/degnekci-plan.md`: three numbers, question cards
 * (answer by tapping an option or typing), the project list with each card's next step, and
 * the idea inbox. Self-contained like `OrchTab`: the light `data.steward` slice rides the
 * existing WS push; the full `/api/steward/state` is fetched only while this tab is mounted and
 * re-fetched when the pushed counts/last tick change (no polling timer of its own). Every write
 * goes through `/api/steward/*` (local-only, same data as `py/cops steward`).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  apiStewardAnswer,
  apiStewardAsk,
  apiStewardBrain,
  apiStewardConfig,
  apiStewardEnable,
  apiStewardIdea,
  apiStewardIdeaExport,
  apiStewardIdeaUpdate,
  apiStewardProjectSet,
  apiStewardProjectRemove,
  apiStewardShutdown,
  apiStewardUp,
  apiStewardIdentityCreate,
  apiStewardIdentityRemove,
  apiStewardIdentityTransfer,
  apiStewardTick,
  apiStewardTour,
  getStewardState,
} from "../api/client";
import { describeApiError } from "../api/errors";
import { StewardJobs } from "./StewardJobs";
import { ReviewPanel } from "./ReviewPanel";
import { StewardActions } from "./StewardActions";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import { showToast } from "../state/toast";
import type { StewardHostHealth, StewardQuestion, StewardStateResult } from "../api/types";

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

const SID_KEY = "claudeops.steward.sid";

const SETTING_FIELDS: { key: string; label: "stewardSetTick" | "stewardSetTour" | "stewardSetTourRetry" | "stewardSetIdle" | "stewardSetReview" | "stewardSetMaxActive" }[] = [
  { key: "tick_seconds", label: "stewardSetTick" },
  { key: "tour_minutes", label: "stewardSetTour" },
  { key: "tour_retry_minutes", label: "stewardSetTourRetry" },
  { key: "idle_minutes", label: "stewardSetIdle" },
  { key: "review_minutes", label: "stewardSetReview" },
  { key: "max_active", label: "stewardSetMaxActive" },
];

/** A number field that saves on Enter / blur when the value changed (the backend validates the range). */
function NumberSetting({ label, value, width, onSave }: { label: string; value: number; width?: string; onSave: (n: number) => void }) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  function commit() {
    const n = Number(text);
    if (text.trim() !== "" && Number.isFinite(n) && n !== value) onSave(n);
    else setText(String(value));
  }
  return (
    <label className="opts-hint" style={{ display: "inline-flex", gap: ".3rem", alignItems: "center" }}>
      {label}
      <input
        type="number"
        value={text}
        style={{ width: width ?? "5rem" }}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
      />
    </label>
  );
}

function readSid(): string {
  try {
    return localStorage.getItem(SID_KEY) || "default";
  } catch {
    return "default";
  }
}

/** `@host` badge for a remote project (nothing for local); a warning mark when the host is down or backing off. */
function HostBadge({ host, health }: { host?: string; health?: StewardHostHealth }) {
  const { t } = useLang();
  if (!host) return null;
  const bad = health && health.state !== "ok";
  const warn = health?.state === "backoff" ? t.stewardHostBackoff : t.stewardHostDown;
  return (
    <span className="cli-badge" style={{ marginLeft: ".3rem" }} title={bad ? warn : host}>
      @{host}
      {bad ? " ⚠" : ""}
    </span>
  );
}

function QuestionCard({ q, sid, health, onAnswered }: { q: StewardQuestion; sid: string; health?: StewardHostHealth; onAnswered: () => void }) {
  const { t } = useLang();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(answer: string) {
    const a = answer.trim();
    if (!a || busy) return;
    setBusy(true);
    try {
      const res = await apiStewardAnswer(q.id, a, sid);
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
        <b>{q.project || "degnekci"}</b>
        <HostBadge host={q.host} health={health} /> · {ago(q.created_at, t.stewardNever)}
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

export function StewardTab({ onOpenTerminal }: { onOpenTerminal?: (host: string, name: string) => void }) {
  const { t } = useLang();
  const { data, refresh } = useStatusContext();
  const [state, setState] = useState<StewardStateResult | null>(null);
  const [error, setError] = useState("");
  const [askText, setAskText] = useState("");
  const [askOptions, setAskOptions] = useState("");
  const [ideaText, setIdeaText] = useState("");
  const [exportTarget, setExportTarget] = useState<"project" | "all">("project");
  const [busy, setBusy] = useState(false);
  const [shutdownOpen, setShutdownOpen] = useState(false);
  const [keepSet, setKeepSet] = useState<Set<string>>(new Set());
  const [newId, setNewId] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [newRole, setNewRole] = useState("steward");
  const [newProject, setNewProject] = useState("");
  const [xferProject, setXferProject] = useState("");
  const [xferTo, setXferTo] = useState("");
  const [pickedSid, setPickedSid] = useState(readSid);

  // Identity rows (multi-steward, P6). One identity (or an older backend without the slice) = no picker, UI as before.
  const rows = data?.stewards;
  const multi = !!rows && rows.length > 1;
  // A stored id that no longer exists falls back to `default`; with a single identity the selection is always `default`.
  const sid = useMemo(() => (multi && rows.some((x) => x.id === pickedSid) ? pickedSid : "default"), [multi, rows, pickedSid]);

  const sidRef = useRef(sid);
  useEffect(() => {
    sidRef.current = sid;
  }, [sid]);

  function pick(id: string) {
    if (id === sid) return;
    setState(null);
    setError("");
    setPickedSid(id);
    try {
      localStorage.setItem(SID_KEY, id);
    } catch {
      /* private mode / blocked storage: the choice just is not remembered */
    }
  }

  // Same shape as `OrchTab`'s detail fetch: the promise's `.then` updates state (never synchronously in the effect).
  const load = useCallback(
    () =>
      getStewardState(sid).then(
        (res) => {
          if (sidRef.current !== sid) return; // identity switched while in flight: drop the stale answer
          if (res.ok) {
            setState(res);
            setError("");
          } else setError(t.requestFailed);
        },
        (e: unknown) => setError(describeApiError(e, t)),
      ),
    [t, sid],
  );

  // Re-fetch on the pushed light slice changing (counts / last tick), never on a timer.
  const sum = rows?.find((x) => x.id === sid) ?? data?.steward;
  const key = `${sum?.open_questions ?? 0}|${sum?.ideas_new ?? 0}|${sum?.pending_items ?? 0}|${data?.steward?.last_tick?.at ?? 0}|${sid}|${rows?.length ?? 0}|${sum?.mode ?? ""}|${sum?.enabled ?? ""}`;
  const isReviewer = rows?.find((x) => x.id === sid)?.role === "reviewer";
  useEffect(() => {
    if (!isReviewer) void load(); // a reviewer has no project/question state; ReviewPanel loads its own
  }, [load, key, isReviewer]);

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
  const pickerButtons = multi && (
    <div className="opts" role="group" aria-label={t.stewardPick}>
      {rows.map((x) => (
        <button
          key={x.id}
          type="button"
          className={x.id === sid ? "go" : undefined}
          aria-pressed={x.id === sid}
          onClick={() => pick(x.id)}
          title={t.stewardRowStat(x.project_count, x.open_questions)}
        >
          <span className={`dot ${x.brain?.running ? "on" : "off"}`} />
          {x.label || x.id} · {x.enabled ? t.stewardOn : t.stewardOffShort} · {x.mode}
          {x.role === "reviewer" ? " · reviewer" : `${x.role === "generic" ? " · generic" : ""} · ${t.stewardRowStat(x.project_count, x.open_questions)}`}
        </button>
      ))}
    </div>
  );
  if (isReviewer) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: ".8rem" }}>
        {pickerButtons}
        <ReviewPanel sid={sid} refreshKey={key} />
      </div>
    );
  }
  const s = state?.summary ?? (sid === "default" ? data.steward : null);
  const draining = (state?.config as Record<string, unknown> | undefined)?.drain === true;
  const projectsTotal = Object.values(s?.projects || {}).reduce((a, b) => a + b, 0);
  const phases = Object.entries(s?.projects || {})
    .filter(([, n]) => n > 0)
    .map(([ph, n]) => `${ph} ${n}`)
    .join(", ");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ".8rem" }}>
      <span className="opts-hint">{t.stewardDesc}</span>
      {pickerButtons}
      {s && !s.enabled && <div className="warn-banner">{t.stewardOff}</div>}
      {draining && <div className="warn-banner">{t.stewardDrainBanner}</div>}
      {state?.shutdown && (
        <div className="legend" style={{ margin: 0 }}>
          <b>{state.shutdown.cancelled ? t.stewardSdCancelled : state.shutdown.done ? t.stewardSdDone : t.stewardSdRunning}</b>
          {Object.entries(state.shutdown.items).map(([n, i]) => (
            <span key={n} className="cli-badge" style={{ marginLeft: ".3rem" }} title={i.blocked || undefined}>
              {n}: {i.stage}{i.blocked ? " ⚠" : ""}
            </span>
          ))}
        </div>
      )}
      {error && <div className="warn-banner">{error}</div>}

      {s && (
        <>
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
        <button type="button" disabled={busy} onClick={() => void run(() => apiStewardTick(sid))}>
          {t.stewardTickBtn}
        </button>
      </div>

      <div className="opts">
        <button type="button" disabled={busy} onClick={() => void run(() => apiStewardEnable(!s.enabled, sid))}>
          {s.enabled ? t.stewardCtlDisable : t.stewardCtlEnable}
        </button>
        <select
          value={s.mode}
          disabled={busy}
          aria-label="mode"
          onChange={(e) => void run(() => apiStewardConfig("mode", e.target.value, sid))}
        >
          <option value="observe">observe</option>
          <option value="act">act</option>
        </select>
        <button type="button" disabled={busy} onClick={() => void run(() => apiStewardBrain(s.brain?.running ? "stop" : "start", sid))}>
          {s.brain?.running ? t.stewardCtlBrainStop : t.stewardCtlBrainStart}
        </button>
        <button type="button" disabled={busy} title={t.stewardCtlUpHint} onClick={() => void run(() => apiStewardUp(sid))}>
          {t.stewardCtlUp}
        </button>
        <button type="button" disabled={busy} onClick={() => void run(() => apiStewardConfig("drain", draining ? "off" : "on", sid))}>
          {draining ? t.stewardCtlDrainOff : t.stewardCtlDrainOn}
        </button>
        <button type="button" disabled={busy} onClick={() => void run(() => apiStewardTour(sid))}>
          {t.stewardCtlTour}
        </button>
        <button
          type="button"
          className="retire"
          disabled={busy}
          onClick={() => setShutdownOpen((o) => !o)}
        >
          {t.stewardCtlShutdown}
        </button>
      </div>
      {shutdownOpen && (
        <div className="opts" style={{ flexDirection: "column", alignItems: "flex-start", gap: ".3rem" }}>
          <span className="opts-hint">{t.stewardCtlShutdownConfirm}</span>
          <span className="opts-hint">{t.stewardShutdownKeepHint}</span>
          {(state?.projects || []).filter((p) => p.running).map((p) => (
            <label key={p.name}>
              <input
                type="checkbox"
                checked={keepSet.has(p.name)}
                onChange={(e) => setKeepSet((cur) => { const n = new Set(cur); if (e.target.checked) n.add(p.name); else n.delete(p.name); return n; })}
              />{" "}
              {p.name} · {t.stewardShutdownKeepLabel}
            </label>
          ))}
          <span>
            <button
              type="button"
              className="retire"
              disabled={busy}
              onClick={() => {
                const keep = (state?.projects || []).filter((p) => p.running && keepSet.has(p.name)).map((p) => p.session?.name ?? p.name);
                setShutdownOpen(false);
                void run(() => apiStewardShutdown(sid, keep));
              }}
            >
              {t.stewardShutdownGo}
            </button>{" "}
            <button type="button" onClick={() => setShutdownOpen(false)}>{t.stewardShutdownCancel}</button>
          </span>
        </div>
      )}
      <details>
        <summary className="legend" style={{ cursor: "pointer", margin: 0 }}>{t.stewardSettingsTitle}</summary>
        <div className="opts" style={{ marginTop: ".4rem" }}>
          {SETTING_FIELDS.map((f) => {
            const v = Number((state?.config as Record<string, unknown> | undefined)?.[f.key]);
            return Number.isFinite(v) ? (
              <NumberSetting
                key={f.key}
                label={t[f.label]}
                value={v}
                onSave={(n) => void run(() => apiStewardConfig(f.key, n, sid), () => showToast(t.stewardSaved, "success"))}
              />
            ) : null;
          })}
        </div>
      </details>

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
        <QuestionCard key={q.id} q={q} sid={sid} health={q.host ? state.remote_hosts?.[q.host] : undefined} onAnswered={() => void load().then(refresh)} />
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
                    sid,
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

      <details>
        <summary className="legend" style={{ cursor: "pointer", margin: 0 }}>{t.stewardIdTitle}</summary>
        <div className="opts" style={{ marginTop: ".4rem", flexDirection: "column", alignItems: "flex-start", gap: ".4rem" }}>
          <span className="opts-hint">{t.stewardIdCreateHint}</span>
          <span>
            <input value={newId} placeholder={t.stewardIdNewPlaceholder} onChange={(e) => setNewId(e.target.value.toLowerCase())} maxLength={16} />{" "}
            <input value={newLabel} placeholder={t.stewardIdLabelPlaceholder} onChange={(e) => setNewLabel(e.target.value)} />{" "}
            <select value={newRole} onChange={(e) => setNewRole(e.target.value)} aria-label={t.stewardIdRole} title={t.stewardIdRole}>
              <option value="steward">steward</option>
              <option value="generic">generic</option>
              <option value="reviewer">reviewer</option>
            </select>{" "}
            <button
              type="button"
              disabled={busy || !newId.trim()}
              onClick={() => void run(() => apiStewardIdentityCreate(newId.trim(), newLabel.trim(), newRole), () => { setNewId(""); setNewLabel(""); setNewRole("steward"); showToast(t.stewardIdDone, "success"); })}
            >
              {t.stewardIdCreate}
            </button>
          </span>
          <span className="opts-hint">{t.stewardIdTransferHint}</span>
          <span>
            <select value={xferProject} onChange={(e) => setXferProject(e.target.value)} aria-label={t.stewardIdProject}>
              <option value="">{t.stewardIdProject}</option>
              {(state?.projects || []).filter((p) => !p.running).map((p) => (
                <option key={p.name} value={p.name}>{p.name}</option>
              ))}
            </select>{" "}
            <select value={xferTo} onChange={(e) => setXferTo(e.target.value)} aria-label={t.stewardIdTo}>
              <option value="">{t.stewardIdTo}</option>
              {(rows || []).filter((x) => x.id !== sid).map((x) => (
                <option key={x.id} value={x.id}>{x.label || x.id}</option>
              ))}
            </select>{" "}
            <button
              type="button"
              disabled={busy || !xferProject || !xferTo}
              onClick={() => void run(() => apiStewardIdentityTransfer(xferProject, xferTo), () => { setXferProject(""); showToast(t.stewardIdDone, "success"); })}
            >
              {t.stewardIdTransfer}
            </button>
          </span>
          {sid === "default" ? (
            <span className="opts-hint">{t.stewardIdDefaultKeep}</span>
          ) : (
            <button
              type="button"
              className="retire"
              disabled={busy}
              onClick={() => {
                if (window.confirm(t.stewardIdRemoveConfirm)) void run(() => apiStewardIdentityRemove(sid), () => pick("default"));
              }}
            >
              {t.stewardIdRemove}
            </button>
          )}
        </div>
      </details>

      <StewardActions sid={sid} projects={(state?.projects || []).map((p) => ({ name: p.name, running: !!p.running }))} />
      <StewardJobs sid={sid} projects={(state?.projects || []).map((p) => p.name)} />

      <h3 style={{ margin: ".4rem 0 0" }}>{t.stewardPendingTitle}</h3>
      {state && (state.pending?.length ?? 0) === 0 && <span className="opts-hint">{t.stewardNoPending}</span>}
      {state?.pending?.map((it, idx) => (
        <div key={`${it.kind}-${it.name}-${idx}`} className="legend" style={{ margin: 0 }}>
          <span className="cli-badge">{it.kind}</span> <b>{it.name}</b> {it.text}
        </div>
      ))}

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
                <th>{t.stewardColCadence}</th>
                <th>{t.stewardColNext}</th>
                <th>{t.stewardColVisit}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {state.projects.map((p) => (
                <tr key={p.name}>
                  <td>
                    <span className={`dot ${p.running ? "on" : "off"}`} />
                    {p.session && onOpenTerminal ? (
                      <button type="button" className="linkbtn" title={t.stewardOpenTerminal} onClick={() => onOpenTerminal(p.session?.host ?? "", p.session?.name ?? p.name)}>
                        {p.name}
                      </button>
                    ) : (
                      p.name
                    )}
                    <HostBadge host={p.host} health={p.host ? state.remote_hosts?.[p.host] : undefined} />
                    {p.kind && p.kind !== "other" ? <span className="cli-badge" style={{ marginLeft: ".3rem" }}>{p.kind}</span> : null}
                  </td>
                  <td>
                    <span className="phase-badge">{p.phase}</span>
                  </td>
                  <td>{p.priority}</td>
                  <td>
                    <NumberSetting
                      label=""
                      width="4.5rem"
                      value={p.cadence_minutes}
                      onSave={(n) => void run(() => apiStewardProjectSet(p.name, { cadence_minutes: n }, sid), () => showToast(t.stewardSaved, "success"))}
                    />
                  </td>
                  <td className="cwd" title={p.goal}>
                    {p.next_step || p.goal || "—"}
                  </td>
                  <td>{ago(p.last_visit, t.stewardNever)}</td>
                  <td>
                    <button
                      type="button"
                      className="closebtn"
                      disabled={busy}
                      onClick={() => {
                        if (window.confirm(t.stewardProjRemoveConfirm(p.name))) void run(() => apiStewardProjectRemove(p.name, sid), () => showToast(t.stewardSaved, "success"));
                      }}
                    >
                      {t.stewardProjRemove}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="opts">
        <input type="text" value={newProject} placeholder={t.stewardProjAddPlaceholder} onChange={(e) => setNewProject(e.target.value.trim())} />
        <button
          type="button"
          disabled={busy || !newProject}
          onClick={() => void run(() => apiStewardProjectSet(newProject, { phase: "planned" }, sid), () => { setNewProject(""); showToast(t.stewardSaved, "success"); })}
        >
          {t.stewardProjAdd}
        </button>
      </div>

      <h3 style={{ margin: ".4rem 0 0" }}>{t.stewardIdeasTitle}</h3>
      {state && state.ideas.length === 0 && <span className="opts-hint">{t.stewardNoIdeas}</span>}
      {state && state.ideas.length > 0 && (
        <label className="opts-hint">
          {t.stewardExportTarget}{" "}
          <select value={exportTarget} onChange={(e) => setExportTarget(e.target.value === "all" ? "all" : "project")}>
            <option value="project">{t.stewardExportProject}</option>
            <option value="all">{t.stewardExportAll}</option>
          </select>
        </label>
      )}
      {state?.ideas.map((i) => (
        <div key={i.id} className="opts" style={card}>
          <span style={{ flex: 1, minWidth: "12rem" }}>
            {i.text} <span className="legend">({ago(i.created_at, t.stewardNever)}{i.source ? `, ${i.source}` : ""})</span>
          </span>
          <button type="button" disabled={busy} title={t.stewardIdeaToTodoTitle} onClick={() => void run(() => apiStewardIdeaExport(i.id, "todo", exportTarget, sid), () => showToast(t.stewardIdeaExported))}>
            {t.stewardIdeaToTodo}
          </button>
          <button type="button" disabled={busy} title={t.stewardIdeaToTbdTitle} onClick={() => void run(() => apiStewardIdeaExport(i.id, "tbd", exportTarget, sid), () => showToast(t.stewardIdeaExported))}>
            {t.stewardIdeaToTbd}
          </button>
          <button type="button" className="retire" disabled={busy} onClick={() => void run(() => apiStewardIdeaUpdate(i.id, "later", sid))}>
            {t.stewardIdeaLater}
          </button>
          <button type="button" className="closebtn" disabled={busy} onClick={() => void run(() => apiStewardIdeaUpdate(i.id, "dropped", sid))}>
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
            if (e.key === "Enter" && ideaText.trim()) void run(() => apiStewardIdea(ideaText, sid), () => setIdeaText(""));
          }}
        />
        <button type="button" disabled={busy || !ideaText.trim()} onClick={() => void run(() => apiStewardIdea(ideaText, sid), () => setIdeaText(""))}>
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
                {r.host ? `@${r.host}` : ""}
                {r.dry ? ` (${t.stewardDry})` : ""}
                {r.ok === false ? ` ✗ ${r.detail ?? ""}` : ""}
                {r.reason ? ` — ${r.reason}` : ""}
              </div>
            ))}
          </div>
        </>
      )}
        </>
      )}
    </div>
  );
}
