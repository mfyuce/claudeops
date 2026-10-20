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
import html
import json
import os
import re
import secrets
import subprocess
import threading
import time
from collections import Counter
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


@dataclass(frozen=True)
class StewardPaths:
    """Bir değnekçi kimliğinin dosya yolları. `cards`/`oneshot` kimlikler arasında ORTAKTIR (hep `STEWARD_DIR` altında)."""
    sid: str
    root: str
    projects: str
    ideas: str
    questions: str
    state: str
    log: str
    jobs: str
    workspace: str
    daily: str
    lock: str
    cards: str
    oneshot: str


_SID_RE = re.compile(r"[a-z]+")   # yalnız harf: yol ayıracı/`..` ile `stewards/` dışına çıkılamaz (tam kimlik kuralı P2)


def paths_for(sid: str = "default") -> StewardPaths:
    """Yollar ÇAĞRI ANINDA türer. `default`: bugünkü düzen (`STEWARD_DIR` ve modül sabitleri, veri taşınmaz);
    diğer kimlikler `STEWARD_DIR/stewards/<sid>/`. `stewards/` asimetrisi yalnız burada."""
    sid = "default" if sid is None else sid
    if not isinstance(sid, str) or not _SID_RE.fullmatch(sid):
        raise ValueError(f"invalid steward id: {sid!r}")
    shared = dict(cards=os.path.join(STEWARD_DIR, "cards"), oneshot=os.path.join(STEWARD_DIR, "oneshot"))
    if sid == "default":
        return StewardPaths(sid=sid, root=STEWARD_DIR, projects=PROJECTS_JSON, ideas=IDEAS_JSON,
                            questions=QUESTIONS_JSON, state=STATE_JSON, log=LOG_JSONL,
                            jobs=os.path.join(STEWARD_DIR, "jobs.json"), workspace=WORKSPACE_DIR,
                            daily=os.path.join(STEWARD_DIR, "daily"), lock=os.path.join(STEWARD_DIR, ".lock"), **shared)
    r = os.path.join(STEWARD_DIR, "stewards", sid)
    return StewardPaths(sid=sid, root=r, projects=os.path.join(r, "projects.json"), ideas=os.path.join(r, "ideas.json"),
                        questions=os.path.join(r, "questions.json"), state=os.path.join(r, "state.json"),
                        log=os.path.join(r, "log.jsonl"), jobs=os.path.join(r, "jobs.json"),
                        workspace=os.path.join(r, "workspace"), daily=os.path.join(r, "daily"),
                        lock=os.path.join(r, ".lock"), **shared)


def _pp(paths: Any = None) -> StewardPaths:
    """İsteğe bağlı `paths` argümanı: None = `default` (eski davranış), str = kimlik, StewardPaths = olduğu gibi."""
    return paths if isinstance(paths, StewardPaths) else paths_for("default" if paths is None else paths)
CARD_DOCS = ("GOAL.md", "PLAN.md", "TODO.md", "TOBEDECIDED.md", "DONE.md")
CARD_DOC_CHARS = 1500            # kartın modele göstereceği her doküman başı
CARD_LIST_ITEMS = 8              # open_tbds / blockers / recent_done en çok bu kadar madde
CARD_TEXT_CHARS = 400            # kart alanlarının (goal/next_step/madde) üst sınırı

PHASES = ("idea", "planning", "planned", "paused", "done")
KINDS = ("book", "article", "software", "other")
ACTIVE_PHASES = ("planning", "planned")

# Yetki kipi (docs/degnekci-plan.md: observe → suggest → act, ilk hafta observe). `suggest` henüz yok (faz 5).
MODES = ("observe", "act")
# observe'da UYGULANMAYAN (yalnız `would:<kind>` olarak kaydedilen) eylemler: canlı oturuma dokunanlar.
# ask_user / idea / set_phase / kart yenileme observe'da da çalışır (kayıt tutar, oturuma dokunmaz).
OBSERVE_SKIPPED = ("handover", "respawn", "start", "stop", "deliver_answer", "tour")
OBSERVE_DEDUP_SECONDS = 6 * 3600   # aynı (tür, ad, soru) `would:` kaydı bu sürede bir kez yazılır

# Oturum yanıtlarında aranan işaretler — protokol/parse sözleşmesi, yerelleştirilmez
# (`orchestration.VERDICT_MARKER` ile aynı ilke). Proje oturumları MCP olmadan da
# değnekçiye bu satırlarla konuşur.
MARK_END = "COPS-STEWARD-END"          # beynin tur yanıtının sonu
MARK_ASK = "STEWARD-ASK:"              # insana soru (satırın kalanı soru metni)
MARK_IDEA = "STEWARD-IDEA:"            # yeni fikir
MARK_ROUTINE = "STEWARD-ROUTINE:"      # işleyiş sorusu (ne zaman/hangi sıra/hangi model): beyin cevaplar, sahibi rahatsız edilmez
MARK_BLOCKED = "STEWARD-BLOCKED:"      # takıldım (insana soru olarak düşer, önekli)
MARK_PLAN_READY = "STEWARD-PLAN-READY"  # planlama bitti → faz planned
MARK_DONE = "STEWARD-DONE"             # proje bitti → faz done, oturum durur
READY_FOR_HANDOVER = "READY FOR HANDOVER"

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_QUESTION_CHARS = 2000
QUESTION_MAX_OPTIONS = 6         # soru seçenekleri (evet/hayır, A/B/C, sonra): telefon sayfasında tek dokunuş
_MAX_OPTION_CHARS = 80
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
    status: str = "new"             # new | project | dropped | later | exported
    project: str = ""               # projeye dönüştüyse adı
    source: str = ""                # hangi oturum/kim yazdı
    exported: List[Dict[str, Any]] = field(default_factory=list)   # TODO/TBD'ye aktarım kayıtları (kind, target, projects, at)


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
    options: List[str] = field(default_factory=list)   # kısa seçenekler (boş = serbest metin); cevap bunlardan biri ya da metin
    key: str = ""                   # `/q/<id>?k=<key>` sayfasının soruya ÖZEL anahtarı (panel token'ı ntfy'ye girmesin)
    notified_at: float = 0.0        # telefona bildirildi (aynı açık soru ikinci kez bildirilmez)
    routine: bool = False           # işleyiş sorusu: telefona gitmez, beynin turunda cevaplanır; ROUTINE_ESCALATE_SECONDS dolarsa sahibine düşer
    repeats: int = 0                # oturum aynı soruyu yeniden sordu: cevap "zaten cevapladım" notuyla yeniden iletildi


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
    context_tokens: Optional[int] = None   # son asistan turunun bağlam boyutu (claude transkriptinden; bilinmiyorsa None)
    model: str = ""                     # çalışan modelin adı (eşik modele göre seçilir; bilinmiyorsa "")
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
    history_min_age_minutes: int = 15   # satır eşiği (yedek yol) yalnız bu kadar dakikadan yaşlı oturumda tetikler; 0 = yaşa bakma
    context_warn_tokens_fable: int = 150000   # Fable oturumlarında eşik (token başına daha pahalı: 0 = genel eşiği kullan)
    context_warn_tokens: int = 300000   # oturumun bağlamı (son turun girdi+cache token'ı) bu sayıyı aşarsa handover (0 = kapalı); her tur bağlamın TAMAMI yeniden okunur
    brain_cli: str = "claude"
    brain_model: str = ""
    brain_effort: str = "high"
    brain_name: str = "degnekci"
    planning_model: str = ""
    planning_effort: str = "medium"   # sahibin kalıcı kuralı: proje ANA oturumu Sonnet medium; ağır iş alt ajanda
    planned_model: str = ""
    planned_effort: str = ""
    lang: str = "tr"
    card_refresh: bool = True        # tick'te proje kartlarını (eskiyen/değişen) yenile
    card_cli: str = "claude"         # kart özetini üreten CLI (providers.oneshot)
    card_model: str = ""             # "" = card_cli'nin model_choices'inde "haiku" geçen, yoksa varsayılan model
    card_max_age_hours: int = 24     # kart bundan eskiyse yenile (0 = yaşa bakma)
    cards_per_tick: int = 1          # bir tick'te en çok kaç kart yenilenir (0 = hiç)
    mode: str = "observe"            # observe: oturuma dokunan eylemler uygulanmaz, `would:` olarak kaydedilir | act
    summary_hour: int = 21           # günlük özet: bu saatten (yerel) sonraki ilk tick'te, günde bir


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


