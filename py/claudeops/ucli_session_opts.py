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

import os
import re
from typing import Any, Dict, List, Tuple

from .envnames import is_safe_env_name
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
    # yorumlayıcılar / betik motorları (rastgele kod): `*` deseni de bunları AÇAMAZ
    "perl", "ruby", "node", "nodejs", "deno", "bun", "php", "lua", "luajit", "tclsh", "wish", "expect", "julia", "Rscript",
    "awk", "gawk", "mawk", "nawk", "sed", "pwsh", "powershell", "osascript", "groovy", "jshell", "guile", "emacs",
    # başka komut çalıştıranlar / kaçış sağlayanlar
    "flock", "chroot", "setsid", "stdbuf", "watch", "parallel", "tmux", "screen", "script", "unshare", "nsenter", "setpriv",
    "taskset", "ionice", "systemd-run", "at", "batch", "crontab", "run-parts", "bwrap", "docker", "podman", "gdb", "lldb",
    "vi", "vim", "nvim", "ed", "ex", "less", "more", "man", "curl", "wget",
})

# Sürümlü yorumlayıcı adları (`python3.12`, `pypy3`, `ruby3.2`, `perl5.38`): tam ad listesi bunları kaçırırdı.
_FORBIDDEN_RE = re.compile(r"^(?:python|pypy|perl|ruby|node|php|lua|tclsh|busybox)[0-9._-]*$", re.I)


def is_forbidden_cmd(name: str) -> bool:
    n = (name or "").lower()
    return n in FORBIDDEN_CMDS or n in _FORBIDDEN_LOWER or bool(_FORBIDDEN_RE.match(n))


_FORBIDDEN_LOWER = frozenset(x.lower() for x in FORBIDDEN_CMDS)

_CMD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_GLOB_RE = re.compile(r"^[A-Za-z0-9_./*?-]{1,120}$")
MAX_CMDS = 12
MAX_EXPANDED = 4000          # desenlerin PATH'ten açılmış toplam komut sayısı üst sınırı (argv boyutu)
_PATTERN_CHARS = re.compile(r"^[A-Za-z0-9._+*?\[\]!-]{1,64}$")
MAX_GLOBS = 4
MAX_BINDS = 6
_BIND_RE = re.compile(r"^/[A-Za-z0-9_./+@-]{1,200}$")
TIMEOUT_RANGE = (1, 600)
MAX_COST_USD = 100.0         # `max_cost_usd` (tur başına USD) üst sınırı: yazım hatası sınırsız harcama açmasın
# Grup B sınır bayrakları (cli_opts anahtarı -> üst sınır); 0/boş = bayrak verilmez. Ayar grubu yok: oturum başına cli_opts.
INT_LIMITS = {
    "max_prompt_tokens": 100_000_000,
    "max_repeated_calls": 1000,
    "max_consecutive_failures": 1000,
    "max_continuation_steps": 1000,
    "exec_per_script": 1000,
    "instructions_max_kib": 256,   # UCLI-HELP: varsayılan 40, en çok 256
}
PRICE_MAX = 1000.0           # `price` her alanı için USD / milyon token üst sınırı


