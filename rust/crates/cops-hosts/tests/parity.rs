//! Python paritesi (iş 4, sahip eki "İŞLEVCE EŞLİK").
//!
//! İki yol:
//! - METİN: route kümeleri `web_hosts.py` kaynağından, gRPC alanları `host_bridge.proto` ve `grpc.rs` metninden okunur
//!   (elle kopya liste yok).
//! - DİFERANSİYEL: aynı girdiler Python'a (`tools/py_parity.py`, geçici `CLAUDEOPS_DIR`/`HOME`, ağ süreç içinde
//!   engelli) ve crate'e verilir, çıktılar karşılaştırılır. Bilinen farklar her testte AYRI listede, gerekçeli; listedeki
//!   girdi artık eşitse test düşer (liste bayatlamasın).
//!
//! Python yoksa ya da kahin çalışmazsa test DÜŞER (sessiz atlama yok).

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use cops_hosts::consts::{self, Timeouts};
use cops_hosts::grpc::{self, pb};
use cops_hosts::health::{self, Capabilities};
use cops_hosts::record::{self, Draft, RecordError};
use cops_hosts::status::{self, HostStatus, StatusBook};
use cops_hosts::tier::{Tier, TierBook};
use cops_hosts::{endpoint, flight, guard, http, proxy, ws, HostRecord};
use serde_json::{json, Map, Value};

// ---------------------------------------------------------------- ortak

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .unwrap()
}

fn read(rel: &str) -> String {
    std::fs::read_to_string(repo().join(rel)).unwrap_or_else(|e| panic!("{rel}: {e}"))
}

/// Python kahini: yalıtılmış ortam, 120 sn zaman aşımı (`timeout`), başarısızlık = test düşer.
fn oracle(req: Value) -> Value {
    let tmp = tempfile::tempdir().unwrap();
    let state = tmp.path().join("claudeops");
    std::fs::create_dir(&state).unwrap();
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("tools/py_parity.py");
    let mut child = Command::new("timeout")
        .arg("120")
        .arg("python3")
        .arg("-I")
        // `py/` altına bayt kodu yazılmaz.
        .arg("-B")
        .arg(&script)
        .arg(repo().join("py"))
        .env_clear()
        .env("PATH", std::env::var("PATH").unwrap_or_default())
        .env("TMPDIR", std::env::temp_dir())
        .env("LANG", "C.UTF-8")
        .env("HOME", tmp.path())
        .env("CLAUDEOPS_DIR", &state)
        .env("CLAUDEOPS_DIAG_LOG", tmp.path().join("diag.log"))
        .env("CLAUDEOPS_EXTENSIONS", "0")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("python3 çalıştırılamadı");
    child
        .stdin
        .take()
        .unwrap()
        .write_all(req.to_string().as_bytes())
        .unwrap();
    let out = child.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "py_parity düştü ({}): {}",
        out.status,
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).expect("py_parity çıktısı JSON değil")
}

/// Bilinen fark listesiyle karşılaştırma: listede olmayan her girdi eşit, listedeki her girdi gerçekten farklı.
fn compare(op: &str, inputs: &[Value], py: &[Value], rust: &[Value], known: &[(Value, &str)]) {
    assert_eq!(inputs.len(), py.len(), "{op}: Python çıktı sayısı");
    let mut unexpected = Vec::new();
    for ((i, p), r) in inputs.iter().zip(py).zip(rust) {
        let is_known = known.iter().any(|(k, _)| k == i);
        if is_known {
            assert_ne!(p, r, "{op}: bilinen fark artık yok, listeden çıkar: {i}");
        } else if p != r {
            unexpected.push(format!("{op}: girdi {i}\n  python {p}\n  rust   {r}"));
        }
    }
    for (k, why) in known {
        assert!(
            inputs.contains(k),
            "{op}: bilinen fark girdisi listede yok: {k} ({why})"
        );
    }
    assert!(unexpected.is_empty(), "\n{}", unexpected.join("\n"));
}

// ---------------------------------------------------------------- metin: route kümeleri

/// `NAME = {...}` / `(...)` / `"..."` ataması içindeki dize literalleri (yorumlar atlanır).
fn py_strings(src: &str, name: &str) -> Vec<String> {
    let start = src
        .lines()
        .scan(0usize, |off, l| {
            let here = *off;
            *off += l.len() + 1;
            Some((here, l))
        })
        .find(|(_, l)| l.starts_with(&format!("{name} = ")))
        .map(|(o, l)| o + l.find(" = ").unwrap() + 3)
        .unwrap_or_else(|| panic!("{name} ataması bulunamadı"));
    let mut out = Vec::new();
    let mut depth = 0i32;
    let mut cur: Option<String> = None;
    let mut comment = false;
    for c in src[start..].chars() {
        if comment {
            if c == '\n' {
                comment = false;
            }
            continue;
        }
        match (&mut cur, c) {
            (Some(s), '"') => {
                out.push(std::mem::take(s));
                cur = None;
                if depth == 0 {
                    break;
                }
            }
            (Some(s), _) => s.push(c),
            (None, '"') => cur = Some(String::new()),
            (None, '#') => comment = true,
            (None, '{' | '(' | '[') => depth += 1,
            (None, '}' | ')' | ']') => {
                depth -= 1;
                if depth == 0 {
                    break;
                }
            }
            (None, '\n') if depth == 0 => break,
            _ => {}
        }
    }
    out
}

fn as_set(v: &[&str]) -> BTreeSet<String> {
    v.iter().map(|s| s.to_string()).collect()
}

#[test]
fn host_routed_route_sets_equal_python_source() {
    let src = read("py/claudeops/commands/web_hosts.py");
    for (name, rust) in [
        ("HOST_ROUTED_PATHS", consts::HOST_ROUTED_PATHS),
        ("GET_HOST_ROUTED_PATHS", consts::GET_HOST_ROUTED_PATHS),
        ("SECRET_BODY_PATHS", consts::SECRET_BODY_PATHS),
        ("TERM_RETRY_PATHS", consts::TERM_RETRY_PATHS),
    ] {
        let py: BTreeSet<String> = py_strings(&src, name).into_iter().collect();
        assert!(!py.is_empty(), "{name}: Python kümesi boş okundu");
        assert_eq!(as_set(rust), py, "{name}");
        assert_eq!(
            as_set(rust).len(),
            rust.len(),
            "{name}: Rust listesinde yineleme"
        );
    }
    assert_eq!(
        py_strings(&src, "FILE_DOWNLOAD_PATH"),
        vec![consts::FILE_DOWNLOAD_PATH]
    );
    assert_eq!(
        py_strings(&src, "FILE_UPLOAD_PATH"),
        vec![consts::FILE_UPLOAD_PATH]
    );
    for p in consts::HOST_ROUTED_PATHS {
        assert!(consts::is_host_routed_post(p) && !p.is_empty());
    }
    for p in consts::GET_HOST_ROUTED_PATHS {
        assert!(consts::is_host_routed_get(p));
    }
    // Kendi kendini sınama: ayrıştırıcı yorumdaki yolu almaz.
    assert_eq!(
        py_strings("X = {\"/a\",  # \"/yorum\"\n \"/b\"}\n", "X"),
        vec!["/a", "/b"]
    );
}