def load_projects(paths: Any = None) -> Dict[str, Project]:
    raw = _load_json(_pp(paths).projects, {})
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


def save_projects(projects: Dict[str, Project], paths: Any = None) -> None:
    _save_json(_pp(paths).projects, {n: dataclasses.asdict(p) for n, p in projects.items()})


def upsert_project(name: str, *, paths: Any = None, **fields: Any) -> Project:
    """Alan bazlı güncelle (None/verilmeyen alanlar korunur). Geçersiz faz/tür/priority yok sayılır."""
    if not valid_name(name):
        raise ValueError(f"invalid project name: {name!r}")
    projects = load_projects(paths)
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
    save_projects(projects, paths)
    return p


def remove_project(name: str, paths: Any = None) -> bool:
    projects = load_projects(paths)
    if name not in projects:
        return False
    del projects[name]
    save_projects(projects, paths)
    return True


def load_ideas(paths: Any = None) -> List[Idea]:
    raw = _load_json(_pp(paths).ideas, [])
    return [_from_dict(Idea, d) for d in raw if isinstance(d, dict) and d.get("id")] if isinstance(raw, list) else []


def save_ideas(ideas: List[Idea], paths: Any = None) -> None:
    _save_json(_pp(paths).ideas, [dataclasses.asdict(i) for i in ideas])


def add_idea(text: str, source: str = "", paths: Any = None) -> Idea:
    text = str(text).strip()[:_MAX_IDEA_CHARS]
    if not text:
        raise ValueError("empty idea")
    ideas = load_ideas(paths)
    idea = Idea(id=_new_id("i"), text=text, created_at=_now(), source=source)
    ideas.append(idea)
    save_ideas(ideas, paths)
    return idea


def update_idea(idea_id: str, status: Optional[str] = None, project: Optional[str] = None,
                paths: Any = None) -> Optional[Idea]:
    ideas = load_ideas(paths)
    for i in ideas:
        if i.id == idea_id:
            if status in ("new", "project", "dropped", "later", "exported"):
                i.status = status
            if project is not None:
                i.project = str(project)
            save_ideas(ideas, paths)
            return i
    return None


def record_idea_export(idea_id: str, record: Dict[str, Any], paths: Any = None) -> Optional[Idea]:
    """Fikri `exported` yapar (varsayılan listeden kalkar) ve aktarım kaydını fikrin üstünde tutar (silinmez)."""
    ideas = load_ideas(paths)
    for i in ideas:
        if i.id == idea_id:
            i.status = "exported"
            i.exported = list(i.exported or []) + [record]
            save_ideas(ideas, paths)
            return i
    return None


def load_questions(paths: Any = None) -> List[Question]:
    raw = _load_json(_pp(paths).questions, [])
    return [_from_dict(Question, d) for d in raw if isinstance(d, dict) and d.get("id")] if isinstance(raw, list) else []


def save_questions(questions: List[Question], paths: Any = None) -> None:
    _save_json(_pp(paths).questions, [dataclasses.asdict(q) for q in questions])


def normalize_options(options: Any) -> List[str]:
    """Seçenek listesi: dize/sayı elemanlar, boşluk kırpılır, boş/yinelenen atılır, en çok `QUESTION_MAX_OPTIONS`,
    her biri `_MAX_OPTION_CHARS`. Liste değilse (ör. tek dize, None) boş liste = serbest metin sorusu."""
    if isinstance(options, str):
        options = [options]
    if not isinstance(options, (list, tuple)):
        return []
    out: List[str] = []
    for o in options:
        if isinstance(o, bool) or o is None:
            continue
        t = " ".join(str(o).split())[:_MAX_OPTION_CHARS]
        if t and t not in out:
            out.append(t)
        if len(out) >= QUESTION_MAX_OPTIONS:
            break
    return out


def resolve_answer(q: Question, raw: str) -> str:
    """Ham cevap → kaydedilecek metin: seçenekli soruda `1`..`n` (ya da `A`..) o seçeneğin metni, seçenek metnine
    (büyük/küçük harf duyarsız) tam eşleşen de kanonik metin; diğer her şey serbest metin olarak kalır."""
    raw = " ".join(str(raw).split())
    if q.options and raw:
        if raw.isdigit() and 1 <= int(raw) <= len(q.options):
            return q.options[int(raw) - 1]
        if len(raw) == 1 and raw.upper().isalpha() and ord(raw.upper()) - 65 < len(q.options):
            return q.options[ord(raw.upper()) - 65]
        for o in q.options:
            if o.casefold() == raw.casefold():
                return o
    return raw


REASK_WINDOW_SECONDS = 12 * 3600   # bu süre içinde cevaplanmış benzer soru "tekrar" sayılır
REASK_MIN_SIMILARITY = 0.6         # kelime kümesi Jaccard benzerliği eşiği
TOUR_MAX_ITEMS = 8                  # bir turda en çok bu kadar madde (büyük prompt beynin giriş kutusunda takılıyordu); kalanı sonraki tura
ROUTINE_ESCALATE_SECONDS = 30 * 60   # beyin bu sürede rutin soruyu cevaplamazsa soru sahibine (telefon) düşer
REASK_MAX_REPEATS = 2              # aynı cevap en çok bu kadar yeniden iletilir, sonra soru gerçekten açılır
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _words(text: str) -> set:
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) > 2}


def find_answered_duplicate(questions: List["Question"], project: str, text: str,
                            now: Optional[float] = None) -> Optional["Question"]:
    """Aynı projede, son `REASK_WINDOW_SECONDS` içinde cevaplanmış ve `text`e kelime düzeyinde çok benzeyen soru
    (en benzeri); yoksa None."""
    now = _now() if now is None else now
    mine = _words(text)
    if not mine:
        return None
    best, best_sim = None, 0.0
    for q in questions:
        if q.status != "answered" or q.project != project or not q.answered_at:
            continue
        if now - q.answered_at > REASK_WINDOW_SECONDS:
            continue
        if "anlamad" in q.answer.lower() or "understand" in q.answer.lower():
            continue   # "anlamadım, ayrıntılı sor" = sahibi yeniden sorulmasını istedi
        theirs = _words(q.text)
        if not theirs:
            continue
        sim = len(mine & theirs) / len(mine | theirs)
        if sim >= REASK_MIN_SIMILARITY and sim > best_sim:
            best, best_sim = q, sim
    return best


def recent_answers(project: str, exclude_id: str = "", limit: int = 5,
                   questions: Optional[List["Question"]] = None, paths: Any = None) -> List["Question"]:
    """Projenin en son `limit` cevaplanmış sorusu (eskiden yeniye); `exclude_id` hariç."""
    qs = [q for q in (questions if questions is not None else load_questions(paths))
          if q.status == "answered" and q.project == project and q.id != exclude_id and q.answer.strip()]
    qs.sort(key=lambda q: q.answered_at)
    return qs[-limit:]


