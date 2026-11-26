//! Aile (G6): sağlayıcı canlı okuyucuları (`busy_status_pattern`, `background_work`, `live_*`) ve ucli sohbet dizini /
//! durum dosyası / hata kaydı okuyucuları. Senaryolar `py/tests/test_{bg_work,provider_live_context,ucli_*}.py` +
//! boş/bozuk/Unicode/yanlış tip/kısmi dosya sınırları. Tüm dosyalar geçici HOME altında.

use crate::common::*;
use crate::fam_bg::{pending_use, screens, sub_agent, Rng, T};
use cops_providers::bg_work::Clock;
use cops_providers::ucli::state_dir_for;
use cops_providers::ucli_status::{PHASE_INT_FIELDS, STATUS_MAX_BYTES, USAGE_FIELDS};
use cops_providers::{Cli, FileStat, Live, LiveProbe, SqlCell};
use rusqlite::types::Value as Sql;
use serde_json::{json, Map, Value};
use std::fs;

/// Dosya/dizin/SQLite GERÇEK uygulayıcıdan ([`cops_providers::real::RealProbe`]); `/proc` ve süreç dizini vakanın sahte
/// olguları.
impl LiveProbe for FsProbe<'_> {
    fn read_bytes(&self, path: &str, max: u64) -> Option<Vec<u8>> {
        self.real.read_bytes(path, max)
    }
    fn read_tail(&self, path: &str, max: u64) -> Option<Vec<u8>> {
        self.real.read_tail(path, max)
    }
    fn read_range(&self, path: &str, start: u64, len: u64) -> Option<Vec<u8>> {
        self.real.read_range(path, start, len)
    }
    fn list_dir(&self, path: &str) -> Option<Vec<String>> {
        self.real.list_dir(path)
    }
    fn stat(&self, path: &str) -> Option<FileStat> {
        self.real.stat(path)
    }
    fn proc_stat(&self, pid: i64) -> Option<Vec<u8>> {
        self.case.fact("proc_stat")?.get(pid.to_string())?.as_str().map(|s| s.as_bytes().to_vec())
    }
    fn current_dir(&self) -> String {
        self.e.root.clone()
    }
    fn agy_sids_doc(&self) -> Option<cops_providers::pyjson::Py> {
        self.real.agy_sids_doc()
    }
    fn sqlite_rows(&self, db: &str, sql: &str, params: &[SqlCell], row: &mut dyn FnMut(Vec<SqlCell>) -> bool) -> bool {
        self.real.sqlite_rows(db, sql, params, row)
    }
    fn claude_project_dir(&self, cwd: &str) -> String {
        self.real.claude_project_dir(cwd)
    }
    fn sqlite_cell(&self, db: &str, sql: &str, param: &str) -> Option<SqlCell> {
        self.real.sqlite_cell(db, sql, param)
    }
}

fn opt<T: Into<Value>>(v: Option<T>) -> Value {
    v.map_or(Value::Null, Into::into)
}

fn rs_live(e: &Env, c: &Case) -> RsOut {
    let cli = Cli::parse(c.args["cli"].as_str().unwrap());
    let cwd = c.args["cwd"].as_str().unwrap();
    let sid = c.args.get("sid").and_then(Value::as_str);
    let pane = c.args.get("pane").and_then(Value::as_str).unwrap_or("");
    let settings = e.settings();
    let paths = e.paths();
    let probe = FsProbe::new(e, c);
    let clock = Clock { now: c.args["now"].as_f64().unwrap(), utc_offset_secs: 0 };
    let live = Live { settings: &settings, paths: &paths, probe: &probe, clock };
    let usage = live.live_usage(cli, cwd, sid).map(|u| {
        Value::Object(USAGE_FIELDS.iter().zip(u.values()).map(|(k, v)| (k.to_string(), v.into())).collect::<Map<_, _>>())
    });
    let phase = live.live_phase(cli, cwd, sid).map(|p| {
        let mut m = map(json!({"name": p.name}));
        for (k, v) in PHASE_INT_FIELDS.iter().zip(p.ints) {
            if let Some(v) = v {
                m.insert(k.to_string(), v.into());
            }
        }
        if let Some(d) = p.detail {
            m.insert("detail".into(), d.into());
        }
        if let Some(l) = p.last_unix {
            m.insert("last_unix".into(), l.into());
        }
        Value::Object(m)
    });
    let failed = live.live_failed_turns(cli, cwd, sid).map(|f| {
        let mut m = map(json!({"count": f.count, "last_unix": f.last_unix}));
        if let Some(err) = f.last_error {
            m.insert("last_error".into(), err.into());
        }
        Value::Object(m)
    });
    let mut out = map(json!({
        "busy_status_pattern": cli.busy_status_pattern(),
        "background_work": opt(live.background_work(cli, pane, cwd, sid)),
        "live_busy": opt(live.live_busy(cli, cwd, sid)),
        "live_tools": opt(live.live_tools(cli, cwd, sid)),
        "live_context": opt(live.live_context(cli, cwd, sid)),
        "live_usage": usage,
        "live_failed_turns": failed,
        "live_phase": phase,
    }));
    if cli == Cli::Ucli {
        out.insert("dirs".into(), json!(live.chat_session_dirs(cwd)));
        // Python f-string: sid None ise "None"
        let name = format!("{}.status.json", sid.unwrap_or("None"));
        out.insert("status_path".into(), live.find_chat_file(cwd, &name).into());
        let records = live.failed_turn_records(cwd, sid.unwrap_or(""));
        out.insert("records".into(), json!(records));
    }
    RsOut::ret(Value::Object(out))
}

