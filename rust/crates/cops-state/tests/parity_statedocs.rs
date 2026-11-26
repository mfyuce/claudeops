//! `statedocs.py` dalları (kip önbelleği, önekler, imza atlaması, DB hatası, ayna, günlük/diag.log, `mirror_log`,
//! `shadow_tsv`): aynı senaryo Python'da ve Rust'ta, aynı gözlem listesi.
//!
//! DB hatası iki dilde aynı yolla üretilir: DB'ye `RAISE(ABORT)` tetikleyicisi konur.
use cops_state::roster::read_text;
use cops_state::statedocs::{Read, MIRROR_EVERY, MIRROR_KEEP};
use cops_state::{Backend, Json, StateDocs, Store, WriteOutcome};
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::{Arc, Mutex};

mod common;
use common::{j, Env};

/// Python tarafının ortak başlangıcı: `sd`, `st`, `p(ad)`, `obs(x)`, `sql(metin)`; sonunda gözlemler basılır.
const HEAD: &str = "import sqlite3\nfrom claudeops import statedocs as sd\nfrom claudeops.store import default_store\n\
from claudeops.paths import CLAUDEOPS_DIR as D\nst = default_store()\nO = []\nobs = O.append\n\
p = lambda n: os.path.join(D, n + '.json')\n\
def sql(q):\n    c = sqlite3.connect(os.path.join(D, 'claudeops.db'), isolation_level=None); r = c.execute(q).fetchall(); c.close(); return r\n\
def put(n, t):\n    open(os.path.join(D, n), 'w').write(t)\n";
const TAIL: &str = "\nprint(json.dumps(O, ensure_ascii=False))";

const FAIL_DOCS: &str =
    "CREATE TRIGGER hata BEFORE INSERT ON docs BEGIN SELECT RAISE(ABORT, 'kilitli'); END";
const OK_DOCS: &str = "DROP TRIGGER hata";

fn py(e: &Env, mode: &str, body: &str) -> Json {
    j(e.py(mode, &format!("{HEAD}{body}{TAIL}")).trim_end())
}

fn sql(e: &Env, q: &str) {
    let c = rusqlite::Connection::open(e.dir().db()).unwrap();
    c.execute_batch(q).unwrap();
}

fn val(r: Read) -> Json {
    r.into_option().unwrap_or_else(|| Json::from("YOK"))
}

fn doc(s: &Store, n: &str) -> Json {
    s.get_doc(n).unwrap().unwrap_or_else(|| Json::from("YOK"))
}

/// Şeması Python'dan hazır iki ortam: (Python senaryosu, Rust senaryosu).
fn pair(mode: &str) -> (Env, Env) {
    let (a, b) = (Env::new(), Env::new());
    for e in [&a, &b] {
        e.py(
            mode,
            "from claudeops.store import default_store\ndefault_store()",
        );
    }
    (a, b)
}

fn same(rs: Vec<Json>, py: Json, want: &str) {
    let rs = Json::Array(rs);
    assert_eq!(rs.to_compact(), py.to_compact(), "Rust != Python");
    assert_eq!(rs, j(want), "beklenen");
}

/// Günlükçüsü toplanan `StateDocs`.
fn logged(e: &Env, backend: Backend) -> (StateDocs, Arc<Mutex<Vec<String>>>) {
    let log = Arc::new(Mutex::new(Vec::new()));
    let l = log.clone();
    let docs = e
        .docs(backend)
        .with_logger(move |m| l.lock().unwrap().push(m.to_string()));
    (docs, log)
}

