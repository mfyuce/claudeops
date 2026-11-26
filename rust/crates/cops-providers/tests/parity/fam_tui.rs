//! Aile (G4): sağlayıcı TUI davranışı (devir kancaları, girdi hazırlama, mod kalıpları) ve canlı model/effort geçişi
//! ile başıboş diyalog: sahte ekran dizisi + sahte saat; dönüş, gönderilen metin/tuş sırası, yakalama ve uyku sırası,
//! bitiş anı ve diag (iki tarafta da boş) karşılaştırılır. Senaryolar `py/tests/test_{proc08_model_switch_no_blind_enter,
//! live_model_effort,provider_wants_split,ucli_multiline_flatten}.py` + sınır ve rastgele ekranlar.

use crate::common::*;
use crate::fake_pane::{FakePane, Script};
use crate::fam_bg::Rng;
use cops_providers::{strip_ansi, Cli};
use regex::Regex;
use serde_json::{json, Value};

const CLIS: [&str; 7] = ["claude", "agy", "codex", "copilot", "shell", "ucli", "yok"];

const ANSI_SWITCH: &str = "\x1b[1m\x1b[38;5;220mSwitch\x1b[0m\x1b[39m\x1b[49m \x1b[1m\x1b[38;5;220mmodel?\x1b[0m";
const ANSI_EFFORT: &str = "\x1b[1mChange\x1b[0m \x1b[2meffort\x1b[0m \x1b[38;5;1mlevel?\x1b[0m";

/// Rastgele ekran/metin parçaları: işaretler, yarım işaretler, ANSI kırıntıları, satır sonları, Unicode boşlukları.
const FRAGMENTS: &[&str] = &[
    "Switch model?", "Switch ", "model?", "Set model to", "Kept model as", "Change effort level?",
    "Set effort level to", "Not applied:", "exceeds the cap", "Failed to set effort level", "Do you want to proceed?",
    "switch model?", " ", " ", "\n", "\r", "\t", "x", "ğ", "İ", "1. Yes", "\x1b", "[", "]", "0", ";", "m", "K", "?", "\x07",
    "\\", "\x1b[0m", "\x1b[38;5;220m", "\x1b[?25l", "\x1b]0;baslik\x07", "\x1b]8;;http://x\x1b\\", "\x1b]", "\u{b}",
    "\u{c}", "\u{1c}", "\u{1f}", "\u{85}", "\u{a0}", "\u{2028}", "\u{3000}", "\u{200b}", "\u{0}",
];

fn rs_static(_e: &Env, c: &Case) -> RsOut {
    let cli = Cli::parse(c.args["cli"].as_str().unwrap());
    let texts = strs(c.args.get("texts"));
    let models = strs(c.args.get("models"));
    let efforts = c.args["efforts"].as_array().unwrap();
    RsOut::ret(json!({
        "has_conversation": cli.has_conversation(),
        "wants_handover_wrapup": cli.wants_handover_wrapup(),
        "wants_stuck_recovery": cli.wants_stuck_recovery(),
        "input_settle_delay": cli.input_settle_delay().to_bits() as i64,
        "compact_command": cli.compact_command(),
        "mode_status_patterns": cli.mode_status_patterns().iter().map(|(k, v)| json!([k, v])).collect::<Vec<_>>(),
        "cyclable_modes": cli.cyclable_modes(),
        "prepare_input": texts.iter().map(|t| cli.prepare_input(t).into_owned()).collect::<Vec<_>>(),
        "model_downgrade": models.iter().map(|m| cli.handover_model_downgrade(m)).collect::<Vec<_>>(),
        "effort_downgrade": efforts
            .iter()
            .map(|p| cli.handover_effort_downgrade(p[0].as_str().unwrap(), p[1].as_str().unwrap()))
            .collect::<Vec<_>>(),
    }))
}

fn rs_strip(_e: &Env, c: &Case) -> RsOut {
    RsOut::ret(json!(strs(c.args.get("texts")).iter().map(|t| strip_ansi(t)).collect::<Vec<_>>()))
}

fn rs_modes(_e: &Env, c: &Case) -> RsOut {
    let cli = Cli::parse(c.args["cli"].as_str().unwrap());
    let pats: Vec<(&str, Regex)> = cli
        .mode_status_patterns()
        .iter()
        .map(|(m, p)| (*m, Regex::new(&format!("(?i){p}")).unwrap()))
        .collect();
    let found: Vec<Option<&str>> =
        strs(c.args.get("texts")).iter().map(|t| pats.iter().find(|(_, r)| r.is_match(t)).map(|(m, _)| *m)).collect();
    RsOut::ret(json!(found))
}

