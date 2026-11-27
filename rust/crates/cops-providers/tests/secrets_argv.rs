//! Sır argv'de yok (ders 2.5 "sırlar argv'de değil", H12): BYOK anahtarları komut satırına girmez, yalnız 0600
//! `WriteSecret` etkisine ve (çocuğun okuyacağı) dosyaya gider; `BuildOutput`un `Debug` çıktısı ve günlük olayları
//! anahtarı içermez. Sahte ikililer geçici ağaçta; gerçek HOME/ağ yok.

#[path = "g8/support.rs"]
mod support;

use cops_providers::{BuildArgs, BuildOutput, Cli, Effect, ModelCatalog, Providers, Settings};
use serde_json::{json, Map, Value};

const KEY: &str = "sk-proj-GIZLI-ANAHTAR-0123456789";

/// Yardım metni ucli'nin tanıdığı bayrakları listeler (yalnız bayrak desteği yoklaması için).
const UCLI_HELP: &str = "echo 'Usage: ucli [OPTIONS]'; for f in --model --effort --endpoint --api-key-env --api-key-file \
--provider --state-dir --session --usage-log --interactive --request-timeout-secs --max-steps --instructions-auto \
--metrics-dir --allow-exec --allow-write --write-root --allow-net; do echo \"  $f <X>\"; done";

fn build(
    t: &support::Tmp,
    cli: Cli,
    settings: &Settings,
    opts: Option<&Map<String, Value>>,
) -> (String, BuildOutput) {
    let _g = support::spawn_guard();
    let probe = t.probe();
    let catalog = ModelCatalog::default();
    let paths = t.paths();
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
            Effect::WriteSecret { content, .. } => Some(content.as_str()),
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
