//! Dış dünya ile sınır: crate'in okuduğu olgular ([`Probe`]), istediği yan etkiler ([`Effect`]) ve sabit yollar.

use crate::ucli_opts::Toolchain;
use serde_json::Value;
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
    /// copilot'un oturum deposu (`COPILOT_HOME`a bakmaz: Python `SESSION_STORE_DB`).
    pub fn copilot_session_db(&self) -> String {
        format!("{}/.copilot/session-store.db", self.home)
    }
    /// claude'un süreç kayıt dizini (`SESSIONS_DIR`; `<pid>.json`).
    pub fn claude_sessions_dir(&self) -> String {
        format!("{}/.claude/sessions", self.home)
    }
    /// agy'nin cwd -> konuşma kimliği önbelleği (`CONVERSATIONS_CACHE`).
    pub fn agy_conversations_cache(&self) -> String {
        format!("{}/.gemini/antigravity-cli/cache/last_conversations.json", self.home)
    }
    /// codex rollout arşivi (`CODEX_HOME`a bakmaz: Python `SESSIONS_DIR`).
    pub fn codex_sessions_dir(&self) -> String {
        format!("{}/.codex/sessions", self.home)
    }
    /// agy konuşma veritabanları (`CONVERSATIONS_DIR`).
    pub fn agy_conversations_dir(&self) -> String {
        format!("{}/.gemini/antigravity-cli/conversations", self.home)
    }
    /// `CODEX_HOME` (ortamdaki `CODEX_HOME`a bakmaz: Python sabiti).
    pub fn codex_home(&self) -> String {
        format!("{}/.codex", self.home)
    }
    /// `MODELS_CACHE`.
    pub fn codex_models_cache(&self) -> String {
        format!("{}/models_cache.json", self.codex_home())
    }
    /// `CLAUDE_MODELS_JSON` (`claude_models` belgesinin dosya yolu; okuma [`crate::ModelIo::claude_models_doc`]).
    pub fn claude_models_json(&self) -> String {
        format!("{}/claude_models.json", self.claudeops_dir)
    }
    pub fn ucli_metrics_dir(&self) -> String {
        format!("{}/ucli_metrics", self.claudeops_dir)
    }
    /// `ucli_agents.token_file(session)`.
    pub fn ucli_agent_token_file(&self, session: &str) -> String {
        format!("{}/ucli_agent_tokens/{session}", self.claudeops_dir)
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
    /// Python `open(path, encoding="utf-8").read()`: evrensel satır sonu (`\r\n`, `\r` -> `\n`); yoksa ya da UTF-8 değilse
    /// None (Python'da bozuk UTF-8 bazı yollarda istisnadır, bkz. parite raporu).
    fn read_text(&self, path: &str) -> Option<String>;
    /// `os.path.realpath` (strict DEĞİL): göreli yol çağıranın çalışma dizinine göre mutlaklaşır, var olmayan parçalar
    /// normalleştirilerek korunur (`/a/b/` -> `/a/b`, `..` düşer). "Çözülemezse girdi" DEĞİL: `ucli` durum dizini adı ve
    /// özeti bu çıktıdan hesaplanır.
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
    /// Yönetilen yerel SearXNG adresi (hazır değilse None; spawn BEKLEMEZ). `preview` (kuru çalıştırma): docker'a
    /// dokunulmaz, kurulum/başlatma tetiklenmez; yalnız ŞU AN cevap veren adres döner.
    fn searxng_url(&self, session: &str, preview: bool) -> Option<String>;
    /// `ucli_checks` kayıt dosyasını yükle/denetle (hata metni).
    fn checks_registry(&self, path: &str) -> Result<(), String>;
    /// Günlük USD tavanı + başlatma payı ayırma; aşıldıysa hata metni.
    fn claude_cost_gate(&self, session: &str) -> Result<(), String>;
    /// Alt ajan token'ı üret (0600 dosya); dönen DOSYA YOLU. Token'ın kendisi hiçbir zaman dönmez.
    fn issue_agent_token(&self, session: &str) -> Result<String, String>;
    /// Panelin loopback portu (bilinmiyorsa None).
    fn panel_port(&self) -> Option<u16>;
    /// ucli MCP kaydı: `config_path` (`os.path.lexists` ise) silinir, `argv` `cwd`de çalıştırılır (20 sn). Günlük olaylarını
    /// crate yazar (Python `register_mcp` ile aynı alanlar).
    fn register_mcp(&self, cwd: &str, config_path: &str, argv: &[String]) -> Result<(), McpRegisterError>;
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
    /// `chmod(path, 0o700)` (var olan dizinin izni de daraltılır).
    ChmodPrivate { path: String },
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
            Effect::ChmodPrivate { path } => write!(f, "ChmodPrivate({path})"),
        }
    }
}

/// [`Probe::register_mcp`] hatası. Metinler Python `repr(e)` biçimindedir (`OSError('...')`), günlüğe aynen gider.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum McpRegisterError {
    /// Eski kayıt dosyası silinemedi.
    Unlink(String),
    /// Süreç başlatılamadı / zaman aşımı.
    Spawn(String),
    /// Sıfır olmayan çıkış.
    Exit { rc: i32, stdout: String, stderr: String },
}

/// `diag_log(event, **alanlar)` karşılığı; çağıran günlüğe yazar. Alan sırası ve JSON tipi Python'daki gibidir (bool, sayı,
/// liste metne çevrilmez).
#[derive(Debug, Clone, PartialEq)]
pub struct Diag {
    pub event: &'static str,
    pub fields: Vec<(&'static str, Value)>,
}

/// Komut kurulumunda biriken yan etkiler ve günlük olayları.
#[derive(Debug, Default)]
pub struct BuildOutput {
    /// Kuru çalıştırma: durum değiştiren [`Probe`] çağrıları yapılmaz (`claude_cost_gate` hariç: payı yalnız bellekte
    /// ayırır, Python gibi). Biriken `effects`/`diags` çağıran tarafından UYGULANMAZ ([`crate::spawn::plan_spawn`]
    /// kendi eklediklerini atar).
    pub dry_run: bool,
    pub effects: Vec<Effect>,
    pub diags: Vec<Diag>,
}

impl BuildOutput {
    pub(crate) fn diag(&mut self, event: &'static str, fields: Vec<(&'static str, Value)>) {
        self.diags.push(Diag { event, fields });
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
