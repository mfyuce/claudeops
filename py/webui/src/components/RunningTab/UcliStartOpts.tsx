/**
 * ucli-only start options in the OptionsRow: the model SERVICE (Evren/Claude/Grok/OpenRouter; a service without a saved
 * key is disabled) and an optional, default-OFF `exec` permission (an allow-list of command names, an optional narrow
 * glob for files the model wrote, a timeout). Shells / wrappers / network are not offered (the backend rejects them
 * too: `ucli_session_opts.validate_opts`). State is owned by `OptionsRow`; `toCliOpts` builds the `cli_opts` payload.
 */
import type { Lang } from "../../i18n/strings";
import { useStatusContext } from "../../state/StatusContext";

export interface UcliStartState {
  service: string;
  serviceModel: string;
  execOn: boolean;
  execCmds: string;
  execGlob: string;
  execTimeout: string;
}

export const EMPTY_UCLI_START: UcliStartState = {
  service: "evren",
  serviceModel: "",
  execOn: false,
  execCmds: "",
  execGlob: "",
  execTimeout: "",
};

const SERVICES = [
  { id: "evren", label: "Evren", env: "UCLI_API_KEY", models: [] as string[] },
  { id: "claude", label: "Claude (Anthropic)", env: "ANTHROPIC_API_KEY", models: ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-fable-5-1"] },
  { id: "grok", label: "Grok (xAI)", env: "XAI_API_KEY", models: [] as string[] },
  { id: "openrouter", label: "OpenRouter", env: "OPENROUTER_API_KEY", models: [] as string[] },
];

/** `cli_opts` for the start payload, or undefined when nothing non-default is chosen (payload unchanged for everyone else). */
export function toCliOpts(s: UcliStartState): Record<string, unknown> | undefined {
  const o: Record<string, unknown> = {};
  if (s.service && s.service !== "evren") o.service = s.service;
  if (s.execOn && s.execCmds.trim()) {
    o.exec_cmds = s.execCmds;
    if (s.execGlob.trim()) o.exec_own_glob = s.execGlob;
    if (s.execTimeout.trim()) o.exec_timeout = s.execTimeout.trim();
  }
  return Object.keys(o).length ? o : undefined;
}

interface Props {
  value: UcliStartState;
  onChange: (v: UcliStartState) => void;
  lang: Lang;
}

export function UcliStartOpts({ value, onChange, lang }: Props) {
  const { data } = useStatusContext();
  const byok = data?.settings.byok?.ucli ?? {};
  const tr = lang === "tr";
  const set = (p: Partial<UcliStartState>) => onChange({ ...value, ...p });
  const svc = SERVICES.find((s) => s.id === value.service) ?? SERVICES[0];
  return (
    <>
      <label>
        {tr ? "hizmet" : "service"}
        <select value={value.service} onChange={(e) => set({ service: e.target.value, serviceModel: "" })}>
          {SERVICES.map((s) => {
            const ok = s.id === "evren" || byok[s.env] === true;
            return (
              <option key={s.id} value={s.id} disabled={!ok}>
                {s.label}
                {ok ? "" : tr ? " (anahtar yok)" : " (no key)"}
              </option>
            );
          })}
        </select>
      </label>
      {value.service !== "evren" && (
        <label>
          {tr ? "model (hizmet)" : "model (service)"}
          <input
            type="text"
            list="ucliSvcModels"
            placeholder="model id"
            value={value.serviceModel}
            onChange={(e) => set({ serviceModel: e.target.value })}
          />
          <datalist id="ucliSvcModels">
            {svc.models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </label>
      )}
      <label title={tr ? "Varsayılan kapalı. Yalnız gerekirse aç." : "Off by default. Enable only when needed."}>
        <input type="checkbox" checked={value.execOn} onChange={(e) => set({ execOn: e.target.checked })} /> exec
      </label>
      {value.execOn && (
        <>
          <input
            type="text"
            placeholder={tr ? "izinli komutlar (cargo, pytest, git)" : "allowed commands (cargo, pytest, git)"}
            value={value.execCmds}
            onChange={(e) => set({ execCmds: e.target.value })}
          />
          <input
            type="text"
            placeholder={tr ? "modelin yazdığı dosyalar: tests/**" : "model-written files: tests/**"}
            value={value.execGlob}
            onChange={(e) => set({ execGlob: e.target.value })}
          />
          <input
            type="text"
            size={6}
            placeholder={tr ? "zaman aşımı sn" : "timeout s"}
            value={value.execTimeout}
            onChange={(e) => set({ execTimeout: e.target.value })}
          />
          <span className="opts-hint" style={{ flexBasis: "100%" }}>
            {tr
              ? "Kabuk, env/xargs/find/sudo ve ağ sunulmaz. Komut yoksa exec kapalı kalır."
              : "No shells, env/xargs/find/sudo or network. With no commands exec stays off."}
          </span>
        </>
      )}
    </>
  );
}
