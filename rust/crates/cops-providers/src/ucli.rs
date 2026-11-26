//! ucli sağlayıcısı. Her isteğe bağlı bayrak YALNIZ ikilinin `chat --help`i listeliyorsa eklenir.
//! API anahtarı argv'ye GİRMEZ: 0600 dosyaya yazılır, `sh -c` içinde `$(cat ...)` ile ortama alınır.

use crate::model_sources::{bounded, lock, HttpRequest, ModelIo, SecretValue, HTTP_MAX_BYTES, LIVE_MODELS_TIMEOUT};
use crate::probe::{BuildOutput, Effect, McpRegisterError, SpawnError};
use crate::provider::{BuildArgs, McpSpec, Providers};
use crate::pyfmt::{basename, fmt_g, join_path, join_quoted, py_float, py_str_repr, quote, str_of, truthy};
use crate::pyjson::Py;
use crate::settings::Settings;
use crate::ucli_opts::{exec_flags, expand_exec_cmds, str_list, BROAD_GLOBS};
use serde_json::{json, Map, Value};
use sha1::{Digest, Sha1};
use std::sync::Mutex;

pub const ALLOW_EDIT: &str = "allow-edit";
const ALLOW_CREATE: &str = "allow-create";
const READ_ONLY: &str = "read-only";
pub const PERMISSION_MODES: [&str; 3] = [READ_ONLY, ALLOW_EDIT, ALLOW_CREATE];
pub const EFFORT_LEVELS: [&str; 2] = ["medium", "high"];
pub const FALLBACK_MODEL: &str = "deepseek-v4-flash";
pub const DEFAULT_ENDPOINT: &str = "https://evren-llmapi.ssyz.org.tr/v1";
const REQUEST_TIMEOUT_SECS: i64 = 600;
const MAX_HISTORY_KIB: i64 = 128;
const INSTRUCTIONS_MAX_BYTES: u64 = 40960;
const PRICED_MODELS: [&str; 2] = ["claude-opus-5-5", "claude-sonnet-5-5"];
const DERIVES_CONTEXT_MARK: &str = "advertises a large window";

/// `--max-steps`, `--max-context-kib`, `--max-tool-calls`, `--max-output-tokens` ön ayarları (`_EFFORT_LIMITS`).
pub const EFFORT_LIMITS: [(&str, [i64; 4]); 2] = [("medium", [25, 256, 64, 4096]), ("high", [200, 16384, 256, 16000])];
const LIMIT_KEYS: [&str; 4] = ["max_steps", "max_context_kib", "max_tool_calls", "max_output_tokens"];

/// Uç noktanın `/models` sonucu.
#[derive(Debug, Clone, Default)]
pub struct LiveModels {
    pub ids: Vec<String>,
    /// model kimliği -> `capabilities`.
    pub caps: Map<String, Value>,
}

impl LiveModels {
    /// Boşsa tek elemanlı sabit yedek.
    pub fn choices(&self) -> Vec<String> {
        if self.ids.is_empty() {
            vec![FALLBACK_MODEL.into()]
        } else {
            self.ids.clone()
        }
    }
}

/// `/models` yanıtı: yalnız `task == "chat"` modeller.
pub fn parse_live_models(payload: &Value) -> LiveModels {
    let mut out = LiveModels::default();
    for m in payload.get("data").and_then(Value::as_array).into_iter().flatten() {
        let Some(id) = m.get("id").filter(|v| truthy(v)).map(str_of) else { continue };
        if m.get("task").and_then(Value::as_str) != Some("chat") {
            continue;
        }
        if let Some(c) = m.get("capabilities").filter(|c| c.is_object()) {
            out.caps.insert(id.clone(), c.clone());
        }
        out.ids.push(id);
    }
    out
}

/// Canlı model listesinin ömrü (sn).
pub const MODELS_TTL: f64 = 300.0;

/// `_fetch_live_models`: `GET <uç nokta>/models`. Anahtar yoksa istek YAPILMAZ; hata, bozuk yanıt ya da sohbet modeli
/// yoksa None.
pub fn fetch_live_models(io: &dyn ModelIo, settings: &Settings) -> Option<LiveModels> {
    let key = settings.byok_value("ucli", "UCLI_API_KEY");
    if key.is_empty() {
        return None;
    }
    let mut endpoint = settings.ucli_endpoint();
    if endpoint.is_empty() {
        endpoint = DEFAULT_ENDPOINT.into();
    }
    let req = HttpRequest {
        url: format!("{}/models", endpoint.trim_end_matches('/')),
        headers: vec![("X-API-Key", SecretValue::new(&key)?)],
        timeout: LIVE_MODELS_TIMEOUT,
        max_body: HTTP_MAX_BYTES,
    };
    let body = bounded(io.http_get(&req), req.max_body)?;
    // Python `json.loads(bytes)` UTF-8 BOM'u kabul eder (UTF-16/32'yi de; burada desteklenmez).
    let body = body.strip_prefix(b"\xef\xbb\xbf").unwrap_or(&body);
    let payload = Py::parse(std::str::from_utf8(body).ok()?)?.to_value();
    Some(parse_live_models(&payload)).filter(|l| !l.ids.is_empty())
}

#[derive(Debug, Default)]
struct Cached {
    ts: f64,
    /// `ids` boş = hiç liste yok (Python `None`); başarısız ilk denemeden sonra sabit yedek yazılır.
    live: LiveModels,
}

/// `_LIVE_MODEL_CACHE` / `_LIVE_MODEL_CACHE_TS` / `_LIVE_CAPS`.
#[derive(Debug, Default)]
pub struct LiveCache(Mutex<Cached>);

