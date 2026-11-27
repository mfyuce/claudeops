//! Aile: model kaynakları (G7). Her vaka bir ADIM DİZİSİ: iki taraf aynı sahte saat, süreç/HTTP yanıtı, belge ve ayarla
//! çalışır; adım başına dönüş, yapılan istekler (argv/URL/başlık/zaman aşımı) ve arka plan başlatmaları karşılaştırılır.
//! `expect`: bilinen ayrışmalarda Rust'ın adım dönüşleri ayrıca doğrulanır.

use crate::common::*;
use cops_providers::{Cli, HttpRequest, ModelIo, ModelSources, Providers, RunRequest, Settings};
use serde_json::{json, Value};
use std::sync::{Arc, Mutex};

#[derive(Default)]
struct State {
    t: f64,
    resp: Value,
    calls: Vec<Value>,
    pending: Vec<Box<dyn FnOnce() + Send>>,
    diags: Vec<cops_providers::Diag>,
}

#[derive(Default)]
struct StepIo(Mutex<State>);

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}

fn hex(b: impl AsRef<[u8]>) -> String {
    b.as_ref().iter().map(|x| format!("{x:02x}")).collect()
}

impl StepIo {
    fn payload(&self) -> Option<Vec<u8>> {
        let s = self.0.lock().unwrap();
        if let Some(r) = s.resp.get("rep") {
            return Some(unhex(r[0].as_str().unwrap()).repeat(r[1].as_u64().unwrap() as usize));
        }
        s.resp.get("hex").and_then(Value::as_str).map(unhex)
    }
}

impl ModelIo for StepIo {
    fn monotonic_secs(&self) -> f64 {
        self.0.lock().unwrap().t
    }
    fn wall_secs(&self) -> f64 {
        self.0.lock().unwrap().t
    }
    fn claude_models_doc(&self) -> Option<Value> {
        None
    }
    fn read_file(&self, path: &str, max: u64) -> Option<Vec<u8>> {
        std::fs::read(path).ok().filter(|d| d.len() as u64 <= max)
    }
    fn run_stdout(&self, req: &RunRequest) -> Option<Vec<u8>> {
        self.0.lock().unwrap().calls.push(json!([
            "run",
            req.argv,
            req.timeout.as_secs_f64() as u64
        ]));
        self.payload()
    }
    fn http_get(&self, req: &HttpRequest) -> Option<Vec<u8>> {
        let mut headers: Vec<(String, String)> = req
            .headers
            .iter()
            .map(|(k, v)| {
                (
                    k.to_lowercase(),
                    v.expose().iter().map(|b| *b as char).collect(),
                )
            })
            .collect();
        headers.sort();
        self.0.lock().unwrap().calls.push(json!([
            "get",
            req.url,
            headers,
            req.timeout.as_secs_f64()
        ]));
        self.payload()
    }
    fn diag(&self, diag: &cops_providers::Diag) {
        self.0.lock().unwrap().diags.push(diag.clone());
    }
    fn spawn_background(&self, name: &'static str, job: Box<dyn FnOnce() + Send + 'static>) {
        let mut s = self.0.lock().unwrap();
        s.calls.push(json!(["bg", name]));
        s.pending.push(job);
    }
}

