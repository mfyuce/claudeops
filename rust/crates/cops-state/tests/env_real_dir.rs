//! Test koşucusu algısının ortam dalları (`_under_test_runner`) ve geçici durum dizininin yaşam döngüsü. Algı süreç
//! başına bir kez hesaplandığı için her durum bu ikilinin ALT SÜRECİ olarak koşar; `HOME` her zaman geçicidir.
use cops_state::paths::{under_test, StateDir, ENV_DIR, ENV_TEST_REAL};
use cops_state::TestEnv;
use std::path::PathBuf;
use std::process::Command;

const CHILD: &str = "COPS_STATE_PROBE";

/// Alt süreç gövdesi (ana koşuda hiçbir şey yapmaz).
#[test]
fn probe_child() {
    if std::env::var_os(CHILD).is_none() {
        return;
    }
    let dir = StateDir::resolve().unwrap();
    let mut seen = String::new();
    if under_test() {
        // geçici dizine yaz, alt sürece devret
        std::fs::create_dir_all(dir.root()).unwrap();
        std::fs::write(dir.settings_json(), "{}").unwrap();
        let mut c = Command::new("python3");
        c.args(["-B", "-c", "import os; print(os.environ['CLAUDEOPS_DIR'])"]);
        dir.apply_env(&mut c);
        seen = String::from_utf8(c.output().unwrap().stdout).unwrap();
        assert!(
            std::env::var_os(ENV_DIR).is_none(),
            "süreç ortamına kendiliğinden yazılmaz"
        );
    }
    println!(
        "SONUC|{}|{}|{}",
        under_test(),
        dir.root().display(),
        seen.trim()
    );
}

fn probe(home: &std::path::Path, real: Option<&str>) -> (bool, PathBuf, String) {
    let mut c = Command::new(std::env::current_exe().unwrap());
    c.args(["--exact", "probe_child", "--nocapture", "--test-threads=1"])
        .env(CHILD, "1")
        .env("HOME", home)
        .env_remove(ENV_DIR)
        .env_remove(ENV_TEST_REAL);
    if let Some(v) = real {
        c.env(ENV_TEST_REAL, v);
    }
    let o = c.output().unwrap();
    let out = String::from_utf8_lossy(&o.stdout).into_owned();
    assert!(o.status.success(), "{out}");
    let line = &out[out.find("SONUC|").expect("sonuç satırı")..];
    let mut f = line.lines().next().unwrap().split('|').skip(1);
    (
        f.next().unwrap() == "true",
        f.next().unwrap().into(),
        f.next().unwrap().into(),
    )
}

#[test]
fn test_runner_env_branches() {
    let env = TestEnv::new().unwrap();
    let home = env.root().to_path_buf();
    // `1` kapatır: gerçek dizin (burada geçici HOME altında) çözülür, hiçbir şey yazılmaz
    let (test, root, _) = probe(&home, Some("1"));
    assert!(!test);
    assert_eq!(root, home.join(".claude/claudeops"));
    assert!(!root.exists());
    // başka her değer test algısını sürdürür (Python `== "1"`)
    for v in [None, Some("0"), Some("true"), Some(""), Some("1 ")] {
        let (test, root, seen) = probe(&home, v);
        assert!(test, "{v:?}");
        assert!(root.starts_with(std::env::temp_dir()), "{root:?}");
        assert!(!root.starts_with(&home));
        assert_eq!(PathBuf::from(seen), root, "alt sürece devir");
        assert!(!root.exists(), "süreç çıkışında silinir: {root:?}");
    }
}
