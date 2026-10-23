"""Reviewer rolü: saf çekirdek (ağ/süreç/tmux YOK). Planlama kararları, istem üretimi, bulgu ayrıştırma ve
`review_pool.json` / `review_history.json` / `findings.json` depoları. Çalıştırıcılar (Evren/agy), tick döngüsü ve API
sonraki partilerde; burada yalnız test edilebilir mantık var (`card` modülü gibi: girdi -> karar).

Havuz `projects.json`'a YAZILMAZ (aynı adın iki kimlikte olması `ownership_index`te projeyi kimseye vermez): ayrı
`review_pool.json`. Çift = (proje, mod, alt model); anahtar `"<proje>|<mode>/<slug>"`."""
from __future__ import annotations
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import steward as sw

WINDOW_SECONDS = 30 * 86400         # bir çift bu sürede `done` ise "taze" (proje tamam ölçütü)
HISTORY_VERSION = 1
HISTORY_RUNS_MAX = 200
MAX_ATTEMPTS = 3                    # error/model_fallback çifti bu denemeden sonra pencere dolana dek bırakılır
MODE_MAX_ATTEMPTS = {"evren": 1}    # Evren: 20 dk zaman aşımı kota yakar, pencere başına en çok 1 deneme (sahip kararı 2026-10-24)


def max_attempts(mode: str) -> int:
    return MODE_MAX_ATTEMPTS.get(mode, MAX_ATTEMPTS)
MODES = ("agy", "evren", "claude", "codex")
PAIR_STATUSES = ("running", "done", "partial", "error", "model_fallback", "limit")
SEVERITIES = ("P1", "P2", "P3")
FINDING_STATES = ("new", "verify_sent", "verified", "refuted", "unclear", "approved", "rejected", "exported")

# Reviewer'a GÖSTERİLMEYECEK yollar (istemde yasak olarak sayılır; parola/anahtar içerebilir).
FORBIDDEN_PATHS = ("CLAUDE.md", ".env*", "*token*", "*credential*", "*.pem", "settings*.json")


# ── hedefler ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReviewTarget:
    mode: str      # agy | evren | claude | codex
    model: str     # sağlayıcıya verilen gerçek model kimliği
    slug: str      # yol/anahtar güvenli ad (`slug_model`)

    @property
    def key(self) -> str:
        return f"{self.mode}/{self.slug}"


def slug_model(model: str) -> str:
    """Yol güvenli ad: '/' ve diğer güvensiz karakterler '-' olur; `..`/boş kalmaz."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(model or "").strip()).strip("-.")
    s = re.sub(r"-{2,}", "-", s)
    return s or "model"


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
    `claude` (Anthropic, `claude -p`) ve `codex` (`codex exec`) katalogsuz ve KAPALI başlar: yalnız `review_claude_models`/`review_codex_models` doluysa o modeller."""
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
    for mode, attr in (("claude", "review_claude_models"), ("codex", "review_codex_models")):
        for m in _split_models(getattr(cfg, attr, "")):
            t = ReviewTarget(mode, m, slug_model(m))
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
    return f"{proj}|{t.mode}/{t.slug}"


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
                busy_projects: Sequence[str] = (), window: float = WINDOW_SECONDS) -> Optional[Tuple[str, ReviewTarget]]:
    """Sıradaki (proje, hedef) ya da None. TEK proje: önce yarım kalan (bazı çiftleri taze, bazısı değil), sonra hiç
    çifti olmayan, sonra en eskisi (en yeni bitişi en eski olan). Tamam projeler, `busy_projects` ve çalışan çiftler
    atlanır; `max_attempts(mod)`i (Evren 1, diğerleri `MAX_ATTEMPTS`) dolduran error/model_fallback çifti `window` dolana dek denenmez."""
    skip = set(blocked_modes(history, now))
    targets = [t for t in targets if t.mode not in skip]   # günlük kotası biten mod sıfırlanana dek denenmez
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
        pick = None
        for t, r in zip(targets, recs):
            if _fresh(r, now, window):
                continue
            if (isinstance(r, dict) and r.get("status") in ("error", "model_fallback")
                    and int(r.get("attempts") or 0) >= max_attempts(t.mode)
                    and now - float(r.get("started_at") or 0) < window):
                continue
            pick = t
            break
        if pick is None:
            continue
        nfresh = sum(1 for r in recs if _fresh(r, now, window))
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
    re.compile(r"(?i)\b((?:api[_-]?key|secret|token|passw(?:or)?d|authorization)\s*[:=]\s*)[\"']?[^\s\"',;]{8,}"),
)


def dsn_passwords(text: str) -> List[str]:
    """Metindeki `scheme://user:PAROLA@host` parolaları (IoLog öğrenip sonraki olaylarda düz metinde de maskeler)."""
    return [m.group(2) for m in _DSN_RE.finditer(str(text or "")) if m.group(2) != "[REDACTED]"]


