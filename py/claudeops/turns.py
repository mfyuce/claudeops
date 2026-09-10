"""Paylaşımlı "tur bitene kadar bekle" primitifi.

`commands/web.py`'nin `/v1/chat/completions` (TOBEDECIDED#21, commit
`5d215ba`) için yazdığı `_v1_is_busy_now`/`_v1_wait_for_reply`'nin buraya
TAŞINMIŞ hali — TOBEDECIDED#15'in orkestrasyon motoru (`commands/
web_orch.py`) AYNI "canlı tmux session'ına metin enjekte et, sonra turun
bittiğini anla" mekanizmasına ihtiyaç duyunca ortaya çıkan paylaşım.

`/v1/*` çağıranı için davranış BİREBİR AYNI kaldı (aynı varsayılanlar:
`stable_polls=2`, marker yok, cancel yok) — sadece `stable_polls`/
`require_marker`/`cancel` YENİ, opsiyonel parametreler eklendi. `web.py`
artık bu modülün `wait_for_reply`/`is_busy_now`'ını doğrudan çağırıyor,
eski `_v1_*` fonksiyon gövdeleri silindi.

Hâlâ dürüst bir sınır: tmux-pane tabanlı bir sistemde "model turu bitirdi"
diye birinci-sınıf bir event YOK (bu proje bunu tekrar tekrar zor yoldan
öğrendi) — burası hâlâ bir sezgi, sadece biraz daha yapılandırılabilir bir
sezgi.
"""
from __future__ import annotations
import re
import threading
import time
from typing import Callable, Optional

from .diaglog import diag_log
from .tmux_backend import strip_ansi, tmux_capture

TIMEOUT_SECONDS = 180.0
POLL_INTERVAL_SECONDS = 0.5


def is_busy_now(name: str, pattern: str) -> bool:
    """(Eski `_v1_is_busy_now`.) `capture-pane` son 8 satır → `strip_ansi` →
    desen ara. Cache'siz (çağıranın kendi sıkı bekleme döngüsü için — panelin
    2s TTL'li `_is_busy_cached`'i BURADA KULLANILMAZ, bkz. modülün eski
    docstring'i web.py commit geçmişinde). Capture başarısız olursa (session
    gitti) False = "meşgul değil"."""
    text = tmux_capture(name, lines=8)
    if text is None:
        return False
    return bool(re.search(pattern, strip_ansi(text)))


def wait_for_reply(
    s, provider, baseline: dict, live_snapshot: object = None, *,
    timeout: float = TIMEOUT_SECONDS, poll: float = POLL_INTERVAL_SECONDS,
    stable_polls: int = 2, require_marker: Optional[str] = None,
    cancel: Optional[threading.Event] = None,
    push_check: Optional[Callable[[], Optional[str]]] = None,
) -> Optional[str]:
    """Enjekte edilen mesajın turu BİTENE kadar bekle, yeni asistan metnini
    döndür (timeout/cancel → None).

    İki strateji, ikisi de provider arayüzünden (dallanma YOK):
    1. `busy_status_pattern()` VARSA (claude): desen taze capture'da
       KAYBOLMUŞ olmalı VE `last_exchange()` baseline'dan FARKLI olmalı.
    2. Yoksa (codex/agy): `last_exchange()` `stable_polls` ARDIŞIK poll
       boyunca AYNI kalmalı (debounce). `/v1/*` (varsayılan 2, ~1s'lik
       belirsizlik hızlı bir sohbet yanıtı için yeterli) İLE orkestrasyon
       worker'ları (çağıran genelde 3, ~3s — dakikalarca süren bir işin
       sonunda biraz daha kesinlik karşılığında birkaç saniye fazladan
       bekleyebilir) arasındaki fark BU parametre.

    `require_marker` — VARSA (ör. `orchestration.END_MARKER`), "bitti" kararı
    yeni metnin bu marker'ı İÇERMESİNİ de şart koşar: zamanlama sezgisini bir
    İÇERİK sinyaline çevirir — yarım yazılmış bir yanıt kendi sonlandırıcısını
    henüz taşımadığı için yanlışlıkla "bitti" sayılamaz. Marker hiç
    görünmeden timeout'a düşülürse dönüş YİNE `None`'dır (`/v1/*`'in timeout
    dönüşüyle AYNI) — çağıran bunu ayırt etmek isterse kendi tarafında
    "marker hiç görünmedi" ile "gerçekten zaman aşımı" arasında ayrım
    yapmalı, bu fonksiyon ikisini birbirinden ayırmaz (tek bir "bitmedi"
    sonucu yeterli, TIMEOUT_SECONDS'lık pencerenin nasıl tükendiği önemli
    değil).

    `cancel` — her poll'da kontrol edilir; set edilmişse HEMEN `None` döner.
    Zaten gönderilmiş mesajı GERİ ALAMAZ, sadece beklemeyi durdurur.

    `live_snapshot` — `s.sid` BİLİNMİYORSA (fresh/hiç resume edilmemiş bir
    session — agy, 2026-09-09 commit `1356edc`) her poll'da
    `discover_live_sid()`'e verilir; bulunduğu anda `last_exchange`'in KENDİ
    sid'i olarak benimsenir. `live_snapshot=None` (varsayılan) = provider
    desteklemiyor (claude/codex) → davranış eskisiyle TAMAMEN AYNI.

    `push_check` (Phase 3, TOBEDECIDED#15 MCP server) — HER poll turunda,
    pane/transcript okumadan ÖNCE çağrılır; metin dönerse (bir katılımcının
    kendi `cops_result_push` MCP tool-call'ı, bkz. `commands/web_orch.py`'nin
    `_push_result`'ı) O METİN doğrudan döndürülür — normal pane-tail
    sezgisine hiç bakılmaz. None (VARSAYILAN) = bu yeteneği kullanmayan HER
    çağıran (`/v1/*` dahil) için no-op, davranış eskisiyle TAMAMEN AYNI."""
    pattern = provider.busy_status_pattern()
    previous: Optional[dict] = None
    stable_count = 0
    sid = s.sid
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancel is not None and cancel.is_set():
            return None
        time.sleep(poll)
        if cancel is not None and cancel.is_set():
            return None

        if push_check is not None:
            pushed = push_check()
            if pushed is not None:
                return pushed

        if sid is None and live_snapshot is not None:
            discovered = provider.discover_live_sid(s.cwd, live_snapshot)
            if discovered:
                sid = discovered
                diag_log("live_sid_discovered", name=s.name, sid=discovered)

        exchange = provider.last_exchange(s.cwd, sid)
        if exchange is None:
            return None  # çağıran bunu gönderimden ÖNCE eliyor; savunma amaçlı
        changed = exchange != baseline
        assistant_text = exchange.get("assistant", "")
        marker_ok = (require_marker is None) or (require_marker in assistant_text)

        if pattern:
            if not is_busy_now(s.name, pattern) and changed and marker_ok:
                return assistant_text
        else:
            if changed and exchange == previous:
                stable_count += 1
            else:
                stable_count = 1 if changed else 0
            previous = exchange
            if changed and marker_ok and stable_count >= stable_polls:
                return assistant_text
    return None
