"""Değnekçi (steward) — projeleri sürekli gezip her birine sıradaki işi veren, kararları
kaydeden, gerektiğinde insana soran ve oturum ekonomisini (2000 satır / dolan context /
boş iş) yöneten zamanlayıcının SAF çekirdeği.

Bu modülde tmux/HTTP/thread YOK — sadece veri modeli, dosya deposu (~/.claude/claudeops/steward/),
kural motoru (`plan_tick`) ve prompt üreticileri. Canlı filoya dokunan motor
`commands/web_steward.py`'de (panelin içinde çalışır), değnekçinin "beyni" olan CLI oturumunun
kullandığı araçlar `commands/mcp_steward.py`'de, insan arayüzü `commands/steward.py`'de.
`orchestration.py`/`web_orch.py` ikilisiyle AYNI ayrım: çekirdek sıfır canlı CLI ile test edilir.

İki katman, bilerek ayrı:
- **Deterministik katman** (bu dosya + motor): ölçülebilir sinyallerle karar verir — scrollback
  `history_warn_at`'a yaklaştı → handover; READY FOR HANDOVER geldi → durdur+yeniden aç; proje
  uğrama sırası geldi ve slot boşsa → aç ve faza göre direktif ver; cevaplanan soru → oturuma ilet;
  yanıt metnindeki `STEWARD-*` işaretleri → soru/fikir/faz değişimi. LLM çağrısı YOK, ucuz, her tick.
- **Yargı katmanı** ("beyin"): "boş iş mi yapıyor", "sıradaki en doğru iş ne", "bu fikir proje
  olur mu", "insana sormalı mı" gibi kararlar bir CLI oturumuna (varsayılan ad `degnekci`) MCP
  araçlarıyla bırakılır. Beyin yalnız gerektiğinde (gözden geçirme maddesi birikince, kendisi
  boştayken, en az `tour_minutes` arayla) bir "tur" prompt'u alır — her tick değil.

Kullanıcı kararı (2026-10-19): "benim gibi düşünecek" kısmı koddan değil, `data/steward.md`
persona dosyasından gelir (Ayarlar'daki `steward_persona_text` ile ezilebilir, `routing.md`
deseni). Hiçbir şey kendiliğinden başlamaz: `steward.enabled` varsayılan KAPALI (projenin
"nothing ever starts automatically" ilkesi).
"""
from __future__ import annotations
import dataclasses
import hashlib
import json
import os
import re
import secrets
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .atomic_json import atomic_write_json
from .paths import CLAUDEOPS_DIR

STEWARD_DIR = os.path.join(CLAUDEOPS_DIR, "steward")
PROJECTS_JSON = os.path.join(STEWARD_DIR, "projects.json")
IDEAS_JSON = os.path.join(STEWARD_DIR, "ideas.json")
QUESTIONS_JSON = os.path.join(STEWARD_DIR, "questions.json")
STATE_JSON = os.path.join(STEWARD_DIR, "state.json")
LOG_JSONL = os.path.join(STEWARD_DIR, "log.jsonl")
WORKSPACE_DIR = os.path.join(STEWARD_DIR, "workspace")   # beynin cwd'si (CLAUDE.md = persona)
BUNDLED_PERSONA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "steward.md")
# Proje kartları: `STEWARD_DIR/cards/<ad>.json` — yol çağrı anında `STEWARD_DIR`'den türetilir (testler tek sabiti patch'ler).
CARD_DOCS = ("GOAL.md", "PLAN.md", "TODO.md", "TOBEDECIDED.md", "DONE.md")
CARD_DOC_CHARS = 1500            # kartın modele göstereceği her doküman başı
CARD_LIST_ITEMS = 8              # open_tbds / blockers / recent_done en çok bu kadar madde
CARD_TEXT_CHARS = 400            # kart alanlarının (goal/next_step/madde) üst sınırı

PHASES = ("idea", "planning", "planned", "paused", "done")
KINDS = ("book", "article", "software", "other")
ACTIVE_PHASES = ("planning", "planned")

# Oturum yanıtlarında aranan işaretler — protokol/parse sözleşmesi, yerelleştirilmez
# (`orchestration.VERDICT_MARKER` ile aynı ilke). Proje oturumları MCP olmadan da
# değnekçiye bu satırlarla konuşur.
MARK_END = "COPS-STEWARD-END"          # beynin tur yanıtının sonu
MARK_ASK = "STEWARD-ASK:"              # insana soru (satırın kalanı soru metni)
MARK_IDEA = "STEWARD-IDEA:"            # yeni fikir
MARK_BLOCKED = "STEWARD-BLOCKED:"      # takıldım (insana soru olarak düşer, önekli)
MARK_PLAN_READY = "STEWARD-PLAN-READY"  # planlama bitti → faz planned
MARK_DONE = "STEWARD-DONE"             # proje bitti → faz done, oturum durur
READY_FOR_HANDOVER = "READY FOR HANDOVER"

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_QUESTION_CHARS = 2000
_MAX_IDEA_CHARS = 2000
_MAX_NOTE_CHARS = 4000


# ── veri modeli ───────────────────────────────────────────────────────────────

@dataclass
class Project:
    name: str                       # roster/instance adı (değnekçi bu adla oturum açar)
    phase: str = "planned"          # PHASES
    kind: str = ""                  # KINDS ("" = bilinmiyor)
    goal: str = ""                  # amaç: kitap/makale/yazılım... tek paragraf
    priority: int = 3               # 1 (önce) .. 5 (sonra)
    cadence_minutes: int = 240      # en az bu sıklıkta uğra (0 = sadece elle)
    notes: str = ""                 # değnekçinin kendi notları (karar özeti, sonraki adım)
    model: str = ""                 # "" = faz varsayılanı / roster modeli
    effort: str = ""                # "" = faz varsayılanı
    last_visit: float = 0.0         # son direktifin zamanı (epoch)
    last_directive: str = ""        # son gönderilen direktif (kısaltılmış)
    visits: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class Idea:
    id: str
    text: str
    created_at: float
    status: str = "new"             # new | project | dropped | later
    project: str = ""               # projeye dönüştüyse adı
    source: str = ""                # hangi oturum/kim yazdı


@dataclass
class Question:
    id: str
    project: str                    # "" = genel (beynin kendi sorusu)
    text: str
    created_at: float
    status: str = "open"            # open | answered
    answer: str = ""
    answered_at: float = 0.0
    delivered_at: float = 0.0       # cevap ilgili oturuma iletildi
    source: str = ""                # soruyu kim açtı (oturum adı / brain / cli)


