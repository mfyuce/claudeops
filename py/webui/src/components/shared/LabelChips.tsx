/**
 * Project label chips (labels.py): colored chips on a row, click = search `label:x`, × removes, "+" opens a small
 * popover (existing labels as toggles + a field for a new name). Used by Running/Registered/Disabled/Retired rows
 * and the steward project list. Labels live in the local store (`POST /api/labels`, human only); the status payload
 * carries `label_defs` (colors/descriptions) and `label_assign` (project key -> labels).
 */
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { apiLabels } from "../../api/client";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { useEscapeKey } from "./useEscapeKey";
import { showToast } from "../../state/toast";

/** App provides it: clicking a chip puts `label:x` into the global search box. */
export const LabelSearchContext = createContext<(label: string) => void>(() => {});

const NAME_OK = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const FALLBACK = "#6b7280";

export function LabelChips({ projectKey, labels }: { projectKey: string; labels?: string[] }) {
  const { lang } = useLang();
  const en = lang === "en";
  const { data, refresh } = useStatusContext();
  const onSearch = useContext(LabelSearchContext);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const box = useRef<HTMLSpanElement>(null);
  const defs = data?.label_defs ?? {};
  const current = labels ?? data?.label_assign?.[projectKey] ?? [];

  useEscapeKey(open ? () => setOpen(false) : undefined);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  if (!projectKey || !data?.label_defs) return null;

  async function change(add: string[], remove: string[]) {
    try {
      const res = await apiLabels({ name: projectKey, add, remove });
      if (!res.ok) showToast(res.error ?? "error", "error");
      refresh();
    } catch (e) {
      showToast(String(e), "error");
    }
  }

  function submitDraft() {
    const n = draft.trim().toLowerCase();
    if (!n) return;
    if (!NAME_OK.test(n)) {
      showToast(en ? "Label: a-z 0-9 _ -, max 32, start with letter/digit" : "Etiket: a-z 0-9 _ -, en çok 32, harf/rakamla başlar", "error");
      return;
    }
    setDraft("");
    void change([n], []);
  }

  return (
    <span className="label-chips" ref={box} onClick={(e) => e.stopPropagation()}>
      {current.map((l) => {
        const color = defs[l]?.color ?? FALLBACK;
        return (
          <span key={l} className="label-chip" style={{ borderColor: color, color }} title={defs[l]?.desc || l}>
            <button type="button" className="label-chip-name" style={{ color }} onClick={() => onSearch(l)} aria-label={`label:${l}`}>
              {l}
            </button>
            <button type="button" className="label-chip-x" style={{ color }} onClick={() => void change([], [l])}
              title={en ? `Remove ${l}` : `${l} etiketini kaldır`} aria-label={en ? `Remove ${l}` : `${l} etiketini kaldır`}>
              ×
            </button>
          </span>
        );
      })}
      <button type="button" className="label-add" onClick={() => setOpen((o) => !o)}
        title={en ? "Add / remove labels" : "Etiket ekle / çıkar"} aria-label={en ? "Add label" : "Etiket ekle"} aria-expanded={open}>
        +
      </button>
      {open && (
        <span className="label-pop" role="dialog">
          {Object.entries(defs).map(([n, d]) => {
            const on = current.includes(n);
            return (
              <button key={n} type="button" className={`label-opt${on ? " on" : ""}`} title={d.desc}
                onClick={() => void change(on ? [] : [n], on ? [n] : [])}>
                <span className="label-dot" style={{ background: d.color }} />
                {n}
                {on && <span className="label-tick">✓</span>}
              </button>
            );
          })}
          <input
            className="label-new"
            value={draft}
            placeholder={en ? "new label…" : "yeni etiket…"}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submitDraft(); } }}
            maxLength={32}
            autoFocus
          />
        </span>
      )}
    </span>
  );
}