impl LiveCache {
    /// Önbellek yoksa ya da bayatsa (bloklayarak) çeker; başarısız çekim eski listeyi ve yetenekleri bırakır.
    pub(crate) fn get(&self, io: &dyn ModelIo, settings: &Settings) -> LiveModels {
        let now = io.monotonic_secs();
        {
            let mut c = lock(&self.0);
            if !c.live.ids.is_empty() && now - c.ts <= MODELS_TTL {
                return c.live.clone();
            }
            c.ts = now;
        }
        let fetched = fetch_live_models(io, settings);
        let mut c = lock(&self.0);
        match fetched {
            Some(live) => c.live = live,
            None if c.live.ids.is_empty() => c.live.ids = vec![FALLBACK_MODEL.into()],
            None => {}
        }
        c.live.clone()
    }
}

/// `--effort`e verilecek seviye; modelin alanı kabul ettiği kanıtlı değilse None.
pub fn reasoning_effort_for(live: &LiveModels, model: &str, level: &str) -> Option<String> {
    let caps = live.caps.get(model)?;
    if caps.get("reasoning_effort") != Some(&Value::Bool(true)) {
        return None;
    }
    if let Some(values) = caps.get("reasoning_effort_values").and_then(Value::as_array).filter(|v| !v.is_empty()) {
        let aliased = caps.get("reasoning_effort_aliases").and_then(Value::as_object).is_some_and(|a| a.contains_key(level));
        if !values.iter().any(|v| v.as_str() == Some(level)) && !aliased {
            return None;
        }
    }
    Some(level.to_string())
}

fn word_char(c: char) -> bool {
    c.is_alphanumeric() || c == '_' || c == '-'
}

/// Yardım metninde TAM bayrak (`(?<![\w-])flag(?![\w-])`); bulunan ilk konumun sonu.
pub fn find_flag(help: &str, flag: &str) -> Option<usize> {
    let mut from = 0;
    while let Some(i) = help[from..].find(flag) {
        let start = from + i;
        let end = start + flag.len();
        if !help[..start].chars().next_back().is_some_and(word_char) && !help[end..].chars().next().is_some_and(word_char)
        {
            return Some(end);
        }
        from = start + help[start..].chars().next().map_or(1, char::len_utf8);
    }
    None
}

/// Bayraktan sonraki ilk `[possible values: a, b]` listesi; bulunamazsa boş (= bilinmiyor).
pub fn flag_values(help: &str, flag: &str) -> Vec<String> {
    const MARK: &str = "[possible values: ";
    let Some(end) = find_flag(help, flag) else { return Vec::new() };
    let Some(i) = help[end..].find(MARK) else { return Vec::new() };
    let rest = &help[end + i + MARK.len()..];
    let Some(close) = rest.find(']') else { return Vec::new() };
    rest[..close].split(',').map(crate::pyfmt::strip).filter(|v| !v.is_empty()).map(str::to_string).collect()
}

/// `resolve_binary`: ayar -> `UCLI_BIN` -> `<repo>/bin/ucli` -> PATH -> kardeş proje derlemesi.
pub fn resolve_binary(p: &Providers<'_>) -> Result<String, SpawnError> {
    let over = p.settings.provider_bin("ucli");
    if !over.is_empty() {
        return Ok(over);
    }
    if let Some(env) = p.probe.env_var("UCLI_BIN").filter(|s| !s.is_empty()) {
        return Ok(env);
    }
    let own = format!("{}/bin/ucli", p.paths.repo_dir);
    if p.probe.is_file(&own) {
        return Ok(own);
    }
    if let Some(found) = p.probe.which("ucli") {
        return Ok(found);
    }
    for profile in ["release", "debug"] {
        let cand = format!("{}/work/projects/tmp/unified-cli/target/{profile}/ucli", p.paths.home);
        if p.probe.is_file(&cand) {
            return Ok(cand);
        }
    }
    Err(SpawnError(
        "ucli binary bulunamadı — Ayarlar > model'de provider_bin.ucli'yi ayarla, UCLI_BIN ortam değişkenini ver, PATH'e \
         ekle, ya da claudeops'a teslim et: `scripts/install-ucli.sh release --build` (unified-cli build'ini bin/ucli'ye \
         kopyalar)."
            .into(),
    ))
}

/// `state_dir_for(cwd)`: `<kök>/<ad>-<sha1(gerçek yol)[:10]>`.
pub fn state_dir_for(state_root: &str, real_cwd: &str) -> String {
    let mut name = basename(real_cwd.trim_end_matches('/'));
    if name.is_empty() {
        name = "root";
    }
    let base: String = name
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() || "_.-".contains(c) { c } else { '_' })
        .take(40)
        .collect();
    let digest: String = Sha1::digest(real_cwd.as_bytes()).iter().map(|b| format!("{b:02x}")).collect();
    format!("{state_root}/{base}-{}", &digest[..10])
}

fn safe_name(session: &str) -> String {
    session.chars().map(|c| if c.is_alphanumeric() || "-_.".contains(c) { c } else { '_' }).collect()
}

/// `binary_supports_flag`: yardım metninde TAM bayrak.
pub fn supports_flag(help: &str, flag: &str) -> bool {
    find_flag(help, flag).is_some()
}

/// `binary_derives_context`: ikili bağlam tavanını modelden türetiyor mu.
pub fn derives_context(help: &str) -> bool {
    help.contains(DERIVES_CONTEXT_MARK)
}

/// Oturum kullanım günlüğü yolu (`ucli_cost.log_path`).
pub fn usage_log_path(dir: &str, session: &str) -> String {
    let mut safe: String = safe_name(session).chars().take(100).collect();
    if safe.is_empty() {
        safe = "session".into();
    }
    format!("{dir}/{safe}.jsonl")
}

