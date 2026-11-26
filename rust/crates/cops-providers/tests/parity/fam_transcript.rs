//! Aile (G3): claude transkriptinden model/effort ve önbellek sıcaklığı (`last_assistant_*`, `last_real_request_epoch`,
//! `_row_epoch`, `live_or_spawn_*`, `last_request_epoch`, önbellek ömrü ve effort kuralı). Senaryolar
//! `py/tests/test_{handover_cache_policy,live_model_effort}.py` + pencere sınırları ve bozuk girdi. Tüm veri sentetik.

use crate::common::*;
use crate::fam_bg::{random_stamps, Rng};
use cops_providers::bg_work::{iso_epoch, Clock};
use cops_providers::claude_transcript::{FIRST_WINDOW_BYTES, MAX_WINDOW_BYTES, PROMPT_CACHE_TTL_SECONDS};
use cops_providers::pyjson::Py;
use cops_providers::{Cli, Live};
use serde_json::{json, Value};

/// 2027-01-15T08:00:00Z
const NOW: i64 = 1_800_000_000;
/// `since` (süreç başlangıcı) olarak kullanılan an: `stamp(0)`.
const START: f64 = NOW as f64;
const CLIS: [&str; 7] = ["claude", "agy", "codex", "copilot", "shell", "ucli", "bogus"];
const CWD: &str = "work/p1";

/// `NOW + delta` saniyenin ISO damgası (aynı gün içinde).
fn stamp(delta: i64) -> String {
    let t = 8 * 3600 + delta;
    assert!((0..86_400).contains(&t), "damga gün dışı: {delta}");
    format!("2027-01-15T{:02}:{:02}:{:02}.000Z", t / 3600, t / 60 % 60, t % 60)
}

/// Gerçek istek satırı.
fn request(delta: i64, model: &str, tokens: [i64; 3]) -> String {
    json!({"type": "assistant", "timestamp": stamp(delta),
           "message": {"model": model, "usage": {"input_tokens": tokens[0],
                       "cache_creation_input_tokens": tokens[1], "cache_read_input_tokens": tokens[2]}}})
    .to_string()
}

fn real(delta: i64, model: &str) -> String {
    request(delta, model, [2, 0, 400_000])
}

fn turn(delta: i64, model: &str, effort: Option<&str>) -> String {
    let mut row = json!({"type": "assistant", "timestamp": stamp(delta), "message": {"model": model}});
    if let Some(e) = effort {
        row["effort"] = e.into();
    }
    row.to_string()
}

fn lines(rows: &[String]) -> Vec<u8> {
    rows.iter().flat_map(|r| format!("{r}\n").into_bytes()).collect()
}

fn project(cwd: &str) -> String {
    let encoded: String = cwd.chars().map(|c| if c.is_ascii_alphanumeric() { c } else { '-' }).collect();
    format!("home/.claude/projects/{encoded}")
}

struct Build<'a> {
    e: &'a Env,
    cases: Vec<Case>,
}

impl Build<'_> {
    fn abs(&self, rel: &str) -> String {
        format!("{}/{rel}", self.e.root)
    }

    fn case(&self, id: &str, args: Value) -> Case {
        Case::new(format!("transkript-{id}"), "transcript", args)
    }

    /// Tek dosya; `since`siz ve `since = START` ile okunur.
    fn read_case(&self, id: &str, data: impl Into<Vec<u8>>) -> Case {
        let path = self.abs("work/t.jsonl");
        self.case(id, json!({"reads": [{"path": path}, {"path": path, "since": START}]}))
            .file(Fx::File("work/t.jsonl".into(), data.into(), 0o644))
    }

    fn read(&mut self, id: &str, data: impl Into<Vec<u8>>) {
        let c = self.read_case(id, data);
        self.cases.push(c);
    }

    /// Bilinen ayrışma: Rust sonucu `expect` ([`since`siz, `since`li] model/effort/istek) ile ayrıca doğrulanır.
    fn diverge(&mut self, id: &str, data: impl Into<Vec<u8>>, expect: Value, why: &'static str) {
        let mut c = self.read_case(&format!("sapma-{id}"), data).known(why);
        c.args["expect"] = expect;
        self.cases.push(c);
    }
}

fn both(model: Option<&str>, effort: Option<&str>, request: Option<f64>) -> Value {
    json!({"model": model, "effort": effort, "request": request})
}

fn at(delta: i64) -> f64 {
    START + delta as f64
}

