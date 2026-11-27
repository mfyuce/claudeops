//! Python paritesi (bayt bayt): aynı geçici durum dizininde web.py `_instances_list()` (yalnız `find_sessions` sabit ad
//! listesine çevrilir; süreç taraması ayrıca `live.rs`te) ve `diaglog.diag_log_tail(30)` çıktısı `json.dumps` ile alınır,
//! Rust `payload` + `pyjson::dumps` ile karşılaştırılır. Rust okuması dizine hiçbir şey yazmaz (her senaryoda anlık görüntü).
mod common;
use common::{py_db, Env};
use cops_ep_state::{diag, instances, pyjson};
use cops_state::Backend;
use std::collections::{BTreeMap, HashSet};
use std::path::Path;

const PY_INSTANCES: &str = "import types
from claudeops.commands import web as w
LIVE = json.loads(sys.stdin.read())
w.find_sessions = lambda measure_cpu=True, mirrors_out=None: [types.SimpleNamespace(name=n) for n in LIVE]
sys.stdout.write(json.dumps(w._instances_list()))";

fn snapshot(root: &Path) -> BTreeMap<String, Vec<u8>> {
    let mut out = BTreeMap::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(d) = stack.pop() {
        for e in std::fs::read_dir(&d).unwrap() {
            let p = e.unwrap().path();
            let key = p.strip_prefix(root).unwrap().to_string_lossy().into_owned();
            if p.is_dir() {
                out.insert(key, b"<dizin>".to_vec());
                stack.push(p);
            } else {
                out.insert(key, std::fs::read(&p).unwrap());
            }
        }
    }
    out
}

fn mode(b: Backend) -> &'static str {
    match b {
        Backend::Files => "files",
        Backend::Dual => "dual",
        Backend::Db => "db",
    }
}

/// Rust çıktısı (yazımsız) ve Python çıktısı; Python istisna verdiyse `Err(stderr)`.
fn both(
    e: &Env,
    b: Backend,
    live: &[&str],
) -> (Result<String, instances::ListError>, Result<String, String>) {
    let before = snapshot(&e.root);
    let set: HashSet<String> = live.iter().map(|s| s.to_string()).collect();
    let rust = instances::payload(&e.ro(b), &set).map(|v| pyjson::dumps(&v));
    assert_eq!(
        snapshot(&e.root),
        before,
        "Rust okuması dizine yazdı ({b:?})"
    );
    let live_json = format!(
        "[{}]",
        live.iter()
            .map(|n| format!("{n:?}"))
            .collect::<Vec<_>>()
            .join(",")
    );
    let (ok, out, err) = e.py_try(mode(b), PY_INSTANCES, &live_json, &[]);
    (rust, if ok { Ok(out) } else { Err(err) })
}

fn assert_same(e: &Env, b: Backend, live: &[&str]) -> String {
    let (rust, py) = both(e, b, live);
    let py = py.unwrap_or_else(|err| panic!("python hata ({b:?}):\n{err}"));
    let rust = rust.unwrap_or_else(|err| panic!("rust hata ({b:?}): {err}"));
    assert_eq!(rust, py, "{b:?}");
    rust
}

