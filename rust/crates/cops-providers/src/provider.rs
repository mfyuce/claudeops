//! `CliProvider` arayüzünün spawn tarafı: tek `match` ile sağlayıcı seçimi (`get_provider`: bilinmeyen ad = claude).

use crate::effort::nearest_effort;
use crate::probe::{BuildOutput, Paths, Probe, SpawnError};
use crate::settings::Settings;
use crate::{agy, claude, codex, copilot, shell, ucli};
use serde_json::{Map, Value};

/// Yönetilen CLI'lar.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Cli {
    Claude,
    Agy,
    Codex,
    Copilot,
    Shell,
    Ucli,
}

impl Cli {
    pub const ALL: [Cli; 6] = [Cli::Claude, Cli::Agy, Cli::Codex, Cli::Copilot, Cli::Shell, Cli::Ucli];

    pub fn parse(name: &str) -> Cli {
        Cli::ALL.into_iter().find(|c| c.name() == name).unwrap_or(Cli::Claude)
    }

    pub fn name(self) -> &'static str {
        match self {
            Cli::Claude => "claude",
            Cli::Agy => "agy",
            Cli::Codex => "codex",
            Cli::Copilot => "copilot",
            Cli::Shell => "shell",
            Cli::Ucli => "ucli",
        }
    }

    /// Başlat penceresi `cli_opts`ını kabul eder.
    pub fn accepts_cli_opts(self) -> bool {
        self == Cli::Ucli
    }

    /// MCP kaydı çalışma alanına bağlı.
    pub fn mcp_needs_cwd(self) -> bool {
        self == Cli::Ucli
    }

    pub fn permission_modes(self) -> &'static [&'static str] {
        match self {
            Cli::Claude => &claude::PERMISSION_MODES,
            Cli::Agy => &agy::PERMISSION_MODES,
            Cli::Codex => &codex::PERMISSION_MODES,
            Cli::Copilot => &copilot::PERMISSION_MODES,
            Cli::Shell => &shell::SENTINEL,
            Cli::Ucli => &ucli::PERMISSION_MODES,
        }
    }

    /// Panelin yeni oturum formunda ön seçili izin modu.
    pub fn default_permission_mode(self) -> &'static str {
        match self {
            Cli::Ucli => ucli::ALLOW_EDIT,
            _ => "auto",
        }
    }

    pub fn effort_levels(self) -> &'static [&'static str] {
        match self {
            Cli::Claude => &claude::EFFORT_LEVELS,
            Cli::Agy => &agy::EFFORT_LEVELS,
            Cli::Codex => &codex::EFFORT_LEVELS,
            Cli::Copilot => &copilot::EFFORT_LEVELS,
            Cli::Shell => &shell::SENTINEL,
            Cli::Ucli => &ucli::EFFORT_LEVELS,
        }
    }

    pub fn default_effort(self) -> &'static str {
        match self {
            Cli::Claude => "medium",
            _ => self.effort_levels().last().copied().unwrap_or(""),
        }
    }

    /// Bu CLI çağrısına özel ortam (komut satırına `KEY=VAL` olarak gömülür: SIR KOYMA).
    pub fn env_overrides(self, session_name: &str) -> Vec<(String, String)> {
        match self {
            Cli::Claude => Vec::new(),
            Cli::Ucli => vec![("TOKIO_WORKER_THREADS".into(), "1".into())],
            Cli::Agy | Cli::Codex | Cli::Copilot | Cli::Shell => vec![("COPS_NAME".into(), session_name.into())],
        }
    }
}

/// Canlı model kaynakları; okuma/ağ çağıranın işi. Boş alan = Python'daki sabit yedek.
#[derive(Debug, Clone, Default)]
pub struct ModelCatalog {
    /// `claude_models` belgesi (`{"models": {id: "enabled"|"disabled"}}`).
    pub claude_state: Option<Value>,
    /// `agy models` çıktısındaki kimlikler (bkz. [`agy::parse_models`]).
    pub agy_models: Vec<String>,
    /// `~/.codex/models_cache.json` (ayrıştırılmış).
    pub codex_cache: Option<Value>,
    /// ucli uç noktasının `/models` sonucu (bkz. [`ucli::parse_live_models`]).
    pub ucli: ucli::LiveModels,
}