def add_question(project: str, text: str, source: str = "", options: Any = None, routine: bool = False,
                 paths: Any = None) -> Question:
    text = str(text).strip()[:_MAX_QUESTION_CHARS]
    if not text:
        raise ValueError("empty question")
    questions = load_questions(paths)
    # Oturum yakın zamanda cevaplanmış bir soruyu yeniden sordu: yeni soru açma, cevabı "zaten cevapladım"
    # notuyla yeniden ilet (üst sınırdan sonra gerçekten yeni soru say; sonsuz döngü olmasın).
    dup = find_answered_duplicate(questions, project, text)
    if dup is not None and dup.repeats < REASK_MAX_REPEATS:
        dup.repeats += 1
        dup.delivered_at = 0.0
        save_questions(questions, paths)
        return dup
    # Aynı projeden AYNI metinle açık bir soru varsa ikinci kez açma (işaret taraması her
    # tick aynı yanıtı görebilir; motor `seen` ile de korur ama depo kendi başına da dayanıklı olsun).
    for q in questions:
        if q.status == "open" and q.project == project and q.text == text:
            return q
    q = Question(id=_new_id("q"), project=project, text=text, created_at=_now(), source=source,
                 options=normalize_options(options), key=secrets.token_hex(8), routine=bool(routine))
    questions.append(q)
    save_questions(questions, paths)
    return q


def answer_question(question_id: str, answer: str, paths: Any = None) -> Optional[Question]:
    answer = str(answer).strip()
    if not answer:
        raise ValueError("empty answer")
    questions = load_questions(paths)
    for q in questions:
        if q.id == question_id:
            q.answer = resolve_answer(q, answer)[:_MAX_QUESTION_CHARS]
            q.status = "answered"
            q.answered_at = _now()
            q.delivered_at = 0.0
            save_questions(questions, paths)
            return q
    return None


def find_question(question_id: str, paths: Any = None) -> Optional[Question]:
    return next((q for q in load_questions(paths) if q.id == question_id), None)


def mark_notified(question_id: str, paths: Any = None) -> None:
    questions = load_questions(paths)
    for q in questions:
        if q.id == question_id:
            q.notified_at = _now()
    save_questions(questions, paths)


def question_link(q: Question, base: str) -> str:
    """Telefon sayfası: `<base>/q/<id>?k=<key>`. `base` boşsa (tünel yok) ya da soru anahtarsızsa (eski kayıt) ""."""
    base = (base or "").rstrip("/")
    return f"{base}/q/{q.id}?k={q.key}" if base and q.key else ""


def question_notification(q: Question, link: str, lang: str = "tr") -> str:
    """ntfy gövdesi: `[proje] soru`, numaralı seçenekler, sonra bağlantı ya da (yoksa) CLI ipucu."""
    lines = [f"[{q.project or 'degnekci'}] {q.text}"]
    lines += [f"{i}) {o}" for i, o in enumerate(q.options, 1)]
    if link:
        lines.append(("→ cevapla: " if lang != "en" else "→ answer: ") + link)
    else:
        lines.append(f"→ py/cops steward answer {q.id} \"...\"")
    return "\n".join(lines)


_QPAGE_TXT = {
    "tr": {"title": "Değnekçi sorusu", "project": "Proje", "asked": "Soruldu", "free": "ya da yaz…", "send": "Gönder",
           "done": "Cevap kaydedildi", "deliver": "Motor bir sonraki turda ilgili oturuma iletir.",
           "already": "Bu soru zaten cevaplanmış", "missing": "Böyle bir soru yok", "denied": "Bağlantı geçersiz",
           "empty": "Boş cevap gönderilemez", "by": "kaynak", "opts_hint": "Birine dokun ya da aşağıya yaz."},
    "en": {"title": "Steward question", "project": "Project", "asked": "Asked", "free": "or type…", "send": "Send",
           "done": "Answer saved", "deliver": "The engine delivers it to the session on its next tick.",
           "already": "This question was already answered", "missing": "No such question", "denied": "Invalid link",
           "empty": "An empty answer cannot be sent", "by": "source", "opts_hint": "Tap one or type below."},
}

_QPAGE_CSS = (
    "body{font:17px/1.45 -apple-system,system-ui,sans-serif;margin:0;padding:1rem;background:#f6f6f4;color:#1b1b1b}"
    "@media(prefers-color-scheme:dark){body{background:#151618;color:#e8e8e6}.card{background:#1f2124!important;"
    "border-color:#33363a!important}input{background:#151618;color:#e8e8e6;border-color:#44474c!important}}"
    ".card{max-width:34rem;margin:0 auto;background:#fff;border:1px solid #ddd;border-radius:12px;padding:1rem}"
    "h1{font-size:.85rem;letter-spacing:.04em;text-transform:uppercase;opacity:.6;margin:0 0 .4rem}"
    ".q{font-size:1.15rem;margin:0 0 .8rem;white-space:pre-wrap}.meta{font-size:.8rem;opacity:.6;margin-bottom:.8rem}"
    ".opt{display:block;width:100%;box-sizing:border-box;font:inherit;font-size:1.05rem;padding:.8rem 1rem;margin:.4rem 0;"
    "border:1px solid #4a7;border-radius:10px;background:#e9f7ee;color:inherit;text-align:left;cursor:pointer}"
    "@media(prefers-color-scheme:dark){.opt{background:#1d3327;border-color:#3f8a5c}}"
    ".row{display:flex;gap:.5rem;margin-top:.8rem}input{flex:1;min-width:0;font:inherit;padding:.7rem .8rem;border:1px solid #bbb;border-radius:10px}"
    ".send{font:inherit;padding:.7rem 1rem;border:1px solid #666;border-radius:10px;background:transparent;color:inherit}"
    ".ok{color:#2a7;font-weight:600}.err{color:#c33}.ans{font-size:1.1rem;margin:.6rem 0;white-space:pre-wrap}"
)


def question_page_html(q: Optional[Question], lang: str = "tr", state: str = "ask", error: str = "",
                       action: str = "") -> str:
    """`/q/<id>` kompakt mobil sayfası (SAF, inline CSS, JS yok): `state` ask (seçenek düğmeleri + serbest metin
    formu) | done (cevap kaydedildi) | already (daha önce cevaplanmış) | missing | denied. Form `action`a POST eder
    (`answer` alanı: düğmenin değeri ya da metin kutusu)."""
    T = _QPAGE_TXT["en" if lang == "en" else "tr"]
    esc = html.escape
    body: List[str] = [f"<h1>{T['title']}</h1>"]
    if q is None or state in ("missing", "denied"):
        body.append(f"<p class='err'>{T['missing'] if state != 'denied' else T['denied']}</p>")
    else:
        body.append(f"<p class='q'>{esc(q.text)}</p>")
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(q.created_at)) if q.created_at else ""
        body.append(f"<p class='meta'>{T['project']}: <b>{esc(q.project or 'degnekci')}</b> · {T['asked']}: {when}"
                    + (f" · {T['by']}: {esc(q.source)}" if q.source else "") + "</p>")
        if state in ("done", "already"):
            body.append(f"<p class='ok'>{T['done'] if state == 'done' else T['already']}</p>")
            body.append(f"<p class='ans'>→ {esc(q.answer)}</p>")
            if state == "done":
                body.append(f"<p class='meta'>{T['deliver']}</p>")
        else:
            if error:
                body.append(f"<p class='err'>{esc(error)}</p>")
            body.append(f"<form method='post' action='{esc(action, quote=True)}'>")
            if q.options:
                body.append(f"<p class='meta'>{T['opts_hint']}</p>")
                for o in q.options:
                    body.append(f"<button class='opt' type='submit' name='answer' value='{esc(o, quote=True)}'>{esc(o)}</button>")
            body.append(f"<div class='row'><input name='answer' placeholder='{esc(T['free'], quote=True)}' autocomplete='off'>"
                        f"<button class='send' type='submit'>{T['send']}</button></div></form>")
    return ("<!doctype html><html lang='" + ("en" if lang == "en" else "tr") + "'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><meta name='robots' content='noindex'>"
            f"<title>{T['title']}</title><style>{_QPAGE_CSS}</style></head><body><div class='card'>"
            + "".join(body) + "</div></body></html>")


