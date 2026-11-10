"""Reviewer rolü: saf çekirdek (ağ/süreç/tmux YOK). Planlama kararları, istem üretimi, bulgu ayrıştırma ve
`review_pool.json` / `review_history.json` / `findings.json` depoları. Çalıştırıcılar, tick döngüsü ve API
`commands/web_review.py`/`web_steward.py`'de; burada yalnız test edilebilir mantık var (`card` modülü gibi: girdi -> karar).

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
import unicodedata
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
    lens: str = ""     # inceleme merceği (`LENSES`); YALNIZ elle koşuda (`review run --lens`), havuz/planlayıcı hiç üretmez

    @property
    def pslug(self) -> str:
        """Çift anahtarındaki ad: aynı model birden çok effort ile ayrı çift olur (`slug@effort`); lens ayrı çift (`~lens`),
        böylece lensli koşu genel incelemenin geçmişini/pencere kararını bozmaz."""
        base = f"{self.slug}@{slug_model(self.effort)}" if self.effort else self.slug
        return f"{base}~{slug_model(self.lens)}" if self.lens else base

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


def excluded_keys(cfg: Any) -> Set[str]:
    """`review_excluded` (virgülle ayrık `mod/model` anahtarı, sahip onaylı çıkarma, TBD#163 c). `ReviewTarget.key` biçimi."""
    return set(_split_models(getattr(cfg, "review_excluded", "")))


def toggle_excluded(text: Any, key: str, exclude: bool) -> str:
    """`review_excluded` değerine `key` ekler/çıkarır (yinelemesiz, sıra korunur); boş sonuç "" döner."""
    cur = _split_models(text)
    if exclude and key not in cur:
        cur.append(key)
    if not exclude:
        cur = [c for c in cur if c != key]
    return ",".join(cur)


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
    skip = excluded_keys(cfg)
    return [t for t in out if t.key not in skip] if skip else out


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


def _num(v: Any, default: float = 0.0) -> float:
    """Diskten gelen (elle düzenlenmiş/bozuk) sayı alanı: sayıya çevrilemezse `default` (planlayıcı çökmesin)."""
    try:
        return float(v or 0)
    except (TypeError, ValueError, OverflowError):
        return default


def pair_key(proj: str, t: ReviewTarget) -> str:
    return f"{proj}|{t.mode}/{t.pslug}"


# ── planlayıcı ────────────────────────────────────────────────────────────────

def _pairs(history: Any) -> Dict[str, Dict[str, Any]]:
    p = history.get("pairs") if isinstance(history, dict) else None
    return p if isinstance(p, dict) else {}


def window_seconds(hours: Any) -> float:
    """`steward.review_window_hours` -> saniye; geçersiz/<=0 değerde varsayılan `WINDOW_SECONDS` (30 gün)."""
    try:
        h = float(hours)
    except (TypeError, ValueError):
        return float(WINDOW_SECONDS)
    return h * 3600.0 if h > 0 else float(WINDOW_SECONDS)


def _fresh(rec: Any, now: float, window: float) -> bool:
    return (isinstance(rec, dict) and rec.get("status") == "done"
            and now - _num(rec.get("finished_at")) < window)


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


def agy_pool(model: str) -> str:
    """agy kota havuzu (`agy --print /usage`): "Gemini 4 Argon" ayrı haftalık, diğer Gemini modelleri "gemini",
    Claude ve GPT (gpt-oss) modelleri TEK havuz "claude_gpt". Bilinmeyen model kendi adıyla (tek başına havuz)."""
    m = str(model or "").lower()
    if "argon" in m:
        return "argon"
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith(("claude", "gpt")):
        return "claude_gpt"
    return m


def model_family(t: "ReviewTarget") -> str:
    """Planlayıcının çeşitlilik birimi: agy'de kota havuzu, diğer modlarda modelin ilk adı (`glm-5.3` -> glm,
    `org/qwen3.8` -> qwen, `claude-sonnet-5-5` -> claude). Mod öneki: aynı aile iki modda ayrı sayılır."""
    if t.mode == "agy":
        return f"agy:{agy_pool(t.model)}"
    name = str(t.model or "").lower().rsplit("/", 1)[-1]
    m = re.match(r"[a-z]+", name)
    return f"{t.mode}:{m.group(0) if m else name}"


def _blocked_targets(targets: Sequence["ReviewTarget"], skip: Any) -> List["ReviewTarget"]:
    """Engelli mod / model düşer; agy'de engelli modelin KOTA HAVUZUNDAKİ kardeşleri de düşer (Claude+gpt-oss tek havuz:
    biri dolunca öteki boş SANILIP denenmesin)."""
    skip = set(skip)
    pools = {agy_pool(k.split("/", 1)[1].split("@", 1)[0].split("~", 1)[0]) for k in skip if k.startswith("agy/")}
    return [t for t in targets if t.mode not in skip and t.key not in skip
            and not (t.mode == "agy" and agy_pool(t.model) in pools)]


def next_review(pool: Any, history: Any, targets: Sequence[ReviewTarget], now: float,
                busy_projects: Sequence[str] = (), window: float = WINDOW_SECONDS,
                head_of: Optional[Callable[[str], str]] = None) -> Optional[Tuple[str, ReviewTarget]]:
    """Sıradaki (proje, hedef) ya da None. TEK proje: önce yarım kalan (bazı çiftleri taze, bazısı değil), sonra hiç
    çifti olmayan, sonra en eskisi (en yeni bitişi en eski olan). Tamam projeler, `busy_projects` ve çalışan çiftler
    atlanır; `head_of(proje)` (git HEAD, "" = bilinmiyor) verilirse pencere dolsa da `done` çiftin kayıtlı `head`i güncel
    HEAD'e EŞİTSE taze sayılır (değişmeyen koda yeniden review yok); projede taze koşusu olmayan model ailesinin
    (`model_family`) hedefi aynı projenin diğer hedeflerinden önce seçilir; `max_attempts(mod)`i (Evren 1, diğerleri `MAX_ATTEMPTS`) dolduran error/model_fallback/partial çifti `window` dolana dek denenmez."""
    targets = _blocked_targets(targets, blocked_modes(history, now))   # kotası biten mod / model / agy havuzu sıfırlanana dek denenmez
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

        covered = {model_family(t) for t, r in zip(targets, recs) if _fresh_or_same(r)}
        pick = None
        for t, r in zip(targets, recs):
            if _fresh_or_same(r):
                continue
            if (isinstance(r, dict) and r.get("status") in ("error", "model_fallback", "partial")
                    and int(_num(r.get("attempts"))) >= max_attempts(t.mode) and counts_as_attempt(r)
                    and now - _num(r.get("started_at")) < window):
                continue
            if model_family(t) not in covered:   # her model ailesinden en az bir koşu: henüz kapsanmamış aile önce
                pick = t
                break
            if pick is None:
                pick = t
        if pick is None:
            continue
        nfresh = sum(1 for r in recs if _fresh_or_same(r))
        known = [_num(r.get("finished_at") or r.get("started_at")) for r in recs if isinstance(r, dict)]
        if nfresh:
            cands.append((0, -nfresh, proj, pick))     # yarım: en çok tamamlanmış olan önce
        elif not known:
            cands.append((1, 0.0, proj, pick))
        else:
            cands.append((2, max(known), proj, pick))
    if not cands:
        return None
    focus = pool_focus(pool)       # ODAK projeler (panel ★): işi olan ODAK proje her zaman diğerlerinin önünde
    cands.sort(key=lambda c: (0 if c[2] in focus else 1, c[0], c[1], c[2]))
    return cands[0][2], cands[0][3]


_OPEN_REVIEW_LINE_RE = re.compile(r"^\s*- \[ \] \(review ", re.M)
BACKLOG_FILES = ("TODO.md", "RTODO.md")


def open_review_lines(text: str) -> int:
    """SAF. Metindeki açık (düzeltilmemiş) review satırı sayısı: `- [ ] (review ...` (export_lines biçimi)."""
    return len(_OPEN_REVIEW_LINE_RE.findall(text or ""))


def backlogged_projects(pool: Any, count_of: Callable[[str], int], limit: int) -> List[str]:
    """SAF. Açık review satırı `limit`e ulaşmış etkin projeler (L1, 10 Kas 2026: 3.521 bulgu, TODO'ya aktarılanların ~%35'i
    düzeltildi; yeni koşu ancak birikim erirken). `limit` <= 0 = kapalı; ★ odak projeler muaf (sahip açıkça istedi)."""
    if limit <= 0:
        return []
    focus = set(pool_focus(pool))
    out = []
    for proj in pool_enabled(pool):
        if proj in focus:
            continue
        try:
            n = int(count_of(proj))
        except Exception:
            continue
        if n >= limit:
            out.append(proj)
    return out


def pool_focus(pool: Any) -> List[str]:
    """Havuzda `focus=True` işaretli, etkin projeler (sıralı)."""
    pr = pool.get("projects") if isinstance(pool, dict) else None
    if not isinstance(pr, dict):
        return []
    return sorted(n for n, e in pr.items() if isinstance(e, dict) and e.get("focus") and e.get("enabled") and not e.get("removed_at"))


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

LENSES = ("dry",)     # "" = genel kod incelemesi (varsayılan)

_LENS_DEFECTS_RE = {
    "en": re.compile(r"Find real defects:.*?before reporting it\.\n", re.S),
    "tr": re.compile(r"Gerçek kusurları bul:.*?raporlamadan önce kodda doğrula\.\n", re.S),
}
_LENS_TEXT = {
    ("dry", "en"): (
        "Review ONLY for DRY violations: repeated code or text blocks, copy-pasted sections, near-identical functions, and "
        "the same knowledge (constants, lists, rules, messages, schemas) kept in more than one place so they can drift apart. "
        "Ignore other kinds of defects and style. Verify both copies in the code before reporting.\n"),
    ("dry", "tr"): (
        "YALNIZ DRY ihlallerini incele: tekrar eden kod ya da metin blokları, kopyalanmış bölümler, neredeyse aynı "
        "fonksiyonlar ve aynı bilginin (sabit, liste, kural, mesaj, şema) birden çok yerde tutulup birbirinden "
        "ayrışabilmesi. Diğer kusur türlerini ve biçimi atla. Raporlamadan önce iki kopyayı da kodda doğrula.\n"),
}
_LENS_FORMAT = {
    "en": (" For this review the body MUST also name the second (repeated) location as `Also at: <path:line>` and give "
           "a consolidation proposal (where the single source of truth should live and what the callers become)."),
    "tr": (" Bu incelemede gövde ayrıca tekrar eden ikinci yeri `Ayrıca: <yol:satır>` olarak vermeli ve bir birleştirme "
           "önerisi içermeli (tek doğru kaynağın nerede duracağı, çağıranların ne olacağı)."),
}


def build_review_prompt(proj: str, cwd: str, lang: str = "tr", lens: str = "") -> str:
    """Salt-okunur kod/belge incelemesi istemi; `lens` boşsa genel inceleme, `dry` ise tekrar/kopya mercesi (bulgu başlık
    biçimi AYNI). Bulgu biçimi `parse_findings` ile eşleşir: `## R-<n> | P1|P2|P3 | dosya:satır | başlık` + gövde."""
    base = _build_general_prompt(proj, cwd, lang)
    if not lens:
        return base
    lg = "en" if lang == "en" else "tr"
    text = _LENS_TEXT.get((lens, lg))
    if text is None:
        raise ValueError(f"unknown review lens: {lens}")
    out, n = _LENS_DEFECTS_RE[lg].subn(lambda _m: text, base, count=1)
    return (out if n else base + " " + text) + _LENS_FORMAT[lg]


def _build_general_prompt(proj: str, cwd: str, lang: str = "tr") -> str:
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
                "Read files whole, in large pages (read_file returns up to 1000 lines a call; read_files several "
                "files at once), not in small windows.\n"
                "Before reporting a finding, read the whole function it is in and the code that calls or guards it; "
                "if a guard, comment or caller already handles the case, drop the finding.\n"
                "Report each finding as a heading line exactly like\n"
                "## R-1 | P2 | path/to/file.py:123 | Short title\n"
                "(severity P1 = critical, P2 = important, P3 = minor; numbering R-1, R-2, ...) followed by a short "
                "body: what is wrong, why, how to reproduce or check, suggested fix, and a last line "
                "`Verified: <file:first-last line>` naming the lines you read to confirm it. "
                "No findings: write 'NO FINDINGS'.")
    return (f"\"{proj}\" projesi için bağımsız bir kod gözden geçiricisisin (çalışma dizini: {cwd}).\n"
            "Bu SALT OKUNUR bir incelemedir: hiçbir dosyayı oluşturma, değiştirme, taşıma ya da silme; kurulum "
            "çalıştırma; commit/push yapma; ağa çıkma.\n"
            f"Şu yolları ASLA açma, alıntılama, özetleme (parola içerebilir): {forb}. Bir gizli değer görürsen "
            "tekrarlama.\n"
            "`reviews/` dizininin altındaki hiçbir şeyi açma (önceki review raporları ve kayıtları): seni yanlı "
            "yapar ve maskelenmiş gizli değer içerebilir. Yalnız kodun kendisini değerlendir.\n"
            "Gerçek kusurları bul: doğruluk hataları, veri kaybı, güvenlik, yarış durumu, bozuk hata yönetimi, "
            "yanıltan eski belgeler. Biçim önerilerini atla. Her iddiayı raporlamadan önce kodda doğrula.\n"
            "Dosyaları küçük pencerelerle değil BÜYÜK parçalarla oku (read_file çağrı başına 1000 satıra kadar "
            "döndürür; read_files birden çok dosyayı tek çağrıda okur).\n"
            "Bir bulguyu yazmadan önce içinde olduğu fonksiyonu baştan sona ve onu çağıran ya da koruyan kodu oku; "
            "bir koruma, açıklama ya da çağıran durumu zaten ele alıyorsa bulguyu bırak.\n"
            "Her bulguyu tam şu biçimde bir başlık satırıyla ver:\n"
            "## R-1 | P2 | yol/dosya.py:123 | Kısa başlık\n"
            "(önem P1 = kritik, P2 = önemli, P3 = küçük; numaralama R-1, R-2, ...) ve altında kısa gövde: ne yanlış, "
            "neden, nasıl doğrulanır, önerilen düzeltme ve son satırda doğrulamak için okuduğun satırlar: "
            "`Doğrulama: <dosya:ilk-son satır>`. Bulgu yoksa 'BULGU YOK' yaz.")


