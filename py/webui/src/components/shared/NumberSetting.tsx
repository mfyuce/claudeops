import { useEffect, useState } from "react";

/** A number field that saves on Enter / blur when the value changed (the backend validates the range). */
export function NumberSetting({ label, value, width, onSave }: { label: string; value: number; width?: string; onSave: (n: number) => void }) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  function commit() {
    const n = Number(text);
    if (text.trim() !== "" && Number.isFinite(n) && n !== value) onSave(n);
    else setText(String(value));
  }
  return (
    <label className="opts-hint" style={{ display: "inline-flex", gap: ".3rem", alignItems: "center" }}>
      {label}
      <input
        type="number"
        value={text}
        style={{ width: width ?? "5rem" }}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
      />
    </label>
  );
}
