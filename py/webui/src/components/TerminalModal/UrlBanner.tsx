/**
 * Replaces `extractTermUrls()`/`renderTermUrls()`/`copyTermUrl()` (web.py
 * ~2281-2332) — surfaces up to 3 most-recent URLs found in the terminal's
 * raw output (login flows — agy device-code, claude OAuth, etc. — print a
 * URL that's unreliable to select-by-touch inside xterm.js, per the
 * original's own comment), each with a copy button and an "open in new
 * tab" link.
 *
 * Safety note (per the plan): this renders LIVE, UNTRUSTED terminal
 * output — text a running CLI session printed, not anything this app
 * controls. Every URL below goes through ordinary React text-node
 * (`{url}`) / attribute (`href={url}`) bindings, never
 * `dangerouslySetInnerHTML` or string-built HTML, so nothing a session
 * prints can ever be interpreted as markup.
 *
 * Self-contained on purpose (own private `stripAnsi`, not imported from
 * `TerminalView.tsx`) — both files need this same trivial, dependency-free
 * one-liner independently, and keeping siblings free of cross-imports
 * keeps each easier to reason about alone.
 */

import { useState } from "react";
import { useLang } from "../../i18n/LangContext";

function stripAnsi(text: string): string {
  return text.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, "").replace(/\x1b\][^\x07]*\x07/g, "");
}

// Same regex as the original's TERM_URL_RE (web.py ~2281).
const TERM_URL_RE = /https?:\/\/[^\s<>"'\x1b\x07]+/g;

/** Original: `extractTermUrls(rawText)` (web.py ~2283-2293) — newest-first,
 * de-duplicated, capped at 3, trailing punctuation trimmed (so a URL
 * followed by a sentence's closing punctuation in the CLI's own prose
 * doesn't get swept into the link). */
function extractTermUrls(rawText: string): string[] {
  const clean = stripAnsi(rawText);
  const matches = clean.match(TERM_URL_RE) ?? [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (let i = matches.length - 1; i >= 0 && out.length < 3; i--) {
    const u = matches[i].replace(/[.,;:)\]}>'"]+$/, "");
    if (!seen.has(u)) {
      seen.add(u);
      out.push(u);
    }
  }
  return out;
}

function UrlRow({ url }: { url: string }) {
  const { t } = useLang();
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch (e) {
      window.alert(t.requestFailed + (e instanceof Error ? e.message : String(e)));
    }
  }

  return (
    <div style={{ display: "flex", gap: ".35rem", alignItems: "center", margin: ".15rem 0", overflow: "hidden" }}>
      <span
        style={{
          flex: 1,
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          fontFamily: "monospace",
          fontSize: ".75rem",
        }}
      >
        {url}
      </span>
      <a href={url} target="_blank" rel="noopener" style={{ whiteSpace: "nowrap" }}>
        {t.termOpen}
      </a>
      <button type="button" style={{ whiteSpace: "nowrap" }} onClick={() => void handleCopy()}>
        {copied ? t.termCopied : t.termCopyBtn}
      </button>
    </div>
  );
}

export function UrlBanner({ rawText }: { rawText: string }) {
  const urls = extractTermUrls(rawText);
  if (!urls.length) return null;
  return (
    // TODO L42 (2026-08-31, user: "url listesi cmd line'a veya altta scrollu
    // bir panel olabilir" — the URL list could sit near the command line, or
    // be a scrollable panel at the bottom): moved from a fixed banner above
    // the terminal (original placement — shifted the whole terminal down
    // every time a URL appeared/disappeared) to just above the command-line
    // row in `TerminalView`, and bounded with its own scroll so it can never
    // push that row far even if it somehow held more than a couple of URLs.
    <div style={{ width: "100%", boxSizing: "border-box", marginTop: ".3rem", maxHeight: "4.5rem", overflowY: "auto" }}>
      {urls.map((u) => (
        <UrlRow key={u} url={u} />
      ))}
    </div>
  );
}