_FINDING_RE = re.compile(r"^#{2,4}\s*(R-\d+)\s*\|\s*(P[123])\s*\|\s*(.*?)\s*\|\s*(.+?)\s*$")


def _fence_step(open_mark: str, line: str) -> Tuple[str, bool]:
    """Kod çiti durumu: (yeni açık çit işareti, bu satır çit satırı mı). Açık çit YALNIZ kendi türüyle kapanır
    (``` içindeki ~~~ satırı çiti kapatmaz, tersi de)."""
    s = line.lstrip()
    mark = "```" if s.startswith("```") else ("~~~" if s.startswith("~~~") else "")
    if not mark:
        return open_mark, False
    if not open_mark:
        return mark, True
    return ("" if mark == open_mark else open_mark), True


def parse_findings(md: str) -> List[Dict[str, str]]:
    """Review çıktısından bulgular: `[{ref, severity, where, title, body}]` (kod çitleri içindeki başlıklar sayılmaz;
    aynı `ref` ikinci kez gelirse atlanır). Biçime uymayan metin yok sayılır."""
    out: List[Dict[str, str]] = []
    cur: Optional[Dict[str, Any]] = None
    fmark = ""
    seen: Set[str] = set()
    for line in str(md or "").splitlines():
        fmark, is_fence = _fence_step(fmark, line)
        fence = bool(fmark)
        if is_fence:
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
_DSN_RE = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s:/@\"']+:)([^\s\"']{3,})(@)(?=[^\s@/\"']+)", re.I)   # büyük harfli şema; parola `@` / `/` içerebilir (açgözlü: boşluksuz parçada SON `@`)

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


