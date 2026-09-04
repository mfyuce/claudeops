/**
 * Global name/cwd filter box, rendered in App.tsx ABOVE <TabBar> (2026-09-04
 * request: "tabların üstüne arama kutusu" — literally above the tabs, not
 * inside any one tab's content, so it stays visible across tab switches and
 * keeps filtering whichever of the 4 list tabs — Running/Registered/
 * Disabled/Retired — is active; Layout/Diag/Settings simply ignore it).
 * State lives in AppShell (App.tsx), not here — plain controlled input.
 */

import { useLang } from "../../i18n/LangContext";

interface SearchBoxProps {
  value: string;
  onChange: (value: string) => void;
}

export function SearchBox({ value, onChange }: SearchBoxProps) {
  const { t } = useLang();
  return (
    <div className="searchbox">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={t.searchPlaceholder}
        aria-label={t.searchPlaceholder}
      />
      {value && (
        <button type="button" className="search-clear" onClick={() => onChange("")} aria-label={t.searchClear} title={t.searchClear}>
          ×
        </button>
      )}
    </div>
  );
}
