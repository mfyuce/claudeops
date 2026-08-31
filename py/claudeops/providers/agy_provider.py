"""agy (Google Antigravity CLI) provider.

Farklar (claude'a göre):
- `--remote-control NAME` muadili YOK → isimlendirme `COPS_NAME` env değişkeniyle
  (spawn'da set edilir, discovery'de `psutil.Process.environ()` ile okunur).
- Resume kaynağı `~/.gemini/antigravity-cli/cache/last_conversations.json`
  (cwd → conversation-id sözlüğü), claude'un jsonl-tabanlı `find_latest_jsonl`'ının
  muadili.
- Model listesi CANLI çekilir (`agy models`, TTL'li cache) — sabit kodlanmaz,
  liste zaten 2 günde bir kez değişti.
- effort için ayrı bir `--effort low|medium|high` flag'i var (model id'sinden
  bağımsız) — permission ise TEK bir `--permission-mode`-benzeri flag değil,
  ya `--dangerously-skip-permissions` ya da `--mode accept-edits|plan`.
- COPS_NAME yoksa (elle başlatılmış bare `agy`) isim `agy-<pid>` placeholder'ı
  olur — claude'daki bare-session/"kayıtsız" davranışıyla paralel; ASLA None
  dönmez (agy'nin claude'un sessions/*.json'ı gibi kendi self-registration'ı yok).
"""
from __future__ import annotations
import json
import os
import shlex
import shutil
import subprocess
import time
from typing import Dict, List, Optional

from .base import CliProvider

CONVERSATIONS_CACHE = os.path.expanduser("~/.gemini/antigravity-cli/cache/last_conversations.json")

PERMISSION_MODES = ["auto", "acceptEdits", "plan"]
EFFORT_LEVELS = ["low", "medium", "high"]

_PERMISSION_FLAGS = {
    "auto": ["--dangerously-skip-permissions"],
    "acceptEdits": ["--mode", "accept-edits"],
    "plan": ["--mode", "plan"],
}

_MODELS_TTL = 300.0  # agy models sabit değil (2 günde bir kez değişti) — canlı çek, ama her 4s status poll'unda değil


def _arg(cmd: List[str], flag: str) -> Optional[str]:
    try:
        i = cmd.index(flag)
    except ValueError:
        return None
    return cmd[i + 1] if i + 1 < len(cmd) else None


class AgyProvider(CliProvider):
    name = "agy"

    def __init__(self) -> None:
        self._cache_ts = 0.0
        self._cache_models: List[str] = []

    def resolve_resume_id(self, cwd: str) -> Optional[str]:
        try:
            with open(CONVERSATIONS_CACHE, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        val = data.get(cwd) or data.get(os.path.normpath(os.path.abspath(cwd)))
        return val.strip() if isinstance(val, str) and val.strip() else None

    def build_inner_command(self, cwd, model, permission_mode, effort,
                             resume_id, prompt, session_name) -> str:
        # Mutlak yol — bkz. claude_provider.py'deki aynı fix'in yorumu (pane'in kendi
        # PATH'i tmux server'ın miras kaldığından farklı/eksik olabilir).
        parts = [shutil.which("agy") or "agy"]
        if resume_id:
            parts += ["--conversation", shlex.quote(resume_id)]
        parts += ["--model", shlex.quote(model)]
        parts += ["--effort", shlex.quote(effort or "medium")]
        parts += _PERMISSION_FLAGS.get(permission_mode or "auto", _PERMISSION_FLAGS["auto"])
        if prompt:
            parts += ["-i", shlex.quote(prompt)]
        return " ".join(parts)

    def env_overrides(self, session_name: str) -> Dict[str, str]:
        return {"COPS_NAME": session_name}

    def matches_proc(self, cmd: List[str]) -> bool:
        return bool(cmd) and os.path.basename(cmd[0]) == "agy"

    def extract_name(self, proc, cmd: List[str]) -> Optional[str]:
        try:
            name = proc.environ().get("COPS_NAME")
        except Exception:
            name = None
        return name or f"agy-{proc.pid}"

    def extract_info(self, cmd: List[str]) -> Dict[str, Optional[str]]:
        if "--dangerously-skip-permissions" in cmd:
            permission_mode = "auto"
        else:
            mode = _arg(cmd, "--mode")
            permission_mode = {"accept-edits": "acceptEdits", "plan": "plan"}.get(mode)
        return {
            "sid": _arg(cmd, "--conversation"),
            "model": _arg(cmd, "--model"),
            "permission_mode": permission_mode,
            "effort": _arg(cmd, "--effort"),
        }

    def model_choices(self) -> List[str]:
        now = time.monotonic()
        if now - self._cache_ts > _MODELS_TTL:
            # Denemeyi başarısız/boş olsa BİLE damgala — yoksa (agy sign-out/hata
            # durumunda) `if models:` hiç tetiklenmez, _cache_ts sabit kalır ve TTL
            # asla dolmadığı için panel her 4s status poll'unda yeniden subprocess
            # çalıştırır (canlı yaşandı: agy sign-out olunca her poll'da ~1s'lik
            # `agy models` çağrısı — TTL'nin var oluş amacını boşa çıkarıyordu).
            self._cache_ts = now
            try:
                out = subprocess.run(["agy", "models"], capture_output=True, text=True,
                                      timeout=5).stdout
                # "agy models" gerçek satırlardan ÖNCE bir durum satırı basıyor
                # ("Fetching available models..." — tab YOK) — sadece gerçek
                # `id\tLabel` satırlarını al, yoksa bu satır ilk "model" gibi görünüp
                # panelde "Fetching available models..." diye anlamsız bir seçenek çıkıyordu.
                models = [ln.split("\t", 1)[0].strip() for ln in out.splitlines() if "\t" in ln]
                if models:
                    self._cache_models = models
            except Exception:
                pass  # eski (belki boş) cache kalır — status endpoint'i asla patlamasın
        return self._cache_models

    def permission_modes(self) -> List[str]:
        return PERMISSION_MODES

    def effort_levels(self) -> List[str]:
        return EFFORT_LEVELS