LEARNED_MIN = 4             # öğrenilmiş (DSN) parolası bundan kısaysa düz metinde maskelenmez (metni bozar); DSN'in kendisi yine maskelenir
LEARNED_PLAIN_MIN = 8       # bundan uzunsa her yerde düz değiştirilir; arası yalnız sözcük sınırında


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
        if not s:
            continue
        if len(s) >= LEARNED_PLAIN_MIN:
            out = out.replace(s, "[REDACTED]")
        elif len(s) >= LEARNED_MIN:     # kısa parola: yalnız kendi başına geçen sözcük (yol/tanımlayıcı içinde geçince metin bozulmasın)
            out = re.sub(r"(?<![A-Za-z0-9_./-])" + re.escape(s) + r"(?![A-Za-z0-9_./-])", "[REDACTED]", out)
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
    uyuşuyor mu (büyük/küçük harf ve ayraç farkı yok sayılır; tam eşitlik gerekir)? Etiket yoksa
    `(False, "")`. Dönüş: (uyuştu, görülen etiket) — sessiz model düşüşünü (`model_fallback`) yakalamak için."""
    labels = [m.group(1).strip("\"'") for m in _LABEL_RE.finditer(str(log_text or ""))]
    if not labels:
        return False, ""
    seen = labels[-1]
    a, b = _norm_label(seen), _norm_label(model)
    return bool(a and b and a == b), seen     # alt dize YOK: gemini-3-pro, gemini-3-pro-high'ı kabul etmesin


# ── yollar ────────────────────────────────────────────────────────────────────

def effort_for(cfg: Any, mode: str, target: Optional["ReviewTarget"] = None) -> str:
    """Yol katmanı için effort adı: claude/codex/copilot `review_<mode>_effort`, diğerleri (agy: kademe model adında, evren:
    bayrak yok) `default`. Hedefte `model@effort` ile effort verilmişse o geçer."""
    v = getattr(target, "effort", "") if target is not None else ""
    if not str(v or "").strip():
        v = getattr(cfg, f"review_{mode}_effort", "") if mode in ("claude", "codex", "copilot") else ""
    return slug_model(v) if str(v or "").strip() else "default"


def review_path(root: str, proj: str, t: ReviewTarget, ts: Any, effort: str = "", lens: str = "") -> str:
    """`<root>/<proje>/<mode>/<altmodel>[/<effort>]/<yyyyMMddHHmmss>/<yyyyMMddHHmmss>.md`; `ts` epoch (yerel saat) ya da
    hazır 14 haneli metin. Her koşunun dosyaları (rapor, `.io.jsonl`, `.model.md`, `.usage.jsonl`) kendi `<ts>/` klasöründe
    toplanır; hepsi `<ts>` önekini korur, bu yüzden `.md` -> yan dosya türetmeleri aynen çalışır. `root` genelde
    `StewardPaths.reviews`. Proje adı yol güvenli hale getirilir. `effort` boşsa effort katmanı yok. (2026-10-24'ten önceki
    koşular eski düz düzende `<ts>.md`; kayıtlı yollar olduğu gibi okunur.)"""
    stamp = ts if isinstance(ts, str) and re.fullmatch(r"\d{14}", ts) else time.strftime("%Y%m%d%H%M%S", time.localtime(float(ts)))
    parts = [root, slug_model(proj), t.mode, t.slug] + ([slug_model(effort)] if effort else []) \
        + ([slug_model(lens or t.lens)] if (lens or t.lens) else [])      # lens son katman: .../<effort>/dry/<ts>/<ts>.md
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


FINDING_FILE_RE = re.compile(r"\.f(\d{2})\.md$")


def finding_path(md: str, n: int) -> str:
    """Modelin bulduğu anda yazdığı TEK bulgu dosyası: raporun yanında `<ts>.fNN.md` (2026-11-04: üç uzun Evren
    koşusu ~3 saat sonra akış kopmasıyla öldü, bulgular sonda yazılacağı için hepsi gitti)."""
    return (md[:-3] if md.endswith(".md") else md) + f".f{n:02d}.md"


def finding_paths(md: str) -> List[str]:
    """Raporun yanındaki `<ts>.fNN.md` bulgu dosyaları, sıra numarasına göre (symlink'ler atlanır)."""
    stem = os.path.basename(md[:-3] if md.endswith(".md") else md)
    d = os.path.dirname(md)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out = [os.path.join(d, n) for n in names if n.startswith(stem + ".") and FINDING_FILE_RE.search(n)]
    return sorted(p for p in out if not os.path.islink(p))


def draft_prompt_suffix(draft: str, lang: str = "tr") -> str:
    """Evren istemine eklenen: her bulguyu BULDUĞU ANDA ayrı create-only dosyaya (`<ts>.fNN.md`), sonda tam raporu
    `draft` yoluna TEK SEFERDE yaz. Koşu yarıda kopsa da yazılmış bulgular kalır (`finding_paths`)."""
    first = finding_path(draft[:-len(".model.md")] + ".md" if draft.endswith(".model.md") else draft, 1)
    pattern = first[:-len("01.md")] + "NN.md"
    if lang == "en":
        return (f"\nWrite each finding THE MOMENT you have verified it, with write_file, to its own new file {pattern} "
                f"(NN = 01, 02, ... in order; the first is {first} ; one finding per file, heading line included). Do not "
                "keep findings for the end: a run can be cut off at any time. When you are done, write the whole report "
                f"once to the absolute path {draft} (create-only: it fails if the file exists, so write it exactly "
                "once). You may not write anywhere else. Then also reply with the report.")
    return (f"\nHer bulguyu DOĞRULADIĞIN ANDA write_file ile kendi yeni dosyasına yaz: {pattern} (NN = 01, 02, ... "
            f"sırayla; ilki {first} ; her dosyada tek bulgu, başlık satırı dahil). Bulguları sona saklama: koşu her an "
            f"kesilebilir. Bitince tam raporu {draft} mutlak yoluna TEK SEFERDE yaz (yalnız yeni dosya: varsa hata "
            "verir, o yüzden tam bir kez yaz). Başka hiçbir yere yazamazsın. Sonra raporu yanıt olarak da ver.")


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


_MODEL_TEXT_KEYS = ("partial_turn", "answer", "result", "text", "messages")


def limit_scan_texts(out: Any, err: Any, jerr: Any, err_has_model_text: bool = False) -> Tuple[str, ...]:
    """Kota/limit taramasına girecek metinler: SAĞLAYICI hata kanalları (stderr, ayrıştırılmış JSON hatası) ve stdout'un
    yalnız sağlayıcıya ait kısmı. Modelin kendi metni (ucli JSON'daki `partial_turn`/`answer`, uzun stdout) HARİÇ:
    kodu inceleyen model `RESOURCE_EXHAUSTED ... Resets in 107h49m47s` yorumunu alıntılayınca zaman aşımı koşusu
    günlerce engellenmişti (uzops/evren/mimo-v2.6-pro 2026-11-04). Stdout: JSON sözlükse model alanları atılır, JSON değilse
    yalnız KISA bir mesajsa (`is_short_banner`) taranır. `err_has_model_text` (ucli modları): stderr modelin canlı
    akışını da taşır (alıntı orada da yanlış pozitif verdi), bu yüzden stdout gibi yalnız KISA mesajsa taranır."""
    e = str(err or "")
    parts = [e if (not err_has_model_text or is_short_banner(e)) else "", str(jerr or "")]
    o = str(out or "")
    try:
        val = json.loads(o)
    except ValueError:
        val = None
    if isinstance(val, dict):
        parts.append(json.dumps({k: v for k, v in val.items() if k not in _MODEL_TEXT_KEYS}, ensure_ascii=False))
    elif is_short_banner(o):
        parts.append(o)
    return tuple(parts)


def is_short_banner(text: Any) -> bool:
    """Çıkış kodu 0 ama stdout'ta rapor yerine KISA bir sağlayıcı mesajı (ör. copilot kota mesajı) var mı? Bulgu başlığı
    (`## R-`) ya da uzun metin gerçek rapordur: onda "quota" sözü geçmesi (kodu inceleyen rapor) limit sayılmaz."""
    t = str(text or "").strip()
    return 0 < len(t) < BANNER_MAX_CHARS and "## R-" not in t


# Model başına kota (agy: `RESOURCE_EXHAUSTED (code 429): Individual quota reached ... Resets in 107h49m47s.`): yalnız o
# mod/model sıfırlanana dek planlayıcıdan çıkar (günlük hesap geneli kota ise TÜM mod: `is_daily_limit`).
_QUOTA_RE = re.compile(r"RESOURCE_EXHAUSTED|Individual quota reached|quota reached|hit your usage limit", re.I)
# codex (ChatGPT hesabı): "You've hit your usage limit. ... or try again at Nov 20th, 2026 6:37 PM." (hesap geneli: TÜM codex modelleri).
# 7 Kas: bu mesaj tanınmadığı için 24 saatte 12 koşu aynı hatayla boşa gitti (codex/gpt-6-luna 0/12).
_USAGE_LIMIT_RE = re.compile(r"hit your usage limit", re.I)
_TRY_AT_RE = re.compile(r"try again at\s+([A-Za-z]{3})[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*([AP]M)", re.I)
_RESET_RE = re.compile(r"resets?\s+in\s+((?:\d+\s*[dhms]\s*)+)", re.I)
_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
QUOTA_FALLBACK_SECONDS = 1800.0      # kota hatası ama sıfırlanma süresi okunamadı: yarım saat sonra yeniden dene
QUOTA_MAX_SECONDS = 14 * 86400.0     # saçma uzun süreyi kırp


def is_quota_exhausted(*texts: Any) -> bool:
    return any(_QUOTA_RE.search(str(t or "")) for t in texts)


def is_usage_limit(*texts: Any) -> bool:
    """Hesap geneli kullanım sınırı (codex): kota bloğu modeli değil TÜM modu durdurur."""
    return any(_USAGE_LIMIT_RE.search(str(t or "")) for t in texts)


def reset_at(*texts: Any) -> Optional[float]:
    """"try again at Nov 20th, 2026 6:37 PM" -> yerel saat epoch; okunamazsa None. İlk eşleşen metin kazanır."""
    for t in texts:
        m = _TRY_AT_RE.search(str(t or ""))
        if m:
            try:
                return time.mktime(time.strptime(f"{m.group(1).title()} {int(m.group(2))} {m.group(3)} {int(m.group(4))}:{m.group(5)} {m.group(6).upper()}",
                                                 "%b %d %Y %I:%M %p"))
            except ValueError:
                continue
    return None


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
    at = reset_at(*texts)
    if at is not None and at > now:
        return min(at, now + QUOTA_MAX_SECONDS)
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
        a, b = _num(rec.get("started_at")), _num(rec.get("finished_at"))
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
                (_num(fields.get("started_at")) or time.time()) - _num(rec.get("started_at")) >= WINDOW_SECONDS)   # started_at verilmediyse şimdi
            fields["attempts"] = (0 if stale else int(_num(rec.get("attempts")))) + 1
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


