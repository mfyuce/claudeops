//! Sır argv'de yok (ders 2.5 "sırlar argv'de değil", H12): BYOK anahtarları komut satırına girmez, yalnız 0600
//! `WriteSecret` etkisine ve (çocuğun okuyacağı) dosyaya gider; `BuildOutput`un `Debug` çıktısı ve günlük olayları
//! anahtarı içermez. Sahte ikililer geçici ağaçta; gerçek HOME/ağ yok.

#[path = "g8/support.rs"]
mod support;

use cops_providers::{
    BuildArgs, BuildOutput, Cli, Effect, ModelCatalog, Paths, Providers, Settings,
};
use serde_json::{json, Map, Value};

const KEY: &str = "sk-proj-GIZLI-ANAHTAR-0123456789";

/// Yardım metni ucli'nin tanıdığı bayrakları listeler (yalnız bayrak desteği yoklaması için).
const UCLI_HELP: &str = "echo 'Usage: ucli [OPTIONS]'; for f in --model --effort --endpoint --api-key-env --api-key-file \
--provider --state-dir --session --usage-log --interactive --request-timeout-secs --max-steps --instructions-auto \
--metrics-dir --allow-exec --allow-write --write-root --allow-net; do echo \"  $f <X>\"; done";

/// Varsayılan (canlı) örnek: durum dizini ortak kök; anahtar dosyaları yazılır.
fn default_instance(t: &support::Tmp) -> Paths {
    Paths {
        claudeops_dir: t.path("home/.claude/claudeops"),
        ..t.paths()
    }
}

fn build(
    t: &support::Tmp,
    cli: Cli,
    settings: &Settings,
    opts: Option<&Map<String, Value>>,
) -> (String, BuildOutput) {
    build_at(t, default_instance(t), cli, settings, opts)
}

fn build_at(
    t: &support::Tmp,
    paths: Paths,
    cli: Cli,
    settings: &Settings,
    opts: Option<&Map<String, Value>>,
) -> (String, BuildOutput) {
    let _g = support::spawn_guard();
    let probe = t.probe();
    let catalog = ModelCatalog::default();
    let p = Providers {
        settings,
        catalog: &catalog,
        paths: &paths,
        probe: &probe,
    };
    let cwd = t.path("work");
    let args = BuildArgs {
        cwd: &cwd,
        model: "",
        permission_mode: "",
        effort: "",
        resume_id: None,
        prompt: Some("merhaba"),
        session_name: "s1",
        extra_args: &[],
        cli_opts: opts,
    };
    let mut out = BuildOutput::default();
    let cmd = p
        .build_inner_command(cli, &args, &mut out)
        .unwrap_or_else(|e| panic!("{cli:?}: {e:?}"));
    (cmd, out)
}

