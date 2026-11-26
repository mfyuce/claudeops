//! `store.py` (log, dışa/içe aktarım, yedek, tsv_files) ve `statedocs.py` (`mirror_log`, `on_corrupt`) paritesi;
//! `.corrupt-<sha8>` yedeği ve `atomic_write_text`.
use cops_state::fsutil::atomic_write_text;
use cops_state::statedocs::Read;
use cops_state::{settings, Backend, Json, Store};
use std::cell::Cell;
use std::os::unix::fs::PermissionsExt;

mod common;
use common::{j, Env};

const STORE: &str = "from claudeops.store import default_store\nst = default_store()\n";

/// DB içeriği (zaman damgasız): docs (ad, gövde, sürüm), tsv_rows, log (akış, ts, gövde).
const DUMP: &str = r#"
from claudeops.store import default_store
c = default_store()._conn()
print(json.dumps({
  'docs': [list(r) for r in c.execute('SELECT name, body, version FROM docs ORDER BY name').fetchall()],
  'tsv': [list(r) for r in c.execute('SELECT file,seq,kind,active,name,c1,c2,c3,c4,cols,raw FROM tsv_rows ORDER BY file,seq').fetchall()],
  'log': [list(r) for r in c.execute('SELECT stream, ts, body FROM log ORDER BY id').fetchall()],
}, ensure_ascii=False))
"#;

/// [`DUMP`]; yerel zamanla eklenen günlük satırlarının `ts`si sıfırlanır (içe aktarılanlar veriden gelir, aynıdır).
fn dump(e: &Env) -> String {
    let mut v = j(e.py("db", DUMP).trim_end());
    for row in v.as_object_mut().unwrap()["log"].as_array_mut().unwrap() {
        let r = row.as_array_mut().unwrap();
        if r[2].as_str() == Some("\"var\"") {
            r[1] = Json::Int(0);
        }
    }
    v.to_compact()
}

