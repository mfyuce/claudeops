/**
 * Error banner: first line (friendly explanation) always visible; when the text has more lines (the raw backend
 * message appended by `friendlyError`) they sit in a collapsible <details>. A copy button copies the whole text.
 */
import { useLang } from "../../i18n/LangContext";
import { showToast } from "../../state/toast";
import { copyToClipboard } from "./clipboard";

export function ErrorBox({ text }: { text: string }) {
  const { lang } = useLang();
  const [head, ...rest] = text.split("\n");
  const raw = rest.join("\n");
  async function copy() {
    try {
      await copyToClipboard(text);
      showToast(lang === "tr" ? "Kopyalandı" : "Copied");
    } catch {
      showToast(lang === "tr" ? "Kopyalanamadı" : "Copy failed");
    }
  }
  return (
    <div className="warn-banner" style={{ overflowWrap: "anywhere" }}>
      {head}
      {raw && (
        <details>
          <summary>{lang === "tr" ? "ayrıntı" : "details"}</summary>
          <pre style={{ whiteSpace: "pre-wrap", margin: ".3rem 0 0" }}>{raw}</pre>
        </details>
      )}{" "}
      <button type="button" onClick={() => void copy()} style={{ marginLeft: 6 }}>
        {lang === "tr" ? "kopyala" : "copy"}
      </button>
    </div>
  );
}
