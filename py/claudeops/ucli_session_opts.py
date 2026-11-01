"""ucli oturumu BAŞLATMA seçenekleri (`cli_opts`): hizmet (Evren/Claude/Grok/OpenRouter) ve `exec` izinleri. Yaprak modül,
saf doğrulama: dosya/ağ/süreç yok. Başlat penceresinden gelen ham sözlük burada TEMİZLENİR; geçersiz değer sessizce atlanmaz,
HATA döner (güvenlik bayrakları: yarım uygulanan bir exec izni, hiç uygulanmamasından kötüdür).

Güvenlik duruşu (sahip, 2026-11-01: "allow-exec olmalı ama yalnız gerekli olanlar için"):
- `exec` VARSAYILAN KAPALI; yalnız `exec_cmds` doluysa açılır (ucli de boş listede hiçbir şey çalıştırmaz).
- Kabuklar ve "başka komut çalıştıran" sarmalayıcılar (`sh`, `env`, `xargs`, `find`, `sudo`...) REDDEDİLİR; `:allow-eval` yazılamaz;
  yalnız çıplak komut adı (yol yok). ucli zaten bwrap kafesi içinde, ağsız çalıştırır.
- AĞ (`--exec-net`) ve sınırsız `--allow-exec-own` bu pencereden SUNULMAZ; modelin yazdığı dosyayı çalıştırmak yalnız dar glob ile
  (`tests/**`), `..`/mutlak yol/boş parça yok.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .settings import ucli_services

def services() -> Dict[str, Tuple[str, str, str]]:
    """id -> (ucli `--provider` değeri ya da "" = varsayılan chat-completions, uç nokta ya da "" = ayardaki Evren uç noktası,
    anahtar env adı). TEK kaynak: `settings.ucli_services()` (Ayarlar'dan düzenlenir; yerleşik liste yedeği)."""
    return {d["id"]: (d["wire"], d["endpoint"], d["env"]) for d in ucli_services()}


def effort_levels_for(service: str, model: str) -> Any:
    """Hizmet + model için geçerli `--effort` seviyeleri: liste ([] = bu modelde effort yok) ya da None (kural yok: Evren
    kataloğu / eski davranış). Kural = hizmetin `efforts` tablosunda model kimliğinde geçen en uzun anahtar."""
    m = (model or "").lower()
    for d in ucli_services():
        if d["id"] != service:
            continue
        keys = [k for k in d.get("efforts", {}) if k in m]
        return list(d["efforts"][max(keys, key=len)]) if keys else None
    return None


# Rastgele komut çalıştırabilen ya da kabuk olan adlar: exec izin listesine GİREMEZ.
FORBIDDEN_CMDS = frozenset({
    "sh", "bash", "zsh", "dash", "fish", "ksh", "csh", "tcsh", "ash", "busybox",
    "env", "xargs", "find", "sudo", "doas", "su", "nohup", "timeout", "nice", "time", "strace", "ltrace",
    "ssh", "scp", "nc", "ncat", "socat",
})

_CMD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_GLOB_RE = re.compile(r"^[A-Za-z0-9_./*?-]{1,120}$")
MAX_CMDS = 12
MAX_EXPANDED = 4000          # desenlerin PATH'ten açılmış toplam komut sayısı üst sınırı (argv boyutu)
_PATTERN_CHARS = re.compile(r"^[A-Za-z0-9._+*?\[\]!-]{1,64}$")
MAX_GLOBS = 4
MAX_BINDS = 6
_BIND_RE = re.compile(r"^/[A-Za-z0-9_./+@-]{1,200}$")
TIMEOUT_RANGE = (1, 600)


def _is_glob(c: str) -> bool:
    return any(ch in c for ch in "*?[")


def _items(v: Any) -> List[str]:
    if isinstance(v, (list, tuple)):
        raw = [str(x) for x in v]
    else:
        raw = str(v or "").replace("\n", ",").split(",")
    return [x.strip() for x in raw if x.strip()]


def validate_opts(raw: Any) -> Tuple[Dict[str, Any], str]:
    """Ham pencere sözlüğü -> (temiz sözlük, hata). Hata boş değilse temiz sözlük BOŞTUR. Bilinmeyen anahtarlar yok sayılır.
    Temiz anahtarlar (yalnız verilenler): `service`, `exec_cmds` (list), `exec_own_glob` (list), `exec_write` (bool, VARSAYILAN KAPALI: modele dosya yazma katmanı `--allow-edit`), `exec_bind_ro` (list, kafese salt-okunur bağlanacak mutlak dizinler: araç zinciri), `exec_timeout` (int)."""
    if not raw:
        return {}, ""
    if not isinstance(raw, dict):
        return {}, "cli_opts nesne olmalı"
    out: Dict[str, Any] = {}
    service = str(raw.get("service") or "").strip().lower()
    if service:
        if service not in services():
            return {}, f"bilinmeyen hizmet: {service}"
        out["service"] = service
    cmds = _items(raw.get("exec_cmds"))
    if cmds:
        if len(cmds) > MAX_CMDS:
            return {}, f"en çok {MAX_CMDS} komut"
        for c in cmds:
            if c.startswith("re:"):                      # regex: PATH'teki komut adlarının TAMAMINA uyar
                pat = c[3:]
                if not pat or len(pat) > 60:
                    return {}, f"geçersiz regex (1-60 karakter): {c}"
                try:
                    re.compile(pat)
                except re.error as e:
                    return {}, f"geçersiz regex ({e}): {c}"
                continue
            if ":" in c or "/" in c:
                return {}, f"yalnız çıplak komut adı, glob ya da re:<regex> (yol ve `:allow-eval` yok): {c}"
            if _is_glob(c):                              # glob (`*`, `cargo*`, `py?`): yasaklılar HİÇBİR ZAMAN açılmaz
                if not _PATTERN_CHARS.match(c):
                    return {}, f"geçersiz glob: {c}"
                continue
            if not _CMD_RE.match(c):
                return {}, f"geçersiz komut adı: {c}"
            if c.lower() in FORBIDDEN_CMDS:
                return {}, f"izin listesine girmez (kabuk/komut çalıştırıcı): {c}"
        out["exec_cmds"] = list(dict.fromkeys(cmds))
    globs = _items(raw.get("exec_own_glob"))
    if globs:
        if not cmds:
            return {}, "exec_own_glob için exec_cmds gerekli (komutsuz exec hiçbir şey çalıştırmaz)"
        if len(globs) > MAX_GLOBS:
            return {}, f"en çok {MAX_GLOBS} glob"
        for g in globs:
            if (not _GLOB_RE.match(g) or g.startswith("/") or g.startswith("-") or ".." in g.split("/")
                    or "" in g.split("/") or g in ("*", "**", "**/*")):
                return {}, f"geçersiz ya da çok geniş glob: {g}"
        out["exec_own_glob"] = list(dict.fromkeys(globs))
    binds = _items(raw.get("exec_bind_ro"))
    if binds:
        if not cmds:
            return {}, "exec_bind_ro için exec_cmds gerekli"
        if len(binds) > MAX_BINDS:
            return {}, f"en çok {MAX_BINDS} dizin"
        for b in binds:
            norm = b.rstrip("/")
            if not _BIND_RE.match(b) or ".." in b.split("/") or "//" in b or norm.count("/") < 2:
                return {}, f"geçersiz ya da çok geniş dizin (mutlak, kök/ev dizini olmaz): {b}"
        out["exec_bind_ro"] = list(dict.fromkeys(b.rstrip("/") for b in binds))
    if raw.get("exec_write") in (True, "true", "on", "1", 1):
        if not cmds:
            return {}, "exec_write için exec_cmds gerekli"
        out["exec_write"] = True
    t = raw.get("exec_timeout")
    if t not in (None, ""):
        try:
            n = int(str(t).strip())
        except ValueError:
            return {}, "exec_timeout sayı olmalı"
        if not (TIMEOUT_RANGE[0] <= n <= TIMEOUT_RANGE[1]):
            return {}, f"exec_timeout {TIMEOUT_RANGE[0]}-{TIMEOUT_RANGE[1]} sn arası"
        if not cmds:
            return {}, "exec_timeout için exec_cmds gerekli"
        out["exec_timeout"] = n
    return out, ""


def path_executables(path_env: Any = None) -> List[str]:
    """PATH'teki çalıştırılabilir dosya adları (sıralı, tekrarsız). Okunamayan dizin atlanır."""
    import os
    names = set()
    for d in (path_env if path_env is not None else os.environ.get("PATH", "")).split(os.pathsep):
        if not d:
            continue
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_file() and os.access(e.path, os.X_OK):
                            names.add(e.name)
                    except OSError:
                        continue
        except OSError:
            continue
    return sorted(n for n in names if _CMD_RE.match(n))


def expand_exec_cmds(items: List[str], available: List[str]) -> Tuple[List[str], str]:
    """Doğrulanmış komut girdileri (çıplak ad | glob | `re:<regex>`) -> (ucli'ye gidecek çıplak adlar, hata). ucli joker tanımaz,
    bu yüzden desenler `available` (PATH) üzerinde AÇILIR. FORBIDDEN_CMDS desenle de (`*` dahil) ASLA açılmaz; açık çıplak ad
    zaten doğrulamada reddedilmiştir. Hiçbir şeye uymayan desen hatadır (sessizce boş izin listesi olmaz)."""
    import fnmatch
    out: List[str] = []
    for it in items:
        if it.startswith("re:"):
            rx = re.compile(it[3:])
            hit = [n for n in available if rx.fullmatch(n)]
        elif _is_glob(it):
            hit = [n for n in available if fnmatch.fnmatchcase(n, it)]
        else:
            out.append(it)
            continue
        hit = [n for n in hit if n.lower() not in FORBIDDEN_CMDS]
        if not hit:
            return [], f"desen hiçbir komuta uymadı: {it}"
        out.extend(hit)
    out = list(dict.fromkeys(out))
    if len(out) > MAX_EXPANDED:
        return [], f"desenler çok geniş ({len(out)} komut > {MAX_EXPANDED})"
    return out, ""


def exec_flags(opts: Dict[str, Any]) -> List[str]:
    """Temiz `opts` -> ucli bayrakları (hepsi `--allow-exec` ailesi; ikilinin tanıması çağıranın işi). Komut yoksa boş."""
    cmds = opts.get("exec_cmds") or []
    if not cmds:
        return []
    argv = ["--allow-exec", "--allow-exec-cmd", ",".join(cmds)]
    for g in opts.get("exec_own_glob") or []:
        argv += ["--allow-exec-own-glob", g]
    for b in opts.get("exec_bind_ro") or []:
        argv += ["--exec-bind-ro", b]
    if opts.get("exec_timeout"):
        argv += ["--exec-timeout-secs", str(int(opts["exec_timeout"]))]
    return argv


# --- hizmetin canlı model listesi (2026-11-02: sabit liste yerine hizmetin KENDİ `/models` ucu) -------------------
import json as _json
import time as _time
import urllib.request as _urlreq

_MODELS_CACHE: Dict[str, Tuple[float, List[str]]] = {}
_MODELS_TTL = 600.0   # sn; başarısızlık 60 sn tutulur (tekrar denemeden önce)


def service_models(service: str, key: str, *, opener=None, now=None) -> List[str]:
    """`SERVICES[service]` uç noktasının `/models` listesi (model kimlikleri, sıralı). Anahtar yoksa/ağ hatasında [].
    Anthropic `x-api-key` + `anthropic-version`, diğerleri `Authorization: Bearer`. Anahtar ASLA loglanmaz."""
    if service not in services() or service == "evren" or not key:
        return []
    t = (now or _time.time)()
    hit = _MODELS_CACHE.get(service)
    if hit and t - hit[0] < (_MODELS_TTL if hit[1] else 60.0):
        return list(hit[1])
    wire, ep, _env = services()[service]
    hdr = {"x-api-key": key, "anthropic-version": "2023-06-01"} if wire == "anthropic-messages" else {"Authorization": f"Bearer {key}"}
    ids: List[str] = []
    try:
        req = _urlreq.Request(ep.rstrip("/") + "/models?limit=200", headers=hdr)
        with (opener or _urlreq.urlopen)(req, timeout=8) as r:
            data = _json.loads(r.read().decode("utf-8", "replace"))
        rows = data.get("data") if isinstance(data, dict) else data
        ids = sorted({str(m.get("id")) for m in (rows or []) if isinstance(m, dict) and m.get("id")})
    except Exception:
        ids = []
    _MODELS_CACHE[service] = (t, ids)
    return list(ids)
