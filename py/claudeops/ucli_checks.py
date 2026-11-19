"""ucli `run_checks` kayıt dosyası: yol ve biçim/boyut ÖN denetimi (docs/ucli-run-checks-design.md 4.1-4.3). Yaprak modül.

Doğrulamanın tek kaynağı ucli'nin `checks validate` alt komutudur (C2); burası yalnız yol çözümü ve ucuz biçim denetimi yapar.
Kayıt `<CLAUDEOPS_DIR>/ucli_checks/<sahip>.json` (0600, dizin 0700, çalışma kökü DIŞINDA); tek kullanıcıda sahip `owner`."""
from __future__ import annotations

import json
import os
import re
import stat
from typing import Any, Dict, Tuple

from .paths import CLAUDEOPS_DIR

ROOT = os.path.join(CLAUDEOPS_DIR, "ucli_checks")
MODES = ("restricted", "full")
MAX_BYTES = 256 * 1024
MAX_CHECKS = 200
_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")


def registry_path(owner: str = "") -> str:
    owner = owner or "owner"
    if not _OWNER.match(owner):
        raise ValueError("geçersiz kayıt sahibi")
    return os.path.join(ROOT, owner + ".json")


def check_shape(data: Any) -> Tuple[bool, str]:
    """Ucuz biçim denetimi: `{"check": [ {name, argv[...]} ... ]}`, ad benzersiz ve güvenli, argv boş değil/dize listesi."""
    if not isinstance(data, dict) or not isinstance(data.get("check"), list):
        return False, "kayıt {\"check\": [...]} olmalı"
    items = data["check"]
    if len(items) > MAX_CHECKS:
        return False, f"en çok {MAX_CHECKS} kontrol"
    seen = set()
    for c in items:
        if not isinstance(c, dict) or not _NAME.match(str(c.get("name") or "")):
            return False, "her kontrolün adı [a-z][a-z0-9_-]{0,47} olmalı"
        if c["name"] in seen:
            return False, f"kontrol adı yinelendi: {c['name']}"
        seen.add(c["name"])
        argv = c.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
            return False, f"{c['name']}: argv boş olmayan dize listesi olmalı"
    return True, ""


def load_registry(owner: str = "") -> Tuple[Dict[str, Any], str]:
    """Kayıt (ayrıştırılmış, biçim denetimli) ya da ({}, hata). Dosya: düz, symlink değil, 0600, boyut sınırlı."""
    try:
        path = registry_path(owner)
    except ValueError as e:
        return {}, str(e)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return {}, "kontrol kaydı yok (Ayarlar > Ucli > Kontroller'den kayıt ekle)"
    except OSError as e:
        return {}, f"kayıt okunamadı: {e.__class__.__name__}"
    if not stat.S_ISREG(st.st_mode):
        return {}, "kayıt düz dosya olmalı (symlink/özel dosya reddedilir)"
    if st.st_mode & 0o077:
        return {}, "kayıt dosyası 0600 olmalı"
    if st.st_size > MAX_BYTES:
        return {}, "kayıt çok büyük"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}, "kayıt geçerli JSON değil"
    ok, why = check_shape(data)
    return (data, "") if ok else ({}, why)
