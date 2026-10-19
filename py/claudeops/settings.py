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
import re
import shutil
import urllib.parse
from typing import Any, Dict, Tuple, TYPE_CHECKING

from .atomic_json import atomic_write_json
from .paths import CLAUDEOPS_DIR

if TYPE_CHECKING:
    from .providers.base import CliProvider

SETTINGS_JSON = os.path.join(CLAUDEOPS_DIR, "settings.json")

DEFAULT_SETTINGS: Dict[str, Any] = {
    "theme": "system",       # "system" | "light" | "dark"
    "handover_effort": "",   # "" = otomatik (default_handover_effort'un high-tercih mantığı)
    "handover_cache_aware": True,  # TBD#87 (2026-10-16): handover'ın model/effort DÜŞÜRMESİ istem
                              # önbelleğinin durumuna bakar: sıcaksa (son istek < ~55 dk) oturumun
                              # modeli bırakılır, soğuksa Sonnet'e düşülür; effort her zaman high
                              # (önbelleği bozan modellerde yalnız soğukken). 338 gerçek devir turunda
                              # ölçüldü: sıcakken `/model` bağlamın tamamını yeniden yazdırıyor. False
                              # = eski davranış (önbelleğe bakmadan hep düşür), KAÇIŞ KAPAĞI.
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
    "ucli_limits": {},       # {max_steps, max_context_kib, max_tool_calls, max_output_tokens,
                              # request_timeout_secs, reasoning_effort: str} (6. alan reasoning_effort 2026-10-17'de,
                              # SAYI DEĞİL: boş = oturumun effort'u aynı adla `--effort` olarak da geçer, `off` = hiç
                              # geçirme (bugüne dek ki davranış), low/medium/high/max = hepsine o seviye; model
                              # alanı kabul etmiyorsa yine geçmez, bkz. `ucli_reasoning_mode()`) (4. alan max_output_tokens 2026-09-28'de, 5. alan
                              # request_timeout_secs 2026-10-17'de eklendi; sonuncu effort preset'inde YOK,
                              # ayrı varsayılanı var: `providers/ucli_provider.py::_REQUEST_TIMEOUT_SECS`) — 2026-09-24,
                              # TODO.md'nin ucli effort maddesi: bu sayılar `providers/ucli_provider.py`
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
                              # 7. alan `stream` (2026-10-18, SAYI DEĞİL): ucli'ye `--stream` geçsin mi (yanıt akışlı
                              # istenir: durum dosyasında `thinking`/`writing` aşamaları görünür, metin pane'e canlı
                              # basılır; bedeli: cevap pane'de iki kez görünür, akış yarıda kesilirse çağrı yeniden
                              # DENENMEZ). `on` aç, `off` kapat, boş = `UCLI_STREAM_DEFAULT` (AÇIK). Okuma: `ucli_stream_enabled()`.
    "ucli_web": {},          # {search_url, search_flavor, search_docker, allow_fetch_domains: str} — 2026-10-16
                              # (TODO.md "ucli web özellikleri"): unified-cli be4448a'nın web araçları
                              # (`web_search`, gerçek sayfada çalışan `fetch_url`) ucli'de varsayılan KAPALI.
                              # ARAMA claudeops tarafında varsayılan AÇIK (kullanıcı kararı, aynı gün: "ucli
                              # web search yapacaksa docker da oto olsun şimdilik"): `search_url` boşken yeni
                              # açılan ucli oturumları claudeops'un KENDİ yönettiği yerel SearXNG kapsayıcısını
                              # (`searxng.py`: loopback, kendiliğinden kurulur/başlar) `--search-url` olarak alır.
                              # GEÇİCİ (TOBEDECIDED.md TBD#88): ucli aramayı kendi içine alınca bu otomatik kalkar.
                              # `search_docker` = "off" (ya da 0/false/no/hayır) bunu KAPATIR; `search_url`
                              # (SearXNG, ör. http://127.0.0.1:8888/search) dolu ise o kazanır ve docker'a
                              # dokunulmaz; geçersiz bir `search_url` arama'yı KAPALI bırakır (başka yere
                              # sessizce yönlendirmez). `search_flavor` yalnız "searxng" (brave şimdilik
                              # DESTEKLENMEZ: anahtarı argv'ye koymadan iletmek ayrı iş, `ucli_provider.py`nin
                              # API-anahtarı dosya+`sh -c` deseni gerekir). `allow_fetch_domains` (virgül/
                              # boşlukla ayrılmış TAM host adları, joker yok; ucli'nin kendi kuralı) dolu ise
                              # `--allow-fetch --allow-fetch-domain ...`; fetch_url HÂLÂ varsayılan kapalı.
                              # `provider_bin`/`ucli_limits`'le AYNI alan-bazlı merge ("boş=kaldır" = varsayılana
                              # dön). Okuma tarafı: `ucli_web_config()`.
    "ucli_script": {},       # {mode: "off"|"read"|"full"} — 2026-10-17 (unified-cli 119c8e5, `chat --allow-script[=read|full]`):
                              # model tek bir kısa Lua programı yazar, ucli bunu SÜREÇ İÇİNDE çalıştırıp araçları
                              # çağırır. VARSAYILAN KAPALI (boş/eksik/`off`): token kazancı henüz gösterilemedi
                              # (unified-cli TODO.md). `read` = yalnız salt-okuma araçlar; `full` = oturumun modele
                              # zaten verdiği her şey (yazma `--allow-edit/--allow-create` ile, fetch, web_search,
                              # MCP), kapılar aynı. YALNIZ ikili `--allow-script`'i tanıyorsa geçer. Tek alanlı sözlük:
                              # `ucli_web`/`ucli_limits`'le aynı alan-bazlı merge ("boş=kaldır" = kapalı). Okuma tarafı:
                              # `ucli_script_mode()`.
    "ucli_usage_warn": {},   # {amber, red: str} — 2026-10-17: ucli token rozetinin renk eşikleri, OTURUM başına
                              # Evren KOTA EŞDEĞERİ token (`ucli_client.quota_equivalent_tokens`: önbellekli girdi
                              # %3 sayılır, panonun ham toplamı DEĞİL), süreç başından beri. Boş/eksik = varsayılan
                              # (amber 1M, kırmızı 3M: Evren günlük hesap kotası 15M, bir oturum tek başına bunun
                              # %7'sini aşarsa amber); `off` (ya da 0/false/no) = o kademe KAPALI. YALNIZ renk/uyarı:
                              # otomatik durdurma YOK. `ucli_limits`le AYNI alan-bazlı merge. Okuma tarafı:
                              # `ucli_usage_warn_thresholds()`.
    "tunnel_watch": "on",    # "on" | "off" — tünel SAĞLIK BEKÇİSİ (2026-10-17, kullanıcı: "settingslerde seçimlik
                              # olsun"; `data/run-tunnel.sh::_watch_tunnel`): quick tunnel kopunca cloudflared
                              # yeni tünel İSTEMİYOR, süreç canlı kalıp genel adres HTTP 530 veriyor ve systemd
                              # yalnız süreç ÖLÜNCE yeniden başlatıyor; bekçi art arda 3 yoklama (~3 dk) HTTP 530
                              # görürse cloudflared'ı sonlandırır, systemd yeni tüneli açar (URL DEĞİŞİR, ntfy
                              # gider). Varsayılan AÇIK. Betik bu dosyayı HER yoklamada okur: Ayarlar > Genel'deki
                              # değişiklik tüneli yeniden başlatmadan geçerli olur. `off`/0/false/no... kapatır
                              # (`_OFF_WORDS`, betikteki küme ile AYNI). Okuma tarafı: `tunnel_watch_enabled()`.
    "default_effort": {},    # {cli: effort} — `default_model`in effort karşılığı (2026-10-19, TBD#90/#91): yeni
                              # oturum formunun ön-dolu değeri VE formsuz yolların (devral, diag) fallback'i.
                              # Kayıt yoksa `provider.default_effort()` (claude: medium; diğerleri: en yüksek
                              # seviye = eski davranış). Listede olmayan değer yok sayılır (bkz. `default_effort_for`).
    "routing_guidance": "on",  # "on" | "off" — yeni açılan oturumlara işe-göre-model/effort yönergesi
                              # (2026-10-19, TBD#91). Claude: her açılışta `--append-system-prompt-file`;
                              # codex: `~/.codex/AGENTS.md`ye işaretli blok (`py/cops routing sync`). AÇIK
                              # oturumlar yönergeyi ancak yeniden açılınca alır. Okuma tarafı: `routing_guidance_enabled()`.
    "routing_guidance_text": "",  # "" = paketlenmiş `data/routing.md`; doluysa o metin kullanılır (Ayarlar'da düzenlenir).
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
            if not isinstance(out.get("default_effort"), dict):
                out["default_effort"] = {}
            if not isinstance(out.get("provider_bin"), dict):
                out["provider_bin"] = {}
            if not isinstance(out.get("byok"), dict):
                out["byok"] = {}
            if not isinstance(out.get("ucli_limits"), dict):
                out["ucli_limits"] = {}
            if not isinstance(out.get("ucli_web"), dict):
                out["ucli_web"] = {}
            if not isinstance(out.get("ucli_script"), dict):
                out["ucli_script"] = {}
            if not isinstance(out.get("ucli_usage_warn"), dict):
                out["ucli_usage_warn"] = {}
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
        if k in ("default_model", "default_effort", "provider_bin", "ucli_limits", "ucli_web", "ucli_script", "ucli_usage_warn", "cli_managed") and isinstance(v, dict):
            merged = dict(current.get(k) or {})
            for ck, cv in v.items():
                if isinstance(cv, (list, tuple)):   # ör. allow_fetch_domains: ["a.org", "b.org"]
                    cv = ",".join(str(x) for x in cv if str(x).strip())
                elif isinstance(cv, bool):          # ör. search_docker: false. `False` "boş = kaldır"a (= varsayılan AÇIK) düşmesin
                    cv = "on" if cv else "off"
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
    bu fonksiyon o zincirin EN SONUNDAKİ halka. Bir restart/respawn'da
    STORED bir değer VARKEN de provider'a-özel tazeleme için bkz.
    `resolved_model_for`."""
    choices = provider.model_choices()
    override = (load_settings().get("default_model") or {}).get(provider.name) or ""
    if override in choices:
        return override
    # Ayarlarda kayıt yoksa provider'ın tercihi (claude: en yeni Sonnet); o da yoksa listenin ilki.
    # Eskiden doğrudan `choices[0]` idi: claude'un sıralı listesinde bu ALFABETİK ilk = `claude-fable-5-1`
    # (yeni oturumlar en pahalı kademede açılıyordu, 2026-10-19'da fark edildi).
    preferred = provider.preferred_default_model()
    # Seçeneği olmayan provider (ör. uzak host'ta modeli listelenemeyen CLI) boş döner: `choices[0]` /api/status'u 500'lerdi.
    return preferred if preferred in choices else (choices[0] if choices else "")


def default_effort_for(provider: "CliProvider") -> str:
    """Bir provider için etkin varsayılan effort — `default_model_for`un effort karşılığı: Ayarlar'daki
    `default_effort[cli]` VARSA ve provider'ın seviye listesinde geçerliyse o, yoksa `provider.default_effort()`.
    Yalnız "effort verilmedi" durumunda çağrılmalı: var olan bir oturumun kendi effort'unu KORUMAK önceliklidir."""
    levels = provider.effort_levels()
    override = (load_settings().get("default_effort") or {}).get(provider.name) or ""
    return override if override in levels else provider.default_effort()


def resolved_model_for(provider: "CliProvider", stored: str) -> str:
    """Restart/respawn yollarının (`rc.py`, `web.py::_start`/`_new_chat`/`_adopt`)
    `stored` (models.tsv kaydı / önceki instance'ın `model` alanı / canlı
    proc'un argv'si) değerini çözmesi — `default_model_for`'un "var olanı
    istisnasız koru" politikasına, provider'ın kendi `refresh_stored_model()`
    kuralı kadar istisna. TODO.md 2026-10-08, kullanıcı: "restartlar da sonet
    5.5 gelmiyor, en son sonet default olmali": `models.tsv`'nin yazıcısı yok,
    bir kere yazılan sonnet id'si sonsuza dek donuk kalıyordu (4 call site'ta
    AYNI kopya desen).

    `stored` boşsa hiç kayıt yok demektir: davranış `default_model_for` ile
    BİREBİR aynı. Doluysa karar provider'a bırakılır — varsayılan no-op, sadece
    claude sonnet pinlerini tazeliyor. Bu yüzden genel varsayılan override'ı
    (bu makinede fable) tazeleme yoluna HİÇ karışmaz."""
    if not stored:
        return default_model_for(provider)
    return provider.refresh_stored_model(stored)


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
    kendi varsayılanında kalır (`request_timeout_secs`te preset yok, provider'ın
    kendi sabiti)."""
    raw = load_settings().get("ucli_limits") or {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, int] = {}
    for key in ("max_steps", "max_context_kib", "max_tool_calls", "max_output_tokens", "request_timeout_secs"):
        try:
            n = int(str(raw.get(key)).strip())
        except (TypeError, ValueError):
            continue
        if n > 0:
            out[key] = n
    return out


USAGE_WARN_DEFAULTS = {"amber": 1_000_000, "red": 3_000_000}


def ucli_usage_warn_thresholds() -> Tuple[int, int]:
    """(amber, kırmızı) kota-eşdeğeri token eşikleri (bkz. `ucli_usage_warn` yorumu). 0 = o kademe kapalı. Pozitif
    tam sayı = eşik, `off` sözcükleri ya da "0" = kapalı, boş/eksik/geçersiz = varsayılan. Asla fırlatmaz."""
    raw = load_settings().get("ucli_usage_warn") or {}
    if not isinstance(raw, dict):
        raw = {}
    out = []
    for key in ("amber", "red"):
        text = str(raw.get(key) if raw.get(key) is not None else "").strip().lower().replace("_", "").replace(",", "")
        if text in _OFF_WORDS:
            out.append(0)
            continue
        try:
            n = int(text)
        except ValueError:
            n = 0
        out.append(n if n > 0 else USAGE_WARN_DEFAULTS[key])
    return out[0], out[1]


def routing_guidance_enabled() -> bool:
    """`routing_guidance` (bkz. DEFAULT_SETTINGS) açık mı: `tunnel_watch_enabled` ile AYNI kural (varsayılan AÇIK,
    `_OFF_WORDS` kapatır). Asla fırlatmaz."""
    value = load_settings().get("routing_guidance")
    return ("on" if value is None else str(value)).strip().lower() not in _OFF_WORDS


def tunnel_watch_enabled() -> bool:
    """`tunnel_watch` (bkz. DEFAULT_SETTINGS) açık mı: varsayılan AÇIK, `_OFF_WORDS` kapatır, boş/tanınmayan değer açık sayılır.
    `data/run-tunnel.sh` AYNI kuralı kendi okur (bash); bu işlev Python tarafının tek tanımıdır. Asla fırlatmaz."""
    value = load_settings().get("tunnel_watch")
    return ("on" if value is None else str(value)).strip().lower() not in _OFF_WORDS


_REASONING_LEVELS = ("low", "medium", "high", "max")


def ucli_reasoning_mode() -> str:
    """`ucli_limits.reasoning_effort` (2026-10-17): ucli'ye `--effort` geçirme kipi. "auto" (boş/eksik/geçersiz:
    oturumun effort ön ayarı, medium/high, aynı adla geçer), "off" (hiç geçirme = bugüne dek ki davranış; kalite
    sorunu çıkarsa tek ayarla geri dönüş) ya da low/medium/high/max (tüm oturumlara o seviye). Model desteği
    ayrıca ve her kipte `providers/ucli_provider.py`de denetlenir. Asla fırlatmaz (settings.json elle düzenlenebiliyor)."""
    raw = load_settings().get("ucli_limits") or {}
    if not isinstance(raw, dict):
        return "auto"
    value = str(raw.get("reasoning_effort") or "").strip().lower()
    if value in _OFF_WORDS:
        return "off"
    return value if value in _REASONING_LEVELS else "auto"


_ON_WORDS = frozenset({"on", "1", "true", "yes", "y", "evet", "acik", "açık", "enabled"})
# `--stream`in varsayılanı (2026-10-18, karar kullanıcıdan bana devredildi): AÇIK. Gerekçe ve ölçüm: TODO.md 2026-10-18 (3)
# (7/7 Evren modeli düz ve araç çağrılı akışı doğru tamamladı, usage sayacı bozulmadı, gerçek Wi-Fi dalgalanmasında akış
# kırılmadı; bedel: cevap terminalde iki kez görünür, akış yarıda kesilirse çağrı yeniden denenmez). Geri dönüş:
# Ayarlar > model > "yanıt akışı" ya da `ucli_limits.stream=off`; yalnız YENİ oturumlara uygulanır.
UCLI_STREAM_DEFAULT = True


def ucli_stream_enabled() -> bool:
    """`ucli_limits.stream` (2026-10-18): ucli'ye `--stream` geçirilsin mi. `_ON_WORDS` açar, `_OFF_WORDS` kapatır,
    boş/eksik/tanınmayan değer `UCLI_STREAM_DEFAULT`. İkilinin bayrağı tanıması ayrıca ve her durumda
    `providers/ucli_provider.py`de denetlenir. Asla fırlatmaz (settings.json elle düzenlenebiliyor)."""
    raw = load_settings().get("ucli_limits") or {}
    if not isinstance(raw, dict):
        return UCLI_STREAM_DEFAULT
    value = str(raw.get("stream") or "").strip().lower()
    if value in _OFF_WORDS:
        return False
    if value in _ON_WORDS:
        return True
    return UCLI_STREAM_DEFAULT


# Tam host adı: etiketler [a-z0-9-], tire uçta olmaz, toplam <= 253. Joker (`*.org`),
# şema (`https://`), yol, port ve boşluk YOK: ucli `--allow-fetch-domain`i "tam host
# adı eşleşmesi, büyük/küçük harf duyarsız, joker yok" diye tanımlıyor.
_HOST_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")
_MAX_FETCH_DOMAINS = 64


def _valid_http_url(url: str) -> bool:
    """http(s) şeması + host adı olan, boşluk/denetim karakteri içermeyen bir adres.
    (Kimlik bilgisi ya da sorgu parçaları engellenmez: operatör kendi arka ucunu yazıyor.)"""
    if not url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port   # geçersiz port burada ValueError fırlatır
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


_OFF_WORDS = frozenset({"off", "0", "false", "no", "n", "hayir", "hayır", "kapali", "kapalı", "disabled", "none"})


def ucli_script_mode() -> str:
    """`settings.json`'ın `ucli_script.mode` alanı — bkz. DEFAULT_SETTINGS'teki yorum. `"read"` ya da `"full"`;
    boş/eksik/`off`/tanınmayan/bozuk her şey `""` (KAPALI). Asla fırlatmaz (settings.json elle düzenlenebiliyor)."""
    raw = load_settings().get("ucli_script")
    if not isinstance(raw, dict):
        return ""
    mode = str(raw.get("mode") or "").strip().lower()
    return mode if mode in ("read", "full") else ""


def ucli_web_config() -> Dict[str, Any]:
    """`settings.json`'ın `ucli_web` alanı — bkz. DEFAULT_SETTINGS'teki yorum. Yalnız
    GEÇERLİ parçaları içeren bir dict döner. Anahtarlar: `search_url` + `search_flavor`
    ("searxng"; ikisi birlikte ya da hiç) YA DA `search_docker: True` (arama adresi boşken ve
    otomatik kapatılmamışken: claudeops'un yönettiği yerel SearXNG, bkz. `searxng.py`; VARSAYILAN),
    `allow_fetch_domains` (tekrarsız, küçük harfli, geçerli host adları listesi).
    Geçersiz/eksik bir parça sessizce ATLANIR ve o yetenek KAPALI kalır (asla fırlatmaz,
    `ucli_limit_overrides`la aynı tolerans; settings.json elle düzenlenebiliyor): bozuk
    bir adres web'i yanlış yere AÇMAZ, kapalı bırakır; dolu ama geçersiz `search_url` otomatik
    docker'a da DÜŞMEZ (operatör belirli bir arka uç istemişti)."""
    raw = load_settings().get("ucli_web") or {}
    if not isinstance(raw, dict):
        raw = {}
    out: Dict[str, Any] = {}
    url = str(raw.get("search_url") or "").strip()
    flavor = str(raw.get("search_flavor") or "").strip().lower() or "searxng"
    if url and flavor == "searxng" and _valid_http_url(url):
        out["search_url"] = url
        out["search_flavor"] = "searxng"
    elif not url:
        mode = raw.get("search_docker")
        if str("" if mode is None else mode).strip().lower() not in _OFF_WORDS:
            out["search_docker"] = True
    doms = raw.get("allow_fetch_domains")
    text = ",".join(str(x) for x in doms) if isinstance(doms, (list, tuple)) else str(doms or "")
    domains: list = []
    for tok in re.split(r"[,\s]+", text.lower()):
        if tok and _HOST_RE.match(tok) and tok not in domains:
            domains.append(tok)
            if len(domains) >= _MAX_FETCH_DOMAINS:
                break
    if domains:
        out["allow_fetch_domains"] = domains
    return out
