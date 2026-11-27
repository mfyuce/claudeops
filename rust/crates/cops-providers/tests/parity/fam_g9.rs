//! Aile G9: `spawn.spawn_session` yürütme akışı (devam çözümü, eklenti MCP'si, kanca, hayalet temizliği, gnome-terminal /
//! penceresiz tmux, bekçi), `open_window`, `open_mirror_window`, `_reclaim_ghost_session`, `routing.sync_global_files`,
//! `paths.REPO_DIR`.
//!
//! tmux, gnome-terminal (`Popen`), saat, süreç taraması ve devam çözümü iki tarafta aynı vaka olgularıyla SAHTE; çağrılar
//! aynı biçimde bir günlüğe yazılır (`calls`) ve sırasıyla karşılaştırılır. Kanca ve eklenti MCP'si iki tarafta GERÇEK kod
//! (`authz.spawn_env` + `extensions.session_mcp_spec` / [`cops_providers::hooks::Hooks`]); kayıtları vakadan. Bekçi
//! Python'da eşzamanlı (sahte `Thread.start`), Rust'ta gerçek iş parçacığı: karşılaştırmadan önce join edilir.
//! Başlatma payı geri verme (`release`) yalnız Rust'ta: her vakada ayrıca denetlenir (kuru ya da hatalı başlatmada bir kez).

use crate::common::*;
use crate::fam_build::spec_of;
use crate::fam_model::with;
use crate::fam_spawn::{pairs, parent_env};
use crate::fam_ucli::full_help;
use cops_providers::hooks::{HookFailure, Hooks, SessionMcpEntry, SpawnRefused};
use cops_providers::real::launch::repo_dir_of;
use cops_providers::real::routing_sync::sync_global_files_at;
use cops_providers::spawn_exec::{
    open_mirror_window, open_window, reclaim_ghost_session, spawn_session, Clock, CostRelease, LaunchError, Launcher,
    ResumeResolver, SessionScan, SpawnDeps, SpawnFailure, SpawnTmux, StartRequest, Terminal,
};
use cops_providers::Cli;
use serde_json::{json, Value};
use std::collections::{BTreeSet, VecDeque};
use std::path::Path;
use std::sync::{Arc, Mutex};

struct St {
    calls: Vec<Value>,
    has: VecDeque<bool>,
    popen: VecDeque<String>,
    t: f64,
    released: Vec<String>,
}

/// Python `_G9` sahtelerinin karşılığı (tek nesne, tüm sınırlar).
struct Fake {
    facts: Value,
    st: Mutex<St>,
}

impl Fake {
    fn new(c: &Case) -> Arc<Fake> {
        let has = c.facts.get("has_session").and_then(Value::as_array).map(|a| a.iter().map(truthy).collect());
        let popen = c.facts.get("popen").and_then(Value::as_array).map(|a| a.iter().map(|x| x.as_str().unwrap().to_string()).collect());
        Arc::new(Fake {
            facts: c.facts.clone(),
            st: Mutex::new(St { calls: Vec::new(), has: has.unwrap_or_default(), popen: popen.unwrap_or_default(), t: 100.0, released: Vec::new() }),
        })
    }
    fn call(&self, v: Value) {
        self.st.lock().unwrap().calls.push(v);
    }
    /// `bool(f.get(k, default))`.
    fn flag(&self, k: &str, default: bool) -> bool {
        self.facts.get(k).map_or(default, truthy)
    }
}

fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