def escalate_routine(question_id: str, paths: Any = None) -> Optional[Question]:
    """Cevapsız kalan rutin soruyu sahibine açık soruya çevir (`routine` kalkar; bildirim çağıranda)."""
    questions = load_questions(paths)
    hit = None
    for q in questions:
        if q.id == question_id and q.status == "open" and q.routine:
            q.routine = False
            hit = q
    if hit is not None:
        save_questions(questions, paths)
    return hit


def mark_delivered(question_id: str, paths: Any = None) -> None:
    questions = load_questions(paths)
    for q in questions:
        if q.id == question_id:
            q.delivered_at = _now()
    save_questions(questions, paths)


def open_questions(questions: Optional[List[Question]] = None, paths: Any = None) -> List[Question]:
    return [q for q in (questions if questions is not None else load_questions(paths)) if q.status == "open"]


def undelivered_answers(questions: Optional[List[Question]] = None, paths: Any = None) -> List[Question]:
    return [q for q in (questions if questions is not None else load_questions(paths))
            if q.status == "answered" and not q.delivered_at]


def load_state(paths: Any = None) -> Dict[str, Any]:
    st = _load_json(_pp(paths).state, {})
    return st if isinstance(st, dict) else {}


def save_state(state: Dict[str, Any], paths: Any = None) -> None:
    _save_json(_pp(paths).state, state)


_LOG_LOCK = threading.Lock()   # ekleme (tick/kart thread'leri) ile sıkıştırma/rotasyon (özet anı) çakışmasın
LOG_MAX_BYTES = 5 * 1024 * 1024   # `rotate_log`: dosya bunu aşınca `log.jsonl.1`e devrilir (tek nesil)
SUMMARY_CATCHUP_DAYS = 3          # açılışta geriye en çok bu kadar günün kaçan özeti üretilir


