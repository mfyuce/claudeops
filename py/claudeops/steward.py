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
import contextlib
import dataclasses
import fcntl
import glob
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
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from . import hosts as hosts_mod      # yaprak modül (yalnız paths'e bağlı): proje `host` doğrulaması
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
    # ── reviewer rolü (yalnız `paths_for` doldurur; `default` kökünde de türer ama kullanılmaz) ──
    reviews: str = ""          # <root>/reviews/<proje>/<mode>/<altmodel>/<ts>.md
    review_pool: str = ""      # review_pool.json (projects.json'a YAZILMAZ: ownership_index çakışması)
    review_history: str = ""   # review_history.json (çift durumları + son çalıştırmalar)
    findings: str = ""         # findings.json (bulgu yaşam döngüsü)


_SID_RE = re.compile(r"[a-z]+")   # yalnız harf: yol ayıracı/`..` ile `stewards/` dışına çıkılamaz (tam kimlik kuralı P2)


def paths_for(sid: str = "default") -> StewardPaths:
    """Yollar ÇAĞRI ANINDA türer. `default`: bugünkü düzen (`STEWARD_DIR` ve modül sabitleri, veri taşınmaz);
    diğer kimlikler `STEWARD_DIR/stewards/<sid>/`. `stewards/` asimetrisi yalnız burada."""
    sid = "default" if sid is None else sid
    if not isinstance(sid, str) or not _SID_RE.fullmatch(sid):
        raise ValueError(f"invalid steward id: {sid!r}")
    shared = dict(cards=os.path.join(STEWARD_DIR, "cards"), oneshot=os.path.join(STEWARD_DIR, "oneshot"))
    def _rv(root: str) -> Dict[str, str]:
        return dict(reviews=os.path.join(root, "reviews"), review_pool=os.path.join(root, "review_pool.json"),
                    review_history=os.path.join(root, "review_history.json"), findings=os.path.join(root, "findings.json"))
    if sid == "default":
        shared.update(_rv(STEWARD_DIR))
        return StewardPaths(sid=sid, root=STEWARD_DIR, projects=PROJECTS_JSON, ideas=IDEAS_JSON,
                            questions=QUESTIONS_JSON, state=STATE_JSON, log=LOG_JSONL,
                            jobs=os.path.join(STEWARD_DIR, "jobs.json"), workspace=WORKSPACE_DIR,
                            daily=os.path.join(STEWARD_DIR, "daily"), lock=os.path.join(STEWARD_DIR, ".lock"), **shared)
    r = os.path.join(STEWARD_DIR, "stewards", sid)
    shared.update(_rv(r))
    return StewardPaths(sid=sid, root=r, projects=os.path.join(r, "projects.json"), ideas=os.path.join(r, "ideas.json"),
                        questions=os.path.join(r, "questions.json"), state=os.path.join(r, "state.json"),
                        log=os.path.join(r, "log.jsonl"), jobs=os.path.join(r, "jobs.json"),
                        workspace=os.path.join(r, "workspace"), daily=os.path.join(r, "daily"),
                        lock=os.path.join(r, ".lock"), **shared)


def _pp(paths: Any = None) -> StewardPaths:
    """İsteğe bağlı `paths` argümanı: None = `default` (eski davranış), str = kimlik, StewardPaths = olduğu gibi."""
    return paths if isinstance(paths, StewardPaths) else paths_for("default" if paths is None else paths)
CARD_DOCS = ("STEWARD_BRIEF.md", "GOAL.md", "PLAN.md", "TODO.md", "TOBEDECIDED.md", "DONE.md")   # STEWARD_BRIEF.md: proje oturumunun güncel görev tarifi (parolasız); CLAUDE.md BİLEREK yok (parola içerebilir)
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
SUBAGENT_QUIET_SECONDS = 90.0    # alt ajan transkripti bu kadar sessizse bitmiş sayılır (cevap iletimi bekletilir)
OBSERVE_SKIPPED = ("auto_answer", "handover", "respawn", "start", "stop", "deliver_answer", "deliver_job", "deliver_lesson", "deliver_findings", "tour", "nudge")
OBSERVE_DEDUP_SECONDS = 6 * 3600   # aynı (tür, ad, soru) `would:` kaydı bu sürede bir kez yazılır

# Oturum yanıtlarında aranan işaretler — protokol/parse sözleşmesi, yerelleştirilmez
# (`orchestration.VERDICT_MARKER` ile aynı ilke). Proje oturumları MCP olmadan da
# değnekçiye bu satırlarla konuşur.
MARK_END = "COPS-STEWARD-END"          # beynin tur yanıtının sonu
MARK_ASK = "STEWARD-ASK:"              # insana soru (satırın kalanı soru metni)
MARK_IDEA = "STEWARD-IDEA:"            # yeni fikir
MARK_ROUTINE = "STEWARD-ROUTINE:"      # işleyiş sorusu (ne zaman/hangi sıra/hangi model): beyin cevaplar, sahibi rahatsız edilmez
MARK_BLOCKED = "STEWARD-BLOCKED:"      # takıldım (insana soru olarak düşer, önekli)
MARK_JOB = "STEWARD-JOB:"              # paylaşımlı servise iş isteği (<tür> [dosya...] [açıklama]): beyin steward_job_submit ile gönderir
JOB_REQUEST_PREFIX = "İŞ İSTEĞİ (STEWARD-JOB): "
MARK_PLAN_READY = "STEWARD-PLAN-READY"  # planlama bitti → faz planned
MARK_DONE = "STEWARD-DONE"             # proje bitti → faz done, oturum durur
NO_DONE_TAG = "NO-STEWARD-DONE"           # proje notunda: STEWARD-DONE işareti yok sayılır (sürekli geliştirme)
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
    host: str = ""                  # oturumun çalıştığı host (`hosts.json` adı); "" = yerel ("local" de yerele normalize edilir)


def normalize_host(host: Any) -> str:
    """Proje/istek host alanı: boşluk kırpılır, `local` (`hosts.LOCAL_HOST_NAME`) ve boş = "" (yerel). SAF."""
    h = str(host or "").strip()
    return "" if h in ("", hosts_mod.LOCAL_HOST_NAME) else h


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
    asked_again: int = 0            # AÇIK iken aynı proje/benzer metinle yeniden soruldu: yeni soru açılmadı, bu sayaç arttı


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
    subagent_active: bool = False       # transkriptin `subagents/agent-*.jsonl` dosyaları SUBAGENT_QUIET_SECONDS içinde yazıldı
    host: str = "local"                 # satırın geldiği host (`/api/status` `host` alanı); uzak = `hosts.json` adı
    subagent_unknown: bool = False      # alt ajan durumu okunamadı (uzak oturum): "boşta" SAYILMAZ (DONE/kapatma devri bekler)

    @property
    def project(self) -> str:
        return self.blueprint or self.name


@dataclass
class Action:
    kind: str       # handover | respawn | start | stop | directive | deliver_answer | deliver_job | deliver_lesson | deliver_findings | ask_user | idea
                    # | set_phase | tour | handover_deferred (yalnız kayıt: eşik devri ertelendi, oturuma dokunmaz)
    name: str = ""  # oturum/proje adı ("" = genel)
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    """`settings.steward_config()`'un döndürdüğü, tip-güvenli ayarlar (varsayılanlar burada tek yerde)."""
    enabled: bool = False
    tick_seconds: int = 120
    tour_minutes: int = 15
    tour_retry_minutes: int = 5     # beyin direktifi meşgul oturum yüzünden ertelendiyse bir sonraki tur bu kadar sonra
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
    auto_context_answer: bool = True    # "bu oturumda mı sürdüreyim, devirle mi" sorusunu motor bağlam ölçümüne bakıp kendisi cevaplar
    drain: bool = False                 # YENİ İŞ ALMA: oturum başlatma (uğrama/cevap-başlatma) ve beyin direktifi durur; çalışan iş, cevap iletimi, devir sürer
    auto_context_ratio: float = 0.7     # bağlam devir eşiğinin bu oranını aşmışsa cevap "önce devir" (altındaysa "bu oturumda sürdür")
    handover_force_ratio: float = 1.3   # eşik devri oturum meşgul/alt ajan çalışırken ERTELENİR; bağlam eşiğin bu katını aşarsa zorla (0 = oran tavanı yok)
    handover_defer_max_minutes: int = 30   # eşik devri en çok bu kadar ertelenir, sonra zorla (0 = erteleme kapalı: eski davranış)
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
    remote_actions: bool = False     # uzak host'taki proje oturumlarına eylem (kimlik başına, VARSAYILAN KAPALI). Açıkken
                                     # yalnız yıkıcı olmayanlar (devir/yönerge/cevap/iş/başlatma); stop/respawn uzakta red (A4)
    # ── çoklu değnekçi (P2) ──
    sid: str = "default"             # bu Config'in kimliği (`steward_config(sid)` doldurur)
    label: str = ""                  # panelde görünen ad
    persona_text: str = ""           # kimliğe özel persona ("" = ortak); default'unki `steward_persona_text`
    ntfy_topic: str = ""             # "" = ortak topic
    max_active_total: int = 6        # MAKİNE GENELİ (yalnız `steward` bloğu): tüm kimliklerde en çok etkin oturum; 0 = sınırsız
    max_starts_total: int = 1        # MAKİNE GENELİ: döngü turu başına tüm kimliklerde en çok başlatma
    # ── reviewer rolü (review.py; yalnız role="reviewer" kimliklerinde anlamlı) ──
    role: str = "steward"            # steward | reviewer | generic (generic: GENERIC_* varsayılanları + üst model kapısı)
    review_timeout_minutes: int = 45   # tek review çalıştırması bu sürede bitmezse iptal
    review_min_gap_minutes: int = 10   # iki review başlatması arası en az bekleme
    review_agy_models: str = ""      # virgülle ayrık agy model listesi ("" = çağıranın verdiği tümü)
    review_max_context_kib: int = 768  # Evren: `--max-context-kib` (ucli varsayılanı 256 uzun review'u düşürüyordu)
    review_max_compactions: int = 24   # Evren: `--max-compactions` (ucli varsayılanı 8)
    review_agy_allow: str = ""         # agy: izole HOME'da izinli salt-okunur komutlar ("" = ls,grep,head,tail,wc; "off" = izolasyon kapalı)
    review_agy_jail: bool = True       # agy: `bwrap` salt-okunur kafes + --dangerously-skip-permissions (bwrap yoksa/False ise izin listesi)
    lessons_project: str = "cli"       # ucli dersleri (reviewer `ucli-lessons.md`) bu projenin çalışan oturumuna direktifle iletilir (`off` = kapalı; boş değer ayarda anahtarı siler); projeyi bu kimlik yönetiyorsa
    advance_findings: bool = False     # İLERLETME değnekçisi: sahibin onayladığı (`exported`) review bulgularını KENDİ projelerinin çalışan oturumuna direktifle iletir (steward_advance.py)
    review_auto_verify: bool = False   # reviewer: `new` bulguları projenin çalışan oturumuna KENDİLİĞİNDEN doğrulatır (tick başına en çok 1 proje; oturum meşgulse bekler)
    review_auto_approve: int = 0       # reviewer: `verified` bulguyu KENDİLİĞİNDEN onaylar: 0 kapalı, 1 yalnız P3, 2 P2+P3 (P1, `unclear` ve parola/gizli geçen bulgu ASLA)
    review_max_tool_calls: int = 14    # Evren: `--max-tool-calls` (ucli varsayılanı 64; ölçüm: 14 ile 5 tur/297-416 sn, sınırsız 1453 sn)
    review_evren_models: str = ""    # virgülle ayrık Evren model listesi ("" = çağıranın verdiği tümü)
    review_claude_models: str = ""   # virgülle ayrık Anthropic model listesi (`claude -p`); "" = KAPALI (ayrı anahtar dosyası gerekir)
    review_codex_models: str = ""    # virgülle ayrık codex model listesi (`codex exec`, salt okunur sandbox); "" = KAPALI
    review_codex_effort: str = "low"   # codex `model_reasoning_effort` (config.toml'daki `max` review için gereksiz pahalı)
    review_copilot_models: str = ""  # virgülle ayrık Copilot model listesi (`copilot -p`); "" = KAPALI
    review_copilot_effort: str = "low"  # copilot `--reasoning-effort`
    review_evren_effort: str = "medium"  # Evren `--effort` (ucli: tavan yükseltilemezse `low` ile tek yeniden deneme YALNIZ görev effort gönderiyorsa çalışır; alanı reddeden modelde atlanır)
    review_claude_effort: str = "low"  # Anthropic review `--effort` (ölçüm 2026-10-23: haiku low en ucuz+geniş)


# Yalnız `settings.steward` bloğunda okunan makine geneli anahtarlar (`stewards.<sid>`'de görülürse yok sayılır).
MACHINE_KEYS = ("tick_seconds", "card_refresh", "card_cli", "card_model", "card_max_age_hours", "cards_per_tick",
                "max_active_total", "max_starts_total")

# Kimlik kuralı (K2): yalnız küçük harf (`session._NAME_RE` `degnekci_2`/`degnekci2`'yi `degnekci` tabanına indirger).
STEWARD_ID_RE = re.compile(r"^[a-z]{2,16}$")
ROLES = ("steward", "reviewer", "generic")
RESERVED_IDS = frozenset({"default", "all", "services", "service", "steward", "stewards"})
BRAIN_PREFIX = "degnekci"


def valid_custom_id(sid: str) -> bool:
    """`default` DIŞI bir kimlik için geçerli mi: `^[a-z]{2,16}$`, rezerve değil, beyin öneki (`degnekci*`) değil."""
    return (isinstance(sid, str) and bool(STEWARD_ID_RE.match(sid)) and sid not in RESERVED_IDS
            and not sid.startswith(BRAIN_PREFIX))


def valid_steward_id(sid: str) -> bool:
    """`default` (özel kimlik) ya da geçerli özel kimlik."""
    return sid == "default" or valid_custom_id(sid)


class ReviewerRefused(ValueError):
    """reviewer rolündeki kimlik projects.json'a yazamaz / proje devralamaz / devredemez (havuzu `review_pool.json`)."""


def reviewer_ids() -> frozenset:
    """Ayarda `stewards.<sid>.role == "reviewer"` olan kimlikler (`default` ASLA reviewer değildir). Ayar okunamazsa
    boş küme. `settings` tembel içe aktarılır (döngü yok)."""
    try:
        from .settings import load_settings
        st = load_settings().get("stewards")
    except Exception:
        return frozenset()
    return frozenset(k for k, v in (st.items() if isinstance(st, dict) else [])
                     if isinstance(v, dict) and valid_custom_id(k) and str(v.get("role") or "").strip() == "reviewer")


def is_reviewer(sid: Any) -> bool:
    """`sid` (str ya da StewardPaths) reviewer rolünde mi?"""
    s = sid.sid if isinstance(sid, StewardPaths) else ("default" if sid is None else sid)
    return s != "default" and s in reviewer_ids()


def brain_name_for(sid: str) -> str:
    """Beyin oturumunun adı: `default` -> `degnekci`, diğerleri `degnekci_<sid>`."""
    return BRAIN_PREFIX if sid == "default" else f"{BRAIN_PREFIX}_{sid}"


