/**
 * "Uzak Masaüstü" tab (2026-09-04, kullanıcı: "bir yeni tab da remote
 * desktoplar için çalışmaya başlayalım. gerekirse rust kodu yazalım") —
 * on-demand, view-only screen sharing. Backend is `rust/screenshare` (a
 * small X11-capture + JPEG + WebSocket daemon, spawned/killed by
 * `remote_desktop.py`, localhost-only/no auth of its own — this tab's
 * `/ws/desktop` connection reuses the SAME `?token=` this whole page
 * already loaded with, proxied by `web.py`'s `_proxy_desktop_ws`).
 *
 * Deliberately NOT interactive (no mouse/keyboard forwarding) — see
 * TODO.md's "Uzak Masaüstü" entry for why that's a separate, higher-stakes
 * fast-follow, not part of this first slice.
 *
 * `useDesktopStream` renders frames via `<img src={blob URL}>` rather than
 * `<canvas>` — simpler (no manual JPEG decode/draw), and at ~2 fps there's
 * no meaningful performance difference. Each new frame's object URL
 * replaces (and revokes) the previous one so the browser never accumulates
 * blob memory across a long-running session.
 */
import { useEffect, useRef, useState } from "react";
import { apiDesktopStart, apiDesktopStop, TOKEN } from "../api/client";
import { callAction } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";

function desktopWsUrl(): string {
  const scheme = location.protocol === "https:" ? "wss://" : "ws://";
  return `${scheme}${location.host}/ws/desktop?token=${encodeURIComponent(TOKEN)}`;
}

function useDesktopStream(active: boolean) {
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    if (!active) return;
    const ws = new WebSocket(desktopWsUrl());
    ws.binaryType = "blob";
    ws.onopen = () => setConnected(true);
    ws.onmessage = (ev) => {
      const nextUrl = URL.createObjectURL(ev.data as Blob);
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = nextUrl;
      setFrameUrl(nextUrl);
    };
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    return () => {
      ws.close();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
      setFrameUrl(null);
      setConnected(false);
    };
  }, [active]);

  return { frameUrl, connected };
}

export function DesktopTab() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [busy, setBusy] = useState<"start" | "stop" | null>(null);

  const running = data?.remote_desktop.running ?? false;
  const { frameUrl, connected } = useDesktopStream(running);

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

  if (!data) return null;

  return (
    <div>
      <div className="opts-hint">{t.desktopDesc}</div>
      <div style={{ margin: ".5rem 0" }}>
        {!running ? (
          <button type="button" className="start" disabled={busy !== null} onClick={() => void handleStart()}>
            {busy === "start" ? t.desktopStarting : t.desktopStartBtn}
          </button>
        ) : (
          <button type="button" className="stop" disabled={busy !== null} onClick={() => void handleStop()}>
            {busy === "stop" ? t.desktopStopping : t.desktopStopBtn}
          </button>
        )}
      </div>
      {running && (
        <div className="desktop-viewport">
          {frameUrl ? (
            <img src={frameUrl} alt="" />
          ) : (
            <div className="opts-hint">{connected ? t.desktopWaitingFrame : t.desktopConnecting}</div>
          )}
        </div>
      )}
    </div>
  );
}
