//! Aile (G8 ikinci parça): maliyet defteri (`ucli_cost.py` + `review._scan_usage`) iki dilde AYNI geçici günlük
//! ağacından: toplamlar bit bit (`repr`), durum özeti, kredi dönemi, tavan reddi ve başlatma payı dizileri.

use crate::common::*;
use crate::fam_bg::Rng;
use cops_providers::cost::{self, refusal, write_mult};
use cops_providers::pyfmt::float_repr;
use cops_providers::real::ledger::{self, file_cost_settings, CostLedger};
use cops_providers::settings::UcliCostConfig;
use serde_json::{json, Value};
use std::fs;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const DIR: &str = "home/.claude/claudeops/ucli_usage";

fn now() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64().floor() + 0.25
}

fn log(name: &str, body: &[u8], mode: u32) -> Fx {
    Fx::File(format!("{DIR}/{name}"), body.to_vec(), mode)
}

fn rec(t_ms: f64, prompt: u64) -> String {
    format!("{{\"t\": {t_ms}, \"usage\": {{\"prompt_tokens\": {prompt}, \"completion_tokens\": 7}}}}\n")
}

fn pick<'a>(rng: &mut Rng, from: &[&'a str]) -> &'a str {
    from[rng.below(from.len())]
}

fn random_line(rng: &mut Rng, now: f64) -> String {
    const NUMBERS: [&str; 22] = [
        "0", "1", "7", "1234", "999999", "1000000", "2.5", "0.1", "-1", "-0.0", "NaN", "Infinity", "-Infinity", "1e300",
        "1e15", "1000000000000001", "true", "\"7\"", "null", "123456789012345678901234567890", "[]", "{}",
    ];
    const KEYS: [&str; 10] = [
        "cache_read_input_tokens", "cached_tokens", "cache_read_tokens", "cache_creation_input_tokens",
        "cache_write_tokens", "input_tokens", "prompt_tokens", "output_tokens", "completion_tokens", "baska",
    ];
    match rng.below(12) {
        0 => pick(rng, &["", "{bozuk", "[]", "5", "null", "  ", "{\"usage\": 1}", "{\"t\": 1, \"usage\": [1]}"]).into(),
        1 => {
            let model = pick(rng, &[
                "\"claude-sonnet-5-5\"", "\"claude-haiku-5-5\"", "\"x-opus-5-5-y\"", "\"claude-fable-5-1\"", "\"x\"",
                "5", "\"\"", "null", "[\"sonnet-5-5\"]",
            ]);
            format!("{{\"event\": \"task_start\", \"model\": {model}, \"t\": {}}}", now * 1000.0)
        }
        _ => {
            let fresh = format!("{}", now * 1000.0 - rng.below(100) as f64 * 60_000.0);
            let old = format!("{}", (now - 3.0 * 86400.0) * 1000.0);
            let quoted = format!("\"{fresh}\"");
            let t = match rng.below(14) {
                0 => old,
                1 => quoted,
                2 => pick(rng, &["\"abc\"", "\"\"", "null", "0", "NaN", "Infinity", "-Infinity", "true", "[1]", "{}",
                    "\" 1_0 \"", "\"nan\"", "1e999"]).to_string(),
                3 => format!("1{}", "0".repeat(400)),
                _ => fresh,
            };
            let n = rng.below(5);
            let fields: Vec<String> = (0..n)
                .map(|_| {
                    let key = pick(rng, &KEYS);
                    let value = if rng.below(2) == 0 { rng.below(5_000_000).to_string() } else { pick(rng, &NUMBERS).into() };
                    format!("\"{key}\": {value}")
                })
                .collect();
            format!("{{\"t\": {t}, \"usage\": {{{}}}}}", fields.join(", "))
        }
    }
}

fn random_log(rng: &mut Rng, now: f64) -> Vec<u8> {
    let mut out = Vec::new();
    for _ in 0..rng.below(7) {
        out.extend_from_slice(random_line(rng, now).as_bytes());
        out.extend_from_slice(match rng.below(8) {
            0 => b"\r\n",
            1 => b"\r",
            2 => b"\xff\xc4\n",
            _ => b"\n",
        });
    }
    out
}

fn case(id: String, steps: Vec<Value>) -> Case {
    Case::new(format!("defter-{id}"), "g8x_ledger", json!({"steps": steps}))
}

