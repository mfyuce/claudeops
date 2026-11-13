/**
 * "Uzak Masaüstü" sekmesi. Görüntüleyici (kare akışı, Kontrol, klavye, kalite, pano, monitör) uzakgoz
 * daemon'unun `viewer.js` dosyasıdır; claudeops web sunucusu onu `/desktop/viewer.js` altında token
 * kontrolüyle sunar, WebSocket `/ws/desktop` ham-bayt proxy'sinden akar. Bu bileşen yalnız başlat/durdur,
 * ayarlar ve (claudeops'un kendi) ses düğmesini barındırır.
 */
import { useEffect, useRef, useState } from "react";
import { apiDesktopStart, apiDesktopStop, TOKEN, withToken } from "../api/client";
import { callAction } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import { GraphicalSession } from "./GraphicalSession";
import { UzakgozSettings } from "./UzakgozSettings";

type Viewer = { destroy: () => void };
type MountViewer = (root: HTMLElement, opts: { url: string; control?: boolean; preset?: string }) => Viewer;

function desktopWsUrl(): string {
  const scheme = location.protocol === "https:" ? "wss://" : "ws://";
  return `${scheme}${location.host}/ws/desktop?token=${encodeURIComponent(TOKEN)}`;
}

/** How long `running` may read false before the viewer is torn down. The status poll can show `running:false` for a
 * moment (slow/lost poll, daemon restart blip, phone tab switch); remounting on every blip dropped the stream. */
const RUNNING_GRACE_MS = 8000;

/** `running` made stable: goes true at once, goes false only after `graceMs` of continuous false. When the user pressed
 * Stop (`stopRequested.current`), false applies immediately so the viewer disappears with the daemon. */
function useStableRunning(running: boolean, stopRequested: React.MutableRefObject<boolean>, graceMs = RUNNING_GRACE_MS): boolean {
  const [stable, setStable] = useState(running);
  useEffect(() => {
    if (running) {
      stopRequested.current = false;
      setStable(true);
      return;
    }
    if (stopRequested.current) {
      setStable(false);
      return;
    }
    const id = window.setTimeout(() => setStable(false), graceMs);
    return () => window.clearTimeout(id);
  }, [running, graceMs, stopRequested]);
  return stable;
}

/** Daemon'un viewer.js'ini gömer; `running` bitince yok eder. */
function useEmbeddedViewer(running: boolean, rootRef: React.RefObject<HTMLDivElement | null>) {
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!running) return;
    let viewer: Viewer | null = null;
    let cancelled = false;
    setError(null);
    (async () => {
      try {
        const mod = (await import(/* @vite-ignore */ withToken("/desktop/viewer.js"))) as { mountViewer: MountViewer };
        if (cancelled || !rootRef.current) return;
        viewer = mod.mountViewer(rootRef.current, { url: desktopWsUrl() });
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
      try { viewer?.destroy(); } catch { /* sekme kapanırken */ }
    };
  }, [running, rootRef]);
  return error;
}

export function DesktopTab() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [busy, setBusy] = useState<"start" | "stop" | null>(null);
  const [audioOn, setAudioOn] = useState(false);
  const [audioError, setAudioError] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const stopRequested = useRef(false);
  const running = data?.remote_desktop.running ?? false;
  const viewerUp = useStableRunning(running, stopRequested);
  const viewerError = useEmbeddedViewer(viewerUp, rootRef);

  async function handleStart() {
    setBusy("start");
    await callAction(() => apiDesktopStart(lang), "desktop", t);
    setBusy(null);
    refresh();
  }

  async function handleStop() {
    setBusy("stop");
    stopRequested.current = true;
    await callAction(() => apiDesktopStop(lang), "desktop", t);
    setBusy(null);
    refresh();
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
      <GraphicalSession />
      <UzakgozSettings />
      <div style={{ margin: ".5rem 0", display: "flex", gap: ".5rem", flexWrap: "wrap" }}>
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
      {viewerUp && viewerError && <div className="opts-hint">viewer.js: {viewerError}</div>}
      {viewerUp && <div ref={rootRef} className="desktop-viewport" style={{ height: "70vh" }} />}
    </div>
  );
}
