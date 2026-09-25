/**
 * "Ayarlar" tab's CLI Install section — per-backend (claude/codex/copilot/agy)
 * install status + one-click install into claudeops's own bin dir
 * (`cli_install.py`, `~/.claude/claudeops/bin` via `npm install -g --prefix`,
 * never a true global/system install — see that module's docstring).
 *
 * Works against any registered remote host too, not just this machine — a
 * host picker re-runs the same status/install calls with `host` set
 * (`web_hosts.HOST_ROUTED_PATHS`/`GET_HOST_ROUTED_PATHS`): the remote
 * claudeops-web instance runs its own `cli_install.py` locally, no
 * shell/SSH involved, same mechanism `/api/start` etc. already use.
 *
 * Same self-contained fetch-on-mount pattern as HostsSection.tsx: this needs
 * `CliInstallStatus[]` (path/managed_by_claudeops), which `StatusContext`'s
 * hot poll payload has no reason to carry. Reuses `getHosts()` (the same
 * call HostsSection makes) just for the list of host *names* to pick from.
 */

import { useEffect, useState } from "react";
import { ApiError, apiInstallCli, getCliStatus, getHosts } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import type { CliInstallStatus } from "../api/types";

const ORDER = ["claude", "codex", "copilot", "agy"];
const LOCAL_HOST = "local";

export function CliInstallSection() {
  const { t, lang } = useLang();
  const [hostNames, setHostNames] = useState<string[]>([]);
  const [selectedHost, setSelectedHost] = useState(LOCAL_HOST);
  const [clis, setClis] = useState<Record<string, CliInstallStatus>>({});
  // `null` = ok, "unreachable" = network/host down, "outdated" = host answered
  // but doesn't know this route yet (404 — needs `git pull`). Distinguishing
  // these matters: 2026-09-25 live case, a 404 from an old-code remote host
  // first showed as a generic "can't reach" message, which read as a
  // connectivity bug when the host was actually fine — just not updated yet.
  const [loadError, setLoadError] = useState<"unreachable" | "outdated" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    void getHosts()
      .then((res) => setHostNames(res.hosts.map((h) => h.name)))
      .catch(() => {
        // Host picker just stays local-only — same tolerant style as HostsSection's load().
      });
  }, []);

  async function load(host: string) {
    try {
      const res = await getCliStatus(host, lang);
      setClis(res.clis);
      setLoadError(null);
    } catch (e) {
      setClis({});
      setLoadError(e instanceof ApiError && e.status === 404 ? "outdated" : "unreachable");
    }
  }

  useEffect(() => {
    void load(selectedHost);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- lang change re-fetches too, load() itself is stable per call
  }, [selectedHost]);

  async function handleInstall(cli: string) {
    setBusy(cli);
    try {
      const res = await apiInstallCli({ cli, host: selectedHost, lang });
      if (!res.ok) window.alert(res.error);
    } catch (e) {
      // Same 404-vs-generic distinction as load() -- a stale/outdated remote
      // host 404s on this route too, and the generic ApiError text ("...this
      // tunnel/URL may no longer be valid...") reads as a connectivity bug
      // when the real cause is just "needs a git pull" (2026-09-25 live case).
      window.alert(e instanceof ApiError && e.status === 404 ? t.cliInstallHostOutdated : describeApiError(e, t));
    } finally {
      setBusy(null);
      await load(selectedHost);
    }
  }

  return (
    <div className="opts" id="settingsCliInstallPanel">
      <span className="opts-hint" style={{ flexBasis: "100%" }}>
        <b>{t.cliInstallLabel}</b> {t.cliInstallDesc}
      </span>
      {hostNames.length > 0 && (
        <label>
          {t.cliInstallHostLabel}
          <select value={selectedHost} onChange={(e) => setSelectedHost(e.target.value)}>
            <option value={LOCAL_HOST}>{LOCAL_HOST}</option>
            {hostNames.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
      )}
      {loadError ? (
        <span className="opts-hint" style={{ color: "var(--red)" }}>
          {loadError === "outdated" ? t.cliInstallHostOutdated : t.cliInstallHostUnreachable}
        </span>
      ) : (
        ORDER.filter((cli) => clis[cli]).map((cli) => {
          const s = clis[cli];
          return (
            <div key={cli} style={{ display: "flex", alignItems: "center", gap: ".5rem", flexBasis: "100%" }}>
              <b style={{ minWidth: "5rem" }}>{cli}</b>
              {s.found ? (
                <span className="opts-hint" title={s.path ?? undefined}>
                  {s.managed_by_claudeops ? t.cliManagedByUs : t.cliFoundElsewhere}
                </span>
              ) : s.installable ? (
                <button type="button" className="go" disabled={busy === cli} onClick={() => void handleInstall(cli)}>
                  {busy === cli ? t.cliInstalling : t.cliInstallBtn}
                </button>
              ) : (
                <span className="opts-hint">
                  {t.cliManualOnly}{" "}
                  {s.manual_url && (
                    <a href={s.manual_url} target="_blank" rel="noreferrer">
                      {s.manual_url}
                    </a>
                  )}
                </span>
              )}
              {s.found && s.managed_by_claudeops && (
                <button type="button" disabled={busy === cli} onClick={() => void handleInstall(cli)}>
                  {busy === cli ? t.cliInstalling : t.cliUpdateBtn}
                </button>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
