"""codex (OpenAI Codex CLI) provider.

Farklar (claude/agy'ye göre):
- `--remote-control`/isimlendirme bayrağı YOK → agy gibi COPS_NAME env'iyle çözülüyor
  (spawn'da set edilir, discovery'de `psutil.Process.environ()` ile okunur).
- Resume kaynağı `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl` — claude'un
  jsonl'ına benzer ama CWD-bazlı klasörleme YOK, hepsi tarih altında GLOBAL bir arşiv.
  Resume id'yi bulmak için dosyaları mtime'a göre en yeniden geriye tarayıp ilk satırın
  (session_meta) cwd'sini eşleştiriyoruz — sid dosya adının SONUNDAKİ uuid'den okunur
  (2025-09 ve 2026-09 örneklerinde filename deseni sabit kaldı, iç JSON şeması
  değişmiş olsa bile — canlı doğrulandı, bkz. DONE.md).
- Model listesi CANLI `~/.codex/models_cache.json`'dan okunur (agy'nin `agy models`
  subprocess'inin dosya-okuma muadili, aynı TTL'li cache deseni) — `priority` alanına
  göre sıralanır, `visibility != "list"` olan (iç/gizli) modeller elenir. Boşsa/okunamazsa
  sabit bir fallback listesine düşer (shell_provider'daki IndexError uyarısı burada da
  geçerli: BOŞ liste asla dönmemeli).
- effort için ayrı bir CLI bayrağı YOK — `-c model_reasoning_effort=<seviye>` config
  override'ıyla veriliyor (canlı doğrulandı: rollout dosyasının turn_context'inde
  `"effort"` alanına yansıyor). EFFORT_LEVELS bu makinedeki TÜM seçilebilir modellerin
  ORTAK desteklediği alt küme (low/medium/high/xhigh) — bazı modeller max/ultra'ya kadar
  çıkıyor ama hepsi değil, seçilen modelden bağımsız her zaman geçerli kalsın diye.
- permission_mode iki bağımsız eksenin (`--sandbox` + `--ask-for-approval`) birleşimi
  → agy'nin `_PERMISSION_FLAGS` desenindeki gibi dört isme (auto/acceptEdits/manual/plan)
  eşleniyor; `--dangerously-bypass-approvals-and-sandbox` tek başına "auto".
- COPS_NAME yoksa (elle başlatılmış bare `codex`) isim `codex-<pid>` placeholder'ı olur
  — agy'nin bare-session davranışıyla paralel, ASLA None dönmez (codex'in claude'daki
  gibi bir sessions/*.json self-registration'ı yok).
"""
from __future__ import annotations
import glob
import json
import os
import re
import shlex
import shutil
import time
from typing import Dict, List, Optional

from .base import CliProvider

CODEX_HOME = os.path.expanduser("~/.codex")
SESSIONS_DIR = os.path.join(CODEX_HOME, "sessions")
MODELS_CACHE = os.path.join(CODEX_HOME, "models_cache.json")

PERMISSION_MODES = ["auto", "acceptEdits", "manual", "plan"]
EFFORT_LEVELS = ["low", "medium", "high", "xhigh"]
# models_cache.json okunamazsa/boşsa son çare (2026-09-01 bu makinede canlı doğrulandı:
# gpt-5.6-terra + gpt-5.5 gerçek bir turn tamamladı; config.toml'ın kendi varsayılanı
# "gpt-5-codex" ise bu ChatGPT hesabında 400 ile reddedildi — o yüzden BURADA tekrarlanmıyor).
FALLBACK_MODELS = ["gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4-mini"]

_PERMISSION_FLAGS = {
    "auto": ["--dangerously-bypass-approvals-and-sandbox"],
    "acceptEdits": ["--sandbox", "workspace-write", "--ask-for-approval", "never"],
    "manual": ["--sandbox", "workspace-write", "--ask-for-approval", "on-request"],
    "plan": ["--sandbox", "read-only", "--ask-for-approval", "on-request"],
}

_MODELS_TTL = 300.0  # agy_provider'daki aynı TTL — dosya küçük/lokal ama her 4s status poll'unda yeniden parse etmeye gerek yok
_ROLLOUT_UUID_RE = re.compile(r"-([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})\.jsonl$")
_MAX_ROLLOUT_SCAN = 500  # global arşiv (cwd-bazlı klasörleme yok) büyürse sınırsız taramayı engelle


def _arg(cmd: List[str], flag: str) -> Optional[str]:
    try:
        i = cmd.index(flag)
    except ValueError:
        return None
    return cmd[i + 1] if i + 1 < len(cmd) else None


def _config_value(cmd: List[str], key: str) -> Optional[str]:
    prefix = f"{key}="
    for i, tok in enumerate(cmd):
        if tok in ("-c", "--config") and i + 1 < len(cmd) and cmd[i + 1].startswith(prefix):
            return cmd[i + 1][len(prefix):]
    return None


