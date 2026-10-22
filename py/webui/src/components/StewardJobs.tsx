/** Değnekçi sekmesi: servis kaydı (varaka) + iş kuyruğu. Onay/ret BİLEREK yok: yalnız varaka'daki insan yöneticide.
 *  Token değeri hiçbir yerde girilmez ya da gösterilmez; yalnız token dosyasının yolu. */
import { useCallback, useEffect, useState } from "react";
import {
  apiStewardJobAck,
  apiStewardJobSubmit,
  apiStewardServiceAdd,
  apiStewardServiceRm,
  getStewardJobKinds,
  getStewardJobs,
  getStewardServices,
} from "../api/client";
import type { StewardJobRow, StewardServiceRow } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { showToast } from "../state/toast";

/** Katalog biçimi bilinmiyor: dizi ya da {kinds|items: [...]} içinden ad/kind alanlarını savunmacı çıkar. */
function kindNames(raw: unknown): string[] {
  const arr = Array.isArray(raw) ? raw : Array.isArray((raw as { kinds?: unknown })?.kinds) ? (raw as { kinds: unknown[] }).kinds
    : Array.isArray((raw as { items?: unknown })?.items) ? (raw as { items: unknown[] }).items : [];
  const out = arr.map((k) => (typeof k === "string" ? k : String((k as { kind?: string; name?: string })?.kind ?? (k as { name?: string })?.name ?? ""))).filter(Boolean);
  return Array.from(new Set(out));
}

