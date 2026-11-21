/**
 * Ayarlar > Ucli > Kontroller: ucli `run_checks` kontrol kaydı (docs/ucli-run-checks-design.md 4.3, C3).
 * Kayıt `/api/ucli/checks` (admin.config) ile okunur/yazılır; model yalnız buradaki adlandırılmış kontrolleri çalıştırır.
 * Düzenleme ham JSON (`{"check":[{name, argv, ...}]}`) + hazır şablon ekleme; doğrulamanın tek kaynağı ucli'dir (U1), burada ön denetim.
 * kubeconfig/ağ (`network = "host"`) taşıyan kontrol kırmızı rozetle gösterilir.
 */
import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { describeApiError } from "../api/errors";
import { showToast } from "../state/toast";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";

interface Check {
  name: string;
  description?: string;
  argv: string[];
  mutating?: boolean;
  network?: string;
  [k: string]: unknown;
}
interface Registry { ok: boolean; checks: Check[]; error?: string; templates?: Record<string, Check> }

export function UcliChecksSection() {
  const { lang, t } = useLang();
  const tr = lang === "tr";
  const [checks, setChecks] = useState<Check[]>([]);
  const [templates, setTemplates] = useState<Record<string, Check>>({});
  const [raw, setRaw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const { data } = useStatusContext();
  const [host, setHost] = useState("local");      // kayıt ilgili hostun KENDİ diskinde (TBD#264)
  const hostNames = (data?.hosts ?? []).map((h) => h.name);
  const q = host !== "local" ? `?host=${encodeURIComponent(host)}` : "";

  async function load() {
    try {
      const r = await apiGet<Registry>(`/api/ucli/checks${q}`);
      setChecks(r.checks ?? []);
      setTemplates(r.templates ?? {});
      setRaw(JSON.stringify({ check: r.checks ?? [] }, null, 1));
      setErr(r.ok ? "" : r.error ?? "");
    } catch (e) {
      setErr(describeApiError(e, t));
    }
  }
  useEffect(() => { void load(); }, [host]);   // eslint-disable-line react-hooks/exhaustive-deps

  async function post(body: object) {
    setBusy(true);
    try {
      const r = await apiPost<{ ok: boolean; error?: string }>("/api/ucli/checks", { ...body, host });
      if (!r.ok) showToast(r.error || "error");
    } catch (e) {
      showToast(describeApiError(e, t));
    } finally {
      setBusy(false);
      await load();
    }
  }

  function saveRaw() {
    let parsed: { check?: unknown };
    try { parsed = JSON.parse(raw); } catch { showToast(tr ? "Geçerli JSON değil" : "Not valid JSON"); return; }
    void post({ check: parsed.check });
  }
  function addTemplate(key: string) {
    const tpl = templates[key];
    if (!tpl || checks.some((c) => c.name === tpl.name)) { showToast(tr ? "Bu ad zaten var" : "Name already exists"); return; }
    void post({ check: [...checks, tpl] });
  }
  function del(name: string) {
    if (!window.confirm(tr ? `"${name}" silinsin mi?` : `Delete "${name}"?`)) return;
    void post({ delete: name });
  }

  return (
    <div className="opts" id="settingsUcliChecksPanel">
      <span className="opts-hint" style={{ flexBasis: "100%" }}>
        <b>{tr ? "Kontroller" : "Checks"}</b>{" "}
        {tr
          ? "ucli run_checks: model yalnız bu kayıttaki adlandırılmış kontrolleri çalıştırır (kafeste). Oturum başlatırken Kontroller seçicisinden açılır; kayıt oturum dışında, model tarafından değiştirilemeyen dosyada durur."
          : "ucli run_checks: the model can run only the named checks in this registry (caged). Enable per session in the start options; the registry lives outside the work root, so the model cannot edit it."}
      </span>
      {hostNames.length > 0 && (
        <label style={{ flexBasis: "100%", display: "flex", gap: ".5rem", alignItems: "center" }}>
          <span className="opts-hint">{tr ? "Host:" : "Host:"}</span>
          <select id="ucliChecksHost" value={host} onChange={(e) => setHost(e.target.value)}>
            <option value="local">local</option>
            {hostNames.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
      )}
      {err && <span className="opts-hint" style={{ color: "var(--red)", flexBasis: "100%" }}>{err}</span>}
      {checks.map((c) => (
        <div key={c.name} style={{ display: "flex", alignItems: "center", gap: ".5rem", flexBasis: "100%", flexWrap: "wrap" }}>
          <b style={{ minWidth: "7rem" }}>{c.name}</b>
          {c.mutating && <span style={{ color: "var(--red)" }}>{tr ? "değiştirici" : "mutating"}</span>}
          {c.network === "host" && <span style={{ color: "var(--red)" }}>{tr ? "ağ: host" : "net: host"}</span>}
          <span className="opts-hint" style={{ overflowWrap: "anywhere", flex: "1 1 12rem" }}>{c.description || c.argv.join(" ")}</span>
          <button type="button" disabled={busy} onClick={() => del(c.name)}>{tr ? "Sil" : "Delete"}</button>
        </div>
      ))}
      {checks.length === 0 && !err && <span className="opts-hint">{tr ? "Kayıtlı kontrol yok." : "No checks registered."}</span>}
      <label>
        {tr ? "Şablon ekle" : "Add template"}
        <select value="" disabled={busy} onChange={(e) => { if (e.target.value) addTemplate(e.target.value); }}>
          <option value="">—</option>
          {Object.keys(templates).map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </label>
      <textarea
        aria-label="checks JSON"
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        spellCheck={false}
        style={{ flexBasis: "100%", minHeight: 140, fontFamily: "monospace", fontSize: 12 }}
      />
      <button type="button" className="go" disabled={busy} onClick={saveRaw}>{tr ? "JSON'u kaydet" : "Save JSON"}</button>
    </div>
  );
}