/// `<üst>_aj<N>` çocuk ajan adı.
pub fn is_child_name(name: &str) -> bool {
    let name = name.strip_suffix('\n').unwrap_or(name);
    name.rmatch_indices("_aj").any(|(i, _)| {
        let n = &name[i + 3..];
        i > 0 && !name[..i].contains('\n') && !n.is_empty() && !n.starts_with('0') && n.bytes().all(|b| b.is_ascii_digit())
    })
}

/// `flag VALUE` çiftini değiştir, yoksa ekle.
fn set_flag_value(argv: &mut Vec<String>, flag: &str, value: &str) {
    if let Some(i) = argv.iter().position(|a| a == flag) {
        if i + 1 < argv.len() {
            argv[i + 1] = value.into();
            return;
        }
        argv.remove(i);
    }
    argv.extend([flag.into(), value.into()]);
}

fn push_once(argv: &mut Vec<String>, flag: &str) {
    if !argv.iter().any(|a| a == flag) {
        argv.push(flag.into());
    }
}

fn value_after<'a>(argv: &'a [String], flag: &str) -> Option<&'a str> {
    argv.iter().position(|a| a == flag).and_then(|i| argv.get(i + 1)).map(String::as_str)
}

struct Ctx<'a, 'b> {
    p: &'a Providers<'b>,
    out: &'a mut BuildOutput,
    binary: String,
    help: String,
    session: &'a str,
}

impl Ctx<'_, '_> {
    fn has(&self, flag: &str) -> bool {
        find_flag(&self.help, flag).is_some()
    }

    fn unsupported(&mut self, flag: &str) {
        let (name, binary) = (self.session.to_string(), self.binary.clone());
        self.out.diag("ucli_flag_unsupported", vec![("name", json!(&name)), ("flag", json!(flag)), ("binary", json!(&binary))]);
    }

    /// İkili tanıyorsa true; tanımıyorsa günlüğe yazar.
    fn known(&mut self, flag: &str) -> bool {
        let ok = self.has(flag);
        if !ok {
            self.unsupported(flag);
        }
        ok
    }

    /// Güvenlik izni bayrağı: tanınmıyorsa spawn REDDEDİLİR (yarım izin yok).
    fn require(&mut self, flag: &str, why: &str) -> Result<(), SpawnError> {
        if self.known(flag) {
            Ok(())
        } else {
            Err(SpawnError(format!("ucli ikilisi {flag} bayrağını tanımıyor ({why})")))
        }
    }

    fn web_args(&mut self, argv: &mut Vec<String>) {
        let cfg = self.p.settings.ucli_web();
        if cfg.search_url.is_some() || cfg.search_docker {
            let auto = cfg.search_url.is_none();
            if !self.has("--search-url") {
                let (name, binary) = (self.session.to_string(), self.binary.clone());
                self.out.diag(
                    "ucli_web_flag_unsupported",
                    vec![("name", json!(&name)), ("flag", json!("--search-url")), ("binary", json!(&binary)), ("auto", json!(auto))],
                );
            } else {
                let preview = self.out.dry_run;
                let url = cfg.search_url.clone().or_else(|| self.p.probe.searxng_url(self.session, preview));
                if let Some(url) = url.filter(|u| !u.is_empty()) {
                    argv.extend(["--search-url".into(), url, "--search-flavor".into(), "searxng".into()]);
                }
            }
        }
        if !cfg.allow_fetch_domains.is_empty() {
            if self.has("--allow-fetch") {
                argv.push("--allow-fetch".into());
                for d in cfg.allow_fetch_domains {
                    argv.extend(["--allow-fetch-domain".into(), d]);
                }
            } else {
                let (name, binary) = (self.session.to_string(), self.binary.clone());
                self.out.diag(
                    "ucli_web_flag_unsupported",
                    vec![("name", json!(&name)), ("flag", json!("--allow-fetch")), ("binary", json!(&binary))],
                );
            }
        }
    }

    /// Ayara bağlı basit bayraklar, Python'daki sırayla.
    fn tuning_args(&mut self, argv: &mut Vec<String>, a: &BuildArgs<'_>, preset: &str, overrides: &[(&str, i64)], force_state: bool) {
        let s = self.p.settings;
        let limit = |key: &str, default: i64| overrides.iter().find(|(k, _)| *k == key).map_or(default, |(_, v)| *v);
        let script = s.ucli_script_mode();
        if !script.is_empty() && self.known("--allow-script") {
            argv.push(format!("--allow-script={script}"));
        }
        if self.known("--request-timeout-secs") {
            argv.extend(["--request-timeout-secs".into(), limit("request_timeout_secs", REQUEST_TIMEOUT_SECS).to_string()]);
        }
        if self.known("--max-history-kib") {
            argv.extend(["--max-history-kib".into(), limit("max_history_kib", MAX_HISTORY_KIB).to_string()]);
        }
        let mode = s.ucli_reasoning_mode();
        if mode != "off" && !a.model.is_empty() && self.known("--effort") {
            let level = if mode == "auto" { preset } else { &mode };
            match reasoning_effort_for(&self.p.catalog.ucli, a.model, level) {
                Some(v) => argv.extend(["--effort".into(), v]),
                None => {
                    let name = self.session.to_string();
                    self.out.diag("ucli_effort_skipped", vec![("name", json!(&name)), ("model", json!(a.model)), ("level", json!(level))]);
                }
            }
        }
        if s.ucli_stream() && self.known("--stream") {
            argv.push("--stream".into());
        }
        if s.ucli_show_reasoning() && self.known("--show-reasoning") {
            argv.push("--show-reasoning".into());
        }
        if !self.session.is_empty() && s.ucli_metrics_enabled() && self.known("--metrics-file") {
            let dir = self.p.paths.ucli_metrics_dir();
            let file = format!("{dir}/{}.jsonl", safe_name(self.session));
            self.out.effects.push(Effect::MkdirPrivate { path: dir });
            argv.extend(["--metrics-file".into(), file]);
        }
        if self.known("--interactive") {
            argv.push("--interactive".into());
        }
        self.state_dir_args(argv, a.cwd, force_state);
    }