/// Her host-routed yol yetki tablosunda bir eyleme düşer (varsayılan `UNMAPPED` = yalnız admin) ve Rust eylemi Python
/// `authz.action_for` ile aynı.
#[test]
fn host_routed_paths_have_the_same_authz_action_as_python() {
    let mut pairs: Vec<(&str, &str)> = Vec::new();
    pairs.extend(consts::HOST_ROUTED_PATHS.iter().map(|p| ("POST", *p)));
    pairs.extend(consts::GET_HOST_ROUTED_PATHS.iter().map(|p| ("GET", *p)));
    pairs.push(("GET", consts::FILE_DOWNLOAD_PATH));
    pairs.push(("POST", consts::FILE_UPLOAD_PATH));
    // Federasyonun kendi okuduğu uçlar (`/api/status` yoklaması, `/ws`, `/ws/term`, facts).
    pairs.extend([("GET", "/api/status"), ("GET", "/ws"), ("GET", "/ws/term")]);
    for (m, p) in &pairs {
        assert_ne!(
            cops_auth::authz::action_for(m, p),
            cops_auth::authz::UNMAPPED,
            "{m} {p}"
        );
    }
    let req: Vec<Value> = pairs.iter().map(|(m, p)| json!([m, p])).collect();
    let py = oracle(json!({ "action_for": req }));
    let rust: Vec<Value> = pairs
        .iter()
        .map(|(m, p)| json!(cops_auth::authz::action_for(m, p)))
        .collect();
    compare(
        "action_for",
        &req,
        py["action_for"].as_array().unwrap(),
        &rust,
        &[],
    );
}

// ---------------------------------------------------------------- metin: gRPC alanları

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct Field {
    name: String,
    number: u32,
    /// "" | "repeated" | "optional" | "map"
    label: String,
    /// proto skaler adı ya da "message"
    ty: String,
}

const SCALARS: [&str; 5] = ["string", "bool", "int32", "double", "int64"];

fn proto_messages(src: &str) -> BTreeMap<String, Vec<Field>> {
    let mut out = BTreeMap::new();
    let mut cur: Option<String> = None;
    for raw in src.lines() {
        let line = raw.split("//").next().unwrap().trim();
        if let Some(rest) = line.strip_prefix("message ") {
            let name = rest.split([' ', '{']).next().unwrap().to_string();
            out.insert(name.clone(), Vec::new());
            cur = if line.ends_with('}') {
                None
            } else {
                Some(name)
            };
            continue;
        }
        if line == "}" {
            cur = None;
            continue;
        }
        let Some(m) = &cur else { continue };
        let Some(decl) = line.strip_suffix(';') else {
            continue;
        };
        let (lhs, num) = decl.split_once('=').unwrap();
        let mut words: Vec<&str> = lhs.split_whitespace().collect();
        let name = words.pop().unwrap().to_string();
        let (label, ty) = match words.as_slice() {
            [t] if t.starts_with("map<") => ("map".to_string(), "message".to_string()),
            [t1, t2] if t1.starts_with("map<") => {
                assert!(t2.ends_with('>'), "{line}");
                ("map".to_string(), "message".to_string())
            }
            [l, t] => (l.to_string(), t.to_string()),
            [t] => (String::new(), t.to_string()),
            other => panic!("tanınmayan alan: {other:?}"),
        };
        let ty = if SCALARS.contains(&ty.as_str()) {
            ty
        } else {
            "message".to_string()
        };
        out.get_mut(m).unwrap().push(Field {
            name,
            number: num.trim().parse().unwrap(),
            label,
            ty,
        });
    }
    out
}

fn rust_pb_messages(src: &str) -> BTreeMap<String, Vec<Field>> {
    let body = &src[src.find("pub mod pb {").expect("pb modülü")..];
    let body = &body[..body.find("\n}\n").unwrap()];
    let mut out = BTreeMap::new();
    let mut cur: Option<String> = None;
    let mut pending: Option<(String, String, u32)> = None;
    for raw in body.lines() {
        let line = raw.trim();
        if let Some(rest) = line.strip_prefix("pub struct ") {
            let name = rest.split([' ', '{']).next().unwrap().to_string();
            out.insert(name.clone(), Vec::new());
            cur = Some(name);
            continue;
        }
        if let Some(attr) = line.strip_prefix("#[prost(") {
            let attr = attr.trim_end_matches(")]");
            let tag: u32 = attr
                .split("tag = \"")
                .nth(1)
                .unwrap()
                .trim_end_matches('"')
                .parse()
                .unwrap();
            let (ty, label) = if attr.starts_with("map =") {
                ("message".to_string(), "map".to_string())
            } else {
                let parts: Vec<&str> = attr.split(", ").collect();
                let label = match parts.get(1) {
                    Some(&"repeated") => "repeated",
                    Some(&"optional") => "optional",
                    _ => "",
                };
                (parts[0].to_string(), label.to_string())
            };
            pending = Some((ty, label, tag));
            continue;
        }
        if let (Some(rest), Some((ty, label, number))) = (line.strip_prefix("pub "), pending.take())
        {
            let name = rest.split(':').next().unwrap().to_string();
            out.get_mut(cur.as_ref().unwrap()).unwrap().push(Field {
                name,
                number,
                label,
                ty,
            });
        }
    }
    out
}

#[test]
fn grpc_messages_match_proto_text_and_python_descriptors() {
    let proto = read("py/claudeops/proto/host_bridge.proto");
    let rs = read("rust/crates/cops-hosts/src/grpc.rs");
    let p = proto_messages(&proto);
    let r = rust_pb_messages(&rs);
    assert_eq!(p.len(), 8, "{:?}", p.keys());
    assert_eq!(p, r, "grpc.rs pb modülü host_bridge.proto ile ayrışıyor");

    // Üretilmiş Python tanımlayıcısı da aynı (ad + numara).
    let py = oracle(json!({"pb_fields": 1}));
    let from_proto: BTreeMap<String, Vec<Value>> = p
        .iter()
        .map(|(m, fs)| {
            (
                m.clone(),
                fs.iter().map(|f| json!([f.name, f.number])).collect(),
            )
        })
        .collect();
    let from_py: BTreeMap<String, Vec<Value>> =
        serde_json::from_value(py["pb_fields"].clone()).unwrap();
    assert_eq!(from_proto, from_py, "host_bridge_pb2 bayat");

    // Servis yolu ve yöntemler.
    let package = proto
        .lines()
        .find_map(|l| l.strip_prefix("package "))
        .unwrap()
        .trim_end_matches(';');
    let service = proto
        .lines()
        .find_map(|l| l.strip_prefix("service "))
        .unwrap()
        .trim_end_matches(" {");
    assert!(
        rs.contains(&format!("const SERVICE: &str = \"/{package}.{service}\";")),
        "SERVICE sabiti"
    );
    let rpcs: Vec<(String, String, bool, String)> = proto
        .lines()
        .filter_map(|l| l.trim().strip_prefix("rpc "))
        .map(|l| {
            let (name, rest) = l.split_once('(').unwrap();
            let (req, rest) = rest.split_once(')').unwrap();
            let resp = rest.split('(').nth(1).unwrap().trim_end_matches(");");
            let stream = resp.starts_with("stream ");
            (
                name.to_string(),
                req.to_string(),
                stream,
                resp.trim_start_matches("stream ").to_string(),
            )
        })
        .collect();
    assert_eq!(rpcs.len(), 3);
    for (name, req, stream, resp) in rpcs {
        assert!(
            rs.contains(&format!("pb::{req} {{")) || rs.contains(&format!("pb::{req} {{}}")),
            "{name}: istek türü {req}"
        );
        if stream {
            assert!(rs.contains(&format!("\"{name}\"")), "{name}: akış yöntemi");
            assert!(rs.contains(&format!("&pb::{resp}")), "{name}: yanıt {resp}");
        } else {
            assert!(
                rs.contains(&format!("{{SERVICE}}/{name}")),
                "{name}: tekil yöntem"
            );
            assert!(rs.contains(&format!("pb::{resp},")), "{name}: yanıt {resp}");
        }
    }
}

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}