#[test]
fn log_functions_match_python() {
    let e = Env::new();
    e.py("db", &format!("{STORE}for i in range(5):\n    st.append_log('a', {{'i': i, 'ş': [1.5]}})\nst.append_log('b', 'x')"));
    let s = Store::open(&e.dir().db()).unwrap();
    for i in 5..9 {
        let id = s
            .append_log("a", &j(&format!(r#"{{"i": {i}, "ş": [1.5]}}"#)))
            .unwrap();
        assert!(id > 0);
    }
    s.append_log("c", &j("null")).unwrap();
    let rs_view = |s: &Store| -> String {
        let rows = |v: Vec<cops_state::store::LogRow>| {
            Json::Array(
                v.into_iter()
                    .map(|r| Json::Array(vec![Json::Int(r.id), r.body]))
                    .collect(),
            )
        };
        Json::Array(vec![
            rows(s.read_log("a", 3, 2).unwrap()),
            rows(s.read_log("a", 100, 0).unwrap()),
            rows(s.read_log("a", -1, 7).unwrap()),
            rows(s.tail_log("a", 2).unwrap()),
            rows(s.tail_log("yok", 2).unwrap()),
            Json::Array(
                s.list_streams()
                    .unwrap()
                    .into_iter()
                    .map(Json::from)
                    .collect(),
            ),
        ])
        .to_compact()
    };
    let py_view = |e: &Env| {
        e.py(
            "db",
            &format!(
                "{STORE}r = lambda v: [[i, b] for i, t, b in v]\nprint(json.dumps([r(st.read_log('a', 3, 2)), r(st.read_log('a')), r(st.read_log('a', -1, 7)), \
                 r(st.tail_log('a', 2)), r(st.tail_log('yok', 2)), st.list_streams()], ensure_ascii=False))"
            ),
        )
    };
    assert_eq!(rs_view(&s), py_view(&e).trim_end());
    // kırpma: Rust 3 bırakır, Python aynı sayıyı görür; Python 0 bırakır
    assert_eq!(s.trim_log("a", 3).unwrap(), 6);
    assert_eq!(
        e.py(
            "db",
            &format!(
                "{STORE}print(len(st.read_log('a')), st.trim_log('a', 10), st.trim_log('b', 0))"
            )
        )
        .trim(),
        "3 0 1"
    );
    assert_eq!(rs_view(&s), py_view(&e).trim_end());
}

#[test]
fn export_import_backup_match_python() {
    let (a, b, c) = (Env::new(), Env::new(), Env::new());
    a.py(
        "db",
        &format!(
            "{STORE}st.set_doc('hosts', [{{'ş': 1.0}}]); st.set_doc('steward/x', {{'a': None}})\n\
             st.replace_tsv('roster.tsv', 'a\\tb\\n#c\\td\\n\\n'); st.replace_tsv('models.tsv', '')\n\
             st.append_log('s1', {{'k': 1}}); st.append_log('s1', [2]); st.append_log('s2', 'z')"
        ),
    );
    let sa = Store::open(&a.dir().db()).unwrap();
    let mut rs_exp = sa.export_all().unwrap();
    let py_exp = j(a
        .py(
            "db",
            &format!("{STORE}print(json.dumps(st.export_all(), ensure_ascii=False))"),
        )
        .trim_end());
    let mut py_exp2 = py_exp.clone();
    for x in [&mut rs_exp, &mut py_exp2] {
        x.as_object_mut()
            .unwrap()
            .insert("exported".into(), Json::Int(0));
    }
    assert_eq!(rs_exp.to_compact(), py_exp2.to_compact());

    // içe aktarım: Rust b'ye, Python c'ye aynı veriyi; sonra aynı veri tekrar (log atlanır)
    for e in [&b, &c] {
        e.py("db", &format!("{STORE}st.append_log('s2', 'var')"));
    }
    let sb = Store::open(&b.dir().db()).unwrap();
    let n1 = sb.import_all(&py_exp).unwrap();
    let n2 = sb.import_all(&py_exp).unwrap();
    let counts = |n: cops_state::store::ImportCounts| {
        format!("{} {} {} {}", n.docs, n.tsv, n.logs, n.logs_skipped)
    };
    let py_counts = c.py_in(
        "db",
        &format!("{STORE}d = json.load(sys.stdin)\nfor _ in range(2):\n    n = st.import_all(d); print(n['docs'], n['tsv'], n['logs'], n['logs_skipped'])"),
        &py_exp.to_compact(),
    );
    assert_eq!(format!("{}\n{}\n", counts(n1), counts(n2)), py_counts);
    assert_eq!(dump(&b), dump(&c));

    // hatalı girdiler: ikisi de hata verir ve hatadan önceki adımlar ikisinde de yazılmış kalır
    let bad = [
        r#"{"format": 2}"#,
        r#"{"format": "1", "docs": {"y": 1}}"#,
        r#"{"format": 1.7, "docs": {"z": 2}, "tsv": {"t.tsv": 5}}"#,
        r#"{"format": true, "docs": []}"#,
        r#"{"format": "x"}"#,
        r#"{"format": 1, "logs": {"n1": [[1, 2]], "n2": [["x", 1]]}}"#,
        r#"{"docs": {"q": 1}}"#,
    ];
    for d in bad {
        let rs = sb.import_all(&j(d));
        let py = c.py_in(
            "db",
            &format!("{STORE}d = json.load(sys.stdin)\ntry:\n    n = st.import_all(d); print(n)\nexcept Exception as ex:\n    print('hata')"),
            d,
        );
        match rs {
            Ok(n) => assert_eq!(
                py.trim(),
                format!(
                    "{{'docs': {}, 'tsv': {}, 'logs': {}, 'logs_skipped': {}}}",
                    n.docs, n.tsv, n.logs, n.logs_skipped
                ),
                "{d}"
            ),
            Err(_) => assert_eq!(py.trim(), "hata", "{d}"),
        }
        assert_eq!(dump(&b), dump(&c), "{d}");
    }

    // yedek: tutarlı kopya, 0600; Python açıp aynı içeriği görür
    let dest = b.root.join("yedek/kopya.db");
    std::fs::create_dir_all(dest.parent().unwrap()).unwrap();
    sb.backup(&dest).unwrap();
    assert_eq!(
        std::fs::metadata(&dest).unwrap().permissions().mode() & 0o777,
        0o600
    );
    let left: Vec<_> = std::fs::read_dir(dest.parent().unwrap()).unwrap().collect();
    assert_eq!(left.len(), 1, "geçici dosya kalmadı");
    let from_backup = b.py(
        "db",
        &format!("from claudeops.store import Store\nst = Store('{}')\nprint(json.dumps(st.export_docs(), ensure_ascii=False), st.schema_version())", dest.display()),
    );
    assert_eq!(
        from_backup.trim_end(),
        format!("{} 2", Json::Object(sb.export_docs().unwrap()).to_compact())
    );
}

#[test]
fn tsv_rows_filter_and_files_match_python() {
    let e = Env::new();
    e.py("db", &format!("{STORE}st.replace_tsv('roster.tsv', 'a\\tb\\n#c\\td\\ne\\n'); st.replace_tsv('models.tsv', 'x\\ty\\n')"));
    let s = Store::open(&e.dir().db()).unwrap();
    let view = |a: Option<bool>| {
        Json::Array(
            s.tsv_rows("roster.tsv", a)
                .unwrap()
                .into_iter()
                .map(|r| {
                    let mut m = cops_state::Map::new();
                    m.insert("seq".into(), Json::Int(r.seq));
                    m.insert("active".into(), r.active.into());
                    m.insert("name".into(), r.name.into());
                    m.insert(
                        "rest".into(),
                        Json::Array(r.rest.into_iter().map(Json::from).collect()),
                    );
                    Json::Object(m)
                })
                .collect(),
        )
    };
    let rs = Json::Array(vec![
        view(None),
        view(Some(true)),
        view(Some(false)),
        Json::Array(s.tsv_files().unwrap().into_iter().map(Json::from).collect()),
    ]);
    let py = e.py(
        "db",
        &format!("{STORE}print(json.dumps([st.tsv_rows('roster.tsv'), st.tsv_rows('roster.tsv', True), st.tsv_rows('roster.tsv', False), st.tsv_files()]))"),
    );
    assert_eq!(rs.to_compact(), py.trim_end());
}

#[test]
fn mirror_log_and_on_corrupt_match_python() {
    for (mode, backend) in [
        ("files", Backend::Files),
        ("dual", Backend::Dual),
        ("db", Backend::Db),
    ] {
        let e = Env::new();
        e.py(mode, STORE);
        let docs = e.docs(backend);
        let inside = e.state.join("diag.log");
        let outside = e.root.join("dis.log");
        assert_eq!(
            docs.mirror_log("diag", &inside, &j(r#"{"m": "ş"}"#)),
            backend != Backend::Files
        );
        assert!(!docs.mirror_log("diag", &outside, &j("1")));
        e.py(
            mode,
            "from claudeops import statedocs\nfrom claudeops.paths import CLAUDEOPS_DIR as D\nstatedocs.mirror_log('diag', os.path.join(D, 'diag.log'), {'m': 'py'})\n\
             statedocs.mirror_log('diag', '/tmp/disarida.log', 2)",
        );
        let got = e.py(mode, &format!("{STORE}print(json.dumps([b for i, t, b in st.read_log('diag')], ensure_ascii=False))"));
        let want = if backend == Backend::Files {
            "[]"
        } else {
            r#"[{"m": "ş"}, {"m": "py"}]"#
        };
        assert_eq!(got.trim_end(), want, "{mode}");

        // bozuk dosya: geri çağrı sayısı Python ile aynı (db-hazır ve hazır olmayan belge)
        for name in ["hosts", "orchdraft"] {
            let p = e.dir().doc_path(name);
            e.write(&format!("{name}.json"), "{bozuk");
            let calls = Cell::new(0);
            let cb = |_: &std::path::Path| calls.set(calls.get() + 1);
            let r = docs.read_with(name, &p, true, Some(&cb));
            let py = e.py(
                mode,
                &format!(
                    "from claudeops import statedocs\nfrom claudeops.paths import CLAUDEOPS_DIR as D\nn = []\n\
                     v = statedocs.read_json('{name}', os.path.join(D, '{name}.json'), 'VARSAYILAN', on_corrupt=n.append)\nprint(len(n), json.dumps(v))"
                ),
            );
            let rs_v = match r {
                Read::Value(v) => v.to_compact(),
                _ => "\"VARSAYILAN\"".into(),
            };
            assert_eq!(
                format!("{} {rs_v}", calls.get()),
                py.trim_end(),
                "{mode} {name}"
            );
        }
    }
}

#[test]
fn sha256_and_corrupt_backup_match_python() {
    let e = Env::new();
    let samples: Vec<Vec<u8>> = (0..70usize)
        .map(|n| (0..n * 7).map(|i| (i * 31 + n) as u8).collect())
        .collect();
    let hex: Vec<String> = samples
        .iter()
        .map(|s| s.iter().map(|b| format!("{b:02x}")).collect())
        .collect();
    let input = Json::Array(hex.iter().map(|h| Json::from(h.as_str())).collect()).to_compact();
    let py = e.py_in(
        "files",
        "import hashlib\nprint(json.dumps([hashlib.sha256(bytes.fromhex(h)).hexdigest() for h in json.load(sys.stdin)]))",
        &input,
    );
    let corrupt_names: Vec<String> = samples
        .iter()
        .enumerate()
        .map(|(i, s)| {
            let p = e.root.join(format!("x{i}"));
            let d = cops_state::fsutil::write_corrupt_copy(&p, s).unwrap();
            d.file_name().unwrap().to_string_lossy().into_owned()
        })
        .collect();
    let py_hex = j(py.trim_end());
    for (i, h) in py_hex.as_array().unwrap().iter().enumerate() {
        assert_eq!(
            corrupt_names[i],
            format!("x{i}.corrupt-{}", &h.as_str().unwrap()[..8])
        );
    }
    // settings._backup_if_corrupt ile aynı karar ve dosya
    let cases: [&[u8]; 7] = [
        b"",
        b"  \n",
        b"{\"a\": 1}",
        b"[1]",
        b"{bozuk",
        b"\xff\xfe",
        b"\xef\xbb\xbf{}",
    ];
    for (i, raw) in cases.iter().enumerate() {
        let (pa, rb) = (Env::new(), Env::new());
        for x in [&pa, &rb] {
            std::fs::write(x.dir().settings_json(), raw).unwrap();
        }
        pa.py("files", "from claudeops import settings\nsettings._backup_if_corrupt(); settings._backup_if_corrupt()");
        let r = settings::backup_if_corrupt(&rb.dir());
        let list = |x: &Env| {
            let mut v: Vec<(String, Vec<u8>, u32)> = std::fs::read_dir(&x.state)
                .unwrap()
                .map(|d| d.unwrap())
                .filter(|d| d.file_name().to_string_lossy().contains("corrupt"))
                .map(|d| {
                    let m = d.metadata().unwrap().permissions().mode() & 0o777;
                    (
                        d.file_name().to_string_lossy().into_owned(),
                        std::fs::read(d.path()).unwrap(),
                        m,
                    )
                })
                .collect();
            v.sort();
            v
        };
        assert_eq!(list(&pa), list(&rb), "durum {i}");
        assert_eq!(r.is_some(), !list(&rb).is_empty(), "durum {i}");
    }
}

#[test]
fn atomic_write_text_matches_python() {
    let (a, b) = (Env::new(), Env::new());
    for e in [&a, &b] {
        std::fs::write(e.state.join("var.txt"), "eski").unwrap();
        std::fs::set_permissions(
            e.state.join("var.txt"),
            std::fs::Permissions::from_mode(0o640),
        )
        .unwrap();
    }
    a.py(
        "files",
        "from claudeops.atomic_json import atomic_write_text as w\nfrom claudeops.paths import CLAUDEOPS_DIR as D\n\
         w(os.path.join(D, 'var.txt'), 'yeni ş\\r\\n'); w(os.path.join(D, 'alt/yeni.txt'), 'x', mode=0o600); w(os.path.join(D, 'umask.txt'), '')",
    );
    let st = &b.state;
    atomic_write_text(&st.join("var.txt"), "yeni ş\r\n", None).unwrap();
    atomic_write_text(&st.join("alt/yeni.txt"), "x", Some(0o600)).unwrap();
    // umask Python alt sürecinde de aynı (kalıtım)
    atomic_write_text(&st.join("umask.txt"), "", None).unwrap();
    for f in ["var.txt", "alt/yeni.txt", "umask.txt"] {
        assert_eq!(a.read(f), b.read(f), "{f}");
        assert_eq!(a.mode(f), b.mode(f), "{f}");
    }
    let names = |e: &Env| {
        let mut v: Vec<String> = std::fs::read_dir(&e.state)
            .unwrap()
            .map(|d| d.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        v.sort();
        v
    };
    assert_eq!(names(&a), names(&b), "geçici dosya kalmadı");
}

/// K1: `replace_tsv` dönüş değeri Python ile aynı (boş metin 0; boş metin yine "empty" satırıyla saklanır).
#[test]
fn replace_tsv_count_matches_python() {
    let (a, b) = (Env::new(), Env::new());
    a.py("db", STORE);
    b.py("db", STORE);
    let texts = [
        "",
        "x\ty\n",
        "",
        "\n",
        "# y\n\na\tb",
        "a\u{2028}b\r\nc",
        "   ",
    ];
    let py = a.py_in(
        "db",
        &format!(
            "{STORE}for t in json.load(sys.stdin):\n    print(json.dumps([st.replace_tsv('a.tsv', t), st.tsv_text('a.tsv'), st.tsv_rows('a.tsv')], ensure_ascii=False))"
        ),
        &Json::Array(texts.iter().map(|t| Json::from(*t)).collect()).to_compact(),
    );
    let s = Store::open(&b.dir().db()).unwrap();
    assert_eq!(s.tsv_text("a.tsv").unwrap(), None);
    let py: Vec<&str> = py.split_terminator('\n').collect();
    assert_eq!(py.len(), texts.len());
    for (t, want) in texts.iter().zip(py) {
        let n = s.replace_tsv("a.tsv", t).unwrap();
        let rows = s.tsv_rows("a.tsv", None).unwrap();
        let rows = rows
            .into_iter()
            .map(|r| {
                Json::Object(
                    [
                        ("seq".to_string(), Json::Int(r.seq)),
                        ("active".to_string(), Json::Bool(r.active)),
                        ("name".to_string(), Json::from(r.name)),
                        (
                            "rest".to_string(),
                            Json::Array(r.rest.into_iter().map(Json::from).collect()),
                        ),
                    ]
                    .into_iter()
                    .collect(),
                )
            })
            .collect();
        let got = Json::Array(vec![
            Json::Int(n as i64),
            s.tsv_text("a.tsv").unwrap().map_or(Json::Null, Json::from),
            Json::Array(rows),
        ]);
        assert_eq!(got.to_compact(), want, "{t:?}");
    }
    assert_eq!(dump(&a), dump(&b));
}