#[test]
fn backend_cache_holds_five_seconds() {
    let (a, b) = (Env::new(), Env::new());
    let py = py(
        &a,
        "",
        "import time\nos.environ.pop('CLAUDEOPS_STORE_BACKEND')\nnow = [1000.0]\nsd.time.time = lambda: now[0]\n\
         put('settings.json', '{\"store_backend\": \"dual\"}'); obs(sd.backend())\n\
         put('settings.json', '{\"store_backend\": \"db\"}'); now[0] += 4.9; obs(sd.backend())\n\
         now[0] += 0.2; obs(sd.backend())",
    );
    assert_eq!(py, j(r#"["dual", "dual", "db"]"#));
    let docs = StateDocs::isolated(b.dir(), None, "");
    b.write("settings.json", r#"{"store_backend": "dual"}"#);
    assert_eq!(docs.backend(), Backend::Dual);
    b.write("settings.json", r#"{"store_backend": "db"}"#);
    assert_eq!(docs.backend(), Backend::Dual, "5 sn dolmadan önbellek");
    std::thread::sleep(std::time::Duration::from_millis(3000));
    assert_eq!(docs.backend(), Backend::Dual, "3 sn: hâlâ önbellek");
    std::thread::sleep(std::time::Duration::from_millis(2100));
    assert_eq!(docs.backend(), Backend::Db, "süre doldu");
}

/// Önbellek kilidi: eşzamanlı ilk okumalar kilitlenmez ve hepsi aynı kipi görür.
#[test]
fn backend_cache_concurrent_readers() {
    let e = Env::new();
    e.write("settings.json", r#"{"store_backend": "dual"}"#);
    for _ in 0..20 {
        let docs = StateDocs::isolated(e.dir(), None, "");
        std::thread::scope(|s| {
            let hs: Vec<_> = (0..8)
                .map(|_| s.spawn(|| (0..50).all(|_| docs.backend() == Backend::Dual)))
                .collect();
            assert!(hs.into_iter().all(|h| h.join().unwrap()));
        });
    }
}

#[test]
fn register_doc_prefix_like_python() {
    let e = Env::new();
    // `é/` iki KOD NOKTASI (üç bayt): Python reddeder
    let prefixes = [
        "auth/", "ab/", "a/", "/", "", "/etc/", "auth", "é/", "éé/", "x/y/",
    ];
    let input = Json::Array(prefixes.iter().map(|s| Json::from(*s)).collect()).to_compact();
    let out = e.py_in(
        "db",
        "from claudeops import statedocs as sd\nout = []\nfor p in json.load(sys.stdin):\n    sd._EXT_PREFIXES.clear()\n\
         \x20   try:\n        sd.register_doc_prefix(p); ok = True\n    except ValueError:\n        ok = False\n\
         \x20   n = p + 'users/u1'\n    out.append([ok, sd.db_ready(n), sd.db_ready('other/x'), sd._effective(n)])\nprint(json.dumps(out, ensure_ascii=False))",
        &input,
    );
    let mut rs = Vec::new();
    for p in prefixes {
        let docs = e.docs(Backend::Db);
        let n = format!("{p}users/u1");
        assert!(!docs.db_ready("auth/users/u1"), "kayıt öncesi");
        let ok = docs.register_doc_prefix(p);
        let eff = match docs.effective_backend(&n) {
            Backend::Db => "db",
            Backend::Dual => "dual",
            Backend::Files => "files",
        };
        rs.push(Json::Array(vec![
            ok.into(),
            docs.db_ready(&n).into(),
            docs.db_ready("other/x").into(),
            eff.into(),
        ]));
    }
    assert_eq!(Json::Array(rs.clone()), j(out.trim_end()));
    assert_eq!(rs[0], j(r#"[true, true, false, "db"]"#));
    assert_eq!(rs[7], j(r#"[false, false, false, "dual"]"#));
    // kayıtlı önek db kipinde DB'yi doğruluk kaynağı yapar
    e.py(
        "db",
        "from claudeops.store import default_store\ndefault_store()",
    );
    let docs = e.docs(Backend::Db);
    assert!(docs.register_doc_prefix("auth/"));
    let path = e.dir().doc_path("auth/u");
    docs.write("auth/u", &path, &j("1"), None).unwrap();
    e.write("auth/u.json", "2");
    assert_eq!(val(docs.read("auth/u", &path)), j("1"));
}

/// `file_truth=false`, dual'de dosya yokken / bozukken DB'den okuma, boş DB'ye tembel içe aktarma.
#[test]
fn dual_read_branches() {
    let (a, b) = pair("dual");
    let py = py(
        &a,
        "dual",
        "sd.write_json('q', p('q'), {'a': 2}); st.set_doc('q', {'a': 3})\n\
         obs(sd.read_json('q', p('q'), file_truth=False)); obs(sd.read_json('q', p('q')))\n\
         os.remove(p('q')); st.set_doc('q', {'a': 4}); obs(sd.read_json('q', p('q'), 'YOK'))\n\
         put('q.json', '{bozuk'); n = []; obs(sd.read_json('q', p('q'), 'YOK', on_corrupt=n.append)); obs(len(n))\n\
         obs(sd.read_json('yok', p('yok'), 'YOK'))\n\
         put('eski.json', '{\"old\": 1}'); obs(st.get_doc('eski', 'YOK')); obs(sd.read_json('eski', p('eski'))); obs(st.get_doc('eski', 'YOK'))\n\
         put('db_once.json', '{\"old\": 2}'); obs(sd.read_json('db_once', p('db_once'), file_truth=False)); obs(st.get_doc('db_once', 'YOK'))",
    );
    let docs = b.docs(Backend::Dual);
    let s = Store::open(&b.dir().db()).unwrap();
    let p = |n: &str| b.dir().doc_path(n);
    let mut o = Vec::new();
    docs.write("q", &p("q"), &j(r#"{"a": 2}"#), None).unwrap();
    s.set_doc("q", &j(r#"{"a": 3}"#)).unwrap();
    o.push(val(docs.read_opts("q", &p("q"), false)));
    // dosya doğruluk kaynağı
    o.push(val(docs.read("q", &p("q"))));
    std::fs::remove_file(p("q")).unwrap();
    s.set_doc("q", &j(r#"{"a": 4}"#)).unwrap();
    o.push(val(docs.read("q", &p("q"))));
    b.write("q.json", "{bozuk");
    let n = std::cell::Cell::new(0);
    let cb = |_: &Path| n.set(n.get() + 1);
    o.push(val(docs.read_with("q", &p("q"), true, Some(&cb))));
    o.push(Json::Int(n.get()));
    o.push(val(docs.read("yok", &p("yok"))));
    b.write("eski.json", r#"{"old": 1}"#);
    o.push(doc(&s, "eski"));
    o.push(val(docs.read("eski", &p("eski"))));
    o.push(doc(&s, "eski"));
    b.write("db_once.json", r#"{"old": 2}"#);
    o.push(val(docs.read_opts("db_once", &p("db_once"), false)));
    o.push(doc(&s, "db_once"));
    same(
        o,
        py,
        r#"[{"a": 3}, {"a": 2}, {"a": 4}, {"a": 4}, 1, "YOK", "YOK", {"old": 1}, {"old": 1}, {"old": 2}, {"old": 2}]"#,
    );
}

/// Okumada DB hatası dosyaya düşer: DB açılamıyor (iki kip, db-hazır belge) ve DB sorgusu hata veriyor.
#[test]
fn db_read_failure_falls_back_to_file() {
    for (mode, backend) in [("dual", Backend::Dual), ("db", Backend::Db)] {
        let (a, b) = pair(mode);
        let py_open = py(
            &a,
            mode,
            "from claudeops import store as S\nput('hosts.json', '[1]')\n\
             def boom():\n    raise RuntimeError('boom')\nS.default_store = boom\n\
             obs(sd.read_json('hosts', p('hosts'))); obs(sd.read_json('yok', p('yok'), 'YOK'))",
        );
        std::fs::remove_file(b.dir().db()).unwrap();
        let (docs, log) = logged(&b, backend);
        b.write("hosts.json", "[1]");
        let o = vec![
            val(docs.read("hosts", &b.dir().doc_path("hosts"))),
            val(docs.read("yok", &b.dir().doc_path("yok"))),
        ];
        same(o, py_open, r#"[[1], "YOK"]"#);
        let log = log.lock().unwrap();
        assert!(
            log.len() == 2 && log[0].starts_with("read hosts: ") && log[0].ends_with(" -> dosya"),
            "{log:?}"
        );
        assert!(!b.dir().db().exists(), "okuma DB yaratmaz");
    }
    // sorgu hatası (tablo yok): açık bağlantıda da dosyaya düşer
    let (_, b) = pair("db");
    let (docs, log) = logged(&b, Backend::Db);
    docs.store().unwrap();
    sql(&b, "ALTER TABLE docs RENAME TO docs_yedek");
    b.write("hosts.json", "[7]");
    assert_eq!(
        val(docs.read("hosts", &b.dir().doc_path("hosts"))),
        j("[7]")
    );
    assert!(log.lock().unwrap()[0].starts_with("read hosts: "));
}

/// Dosya imzası değişmediyse DB karşılaştırması YOK; yazımdan sonra da imza kayıtlıdır; dosya değişince eşitlenir.
#[test]
fn dual_skips_db_compare_when_file_unchanged() {
    let (a, b) = pair("dual");
    let py = py(
        &a,
        "dual",
        "sd.write_json('q', p('q'), {'a': 1}); st.set_doc('q', {'z': 1})\n\
         obs(sd.read_json('q', p('q'))); obs(st.get_doc('q'))\n\
         put('q.json', '{\"a\": 99}'); obs(sd.read_json('q', p('q'))); obs(st.get_doc('q'))\n\
         st.set_doc('q', {'z': 2}); obs(sd.read_json('q', p('q'))); obs(st.get_doc('q'))",
    );
    let docs = b.docs(Backend::Dual);
    let s = Store::open(&b.dir().db()).unwrap();
    let p = b.dir().doc_path("q");
    let mut o = Vec::new();
    let mut step = |s: &Store| {
        o.push(val(docs.read("q", &p)));
        o.push(doc(s, "q"));
    };
    docs.write("q", &p, &j(r#"{"a": 1}"#), None).unwrap();
    s.set_doc("q", &j(r#"{"z": 1}"#)).unwrap();
    step(&s);
    b.write("q.json", r#"{"a": 99}"#);
    step(&s);
    s.set_doc("q", &j(r#"{"z": 2}"#)).unwrap();
    step(&s);
    same(
        o,
        py,
        r#"[{"a": 1}, {"z": 1}, {"a": 99}, {"a": 99}, {"a": 99}, {"z": 2}]"#,
    );
}

/// Dual kipte DB yazımı düşerse imza unutulur ve sonraki okuma DB'yi dosyaya uydurur.
#[test]
fn dual_write_failure_resyncs_on_next_read() {
    let (a, b) = pair("dual");
    let py = py(
        &a,
        "dual",
        &format!(
            "sd.write_json('q', p('q'), {{'v': 1}}); sql(\"{FAIL_DOCS}\")\n\
             sd.write_json('q', p('q'), {{'v': 2}}); sql('{OK_DOCS}')\n\
             obs(st.get_doc('q')); obs('q' in sd._SYNCED); obs(sd.read_json('q', p('q'))); obs(st.get_doc('q'))"
        ),
    );
    let (docs, log) = logged(&b, Backend::Dual);
    let s = Store::open(&b.dir().db()).unwrap();
    let p = b.dir().doc_path("q");
    docs.write("q", &p, &j(r#"{"v": 1}"#), None).unwrap();
    sql(&b, FAIL_DOCS);
    assert_eq!(
        docs.write("q", &p, &j(r#"{"v": 2}"#), None).unwrap(),
        WriteOutcome::Written,
        "dual: dosya doğruluk kaynağı yazıldı"
    );
    sql(&b, OK_DOCS);
    assert_eq!(b.read("q.json"), j(r#"{"v": 2}"#).to_indented());
    let mut o = vec![doc(&s, "q"), Json::Bool(false)];
    o.push(val(docs.read("q", &p)));
    o.push(doc(&s, "q"));
    same(o, py, r#"[{"v": 1}, false, {"v": 2}, {"v": 2}]"#);
    let log = log.lock().unwrap();
    assert!(log[0].starts_with("write q: "), "{log:?}");
    assert_eq!(log[1], "drift q: DB dosyaya uyduruldu");
}

/// db kipinde ayna dosya yazılamazsa hata yutulur (loglanır), DB yazılmıştır.
#[test]
fn db_mirror_failure_is_swallowed() {
    let (a, b) = pair("db");
    let py = py(
        &a,
        "db",
        "os.mkdir(p('hosts')); sd.write_json('hosts', p('hosts'), [5]); obs(st.get_doc('hosts')); obs(sd.read_json('hosts', p('hosts'))); obs(os.path.isdir(p('hosts')))\n\
         obs(sorted(x for x in os.listdir(D) if x.endswith('.tmp')))",
    );
    let (docs, log) = logged(&b, Backend::Db);
    let p = b.dir().doc_path("hosts");
    std::fs::create_dir(&p).unwrap();
    assert_eq!(
        docs.write("hosts", &p, &j("[5]"), None).unwrap(),
        WriteOutcome::Written
    );
    let tmp: Vec<Json> = std::fs::read_dir(&b.state)
        .unwrap()
        .map(|x| x.unwrap().file_name().to_string_lossy().into_owned())
        .filter(|n| n.ends_with(".tmp"))
        .map(Json::from)
        .collect();
    let o = vec![
        doc(&docs.store().unwrap(), "hosts"),
        val(docs.read("hosts", &p)),
        p.is_dir().into(),
        Json::Array(tmp),
    ];
    same(o, py, "[[5], [5], true, []]");
    assert!(log.lock().unwrap()[0].starts_with("mirror hosts: "));
    // db DIŞI kipte aynı yazım hatası YUTULMAZ
    let dual = b.docs(Backend::Dual);
    let p2 = b.dir().doc_path("orchdraft");
    std::fs::create_dir(&p2).unwrap();
    assert!(dual.write("orchdraft", &p2, &j("1"), None).is_err());
}

/// diag.log: ts sıfırlanmış satırlar; hata iletilerinde istisna metni (`{e!r}`) dile özgü olduğu için atılır.
fn diag_lines(path: &Path) -> Vec<String> {
    let text = read_text(path).unwrap().unwrap_or_default();
    text.lines()
        .map(|l| {
            let v = j(l);
            let m = v.as_object().unwrap();
            assert_eq!(m.keys().collect::<Vec<_>>(), ["ts", "event"], "{l}");
            let ts = m["ts"].as_str().unwrap();
            let shape: String = ts
                .chars()
                .map(|c| if c.is_ascii_digit() { '9' } else { c })
                .collect();
            assert_eq!(shape, "9999-99-99T99:99:99", "{l}");
            assert_eq!(
                l,
                v.to_compact(),
                "Python json.dumps(ensure_ascii=False) biçimi"
            );
            let ev = m["event"].as_str().unwrap();
            for p in [
                "statedocs write q: ",
                "statedocs mirror hosts: ",
                "statedocs read q: ",
            ] {
                if let Some(rest) = ev.strip_prefix(p) {
                    let tail = if rest.ends_with(" -> dosya") {
                        " -> dosya"
                    } else {
                        ""
                    };
                    return format!("{p}*{tail}");
                }
            }
            ev.to_string()
        })
        .collect()
}

/// K4: statedocs günlüğü diag.log'a gider (yol, biçim, izin Python ile aynı), dual/db kipte `log` akışına da; ilk içe
/// aktarma "drift" sayılmaz.
#[test]
fn diag_log_matches_python() {
    let (a, b) = pair("dual");
    py(
        &a,
        "dual",
        &format!(
            "put('q.json', '{{\"old\": 1}}'); sd.read_json('q', p('q'))\n\
             st.set_doc('q', {{'zzz': 1}}); put('q.json', '{{\"old\": 22}}'); sd.read_json('q', p('q'))\n\
             sql(\"{FAIL_DOCS}\"); sd.write_json('q', p('q'), {{'v': 'ş'}}); sd.read_json('q', p('q')); sql('{OK_DOCS}')\n\
             os.environ['CLAUDEOPS_STORE_BACKEND'] = 'db'\n\
             os.mkdir(p('hosts')); sd.write_json('hosts', p('hosts'), [5])\n\
             sd._DIRTY.add('claude_models'); put('claude_models.json', '[2]'); sd.read_json('claude_models', p('claude_models'))"
        ),
    );
    let docs = StateDocs::isolated(b.dir(), Some(Backend::Dual), "");
    let s = Store::open(&b.dir().db()).unwrap();
    let q = b.dir().doc_path("q");
    b.write("q.json", r#"{"old": 1}"#);
    docs.read("q", &q);
    s.set_doc("q", &j(r#"{"zzz": 1}"#)).unwrap();
    b.write("q.json", r#"{"old": 22}"#);
    docs.read("q", &q);
    sql(&b, FAIL_DOCS);
    docs.write("q", &q, &j(r#"{"v": "ş"}"#), None).unwrap();
    docs.read("q", &q);
    sql(&b, OK_DOCS);
    let db = StateDocs::isolated(b.dir(), Some(Backend::Db), "");
    let hosts = b.dir().doc_path("hosts");
    std::fs::create_dir(&hosts).unwrap();
    db.write("hosts", &hosts, &j("[5]"), None).unwrap();
    // kirli belge: geçici DB hatasından sonra (Rust'ta gerçek yoldan) dosyadan geri alma
    let cm = b.dir().doc_path("claude_models");
    sql(&b, FAIL_DOCS);
    assert_eq!(
        db.write("claude_models", &cm, &j("[2]"), None).unwrap(),
        WriteOutcome::DbDeferred
    );
    sql(&b, OK_DOCS);
    db.read("claude_models", &cm);

    let (la, lb) = (a.state.join("diag.log"), b.state.join("diag.log"));
    // ts YEREL saat: Python'un `datetime.now()`ı ile arası saniyeler
    let last = read_text(&lb)
        .unwrap()
        .unwrap()
        .lines()
        .last()
        .map(j)
        .unwrap();
    let ts = last.get("ts").and_then(Json::as_str).unwrap();
    let near = a.py(
        "dual",
        &format!("import datetime as d\nprint(abs((d.datetime.now() - d.datetime.fromisoformat('{ts}')).total_seconds()) < 120)"),
    );
    assert_eq!(near.trim_end(), "True", "{ts}");
    let mut rs = diag_lines(&lb);
    // yalnız Rust senaryosunda var: kirli duruma getiren yazımın iletisi
    let extra = rs
        .iter()
        .position(|l| l.starts_with("statedocs write claude_models: "))
        .expect("write iletisi");
    rs.remove(extra);
    assert_eq!(rs, diag_lines(&la));
    assert_eq!(rs[0], "statedocs import q: DB'de yoktu, dosyadan alındı");
    assert_eq!(rs[1], "statedocs drift q: DB dosyaya uyduruldu");
    assert!(!rs[0].contains("drift"));
    for want in [
        "statedocs write q: *",
        "statedocs read q: * -> dosya",
        "statedocs mirror hosts: *",
        "statedocs recover claude_models: DB dosyadan yeniden yazıldı",
    ] {
        assert!(rs.iter().any(|l| l == want), "{want}: {rs:?}");
    }
    let mode = |p: &Path| std::fs::metadata(p).unwrap().permissions().mode() & 0o777;
    assert_eq!(mode(&la), mode(&lb), "diag.log izni (umask)");
    // aynı satırlar DB `log` akışında (dual/db)
    let rows = s.tail_log("diag", 100).unwrap();
    let file: Vec<Json> = read_text(&lb).unwrap().unwrap().lines().map(j).collect();
    assert_eq!(rows.into_iter().map(|r| r.body).collect::<Vec<_>>(), file);
}

/// Python `_rotate_if_big`: 5 MiB'ı AŞAN diag.log `.1`e taşınır; tam sınırda taşınmaz. files kipinde DB'ye satır yok.
#[test]
fn diag_log_rotates_like_python() {
    let (a, b) = pair("files");
    for (size, rotated) in [(5 * 1024 * 1024, false), (5 * 1024 * 1024 + 1, true)] {
        for e in [&a, &b] {
            std::fs::write(e.state.join("diag.log"), vec![b'x'; size]).unwrap();
            let _ = std::fs::remove_file(e.state.join("diag.log.1"));
        }
        a.py(
            "files",
            "from claudeops.diaglog import diag_log\ndiag_log('olay')",
        );
        let docs = StateDocs::isolated(b.dir(), Some(Backend::Files), "");
        docs.diag_log("olay");
        let len = |e: &Env, n: &str| std::fs::metadata(e.state.join(n)).map(|m| m.len()).ok();
        assert_eq!(len(&a, "diag.log.1"), len(&b, "diag.log.1"), "{size}");
        assert_eq!(len(&b, "diag.log.1"), rotated.then_some(size as u64));
        assert_eq!(len(&a, "diag.log"), len(&b, "diag.log"), "{size}");
    }
    assert!(Store::open(&b.dir().db())
        .unwrap()
        .tail_log("diag", 9)
        .unwrap()
        .is_empty());
    // yazılamayan günlük yolu sessiz (best-effort)
    std::fs::remove_file(b.state.join("diag.log")).unwrap();
    std::fs::create_dir(b.state.join("diag.log")).unwrap();
    StateDocs::isolated(b.dir(), Some(Backend::Dual), "").diag_log("olay");
}

#[test]
fn mirror_constants_match_python() {
    let e = Env::new();
    let out = e.py(
        "files",
        "from claudeops import statedocs as sd, store, dbapi, atomic_json\n\
         print(sd._MIRROR_KEEP, sd._MIRROR_EVERY, ' '.join(sd._TSV_FILES), store.BUSY_TIMEOUT_MS, dbapi.BUSY_TIMEOUT_MS, atomic_json.LOCK_TIMEOUT_SECONDS)",
    );
    assert_eq!(
        out.trim_end(),
        format!(
            "{MIRROR_KEEP} {MIRROR_EVERY} {} {b} {b} {:.1}",
            cops_state::statedocs::TSV_FILES.join(" "),
            cops_state::fsutil::LOCK_TIMEOUT.as_secs_f64(),
            b = cops_state::store::BUSY_TIMEOUT_MS,
        )
    );
}

/// `mirror_log`: her `MIRROR_EVERY` eklemede akış `MIRROR_KEEP` satıra kırpılır (önce değil).
#[test]
fn mirror_log_trims_at_threshold() {
    let (a, b) = pair("dual");
    let fill = format!(
        "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i < {}) INSERT INTO log(stream, ts, body) SELECT 'g', 1.0, '0' FROM n",
        MIRROR_KEEP + 5
    );
    sql(&a, &fill);
    sql(&b, &fill);
    let py = py(
        &a,
        "dual",
        "q = \"SELECT COUNT(*), MIN(id), MAX(id) FROM log WHERE stream='g'\"\n\
         for i in range(1999): sd.mirror_log('g', os.path.join(D, 'g.log'), 1)\nobs(list(sql(q)[0]))\n\
         sd.mirror_log('g', os.path.join(D, 'g.log'), 1); obs(list(sql(q)[0]))\n\
         sd.mirror_log('g', os.path.join(D, 'g.log'), 1); obs(list(sql(q)[0]))",
    );
    let docs = b.docs(Backend::Dual);
    let path = b.state.join("g.log");
    let count = || {
        let c = rusqlite::Connection::open(b.dir().db()).unwrap();
        c.query_row(
            "SELECT COUNT(*), MIN(id), MAX(id) FROM log WHERE stream='g'",
            [],
            |r| {
                Ok(Json::Array(vec![
                    Json::Int(r.get(0)?),
                    Json::Int(r.get(1)?),
                    Json::Int(r.get(2)?),
                ]))
            },
        )
        .unwrap()
    };
    let mut o = Vec::new();
    for _ in 1..MIRROR_EVERY {
        assert!(docs.mirror_log("g", &path, &Json::Int(1)));
    }
    o.push(count());
    docs.mirror_log("g", &path, &Json::Int(1));
    o.push(count());
    docs.mirror_log("g", &path, &Json::Int(1));
    o.push(count());
    same(
        o,
        py,
        "[[202004, 1, 202004], [200000, 2006, 202005], [200001, 2006, 202006]]",
    );
}

/// `mirror_log` DB hatasını yutar ve LOGLAMAZ (günlük -> mirror -> günlük döngüsü olmasın).
#[test]
fn mirror_log_swallows_db_errors() {
    let (a, b) = pair("dual");
    const FAIL_LOG: &str =
        "CREATE TRIGGER hata BEFORE INSERT ON log BEGIN SELECT RAISE(ABORT, 'kilitli'); END";
    let py = py(
        &a,
        "dual",
        &format!(
            "sql(\"{FAIL_LOG}\"); obs(sd.mirror_log('s', os.path.join(D, 's.log'), 1)); obs(len(st.tail_log('s'))); obs(os.path.exists(os.path.join(D, 'diag.log')))\n\
             from claudeops import store as S\ndef boom():\n    raise RuntimeError('x')\nS.default_store = boom\nobs(sd.mirror_log('s', os.path.join(D, 's.log'), 1))"
        ),
    );
    assert_eq!(py, j("[null, 0, false, null]"));
    sql(&b, FAIL_LOG);
    let (docs, log) = logged(&b, Backend::Dual);
    assert!(!docs.mirror_log("s", &b.state.join("s.log"), &Json::Int(1)));
    assert!(docs.store().unwrap().tail_log("s", 9).unwrap().is_empty());
    std::fs::remove_file(b.dir().db()).unwrap();
    let (gone, log2) = logged(&b, Backend::Dual);
    assert!(!gone.mirror_log("s", &b.state.join("s.log"), &Json::Int(1)));
    assert!(log.lock().unwrap().is_empty() && log2.lock().unwrap().is_empty());
}

/// `shadow_tsv`: imza değişmediyse atlama (`force=false`), elle düzenleme, boş/silinen dosyada gereksiz yazım yok,
/// files kipi / dizin dışı yol / başka ad atlanır.
#[test]
fn shadow_tsv_skip_branches() {
    let (a, b) = pair("dual");
    // boş gölgeye gereksiz yazım olursa tetikleyici hata verir (loglanır)
    const NO_WRITE: &str =
        "CREATE TRIGGER yazma BEFORE INSERT ON tsv_rows BEGIN SELECT RAISE(ABORT, 'yazildi'); END";
    let py = py(
        &a,
        "dual",
        &format!(
            "r = os.path.join(D, 'roster.tsv'); T = lambda n='roster.tsv': st.tsv_text(n)\n\
             put('roster.tsv', 'a\\tb\\n'); sd.shadow_tsv(r); obs(T())\n\
             st.replace_tsv('roster.tsv', 'bozuk\\n'); sd.shadow_tsv(r); obs(T())\n\
             sd.shadow_tsv(r, force=True); obs(T())\n\
             st.replace_tsv('roster.tsv', 'bozuk\\n'); open(r, 'a').write('yeni\\tz\\n'); sd.shadow_tsv(r); obs(T())\n\
             os.remove(r); sd.shadow_tsv(r, force=True); obs(T())\n\
             put('roster.tsv', ''); sql(\"{NO_WRITE}\"); sd.shadow_tsv(r, force=True); obs(T()); obs(os.path.exists(os.path.join(D, 'diag.log'))); sql('DROP TRIGGER yazma')\n\
             put('roster.tsv', 'x\\ty\\n'); os.environ['CLAUDEOPS_STORE_BACKEND'] = 'files'; sd.shadow_tsv(r, force=True); obs(T()); os.environ['CLAUDEOPS_STORE_BACKEND'] = 'dual'\n\
             put('other.tsv', 'x\\ty\\n'); sd.shadow_tsv(os.path.join(D, 'other.tsv'), force=True); obs(T('other.tsv'))\n\
             o = os.path.join(D, '..', 'roster.tsv'); open(o, 'w').write('dis\\ty\\n'); sd.shadow_tsv(o, force=True); obs(sql('SELECT COUNT(*) FROM tsv_rows')[0][0])"
        ),
    );
    let (docs, log) = logged(&b, Backend::Dual);
    let s = Store::open(&b.dir().db()).unwrap();
    let r = b.dir().roster_tsv();
    let t = |n: &str| s.tsv_text(n).unwrap().map_or(Json::Null, Json::from);
    let mut o = Vec::new();
    b.write("roster.tsv", "a\tb\n");
    docs.shadow_tsv(&r, false);
    o.push(t("roster.tsv"));
    s.replace_tsv("roster.tsv", "bozuk\n").unwrap();
    docs.shadow_tsv(&r, false);
    o.push(t("roster.tsv"));
    docs.shadow_tsv(&r, true);
    o.push(t("roster.tsv"));
    s.replace_tsv("roster.tsv", "bozuk\n").unwrap();
    b.write("roster.tsv", "a\tb\nyeni\tz\n");
    docs.shadow_tsv(&r, false);
    o.push(t("roster.tsv"));
    std::fs::remove_file(&r).unwrap();
    docs.shadow_tsv(&r, true);
    o.push(t("roster.tsv"));
    b.write("roster.tsv", "");
    sql(&b, NO_WRITE);
    docs.shadow_tsv(&r, true);
    o.push(t("roster.tsv"));
    o.push(Json::Bool(!log.lock().unwrap().is_empty()));
    sql(&b, "DROP TRIGGER yazma");
    b.write("roster.tsv", "x\ty\n");
    b.docs(Backend::Files).shadow_tsv(&r, true);
    o.push(t("roster.tsv"));
    b.write("other.tsv", "x\ty\n");
    docs.shadow_tsv(&b.state.join("other.tsv"), true);
    o.push(t("other.tsv"));
    let outside = b.root.join("roster.tsv");
    std::fs::write(&outside, "dis\ty\n").unwrap();
    docs.shadow_tsv(&outside, true);
    let c = rusqlite::Connection::open(b.dir().db()).unwrap();
    o.push(Json::Int(
        c.query_row("SELECT COUNT(*) FROM tsv_rows", [], |r| r.get(0))
            .unwrap(),
    ));
    same(
        o,
        py,
        r#"["a\tb\n", "bozuk\n", "a\tb\n", "a\tb\nyeni\tz\n", null, null, false, null, null, 0]"#,
    );
    // aynı tetikleyici gerçek bir yazımda hata verdiriyor (denetim boşa değil) ve hata yalnız loglanıyor
    sql(&b, NO_WRITE);
    docs.shadow_tsv(&r, true);
    assert!(log.lock().unwrap()[0].starts_with("shadow_tsv "));
}
