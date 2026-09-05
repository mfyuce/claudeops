/**
 * "Uzak Masaüstü" tab (2026-09-04) — on-demand screen sharing with optional
 * mouse/keyboard control. Backend is `rust/screenshare` (X11-capture + JPEG
 * + WebSocket daemon, spawned/killed by `remote_desktop.py`, localhost-only/
 * no auth of its own — this tab's `/ws/desktop` connection reuses the SAME
 * `?token=` this whole page already loaded with, proxied verbatim as raw
 * bytes by `web.py`'s `_proxy_desktop_ws`, which needs no protocol-specific
 * changes for input — it was already bidirectional).
 *
 * `useDesktopStream` renders frames via `<img src={blob URL}>` rather than
 * `<canvas>` — simpler (no manual JPEG decode/draw), and at ~2 fps there's
 * no meaningful performance difference. Each new frame's object URL
 * replaces (and revokes) the previous one so the browser never accumulates
 * blob memory across a long-running session. It also exposes `sendInput`
 * for the control layer below to push JSON input events over the same
 * socket the frames arrive on (one connection, both directions).
 *
 * Control ("Kontrolü Al") is OFF by default and entirely local UI state —
 * turning it on just starts attaching pointer/keyboard listeners, nothing
 * server-side changes. IMPORTANT (found via live testing, not theoretical):
 * this shares the REAL mouse/keyboard with whoever is physically at the
 * machine — X11 routes clicks/scroll by pointer POSITION, not by which
 * window last had keyboard focus, so a physical user moving their own
 * mouse concurrently can and will race with control input. Every pointer-
 * position-dependent event (click, drag, scroll) therefore sends a fresh
 * `move` to the exact event coordinates immediately before it, rather than
 * trusting an earlier move — never assume the remote pointer is still
 * where the last message put it.
 *
 * No modifier-key (Ctrl/Shift/Alt/Meta) forwarding yet, deliberately: the
 * wire protocol has no way to combine a held modifier with another key, and
 * forwarding bare modifier down/up risks a modifier getting stuck "held" on
 * the real machine if a keyup is ever missed (e.g. focus loss mid-press) —
 * a much worse failure mode than just not supporting Ctrl+C yet. Plain
 * character typing (including Shift-shifted symbols and non-ASCII text —
 * Turkish ğ/ü/ş/ı/ö/ç included) still works fine: it rides the hidden
 * input's `input` event, so the browser/OS resolves the actual character
 * before we ever see it.
 *
 * Cursor marker (2026-09-05): the backend ships a tiny JSON text message
 * (`{t:"cursor",x,y}`, distinguishable from a frame by `typeof ev.data`
 * since frames arrive as `Blob`) once per frame with the pointer's position
 * in the SAME coordinate space frame pixels — and outgoing `move` events —
 * already use, so no separate scaling logic is needed here. It's drawn as a
 * plain CSS-percentage-positioned dot inside `.desktop-frame` (a wrapper
 * sized to the `<img>`'s own rendered box), not measured via
 * `getBoundingClientRect()` — the percentage is relative to the image's own
 * box, so the browser handles scaling for free. Independent of "Kontrolü
 * Al": showing where the (possibly physical, possibly another viewer's)
 * cursor is is useful even in view-only mode, default on since it's purely
 * informational and never touches input.
 */
import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, WheelEvent as ReactWheelEvent } from "react";
import { apiDesktopStart, apiDesktopStop, TOKEN } from "../api/client";
import { callAction } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";

type MouseButtonName = "left" | "middle" | "right";

type InputEvent =
  | { t: "move"; x: number; y: number }
  | { t: "down"; b: MouseButtonName }
  | { t: "up"; b: MouseButtonName }
  | { t: "scroll"; dx: number; dy: number }
  | { t: "key"; k: string; a: "click" }
  | { t: "text"; s: string };

// Mirrors `named_key()` in rust/screenshare/src/main.rs — anything not on
// this list is treated as printable text instead (see the hidden input's
// onInput handler), not sent through the key path.
const NAMED_KEYS = new Set([
  "Enter", "Backspace", "Delete", "Tab", "Escape",
  "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",
  "Home", "End", "PageUp", "PageDown",
  "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
]);

const MOVE_THROTTLE_MS = 40; // ~25/s — smooth enough, doesn't flood the socket

function desktopWsUrl(): string {
  const scheme = location.protocol === "https:" ? "wss://" : "ws://";
  return `${scheme}${location.host}/ws/desktop?token=${encodeURIComponent(TOKEN)}`;
}

