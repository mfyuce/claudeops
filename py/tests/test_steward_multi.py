"""Çoklu değnekçi P3: SAF sahiplik çekirdeği (`ownership_index`, `World`, global önek çözümü, rezerve adlar,
`plan_tick(world=...)` / `review_items(world=...)` süzgeçleri). `default`'un davranışı birebir: `world=None` eski yol,
default dünyası da (tek kimlik) aynı çıktıyı verir (altın kayıt + mevcut test girdileri üzerinde karşılaştırma).

Çalıştırma: python3 -m unittest discover -s py/tests"""
import dataclasses
import hashlib
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import steward as sw  # noqa: E402

_REAL_SETTINGS = os.path.expanduser("~/.claude/claudeops/settings.json")
_HASH_BEFORE = None


def _sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def setUpModule():
    global _HASH_BEFORE
    _HASH_BEFORE = _sha(_REAL_SETTINGS)


def tearDownModule():
    if _sha(_REAL_SETTINGS) != _HASH_BEFORE:
        raise AssertionError("gerçek ~/.claude/claudeops/settings.json test sırasında değişti")


def _view(name, **kw):
    base = dict(running=True, cwd="/tmp/x", cli="claude", busy=False, history_size=100, tmux=True,
                started_at=1000.0, last_activity=1000.0)
    base.update(kw)
    return sw.SessionView(name=name, **base)


def _cfg(**kw):
    c = sw.Config(enabled=True)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def _ser(acts, st):
    """Eylem listesi + state'in karşılaştırılabilir (JSON) biçimi. `pending_list` yalnız panelde gösterilen madde özeti
    (altın kayıttan SONRA eklendi, davranışı etkilemez): karşılaştırmaya girmez."""
    st = {k: v for k, v in st.items() if k != "pending_list"}
    return json.loads(json.dumps({"actions": [[a.kind, a.name, a.reason, a.payload] for a in acts], "state": st},
                                 sort_keys=True, default=str))


# ── altın senaryo (P3 öncesi kodla kaydedildi; girdiler DEĞİŞMEZ) ──────────────────────────────────────────────

T0 = 1_760_000_000.0


def _golden_projects():
    P = sw.Project
    return {
        "ncs": P(name="ncs", phase="planned", priority=2, cadence_minutes=60, last_visit=T0 - 7200),
        "ncs2": P(name="ncs2", phase="planning", priority=3, cadence_minutes=60),
        "wifi5gppr": P(name="wifi5gppr", phase="planned", priority=1, cadence_minutes=30, last_visit=T0 - 3600),
        "zlkrn": P(name="zlkrn", phase="planned", priority=2, cadence_minutes=240, last_visit=T0 - 600),
        "mkt": P(name="mkt", phase="paused", priority=1, cadence_minutes=60),
        "a": P(name="a", phase="planning", priority=4, cadence_minutes=30),
        "kitap": P(name="kitap", phase="planned", priority=5, cadence_minutes=60),
    }


def _golden_views(step):
    old = T0 - 3 * 3600
    vs = [
        _view("degnekci", busy=False, history_size=50, started_at=old, last_activity=T0 - 1200),
        _view("ncs20261019", busy=False, history_size=10, context_tokens=410000, started_at=old,
              last_assistant=("devir\nREADY FOR HANDOVER" if step else "çalışıyorum")),
        _view("wifi5gppr20261019", busy=False, history_size=1950, context_tokens=None, started_at=old,
              last_activity=T0 - 3600),
        _view("zlkrn", busy=True, started_at=old, last_activity=T0 - 60, model="claude-fable-5-1",
              context_tokens=200000),
        _view("egyptian20260917", busy=False, history_size=1990, context_tokens=900000,
              last_assistant="STEWARD-ASK: Hangi baskı?\nSTEWARD-IDEA: yeni bir kitap"),
        _view("a", busy=False, started_at=old, last_activity=T0 - 1800,
              last_assistant="STEWARD-PLAN-READY\nSTEWARD-ROUTINE: Opus ne zaman açılsın?\nSTEWARD-BLOCKED: PDF yok"),
        _view("degnekci_kitap", busy=False, last_assistant="STEWARD-ASK: beyin sorusu?"),
        _view("kitap_1", blueprint="kitap", busy=False, started_at=old, last_activity=T0 - 4000,
              last_assistant="STEWARD-DONE" if step else ""),
        _view("ncs2x", busy=True, started_at=old, last_activity=T0 - 100),
    ]
    if step >= 2:
        vs = [v for v in vs if v.name != "ncs20261019"]
    return vs