def _fold(v: Any) -> str:
    """Büyük/küçük harf + aksan katlama (Türkçe İ/I/ı/i dahil): `İşlem` == `işlem` == `ISLEM`. NFKD sonrası birleşik işaretler atılır."""
    t = unicodedata.normalize("NFKD", str(v or "").replace("İ", "I").replace("ı", "i"))
    return "".join(c for c in t if not unicodedata.combining(c)).casefold()


def finding_key(proj: str, where: Any, title: Any) -> str:
    """Bulgu kimliği (TBD#137c): (proje, dosya, normalize başlık) hash'i. Dosya = `where`in `:satır` öncesi (harf duyarlı); başlık küçük harf,
    harf/rakam dışı atılır: aynı hata farklı koşuda/satırda yeniden bulunsa aynı anahtar."""
    fil = re.split(r"[:#]", str(where or "").strip().strip("`"), maxsplit=1)[0].strip().strip("`")
    fil = re.sub(r"^(\./|file://)", "", fil)
    ttl = re.sub(r"[^0-9a-z]+", " ", _fold(title)).strip()
    return hashlib.sha1(f"{proj}\x00{fil}\x00{ttl}".encode("utf-8")).hexdigest()[:16]


def _canon_rank(rec: Dict[str, Any]) -> Tuple[int, float]:
    """Tekilleştirmede kanonik kayıt sırası (küçük = tercih): doğrulanmış/onaylı/dışa aktarılmış < diğerleri <
    refuted/rejected; eşitlikte en eski `created_at` (sahip kararı TBD#R3)."""
    st = rec.get("state")
    tier = 0 if st in ("verified", "approved", "exported") else 2 if st in ("refuted", "rejected") else 1
    try:
        ts = float(rec.get("created_at") or 0)
    except (TypeError, ValueError):
        ts = 0.0
    return (tier, ts)


