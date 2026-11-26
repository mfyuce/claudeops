//! Aile (G2): sohbet geçmişi okuyucuları (`last_exchange`, `full_history`, `last_message_role`, `extra_file_roots`,
//! `read_chat_history`). Senaryolar `py/tests/test_{agy_compaction_view,agy_last_exchange,chat_compaction_view,
//! stopped_session_chat,ucli_last_exchange_pairing,ucli_state_dir}.py` + boş/bozuk/kısmi/Unicode/yanlış tip sınırları ve
//! rastgele girdiler. Tüm veri SENTETİK ve geçici HOME altında.
//!
//! Bilinen ayrışma vakalarında (`chat-sapma-`) Rust'ın güvenli sonucu `expect` ile ayrıca doğrulanır.

use crate::common::*;
use crate::fam_live::with_sessions;
use crate::fam_bg::Rng;
use cops_providers::bg_work::Clock;
use cops_providers::pyjson::Py;
use cops_providers::ucli::state_dir_for;
use cops_providers::{ChatTurn, Cli, Live};
use rusqlite::types::Value as Sql;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::fs;

const CLAUDE_DB_SID: &str = "s1";
const CODEX_FILE: &str = "home/.codex/sessions/2026/11/23/rollout-x-s1.jsonl";
const COPILOT_DB: &str = "home/.copilot/session-store.db";
const AGY_DIR: &str = "home/.gemini/antigravity-cli/conversations";

const AGY_CACHE: &str = "home/.gemini/antigravity-cli/cache/last_conversations.json";

struct Build<'a> {
    e: &'a Env,
    cases: Vec<Case>,
    /// vaka kimliği -> Rust sonucunun beklenen alanları
    expect: HashMap<String, Value>,
}

impl Build<'_> {
    fn cwd(&self) -> String {
        format!("{}/work/p1", self.e.root)
    }

    fn case(&self, id: &str, cli: &str, sid: Option<&str>) -> Case {
        Case::new(format!("chat-{id}"), "chat", json!({"cli": cli, "cwd": self.cwd(), "sid": sid}))
    }

    fn push(&mut self, c: Case) {
        self.cases.push(c);
    }

    /// Bilinen ayrışma: Rust sonucu `expect` alanlarını taşımalı.
    fn diverges(&mut self, c: Case, why: &'static str, expect: Value) {
        self.expect.insert(c.id.clone(), expect);
        self.push(c.known(why));
    }

    /// Eskiden ayrışan, artık iki tarafta eşit vaka: sonuç `expect` ile de sabitlenir.
    fn agrees(&mut self, c: Case, expect: Value) {
        self.expect.insert(c.id.clone(), expect);
        self.push(c);
    }

    fn claude_rel(&self, file: &str) -> String {
        let encoded: String = self.cwd().chars().map(|c| if c.is_ascii_alphanumeric() { c } else { '-' }).collect();
        format!("home/.claude/projects/{encoded}/{file}")
    }

    fn claude(&self, id: &str, body: impl AsRef<[u8]>) -> Case {
        let file = Fx::File(self.claude_rel("s1.jsonl"), body.as_ref().to_vec(), 0o600);
        self.case(&format!("claude-{id}"), "claude", Some(CLAUDE_DB_SID)).file(file)
    }

    fn codex(&self, id: &str, body: impl AsRef<[u8]>) -> Case {
        let file = Fx::File(CODEX_FILE.into(), body.as_ref().to_vec(), 0o600);
        self.case(&format!("codex-{id}"), "codex", Some("s1")).file(file)
    }

    /// Eski (`<cwd>/.ucli/chat`) dizinde `s1.jsonl`.
    fn ucli(&self, id: &str, body: impl AsRef<[u8]>) -> Case {
        let file = Fx::File("work/p1/.ucli/chat/s1.jsonl".into(), body.as_ref().to_vec(), 0o644);
        self.case(&format!("ucli-{id}"), "ucli", Some("s1")).file(file)
    }

    fn agy(&self, id: &str, db: Vec<u8>) -> Case {
        let file = Fx::File(format!("{AGY_DIR}/abc.db"), db, 0o600);
        self.case(&format!("agy-{id}"), "agy", Some("abc")).file(file)
    }

    fn copilot(&self, id: &str, db: Vec<u8>) -> Case {
        let file = Fx::File(COPILOT_DB.into(), db, 0o600);
        self.case(&format!("copilot-sohbet-{id}"), "copilot", Some("s1")).file(file)
    }
}

fn lines<S: AsRef<str>>(rows: &[S]) -> String {
    rows.iter().map(|r| format!("{}\n", r.as_ref())).collect()
}

fn turns(pairs: &[(&str, &str)]) -> Value {
    pairs.iter().map(|(r, t)| json!({"role": r, "text": t})).collect()
}

// ----------------------------------------------------------------------------------------------------------- claude

fn msg(t: &str, content: Value, extra: Value) -> String {
    let mut row = map(json!({"type": t, "message": {"content": content}}));
    row.extend(map(extra));
    Value::Object(row).to_string()
}

fn claude_rows() -> Vec<String> {
    let u = |c: Value| msg("user", c, json!({}));
    let a = |c: Value| msg("assistant", c, json!({}));
    let text = |t: &str| json!({"type": "text", "text": t});
    vec![
        u(json!("eski soru")),
        a(json!("eski cevap")),
        json!({"type": "system", "subtype": "compact_boundary", "compactMetadata": {"trigger": "auto", "preTokens": 261105}})
            .to_string(),
        msg("user", json!("This session is being continued..."), json!({"isCompactSummary": true})),
        u(json!("yeni soru ğüşİ 😀")),
        a(json!([text("bir"), {"type": "tool_use", "name": "x"}, text(""), text("iki\n\u{2028}üç")])),
        u(json!([{"type": "tool_result", "content": "çıktı"}])),
        a(json!([{"type": "tool_use", "name": "Bash"}])),
    ]
}

