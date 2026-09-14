/** "Collapse all" / "Expand all" button pair for a grouped tab — shared by
 * RegisteredTab/RunningTab/GroupTable. `groupKeys` is the CURRENT (already
 * filtered/paginated-or-not, caller's choice) set of group keys to expand
 * to — passed in rather than owned here, same reasoning as
 * `useGroupCollapse.expandAll`. */
import { useLang } from "../../i18n/LangContext";

interface CollapseControlsProps {
  groupKeys: string[];
  onCollapseAll: () => void;
  onExpandAll: (keys: string[]) => void;
}

export function CollapseControls({ groupKeys, onCollapseAll, onExpandAll }: CollapseControlsProps) {
  const { t } = useLang();
  if (groupKeys.length === 0) return null;
  return (
    <div className="opts-hint" style={{ display: "flex", gap: ".4rem", marginBottom: ".3rem" }}>
      <button type="button" onClick={onCollapseAll}>
        {t.collapseAllBtn}
      </button>
      <button type="button" onClick={() => onExpandAll(groupKeys)}>
        {t.expandAllBtn}
      </button>
    </div>
  );
}
