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

effort: gerçek bir "ne kadar düşünsün" karşılığı unified-cli'de hâlâ yok
(TOBEDECIDED.md'ye ayrıca not edildi) — ama PRATİKTE `--max-steps` +
`--max-context-kib`'e bağlandı, bkz. `_EFFORT_LIMITS`'in yorumu (2026-09-24,
"8-round limit" ve ardından "context exceeds 256 KiB" hataları canlı
yaşandı, aynı gün unified-cli'de ikisi de gevşetildi).

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
import urllib.error
import urllib.request
from typing import Dict, FrozenSet, List, Optional, Sequence

import psutil

from ..settings import byok_env_for, ucli_limit_overrides
from ..ucli_client import read_chat_history, resolve_binary
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
_EFFORT_LIMITS = {
    "medium": {"max_steps": 25, "max_context_kib": 256, "max_tool_calls": 64},
    "high": {"max_steps": 100, "max_context_kib": 16384, "max_tool_calls": 256},
}
_EFFORT_LEVELS = list(_EFFORT_LIMITS.keys())

# permission_mode: `chat --allow-edit`'in iki hali (varsayılan KAPALI = salt-
# okunur araçlar). [0] varsayılan (RegisterForm.tsx effectiveModel deseniyle
# AYNI "ilk eleman = varsayılan" kuralı).
_READ_ONLY = "read-only"
_ALLOW_EDIT = "allow-edit"
_PERMISSION_MODES = [_READ_ONLY, _ALLOW_EDIT]

# `_fetch_live_models()` başarısız olursa (key yok/ağ hatası) düşülecek son
# çare — TOBEDECIDED#46'da canlı doğrulanmış TEK model. ucli'nin KENDİ
# --endpoint varsayılanı yerel Ollama'dır (`localhost:11434`) — bu model O
# ENDPOINT'TE YOK, EVREN'e özel; ikisi ayrılırsa 404 (canlı bulundu,
# 2026-09-24, kullanıcı "selam" deyip 404 aldı) — bu yüzden model VE endpoint
# burada birlikte, sabit bir çift olarak tutuluyor.
_MODEL_CHOICES = ["deepseek-v4-flash"]
_ENDPOINT = "https://evren-llmapi.ssyz.org.tr/v1"

# Süreç ömrü boyunca en fazla BİR ağ isteği — `model_choices()` `/api/status`'un
# her poll'unda çağrılıyor, canlı fetch orada YAPILAMAZ (yavaşlatır/bloklar).
# None = "henüz denenmedi", boş liste DEĞİL (aksi halde her çağrı yeniden
# denerdi, key kalıcı yoksa sürekli başarısız ağ isteği atardı).
_LIVE_MODEL_CACHE: Optional[List[str]] = None


def _fetch_live_models() -> Optional[List[str]]:
    """EVREN'in `GET /v1/models`'ı — stdlib-only (`web_hosts.py`'nin
    "requests/httpx YOK" disiplini). Key yoksa veya istek herhangi bir
    sebeple başarısız olursa None (çağıran sabit yedeğe düşer) — bu asla
    fırlatmaz, /api/status'un geri kalanını bir ağ/EVREN sorunu yüzünden
    kırmaz."""
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
    models = [
        m["id"] for m in payload.get("data", [])
        if isinstance(m, dict) and m.get("id") and m.get("task") == "chat"
    ]
    return models or None

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
        limits = {**_EFFORT_LIMITS.get(effort, _EFFORT_LIMITS["medium"]), **ucli_limit_overrides()}
        argv = [
            resolve_binary(), "--root", cwd, "chat", "--repl", "--endpoint", _ENDPOINT,
            "--max-steps", str(limits["max_steps"]),
            "--max-context-kib", str(limits["max_context_kib"]),
            "--max-tool-calls", str(limits["max_tool_calls"]),
            "--pretty",
        ]
        if session_name:
            argv += ["--session", session_name]
        if model:
            argv += ["--model", model]
        if permission_mode == _ALLOW_EDIT:
            argv.append("--allow-edit")
        inner = " ".join(shlex.quote(a) for a in argv)
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

    def extract_info(self, cmd: List[str]) -> Dict[str, Optional[str]]:
        model = None
        parsed_limits: Dict[str, str] = {}
        flag_to_key = {
            "--max-steps": "max_steps",
            "--max-context-kib": "max_context_kib",
            "--max-tool-calls": "max_tool_calls",
        }
        for i, tok in enumerate(cmd):
            if tok == "--model" and i + 1 < len(cmd):
                model = cmd[i + 1]
            elif tok in flag_to_key and i + 1 < len(cmd):
                parsed_limits[flag_to_key[tok]] = cmd[i + 1]
        permission_mode = _ALLOW_EDIT if "--allow-edit" in cmd else _READ_ONLY
        # Ters eşleme: ÜÇÜNÜN BİRDEN eşleştiği preset'in adına dön — tek bir
        # bayrak artık yetmez (üç bağımsız bayrak var). Eşleşmezse (elle
        # değiştirilmiş/eski bir preset) None: bilinmeyen bir effort adı
        # UYDURMAKTANSA "bilinmiyor" göstermek daha doğru.
        effort = next(
            (name for name, lim in _EFFORT_LIMITS.items()
             if all(str(v) == parsed_limits.get(k) for k, v in lim.items())),
            None,
        )
        # sid = session adının kendisi (yukarıdaki modül docstring'ine bkz.) —
        # full_history/last_exchange'in .ucli/chat/{sid}.jsonl'ı bulabilmesi için.
        return {"sid": self._parse_session(cmd), "model": model, "permission_mode": permission_mode, "effort": effort}

    def model_choices(self) -> List[str]:
        global _LIVE_MODEL_CACHE
        if _LIVE_MODEL_CACHE is None:
            _LIVE_MODEL_CACHE = _fetch_live_models() or list(_MODEL_CHOICES)
        return _LIVE_MODEL_CACHE

    def permission_modes(self) -> List[str]:
        return _PERMISSION_MODES

    def effort_levels(self) -> List[str]:
        return _EFFORT_LEVELS

    def full_history(self, cwd: str, sid: Optional[str]) -> Optional[List[Dict[str, str]]]:
        if not sid:
            return None
        return read_chat_history(cwd, sid)

    def last_exchange(self, cwd: str, sid: Optional[str]) -> Optional[Dict[str, str]]:
        turns = self.full_history(cwd, sid)
        if not turns:
            return None
        last_user = next((t["text"] for t in reversed(turns) if t["role"] == "user"), None)
        last_assistant = next((t["text"] for t in reversed(turns) if t["role"] == "assistant"), None)
        if last_user is None and last_assistant is None:
            return None
        return {"user": last_user or "", "assistant": last_assistant or ""}