    /// Geçmişi eski dizinde olan oturum eski dizinle açılır (konuşma kaybolmasın).
    fn state_dir_args(&mut self, argv: &mut Vec<String>, cwd: &str, force: bool) {
        let sdir = state_dir_for(&self.p.paths.ucli_state_root(), &self.p.probe.realpath(cwd));
        let file = format!("{}.jsonl", self.session);
        let in_new = !self.session.is_empty() && self.p.probe.exists(&join_path(&sdir, &file));
        if !(self.p.settings.ucli_state_dir() || in_new || force) || !self.known("--state-dir") {
            return;
        }
        let legacy = join_path(&join_path(&join_path(cwd, ".ucli"), "chat"), &file);
        if !in_new && !self.session.is_empty() && self.p.probe.exists(&legacy) {
            return;
        }
        argv.extend(["--state-dir".into(), sdir]);
    }

    /// Claude (Anthropic API) hizmeti: günlük tavan + takım bayrakları.
    fn claude_service_flags(&mut self, argv: &mut Vec<String>, cwd: &str) -> Result<(), SpawnError> {
        self.p.probe.claude_cost_gate(self.session).map_err(SpawnError)?;
        set_flag_value(argv, "--max-output-tokens", "16000");
        if self.known("--cache-ttl") {
            set_flag_value(argv, "--cache-ttl", self.p.settings.ucli_cache_ttl());
        }
        if self.known("--usage-log") {
            let dir = self.p.paths.ucli_usage_dir();
            let log = usage_log_path(&dir, self.session);
            self.out.effects.push(Effect::MkdirPrivate { path: dir });
            set_flag_value(argv, "--usage-log", &log);
        }
        if self.known("--instructions-auto") {
            let too_big = !cwd.is_empty()
                && ["AGENTS.md", "CLAUDE.md"].iter().any(|n| {
                    self.p.probe.file_size(&join_path(cwd, n)).is_some_and(|b| b > INSTRUCTIONS_MAX_BYTES)
                });
            if too_big {
                let name = self.session.to_string();
                self.out.diag(
                    "ucli_instructions_skipped",
                    vec![("name", json!(&name)), ("cwd", json!(cwd)), ("limit", json!(INSTRUCTIONS_MAX_BYTES))],
                );
            } else {
                push_once(argv, "--instructions-auto");
            }
        }
        Ok(())
    }