def steward_title(sid: str, role: str, session: str = "") -> str:
    """History başlığı (TEK kaynak): beyin -> `değnekçi · <sid> · beyin`; yönetilen proje oturumu ->
    `<oturum adı> (değnekçi: <sid>)`."""
    if role == "brain":
        return f"değnekçi · {sid} · beyin"
    return f"{session} (değnekçi: {sid})"


def steward_badge(name: str, index: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """SAF. Oturum/instance adı için History rozeti: beyin (`index["brains"]` ya da `degnekci*`) ya da bir değnekçinin
    sahip olduğu proje oturumu (`_project_key` önek eşler: `ncs20261019` -> `ncs`); değilse None.
    Dönüş `{kind: "steward", role: brain|project, sid, title}`."""
    brains = index.get("brains") or {}
    if name in brains:
        sid = brains[name]
    elif name == BRAIN_PREFIX or name.startswith(BRAIN_PREFIX + "_"):
        sid = "default" if name == BRAIN_PREFIX else name[len(BRAIN_PREFIX) + 1:]
    else:
        sid = ""
    if sid:
        return {"kind": "steward", "role": "brain", "sid": sid, "title": steward_title(sid, "brain")}
    owners = index.get("owners") or {}
    key = _project_key(name, owners)
    if key and owners.get(key):
        return {"kind": "steward", "role": "project", "sid": owners[key], "title": steward_title(owners[key], "project", name)}
    return None


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


# ── kilitler (çoklu değnekçi P1b) ─────────────────────────────────────────────

LOCK_TIMEOUT = 10.0   # sn; aşılırsa `LockTimeout` (SESSİZ ATLAMA YOK; panelin 15 sn API zaman aşımının altında)
_LOCK_POLL = 0.02
_HELD = threading.local()   # bu iş parçacığının tuttuğu kilitler {yol: derinlik}: yeniden girişli


class LockTimeout(RuntimeError):
    """`flock` zaman aşımında alınamadı: yazım yapılmadı, çağıran hatayı görür."""


class OwnedElsewhere(ValueError):
    """Proje adı başka bir değnekçi kimliğinin `projects.json`'unda zaten var (`owner` = o kimlik)."""
    def __init__(self, name: str, owner: str):
        super().__init__(f"project {name!r} is owned by steward {owner!r}")
        self.name = name
        self.owner = owner


@contextlib.contextmanager
def _flock(path: str, timeout: Optional[float] = None):
    """`path` üzerinde dışlayıcı `fcntl.flock`. Süreçler arası dışlar; aynı süreçte iş parçacıkları da birbirini
    dışlar (her giriş kendi açık dosya tanımını açar). AYNI iş parçacığı yeniden girerse kilitlenmez (sayaç)."""
    key = os.path.abspath(path)
    held = _HELD.__dict__.setdefault("held", {})
    if held.get(key):
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    wait = LOCK_TIMEOUT if timeout is None else timeout
    os.makedirs(os.path.dirname(key), exist_ok=True)
    fd = os.open(key, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(f"could not lock {key} within {wait:g}s") from None
                time.sleep(_LOCK_POLL)
        held[key] = 1
        try:
            yield
        finally:
            held.pop(key, None)
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def steward_lock(paths: Any = None, timeout: Optional[float] = None):
    """Kimlik başına okuma-değiştir-yaz kilidi (`StewardPaths.lock`): `with sw.steward_lock(sid): load → değiştir → save`."""
    return _flock(_pp(paths).lock, timeout)


def ownership_lock(timeout: Optional[float] = None):
    """Global sahiplik kilidi (`STEWARD_DIR/.ownership.lock`): herhangi bir `projects.json` yazımı. Sıra: önce bu,
    sonra kimlik kilidi (ters sıra kilitlenme riski)."""
    return _flock(os.path.join(STEWARD_DIR, ".ownership.lock"), timeout)


def project_owner(name: str, exclude: str = "") -> str:
    """`name` adlı proje hangi kimliğin `projects.json`'unda (`exclude` hariç)? Yok = "". Yalnız dosyalara bakar
    (talep protokolünün `OwnedElsewhere` denetimi; okuma tarafının tam görünümü `ownership_index`)."""
    sids = ["default"] + sorted(os.path.basename(os.path.dirname(f)) for f in
                                glob.glob(os.path.join(STEWARD_DIR, "stewards", "*", "projects.json")))
    rv = reviewer_ids()     # reviewer'ın (elle/eski) projects.json'u sahiplik sayılmaz
    for sid in sids:
        if sid == exclude or sid in rv or not _SID_RE.fullmatch(sid):
            continue
        raw = _load_json(paths_for(sid).projects, {})
        if isinstance(raw, dict) and name in raw:
            return sid
    return ""


# ── sahiplik indeksi (çoklu değnekçi P3) ──────────────────────────────────────
# Sahiplik = projects.json dosyalarının KENDİSİ (K2): ayrı kayıt yok. Aynı ad iki kimlikte = çakışma, kimse yönetmez.
# İndeks bölümlü bir sözlük; `"hosts": {proje: host}` bölümü uzak projeleri taşır (TODO 2026-10-20 (14)): yalnız yerel
# OLMAYANLAR, yalnız çakışmasız projeler. Tüketiciler `World` yöntemleriyle okur (iç biçim değişebilir).

# projects.json yolu → (mtime_ns, size, adlar, {ad: host} yalnız uzaklar)
_OWN_CACHE: Dict[str, Tuple[int, int, Tuple[str, ...], Dict[str, str]]] = {}


class ReservedName(ValueError):
    """Ad proje olarak talep edilemez (beyin adı/öneki, `degnekci*` ailesi, servis adı)."""
    def __init__(self, name: str, reason: str):
        super().__init__(f"project name {name!r} is reserved ({reason})")
        self.name = name
        self.reason = reason


def services_path() -> str:
    """Pasif servis kaydı (K10, P8b'de yazılır; burada yalnız okunur)."""
    return os.path.join(STEWARD_DIR, "services.json")


def discover_steward_ids() -> List[str]:
    """Diskte durum dizini olan kimlikler: `default` + `STEWARD_DIR/stewards/<harf>/`. Ayarda geçersiz sayılan bir
    dizin de (elle açılmış) sayılır: onun projeleri kimsenin olmaz ama başkası da talep edemez (güvenli başarısızlık)."""
    try:
        entries = os.listdir(os.path.join(STEWARD_DIR, "stewards"))
    except OSError:
        entries = []
    return ["default"] + sorted(e for e in entries if e != "default" and _SID_RE.fullmatch(e)
                                and os.path.isdir(os.path.join(STEWARD_DIR, "stewards", e)))


def _project_meta(path: str, fresh: bool = False) -> Tuple[Tuple[str, ...], Dict[str, str]]:
    """`projects.json`'daki geçerli proje adları (`load_projects` ile aynı süzgeç) + uzak projelerin host'ları;
    `(mtime_ns, size)` önbellekli."""
    try:
        stt = os.stat(path)
    except OSError:
        _OWN_CACHE.pop(path, None)
        return (), {}
    hit = _OWN_CACHE.get(path)
    if not fresh and hit and hit[0] == stt.st_mtime_ns and hit[1] == stt.st_size:
        return hit[2], hit[3]
    raw = _load_json(path, {})
    names = tuple(sorted(str(n) for n, d in raw.items() if isinstance(d, dict) and valid_name(str(n)))) \
        if isinstance(raw, dict) else ()
    hosts = {n: h for n in names if (h := normalize_host(raw[n].get("host")))}
    _OWN_CACHE[path] = (stt.st_mtime_ns, stt.st_size, names, hosts)
    return names, hosts


def _project_names(path: str, fresh: bool = False) -> Tuple[str, ...]:
    return _project_meta(path, fresh)[0]


def build_ownership_index(names_by_sid: Dict[str, Any], brains: Optional[Dict[str, str]] = None,
                          services: Optional[Dict[str, Any]] = None,
                          hosts: Optional[Dict[str, Dict[str, str]]] = None) -> Dict[str, Any]:
    """SAF. `names_by_sid`: {kimlik: proje adları}; `brains`: {kimlik: beyin adı} (verilmeyen kimlik `brain_name_for`);
    `services`: services.json içeriği; `hosts`: {kimlik: {proje: host}} (yalnız uzak projeler). Dönüş `{"owners":
    {proje: kimlik}, "conflicts": {proje: [kimlik..]}, "brains": {beyin_adı: kimlik}, "services": {ad: kayıt},
    "hosts": {proje: host}}`. Çakışan ad `owners`'a da `hosts`'a da GİRMEZ."""
    seen: Dict[str, List[str]] = {}
    for sid in sorted(names_by_sid):
        for n in names_by_sid[sid] or ():
            lst = seen.setdefault(str(n), [])
            if sid not in lst:
                lst.append(sid)
    owners = {n: s[0] for n, s in seen.items() if len(s) == 1}
    conflicts = {n: sorted(s) for n, s in seen.items() if len(s) > 1}
    brain_map: Dict[str, str] = {}
    for sid in sorted(set(names_by_sid) | set(brains or {})):
        brain_map[(brains or {}).get(sid) or brain_name_for(sid)] = sid
    svc = {str(n): (dict(r) if isinstance(r, dict) else {}) for n, r in (services or {}).items() if valid_name(str(n))}
    host_map = {p: h for p, h in ((p, normalize_host((hosts or {}).get(s, {}).get(p))) for p, s in owners.items()) if h}
    return {"owners": owners, "conflicts": conflicts, "brains": brain_map, "services": svc, "hosts": host_map}


def ownership_index(sids: Optional[List[str]] = None, *, brains: Optional[Dict[str, str]] = None,
                    fresh: bool = False) -> Dict[str, Any]:
    """Tüm kimliklerin `projects.json`'u + beyin adları + `services.json` → `build_ownership_index`. G/Ç yalnız
    burada (okuma); `sids`: ayardaki kimlikler (dizini olmasa da beyin adı rezerve olur), `fresh`: önbelleği atla
    (talep protokolü). reviewer kimliğinin `projects.json`'u HESABA KATILMAZ (boş sayılır; beyin adı yine rezerve)."""
    ids = list(dict.fromkeys(discover_steward_ids() + [s for s in (sids or []) if valid_steward_id(s)]))
    rv = reviewer_ids()
    meta = {sid: (((), {}) if sid in rv else _project_meta(paths_for(sid).projects, fresh)) for sid in ids}
    svc = _load_json(services_path(), {})
    return build_ownership_index({s: m[0] for s, m in meta.items()}, brains, svc if isinstance(svc, dict) else {},
                                 {s: m[1] for s, m in meta.items()})


def reserved_reason(name: str, index: Dict[str, Any]) -> str:
    """Ad proje olarak talep edilemiyorsa nedeni, değilse "". SAF. `_project_key` önek eşlediği için beyin adının
    öneki (`deg`) ya da uzantısı (`degnekci_x`) da rezerve; `degnekci*` ailesi her zaman. Servis adı (prefix kipinde
    servisle başlayan ad da)."""
    for b in sorted(set(index.get("brains") or {}) | {BRAIN_PREFIX}):
        if name == b or b.startswith(name) or name.startswith(b):
            return f"brain name {b}"
    for s, rec in (index.get("services") or {}).items():
        if name == s or ((rec or {}).get("match") != "exact" and name.startswith(s)):
            return f"service {s}"
    return ""


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
                p.host = normalize_host(p.host)    # elle yazılmış "local" / bozuk tip: yerel
                out[p.name] = p
    return out


def save_projects(projects: Dict[str, Project], paths: Any = None) -> None:
    with ownership_lock(), steward_lock(paths):
        _save_json(_pp(paths).projects, {n: dataclasses.asdict(p) for n, p in projects.items()})


class HostChangeRefused(ValueError):
    """Proje `host`u değiştirilemez: geçersiz/kayıtsız host ya da projenin bir oturumu çalışıyor (ya da bilinmiyor)."""


# Host değişince o projenin oturum adlarıyla tutulan devir/iletim izleri silinir (eski host'taki oturumun izi yeni host'taki
# aynı adlı oturuma taşınmasın: bekleyen devir yanlış oturumu yeniden açar, önsöz "gitti" sanılır, yanıt özeti tutmaz).
_HOST_STATE_KEYS = ("ho_pending", "done_pending", "preamble_sent", "seen_assistant", "ho_deferred")


def _clear_project_state(name: str, projects: Dict[str, Project], paths: Any = None) -> List[str]:
    """`state`teki `_HOST_STATE_KEYS` sözlüklerinden adı (`host:ad` biçimi dahil) `name` projesine çözülen girdileri sil.
    Dönen: silinen anahtarlar. Çağıran kimlik kilidini tutar (kilit yeniden girişli)."""
    st = load_state(paths)
    gone: List[str] = []
    for key in _HOST_STATE_KEYS:
        d = st.get(key)
        if not isinstance(d, dict):
            continue
        for k in list(d):
            bare = str(k).split(":", 1)[-1]
            if _project_key(bare, projects) == name or (key == "done_pending" and d.get(k) == name):
                del d[k]
                gone.append(f"{key}.{k}")
    if gone:
        save_state(st, paths)
    return gone


def upsert_project(name: str, *, paths: Any = None, force: bool = False,
                   running: Optional[Any] = None, **fields: Any) -> Project:
    """Alan bazlı güncelle (None/verilmeyen alanlar korunur). Geçersiz faz/tür/priority yok sayılır.

    `host` (uzak proje): `hosts.json`'da kayıtlı olmalı (`normalize_host`: "local"/"" = yerel), aksi halde
    `HostChangeRefused`. Mevcut projenin host'u DEĞİŞİYORSA `running()` (çağıranın "projenin herhangi bir host'ta
    çalışan oturumu var mı" denetimi: True/False/None=bilinmiyor) yalnız False dönerse kabul edilir; `force` denetimi
    atlar. Değişince o projenin `state` izleri (`_HOST_STATE_KEYS`) temizlenir. Yeni projede çalışma denetimi yok."""
    if not valid_name(name):
        raise ValueError(f"invalid project name: {name!r}")
    if is_reviewer(_pp(paths)):
        raise ReviewerRefused(f"steward {_pp(paths).sid!r} is a reviewer: it cannot own projects (use its review pool)")
    if "host" in fields and fields["host"] is not None:
        fields["host"] = normalize_host(fields["host"])
        if fields["host"] and hosts_mod.get_host(fields["host"]) is None:
            raise HostChangeRefused(f"unknown host: {fields['host']!r} (not in hosts.json)")
    # Talep protokolü: ownership kilidi → ad başka kimlikte mi → kendi RMW (kimlik kilidi)
    with ownership_lock(), steward_lock(paths):
        other = project_owner(name, exclude=_pp(paths).sid)
        if other:
            raise OwnedElsewhere(name, other)
        projects = load_projects(paths)
        if name not in projects:   # yeni talep: rezerve ad reddi (mevcut kayıt hiç etkilenmez)
            why = reserved_reason(name, ownership_index(fresh=True))
            if why:
                raise ReservedName(name, why)
        p = projects.get(name) or Project(name=name, created_at=_now())
        host_changed = name in projects and fields.get("host") is not None and fields["host"] != p.host
        if host_changed and not force:
            busy = running() if callable(running) else None
            if busy is not False:
                raise HostChangeRefused(
                    f"project {name!r} has a running session (or its state is unknown): stop it before moving it "
                    f"from {p.host or 'local'!r} to {fields['host'] or 'local'!r} (or force)")
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
        if host_changed:
            gone = _clear_project_state(name, projects, paths)
            log_event("project_host", paths=paths, name=name, host=p.host, forced=bool(force), cleared=gone)
        return p


def remove_project(name: str, paths: Any = None) -> bool:
    with ownership_lock(), steward_lock(paths):
        projects = load_projects(paths)
        if name not in projects:
            return False
        del projects[name]
        save_projects(projects, paths)
        return True


def transfer_project(name: str, to_sid: str) -> str:
    """Projeyi bugünkü sahibinden `to_sid`e devret (plan (b) devir): kayıt + o projenin açık/iletilmemiş soruları +
    (varsa) bekleyen işler (`jobs.json`, `project` alanı) TEK kilit altında taşınır (önce `.ownership.lock`, sonra
    iki kimlik kilidi kimlik adına göre sıralı: kilitlenme yok); her iki logda `transfer` olayı. Oturumun çalışıp
    çalışmadığı ÇAĞIRANIN işi (CLI denetler). Dönen: eski sahip. Hata: `ValueError` (yok / zaten orada / hedefte aynı ad
    / hedef kimlik ayarda tanımlı değil)."""
    if not valid_steward_id(to_sid):
        raise ValueError(f"invalid steward id: {to_sid!r}")
    from .settings import steward_ids      # tembel: `settings` bu modülü tembel içe aktarır (döngü yok)
    if to_sid not in steward_ids():
        # Ayarda olmayan kimliğe devir `stewards/<yeni>/projects.json` açardı: "dizin var, ayar yok" kimlik, kimse yönetmez.
        raise ValueError(f"unknown steward id: {to_sid!r} (not defined in settings)")
    if is_reviewer(to_sid):
        raise ReviewerRefused(f"steward {to_sid!r} is a reviewer: projects cannot be transferred to it")
    with ownership_lock():
        src = project_owner(name)
        if src and is_reviewer(src):    # project_owner reviewer'ı zaten atlar; savunma
            raise ReviewerRefused(f"steward {src!r} is a reviewer: projects cannot be transferred from it")
        if not src:
            raise ValueError(f"project {name!r} not found in any steward")
        if src == to_sid:
            raise ValueError(f"project {name!r} already belongs to steward {to_sid!r}")
        first, second = sorted((src, to_sid))
        with steward_lock(first), steward_lock(second):
            if name in load_projects(to_sid):
                raise ValueError(f"project {name!r} already exists in steward {to_sid!r}")
            src_projects = load_projects(src)
            if name not in src_projects:
                raise ValueError(f"project {name!r} not found in steward {src!r}")
            dst_projects = load_projects(to_sid)
            dst_projects[name] = src_projects.pop(name)
            moved_q = 0
            src_qs, dst_qs = load_questions(src), load_questions(to_sid)
            keep = []
            for q in src_qs:
                if q.project == name and (q.status == "open" or not q.delivered_at):
                    dst_qs.append(q)
                    moved_q += 1
                else:
                    keep.append(q)
            moved_jobs = 0
            sj, dj = _pp(src).jobs, _pp(to_sid).jobs
            sjobs, djobs = _load_json(sj, []), _load_json(dj, [])
            mine: List[Any] = []
            if isinstance(sjobs, list) and isinstance(djobs, list):
                mine = [j for j in sjobs if isinstance(j, dict) and j.get("project") == name]
                moved_jobs = len(mine)
            # Yazım sırası: hedef projects → hedef jobs/questions → kaynak projects → kaynak jobs/questions. Yarıda kalırsa
            # (disk/OSError) ad İKİ yerde olur = çakışma (kimse yönetmez, `ownership_conflict` görünür; güvenli başarısızlık);
            # kaynak kaydı/işleri/soruları silinmeden önce hedefte tam kopya vardır, hiçbir iş öksüz kalmaz.
            save_projects(dst_projects, to_sid)
            if mine:
                _save_json(dj, djobs + mine)
            save_questions(dst_qs, to_sid)
            save_projects(src_projects, src)
            if mine:
                _save_json(sj, [j for j in sjobs if j not in mine])
            save_questions(keep, src)
            log_event("transfer", paths=src, name=name, to=to_sid, questions=moved_q, jobs=moved_jobs)
            log_event("transfer", paths=to_sid, name=name, frm=src, questions=moved_q, jobs=moved_jobs)
        return src


def load_ideas(paths: Any = None) -> List[Idea]:
    raw = _load_json(_pp(paths).ideas, [])
    return [_from_dict(Idea, d) for d in raw if isinstance(d, dict) and d.get("id")] if isinstance(raw, list) else []


def save_ideas(ideas: List[Idea], paths: Any = None) -> None:
    with steward_lock(paths):
        _save_json(_pp(paths).ideas, [dataclasses.asdict(i) for i in ideas])


def add_idea(text: str, source: str = "", paths: Any = None) -> Idea:
    text = str(text).strip()[:_MAX_IDEA_CHARS]
    if not text:
        raise ValueError("empty idea")
    with steward_lock(paths):
        ideas = load_ideas(paths)
        idea = Idea(id=_new_id("i"), text=text, created_at=_now(), source=source)
        ideas.append(idea)
        save_ideas(ideas, paths)
        return idea


def update_idea(idea_id: str, status: Optional[str] = None, project: Optional[str] = None,
                paths: Any = None) -> Optional[Idea]:
    with steward_lock(paths):
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
    with steward_lock(paths):
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
    with steward_lock(paths):
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
TOUR_INLINE_MAX_CHARS = 4000        # tur bundan uzunsa tmux'e gömülmez: dosyaya yazılır, beyne kısa 'şunu oku' mesajı gider (>10K kesiliyordu)
TOUR_FILES_KEEP = 5
TOUR_MAX_ITEMS = 8                  # bir turda en çok bu kadar madde (büyük prompt beynin giriş kutusunda takılıyordu); kalanı sonraki tura
ROUTINE_ESCALATE_SECONDS = 30 * 60   # beyin bu sürede rutin soruyu cevaplamazsa soru sahibine (telefon) düşer
REASK_MAX_REPEATS = 2              # aynı cevap en çok bu kadar yeniden iletilir, sonra soru gerçekten açılır
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _words(text: str) -> set:
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) > 2}


