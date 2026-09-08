/**
 * "Ayarlar" tab's Hosts section (Faz 4, multi-host federation plan,
 * ~/.claude/plans/vectorized-jingling-harp.md) — register/list/remove the
 * remote `cops web` instances this aggregator polls and proxies actions to.
 *
 * Deliberately fetches its own `getHosts()` on mount/after every add-remove
 * rather than reading `StatusContext`'s `data.hosts` — that field is the
 * lean per-poll operational view (`HostStatus`: name/ok/error/cli_list/
 * cli_options/dups) used by the hot status path; it has no `base_url`/
 * `has_token`, which this registry-management UI needs (`HostRecord`, from
 * a separate, only-fetched-when-this-panel-is-open endpoint).
 *
 * Editing a host reuses the same add-form + `save_host()`'s upsert semantics
 * (same name replaces base_url; blank token keeps the existing one) — clicking
 * "düzenle" just pre-fills name/base_url (never the token, it's never sent
 * back from the server) and scrolls the form into edit mode, it isn't a
 * separate code path.
 */

import { useEffect, useState } from "react";
import { apiRemoveHost, apiSaveHost, apiTestHost, getHosts } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import type { HostRecord } from "../api/types";

export function HostsSection() {
  const { t, lang } = useLang();
  const { data } = useStatusContext();
  const [hosts, setHosts] = useState<HostRecord[]>([]);
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  // Per-row, not the single `busy` above — testing one host shouldn't grey
  // out the add form or every other row's own "test now" button.
  const [testingNames, setTestingNames] = useState<Set<string>>(new Set());
  // Editing isn't a separate mode/flag — it's just "the name field happens to
  // match an already-registered host," same as typing an existing name by
  // hand would do. Derived, not stored, so it can never drift out of sync.
  const editingExisting = hosts.some((h) => h.name === name.trim());

  async function load() {
    try {
      const res = await getHosts();
      setHosts(res.hosts);
    } catch {
      // Secondary panel, not gated behind `data &&` like the rest of the app
      // — a transient failure here just leaves the previous list on screen,
      // no dedicated error banner needed for this one.
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function handleAdd() {
    setBusy(true);
    const savedName = name.trim();
    try {
      const res = await apiSaveHost({ name: savedName, base_url: baseUrl.trim(), token: token.trim(), lang });
      if (!res.ok) {
        window.alert(res.error);
      } else {
        setName("");
        setBaseUrl("");
        setToken("");
        // The background poller hasn't reached this host yet (up to ~3s away,
        // or never if this is a brand-new registration) — a plain `load()`
        // here would show "not polled yet" right after a successful save.
        // `handleTest` checks it on the spot and `load()`s the real result.
        await handleTest(savedName);
      }
    } catch (e) {
      window.alert(describeApiError(e, t));
    } finally {
      setBusy(false);
    }
  }

  /** On-demand check (`/api/hosts/test`) instead of waiting for the
   * background poller's own ~3s cadence — used by the add-flow above and by
   * each row's own "test now" button. Never surfaces `host_ok: false` as an
   * alert — an unreachable host is an expected, informative result here, not
   * a request failure; the row's own connected/unreachable badge (driven by
   * the `load()` below, same cache this test just updated) already shows it. */
  async function handleTest(hostName: string) {
    setTestingNames((prev) => new Set(prev).add(hostName));
    try {
      const res = await apiTestHost({ name: hostName, lang });
      if (!res.ok) window.alert(res.error);
    } catch (e) {
      window.alert(describeApiError(e, t));
    } finally {
      setTestingNames((prev) => {
        const next = new Set(prev);
        next.delete(hostName);
        return next;
      });
      await load();
    }
  }

  function handleEdit(h: HostRecord) {
    setName(h.name);
    setBaseUrl(h.base_url);
    setToken("");
  }

  function handleCancelEdit() {
    setName("");
    setBaseUrl("");
    setToken("");
  }

  async function handleRemove(hostName: string) {
    if (!window.confirm(t.hostRemoveConfirm(hostName))) return;
    try {
      const res = await apiRemoveHost({ name: hostName, lang });
      if (!res.ok) window.alert(res.error);
    } catch (e) {
      window.alert(describeApiError(e, t));
    }
    await load();
  }

  return (
    <div className="opts" id="hostsPanel">
      <span className="opts-hint" style={{ flexBasis: "100%" }}>
        <b>{t.hostsTitle}</b> {t.hostsDesc}
      </span>
      <span className="opts-hint" style={{ flexBasis: "100%" }}>
        {t.tunnelInfoLabel}:{" "}
        {data?.tunnel.url ? (
          <>
            <code>{data.tunnel.url}</code>
            {data.tunnel.label && <span className="cli-badge">{data.tunnel.label}</span>}
          </>
        ) : (
          t.tunnelNoneMsg
        )}
      </span>
      <label>
        {t.hostNameLabel}
        <input type="text" placeholder="yuhem" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        {t.hostBaseUrlLabel}
        <input
          type="text"
          placeholder="https://xxxx.trycloudflare.com"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
        />
      </label>
      <label>
        {t.hostTokenLabel}
        <input type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
      </label>
      {editingExisting && <span className="opts-hint">{t.hostTokenKeepHint}</span>}
      <button type="button" className="go" disabled={busy} onClick={() => void handleAdd()}>
        {busy ? (editingExisting ? t.hostSaving : t.hostAdding) : editingExisting ? t.hostSaveBtn : t.hostAddBtn}
      </button>
      {editingExisting && (
        <button type="button" onClick={handleCancelEdit}>
          {t.hostCancelEdit}
        </button>
      )}
      <div style={{ flexBasis: "100%", display: "flex", flexDirection: "column", gap: ".35rem", marginTop: ".3rem" }}>
        {hosts.length === 0 ? (
          <span className="opts-hint">{t.hostNone}</span>
        ) : (
          hosts.map((h) => (
            <div key={h.name} className="opts-hint" style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
              <b>{h.name}</b>
              <span style={{ color: "var(--muted)" }}>{h.base_url}</span>
              <span style={{ color: h.ok ? "var(--green)" : "var(--red)" }} title={h.error ?? undefined}>
                {h.ok ? t.hostConnected : t.hostUnreachable}
              </span>
              <button type="button" disabled={testingNames.has(h.name)} onClick={() => void handleTest(h.name)}>
                {testingNames.has(h.name) ? t.hostTesting : t.hostTestBtn}
              </button>
              <button type="button" onClick={() => handleEdit(h)}>
                {t.hostEditBtn}
              </button>
              <button type="button" className="closebtn" onClick={() => void handleRemove(h.name)}>
                {t.hostRemoveBtn}
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
