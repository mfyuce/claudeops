"""Reviewer rolü: saf çekirdek (ağ/süreç/tmux YOK). Planlama kararları, istem üretimi, bulgu ayrıştırma ve
`review_pool.json` / `review_history.json` / `findings.json` depoları. Çalıştırıcılar (Evren/agy), tick döngüsü ve API
sonraki partilerde; burada yalnız test edilebilir mantık var (`card` modülü gibi: girdi -> karar).

Havuz `projects.json`'a YAZILMAZ (aynı adın iki kimlikte olması `ownership_index`te projeyi kimseye vermez): ayrı
`review_pool.json`. Çift = (proje, mod, alt model); anahtar `"<proje>|<mode>/<slug>"`."""
from __future__ import annotations
import hashlib
import json
import os
import calendar
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from . import steward as sw

WINDOW_SECONDS = 30 * 86400         # bir çift bu sürede `done` ise "taze" (proje tamam ölçütü)
HISTORY_VERSION = 1
HISTORY_RUNS_MAX = 200
MAX_ATTEMPTS = 3                    # error/model_fallback/partial çifti bu denemeden sonra pencere dolana dek bırakılır
MODE_MAX_ATTEMPTS = {"evren": 1, "anthropic": 1}    # Evren: 20 dk zaman aşımı kota yakar, pencere başına en çok 1 deneme (sahip kararı 2026-10-24)


UNCOUNTED_ERRORS = ("cancelled", "spawn:", "yeniden başlatma")     # TBD#139: kaza sayılmayan hatalar (iptal, süreç açılamadı, servis restart'ı)


def counts_as_attempt(rec: Any) -> bool:
    """Bu çift kaydının hatası deneme hakkını TÜKETİR mi: restart/iptal/spawn hatası tüketmez (aynı çift 30 gün kilitlenmesin);
    gerçek zaman aşımı/`partial`/rc≠0 tüketir."""
    err = str((rec or {}).get("error") or "")
    return not any(err.startswith(p) for p in UNCOUNTED_ERRORS)


def max_attempts(mode: str) -> int:
    return MODE_MAX_ATTEMPTS.get(mode, MAX_ATTEMPTS)
MODES = ("agy", "evren", "claude", "codex", "copilot", "anthropic")
UCLI_MODES = ("evren", "anthropic")      # ucli ile koşan modlar (anthropic = ucli --provider anthropic-messages, gerçek API)
ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1"
# $ / 1M token: (girdi, çıktı, önbellek okuma, önbellek yazma). Haiku 5.5: >100K istemde 0,50/2,50 (ucli tek istek boyutunu ayırmaz: alt sınır)
ANTHROPIC_PRICES = {"haiku-5-5": (0.10, 0.50, 0.01, 0.125), "sonnet-5-5": (2.0, 10.0, 0.10, 2.5), "opus-5-5": (4.0, 20.0, 0.20, 5.0),
                    # fable-5-1: 10/50 $/M; önbellek okuma 0,025x (resmî prompt-caching belgesi: Fable 5.1 0,025x, Opus/Sonnet 5.5 0,05x, Haiku 5.5 0,1x), yazma 5 dk 1,25x
                    "fable-5-1": (10.0, 50.0, 0.25, 12.5)}


def parse_slots(spec: Any) -> Dict[str, int]:
    """`review_slots` ayarı (`agy=5,evren=1,codex=1,copilot=0`) -> {mod: yuva}. ""/`off` = {} (eski TEK iş kipi).
    Belirtilmeyen mod 1 yuva, 0 = mod KAPALI (yeni koşu başlamaz, çalışan biter). Bilinmeyen mod/bozuk değer yok sayılır."""
    t = str(spec or "").strip().lower()
    if not t or t == "off":
        return {}
    out = {m: 1 for m in MODES}
    seen = False
    for part in t.split(","):
        k, sep, v = part.partition("=")
        k, v = k.strip(), v.strip()
        if sep and k in MODES and v.isdigit():
            out[k] = int(v)
            seen = True
    return out if seen else {}
PAIR_STATUSES = ("running", "done", "partial", "error", "model_fallback", "limit")
SEVERITIES = ("P1", "P2", "P3")
FINDING_STATES = ("new", "verify_sent", "verified", "refuted", "unclear", "approved", "rejected", "exported", "dup")

# Reviewer'a GÖSTERİLMEYECEK yollar (istemde yasak olarak sayılır; parola/anahtar içerebilir).
FORBIDDEN_PATHS = ("CLAUDE.md", ".env*", "*token*", "*credential*", "*.pem", "settings*.json")


# ── hedefler ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReviewTarget:
    mode: str      # agy | evren | claude | codex | copilot
    model: str     # sağlayıcıya verilen gerçek model kimliği
    slug: str      # yol/anahtar güvenli ad (`slug_model`)
    effort: str = ""   # hedefe özel effort (`model@effort` biçimi); boşsa `review_<mode>_effort` ayarı

    @property
    def pslug(self) -> str:
        """Çift anahtarındaki ad: aynı model birden çok effort ile ayrı çift olur (`slug@effort`)."""
        return f"{self.slug}@{slug_model(self.effort)}" if self.effort else self.slug

    @property
    def key(self) -> str:
        return f"{self.mode}/{self.pslug}"

    @property
    def spec(self) -> str:
        return f"{self.model}@{self.effort}" if self.effort else self.model


