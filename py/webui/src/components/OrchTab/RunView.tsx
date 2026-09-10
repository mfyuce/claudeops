/**
 * TOBEDECIDED#15 Phase 2 — renders one run's detail, live (while
 * `OrchTab`'s `data.orch.active` names it) or historical (after it's
 * finished). `run` is fetched by the parent via `getOrchRun()` — this
 * component only renders, it never fetches on its own.
 *
 * A controller can own TWO result rows in the same run (`kind="brief"` from
 * the briefing phase, `kind="final"` from the post-outcome handoff) — a
 * naive "find the one result matching this participant's (host,name)"
 * would only ever surface the first one. Sections are grouped by `kind`
 * instead: Controller (brief + handoff) / Workers (worker_result, one card
 * each) / Decider (decision) — matches how the engine's own phases run.
 */

import type { ReactNode } from "react";
import { useLang } from "../../i18n/LangContext";
import type { Strings } from "../../i18n/strings";
import type { OrchResultItem, OrchRun } from "../../api/types";

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

function StatusLine({ status, elapsed, t }: { status: string | null; elapsed?: number; t: Strings }) {
  if (!status) return null;
  return (
    <div style={{ color: RESULT_COLOR[status] ?? "var(--muted)", fontSize: ".82rem" }}>
      {t.orchResultStatusLabel(status)}
      {elapsed && elapsed > 0 ? ` · ${elapsed.toFixed(1)}s` : ""}
    </div>
  );
}

function TextDetails({ text, t }: { text: string; t: Strings }) {
  if (!text) return null;
  return (
    <details style={{ fontSize: ".78rem", marginTop: ".2rem" }}>
      <summary style={{ cursor: "pointer", color: "var(--muted)" }}>{t.orchViewBtn}</summary>
      <div style={{ whiteSpace: "pre-wrap", marginTop: ".2rem" }}>{text}</div>
    </details>
  );
}

function Card({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        border: "1px solid var(--border)", borderRadius: "6px", background: "var(--panel2)",
        padding: ".5rem", flex: "1 1 220px", minWidth: "180px",
      }}
    >
      {children}
    </div>
  );
}

export function RunView({ run, onCancel }: RunViewProps) {
  const { t } = useLang();

  if (!run) return <span className="opts-hint">…</span>;

  const isLive = run.status === "working" || run.status === "briefing" || run.status === "deciding";
  const byKind = (kind: string): OrchResultItem | undefined => run.results.find((r) => r.kind === kind);
  const controller = run.participants.find((p) => p.role === "controller");
  const decider = run.participants.find((p) => p.role === "decider");
  const workers = run.participants.filter((p) => p.role === "worker");
  const briefResult = byKind("brief");
  const decisionResult = byKind("decision");
  const finalResult = byKind("final");

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

      {run.brief && (
        <div className="opts-hint" style={{ flexBasis: "100%" }}>
          <b>{t.orchBriefLabel}</b>
          <div style={{ whiteSpace: "pre-wrap", color: "var(--text)", fontSize: ".82rem", marginTop: ".15rem" }}>
            {run.brief}
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap: ".5rem" }}>
        {controller && (
          <Card>
            <div style={{ display: "flex", justifyContent: "space-between", gap: ".4rem" }}>
              <b>{controller.name}</b>
              <span className="cli-badge">{t.orchRoleLabel("controller")}</span>
            </div>
            <StatusLine status={briefResult?.status ?? (isLive && run.status === "briefing" ? "pending" : null)} elapsed={briefResult?.elapsed} t={t} />
            {finalResult && (
              <>
                <div style={{ fontSize: ".78rem", color: "var(--muted)", marginTop: ".3rem" }}>{t.orchHandoffLabel}</div>
                <StatusLine status={finalResult.status} t={t} />
              </>
            )}
          </Card>
        )}
        {workers.map((p) => {
          const r = run.results.find((x) => x.kind === "worker_result" && x.host === p.host && x.name === p.name);
          const status = r ? r.status : isLive ? "pending" : null;
          return (
            <Card key={`${p.host}:${p.name}`}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: ".4rem" }}>
                <b>{p.name}</b>
                <span className="cli-badge">{p.cli}</span>
              </div>
              <StatusLine status={status} elapsed={r?.elapsed} t={t} />
              {r?.verdict && <div style={{ fontSize: ".82rem", marginTop: ".2rem" }}>{r.verdict}</div>}
              {r?.text && <TextDetails text={r.text} t={t} />}
            </Card>
          );
        })}
        {decider && (
          <Card>
            <div style={{ display: "flex", justifyContent: "space-between", gap: ".4rem" }}>
              <b>{decider.name}</b>
              <span className="cli-badge">{t.orchRoleLabel("decider")}</span>
            </div>
            <StatusLine status={decisionResult?.status ?? (isLive && run.status === "deciding" ? "pending" : null)} elapsed={decisionResult?.elapsed} t={t} />
            {decisionResult?.verdict && <div style={{ fontSize: ".82rem", marginTop: ".2rem" }}>{decisionResult.verdict}</div>}
            {decisionResult?.text && <TextDetails text={decisionResult.text} t={t} />}
          </Card>
        )}
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