def add_findings(paths: Any, proj: str, review_file: str, parsed: Sequence[Dict[str, str]]) -> List[str]:
    """Ayrıştırılmış bulguları `findings.json`a `state=new` ile ekler (kilit altında); eklenen fid'ler döner.
    fid = `<proje>:<review dosyası temel adı sıkıştırılmış>:<ref>`: aynı dosya iki kez işlenirse çoğalmaz.
    Başka bir review dosyasından aynı `finding_key`li bulgu zaten varsa (reddedilmiş dahil) yenisi `state=dup`,
    `dup_of=<eski fid>` yazılır: doğrulama/onay/dışa aktarım hattına girmez, dönen listeye de girmez. AYNI raporun
    bulguları (R-1, R-2…) birbirine karşı ASLA tekilleşmez (aynı başlık, ayrı satır = ayrı bulgu); yanlış `dup` için
    `decide_finding(..., "undup")` bulguyu `new`e döndürür."""
    p = sw._pp(paths)
    root = p.reviews.rstrip(os.sep) + os.sep       # ayırıcılı önek: `/x/reviews2/..` `/x/reviews` altında sayılmaz
    base = re.sub(r"[^A-Za-z0-9]+", "", os.path.relpath(review_file, p.reviews) if review_file.startswith(root) else review_file)
    added: List[str] = []
    with sw.steward_lock(p):
        data = load_findings(p)
        by_key: Dict[str, str] = {}
        for ofid, orec in data.items():
            if (isinstance(orec, dict) and orec.get("state") != "dup" and orec.get("project") == proj
                    and orec.get("review_file") != review_file):
                okey = orec.get("key") or finding_key(proj, orec.get("where"), orec.get("title"))
                cur = data.get(by_key.get(okey, ""))
                # kanonik kayıt dict sırasına değil (öncelik, yaş) sırasına bağlı (TBD#R3): doğrulanmış/onaylı/dışa aktarılmış
                # > diğer durumlar > refuted/rejected; eşitlikte en eski kayıt (created_at) kanonik kalır.
                if okey not in by_key or not isinstance(cur, dict) or _canon_rank(orec) < _canon_rank(cur):
                    by_key[okey] = ofid
        changed = False
        for f in parsed:
            fid = f"{slug_model(proj)}:{base}:{f['ref']}"
            if fid in data:
                if data[fid].get("review_file") == review_file:
                    continue                                    # aynı rapor ikinci kez işleniyor: çoğalmaz
                fid += "~" + hashlib.sha1(review_file.encode("utf-8")).hexdigest()[:6]    # ad sıkıştırma çakışması: ikinci raporun bulguları düşmesin
                if fid in data:
                    continue
            key = finding_key(proj, f["where"], f["title"])
            rec = {"project": proj, "review_file": review_file, "ref": f["ref"], "severity": f["severity"],
                   "title": f["title"], "where": f["where"], "body": f["body"], "state": "new", "verdict": "",
                   "verdict_at": None, "decided_by": "", "decided_at": None, "exported_to": "",
                   "created_at": time.time(), "key": key}
            if key in by_key:
                rec["state"], rec["dup_of"] = "dup", by_key[key]
                canon = data.get(by_key[key])
                if (isinstance(canon, dict) and canon.get("state") in ("new", "verify_sent", "unclear", "verified")
                        and str(f["severity"]) < str(canon.get("severity") or "P9")):
                    canon["severity"] = f["severity"]           # aynı bulgu sonradan daha ağır bulunduysa asıl kayıt yükselir (P1 < P2 < P3)
            else:
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
    fmark = ""
    for raw in str(text or "").splitlines():
        s = raw.strip()
        fmark, is_fence = _fence_step(fmark, s)
        fenced = bool(fmark)
        if is_fence:
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
            try:
                with open(os.path.join(dp, fn), encoding="utf-8", errors="replace") as f:
                    a["runs"] += 1                      # okunamayan dosya "koşu" sayılmaz
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