fn script_of(a: &Value) -> Script {
    let d = Script::default();
    Script {
        screens: a["screens"].as_array().unwrap().iter().map(|s| s.as_str().map(String::from)).collect(),
        send_ok: a.get("send_ok").and_then(Value::as_bool).unwrap_or(true),
        keys: a.get("keys").and_then(Value::as_array).map(|k| k.iter().map(|b| b.as_bool().unwrap()).collect()).unwrap_or_default(),
        t0: a["t0"].as_f64().unwrap(),
        send_cost: a.get("send_cost").and_then(Value::as_f64).unwrap_or(d.send_cost),
        capture_cost: a.get("capture_cost").and_then(Value::as_f64).unwrap_or(d.capture_cost),
    }
}

fn rs_pane(_e: &Env, c: &Case) -> RsOut {
    let a = &c.args;
    let cli = Cli::parse(a["cli"].as_str().unwrap());
    let name = a["name"].as_str().unwrap();
    let target = a["target"].as_str().unwrap();
    let pane = FakePane::new(script_of(a));
    match a["which"].as_str().unwrap() {
        "model" => {
            let _ = cli.apply_live_model_switch(&pane, name, target);
        }
        "effort" => {
            let _ = cli.apply_live_effort_switch(&pane, name, target);
        }
        _ => cli.dismiss_stray_dialog(&pane, name),
    }
    let end = pane.now.get().to_bits() as i64;
    let log = pane.log.take();
    RsOut::ret(json!({"log": log, "end": end}))
}

fn static_cases() -> Vec<Case> {
    let mut texts: Vec<String> = [
        "", "a", "  tek satır  ", "a\nb\n\n  c  \r\nd\re", "x\n", "\n", "\n\n", "\t", " \r ", "a\tb\t\tc  d", "a  b",
        "a\u{b}b", "a\u{c}b", "a\u{2028}b", "a\u{85}b", "a\u{b}b\n", "a\u{1c}b\u{1d}c\u{1e}d\u{1f}e\n",
        "a\u{a0}b\u{3000}c\u{2003}d\n", "a\u{200b}b\u{feff}c\n", "ğ İ ı\n ş", "- madde\n- diğer;\n", "a\u{0}\n\u{1b}[0m b",
    ]
    .into_iter()
    .map(String::from)
    .collect();
    texts.push(format!("bir\n{}\nson", "uzun ".repeat(400)));
    let mut r = Rng(41);
    texts.extend((0..600).map(|_| r.soup(FRAGMENTS, 12)));
    let models = [
        "", "opus", "OPUS", "claude-opus-5-5", "claude-fable-5-2[1m]", "Fable", "claude-sonnet-5-5", "sonnet",
        "claude-haiku-5-5", "gpt-5.4", "o pus", "opu\u{17f}", "FABLE", "fabLe", "İopus", "\u{212a}opus", "default",
        "claude-sonnet-opus", "FABLİ",
    ];
    let levels = ["low", "medium", "high", "xhigh", "max", "", "ultra", "HIGH", " high", "none"];
    let efforts: Vec<[&str; 2]> = levels.iter().flat_map(|c| levels.iter().map(move |t| [*c, *t])).collect();
    CLIS.iter()
        .map(|cli| {
            Case::new(
                format!("g4-sabit-{cli}"),
                "g4_static",
                json!({"cli": cli, "texts": texts, "models": models, "efforts": efforts}),
            )
        })
        .collect()
}