_SALIENT_RE = re.compile(r"\b[A-Za-z]{1,3}\d+(?:[-_.]\d+)*\b|\b(?:opus|fable|sonnet|haiku|high|medium|low|max)\b", re.IGNORECASE)
SALIENT_MIN_TOKENS = 3             # bölüm/aşama kodu + model + effort gibi ayırt edici kelimeler: en az bu kadar ortak ve aynı küme


def _salient(text: str) -> frozenset:
    """Sorunun konusunu belirleyen kısa jetonlar (G8, A3-5, opus, fable, high...). Uzun serbest cümlelerde kelime Jaccard'ı
    düşük kalır ("G8 Opus high, sonra Fable high mı?" 4 farklı anlatımla 4 kez soruldu); konu jetonları aynıysa tekrar sayılır."""
    return frozenset(m.group(0).lower() for m in _SALIENT_RE.finditer(text))


SIMILAR_MIN_SCORE = 0.25


def similar_answers(text: str, questions: List["Question"], project: str = "", exclude_id: str = "",
                    limit: int = 3) -> List["Question"]:
    """Karar hafızası (yalnız bu kimliğin `questions.json`'u): `text`e en çok benzeyen cevaplanmış sorular (en benzer önce).
    Skor = kelime Jaccard'ı + ortak konu jetonu payı (+0.1 aynı proje). Beyin rutin/takılma maddesinde sahibin geçmiş
    kararlarını görür; aynı şeyi yeniden sormasın, tutarlı cevaplasın."""
    mine, mine_sal = _words(text), _salient(text)
    if not mine:
        return []
    scored = []
    for q in questions:
        if q.status != "answered" or not q.answer.strip() or q.id == exclude_id:
            continue
        theirs = _words(q.text)
        if not theirs:
            continue
        score = len(mine & theirs) / len(mine | theirs)
        sal = _salient(q.text)
        if mine_sal and sal:
            score += 0.3 * len(mine_sal & sal) / len(mine_sal | sal)
        if project and q.project == project:
            score += 0.1
        if score >= SIMILAR_MIN_SCORE:
            scored.append((score, q.answered_at, q))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [q for _, _, q in scored[:limit]]


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
        if sim < REASK_MIN_SIMILARITY:
            sal, sal_q = _salient(text), _salient(q.text)
            if len(sal) >= SALIENT_MIN_TOKENS and sal == sal_q:
                sim = REASK_MIN_SIMILARITY       # konu jetonları birebir aynı: tekrar say
        if sim >= REASK_MIN_SIMILARITY and sim > best_sim:
            best, best_sim = q, sim
    return best


OPEN_MERGE_WINDOW_SECONDS = 24 * 3600   # açık benzer soru bu süre içinde sorulmuşsa yeni soru açılmaz
OPEN_MERGE_MIN_WORDS = 4                # iki metinde de en az bu kadar anlamlı kelime: "x soru 3?"/"x soru 4?" gibi kısa sorular birleşmesin


def find_open_similar(questions: List["Question"], project: str, text: str,
                      now: Optional[float] = None) -> Optional["Question"]:
    """Aynı projede hâlâ AÇIK (cevapsız), yakın zamanda açılmış ve `text`e kelime düzeyinde çok benzeyen soru (en benzeri).
    Benzerlik ölçütü `find_answered_duplicate` ile aynı (Jaccard >= REASK_MIN_SIMILARITY ya da aynı konu jetonları)."""
    now = _now() if now is None else now
    mine = _words(text)
    if len(mine) < OPEN_MERGE_MIN_WORDS:
        return None
    best, best_sim = None, 0.0
    for q in questions:
        if q.status != "open" or q.project != project or now - q.created_at > OPEN_MERGE_WINDOW_SECONDS:
            continue
        theirs = _words(q.text)
        if len(theirs) < OPEN_MERGE_MIN_WORDS:
            continue
        sim = len(mine & theirs) / len(mine | theirs)
        if sim < REASK_MIN_SIMILARITY:
            sal, sal_q = _salient(text), _salient(q.text)
            if len(sal) >= SALIENT_MIN_TOKENS and sal == sal_q:
                sim = REASK_MIN_SIMILARITY
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


def _unique_question_key(sid: str) -> str:
    """Soruya özel anahtar: rastgele 16 hex; diğer kimliklerin sorularında zaten varsa yenisi çekilir (`/q/` kimlik
    verilmeden tüm depolarda arar: anahtar kimlikler arası çakışmasın)."""
    taken = set()
    for other in discover_steward_ids():
        if other != sid:
            taken.update(q.key for q in load_questions(other) if q.key)
    while True:
        key = secrets.token_hex(8)
        if key not in taken:
            return key


def add_question(project: str, text: str, source: str = "", options: Any = None, routine: bool = False,
                 paths: Any = None) -> Question:
    text = str(text).strip()[:_MAX_QUESTION_CHARS]
    if not text:
        raise ValueError("empty question")
    with steward_lock(paths):
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
        # Benzer (aynı olmayan) AÇIK soru: yenisi açılmaz, sayaç artar (devirle gelen yeni oturum öncekinin sorusunu bilmez).
        sim = find_open_similar(questions, project, text)
        if sim is not None:
            sim.asked_again += 1
            save_questions(questions, paths)
            return sim
        q = Question(id=_new_id("q"), project=project, text=text, created_at=_now(), source=source,
                     options=normalize_options(options), key=_unique_question_key(_pp(paths).sid), routine=bool(routine))
        questions.append(q)
        save_questions(questions, paths)
        return q


def answer_question(question_id: str, answer: str, paths: Any = None) -> Optional[Question]:
    answer = str(answer).strip()
    if not answer:
        raise ValueError("empty answer")
    with steward_lock(paths):
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
    with steward_lock(paths):
        questions = load_questions(paths)
        for q in questions:
            if q.id == question_id:
                q.notified_at = _now()
        save_questions(questions, paths)


def question_link(q: Question, base: str, sid: str = "default") -> str:
    """Telefon sayfası: `<base>/q/<id>?k=<key>`; default dışı kimlikte `&s=<sid>` (soru o kimliğin deposunda aranır;
    default için biçim eskisiyle AYNI). `base` boşsa (tünel yok) ya da soru anahtarsızsa (eski kayıt) ""."""
    base = (base or "").rstrip("/")
    if not (base and q.key):
        return ""
    return f"{base}/q/{q.id}?k={q.key}" + ("" if sid == "default" else f"&s={sid}")


def ask_hint(question_id: str, sid: str = "default") -> str:
    """CLI cevap ipucu (`py/cops steward [-s <sid>] answer <id> "..."`)."""
    return f"py/cops steward{'' if sid == 'default' else ' -s ' + sid} answer {question_id} \"...\""


def ask_prefix(project: str, sid: str = "default", host: str = "") -> str:
    """ntfy gövde öneki: default `[proje]` (eskisi), diğer kimlik `[<sid>/<proje>]` (K4). Uzak projede (`host`, A5)
    ad `proje@host` olur (`[oiso@ulak_31]`); yerelde ("" / "local") çıktı DEĞİŞMEZ."""
    h = normalize_host(host)
    name = (project or 'degnekci') + (f"@{h}" if h and project else "")
    return f"[{name}]" if sid == "default" else f"[{sid}/{name}]"


def question_notification(q: Question, link: str, lang: str = "tr", sid: str = "default", host: str = "") -> str:
    """ntfy gövdesi: `[proje] soru` (default dışı: `[sid/proje]`), numaralı seçenekler, sonra bağlantı ya da (yoksa) CLI ipucu."""
    lines = [f"{ask_prefix(q.project, sid, host)} {q.text}"]
    lines += [f"{i}) {o}" for i, o in enumerate(q.options, 1)]
    if link:
        lines.append(("→ cevapla: " if lang != "en" else "→ answer: ") + link)
    else:
        lines.append("→ " + ask_hint(q.id, sid))
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
    with steward_lock(paths):
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
    with steward_lock(paths):
        questions = load_questions(paths)
        for q in questions:
            if q.id == question_id:
                q.delivered_at = _now()
        save_questions(questions, paths)


def open_questions(questions: Optional[List[Question]] = None, paths: Any = None) -> List[Question]:
    return [q for q in (questions if questions is not None else load_questions(paths)) if q.status == "open"]


HANDOVER_QUESTIONS_MAX = 8
HANDOVER_QUESTION_CHARS = 200