fn cap(v: Value) -> Value {
    json!({"ucli_cost": v})
}

fn cases() -> Vec<Case> {
    let now = now();
    let ms = now * 1000.0;
    let mut v = Vec::new();
    let mut rng = Rng(0x1ed6e7);
    for i in 0..260 {
        let body = random_log(&mut rng, now);
        let model = ["", "", "", "claude-haiku-5-5", "bilinmeyen"][rng.below(5)];
        let since = [0.0, ledger::day_start_ms(now), ms - 3_600_000.0][rng.below(3)];
        let mult = [1.0, 1.6][rng.below(2)];
        let mut c = case(format!("satir{i}"), vec![
            json!(["scan", "a.jsonl", model, since, mult]),
            json!(["scan", "a.jsonl", "", 0.0, 1.6]),
            json!(["problem", now]),
            json!(["state", now, false]),
            json!(["gate", "s", now]),
        ]);
        c.files = vec![log("a.jsonl", &body, 0o600)];
        let limit = [0.0, 0.5, 1000.0][rng.below(3)];
        v.push(c.settings_json(cap(json!({"daily_cap_usd": limit}))));
    }
    let tree = |extra: Vec<Fx>| {
        let mut files = vec![
            log("bir.jsonl", rec(ms, 400_000).as_bytes(), 0o600),
            log("iki.jsonl", (rec(ms - 600_000.0, 100_000) + &rec(ms - 3_000_000.0, 50_000)).as_bytes(), 0o600),
            log("eski.jsonl", rec(ms - 5.0 * 86400e3, 900_000).as_bytes(), 0o600),
            log("bos.jsonl", b"", 0o600),
            log("not.txt", rec(ms, 1).as_bytes(), 0o600),
            log("other/ic.jsonl", rec(ms, 9_000_000).as_bytes(), 0o600),
            log(".jsonl", rec(ms, 10).as_bytes(), 0o600),
        ];
        files.extend(extra);
        files
    };
    let today = {
        let t = ledger::day_start_ms(now) / 1000.0;
        move |days: i64| day_text(t + days as f64 * 86400.0 + 43200.0)
    };
    let configs = [
        json!({}),
        json!({"daily_cap_usd": 0.5}),
        json!({"daily_cap_usd": "1,5", "cache_ttl": "5m"}),
        json!({"daily_cap_usd": 500, "credit_total_usd": 200}),
        json!({"credit_total_usd": "0.001", "credit_since": today(0), "credit_until": today(9)}),
        json!({"credit_total_usd": 200, "credit_since": today(-30), "credit_until": today(-1)}),
        json!({"credit_total_usd": 200, "credit_until": today(0)}),
        json!({"credit_since": "2026-13-45", "credit_until": "9999-99-99", "credit_total_usd": 5}),
        json!({"credit_since": today(-6)}),
        json!({"daily_cap_usd": "abc"}),
    ];
    for (i, cfg) in configs.iter().enumerate() {
        let mut c = case(format!("agac{i}"), vec![
            json!(["state", now, false]),
            json!(["per", now]),
            json!(["today", now]),
            json!(["rate", now, 60.0]),
            json!(["rate", now, 15.0]),
            json!(["rate", now, 0.0]),
            json!(["rate", now, -1.0]),
            json!(["total", 0.0]),
            json!(["total", ms - 3_600_000.0]),
            json!(["cap", now]),
            json!(["problem", now]),
            // önbellek: 30 sn içinde yeni satır görünmez, sonra görünür
            json!(["state", now, true]),
            json!(["write", "bir.jsonl", rec(ms, 1_000_000)]),
            json!(["state", now + 10.0, true]),
            json!(["state", now + 31.0, true]),
            json!(["invalidate"]),
            json!(["state", now + 32.0, true]),
        ]);
        c.files = tree(vec![]);
        c.args["mtimes"] = json!([[format!("{DIR}/eski.jsonl"), now - 5.0 * 86400.0]]);
        v.push(c.settings_json(cap(cfg.clone())));
    }
    // çok oturum: en çok harcayan 10, eşitlikte ada göre
    let mut many = case("cok".into(), vec![json!(["state", now, false])]);
    many.files = (0..16).map(|i| log(&format!("s{i:02}.jsonl"), rec(ms, 1000 * (i % 5) as u64).as_bytes(), 0o600)).collect();
    v.push(many);
    // rezervasyon dizileri
    let steps = vec![
        json!(["reserve", "a", now]), json!(["reserve", "a", now + 1.0]), json!(["held"]), json!(["reserve", "b", now + 2.0]),
        json!(["reserve", "c", now + 3.0]), json!(["gate", "c", now + 3.0]), json!(["release", "a"]), json!(["release", "a"]),
        json!(["reserve", "c", now + 4.0]), json!(["held"]), json!(["reserve", "d", now + 121.0]),
        json!(["reserve", "e", now + 122.5]), json!(["held"]),
    ];
    for (i, limit) in [0.0, 0.5, 1.0, 2.0, 2.5, 3.0, 100.0].iter().enumerate() {
        v.push(case(format!("pay{i}"), steps.clone()).settings_json(cap(json!({"daily_cap_usd": limit}))));
        let mut c = case(format!("pay-harcamali{i}"), steps.clone());
        c.files = vec![log("x.jsonl", rec(ms, 400_000).as_bytes(), 0o600)];
        v.push(c.settings_json(cap(json!({"daily_cap_usd": limit}))));
    }
    // okunamayan / normal olmayan günlük: açık tavan reddeder, kapalı tavan geçirir
    let broken: [(&str, Vec<Fx>); 6] = [
        ("izinsiz", vec![log("a.jsonl", rec(ms, 1).as_bytes(), 0o000)]),
        ("dizin-adli", vec![Fx::Dir(format!("{DIR}/d.jsonl"), 0o700)]),
        ("dizin-dosya", vec![file(DIR, "x", 0o600)]),
        ("dizin-izinsiz", vec![Fx::Dir(DIR.into(), 0o300)]),
        ("kopuk-bag", vec![Fx::Link(format!("{DIR}/k.jsonl"), "yok".into())]),
        ("bag-dongu", vec![Fx::Link(format!("{DIR}/l.jsonl"), "l.jsonl".into())]),
    ];
    for (id, files) in broken {
        for (suffix, limit) in [("acik", 5.0), ("kapali", 0.0)] {
            let mut c = case(format!("{id}-{suffix}"), vec![
                json!(["problem", now]), json!(["state", now, false]), json!(["per", now]), json!(["total", 0.0]),
                json!(["gate", "s", now]), json!(["held"]),
            ]);
            c.files = files.clone();
            v.push(c.settings_json(cap(json!({"daily_cap_usd": limit}))));
        }
    }
    // yerel gün ve tarih
    let days = ["2026-11-22", "2026-02-31", "2026-13-01", "2026-00-00", "0001-01-01", "9999-12-31", " 2026- 1 -1 ", "2026-11",
        "a-b-c", "", "2026-11-22-1", "٢٠٢٦-١١-٢٢", "2_026-1_1-2"];
    let dated: Vec<Value> = days.iter().flat_map(|d| [json!([d, false]), json!([d, true])]).collect();
    v.push(case("gun".into(), vec![json!(["days", now, dated]), json!(["days", 0.0, []]), json!(["days", 1_790_000_000.9, []])]));
    // kredi dönemi (saf)
    let mut steps = Vec::new();
    for total in [0.0, 10.0, 162.0] {
        for until in ["", "2026-12-01", "2026-11-22", "2026-11-01", "bozuk", "2026-13-45"] {
            for spent in [0.0, 12.0, 500.0] {
                let cfg = json!({"credit_total_usd": total, "credit_until": until, "credit_since": "2026-11-22"});
                steps.push(json!(["window", cfg, spent, 1_795_341_600.0]));
            }
        }
    }
    v.push(case("kredi".into(), steps));
    v
}

