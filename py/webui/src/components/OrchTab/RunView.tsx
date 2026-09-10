/**
 * TOBEDECIDED#15 Phase 1 — renders one run's detail, live (while
 * `OrchTab`'s `data.orch.active` names it) or historical (after it's
 * finished). `run` is fetched by the parent via `getOrchRun()` — this
 * component only renders, it never fetches on its own.
 */

import { useLang } from "../../i18n/LangContext";
import type { OrchRun } from "../../api/types";

interface RunViewProps {
  run: OrchRun | null;
  onCancel?: () => void;
}

const RESULT_COLOR: Record<string, string> = {
  ok: "var(--green)",
  timeout: "var(--red)",
  send_failed: "var(--red)",
  unreachable: "var(--red)",
  no_envelope: "var(--amber)",
  pending: "var(--muted)",
};

export function RunView({ run, onCancel }: RunViewProps) {
  const { t } = useLang();

  if (!run) return <span className="opts-hint">…</span>;

  const isLive = run.status === "working";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ".5rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: ".6rem", flexWrap: "wrap" }}>
        <b>{t.orchStatusLabel(run.status)}</b>
        <span className="opts-hint" style={{ flexBasis: "auto", minHeight: 0 }}>
          {t.orchTaskLabel}: {run.task}
        </span>
        {isLive && onCancel && (
          <button type="button" className="stop" onClick={onCancel}>
            {t.orchCancelRunBtn}
          </button>
        )}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: ".5rem" }}>
        {run.participants.map((p) => {
          const r = run.results.find((x) => x.host === p.host && x.name === p.name);
          const status = r ? r.status : isLive ? "pending" : null;
          return (
            <div
              key={`${p.host}:${p.name}`}
              style={{
                border: "1px solid var(--border)", borderRadius: "6px", background: "var(--panel2)",
                padding: ".5rem", flex: "1 1 220px", minWidth: "180px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: ".4rem" }}>
                <b>{p.name}</b>
                <span className="cli-badge">{p.cli}</span>
              </div>
              {status && (
                <div style={{ color: RESULT_COLOR[status] ?? "var(--muted)", fontSize: ".82rem" }}>
                  {t.orchResultStatusLabel(status)}
                  {r && r.elapsed > 0 ? ` · ${r.elapsed.toFixed(1)}s` : ""}
                </div>
              )}
              {r?.verdict && <div style={{ fontSize: ".82rem", marginTop: ".2rem" }}>{r.verdict}</div>}
              {r?.text && (
                <details style={{ fontSize: ".78rem", marginTop: ".2rem" }}>
                  <summary style={{ cursor: "pointer", color: "var(--muted)" }}>{t.orchViewBtn}</summary>
                  <div style={{ whiteSpace: "pre-wrap", marginTop: ".2rem" }}>{r.text}</div>
                </details>
              )}
            </div>
          );
        })}
      </div>
      {run.outcome && (
        <div className="opts-hint" style={{ flexBasis: "100%" }}>
          <b>{t.orchFinalLabel}</b> ({t.orchOutcomeMethodLabel(run.outcome.method)})
          {run.outcome.final ? `: ${run.outcome.final}` : ""}
          {run.outcome.tally.length > 0 && (
            <div>
              {t.orchTallyLabel}:{" "}
              {run.outcome.tally.map((ta) => `${ta.verdict_key} (${ta.votes}: ${ta.voters.join(", ")})`).join(" · ")}
            </div>
          )}
          {run.outcome.abstained.length > 0 && (
            <div>
              {t.orchAbstainedLabel}:{" "}
              {run.outcome.abstained.map((a) => `${a.name} (${t.orchResultStatusLabel(a.status)})`).join(", ")}
            </div>
          )}
          {run.outcome.note && <div>{run.outcome.note}</div>}
        </div>
      )}
    </div>
  );
}
