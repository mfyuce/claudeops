"""reviewer değnekçi motoru (adım 2: yalnız iskelet).

`web_steward.tick_round`, rolü `reviewer` olan ve AÇIK kimlik için `tick_once`/`passive_scan`/kart/beyin/kapatma
yerine YALNIZ `review_tick(cfg)` çağırır. reviewer kimliği hiçbir tmux oturumuna dokunmaz (`web_steward._target` onu
her zaman reddeder), `projects.json`'a yazmaz (`steward.upsert_project`/`transfer_project` `ReviewerRefused`), beyni
yoktur (`brain_start` reddeder); havuzu `review_pool.json`, geçmişi `review_history.json` (`review.py` saf çekirdeği).

Adım 5'te doldurulacak: havuz eşitleme (`review.pool_sync`), sıradaki çift (`review.next_review`), Evren/agy
çalıştırıcıları (kendi `Popen`'ı, zaman aşımı, iptal), sonuç dosyası + bulgu çıkarımı.

Bu modül `web.py`'yi ve `web_steward`'ı İÇE AKTARMAZ (döngü yok; eylemler gerekirse geri çağrıyla verilir)."""
import json
import os
import signal
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import review as rv
from .. import steward as sw
from .. import ucli_client

REVIEW_ENV_PREFIXES = ("CLAUDE", "GEMINI", "ANTIGRAVITY")   # spawn.py deseni: bu süreç kendi oturum kimliğini çocuğa sızdırmaz
KILL_GRACE_SECONDS = 10.0                                   # SIGTERM -> SIGKILL aralığı
AGY_LOG_DIR = os.path.expanduser("~/.gemini/antigravity-cli/log")
UCLI_KEY_FILE = os.path.expanduser("~/.claude/claudeops/ucli_api_key")
EVREN_MAX_STEPS = 200
EVREN_MAX_IO_MIB = 2048
STDERR_KEEP = 300

# Süreç geneli TEK çalıştırma kilidi (claudeops'un `_LOCK`'u ile ilgisi YOK, onu TUTMA). Çalışırken iş thread'inde tutulur.
_REVIEW_LOCK = threading.Lock()
_JOBS: Dict[str, "_Job"] = {}
_JOBS_LOCK = threading.Lock()


class _Job:
    def __init__(self, key: str) -> None:
        self.key = key
        self.proc: Any = None
        self.cancelled = False


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


def evren_argv(binary: str, cwd: str, model: str, prompt: str, endpoint: str, supports_io: bool) -> List[str]:
    """`ucli --root <cwd> chat --model M --endpoint E --api-key-env UCLI_API_KEY --max-steps 200 [--max-io-mib N] <prompt>`.
    --allow-edit/--allow-create ASLA (varsayılan salt okunur); anahtar argv'de DEĞİL, yalnız süreç ortamında."""
    return ucli_client.build_chat_argv(
        binary, cwd, repl=False, session=None, model=model, endpoint=endpoint, api_key_env="UCLI_API_KEY",
        with_mcp=False, max_steps=EVREN_MAX_STEPS,
        extra_args=(["--max-io-mib", str(EVREN_MAX_IO_MIB)] if supports_io else [])) + [prompt]


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


def _first_new_agy_log(log_dir: str, since: float) -> str:
    """Koşu BAŞLANGICINDAN (mtime >= since) yeni ilk `cli-*.log` içeriği; yoksa ""."""
    try:
        cands = []
        for n in os.listdir(log_dir):
            if n.startswith("cli-") and n.endswith(".log"):
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


def cancel_job(project: str, target: rv.ReviewTarget) -> bool:
    """Çalışan işi iptal eder: SIGTERM, `KILL_GRACE_SECONDS` sonra hâlâ yaşıyorsa SIGKILL. Çalışan iş yoksa False."""
    with _JOBS_LOCK:
        job = _JOBS.get(rv.pair_key(project, target))
    if job is None or job.proc is None:
        return False
    job.cancelled = True
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


def _extract_text(mode: str, stdout: str) -> Tuple[str, str]:
    """(metin, hata). Evren: JSON `answer`; bozuk/yarım JSON'da ham metin (kısmi çıktı kaybolmasın)."""
    if mode != "evren":
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