def _golden_questions():
    Q = sw.Question
    return [
        Q(id="q1", project="ncs", text="ncs?", created_at=T0 - 500, status="answered", answer="evet",
          answered_at=T0 - 100, source="ncs20261019"),
        Q(id="q2", project="egyptian20260917", text="eg?", created_at=T0 - 500, status="answered", answer="A",
          answered_at=T0 - 100, source="egyptian20260917"),
        Q(id="q3", project="mkt", text="mkt?", created_at=T0 - 500, status="answered", answer="B",
          answered_at=T0 - 100, source="mkt"),
        Q(id="q4", project="a", text="rutin?", created_at=T0 - 7200, routine=True, source="a"),
        Q(id="q5", project="", text="genel", created_at=T0 - 500, status="answered", answer="C", answered_at=T0 - 50),
        Q(id="q6", project="yok", text="kayıtsız kapalı", created_at=T0 - 500, status="answered", answer="D",
          answered_at=T0 - 50, source="yok20261001"),
    ]


def _golden_ideas():
    return [sw.Idea(id="i1", text="fikir", created_at=T0 - 100)]


GOLDEN_CFGS = (
    dict(max_active=4, tour_minutes=1),
    dict(max_active=2, max_starts_per_tick=2, stop_idle_minutes=30, tour_minutes=1),
    dict(max_active=6, max_starts_per_tick=3, context_warn_tokens=0, history_min_age_minutes=0),
)


def run_golden(tick):
    """`tick(views, projects, state, cfg, now, questions, ideas) -> (acts, st)`; her yapılandırma için 3 tick zinciri."""
    out = []
    for ck in GOLDEN_CFGS:
        cfg = _cfg(**ck)
        st = {"ho_pending": {"oldgone": T0 - 99999}}
        for step in range(3):
            acts, st = tick(_golden_views(step), _golden_projects(), st, cfg, T0 + step * 1200,
                            _golden_questions(), _golden_ideas())
            out.append(_ser(acts, st))
    return out


GOLDEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "steward_golden_tick.json")


def _golden():
    with open(GOLDEN_FILE, encoding="utf-8") as f:
        return json.load(f)


def _golden_world():
    """P9 O4: altın girdideki `degnekci_kitap` görünümü kimliği olmayan (çıkarılmış) bir beyindir; `world` ile planlarken
    artık kullanıcının ad hoc oturumu SAYILMAZ (`brain_other`: işareti taranmaz). `world=None` eski yol kaydı aynen korur
    (`_golden()`); `world` yolu için tek fark: o oturumun `ask_user` eylemi ve `seen_assistant` kaydı yoktur."""
    out = _golden()
    for rec in out:
        rec["actions"] = [a for a in rec["actions"] if a[1] != "degnekci_kitap"]
        rec["state"].get("seen_assistant", {}).pop("degnekci_kitap", None)
    return out


def _default_world(projects, cfg):
    return sw.world_for("default", sw.build_ownership_index({"default": list(projects)}), cfg.brain_name)


def _tick_default_world(views, projects, state, cfg, now, questions, ideas):
    return _ORIG_PLAN_TICK(views, projects, state, cfg, now, questions, ideas, world=_default_world(projects, cfg))


_ORIG_PLAN_TICK = sw.plan_tick
_ORIG_REVIEW_ITEMS = sw.review_items


class TestGolden(_Tmp):
    """P3 öncesi kodla kaydedilmiş çıktı (`steward_golden_tick.json`): 3 yapılandırma × 3 tick zinciri; devir, yeniden
    açma, durdurma, işaretler, cevap iletimi, başlatma, slot baskısı, rutin yükseltme, tur adımlarının hepsi."""

    def test_world_none_is_byte_identical(self):
        self.assertEqual(run_golden(sw.plan_tick), _golden())

    def test_default_world_is_identical(self):
        self.assertEqual(run_golden(_tick_default_world), _golden_world())

    def test_default_world_from_disk_index_is_identical(self):
        sw.save_projects(_golden_projects())
        idx = sw.ownership_index(fresh=True)
        self.assertEqual(idx["owners"], {n: "default" for n in _golden_projects()})
        self.assertEqual((idx["conflicts"], idx["brains"]), ({}, {"degnekci": "default"}))

        def tick(views, projects, state, cfg, now, questions, ideas):
            return sw.plan_tick(views, projects, state, cfg, now, questions, ideas,
                                world=sw.world_for("default", idx, cfg.brain_name))
        self.assertEqual(run_golden(tick), _golden_world())


# ── mevcut test girdileri üzerinde altın karşılaştırma: test_steward'ın TÜM sınıfları, her plan_tick/review_items
# çağrısında `world=None` ile default dünyasının çıktısı eşit olmak zorunda (fark = test başarısız) ──────────────

_CHECKED = {"plan_tick": 0, "review_items": 0}


