//! Gerçek [`Probe`] + [`LiveProbe`].
//!
//! Dışarıdan verilenler ([`RealDeps`]) süreç başına tek örnek olması gereken ya da başka ize ait sınırlardır; hiçbiri
//! için sessiz "izin ver" varsayılanı yoktur.

use crate::cost::CostRefusal;
use crate::live::{FileStat, LiveProbe, SqlCell};
use crate::probe::{Effect, McpRegisterError, Paths, Probe};
use crate::pyjson::Py;
use crate::real::agents::AgentRegistry;
use crate::real::docs::DocStore;
use crate::real::effects::EffectError;
use crate::real::help::HelpCache;
use crate::real::process::{self, Capture, RunError, Spec};
use crate::real::{checks, effects, fsio, oserr, pathexec, sqlite, Env};
use crate::ucli_opts::Toolchain;
use std::fs;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

/// `_MCP_ADD_TIMEOUT`.
pub const MCP_ADD_TIMEOUT: Duration = Duration::from_secs(20);
/// `mcp add` çıktısından tutulan son bayt (günlüğe son 300 karakter gider; Python sınırsız).
const MCP_OUTPUT_TAIL: usize = 64 * 1024;
/// `/proc/<pid>/stat` okuma sınırı.
const PROC_STAT_MAX_BYTES: u64 = 64 * 1024;

/// Claude (API) hizmetinin günlük USD tavanı + başlatma payı (`ucli_cost.cap_exceeded` + `reserve`). Gerçek
/// uygulama [`crate::real::ledger::CostLedger`].
pub trait CostGate: Send + Sync {
    fn check_and_reserve(&self, session: &str) -> Result<(), CostRefusal>;
    /// Başlatma başarısız oldu: payı hemen geri ver.
    fn release(&self, session: &str);
}

/// Yönetilen SearXNG adresi (`searxng.ensure_search_url`). Gerçek uygulama [`crate::real::searxng::ManagedSearch`].
pub trait SearchUrl: Send + Sync {
    fn search_url(&self, session: &str, preview: bool) -> Option<String>;
}

/// `claude_provider._encode_cwd` -> `~/.claude/projects/<..>` (rs/proc `transcript.rs::encode_cwd`).
pub trait ProjectDirs: Send + Sync {
    fn claude_project_dir(&self, cwd: &str) -> String;
}

#[derive(Clone)]
pub struct RealDeps {
    pub docs: Arc<dyn DocStore>,
    pub projects: Arc<dyn ProjectDirs>,
    pub cost: Arc<dyn CostGate>,
    pub search: Arc<dyn SearchUrl>,
    /// Süreç başına TEK örnek paylaşılmalı.
    pub help: Arc<HelpCache>,
    /// Panelin loopback portu (`ucli_agents._PANEL_PORT`; panel süreci verir).
    pub panel_port: Option<u16>,
}

pub struct RealProbe {
    paths: Paths,
    env: Env,
    deps: RealDeps,
    agents: AgentRegistry,
    cwd: Option<String>,
    proc_root: String,
    mcp_timeout: Duration,
}

impl RealProbe {
    pub fn new(paths: Paths, env: Env, deps: RealDeps) -> RealProbe {
        let agents = AgentRegistry::new(&paths);
        RealProbe {
            paths,
            env,
            deps,
            agents,
            cwd: None,
            proc_root: "/proc".into(),
            mcp_timeout: MCP_ADD_TIMEOUT,
        }
    }

    /// Göreli yolların tabanı (verilmezse sürecin çalışma dizini).
    pub fn with_cwd(mut self, cwd: impl Into<String>) -> RealProbe {
        self.cwd = Some(cwd.into());
        self
    }

    /// `/proc` yerine başka kök (test).
    pub fn with_proc_root(mut self, root: impl Into<String>) -> RealProbe {
        self.proc_root = root.into();
        self
    }

    pub fn with_mcp_timeout(mut self, timeout: Duration) -> RealProbe {
        self.mcp_timeout = timeout;
        self
    }

    pub fn paths(&self) -> &Paths {
        &self.paths
    }

    pub fn agents(&self) -> &AgentRegistry {
        &self.agents
    }
}