fn rs_sources(e: &Env, c: &Case) -> RsOut {
    let io = Arc::new(StepIo::default());
    let sources = ModelSources::new(io.clone());
    let paths = e.paths();
    let probe = FsProbe::new(e, c);
    let mut settings = e.settings();
    let source = c.args["source"].as_str().unwrap();
    let mut out = Vec::new();
    for step in c.args["steps"].as_array().unwrap() {
        {
            let mut s = io.0.lock().unwrap();
            s.t = step["t"].as_f64().unwrap();
            s.resp = step.get("resp").cloned().unwrap_or(Value::Null);
            s.calls.clear();
        }
        if let Some(text) = step.get("settings").and_then(Value::as_str) {
            std::fs::write(format!("{}/settings.json", e.state), text).unwrap();
            settings = Settings::from_json(text);
        }
        if let Some(f) = step.get("file") {
            let path = paths.codex_models_cache();
            match f.as_str() {
                None => {
                    let _ = std::fs::remove_file(&path);
                }
                Some(h) => {
                    std::fs::create_dir_all(paths.codex_home()).unwrap();
                    std::fs::write(&path, unhex(h)).unwrap();
                }
            }
        }
        let choices = |cli: Cli| {
            let catalog = sources.catalog(cli, &settings, &paths, &probe);
            let p = Providers {
                settings: &settings,
                catalog: &catalog,
                paths: &paths,
                probe: &probe,
            };
            (
                p.model_choices(cli),
                Value::Object(catalog.ucli.caps.clone()),
            )
        };
        let mut row = match source {
            "agy" => json!({"ret": choices(Cli::Agy).0, "exc": null}),
            "codex" => json!({"ret": choices(Cli::Codex).0, "exc": null}),
            "ucli" => {
                let (ret, caps) = choices(Cli::Ucli);
                json!({"ret": ret, "exc": null, "caps": caps})
            }
            _ => {
                json!({"ret": sources.service_models(&settings, step["service"].as_str().unwrap(), step["key"].as_str().unwrap()),
                        "exc": null})
            }
        };
        if step.get("run_bg").and_then(Value::as_bool) == Some(true) {
            // iş, kilit bırakıldıktan sonra koşar (kendisi de `StepIo`yu kullanır)
            let jobs = std::mem::take(&mut io.0.lock().unwrap().pending);
            jobs.into_iter().for_each(|j| j());
        }
        row["calls"] = Value::from(io.0.lock().unwrap().calls.clone());
        out.push(row);
    }
    if let Some(expect) = c.args.get("expect") {
        let got: Vec<Value> = out.iter().map(|r| r["ret"].clone()).collect();
        assert_eq!(&Value::from(got), expect, "vaka {}", c.id);
    }
    let diags = std::mem::take(&mut io.0.lock().unwrap().diags);
    RsOut {
        extra_diags: diags,
        ..RsOut::ret(Value::from(out))
    }
}

fn seq(id: impl Into<String>, source: &str, steps: Vec<Value>) -> Case {
    Case::new(id, "sources", json!({"source": source, "steps": steps}))
}

fn diverges(id: &str, source: &str, steps: Vec<Value>, expect: Value, why: &'static str) -> Case {
    Case::new(
        id,
        "sources",
        json!({"source": source, "steps": steps, "expect": expect}),
    )
    .known(why)
}

/// 27 Kas'ta iki tarafta düzelen eski ayrışma: Python ile eşit olmalı VE Rust adım dönüşleri `expect`.
fn fixed(id: &str, source: &str, steps: Vec<Value>, expect: Value) -> Case {
    Case::new(
        id,
        "sources",
        json!({"source": source, "steps": steps, "expect": expect}),
    )
}

fn ok(b: impl AsRef<[u8]>) -> Value {
    json!({"hex": hex(b)})
}

fn fail(kind: &str) -> Value {
    json!({"raise": kind})
}

/// Belirlenimci sözde rastgele (xorshift64*).
struct Rng(u64);

impl Rng {
    fn n(&mut self, n: u64) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_f491_4f6c_dd1d) % n
    }
    fn pick<'a>(&mut self, l: &[&'a str]) -> &'a str {
        l[self.n(l.len() as u64) as usize]
    }
    /// Önbellek sınırlarına yakın artışlarla ilerleyen saat.
    fn advance(&mut self, t: f64) -> f64 {
        t + [
            0.0, 1.0, 59.0, 60.0, 61.0, 299.5, 300.0, 300.5, 1000.0, 86399.0, 86400.0, 90000.0,
        ][self.n(12) as usize]
    }
    fn mutate(&mut self, mut b: Vec<u8>) -> Vec<u8> {
        if !b.is_empty() && self.n(5) == 0 {
            b.truncate(self.n(b.len() as u64) as usize);
        }
        if !b.is_empty() && self.n(8) == 0 {
            let i = self.n(b.len() as u64) as usize;
            let c = b"{}[]\",:0a ";
            b[i] = c[self.n(c.len() as u64) as usize];
        }
        b
    }
}

