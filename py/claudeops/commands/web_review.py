"""reviewer değnekçi motoru (adım 2: yalnız iskelet).

`web_steward.tick_round`, rolü `reviewer` olan ve AÇIK kimlik için `tick_once`/`passive_scan`/kart/beyin/kapatma
yerine YALNIZ `review_tick(cfg)` çağırır. reviewer kimliği hiçbir tmux oturumuna dokunmaz (`web_steward._target` onu
her zaman reddeder), `projects.json`'a yazmaz (`steward.upsert_project`/`transfer_project` `ReviewerRefused`), beyni
yoktur (`brain_start` reddeder); havuzu `review_pool.json`, geçmişi `review_history.json` (`review.py` saf çekirdeği).

Adım 5'te doldurulacak: havuz eşitleme (`review.pool_sync`), sıradaki çift (`review.next_review`), Evren/agy
çalıştırıcıları (kendi `Popen`'ı, zaman aşımı, iptal), sonuç dosyası + bulgu çıkarımı.

Bu modül `web.py`'yi ve `web_steward`'ı İÇE AKTARMAZ (döngü yok; eylemler gerekirse geri çağrıyla verilir)."""
from typing import Any, Dict

from .. import steward as sw


def review_tick(cfg: sw.Config) -> Dict[str, Any]:
    """Bir reviewer kimliğinin döngü turu. Şimdilik no-op: hiçbir dosyaya/oturuma/sürece dokunmaz."""
    return {"ok": True, "actions": [], "started": 0, "noop": True}
