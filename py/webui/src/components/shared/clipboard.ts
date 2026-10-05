/**
 * `navigator.clipboard` only exists in a secure context (HTTPS or
 * localhost) — opening the panel over plain HTTP (a LAN IP, an HTTP
 * tunnel) leaves it `undefined`, so a bare `.writeText()` call throws
 * `TypeError: Cannot read properties of undefined` instead of failing
 * gracefully (gemini SEC-08, 2026-10-03 review). Falls back to the
 * standard hidden-textarea + `execCommand('copy')` trick, which still
 * works without a secure context — same approach every pre-Clipboard-API
 * copy button used.
 */
export async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  // Off-screen rather than display:none — some browsers refuse to select
  // text inside a non-rendered element.
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  ta.style.top = "0";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try {
    if (!document.execCommand("copy")) throw new Error("execCommand('copy') returned false");
  } finally {
    document.body.removeChild(ta);
  }
}