fn agy_cases() -> Vec<Case> {
    let out = |ids: &[&str]| {
        ok(format!(
            "Fetching available models...\n{}",
            ids.iter()
                .map(|i| format!("{i}\tAd {i}\n"))
                .collect::<String>()
        ))
    };
    let s = |t: f64, resp: Value| json!({"t": t, "resp": resp});
    let bg = |t: f64, resp: Value| json!({"t": t, "resp": resp, "run_bg": true});
    let mut v = vec![
        // açılıştan sonraki ilk 300 sn: soğuk önbellek hiç çekilmez (Python `_cache_ts = 0.0`)
        seq("src-agy-acilis", "agy", vec![s(0.0, out(&["a"])), s(299.0, out(&["a"])), s(300.0, out(&["a"])), s(300.5, out(&["a"]))]),
        seq("src-agy-akis", "agy", vec![
            s(1000.0, fail("os")), s(1001.0, out(&["a"])), s(1300.0, out(&["a"])), s(1300.5, out(&["a", "b"])),
            s(1600.5, out(&["c"])), s(1601.0, out(&["c"])), s(1602.0, out(&["c"])), bg(1901.5, out(&["d"])),
            s(1902.0, out(&["e"])), bg(2300.0, fail("timeout")), s(2301.0, out(&["f"])),
            bg(2700.0, ok("Fetching...\nsign in required\n")), s(2701.0, fail("os")), bg(3100.0, ok(b"\xff\tx\n")),
            s(3101.0, fail("os")), bg(3500.0, ok("")), s(3501.0, fail("os")),
        ]),
        seq("src-agy-soguk-hata", "agy", vec![
            s(400.0, fail("timeout")), s(500.0, out(&["a"])), s(701.0, ok(b"\xff\tx\n")), s(1002.0, ok("yalnız metin")),
            s(1303.0, out(&["a"])),
        ]),
        seq("src-agy-bicim", "agy", vec![
            s(400.0, ok("x\r\n a \tEtiket\r\n\tbos-kimlik\r\nb\tc\td\rğ\t\u{2028}z\ty\n\u{1c}k\u{1f}\tS\n")),
            s(401.0, fail("os")),
        ]),
        seq("src-agy-cikis-kodu", "agy", vec![s(400.0, json!({"hex": hex("m\tM\n"), "rc": 1}))]),
        seq("src-agy-saat-geri", "agy", vec![s(1000.0, out(&["a"])), s(10.0, out(&["b"])), s(1300.5, out(&["b"]))]),
    ];
    let mut r = Rng(0x00a6_7100_0001);
    for i in 0..150 {
        let mut t = 200.0;
        let steps = (0..12)
            .map(|_| {
                t = r.advance(t);
                let resp = match r.n(6) {
                    0 => fail(r.pick(&["os", "timeout"])),
                    _ => {
                        let text: String = (0..r.n(5))
                            .map(|_| {
                                let id =
                                    r.pick(&["a", "gemini-x-high", " b ", "", "ğ", "Fetching..."]);
                                let sep = r.pick(&["\t", "\t", " ", ""]);
                                let end = r.pick(&["\n", "\r\n", "\r", "", "\u{b}", "\u{85}"]);
                                format!("{id}{sep}L{end}")
                            })
                            .collect();
                        ok(r.mutate(text.into_bytes()))
                    }
                };
                json!({"t": t, "resp": resp, "run_bg": r.n(3) > 0})
            })
            .collect();
        v.push(seq(format!("src-agy-rastgele-{i}"), "agy", steps));
    }
    v
}

fn codex_doc(slugs: &[(&str, i64)]) -> String {
    let models: Vec<Value> = slugs
        .iter()
        .map(|(s, p)| json!({"slug": s, "visibility": "list", "priority": p}))
        .collect();
    json!({"models": models}).to_string()
}