def _plan_tick_checked(views, projects, state, cfg, now, questions, ideas, world=None):
    if world is not None:
        return _ORIG_PLAN_TICK(views, projects, state, cfg, now, questions, ideas, world=world)
    old = _ORIG_PLAN_TICK(views, projects, state, cfg, now, questions, ideas)
    new = _ORIG_PLAN_TICK(views, projects, state, cfg, now, questions, ideas, world=_default_world(projects, cfg))
    if _ser(*old) != _ser(*new):
        raise AssertionError(f"default world differs from world=None:\n{_ser(*old)}\n!=\n{_ser(*new)}")
    _CHECKED["plan_tick"] += 1
    return old


def _review_items_checked(views, projects, cfg, now, questions, ideas, *, skip=None, last_directive_at=None,
                          reviewed_at=None, world=None):
    kw = dict(skip=skip, last_directive_at=last_directive_at, reviewed_at=reviewed_at)
    if world is not None:
        return _ORIG_REVIEW_ITEMS(views, projects, cfg, now, questions, ideas, world=world, **kw)
    old = _ORIG_REVIEW_ITEMS(views, projects, cfg, now, questions, ideas, **kw)
    new = _ORIG_REVIEW_ITEMS(views, projects, cfg, now, questions, ideas, world=_default_world(projects, cfg), **kw)
    if old != new:
        raise AssertionError(f"review_items default world differs: {old} != {new}")
    _CHECKED["review_items"] += 1
    return old


class _DefaultWorldChecked:
    def setUp(self):
        super().setUp()
        for name, fn in (("plan_tick", _plan_tick_checked), ("review_items", _review_items_checked)):
            p = mock.patch.object(sw, name, fn)
            p.start()
            self.addCleanup(p.stop)


import test_steward as _ts  # noqa: E402  (modül adıyla: sınıfları bu modülde İKİNCİ kez keşfedilmez)

for _n, _c in sorted(vars(_ts).items()):
    if isinstance(_c, type) and issubclass(_c, unittest.TestCase) and _c.__module__ == _ts.__name__:
        globals()[f"DefaultWorld_{_n}"] = type(f"DefaultWorld_{_n}", (_DefaultWorldChecked, _c), {})
del _n, _c


# ── sahiplik indeksi ───────────────────────────────────────────────────────────────────────────────────────────

class TestOwnershipIndex(_Tmp):
    def test_two_identities_owners_and_brains(self):
        sw.upsert_project("ncs")
        sw.upsert_project("ncs2", paths="kitap")
        idx = sw.ownership_index()
        self.assertEqual(idx["owners"], {"ncs": "default", "ncs2": "kitap"})
        self.assertEqual(idx["brains"], {"degnekci": "default", "degnekci_kitap": "kitap"})
        self.assertEqual((idx["conflicts"], idx["services"]), ({}, {}))
        self.assertEqual(sw.discover_steward_ids(), ["default", "kitap"])

    def test_settings_ids_reserve_brains_without_dirs(self):
        idx = sw.ownership_index(["default", "dergi", "Bad", "degnekcix"])
        self.assertEqual(idx["brains"], {"degnekci": "default", "degnekci_dergi": "dergi"})
        idx = sw.ownership_index(brains={"default": "benimbeyin"})
        self.assertEqual(idx["brains"], {"benimbeyin": "default"})

    def test_conflict_nobody_owns(self):
        sw.upsert_project("ncs")
        sw.upsert_project("mkt", paths="kitap")
        # elle düzenleme: aynı ad iki dosyada (talep protokolü bunu reddeder, yalnız el ile olur)
        for sid in ("default", "kitap"):
            path = sw.paths_for(sid).projects
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            raw["zlkrn"] = dataclasses.asdict(sw.Project(name="zlkrn", phase="planned", cadence_minutes=60))
            with open(path, "w", encoding="utf-8") as f:
                json.dump(raw, f)
        idx = sw.ownership_index()
        self.assertEqual(idx["conflicts"], {"zlkrn": ["default", "kitap"]})
        self.assertNotIn("zlkrn", idx["owners"])
        for sid in ("default", "kitap"):
            w = sw.world_for(sid, idx)
            self.assertFalse(w.owns("zlkrn"))
            self.assertEqual(w.session_class("zlkrn"), "conflict")
            self.assertEqual(w.session_class("zlkrn20261019"), "conflict")
            self.assertNotIn("zlkrn", w.own_projects(sw.load_projects(sid)))

    def test_cache_follows_file_changes(self):
        sw.upsert_project("ncs")
        self.assertEqual(sw.ownership_index()["owners"], {"ncs": "default"})
        sw.upsert_project("mkt")
        self.assertEqual(sw.ownership_index()["owners"], {"ncs": "default", "mkt": "default"})
        sw.remove_project("ncs")
        self.assertEqual(sw.ownership_index()["owners"], {"mkt": "default"})
        os.remove(sw.paths_for("default").projects)
        self.assertEqual(sw.ownership_index()["owners"], {})

    def test_services_are_read_and_reserved(self):
        os.makedirs(sw.STEWARD_DIR, exist_ok=True)
        with open(sw.services_path(), "w", encoding="utf-8") as f:
            json.dump({"varaka": {"match": "prefix"}, "embed": {"match": "exact"}, "Bad Name": {}}, f)
        idx = sw.ownership_index()
        self.assertEqual(sorted(idx["services"]), ["embed", "varaka"])
        self.assertEqual(sw.reserved_reason("varaka", idx), "service varaka")
        self.assertEqual(sw.reserved_reason("varaka2", idx), "service varaka")
        self.assertEqual(sw.reserved_reason("embedx", idx), "")         # exact kipte uzantısı serbest
        with self.assertRaises(sw.ReservedName):
            sw.upsert_project("varaka")
        w = sw.world_for("default", idx)
        self.assertEqual((w.session_class("varaka"), w.session_class("varaka20261019"), w.session_class("embed")),
                         ("service", "service", "service"))
        self.assertEqual(w.session_class("embedx"), "adhoc")

    def test_reading_writes_nothing(self):
        before = sorted(os.listdir(self.dir.name))
        sw.ownership_index()
        sw.ownership_index(["default", "kitap"], fresh=True)
        self.assertEqual(sorted(os.listdir(self.dir.name)), before)
        self.assertFalse(os.path.exists(sw.STEWARD_DIR))


