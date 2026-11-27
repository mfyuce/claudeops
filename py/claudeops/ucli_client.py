"""ucli (unified-cli, ~/work/projects/tmp/unified-cli) rust agent'ını
subprocess pipe'ıyla konuşan, tmux'suz varsayılan yol — TOBEDECIDED#44(b).

Bilerek bir `CliProvider` DEĞİL (bkz. providers/base.py): o arayüz "uzun
ömürlü, etkileşimli bir tmux pane'i" varsayımı üzerine kurulu (spawn/discovery/
handover hepsi bunu varsayar), ucli'nin `chat --repl`/`chat --session` modları
ise düz stdin/stdout JSON-satırı yeterli, TTY'ye hiç dokunmuyor — kullanıcı
notu (2026-09-22): "claudeops her zaman tmux istemez, stdin'de [de] modlar
olsa iyi olur". tmux'lu (hidden=True, panelden canlı izlenebilir) bir yol
İSTENİRSE ShellProvider'ın deseni ayrıca eklenir; aynı gün ikinci bir netleşme
(kullanıcı): `--repl` hiçbir TTY-özel/raw-mode davranışına dokunmadığı için o
pane'de görülecek şey zaten sadece yazılan satır + JSON cevabın sırayla
ardışık akması — ayrı bir "girdi/çıktı" görünümü gerekmez. Bu modül o karardan
bağımsız, sadece pipe yolunu çözer.

İki mod:
- `ucli_chat_once()`: her çağrı ayrı process (`session=` verilirse ucli'nin
  kendi `.ucli/chat/NAME.jsonl`'ı üzerinden çağrılar arası hatırlar, verilmezse
  tamamen durumsuz) — nadir/ara sıra soru için, process-başlatma maliyeti
  önemsiz.
- `UcliReplSession`: TEK process açık kalır (`--repl`), turlar arasında
  `reqwest::Client` PAYLAŞILIR (TCP/TLS handshake tekrarlanmaz) — sık ardışık
  soru için. `ask()` bir prompt yazıp TEK JSON satırı okur; ucli'nin
  `main.rs`'i repl çıktısının HER turda tek-satır kompakt JSON olmasını
  garanti eder (2026-09-22'de burada bulunup unified-cli'de fixlendi —
  `--format`'ın pretty-print'i eskiden repl turlarını da 3 satıra
  yayıyordu, `output_with_style(..., pretty=False)` ile düzeltildi, bkz.
  unified-cli DONE.md/crates/ucli/tests/cli.rs'teki regresyon testi).

Protokolün kendi sınırı: `--repl` stdin'i SATIR satır okuyor, bir turun
cevabını request-id'siz eşliyor (sıraya güveniyor) — bu yüzden `ask()` bir
prompt içinde `\n` ya da boş satır kabul ETMEZ (ucli boş satırları sessizce
atlar, cevap gelmez → sıra kayar) ve timeout'ta session'ı KURTARMAYA
çalışmak yerine öldürür (gecikmiş bir cevap sıraya sonradan girip bir SONRAKİ
`ask()`'in cevabıymış gibi görünebilirdi — bkz. `_pump_stdout`).
"""
from __future__ import annotations
import collections
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import paths as _paths
from . import preview
from .childgroup import _run_grouped
from .diaglog import diag_log
from .settings import load_settings

# claudeops'un KENDİ ucli kopyası: `<repo>/bin/ucli` (kullanıcı kararı, 2026-10-09:
# "claudeops ucli'yi kendi reposunda tutsun, gerektiğinde release'i/debug'ı oraya
# gönderelim"). git'e GİRMEZ (.gitignore: /bin/ucli*), `scripts/install-ucli.sh`
# teslim eder. Dosya adı `ucli` KALMALI: providers/ucli_provider.py::matches_proc
# süreci basename'iyle tanıyor. Testlerde yamalanabilsin diye modül sabiti.
OWN_UCLI = Path(__file__).resolve().parents[2] / "bin" / "ucli"

# `/api/io/ask`'ın `api_key_env` alanı (bkz. io_providers/ucli_provider.py)
# doğrulanmadan `_subprocess_env`'de `os.environ`'a anahtar-ADI olarak
# yazılıyordu — `LD_PRELOAD`/`PYTHONPATH`/`BASH_ENV`/`NODE_OPTIONS` gibi bir
# İSİM göndermek (değeri her ne olursa olsun) subprocess'e kod enjeksiyonu
# demekti (Antigravity SEC-06). settings.py'nin BYOK maddesiyle "aynı bug
# sınıfı" olsa da BİLEREK DAHA SIKI bir desen kullanılıyor: burada meşru tek
# bir şekil var ("API anahtarımı tutan env-var'ın adı"), `COPILOT_PROVIDER_
# BASE_URL`/`_MODEL` gibi API-key-DIŞI meşru BYOK alanları (settings.py'nin
# izin verdiği) bu yüzeyde hiç yok — TODO.md'nin kendi önerisi
# (`^[A-Z0-9_]+_API_KEY$`) izlendi, genel `^[A-Z_][A-Z0-9_]*$` DEĞİL (o,
# "LD_PRELOAD" gibi sözdizimsel-geçerli ama anlamsal-tehlikeli bir ismi
# BURADA geçirirdi — canlı test bunu doğruladı, settings.py'nin daha gevşek
# deseni bilerek BAŞKA bir yüzey için, bkz. o dosyanın yorumu)."
_SAFE_ENV_NAME_RE = re.compile(r"^[A-Z0-9_]+_API_KEY$")


class UcliError(RuntimeError):
    """ucli'nin kendi `{"error": "..."}` turu ya da process/parse hatası."""