def slug_model(model: str) -> str:
    """Yol güvenli ad: '/' ve diğer güvensiz karakterler '-' olur; `..`/boş kalmaz."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(model or "").strip()).strip("-.")
    s = re.sub(r"-{2,}", "-", s)
    return s or "model"


def split_spec(spec: Any) -> Tuple[str, str]:
    """`model@effort` -> (model, effort); `@` yoksa effort boş. Model kimliklerinde `@` bulunmaz."""
    m, _, e = str(spec or "").strip().partition("@")
    return m.strip(), e.strip()


def _split_models(text: Any) -> List[str]:
    out: List[str] = []
    for part in str(text or "").split(","):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def targets_from_config(cfg: Any, agy_models: Sequence[str], evren_models: Sequence[str]) -> List[ReviewTarget]:
    """`cfg.review_agy_models` / `review_evren_models` (virgülle ayrık) var olanla (`agy_models`/`evren_models`)
    KESİŞTİRİLİR; boş ayar = verilenin tümü. Sıra: önce agy, sonra evren; yinelenen slug atılır.
    `claude` (Anthropic, `claude -p`), `codex` (`codex exec`) ve `copilot` (`copilot -p`) katalogsuz ve KAPALI başlar: yalnız `review_claude_models`/`review_codex_models`/`review_copilot_models` doluysa o modeller."""
    out: List[ReviewTarget] = []
    seen: Set[str] = set()
    for mode, avail, want in (("agy", agy_models, getattr(cfg, "review_agy_models", "")),
                              ("evren", evren_models, getattr(cfg, "review_evren_models", ""))):
        wanted = _split_models(want)
        for m in (wanted if wanted else list(avail or [])):
            if wanted and m not in (avail or []):
                continue
            t = ReviewTarget(mode, m, slug_model(m))
            if t.key not in seen:
                seen.add(t.key)
                out.append(t)
    for mode, attr in (("claude", "review_claude_models"), ("codex", "review_codex_models"),
                       ("copilot", "review_copilot_models"), ("anthropic", "review_anthropic_models")):
        for spec in _split_models(getattr(cfg, attr, "")):
            m, eff = split_spec(spec)         # `claude-haiku-5-5@low,claude-haiku-5-5@high`: aynı model, iki ayrı çift
            if not m:
                continue
            t = ReviewTarget(mode, m, slug_model(m), eff)
            if t.key not in seen:
                seen.add(t.key)
                out.append(t)
    return out


def review_title(project: str, mode: str, model: str, ts: Any) -> str:
    """History satırı/sohbet başlığı (TEK kaynak): `review · <proje> · <mode>/<model> · <yyyy-MM-dd HH:mm>`.
    `ts` epoch ya da 14 haneli `yyyyMMddHHmmss` damgası; çözülemezse zaman parçası atlanır."""
    when = ""
    try:
        if isinstance(ts, str) and re.fullmatch(r"\d{14}", ts):
            when = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}"
        elif ts not in (None, ""):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except (ValueError, TypeError, OverflowError, OSError):
        when = ""
    parts = ["review", str(project), f"{mode}/{model}"] + ([when] if when else [])
    return " · ".join(parts)


def pair_key(proj: str, t: ReviewTarget) -> str:
    return f"{proj}|{t.mode}/{t.pslug}"


# ── planlayıcı ────────────────────────────────────────────────────────────────

def _pairs(history: Any) -> Dict[str, Dict[str, Any]]:
    p = history.get("pairs") if isinstance(history, dict) else None
    return p if isinstance(p, dict) else {}


def _fresh(rec: Any, now: float, window: float) -> bool:
    return (isinstance(rec, dict) and rec.get("status") == "done"
            and now - float(rec.get("finished_at") or 0) < window)


def project_complete(history: Any, proj: str, targets: Sequence[ReviewTarget], now: float,
                     window: float = WINDOW_SECONDS) -> bool:
    """Her hedef için `window` içinde `done` çift var mı? (hedef listesi boşsa tamam SAYILMAZ)"""
    pairs = _pairs(history)
    return bool(targets) and all(_fresh(pairs.get(pair_key(proj, t)), now, window) for t in targets)


def pool_enabled(pool: Any) -> List[str]:
    """Havuzda etkin (enabled, removed_at yok) proje adları, sıralı."""
    pr = pool.get("projects") if isinstance(pool, dict) else None
    if not isinstance(pr, dict):
        return []
    return sorted(n for n, e in pr.items() if isinstance(e, dict) and e.get("enabled") and not e.get("removed_at"))


def next_review(pool: Any, history: Any, targets: Sequence[ReviewTarget], now: float,
                busy_projects: Sequence[str] = (), window: float = WINDOW_SECONDS,
                head_of: Optional[Callable[[str], str]] = None) -> Optional[Tuple[str, ReviewTarget]]:
    """Sıradaki (proje, hedef) ya da None. TEK proje: önce yarım kalan (bazı çiftleri taze, bazısı değil), sonra hiç
    çifti olmayan, sonra en eskisi (en yeni bitişi en eski olan). Tamam projeler, `busy_projects` ve çalışan çiftler
    atlanır; `head_of(proje)` (git HEAD, "" = bilinmiyor) verilirse pencere dolsa da `done` çiftin kayıtlı `head`i güncel
    HEAD'e EŞİTSE taze sayılır (değişmeyen koda yeniden review yok); `max_attempts(mod)`i (Evren 1, diğerleri `MAX_ATTEMPTS`) dolduran error/model_fallback/partial çifti `window` dolana dek denenmez."""
    skip = set(blocked_modes(history, now))
    targets = [t for t in targets if t.mode not in skip and t.key not in skip]   # kotası biten mod / model sıfırlanana dek denenmez
    if not targets:
        return None
    pairs = _pairs(history)
    busy = set(busy_projects)
    cands: List[Tuple[int, float, str, ReviewTarget]] = []
    for proj in pool_enabled(pool):
        if proj in busy:
            continue
        recs = [pairs.get(pair_key(proj, t)) for t in targets]
        if any(isinstance(r, dict) and r.get("status") == "running" for r in recs):
            continue                                   # projede çalışan çift var: aynı projeye ikinci iş yok
        _hd: List[str] = []

        def _same_head(r: Any) -> bool:
            if head_of is None or not isinstance(r, dict) or r.get("status") != "done" or not r.get("head"):
                return False
            if not _hd:
                try:
                    _hd.append(str(head_of(proj) or ""))
                except Exception:
                    _hd.append("")
            return bool(_hd[0]) and _hd[0] == r.get("head")

        def _fresh_or_same(r: Any) -> bool:
            return _fresh(r, now, window) or _same_head(r)

        pick = None
        for t, r in zip(targets, recs):
            if _fresh_or_same(r):
                continue
            if (isinstance(r, dict) and r.get("status") in ("error", "model_fallback", "partial")
                    and int(r.get("attempts") or 0) >= max_attempts(t.mode) and counts_as_attempt(r)
                    and now - float(r.get("started_at") or 0) < window):
                continue
            pick = t
            break
        if pick is None:
            continue
        nfresh = sum(1 for r in recs if _fresh_or_same(r))
        known = [float(r.get("finished_at") or r.get("started_at") or 0) for r in recs if isinstance(r, dict)]
        if nfresh:
            cands.append((0, -nfresh, proj, pick))     # yarım: en çok tamamlanmış olan önce
        elif not known:
            cands.append((1, 0.0, proj, pick))
        else:
            cands.append((2, max(known), proj, pick))
    if not cands:
        return None
    cands.sort(key=lambda c: (c[0], c[1], c[2]))
    return cands[0][2], cands[0][3]


# ── havuz ─────────────────────────────────────────────────────────────────────

def pool_sync(pool: Any, owner_names: Sequence[str], now: float) -> Tuple[Dict[str, Any], bool]:
    """Havuzu değnekçilerin sahip olduğu proje adlarıyla eşler: yeni ad `auto` eklenir; `auto` kayıt sahipsiz kalırsa
    `enabled=False, removed_at=now`, geri gelirse (elle kapatılmamışsa) yeniden açılır. `manual` kayıtlara
    DOKUNULMAZ. (yeni_havuz, değişti_mi) döner; girdi değiştirilmez."""
    src = pool.get("projects") if isinstance(pool, dict) else None
    projects: Dict[str, Any] = {k: dict(v) for k, v in (src or {}).items() if isinstance(v, dict)}
    owners = {n for n in owner_names if isinstance(n, str) and n}
    changed = False
    for n in sorted(owners):
        e = projects.get(n)
        if e is None:
            projects[n] = {"enabled": True, "source": "auto", "added_at": now, "removed_at": None}
            changed = True
        elif e.get("source") == "auto" and e.get("removed_at"):
            e.update(enabled=True, removed_at=None)
            changed = True
    for n, e in projects.items():
        if n not in owners and e.get("source") == "auto" and not e.get("removed_at"):
            e.update(enabled=False, removed_at=now)
            changed = True
    return {"projects": projects}, changed


# ── istem ─────────────────────────────────────────────────────────────────────