HEALTH_DAYS = 7
HEALTH_MIN_RUNS = 5
HEALTH_MAX_RATE = 0.25


def model_health(history: Any, now: float, days: float = HEALTH_DAYS, min_runs: int = HEALTH_MIN_RUNS,
                 max_rate: float = HEALTH_MAX_RATE) -> List[Dict[str, Any]]:
    """Son `days` günde (mod/model) başına başarı oranı (sahip TBD#163 c). SAF. `limit` koşuları (kota/sağlayıcı sınırı, modelin
    kusuru değil) HİÇ sayılmaz; başarı = `done`/`partial` (rapor ya da kısmi bulgu bıraktı), `error` = başarısız. `candidate`:
    en az `min_runs` sayılan koşu VE oran <= `max_rate`. En kötü oran önce."""
    agg: Dict[str, Dict[str, Any]] = {}
    runs = history.get("runs") if isinstance(history, dict) else None
    cutoff = now - days * 86400
    for r in runs if isinstance(runs, list) else []:
        if not isinstance(r, dict) or "|" not in str(r.get("pair") or ""):
            continue
        if _num(r.get("at")) < cutoff or str(r.get("status")) == "limit":
            continue
        target = str(r["pair"]).split("|", 1)[1]
        a = agg.setdefault(target, {"target": target, "runs": 0, "ok": 0, "error": 0})
        a["runs"] += 1
        if str(r.get("status")) in ("done", "partial"):
            a["ok"] += 1
        else:
            a["error"] += 1
    out = []
    for a in agg.values():
        a["rate"] = round(a["ok"] / a["runs"], 3) if a["runs"] else 0.0
        a["candidate"] = a["runs"] >= min_runs and a["rate"] <= max_rate
        out.append(a)
    return sorted(out, key=lambda x: (x["rate"], -x["runs"], x["target"]))


