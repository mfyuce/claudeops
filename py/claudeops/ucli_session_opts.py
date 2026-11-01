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

# id -> (ucli `--provider` değeri ya da "" = varsayılan chat-completions, uç nokta ya da "" = ayardaki Evren uç noktası, anahtar env adı)
SERVICES: Dict[str, Tuple[str, str, str]] = {
    "evren": ("", "", "UCLI_API_KEY"),
    "claude": ("anthropic-messages", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY"),
    "grok": ("", "https://api.x.ai/v1", "XAI_API_KEY"),
    "openrouter": ("", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}

# Rastgele komut çalıştırabilen ya da kabuk olan adlar: exec izin listesine GİREMEZ.
FORBIDDEN_CMDS = frozenset({
    "sh", "bash", "zsh", "dash", "fish", "ksh", "csh", "tcsh", "ash", "busybox",
    "env", "xargs", "find", "sudo", "doas", "su", "nohup", "timeout", "nice", "time", "strace", "ltrace",
    "ssh", "scp", "nc", "ncat", "socat",
})

_CMD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_GLOB_RE = re.compile(r"^[A-Za-z0-9_./*?-]{1,120}$")
MAX_CMDS = 12
MAX_GLOBS = 4
MAX_BINDS = 6
_BIND_RE = re.compile(r"^/[A-Za-z0-9_./+@-]{1,200}$")
TIMEOUT_RANGE = (1, 600)


def _items(v: Any) -> List[str]:
    if isinstance(v, (list, tuple)):
        raw = [str(x) for x in v]
    else:
        raw = str(v or "").replace("\n", ",").split(",")
    return [x.strip() for x in raw if x.strip()]


def validate_opts(raw: Any) -> Tuple[Dict[str, Any], str]:
    """Ham pencere sözlüğü -> (temiz sözlük, hata). Hata boş değilse temiz sözlük BOŞTUR. Bilinmeyen anahtarlar yok sayılır.
    Temiz anahtarlar (yalnız verilenler): `service`, `exec_cmds` (list), `exec_own_glob` (list), `exec_bind_ro` (list, kafese salt-okunur bağlanacak mutlak dizinler: araç zinciri), `exec_timeout` (int)."""
    if not raw:
        return {}, ""
    if not isinstance(raw, dict):
        return {}, "cli_opts nesne olmalı"
    out: Dict[str, Any] = {}
    service = str(raw.get("service") or "").strip().lower()
    if service:
        if service not in SERVICES:
            return {}, f"bilinmeyen hizmet: {service}"
        out["service"] = service
    cmds = _items(raw.get("exec_cmds"))
    if cmds:
        if len(cmds) > MAX_CMDS:
            return {}, f"en çok {MAX_CMDS} komut"
        for c in cmds:
            if ":" in c or "/" in c:
                return {}, f"yalnız çıplak komut adı (yol ve `:allow-eval` yok): {c}"
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