def build_review_prompt(proj: str, cwd: str, lang: str = "tr") -> str:
    """Salt-okunur kod/belge incelemesi istemi. Bulgu biçimi `parse_findings` ile eşleşir:
    `## R-<n> | P1|P2|P3 | dosya:satır | başlık` + gövde."""
    forb = ", ".join(FORBIDDEN_PATHS)
    if lang == "en":
        return (f"You are an independent code reviewer for the project \"{proj}\" (working directory: {cwd}).\n"
                "This is a READ-ONLY review: do not create, edit, move or delete any file, do not run installers, "
                "do not commit, push or contact the network.\n"
                f"Never open, quote or summarise these paths (they may hold secrets): {forb}. If you see a secret, "
                "do not repeat it.\n"
                "Do NOT open anything under a `reviews/` directory (earlier review reports and transcripts): "
                "they would bias you and may contain masked secrets. Judge the code itself.\n"
                "Find real defects: correctness bugs, data loss, security problems, races, broken error handling, "
                "stale docs that mislead. Skip style nits. Verify each claim in the code before reporting it.\n"
                "Report each finding as a heading line exactly like\n"
                "## R-1 | P2 | path/to/file.py:123 | Short title\n"
                "(severity P1 = critical, P2 = important, P3 = minor; numbering R-1, R-2, ...) followed by a short "
                "body: what is wrong, why, how to reproduce or check, suggested fix. No findings: write 'NO FINDINGS'.")
    return (f"\"{proj}\" projesi için bağımsız bir kod gözden geçiricisisin (çalışma dizini: {cwd}).\n"
            "Bu SALT OKUNUR bir incelemedir: hiçbir dosyayı oluşturma, değiştirme, taşıma ya da silme; kurulum "
            "çalıştırma; commit/push yapma; ağa çıkma.\n"
            f"Şu yolları ASLA açma, alıntılama, özetleme (parola içerebilir): {forb}. Bir gizli değer görürsen "
            "tekrarlama.\n"
            "`reviews/` dizininin altındaki hiçbir şeyi açma (önceki review raporları ve kayıtları): seni yanlı "
            "yapar ve maskelenmiş gizli değer içerebilir. Yalnız kodun kendisini değerlendir.\n"
            "Gerçek kusurları bul: doğruluk hataları, veri kaybı, güvenlik, yarış durumu, bozuk hata yönetimi, "
            "yanıltan eski belgeler. Biçim önerilerini atla. Her iddiayı raporlamadan önce kodda doğrula.\n"
            "Her bulguyu tam şu biçimde bir başlık satırıyla ver:\n"
            "## R-1 | P2 | yol/dosya.py:123 | Kısa başlık\n"
            "(önem P1 = kritik, P2 = önemli, P3 = küçük; numaralama R-1, R-2, ...) ve altında kısa gövde: ne yanlış, "
            "neden, nasıl doğrulanır, önerilen düzeltme. Bulgu yoksa 'BULGU YOK' yaz.")


_FINDING_RE = re.compile(r"^#{2,4}\s*(R-\d+)\s*\|\s*(P[123])\s*\|\s*(.*?)\s*\|\s*(.+?)\s*$")


def parse_findings(md: str) -> List[Dict[str, str]]:
    """Review çıktısından bulgular: `[{ref, severity, where, title, body}]` (kod çitleri içindeki başlıklar sayılmaz;
    aynı `ref` ikinci kez gelirse atlanır). Biçime uymayan metin yok sayılır."""
    out: List[Dict[str, str]] = []
    cur: Optional[Dict[str, Any]] = None
    fence = False
    seen: Set[str] = set()
    for line in str(md or "").splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            if cur is not None:
                cur["lines"].append(line)
            continue
        m = None if fence else _FINDING_RE.match(line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            cur = {"ref": m.group(1), "severity": m.group(2), "where": m.group(3), "title": m.group(4), "lines": []}
            out.append(cur)
        elif cur is not None:
            if not fence and re.match(r"^#{1,2}\s", line):
                cur = None                              # başka bir üst başlık bulguyu bitirir
            else:
                cur["lines"].append(line)
    return [{"ref": c["ref"], "severity": c["severity"], "where": c["where"], "title": c["title"],
             "body": "\n".join(c["lines"]).strip()} for c in out]


# ── gizli değer ayıklama ──────────────────────────────────────────────────────

# `scheme://kullanıcı:PAROLA@host`: parola grubu 2; IoLog bu parolayı ÖĞRENİR ve düz metinde (DSN dışında) de maskeler.
_DSN_RE = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s:/@\"']+:)([^\s@/\"']{3,})(@)")

_SECRET_RES = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),     # JWT
    re.compile(r"\btk_[A-Za-z0-9]{16,}"),                                              # ntfy
    # anahtar (db_password, API_KEY, "password", \"api_key\" dahil; tırnak/kaçışlı tırnak) + `:`/`=` + değer
    re.compile(r"(?i)((?:api[_-]?key|secret|token|pass(?:w(?:or)?d)?|authorization)[\w-]*[\\\"']{0,2}\s*[:=]\s*[\\]?[\"']?)[^\s\\\"',;]{8,}"),
    re.compile(r"(?i)(--(?:password|passwd|token|api-key|secret)[ =])[^\s\"']{4,}"),
)


def dsn_passwords(text: str) -> List[str]:
    """Metindeki `scheme://user:PAROLA@host` parolaları (IoLog öğrenip sonraki olaylarda düz metinde de maskeler)."""
    return [m.group(2) for m in _DSN_RE.finditer(str(text or "")) if m.group(2) != "[REDACTED]"]


def redact_secrets(text: str, learned: Sequence[str] = ()) -> str:
    """Bilinen gizli değer biçimlerini `[REDACTED]` yapar (review çıktısı diske/panele yazılmadan önce). `learned`:
    daha önce görülmüş sır değerleri (DSN parolası) düz metinde de maskelenir."""
    text = str(text or "")
    learned = list(learned) + [pw for pw in dsn_passwords(text) if pw not in learned]   # bu metindeki DSN parolası metnin her yerinde maskelenir
    out = _DSN_RE.sub(lambda m: m.group(1) + "[REDACTED]" + m.group(3), text)
    for s in sorted(learned, key=len, reverse=True):
        if s:
            out = out.replace(s, "[REDACTED]")
    for rx in _SECRET_RES:
        if rx.groups:
            out = rx.sub(lambda m: m.group(1) + "[REDACTED]", out)
        else:
            out = rx.sub("[REDACTED]", out)
    return out


# ── agy izin kuralı (başsız kipte komut izni sorulamaz: koşu "auto-denied" ile ölür) ───────────

# Yalnız salt-okunur komutlar. Deneyle (2026-10-24): `command(ls)` `ls -la`yı kabul eder; `a && rm x`, `a; rm x`, `$(rm x)`,
# `> dosya` YÖNLENDİRMESİ reddedilir (komut bütün olarak ayrıştırılır). BİLEREK YOK: rg (--pre komut çalıştırır),
# git log/diff/show (--output dosya yazar), find (-exec/-delete), cat (yasak yolları okutur), sed/awk/xargs/sh/python.
AGY_ALLOW_DEFAULT = ("ls", "grep", "head", "tail", "wc")


def agy_allow_list(spec: Any) -> List[str]:
    """`review_agy_allow` ayarı: "" = varsayılan; "off" = izolasyon kapalı (eski davranış). Virgülle ayrık komut adları."""
    t = str(spec or "").strip()
    if t.lower() == "off":
        return []
    names = [x.strip() for x in t.split(",") if x.strip()] or list(AGY_ALLOW_DEFAULT)
    return [n for n in names if re.fullmatch(r"[A-Za-z0-9._-]+", n)]


def agy_settings(cwd: str, allow: Sequence[str]) -> Dict[str, Any]:
    """İzole agy HOME'unun `.gemini/antigravity-cli/settings.json`u: yalnız `allow` komutları, çalışma alanı dışı erişim yok."""
    return {"allowNonWorkspaceAccess": False,
            "permissions": {"allow": [f"command({a})" for a in allow]},
            "trustedWorkspaces": [cwd]}


# ── agy etiket doğrulama ──────────────────────────────────────────────────────

_LABEL_RE = re.compile(r"Propagating selected model override\b.*?\blabel=(\"[^\"]*\"|'[^']*'|\S+)")


