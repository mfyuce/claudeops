//! Python <-> Rust paritesi: aynı geçici durum dizinine biri yazar, diğeri okur. Python alt süreçte `py/claudeops`i yükler
//! (`HOME` ve `CLAUDEOPS_DIR` geçici; canlı dizine dokunulmaz). `python3` gerekir.
use cops_state::instances::{derived_name, infer_blueprint, Instances, Launch, NewInstance};
use cops_state::roster::{Roster, Tsv, PROVIDERS};
use cops_state::{settings, statedocs, Backend, Json, Map, StateDocs, Store, StoreError};

mod common;
use common::{j, Env};

const STORE: &str = "from claudeops.store import default_store\nst = default_store()\n";

#[test]
fn constants_match_python() {
    let e = Env::new();
    let out = e.py(
        "files",
        "from claudeops import store, statedocs, settings\nfrom claudeops.providers import PROVIDERS\n\
         print(json.dumps({'schema': len(store.MIGRATIONS), 'providers': list(PROVIDERS), 'ready': sorted(statedocs.DB_READY),\n\
         'prefixes': sorted(statedocs.DB_READY_PREFIXES), 'off': sorted(settings._OFF_WORDS)}))\n\
         print(json.dumps(settings.DEFAULT_SETTINGS, ensure_ascii=False))",
    );
    let mut lines = out.lines();
    let c = j(lines.next().unwrap());
    let strs = |k: &str| -> Vec<String> {
        c.get(k)
            .unwrap()
            .as_array()
            .unwrap()
            .iter()
            .map(|x| x.as_str().unwrap().to_string())
            .collect()
    };
    assert_eq!(
        c.get("schema").unwrap().as_i64().unwrap(),
        cops_state::store::SCHEMA_VERSION
    );
    assert_eq!(strs("providers"), PROVIDERS);
    let mut ready = statedocs::DB_READY.to_vec();
    ready.sort_unstable();
    assert_eq!(strs("ready"), ready);
    let mut pre = statedocs::DB_READY_PREFIXES.to_vec();
    pre.sort_unstable();
    assert_eq!(strs("prefixes"), pre);
    assert_eq!(
        Json::Object(settings::defaults().clone()).to_compact(),
        lines.next().unwrap(),
        "default_settings.json Python DEFAULT_SETTINGS'ten ayrıştı"
    );
    for w in strs("off") {
        std::fs::write(
            e.dir().settings_json(),
            Json::Object(
                [("tunnel_watch".to_string(), Json::Str(w.clone()))]
                    .into_iter()
                    .collect(),
            )
            .to_compact(),
        )
        .unwrap();
        assert!(
            !settings::load(&e.dir()).flag_default_on("tunnel_watch"),
            "{w}"
        );
    }
}

