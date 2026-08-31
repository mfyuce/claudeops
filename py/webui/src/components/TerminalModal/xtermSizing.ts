/**
 * Verbatim, typed port of `computeFitFontSize`/`fitContainerToTerm`/
 * `measureCharWidthPx` (web.py ~2119-2164). Deliberately NOT using
 * `@xterm/addon-fit` — that addon solves the opposite problem (shrinking
 * the terminal's cols/rows to fit a fixed-size container); this app has a
 * fixed cols/rows (the real tmux pane's actual size, reported by the
 * backend) and needs to size the CONTAINER/font to fit an arbitrary
 * viewport instead, which is exactly what this hand-written logic does
 * (and why the original never adopted the addon either).
 *
 * `import type` for `Terminal` below is erased at compile time
 * (`verbatimModuleSyntax`) — it does not pull `@xterm/xterm`'s runtime
 * code into whatever chunk this file ends up in, so this stays safe to
 * import from anywhere without undoing `TerminalView`'s dynamic `import()`
 * code-splitting.
 */

import type { Terminal } from "@xterm/xterm";

/** Original: `computeFitFontSize(cols)` (web.py ~2119-2127). Shrinks the
 * font just enough that `cols` columns fit the current viewport width,
 * clamped to [7, 15]px — real terminals (a desktop gnome-terminal window)
 * are almost always wider than a phone screen, so a fixed font-size
 * either clips text or hides horizontal scroll in a way that reads as
 * "the terminal is misaligned/scrolled wrong" (the original bug report
 * this fixed). */
export function computeFitFontSize(cols: number): number {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  ctx.font = "100px monospace";
  const cellWidthAt100 = ctx.measureText("0").width;
  const available = Math.max(200, window.innerWidth * 0.92 - 40);
  const fit = (available / cols / cellWidthAt100) * 100;
  return Math.max(7, Math.min(fit, 15));
}

/** Reads xterm.js's private (but stable — the same one `@xterm/addon-fit`
 * itself relies on internally) per-cell pixel dimensions. Not part of the
 * public `Terminal` type, hence the loose cast; wrapped in try/catch
 * exactly like the original since this can break on an xterm.js internal
 * shape change, in which case `fitContainerToTerm`'s canvas-measurement
 * fallback takes over. */
function readXtermCellDims(term: Terminal): { width: number; height: number } | null {
  try {
    const core = (
      term as unknown as {
        _core?: { _renderService?: { dimensions?: { css?: { cell?: { width: number; height: number } } } } };
      }
    )._core;
    const dims = core?._renderService?.dimensions?.css?.cell;
    if (dims && dims.width > 0 && dims.height > 0) return { width: dims.width, height: dims.height };
  } catch {
    // internal API shape changed/inaccessible — canvas fallback below.
  }
  return null;
}

/** Original: `fitContainerToTerm(name, cols, rows)` (web.py ~2129-2153).
 * Sizes `container` to exactly fit `cols`x`rows` of `term`'s real
 * character-cell dimensions, read BEFORE the DOM is queried (querying the
 * container's own current size here would be circular — see the
 * original's comment — since `.xterm-viewport` stretches to whatever the
 * container's size currently is). Falls back to a canvas-measured
 * estimate if the internal API is unavailable. */
export function fitContainerToTerm(term: Terminal, container: HTMLElement, cols: number, rows: number): void {
  requestAnimationFrame(() => {
    const dims = readXtermCellDims(term);
    if (dims) {
      container.style.width = `${Math.ceil(cols * dims.width)}px`;
      container.style.height = `${Math.ceil(rows * dims.height)}px`;
      return;
    }
    const cw = measureCharWidthPx();
    container.style.width = `${Math.ceil(cols * cw)}px`;
    container.style.height = `${Math.ceil(rows * cw * 2)}px`; // rough line-height estimate
  });
}

/** Original: `measureCharWidthPx()` (web.py ~2155-2164) — module-level
 * memoized (a pure fact about the browser's monospace-font metrics at a
 * fixed size, not per-session state, so a plain module-level cache is
 * correct here, not a shadow dict). */
let charWidthPx: number | null = null;
export function measureCharWidthPx(): number {
  if (charWidthPx == null) {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d")!;
    ctx.font = "12.8px monospace"; // 0.8rem @ 16px root
    charWidthPx = ctx.measureText("0".repeat(100)).width / 100;
  }
  return charWidthPx;
}