impl SpawnTmux for Fake {
    fn available(&self) -> bool {
        self.call(json!(["tmux_available"]));
        self.flag("tmux", true)
    }
    fn new_session_fragment(&self, name: &str, cwd: &str, inner: &str) -> Result<String, String> {
        self.call(json!(["frag", name, cwd, inner]));
        Ok(format!("TMUXFRAG<{name}|{cwd}|{inner}>"))
    }
    fn attach_fragment(&self, name: &str) -> Result<String, String> {
        self.call(json!(["attach", name]));
        Ok(format!("TMUXATTACH<{name}>"))
    }
    fn spawn_direct(&self, name: &str, cwd: &str, inner: &str, env: &[(String, String)]) -> bool {
        self.call(json!(["direct", name, cwd, inner, pairs(env)]));
        self.flag("direct_ok", true)
    }
    fn has_session(&self, name: &str) -> bool {
        let mut st = self.st.lock().unwrap();
        st.calls.push(json!(["has", name]));
        st.has.pop_front().unwrap_or_else(|| self.flag("has_default", true))
    }
    fn ghost_session(&self, name: &str) -> bool {
        self.call(json!(["ghost", name]));
        self.flag("ghost", false)
    }
    fn capture(&self, name: &str, lines: u32) -> Option<String> {
        self.call(json!(["capture", name, lines]));
        self.facts.get("capture").and_then(Value::as_str).map(String::from)
    }
    fn kill_session(&self, name: &str) {
        self.call(json!(["kill", name]));
    }
}

impl Terminal for Fake {
    fn available(&self) -> bool {
        self.call(json!(["gt_available"]));
        self.flag("gt", true)
    }
    fn path_exists(&self, path: &str) -> bool {
        Path::new(path).exists()
    }
    fn launch(&self, argv: &[String], env: &[(String, String)]) -> Result<bool, LaunchError> {
        let mut st = self.st.lock().unwrap();
        st.calls.push(json!(["launch", argv, pairs(env)]));
        match st.popen.pop_front().as_deref().unwrap_or("ok") {
            "oserror" => Ok(false),
            "value" => Err(LaunchError::Value("embedded null byte".into())),
            _ => Ok(true),
        }
    }
}

impl Clock for Fake {
    fn monotonic(&self) -> f64 {
        self.st.lock().unwrap().t
    }
    fn sleep(&self, secs: f64) {
        let mut st = self.st.lock().unwrap();
        st.calls.push(json!(["sleep", secs]));
        st.t += secs;
    }
}

impl SessionScan for Fake {
    fn live_sessions(&self) -> Option<Vec<(String, Option<String>)>> {
        match self.facts.get("live") {
            Some(Value::String(s)) if s == "raise" => None,
            Some(Value::Array(rows)) => Some(
                rows.iter().map(|r| (r[0].as_str().unwrap().to_string(), r[1].as_str().map(String::from))).collect(),
            ),
            _ => Some(Vec::new()),
        }
    }
}

impl ResumeResolver for Fake {
    fn resolve_resume_id(&self, _cli: Cli, cwd: &str, in_use: &BTreeSet<String>, session_name: &str) -> Option<String> {
        self.call(json!(["resolve", cwd, in_use, session_name]));
        self.facts.get("resume").and_then(Value::as_str).map(String::from)
    }
}

impl CostRelease for Fake {
    fn release(&self, session: &str) {
        self.st.lock().unwrap().released.push(session.into());
    }
}

