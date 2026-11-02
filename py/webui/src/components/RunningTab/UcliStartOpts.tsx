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
  /** Ready-made Rust toolchain (`exec_toolchain: "rust"`): the backend finds cargo/rustc + binds them read-only. */
  execToolchain: boolean;
  /** Per-turn USD ceiling (`max_cost_usd`), empty = none. */
  maxCost: string;
}

/** One-click start presets (coder = may run+write in the cage with the Rust toolchain; reviewer = read-only, no exec). */
export interface UcliPreset {
  id: "coder" | "reviewer" | "light";
  tr: string;
  en: string;
  tipTr: string;
  tipEn: string;
  /** Model / effort live in `OptionsRow` (not in `UcliStartState`); they reach it through `onPreset`. */
  model?: string;
  effort?: string;
  patch: Partial<UcliStartState>;
}

export const UCLI_PRESETS: UcliPreset[] = [
  {
    id: "coder",
    tr: "Koder",
    en: "Coder",
    tipTr: "claude-sonnet-5-5, orta düşünme, dosya yazma izni, exec: git + Rust (cargo/rustc), tur tavanı 1 USD.",
    tipEn: "claude-sonnet-5-5, medium effort, file write, exec: git + Rust (cargo/rustc), turn cap 1 USD.",
    model: "claude-sonnet-5-5",
    effort: "medium",
    patch: { execOn: true, execCmds: "git", execWrite: true, execToolchain: true, execGlob: "", acceptRisk: false, maxCost: "1" },
  },
  {
    id: "reviewer",
    tr: "Reviewer",
    en: "Reviewer",
    tipTr: "Salt okunur inceleme: exec ve yazma kapalı, orta düşünme, tur tavanı 0.50 USD.",
    tipEn: "Read-only review: exec and write off, medium effort, turn cap 0.50 USD.",
    effort: "medium",
    patch: { execOn: false, execWrite: false, execToolchain: false, execGlob: "", acceptRisk: false, maxCost: "0.50" },
  },
  {
    id: "light",
    tr: "Hafif sohbet",
    en: "Light chat",
    tipTr: "Kısa soru-cevap: exec ve yazma kapalı, düşük düşünme, tur tavanı 0.20 USD.",
    tipEn: "Quick Q&A: exec and write off, low effort, turn cap 0.20 USD.",
    effort: "low",
    patch: { execOn: false, execWrite: false, execToolchain: false, execGlob: "", acceptRisk: false, maxCost: "0.20" },
  },
];

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
  execToolchain: false,
  maxCost: "",
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
    if (s.execToolchain) o.exec_toolchain = "rust";
  }
  if (s.maxCost.trim()) o.max_cost_usd = s.maxCost.trim();
  return Object.keys(o).length ? o : undefined;
}

interface Props {
  value: UcliStartState;
  onChange: (v: UcliStartState) => void;
  lang: Lang;
  /** Session working directory (local sessions): used for the 16 KiB instruction-file warning. */
  cwd?: string;
  /** Called with a preset's model/effort so the parent can fill its own fields. */
  onPreset?: (p: UcliPreset) => void;
}