def _norm_label(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


def agy_label_ok(log_text: str, model: str) -> Tuple[bool, str]:
    """agy log'unda `Propagating selected model override ... label=<L>` satırlarından SONUNCUSU istenen modelle
    uyuşuyor mu (büyük/küçük harf ve ayraç farkı yok sayılır; biri ötekini içeriyorsa uyuşur)? Etiket yoksa
    `(False, "")`. Dönüş: (uyuştu, görülen etiket) — sessiz model düşüşünü (`model_fallback`) yakalamak için."""
    labels = [m.group(1).strip("\"'") for m in _LABEL_RE.finditer(str(log_text or ""))]
    if not labels:
        return False, ""
    seen = labels[-1]
    a, b = _norm_label(seen), _norm_label(model)
    return bool(a and b and (a == b or a in b or b in a)), seen


# ── yollar ────────────────────────────────────────────────────────────────────

def effort_for(cfg: Any, mode: str, target: Optional["ReviewTarget"] = None) -> str:
    """Yol katmanı için effort adı: claude/codex/copilot `review_<mode>_effort`, diğerleri (agy: kademe model adında, evren:
    bayrak yok) `default`. Hedefte `model@effort` ile effort verilmişse o geçer."""
    v = getattr(target, "effort", "") if target is not None else ""
    if not str(v or "").strip():
        v = getattr(cfg, f"review_{mode}_effort", "") if mode in ("claude", "codex", "copilot") else ""
    return slug_model(v) if str(v or "").strip() else "default"


def review_path(root: str, proj: str, t: ReviewTarget, ts: Any, effort: str = "") -> str:
    """`<root>/<proje>/<mode>/<altmodel>[/<effort>]/<yyyyMMddHHmmss>/<yyyyMMddHHmmss>.md`; `ts` epoch (yerel saat) ya da
    hazır 14 haneli metin. Her koşunun dosyaları (rapor, `.io.jsonl`, `.model.md`, `.usage.jsonl`) kendi `<ts>/` klasöründe
    toplanır; hepsi `<ts>` önekini korur, bu yüzden `.md` -> yan dosya türetmeleri aynen çalışır. `root` genelde
    `StewardPaths.reviews`. Proje adı yol güvenli hale getirilir. `effort` boşsa effort katmanı yok. (2026-10-24'ten önceki
    koşular eski düz düzende `<ts>.md`; kayıtlı yollar olduğu gibi okunur.)"""
    stamp = ts if isinstance(ts, str) and re.fullmatch(r"\d{14}", ts) else time.strftime("%Y%m%d%H%M%S", time.localtime(float(ts)))
    parts = [root, slug_model(proj), t.mode, t.slug] + ([slug_model(effort)] if effort else [])
    return os.path.join(*parts, stamp, stamp + ".md")


def draft_path(md: str) -> str:
    """Evren modelinin (`ucli --allow-create-dir`) kendi eliyle yazdığı rapor taslağı: raporun yanında `<ts>.model.md`.
    Zaman aşımında stdout boşsa kurtarma kaynağı olur."""
    return (md[:-3] if md.endswith(".md") else md) + ".model.md"


def partial_path(md: str) -> str:
    """ucli `--partial-file` hedefi: görev her araç turu sınırında JSON yazar (partial, tool_rounds, tool_calls, written,
    assistant_text = son 32 KiB); duvar saati bütçesinde SIGKILL gelirse kurtarma kaynağı olur."""
    return (md[:-3] if md.endswith(".md") else md) + ".partial.json"


def error_path(md: str) -> str:
    """Başarısız koşunun kalıcı hata günlüğü: hata iletisi + stdout/stderr kuyruğu (maskeli, 0600)."""
    return (md[:-3] if md.endswith(".md") else md) + ".error.txt"


def draft_prompt_suffix(draft: str, lang: str = "tr") -> str:
    """Evren istemine eklenen: raporu create-only `write_file` ile TEK SEFERDE `draft` yoluna da yaz."""
    if lang == "en":
        return (f"\nAdditionally, as soon as your findings are ready, write the SAME report once with write_file to the "
                f"absolute path {draft} (create-only: it fails if the file exists, so write it exactly once, never "
                "partially). You may not write anywhere else. Then also reply with the report.")
    return (f"\nAyrıca bulgularını hazırlar hazırlamaz AYNI raporu write_file ile {draft} mutlak yoluna TEK SEFERDE yaz "
            "(yalnız yeni dosya: varsa hata verir, o yüzden tam bir kez yaz, parça parça değil). Başka hiçbir yere "
            "yazamazsın. Sonra raporu yanıt olarak da ver.")


# ── günlük kota engeli (Evren: hesap geneli 15M/gün, UTC gece yarısı sıfırlanır) ───────────────

_LIMIT_RE = re.compile(r"daily_token_limit_exceeded|daily token limit|exceeded your monthly quota", re.I)


def is_daily_limit(*texts: Any) -> bool:
    return any(_LIMIT_RE.search(str(t or "")) for t in texts)


def next_utc_midnight(now: float) -> float:
    return (int(now) // 86400 + 1) * 86400.0


def next_utc_month_start(now: float) -> float:
    """Sonraki ayın 1'i 00:00 UTC (aylık kota, ör. copilot `exceeded your monthly quota`)."""
    t = time.gmtime(now)
    y, m = (t.tm_year + 1, 1) if t.tm_mon == 12 else (t.tm_year, t.tm_mon + 1)
    return float(calendar.timegm((y, m, 1, 0, 0, 0)))


def block_until_for_limit(now: float, *texts: Any) -> float:
    """Günlük/aylık kota engelinin bitişi: "monthly" geçiyorsa ayın sonu, değilse UTC gece yarısı."""
    if any(re.search(r"monthly", str(t or ""), re.I) for t in texts):
        return next_utc_month_start(now)
    return next_utc_midnight(now)


BANNER_MAX_CHARS = 600


def is_short_banner(text: Any) -> bool:
    """Çıkış kodu 0 ama stdout'ta rapor yerine KISA bir sağlayıcı mesajı (ör. copilot kota mesajı) var mı? Bulgu başlığı
    (`## R-`) ya da uzun metin gerçek rapordur: onda "quota" sözü geçmesi (kodu inceleyen rapor) limit sayılmaz."""
    t = str(text or "").strip()
    return 0 < len(t) < BANNER_MAX_CHARS and "## R-" not in t


# Model başına kota (agy: `RESOURCE_EXHAUSTED (code 429): Individual quota reached ... Resets in 107h49m47s.`): yalnız o
# mod/model sıfırlanana dek planlayıcıdan çıkar (günlük hesap geneli kota ise TÜM mod: `is_daily_limit`).
_QUOTA_RE = re.compile(r"RESOURCE_EXHAUSTED|Individual quota reached|quota reached", re.I)
_RESET_RE = re.compile(r"resets?\s+in\s+((?:\d+\s*[dhms]\s*)+)", re.I)
_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
QUOTA_FALLBACK_SECONDS = 1800.0      # kota hatası ama sıfırlanma süresi okunamadı: yarım saat sonra yeniden dene
QUOTA_MAX_SECONDS = 14 * 86400.0     # saçma uzun süreyi kırp


def is_quota_exhausted(*texts: Any) -> bool:
    return any(_QUOTA_RE.search(str(t or "")) for t in texts)


def reset_seconds(*texts: Any) -> Optional[float]:
    """"Resets in 107h49m47s" -> saniye (d/h/m/s birimleri); okunamazsa None. İlk eşleşen metin kazanır."""
    for t in texts:
        m = _RESET_RE.search(str(t or ""))
        if m:
            total = sum(int(n) * _UNIT_SECONDS[u.lower()] for n, u in re.findall(r"(\d+)\s*([dhmsDHMS])", m.group(1)))
            if total > 0:
                return float(min(total, QUOTA_MAX_SECONDS))
    return None


def quota_block_until(now: float, *texts: Any) -> float:
    return now + (reset_seconds(*texts) or QUOTA_FALLBACK_SECONDS)


def set_block(paths: Any, key: str, until: float, reason: str = "") -> None:
    """`key`: mod (`evren`: tüm mod) ya da `mod/slug` (tek model, `ReviewTarget.key`)."""
    p = sw._pp(paths)
    with sw.steward_lock(p):
        hist = load_history(p)
        hist.setdefault("blocks", {})[key] = {"until": float(until), "reason": reason}
        save_history(p, hist)


def blocked_modes(history: Any, now: float) -> List[str]:
    """Süresi dolmamış engellerin anahtarları (mod ya da `mod/slug`)."""
    b = history.get("blocks") if isinstance(history, dict) else None
    if not isinstance(b, dict):
        return []
    return sorted(m for m, e in b.items() if isinstance(e, dict) and float(e.get("until") or 0) > now)


# ── depolar ───────────────────────────────────────────────────────────────────

def load_pool(paths: Any) -> Dict[str, Any]:
    raw = sw._load_json(sw._pp(paths).review_pool, {})
    return raw if isinstance(raw, dict) and isinstance(raw.get("projects"), dict) else {"projects": {}}


def save_pool(paths: Any, pool: Dict[str, Any]) -> None:
    sw._save_json(sw._pp(paths).review_pool, pool)


def load_history(paths: Any) -> Dict[str, Any]:
    raw = sw._load_json(sw._pp(paths).review_history, {})
    if not isinstance(raw, dict):
        raw = {}
    if not isinstance(raw.get("pairs"), dict):
        raw["pairs"] = {}
    if not isinstance(raw.get("runs"), list):
        raw["runs"] = []
    raw["version"] = HISTORY_VERSION
    return raw


def save_history(paths: Any, hist: Dict[str, Any]) -> None:
    hist = dict(hist)
    hist["runs"] = list(hist.get("runs") or [])[-HISTORY_RUNS_MAX:]
    sw._save_json(sw._pp(paths).review_history, hist)


def _run_seconds(rec: Dict[str, Any]) -> Optional[float]:
    """Koşunun duvar süresi (sn): `finished_at - started_at`; ikisi de yoksa ya da tutarsızsa None (uydurma yok)."""
    try:
        a, b = float(rec.get("started_at") or 0), float(rec.get("finished_at") or 0)
    except (TypeError, ValueError):
        return None
    return round(b - a, 1) if a > 0 and b >= a else None


def update_pair(paths: Any, proj: str, t: ReviewTarget, **fields: Any) -> Dict[str, Any]:
    """Çift kaydını kilit altında okuyup-değiştirip-yazar (`status`, `started_at`, `finished_at`, `file`, `error`,
    `label_seen`, `pid`, `attempts`...). `status="running"` yeni denemeyse `attempts` +1 (çağıran `attempts=`
    vermediyse). Güncel kaydı döner; bitiş durumlarında `runs`a özet satır eklenir."""
    p = sw._pp(paths)
    if fields.get("status") is not None and fields["status"] not in PAIR_STATUSES:
        raise ValueError(f"invalid pair status: {fields['status']!r}")
    with sw.steward_lock(p):
        hist = load_history(p)
        key = pair_key(proj, t)
        rec = dict(hist["pairs"].get(key) or {})
        if fields.get("status") == "running" and "attempts" not in fields:
            # önceki pencerenin sonucu (done ya da pencere dışı) sayaca taşınmaz: yeni pencere 1. denemeyle başlar
            stale = rec.get("status") == "done" or (
                float(fields.get("started_at") or 0) - float(rec.get("started_at") or 0) >= WINDOW_SECONDS)
            fields["attempts"] = (0 if stale else int(rec.get("attempts") or 0)) + 1
        rec.update(fields)
        hist["pairs"][key] = rec
        if fields.get("status") in ("done", "partial", "error", "model_fallback", "limit"):
            hist["runs"].append({"pair": key, "status": rec["status"], "at": rec.get("finished_at"), "file": rec.get("file"),
                                "io_file": rec.get("io_file"), "seconds": _run_seconds(rec)})
        save_history(p, hist)
    return rec


def load_findings(paths: Any) -> Dict[str, Any]:
    raw = sw._load_json(sw._pp(paths).findings, {})
    return raw if isinstance(raw, dict) else {}


def save_findings(paths: Any, findings: Dict[str, Any]) -> None:
    sw._save_json(sw._pp(paths).findings, findings)


def finding_key(proj: str, where: Any, title: Any) -> str:
    """Bulgu kimliği (TBD#137c): (proje, dosya, normalize başlık) hash'i. Dosya = `where`in `:satır` öncesi; başlık küçük harf,
    harf/rakam dışı atılır: aynı hata farklı koşuda/satırda yeniden bulunsa aynı anahtar."""
    fil = re.split(r"[:#]", str(where or "").strip(), 1)[0].strip().lower()
    ttl = re.sub(r"[^0-9a-zçğıöşü]+", " ", str(title or "").lower()).strip()
    return hashlib.sha1(f"{proj}\x00{fil}\x00{ttl}".encode("utf-8")).hexdigest()[:16]


def add_findings(paths: Any, proj: str, review_file: str, parsed: Sequence[Dict[str, str]]) -> List[str]:
    """Ayrıştırılmış bulguları `findings.json`a `state=new` ile ekler (kilit altında); eklenen fid'ler döner.
    fid = `<proje>:<review dosyası temel adı sıkıştırılmış>:<ref>`: aynı dosya iki kez işlenirse çoğalmaz.
    Aynı `finding_key`li bulgu zaten varsa (her durumda; reddedilmiş dahil) yenisi `state=dup`, `dup_of=<eski fid>` yazılır:
    doğrulama/onay/dışa aktarım hattına girmez, dönen listeye de girmez."""
    p = sw._pp(paths)
    base = re.sub(r"[^A-Za-z0-9]+", "", os.path.relpath(review_file, p.reviews) if review_file.startswith(p.reviews) else review_file)
    added: List[str] = []
    with sw.steward_lock(p):
        data = load_findings(p)
        by_key: Dict[str, str] = {}
        for ofid, orec in data.items():
            if isinstance(orec, dict) and orec.get("state") != "dup" and orec.get("project") == proj:
                by_key.setdefault(orec.get("key") or finding_key(proj, orec.get("where"), orec.get("title")), ofid)
        changed = False
        for f in parsed:
            fid = f"{slug_model(proj)}:{base}:{f['ref']}"
            if fid in data:
                continue
            key = finding_key(proj, f["where"], f["title"])
            rec = {"project": proj, "review_file": review_file, "ref": f["ref"], "severity": f["severity"],
                   "title": f["title"], "where": f["where"], "body": f["body"], "state": "new", "verdict": "",
                   "verdict_at": None, "decided_by": "", "decided_at": None, "exported_to": "",
                   "created_at": time.time(), "key": key}
            if key in by_key:
                rec["state"], rec["dup_of"] = "dup", by_key[key]
            else:
                by_key[key] = fid
                added.append(fid)
            data[fid] = rec
            changed = True
        if changed:
            save_findings(p, data)
    return added


# ── bulgu akışı (adım 7): doğrulama kararı, sahip onayı ──────────────────────
# Bulguyu BEYİN onaylamaz: projenin kendi oturumu bir Sonnet alt ajanla koda karşı doğrular (`STEWARD-REVIEW-VERDICT`
# satırı), sonra SAHİP bulgu başına onaylar/reddeder; yalnız onaylı bulgu TODO/TBD'ye dışa aktarılır.

VERDICT_MARK = "STEWARD-REVIEW-VERDICT:"
VERDICTS = ("verified", "refuted", "unclear")
VERIFIABLE_STATES = ("new", "verify_sent", "unclear")          # doğrulama direktifi gönderilebilir
APPROVABLE_STATES = ("verified", "unclear")                    # refuted/new/verify_sent approve EDİLEMEZ
REJECTABLE_STATES = ("new", "verify_sent", "verified", "refuted", "unclear")
VERIFY_MAX_FINDINGS = 20                                       # tek direktifte en çok bulgu
VERDICT_REASON_MAX = 500

# Satırın TAMAMI (baştaki boşluk hariç) işaretle başlamalı: düzyazıdaki anma, `...` içindeki örnek, madde imi sayılmaz.
_VERDICT_RE = re.compile(r"^STEWARD-REVIEW-VERDICT:[ \t]*([A-Za-z0-9][A-Za-z0-9._:-]*)[ \t]+(verified|refuted|unclear)"
                         r"(?:[ \t]+(.*))?$")
_PLACEHOLDER_RE = re.compile(r"^<[^<>\n]{1,80}>[\s`.…]*$")


def scan_verdicts(text: str) -> List[Tuple[str, str, str]]:
    """Oturum yanıtındaki GERÇEK `STEWARD-REVIEW-VERDICT: <fid> verified|refuted|unclear <gerekçe>` satırları:
    `[(fid, karar, gerekçe)]` (aynı fid için son satır geçerli). A11 deseni: kod bloğu (```/~~~) içi, `>` alıntı,
    satır içinde geçen anma ve `<yer tutucu>` gerekçeli yazım örneği SAYILMAZ. SAF."""
    out: Dict[str, Tuple[str, str, str]] = {}
    fenced = False
    for raw in str(text or "").splitlines():
        s = raw.strip()
        if s.startswith("```") or s.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced or s.startswith(">"):
            continue
        m = _VERDICT_RE.match(s)
        if not m:
            continue
        reason = (m.group(3) or "").strip()
        if _PLACEHOLDER_RE.match(reason):
            continue
        out[m.group(1)] = (m.group(1), m.group(2), reason[:VERDICT_REASON_MAX])
    return list(out.values())


def text_hash(text: str) -> str:
    import hashlib
    return hashlib.sha1(str(text or "").encode("utf-8", "replace")).hexdigest()


def apply_verdicts(findings: Dict[str, Any], project: str, verdicts: Sequence[Tuple[str, str, str]], src_hash: str,
                   session: str, now: float) -> List[str]:
    """`findings`i YERİNDE günceller; uygulanan fid'ler döner. Kabul: bilinen fid, aynı proje, durum `verify_sent`,
    ve metin doğrulama gönderilirken görülen (eski) son yanıt DEĞİL (`verify_baseline`) ya da bu fid'e daha önce
    uygulanmış metin değil (`verdict_src`). SAF."""
    applied: List[str] = []
    for fid, verdict, reason in verdicts:
        rec = findings.get(fid)
        if not isinstance(rec, dict) or rec.get("project") != project or rec.get("state") != "verify_sent":
            continue
        if verdict not in VERDICTS or src_hash in (rec.get("verify_baseline"), rec.get("verdict_src")):
            continue
        rec.update(state=verdict, verdict=reason, verdict_at=now, verdict_session=session, verdict_src=src_hash)
        applied.append(fid)
    return applied


VERIFY_REQUEUE_SECONDS = 6 * 3600       # oturum doğrulaması bu kadar süredir cevapsız (karar son mesajda değildi/oturum yok): yeniden sıraya
VERIFY_MAX_TRIES = 3                    # bulgu başına doğrulama gönderimi; dolunca `unclear` (elle bakılır)


def requeue_stale_verify(findings: Dict[str, Any], now: float, stale: float = VERIFY_REQUEUE_SECONDS) -> List[str]:
    """`findings`i YERİNDE günceller; OTURUM doğrulamasında (`verify_session != "self"`) `stale` sn'dir cevapsız kalan
    `verify_sent` bulguyu `new`e döndürür (`verify_tries`+1; `VERIFY_MAX_TRIES` dolunca `unclear`). Karar yalnız SON asistan
    mesajından okunduğu için proje oturumu araya başka mesaj üretirse karar bir daha görülmez; bulgu sonsuza dek
    `verify_sent` kalmasın. Dönen: etkilenen fid'ler. SAF."""
    out: List[str] = []
    for fid, rec in findings.items():
        if not isinstance(rec, dict) or rec.get("state") != "verify_sent" or rec.get("verify_session") == "self":
            continue
        if now - float(rec.get("verify_sent_at") or 0) < stale:
            continue
        tries = int(rec.get("verify_tries") or 0) + 1
        if tries >= VERIFY_MAX_TRIES:
            rec.update(state="unclear", verify_tries=tries, verdict_at=now,
                       verdict=f"doğrulama {tries} gönderimde sonuç vermedi (karar son mesajda görülmedi)"[:VERDICT_REASON_MAX])
        else:
            rec.update(state="new", verify_tries=tries)
        out.append(fid)
    return out


def usage_summary(reviews_root: str, project: str = "") -> List[Dict[str, Any]]:
    """`<reviews>/<proje>/<mod>/<model>/.../<ts>/<ts>.usage.jsonl` (ucli `--usage-log`) dosyalarını (proje, mod/model) başına toplar:
    koşu, istek, istem/cevap/akıl yürütme/önbellekli token, istek süresi. En çok istem token'ı olan önce. Okunamayan satır/dosya
    atlanır. Yalnız SAYILAR okunur (istem/cevap metni dosyada yok). Koşu başına maliyet sorusunun cevabı."""
    agg: Dict[Tuple[str, str], Dict[str, Any]] = {}
    root = os.path.abspath(reviews_root)
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            if not fn.endswith(".usage.jsonl"):
                continue
            parts = os.path.relpath(os.path.join(dp, fn), root).split(os.sep)
            if len(parts) < 4:
                continue
            proj, tgt = parts[0], parts[1] + "/" + parts[2]
            if project and proj != project:
                continue
            a = agg.setdefault((proj, tgt), {"project": proj, "target": tgt, "runs": 0, "requests": 0, "prompt_tokens": 0,
                                             "completion_tokens": 0, "reasoning_tokens": 0, "cached_tokens": 0, "total_tokens": 0,
                                             "seconds": 0.0})
            a["runs"] += 1
            try:
                with open(os.path.join(dp, fn), encoding="utf-8", errors="replace") as f:
                    for ln in f:
                        try:
                            e = json.loads(ln)
                        except ValueError:
                            continue
                        if not isinstance(e, dict) or e.get("event") != "request":
                            continue
                        u = e.get("usage") if isinstance(e.get("usage"), dict) else {}
                        a["requests"] += 1
                        a["seconds"] += float(e.get("seconds") or 0)
                        for src, dst in (("prompt_tokens", "prompt_tokens"), ("completion_tokens", "completion_tokens"),
                                         ("reasoning_tokens", "reasoning_tokens"), ("cached_tokens", "cached_tokens"),
                                         ("total_tokens", "total_tokens")):     # total: yalnız toplam bildiren sağlayıcı (codex)
                            v = u.get(src)
                            if isinstance(v, (int, float)) and not isinstance(v, bool):
                                a[dst] += int(v)
            except OSError:
                continue
    return sorted(agg.values(), key=lambda r: (-(r["prompt_tokens"] or r["total_tokens"]), r["project"], r["target"]))


def duration_summary(history: Any, project: str = "") -> List[Dict[str, Any]]:
    """`runs` kayıtlarından (proje, mod/model) başına TÜM sağlayıcılar için koşu sayısı ve duvar süresi. Süresi kayıtlı olmayan
    (eski) koşular `unknown` sayılır, süreye katılmaz. En çok süre önce."""
    agg: Dict[Tuple[str, str], Dict[str, Any]] = {}
    runs = history.get("runs") if isinstance(history, dict) else None
    for r in runs if isinstance(runs, list) else []:
        if not isinstance(r, dict) or "|" not in str(r.get("pair") or ""):
            continue
        proj, tgt = str(r["pair"]).split("|", 1)
        if project and proj != project:
            continue
        a = agg.setdefault((proj, tgt), {"project": proj, "target": tgt, "runs": 0, "timed": 0, "unknown": 0, "seconds": 0.0})
        a["runs"] += 1
        sec = r.get("seconds")
        if isinstance(sec, (int, float)) and not isinstance(sec, bool) and sec >= 0:
            a["timed"] += 1
            a["seconds"] += float(sec)
        else:
            a["unknown"] += 1
    return sorted(agg.values(), key=lambda r: (-r["seconds"], r["project"], r["target"]))


def build_verify_message(rows: Sequence[Dict[str, Any]], lang: str = "tr") -> str:
    """Proje oturumuna giden doğrulama direktifi. `rows`: `id`, `severity`, `where`, `title` alanlı bulgular."""
    items = "\n".join(f"- {r['id']} | {r.get('severity') or '?'} | {r.get('where') or '?'} | "
                      f"{' '.join(str(r.get('title') or '').split())[:200]}" for r in rows)
    if lang == "en":
        return ("An independent code review reported the findings below. Start a Sonnet sub-agent (model: sonnet) and "
                "have it check EACH finding against the current code. Do NOT fix anything, do not edit files, do not "
                "commit.\nFindings (id | severity | location | title):\n" + items + "\n"
                "At the END of your answer write one line per finding, at the very start of the line (not inside a code "
                "block or a quote):\n"
                f"{VERDICT_MARK} <id> verified|refuted|unclear <one-sentence reason>")
    return ("Bağımsız bir kod incelemesi aşağıdaki bulguları raporladı. Bir Sonnet alt ajanı (model: sonnet) başlat ve "
            "HER bulguyu güncel koda karşı doğrulat. Düzeltme YAPMA, dosya değiştirme, commit etme.\n"
            "Bulgular (kimlik | önem | yer | başlık):\n" + items + "\n"
            "Cevabının SONUNDA her bulgu için ayrı bir satır yaz, satırın EN BAŞINDA (kod bloğu ya da alıntı içinde "
            "değil):\n"
            f"{VERDICT_MARK} <kimlik> verified|refuted|unclear <tek cümlelik gerekçe>")


def build_self_verify_prompt(rows: Sequence[Dict[str, Any]], lang: str = "tr") -> str:
    """Reviewer'ın KENDİ salt-okunur `claude -p` doğrulayıcısına giden istem (TBD#137 a=A): proje oturumu uyanmaz, alt ajan
    yok; doğrulayıcı kodu kendisi okur. Çıktı biçimi `build_verify_message` ile AYNI (`scan_verdicts` okur)."""
    items = "\n".join(f"- {r['id']} | {r.get('severity') or '?'} | {r.get('where') or '?'} | "
                      f"{' '.join(str(r.get('title') or '').split())[:200]}" for r in rows)
    if lang == "en":
        return ("An independent code review reported the findings below. Check EACH one against the CURRENT code in this "
                "directory (read-only: Read/Grep/Glob). Do not edit anything. A finding is `verified` when the code really "
                "shows it, `refuted` when the code contradicts it, `unclear` when you cannot tell.\nFindings (id | severity | "
                "location | title):\n" + items + "\nAt the END write one line per finding, at the very start of the line "
                f"(not inside a code block or quote):\n{VERDICT_MARK} <id> verified|refuted|unclear <one-sentence reason>")
    return ("Bağımsız bir kod incelemesi aşağıdaki bulguları raporladı. HER birini bu klasördeki GÜNCEL koda karşı kontrol et "
            "(salt okunur: Read/Grep/Glob). Hiçbir şeyi değiştirme. Kod bulguyu gerçekten gösteriyorsa `verified`, koda "
            "aykırıysa `refuted`, karar veremiyorsan `unclear`.\nBulgular (kimlik | önem | yer | başlık):\n" + items + "\n"
            "SONUNDA her bulgu için ayrı bir satır yaz, satırın EN BAŞINDA (kod bloğu ya da alıntı içinde değil):\n"
            f"{VERDICT_MARK} <kimlik> verified|refuted|unclear <tek cümlelik gerekçe>")


def mark_verify_sent(paths: Any, fids: Sequence[str], session: str, baseline: str, now: float) -> List[str]:
    """Doğrulama direktifi GİTTİKTEN sonra bulguları `verify_sent` yapar (kilit altında); yalnız hâlâ
    `VERIFIABLE_STATES`teki bulgular. `baseline`: gönderim anındaki son asistan metninin özeti (eski yanıt yeniden
    işlenmesin)."""
    p = sw._pp(paths)
    done: List[str] = []
    with sw.steward_lock(p):
        data = load_findings(p)
        for fid in fids:
            rec = data.get(fid)
            if isinstance(rec, dict) and rec.get("state") in VERIFIABLE_STATES:
                rec.update(state="verify_sent", verify_sent_at=now, verify_session=session, verify_baseline=baseline)
                done.append(fid)
        if done:
            save_findings(p, data)
    return done


def decide_finding(paths: Any, fid: str, action: str, now: float, by: str = "owner") -> Dict[str, Any]:
    """Sahibin bulgu kararı: approve (yalnız verified|unclear) | reject (dışa aktarılmamış ve kararsız bulgu)."""
    if action not in ("approve", "reject"):
        return {"ok": False, "error": "action must be approve or reject"}
    p = sw._pp(paths)
    with sw.steward_lock(p):
        data = load_findings(p)
        rec = data.get(fid)
        if not isinstance(rec, dict):
            return {"ok": False, "error": f"unknown finding: {fid}"}
        st = rec.get("state")
        allowed = APPROVABLE_STATES if action == "approve" else REJECTABLE_STATES
        if st not in allowed:
            return {"ok": False, "error": f"cannot {action} a finding in state {st!r} (allowed: {', '.join(allowed)})",
                    "state": st}
        rec.update(state="approved" if action == "approve" else "rejected", decided_by=by, decided_at=now)
        save_findings(p, data)
    return {"ok": True, "id": fid, "state": rec["state"]}


EXPORT_HEADING = "## Review bulguları"

_BACKTICK_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`")
_WHERE_FILE_RE = re.compile(r"^\s*`?([^\s:`]+\.[A-Za-z0-9]+)")


def _where_file(row: Dict[str, Any], cwd: str) -> str:
    m = _WHERE_FILE_RE.match(str(row.get("where") or ""))
    path = os.path.realpath(os.path.join(cwd, m.group(1))) if m else ""
    root = os.path.realpath(cwd)
    return path if path.startswith(root + os.sep) and os.path.isfile(path) else ""


def where_relpath(row: Dict[str, Any]) -> str:
    """Bulgunun `where` alanındaki dosya yolu (göreli); mutlak yol ya da `..` içeren yol "" (proje dışına çıkamaz)."""
    m = _WHERE_FILE_RE.match(str(row.get("where") or ""))
    rel = m.group(1) if m else ""
    return "" if (not rel or rel.startswith("/") or ".." in rel.split("/")) else rel


def has_quoted_names(row: Dict[str, Any]) -> bool:
    """Başlıkta backtick'li tanımlayıcı var mı (eskimiş-bulgu denetimi yalnız bunlarla karar verebilir)."""
    return bool(_BACKTICK_RE.search(str(row.get("title") or "")))


def stale_reason_text(row: Dict[str, Any], src: Optional[str]) -> Optional[str]:
    """`stale_reason`un SAF çekirdeği: `src` bulgunun dosyasının metni (None = okunamadı -> karar verilemez)."""
    if src is None:
        return None
    names = {n.split(".")[-1] for n in _BACKTICK_RE.findall(str(row.get("title") or ""))}
    if not names or any(n in src for n in names):
        return None
    return "tanımlayıcılar dosyada yok: " + ", ".join(sorted(names))


def stale_reason(row: Dict[str, Any], cwd: str) -> Optional[str]:
    """Bulgu koddaki duruma göre ESKİMİŞ mi? Yalnız kesin işaret: bulgunun dosyası var ve başlığındaki backtick'li
    tanımlayıcıların HİÇBİRİ dosyada geçmiyor (işlev silinmiş/yeniden adlandırılmış). Dosya yoksa ya da alıntılı ad yoksa
    karar verilemez (None)."""
    path = _where_file(row, cwd)
    if not path:
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError:
        return None
    return stale_reason_text(row, src)


def changed_after_review(row: Dict[str, Any], cwd: str) -> bool:
    """Bulgunun dosyası review raporundan SONRA değişti mi (git son commit zamanı, git yoksa mtime)? Karar verilemezse False."""
    path = _where_file(row, cwd)
    rf = str(row.get("review_file") or "")
    if not path or not rf or not os.path.exists(rf):
        return False
    try:
        t = os.path.getmtime(path)
        if os.path.isdir(os.path.join(cwd, ".git")):
            out = subprocess.run(["git", "-C", cwd, "log", "-1", "--format=%ct", "--", path], capture_output=True,
                                 text=True, timeout=10).stdout.strip()
            if out.isdigit():
                t = float(out)
        return t > os.path.getmtime(rf)
    except (OSError, subprocess.SubprocessError):
        return False


def export_lines(rows: Sequence[Dict[str, Any]], reviews_root: str) -> List[str]:
    out = []
    for r in rows:
        src = str(r.get("review_file") or "")
        if reviews_root and src.startswith(reviews_root.rstrip("/") + "/"):
            src = os.path.relpath(src, reviews_root)
        title = " ".join(str(r.get("title") or "").split())
        out.append(f"- [ ] (review {r['id']}) [{r.get('severity') or '?'}] {r.get('where') or '?'}: {title} "
                   f"(kaynak: {src})" + (f" [{r['note']}]" if r.get("note") else ""))
    return out


def appended_export(text: str, rows: Sequence[Dict[str, Any]], reviews_root: str, stamp: str) -> Tuple[Optional[str], List[str]]:
    """`text`in sonuna onaylı bulguları `EXPORT_HEADING` altında ekler. Dosyada kimliği zaten geçen bulgu yeniden
    yazılmaz. (yeni içerik ya da None, yazılan fid'ler). SAF."""
    fresh = [r for r in rows if f"(review {r['id']})" not in text]
    if not fresh:
        return None, []
    lines = export_lines(fresh, reviews_root)
    last_head = next((ln for ln in reversed(text.splitlines()) if ln.startswith("## ")), "")
    body = text.rstrip("\n")
    if last_head.startswith(EXPORT_HEADING):
        new = f"{body}\n" + "\n".join(lines) + "\n"
    else:
        new = (f"{body}\n\n" if body else "") + f"{EXPORT_HEADING} ({stamp})\n" + "\n".join(lines) + "\n"
    return new, [r["id"] for r in fresh]


_INCOMPLETE_RE = re.compile(r"tool[- ]call budget (?:was )?exhausted|budget exhausted|araç (?:çağrısı )?bütçesi\s+(?:\(\d+ çağrı\)\s+)?tükendi|inceleme(?:nin)? (?:durumu: )?tamamlanmadı", re.I)     # TBD#139: tek kelime `denetlenmemiştir` ("tests/ denetlenmemiştir" notu) yanlış pozitifti
_HAS_FINDING_RE = re.compile(r"^## R-\d+ \|", re.M)


def report_incomplete(text: str) -> bool:
    """Rapor "araç bütçesi tükendi / tamamlanmadı" diyor VE hiç `## R-n |` bulgu başlığı yok: `BULGU YOK` yazsa da bu bir
    inceleme değil kapsam beyanıdır; `done` değil `partial` sayılır (2026-10-26 A/B koşusu B: bütçe bitti, durum yine `done`)."""
    t = text or ""
    return bool(_INCOMPLETE_RE.search(t)) and not _HAS_FINDING_RE.search(t)



def anthropic_price(model: str) -> Tuple[float, float, float, float]:
    m = str(model or "")
    for k, v in ANTHROPIC_PRICES.items():
        if k in m:
            return v
    return ANTHROPIC_PRICES["opus-5-5"]       # bilinmeyen model: en pahalı varsayım (bütçe güvenli tarafta)


def usage_cost_usd(path: str, model: str) -> float:
    """Bir `.usage.jsonl` dosyasının $ maliyeti (istek başına ucli `usage`: girdi/çıktı/önbellek okuma/yazma). Tanınmayan
    alan 0 sayılır; hiç ayrıştırılamazsa dosya boyutundan bağımsız 0 döner (bütçe kapısı `anthropic_spent_usd` yedek tahmin ekler)."""
    pi, po, pr, pw = anthropic_price(model)
    tot = 0.0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    u = (json.loads(line) or {}).get("usage") or {}
                except ValueError:
                    continue
                def g(*names: str) -> float:
                    for n in names:
                        if isinstance(u.get(n), (int, float)):
                            return float(u[n])
                    return 0.0
                cr = g("cache_read_input_tokens", "cached_tokens", "cache_read_tokens")
                cw = g("cache_creation_input_tokens", "cache_write_tokens")
                inp = max(0.0, g("input_tokens", "prompt_tokens") - (0 if "cache_read_input_tokens" in u else cr) - (0 if "cache_creation_input_tokens" in u else cw))
                if "cached_tokens" in u and "cache_creation_input_tokens" not in u:
                    inp_price = pw      # ucli normalleştirilmiş sayaç: yazma ayrı raporlanmaz, önbellek istendiğinden yeni girdi yazma fiyatından sayılır (güvenli üst sınır)
                else:
                    inp_price = pi
                tot += (inp * inp_price + g("output_tokens", "completion_tokens") * po + cr * pr + cw * pw) / 1e6
    except OSError:
        pass
    return tot


def anthropic_spent_usd(reviews_root: str) -> float:
    """Tüm `anthropic` koşularının toplam $ (yalnız `<root>/*/anthropic/<model>/<effort>/<ts>/<ts>.usage.jsonl`)."""
    import glob
    tot = 0.0
    for f in glob.glob(os.path.join(reviews_root, "*", "anthropic", "*", "*", "*", "*.usage.jsonl")):
        parts = f.split(os.sep)
        tot += usage_cost_usd(f, parts[-4])
    return tot
