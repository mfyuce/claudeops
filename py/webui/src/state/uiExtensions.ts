/** K10: tabs contributed by installed extension packages. Fetched once at start; any failure = empty list (panel keeps working). */
import { useEffect, useState } from "react";
import { getUiExtensions } from "../api/client";
import type { UiExtension } from "../api/types";

export function useUiExtensions(): { extensions: UiExtension[]; loaded: boolean } {
  const [state, setState] = useState<{ extensions: UiExtension[]; loaded: boolean }>({ extensions: [], loaded: false });
  useEffect(() => {
    let cancelled = false;
    void getUiExtensions().then((r) => {
      if (!cancelled) setState({ extensions: r.extensions, loaded: true });
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}