def handover_questions_note(questions: List["Question"], name: str, lang: str = "tr", project: str = "") -> str:
    """Devir mesajına eklenecek "sorduğum AÇIK sorular" bölümü: bu oturumun (kaynak) ya da projesinin cevapsız soruları.
    Yeni oturum öncekinin sorusunu bilmez ve aynısını yeniden açar (copsdev, 2026-10-24); özet bu soruları taşısın.
    Açık soru yoksa "" (mesaj değişmez)."""
    keys = {name, project} - {""}      # `name` = oturum adı (tarihli olabilir), `project` = kayıtlı proje adı
    rows = [q for q in questions if q.status == "open" and (q.source in keys or q.project in keys)]
    if not rows:
        return ""
    rows.sort(key=lambda q: q.created_at)
    lines = []
    for q in rows[:HANDOVER_QUESTIONS_MAX]:
        text = " ".join(str(q.text or "").split())
        if len(text) > HANDOVER_QUESTION_CHARS:
            text = text[:HANDOVER_QUESTION_CHARS - 1] + "…"
        again = f" (+{q.asked_again} kez yeniden soruldu)" if lang != "en" and q.asked_again else (
            f" (+{q.asked_again} re-asks)" if q.asked_again else "")
        lines.append(f"- [{q.id}] {text}{again}")
    more = len(rows) - len(lines)
    if lang == "en":
        head = ("OPEN QUESTIONS I asked (still unanswered; the new session must NOT ask them again, the steward delivers "
                "the answer). Copy them under a \"## Open questions\" line in your READY FOR HANDOVER summary:")
        tail = f"\n- … and {more} more" if more > 0 else ""
    else:
        head = ("Sorduğum AÇIK sorular (hâlâ cevapsız; yeni oturum AYNISINI yeniden SORMASIN, cevabı değnekçi iletir). "
                "READY FOR HANDOVER özetine \"## Açık sorular\" başlığıyla aynen kopyala:")
        tail = f"\n- … ve {more} soru daha" if more > 0 else ""
    return head + "\n" + "\n".join(lines) + tail


def undelivered_answers(questions: Optional[List[Question]] = None, paths: Any = None) -> List[Question]:
    return [q for q in (questions if questions is not None else load_questions(paths))
            if q.status == "answered" and not q.delivered_at]


def load_state(paths: Any = None) -> Dict[str, Any]:
    st = _load_json(_pp(paths).state, {})
    return st if isinstance(st, dict) else {}


def save_state(state: Dict[str, Any], paths: Any = None) -> None:
    with steward_lock(paths):
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


def raw_card_from_docs(docs: Dict[str, str]) -> Dict[str, Any]:
    """UZAK projenin ham kartı: belge başları host-routed okumadan gelir, git bilgisi YOK (`git_unknown`; yerel `git`
    uzak yola bakamaz). `source_hash` yalnız belgelerden (`build_raw_card`ın belge kısmıyla aynı şema). SAF."""
    h = hashlib.sha1()
    for d in CARD_DOCS:
        if d in docs:
            h.update(f"\0{d}\0{docs[d]}".encode("utf-8", "replace"))
    return {"docs": dict(docs), "git_log": [], "last_commit": 0.0, "git_unknown": True, "source_hash": h.hexdigest()[:16]}


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
    if raw.get("git_unknown"):
        parts.append("=== git ===\nremote: bilinmiyor" if tr else "=== git ===\nremote: unknown")
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

def _unwrap_ticks(prefix: str, body: str) -> str:
    """İşaretin etrafındaki biçimlendirme backtick'ini at, gövdenin KENDİ backtick'ine dokunma: `` `STEWARD-ASK: x` ``
    (öndeki tek backtick işaretten ÖNCE) sondaki eşini atar; gövde tümüyle `...` ise sarmalı atılır. Eskiden
    `.strip("`")` gövdenin başındaki meşru `kod` backtick'ini de silip soruyu ortadan başlatıyordu."""
    if prefix.count("`") % 2 == 1 and body.endswith("`"):
        body = body[:-1].rstrip()
    if len(body) > 1 and body.startswith("`") and body.endswith("`") and body.count("`") == 2:
        body = body[1:-1]
    return body.strip()


_JOB_BODY_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}\s+\S")   # '<tür> <dosya/açıklama>': tür küçük harf kimliği


_PLACEHOLDER_BODY_RE = re.compile(r"^<[^<>\n]{1,80}>[\s`.…]*$")   # '<soru>' gibi YER TUTUCU: yazım örneği, gerçek soru değil


def done_blocked(project: Any) -> bool:
    """Proje notunda `NO_DONE_TAG` varsa `STEWARD-DONE` işlenmez (copsdev, 2026-10-24: iki kez bir bulgu paketi/devir
    mesajı yüzünden proje `done` olup oturum durdu). SAF."""
    return NO_DONE_TAG in str(getattr(project, "notes", "") or "")


def scan_markers(text: str) -> Dict[str, Any]:
    """Bir oturum yanıtındaki `STEWARD-*` satırlarını çıkar. Dönen: {asks:[...], ideas:[...],
    blocked:[...], plan_ready: bool, done: bool}. Satır başındaki madde/boşluk toleranslı;
    işaret satırın İÇİNDE de olabilir (model bazen önüne açıklama koyar) — kalanı alınır."""
    out: Dict[str, Any] = {"asks": [], "routines": [], "ideas": [], "blocked": [], "jobs": [], "plan_ready": False, "done": False}
    if not text:
        return out
    fenced = False
    for raw in text.splitlines():
        if raw.strip().startswith("```"):      # kod bloğu içindeki işaret yazım örneğidir
            fenced = not fenced
            continue
        if fenced or raw.lstrip().startswith(">"):     # kod bloğu / alıntı satırı
            continue
        line = raw.strip().lstrip("-*• ").strip()
        if not line:
            continue
        for mark, key in ((MARK_ROUTINE, "routines"), (MARK_ASK, "asks"), (MARK_IDEA, "ideas"), (MARK_BLOCKED, "blocked"),
                          (MARK_JOB, "jobs")):
            idx = line.find(mark)
            if idx != -1:
                body = _unwrap_ticks(line[:idx], line[idx + len(mark):].strip())
                if _PLACEHOLDER_BODY_RE.match(body):
                    break   # `STEWARD-BLOCKED: <nerede takıldın>` türü yazım örneği
                if key == "jobs" and not (line[:idx] in ("", "`") and _JOB_BODY_RE.match(body)):
                    break   # düzyazıdaki anma ya da yer tutucu ('<iş türü> <dosya>'): iş isteği değil
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
    f"- paylaşımlı servise (varaka) iş göndermek istiyorsan, istek dosyasını projede hazırla ve: `{MARK_JOB} <iş türü> <dosya yolu> [kısa açıklama]`; "
    "değnekçi beyni işi kuyruğa gönderir, sonucu sana iletilir; sahibe 'devam de' deme\n"
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
    f"- to send a job to the shared service (varaka), prepare the request file in the project and write: `{MARK_JOB} <job kind> <file path> [short note]`; "
    "the steward brain submits it to the queue and its result is delivered to you; do NOT ask me to say 'go on'\n"
    f"- stuck after thinking it through: `{MARK_BLOCKED} <where>`\n"
    "Rules: my answers are short ('both', 'go in order', 'you continue') and are STANDING rules; do not re-ask "
    "the same topic. If an answer is not enough, proceed with a sensible default and record the assumption in "
    "TOBEDECIDED.md. The 'My earlier answers' list below holds decisions I already gave you; follow them.\n"
)


def build_directive(project: Project, lang: str = "tr", extra: str = "", answer: Optional[Question] = None,
                    more: Optional[List[Question]] = None, compact: bool = False) -> str:
    """Bir proje oturumuna gönderilecek faz direktifi. `answer` verilirse önce insanın cevabı iletilir.
    Beyin kendi direktifini `extra` ile tamamen ezebilir (şablon yine protokol kuyruğunu ekler).
    `compact` (yalnız `answer` ile): oturum amaç/not/protokolü bu yaşamında zaten aldı; yalnız soru-cevap + `extra`."""
    tr = lang != "en"
    compact = bool(compact and answer is not None)
    parts: List[str] = []
    head = f"[claudeops değnekçi — {project.name}]" if tr else f"[claudeops steward — {project.name}]"
    parts.append(head)
    if project.goal and not compact:
        parts.append(("Amaç: " if tr else "Goal: ") + project.goal.strip())
    if answer is not None:
        parts.append(("Sorduğun soru: " if tr else "Your question: ") + answer.text.strip())
        parts.append(("Cevabım: " if tr else "My answer: ") + answer.answer.strip())
        if answer.repeats:
            parts.append("Bunu zaten cevapladım, yukarıdaki cevap geçerli; yeniden sorma, devam et." if tr else
                         "I already answered this; the answer above stands. Do not ask again, continue.")
        for m in more or []:    # aynı oturuma aynı tickte biriken ek cevaplar: TEK mesajda (ayrı ayrı uyandırma yok)
            parts.append(("Sorduğun soru: " if tr else "Your question: ") + m.text.strip())
            parts.append(("Cevabım: " if tr else "My answer: ") + m.answer.strip())
        prior = [] if compact else recent_answers(project.name, exclude_id=answer.id)
        if prior and more:
            skip = {m.id for m in more}
            prior = [q for q in prior if q.id not in skip]
        if prior:
            parts.append(("Önceki cevaplarım:\n" if tr else "My earlier answers:\n") +
                         "\n".join(f"- {q.text.strip()[:140]} → {q.answer.strip()[:200]}" for q in prior))
    if extra.strip():
        parts.append(extra.strip())
    elif compact:
        pass
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
    if compact:
        return "\n\n".join(parts)
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
        bl = it.get("backlog")      # yalnız generic rolde (`web_steward.run_tour`); diğer kimliklerin prompt'u aynı
        if bl:
            if bl.get("auto"):
                lines.append(("otonom ilerletilebilir (sahibin cevabı gerekmez): " if tr else "autonomous (no owner answer needed): ")
                             + "; ".join(_clip(x, 160) for x in bl["auto"]))
            if bl.get("decide"):
                lines.append(("karar gerekir (ATLA, varsayılanı uygulama; açık değilse steward_ask_user): " if tr else
                              "needs a decision (SKIP, never apply a default; steward_ask_user unless already open): ")
                             + "; ".join(_clip(x, 160) for x in bl["decide"]))
        if it.get("text"):
            lines.append(_clip(it["text"], 600))
        for sq in it.get("similar") or []:
            lines.append((f"benzer geçmiş karar [{sq.get('project') or '-'}]: " if tr else f"similar past decision [{sq.get('project') or '-'}]: ")
                         + _clip(sq.get("text", ""), 160) + " → " + _clip(sq.get("answer", ""), 200))
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
    "- Alt ajan bağlam bütçesi: ajan direktifine \"yalnız şu dosyaları oku\" listesini ve çıktı dosyasını AÇIK yaz (bütün repoyu/büyük kaynakları okutma; "
    "büyük ön okumayı ayrı Sonnet çekme ajanına yaptır, Opus/Fable'a kısa özet ver). Çıktıyı bölüm bölüm `Edit`leme: tek `Write` ya da en çok 3-4 büyük "
    "düzenleme (her araç çağrısı tüm bağlamı yeniden okutur). Fable ajanına özellikle dar dosya listesi ver.\n"
    "- Rutin sorular: bu kuralda ve proje notunda zaten karara bağlı bir işi (hangi modelle, sırayla mı, ayrı ajanla mı) `steward_answer` ile kendin cevapla; "
    "sahibe yükseltme. Yeni bir karar gerektirmiyorsa \"devam et\" de.\n"
    "- İŞ İSTEĞİ maddesi (\"İŞ İSTEĞİ (STEWARD-JOB): <tür> <dosya> ...\"): proje paylaşımlı servise (varaka) iş istiyor. `steward_jobs kinds=true` ile "
    "türü doğrula, `steward_job_submit` ile (project, kind, files=[proje klasörü içi yol]) gönder, sonra `steward_answer` ile projeye iş kimliğini ve durumu "
    "(queued / awaiting_approval) bildir. Onay bekleyen işi KENDİN onaylama, sahibe `steward_ask_user` ile haber ver. Tür ya da dosya belirsizse "
    "tahmin etme, `steward_answer` ile projeye neyin eksik olduğunu söyle. Sonucu motor iş bitince projeye zaten iletir.\n"
    "- SAHİBE AİT KARARLAR: commit, push, merge, deploy, kurulum, silme, harcama, kimlik/yetki ve kod değişikliği onayı SAHİBİN kararıdır; "
    "`steward_answer` ile ASLA onay verme (motor reddeder). Böyle bir soru gelirse `steward_ask_user` ile sahibe ilet. Direktif meşgul oturum yüzünden "
    "`session_busy` dönerse tekrarlama; sonraki turda yeniden değerlendir.\n"
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
    "- Sub-agent context budget: write an explicit \"read only these files\" list and the output file in each sub-agent directive (never the whole repo/large sources; "
    "have a separate Sonnet fetch agent do big pre-reading and hand Opus/Fable a short summary). Do not `Edit` output section by section: one `Write` or at most "
    "3-4 large edits (every tool call re-reads the whole context). Give Fable agents an especially narrow file list.\n"
    "- Routine questions: if this rule or the project note already decides it (which model, in order or not, separate agent), answer it yourself with `steward_answer`; "
    "do not escalate to the owner. If no new decision is needed, say \"continue\".\n"
    "- JOB REQUEST item (\"İŞ İSTEĞİ (STEWARD-JOB): <kind> <file> ...\"): the project wants a job in the shared service (varaka). Check the kind with "
    "`steward_jobs kinds=true`, submit with `steward_job_submit` (project, kind, files=[path inside the project folder]), then tell the project the job id and "
    "state (queued / awaiting_approval) with `steward_answer`. NEVER approve a job awaiting approval yourself; tell the owner with `steward_ask_user`. If the "
    "kind or file is unclear, do not guess: tell the project what is missing via `steward_answer`. The engine delivers the result when the job finishes.\n"
    "- OWNER-ONLY DECISIONS: commit, push, merge, deploy, install, delete, spending, credentials/authority and approving code changes belong to the "
    "OWNER; NEVER approve them with `steward_answer` (the engine rejects it). Forward such a question with `steward_ask_user`. If a directive returns "
    "`session_busy`, do not repeat it; re-evaluate on the next tour.\n"
)


def identity_section(sid: str, label: str = "", lang: str = "tr") -> str:
    """Default DIŞI kimliğin beyni için kısa kimlik bölümü (docs/multi-steward-plan.md (d)). `default` için "" (o beynin
    CLAUDE.md'si BAYT BAYT eskisi gibi kalır)."""
    if sid == "default":
        return ""
    who = f"`{sid}` (`{label}`)" if label else f"`{sid}`"
    if lang != "en":
        return (
            f"## Kimliğin\n"
            f"Sen {who} değnekçisisin. Yalnız `steward_overview`'daki projeler senin; başka proje ya da oturuma hâkim değilsin.\n"
            f"`degnekci*` adlı oturumlar başka değnekçilerin beyinleri, paylaşımlı servis oturumları da senin değil: hiçbirine yazma; "
            f"araçlar reddeder, reddi yeniden deneme.\n"
            f"MCP araçları kimliğini (`{sid}`) her çağrıya OTOMATİK ekler; kimlik parametresi yoktur, değiştirilemez.\n\n")
    return (
        f"## Your identity\n"
        f"You are the steward {who}. Only the projects listed by `steward_overview` are yours; you do not govern any other project or session.\n"
        f"Sessions named `degnekci*` are the brains of other stewards, and shared service sessions are not yours either: never write to "
        f"them; the tools refuse, and you must not retry a refusal.\n"
        f"The MCP tools add your identity (`{sid}`) to every call AUTOMATICALLY; there is no identity parameter and it cannot be changed.\n\n")