def resolve_binary(binary: Optional[str] = None) -> str:
    """`binary` verilmezse sırayla: Ayarlar > model'deki `provider_bin.ucli`
    override'ı, `UCLI_BIN` env, claudeops'un KENDİ kopyası (`OWN_UCLI` =
    `<repo>/bin/ucli`), PATH'te `ucli`, son çare olarak kardeş proje
    `~/work/projects/tmp/unified-cli`'nin release/debug build'i (release
    ÖNCE). Hiçbiri yoksa net bir hata — sessizce `FileNotFoundError: [Errno 2]`
    gibi anlaşılmaz bir subprocess istisnasına düşmek yerine.

    `provider_bin` override'ı 2026-09-24'te eklendi (TODO.md'nin federasyon
    maddesi) — `settings.resolved_binary()`'nin claude/codex/agy/copilot'ta
    ZATEN yaptığının aynısı, UI'da (Ayarlar > model, "CLI binary yolu
    override") `data.cli_list`'i döngüleyen satır zaten `ucli`'yi de
    kapsıyordu, sadece BU fonksiyon hiç okumuyordu. Alttaki adımlar (kendi
    kopya, PATH'te arama, kardeş proje build'i) BU MAKİNEYE özel kalmaya
    devam ediyor — federasyonda (ör. yuhem) `ucli` PATH'te değilse, kendi
    kopya teslim edilmemişse ve unified-cli AYNI dizin yapısında yoksa hâlâ
    patlar, ama artık o host'un KENDİ (host-başına-ayrı) settings.json'ına
    `provider_bin.ucli` yazılarak atlanabiliyor.

    Kendi kopya (kullanıcı kararı, 2026-10-09: "claudeops ucli'yi kendi
    reposunda tutsun, gerektiğinde release'i/debug'ı oraya gönderelim"):
    claudeops artık unified-cli'nin geliştirirken sürekli değişen `target/`
    dizinine BAĞIMLI değil; kullandığı ikili, biz bilerek teslim edene kadar
    değişmez. Teslim: `scripts/install-ucli.sh [release|debug] [--build]`.
    TEK aktif kopya vardır: hangi profili gönderdiysek `bin/ucli`'de o durur
    (hangisi olduğu `bin/ucli.info`'da), yani "debug gönderdim ama release hâlâ
    kazanıyor" tuzağı yok. git'e GİRMEZ (`.gitignore`: `/bin/ucli*`; public
    repo, release ~25 MB, debug ~100 MB, GitHub dosya sınırı 100 MB) ve
    `git pull` ile federasyon host'larına gitmez: oralar PATH ya da
    `provider_bin.ucli` kullanmaya devam eder. Debug'a zorlamak için ya debug'ı
    teslim et ya da `UCLI_BIN` / `provider_bin.ucli` ver.

    Kardeş proje build'i yalnız SON ÇARE (kendi kopya yoksa): release ÖNCE,
    debug yedek. ⚠ Bayat build tuzağı: unified-cli'nin kendi geliştirme
    döngüsü (README'nin HER örneği) `cargo build --locked` yani DEBUG derler;
    release'i kimse yenilemezse bu yol sessizce eski bir build'i seçer. CANLI
    yaşandı: 2026-09-22'de `target/release/ucli` 5 gün eski bir build'di
    (`--session`/`--repl` eklenmeden ÖNCE), sessizce seçilip kafa karıştırıcı
    "unexpected argument '--repl'" hatası verdi. Teslim edilen kopya da
    kendiliğinden yenilenmez; `install-ucli.sh` bayat kaynağı reddeder,
    otomatik yenileme TODO.md 2026-10-09'da açık."""
    if binary:
        return binary
    raw = (load_settings().get("provider_bin") or {}).get("ucli")
    override = raw.strip() if isinstance(raw, str) else ""      # elle düzenlenmiş metin olmayan değer yok sayılır
    if override:
        return override
    env_bin = os.environ.get("UCLI_BIN")
    if env_bin:
        return env_bin
    if OWN_UCLI.is_file():
        return str(OWN_UCLI)
    found = shutil.which("ucli")
    if found:
        return found
    sibling = Path.home() / "work" / "projects" / "tmp" / "unified-cli" / "target"
    for profile in ("release", "debug"):
        candidate = sibling / profile / "ucli"
        if candidate.is_file():
            return str(candidate)
    raise UcliError(
        "ucli binary bulunamadı — Ayarlar > model'de provider_bin.ucli'yi "
        "ayarla, UCLI_BIN ortam değişkenini ver, PATH'e ekle, ya da "
        "claudeops'a teslim et: `scripts/install-ucli.sh release --build` "
        "(unified-cli build'ini bin/ucli'ye kopyalar)."
    )


# `ucli chat --help` çıktısı, (yol, mtime_ns, boyut) başına: bayrak yoklaması her spawn'da bir
# alt süreç açmasın, ama teslim edilen yeni bir ikili (`install-ucli.sh`) mtime/boyutu değiştirip
# yoklamayı kendiliğinden tazelesin.
_HELP_CACHE: Dict[Tuple[str, int, int], str] = {}
_HELP_UNREADABLE: set = set()       # UTF-8 olmayan çıktısı günlüğe girmiş (yol, mtime_ns, boyut): yoklama başına tekrar yazılmaz
_HELP_TIMEOUT_SECONDS = 10.0


