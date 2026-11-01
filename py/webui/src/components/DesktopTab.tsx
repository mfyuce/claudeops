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
import { apiDesktopStart, apiDesktopStop, TOKEN, withToken } from "../api/client";
import { callAction } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import { UzakgozSettings } from "./UzakgozSettings";
import { VirtualKeyboard, type ModName } from "./VirtualKeyboard";

type MouseButtonName = "left" | "middle" | "right";

type InputEvent =
  | { t: "move"; x: number; y: number }
  | { t: "down"; b: MouseButtonName }
  | { t: "up"; b: MouseButtonName }
  | { t: "scroll"; dx: number; dy: number }
  | { t: "key"; k: string; a: "click" | "down" | "up" }
  | { t: "text"; s: string }
  | { t: "cfg"; quality?: number; scale?: number; fps?: number };

/** Stream presets sent as `cfg` (daemon clamps: quality 10-95, scale 10-100 %, fps 1-30). */
const PRESETS: Record<string, { quality: number; scale: number; fps: number }> = {
  fast: { quality: 50, scale: 60, fps: 12 },
  balanced: { quality: 70, scale: 100, fps: 15 },
  sharp: { quality: 85, scale: 100, fps: 20 },
};

type StreamInfo = { w: number; h: number };

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
  const [info, setInfo] = useState<StreamInfo | null>(null);
  const [fps, setFps] = useState(0);
  const framesRef = useRef(0);
  const urlRef = useRef<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!active) return;
    const ws = new WebSocket(desktopWsUrl());
    wsRef.current = ws;
    ws.binaryType = "blob";
    ws.onopen = () => setConnected(true);
    const fpsTimer = window.setInterval(() => {
      setFps(framesRef.current);
      framesRef.current = 0;
    }, 1000);
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        try {
          const msg = JSON.parse(ev.data) as { t?: string; x?: number; y?: number; w?: number; h?: number };
          if (msg.t === "cursor" && typeof msg.x === "number" && typeof msg.y === "number") {
            setCursor({ x: msg.x, y: msg.y });
          } else if (msg.t === "info" && typeof msg.w === "number" && typeof msg.h === "number") {
            // Full SCREEN size: input/cursor coordinates live in this space even when scaled frames are smaller.
            setInfo({ w: msg.w, h: msg.h });
          }
        } catch {
          // Ignore malformed control messages — never worth dropping the stream over.
        }
        return;
      }
      framesRef.current += 1;
      const nextUrl = URL.createObjectURL(ev.data as Blob);
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = nextUrl;
      setFrameUrl(nextUrl);
    };
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    return () => {
      window.clearInterval(fpsTimer);
      wsRef.current = null;
      ws.close();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
      setFrameUrl(null);
      setConnected(false);
      setCursor(null);
      setInfo(null);
      setFps(0);
    };
  }, [active]);

  function sendInput(event: InputEvent) {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(event));
  }

  return { frameUrl, connected, cursor, info, fps, sendInput };
}