/// Vakanın kanca ve eklenti kayıtları (Python `authz.set_spawn_hook`, `extensions._SESSION_MCP`/`_MCP`).
fn hooks(fake: &Arc<Fake>, c: &Case, repo: &str) -> Hooks {
    let spawn_hook = c.fact("hook").cloned().map(|hook| {
        let f = Arc::clone(fake);
        let b: Box<cops_providers::hooks::SpawnHookFn> = Box::new(move |cli: &str, name: &str, cwd: &str| {
            f.call(json!(["hook", cli, name, cwd]));
            if let Some(r) = hook.get("refuse").and_then(Value::as_array) {
                let s = |i: usize| r.get(i).and_then(Value::as_str).unwrap_or("").to_string();
                return Err(HookFailure::Refused(SpawnRefused { reason: s(0), detail: s(1) }));
            }
            if let Some(m) = hook.get("raise").and_then(Value::as_str) {
                return Err(HookFailure::Error { class: "RuntimeError".into(), message: m.into() });
            }
            Ok(hook
                .get("env")
                .and_then(Value::as_array)
                .map(|a| a.iter().map(|p| (p[0].as_str().unwrap().into(), p[1].as_str().unwrap().into())).collect())
                .unwrap_or_default())
        });
        b
    });
    let session_mcp = c
        .fact("ext")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(|e| {
            let f = Arc::clone(fake);
            let sid = e["sid"].as_str().unwrap().to_string();
            let want = e["cwd"].as_str().unwrap().to_string();
            let sid2 = sid.clone();
            let tools = match e.get("tools") {
                Some(Value::String(s)) if s == "bozuk" => Some(Err("KeyError: 'name'".to_string())),
                Some(Value::Array(t)) => Some(Ok(t.iter().map(|x| x.as_str().unwrap().to_string()).collect())),
                _ => None,
            };
            SessionMcpEntry {
                server_id: sid,
                matches: Box::new(move |cwd: &str| {
                    f.call(json!(["pred", sid2, cwd]));
                    if want == "raise" {
                        return Err("koşul".into());
                    }
                    Ok(want == "*" || want == cwd)
                }),
                tools,
            }
        })
        .collect();
    Hooks { spawn_hook, session_mcp, repo_dir: repo.into() }
}

fn launcher(fake: &Arc<Fake>, sink: &Arc<VecSink>, e: &Env, c: &Case) -> Launcher {
    Launcher {
        tmux: fake.clone(),
        terminal: fake.clone(),
        clock: fake.clone(),
        diag: sink.clone(),
        parent_env: parent_env(e, c),
    }
}

fn failure(f: &SpawnFailure) -> Value {
    match f {
        SpawnFailure::Refused { error, .. } => json!(["refused", error.0]),
        SpawnFailure::Error { class, message } => json!([class, message]),
    }
}

fn finish(fake: &Fake, sink: &VecSink, r: Result<Value, SpawnFailure>) -> RsOut {
    let calls = std::mem::take(&mut fake.st.lock().unwrap().calls);
    let mut rs = RsOut::ret(match r {
        Ok(v) => json!({"ret": v, "calls": calls}),
        Err(f) => json!({"exc": failure(&f), "calls": calls}),
    });
    rs.extra_diags = sink.take();
    rs
}