fn codex_cases() -> Vec<Case> {
    let s = |t: f64, file: Option<String>| json!({"t": t, "file": file.map(hex)});
    let doc = |l: &[(&str, i64)]| Some(codex_doc(l));
    let mut v = vec![
        seq("src-codex-acilis", "codex", vec![s(5.0, doc(&[("a", 1)])), s(300.0, doc(&[("a", 1)])), s(300.5, doc(&[("a", 1)]))]),
        seq("src-codex-akis", "codex", vec![
            s(400.0, None), s(500.0, doc(&[("a", 1)])), s(700.0, doc(&[("a", 1)])), s(700.5, doc(&[("b", 2), ("a", 1)])),
            s(800.0, doc(&[("c", 1)])), s(1001.0, None), s(1302.0, Some("{bozuk".into())), s(1603.0, Some("[1]".into())),
            s(1904.0, Some("{\"models\": 5}".into())), s(2205.0, Some("{\"models\": []}".into())),
            s(2506.0, Some("{\"models\": [1]}".into())), s(2807.0, Some(String::new())),
            s(3108.0, Some(format!("\u{feff}{}", codex_doc(&[("z", 1)])))), s(3409.0, doc(&[("d", 1)])),
        ]),
        seq("src-codex-nan", "codex", vec![s(
            400.0,
            Some("{\"x\": NaN, \"y\": 123456789012345678901234567890, \"models\": [{\"slug\": \"n\", \"visibility\": \"list\"}]}".into()),
        )]),
        seq("src-codex-karisik-oncelik", "codex", vec![
            s(400.0, doc(&[("a", 1)])),
            s(800.0, Some("{\"models\": [{\"slug\": \"b\", \"visibility\": \"list\", \"priority\": \"1\"}, {\"slug\": \"c\", \"visibility\": \"list\", \"priority\": 2}]}".into())),
        ]),
        fixed(
            "src-codex-sapma-utf8", "codex",
            vec![s(400.0, doc(&[("a", 1)])), json!({"t": 800.0, "file": hex(b"{\"models\": \xff}")})],
            json!([["a"], ["a"]]),
        ),
    ];
    let mut r = Rng(0x00c0_de00_0002);
    for i in 0..150 {
        let mut t = 200.0;
        let steps = (0..10)
            .map(|_| {
                t = r.advance(t);
                let file = (r.n(6) > 0).then(|| {
                    let models: Vec<Value> = (0..r.n(4))
                        .map(|_| {
                            let mut m = serde_json::Map::new();
                            if r.n(8) > 0 {
                                m.insert(
                                    "slug".into(),
                                    json!(r.pick(&["a", "b", "gpt-5.5", "", "ğ"])),
                                );
                            }
                            if r.n(6) > 0 {
                                m.insert(
                                    "visibility".into(),
                                    json!(r.pick(&["list", "list", "hide"])),
                                );
                            }
                            if r.n(2) == 0 {
                                m.insert("priority".into(), json!(r.n(4)));
                            }
                            Value::Object(m)
                        })
                        .collect();
                    // yalnız ASCII dışı baytı bozmayan kesme: UTF-8 bozulması ayrı (bilinen) vaka
                    let text = json!({"models": models}).to_string().replace('ğ', "g");
                    hex(r.mutate(text.into_bytes()))
                });
                json!({"t": t, "file": file})
            })
            .collect();
        v.push(seq(format!("src-codex-rastgele-{i}"), "codex", steps));
    }
    v
}

fn chat_payload(ids: &[&str]) -> String {
    let data: Vec<Value> = ids
        .iter()
        .map(|i| json!({"id": i, "task": "chat", "capabilities": {"reasoning_effort": true, "n": 1}}))
        .collect();
    json!({"data": data}).to_string()
}

fn key_settings(key: &str, endpoint: &str) -> String {
    json!({"byok": {"ucli": {"UCLI_API_KEY": key}}, "ucli_endpoint": endpoint}).to_string()
}

