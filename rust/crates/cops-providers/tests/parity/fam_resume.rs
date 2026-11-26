//! Aile (G1): oturum kimliği ve devam (`resolve_resume_id`, `sid_for_stopped_session`, canlı kimlik keşfi,
//! `jsonl_path_for`, `session_file_sid`, `_ids_held_by_others`, `agy_sids` yazımı). Senaryolar
//! `py/tests/test_{stopped_session_chat,handover_cache_policy,needs_ho_transcript,agy_sids_store}.py` + bozuk/boş/
//! Unicode girdi, tarama sınırları ve eşit zamanlı dosyalar. Tüm veri sentetik, `/proc` ve süreç taraması sahte.

use crate::common::*;
use crate::fam_bg::Rng;
use crate::fam_live::with_sessions;
use cops_providers::claude_resume::{META_CACHE_MAX, META_HEAD_LINES, RESUME_SCAN_LIMIT, STUB_MAX_BYTES};
use cops_providers::codex_resume::MAX_ROLLOUT_SCAN;
use cops_providers::pyjson::Py;
use cops_providers::{agy_resume, copilot, ids_held_by_others, AgySidStore, Cli, Live, LiveSession, MetaCache};
use rusqlite::types::Value as Sql;
use serde_json::{json, Value};
use std::cell::RefCell;
use std::collections::{BTreeSet, HashMap};
use std::fs;

const CWD: &str = "work/p1";
const T0: i64 = 1_700_000_000;
const AGY_DIR: &str = "home/.gemini/antigravity-cli/conversations";
const AGY_CACHE: &str = "home/.gemini/antigravity-cli/cache/last_conversations.json";
const COPILOT_DB: &str = "home/.copilot/session-store.db";
const ROLL: &str = "home/.codex/sessions/2026/11/23";

/// `/proc/<pid>/stat` satırı: comm boşluk ve parantez taşır, 19. alan (comm sonrası) `start`.
pub fn proc_stat(pid: i64, start: &str) -> String {
    format!("{pid} (cl) a(u) S 1 1 1 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 {start} 0 0\n")
}

fn project(cwd: &str) -> String {
    let encoded: String = cwd.chars().map(|c| if c.is_ascii_alphanumeric() { c } else { '-' }).collect();
    format!("home/.claude/projects/{encoded}")
}

struct Build<'a> {
    e: &'a Env,
    cases: Vec<Case>,
    /// Dosya -> mtime (kök göreli yol): fixture kurulduktan sonra iki tarafta da uygulanır.
    times: HashMap<String, Vec<(String, i64, u32)>>,
    expect: HashMap<String, Value>,
}

/// Kurulmakta olan vaka.
struct B {
    id: String,
    files: Vec<Fx>,
    times: Vec<(String, i64, u32)>,
    queries: Vec<Value>,
    facts: Value,
}

impl B {
    fn new(id: &str) -> B {
        B { id: format!("devam-{id}"), files: Vec::new(), times: Vec::new(), queries: Vec::new(), facts: json!({}) }
    }
    fn raw(mut self, rel: impl Into<String>, body: impl Into<Vec<u8>>) -> B {
        self.files.push(Fx::File(rel.into(), body.into(), 0o644));
        self
    }
    fn at(mut self, rel: impl Into<String>, body: impl Into<Vec<u8>>, mtime: i64) -> B {
        let rel = rel.into();
        self.times.push((rel.clone(), mtime, 0));
        self.raw(rel, body)
    }
    fn at_ns(mut self, rel: impl Into<String>, body: impl Into<Vec<u8>>, mtime: i64, ns: u32) -> B {
        let rel = rel.into();
        self.times.push((rel.clone(), mtime, ns));
        self.raw(rel, body)
    }
    fn fx(mut self, f: Fx) -> B {
        self.files.push(f);
        self
    }
    fn q(mut self, q: Value) -> B {
        self.queries.push(q);
        self
    }
    fn facts(mut self, v: Value) -> B {
        self.facts = v;
        self
    }
}

impl Build<'_> {
    fn abs(&self, rel: &str) -> String {
        format!("{}/{rel}", self.e.root)
    }
    fn cwd(&self) -> String {
        self.abs(CWD)
    }
    fn dir(&self) -> String {
        project(&self.cwd())
    }
    fn push(&mut self, b: B) {
        let c = Case::new(b.id.clone(), "resume", json!({"queries": b.queries}));
        let mut c = c.facts(b.facts);
        c.files = b.files;
        self.times.insert(b.id, b.times);
        self.cases.push(c);
    }
    fn diverges(&mut self, b: B, why: &'static str, expect: Value) {
        self.expect.insert(b.id.clone(), expect);
        self.push(b);
        let c = self.cases.last_mut().unwrap();
        c.known = Some(why);
    }

    /// claude sorguları: `sid` yolları, resume seçimi (adlarla ve ellerdekiyle) ve durmuş oturum.
    fn claude_queries(&self, b: B, names: &[&str], held: &[&str]) -> B {
        let cwd = self.cwd();
        let mut b = b.q(json!({"f": "latest", "cwd": cwd}));
        for sid in [Value::Null, json!(""), json!("a"), json!("yok")] {
            b = b.q(json!({"f": "jsonl", "cwd": cwd, "sid": sid}));
        }
        for name in names {
            b = b.q(json!({"f": "resolve", "cli": "claude", "cwd": cwd, "name": name}));
            b = b.q(json!({"f": "resolve", "cli": "claude", "cwd": cwd, "name": name, "in_use": held}));
            b = b.q(json!({"f": "stopped", "cli": "claude", "cwd": cwd, "name": name}));
        }
        b
    }
}

// ----------------------------------------------------------------------------------------------------------- claude

fn head(title: Option<&str>, cwd: &str) -> Vec<String> {
    let mut rows = Vec::new();
    if let Some(t) = title {
        rows.push(json!({"type": "custom-title", "customTitle": t}).to_string());
    }
    rows.push(json!({"type": "system", "cwd": cwd}).to_string());
    rows
}