MEMORY_TR = (
    "\n## Hafızan (NOTLAR.md)\n"
    "- Bu klasördeki `NOTLAR.md` senin kalıcı hafızan: bu CLAUDE.md her açılışta yeniden yazılır, o dosyaya DOKUNULMAZ. Oturum başında oku; "
    "kalıcı bir şey öğrendiğinde (sahibin tercihi, bir projenin tuhaflığı, tekrar eden hata) bir iki satır ekle; şişirme, eskiyeni sil.\n"
    "- Devir/kapatma mesajı geldiğinde önce `NOTLAR.md`yi güncelle, sonra yanıtını `READY FOR HANDOVER` ile bitir.\n"
)
MEMORY_EN = (
    "\n## Your memory (NOTLAR.md)\n"
    "- `NOTLAR.md` in this folder is your persistent memory: this CLAUDE.md is rewritten at every start, that file is NEVER touched. Read it at "
    "session start; when you learn something durable (owner preference, a project quirk, a recurring mistake) add a line or two; keep it short, drop stale entries.\n"
    "- When a handover/shutdown message arrives, update `NOTLAR.md` first, then end your reply with `READY FOR HANDOVER`.\n"
)

REMOTE_NOTE_TR = (
    "\n## Uzak host'taki projeler\n"
    "Bazı proje oturumları başka bir makinede (host) çalışır: araç çıktılarında `host` alanıyla (ve `proje@host` "
    "adıyla) görünür. Yerel ve uzak oturumlar AYNI araçlarla yönetilir; host'u sen verme, proje kaydından çözülür. "
    "Host kapalıysa o projeye eylem yapılmaz (beklemek doğru), uzak klasörün git durumu bilinmez.\n")
REMOTE_NOTE_EN = (
    "\n## Projects on remote hosts\n"
    "Some project sessions run on another machine (host): they show up with a `host` field (and a `project@host` "
    "name) in tool output. Local and remote sessions are managed with the SAME tools; never pass a host, it is "
    "resolved from the project record. While a host is down nothing is done to its projects (waiting is right), and "
    "the git state of a remote folder is unknown.\n")


def build_workspace_claude_md(persona: str, lang: str = "tr", sid: str = "default", label: str = "",
                              remote: bool = False, role: str = "steward") -> str:
    """Beynin cwd'sindeki CLAUDE.md — persona + (default dışı kimlikte kimlik bölümü) + araç kılavuzu + model kuralı.
    Her beyin açılışında yeniden yazılır. `sid="default"` çıktısı kimlik kavramından ÖNCEKİyle birebir aynıdır.
    `remote`: kimliğin uzak host'lu projesi var (A5) → kısa "uzak projeler" notu eklenir. `role="generic"`: model
    kuralından sonra generic bölümü eklenir (diğer rollerde çıktı aynı)."""
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
    note = (REMOTE_NOTE_TR if tr else REMOTE_NOTE_EN) if remote else ""     # yalnız uzak projesi olan kimlikte (yerel çıktı aynı)
    gen = ((GENERIC_RULE_TR if tr else GENERIC_RULE_EN) if role == "generic" else "")
    return persona.rstrip() + "\n\n" + identity_section(sid, label, lang) + tools + note + (MODEL_RULE_TR if tr else MODEL_RULE_EN) + gen + (MEMORY_TR if tr else MEMORY_EN) + tail


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
                 reviewed_at: Optional[Dict[str, float]] = None,
                 world: Optional[World] = None) -> List[Dict[str, Any]]:
    """Beynin yargısını gerektiren maddeler: boşta bekleyen proje oturumu (`idle`), uzun süredir meşgul
    olup gözden geçirilmemiş oturum (`review`), yeni fikir (`idea`), oturuma iletilemeyen cevap
    (`blocked`). `plan_tick` bunu çağırır; elle "tur" (`web_steward.run_tour(force=True)`) de aynı listeyi alır.
    `world` verilirse yalnız o kimliğin projeleri/oturumları (fikir/soru zaten kimliğin kendi deposundan gelir)."""
    skip = skip or set()
    lda = last_directive_at or {}
    rva = reviewed_at or {}
    if world is not None:
        projects = world.own_projects(projects)
    items: List[Dict[str, Any]] = []
    # Sahibin cevabını bekleyen oturum (açık, rutin olmayan soru) ya da bitmiş/duraklatılmış proje "boşta" sayılmaz:
    # beynin yapacağı bir şey yok, bayat bayrak olarak `skip` yedirirdi (20 Eki: 54 boşa tur maddesi).
    waiting = {q.source for q in questions if q.status == "open" and not q.routine and q.source}
    waiting |= {q.project for q in questions if q.status == "open" and not q.routine and q.project}
    for v in views:
        if not v.running or not _is_project_session(v, projects) or v.name in skip or v.name == cfg.brain_name:
            continue
        if world is not None and world.session_class(v.name, v.blueprint) != "own":
            continue
        if v.name in waiting or v.project in waiting or projects[v.project].phase in ("done", "paused"):
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


# ── kimlik görünümü (çoklu değnekçi P3, SAF) ─────────────────────────────────

_DATE8_RE = re.compile(r"20\d\d(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])")   # türetilmiş oturum adının tarih soneki
_DENY = ("other", "conflict", "service", "brain_other", "brain_own")


@dataclass
class World:
    """Bir değnekçi kimliğinin (`sid`) dünyaya bakışı: sahiplik indeksinden türer (`world_for`). `plan_tick`/`review_items`
    `world` alınca yalnız bu kimliğin projelerine eylem/madde üretir. Oturum sınıfları (`session_class`):
    `own` (bu kimliğin projesi), `other` (başka kimliğin), `conflict` (aynı ad iki kimlikte: kimse yönetmez),
    `adhoc` (hiçbir kimliğin değil), `brain_own`/`brain_other` (beyin oturumları), `service` (pasif servis)."""
    sid: str = "default"
    owners: Dict[str, str] = field(default_factory=dict)        # proje → kimlik (çakışanlar hariç)
    conflicts: frozenset = frozenset()                           # birden çok kimlikte görünen proje adları
    brains: Dict[str, str] = field(default_factory=dict)        # beyin oturumu adı → kimlik
    services: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    is_adhoc_owner: bool = True                                  # kayıtsız oturumların işaretlerini işler (yalnız default)
    starts_left: Optional[int] = None                            # döngü turunun kalan başlatma hakkı (`max_starts_total`); None = sınırsız
    hosts: Dict[str, str] = field(default_factory=dict)          # uzak proje → host (yerel projeler YOK; indeksin `hosts` bölümü)
    unavailable: frozenset = frozenset()                         # host'u şu an erişilemeyen (ya da uzak eylemi kapalı) projeler:
                                                                 # başlatılmaz, devir/DONE izi silinmez (görünümleri yok diye "kapandı" sayılmaz)

    def host_of(self, project: str) -> str:
        """Projenin host'u ("" = yerel)."""
        return self.hosts.get(project, "")

    def owner_of(self, project: str) -> str:
        """Projenin sahibi ("" = sahipsiz ya da çakışmalı)."""
        return "" if project in self.conflicts else self.owners.get(project, "")

    def owns(self, project: str) -> bool:
        return bool(project) and self.owner_of(project) == self.sid

    def own_projects(self, projects: Dict[str, "Project"]) -> Dict[str, "Project"]:
        """Verilen proje sözlüğünden YALNIZ bu kimliğin sahip olduğu (çakışmasız) projeler."""
        return {n: p for n, p in projects.items() if self.owns(n)}

    def _owner_tag(self, project: str) -> str:
        return "!conflict" if project in self.conflicts else self.owners.get(project, "")

    def resolve(self, name: str) -> Tuple[str, str]:
        """Oturum adı → (tür, anahtar): tür `brain` | `service` | `project` | "". Proje çözümü GLOBAL (K4): tüm
        kimliklerin projeleri üzerinde tam ad, sonra en uzun önek (`_project_key` ile aynı). Tek fark: en uzun önek
        ile tarih sonekli ayrıştırma (`ncs` + `20261019`) FARKLI sahiplere düşerse ayrıştırma kazanır: `ncs` (A) ve
        `ncs2` (B) varken `ncs20261019` A'nın, `ncs2x` B'nin. Aynı sahipte eski sonuç (en uzun önek) birebir kalır."""
        if not name:
            return "", ""
        if name in self.brains:
            return "brain", name
        if name.startswith(BRAIN_PREFIX):
            # `degnekci*` ailesi ad kuralıyla rezerve (`reserved_reason`): sahipsiz olsa da (kimliği çıkarılmış ama beyni hâlâ
            # çalışan `degnekci_kitap`) kullanıcının ad hoc oturumu DEĞİL, başka bir beyindir (`brain_other`: işaretleri
            # taranmaz, cevap iletilmez).
            return "brain", name
        for s, rec in self.services.items():
            if name == s or ((rec or {}).get("match") != "exact" and name.startswith(s)):
                return "service", s
        cands = set(self.owners) | set(self.conflicts)
        if name in cands:
            return "project", name
        longest = ""
        dated = ""
        for p in cands:
            if not name.startswith(p):
                continue
            if len(p) > len(longest):
                longest = p
            if _DATE8_RE.match(name[len(p):len(p) + 8]) and len(name) >= len(p) + 8 and len(p) > len(dated):
                dated = p
        if dated and dated != longest and self._owner_tag(dated) != self._owner_tag(longest):
            return "project", dated
        return ("project", longest) if longest else ("", "")

    def _class(self, kind: str, key: str) -> str:
        if kind == "brain":
            return "brain_own" if self.brains.get(key) == self.sid else "brain_other"
        if kind == "service":
            return "service"
        if kind == "project":
            if key in self.conflicts:
                return "conflict"
            owner = self.owners.get(key, "")
            return "own" if owner == self.sid else ("other" if owner else "adhoc")
        return "adhoc"

    def name_class(self, name: str) -> str:
        """Yalnız ada göre sınıf (blueprint'siz; ör. `ho_pending`'deki görünümü olmayan adlar)."""
        return self._class(*self.resolve(name))

    def session_class(self, name: str, blueprint: Optional[str] = None) -> str:
        """Ad + (varsa) instance blueprint'i. Blueprint yalnız TAM adla bakılır ve ancak REDDEDEBİLİR ya da `adhoc`'u
        `own`'a çevirebilir: ad A'yı, blueprint B'yi gösteriyorsa iki kimlik de dokunmaz."""
        c = self.name_class(name)
        if c in ("brain_own", "brain_other", "service"):
            return c
        b = "adhoc"
        if blueprint and blueprint != name:
            if blueprint in self.brains:
                b = "brain_other"
            elif blueprint in self.services:
                b = "service"
            elif blueprint in self.owners or blueprint in self.conflicts:
                b = self._class("project", blueprint)
        if c in _DENY:
            return c
        if b in _DENY:
            return b
        return "own" if "own" in (c, b) else "adhoc"

    def project_key(self, name: str) -> str:
        """Ad bu kimliğin projesine çözülüyorsa proje adı, değilse "" (`_project_key`'in kimlikli karşılığı)."""
        kind, key = self.resolve(name)
        return key if kind == "project" and self.owns(key) else ""


def world_for(sid: str, index: Dict[str, Any], brain_name: str = "", starts_left: Optional[int] = None) -> World:
    """`ownership_index()` çıktısından kimliğin görünümü. `brain_name`: bu kimliğin etkin beyin adı (default'ta
    `steward.brain_name` ezmesi olabilir; verilmezse `brain_name_for`). SAF."""
    brains = {n: s for n, s in (index.get("brains") or {}).items() if s != sid}
    brains[brain_name or brain_name_for(sid)] = sid
    return World(sid=sid, owners=dict(index.get("owners") or {}), conflicts=frozenset(index.get("conflicts") or ()),
                 brains=brains, services=dict(index.get("services") or {}), is_adhoc_owner=(sid == "default"),
                 starts_left=starts_left, hosts=dict(index.get("hosts") or {}))


def select_rows(rows: List[Dict[str, Any]], world: World, fresh_hosts: Any = ()) -> List[Dict[str, Any]]:
    """`/api/status` satırlarından değnekçinin göreceği oturumlar. SAF. Yerel satır (`host` yok/`local`) dahil; istisna:
    adı (ya da instance blueprint'i) UZAK host'lu bir projeye çözülüyorsa düşer (o proje orada yaşar, buradaki aynı adlı
    oturum onun değil). Uzak satır YALNIZ: ad bir projeye çözülür VE o projenin host'u satırın host'u VE host taze
    (`fresh_hosts`) ise. Uzak beyin/servis/kayıtsız satır HEP düşer (uzaktaki `degnekci` bizim beynimiz sanılmasın).
    Görünümlerde ad tekil kalır: bir ad ya yerelden ya da projesinin host'undan gelir."""
    fresh = set(fresh_hosts or ())
    out: List[Dict[str, Any]] = []
    for r in rows:
        host = normalize_host(r.get("host"))
        name = str(r.get("name") or "")
        kind, key = world.resolve(name)
        proj_host = world.host_of(key) if kind == "project" else ""
        if not host:
            bp = r.get("blueprint") if r.get("instance") else None
            if proj_host or (bp and bp != name and world.host_of(bp)):
                continue
            out.append(r)
        elif kind == "project" and proj_host == host and host in fresh:
            out.append(r)
    return out


def _sibling_running(views: List[SessionView], name: str, projects: Dict[str, "Project"], cfg: "Config",
                     world: Optional[World] = None) -> bool:
    """`name`in projesinin BAŞKA bir çalışan oturumu var mı (beyin sayılmaz, kayıtsız proje = hayır)."""
    if world is not None:
        key = world.project_key(name)
        return bool(key) and any(x.running and x.name != name and x.name != cfg.brain_name
                                 and world.resolve(x.name) == ("project", key) for x in views)
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


def handover_defer_decision(v: "SessionView", cfg: "Config", now: float, since: Optional[float],
                            tokens: Optional[int] = None, warn: int = 0) -> Tuple[str, str]:
    """Eşiği aşmış oturumun devri ŞİMDİ mi: ("go" | "defer" | "force", neden). SAF.
    Oturum meşgulse (`busy` kesin True), alt ajanı çalışıyorsa ya da alt ajan durumu bilinmiyorsa devir ertelenir
    (devir yeni konuşma açar; arkadaki ajanın sonucu kaybolurdu). Sert tavan: bağlam eşiğin `handover_force_ratio`
    katını aştıysa (yalnız token biliniyorsa) ya da erteleme `since`ten beri `handover_defer_max_minutes` dakikayı
    aştıysa "force". `handover_defer_max_minutes` 0 = erteleme kapalı (her zaman "go")."""
    why = ",".join(n for n, on in (("busy", v.busy is True), ("subagent_active", bool(v.subagent_active)),
                                   ("subagent_unknown", bool(v.subagent_unknown))) if on)
    if not why or cfg.handover_defer_max_minutes <= 0:
        return "go", ""
    ratio = float(cfg.handover_force_ratio or 0)
    if tokens and warn and ratio > 0 and tokens >= warn * ratio:
        return "force", f"{why}; context {tokens} >= {ratio:g} x {warn}"
    if since is not None and (now - since) >= cfg.handover_defer_max_minutes * 60:
        return "force", f"{why}; deferred {int((now - since) // 60)} min >= {cfg.handover_defer_max_minutes}"
    return "defer", why


# ── kontrollü kapatma (`steward shutdown`, SAF çekirdek) ───────────────────────