struct Build<'a> {
    e: &'a Env,
    cases: Vec<Case>,
}

impl Build<'_> {
    fn cwd(&self) -> String {
        format!("{}/work/p1", self.e.root)
    }

    fn case(&self, id: &str, cli: &str, sid: Option<&str>, pane: &str) -> Case {
        Case::new(format!("live-{id}"), "live", json!({"cli": cli, "cwd": self.cwd(), "sid": sid, "pane": pane, "now": T}))
    }

    /// Yeni (`--state-dir`) sohbet dizini, köke göreli.
    fn new_dir(&self) -> String {
        let root = format!("{}/.claude/claudeops/ucli-state", self.e.home);
        let dir = state_dir_for(&root, &self.cwd());
        dir.strip_prefix(&format!("{}/", self.e.root)).unwrap().to_string()
    }

    /// Eski dizinde `s1.status.json` içeriği `body` olan ucli vakası.
    fn status(&self, id: &str, body: impl AsRef<[u8]>) -> Case {
        self.case(&format!("durum-{id}"), "ucli", Some("s1"), "")
            .file(Fx::File("work/p1/.ucli/chat/s1.status.json".into(), body.as_ref().to_vec(), 0o644))
    }

    fn push(&mut self, c: Case) {
        self.cases.push(c);
    }
}

const WRITING: &str = r#"{"name":"writing","since_unix":1700000000,"attempt":1,"max_attempts":10,"wait_secs":0,"detail":null,"streamed_bytes":64936}"#;