/// MCP sunucusunu bir CLI'a bağlama isteği.
#[derive(Debug, Clone, Default)]
pub struct McpSpec {
    pub name: String,
    pub command: String,
    pub args: Vec<String>,
    pub allowed_tools: Vec<String>,
}

/// `build_inner_command` girdileri.
#[derive(Debug, Clone, Default)]
pub struct BuildArgs<'a> {
    pub cwd: &'a str,
    pub model: &'a str,
    pub permission_mode: &'a str,
    pub effort: &'a str,
    pub resume_id: Option<&'a str>,
    pub prompt: Option<&'a str>,
    pub session_name: &'a str,
    pub extra_args: &'a [String],
    /// Yalnız `accepts_cli_opts` sağlayıcısında okunur ([`crate::ucli_opts::validate_opts`] çıktısı).
    pub cli_opts: Option<&'a Map<String, Value>>,
}

/// Sağlayıcı işlemlerinin bağlamı.
pub struct Providers<'a> {
    pub settings: &'a Settings,
    pub catalog: &'a ModelCatalog,
    pub paths: &'a Paths,
    pub probe: &'a dyn Probe,
}

/// PATH'te yoksa bakılan bilinen kurulum konumları (yalnız claude).
const CLAUDE_KNOWN_PATHS: [&str; 6] = [
    "~/cc/node_modules/@anthropic-ai/claude-code/bin/claude.exe",
    "~/cc/node_modules/.bin/claude",
    "~/.local/bin/claude",
    "~/.claude/local/claude",
    "~/.npm-global/bin/claude",
    "/usr/local/bin/claude",
];

