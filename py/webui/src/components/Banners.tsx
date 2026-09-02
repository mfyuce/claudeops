/**
 * Replaces the original `render()`'s banner block (web.py ~1527-1535):
 * config-error, duplicate-names, and fallback-alert banners.
 */

import type { ReactNode } from "react";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";

interface BannersProps {
  /** The fallback-alert banner's button jumps to the Diagnostics tab
   * (original: `onclick="setTab('diag')"`) — `App` owns `activeTab`, so
   * this is passed down rather than reaching for a tab-switch Context. */
  onGoToDiagnostics: () => void;
}

export function Banners({ onGoToDiagnostics }: BannersProps) {
  const { t } = useLang();
  const { data } = useStatusContext();

  const banners: ReactNode[] = [];
  if (data && !data.config_ok) {
    banners.push(
      <div className="banner bad" key="config">
        ⚠ {t.configMsg(data.config_code, data.config_detail)}
      </div>,
    );
  }
  if (data && data.dups.length) {
    banners.push(
      <div className="banner bad" key="dups">
        {t.dupWarn}
        {data.dups.join(", ")}
      </div>,
    );
  }
  if (data && data.diag.fallback_alert) {
    banners.push(
      <div className="banner bad" key="fallback">
        {t.fallbackAlertMsg(data.diag.recent_fallback_count, data.diag.fallback_alert_window_minutes)}{" "}
        <button type="button" className="start" onClick={onGoToDiagnostics}>
          {t.fallbackAlertBtn}
        </button>
      </div>,
    );
  }

  return <div id="banners">{banners}</div>;
}