/// Python pb2 ile kodlanan mesaj Rust'ta çözülür; iki tarafın dict/JSON dönüşümü aynı.
#[test]
fn grpc_wire_decoding_matches_python_conversion() {
    use prost::Message;
    let full_row = json!({"name": "s1", "host": "local", "model": "m", "cwd": "/w", "cli": "claude", "running": true,
        "pid": 42, "cpu": 1.5, "kind": "fresh", "needs_ho": false, "busy": true, "history_size": 7, "registered": true,
        "tmux": true, "live_model": "lm", "live_effort": "high", "instance": true, "blueprint": "bp",
        "ucli_write": true, "ucli_exec": false, "ucli_max_cost_usd": 2.0});
    let status = vec![
        json!({}),
        json!({"ok": true, "sessions": [full_row.clone(), {"name": "bare"}], "closed": [{"name": "c", "ucli_write": false}],
               "retired": [{"name": "r", "ucli_write": true, "ucli_max_cost_usd": 0.5}],
               "cli_list": ["claude", "codex"], "dups": ["x"],
               "cli_options": {"claude": {"models": ["a", "b"], "effort_levels": ["low"]}, "codex": {}},
               "extras_json": "{\"disk_clean\": {\"a\": 1}, \"fwd\": null, \"build\": {\"running\": \"abc\"}, \"other\": 1}"}),
        json!({"extras_json": "not json"}),
        json!({"extras_json": "[1, 2]"}),
        json!({"ok": false, "error": "e", "sessions": [{"name": "x", "kind": "", "pid": 0, "cpu": 0.0}]}),
    ];
    let term = vec![
        json!({"ok": true, "text": "hi", "cols": 80, "rows": 24, "history_size": 0, "masked": true, "mode": "plan"}),
        json!({"ok": true, "text": "", "mode": ""}),
        json!({"ok": false, "error": "e", "text": "ignored"}),
        json!({"ok": false}),
    ];
    let py = oracle(json!({"grpc_status": status, "grpc_term": term}));
    let mut rust_s = Vec::new();
    let mut py_s = Vec::new();
    for out in py["grpc_status"].as_array().unwrap() {
        let m = pb::StatusUpdate::decode(unhex(out["hex"].as_str().unwrap()).as_slice()).unwrap();
        rust_s.push(grpc::status_to_value(&m));
        py_s.push(out["dict"].clone());
    }
    compare("grpc_status", &status, &py_s, &rust_s, &[]);
    let mut rust_t = Vec::new();
    let mut py_t = Vec::new();
    for out in py["grpc_term"].as_array().unwrap() {
        let m = pb::TermUpdate::decode(unhex(out["hex"].as_str().unwrap()).as_slice()).unwrap();
        rust_t.push(grpc::term_to_value(&m));
        py_t.push(out["dict"].clone());
    }
    compare("grpc_term", &term, &py_t, &rust_t, &[]);
}

// ---------------------------------------------------------------- sabitler ve hata metinleri

fn secs(d: Duration) -> Value {
    json!(d.as_secs_f64())
}