function buttonName(button: number): MouseButtonName {
  if (button === 2) return "right";
  if (button === 1) return "middle";
  return "left";
}

// Wheel deltas vary wildly by device/browser (pixels vs. lines vs. pages,
// and anywhere from ~1 to 100+ per event) — collapse to a small, bounded
// step per event; the natural repeat rate of wheel events does the rest.
function scrollStep(delta: number): number {
  if (delta === 0) return 0;
  return Math.sign(delta) * Math.min(3, Math.max(1, Math.round(Math.abs(delta) / 40)));
}

type CursorPos = { x: number; y: number };

function useDesktopStream(active: boolean) {
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [cursor, setCursor] = useState<CursorPos | null>(null);
  const urlRef = useRef<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!active) return;
    const ws = new WebSocket(desktopWsUrl());
    wsRef.current = ws;
    ws.binaryType = "blob";
    ws.onopen = () => setConnected(true);
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        try {
          const msg = JSON.parse(ev.data) as { t?: string; x?: number; y?: number };
          if (msg.t === "cursor" && typeof msg.x === "number" && typeof msg.y === "number") {
            setCursor({ x: msg.x, y: msg.y });
          }
        } catch {
          // Ignore malformed control messages — never worth dropping the stream over.
        }
        return;
      }
      const nextUrl = URL.createObjectURL(ev.data as Blob);
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = nextUrl;
      setFrameUrl(nextUrl);
    };
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    return () => {
      wsRef.current = null;
      ws.close();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
      setFrameUrl(null);
      setConnected(false);
      setCursor(null);
    };
  }, [active]);

  function sendInput(event: InputEvent) {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(event));
  }

  return { frameUrl, connected, cursor, sendInput };
}

