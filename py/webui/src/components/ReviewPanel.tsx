/**
 * Reviewer identity panel (steward role `reviewer`, `/api/steward/review/*`): project x model matrix, pool toggles,
 * manual runs, running jobs, review file viewer and the findings flow (verify / approve / reject / export).
 * Shown by `StewardTab` instead of the normal project panels. No timer of its own: `refreshKey` is the parent's
 * `data.steward` WS-slice key, a change re-fetches; every write re-fetches once.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  apiReviewCancel,
  apiReviewExport,
  apiReviewFinding,
  apiReviewPool,
  apiReviewRun,
  apiReviewVerify,
  getReviewFile,
  getReviewFindings,
  getReviewState,
} from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { showToast } from "../state/toast";
import type { ReviewFinding, ReviewPair, ReviewStateResult } from "../api/types";

const STATUS_COLOR: Record<string, string> = {
  done: "#2e9d57",
  partial: "#d19a1e",
  error: "#d1453b",
  model_fallback: "#c4631f",
  running: "#3b82d1",
};
const FINDING_STATES = ["new", "verify_sent", "verified", "refuted", "unclear", "approved", "rejected", "exported"];

function when(ts: number | undefined, never: string): string {
  if (!ts) return never;
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

const card: React.CSSProperties = { border: "1px solid var(--border)", borderRadius: 8, padding: ".5rem .7rem", background: "var(--panel)" };

export function ReviewPanel({ sid, refreshKey }: { sid: string; refreshKey: string }) {
  const { t } = useLang();
  const [st, setSt] = useState<ReviewStateResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [newProject, setNewProject] = useState("");
  const [file, setFile] = useState<{ path: string; text: string; truncated: boolean } | null>(null);
  const [fProject, setFProject] = useState("");
  const [fState, setFState] = useState("");
  const [findings, setFindings] = useState<ReviewFinding[]>([]);
  const sidRef = useRef(sid);
  useEffect(() => {
    sidRef.current = sid;
  }, [sid]);

  const load = useCallback(
    () =>
      Promise.all([getReviewState(sid), getReviewFindings(sid, fProject, fState)]).then(
        ([s, f]) => {
          if (sidRef.current !== sid) return;
          if (s.ok) {
            setSt(s);
            setError("");
          } else setError(s.error || t.requestFailed);
          if (f.ok) setFindings(f.findings ?? []);
        },
        (e: unknown) => setError(describeApiError(e, t)),
      ),
    [sid, fProject, fState, t],
  );
  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  async function act(fn: () => Promise<{ ok: boolean; error?: string }>, okText?: string, after?: () => void) {
    if (busy) return;
    setBusy(true);
    try {
      const r = await fn();
      if (!r.ok) showToast(r.error || t.requestFailed);
      else {
        if (okText) showToast(okText, "success");
        after?.();
      }
    } catch (e) {
      showToast(describeApiError(e, t));
    } finally {
      setBusy(false);
      void load();
    }
  }

  async function openFile(path: string) {
    try {
      const r = await getReviewFile(sid, path);
      if (r.ok) setFile({ path: r.path ?? path, text: r.text ?? "", truncated: !!r.truncated });
      else showToast(r.error || t.requestFailed);
    } catch (e) {
      showToast(describeApiError(e, t));
    }
  }

  const targets = st?.targets ?? [];
  const running = st?.running ?? [];
  const projects = (st?.pool ?? []).map((r) => r.project);
  const exportProjects = Array.from(new Set(findings.filter((f) => f.state === "approved").map((f) => f.project)));

  function Cell({ project, tk, mode, model, pair }: { project: string; tk: string; mode: string; model: string; pair: ReviewPair | null | undefined }) {
    const status = pair?.status ?? "";
    const color = STATUS_COLOR[status];
    return (
      <td style={{ whiteSpace: "nowrap" }}>
        <span
          className="cli-badge"
          style={color ? { borderColor: color, color } : undefined}
          title={[status, pair?.error, pair?.label_seen ? `label: ${pair.label_seen}` : ""].filter(Boolean).join(" · ") || undefined}
        >
          {status || "—"} {when(pair?.finished_at ?? pair?.started_at, t.rvNever)}
        </span>{" "}
        {pair?.file && (
          <button type="button" className="linkbtn" title={t.rvOpenFile} onClick={() => void openFile(pair.file as string)}>
            ⎘
          </button>
        )}
        <button
          type="button"
          className="linkbtn"
          title={`${t.rvRunTitle}: ${tk}`}
          disabled={busy || status === "running" || running.includes(`${project}|${tk}`)}
          onClick={() => void act(() => apiReviewRun(sid, project, mode, model), t.rvDone)}
        >
          ▶
        </button>
      </td>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ".8rem", minWidth: 0 }}>
      <h3 style={{ margin: 0 }}>{t.rvTitle}</h3>
      <span className="opts-hint">{t.rvDesc}</span>
      {st && !st.enabled && <div className="warn-banner">{t.rvOff}</div>}
      {error && <div className="warn-banner">{error}</div>}

      {st && st.pool.length === 0 && <span className="opts-hint">{t.rvNoPool}</span>}
      {st && targets.length === 0 && <span className="opts-hint">{t.rvNoTargets}</span>}
      {st && st.pool.length > 0 && (
        <div className="tablewrap" style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>{t.rvEnabled}</th>
                <th>{t.rvProject}</th>
                {targets.map((tg) => (
                  <th key={tg.key} title={tg.key}>
                    {tg.mode}:{tg.slug || tg.model}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {st.pool.map((row) => (
                <tr key={row.project}>
                  <td>
                    <input
                      type="checkbox"
                      checked={row.enabled}
                      disabled={busy}
                      aria-label={`${t.rvEnabled}: ${row.project}`}
                      onChange={(e) => void act(() => apiReviewPool(sid, e.target.checked ? "enable" : "disable", row.project))}
                    />
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <b>{row.project}</b>
                    {row.complete && (
                      <span className="cli-badge" style={{ marginLeft: ".3rem", borderColor: STATUS_COLOR.done, color: STATUS_COLOR.done }}>
                        ✓ {t.rvComplete}
                      </span>
                    )}{" "}
                    <button type="button" className="linkbtn" disabled={busy} onClick={() => void act(() => apiReviewPool(sid, "remove", row.project))}>
                      {t.rvRemove}
                    </button>
                  </td>
                  {targets.map((tg) => (
                    <Cell key={tg.key} project={row.project} tk={tg.key} mode={tg.mode} model={tg.model} pair={row.pairs[tg.key]} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="opts">
        <input
          type="text"
          value={newProject}
          placeholder={t.rvPoolAdd}
          style={{ flex: 1, minWidth: "10rem" }}
          onChange={(e) => setNewProject(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && newProject.trim()) void act(() => apiReviewPool(sid, "add", newProject.trim()), undefined, () => setNewProject(""));
          }}
        />
        <button type="button" disabled={busy || !newProject.trim()} onClick={() => void act(() => apiReviewPool(sid, "add", newProject.trim()), undefined, () => setNewProject(""))}>
          {t.rvAddBtn}
        </button>
      </div>

      <h4 style={{ margin: 0 }}>{t.rvRunning}</h4>
      {running.length === 0 && <span className="opts-hint">{t.rvNoRunning}</span>}
      {running.length > 0 && (
        <div className="opts">
          {running.map((k) => (
            <span key={k} className="cli-badge" style={{ borderColor: STATUS_COLOR.running, color: STATUS_COLOR.running, overflowWrap: "anywhere" }}>
              {k}
            </span>
          ))}
          <button type="button" className="retire" disabled={busy} onClick={() => void act(() => apiReviewCancel(sid, ""), t.rvDone)}>
            {t.rvCancelAll}
          </button>
          {Array.from(new Set(running.map((k) => k.split("|")[0]))).map((p) => (
            <button key={p} type="button" disabled={busy} onClick={() => void act(() => apiReviewCancel(sid, p), t.rvDone)}>
              {t.rvCancel} {p}
            </button>
          ))}
        </div>
      )}

      {file && (
        <div style={card}>
          <div className="opts">
            <b style={{ overflowWrap: "anywhere" }}>{file.path}</b>
            {file.truncated && <span className="legend">{t.rvTruncated}</span>}
            <button type="button" onClick={() => setFile(null)}>
              {t.rvFileClose}
            </button>
          </div>
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: "28rem", overflow: "auto", margin: ".4rem 0 0" }}>{file.text}</pre>
        </div>
      )}

      <h4 style={{ margin: 0 }}>{t.rvFindings}</h4>
      <div className="opts">
        <select value={fProject} onChange={(e) => setFProject(e.target.value)} aria-label={t.rvProject}>
          <option value="">{t.rvAllProjects}</option>
          {projects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select value={fState} onChange={(e) => setFState(e.target.value)} aria-label="state">
          <option value="">{t.rvAllStates}</option>
          {FINDING_STATES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {fProject && (
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              void act(() => apiReviewVerify(sid, fProject, findings.filter((f) => ["new", "verify_sent", "unclear"].includes(f.state)).map((f) => f.id)), t.rvVerifySent)
            }
          >
            {t.rvVerify}
          </button>
        )}
        {exportProjects.map((p) =>
          (["todo", "tbd"] as const).map((kind) => (
            <button key={`${p}-${kind}`} type="button" disabled={busy} onClick={() => void act(() => apiReviewExport(sid, p, kind), `${t.rvExported}: ${p}`)}>
              {p}: {kind === "todo" ? t.rvExportTodo : t.rvExportTbd}
            </button>
          )),
        )}
      </div>
      {findings.length === 0 && <span className="opts-hint">{t.rvNoFindings}</span>}
      {findings.map((f) => (
        <div key={f.id} style={card}>
          <div className="legend" style={{ margin: 0, overflowWrap: "anywhere" }}>
            <b>{f.project}</b> · {f.ref} · {f.severity} · <span className="cli-badge">{f.state}</span>
            {f.where ? ` · ${f.where}` : ""}
          </div>
          <div style={{ margin: ".3rem 0", overflowWrap: "anywhere" }}>{f.title}</div>
          {f.verdict && <div className="legend" style={{ overflowWrap: "anywhere" }}>{f.verdict}</div>}
          <div className="opts">
            <button type="button" className="linkbtn" onClick={() => void openFile(f.review_file)}>
              {t.rvOpenFile}
            </button>
            <button
              type="button"
              disabled={busy || !["new", "verify_sent", "unclear"].includes(f.state)}
              onClick={() => void act(() => apiReviewVerify(sid, f.project, [f.id]), t.rvVerifySent)}
            >
              {t.rvVerify}
            </button>
            <button
              type="button"
              className="go"
              disabled={busy || !["verified", "unclear"].includes(f.state)}
              title={f.state === "refuted" ? t.rvRefutedHint : undefined}
              onClick={() => void act(() => apiReviewFinding(sid, f.id, "approve"))}
            >
              {t.rvApprove}
            </button>
            <button
              type="button"
              className="retire"
              disabled={busy || !["new", "verify_sent", "verified", "refuted", "unclear"].includes(f.state)}
              onClick={() => void act(() => apiReviewFinding(sid, f.id, "reject"))}
            >
              {t.rvReject}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
