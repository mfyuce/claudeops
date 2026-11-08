import { useEffect, useState } from "react";

/** A text field that saves on Enter / blur when the value changed (the backend validates and normalizes; empty = default). */
export function TextSetting({ label, value, width, placeholder, title, onSave }: {
  label: string; value: string; width?: string; placeholder?: string; title?: string; onSave: (s: string) => void;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  function commit() {
    const s = text.trim();
    if (s !== value) onSave(s);
    else setText(value);
  }
  return (
    <label className="opts-hint" title={title} style={{ display: "inline-flex", gap: ".3rem", alignItems: "center", flexWrap: "wrap" }}>
      {label}
      <input
        type="text"
        value={text}
        placeholder={placeholder}
        style={{ width: width ?? "14rem", maxWidth: "100%" }}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
      />
    </label>
  );
}
