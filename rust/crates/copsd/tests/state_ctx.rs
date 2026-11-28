//! B0 durum bağlamı: `RouteCtx` kurulumu yan etkisiz, `ReadDocs::read` Python okuma kararını verir ama HİÇBİR şey yazmaz
//! (`StateDocs::read` aynı durumda yazar: karşılaştırma testi), test ikilisinde durum dizini canlı dizine çözülmez (H16),
//! `cops-tmux` yutulan hata satırı sır/pane metni taşımaz.
use cops_state::statedocs::Read;
use cops_state::{Backend, Json, StateDocs, TestEnv};
use copsd::routes::RouteCtx;
use copsd::state::ReadDocs;
use std::collections::BTreeMap;
use std::path::Path;

/// Dizin ağacının (yol -> içerik) anlık görüntüsü: yazım olmadığının kanıtı.
fn snapshot(root: &Path) -> BTreeMap<String, Vec<u8>> {
    let mut out = BTreeMap::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(d) = stack.pop() {
        for e in std::fs::read_dir(&d).unwrap() {
            let p = e.unwrap().path();
            if p.is_dir() {
                stack.push(p);
            } else {
                let key = p.strip_prefix(root).unwrap().to_string_lossy().into_owned();
                out.insert(key, std::fs::read(&p).unwrap());
            }
        }
    }
    out
}

/// Python şemasının `docs` parçası (sürüm denetimi geçsin); WAL kipine ALINMAZ (salt okunur açılış dosya yaratmasın diye
/// değil, yazım olursa ana dosya değişsin diye: rollback günlüğünde yazım ana dosyaya iner).
fn make_db(env: &TestEnv, rows: &[(&str, &str)]) {
    let c = rusqlite::Connection::open(env.dir().db()).unwrap();
    c.execute_batch(
        "CREATE TABLE docs(name TEXT PRIMARY KEY, body TEXT, version INTEGER, updated REAL);",
    )
    .unwrap();
    for (n, b) in rows {
        c.execute("INSERT INTO docs VALUES(?1, ?2, 1, 1.0)", [n, b])
            .unwrap();
    }
    c.pragma_update(None, "user_version", cops_state::store::SCHEMA_VERSION)
        .unwrap();
}

fn write(p: &Path, s: &str) {
    std::fs::write(p, s).unwrap();
}

fn same(r: Read, want: &str) {
    match r {
        Read::Value(v) => assert!(
            v.py_eq(&Json::parse(want).unwrap()),
            "{} != {want}",
            v.to_compact()
        ),
        other => panic!("değer yok: {other:?}"),
    }
}

