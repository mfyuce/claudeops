"""ucli (unified-cli) — tmux-backed `CliProvider` (TOBEDECIDED#44(b)'nin
"hâlâ açık" kısmı). `ucli chat --repl` hiçbir TTY-özel davranışa ihtiyaç
duymuyor (ucli_client.py'nin modül docstring'inde zaten doğrulanmıştı) —
bu yüzden `ShellProvider`'ın (düz bash) yaptığı gibi pane'e `ucli`'yi
DOĞRUDAN koyup mevcut generic spawn/discovery/capture-pane makinesini
olduğu gibi ödünç alıyoruz: fleet'te normal bir session gibi görünür,
Running/Registered'da satırı olur.

`--pretty` (2026-09-24, unified-cli'ye YENİ eklendi) argv'ye eklendi —
terminal-popup'ın ham "Terminal" sekmesi artık ham JSON DEĞİL, markdown-
render edilmiş cevap gösteriyor (ANSI sadece gerçek TTY'de, tmux pane'i
öyle olduğu için sorunsuz; `--session`/`--repl`'in KENDİSİ hâlâ düz metin
saklıyor, `.jsonl` formatı/full_history/last_exchange etkilenmedi — sadece
CANLI görünüm). Varsayılan sekme diğer TÜM provider'larla AYNI, "Terminal"
(`TerminalModal.tsx`, ucli'ye özel bir dal YOK) — "Sohbet" (`ChatView.tsx`,
`full_history` okur) DENENDİ ama .jsonl'ı sadece TUR BİTİNCE okuduğu için
`UnifiedCLI tool: X` canlı ilerleme satırları orada hiç görünmüyordu
(kullanıcı: "akış canlı değil sanki", 2026-09-24) — geri alındı. Sohbet
sekmesi hâlâ var, geçmişi tool-call-log'suz gözden geçirmek için kullanışlı,
sadece varsayılan DEĞİL.

Bu, `io_providers/ucli_provider.py`'nin tmux'suz `IoProvider`'ından
TAMAMEN AYRI bir yol — ikisi de bilerek var (2026-09-24, kullanıcı: eski
CLI'lar tmux'lu kalsın + ucli de "aynı muamele"yi görsün): biri
Diagnostics'ten hızlı/tek-seferlik soru (proje+session seçip sor, tmux
hiç açılmaz), biri fleet'in normal bir üyesi (bu dosya). İkisi de AYNI
`.ucli/chat/*.jsonl` dosyalarını okur/yazar (`ucli_client.chat_session_dir`/
`read_chat_history` — ortak yardımcılar), sadece süreç yönetimi farklı.

model: `RegisterForm.tsx`'in model `<select>`'i serbest metin KABUL ETMİYOR
(kontrol edildi, TBD#44(b)'nin açık kalan sorusuydu) — dropdown kalıyor, ama
İÇİNDEKİ liste artık hardcoded DEĞİL: EVREN'in kendi `GET /v1/models`'ı
canlı çekiliyor (`_fetch_live_models`, 2026-09-24 — kullanıcı EVREN'in API
dokümantasyonunu paylaşınca fark edildi: sabit "tek doğrulanmış model" bile
GÜVENİLMEZMİŞ, aynı gün EVREN'in listesi `deepseek-v4-flash` değil
`deepseek-v4.1-flash` diyordu). Süreç ömrü boyunca BİR KEZ çekilip
cache'lenir (`/api/status`'un her ~birkaç saniyede bir çağırdığı
`model_choices()`'ı ağ isteğiyle YAVAŞLATMAMAK için — key yoksa/istek
başarısız olursa `_MODEL_CHOICES`'daki sabit yedeğe sessizce düşülür, asla
fırlatmaz). Bir anahtar SONRADAN Ayarlar'dan girilirse liste bir SONRAKİ
servis restart'ında tazelenir (canlı invalidation yok, bilinçli basitlik).

permission_mode: ucli'nin GERÇEK bir analogu var — `chat --allow-edit`
(varsayılan KAPALI: model sadece salt-okunur araçlara erişir; açılırsa
edit_file/write_file/delete_file/move_file de sunulur, bkz. unified-cli
TOBEDECIDED.md'nin "Yetki ve dağıtım" satırı). `_SENTINEL` YERİNE bu iki
değer (`read-only`/`allow-edit`) kullanılıyor (2026-09-24, kullanıcı
"permission mode yok mu, ayarlanamaz mı?" diye sorunca düzeltildi — ilk
taslak yanlışlıkla ShellProvider'ın "kavram yok" desenini kopyalamıştı).

effort: ilk başta unified-cli'de "ne kadar düşünsün" karşılığı yoktu — PRATİKTE
`--max-steps` + `--max-context-kib`'e bağlandı, bkz. `_EFFORT_LIMITS`'in yorumu
(2026-09-24, "8-round limit" ve ardından "context exceeds 256 KiB" hataları
canlı yaşandı, aynı gün unified-cli'de ikisi de gevşetildi). `--effort`
(low/medium/high/max, 2026-10-05'ten beri ucli'de) 2026-10-17'de bağlandı: seçili
ön ayar aynı adla geçer, modelin alanı kabul ettiği Evren `capabilities`ından
doğrulanırsa; bkz. `_effort_args`.

2026-10-17/18'de ucli'nin yeni yüzeyleri bağlandı (hepsi ikilinin bayrağı tanımasına kapılı, eski ikili 'unexpected
argument' ile spawn anında ölmesin diye): `allow-create` izin kipi (`--allow-create`, yalnız YENİ dosya), `ucli_script`
ayarı (`--allow-script=read|full`, gömülü Lua katmanı, varsayılan KAPALI; bkz. `_script_args`), `ucli_limits.stream`
(`--stream`, bkz. `_stream_args`) ve durum dosyasının `phase` alanı (`live_phase`: yanıt bekliyor / düşünüyor /
yazıyor / yeniden deneme; panelde `web._live_phase` rozeti).

Resume kimliği: ayrı bir UUID/sid kavramı yok — `sid` alanına doğrudan
`--session`'ın kendi değerini (=session adı) koyuyoruz, çünkü
`full_history`/`last_exchange`'in aldığı `sid` zaten `.ucli/chat/{sid}.jsonl`
dosya adı olarak kullanılabiliyor; `resolve_resume_id` bu yüzden hep None
döner (ShellProvider'daki "hep fresh" ile AYNI görünür ama nedeni farklı:
burada "resume" zaten `--session NAME`'in kendisi, ayrı bir id'ye gerek
yok — claude'un jsonl-sid'i gibi konuşmadan BAĞIMSIZ bir kimlik değil).

API key: EVREN `UCLI_API_KEY`'i Ayarlar > model sekmesindeki BYOK alanından
(`settings.byok_env_for("ucli")`, chmod 600 settings.json) geliyor — ama
`CopilotProvider.env_overrides()`'ın yaptığı gibi KOMUT SATIRINA gömülmüyor
(bu makine çok-kullanıcılı, `ps aux` argv'yi HERKESE gösterir). Bunun yerine
her `build_inner_command` çağrısında `_API_KEY_FILE`'a (chmod 600, `web.token`
ile AYNI desen) tazelenir, pane'in komutu `sh -c 'UCLI_API_KEY="$(cat ...)"
exec ucli ...'` ile SARILIR — anahtar sadece ucli process'inin ortamında
kalır, argv'de hiç görünmez (uçtan uca test edildi, 2026-09-24). Settings'te
değer yoksa dosyaya dokunulmaz (elle oluşturulmuş bir dosya varsa korunur).
"""
from __future__ import annotations
import json
import os
import shlex
import time
import urllib.error
import urllib.request
from typing import Any, Dict, FrozenSet, List, Optional, Sequence

