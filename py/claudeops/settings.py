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
    "history_warn_at": 1900, # tmux scrollback (`tmux_backend.HISTORY_LIMIT`=2000) bu sayıya
                              # yaklaşınca Terminal görünümünün sayaç rengi + ana tablonun
                              # "dikkat gerekenleri seç" butonu bunu eşik alır (2026-09-15,
                              # kullanıcı: "1900-2000 (settingden) olanları... seç butonu") —
                              # HISTORY_LIMIT'in kendisi (2000) sabit kalır, o tmux'un GERÇEK
                              # yapılandırması (bkz. tmux.conf); burada kullanıcı-tercihi olan
                              # SADECE "ne kadar erken uyarılmak istiyorum" eşiği.
    "fleet_sort": "name",    # "name" | "cwd" — Running/Registered/Disabled/Retired tablolarındaki
                              # grupların birincil sıralama anahtarı (2026-09-23, iki ayrı canlı
                              # şikayet sonrası eklendi: önce case-sensitivity bug'ı — bkz. web.py
                              # _status_payload — sonra kullanıcı ekranda gördüğü KISA İSMİN
                              # alfabetik olmasını istediğini netleştirdi; cwd bazen isimle hiç
                              # örtüşmüyor, ör. "urartian" klasörü "U_urartian_corpus_nlp"). 21
                              # Eylül'ün "ana sıralama cwd'ye göre" kararı (TODO.md #1) tersine
                              # ÇEVRİLMEDİ, konfigüre edilebilir yapıldı — varsayılan "name",
                              # "cwd" isteyen (aynı klasördeki session'ları yan yana tutmak
                              # isteyenler için) Ayarlar > Genel'den seçer.
    "layout_grid": 4,        # `py/cops layout`/web "Yerleşim" sekmesi: desktop başına pencere
                              # sayısı (2026-09-15, kullanıcı: "settings de alani 4 e 8 e 2 ye
                              # bol gibi ayar da olmali") — `layout.py`'nin `_GRID_LAYOUTS`'una
                              # göre (cols,rows)'a çevrilir (2→2x1, 4→2x2, 8→4x2); tanınmayan bir
                              # değer sessizce 4'e (2x2) düşer.
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
                              # yönlendirir; ucli'nin UCLI_API_KEY'i) enjekte edilecek ham env
                              # değişkenleri. 2026-09-24: Ayarlar > model sekmesinde masked
                              # (type=password) bir alan var (SettingsTab.tsx) — dosya artık
                              # world-readable DEĞİL (mode=0o600, aynı gün fix edildi) ve
                              # save_settings() bu alan için ayrı bir iç-içe merge yapıyor (bkz.
                              # o fonksiyonun içindeki "byok" dalı). Boş (varsayılan) = provider
                              # kendi normal routing'ine/login'ine göre spawn olur, hiçbir şey
                              # enjekte edilmez. copilot'un env_overrides()'ı bunu KOMUT SATIRINA
                              # gömüyor (`ps aux`'a açık, çok-kullanıcılı makinede risk) — ucli
                              # KASITLI OLARAK bunu kullanmıyor, bkz. providers/ucli_provider.py'nin
                              # dosya+`sh -c` dolaylaması.
    "cli_managed": {},       # {cli: "1"} — 2026-09-25, cli_install.py: bu CLI'yi claudeops'un
                              # kendisi mi kurdu (npm --prefix ile kendi bin/'ine) yoksa kullanıcı
                              # zaten kendi başına mı kurmuştu. `provider_bin`'le AYNI alan-bazlı
                              # merge/"boş=kaldır" dili ama farklı anlam: SADECE bu true olan bir
                              # CLI için tekrar kurulum/update denemesi güvenli — claudeops kendi
                              # kurmadığı bir binary'nin üzerine ASLA yazmaz (cli_install.py'nin
                              # kendi install_cli() reddi buna dayanır).
    "ucli_limits": {},       # {max_steps, max_context_kib, max_tool_calls: str} — 2026-09-24,
                              # TODO.md'nin ucli effort maddesi: bu 3 sayı `providers/ucli_provider.py`
                              # içindeki `_EFFORT_LIMITS`'te (medium/high preset'leri) gömülüydü,
                              # kullanıcı her ayar isteğinde bana bir sayı söylüyor, ben Python'da
                              # elle değiştirip servisi restart ediyordum. Burada TEK, flat bir
                              # override seti — `provider_bin` gibi cli-bazlı {cli: ...} DEĞİL,
                              # çünkü bu numerik "effort" kavramı bugün SADECE ucli'de var, bir
                              # {cli: {...}} haritası şimdiden erken bir genelleme olurdu. Dolu olan
                              # her alan, SEÇİLİ effort seviyesi (medium/high) ne olursa olsun o
                              # preset'in karşılık gelen sayısının YERİNE geçer; boş/eksik alan
                              # preset'in kendi varsayılanında kalır ("boş=otomatiğe dön",
                              # provider_bin/byok'la AYNI dil). Okuma tarafı: `ucli_limit_overrides()`.
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
            if not isinstance(out.get("ucli_limits"), dict):
                out["ucli_limits"] = {}
            if not isinstance(out.get("cli_managed"), dict):
                out["cli_managed"] = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return out


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    """`patch`'i mevcut ayarların ÜSTÜNE merge edip diske yaz, YENİ TAM ayarları
    döndür. Bilinmeyen anahtarlar sessizce atlanır (DEFAULT_SETTINGS şemasının
    dışına taşmaz). `default_model`/`provider_bin`/`ucli_limits` alan-bazlı
    merge edilir (tek bir anahtarı güncellemek diğerlerini silmez); boş string
    verilmesi o anahtarı "otomatiğe dön" anlamında sözlükten TAMAMEN kaldırır
    (`default_model`/`provider_bin`'de anahtar=cli adı, `ucli_limits`'te
    anahtar=alan adı — mekanik aynı, ne temsil ettiği farklı)."""
    current = load_settings()
    for k, v in patch.items():
        if k not in DEFAULT_SETTINGS:
            continue
        if k in ("default_model", "provider_bin", "ucli_limits", "cli_managed") and isinstance(v, dict):
            merged = dict(current.get(k) or {})
            for ck, cv in v.items():
                if cv:
                    merged[str(ck)] = str(cv)
                else:
                    merged.pop(str(ck), None)
            current[k] = merged
        elif k == "byok" and isinstance(v, dict):
            # {cli: {ENV_VAR: value}} — bir seviye daha derin merge, YUKARIDAKİ
            # düz {cli: value} deseninden farklı (byok_env_for()'un docstring'i
            # bu boşluğu zaten işaret ediyordu: çağıran ya TÜM byok'u göndermeli
            # ya da provider-bazlı merge'i kendisi yapmalıydı — artık burada).
            # Bir provider'a boş string verilen bir ENV_VAR o provider'ın
            # sözlüğünden kaldırılır; sözlük boşalırsa provider'ın kendisi de
            # kaldırılır (default_model/provider_bin'in "boş=otomatiğe dön"
            # semantiğiyle aynı).
            merged_byok = {ck: dict(cv) for ck, cv in (current.get("byok") or {}).items()}
            for cli_name, envs in v.items():
                if not isinstance(envs, dict):
                    continue
                target = dict(merged_byok.get(cli_name) or {})
                for env_name, env_val in envs.items():
                    if env_val:
                        target[str(env_name)] = str(env_val)
                    else:
                        target.pop(str(env_name), None)
                if target:
                    merged_byok[str(cli_name)] = target
                else:
                    merged_byok.pop(str(cli_name), None)
            current["byok"] = merged_byok
        else:
            current[k] = v
    # mode=0o600: `byok` sırlar taşıyabiliyor (2026-09-24'e kadar bu satır
    # mode=None'dı — settings.json 664/world-readable kalmıştı, çok-kullanıcılı
    # bu makinede gerçek bir açık; sonraki YAZIMDA `os.replace` hedefi kaynağın
    # izniyle değiştirdiği için elle chmod GEREKMEDİ, tek satır yeterli).
    atomic_write_json(SETTINGS_JSON, current, mode=0o600)
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

    `save_settings()` artık `byok` için de alan-bazlı merge yapıyor (2026-09-24,
    `default_model`/`provider_bin`'in düz `{cli: str}`'inden FARKLI, bir seviye
    daha derin `{cli: {env: val}}` merge'i — Ayarlar UI'ının bir provider'ın TEK
    bir ENV_VAR'ını, diğerlerine/diğer provider'lara dokunmadan güncelleyebilmesi
    için) — bu fonksiyon SADECE okuma tarafı, o merge'den bağımsız."""
    raw = (load_settings().get("byok") or {}).get(cli_name)
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v}


def ucli_limit_overrides() -> Dict[str, int]:
    """`settings.json`'ın `ucli_limits` alanı — bkz. DEFAULT_SETTINGS'teki yorum.
    `providers/ucli_provider.py`'nin `_EFFORT_LIMITS[effort]`'inin (medium/high
    preset'i) ÜSTÜNE merge edilecek, SADECE geçerli (pozitif tam sayıya
    çevrilebilen) alanları içeren bir dict döner. Eksik/boş/negatif/sayısal-
    olmayan bir değer sessizce ATLANIR (asla fırlatmaz, `byok_env_for` ile aynı
    tolerans — settings.json elle düzenlenebiliyor); atlanan alan preset'in
    kendi varsayılanında kalır."""
    raw = load_settings().get("ucli_limits") or {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, int] = {}
    for key in ("max_steps", "max_context_kib", "max_tool_calls"):
        try:
            n = int(str(raw.get(key)).strip())
        except (TypeError, ValueError):
            continue
        if n > 0:
            out[key] = n
    return out
