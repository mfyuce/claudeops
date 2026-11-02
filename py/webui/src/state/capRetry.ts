/**
 * Günlük ucli USD tavanı yüzünden REDDEDİLEN başlatma (backend `code: "ucli_daily_cap"`, bkz. `ucli_cost.refusal`).
 * Tüm başlatma girişleri (Kayıtlı/GroupTable, Geçmiş/HistoryTab, Çalışanlar/OptionsRow + BulkBar) reddi AYNI yoldan
 * bildirir: `offerCapRetry(...)`. `<CapRetryPrompt>` (App'te bir kez bağlı) "tavanı X USD yap ve tekrar dene" sunar.
 * `toast.ts` gibi modül düzeyinde pub-sub: çağıranlar düz async fonksiyonlardır, Context'e ulaşamaz.
 */

import { LOCAL_HOST } from "./hosts";

export const CAP_CODE = "ucli_daily_cap";

export interface CapRefusal {
  ok: false;
  error: string;
  code?: string;
  today_usd?: number;
  cap_usd?: number;
}

/** What a retried start may return. */
export type CapRetryResult = { ok: boolean; error?: string; code?: string; today_usd?: number; cap_usd?: number };

export interface CapPrompt {
  id: number;
  name: string;
  error: string;
  todayUsd: number;
  capUsd: number;
  retry: () => Promise<CapRetryResult>;
}

export function isCapRefusal(res: { ok: boolean; code?: string } | null | undefined): res is CapRefusal {
  return !!res && res.ok === false && res.code === CAP_CODE;
}

/** Önerilen yeni tavan: bugünkü harcamanın üstünde, 5'in katına yuvarlanmış. */
export function suggestCap(todayUsd: number, capUsd: number): number {
  const base = Math.max(todayUsd, capUsd);
  return Math.ceil((base + 1) / 5) * 5 + 5;
}

type Listener = (p: CapPrompt | null) => void;
let current: CapPrompt | null = null;
let nextId = 1;
const listeners = new Set<Listener>();

function emit(): void {
  for (const l of listeners) l(current);
}

/**
 * Reddi bir istemle sunar. `false` döner (çağıran eski toast yoluna düşer) eğer ret tavan reddi değilse ya da
 * başlatma UZAK bir host'ta olduysa (tavan ayarı yerel makinenin; uzak hosta yazılamaz).
 */
export function offerCapRetry(
  res: { ok: boolean; error?: string; code?: string; today_usd?: number; cap_usd?: number },
  name: string,
  host: string,
  retry: () => Promise<CapRetryResult>,
): boolean {
  if (!isCapRefusal(res) || host !== LOCAL_HOST) return false;
  current = {
    id: nextId++,
    name,
    error: res.error,
    todayUsd: res.today_usd ?? 0,
    capUsd: res.cap_usd ?? 0,
    retry,
  };
  emit();
  return true;
}

export function dismissCapRetry(): void {
  current = null;
  emit();
}

export function subscribeCapRetry(l: Listener): () => void {
  listeners.add(l);
  l(current);
  return () => listeners.delete(l);
}
