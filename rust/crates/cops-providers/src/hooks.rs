//! Spawn yolundaki kanca çağrılarının sözleşmesi: çok kullanıcı kancası (`authz.spawn_env`) ve eklenti MCP'si
//! (`extensions.session_mcp_spec` + `mcp_ext.default_spec`).
//!
//! Kanca KAYITLARI (kim, ne zaman kaydeder) bu crate'te değil: çağıran süreç [`Hooks`]u kurar. Burada yalnız Python'un
//! çağrı anlamı vardır: kanca yoksa boş; ret aynen; başka hata = günlük + `hook_error` reddi (kapalı yön); eklenti
//! koşulunun hatası yutulur (spawn engellenmez).

use crate::probe::BuildOutput;
use crate::provider::McpSpec;
use crate::pyfmt::join_path;
use serde_json::json;
use std::fmt;

/// Python `authz.SpawnRefused` (bir `ValueError`): oturum başlatılamaz. `reason` kısa makine kodu.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SpawnRefused {
    pub reason: String,
    pub detail: String,
}

impl fmt::Display for SpawnRefused {
    /// `str(SpawnRefused)`: `reason: detail`, ayrıntı yoksa yalnız `reason`.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.detail.is_empty() {
            f.write_str(&self.reason)
        } else {
            write!(f, "{}: {}", self.reason, self.detail)
        }
    }
}

/// Kanca işlevinin hatası.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HookFailure {
    /// Kanca bilerek reddetti (aynen yükselir).
    Refused(SpawnRefused),
    /// Beklenmeyen hata: `class` = Python `type(e).__name__`, `message` = `str(e)`.
    Error { class: String, message: String },
}

/// Çok kullanıcı kancası: `(cli, ad, cwd) -> {ORTAM: değer}`. Kimlik (principal) kapanışta taşınır.
pub type SpawnHookFn =
    dyn Fn(&str, &str, &str) -> Result<Vec<(String, String)>, HookFailure> + Send + Sync;

/// Eklenti MCP koşulu: `cwd` bu eklentiye ait mi (hata = bu eklenti atlanır).
pub type CwdPredicate = dyn Fn(&str) -> Result<bool, String> + Send + Sync;

/// `extensions._SESSION_MCP` girdisi (kayıt sırası korunur) ve sunucunun araç adları (`_MCP[sid]["tools"]`).
pub struct SessionMcpEntry {
    pub server_id: String,
    pub matches: Box<CwdPredicate>,
    /// `None` = sunucu kayıtlı değil (Python `{"tools": []}`); `Err` = araç listesi okunamadı (bu eklenti atlanır).
    pub tools: Option<Result<Vec<String>, String>>,
}

/// `authz.spawn_env`: kanca yoksa boş. Dönüş Python `dict` gibi tekilleştirilir (aynı ad: ilk konumda son değer).
/// Beklenmeyen hata `authz_spawn_hook_failed` günlüğü + `SpawnRefused("hook_error")`.
pub fn spawn_env(
    hook: Option<&SpawnHookFn>,
    cli: &str,
    name: &str,
    cwd: &str,
    out: &mut BuildOutput,
) -> Result<Vec<(String, String)>, SpawnRefused> {
    let Some(hook) = hook else {
        return Ok(Vec::new());
    };
    match hook(cli, name, cwd) {
        Ok(env) => {
            let mut dict: Vec<(String, String)> = Vec::with_capacity(env.len());
            for (k, v) in env {
                match dict.iter_mut().find(|(have, _)| *have == k) {
                    Some(slot) => slot.1 = v,
                    None => dict.push((k, v)),
                }
            }
            Ok(dict)
        }
        Err(HookFailure::Refused(r)) => Err(r),
        Err(HookFailure::Error { class, message }) => {
            let text: String = format!("{class}: {message}").chars().take(200).collect();
            out.diag(
                "authz_spawn_hook_failed",
                vec![("error", json!(text)), ("cli", json!(cli))],
            );
            Err(SpawnRefused {
                reason: "hook_error".into(),
                detail: String::new(),
            })
        }
    }
}

/// `mcp_ext.default_spec(sid)`: `cops-ext-<sid>`, `<depo>/py/cops mcp-ext <sid>`, araç adları izin listesi.
pub fn default_spec(server_id: &str, tools: Vec<String>, repo_dir: &str) -> McpSpec {
    McpSpec {
        name: format!("cops-ext-{server_id}"),
        command: join_path(&join_path(repo_dir, "py"), "cops"),
        args: vec!["mcp-ext".into(), server_id.into()],
        allowed_tools: tools,
    }
}

/// `extensions.session_mcp_spec(cwd)`: koşulu tutan İLK eklentinin spec'i; koşul ya da araç listesi hatası o eklentiyi
/// atlar (istisna sızmaz).
pub fn session_mcp_spec(entries: &[SessionMcpEntry], repo_dir: &str, cwd: &str) -> Option<McpSpec> {
    entries.iter().find_map(|e| match (e.matches)(cwd) {
        Ok(true) => match &e.tools {
            None => Some(default_spec(&e.server_id, Vec::new(), repo_dir)),
            Some(Ok(tools)) => Some(default_spec(&e.server_id, tools.clone(), repo_dir)),
            Some(Err(_)) => None,
        },
        Ok(false) | Err(_) => None,
    })
}

/// Spawn yürütücüsünün kanca sınırı ([`crate::spawn_exec::spawn_session`]).
pub trait SpawnHooks {
    /// `authz.spawn_env`. `dry_run` Python'da YOK (kanca kuru koşuyu bilmez, TODO "spawn kancası kuru koşuda da
    /// yazıyor"); uygulayıcı bugün yok saymalıdır.
    fn spawn_env(
        &self,
        cli: &str,
        name: &str,
        cwd: &str,
        dry_run: bool,
        out: &mut BuildOutput,
    ) -> Result<Vec<(String, String)>, SpawnRefused>;
    /// `extensions.session_mcp_spec(cwd)`.
    fn session_mcp(&self, cwd: &str) -> Option<McpSpec>;
}

/// Kayıtlı kancalar (OSS'te ikisi de boş: davranış kancasız Python ile aynı).
#[derive(Default)]
pub struct Hooks {
    pub spawn_hook: Option<Box<SpawnHookFn>>,
    pub session_mcp: Vec<SessionMcpEntry>,
    /// `mcp_ext.default_spec`in `REPO_DIR`i.
    pub repo_dir: String,
}

impl SpawnHooks for Hooks {
    fn spawn_env(
        &self,
        cli: &str,
        name: &str,
        cwd: &str,
        _dry_run: bool,
        out: &mut BuildOutput,
    ) -> Result<Vec<(String, String)>, SpawnRefused> {
        spawn_env(self.spawn_hook.as_deref(), cli, name, cwd, out)
    }
    fn session_mcp(&self, cwd: &str) -> Option<McpSpec> {
        session_mcp_spec(&self.session_mcp, &self.repo_dir, cwd)
    }
}