def log_event(event: str, *, paths: Any = None, **data: Any) -> None:
    """Append-only JSONL — `diaglog.diag_log` ile aynı best-effort disiplin."""
    try:
        pp = _pp(paths)
        os.makedirs(os.path.dirname(pp.log), exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **data}
        with _LOG_LOCK, open(pp.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _rewrite_log(lines: List[str], paths: Any = None) -> None:
    log = _pp(paths).log
    tmp = log + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.replace(tmp, log)


def compact_log(date: str, paths: Any = None) -> int:
    """O günün (`YYYY-MM-DD`) `tick` satırlarını (günde ~720: her 2 dakikada bir) TEK bir `ticks` satırına katla:
    `{"ts": "<date>T23:59:59", "event": "ticks", "n", "manual", "errors", "mode"}`. Günlük özet yazıldıktan SONRA
    çağrılır; `daily_summary` bu toplamı sayar, dolayısıyla o günün özeti sıkıştırmadan sonra da AYNI çıkar. Diğer
    olaylar (eylem, soru, kart, özet...) yerinde kalır. Dönen: katlanan tick sayısı (0 = dosyaya dokunulmadı)."""
    with _LOG_LOCK:
        try:
            with open(_pp(paths).log, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return 0
        agg = {"n": 0, "manual": 0, "errors": 0, "mode": ""}
        out: List[str] = []
        placed = False
        agg_line = lambda: json.dumps({"ts": f"{date}T23:59:59", "event": "ticks", **agg}, ensure_ascii=False) + "\n"  # noqa: E731
        for ln in lines:
            ts = ln[8:27] if ln.startswith('{"ts": "') else ""
            if ts.startswith(date) and '"event": "tick"' in ln:
                try:
                    e = json.loads(ln)
                except json.JSONDecodeError:
                    out.append(ln)
                    continue
                agg["n"] += 1
                agg["manual"] += 1 if e.get("trigger") != "timer" else 0
                agg["errors"] += 1 if e.get("error") else 0
                agg["mode"] = str(e.get("mode") or agg["mode"])
                continue
            if agg["n"] and not placed and ts and ts[:10] > date:
                out.append(agg_line())      # o günün sonu: toplam satırı sonraki günün ilk kaydından ÖNCE
                placed = True
            out.append(ln)
        if not agg["n"]:
            return 0
        if not placed:
            out.append(agg_line())
        _rewrite_log(out, paths)
        return int(agg["n"])


def rotate_log(max_bytes: int = LOG_MAX_BYTES, paths: Any = None) -> bool:
    """`log.jsonl` `max_bytes`ı aşınca `log.jsonl.1`e devir (öncekinin üstüne; tek nesil yeter: günlük özetler
    `daily/`de duruyor). Dönen: devrildi mi."""
    with _LOG_LOCK:
        try:
            log = _pp(paths).log
            if os.path.getsize(log) <= max_bytes:
                return False
            os.replace(log, log + ".1")
            return True
        except OSError:
            return False


def tail_log(n: int = 50, paths: Any = None) -> List[Dict[str, Any]]:
    try:
        with open(_pp(paths).log, encoding="utf-8") as f:
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

def card_path(name: str, paths: Any = None) -> str:
    return os.path.join(_pp(paths).cards, f"{name}.json")


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


def load_card(name: str, paths: Any = None) -> Optional[Dict[str, Any]]:
    d = _load_json(card_path(name, paths), None)
    return d if isinstance(d, dict) else None


def save_card(name: str, card: Dict[str, Any], paths: Any = None) -> None:
    _save_json(card_path(name, paths), card)


def load_cards(paths: Any = None) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    try:
        names = os.listdir(_pp(paths).cards)
    except OSError:
        return out
    for fn in sorted(names):
        if fn.endswith(".json") and valid_name(fn[:-5]):
            c = load_card(fn[:-5], paths)
            if c is not None:
                out[fn[:-5]] = c
    return out


def mark_card_stale(name: str, paths: Any = None) -> bool:
    """Oturum yeniden açıldı (handover sonrası) -> kart bir sonraki fırsatta yenilensin. Kart yoksa no-op."""
    card = load_card(name, paths)
    if card is None or card.get("stale"):
        return False
    card["stale"] = True
    save_card(name, card, paths)
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


def note_card_failure(name: str, source_hash: str, error: str, now: Optional[float] = None,
                      paths: Any = None) -> None:
    """Var olan kartı bozmadan başarısız denemeyi kaydet (`card_refresh_reason` geri çekilsin)."""
    card = load_card(name, paths)
    if card is None:
        return
    card.update({"attempt_hash": source_hash, "attempt_at": now if now is not None else _now(),
                 "last_error": _short(error, 300)})
    save_card(name, card, paths)


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
    out: Dict[str, Any] = {"asks": [], "routines": [], "ideas": [], "blocked": [], "plan_ready": False, "done": False}
    if not text:
        return out
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*• ").strip()
        if not line:
            continue
        for mark, key in ((MARK_ROUTINE, "routines"), (MARK_ASK, "asks"), (MARK_IDEA, "ideas"), (MARK_BLOCKED, "blocked")):
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
    f"- işleyiş sorusu (ne zaman açılsın, hangi sırayla, hangi modelle, devir notuyla mı): `{MARK_ROUTINE} <soru>`; "
    "bunu değnekçi beyni cevaplar, sana değil bana sorma. YALNIZ gerçek bir soru için ve soru işaretiyle bitir; "
    "'bekliyorum', 'bitti', 'yeni soru yok' gibi durum cümlesi için KULLANMA\n"
    f"- aklına bu projeyle ilgisiz yeni bir fikir gelirse: `{MARK_IDEA} <fikir>`\n"
    f"- takıldın, düşündün, çözemedin: `{MARK_BLOCKED} <nerede takıldın>`\n"
    "Kurallar: cevaplarım kısadır ('ikisi de', 'sıradan git', 'sen devam') ve KALICI kuraldır; aynı konuyu "
    "yeniden sorma. Cevap yetmiyorsa makul bir varsayılanla ilerle, varsayımını TOBEDECIDED.md'ye yaz. "
    "Aşağıdaki 'Önceki cevaplarım' listesi sana verdiğim kararlardır, onlara uy.\n"
)

_PROTOCOL_EN = (
    "Steward protocol (at the END of your reply, one per line, only when needed):\n"
    f"- a decision you cannot make without me: `{MARK_ASK} <one-sentence question>`\n"
    f"- a process question (when to reopen, which order, which model, with the handover note?): `{MARK_ROUTINE} <question>`; "
    "the steward brain answers it, not me\n"
    f"- a new idea unrelated to this project: `{MARK_IDEA} <idea>`\n"
    f"- stuck after thinking it through: `{MARK_BLOCKED} <where>`\n"
    "Rules: my answers are short ('both', 'go in order', 'you continue') and are STANDING rules; do not re-ask "
    "the same topic. If an answer is not enough, proceed with a sensible default and record the assumption in "
    "TOBEDECIDED.md. The 'My earlier answers' list below holds decisions I already gave you; follow them.\n"
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
        if answer.repeats:
            parts.append("Bunu zaten cevapladım, yukarıdaki cevap geçerli; yeniden sorma, devam et." if tr else
                         "I already answered this; the answer above stands. Do not ask again, continue.")
        prior = recent_answers(project.name, exclude_id=answer.id)
        if prior:
            parts.append(("Önceki cevaplarım:\n" if tr else "My earlier answers:\n") +
                         "\n".join(f"- {q.text.strip()[:140]} → {q.answer.strip()[:200]}" for q in prior))
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
            "steward_answer (RUTİN SORU: ne zaman/hangi sıra/hangi model gibi işleyiş sorusunu sen cevapla, bana sorma), "
            "steward_ask_user (benim kararım gerekiyor), steward_set_project (faz/öncelik/not), "
            "steward_idea_update (fikir: proje/sonra/çöp), steward_register_project (fikirden proje), "
            "steward_skip (bu tur dokunma). Kararsız kaldığında sor, ama sormadan verebileceğin kararı sorma."
        )
    else:
        lines.append(
            "For EACH item below decide and call the matching MCP tool (steward_project_context gives more context): "
            "steward_directive (next task), steward_restart (idle/wrong work → stop and reopen with a better directive, "
            "other model/effort if needed), steward_stop, steward_answer (ROUTINE QUESTION: answer process questions yourself, do not ask me), steward_ask_user (needs my decision), steward_set_project, "
            "steward_idea_update, steward_register_project, steward_skip. Ask when unsure, never ask what you can decide."
        )
    if open_qs:
        lines.append("")
        lines.append("Bana sorulmuş, hâlâ cevapsız sorular (tekrar sorma):" if tr else "Open questions already waiting on me (do not re-ask):")
        for q in [x for x in open_qs if not x.routine][:10]:
            lines.append(f"- [{q.id}] {q.project or '-'}: {_clip(q.text, 200)}")
    for n, it in enumerate(items, 1):
        lines.append("")
        kind = it.get("kind", "")
        name = it.get("name", "")
        label = {"idle": "BOŞTA" if tr else "IDLE", "review": "GÖZDEN GEÇİR" if tr else "REVIEW",
                 "idea": "FİKİR" if tr else "IDEA", "due": "SIRASI GELDİ" if tr else "DUE",
                 "blocked": "TAKILDI" if tr else "BLOCKED",
                 "routine": "RUTİN SORU" if tr else "ROUTINE QUESTION"}.get(kind, kind.upper())
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


MODEL_RULE_TR = (
    "\n## Model kuralı (sahibin KALICI kararı, 2026-10-20; pazarlık yok)\n"
    "- Proje ANA oturumu HER ZAMAN Sonnet 5.5 + medium. `steward_directive`/`steward_restart`/`steward_set_project` ile model/effort verirken "
    "ana oturumu Fable, Opus ya da high YAPMA; boş bırakma, `claude-sonnet-5-5` + `medium` yaz.\n"
    "- Ağır iş İŞE GÖRE ALT AJANDA, modeli direktife AÇIK yaz: araştırma/doğrulama/çekme = Sonnet; ilk taslak (bölüm, nesir, analiz) = Opus high "
    "(mekanik kısım: tablo, kaynakça, özet = Opus medium); Fable YALNIZ bitmiş işin son cilası/denetimi (tek geçiş, bir kez okuma).\n"
    "- Aynı anda en fazla 1 Fable ajanı; ajana yalnız gereken dosyaları okut (alt ajan bağlamı cache yazmayı şişirir). "
    "Direktifte \"Fable high ile yaz\" deme.\n"
    "- Sebep: Fable haftalık kotası hızla doluyor; token başına en pahalı model. Proje notunda eski bir model satırı bununla çelişirse BU KURAL geçerli.\n"
    "- İSTİSNA: sahibin bu kuraldan SONRA verdiği AÇIK bir model cevabı (ör. \"yazım Fable\") o iş için kuralı esnetir; onu uygula, kuralla "
    "\"netleştirme\" yapma. Kuraldan ÖNCE (2026-10-20 öncesi) verilmiş eski bir cevap kuralla çakışıyorsa sahibe `steward_ask_user` ile seçenekli yeniden sor, kendin ezme.\n"
)
MODEL_RULE_EN = (
    "\n## Model rule (owner's PERMANENT decision, 2026-10-20; not negotiable)\n"
    "- A project's MAIN session is ALWAYS Sonnet 5.5 + medium. When you pass model/effort via `steward_directive`/`steward_restart`/"
    "`steward_set_project`, never make the main session Fable, Opus or high; never leave it blank, write `claude-sonnet-5-5` + `medium`.\n"
    "- Heavy work goes to a SUB-AGENT chosen by task, with the model written EXPLICITLY in the directive: research/verification/fetching = Sonnet; "
    "first draft (chapter, prose, analysis) = Opus high (mechanical parts: tables, references, summaries = Opus medium); Fable ONLY for the final "
    "polish/audit of finished work (one pass, read once).\n"
    "- At most 1 Fable agent at a time; make the agent read only the files it needs. Never write \"write it with Fable high\" in a directive.\n"
    "- Why: the Fable weekly quota fills fast and it is the priciest model per token. If an old model line in a project note conflicts, THIS rule wins.\n"
    "- EXCEPTION: an EXPLICIT model answer the owner gives AFTER this rule (e.g. \"write it with Fable\") relaxes the rule for that job; apply it, "
    "do not \"clarify\" it away with the rule. If an older answer (given before 2026-10-20) conflicts with the rule, re-ask the owner with "
    "`steward_ask_user` and options; do not override it yourself.\n"
)


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
        "- `steward_answer id answer` — bir RUTİN SORU'yu (projenin işleyiş sorusu) cevapla; motor cevabı oturuma iletir. Karar sorularını (telif, harcama, commit/push) sahibine bırak\n"
        "- `steward_ask_user project question [options]` — bana soru (telefona bildirim gider, `options` verirsen "
        "(en çok 6 kısa seçenek: evet/hayır, A/B/C, sonra) tek dokunuşla cevaplarım; cevabı motor oturuma iletir)\n"
        "- `steward_note project text` — kendi notun (bir sonraki direktifte oturuma da gider)\n"
        "- `steward_idea text` / `steward_idea_update id status [project]` — fikir kutusu\n"
        "- `steward_questions` / `steward_log` — açık sorular / son olaylar\n"
        "- `steward_skip name reason` — bu tur dokunmuyorum (kayda geçer)\n"
        "\n`steward_overview` içindeki `config.mode` `observe` ise `steward_directive`/`steward_restart`/`steward_stop`/"
        "`steward_handover` KAYDA geçer ama UYGULANMAZ (yanıtta `dry: true`); soru, fikir, faz/not değişikliği çalışır. "
        "Kararını yine ver: sahibi `would:` kayıtlarından neyi yapacağını görüp güven kazandırır.\n"
        if tr else
        "## Your tools (MCP `cops-steward`)\n"
        "- `steward_overview`, `steward_project_context name`, `steward_read_file name path`\n"
        "- `steward_directive`, `steward_restart`, `steward_handover`, `steward_stop`\n"
        "- `steward_set_project`, `steward_register_project`, `steward_ask_user`, `steward_note`\n"
        "- `steward_idea`, `steward_idea_update`, `steward_questions`, `steward_log`, `steward_skip`\n"
        "\nWhen `config.mode` in `steward_overview` is `observe`, `steward_directive`/`steward_restart`/`steward_stop`/"
        "`steward_handover` are recorded but NOT applied (`dry: true` in the reply); questions, ideas and phase/note "
        "changes still work. Decide anyway: the owner reads the `would:` records to learn what you would do.\n"
    )
    tail = (
        f"\n## Tur protokolü\nHer tur prompt'unda listelenen her madde için bir araç çağır; bitince yanıtını tek başına "
        f"`{MARK_END}` satırıyla kapat. Araç çağırmadan verilen karar KAYDA GEÇMEZ.\n"
        if tr else
        f"\n## Tour protocol\nCall one tool per listed item; finish with a line containing only `{MARK_END}`. "
        "A decision without a tool call is not recorded.\n"
    )
    return persona.rstrip() + "\n\n" + tools + (MODEL_RULE_TR if tr else MODEL_RULE_EN) + tail


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
    for q in questions:
        if q.status == "open" and q.routine:
            items.append({"kind": "routine", "name": q.project or "-", "id": q.id,
                          "text": f"Rutin soru [{q.id}] (steward_answer id cevap ile cevapla): {q.text}"})
    for q in undelivered_answers(questions):
        if not q.project or q.project == cfg.brain_name or q.project not in projects:
            items.append({"kind": "blocked", "name": q.project or "-", "id": q.id,
                          "text": f"Cevaplanan soru [{q.id}]: {q.text}\nCevap: {q.answer}"})
    return items


