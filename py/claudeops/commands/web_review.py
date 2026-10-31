"""reviewer değnekçi motoru (adım 2: yalnız iskelet).

`web_steward.tick_round`, rolü `reviewer` olan ve AÇIK kimlik için `tick_once`/`passive_scan`/kart/beyin/kapatma
yerine YALNIZ `review_tick(cfg)` çağırır. reviewer kimliği hiçbir tmux oturumuna dokunmaz (`web_steward._target` onu
her zaman reddeder), `projects.json`'a yazmaz (`steward.upsert_project`/`transfer_project` `ReviewerRefused`), beyni
yoktur (`brain_start` reddeder); havuzu `review_pool.json`, geçmişi `review_history.json` (`review.py` saf çekirdeği).

Adım 5'te doldurulacak: havuz eşitleme (`review.pool_sync`), sıradaki çift (`review.next_review`), Evren/agy
çalıştırıcıları (kendi `Popen`'ı, zaman aşımı, iptal), sonuç dosyası + bulgu çıkarımı.

Bu modül `web.py`'yi ve `web_steward`'ı İÇE AKTARMAZ (döngü yok; eylemler gerekirse geri çağrıyla verilir)."""
import codecs
import json
import os
import re
import signal
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import review as rv
from .. import review_remote as rr
from .. import review_store as rs
from .. import review_remote_run as rrun
from .. import steward as sw
from .. import steward_advance as sa
from .. import steward_lessons as sl
from .. import ucli_client

REVIEW_ENV_PREFIXES = ("CLAUDE", "GEMINI", "ANTIGRAVITY", "ANTHROPIC")   # spawn.py deseni: bu süreç kendi oturum kimliğini çocuğa sızdırmaz
KILL_GRACE_SECONDS = 10.0                                   # SIGTERM -> SIGKILL aralığı
AGY_LOG_DIR = os.path.expanduser("~/.gemini/antigravity-cli/log")
UCLI_KEY_FILE = os.path.expanduser("~/.claude/claudeops/ucli_api_key")
ANTHROPIC_REVIEW_KEY_FILE = os.path.expanduser("~/.claude/claudeops/anthropic_review_key")   # 600; videogen ürün anahtarı KULLANILMAZ
EVREN_MAX_STEPS = 200
EVREN_MAX_IO_MIB = 2048
STDERR_KEEP = 300
DELTA_KEEP_CHARS = 2_000_000    # IoLog'un bellekte tuttuğu akış metni üst sınırı (40 dk'lık koşu MB'larca delta üretir)
HEARTBEAT_SECONDS = 10.0            # testler küçültür

# Süreç geneli TEK çalıştırma kilidi (claudeops'un `_LOCK`'u ile ilgisi YOK, onu TUTMA). Çalışırken iş thread'inde tutulur.
_REVIEW_LOCK = threading.Lock()
_JOBS: Dict[str, "_Job"] = {}
_JOBS_LOCK = threading.Lock()
# Yuva kipi (`review_slots`): başlatmadan bitişe tutulan yuvalar (iş anahtarı -> (mod, yuva no)). Tek iş kipinde de iş
# buraya yazılır (iki kip arası geçişte biri ötekini görür). `_SWEEPING`: şu an yetim oturumu süpürülen uzak projeler.
_SLOT_LOCK = threading.Lock()
_ACTIVE: Dict[str, Tuple[str, int]] = {}
_SWEEPING: set = set()


class _Job:
    def __init__(self, key: str) -> None:
        self.key = key
        self.proc: Any = None
        self.cancelled = False
        self.sid = ""                # işi başlatan reviewer kimliği
        self.prompt = ""
        self.locked = False          # tek iş kipinde `_REVIEW_LOCK`u tutuyor


def _take_slot(key: str, project: str, mode: str, slots: Dict[str, int]) -> Tuple[int, str]:
    """(yuva no, "") ya da (-1, neden). `slots` boş = tek iş kipi (başka iş varsa red). Yuva kipinde: mod yuvası dolu/0,
    aynı PROJE başka koşuda (ortak yerel kopya/cwd) ya da süpürülüyorsa red. Yuva no modun boş en küçük numarası."""
    with _SLOT_LOCK:
        if key in _ACTIVE or project in _SWEEPING:
            return -1, "bu proje için review çalışıyor"
        if not slots:
            if _ACTIVE:
                return -1, "başka bir review çalışıyor"
        else:
            cap = slots.get(mode, 1)
            if cap <= 0:
                return -1, f"{mode} kapalı (0 yuva)"
            if any(k.split("|", 1)[0] == project for k in _ACTIVE):
                return -1, "bu proje için review çalışıyor"
            used = {i for m, i in _ACTIVE.values() if m == mode}
            if len(used) >= cap:
                return -1, f"{mode} yuvaları dolu ({cap})"
        idx = min(set(range(len(_ACTIVE) + 1)) - {i for m, i in _ACTIVE.values() if m == mode})
        _ACTIVE[key] = (mode, idx)
        return idx, ""


def _release_slot(key: str) -> None:
    with _SLOT_LOCK:
        _ACTIVE.pop(key, None)


def active_slots() -> Dict[str, List[str]]:
    """{mod: [çalışan iş anahtarları]} (tüm kimlikler; başlamakta olanlar dahil)."""
    with _SLOT_LOCK:
        out: Dict[str, List[str]] = {}
        for k, (m, _i) in _ACTIVE.items():
            out.setdefault(m, []).append(k)
    return {m: sorted(v) for m, v in out.items()}


# ── ortam / argv ──────────────────────────────────────────────────────────────

def clean_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(REVIEW_ENV_PREFIXES)}
    if extra:
        env.update(extra)
    return env


def _api_key() -> str:
    from ..settings import byok_env_for
    key = (byok_env_for("ucli").get("UCLI_API_KEY") or "").strip()
    if not key:
        try:
            with open(UCLI_KEY_FILE) as f:
                key = f.read().strip()
        except OSError:
            key = ""
    return key


