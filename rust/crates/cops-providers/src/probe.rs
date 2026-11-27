//! Dış dünya ile sınır: crate'in okuduğu olgular ([`Probe`]), istediği yan etkiler ([`Effect`]) ve sabit yollar.

use crate::cost::CostRefusal;
use crate::pyfmt::{abspath, join_path, relpath};
use crate::real::effects::EffectError;
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
        let name = if service.is_empty() {
            "ucli_api_key".to_string()
        } else {
            format!("ucli_key_{service}")
        };
        format!("{}/{name}", self.home_state())
    }
    pub fn copilot_env_file(&self) -> String {
        format!("{}/copilot_byok_env", self.home_state())
    }
    /// `settings.SETTINGS_JSON`.
    pub fn settings_json(&self) -> String {
        format!("{}/settings.json", self.claudeops_dir)
    }
    pub fn ucli_usage_dir(&self) -> String {
        format!("{}/ucli_usage", self.home_state())
    }
    pub fn ucli_state_root(&self) -> String {
        format!("{}/ucli-state", self.home_state())
    }
    /// `paths.shared_write_allowed` (TBD#412 b): ortak kök (`<home>/.claude/claudeops`) altındaki yol bu süreçte
    /// yazılıp silinebilir mi. `claudeops_dir` başka dizini gösteriyorsa (ikinci örnek) HAYIR; kök dışı yol serbest.
    /// Sözcüksel ya da çözülmüş yol kökteyse ortaktır.
    pub fn shared_write_allowed(&self, path: &str, realpath: &dyn Fn(&str) -> String) -> bool {
        let shared = self.home_state();
        if realpath(&self.claudeops_dir) == realpath(&shared) {
            return true;
        }
        let inside = |root: String, p: String| {
            p == root || p.strip_prefix(&root).is_some_and(|r| r.starts_with('/'))
        };
        !(inside(abspath(&shared, "/"), abspath(path, "/"))
            || inside(realpath(&shared), realpath(path)))
    }
    /// `ucli_provider._service_key_file`: hizmet anahtarının yazılıp okunduğu dosya. Ortak dosya salt okunursa (ikinci
    /// örnek) aynı adla `claudeops_dir` altında: deneme anahtarı canlınınkini ezmez (TBD#417 S6).
    pub fn service_key_file(&self, service: &str, realpath: &dyn Fn(&str) -> String) -> String {
        let shared = self.ucli_key_file(service);
        if self.shared_write_allowed(&shared, realpath) {
            return shared;
        }
        let name = shared.rsplit('/').next().unwrap_or_default();
        join_path(&self.claudeops_dir, name)
    }
    /// `ucli_cost.write_dir(base)`: günlüğün YAZILACAĞI dizin; ortak dizin salt okunursa `claudeops_dir` altındaki eşi.
    pub fn usage_write_dir(&self, base: &str, realpath: &dyn Fn(&str) -> String) -> String {
        if self.shared_write_allowed(base, realpath) {
            return base.to_string();
        }
        join_path(&self.claudeops_dir, &relpath(base, &self.home_state(), "/"))
    }
    /// `ucli_cost.read_dirs(base)`: ortak dizin, yazma başka yere gidiyorsa o da.
    pub fn usage_read_dirs(&self, base: &str, realpath: &dyn Fn(&str) -> String) -> Vec<String> {
        let own = self.usage_write_dir(base, realpath);
        if own == base {
            vec![own]
        } else {
            vec![base.to_string(), own]
        }
    }
    /// `ucli_client.state_dir_for`ın kök dizini: ucli bu dizine YAZAR.
    pub fn ucli_state_write_root(&self, realpath: &dyn Fn(&str) -> String) -> String {
        let shared = self.ucli_state_root();
        if self.shared_write_allowed(&shared, realpath) {
            shared
        } else {
            join_path(&self.claudeops_dir, "ucli-state")
        }
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
        format!(
            "{}/.gemini/antigravity-cli/cache/last_conversations.json",
            self.home
        )
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
        format!("{}/{session}", self.ucli_agent_token_dir())
    }
    pub fn ucli_ask_root(&self) -> String {
        format!("{}/ucli_ask", self.claudeops_dir)
    }
    /// `ucli_approval.ROOT`.
    pub fn ucli_approval_root(&self) -> String {
        format!("{}/ucli_approval", self.claudeops_dir)
    }
    /// `AGY_SIDS_JSON`.
    pub fn agy_sids_json(&self) -> String {
        format!("{}/agy_sids.json", self.claudeops_dir)
    }
    /// `ucli_agents.STATE_FILE`.
    pub fn ucli_agents_json(&self) -> String {
        format!("{}/ucli_agents.json", self.claudeops_dir)
    }
    /// `ucli_agents.TOKEN_DIR`.
    pub fn ucli_agent_token_dir(&self) -> String {
        format!("{}/ucli_agent_tokens", self.claudeops_dir)
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
    /// `routing.CODEX_AGENTS` (`~/.codex/AGENTS.md`; `CODEX_HOME`a bakmaz).
    pub fn codex_agents_md(&self) -> String {
        format!("{}/.codex/AGENTS.md", self.home)
    }
    /// `routing.AGY_GEMINI` (`~/.gemini/GEMINI.md`).
    pub fn agy_gemini_md(&self) -> String {
        format!("{}/.gemini/GEMINI.md", self.home)
    }
}

