/**
 * Replaces `extractTermUrls()`/`renderTermUrls()`/`copyTermUrl()` (web.py
 * ~2281-2332) — surfaces up to 3 most-recent URLs found in the terminal's
 * raw output (login flows — agy device-code, claude OAuth, etc. — print a
 * URL that's unreliable to select-by-touch inside xterm.js, per the
 * original's own comment), each with a copy button and an "open in new
 * tab" link.
 *
 * 2026-09-05 (user: "aşağıdaki url listsine dosyalsrı da mı eklesek?"):
 * extended to also surface file paths mentioned in the same raw output —
 * a CLI printing "wrote output to /path/to/report.pdf" is exactly the kind
 * of thing this banner already exists for. Unlike URLs, a bare path regex
 * is NOT trustworthy on its own (Linux paths can contain spaces, and plain
 * prose is full of `/`-shaped false positives — division, dates, etc.) —
 * every candidate is validated against the backend (`_files_validate()`,
 * which resolves it against this session's real allowed roots and confirms
 * it's an actual file) before it's ever shown; nothing renders from the
 * regex match alone. Validation is debounced to the candidate SET, not the
 * (~200ms) poll tick — `lastCandidatesKeyRef` skips the network round trip
 * entirely when nothing actually changed.
 *
 * Safety note (per the plan): this renders LIVE, UNTRUSTED terminal
 * output — text a running CLI session printed, not anything this app
 * controls. Every URL/path below goes through ordinary React text-node
 * (`{url}`) / attribute (`href={url}`) bindings, never
 * `dangerouslySetInnerHTML` or string-built HTML, so nothing a session
 * prints can ever be interpreted as markup.
 */

import { useEffect, useRef, useState } from "react";
import { filesDownloadUrl, postFilesValidate } from "../../api/client";
import { useLang } from "../../i18n/LangContext";
import { isViewable } from "./fileViewerKind";

function stripAnsi(text: string): string {
  return text.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, "").replace(/\x1b\][^\x07]*\x07/g, "");
}

// Same regex as the original's TERM_URL_RE (web.py ~2281).
const TERM_URL_RE = /https?:\/\/[^\s<>"'\x1b\x07]+/g;

// Absolute-ish path candidates (optionally ~/../.-prefixed) — deliberately
// loose (see file header): a naive match on ordinary prose (e.g. "3/4" or
// "04/09/2026") is harmless here because it just fails backend validation
// below and never gets rendered. Real filtering happens server-side.
const TERM_PATH_RE = /(?:~|\.{1,2})?\/[^\s<>"'\x1b\x07]+/g;
const MAX_PATH_CANDIDATES = 8;

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

/** Same shape as `extractTermUrls` — newest-first, deduplicated, capped,
 * trailing punctuation trimmed. Returns raw CANDIDATE strings, not
 * validated yet (see `UrlBanner`'s effect). */
function extractTermPathCandidates(rawText: string): string[] {
  const clean = stripAnsi(rawText);
  const matches = clean.match(TERM_PATH_RE) ?? [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (let i = matches.length - 1; i >= 0 && out.length < MAX_PATH_CANDIDATES; i--) {
    const p = matches[i].replace(/[.,;:)\]}>'"]+$/, "");
    if (p.length > 1 && !seen.has(p)) {
      seen.add(p);
      out.push(p);
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
      <a href={url} target="_blank" rel="noopener noreferrer" style={{ whiteSpace: "nowrap" }}>
        {t.termOpen}
      </a>
      <button type="button" style={{ whiteSpace: "nowrap" }} onClick={() => void handleCopy()}>
        {copied ? t.termCopied : t.termCopyBtn}
      </button>
    </div>
  );
}

function FileMentionRow({
  path, name, lang, onView,
}: {
  path: string;
  name: string;
  lang: "tr" | "en";
  onView: (path: string) => void;
}) {
  const { t } = useLang();
  const filename = path.split("/").pop() ?? path;
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
        📄 {path}
      </span>
      {isViewable(filename) && (
        <button type="button" style={{ whiteSpace: "nowrap" }} onClick={() => onView(path)}>
          {t.filesView}
        </button>
      )}
      <a href={filesDownloadUrl(name, lang, path)} download={filename} style={{ whiteSpace: "nowrap" }}>
        {t.filesDownload}
      </a>
    </div>
  );
}

interface UrlBannerProps {
  rawText: string;
  /** Lite terminal frames (`web_term_lite.py`) carry only the visible rows, so the backend
   * extracts these two lists from the FULL capture with the same rules as the two functions
   * above. When absent (legacy full frame) they are derived from `rawText` here, as before. */
  urls?: string[];
  paths?: string[];
  name: string;
  onView: (path: string) => void;
}

export function UrlBanner({ rawText, urls: urlsProp, paths: pathsProp, name, onView }: UrlBannerProps) {
  const { lang } = useLang();
  const urls = urlsProp ?? extractTermUrls(rawText);
  const [validFiles, setValidFiles] = useState<string[]>([]);
  const lastCandidatesKeyRef = useRef<string>("");
  // A string key, not the array: a lite frame delivers a fresh `paths` array every tick, and the
  // effect below must only re-run when the candidate SET actually changed.
  const pathsKey = pathsProp ? pathsProp.join(" ") : null;

  useEffect(() => {
    const candidates =
      pathsKey !== null ? (pathsKey === "" ? [] : pathsKey.split(" ")) : extractTermPathCandidates(rawText);
    const key = candidates.join("\0");
    if (key === lastCandidatesKeyRef.current) return; // aynı aday seti — gereksiz round-trip yok
    lastCandidatesKeyRef.current = key;
    if (candidates.length === 0) {
      setValidFiles([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const d = await postFilesValidate(name, lang, candidates);
        if (!cancelled && d.ok) setValidFiles(d.valid);
      } catch {
        // sessizce yut — bu banner "en iyi çaba" bir özellik, terminal akışını hiç bozmamalı
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [rawText, pathsKey, name, lang]);

  if (!urls.length && !validFiles.length) return null;
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
      {validFiles.map((p) => (
        <FileMentionRow key={p} path={p} name={name} lang={lang} onView={onView} />
      ))}
    </div>
  );
}