def _anthropic_review_key() -> str:
    try:
        with open(ANTHROPIC_REVIEW_KEY_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


def claude_argv(binary: str, model: str, effort: str, prompt: str, json_out: bool = False) -> List[str]:
    """`claude -p <prompt> --model M --effort E` salt okunur: yalnız Read/Grep/Glob + `ls|wc|head`; yazma araçları ve CLAUDE.md
    kapalı. Prompt `-p` DEĞERİ DEĞİL konumsal ilk argüman, çünkü `--allowedTools`/`--disallowedTools` değişken sayılıdır ve
    sonrakini yutar. Ölçüm (2026-10-23, ncs): haiku-5-5 low 88 sn / $0.017, sonnet-5-5 low 26 sn / $0.069."""
    argv = [binary, "-p", prompt, "--model", model]
    if effort:
        argv += ["--effort", effort]
    if json_out:        # reviewer koşusu: stdout tek JSON (result + usage); öz-doğrulama düz metin okur, bayrak onda yok
        argv += ["--output-format", "json"]
    return argv + ["--tools", "default", "--permission-mode", "dontAsk",
                   "--settings", json.dumps({"claudeMdExcludes": ["**/CLAUDE.md"], "autoMemoryEnabled": False}),
                   "--allowedTools", "Read", "Grep", "Glob", "Bash(ls:*)", "Bash(wc:*)", "Bash(head:*)",
                   "--disallowedTools", "Read(**/CLAUDE.md)", "Edit", "Write", "NotebookEdit", "Bash(*CLAUDE.md*)"]


def codex_argv(binary: str, cwd: str, model: str, effort: str, prompt: str) -> List[str]:
    """`codex exec -s read-only -C <cwd> -m M [-c model_reasoning_effort=E] <prompt>`: sandbox salt okunur (yazma/ağ yok);
    stdout yalnız son mesajdır, ilerleme stderr'e gider. Ölçüm: `-c model_reasoning_effort` olmadan config.toml'daki `max` uygulanır."""
    argv = [binary, "exec", "-s", "read-only", "--skip-git-repo-check", "-C", cwd, "-m", model]
    if effort:
        argv += ["-c", f"model_reasoning_effort={effort}"]
    return argv + [prompt]


# copilot: yalnız bu salt-okunur komutlar onaysız çalışır; yazma ve yıkıcı/ağ komutları açıkça reddedilir.
COPILOT_ALLOW_SHELL = ("ls", "grep", "head", "tail", "wc")
COPILOT_DENY_SHELL = ("rm", "mv", "cp", "curl", "wget", "sed", "find", "sh", "bash", "zsh", "python", "python3", "tee",
                      "awk", "perl", "ruby", "node", "xargs", "env", "nc", "ssh", "scp", "dd", "chmod", "chown", "ln", "touch",
                      "mkdir", "rmdir", "truncate", "git push", "git commit", "git checkout", "git apply", "git reset",
                      "git clean", "git stash", "git add")
# Asıl koruma izin listesi (`--allow-tool shell(ls)`...; başsız kipte listede olmayan komut sorulmaz); bu liste ikinci kat.
COPILOT_DENY = ("write",) + tuple(f"shell({c})" for c in COPILOT_DENY_SHELL)


def copilot_argv(binary: str, model: str, effort: str, prompt: str) -> List[str]:
    """`copilot -p <prompt> -s --model M [--reasoning-effort E] --no-ask-user --allow-tool shell(ls) ... --deny-tool write ...`.
    DOĞRULANMADI (2026-10-24: hesap aylık kotası dolu, canlı koşu yapılamadı): reddetme kuralları belgeye göre izinden önceliklidir
    (`--deny-tool` > `--allow-tool`); başsız kipte izinsiz aracın davranışı (hata mı, sessiz ret mi) canlı denenmedi."""
    argv = [binary, "-p", prompt, "-s", "--model", model, "--no-ask-user", "--disable-client-telemetry"]
    if effort:
        argv += ["--reasoning-effort", effort]
    for c in COPILOT_ALLOW_SHELL:
        argv += ["--allow-tool", f"shell({c})"]
    for d in COPILOT_DENY:
        argv += ["--deny-tool", d]
    return argv


def evren_argv(binary: str, cwd: str, model: str, prompt: str, endpoint: str, supports_io: bool,
               live_flags: Optional[List[str]] = None, budget_flags: Optional[List[str]] = None,
               create_dir: str = "") -> List[str]:
    """`ucli --root <cwd> chat --model M --endpoint E --api-key-env UCLI_API_KEY --max-steps 200 [--max-io-mib N] <prompt>`.
    --allow-edit/--allow-create ASLA (varsayılan salt okunur); anahtar argv'de DEĞİL, yalnız süreç ortamında.
    `live_flags` (`--stream`, `--show-reasoning`): yalnız stderr sunumu, stdout sözleşmesi ve yazma izni değişmez.
    `create_dir`: `--allow-create-dir DIR`, projenin DIŞINDA tek dizinde YALNIZ yeni dosya (raporun taslağı); proje içi salt okunur kalır."""
    return ucli_client.build_chat_argv(
        binary, cwd, repl=False, session=None, model=model, endpoint=endpoint, api_key_env="UCLI_API_KEY",
        with_mcp=False, max_steps=EVREN_MAX_STEPS,
        extra_args=(["--max-io-mib", str(EVREN_MAX_IO_MIB)] if supports_io else []) + list(budget_flags or []) + list(live_flags or [])
        + (["--allow-create-dir", create_dir] if create_dir else [])) + [prompt]


def agy_home(root: str, cwd: str, allow: Sequence[str], real_home: str = "", slot: int = 0) -> str:
    """Review'a özel İZOLE agy HOME'u (`<root>/agy_home`): kendi `settings.json`ı (yalnız salt-okunur komut izni, kullanıcının
    global ayarına/GEMINI.md'sine dokunmaz) + gerçek HOME'dan KOPYALANAN oturum belirteci. Belirteç her koşuda yeniden
    kopyalanır (agy içeride yenilerse gerçeğe yazılmaz). Gerçek ~/.gemini/antigravity-cli yoksa belirteçsiz kurulur.
    `slot` > 0 (eşzamanlı agy yuvası): ayrı `<root>/agy_home_<n>` (settings.json'daki cwd, günlük dizini ve TMPDIR koşu başına)."""
    real = os.path.join(real_home or os.path.expanduser("~"), ".gemini", "antigravity-cli")
    home = os.path.join(root, "agy_home" if slot <= 0 else f"agy_home_{slot}")
    cfg = os.path.join(home, ".gemini", "antigravity-cli")
    os.makedirs(cfg, mode=0o700, exist_ok=True)
    for name in ("antigravity-oauth-token", "installation_id"):
        try:
            shutil.copyfile(os.path.join(real, name), os.path.join(cfg, name))
            os.chmod(os.path.join(cfg, name), 0o600)
        except OSError:
            pass
    tmp = os.path.join(cfg, "settings.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rv.agy_settings(cwd, allow), f, indent=2)
    os.replace(tmp, os.path.join(cfg, "settings.json"))
    _prune_agy_tmp(os.path.join(home, "tmp"))
    return home


AGY_TMP_KEEP_SECONDS = 86400


def _prune_agy_tmp(tmp: str, now: Optional[float] = None) -> None:
    """Kafeste `/tmp` salt okunurdur; geçici dosya isteyen araçlar için `TMPDIR=<agy_home>/tmp` (yazılabilir). Agy'nin
    (ör. testleri koşturarak) biriktirdiği 1 günden eski kalıntılar her kurulumda silinir. Hata yutulur."""
    os.makedirs(tmp, mode=0o700, exist_ok=True)
    cut = (time.time() if now is None else now) - AGY_TMP_KEEP_SECONDS
    try:
        names = os.listdir(tmp)
    except OSError:
        return
    for n in names:
        fp = os.path.join(tmp, n)
        try:
            if os.path.getmtime(fp) < cut:
                shutil.rmtree(fp) if os.path.isdir(fp) and not os.path.islink(fp) else os.unlink(fp)
        except OSError:
            pass


def bwrap_jail(argv: List[str], home: str, bwrap: str) -> List[str]:
    """`bwrap --ro-bind / / --dev /dev --proc /proc --bind HOME HOME --unshare-pid --new-session --die-with-parent -- <argv>
    --dangerously-skip-permissions`: tüm dosya sistemi SALT OKUNUR (yalnız izole agy HOME'u yazılabilir), bu yüzden agy'nin
    her komutu onaysız çalışabilir ama proje/ev dizinine yazamaz ("Read-only file system", 2026-10-24 deneyle doğrulandı;
    izin listesi yaklaşımı agy'nin beklenmedik bir komutunda (`git status`) tüm koşuyu öldürüyordu). Ağ AÇIK kalır (API gerekli):
    yetki sınırı yazma, sızdırma değil. `argv[0]` agy ikilisidir; bayrak ondan hemen sonra eklenir."""
    return [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--bind", home, home,
            "--unshare-pid", "--new-session", "--die-with-parent", "--", argv[0], "--dangerously-skip-permissions"] + list(argv[1:])


def agy_argv(binary: str, model: str, prompt: str, provider: Any) -> List[str]:
    """`agy --print=<prompt> --model M [--effort E] --mode plan`.
    DOĞRULANMADI: `agy --print` kipinin araç (dosya okuma) kullanıp kullanmadığı ve `--mode plan`ın yazmayı gerçekten
    engelleyip engellemediği gerçek agy ile denenmedi; sonuç dosyasını yine BİZ yazarız, ama salt-okunurluk agy'ye güvenir."""
    argv = [binary, f"--print={prompt}", "--model", model]
    if model.startswith("gemini"):
        # agy'de effort model kimliğinin kademesi (`gemini-*-high`); kademesiz/gemini dışı modele --effort EKLENMEZ
        # (çatışan --effort modeli sessizce değiştirir, bkz. CLAUDE.md "Effort").
        if provider.model_effort_levels(model):
            eff = provider.resolve_effort(model, "high")
            if eff:
                argv += ["--effort", eff]
    return argv + ["--mode", "plan"]


def _agy_log_names(log_dir: str) -> frozenset:
    try:
        return frozenset(n for n in os.listdir(log_dir) if n.startswith("cli-") and n.endswith(".log"))
    except OSError:
        return frozenset()


def _first_new_agy_log(log_dir: str, since: float, exclude: Any = ()) -> str:
    """Koşu BAŞLANGICINDAN (mtime >= since) yeni ilk `cli-*.log` içeriği; yoksa "". `exclude`: koşu öncesi var olan
    günlük adları (hâlâ yazılan eski koşunun günlüğü yeni sanılmasın)."""
    try:
        cands = []
        for n in os.listdir(log_dir):
            if n.startswith("cli-") and n.endswith(".log") and n not in exclude:
                fp = os.path.join(log_dir, n)
                mt = os.path.getmtime(fp)
                if mt >= since - 1.0:
                    cands.append((mt, fp))
        for _mt, fp in sorted(cands):
            with open(fp, errors="replace") as f:
                return f.read()
    except OSError:
        pass
    return ""


# ── süreç yönetimi ────────────────────────────────────────────────────────────

def _killpg(proc: Any, sig: int) -> None:
    """YALNIZ kendi Popen'imizin grubu (`start_new_session` => pgid == pid). PID/ağaç taraması YOK."""
    ab = getattr(proc, "abort", None)
    if callable(ab):        # uzak review (RemoteReviewProc): gerçek süreç yok, uzak oturumu kapatır
        ab()
        return
    pid = getattr(proc, "pid", None)
    if not isinstance(pid, int) or pid <= 1:
        return
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _terminate(proc: Any, grace: float) -> None:
    _killpg(proc, signal.SIGTERM)
    try:
        proc.wait(timeout=grace)
    except Exception:
        _killpg(proc, signal.SIGKILL)
        try:
            proc.wait(timeout=5)       # SIGKILL sonrası biçer: zombi kalmasın
        except Exception:
            pass


def cancel_job(project: str, target: rv.ReviewTarget) -> bool:
    """Çalışan işi iptal eder: SIGTERM, `KILL_GRACE_SECONDS` sonra hâlâ yaşıyorsa SIGKILL. Çalışan iş yoksa False."""
    return cancel_key(rv.pair_key(project, target))


def cancel_key(key: str) -> bool:
    with _JOBS_LOCK:
        job = _JOBS.get(key)
    if job is None:
        return False
    job.cancelled = True
    if job.proc is None:      # süreç henüz oluşmadı: iptal işaretlendi, `_execute` süreci açar açmaz öldürür (yutulmaz)
        return True
    _killpg(job.proc, signal.SIGTERM)

    def _late() -> None:
        try:
            if job.proc.poll() is None:
                _killpg(job.proc, signal.SIGKILL)
        except Exception:
            pass
    t = threading.Timer(KILL_GRACE_SECONDS, _late)
    t.daemon = True
    t.start()
    return True


# ── kalıcı IO günlüğü (sohbet görünümü: <ts>.io.jsonl, review md'nin yanında) ──

IO_SUFFIX = ".io.jsonl"
IO_MAX_BYTES = 50 * 1024 * 1024     # kalıcı dosya üst sınırı; aşılınca ortası kırpılır (baş + son kalır, not düşülür)
IO_HEAD_BYTES = 1 * 1024 * 1024
IO_TAIL_BYTES = 24 * 1024 * 1024
LIVE_READ_BYTES = 512 * 1024        # GET yanıtı penceresi: dosyanın SON bu kadarı (kalıcı dosya sınırsız)
PREFIX = "UnifiedCLI "


def io_path_for(md_path: str) -> str:
    return (md_path[:-3] if md_path.endswith(".md") else md_path) + IO_SUFFIX


class IoLog:
    """Artımlı (her olayda açıp ekler: servis çökse de kaybolmaz), sırları temizlenmiş olay günlüğü, satır başına JSON
    `{ts, role: user|assistant|tool|system, kind, text}`. Dosya iş bitse/iptal/timeout olsa da SİLİNMEZ.
    stderr akışı (`feed_err`) satırlara ayrılır: `UnifiedCLI tool:` -> tool; `UnifiedCLI model:`/`reasoning:` ->
    assistant; diğer `UnifiedCLI ...` -> system; öneksiz metin (--stream delta) -> assistant `delta` (istemci birleştirir).
    Sondaki bölünmüş sözcük bir sonraki yazıya kadar tutulur ki bir sır iki parçaya bölünüp redact'ten kaçmasın."""

    def __init__(self, path: str, now: Callable[[], float] = time.time, max_bytes: int = IO_MAX_BYTES,
                 head: int = IO_HEAD_BYTES, tail: int = IO_TAIL_BYTES, err_as_delta: bool = True) -> None:
        self.path, self.now, self.max_bytes, self.head, self.tail = path, now, max_bytes, head, tail
        self.err_as_delta = err_as_delta    # False (claude/codex/agy/copilot): öneksiz stderr cevap DEĞİL, system/stderr satırı
        self._eline = ""
        self._lock = threading.RLock()
        self._buf = ""              # stderr satır birleştirici
        self._at_start = True
        self._hold = ""             # delta için tutulan sözcük kuyruğu
        self._learned: List[str] = []   # DSN'den öğrenilen parolalar: düz metinde de maskelenir
        self._deltas: List[str] = []    # akışla gelen cevap parçaları (maskeli): zaman aşımında rapor kurtarma kaynağı
        self._delta_chars = 0           # `_deltas` toplam uzunluğu (DELTA_KEEP_CHARS ile sınırlı: bellek)
        self.ok = True
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8"):
                pass
        except OSError:
            self.ok = False

    def event(self, role: str, text: str, kind: str = "") -> None:
        if not self.ok or not text:
            return
        with self._lock:
            for s in rv.dsn_passwords(text):
                if s not in self._learned:
                    self._learned.append(s)
            learned = list(self._learned)
        rec = {"ts": round(self.now(), 3), "role": role, "text": rv.redact_secrets(text, learned)}
        if kind:
            rec["kind"] = kind
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line)
                if os.path.getsize(self.path) > self.max_bytes:
                    self._trim()
            except OSError:
                self.ok = False

    def _trim(self) -> None:
        with open(self.path, "rb") as f:
            head = f.read(self.head)
            f.seek(-self.tail, os.SEEK_END)
            tail = f.read()
        nl = head.rfind(b"\n")
        head = head[:nl + 1] if nl >= 0 else b""
        nl = tail.find(b"\n")
        tail = tail[nl + 1:] if nl >= 0 else b""
        note = json.dumps({"ts": round(self.now(), 3), "role": "system", "kind": "trim",
                           "text": "(ortadaki çıktı boyut sınırı nedeniyle kırpıldı)"}, ensure_ascii=False) + "\n"
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(head + note.encode() + tail)
        os.replace(tmp, self.path)

    def system(self, msg: str) -> None:
        self.event("system", msg)

    def out(self, text: str) -> None:
        """stdout: ajan modunda tek JSON sonuç, agy'de düz cevap."""
        self.event("assistant", text, "result")

    def _delta(self, text: str, final: bool = False) -> None:
        with self._lock:
            buf = self._hold + text
            self._hold = ""
            if not final:
                m = re.search(r"\S+$", buf)
                if m:
                    self._hold, buf = buf[m.start():], buf[:m.start()]
            self.event("assistant", buf, "delta")
            if buf:
                red = rv.redact_secrets(buf, self._learned)
                self._deltas.append(red)
                self._delta_chars += len(red)
                while self._delta_chars > DELTA_KEEP_CHARS and len(self._deltas) > 1:   # rapor SONDA: en eskiler atılır
                    self._delta_chars -= len(self._deltas.pop(0))

    def learned(self) -> List[str]:
        """Akışta DSN'den öğrenilmiş parolalar (nihai rapor/taslak maskelemesi de bunları kullanır)."""
        with self._lock:
            return list(self._learned)

    def streamed_report(self) -> str:
        """Akışla gelen cevap metninden SON `## R-1 | P.. |` başlığından itibaren kısım (bulgu başlığı yoksa ""). Ucli
        stdout'a yalnız iş BİTİNCE JSON yazar; zaman aşımında rapor yarıda ama akışta durur (ncs, effort high, 40 dk)."""
        with self._lock:
            self._delta("", final=True)
            txt = "".join(self._deltas)
        starts = [m.start() for m in re.finditer(r"(?m)^#{2,4}\s*R-1\s*\|\s*P[123]\s*\|", txt)]
        if starts:
            return txt[starts[-1]:].strip()
        lines = [l.strip() for l in txt.splitlines() if l.strip()]
        if lines and re.fullmatch(r"(?i)(bulgu yok|no findings)\.?", lines[-1]):
            return lines[-1]                       # başlıksız "bulgu yok" raporu: SON satır tam bu ifadeyse
        return ""

    def feed_err(self, txt: str) -> None:
        with self._lock:
            self._buf += txt
            while self._buf:
                if self._at_start:
                    if self._buf.startswith(PREFIX):
                        i = self._buf.find("\n")
                        if i < 0:
                            break
                        line, self._buf = self._buf[:i], self._buf[i + 1:]
                        self._line(line[len(PREFIX):])
                        continue
                    if len(self._buf) < len(PREFIX) and PREFIX.startswith(self._buf):
                        break
                    self._at_start = False
                i = self._buf.find("\n")
                if i < 0:
                    self._plain(self._buf)
                    self._buf = ""
                    break
                self._plain(self._buf[:i + 1])
                self._buf = self._buf[i + 1:]
                self._at_start = True

    def _plain(self, txt: str, final: bool = False) -> None:
        """Öneksiz stderr metni: `--stream` Evren'de cevap parçası (delta); diğer modlarda hata/uyarı satırı (system)."""
        if self.err_as_delta:
            self._delta(txt, final=final)
            return
        self._eline += txt
        while True:
            i = self._eline.find("\n")
            if i < 0:
                break
            line, self._eline = self._eline[:i], self._eline[i + 1:]
            if line.strip():
                self.event("system", line, "stderr")
        if final and self._eline.strip():
            self.event("system", self._eline, "stderr")
        if final:
            self._eline = ""

    def _line(self, rest: str) -> None:
        for pre, role, kind in (("tool:", "tool", "call"), ("model:", "assistant", "model"),
                                ("reasoning:", "assistant", "reasoning")):
            if rest.startswith(pre):
                self.event(role, rest[len(pre):].strip(), kind)
                return
        self.event("system", PREFIX + rest, "ucli")

    def close(self) -> None:
        with self._lock:
            tail, self._buf = self._buf, ""
            if tail:
                if self._at_start and tail.startswith(PREFIX):
                    self._line(tail[len(PREFIX):])
                else:
                    self._plain(tail, final=True)
            self._plain("", final=True)


def _read_io_file(full: str, offset: Any) -> Dict[str, Any]:
    """Tam satırlarla, `offset` baytından; pencere son LIVE_READ_BYTES ile sınırlı. `events` ayrıştırılmış satırlar
    (bozuk satır -> system/raw olay, çökme yok)."""
    size = os.path.getsize(full)
    try:
        off = int(offset)
    except (TypeError, ValueError):
        off = 0
    reset = False
    if off < 0 or off > size:
        off, reset = 0, True
    if size - off > LIVE_READ_BYTES:
        off, reset = size - LIVE_READ_BYTES, True
    with open(full, "rb") as f:
        f.seek(off)
        data = f.read(size - off)
    if reset and off > 0:       # pencere satır ortasında başlamasın
        nl = data.find(b"\n")
        data = data[nl + 1:] if nl >= 0 else b""
        off = size - len(data)
    end = data.rfind(b"\n")    # yarım son satırı sonraki çekişe bırak
    data = data[:end + 1] if end >= 0 else b""
    events: List[Dict[str, Any]] = []
    for ln in data.decode("utf-8", "replace").splitlines():
        if not ln.strip():
            continue
        try:
            ev = json.loads(ln)
            if not isinstance(ev, dict):
                raise ValueError
        except ValueError:
            ev = {"role": "system", "kind": "raw", "text": ln}
        events.append(ev)
    return {"events": events, "offset": off + len(data), "size": size, "reset": reset or off == 0}


def read_io(cfg: Any, rel: str, offset: Any = 0) -> Dict[str, Any]:
    """GET `review/io?path=`: kimliğin `reviews/` ağacı altındaki `*.io.jsonl` (ya da onun `.md` eşi). Mutlak yol, `..`,
    NUL ve symlink kaçışı reddedilir."""
    p = sw.paths_for(cfg.sid)
    rel = str(rel or "")
    if not rel or "\x00" in rel:
        return {"ok": False, "error": "path required"}
    if rel.endswith(".md"):
        rel = io_path_for(rel)
    if not rel.endswith(IO_SUFFIX):
        return {"ok": False, "error": "not an io log"}
    root = os.path.realpath(p.reviews)
    cand = rel if os.path.isabs(rel) else os.path.join(p.reviews, rel)
    if ".." in rel.replace("\\", "/").split("/"):
        return {"ok": False, "error": "path outside reviews"}
    full = os.path.realpath(cand)
    if not full.startswith(root + os.sep):
        return {"ok": False, "error": "path outside reviews"}
    if not os.path.isfile(full):
        return {"ok": False, "error": "not found"}
    try:
        res = _read_io_file(full, offset)
    except OSError as e:
        return {"ok": False, "error": str(e)}
    res.update(ok=True, path=os.path.relpath(full, root))
    return res


def io_to_messages(events: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """IO olayları -> sohbet iletileri (`role` user|assistant|tool|system, `text`, `kind`). Ardışık `delta` parçaları tek
    assistant iletisinde birleşir; araç çağrıları/ucli satırları/düşünce `tool`/`system` (istemci katlar). Akışla gelmiş
    cevabın ardından gelen stdout sonucu tekrar gösterilmez; akışsızsa (agy ya da `--stream` yok) sonuç cevaptır
    (Evren JSON'unda `answer`)."""
    msgs: List[Dict[str, str]] = []
    streamed = False
    for ev in events:
        role, kind, text = str(ev.get("role") or "system"), str(ev.get("kind") or ""), str(ev.get("text") or "")
        if not text:
            continue
        if role == "assistant" and kind == "delta":
            streamed = True
            if msgs and msgs[-1]["role"] == "assistant" and msgs[-1].get("kind") == "delta":
                msgs[-1]["text"] += text
            else:
                msgs.append({"role": "assistant", "text": text, "kind": "delta"})
        elif role == "assistant" and kind == "result":
            if streamed:
                continue
            ans, _e = _extract_text("evren", text)
            msgs.append({"role": "assistant", "text": ans or text, "kind": "result"})
        elif role == "assistant" and kind == "reasoning":
            msgs.append({"role": "system", "text": text, "kind": "reasoning"})
        elif role in ("user", "assistant", "tool", "system"):
            msgs.append({"role": role, "text": text, "kind": kind})
        else:
            msgs.append({"role": "system", "text": text, "kind": kind})
    return msgs


def read_chat(cfg: Any, rel: str) -> Dict[str, Any]:
    """GET `review/chat?path=`: `read_io` ile aynı yol güvenliği; olaylar sohbet iletilerine çevrilir. `running` çift
    kaydındaki `io_file` ile eşleşen çalışan iş varsa True."""
    r = read_io(cfg, rel, 0)
    if not r.get("ok"):
        return r
    p = sw.paths_for(cfg.sid)
    hist = rv.load_history(p)
    running = False
    status = ""
    for key, rec in hist["pairs"].items():
        io = str((rec or {}).get("io_file") or "")
        if io and os.path.realpath(io) == os.path.realpath(os.path.join(p.reviews, r["path"])):
            status = str(rec.get("status") or "")
            running = key in running_keys(cfg.sid)
    msgs = io_to_messages(r.pop("events"))
    r.update(messages=msgs, total=len(msgs), running=running, status=status, supported=True)
    return r


def _pid_tree(root: Any) -> List[int]:
    """`root` pid'i + /proc'taki tüm torunları (koşan review sürecinin çocukları: agy/bwrap vb. panelde kendi satırıyla görünür).
    Okunamazsa yalnız kök; pid yoksa boş."""
    try:
        root = int(root)
    except (TypeError, ValueError):
        return []
    if root <= 0:
        return []
    kids: Dict[int, List[int]] = {}
    try:
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                with open(f"/proc/{name}/stat", "rb") as f:
                    raw = f.read().decode("utf-8", "replace")
                ppid = int(raw[raw.rindex(")") + 2:].split()[1])
            except (OSError, ValueError, IndexError):
                continue
            kids.setdefault(ppid, []).append(int(name))
    except OSError:
        return [root]
    out, todo = [], [root]
    while todo:
        cur = todo.pop()
        if cur in out:
            continue
        out.append(cur)
        todo.extend(kids.get(cur, []))
    return out


def review_runs(cfg: Any) -> List[Dict[str, Any]]:
    """History'de listelenecek review koşuları (kimlik başına): çift kayıtlarının son koşusu + `runs` geçmişindeki dosyalar;
    yalnız IO günlüğü diskte olanlar. `io` = `reviews/` altı göreli yol (istemci bunu `review/chat`e geri verir)."""
    p = sw.paths_for(cfg.sid)
    hist = rv.load_history(p)
    root = os.path.realpath(p.reviews)
    running = set(running_keys(cfg.sid))
    rows: Dict[str, Dict[str, Any]] = {}

    def add(pair: str, md: str, status: str, started: Any, finished: Any, is_run: bool, error: str = "", pid: Any = None) -> None:
        proj, _, tk = pair.partition("|")
        mode, _, slug = tk.partition("/")
        io = io_path_for(md) if md else ""
        if not io or not os.path.isfile(io):
            return
        rel = os.path.relpath(os.path.realpath(io), root)
        if rel.startswith(".."):
            return
        stamp = os.path.basename(md)[:14]
        ts = started if started else (stamp if re.fullmatch(r"\d{14}", stamp) else None)
        rows[rel] = {"sid": cfg.sid, "project": proj, "mode": mode, "model": slug, "status": status, "io": rel,
                     "file": md, "started_at": started, "finished_at": finished, "running": is_run,
                     "error": error, "duration": (float(finished) - float(started)) if started and finished else None,
                     "title": rv.review_title(proj, mode, slug, ts),
                     "pids": _pid_tree(pid) if is_run else []}
    for r in hist.get("runs") or []:
        if not isinstance(r, dict):
            continue
        # Rapor üretmeden biten koşuda (`error`/`timeout`/`limit`) `file` yoktur; IO günlüğünden `.md` yolu türetilir.
        md = str(r.get("file") or "") or (str(r["io_file"])[:-len(IO_SUFFIX)] + ".md" if r.get("io_file") else "")
        if md:
            add(str(r.get("pair") or ""), md, str(r.get("status") or ""), None, r.get("at"), False)
    for key, rec in hist["pairs"].items():
        if isinstance(rec, dict) and rec.get("io_file"):
            md = str(rec["io_file"])[:-len(IO_SUFFIX)] + ".md"
            add(key, md, str(rec.get("status") or ""), rec.get("started_at"), rec.get("finished_at"), key in running, str(rec.get("error") or ""), rec.get("pid"))

    def newest_first(r: Dict[str, Any]) -> Tuple[str, str]:
        # Yol `proje/mod/model/effort/<ts>/...` ile başlar: yola göre sıralamak projeleri/modelleri gruplar, zamanı DEĞİL.
        # Sıra koşunun zaman damgası (dosya adı `<14 hane>.md`); bilinmiyorsa en sona.
        stamp = os.path.basename(str(r.get("file") or ""))[:14]
        return (stamp if re.fullmatch(r"\d{14}", stamp) else "", r["io"])
    return sorted(rows.values(), key=newest_first, reverse=True)


def read_live(cfg: Any, project: str, target_key: str, offset: Any = 0) -> Dict[str, Any]:
    """GET `review/live`: çiftin son koşusunun IO günlüğü (`io_file` çift kaydında). Yol istemciden gelmez; `target` bilinen
    hedef anahtarı olmak zorunda. İş bitince de aynı çağrı son hâli döner (`running: false`)."""
    p = sw.paths_for(cfg.sid)
    proj = str(project or "").strip()
    match = [tg for tg in current_targets(cfg) if tg.key == str(target_key or "")]
    if not match or not proj:
        return {"ok": False, "error": "unknown target"}
    tg = match[0]
    rec = rv.load_history(p)["pairs"].get(rv.pair_key(proj, tg)) or {}
    running = rv.pair_key(proj, tg) in running_keys(cfg.sid)
    io = str(rec.get("io_file") or "")
    if not io:
        return {"ok": True, "running": running, "events": [], "offset": 0, "size": 0, "reset": True, "exists": False}
    r = read_io(cfg, io, offset)
    if not r.get("ok"):
        return {"ok": True, "running": running, "events": [], "offset": 0, "size": 0, "reset": True, "exists": False}
    r.update(running=running, exists=True, status=rec.get("status"), file=rec.get("file"))
    return r


def _claude_result(stdout: str) -> Optional[Dict[str, Any]]:
    """`claude -p --output-format json` çıktısındaki `type: result` nesnesi (tek nesne ya da dizinin SON result'ı); yoksa None."""
    try:
        val = json.loads(stdout)
    except ValueError:
        return None
    if isinstance(val, list):
        val = next((v for v in reversed(val) if isinstance(v, dict) and v.get("type") == "result"), None)
    return val if isinstance(val, dict) and ("result" in val or "usage" in val) else None


def claude_usage_event(stdout: str) -> Optional[Dict[str, Any]]:
    """claude JSON sonucundan `review usage`un okuduğu tek `request` olayı (yalnız SAYILAR). Sayı yoksa None (uydurma yok).
    İstem = giriş + önbellek okuma + önbellek yazma; önbellekli = önbellek okuma."""
    res = _claude_result(stdout)
    u = res.get("usage") if isinstance(res, dict) and isinstance(res.get("usage"), dict) else None
    if not u:
        return None

    def num(k: str) -> int:
        v = u.get(k)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else 0

    cached = num("cache_read_input_tokens")
    ev: Dict[str, Any] = {"event": "request",
                          "usage": {"prompt_tokens": num("input_tokens") + cached + num("cache_creation_input_tokens"),
                                    "completion_tokens": num("output_tokens"), "cached_tokens": cached},
                          "seconds": round(float(res.get("duration_ms") or 0) / 1000.0, 1)}
    cost = res.get("total_cost_usd")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        ev["cost_usd"] = float(cost)
    return ev


_CODEX_TOKENS_RE = re.compile(r"tokens used\s*[:\n]\s*([0-9][0-9.,]*)", re.I)


def codex_usage_event(stderr: str) -> Optional[Dict[str, Any]]:
    """codex stderr'indeki `tokens used` + sayı (yalnız TOPLAM bildirir; istem/cevap ayrımı yok). Yoksa None (uydurma yok)."""
    ms = _CODEX_TOKENS_RE.findall(stderr or "")
    if not ms:
        return None
    digits = re.sub(r"[.,]", "", ms[-1])
    return {"event": "request", "usage": {"total_tokens": int(digits)}} if digits.isdigit() else None


def _extract_text(mode: str, stdout: str) -> Tuple[str, str]:
    """(metin, hata). Evren: JSON `answer`; claude: JSON `result` (JSON değilse ham metin); bozuk/yarım JSON'da ham metin
    (kısmi çıktı kaybolmasın)."""
    if mode == "claude":
        res = _claude_result(stdout)
        if res is None:
            return stdout, ""
        txt = res.get("result")
        if res.get("is_error"):
            return (txt if isinstance(txt, str) else ""), (str(txt) if isinstance(txt, str) and txt else "claude is_error")
        return (txt if isinstance(txt, str) else ""), ""
    if mode not in rv.UCLI_MODES:
        return stdout, ""
    try:
        val = json.loads(stdout)
    except ValueError:
        return stdout, ""
    if isinstance(val, dict):
        if val.get("error"):
            return "", str(val["error"])
        return str(val.get("answer") or ""), ""
    return stdout, ""


_REPORT_HEAD_RE = re.compile(r"^## R-\d+ \||BULGU YOK", re.MULTILINE)
ERROR_LOG_KEEP = 16 * 1024      # hata günlüğünde stdout/stderr kuyruğu (her biri)


def _partial_turn_text(stdout: str) -> str:
    """ucli başarısız tek-atımlık chat'te `{"error":..., "partial_turn": ...}` basar: kısmi tur metni (yoksa "")."""
    try:
        val = json.loads(stdout)
    except ValueError:
        return ""
    pt = val.get("partial_turn") if isinstance(val, dict) else None
    if isinstance(pt, dict):
        pt = pt.get("assistant_text") or pt.get("answer") or pt.get("text")
    return pt if isinstance(pt, str) else ""


def _recover_partial(path: str, learned: Sequence[str] = ()) -> str:
    """`--partial-file` (`rv.partial_path`) içindeki `assistant_text`: reviewer SIGKILL ettiğinde bile son tur sınırındaki
    metin. Dosya diskte maskelenmeden kalmasın diye maskeli yeniden yazılır (atomik). Yalnız rapor başlığı (`## R-n |` ya da
    `BULGU YOK`) içeren metin rapor sayılır; yoksa "" (çöp `partial` üretme)."""
    pp = rv.partial_path(path)
    try:
        if os.path.islink(pp):
            return ""
        with open(pp, encoding="utf-8", errors="replace") as f:
            raw = f.read()
        val = json.loads(raw)
    except (OSError, ValueError):
        return ""
    red = rv.redact_secrets(raw, learned)
    tmp = pp + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(red)
        os.replace(tmp, pp)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    text = val.get("assistant_text") if isinstance(val, dict) else ""
    text = rv.redact_secrets(text, learned) if isinstance(text, str) else ""
    return text if _REPORT_HEAD_RE.search(text) else ""


def _write_error_log(path: str, status: str, error: str, rc: Any, timed_out: bool, jerr: str, out: str, err: str,
                     learned: Sequence[str] = ()) -> str:
    """Başarısız (done olmayan) koşu için kalıcı hata günlüğü `<ts>.error.txt` (0600): durum, hata gövdesi, çıkış kodu,
    stdout/stderr kuyruğu; hepsi maskeli. Günlüksüz kalan hatalar (glm-5.3 "exceeds 1 MiB", 2026-10-24) bir daha olmasın.
    Yazılan yolu döndürür ("" = yazılamadı)."""
    ep = rv.error_path(path)
    body = (f"durum: {status}\nhata: {error}\nçıkış_kodu: {rc}\nzaman_aşımı: {bool(timed_out)}\n"
            f"json_hata: {jerr}\n\n--- stdout (son {ERROR_LOG_KEEP} bayt) ---\n{(out or '')[-ERROR_LOG_KEEP:]}\n"
            f"\n--- stderr (son {ERROR_LOG_KEEP} bayt) ---\n{(err or '')[-ERROR_LOG_KEEP:]}\n")
    try:
        os.makedirs(os.path.dirname(ep), exist_ok=True)
        tmp = ep + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(rv.redact_secrets(body, learned))
        os.replace(tmp, ep)
        return ep
    except OSError:
        return ""


def _write_report(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)      # kod alıntılı rapor: hata günlüğüyle aynı izin (umask 0644 değil)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def _tail(s: str, learned: Sequence[str] = ()) -> str:
    s = rv.redact_secrets((s or "").strip(), learned)
    return s[-STDERR_KEEP:]


def _execute(job: _Job, paths: Any, cfg: Any, project: str, target: rv.ReviewTarget, argv: List[str], env: Dict[str, str],
             cwd: str, path: str, started: float, popen: Callable, agy_log_dir: str, now: Callable[[], float]) -> None:
    key = job.key
    live = IoLog(io_path_for(path), now, err_as_delta=(target.mode in rv.UCLI_MODES))
    agy_before = _agy_log_names(agy_log_dir) if target.mode == "agy" else frozenset()
    if job.prompt:
        live.event("user", job.prompt, "prompt")
    try:
        try:
            proc = popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
        except OSError as e:
            live.system(f"süreç başlamadı: {e}")
            rv.update_pair(paths, project, target, status="error", finished_at=now(), error=f"spawn: {e}")
            return
        job.proc = proc
        if job.cancelled:     # süreç açılmadan gelen iptal (`cancel_key`): şimdi uygula
            _killpg(proc, signal.SIGTERM)
        rv.update_pair(paths, project, target, pid=getattr(proc, "pid", None))
        live.system(f"başladı: {project} {target.mode}/{target.slug}, pid {getattr(proc, 'pid', '?')}. "
                 + ("Çıktı canlı akar." if target.mode in rv.UCLI_MODES else "Çıktı iş bitince gelir."))
        stop_hb = threading.Event()

        def _beat() -> None:
            while not stop_hb.wait(HEARTBEAT_SECONDS):
                live.system(f"çalışıyor: {int(now() - started)} sn, pid {getattr(proc, 'pid', '?')}")
        threading.Thread(target=_beat, daemon=True, name=f"review-hb-{key}").start()
        timed_out = False
        timeout = max(1.0, float(getattr(cfg, "review_timeout_minutes", 45)) * 60.0)
        bufs: Dict[str, List[str]] = {"out": [], "err": []}
        readers: List[threading.Thread] = []

        def _pump(name: str, stream: Any) -> None:
            dec = codecs.getincrementaldecoder("utf-8")("replace")
            try:
                fd = stream.fileno()
                while True:
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    txt = dec.decode(chunk)
                    bufs[name].append(txt)
                    (live.out if name == "out" else live.feed_err)(txt)
            except (OSError, ValueError):
                pass
            tail = dec.decode(b"", final=True)
            if tail:
                bufs[name].append(tail)
                (live.out if name == "out" else live.feed_err)(tail)
        try:
            real = all(callable(getattr(getattr(proc, a, None), "fileno", None)) for a in ("stdout", "stderr"))
            if real:
                for nm, st in (("out", proc.stdout), ("err", proc.stderr)):
                    th = threading.Thread(target=_pump, args=(nm, st), daemon=True, name=f"review-pump-{nm}-{key}")
                    th.start()
                    readers.append(th)
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    _terminate(proc, KILL_GRACE_SECONDS)
                for th in readers:
                    th.join(10)
                out, err = "".join(bufs["out"]), "".join(bufs["err"])
            else:   # sahte/akışsız süreç: tek seferde topla, bitince günlüğe yaz
                try:
                    out, err = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    _terminate(proc, KILL_GRACE_SECONDS)
                    out, err = proc.communicate()
                live.out(out or "")
                live.feed_err(err or "")
        finally:
            stop_hb.set()
        out, err = out or "", err or ""
        text, jerr = _extract_text(target.mode, out)
        if target.mode in ("claude", "codex"):     # token: yalnız sayılar `<ts>.usage.jsonl`e (review usage okur); sayı yoksa dosya yok
            uev = claude_usage_event(out) if target.mode == "claude" else codex_usage_event(err)
            if uev and path.endswith(".md"):
                try:
                    with open(path[:-3] + ".usage.jsonl", "w", encoding="utf-8") as uf:
                        uf.write(json.dumps(uev) + "\n")
                except OSError:
                    pass
        recovered = False
        if target.mode in rv.UCLI_MODES:
            text, recovered = _recover_draft(path, text, live.learned())
            if not text.strip():
                text = live.streamed_report()       # taslak da yoksa: akıştaki yarım rapor
                recovered = bool(text.strip())
            if not text.strip():                    # son çare: ucli `--partial-file` (SIGKILL'e dayanıklı) ya da `partial_turn`
                text = _recover_partial(path, live.learned()) or _partial_turn_text(out)
                recovered = bool(text.strip())
        text = rv.redact_secrets(text, live.learned())
        rc = getattr(proc, "returncode", None)
        fields: Dict[str, Any] = {"finished_at": now(), "pid": None}
        if text.strip():
            _write_report(path, text)
            fields["file"] = path
        if job.cancelled:
            status, error = ("partial" if text.strip() else "error"), "cancelled"
        elif timed_out:
            status, error = ("partial" if text.strip() else "error"), f"timeout {int(timeout // 60)} dk"
        elif jerr:
            status, error = ("partial" if text.strip() else "error"), _tail(jerr, live.learned())
        elif rc == 0 and text.strip() and not recovered and rv.report_incomplete(text):
            status, error = "partial", "incomplete: tool budget exhausted (no findings, scope disclaimer)"
        elif rc == 0 and text.strip() and not recovered:
            status, error = "done", ""
        elif text.strip():
            status, error = "partial", f"exit={rc} {_tail(err, live.learned())}".strip()
        else:
            status, error = "error", f"exit={rc} {_tail(err, live.learned())}".strip()
        # Limit taraması: başarısız koşuda stdout+stderr; BAŞARILI görünen (rc=0) koşuda yalnız stdout KISA bir sağlayıcı
        # mesajıysa (copilot kota mesajını çıkış kodu 0 ile basar; rapor sanılıp `done` olmasın).
        chk = (out, err, jerr) if (status != "done" or rv.is_short_banner(text)) else ()
        if chk and rv.is_daily_limit(*chk):
            until = rv.block_until_for_limit(now(), *chk)
            status = "limit"
            error = ("aylık kota doldu; ay sonuna dek durdu" if until != rv.next_utc_midnight(now())
                     else "günlük kota doldu (daily_token_limit_exceeded); mod UTC gece yarısına dek durdu")
            rv.set_block(paths, target.mode, until, error)
        elif chk and rv.is_quota_exhausted(*chk):
            until = rv.quota_block_until(now(), *chk)
            status = "limit"
            error = f"model kotası doldu ({target.key}); {time.strftime('%Y-%m-%d %H:%M', time.localtime(until))} dolayına dek planlayıcıdan çıktı"
            rv.set_block(paths, target.key, until, error)
        elif target.mode in rv.UCLI_MODES and status in ("error", "partial") \
                and (not text.strip() or (timed_out and not _REPORT_HEAD_RE.search(text))):      # kurtarılmış rapor varsa ders (= araştırma turu) açma
            _write_lesson(sw._pp(paths), project, target, status, error, live.learned())
        if target.mode == "agy" and status in ("done", "partial"):
            ok, seen = rv.agy_label_ok(_first_new_agy_log(agy_log_dir, started, agy_before), target.model)
            fields["label_seen"] = seen
            if not ok:
                # dosya saklanır ama done sayılmaz: agy planda olmayan modeli sessizce başka modele düşürür
                status, error = "model_fallback", f"agy etiket uyuşmadı: istenen={target.model} görülen={seen or '(yok)'}"
        if status != "done":
            ef = _write_error_log(path, status, error, rc, timed_out, jerr, out, err, live.learned())
            if ef:
                fields["error_file"] = ef
        fields.update(status=status, error=error)
        live.system(f"bitti: {status}" + (f" ({error})" if error else "") + (f"; dosya: {fields['file']}" if fields.get("file") else ""))
        live.close()
        rv.update_pair(paths, project, target, **fields)
        if status in ("done", "partial") and fields.get("file"):
            try:    # bulgular state=new ile kaydedilir; ayrıştırma hatası koşunun sonucunu bozmaz
                rv.add_findings(paths, project, path, rv.parse_findings(text))
            except Exception as e:
                sw.log_event("review_findings_failed", paths=paths, project=project, error=_tail(repr(e)))
    except Exception as e:   # çalıştırıcı asla `running` bırakıp ölmesin
        try:
            rv.update_pair(paths, project, target, status="error", finished_at=now(), error=_tail(f"{type(e).__name__}: {e}"))
        except Exception:
            pass
    finally:
        live.close()
        with _JOBS_LOCK:
            _JOBS.pop(key, None)
        _release_slot(key)
        if job.locked:
            _REVIEW_LOCK.release()


def _recover_draft(path: str, text: str, learned: Sequence[str] = ()) -> Tuple[str, bool]:
    """Evren modelinin `--allow-create-dir` ile yazdığı taslak (`rv.draft_path`): ham taslak diskte maskelenmeden
    kalmasın diye HER ZAMAN maskeli yeniden yazılır (`learned`: akışta DSN'den öğrenilmiş parolalar); stdout metni boşsa
    (zaman aşımı, kesik çıktı) taslak rapor olur. (metin, taslaktan_mı)."""
    dp = rv.draft_path(path)
    try:
        if os.path.islink(dp):                   # model symlink bırakmış olamaz (create-only) ama okuma/yazma izlemesin
            return text, False
        with open(dp, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError:
        return text, False
    red = rv.redact_secrets(raw, learned)
    tmp = dp + ".tmp"
    try:                                          # atomik: yarım yazılmış/boş taslak kalmaz
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(red)
        os.replace(tmp, dp)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return (text, False) if text.strip() else (red, bool(red.strip()))


def _write_lesson(p: Any, project: str, target: rv.ReviewTarget, status: str, error: str, learned: Sequence[str] = ()) -> None:
    """Evren modeli review'u bitiremedi: ucli dersi `<çalışma alanı>/ucli-lessons.md`ye eklenir (ucli kimliğinin
    beyni TODO/TBD'ye çevirir; başka reponun dosyasına yazmayız). `learned`: koşuda öğrenilen DSN parolaları (hata
    metninde de maskelenir). Dosya `sl.prune_lessons` ile son `FILE_MAX` otomatik satıra kırpılır."""
    try:
        line = (f"- [otomatik] {time.strftime('%Y-%m-%d %H:%M')} proje={project} model={target.model} durum={status} "
                f"hata={_tail(error, learned)}: ucli bu model/proje çiftinde review'u bitiremedi; nedenini araştır, TODO/TBD yap, düzelt.\n")
        path = os.path.join(p.root, sl.LESSONS_FILE)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
        try:    # dosya sınırsız büyümesin: yalnız son `FILE_MAX` otomatik satır kalır (atomik yeniden yazım)
            with open(path, encoding="utf-8", errors="replace") as f:
                cur = f.read()
            pruned = sl.prune_lessons(cur)
            if pruned != cur:
                with open(path + ".tmp", "w", encoding="utf-8") as f:
                    f.write(pruned)
                os.replace(path + ".tmp", path)
        except OSError:
            pass
        sw.log_event("review_ucli_lesson", paths=p, project=project, model=target.model, status=status)
    except Exception:
        pass


def _default_popen(*a: Any, **k: Any) -> Any:
    """Üretimin süreç başlatıcısı. Ayrı bir ad: testler (`tests/_no_real_review.py`) bunu değiştirip gerçek süreç
    başlamasını engeller."""
    return subprocess.Popen(*a, **k)


def run_job(paths: Any, cfg: Any, project: str, cwd: str, target: rv.ReviewTarget, *,
            popen: Optional[Callable] = None, now: Callable[[], float] = time.time,
            ucli_bin: Optional[str] = None, agy_bin: Optional[str] = None, agy_log_dir: str = AGY_LOG_DIR,
            agy_models: Optional[List[str]] = None, provider: Any = None, api_key: Optional[str] = None,
            endpoint_fn: Optional[Callable[[], str]] = None, supports_flag: Optional[Callable[[str, str], bool]] = None,
            lang: str = "tr") -> Dict[str, Any]:
    """Bir (proje, mod, model) çiftinin review'ını arka plan thread'inde başlatır; hemen döner. `review_slots` boşsa süreç
    genelinde aynı anda TEK iş (`_REVIEW_LOCK`), doluysa mod başına yuva (`_take_slot`); meşgulse `{"ok": False, "busy": True}`.
    Sonuç `review_history.json`a yazılır."""
    popen = popen or _default_popen
    p = sw._pp(paths)
    key = rv.pair_key(project, target)
    slots = rv.parse_slots(getattr(cfg, "review_slots", ""))
    locked = not slots
    if locked and not _REVIEW_LOCK.acquire(blocking=False):
        return {"ok": False, "busy": True, "error": "başka bir review çalışıyor"}
    slot, why = _take_slot(key, project, target.mode, slots)
    if slot < 0:
        if locked:
            _REVIEW_LOCK.release()
        return {"ok": False, "busy": True, "error": why}
    t0 = now()
    try:
        rdrv = remote_driver(project)
        if rdrv is not None and target.mode != "evren":
            raise RuntimeError("uzak projede review yalnız evren (ucli) hedefleriyle koşar")
        if rdrv is not None:
            cwd = rdrv.cwd()
        prompt = rv.build_review_prompt(project, cwd, lang)
        env_extra: Dict[str, str] = {}
        if rdrv is not None:
            # UZAK koşu (TBD#117 ek 3 c): uzak host'ta normal ucli oturumu; yerel süreç, anahtar, taslak dosyası YOK
            eff = str(target.effort or getattr(cfg, "review_evren_effort", "medium") or "medium")
            argv = ["remote-review", rdrv.host, project, target.model]
            popen = lambda *_a, **_k: rrun.RemoteReviewProc(   # noqa: E731
                rdrv, target.model, eff, prompt, lambda t: bool(_REPORT_HEAD_RE.search(t or "")))
        elif target.mode in rv.UCLI_MODES:
            from ..providers import ucli_provider as up
            binary = ucli_client.resolve_binary(ucli_bin)
            sup = (supports_flag or ucli_client.binary_supports_flag)(binary, "--max-io-mib")
            sf = supports_flag or ucli_client.binary_supports_flag
            live_flags = [fl for fl in ("--stream", "--show-reasoning") if sf(binary, fl)]
            budget: List[str] = []
            for flag, attr, dflt in (("--max-context-kib", "review_max_context_kib", 768),
                                     ("--max-compactions", "review_max_compactions", 24),
                                     ("--max-tool-calls", "review_max_tool_calls", 30)):
                if sf(binary, flag):
                    budget += [flag, str(max(1, int(getattr(cfg, attr, dflt) or dflt)))]
            for flag, attr, dflt in (("--max-wall-secs", "review_max_wall_secs", 900),
                                     ("--request-timeout-secs", "review_request_timeout_secs", 300)):
                val = getattr(cfg, attr, dflt)
                val = dflt if val is None else int(val)
                if val > 0 and sf(binary, flag):        # 0 = kapalı (geri alma); eski ikili bayrağı bilmiyorsa gitmez
                    budget += [flag, str(val)]
            mot = getattr(cfg, "review_max_output_tokens", 32768)
            mot = 32768 if mot is None else int(mot)
            if mot > 0 and sf(binary, "--max-output-tokens"):    # 0 = kapalı; eski ikili bayrağı bilmiyorsa gitmez
                budget += ["--max-output-tokens", str(mot)]
            if str(getattr(cfg, "review_evren_script", "") or "").strip().lower() == "read" and sf(binary, "--allow-script"):
                budget += ["--allow-script=read"]     # yalnız salt-okunur araçlar (yazma/fetch/MCP YOK): review'ın salt-okunur kuralı bozulmaz
            create_dir = ""
            rpath = rv.review_path(p.reviews, project, target, t0, rv.effort_for(cfg, target.mode, target))
            os.makedirs(os.path.dirname(rpath), exist_ok=True)
            if sf(binary, "--usage-log"):           # token ekonomisi ölçümü: istek başına sayılar (istem/cevap/araç sonucu YOK)
                budget += ["--usage-log", rpath[:-3] + ".usage.jsonl"]
            if sf(binary, "--effort"):
                # HER Evren koşusunda effort gider (ucli'nin "output limit used up by reasoning" -> low yeniden denemesi bunu şart
                # koşar); model alanı kabul ettiği kanıtlı değilse (gemma-4-31b 400) `reasoning_effort_for` None verir.
                level = str(target.effort or getattr(cfg, "review_evren_effort", "medium") or "").strip()
                if target.mode == "anthropic":      # Claude modelleri low..max'i kabul eder; model alanı kapısı Evren'e özel
                    eff = level if level in ("low", "medium", "high", "xhigh", "max") else None
                else:
                    eff = up.reasoning_effort_for(target.model, level) if level and level.lower() != "off" else None
                if eff:
                    budget += ["--effort", eff]
            if sf(binary, "--partial-file"):        # SIGKILL'e dayanıklı kısmi çıktı (tur sınırında atomik yazılır, 0600)
                budget += ["--partial-file", os.path.realpath(rv.partial_path(rpath))]   # ucli yolun HERHANGİ bir bileşeni symlink ise reddeder
            if sf(binary, "--allow-create-dir"):
                create_dir = os.path.dirname(rpath)
                prompt += rv.draft_prompt_suffix(rv.draft_path(rpath), lang)
            if target.mode == "anthropic":
                budget += ["--provider", "anthropic-messages"]
                ep = rv.ANTHROPIC_ENDPOINT
                key_val = api_key if api_key is not None else _anthropic_review_key()
                if not key_val:
                    raise RuntimeError(f"Anthropic review anahtarı yok: {ANTHROPIC_REVIEW_KEY_FILE}")
            else:
                ep = (endpoint_fn or up.endpoint)()
                key_val = api_key if api_key is not None else _api_key()
                if not key_val:
                    raise RuntimeError("Evren API anahtarı yok")
            argv = evren_argv(binary, cwd, target.model, prompt, ep, bool(sup), live_flags, budget, create_dir)
            env_extra["UCLI_API_KEY"] = key_val
        elif target.mode == "claude":
            from ..settings import resolved_binary
            key_val = api_key if api_key is not None else _anthropic_review_key()
            if not key_val:
                raise RuntimeError(f"Anthropic review anahtarı yok: {ANTHROPIC_REVIEW_KEY_FILE} (600) oluştur")
            cdir = os.path.join(p.root, "claude_cfg")    # CLAUDE.md/hafıza/oturum geçmişi yok: izole yapılandırma dizini
            os.makedirs(cdir, exist_ok=True)
            cj = os.path.join(cdir, ".claude.json")
            if not os.path.exists(cj):
                with open(cj, "w") as f:
                    json.dump({"hasCompletedOnboarding": True, "theme": "dark",
                               "projects": {cwd: {"hasTrustDialogAccepted": True}}}, f)
            argv = claude_argv(resolved_binary("claude"), target.model, str(target.effort or getattr(cfg, "review_claude_effort", "low") or ""), prompt, json_out=True)
            env_extra.update(ANTHROPIC_API_KEY=key_val, CLAUDE_CONFIG_DIR=cdir, DISABLE_AUTOUPDATER="1")
        elif target.mode == "codex":
            from ..settings import resolved_binary
            argv = codex_argv(resolved_binary("codex"), cwd, target.model, str(target.effort or getattr(cfg, "review_codex_effort", "low") or ""), prompt)
        elif target.mode == "copilot":
            from ..settings import resolved_binary
            argv = copilot_argv(resolved_binary("copilot"), target.model, str(target.effort or getattr(cfg, "review_copilot_effort", "low") or ""), prompt)
        elif target.mode == "agy":
            from ..providers.agy_provider import AgyProvider
            from ..settings import resolved_binary
            prov = provider or AgyProvider()
            models = agy_models if agy_models is not None else prov.model_choices()
            if target.model not in models:
                raise RuntimeError(f"agy model listesinde yok: {target.model}")
            argv = agy_argv(agy_bin or resolved_binary("agy"), target.model, prompt, prov)
            allow = rv.agy_allow_list(getattr(cfg, "review_agy_allow", ""))
            if allow:   # izole HOME: komut izni yalnız salt-okunur liste; günlük/etiket doğrulaması da bu HOME'dan okunur
                home = agy_home(p.root, cwd, allow, slot=slot)
                env_extra["HOME"] = home
                env_extra["TMPDIR"] = os.path.join(home, "tmp")     # kafeste /tmp salt okunur
                bwrap = shutil.which("bwrap") if getattr(cfg, "review_agy_jail", True) else None
                if bwrap:    # salt-okunur dosya sistemi kafesi: izin sorusu yok, yazma imkansız (yoksa izin listesi yolu)
                    argv = bwrap_jail(argv, home, bwrap)
                if agy_log_dir == AGY_LOG_DIR:
                    agy_log_dir = os.path.join(home, ".gemini", "antigravity-cli", "log")
        else:
            raise RuntimeError(f"bilinmeyen mod: {target.mode}")
        rv.update_pair(p, project, target, status="running", started_at=t0, finished_at=None, file=None, error=None,
                       label_seen=None, pid=None, head=project_head(cwd) or None)
        job = _Job(key)
        job.sid = p.sid
        job.prompt = prompt
        job.locked = locked
        with _JOBS_LOCK:
            _JOBS[key] = job
        path = rv.review_path(p.reviews, project, target, t0, rv.effort_for(cfg, target.mode, target))
        rv.update_pair(p, project, target, io_file=io_path_for(path))
        th = threading.Thread(target=_execute, daemon=True, name=f"review-{key}",
                              args=(job, p, cfg, project, target, argv, clean_env(env_extra), cwd, path, t0, popen,
                                    agy_log_dir, now))
        th.start()
    except Exception as e:
        with _JOBS_LOCK:        # iş kaydı açıldıktan sonra başlatma düştüyse kayıt (ve iptal edilebilir sahte iş) kalmasın
            _JOBS.pop(key, None)
        _release_slot(key)
        if locked:
            _REVIEW_LOCK.release()
        try:
            rv.update_pair(p, project, target, status="error", started_at=t0, finished_at=now(), error=_tail(str(e)))
        except Exception:
            pass
        return {"ok": False, "error": str(e)}
    return {"ok": True, "key": key, "file": path, "thread": th, "argv": argv}


def _recover_restart_report(rec: Dict[str, Any]) -> str:
    """TBD#119 B: restart ile ölen koşunun diskte kalan taslağı (`.model.md`) ya da `--partial-file` metni rapor başlığı
    içeriyorsa maskeli `<ts>.md` olarak yazılır ve bulgular `new` kaydedilir. Rapor yolu `io_file`dan türetilir. Yazılan
    yol ("" = kurtarılacak rapor yok / var olan rapor dosyası korunur)."""
    io = rec.get("io_file")
    if not isinstance(io, str) or not io.endswith(IO_SUFFIX):
        return ""
    path = io[:-len(IO_SUFFIX)] + ".md"
    if os.path.exists(path) or os.path.islink(path):
        return ""
    text, _ = _recover_draft(path, "")
    if not _REPORT_HEAD_RE.search(text or ""):
        text = _recover_partial(path)
    text = rv.redact_secrets(text or "")
    if not _REPORT_HEAD_RE.search(text):
        return ""
    try:
        _write_report(path, text)
    except OSError:
        return ""
    return path


def recover_on_start(paths: Any, now: Callable[[], float] = time.time) -> int:
    """Servis yeniden başlayınca `running` kalan çiftler (süreç ölmüştür) `partial` olur. Kaç çift düzeltildi."""
    p = sw._pp(paths)
    n = 0
    recovered: List[Tuple[str, str]] = []
    with sw.steward_lock(p):
        hist = rv.load_history(p)
        for key, rec in hist["pairs"].items():
            if isinstance(rec, dict) and rec.get("status") == "running":
                if key in busy_keys():   # bu süreçte CANLI ya da başlamakta olan iş (restart sonrası ilk tick'ten ÖNCE elle başlatılan): yarıda kalmış değil
                    continue
                rec.update(status="partial", finished_at=now(), pid=None, error="yeniden başlatma: koşu yarıda kaldı")
                saved = _recover_restart_report(rec)
                if saved:       # TBD#119 B: diskte kalan taslak/partial rapor olarak kurtarıldı
                    rec["file"] = saved
                    recovered.append((key.split("|", 1)[0], saved))
                hist["runs"].append({"pair": key, "status": "partial", "at": rec["finished_at"], "file": rec.get("file")})
                n += 1
        if n:
            rv.save_history(p, hist)
    for proj, path in recovered:    # bulgular kilit dışında (add_findings kendi kilidini alır)
        try:
            with open(path, encoding="utf-8") as f:
                rv.add_findings(paths, proj, path, rv.parse_findings(f.read()))
        except Exception as e:
            sw.log_event("review_findings_failed", paths=paths, project=proj, error=_tail(repr(e)))
    return n


# ── planlayıcı (adım 5) ───────────────────────────────────────────────────────

# Test anahtarı: False iken tick'in başlattığı iş eşzamanlı (thread beklenir). Üretimde True.
_REVIEW_BACKGROUND = True
# `run_job`a ek anahtar sözcük argümanları (testler `popen=` vb. enjekte eder; üretimde boş).
_RUN_KW: Dict[str, Any] = {}
_RECOVERED: set = set()          # `recover_on_start` çalışmış kimlikler (süreç başına bir kez)


def project_cwd(name: str) -> str:
    """Projenin YEREL klasörü (instances kaydı). `web_steward` kendi çözücüsünü `set_cwd_resolver` ile bağlar."""
    if _CWD_FN is not None:
        return _CWD_FN(name) or ""
    try:
        from .. import instances as inst_mod
        rec = inst_mod.get_instance(name)
        return str((rec or {}).get("cwd") or "")
    except Exception:
        return ""


_CWD_FN: Optional[Callable[[str], str]] = None


def review_cwd(name: str, idx: Optional[Dict[str, Any]] = None) -> str:
    """Review'un koşacağı klasör: uzak projede sahibin seçtiği yerel kopya, değilse projenin yerel klasörü."""
    return remote_copy_path(name, idx) or project_cwd(name)


_COPY_FAIL: Dict[str, Tuple[str, float]] = {}      # proje -> (son hata, log zamanı): her tick aynı hatayı yazmasın
COPY_FAIL_LOG_SECONDS = 3600.0

_NOTIFY_FN: Optional[Callable[[str, Any], Any]] = None
ASK_RETRY_SECONDS = 24 * 3600.0                     # cevabı tanınmayan "nerede review" sorusu en erken bu kadar sonra yeniden sorulur


def set_notifier(fn: Optional[Callable[[str, Any], Any]]) -> None:
    """`web_steward` bağlar: `fn(sahip_kimlik, Question)` soruyu telefona bildirir (bu modül ntfy'yi bilmez)."""
    global _NOTIFY_FN
    _NOTIFY_FN = fn


def _log_copy_fail(p: Any, project: str, msg: str, now: float) -> None:
    last = _COPY_FAIL.get(project)
    if last and last[0] == msg and now - last[1] < COPY_FAIL_LOG_SECONDS:
        return
    _COPY_FAIL[project] = (msg, now)
    sw.log_event("review_copy_not_ready", paths=p, project=project, error=msg)


def ask_remote_choice(cfg: Any, now: float, idx: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Sahip kararı bilinmeyen (`review_where` ""/"ask") uzak proje için SAHİBE tek soru açar (TBD#114): seçenekler yerel
    kopya / uzak / vazgeç. Aynı anda en çok BİR açık soru (N uzak proje N bildirim üretmesin); cevabı tanınmayan soru
    `ASK_RETRY_SECONDS` içinde yinelenmez. Cevap `steward.answer_question` kancasında projeye yazılır. Açılan projeyi döner."""
    idx = ownership() if idx is None else idx
    remotes = remote_projects(idx)
    cands = sorted(n for n, (_sid, pj) in remotes.items() if pj.review_where in ("", "ask"))
    if not cands:
        return None
    qcache: Dict[str, List[Any]] = {}

    def questions(sid: str) -> List[Any]:
        if sid not in qcache:
            try:
                qcache[sid] = [q for q in sw.load_questions(sw.paths_for(sid)) if q.source == rr.ASK_SOURCE]
            except Exception:
                qcache[sid] = []
        return qcache[sid]
    for _n, (sid, _pj) in remotes.items():
        if any(q.status == "open" for q in questions(sid)):
            return None
    for name in cands:
        sid, pj = remotes[name]
        mine = [q for q in questions(sid) if q.project == name]
        if mine and now - max(q.created_at for q in mine) < ASK_RETRY_SECONDS:
            continue
        q = sw.add_question(name, rr.ask_text(name, pj.host, getattr(cfg, "lang", "tr")), source=rr.ASK_SOURCE,
                            options=rr.OPTIONS, paths=sw.paths_for(sid))
        try:
            sw.upsert_project(name, paths=sw.paths_for(sid), review_where="ask")
        except Exception:
            pass
        sw.log_event("review_where_asked", paths=sw.paths_for(sid), project=name, id=q.id)
        if _NOTIFY_FN is not None:
            try:
                _NOTIFY_FN(sid, q)
            except Exception:
                pass
        return name
    return None


def prepare_project(name: str, idx: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """Koşudan ÖNCE: uzak projenin yerel kopyası `git pull --ff-only` ile güncellenir (kirli/ayrışmışsa DUR). Yerel proje = (True, "")."""
    path = remote_copy_path(name, idx)
    if not path:
        return True, ""
    return rr.prepare_copy(path)


def set_cwd_resolver(fn: Optional[Callable[[str], str]]) -> None:
    global _CWD_FN
    _CWD_FN = fn


def ownership() -> Dict[str, Any]:
    """Tüm kimliklerin sahiplik indeksi (reviewer kimlikleri zaten boş sayılır). Okuma hatası = boş."""
    try:
        from ..settings import steward_ids
        return sw.ownership_index(steward_ids()) or {}
    except Exception:
        return {}


def remote_projects(idx: Optional[Dict[str, Any]] = None) -> Dict[str, Tuple[str, Any]]:
    """{ad: (sahip kimlik, Project)}: tek sahipli, uzak `host`'lu projeler (sahip kararı `review_where` burada)."""
    idx = ownership() if idx is None else idx
    owners = idx.get("owners") or {}
    cache: Dict[str, Dict[str, Any]] = {}
    out: Dict[str, Tuple[str, Any]] = {}
    for name in (idx.get("hosts") or {}):
        sid = owners.get(name)
        if not sid:
            continue
        if sid not in cache:
            try:
                cache[sid] = sw.load_projects(sid)
            except Exception:
                cache[sid] = {}
        proj = cache[sid].get(name)
        if proj is not None:
            out[name] = (sid, proj)
    return out


_REMOTE_FN: Optional[Callable[[str, str], Any]] = None


def set_remote_driver(fn: Optional[Callable[[str, str], Any]]) -> None:
    """`web_steward` bağlar: `fn(proje, host)` -> uzak review sürücüsü (kapılar + uzak G/Ç; `review_remote_run` sözleşmesi)."""
    global _REMOTE_FN
    _REMOTE_FN = fn


def remote_host(project: str, idx: Optional[Dict[str, Any]] = None) -> str:
    """Sahip `review_where=remote` seçtiyse projenin uzak host'u, değilse ""."""
    idx = ownership() if idx is None else idx
    ent = remote_projects(idx).get(project)
    if ent is None or ent[1].review_where != "remote":
        return ""
    return (idx.get("hosts") or {}).get(project) or ""


def remote_driver(project: str) -> Any:
    """`run_job` için uzak sürücü ya da None (yerel proje / `remote` seçilmemiş / sürücü bağlı değil)."""
    host = remote_host(project)
    if not host or _REMOTE_FN is None:
        return None
    return _REMOTE_FN(project, host)


SWEEP_EVERY_SECONDS = 600.0
_SWEPT_AT: Dict[str, float] = {}


def sweep_remote(now: float, idx: Optional[Dict[str, Any]] = None) -> List[str]:
    """`remote` kipindeki her projede: bu süreçte o projenin çalışan işi YOKSA uzaktaki yetim `rvw_<proje>` oturumunu kapatır
    (proje başına en çok `SWEEP_EVERY_SECONDS`te bir yoklama). Kapatılan projelerin listesi. Hata tick'i düşürmez."""
    if _REMOTE_FN is None:
        return []
    if not _REVIEW_LOCK.acquire(blocking=False):      # bir iş (elle başlatılan dahil) şimdi başlıyor/koşuyor: yarışma, atla
        return []
    try:
        return _sweep_remote_locked(now, idx)
    finally:
        _REVIEW_LOCK.release()


def _sweep_remote_locked(now: float, idx: Optional[Dict[str, Any]]) -> List[str]:
    idx = ownership() if idx is None else idx
    out: List[str] = []
    for name in sorted(remote_projects(idx)):
        host = remote_host(name, idx)
        if not host or now - _SWEPT_AT.get(name, -1e9) < SWEEP_EVERY_SECONDS:
            continue
        with _SLOT_LOCK:        # yuva kipinde başka projelerin işi sürerken de süpürülür: bu proje o arada başlatılamaz
            if name in {k.split("|", 1)[0] for k in list(_ACTIVE) + running_keys()}:
                continue
            _SWEEPING.add(name)
        _SWEPT_AT[name] = now
        try:
            if _REMOTE_FN(name, host).sweep():
                out.append(name)
        except Exception:
            continue
        finally:
            with _SLOT_LOCK:
                _SWEEPING.discard(name)
    return out


def remote_ready(project: str, idx: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """Uzak (`remote` kipi) projede koşudan ÖNCE: sürücü bağlı mı, kapılar (remote_actions, host taze) ve uzak klasör tamam mı."""
    host = remote_host(project, idx)
    if not host:
        return True, ""
    if _REMOTE_FN is None:
        return False, "remote review driver is not wired"
    return _REMOTE_FN(project, host).ready()


def remote_copy_path(name: str, idx: Optional[Dict[str, Any]] = None) -> str:
    """Uzak projenin review edilebilir YEREL kopyası (sahip `local` seçti ve yol git deposu); yoksa ""."""
    ent = remote_projects(idx).get(name)
    if ent is None:
        return ""
    proj = ent[1]
    return proj.local_path if rr.eligible(proj.review_where, proj.local_path) else ""


def remote_block_reason(project: str, idx: Optional[Dict[str, Any]] = None) -> str:
    """Uzak proje review/havuz/export'a alınamıyorsa nedeni, değilse "". Yerel proje = ""."""
    idx = ownership() if idx is None else idx
    if project not in (idx.get("hosts") or {}):
        return ""
    ent = remote_projects(idx).get(project)
    where = ent[1].review_where if ent else ""
    if where == "local":
        return "" if remote_copy_path(project, idx) else "remote project: local copy path is missing or not a git repo (set local_path)"
    if where == "remote":
        return "" if _REMOTE_FN is not None else "remote review driver is not wired"
    return "remote projects are not reviewed (v1)"


def local_owned_names(idx: Optional[Dict[str, Any]] = None) -> List[str]:
    """Havuza girebilecek proje adları: tek sahipli ve YEREL ya da sahibin yerel kopya seçtiği uzak proje."""
    idx = ownership() if idx is None else idx
    hosts = idx.get("hosts") or {}
    out = [n for n in (idx.get("owners") or {}) if n not in hosts]
    out += [n for n in hosts if remote_copy_path(n, idx) or remote_host(n, idx)]
    return sorted(out)


def available_models() -> Tuple[List[str], List[str]]:
    """(agy modelleri, Evren modelleri). Her kaynak ayrı korunur: liste alma hatası boş liste olur, tick'i düşürmez."""
    agy: List[str] = []
    evren: List[str] = []
    try:
        from ..providers.agy_provider import AgyProvider
        agy = list(AgyProvider().model_choices() or [])
    except Exception:
        agy = []
    try:
        from ..providers import ucli_provider as up
        evren = list(up._live_models() or [])
    except Exception:
        evren = []
    return agy, evren


def current_targets(cfg: Any) -> List[rv.ReviewTarget]:
    try:
        agy, evren = available_models()
    except Exception:
        agy, evren = [], []
    try:
        return rv.targets_from_config(cfg, agy, evren)
    except Exception:
        return []


def project_head(cwd: str) -> str:
    """Projenin git HEAD'i (yerel klasör; "" = git değil/okunamadı). Değişmeyen koda yeniden review yapılmasın diye çift
    kaydına yazılır (`head`) ve `rv.next_review(head_of=...)` ile karşılaştırılır."""
    if not cwd or not os.path.isdir(cwd):
        return ""
    try:
        r = subprocess.run(["git", "-C", cwd, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    out = (r.stdout or "").strip()
    return out if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,64}", out) else ""


def running_keys(sid: str = "") -> List[str]:
    with _JOBS_LOCK:
        return sorted(k for k, j in _JOBS.items() if not sid or j.sid == sid)


def cancel_all(sid: str = "", project: str = "") -> List[str]:
    out = []
    for k in running_keys(sid):
        if project and k.split("|", 1)[0] != project:
            continue
        if cancel_key(k):
            out.append(k)
    return out


def sync_pool(paths: Any, now: float, names: Optional[List[str]] = None) -> Tuple[Dict[str, Any], bool]:
    """Havuzu sahip adlarıyla eşler (kilit altında okuyup-yazar). (havuz, değişti_mi)."""
    p = sw._pp(paths)
    names = local_owned_names() if names is None else names
    with sw.steward_lock(p):
        pool = rv.load_pool(p)
        new, changed = rv.pool_sync(pool, names, now)
        if changed:
            rv.save_pool(p, new)
    return new, changed


def review_disable(cfg: Any) -> Dict[str, Any]:
    """Kapalı reviewer kimliği: koşan iş iptal edilir, hiçbir şey başlamaz."""
    cancelled = cancel_all(cfg.sid)
    return {"ok": True, "actions": [{"kind": "cancel", "key": k, "why": "disabled"} for k in cancelled], "started": 0,
            "noop": not cancelled, "disabled": True}


def start_job(paths: Any, cfg: Any, project: str, target: rv.ReviewTarget, cwd: str) -> Dict[str, Any]:
    res = run_job(paths, cfg, project, cwd, target, **dict({"lang": getattr(cfg, "lang", "tr") or "tr"}, **_RUN_KW))
    th = res.get("thread")
    if th is not None and not _REVIEW_BACKGROUND:
        th.join(timeout=60)
    return res


def review_tick(cfg: sw.Config, now: Optional[float] = None) -> Dict[str, Any]:
    """Bir reviewer kimliğinin döngü turu: (kapalıysa iptal) -> ilk tick'te `recover_on_start` -> havuz eşitleme ->
    havuzdan çıkan/devre dışı projenin koşan işini iptal -> tek iş kuralı + en az aralık -> sıradaki çift -> `run_job`.
    Oturum AÇMAZ; `max_starts_total` bütçesine sayılmaz. Hata yutulmaz ama tick_round tek kimlik için yakalar."""
    if not cfg.enabled:
        return review_disable(cfg)
    t = time.time() if now is None else now
    p = sw.paths_for(cfg.sid)
    actions: List[Dict[str, Any]] = []
    if cfg.sid not in _RECOVERED:
        _RECOVERED.add(cfg.sid)
        n = recover_on_start(p, now=lambda: t)
        if n:
            actions.append({"kind": "recover", "pairs": n})
        try:
            recover_self_verify(p)
        except Exception as e:
            sw.log_event("review_self_verify_recover_failed", paths=p, error=_tail(repr(e)))
    try:
        applied = process_verdicts(cfg, t)
    except Exception as e:      # karar okuma hatası planlayıcıyı düşürmesin
        sw.log_event("review_verdicts_failed", paths=p, error=_tail(repr(e)))
        applied = []
    if applied:
        actions.append({"kind": "verdicts", "findings": applied})
    try:
        auto = auto_approve(cfg, t)
    except Exception as e:
        sw.log_event("review_auto_approve_failed", paths=p, error=_tail(repr(e)))
        auto = []
    if auto:
        actions.append({"kind": "auto_approve", "findings": auto})
    try:
        exp = auto_export(cfg, t)
    except Exception as e:
        sw.log_event("review_auto_export_failed", paths=p, error=_tail(repr(e)))
        exp = []
    if exp:
        actions.append({"kind": "auto_export", "projects": exp})
    try:
        bt = before_tbd(cfg, t)
    except Exception as e:
        sw.log_event("review_before_tbd_failed", paths=p, error=_tail(repr(e)))
        bt = []
    if bt:
        actions.append({"kind": "before_tbd", "findings": bt})
    try:
        stored = store_reports(cfg)
    except Exception as e:      # saklama hatası review turunu düşürmesin
        sw.log_event("review_store_failed", paths=p, error=_tail(repr(e)))
        stored = []
    if stored:
        actions.append({"kind": "store_reports", "files": len(stored)})
    try:
        committed = store_commit(cfg, t)
    except Exception as e:
        sw.log_event("review_store_commit_failed", paths=p, error=_tail(repr(e)))
        committed = 0
    if committed:
        actions.append({"kind": "store_commit", "files": committed})
    try:
        asked = ask_remote_choice(cfg, t)
    except Exception as e:      # soru açma hatası review turunu düşürmesin
        sw.log_event("review_where_ask_failed", paths=p, error=_tail(repr(e)))
        asked = None
    if asked:
        actions.append({"kind": "ask_remote_choice", "project": asked})
    try:
        for swept in sweep_remote(t):
            actions.append({"kind": "remote_swept", "project": swept})
    except Exception as e:
        sw.log_event("review_remote_sweep_failed", paths=p, error=_tail(repr(e)))
    pool, changed = sync_pool(p, t)
    if changed:
        actions.append({"kind": "pool_sync"})
    enabled = set(rv.pool_enabled(pool))
    for k in running_keys(cfg.sid):          # havuzdan çıkan/devre dışı projenin işi
        if k.split("|", 1)[0] not in enabled and cancel_key(k):
            actions.append({"kind": "cancel", "key": k, "why": "not in pool"})
    slots = rv.parse_slots(getattr(cfg, "review_slots", ""))
    if not slots and busy_keys():
        return {"ok": True, "actions": actions, "started": 0, "noop": not actions, "busy": True}
    if getattr(cfg, "drain", False):      # "bitir, yeni başlatma": koşan iş sürdü (iptal edilmez), yenisi açılmaz; restart öncesi boşalt
        return {"ok": True, "actions": actions, "started": 0, "noop": not actions, "draining": True}
    hist = rv.load_history(p)
    last = max([float(r.get("started_at") or 0) for r in hist["pairs"].values() if isinstance(r, dict)] or [0.0])
    gap = max(0, int(getattr(cfg, "review_min_gap_minutes", 0))) * 60
    if last and t - last < gap:
        return {"ok": True, "actions": actions, "started": 0, "noop": not actions, "waiting": int(gap - (t - last))}
    targets = current_targets(cfg)
    if not targets:
        return {"ok": True, "actions": actions, "started": 0, "noop": not actions, "reason": "no targets"}
    if slots:
        return _tick_slots(p, cfg, pool, hist, targets, slots, t, gap, actions)
    skip: List[str] = []
    while True:
        nxt = rv.next_review(pool, hist, targets, t, busy_projects=skip, head_of=_head_of)
        if nxt is None:
            return {"ok": True, "actions": actions, "started": 0, "noop": not actions}
        proj, target = nxt
        state, cwd = _ready_project(p, proj, target, t, actions)
        if state == "ok":
            break
        skip.append(proj)                    # klasörü bulunamayan / yerel kopyası hazırlanamayan proje bu turda atlanır
    res = start_job(p, cfg, proj, target, cwd)
    if res.get("ok"):
        actions.append({"kind": "review_start", "project": proj, "target": target.key})
        return {"ok": True, "actions": actions, "started": 1, "noop": False}
    actions.append({"kind": "review_failed", "project": proj, "target": target.key, "error": res.get("error")})
    return {"ok": False, "actions": actions, "started": 0, "noop": False, "error": res.get("error")}


def _head_of(pr: str) -> str:
    return "" if remote_host(pr) else project_head(project_cwd(pr))


def _ready_project(p: Any, proj: str, target: rv.ReviewTarget, t: float, actions: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Koşudan önce proje hazır mı: ("ok", cwd) | ("mode", "") (uzak proje + evren dışı hedef: yalnız bu mod atlanır) |
    ("proj", "") (klasör yok / yerel kopya hazırlanamadı / uzak kapı kapalı: proje bu turda atlanır)."""
    if remote_host(proj):               # `remote` kipi: klasör uzakta; kapılar + host tazeliği + hedef evren mi
        if target.mode != "evren":
            msg = "remote review runs evren (ucli) targets only"
            _log_copy_fail(p, proj, msg, t)
            actions.append({"kind": "remote_not_ready", "project": proj, "error": msg})
            return "mode", ""
        ready, msg = remote_ready(proj)
        if ready:
            return "ok", ""
        _log_copy_fail(p, proj, msg, t)
        actions.append({"kind": "remote_not_ready", "project": proj, "error": msg})
        return "proj", ""
    cwd = review_cwd(proj)
    if cwd and os.path.isdir(cwd):
        ready, msg = prepare_project(proj)
        if ready:
            return "ok", cwd
        _log_copy_fail(p, proj, msg, t)
        actions.append({"kind": "copy_not_ready", "project": proj, "error": msg})
    return "proj", ""


def _key_mode(key: str) -> str:
    return key.split("|", 1)[1].split("/", 1)[0] if "|" in key else ""


def busy_keys() -> List[str]:
    """Çalışan ya da başlamakta olan tüm işler (tüm kimlikler): `_JOBS` + yuva kayıtları."""
    with _SLOT_LOCK:
        act = set(_ACTIVE)
    return sorted(act | set(running_keys()))


def anthropic_excluded(cfg: Any, pool: Any) -> List[str]:
    """`anthropic` modu yalnız `review_anthropic_projects` listesindeki projelere koşar: havuzdaki diğerleri atlanır."""
    allow = {x.strip() for x in str(getattr(cfg, "review_anthropic_projects", "") or "").split(",") if x.strip()}
    return [pr for pr in rv.pool_enabled(pool) if pr not in allow]


def anthropic_trial_complete(cfg: Any, pool: Any, hist: Any, targets: List[rv.ReviewTarget]) -> bool:
    """Bir defalık deneme: izinli her proje x her anthropic hedefi bir kez `done` (pencere gözetilmez) ise True; mod bir daha koşmaz."""
    allow = [x.strip() for x in str(getattr(cfg, "review_anthropic_projects", "") or "").split(",") if x.strip()]
    ant = [t for t in targets if t.mode == "anthropic"]
    pairs = rv._pairs(hist)
    return bool(allow and ant) and all((pairs.get(rv.pair_key(pr, t)) or {}).get("status") == "done" for pr in allow for t in ant)


def anthropic_filter(p: Any, cfg: Any, targets: List[rv.ReviewTarget], pool: Any = None, hist: Any = None) -> List[rv.ReviewTarget]:
    """Toplam harcama `review_anthropic_budget_usd`'ye ulaştıysa anthropic hedefleri bu turda planlanmaz (koşan iş biter)."""
    if not any(t.mode == "anthropic" for t in targets):
        return targets
    if hist is not None and anthropic_trial_complete(cfg, pool, hist, targets):
        return [t for t in targets if t.mode != "anthropic"]
    cap = float(getattr(cfg, "review_anthropic_budget_usd", 100.0) or 0)
    spent = rv.anthropic_spent_usd(p.reviews)
    if cap > 0 and spent >= cap:
        sw.log_event("review_anthropic_budget_reached", paths=p, spent=round(spent, 2), cap=cap)
        return [t for t in targets if t.mode != "anthropic"]
    return targets


def _tick_slots(p: Any, cfg: Any, pool: Dict[str, Any], hist: Dict[str, Any], targets: List[rv.ReviewTarget],
                slots: Dict[str, int], t: float, gap: int, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Yuva kipi (`review_slots`): her modda boş yuva kadar koşu, modlar arası sırayla birer birer (biri tüm projeleri
    kapmasın). Aynı proje iki koşuda olmaz (mod fark etmez). 0 yuvalı modun hedefi seçilmez. `review_min_gap_minutes` > 0
    ise tick başına en çok 1 başlatma (aralık başlatmalar arasıdır, yuva doluluğundan bağımsız)."""
    busy = busy_keys()
    targets = anthropic_filter(p, cfg, targets, pool, hist)
    free = {m: slots.get(m, 1) - sum(1 for k in busy if _key_mode(k) == m) for m in rv.MODES}
    busy_proj = {k.split("|", 1)[0] for k in busy}
    by_mode = {m: [x for x in targets if x.mode == m] for m in rv.MODES}
    skip_mode: Dict[str, List[str]] = {m: [] for m in rv.MODES}
    bad: List[str] = []                 # bu turda hazırlanamayan projeler (tüm modlarda atlanır)
    live = [m for m in rv.MODES if by_mode[m] and free[m] > 0]
    started, errors = 0, []
    while live:
        for mode in list(live):
            if started and gap:
                live = []
                break
            nxt = rv.next_review(pool, hist, by_mode[mode], t, busy_projects=sorted(busy_proj) + bad + skip_mode[mode]
                                 + (anthropic_excluded(cfg, pool) if mode == "anthropic" else []),
                                 head_of=_head_of)
            if nxt is None:
                live.remove(mode)
                continue
            proj, target = nxt
            state, cwd = _ready_project(p, proj, target, t, actions)
            if state != "ok":
                (skip_mode[mode] if state == "mode" else bad).append(proj)
                continue
            res = start_job(p, cfg, proj, target, cwd)
            if res.get("ok"):
                actions.append({"kind": "review_start", "project": proj, "target": target.key})
                started += 1
                free[mode] -= 1
                busy_proj.add(proj)
                if free[mode] <= 0:
                    live.remove(mode)
            else:
                actions.append({"kind": "review_failed", "project": proj, "target": target.key, "error": res.get("error")})
                errors.append(res.get("error"))
                skip_mode[mode].append(proj)
    out: Dict[str, Any] = {"ok": not errors or bool(started), "actions": actions, "started": started,
                           "noop": not actions}
    if errors:
        out["error"] = errors[0]
    return out


# ── yüzey (adım 6): saf yardımcılar, web_steward sarmalar ──────────────────────

FILE_MAX_CHARS = 200_000


def _slot_rows(cfg: Any) -> Dict[str, Dict[str, Any]]:
    """Yuva kipinde {mod: {"slots": n, "running": [anahtar...]}} (0 = mod kapalı); tek iş kipinde {}."""
    slots = rv.parse_slots(getattr(cfg, "review_slots", ""))
    if not slots:
        return {}
    busy = busy_keys()
    return {m: {"slots": n, "running": [k for k in busy if _key_mode(k) == m]} for m, n in slots.items()}


def review_state(cfg: Any, now: Optional[float] = None) -> Dict[str, Any]:
    t = time.time() if now is None else now
    p = sw.paths_for(cfg.sid)
    pool = rv.load_pool(p)
    hist = rv.load_history(p)
    targets = current_targets(cfg)
    rows = []
    for name, e in sorted((pool.get("projects") or {}).items()):
        if not isinstance(e, dict):
            continue
        rows.append({"project": name, "enabled": bool(e.get("enabled")) and not e.get("removed_at"),
                     "source": e.get("source") or "", "added_at": e.get("added_at"), "removed_at": e.get("removed_at"),
                     "complete": rv.project_complete(hist, name, targets, t),
                     "pairs": {tg.key: hist["pairs"].get(rv.pair_key(name, tg)) for tg in targets}})
    return {"ok": True, "enabled": bool(cfg.enabled), "role": cfg.role,
            "remote_projects": remote_where_rows(),
            "targets": [{"mode": x.mode, "model": x.model, "slug": x.slug, "key": x.key, "effort": x.effort} for x in targets],
            "pool": rows, "running": running_keys(cfg.sid), "slots": _slot_rows(cfg),
            "runs": list(hist.get("runs") or [])[-50:],
            "min_gap_minutes": cfg.review_min_gap_minutes, "timeout_minutes": cfg.review_timeout_minutes,
            "auto_verify": bool(cfg.review_auto_verify), "auto_approve": int(cfg.review_auto_approve),
            "auto_export": bool(cfg.review_auto_export)}


def read_review_file(cfg: Any, rel: str) -> Dict[str, Any]:
    """YALNIZ kimliğin `reviews/` ağacı altı. Mutlak yol, `..`, NUL ve symlink kaçışı reddedilir."""
    p = sw.paths_for(cfg.sid)
    rel = str(rel or "")
    if not rel or "\x00" in rel:
        return {"ok": False, "error": "path required"}
    root = os.path.realpath(p.reviews)
    cand = rel if os.path.isabs(rel) else os.path.join(p.reviews, rel)
    if ".." in rel.replace("\\", "/").split("/"):
        return {"ok": False, "error": "path outside reviews"}
    full = os.path.realpath(cand)
    if full != root and not full.startswith(root + os.sep):
        return {"ok": False, "error": "path outside reviews"}
    if not os.path.isfile(full):
        return {"ok": False, "error": "not found"}
    try:
        with open(full, errors="replace") as f:
            text = f.read(FILE_MAX_CHARS + 1)
    except OSError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "path": os.path.relpath(full, root), "text": text[:FILE_MAX_CHARS], "truncated": len(text) > FILE_MAX_CHARS}


def list_findings(cfg: Any, project: str = "", state: str = "") -> Dict[str, Any]:
    data = rv.load_findings(sw.paths_for(cfg.sid))
    rows = [dict(v, id=k) for k, v in data.items() if isinstance(v, dict)
            and (not project or v.get("project") == project) and (not state or v.get("state") == state)]
    rows.sort(key=lambda r: (str(r.get("project")), str(r.get("review_file")), str(r.get("ref"))))
    return {"ok": True, "findings": rows}


def remote_where_rows() -> List[Dict[str, Any]]:
    """Panel: uzak projeler ve sahibin `review_where` kararı: [{project, host, where, local_path}] (ada göre)."""
    try:
        rp = remote_projects()
    except Exception:
        return []
    return [{"project": n, "host": pj.host, "where": pj.review_where or "ask", "local_path": pj.local_path}
            for n, (_sid, pj) in sorted(rp.items())]


def set_where(project: str, where: str, local_path: str = "") -> Dict[str, Any]:
    """Panel/API: uzak projenin `review_where` kararını (ask|local|remote|off) elle ayarla (soruyu beklemeden). `local`
    geçerli bir git deposu yolu ister. Yerel proje ya da bilinmeyen ad reddedilir. Sahip kimliğin dosyasına yazılır."""
    project = str(project or "").strip()
    where = str(where or "").strip()
    if where not in ("ask", "local", "remote", "off"):
        return {"ok": False, "error": "where must be ask|local|remote|off"}
    ent = remote_projects().get(project)
    if ent is None:
        return {"ok": False, "error": f"not a remote project: {project}"}
    fields: Dict[str, Any] = {"review_where": where}
    if where == "local":
        path = os.path.expanduser(str(local_path or ent[1].local_path or "").strip())
        if not os.path.isabs(path) or not rr.is_git_dir(path):
            return {"ok": False, "error": "local requires an absolute path to a git repository"}
        fields["local_path"] = path
    try:
        sw.upsert_project(project, paths=sw.paths_for(ent[0]), **fields)
    except Exception as e:
        return {"ok": False, "error": _tail(f"{type(e).__name__}: {e}")}
    sw.log_event("review_where", paths=sw.paths_for(ent[0]), project=project, where=where, source="ui")
    return {"ok": True, "project": project, "where": where, "local_path": fields.get("local_path", ent[1].local_path)}


def pool_action(cfg: Any, action: str, project: str, now: Optional[float] = None) -> Dict[str, Any]:
    t = time.time() if now is None else now
    project = str(project or "").strip()
    if not project or not sw.valid_name(project):
        return {"ok": False, "error": "invalid project name"}
    p = sw.paths_for(cfg.sid)
    if action not in ("add", "remove", "enable", "disable"):
        return {"ok": False, "error": "action must be add|remove|enable|disable"}
    idx = ownership()
    if action in ("add", "enable"):
        why = remote_block_reason(project, idx)
        if why:
            return {"ok": False, "error": why}
    with sw.steward_lock(p):
        pool = rv.load_pool(p)
        pr = pool["projects"]
        e = pr.get(project)
        if action == "add":
            if e is None and not (project in (idx.get("owners") or {}) or project_cwd(project)):
                return {"ok": False, "error": f"unknown project: {project}"}
            pr[project] = dict(e or {}, enabled=True, source="manual", added_at=(e or {}).get("added_at") or t, removed_at=None)
        elif e is None:
            return {"ok": False, "error": f"not in pool: {project}"}
        elif action == "enable":
            e.update(enabled=True, removed_at=None)
        elif action == "disable":
            e["enabled"] = False
        else:   # remove: elle eklenmiş ve sahipsiz kayıt silinir; aksi halde elle-pasif işaretlenir (pool_sync geri açmasın)
            if e.get("source") == "manual" and project not in (idx.get("owners") or {}):
                del pr[project]
            else:
                e.update(enabled=False, source="manual", removed_at=t)
        rv.save_pool(p, pool)
    cancelled = []
    if action in ("remove", "disable"):
        cancelled = cancel_all(cfg.sid, project)
    return {"ok": True, "action": action, "project": project, "cancelled": cancelled}


def manual_run(cfg: Any, project: str, mode: str = "", model: str = "") -> Dict[str, Any]:
    project = str(project or "").strip()
    if not cfg.enabled:
        return {"ok": False, "error": "reviewer is disabled"}
    if not project or not sw.valid_name(project):
        return {"ok": False, "error": "invalid project name"}
    idx = ownership()
    why = remote_block_reason(project, idx)
    if why:
        return {"ok": False, "error": why}
    is_remote = bool(remote_host(project, idx))
    cwd = "" if is_remote else review_cwd(project, idx)
    if not is_remote and (not cwd or not os.path.isdir(cwd)):
        return {"ok": False, "error": f"project folder not found: {project}"}
    p = sw.paths_for(cfg.sid)
    targets = current_targets(cfg)
    if mode or model:
        if mode not in rv.MODES or not model:
            return {"ok": False, "error": "mode must be agy|evren|claude|codex|copilot and model is required"}
        mname, meff = rv.split_spec(model)    # `model@effort`: aynı modelin ayrı effort çifti
        known = [x for x in targets if x.mode == mode and x.model == mname and (not meff or x.effort == meff)]
        if targets and not known:
            return {"ok": False, "error": f"unknown target: {mode}/{model}"}
        target = known[0] if known else rv.ReviewTarget(mode, mname, rv.slug_model(mname), meff)
    else:
        hist = rv.load_history(p)
        pool = {"projects": {project: {"enabled": True}}}
        slots0 = rv.parse_slots(getattr(cfg, "review_slots", ""))
        nxt = rv.next_review(pool, hist, [x for x in targets if not slots0 or slots0.get(x.mode, 1) > 0], time.time())
        if nxt is None:
            return {"ok": False, "error": "no pending target for this project"}
        target = nxt[1]
    slots = rv.parse_slots(getattr(cfg, "review_slots", ""))
    busy = busy_keys()
    if not slots and busy:
        return {"ok": False, "busy": True, "error": "another review is running"}
    if slots:       # yuva kipi: yerel kopya `git pull`u başlamadan, aynı proje / dolu ya da kapalı mod burada reddedilir
        if slots.get(target.mode, 1) <= 0:
            return {"ok": False, "error": f"{target.mode} is disabled (0 slots)"}
        if any(k.split("|", 1)[0] == project for k in busy):
            return {"ok": False, "busy": True, "error": "a review of this project is running"}
        if sum(1 for k in busy if _key_mode(k) == target.mode) >= slots.get(target.mode, 1):
            return {"ok": False, "busy": True, "error": f"{target.mode} slots are full"}
    if is_remote:
        if target.mode != "evren":
            return {"ok": False, "error": "remote review runs evren (ucli) targets only"}
        ready, msg = remote_ready(project, idx)
    else:
        ready, msg = prepare_project(project, idx)
    if not ready:
        sw.log_event("review_copy_not_ready", paths=p, project=project, error=msg)
        return {"ok": False, "error": msg}
    res = start_job(p, cfg, project, target, cwd)
    return {k: v for k, v in res.items() if k not in ("thread", "argv")}


def cancel_action(cfg: Any, project: str = "") -> Dict[str, Any]:
    c = cancel_all(cfg.sid, str(project or "").strip())
    return {"ok": True, "cancelled": c}


# ── bulgu akışı (adım 7) ──────────────────────────────────────────────────────
# Karar okuma: reviewer kimliği oturuma YAZMAZ, oturum AÇMAZ, `_target`tan geçmez. Sahibin oturumunun son asistan
# metnini `web_steward` kendi yalnız-okuma görünüm yolundan (`_collect_views`) verir: `fn(proje) -> (oturum, metin)`
# ya da None (sahip yok / uzak / çalışan oturum yok / birden çok oturum). Bu modül web_steward'ı içe aktarmaz.

_VERDICT_READER: Optional[Callable[[str], Optional[Tuple[str, str]]]] = None


def set_verdict_reader(fn: Optional[Callable[[str], Optional[Tuple[str, str]]]]) -> None:
    global _VERDICT_READER
    _VERDICT_READER = fn


def process_verdicts(cfg: Any, now: Optional[float] = None) -> List[str]:
    """`verify_sent` bulguların projeleri için sahibin oturumunun son yanıtındaki `STEWARD-REVIEW-VERDICT` satırlarını
    işler (`rv.scan_verdicts` + `rv.apply_verdicts`). Uygulanan fid'ler döner."""
    reader = _VERDICT_READER
    if reader is None:
        return []
    t = time.time() if now is None else now
    p = sw.paths_for(cfg.sid)
    data = rv.load_findings(p)
    projects = sorted({str(v.get("project")) for v in data.values()
                       if isinstance(v, dict) and v.get("state") == "verify_sent" and v.get("project")
                       and v.get("verify_session") != "self"})     # kendi doğrulama sonucunu kendi thread'i uygular
    applied: List[str] = []
    with sw.steward_lock(p):       # cevapsız kalan oturum doğrulaması yeniden sıraya (karar yalnız son mesajdan okunur)
        cur0 = rv.load_findings(p)
        requeued = rv.requeue_stale_verify(cur0, t)
        if requeued:
            rv.save_findings(p, cur0)
    if requeued:
        sw.log_event("review_verify_requeued", paths=p, findings=requeued)
    for proj in projects:
        got = reader(proj)
        if not got:
            continue
        session, text = got
        verdicts = rv.scan_verdicts(text)
        if not verdicts:
            continue
        h = rv.text_hash(text)
        with sw.steward_lock(p):
            cur = rv.load_findings(p)
            done = rv.apply_verdicts(cur, proj, verdicts, h, session, t)
            if done:
                rv.save_findings(p, cur)
        if done:
            sw.log_event("review_verdicts", paths=p, project=proj, session=session, findings=done,
                         verdicts={f: cur[f]["state"] for f in done})
            applied.extend(done)
    return applied


# ── kendi doğrulama (TBD#137 a=A): reviewer'ın salt-okunur `claude -p` Sonnet süreci, proje oturumu uyanmaz ──────────

SELF_VERIFY_MODEL = "claude-sonnet-5-5"
SELF_VERIFY_TIMEOUT = 900.0          # sn; aşılırsa süreç sonlandırılır, bulgular yeniden denenir
SELF_VERIFY_MAX_TRIES = 3            # bulgu başına; dolunca `unclear` (elle bakılır)
_SELF_VERIFY: Dict[str, threading.Thread] = {}     # proje -> canlı doğrulama thread'i
_SELF_VERIFY_LOCK = threading.Lock()


def self_verify_running(project: str = "") -> bool:
    with _SELF_VERIFY_LOCK:
        for k, t in list(_SELF_VERIFY.items()):
            if not t.is_alive():
                _SELF_VERIFY.pop(k, None)
        return bool(_SELF_VERIFY) if not project else project in _SELF_VERIFY


def _self_verify_fail(p: Any, fids: Sequence[str], reason: str, now: float) -> None:
    """Çalışmayan/eksik doğrulama: bulgu `new`e döner (`verify_tries`+1); deneme hakkı bitince `unclear`."""
    with sw.steward_lock(p):
        data = rv.load_findings(p)
        for fid in fids:
            rec = data.get(fid)
            if not isinstance(rec, dict) or rec.get("state") != "verify_sent" or rec.get("verify_session") != "self":
                continue
            tries = int(rec.get("verify_tries") or 0) + 1
            if tries >= SELF_VERIFY_MAX_TRIES:
                rec.update(state="unclear", verdict=f"otomatik doğrulama {tries} denemede sonuç vermedi: {reason}"[:rv.VERDICT_REASON_MAX],
                           verdict_at=now, verify_tries=tries)
            else:
                rec.update(state="new", verify_tries=tries)
        rv.save_findings(p, data)


def _self_verify_run(cfg: Any, project: str, rows: List[Dict[str, Any]], cwd: str, popen: Optional[Callable],
                     now: Callable[[], float]) -> List[str]:
    p = sw.paths_for(cfg.sid)
    fids = [r["id"] for r in rows]
    from ..settings import resolved_binary
    effort = str(getattr(cfg, "review_claude_effort", "") or "low")
    argv = claude_argv(resolved_binary("claude"), SELF_VERIFY_MODEL, effort, rv.build_self_verify_prompt(rows, getattr(cfg, "lang", "tr")))
    out = ""
    try:
        proc = (popen or _default_popen)(argv, cwd=cwd, env=clean_env({"DISABLE_AUTOUPDATER": "1"}), stdin=subprocess.DEVNULL,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            out, _err = proc.communicate(timeout=SELF_VERIFY_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            _self_verify_fail(p, fids, "zaman aşımı", now())
            return []
        if getattr(proc, "returncode", 0) not in (0, None):
            _self_verify_fail(p, fids, f"rc={proc.returncode}", now())
            return []
    except Exception as e:      # süreç açılamadı
        sw.log_event("review_self_verify_failed", paths=p, project=project, error=_tail(repr(e)))
        _self_verify_fail(p, fids, "başlatılamadı", now())
        return []
    verdicts = [v for v in rv.scan_verdicts(out) if v[0] in set(fids)]
    h = rv.text_hash(out)
    with sw.steward_lock(p):
        cur = rv.load_findings(p)
        done = rv.apply_verdicts(cur, project, verdicts, h, "self", now())
        if done:
            rv.save_findings(p, cur)
    missing = [f for f in fids if f not in done]
    if missing:
        _self_verify_fail(p, missing, "kararsız/eksik çıktı", now())
    if done:
        sw.log_event("review_verdicts", paths=p, project=project, session="self", findings=done)
    return done


def self_verify(cfg: Any, project: str, rows: List[Dict[str, Any]], *, popen: Optional[Callable] = None,
                now: Callable[[], float] = time.time, background: Optional[bool] = None) -> Dict[str, Any]:
    """`rows`u (verify_candidates çıktısı) reviewer'ın KENDİ salt-okunur `claude -p` sürecine doğrulatır; proje oturumu
    uyanmaz. Bulgular önce `verify_sent` (`verify_session=self`), sonuçla `verified|refuted|unclear`; süreç düşerse/karar
    eksikse `new`e döner (en çok `SELF_VERIFY_MAX_TRIES`). Proje başına tek canlı doğrulama. Arka planda koşar
    (`_REVIEW_BACKGROUND`; testte eşzamanlı)."""
    project = str(project or "").strip()
    if not rows:
        return {"ok": False, "error": "no findings to verify"}
    cwd = review_cwd(project)
    if not cwd or not os.path.isdir(cwd):
        return {"ok": False, "code": "no_cwd", "error": f"project {project!r} has no local folder to verify against"}
    with _SELF_VERIFY_LOCK:
        t = _SELF_VERIFY.get(project)
        if t is not None and t.is_alive():
            return {"ok": False, "code": "already_running", "error": f"a verification for {project!r} is already running"}
    p = sw.paths_for(cfg.sid)
    marked = rv.mark_verify_sent(p, [r["id"] for r in rows], "self", "", now())
    if not marked:
        return {"ok": False, "error": "no findings in a verifiable state"}
    rows = [r for r in rows if r["id"] in set(marked)]
    sw.log_event("review_verify", paths=p, project=project, session="self", findings=marked, source="self")
    bg = _REVIEW_BACKGROUND if background is None else background
    if bg:
        th = threading.Thread(target=_self_verify_run, args=(cfg, project, rows, cwd, popen, now), daemon=True,
                              name=f"self-verify-{project}")
        with _SELF_VERIFY_LOCK:
            _SELF_VERIFY[project] = th
        th.start()
    else:
        _self_verify_run(cfg, project, rows, cwd, popen, now)
    return {"ok": True, "project": project, "session": "self", "findings": marked}


def recover_self_verify(paths: Any) -> int:
    """Servis yeniden başlayınca canlı thread'i olmayan `verify_session=self` + `verify_sent` bulgular `new`e döner."""
    p = sw._pp(paths)
    live = {k for k, t in list(_SELF_VERIFY.items()) if t.is_alive()}
    stuck = [k for k, v in rv.load_findings(p).items() if isinstance(v, dict) and v.get("state") == "verify_sent"
             and v.get("verify_session") == "self" and v.get("project") not in live]
    if stuck:
        _self_verify_fail(p, stuck, "yeniden başlatma", time.time())
    return len(stuck)


def bulk_decide(cfg: Any, action: str, project: str = "", fids: Optional[Sequence[str]] = None,
                severities: Optional[Sequence[str]] = None, now: Optional[float] = None) -> Dict[str, Any]:
    """Toplu onay/ret (TBD#137 b): SAHİBİN çağrısı. `fids` verilirse yalnız onlar; yoksa `verified` bulgular (isteğe bağlı
    proje ve önem süzgeci). `approve` yalnız `verified|unclear`, `reject` kararsızlara; geçersiz olanlar `skipped`."""
    if action not in ("approve", "reject"):
        return {"ok": False, "error": "action must be approve or reject"}
    t = time.time() if now is None else now
    p = sw.paths_for(cfg.sid)
    data = rv.load_findings(p)
    if fids:
        targets = [str(f) for f in fids]
    else:
        targets = [k for k, v in sorted(data.items()) if isinstance(v, dict) and v.get("state") == "verified"
                   and (not project or v.get("project") == project)
                   and (not severities or str(v.get("severity") or "") in set(severities))]
    done: List[str] = []
    skipped: List[str] = []
    for fid in targets:
        if rv.decide_finding(p, fid, action, t, by="owner").get("ok"):
            done.append(fid)
        else:
            skipped.append(fid)
    if done:
        sw.log_event("review_bulk_decide", paths=p, action=action, project=project, findings=done)
    return {"ok": True, "action": action, "done": done, "skipped": skipped}


AUTO_APPROVE_SEVERITIES = {1: ("P3",), 2: ("P2", "P3")}     # `review_auto_approve` düzeyi -> otomatik onaylanabilir önem; P1 ASLA


def auto_approve(cfg: Any, now: Optional[float] = None) -> List[str]:
    """`review_auto_approve` > 0 ise `verified` bulguları KENDİLİĞİNDEN onaylar (`decided_by=auto`): yalnız düzeyin önem
    kümesi (1 = P3, 2 = P2+P3); `unclear`, P1 ve başlık/yer/gövdesinde parola/gizli değer geçen bulgu sahibe kalır.
    Dosyaya YAZMAZ (export ayrı adım). Onaylananların fid'leri döner."""
    sev = AUTO_APPROVE_SEVERITIES.get(int(getattr(cfg, "review_auto_approve", 0) or 0))
    if not sev:
        return []
    t = time.time() if now is None else now
    p = sw.paths_for(cfg.sid)
    done: List[str] = []
    for fid, rec in sorted(rv.load_findings(p).items()):
        if not isinstance(rec, dict) or rec.get("state") != "verified" or str(rec.get("severity") or "") not in sev:
            continue
        if sa.is_sensitive(dict(rec, title=f"{rec.get('title') or ''} {rec.get('body') or ''}")):
            continue
        if rv.decide_finding(p, fid, "approve", t, by="auto").get("ok"):
            done.append(fid)
    if done:
        sw.log_event("review_auto_approve", paths=p, findings=done, level=int(cfg.review_auto_approve))
    return done


BEFORE_TBD_STATES = ("unclear", "refuted")     # başka yerde kalıcı olmayan bulgular (exported/approved zaten projenin TODO/TBD'sinde)


def before_tbd(cfg: Any, now: Optional[float] = None) -> List[str]:
    """`review_before_tbd_dir` doluysa `unclear`/`refuted` bulguları `<klasör>/BEFORETBD-<tarih>.md` sonuna ekler (özel
    repo klasörü; commit/push OTOMATİK DEĞİL). Tek yazım: başlıktaki bulgu kimliği herhangi bir `BEFORETBD*.md`te varsa
    atlanır. Parola/gizli değer geçen bulgunun gövdesi YAZILMAZ. Yazılan fid'ler döner."""
    root = str(getattr(cfg, "review_before_tbd_dir", "") or "").strip()
    if not root or not os.path.isdir(root):
        return []
    t = time.time() if now is None else now
    p = sw.paths_for(cfg.sid)
    rows = [(fid, rec) for fid, rec in sorted(rv.load_findings(p).items())
            if isinstance(rec, dict) and rec.get("state") in BEFORE_TBD_STATES]
    if not rows:
        return []
    seen = ""
    for name in sorted(os.listdir(root)):
        if name.startswith("BEFORETBD") and name.endswith(".md"):
            try:
                with open(os.path.join(root, name), encoding="utf-8") as f:
                    seen += f.read()
            except OSError:
                pass
    blocks: List[str] = []
    done: List[str] = []
    for fid, rec in rows:
        if f"## {fid} |" in seen:
            continue
        secret = sa.is_sensitive(dict(rec, title=f"{rec.get('title') or ''} {rec.get('body') or ''}"))
        body = "(parola/gizli değer geçtiği için gövde yazılmadı)" if secret else " ".join(str(rec.get("body") or "").split())[:1500]
        blocks.append(f"## {fid} | {rec.get('severity') or '?'} | {rec.get('state')}\n"
                      f"- Yer: `{rec.get('where') or '?'}`\n"
                      f"- Başlık: {' '.join(str(rec.get('title') or '').split())}\n"
                      f"- Doğrulama: {' '.join(str(rec.get('verdict') or '').split()) or '-'}\n"
                      f"- Bulgu gövdesi: {body}\n")
        done.append(fid)
    if not blocks:
        return []
    path = os.path.join(root, f"BEFORETBD-{time.strftime('%Y-%m-%d', time.localtime(t))}.md")
    head = "" if os.path.exists(path) else ("# BEFORETBD: reviewer bulguları, başka yerde kalıcı olmayanlar (belirsiz / çürütülen)\n"
                                           "> Otomatik yazıldı (review_before_tbd_dir). Sahip karar verir: karar verilemedi / saçma / TBD'ye taşı.\n")
    with open(path, "a", encoding="utf-8") as f:
        f.write(head + "\n" + "\n".join(blocks))
    sw.log_event("review_before_tbd", paths=p, file=path, findings=done)
    return done


_STORE_TS = re.compile(r"^\d{14}$")
STORE_SUFFIXES = (".md", ".usage.jsonl")      # rapor (maskeli) + yalnız sayılar; `.io.jsonl`/`.model.md`/hata günlüğü SAKLANMAZ


def store_commit(cfg: Any, now: float, run: Optional[Callable] = None) -> int:
    """TBD#118 ek: `review_store_commit` açıksa günde bir (`review_store_commit.json`) `review_store_dir/reviews/` altındaki
    yeni dosyalar -prv depoya commit+push edilir. İlk çalışma KURU (yalnız `would` günlüğe: hangi dosyalar eklenirdi);
    sonraki günlük tur act. Gizli değer taramasını geçemeyen dosyalar dışarıda kalır ve sahibe tek soruyla bildirilir.
    Dönen: commit edilen dosya sayısı."""
    root = str(getattr(cfg, "review_store_dir", "") or "").strip()
    if not getattr(cfg, "review_store_commit", False) or not root or not os.path.isdir(root):
        return 0
    p = sw.paths_for(cfg.sid)
    sp = os.path.join(p.root, "review_store_commit.json")
    try:
        with open(sp, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    if not isinstance(st, dict):
        st = {}
    if st.get("last_at") is not None and now - float(st["last_at"]) < rs.STORE_COMMIT_INTERVAL:
        return 0
    dry = not st.get("dry_done")
    res = rs.commit_reviews(root, str(getattr(cfg, "review_store_git_dir", "") or ""),
                            lambda txt: rv.redact_secrets(txt), dry=dry, run=run)
    st.update(last_at=now, dry_done=True if res.get("ok") else st.get("dry_done"))
    tmp = sp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.replace(tmp, sp)
    sw.log_event("review_store_commit", paths=cfg.sid, dry=dry, ok=res.get("ok"), would=res.get("would"),
                 held=res.get("held"), committed=res.get("committed"), pushed=res.get("pushed"), error=res.get("error"))
    if res.get("held"):
        q = sw.add_question("", f"review saklama: gizli değer taramasını geçemeyen {len(res['held'])} dosya -prv commit'inin DIŞINDA kaldı: "
                                + ", ".join(list(res["held"])[:5]), source="reviewer-store", options=["Tamam"], paths=p)
        if _NOTIFY_FN is not None:
            try:
                _NOTIFY_FN(cfg.sid, q)
            except Exception:
                pass
    return int(res.get("committed") or 0)


_STORE_DENIED: Dict[str, str] = {}   # `review_store_denied` olayı aynı nedenle bir kez


def store_reports(cfg: Any) -> List[str]:
    """TBD#118 ilk dilim: `review_store_dir` (sahibin ÖZEL klasörü) doluysa `reviews/<proje>/<mode>/<model>/<effort>/<ts>/` altındaki
    biten koşunun raporu ve sayaç günlüğü `<klasör>/reviews/...` altına AYNI göreli yolla kopyalanır (var olan dosya yeniden
    yazılmaz). Git komutu ÇALIŞTIRILMAZ (add/commit/push sahibin ya da ayrı bir kararın işi, `before_tbd` ile aynı duruş).
    Dönen: kopyalanan göreli yollar."""
    root = str(getattr(cfg, "review_store_dir", "") or "").strip()
    if not root or not os.path.isdir(root):
        return []
    src_root = sw._pp(cfg.sid).reviews
    dst_root = os.path.join(os.path.realpath(root), "reviews")
    if os.path.realpath(dst_root).startswith(os.path.realpath(src_root) + os.sep):
        return []              # hedef kaynağın içinde: özyineleme
    ok, why = rs.dest_guard(dst_root)
    if not ok:             # TBD#118: public (ya da bilinmeyen) bir deponun izlenebilir yoluna kopyalama
        if _STORE_DENIED.get(root) != why:
            _STORE_DENIED[root] = why
            sw.log_event("review_store_denied", paths=cfg.sid, root=root, reason=why)
        return []
    copied: List[str] = []
    for dirpath, _dirs, files in os.walk(src_root):
        ts = os.path.basename(dirpath)
        if not _STORE_TS.match(ts):
            continue
        for name in sorted(files):
            if not (name.startswith(ts) and name.endswith(STORE_SUFFIXES)) or name.endswith(".model.md") or ".err" in name:
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), src_root)
            dst = os.path.join(dst_root, rel)
            if os.path.exists(dst) or os.path.islink(os.path.join(dirpath, name)):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = f"{dst}.{os.getpid()}.tmp"
            shutil.copyfile(os.path.join(dirpath, name), tmp)
            os.replace(tmp, dst)
            copied.append(rel)
    if copied:
        sw.log_event("review_store", paths=cfg.sid, root=root, n=len(copied))
    return copied


def verify_candidates(cfg: Any, project: str, fids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Doğrulanacak bulgular: `fids` verildiyse onlar (yalnız bu projenin ve `VERIFIABLE_STATES`teki), yoksa projenin
    `new` bulguları; önem sırasıyla, en çok `VERIFY_MAX_FINDINGS`."""
    data = rv.load_findings(sw.paths_for(cfg.sid))
    rows = []
    for k, v in data.items():
        if not isinstance(v, dict) or v.get("project") != project:
            continue
        if fids:
            if k in fids and v.get("state") in rv.VERIFIABLE_STATES:
                rows.append(dict(v, id=k))
        elif v.get("state") == "new":
            rows.append(dict(v, id=k))
    rows.sort(key=lambda r: (str(r.get("severity") or "P9"), str(r.get("review_file")), str(r.get("ref"))))
    return rows[:rv.VERIFY_MAX_FINDINGS]


def decide(cfg: Any, fid: str, action: str, now: Optional[float] = None) -> Dict[str, Any]:
    fid = str(fid or "").strip()
    if not fid:
        return {"ok": False, "error": "finding id required"}
    r = rv.decide_finding(sw.paths_for(cfg.sid), fid, str(action or ""), time.time() if now is None else now)
    if r.get("ok"):
        sw.log_event("review_decide", paths=cfg.sid, id=fid, action=action, state=r["state"], by="owner")
    return r


def auto_export(cfg: Any, now: Optional[float] = None) -> List[str]:
    """`review_auto_export` açıksa YEREL projelerin `approved` bulgularını TODO.md'ye, doğrulanamayan (`unclear`)
    bulgularını TOBEDECIDED.md'ye yazar (`exported_by=auto`); uzak proje (host'lu) ve parola/gizli geçen bulgu atlanır; tick başına EN ÇOK 1
    proje; bir projede hata olursa log + sonrakine geçer. Aynı bulgu iki kez yazılmaz (`appended_export` dosyadakini
    tanır). Yazılan projelerin adları döner."""
    if not getattr(cfg, "review_auto_export", False):
        return []
    t = time.time() if now is None else now
    p = sw.paths_for(cfg.sid)
    remote = set(ownership().get("hosts") or {})
    allf = rv.load_findings(p)
    # onaylı bulgular -> TODO.md; doğrulanamayan (`unclear`, karar gerektirir) bulgular -> TOBEDECIDED.md (tick başına 1 proje)
    for fname, st in (("TODO.md", "approved"), ("TOBEDECIDED.md", "unclear")):
        projects = sorted({str(v.get("project") or "") for v in allf.values()
                           if isinstance(v, dict) and v.get("state") == st} - {""} - remote)
        for proj in projects:
            try:
                res = export_findings(cfg, proj, fname, t, by="auto", states=(st,))
            except Exception as e:
                sw.log_event("review_auto_export_failed", paths=p, project=proj, file=fname, error=_tail(repr(e)))
                continue
            if res.get("ok"):
                sw.log_event("review_auto_export", paths=p, project=proj, file=fname, written=res.get("written"), already=res.get("already"))
                return [proj]
    return []


def _export_remote(cfg: Any, project: str, fname: str, t: float, by: str) -> Dict[str, Any]:
    """Uzak projenin onaylı bulgularını uzak `fname` sonuna yazar (taşıma: `RemoteReviewDriver.export_file`, claudeops
    API'si). Yerel `stale_reason`/`changed_after_review` uzak ağaca bakamaz: atlanır. Hassas bulgu HER ZAMAN atlanır.
    Çift yazma yok: dosyada `(review <id>)` varsa yeniden yazılmaz, yine `exported` sayılır. Dosya yoksa dur ve raporla."""
    host = (ownership().get("hosts") or {}).get(project) or ""
    drv = _REMOTE_FN(project, host) if (host and _REMOTE_FN is not None) else None     # review_where'den bağımsız: dışa aktarım host'a bakar
    if drv is None:
        return {"ok": False, "error": "remote export needs a wired remote driver"}
    p = sw.paths_for(cfg.sid)
    stamp = time.strftime("%Y-%m-%d", time.localtime(t))
    with sw.steward_lock(p):
        data = rv.load_findings(p)
        rows = [dict(v, id=k) for k, v in sorted(data.items())
                if isinstance(v, dict) and v.get("project") == project and v.get("state") == "approved"
                and not sa.is_sensitive(dict(v, title=f"{v.get('title') or ''} {v.get('body') or ''}"))]
    reader = getattr(drv, "read_rel", None)
    if callable(reader) and rows:       # eskimiş bulgu uzak TODO'ya yazılmasın: tanımlayıcı denetimi uzak dosya metniyle
        stale: Dict[str, str] = {}
        cache: Dict[str, Optional[str]] = {}
        for r in rows:
            rel = rv.where_relpath(r) if rv.has_quoted_names(r) else ""     # alıntılı ad yoksa karar verilemez: uzak okuma yok
            if not rel:
                continue
            if rel not in cache:
                try:
                    cache[rel] = reader(rel)
                except Exception:
                    cache[rel] = None
            why = rv.stale_reason_text(r, cache[rel])
            if why:
                stale[r["id"]] = why
        if stale:
            with sw.steward_lock(p):
                data = rv.load_findings(p)
                for fid, why in stale.items():
                    if fid in data and data[fid].get("state") == "approved":
                        data[fid].update(state="rejected", decided_by="stale-check", decided_at=t, stale_reason=why)
                rv.save_findings(p, data)
            rows = [r for r in rows if r["id"] not in stale]
    if not rows:
        return {"ok": False, "error": "no approved findings to export", "project": project}
    ids = [r["id"] for r in rows]
    msg = (f"Review bulguları {fname} dosyasına eklendi ({len(ids)} madde, 'Review bulguları' başlığı); sırası geldiğinde bak."
           if getattr(cfg, "lang", "tr") != "en" else
           f"Review findings were appended to {fname} ({len(ids)} items, 'Review bulguları' section); see it when convenient.")
    res = drv.export_file(fname, lambda text: rv.appended_export(text, rows, p.reviews, stamp), msg)
    if not res.get("ok"):
        sw.log_event("review_export_failed", paths=p, project=project, file=fname, error=_tail(str(res.get("error"))))
        return dict(res, project=project)
    written = list(res.get("written") or [])
    already = [i for i in ids if i not in written]
    target = f"{res.get('host')}:{res.get('path')}"
    with sw.steward_lock(p):
        data = rv.load_findings(p)
        for fid in ids:
            if fid in data and data[fid].get("state") == "approved":
                data[fid].update(state="exported", exported_to=target, exported_at=t)
                if by:
                    data[fid]["exported_by"] = by
        rv.save_findings(p, data)
    sw.log_event("review_export", paths=p, project=project, file=fname, written=written, already=already, remote=res.get("host"),
                 **({"by": by} if by else {}))
    return {"ok": True, "project": project, "file": target, "written": written, "already": already,
            "session_open": bool(res.get("session_open")), "notified": bool(res.get("notified")),
            "commit": "not done (no remote shell API); commit/push the remote repo manually" if written else ""}


def export_findings(cfg: Any, project: str, fname: str, now: Optional[float] = None, by: str = "",
                    states: Sequence[str] = ("approved",)) -> Dict[str, Any]:
    """Projenin ONAYLI bulgularını yerel proje klasöründeki `fname` (TODO.md / TOBEDECIDED.md) sonuna
    `## Review bulguları` başlığı altında ekler; yazılanlar `exported` olur (çift dışa aktarma yok). Onaysız bulgu ASLA
    yazılmaz. Uzak proje reddedilir (yerel dosya sistemi ona ait değil)."""
    t = time.time() if now is None else now
    project = str(project or "").strip()
    if not project or not sw.valid_name(project):
        return {"ok": False, "error": "invalid project name"}
    if "/" in fname or ".." in fname or "\x00" in fname or not fname:
        return {"ok": False, "error": "invalid target file"}
    if project in (ownership().get("hosts") or {}):
        return _export_remote(cfg, project, fname, t, by)
    cwd = project_cwd(project)
    if not cwd or not os.path.isdir(cwd):
        return {"ok": False, "error": f"project folder not found: {project}"}
    p = sw.paths_for(cfg.sid)
    target = os.path.join(cwd, fname)
    stamp = time.strftime("%Y-%m-%d", time.localtime(t))
    with sw.steward_lock(p):
        data = rv.load_findings(p)
        rows = [dict(v, id=k) for k, v in sorted(data.items())
                if isinstance(v, dict) and v.get("project") == project and v.get("state") in states
                and not (by == "auto" and sa.is_sensitive(dict(v, title=f"{v.get('title') or ''} {v.get('body') or ''}")))]
        dropped = False
        for r in list(rows):       # koddaki duruma karşı denetim: eskimiş bulgu yazılmaz, değişen dosya işaretlenir
            why = rv.stale_reason(r, cwd)
            if why:
                data[r["id"]].update(state="rejected", decided_by="stale-check", decided_at=t, stale_reason=why)
                rows.remove(r)
                dropped = True
            elif rv.changed_after_review(r, cwd):
                r["note"] = "dosya incelemeden sonra değişti, hâlâ geçerli mi doğrula"
        if dropped:
            rv.save_findings(p, data)
        if not rows:
            return {"ok": False, "error": "no approved findings to export" if tuple(states) == ("approved",) else "no findings to export", "project": project}
        try:
            with open(target, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            text = ""
        new, written = rv.appended_export(text, rows, p.reviews, stamp)
        if new is not None:
            tmp = f"{target}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(new)
            os.replace(tmp, target)
        already = [r["id"] for r in rows if r["id"] not in written]
        for fid in written + already:       # dosyada zaten olan onaylı bulgu da `exported` sayılır (yeniden yazılmaz)
            data[fid].update(state="exported", exported_to=target, exported_at=t)
            if by:
                data[fid]["exported_by"] = by
        rv.save_findings(p, data)
    sw.log_event("review_export", paths=p, project=project, file=fname, written=written, already=already,
                 **({"by": by} if by else {}))
    return {"ok": True, "project": project, "file": target, "written": written, "already": already}
