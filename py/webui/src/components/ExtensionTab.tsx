/**
 * Host for an extension-contributed tab (K10). Loads the bundle with a dynamic `import()` from the same origin
 * (the DesktopTab/viewer.js precedent), checks `uiApi`, and calls `mount(el, ctx) -> {destroy}`. Every failure
 * (import error, version mismatch, `mount` throwing) is shown inside the tab; the rest of the panel keeps working.
 */
import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { withToken } from "../api/client";
import type { UiExtension } from "../api/types";
import { makeExtCtx, UI_EXTENSION_API } from "../extensions/ctx";
import { useLang } from "../i18n/LangContext";
import { showToast } from "../state/toast";

interface ExtModule {
  uiApi?: number;
  mount?: (el: HTMLElement, ctx: unknown) => { destroy?: () => void } | void;
}

/** Catches React render errors of the extension host. Exceptions inside the extension's own DOM event handlers are
 * outside any React boundary: the extension must handle its own (part of the contract). */
export class ExtensionBoundary extends Component<{ children: ReactNode; label: string }, { error: string | null }> {
  state = { error: null as string | null };
  static getDerivedStateFromError(e: unknown) {
    return { error: String(e) };
  }
  render() {
    if (this.state.error) return <div className="opts-hint" role="alert">{this.props.label}: {this.state.error}</div>;
    return this.props.children;
  }
}

export function ExtensionTab({ ext, openSession, search = "" }: { ext: UiExtension; openSession: (host: string, name: string) => void; search?: string }) {
  const { t, lang } = useLang();
  const rootRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "incompatible" | "failed">("loading");
  const [error, setError] = useState("");
  // Üst arama kutusu eklentiye `ctx.search` ile akar (ctx yeniden kurulmaz: eklenti yeniden bağlanmasın).
  const searchRef = useRef(search);
  const listeners = useRef(new Set<(q: string) => void>());
  useEffect(() => {
    searchRef.current = search;
    listeners.current.forEach((fn) => {
      try {
        fn(search);
      } catch {
        // eklentinin kendi dinleyici hatası paneli bozmaz
      }
    });
  }, [search]);
  const ctx = useMemo(
    () =>
      makeExtCtx({
        lang,
        openSession,
        search: {
          get: () => searchRef.current,
          subscribe: (fn) => {
            listeners.current.add(fn);
            return () => listeners.current.delete(fn);
          },
        },
      }),
    [lang, openSession],
  );

  useEffect(() => {
    let cancelled = false;
    let handle: { destroy?: () => void } | void = undefined;
    const root = rootRef.current;
    (async () => {
      try {
        const mod = (await import(/* @vite-ignore */ withToken(ext.entry))) as ExtModule;
        if (cancelled || !root) return;
        if (mod.uiApi !== UI_EXTENSION_API || typeof mod.mount !== "function") {
          setStatus("incompatible");
          return;
        }
        handle = mod.mount(root, ctx);
        setStatus("ok");
      } catch (e) {
        if (cancelled) return;
        setError(String(e));
        setStatus("failed");
        showToast(`${t.extLoadFailed}: ${ext.id}`, "error");
      }
    })();
    return () => {
      cancelled = true;
      try {
        if (handle && typeof handle.destroy === "function") handle.destroy();
      } catch {
        // tab closing: a throwing destroy must not break navigation
      }
      if (root) root.textContent = "";
    };
  }, [ext.entry, ext.id, ctx, t.extLoadFailed]);

  return (
    <div>
      {status === "loading" && <div className="opts-hint" role="status">{t.extLoading}</div>}
      {status === "incompatible" && <div className="opts-hint" role="alert">{t.extIncompatible}: {ext.id}</div>}
      {status === "failed" && <div className="opts-hint" role="alert">{t.extLoadFailed}: {error}</div>}
      <div ref={rootRef} className="ext-root" />
    </div>
  );
}