fn rs_g9(e: &Env, c: &Case) -> RsOut {
    let a = &c.args;
    let s = |k: &str| a.get(k).and_then(Value::as_str).map(String::from);
    let fake = Fake::new(c);
    let sink = Arc::new(VecSink::default());
    let l = launcher(&fake, &sink, e, c);
    match c.op {
        "g9_spawn" => with(e, c, |p, probe| {
            let mut req = StartRequest::new(s("name").unwrap(), s("cwd").unwrap(), s("model").unwrap_or("m".into()));
            req.display = s("display");
            req.permission_mode = s("perm").unwrap_or("auto".into());
            req.effort = s("effort").unwrap_or("max".into());
            req.force_new = a.get("force_new").is_some_and(truthy);
            req.prompt = s("prompt");
            req.dry_run = a.get("dry_run").is_some_and(truthy);
            req.cli = s("cli").unwrap_or("claude".into());
            req.mcp_server = a.get("mcp").filter(|v| truthy(v)).map(spec_of);
            req.hidden = a.get("hidden").is_some_and(truthy);
            req.cli_opts = a.get("cli_opts").and_then(Value::as_object).cloned();
            let h = hooks(&fake, c, &e.repo);
            let deps = SpawnDeps { providers: p, resume: &*fake, scan: &*fake, hooks: &h, cost: &*fake };
            let r = spawn_session(&deps, &l, &req).map(|started| {
                if let Some(w) = started.watchdog {
                    w.join();
                }
                json!(started.kind)
            });
            let released = std::mem::take(&mut fake.st.lock().unwrap().released);
            let want: Vec<String> = if req.dry_run || r.is_err() { vec![req.name.clone()] } else { Vec::new() };
            assert_eq!(released, want, "[{}] release", c.id);
            let mut rs = finish(&fake, &sink, r);
            rs.mcp_calls = probe.mcp_calls.borrow().clone();
            rs
        }),
        "g9_window" => {
            let r = open_window(&l, &s("name").unwrap(), &s("cwd").unwrap(), s("display").as_deref()).map(|b| json!(b));
            finish(&fake, &sink, r)
        }
        "g9_mirror" => {
            let port = a["port"].as_u64().unwrap() as u16;
            let r = open_mirror_window(&l, &e.paths(), &s("host").unwrap(), &s("name").unwrap(), port, s("display").as_deref())
                .map(|b| json!(b));
            finish(&fake, &sink, r)
        }
        "g9_reclaim" => {
            reclaim_ghost_session(&l, &s("name").unwrap(), &s("cli").unwrap());
            finish(&fake, &sink, Ok(Value::Null))
        }
        "g9_sync" => with(e, c, |p, probe| {
            let out = sync_global_files_at(probe, p.settings, p.paths, &s("codex").unwrap(), &s("agy").unwrap(), &*sink);
            let mut rs = RsOut::ret(json!({out[0].0: out[0].1, out[1].0: out[1].1}));
            rs.extra_diags = sink.take();
            rs
        }),
        "g9_repo_dir" => RsOut::ret(json!(repo_dir_of(Path::new(&format!("{}/py/claudeops/paths.py", e.repo))))),
        op => panic!("bilinmeyen işlem {op}"),
    }
}

