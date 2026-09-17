/**
 * A tab's top-level descriptive/warning text, collapsed behind a small
 * (i) toggle instead of always taking up space (2026-09-17, user:
 * "tablarin ustundeki aciklamalari gerekirse acilabilir veya popup da
 * gsterilebilir hale getirelim"). Picked accordion/expand-in-place over a
 * popup - it matches this app's existing expand/collapse language
 * (CwdCell's click-to-expand, CollapseControls' group toggle) and needs
 * no popup-positioning logic, which especially matters on the narrow/
 * mobile layouts this panel is regularly used from.
 *
 * Reuses the existing `.opts-hint`/`.warn-banner` classes for the revealed
 * text itself (same look as before, just hidden until asked for) - only
 * the toggle button and its wrapper are new.
 */

import { useState, type ReactNode } from "react";
import { useLang } from "../../i18n/LangContext";

export function TabHint({ children, warn }: { children: ReactNode; warn?: boolean }) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  return (
    <div className="tab-hint">
      <button type="button" className="tab-hint-toggle" aria-expanded={open} title={t.tabHintToggle} onClick={() => setOpen((v) => !v)}>
        ⓘ
      </button>
      {open && <div className={warn ? "warn-banner" : "opts-hint"}>{children}</div>}
    </div>
  );
}
