//! Aile (G10): tek atımlık çağrı ve onay kaydı. İki tarafta da GERÇEK alt süreç koşar, ama ikili YALNIZ vaka ağacındaki
//! sahte kabuk betikleridir (`repo_dir` de ağaca çevrilir: depodaki `bin/ucli` hiçbir yoldan seçilemez). Karşılaştırılan:
//! dönüş / hata metni, betiğin gördüğü argv ve ortam (`work/call.txt`), dosya ağacı ve izinler, `diag.log`.

use crate::common::*;
use crate::fam_bg::Rng;
use cops_providers::approval::{self, NewRun};
use cops_providers::oneshot::{self, ChatArgv};
use cops_providers::pyjson::Py;
use cops_providers::real::approval::ApprovalStore;
use cops_providers::real::diaglog::DiagLog;
use cops_providers::real::oneshot::{ApiKey, ChatRequest, OneShot};
use cops_providers::{Cli, Providers};
use serde_json::{json, Value};

const NOW: f64 = 1_790_000_000.25;
const KEY: &str = "sk-g10-gizli-anahtar-0001";
const HELP: &str = "--state-dir <D> --approval-dir <D>";

/// Sahte ucli: `chat --help` bayrakları basar; öteki çağrılarda argv'yi ve ilgili ortamı `work/call.txt`ye ekler.
fn ucli_script(root: &str, rel: &str, help: &str, body: &str) -> Fx {
    file(
        rel,
        &format!(
            "#!/bin/sh\nif [ \"$1 $2\" = 'chat --help' ]; then echo '{help}'; exit 0; fi\n\
             {{ for a in \"$@\"; do printf '[%s]\\n' \"$a\"; done\n\
             printf 'key=%s other=%s\\n' \"$UCLI_API_KEY\" \"$X_API_KEY\"; }} >> '{root}/work/call.txt'\n{body}\n"
        ),
        0o755,
    )
}

const ANSWER: &str = r#"echo '{"answer":"tamam","model_rounds":1,"tool_calls":0}'"#;

fn suspended(id: &str) -> String {
    format!("echo 'gürültü'; echo '{{\"suspended\":{{\"id\":\"{id}\",\"state\":\"s\",\"resume\":\"r\"}}}}'; exit 75")
}

