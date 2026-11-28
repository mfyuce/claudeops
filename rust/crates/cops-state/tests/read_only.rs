//! B1 salt okuma kipi ([`StateDocs::into_read_only`]): okuma kararları ham yol ile AYNI, ama dizine hiçbir şey yazılmaz.
//! Her test aynı durumu önce salt okuma kipiyle okur (dizin anlık görüntüsü değişmez), sonra ham `StateDocs` ile okur ve
//! ham yolun YAZDIĞINI gösterir: ham yol yazmayı bırakırsa (ya da salt okuma yazarsa) test kırmızı olur.
mod common;
use common::{j, Env};
use cops_state::instances::Instances;
use cops_state::roster::{Roster, Tsv};
use cops_state::statedocs::{Read, WriteError};
use cops_state::{Backend, Json, StateDocs};
use std::collections::BTreeMap;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

/// Yol -> (içerik ya da `<dizin>`, izin): dosya/dizin/izin yaratılmadığının kanıtı.
fn snapshot(root: &Path) -> BTreeMap<String, (Vec<u8>, u32)> {
    let mut out = BTreeMap::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(d) = stack.pop() {
        for e in std::fs::read_dir(&d).unwrap() {
            let p = e.unwrap().path();
            let meta = std::fs::symlink_metadata(&p).unwrap();
            let key = p.strip_prefix(root).unwrap().to_string_lossy().into_owned();
            let mode = meta.permissions().mode();
            if meta.is_dir() {
                out.insert(key, (b"<dizin>".to_vec(), mode));
                stack.push(p);
            } else {
                out.insert(key, (std::fs::read(&p).unwrap(), mode));
            }
        }
    }
    out
}

fn ro(e: &Env, b: Backend) -> StateDocs {
    StateDocs::isolated(e.dir(), Some(b), "").into_read_only()
}

/// Ham yol, günlükçüsüz (`diag.log`a yazar).
fn raw(e: &Env, b: Backend) -> StateDocs {
    StateDocs::isolated(e.dir(), Some(b), "")
}

/// Python şemalı DB (WAL, süreç çıkınca yan dosyalar silinir).
fn py_db(e: &Env, set: &str) {
    e.py(
        "db",
        &format!("from claudeops.store import default_store\nst = default_store()\n{set}"),
    );
}

fn db_doc(e: &Env, name: &str) -> Option<Json> {
    ro(e, Backend::Db)
        .read_only_store()
        .unwrap()
        .get_doc(name)
        .unwrap()
}

const FILE_DOC: &str = r#"{"version": 1, "instances": {"dosya": {"cwd": "/f"}}}"#;
const DB_DOC: &str = r#"{"version": 1, "instances": {"db": {"cwd": "/d"}}}"#;

/// db kipi: DB'de olmayan belge dosyadan okunur; ham yol DB'ye İÇE AKTARIR, salt okuma aktarmaz.
#[test]
fn db_mode_lazy_import_only_on_raw_path() {
    let e = Env::new();
    py_db(&e, "");
    e.write("instances.json", FILE_DOC);
    let before = snapshot(&e.root);

    let docs = ro(&e, Backend::Db);
    let got = Instances::new(&docs).load();
    assert_eq!(got.keys().collect::<Vec<_>>(), ["dosya"]);
    assert_eq!(snapshot(&e.root), before, "salt okuma dizine dokundu");
    assert_eq!(db_doc(&e, "instances"), None);

    let docs = raw(&e, Backend::Db);
    assert_eq!(
        Instances::new(&docs).load().keys().collect::<Vec<_>>(),
        ["dosya"]
    );
    drop(docs);
    assert!(
        db_doc(&e, "instances").is_some(),
        "ham yol içe aktarmadı: karşılaştırma boş"
    );
    assert_ne!(snapshot(&e.root), before);
}

/// dual kipi: dosya doğruluk kaynağı; ham yol DB'yi dosyaya UYDURUR (drift), salt okuma uydurmaz.
#[test]
fn dual_mode_drift_only_on_raw_path() {
    let e = Env::new();
    py_db(
        &e,
        &format!("st.set_doc('instances', json.loads('{DB_DOC}'))"),
    );
    e.write("instances.json", FILE_DOC);
    let before = snapshot(&e.root);

    let docs = ro(&e, Backend::Dual);
    assert_eq!(
        Instances::new(&docs).load().keys().collect::<Vec<_>>(),
        ["dosya"]
    );
    assert!(matches!(
        docs.read("instances", &e.dir().instances_json()),
        Read::Value(_)
    ));
    assert_eq!(snapshot(&e.root), before);
    assert!(db_doc(&e, "instances").unwrap().py_eq(&j(DB_DOC)));

    let docs = raw(&e, Backend::Dual);
    Instances::new(&docs).load();
    drop(docs);
    assert!(
        db_doc(&e, "instances").unwrap().py_eq(&j(FILE_DOC)),
        "ham yol uydurmadı"
    );
    assert!(std::fs::read_to_string(e.state.join("diag.log"))
        .unwrap()
        .contains("drift instances"));
}

