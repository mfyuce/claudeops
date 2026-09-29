/**
 * Fixed-position stack subscribed to `state/toast.ts`'s module-level
 * store — mounted once in `App.tsx`, near `<Banners>`. See that module's
 * header comment for why this isn't a Context.
 */

import { useEffect, useState } from "react";
import { dismissToast, subscribeToasts, type ToastMessage } from "../../state/toast";

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  useEffect(() => subscribeToasts(setToasts), []);

  if (!toasts.length) return null;
  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.kind}`} onClick={() => dismissToast(toast.id)}>
          <span className="toast-text">{toast.text}</span>
          <button
            type="button"
            className="toast-close"
            aria-label="dismiss"
            onClick={(e) => {
              e.stopPropagation();
              dismissToast(toast.id);
            }}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
