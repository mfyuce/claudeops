/**
 * Bir session'ın "şu an kullandığı" model: çalışıyorsa `live_model` (claude için jsonl'daki
 * canlı değer, aksi halde cmdline'daki spawn-anı değer; bkz. web.py `_live_model_effort`),
 * çalışmıyorsa ya da bilinmiyorsa roster/instance KAYDINDAKİ `model` ("sonraki başlatmada
 * kullanılacak").
 *
 * Running tablosunun hücresi VE "mevcut modelle yeniden başlat" varsayılanları (OptionsRow,
 * AdoptRow, BulkBar) AYNI kaynağı kullansın diye tek yerde. TODO.md 2026-10-09: vc20261008
 * canlıda sonnet-5-5'e geçirilmişti, tablo ve restart varsayılanı kayıttaki haiku'yu
 * gösteriyordu.
 *
 * ⚠ `CliFields`'in `currentModelLabel`'i (model açılırında "" seçeneğinin etiketi) BİLEREK
 * bunu kullanmaz: "" seçeneği backend'de KAYITLI modele çözülür, etiket onu anlatmalı.
 */
import type { SessionInfo } from "../../api/types";

export function effectiveModel(s: Pick<SessionInfo, "running" | "model" | "live_model">): string {
  return (s.running && s.live_model) || s.model || "";
}
