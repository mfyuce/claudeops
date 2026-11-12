/**
 * Shared jittered exponential-backoff formula for the two WS-primary hooks
 * (`useStatus.ts`, `useTermOutput.ts`) — extracted so the same reconnect
 * behavior doesn't drift into two copies (both need it identically, and
 * this session already hit a real bug elsewhere caused by exactly that
 * kind of drift — a backend kill-mechanism duplicated instead of shared).
 */

export const WS_RECONNECT_BASE_MS = 1_000;
export const WS_RECONNECT_CAP_MS = 20_000;

/** "Equal jitter" around an exponential-backoff delay: half fixed, half
 * random — `attempt` 0 → 0.5-1s, doubling each retry up to a 10-20s spread
 * once the exponential part saturates the cap. Never near-zero (unlike
 * "full jitter", `random(0, cap)`), which matters since the far more common
 * case than a real outage is a normal server-restart during a `npm run dev`
 * / redeploy — a fixed floor avoids every open tab hammering the
 * not-yet-listening port in a tight loop, while the random half still
 * avoids every tab retrying in lockstep once it does come back. */
export function reconnectDelayMs(attempt: number): number {
  const exp = Math.min(WS_RECONNECT_CAP_MS, WS_RECONNECT_BASE_MS * 2 ** attempt);
  return exp / 2 + Math.random() * (exp / 2);
}

export interface ReconnectingWsOptions {
  /** URL her (yeniden) bağlanmada yeniden hesaplanır (token/parametre değişebilir). */
  url: () => string;
  /** JSON.parse edilmiş çerçeve; bozuk çerçeve sessizce atılır. */
  onMessage: (frame: unknown) => void;
  /** Bu bağlantı döngüsünün İLK kapanışı (hiç açılmamış, deneme sayacı 0): ör. anında REST yoklaması. */
  onFirstClose?: () => void;
  /** Sekme öne gelince, WS açık olsun olmasın (gerekirse yeniden bağlanmayı denedikten SONRA) çağrılır. */
  onForeground?: () => void;
}

/** WS bağlan/yeniden bağlan/görünürlük/temizlik iskeleti: `useStatus.ts` ile `useTermOutput.ts` aynı kopyayı taşıyordu.
 * Geri dönen fonksiyon temizliktir (zamanlayıcı, dinleyici, soket). Davranış, iki kancanın önceki satır içi sürümüyle birebir. */
export function openReconnectingWs(opts: ReconnectingWsOptions): () => void {
  let alive = true;
  let ws: WebSocket | null = null;
  let timer: number | null = null;
  let attempt = 0;

  const clearTimer = () => {
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
  };

  const scheduleReconnect = () => {
    if (!alive || timer !== null) return;
    const delay = reconnectDelayMs(attempt);
    attempt += 1;
    timer = window.setTimeout(() => {
      timer = null;
      connect();
    }, delay);
  };

  function connect() {
    if (!alive) return;
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;   // ikinci soket açma
    let sock: WebSocket;
    try {
      sock = new WebSocket(opts.url());
    } catch {
      scheduleReconnect();
      return;
    }
    ws = sock;
    sock.onopen = () => {
      attempt = 0;   // yeni el sıkışma başarılı: ağ yolu çalışıyor
    };
    sock.onmessage = (ev: MessageEvent<string>) => {
      if (!alive) return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(ev.data);
      } catch {
        return;
      }
      opts.onMessage(parsed);
    };
    sock.onerror = () => {
      // Bilerek boş: `onclose` her zaman hemen ardından gelir; ikisinden planlamak çift zamanlayıcı kurar.
    };
    sock.onclose = () => {
      if (ws === sock) ws = null;
      if (!alive) return;
      if (attempt === 0) opts.onFirstClose?.();
      scheduleReconnect();
    };
  }

  connect();

  const onVisibilityChange = () => {
    if (document.visibilityState !== "visible") return;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      attempt = 0;   // ön plana dönmek ağın değiştiğine güçlü işaret: hemen dene
      clearTimer();
      connect();
    }
    opts.onForeground?.();
  };
  document.addEventListener("visibilitychange", onVisibilityChange);

  return () => {
    alive = false;
    document.removeEventListener("visibilitychange", onVisibilityChange);
    clearTimer();
    const s = ws;
    ws = null;
    if (s) {
      s.onopen = null;
      s.onmessage = null;
      s.onerror = null;
      s.onclose = null;
      s.close();
    }
  };
}
