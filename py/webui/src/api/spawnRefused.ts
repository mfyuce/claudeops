/**
 * Core UI text for a refused session start (`403 {"error":"spawn_refused","reason","detail"}`).
 * The core keeps only this code table; quota logic itself lives in the enterprise layer (OSS boundary).
 * Unknown codes fall back to the raw `reason: detail`, so nothing is hidden.
 */
import type { Lang } from "../i18n/strings";

const RULES: { re: RegExp; tr: (m: RegExpMatchArray) => string; en: (m: RegExpMatchArray) => string }[] = [
  { re: /^login_required:(.+)$/, tr: (m) => `${m[1]} için önce kendi hesabınla giriş yapmalısın.`, en: (m) => `Sign in to ${m[1]} with your own account first.` },
  { re: /^quota_sessions/, tr: () => "Eşzamanlı oturum sınırına ulaştın; başlatmak için açık bir oturumu kapat.", en: () => "You have reached your concurrent session limit; close an open session to start another." },
  { re: /^quota_usd_day/, tr: () => "Günlük harcama (USD tahmini) sınırın doldu; yeni oturum yarın açılabilir.", en: () => "Your daily spend (estimated USD) limit is used up; new sessions can start tomorrow." },
  { re: /^quota_tokens_day/, tr: () => "Günlük token sınırın doldu; yeni oturum yarın açılabilir.", en: () => "Your daily token limit is used up; new sessions can start tomorrow." },
  { re: /^quota_/, tr: () => "Kullanıcı kotan doldu.", en: () => "Your user quota is used up." },
  { re: /^hook_error$/, tr: () => "Başlatma kontrolü başarısız oldu (güvenli tarafta reddedildi); yöneticiye bildir.", en: () => "The start check failed (refused to be safe); tell your administrator." },
];

export function describeSpawnRefused(reason: string, detail: string | undefined, lang: Lang): string {
  const raw = detail ? `${reason}: ${detail}` : reason;
  for (const r of RULES) {
    const m = reason.match(r.re);
    if (m) return `${(lang === "tr" ? r.tr : r.en)(m)}\n${raw}`;
  }
  return raw;
}