export function DesktopTab() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [busy, setBusy] = useState<"start" | "stop" | null>(null);
  const [audioOn, setAudioOn] = useState(false);
  const [audioError, setAudioError] = useState(false);
  const [controlWanted, setControlWanted] = useState(false);
  const [showCursor, setShowCursor] = useState(true);
  const [showKeyboard, setShowKeyboard] = useState(false);
  const [preset, setPreset] = useState("balanced");

  const running = data?.remote_desktop.running ?? false;
  const control = controlWanted && running; // can't control a stopped/stopping stream
  const { frameUrl, connected, cursor, info, fps, sendInput } = useDesktopStream(running);

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
    const w = info?.w || img?.naturalWidth || 0;
    const h = info?.h || img?.naturalHeight || 0;
    if (!w || !h) {
      setMarkerStyle(null);
      return;
    }
    setMarkerStyle({ left: `${(cursor.x / w) * 100}%`, top: `${(cursor.y / h) * 100}%` });
  }, [cursor, showCursor, info]);

  // Send the chosen quality preset whenever the stream (re)connects or the choice changes.
  useEffect(() => {
    if (connected) sendInput({ t: "cfg", ...PRESETS[preset] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, preset]);

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
    // Input coordinates are in FULL SCREEN pixels (`info`), not in the (possibly scaled-down) frame's own pixels.
    const w = info?.w || img?.naturalWidth || 0;
    const h = info?.h || img?.naturalHeight || 0;
    if (!img || !w || !h) return null;
    const rect = img.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    const x = Math.round(((clientX - rect.left) / rect.width) * w);
    const y = Math.round(((clientY - rect.top) / rect.height) * h);
    return { x: Math.max(0, Math.min(w - 1, x)), y: Math.max(0, Math.min(h - 1, y)) };
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

  /** Modifier burst: `mod down ... key click ... mod up` in one go, so no modifier can stay held remotely. */
  function sendCombo(mods: ModName[], key: string) {
    if (!control) return;
    for (const m of mods) sendInput({ t: "key", k: m, a: "down" });
    if (key) sendInput({ t: "key", k: key, a: "click" });
    else if (mods.length === 1) sendInput({ t: "key", k: mods[0], a: "click" });   // bare "Win"
    for (const m of [...mods].reverse()) sendInput({ t: "key", k: m, a: "up" });
  }

  function handleKeyDown(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (!control) return;
    // Physical Ctrl/Alt/Meta + a key (Ctrl+C...): forwarded as one burst. Combos the browser itself reserves never arrive.
    if ((e.ctrlKey || e.altKey || e.metaKey) && !["Control", "Alt", "Meta", "Shift"].includes(e.key)) {
      const mods: ModName[] = [];
      if (e.ctrlKey) mods.push("Control");
      if (e.altKey) mods.push("Alt");
      if (e.metaKey) mods.push("Meta");
      if (e.shiftKey) mods.push("Shift");
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      if (key.length === 1 || NAMED_KEYS.has(key)) {
        e.preventDefault();
        sendCombo(mods, key);
        return;
      }
    }
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
      <div style={{ margin: ".5rem 0", display: "flex", gap: ".5rem", flexWrap: "wrap", alignItems: "center" }}>
        <button
          type="button"
          className={audioOn ? "stop" : "start"}
          onClick={() => { setAudioError(false); setAudioOn((v) => !v); }}
        >
          {audioOn ? t.audioOffBtn : t.audioOnBtn}
        </button>
        {audioOn && (
          <audio
            autoPlay
            controls
            src={withToken("/api/audio/live.mp3")}
            onError={() => { setAudioOn(false); setAudioError(true); }}
            style={{ height: "2rem" }}
          />
        )}
        <span className="opts-hint">{audioError ? t.audioError : t.audioHint}</span>
      </div>
      <UzakgozSettings />
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
            <button type="button" className={showKeyboard ? "stop" : "start"} onClick={() => setShowKeyboard((v) => !v)}>
              {lang === "tr" ? "Klavye" : "Keyboard"}
            </button>
            <label>
              {lang === "tr" ? "kalite" : "quality"}{" "}
              <select value={preset} onChange={(e) => setPreset(e.target.value)}>
                <option value="fast">{lang === "tr" ? "hızlı (mobil)" : "fast (mobile)"}</option>
                <option value="balanced">{lang === "tr" ? "dengeli" : "balanced"}</option>
                <option value="sharp">{lang === "tr" ? "net" : "sharp"}</option>
              </select>
            </label>
            <span className="opts-hint">{fps} fps</span>
            <label className="fresh-toggle">
              <input type="checkbox" checked={showCursor} onChange={(e) => setShowCursor(e.target.checked)} />{" "}
              {t.desktopCursorToggle}
            </label>
          </>
        )}
      </div>
      {running && control && <div className="opts-hint">{t.desktopControlHint}</div>}
      {running && showKeyboard && (
        control ? (
          <VirtualKeyboard
            lang={lang}
            onKey={sendCombo}
            onText={(s) => sendInput({ t: "text", s })}
          />
        ) : (
          <div className="opts-hint">{lang === "tr" ? "Klavye için önce Kontrolü Al." : "Take control first to use the keyboard."}</div>
        )
      )}
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