export function StewardJobs({ sid, projects }: { sid: string; projects: string[] }) {
  const { t } = useLang();
  const [services, setServices] = useState<StewardServiceRow[]>([]);
  const [jobs, setJobs] = useState<StewardJobRow[]>([]);
  const [onlyOpen, setOnlyOpen] = useState(true);
  const [kinds, setKinds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [svc, setSvc] = useState({ name: "", url: "", token: "" });
  const [job, setJob] = useState({ project: "", kind: "", files: "", params: "", note: "" });

  const load = useCallback(
    async (refresh = false) => {
      try {
        const [s, j] = await Promise.all([getStewardServices(), getStewardJobs(sid, onlyOpen ? "open" : "all", refresh)]);
        if (s.ok) setServices(s.services ?? []);
        if (j.ok) setJobs(j.jobs ?? []);
      } catch (e) {
        showToast(describeApiError(e, t));
      }
    },
    [sid, onlyOpen, t],
  );

  useEffect(() => {
    void load();
  }, [load]);

  async function act(fn: () => Promise<{ ok: boolean; error?: string }>, after?: () => void, refresh = false) {
    if (busy) return;
    setBusy(true);
    try {
      const r = await fn();
      if (!r.ok) showToast(r.error || t.requestFailed);
      else after?.();
    } catch (e) {
      showToast(describeApiError(e, t));
    } finally {
      setBusy(false);
      void load(refresh);
    }
  }

  async function loadKinds() {
    if (kinds.length) return;
    try {
      const r = await getStewardJobKinds(sid);
      if (r.ok) setKinds(kindNames(r.kinds));
    } catch {
      /* katalog yoksa serbest metin kalır */
    }
  }

  function submit() {
    let params: Record<string, unknown> = {};
    if (job.params.trim()) {
      try {
        const p = JSON.parse(job.params);
        if (!p || typeof p !== "object" || Array.isArray(p)) throw new Error("not object");
        params = p as Record<string, unknown>;
      } catch {
        showToast(t.stewardJobsBadJson);
        return;
      }
    }
    const files = job.files.split(",").map((f) => f.trim()).filter(Boolean);
    void act(
      () => apiStewardJobSubmit({ project: job.project, kind: job.kind.trim(), files, params, spec_text: job.note }, sid),
      () => {
        setJob({ project: job.project, kind: "", files: "", params: "", note: "" });
        showToast(t.stewardJobsSubmitted, "success");
      },
      true,
    );
  }

  return (
    <>
      <details>
        <summary className="legend" style={{ cursor: "pointer", margin: 0 }}>{t.stewardSvcTitle}</summary>
        <div className="opts" style={{ marginTop: ".4rem", flexDirection: "column", alignItems: "flex-start", gap: ".4rem" }}>
          <span className="opts-hint">{t.stewardSvcHint}</span>
          {services.length === 0 && <span className="opts-hint">{t.stewardSvcNone}</span>}
          {services.map((x) => (
            <span key={x.name} className="legend" style={{ margin: 0 }}>
              <b>{x.name}</b> {x.url} · {x.match} · {x.open_jobs} {t.stewardSvcOpenJobs}
              {!x.token_present ? ` · ⚠ ${t.stewardSvcNoToken}` : x.token_warning ? ` · ⚠ ${x.token_warning}` : ""}{" "}
              <button
                type="button"
                className="retire"
                disabled={busy || x.open_jobs > 0}
                onClick={() => {
                  if (window.confirm(t.stewardSvcRmConfirm)) void act(() => apiStewardServiceRm(x.name));
                }}
              >
                {t.stewardSvcRm}
              </button>
            </span>
          ))}
          <span>
            <input value={svc.name} placeholder={t.stewardSvcName} onChange={(e) => setSvc({ ...svc, name: e.target.value.toLowerCase() })} />{" "}
            <input value={svc.url} placeholder={t.stewardSvcUrl} onChange={(e) => setSvc({ ...svc, url: e.target.value })} />{" "}
            <input value={svc.token} placeholder={t.stewardSvcTokenFile} onChange={(e) => setSvc({ ...svc, token: e.target.value })} />{" "}
            <button
              type="button"
              disabled={busy || !svc.name.trim() || !svc.url.trim() || !svc.token.trim()}
              onClick={() => void act(() => apiStewardServiceAdd(svc.name.trim(), svc.url.trim(), svc.token.trim(), "prefix"), () => setSvc({ name: "", url: "", token: "" }))}
            >
              {t.stewardSvcAdd}
            </button>
          </span>
        </div>
      </details>

      <h3 style={{ margin: ".4rem 0 0" }}>{t.stewardJobsTitle}</h3>
      <div className="opts">
        <button type="button" className={onlyOpen ? "go" : undefined} aria-pressed={onlyOpen} onClick={() => setOnlyOpen(true)}>{t.stewardJobsOpen}</button>
        <button type="button" className={!onlyOpen ? "go" : undefined} aria-pressed={!onlyOpen} onClick={() => setOnlyOpen(false)}>{t.stewardJobsAll}</button>
        <button type="button" disabled={busy} onClick={() => void act(async () => ({ ok: true }), undefined, true)}>{t.stewardJobsPoll}</button>
      </div>
      {jobs.length === 0 && <span className="opts-hint">{t.stewardJobsNone}</span>}
      {jobs.map((j) => (
        <div key={`${j.service}-${j.id}`} className="legend" style={{ margin: 0 }}>
          <span className="cli-badge">{j.state ?? "?"}</span> <b>{j.service}#{j.id}</b> {j.project ?? "-"} · {j.kind ?? "-"}
          {j.approval_state ? ` · ${j.approval_state}` : ""}
          {j.result_summary ? ` · ${j.result_summary}` : ""}
          {j.error ? ` · ⚠ ${j.error}` : ""}
          {j.state === "awaiting_approval" ? <span className="opts-hint"> · {t.stewardJobsAwaiting}</span> : null}
          {!j.open && !j.delivered ? (
            <>
              {" "}
              <button type="button" disabled={busy} onClick={() => void act(() => apiStewardJobAck(j.id, j.service, sid))}>{t.stewardJobsAck}</button>
            </>
          ) : null}
        </div>
      ))}

      <details onToggle={(e) => { if ((e.target as HTMLDetailsElement).open) void loadKinds(); }}>
        <summary className="legend" style={{ cursor: "pointer", margin: 0 }}>{t.stewardJobsSubmit}</summary>
        <div className="opts" style={{ marginTop: ".4rem", flexDirection: "column", alignItems: "flex-start", gap: ".4rem" }}>
          <span>
            <select value={job.project} onChange={(e) => setJob({ ...job, project: e.target.value })} aria-label="project">
              <option value="">—</option>
              {projects.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>{" "}
            <input list="steward-job-kinds" value={job.kind} placeholder={t.stewardJobsKind} onChange={(e) => setJob({ ...job, kind: e.target.value })} />
            <datalist id="steward-job-kinds">{kinds.map((k) => <option key={k} value={k} />)}</datalist>
          </span>
          <input style={{ width: "100%" }} value={job.files} placeholder={t.stewardJobsFiles} onChange={(e) => setJob({ ...job, files: e.target.value })} />
          <input style={{ width: "100%" }} value={job.params} placeholder={t.stewardJobsParams} onChange={(e) => setJob({ ...job, params: e.target.value })} />
          <input style={{ width: "100%" }} value={job.note} placeholder={t.stewardJobsNote} onChange={(e) => setJob({ ...job, note: e.target.value })} />
          <button type="button" disabled={busy || !job.project || !job.kind.trim()} onClick={submit}>{t.stewardJobsSubmit}</button>
        </div>
      </details>
    </>
  );
}
