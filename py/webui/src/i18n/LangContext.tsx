import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { STRINGS, type Lang, type Strings } from "./strings";

const STORAGE_KEY = "cops_lang"; // same key as the original PAGE_HTML JS

/**
 * Same default logic as the original `let LANG = localStorage.getItem('cops_lang')
 * || (navigator.language.toLowerCase().startsWith('tr') ? 'tr' : 'en');` —
 * localStorage first, then navigator.language, defaulting to 'en'.
 * localStorage access is wrapped in try/catch: it can throw in some
 * contexts (private browsing, storage disabled) even though this app
 * doesn't run inside an iframe today — matches the original's own
 * `try { localStorage.setItem(...) } catch (e) {}` defensiveness in `setLang`.
 */
function detectDefaultLang(): Lang {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "tr" || stored === "en") return stored;
  } catch {
    // ignore — fall through to navigator.language
  }
  return navigator.language.toLowerCase().startsWith("tr") ? "tr" : "en";
}

interface LangContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  /** Resolved strings for the current language — call sites use `t.someKey`
   * (or `t.someFn(args)`), which `tsc` checks against `Strings` at compile
   * time. This is the React-idiomatic replacement for the original's
   * `t(key)` lookup function of the same name. */
  t: Strings;
}

const LangContext = createContext<LangContextValue | null>(null);

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectDefaultLang);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // ignore, same as the original's setLang()
    }
  }, []);

  return <LangContext.Provider value={{ lang, setLang, t: STRINGS[lang] }}>{children}</LangContext.Provider>;
}

export function useLang(): LangContextValue {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useLang() must be used within a <LangProvider>");
  return ctx;
}
