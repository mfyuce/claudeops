//! Aile (G8 ikinci parça): `searxng.ensure_search_url`. Docker YOK: iki taraf da vaka ağacındaki sahte `docker`
//! kabuk betiğini gerçekten çalıştırır (çağrılar dosyaya yazılır); sağlık yoklaması ve ayrık kurulum süreci sahte.
//! Ek vaka: koşucunun ağ engeli hâlâ tutuyor.

use crate::common::*;
use cops_providers::real::diaglog::DiagLog;
use cops_providers::real::probe::SearchUrl;
use cops_providers::real::searxng::{ManagedSearch, Provision};
use serde_json::{json, Value};
use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::Duration;

const NOW: f64 = 1_790_000_000.5;

fn docker(root: &str) -> Fx {
    let w = format!("{root}/work");
    file(
        "bin/docker",
        &format!(
            "#!/bin/sh\necho \"$@\" >> {w}/docker.log\nif [ \"$1\" = start ]; then\n  [ -f {w}/start.err ] && /bin/cat \
             {w}/start.err >&2\n  [ -f {w}/start.rc ] && exit \"$(/bin/cat {w}/start.rc)\"\n  exit 0\nfi\n[ -f \
             {w}/out ] && /bin/cat {w}/out\n[ -f {w}/err ] && /bin/cat {w}/err >&2\n[ -f {w}/rc ] && exit \
             \"$(/bin/cat {w}/rc)\"\nexit 0\n"
        ),
        0o755,
    )
}