fn assert_secret_only_in_effect(cmd: &str, out: &BuildOutput, what: &str) {
    assert!(!cmd.contains("GIZLI"), "{what}: komut satırında sır: {cmd}");
    assert!(
        !format!("{out:?}").contains("GIZLI"),
        "{what}: Debug çıktısında sır"
    );
    assert!(
        !format!("{:?}", out.diags).contains("GIZLI"),
        "{what}: günlükte sır"
    );
    let secret = out
        .effects
        .iter()
        .filter_map(|e| match e {
            Effect::WriteSecret { content, .. } | Effect::WriteSpawnEnv { content, .. } => {
                Some(content.as_str())
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    assert!(
        secret.iter().any(|c| c.contains(KEY)),
        "{what}: sır 0600 dosyaya yazılmıyor: {:?}",
        out.effects
    );
    // Sır yalnız `WriteSecret`te: atomik yazım/dokunma içeriğinde yok.
    for e in &out.effects {
        if let Effect::WriteAtomic { content, .. } = e {
            assert!(!content.contains("GIZLI"), "{what}: WriteAtomic içinde sır");
        }
    }
}

#[test]
fn copilot_byok_key_goes_to_a_private_file_not_argv() {
    let t = support::Tmp::new();
    t.script("bin/copilot", "echo copilot");
    let settings =
        Settings::from_json(&json!({"byok": {"copilot": {"COPILOT_API_KEY": KEY}}}).to_string());
    let (cmd, out) = build(&t, Cli::Copilot, &settings, None);
    assert_secret_only_in_effect(&cmd, &out, "copilot");
    assert!(cmd.contains(&t.paths().copilot_env_file()), "{cmd}");
}

#[test]
fn ucli_evren_key_goes_to_a_private_file_not_argv() {
    let t = support::Tmp::new();
    t.script("bin/ucli", UCLI_HELP);
    let settings =
        Settings::from_json(&json!({"byok": {"ucli": {"UCLI_API_KEY": KEY}}}).to_string());
    let (cmd, out) = build(&t, Cli::Ucli, &settings, None);
    assert_secret_only_in_effect(&cmd, &out, "ucli evren");
}

#[test]
fn ucli_service_key_goes_to_a_private_file_not_argv() {
    let t = support::Tmp::new();
    t.script("bin/ucli", UCLI_HELP);
    let settings = Settings::from_json(
        &json!({
            "byok": {"ucli": {"OPENAI_API_KEY": KEY}},
            "ucli_services": [{"id": "openai", "label": "OpenAI", "env": "OPENAI_API_KEY",
                               "endpoint": "https://api.openai.com/v1", "wire": ""}]
        })
        .to_string(),
    );
    let mut opts = Map::new();
    opts.insert("service".into(), json!("openai"));
    let (cmd, out) = build(&t, Cli::Ucli, &settings, Some(&opts));
    assert_secret_only_in_effect(&cmd, &out, "ucli hizmet");
    assert!(
        cmd.contains("OPENAI_API_KEY"),
        "anahtar ADI (değeri değil) komutta: {cmd}"
    );
}

/// İkinci örnek (TBD#412 b): ortak anahtar dosyası yazılmaz, farklı anahtar komuta da dosyaya da girmez.
#[test]
fn a_second_instance_writes_no_shared_key_file() {
    let t = support::Tmp::new();
    t.script("bin/ucli", UCLI_HELP);
    t.script("bin/copilot", "echo copilot");
    for (cli, settings) in [
        (Cli::Ucli, json!({"byok": {"ucli": {"UCLI_API_KEY": KEY}}})),
        (
            Cli::Copilot,
            json!({"byok": {"copilot": {"COPILOT_API_KEY": KEY}}}),
        ),
    ] {
        let settings = Settings::from_json(&settings.to_string());
        let (cmd, out) = build_at(&t, t.paths(), cli, &settings, None);
        assert!(!cmd.contains("GIZLI") && !format!("{out:?}").contains("GIZLI"));
        assert!(
            !out.effects
                .iter()
                .any(|e| matches!(e, Effect::WriteSecret { .. } | Effect::Remove { .. })),
            "{:?}",
            out.effects
        );
        assert!(out.diags.iter().any(|d| d.event == "shared_key_readonly"));
    }
}

// ------------------------------------------------------------------------------------------- S4: açılış ortamı

/// S4: kanca/sağlayıcı ortamında adı `_KEY`/`_TOKEN`/`_SECRET` ile biten değer komut satırına girmez; yalnız
/// [`Effect::WriteSpawnEnv`] içeriğinde. Gerçek kabukta: değer çocuğa ulaşır, dosya yüklenince silinir, kalan kabuğa
/// sızmaz. Sır adı yoksa komut ve etki listesi eski biçimde.
#[test]
fn spawn_secret_env_goes_to_a_private_file_not_argv() {
    use cops_providers::real::effects;
    use cops_providers::spawn::{plan_spawn, SpawnRequest};
    let t = support::Tmp::new();
    t.script("bin/claude", "echo claude");
    let settings = Settings::from_json(r#"{"spawn_nice": "off"}"#);
    let paths = t.paths();
    let probe = t.probe();
    let catalog = ModelCatalog::default();
    let p = Providers {
        settings: &settings,
        catalog: &catalog,
        paths: &paths,
        probe: &probe,
    };
    let mut req = SpawnRequest {
        name: "s1".into(),
        cwd: t.path("work"),
        model: "m".into(),
        permission_mode: "auto".into(),
        effort: "high".into(),
        cli: "claude".into(),
        hook_env: vec![
            ("PROVIDER_DIR".into(), "/p d".into()),
            ("API_KEY".into(), format!("{KEY} 'q' $(id)")),
            ("MY_TOKEN".into(), "GIZLI-token".into()),
            ("X_SECRET".into(), "GIZLI-sir".into()),
        ],
        ..SpawnRequest::default()
    };
    let mut out = BuildOutput::default();
    let plan = {
        let _g = support::spawn_guard();
        plan_spawn(&p, &req, &mut out).unwrap()
    };
    assert_secret_only_in_effect(&plan.inner, &out, "spawn ortamı");
    assert!(
        plan.inner.contains("PROVIDER_DIR='/p d' "),
        "{}",
        plan.inner
    );
    assert!(
        !plan.dry_run_line(&req.cwd).contains("GIZLI"),
        "kuru satırda sır"
    );
    let effect = out
        .effects
        .iter()
        .find(|e| matches!(e, Effect::WriteSpawnEnv { .. }))
        .expect("WriteSpawnEnv yok")
        .clone();
    let Effect::WriteSpawnEnv { dir, file, .. } = &effect else {
        unreachable!()
    };
    assert_eq!(dir, &t.path("state/spawn-env"));
    let path = format!("{dir}/{file}");
    effects::apply(&effect).unwrap();
    assert_eq!(support::mode(dir), 0o700);
    assert_eq!(support::mode(&path), 0o600);
    let script = format!(
        "{}; echo KALAN=${{API_KEY-yok}}",
        plan.inner.replace(&plan.invocation, "env")
    );
    let run = std::process::Command::new("sh")
        .args(["-c", &script])
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&run.stdout);
    assert!(run.status.success(), "{stdout}");
    for (k, v) in &req.hook_env {
        assert!(stdout.contains(&format!("{k}={v}\n")), "{k}: {stdout}");
    }
    assert!(stdout.contains("KALAN=yok"), "{stdout}");
    assert!(
        !std::path::Path::new(&path).exists(),
        "dosya yüklenince silinmedi"
    );

    // Kuru kip: etki yok, satır maskeli.
    req.dry_run = true;
    let mut dry = BuildOutput::default();
    let dplan = plan_spawn(&p, &req, &mut dry).unwrap();
    assert!(dry.effects.is_empty(), "{dry:?}");
    assert!(!dplan.dry_run_line(&req.cwd).contains("GIZLI"));

    // Sır adı yok: eski komut biçimi, etki yok.
    req.dry_run = false;
    req.hook_env = vec![
        ("PROVIDER_DIR".into(), "/p d".into()),
        ("TOKENS".into(), "2".into()),
    ];
    let mut plain = BuildOutput::default();
    let pplan = plan_spawn(&p, &req, &mut plain).unwrap();
    assert!(
        !plain
            .effects
            .iter()
            .any(|e| matches!(e, Effect::WriteSpawnEnv { .. })),
        "{plain:?}"
    );
    assert_eq!(
        pplan.inner,
        format!(
            "cd {} && PROVIDER_DIR='/p d' TOKENS=2 {}",
            req.cwd, pplan.invocation
        )
    );
}

/// [`Effect::WriteSpawnEnv`] kapalı yöne düşer: bağlantı, dizin olmayan, başkasına ait ya da yazılamaz dizinde hiçbir
/// şey yazılmaz; var olan dosya EZİLMEZ; geniş izinli kendi dizini 0700'e daralır; eski artıklar silinir, tazeler kalır.
#[test]
fn spawn_env_file_fails_closed_and_never_overwrites() {
    use cops_providers::real::effects::{write_spawn_env, write_spawn_env_as};
    use std::fs;
    use std::os::unix::fs::PermissionsExt;
    let t = support::Tmp::new();
    let dir = t.path("state/spawn-env");
    let other = t.path("work/baska");
    fs::create_dir(&other).unwrap();

    std::os::unix::fs::symlink(&other, &dir).unwrap();
    let e = write_spawn_env(&dir, "a.env", KEY.as_bytes()).unwrap_err();
    // `O_DIRECTORY|O_NOFOLLOW` bağlantıda Linux'ta ENOTDIR (hedef dizin) ya da ELOOP verir
    assert!(
        matches!(e.1.raw_os_error(), Some(libc::ENOTDIR | libc::ELOOP)),
        "{e:?}"
    );
    assert_eq!(fs::read_dir(&other).unwrap().count(), 0);
    fs::remove_file(&dir).unwrap();

    t.write("state/spawn-env", "", 0o600);
    let e = write_spawn_env(&dir, "a.env", KEY.as_bytes()).unwrap_err();
    assert_eq!(e.1.raw_os_error(), Some(libc::ENOTDIR));
    fs::remove_file(&dir).unwrap();

    fs::create_dir(&dir).unwrap();
    fs::set_permissions(&dir, fs::Permissions::from_mode(0o700)).unwrap();
    // SAFETY: yan etkisiz sistem çağrısı.
    let me = unsafe { libc::geteuid() };
    let e = write_spawn_env_as(me + 1, &dir, "a.env", KEY.as_bytes()).unwrap_err();
    assert_eq!(e.1.raw_os_error(), Some(libc::EPERM));
    assert_eq!(fs::read_dir(&dir).unwrap().count(), 0);

    fs::set_permissions(&dir, fs::Permissions::from_mode(0o755)).unwrap();
    let old = t.write("state/spawn-env/eski.env", "export A_KEY=1\n", 0o600);
    let fresh = t.write("state/spawn-env/taze.env", "export A_KEY=2\n", 0o600);
    let past = std::time::SystemTime::now() - std::time::Duration::from_secs(3700);
    fs::File::options()
        .write(true)
        .open(&old)
        .unwrap()
        .set_modified(past)
        .unwrap();
    write_spawn_env(&dir, "b.env", b"export B_KEY=x\n").unwrap();
    assert_eq!(support::mode(&dir), 0o700);
    assert!(!std::path::Path::new(&old).exists(), "eski artık kaldı");
    assert!(std::path::Path::new(&fresh).exists());
    assert_eq!(support::mode(&format!("{dir}/b.env")), 0o600);

    let e = write_spawn_env(&dir, "taze.env", KEY.as_bytes()).unwrap_err();
    assert_eq!(e.1.raw_os_error(), Some(libc::EEXIST));
    assert_eq!(fs::read_to_string(&fresh).unwrap(), "export A_KEY=2\n");
    let names: Vec<String> = fs::read_dir(&dir)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    assert!(names.iter().all(|n| !n.ends_with(".tmp")), "{names:?}");

    if me != 0 {
        fs::set_permissions(&dir, fs::Permissions::from_mode(0o500)).unwrap();
        let e = write_spawn_env(&dir, "c.env", KEY.as_bytes()).unwrap_err();
        assert_eq!(e.1.raw_os_error(), Some(libc::EACCES));
        fs::set_permissions(&dir, fs::Permissions::from_mode(0o700)).unwrap();
    }
}

/// Gerçek token: 16 onaltılık karakter, art arda farklı.
#[test]
fn spawn_env_tokens_are_random_hex() {
    use cops_providers::real::effects::spawn_env_token;
    let (a, b) = (spawn_env_token(), spawn_env_token());
    assert_eq!(a.len(), 16);
    assert!(a.chars().all(|c| c.is_ascii_hexdigit()), "{a}");
    assert_ne!(a, b);
}