fn spawn_cases(e: &Env) -> Vec<Case> {
    let w = format!("{}/p1", e.work);
    let base = |id: String, cli: &str, extra: Value| {
        let mut a = json!({"cli": cli, "name": "s1", "cwd": w, "model": "m", "perm": "auto", "effort": "high", "display": ":5"});
        a.as_object_mut().unwrap().extend(extra.as_object().unwrap().clone());
        Case::new(id, "g9_spawn", a).facts(json!({"ucli_help": full_help()}))
    };
    let mut v = Vec::new();
    let ext = json!([{"sid": "notes", "cwd": "*", "tools": ["t1", "t2"]}]);
    for cli in ["claude", "agy", "codex", "copilot", "shell", "ucli", "bogus"] {
        v.push(base(format!("{cli}-gt"), cli, json!({})));
        v.push(base(format!("{cli}-gizli"), cli, json!({"hidden": true})));
        v.push(base(format!("{cli}-gizli-tmuxsuz"), cli, json!({"hidden": true})).facts(json!({"tmux": false})));
        v.push(base(format!("{cli}-gtsiz"), cli, json!({})).facts(json!({"gt": false})));
        v.push(base(format!("{cli}-gtsiz-tmuxsuz"), cli, json!({})).facts(json!({"gt": false, "tmux": false})));
        v.push(base(format!("{cli}-tmuxsuz"), cli, json!({})).facts(json!({"tmux": false})));
        v.push(base(format!("{cli}-kuru"), cli, json!({"dry_run": true})).facts(json!({"ext": ext, "hook": {"env": [["A_B", "1"]]}})));
        v.push(base(format!("{cli}-hayalet"), cli, json!({}))
            .facts(json!({"ghost": true, "capture": "\u{1b}[31mOut of credits\u{1b}[0m\n\n  \nson satır\n"})));
        v.push(base(format!("{cli}-devam"), cli, json!({}))
            .facts(json!({"resume": "abcdef1234567890", "live": [["s1", "kendi"], ["s2", "baskasi"], ["s3", null], ["", "bos-ad"]]})));
        v.push(base(format!("{cli}-yeni-zorla"), cli, json!({"force_new": true})).facts(json!({"resume": "abcdef1234567890"})));
        v.push(base(format!("{cli}-eklenti"), cli, json!({})).facts(json!({"ext": ext})));
        v.push(base(format!("{cli}-kanca"), cli, json!({"hidden": true}))
            .facts(json!({"hook": {"env": [["PROVIDER_DIR", "/p d"], ["COPS_NAME", "ezilir"], ["PROVIDER_DIR", "/son"], ["lower", "x"]]}})));
        v.push(base(format!("{cli}-kanca-red"), cli, json!({})).facts(json!({"hook": {"refuse": ["no_login", "ayrıntı"]}})));
    }
    // Ekran: açık değer yoksa ortamdan (X soketi yoklaması sistemin /tmp'sine bakar, iki tarafta aynı).
    v.push(base("ekran-ortam".into(), "claude", json!({"display": null})).env("DISPLAY", ":9"));
    v.push(base("ekran-bos-ortam".into(), "claude", json!({"display": null})).env("DISPLAY", ""));
    v.push(base("ekran-yok".into(), "claude", json!({"display": null})));
    v.push(base("ortam-supurme".into(), "claude", json!({"hidden": true}))
        .env("DISPLAY", ":2").env("CLAUDE_CODE_X", "1").env("GEMINI_K", "g").env("ANTIGRAVITY_Y", "a").env("XCLAUDE", "kalir"));
    // Bekçi: ilk deneme tutmaz, sonraki tutar / hiç tutmaz / yeniden deneme başlatılamaz / Popen ValueError.
    let f = |n: usize| json!(vec![false; n]);
    let then_true = |n: usize| {
        let mut x = vec![false; n];
        x.push(true);
        json!(x)
    };
    v.push(base("bekci-hemen".into(), "claude", json!({})).facts(json!({"has_session": [true]})));
    v.push(base("bekci-ikinci".into(), "claude", json!({})).facts(json!({"has_session": then_true(8)})));
    v.push(base("bekci-ucuncu-gec".into(), "claude", json!({})).facts(json!({"has_session": then_true(19)})));
    v.push(base("bekci-hic".into(), "claude", json!({})).facts(json!({"has_default": false})));
    v.push(base("bekci-hic-direkt-dustu".into(), "claude", json!({})).facts(json!({"has_default": false, "direct_ok": false})));
    v.push(base("bekci-son-yoklama".into(), "claude", json!({})).facts(json!({"has_session": f(24), "has_default": true})));
    v.push(base("bekci-baslatilamadi".into(), "claude", json!({})).facts(json!({"has_default": false, "popen": ["ok", "oserror", "ok"]})));
    v.push(base("bekci-valueerror".into(), "claude", json!({})).facts(json!({"has_default": false, "popen": ["ok", "value"]})));
    v.push(base("ilk-oserror".into(), "claude", json!({})).facts(json!({"popen": ["oserror"]})));
    v.push(base("ilk-oserror-tmuxsuz".into(), "claude", json!({})).facts(json!({"popen": ["oserror"], "tmux": false})));
    v.push(base("ilk-valueerror".into(), "claude", json!({})).facts(json!({"popen": ["value"], "ghost": true})));
    // Kanca: hata (kapalı yön + günlük), ayrıntısız ret, kuru kipte ret, uzun hata metni.
    v.push(base("kanca-hata".into(), "claude", json!({})).facts(json!({"hook": {"raise": "patladı"}})));
    v.push(base("kanca-hata-uzun".into(), "ucli", json!({})).facts(json!({"hook": {"raise": "ğ".repeat(300)}})));
    v.push(base("kanca-red-yalin".into(), "codex", json!({})).facts(json!({"hook": {"refuse": ["quota"]}})));
    v.push(base("kanca-red-kuru".into(), "claude", json!({"dry_run": true})).facts(json!({"hook": {"refuse": ["x", "y"]}})));
    v.push(base("kanca-ucli-tavan".into(), "ucli", json!({"hidden": true, "cli_opts": {"max_session_usd": 50}}))
        .facts(json!({"hook": {"env": [["CLAUDEOPS_SESSION_USD_CAP", "12"]]}})));
    // Eklenti MCP'si: eşleşmeyen, hata veren, araç listesi bozuk, kayıtsız sunucu, açık `mcp_server`.
    let p1 = w.clone();
    let exts = [
        json!([{"sid": "a", "cwd": "/baska"}, {"sid": "b", "cwd": p1, "tools": ["x"]}]),
        json!([{"sid": "a", "cwd": "raise"}, {"sid": "b", "cwd": "*"}]),
        json!([{"sid": "a", "cwd": "*", "tools": "bozuk"}, {"sid": "b", "cwd": "*", "tools": []}]),
        json!([{"sid": "a", "cwd": "/yok"}]),
        json!([]),
    ];
    for (i, x) in exts.iter().enumerate() {
        v.push(base(format!("eklenti-{i}"), "claude", json!({})).facts(json!({"ext": x})));
    }
    v.push(base("eklenti-acik-mcp".into(), "claude", json!({"mcp": {"name": "n", "command": "/c", "args": ["a"]}}))
        .facts(json!({"ext": exts[0]})));
    v.push(base("tarama-dustu".into(), "claude", json!({})).facts(json!({"live": "raise", "resume": "r"})));
    v.push(base("ad-tirnak".into(), "claude", json!({"name": "a b'c", "cwd": format!("{w}/x y"), "prompt": "merhaba"})));
    v
}

