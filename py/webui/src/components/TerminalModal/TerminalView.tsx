/**
 * Replaces `ensureXtermFor`/`pollTerm`/`loadXtermLib` (web.py ~2012-2274),
 * plus (per this stage's explicit brief) the special-key buttons, the
 * command input+send button, the copy-visible-output button, and the
 * `UrlBanner`. Always mounted for as long as `TerminalModal` is open
 * (visibility toggled via the `hidden` prop, not conditional
 * mount/unmount) — see `TerminalModal.tsx`'s header comment for why that
 * asymmetry with `ChatView` is deliberate, matching the original exactly.
 *
 * One deliberate placement difference from the original, called out
 * explicitly since it moves a control to a different DOM parent than
 * `termRow()` had it in: the "copy visible output" button lived in the
 * original's MODAL HEADER (`termRow()`, always visible regardless of
 * sub-tab). This stage's brief assigns porting it to `TerminalView`
 * instead, grouped with the other term-specific action controls (key
 * buttons/input/send) rather than the shell — reasonable since the action
 * only concerns the term view (copying its ANSI-stripped output) and has
 * nothing to do with the chat sub-tab. Same underlying request/behavior,
 * just relocated.
 *
 * `inputText` (the command-input's typed-but-unsent text) is plain local
 * `useState` here — this is the second core regression check the whole
 * rewrite exists for (`StatusContext`'s 4s poll cannot touch this
 * component's props/position in the tree, so React never remounts it and
 * the text survives untouched, structurally, the same way `OptionsRow`'s
 * `modelOther` does).
 */

import { useEffect, useRef, useState } from "react";
import type { Terminal } from "@xterm/xterm";
import { apiTermInput, apiTermKey, getTermOutput } from "../../api/client";
import { describeApiError } from "../../api/errors";
import { useLang } from "../../i18n/LangContext";
import { computeFitFontSize, fitContainerToTerm } from "./xtermSizing";
import { UrlBanner } from "./UrlBanner";

const POLL_INTERVAL_MS = 200;
const INITIAL_COLS = 160;
const INITIAL_ROWS = 45;

// Same list/order as the original's XTERM_KEYS (web.py ~2018) — 'Enter' is
// a SEPARATE special key from the input's own Enter-to-send behavior: it
// sends a bare Enter keypress straight to the tmux pane (e.g. to dismiss a
// "press enter to continue" prompt) without requiring any typed text,
// which sendTermInput() can't do (it early-returns on an empty input).
// Cross-checked against tmux_backend.py's real ALLOWED_SPECIAL_KEYS
// ({"C-c","C-d","Escape","Up","Down","Left","Right","Tab","Enter"}) — this
// button list is a subset (no C-d button in the UI, same as the original).
const XTERM_KEYS: [string, string][] = [
  ["↵", "Enter"],
  ["ctrl-c", "C-c"],
  ["esc", "Escape"],
  ["↑", "Up"],
  ["↓", "Down"],
  ["←", "Left"],
  ["→", "Right"],
  ["tab", "Tab"],
];

function stripAnsi(text: string): string {
  return text.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, "").replace(/\x1b\][^\x07]*\x07/g, "");
}

interface XtermInstance {
  term: Terminal;
  cols: number;
  rows: number;
  lastText: string | null;
}

type XtermState = "loading" | "ready" | "failed";

interface TerminalViewProps {
  name: string;
  hidden: boolean;
  onView: (path: string) => void;
}