/// Python testlerindeki senaryolar ve satır biçimi sınırları.
fn rows(b: &mut Build<'_>) {
    let user = json!({"type": "user", "timestamp": stamp(-500)}).to_string();
    let m = "claude-opus-5-5";
    let synthetic_zero = request(-10, "<synthetic>", [0, 0, 0]);
    let side = |d| {
        let mut v: Value = serde_json::from_str(&real(d, m)).unwrap();
        v["isSidechain"] = true.into();
        v.to_string()
    };
    let no_usage = json!({"type": "assistant", "timestamp": stamp(-10), "message": {"model": m}}).to_string();
    let no_ts = json!({"type": "assistant", "message": {"model": m}}).to_string();
    let scenarios: Vec<(&str, Vec<String>)> = vec![
        ("son-istek", vec![real(-500, m), real(-100, m)]),
        ("alt-ajan", vec![real(-4000, m), side(-10)]),
        ("kullanimsiz", vec![real(-4000, m), no_usage.clone(), request(-5, m, [0, 0, 0])]),
        ("yalniz-kullanici", vec![user.clone()]),
        ("bos", vec![]),
        ("surec-sonrasi", vec![turn(-100, "claude-sonnet-5", Some("max")), turn(50, "claude-sonnet-5-5", Some("high"))]),
        ("onceki-surec", vec![user.clone(), turn(-100, "claude-sonnet-5-5", Some("max"))]),
        ("damgasiz", vec![turn(10, "claude-sonnet-5", None), no_ts.clone()]),
        ("ilk-eskide-dur", vec![turn(10, "claude-sonnet-5", None), turn(-10, "claude-haiku-5-5", None)]),
        ("eski-damgasiz-onde", vec![no_ts, turn(-10, "claude-haiku-5-5", None)]),
        ("tam-sinir", vec![turn(0, m, Some("low"))]),
        ("sinir-alti", vec![turn(-1, m, Some("low"))]),
        ("eski-degersiz", vec![turn(5, m, Some("high")), json!({"type": "assistant", "timestamp": stamp(-1)}).to_string().replace("}", r#","message":{}}"#)]),
        ("eski-kullanici", vec![turn(5, m, Some("high")), user.clone()]),
        ("effort-eski-satirda", vec![turn(5, "claude-sonnet-5-5", Some("max")), turn(9, "claude-haiku-5-5", None)]),
        ("effort-bos", vec![turn(5, m, Some("high")), turn(9, m, Some(""))]),
        ("model-bos", vec![turn(5, "claude-sonnet-5", None), turn(9, "", None)]),
        ("sentetik-sifir-effortlu", vec![real(-4000, m), synthetic_zero]),
    ];
    for (id, r) in &scenarios {
        // model okuyan yer tutucu satırları ayrışır (aşağıda): bu senaryo yalnız istek zamanı için sapma
        if *id == "sentetik-sifir-effortlu" {
            b.diverge(
                id,
                lines(r),
                json!([both(Some(m), None, Some(at(-4000))), both(None, None, Some(at(-4000)))]),
                "`<synthetic>` yer tutucusu: Python canlı model diye döndürür, Rust gerçek modeli arar",
            );
            continue;
        }
        b.read(id, lines(r));
    }
    // satır alanlarının tip/değer sınırları
    let variants: Vec<(&str, &str)> = vec![
        ("type-sayi", r#"{"type":5,"message":{"model":"x"}}"#),
        ("type-liste", r#"{"type":["assistant"],"message":{"model":"x"}}"#),
        ("type-buyuk", r#"{"type":"Assistant","message":{"model":"x"}}"#),
        ("mesaj-yok", r#"{"type":"assistant","effort":"low"}"#),
        ("mesaj-bos", r#"{"type":"assistant","message":{}}"#),
        ("model-null", r#"{"type":"assistant","message":{"model":null}}"#),
        ("model-sifir", r#"{"type":"assistant","message":{"model":0}}"#),
        ("model-false", r#"{"type":"assistant","message":{"model":false}}"#),
        ("model-bos-liste", r#"{"type":"assistant","message":{"model":[]}}"#),
        ("effort-sayi", r#"{"type":"assistant","effort":3,"message":{}}"#),
        ("effort-liste", r#"{"type":"assistant","effort":["max"],"message":{}}"#),
        ("effort-null", r#"{"type":"assistant","effort":null,"message":{}}"#),
        ("effort-mesajda", r#"{"type":"assistant","message":{"effort":"max"}}"#),
        ("yinelenen", r#"{"type":"user","type":"assistant","effort":"a","effort":"b","message":{"model":"ilk","model":"son"}}"#),
        ("nan", r#"{"type":"assistant","x":NaN,"effort":"low","message":{"model":"x"}}"#),
        ("vekil-disi-alan", r#"{"type":"assistant","x":"\ud83d","message":{"model":"x"}}"#),
        ("bom", "\u{feff}{\"type\":\"assistant\",\"message\":{\"model\":\"x\"}}"),
        ("kirpma", "\u{1c}\u{a0}\u{3000} \t{\"type\":\"assistant\",\"message\":{\"model\":\"x\"}}\u{85}\r"),
        ("u2028", "{\"type\":\"assistant\",\"message\":{\"model\":\"x\"}}\u{2028}{\"type\":\"assistant\",\"message\":{\"model\":\"y\"}}"),
        ("yalniz-cr", "{\"type\":\"assistant\",\"message\":{\"model\":\"x\"}}\r{\"type\":\"assistant\",\"message\":{\"model\":\"y\"}}"),
        ("kuyruk-cop", r#"{"type":"assistant","message":{"model":"x"}} x"#),
        ("yarim", r#"{"type":"assistant","message":{"model":"x""#),
        ("unicode-model", r#"{"type":"assistant","effort":"çok","message":{"model":"modél-🙂"}}"#),
    ];
    for (id, line) in variants {
        let mut data = lines(&[real(-30, m), turn(-20, "onceki", Some("medium"))]);
        data.extend_from_slice(line.as_bytes());
        b.read(&format!("satir-{id}"), data);
    }
    let usage: Vec<(&str, &str, &str)> = vec![
        ("sidechain-metin", r#""isSidechain":"false","#, r#"{"input_tokens":1}"#),
        ("sidechain-sifir", r#""isSidechain":0,"#, r#"{"input_tokens":1}"#),
        ("sidechain-bos", r#""isSidechain":[],"#, r#"{"input_tokens":1}"#),
        ("bool", "", r#"{"input_tokens":true}"#),
        ("kesir", "", r#"{"input_tokens":1.5}"#),
        ("metin", "", r#"{"input_tokens":"5"}"#),
        ("negatif", "", r#"{"input_tokens":-5}"#),
        ("toplam-sifir", "", r#"{"input_tokens":5,"cache_read_input_tokens":-5}"#),
        ("toplam-bir", "", r#"{"input_tokens":5,"cache_creation_input_tokens":-4}"#),
        ("yalniz-yazma", "", r#"{"cache_creation_input_tokens":9}"#),
        ("yalniz-cikti", "", r#"{"output_tokens":9}"#),
        ("dev", "", r#"{"input_tokens":123456789012345678901234567890}"#),
        ("eksi-dev", "", r#"{"input_tokens":-123456789012345678901234567890,"cache_read_input_tokens":3}"#),
        ("i64-tasma", "", r#"{"input_tokens":9223372036854775807,"cache_read_input_tokens":9223372036854775807}"#),
        ("liste", "", r#"[1]"#),
        ("null", "", "null"),
        ("bos", "", "{}"),
    ];
    for (id, extra, u) in usage {
        let line = format!(
            r#"{{"type":"assistant",{extra}"timestamp":"{}","message":{{"model":"x","usage":{u}}}}}"#,
            stamp(-5)
        );
        b.read(&format!("kullanim-{id}"), lines(&[real(-30, m), line]));
    }
    for (id, model) in [("sayi", "5"), ("sifir", "0"), ("bos", r#""""#), ("null", "null"), ("sentetik", r#""<synthetic>""#)] {
        let line = format!(
            r#"{{"type":"assistant","timestamp":"{}","message":{{"model":{model},"usage":{{"input_tokens":1}}}}}}"#,
            stamp(-5)
        );
        // yalnız istek zamanı karşılaştırılır: sayı/yer tutucu model okuyucuda ayrışır
        let path = b.abs("work/t.jsonl");
        let data = lines(&[real(-30, m), line]);
        if matches!(id, "sayi" | "sentetik") {
            let model_after = Some(m);
            b.diverge(
                &format!("istek-model-{id}"),
                data,
                json!([both(model_after, None, Some(if id == "sayi" { at(-5) } else { at(-30) })),
                       both(None, None, Some(if id == "sayi" { at(-5) } else { at(-30) }))]),
                "metin olmayan ya da yer tutucu model: Python model diye döndürür, Rust gerçek modeli arar",
            );
        } else {
            let c = b.case(&format!("istek-model-{id}"), json!({"reads": [{"path": path}]}))
                .file(Fx::File("work/t.jsonl".into(), data, 0o644));
            b.cases.push(c);
        }
    }
    for (id, ts) in [
        ("yok", None),
        ("sayi", Some("5")),
        ("bozuk", Some(r#""dün""#)),
        ("sifir-an", Some(r#""1970-01-01T00:00:00Z""#)),
        ("sifir-arti", Some(r#""1970-01-01T00:00:00.000001Z""#)),
        ("eski", Some(r#""1969-12-31T23:59:59Z""#)),
        ("gelecek", Some(r#""2150-01-01T00:00:00Z""#)),
        ("dilimli", Some(r#""2027-01-15T11:00:00+03:00""#)),
        ("dilimsiz", Some(r#""2027-01-15T11:00:00""#)),
    ] {
        let ts = ts.map_or(String::new(), |t| format!(r#""timestamp":{t},"#));
        let line = format!(r#"{{"type":"assistant",{ts}"message":{{"model":"x","usage":{{"input_tokens":1}}}}}}"#);
        for tz in ["UTC0", "XXX-3"] {
            let path = b.abs("work/t.jsonl");
            let data = lines(&[real(-30, m), line.clone()]);
            let c = b
                .case(&format!("damga-{id}-{tz}"), json!({"tz": tz, "reads": [{"path": path}, {"path": path, "since": START}]}))
                .file(Fx::File("work/t.jsonl".into(), data, 0o644));
            b.cases.push(c);
        }
    }
}

fn divergences(b: &mut Build<'_>) {
    let m = "claude-opus-5-5";
    let base = real(-30, m).replace(r#""type":"assistant""#, r#""type":"assistant","effort":"low""#);
    let found = |since: bool| {
        let r = both(Some(m), Some("low"), Some(at(-30)));
        let none = both(None, None, Some(at(-30)));
        if since { none } else { r }
    };
    let expect = json!([found(false), found(true)]);
    for (id, line) in [("satir-sayi", "5"), ("satir-liste", "[1]"), ("satir-metin", r#""assistant""#), ("satir-null", "null")] {
        b.diverge(
            id,
            lines(&[base.clone(), line.into()]),
            expect.clone(),
            "nesne olmayan JSON satırı: Python `AttributeError` atar, Rust satırı atlar",
        );
    }
    for (id, msg) in [("mesaj-null", "null"), ("mesaj-metin", r#""x""#), ("mesaj-liste", "[1]"), ("mesaj-sayi", "3")] {
        b.diverge(
            id,
            lines(&[base.clone(), format!(r#"{{"type":"assistant","message":{msg}}}"#)]),
            expect.clone(),
            "nesne olmayan `message`: Python model okurken `AttributeError` atar, Rust satırı atlar",
        );
    }
    for (id, model) in [("model-sayi", "5"), ("model-liste", r#"["a"]"#), ("model-nesne", r#"{"a":1}"#), ("model-true", "true")] {
        b.diverge(
            id,
            lines(&[base.clone(), format!(r#"{{"type":"assistant","message":{{"model":{model}}}}}"#)]),
            expect.clone(),
            "metin olmayan model: Python değeri olduğu gibi döndürür, Rust satırı atlar",
        );
    }
    b.diverge(
        "sentetik-yalniz-yeni",
        lines(&[base.clone(), turn(7, "<synthetic>", None)]),
        json!([both(Some(m), Some("low"), Some(at(-30))), both(None, None, Some(at(-30)))]),
        "süreç sonrası yalnız `<synthetic>`: Python onu canlı model sayar, Rust bilinmiyor der",
    );
    let deep = format!(
        r#"{{"type":"assistant","effort":"max","message":{{"model":"derin"}},"d":{}{}}}"#,
        "[".repeat(600),
        "]".repeat(600)
    );
    b.diverge("derin", lines(&[base.clone(), deep]), expect.clone(), "512'den derin satır: Python okur, Rust atlar");
    b.diverge(
        "vekil",
        lines(&[base.clone(), r#"{"type":"assistant","effort":"low","message":{"model":"a\ud83d"}}"#.into()]),
        json!([both(Some("a\u{fffd}"), Some("low"), Some(at(-30))), both(Some("a\u{fffd}"), Some("low"), Some(at(-30)))]),
        "eşlenmemiş vekil: Python vekili taşır, Rust U+FFFD",
    );
    b.diverge(
        "yil-bir",
        lines(&[turn(20, "yeni", Some("high")), r#"{"type":"assistant","timestamp":"0001-01-01T00:00:00","message":{}}"#.into()]),
        json!([both(Some("yeni"), Some("high"), None), both(None, None, None)]),
        "1. yılın ilk gününde dilimsiz damga: Python 'damga yok' sayıp sürer, Rust çok eski sayıp durur",
    );
}

/// `row` satırının başı dosya sonundan tam `distance` bayt geride; öncesinde ve sonrasında satır dolgusu.
fn placed(row: &str, distance: usize, pad: &str) -> Vec<u8> {
    let mut data = lines(&[turn(-900, "en-eski", Some("low"))]).repeat(3);
    let tail = distance.checked_sub(row.len() + 1).expect("mesafe satırdan kısa");
    data.extend_from_slice(row.as_bytes());
    data.push(b'\n');
    let line = format!("{{\"type\":\"user\",\"pad\":\"{pad}\"}}\n");
    let mut after = line.repeat(tail / line.len()).into_bytes();
    after.resize(tail, b' ');
    data.extend(after);
    data
}

fn windows(b: &mut Build<'_>) {
    let row = real(-42, "hedef").replace(r#""type":"assistant""#, r#""type":"assistant","effort":"max""#);
    let mut window = FIRST_WINDOW_BYTES;
    while window <= MAX_WINDOW_BYTES {
        for delta in [-1i64, 0, 1] {
            let distance = (window as i64 + delta) as usize;
            b.read(&format!("pencere-{window}-{delta}"), placed(&row, distance, &"x".repeat(900)));
        }
        window *= 4;
    }
    // pencere başı çok baytlı karakterin ortasına düşer
    for shift in 0..4 {
        b.read(
            &format!("pencere-utf8-{shift}"),
            placed(&row, 70_000 + shift, &"ğ🙂€".repeat(100)),
        );
    }
    // ilk pencereden uzun tek satır (dosyada başka satır yok / var)
    let long = format!(r#"{{"type":"assistant","effort":"high","message":{{"model":"uzun"}},"p":"{}"}}"#, "y".repeat(200_000));
    b.read("pencere-uzun-satir", lines(std::slice::from_ref(&long)));
    b.read("pencere-uzun-satir-onceli", lines(&[real(-60, "once"), long]));
    // model ilk pencerede, effort yalnız büyüyen pencerede
    let mut data = lines(&[turn(1, "uzak", Some("xhigh"))]);
    data.extend(placed(&turn(2, "yakin", None), 1_000, "x"));
    let mut far = lines(&[turn(1, "uzak", Some("xhigh"))]);
    far.extend(format!("{{\"pad\":\"{}\"}}\n", "z".repeat(100_000)).into_bytes());
    far.extend(lines(&[turn(2, "yakin", None)]));
    b.read("pencere-effort-uzakta", far);
    b.read("pencere-effort-yakinda", data);
    // sonda satır sonu yok / yarım yazılan satır
    let mut open = lines(&[real(-60, "tam")]);
    open.extend_from_slice(real(-1, "satir-sonsuz").as_bytes());
    b.read("sonda-satirsonu-yok", open.clone());
    open.truncate(open.len() - 7);
    b.read("sonda-yarim", open);
    b.read("yalniz-yenisatir", b"\n\n\r\n  \n".to_vec());
    b.read("bos-dosya", Vec::new());
    let mut broken = lines(&[real(-60, "tam")]);
    broken.extend_from_slice(b"\xff\xfe\xed\xa0\x80 \xc3\n{\"type\":\"assistant\",\"effort\":\"a\xffb\",\"message\":{\"model\":\"m\xc3\"}}\n\xe2\x82");
    b.read("bozuk-utf8", broken);
    b.read("dev-sayi", lines(&[real(-60, "tam"), format!(r#"{{"type":"assistant","message":{{"model":"dev"}},"n":{}}}"#, "9".repeat(5000))]));
    b.read("ikili", (0..=255u8).cycle().take(5000).collect::<Vec<_>>());
    // yok, dizin, link, izinsiz
    let paths: Vec<Value> = ["work/yok", "work/p1", "work/link", "work/kapali", "work/kopuk"]
        .iter()
        .map(|p| json!({"path": b.abs(p)}))
        .collect();
    let c = b
        .case("yollar", json!({"reads": paths}))
        .file(Fx::File("work/hedef".into(), lines(&[real(-9, "x")]), 0o644))
        .file(Fx::Link("work/link".into(), "hedef".into()))
        .file(Fx::Link("work/kopuk".into(), "yok".into()))
        .file(Fx::File("work/kapali".into(), lines(&[real(-9, "x")]), 0o000));
    b.cases.push(c);
}

/// Rastgele satır karışımları (ayrışan türler hariç) ve bozulmuş satırlar.
fn random_files(b: &mut Build<'_>) {
    let mut r = Rng(7);
    const MODELS: [&str; 4] = ["claude-opus-5-5", "claude-sonnet-5", "ğ-model", ""];
    const EFFORTS: [&str; 4] = ["low", "max", "", "çok"];
    const NOISE: [&str; 12] = ["", " ", "{", "}", "x", "{\"type\":\"assistant\"", "\u{1c}", "\r", "{}", "[", "\"", "\u{feff}"];
    for i in 0..400 {
        let mut data = Vec::new();
        for _ in 0..1 + r.below(9) {
            let mut row = serde_json::Map::new();
            let kind = ["assistant", "assistant", "assistant", "user", "system"][r.below(5)];
            row.insert("type".into(), kind.into());
            let delta = r.below(400) as i64 - 200;
            match r.below(8) {
                0 => {}
                1 => drop(row.insert("timestamp".into(), "bozuk".into())),
                2 => drop(row.insert("timestamp".into(), 5.into())),
                _ => drop(row.insert("timestamp".into(), stamp(delta).into())),
            }
            if r.below(3) > 0 {
                row.insert("effort".into(), EFFORTS[r.below(4)].into());
            }
            if r.below(6) == 0 {
                row.insert("isSidechain".into(), (r.below(2) == 0).into());
            }
            let mut message = serde_json::Map::new();
            if r.below(5) > 0 {
                message.insert("model".into(), MODELS[r.below(4)].into());
            }
            if r.below(4) > 0 {
                let n = [0i64, 1, -1, 500][r.below(4)];
                message.insert("usage".into(), json!({"input_tokens": n, "cache_read_input_tokens": r.below(2)}));
            }
            if r.below(7) > 0 {
                row.insert("message".into(), message.into());
            }
            let mut line: Vec<char> = Value::Object(row).to_string().chars().collect();
            if r.below(8) == 0 {
                let cut = r.below(line.len());
                line.truncate(cut);
            }
            if r.below(8) == 0 {
                let at = r.below(line.len() + 1);
                line.splice(at..at, NOISE[r.below(NOISE.len())].chars()).for_each(drop);
            }
            let line: String = line.into_iter().collect();
            // gürültü geçerli ama nesne olmayan bir satır üretebilir: o ayrışma `sapma-satir-*`de
            if Py::parse(line.trim()).is_some_and(|v| !v.is_object()) {
                continue;
            }
            data.extend(line.into_bytes());
            data.extend_from_slice([b"\n".as_slice(), b"\r\n", b"\n\n"][r.below(3)]);
        }
        if r.below(5) == 0 {
            let cut = r.below(data.len() + 1);
            data.truncate(cut);
        }
        let path = b.abs("work/t.jsonl");
        let since = at(r.below(400) as i64 - 200);
        let c = b
            .case(&format!("rastgele-{i}"), json!({"reads": [{"path": path}, {"path": path, "since": since}]}))
            .file(Fx::File("work/t.jsonl".into(), data, 0o644));
        b.cases.push(c);
    }
}

fn stamps_and_models(b: &mut Build<'_>) {
    for tz in ["UTC0", "XXX-3"] {
        let mut stamps: Vec<Value> = random_stamps().into_iter().map(Value::from).collect();
        stamps.extend([json!(null), json!(5), json!(1.5), json!(true), json!([]), json!({}), json!(""), json!("Z")]);
        let c = b.case(&format!("damga-listesi-{tz}"), json!({"tz": tz, "stamps": stamps}));
        b.cases.push(c);
    }
    let mut models: Vec<Value> = [
        "claude-sonnet-5-5", "claude-sonnet-5-5[1m]", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1",
        "claude-mythos-5-1", "claude-haiku-5-5", "claude-haiku-5-5[1m]", "sonnet", "opus", "fable", "",
        "claude-sonnet-5", "claude-sonnet-5[1m]", "claude-sonnet-5-20260401", "CLAUDE-SONNET-5", "claude-sonnet-4-6",
        "claude-opus-4-8", "claude-haiku-4-5-20251001", "claude-fable-5", "claude-mythos-5", "claude-3-5-sonnet",
        " claude-sonnet-5", "x-claude-sonnet-5", "claude-sonnet-5-", "claude-sonnet-5-x", "claude-sonnet-5-1x",
        "claude-sonnet-5-12", "claude-sonnet-5-1-2", "claude-sonnet-5-\u{663}", "claude-sonnet-5-\u{663}\u{664}",
        "claude-sonnet-50", "claude-opus-40", "claude-haiku-4", "claude-fable-4", "claude-opus-3", "claude-30",
        "claude-", "claude-sonnet-5\n", "<synthetic>", "Claude-Fable-5", "CLAUDE-SONNET-5-5", "claude-İ", "gpt-5",
    ]
    .iter()
    .map(|s| Value::from(*s))
    .collect();
    models.push(Value::Null);
    let mut r = Rng(8);
    const PARTS: [&str; 16] = [
        "claude", "-", "sonnet", "opus", "haiku", "fable", "mythos", "3", "4", "5", "0", "1", "[1m]", "x", "S", " ",
    ];
    for _ in 0..2000 {
        let tail = r.soup(&PARTS, 5);
        models.push(Value::from(format!("claude-{tail}")));
        let family = PARTS[2 + r.below(5)];
        models.push(Value::from(format!("claude-{family}-{}{}", PARTS[7 + r.below(3)], r.soup(&PARTS, 3))));
    }
    let c = b.case("model-listesi", json!({"models": models, "clis": CLIS}));
    b.cases.push(c);
}

/// `last_request_epoch`: yalnız tam eşleşen dosyalar, iki sid adayı.
fn requests(b: &mut Build<'_>) {
    let cwd = b.abs(CWD);
    let dir = project(&cwd);
    let put = |c: Case, name: &str, delta: i64| {
        c.file(Fx::File(format!("{dir}/{name}.jsonl"), lines(&[real(delta, "claude-opus-5-5")]), 0o644))
    };
    let queries: Vec<(&str, Option<&str>, Option<i64>)> = vec![
        ("sid", Some("old-sid"), None),
        ("sid-yok", None, None),
        ("sid-bos", Some(""), None),
        ("baska", Some("other"), None),
        ("pid", None, Some(4242)),
        ("pid-sifir", None, Some(0)),
        ("pid-kayitsiz", None, Some(7)),
        ("pid-dosyasiz", None, Some(4243)),
        ("pid-bos-sid", None, Some(4244)),
        ("iki-aday-yeni-pid", Some("old-sid"), Some(4242)),
        ("iki-aday-yeni-cmd", Some("new-sid"), Some(4245)),
        ("ayni-aday", Some("new-sid"), Some(4242)),
        ("eksik-cmd", Some("missing"), Some(4242)),
        ("eksik-pid", Some("old-sid"), Some(4243)),
        ("ikisi-eksik", Some("missing"), Some(4243)),
        ("bos-konusma", Some("empty"), None),
        ("bos-ve-dolu", Some("empty"), Some(4242)),
        ("dizin", Some("folder"), None),
        ("nokta", Some("."), None),
        ("ust", Some("../p/old-sid"), None),
        ("nul", Some("old-sid\u{0}"), None),
        ("onek", Some("old"), None),
    ];
    for cli in ["claude", "codex", "ucli", "bogus"] {
        let list: Vec<Value> =
            queries.iter().map(|(_, sid, pid)| json!({"cli": cli, "cwd": cwd, "sid": sid, "pid": pid})).collect();
        let mut c = b.case(&format!("istek-{cli}"), json!({"requests": list})).facts(json!({"session_sid": {
            "4242": "new-sid", "4243": "missing", "4244": "", "4245": "old-sid", "0": "new-sid"}}));
        c = put(c, "old-sid", -9000);
        c = put(c, "new-sid", -40);
        c = put(c, "sibling", -5);
        c = c
            .file(Fx::File(format!("{dir}/empty.jsonl"), lines(&[r#"{"type":"system"}"#.into()]), 0o644))
            .file(Fx::Dir(format!("{dir}/folder.jsonl"), 0o755));
        b.cases.push(c);
    }
    // mutlak yol biçimli sid proje dizinini yok sayar
    let outside = b.abs("work/disari");
    let c = b
        .case("istek-mutlak", json!({"requests": [{"cli": "claude", "cwd": cwd, "sid": outside}]}))
        .file(Fx::File("work/disari.jsonl".into(), lines(&[real(-3, "x")]), 0o644));
    b.cases.push(c);
    let mut c = b
        .case("sapma-uzun-sid", json!({"requests": [{"cli": "claude", "cwd": cwd, "sid": "s".repeat(300), "pid": 4242}]}))
        .facts(json!({"session_sid": {"4242": "new-sid"}}))
        .known("dosya adı sınırını aşan sid: Python `is_file` `OSError` atar, Rust adayı yok sayıp diğerine bakar");
    c = put(c, "new-sid", -40);
    c.args["expect_requests"] = json!([at(-40)]);
    b.cases.push(c);
}

/// `live_or_spawn_*`: claude dışında ya da transkript/tur yoksa spawn değeri. (Transkript çözümü G1: test uygulaması.)
fn live(b: &mut Build<'_>) {
    let cwd = b.abs(CWD);
    let dir = project(&cwd);
    let other = b.abs("work/bos-proje");
    let q = |cli: &str, cwd: &str, sid: Option<&str>| json!({"cli": cli, "cwd": cwd, "sid": sid, "fallback": "spawn"});
    let queries: Vec<Value> = ["claude", "codex", "agy", "ucli", "shell", "bogus", "", "Claude"]
        .iter()
        .map(|cli| q(cli, &cwd, Some("s1")))
        .chain([
            q("claude", &cwd, Some("effortsuz")),
            q("claude", &cwd, Some("modelsiz")),
            q("claude", &cwd, Some("turu-yok")),
            q("claude", &other, Some("s1")),
            json!({"cli": "claude", "cwd": cwd, "sid": "s1", "fallback": ""}),
            json!({"cli": "claude", "cwd": other, "sid": null, "fallback": ""}),
        ])
        .collect();
    let c = b
        .case("canli", json!({"live": queries}))
        .file(Fx::File(format!("{dir}/s1.jsonl"), lines(&[turn(0, "claude-sonnet-5-5", Some("high"))]), 0o644))
        .file(Fx::File(format!("{dir}/effortsuz.jsonl"), lines(&[turn(1, "claude-haiku-5-5", None)]), 0o644))
        .file(Fx::File(format!("{dir}/modelsiz.jsonl"), lines(&[r#"{"type":"assistant","effort":"low"}"#.into()]), 0o644))
        .file(Fx::File(format!("{dir}/turu-yok.jsonl"), lines(&[r#"{"type":"user"}"#.into()]), 0o644));
    b.cases.push(c);
    let mut c = b
        .case("sapma-canli-sentetik", json!({"live": [q("claude", &cwd, Some("s1"))]}))
        .file(Fx::File(
            format!("{dir}/s1.jsonl"),
            lines(&[turn(1, "claude-opus-5-5", Some("high")), turn(2, "<synthetic>", None)]),
            0o644,
        ))
        .known("`<synthetic>` yer tutucusu: Python canlı model diye döndürür, Rust son gerçek modeli verir");
    c.args["expect_live"] = json!([["claude-opus-5-5", "high"]]);
    b.cases.push(c);
}

fn rs_transcript(e: &Env, c: &Case) -> RsOut {
    let offset = if c.args["tz"] == "XXX-3" { 3 * 3600 } else { 0 };
    let settings = e.settings();
    let paths = e.paths();
    let probe = FsProbe::new(e, c);
    let live = Live { settings: &settings, paths: &paths, probe: &probe, clock: Clock { now: START, utc_offset_secs: offset } };
    let list = |k: &str| c.args.get(k).and_then(Value::as_array).cloned().unwrap_or_default();
    let text = |v: &Value, k: &str| v.get(k).and_then(Value::as_str).map(String::from);
    let epoch = |v: Option<f64>| v.map_or(Value::Null, fjson);
    let clis: Vec<Cli> = list("clis").iter().map(|v| Cli::parse(v.as_str().unwrap())).collect();
    let reads: Vec<Value> = list("reads")
        .iter()
        .map(|r| {
            let path = r["path"].as_str().unwrap();
            let since = r.get("since").and_then(Value::as_f64);
            json!({"model": live.last_assistant_model(path, since), "effort": live.last_assistant_effort(path, since),
                   "request": epoch(live.last_real_request_epoch(path))})
        })
        .collect();
    let stamps: Vec<Value> = list("stamps")
        .iter()
        .map(|v| epoch(iso_epoch(&Py::parse(&v.to_string()).unwrap(), offset)))
        .collect();
    let keeps: Vec<Value> = list("models")
        .iter()
        .map(|m| Value::from(clis.iter().map(|c| c.effort_switch_keeps_cache(m.as_str())).collect::<Vec<_>>()))
        .collect();
    let lives: Vec<Value> = list("live")
        .iter()
        .map(|q| {
            let (cli, cwd, fallback) = (text(q, "cli").unwrap(), text(q, "cwd").unwrap(), text(q, "fallback").unwrap());
            let sid = text(q, "sid");
            json!([live.live_or_spawn_model(&cli, &cwd, sid.as_deref(), &fallback),
                   live.live_or_spawn_effort(&cli, &cwd, sid.as_deref(), &fallback)])
        })
        .collect();
    let requests: Vec<Value> = list("requests")
        .iter()
        .map(|q| {
            let cli = Cli::parse(&text(q, "cli").unwrap());
            let pid = q.get("pid").and_then(Value::as_i64);
            epoch(live.last_request_epoch(cli, &text(q, "cwd").unwrap(), text(q, "sid").as_deref(), pid))
        })
        .collect();
    for (key, got) in [("expect", &reads), ("expect_requests", &requests), ("expect_live", &lives)] {
        if let Some(want) = c.args.get(key) {
            assert_eq!(want, &Value::from(got.clone()), "[{}] Rust sonucu beklenenden farklı ({key})", c.id);
        }
    }
    RsOut::ret(json!({
        "reads": reads,
        "stamps": stamps,
        "keeps": keeps,
        "ttl": clis.iter().map(|c| c.prompt_cache_ttl_seconds()).collect::<Vec<_>>(),
        "live": lives,
        "requests": requests,
        "constants": [FIRST_WINDOW_BYTES, MAX_WINDOW_BYTES, PROMPT_CACHE_TTL_SECONDS],
    }))
}

pub fn run() {
    let mut r = Runner::new();
    let cases = {
        let mut b = Build { e: &r.e, cases: Vec::new() };
        rows(&mut b);
        divergences(&mut b);
        windows(&mut b);
        random_files(&mut b);
        stamps_and_models(&mut b);
        requests(&mut b);
        live(&mut b);
        b.cases
    };
    r.run(cases, &[], rs_transcript);
    r.finish("transcript");
}