    /// Temiz `cli_opts` -> argv; dönen değer hizmet anahtarının ortam öneki.
    fn apply_cli_opts(
        &mut self,
        argv: &mut Vec<String>,
        opts: &Map<String, Value>,
        a: &BuildArgs<'_>,
    ) -> Result<String, SpawnError> {
        let probe = self.p.probe;
        let on = |k: &str| opts.get(k).is_some_and(truthy);
        let mut env_prefix = String::new();
        let service = opts.get("service").filter(|v| truthy(v)).map(str_of).unwrap_or_default();
        if !service.is_empty() && service != "evren" {
            let services = self.p.settings.ucli_services();
            let svc = services
                .iter()
                .find(|s| s.id == service)
                .ok_or_else(|| SpawnError(format!("bilinmeyen hizmet: {service}")))?;
            let key = self.p.settings.byok_value("ucli", &svc.env);
            if key.is_empty() {
                return Err(SpawnError(format!("{service}: anahtar yok (Model anahtarları panelinden gir: {})", svc.env)));
            }
            if !svc.wire.is_empty() && !self.has("--provider") {
                return Err(SpawnError("ucli ikilisi --provider bayrağını tanımıyor".into()));
            }
            let path = self.p.paths.ucli_key_file(&service);
            self.out.effects.push(Effect::WriteSecret { path: path.clone(), content: key });
            let endpoint = if svc.endpoint.is_empty() { "" } else { &svc.endpoint };
            set_flag_value(argv, "--endpoint", endpoint);
            set_flag_value(argv, "--api-key-env", &svc.env);
            if !svc.wire.is_empty() {
                set_flag_value(argv, "--provider", &svc.wire);
            }
            // Evren kataloğuna bağlı `--effort` başka hizmette anlamsız.
            if let Some(i) = argv.iter().position(|x| x == "--effort") {
                argv.drain(i..(i + 2).min(argv.len()));
            }
            if let Some(model) = value_after(argv, "--model").map(str::to_string) {
                let levels = self.p.settings.ucli_effort_levels_for(&service, &model).unwrap_or_default();
                if levels.iter().any(|x| x == a.effort) && self.has("--effort") {
                    argv.extend(["--effort".into(), a.effort.into()]);
                }
            }
            env_prefix = format!("{}=\"$(cat {})\"", svc.env, quote(&path));
            if service == "claude" {
                self.claude_service_flags(argv, a.cwd)?;
            }
        }
        if !argv.iter().any(|x| x == "--usage-log") && self.known("--usage-log") {
            let dir = format!("{}/other", self.p.paths.ucli_usage_dir());
            let log = usage_log_path(&dir, self.session);
            self.out.effects.push(Effect::MkdirPrivate { path: dir });
            set_flag_value(argv, "--usage-log", &log);
        }
        // `float(opts[k])`: dönüşmeyen değer Python'da ValueError/TypeError fırlatır (spawn düşer).
        let as_usd = |k: &str| -> Result<Option<f64>, SpawnError> {
            match opts.get(k).filter(|v| truthy(v)) {
                None => Ok(None),
                Some(v) => py_float(v).map(Some).ok_or_else(|| SpawnError(float_error(v))),
            }
        };
        if let Some(usd) = as_usd("max_cost_usd")? {
            if self.known("--max-cost-usd") {
                let model = value_after(argv, "--model").unwrap_or("").to_string();
                if PRICED_MODELS.contains(&model.as_str()) {
                    set_flag_value(argv, "--max-cost-usd", &fmt_g(usd));
                } else {
                    let name = self.session.to_string();
                    self.out.diag(
                        "ucli_max_cost_skipped",
                        vec![("name", json!(&name)), ("model", json!(&model)), ("reason", json!("no built-in price"))],
                    );
                }
            }
        }
        // Evren (ücretsiz) hizmette varsayılan oturum tavanı eklenmez.
        let session_cap = as_usd("max_session_usd")?.filter(|v| *v != 0.0).unwrap_or_else(|| {
            if service.is_empty() || service == "evren" {
                0.0
            } else {
                self.p.settings.default_max_session_usd()
            }
        });
        if session_cap != 0.0 && self.known("--max-session-usd") {
            set_flag_value(argv, "--max-session-usd", &fmt_g(session_cap));
        }
        for (key, flag) in [("git_commit", "--allow-git-commit"), ("git_push", "--allow-git-push")] {
            if on(key) {
                self.require(flag, "git izni yarım uygulanmaz")?;
                push_once(argv, flag);
            }
        }
        for (key, flag) in [
            ("max_prompt_tokens", "--max-prompt-tokens"),
            ("max_repeated_calls", "--max-repeated-calls"),
            ("max_consecutive_failures", "--max-consecutive-failures"),
            ("max_continuation_steps", "--max-continuation-steps"),
            ("exec_per_script", "--exec-per-script"),
            ("price", "--price"),
            ("no_prompt_cache", "--no-prompt-cache"),
            ("show_usage", "--show-usage"),
            ("checkpoint", "--checkpoint"),
            ("instructions_user", "--instructions-user"),
            ("instructions_max_kib", "--instructions-max-kib"),
        ] {
            let Some(val) = opts.get(key).filter(|v| truthy(v)) else { continue };
            if !self.known(flag) {
                continue;
            }
            if val.is_boolean() {
                push_once(argv, flag);
            } else {
                set_flag_value(argv, flag, &str_of(val));
            }
        }
        if let Some(ste) = opts.get("search_token_env").filter(|v| truthy(v)) {
            // Yalnız ad gider; arama arka ucu yoksa anlamsız.
            if !argv.iter().any(|x| x == "--search-url") {
                let name = self.session.to_string();
                self.out.diag(
                    "ucli_flag_skipped",
                    vec![("name", json!(&name)), ("flag", json!("--search-token-env")), ("reason", json!("no --search-url"))],
                );
            } else if self.known("--search-token-env") {
                set_flag_value(argv, "--search-token-env", &str_of(ste));
            }
        }
        for (key, flag) in [("allow_image", "--allow-image"), ("allow_scholar", "--allow-scholar")] {
            if on(key) {
                self.require(flag, "yetenek izni yarım uygulanmaz")?;
                push_once(argv, flag);
            }
        }
        if on("approval_dir") {
            return Err(SpawnError("approval_dir REPL oturumunda kullanılamaz (REPL için ask_dir)".into()));
        }
        if on("ask_dir") {
            if self.session.is_empty() {
                return Err(SpawnError("ask_dir için oturum adı gerekli".into()));
            }
            self.require("--ask-dir", "soru kanalı yarım uygulanmaz")?;
            if !valid_ask_name(self.session) {
                return Err(SpawnError("geçersiz oturum adı".into()));
            }
            let root = self.p.paths.ucli_ask_root();
            let dir = format!("{root}/{}", self.session);
            self.out.effects.push(Effect::MkdirPrivate { path: root });
            self.out.effects.push(Effect::MkdirPrivate { path: dir.clone() });
            self.out.effects.push(Effect::ChmodPrivate { path: dir.clone() });
            set_flag_value(argv, "--ask-dir", &dir);
        }
        let mut opts = opts.clone();
        if on_map(&opts, "exec_cmds") {
            let names = expand_exec_cmds(&str_list(&opts, "exec_cmds"), &probe.path_executables()).map_err(SpawnError)?;
            opts.insert("exec_cmds".into(), Value::from(names));
        }
        let ex = exec_flags(&opts, &|| probe.rust_toolchain(), &|d| probe.is_dir(d));
        let globs = str_list(&opts, "exec_own_glob");
        if on_map(&opts, "accept_risk") && globs.iter().any(|g| BROAD_GLOBS.contains(&g.as_str())) {
            let broad: Vec<&str> = globs.iter().map(String::as_str).filter(|g| BROAD_GLOBS.contains(g)).collect();
            let name = self.session.to_string();
            self.out.diag("ucli_grant", vec![("name", json!(&name)), ("globs", json!(broad)), ("accept_risk", json!(true))]);
        }
        if !ex.is_empty() {
            let mut need = vec!["--allow-exec", "--allow-exec-cmd"];
            if on_map(&opts, "exec_own_glob") {
                need.push("--allow-exec-own-glob");
            }
            if on_map(&opts, "exec_bind_ro") || on_map(&opts, "exec_toolchain") {
                need.push("--exec-bind-ro");
            }
            if on_map(&opts, "exec_toolchain") {
                need.extend(["--exec-env", "--exec-memory-mib", "--exec-max-tasks"]);
            }
            if on_map(&opts, "exec_timeout") {
                need.push("--exec-timeout-secs");
            }
            for flag in need {
                self.require(flag, "exec izni yarım uygulanmaz")?;
            }
            argv.extend(ex.iter().cloned());
            if on_map(&opts, "exec_write") && !argv.iter().any(|x| x == "--allow-edit") {
                if !self.has("--allow-edit") {
                    return Err(SpawnError("ucli ikilisi --allow-edit bayrağını tanımıyor (yazma izni yarım uygulanmaz)".into()));
                }
                argv.retain(|x| x != "--allow-create");
                argv.push("--allow-edit".into());
            }
            if on_map(&opts, "ask_edit") {
                self.require("--ask-edit", "izin yarım uygulanmaz")?;
                push_once(argv, "--ask-edit");
            }
        }
        if let Some(uc) = opts.get("ucli_checks").filter(|v| truthy(v)) {
            if self.session.is_empty() {
                return Err(SpawnError("ucli_checks için oturum adı gerekli".into()));
            }
            let field = |k: &str| uc.get(k).map(str_of).unwrap_or_default();
            let (mode, max) = (field("mode"), field("max"));
            let risk = uc.get("accept_risk").is_some_and(truthy);
            let mut need = vec!["--allow-checks", "--checks-max", "--checks-file"];
            if risk {
                need.push("--checks-accept-risk");
            }
            for flag in need {
                self.require(flag, "kontrol izni yarım uygulanmaz")?;
            }
            for (flag, val) in [("--allow-checks", &mode), ("--checks-max", &max)] {
                let known = flag_values(&self.help, flag);
                if !known.is_empty() && !known.contains(val) {
                    return Err(SpawnError(format!(
                        "ucli ikilisi {flag} için '{val}' değerini tanımıyor (bilinenler: {})",
                        known.join(", ")
                    )));
                }
            }
            if !argv.iter().any(|x| x == "--state-dir") {
                return Err(SpawnError(
                    "ucli_checks için state-dir gerekli (ikili --state-dir'i tanımıyor ya da oturumun geçmişi eski dizinde)"
                        .into(),
                ));
            }
            let registry = format!("{}/owner.json", self.p.paths.ucli_checks_root());
            probe.checks_registry(&registry).map_err(SpawnError)?;
            set_flag_value(argv, "--allow-checks", &mode);
            set_flag_value(argv, "--checks-max", &max);
            set_flag_value(argv, "--checks-file", &registry);
            if risk {
                push_once(argv, "--checks-accept-risk");
            }
            if mode == "full" || max == "full" {
                let name = self.session.to_string();
                self.out.diag(
                    "ucli_grant",
                    vec![("name", json!(&name)), ("checks", json!("full")), ("accept_risk", json!(true))],
                );
            }
        }
        if on_map(&opts, "ask_edit") && ex.is_empty() {
            // Exec katmanı yok: onay yalnız `--allow-edit` varsa anlamlı.
            if !argv.iter().any(|x| x == "--allow-edit") {
                let name = self.session.to_string();
                self.out.diag(
                    "ucli_flag_skipped",
                    vec![("name", json!(&name)), ("flag", json!("--ask-edit")), ("reason", json!("no --allow-edit"))],
                );
            } else {
                self.require("--ask-edit", "izin yarım uygulanmaz")?;
                push_once(argv, "--ask-edit");
            }
        }
        Ok(env_prefix)
    }