class TestReservedNames(_Tmp):
    def test_reserved_reason(self):
        idx = sw.build_ownership_index({"default": [], "kitap": []})
        for name in ("degnekci", "deg", "d", "degnekci_x", "degnekcix", "degnekci_kitap", "degnekci_kitapx"):
            self.assertTrue(sw.reserved_reason(name, idx), name)
        for name in ("kitap", "ncs", "dergi", "egyptian"):
            self.assertEqual(sw.reserved_reason(name, idx), "", name)
        idx = sw.build_ownership_index({"default": []}, brains={"default": "benimbeyin"})
        self.assertTrue(sw.reserved_reason("benim", idx))
        self.assertTrue(sw.reserved_reason("degnekci", idx))   # aile her zaman rezerve

    def test_claim_rejects_new_reserved_name_but_keeps_existing(self):
        for name in ("deg", "degnekci", "degnekci_kitap"):
            with self.assertRaises(sw.ReservedName):
                sw.upsert_project(name)
        with self.assertRaises(ValueError):          # çağıranların `except ValueError` yolu korunur
            sw.upsert_project("de")
        self.assertEqual(sw.load_projects(), {})
        # eski (P3 öncesi) veride rezerve bir ad varsa güncellenebilir, silinmez
        sw.save_projects({"deg": sw.Project(name="deg")})
        self.assertEqual(sw.upsert_project("deg", notes="n").notes, "n")
        self.assertTrue(sw.remove_project("deg"))

    def test_owned_elsewhere_still_wins_for_other_identity(self):
        sw.upsert_project("ncs")
        with self.assertRaises(sw.OwnedElsewhere):
            sw.upsert_project("ncs", paths="kitap")


# ── global önek çözümü ─────────────────────────────────────────────────────────────────────────────────────────

def _two_worlds(default_projects=("ncs", "wifi5gppr", "egy"), kitap_projects=("ncs2", "kitap"), services=None):
    idx = sw.build_ownership_index({"default": list(default_projects), "kitap": list(kitap_projects)},
                                   services=services)
    return sw.world_for("default", idx), sw.world_for("kitap", idx), idx