fn ucli_cases() -> Vec<Case> {
    let s = |t: f64, resp: Value| json!({"t": t, "resp": resp});
    let set =
        |t: f64, settings: String, resp: Value| json!({"t": t, "settings": settings, "resp": resp});
    let k = || key_settings("anahtar", "");
    let good = |ids: &[&str]| ok(chat_payload(ids));
    let mut v = vec![
        seq("src-ucli-anahtarsiz", "ucli", vec![
            s(1.0, good(&["a"])), set(2.0, key_settings("  ", ""), good(&["a"])), set(100.0, k(), good(&["a"])),
            s(302.5, good(&["a"])), set(700.0, "{}".into(), good(&["b"])), s(1100.0, good(&["b"])),
        ]),
        seq("src-ucli-akis", "ucli", vec![
            set(0.5, k(), fail("os")), s(100.0, good(&["a"])), s(300.5, good(&["a"])), s(301.0, good(&["a", "b"])),
            s(601.0, good(&["c"])), s(601.5, fail("http")), s(902.0, fail("timeout")), s(1203.0, ok("{\"data\": []}")),
            s(1504.0, ok("{bozuk")), s(1805.0, ok("[]")), s(2106.0, ok("{\"data\": {}}")), s(2407.0, ok("{}")),
            s(2708.0, ok("{\"data\": [{\"id\": \"e\", \"task\": \"embedding\"}, 5, {\"task\": \"chat\"}, {\"id\": \"\", \"task\": \"chat\"}]}")),
            s(3009.0, ok(b"{\"data\": \"\xff\"}")), s(3310.0, good(&["d"])),
        ]),
        seq("src-ucli-yetenek", "ucli", vec![
            set(1.0, k(), good(&["a", "b"])),
            s(400.0, ok("{\"data\": [{\"id\": \"c\", \"task\": \"chat\"}, {\"id\": \"d\", \"task\": \"chat\", \"capabilities\": [1]}, {\"id\": \"c\", \"task\": \"chat\", \"capabilities\": {\"x\": 1}}]}")),
            s(800.0, ok("\u{feff}{\"data\": [{\"id\": \"bom\", \"task\": \"chat\"}]}")),
            s(1200.0, ok("{\"y\": NaN, \"data\": [{\"id\": \"nan\", \"task\": \"chat\", \"capabilities\": {\"z\": 12.5}}]}")),
        ]),
        seq("src-ucli-uc-nokta", "ucli", vec![
            set(1.0, key_settings(" k2 \n", "http://localhost:8000/v1/"), good(&["a"])),
            set(400.0, key_settings("k3", "ftp://x/v1"), good(&["a"])),
            set(800.0, key_settings("k4", "https://u:p@example.invalid/v1//"), good(&["a"])),
            set(1200.0, json!({"byok": {"ucli": {"UCLI_API_KEY": 12345}}}).to_string(), good(&["a"])),
            set(1600.0, json!({"byok": {"ucli": "x"}}).to_string(), good(&["a"])),
        ]),
        // 27 Kas: metin olmayan kimlik iki tarafta atlanır, çok derin gövde iki tarafta başarısız çekim (yedek liste)
        fixed(
            "src-ucli-sapma-sayi-id", "ucli",
            vec![set(1.0, k(), ok("{\"data\": [{\"id\": 5, \"task\": \"chat\"}]}"))],
            json!([["deepseek-v4-flash"]]),
        ),
        fixed(
            "src-ucli-sapma-liste-id", "ucli",
            vec![set(1.0, k(), ok("{\"data\": [{\"id\": [1], \"task\": \"chat\", \"capabilities\": {}}]}"))],
            json!([["deepseek-v4-flash"]]),
        ),
        fixed(
            "src-ucli-sapma-derin", "ucli",
            vec![set(1.0, k(), json!({"rep": [hex("["), 100000]}))],
            json!([["deepseek-v4-flash"]]),
        ),
        diverges(
            "src-ucli-sapma-utf16", "ucli",
            vec![set(1.0, k(), ok(chat_payload(&["u"]).encode_utf16().flat_map(u16::to_le_bytes).collect::<Vec<_>>()))],
            json!([["deepseek-v4-flash"]]),
            "ucli /models UTF-16 gövde: Python json.loads(bytes) kabul eder, Rust yalnız UTF-8",
        ),
    ];
    let mut r = Rng(0x0001_c110_0003);
    for i in 0..150 {
        let mut t = 0.0;
        let steps = (0..10)
            .map(|n| {
                t = r.advance(t);
                let resp = match r.n(6) {
                    0 => fail(r.pick(&["os", "http", "timeout"])),
                    _ => {
                        let data: Vec<Value> = (0..r.n(4))
                            .map(|_| {
                                let mut m = serde_json::Map::new();
                                if r.n(8) > 0 {
                                    m.insert(
                                        "id".into(),
                                        [
                                            json!("a"),
                                            json!("b"),
                                            json!(""),
                                            json!(null),
                                            json!("ğ"),
                                        ][r.n(5) as usize]
                                            .clone(),
                                    );
                                }
                                if r.n(6) > 0 {
                                    m.insert(
                                        "task".into(),
                                        json!(r.pick(&["chat", "chat", "ocr"])),
                                    );
                                }
                                if r.n(2) == 0 {
                                    m.insert(
                                        "capabilities".into(),
                                        [
                                            json!({"reasoning_effort": true}),
                                            json!({}),
                                            json!(null),
                                            json!("x"),
                                        ][r.n(4) as usize]
                                            .clone(),
                                    );
                                }
                                Value::Object(m)
                            })
                            .collect();
                        ok(r.mutate(json!({"data": data}).to_string().into_bytes()))
                    }
                };
                let mut step = json!({"t": t, "resp": resp});
                if n == 0 || r.n(5) == 0 {
                    let key = r.pick(&["", "k", " k ", "k"]);
                    let ep = r.pick(&["", "http://a.invalid/v1", "http://b.invalid/v1/", "bozuk"]);
                    step["settings"] = json!(key_settings(key, ep));
                }
                step
            })
            .collect();
        v.push(seq(format!("src-ucli-rastgele-{i}"), "ucli", steps));
    }
    v
}

