"""Fleet snapshot — çalışan session'ların anlık görüntüsünü kaydet/geri-yükle.

TODO.md 2026-09-16 maddesi (kullanıcı: "last running snapshot gibi bisi olmali.
makineyi kapatinca kaldigi yerden devam etmesi icin"): guard kasıtlı kapalı
([[feedback-manual-fleet-control]]), bu yüzden reboot sonrası fleet'i geri açmak
[[reboot-recovery]]'nin otomatik jsonl-resume mekanizmasından FARKLI — açıkça
kullanıcı-tetiklemeli üç adım (kaydet → görüntüle → geri-yükle).

2026-09-21 genişletmesi (kullanıcı: "en son snapshot almayi unuttum ve son
snapshot farkli bir conf gosteriyor... snapshot listesi coklu olmali... eger
kapanirken son snapshot ile kapanirkenki cli lar ayni ise sorun yok ama farkli
ise kapanis snapshati diye kaydetmeli") — tek-kayıt modelinden (`last_
snapshot.json`, her `save_snapshot()` çağrısında ÜZERİNE YAZILAN) bir GEÇMİŞE
(`snapshots.json`, liste) geçildi, iki `kind` ile:
  - "manual"  — kullanıcının panelindeki "Snapshot kaydet" düğmesi, HER ZAMAN
    yeni bir girdi ekler.
  - "closing" — panel süreci SIGTERM alınca OTOMATİK (`commands/web.py`'nin
    `run()`'daki handler'ı — systemd `stop`/`restart`/gerçek shutdown hepsi
    aynı sinyali gönderir), ama SADECE fleet en son kaydedilenden FARKLIYSA;
    aynıysa kullanıcının kendi kuralınca sessizce atlanır, kopya YARATILMAZ.
Eski `last_snapshot.json` silinmedi — ilk `_load_all()` çağrısında (dosya
`snapshots.json` henüz yokken) BİR KEZ listeye "manual" girdisi olarak
göçürülür, kullanıcının o ana kadar elle aldığı gerçek kayıt kaybolmaz.

Leaf modül (sadece atomic_json/paths'e bağımlı) — settings.py ile aynı disiplin,
commands/ paketine bağımlı olmayan modüller de sorunsuz import edebilsin.
"""
from __future__ import annotations
import json
import os
import time
from typing import Any, Dict, List, Optional

from .atomic_json import atomic_write_json
from .paths import CLAUDEOPS_DIR

SNAPSHOT_JSON = os.path.join(CLAUDEOPS_DIR, "last_snapshot.json")  # legacy — sadece bir kerelik migrasyon kaynağı
SNAPSHOTS_JSON = os.path.join(CLAUDEOPS_DIR, "snapshots.json")

# Sonsuz büyümesin diye üst sınır — en eski kayıtlar sessizce düşer. Günde
# birkaç "closing" + ara sıra elle "manual" ile bile haftalarca geçmiş tutar.
MAX_SNAPSHOTS = 50


def _entry_key(e: Dict[str, Any]):
    return (e.get("name"), e.get("cwd"), e.get("model"), e.get("permission_mode"),
            e.get("effort"), e.get("cli"))


def _same_sessions(a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> bool:
    """Sıradan bağımsız küme karşılaştırması — `find_sessions()`'ın proc-tarama
    sırası garantili değil, önemli olan HANGİ session'ların (hangi GERÇEK
    model/permission_mode/effort/cli ile) çalıştığı, listede kaçıncı sırada
    oldukları değil."""
    return {_entry_key(x) for x in a} == {_entry_key(x) for x in b}


def _migrate_legacy() -> List[Dict[str, Any]]:
    """`snapshots.json` hiç yoksa ama eski tek-kayıt `last_snapshot.json` varsa
    onu listeye "manual" girdisi olarak taşır — bir kereliğine; `snapshots.json`
    bir kez yazılınca (aşağıdaki `save_snapshot()`) bir daha tetiklenmez."""
    try:
        with open(SNAPSHOT_JSON, encoding="utf-8") as f:
            legacy = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(legacy, dict) or not isinstance(legacy.get("sessions"), list):
        return []
    return [{"saved_at": legacy.get("saved_at") or time.time(), "kind": "manual",
             "sessions": legacy["sessions"]}]


def _load_all() -> List[Dict[str, Any]]:
    try:
        with open(SNAPSHOTS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return _migrate_legacy()


def save_snapshot(sessions: List[Dict[str, Any]], kind: str = "manual") -> Dict[str, Any]:
    """`sessions`: [{"name","cwd","model","permission_mode","effort","cli"}] —
    çağıran (web.py) canlı Session listesinden bu şekli üretir; burası sadece
    diske yazar (discovery'ye bağımlı DEĞİL, leaf disiplini).

    `kind="manual"` HER ZAMAN yeni bir girdi ekler. `kind="closing"` SADECE
    fleet en son kayıttan FARKLIYSA ekler — aynıysa var olan son girdiyi
    olduğu gibi döner (kullanıcının kuralı: "aynıysa sorun yok")."""
    all_snaps = _load_all()
    if kind == "closing" and all_snaps and _same_sessions(all_snaps[-1]["sessions"], sessions):
        return all_snaps[-1]
    entry = {"saved_at": time.time(), "kind": kind, "sessions": sessions}
    all_snaps.append(entry)
    del all_snaps[:-MAX_SNAPSHOTS]
    atomic_write_json(SNAPSHOTS_JSON, all_snaps)
    return entry


def load_latest_snapshot() -> Dict[str, Any]:
    """En son kayıt (manuel ya da kapanış, hangisi daha yeniyse) — `/api/status`'ın
    "Son snapshot: X" özeti + varsayılan (saved_at verilmeyen) resume hedefi
    için. Eksik/bozuk dosyaya toleranslı (settings.py'nin load_settings()'iyle
    aynı tolerans deseni)."""
    all_snaps = _load_all()
    if all_snaps:
        return all_snaps[-1]
    return {"saved_at": None, "kind": None, "sessions": []}


def get_snapshot(saved_at: float) -> Optional[Dict[str, Any]]:
    """Geçmiş listesindeki BELİRLİ bir kaydı (panelin "geri yükle" tıklaması
    hangi satırı seçtiyse) `saved_at`'ine göre bulur — float'lar JSON round-trip
    sonrası birebir aynı kalır, ayrı bir id alanı gerekmez."""
    for s in _load_all():
        if s.get("saved_at") == saved_at:
            return s
    return None


def list_snapshots() -> List[Dict[str, Any]]:
    """Panelin geçmiş listesi için METADATA-only (tam session gövdesi YOK —
    `_snapshot_info()`'nun "gereksiz büyük" gerekçesiyle aynı), en yeni ÖNCE."""
    return [{"saved_at": s.get("saved_at"), "kind": s.get("kind", "manual"),
             "count": len(s.get("sessions") or [])}
            for s in reversed(_load_all())]