/// Komut kurulurken okunan olgular. Uygulama G/Ç yapar; crate yapmaz.
///
/// Dört yöntem durum değiştirir ([`Probe::claude_cost_gate`], [`Probe::issue_agent_token`], [`Probe::register_mcp`],
/// [`Probe::apply_now`]): sonuçları komutu etkilediği için [`Effect`] listesine bırakılamazlar.
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
    /// Günlük USD tavanı + başlatma payı ayırma; aşıldıysa ya da harcama sayılamıyorsa ret.
    fn claude_cost_gate(&self, session: &str) -> Result<(), CostRefusal>;
    /// Alt ajan token'ı üret (0600 dosya); dönen DOSYA YOLU. Token'ın kendisi hiçbir zaman dönmez.
    fn issue_agent_token(&self, session: &str) -> Result<String, String>;
    /// Panelin loopback portu (bilinmiyorsa None).
    fn panel_port(&self) -> Option<u16>;
    /// ucli MCP kaydı: `config_path` (`os.path.lexists` ise) silinir, `argv` `cwd`de çalıştırılır (20 sn). Günlük olaylarını
    /// crate yazar (Python `register_mcp` ile aynı alanlar). `Ok(true)`: kayıt başarılı ama çıktıda UTF-8 olmayan bayt
    /// vardı (U+FFFD); sonucu yalnız çıkış kodu belirler.
    fn register_mcp(
        &self,
        cwd: &str,
        config_path: &str,
        argv: &[String],
    ) -> Result<bool, McpRegisterError>;
    /// Başarısızlığı KOMUTU değiştiren yazımlar için yan etkiyi HEMEN uygula (Python'da bayrak yazım başarılıysa
    /// eklenir). Kuru çalıştırmada çağrılmaz; bekleyen yan etkiler bu yolla önceden uygulanıp listeden düşer. Gerçek uygulama: [`crate::real::effects::apply`].
    fn apply_now(&self, effect: &Effect) -> Result<(), EffectError>;
    /// S4 sır ortam dosyasının adındaki rastgele parça (Python `spawn._spawn_env_token`, 16 onaltılık karakter). Eşzamanlı
    /// açılışlar birbirinin dosyasını ezmesin diye her çağrıda farklı olmalı (yazım ayrıca `O_EXCL`). Gerçek:
    /// [`crate::real::effects::spawn_env_token`].
    fn spawn_env_token(&self) -> String;
}

/// Komuttan ÖNCE çağıranın uygulaması gereken dosya işlemleri (verilen sırayla).
#[derive(Clone, PartialEq, Eq)]
pub enum Effect {
    /// 0600, `O_NOFOLLOW`, kırp-yaz; var olan dosyanın izni de 0600'e çekilir. İçerik SIR olabilir.
    WriteSecret {
        path: String,
        content: String,
    },
    /// Atomik yazım; var olan dosyanın izni korunur (symlink ise hedefi yazılır).
    WriteAtomic {
        path: String,
        content: String,
    },
    /// Boş damga dosyası (0600, `O_NOFOLLOW`, kırp).
    Touch {
        path: String,
    },
    Remove {
        path: String,
    },
    /// `makedirs(mode=0700, exist_ok=True)`.
    MkdirPrivate {
        path: String,
    },
    /// `chmod(path, 0o700)` (var olan dizinin izni de daraltılır).
    ChmodPrivate {
        path: String,
    },
    /// S4 sır ortam dosyası `dir/file` (Python `spawn._write_spawn_env_file`): dizin 0700 (bağlantı, dizin olmayan ya da
    /// başkasına ait ise hata; grup/diğer izni daraltılır), eski artıklar silinir, dosya geçici adla `O_EXCL|O_NOFOLLOW`
    /// 0600 yazılıp var olanı EZMEDEN bağlanır. İçerik SIR. Uygulanamazsa spawn REDDEDİLİR (komut satırına düşülmez).
    WriteSpawnEnv {
        dir: String,
        file: String,
        content: String,
    },
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
            Effect::WriteSpawnEnv { dir, file, .. } => {
                write!(f, "WriteSpawnEnv({dir}/{file}, <redacted>)")
            }
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
    Exit {
        rc: i32,
        stdout: String,
        stderr: String,
    },
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
    /// Maliyet kapısı reddettiyse nedeni (`code` ve tutarlar: [`crate::cost::refusal`]).
    pub cost_refusal: Option<CostRefusal>,
}

impl BuildOutput {
    /// Başarısı komutu değiştiren yan etki: önce bekleyen [`Effect`]ler SIRAYLA uygulanır (Python'da yazımlar komut
    /// kurulurken olur), sonra `effect`. Bekleyen biri düşerse o ve sonrası listede KALIR (çağıran aynı hatayı alır,
    /// spawn düşer), `effect` denenmez: `Err(None)`. `effect`in kendisi düşerse `Err(Some(..))`. Kuru çalıştırmada
    /// hiçbir şey yapılmaz ve başarı sayılır.
    pub(crate) fn apply_now(
        &mut self,
        probe: &dyn Probe,
        effect: Effect,
    ) -> Result<(), Option<EffectError>> {
        if self.dry_run {
            return Ok(());
        }
        while let Some(first) = self.effects.first() {
            probe.apply_now(first).map_err(|_| None)?;
            self.effects.remove(0);
        }
        probe.apply_now(&effect).map_err(Some)
    }

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