def _project_key(name: str, projects: Dict[str, "Project"]) -> str:
    """Oturum adı → kayıtlı proje adı (tam ad ya da en uzun proje-adı öneki: `ncs20261019` → `ncs`); yoksa ""."""
    best = ""
    for p in projects:
        if (name == p or name.startswith(p)) and len(p) > len(best):
            best = p
    return best


def _sibling_running(views: List[SessionView], name: str, projects: Dict[str, "Project"], cfg: "Config") -> bool:
    """`name`in projesinin BAŞKA bir çalışan oturumu var mı (beyin sayılmaz, kayıtsız proje = hayır)."""
    key = _project_key(name, projects)
    if not key:
        return False
    return any(x.running and x.name != name and x.name != cfg.brain_name and _project_key(x.name, projects) == key
               for x in views)


def pick_delivery_view(views: List[Any], project: str, source: str = "") -> Optional[Any]:
    """Cevabın gideceği çalışan oturum. Projenin birden çok açık oturumu olabilir (deneme `_1`, `_2`...):
    önce soruyu açan oturum (`source`), sonra adı projeyle başlayan en kısa/eski ad (ana oturum), son çare ilk bulunan."""
    mine = [x for x in views if x.running and x.project == project]
    if not mine:
        return None
    for x in mine:
        if source and x.name == source:
            return x
    return sorted(mine, key=lambda x: (len(x.name), x.name))[0]


