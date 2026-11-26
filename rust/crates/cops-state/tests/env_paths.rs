//! `paths.py` sabitleri (`HOME` tabanlı olanlar dahil), `ucli_key_file`, `/proc` yardımcıları ve
//! `ensure_private_state_dir` paritesi. Ayrı test ikilisi (tek test): `HOME` bu süreçte GEÇİCİ dizine çevrilir.
use cops_state::paths::{self, ProcError};
use cops_state::{Json, StateDir};
use std::os::unix::fs::PermissionsExt;

mod common;
use common::{j, Env};

#[test]
fn paths_match_python() {
    let e = Env::new();
    let home = e.root.join("home");
    // SAFETY: bu ikilide tek test var; ortamı başka iş parçacığı okumaz.
    unsafe { std::env::set_var("HOME", &home) };
    let me = std::process::id();
    let out = e.py(
        "files",
        &format!(
            "from claudeops import paths as p\n\
             print(json.dumps([p.HOME, p.CLAUDE_DIR, p.SESSIONS_DIR, p.PROJECTS_DIR, p.CONFIG_JSON, p.GUARD_LOCK, p.CLAUDE_MODELS_JSON,\n\
             \x20 p.ucli_key_file(), p.ucli_key_file(''), p.ucli_key_file('groq'), p.proc_ppid({me}), p.proc_stat_fields({me})[19], p.proc_stat_fields({me})[1]]))"
        ),
    );
    let s = |p: std::path::PathBuf| Json::from(p.display().to_string());
    let fields = paths::proc_stat_fields(me).unwrap();
    let ppid = paths::proc_ppid(me).unwrap();
    let rs = Json::Array(vec![
        paths::home().into(),
        s(paths::claude_dir()),
        s(paths::sessions_dir()),
        s(paths::projects_dir()),
        s(paths::config_json()),
        s(paths::guard_lock()),
        s(e.dir().claude_models_json()),
        paths::ucli_key_file("").into(),
        paths::ucli_key_file("").into(),
        paths::ucli_key_file("groq").into(),
        Json::Int(ppid),
        fields[19].as_str().into(),
        fields[1].as_str().into(),
    ]);
    assert_eq!(rs, j(out.trim_end()));
    let h = home.display();
    assert_eq!(paths::home(), h.to_string());
    assert_eq!(paths::sessions_dir(), home.join(".claude/sessions"));
    assert_eq!(paths::projects_dir(), home.join(".claude/projects"));
    assert_eq!(paths::config_json(), home.join(".claude.json"));
    assert_eq!(
        paths::ucli_key_file(""),
        format!("{h}/.claude/claudeops/ucli_api_key"),
        "boş hizmet: Evren anahtarı"
    );
    assert_eq!(
        paths::ucli_key_file("groq"),
        format!("{h}/.claude/claudeops/ucli_key_groq")
    );
    // SAFETY: getuid/getppid her zaman başarılıdır.
    let (uid, parent) = unsafe { (libc::getuid(), libc::getppid()) };
    assert_eq!(
        paths::guard_lock(),
        std::path::PathBuf::from(format!("/tmp/claudeops-{uid}/guard.lock"))
    );
    assert_eq!(ppid, i64::from(parent));
    assert_eq!(fields[1], parent.to_string());
    assert!(matches!(
        paths::proc_stat_fields(u32::MAX),
        Err(ProcError::Io(_))
    ));
    assert!(matches!(paths::proc_ppid(u32::MAX), Err(ProcError::Io(_))));
    assert!(
        !home.join(".claude").exists(),
        "yol işlevleri dizin yaratmaz"
    );

    // ensure_private_state_dir: yoksa oluşturur (ara dizinlerle), varsa 0700'e çeker; Python aynı
    let mode = |p: &std::path::Path| std::fs::metadata(p).unwrap().permissions().mode() & 0o7777;
    for (n, existing) in [("yeni", false), ("acik", true)] {
        let (a, b) = (
            e.root.join(format!("py-{n}/s")),
            e.root.join(format!("rs-{n}/s")),
        );
        for d in [&a, &b] {
            if existing {
                std::fs::create_dir_all(d).unwrap();
                std::fs::set_permissions(d, std::fs::Permissions::from_mode(0o755)).unwrap();
            }
        }
        let st = e
            .command(
                "files",
                "from claudeops import paths\npaths.ensure_private_state_dir()",
            )
            .env("CLAUDEOPS_DIR", &a)
            .status()
            .unwrap();
        assert!(st.success());
        let d = StateDir::at(&b);
        d.ensure_private().unwrap();
        d.ensure_private().unwrap();
        assert_eq!(mode(&a), 0o700, "{n}");
        assert_eq!(mode(&b), 0o700, "{n}");
    }
}
