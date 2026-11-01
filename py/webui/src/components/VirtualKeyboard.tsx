/**
 * On-screen keyboard for the Uzak Masaüstü tab (owner, 2026-11-01: phone/web viewers have no Ctrl/Alt/Esc/F-keys and the
 * browser cannot capture combos like Ctrl+W or Alt+Tab). Modifiers are STICKY ON THE CLIENT ONLY: one tap = applies to the
 * next key (once), second tap = locked, third = off. Nothing is sent to the remote machine until a key is pressed, and then
 * as one burst `mod down ... key click ... mod up`, so a missed event can never leave a modifier held on the real machine
 * (the reason the physical-modifier path was held back before). `onKey(mods, key)` does the sending.
 */
import { useState } from "react";
import type { Lang } from "../i18n/strings";

export type ModName = "Control" | "Alt" | "Shift" | "Meta";
type Latch = "off" | "once" | "lock";

interface Props {
  lang: Lang;
  /** `key` is a daemon key name (Enter, Escape, ArrowUp, F5, ...) or a single character. */
  onKey: (mods: ModName[], key: string) => void;
  /** Free text, typed as Unicode on the remote side. */
  onText: (s: string) => void;
}

const MODS: { name: ModName; label: string }[] = [
  { name: "Control", label: "Ctrl" },
  { name: "Alt", label: "Alt" },
  { name: "Shift", label: "Shift" },
  { name: "Meta", label: "Win" },
];

const ROWS: string[][] = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "="],
  ["q", "w", "e", "r", "t", "y", "u", "ı", "o", "p", "ğ", "ü"],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l", "ş", "i", "["],
  ["z", "x", "c", "v", "b", "n", "m", "ö", "ç", ",", ".", "/"],
];

const NAV: [string, string][] = [
  ["Esc", "Escape"], ["Tab", "Tab"], ["⌫", "Backspace"], ["Del", "Delete"], ["Enter", "Enter"],
  ["←", "ArrowLeft"], ["↓", "ArrowDown"], ["↑", "ArrowUp"], ["→", "ArrowRight"],
  ["Home", "Home"], ["End", "End"], ["PgUp", "PageUp"], ["PgDn", "PageDown"],
];

const COMBOS: [string, ModName[], string][] = [
  ["Ctrl+C", ["Control"], "c"], ["Ctrl+V", ["Control"], "v"], ["Ctrl+X", ["Control"], "x"], ["Ctrl+A", ["Control"], "a"],
  ["Ctrl+Z", ["Control"], "z"], ["Ctrl+S", ["Control"], "s"], ["Ctrl+W", ["Control"], "w"], ["Ctrl+T", ["Control"], "t"],
  ["Alt+Tab", ["Alt"], "Tab"], ["Alt+F4", ["Alt"], "F4"], ["Win", ["Meta"], ""], ["Ctrl+Alt+T", ["Control", "Alt"], "t"],
];

const FKEYS = Array.from({ length: 12 }, (_, i) => `F${i + 1}`);

export function VirtualKeyboard({ lang, onKey, onText }: Props) {
  const tr = lang === "tr";
  const [latch, setLatch] = useState<Record<ModName, Latch>>({ Control: "off", Alt: "off", Shift: "off", Meta: "off" });
  const [showF, setShowF] = useState(false);
  const [showLetters, setShowLetters] = useState(true);
  const [text, setText] = useState("");

  function cycle(m: ModName) {
    setLatch((p) => ({ ...p, [m]: p[m] === "off" ? "once" : p[m] === "once" ? "lock" : "off" }));
  }

  /** Active modifiers + release the "once" ones. */
  function takeMods(): ModName[] {
    const active = MODS.filter((m) => latch[m.name] !== "off").map((m) => m.name);
    if (active.length) setLatch((p) => {
      const n = { ...p };
      for (const m of active) if (n[m] === "once") n[m] = "off";
      return n;
    });
    return active;
  }

  function press(key: string, extra: ModName[] = []) {
    const mods = Array.from(new Set([...takeMods(), ...extra]));
    // Plain Shift + a single letter is typed as text (the remote layout resolves Unicode / Turkish İ itself).
    if (key.length === 1 && mods.length === 1 && mods[0] === "Shift") onText(key.toLocaleUpperCase("tr"));
    else if (key.length === 1 && mods.length === 0) onText(key);
    else onKey(mods, key);
  }

  // Buttons must not steal focus from the viewer / hidden input (matters on touch).
  const keep = (e: React.PointerEvent) => e.preventDefault();
  const btn = (label: string, onClick: () => void, cls = "", key?: string) => (
    <button key={key ?? label} type="button" className={`vk-key ${cls}`} onPointerDown={keep} onClick={onClick}>
      {label}
    </button>
  );

  return (
    <div className="vkbd">
      <div className="vk-row">
        {MODS.map((m) => btn(
          latch[m.name] === "lock" ? `${m.label} 🔒` : m.label,
          () => cycle(m.name),
          latch[m.name] === "off" ? "" : latch[m.name] === "lock" ? "vk-lock" : "vk-once",
        ))}
        {btn(showLetters ? (tr ? "harfleri gizle" : "hide letters") : (tr ? "harfler" : "letters"), () => setShowLetters((v) => !v), "vk-aux")}
        {btn(showF ? "F1-F12 ▲" : "F1-F12 ▼", () => setShowF((v) => !v), "vk-aux")}
      </div>
      {showF && <div className="vk-row">{FKEYS.map((k) => btn(k, () => press(k)))}</div>}
      <div className="vk-row">{NAV.map(([label, key]) => btn(label, () => press(key), "", key))}</div>
      {showLetters && ROWS.map((row, i) => (
        <div className="vk-row" key={i}>
          {row.map((c) => btn(latch.Shift !== "off" ? c.toLocaleUpperCase("tr") : c, () => press(c), "", c))}
        </div>
      ))}
      {showLetters && (
        <div className="vk-row">
          {btn(tr ? "Boşluk" : "Space", () => press("Space"), "vk-wide")}
        </div>
      )}
      <div className="vk-row">
        {COMBOS.map(([label, mods, key]) => btn(label, () => onKey(mods, key), "vk-combo"))}
      </div>
      <form
        className="vk-row"
        onSubmit={(e) => { e.preventDefault(); if (text) { onText(text); setText(""); } }}
      >
        <input
          type="text"
          className="vk-text"
          value={text}
          placeholder={tr ? "metin yaz, Gönder (yapıştırma için)" : "type text, Send (for paste)"}
          onChange={(e) => setText(e.target.value)}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
        />
        <button type="submit" className="vk-key vk-aux">{tr ? "Gönder" : "Send"}</button>
        <button type="button" className="vk-key vk-aux" onClick={() => onKey([], "Enter")}>Enter</button>
      </form>
    </div>
  );
}