@dataclass
class SessionView:
    """Motorun bir tick'te kural motoruna verdiği, host/provider'dan bağımsız oturum görünümü.
    `commands/web_steward.py` bunu `/api/status` satırı + provider okumalarından üretir."""
    name: str
    running: bool
    cwd: str = ""
    cli: str = "claude"
    blueprint: Optional[str] = None     # instance ise blueprint adı (proje = blueprint ya da ad)
    busy: Optional[bool] = None
    history_size: Optional[int] = None
    needs_ho: Optional[bool] = None
    tmux: bool = False
    last_assistant: str = ""            # son asistan metni (işaret taraması için)
    last_activity: float = 0.0          # son model isteği/aktivite (epoch, 0 = bilinmiyor)
    started_at: float = 0.0             # sürecin başlangıcı (epoch)
    stuck: bool = False

    @property
    def project(self) -> str:
        return self.blueprint or self.name


@dataclass
class Action:
    kind: str       # handover | respawn | start | stop | directive | deliver_answer | ask_user | idea
                    # | set_phase | tour
    name: str = ""  # oturum/proje adı ("" = genel)
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    """`settings.steward_config()`'un döndürdüğü, tip-güvenli ayarlar (varsayılanlar burada tek yerde)."""
    enabled: bool = False
    tick_seconds: int = 120
    tour_minutes: int = 15
    max_active: int = 4
    max_starts_per_tick: int = 1
    idle_minutes: int = 10
    review_minutes: int = 90
    stop_idle_minutes: int = 45
    ho_grace_minutes: int = 15
    history_warn_at: int = 1900
    brain_cli: str = "claude"
    brain_model: str = ""
    brain_effort: str = "high"
    brain_name: str = "degnekci"
    planning_model: str = ""
    planning_effort: str = "high"
    planned_model: str = ""
    planned_effort: str = ""
    lang: str = "tr"
    card_refresh: bool = True        # tick'te proje kartlarını (eskiyen/değişen) yenile
    card_cli: str = "claude"         # kart özetini üreten CLI (providers.oneshot)
    card_model: str = ""             # "" = card_cli'nin model_choices'inde "haiku" geçen, yoksa varsayılan model
    card_max_age_hours: int = 24     # kart bundan eskiyse yenile (0 = yaşa bakma)
    cards_per_tick: int = 1          # bir tick'te en çok kaç kart yenilenir (0 = hiç)


def _now() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"


def valid_name(name: str) -> bool:
    return bool(name) and bool(_NAME_RE.match(name)) and len(name) <= 48


# ── depo ──────────────────────────────────────────────────────────────────────

def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _save_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write_json(path, obj, mode=0o600)


def _from_dict(cls, d: Dict[str, Any]):
    names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in names})


def load_projects() -> Dict[str, Project]:
    raw = _load_json(PROJECTS_JSON, {})
    out: Dict[str, Project] = {}
    if isinstance(raw, dict):
        for name, d in raw.items():
            if isinstance(d, dict) and valid_name(str(name)):
                d = dict(d)
                d["name"] = str(name)
                p = _from_dict(Project, d)
                if p.phase not in PHASES:
                    p.phase = "planned"
                out[p.name] = p
    return out


def save_projects(projects: Dict[str, Project]) -> None:
    _save_json(PROJECTS_JSON, {n: dataclasses.asdict(p) for n, p in projects.items()})


def upsert_project(name: str, **fields: Any) -> Project:
    """Alan bazlı güncelle (None/verilmeyen alanlar korunur). Geçersiz faz/tür/priority yok sayılır."""
    if not valid_name(name):
        raise ValueError(f"invalid project name: {name!r}")
    projects = load_projects()
    p = projects.get(name) or Project(name=name, created_at=_now())
    for k, v in fields.items():
        if v is None or not hasattr(p, k) or k in ("name", "created_at"):
            continue
        if k == "phase" and v not in PHASES:
            continue
        if k == "kind" and v not in KINDS and v != "":
            continue
        if k in ("priority", "cadence_minutes", "visits"):
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
            if k == "priority":
                v = min(5, max(1, v))
            if k == "cadence_minutes":
                v = max(0, v)
        if k == "notes":
            v = str(v)[:_MAX_NOTE_CHARS]
        setattr(p, k, v)
    p.updated_at = _now()
    projects[name] = p
    save_projects(projects)
    return p


def remove_project(name: str) -> bool:
    projects = load_projects()
    if name not in projects:
        return False
    del projects[name]
    save_projects(projects)
    return True


def load_ideas() -> List[Idea]:
    raw = _load_json(IDEAS_JSON, [])
    return [_from_dict(Idea, d) for d in raw if isinstance(d, dict) and d.get("id")] if isinstance(raw, list) else []


def save_ideas(ideas: List[Idea]) -> None:
    _save_json(IDEAS_JSON, [dataclasses.asdict(i) for i in ideas])


def add_idea(text: str, source: str = "") -> Idea:
    text = str(text).strip()[:_MAX_IDEA_CHARS]
    if not text:
        raise ValueError("empty idea")
    ideas = load_ideas()
    idea = Idea(id=_new_id("i"), text=text, created_at=_now(), source=source)
    ideas.append(idea)
    save_ideas(ideas)
    return idea


def update_idea(idea_id: str, status: Optional[str] = None, project: Optional[str] = None) -> Optional[Idea]:
    ideas = load_ideas()
    for i in ideas:
        if i.id == idea_id:
            if status in ("new", "project", "dropped", "later"):
                i.status = status
            if project is not None:
                i.project = str(project)
            save_ideas(ideas)
            return i
    return None


def load_questions() -> List[Question]:
    raw = _load_json(QUESTIONS_JSON, [])
    return [_from_dict(Question, d) for d in raw if isinstance(d, dict) and d.get("id")] if isinstance(raw, list) else []


def save_questions(questions: List[Question]) -> None:
    _save_json(QUESTIONS_JSON, [dataclasses.asdict(q) for q in questions])


def add_question(project: str, text: str, source: str = "") -> Question:
    text = str(text).strip()[:_MAX_QUESTION_CHARS]
    if not text:
        raise ValueError("empty question")
    questions = load_questions()
    # Aynı projeden AYNI metinle açık bir soru varsa ikinci kez açma (işaret taraması her
    # tick aynı yanıtı görebilir; motor `seen` ile de korur ama depo kendi başına da dayanıklı olsun).
    for q in questions:
        if q.status == "open" and q.project == project and q.text == text:
            return q
    q = Question(id=_new_id("q"), project=project, text=text, created_at=_now(), source=source)
    questions.append(q)
    save_questions(questions)
    return q


