"""Uzak host registry — ~/.claude/claudeops/hosts.json (0600).

roster.tsv/models.tsv/web.token ile aynı "repo DIŞI, kaynak-of-truth" deseni.
Leaf modül (settings.py'yle aynı disiplin: sadece paths'e bağımlı, commands/
paketine bağımlı olmayan modüller de sorunsuz import edebilsin — web.py bunu
import eder, tersi asla olmaz).

settings.json'dan FARKI: her kayıt kendi bearer token'ını taşıyor —
settings.save_settings() dosyayı hiç chmod'lamıyor (varsayılan umask,
muhtemelen 644/world-readable), token'ları oraya koymak güvenlik regresyonu
olurdu. Bu modül web.py'nin _load_or_create_token()'ıyla AYNI 0600 pattern'ini
kullanır — ve settings.json'ın aksine HER yazımda (sadece ilk oluşturmada
değil) yeniden uygulanır, çünkü bu dosya (token rotasyonu/host ekleme-çıkarma
ile) sık sık yeniden yazılıyor.
"""
from __future__ import annotations
import json
import os
import re
from typing import Any, Dict, List, Optional

from .paths import CLAUDEOPS_DIR

HOSTS_JSON = os.path.join(CLAUDEOPS_DIR, "hosts.json")

# Rezerve — local aggregator'ın kendi session'larını etiketlemek için kullanılan
# sentinel; kayıtlı bir uzak host adı olarak asla kabul edilmez.
LOCAL_HOST_NAME = "local"

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

ERR: Dict[str, Dict[str, str]] = {
    "invalid_name": {
        "tr": "geçersiz host adı — küçük harfle başlamalı, sadece harf/rakam/_/- içerebilir",
        "en": "invalid host name — must start with a lowercase letter, only letters/digits/_/- allowed",
    },
    "reserved_name": {
        "tr": f"'{LOCAL_HOST_NAME}' ayrılmış bir isim, host adı olarak kullanılamaz",
        "en": f"'{LOCAL_HOST_NAME}' is reserved, cannot be used as a host name",
    },
    "invalid_url": {
        "tr": "geçersiz base URL — http:// veya https:// ile başlamalı",
        "en": "invalid base URL — must start with http:// or https://",
    },
    "token_required": {
        "tr": "yeni bir host için token zorunlu",
        "en": "token is required for a new host",
    },
}


def _err(lang: str, key: str) -> Dict[str, Any]:
    return {"ok": False, "error": ERR[key]["en" if lang == "en" else "tr"]}


def load_hosts() -> List[Dict[str, str]]:
    """Tüm kayıtlı host'lar — TAM kayıt (token dahil), sadece backend-içi
    kullanım için (asla doğrudan bir API yanıtına konmaz — bkz. list_hosts_public).
    Eksik/bozuk dosyaya karşı toleranslı (settings.load_settings ile aynı disiplin)."""
    try:
        with open(HOSTS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [h for h in data if isinstance(h, dict) and "name" in h]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def get_host(name: str) -> Optional[Dict[str, str]]:
    for h in load_hosts():
        if h.get("name") == name:
            return h
    return None


def _write_hosts(hosts: List[Dict[str, str]]) -> None:
    """Atomik + 0600 yazım — settings.save_settings()'in tmp+os.replace deseni,
    AMA tmp dosyası baştan 0600 açılır (token içerdiği için — web.py'nin
    _load_or_create_token()'ıyla aynı os.open pattern'i). os.replace (rename)
    hedefi KAYNAĞIN izinleriyle değiştirir, hedefte önceden var olan izinlerle
    değil — yani her yazımda 0600 korunur, tek-seferlik oluşturmaya bağlı değil."""
    os.makedirs(CLAUDEOPS_DIR, exist_ok=True)
    tmp = HOSTS_JSON + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(hosts, f, ensure_ascii=False, indent=2)
    os.replace(tmp, HOSTS_JSON)  # atomic — eşzamanlı okuyan yarım dosya görmez


def save_host(name: str, base_url: str, token: str, lang: str = "tr") -> Dict[str, Any]:
    """Upsert. Var olan bir isimde token boş bırakılırsa mevcut token KORUNUR
    (sadece base_url güncellenir) — yeni bir isimde token zorunlu."""
    name = name.strip()
    base_url = base_url.strip().rstrip("/")
    token = token.strip()

    if not _NAME_RE.match(name):
        return _err(lang, "invalid_name")
    if name == LOCAL_HOST_NAME:
        return _err(lang, "reserved_name")
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        return _err(lang, "invalid_url")

    hosts = load_hosts()
    existing = next((h for h in hosts if h.get("name") == name), None)
    if not token:
        if existing is None:
            return _err(lang, "token_required")
        token = existing.get("token", "")

    record = {"name": name, "base_url": base_url, "token": token}
    if existing is None:
        hosts.append(record)
    else:
        hosts = [record if h.get("name") == name else h for h in hosts]
    _write_hosts(hosts)
    return {"ok": True}


def remove_host(name: str, lang: str = "tr") -> Dict[str, Any]:
    """Idempotent — kayıtlı değilse bile {"ok": True} (settings.py'nin toleranslı
    stiliyle aynı ruh; frontend'in çift-tıklama/stale state için özel hata
    yönetimi yapmasına gerek kalmaz)."""
    del lang  # şu an hiçbir hata yolu yok, imza tutarlılığı için tutuluyor
    hosts = [h for h in load_hosts() if h.get("name") != name]
    _write_hosts(hosts)
    return {"ok": True}


def list_hosts_public() -> List[Dict[str, Any]]:
    """Token ASLA dönmez — browser'a giden TEK yol budur. `has_token` sadece bir
    kayıtlı token OLUP OLMADIĞINI belirtir, değerini asla açığa çıkarmaz."""
    return [
        {"name": h.get("name", ""), "base_url": h.get("base_url", ""), "has_token": bool(h.get("token"))}
        for h in load_hosts()
    ]
