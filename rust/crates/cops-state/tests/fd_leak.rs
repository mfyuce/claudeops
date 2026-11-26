//! H1: tanıtıcı sızıntısı yok. Ayrı test ikilisi (tek test): başka testlerin açtığı tanıtıcılar sayımı bozmasın.
//! Tüm genel yollar (DB, belge, kilit, TSV, instances, ayar, yedek, hata yolları) 60 kez çalıştırılır; `/proc/self/fd`
//! sayısı önce/sonra aynı olmalı.
use cops_state::fsutil::FileLock;
use cops_state::instances::{Instances, NewInstance};
use cops_state::roster::{Roster, Tsv};
use cops_state::settings::SettingsReader;
use cops_state::{Backend, Json, StateDocs, Store, TestEnv};
use std::time::Duration;

fn fds() -> usize {
    std::fs::read_dir("/proc/self/fd").unwrap().count()
}

#[test]
fn no_fd_leak() {
    let env = TestEnv::new().unwrap();
    let st = std::process::Command::new("python3")
        .args(["-B", "-c", "import sys; sys.path.insert(0, sys.argv[1]); from claudeops.store import default_store; default_store()"])
        .arg(std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../py"))
        .env("CLAUDEOPS_DIR", env.dir().root())
        .env("CLAUDEOPS_EXTENSIONS", "")
        .status()
        .unwrap();
    assert!(st.success());
    let d = env.dir().clone();
    let j = Json::parse(r#"{"a": [1, "ş"]}"#).unwrap();
    let round = |i: usize| {
        let docs = StateDocs::isolated(d.clone(), Some(Backend::Db), "").with_logger(|_| {});
        docs.write("hosts", &d.doc_path("hosts"), &j, Some(0o600))
            .unwrap();
        assert!(docs
            .read("hosts", &d.doc_path("hosts"))
            .into_option()
            .is_some());
        docs.mirror_log("diag", &d.join("diag.log"), &j);
        let dual = StateDocs::isolated(d.clone(), Some(Backend::Dual), "").with_logger(|_| {});
        dual.write("orchdraft", &d.doc_path("orchdraft"), &j, None)
            .unwrap();
        dual.read("orchdraft", &d.doc_path("orchdraft"));
        Instances::new(&docs)
            .record(&format!("n{i}"), &NewInstance::default())
            .unwrap();
        Instances::new(&docs).load();
        {
            let g = Roster::new(&docs).lock().unwrap();
            g.append(Tsv::Roster, &[&format!("r{i}"), "/c", "m"])
                .unwrap();
            let _inner = FileLock::acquire(&d.join("roster")).unwrap(); // yeniden giriş
        }
        Roster::new(&docs).fleet_status().unwrap();
        // hata yolları: kilit zaman aşımı, olmayan DB, bozuk belge
        let held = FileLock::acquire(&d.join("x")).unwrap();
        let t = std::thread::spawn({
            let p = d.join("x");
            move || FileLock::acquire_within(&p, Duration::from_millis(1)).is_err()
        });
        assert!(t.join().unwrap());
        drop(held);
        assert!(Store::open(&d.join("yok.db")).is_err());
        std::fs::write(d.join("instances.json"), "{bozuk").unwrap();
        assert!(Instances::new(&docs).forget("n0").is_err());
        std::fs::remove_file(d.join("instances.json")).unwrap();
        // atomik yazım hatası (`rename` hedefi dizin): tanıtıcı da geçici dosya da kalmaz
        let dolu = d.join("dolu-dizin");
        std::fs::create_dir_all(dolu.join("x")).unwrap();
        assert!(cops_state::fsutil::atomic_write_text(&dolu, "x", None).is_err());
        assert!(cops_state::fsutil::atomic_write_json(&dolu, &j, None).is_err());
        assert!(cops_state::fsutil::atomic_write_tsv(&dolu, "x").is_err());
        assert!(!std::fs::read_dir(d.root()).unwrap().any(|e| e
            .unwrap()
            .file_name()
            .to_string_lossy()
            .ends_with(".tmp")));
        SettingsReader::new(d.clone()).load();
        let s = Store::open(&d.db()).unwrap();
        s.backup(&env.root().join("yedek.db")).unwrap();
        s.export_all().unwrap();
    };
    round(0); // tembel başlatmalar (OnceLock vb.) sayımdan önce
    let before = fds();
    for i in 1..60 {
        round(i);
    }
    assert_eq!(fds(), before, "tanıtıcı sızıntısı");
}