export function UcliStartOpts({ value, onChange, lang, cwd, onPreset }: Props) {
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
      <label title={tr ? "Hazır bir ayar seç: model, düşünme düzeyi, izinler ve tur tavanı birlikte dolar. Sonra istediğin alanı elle değiştirebilirsin." : "Pick a preset: model, effort, permissions and turn cap are filled together. You can still edit any field."}>
        {tr ? "ön ayar" : "preset"}
        <select
          value=""
          onChange={(e) => {
            const p = UCLI_PRESETS.find((x) => x.id === e.target.value);
            if (!p) return;
            set(p.patch);
            onPreset?.(p);
          }}
        >
          <option value="">{tr ? "seç…" : "choose…"}</option>
          {UCLI_PRESETS.map((p) => (
            <option key={p.id} value={p.id} title={tr ? p.tipTr : p.tipEn}>
              {tr ? p.tr : p.en}
            </option>
          ))}
        </select>
      </label>
      <label title={tr ? "Tur (görev) başına tahmini USD tavanı; aşılınca tur toparlanır. Boş = sınırsız." : "Estimated USD ceiling per turn; the turn wraps up when exceeded. Empty = no limit."}>
        {tr ? "tur tavanı (USD)" : "turn cap (USD)"}
        <input type="text" size={5} inputMode="decimal" placeholder="0.50" value={value.maxCost} onChange={(e) => set({ maxCost: e.target.value })} />
      </label>
      {overFiles.length > 0 && (
        <span className="opts-hint" style={{ flexBasis: "100%", color: "#b45309" }} role="alert">
          {overFiles
            .map((f) => `${f.name} ${Math.round(f.bytes / 1024)} KB > ${Math.round((instr?.limit ?? 40960) / 1024)} KiB`)
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
            title={tr ? "Modelin yazdığı dosyalardan hangilerinin çalıştırılabileceğini belirleyen dar glob (örn. tests/**). Boş = yazılan dosya çalıştırılamaz." : "Narrow glob of model-written files that may be executed (e.g. tests/**). Empty = written files cannot be executed."}
            placeholder={tr ? "çalıştırılabilir yazılan dosyalar: tests/**" : "executable model-written files: tests/**"}
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
          <label title={tr ? "none: araç zinciri yok. rust: sunucu cargo/rustc'yi bulup kafese salt okunur bağlar; elle dizin yazmana gerek kalmaz. Ağ yok, çevrimdışı derler." : "none: no toolchain. rust: the server finds cargo/rustc and binds them read-only; no manual dirs needed. No network, builds offline."}>
            {tr ? "exec_toolchain (araç zinciri)" : "exec_toolchain"}
            <select value={value.execToolchain ? "rust" : "none"} onChange={(e) => set({ execToolchain: e.target.value === "rust" })}>
              <option value="none">none</option>
              <option value="rust">rust</option>
            </select>
          </label>
          <input
            type="text"
            title={tr ? "Kafese salt okunur bağlanacak MUTLAK dizinler (virgülle). Rust için yukarıdaki exec_toolchain=rust yeterli." : "ABSOLUTE dirs to bind read-only into the cage (comma separated). For Rust, exec_toolchain=rust above is enough."}
            placeholder={tr ? "bağlanacak dizinler (salt okunur): /home/ben/.rustup/toolchains/X" : "dirs to bind (read-only): /home/ben/.rustup/toolchains/X"}
            value={value.execBind}
            onChange={(e) => set({ execBind: e.target.value })}
          />
          <input
            type="text"
            size={6}
            title={tr ? "Her komut için saniye cinsinden zaman aşımı. Boş = sunucu varsayılanı." : "Per-command timeout in seconds. Empty = server default."}
            placeholder={tr ? "zaman aşımı sn" : "timeout s"}
            value={value.execTimeout}
            onChange={(e) => set({ execTimeout: e.target.value })}
          />
          <span className="opts-hint" style={{ flexBasis: "100%" }}>
            {tr
              ? "Çoğu iş için exec gerekmez: oturumda zaten dosya okuma, arama, json_query, pipeline, git_* ve date_text araçları var. exec son çare. Açarsan komutlar ağsız bir kafeste çalışır ve yalnız çalışma alanına yazabilir. İzinli komutları yaz (ad, cargo* gibi glob ya da re:<regex>; * = her komut, ama kabuk/env/xargs/find/sudo/ssh/nc hiçbir desenle açılmaz). Cargo/node gerekiyorsa exec_toolchain=rust seç ya da salt okunur bağlanacak MUTLAK dizinleri yaz. Komut boşsa exec kapalı kalır."
              : "Most tasks do not need exec: sessions already have file read, search, json_query, pipeline, git_* and date_text tools. Exec is a last resort. When on, commands run in a no-network cage and can only write inside the workspace. List allowed commands (name, a glob like cargo*, or re:<regex>; * = every command, but shells/env/xargs/find/sudo/ssh/nc are never opened by any pattern). For cargo/node pick exec_toolchain=rust or list ABSOLUTE dirs to bind read-only. With no commands, exec stays off."}
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