#[test]
fn route_ctx_construction_touches_nothing() {
    let env = TestEnv::new().unwrap();
    make_db(&env, &[("hosts", "[]")]);
    write(&env.dir().settings_json(), r#"{"store_backend": "db"}"#);
    let before = snapshot(env.dir().root());
    let root = env.dir().root().to_path_buf();
    let ctx = RouteCtx::new(root.clone(), env.dir().db(), env.dir().instances_json());
    assert_eq!(ctx.docs.dir().root(), root.as_path());
    let _ = ctx.docs.backend(); // settings.json okur
    let _ = format!("{ctx:?}");
    assert_eq!(snapshot(env.dir().root()), before);
}

/// Kurulum boş/olmayan dizinde de bir şey yaratmaz.
#[test]
fn route_ctx_on_missing_dir_creates_nothing() {
    let env = TestEnv::new().unwrap();
    let missing = env.root().join("yok");
    let ctx = RouteCtx::new(
        missing.clone(),
        missing.join("claudeops.db"),
        missing.join("instances.json"),
    );
    assert_eq!(ctx.docs.backend(), Backend::Files);
    assert!(matches!(
        ctx.docs.read("hosts", &missing.join("hosts.json")),
        Read::Missing
    ));
    assert!(!missing.exists());
}

#[test]
fn db_mode_reads_db_and_never_imports() {
    let env = TestEnv::new().unwrap();
    make_db(&env, &[("hosts", r#"[{"name": "dbden"}]"#)]);
    let hosts = env.dir().join("hosts.json");
    write(&hosts, r#"[{"name": "dosyadan"}]"#);
    // `snapshots` db-hazır, DB'de YOK, dosyada var: Python (ve StateDocs::read) burada DB'ye içe aktarır.
    let snaps = env.dir().join("snapshots.json");
    write(&snaps, r#"{"a": 1}"#);
    let before = snapshot(env.dir().root());

    let ro = ReadDocs::from_docs(StateDocs::isolated(
        env.dir().clone(),
        Some(Backend::Db),
        "",
    ));
    same(ro.read("hosts", &hosts), r#"[{"name":"dbden"}]"#);
    same(ro.read("snapshots", &snaps), r#"{"a":1}"#);
    // db-hazır olmayan belge db kipinde `dual`: dosya
    let other = env.dir().join("other.json");
    write(&other, "[1]");
    let before_other = snapshot(env.dir().root());
    same(ro.read("other", &other), "[1]");
    assert_eq!(snapshot(env.dir().root()), before_other);
    std::fs::remove_file(&other).unwrap();
    assert_eq!(snapshot(env.dir().root()), before, "ReadDocs yazdı");

    // Karşılaştırma: aynı okuma ham StateDocs ile DB'ye yazar (R2 ihlali; bu yüzden copsd onu dışarı vermez).
    let raw = StateDocs::isolated(env.dir().clone(), Some(Backend::Db), "");
    let _ = raw.read("snapshots", &snaps);
    drop(raw);
    let c = rusqlite::Connection::open(env.dir().db()).unwrap();
    let n: i64 = c
        .query_row(
            "SELECT count(*) FROM docs WHERE name='snapshots'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(
        n, 1,
        "StateDocs::read içe aktarmadı: karşılaştırma geçersiz"
    );
}

#[test]
fn dual_mode_file_is_truth_and_db_is_not_reconciled() {
    let env = TestEnv::new().unwrap();
    make_db(
        &env,
        &[("hosts", r#"["db"]"#), ("gone", r#"["yalniz-db"]"#)],
    );
    let hosts = env.dir().join("hosts.json");
    write(&hosts, r#"["dosya"]"#);
    let before = snapshot(env.dir().root());
    let ro = ReadDocs::from_docs(StateDocs::isolated(
        env.dir().clone(),
        Some(Backend::Dual),
        "",
    ));
    same(ro.read("hosts", &hosts), r#"["dosya"]"#);
    // dosya yoksa DB değeri (Python `get_doc(name) or r`)
    same(
        ro.read("gone", &env.dir().join("gone.json")),
        r#"["yalniz-db"]"#,
    );
    assert_eq!(
        snapshot(env.dir().root()),
        before,
        "ReadDocs DB'yi dosyaya uydurdu"
    );

    let raw = StateDocs::isolated(env.dir().clone(), Some(Backend::Dual), "");
    let _ = raw.read("hosts", &hosts);
    drop(raw);
    assert_ne!(
        snapshot(env.dir().root()),
        before,
        "StateDocs::read uydurmadı: karşılaştırma geçersiz"
    );
}

#[test]
fn files_mode_and_paths_outside_state_dir_read_the_file() {
    let env = TestEnv::new().unwrap();
    make_db(&env, &[("hosts", r#"["db"]"#)]);
    let hosts = env.dir().join("hosts.json");
    write(&hosts, r#"["dosya"]"#);
    let ro = ReadDocs::from_docs(StateDocs::isolated(
        env.dir().clone(),
        Some(Backend::Files),
        "",
    ));
    same(ro.read("hosts", &hosts), r#"["dosya"]"#);
    let outside = env.root().join("dis.json");
    write(&outside, r#"["dis"]"#);
    let db = ReadDocs::from_docs(StateDocs::isolated(
        env.dir().clone(),
        Some(Backend::Db),
        "",
    ));
    same(db.read("hosts", &outside), r#"["dis"]"#);
}

/// DB açılamazsa (yok) `db` kipte dosyaya düşülür ve DB yaratılmaz.
#[test]
fn db_mode_without_db_falls_back_to_file_and_creates_nothing() {
    let env = TestEnv::new().unwrap();
    let hosts = env.dir().join("hosts.json");
    write(&hosts, r#"["dosya"]"#);
    let before = snapshot(env.dir().root());
    let ro = ReadDocs::from_docs(StateDocs::isolated(
        env.dir().clone(),
        Some(Backend::Db),
        "",
    ));
    same(ro.read("hosts", &hosts), r#"["dosya"]"#);
    assert_eq!(snapshot(env.dir().root()), before);
}

/// H16: test ikilisinde `CLAUDEOPS_DIR` yokken copsd'nin durum dizini canlı dizin değil, süreç başına geçici dizin.
#[test]
fn state_dir_under_test_is_never_live() {
    if std::env::var_os("CLAUDEOPS_DIR").is_some()
        || std::env::var_os("CLAUDEOPS_TEST_REAL_DIR").is_some()
    {
        return;
    }
    let d = copsd::state_dir();
    assert!(d.starts_with(std::env::temp_dir()), "{}", d.display());
    for live in cops_state::paths::live_dirs() {
        assert!(!d.starts_with(&live), "{}", d.display());
    }
}

#[test]
fn tmux_swallow_line_keeps_only_a_short_first_line() {
    use cops_tmux::Swallowed;
    let l = copsd::tmux_swallow_line(Swallowed::DeleteBuffer, 3, "no buffer cops-1\n");
    assert_eq!(
        l,
        "copsd: tmux yutulan hata delete_buffer_failed (toplam 3): no buffer cops-1"
    );
    let l = copsd::tmux_swallow_line(Swallowed::StdinWrite, 1, "ilk\nPAROLA-PANE-METNI\n");
    assert!(!l.contains("PAROLA"), "{l}");
    assert!(l.ends_with("ilk [kırpıldı]"), "{l}");
    let long = "x".repeat(1000);
    let l = copsd::tmux_swallow_line(Swallowed::ReapChild, 1, &long);
    assert!(l.chars().count() < copsd::SWALLOW_TEXT_MAX + 100, "{l}");
    let l = copsd::tmux_swallow_line(Swallowed::KillChild, 1, "a\u{1b}[31mb\rc");
    assert!(!l.chars().any(char::is_control), "{l:?}");
}

/// Çok kullanıcı (yerel uç yetki kancası takılı): terminal uçları taban ada düşmez (yetki istekteki ada verilir; `x`in
/// sahibi kayıtsız `x7`yi okuyamasın). Tek kullanıcıda Python gibi taban ad.
#[test]
fn term_resolver_is_exact_only_in_multi_user() {
    let env = TestEnv::new().unwrap();
    let root = env.dir().root().to_path_buf();
    let mut ctx = RouteCtx::new(root, env.dir().db(), env.dir().instances_json());
    assert!(!ctx.multi_user);
    assert!(!copsd::routes::term_resolver(&ctx).is_exact_only());
    ctx.multi_user = true;
    assert!(copsd::routes::term_resolver(&ctx).is_exact_only());
}
