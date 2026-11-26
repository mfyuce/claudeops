//! H16: test ikilisinde canlı durum dizinine yazan her yol PANİK verir ve HİÇBİR ŞEY yazmaz. Gerçek canlı dizine
//! dokunmamak için bu iş parçacığında geçici bir dizin "canlı" ilan edilir (`with_extra_live_dir`); gerçek canlı dizin
//! için yalnız dosya sistemine dokunmayan [`guard_write`] çağrılır.
use cops_state::fsutil::{
    atomic_write_json, atomic_write_text, atomic_write_tsv, create_unique, write_corrupt_copy,
    FileLock,
};
use cops_state::paths::{guard_write, live_dirs, under_test, with_extra_live_dir};
use cops_state::{Backend, Json, StateDir, StateDocs, Store, TestEnv};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::path::Path;

fn panics(f: impl FnOnce()) -> bool {
    catch_unwind(AssertUnwindSafe(f)).is_err()
}

fn tree(p: &Path) -> Vec<String> {
    let mut v: Vec<String> = Vec::new();
    for e in std::fs::read_dir(p).unwrap() {
        let e = e.unwrap();
        v.push(e.file_name().to_string_lossy().into_owned());
        if e.file_type().unwrap().is_dir() {
            v.extend(tree(&e.path()));
        }
    }
    v.sort();
    v
}

#[test]
fn writers_panic_in_live_dir_and_write_nothing() {
    assert!(under_test());
    // başka bir ortamda Python'un kurduğu gerçek bir DB (Store::open için)
    let other = TestEnv::new().unwrap();
    let py = std::process::Command::new("python3")
        .args(["-B", "-c", "import sys; sys.path.insert(0, sys.argv[1]); from claudeops.store import default_store; default_store()"])
        .arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../py"))
        .env("CLAUDEOPS_DIR", other.dir().root())
        .env("CLAUDEOPS_EXTENSIONS", "")
        .status()
        .unwrap();
    assert!(py.success());
    let live = TestEnv::new().unwrap();
    std::fs::copy(other.dir().db(), live.dir().db()).unwrap();
    let before = tree(live.root());
    let d = live.dir().clone();
    let j = Json::parse(r#"{"a": 1}"#).unwrap();
    with_extra_live_dir(live.root(), || {
        assert!(panics(|| drop(atomic_write_json(
            &d.join("x.json"),
            &j,
            None
        ))));
        assert!(panics(|| drop(atomic_write_text(
            &d.join("x.txt"),
            "x",
            None
        ))));
        assert!(panics(|| drop(atomic_write_tsv(&d.roster_tsv(), "a\tb\n"))));
        assert!(panics(|| drop(FileLock::acquire(&d.join("k")))));
        assert!(panics(|| drop(FileLock::exclusive(&d.join("k.lock")))));
        assert!(panics(|| drop(create_unique(d.root(), "a", ".tmp"))));
        assert!(panics(|| drop(write_corrupt_copy(&d.join("s.json"), b"x"))));
        assert!(panics(|| drop(
            StateDir::at(d.join("yeni")).ensure_private()
        )));
        assert!(panics(|| drop(Store::open(&d.db()))));
        let docs = StateDocs::isolated(d.clone(), Some(Backend::Files), "");
        assert!(panics(|| drop(docs.write(
            "hosts",
            &d.doc_path("hosts"),
            &j,
            None
        ))));
        assert!(panics(|| docs.diag_log("x")));
        let out = other.root().join("yedek.db");
        let st = Store::open(&other.dir().db()).unwrap();
        assert!(panics(|| drop(st.backup(&d.join("yedek.db")))));
        st.backup(&out).unwrap(); // canlı olmayan hedef: çalışır
    });
    assert_eq!(
        tree(live.root()),
        before,
        "canlı ilan edilen dizine hiçbir şey yazılmadı"
    );
}

#[test]
fn real_live_dir_is_guarded_without_touching_it() {
    let dirs = live_dirs();
    assert!(!dirs.is_empty());
    for l in dirs {
        assert!(l.ends_with(".claude/claudeops"));
        // guard_write yalnız yol çözer (readlink), yazmaz
        assert!(
            panics(|| guard_write(&l.join("roster.tsv"))),
            "{}",
            l.display()
        );
        assert!(panics(|| guard_write(&l)), "{}", l.display());
    }
    let tmp = TestEnv::new().unwrap();
    guard_write(&tmp.dir().join("x")); // geçici dizin serbest
}
