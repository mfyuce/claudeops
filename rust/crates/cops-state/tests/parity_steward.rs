//! `settings.steward_ids` / `steward_config` (K2) ve `default_model_for` / `default_effort_for` / `resolved_model_for`
//! (K3) paritesi: aynı `settings.json`, aynı girdi, aynı çıktı (`dataclasses.asdict` JSON baytı).
use cops_state::json::Map;
use cops_state::settings::{Settings, SettingsReader};
use cops_state::steward_settings::{self as ss, StewardConfigError};
use cops_state::Json;

mod common;
use common::Env;

/// `settings.json` durumları. Ham metin: `NaN`/`Infinity`/büyük sayı korunur.
const CASES: &[&str] = &[
    r#"{}"#,
    r#"{"steward": {"enabled": "on", "mode": "act", "max_active": "3"}, "stewards": {"kitap": {"enabled": "on", "max_active": "9", "mode": "act"}}}"#,
    r#"{"steward": {"handover_force_ratio": "1.5", "handover_defer_max_minutes": "10", "auto_context_ratio": "0.6"}}"#,
    r#"{"steward": {"handover_force_ratio": "x", "brain_name": "benimbeyin"}}"#,
    r#"{"stewards": {"zeta": {}, "kitap": {"enabled": "on"}, "Bad": {}, "degnekci": {}, "degnekcix": {}, "all": {}, "default": {}, "x": {}, "str": "bozuk", "abcdefghijklmnopq": {}, "ki_tap": {}, "ab": {}}}"#,
    r#"{"steward": {"enabled": "on", "mode": "act", "max_active": "4", "tick_seconds": "90", "cards_per_tick": "2", "max_active_total": "8", "max_starts_total": "2", "brain_effort": "low", "lang": "en", "brain_name": "zzz"},
        "stewards": {"kitap": {"label": "Kitaplar", "enabled": "on", "mode": "observe", "max_active": "2", "brain_model": "m", "summary_hour": "9", "persona_text": "p", "ntfy_topic": "t", "tick_seconds": "999", "max_active_total": "77", "brain_name": "hile", "sid": "baska", "history_warn_at": 5}}}"#,
    r#"{"stewards": {"kitap": {"max_active": "abc", "mode": "bogus", "summary_hour": "40", "lang": "xx"}}}"#,
    r#"{"stewards": "bozuk", "steward": "bozuk"}"#,
    r#"{"stewards": {"reviewer": {"role": "reviewer", "review_agy_models": "a,b", "review_timeout_minutes": "30"}, "bozuk": {"role": "xx"}}, "steward": {"role": "reviewer"}}"#,
    r#"{"steward": {"role": "generic"}, "stewards": {"gen": {"role": "generic"}, "kitap": {}}}"#,
    r#"{"stewards": {"gen": {"role": "generic", "planned_model": "claude-opus-5-5", "planned_effort": "high", "planning_effort": "  "}}}"#,
    r#"{"steward": {"enabled": "on", "tick_seconds": "5", "max_active": "abc", "lang": "xx", "brain_name": "bad name"}, "history_warn_at": 1500}"#,
    r#"{"steward": {"mode": "act", "summary_hour": "99", "ask_gate": "SHADOW"}, "history_warn_at": 5}"#,
    r#"{"steward": {"mode": "yolo", "card_refresh": "off", "cards_per_tick": "3", "ask_gate": " On ", "ask_gate_threshold": "0.9", "ask_gate_owner_projects": " a,b "}}"#,
    r#"{"steward": {"ask_gate": "bogus", "enabled": "", "mode": " act "}, "history_warn_at": " 1_600 "}"#,
    r#"{"stewards": {"kitap": {"enabled": "on", "brain_cli": "ucli", "brain_model": "claude-opus-5-5", "brain_service": "Claude", "brain_max_cost_usd": "0"}}}"#,
    r#"{"steward": {"enabled": true, "drain": " EVET ", "auto_start": 1, "card_refresh": "True", "remote_actions": 1.0, "done_handover": null, "brain_mcp_check": []}}"#,
    r#"{"steward": {"max_active": -3, "idle_minutes": 5.0, "review_minutes": true, "stop_idle_minutes": " ٤٥ ", "ho_grace_minutes": "+0_7", "tour_minutes": 99999999999999999999999, "tour_retry_minutes": "-99999999999999999999999", "review_timeout_minutes": 0, "review_window_hours": 99999999999999999999999, "tick_seconds": 99999999999999999999999, "summary_hour": 99999999999999999999999}}"#,
    r#"{"steward": {"handover_force_ratio": -1, "auto_context_ratio": "nan", "ask_gate_threshold": "inf", "brain_max_cost_usd": "-0.0", "done_handover_min_ratio": 1e400, "no_work_open_q_hours": " 1_0.5 ", "review_anthropic_budget_usd": [1]}}"#,
    r#"{"steward": {"brain_name": "___"}}"#,
    r#"{"steward": {"brain_name": "a_b_9"}}"#,
    r#"{"steward": {"brain_name": "ş١²Ⅻ"}}"#,
    r#"{"steward": {"brain_name": "á"}}"#,
    r#"{"steward": {"brain_name": "a-b"}}"#,
    r#"{"steward": {"brain_name": "  "}}"#,
    r#"{"steward": {"brain_name": null, "label": null, "brain_model": 5, "persona_text": [1, "a'"], "ntfy_topic": {"k": true}}}"#,
    r#"{"steward": {"review_window_hours": 0, "lang": "EN", "role": " generic ", "mode": "ACT"}}"#,
    r#"{"history_warn_at": 0}"#,
    r#"{"history_warn_at": ""}"#,
    r#"{"history_warn_at": null}"#,
    r#"{"history_warn_at": true}"#,
    r#"{"history_warn_at": 2500.9}"#,
    r#"{"history_warn_at": "12.5"}"#,
    r#"{"history_warn_at": "abc"}"#,
    r#"{"history_warn_at": [1]}"#,
    r#"{"history_warn_at": {"a": 1}}"#,
    r#"{"history_warn_at": -7}"#,
    r#"{"history_warn_at": 1e300}"#,
    r#"{"history_warn_at": -1e300}"#,
    r#"{"history_warn_at": NaN}"#,
    r#"{"history_warn_at": 99999999999999999999999}"#,
    r#"{"history_warn_at": Infinity}"#,
    r#"{"history_warn_at": 1e400}"#,
    r#"{"history_warn_at": -Infinity}"#,
];