/// Zengin örnek: sıralama eşitlikleri (kararlılık), yedek anahtar, unutulmuş/boş `forgotten`, kayıt içindeki
/// `name`/`host`/`running`/`badge`/`title`, büyük tam sayı, Unicode, beyin ve proje rozetleri, çakışan proje, reviewer
/// kimliği, geçersiz adlar.
fn rich(e: &Env) {
    let odd = "\u{e7}\u{11f} \u{1F600} \u{7f}\u{2028}\u{85}";
    let inst = format!(
        r#"{{"version": 1, "instances": {{
 "ncs20261019": {{"blueprint": "ncs", "cwd": "/w/ncs", "cli": "claude", "created_at": 100, "last_started_at": 300.5}},
 "degnekci": {{"cwd": "/s", "created_at": 50}},
 "degnekci_iso": {{"cwd": "/s", "last_started_at": 300.5}},
 "eski": {{"cwd": "/e", "forgotten": true, "created_at": 999}},
 "unutma": {{"cwd": "/e", "forgotten": "", "created_at": 10}},
 "ç-ad": {{"cwd": "/ü", "note": "{odd}", "created_at": 300.5}},
 "tie2": {{"created_at": 300.5, "last_started_at": 0}},
 "esit-int": {{"created_at": 300}},
 "esit-float": {{"created_at": 300.0}},
 "nokey": {{"cwd": "/n"}},
 "bos-anahtar": {{"created_at": "", "last_started_at": null}},
 "nested": {{"created_at": 1e3, "x": {{"y": [1, 2.50, null, true, -0.0, 1e-7]}}, "name": "ic", "host": "uzak", "running": "?", "badge": "eski", "title": "eski"}},
 "big": {{"created_at": 12345678901234567890}},
 "neg": {{"created_at": -1.5}},
 "ortak20261101": {{"created_at": 5}},
 "rv": {{"created_at": 6}},
 "mtsyn20260909review": {{"created_at": 7}},
 "mtsyn_2": {{"created_at": 8}},
 "mtsyn": {{"created_at": 8}},
 "zz2": {{"created_at": 9}},
 "dup": {{"created_at": 1}},
 "dup": {{"created_at": 2}}
}}}}"#
    );
    e.write("instances.json", inst);
    e.write(
        "steward/projects.json",
        r#"{"ncs": {"phase": "planned"}, "ortak": {}, "mtsyn": {}, "Bad": {}, "x-": {}, "notdict": 5, "zz": {}}"#,
    );
    e.write(
        "steward/stewards/iso/projects.json",
        r#"{"ortak": {}, "zz": {}, "zz2": {}}"#,
    );
    e.write("steward/stewards/rev/projects.json", r#"{"rv": {}}"#);
    e.write("steward/stewards/Upper/projects.json", r#"{"dup": {}}"#);
    e.write("steward/stewards/dosya", "x");
    e.write("steward/services.json", r#"{"svc": {}}"#);
    e.write(
        "settings.json",
        r#"{"stewards": {"rev": {"role": " reviewer "}, "iso": {"role": "steward"}}}"#,
    );
}

#[test]
fn rich_fixture_all_backends() {
    let live = ["ncs20261019", "nokey", "yok", "eski"];
    let e = Env::new();
    rich(&e);
    let out = assert_same(&e, Backend::Files, &live);
    // kendi denetimimiz: rozetler ve sıra gerçekten sınandı
    assert!(
        out.contains("ncs20261019 (de\\u011fnek\\u00e7i: default)"),
        "{out}"
    );
    assert!(out.contains("\\u00b7 iso \\u00b7 beyin"), "{out}");
    assert!(
        !out.contains("ortak20261101 (de"),
        "çakışan proje rozet almamalı: {out}"
    );
    assert!(
        !out.contains("rv (de"),
        "reviewer projesi sayılmamalı: {out}"
    );
    assert!(out.contains("zz2 (de\\u011fnek\\u00e7i: iso)"), "{out}");
    for b in [Backend::Dual, Backend::Db] {
        let e = Env::new();
        py_db(&e, "");
        rich(&e);
        assert_same(&e, b, &live);
    }
}

/// db kipi: kayıtlar ve proje listesi YALNIZ DB'de / dosyadan farklı DB'de. `projects.json` aynası yoksa Python adları hiç
/// okumaz (`os.stat`), varsa DB içeriğini okur.
#[test]
fn db_truth_and_missing_mirror() {
    let e = Env::new();
    py_db(
        &e,
        r#"st.set_doc('instances', {"version": 1, "instances": {"dbden20261111": {"created_at": 2}, "ncs_1": {"created_at": 1}}})
st.set_doc('steward/projects', {"ncs": {}})
st.set_doc('steward/stewards/iso/projects', {"dbden": {}})"#,
    );
    e.write(
        "instances.json",
        r#"{"version": 1, "instances": {"dosyadan": {"created_at": 1}}}"#,
    );
    std::fs::create_dir_all(e.state.join("steward/stewards/iso")).unwrap();
    let out = assert_same(&e, Backend::Db, &[]);
    assert!(
        out.contains("dbden20261111") && !out.contains("dosyadan"),
        "{out}"
    );
    assert!(
        !out.contains("ncs_1 (de"),
        "ayna yokken DB adı sayılmamalı: {out}"
    );
    e.write("steward/projects.json", r#"{"baska": {}}"#);
    let out = assert_same(&e, Backend::Db, &[]);
    assert!(
        out.contains("ncs_1 (de"),
        "ayna varken DB içeriği okunmalı: {out}"
    );
    // dual: dosya doğruluk kaynağı
    let out = assert_same(&e, Backend::Dual, &[]);
    assert!(out.contains("dosyadan"), "{out}");
}

/// Bozuk/olmayan girdiler: kayıt yok, bozuk `instances.json` (files: boş; db: DB satırı), `files` kipinde UTF-8 olmayan
/// `projects.json` (Python `ownership_index` istisnası -> HİÇ rozet yok), boş dosya.
#[test]
fn broken_inputs() {
    let e = Env::new();
    assert_eq!(
        assert_same(&e, Backend::Files, &[]),
        r#"{"ok": true, "instances": []}"#
    );
    e.write("instances.json", "{yarim");
    assert_same(&e, Backend::Files, &[]);
    e.write("instances.json", r#"{"version": 1, "instances": []}"#);
    assert_same(&e, Backend::Files, &[]);
    e.write(
        "instances.json",
        r#"{"version": 1, "instances": {"degnekci": {}, "ncs": {}}}"#,
    );
    e.write("steward/projects.json", b"{\"ncs\": {}, \"x\": \"\xff\"}");
    let out = assert_same(&e, Backend::Files, &[]);
    assert!(!out.contains("badge"), "{out}");
    // dual kipinde aynı bayt Python'da da yakalanır: rozet VAR
    let e2 = Env::new();
    py_db(&e2, "");
    e2.write(
        "instances.json",
        r#"{"version": 1, "instances": {"degnekci": {}, "ncs": {}}}"#,
    );
    e2.write("steward/projects.json", b"{\"ncs\": {}, \"x\": \"\xff\"}");
    let out = assert_same(&e2, Backend::Dual, &[]);
    assert!(out.contains("badge"), "{out}");
    // services.json UTF-8 değil (files): yine hiç rozet
    e.write("steward/projects.json", r#"{"ncs": {}}"#);
    e.write("steward/services.json", b"\xfe");
    let out = assert_same(&e, Backend::Files, &[]);
    assert!(!out.contains("badge"), "{out}");
    // db kipi: bozuk ayna, DB satırı kullanılır
    let e3 = Env::new();
    py_db(
        &e3,
        r#"st.set_doc('instances', {"version": 1, "instances": {"dbde": {}}})"#,
    );
    e3.write("instances.json", "{yarim");
    let out = assert_same(&e3, Backend::Db, &["dbde"]);
    assert!(out.contains(r#""running": true"#), "{out}");
}

/// Python'un istisna verdiği (yanıt yazmadığı) kayıtlar: Rust hata döner (uç 500).
#[test]
fn python_exceptions_are_errors() {
    for (inst, want) in [
        (r#"{"a": 5}"#, "NotDict"),
        (
            r#"{"a": {"created_at": 1}, "b": {"created_at": "x"}}"#,
            "SortType",
        ),
        (
            r#"{"a": {"created_at": {"k": 1}}, "b": {"created_at": {"k": 2}}}"#,
            "SortType",
        ),
    ] {
        let e = Env::new();
        e.write(
            "instances.json",
            format!(r#"{{"version": 1, "instances": {inst}}}"#),
        );
        let (rust, py) = both(&e, Backend::Files, &[]);
        let err = py.expect_err("python istisna vermeliydi");
        assert!(err.contains("Error"), "{err}");
        assert!(format!("{:?}", rust.unwrap_err()).starts_with(want));
    }
}

// ---- diag.log ----------------------------------------------------------------------------------------------------

fn diag_same(e: &Env, content: &[u8]) -> String {
    let path = e.root.join("diag.log");
    std::fs::write(&path, content).unwrap();
    let rust = pyjson::dumps(&diag::payload(&path));
    let (ok, py, err) = e.py_try(
        "files",
        "from claudeops.diaglog import diag_log_tail\nsys.stdout.write(json.dumps({'lines': diag_log_tail(30)}))",
        "",
        &[("CLAUDEOPS_DIAG_LOG", &path)],
    );
    assert!(ok, "{err}");
    assert_eq!(rust, py);
    rust
}

#[test]
fn diag_tail_parity() {
    let e = Env::new();
    // dosya yok
    let (ok, py, _) = e.py_try(
        "files",
        "from claudeops.diaglog import diag_log_tail\nsys.stdout.write(json.dumps({'lines': diag_log_tail(30)}))",
        "",
        &[("CLAUDEOPS_DIAG_LOG", &e.root.join("yok.log"))],
    );
    assert!(ok);
    assert_eq!(py, pyjson::dumps(&diag::payload(&e.root.join("yok.log"))));
    assert_eq!(py, r#"{"lines": []}"#);
    diag_same(&e, b"");
    diag_same(&e, b"\n\n  \n");
    // satır ayıraçları, boşluk kırpma, bozuk UTF-8
    let tricky = b"  ilk \xc3\xa7\r\nikinci\x0bu\x0cv\x1cw\x1dx\x1ey\xc2\x85z\xe2\x80\xa8q\xe2\x80\xa9r\n\n \t \n\xed\xa0\x80bozuk\xff\xfe\xc3(\xe2\x82\n\xf0\x9f\x98\x80 son\x1f\r";
    diag_same(&e, tricky);
    // 40 satır: son 30
    let many: String = (0..40)
        .map(|i| format!("{{\"ts\": \"t\", \"event\": \"e{i}\"}}\n"))
        .collect();
    let out = diag_same(&e, many.as_bytes());
    assert!(
        out.contains("e39") && out.contains("e10") && !out.contains("\"e9\""),
        "{out}"
    );
    // pencereden büyük dosya: pencere sınırı çok baytlı karakterin ortasına düşer, ilk (yarım) satır atılır
    let mut big = Vec::new();
    while big.len() < diag::TAIL_WINDOW as usize + 1000 {
        big.extend_from_slice("ğüşiöç satır dolgu ".repeat(7).as_bytes());
        big.push(b'\n');
    }
    big.extend_from_slice(b"son satir\n");
    let out = diag_same(&e, &big);
    assert!(out.contains("son satir"));
    // pencere tam bir satır sonunda başlıyor
    let line = b"0123456789abcde\n"; // 16 bayt
    let big2: Vec<u8> = line.repeat((diag::TAIL_WINDOW as usize / 16) + 3);
    diag_same(&e, &big2);
}
