"""API anahtarlı (byok.ucli) sağlayıcıların bakiye/limit okuması (Ayarlar > Kullanım, model çağrısı YOK).

Yalnız sağlayıcının ÜCRETSİZ uç noktası olan yerde ağa çıkılır; olmayanlarda dürüstçe `no_endpoint` döner (13 Kas araştırması):
- OPENROUTER_API_KEY: `GET https://openrouter.ai/api/v1/key` (kullanım, limit, kalan; belgeli, ücretsiz).
- GROQ_API_KEY: bakiye/kota uç noktası YOK (yalnız yanıt başlıklarında oran limiti); `no_endpoint`.
- ANTHROPIC_API_KEY: sıradan anahtarla bakiye uç noktası YOK (yönetici anahtarı gerekir); yerel `ucli_cost` kredi tahmini varsa o.
- UCLI_API_KEY (Evren): `GET /v1/quota` (X-API-Key) VAR (18 Kas; evren_scale.py de kullanır): 5 dk pencere, günlük kalan token (15M), eşzamanlılık.
  Eski "uç nokta yok, 10M" notu bayattı. Yerel `ucli_cost` sayacı Evren'in DEĞİL, Claude/Anthropic hizmetiyle açılan ucli oturumlarının dolarıdır
  (yalnız Anthropic API satırında gösterilir; eskiden iki satırda birden çıkıyordu).
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


def _pct_left(left: Any, total: Any) -> str:
    try:
        return f"{100.0 * float(left) / float(total):.0f}" if float(total) > 0 else ""
    except (TypeError, ValueError):
        return ""


def _tok(v: Any) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "?"
    return f"{n / 1e6:.2f}M" if n >= 1e6 else f"{n / 1e3:.0f}K" if n >= 1e3 else f"{n:.0f}"


def evren(key: str, fetch=None) -> Dict[str, Any]:
    """Evren `GET /v1/quota`: günlük kalan token, 5 dk pencere, eşzamanlılık. Okunamazsa `request_failed`. Yüzde = KALAN."""
    from . import evren_scale
    d = (fetch or (lambda: evren_scale.fetch_quota(key)))()
    if not isinstance(d, dict):
        return {"supported": True, "available": False, "reason": "request_failed"}
    entries: List[Dict[str, str]] = []
    dl, dr = d.get("daily_limit_tokens"), d.get("daily_remaining_tokens")
    if dl is not None and dr is not None:
        entries.append({"label": "Günlük kalan (token)", "percent": _pct_left(dr, dl),
                        "detail": f"{_tok(dr)} / {_tok(dl)}; sıfırlanma {d.get('daily_reset_at') or '?'}"})
    cap, used = d.get("cap"), d.get("used_tokens")
    if cap is not None and used is not None:
        try:
            left = float(cap) - float(used)
        except (TypeError, ValueError):
            left = None
        entries.append({"label": f"{d.get('window_minutes') or 5} dk pencere kalan (token)", "percent": _pct_left(left, cap) if left is not None else "",
                        "detail": f"{_tok(left) if left is not None else '?'} / {_tok(cap)}; sıfırlanma {d.get('reset_at') or '?'}"})
    if d.get("concurrency_limit") is not None:
        entries.append({"label": "Eşzamanlı istek", "percent": "", "detail": f"{d.get('concurrent_requests') or 0} / {d['concurrency_limit']}"})
    if not entries:
        return {"supported": True, "available": False, "reason": "parse_failed"}
    return {"supported": True, "available": True, "checked_via": "api", "entries": entries}


def _local_cost(cost_state: Optional[Dict[str, Any]], note: str) -> Dict[str, Any]:
    if not cost_state:
        return {"supported": True, "available": False, "reason": "no_endpoint"}
    entries = [{"label": "ucli (Claude hizmeti) bugün, yerel sayaç", "percent": "" if cost_state.get("pct") is None else str(int(cost_state["pct"])),
                "detail": f"{_usd(cost_state.get('today_usd'))}" + (f" / tavan {_usd(cost_state['cap_usd'])}" if cost_state.get("cap_usd") else "")}]
    if cost_state.get("credit_left_usd") is not None:
        extra = ""
        if cost_state.get("days_left") is not None:
            extra = f" · {cost_state['days_left']} gün kaldı ({cost_state.get('credit_until')})"
            if cost_state.get("daily_budget_usd") is not None:
                extra += f" · günlük bütçe {_usd(cost_state['daily_budget_usd'])}"
        entries.append({"label": "Kredi (tahmini kalan)", "percent": "", "detail": _usd(cost_state["credit_left_usd"]) + extra})
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
            res = _local_cost(cost_state, "Anthropic bakiye uç noktası yok (yönetici anahtarı gerekir); yerel tahmin: yalnız Claude hizmetiyle açılan ucli oturumları")
        else:
            res = evren(key)
        out[f"api:{label}"] = res
    return out