def context_threshold(cfg: "Config", model: str) -> int:
    """Bu modelde handover'ı tetikleyen bağlam token eşiği (0 = kapalı). Fable daha pahalıdır: ayrı, genelde düşük eşik."""
    if "fable" in (model or "").lower() and cfg.context_warn_tokens_fable and cfg.context_warn_tokens:
        return min(cfg.context_warn_tokens_fable, cfg.context_warn_tokens)
    return cfg.context_warn_tokens


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
    def _managed(name: str) -> bool:
        # Oturum ekonomisi (handover/yeniden açma) YALNIZ değnekçinin yönettiği oturumlara: beyin + kayıtlı proje
        # oturumları. Kullanıcının diğer oturumlarına (egyptian.., oa.., cops..) mesaj gönderilmez, yeniden açılmaz.
        return name == cfg.brain_name or bool(_project_key(name, projects))

    for v in views:
        if not v.running or not v.tmux or not _managed(v.name):
            continue
        if v.name in ho_pending:
            continue
        # Bağlam token'ı BİLİNİYORSA (claude transkripti) tek ölçüt odur: satır sayısı tmux ekranını yansıtır,
        # bağlamı değil (uzun çıktıda dakikada ~80 satır; yeni açılan oturum 7 dk'da eşiğe varıp devri döngüye sokuyordu).
        # Token bilinmiyorsa (claude dışı CLI, henüz tur yapmamış oturum) ya da eşik kapalıysa satır sayısı YEDEK ölçüt;
        # o da yeni açılmış oturumda tetiklemez (`history_min_age_minutes`).
        warn_tokens = context_threshold(cfg, v.model)
        tokens_known = bool(warn_tokens and v.context_tokens)
        if tokens_known:
            if v.context_tokens >= warn_tokens:
                actions.append(Action("handover", v.name, f"context {v.context_tokens} token >= {warn_tokens}"))
                ho_pending[v.name] = now
                busy_names.add(v.name)
        elif v.history_size is not None and v.history_size >= cfg.history_warn_at:
            young = (cfg.history_min_age_minutes and v.started_at
                     and (now - v.started_at) < cfg.history_min_age_minutes * 60)
            if not young:
                actions.append(Action("handover", v.name, f"history_size {v.history_size} >= {cfg.history_warn_at}"))
                ho_pending[v.name] = now
                busy_names.add(v.name)

    # 2) Handover gönderilmiş olanlar — READY FOR HANDOVER geldi ya da süre doldu → yeniden aç
    for name, sent_at in list(ho_pending.items()):
        if not _managed(name):
            ho_pending.pop(name, None)   # yönetilmeyen oturum (eski kayıt/elle): yeniden AÇILMAZ
            continue
        if name in busy_names:
            continue
        v = by_name.get(name)
        if v is None or not v.running:
            if not _sibling_running(views, name, projects, cfg):
                actions.append(Action("respawn", name, "handover sent, session gone → start"))
            ho_pending.pop(name, None)
            busy_names.add(name)
            continue
        ready = READY_FOR_HANDOVER in (v.last_assistant or "")
        expired = (now - float(sent_at)) >= cfg.ho_grace_minutes * 60
        # busy None (bu CLI'da sinyal yok) = "meşgul değil" sayılır; yalnız kesin True bekletir
        if v.busy is not True and (ready or expired):
            if _sibling_running(views, name, projects, cfg):
                # Aynı projenin başka oturumu çalışıyor: devri biten ikinci oturum yeniden AÇILMAZ, kapanır
                # (proje başına tek canlı oturum; her oturum kendi bağlamını her turda yeniden okur).
                actions.append(Action("stop", name, "devir bitti, projenin başka oturumu çalışıyor → kapat"))
            else:
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
        for q in m["routines"]:
            if "?" not in q:
                continue   # "bekliyorum, yeni soru yok" gibi durum cümlesi soru değil: kayda da girmez, sahibine de gitmez
            actions.append(Action("ask_user", v.name, "STEWARD-ROUTINE",
                                  {"project": proj or v.name, "text": q, "routine": True}))
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
        if not target or target == cfg.brain_name:
            # Genel/beyin sorusu: beyin turunda gösterilir (aşağıda), oturuma iletilmez
            continue
        if target not in projects:
            # Kayıtlı proje olmayan (ad hoc) oturumun sorusu: cevap, soruyu açan oturum hâlâ çalışıyorsa ona gider
            # (eskiden sessizce iletilmiyordu: sahibi cevap yazıyor, oturum hiç görmüyordu); çalışmıyorsa beklemez, atlanır.
            v = next((x for x in views if x.running and x.name == q.source and x.name != cfg.brain_name), None)
            if v is not None and v.name not in busy_names and not v.busy:
                actions.append(Action("deliver_answer", v.name, "answer", {"question_id": q.id}))
                busy_names.add(v.name)
                last_directive_at[v.name] = now
            continue
        v = pick_delivery_view(views, target, q.source)
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

    # 5) Uğrama sırası — çalışmayan, aktif fazdaki, süresi dolmuş projeler.
    # observe kipinde `start` uygulanmaz, `last_visit` hiç ilerlemez: `observed_visit` (bkz. `observe_filter`)
    # "uğranmış gibi" davranmayı sağlar, yoksa her tick aynı en öncelikli proje için `would:start` üretirdi.
    observed_visit: Dict[str, float] = dict(st.get("observed_visit") or {})
    visit_of = lambda p: max(p.last_visit, float(observed_visit.get(p.name) or 0.0))   # noqa: E731
    due: List[Project] = []
    for p in projects.values():
        if p.phase not in ACTIVE_PHASES or p.cadence_minutes <= 0 or p.name in running_projects or p.name in busy_names:
            continue
        if visit_of(p) == 0 or (now - visit_of(p)) >= p.cadence_minutes * 60:
            due.append(p)
    due.sort(key=lambda p: (p.priority, visit_of(p)))
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

    # 6b) Beynin cevaplamadığı rutin soru sahibine düşer (sessizce takılı kalmasın)
    for q in questions:
        if q.status == "open" and q.routine and (now - q.created_at) >= ROUTINE_ESCALATE_SECONDS:
            actions.append(Action("escalate_routine", q.project or "-", "rutin soru cevapsız", {"question_id": q.id}))

    # 7) Beyin turu maddeleri
    items = review_items(views, projects, cfg, now, questions, ideas,
                         skip=busy_names | set(ho_pending), last_directive_at=last_directive_at, reviewed_at=reviewed_at)
    last_tour = float(st.get("last_tour") or 0.0)
    brain = by_name.get(cfg.brain_name)
    if items and (now - last_tour) >= cfg.tour_minutes * 60 and brain is not None and brain.running and brain.busy is False:
        items = items[:TOUR_MAX_ITEMS]
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


def observe_filter(actions: List[Action], mode: str, state: Dict[str, Any], now: float
                   ) -> Tuple[List[Action], List[Action], Dict[str, Any]]:
    """`plan_tick`in eylemlerini kipe göre ayır: (uygulanacak, kuru/`would:`, güncellenmiş state). SAF.

    `act`: hepsi uygulanır, observe izleri (`observed`, `observed_visit`) silinir.
    `observe`: `OBSERVE_SKIPPED` türleri uygulanmaz; aynı (tür, ad, soru) anahtarı `OBSERVE_DEDUP_SECONDS` içinde
    bir kez raporlanır — eylem hiç uygulanmadığı için durum (cevaplanmış ama iletilmemiş soru, eşik üstü scrollback)
    değişmez ve plan_tick her tick aynısını üretirdi. Uğrama (`start`, soru dışı) `observed_visit`e yazılır ki
    sıradaki projeler de görünsün (bkz. plan_tick adım 5)."""
    st = dict(state)
    if mode != "observe":
        st.pop("observed", None)
        st.pop("observed_visit", None)
        return list(actions), [], st
    seen: Dict[str, float] = {k: float(v) for k, v in (st.get("observed") or {}).items()
                              if now - float(v) < OBSERVE_DEDUP_SECONDS}
    visits: Dict[str, float] = dict(st.get("observed_visit") or {})
    apply: List[Action] = []
    dry: List[Action] = []
    for a in actions:
        if a.kind not in OBSERVE_SKIPPED:
            apply.append(a)
            continue
        if a.kind == "start" and not a.payload.get("question_id"):
            visits[a.name] = now
        key = f"{a.kind}:{a.name}:{a.payload.get('question_id', '')}"
        if key in seen:
            continue
        seen[key] = now
        dry.append(a)
    st["observed"] = seen
    st["observed_visit"] = visits
    return apply, dry, st


# ── günlük özet ───────────────────────────────────────────────────────────────

def daily_path(date: str, paths: Any = None) -> str:
    return os.path.join(_pp(paths).daily, f"{date}.md")


def log_entries_for_date(date: str, paths: Any = None) -> List[Dict[str, Any]]:
    """`log.jsonl`'dan o güne (`YYYY-MM-DD`, yerel) ait kayıtlar; dosyayı satır satır okur (bütününü belleğe almaz)."""
    out: List[Dict[str, Any]] = []
    try:
        with open(_pp(paths).log, encoding="utf-8") as f:
            for ln in f:
                if f'"ts": "{date}' not in ln[:40]:
                    continue
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


def summary_due(state: Dict[str, Any], now: float, hour: int) -> str:
    """Bugünün (yerel) günlük özeti yazılmalı mı: saat `hour`u geçtiyse ve bugün henüz yazılmadıysa tarih, yoksa ""."""
    lt = time.localtime(now)
    today = time.strftime("%Y-%m-%d", lt)
    return today if lt.tm_hour >= hour and state.get("summary_date") != today else ""


def missed_summary_dates(now: float, days: int = SUMMARY_CATCHUP_DAYS, paths: Any = None) -> List[str]:
    """Özeti KAÇMIŞ geçmiş günler (eskiden yeniye): bugün hariç son `days` günden `daily/<tarih>.md`si olmayan ve
    `log.jsonl`'da kaydı bulunanlar. `summary_hour`da panel kapalıysa o gün özetlenmezdi (TODO 2026-10-19 (6d));
    açılıştan sonraki ilk tick bunları tamamlar. Kaydı olmayan gün (döngü kapalıydı) özetlenmez: boş özet gitmesin."""
    out: List[str] = []
    for back in range(max(0, days), 0, -1):
        date = time.strftime("%Y-%m-%d", time.localtime(now - back * 86400))
        if os.path.isfile(daily_path(date, paths)):
            continue
        if log_entries_for_date(date, paths):
            out.append(date)
    return out