fn text_cases() -> Vec<Case> {
    let mut r = Rng(42);
    let mut strip: Vec<String> = [
        "", ANSI_SWITCH, ANSI_EFFORT, "\x1b[m", "\x1b[1;2;3;4mx", "\x1b[?25lx", "\x1b[1 qx", "\x1b[12~x", "\x1b(Bx",
        "\x1b]0;a\x07b", "\x1b]0;a\nb\x07c", "\x1b]8;;u\x1b\\link\x1b]8;;\x1b\\", "\x1b]yarım", "\x1b[", "\x1b[3",
        "\x1b]a\x1b[0mb\x07c", "\x1b[\x1b[0m0mx", "\x1b[٣mx", "\x1b[0İ", "a\x1b[0Kb\r\n",
    ]
    .into_iter()
    .map(String::from)
    .collect();
    strip.extend((0..3000).map(|_| r.soup(FRAGMENTS, 16)));
    let mut cases = vec![Case::new("g4-strip", "g4_strip", json!({"texts": strip}))];

    const MODE: &[&str] = &[
        "plan", "PLAN", "Plan", " ", "  ", "mode", "on", " mode on", "accept edits on", "Accept Edits On", "auto mode on",
        "manual mode on", "autopilot", "AutoPilot", "·", "•", ".", "\n", "\t", "\u{a0}", "\u{3000}", "x", "ğ",
        "(shift+tab to cycle)", "⏵⏵ ",
    ];
    let mut modes: Vec<String> = [
        "", "plan mode on", "⏸ PLAN MODE ON (shift+tab to cycle)", "⏵⏵ accept edits on", "⏵⏵ auto mode on",
        "manual mode on", "manual mode on · plan mode on", "plan mode off", "plan\nmode on", "· plan ·", "·plan·",
        "· PLAN ·", "·\n plan \t·", "· autopilot ·", "· autopilot · plan ·", "a plan to follow", "· planning ·",
    ]
    .into_iter()
    .map(String::from)
    .collect();
    modes.extend((0..2000).map(|_| r.soup(MODE, 10)));
    for cli in CLIS {
        cases.push(Case::new(format!("g4-mod-{cli}"), "g4_modes", json!({"cli": cli, "texts": modes})));
    }
    // Desen METİNLERİ aynıdır; ayrışma onları derleyen motorda (tüketici T2/T4; `docs/rs-prov.md` G4).
    cases.push(
        Case::new("g4-mod-sapma-noktali-i", "g4_modes", json!({"cli": "claude", "texts": ["ACCEPT EDİTS ON", "accept edıts on"]}))
            .known("Python IGNORECASE `i`yi `İ`/`ı` ile de eşler; Rust `(?i)` eşlemez"),
    );
    cases.push(
        Case::new("g4-mod-sapma-bosluk", "g4_modes", json!({"cli": "copilot", "texts": ["·\u{1c}plan\u{1f}·"]}))
            .known("Python `\\s` U+001C..U+001F'i boşluk sayar; Rust `\\s` saymaz"),
    );
    cases
}

struct Pane {
    which: &'static str,
    cli: &'static str,
    screens: Vec<Option<String>>,
    extra: Value,
}

fn pane_case(id: String, p: Pane) -> Case {
    let target = if p.which == "effort" { "high" } else { "sonnet" };
    let mut args = json!({"which": p.which, "cli": p.cli, "name": "oturum_1", "target": target, "screens": p.screens, "t0": 1000.0});
    if let (Value::Object(a), Value::Object(b)) = (&mut args, p.extra) {
        a.extend(b);
    }
    Case::new(id, "g4_pane", args)
}

fn some(v: &[&str]) -> Vec<Option<String>> {
    v.iter().map(|s| Some(s.to_string())).collect()
}

/// `n` boş ekrandan sonra `last` (sınır: kaçıncı yakalamada görüldüğü).
fn after(n: usize, last: &str, tail: &str) -> Vec<Option<String>> {
    let mut v = vec![Some("calisiyor...".to_string()); n];
    v.push(Some(last.to_string()));
    v.push(Some(tail.to_string()));
    v
}

