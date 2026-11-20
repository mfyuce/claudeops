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


# ---- C2: kayıt yazımı, mod dosyası, denetim kaydı ----

AUDIT = os.path.join(ROOT, "audit.jsonl")
_RANK = {"off": 0, "restricted": 1, "full": 2}


def save_registry(data: Any, owner: str = "") -> Tuple[bool, str]:
    """Biçim denetiminden geçen kaydı atomik yazar (0600, dizin 0700, O_NOFOLLOW). Doğrulamanın tek kaynağı ucli'dir (U1); burada ön denetim."""
    ok, why = check_shape(data)
    if not ok:
        return False, why
    try:
        path = registry_path(owner)
    except ValueError as e:
        return False, str(e)
    raw = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
    if len(raw) > MAX_BYTES:
        return False, "kayıt çok büyük"
    os.makedirs(ROOT, mode=0o700, exist_ok=True)
    os.chmod(ROOT, 0o700)
    tmp = f"{path}.tmp{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return True, ""


def delete_check(name: str, owner: str = "") -> Tuple[bool, str]:
    data, err = load_registry(owner)
    if err:
        return False, err
    items = [c for c in data["check"] if c.get("name") != name]
    if len(items) == len(data["check"]):
        return False, "kontrol bulunamadı"
    return save_registry({**data, "check": items}, owner)


def mode_file(state_dir: str, session: str) -> str:
    if not _OWNER.match(session or ""):
        raise ValueError("geçersiz oturum adı")
    return os.path.join(state_dir, session + ".checks.json")


def set_mode(state_dir: str, session: str, mode: str, cap: str, *, confirm: bool = False, user: str = "", ip: str = "") -> Tuple[int, Dict[str, Any]]:
    """Mod dosyasını yazar (`seq+1`). Daraltma onaysız; genişletme `confirm` ister; tavanı aşan = 409. (HTTP kodu, yanıt) döner."""
    import time
    if mode not in _RANK or cap not in MODES:
        return 400, {"ok": False, "error": "mode off|restricted|full, max restricted|full olmalı"}
    try:
        path = mode_file(state_dir, session)
    except ValueError as e:
        return 400, {"ok": False, "error": str(e)}
    cur, seq = "off", 0
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        cur, seq = str(d.get("mode") or "off"), int(d.get("seq") or 0)
    except (OSError, ValueError, TypeError):
        pass
    if _RANK[mode] > _RANK[cap]:
        return 409, {"ok": False, "error": "tavanı aşıyor: oturumu yeni tavanla yeniden aç", "max": cap}
    if _RANK[mode] > _RANK.get(cur, 0) and not confirm:
        return 400, {"ok": False, "error": "genişletme confirm:true ister", "need_confirm": True}
    at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "mode": mode, "seq": seq + 1, "set_by": user or "panel", "at": at}, f)
    os.replace(tmp, path)
    audit({"at": at, "user": user, "session": session, "from": cur, "to": mode, "max": cap, "ip": ip})
    return 200, {"ok": True, "mode": mode, "seq": seq + 1}


def audit(rec: Dict[str, Any]) -> None:
    os.makedirs(ROOT, mode=0o700, exist_ok=True)
    fd = os.open(AUDIT, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def get_mode(state_dir: str, session: str) -> Dict[str, Any]:
    """Mod dosyasının içeriği (`mode`, `seq`); dosya yok/bozuk/geçersiz ad = kapalı. Salt okur."""
    try:
        with open(mode_file(state_dir, session), encoding="utf-8") as f:
            d = json.load(f)
        mode = str(d.get("mode") or "off")
        return {"mode": mode if mode in _RANK else "off", "seq": int(d.get("seq") or 0)}
    except (OSError, ValueError, TypeError):
        return {"mode": "off", "seq": 0}
