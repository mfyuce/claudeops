"""Ayarlar > Model'deki CLI kurulum yordamı -- claude/codex/copilot/agy'yi
claudeops'un kendi bin dizinine kurar.

İki farklı kurulum mekanizması var:
- npm --prefix (claude/codex/copilot): `-g` "global" anlamına gelse de
  `--prefix` verildiğinde npm sistem geneli hiçbir yere dokunmuyor, kurulum
  TAMAMEN `INSTALL_DIR` altında kalıyor (sudo gerekmiyor, makineyi paylaşan
  başka bir kullanıcıyı ETKİLEMİYOR).
- resmi kurulum script'i + `--dir` (agy/Antigravity): `antigravity.google/
  cli/install.sh` kendi SHA512 doğrulaması yapıyor ve bir `--dir <path>`
  bayrağı sunuyor (2026-09-25, kullanıcı buldu, script indirilip incelendi --
  claude.ai/install.sh'nin aksine bu GERÇEKTEN özel bir dizin kabul ediyor).

İkisi de native/curl installer'ların "hep ~/.local/bin'e kurar, hedef dizin
seçilemiyor" kısıtından BAĞIMSIZ, claudeops'un kendi dizinine yönlendirilebiliyor.

Leaf modül (sadece paths/settings'e bağımlı, settings.py'yle aynı disiplin).
"""
from __future__ import annotations
import os
import shutil
import subprocess
from typing import Any, Dict

from .paths import CLAUDEOPS_DIR
from .settings import load_settings, save_settings

INSTALL_DIR = os.path.join(CLAUDEOPS_DIR, "bin")

# cli adı -> (PATH'teki/kurulacak binary adı, resmi npm paket adı) -- üçü de
# 2026-09-25'te doğrulandı: docs (claude), GitHub repo (codex, copilot).
NPM_INSTALLABLE: Dict[str, tuple] = {
    "claude": ("claude", "@anthropic-ai/claude-code"),
    "codex": ("codex", "@openai/codex"),
    "copilot": ("copilot", "@github/copilot"),
}
# cli adı -> (binary adı, kurulum script'i URL'i) -- script kendi --dir
# bayrağıyla TARGET_DIR/<binary> yoluna kuruyor (npm'in aksine bir "bin/"
# alt-dizini YOK, doğrudan INSTALL_DIR'in içine).
SCRIPT_INSTALLABLE: Dict[str, tuple] = {
    "agy": ("agy", "https://antigravity.google/cli/install.sh"),
}

ALL_CLIS = ("claude", "codex", "copilot", "agy")


def cli_status(cli_name: str) -> Dict[str, Any]:
    """PATH'te/override'da var mı, claudeops mu kurdu. `has_token` desenindeki
    gibi (hosts.py) -- sır değil, tam yol dönmesi sorun değil."""
    settings = load_settings()
    override = (settings.get("provider_bin") or {}).get(cli_name, "").strip()
    on_path = shutil.which(cli_name)
    managed = bool((settings.get("cli_managed") or {}).get(cli_name))
    found_path = override or on_path
    return {
        "cli": cli_name,
        "found": bool(found_path),
        "path": found_path,
        "managed_by_claudeops": managed,
        "installable": cli_name in NPM_INSTALLABLE or cli_name in SCRIPT_INSTALLABLE,
        "manual_url": None,
    }


def all_cli_status() -> Dict[str, Dict[str, Any]]:
    return {name: cli_status(name) for name in ALL_CLIS}


def _install_via_npm(binary_name: str, package: str, lang: str) -> Dict[str, Any]:
    if not shutil.which("npm"):
        return {"ok": False, "error": ("npm bulunamadı -- Node.js/npm kurulu olmalı" if lang == "tr"
                                        else "npm not found -- Node.js/npm must be installed")}
    os.makedirs(INSTALL_DIR, exist_ok=True)
    try:
        r = subprocess.run(
            ["npm", "install", "-g", "--prefix", INSTALL_DIR, package],
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "npm install zaman aşımına uğradı (300sn)" if lang == "tr"
                else "npm install timed out (300s)"}
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout or "npm install failed").strip()[-2000:]}
    return {"ok": True, "path": os.path.join(INSTALL_DIR, "bin", binary_name)}


def _install_via_script(binary_name: str, script_url: str, lang: str) -> Dict[str, Any]:
    if not shutil.which("curl"):
        return {"ok": False, "error": "curl bulunamadı" if lang == "tr" else "curl not found"}
    os.makedirs(INSTALL_DIR, exist_ok=True)
    script_path = os.path.join(INSTALL_DIR, f".install-{binary_name}.sh")
    try:
        dl = subprocess.run(["curl", "-fsSL", script_url, "-o", script_path],
                             capture_output=True, text=True, timeout=60)
        if dl.returncode != 0:
            return {"ok": False, "error": (dl.stderr or "indirme başarısız").strip()[-2000:]}
        r = subprocess.run(["bash", script_path, "--dir", INSTALL_DIR],
                            capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "kurulum zaman aşımına uğradı (300sn)" if lang == "tr"
                else "install timed out (300s)"}
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout or "install script failed").strip()[-2000:]}
    return {"ok": True, "path": os.path.join(INSTALL_DIR, binary_name)}


def install_cli(cli_name: str, lang: str = "tr") -> Dict[str, Any]:
    """Zaten (BAŞKA bir yoldan) bulunmuşsa VE claudeops tarafından
    kurulmamışsa REDDEDER -- kullanıcının kendi kurduğu bir binary'nin
    üzerine asla yazmaz. claudeops'un KENDİ kurulumuysa tekrar çağrı = update
    (hem npm hem agy'nin script'i her seferinde en güncel sürümü çeker)."""
    if cli_name not in NPM_INSTALLABLE and cli_name not in SCRIPT_INSTALLABLE:
        return {"ok": False, "error": ("bu CLI için otomatik kurulum yok" if lang == "tr"
                                        else "no automated install for this CLI")}
    status = cli_status(cli_name)
    if status["found"] and not status["managed_by_claudeops"]:
        return {"ok": False, "error": ("zaten kurulu (claudeops tarafından kurulmadı, dokunulmuyor)"
                                        if lang == "tr" else
                                        "already installed (not by claudeops, leaving it alone)")}

    if cli_name in NPM_INSTALLABLE:
        binary_name, package = NPM_INSTALLABLE[cli_name]
        result = _install_via_npm(binary_name, package, lang)
    else:
        binary_name, script_url = SCRIPT_INSTALLABLE[cli_name]
        result = _install_via_script(binary_name, script_url, lang)
    if not result["ok"]:
        return result

    installed_path = result["path"]
    if not os.path.isfile(installed_path):
        return {"ok": False, "error": (f"kurulum bitti ama {installed_path} bulunamadı" if lang == "tr"
                                        else f"install finished but {installed_path} not found")}

    settings = load_settings()
    save_settings({
        "provider_bin": {**(settings.get("provider_bin") or {}), cli_name: installed_path},
        "cli_managed": {**(settings.get("cli_managed") or {}), cli_name: "1"},
    })
    return {"ok": True, "path": installed_path}