class TestGlobalPrefix(unittest.TestCase):
    def test_ncs_vs_ncs2(self):
        a, b, _ = _two_worlds()
        cases = {"ncs": ("own", "other"), "ncs20261019": ("own", "other"), "ncs_1": ("own", "other"),
                 "ncs2": ("other", "own"), "ncs2x": ("other", "own"), "ncs220261019": ("other", "own"),
                 "ncs220261019_2": ("other", "own"), "wifi5gppr20261019": ("own", "other"),
                 "egyptian20260917": ("own", "other"),       # `egy` öneki: eski kural (en uzun önek) korunur
                 "kitap_1": ("other", "own"), "oa20261001": ("adhoc", "adhoc")}
        for name, (ca, cb) in cases.items():
            self.assertEqual((a.session_class(name), b.session_class(name)), (ca, cb), name)
        self.assertEqual(a.project_key("ncs20261019"), "ncs")
        self.assertEqual(b.project_key("ncs20261019"), "")
        self.assertEqual(b.project_key("ncs2x"), "ncs2")

    def test_same_owner_keeps_old_longest_prefix(self):
        projects = {n: sw.Project(name=n) for n in ("ncs", "ncs2")}
        w = _default_world(projects, sw.Config())
        for name in ("ncs20261019", "ncs2x", "ncs", "ncs_1", "zzz"):
            self.assertEqual(w.resolve(name)[1], sw._project_key(name, projects), name)

    def test_brains_are_never_projects(self):
        idx = sw.build_ownership_index({"default": ["deg", "kitap"], "kitap": ["ncs2"]})   # `deg`: eski veri
        a, b = sw.world_for("default", idx), sw.world_for("kitap", idx)
        self.assertEqual((a.session_class("degnekci_kitap"), b.session_class("degnekci_kitap")),
                         ("brain_other", "brain_own"))
        self.assertEqual((a.session_class("degnekci"), b.session_class("degnekci")), ("brain_own", "brain_other"))
        self.assertEqual(a.project_key("degnekci_kitap"), "")

    def test_blueprint_can_only_deny(self):
        a, b, _ = _two_worlds()
        # ad B'yi (`ncs2`), blueprint A'yı (`ncs`) gösteriyor: iki kimlik de dokunmaz
        self.assertEqual((a.session_class("ncs2x", "ncs"), b.session_class("ncs2x", "ncs")), ("other", "other"))
        # kayıtsız ad + kendi blueprint'i: sahibi yönetir
        self.assertEqual((a.session_class("deneme1", "ncs"), b.session_class("deneme1", "ncs")), ("own", "other"))
        self.assertEqual(a.session_class("x", "degnekci_kitap"), "brain_other")


# ── plan_tick / review_items kimlik süzgeçleri ─────────────────────────────────────────────────────────────────

def _multi_setup():
    """default: ncs, wifi5gppr, zlkrn, mkt, a; kitap: kitap, ncs2 (altın senaryonun projeleri bölünür)."""
    allp = _golden_projects()
    mine = {"default": {n: p for n, p in allp.items() if n not in ("kitap", "ncs2")},
            "kitap": {n: allp[n] for n in ("kitap", "ncs2")}}
    idx = sw.build_ownership_index({s: list(p) for s, p in mine.items()})
    return mine, idx