fn claude_cases(b: &mut Build<'_>) {
    let all = claude_rows();
    let c = b.claude("temel", lines(&all));
    b.push(c);
    // her önek: son satır türü değiştikçe eşleme
    for n in 0..all.len() {
        let c = b.claude(&format!("onek-{n}"), lines(&all[..n]));
        b.push(c);
    }
    let c = b.case("claude-dosya-yok", "claude", Some("s1"));
    b.push(c);
    let c = b.case("claude-sid-yok", "claude", None);
    b.push(c);
    let file = Fx::File(b.claude_rel("baska.jsonl"), lines(&all).into_bytes(), 0o600);
    for (id, sid) in [("en-yeni", None), ("en-yeni-bos-sid", Some("")), ("en-yeni-yanlis-sid", Some("yok"))] {
        let c = b.case(&format!("claude-{id}"), "claude", sid).file(file.clone());
        b.push(c);
    }
    let c = b.case("claude-dizin-dosya-yerinde", "claude", Some("s1")).file(Fx::Dir(b.claude_rel("s1.jsonl"), 0o755));
    b.push(c);
    let c = b.case("claude-izinsiz", "claude", Some("s1")).file(Fx::File(
        b.claude_rel("s1.jsonl"),
        lines(&all).into_bytes(),
        0o000,
    ));
    b.push(c);

    let q = msg("user", json!("soru"), json!({}));
    let r = msg("assistant", json!("cevap"), json!({}));
    // bayrakların doğruluk değeri
    for (i, v) in [json!(true), json!(false), json!(0), json!(1), json!(""), json!("no"), json!([]), json!([0]), json!({}), Value::Null]
        .into_iter()
        .enumerate()
    {
        for key in ["isSidechain", "isMeta", "isCompactSummary"] {
            let flagged = |t: &str, c: &str| msg(t, json!(c), json!({ key: v.clone() }));
            let body = lines(&[q.clone(), r.clone(), flagged("user", "işaretli soru"), flagged("assistant", "işaretli cevap")]);
            let c = b.claude(&format!("bayrak-{key}-{i}"), body);
            b.push(c);
        }
    }
    // içerik biçimleri (kullanıcı ve asistan)
    let contents = [
        json!(""),
        json!("   "),
        json!("\u{3000}\u{a0}\u{1c}"),
        json!("\u{200b}"),
        json!([]),
        json!([{}]),
        json!([{"type": "image"}]),
        json!([{"type": "text"}]),
        json!([{"type": "text", "text": ""}]),
        json!([{"type": "text", "text": " "}]),
        json!([{"type": "text", "text": 0}]),
        json!([{"type": "text", "text": null}]),
        json!([{"type": "Text", "text": "büyük"}]),
        json!([{"type": 5, "text": "sayı tür"}]),
        json!(["düz dize", 3, null, {"type": "text", "text": "son"}]),
        json!([{"type": "text", "text": "a"}, {"type": "tool_result"}]),
        json!(5),
        json!(true),
        Value::Null,
        json!({"type": "text", "text": "sözlük"}),
    ];
    for (i, content) in contents.iter().enumerate() {
        let body = lines(&[q.clone(), msg("user", content.clone(), json!({})), msg("assistant", content.clone(), json!({}))]);
        let c = b.claude(&format!("icerik-{i}"), body);
        b.push(c);
        let body = lines(&[msg("user", content.clone(), json!({"isCompactSummary": true})), r.clone()]);
        let c = b.claude(&format!("ozet-{i}"), body);
        b.push(c);
    }
    // sınır işareti meta biçimleri
    let metas = [
        json!({}),
        Value::Null,
        json!(0),
        json!(""),
        json!([]),
        json!(false),
        json!({"trigger": "manual"}),
        json!({"preTokens": 0}),
        json!({"trigger": null, "preTokens": null}),
        json!({"trigger": true, "preTokens": false}),
        json!({"trigger": 1.5, "preTokens": -0.0}),
        json!({"trigger": 1e300, "preTokens": 1.5e-7}),
        json!({"trigger": ["a", 1, null], "preTokens": {"k": "v'q", "n": 2.0}}),
        json!({"trigger": "ğ, \"x\"", "preTokens": "261105"}),
    ];
    for (i, meta) in metas.iter().enumerate() {
        let row = json!({"type": "system", "subtype": "compact_boundary", "compactMetadata": meta}).to_string();
        let c = b.claude(&format!("sinir-{i}"), lines(&[q.clone(), r.clone(), row]));
        b.push(c);
    }
    for (id, row) in [
        ("sinir-meta-yok", r#"{"type":"system","subtype":"compact_boundary"}"#),
        ("sinir-nan", r#"{"type":"system","subtype":"compact_boundary","compactMetadata":{"trigger":NaN,"preTokens":-Infinity}}"#),
        ("sinir-buyuk-sayi", r#"{"type":"system","subtype":"compact_boundary","compactMetadata":{"preTokens":123456789012345678901234567890}}"#),
        ("sinir-baska-altur", r#"{"type":"system","subtype":"x"}"#),
        ("sinir-sidechain", r#"{"type":"system","subtype":"compact_boundary","isSidechain":true}"#),
        ("tur-sayi", r#"{"type":5,"message":{"content":"x"}}"#),
        ("tur-yok", r#"{"message":{"content":"x"}}"#),
        ("mesaj-yok", r#"{"type":"assistant"}"#),
        ("kullanici-mesaj-yok", r#"{"type":"user"}"#),
        ("yinelenen-anahtar", r#"{"type":"user","type":"assistant","message":{"content":"a","content":"b"}}"#),
        ("nan-alan", r#"{"type":"assistant","x":NaN,"message":{"content":"nan'lı"}}"#),
        ("vekil-cifti", r#"{"type":"assistant","message":{"content":"😀"}}"#),
    ] {
        let c = b.claude(id, lines(&[q.as_str(), row]));
        b.push(c);
    }
    // satır biçimi
    let body = lines(&[q.clone(), r.clone()]);
    for (id, text) in [
        ("bos", String::new()),
        ("bos-satirlar", format!("\n\n  \n{body}\n\n")),
        ("crlf", body.replace('\n', "\r\n")),
        ("tek-cr", body.replace('\n', "\r")),
        ("son-satirsiz", body.trim_end().to_string()),
        ("yarim-son-satir", format!("{body}{{\"type\":\"assistant\",\"mess")),
        ("bom", format!("\u{feff}{body}")),
        ("bozuk-satirlar", format!("çöp\n{{\n{body}}}\nNone\n{{'type':'user'}}\n")),
        ("kirpma", format!("\u{3000}\u{1c} \t{q}\u{a0}\u{c}\n{r}\u{2028}\n")),
        ("ayni-satirda-iki", format!("{q}{r}\n{q} {r}\n")),
        ("ayirac-satir-degil", format!("{q}\u{2028}{r}\n{q}\u{85}{r}\n{q}\u{b}{r}\n")),
        ("nul", format!("{q}\n\u{0}\n{r}\n")),
    ] {
        let c = b.claude(&format!("satir-{id}"), text);
        b.push(c);
    }
    let long: Vec<String> = (0..3000)
        .map(|i| msg(if i % 2 == 0 { "user" } else { "assistant" }, json!(format!("tur {i} {}", "ğ".repeat(i % 50))), json!({})))
        .collect();
    let c = b.claude("uzun", lines(&long));
    b.push(c);
    let c = b.claude("dev-satir", lines(&[q.clone(), msg("assistant", json!("x".repeat(3_000_000)), json!({}))]));
    b.push(c);
    // her karakter sınırında kesilmiş dosya (yazım sürerken okuma)
    let full = lines(&all);
    let cuts: Vec<usize> = full.char_indices().map(|(i, _)| i).step_by(11).collect();
    for cut in cuts {
        let c = b.claude(&format!("kesik-{cut}"), &full[..cut]);
        b.push(c);
    }
}

fn claude_divergences(b: &mut Build<'_>) {
    let q = msg("user", json!("soru"), json!({}));
    let r = msg("assistant", json!("cevap"), json!({}));
    let ok = json!({"last_exchange": {"user": "soru", "assistant": "cevap"}, "full_history": turns(&[("user", "soru"), ("assistant", "cevap")])});
    for (id, bad) in [
        ("dizi-satir", "[1,2]".to_string()),
        ("dize-satir", "\"x\"".to_string()),
        ("sayi-satir", "5".to_string()),
        ("null-satir", "null".to_string()),
    ] {
        let c = b.claude(&format!("sekil-{id}"), lines(&[q.as_str(), r.as_str(), bad.as_str()]));
        b.agrees(c, ok.clone());
    }
    for (id, bad) in [
        ("mesaj-null", r#"{"type":"user","message":null}"#),
        ("mesaj-metin", r#"{"type":"user","message":"x"}"#),
        ("mesaj-dizi", r#"{"type":"user","message":[1]}"#),
        ("ozet-mesaj-null", r#"{"type":"user","isCompactSummary":true,"message":null}"#),
    ] {
        let c = b.claude(&format!("sekil-{id}"), lines(&[q.as_str(), bad, r.as_str()]));
        b.agrees(c, ok.clone());
    }
    for (id, v) in [("sayi", "5"), ("sozluk", r#"{"a":1}"#), ("true", "true")] {
        let bad = format!(r#"{{"type":"assistant","message":{{"content":[{{"type":"text","text":{v}}},{{"type":"text","text":"cevap"}}]}}}}"#);
        let c = b.claude(&format!("sekil-metin-degil-{id}"), lines(&[q.as_str(), bad.as_str()]));
        b.agrees(c, ok.clone());
    }
    let meta = r#"{"type":"system","subtype":"compact_boundary","compactMetadata":"x"}"#;
    let c = b.claude("sekil-meta-metin", lines(&[q.as_str(), r.as_str(), meta]));
    b.agrees(c, json!({"full_history": turns(&[("user", "soru"), ("assistant", "cevap"), ("boundary", ", ")])}));
    // bozuk UTF-8: yazım sürerken çok baytlı karakterin ortasında kesilen dosya
    let mut cut = lines(&[q.as_str(), r.as_str()]).into_bytes();
    cut.extend_from_slice(b"{\"type\":\"assistant\",\"message\":{\"content\":\"\xc4");
    let c = b.claude("sekil-utf8-kesik", cut);
    b.agrees(c, ok.clone());
    let mut mid = format!("{q}\n").into_bytes();
    mid.extend_from_slice(b"\xff\xfe\n");
    mid.extend_from_slice(format!("{r}\n").as_bytes());
    let c = b.claude("sekil-utf8-orta", mid);
    b.agrees(c, ok.clone());
    let deep = format!("{{\"type\":\"x\",\"d\":{}{}}}", "[".repeat(100_000), "]".repeat(100_000));
    let c = b.claude("sekil-derin", lines(&[q.as_str(), r.as_str(), deep.as_str()]));
    b.agrees(c, ok.clone());
    let huge = format!("{{\"type\":\"x\",\"n\":{}}}", "9".repeat(5000));
    let c = b.claude("sekil-dev-sayi", lines(&[q.as_str(), r.as_str(), huge.as_str()]));
    b.agrees(c, ok.clone());
    let summary = msg("user", json!("özet"), json!({"isCompactSummary": true}));
    let c = b.claude("ozet-kullanici-degil", lines(&[q.as_str(), summary.as_str(), r.as_str()]));
    b.agrees(c, json!({"last_exchange": {"user": "soru", "assistant": "cevap"}}));
    let c = b.claude("ozet-yalniz", lines(&[summary.as_str(), r.as_str()]));
    b.agrees(c, json!({"last_exchange": {"user": "", "assistant": "cevap"}}));
    let c = b.claude("mesaj-son-asistan", lines(&[q.as_str(), r.as_str(), r#"{"type":"assistant","message":5}"#]));
    b.agrees(c, json!({"last_exchange": {"user": "soru", "assistant": ""}}));
    let lone = r#"{"type":"assistant","message":{"content":"yarım \ud83d"}}"#;
    let c = b.claude("sapma-vekil", lines(&[q.as_str(), lone]));
    b.diverges(
        c,
        "eşlenmemiş vekil: Python vekili taşır, Rust U+FFFD",
        json!({"last_exchange": {"user": "soru", "assistant": "yarım \u{fffd}"}}),
    );
}

// ------------------------------------------------------------------------------------------------------------ codex

fn codex_msg(role: &str, content: Value) -> String {
    json!({"type": "response_item", "payload": {"type": "message", "role": role, "content": content}}).to_string()
}

fn block(kind: &str, text: &str) -> Value {
    json!({"type": kind, "text": text})
}

fn codex_cases(b: &mut Build<'_>) {
    let user = |t: &str| codex_msg("user", json!([block("input_text", t)]));
    let ai = |t: &str| codex_msg("assistant", json!([block("output_text", t)]));
    let all = vec![
        json!({"type": "session_meta", "payload": {"cwd": "/yok", "id": "s1"}}).to_string(),
        user("<environment_context>\n  <cwd>/x</cwd>\n</environment_context>"),
        user("soru ğ 😀"),
        json!({"type": "response_item", "payload": {"type": "reasoning", "summary": []}}).to_string(),
        ai("ara cevap"),
        codex_msg("developer", json!([block("input_text", "yönerge")])),
        codex_msg("assistant", json!([block("output_text", "a"), block("reasoning", "gizli"), block("input_text", "b")])),
        json!({"type": "event_msg", "payload": {"type": "message", "role": "user", "content": []}}).to_string(),
        user("cevapsız"),
        codex_msg("assistant", json!([])),
    ];
    for n in 0..=all.len() {
        let c = b.codex(&format!("onek-{n}"), lines(&all[..n]));
        b.push(c);
    }
    for (id, sid) in [("sid-yok", None), ("bos-sid", Some("")), ("yanlis-sid", Some("yok"))] {
        let c = b.case(&format!("codex-{id}"), "codex", sid).file(Fx::File(CODEX_FILE.into(), lines(&all).into_bytes(), 0o600));
        b.push(c);
    }
    let q = user("soru");
    let r = ai("cevap");
    let texts = [
        "",
        " ",
        "\u{3000}",
        "  <environment_context>x",
        "\u{1c}\n<environment_context>",
        "x <environment_context>",
        "<Environment_context>",
        "<environment_context",
        "  gerçek soru  ",
    ];
    for (i, t) in texts.iter().enumerate() {
        let c = b.codex(&format!("metin-{i}"), lines(&[q.clone(), r.clone(), user(t), ai(t)]));
        b.push(c);
    }
    let contents = [
        json!("düz dize"),
        Value::Null,
        json!(5),
        json!({"type": "input_text", "text": "x"}),
        json!([block("text", "claude türü")]),
        json!([{"type": "input_text"}, {"type": "output_text", "text": ""}, {"type": "output_text", "text": null}]),
        json!([{"type": ["input_text"], "text": "x"}, "dize", 4]),
        json!([block("input_text", "bir"), block("output_text", "iki")]),
    ];
    for (i, content) in contents.iter().enumerate() {
        let body = lines(&[
            q.clone(),
            r.clone(),
            codex_msg("user", content.clone()),
            codex_msg("assistant", content.clone()),
        ]);
        let c = b.codex(&format!("icerik-{i}"), body);
        b.push(c);
    }
    for (id, row) in [
        ("payload-yok", r#"{"type":"response_item"}"#),
        ("payload-bos", r#"{"type":"response_item","payload":{}}"#),
        ("rol-yok", r#"{"type":"response_item","payload":{"type":"message","content":[]}}"#),
        ("rol-sayi", r#"{"type":"response_item","payload":{"type":"message","role":1}}"#),
        ("icerik-yok", r#"{"type":"response_item","payload":{"type":"message","role":"assistant"}}"#),
        ("baska-tur-payload-metin", r#"{"type":"event_msg","payload":"x"}"#),
    ] {
        let c = b.codex(id, lines(&[q.as_str(), r.as_str(), row]));
        b.push(c);
    }
    let body = lines(&[q.clone(), r.clone()]);
    for (id, text) in [
        ("bos", String::new()),
        ("crlf", body.replace('\n', "\r\n")),
        ("yarim", format!("{body}{{\"type\":\"resp")),
        ("bozuk", format!("çöp\n{body}}}\n")),
    ] {
        let c = b.codex(&format!("satir-{id}"), text);
        b.push(c);
    }
    let ok = json!({"last_exchange": {"user": "soru", "assistant": "cevap"}, "full_history": turns(&[("user", "soru"), ("assistant", "cevap")])});
    for (id, bad) in [
        ("dizi-satir", "[1]"),
        ("payload-null", r#"{"type":"response_item","payload":null}"#),
        ("payload-metin", r#"{"type":"response_item","payload":"x"}"#),
    ] {
        let c = b.codex(&format!("sekil-{id}"), lines(&[q.as_str(), r.as_str(), bad]));
        b.agrees(c, ok.clone());
    }
    let bad = r#"{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":7},{"type":"output_text","text":"cevap"}]}}"#;
    let c = b.codex("sekil-metin-degil", lines(&[q.as_str(), bad]));
    b.agrees(c, ok.clone());
    let mut cut = body.clone().into_bytes();
    cut.extend_from_slice(b"{\"x\":\"\xe2\x82");
    let c = b.codex("utf8", cut);
    b.agrees(c, ok);
    // okunamayan son satır: son rol bilinmiyor; geride kalan okunamayan satır rolü gizlemez
    for (id, tail, role) in [
        ("kuyruk-bayt", b"\xff\n".as_slice(), Value::Null),
        ("kuyruk-bayt-bosluk", b"\xff\n\n  \n", Value::Null),
        ("kuyruk-bayt-yarim", b"\xff\n{\"type\":\"resp", Value::Null),
        ("kuyruk-bos-nesne", b"{}\n", Value::Null),
        ("kuyruk-yarim", b"{\"type\":\"resp", json!("user")),
        ("kuyruk-gecildi", b"\xff\n{\"type\":\"x\"}\n", json!("user")),
    ] {
        let mut data = format!("{q}\n").into_bytes();
        data.extend_from_slice(tail);
        let c = b.codex(&format!("rol-{id}"), data);
        b.agrees(c, json!({"last_message_role": role}));
        let mut data = format!("{}\n", msg("user", json!("soru"), json!({}))).into_bytes();
        data.extend_from_slice(tail);
        let c = b.claude(&format!("rol-{id}"), data);
        b.agrees(c, json!({"last_message_role": role}));
    }
}

// -------------------------------------------------------------------------------------------------------------- ucli

fn ucli_row(role: Value, content: Value) -> String {
    json!({"role": role, "content": content}).to_string()
}

fn ucli_cases(b: &mut Build<'_>) {
    const HEADER: &str = r#"{"ucli_session_schema_version":1}"#;
    let user = |t: &str| ucli_row(json!("user"), json!(t));
    let ai = |t: &str| ucli_row(json!("assistant"), json!(t));
    let h = HEADER.to_string();
    let tool = ucli_row(json!("tool"), json!("araç çıktısı"));
    let named: Vec<(&str, Vec<String>)> = vec![
        ("baslik", vec![h.clone(), user("soru"), ai("cevap")]),
        ("yalniz-baslik", vec![h.clone()]),
        ("basliksiz", vec![user("soru"), ai("cevap")]),
        ("bekleyen", vec![user("a"), ai("OLD COPS-END"), user("b")]),
        ("cevapli", vec![user("a"), ai("A")]),
        ("yalniz-asistan", vec![ai("A")]),
        ("araya-arac", vec![user("a"), ai("A"), tool.clone(), ai("B"), tool.clone()]),
        ("yalniz-arac", vec![tool.clone(), ucli_row(json!("system"), json!("sistem"))]),
        ("asistan-null", vec![user("a"), ai("A"), ucli_row(json!("assistant"), Value::Null)]),
        ("kullanici-null", vec![user("a"), ai("A"), ucli_row(json!("user"), Value::Null)]),
        ("nesne-olmayan", vec!["[1]".into(), "5".into(), "\"role\"".into(), "null".into(), user("a")]),
        ("rolsuz", vec![json!({"content": "x"}).to_string(), user("a")]),
        ("bos-satirlar", vec![String::new(), "  \u{3000} ".into(), user("a"), String::new()]),
    ];
    for (id, rows) in named {
        let c = b.ucli(id, lines(&rows));
        b.push(c);
    }
    for (i, v) in [json!(""), json!(0), json!(false), json!([]), json!({}), json!(7), json!(1.5), json!(true), json!(["a", {"k": null}]), json!({"b": 1, "a": "ğ"})]
        .into_iter()
        .enumerate()
    {
        let c = b.ucli(&format!("icerik-{i}"), lines(&[user("a"), ucli_row(json!("assistant"), v.clone())]));
        b.push(c);
        let c = b.ucli(&format!("kullanici-icerik-{i}"), lines(&[ai("x"), ucli_row(json!("user"), v.clone())]));
        b.push(c);
        let c = b.ucli(&format!("rol-{i}"), lines(&[user("a"), ucli_row(v, json!("rol tuhaf"))]));
        b.push(c);
    }
    let c = b.ucli("rol-null", lines(&[ucli_row(Value::Null, json!("x"))]));
    b.push(c);
    let c = b.ucli("sayilar", format!("{}\n{}\n", r#"{"role":"assistant","content":NaN}"#, r#"{"role":"x","content":123456789012345678901234567890}"#));
    b.push(c);
    for (id, bad) in [
        ("bozuk-json", "{not json"),
        ("iceriksiz", r#"{"role":"user"}"#),
        ("yarim", r#"{"role":"assistant","cont"#),
        ("tek-tirnak", "{'role':'user'}"),
        ("fazla", r#"{"role":"user","content":"a"} x"#),
    ] {
        for (at, rows) in [("sonda", vec![h.clone(), user("a"), bad.to_string()]), ("basta", vec![bad.to_string(), user("a")])] {
            let c = b.ucli(&format!("bozuk-{id}-{at}"), lines(&rows));
            b.push(c);
        }
    }
    // yarım yazılmış son satır (satır sonu yok): atlanır, son rol bilinmiyor
    let done = lines(&[h.clone(), user("soru"), ai("cevap")]);
    let ok = turns(&[("user", "soru"), ("assistant", "cevap")]);
    for (id, tail) in [
        ("json", br#"{"role":"assistant","cont"#.as_slice()),
        ("bayt", b"{\"role\":\"user\",\"content\":\"\xc4"),
    ] {
        let mut data = done.clone().into_bytes();
        data.extend_from_slice(tail);
        let c = b.ucli(&format!("yarim-son-{id}"), data);
        b.agrees(c, json!({"full_history": ok, "read_chat_history": ok, "last_message_role": null,
                           "last_exchange": {"user": "soru", "assistant": "cevap"}}));
    }
    let c = b.ucli("sonsuz-tam-satir", format!("{done}{}", user("yeni")));
    b.agrees(c, json!({"last_message_role": "user"}));
    let body = lines(&[h.clone(), user("soru"), ai("cevap")]);
    for (id, text) in [
        ("bos", String::new()),
        ("crlf", body.replace('\n', "\r\n")),
        ("tek-cr", body.replace('\n', "\r")),
        ("bom", format!("\u{feff}{body}")),
        ("ayirac", format!("{}\u{2028}{}\n", user("a"), ai("b"))),
        ("ham-u2028", "{\"role\":\"user\",\"content\":\"a\u{2028}b\"}\n".to_string()),
    ] {
        let c = b.ucli(&format!("satir-{id}"), text);
        b.push(c);
    }
    for (id, sid) in [("sid-yok", None), ("bos-sid", Some("")), ("dosya-yok", Some("nope"))] {
        let file = Fx::File("work/p1/.ucli/chat/s1.jsonl".into(), body.clone().into_bytes(), 0o644);
        let c = b.case(&format!("ucli-{id}"), "ucli", sid).file(file);
        b.push(c);
    }
    let c = b.case("ucli-dizin-dosya-yerinde", "ucli", Some("s1")).file(Fx::Dir("work/p1/.ucli/chat/s1.jsonl".into(), 0o755));
    b.push(c);
    let c = b
        .case("ucli-izinsiz", "ucli", Some("s1"))
        .file(Fx::File("work/p1/.ucli/chat/s1.jsonl".into(), body.clone().into_bytes(), 0o000));
    b.push(c);
    // yeni (`--state-dir`) ve eski dizin sırası
    let root = format!("{}/.claude/claudeops/ucli-state", b.e.home);
    let new = state_dir_for(&root, &b.cwd());
    let new = new.strip_prefix(&format!("{}/", b.e.root)).unwrap().to_string();
    for (flag, on) in [("acik", true), ("kapali", false)] {
        for (id, sid) in [("eski", "eski"), ("yeni", "yeni"), ("ikisi", "ikisi"), ("yok", "yok")] {
            let put = |dir: &str, name: &str, text: &str| {
                Fx::File(format!("{dir}/{name}.jsonl"), format!("{}\n", user(text)).into_bytes(), 0o644)
            };
            let mut c = b
                .case(&format!("ucli-dizin-{flag}-{id}"), "ucli", Some(sid))
                .file(put("work/p1/.ucli/chat", "eski", "merhaba"))
                .file(put(&new, "yeni", "selam"))
                .file(put("work/p1/.ucli/chat", "ikisi", "eski kopya"))
                .file(put(&new, "ikisi", "yeni kopya"));
            if on {
                c = c.settings_json(json!({"ucli_limits": {"state_dir": "on"}}));
            }
            b.push(c);
        }
    }
    let mut bad = body.clone().into_bytes();
    bad.extend_from_slice(b"\xff\n");
    let c = b.ucli("utf8", bad);
    b.agrees(c, json!({"full_history": null, "last_exchange": null, "read_chat_history": null}));
    let deep = format!("{{\"role\":\"x\",\"content\":{}{}}}", "[".repeat(100_000), "]".repeat(100_000));
    let c = b.ucli("derin", lines(&[user("a"), deep]));
    b.agrees(c, json!({"full_history": null}));
    let huge = format!("{{\"role\":\"x\",\"content\":{}}}", "9".repeat(5000));
    let c = b.ucli("dev-sayi", lines(&[user("a"), huge]));
    b.agrees(c, json!({"full_history": null}));
    let c = b.ucli("sapma-vekil", lines(&[r#"{"role":"user","content":"\udc00"}"#]));
    b.diverges(
        c,
        "eşlenmemiş vekil: Python vekili taşır, Rust U+FFFD",
        json!({"full_history": turns(&[("user", "\u{fffd}")])}),
    );
}

// --------------------------------------------------------------------------------------------------------------- agy

fn varint(mut n: u64) -> Vec<u8> {
    let mut out = Vec::new();
    loop {
        let byte = (n & 0x7f) as u8;
        n >>= 7;
        out.push(if n == 0 { byte } else { byte | 0x80 });
        if n == 0 {
            return out;
        }
    }
}

fn ld(no: u64, data: &[u8]) -> Vec<u8> {
    let mut out = varint((no << 3) | 2);
    out.extend(varint(data.len() as u64));
    out.extend_from_slice(data);
    out
}

fn pu(t: &str) -> Sql {
    Sql::Blob(ld(19, &ld(2, t.as_bytes())))
}

fn pa(t: &str) -> Sql {
    Sql::Blob(ld(20, &ld(1, t.as_bytes())))
}

fn db_with(schema: &str, insert: &str, rows: &[Vec<Sql>]) -> Vec<u8> {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("s.db");
    let c = rusqlite::Connection::open(&path).unwrap();
    c.execute_batch(schema).unwrap();
    c.execute_batch("BEGIN").unwrap();
    for r in rows {
        c.execute(insert, rusqlite::params_from_iter(r.iter())).unwrap();
    }
    c.execute_batch("COMMIT").unwrap();
    drop(c);
    fs::read(path).unwrap()
}

/// `steps` tablosu; `affinity` = `step_type` sütun tipi.
fn agy_db_typed(affinity: &str, rows: &[(i64, Sql, Sql)]) -> Vec<u8> {
    let rows: Vec<Vec<Sql>> = rows.iter().map(|(i, t, p)| vec![Sql::Integer(*i), t.clone(), p.clone()]).collect();
    db_with(
        &format!("CREATE TABLE steps (idx INTEGER, step_type {affinity}, step_payload BLOB)"),
        "INSERT INTO steps VALUES (?,?,?)",
        &rows,
    )
}

fn agy_db(rows: &[(i64, Sql)]) -> Vec<u8> {
    // satır: (adım türü, yük); idx = sıra
    let rows: Vec<(i64, Sql, Sql)> =
        rows.iter().enumerate().map(|(i, (t, p))| (i as i64, Sql::Integer(*t), p.clone())).collect();
    agy_db_typed("INTEGER", &rows)
}

fn agy_scenarios() -> Vec<(&'static str, Vec<(i64, Sql)>)> {
    let blob = |b: &[u8]| Sql::Blob(b.to_vec());
    let summary = blob(b"x<summary>ozet</summary>");
    vec![
        ("sikistirma", vec![
            (14, pu("soru")),
            (15, pa("cevap")),
            (23, blob(b"baska bir type-23 adimi")),
            (23, summary.clone()),
            (14, pu("yeni")),
        ]),
        ("son-cift", vec![(14, pu("ilk")), (15, pa("c1")), (14, pu("ikinci")), (15, pa("c2")), (15, Sql::Blob(ld(20, b"")))]),
        ("bos", vec![]),
        ("yalniz-kullanici", vec![(14, pu("x"))]),
        ("yalniz-asistan", vec![(15, pa("x"))]),
        ("arada-sinir", vec![(14, pu("s")), (23, summary.clone()), (15, pa("c"))]),
        ("bos-kullanici", vec![(14, pu("onceki")), (14, pu("")), (15, pa("c"))]),
        ("ardisik", vec![(14, pu("a")), (14, pu("b")), (15, pa("1")), (15, pa("2"))]),
        ("baska-turler", vec![(1, pu("x")), (14, pu("s")), (99, pa("y")), (15, pa("c")), (0, summary)]),
        ("yuk-null", vec![(14, pu("s")), (15, pa("c")), (14, Sql::Null), (15, Sql::Null), (23, Sql::Null)]),
        ("yuk-metin", vec![(14, pu("s")), (15, pa("c")), (15, Sql::Text("metin".into())), (23, Sql::Text("<summary>".into()))]),
        ("yuk-sayi", vec![(15, pa("c")), (15, Sql::Integer(5)), (14, Sql::Real(1.5))]),
        ("yuk-bos", vec![(14, blob(b"")), (15, blob(b"")), (23, blob(b""))]),
        ("sinir-yarim", vec![(23, blob(b"<summary")), (23, blob(b"<Summary>")), (23, blob(b"\0\xff<summary>"))]),
        ("unicode", vec![(14, pu("ğüş İ 😀\u{2028}\0")), (15, pa("  "))]),
    ]
}

fn agy_payloads() -> Vec<Vec<u8>> {
    let cat = |parts: &[Vec<u8>]| parts.concat();
    let inner = ld(2, b"metin");
    let good = ld(19, &inner);
    let mut out = vec![
        good.clone(),
        // son yazan kazanır
        cat(&[good.clone(), ld(19, &ld(2, b"ikinci"))]),
        ld(19, &cat(&[ld(2, b"a"), ld(2, b"b")])),
        // yanlış wire type
        cat(&[varint(19 << 3), varint(5)]),
        ld(19, &cat(&[varint(2 << 3), varint(5)])),
        cat(&[good.clone(), varint(19 << 3), varint(5)]),
        // önde başka alanlar: varint, 64 bit, 32 bit
        cat(&[varint(1 << 3), varint(u64::MAX), good.clone()]),
        cat(&[varint((3 << 3) | 1), vec![0; 8], good.clone()]),
        cat(&[varint((3 << 3) | 5), vec![0; 4], good.clone()]),
        cat(&[varint((3 << 3) | 1), vec![0; 3]]),
        cat(&[good.clone(), varint((3 << 3) | 5), vec![0; 1]]),
        // desteklenmeyen wire type: durur, öncesi geçerli
        cat(&[good.clone(), varint((3 << 3) | 3), ld(19, &ld(2, b"sonrasi"))]),
        cat(&[varint((3 << 3) | 4), good.clone()]),
        cat(&[varint((3 << 3) | 6), good.clone()]),
        cat(&[good.clone(), varint((3 << 3) | 7)]),
        // uzunluk veriyi aşıyor
        cat(&[varint((19 << 3) | 2), varint(1000), inner.clone()]),
        cat(&[varint((19 << 3) | 2), varint(u64::MAX), inner.clone()]),
        cat(&[varint((19 << 3) | 2), vec![0xff; 20], vec![0x01], inner.clone()]),
        cat(&[good.clone(), varint((19 << 3) | 2), varint(9)]),
        cat(&[good.clone(), varint((19 << 3) | 2)]),
        cat(&[good.clone(), vec![0x80]]),
        cat(&[good.clone(), vec![0x80; 50]]),
        cat(&[good.clone(), varint(1 << 3), vec![0xff]]),
        // 64 biti aşan etiket (alt bitleri alan 19'a benzer)
        cat(&[vec![0x9a, 0x81, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x02], varint(inner.len() as u64), inner.clone()]),
        // sıfır dolgulu uzun etiket
        cat(&[vec![0x9a, 0x81, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x00], varint(inner.len() as u64), inner]),
        // iç metin bozuk UTF-8
        ld(19, &ld(2, b"a\xff b\xc4 c\xe2\x82 d\xed\xa0\x80 e\xf0\x80\x80 f\xc0\xaf")),
        ld(19, &ld(2, b"\xf4\x90\x80\x80\x80\xfe")),
    ];
    // kullanıcı yükleri asistan alanına da (20 -> 1)
    out.push(ld(20, &ld(1, b"asistan")));
    out.push(ld(20, &cat(&[ld(3, b"dusunce"), ld(1, b"gorunur")])));
    out.push(ld(20, &ld(3, b"yalniz dusunce")));
    let full = cat(&[ld(19, &ld(2, "kesik ğ".as_bytes())), ld(20, &ld(1, "kesik 😀".as_bytes()))]);
    out.extend((0..=full.len()).map(|n| full[..n].to_vec()));
    out
}

/// Geçerli bir yapının rastgele bozulmuş biçimleri.
fn random_payload(r: &mut Rng) -> Vec<u8> {
    let text: Vec<u8> = (0..r.below(12)).map(|_| [b'a', b' ', 0xc4, 0x9f, 0xff, 0xe2, 0x82, 0xf0, 0x80][r.below(9)]).collect();
    let (outer, inner) = [(19, 2), (20, 1), (20, 3), (19, 1), (2, 19)][r.below(5)];
    let mut p = ld(outer, &ld(inner, &text));
    if r.below(3) == 0 {
        p.extend(ld(outer, &ld(inner, b"ek")));
    }
    for _ in 0..r.below(4) {
        let at = r.below(p.len().max(1));
        match r.below(4) {
            0 => p[at] = r.below(256) as u8,
            1 => p.insert(at, r.below(256) as u8),
            2 => p.truncate(at.max(1)),
            _ => p.extend((0..r.below(6)).map(|_| r.below(256) as u8)),
        }
    }
    p
}

fn agy_cases(b: &mut Build<'_>) {
    for (id, rows) in agy_scenarios() {
        let c = b.agy(id, agy_db(&rows));
        b.push(c);
    }
    for (i, p) in agy_payloads().into_iter().enumerate() {
        let c = b.agy(&format!("yuk-{i}"), agy_db(&[(14, Sql::Blob(p.clone())), (15, Sql::Blob(p))]));
        b.push(c);
    }
    let mut r = Rng(7);
    for n in 0..150 {
        let rows: Vec<(i64, Sql)> = (0..r.below(14))
            .map(|_| {
                let t = [14, 15, 23][r.below(3)];
                let mut p = random_payload(&mut r);
                if t == 23 && r.below(2) == 0 {
                    p.extend_from_slice(b"<summary>");
                }
                (t, Sql::Blob(p))
            })
            .collect();
        let c = b.agy(&format!("rastgele-{n}"), agy_db(&rows));
        b.push(c);
    }
    let long: Vec<(i64, Sql)> =
        (0..2000).map(|i| if i % 2 == 0 { (14, pu(&format!("s{i}"))) } else { (15, pa(&format!("c{i}"))) }).collect();
    let c = b.agy("uzun", agy_db(&long));
    b.push(c);
    let c = b.agy("dev-yuk", agy_db(&[(14, pu(&"s".repeat(2_000_000))), (15, pa(&"c".repeat(2_000_000)))]));
    b.push(c);
    // idx sırası ekleme sırasından farklı
    let c = b.agy("idx-sirasi", agy_db_typed("INTEGER", &[
        (5, Sql::Integer(15), pa("son")),
        (1, Sql::Integer(14), pu("ilk")),
        (3, Sql::Integer(15), pa("orta")),
        (4, Sql::Integer(14), pu("ikinci")),
    ]));
    b.push(c);
    for affinity in ["", "TEXT", "REAL", "BLOB"] {
        let rows = [
            (0, Sql::Integer(14), pu("tam")),
            (1, Sql::Real(15.0), pa("kesir")),
            (2, Sql::Text("14".into()), pu("metin")),
            (3, Sql::Text("15".into()), pa("metin-a")),
            (4, Sql::Real(14.5), pu("yarim")),
            (5, Sql::Null, pu("null")),
        ];
        let c = b.agy(&format!("tur-tipi-{}", affinity.to_lowercase()), agy_db_typed(affinity, &rows));
        b.push(c);
    }
    for (id, content) in [
        ("bozuk-db", b"not a database at all, definitely not".to_vec()),
        ("bos-dosya", Vec::new()),
        ("tablo-yok", db_with("CREATE TABLE x (a)", "INSERT INTO x VALUES (?)", &[])),
        ("sutun-yok", db_with("CREATE TABLE steps (idx, step_type)", "INSERT INTO steps VALUES (?,?)", &[])),
    ] {
        let c = b.agy(id, content);
        b.push(c);
    }
    let good = agy_db(&long);
    for (id, keep) in [("kesik-baslik", 50), ("kesik-yari", good.len() / 2), ("kesik-sayfa", 4096)] {
        let c = b.agy(&format!("db-{id}"), good[..keep].to_vec());
        b.push(c);
    }
    let db = agy_db(&[(14, pu("s")), (15, pa("c"))]);
    for (id, sid, resume) in [
        ("resume", None, Some("abc")),
        ("bos-sid", Some(""), Some("abc")),
        ("resume-yok", None, None),
        ("resume-bos", None, Some("")),
        ("sid-yok-dosya", Some("nope"), Some("abc")),
        ("resume-dosyasiz", None, Some("nope")),
    ] {
        let mut c = b
            .case(&format!("agy-{id}"), "agy", sid)
            .file(Fx::File(format!("{AGY_DIR}/abc.db"), db.clone(), 0o600));
        if let Some(x) = resume {
            let cache = json!({ b.cwd(): x }).to_string();
            c = c.file(Fx::File(AGY_CACHE.into(), cache.into_bytes(), 0o600));
        }
        b.push(c);
    }
    // mutlak yol veren kimlik dizinin dışını açar (Python `os.path.join` gibi)
    let outside = format!("{}/work/dis", b.e.root);
    let c = b.case("agy-mutlak-kimlik", "agy", Some(&outside)).file(Fx::File("work/dis.db".into(), db.clone(), 0o600));
    b.push(c);
    let c = b.case("agy-dizin-db-yerinde", "agy", Some("abc")).file(Fx::Dir(format!("{AGY_DIR}/abc.db"), 0o755));
    b.push(c);
    let c = b.case("agy-izinsiz", "agy", Some("abc")).file(Fx::File(format!("{AGY_DIR}/abc.db"), db.clone(), 0o000));
    b.push(c);
    // UTF-8 olmayan metin hücresi sütunda: iki tarafta SQLite hatası. Python bir satır önden okuduğu için hatadan
    // önceki son iyi satırı da kaybeder.
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("s.db");
    let conn = rusqlite::Connection::open(&path).unwrap();
    conn.execute_batch("CREATE TABLE steps (idx INTEGER, step_type, step_payload BLOB)").unwrap();
    let put = |idx: i64, t: i64, p: Sql| {
        conn.execute("INSERT INTO steps VALUES (?,?,?)", rusqlite::params![idx, t, p]).unwrap();
    };
    put(1, 14, pu("s"));
    put(2, 15, pa("c"));
    conn.execute_batch("INSERT INTO steps VALUES (0, 14, CAST(X'FF' AS TEXT))").unwrap();
    drop(conn);
    let c = b.agy("sapma-utf8-hucre", fs::read(&path).unwrap());
    b.diverges(
        c,
        "okuma ortasında SQLite hatası: Python bir satır önden okuduğundan hatadan önceki iyi satırı da atar, Rust tutar",
        json!({"last_exchange": {"user": "s", "assistant": "c"}, "full_history": []}),
    );
    // `#`: Python `file:{yol}?mode=ro` URI'sinde parça ayracı; yol kesilir ve `mode=ro` düşer.
    let c = b.case("agy-sapma-uri", "agy", Some("a#b")).file(Fx::File(format!("{AGY_DIR}/a#b.db"), db, 0o600));
    b.diverges(
        c,
        "yolda `#`: Python URI'yi yanlış ayrıştırır (konuşma okunmaz, `a` adlı boş dosya yaratır), Rust dosyayı salt okur açar",
        json!({"last_exchange": {"user": "s", "assistant": "c"}, "full_history": turns(&[("user", "s"), ("assistant", "c")])}),
    );
}

// ----------------------------------------------------------------------------------------------------------- copilot

fn copilot_db(rows: &[(&str, i64, Sql, Sql)]) -> Vec<u8> {
    let rows: Vec<Vec<Sql>> = rows
        .iter()
        .map(|(s, i, u, a)| vec![Sql::Text((*s).into()), Sql::Integer(*i), u.clone(), a.clone()])
        .collect();
    db_with(
        "CREATE TABLE turns (session_id TEXT, turn_index INT, user_message, assistant_response)",
        "INSERT INTO turns VALUES (?,?,?,?)",
        &rows,
    )
}

fn copilot_cases(b: &mut Build<'_>) {
    let t = |s: &str| Sql::Text(s.into());
    let db = copilot_db(&[
        ("s1", 1, t("ikinci ğ 😀"), t("c2")),
        ("s1", 0, t("ilk"), t("c1")),
        ("s2", 0, t("başka"), t("oturum")),
        ("bek", 0, t("a"), t("A")),
        ("bek", 1, t("b"), Sql::Null),
        ("bos", 0, t(""), t("")),
        ("yalniz", 0, Sql::Null, t("A")),
    ]);
    for (id, sid, resume) in [
        ("temel", Some("s1"), None),
        ("bekleyen", Some("bek"), None),
        ("bos-tur", Some("bos"), None),
        ("yalniz-asistan", Some("yalniz"), None),
        ("tur-yok", Some("yok"), None),
        ("enjeksiyon", Some("s1' OR 1=1 --"), None),
        ("resume", None, Some("s2")),
        ("bos-sid", Some(""), Some("s2")),
        ("resume-yok", None, None),
        ("resume-bos", None, Some("")),
    ] {
        let db = match resume {
            Some(r) => with_sessions(&db, &[(Sql::Text(r.into()), Sql::Text(b.cwd()))]),
            None => db.clone(),
        };
        let c = b.case(&format!("copilot-sohbet-{id}"), "copilot", sid).file(Fx::File(COPILOT_DB.into(), db, 0o600));
        b.push(c);
    }
    let cells = [
        ("null", Sql::Null),
        ("sifir", Sql::Integer(0)),
        ("sayi", Sql::Integer(-7)),
        ("buyuk", Sql::Integer(i64::MAX)),
        ("sifir-kesir", Sql::Real(0.0)),
        ("kesir", Sql::Real(1.5)),
        ("sonsuz", Sql::Real(f64::INFINITY)),
        ("metin-sifir", t("0")),
        ("bosluk", t("  ")),
        ("blob-bos", Sql::Blob(Vec::new())),
    ];
    for (id, v) in cells {
        let c = b.copilot(&format!("hucre-{id}"), copilot_db(&[("s1", 0, v.clone(), t("A")), ("s1", 1, t("u"), v)]));
        b.push(c);
    }
    for (id, content) in [
        ("bozuk", b"not a database at all, definitely not".to_vec()),
        ("bos-dosya", Vec::new()),
        ("tablo-yok", db_with("CREATE TABLE x (a)", "INSERT INTO x VALUES (?)", &[])),
        ("kesik", db[..db.len() / 2].to_vec()),
    ] {
        let c = b.copilot(&format!("db-{id}"), content);
        b.push(c);
    }
    let c = b.case("copilot-sohbet-db-yok", "copilot", Some("s1"));
    b.push(c);
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("s.db");
    let conn = rusqlite::Connection::open(&path).unwrap();
    conn.execute_batch(
        "CREATE TABLE turns (session_id TEXT, turn_index INT, user_message, assistant_response);
         INSERT INTO turns VALUES ('s1', 0, 'u', 'a');
         INSERT INTO turns VALUES ('s1', 1, CAST(X'FF' AS TEXT), 'a');",
    )
    .unwrap();
    drop(conn);
    let c = b.copilot("utf8-hucre", fs::read(&path).unwrap());
    b.push(c);
    let c = b.copilot("sapma-blob", copilot_db(&[("s1", 0, Sql::Blob(b"ham".to_vec()), t("A"))]));
    b.diverges(
        c,
        "BLOB hücre: Python `bytes` döndürür (panel JSON'a yazamaz), Rust metne çevirir",
        json!({"last_exchange": {"user": "ham", "assistant": "A"}, "full_history": turns(&[("user", "ham"), ("assistant", "A")])}),
    );
}

// ------------------------------------------------------------------------------------------------------------- ortak

fn other_cases(b: &mut Build<'_>) {
    for (id, sid) in [("sid", Some("s1")), ("sidsiz", None)] {
        let c = b.case(&format!("shell-{id}"), "shell", sid);
        b.push(c);
    }
    // `extra_file_roots`: cwd kodlaması
    let cwds = [
        "/home/u/BLM308_veri_madenciliği",
        "/a/b/",
        "göreli/dizin",
        "",
        "/",
        "/x y/.z/-q_",
        "/İŞ/😀/٣",
        "/a\nb",
    ];
    for (i, cwd) in cwds.iter().enumerate() {
        for cli in ["claude", "codex", "agy", "copilot", "ucli", "shell"] {
            let c = Case::new(format!("chat-kok-{cli}-{i}"), "chat", json!({"cli": cli, "cwd": cwd, "sid": null}));
            b.push(c);
        }
    }
}

/// Satır parçalarından rastgele jsonl (geçerli JSON; Python'da istisna üretmeyen alan tipleri).
fn random_rows(b: &mut Build<'_>) {
    let mut r = Rng(11);
    for n in 0..200 {
        let rows: Vec<String> = (0..r.below(14))
            .map(|_| {
                let t = ["user", "assistant", "system", "x"][r.below(4)];
                let block = ["text", "tool_use", "tool_result", "input_text"][r.below(4)];
                let content = match r.below(4) {
                    0 => json!(["", " ", "a", "ğ 😀"][r.below(4)]),
                    1 => Value::Null,
                    2 => json!([self::block(block, ["", "m", "n"][r.below(3)])]),
                    _ => json!([{"type": "text", "text": "p"}, {"type": block, "text": "q"}]),
                };
                let mut row = map(json!({"type": t, "message": {"content": content}}));
                for key in ["isSidechain", "isMeta", "isCompactSummary"] {
                    if r.below(5) == 0 {
                        row.insert(key.into(), json!(r.below(2) == 0));
                    }
                }
                if r.below(4) == 0 {
                    row.insert("subtype".into(), json!("compact_boundary"));
                    row.insert("compactMetadata".into(), json!({"trigger": "auto", "preTokens": r.below(100)}));
                }
                Value::Object(row).to_string()
            })
            .collect();
        let c = b.claude(&format!("rastgele-{n}"), lines(&rows));
        b.push(c);
    }
    for n in 0..150 {
        let rows: Vec<String> = (0..r.below(14))
            .map(|_| {
                let t = ["response_item", "response_item", "response_item", "event_msg"][r.below(4)];
                let kind = ["message", "message", "message", "reasoning"][r.below(4)];
                let role = ["user", "assistant", "developer"][r.below(3)];
                let block = ["input_text", "output_text", "text"][r.below(3)];
                let text = ["", " ", "a", "<environment_context>x", " <environment_context>", "ğ"][r.below(6)];
                json!({"type": t, "payload": {"type": kind, "role": role, "content": [{"type": block, "text": text}]}}).to_string()
            })
            .collect();
        let c = b.codex(&format!("rastgele-{n}"), lines(&rows));
        b.push(c);
    }
    for n in 0..150 {
        let rows: Vec<String> = (0..r.below(10))
            .map(|_| {
                let role = ["user", "assistant", "tool"][r.below(3)];
                match r.below(12) {
                    0 => r#"{"ucli_session_schema_version":1}"#.to_string(),
                    1 => ucli_row(json!(role), Value::Null),
                    _ => ucli_row(json!(role), json!(["", "a", "b", "ğ"][r.below(4)])),
                }
            })
            .collect();
        let c = b.ucli(&format!("rastgele-{n}"), lines(&rows));
        b.push(c);
    }
}

// ------------------------------------------------------------------------------------------------------------- koşum

fn value(v: &Py) -> Value {
    match v {
        Py::Null => Value::Null,
        Py::Bool(b) => (*b).into(),
        Py::Int(i) => (*i).into(),
        Py::BigInt(s) => serde_json::from_str(s).unwrap_or(Value::Null),
        Py::Float(f) => fjson(*f),
        Py::Str(s) => s.as_str().into(),
        Py::Array(a) => a.iter().map(value).collect(),
        Py::Object(o) => Value::Object(o.iter().map(|(k, v)| (k.clone(), value(v))).collect()),
    }
}

fn history(h: Option<Vec<ChatTurn>>) -> Value {
    match h {
        Some(turns) => turns.iter().map(|t| json!({"role": value(&t.role), "text": value(&t.text)})).collect(),
        None => Value::Null,
    }
}

fn rs_chat(e: &Env, c: &Case) -> RsOut {
    let cli = Cli::parse(c.args["cli"].as_str().unwrap());
    let cwd = c.args["cwd"].as_str().unwrap();
    let sid = c.args.get("sid").and_then(Value::as_str);
    let settings = e.settings();
    let paths = e.paths();
    let probe = FsProbe::new(e, c);
    let live = Live { settings: &settings, paths: &paths, probe: &probe, clock: Clock { now: 0.0, utc_offset_secs: 0 } };
    let exchange = live
        .last_exchange(cli, cwd, sid)
        .map(|x| json!({"user": value(&x.user), "assistant": value(&x.assistant)}));
    let roots: Vec<Value> = live.extra_file_roots(cli, cwd).into_iter().map(|(k, p)| json!([k, p])).collect();
    let mut out = map(json!({
        "last_exchange": exchange,
        "full_history": history(live.full_history(cli, cwd, sid)),
        "last_message_role": live.last_message_role(cli, cwd, sid).map(|r| value(&r)),
        "extra_file_roots": roots,
        "roots": [paths.codex_sessions_dir(), paths.agy_conversations_dir(), paths.copilot_session_db()],
    }));
    if cli == Cli::Ucli {
        out.insert("read_chat_history".into(), history(live.read_chat_history(cwd, sid.unwrap_or(""))));
    }
    RsOut::ret(Value::Object(out))
}

pub fn run() {
    let mut r = Runner::new();
    let (cases, expect) = {
        let mut b = Build { e: &r.e, cases: Vec::new(), expect: HashMap::new() };
        claude_cases(&mut b);
        claude_divergences(&mut b);
        codex_cases(&mut b);
        ucli_cases(&mut b);
        agy_cases(&mut b);
        copilot_cases(&mut b);
        other_cases(&mut b);
        random_rows(&mut b);
        (b.cases, b.expect)
    };
    r.run(cases, &[], |e, c| {
        let out = rs_chat(e, c);
        if let Some(want) = expect.get(&c.id) {
            for (k, v) in want.as_object().unwrap() {
                assert_eq!(&out.ret[k], v, "[{}] güvenli sonuç: {k}", c.id);
            }
        }
        out
    });
    r.finish("chat");
}
