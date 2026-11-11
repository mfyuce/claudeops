/**
 * "Why is this project not moving?" pieces of the steward tab (11 Nov 2026, owner: "1000 TODOs and they say there is no
 * work? are these rules in the UI?"): the per-project reason cell (derived by the engine from the same conditions it
 * decides with, `steward.explain_idle`), the settings of the rules that hold projects back, and the loop-guard box.
 */
import { apiStewardConfig, apiStewardLoopReset } from "../api/client";
import type { SimpleResult, StewardLoopGuard, StewardProject } from "../api/types";
import { NumberSetting } from "./shared/NumberSetting";
import { showToast } from "../state/toast";

type Run = <T extends SimpleResult>(fn: () => Promise<T>, after?: (r: T) => void) => Promise<void>;

/** Codes that mean "progressing / about to": shown muted, everything else is a hold reason shown in amber. */
const OK_CODES = new Set(["working", "starting", "nudging", "running", "idle_wait", "cadence_wait", "answer_pending"]);

function when(ts: number): string {
  return new Date(ts * 1000).toLocaleString(undefined, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function WhyCell({ why, lang }: { why: StewardProject["why"]; lang: string }) {
  if (!why) return <span className="opts-hint">{lang === "en" ? "(next tick)" : "(sonraki tick)"}</span>;
  const age = Math.max(0, Math.round((Date.now() / 1000 - why.at) / 60));
  const tip = `${why.code}${why.detail ? ` · ${why.detail}` : ""} · ${lang === "en" ? `computed ${age} min ago` : `${age} dk önce hesaplandı`}`;
  return (
    <span title={tip} style={{ color: OK_CODES.has(why.code) ? "var(--muted)" : "var(--amber, #d97706)" }}>
      {why.text}
      {why.detail ? <span className="opts-hint" style={{ display: "block", fontSize: ".7rem" }}>{why.detail}</span> : null}
      {why.next_work ? (
        <span className="opts-hint" style={{ display: "block", fontSize: ".7rem" }}
          title={lang === "en" ? "Reported by the session (STEWARD-NEXT); informational" : "Oturumun bildirdiği (STEWARD-NEXT); yalnız bilgi"}>
          {lang === "en" ? "next: " : "sıradaki: "}{why.next_work.text}
        </span>
      ) : null}
      {why.owner_in_todo ? (
        <span className="opts-hint" style={{ display: "block", fontSize: ".7rem", color: "var(--amber, #d97706)" }}
          title={lang === "en" ? "Move them to TOBEDECIDED.md; TODO.md should hold only ownerless work" : "TOBEDECIDED.md'ye taşınmalı; TODO.md'de yalnız sahipsiz iş kalmalı"}>
          {lang === "en" ? `${why.owner_in_todo} owner-bound item(s) in TODO` : `TODO'da sahibe bağlı ${why.owner_in_todo} madde`}
        </span>
      ) : null}
    </span>
  );
}

const CHOICES: { key: string; tr: string; en: string; hintTr: string; hintEn: string }[] = [
  { key: "claude_idle", tr: "boşta dürtme (claude)", en: "idle nudge (claude)",
    hintTr: "off = hiç; dry = yalnız ölçer, dürtme GİTMEZ; act = 'devam: <iş>' gönderir", hintEn: "off = never; dry = only measures, nothing is sent; act = sends 'devam: <work>'" },
  { key: "keepwarm", tr: "keepwarm", en: "keepwarm", hintTr: "önbellek canlı tutma dürtmesi (off | dry | act)", hintEn: "cache keep-alive nudge (off | dry | act)" },
  { key: "wake_gate", tr: "uyandırma kapısı", en: "wake gate", hintTr: "aynı metinli tekrar direktifi: dry = yalnız olay, act = göndermez", hintEn: "repeated same-text directive: dry = event only, act = not sent" },
];

const NUMS: { key: string; tr: string; en: string }[] = [
  { key: "claude_idle_nudge_secs", tr: "dürtme eşiği (sn)", en: "nudge threshold (s)" },
  { key: "ucli_idle_max_consecutive", tr: "dürtme hakkı (art arda)", en: "nudge budget (consecutive)" },
  { key: "max_starts_total", tr: "tick başına en çok başlatma (makine geneli)", en: "max starts per round (machine-wide)" },
];

export function IdleRules({ config, sid, run, busy, lang }: { config: Record<string, unknown> | undefined; sid?: string; run: Run; busy: boolean; lang: string }) {
  const en = lang === "en";
  const saved = () => showToast(en ? "Saved" : "Kaydedildi", "success");
  return (
    <div className="opts" style={{ marginTop: ".4rem", alignItems: "center" }}>
      <span className="legend" style={{ margin: 0 }}>{en ? "Rules that hold projects back" : "Projeyi bekleten kurallar"}:</span>
      {CHOICES.map((c) => (
        <label key={c.key} className="opts-hint" title={en ? c.hintEn : c.hintTr}>
          {en ? c.en : c.tr}{" "}
          <select value={String(config?.[c.key] ?? "")} disabled={busy}
            onChange={(e) => void run(() => apiStewardConfig(c.key, e.target.value, sid), saved)}>
            <option value="off">off</option>
            <option value="dry">dry</option>
            <option value="act">act</option>
          </select>
        </label>
      ))}
      <label className="opts-hint" title={en ? "off: the engine never opens a session on cadence (only answers/brain)" : "off: motor cadence ile hiç oturum açmaz (yalnız cevap/beyin)"}>
        <input type="checkbox" checked={config?.auto_start !== false} disabled={busy}
          onChange={(e) => void run(() => apiStewardConfig("auto_start", e.target.checked ? "on" : "off", sid), saved)} />{" "}
        auto_start
      </label>
      {NUMS.map((n) => {
        const v = Number(config?.[n.key]);
        return Number.isFinite(v) ? (
          <NumberSetting key={n.key} label={en ? n.en : n.tr} value={v} onSave={(x) => void run(() => apiStewardConfig(n.key, x, sid), saved)} />
        ) : null;
      })}
    </div>
  );
}

export function LoopGuardBox({ items, sid, run, busy, lang }: { items: StewardLoopGuard[] | undefined; sid?: string; run: Run; busy: boolean; lang: string }) {
  const en = lang === "en";
  if (!items || items.length === 0) return null;
  return (
    <div className="opts" style={{ flexDirection: "column", alignItems: "flex-start", gap: ".2rem" }}>
      <span className="legend" style={{ margin: 0 }}>
        {en ? "Loop guard (same action repeated with no change on the target)" : "Döngü koruması (hedefte değişiklik yokken tekrar eden eylem)"}
      </span>
      {items.map((g) => (
        <span key={g.key} className="opts-hint">
          <code>{g.kind}</code> → {g.name}:{" "}
          {g.paused
            ? <b style={{ color: "var(--red, #dc2626)" }}>{en ? `STOPPED, paused until ${when(g.until)}` : `DURDU, ${when(g.until)} saatine dek duraklatıldı`}</b>
            : (en ? `repeat ${g.n}/${g.max}` : `tekrar ${g.n}/${g.max}`)}{" "}
          <button type="button" disabled={busy} onClick={() => void run(() => apiStewardLoopReset(g.key, sid), () => showToast(en ? "Reset" : "Sıfırlandı", "success"))}>
            {en ? "reset" : "sıfırla"}
          </button>
        </span>
      ))}
      {items.length > 1 && (
        <button type="button" disabled={busy} onClick={() => void run(() => apiStewardLoopReset("", sid), () => showToast(en ? "Reset" : "Sıfırlandı", "success"))}>
          {en ? "reset all" : "hepsini sıfırla"}
        </button>
      )}
    </div>
  );
}