class TestNoCrossActions(unittest.TestCase):
    def _run(self, sid, step=0, questions=None, cfg_kw=None, state=None):
        mine, idx = _multi_setup()
        cfg = _cfg(**(cfg_kw or dict(max_active=4, tour_minutes=1)))
        if sid != "default":
            cfg.sid, cfg.brain_name = sid, sw.brain_name_for(sid)
        w = sw.world_for(sid, idx, cfg.brain_name)
        views = _golden_views(step)
        acts, st = sw.plan_tick(views, mine[sid], state or {}, cfg, T0 + step * 1200,
                                _golden_questions() if questions is None else questions, _golden_ideas(), world=w)
        return acts, st, w, {v.name: v.blueprint for v in views}

    def _assert_only_own(self, acts, w, bp):
        for a in acts:
            if a.kind in ("start", "set_phase"):
                self.assertTrue(w.owns(a.name), (w.sid, a.kind, a.name))
            elif a.kind == "escalate_routine":
                continue   # soru kimliğin kendi deposundan
            elif a.kind == "tour":
                self.assertEqual(w.brains.get(a.name), w.sid)
            else:
                cls = w.session_class(a.name, bp.get(a.name))
                ok = cls in ("own", "brain_own") or (cls == "adhoc" and w.is_adhoc_owner
                                                    and a.kind in ("ask_user", "idea", "deliver_answer"))
                self.assertTrue(ok, (w.sid, a.kind, a.name, cls))

    def test_each_identity_touches_only_its_own(self):
        for step in range(3):
            for sid in ("default", "kitap"):
                acts, _, w, bp = self._run(sid, step)
                self._assert_only_own(acts, w, bp)
        acts, _, _, _ = self._run("kitap", 1, questions=[])   # kitap'ın kendi deposu (default'un soruları değil)
        names = {a.name for a in acts}
        self.assertTrue({"kitap", "kitap_1"} & names)   # kitap kendi işini görüyor (STEWARD-DONE)
        self.assertFalse(names & {"ncs20261019", "wifi5gppr20261019", "zlkrn", "egyptian20260917", "a", "degnekci"})
        acts, _, _, _ = self._run("default", 1)
        self.assertFalse({a.name for a in acts} & {"kitap", "kitap_1", "ncs2x", "ncs2", "degnekci_kitap"})

    def test_kitap_brain_tours_and_economy_only_for_kitap(self):
        acts, _, _, _ = self._run("kitap", 0)
        self.assertEqual([a.name for a in acts if a.kind == "tour"], ["degnekci_kitap"])
        acts, _, _, _ = self._run("default", 0)
        self.assertEqual([a.name for a in acts if a.kind == "tour"], ["degnekci"])
        # ncs2x (kitap) bağlamı büyük → yalnız kitap devreder; ncs20261019 (default) yalnız default
        big = [_view("ncs2x", context_tokens=900000), _view("ncs20261019", context_tokens=900000)]
        mine, idx = _multi_setup()
        for sid, expect in (("default", ["ncs20261019"]), ("kitap", ["ncs2x"])):
            acts, _ = sw.plan_tick(big, mine[sid], {}, _cfg(), T0, [], [], world=sw.world_for(sid, idx))
            self.assertEqual([a.name for a in acts if a.kind == "handover"], expect, sid)

    def test_sibling_check_is_per_identity(self):
        # ncs (default) devrini bitirdi; ncs2x (kitap) çalışıyor: eski tek-kimlik önek kuralı bunu "kardeş" sayıp
        # kapatırdı, kimlikli çözümde ncs yeniden açılır.
        mine, idx = _multi_setup()
        a = _view("ncs20261019", last_assistant="READY FOR HANDOVER")
        b = _view("ncs2x", busy=True)
        st = {"ho_pending": {"ncs20261019": T0 - 60}}
        acts, _ = sw.plan_tick([a, b], mine["default"], st, _cfg(), T0, [], [], world=sw.world_for("default", idx))
        self.assertEqual([(x.kind, x.name) for x in acts if x.name == "ncs20261019"], [("respawn", "ncs20261019")])
        acts, st2 = sw.plan_tick([a, b], mine["kitap"], st, _cfg(), T0, [], [], world=sw.world_for("kitap", idx))
        self.assertEqual([x for x in acts if x.name == "ncs20261019"], [])
        self.assertNotIn("ncs20261019", st2["ho_pending"])   # başkasının oturumu: kitap'ın kaydından düşer

    def test_conflicted_project_gets_no_actions(self):
        mine, _ = _multi_setup()
        both = {"default": list(mine["default"]), "kitap": list(mine["kitap"]) + ["zlkrn"]}
        idx = sw.build_ownership_index(both)
        views = [_view("zlkrn", context_tokens=900000, last_assistant="STEWARD-ASK: soru?\nSTEWARD-DONE")]
        for sid in ("default", "kitap"):
            projects = dict(mine[sid])
            projects["zlkrn"] = sw.Project(name="zlkrn", phase="planned", cadence_minutes=1)
            acts, _ = sw.plan_tick(views, projects, {}, _cfg(), T0, [], [], world=sw.world_for(sid, idx))
            self.assertEqual([a for a in acts if a.name == "zlkrn"], [], sid)
            self.assertEqual(sw.review_items(views, projects, _cfg(), T0 + 9999, [], [], world=sw.world_for(sid, idx)), [])


class TestMarkers(unittest.TestCase):
    def test_adhoc_markers_only_default_and_project_markers_only_owner(self):
        mine, idx = _multi_setup()
        views = [_view("egyptian20260917", last_assistant="STEWARD-ASK: kayıtsız?"),
                 _view("kitap_1", blueprint="kitap", last_assistant="STEWARD-ASK: kitap?\nSTEWARD-IDEA: k-fikir"),
                 _view("ncs20261019", last_assistant="STEWARD-ASK: ncs?"),
                 _view("degnekci_kitap", last_assistant="STEWARD-ASK: beyin?"),
                 _view("degnekci", last_assistant="STEWARD-ASK: default beyin?")]
        got = {}
        for sid in ("default", "kitap"):
            cfg = _cfg(brain_name=sw.brain_name_for(sid))
            acts, _ = sw.plan_tick(views, mine[sid], {}, cfg, T0, [], [], world=sw.world_for(sid, idx, cfg.brain_name))
            got[sid] = sorted((a.kind, a.name, a.payload.get("text")) for a in acts if a.kind in ("ask_user", "idea"))
        self.assertEqual(got["default"], [("ask_user", "egyptian20260917", "kayıtsız?"),
                                          ("ask_user", "ncs20261019", "ncs?")])
        self.assertEqual(got["kitap"], [("ask_user", "kitap_1", "kitap?"), ("idea", "kitap_1", "k-fikir")])
        # world=None (eski davranış): beyin dışındaki her oturum taranır
        acts, _ = sw.plan_tick(views, mine["default"], {}, _cfg(), T0, [], [])
        self.assertIn("degnekci_kitap", {a.name for a in acts if a.kind == "ask_user"})

    def test_adhoc_answer_delivery_only_default(self):
        mine, idx = _multi_setup()
        q = sw.Question(id="q", project="egyptian20260917", text="?", created_at=T0 - 9, status="answered",
                        answer="A", answered_at=T0 - 5, source="egyptian20260917")
        views = [_view("egyptian20260917")]
        for sid, expect in (("default", ["egyptian20260917"]), ("kitap", [])):
            cfg = _cfg(brain_name=sw.brain_name_for(sid))
            acts, _ = sw.plan_tick(views, mine[sid], {}, cfg, T0, [q], [], world=sw.world_for(sid, idx, cfg.brain_name))
            self.assertEqual([a.name for a in acts if a.kind == "deliver_answer"], expect, sid)
        # kitap'ın sorusu, oturumu başka kimliğe geçmiş bir kaynağa da iletilmez
        q2 = dataclasses.replace(q, project="ncs20261019", source="ncs20261019")
        acts, _ = sw.plan_tick([_view("ncs20261019")], mine["kitap"], {}, _cfg(brain_name="degnekci_kitap"), T0, [q2],
                               [], world=sw.world_for("kitap", idx))
        self.assertEqual([a for a in acts if a.kind == "deliver_answer"], [])