/// db kipi, bozuk ayna + DB satırı: değer DB'den; ham yol kanıt yedeği (`.corrupt-<sha8>`) ve `diag.log` yazar.
#[test]
fn corrupt_mirror_backup_only_on_raw_path() {
    let e = Env::new();
    py_db(
        &e,
        &format!("st.set_doc('instances', json.loads('{DB_DOC}'))"),
    );
    e.write("instances.json", "{yarim");
    let before = snapshot(&e.root);

    let docs = ro(&e, Backend::Db);
    let i = Instances::new(&docs);
    assert_eq!(
        i.read_strict()
            .unwrap()
            .get("instances")
            .unwrap()
            .as_object()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(i.load().keys().collect::<Vec<_>>(), ["db"]);
    assert_eq!(snapshot(&e.root), before);

    let docs = raw(&e, Backend::Db);
    Instances::new(&docs).read_strict().unwrap();
    let names: Vec<String> = snapshot(&e.state).into_keys().collect();
    assert!(
        names
            .iter()
            .any(|n| n.starts_with("instances.json.corrupt-")),
        "{names:?}"
    );
    assert!(names.iter().any(|n| n == "diag.log"), "{names:?}");
}

/// Yazım yüzleri: salt okumada reddedilir ya da sessizce hiçbir şey yapmaz; ham yolda aynı çağrılar yazar.
#[test]
fn write_surfaces_refused_in_read_only() {
    let e = Env::new();
    py_db(&e, "");
    e.write("roster.tsv", "a\t/a\tm\tclaude\n");
    e.write("instances.json", FILE_DOC);
    let before = snapshot(&e.root);

    let docs = ro(&e, Backend::Db);
    let path = e.dir().instances_json();
    assert!(matches!(
        docs.write("instances", &path, &j("{}"), None),
        Err(WriteError::ReadOnly)
    ));
    assert!(Instances::new(&docs).mutate(|m| m.clear()).is_err());
    assert!(Roster::new(&docs).lock().is_err());
    assert_eq!(Roster::new(&docs).raw_rows(Tsv::Roster).unwrap().len(), 1);
    assert!(!docs.mirror_log("diag", &e.state.join("diag.log"), &j("{}")));
    docs.shadow_tsv(&e.dir().roster_tsv(), true);
    docs.diag_log("salt_okuma_denemesi");
    assert_eq!(
        snapshot(&e.root),
        before,
        "salt okuma yazım yüzü dizine dokundu"
    );

    // ham yol: aynı çağrılar yazar
    let docs = raw(&e, Backend::Db);
    assert!(Roster::new(&docs).raw_rows(Tsv::Roster).is_ok());
    assert!(
        docs.store()
            .unwrap()
            .tsv_text("roster.tsv")
            .unwrap()
            .is_some(),
        "ham shadow_tsv yazmadı"
    );
    assert!(docs.mirror_log("diag", &e.state.join("diag.log"), &j("{}")));
    docs.diag_log("ham");
    assert!(e.state.join("diag.log").exists());
    assert!(Instances::new(&docs).mutate(|m| m.clear()).is_ok());
    assert!(e.state.join("instances.json.lock").exists());
}

/// DB okunamıyor (şema sürümü farklı): iki yol da dosyaya düşer; ham yol bunu `diag.log`a yazar, salt okuma yazmaz.
#[test]
fn db_error_fallback_logs_only_on_raw_path() {
    let e = Env::new();
    py_db(&e, "st._conn().execute('PRAGMA user_version=99')");
    e.write("instances.json", FILE_DOC);
    let before = snapshot(&e.root);
    let docs = ro(&e, Backend::Db);
    assert_eq!(
        Instances::new(&docs).load().keys().collect::<Vec<_>>(),
        ["dosya"]
    );
    assert_eq!(snapshot(&e.root), before);
    let docs = raw(&e, Backend::Db);
    assert_eq!(
        Instances::new(&docs).load().keys().collect::<Vec<_>>(),
        ["dosya"]
    );
    assert!(std::fs::read_to_string(e.state.join("diag.log"))
        .unwrap()
        .contains("statedocs read instances"));
}

/// Daha yeni şema uyarısı salt okuma açılışından gelir: yazma kipindeki (günlükçüsüz) `StateDocs`ta da dizine dokunmaz.
#[test]
fn newer_schema_warning_never_writes_diag_log() {
    let e = Env::new();
    py_db(&e, "");
    let c = rusqlite::Connection::open(e.dir().db()).unwrap();
    // `schema_version` tablosu varsa sürüm `max(tablo, user_version)`
    c.pragma_update(None, "user_version", cops_state::store::SCHEMA_VERSION + 1)
        .unwrap();
    drop(c);
    let docs = raw(&e, Backend::Db);
    let st = docs.read_only_store().unwrap();
    assert!(st.schema() > cops_state::store::SCHEMA_VERSION);
    assert!(
        !e.dir().join("diag.log").exists(),
        "salt okuma diag.log yazdı"
    );
}