import psutil

from .. import searxng
from ..diaglog import diag_log
from ..settings import (byok_env_for, ucli_limit_overrides, ucli_reasoning_mode, ucli_script_mode, ucli_stream_enabled,
                        ucli_web_config)
from ..ucli_client import binary_supports_flag, read_chat_history, read_status_file, resolve_binary
from .base import CliProvider

# effort: "ne kadar düşünsün" anlamında GERÇEK bir karşılığı yok (unified-cli
# TOBEDECIDED.md'sine bu boşluk ayrıca not edildi) — ama 2026-09-24'te
# kullanıcının "derin review yap" isteği ucli'nin `--max-steps` varsayılanında
# (8) `{"error":"Agent reached the 8-round limit..."}` ile yarım kaldı, sonra
# 60 denenince `(1..=32)` sert tavanına (o zamanki derleme-zamanı sabit)
# çarptı. 2026-09-24, AYNI GÜN unified-cli tarafında (henüz commit YOK, sadece
# yerel derlenmiş binary'de) İKİSİ DE değişti: `--max-steps`'in artık üst
# sınırı yok ("gerçek maliyet sınırı --max-steps değil --max-context-kib"),
# `--max-context-kib` (context KiB tavanı, varsayılan 256 — ucli'nin kendi
# --help'i "full-repo review için yükselt" diyor) yeni eklendi. Asıl kontrol
# artık İKİNCİSİ, ikisi birlikte effort'a bağlandı. [0]=varsayılan (diğer
# provider'ların ["low",...,"max"] listeleriyle aynı "ilk eleman=varsayılan").
#
# Üçüncü boyut, AYNI GÜN biraz sonra eklendi: `--max-tool-calls` (toplam
# tool-call bütçesi, varsayılan 64 — eski sabit değerin AYNISI). Tur-başına
# 16 tool-call tavanı bu bayraktan BAĞIMSIZ, hâlâ sabit (ucli'nin kendi
# --help'i: "A single model turn is separately capped at 16 calls regardless
# of this flag") — o yüzden burada YOK, sadece toplam bütçe ayarlanıyor.
#
# ⚠ Bu üç bayrak (`--max-steps` üst sınırsızlığı, `--max-context-kib`,
# `--max-tool-calls`) unified-cli'de HENÜZ COMMIT EDİLMEDİ — sadece o an
# derlenmiş `target/debug/ucli`'de var. Kaynak geri alınır/değişirse
# (`resolve_binary()` farklı bir build'e düşerse de aynı risk) claudeops'un
# ucli session'ları "unexpected argument" ile spawn anında patlar. Bilerek
# göze alındı (aktif, eşzamanlı geliştirilen iki proje) — commit'lenince bu
# not silinebilir.
# "high"in max_context_kib'i 2026-09-24'te 2048→16384'e yükseltildi:
# kullanıcı EVREN modellerinden birinin gerçek context'inin ~2.5M (muhtemelen
# token) olduğunu bildirdi — 2048 KiB bunun çok altında kalıyordu, bolca boşluk
# var. Yine de MODELE ÖZGÜ bir hesap DEĞİL (EVREN'in /v1/models'ı context-length
# hiç döndürmüyor, kontrol edildi) — düz, cömert bir sabit güvenlik tavanı,
# 2.5M token'a (kabaca 10 MB ham metin) hâlâ bilerek MESAFELİ.
#
# max_output_tokens (2026-09-28 eklendi) + "high"in max_steps'i 100→200:
# unified-cli'nin yeni --max-output-tokens'ı (agent.rs'in truncation-recovery
# fix'inden ÖNCE bu proje ChatCompletions'a hiçbir değer göndermiyordu, endpoint
# kendi bilinmeyen varsayılanını sessizce kullanıyordu) canlıda 9 paralel deep-
# review session'ından biri (cops20260927_11, qwen3.8-flash-next) 100/100 adımda
# hâlâ kesikken pes etti — "derin güvenlik review yaz" gibi uzun-final-cevap
# gerektiren görevler eski (4096 zımni) çıktı bütçesiyle çok fazla "kesildi,
# devam et" turu istiyor, 100 adım (aynı sayaç hem tool-call hem continuation
# için PAYLAŞIMLI) yetmiyordu. "medium" 4096'da (ucli'nin kendi varsayılanı,
# davranış DEĞİŞMİYOR, sadece açıkça yazıldı) bırakıldı, "high" 16000'e
# çıkarıldı + max_steps 200'e — ikisi birlikte gerçek canlı arızayı hedefliyor.
_EFFORT_LIMITS = {
    "medium": {"max_steps": 25, "max_context_kib": 256, "max_tool_calls": 64, "max_output_tokens": 4096},
    "high": {"max_steps": 200, "max_context_kib": 16384, "max_tool_calls": 256, "max_output_tokens": 16000},
}
_EFFORT_LEVELS = list(_EFFORT_LIMITS.keys())