SHUTDOWN_QUIET_SECONDS = 60.0          # ana transkript + alt ajanlar bu kadar sessizse "iş bitti"
SHUTDOWN_WAIT_MAX_SECONDS = 45 * 60    # iş bitmezse bu süreden sonra oturum AÇIK bırakılır (zorlanmaz)
SHUTDOWN_HO_MAX_SECONDS = 10 * 60      # devir cevabı gelmezse oturum AÇIK bırakılır
_SD_TERMINAL = ("closed", "kept", "gone", "busy_left", "ho_timeout")


def plan_shutdown(views: List[SessionView], projects: Dict[str, Project], sd: Dict[str, Any], cfg: Config, now: float,
                  world: Optional[World] = None, blockers: Optional[Dict[str, str]] = None) -> Tuple[List[Action], Dict[str, Any], bool]:
    """Kontrollü kapatma adımı. `sd`: {started, items: {ad: {stage, at}}}; dönen: (eylemler, yeni sd, bitti mi).
    Sıra: proje oturumları (iş sessiz → devir mesajı → asistan "READY FOR HANDOVER" dedi → durdur), SONRA beyin.
    Zorlamaz: iş bitmeyen / devir cevaplamayan oturum açık bırakılır (`busy_left`/`ho_timeout`).
    `blockers`: {oturum adı: sebep}: sessizlik tek başına "iş bitti" sayılmasın (ör. açık varaka işi bekleyen oturum); bu oturumlar
    devir almaz, bekleme süresi dolarsa `busy_left` olur. SAF."""
    blockers = blockers or {}
    sd = json.loads(json.dumps(sd or {}))
    modes: Dict[str, str] = sd.get("modes") or {}      # {oturum adı: "stop"|"keep"}; yoksa "stop"
    sd.setdefault("started", now)
    items: Dict[str, Dict[str, Any]] = sd.setdefault("items", {})
    by_name = {v.name: v for v in views}
    own = world.own_projects(projects) if world is not None else projects

    def _is_own(v: SessionView) -> bool:
        if v.name == cfg.brain_name or not v.running:
            return False
        if world is not None:
            return world.session_class(v.name, v.blueprint) == "own"
        return v.project in own

    if not sd.get("init"):
        sd["init"] = True
        for v in views:
            if _is_own(v):
                items[v.name] = {"stage": "wait", "at": now}
    brain = by_name.get(cfg.brain_name)
    actions: List[Action] = []

    def _step(name: str) -> None:
        it = items[name]
        v = by_name.get(name)
        if it["stage"] in _SD_TERMINAL:
            return
        if v is None or not v.running:
            it["stage"], it["at"] = "gone" if it["stage"] == "wait" else "closed", now
            return
        if it["stage"] == "wait":
            quiet = (now - max(v.last_activity, 0.0)) >= SHUTDOWN_QUIET_SECONDS if v.last_activity else True
            if name in blockers:
                it["blocked"] = blockers[name]
            else:
                it.pop("blocked", None)
            if v.busy is not True and not v.subagent_active and not v.subagent_unknown and quiet and name not in blockers:
                actions.append(Action("handover", name, "shutdown"))
                it["stage"], it["at"] = "ho", now
            elif now - float(sd["started"]) >= SHUTDOWN_WAIT_MAX_SECONDS:
                it["stage"], it["at"] = "busy_left", now
        elif it["stage"] == "ho":
            ready = READY_FOR_HANDOVER in (v.last_assistant or "") and v.last_activity >= float(it["at"])
            if ready and v.busy is not True:
                if modes.get(name) == "keep":      # devir alındı, oturum AÇIK kalır (yalnız dur)
                    it["stage"], it["at"] = "kept", now
                else:
                    actions.append(Action("stop", name, "shutdown"))
                    it["stage"], it["at"] = "closed", now
            elif now - float(it["at"]) >= SHUTDOWN_HO_MAX_SECONDS:
                it["stage"], it["at"] = "ho_timeout", now

    for name in list(items):
        if name != cfg.brain_name:
            _step(name)
    projects_done = all(i["stage"] in _SD_TERMINAL for n, i in items.items() if n != cfg.brain_name)
    if projects_done:
        if brain is not None and brain.running and cfg.brain_name not in items:
            items[cfg.brain_name] = {"stage": "wait", "at": now}
        if cfg.brain_name in items:
            _step(cfg.brain_name)
    done = projects_done and all(i["stage"] in _SD_TERMINAL for i in items.values())
    return actions, sd, done


_CTX_Q_SESSION_RE = re.compile(r"bu oturum|this session", re.I)
_CTX_Q_HANDOVER_RE = re.compile(r"devir|yeni oturum|handover|new session", re.I)
_CTX_Q_EXCLUDE_RE = re.compile(r"commit|push|merge|deploy|force|\bsil|delete", re.I)   # sahip kararları otomatik cevaplanmaz


def is_context_question(text: str) -> bool:
    """'Bu oturumda mı sürdüreyim, devir notuyla yeni oturuma mı bırakayım?' kalıbı: cevabı bağlam ölçümünden çıkar."""
    t = text or ""
    return bool(_CTX_Q_SESSION_RE.search(t) and _CTX_Q_HANDOVER_RE.search(t) and not _CTX_Q_EXCLUDE_RE.search(t))


def context_answer(tokens: int, warn: int, ratio: float, lang: str = "tr") -> Tuple[bool, str]:
    """(devir_gerekli, cevap metni). Bağlam devir eşiğinin `ratio` oranını aşmışsa devir, aksi halde bu oturumda sürdür."""
    pct = int(round(100.0 * tokens / warn)) if warn else 0
    ho = bool(warn) and tokens >= ratio * warn
    k = f"{tokens // 1000}K/{warn // 1000}K"
    if lang == "en":
        return ho, (f"Hand over first: context {k} ({pct}% of the handover threshold). The handover message is being sent now; "
                    f"the new session continues from the handover note. Start no new work here, write the note."
                    if ho else f"Continue in this session (context {k}, {pct}% of the handover threshold: far from it).")
    return ho, (f"Önce devir: bağlam {k} (devir eşiğinin %{pct}'i). Devir mesajı şimdi gönderiliyor; yeni oturum devir notuyla sürdürür. "
                f"Burada yeni iş başlatma, devir notunu yaz." if ho
                else f"Bu oturumda sürdür (bağlam {k}, devir eşiğinin %{pct}'i: eşiğe uzak).")


def tour_delivery(prompt: str, workspace: str, now: float, lang: str = "tr") -> Tuple[str, str]:
    """(gönderilecek mesaj, yazılan dosya yolu ya da ""). Kısa tur olduğu gibi gider; uzunsa `<workspace>/tours/tour-<ts>.md`
    dosyasına yazılır (çalışma alanı içinde: beynin okuma izni var) ve mesaj yalnız dosya yolunu gösterir. Eski dosyalar budanır."""
    if len(prompt) <= TOUR_INLINE_MAX_CHARS:
        return prompt, ""
    d = os.path.join(workspace, "tours")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "tour-%d.md" % int(now))
    with open(path, "w", encoding="utf-8") as f:
        f.write(prompt)
    for old in sorted(os.listdir(d))[:-TOUR_FILES_KEEP]:
        try:
            os.remove(os.path.join(d, old))
        except OSError:
            pass
    if lang == "en":
        msg = (f"[tour] The items are long, so they are in a file: {path} . Read the WHOLE file first (Read tool), then act on each "
               f"item with the matching tool exactly as the file says. Do not answer from this message alone.")
    else:
        msg = (f"[tur] Maddeler uzun olduğu için dosyada: {path} . Önce dosyanın TAMAMINI oku (Read aracı), sonra dosyada yazdığı gibi "
               f"her madde için ilgili aracı çağır. Yalnız bu mesaja bakarak cevap verme.")
    return msg, path

DIRECTIVE_MIN_GAP_SECONDS = 90.0     # aynı oturuma iki direktif arası: cevap teslimi ile beyin direktifi çarpışmasın

# Sahibin kararı olan konular: beyin bunlara `steward_answer` ile ASLA cevap vermez (soru rutin etiketli olsa bile).
OWNER_ONLY_RE = re.compile(r"commit|push|merge|deploy|force|install|kurulum|kurul|\bsil|delete|harca|spend|password|parola|token|yetki|credential", re.I)


def brain_may_answer(q: "Question") -> Tuple[bool, str]:
    """Beynin bu soruya `steward_answer` ile cevap verip veremeyeceği: yalnız RUTİN etiketli ve sahip kararı içermeyen
    sorular. SAF; kod, commit/push, kurulum, silme, harcama, kimlik/yetki sahibe aittir."""
    if not q.routine:
        return False, "owner question (STEWARD-ASK): only the owner answers it"
    if OWNER_ONLY_RE.search(q.text or ""):
        return False, "owner decision (commit/push/install/delete/spend/credentials): only the owner answers it"
    return True, ""


def directive_defer_reason(busy: Optional[bool], last_directive_at: float, now: float,
                           gap: float = DIRECTIVE_MIN_GAP_SECONDS) -> str:
    """Beyin direktifi şimdi gönderilmemeli mi: oturum meşgulse ya da az önce başka bir direktif/cevap gittiyse sebep, yoksa "". SAF."""
    if busy is True:
        return "busy"
    if last_directive_at and (now - last_directive_at) < gap:
        return "recent"
    return ""


# ── generic rolü (2026-10-22, TODO (20)): normal kimlik + Sonnet medium varsayılanı + üst model onay kapısı ──

GENERIC_MODEL = "claude-sonnet-5-5"
GENERIC_EFFORT = "medium"
UPPER_MODEL_RE = re.compile(r"opus|fable", re.I)
UPPER_EFFORTS = frozenset({"high", "xhigh", "max"})
UPPER_MODEL_SOURCE = "upper_model"      # onay sorusunun `source`u (beyin cevaplayamaz: rutin değil)
APPROVE_WORDS = frozenset({"onayla", "onay", "onaylıyorum", "evet", "approve", "approved", "yes"})
GENERIC_BACKLOG_ITEMS = 6
_TODO_DONE_RE = re.compile(r"^\[[xX✓]\]|\b(?:DONE|BİTTİ|bitti|tamamlandı)\b|~~")
_TBD_DECIDED_RE = re.compile(r"\b(?:karar|decided|decision|cevap|answer|onaylandı|approved|kapandı|resolved)\s*[:=]|✓|✅", re.I)


def is_generic(cfg: Any) -> bool:
    return getattr(cfg, "role", "") == "generic"


def is_upper_tier(model: str, effort: str) -> bool:
    """Ana oturum için üst kademe mi: Opus/Fable modeli ya da high/xhigh/max effort. SAF."""
    return bool(UPPER_MODEL_RE.search(model or "")) or (effort or "").strip().lower() in UPPER_EFFORTS


def upper_tier_tag(project: str, model: str, effort: str) -> str:
    """Onay sorusunun metnine gömülen imza (onay YALNIZ bu proje + model + effort üçlüsü için geçerli)."""
    return f"[upper-model project={project} model={model or '-'} effort={effort or '-'}]"


def upper_tier_question_text(project: str, model: str, effort: str, lang: str = "tr") -> str:
    tag = upper_tier_tag(project, model, effort)
    if lang == "en":
        return (f"{tag} The steward wants to run the MAIN session of '{project}' with model {model or '-'} / effort "
                f"{effort or '-'} (above Sonnet medium). Approve? Until approved it stays on Sonnet medium.")
    return (f"{tag} Değnekçi '{project}' ANA oturumunu {model or '-'} / {effort or '-'} ile çalıştırmak istiyor "
            f"(Sonnet medium üstü). Onaylıyor musun? Onaya kadar Sonnet medium sürer.")


def upper_tier_approved(questions: List["Question"], project: str, model: str, effort: str) -> bool:
    """Sahip bu proje + model + effort için üst kademeyi onayladı mı (cevaplanmış `upper_model` sorusu, onay kelimesi). SAF."""
    tag = upper_tier_tag(project, model, effort)
    for q in questions:
        if q.status == "answered" and q.source == UPPER_MODEL_SOURCE and tag in (q.text or ""):
            if (q.answer or "").strip().lower().rstrip(".!") in APPROVE_WORDS:
                return True
    return False


def generic_backlog(todo_text: str = "", tbd_text: str = "", card: Optional[Dict[str, Any]] = None) -> Dict[str, List[str]]:
    """generic tur maddesi için iş listesi: `auto` = kullanıcı cevabı gerektirmeyen (otonom ilerletilebilir) adaylar,
    `decide` = karar gerektiren (beyin ATLAR, sahibe sorar). Kaba ve SAF: TODO.md madde satırları (biten/üstü çizili hariç;
    sahibe ait iş (OWNER_ONLY_RE) `decide`e), TOBEDECIDED.md `TBD` satırları + kartın `open_tbds`i (kararı yazılmış olan
    `auto`ya, gerisi `decide`e). Son kararı beyin verir; bu yalnız bağlam."""
    auto: List[str] = []
    decide: List[str] = []

    def _add(lst: List[str], t: str) -> None:
        t = _short(t)
        if t and t not in auto and t not in decide and len(lst) < GENERIC_BACKLOG_ITEMS:
            lst.append(t)

    for ln in (todo_text or "").splitlines():
        raw = ln.strip()
        if not raw.startswith(("- ", "* ", "+ ")) and not re.match(r"^\d+[.)]\s", raw):
            continue
        t = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", raw).strip()
        if not t or _TODO_DONE_RE.search(t):
            continue
        t = re.sub(r"^\[ \]\s*", "", t)
        _add(decide if OWNER_ONLY_RE.search(t) else auto, t)
    tbds = [ln.strip().lstrip("-*+• ").strip() for ln in (tbd_text or "").splitlines()
            if "TBD" in ln and not ln.lstrip().startswith("#")]      # başlık satırı (`# TBD`) madde değil
    tbds += [str(x) for x in ((card or {}).get("open_tbds") or [])]
    for t in tbds:
        _add(auto if _TBD_DECIDED_RE.search(t) and not OWNER_ONLY_RE.search(t) else decide, t)
    return {"auto": auto, "decide": decide}


