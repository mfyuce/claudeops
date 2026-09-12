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
import shutil
from typing import Any, Dict, TYPE_CHECKING

from .atomic_json import atomic_write_json
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
    "provider_bin": {},      # {cli: mutlak binary yolu} — 2026-09-07, canlı yuhem vakası: claude
                              # PATH'te DEĞİL, bir projenin kendi node_modules/.bin'inde kurulu
                              # (npm global değil, proje-yerel). Paylaşımlı bir hesapta (ör. tek
                              # bir Linux kullanıcısını birden fazla kişi paylaşıyor) `claude`'u
                              # ~/.local/bin gibi PAYLAŞIMLI bir PATH konumuna symlink'lemek
                              # kullanıcının kendi credit'lerini/kimliğini o hesabı paylaşan
                              # HERKESE açardı — settings.json bu makineye ÖZEL kaldığı için
                              # (her host'un kendi ayrı dosyası, bkz. hosts.py/web_hosts.py'nin
                              # federasyon tasarımı) burası PATH değiştirmeden aynı sonucu verir,
                              # hiçbir shared konuma dokunmadan.
    "byok": {},              # {cli: {ENV_VAR: value}} — 2026-09-13, TODO.md'nin "BYOK" maddesi:
                              # bir provider'ın KENDİ bring-your-own-key mekanizmasına (ör. copilot'un
                              # COPILOT_PROVIDER_BASE_URL/_API_KEY/COPILOT_MODEL — `copilot help
                              # providers`, DeepSeek/Ollama/Azure gibi GitHub-dışı bir backend'e
                              # yönlendirir) enjekte edilecek ham env değişkenleri. Ayarlar sekmesinde
                              # BİLEREK bir UI alanı YOK (API-key bir SIR, bu dosyanın geri kalanı gibi
                              # düz tercih değil — maskeleme/izin tasarımı ayrı bir karar) — bugün için
                              # sadece dosyanın kendisini elle düzenleyerek ya da save_settings()'in
                              # (herhangi bir DEFAULT_SETTINGS anahtarını genel kabul eden) mevcut
                              # `/api/settings` yoluyla set edilir. Boş (varsayılan) = provider kendi
                              # normal routing'ine/login'ine göre spawn olur, hiçbir şey enjekte edilmez.
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
            if not isinstance(out.get("provider_bin"), dict):
                out["provider_bin"] = {}
            if not isinstance(out.get("byok"), dict):
                out["byok"] = {}
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
        if k in ("default_model", "provider_bin") and isinstance(v, dict):
            merged = dict(current.get(k) or {})
            for ck, cv in v.items():
                if cv:
                    merged[str(ck)] = str(cv)
                else:
                    merged.pop(str(ck), None)
            current[k] = merged
        else:
            current[k] = v
    atomic_write_json(SETTINGS_JSON, current)
    return current


def resolved_binary(cli_name: str) -> str:
    """Bir provider'ın çalıştırılabilir yolu — sırayla: Ayarlar'daki elle-girilmiş
    override (`provider_bin[cli_name]`, PATH'e HİÇ dokunmadan tam yol) → `shutil.which`
    (normal PATH araması) → bare isim (eski davranış, `spawn_session`'ın kendisi
    zaten `Popen`'ı PATH üzerinden çözecek). Her provider'ın kendi `shutil.which(NAME)
    or NAME` satırının yerine geçer — DRY + üçünde de aynı override mantığı."""
    override = (load_settings().get("provider_bin") or {}).get(cli_name, "").strip()
    if override:
        return override
    return shutil.which(cli_name) or cli_name


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


def byok_env_for(cli_name: str) -> Dict[str, str]:
    """`settings.json`'ın `byok[cli_name]` alanı — bkz. DEFAULT_SETTINGS'teki
    `byok` yorumu. Provider'ların `env_overrides()`'ı bunu kendi COPS_NAME'ine
    EK olarak döndürür (`spawn.py` ikisini de aynı şekilde, sırayla `env
    KEY=VAL ...` olarak komut satırına gömer — bkz. o dosyanın yorumu, tek bir
    anahtara özel bir varsayım YOK).

    Bozuk/eksik veri asla fırlatmaz: `cli_name` altında ne varsa (dict değilse
    dahi) `{}`'e düşer, iç değerler `str()`'e zorlanır (settings.json elle
    düzenlenebiliyor — bir sayı/bool/liste yazılmışsa `env KEY=VAL` gömme adımı
    yine de bir `str` bekler).

    `save_settings()`'in `default_model`/`provider_bin` için yaptığı ALAN-BAZLI
    merge BURADA YOK (`byok`'un şekli `{cli: {env: val}}` — o ikisinin düz
    `{cli: str}`'inden farklı, aynı merge mantığı doğrudan uygulanamaz) — bugün
    hiçbir yazıcı (Ayarlar UI'ı, `/api/settings`) bu alana yazmadığı için pratik
    bir fark yaratmıyor; ileride bir yazıcı eklenirse ya kendi merge'ini yapmalı
    ya da her seferinde TÜM `byok` dict'ini göndermeli."""
    raw = (load_settings().get("byok") or {}).get(cli_name)
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v}