_SUMMARY_TXT = {
    "tr": {
        "title": "Değnekçi günlük özet", "mode": "Mod", "obs_note": "oturuma dokunan eylemler uygulanmadı, yalnız kaydedildi",
        "ticks": "Tick", "manual": "elle", "errors": "hatalı", "no_ticks": "kayıt yok (döngü kapalıydı ya da panel çalışmıyordu)",
        "applied": "Uygulanan eylemler", "failed": "başarısız", "would": "Yapılacaktı (observe, uygulanmadı)",
        "questions": "Sorular", "opened": "açıldı", "answered": "cevaplandı", "ideas": "Fikirler", "new": "yeni",
        "cards": "Kartlar", "refreshed": "yenilendi", "handovers": "Handover", "directives": "Direktifler",
        "phases": "Faz değişimi", "pending": "Bekleyen", "open_q": "açık soru", "ideas_new": "yeni fikir",
        "items": "gözden geçirme maddesi", "undelivered": "iletilmemiş cevap", "none": "yok",
    },
    "en": {
        "title": "Steward daily summary", "mode": "Mode", "obs_note": "actions that touch sessions were recorded, not applied",
        "ticks": "Ticks", "manual": "manual", "errors": "with errors", "no_ticks": "none logged (loop was off or the panel was down)",
        "applied": "Actions applied", "failed": "failed", "would": "Would have done (observe, not applied)",
        "questions": "Questions", "opened": "opened", "answered": "answered", "ideas": "Ideas", "new": "new",
        "cards": "Cards", "refreshed": "refreshed", "handovers": "Handovers", "directives": "Directives",
        "phases": "Phase changes", "pending": "Pending", "open_q": "open questions", "ideas_new": "new ideas",
        "items": "review items", "undelivered": "undelivered answers", "none": "none",
    },
}


def _names(names: List[str], n: int = 5) -> str:
    uniq = list(dict.fromkeys(x for x in names if x))
    return ", ".join(uniq[:n]) + (f" +{len(uniq) - n}" if len(uniq) > n else "")


def _kind_counts(entries: List[Dict[str, Any]], key: str = "kind") -> str:
    c = Counter(str(e.get(key) or "?") for e in entries)
    return ", ".join(f"{k} {v}" for k, v in sorted(c.items()))


def daily_summary(entries: List[Dict[str, Any]], date: str, lang: str = "tr",
                  pending: Optional[Dict[str, int]] = None) -> str:
    """`log.jsonl` kayıtlarından (o güne ait olanlar süzülür) bir günün özeti — SAF, markdown. Sayılanlar: tick,
    uygulanan eylemler ve observe'da `would:` olanlar (türe göre), açılan/cevaplanan soru, fikir, yenilenen kart,
    handover, direktif, faz değişimi; `pending` (depodan: açık soru, yeni fikir, bekleyen madde, iletilmemiş cevap)."""
    T = _SUMMARY_TXT["en" if lang == "en" else "tr"]
    day = [e for e in entries if str(e.get("ts", "")).startswith(date)]
    ev = lambda name: [e for e in day if e.get("event") == name]   # noqa: E731
    ticks = ev("tick")
    folded = ev("ticks")            # `compact_log` sonrası: o günün tick'leri tek toplam satırında
    actions = ev("action")
    would = [e for e in day if str(e.get("event", "")).startswith("would:")]
    asks = [e for e in actions if e.get("kind") == "ask_user" and e.get("ok")] + ev("ask")
    ideas = [e for e in actions if e.get("kind") == "idea" and e.get("ok")] + ev("idea")
    cards = ev("card")
    phases = [e for e in actions if e.get("kind") == "set_phase" and e.get("ok")]
    handovers = [e for e in actions if e.get("kind") == "handover" and e.get("ok")] + ev("handover")
    applied = [e for e in actions if e.get("kind") not in ("ask_user", "idea", "set_phase")]
    mode = next((str(e.get("mode")) for e in reversed(ticks + folded) if e.get("mode")), "")
    n_ticks = len(ticks) + sum(int(e.get("n") or 0) for e in folded)

    lines = [f"# {T['title']} — {date}"]
    if mode:
        lines.append(f"{T['mode']}: **{mode}**" + (f" ({T['obs_note']})" if mode == "observe" else ""))
    lines.append("")
    if n_ticks:
        extra = []
        manual = sum(1 for e in ticks if e.get("trigger") != "timer") + sum(int(e.get("manual") or 0) for e in folded)
        bad = sum(1 for e in ticks if e.get("error")) + sum(int(e.get("errors") or 0) for e in folded)
        if manual:
            extra.append(f"{manual} {T['manual']}")
        if bad:
            extra.append(f"{bad} {T['errors']}")
        lines.append(f"- {T['ticks']}: {n_ticks}" + (f" ({', '.join(extra)})" if extra else ""))
    else:
        lines.append(f"- {T['ticks']}: {T['no_ticks']}")
    if applied:
        failed = sum(1 for e in applied if not e.get("ok"))
        lines.append(f"- {T['applied']}: {len(applied)} — {_kind_counts(applied)}" + (f" ({failed} {T['failed']})" if failed else ""))
    if would:
        per_kind = {}
        for e in would:
            per_kind.setdefault(str(e["event"]).split(":", 1)[1], []).append(str(e.get("name") or ""))
        parts = [f"{k} {len(v)}" + (f" ({_names(v)})" if _names(v) else "") for k, v in sorted(per_kind.items())]
        lines.append(f"- {T['would']}: {len(would)} — " + "; ".join(parts))
    answers = ev("answer")
    if asks or answers:
        lines.append(f"- {T['questions']}: {len(asks)} {T['opened']}, {len(answers)} {T['answered']}")
    if ideas:
        lines.append(f"- {T['ideas']}: {len(ideas)} {T['new']}")
    if cards:
        ok = [e for e in cards if e.get("ok")]
        bad = [e for e in cards if not e.get("ok")]
        lines.append(f"- {T['cards']}: {len(ok)} {T['refreshed']}" + (f" ({_names([str(e.get('name')) for e in ok])})" if ok else "")
                     + (f", {len(bad)} {T['failed']}" if bad else ""))
    if handovers:
        lines.append(f"- {T['handovers']}: {len(handovers)} ({_names([str(e.get('name')) for e in handovers])})")
    dirs = ev("directive")
    if dirs:
        lines.append(f"- {T['directives']}: {len(dirs)} ({_names([str(e.get('name')) for e in dirs])})")
    if phases:
        lines.append(f"- {T['phases']}: " + _names([f"{e.get('name')} ({e.get('reason')})" for e in phases], 8))
    if pending is not None:
        lines.append(f"- {T['pending']}: {pending.get('open_questions', 0)} {T['open_q']}, {pending.get('ideas_new', 0)} "
                     f"{T['ideas_new']}, {pending.get('pending_items', 0)} {T['items']}, "
                     f"{pending.get('undelivered_answers', 0)} {T['undelivered']}")
    return "\n".join(lines) + "\n"


def summary_text(date: Optional[str] = None, lang: str = "tr", paths: Any = None) -> str:
    """Depolardan (log, soru/fikir kutusu, state) `date`in (varsayılan: bugün) özetini kur."""
    date = date or time.strftime("%Y-%m-%d")
    state = load_state(paths)
    pending = {"open_questions": len(open_questions(paths=paths)),
               "ideas_new": sum(1 for i in load_ideas(paths) if i.status == "new"),
               "pending_items": int(state.get("pending_items") or 0),
               "undelivered_answers": len(undelivered_answers(paths=paths))}
    return daily_summary(log_entries_for_date(date, paths), date, lang, pending)


def write_daily(date: str, text: str, paths: Any = None) -> str:
    path = daily_path(date, paths)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return path


def summarize_projects(projects: Dict[str, Project]) -> Dict[str, int]:
    out = {ph: 0 for ph in PHASES}
    for p in projects.values():
        out[p.phase] = out.get(p.phase, 0) + 1
    return out