BROAD_GLOBS = ("*", "**", "**/*")   # yalnız `accept_risk` ile kabul edilir


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
    Temiz anahtarlar (yalnız verilenler): `service`, `exec_cmds` (list), `exec_own_glob` (list), `exec_write` (bool, VARSAYILAN KAPALI: modele dosya yazma katmanı `--allow-edit`), `exec_bind_ro` (list, kafese salt-okunur bağlanacak mutlak dizinler: araç zinciri), `exec_timeout` (int), `max_cost_usd` (float > 0, tur başına USD tavanı)."""
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
            if is_forbidden_cmd(c):
                return {}, f"izin listesine girmez (kabuk/komut çalıştırıcı): {c}"
        out["exec_cmds"] = list(dict.fromkeys(cmds))
    tcv = str(raw.get("exec_toolchain") or "").strip().lower()
    if tcv:
        if tcv != "rust":
            return {}, f"bilinmeyen exec_toolchain: {tcv} (yalnız rust)"
        _tc, tc_err = rust_toolchain()
        if tc_err:
            return {}, tc_err
        out["exec_toolchain"] = "rust"
    globs = _items(raw.get("exec_own_glob"))
    if globs:
        if not cmds:
            return {}, "exec_own_glob için exec_cmds gerekli (komutsuz exec hiçbir şey çalıştırmaz)"
        if len(globs) > MAX_GLOBS:
            return {}, f"en çok {MAX_GLOBS} glob"
        accept = bool(raw.get("accept_risk")) and str(raw.get("accept_risk")).lower() not in ("0", "false", "no", "off")
        for g in globs:
            if (not _GLOB_RE.match(g) or g.startswith("/") or g.startswith("-") or ".." in g.split("/")
                    or "" in g.split("/")):
                return {}, f"geçersiz glob: {g}"
            if g in BROAD_GLOBS:
                if not accept:
                    return {}, ('çok geniş glob: tüm dosyalara çalıştırma izni verir; kabul etmek için '
                                f'"riski kabul ediyorum" işaretle: {g}')
                out["accept_risk"] = True
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
    c = raw.get("max_cost_usd")
    if c not in (None, ""):
        # Tur (görev) başına tahmini USD tavanı -> ucli `--max-cost-usd` (aşılınca tur toparlanır). 0 = yok (anahtar düşer).
        try:
            usd = float(str(c).strip().replace(",", "."))
        except ValueError:
            return {}, "max_cost_usd sayı olmalı"
        if not (0 <= usd <= MAX_COST_USD) or usd != usd:
            return {}, f"max_cost_usd 0-{MAX_COST_USD:g} USD arası"
        if usd > 0:
            out["max_cost_usd"] = usd
    s = raw.get("max_session_usd")
    if s not in (None, ""):
        # OTURUM boyunca toplam tahmini USD tavanı -> ucli `--max-session-usd` (yalnız REPL; çalışan tur kesilmez, yeni tur
        # reddedilir). `max_cost_usd` TUR başına: 2 USD'lik tur tavanı oturumu sınırlamaz (copsdev 4,71 USD, 5 Kas). 0 = yok.
        try:
            usd = float(str(s).strip().replace(",", "."))
        except ValueError:
            return {}, "max_session_usd sayı olmalı"
        if not (0 <= usd <= MAX_COST_USD * 10) or usd != usd:
            return {}, f"max_session_usd 0-{MAX_COST_USD * 10:g} USD arası"
        if usd > 0:
            out["max_session_usd"] = usd
    # git araçları (ucli `--allow-git-commit` / `--allow-git-push`, TBD#157): VARSAYILAN KAPALI, birbirinden bağımsız, exec'e bağlı değil.
    # Bayrak güvenlik izni olduğundan belirsiz değer (ör. "maybe") sessizce yok sayılmaz, HATA döner.
    for key in ("git_commit", "git_push"):
        v = raw.get(key)
        if v in (None, "", False, 0, "0", "false", "no", "off"):
            continue
        if v in (True, 1, "true", "on", "1", "yes"):
            out[key] = True
            continue
        return {}, f"{key} true/false olmalı"
    # Sınır bayrakları (grup B): boş/0 = bayrak verilmez (ucli varsayılanı); sayı değilse ya da üst sınırı aşarsa HATA.
    for key, hi in INT_LIMITS.items():
        v = raw.get(key)
        if v in (None, "", False):
            continue
        try:
            n = int(str(v).strip())
        except ValueError:
            return {}, f"{key} tam sayı olmalı"
        if not (0 <= n <= hi):
            return {}, f"{key} 0-{hi} arası"
        if n > 0:
            out[key] = n
    # instructions_user: operatörün ~/.claude/CLAUDE.md'si seçilen model hizmetine gider (gizlilik): VARSAYILAN KAPALI.
    for key in ("no_prompt_cache", "show_usage", "instructions_user", "checkpoint"):
        v = raw.get(key)
        if v in (None, "", False, 0, "0", "false", "no", "off"):
            continue
        if v in (True, 1, "true", "on", "1", "yes"):
            out[key] = True
            continue
        return {}, f"{key} true/false olmalı"
    # Grup D yetenek bayrakları (hepsi VARSAYILAN KAPALI, belirsiz değer HATA). `exec_own_glob` (--allow-exec-own-glob) yukarıda zaten var.
    # --exec-net ve sınırsız --allow-exec-own BİLEREK yok (modül başlığı; sahip kararı bekliyor). ask_edit yazma izni (exec_write) ister.
    for key in ("allow_image", "allow_scholar", "ask_edit", "ask_dir", "approval_dir"):
        v = raw.get(key)
        if v in (None, "", False, 0, "0", "false", "no", "off"):
            continue
        if v not in (True, 1, "true", "on", "1", "yes"):
            return {}, f"{key} true/false olmalı"
        if key == "ask_edit" and not out.get("exec_write"):
            return {}, "ask_edit için exec_write (--allow-edit) gerekli"
        if key == "approval_dir" and not out.get("ask_edit"):
            return {}, "approval_dir için ask_edit (ve exec_write) gerekli"
        if key == "approval_dir" and (out.get("ask_dir") or raw.get("ask_dir") not in (None, "", False, 0, "0", "false", "no", "off")):
            return {}, "approval_dir (tek atımlık iş) ile ask_dir (REPL) birlikte kullanılamaz"
        out[key] = True
    # --search-token-env: YALNIZ ortam değişkeni ADI (değer değil); token argv/log/ayara girmez.
    ste = raw.get("search_token_env")
    if ste not in (None, ""):
        ste = str(ste).strip()
        if len(ste) > 64 or not is_safe_env_name(ste):
            return {}, "search_token_env yalnız ortam değişkeni ADI olmalı (A-Z, 0-9, _; <=64), değer değil"
        out["search_token_env"] = ste
    p = raw.get("price")
    if p not in (None, ""):
        # ucli `--price`: milyon token başına USD, `IN,OUT` ya da `IN,OUT,CACHE_READ,CACHE_WRITE` (UCLI-HELP). Yanlış fiyat
        # maliyet hesabını bozar: tam 2 ya da 4 sayı, hepsi 0 < x <= PRICE_MAX, aksi HATA.
        parts = [x.strip() for x in str(p).split(",")]   # ondalık ayracı yalnız nokta (virgül alan ayracıdır)
        if len(parts) not in (2, 4):
            return {}, "price IN,OUT ya da IN,OUT,CACHE_READ,CACHE_WRITE olmalı (milyon token başına USD)"
        vals = []
        for x in parts:
            try:
                f = float(x)
            except ValueError:
                return {}, "price değerleri sayı olmalı"
            if f != f or not (0 < f <= PRICE_MAX):
                return {}, f"price değerleri 0-{PRICE_MAX:g} USD/milyon token arası (0 hariç)"
            vals.append(f)
        out["price"] = ",".join(f"{f:g}" for f in vals)
    uc = raw.get("ucli_checks")
    if uc not in (None, "", False, {}):
        # run_checks (docs/ucli-run-checks-design.md 4.1): VARSAYILAN KAPALI, geçersiz değer HATA. Kayıt dosyasının varlığı açılışta
        # (`_apply_cli_opts`) denetlenir: kayıt sahibi (panel kullanıcısı) burada bilinmez.
        if not isinstance(uc, dict):
            return {}, "ucli_checks {mode, max, accept_risk} nesnesi olmalı"
        mode = str(uc.get("mode") or "").strip().lower()
        if mode not in ("restricted", "full"):
            return {}, "ucli_checks.mode restricted ya da full olmalı"
        mx = str(uc.get("max") or mode).strip().lower()
        if mx not in ("restricted", "full"):
            return {}, "ucli_checks.max restricted ya da full olmalı"
        if mx == "restricted" and mode == "full":
            return {}, "ucli_checks.max, mode'dan düşük olamaz"
        risk = uc.get("accept_risk") in (True, 1, "true", "on", "1", "yes")
        if "full" in (mode, mx) and not risk:
            return {}, "ucli_checks full için accept_risk gerekli (yorumlayıcılar serbest kalır; yine kafeste)"
        out["ucli_checks"] = {"mode": mode, "max": mx, "accept_risk": risk}
    return out, ""


DEFAULT_MAX_SESSION_USD = 8.0     # sahip 11 Kas: ucli oturumu başına varsayılan toplam tavan (ayar: ucli_max_session_usd; 0 = yok)


def default_max_session_usd() -> float:
    """`ucli_max_session_usd` ayarı: boş/bozuk = 8, 0 = tavan yok. Kayıtta kendi `max_session_usd`u varsa o kazanır."""
    from .settings import load_settings
    raw = load_settings().get("ucli_max_session_usd")
    if raw in (None, ""):
        return DEFAULT_MAX_SESSION_USD
    try:
        v = float(str(raw).strip().replace(",", "."))
    except ValueError:
        return DEFAULT_MAX_SESSION_USD
    if v != v or v < 0 or v == float("inf"):
        return DEFAULT_MAX_SESSION_USD
    return v


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
    return sorted(n for n in names if _CMD_RE.fullmatch(n))     # `$` sondaki satır sonunu kabul ederdi


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
        hit = [n for n in hit if not is_forbidden_cmd(n)]
        if not hit:
            return [], f"desen hiçbir komuta uymadı: {it}"
        out.extend(hit)
    out = list(dict.fromkeys(out))
    if len(out) > MAX_EXPANDED:
        return [], f"desenler çok geniş ({len(out)} komut > {MAX_EXPANDED})"
    return out, ""


def _rustup_default_toolchain(rustup_home: str) -> str:
    """`<rustup_home>/settings.toml` içindeki `default_toolchain` (yoksa/okunamazsa ""). Tam TOML ayrıştırıcı gerekmez: tek anahtar."""
    try:
        with open(os.path.join(rustup_home, "settings.toml"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r'\s*default_toolchain\s*=\s*"([^"]+)"', line)
                if m:
                    return m.group(1).strip()
    except (OSError, UnicodeDecodeError):     # bozuk dosya = varsayılan bilinmiyor (birden çok adayda "belirsiz" reddi)
        pass
    return ""


def rust_toolchain() -> Tuple[Dict[str, str], str]:
    """Kafese verilecek Rust araç zinciri -> ({root, cargo, rustc, registry, git, rustup_home, cargo_home}, hata). Yolu kullanıcı
    VERMEZ: `~/.rustup/toolchains/` altındaki TEK dizin (ya da `RUSTUP_TOOLCHAIN` adlısı) bulunur; kafeste `$HOME` boştur ve çıplak
    `cargo` bir rustup vekilidir (toolchain seçemez), bu yüzden GERÇEK ikili tam yolla çalıştırılır (ucli bunu kendi E3 hatasında önerir)."""
    home = os.path.expanduser("~")
    rh = os.path.join(home, ".rustup")
    tdir = os.path.join(rh, "toolchains")
    try:
        names = sorted(n for n in os.listdir(tdir) if os.path.isfile(os.path.join(tdir, n, "bin", "cargo"))
                       and os.path.isfile(os.path.join(tdir, n, "bin", "rustc")))
    except OSError:
        return {}, f"Rust araç zinciri bulunamadı: {tdir}"
    want = os.environ.get("RUSTUP_TOOLCHAIN", "")
    pick = [n for n in names if n.startswith(want)] if want else names
    if want and not pick:       # istenen araç zinciri yok: başkasını SESSİZCE seçme
        return {}, f"RUSTUP_TOOLCHAIN={want} ile eşleşen araç zinciri yok: {tdir}"
    if len(pick) > 1 and not want:      # birden çok: rustup'ın kendi varsayılanı (settings.toml default_toolchain) TEK adayı seçer
        dflt = _rustup_default_toolchain(rh)
        if dflt:
            pick = [n for n in pick if n == dflt or n.startswith(dflt + "-")]
    if len(pick) != 1:
        return {}, f"Rust araç zinciri belirsiz/yok ({len(pick)} aday): {tdir}"
    root = os.path.join(tdir, pick[0])
    ch = os.path.join(home, ".cargo")
    return {"root": root, "cargo": os.path.join(root, "bin", "cargo"), "rustc": os.path.join(root, "bin", "rustc"),
            "registry": os.path.join(ch, "registry"), "git": os.path.join(ch, "git"),
            "rustup_home": rh, "cargo_home": ch}, ""


def exec_flags(opts: Dict[str, Any]) -> List[str]:
    """Temiz `opts` -> ucli bayrakları (hepsi `--allow-exec` ailesi; ikilinin tanıması çağıranın işi). Komut yoksa boş."""
    cmds = list(opts.get("exec_cmds") or [])
    tc: Dict[str, str] = {}
    if opts.get("exec_toolchain") == "rust":
        tc, _err = rust_toolchain()
        if tc:
            cmds += [tc["cargo"], tc["rustc"]]
    if not cmds:
        return []
    argv = ["--allow-exec", "--allow-exec-cmd", ",".join(cmds)]
    for g in opts.get("exec_own_glob") or []:
        argv += ["--allow-exec-own-glob", g]
    binds = list(opts.get("exec_bind_ro") or [])
    if tc:
        binds += [tc["root"]] + [p for p in (tc["registry"], tc["git"]) if os.path.isdir(p)]
        # ucli kafesi YALNIZ izinli değişkenleri kabul eder (RUSTC yok): gerçek toolchain bin'i PATH'in başına konur, böylece çıplak
        # `rustc`/`cargo` rustup/snap vekiline çözülmez (canlı bulgu 2026-11-02: snap profil zaman aşımı, exit 46).
        for kv in (f"RUSTUP_HOME={tc['rustup_home']}", f"CARGO_HOME={tc['cargo_home']}",
                   f"RUSTUP_TOOLCHAIN={os.path.basename(tc['root'])}", "CARGO_NET_OFFLINE=true",
                   f"PATH={os.path.dirname(tc['cargo'])}:/usr/local/bin:/usr/bin:/bin"):
            argv += ["--exec-env", kv]
        # rustc/linker çok sanal bellek ve iş parçacığı kullanır: varsayılan RLIMIT_AS bağlama aşamasında düşürüyordu (canlı 2026-11-02)
        argv += ["--exec-memory-mib", "32768", "--exec-max-tasks", "4096"]
    for b in dict.fromkeys(binds):
        argv += ["--exec-bind-ro", b]
    if opts.get("exec_timeout"):
        argv += ["--exec-timeout-secs", str(int(opts["exec_timeout"]))]
    return argv


# --- hizmetin canlı model listesi (2026-11-02: sabit liste yerine hizmetin KENDİ `/models` ucu) -------------------
import json as _json
import time as _time
import urllib.request as _urlreq

_MODELS_CACHE: Dict[str, Tuple[float, List[str]]] = {}
_MODELS_TTL = 86400.0   # sn (24 sa, TBD#146); başarısızlık 60 sn tutulur (tekrar denemeden önce)
_MODELS_RETRY = 60.0


def _models_cache_key(service: str, ep: str, key: str) -> str:
    """Önbellek anahtarı hizmet + uç nokta + anahtar özeti: anahtar ya da uç nokta değişince eski liste kullanılmaz;
    anahtarın kendisi saklanmaz. Rust `ucli_opts::models_cache_key`."""
    import hashlib
    return f"{service}\0{ep}\0{hashlib.sha256(key.encode('utf-8', 'surrogatepass')).hexdigest()}"


def _parse_service_models(raw: bytes) -> List[str]:
    """`{"data": [...]}` ya da doğrudan dizi -> sıralı, tekrarsız kimlikler. `data` yok/`null` boş liste; JSON olmayan
    gövde ya da dizi olmayan `data` `ValueError` (başarısız çekim). Rust `ucli_opts::parse_service_models`."""
    data = _json.loads(raw.decode("utf-8", "replace"))
    rows = data.get("data") if isinstance(data, dict) else data
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError("models: dizi değil")
    return sorted({str(m.get("id")) for m in rows if isinstance(m, dict) and m.get("id")})


class _NoRedirect(_urlreq.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):   # API anahtarı başlığı başka adrese taşınmasın (TBD#389)
        return None


def _open_no_redirect(req, timeout):
    """`urlopen` gibi (proxy ortamı dahil) ama 3xx HİÇ izlenmez: `HTTPError` olarak döner."""
    return _urlreq.build_opener(_NoRedirect).open(req, timeout=timeout)


def service_models(service: str, key: str, *, opener=None, now=None) -> List[str]:
    """`SERVICES[service]` uç noktasının `/models` listesi (model kimlikleri, sıralı). Anahtar yoksa/ağ hatasında [].
    Anthropic `x-api-key` + `anthropic-version`, diğerleri `Authorization: Bearer`. Anahtar ASLA loglanmaz.
    Önbellek hizmet + uç nokta + anahtar özetine bağlı. Başarısız çekim eski DOLU listeyi ezmez (o döner, yeniden deneme
    60 sn sonra); eski liste yoksa boş sonuç 60 sn tutulur."""
    if service not in services() or service == "evren" or not key:
        return []
    t = (now or _time.time)()
    wire, ep, _env = services()[service]
    ck = _models_cache_key(service, ep, key)
    hit = _MODELS_CACHE.get(ck)
    if hit and t - hit[0] < (_MODELS_TTL if hit[1] else _MODELS_RETRY):
        return list(hit[1])
    hdr = {"x-api-key": key, "anthropic-version": "2023-06-01"} if wire == "anthropic-messages" else {"Authorization": f"Bearer {key}"}
    try:
        req = _urlreq.Request(ep.rstrip("/") + "/models?limit=200", headers=hdr)
        with (opener or _open_no_redirect)(req, timeout=8) as r:
            ids = _parse_service_models(r.read())
        entry = (t, ids)
    except Exception:
        from .diaglog import diag_log
        diag_log("models_fetch_failed", source=service)     # yutulan hata günlüğe (anahtar/adres yok)
        entry = (t - _MODELS_TTL + _MODELS_RETRY, hit[1]) if hit and hit[1] else (t, [])
    _MODELS_CACHE[ck] = entry
    return list(entry[1])