def health_digest(rows: Sequence[Dict[str, Any]], excluded: Sequence[str] = (), days: float = HEALTH_DAYS, lang: str = "tr") -> str:
    """Haftalık özet metni: çıkarma ADAYLARI (onay sahipte) + zaten dışlananlar. Aday yoksa boş string."""
    cands = [r for r in rows if r.get("candidate") and r["target"] not in set(excluded)]
    if not cands:
        return ""
    head = (f"Reviewer: son {days:g} günde başarısız model/mod adayları (sahip onaylarsa havuzdan çıkar; `limit` koşuları sayılmaz):"
            if lang == "tr" else f"Reviewer: low-success model/mode candidates over the last {days:g} days (excluded on owner approval; `limit` runs not counted):")
    lines = [f"- {r['target']}: {r['ok']}/{r['runs']} başarılı (%{round(100 * r['rate'])})" for r in cands]
    tail = ("Çıkarmak için: `py/cops steward -s reviewer review exclude <mod/model>`" if lang == "tr"
            else "To exclude: `py/cops steward -s reviewer review exclude <mode/model>`")
    return "\n".join([head] + lines + [tail])


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
    """Sahibin bulgu kararı: approve (yalnız verified|unclear) | reject (dışa aktarılmamış ve kararsız bulgu) |
    undup (yanlışlıkla `dup` olmuş bulguyu `new`e döndürür, `dup_of` silinir)."""
    if action not in ("approve", "reject", "undup"):
        return {"ok": False, "error": "action must be approve, reject or undup"}
    p = sw._pp(paths)
    with sw.steward_lock(p):
        data = load_findings(p)
        rec = data.get(fid)
        if not isinstance(rec, dict):
            return {"ok": False, "error": f"unknown finding: {fid}"}
        st = rec.get("state")
        if action == "undup":
            if st != "dup":
                return {"ok": False, "error": f"cannot undup a finding in state {st!r} (allowed: dup)", "state": st}
            rec.pop("dup_of", None)
            rec.update(state="new", decided_by=by, decided_at=now)
            save_findings(p, data)
            return {"ok": True, "id": fid, "state": "new"}
        allowed = APPROVABLE_STATES if action == "approve" else REJECTABLE_STATES
        if st not in allowed:
            return {"ok": False, "error": f"cannot {action} a finding in state {st!r} (allowed: {', '.join(allowed)})",
                    "state": st}
        rec.update(state="approved" if action == "approve" else "rejected", decided_by=by, decided_at=now)
        save_findings(p, data)
    return {"ok": True, "id": fid, "state": rec["state"]}


EXPORT_HEADING = "## Review bulguları"

# RTODO/RTBD ayrımı (sahip, 2026-11-01: "gerekirse rtodo rtbd'ye"): bulgunun TÜRÜNE göre. Anahtar kelime ile TAHMİNİ: karar
# gerektiren (politika/tercih/seçenek/belirsiz davranış) bulgu RTBD'ye, düz hata RTODO'ya gider; şüphede RTODO.
_DECISION_RE = re.compile(
    r"\b(karar\w*|tercih\w*|seçenek\w*|politika\w*|sahip\w* karar|belirsiz\w*|trade-?off|design decision|should (?:we|it)|policy|ambiguous|undefined behaviou?r)",
    re.I)


def is_decision(row: Dict[str, Any]) -> bool:
    return bool(_DECISION_RE.search(f"{row.get('title') or ''} {str(row.get('body') or '')[:600]}"))