fn service_cases() -> Vec<Case> {
    let s = |t: f64, service: &str, key: &str, resp: Value| json!({"t": t, "service": service, "key": key, "resp": resp});
    let one = |id: &str| ok(json!({"data": [{"id": id}]}).to_string());
    let mut v = vec![
        seq(
            "src-svc-istek-yok",
            "service",
            vec![
                s(0.0, "evren", "K", one("a")),
                s(0.0, "grok", "", one("a")),
                s(0.0, "yok", "K", one("a")),
                s(0.0, "", "K", one("a")),
                s(0.0, "Grok", "K", one("a")),
            ],
        ),
        seq(
            "src-svc-ttl",
            "service",
            vec![
                s(1000.0, "grok", "K", one("m1")),
                s(81000.0, "grok", "K", one("m2")),
                s(87399.5, "grok", "K", one("m2")),
                s(87400.0, "grok", "K", one("m3")),
                s(87401.0, "grok", "BASKA", one("m4")),
                // süre dolunca başarısızlık iyi listeyi EZER; 60 sn sonra yeniden denenir
                s(200000.0, "grok", "K", fail("os")),
                s(200030.0, "grok", "K", one("m5")),
                s(200059.5, "grok", "K", one("m5")),
                s(200060.0, "grok", "K", one("m5")),
            ],
        ),
        seq(
            "src-svc-bos-sonuc",
            "service",
            vec![
                s(0.0, "groq", "K", ok("{\"data\": []}")),
                s(59.0, "groq", "K", one("a")),
                s(60.0, "groq", "K", one("a")),
            ],
        ),
        seq(
            "src-svc-ayri",
            "service",
            vec![
                s(0.0, "grok", "K", one("g")),
                s(0.0, "groq", "K", one("q")),
                s(1.0, "grok", "K", one("x")),
                s(1.0, "claude", "KEY", one("c")),
                s(1.0, "openrouter", "K o", one("o")),
            ],
        ),
        seq(
            "src-svc-saat-geri",
            "service",
            vec![
                s(1000.0, "grok", "K", one("a")),
                s(1.0, "grok", "K", one("b")),
            ],
        ),
        seq(
            "src-svc-ozel",
            "service",
            vec![
                json!({"t": 0.0, "service": "benim", "key": "K", "resp": one("a"),
                   "settings": json!({"ucli_services": [{"id": "benim", "env": "BENIM_KEY", "endpoint": "http://h.invalid/api/v9///"},
                                                        {"id": "ant", "env": "ANT_KEY", "wire": "anthropic-messages", "endpoint": "http://a.invalid"}]}).to_string()}),
                s(1.0, "ant", "K", one("b")),
                s(2.0, "grok", "K", one("c")),
                s(3.0, "evren", "K", one("d")),
            ],
        ),
    ];
    let bodies: &[&str] = &[
        "{\"data\": [{\"id\": \"b\"}, {\"id\": \"a\"}, {\"id\": \"a\"}]}",
        "[{\"id\": \"b\"}, {\"id\": \"a\"}]",
        "{\"data\": null}",
        "{\"data\": 0}",
        "{\"data\": 5}",
        "{\"data\": true}",
        "{\"data\": \"abc\"}",
        "{\"data\": {\"id\": \"x\"}}",
        "{}",
        "5",
        "\"abc\"",
        "null",
        "",
        "{bozuk",
        "\u{feff}{\"data\": [{\"id\": \"bom\"}]}",
        "{\"data\": [{\"id\": 5}, {\"id\": 0}, {\"id\": 1.5}, {\"id\": 0.0}, {\"id\": true}, {\"id\": false}, {\"id\": null}, {\"id\": \"\"}, {}, 7, \"s\", [1]]}",
        "{\"data\": [{\"id\": [1, \"a'b\", null]}, {\"id\": {\"k\": 1.0}}, {\"id\": []}, {\"id\": {}}]}",
        "{\"data\": [{\"id\": NaN}, {\"id\": -Infinity}, {\"id\": 123456789012345678901234567890}, {\"id\": 1e400}]}",
        "{\"data\": [{\"id\": \"Z\"}, {\"id\": \"a\"}, {\"id\": \"ğ\"}, {\"id\": \"\\ud83d\\ude00\"}, {\"id\": \"\u{ff00}\"}, {\"id\": \"A\"}]}",
        "{\"data\": [{\"id\": \"ilk\", \"id\": \"son\"}], \"data\": [{\"id\": \"kazanan\"}]}",
    ];
    for (i, b) in bodies.iter().enumerate() {
        v.push(seq(
            format!("src-svc-govde-{i}"),
            "service",
            vec![s(0.0, "grok", "K", ok(b)), s(61.0, "grok", "K", ok(b))],
        ));
    }
    v.push(seq(
        "src-svc-govde-utf8",
        "service",
        vec![s(
            0.0,
            "grok",
            "K",
            ok(b"{\"data\": [{\"id\": \"a\xff\xc3b\xf0\x9f\"}]}"),
        )],
    ));
    v.push(seq(
        "src-svc-govde-hata",
        "service",
        vec![
            s(0.0, "grok", "K", fail("http")),
            s(61.0, "grok", "K", fail("timeout")),
        ],
    ));
    v.push(seq(
        "src-svc-cok-derin",
        "service",
        vec![s(0.0, "grok", "K", json!({"rep": [hex("["), 100000]}))],
    ));
    v.push(diverges(
        "src-svc-sapma-vekil",
        "service",
        vec![s(
            0.0,
            "grok",
            "K",
            ok("{\"data\": [{\"id\": \"a\\ud800\"}]}"),
        )],
        json!([["a\u{fffd}"]]),
        "hizmet /models eşlenmemiş vekil: Python vekili taşır, Rust U+FFFD",
    ));
    v.push(diverges(
        "src-svc-sapma-derinlik",
        "service",
        vec![s(
            0.0,
            "grok",
            "K",
            ok(format!(
                "{{\"data\": [{{\"id\": \"a\"}}], \"x\": {}{}}}",
                "[".repeat(600),
                "]".repeat(600)
            )),
        )],
        json!([[]]),
        "hizmet /models 512'den derin gövde: Python okur, Rust boş liste",
    ));
    let mut r = Rng(0x005e_71ce_0004);
    for i in 0..200 {
        let mut t = 0.0;
        let steps = (0..10)
            .map(|_| {
                t = r.advance(t);
                let resp = match r.n(5) {
                    0 => fail(r.pick(&["os", "http", "timeout"])),
                    _ => {
                        let rows: Vec<Value> = (0..r.n(5))
                            .map(|_| match r.n(8) {
                                0 => json!(null),
                                1 => json!({"id": r.n(3)}),
                                2 => json!({"ad": "x"}),
                                _ => json!({"id": r.pick(&["a", "B", "ç", "", "a-1", "a_1"])}),
                            })
                            .collect();
                        let body = if r.n(4) == 0 {
                            json!(rows)
                        } else {
                            json!({"data": rows})
                        };
                        ok(r.mutate(body.to_string().into_bytes()))
                    }
                };
                s(
                    t,
                    r.pick(&["grok", "grok", "claude", "evren", "yok"]),
                    r.pick(&["K", "K", ""]),
                    resp,
                )
            })
            .collect();
        v.push(seq(format!("src-svc-rastgele-{i}"), "service", steps));
    }
    v
}

pub fn run() {
    let mut r = Runner::new();
    for cases in [agy_cases(), codex_cases(), ucli_cases(), service_cases()] {
        r.run(cases, &[], rs_sources);
    }
    r.finish("model kaynakları");
}