    /// Alt ajan desteği: (ek argv, ek ortam atamaları). Token dosyada kalır, argv'ye girmez.
    fn agent_setup(&mut self) -> (Vec<String>, Vec<String>) {
        let none = (Vec::new(), Vec::new());
        if self.session.is_empty() || !self.p.settings.ucli_agents_enabled() || is_child_name(self.session) {
            return none;
        }
        let Some(port) = self.p.probe.panel_port().filter(|p| *p != 0) else { return none };
        if !self.known("--allow-agents") {
            return none;
        }
        // Kuru kurulum token ÜRETMEZ: yalnız dosya yolu (güvensiz ad gerçek koşuyla aynı biçimde reddedilir).
        let issued = if !self.out.dry_run {
            self.p.probe.issue_agent_token(self.session)
        } else if valid_ask_name(self.session) && !self.session.ends_with('\n') {
            Ok(self.p.paths.ucli_agent_token_file(self.session))
        } else {
            Err("ValueError".into())
        };
        match issued {
            Ok(path) => (
                vec!["--allow-agents".into()],
                vec![
                    format!("UCLI_AGENT_URL={}", quote(&format!("http://127.0.0.1:{port}"))),
                    format!("UCLI_AGENT_TOKEN=\"$(cat {})\"", quote(&path)),
                ],
            ),
            Err(e) => {
                let name = self.session.to_string();
                self.out.diag("ucli_agents_token_failed", vec![("name", json!(&name)), ("error", json!(&e))]);
                none
            }
        }
    }

    /// Evren anahtar dosyasını ayarla eşitle; true = komut anahtarı dosyadan okumalı.
    fn sync_api_key_file(&mut self) -> bool {
        let file = self.p.paths.ucli_key_file("");
        let marker = format!("{file}.managed");
        let key = self.p.settings.byok_value("ucli", "UCLI_API_KEY");
        if key.is_empty() {
            if self.p.probe.is_file(&marker) {
                self.out.effects.push(Effect::Remove { path: file });
                self.out.effects.push(Effect::Remove { path: marker });
                return false;
            }
            return self.p.probe.is_file(&file);
        }
        self.out.effects.push(Effect::WriteSecret { path: file, content: key });
        self.out.effects.push(Effect::Touch { path: marker });
        true
    }
}

fn on_map(opts: &Map<String, Value>, key: &str) -> bool {
    opts.get(key).is_some_and(truthy)
}

fn valid_ask_name(name: &str) -> bool {
    let name = name.strip_suffix('\n').unwrap_or(name);
    name.len() <= 100
        && name.bytes().next().is_some_and(|b| b.is_ascii_alphanumeric())
        && name.bytes().all(|b| b.is_ascii_alphanumeric() || b"_.-".contains(&b))
}

