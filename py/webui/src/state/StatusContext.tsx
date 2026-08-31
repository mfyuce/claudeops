/**
 * `StatusContext` — thin Context wrapper around `useStatus()`. Per the
 * plan: "nearly every component needs a slice of this, prop-drilling buys
 * nothing" — `RunningTab`/`RegisteredTab`/`SessionRow`/`OptionsRow`/
 * `AdoptRow`/`BulkBar`/`TabBar`/`Banners` all read it directly instead of
 * receiving `data`/`refresh` as props.
 */

import { createContext, useContext, type ReactNode } from "react";
import { useStatus, type UseStatusResult } from "../hooks/useStatus";

const StatusContext = createContext<UseStatusResult | null>(null);

export function StatusProvider({ children }: { children: ReactNode }) {
  const status = useStatus();
  return <StatusContext.Provider value={status}>{children}</StatusContext.Provider>;
}

export function useStatusContext(): UseStatusResult {
  const ctx = useContext(StatusContext);
  if (!ctx) throw new Error("useStatusContext() must be used within a <StatusProvider>");
  return ctx;
}
