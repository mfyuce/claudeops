/**
 * ucli-only start options in the OptionsRow: the model SERVICE (from Settings; a service without a saved
 * key is disabled) and an optional, default-OFF `exec` permission (an allow-list of command names, an optional narrow
 * glob for files the model wrote, a timeout). Shells / wrappers / network are not offered (the backend rejects them
 * too: `ucli_session_opts.validate_opts`). State is owned by `OptionsRow`; `toCliOpts` builds the `cli_opts` payload.
 */
import { useEffect, useState } from "react";
import { apiGet } from "../../api/client";
import type { UcliServiceDef } from "../../api/types";
import type { Lang } from "../../i18n/strings";
import { useStatusContext } from "../../state/StatusContext";

export interface UcliStartState {
  service: string;
  serviceModel: string;
  execOn: boolean;
  execCmds: string;
  execGlob: string;
  execWrite: boolean;
  execBind: string;
  execTimeout: string;
  acceptRisk: boolean;
}

export const EMPTY_UCLI_START: UcliStartState = {
  service: "evren",
  serviceModel: "",
  execOn: false,
  execCmds: "*",
  execGlob: "",
  execWrite: false,
  execBind: "",
  execTimeout: "",
  acceptRisk: false,
};

/** Patterns that grant execution on EVERY file (backend needs `accept_risk` for them). */
export function hasBroadGlob(glob: string): boolean {
  return glob.split(/[,\n]/).some((g) => ["*", "**", "**/*"].includes(g.trim()));
}

interface InstrCheck {
  limit: number;
  files: { name: string; bytes: number; over: boolean }[];
}

/** Services come from Settings (`data.settings.ucli_services`, one source with the Model keys panel). */
function useServices(): UcliServiceDef[] {
  const { data } = useStatusContext();
  return data?.settings.ucli_services ?? [];
}

/** `cli_opts` for the start payload, or undefined when nothing non-default is chosen (payload unchanged for everyone else). */
export function toCliOpts(s: UcliStartState): Record<string, unknown> | undefined {
  const o: Record<string, unknown> = {};
  if (s.service && s.service !== "evren") o.service = s.service;
  if (s.execOn && s.execCmds.trim()) {
    o.exec_cmds = s.execCmds;
    if (s.execGlob.trim()) o.exec_own_glob = s.execGlob;
    if (s.acceptRisk && hasBroadGlob(s.execGlob)) o.accept_risk = true;
    if (s.execWrite) o.exec_write = true;
    if (s.execBind.trim()) o.exec_bind_ro = s.execBind;
    if (s.execTimeout.trim()) o.exec_timeout = s.execTimeout.trim();
  }
  return Object.keys(o).length ? o : undefined;
}

interface Props {
  value: UcliStartState;
  onChange: (v: UcliStartState) => void;
  lang: Lang;
  /** Session working directory (local sessions): used for the 16 KiB instruction-file warning. */
  cwd?: string;
}