def chat_help_text(binary: str) -> str:
    """`<binary> chat --help` çıktısı (stdout + stderr); çalıştırılamazsa ya da çıktı UTF-8 değilse "" (hiçbir bayrak
    tanınmaz; ÖNBELLEĞE ALINMAZ: geçici bir hata kalıcı 'bayrak yok' kararına dönüşmesin)."""
    binary = shutil.which(binary) or binary       # çıplak komut adı (`ucli`) PATH'ten çözülür; os.stat onu bulamazdı
    try:
        st = os.stat(binary)
    except OSError:
        return ""
    key = (binary, st.st_mtime_ns, st.st_size)
    hit = _HELP_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        # stdin verilmezse girdi bekleyen ikili 10 sn asılır ve çağıranın girdisini (CLI terminali) tüketir
        res = _run_grouped([binary, "chat", "--help"], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                             timeout=_HELP_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return ""
    except UnicodeDecodeError:
        if key not in _HELP_UNREADABLE and not preview.active():      # kuru kipte günlük yok: işaret de tüketilmez
            _HELP_UNREADABLE.add(key)
            diag_log("help_output_not_utf8", binary=binary)
        return ""
    text = (res.stdout or "") + (res.stderr or "")
    if not text.strip():
        return ""
    _HELP_CACHE[key] = text
    return text


def binary_supports_flag(binary: str, flag: str) -> bool:
    """`ucli chat`in `flag`i tanıyıp tanımadığı. TAM bayrak eşleşmesi (`--allow-fetch`
    yalnız `--allow-fetch-domain` varsa 'var' sayılmaz): ucli'nin web bayrakları
    farklı commit'lerde geldi, eski bir ikili 'unexpected argument' ile spawn anında
    patlardı (bkz. `providers/ucli_provider.py` ⚠ notu)."""
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", chat_help_text(binary)) is not None


def binary_flag_values(binary: str, flag: str) -> list:
    """`chat --help`teki `[possible values: a, b]` listesi (bayrağın hemen ardındaki ilk). Bulunamazsa [] (= bilinmiyor)."""
    m = re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])[\s\S]*?\[possible values: ([^\]]*)\]", chat_help_text(binary))
    return [v.strip() for v in m.group(1).split(",") if v.strip()] if m else []


# `--max-context-kib` verilmezse bağlam tavanını modelin `/models` kaydından (bağlam penceresi + çıkış payı) türeten
# ucli'nin `chat --help`inde geçen ifade. Türetme ve bu yardım metni unified-cli `66a1004`te (2026-11-04) BİRLİKTE geldi;
# `--max-context-kib`in kendi yardım metni o commit'te güncellenmedi (hâlâ sağlayıcı sabitini anlatıyor), o yüzden
# bayrak varlığı değil bu ifade aranır. Daha eski ikili bayraksız açılırsa sabit 256 KiB'ye düşerdi.
_DERIVES_CONTEXT_MARK = "advertises a large window"


def binary_derives_context(binary: str) -> bool:
    """ucli bağlam tavanını modelden kendisi türetiyor mu (bkz. `_DERIVES_CONTEXT_MARK`)."""
    return _DERIVES_CONTEXT_MARK in chat_help_text(binary)


def build_chat_argv(
    binary: str,
    root: str,
    *,
    repl: bool,
    session: Optional[str],
    model: Optional[str],
    endpoint: Optional[str],
    api_key_env: str,
    with_mcp: bool,
    max_steps: Optional[int],
    extra_args: Sequence[str] = (),
) -> list[str]:
    argv = [binary, "--root", root, "chat"]
    if repl:
        argv.append("--repl")
    if session:
        argv += ["--session", session]
    if model:
        argv += ["--model", model]
    if endpoint:
        argv += ["--endpoint", endpoint]
    if api_key_env:
        argv += ["--api-key-env", api_key_env]
    if with_mcp:
        argv.append("--with-mcp")
    if max_steps is not None:
        argv += ["--max-steps", str(max_steps)]
    argv += [str(a) for a in extra_args]   # çağıranın ek bayrakları (ör. reviewer: --max-io-mib); prompt'tan ÖNCE
    return argv


def _subprocess_env(api_key_env: str, api_key: Optional[str]) -> Optional[Dict[str, str]]:
    """`api_key` verilirse (ör. bir web formundan) `subprocess`'e geçilecek
    TAM env kopyası — `api_key_env` adlı değişkeni ekler/override eder,
    sürecin kendi ortamına kalıcı yazmaz. `api_key` verilmezse None (=
    `Popen`/`run`'ın kendi varsayılanı: ebeveyn env'i DEĞİŞTİRMEDEN miras al)
    — bugüne kadarki davranış birebir korunur, sadece YENİ bir çağıran
    (ör. web formu) açıkça bir anahtar geçtiğinde devreye girer."""
    if api_key is None:
        return None
    if not _SAFE_ENV_NAME_RE.fullmatch(api_key_env or ""):
        raise UcliError(f"invalid api_key_env name: {api_key_env!r}")
    return {**os.environ, api_key_env: api_key}


def _key_env_refusal(name: str) -> str:
    """TBD#401: tek atımlık çağrıda anahtar adı yalnız `UCLI_API_KEY` ya da ayarlarda tanımlı bir ucli hizmetinin `env`i
    olabilir (başka ad, ortamdaki herhangi bir değişkeni çağıranın verdiği uç noktaya "anahtar" diye gönderirdi). Boş metin =
    kabul; değilse ret metni (ad yankılanmaz: alana yanlışlıkla anahtar yapıştırılmış olabilir). `settings.json` var ama
    okunamıyor, normal dosya değil, bozuk ya da `ucli_services` liste değilse yalnız `UCLI_API_KEY`."""
    if name == "UCLI_API_KEY":
        return ""
    from . import settings
    stored: Any = None
    try:
        if os.path.exists(settings.SETTINGS_JSON) and not os.path.isfile(settings.SETTINGS_JSON):
            raise ValueError("normal dosya değil")      # FIFO/aygıt: açmak bloklar
        with open(settings.SETTINGS_JSON, encoding="utf-8") as f:
            stored = json.load(f)
    except FileNotFoundError:
        stored = {}
    except (OSError, ValueError, RecursionError):
        pass
    if not isinstance(stored, dict) or not isinstance(stored.get("ucli_services", []), list):
        return "api_key_env kabul edilmedi: settings.json okunamadı ya da bozuk, yalnız UCLI_API_KEY kullanılabilir"
    if name in {s["env"] for s in settings.normalize_ucli_services(stored.get("ucli_services"))}:
        return ""
    return "api_key_env kabul edilmedi: yalnız UCLI_API_KEY ya da ayarlarda tanımlı ucli hizmetlerinin anahtar adları"


