/**
 * Generic tmux-less "IoProvider" ask panel — TOBEDECIDED#44's "shell/tmux
 * olmadan provider ekleme yöntemi". Replaces the old ucli-specific hardcoded
 * form: the field list comes from `GET /api/io/providers` (`io_providers/
 * base.py::FormField`), so a second tmux-less provider would show up here
 * with zero changes to this file, only a new provider module + registry
 * line on the Python side.
 *
 * Project + session aware (2026-09-23, user: "birden çok projede birden çok
 * session açabilecek miyim, oradan devam edebilecek miyim") — `cwd` is a
 * real, caller-chosen project directory (no more hardcoded `REPO_DIR`), and
 * an existing `session` name's prior turns are fetched and shown above the
 * prompt box before asking again, the same "pick up where you left off"
 * idea `CliProvider.full_history` already gives tmux-backed sessions.
 */
import { useEffect, useState } from "react";
import { apiIoAsk, ApiError, getIoHistory, getIoProviders, getIoSessions } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import { TabHint } from "./shared/TabHint";

const NEW_SESSION = "\u0000new"; // sentinel <select> value for "type a new session name below"

export function IoAskPanel() {
  const { t } = useLang();
  const { data } = useStatusContext();

  const [providers, setProviders] = useState<Record<string, { fields: { key: string; label: string; type: string; placeholder: string; required: boolean }[] }> | null>(null);
  const [provider, setProvider] = useState("");
  const [cwd, setCwd] = useState("");
  const [sessions, setSessions] = useState<string[]>([]);
  const [sessionChoice, setSessionChoice] = useState(NEW_SESSION);
  const [newSessionName, setNewSessionName] = useState("");
  const [history, setHistory] = useState<{ role: string; text: string }[] | null>(null);
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        const res = await getIoProviders();
        if (res.ok) {
          setProviders(res.providers);
          const first = Object.keys(res.providers)[0];
          if (first) setProvider(first);
        }
      } catch {
        setProviders({});
      }
    })();
  }, []);

  const knownCwds = Array.from(new Set(data?.sessions.map((s) => s.cwd) ?? []));
  const activeSession = sessionChoice === NEW_SESSION ? newSessionName.trim() : sessionChoice;

  async function refreshSessions(forCwd: string, forProvider: string = provider) {
    setSessions([]);
    if (!forProvider || !forCwd.trim()) return;
    try {
      const res = await getIoSessions(forProvider, forCwd.trim());
      if (res.ok) setSessions(res.sessions);
    } catch {
      // sessizce boş liste - cwd henüz geçersiz/erişilemez olabilir, yazarken normal
    }
  }

  async function loadHistoryFor(name: string) {
    if (!provider || !cwd.trim() || !name.trim()) {
      setHistory(null);
      return;
    }
    try {
      const res = await getIoHistory(provider, cwd.trim(), name.trim());
      setHistory(res.ok ? res.turns : null);
    } catch {
      setHistory(null);
    }
  }

  async function handleAsk() {
    setBusy(true);
    setResult("");
    try {
      const res = await apiIoAsk({
        provider,
        cwd: cwd.trim(),
        session: activeSession,
        prompt,
        fields: fieldValues,
      });
      if (res.ok) {
        setResult(t.diagUcliResult(res.answer, res.model_rounds, res.tool_calls));
        setPrompt("");
        if (activeSession) {
          await refreshSessions(cwd);
          setSessionChoice(activeSession);
          await loadHistoryFor(activeSession);
        }
      } else {
        setResult(`✗ ${res.error}`);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) window.alert(t.authErrorShort);
      else setResult(`✗ ${describeApiError(e, t)}`);
    }
    setBusy(false);
  }

  if (providers === null) return null;
  const fields = providers[provider]?.fields ?? [];
  const providerNames = Object.keys(providers);
  if (providerNames.length === 0) return <TabHint>{t.diagUcliHint}</TabHint>;

  return (
    <div className="opts" id="ucliAskPanel">
      <TabHint>{t.diagUcliHint}</TabHint>

      {providerNames.length > 1 && (
        <label>
          provider
          <select
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              setFieldValues({});
              void refreshSessions(cwd, e.target.value);
            }}
          >
            {providerNames.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
      )}

      <label style={{ flexBasis: "100%" }}>
        {t.diagUcliCwdLabel}
        <input
          type="text"
          list="io-known-cwds"
          placeholder={t.diagUcliCwdPlaceholder}
          value={cwd}
          onChange={(e) => setCwd(e.target.value)}
          onBlur={() => void refreshSessions(cwd)}
        />
        <datalist id="io-known-cwds">
          {knownCwds.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      </label>

      <label>
        {t.diagUcliSessionLabel}
        <select
          value={sessionChoice}
          onChange={(e) => {
            setSessionChoice(e.target.value);
            if (e.target.value !== NEW_SESSION) void loadHistoryFor(e.target.value);
            else setHistory(null);
          }}
        >
          <option value={NEW_SESSION}>{t.diagUcliNewSession}</option>
          {sessions.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
      {sessionChoice === NEW_SESSION && (
        <label>
          {t.diagUcliNewSessionNameLabel}
          <input
            type="text"
            placeholder={t.diagUcliSessionPlaceholder}
            value={newSessionName}
            onChange={(e) => setNewSessionName(e.target.value)}
          />
        </label>
      )}

      {fields.map((f) => {
        const meta = t.ioFieldMeta[f.key];
        return (
          <label key={f.key}>
            {meta?.label ?? f.label}
            <input
              type={f.type === "password" ? "password" : "text"}
              autoComplete="off"
              placeholder={meta?.placeholder ?? f.placeholder}
              value={fieldValues[f.key] ?? ""}
              onChange={(e) => setFieldValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
            />
          </label>
        );
      })}

      {history && history.length > 0 && (
        <pre className="layout-result" style={{ flexBasis: "100%", maxHeight: "10rem", overflowY: "auto" }}>
          {history.map((turn) => `${turn.role === "user" ? "›" : "·"} ${turn.text}`).join("\n\n")}
        </pre>
      )}

      <label style={{ flexBasis: "100%" }}>
        {t.diagUcliPromptLabel}
        <input
          type="text"
          placeholder={t.diagUcliPromptPlaceholder}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
      </label>
      <button type="button" className="go" disabled={busy || !prompt.trim() || !cwd.trim()} onClick={() => void handleAsk()}>
        {busy ? t.diagUcliAsking : t.diagUcliBtn}
      </button>

      <pre className="layout-result" style={{ flexBasis: "100%" }}>
        {result}
      </pre>
    </div>
  );
}