fn chat_cases(r: &str) -> Vec<Case> {
    let ucli = format!("{r}/bin/ucli");
    let root = format!("{r}/work/p1");
    let call = |prompt: &str, kw: Value| {
        let mut full = json!({"binary": ucli, "timeout": 10.0});
        full.as_object_mut()
            .unwrap()
            .extend(kw.as_object().unwrap().clone());
        json!({"root": root, "prompt": prompt, "kw": full})
    };
    let case = |id: String, body: &str, calls: Vec<Value>| {
        Case::new(
            format!("sohbet-{id}"),
            "g10_chat",
            json!({"now": NOW, "calls": calls}),
        )
        .file(ucli_script(r, "bin/ucli", HELP, body))
    };
    let plain = || vec![call("merhaba dünya", json!({}))];
    let mut v = vec![case("basit".into(), ANSWER, plain())];
    // çıkış / çıktı biçimleri
    let long = "i=0; while [ $i -lt 40 ]; do echo \"satır $i ğ\" >&2; i=$((i+1)); done; exit 3";
    for (id, body) in [
        ("cikis-stderr", "echo '  hata metni  ' >&2; exit 2"),
        ("cikis-sessiz", "exit 4"),
        ("cikis-bosluk", "printf ' \\n\\t' >&2; exit 4"),
        ("cikis-uzun", long),
        ("cikis-75-anahtarsiz", "echo '{\"suspended\":{\"id\":\"a\"}}'; exit 75"),
        ("sinyal", "kill -KILL $$"),
        ("bos", "true"),
        ("bozuk", "echo 'json değil'"),
        ("bozuk-iki", "echo '{} {}'"),
        ("liste", "echo '[1, 2]'"),
        ("sayi", "echo 5"),
        ("dize", "echo '\"error\"'"),
        ("null", "echo null"),
        ("derin", "head=''; i=0; while [ $i -lt 14 ]; do head=\"[$head$head\"; i=$((i+1)); done; printf %s \"$head\""),
        ("hata-dize", "echo '{\"error\":\"model yok\"}'"),
        ("hata-null", "echo '{\"error\":null}'"),
        ("hata-nesne", "echo '{\"error\":{\"kod\":5,\"ad\":\"ğ\\n\",\"x\":[true,1.5]}}'"),
        ("hata-ve-cikis", "echo '{\"error\":\"x\"}'; echo stderr >&2; exit 1"),
        ("butce", "echo '{\"answer\":\"yarım\",\"budget_exhausted\":\"failures\"}'"),
        ("butce-bilinmeyen", "echo '{\"answer\":\"y\",\"budget_exhausted\":[\"a\",1]}'"),
        ("crlf", "printf '{\"answer\":\\r\\n\"a\"}\\r\\n'"),
        ("crlf-stderr", "printf 'bir\\r\\niki\\r' >&2; exit 2"),
        ("utf8", "printf '\\377'"),
        ("utf8-stderr", "printf '\\377' >&2; echo '{}'"),
        ("stdin", "read x; printf '{\"answer\":\"[%s]\"}' \"$x\""),
    ] {
        v.push(case(id.into(), body, plain()));
    }
    v.push(case(
        "zaman-asimi".into(),
        "exec /bin/sleep 20",
        vec![call("p", json!({"timeout": 0.5}))],
    ));
    // argv seçenekleri ve anahtar
    v.push(case(
        "tum-bayraklar".into(),
        ANSWER,
        vec![call(
            "p q",
            json!({"model": "m1", "endpoint": "http://e/v1", "with_mcp": true, "max_steps": 7,
            "extra_args": ["--allow-edit", "--max-io-mib", "3"], "api_key": KEY}),
        )],
    ));
    v.push(case(
        "bos-degerler".into(),
        ANSWER,
        vec![call(
            "p",
            json!({"model": "", "endpoint": "", "session": "", "max_steps": 0,
            "approval_run_key": ""}),
        )],
    ));
    let services = |envs: &[&str]| {
        let list: Vec<Value> = envs
            .iter()
            .enumerate()
            .map(|(i, e)| json!({"id": format!("h{i}"), "endpoint": "https://h.invalid/v1", "env": e}))
            .collect();
        json!({ "ucli_services": list })
    };
    v.push(
        case(
            "anahtar-adi".into(),
            ANSWER,
            vec![call(
                "p",
                json!({"api_key": KEY, "api_key_env": "X_API_KEY"}),
            )],
        )
        .settings_json(services(&["X_API_KEY"])),
    );
    // TBD#401: yalnız `UCLI_API_KEY` ve ayardaki hizmetlerin `env`i; belirsiz ayarda yalnız `UCLI_API_KEY`.
    let named = |name: &str| {
        vec![
            call("p", json!({"api_key_env": name})),
            call("p", json!({"api_key_env": name, "api_key": KEY})),
        ]
    };
    for (id, name) in [
        ("varsayilan", "UCLI_API_KEY"),
        ("yerlesik", "ANTHROPIC_API_KEY"),
        ("baska", "HOME"),
        ("tanimsiz", "OZEL_API_KEY"),
        ("anahtar-yapistirilmis", KEY),
    ] {
        v.push(case(format!("tbd401-{id}"), ANSWER, named(name)).env("OZEL_API_KEY", KEY));
    }
    for (id, name) in [
        ("hizmet", "OZEL_API_KEY"),
        ("hizmet-listesi-disi", "GROQ_API_KEY"),
        // ayarda tanımlı ama `*_API_KEY` değil: anahtar verilince eski ad denetimi de reddeder
        ("hizmet-baska-bicim", "BASKA_SIR"),
    ] {
        v.push(
            case(format!("tbd401-{id}"), ANSWER, named(name))
                .settings_json(services(&["OZEL_API_KEY", "BASKA_SIR"])),
        );
    }
    for (id, doc) in [
        ("bozuk", "{bozuk"),
        ("liste", "[1]"),
        ("hizmet-null", r#"{"ucli_services": null}"#),
        ("hizmet-metin", r#"{"ucli_services": "x"}"#),
        ("hizmet-bos", r#"{"ucli_services": []}"#),
    ] {
        for name in ["ANTHROPIC_API_KEY", "UCLI_API_KEY"] {
            v.push(
                case(format!("tbd401-ayar-{id}-{name}"), ANSWER, named(name)).file(file(
                    "state/settings.json",
                    doc,
                    0o600,
                )),
            );
        }
    }
    v.push(
        case(
            "anahtar-bos".into(),
            ANSWER,
            vec![call("p", json!({"api_key": ""}))],
        )
        .env("UCLI_API_KEY", "miras"),
    );
    v.push(case("anahtar-miras".into(), ANSWER, plain()).env("UCLI_API_KEY", KEY));
    for (i, name) in [
        "",
        "LD_PRELOAD",
        "X_API_KEY\n",
        "x_API_KEY",
        "_API_KEY",
        "PATH",
    ]
    .iter()
    .enumerate()
    {
        v.push(case(
            format!("anahtar-adi-ret{i}"),
            ANSWER,
            vec![call("p", json!({"api_key": KEY, "api_key_env": name}))],
        ));
    }
    for (i, prompt) in [
        "-",
        "--allow-edit",
        "-x",
        "- madde",
        "a -b",
        "",
        "ğ\nikinci",
        "$(x) `y` ; z",
    ]
    .iter()
    .enumerate()
    {
        v.push(case(
            format!("prompt{i}"),
            ANSWER,
            vec![call(prompt, json!({}))],
        ));
    }
    v.push(case(
        "prompt-nul".into(),
        ANSWER,
        vec![call("a\0b", json!({}))],
    ));
    v.push(case(
        "anahtar-nul".into(),
        ANSWER,
        vec![call("p", json!({"api_key": "a\0b"}))],
    ));
    // sır silme: her hata yolu
    for (i, body) in [
        "echo \"bad key $UCLI_API_KEY\" >&2; exit 2",
        "echo \"not json $UCLI_API_KEY\"",
        "printf '{\"error\":\"key %s\"}' \"$UCLI_API_KEY\"",
        "echo \"[\\\"$UCLI_API_KEY\\\"]\"",
    ]
    .iter()
    .enumerate()
    {
        v.push(case(
            format!("sir-acik{i}"),
            body,
            vec![call("p", json!({"api_key": KEY}))],
        ));
        v.push(case(format!("sir-miras{i}"), body, plain()).env("UCLI_API_KEY", KEY));
        v.push(case(
            format!("sir-kisa{i}"),
            body,
            vec![call("p", json!({"api_key": "kisa"}))],
        ));
    }
    // çalıştırılamayan ikili
    let bad = |id: &str, bin: String, fx: Vec<Fx>| {
        let mut c = Case::new(
            format!("ikili-{id}"),
            "g10_chat",
            json!({"now": NOW, "calls": [call("p", json!({"binary": bin}))]}),
        );
        c.files = fx;
        c
    };
    v.push(bad("yok", format!("{r}/bin/yok"), vec![]));
    v.push(bad("ad-yok", "yok-boyle-ucli".into(), vec![]));
    v.push(bad(
        "izinsiz",
        format!("{r}/bin/izinsiz"),
        vec![file("bin/izinsiz", "#!/bin/sh\n", 0o644)],
    ));
    v.push(bad("dizin", format!("{r}/bin"), vec![]));
    // `#!` satırı olmayan betik: iki tarafta da `ENOEXEC` (kabuğa düşülmez)
    v.push(bad(
        "satirsiz-betik",
        format!("{r}/bin/satirsiz"),
        vec![file("bin/satirsiz", "echo '{}'\n", 0o755)],
    ));
    v.push(bad(
        "yorumlayici-yok",
        format!("{r}/bin/bozuk"),
        vec![file("bin/bozuk", "#!/yok/yorumlayici\n", 0o755)],
    ));
    // ikili çözümü: ayar, PATH, hiçbiri
    let no_bin = json!({"root": root, "prompt": "p", "kw": {"timeout": 10.0}});
    v.push(
        Case::new(
            "coz-ayar",
            "g10_chat",
            json!({"now": NOW, "calls": [no_bin]}),
        )
        .file(ucli_script(r, "work/ozel", HELP, ANSWER))
        .settings_json(json!({"provider_bin": {"ucli": format!("{r}/work/ozel")}})),
    );
    v.push(
        Case::new(
            "coz-path",
            "g10_chat",
            json!({"now": NOW, "calls": [no_bin]}),
        )
        .file(ucli_script(r, "bin/ucli", HELP, ANSWER)),
    );
    v.push(
        Case::new(
            "coz-hic",
            "g10_chat",
            json!({"now": NOW, "calls": [no_bin]}),
        )
        .file(Fx::Remove("bin/ucli".into())),
    );
    // --state-dir
    let sdir = cops_providers::ucli::state_dir_for("home/.claude/claudeops/ucli-state", &root);
    // `state_dir_for` kökü göreli verildi: fixture yolu köke göredir
    let new_file = file(&format!("{sdir}/s1.jsonl"), "{}\n", 0o600);
    let old_file = file("work/p1/.ucli/chat/s1.jsonl", "{}\n", 0o600);
    for (on, new, old, help) in [
        (true, false, false, HELP),
        (false, false, false, HELP),
        (true, false, true, HELP),
        (false, true, false, HELP),
        (true, true, true, HELP),
        (false, false, true, HELP),
        (true, false, false, "--x"),
    ] {
        let mut c = Case::new(format!("durum-dizini-{on}-{new}-{old}-{}", help.len()), "g10_chat",
            json!({"now": NOW, "calls": [call("p", json!({"session": "s1", "extra_args": ["--z"]}))]}))
            .file(ucli_script(r, "bin/ucli", help, ANSWER))
            .settings_json(json!({"ucli_limits": {"state_dir": if on { "on" } else { "off" }}}));
        if new {
            c = c.file(new_file.clone());
        }
        if old {
            c = c.file(old_file.clone());
        }
        v.push(c);
    }
    // onay kanalı
    let appr = |key: &str| {
        call(
            "yap",
            json!({"approval_run_key": key, "approval_owner": "ali", "session": "s1",
        "extra_args": ["--allow-edit", "--ask-edit"], "api_key": KEY}),
        )
    };
    let index = "state/ucli_approval/index.json";
    let ok = suspended("onay-1");
    v.push(case("onay-askida".into(), &ok, vec![appr("r1")]));
    v.push(case(
        "onay-oturumsuz".into(),
        &ok,
        vec![call("yap", json!({"approval_run_key": "r1"}))],
    ));
    v.push(case("onay-bitti".into(), ANSWER, vec![appr("r1")]));
    v.push(case(
        "onay-iki-kez".into(),
        &ok,
        vec![appr("r1"), appr("r1"), appr("r2")],
    ));
    v.push(case(
        "onay-satirsiz".into(),
        "echo hiç; exit 75",
        vec![appr("r1")],
    ));
    v.push(case(
        "onay-satirsiz-stderr".into(),
        "echo neden >&2; exit 75",
        vec![appr("r1")],
    ));
    v.push(case(
        "onay-kotu-kimlik".into(),
        &suspended("../x"),
        vec![appr("r1")],
    ));
    v.push(case(
        "onay-baska-kod".into(),
        "echo '{\"suspended\":{\"id\":\"a\"}}'; exit 74",
        vec![appr("r1")],
    ));
    v.push(
        Case::new(
            "onay-bayrak-yok",
            "g10_chat",
            json!({"now": NOW, "calls": [appr("r1")]}),
        )
        .file(ucli_script(r, "bin/ucli", "--state-dir", &ok)),
    );
    for (i, key) in ["BAD KEY", "../x", "r1\n", "1", "a/b"].iter().enumerate() {
        v.push(case(format!("onay-ad{i}"), &ok, vec![appr(key)]));
    }
    for (id, body) in [
        (
            "digerleri",
            r#"{"z": {"state": "suspended", "n": 1.5, "u": [null, "ğ"]}, "r1": {"state": "done"}, "a": 5}"#,
        ),
        ("bitmis", r#"{"r1": {"state": "expired", "owner": "eski"}}"#),
        ("bozuk", "{"),
        ("liste", "[1]"),
        ("canli", r#"{"r1": {"state": "suspended"}}"#),
        ("surdurulen", r#"{"r1": {"state": "resuming"}}"#),
        ("calisan", r#"{"r1": {"state": "running"}}"#),
        ("taninmayan", r#"{"r1": 5}"#),
        ("durumsuz", r#"{"r1": {}}"#),
    ] {
        v.push(
            case(format!("onay-defter-{id}"), &ok, vec![appr("r1")]).file(file(index, body, 0o600)),
        );
    }
    v.push(
        case("onay-defter-utf8".into(), &ok, vec![appr("r1")]).file(Fx::File(
            index.into(),
            b"{\xff}".to_vec(),
            0o640,
        )),
    );
    v.push(
        case("onay-defter-okunamaz".into(), &ok, vec![appr("r1")]).file(file(index, "{}", 0o000)),
    );
    v.push(
        case("onay-defter-dizin".into(), &ok, vec![appr("r1")]).file(Fx::Dir(index.into(), 0o700)),
    );
    v.push(
        case("onay-kok-dosya".into(), &ok, vec![appr("r1")]).file(file(
            "state/ucli_approval",
            "x",
            0o600,
        )),
    );
    v.push(
        case("onay-kosu-baglanti".into(), &ok, vec![appr("r1")])
            .file(Fx::Dir("home/baska".into(), 0o755))
            .file(Fx::Link(
                "state/ucli_approval/r1".into(),
                "../../home/baska".into(),
            )),
    );
    v.push(
        case("onay-kilit-baglanti".into(), &ok, vec![appr("r1")])
            .file(file("home/hedef", "x", 0o600))
            .file(Fx::Link(format!("{index}.lock"), "../../home/hedef".into())),
    );
    // koşu sürerken defter kullanılamaz hâle gelir: kayıt yazılamaz, günlüğe düşer, hata döner
    let breaks = format!("/bin/mkdir -p '{r}/state/ucli_approval/index.json'; {ok}");
    v.push(case(
        "onay-kayit-yazilamadi".into(),
        &breaks,
        vec![appr("r1")],
    ));
    let races = format!("echo '{{\"r1\":{{\"state\":\"suspended\"}}}}' > '{r}/state/ucli_approval/index.json'; {ok}");
    v.push(case("onay-yaris".into(), &races, vec![appr("r1")]));
    v
}

fn oneshot_cases(r: &str) -> Vec<Case> {
    let cwd = format!("{r}/work/notr/ic");
    let sh = |body: &str| json!(["/bin/sh", "-c", body]);
    let argv_case = |id: &str, argv: Value, cwd: &str, timeout: f64| {
        Case::new(
            format!("argv-{id}"),
            "g10_oneshot",
            json!({"calls": [{"cli": "claude", "prompt": "p", "cwd": cwd, "timeout": timeout, "argv": argv}]}),
        )
    };
    let mut v = Vec::new();
    for (id, body) in [
        ("basit", "read x; echo \"  [$x] ok  \"; pwd"),
        ("cikis", "echo cikti; echo ' hata ' >&2; exit 3"),
        ("cikis-stdout", "echo ' yalnız çıktı '; exit 4"),
        ("cikis-bosluk-stderr", "echo cikti; echo '   ' >&2; exit 4"),
        ("cikis-sessiz", "exit 5"),
        (
            "cikis-uzun",
            "i=0; while [ $i -lt 60 ]; do echo \"ş $i ğ\" >&2; i=$((i+1)); done; exit 6",
        ),
        ("sinyal", "kill -TERM $$"),
        ("bos", "true"),
        ("bosluk", "printf ' \\n\\t '"),
        ("crlf", "printf 'a\\r\\nb\\rc\\r\\n'"),
        ("utf8", "printf '\\377'"),
        ("utf8-stderr", "echo x; printf '\\377' >&2"),
    ] {
        v.push(argv_case(id, sh(body), &cwd, 10.0));
    }
    for (i, t) in [0.5, 1.5].iter().enumerate() {
        v.push(argv_case(
            &format!("zaman-asimi{i}"),
            sh("exec /bin/sleep 20"),
            &cwd,
            *t,
        ));
    }
    v.push(argv_case("yok", json!([format!("{r}/bin/yok")]), &cwd, 5.0));
    v.push(argv_case(
        "ad-yok",
        json!(["yok-boyle-bir-ikili"]),
        &cwd,
        5.0,
    ));
    v.push(argv_case("nul", sh("echo \0"), &cwd, 5.0));
    v.push(argv_case(
        "cwd-nul",
        sh("echo"),
        &format!("{r}/work/a\0"),
        5.0,
    ));
    v.push(
        argv_case("cwd-dosya", sh("echo x"), &format!("{r}/work/d"), 5.0)
            .file(file("work/d", "x", 0o600)),
    );
    v.push(
        argv_case(
            "cwd-dosya-alti",
            sh("echo x"),
            &format!("{r}/work/d/alt"),
            5.0,
        )
        .file(file("work/d", "x", 0o600)),
    );
    v.push(argv_case(
        "cwd-var",
        sh("pwd"),
        &format!("{r}/work/p1"),
        5.0,
    ));
    // gerçek `claude` yolu: argv sağlayıcıdan, ikili sahte
    let claude = |help: &str| {
        file(
            "bin/claude",
            &format!(
                "#!/bin/sh\nif [ \"$1\" = --help ]; then echo '{help}'; exit 0; fi\n\
             for a in \"$@\"; do printf '[%s]' \"$a\"; done"
            ),
            0o755,
        )
    };
    for (i, help) in ["--no-session-persistence  x", "--no-session  x", ""]
        .iter()
        .enumerate()
    {
        for (j, model) in [json!("m"), json!(""), Value::Null].iter().enumerate() {
            v.push(Case::new(format!("claude{i}-{j}"), "g10_oneshot", json!({"calls": [
                {"cli": "claude", "prompt": "özetle bunu", "model": model, "cwd": cwd, "timeout": 5.0}]}))
                .file(claude(help)));
        }
    }
    let unsupported = ["agy", "codex", "copilot"]
        .map(|c| json!({"cli": c, "prompt": "p", "cwd": cwd, "timeout": 5.0}));
    v.push(Case::new(
        "desteklemeyen",
        "g10_oneshot",
        json!({"calls": unsupported}),
    ));
    // ucli: anahtar kaynağı, uç nokta, cevap biçimi
    let key_rel = "home/.claude/claudeops/ucli_api_key";
    let ucli = |id: &str, body: &str, model: Value| {
        Case::new(
            format!("ucli-{id}"),
            "g10_oneshot",
            json!({"calls": [
            {"cli": "ucli", "prompt": "özetle", "model": model, "cwd": cwd, "timeout": 5.0}]}),
        )
        .file(ucli_script(r, "bin/ucli", HELP, body))
    };
    let m = || json!("m1");
    v.push(ucli("anahtarsiz", ANSWER, m()));
    v.push(ucli("model-bos", ANSWER, json!("")));
    v.push(ucli("model-yok", ANSWER, Value::Null));
    v.push(ucli("ortam-anahtari", ANSWER, m()).env("UCLI_API_KEY", "miras-anahtar"));
    v.push(ucli("ayar-anahtari", ANSWER, m())
        .settings_json(json!({"byok": {"ucli": {"UCLI_API_KEY": format!("  {KEY} ")}}, "ucli_endpoint": "http://yerel:1/v1/"}))
        .file(file(key_rel, "dosyadaki", 0o600)));
    v.push(
        ucli("ayar-bos", ANSWER, m())
            .settings_json(
                json!({"byok": {"ucli": {"UCLI_API_KEY": "  "}}, "ucli_endpoint": "bozuk"}),
            )
            .file(file(key_rel, " dosyadaki-anahtar \r\n", 0o600)),
    );
    v.push(
        ucli("dosya-bos", ANSWER, m())
            .file(file(key_rel, " \n", 0o600))
            .env("UCLI_API_KEY", "miras-anahtar"),
    );
    v.push(ucli("dosya-dizin", ANSWER, m()).file(Fx::Dir(key_rel.into(), 0o700)));
    v.push(ucli("dosya-izinsiz", ANSWER, m()).file(file(key_rel, "x", 0o000)));
    v.push(
        ucli("dosya-baglanti", ANSWER, m())
            .file(file("home/asil", KEY, 0o600))
            .file(Fx::Link(key_rel.into(), "../../asil".into())),
    );
    v.push(ucli("dosya-aygit", ANSWER, m()).file(Fx::Link(key_rel.into(), "/dev/null".into())));
    v.push(ucli("dosya-utf8", ANSWER, m()).file(Fx::File(
        key_rel.into(),
        b"sk-gizli\xff".to_vec(),
        0o600,
    )));
    v.push(ucli("dosya-nul", ANSWER, m()).file(Fx::File(
        key_rel.into(),
        b"sk\0gizli".to_vec(),
        0o600,
    )));
    for (id, body) in [
        ("cevap-yok", "echo '{}'"),
        ("cevap-bos", "echo '{\"answer\":\"  \"}'"),
        ("cevap-null", "echo '{\"answer\":null}'"),
        ("cevap-sifir", "echo '{\"answer\":0}'"),
        ("cevap-sayi", "echo '{\"answer\":2.5}'"),
        ("cevap-liste", "echo '{\"answer\":[\"a\",null]}'"),
        (
            "cevap-kirp",
            "echo '{\"answer\":\"  {\\\"goal\\\": 1}\\n \"}'",
        ),
        (
            "butce",
            "echo '{\"answer\":\"a\",\"budget_exhausted\":\"failures\"}'",
        ),
        ("hata", "echo '{\"error\":\"yok\"}'"),
        ("cikis", "echo patladı >&2; exit 1"),
        ("bozuk", "echo x"),
        ("askida", "echo '{\"suspended\":{\"id\":\"a\"}}'; exit 75"),
    ] {
        v.push(ucli(id, body, m()));
    }
    v.push(
        ucli("sir", "echo \"k=$UCLI_API_KEY\" >&2; exit 1", m()).file(file(key_rel, KEY, 0o600)),
    );
    let mut slow = ucli("zaman-asimi", "exec /bin/sleep 20", m());
    slow.args["calls"][0]["timeout"] = json!(0.5);
    v.push(slow);
    let mut blocked = ucli("cwd-dosya", ANSWER, m()).file(file("work/d", "x", 0o600));
    blocked.args["calls"][0]["cwd"] = json!(format!("{r}/work/d/alt"));
    v.push(blocked);
    v.push(
        Case::new(
            "ucli-ikili-yok",
            "g10_oneshot",
            json!({"calls": [
        {"cli": "ucli", "prompt": "p", "cwd": cwd, "timeout": 5.0}]}),
        )
        .file(Fx::Remove("bin/ucli".into())),
    );
    let mut flag = ucli("prompt-bayrak", ANSWER, m());
    flag.args["calls"][0]["prompt"] = json!("--allow-edit");
    v.push(flag);
    v
}

fn approval_cases() -> Vec<Case> {
    let reg = |k: &str| {
        json!([
            "register",
            k,
            "/w",
            "s1",
            ["/bin/ucli", "--root", "/w", "ğ \"x\""],
            "ali"
        ])
    };
    let flow = json!([
        ["slot", "r1"],
        ["dir_for", "r1", false],
        reg("r1"),
        ["slot", "r1"],
        reg("r1"),
        ["set_state", "r1", "suspended"],
        reg("r1"),
        ["set_state", "r1", "resuming"],
        ["slot", "r1"],
        ["set_state", "r1", "done"],
        ["slot", "r1"],
        reg("r1"),
        reg("r2"),
        ["set_state", "r1", "expired"],
        reg("r1"),
        ["set_state", "yok", "done"],
        ["set_state", "r1", "weird"],
        ["set_state", "BAD", "done"],
        reg("BAD"),
        ["dir_for", "", true],
        ["dir_for", "r3\n", true],
        ["dir_for", "r3", true],
        ["dir_for", "r3", true],
        ["slot", ""]
    ]);
    let c = |id: &str, steps: &Value| {
        Case::new(
            format!("kayit-{id}"),
            "g10_approval",
            json!({"now": NOW, "steps": steps}),
        )
    };
    let index = "state/ucli_approval/index.json";
    let mut v = vec![c("akis", &flow)];
    for (i, body) in [
        "",
        "{",
        "[]",
        "null",
        "5",
        "{}",
        r#"{"x": 1}"#,
        r#"{"r1": null}"#,
        r#"{"r1": "done"}"#,
        r#"{"r1": {"state": 5}}"#,
        r#"{"r1": {"state": "done"}, "k": {"a": [1, 2.5, "ğ", true, null, {}], "b": 1e300}}"#,
        "\u{feff}{}",
        r#"{"r2": {"state": "done"}, "r1": {"state": "expired"}}"#,
    ]
    .iter()
    .enumerate()
    {
        v.push(c(&format!("belge{i}"), &flow).file(file(index, body, 0o644)));
    }
    v.push(c("utf8", &flow).file(Fx::File(index.into(), b"\xff\xfe".to_vec(), 0o600)));
    v.push(c("derin", &flow).file(Fx::File(index.into(), vec![b'['; 100_000], 0o600)));
    v.push(c("okunamaz", &flow).file(file(index, "{}", 0o000)));
    v.push(c("dizin", &flow).file(Fx::Dir(index.into(), 0o755)));
    v.push(
        c("defter-baglanti", &flow)
            .file(file(
                "home/hedef",
                r#"{"r9": {"state": "suspended"}}"#,
                0o600,
            ))
            .file(Fx::Link(index.into(), "../../home/hedef".into())),
    );
    v.push(
        c("kopya-var", &flow)
            .file(file(index, "{", 0o600))
            .file(file(
                "state/ucli_approval/index.json.corrupt-021fb596db81",
                "eski kopya",
                0o600,
            )),
    );
    v.push(c("kok-dosya", &flow).file(file("state/ucli_approval", "x", 0o600)));
    v.push(
        c("kok-genis", &flow)
            .file(Fx::Dir("state/ucli_approval".into(), 0o755))
            .file(Fx::Dir("state/ucli_approval/r1".into(), 0o755))
            .file(Fx::Dir("state/ucli_approval/r1/pending".into(), 0o777)),
    );
    v.push(c("kok-salt-okunur", &flow).file(Fx::Dir("state/ucli_approval".into(), 0o500)));
    for (i, sub) in ["r1", "r1/pending", "r1/answers", "r3/suspended"]
        .iter()
        .enumerate()
    {
        let up = "../".repeat(sub.matches('/').count() + 2);
        v.push(
            c(&format!("baglanti{i}"), &flow)
                .file(Fx::Dir("home/baska".into(), 0o755))
                .file(Fx::Link(
                    format!("state/ucli_approval/{sub}"),
                    format!("{up}home/baska"),
                )),
        );
    }
    v.push(c("alt-dosya", &flow).file(file("state/ucli_approval/r1/answers", "x", 0o600)));
    v.push(c("kilit-dizin", &flow).file(Fx::Dir(format!("{index}.lock"), 0o700)));
    v
}

/// Onay kartları (`pending`) ve açılıştaki kurtarma (`recover_resuming`).
fn card_cases() -> Vec<Case> {
    const WEEK: f64 = 604800.0;
    let index = "state/ucli_approval/index.json";
    let run = "state/ucli_approval/r1";
    let card = |name: &str, body: &str| file(&format!("{run}/pending/{name}"), body, 0o600);
    let steps = json!([
        ["pending", "r1", null],
        ["pending", "r1", 0.0],
        ["recover", null, WEEK],
        ["pending", "r1", null],
        ["recover", NOW, WEEK],
        ["recover", NOW + 2.0 * WEEK, WEEK],
        ["pending", "BAD", null],
        ["pending", "yok", null]
    ]);
    let case = |id: String, index_body: &str| {
        Case::new(
            format!("kart-{id}"),
            "g10_approval",
            json!({"now": NOW, "steps": steps}),
        )
        .file(file(index, index_body, 0o600))
    };
    let record = |state: &str| format!(r#"{{"r1": {{"state": {state}, "created_at": {NOW}}}}}"#);
    let states = [
        r#""running""#,
        r#""suspended""#,
        r#""resuming""#,
        r#""done""#,
        r#""expired""#,
        "5",
        "null",
        r#"["suspended"]"#,
    ];
    let sets: [(&str, &[&str]); 6] = [
        ("yok", &[]),
        ("bekleyen", &["pending"]),
        ("surdurulmus", &["resumed"]),
        ("zincir", &["resumed", "pending"]),
        ("durumsuz", &["null", "resumed"]),
        ("tuhaf", &["[\"pending\"]", "5"]),
    ];
    let mut v = Vec::new();
    for (si, state) in states.iter().enumerate() {
        for (name, statuses) in sets {
            let mut c = case(format!("{si}-{name}"), &record(state));
            for (i, status) in statuses.iter().enumerate() {
                let status = if ["pending", "resumed"].contains(status) {
                    format!("\"{status}\"")
                } else {
                    status.to_string()
                };
                let body = format!(
                    r#"{{"id": "a{i}", "status": {status}, "kind": "edit", "expires_at": 9e12}}"#
                );
                c = c.file(card(&format!("a{i}.json"), &body));
            }
            v.push(c);
        }
        let consumed = case(format!("{si}-kullanilmis"), &record(state))
            .file(card("a.json", r#"{"id": "a", "status": "pending"}"#))
            .file(file(&format!("{run}/consumed"), "", 0o600));
        v.push(consumed);
        v.push(
            case(format!("{si}-kullanilmis-baglanti"), &record(state))
                .file(Fx::Link(format!("{run}/consumed"), "yok".into())),
        );
    }
    // alanların `str()` ve süre anlamı
    let values = [
        "null",
        "true",
        "false",
        "0",
        "5",
        "-1",
        "1.5",
        "0.0",
        "1e300",
        "1790000000",
        "1790000000.25",
        "1790000001",
        "99999999999999999999999",
        "-99999999999999999999999",
        r#""""#,
        r#""ğ 'x' \"y\"""#,
        "[]",
        r#"[1, "a", null, true, 2.5]"#,
        "{}",
        r#"{"k": ["ğ", {"n": 1}]}"#,
    ];
    for (i, value) in values.iter().enumerate() {
        let body = format!(
            r#"{{"id": "a", "status": "pending", "kind": {value}, "tool": {value}, "summary": {value}, "created_at": {value}, "expires_at": {value}, "fazla": 1}}"#
        );
        v.push(case(format!("alan{i}"), &record(r#""suspended""#)).file(card("a.json", &body)));
    }
    // `created_at` (kurtarmanın süre hesabı)
    for (i, created) in [
        "null",
        "true",
        "false",
        "0",
        "0.0",
        "5",
        "1790000000",
        "1e300",
        r#""""#,
        r#"" 12.5 ""#,
        r#""1_000""#,
        r#""inf""#,
        r#""abc""#,
        "[]",
        "[1]",
        "{}",
        r#"{"a": 1}"#,
    ]
    .iter()
    .enumerate()
    {
        let body = format!(
            r#"{{"once": {{"state": "resuming", "created_at": 1}}, "r1": {{"state": "suspended", "created_at": {created}, "x": 1}}}}"#
        );
        v.push(case(format!("yas{i}"), &body));
    }
    // okunmayan, bozuk ve tuhaf kartlar: yanlarında geçerli bir kart
    let good = r#"{"id": "z", "status": "resumed"}"#;
    let pend = r#"{"id": "b", "status": "pending"}"#;
    for (i, body) in [
        "",
        "{",
        "[]",
        "null",
        r#""pending""#,
        r#"{"status": "pending"}"#,
        r#"{"id": 5, "status": "pending"}"#,
        r#"{"id": "../x", "status": "pending"}"#,
        r#"{"id": "a\n", "status": "pending"}"#,
        "\u{feff}{\"id\": \"a\", \"status\": \"pending\"}",
        "{\r\n\"id\": \"a\",\r\"status\": \"pending\"}",
    ]
    .iter()
    .enumerate()
    {
        v.push(
            case(format!("bozuk{i}"), &record(r#""suspended""#))
                .file(card("a.json", body))
                .file(card("z.json", good)),
        );
    }
    let base = |id: &str| case(id.into(), &record(r#""resuming""#)).file(card("z.json", good));
    v.push(base("utf8").file(Fx::File(
        format!("{run}/pending/a.json"),
        b"\xff\xfe".to_vec(),
        0o600,
    )));
    v.push(base("derin").file(Fx::File(
        format!("{run}/pending/a.json"),
        vec![b'['; 100_000],
        0o600,
    )));
    v.push(base("okunamaz").file(file(&format!("{run}/pending/a.json"), pend, 0o000)));
    v.push(base("dizin-kart").file(Fx::Dir(format!("{run}/pending/a.json"), 0o700)));
    v.push(
        base("baska-uzanti")
            .file(card("a.JSON", pend))
            .file(card("b.json.tmp", pend)),
    );
    v.push(
        base("sira")
            .file(card("b.json", pend))
            .file(card("a.json", r#"{"id": "y", "status": "pending"}"#)),
    );
    v.push(base("gizli-ad").file(card(".json", pend)));
    v.push(
        base("kart-baglanti")
            .file(file("home/kart", pend, 0o600))
            .file(Fx::Link(
                format!("{run}/pending/a.json"),
                "../../../../home/kart".into(),
            )),
    );
    v.push(
        case("transkript".into(), &record(r#""suspended""#)).file(file(
            &format!("{run}/suspended/a.json"),
            pend,
            0o600,
        )),
    );
    v.push(
        case("pending-dosya".into(), &record(r#""resuming""#)).file(file(
            &format!("{run}/pending"),
            "x",
            0o600,
        )),
    );
    for (i, body) in [
        "{",
        "[]",
        "{}",
        r#"{"r1": null, "BAD": {"state": "resuming"}, "r2": {"state": "resuming"}}"#,
        r#"{"r1": {"state": "resuming", "result": 1, "finished_at": 2, "owner": "a"}}"#,
        r#"{"r1": {"state": "suspended", "created_at": "abc"}}"#,
    ]
    .iter()
    .enumerate()
    {
        v.push(case(format!("defter{i}"), body).file(card("z.json", good)));
    }
    v.push(base("kilit-dizin").file(Fx::Dir(format!("{index}.lock"), 0o700)));
    v
}

fn pure_cases() -> Vec<Case> {
    let mut rng = Rng(0x1010);
    const BITS: [&str; 24] = [
        "{",
        "}",
        "\"suspended\"",
        ":",
        "\"id\"",
        "\"ab-1\"",
        "\"../x\"",
        " ",
        "\n",
        "\r\n",
        "x",
        ",",
        "[",
        "]",
        "5",
        "null",
        "\"state\"",
        "\u{2028}",
        "\t",
        "NaN",
        "\"a\\n\"",
        "{\"suspended\":{\"id\":\"",
        "\"}}",
        "ğ",
    ];
    let mut suspended: Vec<String> = (0..1500)
        .map(|_| {
            (0..1 + rng.below(14))
                .map(|_| BITS[rng.below(BITS.len())])
                .collect()
        })
        .collect();
    suspended.extend(
        [
            "{\"suspended\":{\"id\":\"a\"}}",
            "  {\"suspended\":{\"id\":\"a\",\"id\":\"b\"}}  ",
            "{\"suspended\":null}",
            "{\"suspended\":{\"id\":\"a\"}}\u{85}{\"suspended\":{\"id\":\"b\"}}",
            "\u{a0}{\"suspended\":{\"id\":\"a\"}}",
            "{\"suspended\":{\"id\":\"a\"},\"x\":NaN}",
            "",
        ]
        .map(String::from),
    );
    const CHARS: [char; 14] = [
        'a', 'A', 'z', '0', '9', '_', '-', '.', '/', ' ', '\n', 'ğ', '١', '\0',
    ];
    let mut word = |max: usize| -> String {
        (0..rng.below(max))
            .map(|_| CHARS[rng.below(CHARS.len())])
            .collect()
    };
    let mut names: Vec<String> = (0..1500).map(|_| word(6)).collect();
    names.extend([63, 64, 65, 99, 100, 101].map(|n| "a".repeat(n)));
    let mut env_names: Vec<String> = (0..300).map(|_| format!("{}_API_KEY", word(4))).collect();
    env_names.extend(
        [
            "_API_KEY",
            "X_API_KEY\n",
            "X_API_KEY",
            "XAPI_KEY",
            "X_API_KEY_",
            "",
            "LD_PRELOAD",
            "İ_API_KEY",
        ]
        .map(String::from),
    );
    let budget = [
        "{}",
        "[1]",
        "5",
        "null",
        "\"x\"",
        r#"{"budget_exhausted": 0, "answer": "a"}"#,
        r#"{"budget_exhausted": false, "answer": "a"}"#,
        r#"{"budget_exhausted": [], "answer": "a"}"#,
        r#"{"budget_exhausted": "failures", "answer": "a"}"#,
        r#"{"budget_exhausted": "failures"}"#,
        r#"{"budget_exhausted": "failures", "answer": null}"#,
        r#"{"budget_exhausted": "failures", "answer": ""}"#,
        r#"{"budget_exhausted": "x", "answer": "[⚠ var]"}"#,
        r#"{"budget_exhausted": "x", "answer": " [⚠ var]"}"#,
        r#"{"budget_exhausted": true, "answer": "a"}"#,
        r#"{"budget_exhausted": 2.5, "answer": "a"}"#,
        r#"{"budget_exhausted": {"a": [null, "b'\""]}, "answer": "a", "z": 1}"#,
    ];
    let redact = json!([
        ["abc sk-12345678 x sk-12345678", "sk-12345678"],
        ["abc", null],
        ["abc", ""],
        ["1234567 x", "1234567"],
        ["12345678 x", " 12345678\n"],
        ["ğğğğğğğ y", "ğğğğğğğ"],
        ["ğğğğğğğğ y", "ğğğğğğğğ"],
        ["        ", "        "]
    ]);
    let mut argv = Vec::new();
    for _ in 0..200 {
        let mut opt = |vals: &[Value]| vals[rng.below(vals.len())].clone();
        let text = [Value::Null, json!(""), json!("v"), json!("a b")];
        argv.push(json!({"binary": "/b/ucli", "root": opt(&[json!("/w"), json!("")]), "repl": opt(&[json!(true), json!(false)]),
            "session": opt(&text), "model": opt(&text), "endpoint": opt(&text),
            "api_key_env": opt(&[json!(""), json!("K_API_KEY")]), "with_mcp": opt(&[json!(true), json!(false)]),
            "max_steps": opt(&[Value::Null, json!(0), json!(-1), json!(9)]),
            "extra_args": opt(&[json!([]), json!(["--a", ""])])}));
    }
    vec![Case::new(
        "saf",
        "g10_pure",
        json!({"suspended": suspended, "keys": names, "ids": names, "env_names": env_names,
        "budget": budget, "redact": redact, "argv": argv}),
    )]
}

fn opt<'a>(v: &'a Value, k: &str) -> Option<&'a str> {
    v.get(k).and_then(Value::as_str)
}

fn list(v: &Value) -> Vec<String> {
    v.as_array()
        .map(|a| a.iter().map(|x| x.as_str().unwrap().to_string()).collect())
        .unwrap_or_default()
}

fn jsonable(v: &Py) -> Value {
    match v {
        Py::Float(f) => fjson(*f),
        Py::Array(a) => a.iter().map(jsonable).collect(),
        Py::Object(o) => Value::Object(o.iter().map(|(k, v)| (k.clone(), jsonable(v))).collect()),
        other => other.to_value(),
    }
}

fn rs_pure(a: &Value) -> Value {
    let strings = |k: &str| list(&a[k]);
    let argv: Vec<Vec<String>> = a["argv"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| {
            let extra = list(&c["extra_args"]);
            oneshot::build_chat_argv(&ChatArgv {
                binary: c["binary"].as_str().unwrap(),
                root: c["root"].as_str().unwrap(),
                repl: c["repl"].as_bool().unwrap(),
                session: opt(c, "session"),
                model: opt(c, "model"),
                endpoint: opt(c, "endpoint"),
                api_key_env: c["api_key_env"].as_str().unwrap(),
                with_mcp: c["with_mcp"].as_bool().unwrap(),
                max_steps: c["max_steps"].as_i64(),
                extra_args: &extra,
            })
        })
        .collect();
    json!({
        "suspended": strings("suspended").iter()
            .map(|s| approval::parse_suspended(s).map_or(Value::Null, |id| json!({"id": id}))).collect::<Vec<_>>(),
        "run_key": strings("keys").iter().map(|s| approval::valid_run_key(s)).collect::<Vec<_>>(),
        "id": strings("ids").iter().map(|s| approval::valid_approval_id(s)).collect::<Vec<_>>(),
        "env_name": strings("env_names").iter().map(|s| oneshot::is_api_key_env_name(s)).collect::<Vec<_>>(),
        "budget": strings("budget").iter()
            .map(|s| jsonable(&oneshot::mark_budget_exhausted(Py::parse(s).unwrap()))).collect::<Vec<_>>(),
        "redact": a["redact"].as_array().unwrap().iter()
            .map(|p| oneshot::redact(p[0].as_str().unwrap(), p[1].as_str())).collect::<Vec<_>>(),
        "argv": argv,
    })
}

fn now_fixed() -> f64 {
    NOW
}

fn zero() -> f64 {
    0.0
}

fn rs_approval(store: &ApprovalStore, step: &Value) -> Value {
    let s = |i: usize| step[i].as_str().unwrap();
    let done = match s(0) {
        "register" => {
            let argv = list(&step[4]);
            let run = NewRun {
                cwd: s(2),
                session: s(3),
                argv_resume: &argv,
                owner: s(5),
            };
            store.register(s(1), run).map(Value::from)
        }
        "set_state" => store.set_state(s(1), s(2)).map(Value::from),
        "dir_for" => store
            .dir_for(s(1), step[2].as_bool().unwrap())
            .map(Value::from),
        "pending" => Ok(store
            .pending(s(1), step[2].as_f64())
            .iter()
            .map(jsonable)
            .collect()),
        "recover" => store
            .recover_resuming(step[1].as_f64(), step[2].as_f64().unwrap())
            .map(Value::from),
        _ => Ok(Value::from(store.slot_free(s(1)))),
    };
    match done {
        Ok(v) => json!(["ok", v]),
        Err(e) if e.class == "TypeError" => json!(["err", e.class, ""]),
        Err(e) => json!(["err", e.class, e.text]),
    }
}

fn rs_g10(e: &Env, c: &Case) -> RsOut {
    let a = &c.args;
    if c.op == "g10_pure" {
        return RsOut::ret(rs_pure(a));
    }
    let mut paths = e.paths();
    paths.repo_dir = format!("{}/yok", e.root); // depodaki gerçek `bin/ucli` hiçbir yoldan seçilemez
    let env = case_env(e, c);
    let probe = real_probe_at(e, c, paths.clone());
    let settings = e.settings();
    let catalog = e.catalog(c);
    let providers = Providers {
        settings: &settings,
        catalog: &catalog,
        paths: &paths,
        probe: &probe,
    };
    let clock = if a["now"].as_f64() == Some(NOW) {
        now_fixed
    } else {
        zero
    };
    let diag = DiagLog::from_env(&paths, &env);
    let approvals = ApprovalStore::new(&paths)
        .with_clock(clock)
        .with_diag(std::sync::Arc::new(diag.clone()));
    let shot = OneShot {
        providers: &providers,
        env: &env,
        approvals: &approvals,
        diag: &diag,
    };
    let out: Vec<Value> = match c.op {
        "g10_approval" => a["steps"]
            .as_array()
            .unwrap()
            .iter()
            .map(|s| rs_approval(&approvals, s))
            .collect(),
        "g10_chat" => a["calls"]
            .as_array()
            .unwrap()
            .iter()
            .map(|call| {
                let kw = &call["kw"];
                let extra = list(&kw["extra_args"]);
                let mut req = ChatRequest::new(
                    call["root"].as_str().unwrap(),
                    call["prompt"].as_str().unwrap(),
                );
                req.session = opt(kw, "session");
                req.model = opt(kw, "model");
                req.endpoint = opt(kw, "endpoint");
                req.api_key_env = opt(kw, "api_key_env").unwrap_or(req.api_key_env);
                req.api_key = opt(kw, "api_key").map(ApiKey::new);
                req.with_mcp = kw["with_mcp"].as_bool().unwrap_or(false);
                req.max_steps = kw["max_steps"].as_i64();
                req.binary = opt(kw, "binary");
                req.timeout = kw["timeout"].as_f64().unwrap_or(req.timeout);
                req.extra_args = &extra;
                req.approval_run_key = opt(kw, "approval_run_key");
                req.approval_owner = opt(kw, "approval_owner").unwrap_or("");
                match shot.chat_once(&req) {
                    Ok(v) => json!(["ok", jsonable(&v)]),
                    Err(err) => json!(["err", err.0]),
                }
            })
            .collect(),
        "g10_oneshot" => a["calls"]
            .as_array()
            .unwrap()
            .iter()
            .map(|call| {
                let s = |k: &str| call[k].as_str().unwrap();
                let timeout = call["timeout"].as_f64().unwrap();
                let done = match call.get("argv").filter(|v| !v.is_null()) {
                    Some(argv) => shot
                        .run_argv(s("cli"), &list(argv), s("cwd"), timeout)
                        .map(Some),
                    None => shot.oneshot(
                        Cli::parse(s("cli")),
                        s("prompt"),
                        opt(call, "model"),
                        s("cwd"),
                        timeout,
                    ),
                };
                match done {
                    Ok(v) => json!(["ok", v]),
                    Err(err) => json!(["err", err.0]),
                }
            })
            .collect(),
        other => panic!("bilinmeyen işlem {other}"),
    };
    let log = diag.path();
    crate::fam_g8::fix_ts(log);
    RsOut::ret(Value::from(out))
}

pub fn run() {
    let mut r = Runner::new();
    let root = r.e.root.clone();
    let mut cases = pure_cases();
    cases.extend(approval_cases());
    cases.extend(card_cases());
    cases.extend(chat_cases(&root));
    cases.extend(oneshot_cases(&root));
    r.run(cases, &[], rs_g10);
    r.finish("g10");
}