# Bir model isteğinin ucli'de iptal edilmeden bekleyeceği süre (`--request-timeout-secs`; ucli'nin kendi
# varsayılanı 120 sn). Zaman aşımı filoda ölçülen EN PAHALI tek olay: sunucu iptal edilen isteği yine işleyip
# sayıyor ve yeniden deneme önbelleksiz dönüyor (unified-cli `bench/token-economy`: bir koşunun %28'i, bir
# diğerinde meşru işin 2,4 katı; `wifi5gppr20261016_4`te ~231 KB'lık bir istek 120 sn'yi aşıp ~80K token
# boşa yaktı). 600: unified-cli TOBEDECIDED.md "Token ekonomisi" seçenek (b)nin önerisi. Ayarlar'daki
# `ucli_limits.request_timeout_secs` bunun YERİNE geçer. `_EFFORT_LIMITS`e BİLEREK girmedi: effort adı çalışan
# komut satırından o dört sayıyla geri okunur (`extract_info`), beşincisi eski oturumların effort'unu
# "bilinmiyor"a düşürürdü.
_REQUEST_TIMEOUT_SECS = 600

# Durum dosyasının `usage` nesnesinin (unified-cli `status.rs`) alanları, `live_usage`in döndürdüğü anahtarlar.
# `reported < requests` ya da `unmetered > 0` ise token sayıları TABANDIR (uç nokta bazı isteklerde `usage`
# göndermedi / iptal edilen deneme sunucuda sayıldı ama tokeni bilinmiyor); bu karar arayüzde verilir.
_USAGE_FIELDS = ("requests", "reported", "prompt_tokens", "cached_tokens", "completion_tokens",
                 "reasoning_tokens", "request_bytes", "unmetered", "unmetered_bytes")

# Durum dosyasındaki `phase` (unified-cli 1778f34, 2026-10-18) tam sayı alanları. `name` ve `detail` metin.
_PHASE_INT_FIELDS = ("since_unix", "attempt", "max_attempts", "wait_secs", "streamed_bytes")

# permission_mode: `chat --allow-edit`'in iki hali (varsayılan KAPALI = salt-
# okunur araçlar). [0] varsayılan (RegisterForm.tsx effectiveModel deseniyle
# AYNI "ilk eleman = varsayılan" kuralı).
_READ_ONLY = "read-only"
_ALLOW_EDIT = "allow-edit"
# 2026-10-17: `chat --allow-create` (unified-cli 2026-09-28): YALNIZ yeni dosya yaratabilir, var olan hiçbir şeyi
# değiştiremez/silemez/taşıyamaz (--allow-edit ile karşılıklı dışlayıcı). Araştırma oturumları "yalnız reviews/…
# yaz" için bunu kullanır.
_ALLOW_CREATE = "allow-create"
_PERMISSION_MODES = [_READ_ONLY, _ALLOW_EDIT, _ALLOW_CREATE]

# `_fetch_live_models()` başarısız olursa (key yok/ağ hatası) düşülecek son
# çare — TOBEDECIDED#46'da canlı doğrulanmış TEK model. ucli'nin KENDİ
# --endpoint varsayılanı yerel Ollama'dır (`localhost:11434`) — bu model O
# ENDPOINT'TE YOK, EVREN'e özel; ikisi ayrılırsa 404 (canlı bulundu,
# 2026-09-24, kullanıcı "selam" deyip 404 aldı) — bu yüzden model VE endpoint
# burada birlikte, sabit bir çift olarak tutuluyor.
_MODEL_CHOICES = ["deepseek-v4-flash"]
_ENDPOINT = "https://evren-llmapi.ssyz.org.tr/v1"