export function UcliStartOpts({ value, onChange, lang, cwd }: Props) {
  const { data } = useStatusContext();
  const byok = data?.settings.byok?.ucli ?? {};
  const tr = lang === "tr";
  const set = (p: Partial<UcliStartState>) => onChange({ ...value, ...p });
  const SERVICES = useServices();
  const svcBase = SERVICES.find((s) => s.id === value.service) ?? SERVICES[0] ?? { id: "evren", label: "Evren", env: "UCLI_API_KEY", models: [] as string[] };
  const [live, setLive] = useState<string[]>([]);
  useEffect(() => {
    setLive([]);
    if (value.service === "evren") return;
    let on = true;
    apiGet<{ models?: string[] }>(`/api/ucli/service-models?service=${encodeURIComponent(value.service)}`)
      .then((r) => on && setLive(r.models ?? []))
      .catch(() => {});
    return () => {
      on = false;
    };
  }, [value.service]);
  const [instr, setInstr] = useState<InstrCheck | null>(null);
  useEffect(() => {
    setInstr(null);
    if (!cwd) return;
    let on = true;
    apiGet<InstrCheck>(`/api/ucli/instructions-check?cwd=${encodeURIComponent(cwd)}`)
      .then((r) => on && setInstr(r))
      .catch(() => {});
    return () => {
      on = false;
    };
  }, [cwd]);
  const overFiles = (instr?.files ?? []).filter((f) => f.over);
  const broad = hasBroadGlob(value.execGlob);
  // canlı liste (hizmetin /models ucu) öncelikli; yoksa koddaki yedek liste
  const svc = { ...svcBase, models: live.length > 0 ? live : svcBase.models };
  return (
    <>
      {overFiles.length > 0 && (
        <span className="opts-hint" style={{ flexBasis: "100%", color: "#b45309" }} role="alert">
          {overFiles
            .map((f) => `${f.name} ${Math.round(f.bytes / 1024)} KB > ${Math.round((instr?.limit ?? 16384) / 1024)} KiB`)
            .join(", ")}
          {tr ? ": proje talimatları YÜKLENMEYECEK (ucli sınırı)" : ": project instructions will NOT be loaded (ucli limit)"}
        </span>
      )}
      <label>
        {tr ? "hizmet" : "service"}
        <select value={value.service} onChange={(e) => {
            const ns = SERVICES.find((x) => x.id === e.target.value);
            set({ service: e.target.value, serviceModel: ns && ns.models.length > 0 ? ns.models[0] : "" });
          }}>
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
          {svc.models.length > 0 && (
            <select
              value={svc.models.includes(value.serviceModel) ? value.serviceModel : value.serviceModel ? "__custom" : ""}
              onChange={(e) => set({ serviceModel: e.target.value === "__custom" ? "x-" : e.target.value })}
            >
              {svc.models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
              <option value="__custom">{tr ? "başka (elle yaz)…" : "other (type)…"}</option>
            </select>
          )}
          {(svc.models.length === 0 || (value.serviceModel !== "" && !svc.models.includes(value.serviceModel))) && (
            <input
              type="text"
              placeholder="model id"
              value={value.serviceModel === "x-" ? "" : value.serviceModel}
              onChange={(e) => set({ serviceModel: e.target.value })}
            />
          )}
        </label>
      )}
      <label title={tr ? "Varsayılan kapalı. Yalnız gerekirse aç." : "Off by default. Enable only when needed."}>
        <input type="checkbox" checked={value.execOn} onChange={(e) => set({ execOn: e.target.checked })} /> exec
      </label>
      {value.execOn && (
        <>
          <input
            type="text"
            title={tr ? "Virgülle: komut adı, glob (cargo*) ya da re:<regex>. * = PATH'teki her komut (kabuk/env/xargs/ssh/nc/sudo... HARİÇ)." : "Comma separated: command name, glob (cargo*) or re:<regex>. * = every command on PATH (EXCEPT shells/env/xargs/ssh/nc/sudo...)."}
            placeholder={tr ? "izinli komutlar: * | cargo* | re:^py.*$ | git" : "allowed commands: * | cargo* | re:^py.*$ | git"}
            value={value.execCmds}
            onChange={(e) => set({ execCmds: e.target.value })}
          />
          <input
            type="text"
            placeholder={tr ? "modelin yazdığı dosyalar: tests/**" : "model-written files: tests/**"}
            value={value.execGlob}
            onChange={(e) => set({ execGlob: e.target.value })}
          />
          {broad && (
            <span className="opts-hint" style={{ flexBasis: "100%", color: "#b91c1c" }} role="alert">
              {tr
                ? "Uyarı: bu desen modelin yazdığı TÜM dosyalara çalıştırma izni verir. Kabul etmek için işaretle (işaretsizse sunucu başlatmayı reddeder)."
                : "Warning: this pattern allows executing ALL files the model writes. Tick to accept (unticked, the server refuses to start)."}{" "}
              <label>
                <input type="checkbox" checked={value.acceptRisk} onChange={(e) => set({ acceptRisk: e.target.checked })} />{" "}
                {tr ? "Riski kabul ediyorum" : "I accept the risk"}
              </label>
            </span>
          )}
          <label title={tr ? "Varsayılan kapalı. Açılınca modele dosya yazma katmanı (--allow-edit) verilir." : "Off by default. When on, the model gets the file-write tier (--allow-edit)."}>
            <input type="checkbox" checked={value.execWrite} onChange={(e) => set({ execWrite: e.target.checked })} /> {tr ? "yazma izni" : "write access"}
          </label>
          <input
            type="text"
            placeholder={tr ? "bağlanacak dizinler (salt okunur): /home/ben/.rustup/toolchains/X" : "dirs to bind (read-only): /home/ben/.rustup/toolchains/X"}
            value={value.execBind}
            onChange={(e) => set({ execBind: e.target.value })}
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
              ? "Komutlar kafes içinde (bwrap, ağsız) çalışır; kafes yalnız çalışma alanını yazılabilir görür. cargo/node gibi araç zinciri için kafese salt okunur bağlanacak MUTLAK dizinleri yaz (örn. /home/ben/.rustup/toolchains/X). Komut alanı: ad, glob (cargo*) ya da re:<regex>; * her komut demektir ama kabuk/env/xargs/find/sudo/ssh/nc HİÇBİR desenle açılmaz. Ağ sunulmaz. Komut yoksa exec kapalı kalır."
              : "Commands run in a no-network bwrap cage where only the workspace is writable. For toolchains (cargo, node) list ABSOLUTE dirs to bind read-only (e.g. /home/me/.rustup/toolchains/X). Command field: name, glob (cargo*) or re:<regex>; * means every command but shells/env/xargs/find/sudo/ssh/nc are never opened by any pattern. No network. With no commands exec stays off."}
          </span>
        </>
      )}
    </>
  );
}

/**
 * Effort levels valid for the chosen service + model, from the service's `efforts` table in Settings (longest key found
 * in the model id wins). `null` = no rule (keep the CLI's own list); `[]` = this model takes no effort.
 */
export function serviceEffortLevels(services: UcliServiceDef[] | undefined, service: string, model: string): string[] | null {
  if (service === "evren") return null;
  const d = services?.find((x) => x.id === service);
  const m = model.toLowerCase();
  const keys = Object.keys(d?.efforts ?? {}).filter((k) => m.includes(k));
  if (!d || keys.length === 0) return null;
  keys.sort((a, b) => b.length - a.length);
  return d.efforts?.[keys[0]] ?? null;
}