#[test]
fn shared_constants_and_error_texts_equal_python() {
    let py = oracle(json!({"constants": 1}));
    let c = &py["constants"];
    let t = Timeouts::default();
    let num = |k: &str| c[k].as_f64().unwrap_or_else(|| panic!("{k}"));
    let eq = [
        ("STATUS_TIMEOUT_SECONDS", secs(t.status)),
        ("TERM_READ_TIMEOUT_SECONDS", secs(t.term_read)),
        ("ACTION_TIMEOUT_SECONDS", secs(t.action)),
        ("FALLBACK_TIMEOUT_SECONDS", secs(t.fallback)),
        ("TERM_ATTEMPT_TIMEOUT", secs(t.term_attempt)),
        ("_WS_PROBE_TIMEOUT_SECONDS", secs(t.ws_probe)),
        ("_GRPC_PROBE_TIMEOUT_SECONDS", secs(t.grpc_probe)),
        ("POLL_INTERVAL_SECONDS", secs(consts::POLL_INTERVAL)),
        ("POLLER_STALL_SECONDS", secs(consts::POLLER_STALL)),
        ("WATCHDOG_INTERVAL_SECONDS", secs(consts::WATCHDOG_INTERVAL)),
        ("_PROBE_MIN_GAP_SECONDS", secs(consts::PROBE_MIN_GAP)),
        (
            "STATUS_PUSH_SILENCE_SECONDS",
            secs(consts::STATUS_PUSH_SILENCE),
        ),
        (
            "CAPABILITY_PROBE_INTERVAL_SECONDS",
            secs(consts::CAPABILITY_PROBE_INTERVAL),
        ),
        (
            "_TERM_RELAY_IDLE_TTL_SECONDS",
            secs(consts::TERM_RELAY_IDLE_TTL),
        ),
        (
            "_TERM_RELAY_RESTART_MIN_INTERVAL_SECONDS",
            secs(consts::TERM_RELAY_RESTART_MIN_INTERVAL),
        ),
        (
            "_TERM_RELAY_SILENCE_SECONDS",
            secs(consts::TERM_RELAY_SILENCE),
        ),
        (
            "_CONSUMER_DEATH_LOG_MIN_INTERVAL_SECONDS",
            secs(consts::CONSUMER_DEATH_LOG_MIN_INTERVAL),
        ),
        ("_INFLIGHT_MAX_SECONDS", secs(flight::INFLIGHT_MAX)),
        ("DNS_CHECK_TIMEOUT", secs(guard::DNS_CHECK_TIMEOUT)),
        ("TERM_MAX_ATTEMPTS", json!(consts::TERM_MAX_ATTEMPTS as f64)),
        (
            "CONSECUTIVE_FAILURES_BEFORE_ERROR",
            json!(consts::CONSECUTIVE_FAILURES_BEFORE_ERROR as f64),
        ),
        ("_DEDUP_LAST_GOOD_MAX", json!(flight::LAST_GOOD_MAX as f64)),
        ("_CONN_POOL_MAX_IDLE", json!(http::POOL_MAX_IDLE as f64)),
        ("REMOTE_STALE_SECONDS", json!(health::REMOTE_STALE_SECONDS)),
        ("REMOTE_BACKOFF_TICKS", json!(health::BACKOFF_TICKS as f64)),
        ("REMOTE_BACKOFF_SECONDS", json!(health::BACKOFF_SECONDS)),
        (
            "MAX_DESTRUCTIVE_PER_HOST",
            json!(health::MAX_DESTRUCTIVE_PER_HOST as f64),
        ),
        (
            "REMOTE_PROBES_PER_TICK",
            json!(health::PROBES_PER_TICK as f64),
        ),
        (
            "REMOTE_CAPS_RECHECK_SECONDS",
            json!(health::CAPS_RECHECK_SECONDS),
        ),
    ];
    for (k, rust) in eq {
        assert_eq!(json!(num(k)), rust, "{k}");
    }
    assert_eq!(c["LOCAL_HOST_NAME"], consts::LOCAL_HOST_NAME);
    assert_eq!(
        c["LOOPBACK_REACH_DEFAULT"],
        json!(guard::LOOPBACK_REACH_DEFAULT)
    );
    assert_eq!(c["REFUSED_PREFIX"], "outbound refused:");
    assert!(proxy::CallError::Refused("x".into())
        .to_string()
        .starts_with(c["REFUSED_PREFIX"].as_str().unwrap()));

    // Metinle sabitlenen gRPC değerleri (özel sabitler).
    let rs = read("rust/crates/cops-hosts/src/grpc.rs");
    let extra: Vec<String> = serde_json::from_value(c["_EXTRA_KEYS"].clone()).unwrap();
    assert!(
        rs.contains(&format!(
            "const EXTRA_KEYS: [&str; {}] = [{}];",
            extra.len(),
            extra
                .iter()
                .map(|k| format!("\"{k}\""))
                .collect::<Vec<_>>()
                .join(", ")
        )),
        "EXTRA_KEYS"
    );
    assert_eq!(
        c["_KEEPALIVE_OPTIONS"],
        json!([
            ["grpc.keepalive_time_ms", 20000],
            ["grpc.keepalive_timeout_ms", 5000],
            ["grpc.keepalive_permit_without_calls", 1]
        ])
    );
    for needle in [
        ".http2_keep_alive_interval(Duration::from_secs(20))",
        ".keep_alive_timeout(Duration::from_secs(5))",
        ".keep_alive_while_idle(true)",
    ] {
        assert!(rs.contains(needle), "{needle}");
    }

    // Hata metinleri (`hosts.ERR`), iki dil.
    let errs = [
        ("invalid_name", RecordError::InvalidName),
        ("reserved_name", RecordError::ReservedName),
        ("invalid_url", RecordError::InvalidUrl),
        ("invalid_grpc_url", RecordError::InvalidGrpcUrl),
        ("invalid_extra_url", RecordError::InvalidExtraUrl),
        ("corrupt", RecordError::Corrupt),
        ("blocked_host", RecordError::BlockedHost),
        ("token_required", RecordError::TokenRequired),
    ];
    let py_err = c["ERR"].as_object().unwrap();
    assert_eq!(py_err.len(), errs.len(), "hosts.ERR anahtar sayısı");
    for (k, e) in errs {
        for lang in ["tr", "en"] {
            assert_eq!(py_err[k][lang], e.message(lang), "ERR[{k}][{lang}]");
        }
        assert_eq!(
            e.message("xx"),
            e.message("tr"),
            "bilinmeyen dil = tr (Python `_err`)"
        );
    }

    // Belgelenmiş farklar (docs/rs-hosts.md "Python'dan bilinçli farklar"): Python'da karşılığı olmayan Rust sınırları.
    assert_eq!(t.total_cap, Duration::from_secs(600));
    assert_eq!(t.long_read, Duration::from_secs(90));
    assert_eq!(
        t.ws_open,
        Duration::from_secs(10),
        "Python `open_timeout=10.0` literal"
    );
}

// ---------------------------------------------------------------- saf işlevler