fn status_bodies(b: &mut Build<'_>) {
    let long = "ğ".repeat(500);
    let mut bodies: Vec<String> = [
        r#"{}"#,
        r#"{"activity":"waiting_for_stdin"}"#,
        r#"{"activity":"waiting_for_model"}"#,
        r#"{"activity":"running_tool","background_tasks":2}"#,
        r#"{"activity":"waiting_for_user","background_tasks":0}"#,
        r#"{"activity":"Waiting_for_stdin"}"#,
        r#"{"activity":null}"#,
        r#"{"activity":7}"#,
        r#"{"activity":["waiting_for_stdin"]}"#,
        r#"{"background_tasks":"2","tools":"x","context_bytes":"12"}"#,
        r#"{"background_tasks":-1,"tools":null,"context_bytes":-5}"#,
        r#"{"background_tasks":true,"tools":{},"context_bytes":true}"#,
        r#"{"background_tasks":1.0,"tools":[],"context_bytes":1.0}"#,
        r#"{"background_tasks":null,"tools":[""],"context_bytes":0}"#,
        r#"{"tools":["a","read_file","ğ aracı"],"context_bytes":1200000}"#,
        r#"{"tools":["a",1],"context_bytes":5}"#,
        r#"{"tools":["a",null],"context_bytes":7}"#,
        r#"{"background_tasks":9223372036854775807,"context_bytes":18446744073709551615}"#,
        r#"{"background_tasks":-123456789012345678901234567890,"context_bytes":-123456789012345678901234567890}"#,
        r#"{"background_tasks":-0,"context_bytes":-0}"#,
        // usage
        r#"{"usage":{"requests":12,"reported":12,"prompt_tokens":466378,"cached_tokens":251648,"completion_tokens":9001,"reasoning_tokens":4200,"request_bytes":1234567,"unmetered":0,"unmetered_bytes":0}}"#,
        r#"{"usage":{"requests":12,"reported":11,"prompt_tokens":1,"cached_tokens":2,"completion_tokens":3,"reasoning_tokens":4,"request_bytes":5,"future_field":5}}"#,
        r#"{"usage":{"requests":"12","reported":-3,"prompt_tokens":1.5,"cached_tokens":true,"completion_tokens":null,"reasoning_tokens":[1],"request_bytes":{},"unmetered":2}}"#,
        r#"{"usage":{}}"#,
        r#"{"usage":null}"#,
        r#"{"usage":[]}"#,
        r#"{"usage":"x"}"#,
        r#"{"usage":7}"#,
        r#"{"turns":3}"#,
        // phase
        r#"{"phase":{"name":"retry_backoff","since_unix":5,"attempt":2,"max_attempts":10,"wait_secs":10,"detail":"could not connect (timed out) after 20s"}}"#,
        r#"{"phase":null}"#,
        r#"{"phase":[]}"#,
        r#"{"phase":"writing"}"#,
        r#"{"phase":7}"#,
        r#"{"phase":{}}"#,
        r#"{"phase":{"name":null}}"#,
        r#"{"phase":{"name":""}}"#,
        r#"{"phase":{"name":"   "}}"#,
        r#"{"phase":{"name":"\u001c\u001f\u00a0\u3000"}}"#,
        r#"{"phase":{"name":3}}"#,
        r#"{"phase":{"name":["writing"]}}"#,
        r#"{"phase":{"name":"\u001c writing \u00a0","detail":"\u001f x y \n"}}"#,
        r#"{"phase":{"name":"waiting_response","since_unix":"12","attempt":-1,"max_attempts":true,"wait_secs":1.5,"streamed_bytes":null}}"#,
        r#"{"phase":{"name":"w","detail":""}}"#,
        r#"{"phase":{"name":"w","detail":"  "}}"#,
        r#"{"phase":{"name":"w","detail":7}}"#,
        r#"{"phase":{"name":"tool_prefetch","since_unix":9,"future_field":5}}"#,
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    bodies.push(format!(r#"{{"phase":{{"name":"  writing{long}","detail":"{long}"}}}}"#));
    bodies.push(format!(r#"{{"phase":{{"name":"{}","detail":" {}🙂 "}}}}"#, "x".repeat(39) + " y", "x".repeat(159)));
    for last in ["1700000042", "null", "\"12\"", "-5", "true", "1.5", "[1]", "0"] {
        bodies.push(format!(r#"{{"phase":{WRITING},"last_activity_unix":{last}}}"#));
    }
    for (i, body) in bodies.iter().enumerate() {
        let c = b.status(&format!("{i}"), body);
        b.push(c);
    }
    // bozuk dosyalar ve Python `json` ayrıntıları (her biri sayaç/faz taşır ki kabul/ret görünsün)
    let full = format!(r#""activity":"waiting_for_stdin","context_bytes":400,"usage":{{"requests":1}},"phase":{WRITING}"#);
    let nested = |n: usize| format!(r#"{{{full},"d":{}{}}}"#, "[".repeat(n), "]".repeat(n));
    let broken: Vec<(&str, Vec<u8>)> = vec![
        ("bozuk", b"{not json".to_vec()),
        ("bos", Vec::new()),
        ("bosluk", b" \n\t".to_vec()),
        ("liste", b"[1]".to_vec()),
        ("null", b"null".to_vec()),
        ("sayi", b"5".to_vec()),
        ("metin", b"\"x\"".to_vec()),
        ("yarim", format!("{{{full}").into_bytes()),
        ("kuyruk", format!("{{{full}}} x").into_bytes()),
        ("virgul", format!("{{{full},}}").into_bytes()),
        ("bom", format!("\u{feff}{{{full}}}").into_bytes()),
        ("utf8", [format!("{{{full},\"x\":\"").into_bytes(), vec![0xff, b'"', b'}']].concat()),
        ("denetim", format!("{{{full},\"x\":\"a\tb\"}}").into_bytes()),
        ("satir", format!("{{{full},\r\n\"x\":1}}\r\n").into_bytes()),
        ("formfeed", format!("{{{full}}}\u{c}").into_bytes()),
        ("onsifir", format!("{{{full},\"x\":01}}").into_bytes()),
        ("nokta", format!("{{{full},\"x\":1.}}").into_bytes()),
        ("nan", format!("{{{full},\"x\":NaN,\"y\":Infinity,\"z\":-Infinity}}").into_bytes()),
        ("nan-alan", br#"{"context_bytes":NaN,"background_tasks":Infinity,"usage":{"requests":NaN}}"#.to_vec()),
        ("vekil", format!(r#"{{{full},"x":"\ud83d","y":"\udc00 \ud83d\ude00"}}"#).into_bytes()),
        ("yinelenen", format!(r#"{{{full},"context_bytes":800,"activity":"running_tool"}}"#).into_bytes()),
        ("us", format!(r#"{{{full},"x":1e999,"y":-1.5E+3}}"#).into_bytes()),
        ("derin", nested(300).into_bytes()),
    ];
    for (id, body) in broken {
        let c = b.status(id, body);
        b.push(c);
    }
    let c = b.status("cok-derin", nested(600)).known("512'den derin belge: Python okur, Rust 'okunamadı' sayar (yığın sınırı)");
    b.push(c);
    // 4300 basamaktan uzun sayı iki tarafta da "okunamadı"
    let c = b.status("dev-sayi", format!(r#"{{{full},"x":{}}}"#, "9".repeat(5000)));
    b.push(c);
    let c = b
        .status("tasan-sayac", r#"{"usage":{"requests":123456789012345678901234567890},"phase":{"name":"w","attempt":18446744073709551616}}"#)
        .known("u64'e sığmayan sayaç: Python sınırsız int, Rust u64::MAX");
    b.push(c);
    let c = b
        .status("sinir-ustu", format!("{{{full}}}{}", " ".repeat(STATUS_MAX_BYTES as usize)))
        .known("8 MiB üstü durum dosyası: Python sınırsız okur, Rust 'okunamadı' sayar");
    b.push(c);
    let c = b.status("sinir-icinde", format!("{{{full}}}{}", " ".repeat(STATUS_MAX_BYTES as usize - full.len() - 2)));
    b.push(c);
    let c = b.case("durum-dizin", "ucli", Some("s1"), "").file(Fx::Dir("work/p1/.ucli/chat/s1.status.json".into(), 0o755));
    b.push(c);
    for (id, sid) in [("yok-sid", None), ("bos-sid", Some("")), ("baska-sid", Some("s2")), ("onek-sid", Some("s"))] {
        let c = b
            .case(&format!("durum-{id}"), "ucli", sid, "1 shell · esc to interrupt")
            .file(file("work/p1/.ucli/chat/s1.status.json", &format!("{{{full}}}"), 0o644));
        b.push(c);
    }
}

/// Geçerli bir durum dosyasının rastgele bozulmuş biçimleri: kabul/ret ve okunan alanlar aynı olmalı.
fn mutated_status(b: &mut Build<'_>) {
    const T: &[&str] = &[
        "{", "}", "[", "]", "\"", ",", ":", " ", "-", ".", "e", "1", "0", "null", "true", "NaN", "Infinity", "\\",
        "\\n", "\\u0041", "ğ", "\n", "\t",
    ];
    let base = r#"{"activity":"waiting_for_stdin","context_bytes":4096,"background_tasks":2,"tools":["a","b"],"usage":{"requests":3,"unmetered":1},"phase":{"name":"writing","since_unix":17,"detail":"d"},"last_activity_unix":42}"#;
    let mut r = Rng(3);
    for i in 0..400 {
        let mut c: Vec<char> = base.chars().collect();
        for _ in 0..1 + r.below(2) {
            let at = r.below(c.len());
            match r.below(3) {
                0 => {
                    c.remove(at);
                }
                1 => c.splice(at..=at, T[r.below(T.len())].chars()).for_each(drop),
                _ => c.splice(at..at, T[r.below(T.len())].chars()).for_each(drop),
            }
        }
        let case = b.status(&format!("rastgele-{i}"), c.into_iter().collect::<String>());
        b.push(case);
    }
}

/// `--state-dir` açık/kapalı, yeni/eski dizin birleşimleri.
fn state_dirs(b: &mut Build<'_>) {
    let new = b.new_dir();
    let on = json!({"ucli_limits": {"state_dir": "on"}});
    for (setting, tag) in [(Some(&on), "acik"), (None, "kapali")] {
        for (has_new_dir, in_new, in_old) in
            [(false, false, false), (false, false, true), (true, false, false), (true, true, false), (true, false, true), (true, true, true)]
        {
            let mut c = b.case(&format!("dizin-{tag}-{has_new_dir}-{in_new}-{in_old}"), "ucli", Some("oturum-ğ"), "");
            if let Some(s) = setting {
                c = c.settings_json(s.clone());
            }
            if has_new_dir {
                c = c.file(Fx::Dir(new.clone(), 0o700));
            }
            if in_new {
                c = c
                    .file(file(&format!("{new}/oturum-ğ.status.json"), r#"{"context_bytes":40}"#, 0o600))
                    .file(file(&format!("{new}/failed/oturum-ğ-20-1.json"), r#"{"error":"yeni"}"#, 0o600));
            }
            if in_old {
                c = c
                    .file(file("work/p1/.ucli/chat/oturum-ğ.status.json", r#"{"context_bytes":80}"#, 0o600))
                    .file(file("work/p1/.ucli/chat/failed/oturum-ğ-30-1.json", r#"{"error":"eski"}"#, 0o600));
            }
            b.push(c);
        }
    }
    // cwd symlink (gerçek yol özetlenir), sonda `/`, göreli yol
    for (id, cwd) in
        [("link", format!("{}/work/lnk", b.e.root)), ("bolu", format!("{}/work/p1/", b.e.root)), ("goreli", "work/p1".into())]
    {
        let mut c = b
            .case(&format!("dizin-{id}"), "ucli", Some("s1"), "")
            .settings_json(on.clone())
            .file(Fx::Link("work/lnk".into(), "p1".into()))
            .file(file(&format!("{new}/s1.status.json"), r#"{"context_bytes":40}"#, 0o600));
        c.args["cwd"] = cwd.into();
        b.push(c);
    }
}

fn failed_records(b: &mut Build<'_>) {
    const DIR: &str = "work/p1/.ucli/chat/failed";
    let put = |c: Case, name: &str, body: &str| c.file(file(&format!("{DIR}/{name}"), body, 0o644));
    let c = b.case("hata-dizin-yok", "ucli", Some("s1"), "");
    b.push(c);
    let c = b.case("hata-dizin-bos", "ucli", Some("s1"), "").file(Fx::Dir(DIR.into(), 0o755));
    b.push(c);
    let c = b.case("hata-dizin-dosya", "ucli", Some("s1"), "").file(file(DIR, "x", 0o644));
    b.push(c);
    let mut c = b.case("hata-sayim", "ucli", Some("s1"), "");
    for (name, body) in [
        ("s1-1700000000-1.json", r#"{"error":"old"}"#),
        ("s1-1700000500-2.json", r#"{"error":"timed out\nafter 600s"}"#),
        ("s1-2-1700000900-1.json", r#"{"error":"other session"}"#),
        ("s1-notes.json", "{}"),
        ("s1-1700000600-1.txt", "x"),
        ("s1-1700000600-1.JSON", "x"),
        ("s1-x-1.json", "{}"),
        ("s1-1-x.json", "{}"),
        ("s1--1.json", "{}"),
        ("s1-1-.json", "{}"),
        ("s1-1700000700.json", "{}"),
        ("-1700000800-1.json", "{}"),
        ("s2-1700000800-1.json", "{}"),
        (".json", "{}"),
    ] {
        c = put(c, name, body);
    }
    b.push(c);
    // aynı saniye: sıra n'e göre; Unicode ondalık rakam; baştaki sıfır
    let mut c = b.case("hata-sira", "ucli", Some("s1"), "");
    for (name, body) in [
        ("s1-100-2.json", r#"{"error":"iki"}"#),
        ("s1-100-10.json", r#"{"error":"on"}"#),
        ("s1-0099-1.json", r#"{"error":"eski"}"#),
        ("s1-٥-1.json", r#"{"error":"arapça"}"#),
    ] {
        c = put(c, name, body);
    }
    b.push(c);
    // tireli oturum adı
    let c = put(put(b.case("hata-tireli", "ucli", Some("cli-2"), ""), "cli-2-5-1.json", "{}"), "cli-7-1.json", "{}");
    b.push(c);
    let c = put(b.case("hata-ust-simge", "ucli", Some("s1"), ""), "s1-5-1.json", r#"{"error":"x"}"#);
    // üst simge rakamlı ad iki tarafta da yalnız kendisi atlanır
    let c = put(c, "s1-²-1.json", "{}");
    b.push(c);
    let c = put(b.case("hata-dev-unix", "ucli", Some("s1"), ""), "s1-99999999999999999999999999-1.json", "{}")
        .known("u64'e sığmayan zaman: Python sınırsız int, Rust u64::MAX");
    b.push(c);
    let long = "ğ ".repeat(200);
    let errors: Vec<String> = [
        r#"{"error":"  a \t b\n\n c \u001c d \u3000 e \u00a0 "}"#,
        r#"{"error":"   "}"#,
        r#"{"error":""}"#,
        r#"{"error":null}"#,
        r#"{}"#,
        r#"{"error":0}"#,
        r#"{"error":false}"#,
        r#"{"error":true}"#,
        r#"{"error":42}"#,
        r#"{"error":-2.5}"#,
        r#"{"error":1e300}"#,
        r#"{"error":NaN}"#,
        r#"{"error":123456789012345678901234567890}"#,
        r#"{"error":[]}"#,
        r#"{"error":["a","b'c","d\"e","f\ng",1,1.5,true,null,{"k":[]}]}"#,
        r#"{"error":["\u00a0\u200b\u2028\u0007\u007f ğ 🙂 \\ '\""]}"#,
        r#"{"error":{"message":"HTTP 400"}}"#,
        r#"{"error":{"message":"","error":"ikinci"}}"#,
        r#"{"error":{"message":null,"error":0,"code":500}}"#,
        r#"{"error":{"message":{"a":"b","c":[1,2]}}}"#,
        r#"{"error":{"error":["x"]}}"#,
        r#"{"error":{}}"#,
        r#"{"error":{"ğ":"ü\n\t\r\b\f\u0001\"\\ 🙂","f":1.0,"n":null,"t":true,"x":NaN,"y":-Infinity,"l":[1,[]],"o":{}}}"#,
        r#"{"error":{"z":1,"a":2,"z":3}}"#,
        r#"[{"error":"x"}]"#,
        r#""error""#,
        "null",
        "{not json",
        "",
    ]
    .iter()
    .map(|s| s.to_string())
    .chain([format!(r#"{{"error":"{long}"}}"#), format!(r#"{{"error":{{"message":"{}🙂🙂"}}}}"#, "x".repeat(159))])
    .collect();
    for (i, body) in errors.iter().enumerate() {
        let c = put(b.case(&format!("hata-metin-{i}"), "ucli", Some("s1"), ""), "s1-1700000000-1.json", body);
        b.push(c);
    }
    let c = b
        .case("hata-utf8", "ucli", Some("s1"), "")
        .file(Fx::File(format!("{DIR}/s1-1-1.json"), b"{\"error\":\"\xff\"}".to_vec(), 0o644));
    b.push(c);
    let c = b.case("hata-kayit-dizin", "ucli", Some("s1"), "").file(Fx::Dir(format!("{DIR}/s1-1-1.json"), 0o755));
    b.push(c);
}

fn background(b: &mut Build<'_>) {
    let cwd = b.cwd();
    let projects = format!("home/.claude/projects/{}", encode_cwd(&cwd));
    let pend = pending_use("t1", "2099-01-01T00:00:00Z") + "\n";
    let stale = pending_use("t1", "2000-01-01T00:00:00Z") + "\n";
    for (name, screen) in screens() {
        if name == "kenar" {
            continue;
        }
        for cli in ["claude", "codex"] {
            let c = b.case(&format!("ekran-{cli}-{name}-{}", screen.len()), cli, None, &screen);
            b.push(c);
        }
    }
    for (id, sid, body) in [("bekleyen", Some("abc"), &pend), ("eski", Some("abc"), &stale), ("sidsiz", None, &pend)] {
        for pane in ["", "❯ ? for shortcuts", "2 background tasks · ↓ to manage"] {
            let c = b
                .case(&format!("claude-{id}-{}", pane.len()), "claude", sid, pane)
                .file(file(&format!("{projects}/abc.jsonl"), body, 0o600));
            b.push(c);
        }
    }
    let c = b.case("claude-transkript-yok", "claude", Some("abc"), "");
    b.push(c);
    let rollout = "home/.codex/sessions/2026/11/23/rollout-x-sidabc.jsonl";
    let agents = [
        sub_agent("started", json!("a1"), "2026-11-23T10:17:26Z"),
        sub_agent("started", json!("a2"), "2026-11-23T10:17:27Z"),
        sub_agent("completed", json!("a1"), "2026-11-23T10:18:30Z"),
    ]
    .join("\n");
    for pane in ["", "  1 background terminal running · /ps to view"] {
        let c = b.case(&format!("codex-ajan-{}", pane.len()), "codex", Some("sidabc"), pane).file(file(rollout, &agents, 0o600));
        b.push(c);
    }
    // diğer CLI'lar: ekran ve sid ne olursa olsun varsayılanlar
    for cli in ["claude", "agy", "codex", "copilot", "ucli", "shell", "bogus"] {
        let c = b.case(&format!("varsayilan-{cli}"), cli, Some("sid"), "1 shell · esc to interrupt");
        b.push(c);
    }
}

fn token_count(input: Value) -> String {
    json!({"type": "event_msg", "payload": {"type": "token_count", "info": {
        "last_token_usage": {"input_tokens": input, "cached_input_tokens": 5}, "model_context_window": 258400}}})
    .to_string()
}

fn codex_context(b: &mut Build<'_>) {
    const ROLLOUT: &str = "home/.codex/sessions/2026/11/23/rollout-x-sidabc.jsonl";
    let t = |n: i64| token_count(json!(n));
    let other = r#"{"type":"response_item","payload":{}}"#;
    let filler = format!("{{\"x\":\"{}\"}}", "x".repeat(262_144));
    let bodies: Vec<String> = vec![
        format!("{}\n{other}\n{}\n", t(1000), t(20138)),
        format!("{other}\n"),
        String::new(),
        "{\"type\":\"event_msg\",\"payload\":{\"type\":\"token_count\",\"info\":null}}\n".into(),
        format!("{}\n{{\"payload\":{{\"type\":\"token_count\",\"info\":null}}}}\n", t(7)),
        format!("{}\n{}\n", t(7), t(0)),
        format!("{}\n{}\n", t(7), t(-3)),
        format!("{}\n{}\n", t(7), token_count(json!("9"))),
        format!("{}\n{}\n", t(7), token_count(json!(9.5))),
        format!("{}\n{}\n", t(7), token_count(json!(null))),
        format!("{}\n[\"token_count\"]\n\"token_count\"\nnull \"token_count\"\n", t(7)),
        format!("{}\n{{\"payload\":\"token_count\"}}\n{{\"payload\":{{\"type\":\"token_count\",\"info\":\"x\"}}}}\n", t(7)),
        format!("{}\n{{\"payload\":{{\"type\":\"token_count\",\"info\":{{\"last_token_usage\":[]}}}}}}\n", t(7)),
        format!("{}\n{}\n", t(7), t(9).replace("event_count", "x").replace("\"type\":\"token_count\"", "\"type\":\"other\",\"k\":\"token_count\"")),
        // yarım yazılmış son satır, CRLF, `\r`, Python satır sınırları
        format!("{}\n{}", t(7), &t(9)[..60]),
        format!("{}\r\n{}\r\n", t(7), t(9)),
        format!("{}\r{}", t(7), t(9)),
        format!("{}\u{2028}{}\u{85}", t(7), t(9)),
        format!("{}\n{}\n", t(7), t(9).replacen('{', "{\"s\":\"a\u{2028}b\",", 1)),
        format!("{}\n{}\n", t(7), t(9).replacen('{', "{\"s\":\"\\ud83d\",\"n\":NaN,", 1)),
        // 256 KiB kuyruğu dışında / içinde
        format!("{}\n{filler}\n", t(7)),
        format!("{filler}\n{}\n", t(11)),
    ];
    for (i, body) in bodies.iter().enumerate() {
        let c = b.case(&format!("codex-ctx-{i}"), "codex", Some("sidabc"), "").file(file(ROLLOUT, body, 0o600));
        b.push(c);
    }
    let mut broken = t(7).into_bytes();
    broken.extend_from_slice(b"\n\xff\xfe \"token_count\"\n");
    let c = b.case("codex-ctx-utf8", "codex", Some("sidabc"), "").file(Fx::File(ROLLOUT.into(), broken, 0o600));
    b.push(c);
    for (id, sid) in [("yok", Some("yok-sid")), ("sidsiz", None)] {
        let c = b.case(&format!("codex-ctx-{id}"), "codex", sid, "").file(file(ROLLOUT, &t(7), 0o600));
        b.push(c);
    }
    let c = b
        .case("codex-ctx-bool", "codex", Some("sidabc"), "")
        .file(file(ROLLOUT, &format!("{}\n{}\n", t(7), token_count(json!(true))), 0o600));
    b.push(c);
    let c = b
        .case("codex-ctx-negatif", "codex", Some("sidabc"), "")
        .file(file(ROLLOUT, &format!("{}\n{}\n", t(7), token_count(json!(-5))), 0o600));
    b.push(c);
    let c = b
        .case("codex-ctx-dev", "codex", Some("sidabc"), "")
        .file(file(ROLLOUT, &token_count(json!(1)).replace("\"input_tokens\":1}", "\"input_tokens\":99999999999999999999}"), 0o600))
        .known("i64'e sığmayan sayaç: Python sınırsız int, Rust i64::MAX");
    b.push(c);
}

/// `assistant_usage_events` tablolu bir SQLite dosyasının baytları.
fn db_bytes(rows: &[(&str, i64, Option<&str>, Sql, &str)]) -> Vec<u8> {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("s.db");
    let c = rusqlite::Connection::open(&path).unwrap();
    // tip belirtilmeyen sütun: dinamik tip korunur
    c.execute_batch("CREATE TABLE assistant_usage_events (session_id TEXT, turn_index INT, agent_id TEXT, input_tokens, created_at TEXT)")
        .unwrap();
    for r in rows {
        c.execute("INSERT INTO assistant_usage_events VALUES (?,?,?,?,?)", rusqlite::params![r.0, r.1, r.2, r.3, r.4])
            .unwrap();
    }
    drop(c);
    fs::read(path).unwrap()
}

/// Var olan SQLite baytlarına copilot `sessions` tablosu ekler: `(id, cwd)`, sırayla yeniye.
pub fn with_sessions(db: &[u8], rows: &[(Sql, Sql)]) -> Vec<u8> {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("s.db");
    fs::write(&path, db).unwrap();
    let c = rusqlite::Connection::open(&path).unwrap();
    c.execute_batch("CREATE TABLE sessions (id, cwd, updated_at)").unwrap();
    for (i, (id, cwd)) in rows.iter().enumerate() {
        c.execute("INSERT INTO sessions VALUES (?,?,?)", rusqlite::params![id, cwd, i as i64]).unwrap();
    }
    drop(c);
    fs::read(path).unwrap()
}

fn copilot_context(b: &mut Build<'_>) {
    const DB: &str = "home/.copilot/session-store.db";
    let t0 = "2026-10-27T10:00:00Z";
    let t1 = "2026-10-27T10:05:00Z";
    let rows = db_bytes(&[
        ("s1", 0, None, Sql::Integer(1000), t0),
        ("s1", 1, None, Sql::Integer(5000), t1),
        ("s1", 1, Some("sub1"), Sql::Integer(99999), "2026-10-27T10:06:00Z"),
        ("s2", 0, None, Sql::Integer(7), "2026-10-27T10:07:00Z"),
        ("tur", 0, None, Sql::Integer(1), t0),
        ("tur", 2, None, Sql::Integer(2), t0),
        ("tur", 1, None, Sql::Integer(3), t0),
    ]);
    for (id, sid, resume) in [
        ("son", Some("s1"), None),
        ("tur", Some("tur"), None),
        ("yok", Some("yok"), None),
        ("enjeksiyon", Some("s1' OR 1=1 --"), None),
        ("resume", None, Some("s2")),
        ("bos-sid", Some(""), Some("s2")),
        ("resume-yok", None, None),
        ("resume-bos", None, Some("")),
    ] {
        let db = match resume {
            Some(r) => with_sessions(&rows, &[(Sql::Text(r.into()), Sql::Text(b.cwd()))]),
            None => rows.clone(),
        };
        let c = b.case(&format!("copilot-{id}"), "copilot", sid, "").file(Fx::File(DB.into(), db, 0o600));
        b.push(c);
    }
    let cells: Vec<(&str, Sql)> = vec![
        ("null", Sql::Null),
        ("sifir", Sql::Integer(0)),
        ("negatif", Sql::Integer(-4)),
        ("buyuk", Sql::Integer(i64::MAX)),
        ("kesir", Sql::Real(1234.9)),
        ("eksi-kesir", Sql::Real(-1.5)),
        ("yarim", Sql::Real(0.5)),
        ("sifir-kesir", Sql::Real(0.0)),
        ("metin", Sql::Text(" 1_000 ".into())),
        ("metin-sifir", Sql::Text("0".into())),
        ("metin-bos", Sql::Text(String::new())),
        ("blob", Sql::Blob(b"12".to_vec())),
        ("blob-bos", Sql::Blob(Vec::new())),
    ];
    for (id, v) in cells {
        let c = b
            .case(&format!("copilot-hucre-{id}"), "copilot", Some("s1"), "")
            .file(Fx::File(DB.into(), db_bytes(&[("s1", 0, None, v, t0)]), 0o600));
        b.push(c);
    }
    for (id, v) in [("metin-harf", Sql::Text("abc".into())), ("sonsuz", Sql::Real(f64::INFINITY))] {
        let c = b
            .case(&format!("copilot-hucre-{id}"), "copilot", Some("s1"), "")
            .file(Fx::File(DB.into(), db_bytes(&[("s1", 0, None, v, t0)]), 0o600))
            .known("sayıya çevrilemeyen hücre: Python `int()` istisnası yükselir, Rust None");
        b.push(c);
    }
    for (id, content) in [("bozuk", b"not a database at all, definitely not".to_vec()), ("bos", Vec::new())] {
        let c = b.case(&format!("copilot-db-{id}"), "copilot", Some("s1"), "").file(Fx::File(DB.into(), content, 0o600));
        b.push(c);
    }
    let c = b.case("copilot-db-yok", "copilot", Some("s1"), "");
    b.push(c);
}

pub fn run() {
    let mut r = Runner::new();
    let cases = {
        let mut b = Build { e: &r.e, cases: Vec::new() };
        status_bodies(&mut b);
        mutated_status(&mut b);
        state_dirs(&mut b);
        failed_records(&mut b);
        background(&mut b);
        codex_context(&mut b);
        copilot_context(&mut b);
        b.cases
    };
    r.run(cases, &[], rs_live);
    r.finish("live");
}
