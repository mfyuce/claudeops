//! `paths::realpath` = Python `os.path.realpath` (katı değil), gözden geçirme agy R-2: hedefi olmayan bağda `..` ve ara bağlar
//! da çözülür (`db_ok`/`guard_write` kararı Python'la aynı olsun). Gerçek `python3`e karşı.
use cops_state::paths::realpath;
use cops_state::TestEnv;
use std::os::unix::fs::symlink;
use std::path::PathBuf;

#[test]
fn realpath_matches_python_on_dangling_and_chained_links() {
    let env = TestEnv::new().unwrap();
    let r = env.root().join("rp");
    let real = r.join("gercek");
    std::fs::create_dir_all(real.join("alt")).unwrap();
    std::fs::create_dir_all(r.join("b")).unwrap();
    let s = |t: &str, l: &str| symlink(t, r.join(l)).unwrap();
    s("yok/../gercek/dosya", "sarkan_nokta"); // hedef yok, içinde `..`
    s("ara/alt/x", "ara_uzerinden"); // ara bileşen bağ, kuyruk yok
    s("gercek", "ara");
    s("/nonexistent-cops/../tmp", "mutlak_sarkan");
    s("dongu2", "dongu1");
    s("dongu1", "dongu2");
    s("../gercek/alt/../yeni", "b/ust");
    s("zincir2", "zincir1");
    s("zincir3/../gercek", "zincir2");
    let cases: Vec<PathBuf> = [
        "sarkan_nokta",
        "sarkan_nokta/ek",
        "ara_uzerinden",
        "ara/alt/../alt/z",
        "mutlak_sarkan",
        "dongu1/x",
        "b/ust",
        "b/ust/../q",
        "zincir1/alt",
        "gercek/./alt//y",
        "yok1/yok2/..",
    ]
    .iter()
    .map(|c| r.join(c))
    .collect();
    let out = std::process::Command::new("python3")
        .args([
            "-I",
            "-c",
            "import os, sys\nfor p in sys.argv[1:]: print(os.path.realpath(p))",
        ])
        .args(&cases)
        .output()
        .unwrap();
    assert!(out.status.success());
    let py = String::from_utf8(out.stdout).unwrap();
    let rs: String = cases
        .iter()
        .map(|c| format!("{}\n", realpath(c).display()))
        .collect();
    assert_eq!(rs, py);
}
