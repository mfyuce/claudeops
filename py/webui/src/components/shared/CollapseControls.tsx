/** Single collapse/expand-all TOGGLE for a grouped tab — shared by
 * RegisteredTab/RunningTab/GroupTable. One button, not two (2026-09-14,
 * user: "bu tablo ustunde tek button olsun => collapse icin arti collapse
 * icin eksi gibi") — shows "+" when collapsing-further is the useful action
 * (nothing/not-everything expanded: click to expand all) and "−" when
 * anything is currently expanded (click to collapse all), mirroring the
 * same +/− affordance convention as a single tree node's own toggle, just
 * for "all of them" at once instead of one row.
 *
 * `groupKeys` is the CURRENT (already filtered/paginated-or-not, caller's
 * choice) set of group keys — passed in rather than owned here, same
 * reasoning as `useGroupCollapse.expandAll`. `isExpanded` is the same
 * per-key lookup `useGroupCollapse()` already returns to callers — reused
 * here to derive the aggregate state instead of the hook needing its own
 * "any expanded" accessor. */
import { useLang } from "../../i18n/LangContext";

interface CollapseControlsProps {
  groupKeys: string[];
  isExpanded: (key: string) => boolean;
  onCollapseAll: () => void;
  onExpandAll: (keys: string[]) => void;
}

export function CollapseControls({ groupKeys, isExpanded, onCollapseAll, onExpandAll }: CollapseControlsProps) {
  const { t } = useLang();
  if (groupKeys.length === 0) return null;
  const anyExpanded = groupKeys.some(isExpanded);
  return (
    <div className="opts-hint" style={{ marginBottom: ".3rem" }}>
      <button
        type="button"
        title={anyExpanded ? t.collapseAllBtn : t.expandAllBtn}
        onClick={() => (anyExpanded ? onCollapseAll() : onExpandAll(groupKeys))}
      >
        {anyExpanded ? "−" : "+"}
      </button>
    </div>
  );
}