def _write_report(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def _tail(s: str) -> str:
    s = rv.redact_secrets((s or "").strip())
    return s[-STDERR_KEEP:]


def _execute(job: _Job, paths: Any, cfg: Any, project: str, target: rv.ReviewTarget, argv: List[str], env: Dict[str, str],
             cwd: str, path: str, started: float, popen: Callable, agy_log_dir: str, now: Callable[[], float]) -> None:
    key = job.key
    try:
        try:
            proc = popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
        except OSError as e:
            rv.update_pair(paths, project, target, status="error", finished_at=now(), error=f"spawn: {e}")
            return
        job.proc = proc
        rv.update_pair(paths, project, target, pid=getattr(proc, "pid", None))
        timed_out = False
        timeout = max(1.0, float(getattr(cfg, "review_timeout_minutes", 45)) * 60.0)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate(proc, KILL_GRACE_SECONDS)
            out, err = proc.communicate()
        out, err = out or "", err or ""
        text, jerr = _extract_text(target.mode, out)
        text = rv.redact_secrets(text)
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
            status, error = "error", _tail(jerr)
        elif rc == 0 and text.strip():
            status, error = "done", ""
        elif text.strip():
            status, error = "partial", f"exit={rc} {_tail(err)}".strip()
        else:
            status, error = "error", f"exit={rc} {_tail(err)}".strip()
        if target.mode == "agy" and status in ("done", "partial"):
            ok, seen = rv.agy_label_ok(_first_new_agy_log(agy_log_dir, started), target.model)
            fields["label_seen"] = seen
            if not ok:
                # dosya saklanır ama done sayılmaz: agy planda olmayan modeli sessizce başka modele düşürür
                status, error = "model_fallback", f"agy etiket uyuşmadı: istenen={target.model} görülen={seen or '(yok)'}"
        fields.update(status=status, error=error)
        rv.update_pair(paths, project, target, **fields)
    except Exception as e:   # çalıştırıcı asla `running` bırakıp ölmesin
        try:
            rv.update_pair(paths, project, target, status="error", finished_at=now(), error=_tail(f"{type(e).__name__}: {e}"))
        except Exception:
            pass
    finally:
        with _JOBS_LOCK:
            _JOBS.pop(key, None)
        _REVIEW_LOCK.release()


def run_job(paths: Any, cfg: Any, project: str, cwd: str, target: rv.ReviewTarget, *,
            popen: Callable = subprocess.Popen, now: Callable[[], float] = time.time,
            ucli_bin: Optional[str] = None, agy_bin: Optional[str] = None, agy_log_dir: str = AGY_LOG_DIR,
            agy_models: Optional[List[str]] = None, provider: Any = None, api_key: Optional[str] = None,
            endpoint_fn: Optional[Callable[[], str]] = None, supports_flag: Optional[Callable[[str, str], bool]] = None,
            lang: str = "tr") -> Dict[str, Any]:
    """Bir (proje, mod, model) çiftinin review'ını arka plan thread'inde başlatır; hemen döner. Süreç genelinde aynı anda
    TEK iş (`_REVIEW_LOCK`); meşgulse `{"ok": False, "busy": True}`. Sonuç `review_history.json`a yazılır."""
    p = sw._pp(paths)
    key = rv.pair_key(project, target)
    if not _REVIEW_LOCK.acquire(blocking=False):
        return {"ok": False, "busy": True, "error": "başka bir review çalışıyor"}
    t0 = now()
    try:
        prompt = rv.build_review_prompt(project, cwd, lang)
        env_extra: Dict[str, str] = {}
        if target.mode == "evren":
            from ..providers import ucli_provider as up
            binary = ucli_client.resolve_binary(ucli_bin)
            sup = (supports_flag or ucli_client.binary_supports_flag)(binary, "--max-io-mib")
            argv = evren_argv(binary, cwd, target.model, prompt, (endpoint_fn or up.endpoint)(), bool(sup))
            key_val = api_key if api_key is not None else _api_key()
            if not key_val:
                raise RuntimeError("Evren API anahtarı yok")
            env_extra["UCLI_API_KEY"] = key_val
        elif target.mode == "agy":
            from ..providers.agy_provider import AgyProvider
            from ..settings import resolved_binary
            prov = provider or AgyProvider()
            models = agy_models if agy_models is not None else prov.model_choices()
            if target.model not in models:
                raise RuntimeError(f"agy model listesinde yok: {target.model}")
            argv = agy_argv(agy_bin or resolved_binary("agy"), target.model, prompt, prov)
        else:
            raise RuntimeError(f"bilinmeyen mod: {target.mode}")
        rv.update_pair(p, project, target, status="running", started_at=t0, finished_at=None, file=None, error=None,
                       label_seen=None, pid=None)
        job = _Job(key)
        with _JOBS_LOCK:
            _JOBS[key] = job
        path = rv.review_path(p.reviews, project, target, t0)
        th = threading.Thread(target=_execute, daemon=True, name=f"review-{key}",
                              args=(job, p, cfg, project, target, argv, clean_env(env_extra), cwd, path, t0, popen,
                                    agy_log_dir, now))
        th.start()
    except Exception as e:
        _REVIEW_LOCK.release()
        try:
            rv.update_pair(p, project, target, status="error", started_at=t0, finished_at=now(), error=_tail(str(e)))
        except Exception:
            pass
        return {"ok": False, "error": str(e)}
    return {"ok": True, "key": key, "file": path, "thread": th, "argv": argv}


def recover_on_start(paths: Any, now: Callable[[], float] = time.time) -> int:
    """Servis yeniden başlayınca `running` kalan çiftler (süreç ölmüştür) `partial` olur. Kaç çift düzeltildi."""
    p = sw._pp(paths)
    n = 0
    with sw.steward_lock(p):
        hist = rv.load_history(p)
        for key, rec in hist["pairs"].items():
            if isinstance(rec, dict) and rec.get("status") == "running":
                rec.update(status="partial", finished_at=now(), pid=None, error="yeniden başlatma: koşu yarıda kaldı")
                hist["runs"].append({"pair": key, "status": "partial", "at": rec["finished_at"], "file": rec.get("file")})
                n += 1
        if n:
            rv.save_history(p, hist)
    return n


def review_tick(cfg: sw.Config) -> Dict[str, Any]:
    """Bir reviewer kimliğinin döngü turu. Şimdilik no-op: hiçbir dosyaya/oturuma/sürece dokunmaz."""
    return {"ok": True, "actions": [], "started": 0, "noop": True}
