//! Model kaynakları (G7) birim testleri: paritenin göremediği sözleşmeler (sır maskeleme, okuma sınırları, ardışık hata,
//! gerçek arka plan iş parçacığı, belge deposu, tek ortak çekim). Gerçek süreç, ağ ya da dosya YOK.

use cops_providers::model_sources::{
    AGY_MODELS_MAX_BYTES, CODEX_CACHE_MAX_BYTES, HTTP_MAX_BYTES, LIVE_MODELS_TIMEOUT,
};
use cops_providers::ucli::{self, reasoning_effort_for};
use cops_providers::ucli_opts::{Toolchain, SERVICE_MODELS_RETRY, SERVICE_MODELS_TTL};
use cops_providers::{
    agy, codex, Cli, HttpRequest, McpRegisterError, ModelIo, ModelSources, Paths, Probe, Providers,
    RunRequest, SecretValue, Settings,
};
use serde_json::{json, Value};
use std::sync::mpsc::{channel, Receiver};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

const WAIT: Duration = Duration::from_secs(10);

type Job = Box<dyn FnOnce() + Send + 'static>;

#[derive(Default)]
struct State {
    t: f64,
    run: Option<Vec<u8>>,
    http: Option<Vec<u8>>,
    file: Option<Vec<u8>>,
    doc: Option<Value>,
    runs: Vec<RunRequest>,
    gets: Vec<HttpRequest>,
    reads: Vec<(String, u64)>,
    /// None: gerçek iş parçacığı (varsayılan uygulama); Some: iş kuyrukta bekler.
    queue: Option<Vec<Job>>,
}

#[derive(Default)]
struct Fake {
    s: Mutex<State>,
    /// İkinci ve sonraki `run_stdout` çağrıları bu kapıda (zaman aşımlı) bekler.
    gate: Mutex<Option<Receiver<()>>>,
}

impl Fake {
    fn set(&self, f: impl FnOnce(&mut State)) {
        f(&mut self.s.lock().unwrap())
    }
    fn counts(&self) -> (usize, usize, usize) {
        let s = self.s.lock().unwrap();
        (s.runs.len(), s.gets.len(), s.reads.len())
    }
}

/// Varsayılan `spawn_background`ı (gerçek iş parçacığı) sınamak için kuyruksuz sarmalayıcı.
struct Threaded(Arc<Fake>);

macro_rules! forward {
    ($t:ty, $f:expr) => {
        fn monotonic_secs(&self) -> f64 {
            $f(self).s.lock().unwrap().t
        }
        fn wall_secs(&self) -> f64 {
            $f(self).s.lock().unwrap().t
        }
        fn claude_models_doc(&self) -> Option<Value> {
            $f(self).s.lock().unwrap().doc.clone()
        }
        fn read_file(&self, path: &str, max: u64) -> Option<Vec<u8>> {
            let mut s = $f(self).s.lock().unwrap();
            s.reads.push((path.into(), max));
            s.file.clone()
        }
        fn run_stdout(&self, req: &RunRequest) -> Option<Vec<u8>> {
            let (n, out) = {
                let mut s = $f(self).s.lock().unwrap();
                s.runs.push(req.clone());
                (s.runs.len(), s.run.clone())
            };
            if n > 1 {
                if let Some(rx) = $f(self).gate.lock().unwrap().take() {
                    let _ = rx.recv_timeout(WAIT);
                    let late = $f(self).s.lock().unwrap().run.clone();
                    return late;
                }
            }
            out
        }
        fn http_get(&self, req: &HttpRequest) -> Option<Vec<u8>> {
            let mut s = $f(self).s.lock().unwrap();
            s.gets.push(req.clone());
            s.http.clone()
        }
    };
}

fn same(f: &Fake) -> &Fake {
    f
}

fn inner(t: &Threaded) -> &Fake {
    &t.0
}

impl ModelIo for Fake {
    forward!(Fake, same);
    fn spawn_background(&self, _name: &'static str, job: Job) {
        // kuyruk yoksa iş DÜŞER (iş parçacığı başlatılamadı durumu)
        if let Some(q) = self.s.lock().unwrap().queue.as_mut() {
            q.push(job);
        }
    }
}

