"""Ayarlar > Model'deki CLI kurulum yordamı -- claude/codex/copilot'u (agy hariç,
scriptlenebilir bir Linux kurulumu doğrulanamadı) claudeops'un kendi bin dizinine
kurar.

`npm install -g --prefix DIR paket` KULLANILIYOR -- `-g` "global" anlamına
gelse de `--prefix` verildiğinde npm sistem geneli hiçbir yere dokunmuyor,
kurulum TAMAMEN `DIR` altında kalıyor (sudo gerekmiyor, makineyi paylaşan
başka bir kullanıcıyı ETKİLEMİYOR) -- native/curl installer'ların aksine (ör.
claude.ai/install.sh HER ZAMAN ~/.local/bin'e kurar, hedef dizin seçilemiyor,
ki o da zaten kullanıcıya özel ama BURADA claudeops'un kendi dizini isteniyor).

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
# agy (Google Antigravity) -- antigravity.google bu taramada sadece macOS
# indirme linki sundu, scriptlenebilir bir Linux kurulumu bulunamadı. Yanlış
# bir komut UYDURMAK yerine BİLEREK kurulum eklenmedi, sadece tespit + linki.
MANUAL_ONLY: Dict[str, str] = {"agy": "https://antigravity.google/"}

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
        "installable": cli_name in NPM_INSTALLABLE,
        "manual_url": MANUAL_ONLY.get(cli_name),
    }


def all_cli_status() -> Dict[str, Dict[str, Any]]:
    return {name: cli_status(name) for name in ALL_CLIS}


def install_cli(cli_name: str, lang: str = "tr") -> Dict[str, Any]:
    """Zaten (BAŞKA bir yoldan) bulunmuşsa VE claudeops tarafından
    kurulmamışsa REDDEDER -- kullanıcının kendi kurduğu bir binary'nin
    üzerine asla yazmaz. claudeops'un KENDİ kurulumuysa tekrar çağrı = update
    (npm install her seferinde en güncel sürümü çeker)."""
    if cli_name not in NPM_INSTALLABLE:
        return {"ok": False, "error": ("bu CLI için otomatik kurulum yok" if lang == "tr"
                                        else "no automated install for this CLI")}
    status = cli_status(cli_name)
    if status["found"] and not status["managed_by_claudeops"]:
        return {"ok": False, "error": ("zaten kurulu (claudeops tarafından kurulmadı, dokunulmuyor)"
                                        if lang == "tr" else
                                        "already installed (not by claudeops, leaving it alone)")}
    if not shutil.which("npm"):
        return {"ok": False, "error": ("npm bulunamadı -- Node.js/npm kurulu olmalı" if lang == "tr"
                                        else "npm not found -- Node.js/npm must be installed")}

    binary_name, package = NPM_INSTALLABLE[cli_name]
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

    installed_path = os.path.join(INSTALL_DIR, "bin", binary_name)
    if not os.path.isfile(installed_path):
        return {"ok": False, "error": (f"kurulum bitti ama {installed_path} bulunamadı" if lang == "tr"
                                        else f"install finished but {installed_path} not found")}

    settings = load_settings()
    save_settings({
        "provider_bin": {**(settings.get("provider_bin") or {}), cli_name: installed_path},
        "cli_managed": {**(settings.get("cli_managed") or {}), cli_name: "1"},
    })
    return {"ok": True, "path": installed_path}