#[test]
fn json_bytes_match_python() {
    let e = Env::new();
    let out = e.py(
        "files",
        r#"
import random, struct
random.seed(7)
vals = [0.0, -0.0, 1.0, -1.5, 1e16, 1e15, 9999999999999998.0, 1e-4, 1e-5, 0.0001234, 1e22, 1.7976931348623157e308, 5e-324,
        1764151234.123456, 0.1+0.2, 100.0, 123456789012345678.0, float('inf'), float('-inf'), float('nan')]
for _ in range(4000):
    vals.append(struct.unpack('<d', struct.pack('<Q', random.getrandbits(64)))[0])
    vals.append(random.uniform(-1e6, 1e6))
    vals.append(random.random() * 10 ** random.randint(-30, 30))
strs = [''.join(chr(c) for c in range(0, 200)), 'şçğıİöü — “x” \u2028\u2029 \U0001F600 \\ " /', '']
doc = {'z': 1, 'a': [vals, strs], 'ints': [0, -1, 2**63-1, -2**63, 2**64, -2**70], 'e': {}, 'l': [], 'n': [None, True, False],
       'nest': {'b': {'a': [[], {}, [{'k': 'v'}]]}}, '': 'boş anahtar'}
for d in (doc, [], {}, 'x', 3, 2.5, None):
    for kw in ({}, {'indent': 2}):
        print(json.dumps(json.dumps(d, ensure_ascii=False, **kw)))
    print(json.dumps(json.dumps(d)))
"#,
    );
    let lines: Vec<String> = out
        .lines()
        .map(|l| j(l).as_str().unwrap().to_string())
        .collect();
    assert_eq!(lines.len(), 21);
    for c in lines.chunks(3) {
        let (compact, indented, ascii) = (&c[0], &c[1], &c[2]);
        for src in [compact, indented, ascii] {
            let v = j(src);
            assert_eq!(&v.to_compact(), compact);
            assert_eq!(&v.to_indented(), indented);
        }
    }
    // reddedilenler Python ile aynı
    let bad = [
        "",
        "{",
        "[1,]",
        "{\"a\":1,}",
        "01",
        "1.",
        ".5",
        "+1",
        "'a'",
        "\"a\nb\"",
        "tru",
        "[1] x",
        "\u{feff}1",
        "{1:2}",
        "\"\\x\"",
        "-",
    ];
    let input = Json::Array(bad.iter().map(|s| Json::from(*s)).collect()).to_compact();
    let out = e.py_in(
        "files",
        "n = 0\nfor s in json.load(sys.stdin):\n    try:\n        json.loads(s)\n    except ValueError:\n        n += 1\nprint(n)",
        &input,
    );
    // json.loads(str) BOM'u da reddeder
    assert_eq!(out.trim(), bad.len().to_string());
    for s in bad {
        assert!(Json::parse(s).is_err(), "{s:?}");
    }
    // yinelenen anahtar: son değer, ilk konum
    assert_eq!(
        j(r#"{"a":1,"b":2,"a":3}"#).to_compact(),
        r#"{"a": 3, "b": 2}"#
    );
    // serde yanıtı sırayı korur
    assert_eq!(
        serde_json::to_string(&j(r#"{"z":1,"a":[2.5,null]}"#)).unwrap(),
        r#"{"z":1,"a":[2.5,null]}"#
    );
}

#[test]
fn db_roundtrip_both_ways() {
    let e = Env::new();
    assert!(matches!(
        Store::open(&e.dir().db()),
        Err(StoreError::Missing(_))
    ));
    assert!(!e.dir().db().exists(), "Rust DB oluşturmaz");
    e.py(
        "db",
        &format!("{STORE}st.set_doc('hosts', [{{'name':'yerel','ş':1.0}}]); st.set_doc('steward/quota', {{'t':1764151234.5}}); st.set_doc('steward/a_b', 1); st.set_doc('steward/axb', 2)"),
    );
    let s = Store::open(&e.dir().db()).unwrap();
    assert_eq!(
        s.get_doc_raw("hosts").unwrap().unwrap(),
        r#"[{"name": "yerel", "ş": 1.0}]"#
    );
    assert_eq!(s.doc_version("hosts").unwrap(), 1);
    assert_eq!(s.list_docs("steward/a_").unwrap(), ["steward/a_b"]);
    assert_eq!(s.set_doc("hosts", &j(r#"[{"b":2,"a":1e-05}]"#)).unwrap(), 2);
    s.set_doc("rust/only", &j(r#"{"ü":[1,2]}"#)).unwrap();
    let n = s
        .update_doc("counter", Json::Int(0), |v| {
            Some(Json::Int(v.as_i64().unwrap() + 1))
        })
        .unwrap();
    assert_eq!(n, Json::Int(1));
    s.update_doc("counter", Json::Int(0), |_| None).unwrap();
    assert!(s.delete_doc("steward/axb").unwrap());
    let out = e.py(
        "db",
        &format!(
            "{STORE}\nr = st._conn().execute(\"SELECT body, version FROM docs WHERE name='hosts'\").fetchone()\nprint(r[0]); print(r[1])\n\
             print(json.dumps(st.get_doc('rust/only'), ensure_ascii=False)); print(st.get_doc('counter'), st.doc_version('counter'))\n\
             print(st.list_docs('steward/')); print(st.schema_version())"
        ),
    );
    assert_eq!(
        out.lines().collect::<Vec<_>>(),
        [
            r#"[{"b": 2, "a": 1e-05}]"#,
            "2",
            r#"{"ü": [1, 2]}"#,
            "1 1",
            "['steward/a_b', 'steward/quota']",
            "2"
        ]
    );
    assert_eq!(e.mode("claudeops.db"), 0o600);
    for f in ["claudeops.db-wal", "claudeops.db-shm"] {
        if e.state.join(f).exists() {
            assert_eq!(e.mode(f), 0o600, "{f}");
        }
    }
}

#[test]
fn schema_mismatch_never_writes() {
    let e = Env::new();
    e.py("db", &format!("{STORE}st.set_doc('hosts', [1])"));
    // açıkken Python tarafı sürümü ilerletirse yazım reddedilir
    let docs = e.docs(Backend::Db);
    let open = docs.store().unwrap();
    e.py(
        "files",
        "import sqlite3\nc = sqlite3.connect(os.environ['CLAUDEOPS_DIR'] + '/claudeops.db')\nc.execute('PRAGMA user_version=3'); c.commit()",
    );
    assert!(matches!(
        open.set_doc("hosts", &j("[2]")),
        Err(StoreError::Schema { found: 3 })
    ));
    let docs = e.docs(Backend::Db);
    assert!(matches!(docs.store(), Err(StoreError::Schema { found: 3 })));
    let p = e.dir().doc_path("hosts");
    assert!(docs.write("hosts", &p, &j("[2]"), None).is_err());
    assert!(!p.exists(), "kalıcı hatada ayna da yazılmaz");
    // dual: dosya doğruluk kaynağı, yazım sürer
    let docs = e.docs(Backend::Dual);
    docs.write("hosts", &p, &j("[2]"), None).unwrap();
    assert_eq!(e.read("hosts.json"), "[\n  2\n]");
    // Postgres url: SQLite'a sessizce yazılmaz
    let pg = StateDocs::isolated(e.dir(), Some(Backend::Db), "postgresql://u:gizli@h/d")
        .with_logger(|_| {});
    match pg.store() {
        Err(StoreError::Unsupported(s)) => assert_eq!(s, "postgresql"),
        _ => panic!("Unsupported bekleniyordu"),
    }
}

#[test]
fn statedocs_modes_with_python() {
    for (mode, backend) in [
        ("files", Backend::Files),
        ("dual", Backend::Dual),
        ("db", Backend::Db),
    ] {
        let e = Env::new();
        e.py(mode, STORE); // DB şeması Python'dan
        let doc = r#"{"z": 1.0, "a": ["ş", {}]}"#;
        let docs = e.docs(backend);
        for name in ["steward/quota", "claude_models", "orchdraft"] {
            let pname = format!("{name}.json");
            let path = e.dir().doc_path(name);
            let call = format!(
                "from claudeops import statedocs\nfrom claudeops.paths import CLAUDEOPS_DIR as D\np = os.path.join(D, '{pname}')\n"
            );
            // Python yazar, Rust okur
            e.py(
                mode,
                &format!(
                    "{call}statedocs.write_json('{name}', p, json.loads('{doc}'), mode=0o600)"
                ),
            );
            let py_bytes = e.read(&pname);
            assert_eq!(
                docs.read(name, &path).into_option(),
                Some(j(doc)),
                "{mode} {name}"
            );
            // Rust aynı nesneyi yazar: aynı baytlar
            std::fs::remove_file(&path).unwrap();
            docs.write(name, &path, &j(doc), Some(0o600)).unwrap();
            assert_eq!(e.read(&pname), py_bytes);
            assert_eq!(e.mode(&pname), 0o600);
            // Rust yazar, Python okur
            docs.write(name, &path, &j(r#"{"r": 2}"#), Some(0o600))
                .unwrap();
            let got = e.py(
                mode,
                &format!("{call}print(json.dumps(statedocs.read_json('{name}', p, None)))"),
            );
            assert_eq!(got.trim(), r#"{"r": 2}"#, "{mode} {name}");
            // elle düzenleme: db-hazır belgede db kipi dosyaya BAKMAZ, diğer her durumda dosya geçer
            std::thread::sleep(std::time::Duration::from_millis(15));
            e.write(&pname, r#"{"el": 3}"#);
            let db_truth = backend == Backend::Db && name != "orchdraft";
            let want = if db_truth {
                j(r#"{"r": 2}"#)
            } else {
                j(r#"{"el": 3}"#)
            };
            assert_eq!(
                docs.read(name, &path).into_option(),
                Some(want.clone()),
                "{mode} {name}"
            );
            let in_db = e.py(
                mode,
                &format!("{STORE}print(json.dumps(st.get_doc('{name}')))"),
            );
            match backend {
                Backend::Files => assert_eq!(in_db.trim(), "null"),
                _ => assert_eq!(j(&in_db), want, "{mode} {name}"),
            }
            let py_view = e.py(
                mode,
                &format!("{call}print(json.dumps(statedocs.read_json('{name}', p, None)))"),
            );
            assert_eq!(j(&py_view), want);
        }
        // durum dizini DIŞINDAKİ yol DB'ye dokunmaz
        let outside = e.root.join("dis.json");
        docs.write("hosts", &outside, &j("[9]"), None).unwrap();
        assert_eq!(
            e.py(mode, &format!("{STORE}print(st.get_doc('hosts'))"))
                .trim(),
            "None"
        );
        // name_for
        let nested = e.state.join("steward/stewards/rev/questions.json");
        let py_name = e.py(
            mode,
            &format!(
                "from claudeops import statedocs\nprint(statedocs.name_for('{}'))",
                nested.display()
            ),
        );
        assert_eq!(docs.name_for(&nested), py_name.trim());
    }
}

#[test]
fn db_transient_failure_defers_and_recovers() {
    let e = Env::new();
    e.py("db", &format!("{STORE}st.set_doc('hosts', [1])"));
    let docs = e.docs(Backend::Db);
    let path = e.dir().doc_path("hosts");
    docs.store().unwrap();
    // başka süreç yazar kilidini busy_timeout'tan uzun tutar
    let mut child = e
        .command(
            "db",
            "import sqlite3, time\nc = sqlite3.connect(os.environ['CLAUDEOPS_DIR'] + '/claudeops.db', isolation_level=None)\n\
             c.execute('BEGIN IMMEDIATE'); print('kilit', flush=True); sys.stdin.read(); c.execute('ROLLBACK')",
        )
        .spawn()
        .unwrap();
    let mut line = String::new();
    std::io::BufRead::read_line(
        &mut std::io::BufReader::new(child.stdout.take().unwrap()),
        &mut line,
    )
    .unwrap();
    assert_eq!(line.trim(), "kilit");
    let out = docs.write("hosts", &path, &j("[2]"), None).unwrap();
    assert_eq!(out, cops_state::WriteOutcome::DbDeferred);
    drop(child.stdin.take());
    assert!(child.wait().unwrap().success());
    assert_eq!(docs.read("hosts", &path).into_option(), Some(j("[2]")));
    assert_eq!(
        docs.store().unwrap().get_doc("hosts").unwrap(),
        Some(j("[2]"))
    );
}

#[test]
fn backend_from_settings_file() {
    let e = Env::new();
    let docs = || StateDocs::new(e.dir());
    if std::env::var_os("CLAUDEOPS_STORE_BACKEND").is_some() {
        return;
    }
    assert_eq!(docs().backend(), Backend::Files);
    e.write("settings.json", r#"{"store_backend": " DB "}"#);
    assert_eq!(docs().backend(), Backend::Db);
    e.write("settings.json", r#"{"store_backend": "x"}"#);
    assert_eq!(docs().backend(), Backend::Files);
}

#[test]
fn settings_match_python() {
    let e = Env::new();
    let cases = [
        None,
        Some(""),
        Some("{bozuk"),
        Some("[1,2]"),
        Some(
            r#"{"theme":"dark","bilinmeyen":1,"byok":{"copilot":{"K":"v"}},"history_warn_at":"x"}"#,
        ),
        Some(
            r#"{"stewards":{"zz":{"mode":"act"},"aa":{}},"default_model":[],"cli_managed":null,"steward":3,"ucli_limits":"x","ucli_services":[{"id":"evren"}],"layout_grid":2.0}"#,
        ),
    ];
    let reader = settings::SettingsReader::new(e.dir());
    for c in cases {
        match c {
            None => drop(std::fs::remove_file(e.dir().settings_json())),
            Some(t) => e.write("settings.json", t),
        }
        let py = e.py(
            "files",
            "from claudeops.settings import load_settings\nprint(json.dumps(load_settings(), ensure_ascii=False))",
        );
        let rs = reader.load();
        assert_eq!(
            Json::Object(rs.as_map().clone()).to_compact(),
            py.trim_end_matches('\n'),
            "{c:?}"
        );
    }
}

const ROSTER: &str = "name\tcwd\tmodel\n# yorum satırı\n\nalfa\t/tmp/a/\tm1\tcodex\nbeta\t/tmp/b/../c//d\tm2\t# EMEKLİ not\r\n#gama\t/tmp/g\tm3\tagy\n#delta\t/tmp/d\tm4\nalfa\t/tmp/yinelenen\tm9\tclaude\nikili\t//x/./y\r\neps\t\tm5\n  zeta\t/tmp/z\tm6\tucli  \n# \nyalnizroster\t/tmp/r\tm";
const MODELS: &str = "alfa\tm1\nbeta\tm2\n#gama\tm3\n#delta\tm4\nikili\tm7\n#eps\tm5\nzeta\tm6\nyalnizmodel\tm\nalfa\tm-son\n";

const DUMP_TSV: &str = r#"
from claudeops.store import default_store
st = default_store()
rows = st._conn().execute("SELECT file,seq,kind,active,name,c1,c2,c3,c4,cols,raw FROM tsv_rows ORDER BY file,seq").fetchall()
print(json.dumps([list(r) for r in rows], ensure_ascii=False))
"#;

fn rust_view(docs: &StateDocs) -> Json {
    let r = Roster::new(docs);
    let s = |v: &str| Json::from(v);
    let obj = |v: Vec<(&str, Json)>| -> Json {
        Json::Object(v.into_iter().map(|(k, v)| (k.to_string(), v)).collect())
    };
    let raw = |w| {
        Json::Array(
            r.raw_rows(w)
                .unwrap()
                .iter()
                .map(|x| {
                    obj(vec![
                        ("name", s(&x.name)),
                        ("rest", Json::Array(x.rest.iter().map(|y| s(y)).collect())),
                        ("active", x.active.into()),
                    ])
                })
                .collect(),
        )
    };
    let roster = Json::Array(
        r.entries()
            .unwrap()
            .iter()
            .map(|x| Json::Array(vec![s(&x.name), s(&x.cwd), s(&x.model), s(&x.cli)]))
            .collect(),
    );
    let models = Json::Object(
        r.models()
            .unwrap()
            .into_iter()
            .map(|(k, v)| (k, v.into()))
            .collect(),
    );
    let fleet = Json::Object(
        r.fleet_status()
            .unwrap()
            .into_iter()
            .map(|(k, p)| {
                (
                    k,
                    obj(vec![
                        ("cwd", s(&p.cwd)),
                        ("model", s(&p.model)),
                        ("cli", s(&p.cli)),
                        ("state", s(p.state.as_str())),
                    ]),
                )
            })
            .collect(),
    );
    obj(vec![
        ("raw_roster", raw(Tsv::Roster)),
        ("raw_models", raw(Tsv::Models)),
        ("roster", roster),
        ("models", models),
        ("fleet", fleet),
    ])
}

const PY_VIEW: &str = r#"
from claudeops import roster
from claudeops.commands import web
print(json.dumps({"raw_roster": web._read_tsv_raw(web.ROSTER_TSV), "raw_models": web._read_tsv_raw(web.MODELS_TSV),
 "roster": [[e.name, e.cwd, e.model, e.cli] for e in roster.read_roster()], "models": roster.read_models(),
 "fleet": web._fleet_status()}, ensure_ascii=False))
"#;

#[test]
fn roster_reads_and_writes_match_python() {
    let (a, b) = (Env::new(), Env::new()); // a = Python yazar, b = Rust yazar
    for e in [&a, &b] {
        e.py("dual", STORE);
        e.write("roster.tsv", ROSTER);
        e.write("models.tsv", MODELS);
    }
    let docs = b.docs(Backend::Dual);
    let py = a.py("dual", PY_VIEW);
    assert_eq!(rust_view(&docs).to_compact(), py.trim_end_matches('\n'));

    a.py(
        "dual",
        r#"
from claudeops.commands import web as w
R, M = w.ROSTER_TSV, w.MODELS_TSV
w._append_tsv_line(R, ["yeni", "/tmp/y", "m", "claude"]); w._append_tsv_line(M, ["yeni", "m"])
assert w._toggle_comment(R, "alfa", False); assert w._toggle_comment(M, "gama", True); assert w._toggle_comment(M, "beta", True)
assert w._replace_tsv_line(R, "delta", ["delta2", "/tmp/d2", "mm", "agy"]); assert w._replace_tsv_line(M, "zeta", ["zeta", "z2"])
assert not w._toggle_comment(R, "yok", True)
"#,
    );
    {
        let g = Roster::new(&docs).lock().unwrap();
        g.append(Tsv::Roster, &["yeni", "/tmp/y", "m", "claude"])
            .unwrap();
        g.append(Tsv::Models, &["yeni", "m"]).unwrap();
        assert!(g.set_active(Tsv::Roster, "alfa", false).unwrap());
        assert!(g.set_active(Tsv::Models, "gama", true).unwrap());
        assert!(g.set_active(Tsv::Models, "beta", true).unwrap());
        assert!(g
            .replace(Tsv::Roster, "delta", &["delta2", "/tmp/d2", "mm", "agy"])
            .unwrap());
        assert!(g.replace(Tsv::Models, "zeta", &["zeta", "z2"]).unwrap());
        assert!(!g.set_active(Tsv::Roster, "yok", true).unwrap());
        assert!(g.append(Tsv::Roster, &["x", "a\nb"]).is_err());
    }
    for f in ["roster.tsv", "models.tsv"] {
        assert_eq!(a.read(f).as_bytes(), b.read(f).as_bytes(), "{f}");
        assert_eq!(a.mode(f), b.mode(f), "{f} izin");
    }
    assert_eq!(
        a.py("dual", DUMP_TSV),
        b.py("dual", DUMP_TSV),
        "tsv_rows gölgesi"
    );
    assert_eq!(
        rust_view(&docs).to_compact(),
        a.py("dual", PY_VIEW).trim_end_matches('\n')
    );

    // elle yazılan egzotik içerik, boş ve silinen dosya: gölge yine aynı
    for text in [Some("a\tb\u{2028}c\td\u{0c}\n#\t\n\t\n"), Some(""), None] {
        for e in [&a, &b] {
            match text {
                Some(t) => e.write("roster.tsv", t),
                None => std::fs::remove_file(e.dir().roster_tsv()).unwrap(),
            }
        }
        a.py("dual", "from claudeops import statedocs\nfrom claudeops.paths import ROSTER_TSV\nstatedocs.shadow_tsv(ROSTER_TSV, force=True)");
        docs.shadow_tsv(&b.dir().roster_tsv(), true);
        assert_eq!(a.py("dual", DUMP_TSV), b.py("dual", DUMP_TSV), "{text:?}");
    }
}

#[test]
fn register_project_across_languages() {
    let e = Env::new();
    e.py("dual", STORE);
    let docs = e.docs(Backend::Dual);
    let r = Roster::new(&docs);
    let cwd = e.root.display().to_string();
    let reg = |name: &str, cwd: &str, running: &[(String, String)]| {
        r.register_project(name, cwd, "", "yok", running, |cli| format!("def-{cli}"))
            .map_err(|x| x.code())
    };
    let running = [("zzcalisan20261126".to_string(), "zzcalisan".to_string())];
    assert_eq!(reg("Büyük", &cwd, &[]), Err("invalid_name"));
    assert_eq!(reg("1a", &cwd, &[]), Err("invalid_name"));
    assert_eq!(reg("zzcalisan", &cwd, &running), Err("conflicts_running"));
    assert_eq!(reg("zzyeni", "/yok/boyle", &[]), Err("dir_not_found"));
    assert_eq!(reg("zzyeni", "  ", &[]), Err("dir_not_found"));
    assert_eq!(reg(" zzrust ", &format!(" {cwd} "), &[]), Ok(()));
    assert_eq!(reg("zzrust", &cwd, &[]), Err("already_registered"));
    assert_eq!(
        e.read("roster.tsv"),
        format!("zzrust\t{cwd}\tdef-claude\tclaude\n")
    );
    assert_eq!(e.read("models.tsv"), "zzrust\tdef-claude\n");
    let out = e.py(
        "dual",
        &format!(
            "from claudeops.commands import web as w\nprint(w._register_project('zzrust', '{cwd}')['ok'])\n\
             print(w._register_project('zzpython', '{cwd}', 'm', 'codex')['ok'])\nprint(w._fleet_status()['zzrust']['state'])"
        ),
    );
    assert_eq!(out, "False\nTrue\nactive\n");
    assert_eq!(reg("zzpython", &cwd, &[]), Err("already_registered"));
    assert_eq!(r.fleet_status().unwrap()["zzpython"].cli, "codex");
    e.py(
        "dual",
        &format!("from claudeops import instances as i\ni.record_instance('zzinst', blueprint=None, cwd='{cwd}', cli='claude', model='m', origin='t')"),
    );
    assert_eq!(reg("zzinst", &cwd, &[]), Err("name_in_use"));
}

fn normalized_instances(e: &Env) -> String {
    let mut d = j(&e.read("instances.json"));
    let items = d.as_object_mut().unwrap()["instances"]
        .as_object_mut()
        .unwrap();
    for rec in items.values_mut().filter_map(Json::as_object_mut) {
        for k in ["created_at", "last_started_at"] {
            if let Some(v) = rec.get_mut(k) {
                if v.as_f64().is_some_and(|f| f > 1e9) {
                    *v = Json::from("ZAMAN");
                }
            }
        }
    }
    d.to_indented()
}

#[test]
fn instances_match_python() {
    for (mode, backend) in [("files", Backend::Files), ("db", Backend::Db)] {
        let (a, b) = (Env::new(), Env::new());
        a.py(mode, STORE);
        b.py(mode, STORE);
        a.py(
            mode,
            r#"
from claudeops import instances as i
i.record_instance('p20261126', blueprint='p', cwd='/c', cli='ucli', model='m', origin='new_chat', cli_opts={'service':'evren'})
i.record_instance('q20261126', blueprint=None, cwd='/d', cli='claude', model='s', permission_mode='auto', effort='high', origin='adopt', created_at=5.0)
i.record_instance('p20261126', blueprint='p', cwd='/c2', cli='ucli', model='m2', origin='baska', cli_opts={'service':'claude'})
i.mark_started('p20261126', cli='claude', model='x', permission_mode='', effort='low')
i.mark_started('yok', cli='claude', model='x', permission_mode='', effort='')
assert i.forget_instance('q20261126'); assert not i.forget_instance('q20261126')
i.mark_started('q20261126', cli='claude', model='o', permission_mode='plan', effort='max', cli_opts={'a':1})
assert i.rename_blueprint('p', 'p2') == 1
assert i.add_missing({'q20261126': {}, 'r': {'cwd': '/r'}}) == 1
assert i.forget_instance('r')
"#,
        );
        let docs = b.docs(backend);
        let i = Instances::new(&docs);
        let launch =
            |cli: &str, model: &str, pm: &str, effort: &str, opts: &[(&str, Json)]| Launch {
                cli: cli.into(),
                model: model.into(),
                permission_mode: pm.into(),
                effort: effort.into(),
                cli_opts: opts
                    .iter()
                    .map(|(k, v)| (k.to_string(), v.clone()))
                    .collect(),
            };
        let new =
            |bp: Option<&str>, cwd: &str, origin: &str, at: Option<f64>, l: Launch| NewInstance {
                blueprint: bp.map(Into::into),
                cwd: cwd.into(),
                origin: origin.into(),
                created_at: at,
                launch: l,
            };
        i.record(
            "p20261126",
            &new(
                Some("p"),
                "/c",
                "new_chat",
                None,
                launch("ucli", "m", "", "", &[("service", "evren".into())]),
            ),
        )
        .unwrap();
        i.record(
            "q20261126",
            &new(
                None,
                "/d",
                "adopt",
                Some(5.0),
                launch("claude", "s", "auto", "high", &[]),
            ),
        )
        .unwrap();
        i.record(
            "p20261126",
            &new(
                Some("p"),
                "/c2",
                "baska",
                None,
                launch("ucli", "m2", "", "", &[("service", "claude".into())]),
            ),
        )
        .unwrap();
        i.mark_started("p20261126", &launch("claude", "x", "", "low", &[]))
            .unwrap();
        i.mark_started("yok", &launch("claude", "x", "", "", &[]))
            .unwrap();
        assert!(i.forget("q20261126").unwrap());
        assert!(!i.forget("q20261126").unwrap());
        i.mark_started(
            "q20261126",
            &launch("claude", "o", "plan", "max", &[("a", Json::Int(1))]),
        )
        .unwrap();
        assert_eq!(i.rename_blueprint("p", "p2").unwrap(), 1);
        let add: Map = j(r#"{"q20261126": {}, "r": {"cwd": "/r"}}"#)
            .as_object()
            .unwrap()
            .clone();
        assert_eq!(i.add_missing(&add).unwrap(), 1);
        assert!(i.forget("r").unwrap());
        assert_eq!(normalized_instances(&a), normalized_instances(&b), "{mode}");
        assert_eq!(b.mode("instances.json"), 0o600);
        // çapraz okuma: Python'un yazdığını Rust, Rust'ınkini Python
        let py_load = "from claudeops import instances as i\nprint(json.dumps(i.load_instances(), ensure_ascii=False))";
        let ad = a.docs(backend);
        assert_eq!(
            Json::Object(Instances::new(&ad).load()).to_compact(),
            a.py(mode, py_load).trim_end()
        );
        assert_eq!(
            Json::Object(i.load()).to_compact(),
            b.py(mode, py_load).trim_end()
        );
        // db kipinde ayna silinse de kayıtlar DB'den gelir
        if backend == Backend::Db {
            std::fs::remove_file(b.dir().instances_json()).unwrap();
            assert_eq!(i.load().len(), 3);
        }
        // db kipinde bozuk olan yalnız ayna: DB satırından sürer, ham hali saklanır; diğer kiplerde üstüne yazılmaz
        a.write("instances.json", "{yarim");
        b.write("instances.json", "{yarim");
        let fresh = b.docs(backend);
        if backend == Backend::Db {
            assert_eq!(Instances::new(&fresh).load().len(), 3);
            a.py(
                mode,
                "from claudeops import instances as i\ni.forget_instance('q20261126')",
            );
            i.forget("q20261126").unwrap();
            assert_eq!(normalized_instances(&a), normalized_instances(&b), "{mode}");
            let copies = |e: &Env| {
                let mut v: Vec<String> = std::fs::read_dir(&e.state)
                    .unwrap()
                    .map(|d| d.unwrap().file_name().into_string().unwrap())
                    .filter(|n| n.starts_with("instances.json.corrupt-"))
                    .collect();
                v.sort();
                v
            };
            let kept = copies(&b);
            assert_eq!(kept.len(), 1);
            assert_eq!(copies(&a), kept, "iki dilde aynı yedek adı");
            assert_eq!(b.read(&kept[0]), "{yarim");
            assert_eq!(b.mode(&kept[0]), 0o600);
        } else {
            assert!(i.forget("p20261126").is_err());
            assert!(Instances::new(&fresh).load().is_empty());
            assert!(i.load().is_empty());
            assert_eq!(b.read("instances.json"), "{yarim");
        }
    }
}

#[test]
fn concurrent_writers_lose_nothing() {
    let e = Env::new();
    e.py("db", STORE);
    let mut child = e
        .command(
            "db",
            r#"
from claudeops import instances as i
from claudeops.commands import web as w
from claudeops.store import default_store
sys.stdout.write('hazir\n'); sys.stdout.flush()
for n in range(40):
    i.record_instance('py%d' % n, blueprint=None, cwd='/c', cli='claude', model='m', origin='t')
    w._append_tsv_line(w.ROSTER_TSV, ['py%d' % n, '/c', 'm', 'claude'])
    default_store().update_doc('sayac', lambda v: v + 1, 0)
"#,
        )
        .spawn()
        .unwrap();
    let mut out = std::io::BufReader::new(child.stdout.take().unwrap());
    let mut line = String::new();
    std::io::BufRead::read_line(&mut out, &mut line).unwrap();
    let docs = std::sync::Arc::new(e.docs(Backend::Db));
    let threads: Vec<_> = (0..4)
        .map(|t| {
            let docs = docs.clone();
            std::thread::spawn(move || {
                for n in 0..10 {
                    let name = format!("rs{t}x{n}");
                    Instances::new(&docs)
                        .record(&name, &NewInstance::default())
                        .unwrap();
                    Roster::new(&docs)
                        .lock()
                        .unwrap()
                        .append(Tsv::Roster, &[&name, "/c", "m", "claude"])
                        .unwrap();
                    docs.store()
                        .unwrap()
                        .update_doc("sayac", Json::Int(0), |v| {
                            Some(Json::Int(v.as_i64().unwrap() + 1))
                        })
                        .unwrap();
                }
            })
        })
        .collect();
    for t in threads {
        t.join().unwrap();
    }
    let o = child.wait_with_output().unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    assert_eq!(Instances::new(&docs).load().len(), 80);
    assert_eq!(Roster::new(&docs).entries().unwrap().len(), 80);
    let st = docs.store().unwrap();
    assert_eq!(st.get_doc("sayac").unwrap(), Some(Json::Int(80)));
    assert_eq!(st.tsv_rows("roster.tsv", None).unwrap().len(), 80);
}

#[test]
fn name_helpers_match_python() {
    let e = Env::new();
    let names = [
        "hc20261126",
        "mtsyn20260909fablereview",
        "ysf220261105",
        "ysf2+20261105",
        "a20261126_1_2",
        "20261126",
        "A20261126",
        "a2026112",
        "a202611260",
        "a1234567890123",
        "x12345678y",
        "x_20261126",
        "ab20261126-x",
        "cops",
        "a20261126X",
        "p1234567820261126",
        "",
    ];
    let paths = [
        "/a//b/../c/",
        "",
        ".",
        "..",
        "../..",
        "a/../..",
        "//a",
        "///a",
        "/..",
        "/a/./b/.",
        "a//b",
        "./a",
        "ş/../ü",
    ];
    let arr = |v: &[&str]| Json::Array(v.iter().map(|s| Json::from(*s)).collect());
    let input = Json::Array(vec![arr(&names), arr(&paths)]).to_compact();
    let out = e.py_in(
        "files",
        r#"
from claudeops import instances as i
names, paths = json.load(sys.stdin)
bps = {'hc': '/h', 'mtsyn': '/m', 'q': '/h/', 'a': '/zz', 'x': '/only'}
res = []
for n in names:
    m = i.DERIVED_NAME_RE.match(n)
    res.append([list(m.groups()) if m else None] + [i.infer_blueprint(n, c, bps) for c in ('/h', '/m', '/only', '/yok')])
print(json.dumps([res, [os.path.normpath(p) for p in paths]], ensure_ascii=False))
"#,
        &input,
    );
    let bps = [
        ("hc", "/h"),
        ("mtsyn", "/m"),
        ("q", "/h/"),
        ("a", "/zz"),
        ("x", "/only"),
    ]
    .into_iter()
    .map(|(a, b)| (a.to_string(), b.to_string()))
    .collect();
    let opt = |o: Option<String>| o.map_or(Json::Null, Json::from);
    let res = names
        .iter()
        .map(|n| {
            let parts = derived_name(n).map_or(Json::Null, |(a, b, c)| arr(&[a, b, c]));
            let mut row = vec![parts];
            row.extend(
                ["/h", "/m", "/only", "/yok"]
                    .iter()
                    .map(|c| opt(infer_blueprint(n, c, &bps))),
            );
            Json::Array(row)
        })
        .collect();
    let norm = paths
        .iter()
        .map(|p| Json::from(cops_state::roster::normpath(p)))
        .collect();
    let rs = Json::Array(vec![Json::Array(res), Json::Array(norm)]);
    assert_eq!(rs.to_compact(), out.trim_end());
}