export function TerminalView({ name, hidden, onView }: TerminalViewProps) {
  const { t, lang } = useLang();

  const containerRef = useRef<HTMLDivElement | null>(null);
  const instRef = useRef<XtermInstance | null>(null);
  const [xtermState, setXtermState] = useState<XtermState>("loading");

  const [hint, setHint] = useState("");
  const [rawText, setRawText] = useState("");
  const [fallbackText, setFallbackText] = useState("");

  const [inputText, setInputText] = useState("");
  const [copyLabel, setCopyLabel] = useState<string | null>(null);
  const copyResetTimer = useRef<number | null>(null);

  // ---- create the xterm.js instance once, dynamically importing the
  // library (and its CSS) so it code-splits and is only ever fetched when
  // a terminal is actually opened (original: loadXtermLib()'s lazy
  // <script>/<link> injection; here, bundled into dist/ instead of
  // CDN-vendored, so there's no runtime network dependency once built).
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [{ Terminal }] = await Promise.all([import("@xterm/xterm"), import("@xterm/xterm/css/xterm.css")]);
        if (cancelled) return;
        const container = containerRef.current;
        if (!container) return;
        const fontSize = computeFitFontSize(INITIAL_COLS);
        const term = new Terminal({
          cols: INITIAL_COLS,
          rows: INITIAL_ROWS,
          scrollback: 5000,
          // `tmux capture-pane -p`'s plain-text mode (tmux_backend.py's
          // tmux_capture) emits bare \n, not \r\n — with convertEol:false
          // that's a line-feed with NO carriage return, so each new line
          // keeps the PREVIOUS line's cursor column instead of resetting to
          // 0, producing a diagonal staircase instead of a left-aligned
          // list (found live, 2026-09-01, testing the shell provider's
          // terminal — a real bug, unrelated to the touch-scroll one this
          // session started investigating). Content that already emits
          // proper \r\n (claude/agy's own TUI redraws) is unaffected —
          // \r-then-\n and convertEol's synthesized \r-then-\n land in the
          // same place, so this is a strict fix, not a trade-off.
          convertEol: true,
          disableStdin: true,
          fontSize,
          // Default (1) is calibrated for a ~17px desktop line-height — this
          // terminal's real font is shrunk to fit a phone screen (~8px rows
          // here), so the SAME wheel/touch delta maps to a tiny fraction of a
          // line. Measured live (Playwright + real CDP touch dispatch, no
          // browser tooling in-conversation so this had to be tested this
          // way): ~6500px of wheel delta moved ~1 line — a full-height mobile
          // swipe or a few wheel clicks did nothing perceptible. 2026-09-01.
          scrollSensitivity: 20,
        });
        term.open(container);
        instRef.current = { term, cols: INITIAL_COLS, rows: INITIAL_ROWS, lastText: null };
        fitContainerToTerm(term, container, INITIAL_COLS, INITIAL_ROWS);
        setXtermState("ready");
      } catch {
        // Original deliberately does NOT latch a permanent "failed" flag
        // globally (a one-off mobile/cellular network hiccup used to
        // strand a tab on the raw-ANSI fallback forever) — here that
        // concern doesn't apply the same way: this effect runs once per
        // mount, and a fresh mount (a different session opened, or this
        // same one re-opened via a fresh `key`) gets its own fresh
        // attempt rather than reusing a cached failure.
        if (!cancelled) setXtermState("failed");
      }
    })();
    return () => {
      cancelled = true;
      if (instRef.current) {
        try {
          instRef.current.term.dispose();
        } catch {
          // matches the original's empty catch around xtermInstances[prev].term.dispose()
        }
        instRef.current = null;
      }
    };
  }, []);

  // ---- poll /api/term/output every 200ms, for as long as this component
  // is mounted (i.e. for as long as the modal is open) — independent of
  // `hidden`/`xtermState`, matching the original's termPollTimer exactly.
  useEffect(() => {
    let cancelled = false;

    async function poll() {
      let result;
      try {
        result = await getTermOutput(name, lang);
      } catch {
        // Original pollTerm() has no try/catch around its own fetch — a
        // network exception there becomes an unhandled rejection inside
        // the setInterval callback (nothing awaits/catches it). Matched
        // here by just skipping this tick silently; the next 200ms tick
        // retries on its own.
        return;
      }
      if (cancelled) return;

      // Original: renderTermUrls(name, d.text) runs unconditionally
      // whenever d.ok, BEFORE the atBottom/xterm-instance branching below
      // — the URL banner always reflects the latest raw text regardless
      // of scroll-pause state or whether xterm loaded at all.
      if (result.ok) setRawText(result.text);

      const inst = instRef.current;
      if (inst) {
        const buf = inst.term.buffer.active;
        const atBottom = buf.viewportY >= buf.baseY;
        if (!atBottom) {
          setHint(t.termScrolledHint);
          return;
        }
        setHint("");

        // Original reads d.cols/d.rows unconditionally (harmless in
        // untyped JS: undefined on a failed response, short-circuiting
        // `resized` to false) — ApiErr has no cols/rows field at all, so
        // the null-when-not-ok fallback below reproduces the same
        // falsy-short-circuit behavior in a type-safe way.
        const cols = result.ok ? result.cols : null;
        const rows = result.ok ? result.rows : null;
        const resized = !!(cols && rows && (cols !== inst.cols || rows !== inst.rows));
        if (resized && cols && rows) {
          inst.term.options.fontSize = computeFitFontSize(cols);
          inst.term.resize(cols, rows);
          inst.cols = cols;
          inst.rows = rows;
          if (containerRef.current) fitContainerToTerm(inst.term, containerRef.current, cols, rows);
        }

        if (result.ok && result.text === inst.lastText && !resized) {
          // identical content, not resized — skip reset+write entirely so
          // quiet ticks (no new output) never visibly flicker.
        } else if (result.ok) {
          inst.lastText = result.text;
          // A separate synchronous term.reset() (blanks immediately) followed
          // by an async term.write() (parses/paints over one or more later
          // frames) leaves a gap the browser can paint mid-update — visible
          // as a flash on every content-changing ~200ms tick during
          // "Computing…" (2026-08-31, ported fix from the original panel's
          // pollTerm — same root cause, independently re-discovered here).
          // Folding the clear into the write() call itself (as data, not an
          // out-of-band API call) makes clear+redraw a single pass through
          // xterm's own parser instead of two.
          inst.term.write(`\x1b[H\x1b[2J\x1b[3J${result.text}`, () => inst.term.scrollToBottom());
        } else {
          inst.lastText = null;
          inst.term.reset();
          inst.term.write(t.termGone(result.error));
        }
        return;
      }

      // xterm not ready/failed to load — plain ANSI-stripped fallback.
      setFallbackText(result.ok ? stripAnsi(result.text) : t.termGone(result.error));
    }

    void poll();
    const id = setInterval(() => void poll(), POLL_INTERVAL_MS);
    // Browsers throttle setInterval in backgrounded tabs (2026-09-05, user
    // report: content "arrives late" after switching away and back to the
    // panel tab) — without this, a backgrounded tab's poll can fall many
    // seconds behind and only catches up on the next throttled tick.
    // useStatus.ts's WS hook already does the equivalent (immediate
    // reconnect on visibilitychange); this mirrors that for the plain-REST
    // polling here.
    function onVisible() {
      if (document.visibilityState === "visible") void poll();
    }
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [name, lang, t]);

  useEffect(() => {
    return () => {
      if (copyResetTimer.current !== null) window.clearTimeout(copyResetTimer.current);
    };
  }, []);

  function handleSendKey(key: string) {
    // Original sendTermKey() has no error handling at all (fire-and-forget,
    // inline onclick, not awaited) — .catch(()=>{}) here avoids a genuine
    // unhandled-promise-rejection but is otherwise the same silent-on-
    // failure behavior from the user's point of view.
    void apiTermKey({ name, key, lang }).catch(() => {});
  }

  function handleSend() {
    if (!inputText) return;
    const text = inputText;
    setInputText("");
    void apiTermInput({ name, text, lang }).catch(() => {});
  }

  async function handleCopyVisible() {
    try {
      const res = await getTermOutput(name, lang);
      if (!res.ok) {
        window.alert(`${name}: ${res.error}`);
        return;
      }
      await navigator.clipboard.writeText(stripAnsi(res.text));
      setCopyLabel(t.termCopied);
      if (copyResetTimer.current !== null) window.clearTimeout(copyResetTimer.current);
      copyResetTimer.current = window.setTimeout(() => setCopyLabel(null), 1200);
    } catch (e) {
      // Original's copyTermText() calls r.json() on the raw fetch response
      // with no r.ok/content-type/401 check at all — a 401 there throws a
      // JSON-parse SyntaxError caught by the same generic catch, showing a
      // confusing raw parse-error message instead of an auth message.
      // getTermOutput()/describeApiError() (shared with the rest of this
      // app) correctly detect a 401 first — a strict improvement that
      // falls out of reusing the shared client rather than a hand-rolled
      // fetch, not a deliberate behavior change.
      window.alert(describeApiError(e, t));
    }
  }

  return (
    <div hidden={hidden} style={{ width: "100%" }}>
      <div
        ref={containerRef}
        hidden={xtermState === "failed"}
        style={{
          background: "#111",
          padding: ".35rem",
          borderRadius: "4px",
          overflow: "auto",
          // xterm.js's own touch handling (selection/drag) can end up
          // competing with the browser's native touch-scroll on this
          // container's — and its internal .xterm-viewport's — overflow
          // (2026-08-31, live mobile report: "terminal doesn't scroll").
          // touch-action: pan-y is the standard hint for "a vertical drag
          // here is a scroll, not something else" — cheap/safe to set even
          // if it turns out not to be the whole story.
          touchAction: "pan-y",
          maxWidth: "calc(95vw - 1.4rem)",
          maxHeight: "calc(92vh - 130px)",
          boxSizing: "content-box",
          fontFamily: "monospace",
          fontSize: ".8rem",
          color: "#ddd",
          whiteSpace: xtermState === "ready" ? undefined : "pre-wrap",
        }}
      />
      {xtermState === "failed" && (
        <pre
          style={{
            background: "#111",
            padding: ".35rem",
            borderRadius: "4px",
            overflow: "auto",
            maxWidth: "calc(95vw - 1.4rem)",
            maxHeight: "calc(92vh - 130px)",
            boxSizing: "content-box",
            fontFamily: "monospace",
            fontSize: ".8rem",
            color: "#ddd",
            whiteSpace: "pre-wrap",
            margin: 0,
          }}
        >
          {fallbackText}
        </pre>
      )}
      <div className="opts-hint" style={{ width: "100%", boxSizing: "border-box" }}>
        {hint}
      </div>
      <UrlBanner rawText={rawText} name={name} onView={onView} />
      <div className="opts" style={{ marginTop: ".4rem", width: "100%", boxSizing: "border-box" }}>
        {XTERM_KEYS.map(([label, key]) => (
          <button type="button" key={key} onClick={() => handleSendKey(key)}>
            {label}
          </button>
        ))}
        <button type="button" title={t.termCopyHint} onClick={() => void handleCopyVisible()}>
          {copyLabel ?? t.termCopyBtn}
        </button>
        <input
          type="text"
          placeholder={t.termPlaceholder}
          style={{ flex: 1, minWidth: "200px" }}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSend();
          }}
        />
        <button type="button" className="go" onClick={handleSend}>
          {t.termSend}
        </button>
      </div>
    </div>
  );
}
