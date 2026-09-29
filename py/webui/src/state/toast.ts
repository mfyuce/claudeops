/**
 * Non-blocking replacement for `window.alert()` (2026-09-29 TODO: native
 * alert() freezes the whole UI until dismissed, especially bad on
 * mobile). Plain module-level pub-sub, NOT a React Context: most callers
 * (`api/errors.ts`'s `callAction`, and every component's own catch block)
 * fire from plain async functions/event handlers, never from inside a
 * render — a hook-based Context wouldn't reach them. Any module can
 * import `showToast` directly; `<ToastContainer>` (mounted once in
 * `App.tsx`) is the only thing that needs to subscribe.
 */

export type ToastKind = "error" | "success" | "info";

export interface ToastMessage {
  id: number;
  text: string;
  kind: ToastKind;
}

type Listener = (toasts: ToastMessage[]) => void;

const DURATION_MS: Record<ToastKind, number> = {
  error: 6000,
  info: 5000,
  success: 3000,
};

// Hard cap so a bulk action failing N times in a row can't paper the
// whole screen — oldest drops early instead of growing an unbounded stack.
const MAX_VISIBLE = 5;

let toasts: ToastMessage[] = [];
let nextId = 1;
const listeners = new Set<Listener>();

function emit(): void {
  for (const listener of listeners) listener(toasts);
}

export function showToast(text: string, kind: ToastKind = "error"): void {
  const id = nextId++;
  toasts = [...toasts, { id, text, kind }].slice(-MAX_VISIBLE);
  emit();
  window.setTimeout(() => dismissToast(id), DURATION_MS[kind]);
}

export function dismissToast(id: number): void {
  toasts = toasts.filter((toast) => toast.id !== id);
  emit();
}

export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener);
  listener(toasts);
  return () => listeners.delete(listener);
}