#[test]
fn address_filters_match_python() {
    let ports = guard::reach_loopback_ports(None);
    let pairs = vec![
        json!(["https://a.example", "https://b.example"]),
        json!(["https://a.example", "http://10.20.4.1:8765"]),
        json!(["https://a.example", "http://192.168.1.5"]),
        json!(["https://a.example", "http://172.16.0.1"]),
        json!(["https://a.example", "http://127.0.0.1:18765"]),
        json!(["https://a.example", "http://[::1]:18766"]),
        json!(["https://a.example", "http://b.example"]),
        json!(["https://a.example", "http://8.8.8.8"]),
        json!(["https://a.example", "http://169.254.1.1"]),
        json!(["https://a.example", "http://127.0.0.1:1"]),
        json!(["https://a.example", "http://localhost:18765"]),
        json!(["https://a.example", "http://[fd00::1]:80"]),
        json!(["http://a.example", "http://b.example"]),
        json!(["http://a.example", "https://b.example"]),
        json!(["HTTPS://a.example", "http://b.example"]),
        json!(["https://a.example", "ftp://x"]),
        json!(["https://a.example", "http://100.64.0.1"]),
        json!(["https://a.example", "http://[::ffff:8.8.8.8]"]),
    ];
    let lan = vec![
        json!("http://10.0.0.1"),
        json!("http://10.0.0.1:8765/x"),
        json!("http://192.168.0.1"),
        json!("http://172.31.255.255"),
        json!("http://172.32.0.1"),
        json!("https://10.0.0.1"),
        json!("http://127.0.0.1"),
        json!("http://169.254.169.254"),
        json!("http://0.0.0.0"),
        json!("http://8.8.8.8"),
        json!("http://example.com"),
        json!("http://[fd12::1]"),
        json!("http://[fe80::1]"),
        json!("http://100.64.0.1"),
        json!("http://198.18.0.1"),
        json!("http://192.0.2.1"),
        json!("http://[::ffff:8.8.8.8]"),
        json!("http://[2001:db8::1]"),
    ];
    let secret = vec![
        json!("https://x"),
        json!("http://127.0.0.1:1"),
        json!("http://[::1]:1"),
        json!("http://localhost:9"),
        json!("http://10.0.0.1"),
        json!("http://127.0.0.2"),
    ];
    let ips = vec![
        json!("127.0.0.1"),
        json!("127.9.9.9"),
        json!("169.254.169.254"),
        json!("0.0.0.0"),
        json!("::1"),
        json!("::"),
        json!("fe80::1"),
        json!("::ffff:169.254.169.254"),
        json!("::ffff:127.0.0.1"),
        json!("10.0.0.1"),
        json!("8.8.8.8"),
        json!("fc00::1"),
        json!("::ffff:10.0.0.1"),
        json!("fe80::1%eth0"),
    ];
    let dns = vec![
        json!("example.com"),
        json!("127.0.0.1"),
        json!("::1"),
        json!("127.1"),
        json!("2130706433"),
        json!(""),
        json!("localhost"),
        json!("fe80::1%eth0"),
    ];
    let reach = vec![
        json!({"setting": null, "urls": ["http://127.0.0.1:18765", "http://[::1]:18766", "https://127.0.0.1:18765",
                                         "http://127.0.0.1:8765", "http://localhost:18765", "http://127.0.0.1"]}),
        json!({"setting": "", "urls": ["http://127.0.0.1:18765"]}),
        json!({"setting": "1; 2,x,70000,0,+3, 4 ", "urls": ["http://127.0.0.1:2", "http://127.0.0.1:3"]}),
    ];
    let enc = vec![
        json!([["a b", "ç/&=+%"], ["token", "x~y_z.-"]]),
        json!([["names", "s1,s2"], ["k", ""]]),
    ];
    let py = oracle(json!({
        "candidate_allowed": pairs, "is_private_lan_http": lan, "secret_safe_url": secret,
        "ip_is_blocked": ips, "hostname_is_dns_name": dns, "reach": reach, "urlencode": enc,
    }));
    let arr = |k: &str| py[k].as_array().unwrap().clone();

    let rust: Vec<Value> = pairs
        .iter()
        .map(|p| {
            json!(guard::candidate_allowed(
                p[0].as_str().unwrap(),
                p[1].as_str().unwrap(),
                &ports
            ))
        })
        .collect();
    compare(
        "candidate_allowed",
        &pairs,
        &arr("candidate_allowed"),
        &rust,
        &[],
    );

    let rust: Vec<Value> = lan
        .iter()
        .map(|u| json!(guard::is_private_lan_http(u.as_str().unwrap())))
        .collect();
    compare(
        "is_private_lan_http",
        &lan,
        &arr("is_private_lan_http"),
        &rust,
        &[],
    );

    let rust: Vec<Value> = secret
        .iter()
        .map(|u| json!(guard::secret_safe_url(u.as_str().unwrap())))
        .collect();
    compare(
        "secret_safe_url",
        &secret,
        &arr("secret_safe_url"),
        &rust,
        &[],
    );

    let rust: Vec<Value> = ips
        .iter()
        .map(|s| {
            let raw = s.as_str().unwrap().split('%').next().unwrap();
            json!(raw.parse().is_ok_and(guard::ip_is_blocked))
        })
        .collect();
    compare("ip_is_blocked", &ips, &arr("ip_is_blocked"), &rust, &[]);

    let rust: Vec<Value> = dns
        .iter()
        .map(|h| json!(endpoint::host_is_dns_name(h.as_str().unwrap())))
        .collect();
    compare(
        "hostname_is_dns_name",
        &dns,
        &arr("hostname_is_dns_name"),
        &rust,
        &[(
            json!("fe80::1%eth0"),
            "Python `ip_address` kapsam (%) kabul eder; Rust bağlantıda kapsamı ayrıca soyar",
        )],
    );

    let rust: Vec<Value> = reach
        .iter()
        .map(|x| {
            let p = guard::reach_loopback_ports(x["setting"].as_str());
            let urls: Vec<bool> = x["urls"]
                .as_array()
                .unwrap()
                .iter()
                .map(|u| guard::is_reach_loopback(u.as_str().unwrap(), &p))
                .collect();
            json!({"ports": p, "urls": urls})
        })
        .collect();
    compare("reach", &reach, &arr("reach"), &rust, &[]);

    let rust: Vec<Value> = enc
        .iter()
        .map(|pairs| {
            let q: Vec<(String, String)> = serde_json::from_value(pairs.clone()).unwrap();
            json!(endpoint::urlencode(&q))
        })
        .collect();
    compare("urlencode", &enc, &arr("urlencode"), &rust, &[]);
}

#[test]
fn input_id_rule_is_python_or_stricter() {
    let ids = vec![
        json!("abc-123"),
        json!(""),
        json!("a b"),
        json!("x".repeat(64)),
        json!("x".repeat(65)),
        json!("tab\t"),
        json!(5),
        json!(null),
        json!("ç"),
        json!("a\u{200b}"),
        json!("a\u{a0}"),
        json!("\u{e000}"),
    ];
    let py = oracle(json!({ "valid_input_id": ids }));
    let rust: Vec<Value> = ids
        .iter()
        .map(|v| json!(proxy::valid_input_id(v)))
        .collect();
    let py = py["valid_input_id"].as_array().unwrap().clone();
    // Rust hiçbir girdide Python'dan gevşek değil (Rust geçerli => Python geçerli).
    for ((i, p), r) in ids.iter().zip(&py).zip(&rust) {
        assert!(
            !(r == &json!(true) && p == &json!(false)),
            "Rust gevşek: {i}"
        );
    }
    compare(
        "valid_input_id",
        &ids,
        &py,
        &rust,
        &[(
            json!("ç"),
            "ASCII dışı kimlikte Rust yeniden denemez (Python Unicode sürümüne bağlı isprintable)",
        )],
    );
}

// ---------------------------------------------------------------- kayıt doğrulama