pub(crate) fn build_inner_command(
    p: &Providers<'_>,
    a: &BuildArgs<'_>,
    out: &mut BuildOutput,
) -> Result<String, SpawnError> {
    let preset = if EFFORT_LIMITS.iter().any(|(n, _)| *n == a.effort) { a.effort } else { "medium" };
    let base = EFFORT_LIMITS.iter().find(|(n, _)| *n == preset).expect("ön ayar var").1;
    let overrides = p.settings.ucli_limit_overrides();
    let limit = |i: usize| overrides.iter().find(|(k, _)| *k == LIMIT_KEYS[i]).map_or(base[i], |(_, v)| *v);
    let binary = resolve_binary(p)?;
    // Python `chat_help_text`: çıplak ad PATH'ten çözülür.
    let help = p.probe.ucli_chat_help(&p.probe.which(&binary).unwrap_or_else(|| binary.clone()));
    let mut cx = Ctx { p, out, binary: binary.clone(), help, session: a.session_name };

    let endpoint = Some(p.settings.ucli_endpoint()).filter(|e| !e.is_empty()).unwrap_or_else(|| DEFAULT_ENDPOINT.into());
    let mut argv: Vec<String> = [binary.as_str(), "--root", a.cwd, "chat", "--repl", "--endpoint", &endpoint, "--max-steps"]
        .map(String::from)
        .to_vec();
    argv.push(limit(0).to_string());
    // İkili bağlam tavanını modelden türetiyorsa yalnız açık ayar geçer.
    if overrides.iter().any(|(k, _)| *k == "max_context_kib") || !cx.help.contains(DERIVES_CONTEXT_MARK) {
        argv.extend(["--max-context-kib".into(), limit(1).to_string()]);
    }
    argv.extend(["--max-tool-calls".into(), limit(2).to_string()]);
    argv.extend(["--max-output-tokens".into(), limit(3).to_string()]);
    argv.push("--pretty".into());
    if !a.session_name.is_empty() {
        argv.extend(["--session".into(), a.session_name.into(), "--status-file".into()]);
    }
    if !a.model.is_empty() {
        argv.extend(["--model".into(), a.model.into()]);
    }
    if a.permission_mode == ALLOW_EDIT {
        argv.push("--allow-edit".into());
    } else if a.permission_mode == ALLOW_CREATE && cx.known("--allow-create") {
        argv.push("--allow-create".into());
    }
    cx.web_args(&mut argv);
    let opts = a.cli_opts.filter(|o| !o.is_empty());
    let force_state = opts.is_some_and(|o| on_map(o, "ucli_checks"));
    cx.tuning_args(&mut argv, a, preset, &overrides, force_state);
    if a.extra_args.iter().any(|x| x == "--with-mcp") {
        argv.push("--with-mcp".into());
    }
    let mut service_env = String::new();
    if let Some(opts) = opts {
        service_env = cx.apply_cli_opts(&mut argv, opts, a)?;
    }
    let (agent_args, agent_env) = cx.agent_setup();
    argv.extend(agent_args);
    let inner = join_quoted(&argv);
    let agent_prefix = if agent_env.is_empty() { String::new() } else { agent_env.join(" ") + " " };
    let sh = |wrapped: String| format!("sh -c {}", quote(&wrapped));
    if !service_env.is_empty() {
        return Ok(sh(format!("{service_env} {agent_prefix}exec {inner}")));
    }
    if cx.sync_api_key_file() {
        let key_file = p.paths.ucli_key_file("");
        let key_file = quote(&key_file);
        return Ok(sh(format!("UCLI_API_KEY=\"$(cat {key_file})\" {agent_prefix}exec {inner}")));
    }
    if !agent_prefix.is_empty() {
        return Ok(sh(format!("{agent_prefix}exec {inner}")));
    }
    Ok(inner)
}

/// `ucli mcp add` sunucu adı: 1-24 ASCII harf/rakam/alt çizgi.
pub fn mcp_server_name(spec_name: &str) -> String {
    let clean: String =
        spec_name.chars().map(|c| if c.is_ascii_alphanumeric() || c == '_' { c } else { '_' }).take(24).collect();
    if clean.is_empty() {
        "mcp".into()
    } else {
        clean
    }
}

/// `ucli --root CWD mcp add ...` argv'si (kimlik bilgisi yok).
pub fn mcp_add_argv(binary: &str, cwd: &str, spec: &McpSpec) -> Vec<String> {
    let name = mcp_server_name(&spec.name);
    let mut argv: Vec<String> =
        [binary, "--root", cwd, "mcp", "add", &name, "--command", &spec.command].map(String::from).to_vec();
    for t in &spec.allowed_tools {
        argv.extend(["--allow-tool".into(), t.clone()]);
    }
    argv.push("--".into());
    argv.extend(spec.args.iter().cloned());
    argv
}

/// `_MCP_TOOL_RE.fullmatch` (`[A-Za-z0-9_.-]{1,64}`): sondaki satır sonu da reddedilir.
fn valid_tool_name(t: &str) -> bool {
    (1..=64).contains(&t.len()) && t.bytes().all(|b| b.is_ascii_alphanumeric() || b"_.-".contains(&b))
}