fn pane_cases() -> Vec<Case> {
    let perm = "Do you want to proceed?\n❯ 1. Yes\n  2. No";
    let both = "Set model to x\nSwitch model?\nChange effort level?\nSet effort level to x";
    let named: Vec<(&str, Vec<Option<String>>, Value)> = vec![
        ("izin", some(&[perm]), json!({})),
        ("model-diyalog", some(&["Switch model?\n❯ Yes", "Set model to sonnet"]), json!({})),
        ("model-uygulandi", some(&["Set model to sonnet"]), json!({})),
        ("model-vazgecildi", some(&["Kept model as opus"]), json!({})),
        ("effort-diyalog", some(&["Change effort level?", "Set effort level to high"]), json!({})),
        ("effort-uygulandi", some(&["Set effort level to high"]), json!({})),
        ("effort-reddedildi", some(&["Not applied: x"]), json!({})),
        ("effort-tavan", some(&["x exceeds the cap y"]), json!({})),
        ("effort-hata", some(&["Failed to set effort level"]), json!({})),
        ("yaziyor", some(&["kullanıcı yazıyor..."]), json!({})),
        ("ansi-model", some(&[ANSI_SWITCH, "Set model to sonnet"]), json!({})),
        ("ansi-effort", some(&[ANSI_EFFORT, "Set effort level to high"]), json!({})),
        ("ikisi-birden", some(&[both]), json!({})),
        ("diyalog-kalir", some(&["Switch model?\nChange effort level?"]), json!({})),
        ("eski-isaret", some(&["Set model to a\nSet effort level to b", "Switch model?\nChange effort level?"]), json!({})),
        ("yakalama-yok", vec![None], json!({})),
        ("ekran-hic", vec![], json!({})),
        ("yok-sonra-diyalog", vec![None, None, Some("Switch model?\nChange effort level?".into()), None], json!({})),
        ("bos", some(&[""]), json!({})),
        ("gonderilemedi", some(&["Switch model?"]), json!({"send_ok": false})),
        ("tus-basarisiz", some(&["Switch model?\nChange effort level?"]), json!({"keys": [false]})),
        ("down-gitti-enter-yok", some(&["Switch model?"]), json!({"keys": [true, false]})),
        ("yavas-yakalama", some(&["x"]), json!({"capture_cost": 25.0})),
        ("yavas-yakalama-son-diyalog", some(&["x", "Switch model?\nChange effort level?"]), json!({"capture_cost": 25.0})),
        ("yavas-gonderim", some(&["Switch model?"]), json!({"send_cost": 100.0})),
        ("tam-sinir", some(&["x", "x", "Switch model?\nChange effort level?"]), json!({"capture_cost": 3.7})),
    ];
    let mut cases = Vec::new();
    for (which, which_id) in [("model", "model"), ("effort", "effort"), ("dismiss", "dialog")] {
        for (id, screens, extra) in &named {
            cases.push(pane_case(
                format!("g4-pane-{which_id}-{id}"),
                Pane { which, cli: "claude", screens: screens.clone(), extra: extra.clone() },
            ));
        }
        // claude dışı: hiçbir çağrı yok
        for cli in CLIS.iter().skip(1) {
            cases.push(pane_case(
                format!("g4-pane-{which_id}-diger-{cli}"),
                Pane { which, cli, screens: some(&["Switch model?\nChange effort level?"]), extra: json!({}) },
            ));
        }
        // diyalog/işaret kaçıncı yakalamada: süre sınırının iki yanı (döngü içi, son bakış, hiç)
        let (dialog, done, last): (&str, &str, usize) = match which {
            "effort" => ("Change effort level?", "Set effort level to high", 27),
            "model" => ("Switch model?", "Set model to sonnet", 67),
            _ => ("Switch model?", "x", 12),
        };
        for n in (0..4).chain(last - 3..last + 4) {
            cases.push(pane_case(
                format!("g4-pane-{which_id}-sinir-diyalog-{n}"),
                Pane { which, cli: "claude", screens: after(n, dialog, done), extra: json!({}) },
            ));
            cases.push(pane_case(
                format!("g4-pane-{which_id}-sinir-isaret-{n}"),
                Pane { which, cli: "claude", screens: after(n, done, dialog), extra: json!({}) },
            ));
        }
    }
    let mut r = Rng(43);
    for i in 0..900 {
        let which = ["model", "effort", "dismiss"][r.below(3)];
        let n = r.below(8);
        let screens: Vec<Option<String>> =
            (0..n).map(|_| (r.below(8) != 0).then(|| if r.below(3) == 0 { String::new() } else { r.soup(FRAGMENTS, 7) })).collect();
        let cost = [0.0, 0.0, 0.05, 0.7, 2.9, 9.0][r.below(6)];
        let keys: Vec<bool> = (0..r.below(3)).map(|_| r.below(4) != 0).collect();
        let t0 = [0.0, 0.1, 1000.0, 123456.789][r.below(4)];
        let extra = json!({"capture_cost": cost, "keys": keys, "send_ok": r.below(12) != 0, "t0": t0});
        cases.push(pane_case(format!("g4-pane-rastgele-{i}"), Pane { which, cli: "claude", screens, extra }));
    }
    cases
}

pub fn run() {
    let mut r = Runner::new();
    r.run(static_cases(), &[], rs_static);
    let (strip, modes): (Vec<Case>, Vec<Case>) = text_cases().into_iter().partition(|c| c.op == "g4_strip");
    r.run(strip, &[], rs_strip);
    r.run(modes, &[], rs_modes);
    r.run(pane_cases(), &[], rs_pane);
    r.finish("tui");
}
