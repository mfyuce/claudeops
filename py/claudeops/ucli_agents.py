"""ucli alt ajanları (unified-cli `--allow-agents`): kayıt defteri, oturuma özel ajan token'ı, ad kuralları. Yaprak modül
(web/provider içe aktarmaz): `providers/ucli_provider.py` token üretimi için, `commands/web_agents.py` uç noktalar için
kullanır.

Güvenlik duruşu:
- Token oturum başına `secrets.token_hex(32)`; YALNIZ 0600 dosyada (`TOKEN_DIR/<oturum>`) ve ucli süreci env'inde
  (`UCLI_AGENT_TOKEN="$(cat dosya)"`) durur; argv'ye ve loga ASLA girmez. Kayıt defterinde yalnız SHA-256 özeti tutulur.
- Token yalnız `/api/agents/*` yollarında geçerlidir (web.py `_agents_caller`) ve yalnız o üst oturumun çocukları için.
- Derinlik 1: çocuk (`<üst>_aj<N>`) ajan token'ı ALMAZ (`is_child_name`), çocuğun çocuğu açılamaz.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .paths import CLAUDEOPS_DIR
from .settings import load_settings

STATE_FILE = os.path.join(CLAUDEOPS_DIR, "ucli_agents.json")
TOKEN_DIR = os.path.join(CLAUDEOPS_DIR, "ucli_agent_tokens")

MAX_LIVE_CHILDREN = 2           # üst başına en çok canlı çocuk
DEFAULT_MAX_COST_USD = 2.0      # çocuk başına USD tavanı (ayar: ucli_agents_max_cost_usd)
MAX_RECORDS_PER_PARENT = 50     # durmuş çocuk kayıtlarından en yeni N tanesi tutulur (status/result durduktan sonra da okunur)
STARTING_GRACE_SECONDS = 120.0  # "starting" kaydı oturum henüz görünmese de bu kadar süre canlı sayılır
MAX_TEXT_CHARS = 20000

_CHILD_RE = re.compile(r"^(?P<parent>.+)_aj(?P<n>[1-9][0-9]*)$")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")

_LOCK = threading.RLock()
_PANEL_PORT: Optional[int] = None


# -- ayarlar ---------------------------------------------------------------------------------------------------------

_OFF_WORDS = ("off", "0", "false", "no", "none", "disabled", "kapali", "kapalı")


def enabled() -> bool:
    """`ucli_agents` ayarı: varsayılan AÇIK, `off` (ve eşanlamlıları) kapatır. Asla fırlatmaz."""
    v = load_settings().get("ucli_agents")
    return (("on" if v is None else str(v)).strip().lower() or "on") not in _OFF_WORDS


def max_cost_usd() -> float:
    """`ucli_agents_max_cost_usd` (varsayılan 2): çocuk başına USD tavanı; 0 = tavan yok. Bozuk değer varsayılana düşer."""
    raw = load_settings().get("ucli_agents_max_cost_usd")
    if raw in (None, ""):
        return DEFAULT_MAX_COST_USD
    try:
        v = float(str(raw).strip().replace(",", "."))
    except ValueError:
        return DEFAULT_MAX_COST_USD
    if v != v or v < 0 or v == float("inf"):
        return DEFAULT_MAX_COST_USD
    return min(v, 100.0)


def set_panel_port(port: Optional[int]) -> None:
    """Panelin dinlediği port (web `run` çağırır). Bilinmiyorsa ajan özelliği açılmaz (yanlış porta yönlendirmeyelim)."""
    global _PANEL_PORT
    _PANEL_PORT = int(port) if port else None


def panel_url() -> Optional[str]:
    return f"http://127.0.0.1:{_PANEL_PORT}" if _PANEL_PORT else None


# -- adlar -----------------------------------------------------------------------------------------------------------

def is_child_name(name: str) -> bool:
    return bool(_CHILD_RE.match(name or ""))


def parent_of_name(name: str) -> Optional[str]:
    m = _CHILD_RE.match(name or "")
    return m.group("parent") if m else None


def fold_text(text: Any) -> str:
    """Çok satırlı metni TEK satıra katlar (ucli REPL'i her satırı ayrı tur sayar); boş satırlar atılır, kontrol karakterleri
    boşluğa döner, uzunluk `MAX_TEXT_CHARS` ile sınırlı. REPL komutu gibi okunmasın diye `/`, `!`, `@` ile başlayan metnin önüne
    düz bir önek konur."""
    s = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", s)
    s = " ".join(p.strip() for p in s.split("\n") if p.strip())
    s = " ".join(s.split("\t")).strip()
    s = s[:MAX_TEXT_CHARS]
    if s[:1] in ("/", "!", "@"):
        s = "Message: " + s
    return s


# -- kayıt defteri ---------------------------------------------------------------------------------------------------

def _empty() -> Dict[str, Any]:
    return {"parents": {}, "children": {}}


def _load() -> Dict[str, Any]:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    for k in ("parents", "children"):
        if not isinstance(data.get(k), dict):
            data[k] = {}
    return data


def _save(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), mode=0o700, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, STATE_FILE)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_file(session_name: str) -> str:
    return os.path.join(TOKEN_DIR, session_name)


def _write_token_file(session_name: str, token: str) -> str:
    if not _SAFE_NAME_RE.match(session_name or ""):
        raise ValueError("unsafe session name")
    os.makedirs(TOKEN_DIR, mode=0o700, exist_ok=True)
    os.chmod(TOKEN_DIR, 0o700)
    path = token_file(session_name)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(token)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def issue_token(session_name: str) -> str:
    """`session_name` (üst oturum) için YENİ token üretir (eskisi geçersizleşir), 0600 dosyaya yazar, özetini kaydeder;
    dönen değer DOSYA YOLU (token'ın kendisi hiçbir yerde dönmez). Çocuk adı ya da güvensiz ad için ValueError."""
    if is_child_name(session_name):
        raise ValueError("child sessions do not get an agent token (depth 1)")
    token = secrets.token_hex(32)
    path = _write_token_file(session_name, token)
    with _LOCK:
        data = _load()
        rec = data["parents"].setdefault(session_name, {})
        rec.update(sha256=_digest(token), issued=time.time())
        rec.setdefault("seq", 0)
        _save(data)
    return path


def parent_for_token(token: str) -> Optional[str]:
    """Bearer token -> üst oturum adı (geçerli değilse None). Tüm kayıtlar sabit zamanlı karşılaştırılır."""
    if not token or not isinstance(token, str) or len(token) > 256:
        return None
    h = _digest(token)
    found = None
    with _LOCK:
        parents = _load()["parents"]
    for name, rec in parents.items():
        d = rec.get("sha256") if isinstance(rec, dict) else None
        if isinstance(d, str) and secrets.compare_digest(h, d):
            found = name
    return found


def revoke_parent(session_name: str) -> None:
    """Üst oturum kapandı: token dosyası silinir, özet düşer (çocuk kayıtları KALIR: status/result okunabilsin)."""
    if _SAFE_NAME_RE.match(session_name or ""):     # güvensiz ad (`../x`) dosya silmeye dönüşmesin
        try:
            os.remove(token_file(session_name))
        except OSError:
            pass
    with _LOCK:
        data = _load()
        rec = data["parents"].get(session_name)
        if isinstance(rec, dict) and "sha256" in rec:
            rec.pop("sha256", None)
            _save(data)


def parents() -> List[str]:
    with _LOCK:
        return [n for n, r in _load()["parents"].items() if isinstance(r, dict) and r.get("sha256")]


def get_child(name: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        rec = _load()["children"].get(name)
    return dict(rec) if isinstance(rec, dict) else None


def children_of(parent: str) -> Dict[str, Dict[str, Any]]:
    with _LOCK:
        ch = _load()["children"]
    return {n: dict(r) for n, r in ch.items() if isinstance(r, dict) and r.get("parent") == parent}


def all_children() -> Dict[str, Dict[str, Any]]:
    with _LOCK:
        ch = _load()["children"]
    return {n: dict(r) for n, r in ch.items() if isinstance(r, dict)}


def is_live(rec: Dict[str, Any], running: "set[str]", name: str, now: Optional[float] = None) -> bool:
    """Çocuk kaydı canlı mı: durdurulmamış ve (oturum çalışıyor ya da başlatma tazesi)."""
    if rec.get("status") == "stopped":
        return False
    if name in running:
        return True
    t = time.time() if now is None else now
    return rec.get("status") == "starting" and t - float(rec.get("created") or 0) < STARTING_GRACE_SECONDS


def reserve_child(parent: str, running: "set[str]", exists, fields: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """Kilit altında: üst başına canlı çocuk sınırını denetler ve `<üst>_aj<N>` adını "starting" olarak ayırır.
    `exists(name) -> bool`: ad başka yerde (instance kaydı vb.) kullanılıyorsa N atlanır. (ad, "") ya da (None, hata)."""
    if is_child_name(parent):
        return None, "an agent cannot start agents (depth limit 1)"
    with _LOCK:
        data = _load()
        mine = {n: r for n, r in data["children"].items() if isinstance(r, dict) and r.get("parent") == parent}
        live = [n for n, r in mine.items() if is_live(r, running, n)]
        if len(live) >= MAX_LIVE_CHILDREN:
            return None, f"live agent limit reached ({MAX_LIVE_CHILDREN} per parent): stop one first"
        prec = data["parents"].setdefault(parent, {"seq": 0})
        n = int(prec.get("seq") or 0)
        while True:
            n += 1
            name = f"{parent}_aj{n}"
            if name not in data["children"] and not exists(name):
                break
        prec["seq"] = n
        rec = {"parent": parent, "status": "starting", "created": time.time()}
        rec.update(fields)
        data["children"][name] = rec
        _prune(data, parent)
        _save(data)
    return name, ""


def _prune(data: Dict[str, Any], parent: str) -> None:
    stopped = sorted(((r.get("created") or 0, n) for n, r in data["children"].items()
                      if isinstance(r, dict) and r.get("parent") == parent and r.get("status") == "stopped"))
    for _t, n in stopped[:-MAX_RECORDS_PER_PARENT]:
        data["children"].pop(n, None)


def update_child(name: str, **fields: Any) -> None:
    with _LOCK:
        data = _load()
        rec = data["children"].get(name)
        if isinstance(rec, dict):
            rec.update(fields)
            _save(data)


def mark_stopped(name: str, reason: str = "") -> None:
    update_child(name, status="stopped", stopped_at=time.time(), **({"reason": reason} if reason else {}))