# 2026-09-29 canlı bulgu: eskiden süreç ömrü boyunca EN FAZLA BİR ağ isteği
# vardı (TTL yok) — ilk çağrı reboot'tan hemen sonra ağ/Evren henüz hazır
# değilken başarısız olursa (canlı yaşandı: servis bu sabahki reboot'tan
# sonra ucli için sürekli tek elemanlı statik yedeği (`_MODEL_CHOICES`)
# sunmaya devam etti, oysa Evren o sırada zaten erişilebilirdi — servis
# yeniden başlamadan KENDİLİĞİNDEN düzelmiyordu) o başarısızlık BİR DAHA HİÇ
# denenmeden kalıcılaşıyordu. `agy_provider.py`'nin `_MODELS_TTL` deseniyle
# AYNI periyodik-yeniden-deneme'ye geçildi — `/api/status`'un her poll'unda
# HÂLÂ ağ isteği atılmıyor (`_LIVE_MODEL_CACHE_TS` bunu engelliyor), sadece
# artık süresiz değil, 5 dakikada bir tekrar denendiği için Evren/key
# durumu düzelince PANEL DE kendiliğinden düzeliyor.
_MODELS_TTL = 300.0
_LIVE_MODEL_CACHE: Optional[List[str]] = None
_LIVE_MODEL_CACHE_TS = 0.0
# model kimliği -> Evren'in o modeldeki `capabilities` nesnesi (son BAŞARILI çekimden; `reasoning_effort_for`
# okur). Boş = hiç çekilemedi (anahtarsız kurulum, ağ yok): `--effort` hiç geçmez.
_LIVE_CAPS: Dict[str, dict] = {}


