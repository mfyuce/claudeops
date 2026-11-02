/**
 * Plain-language wrapper for ucli-tab error strings. The raw message (backend text or `describeApiError`) is always
 * kept after the explanation, so nothing is hidden; unknown messages come back unchanged.
 */
import type { Lang } from "../i18n/strings";

const RULES: { re: RegExp; tr: string; en: string }[] = [
  { re: /failed to fetch|networkerror|load failed|network request/i, tr: "Sunucuya ulaşılamadı. claudeops web sunucusu çalışıyor mu, bağlantı kopmuş olabilir mi?", en: "Could not reach the server. Is the claudeops web server running, or did the connection drop?" },
  { re: /\b401\b|unauthori[sz]ed|yetkisiz/i, tr: "Oturum yetkisi geçersiz. Sayfayı yenile ya da yeniden giriş yap.", en: "Not authorised. Reload the page or sign in again." },
  { re: /\b403\b|forbidden/i, tr: "Bu işlem bu oturumdan yapılamıyor (yalnız insan/yerel kullanıcı).", en: "This action is not allowed from this session (human/local user only)." },
  { re: /\b5\d\d\b|unexpected response|internal server/i, tr: "Sunucu beklenmeyen bir yanıt verdi. Birazdan yeniden dene; sürerse Tanılama sekmesine bak.", en: "The server returned an unexpected response. Retry shortly; if it persists, check the Diagnostics tab." },
  { re: /timed? ?out|zaman aşımı/i, tr: "İstek zaman aşımına uğradı. Ağ ya da model hizmeti yavaş olabilir.", en: "The request timed out. The network or model service may be slow." },
  { re: /api[_ ]?key|anahtar|\bkey\b.*(missing|not set|yok)/i, tr: "Model anahtarı eksik ya da geçersiz. \"Model anahtarları\" bölümünden kaydet.", en: "Model key missing or invalid. Save it in the \"Model keys\" section." },
  { re: /cap|tavan|budget|limit/i, tr: "Harcama ya da kullanım sınırına takılmış olabilir. Harcama özetine ve tavan ayarına bak.", en: "A spending or usage limit may have been hit. Check the spend summary and cap setting." },
  { re: /exec|toolchain|araç zinciri|geçersiz.*dizin/i, tr: "Komut/araç zinciri ayarı reddedildi. Komut adları yalın olmalı, dizinler mutlak ve dar olmalı.", en: "The exec/toolchain setting was rejected. Use plain command names and narrow absolute dirs." },
];

/** Generic (non-ucli) variant: only the connection/auth/server/timeout rules, so other tabs do not get ucli-specific advice. */
export function friendlyError(raw: string, lang: Lang): string {
  const msg = (raw || "").trim();
  if (!msg) return msg;
  const hit = RULES.slice(0, 5).find((r) => r.re.test(msg));
  return hit ? `${lang === "tr" ? hit.tr : hit.en}\n${msg}` : msg;
}

export function friendlyUcliError(raw: string, lang: Lang): string {
  const msg = (raw || "").trim();
  if (!msg) return msg;
  const hit = RULES.find((r) => r.re.test(msg));
  if (!hit) return msg;
  return `${lang === "tr" ? hit.tr : hit.en}\n${msg}`;
}
