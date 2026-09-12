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
 * Two ways to get keystrokes INTO the pane, and they are deliberately
 * different: the command box at the bottom sends a whole message at once
 * (`/api/term/input`, backend appends Enter), while "live typing" (opt-in
 * toggle, remembered per browser) flips xterm's own `disableStdin` off and
 * forwards its `onData` stream verbatim (`/api/term/raw`, no Enter appended)
 * — that is the 2026-09-08 request "neden direk terminale yazamiyorum da
 * text box a yazmaya mecbur kaliorum". Default OFF on purpose: with it on,
 * a stray keypress while reading (or an arrow key meant for xterm's own
 * scrollback) lands in the running CLI.
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
import { apiTermInput, apiTermKey, apiTermRaw, apiTermSetMode, getTermOutput } from "../../api/client";
import type { TermSetModePayload } from "../../api/client";
import { describeApiError } from "../../api/errors";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { cliOptionsFor, rowKey } from "../../state/hosts";
import { computeFitFontSize, fitContainerToTerm } from "./xtermSizing";
import { UrlBanner } from "./UrlBanner";

// The live-changeable mode list is NOT hardcoded here any more: it comes from
// the backend per CLI (`cli_options[cli].cyclable_modes`, i.e. the provider's
// own `cyclable_modes()`), because it is a per-CLI fact — codex/agy/shell have
// no Shift+Tab mode cycle at all and used to be offered claude's modes anyway.
// An empty list hides the picker entirely.

const POLL_INTERVAL_MS = 200;
// A remote host's connection (VS Code devtunnel, Cloudflare, etc.) can have
// brief individual-request blips even while the underlying tunnel is fine
// overall — at a 200ms poll interval, treating every single failed tick as
// "unreachable" flashes the error over good content almost as fast as it
// clears (live report, 2026-09-07: "content comes up then quickly reverts").
// Local sessions go through no extra network hop and essentially never see
// isolated failures, so this costs them nothing — it only changes how many
// blips in a row it takes before a REAL outage is reported.
const CONSECUTIVE_FAILURES_BEFORE_ERROR = 5;
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

// Live typing knobs. Ordering matters more than latency: keystrokes are only
// correct if they reach the pane in the order they were typed, so there is
// never more than ONE /api/term/raw request in flight — anything typed while
// one is out accumulates and goes as the next batch. The timer below only
// keeps a fast burst (or a paste, which xterm hands over as a single chunk)
// from firing one HTTP request per character, which matters most on a
// tunneled/remote host.
const RAW_FLUSH_MS = 25;
// Mirrors the backend's MAX_TERM_RAW_CHARS — a paste bigger than this is
// sliced here into several ordered calls instead of being rejected whole.
const RAW_MAX_CHARS = 8192;
const LIVE_INPUT_STORAGE_KEY = "cops_term_live_input";

function readStoredLiveInput(): boolean {
  try {
    return localStorage.getItem(LIVE_INPUT_STORAGE_KEY) === "1";
  } catch {
    // ignore — same defensiveness as App.tsx's readStoredTab()
    return false;
  }
}

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

// Owned here (rather than in TerminalModal, which only stores the current
// value) because TerminalView is the thing that actually interprets it —
// which of its two internal blocks (canvas+controls vs. the info block
// below) that "info" state hides is TerminalView's own concern.
export type SubTab = "term" | "chat" | "files" | "info";

interface TerminalViewProps {
  name: string;
  host: string;
  activeSubTab: SubTab;
  onView: (path: string) => void;
}