def _fetch_live_models() -> Optional[List[str]]:
    """EVREN'in `GET /v1/models`'ı — stdlib-only (`web_hosts.py`'nin
    "requests/httpx YOK" disiplini). Key yoksa veya istek herhangi bir
    sebeple başarısız olursa None (çağıran sabit yedeğe düşer) — bu asla
    fırlatmaz, /api/status'un geri kalanını bir ağ/EVREN sorunu yüzünden
    kırmaz."""
    global _LIVE_CAPS
    key = byok_env_for("ucli").get("UCLI_API_KEY", "").strip()
    if not key:
        return None
    req = urllib.request.Request(
        _ENDPOINT.rstrip("/") + "/models",
        headers={"X-API-Key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            payload = json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None
    # `task` alanına göre filtrele — canlı yanıt (2026-09-24) chat DIŞI
    # modeller de içeriyordu (dots-ocr/qwen3-embedding-8b/qwen3-reranker-8b/
    # qwen3-asr-1.7b/deepseek-ocr-2 — OCR/embedding/reranking/konuşma-tanıma),
    # bunlar ucli chat'in agent döngüsünde anlamsız/işlevsiz olurdu. `task`
    # alanı yoksa/tanınmayan bir değerse (ileride yeni bir kategori eklenirse)
    # temkinli davranıp DIŞARIDA bırakılıyor — sessizce yanlış bir modeli
    # sunmaktansa listeden eksik kalması daha güvenli.
    chat = [
        m for m in payload.get("data", [])
        if isinstance(m, dict) and m.get("id") and m.get("task") == "chat"
    ]
    if chat:
        # AYNI çekimden model yetenekleri de saklanır (`--effort` kapısı, bkz. `reasoning_effort_for`): ikinci bir
        # ağ isteği ve ikinci bir TTL yok. Boş/başarısız çekim önceki haritayı silmez (id listesiyle aynı kural).
        _LIVE_CAPS ={m["id"]: m["capabilities"] for m in chat if isinstance(m.get("capabilities"), dict)}
    return [m["id"] for m in chat] or None


def _live_models() -> List[str]:
    """TTL'li (`_MODELS_TTL`) canlı model listesi + yedek; `model_choices()` ve `reasoning_effort_for` ortak
    kullanır. Asla fırlatmaz."""
    global _LIVE_MODEL_CACHE, _LIVE_MODEL_CACHE_TS
    now = time.monotonic()
    if _LIVE_MODEL_CACHE is None or now - _LIVE_MODEL_CACHE_TS > _MODELS_TTL:
        _LIVE_MODEL_CACHE_TS = now
        fetched = _fetch_live_models()
        if fetched:
            _LIVE_MODEL_CACHE = fetched
        elif _LIVE_MODEL_CACHE is None:
            _LIVE_MODEL_CACHE = list(_MODEL_CHOICES)
        # fetched boşsa ama zaten bir cache VARSA (önceki başarılı liste ya
        # da statik yedek) dokunulmaz — geçici bir hata onu geriletmesin.
    return _LIVE_MODEL_CACHE


def reasoning_effort_for(model: str, level: str) -> Optional[str]:
    """`--effort`e verilecek seviye; modelin alanı KABUL ETTİĞİ kanıtlı değilse None. Kaynak Evren'in
    `GET /v1/models` `capabilities` alanı: `reasoning_effort` (true/false), `reasoning_effort_values` (izinli
    liste ya da null), `reasoning_effort_aliases` (ör. glm-5.3: medium -> high). Canlı bulgu (2026-10-17):
    gemma-4-31b alanı HTTP 400 ile reddediyor ("'reasoning_effort' parametresini desteklemiyor"); körlemesine
    geçirmek o modelin oturumlarını ilk istekte öldürürdü. Bilinmeyen model, çekilememiş katalog ya da
    anahtarsız kurulum = None (eski davranış: alan hiç gönderilmez)."""
    _live_models()   # TTL'li tazeleme; panelin /api/status poll'u listeyi zaten sıcak tutuyor
    caps = _LIVE_CAPS.get(model)
    if not isinstance(caps, dict) or caps.get("reasoning_effort") is not True:
        return None
    values, aliases = caps.get("reasoning_effort_values"), caps.get("reasoning_effort_aliases")
    if isinstance(values, list) and values and level not in values \
            and not (isinstance(aliases, dict) and level in aliases):
        return None
    return level

# EVREN `evren_llm_...` key'i — tmux SUNUCUSU yeni pane'lere `update-environment`
# LİSTESİNDEKİ (DISPLAY/SSH_AUTH_SOCK) dışında hiçbir env değişkeni AKTARMIYOR
# (canlı doğrulandı, 2026-09-24: `strings /proc/<pid>/environ` çalışan ucli
# process'inde ne UCLI_API_KEY ne UCLI_MODEL_URL buldu) — bu yüzden anahtar
# claudeops-web'in KENDİ ortamından miras kalamıyor, `web.token`'la AYNI
# desende (chmod 600, tek-kullanıcı) ayrı bir dosyadan okunuyor; asıl kaynak
# Ayarlar'daki BYOK alanı (`_sync_api_key_file()` her spawn'da tazeler).
_API_KEY_FILE = os.path.expanduser("~/.claude/claudeops/ucli_api_key")


def _sync_api_key_file() -> bool:
    """Settings'te (`byok.ucli.UCLI_API_KEY`) bir değer varsa `_API_KEY_FILE`'a
    (chmod 600) yazar/tazeler, `True` döner. Settings'te değer YOKSA dosyaya
    DOKUNMAZ — elle (ör. eski `read -s` deneme sürecinden) oluşturulmuş bir
    dosya varsa onu KORUR, sessizce silmez; sadece o dosyanın var olup
    olmadığını döner."""
    key = byok_env_for("ucli").get("UCLI_API_KEY", "").strip()
    if not key:
        return os.path.isfile(_API_KEY_FILE)
    fd = os.open(_API_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key)
    return True


def _web_args(binary: str, session_name: str = "") -> List[str]:
    """Ayarlar'daki `ucli_web` (bkz. `settings.ucli_web_config`) → ucli'nin web bayrakları.
    ARAMA varsayılan AÇIK (kullanıcı kararı, 2026-10-16): `search_url` boşken claudeops'un yönettiği
    yerel SearXNG kapsayıcısı (`searxng.ensure_search_url`: kendiliğinden kurulur/başlar) kullanılır;
    hazır değilse o oturum aramasız açılır, spawn ASLA beklemez/kırılmaz. GEÇİCİ: ucli aramayı
    Docker'sız kendi içine alınca bu dal kalkar (TOBEDECIDED.md TBD#88). `fetch_url` ise yalnız
    `allow_fetch_domains` doluysa (unified-cli be4448a'nın kendi ilkesi: yetenek bayrakları kapalı gelir).
    Her yetenek AYRI ve YALNIZ ikili o bayrağı tanıyorsa eklenir: web bayrakları farklı commit'lerde
    geldi, eski bir ikili 'unexpected argument' ile spawn anında patlardı (yukarıdaki ⚠ notla AYNI
    risk); tanımıyorsa o yetenek atlanır ve günlüğe yazılır (eski ikiliyle docker'a da dokunulmaz).
    Anahtar GEREKMİYOR (SearXNG arka ucu operatörün kendi adresi); bu yüzden argv'ye sır girmez."""
    cfg = ucli_web_config()
    args: List[str] = []
    if cfg.get("search_url") or cfg.get("search_docker"):
        auto = not cfg.get("search_url")
        if not binary_supports_flag(binary, "--search-url"):
            diag_log("ucli_web_flag_unsupported", name=session_name, flag="--search-url", binary=binary, auto=auto)
        else:
            url = cfg.get("search_url")
            if auto:
                try:
                    url = searxng.ensure_search_url(session_name)
                except Exception as e:   # sözleşme: fırlatmaz; yine de web araması spawn'ı KIRMASIN
                    diag_log("ucli_web_searxng_error", name=session_name, error=repr(e)[:200])
                    url = None
            if url:
                args += ["--search-url", url, "--search-flavor", "searxng"]
    domains = cfg.get("allow_fetch_domains")
    if domains:
        if binary_supports_flag(binary, "--allow-fetch"):
            args.append("--allow-fetch")
            for d in domains:
                args += ["--allow-fetch-domain", d]
        else:
            diag_log("ucli_web_flag_unsupported", name=session_name, flag="--allow-fetch", binary=binary)
    return args


def _script_args(binary: str, session_name: str = "") -> List[str]:
    """`--allow-script=read|full` (bkz. `settings.ucli_script_mode`). VARSAYILAN KAPALI: ayar boşsa argv BİREBİR
    eskisi. Diğer bayraklarla AYNI sebepten YALNIZ ikili bayrağı tanıyorsa eklenir (eski ikili 'unexpected
    argument' ile spawn anında patlardı); atlanırsa günlüğe yazılır. `=` biçimi ŞART: ucli'nin bayrağı isteğe
    bağlı değer alır, ayrı argüman olarak yazılsa komut satırındaki bir sonraki sözcüğü yutabilirdi."""
    mode = ucli_script_mode()
    if not mode:
        return []
    if not binary_supports_flag(binary, "--allow-script"):
        diag_log("ucli_flag_unsupported", name=session_name, flag="--allow-script", binary=binary)
        return []
    return [f"--allow-script={mode}"]


def _stream_args(binary: str, session_name: str = "") -> List[str]:
    """`--stream` (bkz. `settings.ucli_stream_enabled`). Diğer bayraklarla AYNI sebepten YALNIZ ikili bayrağı tanıyorsa
    eklenir (eski ikili 'unexpected argument' ile spawn anında patlardı); atlanırsa günlüğe yazılır. Sağlayıcı filtresi
    YOK: claudeops `--provider` geçirmez, ucli'nin varsayılanı `chat-completions` (akışı yalnız o destekler)."""
    if not ucli_stream_enabled():
        return []
    if not binary_supports_flag(binary, "--stream"):
        diag_log("ucli_flag_unsupported", name=session_name, flag="--stream", binary=binary)
        return []
    return ["--stream"]


def _timeout_args(binary: str, limits: Dict[str, int], session_name: str = "") -> List[str]:
    """`--request-timeout-secs` (bkz. `_REQUEST_TIMEOUT_SECS`). `_web_args`le AYNI sebepten YALNIZ ikili bayrağı
    tanıyorsa eklenir: eski bir ikili 'unexpected argument' ile spawn anında patlardı; tanımıyorsa atlanır
    ve günlüğe yazılır (o oturum ucli'nin kendi 120 sn'siyle açılır)."""
    if not binary_supports_flag(binary, "--request-timeout-secs"):
        diag_log("ucli_flag_unsupported", name=session_name, flag="--request-timeout-secs", binary=binary)
        return []
    return ["--request-timeout-secs", str(limits.get("request_timeout_secs", _REQUEST_TIMEOUT_SECS))]


# `--effort` ("ne kadar düşünsün"; Evren'e üst düzey `reasoning_effort` olarak gider). Filo bugüne dek bayrağı HİÇ
# geçirmedi ve ölçülen en pahalı seçenek tam da buydu (unified-cli `bench/token-economy/README.md`, 2026-10-17,
# kod incelemesi görevi, ayar başına TEK koşu, deepseek-v4-flash): bayraksız 205K kota / 91K akıl yürütme tokeni /
# 716 sn; low 87K / 25K / 118 sn; medium 74K / 34K / 196 sn; high 105K / 32K / 174 sn. Kalite karşılaştırması
# YAPILMADI (cevap boyutları 8,4K / 4,3K / 4,4K / 18K karakter), bu yüzden yeni ayar/arayüz yok: panelde seçili
# effort ön ayarı (medium/high) aynı adla geçer, `ucli_limits.reasoning_effort` = `off` bugünkü davranışa tek
# ayarla döndürür. `_EFFORT_LIMITS`e BİLEREK girmedi (`_REQUEST_TIMEOUT_SECS`le aynı sebep: effort adı çalışan komut
# satırından dört sayıyla geri okunur). Model başına destek ayrıca denetlenir, bkz. `reasoning_effort_for`.
def _effort_args(binary: str, model: Optional[str], preset: str, session_name: str = "") -> List[str]:
    """`--effort` (bkz. üstteki not). `_timeout_args`le AYNI sebepten YALNIZ ikili bayrağı tanıyorsa eklenir (eski
    ikili 'unexpected argument' ile patlardı) ve YALNIZ model alanı kabul ediyorsa (HTTP 400 riski); atlanan her
    durum günlüğe yazılır, o oturum bugünkü gibi bayraksız açılır. `off` ayarı sessiz atlar."""
    mode = ucli_reasoning_mode()
    if mode == "off" or not model:
        return []
    if not binary_supports_flag(binary, "--effort"):
        diag_log("ucli_flag_unsupported", name=session_name, flag="--effort", binary=binary)
        return []
    level = preset if mode == "auto" else mode
    value = reasoning_effort_for(model, level)
    if value is None:
        diag_log("ucli_effort_skipped", name=session_name, model=model, level=level)
        return []
    return ["--effort", value]


class UcliProvider(CliProvider):
    name = "ucli"

    def has_conversation(self) -> bool:
        return True  # gerçek bir sohbet: .ucli/chat/NAME.jsonl geçmişi tutuyor

    def resolve_resume_id(self, cwd: str, in_use: FrozenSet[str] = frozenset(),
                          session_name: str = "") -> Optional[str]:
        return None  # "resume" zaten --session NAME'in kendisi, ayrı id yok

    def build_inner_command(self, cwd, model, permission_mode, effort,
                             resume_id, prompt, session_name, extra_args: Sequence[str] = ()) -> str:
        # resume_id/prompt/extra_args ucli'de anlamsız — yok sayılır (MCP
        # kavramı bu yüzeyde yok, mcp_launch_args() base.py'nin boş-liste
        # varsayımında kalıyor). effort → --max-steps + --max-context-kib +
        # --max-tool-calls, bkz. _EFFORT_LIMITS'in yorumu; tanınmayan/boş bir
        # değer sessizce "medium"a düşer. Ayarlar > model'deki `ucli_limits`
        # override'ı (settings.ucli_limit_overrides(), TODO.md'nin ucli effort
        # maddesi, 2026-09-24) dolu olduğu alanlarda preset'in sayısının
        # YERİNE geçer — artık kullanıcı Python'a dokunmadan/servis restart
        # etmeden bu 3 sayıyı kendi ayarlayabiliyor.
        preset = effort if effort in _EFFORT_LIMITS else "medium"
        limits = {**_EFFORT_LIMITS[preset], **ucli_limit_overrides()}
        argv = [
            resolve_binary(), "--root", cwd, "chat", "--repl", "--endpoint", _ENDPOINT,
            "--max-steps", str(limits["max_steps"]),
            "--max-context-kib", str(limits["max_context_kib"]),
            "--max-tool-calls", str(limits["max_tool_calls"]),
            "--max-output-tokens", str(limits["max_output_tokens"]),
            "--pretty",
        ]
        if session_name:
            # --status-file: 2026-10-04'te ucli --help'te fark edildi, "e.g.
            # claudeops" diyen kendi docstring'i TAM BU okuma için eklenmiş
            # (.ucli/chat/{session}.status.json, bkz. live_busy()). --session
            # olmadan anlamsız (ucli kendi --help'i "meaningful only with
            # --repl and --session NAME" diyor) — bu yüzden onunla aynı dalda.
            argv += ["--session", session_name, "--status-file"]
        if model:
            argv += ["--model", model]
        if permission_mode == _ALLOW_EDIT:
            argv.append("--allow-edit")
        elif permission_mode == _ALLOW_CREATE:
            if binary_supports_flag(argv[0], "--allow-create"):
                argv.append("--allow-create")
            else:   # tanımayan eski ikili 'unexpected argument' ile patlardı: salt-okunur aç, günlüğe yaz
                diag_log("ucli_flag_unsupported", name=session_name, flag="--allow-create", binary=argv[0])
        argv += _web_args(argv[0], session_name)
        argv += _script_args(argv[0], session_name)
        argv += _timeout_args(argv[0], limits, session_name)
        argv += _effort_args(argv[0], model, preset, session_name)
        argv += _stream_args(argv[0], session_name)
        inner =" ".join(shlex.quote(a) for a in argv)
        if _sync_api_key_file():
            # Anahtarı argv'ye GÖMMÜYORUZ — bu makine çok-kullanıcılı, `ps aux`
            # komut satırını HERKESE gösterir (CLAUDE.md'nin uyardığı sınıf).
            # `exec`'ten ÖNCE dosyayı okuyup env'e koyan bir `sh -c` sarmalıyor:
            # anahtar SADECE ucli process'inin (argv'de DEĞİL) ortamında kalır,
            # `exec` sh'yi ucli ile DEĞİŞTİRDİĞİ için (aynı PROC_TAG deseni,
            # bkz. shell_provider.py) discovery'nin gördüğü argv de temiz kalır.
            wrapped = f'UCLI_API_KEY="$(cat {_API_KEY_FILE})" exec {inner}'
            return "sh -c " + shlex.quote(wrapped)
        return inner

    def matches_proc(self, cmd: List[str]) -> bool:
        return bool(cmd) and os.path.basename(cmd[0]) == "ucli"

    def _parse_session(self, cmd: List[str]) -> Optional[str]:
        for i, tok in enumerate(cmd):
            if tok == "--session" and i + 1 < len(cmd):
                return cmd[i + 1]
        return None

    def extract_name(self, proc: "psutil.Process", cmd: List[str]) -> Optional[str]:
        return self._parse_session(cmd)

    def extract_info(self, cmd: List[str], cwd: str = "", session_name: str = "") -> Dict[str, Optional[str]]:
        model = None
        parsed_limits: Dict[str, str] = {}
        flag_to_key = {
            "--max-steps": "max_steps",
            "--max-context-kib": "max_context_kib",
            "--max-tool-calls": "max_tool_calls",
            "--max-output-tokens": "max_output_tokens",
        }
        for i, tok in enumerate(cmd):
            if tok == "--model" and i + 1 < len(cmd):
                model = cmd[i + 1]
            elif tok in flag_to_key and i + 1 < len(cmd):
                parsed_limits[flag_to_key[tok]] = cmd[i + 1]
        permission_mode = (_ALLOW_EDIT if "--allow-edit" in cmd
                           else _ALLOW_CREATE if "--allow-create" in cmd else _READ_ONLY)
        # Ters eşleme: DÖRDÜNÜN BİRDEN eşleştiği preset'in adına dön — tek bir
        # bayrak artık yetmez (dört bağımsız bayrak var). Eşleşmezse (elle
        # değiştirilmiş/eski bir preset) None: bilinmeyen bir effort adı
        # UYDURMAKTANSA "bilinmiyor" göstermek daha doğru. 2026-10-16: dördüncü
        # alan (`--max-output-tokens`, 2026-09-28'de presetlere eklendi) burada
        # ayrıştırılmıyordu, bu yüzden hiçbir preset eşleşmiyor ve effort HEP None
        # çıkıyordu; `test_ucli_web.BuildInnerCommandTests.test_every_effort_preset_round_trips_
        # through_the_running_command` preset ile ayrıştırıcı birbirinden koparsa yakalar.
        effort = next(
            (name for name, lim in _EFFORT_LIMITS.items()
             if all(str(v) == parsed_limits.get(k) for k, v in lim.items())),
            None,
        )
        # sid = session adının kendisi (yukarıdaki modül docstring'ine bkz.) —
        # full_history/last_exchange'in .ucli/chat/{sid}.jsonl'ı bulabilmesi için.
        return {"sid": self._parse_session(cmd), "model": model, "permission_mode": permission_mode, "effort": effort}

    def model_choices(self) -> List[str]:
        return _live_models()

    def permission_modes(self) -> List[str]:
        return _PERMISSION_MODES

    def effort_levels(self) -> List[str]:
        return _EFFORT_LEVELS

    def full_history(self, cwd: str, sid: Optional[str]) -> Optional[List[Dict[str, str]]]:
        if not sid:
            return None
        return read_chat_history(cwd, sid)

    def sid_for_stopped_session(self, cwd: str, session_name: str) -> Optional[str]:
        # sid = session adının kendisi (modül docstring'i, `extract_info`): durmuş bir ucli
        # session'ı sid'siz kalınca `full_history` None döner ve panel, ucli sohbeti
        # DESTEKLEDİĞİ halde "bu CLI için sohbet görünümü henüz yok" derdi.
        return session_name or None

    def live_busy(self, cwd: str, sid: Optional[str]) -> Optional[bool]:
        # waiting_for_stdin = idle (sıradaki prompt'u bekliyor); diğer üçü
        # (waiting_for_model/running_tool/waiting_for_user) "şu an bir turu
        # işliyor, yeni bir prompt enjekte etme" anlamında hepsi busy=True —
        # waiting_for_user (modelin kendi ask_user tool-call'ı, bkz. ucli'nin
        # status.rs'i) teknik olarak "insan girdisi bekliyor" olsa da
        # BEKLEDİĞİ şey sıradan bir chat mesajı değil o tool-call'ın cevabı,
        # panelin düz "mesaj gönder" kutusuyla karıştırılmamalı.
        if not sid:
            return None
        status = read_status_file(cwd, sid)
        if status is None:
            return None
        return status.get("activity") != "waiting_for_stdin"

    def live_usage(self, cwd: str, sid: Optional[str]) -> Optional[Dict[str, int]]:
        # Durum dosyasındaki `usage` (unified-cli 2026-10-16): SÜREÇ boyunca TÜM görevlerin toplamı,
        # başarısız görev dahil. `usage` hiç yoksa (eski ikili) None = bilinmiyor; `unmetered*`
        # (1d64d73) eski ikilide yok, yokluğu 0 sayılır. Sayı olmayan/negatif değer 0'a iner: rozet
        # bozuk bir dosya yüzünden hiç görünmez olmasın, ama uydurma bir sayı da göstermesin.
        if not sid:
            return None
        status = read_status_file(cwd, sid)
        raw = status.get("usage") if status else None
        if not isinstance(raw, dict):
            return None
        out: Dict[str, int] = {}
        for key in _USAGE_FIELDS:
            v = raw.get(key, 0)
            out[key] = v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0
        return out

    def live_phase(self, cwd: str, sid: Optional[str]) -> Optional[Dict[str, Any]]:
        # Durum dosyasındaki `phase` (unified-cli 1778f34, 2026-10-18): bir MODEL ÇAĞRISI sürerken o an ne yapıldığı
        # (`waiting_response`/`thinking`/`writing`/`retry_backoff`/`rate_limited`); çağrı dışında null, eski ikilide alan
        # yok → None (bilinmiyor, rozet yok). `thinking`/`writing` YALNIZ `--stream` ile ayırt edilir (akışsız yanıt tek
        # parça gelir). Bilinmeyen ad AYNEN geçer (ileri uyum: ucli yeni bir faz ekleyince rozet susmasın), sayı olmayan
        # ya da negatif değer atılır (uydurma bir sayı göstermemek için 0'a ÇEKİLMEZ: eksik alan "bilinmiyor" demek).
        if not sid:
            return None
        status = read_status_file(cwd, sid)
        raw = status.get("phase") if status else None
        if not isinstance(raw, dict):
            return None
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        out: Dict[str, Any] = {"name": name.strip()[:40]}
        for key in _PHASE_INT_FIELDS:
            v = raw.get(key)
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                out[key] = v
        detail = raw.get("detail")
        if isinstance(detail, str) and detail.strip():
            out["detail"] = detail.strip()[:160]
        # `last_activity_unix`: dosyanın EN SON yazıldığı an (ucli her yazımda yeniler; akışta en çok 2 sn'de bir yazar).
        # Akış donarsa bu durur, `since_unix` (aşamanın başı) durmaz: "son bayttan beri" süresi ancak bundan çıkar.
        last = status.get("last_activity_unix")
        if isinstance(last, int) and not isinstance(last, bool) and last >= 0:
            out["last_unix"] = last
        return out

    def last_exchange(self, cwd: str, sid: Optional[str]) -> Optional[Dict[str, str]]:
        turns = self.full_history(cwd, sid)
        if not turns:
            return None
        last_user = next((t["text"] for t in reversed(turns) if t["role"] == "user"), None)
        last_assistant = next((t["text"] for t in reversed(turns) if t["role"] == "assistant"), None)
        if last_user is None and last_assistant is None:
            return None
        return {"user": last_user or "", "assistant": last_assistant or ""}