export function DesktopTab() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [busy, setBusy] = useState<"start" | "stop" | null>(null);
  const [controlWanted, setControlWanted] = useState(false);
  const [showCursor, setShowCursor] = useState(true);

  const running = data?.remote_desktop.running ?? false;
  const control = controlWanted && running; // can't control a stopped/stopping stream
  const { frameUrl, connected, cursor, sendInput } = useDesktopStream(running);

  const imgRef = useRef<HTMLImageElement>(null);
  const hiddenInputRef = useRef<HTMLInputElement>(null);
  const lastMoveRef = useRef(0);
  const [markerStyle, setMarkerStyle] = useState<{ left: string; top: string } | null>(null);

  useEffect(() => {
    if (control) hiddenInputRef.current?.focus({ preventScroll: true });
    else hiddenInputRef.current?.blur();
  }, [control]);

  // Recomputed whenever a new cursor position arrives (~2/s while running) —
  // reads `imgRef.current` here rather than during render (a bare ref read
  // in render isn't safe: nothing guarantees it reflects the latest commit).
  // Uses the img's *intrinsic* size, not getBoundingClientRect() — `.desktop-
  // frame` hugs the img's rendered box exactly, so a plain CSS percentage
  // lets the browser do the client-size scaling for free.
  useEffect(() => {
    if (!showCursor || !cursor) {
      setMarkerStyle(null);
      return;
    }
    const img = imgRef.current;
    if (!img || !img.naturalWidth || !img.naturalHeight) {
      setMarkerStyle(null);
      return;
    }
    setMarkerStyle({
      left: `${(cursor.x / img.naturalWidth) * 100}%`,
      top: `${(cursor.y / img.naturalHeight) * 100}%`,
    });
  }, [cursor, showCursor]);

  async function handleStart() {
    setBusy("start");
    await callAction(() => apiDesktopStart(lang), "desktop", t);
    setBusy(null);
    refresh();
  }

  async function handleStop() {
    setBusy("stop");
    await callAction(() => apiDesktopStop(lang), "desktop", t);
    setBusy(null);
    refresh();
  }

  function remoteCoords(clientX: number, clientY: number): { x: number; y: number } | null {
    const img = imgRef.current;
    if (!img || !img.naturalWidth || !img.naturalHeight) return null;
    const rect = img.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    const x = Math.round(((clientX - rect.left) / rect.width) * img.naturalWidth);
    const y = Math.round(((clientY - rect.top) / rect.height) * img.naturalHeight);
    return {
      x: Math.max(0, Math.min(img.naturalWidth - 1, x)),
      y: Math.max(0, Math.min(img.naturalHeight - 1, y)),
    };
  }

  function handlePointerDown(e: ReactPointerEvent<HTMLImageElement>) {
    if (!control) return;
    e.preventDefault();
    imgRef.current?.setPointerCapture(e.pointerId);
    const pos = remoteCoords(e.clientX, e.clientY);
    if (!pos) return;
    sendInput({ t: "move", x: pos.x, y: pos.y });
    sendInput({ t: "down", b: buttonName(e.button) });
    lastMoveRef.current = performance.now();
    hiddenInputRef.current?.focus({ preventScroll: true });
  }

  function handlePointerMove(e: ReactPointerEvent<HTMLImageElement>) {
    if (!control) return;
    const now = performance.now();
    if (now - lastMoveRef.current < MOVE_THROTTLE_MS) return;
    lastMoveRef.current = now;
    const pos = remoteCoords(e.clientX, e.clientY);
    if (pos) sendInput({ t: "move", x: pos.x, y: pos.y });
  }

  function handlePointerUp(e: ReactPointerEvent<HTMLImageElement>) {
    if (!control) return;
    e.preventDefault();
    sendInput({ t: "up", b: buttonName(e.button) });
  }

  function handleWheel(e: ReactWheelEvent<HTMLImageElement>) {
    if (!control) return;
    e.preventDefault();
    const pos = remoteCoords(e.clientX, e.clientY);
    if (pos) sendInput({ t: "move", x: pos.x, y: pos.y });
    const dx = scrollStep(e.deltaX);
    const dy = scrollStep(e.deltaY);
    if (dx !== 0 || dy !== 0) sendInput({ t: "scroll", dx, dy });
  }

  function handleKeyDown(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (!control) return;
    if (NAMED_KEYS.has(e.key)) {
      e.preventDefault();
      sendInput({ t: "key", k: e.key, a: "click" });
    }
    // Anything else (printable characters, modifier keys) is deliberately
    // left alone here — see the file header comment for why.
  }

  function handleHiddenInput(e: FormEvent<HTMLInputElement>) {
    if (!control) return;
    const el = e.currentTarget;
    const text = el.value;
    el.value = "";
    if (text) sendInput({ t: "text", s: text });
  }

  if (!data) return null;

  return (
    <div>
      <div className="opts-hint">{t.desktopDesc}</div>
      <div style={{ margin: ".5rem 0", display: "flex", gap: ".5rem", flexWrap: "wrap" }}>
        {!running ? (
          <button type="button" className="start" disabled={busy !== null} onClick={() => void handleStart()}>
            {busy === "start" ? t.desktopStarting : t.desktopStartBtn}
          </button>
        ) : (
          <>
            <button type="button" className="stop" disabled={busy !== null} onClick={() => void handleStop()}>
              {busy === "stop" ? t.desktopStopping : t.desktopStopBtn}
            </button>
            <button type="button" className={control ? "stop" : "start"} onClick={() => setControlWanted((v) => !v)}>
              {control ? t.desktopControlOffBtn : t.desktopControlOnBtn}
            </button>
            <label className="fresh-toggle">
              <input type="checkbox" checked={showCursor} onChange={(e) => setShowCursor(e.target.checked)} />{" "}
              {t.desktopCursorToggle}
            </label>
          </>
        )}
      </div>
      {running && control && <div className="opts-hint">{t.desktopControlHint}</div>}
      {running && (
        <div className={`desktop-viewport${control ? " controlling" : ""}`}>
          {frameUrl ? (
            <div className="desktop-frame">
              <img
                ref={imgRef}
                src={frameUrl}
                alt=""
                draggable={false}
                onPointerDown={handlePointerDown}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
                onPointerCancel={handlePointerUp}
                onWheel={handleWheel}
                onContextMenu={(e) => control && e.preventDefault()}
              />
              {markerStyle && <div className="desktop-cursor-marker" style={markerStyle} />}
            </div>
          ) : (
            <div className="opts-hint">{connected ? t.desktopWaitingFrame : t.desktopConnecting}</div>
          )}
        </div>
      )}
      {running && (
        <input
          ref={hiddenInputRef}
          type="text"
          tabIndex={-1}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          onKeyDown={handleKeyDown}
          onInput={handleHiddenInput}
          style={{ position: "absolute", opacity: 0, width: 1, height: 1, pointerEvents: "none", fontSize: 16 }}
        />
      )}
    </div>
  );
}