def redact_secrets(text: str, learned: Sequence[str] = ()) -> str:
    """Bilinen gizli değer biçimlerini `[REDACTED]` yapar (review çıktısı diske/panele yazılmadan önce). `learned`:
    daha önce görülmüş sır değerleri (DSN parolası) düz metinde de maskelenir."""
    out = _DSN_RE.sub(lambda m: m.group(1) + "[REDACTED]" + m.group(3), str(text or ""))
    for s in sorted(learned, key=len, reverse=True):
        if s:
            out = out.replace(s, "[REDACTED]")
    for rx in _SECRET_RES:
        if rx.groups:
            out = rx.sub(lambda m: m.group(1) + "[REDACTED]", out)
        else:
            out = rx.sub("[REDACTED]", out)
    return out


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

def effort_for(cfg: Any, mode: str) -> str:
    """Yol katmanı için effort adı: claude/codex `review_<mode>_effort`, diğerleri (agy: kademe model adında, evren:
    bayrak yok) `default`."""
    v = getattr(cfg, f"review_{mode}_effort", "") if mode in ("claude", "codex") else ""
    return slug_model(v) if str(v or "").strip() else "default"


def review_path(root: str, proj: str, t: ReviewTarget, ts: Any, effort: str = "") -> str:
    """`<root>/<proje>/<mode>/<altmodel>[/<effort>]/<yyyyMMddHHmmss>.md`; `ts` epoch (yerel saat) ya da hazır 14 haneli
    metin. `root` genelde `StewardPaths.reviews`. Proje adı yol güvenli hale getirilir. `effort` boşsa eski düzen."""
    stamp = ts if isinstance(ts, str) and re.fullmatch(r"\d{14}", ts) else time.strftime("%Y%m%d%H%M%S", time.localtime(float(ts)))
    parts = [root, slug_model(proj), t.mode, t.slug] + ([slug_model(effort)] if effort else [])
    return os.path.join(*parts, stamp + ".md")


def draft_path(md: str) -> str:
    """Evren modelinin (`ucli --allow-create-dir`) kendi eliyle yazdığı rapor taslağı: raporun yanında `<ts>.model.md`.
    Zaman aşımında stdout boşsa kurtarma kaynağı olur."""
    return (md[:-3] if md.endswith(".md") else md) + ".model.md"


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

_LIMIT_RE = re.compile(r"daily_token_limit_exceeded|daily token limit", re.I)


def is_daily_limit(*texts: Any) -> bool:
    return any(_LIMIT_RE.search(str(t or "")) for t in texts)


def next_utc_midnight(now: float) -> float:
    return (int(now) // 86400 + 1) * 86400.0


def set_block(paths: Any, mode: str, until: float, reason: str = "") -> None:
    p = sw._pp(paths)
    with sw.steward_lock(p):
        hist = load_history(p)
        hist.setdefault("blocks", {})[mode] = {"until": float(until), "reason": reason}
        save_history(p, hist)


def blocked_modes(history: Any, now: float) -> List[str]:
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
            fields["attempts"] = int(rec.get("attempts") or 0) + 1
        rec.update(fields)
        hist["pairs"][key] = rec
        if fields.get("status") in ("done", "partial", "error", "model_fallback"):
            hist["runs"].append({"pair": key, "status": rec["status"], "at": rec.get("finished_at"), "file": rec.get("file")})
        save_history(p, hist)
    return rec


def load_findings(paths: Any) -> Dict[str, Any]:
    raw = sw._load_json(sw._pp(paths).findings, {})
    return raw if isinstance(raw, dict) else {}


def save_findings(paths: Any, findings: Dict[str, Any]) -> None:
    sw._save_json(sw._pp(paths).findings, findings)


def add_findings(paths: Any, proj: str, review_file: str, parsed: Sequence[Dict[str, str]]) -> List[str]:
    """Ayrıştırılmış bulguları `findings.json`a `state=new` ile ekler (kilit altında); eklenen fid'ler döner.
    fid = `<proje>:<review dosyası temel adı sıkıştırılmış>:<ref>`: aynı dosya iki kez işlenirse çoğalmaz."""
    p = sw._pp(paths)
    base = re.sub(r"[^A-Za-z0-9]+", "", os.path.relpath(review_file, p.reviews) if review_file.startswith(p.reviews) else review_file)
    added: List[str] = []
    with sw.steward_lock(p):
        data = load_findings(p)
        for f in parsed:
            fid = f"{slug_model(proj)}:{base}:{f['ref']}"
            if fid in data:
                continue
            data[fid] = {"project": proj, "review_file": review_file, "ref": f["ref"], "severity": f["severity"],
                         "title": f["title"], "where": f["where"], "body": f["body"], "state": "new", "verdict": "",
                         "verdict_at": None, "decided_by": "", "decided_at": None, "exported_to": "",
                         "created_at": time.time()}
            added.append(fid)
        if added:
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


def export_lines(rows: Sequence[Dict[str, Any]], reviews_root: str) -> List[str]:
    out = []
    for r in rows:
        src = str(r.get("review_file") or "")
        if reviews_root and src.startswith(reviews_root.rstrip("/") + "/"):
            src = os.path.relpath(src, reviews_root)
        title = " ".join(str(r.get("title") or "").split())
        out.append(f"- [ ] (review {r['id']}) [{r.get('severity') or '?'}] {r.get('where') or '?'}: {title} "
                   f"(kaynak: {src})")
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