const SIDS: &[&str] = &[
    "default",
    "kitap",
    "gen",
    "reviewer",
    "bozuk",
    "zeta",
    "yeni",
    "ab",
    "abcdefghijklmnop",
    "Kitap",
    "all",
    "degnekci",
    "degnekcix",
    "",
    "a",
    "abcdefghijklmnopq",
    "kitap2",
    "ki_tap",
    "ki-tap",
    "services",
    "service",
    "steward",
    "stewards",
];

const PY: &str = r#"
import dataclasses
from claudeops import settings as s
data = json.load(sys.stdin)
def call(f):
    try:
        return f()
    except Exception as e:
        return {'error': type(e).__name__}
for case in data['cases']:
    with open(s.SETTINGS_JSON, 'w', encoding='utf-8') as f:
        f.write(case)
    s._LOAD_CACHE['sig'] = None
    print(json.dumps(call(s.steward_ids), ensure_ascii=False))
    for sid in data['sids']:
        print(json.dumps(call(lambda: dataclasses.asdict(s.steward_config(sid))), ensure_ascii=False))
"#;

fn strs(v: &[&str]) -> Json {
    Json::Array(v.iter().map(|x| Json::from(*x)).collect())
}

fn error(name: &str) -> String {
    format!(r#"{{"error": "{name}"}}"#)
}

#[test]
fn steward_config_matches_python() {
    let e = Env::new();
    let input = Json::Object(
        [
            ("cases".to_string(), strs(CASES)),
            ("sids".to_string(), strs(SIDS)),
        ]
        .into_iter()
        .collect(),
    );
    let out = e.py_in("files", PY, &input.to_compact());
    let mut lines = out.split_terminator('\n');
    for case in CASES {
        let s = Settings::from_text(Some(case));
        assert_eq!(
            Json::Array(s.steward_ids().into_iter().map(Json::from).collect()).to_compact(),
            lines.next().unwrap(),
            "steward_ids: {case}"
        );
        for sid in SIDS {
            let got = match s.steward_config(sid) {
                Ok(c) => c.to_json().to_compact(),
                Err(StewardConfigError::InvalidSid(_)) => error("ValueError"),
            };
            assert_eq!(got, lines.next().unwrap(), "sid {sid:?}: {case}");
        }
    }
    assert_eq!(lines.next(), None);
}

/// Python testlerinin iddiaları Rust tarafında açık değerlerle (parite iki tarafın birlikte kaymasını yakalamaz).
#[test]
fn steward_config_values() {
    let cfg = |text: &str, sid: &str| Settings::from_text(Some(text)).steward_config(sid).unwrap();
    let d = cfg("{}", "default");
    assert!(!d.bool_of("enabled"));
    assert_eq!(
        (
            d.int_of("max_active_total"),
            d.int_of("max_starts_total"),
            d.int_of("history_warn_at")
        ),
        (6, 1, 1900)
    );
    assert_eq!(
        (
            d.str_of("sid"),
            d.str_of("mode"),
            d.str_of("role"),
            d.str_of("brain_name")
        ),
        ("default", "observe", "steward", "degnekci")
    );
    assert_eq!(
        (
            d.str_of("ask_gate"),
            d.float_of("ask_gate_threshold"),
            d.str_of("ask_gate_owner_projects")
        ),
        ("off", 0.7, "")
    );
    assert_eq!(
        (
            d.str_of("brain_cli"),
            d.str_of("brain_service"),
            d.float_of("brain_max_cost_usd")
        ),
        ("claude", "claude", 1.0)
    );
    let c = cfg(CASES[11], "default");
    assert!(c.bool_of("enabled"));
    assert_eq!(
        (
            c.int_of("tick_seconds"),
            c.int_of("max_active"),
            c.str_of("lang"),
            c.str_of("brain_name"),
            c.int_of("history_warn_at")
        ),
        (15, 4, "tr", "degnekci", 1500)
    );
    let g = cfg(CASES[9], "gen");
    assert_eq!(
        (
            g.str_of("role"),
            g.str_of("planning_model"),
            g.str_of("planning_effort"),
            g.str_of("planned_model"),
            g.str_of("planned_effort")
        ),
        (
            "generic",
            ss::GENERIC_MODEL,
            "medium",
            ss::GENERIC_MODEL,
            "medium"
        )
    );
    // kimlik bloğuna açıkça yazılan model/effort geçer, boş kalanlar generic varsayılanı alır
    let own = cfg(CASES[10], "gen");
    assert_eq!(
        (
            own.str_of("planned_model"),
            own.str_of("planned_effort"),
            own.str_of("planning_model"),
            own.str_of("planning_effort"),
        ),
        ("claude-opus-5-5", "high", ss::GENERIC_MODEL, "medium")
    );
    assert_eq!(
        cfg(CASES[9], "default").str_of("role"),
        "steward",
        "default asla generic değil"
    );
    assert_eq!(
        cfg(CASES[8], "default").str_of("role"),
        "steward",
        "default asla reviewer değil"
    );
    let r = cfg(CASES[8], "reviewer");
    assert_eq!(
        (
            r.str_of("role"),
            r.str_of("review_agy_models"),
            r.int_of("review_timeout_minutes")
        ),
        ("reviewer", "a,b", 30)
    );
    let k = cfg(CASES[5], "kitap");
    assert_eq!(
        (
            k.str_of("brain_effort"),
            k.int_of("tick_seconds"),
            k.int_of("max_active_total"),
            k.str_of("brain_name")
        ),
        ("high", 90, 8, "degnekci_kitap")
    );
    assert_eq!(
        Settings::from_text(Some(CASES[4])).steward_ids(),
        ["default", "ab", "kitap", "zeta"]
    );
    assert_eq!(
        Settings::from_text(None).steward_config("Kitap"),
        Err(StewardConfigError::InvalidSid("Kitap".into()))
    );
    // dosyadan okuyan yol aynı sonucu verir
    let e = Env::new();
    std::fs::write(e.dir().settings_json(), CASES[5]).unwrap();
    assert_eq!(
        SettingsReader::new(e.dir())
            .load()
            .steward_config("kitap")
            .unwrap(),
        k
    );
    // Debug sır (ntfy konusu) göstermez
    let dbg = format!(
        "{:?}",
        cfg(r#"{"steward": {"ntfy_topic": "gizli-konu"}}"#, "default")
    );
    assert!(!dbg.contains("gizli-konu"), "{dbg}");
}

#[test]
fn steward_constants_match_python() {
    let e = Env::new();
    let out = e.py(
        "files",
        "import dataclasses\nfrom claudeops import steward as sw\n\
         print(json.dumps(dataclasses.asdict(sw.Config()), ensure_ascii=False))\n\
         print(json.dumps([list(sw.MODES), list(sw.ROLES), list(sw.MACHINE_KEYS), sorted(sw.RESERVED_IDS), sw.BRAIN_PREFIX, sw.GENERIC_MODEL, sw.GENERIC_EFFORT, \
         [sw.brain_name_for(x) for x in ('default', 'kitap')]]))",
    );
    let mut lines = out.lines();
    assert_eq!(
        Json::Object(ss::defaults().clone()).to_compact(),
        lines.next().unwrap(),
        "default_steward_config.json ayrıştı"
    );
    let mut reserved = ss::RESERVED_IDS.to_vec();
    reserved.sort_unstable();
    let rs = Json::Array(vec![
        strs(&ss::MODES),
        strs(&ss::ROLES),
        strs(&ss::MACHINE_KEYS),
        strs(&reserved),
        ss::BRAIN_PREFIX.into(),
        ss::GENERIC_MODEL.into(),
        ss::GENERIC_EFFORT.into(),
        Json::Array(
            ["default", "kitap"]
                .iter()
                .map(|s| ss::brain_name_for(s).into())
                .collect(),
        ),
    ]);
    assert_eq!(rs.to_compact(), lines.next().unwrap());
}

/// TBD#379 S11: sondaki satır sonu iki dilde de reddedilir (`"default\n"` rezerve denetimini aşamaz).
#[test]
fn steward_id_trailing_newline_rejected_in_both() {
    let e = Env::new();
    let text = r#"{"stewards": {"kitap\n": {}, "default\n": {}}}"#;
    std::fs::write(e.dir().settings_json(), text).unwrap();
    let py = e.py(
        "files",
        "from claudeops import settings as s\ntry:\n    s.steward_config('kitap\\n'); r = 'kabul'\nexcept ValueError:\n    r = 'red'\nprint(json.dumps([s.steward_ids(), r]))",
    );
    assert_eq!(py.trim_end(), r#"[["default"], "red"]"#);
    let s = Settings::from_text(Some(text));
    assert_eq!(s.steward_ids(), ["default"]);
    assert!(matches!(
        s.steward_config("kitap\n"),
        Err(StewardConfigError::InvalidSid(_))
    ));
    assert!(!ss::valid_custom_id("default\n") && !ss::valid_steward_id("kitap\n"));
}

/// TBD#379 S12: sonsuz `history_warn_at` varsayılana düşer.
#[test]
fn infinite_history_warn_at_keeps_default() {
    for raw in ["Infinity", "-Infinity", "1e400"] {
        let s = Settings::from_text(Some(&format!(r#"{{"history_warn_at": {raw}}}"#)));
        let c = s.steward_config("default").unwrap();
        assert_eq!(c.int_of("history_warn_at"), 1900, "{raw}");
    }
}

// ---- K3 --------------------------------------------------------------------------------------------------------------

const MODEL_SETTINGS: &[&str] = &[
    r#"{}"#,
    r#"{"default_model": {"c": "m2"}, "default_effort": {"c": "high"}}"#,
    r#"{"default_model": {"c": "yok"}, "default_effort": {"c": "bogus"}}"#,
    r#"{"default_model": {"c": ""}, "default_effort": {"c": ""}}"#,
    r#"{"default_model": {"c": 5}, "default_effort": {"c": ["high"]}}"#,
    r#"{"default_model": {"c": 0}, "default_effort": {"c": null}}"#,
    r#"{"default_model": "x", "default_effort": 7}"#,
    r#"{"default_model": {"d": "m2"}, "default_effort": {"d": "high"}}"#,
];

/// (model_choices, preferred, effort_levels, default_effort, stored)
type Provider = (
    &'static [&'static str],
    Option<&'static str>,
    &'static [&'static str],
    &'static str,
    &'static str,
);

const PROVIDERS: &[Provider] = &[
    (
        &["m1", "m2", "s5"],
        Some("s5"),
        &["low", "medium", "high"],
        "medium",
        "",
    ),
    (&["m1", "m2"], Some("yok"), &["low", "high"], "high", "eski"),
    (&["m1", "m2"], None, &[], "", "m1"),
    (&[], Some("s5"), &["medium"], "medium", ""),
    (&[], None, &["", "high"], "", ""),
    (&["", "m2"], Some("m2"), &["high"], "x", ""),
];

#[test]
fn default_model_and_effort_match_python() {
    let e = Env::new();
    let provs = Json::Array(
        PROVIDERS
            .iter()
            .map(|(m, p, l, d, st)| {
                Json::Array(vec![
                    strs(m),
                    p.map_or(Json::Null, Json::from),
                    strs(l),
                    (*d).into(),
                    (*st).into(),
                ])
            })
            .collect(),
    );
    let input: Map = [
        ("settings".to_string(), strs(MODEL_SETTINGS)),
        ("providers".to_string(), provs),
    ]
    .into_iter()
    .collect();
    let out = e.py_in(
        "files",
        r#"
from claudeops import settings as s
data = json.load(sys.stdin)
class P:
    name = 'c'
    def __init__(self, a): self.m, self.p, self.l, self.d, self.stored = a
    def model_choices(self): return list(self.m)
    def preferred_default_model(self): return self.p
    def effort_levels(self): return list(self.l)
    def default_effort(self): return self.d
    def refresh_stored_model(self, x): return 'taze:' + x
for text in data['settings']:
    with open(s.SETTINGS_JSON, 'w', encoding='utf-8') as f:
        f.write(text)
    s._LOAD_CACHE['sig'] = None
    for a in data['providers']:
        p = P(a)
        print(json.dumps([s.default_model_for(p), s.default_effort_for(p), s.resolved_model_for(p, p.stored)]))
"#,
        &Json::Object(input).to_compact(),
    );
    let mut lines = out.split_terminator('\n');
    let owned = |v: &[&str]| -> Vec<String> { v.iter().map(|x| x.to_string()).collect() };
    for text in MODEL_SETTINGS {
        let s = Settings::from_text(Some(text));
        for (m, p, l, d, stored) in PROVIDERS {
            let (m, l) = (owned(m), owned(l));
            let got = Json::Array(vec![
                s.default_model_for("c", &m, *p).into(),
                s.default_effort_for("c", &l, d).into(),
                s.resolved_model_for("c", stored, &m, *p, |x| format!("taze:{x}"))
                    .into(),
            ]);
            assert_eq!(got.to_compact(), lines.next().unwrap(), "{text} {m:?}");
        }
    }
    assert_eq!(lines.next(), None);
    // açık değerler
    let s = Settings::from_text(Some(MODEL_SETTINGS[1]));
    let m = owned(&["m1", "m2"]);
    let l = owned(&["medium", "high"]);
    assert_eq!(
        s.default_model_for("c", &m, Some("m1")),
        "m2",
        "geçerli ayar tercihi ezer"
    );
    assert_eq!(s.default_effort_for("c", &l, "medium"), "high");
    let bad = Settings::from_text(Some(MODEL_SETTINGS[2]));
    assert_eq!(
        bad.default_model_for("c", &m, Some("m2")),
        "m2",
        "geçersiz ayar: tercih"
    );
    assert_eq!(
        bad.default_model_for("c", &m, None),
        "m1",
        "tercih yok: ilk seçenek"
    );
    assert_eq!(
        bad.default_model_for("c", &[], Some("m2")),
        "",
        "seçenek yok: boş"
    );
    assert_eq!(
        bad.default_effort_for("c", &l, "medium"),
        "medium",
        "geçersiz ayar: sağlayıcı varsayılanı"
    );
}