GENERIC_RULE_TR = (
    "\n## Generic değnekçi kuralları (bu kimliğin rolü `generic`)\n"
    "- Projeler panelden/CLI'dan DİNAMİK eklenir/çıkarılır; `steward_overview` güncel listeyi verir.\n"
    "- Her turda proje maddesindeki `otonom ilerletilebilir` listesinden (kart, TODO.md, kararı yazılmış TBD) sahibin cevabını "
    "GEREKTİRMEYEN EN ÖNEMLİ tek işi seç ve `steward_directive` ile ver; liste boşsa kartın sıradaki adımına bak.\n"
    "- `karar gerekir` listesindeki maddeleri ATLA: her biri için (zaten açık değilse) `steward_ask_user` ile seçenekli soru aç. "
    "Önerilen bir varsayılan olsa bile onu KENDİN UYGULAMA, projeye de \"varsayılanı uygula\" deme; cevap gelince motor iletir.\n"
    "- Model: ana oturum HEP `claude-sonnet-5-5` + `medium`; model/effort alanını boş bırakırsan zaten budur. Opus/Fable ya da "
    "high/xhigh/max effort'a çeken directive/restart/set_project çağrısı sahibin onayı yoksa REDDEDİLİR (`upper_model_needs_approval`) "
    "ve motor sahibe onay sorusu açar; reddi tekrarlama, aynı işi model vermeden Sonnet medium ile sürdür. Onay gelince (soru "
    "cevaplanınca) aynı model/effort ile yeniden deneyebilirsin.\n"
    "- Ağır işi alt ajana (fork) ver ve direktife modelini AÇIK yaz: araştırma/çekme/doğrulama = Sonnet. Opus ya da Fable alt ajanı "
    "da bu kimlikte YALNIZ sahibin onayıyla (`steward_ask_user`); onaya kadar Sonnet alt ajanla ilerle.\n"
    "- Commit/push/merge/deploy/silme/harcama yine sahibin; bunları direktifle isteme, `steward_answer` ile onaylama.\n"
)
GENERIC_RULE_EN = (
    "\n## Generic steward rules (this identity's role is `generic`)\n"
    "- Projects are added/removed DYNAMICALLY from the panel/CLI; `steward_overview` has the current list.\n"
    "- On each tour pick from the project item's `autonomous` list (card, TODO.md, TBDs with a recorded decision) the single MOST "
    "important task that does NOT need the owner's answer and send it with `steward_directive`; if the list is empty use the card's next step.\n"
    "- SKIP the items under `needs a decision`: for each one (unless already open) open a question with options via `steward_ask_user`. "
    "Even if a default is suggested, NEVER apply it yourself and never tell the project to apply it; the engine delivers the answer.\n"
    "- Model: the main session is ALWAYS `claude-sonnet-5-5` + `medium`; leaving model/effort empty gives exactly that. A "
    "directive/restart/set_project that raises it to Opus/Fable or high/xhigh/max effort is REFUSED without the owner's approval "
    "(`upper_model_needs_approval`) and the engine opens an approval question; do not retry the refusal, continue the same work on "
    "Sonnet medium without a model. Once the question is answered with approval you may retry with that model/effort.\n"
    "- Give heavy work to a sub-agent (fork) and write its model EXPLICITLY in the directive: research/fetching/verification = Sonnet. "
    "Opus or Fable sub-agents also need the owner's approval in this identity (`steward_ask_user`); until then use Sonnet sub-agents.\n"
    "- Commit/push/merge/deploy/delete/spending stay with the owner; never request them in a directive or approve them with `steward_answer`.\n"
)


def marker_record_actions(name: str, proj: str, m: Dict[str, Any]) -> List[Action]:
    """Oturum yanıtındaki soru/rutin/takıldım/fikir işaretlerinin KAYIT eylemleri (oturuma dokunmaz). `plan_tick` ve
    döngü kapalıyken çalışan `plan_markers` aynı kuralı paylaşır."""
    out: List[Action] = []
    for q in m["asks"]:
        out.append(Action("ask_user", name, "STEWARD-ASK", {"project": proj or name, "text": q}))
    for q in m["routines"]:
        if "?" not in q:
            continue   # "bekliyorum, yeni soru yok" gibi durum cümlesi soru değil: kayda da girmez, sahibine de gitmez
        out.append(Action("ask_user", name, "STEWARD-ROUTINE", {"project": proj or name, "text": q, "routine": True}))
    for j in m.get("jobs", []):   # iş isteği: beyin turunda rutin madde olarak görünür, `steward_job_submit` + `steward_answer` ile kapanır
        out.append(Action("ask_user", name, "STEWARD-JOB", {"project": proj or name, "text": JOB_REQUEST_PREFIX + j, "routine": True}))
    for b in m["blocked"]:
        out.append(Action("ask_user", name, "STEWARD-BLOCKED", {"project": proj or name, "text": ("Takıldım: " + b)}))
    for i in m["ideas"]:
        out.append(Action("idea", name, "STEWARD-IDEA", {"text": i}))
    return out


def plan_markers(views: List[SessionView], projects: Dict[str, Project], state: Dict[str, Any], cfg: Config,
                 world: Optional[World] = None) -> Tuple[List[Action], Dict[str, Any]]:
    """Değnekçi KAPALIYKEN çalışan salt kayıt taraması: `plan_tick` adım 3'ün yalnız soru/fikir kısmı. Faz değiştirme,
    durdurma, iletim, başlatma YOK; yalnız `ask_user`/`idea` eylemleri ve `seen_assistant` güncellenir (kapalıyken
    düşen STEWARD-ASK kaybolmasın; açılınca ayrıca taranmasına gerek kalmasın). SAF."""
    if world is not None:
        projects = world.own_projects(projects)
    st: Dict[str, Any] = json.loads(json.dumps(state)) if state else {}
    seen: Dict[str, str] = dict(st.get("seen_assistant") or {})
    actions: List[Action] = []
    for v in views:
        if not v.running or not v.last_assistant or v.name == cfg.brain_name:
            continue
        if world is not None:
            cls = world.session_class(v.name, v.blueprint)
            if cls != "own" and not (cls == "adhoc" and world.is_adhoc_owner):
                continue
        digest = hashlib.sha1(v.last_assistant.encode('utf-8', 'replace')).hexdigest()[:16]
        if seen.get(v.name) == digest:
            continue
        seen[v.name] = digest
        proj = v.project if v.project in projects else ""
        actions.extend(marker_record_actions(v.name, proj, scan_markers(v.last_assistant)))
    st["seen_assistant"] = seen
    return actions, st


def plan_tick(views: List[SessionView], projects: Dict[str, Project], state: Dict[str, Any], cfg: Config,
              now: float, questions: List[Question], ideas: List[Idea],
              world: Optional[World] = None) -> Tuple[List[Action], Dict[str, Any]]:
    """Bir tick'in kararları. SAF: hiçbir yan etki yok; `state`'in GÜNCELLENMİŞ kopyasını döner
    (motor kaydeder). Sıra: ekonomi (handover/respawn) → işaretler → cevap iletimi → uğrama/başlatma →
    slot baskısı → beyin turu.

    `world` (çoklu değnekçi): verilmezse eski davranış birebir. Verilirse `projects` kimliğin sahip olduğu
    (çakışmasız) projelere süzülür; başka kimliğin projesi/beyni, servis ve çakışmalı proje oturumuna HİÇBİR eylem
    üretilmez; kayıtsız oturumun işaretlerini ve ad hoc cevap iletimini yalnız `is_adhoc_owner` (default) işler;
    slot `max_active` yanında makine geneli `max_active_total` (diğer kimliklerin çalışan projeleri dahil) ve
    `world.starts_left` ile sınırlanır. Uzak projelerin oturumları (`SessionView.host`) aynı kurallardan geçer ve
    sayımlara girer; `world.unavailable` projeleri için başlatma üretilmez, görünümleri yok diye devir/DONE izleri
    silinmez. `subagent_unknown` görünümde STEWARD-DONE ertelenir (bilinmiyor = boşta değil)."""
    if world is not None:
        projects = world.own_projects(projects)
    bp = {v.name: v.blueprint for v in views if v.blueprint}

    def _mine(v: SessionView) -> bool:
        """Görünüm bu kimliğin proje oturumu mu (eski yol: `_is_project_session`)."""
        return _is_project_session(v, projects) and (world is None or world.session_class(v.name, v.blueprint) == "own")

    st: Dict[str, Any] = json.loads(json.dumps(state)) if state else {}
    ho_pending: Dict[str, float] = dict(st.get("ho_pending") or {})
    seen: Dict[str, str] = dict(st.get("seen_assistant") or {})
    done_pending: Dict[str, str] = dict(st.get("done_pending") or {})
    last_directive_at: Dict[str, float] = dict(st.get("last_directive_at") or {})
    reviewed_at: Dict[str, float] = dict(st.get("reviewed_at") or {})
    actions: List[Action] = []
    by_name = {v.name: v for v in views}
    busy_names: set = set()   # bu tick'te zaten dokunulan oturumlar (ikinci bir eylem gönderme)

    def _unavail(name: str) -> bool:
        """Ad, host'u şu an erişilemeyen bir projeye çözülüyor mu (görünümü yok diye "kapandı" sayılmaz)."""
        return world is not None and bool(world.unavailable) and world.project_key(name) in world.unavailable

    # 1) Oturum ekonomisi — scrollback eşiği → handover (beyin dahil: onun da scrollback'i dolar)
    def _managed(name: str) -> bool:
        # Oturum ekonomisi (handover/yeniden açma) YALNIZ değnekçinin yönettiği oturumlara: beyin + kayıtlı proje
        # oturumları. Kullanıcının diğer oturumlarına (egyptian.., oa.., cops..) mesaj gönderilmez, yeniden açılmaz.
        if name == cfg.brain_name:
            return True
        if world is None:
            return bool(_project_key(name, projects))
        # Ad bu kimliğin projesine çözülmeli (eski önek kuralı, global) VE blueprint başkasını göstermemeli
        return bool(world.project_key(name)) and world.session_class(name, bp.get(name)) == "own"

    # Eşik devri ertelemesi (`handover_defer_decision`): {oturum: {since, why}}; tick-arası iz (done_pending gibi).
    # Yenilenmeyen kayıt (eşiğin altına indi, kapandı, devir başladı) düşer.
    ho_deferred_prev: Dict[str, Dict[str, Any]] = dict(st.get("ho_deferred") or {})
    ho_deferred: Dict[str, Dict[str, Any]] = {}

    def _threshold_handover(v: SessionView, reason: str, tokens: Optional[int], warn: int) -> bool:
        """Eşik devri: ertelenecekse kayıt (`handover_deferred` eylemi yalnız ilk ertelemede ya da neden değişince) +
        oturum bu tick'te başka eylem almaz; değilse devir. Dönen: devir başladı mı."""
        prev = ho_deferred_prev.get(v.name)
        since = float(prev.get("since") or now) if isinstance(prev, dict) else None
        verdict, why = handover_defer_decision(v, cfg, now, since, tokens, warn)
        busy_names.add(v.name)
        if verdict == "defer":
            ho_deferred[v.name] = {"since": since if since is not None else now, "why": why}
            if not isinstance(prev, dict) or prev.get("why") != why:
                actions.append(Action("handover_deferred", v.name, why, {"handover_reason": reason}))
            return False
        # Gerekçe eki yalnız önceden ertelenmiş devirde (ertelemesiz ilk tick'teki zorlama eski metinle aynı kalır: altın kayıt)
        if since is not None:
            reason = f"{reason} (zorla: {why})" if verdict == "force" else f"{reason} (ertelenmişti)"
        actions.append(Action("handover", v.name, reason))
        ho_pending[v.name] = now
        return True

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
                _threshold_handover(v, f"context {v.context_tokens} token >= {warn_tokens}", v.context_tokens, warn_tokens)
        elif v.history_size is not None and v.history_size >= cfg.history_warn_at:
            young = (cfg.history_min_age_minutes and v.started_at
                     and (now - v.started_at) < cfg.history_min_age_minutes * 60)
            if not young:
                _threshold_handover(v, f"history_size {v.history_size} >= {cfg.history_warn_at}", None, 0)

    # 1b) Bağlam sorusu: "bu oturumda mı sürdüreyim, devirle mi" sahibine/beyne sorulmaz; bağlam ölçümünden motor cevaplar.
    # Eşiğe yakınsa aynı tick'te devir de başlar (oturum kendini kapatıp açamaz; devri motor yürütür).
    if cfg.auto_context_answer:
        for q in questions:
            if q.status != "open" or not is_context_question(q.text):
                continue
            v = by_name.get(q.source)
            if v is None or not v.running or not v.tmux or not v.context_tokens or not _managed(v.name):
                continue
            warn = context_threshold(cfg, v.model)
            if not warn or v.name in ho_pending or v.name in busy_names:
                continue
            ho, text = context_answer(v.context_tokens, warn, cfg.auto_context_ratio, cfg.lang)
            if not ho:
                actions.append(Action("auto_answer", v.name, "context", {"question_id": q.id, "answer": text, "handover": False}))
                continue
            # "Önce devir" cevabı devirle birlikte gider; devir ertelenirse soru da açık kalır (sonraki tick yeniden karar)
            mark = len(actions)
            if _threshold_handover(v, f"context soru: {v.context_tokens} token >= {int(cfg.auto_context_ratio * warn)}",
                                   v.context_tokens, warn):
                actions.insert(mark, Action("auto_answer", v.name, "context", {"question_id": q.id, "answer": text, "handover": True}))

    for name, rec in ho_deferred_prev.items():      # host kapalı: görünümü yok diye erteleme izi silinmez
        if name not in ho_deferred and name not in by_name and _unavail(name):
            ho_deferred[name] = rec

    # 2) Handover gönderilmiş olanlar — READY FOR HANDOVER geldi ya da süre doldu → yeniden aç
    for name, sent_at in list(ho_pending.items()):
        if not _managed(name):
            ho_pending.pop(name, None)   # yönetilmeyen oturum (eski kayıt/elle): yeniden AÇILMAZ
            continue
        if name in busy_names:
            continue
        v = by_name.get(name)
        if v is None and _unavail(name):
            continue     # host kapalı: devir izi korunur, yeniden açma host dönünce kararlaştırılır
        if v is None or not v.running:
            if not _sibling_running(views, name, projects, cfg, world):
                actions.append(Action("respawn", name, "handover sent, session gone → start"))
            ho_pending.pop(name, None)
            busy_names.add(name)
            continue
        ready = READY_FOR_HANDOVER in (v.last_assistant or "")
        expired = (now - float(sent_at)) >= cfg.ho_grace_minutes * 60
        # busy None (bu CLI'da sinyal yok) = "meşgul değil" sayılır; yalnız kesin True bekletir
        if v.busy is not True and (ready or expired):
            if _sibling_running(views, name, projects, cfg, world):
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
        if world is not None:
            # Yalnız KENDİ proje oturumları; kayıtsız oturumu yalnız default işler (K9): başka kimliğin projesi/beyni,
            # servis ve çakışmalı proje oturumunun işaretleri bu kimliğe soru/fikir olarak düşmez.
            cls = world.session_class(v.name, v.blueprint)
            if cls != "own" and not (cls == "adhoc" and world.is_adhoc_owner):
                continue
        digest = hashlib.sha1(v.last_assistant.encode('utf-8', 'replace')).hexdigest()[:16]
        if seen.get(v.name) == digest:
            continue
        seen[v.name] = digest
        m = scan_markers(v.last_assistant)
        proj = v.project if v.project in projects else ""
        actions.extend(marker_record_actions(v.name, proj, m))
        if proj and m["plan_ready"] and projects[proj].phase == "planning":
            actions.append(Action("set_phase", proj, "STEWARD-PLAN-READY", {"phase": "planned"}))
        if proj and m["done"] and done_blocked(projects[proj]):
            pass    # sürekli geliştirme projesi: bir iş paketinin bitişi (devir mesajı dahil) projeyi `done` yapmaz
        elif proj and m["done"]:
            if v.subagent_active or v.subagent_unknown:
                # Alt ajan hâlâ çalışıyor: işaret erken (wifi5g, Aşama 3 cila sürerken `done` oldu). Ertele; ajan bitince uygulanır.
                done_pending[v.name] = proj
            else:
                actions.append(Action("set_phase", proj, "STEWARD-DONE", {"phase": "done"}))
                if v.name not in busy_names:
                    actions.append(Action("stop", v.name, "STEWARD-DONE"))
                    busy_names.add(v.name)

    for name, proj in list(done_pending.items()):    # ertelenmiş STEWARD-DONE: alt ajan sustu mu?
        v = by_name.get(name)
        if v is None and _unavail(name):
            continue
        if v is None or not v.running or proj not in projects or done_blocked(projects[proj]):
            done_pending.pop(name, None)    # (NO_DONE_TAG ertelemeden SONRA eklenmiş olabilir: yeniden denetle)
        elif not v.subagent_active and not v.subagent_unknown and v.busy is not True and name not in busy_names:
            actions.append(Action("set_phase", proj, "STEWARD-DONE (ertelenmişti)", {"phase": "done"}))
            actions.append(Action("stop", name, "STEWARD-DONE (ertelenmişti)"))
            busy_names.add(name)
            done_pending.pop(name, None)

    # 4) Cevaplanmış sorular → ilgili oturuma ilet (kapalıysa aç)
    starts = 0
    running_projects = {v.project for v in views if v.running and _mine(v)}
    active = len(running_projects)
    max_starts = 0 if cfg.drain else cfg.max_starts_per_tick
    others_active = 0
    if world is not None:
        if world.starts_left is not None:
            max_starts = max(0, min(max_starts, world.starts_left))
        if cfg.max_active_total > 0:
            # Makine geneli sınır: başka kimliklerin çalışan (çakışmasız) proje oturumları da sayılır
            busy_other = set()
            for x in views:
                if not x.running:
                    continue
                if x.blueprint and x.blueprint in world.owners:
                    key = x.blueprint
                else:
                    kind, key = world.resolve(x.name)
                    if kind != "project":
                        continue
                owner = world.owner_of(key)
                if owner and owner != world.sid:
                    busy_other.add(key)
            others_active = len(busy_other)

    def _slots() -> int:
        n = cfg.max_active - active - starts
        if world is not None and cfg.max_active_total > 0:
            n = min(n, cfg.max_active_total - active - others_active - starts)
        return n
    deliver_by_session: Dict[str, Action] = {}
    for q in undelivered_answers(questions):
        target = q.project
        if not target or target == cfg.brain_name:
            # Genel/beyin sorusu: beyin turunda gösterilir (aşağıda), oturuma iletilmez
            continue
        if target not in projects:
            # Kayıtlı proje olmayan (ad hoc) oturumun sorusu: cevap, soruyu açan oturum hâlâ çalışıyorsa ona gider
            # (eskiden sessizce iletilmiyordu: sahibi cevap yazıyor, oturum hiç görmüyordu); çalışmıyorsa beklemez, atlanır.
            v = next((x for x in views if x.running and x.name == q.source and x.name != cfg.brain_name
                      and (world is None or world.session_class(x.name, x.blueprint) == "own"
                           or (world.is_adhoc_owner and world.session_class(x.name, x.blueprint) == "adhoc"))), None)
            if v is not None and v.name not in busy_names and not v.busy:
                actions.append(Action("deliver_answer", v.name, "answer", {"question_id": q.id}))
                busy_names.add(v.name)
                last_directive_at[v.name] = now
            continue
        v = pick_delivery_view(views if world is None else [x for x in views if _mine(x)], target, q.source)
        if v is not None:
            if v.name in deliver_by_session:
                deliver_by_session[v.name].payload.setdefault("more_ids", []).append(q.id)    # aynı tick, aynı oturum: birleştir
                continue
            if v.name in busy_names or v.busy or v.subagent_active:
                continue   # bir sonraki tick (çalışan alt ajan varken ana oturumu uyandırma)
            act = Action("deliver_answer", v.name, "answer", {"question_id": q.id})
            actions.append(act)
            deliver_by_session[v.name] = act
            busy_names.add(v.name)
            last_directive_at[v.name] = now
        elif starts < max_starts and _slots() > 0 and not (world is not None and target in world.unavailable):
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
        if world is not None and p.name in world.unavailable:
            continue     # host erişilemiyor: görünümü yok diye "çalışmıyor" sayılıp başlatılmaz
        if visit_of(p) == 0 or (now - visit_of(p)) >= p.cadence_minutes * 60:
            due.append(p)
    due.sort(key=lambda p: (p.priority, visit_of(p)))
    free = max(0, _slots())
    for p in due:
        if starts >= max_starts or free <= 0:
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
            if not v.running or not _mine(v) or v.name in busy_names or v.name in ho_pending:
                continue
            idle_since = max(v.last_activity, last_directive_at.get(v.name, 0.0), v.started_at)
            if v.busy is False and idle_since and (now - idle_since) >= cfg.stop_idle_minutes * 60:
                actions.append(Action("stop", v.name, f"idle ≥ {cfg.stop_idle_minutes} dk, slot bekleyen var"))
                busy_names.add(v.name)

    # 6a) API hatasında takılan oturumlar (yalnız bu kimliğin yönettiği, tmux'lu, yerel/uzak görünümler)
    api_actions, api_err, api_out = plan_api_recovery(
        views, lambda v: bool(v.tmux) and _managed(v.name), busy_names | set(ho_pending),
        dict(st.get("api_err") or {}), dict(st.get("api_outage") or {}), now)
    for a in api_actions:
        actions.append(a)
        if a.kind == "nudge":
            busy_names.add(a.name)

    # 6b) Beynin cevaplamadığı rutin soru sahibine düşer (sessizce takılı kalmasın)
    for q in questions:
        if q.status == "open" and q.routine and (now - q.created_at) >= ROUTINE_ESCALATE_SECONDS:
            actions.append(Action("escalate_routine", q.project or "-", "rutin soru cevapsız", {"question_id": q.id}))

    # 7) Beyin turu maddeleri
    items = review_items(views, projects, cfg, now, questions, ideas,
                         skip=busy_names | set(ho_pending), last_directive_at=last_directive_at, reviewed_at=reviewed_at,
                         world=world)
    last_tour = float(st.get("last_tour") or 0.0)
    brain = by_name.get(cfg.brain_name)
    tour_gap = (cfg.tour_retry_minutes if st.get("tour_deferred") else cfg.tour_minutes) * 60
    if items and (now - last_tour) >= tour_gap and brain is not None and brain.running and brain.busy is False:
        items = items[:TOUR_MAX_ITEMS]
        st.pop("tour_deferred", None)
        actions.append(Action("tour", cfg.brain_name, f"{len(items)} madde", {"items": items}))
        st["last_tour"] = now
        for it in items:
            if it["kind"] == "review":
                reviewed_at[it["name"]] = now
    st["pending_items"] = len(items)
    st["pending_list"] = [{"kind": str(it.get("kind") or ""), "name": str(it.get("name") or ""),
                           "text": str(it.get("text") or "")[:300]} for it in items[:20]]
    st["ho_pending"] = ho_pending
    st["seen_assistant"] = seen
    if done_pending:
        st["done_pending"] = done_pending
    else:
        st.pop("done_pending", None)     # boşken anahtar yazılmaz (varsayılan durum biçimi değişmez)
    if ho_deferred:
        st["ho_deferred"] = ho_deferred
    else:
        st.pop("ho_deferred", None)
    st["last_directive_at"] = last_directive_at
    st["reviewed_at"] = reviewed_at
    for key, val in (("api_err", api_err), ("api_outage", api_out)):
        if val:
            st[key] = val
        else:
            st.pop(key, None)        # boşken anahtar yazılmaz (varsayılan durum biçimi değişmez)
    st["last_tick"] = now
    return actions, st