fn window_cases(e: &Env) -> Vec<Case> {
    let w = format!("{}/p1", e.work);
    let mut v = Vec::new();
    for (i, facts) in [json!({}), json!({"has_session": [false]}), json!({"popen": ["oserror"]}), json!({"popen": ["value"]})]
        .iter()
        .enumerate()
    {
        v.push(Case::new(format!("pencere-{i}"), "g9_window", json!({"name": "s1", "cwd": w, "display": ":4"})).facts(facts.clone()));
    }
    v.push(Case::new("pencere-ortam", "g9_window", json!({"name": "a b", "cwd": w})).env("DISPLAY", ":8").env("CLAUDE_X", "1"));
    for (i, facts) in [json!({}), json!({"popen": ["oserror"]}), json!({"popen": ["value"]})].iter().enumerate() {
        v.push(Case::new(format!("ayna-{i}"), "g9_mirror", json!({"host": "ulak31", "name": "proje 1", "port": 8765, "display": ":0"}))
            .facts(facts.clone()));
    }
    v.push(Case::new("ayna-ortam", "g9_mirror", json!({"host": "h'x", "name": "ğ\"", "port": 1})).env("DISPLAY", ":3"));
    v
}

fn reclaim_cases() -> Vec<Case> {
    let mut v = Vec::new();
    let long: String = (0..200).map(|i| format!("satır {i} ğüşiöç\n")).collect();
    let screens = [
        json!(null),
        json!(""),
        json!("\u{1b}[1;32mbitti\u{1b}[0m\r\n\r\n   \r\nçıkış\n"),
        json!(long),
        json!("a\u{1c}b\u{1d}c\u{0b}d\u{0c}e\u{85}f\u{2028}g\u{2029}h\n\t \n"),
        json!("\u{1b}]0;başlık\u{7}metin\u{1b}[?25l\n"),
        json!("x".repeat(1600)),
    ];
    for (i, sc) in screens.iter().enumerate() {
        v.push(Case::new(format!("hayalet-{i}"), "g9_reclaim", json!({"name": "s1", "cli": "claude"}))
            .facts(json!({"ghost": true, "capture": sc})));
    }
    v.push(Case::new("hayalet-shell", "g9_reclaim", json!({"name": "s1", "cli": "shell"})).facts(json!({"ghost": true})));
    v.push(Case::new("hayalet-degil", "g9_reclaim", json!({"name": "s1", "cli": "agy"})));
    v.push(Case::new("hayalet-tmuxsuz", "g9_reclaim", json!({"name": "s1", "cli": "ucli"})).facts(json!({"ghost": true, "tmux": false})));
    v
}