class TestSlots(unittest.TestCase):
    def _setup(self):
        P = sw.Project
        mine = {"default": {"a": P(name="a", cadence_minutes=60), "b": P(name="b", cadence_minutes=60),
                            "c": P(name="c", cadence_minutes=60)},
                "kitap": {"x": P(name="x", cadence_minutes=60), "y": P(name="y", cadence_minutes=60),
                          "z": P(name="z", cadence_minutes=60)}}
        idx = sw.build_ownership_index({s: list(p) for s, p in mine.items()})
        views = [_view(n, busy=True) for n in ("a", "b", "x", "y", "z")]
        return mine, idx, views

    def test_max_active_total_counts_other_identities(self):
        mine, idx, views = self._setup()
        cfg = _cfg(max_active=4, max_active_total=5)
        w = sw.world_for("default", idx)
        acts, _ = sw.plan_tick(views, mine["default"], {}, cfg, T0, [], [], world=w)
        self.assertEqual([a for a in acts if a.kind == "start"], [])          # 2 + 3 = 5: makine dolu
        acts, _ = sw.plan_tick(views, mine["default"], {}, cfg, T0, [], [])   # eski yol: yalnız kendi max_active
        self.assertEqual([a.name for a in acts if a.kind == "start"], ["c"])
        cfg0 = _cfg(max_active=4, max_active_total=0)                         # 0 = sınırsız
        acts, _ = sw.plan_tick(views, mine["default"], {}, cfg0, T0, [], [], world=w)
        self.assertEqual([a.name for a in acts if a.kind == "start"], ["c"])
        cfg6 = _cfg(max_active=4, max_active_total=6)
        acts, _ = sw.plan_tick(views, mine["default"], {}, cfg6, T0, [], [], world=w)
        self.assertEqual([a.name for a in acts if a.kind == "start"], ["c"])

    def test_start_blocked_reason_is_visible(self):
        # canlı 2026-10-24: ae/hc/hcr süresi dolmuştu ama makine geneli sınır doluydu; neden hiçbir yerde görünmüyordu
        mine, idx, views = self._setup()
        w = sw.world_for("default", idx)
        _, st = sw.plan_tick(views, mine["default"], {}, _cfg(max_active=4, max_active_total=5), T0, [], [], world=w)
        self.assertEqual(st["start_blocked"]["reason"], "max_active_total")
        self.assertEqual((st["start_blocked"]["projects"], st["start_blocked"]["others_active"]), (["c"], 3))
        _, st = sw.plan_tick(views, mine["default"], {}, _cfg(max_active=2, max_active_total=0), T0, [], [], world=w)
        self.assertEqual(st["start_blocked"]["reason"], "max_active")
        _, st = sw.plan_tick(views, mine["default"], {}, _cfg(max_active=4, max_active_total=6), T0, [], [], world=w)
        self.assertNotIn("start_blocked", st)                                  # başlatıldı: engel yok

    def test_max_active_total_counts_only_busy_sessions(self):
        # Sahip kuralı (TODO 1233): makine geneli slotu yalnız mesaj alan/meşgul oturum yer; boşta açık oturum yemez
        mine, idx, _ = self._setup()
        w = sw.world_for("default", idx)
        cfg = _cfg(max_active=4, max_active_total=5)
        idle = [_view(n, busy=False) for n in ("a", "b", "x", "y", "z")]      # hepsi boşta (son etkinlik çok eski)
        acts, st = sw.plan_tick(idle, mine["default"], {}, cfg, T0, [], [], world=w)
        self.assertEqual([a.name for a in acts if a.kind == "start"], ["c"])
        self.assertNotIn("start_blocked", st)
        # yalnız kitap'ın oturumları meşgul (3) + benimkiler boşta: 0 + 3 < 5 → başlar
        mixed = [_view("a", busy=False), _view("b", busy=False)] + [_view(n, busy=True) for n in ("x", "y", "z")]
        acts, _ = sw.plan_tick(mixed, mine["default"], {}, cfg, T0, [], [], world=w)
        self.assertEqual([a.name for a in acts if a.kind == "start"], ["c"])
        # benimkiler de meşgul: 2 + 3 = 5 → dolu; olay güncel (meşgul) sayımı yazar
        acts, st = sw.plan_tick([_view(n, busy=True) for n in ("a", "b", "x", "y", "z")], mine["default"], {}, cfg,
                                T0, [], [], world=w)
        self.assertEqual([a for a in acts if a.kind == "start"], [])
        sb = st["start_blocked"]
        self.assertEqual((sb["reason"], sb["active_busy"], sb["others_active"], sb["max_active_total"]),
                         ("max_active_total", 2, 3, 5))

    def test_busy_signal_variants_for_total_slot(self):
        mine, idx, _ = self._setup()
        w = sw.world_for("default", idx)
        cfg = _cfg(max_active=4, max_active_total=3)
        base = [_view("a", busy=False), _view("b", busy=False)]
        cases = {
            "unknown": [_view(n, busy=None) for n in ("x", "y", "z")],                    # sinyal yok: boşta SAYILMAZ, slot yer
            "subagent": [_view(n, busy=False, subagent_active=True) for n in ("x", "y", "z")],
            "remote?": [_view(n, busy=False, subagent_unknown=True) for n in ("x", "y", "z")],
            "recent": [_view(n, busy=False, last_activity=T0 - 30) for n in ("x", "y", "z")],   # az önce mesaj aldı
        }
        for label, others in cases.items():
            acts, _ = sw.plan_tick(base + others, mine["default"], {}, cfg, T0, [], [], world=w)
            self.assertEqual([a for a in acts if a.kind == "start"], [], label)
        # aynı oturumlar uzun süredir boşta: slot açılır
        acts, _ = sw.plan_tick(base + [_view(n, busy=False, last_activity=T0 - 3600) for n in ("x", "y", "z")],
                               mine["default"], {}, cfg, T0, [], [], world=w)
        self.assertEqual([a.name for a in acts if a.kind == "start"], ["c"])

    def test_local_max_active_still_counts_open_sessions(self):
        # yerel `max_active` (ve ona bağlı stop_idle slot baskısı) değişmedi: boşta açık oturum yine sayılır
        mine, idx, _ = self._setup()
        w = sw.world_for("default", idx)
        idle = [_view(n, busy=False) for n in ("a", "b", "x", "y", "z")]
        acts, st = sw.plan_tick(idle, mine["default"], {}, _cfg(max_active=2, max_active_total=5, stop_idle_minutes=5),
                                T0, [], [], world=w)
        self.assertEqual([a for a in acts if a.kind == "start"], [])
        self.assertEqual(st["start_blocked"]["reason"], "max_active")
        self.assertEqual(sorted(a.name for a in acts if a.kind == "stop"), ["a", "b"])

    def test_starts_left_budget(self):
        mine, idx, views = self._setup()
        cfg = _cfg(max_active=4, max_active_total=0, max_starts_per_tick=2)
        for left, expect in ((0, []), (1, ["c"]), (None, ["c"])):
            w = sw.world_for("default", idx, starts_left=left)
            acts, _ = sw.plan_tick(views, mine["default"], {}, cfg, T0, [], [], world=w)
            self.assertEqual([a.name for a in acts if a.kind == "start"], expect, left)


class TestReviewItems(unittest.TestCase):
    def test_only_own_sessions(self):
        mine, idx = _multi_setup()
        views = [_view("ncs", busy=False), _view("kitap_1", blueprint="kitap", busy=False),
                 _view("ncs2", busy=False), _view("egyptian20260917", busy=False)]
        cfg = _cfg()
        now = T0 + 99999
        got = {sid: sorted(i["name"] for i in sw.review_items(views, mine[sid], cfg, now, [], [],
                                                              world=sw.world_for(sid, idx)))
               for sid in ("default", "kitap")}
        self.assertEqual(got, {"default": ["ncs"], "kitap": ["kitap_1", "ncs2"]})
        # world=None: eski davranış (verilen proje sözlüğü neyse)
        allp = dict(mine["default"], **mine["kitap"])
        self.assertEqual(sorted(i["name"] for i in sw.review_items(views, allp, cfg, now, [], [])),
                         ["kitap_1", "ncs", "ncs2"])
