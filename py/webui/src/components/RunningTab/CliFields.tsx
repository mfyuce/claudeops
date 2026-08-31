/**
 * Replaces the original `renderCliFields()` (web.py ~1934-1963) — the
 * model/permission-mode/effort fields shared by both `OptionsRow` and
 * `AdoptRow`, exactly as the original shared one function for both
 * `unifiedOptsRow()` and `adoptOptsRow()`. Not named in the plan's
 * component table (which only lists whole rows), added here purely to
 * avoid duplicating this block twice — it holds no state of its own
 * (fully controlled via props), so it doesn't touch the plan's "local
 * useState in OptionsRow/AdoptRow, no shadow dict" requirement: the state
 * still lives in whichever of those two components renders this.
 *
 * One deliberate, documented improvement over the original: the model
 * `<select>` here is a normal React-controlled element bound to `model`
 * by `value`, so selecting "…" (value `"__other__"`) always shows as
 * selected on every re-render. The original built this same option list
 * as an HTML string and text-replaced `value="…"` with `value="__other__"`
 * *after* deciding which option got the `selected` attribute by comparing
 * against the raw label "…" — so `saved.model === '__other__'` (the only
 * way it's ever set, via the real onchange handler) never matched the
 * label text, and after any re-render the visible dropdown silently
 * reverted to showing the "(current)" placeholder while the free-text
 * input stayed visible underneath it. That's a latent quirk of building
 * option lists as strings, not a behavior worth reproducing — a
 * controlled `<select>` just doesn't have this failure mode.
 */

import { useLang } from "../../i18n/LangContext";
import type { CliOptions } from "../../api/types";

export const OTHER_MODEL_VALUE = "__other__";

interface CliFieldsProps {
  /** Label shown inside the "(...)" placeholder option — the session's
   * current model when the row's CLI hasn't been changed from its own,
   * otherwise the newly-chosen CLI's first model (matches the original
   * passing `currentModel=''` through `onCliChange` -> `renderCliFields`,
   * which falls back to `opts.models[0]`). */
  currentModelLabel: string;
  model: string;
  modelOther: string;
  permissionMode: string;
  effort: string;
  cliOptions: CliOptions;
  onModelChange: (value: string) => void;
  onModelOtherChange: (value: string) => void;
  onPermissionModeChange: (value: string) => void;
  onEffortChange: (value: string) => void;
}

export function CliFields({
  currentModelLabel,
  model,
  modelOther,
  permissionMode,
  effort,
  cliOptions,
  onModelChange,
  onModelOtherChange,
  onPermissionModeChange,
  onEffortChange,
}: CliFieldsProps) {
  const { t } = useLang();
  return (
    <>
      <label>
        {t.modelLabel}
        <select value={model} onChange={(e) => onModelChange(e.target.value)}>
          <option value="">({currentModelLabel})</option>
          {cliOptions.models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
          <option value={OTHER_MODEL_VALUE}>…</option>
        </select>
      </label>
      {model === OTHER_MODEL_VALUE && (
        <input
          type="text"
          placeholder="model id"
          value={modelOther}
          onChange={(e) => onModelOtherChange(e.target.value)}
        />
      )}
      <label>
        {t.pmLabel}
        <select value={permissionMode} onChange={(e) => onPermissionModeChange(e.target.value)}>
          {cliOptions.permission_modes.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t.effortLabel}
        <select value={effort} onChange={(e) => onEffortChange(e.target.value)}>
          {cliOptions.effort_levels.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}