def answer_question(question_id: str, answer: str) -> Optional[Question]:
    answer = str(answer).strip()
    if not answer:
        raise ValueError("empty answer")
    questions = load_questions()
    for q in questions:
        if q.id == question_id:
            q.answer = answer[:_MAX_QUESTION_CHARS]
            q.status = "answered"
            q.answered_at = _now()
            q.delivered_at = 0.0
            save_questions(questions)
            return q
    return None


def mark_delivered(question_id: str) -> None:
    questions = load_questions()
    for q in questions:
        if q.id == question_id:
            q.delivered_at = _now()
    save_questions(questions)


def open_questions(questions: Optional[List[Question]] = None) -> List[Question]:
    return [q for q in (questions if questions is not None else load_questions()) if q.status == "open"]


def undelivered_answers(questions: Optional[List[Question]] = None) -> List[Question]:
    return [q for q in (questions if questions is not None else load_questions())
            if q.status == "answered" and not q.delivered_at]


def load_state() -> Dict[str, Any]:
    st = _load_json(STATE_JSON, {})
    return st if isinstance(st, dict) else {}


def save_state(state: Dict[str, Any]) -> None:
    _save_json(STATE_JSON, state)


def log_event(event: str, **data: Any) -> None:
    """Append-only JSONL — `diaglog.diag_log` ile aynı best-effort disiplin."""
    try:
        os.makedirs(STEWARD_DIR, exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **data}
        with open(LOG_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def tail_log(n: int = 50) -> List[Dict[str, Any]]:
    try:
        with open(LOG_JSONL, encoding="utf-8") as f:
            lines = f.readlines()[-n:]
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


# ── proje kartları ────────────────────────────────────────────────────────────
#
# Beyin 160 repoyu değil bu kartları okur (kullanıcı kararı 2026-10-19): her proje için GOAL/PLAN/TODO/
# TOBEDECIDED/DONE başları + son commit'ler ucuz bir modelle tek JSON'a özetlenir ve diske yazılır. Ham kısım
# (`build_raw_card`) modelsiz ve testlidir; model çağrısı motorda (`web_steward.summarize_card`), bu dosyada
# yalnız prompt ve çıktı ayrıştırması var. Özet bozuk gelirse ham karttan türetilen kart KALIR.

def card_path(name: str) -> str:
    return os.path.join(STEWARD_DIR, "cards", f"{name}.json")


def _read_doc_head(cwd: str, rel: str, max_chars: int = CARD_DOC_CHARS) -> str:
    try:
        with open(os.path.join(cwd, rel), encoding="utf-8", errors="replace") as f:
            return f.read(max_chars + 1)[:max_chars].strip()
    except OSError:
        return ""


def _git_recent(cwd: str, n: int = 5) -> Tuple[List[str], float]:
    """(`<kısa-sha> <tarih> <konu>` satırları, son commit epoch'u). Git deposu değilse/hata: ([], 0.0).
    `.git` YOKSA hiç çalıştırılmaz: üst klasördeki başka bir deponun geçmişi bu projeye yazılmasın."""
    if not cwd or not os.path.exists(os.path.join(cwd, ".git")):
        return [], 0.0
    try:
        r = subprocess.run(["git", "-C", cwd, "log", f"-{n}", "--format=%h\t%ct\t%cs\t%s"],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        return [], 0.0
    if r.returncode != 0:
        return [], 0.0
    lines: List[str] = []
    last = 0.0
    for ln in r.stdout.splitlines():
        parts = ln.split("\t", 3)
        if len(parts) < 4:
            continue
        sha, ct, day, subject = parts
        try:
            last = max(last, float(ct))
        except ValueError:
            pass
        lines.append(f"{sha} {day} {subject}")
    return lines, last


def build_raw_card(cwd: str) -> Dict[str, Any]:
    """Modelsiz ham kart: {docs: {dosya: baş}, git_log: [...], last_commit: epoch, source_hash}. `source_hash`
    kartın görebileceği her şeyin (doküman başları + son commit satırları) özeti; değişince kart eskimiş sayılır."""
    docs: Dict[str, str] = {}
    for d in CARD_DOCS:
        head = _read_doc_head(cwd, d) if cwd else ""
        if head:
            docs[d] = head
    git_log, last_commit = _git_recent(cwd)
    h = hashlib.sha1()
    for d in CARD_DOCS:
        if d in docs:
            h.update(f"\0{d}\0{docs[d]}".encode("utf-8", "replace"))
    for ln in git_log:
        h.update(f"\0{ln}".encode("utf-8", "replace"))
    return {"docs": docs, "git_log": git_log, "last_commit": last_commit, "source_hash": h.hexdigest()[:16]}


def _short(text: Any, n: int = CARD_TEXT_CHARS) -> str:
    return _clip(" ".join(str(text or "").split()), n)


def _str_list(v: Any) -> List[str]:
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    out = [_short(x) for x in v if str(x or "").strip()]
    return out[:CARD_LIST_ITEMS]


def _tbd_lines(text: str) -> List[str]:
    """TOBEDECIDED başından `TBD`'li satırlar — model yokken `open_tbds` için kaba bir ham tahmin."""
    out = []
    for ln in (text or "").splitlines():
        t = ln.strip().lstrip("-*#• ").strip()
        if "TBD" in t and t:
            out.append(_short(t))
        if len(out) >= CARD_LIST_ITEMS:
            break
    return out


def _goal_from_docs(docs: Dict[str, str]) -> str:
    for line in (docs.get("GOAL.md") or "").splitlines():
        t = line.strip()
        if t and not t.startswith("#"):
            return _short(t)
    return ""


def raw_card_fields(raw: Dict[str, Any], project: Optional[Project] = None) -> Dict[str, Any]:
    """Modele hiç gidilemeyen/yanıtı bozuk durumda kartın içi: ham veriden türetilir, `next_step` bilinmiyor."""
    docs = raw.get("docs") or {}
    subjects = [ln.split(" ", 2)[2] for ln in (raw.get("git_log") or []) if ln.count(" ") >= 2]
    return {
        "goal": _short((project.goal if project else "") or _goal_from_docs(docs)),
        "phase_guess": project.phase if project and project.phase in PHASES else "",
        "next_step": "",
        "open_tbds": _tbd_lines(docs.get("TOBEDECIDED.md", "")),
        "blockers": [],
        "recent_done": [_short(x) for x in subjects[:3]],
    }


def parse_card_json(text: str) -> Optional[Dict[str, Any]]:
    """Modelin yanıtından kart alanlarını çıkar: ```json çitli ya da çıplak, etrafında düzyazı olabilir.
    Ayrıştırılamıyor ya da hiç tanınan alan yoksa None (çağıran ham kartta kalır)."""
    if not text:
        return None
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    cand = m.group(1) if m else None
    if cand is None:
        i, j = t.find("{"), t.rfind("}")
        if i == -1 or j <= i:
            return None
        cand = t[i:j + 1]
    try:
        d = json.loads(cand)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    known = ("goal", "phase_guess", "next_step", "open_tbds", "blockers", "recent_done")
    if not any(k in d for k in known):
        return None
    phase = str(d.get("phase_guess") or "").strip().lower()
    return {
        "goal": _short(d.get("goal")),
        "phase_guess": phase if phase in PHASES else "",
        "next_step": _short(d.get("next_step")),
        "open_tbds": _str_list(d.get("open_tbds")),
        "blockers": _str_list(d.get("blockers")),
        "recent_done": _str_list(d.get("recent_done")),
    }


def build_card_prompt(name: str, raw: Dict[str, Any], project: Optional[Project] = None, lang: str = "tr") -> str:
    """Kart özeti için tek seferlik prompt — dosya içeriği prompt'un içinde (model araç kullanamaz)."""
    tr = lang != "en"
    parts: List[str] = []
    if tr:
        parts.append(
            f"Aşağıda '{name}' adlı bir projenin belge başları ve son commit'leri var. Bunlardan projenin durum kartını "
            "çıkar. YALNIZ tek bir JSON nesnesi yaz (açıklama, markdown çiti yok), şu anahtarlarla:\n"
            '{"goal": "tek cümle amaç", "phase_guess": "idea|planning|planned|paused|done", '
            '"next_step": "sıradaki tek somut iş", "open_tbds": ["açık karar maddeleri"], '
            '"blockers": ["engeller"], "recent_done": ["son biten işler"]}\n'
            f"Listeler en çok {CARD_LIST_ITEMS} madde, her alan kısa ve Türkçe olsun. Bilmediğin alanı boş bırak "
            "(\"\" ya da []); uydurma.")
    else:
        parts.append(
            f"Below are the document heads and recent commits of a project called '{name}'. Produce its status card. "
            "Write ONLY a single JSON object (no prose, no markdown fence) with these keys:\n"
            '{"goal": "one-sentence goal", "phase_guess": "idea|planning|planned|paused|done", '
            '"next_step": "the single next concrete task", "open_tbds": ["open decision items"], '
            '"blockers": ["blockers"], "recent_done": ["recently finished work"]}\n'
            f"At most {CARD_LIST_ITEMS} items per list, every field short. Leave unknown fields empty (\"\" or []); do not invent.")
    if project is not None:
        if project.goal:
            parts.append(("Kayıtlı amaç: " if tr else "Registered goal: ") + _short(project.goal, 600))
        parts.append(("Kayıtlı faz: " if tr else "Registered phase: ") + project.phase)
    for d, body in (raw.get("docs") or {}).items():
        parts.append(f"=== {d} ===\n{body}")
    if raw.get("git_log"):
        parts.append("=== git log -5 ===\n" + "\n".join(raw["git_log"]))
    if not (raw.get("docs") or raw.get("git_log")):
        parts.append("(belge ya da commit yok)" if tr else "(no documents or commits)")
    return "\n\n".join(parts)


def pick_card_model(configured: str, choices: List[str], fallback: str = "") -> str:
    """`card_model` doluysa o; boşsa `choices` içinde "haiku" geçen ilk (sıralı listenin SONUNCUSU = en yeni
    olanı), yoksa `fallback` (sağlayıcının varsayılan modeli)."""
    if configured.strip():
        return configured.strip()
    haiku = sorted(c for c in choices if "haiku" in c.lower())
    return haiku[-1] if haiku else fallback


def make_card(raw: Dict[str, Any], parsed: Optional[Dict[str, Any]], project: Optional[Project] = None,
              *, now: Optional[float] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ham + (varsa) model özeti -> yazılacak kart. Özet alanı boşsa ham türetimdeki değer kalır.
    `summarized`: modelden gelen özet kullanıldı mı (False = ham kart)."""
    base = raw_card_fields(raw, project)
    if parsed:
        for k, v in parsed.items():
            if v:
                base[k] = v
    card = dict(base)
    card.update({
        "last_activity": float(raw.get("last_commit") or 0.0),
        "source_hash": raw.get("source_hash", ""),
        "updated_at": now if now is not None else _now(),
        "summarized": bool(parsed),
    })
    if meta:
        card.update(meta)
    return card


def load_card(name: str) -> Optional[Dict[str, Any]]:
    d = _load_json(card_path(name), None)
    return d if isinstance(d, dict) else None


def save_card(name: str, card: Dict[str, Any]) -> None:
    _save_json(card_path(name), card)


def load_cards() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    try:
        names = os.listdir(os.path.join(STEWARD_DIR, "cards"))
    except OSError:
        return out
    for fn in sorted(names):
        if fn.endswith(".json") and valid_name(fn[:-5]):
            c = load_card(fn[:-5])
            if c is not None:
                out[fn[:-5]] = c
    return out


def mark_card_stale(name: str) -> bool:
    """Oturum yeniden açıldı (handover sonrası) -> kart bir sonraki fırsatta yenilensin. Kart yoksa no-op."""
    card = load_card(name)
    if card is None or card.get("stale"):
        return False
    card["stale"] = True
    save_card(name, card)
    return True


def card_refresh_reason(card: Optional[Dict[str, Any]], source_hash: str, now: float, max_age_hours: int) -> str:
    """"" = yenileme gerekmez; aksi halde neden: missing | stale | changed | old. Aynı kaynak özeti için
    başarısız bir deneme (`attempt_hash`) varsa `max_age_hours` dolana dek tekrar denenmez (her tick'te boşa
    model çağrısı olmasın); kaynak değişirse hemen yeniden denenir."""
    if card is None:
        return "missing"
    max_age = max_age_hours * 3600
    attempt_at = float(card.get("attempt_at") or 0.0)
    if card.get("attempt_hash") == source_hash and (not max_age or now - attempt_at < max_age):
        return ""
    if card.get("stale"):
        return "stale"
    if card.get("source_hash") != source_hash:
        return "changed"
    if max_age and now - max(float(card.get("updated_at") or 0.0), attempt_at) >= max_age:
        return "old"
    return ""


def note_card_failure(name: str, source_hash: str, error: str, now: Optional[float] = None) -> None:
    """Var olan kartı bozmadan başarısız denemeyi kaydet (`card_refresh_reason` geri çekilsin)."""
    card = load_card(name)
    if card is None:
        return
    card.update({"attempt_hash": source_hash, "attempt_at": now if now is not None else _now(),
                 "last_error": _short(error, 300)})
    save_card(name, card)


def card_one_liner(card: Optional[Dict[str, Any]]) -> str:
    return str((card or {}).get("next_step") or "")


# ── persona ───────────────────────────────────────────────────────────────────

def persona_text(override: str = "") -> str:
    """Etkin persona: Ayarlar'daki override doluysa o, yoksa paketlenmiş `data/steward.md`."""
    if override.strip():
        return override.strip() + "\n"
    try:
        with open(BUNDLED_PERSONA, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# ── işaret taraması ───────────────────────────────────────────────────────────

def scan_markers(text: str) -> Dict[str, Any]:
    """Bir oturum yanıtındaki `STEWARD-*` satırlarını çıkar. Dönen: {asks:[...], ideas:[...],
    blocked:[...], plan_ready: bool, done: bool}. Satır başındaki madde/boşluk toleranslı;
    işaret satırın İÇİNDE de olabilir (model bazen önüne açıklama koyar) — kalanı alınır."""
    out: Dict[str, Any] = {"asks": [], "ideas": [], "blocked": [], "plan_ready": False, "done": False}
    if not text:
        return out
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*• ").strip()
        if not line:
            continue
        for mark, key in ((MARK_ASK, "asks"), (MARK_IDEA, "ideas"), (MARK_BLOCKED, "blocked")):
            idx = line.find(mark)
            if idx != -1:
                body = line[idx + len(mark):].strip().strip("`")
                if body:
                    out[key].append(body)
                break
        else:
            if MARK_PLAN_READY in line:
                out["plan_ready"] = True
            elif MARK_DONE in line and MARK_END not in line:
                out["done"] = True
    return out


# ── direktif / tur prompt'ları ────────────────────────────────────────────────

_PROTOCOL_TR = (
    "Değnekçi protokolü (yanıtının SONUNDA, her biri ayrı satır, gerektiğinde):\n"
    f"- bana sormadan ilerleyemeyeceğin bir karar varsa: `{MARK_ASK} <tek cümlelik soru>`\n"
    f"- aklına bu projeyle ilgisiz yeni bir fikir gelirse: `{MARK_IDEA} <fikir>`\n"
    f"- takıldın, düşündün, çözemedin: `{MARK_BLOCKED} <nerede takıldın>`\n"
)

_PROTOCOL_EN = (
    "Steward protocol (at the END of your reply, one per line, only when needed):\n"
    f"- a decision you cannot make without me: `{MARK_ASK} <one-sentence question>`\n"
    f"- a new idea unrelated to this project: `{MARK_IDEA} <idea>`\n"
    f"- stuck after thinking it through: `{MARK_BLOCKED} <where>`\n"
)


def build_directive(project: Project, lang: str = "tr", extra: str = "", answer: Optional[Question] = None) -> str:
    """Bir proje oturumuna gönderilecek faz direktifi. `answer` verilirse önce insanın cevabı iletilir.
    Beyin kendi direktifini `extra` ile tamamen ezebilir (şablon yine protokol kuyruğunu ekler)."""
    tr = lang != "en"
    parts: List[str] = []
    head = f"[claudeops değnekçi — {project.name}]" if tr else f"[claudeops steward — {project.name}]"
    parts.append(head)
    if project.goal:
        parts.append(("Amaç: " if tr else "Goal: ") + project.goal.strip())
    if answer is not None:
        parts.append(("Sorduğun soru: " if tr else "Your question: ") + answer.text.strip())
        parts.append(("Cevabım: " if tr else "My answer: ") + answer.answer.strip())
    if extra.strip():
        parts.append(extra.strip())
    elif project.phase == "planning":
        if tr:
            parts.append(
                "Planlama fazındayız. Sırayla:\n"
                "1. Konuyla ilgili literatürü ve mevcut çözümleri tara (web araması, kaynak listesi); bulduklarını "
                "KAYNAKLAR.md'ye kısa özetle yaz.\n"
                "2. Zaten yapan var mı? İşe yarıyor mu, kullanılmalı mı? Daha iyisi var mı, daha iyisi olur mu? "
                "Gerekçeli değerlendir.\n"
                "3. PLAN.md yaz: hedef, kapsam, adımlar (sıralı, küçük), riskler, açık kararlar.\n"
                "Verdiğin kararları TOBEDECIDED.md'ye (TBD#), ertelenen işleri TODO.md'ye yaz. Her adımda commit+push.\n"
                f"Plan tamamlanıp uygulanmaya hazır olduğunda yanıtını `{MARK_PLAN_READY}` satırıyla bitir."
            )
        else:
            parts.append(
                "We are in the planning phase. In order:\n"
                "1. Survey the literature and existing solutions (web search, source list); summarize into KAYNAKLAR.md.\n"
                "2. Does something already do this? Is it usable? Is there something better, could there be? Judge with reasons.\n"
                "3. Write PLAN.md: goal, scope, ordered small steps, risks, open decisions.\n"
                "Record decisions in TOBEDECIDED.md (TBD#), deferred work in TODO.md. Commit+push at every step.\n"
                f"When the plan is ready to execute, end your reply with `{MARK_PLAN_READY}`."
            )
    elif project.phase == "planned":
        if tr:
            parts.append(
                "Plan hazır, uygulama fazındayız. PLAN.md/TODO.md'deki SIRADAKİ işi al ve ilerlet: gerekli komutları "
                "çalıştır, sonucu doğrula. Aldığın kararları TOBEDECIDED.md'ye (TBD#), fark ettiğin edge case'leri "
                "TODO.md'ye kaydet. Takıldığın yerde önce kendin düşün, çözüm bulamazsan sor. İş bitince commit+push, "
                "DONE.md'ye tek satır.\n"
                f"Projedeki her şey bittiyse yanıtını `{MARK_DONE}` satırıyla bitir."
            )
        else:
            parts.append(
                "The plan is ready; execution phase. Take the NEXT item in PLAN.md/TODO.md and move it forward: run the "
                "needed commands, verify the result. Record decisions in TOBEDECIDED.md (TBD#), edge cases in TODO.md. "
                "When stuck, think first, ask only if you cannot resolve it. Commit+push when done, one line in DONE.md.\n"
                f"If the whole project is finished, end your reply with `{MARK_DONE}`."
            )
    if project.notes.strip():
        parts.append(("Değnekçi notu: " if tr else "Steward note: ") + project.notes.strip())
    parts.append(_PROTOCOL_TR if tr else _PROTOCOL_EN)
    return "\n\n".join(parts)


def _clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def card_lines(card: Dict[str, Any], tr: bool = True, now: Optional[float] = None) -> List[str]:
    """Proje kartını tur prompt'una / insan çıktısına gidecek kısa satırlara döker (boş alanlar atlanır)."""
    out: List[str] = []
    age = ""
    if card.get("updated_at"):
        h = max(0, int(((now or _now()) - float(card["updated_at"])) / 3600))
        age = (f" ({h} sa önce" if tr else f" ({h}h ago") + (", bayat)" if card.get("stale") and tr else
                                                              ", stale)" if card.get("stale") else ")")
    out.append(("kart" if tr else "card") + age + ("" if card.get("summarized", True) else (" [ham]" if tr else " [raw]")) + ":")
    for key, label_tr, label_en in (("goal", "amaç", "goal"), ("phase_guess", "faz tahmini", "phase guess"),
                                    ("next_step", "sıradaki adım", "next step")):
        if card.get(key):
            out.append(f"- {label_tr if tr else label_en}: {_clip(card[key], 300)}")
    for key, label_tr, label_en in (("open_tbds", "açık TBD", "open TBDs"), ("blockers", "engeller", "blockers"),
                                    ("recent_done", "son biten", "recently done")):
        vals = card.get(key) or []
        if vals:
            out.append(f"- {label_tr if tr else label_en}: " + "; ".join(_clip(v, 120) for v in vals[:5]))
    return out


def build_tour_prompt(items: List[Dict[str, Any]], lang: str = "tr", open_qs: Optional[List[Question]] = None,
                      now: Optional[float] = None) -> str:
    """Beyne gönderilen tur prompt'u. `items`: motorun topladığı gözden-geçirme maddeleri —
    her biri {kind: idle|review|idea|due|blocked, name, phase, goal, last_directive, last_exchange,
    docs: {TODO.md: ..., PLAN.md: ...}, idle_minutes, text}. Beyin HER madde için bir MCP aracı çağırır
    (steward_directive / steward_restart / steward_stop / steward_ask_user / steward_set_project /
    steward_idea_update / steward_skip) ve `MARK_END` satırıyla bitirir."""
    tr = lang != "en"
    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(now or _now()))
    lines: List[str] = []
    lines.append(f"[claudeops değnekçi turu — {ts}]" if tr else f"[claudeops steward tour — {ts}]")
    if tr:
        lines.append(
            "Aşağıdaki maddelerin HER BİRİ için bir karar ver ve ilgili MCP aracını çağır "
            "(steward_project_context ile daha fazla bağlam alabilirsin): "
            "steward_directive (sıradaki işi ver), steward_restart (boş/yanlış iş yapıyor → durdur, daha iyi "
            "direktifle ve gerekirse başka model/effort ile yeniden aç), steward_stop (şimdilik dursun), "
            "steward_ask_user (benim kararım gerekiyor), steward_set_project (faz/öncelik/not), "
            "steward_idea_update (fikir: proje/sonra/çöp), steward_register_project (fikirden proje), "
            "steward_skip (bu tur dokunma). Kararsız kaldığında sor, ama sormadan verebileceğin kararı sorma."
        )
    else:
        lines.append(
            "For EACH item below decide and call the matching MCP tool (steward_project_context gives more context): "
            "steward_directive (next task), steward_restart (idle/wrong work → stop and reopen with a better directive, "
            "other model/effort if needed), steward_stop, steward_ask_user (needs my decision), steward_set_project, "
            "steward_idea_update, steward_register_project, steward_skip. Ask when unsure, never ask what you can decide."
        )
    if open_qs:
        lines.append("")
        lines.append("Bana sorulmuş, hâlâ cevapsız sorular (tekrar sorma):" if tr else "Open questions already waiting on me (do not re-ask):")
        for q in open_qs[:10]:
            lines.append(f"- [{q.id}] {q.project or '-'}: {_clip(q.text, 200)}")
    for n, it in enumerate(items, 1):
        lines.append("")
        kind = it.get("kind", "")
        name = it.get("name", "")
        label = {"idle": "BOŞTA" if tr else "IDLE", "review": "GÖZDEN GEÇİR" if tr else "REVIEW",
                 "idea": "FİKİR" if tr else "IDEA", "due": "SIRASI GELDİ" if tr else "DUE",
                 "blocked": "TAKILDI" if tr else "BLOCKED"}.get(kind, kind.upper())
        lines.append(f"### {n}. {label} — {name or it.get('id', '')}")
        if kind == "idea":
            lines.append(f"id={it.get('id')}  {_clip(it.get('text', ''), 600)}")
            continue
        if it.get("phase"):
            lines.append(("faz: " if tr else "phase: ") + str(it["phase"]) + (f"  tür: {it['kindp']}" if it.get("kindp") else ""))
        if it.get("goal"):
            lines.append(("amaç: " if tr else "goal: ") + _clip(it["goal"], 300))
        if it.get("idle_minutes") is not None:
            mins = int(it["idle_minutes"])
            lines.append(f"boşta: {mins} dk" if tr else f"idle: {mins} min")
        if it.get("last_directive"):
            lines.append(("son direktif: " if tr else "last directive: ") + _clip(it["last_directive"], 300))
        ex = it.get("last_exchange") or {}
        if ex.get("user"):
            lines.append(("son istek: " if tr else "last request: ") + _clip(ex["user"], 300))
        if ex.get("assistant"):
            lines.append(("son yanıt: " if tr else "last reply: ") + _clip(ex["assistant"], 700))
        card = it.get("card")
        if card:
            lines += card_lines(card, tr)
        else:
            for doc, body in (it.get("docs") or {}).items():
                if body:
                    lines.append(f"{doc} (baş):" if tr else f"{doc} (head):")
                    lines.append(_clip(body, 600))
        if it.get("text"):
            lines.append(_clip(it["text"], 600))
    lines.append("")
    lines.append((f"Bütün maddeleri işledikten sonra yanıtını tek başına `{MARK_END}` satırıyla bitir."
                  if tr else f"After handling every item, end your reply with a line containing only `{MARK_END}`."))
    return "\n".join(lines)


def build_workspace_claude_md(persona: str, lang: str = "tr") -> str:
    """Beynin cwd'sindeki CLAUDE.md — persona + araç kılavuzu. Her beyin açılışında yeniden yazılır."""
    tr = lang != "en"
    tools = (
        "## Araçların (MCP `cops-steward`)\n"
        "- `steward_overview` — filo + projeler (sıradaki adım dahil) + açık sorular + yeni fikirler (her turun başında bak)\n"
        "- `steward_project_context name` — projenin fazı/amacı/notu, son konuşma, PROJE KARTI (hedef, sıradaki adım, açık TBD'ler, engeller; "
        "kart yoksa TODO/PLAN/TOBEDECIDED başları; `docs=true` ikisini birden), git durumu\n"
        "- `steward_read_file name path` — proje klasöründen dosya oku (salt-okunur)\n"
        "- `steward_directive name text [model effort]` — oturuma sıradaki işi gönder (kapalıysa açar)\n"
        "- `steward_restart name directive reason [model effort]` — durdur + aynı konuşmayla yeniden aç + yeni direktif\n"
        "- `steward_handover name` — kapanış mesajı gönder (dolan oturum; motor zaten 1900 satırda bunu kendisi yapar)\n"
        "- `steward_stop name reason` — oturumu durdur\n"
        "- `steward_set_project name [phase kind goal priority cadence_minutes notes model effort]`\n"
        "- `steward_register_project name cwd goal [kind phase cli model resources]` — yeni proje (klasör yoksa açar, GOAL.md yazar)\n"
        "- `steward_ask_user project question` — bana soru (telefona bildirim gider; cevabı motor oturuma iletir)\n"
        "- `steward_note project text` — kendi notun (bir sonraki direktifte oturuma da gider)\n"
        "- `steward_idea text` / `steward_idea_update id status [project]` — fikir kutusu\n"
        "- `steward_questions` / `steward_log` — açık sorular / son olaylar\n"
        "- `steward_skip name reason` — bu tur dokunmuyorum (kayda geçer)\n"
        if tr else
        "## Your tools (MCP `cops-steward`)\n"
        "- `steward_overview`, `steward_project_context name`, `steward_read_file name path`\n"
        "- `steward_directive`, `steward_restart`, `steward_handover`, `steward_stop`\n"
        "- `steward_set_project`, `steward_register_project`, `steward_ask_user`, `steward_note`\n"
        "- `steward_idea`, `steward_idea_update`, `steward_questions`, `steward_log`, `steward_skip`\n"
    )
    tail = (
        f"\n## Tur protokolü\nHer tur prompt'unda listelenen her madde için bir araç çağır; bitince yanıtını tek başına "
        f"`{MARK_END}` satırıyla kapat. Araç çağırmadan verilen karar KAYDA GEÇMEZ.\n"
        if tr else
        f"\n## Tour protocol\nCall one tool per listed item; finish with a line containing only `{MARK_END}`. "
        "A decision without a tool call is not recorded.\n"
    )
    return persona.rstrip() + "\n\n" + tools + tail


# ── kural motoru ──────────────────────────────────────────────────────────────

def _is_project_session(v: SessionView, projects: Dict[str, Project]) -> bool:
    return v.project in projects


def phase_model_effort(project: Project, cfg: Config) -> Tuple[str, str]:
    """(model, effort) — proje override'ı > faz varsayılanı > "" (çağıran roster/provider varsayılanına düşer)."""
    if project.phase == "planning":
        model, effort = cfg.planning_model, cfg.planning_effort
    else:
        model, effort = cfg.planned_model, cfg.planned_effort
    return (project.model or model or ""), (project.effort or effort or "")


def review_items(views: List[SessionView], projects: Dict[str, Project], cfg: Config, now: float,
                 questions: List[Question], ideas: List[Idea], *, skip: Optional[set] = None,
                 last_directive_at: Optional[Dict[str, float]] = None,
                 reviewed_at: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """Beynin yargısını gerektiren maddeler: boşta bekleyen proje oturumu (`idle`), uzun süredir meşgul
    olup gözden geçirilmemiş oturum (`review`), yeni fikir (`idea`), oturuma iletilemeyen cevap
    (`blocked`). `plan_tick` bunu çağırır; elle "tur" (`web_steward.run_tour(force=True)`) de aynı listeyi alır."""
    skip = skip or set()
    lda = last_directive_at or {}
    rva = reviewed_at or {}
    items: List[Dict[str, Any]] = []
    for v in views:
        if not v.running or not _is_project_session(v, projects) or v.name in skip or v.name == cfg.brain_name:
            continue
        idle_since = max(v.last_activity, lda.get(v.name, 0.0), v.started_at)
        if v.busy is False and idle_since and (now - idle_since) >= cfg.idle_minutes * 60:
            items.append({"kind": "idle", "name": v.name, "idle_minutes": (now - idle_since) / 60})
        elif v.busy and (now - max(lda.get(v.name, 0.0), rva.get(v.name, 0.0), v.started_at)) >= cfg.review_minutes * 60:
            items.append({"kind": "review", "name": v.name})
    for i in ideas:
        if i.status == "new":
            items.append({"kind": "idea", "id": i.id, "text": i.text, "name": ""})
    for q in undelivered_answers(questions):
        if not q.project or q.project == cfg.brain_name or q.project not in projects:
            items.append({"kind": "blocked", "name": q.project or "-", "id": q.id,
                          "text": f"Cevaplanan soru [{q.id}]: {q.text}\nCevap: {q.answer}"})
    return items


def plan_tick(views: List[SessionView], projects: Dict[str, Project], state: Dict[str, Any], cfg: Config,
              now: float, questions: List[Question], ideas: List[Idea]) -> Tuple[List[Action], Dict[str, Any]]:
    """Bir tick'in kararları. SAF: hiçbir yan etki yok; `state`'in GÜNCELLENMİŞ kopyasını döner
    (motor kaydeder). Sıra: ekonomi (handover/respawn) → işaretler → cevap iletimi → uğrama/başlatma →
    slot baskısı → beyin turu."""
    st: Dict[str, Any] = json.loads(json.dumps(state)) if state else {}
    ho_pending: Dict[str, float] = dict(st.get("ho_pending") or {})
    seen: Dict[str, str] = dict(st.get("seen_assistant") or {})
    last_directive_at: Dict[str, float] = dict(st.get("last_directive_at") or {})
    reviewed_at: Dict[str, float] = dict(st.get("reviewed_at") or {})
    actions: List[Action] = []
    by_name = {v.name: v for v in views}
    busy_names: set = set()   # bu tick'te zaten dokunulan oturumlar (ikinci bir eylem gönderme)

    # 1) Oturum ekonomisi — scrollback eşiği → handover (beyin dahil: onun da scrollback'i dolar)
    for v in views:
        if not v.running or not v.tmux:
            continue
        if v.history_size is not None and v.history_size >= cfg.history_warn_at and v.name not in ho_pending:
            actions.append(Action("handover", v.name, f"history_size {v.history_size} >= {cfg.history_warn_at}"))
            ho_pending[v.name] = now
            busy_names.add(v.name)

    # 2) Handover gönderilmiş olanlar — READY FOR HANDOVER geldi ya da süre doldu → yeniden aç
    for name, sent_at in list(ho_pending.items()):
        if name in busy_names:
            continue
        v = by_name.get(name)
        if v is None or not v.running:
            actions.append(Action("respawn", name, "handover sent, session gone → start"))
            ho_pending.pop(name, None)
            busy_names.add(name)
            continue
        ready = READY_FOR_HANDOVER in (v.last_assistant or "")
        expired = (now - float(sent_at)) >= cfg.ho_grace_minutes * 60
        # busy None (bu CLI'da sinyal yok) = "meşgul değil" sayılır; yalnız kesin True bekletir
        if v.busy is not True and (ready or expired):
            actions.append(Action("respawn", name, "READY FOR HANDOVER" if ready else "handover grace expired"))
            ho_pending.pop(name, None)
            busy_names.add(name)

    # 3) İşaret taraması — yalnız DEĞİŞMİŞ yanıtlarda (aynı yanıtı her tick yeniden işleme)
    for v in views:
        if not v.running or not v.last_assistant or v.name == cfg.brain_name:
            continue
        digest = hashlib.sha1(v.last_assistant.encode('utf-8', 'replace')).hexdigest()[:16]
        if seen.get(v.name) == digest:
            continue
        seen[v.name] = digest
        m = scan_markers(v.last_assistant)
        proj = v.project if v.project in projects else ""
        for q in m["asks"]:
            actions.append(Action("ask_user", v.name, "STEWARD-ASK", {"project": proj or v.name, "text": q}))
        for b in m["blocked"]:
            actions.append(Action("ask_user", v.name, "STEWARD-BLOCKED",
                                  {"project": proj or v.name, "text": ("Takıldım: " + b)}))
        for i in m["ideas"]:
            actions.append(Action("idea", v.name, "STEWARD-IDEA", {"text": i}))
        if proj and m["plan_ready"] and projects[proj].phase == "planning":
            actions.append(Action("set_phase", proj, "STEWARD-PLAN-READY", {"phase": "planned"}))
        if proj and m["done"]:
            actions.append(Action("set_phase", proj, "STEWARD-DONE", {"phase": "done"}))
            if v.name not in busy_names:
                actions.append(Action("stop", v.name, "STEWARD-DONE"))
                busy_names.add(v.name)

    # 4) Cevaplanmış sorular → ilgili oturuma ilet (kapalıysa aç)
    starts = 0
    running_projects = {v.project for v in views if v.running and _is_project_session(v, projects)}
    active = len(running_projects)
    for q in undelivered_answers(questions):
        target = q.project
        if not target or target == cfg.brain_name or target not in projects:
            # Genel/beyin sorusu: beyin turunda gösterilir (aşağıda), oturuma iletilmez
            continue
        v = next((x for x in views if x.running and x.project == target), None)
        if v is not None:
            if v.name in busy_names or v.busy:
                continue   # bir sonraki tick
            actions.append(Action("deliver_answer", v.name, "answer", {"question_id": q.id}))
            busy_names.add(v.name)
            last_directive_at[v.name] = now
        elif starts < cfg.max_starts_per_tick and active + starts < cfg.max_active:
            actions.append(Action("start", target, "answer → start", {"question_id": q.id}))
            starts += 1
            busy_names.add(target)
            last_directive_at[target] = now

    # 5) Uğrama sırası — çalışmayan, aktif fazdaki, süresi dolmuş projeler
    due: List[Project] = []
    for p in projects.values():
        if p.phase not in ACTIVE_PHASES or p.cadence_minutes <= 0 or p.name in running_projects or p.name in busy_names:
            continue
        if p.last_visit == 0 or (now - p.last_visit) >= p.cadence_minutes * 60:
            due.append(p)
    due.sort(key=lambda p: (p.priority, p.last_visit))
    free = max(0, cfg.max_active - active - starts)
    for p in due:
        if starts >= cfg.max_starts_per_tick or free <= 0:
            break
        actions.append(Action("start", p.name, "due", {"phase": p.phase}))
        starts += 1
        free -= 1
        busy_names.add(p.name)
        last_directive_at[p.name] = now
    waiting = [p for p in due if p.name not in busy_names]

    # 6) Slot baskısı — bekleyen varsa, uzun süredir boşta duran proje oturumlarını durdur
    if waiting and free <= 0:
        for v in views:
            if not v.running or not _is_project_session(v, projects) or v.name in busy_names or v.name in ho_pending:
                continue
            idle_since = max(v.last_activity, last_directive_at.get(v.name, 0.0), v.started_at)
            if v.busy is False and idle_since and (now - idle_since) >= cfg.stop_idle_minutes * 60:
                actions.append(Action("stop", v.name, f"idle ≥ {cfg.stop_idle_minutes} dk, slot bekleyen var"))
                busy_names.add(v.name)

    # 7) Beyin turu maddeleri
    items = review_items(views, projects, cfg, now, questions, ideas,
                         skip=busy_names | set(ho_pending), last_directive_at=last_directive_at, reviewed_at=reviewed_at)
    last_tour = float(st.get("last_tour") or 0.0)
    brain = by_name.get(cfg.brain_name)
    if items and (now - last_tour) >= cfg.tour_minutes * 60 and brain is not None and brain.running and brain.busy is False:
        actions.append(Action("tour", cfg.brain_name, f"{len(items)} madde", {"items": items}))
        st["last_tour"] = now
        for it in items:
            if it["kind"] == "review":
                reviewed_at[it["name"]] = now
    st["pending_items"] = len(items)
    st["ho_pending"] = ho_pending
    st["seen_assistant"] = seen
    st["last_directive_at"] = last_directive_at
    st["reviewed_at"] = reviewed_at
    st["last_tick"] = now
    return actions, st


def summarize_projects(projects: Dict[str, Project]) -> Dict[str, int]:
    out = {ph: 0 for ph in PHASES}
    for p in projects.values():
        out[p.phase] = out.get(p.phase, 0) + 1
    return out
