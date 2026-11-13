"""API anahtarlı (byok.ucli) sağlayıcıların bakiye/limit okuması (Ayarlar > Kullanım, model çağrısı YOK).

Yalnız sağlayıcının ÜCRETSİZ uç noktası olan yerde ağa çıkılır; olmayanlarda dürüstçe `no_endpoint` döner (13 Kas araştırması):
- OPENROUTER_API_KEY: `GET https://openrouter.ai/api/v1/key` (kullanım, limit, kalan; belgeli, ücretsiz).
- GROQ_API_KEY: bakiye/kota uç noktası YOK (yalnız yanıt başlıklarında oran limiti); `no_endpoint`.
- ANTHROPIC_API_KEY: sıradan anahtarla bakiye uç noktası YOK (yönetici anahtarı gerekir); yerel `ucli_cost` kredi tahmini varsa o.
- UCLI_API_KEY (Evren): kullanım uç noktası bulunamadı; günlük 10M token tavanı yerel sayaçtan ölçülemez; yerel `ucli_cost` günlük USD.
Anahtar YALNIZ sunucu tarafında `Authorization` başlığında; argv'ye, günlüğe, hata metnine ve çıktıya girmez."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
TIMEOUT = 8.0

# env değişkeni -> (görünen ad, okuyucu)
NAMES = {
    "UCLI_API_KEY": "Evren",
    "ANTHROPIC_API_KEY": "Anthropic API",
    "OPENROUTER_API_KEY": "OpenRouter",
    "GROQ_API_KEY": "Groq",
}


def _usd(v: Any) -> str:
    try:
        return f"${float(v):.2f}"
    except (TypeError, ValueError):
        return "?"


def openrouter(key: str, opener=urllib.request.urlopen) -> Dict[str, Any]:
    req = urllib.request.Request(OPENROUTER_KEY_URL, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with opener(req, timeout=TIMEOUT) as r:
            data = (json.loads(r.read().decode("utf-8", "replace")) or {}).get("data") or {}
    except urllib.error.HTTPError as e:
        return {"supported": True, "available": False, "reason": "auth_failed" if e.code in (401, 403) else "request_failed"}
    except (OSError, ValueError, urllib.error.URLError):
        return {"supported": True, "available": False, "reason": "request_failed"}
    usage, limit, left = data.get("usage"), data.get("limit"), data.get("limit_remaining")
    entries: List[Dict[str, str]] = [{"label": "Kullanım", "percent": "", "detail": f"{_usd(usage)} harcandı"}]
    if limit is not None:
        try:
            pct = f"{100.0 * float(usage or 0) / float(limit):.0f}" if float(limit) > 0 else ""
        except (TypeError, ValueError):
            pct = ""
        entries.append({"label": "Anahtar limiti", "percent": pct, "detail": f"{_usd(left)} kaldı / {_usd(limit)}"})
    else:
        entries.append({"label": "Anahtar limiti", "percent": "", "detail": "limit yok"})
    return {"supported": True, "available": True, "checked_via": "api", "entries": entries}


def _local_cost(cost_state: Optional[Dict[str, Any]], note: str) -> Dict[str, Any]:
    if not cost_state:
        return {"supported": True, "available": False, "reason": "no_endpoint"}
    entries = [{"label": "ucli bugün (yerel sayaç)", "percent": "" if cost_state.get("pct") is None else str(int(cost_state["pct"])),
                "detail": f"{_usd(cost_state.get('today_usd'))}" + (f" / tavan {_usd(cost_state['cap_usd'])}" if cost_state.get("cap_usd") else "")}]
    if cost_state.get("credit_left_usd") is not None:
        entries.append({"label": "Kredi (tahmini kalan)", "percent": "", "detail": _usd(cost_state["credit_left_usd"])})
    entries.append({"label": "Not", "percent": "", "detail": note})
    return {"supported": True, "available": True, "checked_via": "local", "entries": entries}


def collect(byok: Dict[str, Any], cost_state: Optional[Dict[str, Any]] = None, opener=urllib.request.urlopen) -> Dict[str, Dict[str, Any]]:
    """`byok` = settings `byok.ucli` ({ENV: değer}); anahtarı olan her sağlayıcı için bir satır. Çıktı anahtarları `api:<Ad>`."""
    out: Dict[str, Dict[str, Any]] = {}
    for env, label in NAMES.items():
        key = str((byok or {}).get(env) or "").strip()
        if not key:
            continue
        if env == "OPENROUTER_API_KEY":
            res = openrouter(key, opener)
        elif env == "GROQ_API_KEY":
            res = {"supported": True, "available": False, "reason": "no_endpoint"}
        elif env == "ANTHROPIC_API_KEY":
            res = _local_cost(cost_state, "Anthropic bakiye uç noktası yok (yönetici anahtarı gerekir); yerel tahmin")
        else:
            res = _local_cost(cost_state, "Evren kullanım uç noktası yok; günlük 10M token tavanı ölçülemiyor")
        out[f"api:{label}"] = res
    return out