impl ModelIo for Threaded {
    forward!(Threaded, inner);
}

/// Yalnız `which` kullanılır (agy ikilisi çözümü).
struct Which;

impl Probe for Which {
    fn is_file(&self, _: &str) -> bool {
        false
    }
    fn is_dir(&self, _: &str) -> bool {
        false
    }
    fn exists(&self, _: &str) -> bool {
        false
    }
    fn is_symlink(&self, _: &str) -> bool {
        false
    }
    fn is_executable_file(&self, _: &str) -> bool {
        false
    }
    fn file_size(&self, _: &str) -> Option<u64> {
        None
    }
    fn read_text(&self, _: &str) -> Option<String> {
        None
    }
    fn realpath(&self, p: &str) -> String {
        p.into()
    }
    fn which(&self, name: &str) -> Option<String> {
        Some(format!("/opt/my tools/{name}"))
    }
    fn env_var(&self, _: &str) -> Option<String> {
        None
    }
    fn claude_help(&self, _: &str) -> String {
        String::new()
    }
    fn ucli_chat_help(&self, _: &str) -> String {
        String::new()
    }
    fn path_executables(&self) -> Vec<String> {
        Vec::new()
    }
    fn rust_toolchain(&self) -> Result<Toolchain, String> {
        Err(String::new())
    }
    fn searxng_url(&self, _: &str, _: bool) -> Option<String> {
        None
    }
    fn checks_registry(&self, _: &str) -> Result<(), String> {
        Ok(())
    }
    fn claude_cost_gate(&self, _: &str) -> Result<(), cops_providers::cost::CostRefusal> {
        Ok(())
    }
    fn issue_agent_token(&self, _: &str) -> Result<String, String> {
        Err(String::new())
    }
    fn panel_port(&self) -> Option<u16> {
        None
    }
    fn apply_now(
        &self,
        _: &cops_providers::Effect,
    ) -> Result<(), cops_providers::real::effects::EffectError> {
        unimplemented!()
    }
    fn register_mcp(&self, _: &str, _: &str, _: &[String]) -> Result<(), McpRegisterError> {
        Ok(())
    }
}

fn paths() -> Paths {
    Paths {
        claudeops_dir: "/yok/state".into(),
        home: "/yok/home".into(),
        repo_dir: "/yok/repo".into(),
    }
}

fn keyed(key: &str) -> Settings {
    Settings::from_json(&json!({"byok": {"ucli": {"UCLI_API_KEY": key}}}).to_string())
}

fn setup() -> (Arc<Fake>, ModelSources) {
    let io = Arc::new(Fake::default());
    io.set(|s| {
        s.t = 1000.0;
        s.queue = Some(Vec::new());
    });
    let sources = ModelSources::new(io.clone());
    (io, sources)
}

fn live_body(id: &str) -> Vec<u8> {
    json!({"data": [{"id": id, "task": "chat", "capabilities": {"reasoning_effort": true}},
                    {"id": "gemma", "task": "chat", "capabilities": {"reasoning_effort": false}}]})
    .to_string()
    .into_bytes()
}

#[test]
fn lifetimes_and_limits_match_python() {
    assert_eq!(
        (agy::MODELS_TTL, codex::MODELS_TTL, ucli::MODELS_TTL),
        (300.0, 300.0, 300.0)
    );
    assert_eq!((SERVICE_MODELS_TTL, SERVICE_MODELS_RETRY), (86400.0, 60.0));
    assert_eq!(LIVE_MODELS_TIMEOUT, Duration::from_secs(5));
}