# ── API hatası dayanıklılığı ──────────────────────────────────────────────────
# Oturum `API Error: 500/429/overloaded/Connection lost` satırında takılıp boşta kalır (alt ajanı sürerken bile); kimse
# uyandırmaz. Tek oturum: artan aralıkla "devam"; birden çok oturum aynı anda = sağlayıcı kesintisi: kimseye mesaj yok, TEK
# bildirim, 10 dk'da bir TEK oturumla yoklama, düzelince 4'lü gruplarla uyandırma (toplu uyandırma rate-limit tetikler).

_API_ERR_RE = re.compile(r"^\s*API Error:\s*(?P<body>.*)", re.I | re.S)
_API_RETRY_HEAD_RE = re.compile(r"^\s*(?:5\d\d|429)\b")
_API_RETRY_WORD_RE = re.compile(r"overloaded|connection lost|connection error|timed?[ -]?out|econnreset|socket hang up|"
                                r"internal server error|service unavailable|bad gateway|gateway time-?out|rate.?limit|temporar", re.I)
API_NUDGE_TEXT = "devam"
API_NUDGE_DELAYS = (60.0, 180.0, 600.0)   # 1., 2., 3. "devam" öncesi bekleme (ilkinde hatanın görüldüğünden, sonrakilerde önceki "devam"dan)
API_NUDGE_MAX = len(API_NUDGE_DELAYS)
API_GIVEUP_AFTER = 600.0                  # son "devam"dan sonra hâlâ takılıysa bırak + bildir
API_QUIET_SECONDS = 60.0                  # son etkinlikten bu kadar sessizse "takıldı"
API_OUTAGE_MIN = 2                        # bu kadar oturum aynı anda takılırsa = kesinti
API_OUTAGE_PROBE_SECONDS = 600.0
API_WAKE_GROUP = 4


def api_error_kind(text: str) -> str:
    """Son asistan metni için: "" (API hatası değil) | "retry" (5xx/429/overloaded/bağlantı: "devam" işe yarayabilir) |
    "fatal" (4xx ör. geçersiz istek/bağlam doldu: "devam" aynı hatayı üretir)."""
    m = _API_ERR_RE.match(str(text or ""))
    if not m:
        return ""
    body = m.group("body")[:300]
    return "retry" if (_API_RETRY_HEAD_RE.search(body) or _API_RETRY_WORD_RE.search(body)) else "fatal"


def plan_api_recovery(views: List[SessionView], eligible: Callable[[SessionView], bool], skip: Set[str],
                      st_err: Dict[str, Any], st_out: Dict[str, Any], now: float
                      ) -> Tuple[List[Action], Dict[str, Any], Dict[str, Any]]:
    """SAF. Dönen: (eylemler, yeni api_err durumu, yeni api_outage durumu). Eylem türleri: `nudge` (oturuma "devam"),
    `api_outage` (kesinti başladı: tek bildirim), `api_recovered` (kesinti bitti), `api_giveup` (3 denemede düzelmedi: bırak +
    sahibine bildir). Alt ajanı süren, meşgul ya da yakın zamanda etkinliği olan oturuma dokunulmaz."""
    actions: List[Action] = []
    err: Dict[str, Any] = {}
    stuck: List[SessionView] = []
    for v in views:
        if not v.running or v.name in skip or not eligible(v) or api_error_kind(v.last_assistant) != "retry":
            continue
        if v.busy is True or v.subagent_active or v.subagent_unknown:
            continue
        if v.last_activity and (now - v.last_activity) < API_QUIET_SECONDS:
            continue
        prev = st_err.get(v.name) if isinstance(st_err.get(v.name), dict) else {}
        # aynı hata metni sürüyorsa kayıt devam eder; metin değiştiyse (yeni hata) sayaç sıfırlanır
        h = hashlib.sha1(v.last_assistant.encode("utf-8", "replace")).hexdigest()[:10]
        rec = dict(prev) if prev.get("hash") == h else {"since": now, "nudges": 0, "last_nudge": 0.0, "gave_up": False}
        rec["hash"] = h
        err[v.name] = rec
        stuck.append(v)
    out = dict(st_out) if isinstance(st_out, dict) else {}
    live = [v for v in stuck if not err[v.name].get("gave_up")]

    def _nudge(v: SessionView, why: str) -> None:
        r = err[v.name]
        r["nudges"] = int(r.get("nudges") or 0) + 1
        r["last_nudge"] = now
        actions.append(Action("nudge", v.name, why, {"text": API_NUDGE_TEXT, "n": r["nudges"]}))

    def _due_single(v: SessionView) -> bool:
        r = err[v.name]
        n = int(r.get("nudges") or 0)
        if n >= API_NUDGE_MAX:
            return False
        base = float(r["since"]) if n == 0 else float(r["last_nudge"])
        return (now - base) >= API_NUDGE_DELAYS[n]

    def _giveup(v: SessionView) -> None:
        r = err[v.name]
        if int(r.get("nudges") or 0) >= API_NUDGE_MAX and not r.get("gave_up") and (now - float(r["last_nudge"])) >= API_GIVEUP_AFTER:
            r["gave_up"] = True
            actions.append(Action("api_giveup", v.name, f"{API_NUDGE_MAX} 'devam' sonrası hâlâ API hatasında", {}))

    if len(live) >= API_OUTAGE_MIN or (out and live):
        # kesinti: oturumlara tek tek yazma
        if not out:
            out = {"since": now, "probe": "", "probe_at": 0.0, "woken": [], "recovered": False}
            actions.append(Action("api_outage", "", f"{len(live)} oturum aynı anda API hatasında", {"names": sorted(v.name for v in live)}))
        woken = set(out.get("woken") or [])
        probe = str(out.get("probe") or "")
        if not out.get("recovered") and probe and not any(v.name == probe for v in stuck):
            out["recovered"] = True                           # yoklama oturumu ilerledi: sağlayıcı düzeldi
            actions.append(Action("api_recovered", probe, "yoklama oturumu API hatasından çıktı", {}))
        if out.get("recovered"):
            waiting = [v for v in live if v.name not in woken]
            for v in waiting[:API_WAKE_GROUP]:
                _nudge(v, "kesinti bitti, sırayla uyandırma")
                woken.add(v.name)
        elif now >= float(out.get("probe_at") or 0.0):
            cand = next((v for v in sorted(live, key=lambda x: x.name) if int(err[v.name].get("nudges") or 0) < API_NUDGE_MAX), None)
            if cand is not None:
                _nudge(cand, "kesinti yoklaması")
                out["probe"] = cand.name
                out["probe_at"] = now + API_OUTAGE_PROBE_SECONDS
        out["woken"] = sorted(woken & {v.name for v in stuck})
    else:
        if out:                                                # kesinti bitti: kalanlar tek-oturum kurallarına döner
            out = {}
        for v in live:
            if _due_single(v):
                _nudge(v, "API hatası, otomatik devam")
            else:
                _giveup(v)
    if not stuck and out:
        out = {}                                                # kimse takılı değil: kesinti kaydı düşer
    return actions, err, out


def _observe_cluster(a: Action) -> str:
    """İletim eylemlerinin (`deliver_findings`/`deliver_lesson`) `would:` tekilleştirme eki: bulgu/ders KÜMESİ. Küme
    değişmedikçe aynı kayıt yinelenmez; küme değişince (yeni bulgu, biri bitti) yeniden yazılır."""
    if a.kind == "deliver_findings":
        ids = sorted(str(r.get("id")) for r in (a.payload.get("rows") or []) if isinstance(r, dict))
    elif a.kind == "deliver_lesson":
        ids = sorted(str(h) for h in (a.payload.get("hashes") or []))
    else:
        return ""
    return hashlib.sha1("|".join(ids).encode("utf-8")).hexdigest()[:10]


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
        key = f"{a.kind}:{a.name}:{a.payload.get('question_id', '') or a.payload.get('job_id', '') or _observe_cluster(a)}"
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