def _safe_mtime(p: str) -> float:
    try:
        return os.stat(p).st_mtime
    except OSError:
        return 0.0


def _session_meta(path: str) -> Optional[dict]:
    """Rollout dosyasının İLK satırı (session_meta) — cwd eşleşmesi için tek satır
    okumak yeterli, tüm dosyayı (görüşme geçmişi dahil) parse etmeye gerek yok."""
    try:
        with open(path, encoding="utf-8") as f:
            first = f.readline()
        d = json.loads(first)
        if d.get("type") == "session_meta":
            return d.get("payload") or {}
    except (OSError, json.JSONDecodeError):
        pass
    return None


class CodexProvider(CliProvider):
    name = "codex"

    def __init__(self) -> None:
        self._cache_ts = 0.0
        self._cache_models: List[str] = []

    def resolve_resume_id(self, cwd: str) -> Optional[str]:
        target = os.path.normpath(os.path.abspath(cwd))
        files = glob.glob(os.path.join(SESSIONS_DIR, "*", "*", "*", "*.jsonl"))
        files.sort(key=_safe_mtime, reverse=True)
        for path in files[:_MAX_ROLLOUT_SCAN]:
            payload = _session_meta(path)
            if not payload:
                continue
            raw_cwd = payload.get("cwd")
            if not raw_cwd or os.path.normpath(os.path.abspath(str(raw_cwd))) != target:
                continue
            m = _ROLLOUT_UUID_RE.search(os.path.basename(path))
            if m:
                return m.group(1)
            return payload.get("id") or payload.get("session_id")
        return None

    def build_inner_command(self, cwd, model, permission_mode, effort,
                             resume_id, prompt, session_name) -> str:
        # Mutlak yol — bkz. claude_provider.py'deki aynı fix'in yorumu (pane'in kendi
        # PATH'i tmux server'ın miras kaldığından farklı/eksik olabilir).
        binary = shutil.which("codex") or "codex"
        parts = [shlex.quote(binary)]
        if resume_id:
            parts += ["resume", shlex.quote(resume_id)]
        parts += ["--model", shlex.quote(model)]
        parts += ["--config", shlex.quote(f"model_reasoning_effort={effort or 'medium'}")]
        parts += _PERMISSION_FLAGS.get(permission_mode or "auto", _PERMISSION_FLAGS["auto"])
        if prompt:
            parts += [shlex.quote(prompt)]
        return " ".join(parts)

    def env_overrides(self, session_name: str) -> Dict[str, str]:
        return {"COPS_NAME": session_name}

    def matches_proc(self, cmd: List[str]) -> bool:
        return bool(cmd) and os.path.basename(cmd[0]) == "codex"

    def extract_name(self, proc, cmd: List[str]) -> Optional[str]:
        try:
            name = proc.environ().get("COPS_NAME")
        except Exception:
            name = None
        return name or f"codex-{proc.pid}"

    def extract_info(self, cmd: List[str]) -> Dict[str, Optional[str]]:
        sid = cmd[2] if len(cmd) >= 3 and cmd[1] == "resume" else None
        permission_mode = None
        if "--dangerously-bypass-approvals-and-sandbox" in cmd:
            permission_mode = "auto"
        else:
            sandbox = _arg(cmd, "--sandbox")
            approval = _arg(cmd, "--ask-for-approval")
            if sandbox and approval:
                wanted = ["--sandbox", sandbox, "--ask-for-approval", approval]
                for mode_name, flags in _PERMISSION_FLAGS.items():
                    if flags == wanted:
                        permission_mode = mode_name
                        break
        return {
            "sid": sid,
            "model": _arg(cmd, "--model"),
            "permission_mode": permission_mode,
            "effort": _config_value(cmd, "model_reasoning_effort"),
        }

    def model_choices(self) -> List[str]:
        now = time.monotonic()
        if now - self._cache_ts > _MODELS_TTL:
            # Denemeyi başarısız/boş olsa BİLE damgala — agy_provider'daki aynı gerekçe:
            # yoksa TTL asla dolmaz, panel her 4s status poll'unda yeniden dosya okur.
            self._cache_ts = now
            try:
                with open(MODELS_CACHE, encoding="utf-8") as f:
                    data = json.load(f)
                listed = [m for m in data.get("models", [])
                          if m.get("visibility") == "list" and m.get("slug")]
                listed.sort(key=lambda m: m.get("priority", 999))
                slugs = [m["slug"] for m in listed]
                if slugs:
                    self._cache_models = slugs
            except (OSError, json.JSONDecodeError, TypeError, AttributeError):
                pass  # eski (belki boş) cache kalır — status endpoint'i asla patlamasın
        return self._cache_models or FALLBACK_MODELS

    def permission_modes(self) -> List[str]:
        return PERMISSION_MODES

    def effort_levels(self) -> List[str]:
        return EFFORT_LEVELS
