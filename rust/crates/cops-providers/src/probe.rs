//! Dış dünya ile sınır: crate'in okuduğu olgular ([`Probe`]), istediği yan etkiler ([`Effect`]) ve sabit yollar.

use crate::ucli_opts::Toolchain;
use std::fmt;

/// Çağıranın verdiği sabit yollar. `home_state` Python'da `CLAUDEOPS_DIR`den BAĞIMSIZ olan dosyaların tabanıdır
/// (`<home>/.claude/claudeops`: anahtar dosyaları, `ucli_usage`, `ucli-state`).
#[derive(Debug, Clone)]
pub struct Paths {
    pub claudeops_dir: String,
    pub home: String,
    /// claudeops deposunun kökü (`bin/ucli`, `py/cops`).
    pub repo_dir: String,
}

impl Paths {
    fn home_state(&self) -> String {
        format!("{}/.claude/claudeops", self.home)
    }
    pub fn ucli_key_file(&self, service: &str) -> String {
        let name = if service.is_empty() { "ucli_api_key".to_string() } else { format!("ucli_key_{service}") };
        format!("{}/{name}", self.home_state())
    }
    pub fn copilot_env_file(&self) -> String {
        format!("{}/copilot_byok_env", self.home_state())
    }
    pub fn ucli_usage_dir(&self) -> String {
        format!("{}/ucli_usage", self.home_state())
    }
    pub fn ucli_state_root(&self) -> String {
        format!("{}/ucli-state", self.home_state())
    }
    pub fn ucli_metrics_dir(&self) -> String {
        format!("{}/ucli_metrics", self.claudeops_dir)
    }
    pub fn ucli_ask_root(&self) -> String {
        format!("{}/ucli_ask", self.claudeops_dir)
    }
    pub fn ucli_checks_root(&self) -> String {
        format!("{}/ucli_checks", self.claudeops_dir)
    }
    pub fn mcp_config(&self) -> String {
        format!("{}/orchestration/mcp_config.json", self.claudeops_dir)
    }
    pub fn routing_bundled(&self) -> String {
        format!("{}/py/claudeops/data/routing.md", self.repo_dir)
    }
    pub fn routing_override(&self) -> String {
        format!("{}/routing-guidance.md", self.claudeops_dir)
    }
}

/// Komut kurulurken okunan olgular. Uygulama G/Ç yapar; crate yapmaz.
///
/// İki yöntem durum değiştirir ([`Probe::claude_cost_gate`], [`Probe::issue_agent_token`], [`Probe::register_mcp`]):
/// sonuçları komutu etkilediği için [`Effect`] olamazlar.
pub trait Probe {
    fn is_file(&self, path: &str) -> bool;
    fn is_dir(&self, path: &str) -> bool;
    fn exists(&self, path: &str) -> bool;
    fn is_symlink(&self, path: &str) -> bool;
    /// Normal dosya VE çalıştırılabilir.
    fn is_executable_file(&self, path: &str) -> bool;
    fn file_size(&self, path: &str) -> Option<u64>;
    fn read_text(&self, path: &str) -> Option<String>;
    /// `os.path.realpath` (çözülemezse girdi).
    fn realpath(&self, path: &str) -> String;
    fn which(&self, name: &str) -> Option<String>;
    fn env_var(&self, name: &str) -> Option<String>;
    /// `<binary> --help` (stdout+stderr), çalıştırılamazsa "".
    fn claude_help(&self, binary: &str) -> String;
    /// `<binary> chat --help` (stdout+stderr), çalıştırılamazsa "".
    fn ucli_chat_help(&self, binary: &str) -> String;
    /// PATH'teki çalıştırılabilir adlar (sıralı, tekrarsız).
    fn path_executables(&self) -> Vec<String>;
    /// `~/.rustup/toolchains` altındaki seçilmiş araç zinciri.
    fn rust_toolchain(&self) -> Result<Toolchain, String>;
    /// Yönetilen yerel SearXNG adresi (hazır değilse None; spawn BEKLEMEZ).
    fn searxng_url(&self, session: &str) -> Option<String>;
    /// `ucli_checks` kayıt dosyasını yükle/denetle (hata metni).
    fn checks_registry(&self, path: &str) -> Result<(), String>;
    /// Günlük USD tavanı + başlatma payı ayırma; aşıldıysa hata metni.
    fn claude_cost_gate(&self, session: &str) -> Result<(), String>;
    /// Alt ajan token'ı üret (0600 dosya); dönen DOSYA YOLU. Token'ın kendisi hiçbir zaman dönmez.
    fn issue_agent_token(&self, session: &str) -> Result<String, String>;
    /// Panelin loopback portu (bilinmiyorsa None).
    fn panel_port(&self) -> Option<u16>;
    /// ucli MCP kaydı: `config_path` silinir, `argv` `cwd`de çalıştırılır; başarı = true.
    fn register_mcp(&self, cwd: &str, config_path: &str, argv: &[String]) -> bool;
}

/// Komuttan ÖNCE çağıranın uygulaması gereken dosya işlemleri (verilen sırayla).
#[derive(Clone, PartialEq, Eq)]
pub enum Effect {
    /// 0600, `O_NOFOLLOW`, kırp-yaz; var olan dosyanın izni de 0600'e çekilir. İçerik SIR olabilir.
    WriteSecret { path: String, content: String },
    /// Atomik yazım; var olan dosyanın izni korunur (symlink ise hedefi yazılır).
    WriteAtomic { path: String, content: String },
    /// Boş damga dosyası (0600, `O_NOFOLLOW`, kırp).
    Touch { path: String },
    Remove { path: String },
    /// `makedirs(mode=0700, exist_ok=True)`.
    MkdirPrivate { path: String },
}

impl fmt::Debug for Effect {
    /// Sır içeriği hiçbir günlüğe basılmaz.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Effect::WriteSecret { path, .. } => write!(f, "WriteSecret({path}, <redacted>)"),
            Effect::WriteAtomic { path, .. } => write!(f, "WriteAtomic({path})"),
            Effect::Touch { path } => write!(f, "Touch({path})"),
            Effect::Remove { path } => write!(f, "Remove({path})"),
            Effect::MkdirPrivate { path } => write!(f, "MkdirPrivate({path})"),
        }
    }
}

/// `diag_log(event, ...)` karşılığı; çağıran günlüğe yazar.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Diag {
    pub event: &'static str,
    pub fields: Vec<(&'static str, String)>,
}

/// Komut kurulumunda biriken yan etkiler ve günlük olayları.
#[derive(Debug, Default)]
pub struct BuildOutput {
    pub effects: Vec<Effect>,
    pub diags: Vec<Diag>,
}

impl BuildOutput {
    pub(crate) fn diag(&mut self, event: &'static str, fields: &[(&'static str, &str)]) {
        self.diags.push(Diag { event, fields: fields.iter().map(|(k, v)| (*k, v.to_string())).collect() });
    }
}

/// Spawn reddi (Python `ValueError` / `UcliError`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SpawnError(pub String);

impl fmt::Display for SpawnError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for SpawnError {}