def _redact(text: str, secret: Optional[str]) -> str:
    """Hata metnine / onay kaydına giren çocuk çıktısından API anahtarını siler (8 karakterden kısa değer anahtar sayılmaz)."""
    secret = (secret or "").strip()
    return text.replace(secret, "<redacted>") if len(secret) >= 8 else text


def _effective_key(api_key_env: str, api_key: Optional[str]) -> Optional[str]:
    """Çocuğun göreceği anahtar: açıkça verilen, yoksa miras alınan ortam değişkeni."""
    return api_key if api_key is not None else os.environ.get(api_key_env or "")


STATE_ROOT = os.path.expanduser("~/.claude/claudeops/ucli-state")


def state_dir_for(cwd: str) -> str:
    """`ucli chat --state-dir`e verilecek kök-başına dizin (depo DIŞI): `<STATE_ROOT>/<ad>-<sha1(gerçek kök)[:10]>`. Aynı kök
    her zaman aynı dizin; farklı köklerin (aynı ada sahip bile olsa) dizini ayrı. Ortak kök salt okunursa (ikinci örnek,
    TBD#412 b) `<CLAUDEOPS_DIR>/ucli-state` altı: ucli bu dizine YAZAR."""
    real = os.path.realpath(cwd)
    base = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(real.rstrip(os.sep)) or "root")[:40]
    root = STATE_ROOT if _paths.shared_write_allowed(STATE_ROOT) else os.path.join(_paths.CLAUDEOPS_DIR, "ucli-state")
    return os.path.join(root, f"{base}-{hashlib.sha1(real.encode('utf-8')).hexdigest()[:10]}")


def legacy_chat_dir(cwd: str) -> str:
    return os.path.join(cwd, ".ucli", "chat")


def chat_session_dirs(cwd: str) -> List[str]:
    """Okuyucuların sırayla bakacağı dizinler. `--state-dir` açıksa (ayar) yeni dizin ÖNCE, eski `<kök>/.ucli/chat` ARKADAN
    (açılmadan önce yazılmış / eski oturumlar); kapalıysa yalnız eski AMA yeni dizinde dosya zaten varsa o da (ayar kapatılsa
    bile o dizindeki canlı oturum okunsun)."""
    from .settings import ucli_state_dir_enabled
    new, old = state_dir_for(cwd), legacy_chat_dir(cwd)
    dirs = [new, old] if (ucli_state_dir_enabled() or os.path.isdir(new)) else [old]
    shared = os.path.join(STATE_ROOT, os.path.basename(new))
    if shared != new and os.path.isdir(shared):    # ikinci örnek: ortak durum dizini yalnız OKUNUR, en arkada
        dirs.append(shared)
    return dirs


def find_chat_file(cwd: str, filename: str) -> str:
    """`filename`in (`NAME.jsonl`, `NAME.status.json`) var olan ilk yolu; yoksa birincil dizindeki yol (yoksunluk çağıranda)."""
    dirs = chat_session_dirs(cwd)
    for d in dirs:
        path = os.path.join(d, filename)
        if os.path.exists(path):
            return path
    return os.path.join(dirs[0], filename)


def chat_session_dir(cwd: str) -> str:
    """`.ucli/chat/*.jsonl`'ın yaşadığı proje-başına dizin — `io_providers/
    ucli_provider.py` (tmux'suz `IoProvider`) ve `providers/ucli_provider.py`
    (tmux-backed `CliProvider`) AYNI klasörü/dosya biçimini okur: ikisi de aynı
    `--session NAME` kavramını paylaşıyor, sadece süreç yönetimi (Python'ın
    kendi pipe'ı vs. tmux pane) farklı."""
    return chat_session_dirs(cwd)[0]


def failed_turn_records(cwd: str, session: str) -> list:
    """`<chat dizini>/failed/<oturum>-<unix>-<n>.json` kayıtları (ucli `259593e`: model çağrısına varmış bir tur hatayla
    ölünce yazılır): `[(unix, yol)]` eskiden yeniye. Ad AYRIŞTIRILIR (`rsplit("-", 2)`), ön ek eşlemesi YOK: `cli` oturumu
    `cli-2` oturumunun kaydını saymaz. Dizin yok/okunamıyorsa boş liste (asla fırlatmaz)."""
    out = []
    for d in chat_session_dirs(cwd):
        fd = os.path.join(d, "failed")
        try:
            names = os.listdir(fd)
        except OSError:
            continue
        for nm in names:
            if not nm.endswith(".json"):
                continue
            parts = nm[:-5].rsplit("-", 2)
            # `isdecimal`: `isdigit` üst simgeyi de kabul eder, `int()` onda istisna atıp TÜM kayıtları gizliyordu
            if len(parts) != 3 or parts[0] != session or not parts[1].isdecimal() or not parts[2].isdecimal():
                continue
            out.append((int(parts[1]), int(parts[2]), os.path.join(fd, nm)))
    out.sort()
    return [(u, p) for u, _n, p in out]


