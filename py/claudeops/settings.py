"""Kullanıcı-bazlı kalıcı ayarlar — ~/.claude/claudeops/settings.json.

roster.tsv/models.tsv/web.token ile AYNI "repo DIŞI, kaynak-of-truth" deseni
(2026-09-02 kullanıcı kararı, TODO L73: "these kind of settings must be kept
for the user... default model for ho, default model for new resume etc. app
theme etc" — sunucu-taraflı, TÜM cihaz/tarayıcılardan aynı ayarlar görünür).

Leaf modül (sadece paths'e bağımlı, diaglog.py'yle aynı disiplin) — handover.py
gibi commands/ PAKETİNE bağımlı olmayan modüller de sorunsuz import edebilsin.
"""
from __future__ import annotations
import json
import os
from typing import Any, Dict, TYPE_CHECKING

from .paths import CLAUDEOPS_DIR

if TYPE_CHECKING:
    from .providers.base import CliProvider

SETTINGS_JSON = os.path.join(CLAUDEOPS_DIR, "settings.json")

DEFAULT_SETTINGS: Dict[str, Any] = {
    "theme": "system",       # "system" | "light" | "dark"
    "handover_effort": "",   # "" = otomatik (default_handover_effort'un high-tercih mantığı)
    "default_model": {},     # {cli: model} — provider'ın kod-içi varsayımı (model_choices()[0])
                              # yerine geçen kalıcı tercih; yeni/resume dropdown'unun ön-dolu
                              # değeri OLDUĞU KADAR, aşağıdaki default_model_for()'un okuduğu
                              # backend fallback'i de bu (guard/stuck/handover/rc/web — "model
                              # verilmedi" durumunun HEPSİ artık buraya bakıyor, bkz. fonksiyon).
}


def load_settings() -> Dict[str, Any]:
    """Eksik/bozuk dosyaya karşı toleranslı — her zaman DEFAULT_SETTINGS'in TÜM
    anahtarlarını içeren tam bir dict döner, çağıran hiçbir zaman KeyError riski
    taşımaz (best-effort, [[diaglog.py]]'nin diag_log'uyla aynı tolerans)."""
    out: Dict[str, Any] = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_JSON, encoding="utf-8") as f:
            stored = json.load(f)
        if isinstance(stored, dict):
            out.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
            if not isinstance(out.get("default_model"), dict):
                out["default_model"] = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return out


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    """`patch`'i mevcut ayarların ÜSTÜNE merge edip diske yaz, YENİ TAM ayarları
    döndür. Bilinmeyen anahtarlar sessizce atlanır (DEFAULT_SETTINGS şemasının
    dışına taşmaz). `default_model` alan-bazlı merge edilir (tek bir provider'ı
    güncellemek diğerlerini silmez); bir provider'a boş string verilmesi o
    provider'ı "otomatiğe dön" anlamında sözlükten TAMAMEN kaldırır."""
    current = load_settings()
    for k, v in patch.items():
        if k not in DEFAULT_SETTINGS:
            continue
        if k == "default_model" and isinstance(v, dict):
            merged = dict(current.get("default_model") or {})
            for ck, cv in v.items():
                if cv:
                    merged[str(ck)] = str(cv)
                else:
                    merged.pop(str(ck), None)
            current["default_model"] = merged
        else:
            current[k] = v
    os.makedirs(CLAUDEOPS_DIR, exist_ok=True)
    tmp = SETTINGS_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_JSON)  # atomic — eşzamanlı okuyan yarım dosya görmez
    return current


def default_model_for(provider: "CliProvider") -> str:
    """Bir provider için etkin varsayılan model — `default_handover_effort`'un
    (handover.py) model karşılığı, AYNI önceliklendirme: Ayarlar'daki override
    VARSA ve hâlâ bu provider'ın `model_choices()` listesinde GEÇERLİYSE o
    kullanılır (liste zamanla değişebilir — ör. bir model emekliye ayrılırsa
    settings.json'daki eski değer sessizce STALE kalabilir, bu yüzden körü
    körüne güvenilmez); yoksa provider'ın kendi ilk seçeneğine düşülür.

    Sadece "hiç model yok" (yeni session / bilinmeyen fallback) durumunda
    çağrılmalı — var olan bir session'ın kendi modelini (session.model,
    info["model"], models.tsv kaydı, ...) KORUMAK istisnasız önceliklidir,
    bu fonksiyon o zincirin EN SONUNDAKİ halka."""
    choices = provider.model_choices()
    override = (load_settings().get("default_model") or {}).get(provider.name) or ""
    return override if override in choices else choices[0]