fn sync_cases(e: &Env) -> Vec<Case> {
    let b = "<!-- claudeops-routing:begin -->";
    let en = "<!-- claudeops-routing:end -->";
    let codex = format!("{}/.codex/AGENTS.md", e.home);
    let agy = format!("{}/.gemini/GEMINI.md", e.home);
    let args = json!({"codex": codex, "agy": agy});
    let mut v = Vec::new();
    let settings = [json!(null), json!({"routing_guidance": "off"}), json!({"routing_guidance_text": "özel"})];
    let files: [Vec<Fx>; 6] = [
        vec![],
        vec![file("home/.codex/AGENTS.md", "kullanıcı\n", 0o640)],
        vec![file("home/.gemini/GEMINI.md", "agy kullanıcı\n", 0o600)],
        vec![file("home/.codex/AGENTS.md", "k\n", 0o644), file("home/.gemini/GEMINI.md", &format!("{b}\neski\n{en}\n"), 0o600)],
        vec![Fx::File("home/.codex/AGENTS.md".into(), vec![0xff, b'\n'], 0o600), file("home/.gemini/GEMINI.md", "g\n", 0o600)],
        vec![file("home/dot/agents.md", "bağlı\n", 0o600), Fx::Link("home/.codex/AGENTS.md".into(), "../dot/agents.md".into()),
             Fx::Dir("home/.gemini".into(), 0o755)],
    ];
    for (i, s) in settings.iter().enumerate() {
        for (j, fx) in files.iter().enumerate() {
            let mut c = Case::new(format!("esitle-{i}-{j}"), "g9_sync", args.clone());
            if !s.is_null() {
                c = c.settings_json(s.clone());
            }
            for f in fx {
                c = c.file(f.clone());
            }
            v.push(c);
        }
    }
    // Yedek zaten var, kırık bağlantı yedek, salt okunur dizin (yazılamaz: OSError sınıfı).
    v.push(Case::new("esitle-yedek-var", "g9_sync", args.clone())
        .file(file("home/.codex/AGENTS.md", "k\n", 0o600))
        .file(file("home/.codex/AGENTS.md.bak-routing", "eski", 0o600)));
    // Kırık bağlantı yedek: `os.path.exists` false, `copy2` bağlantıyı izleyip HEDEFİ oluşturur (Python hatası adayı).
    v.push(Case::new("esitle-kirik-yedek", "g9_sync", args.clone())
        .file(file("home/.codex/AGENTS.md", "k\n", 0o600))
        .file(Fx::Link("home/.codex/AGENTS.md.bak-routing".into(), "../baska-yer.md".into())));
    v.push(Case::new("esitle-salt-okunur", "g9_sync", args.clone())
        .file(file("home/.codex/AGENTS.md", "k\n", 0o600))
        .file(Fx::Dir("home/.gemini".into(), 0o500)));
    v.push(Case::new("esitle-dizin", "g9_sync", args).file(Fx::Dir("home/.codex/AGENTS.md".into(), 0o755)));
    v
}

pub fn run() {
    let mut r = Runner::new();
    let cases = spawn_cases(&r.e);
    r.run(cases, &[], rs_g9);
    let cases = window_cases(&r.e);
    r.run(cases, &[], rs_g9);
    r.run(reclaim_cases(), &[], rs_g9);
    let cases = sync_cases(&r.e);
    r.run(cases, &[], rs_g9);
    r.run(vec![Case::new("depo-dizini", "g9_repo_dir", json!({}))], &[], rs_g9);
    r.finish("g9");
}