def archive_session_files(cwd: str, session: str, stamp: Optional[int] = None) -> List[str]:
    """`fresh=True` ucli başlatması YENİ konuşma açsın diye: `<session>.jsonl` + `<session>.status.json`i her sohbet dizininde
    (yeni `--state-dir` ve eski `<kök>/.ucli/chat`) `<dizin>/archive/<session>.<stamp>.<uzantı>` altına TAŞIR (silmez).
    Oturum ADI değişmez (sid = ad; read_status_file/read_chat_history/jsonl okuyucuları aynen çalışır); `archive/` alt dizini
    `*.jsonl` glob'larına (io_providers) görünmez. Taşınan yolların listesini döner; fırlatmaz. ÇAĞIRAN oturum çalışmıyorken çağırmalı."""
    import time as _time
    if not session or not re.fullmatch(r"[A-Za-z0-9_.-]+", session) or session in (".", ".."):
        return []
    ts = int(stamp if stamp is not None else _time.time())
    moved: List[str] = []
    try:
        dirs = chat_session_dirs(cwd)
    except Exception:
        return moved
    for d in dirs:
        for suffix in (".jsonl", ".status.json"):
            src = os.path.join(d, session + suffix)
            if not os.path.isfile(src):
                continue
            try:
                adir = os.path.join(d, "archive")
                os.makedirs(adir, exist_ok=True)
                dst = os.path.join(adir, f"{session}.{ts}{suffix}")
                n = 1
                while os.path.exists(dst):
                    dst = os.path.join(adir, f"{session}.{ts}_{n}{suffix}")
                    n += 1
                os.replace(src, dst)
                moved.append(dst)
            except OSError:
                continue
    return moved


def status_is_busy(status: Dict[str, Any]) -> bool:
    """Durum dosyası meşgul mü: `waiting_for_stdin` = boşta; öteki üç değer (waiting_for_model/running_tool/waiting_for_user)
    bir turu işliyor demek. Meşgul kuralı TEK yer (`UcliProvider.live_busy` + `web_agents._state`)."""
    return status.get("activity") != "waiting_for_stdin"