impl Providers<'_> {
    pub(crate) fn expand_user(&self, path: &str) -> String {
        match path.strip_prefix('~') {
            Some(rest) if rest.is_empty() || rest.starts_with('/') => format!("{}{rest}", self.paths.home),
            _ => path.to_string(),
        }
    }

    /// `resolved_binary`: ayardaki override -> PATH -> bilinen konumlar -> çıplak ad.
    pub fn resolved_binary(&self, cli_name: &str) -> String {
        let over = self.settings.provider_bin(cli_name);
        if !over.is_empty() {
            let path = self.expand_user(&over);
            if self.probe.is_executable_file(&path) {
                return path;
            }
        }
        if let Some(found) = self.probe.which(cli_name) {
            return found;
        }
        if cli_name == "claude" {
            for cand in CLAUDE_KNOWN_PATHS {
                let path = self.expand_user(cand);
                if self.probe.is_executable_file(&path) {
                    return path;
                }
            }
        }
        cli_name.to_string()
    }

    pub fn model_choices(&self, cli: Cli) -> Vec<String> {
        let fixed = |l: &[&str]| l.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        match cli {
            Cli::Claude => claude::model_choices(self.catalog.claude_state.as_ref()),
            Cli::Agy => self.catalog.agy_models.clone(),
            Cli::Codex => codex::model_choices(self.catalog.codex_cache.as_ref()),
            Cli::Copilot => fixed(&copilot::MODEL_CHOICES),
            Cli::Shell => fixed(&shell::SENTINEL),
            Cli::Ucli => self.catalog.ucli.choices(),
        }
    }

    /// Model için KESİN bilinen effort seviyeleri; None = bilgi yok.
    pub fn model_effort_levels(&self, cli: Cli, model: &str) -> Option<Vec<String>> {
        match cli {
            Cli::Agy => agy::model_effort_levels(model, &self.catalog.agy_models),
            Cli::Codex => codex::model_effort_levels(model, self.catalog.codex_cache.as_ref()),
            _ => None,
        }
    }

    pub fn effort_levels_for(&self, cli: Cli, model: &str) -> Vec<String> {
        self.model_effort_levels(cli, model)
            .unwrap_or_else(|| cli.effort_levels().iter().map(|s| s.to_string()).collect())
    }

    /// spawn'da gerçekten gönderilecek effort.
    pub fn resolve_effort(&self, cli: Cli, model: &str, requested: &str) -> String {
        self.model_effort_levels(cli, model)
            .and_then(|known| nearest_effort(requested, &known))
            .unwrap_or_else(|| requested.to_string())
    }

    pub fn preferred_default_model(&self, cli: Cli) -> Option<String> {
        match cli {
            Cli::Claude => claude::newest_sonnet(&self.model_choices(cli)),
            _ => None,
        }
    }

    /// Ayar (listede geçerliyse) -> sağlayıcı tercihi -> listenin ilki -> "".
    pub fn default_model_for(&self, cli: Cli) -> String {
        let choices = self.model_choices(cli);
        let over = self.settings.per_cli("default_model", cli.name());
        if choices.contains(&over) {
            return over;
        }
        match self.preferred_default_model(cli) {
            Some(p) if choices.contains(&p) => p,
            _ => choices.first().cloned().unwrap_or_default(),
        }
    }

    pub fn default_effort_for(&self, cli: Cli) -> String {
        let over = self.settings.per_cli("default_effort", cli.name());
        if cli.effort_levels().contains(&over.as_str()) {
            over
        } else {
            cli.default_effort().to_string()
        }
    }

    pub fn refresh_stored_model(&self, cli: Cli, stored: &str) -> String {
        match cli {
            Cli::Claude => claude::refresh_stored_model(stored, &self.model_choices(cli)),
            _ => stored.to_string(),
        }
    }

    pub fn resolved_model_for(&self, cli: Cli, stored: &str) -> String {
        if stored.is_empty() {
            self.default_model_for(cli)
        } else {
            self.refresh_stored_model(cli, stored)
        }
    }

    /// Çağrı başına MCP bağlama argv'si (boş = bu CLI'da yok ya da kurulamadı).
    pub fn mcp_launch_args(&self, cli: Cli, spec: &McpSpec, cwd: &str, out: &mut BuildOutput) -> Vec<String> {
        match cli {
            Cli::Claude => claude::mcp_launch_args(self, spec, out),
            Cli::Codex => codex::mcp_launch_args(spec),
            Cli::Ucli => ucli::mcp_launch_args(self, spec, cwd, out),
            _ => Vec::new(),
        }
    }

    /// `CliProvider.validate_cli_opts`: ham başlat penceresi seçenekleri -> temiz sözlük ya da hata metni. ucli dışındaki
    /// sağlayıcı dolu girdiyi reddeder.
    pub fn validate_cli_opts(&self, cli: Cli, raw: &Value) -> Result<Map<String, Value>, String> {
        if cli.accepts_cli_opts() {
            return crate::ucli_opts::validate_opts(raw, self.settings, &|| self.probe.rust_toolchain());
        }
        if crate::pyfmt::truthy(raw) {
            Err(format!("{}: başlatma seçeneği desteklenmiyor", cli.name()))
        } else {
            Ok(Map::new())
        }
    }

    /// Kalıcı kayıt ipucu (yalnız agy); çalıştırılmaz.
    pub fn mcp_setup_command(&self, cli: Cli, spec: &McpSpec) -> Option<String> {
        (cli == Cli::Agy).then(|| agy::mcp_setup_command(spec))
    }

    /// Tek seferlik araçsız çağrı argv'si (yalnız claude).
    pub fn oneshot_argv(&self, cli: Cli, prompt: &str, model: Option<&str>) -> Option<Vec<String>> {
        (cli == Cli::Claude).then(|| claude::oneshot_argv(self, prompt, model))
    }

    /// `<binary> ...` çağrısı (`cd` ve ortam öneki olmadan).
    pub fn build_inner_command(
        &self,
        cli: Cli,
        args: &BuildArgs<'_>,
        out: &mut BuildOutput,
    ) -> Result<String, SpawnError> {
        Ok(match cli {
            Cli::Claude => claude::build_inner_command(self, args, out),
            Cli::Agy => agy::build_inner_command(self, args),
            Cli::Codex => codex::build_inner_command(self, args),
            Cli::Copilot => copilot::build_inner_command(self, args, out),
            Cli::Shell => shell::build_inner_command(),
            Cli::Ucli => return ucli::build_inner_command(self, args, out),
        })
    }
}

/// Sahip kuralı: değnekçinin açtığı claude ana oturumu hep en yeni Sonnet + `medium`.
pub fn main_session_model_effort(model: &str, effort: &str, cli: &str, sonnet: &str) -> (String, String) {
    let m = crate::pyfmt::strip(model);
    let claude_model = m.to_lowercase().starts_with("claude");
    let is_claude = cli == "claude" || (cli.is_empty() && claude_model);
    if !is_claude || sonnet.is_empty() || (!m.is_empty() && !claude_model) {
        (model.to_string(), effort.to_string())
    } else {
        (sonnet.to_string(), "medium".to_string())
    }
}