#[tokio::test]
async fn save_host_validation_and_upsert_match_python() {
    // Yalnız IP literali ya da sayısal biçim: ad çözümü yok (kahin ağsız).
    let existing = r#"[{"name":"a","base_url":"http://10.0.0.1","token":"T","grpc_url":"http://10.0.0.1:1","extra_urls":["http://10.0.0.9"],"k":1}]"#;
    let mk = |args: Value, ex: Option<&str>| json!({"args": args, "existing": ex});
    let cases = vec![
        mk(json!(["a", "http://10.0.0.2", "t", "", "", "tr"]), None),
        mk(
            json!([
                " b ",
                " http://10.0.0.2/ ",
                " t ",
                "",
                "http://10.0.0.3,\nhttp://10.0.0.4/",
                "en"
            ]),
            None,
        ),
        mk(json!(["A", "http://10.0.0.1", "t", "", "", "tr"]), None),
        mk(json!(["1a", "http://10.0.0.1", "t", "", "", "en"]), None),
        mk(json!(["a.b", "http://10.0.0.1", "t", "", "", "en"]), None),
        mk(json!(["local", "http://10.0.0.1", "t", "", "", "tr"]), None),
        mk(json!(["a", "ftp://x", "t", "", "", "tr"]), None),
        mk(json!(["a", "HTTP://10.0.0.1", "t", "", "", "tr"]), None),
        mk(json!(["a", "10.0.0.1", "t", "", "", "en"]), None),
        mk(json!(["a", "http://10.0.0.1", "t", "x", "", "en"]), None),
        mk(
            json!([
                "a",
                "http://10.0.0.1",
                "t",
                "",
                "http://10.0.0.2, nope",
                "en"
            ]),
            None,
        ),
        mk(
            json!(["a", "http://127.0.0.1:18765", "t", "", "", "tr"]),
            None,
        ),
        mk(json!(["a", "http://127.1", "t", "", "", "tr"]), None),
        mk(json!(["a", "http://2130706433", "t", "", "", "tr"]), None),
        mk(
            json!(["a", "http://[::ffff:169.254.169.254]", "t", "", "", "tr"]),
            None,
        ),
        mk(json!(["a", "http://0.0.0.0", "t", "", "", "tr"]), None),
        mk(
            json!([
                "a",
                "http://10.0.0.1",
                "t",
                "http://169.254.169.254",
                "",
                "tr"
            ]),
            None,
        ),
        mk(
            json!(["a", "http://10.0.0.1", "t", "", "http://127.0.0.1:1", "tr"]),
            None,
        ),
        mk(
            json!([
                "a",
                "http://10.0.0.1",
                "t",
                "",
                "http://127.0.0.1:18765",
                "tr"
            ]),
            None,
        ),
        mk(json!(["b", "http://10.0.0.1", "", "", "", "en"]), None),
        mk(
            json!(["a", "http://10.0.0.2", "", "", "", "tr"]),
            Some(existing),
        ),
        mk(
            json!([
                "a",
                "http://10.0.0.2",
                "N",
                "http://10.0.0.2:2",
                "http://10.0.0.8",
                "tr"
            ]),
            Some(existing),
        ),
        mk(
            json!(["b", "http://10.0.0.2", "", "", "", "tr"]),
            Some(existing),
        ),
        mk(
            json!(["a", "http://10.0.0.2", "t", "", "", "tr"]),
            Some("{"),
        ),
        mk(
            json!(["a", "http://10.0.0.2", "t", "", "", "en"]),
            Some("{\"a\":1}"),
        ),
        mk(
            json!(["a", "http://10.0.0.2", "t", "", "", "tr"]),
            Some("  "),
        ),
        mk(
            json!(["c", "http://10.0.0.2", "t", "", "", "tr"]),
            Some(r#"[{"name":"a","token":"T"}, 3, {"base_url":"u"}]"#),
        ),
        mk(
            json!([
                "t",
                "http://10.0.0.1\n/",
                "tok",
                "http://10.0.0.2 /\t/",
                "http://10.0.0.3 /, http://10.0.0.4/\u{2028}/\u{1c}/",
                "tr"
            ]),
            None,
        ),
    ];
    let py = oracle(json!({ "save_host": cases }));
    let ports = guard::reach_loopback_ports(None);
    let mut rust = Vec::new();
    for c in &cases {
        let a: Vec<String> = serde_json::from_value(c["args"].clone()).unwrap();
        let lang = a[5].as_str();
        let current = record::parse_document(c["existing"].as_str().unwrap_or("").as_bytes());
        let r = match Draft::new(&a[0], &a[1], &a[2], &a[3], &a[4], &ports).await {
            Err(e) => Err(e),
            Ok(d) => d.apply(&current),
        };
        rust.push(match r {
            Err(e) => json!({"result": {"ok": false, "error": e.message(lang)}, "hosts": null}),
            Ok(hosts) => json!({"result": {"ok": true}, "hosts": record::to_document(&hosts)}),
        });
    }
    compare("save_host", &cases, py["save_host"].as_array().unwrap(), &rust, &[
        (mk(json!(["c", "http://10.0.0.2", "t", "", "", "tr"]), Some(r#"[{"name":"a","token":"T"}, 3, {"base_url":"u"}]"#)),
         "Rust `to_value` eksik `base_url`i boş metinle yazar; Python kaydı olduğu gibi bırakır (yazım cops-state'te)"),
    ]);
}

// ---------------------------------------------------------------- indirgeme

fn status_json(s: &HostStatus) -> Value {
    json!({"ok": s.ok, "error": s.error, "sessions": s.sessions, "closed": s.closed, "retired": s.retired,
           "cli_list": s.cli_list, "cli_options": s.cli_options, "dups": s.dups, "disk_clean": s.disk_clean,
           "orphan_watch": s.orphan_watch, "fwd": s.fwd, "build_running": s.build_running})
}

/// Python sözlüğünün anahtarlarıyla sınırlı Rust görünümü.
fn like(py: &Value, rust: Value) -> Value {
    match (py.as_object(), rust) {
        (Some(p), Value::Object(r)) => Value::Object(
            p.keys()
                .filter_map(|k| r.get(k).map(|v| (k.clone(), v.clone())))
                .collect(),
        ),
        (_, r) => r,
    }
}

#[test]
fn status_reduction_matches_python() {
    let now = 1000.0;
    let base = |extra: Value| {
        let mut o = json!({"ok": true, "sessions": []});
        for (k, v) in extra.as_object().unwrap() {
            o[k] = v.clone();
        }
        json!({"host": "h", "now": now, "raw": o})
    };
    let mut cases = vec![
        base(
            json!({"sessions": [{"name": "a", "host": "local"}, 5, "x", {"name": "b"}], "closed": "x", "retired": null}),
        ),
        base(json!({"cli_list": ["claude"], "dups": ["a"], "disk_clean": {"a": 1}})),
        base(
            json!({"cli_options": {"claude": {"models": ["m"], "effort_levels": "x"}, "codex": 5}}),
        ),
        base(json!({"cli_options": []})),
        base(json!({"cli_options": "x", "disk_clean": [1], "dups": null, "cli_list": null})),
        base(json!({"cli_list": {}, "dups": 0})),
        base(json!({"ok": false, "error": "e"})),
        base(json!({"ok": 0})),
        base(json!({"ok": "yes", "sessions": [{"name": "y"}]})),
        json!({"host": "h", "now": now, "raw": {"sessions": [{"name": "n"}]}}),
        base(json!({"cli_list": "abc", "dups": {"a": 1}})),
    ];
    for ow in [
        json!({"servers": 3, "procs": "4", "last_end": 9}),
        json!({"servers": "x"}),
        json!({"servers": []}),
        json!({"servers": [1]}),
        json!({"servers": 1.9, "procs": true}),
        json!({"servers": " 7 "}),
        json!({"servers": "+7", "procs": -1.5}),
        json!({"servers": "", "procs": {}}),
        json!("x"),
        json!(null),
        json!({"servers": "1.5"}),
        json!({"servers": {"a": 1}}),
    ] {
        cases.push(base(json!({"orphan_watch": ow})));
    }
    for fwd in [
        json!({"mode": "accept", "kids": ["a", 1, true, null, "e"], "now": 1000.26}),
        json!({"now": "1000.04"}),
        json!({"now": true}),
        json!({"now": [1]}),
        json!({"kids": 5}),
        json!({"kids": {}}),
        json!({"kids": ""}),
        json!({"mode": 5}),
        json!({"mode": 0}),
        json!({"mode": true}),
        json!({"now": null, "kids": null}),
        json!({"now": 1000.25}),
        json!({"now": 1000.35}),
        json!({"now": 1000.05}),
        json!({"now": 999.75}),
        json!({"now": 1002.675}),
        json!({"now": 0}),
        json!({"now": " 1e3 "}),
        json!({"now": "nan"}),
        json!({"now": "-inf"}),
        json!({"now": "Infinity"}),
        json!("x"),
        json!([]),
        json!({"kids": "abc"}),
        json!({"kids": {"a": 1}}),
    ] {
        cases.push(base(json!({"fwd": fwd})));
    }
    for b in [
        json!({"running": "abcdef0123456789"}),
        json!({"running": 123}),
        json!({"running": true}),
        json!({"running": ""}),
        json!({"running": 0}),
        json!("x"),
        json!({"running": null}),
        json!({"running": [1]}),
        json!({"running": 1.5}),
    ] {
        cases.push(base(json!({"build": b})));
    }
    let py = oracle(json!({ "finalize": cases }));
    let py: Vec<Value> = py["finalize"]
        .as_array()
        .unwrap()
        .iter()
        .map(|o| o["ok"].clone())
        .collect();
    let rust: Vec<Value> = cases
        .iter()
        .zip(&py)
        .map(|(c, p)| like(p, status_json(&status::finalize("h", &c["raw"], now))))
        .collect();
    compare("finalize", &cases, &py, &rust, &[]);
}

#[test]
fn ws_frames_match_python() {
    let status_frames = vec![
        json!(
            r#"{"type":"status","data":{"sessions":[{"name":"a"}],"closed":[],"cli_list":["c"],"build":{"running":"x"},"other":1}}"#
        ),
        json!(r#"{"type":"status","data":{"sessions":5}}"#),
        json!(r#"{"type":"status","data":{"sessions":null}}"#),
        json!(r#"{"type":"status","data":{}}"#),
        json!(r#"{"type":"status","data":[1]}"#),
        json!(r#"{"type":"status"}"#),
        json!(r#"{"type":"term","data":{"ok":true}}"#),
        json!("[1,2]"),
        json!("not json"),
        json!("5"),
        json!(""),
    ];
    let term_frames = vec![
        json!(r#"{"type":"term","data":{"ok":true,"text":"x"}}"#),
        json!(r#"{"type":"term","data":"x"}"#),
        json!(r#"{"type":"status","data":{"sessions":[]}}"#),
        json!("[]"),
        json!("null"),
    ];
    let py = oracle(json!({"ws_status": status_frames, "ws_term": term_frames}));
    // Python sözlüğü yok alanları `None` taşır; Rust hiç yazmaz: `finalize` ikisini aynı okur, karşılaştırmada atılır.
    let strip = |v: &Value| match v {
        Value::Object(o) => Value::Object(
            o.iter()
                .filter(|(_, v)| !v.is_null())
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect(),
        ),
        other => other.clone(),
    };
    let run = |frames: &[Value], parse: ws::Parser| -> Vec<Value> {
        frames
            .iter()
            .map(|f| {
                ws::decode_frame(f.as_str().unwrap().as_bytes(), parse)
                    .ok()
                    .flatten()
                    .unwrap_or(Value::Null)
            })
            .collect()
    };
    let py_s: Vec<Value> = py["ws_status"]
        .as_array()
        .unwrap()
        .iter()
        .map(strip)
        .collect();
    compare(
        "ws_status",
        &status_frames,
        &py_s,
        &run(&status_frames, ws::parse_status_frame),
        &[],
    );
    let py_t: Vec<Value> = py["ws_term"].as_array().unwrap().to_vec();
    compare(
        "ws_term",
        &term_frames,
        &py_t,
        &run(&term_frames, ws::parse_term_frame),
        &[],
    );
    // Atlama (loglanan) ile ilgisiz kare ayrımı Python `_ws_envelope` ile aynı: yalnız JSON nesnesi olmayan atlanır.
    for (raw, skipped) in [
        ("[1]", true),
        ("x", true),
        ("", true),
        ("5", true),
        (r#"{"type":"x"}"#, false),
    ] {
        assert_eq!(
            ws::decode_frame(raw.as_bytes(), ws::parse_status_frame).is_err(),
            skipped,
            "{raw}"
        );
    }
}

fn status_of(v: &Value) -> HostStatus {
    let mut s = if v["ok"] == true {
        HostStatus::default()
    } else {
        HostStatus::failed(v["error"].as_str().unwrap_or(""))
    };
    s.ok = v["ok"] == true;
    s.sessions = v["sessions"].as_array().cloned().unwrap_or_default();
    s
}

#[test]
fn poll_cache_tier_and_merge_match_python() {
    let ok = |n: &str| json!({"ok": true, "error": null, "sessions": [{"name": n}]});
    let bad = |e: &str| json!({"ok": false, "error": e, "sessions": []});
    let seqs = vec![
        json!([
            bad("e1"),
            bad("e2"),
            bad("e3"),
            bad("e4"),
            bad("e5"),
            bad("e6")
        ]),
        json!([
            ok("a"),
            bad("e1"),
            bad("e2"),
            bad("e3"),
            bad("e4"),
            bad("e5"),
            bad("e6"),
            ok("b"),
            bad("e7")
        ]),
        json!([ok("a"), ok("b"), bad("e1"), ok("c")]),
    ];
    let tiers = vec![
        json!(["grpc", "rest", "rest", "rest", "rest", "rest", "rest", "ws"]),
        json!(["ws", "rest", "ws", "rest", "rest", "rest", "rest", "rest", "grpc"]),
        json!(["rest", "ws", "grpc", "ws", "ws", "ws", "ws", "ws"]),
    ];
    let now = 2000.0;
    let rows_a = json!({"ok": true, "sessions": [{"name": "Zed", "cwd": "/b"}, {"name": "alpha", "cwd": "/z"}, 5, {"cwd": "/a"},
                                     {"name": 7, "cwd": "/c"}], "closed": [{"name": "c1"}], "retired": "x",
                        "cli_options": {"claude": {"models": ["m"]}}, "fwd": {"mode": "accept", "now": 2001.04}});
    let local = json!({"sessions": [{"name": "beta", "cwd": "/y", "host": "local"}, {"name": "Alpha", "cwd": "/a", "host": "local"}],
                       "closed": [{"name": "zz", "host": "local"}], "retired": []});
    let merges = vec![
        json!({"fleet_sort": "name", "hosts": [{"name": "a"}, {"name": "b"}, {"name": "c"}], "raw": {"a": rows_a},
               "failed": {"c": "down"}, "payload": local, "mirrors": null, "now": now}),
        json!({"fleet_sort": "cwd", "hosts": [{"name": "a"}], "raw": {"a": rows_a}, "payload": local,
               "mirrors": ["a:alpha", "a:None", "a:7"], "now": now}),
        json!({"fleet_sort": "", "hosts": [], "raw": {}, "payload": local, "mirrors": [], "now": now}),
    ];
    let py = oracle(json!({"record": seqs, "tiers": tiers, "merge": merges}));

    let rust: Vec<Value> = seqs
        .iter()
        .map(|seq| {
            let book = StatusBook::default();
            Value::Array(
                seq.as_array()
                    .unwrap()
                    .iter()
                    .map(|r| {
                        book.record("h", status_of(r), now);
                        let c = book.cached("h");
                        json!({"cached": c.map(|c| json!({"ok": c.ok, "error": c.error, "sessions": c.sessions})),
                               "streak": book.fail_streak("h")})
                    })
                    .collect(),
            )
        })
        .collect();
    compare(
        "record",
        &seqs,
        py["record"].as_array().unwrap(),
        &rust,
        &[],
    );

    let tier_of = |s: &str| match s {
        "grpc" => Tier::Grpc,
        "ws" => Tier::Ws,
        _ => Tier::Rest,
    };
    let rust: Vec<Value> = tiers
        .iter()
        .map(|seq| {
            let b = TierBook::default();
            Value::Array(
                seq.as_array()
                    .unwrap()
                    .iter()
                    .map(|t| {
                        b.update("h", tier_of(t.as_str().unwrap()));
                        json!(b.get("h").as_str())
                    })
                    .collect(),
            )
        })
        .collect();
    compare("tiers", &tiers, py["tiers"].as_array().unwrap(), &rust, &[]);

    let rust: Vec<Value> = merges
        .iter()
        .map(|m| {
            let book = StatusBook::default();
            for (name, raw) in m["raw"].as_object().unwrap() {
                book.record(name, status::finalize(name, raw, now), now);
            }
            for (name, err) in m
                .get("failed")
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default()
            {
                book.record(&name, HostStatus::failed(err.as_str().unwrap()), now);
            }
            let hosts: Vec<HostRecord> = m["hosts"]
                .as_array()
                .unwrap()
                .iter()
                .filter_map(HostRecord::from_value)
                .collect();
            let mirrors: Option<HashSet<String>> = m["mirrors"]
                .as_array()
                .map(|a| a.iter().map(|v| v.as_str().unwrap().to_string()).collect());
            let mut payload: Map<String, Value> = m["payload"].as_object().unwrap().clone();
            book.merge_status(
                &mut payload,
                &hosts,
                mirrors.as_ref(),
                m["fleet_sort"] == "cwd",
            );
            Value::Object(payload)
        })
        .collect();
    compare(
        "merge",
        &merges,
        py["merge"].as_array().unwrap(),
        &rust,
        &[],
    );
}

#[test]
fn steward_client_parts_match_python() {
    let transport = vec![
        json!(["a", {"ok": false, "error": "a unreachable: x"}, 200]),
        json!(["a", {"ok": false, "error": "a unreachable: x"}, 0]),
        json!(["a", {"ok": false, "error": "a unreachable: x"}, 500]),
        json!(["a", {"ok": false, "error": "ab unreachable: x"}, 200]),
        json!(["a", {"ok": false, "error": "a unreachable:"}, 200]),
        json!(["a", {"ok": false, "error": "a unreachable"}, 200]),
        json!(["a", {"ok": 0, "error": "a unreachable: x"}, 200]),
        json!(["a", {"ok": false, "error": 5}, 200]),
        json!(["a", {}, 502]),
        json!(["a", {}, 503]),
        json!(["a", {}, 504]),
        json!(["a", {}, 404]),
        json!(["a", {"ok": false, "error": "not_found"}, 200]),
    ];
    let now = 5000.0;
    let fresh = vec![
        json!({"st": {"ok": true, "last_ok_at": 4990.0}, "now": now}),
        json!({"st": {"ok": true, "last_ok_at": 4940.0}, "now": now}),
        json!({"st": {"ok": true, "last_ok_at": 4939.9}, "now": now}),
        json!({"st": {"ok": false, "last_ok_at": 4999.0}, "now": now}),
        json!({"st": {"ok": true, "last_ok_at": 0}, "now": now}),
        json!({"st": {"ok": true}, "now": now}),
        json!({"st": null, "now": now}),
    ];
    let rows = json!([{"name": "a", "running": 1}, {"name": "b", "running": true}, {"name": "b", "running": "yes"},
                      {"name": "c", "running": 0}, {"name": "C", "running": true}, {"name": "d_1", "running": true}, 5]);
    let mut running = Vec::new();
    for name in ["a", "b", "c", "d", "x"] {
        running.push(json!({"st": {"ok": true, "last_ok_age": 1.0, "sessions": rows}, "name": name, "backoff": false}));
    }
    running.push(json!({"st": {"ok": true, "last_ok_age": 1.0, "sessions": rows}, "name": "a", "backoff": true}));
    running.push(json!({"st": {"ok": true, "last_ok_age": 120.0, "sessions": rows}, "name": "a", "backoff": false}));
    running.push(json!({"st": {"ok": false, "last_ok_age": 1.0, "sessions": rows}, "name": "a", "backoff": false}));
    running.push(json!({"st": null, "name": "a", "backoff": false}));
    let health_cases = vec![
        json!({"st": {"ok": true, "last_ok_at": now - 5.5}, "backoff": false, "api": 2, "last_try": now - 1.0, "now": now}),
        json!({"st": {"ok": true, "last_ok_at": now - 5.0}, "backoff": true, "api": null, "last_try": now - 3.0, "now": now}),
        json!({"st": {"ok": false, "error": "x".repeat(200), "last_ok_at": now - 61.0}, "backoff": false, "api": 0, "last_try": 0, "now": now}),
        json!({"st": {"ok": true, "last_ok_at": now - 61.0}, "backoff": false, "api": null, "last_try": now - 2.0, "now": now}),
        json!({"st": null, "backoff": false, "api": null, "last_try": 0, "now": now}),
        json!({"st": null, "backoff": true, "api": 3, "last_try": now - 9.9, "now": now}),
    ];
    let py = oracle(
        json!({"is_transport_error": transport, "host_fresh": fresh, "running_row": running,
                           "health": health_cases}),
    );

    let rust: Vec<Value> = transport
        .iter()
        .map(|c| {
            json!(health::is_transport_error(
                c[0].as_str().unwrap(),
                &c[1],
                c[2].as_u64().unwrap() as u16
            ))
        })
        .collect();
    compare(
        "is_transport_error",
        &transport,
        py["is_transport_error"].as_array().unwrap(),
        &rust,
        &[],
    );

    let st_of = |v: &Value| (!v.is_null()).then(|| status_of(v));
    let rust: Vec<Value> = fresh
        .iter()
        .map(|c| {
            let st = st_of(&c["st"]);
            json!(health::host_fresh(
                st.as_ref(),
                c["st"]["last_ok_at"].as_f64().unwrap_or(0.0),
                now
            ))
        })
        .collect();
    compare(
        "host_fresh",
        &fresh,
        py["host_fresh"].as_array().unwrap(),
        &rust,
        &[],
    );

    let rust: Vec<Value> = running
        .iter()
        .map(|c| {
            let st = st_of(&c["st"]);
            let last = c["st"]["last_ok_age"].as_f64().map_or(0.0, |a| now - a);
            if !health::host_fresh(st.as_ref(), last, now) || c["backoff"] == true {
                return json!([false, null]);
            }
            match health::running_row(st.as_ref(), c["name"].as_str().unwrap()) {
                Err(_) => json!([false, null]),
                Ok(r) => json!([true, r]),
            }
        })
        .collect();
    compare(
        "running_row",
        &running,
        py["running_row"].as_array().unwrap(),
        &rust,
        &[],
    );

    let rust: Vec<Value> = health_cases
        .iter()
        .map(|c| {
            let st = st_of(&c["st"]).map(|mut s| {
                s.error = c["st"]["error"].as_str().map(str::to_string);
                s
            });
            let caps = c["api"].as_i64().map(|api| Capabilities {
                api,
                capabilities: vec![],
            });
            health::health_view(
                st.as_ref(),
                c["st"]["last_ok_at"].as_f64().unwrap_or(0.0),
                c["last_try"].as_f64().unwrap_or(0.0),
                c["backoff"] == true,
                caps.as_ref(),
                now,
            )
        })
        .collect();
    compare(
        "health",
        &health_cases,
        py["health"].as_array().unwrap(),
        &rust,
        &[],
    );
}