fn conv(title: Option<&str>, cwd: &str, chat: bool) -> String {
    let mut rows = head(title, cwd);
    if chat {
        rows.push(r#"{"type":"user","message":{"content":"x"}}"#.into());
    }
    rows.iter().map(|r| format!("{r}\n")).collect()
}

fn claude_cases(b: &mut Build<'_>) {
    let (cwd, dir) = (b.cwd(), b.dir());
    let f = |name: &str| format!("{dir}/{name}.jsonl");
    let names = ["", "inst", "inst2", "idle", "never"];
    let held = ["a", "inst2"];
    let c = b.claude_queries(B::new("claude-dizin-yok"), &names, &held);
    b.push(c);
    let c = b.claude_queries(B::new("claude-dizin-bos").fx(Fx::Dir(dir.clone(), 0o755)), &names, &held);
    b.push(c);
    // kardeş oturumlar: kendi konuşması eski, başlık-yalnız stub daha yeni; elde tutulanlar elenir
    let c = B::new("claude-kardes")
        .at(f("a"), conv(Some("inst"), &cwd, true), T0 + 10)
        .at(f("b"), conv(Some("inst2"), &cwd, true), T0 + 30)
        .at(f("c"), conv(Some("inst"), &cwd, false), T0 + 20)
        .at(f("d"), conv(Some("idle"), &cwd, false), T0 + 1)
        .at(f("e"), conv(Some("idle"), &cwd, false), T0 + 2)
        .at(f("f"), conv(None, &cwd, true), T0 + 5);
    let c = b.claude_queries(c, &names, &held);
    b.push(c);
    // aynı ad: en yeni GERÇEK konuşma (en büyüğü değil); ad ön ek olarak eşleşmez
    let mut old = conv(Some("inst"), &cwd, true);
    old.push_str(&"{\"type\":\"user\"}\n".repeat(50));
    let c = B::new("claude-yeni-gercek")
        .at(f("old"), old, T0 + 10)
        .at(f("new"), conv(Some("inst"), &cwd, true), T0 + 20);
    let c = b.claude_queries(c, &["inst", "ins", "inst1"], &[]);
    b.push(c);
    // başka cwd yazan dosya, cwd'siz dosya, göreli/artıklı cwd yazımı
    let messy = format!("{cwd}//./x/..");
    let c = B::new("claude-cwd")
        .at(f("a"), conv(Some("inst"), "/baska/yer", true), T0 + 40)
        .at(f("b"), conv(Some("inst"), &messy, true), T0 + 30)
        .at(f("c"), conv(Some("never"), "", true), T0 + 20)
        .at(f("d"), r#"{"customTitle":"inst2"}"#.to_string(), T0 + 10)
        .at(f("e"), conv(Some("inst"), "work/p1", true), T0 + 50)
        .at(f("g"), conv(Some("idle"), &format!("{cwd}/"), true), T0 + 60);
    let c = b.claude_queries(c, &names, &["e", "g"]);
    b.push(c);
    // uzantı kuralı: `.jsonl` adlı gizli dosya, `..jsonl`, uzantısız, dizin, bağlantı, kopuk bağlantı
    let c = B::new("claude-adlar")
        .at(format!("{dir}/.jsonl"), conv(Some("inst"), &cwd, true), T0 + 90)
        .at(format!("{dir}/..jsonl"), conv(Some("inst2"), &cwd, true), T0 + 5)
        .at(format!("{dir}/x.json"), conv(Some("idle"), &cwd, true), T0 + 99)
        .at(format!("{dir}/x.jsonl.bak"), conv(Some("never"), &cwd, true), T0 + 98)
        .at(format!("{dir}/.gizli.jsonl"), conv(Some("never"), &cwd, true), T0 + 4)
        .fx(Fx::Dir(format!("{dir}/klasor.jsonl"), 0o755))
        .fx(Fx::Link(format!("{dir}/kopuk.jsonl"), "yok".into()))
        .at(f("a"), conv(Some("never"), &cwd, true), T0 + 1)
        .fx(Fx::Link(format!("{dir}/bag.jsonl"), "a.jsonl".into()));
    let c = b.claude_queries(c, &names, &[]);
    b.push(c);
    // tarama sınırı: resume en yeni 25'e bakar, durmuş oturum hepsine
    for extra in [RESUME_SCAN_LIMIT - 1, RESUME_SCAN_LIMIT, RESUME_SCAN_LIMIT + 5] {
        let mut c = B::new(&format!("claude-sinir-{extra}")).at(f("oldest"), conv(Some("inst"), &cwd, true), T0);
        for i in 0..extra {
            c = c.at(f(&format!("n{i:02}")), conv(Some(&format!("yeni{i}")), &cwd, true), T0 + 10 + i as i64);
        }
        let c = b.claude_queries(c, &["inst", "yeni0", ""], &[]);
        b.push(c);
    }
    // eşit zaman: seçim dizin okuma sırasına bağlı; nanosaniye farkı sıralamayı belirler
    let mut c = B::new("claude-esit-zaman");
    for n in ["z", "m", "a", "q", "b"] {
        c = c.at(f(n), conv(Some("inst"), &cwd, true), T0);
    }
    let c = b.claude_queries(c, &["inst", ""], &["q"]);
    b.push(c);
    for (id, a, z) in [("us", 1000, 2000), ("ns", 1, 2), ("ns-ters", 2, 1), ("saniye-alti", 999_999_999, 0)] {
        let c = B::new(&format!("claude-zaman-{id}"))
            .at_ns(f("a"), conv(Some("inst"), &cwd, true), T0, a)
            .at_ns(f("z"), conv(Some("inst"), &cwd, true), T0, z);
        let c = b.claude_queries(c, &["inst", ""], &[]);
        b.push(c);
    }
    // büyük dosya içine bakılmadan gerçek sayılır; sınırın bir altı taranır
    for (id, size) in [("alti", STUB_MAX_BYTES - 1), ("tam", STUB_MAX_BYTES), ("ustu", STUB_MAX_BYTES + 1)] {
        let mut big = conv(Some("inst"), &cwd, false);
        big.push_str(&" ".repeat(size as usize - big.len()));
        let c = B::new(&format!("claude-stub-{id}"))
            .at(f("kucuk"), conv(Some("inst"), &cwd, true), T0)
            .at(f("a"), big, T0 + 5)
            .q(json!({"f": "stopped", "cli": "claude", "cwd": cwd, "name": "inst"}));
        b.push(c);
    }
}

/// `_jsonl_meta` ve `_has_chat_rows`: satır biçimleri, 15 satır sınırı, satır sonları, bozuk girdi.
fn meta_cases(b: &mut Build<'_>) {
    let title = r#"{"customTitle":"t"}"#;
    let cwd = r#"{"cwd":"/c"}"#;
    let pad = |n: usize| "{}\n".repeat(n);
    let mut bodies: Vec<(String, Vec<u8>)> = [
        ("bos", String::new()),
        ("temel", format!("{title}\n{cwd}\n")),
        ("sonsuz", format!("{title}\n{cwd}")),
        ("on-besinci", format!("{}{title}\n", pad(META_HEAD_LINES - 1))),
        ("on-altinci", format!("{}{title}\n", pad(META_HEAD_LINES))),
        ("crlf", format!("{}{title}\r\n{cwd}\r\n", "{}\r\n".repeat(META_HEAD_LINES - 2))),
        ("cr", format!("{}{title}\r{cwd}\r", "{}\r".repeat(META_HEAD_LINES - 2))),
        ("crlf-disarida", format!("{}{title}\r\n", "{}\r\n".repeat(META_HEAD_LINES))),
        ("bos-satirlar", format!("{}{title}\n", "\n".repeat(META_HEAD_LINES))),
        ("ilk-kazanir", format!("{title}\n{{\"customTitle\":\"u\",\"cwd\":\"/c\"}}\n{{\"cwd\":\"/d\"}}\n")),
        ("bos-baslik", format!("{{\"customTitle\":\"\"}}\n{title}\n{cwd}\n")),
        ("bos-cwd", format!("{{\"cwd\":\"\"}}\n{title}\n{cwd}\n")),
        ("tipler", format!("{{\"customTitle\":5,\"cwd\":[1]}}\n{{\"customTitle\":null}}\n{title}\n")),
        ("nesne-degil", format!("[1]\n5\n\"x\"\nnull\n{title}\n")),
        ("bozuk", format!("{{\n}}{title}\n  {cwd}  \n")),
        ("bom", format!("\u{feff}{title}\n{cwd}\n")),
        ("unicode", "{\"customTitle\":\"ğüş 😀\",\"cwd\":\"/ç\"}\n".to_string()),
        ("uzun-satir", format!("{{\"x\":\"{}\"}}\n{title}\n{cwd}\n", "y".repeat(200_000))),
        ("uzun-sonrasi", format!("{}{{\"x\":\"{}\"}}\n{title}\n", pad(3), "y".repeat(70_000))),
        ("satir-user", "{}\n{\"type\":\"user\"}\n".to_string()),
        ("satir-assistant", "{\"type\":\"assistant\"}".to_string()),
        ("satir-system", "{\"type\":\"system\"}\n{\"type\":[\"user\"]}\n[\"user\"]\n{\"type\":\"User\"}\n".to_string()),
        ("satir-gec", format!("{}{{\"type\":\"user\"}}\n", pad(500))),
    ]
    .into_iter()
    .map(|(id, s)| (id.to_string(), s.into_bytes()))
    .collect();
    bodies.push(("utf8".into(), [b"{\"customTitle\":\"a".to_vec(), vec![0xff, 0xfe], b"\"}\n{\"type\":\"user\"}\n".to_vec()].concat()));
    // rastgele bozulmuş satırlar
    const T: &[&str] = &["{", "}", "\"", ",", ":", " ", "\n", "\r", "\\", "null", "1", "ğ", "\t", "customTitle", "user"];
    let base = format!("{title}\n{cwd}\n{{\"type\":\"user\"}}\n");
    let mut r = Rng(11);
    for i in 0..150 {
        let mut c: Vec<char> = base.chars().collect();
        for _ in 0..1 + r.below(3) {
            let at = r.below(c.len());
            match r.below(3) {
                0 => {
                    c.remove(at);
                }
                1 => c.splice(at..=at, T[r.below(T.len())].chars()).for_each(drop),
                _ => c.splice(at..at, T[r.below(T.len())].chars()).for_each(drop),
            }
        }
        bodies.push((format!("rastgele-{i}"), c.into_iter().collect::<String>().into_bytes()));
    }
    for (id, body) in bodies {
        let path = b.abs("work/m.jsonl");
        let c = B::new(&format!("meta-{id}"))
            .raw("work/m.jsonl", body)
            .q(json!({"f": "meta", "path": path}))
            .q(json!({"f": "chat_rows", "path": path}));
        b.push(c);
    }
    let (missing, folder) = (b.abs("work/yok.jsonl"), b.abs("work/p1"));
    let c = B::new("meta-okunamaz")
        .fx(Fx::File("work/kapali.jsonl".into(), b"{\"type\":\"user\"}\n".to_vec(), 0o000))
        .q(json!({"f": "meta", "path": missing}))
        .q(json!({"f": "meta", "path": folder}))
        .q(json!({"f": "meta", "path": b.abs("work/kapali.jsonl")}))
        .q(json!({"f": "chat_rows", "path": missing}))
        .q(json!({"f": "chat_rows", "path": b.abs("work/kapali.jsonl")}));
    b.push(c);
}

fn session_file_cases(b: &mut Build<'_>) {
    let ok = json!({"pid": 42, "sessionId": "sid-fresh", "procStart": "777"});
    let with = |k: &str, v: Value| {
        let mut o = ok.clone();
        o[k] = v;
        o.to_string()
    };
    let without = |k: &str| {
        let mut o = ok.clone();
        o.as_object_mut().unwrap().remove(k);
        o.to_string()
    };
    let mut bodies: Vec<(String, String)> = vec![
        ("tamam".into(), ok.to_string()),
        ("bozuk".into(), "{bozuk".into()),
        ("liste".into(), "[1,2]".into()),
        ("bos".into(), String::new()),
        ("bom".into(), format!("\u{feff}{ok}")),
        ("nan-pid".into(), r#"{"pid":NaN,"sessionId":"s","procStart":"777"}"#.into()),
        ("pid-yok".into(), without("pid")),
        ("sid-yok".into(), without("sessionId")),
        ("baslangic-yok".into(), without("procStart")),
    ];
    for (i, v) in [json!(43), json!(0), json!(null), json!("42"), json!(" 4_2 "), json!("x"), json!(""), json!(42.9), json!(41.9), json!(true), json!([42]), json!([]), json!({"a": 1}), json!(-42), json!(1e30)].into_iter().enumerate() {
        bodies.push((format!("pid-{i}"), with("pid", v)));
    }
    for (i, v) in [json!(""), json!("  "), json!(123), json!(null), json!(["a"]), json!("  kirpilan \n"), json!("ğ")].into_iter().enumerate() {
        bodies.push((format!("sid-{i}"), with("sessionId", v)));
    }
    for (i, v) in [json!(""), json!("1"), json!(" 777 \n"), json!(777), json!(777.0), json!(null), json!(true), json!("0777")].into_iter().enumerate() {
        bodies.push((format!("start-{i}"), with("procStart", v)));
    }
    let q = json!({"f": "session_sid", "pid": 42});
    for (id, body) in bodies {
        let c = B::new(&format!("kayit-{id}"))
            .raw("home/.claude/sessions/42.json", body)
            .q(q.clone())
            .facts(json!({"proc_stat": {"42": proc_stat(42, "777")}}));
        b.push(c);
    }
    let stats = [
        ("yok", None),
        ("parantezsiz", Some("42 claude S 1".to_string())),
        ("kisa", Some("42 (c) S 1 1".to_string())),
        ("tam-yirmi", Some("42 (c) 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 777".to_string())),
        ("on-dokuz", Some("42 (c) 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 777".to_string())),
        ("baska", Some(proc_stat(42, "778"))),
    ];
    for (id, stat) in stats {
        let mut c = B::new(&format!("stat-{id}")).raw("home/.claude/sessions/42.json", ok.to_string()).q(q.clone());
        if let Some(s) = stat {
            c = c.facts(json!({"proc_stat": {"42": s}}));
        }
        b.push(c);
    }
    let c = B::new("kayit-dosya-yok")
        .q(q.clone())
        .q(json!({"f": "session_sid", "pid": 0}))
        .q(json!({"f": "session_sid", "pid": null}))
        .facts(json!({"proc_stat": {"42": proc_stat(42, "777")}}));
    b.push(c);
    let c = B::new("kayit-utf8").raw("home/.claude/sessions/42.json", vec![b'{', 0xff, b'}']).q(q);
    b.push(c);
}

// ------------------------------------------------------------------------------------------------------------ codex

const U1: &str = "01234567-89ab-cdef-0123-456789abcdef";
const U2: &str = "11111111-2222-3333-4444-555555555555";

fn meta_line(cwd: Value, extra: Value) -> String {
    let mut payload = json!({"cwd": cwd});
    for (k, v) in extra.as_object().unwrap() {
        payload[k] = v.clone();
    }
    format!("{}\n", json!({"type": "session_meta", "payload": payload}))
}

fn codex_queries(b: &Build<'_>, mut c: B, held: &[&str], sids: &[&str]) -> B {
    let cwd = b.cwd();
    c = c.q(json!({"f": "resolve", "cli": "codex", "cwd": cwd}));
    c = c.q(json!({"f": "resolve", "cli": "codex", "cwd": cwd, "in_use": held, "name": "x"}));
    c = c.q(json!({"f": "rollout", "cwd": cwd, "sid": null}));
    for sid in sids {
        c = c.q(json!({"f": "rollout", "cwd": cwd, "sid": sid}));
    }
    c
}

fn codex_cases(b: &mut Build<'_>) {
    let cwd = b.cwd();
    let named = |ts: &str, id: &str| format!("{ROLL}/rollout-{ts}-{id}.jsonl");
    let sids = [U1, U2, "yok", "", "abcdef", "01234567"];
    let c = codex_queries(b, B::new("codex-bos"), &[U1], &sids);
    b.push(c);
    let own = meta_line(json!(cwd), json!({"id": "payload-id"}));
    let c = B::new("codex-temel")
        .at(named("1", U1), own.clone(), T0 + 10)
        .at(named("2", U2), own.clone(), T0 + 20)
        .at(named("3", "99999999-2222-3333-4444-555555555555"), meta_line(json!("/baska"), json!({})), T0 + 30);
    let c = codex_queries(b, c, &[U2], &sids);
    b.push(c);
    // kimlik dosya adında yoksa payload'dan; kimliksiz uygun dosya taramayı bitirir
    for (id, extra) in [
        ("id", json!({"id": "pid-1", "session_id": "pid-2"})),
        ("session-id", json!({"session_id": "pid-2"})),
        ("id-bos", json!({"id": "", "session_id": "pid-2"})),
        ("id-yok", json!({})),
        ("id-bos-iki", json!({"id": null, "session_id": null})),
    ] {
        let c = B::new(&format!("codex-adsiz-{id}"))
            .at(format!("{ROLL}/adsiz.jsonl"), meta_line(json!(cwd), extra), T0 + 20)
            .at(named("1", U1), own.clone(), T0 + 10);
        let c = codex_queries(b, c, &["pid-1"], &["adsiz"]);
        b.push(c);
    }
    // cwd biçimleri ve ilk satır sınırları
    let lines: Vec<(&str, String)> = vec![
        ("cwd-artikli", meta_line(json!(format!("{cwd}/./y/..//")), json!({}))),
        ("cwd-goreli", meta_line(json!("work/p1"), json!({}))),
        ("cwd-bos", meta_line(json!(""), json!({}))),
        ("cwd-null", meta_line(Value::Null, json!({}))),
        ("cwd-sayi", meta_line(json!(5), json!({}))),
        ("cwd-yok", format!("{}\n", json!({"type": "session_meta", "payload": {"id": "x"}}))),
        ("payload-bos", format!("{}\n", json!({"type": "session_meta", "payload": {}}))),
        ("payload-null", format!("{}\n", json!({"type": "session_meta", "payload": null}))),
        ("payload-yok", format!("{}\n", json!({"type": "session_meta"}))),
        ("tur-baska", format!("{}\n", json!({"type": "response_item", "payload": {"cwd": cwd}}))),
        ("ikinci-satir", format!("{{}}\n{}", own)),
        ("bos-ilk", format!("\n{own}")),
        ("bozuk", "{bozuk\n".into()),
        ("bos-dosya", String::new()),
        ("sonsuz", own.trim_end().to_string()),
        ("crlf", own.replace('\n', "\r\n")),
        ("cr", format!("{}\r{{}}\r", own.trim_end())),
        ("uzun", meta_line(json!(cwd), json!({"instructions": "y".repeat(300_000)}))),
        ("bom", format!("\u{feff}{own}")),
    ];
    for (id, body) in lines {
        let c = B::new(&format!("codex-satir-{id}")).at(named("1", U1), body, T0);
        let c = codex_queries(b, c, &[], &[U1]);
        b.push(c);
    }
    // dizin derinliği, gizli adlar, kimlik biçimi, dizin yerinde dosya
    let c = B::new("codex-glob")
        .at("home/.codex/sessions/2026/11/ust.jsonl", own.clone(), T0 + 90)
        .at("home/.codex/sessions/2026/11/23/alt/derin.jsonl", own.clone(), T0 + 91)
        .at("home/.codex/sessions/.gizli/11/23/rollout-a-01234567-89ab-cdef-0123-456789abcdef.jsonl", own.clone(), T0 + 92)
        .at(format!("{ROLL}/.rollout-{U2}.jsonl"), own.clone(), T0 + 93)
        .at(format!("{ROLL}/rollout-{U2}.json"), own.clone(), T0 + 94)
        .fx(Fx::Dir(format!("{ROLL}/rollout-dizin-{U2}.jsonl"), 0o755))
        .fx(Fx::File("home/.codex/sessions/2027".into(), b"dosya".to_vec(), 0o644))
        .at(format!("{ROLL}/rollout-kisa-0123.jsonl"), meta_line(json!(cwd), json!({"id": "kisa"})), T0 + 1)
        .at(format!("home/.codex/sessions/a/b/c/rollout-{U1}.jsonl"), own.clone(), T0 + 2);
    let c = codex_queries(b, c, &[], &[U1, U2, "kisa-0123", "0123"]);
    b.push(c);
    // eşit zaman ve çok sayıda dosya; sınır dışındaki uygun dosya görülmez
    let mut c = B::new("codex-esit");
    for n in ["c", "a", "b"] {
        c = c.at(format!("{ROLL}/{n}.jsonl"), meta_line(json!(cwd), json!({"id": n})), T0);
    }
    let c = codex_queries(b, c, &["a"], &["a", "b"]);
    b.push(c);
    for extra in [MAX_ROLLOUT_SCAN - 1, MAX_ROLLOUT_SCAN] {
        let mut c = B::new(&format!("codex-sinir-{extra}")).at(named("eski", U1), own.clone(), T0);
        for i in 0..extra {
            c = c.at(format!("{ROLL}/n{i}.jsonl"), meta_line(json!("/baska"), json!({})), T0 + 10);
        }
        let c = codex_queries(b, c, &[], &[]);
        b.push(c);
    }
}

// ----------------------------------------------------------------------------------------------------- agy, copilot

fn agy_cases(b: &mut Build<'_>) {
    let cwd = b.cwd();
    let sids = r#"{"inst":"own","held":"held-1","bos":"","gone":"yok","mutlak":"/yok/x"}"#;
    let names = ["", "inst", "held", "sayi", "bos", "gone", "mutlak", "unlearned"];
    let queries = |mut c: B| {
        for name in names {
            c = c.q(json!({"f": "resolve", "cli": "agy", "cwd": cwd, "name": name, "in_use": ["held-1", "tutulan"]}));
            c = c.q(json!({"f": "stopped", "cli": "agy", "cwd": cwd, "name": name}));
        }
        c
    };
    let cache = |v: Value| json!({ cwd.clone(): v }).to_string();
    let caches: Vec<(&str, Option<String>)> = vec![
        ("yok", None),
        ("temel", Some(cache(json!("c1")))),
        ("kirpik", Some(cache(json!("  c1 \n")))),
        ("bos", Some(cache(json!("   ")))),
        ("tutulan", Some(cache(json!("tutulan")))),
        ("tutulan-kirpik", Some(cache(json!(" tutulan ")))),
        ("sayi", Some(cache(json!(5)))),
        ("sifir", Some(cache(json!(0)))),
        ("null", Some(cache(Value::Null))),
        ("baska-cwd", Some(r#"{"/baska":"c1"}"#.into())),
        ("liste", Some("[1]".into())),
        ("bozuk", Some("{bozuk".into())),
        ("bos-dosya", Some(String::new())),
        ("bom", Some(format!("\u{feff}{}", cache(json!("c1"))))),
    ];
    for (id, body) in caches {
        let mut c = B::new(&format!("agy-onbellek-{id}"));
        if let Some(body) = body {
            c = c.raw(AGY_CACHE, body);
        }
        let c = queries(c);
        b.push(c);
    }
    for (id, doc) in [("tam", sids.to_string()), ("liste", "[1]".into()), ("bozuk", "{x".into()), ("bos", String::new())] {
        let c = B::new(&format!("agy-ogrenilen-{id}"))
            .raw("state/agy_sids.json", doc)
            .raw(AGY_CACHE, cache(json!("c1")))
            .raw(format!("{AGY_DIR}/own.db"), "")
            .raw(format!("{AGY_DIR}/held-1.db"), "")
            .fx(Fx::Dir(format!("{AGY_DIR}/yok.db"), 0o755));
        let c = queries(c);
        b.push(c);
    }
    // artıklı cwd: ham anahtar yoksa normalleştirilmiş anahtar
    let messy = format!("{cwd}/./z/..");
    for (id, body) in [
        ("norm", cache(json!("c1"))),
        ("ham", json!({ messy.clone(): "ham", cwd.clone(): "norm" }).to_string()),
        ("ham-bos", json!({ messy.clone(): "", cwd.clone(): "norm" }).to_string()),
        ("ham-sayi", json!({ messy.clone(): 3, cwd.clone(): "norm" }).to_string()),
    ] {
        let c = B::new(&format!("agy-cwd-{id}"))
            .raw(AGY_CACHE, body)
            .q(json!({"f": "resolve", "cli": "agy", "cwd": messy}));
        b.push(c);
    }
    // konuşma dizini taraması ve tek yeni kimlik
    let files = ["a.db", "a.db-wal", "a.db-shm", "b.db-journal", "c.dbx", "d.db.db", "e.sqlite", ".gizli.db", ".db", "ğ.db", "f.db"];
    let mut c = B::new("agy-konusmalar").fx(Fx::Dir(format!("{AGY_DIR}/klasor.db"), 0o755));
    for f in files {
        c = c.raw(format!("{AGY_DIR}/{f}"), "");
    }
    let all = ["a", "b", "c", "d", "f", "ğ", "klasor"];
    c = c.q(json!({"f": "snapshot", "cli": "agy", "cwd": cwd}));
    c = c.q(json!({"f": "discover", "cli": "agy", "cwd": cwd, "before": null}));
    c = c.q(json!({"f": "discover", "cli": "agy", "cwd": cwd, "before": all}));
    c = c.q(json!({"f": "discover", "cli": "agy", "cwd": cwd, "before": &all[1..]}));
    c = c.q(json!({"f": "discover", "cli": "agy", "cwd": cwd, "before": &all[2..]}));
    c = c.q(json!({"f": "discover", "cli": "agy", "cwd": cwd, "before": ["silinen", "a", "b", "c", "d", "f", "ğ"]}));
    b.push(c);
    let mut c = B::new("agy-dizin-yok").q(json!({"f": "snapshot", "cli": "agy", "cwd": cwd}));
    c = c.q(json!({"f": "discover", "cli": "agy", "cwd": cwd, "before": []}));
    b.push(c);
    for (i, (known, sid, name)) in [
        (json!({}), "s", "a"),
        (json!({"a": "s"}), "s", "a"),
        (json!({"b": "s"}), "s", "a"),
        (json!({"a": "s", "b": "s"}), "s", "a"),
        (json!({"b": "t"}), "s", "a"),
        (json!({"b": 1}), "1", "a"),
        (json!({"b": null}), "", "a"),
    ]
    .into_iter()
    .enumerate()
    {
        let c = B::new(&format!("agy-sahipli-{i}")).q(json!({"f": "claimed", "known": known, "sid": sid, "name": name}));
        b.push(c);
    }
    // yazım dizileri: aynı değer, yeni ad, güncelleme, nesne olmayan/bozuk belge
    for (id, doc) in [
        ("yok", None),
        ("dolu", Some(r#"{"z":"1","a":"2","sayi":7}"#)),
        ("liste", Some("[1]")),
        ("bozuk", Some("{bozuk")),
        ("unicode", Some(r#"{"ğ":"ü 😀"}"#)),
    ] {
        let mut c = B::new(&format!("agy-yaz-{id}"));
        if let Some(d) = doc {
            c = c.raw("state/agy_sids.json", d);
        }
        for (name, sid) in [("a", "2"), ("a", "2"), ("yeni", "n"), ("a", "3"), ("sayi", "7"), ("ğ", "ü 😀"), ("", "")] {
            c = c.q(json!({"f": "remember", "name": name, "sid": sid}));
        }
        b.push(c);
    }
}

fn sessions_db(rows: &[(Sql, Sql)]) -> Vec<u8> {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("e.db");
    rusqlite::Connection::open(&path).unwrap().execute_batch("CREATE TABLE x (a)").unwrap();
    with_sessions(&fs::read(path).unwrap(), rows)
}

fn copilot_cases(b: &mut Build<'_>) {
    let cwd = b.cwd();
    let t = |s: &str| Sql::Text(s.into());
    let queries = |mut c: B, held: &[&str]| {
        c = c.q(json!({"f": "resolve", "cli": "copilot", "cwd": cwd}));
        c.q(json!({"f": "resolve", "cli": "copilot", "cwd": cwd, "in_use": held, "name": "x"}))
    };
    let messy = format!("{cwd}//./k/..");
    // satır sırası = `updated_at` artan
    let dbs: Vec<(&str, Vec<(Sql, Sql)>)> = vec![
        ("temel", vec![(t("eski"), t(&cwd)), (t("yeni"), t(&cwd)), (t("baska"), t("/baska"))]),
        ("artikli", vec![(t("a"), t(&messy)), (t("g"), t("work/p1"))]),
        ("bos-cwd", vec![(t("eski"), t(&cwd)), (t("n"), Sql::Null), (t("b"), t("")), (t("s"), Sql::Integer(0))]),
        ("cwd-tipleri", vec![(t("eski"), t(&cwd)), (t("i"), Sql::Integer(5)), (t("r"), Sql::Real(1.5)), (t("bl"), Sql::Blob(b"x".to_vec()))]),
        ("bos-kimlik", vec![(t("eski"), t(&cwd)), (t(""), t(&cwd))]),
        ("null-kimlik", vec![(t("eski"), t(&cwd)), (Sql::Null, t(&cwd))]),
        ("eslesme-yok", vec![(t("a"), t("/baska"))]),
        ("tablo-bos", vec![]),
    ];
    for (id, rows) in dbs {
        let c = B::new(&format!("copilot-{id}")).raw(COPILOT_DB, sessions_db(&rows));
        let c = queries(c, &["yeni"]);
        b.push(c);
    }
    for extra in [copilot::RESUME_SCAN_LIMIT - 1, copilot::RESUME_SCAN_LIMIT] {
        let mut rows = vec![(t("eski"), t(&cwd))];
        rows.extend((0..extra).map(|i| (t(&format!("n{i}")), t("/baska"))));
        let c = B::new(&format!("copilot-sinir-{extra}")).raw(COPILOT_DB, sessions_db(&rows));
        let c = queries(c, &[]);
        b.push(c);
    }
    for (id, body) in [("bozuk", b"not a database at all, definitely not".to_vec()), ("bos", Vec::new())] {
        let c = queries(B::new(&format!("copilot-db-{id}")).raw(COPILOT_DB, body), &[]);
        b.push(c);
    }
    let c = queries(B::new("copilot-db-yok"), &[]);
    b.push(c);
}

fn dispatch_cases(b: &mut Build<'_>) {
    let cwd = b.cwd();
    let mut c = B::new("diger");
    for cli in ["shell", "ucli", "codex", "copilot", "claude", "agy"] {
        for name in ["", "inst"] {
            c = c.q(json!({"f": "resolve", "cli": cli, "cwd": cwd, "name": name}));
            c = c.q(json!({"f": "stopped", "cli": cli, "cwd": cwd, "name": name}));
        }
        c = c.q(json!({"f": "snapshot", "cli": cli, "cwd": cwd}));
        c = c.q(json!({"f": "discover", "cli": cli, "cwd": cwd, "before": []}));
    }
    c = c.q(json!({"f": "constants"}));
    b.push(c);
    let live = json!([["a", "s1"], ["b", null], ["", "s3"], ["c", ""], ["ben", "s5"], ["ben20261108", "s6"], ["d", "s1"]]);
    let mut c = B::new("tutulan");
    for name in ["ben", "", "yok", "a"] {
        c = c.q(json!({"f": "held", "name": name, "live": live}));
    }
    c = c.q(json!({"f": "held", "name": "ben", "live": []})).q(json!({"f": "held", "name": "ben", "live": null}));
    b.push(c);
}

/// Python'un istisna attığı ya da başka tip döndürdüğü girdiler: Rust yalnız o adayı atlar.
fn divergences(b: &mut Build<'_>) {
    let (cwd, dir) = (b.cwd(), b.dir());
    let resolve = |cli: &str, name: &str| json!({"f": "resolve", "cli": cli, "cwd": cwd, "name": name});
    let own = meta_line(json!(cwd), json!({}));
    let good = format!("{ROLL}/rollout-1-{U1}.jsonl");
    let newer = format!("{ROLL}/rollout-2-{U2}.jsonl");
    for (id, body) in [
        ("codex-utf8", vec![0xff, b'\n']),
        ("codex-nesne-degil", b"[1]\n".to_vec()),
        ("codex-payload-liste", b"{\"type\":\"session_meta\",\"payload\":[1]}\n".to_vec()),
        ("codex-utf8-sonraki-satir", [own.replace(U1, U2).into_bytes(), vec![0xff, b'\n']].concat()),
    ] {
        let c = B::new(&format!("sapma-{id}"))
            .at(good.clone(), own.clone(), T0)
            .at(newer.clone(), body, T0 + 5)
            .q(resolve("codex", ""));
        let want = if id == "codex-utf8-sonraki-satir" { U2 } else { U1 };
        b.diverges(c, "ilk okuma parçasında bozuk UTF-8 / nesne olmayan satır ya da payload: Python istisna, Rust yalnız o satırı değerlendirir", json!([want]));
    }
    for (id, v) in [("sayi", json!(7)), ("liste", json!(["x"]))] {
        let c = B::new(&format!("sapma-codex-kimlik-{id}"))
            .at(format!("{ROLL}/adsiz.jsonl"), meta_line(json!(cwd), json!({"id": v})), T0)
            .q(resolve("codex", ""));
        b.diverges(c, "metin olmayan kimlik: Python sayıyı döndürür / listede istisna, Rust 'yok'", json!([null]));
    }
    // `[`: Python sid'i glob deseni sayar
    let c = B::new("sapma-codex-joker")
        .at(good.clone(), own.clone(), T0)
        .at(newer.clone(), meta_line(json!("/baska"), json!({})), T0 + 5)
        .q(json!({"f": "rollout", "cwd": cwd, "sid": "[0-9]"}));
    let want = b.abs(&good);
    b.diverges(c, "joker taşıyan sid: Python glob deseni sayar (başka dosya), Rust ad eşleşmesi yapmaz", json!([want]));
    let c = B::new("sapma-agy-onbellek-utf8").raw(AGY_CACHE, vec![b'{', 0xff, b'}']).q(resolve("agy", ""));
    b.diverges(c, "UTF-8 olmayan cwd önbelleği: Python istisna, Rust 'yok'", json!([null]));
    let c = B::new("sapma-agy-kimlik-sayi")
        .raw("state/agy_sids.json", r#"{"inst":7}"#)
        .raw(AGY_CACHE, json!({ cwd.clone(): "c1" }).to_string())
        .q(resolve("agy", "inst"));
    b.diverges(c, "metin olmayan öğrenilen kimlik: Python döndürür, Rust cwd önbelleğine düşer", json!(["c1"]));
    let c = B::new("sapma-claude-dizin-dosya")
        .raw(dir.clone(), "dosya")
        .q(resolve("claude", ""))
        .q(json!({"f": "latest", "cwd": cwd}));
    b.diverges(c, "proje dizini yerinde dosya: Python `NotADirectoryError`, Rust 'yok'", json!([null, null]));
    let c = B::new("sapma-claude-uzun-sid").at(format!("{dir}/z.jsonl"), "", T0).q(json!({"f": "jsonl", "cwd": cwd, "sid": "s".repeat(300)}));
    b.diverges(c, "dosya adı sınırını aşan sid: Python `is_file` `OSError`, Rust 'yok' (TBD#365: tahmin yok)", json!([null]));
    let c = B::new("sapma-kayit-sonsuz-pid")
        .raw("home/.claude/sessions/42.json", r#"{"pid":Infinity,"sessionId":"s","procStart":"777"}"#)
        .q(json!({"f": "session_sid", "pid": 42}));
    b.diverges(c, "sonsuz pid: Python `OverflowError` yakalamaz, Rust 'yok'", json!([null]));
    let c = B::new("sapma-meta-derin")
        .raw("work/m.jsonl", format!("{{\"customTitle\":\"t\",\"d\":{}{}}}\n", "[".repeat(600), "]".repeat(600)))
        .q(json!({"f": "meta", "path": b.abs("work/m.jsonl")}));
    b.diverges(c, "512'den derin satır: Python okur, Rust atlar", json!([[null, null]]));
    let c = B::new("sapma-copilot-kimlik-sayi")
        .raw(COPILOT_DB, sessions_db(&[(Sql::Integer(7), Sql::Text(cwd.clone()))]))
        .q(resolve("copilot", ""));
    b.diverges(c, "metin olmayan oturum kimliği: Python sayıyı döndürür, Rust 'yok'", json!([null]));
}

// ------------------------------------------------------------------------------------------------------------- koşum

/// `agy_sids` belgesi bellekte: yazım dizilerinde dönüş karşılaştırılır.
struct MemStore(RefCell<Option<Py>>);

impl AgySidStore for MemStore {
    fn load(&self) -> Option<Py> {
        self.0.borrow().clone()
    }
    fn locked(&self, f: &mut dyn FnMut() -> Result<bool, String>) -> Result<bool, String> {
        f()
    }
    fn save(&self, doc: &Py) -> Result<(), String> {
        *self.0.borrow_mut() = Some(doc.clone());
        Ok(())
    }
}

fn rs_resume(e: &Env, c: &Case) -> RsOut {
    let settings = e.settings();
    let paths = e.paths();
    let probe = FsProbe::new(e, c);
    let clock = cops_providers::bg_work::Clock { now: 0.0, utc_offset_secs: 0 };
    let live = Live { settings: &settings, paths: &paths, probe: &probe, clock };
    let cache = MetaCache::default();
    let doc = format!("{}/agy_sids.json", e.state);
    let store = MemStore(RefCell::new(fs::read_to_string(&doc).ok().and_then(|t| Py::parse(&t))));
    let queries = c.args["queries"].as_array().unwrap();
    let set = |v: &Value| -> BTreeSet<String> { strs(Some(v)).into_iter().collect() };
    let out: Vec<Value> = queries
        .iter()
        .map(|q| {
            let s = |k: &str| q.get(k).and_then(Value::as_str);
            let cwd = s("cwd").unwrap_or("");
            let name = s("name").unwrap_or("");
            let cli = Cli::parse(s("cli").unwrap_or(""));
            match s("f").unwrap() {
                "resolve" => json!(live.resolve_resume_id(cli, cwd, &set(&q["in_use"]), name)),
                "stopped" => json!(live.sid_for_stopped_session(cli, cwd, name, &cache)),
                "jsonl" => json!(live.jsonl_path_for(cwd, s("sid"))),
                "latest" => json!(live.find_latest_jsonl(cwd)),
                "rollout" => json!(live.codex_rollout_path(cwd, s("sid"))),
                "session_sid" => json!(q["pid"].as_i64().and_then(|p| live.session_file_sid(p))),
                "meta" => {
                    let m = live.jsonl_meta(s("path").unwrap());
                    json!([m.title, m.cwd])
                }
                "chat_rows" => json!(live.has_chat_rows(s("path").unwrap())),
                "snapshot" => json!(live.snapshot_for_live_sid(cli)),
                "discover" => {
                    let before = (!q["before"].is_null()).then(|| set(&q["before"]));
                    json!(live.discover_live_sid(cli, before.as_ref()))
                }
                "held" => {
                    let rows = q["live"].as_array().map(|a| {
                        a.iter()
                            .map(|r| LiveSession { name: r[0].as_str().unwrap(), sid: r[1].as_str() })
                            .collect::<Vec<_>>()
                    });
                    json!(ids_held_by_others(name, rows.as_deref()))
                }
                "claimed" => {
                    let known = Py::parse(&q["known"].to_string()).unwrap();
                    json!(agy_resume::sid_claimed_by_other(&known, s("sid").unwrap(), name))
                }
                "remember" => {
                    agy_resume::remember_agy_sid(&store, name, s("sid").unwrap(), false).unwrap();
                    match store.load() {
                        Some(d @ Py::Object(_)) => d.to_value(),
                        _ => json!({}),
                    }
                }
                "constants" => json!([META_HEAD_LINES, RESUME_SCAN_LIMIT, STUB_MAX_BYTES, META_CACHE_MAX,
                    MAX_ROLLOUT_SCAN, copilot::RESUME_SCAN_LIMIT,
                    [paths.agy_conversations_cache(), paths.agy_conversations_dir(), paths.claude_sessions_dir(),
                     paths.codex_sessions_dir()]]),
                other => panic!("bilinmeyen sorgu: {other}"),
            }
        })
        .collect();
    if queries.iter().any(|q| q["f"] == "remember") {
        let _ = fs::remove_file(doc);
    }
    RsOut::ret(Value::Array(out))
}

pub fn run() {
    let mut r = Runner::new();
    let (cases, times, expect) = {
        let mut b = Build { e: &r.e, cases: Vec::new(), times: HashMap::new(), expect: HashMap::new() };
        claude_cases(&mut b);
        meta_cases(&mut b);
        session_file_cases(&mut b);
        codex_cases(&mut b);
        agy_cases(&mut b);
        copilot_cases(&mut b);
        dispatch_cases(&mut b);
        divergences(&mut b);
        (b.cases, b.times, b.expect)
    };
    r.run_prepared(
        cases,
        &[],
        |e, c| {
            for (rel, secs, ns) in times.get(&c.id).into_iter().flatten() {
                let at = std::time::UNIX_EPOCH + std::time::Duration::new(*secs as u64, *ns);
                let file = fs::File::options().append(true).open(format!("{}/{rel}", e.root)).unwrap();
                file.set_modified(at).unwrap();
            }
        },
        |e, c| {
            let out = rs_resume(e, c);
            if let Some(want) = expect.get(&c.id) {
                assert_eq!(&out.ret, want, "[{}] güvenli sonuç", c.id);
            }
            out
        },
    );
    r.finish("resume");
}