export function TerminalView({ name, host, activeSubTab, onView }: TerminalViewProps) {
  const { t, lang } = useLang();
  const { data } = useStatusContext();
  const [modeBusy, setModeBusy] = useState(false);
  const [modeMsg, setModeMsg] = useState("");

  const containerRef = useRef<HTMLDivElement | null>(null);
  const instRef = useRef<XtermInstance | null>(null);
  const [xtermState, setXtermState] = useState<XtermState>("loading");

  const [hint, setHint] = useState("");
  // The pane's ACTUAL current permission mode, re-read on every poll from the
  // status bar (null = unknown/not applicable) — the mode <select> shows this
  // rather than a placeholder, which is the whole point of TODO #78: a picker
  // that doesn't show the session's real state invites switching it by accident.
  const [paneMode, setPaneMode] = useState<string | null>(null);
  // Optimistic display for the model picker: claudeops has no way to read a
  // live /model change back (claude's status bar doesn't show the model), so
  // once the user picks one we keep showing it — but only for the exact
  // session+recorded-model it was picked against, so it can never leak onto
  // another session or survive a respawn with a different model. Derived
  // during render (no effect, nothing to reset).
  const [pickedModel, setPickedModel] = useState<{ value: string; forKey: string } | null>(null);
  const [rawText, setRawText] = useState("");
  const [fallbackText, setFallbackText] = useState("");
  const [masked, setMasked] = useState(false);

  const [inputText, setInputText] = useState("");
  const [copyLabel, setCopyLabel] = useState<string | null>(null);
  const copyResetTimer = useRef<number | null>(null);

  const [liveInput, setLiveInput] = useState<boolean>(readStoredLiveInput);
  const [liveMsg, setLiveMsg] = useState("");
  // Everything the once-registered onData handler needs, held in refs: the
  // handler is installed in the mount effect below and would otherwise keep
  // that first render's props/state forever.
  const liveInputRef = useRef(liveInput);
  const ctxRef = useRef({ name, host, lang });
  const queueRawRef = useRef<(data: string) => void>(() => {});
  const pendingRawRef = useRef("");
  const rawSendingRef = useRef(false);
  const rawFlushTimer = useRef<number | null>(null);

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
          // Read from the ref, not the state variable: this effect runs once,
          // asynchronously (dynamic import), so by the time it lands the user
          // may already have toggled live typing — the ref carries the current
          // value, and the [liveInput] effect below keeps it in sync after that.
          disableStdin: !liveInputRef.current,
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
        // Registered once (the instance is created once); the indirection
        // through `queueRawRef` keeps it on the CURRENT props rather than this
        // closure's. xterm already suppresses key events while disableStdin is
        // true, but paste goes through a different path there, so the handler
        // re-checks the toggle itself rather than trusting that.
        term.onData((data) => queueRawRef.current(data));
        instRef.current = { term, cols: INITIAL_COLS, rows: INITIAL_ROWS, lastText: null };
        fitContainerToTerm(term, container, INITIAL_COLS, INITIAL_ROWS);
        // The [liveInput] effect below already does this on every TOGGLE, but
        // if live typing was remembered on from a previous session
        // (readStoredLiveInput()) that effect's first run lands before this
        // async import resolves — instRef.current is still null then, so its
        // own `if (!inst) return` skips the focus() call and it never fires
        // again on its own (liveInput itself didn't change). Catch that one
        // case here, once, right when the instance actually starts existing.
        if (liveInputRef.current) term.focus();
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

  // ---- re-fit the container to the CURRENT viewport whenever it changes.
  // `fitContainerToTerm` sets the container's width/height as fixed pixel
  // values (see xtermSizing.ts's header comment for why — cols/rows are the
  // real pty size, not something to shrink-to-fit), and the only two places
  // that ever call it are this component's mount (with the placeholder
  // INITIAL_COLS/ROWS) and the poll loop's `resized` branch below, which
  // fires only when the BACKEND's reported cols/rows change. A live pane's
  // real terminal size is usually stable for the session's whole lifetime,
  // so once those pixel dimensions are set they otherwise never get
  // recomputed — unlike the modal's own dvh-based outer bounds, this inner
  // container does not track the viewport on its own. A phone's on-screen
  // keyboard opening (toggled by "live typing", see the [liveInput] effect's
  // focus()/blur()) or closing, or a rotation, changes how much space is
  // actually available without ever touching cols/rows — left unhandled,
  // the terminal stays pinned at whatever size fit the viewport the LAST
  // time cols/rows happened to change, which reads as "stuck small" exactly
  // when there's now more room to use (2026-09-11 user report).
  useEffect(() => {
    function refit() {
      const inst = instRef.current;
      const container = containerRef.current;
      if (!inst || !container) return;
      inst.term.options.fontSize = computeFitFontSize(inst.cols);
      fitContainerToTerm(inst.term, container, inst.cols, inst.rows);
    }
    window.addEventListener("resize", refit);
    window.addEventListener("orientationchange", refit);
    window.visualViewport?.addEventListener("resize", refit);
    return () => {
      window.removeEventListener("resize", refit);
      window.removeEventListener("orientationchange", refit);
      window.visualViewport?.removeEventListener("resize", refit);
    };
  }, []);

  // ---- poll /api/term/output every 200ms, for as long as this component
  // is mounted (i.e. for as long as the modal is open) — independent of
  // `hidden`/`xtermState`, matching the original's termPollTimer exactly.
  useEffect(() => {
    let cancelled = false;
    let consecutiveFailures = 0;

    async function poll() {
      let result;
      try {
        result = await getTermOutput(name, lang, host);
      } catch {
        // Original pollTerm() has no try/catch around its own fetch — a
        // network exception there becomes an unhandled rejection inside
        // the setInterval callback (nothing awaits/catches it). Matched
        // here by just skipping this tick silently; the next 200ms tick
        // retries on its own.
        return;
      }
      if (cancelled) return;

      if (result.ok) {
        consecutiveFailures = 0;
      } else {
        consecutiveFailures += 1;
        if (consecutiveFailures < CONSECUTIVE_FAILURES_BEFORE_ERROR) {
          // Isolated blip — keep showing whatever's already on screen rather
          // than flashing an error that (per the poll cadence) may well
          // clear itself on the very next tick.
          return;
        }
      }

      // Original: renderTermUrls(name, d.text) runs unconditionally
      // whenever d.ok, BEFORE the atBottom/xterm-instance branching below
      // — the URL banner always reflects the latest raw text regardless
      // of scroll-pause state or whether xterm loaded at all.
      if (result.ok) {
        setRawText(result.text);
        setMasked(result.masked);
        setPaneMode(result.mode);
      }

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
  }, [name, host, lang, t]);

  useEffect(() => {
    return () => {
      if (copyResetTimer.current !== null) window.clearTimeout(copyResetTimer.current);
      if (rawFlushTimer.current !== null) window.clearTimeout(rawFlushTimer.current);
    };
  }, []);

  useEffect(() => {
    const prev = ctxRef.current;
    ctxRef.current = { name, host, lang };
    // Switching the modal to another session mid-type: whatever is still
    // buffered was meant for the PREVIOUS pane, so it is dropped rather than
    // delivered to the new one.
    if (prev.name !== name || prev.host !== host) pendingRawRef.current = "";
  }, [name, host, lang]);

  useEffect(() => {
    liveInputRef.current = liveInput;
    try {
      localStorage.setItem(LIVE_INPUT_STORAGE_KEY, liveInput ? "1" : "0");
    } catch {
      // ignore — localStorage can throw (private browsing/storage disabled)
    }
    const inst = instRef.current;
    // null while the dynamic import is still in flight — that path reads the
    // ref above when it constructs the Terminal, so nothing is lost here.
    if (!inst) return;
    inst.term.options.disableStdin = !liveInput;
    if (liveInput) inst.term.focus();
    else inst.term.blur();
  }, [liveInput]);

  function flushRaw() {
    if (rawSendingRef.current || !pendingRawRef.current) return;
    const data = pendingRawRef.current.slice(0, RAW_MAX_CHARS);
    pendingRawRef.current = pendingRawRef.current.slice(RAW_MAX_CHARS);
    rawSendingRef.current = true;
    const { name: n, host: h, lang: l } = ctxRef.current;
    void apiTermRaw({ name: n, host: h, data, lang: l })
      .then((res) => setLiveMsg(res.ok ? "" : res.error))
      .catch((e) => setLiveMsg(describeApiError(e, t)))
      .finally(() => {
        rawSendingRef.current = false;
        // Whatever was typed while that request was out goes now, in order.
        if (pendingRawRef.current) flushRaw();
      });
  }

  function queueRaw(data: string) {
    if (!liveInputRef.current || !data) return;
    pendingRawRef.current += data;
    if (rawFlushTimer.current !== null) return;
    rawFlushTimer.current = window.setTimeout(() => {
      rawFlushTimer.current = null;
      flushRaw();
    }, RAW_FLUSH_MS);
  }

  // Deliberately dependency-less: re-pointed on every render so the handler
  // registered once on the xterm instance always calls the newest closure.
  useEffect(() => {
    queueRawRef.current = queueRaw;
  });

  function handleSendKey(key: string) {
    // Original sendTermKey() has no error handling at all (fire-and-forget,
    // inline onclick, not awaited) — .catch(()=>{}) here avoids a genuine
    // unhandled-promise-rejection but is otherwise the same silent-on-
    // failure behavior from the user's point of view.
    void apiTermKey({ name, host, key, lang }).catch(() => {});
  }

  function handleSend() {
    if (!inputText) return;
    const text = inputText;
    setInputText("");
    void apiTermInput({ name, host, text, lang }).catch(() => {});
  }

  // (host, name) is the identity everywhere — never a bare name (two hosts can
  // have a same-named session).
  const session = data?.sessions.find((s) => rowKey(s) === rowKey({ host, name }));
  const cliOpts = cliOptionsFor(data ?? null, host, session?.cli ?? "");
  // What the session is REALLY on: the running process's own --model, falling
  // back to what claudeops recorded for the name (a stopped/unknown proc).
  const knownModel = session?.live_model || session?.model || "";
  const modelPickKey = `${rowKey({ host, name })}|${knownModel}`;
  const modelValue = pickedModel?.forKey === modelPickKey ? pickedModel.value : knownModel;
  const modelOptions =
    modelValue && !cliOpts.models.includes(modelValue) ? [modelValue, ...cliOpts.models] : cliOpts.models;

  async function handleSetMode(mode: TermSetModePayload["mode"]) {
    setModeBusy(true);
    setModeMsg("");
    try {
      const res = await apiTermSetMode({ name, host, mode, lang });
      setModeMsg(res.ok ? "" : res.error);
    } catch (e) {
      setModeMsg(describeApiError(e, t));
    } finally {
      setModeBusy(false);
    }
  }

  // No confirmed direct-argument syntax for /model (only /model with no args,
  // opening an interactive picker, is documented) — sent optimistically as a
  // convenience; if the CLI doesn't accept the argument the picker just opens
  // in the terminal itself and the user finishes the pick there, same as
  // typing it by hand. Nothing destructive either way.
  function handleSetModel(model: string) {
    if (!model) return;
    void apiTermInput({ name, host, text: `/model ${model}`, lang }).catch(() => {});
  }

  async function handleCopyVisible() {
    try {
      const res = await getTermOutput(name, lang, host);
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

  // Split rather than a single `hidden` flag: URL/mode/model/effort moved to
  // their own "info" sub-tab (2026-09-11, user: mobilde bu şerit terminali
  // sıkıştırıyordu — TODO.md "web panel Terminal: mobilde çok sıkışık") so
  // they're only shown/hidden together as their own group now, separate from
  // the canvas+live-typing+key-buttons+input-row group that stays on "term".
  const termHidden = activeSubTab !== "term";
  const infoHidden = activeSubTab !== "info";

  return (
    <>
      <div hidden={termHidden} style={{ width: "100%" }}>
        <div
          ref={containerRef}
          hidden={xtermState === "failed"}
          // A live-typing terminal swallows keystrokes that would otherwise do
          // nothing, so it has to LOOK different — otherwise there's no way to
          // tell whether what you just typed went to the CLI or nowhere.
          style={{
            background: "#111",
            padding: ".35rem",
            borderRadius: "4px",
            outline: liveInput ? "2px solid var(--accent)" : undefined,
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
            // dvh, see TerminalModal.tsx's maxHeight comment.
            maxHeight: "calc(92dvh - 130px)",
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
              // dvh, see TerminalModal.tsx's maxHeight comment.
              maxHeight: "calc(92dvh - 130px)",
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
        <div className="opts" style={{ marginTop: ".4rem", width: "100%", boxSizing: "border-box" }}>
          <label title={t.termLiveHint}>
            <input
              type="checkbox"
              checked={liveInput}
              onChange={(e) => {
                setLiveInput(e.target.checked);
                setLiveMsg("");
              }}
            />{" "}
            {t.termLiveLabel}
          </label>
          {XTERM_KEYS.map(([label, key]) => (
            <button type="button" key={key} onClick={() => handleSendKey(key)}>
              {label}
            </button>
          ))}
          <button type="button" title={t.termCopyHint} onClick={() => void handleCopyVisible()}>
            {copyLabel ?? t.termCopyBtn}
          </button>
          {masked && <div className="warn-banner">{t.termMaskedHint}</div>}
          {liveInput && <div className="opts-hint" style={{ flexBasis: "100%" }}>{t.termLiveOn}</div>}
          {liveMsg && <div className="warn-banner">{liveMsg}</div>}
          <div className="term-input-row">
            {masked ? (
              // Masked panes keep the plain <input type="password"> — a
              // <textarea> CANNOT mask its content, and this box is exactly
              // where the 2026-09-08 password leak happened (DONE.md
              // "2026-09-08 (2)"). Multi-line is irrelevant for a password
              // prompt anyway, so the security path stays byte-for-byte what
              // it was.
              <input
                type="password"
                placeholder={t.termMaskedPlaceholder}
                style={{ flex: 1, minWidth: "200px" }}
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSend();
                }}
              />
            ) : (
              // Multi-line prompts (TODO #67): Enter still sends — the box's
              // whole point — and Shift+Enter inserts a newline. The backend
              // needed NOTHING for this: tmux_send_keys()'s `send-keys -l`
              // carries embedded newlines to the CLI as ONE turn (verified
              // live 2026-09-04 with a 1204-char multi-line message, DONE.md
              // "2026-09-04 (4)"), which is why this is a pure frontend change.
              <textarea
                placeholder={t.termPlaceholder}
                rows={2}
                style={{ flex: 1, minWidth: "200px", resize: "vertical", fontFamily: "inherit" }}
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={(e) => {
                  // isComposing: an IME (or Android's suggestion bar) uses
                  // Enter to accept a candidate — sending there would cut the
                  // word in half and fire a half-typed message.
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
              />
            )}
            <button type="button" className="go" onClick={handleSend}>
              {t.termSend}
            </button>
          </div>
        </div>
      </div>
      <div hidden={infoHidden} style={{ width: "100%" }}>
        <UrlBanner rawText={rawText} name={name} onView={onView} />
        <div className="opts" style={{ marginTop: ".4rem", width: "100%", boxSizing: "border-box" }}>
          {cliOpts.cyclable_modes.length > 0 && (
            <label title={t.termModeHint}>
              {t.termModeLabel}
              <select
                disabled={modeBusy}
                // Controlled by what the pane actually shows: after a successful
                // switch the next poll moves it on its own, and while a switch is
                // in flight it falls back to the placeholder ("applying…").
                value={!modeBusy && paneMode && cliOpts.cyclable_modes.includes(paneMode) ? paneMode : ""}
                onChange={(e) => {
                  if (e.target.value) void handleSetMode(e.target.value as TermSetModePayload["mode"]);
                }}
              >
                <option value="" disabled>
                  {modeBusy ? t.termModeApplying : t.termModePick}
                </option>
                {cliOpts.cyclable_modes.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
          )}
          {modelOptions.length > 0 && (
            <label title={t.termModelHint}>
              {t.termModelLabel}
              <select
                value={modelValue}
                onChange={(e) => {
                  if (!e.target.value) return;
                  setPickedModel({ value: e.target.value, forKey: modelPickKey });
                  handleSetModel(e.target.value);
                }}
              >
                {!modelValue && (
                  <option value="" disabled>
                    {t.termModelPick}
                  </option>
                )}
                {modelOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
          )}
          {session?.live_effort && (
            <span className="opts-hint" title={t.termEffortHint}>
              {t.termEffortLabel}: {session.live_effort}
            </span>
          )}
          {modeMsg && <span className="opts-hint">{modeMsg}</span>}
        </div>
      </div>
    </>
  );
}