fn inspect(ours: bool, running: bool, status: &str, port: Value) -> String {
    let label = if ours { "searxng" } else { "baska" };
    json!([{"Config": {"Labels": {"claudeops.managed": label}}, "State": {"Running": running, "Status": status},
            "HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]}}}])
    .to_string()
}

fn cases(root: &str) -> Vec<Case> {
    let mut v = Vec::new();
    let mut add = |id: &str, health: &[bool], calls: &[(&str, bool)], files: Vec<Fx>| {
        let mut c = Case::new(format!("arama-{id}"), "g8x_searxng", json!({"health": health, "calls": calls, "now": NOW}));
        c.files = files;
        v.push(c);
    };
    let one: &[(&str, bool)] = &[("s1", false)];
    let two: &[(&str, bool)] = &[("s1", false), ("s2", false)];
    let state = |body: &str| file("state/searxng/state.json", body, 0o600);
    let out = |body: &str| file("work/out", body, 0o600);
    let err = |body: &str| file("work/err", body, 0o600);
    let rc = |n: &str| file("work/rc", n, 0o600);
    let d = || docker(root);

    for (i, port) in ["8891", "\"8891\"", "\" 8_891 \"", "8891.9", "true", "0", "-1", "65535", "65536", "\"x\"", "null", "[]",
        "NaN", "Infinity", "1e300"]
    .iter()
    .enumerate()
    {
        let body = format!("{{\"port\": {port}, \"image_id\": \"sha\"}}");
        add(&format!("kayitli{i}"), &[true], one, vec![state(&body)]);
        add(&format!("kayitli-kuru{i}"), &[false], &[("s1", true)], vec![state(&body), d()]);
    }
    for (i, body) in ["", "{", "[]", "5", "{\"port\": 8891"].iter().enumerate() {
        add(&format!("durum-bozuk{i}"), &[], one, vec![state(body), d(), err("Error: No such object: x"), rc("1")]);
    }
    add("docker-yok", &[], two, vec![]);
    add("yok", &[], two, vec![d(), err("Error: No such container: x\n"), rc("1")]);
    add("yok-stdout", &[], one, vec![d(), out("[]\nError: no SUCH object\n"), rc("1")]);
    add("hata", &[], two, vec![d(), err("satir1\n  permission denied while trying to connect  \n\n"), rc("1")]);
    add("hata-sessiz", &[], one, vec![d(), rc("3")]);
    add("hata-uzun", &[], one, vec![d(), err(&"ğ".repeat(600)), rc("1")]);
    for (i, body) in ["", "x", "[]", "{}", "[1]", "[{\"Config\": 5}]", "[{\"State\": \"x\"}]",
        "[{\"HostConfig\": {\"PortBindings\": {\"8080/tcp\": 5}}}]"]
    .iter()
    .enumerate()
    {
        add(&format!("bozuk{i}"), &[], one, vec![d(), out(body)]);
    }
    add("bos-alanlar", &[], one, vec![d(), out("[{\"Config\": null, \"State\": {}, \"HostConfig\": {\"PortBindings\": {}}}]")]);
    add("baskasi", &[], two, vec![d(), out(&inspect(false, true, "running", json!("8890")))]);
    add("calisan", &[true], one, vec![d(), out(&inspect(true, true, "running", json!("8890")))]);
    add("calisan-kayitli", &[false, true], one,
        vec![d(), out(&inspect(true, true, "running", json!("8890"))), state("{\"port\": 8888, \"image_id\": \"ğ\"}")]);
    add("hazir-degil", &[], one, vec![d(), out(&inspect(true, true, "running", json!("8890")))]);
    for status in ["restarting", "dead", "exited"] {
        add(&format!("durum-{status}"), &[], one, vec![d(), out(&inspect(true, true, status, json!("8890")))]);
    }
    add("kapisiz", &[], one, vec![d(), out(&inspect(true, true, "running", json!("")))]);
    add("duran", &[true], one, vec![d(), out(&inspect(true, false, "exited", json!("8890")))]);
    add("duran-baslamaz", &[], one, vec![
        d(), out(&inspect(true, false, "exited", json!("8890"))), file("work/start.rc", "1", 0o600),
        file("work/start.err", "Error: port is already allocated\n", 0o600),
    ]);
    add("kuru", &[], &[("s1", true)], vec![d(), out(&inspect(true, false, "exited", json!("8890")))]);
    // ayrık kurulum: bekleme ve pencere
    let missing = || vec![d(), err("No such object"), rc("1")];
    for (id, key, ago) in [
        ("sogutma", "provision_failed_at", 10.0), ("sogutma-bitti", "provision_failed_at", 600.0),
        ("sogutma-gelecek", "provision_failed_at", -5.0), ("pencere", "provision_started_at", 19.0),
        ("pencere-bitti", "provision_started_at", 20.0),
    ] {
        let mut files = missing();
        files.push(state(&format!("{{\"{key}\": {}, \"baska\": [1]}}", NOW - ago)));
        add(id, &[], one, files);
    }
    for (i, value) in ["true", "\"1\"", "null", "NaN"].iter().enumerate() {
        let mut files = missing();
        files.push(state(&format!("{{\"provision_failed_at\": {value}}}")));
        add(&format!("sogutma-tip{i}"), &[], one, files);
    }
    let mut files = missing();
    files.push(file("state/searxng", "x", 0o600));
    add("durum-dizini-dosya", &[], one, files);
    v.push(Case::new("ag-engeli", "g8x_netguard", json!({})));
    v
}

fn rs_searxng(e: &Env, c: &Case) -> RsOut {
    if c.op == "g8x_netguard" {
        let names = ["searxng", "servis", "saglayici", "urlopen", "soket", "ad"];
        return RsOut::ret(json!(names.map(|n| [n, "engelli"])));
    }
    let a = &c.args;
    let env = case_env(e, c);
    // günlük karşılaştırılan ağacın dışında tutulur
    let log_dir = tempfile::tempdir().unwrap();
    let log = log_dir.path().join("diag.log").to_string_lossy().into_owned();
    let health: Arc<Mutex<VecDeque<bool>>> =
        Arc::new(Mutex::new(a["health"].as_array().unwrap().iter().map(|b| b.as_bool().unwrap()).collect()));
    let provision = Provision { argv: vec!["/bin/true".into()], cwd: e.root.clone() };
    let search = ManagedSearch::new(&e.home, &e.state, env, DiagLog::new(log.clone()), provision)
        .with_health(move |_| health.lock().unwrap().pop_front().unwrap_or(false))
        .with_clock(Arc::new(|| NOW))
        .with_ready_wait(Duration::ZERO);
    let urls: Vec<Option<String>> = a["calls"]
        .as_array()
        .unwrap()
        .iter()
        .map(|call| search.search_url(call[0].as_str().unwrap(), call[1].as_bool().unwrap()))
        .collect();
    let diags: Vec<Value> = std::fs::read_to_string(&log)
        .unwrap_or_default()
        .lines()
        .map(|line| {
            let entry = cops_providers::ojson::OValue::parse(line).unwrap();
            let fields = entry.entries().unwrap();
            let event = fields.iter().find(|(k, _)| k == "event").unwrap().1.to_value();
            let rest: Vec<Value> = fields
                .iter()
                .filter(|(k, _)| k != "ts" && k != "event")
                .map(|(k, v)| json!([k, v.to_value()]))
                .collect();
            json!([event, rest])
        })
        .collect();
    RsOut::ret(json!({"urls": urls, "diags": diags, "name": search.container()}))
}

pub fn run() {
    let mut r = Runner::new();
    let all = cases(&r.e.root);
    r.run(all, &[], rs_searxng);
    r.finish("searxng");
}