pub(crate) fn mcp_launch_args(p: &Providers<'_>, spec: &McpSpec, cwd: &str, out: &mut BuildOutput) -> Vec<String> {
    let binary = match resolve_binary(p) {
        Ok(b) => b,
        Err(e) => {
            // Python `reason=repr(e)`: `UcliError('...')`.
            out.diag("ucli_mcp_skipped", vec![("server", json!(&spec.name)), ("reason", json!(py_repr("UcliError", &e.0)))]);
            return Vec::new();
        }
    };
    let help = p.probe.ucli_chat_help(&p.probe.which(&binary).unwrap_or_else(|| binary.clone()));
    if find_flag(&help, "--with-mcp").is_none() {
        out.diag("ucli_flag_unsupported", vec![("flag", json!("--with-mcp")), ("binary", json!(&binary))]);
        return Vec::new();
    }
    let tools: Vec<String> = spec.allowed_tools.iter().filter(|t| valid_tool_name(t)).cloned().collect();
    if tools.is_empty() {
        out.diag("ucli_mcp_skipped", vec![("server", json!(&spec.name)), ("reason", json!("no allowed tools"))]);
        return Vec::new();
    }
    if !cwd.starts_with('/') || !p.probe.is_dir(cwd) {
        out.diag("ucli_mcp_skipped", vec![("server", json!(&spec.name)), ("reason", json!("no workspace")), ("cwd", json!(cwd))]);
        return Vec::new();
    }
    // Python `register_mcp(binary, cwd, clean)`: oturum adı geçirilmez, günlükte `name=""`.
    let dir = join_path(cwd, ".ucli");
    if p.probe.is_symlink(&dir) {
        out.diag(
            "ucli_mcp_register_failed",
            vec![("name", json!("")), ("cwd", json!(cwd)), ("error", json!(".ucli is a symlink"))],
        );
        return Vec::new();
    }
    // Kuru kurulum: kayıt silinmez/yazılmaz, `mcp add` koşmaz; komut satırı başarılı kayıttaki gibi.
    if out.dry_run {
        return vec!["--with-mcp".into()];
    }
    let clean = McpSpec { allowed_tools: tools, ..spec.clone() };
    match p.probe.register_mcp(cwd, &join_path(&dir, "mcp.json"), &mcp_add_argv(&binary, cwd, &clean)) {
        Ok(()) => {
            out.diag(
                "ucli_mcp_registered",
                vec![
                    ("name", json!("")),
                    ("cwd", json!(cwd)),
                    ("server", json!(mcp_server_name(&clean.name))),
                    ("tools", json!(clean.allowed_tools.len())),
                ],
            );
            vec!["--with-mcp".into()]
        }
        Err(McpRegisterError::Unlink(e) | McpRegisterError::Spawn(e)) => {
            out.diag("ucli_mcp_register_failed", vec![("name", json!("")), ("cwd", json!(cwd)), ("error", json!(e))]);
            Vec::new()
        }
        Err(McpRegisterError::Exit { rc, stdout, stderr }) => {
            // `(r.stderr or r.stdout or "")[-300:]`
            let text = if !stderr.is_empty() { stderr } else { stdout };
            let n = text.chars().count();
            let tail: String = text.chars().skip(n.saturating_sub(300)).collect();
            out.diag(
                "ucli_mcp_register_failed",
                vec![("name", json!("")), ("cwd", json!(cwd)), ("rc", json!(rc)), ("error", json!(tail))],
            );
            Vec::new()
        }
    }
}

/// `float(v)` hata metni (Python 3.10).
fn float_error(v: &Value) -> String {
    match v {
        Value::String(s) => format!("could not convert string to float: {}", py_str_repr(s)),
        Value::Array(_) => "float() argument must be a string or a real number, not 'list'".into(),
        Value::Object(_) => "float() argument must be a string or a real number, not 'dict'".into(),
        _ => "float() argument must be a string or a real number, not 'NoneType'".into(),
    }
}

/// Python `repr(Exc(msg))` (tek argümanlı istisna): `Exc('msg')`.
fn py_repr(class: &str, msg: &str) -> String {
    format!("{class}({})", py_str_repr(msg))
}

/// `instructions_check` içindeki bir dosya.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InstructionsFile {
    pub name: &'static str,
    pub bytes: u64,
    /// `bytes > limit` (sınır dahil değil).
    pub over: bool,
}

/// `instructions_check` sonucu (içerik OKUNMAZ, yalnız boyut).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InstructionsCheck {
    pub limit: u64,
    pub files: Vec<InstructionsFile>,
}

/// `os.path.dirname` (POSIX).
fn py_dirname(p: &str) -> &str {
    let head = &p[..p.rfind('/').map_or(0, |i| i + 1)];
    if !head.is_empty() && head.bytes().any(|b| b != b'/') {
        head.trim_end_matches('/')
    } else {
        head
    }
}

/// `ucli_provider.instructions_check` (panel `/api/ucli/instructions-check`): `cwd`deki `AGENTS.md`/`CLAUDE.md`
/// boyutları. `cwd` mutlak, NUL içermeyen, var olan bir dizin değilse boş liste. Dosya (symlink çözülünce) `cwd`
/// dışındaysa ya da normal dosya değilse atlanır. Boyut okunamazsa (Python `OSError`) o ana dek bulunanlar döner.
pub fn instructions_check(probe: &dyn crate::probe::Probe, cwd: &str) -> InstructionsCheck {
    let mut res = InstructionsCheck { limit: INSTRUCTIONS_MAX_BYTES, files: Vec::new() };
    if cwd.is_empty() || !cwd.starts_with('/') || cwd.contains('\0') {
        return res;
    }
    let root = probe.realpath(cwd);
    if !probe.is_dir(&root) {
        return res;
    }
    for name in ["AGENTS.md", "CLAUDE.md"] {
        let real = probe.realpath(&join_path(&root, name));
        if py_dirname(&real) != root || !probe.is_file(&real) {
            continue;
        }
        let Some(n) = probe.file_size(&real) else { return res };
        res.files.push(InstructionsFile { name, bytes: n, over: n > INSTRUCTIONS_MAX_BYTES });
    }
    res
}