fn day_text(secs: f64) -> String {
    // yerel gün metni: `day_start_ms` ile aynı saat dilimi
    let t = secs as libc::time_t;
    // SAFETY: sıfır geçerli başlangıç; işaretçiler bu çağrıya özel.
    let mut tm: libc::tm = unsafe { std::mem::zeroed() };
    // SAFETY: bkz. üst satır.
    unsafe { libc::localtime_r(&t, &mut tm) };
    format!("{:04}-{:02}-{:02}", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday)
}

fn pairs(mut v: Vec<(String, f64)>) -> Value {
    v.sort_by(|a, b| a.0.cmp(&b.0));
    json!(v.iter().map(|(k, x)| json!([k, float_repr(*x)])).collect::<Vec<_>>())
}

fn repr(f: f64) -> Value {
    json!(float_repr(f))
}

fn rs_ledger(e: &Env, c: &Case) -> RsOut {
    let a = &c.args;
    let base = e.paths().ucli_usage_dir();
    for m in a.get("mtimes").and_then(Value::as_array).into_iter().flatten() {
        let at = UNIX_EPOCH + Duration::from_secs_f64(m[1].as_f64().unwrap());
        let f = fs::OpenOptions::new().write(true).open(format!("{}/{}", e.root, m[0].as_str().unwrap())).unwrap();
        f.set_modified(at).unwrap();
    }
    let settings = file_cost_settings(format!("{}/settings.json", e.state));
    let book = CostLedger::new(base.clone(), settings.clone());
    let out: Vec<Value> = a["steps"]
        .as_array()
        .unwrap()
        .iter()
        .map(|s| {
            let op = s[0].as_str().unwrap();
            let num = |i: usize| s[i].as_f64().unwrap();
            let text = |i: usize| s[i].as_str().unwrap();
            let mult = write_mult(&settings().unwrap());
            let gated = |r: Result<(), cost::CostRefusal>| match r {
                Ok(()) => json!(["ok", null]),
                Err(x) => json!(["err", refusal(&x.to_string(), Some(&x))]),
            };
            let ok = |v: Value| json!(["ok", v]);
            match op {
                "state" => ok(book.state(num(1), s[2].as_bool().unwrap())),
                "per" => ok(pairs(ledger::per_session_usd(num(1), &base, mult))),
                "today" => ok(repr(ledger::today_usd(num(1), &base, mult))),
                "rate" => ok(json!([
                    pairs(ledger::rate_by_session(num(1), num(2), &base, mult)),
                    repr(ledger::rate_usd_per_hour(num(1), num(2), &base, mult))
                ])),
                "total" => ok(repr(ledger::total_usd(&base, mult, num(1)))),
                "scan" => {
                    let r = ledger::scan_usage(format!("{base}/{}", text(1)), text(2), num(3), num(4));
                    ok(json!([float_repr(r.total), r.problem.unwrap_or("")]))
                }
                "problem" => ok(json!(ledger::ledger_problem(num(1), &base, mult).unwrap_or_default())),
                "gate" => gated(book.check_and_reserve_at(text(1), num(2))),
                "cap" => ok(json!(book.cap_exceeded(num(1)).unwrap())),
                "reserve" => gated(book.reserve(text(1), num(2))),
                "release" => {
                    book.release(text(1));
                    ok(Value::Null)
                }
                "held" => ok(json!(book.reserved_sessions())),
                "invalidate" => {
                    book.invalidate();
                    ok(Value::Null)
                }
                "write" => {
                    use std::io::Write;
                    let mut f = fs::OpenOptions::new().append(true).create(true).open(format!("{base}/{}", text(1))).unwrap();
                    f.write_all(text(2).as_bytes()).unwrap();
                    ok(Value::Null)
                }
                "days" => ok(json!([
                    float_repr(ledger::day_start_ms(num(1))),
                    s[2].as_array()
                        .unwrap()
                        .iter()
                        .map(|d| float_repr(ledger::date_ms(d[0].as_str().unwrap(), d[1].as_bool().unwrap())))
                        .collect::<Vec<_>>()
                ])),
                "window" => {
                    let field = |k: &str| s[1][k].as_str().unwrap_or("").to_string();
                    let cfg = UcliCostConfig {
                        daily_cap_usd: 0.0,
                        cache_ttl: "1h",
                        credit_total_usd: s[1]["credit_total_usd"].as_f64().unwrap(),
                        credit_since: field("credit_since"),
                        credit_until: field("credit_until"),
                    };
                    ok(Value::Object(cost::credit_window(&cfg, num(2), num(3), &|d| ledger::date_ms(d, true))))
                }
                other => panic!("bilinmeyen adım {other}"),
            }
        })
        .collect();
    RsOut::ret(Value::from(out))
}

pub fn run() {
    let mut r = Runner::new();
    let all = cases();
    r.run(all, &[], rs_ledger);
    r.finish("ledger");
}