impl Probe for RealProbe {
    fn is_file(&self, path: &str) -> bool {
        Path::new(path).is_file()
    }
    fn is_dir(&self, path: &str) -> bool {
        Path::new(path).is_dir()
    }
    fn exists(&self, path: &str) -> bool {
        Path::new(path).exists()
    }
    fn is_symlink(&self, path: &str) -> bool {
        fs::symlink_metadata(path).is_ok_and(|m| m.file_type().is_symlink())
    }
    fn is_executable_file(&self, path: &str) -> bool {
        pathexec::is_executable_file(path)
    }
    fn file_size(&self, path: &str) -> Option<u64> {
        fs::metadata(path).ok().map(|m| m.len())
    }
    fn read_text(&self, path: &str) -> Option<String> {
        fsio::read_text(path)
    }
    fn realpath(&self, path: &str) -> String {
        pathexec::realpath(path, &self.current_dir())
    }
    fn which(&self, name: &str) -> Option<String> {
        pathexec::which(&self.env, name)
    }
    fn env_var(&self, name: &str) -> Option<String> {
        self.env.get(name)
    }
    fn claude_help(&self, binary: &str) -> String {
        self.deps.help.text(&self.env, binary, &["--help"])
    }
    fn ucli_chat_help(&self, binary: &str) -> String {
        // çıplak komut adı PATH'ten çözülür
        let binary = pathexec::which(&self.env, binary).unwrap_or_else(|| binary.to_string());
        self.deps.help.text(&self.env, &binary, &["chat", "--help"])
    }
    fn path_executables(&self) -> Vec<String> {
        pathexec::path_executables(&self.env)
    }
    fn rust_toolchain(&self) -> Result<Toolchain, String> {
        pathexec::rust_toolchain(&self.paths.home, &self.env)
    }
    fn searxng_url(&self, session: &str, preview: bool) -> Option<String> {
        self.deps.search.search_url(session, preview)
    }
    fn checks_registry(&self, path: &str) -> Result<(), String> {
        checks::load_registry(path).map(drop)
    }
    fn claude_cost_gate(&self, session: &str) -> Result<(), CostRefusal> {
        self.deps.cost.check_and_reserve(session)
    }
    fn issue_agent_token(&self, session: &str) -> Result<String, String> {
        self.agents.issue_token(session)
    }
    fn panel_port(&self) -> Option<u16> {
        self.deps.panel_port
    }
    fn register_mcp(
        &self,
        cwd: &str,
        config_path: &str,
        argv: &[String],
    ) -> Result<bool, McpRegisterError> {
        // symlink ise hedefi değil bağlantının kendisi silinir
        if fs::symlink_metadata(config_path).is_ok() {
            fs::remove_file(config_path).map_err(|e| McpRegisterError::Unlink(oserr::repr(&e)))?;
        }
        let spec = Spec {
            argv,
            cwd: Some(cwd),
            env: &self.env,
            timeout: self.mcp_timeout,
            stdout: Capture::Tail(MCP_OUTPUT_TAIL),
            stderr: Capture::Tail(MCP_OUTPUT_TAIL),
        };
        let out = process::run(&spec)
            .map_err(|e| McpRegisterError::Spawn(run_error_repr(&e, argv, self.mcp_timeout)))?;
        // Python metin kipi, `errors="replace"`
        let text = |b: &[u8]| {
            String::from_utf8_lossy(b)
                .replace("\r\n", "\n")
                .replace('\r', "\n")
        };
        let (stdout, stderr) = (text(&out.stdout), text(&out.stderr));
        if out.code != 0 {
            return Err(McpRegisterError::Exit {
                rc: out.code,
                stdout,
                stderr,
            });
        }
        Ok(stdout.contains('\u{fffd}') || stderr.contains('\u{fffd}'))
    }
    fn apply_now(&self, effect: &Effect) -> Result<(), EffectError> {
        effects::apply(effect)
    }
}

/// `repr(e)`: `subprocess.run`ın fırlattığı istisna.
fn run_error_repr(e: &RunError, argv: &[String], timeout: Duration) -> String {
    match e {
        RunError::Spawn(io) | RunError::Io(io) => oserr::repr(io),
        RunError::Timeout => {
            let items: Vec<String> = argv.iter().map(|a| crate::pyfmt::py_str_repr(a)).collect();
            let secs = timeout.as_secs_f64();
            let secs = if secs.fract() == 0.0 {
                format!("{secs:.0}")
            } else {
                crate::pyfmt::float_repr(secs)
            };
            format!("TimeoutExpired([{}], {secs})", items.join(", "))
        }
        // `Capture::Tail` taşma üretmez
        RunError::Overflow => "OSError('output limit')".into(),
    }
}

impl LiveProbe for RealProbe {
    fn read_bytes(&self, path: &str, max: u64) -> Option<Vec<u8>> {
        fsio::read_bytes(path, max)
    }
    fn read_tail(&self, path: &str, max: u64) -> Option<Vec<u8>> {
        fsio::read_tail(path, max)
    }
    fn list_dir(&self, path: &str) -> Option<Vec<String>> {
        fsio::list_dir(path)
    }
    fn stat(&self, path: &str) -> Option<FileStat> {
        fsio::stat(path)
    }
    fn proc_stat(&self, pid: i64) -> Option<Vec<u8>> {
        fsio::read_bytes(
            &format!("{}/{pid}/stat", self.proc_root),
            PROC_STAT_MAX_BYTES,
        )
    }
    fn current_dir(&self) -> String {
        match &self.cwd {
            Some(c) => c.clone(),
            None => std::env::current_dir()
                .map_or_else(|_| ".".into(), |p| p.to_string_lossy().into_owned()),
        }
    }
    fn agy_sids_doc(&self) -> Option<Py> {
        self.deps.docs.read("agy_sids", &self.paths.agy_sids_json())
    }
    fn read_range(&self, path: &str, start: u64, len: u64) -> Option<Vec<u8>> {
        fsio::read_range(path, start, len)
    }
    fn sqlite_cell(&self, db: &str, sql: &str, param: &str) -> Option<SqlCell> {
        sqlite::sqlite_cell(db, sql, param)
    }
    fn sqlite_rows(
        &self,
        db: &str,
        sql: &str,
        params: &[SqlCell],
        row: &mut dyn FnMut(Vec<SqlCell>) -> bool,
    ) -> bool {
        sqlite::sqlite_rows(db, sql, params, row)
    }
    fn claude_project_dir(&self, cwd: &str) -> String {
        self.deps.projects.claude_project_dir(cwd)
    }
}