#[test]
fn agy_catalog_runs_the_resolved_binary_without_a_shell() {
    let (io, sources) = setup();
    io.set(|s| s.run = Some(b"Fetching\nm1\tM One\n".to_vec()));
    let (settings, paths) = (Settings::default(), paths());
    let c = sources.catalog(Cli::Agy, &settings, &paths, &Which);
    assert_eq!(c.agy_models, ["m1"]);
    let runs = io.s.lock().unwrap().runs.clone();
    assert_eq!(runs.len(), 1);
    assert_eq!(runs[0].argv, ["/opt/my tools/agy", "models"]);
    assert_eq!(
        (runs[0].timeout, runs[0].max_stdout),
        (Duration::from_secs(5), AGY_MODELS_MAX_BYTES)
    );
}

#[test]
fn agy_stale_list_is_returned_at_once_while_a_real_thread_refreshes() {
    let fake = Arc::new(Fake::default());
    let (open, gate) = channel();
    *fake.gate.lock().unwrap() = Some(gate);
    fake.set(|s| {
        s.t = 1000.0;
        s.run = Some(b"Fetching...\nm-old\tEski\n".to_vec());
    });
    let sources = ModelSources::new(Arc::new(Threaded(fake.clone())));
    let bin = || "agy".to_string();
    assert_eq!(sources.agy_models(bin), ["m-old"]); // soğuk: bloklayarak
    fake.set(|s| s.t += agy::MODELS_TTL + 1.0);
    let started = Instant::now();
    assert_eq!(sources.agy_models(bin), ["m-old"]); // bayat: hemen
    assert_eq!(sources.agy_models(bin), ["m-old"]); // yenileme sürerken de kilit tutulmaz
    assert!(started.elapsed() < Duration::from_secs(5));
    fake.set(|s| s.run = Some(b"m-new\tYeni\n".to_vec()));
    open.send(()).unwrap();
    let deadline = Instant::now() + WAIT;
    while sources.agy_models(bin) != ["m-new"] {
        assert!(Instant::now() < deadline, "arka plan yenilemesi gelmedi");
        std::thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(fake.counts().0, 2);
}

#[test]
fn a_background_job_that_cannot_start_keeps_the_old_list() {
    let (io, sources) = setup();
    io.set(|s| {
        s.run = Some(b"a\tA\n".to_vec());
        s.queue = None;
    });
    assert_eq!(sources.agy_models(|| "agy".into()), ["a"]);
    io.set(|s| s.t += 301.0);
    assert_eq!(sources.agy_models(|| "agy".into()), ["a"]);
    assert_eq!(io.counts().0, 1);
}

#[test]
fn binary_is_resolved_only_when_a_fetch_is_due() {
    let (io, sources) = setup();
    io.set(|s| s.run = Some(b"a\tA\n".to_vec()));
    sources.agy_models(|| "agy".into());
    sources.agy_models(|| panic!("TTL içinde ikili çözülmemeli"));
}

#[test]
fn repeated_errors_never_replace_the_last_good_list() {
    let (io, sources) = setup();
    let (settings, paths) = (keyed("k"), paths());
    io.set(|s| {
        s.run = Some(b"a\tA\n".to_vec());
        s.http = Some(live_body("u"));
        s.file = Some(br#"{"models": [{"slug": "c", "visibility": "list"}]}"#.to_vec());
    });
    let all = |sources: &ModelSources| {
        (
            sources.agy_models(|| "agy".into()),
            sources.codex_models(&paths),
            sources.ucli_live(&settings),
        )
    };
    all(&sources);
    for _ in 0..6 {
        io.set(|s| {
            s.t += 301.0;
            (s.run, s.http, s.file) = (None, None, None);
        });
        let (a, c, u) = all(&sources);
        // kilit işler koşmadan bırakılır (işin kendisi de `Fake`i kullanır)
        let jobs = io.s.lock().unwrap().queue.replace(Vec::new()).unwrap();
        jobs.into_iter().for_each(|job| job());
        assert_eq!(
            (a, c, u.choices()),
            (
                vec!["a".to_string()],
                vec!["c".into()],
                vec!["u".into(), "gemma".into()]
            )
        );
        assert_eq!(
            reasoning_effort_for(&u, "u", "high").as_deref(),
            Some("high")
        );
    }
    assert_eq!(io.counts(), (7, 7, 7));
}

#[test]
fn oversized_answers_are_ignored_even_if_the_implementation_returns_them() {
    let (io, sources) = setup();
    let (settings, paths) = (keyed("k"), paths());
    let big = |max: u64, head: &[u8]| {
        let mut v = head.to_vec();
        v.resize(max as usize + 1, b' ');
        Some(v)
    };
    io.set(|s| {
        s.run = big(AGY_MODELS_MAX_BYTES, b"a\tA\n");
        s.file = big(
            CODEX_CACHE_MAX_BYTES,
            br#"{"models": [{"slug": "c", "visibility": "list"}]}"#,
        );
        s.http = big(
            HTTP_MAX_BYTES,
            br#"{"data": [{"id": "u", "task": "chat"}]}"#,
        );
    });
    assert!(sources.agy_models(|| "agy".into()).is_empty());
    assert_eq!(sources.codex_models(&paths), codex::FALLBACK_MODELS);
    assert_eq!(sources.ucli_live(&settings).ids, [ucli::FALLBACK_MODEL]);
    assert!(sources.service_models(&settings, "grok", "k").is_empty());
    let s = io.s.lock().unwrap();
    assert_eq!(
        s.reads,
        [(paths.codex_models_cache(), CODEX_CACHE_MAX_BYTES)]
    );
    assert!(s.gets.iter().all(|r| r.max_body == HTTP_MAX_BYTES));
}

#[test]
fn model_list_and_effort_gate_share_one_fetch() {
    let (io, sources) = setup();
    io.set(|s| s.http = Some(live_body("deepseek-v4-flash")));
    let (settings, paths) = (keyed("k"), paths());
    let catalog = sources.catalog(Cli::Ucli, &settings, &paths, &Which);
    let p = Providers {
        settings: &settings,
        catalog: &catalog,
        paths: &paths,
        probe: &Which,
    };
    assert_eq!(p.model_choices(Cli::Ucli), ["deepseek-v4-flash", "gemma"]);
    let again = sources.catalog(Cli::Ucli, &settings, &paths, &Which);
    assert_eq!(
        reasoning_effort_for(&again.ucli, "deepseek-v4-flash", "high").as_deref(),
        Some("high")
    );
    assert_eq!(reasoning_effort_for(&again.ucli, "gemma", "high"), None);
    assert_eq!(io.counts(), (0, 1, 0));
}

#[test]
fn catalog_touches_only_its_own_source() {
    let (io, sources) = setup();
    io.set(|s| {
        s.doc = Some(json!({"models": {"claude-sonnet-5-5": "enabled", "claude-x-1": "disabled"}}))
    });
    let (settings, paths) = (keyed("k"), paths());
    // claude: belge deposu doğruluk kaynağı; crate `claude_models.json`ı kendisi OKUMAZ (db kipinde dosya bayat olabilir)
    let c = sources.catalog(Cli::Claude, &settings, &paths, &Which);
    let p = Providers {
        settings: &settings,
        catalog: &c,
        paths: &paths,
        probe: &Which,
    };
    assert_eq!(p.model_choices(Cli::Claude), ["claude-sonnet-5-5"]);
    for cli in [Cli::Copilot, Cli::Shell] {
        sources.catalog(cli, &settings, &paths, &Which);
    }
    assert_eq!(io.counts(), (0, 0, 0));
    sources.catalog(Cli::Codex, &settings, &paths, &Which);
    assert_eq!((io.counts().0, io.counts().1), (0, 0));
}

#[test]
fn codex_choices_are_cached_but_effort_levels_read_the_current_file() {
    let (io, sources) = setup();
    let (settings, paths) = (Settings::default(), paths());
    let doc = |slug: &str, level: &str| {
        Some(
            json!({"models": [{"slug": slug, "visibility": "list", "supported_reasoning_levels": [level]}]})
                .to_string()
                .into_bytes(),
        )
    };
    io.set(|s| s.file = doc("m", "low"));
    sources.catalog(Cli::Codex, &settings, &paths, &Which);
    io.set(|s| s.file = doc("yeni", "high"));
    let c = sources.catalog(Cli::Codex, &settings, &paths, &Which);
    let p = Providers {
        settings: &settings,
        catalog: &c,
        paths: &paths,
        probe: &Which,
    };
    assert_eq!(p.model_choices(Cli::Codex), ["m"]);
    assert_eq!(
        p.model_effort_levels(Cli::Codex, "yeni"),
        Some(vec!["high".to_string()])
    );
}

#[test]
fn no_request_without_a_key() {
    let (io, sources) = setup();
    for settings in [Settings::default(), keyed(""), keyed(" \t\n")] {
        assert!(ucli::fetch_live_models(io.as_ref(), &settings).is_none());
    }
    assert!(sources
        .service_models(&Settings::default(), "grok", "")
        .is_empty());
    assert_eq!(io.counts(), (0, 0, 0));
}

#[test]
fn a_key_that_cannot_be_a_header_value_sends_nothing() {
    let (io, sources) = setup();
    for bad in ["a\nX-Enjekte: 1", "a\r\n b", "anahtar-ş"] {
        assert!(
            ucli::fetch_live_models(io.as_ref(), &keyed(bad)).is_none(),
            "{bad:?}"
        );
        assert!(
            sources
                .service_models(&Settings::default(), "grok", bad)
                .is_empty(),
            "{bad:?}"
        );
        io.set(|s| s.t += 61.0);
    }
    assert_eq!(io.counts(), (0, 0, 0));
    // latin-1 gönderilebilir (Python gibi)
    assert_eq!(SecretValue::new("é").unwrap().expose(), [0xe9]);
}

#[test]
fn the_key_stays_out_of_urls_argv_and_debug_output() {
    let (io, sources) = setup();
    let secret = "COK-GIZLI-ANAHTAR";
    let settings = Settings::from_json(
        &json!({"byok": {"ucli": {"UCLI_API_KEY": secret}}, "ucli_endpoint": "https://kul:PAROLA@h.invalid/v1"}).to_string(),
    );
    io.set(|s| s.run = Some(b"a\tA\n".to_vec()));
    sources.ucli_live(&settings);
    for service in ["grok", "claude"] {
        sources.service_models(&settings, service, secret);
    }
    sources.agy_models(|| "agy".into());
    let s = io.s.lock().unwrap();
    assert_eq!(s.gets.len(), 3);
    for r in &s.gets {
        assert!(!r.url.contains(secret));
        let shown = format!("{r:?} {r:#?}");
        assert!(
            !shown.contains(secret) && !shown.contains("PAROLA"),
            "{shown}"
        );
        assert!(shown.contains("<redacted>"));
        assert!(r
            .headers
            .iter()
            .any(|(_, v)| String::from_utf8_lossy(v.expose()).contains(secret)));
    }
    assert!(!format!("{:?}", s.runs).contains(secret));
}

#[test]
fn broken_and_mutated_model_answers_never_panic() {
    let seeds: [&[u8]; 3] = [
        br#"{"data": [{"id": "a", "task": "chat", "capabilities": {"x": [1, NaN]}}, "\ud800", 1e999]}"#,
        br#"[{"id": {"k": [true, null, -0.0]}}, {"id": "\u00e7"}]"#,
        b"\xef\xbb\xbf{\"data\":[{\"id\":123456789012345678901234567890}]}",
    ];
    let (io, sources) = setup();
    let settings = keyed("k");
    for seed in seeds {
        for end in 0..=seed.len() {
            for flip in [None, Some(0xffu8), Some(b'['), Some(b'"')] {
                let mut body = seed[..end].to_vec();
                if let (Some(f), true) = (flip, end > 0) {
                    body[end / 2] = f;
                }
                cops_providers::ucli_opts::parse_service_models(&body);
                io.set(|s| {
                    s.t += 90000.0;
                    (s.http, s.file) = (Some(body.clone()), Some(body.clone()));
                });
                assert!(!sources.ucli_live(&settings).ids.is_empty());
                assert!(!sources.codex_models(&paths()).is_empty());
            }
        }
    }
}