def read_status_file(cwd: str, session: str) -> Optional[Dict[str, Any]]:
    """`{session}.status.json`'ı ayrıştırır (unified-cli'nin `--status-file`'ı,
    2026-10-04'te `ucli chat --help`'te fark edildi — `chat --repl --session
    NAME --status-file`, kendi docstring'i "e.g. claudeops" diyor, TAM BU
    OKUMA için eklenmiş). Şekil: `{"schema_version":1,"pid":...,
    "activity":"waiting_for_stdin"|"waiting_for_model"|"running_tool"|
    "waiting_for_user","tool":...,"model":...,"provider":...,"endpoint":...,
    "turns":...,"context_bytes":...,"io_bytes_used":...,"external_tools":[...],
    "last_activity_unix":...}` (unified-cli `crates/ucli/src/status.rs`).
    Dosya YOK/bozuk/eski bir crash'ten kalmış olabilir (ucli bunu normal
    `/exit`'te siler ama crash/kill'de BİLEREK silmez — kendisi de bir sinyal,
    bkz. status.rs) — hiçbiri hata sayılmaz, hepsinde `None` (çağıran
    pane-capture'a düşsün)."""
    if "/" in str(session) or "\0" in str(session):      # yol parçası olamayan ad: oturum dizininin dışı okunmaz
        return None
    path = find_chat_file(cwd, f"{session}.status.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, RecursionError):     # bozuk JSON/UTF-8, dev sayı, aşırı derin yapı
        return None
    return data if isinstance(data, dict) else None


# Evren kotada önbellekli prompt tokenini 0,03, önbelleksizi 1,0 sayar (unified-cli `bench/token-economy`,
# 2026-10-16/17: panonun "Toplam token"ı ikisini de 1,0 sayar ve hesap KOTASI değildir; koşu A'da pano 12,8M, kota
# 0,93M). `completion_tokens` akıl yürütmeyi içerir (durum dosyasında `reasoning_tokens` onun alt kümesi).
QUOTA_CACHED_WEIGHT = 0.03


def quota_equivalent_tokens(usage: Dict[str, int]) -> int:
    """Durum dosyası `usage`ından (bkz. `CliProvider.live_usage`) Evren kotasına yansıyan token: önbelleksiz girdi +
    önbellekli girdi x `QUOTA_CACHED_WEIGHT` + çıktı. `cached_tokens` `prompt_tokens`ın parçasıdır; bozuk bir dosya
    yüzünden büyük çıkarsa girdiyi aşamaz. TABANDIR: `reported < requests` / `unmetered > 0` iken gerçek değer yüksek olabilir."""
    prompt = max(0, int(usage.get("prompt_tokens", 0)))
    cached = min(prompt, max(0, int(usage.get("cached_tokens", 0))))
    completion = max(0, int(usage.get("completion_tokens", 0)))
    return round((prompt - cached) + QUOTA_CACHED_WEIGHT * cached + completion)


def usage_warn_level(quota_tokens: int, amber: int, red: int) -> int:
    """0 = uyarı yok, 1 = amber, 2 = kırmızı. Eşik 0 = o kademe kapalı. Kırmızı önce bakılır, böylece yanlışlıkla
    red < amber yazılsa da en ağır geçerli kademe kazanır."""
    if red > 0 and quota_tokens >= red:
        return 2
    if amber > 0 and quota_tokens >= amber:
        return 1
    return 0


def read_chat_history(cwd: str, session: str) -> Optional[List[Dict[str, str]]]:
    """`{session}.jsonl`'ı `[{"role":..., "text":...}, ...]`'a çevirir.
    Dosya yoksa boş liste (henüz mesaj yok, hata değil) — okunamaz/bozuksa
    `None` (çağıran "desteklenmiyor" ile "henüz mesaj yok"u ayırabilsin).
    Yazım sürerken yarım kalan SON satır (satır sonu yok ve ayrışmıyor) atlanır; tamamlanmış bozuk satır yine `None`.

    Yeni ucli sürümlerinde dosyanın ilk satırı `{"ucli_session_schema_version":1}` başlığı
    (`role` yok): eskiden `KeyError` → `None` → panel ucli sohbetini "desteklenmiyor" diye
    gösteriyordu (2026-10-14, Geçmiş'te "chat görünmüyor"); `role`süz satır atlanır."""
    return _read_turns(cwd, session)[0]


def _read_turns(cwd: str, session: str):
    """`read_chat_history`nin gövdesi: `(turlar | None, yarım son satır atlandı mı)`."""
    if "/" in str(session) or "\0" in str(session):      # yol parçası olamayan ad: okunamaz sayılır, oturum dizininin dışı okunmaz
        return None, False
    path = find_chat_file(cwd, f"{session}.jsonl")
    if not os.path.isfile(path):
        return [], False
    turns: List[Dict[str, str]] = []
    try:
        with open(path, encoding="utf-8", errors="surrogateescape") as f:
            for raw in f:
                try:
                    raw.encode("utf-8")         # bozuk bayt: `UnicodeEncodeError` (`ValueError`)
                    line = raw.strip()
                    if not line:
                        continue
                    turn = json.loads(line)
                except (ValueError, RecursionError):
                    return (None, False) if raw.endswith("\n") else (turns, True)
                if not isinstance(turn, dict) or "role" not in turn:
                    continue
                turns.append({"role": turn["role"], "text": turn["content"]})
    except (OSError, KeyError):
        return None, False
    return turns, False


_BUDGET_NOTES = {
    "failures": "ucli art arda başarısız araç çağrıları yüzünden takıldı; aşağıdaki cevap KISMİ, işi bitirmedi",
}


def mark_budget_exhausted(value: Dict[str, Any]) -> Dict[str, Any]:
    """563: cevapta `budget_exhausted` (ör. \"failures\") varsa kısmi cevap tam cevap gibi okunmasın: `answer`ın başına
    bir uyarı satırı eklenir (bir kez; zaten eklenmişse dokunmaz). Alan yoksa/boşsa değer AYNEN döner."""
    why = value.get("budget_exhausted") if isinstance(value, dict) else None
    if not why:
        return value
    note = "[⚠ " + _BUDGET_NOTES.get(str(why), f"ucli bütçesi tükendi ({why}); cevap KISMİ olabilir") + "]"
    ans = value.get("answer")
    if isinstance(ans, str) and not ans.startswith("[⚠ "):
        value["answer"] = f"{note}\n{ans}"
    return value


def _parse_turn(line: str) -> Dict[str, Any]:
    line = line.strip()
    if not line:
        raise UcliError("ucli hiçbir çıktı vermeden kapandı")
    try:
        value = json.loads(line)
    except json.JSONDecodeError as e:
        raise UcliError(f"ucli çıktısı tek-satır JSON değildi: {e}\nsatır={line!r}") from e
    if "error" in value:
        raise UcliError(value["error"])
    return mark_budget_exhausted(value)


def ucli_chat_once(
    root: str,
    prompt: str,
    *,
    session: Optional[str] = None,
    model: Optional[str] = None,
    endpoint: Optional[str] = None,
    api_key_env: str = "UCLI_API_KEY",
    api_key: Optional[str] = None,
    with_mcp: bool = False,
    max_steps: Optional[int] = None,
    binary: Optional[str] = None,
    timeout: float = 120.0,
    extra_args: Sequence[str] = (),
    approval_run_key: Optional[str] = None,
    approval_owner: str = "",
) -> Dict[str, Any]:
    """Tek görev, tek process. `approval_run_key` verilirse (`--ask-edit --allow-edit` çağıranın `extra_args`'ında olmalı) iş onay beklemez:
    ucli 75 ile çıkıp `{"suspended":...}` basarsa sonuç hata SAYILMAZ, koşu `ucli_approval` kaydına `suspended` yazılır ve
    `{"status":"suspended","run_key","approval_id"}` döner (docs/ucli-approval-design.md S2). Sürdürme argv'si (prompt'suz) kayda yazılır.

    Dönen dict `{"answer", "model_rounds",
    "tool_calls"}` (`AgentAnswer`, agent.rs) — `chat` (repl'siz) hep pretty-
    printed JSON yazar ama `json.loads` boşluğa bakmaz, framing derdi yok
    (process ömrü boyunca TEK değer). `api_key` verilirse (çağıranın kendi
    ortamına güvenmek yerine, ör. bir web formundan) bkz. `_subprocess_env`. `api_key_env`: bkz. `_key_env_refusal`."""
    refusal = _key_env_refusal(api_key_env)     # her şeyden önce: alt süreç yok, ortam okunmaz
    if refusal:
        raise UcliError(refusal)
    if len(prompt) > 1 and prompt.startswith("-"):   # prompt konumsal argüman: `-` ile başlarsa ucli bayrak sayar (izin enjeksiyonu)
        raise UcliError("prompt '-' ile başlayamaz (ucli bayrak sanır)")
    bin_path = resolve_binary(binary)
    extra: list[str] = []
    if session:
        # Oturum durumu (jsonl/kilit) depo dışına: ayar açık, ikili bayrağı tanıyor ve geçmişi eski dizinde olan bir oturum değilse
        # (o, eskisi gibi sürer: yeni dizinle açılırsa konuşma geçmişi görünmez olurdu). Sağlayıcıdaki `_state_dir_args` ile aynı kural.
        from .settings import ucli_state_dir_enabled
        sdir = state_dir_for(root)
        in_new = os.path.exists(os.path.join(sdir, f"{session}.jsonl"))
        in_old = os.path.exists(os.path.join(legacy_chat_dir(root), f"{session}.jsonl"))
        if (ucli_state_dir_enabled() or in_new) and not (in_old and not in_new) and binary_supports_flag(bin_path, "--state-dir"):
            extra = ["--state-dir", sdir]
    approval_dir = ""
    if approval_run_key:
        from . import ucli_approval
        if not binary_supports_flag(bin_path, "--approval-dir"):
            raise UcliError("ucli ikilisi --approval-dir bayrağını tanımıyor (onay kanalı yarım uygulanmaz)")
        if not ucli_approval._slot_free(ucli_approval._load_index(), approval_run_key):
            raise UcliError(f"run_key kullanımda (bitmemiş onay koşusu var): {approval_run_key!r}")
        try:
            approval_dir = ucli_approval.dir_for(approval_run_key, create=True)
        except (ValueError, OSError) as e:
            raise UcliError(str(e)) from e
        extra = list(extra) + ["--approval-dir", approval_dir]
    argv = build_chat_argv(
        bin_path, root, repl=False, session=session, model=model,
        endpoint=endpoint, api_key_env=api_key_env, with_mcp=with_mcp,
        max_steps=max_steps, extra_args=list(extra) + [str(a) for a in extra_args],
    )
    argv_resume = list(argv)             # prompt'tan ÖNCEKİ bayraklar: `--resume-approval ID` bunlarla (gizli değer yok: anahtar ortamdan)
    argv.append(prompt)
    env = _subprocess_env(api_key_env, api_key)
    secret = _effective_key(api_key_env, api_key)
    try:
        result = _run_grouped(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        raise UcliError(f"ucli {timeout}s içinde cevap vermedi") from e
    except UnicodeDecodeError:
        raise UcliError("ucli çıktısı UTF-8 değildi") from None
    except OSError as e:
        raise UcliError(f"ucli çalıştırılamadı: {e}") from e
    except ValueError:              # argv/env içinde NUL ya da kodlanamayan karakter; metin değeri taşıyabilir, eklenmez
        raise UcliError("ucli çalıştırılamadı: geçersiz argüman ya da ortam değeri") from None
    if approval_run_key and result.returncode == 75:
        from . import ucli_approval
        susp = ucli_approval.parse_suspended(result.stdout)
        if susp:
            try:
                ucli_approval.register(approval_run_key, root, session or "", argv_resume, owner=approval_owner)
                ucli_approval.set_state(approval_run_key, "suspended")
            except (OSError, ValueError) as e:        # kayıt yoksa koşu sürdürülemez: sessizce düşmesin (TBD#383)
                _diag_approval(approval_run_key, e)
                raise UcliError(f"ucli koşusu onay bekliyor (onay {susp['id']}) ama kayıt yazılamadı: {e}") from e
            return {"ok": True, "status": "suspended", "run_key": approval_run_key, "approval_id": susp["id"]}
    if result.returncode != 0:
        raise UcliError(_redact(result.stderr.strip(), secret) or f"ucli exit={result.returncode}")
    try:
        value = json.loads(result.stdout)
    except (ValueError, RecursionError) as e:
        raise UcliError(f"ucli çıktısı JSON değildi: {e}\nstdout={_redact(result.stdout, secret)!r}") from None
    if not isinstance(value, dict):
        raise UcliError(f"ucli çıktısı JSON nesnesi değildi: stdout={_redact(result.stdout, secret)!r}")
    if "error" in value:
        raise UcliError(_redact(str(value["error"]), secret))
    return mark_budget_exhausted(value)


class UcliReplSession:
    """`ucli chat --repl` etrafında ince bir sarmalayıcı — TEK process,
    stdin/stdout PIPE (tmux YOK, ANSI/capture-pane derdi yok).

    Arka planda TEK kalıcı reader thread stdout'u bir `Queue`'ya pompalar
    (session ömrü boyunca) — `ask()` başına thread AÇMIYOR: iki thread'in
    aynı stdout'u eşzamanlı okuması, bir timeout'tan SONRA gecikmiş cevabın
    bir SONRAKİ `ask()`'e yanlış eşlenmesi riski taşırdı. Onun yerine bir
    `ask()` timeout'a uğrarsa process'i doğrudan öldürür (`_ask` bkz.) —
    protokolün request-id'si yok, gecikmiş bir cevabı güvenle "bu turdu"
    diye damgalamanın yolu yok, o yüzden kurtarmaya çalışmak yerine session'ı
    kesin-ölü sayıyoruz.

    Thread-safe: `ask()` kilit tutuyor, paralel çağrılar sıraya girer
    (aynı process'e paralel yazmak/okumak zaten anlamsız — ucli turları TEK
    process içinde sıralı işliyor).
    """

    def __init__(
        self,
        root: str,
        *,
        session: Optional[str] = None,
        model: Optional[str] = None,
        endpoint: Optional[str] = None,
        api_key_env: str = "UCLI_API_KEY",
        api_key: Optional[str] = None,
        with_mcp: bool = False,
        max_steps: Optional[int] = None,
        binary: Optional[str] = None,
    ) -> None:
        argv = build_chat_argv(
            resolve_binary(binary), root, repl=True, session=session, model=model,
            endpoint=endpoint, api_key_env=api_key_env, with_mcp=with_mcp,
            max_steps=max_steps,
        )
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=_subprocess_env(api_key_env, api_key),
        )
        self._lock = threading.Lock()
        self._lines: "queue.Queue[str]" = queue.Queue()
        self._reader = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader.start()
        # stderr BOŞALTILMAZSA boru dolunca (~64 KiB) ucli yazarken bloklanır ve cevap hiç gelmez: ayrı iş parçacığı sürekli
        # okur, yalnız son ~16 KiB'ı tutar (süreç ölünce hata iletisine girer).
        self._err_tail: "collections.deque[str]" = collections.deque()
        self._err_len = 0
        self._err_reader = threading.Thread(target=self._pump_stderr, daemon=True)
        self._err_reader.start()

    _ERR_KEEP = 16 * 1024

    def _pump_stderr(self) -> None:
        if self._proc.stderr is None:
            return
        for line in self._proc.stderr:
            self._err_tail.append(line)
            self._err_len += len(line)
            while self._err_len > self._ERR_KEEP and len(self._err_tail) > 1:
                self._err_len -= len(self._err_tail.popleft())

    def _stderr_text(self) -> str:
        self._err_reader.join(timeout=1.0)      # süreç kapandıysa boru EOF verir; takılırsa eldekini kullan
        return "".join(self._err_tail)

    def _pump_stdout(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self._lines.put(line)
        self._lines.put("")  # EOF sentinel — ucli'nin gerçek turları hiç boş satır basmaz

    def ask(self, prompt: str, timeout: float = 120.0) -> Dict[str, Any]:
        prompt_line = prompt.strip()
        if not prompt_line:
            raise UcliError("boş prompt gönderilemez (ucli --repl boş satırları atlar, cevap gelmez)")
        if "\n" in prompt:
            raise UcliError(
                "prompt tek satır olmalı (--repl stdin'i satır satır okur); "
                "çok satırlı metni çağıran kendi kararıyla tek satıra indirsin"
            )
        if prompt_line == "/exit":
            raise UcliError("'/exit' ask() ile gönderilmez, close() kullan")
        with self._lock:
            if self._proc.poll() is not None:
                raise UcliError(f"ucli repl process zaten kapanmış (exit={self._proc.returncode})")
            assert self._proc.stdin is not None
            self._proc.stdin.write(prompt_line + "\n")
            self._proc.stdin.flush()
            try:
                line = self._lines.get(timeout=timeout)
            except queue.Empty:
                self._proc.kill()  # bkz. sınıf docstring'i: gecikmiş cevabı güvenle eşleyemeyiz
                raise UcliError(f"ucli {timeout}s içinde cevap vermedi, session öldürüldü")
        if line == "":
            raise UcliError(f"ucli repl beklenmedik şekilde kapandı: {self._stderr_text().strip()}")
        return _parse_turn(line)

    def close(self, timeout: float = 5.0) -> None:
        if self._proc.poll() is not None:
            return
        try:
            with self._lock:
                if self._proc.stdin:
                    self._proc.stdin.write("/exit\n")
                    self._proc.stdin.flush()
            self._proc.wait(timeout=timeout)
        except Exception:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=timeout)
            except Exception:
                self._proc.kill()

    def __enter__(self) -> "UcliReplSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def ucli_resume_approval(run_key: str, approval_id: str, *, timeout: float = 1800.0, api_key: Optional[str] = None) -> Dict[str, Any]:
    """Cevabı yazılmış askıdaki koşuyu sürdürür (docs/ucli-approval-design.md S3). Argv KAYITTAN (`begin_resume`), istekten değil.
    Sonuç kayda yazılır: bitti -> `done`, yine 75 + suspended -> `suspended` (yeni kimlik; zincir), hata -> `done` + error.
    Hiçbir yolda istisna fırlatmaz (onay kaydı kilitlenemez/yazılamazsa da `ok: False`)."""
    try:
        return _resume_approval(run_key, approval_id, timeout, api_key)
    except OSError as e:
        _diag_approval(run_key, e)
        return {"ok": False, "error": f"approval record not written: {e}"[:300]}


def _diag_approval(run_key: str, e: BaseException) -> None:
    from .diaglog import diag_log
    diag_log("ucli_approval_record_failed", run_key=run_key, error=f"{type(e).__name__}: {e}"[:200])


def _resume_approval(run_key: str, approval_id: str, timeout: float, api_key: Optional[str]) -> Dict[str, Any]:
    from . import ucli_approval
    argv = ucli_approval.begin_resume(run_key)
    if argv is None:
        return {"ok": False, "error": "run is not suspended"}
    try:
        return _run_resume(run_key, approval_id, argv, timeout, api_key)
    except OSError:         # yalnız sonuç yazımı fırlatır: süreç çalıştı, aynı onay yeniden sürdürülmesin
        ucli_approval._mark_consumed(run_key)
        raise


def _run_resume(run_key: str, approval_id: str, argv: List[str], timeout: float, api_key: Optional[str]) -> Dict[str, Any]:
    from . import ucli_approval
    try:
        api_key_env = argv[argv.index("--api-key-env") + 1] if "--api-key-env" in argv else "UCLI_API_KEY"
        result = _run_grouped(argv + ["--resume-approval", approval_id], capture_output=True, text=True, timeout=timeout,
                              env=_subprocess_env(api_key_env, api_key))
    except Exception as e:      # noqa: BLE001  (zaman aşımı dahil)
        ucli_approval.set_result(run_key, "done", {"error": f"{type(e).__name__}: {e}"[:300]})
        return {"ok": False, "error": "resume failed"}
    if result.returncode == 75:
        susp = ucli_approval.parse_suspended(result.stdout)
        if susp:
            ucli_approval.set_result(run_key, "suspended", {"status": "suspended", "approval_id": susp["id"]})
            return {"ok": True, "status": "suspended", "approval_id": susp["id"]}
    if result.returncode != 0:
        err = _redact(result.stderr.strip(), _effective_key(api_key_env, api_key))
        ucli_approval.set_result(run_key, "done", {"error": (err or f"ucli exit={result.returncode}")})
        return {"ok": False, "error": "ucli failed"}
    try:
        value = json.loads(result.stdout)
    except ValueError:
        ucli_approval.set_result(run_key, "done", {"error": "ucli output was not JSON"})
        return {"ok": False, "error": "bad output"}
    ucli_approval.set_result(run_key, "done", {"answer": str(value.get("answer") or ""), "error": str(value.get("error") or "")})
    return {"ok": True, "status": "done"}
