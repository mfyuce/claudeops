/**
 * Değnekçi "Özetler" / "Turlar": daily digests and long brain-tour files of the selected identity, read-only.
 * Fetched once on mount and when the parent's pushed-slice key changes (no timer of its own); a row opens the
 * file in a markdown viewer (`renderMarkdownSafe`, DOMPurify-sanitized).
 */
import { useEffect, useState } from "react";
import { getStewardDigestFile, getStewardDigests } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { renderMarkdownSafe } from "./shared/markdown";
import type { StewardDigestRow } from "../api/types";

type Kind = "daily" | "tours";

function fmtSize(n: number): string {
  return n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KiB`;
}

function label(kind: Kind, r: StewardDigestRow): string {
  if (kind === "daily") return r.date || r.file;
  return r.ts ? new Date(r.ts * 1000).toLocaleString() : r.file;
}

export function StewardDigests({ sid, refreshKey }: { sid: string; refreshKey: string }) {
  const { t } = useLang();
  const [daily, setDaily] = useState<StewardDigestRow[]>([]);
  const [tours, setTours] = useState<StewardDigestRow[]>([]);
  const [open, setOpen] = useState<{ kind: Kind; file: string } | null>(null);
  const [html, setHtml] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    let cancelled = false;
    void getStewardDigests(sid).then(
      (r) => {
        if (cancelled || !r.ok) return;
        setDaily(r.daily || []);
        setTours(r.tours || []);
      },
      () => undefined,
    );
    return () => {
      cancelled = true;
    };
  }, [sid, refreshKey]);

  useEffect(() => {
    setOpen(null);
    setHtml("");
    setNote("");
  }, [sid]);

  function show(kind: Kind, file: string) {
    if (open && open.kind === kind && open.file === file) {
      setOpen(null);
      return;
    }
    setOpen({ kind, file });
    setHtml("");
    setNote("…");
    getStewardDigestFile(kind, file, sid).then(
      async (r) => {
        if (!r.ok) {
          setNote(r.error || t.requestFailed);
          return;
        }
        setNote(r.truncated ? t.stewardDigestTruncated : "");
        setHtml(await renderMarkdownSafe(r.text || ""));
      },
      (e: unknown) => setNote(describeApiError(e, t)),
    );
  }

  const section = (kind: Kind, title: string, rows: StewardDigestRow[]) => (
    <details>
      <summary className="legend" style={{ cursor: "pointer", margin: 0 }}>
        {title} ({rows.length})
      </summary>
      <div style={{ marginTop: ".4rem", display: "flex", flexDirection: "column", gap: ".2rem" }}>
        {rows.length === 0 && <span className="opts-hint">{t.stewardDigestNone}</span>}
        {rows.map((r) => {
          const sel = open?.kind === kind && open.file === r.file;
          return (
            <div key={r.file}>
              <button type="button" aria-expanded={sel} onClick={() => show(kind, r.file)}>
                {label(kind, r)} · {fmtSize(r.size)}
              </button>
              {sel && (
                <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: ".5rem .8rem", margin: ".3rem 0", overflowX: "auto" }}>
                  {note && <div className="opts-hint">{note}</div>}
                  {/* eslint-disable-next-line react/no-danger -- sanitized via DOMPurify in renderMarkdownSafe */}
                  <div dangerouslySetInnerHTML={{ __html: html }} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ".4rem" }}>
      {section("daily", t.stewardDigestDaily, daily)}
      {section("tours", t.stewardDigestTours, tours)}
    </div>
  );
}