_BACKTICK_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`")
_WHERE_FILE_RE = re.compile(r"^\s*`?([^\s:`]+\.[A-Za-z0-9]+)")


_WHERE_MD_LINK_RE = re.compile(r"^\s*`?\[([^\]]+)\]\([^)]*\)`?")


def where_text(row: Dict[str, Any]) -> str:
    """`where` alanı; model `[yol:3](file:///...)` Markdown bağlantısı yazdıysa yalnız görünen `yol:3`."""
    where = str(row.get("where") or "")
    m = _WHERE_MD_LINK_RE.match(where)
    return m.group(1) if m else where


def _where_file(row: Dict[str, Any], cwd: str) -> str:
    m = _WHERE_FILE_RE.match(where_text(row))
    path = os.path.realpath(os.path.join(cwd, m.group(1))) if m else ""
    root = os.path.realpath(cwd)
    return path if path.startswith(root + os.sep) and os.path.isfile(path) else ""


def where_relpath(row: Dict[str, Any]) -> str:
    """Bulgunun `where` alanındaki dosya yolu (göreli); mutlak yol ya da `..` içeren yol "" (proje dışına çıkamaz)."""
    m = _WHERE_FILE_RE.match(where_text(row))
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
        if os.path.exists(os.path.join(cwd, ".git")):  # dizin ya da worktree'deki .git DOSYASI
            out = subprocess.run(["git", "-C", cwd, "log", "-1", "--format=%ct", "--", path], capture_output=True,
                                 text=True, timeout=10).stdout.strip()
            if out.isdigit():
                t = float(out)
        return t > os.path.getmtime(rf)
    except (OSError, subprocess.SubprocessError):
        return False


def _worktree_main(path: str) -> str:
    """`path` bir git worktree'siyse (`.git` DOSYASI `gitdir: <ana>/.git/worktrees/<ad>`) ana deponun kökü, değilse ""."""
    try:
        with open(os.path.join(path, ".git"), encoding="utf-8") as f:
            line = f.read(4096).strip()
    except OSError:     # dizin (.git klasörü) ya da yok
        return ""
    m = re.match(r"gitdir:\s*(.+)/\.git/worktrees/[^/]+$", line)
    return m.group(1) if m and os.path.isdir(os.path.join(m.group(1), ".git")) else ""


def row_in_repo(row: Dict[str, Any], root: str, cwd: str) -> Tuple[Dict[str, Any], str]:
    """Eskime denetimi için (satır, kök): hedef depo `cwd` değilse (combo) denetim bayat kopyaya değil GERÇEK depoya yapılır,
    `where`in depo öneki atılır (`claudeops/py/a.py:3` -> `py/a.py:3`)."""
    if not root or os.path.realpath(root) == os.path.realpath(cwd):
        return row, cwd
    where = where_text(row).strip().strip("`")
    return dict(row, where=where.split("/", 1)[1] if "/" in where else where), root


def export_root(row: Dict[str, Any], project: str, cwd: str, resolve: Callable[[str], str]) -> str:
    """Bulgunun TODO/TBD/RTODO/RTBD dosyasının yazılacağı depo kökü; "" = çözülemedi (YAZMA, uyar).
    `where` yolunun ilk parçası (`claudeops/...`, `unified-cli/...`) kayıtlı bir projeyse o projenin deposu (`resolve`);
    değilse cwd git deposuysa cwd. review-combo dizini git deposu DEĞİL ve refresh.sh sıfırlıyor: oraya yazmak bulguyu kaybettirir.
    Yol öneki yoksa (`x.py:1`) eski davranış: cwd."""
    rel = where_relpath(row)
    prefix = rel.split("/")[0] if "/" in rel else ""
    if prefix and prefix != project:
        d = resolve(prefix) or ""
        if d and os.path.isdir(d) and os.path.exists(os.path.join(d, ".git")):
            return d
        main = _worktree_main(os.path.join(cwd, prefix))    # combo alt dizini ana deponun worktree'si: depo adı proje adı olmayabilir (claudeops=cops, unified-cli=cli)
        if main:
            return main
    if os.path.exists(os.path.join(cwd, ".git")):
        return cwd
    if prefix and os.path.isdir(os.path.join(cwd, prefix)):
        return ""
    return cwd


def export_lines(rows: Sequence[Dict[str, Any]], reviews_root: str) -> List[str]:
    out = []
    for r in rows:
        src = str(r.get("review_file") or "")
        if reviews_root and src.startswith(reviews_root.rstrip("/") + "/"):
            src = os.path.relpath(src, reviews_root)
        if os.path.isabs(src):      # reviews_root dışında/boş: yerel mutlak yol (kullanıcı adı, dizin yapısı) UZAK TODO'ya sızmaz
            src = "/".join(src.rstrip("/").split("/")[-4:])
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
_HAS_FINDING_RE = re.compile(r"^#{2,4}\s*R-\d+\s*\|", re.M)       # `parse_findings` ile aynı başlık derinliği/boşluk toleransı


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


def usage_cost_usd(path: str, model: str, since_ms: float = 0.0, write_mult: float = 1.0) -> float:
    """Bir `.usage.jsonl` dosyasının $ maliyeti (istek başına ucli `usage`: girdi/çıktı/önbellek okuma/yazma). Tanınmayan
    alan 0 sayılır; hiç ayrıştırılamazsa dosya boyutundan bağımsız 0 döner (bütçe kapısı `anthropic_spent_usd` yedek tahmin ekler)."""
    # `model` boş: modeli kaydın kendisinden (task_start) izle (uzun ömürlü oturum günlüğü). `since_ms` > 0: yalnız o andan sonraki
    # istekler (günlük toplam). `write_mult`: önbellek YAZMA fiyatına çarpan (1h TTL yazma 2x = 5 dk 1,25x'in 1,6 katı).
    pi, po, pr, pw = anthropic_price(model or "opus-5-5")
    tot = 0.0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if not isinstance(rec, dict):
                        continue
                except ValueError:
                    continue
                if not model and rec.get("event") == "task_start" and rec.get("model"):
                    pi, po, pr, pw = anthropic_price(str(rec["model"]))
                    continue
                try:
                    t_rec = float(rec.get("t") or 0)
                except (TypeError, ValueError):
                    t_rec = 0.0
                if since_ms and t_rec < since_ms:
                    continue
                u = rec.get("usage")
                if not isinstance(u, dict):
                    continue
                def g(*names: str) -> float:
                    for n in names:
                        if isinstance(u.get(n), (int, float)):
                            return float(u[n])
                    return 0.0
                cr = g("cache_read_input_tokens", "cached_tokens", "cache_read_tokens")
                cw = g("cache_creation_input_tokens", "cache_write_tokens")
                # `input_tokens` (Anthropic yerli) önbelleği İÇERMEZ; ucli'nin normalleştirilmiş `prompt_tokens`ı önbellek okuma+yazmayı
                # İÇERİR (21534 = 21530 yazma + 4): bu yüzden o alandan çıkarılır, yoksa önbellekli token'lar bir de tam girdi fiyatından
                # sayılırdı (2 Kas 2026: günlük sayaç Console'dan ~5 kat şişkindi).
                if isinstance(u.get("input_tokens"), (int, float)):
                    inp = max(0.0, float(u["input_tokens"]) - (0 if "cache_read_input_tokens" in u else cr) - (0 if "cache_creation_input_tokens" in u else cw))
                else:
                    inp = max(0.0, g("prompt_tokens") - cr - cw)
                if "cached_tokens" in u and "cache_creation_input_tokens" not in u:
                    inp_price = pw      # ucli normalleştirilmiş sayaç: yazma ayrı raporlanmaz, önbellek istendiğinden yeni girdi yazma fiyatından sayılır (güvenli üst sınır)
                else:
                    inp_price = pi
                tot += (inp * inp_price + g("output_tokens", "completion_tokens") * po + cr * pr + cw * pw * write_mult) / 1e6
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
