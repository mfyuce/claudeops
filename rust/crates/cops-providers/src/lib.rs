//! CLI sağlayıcıları (claude, agy, codex, copilot, ucli, shell): spawn komut satırı ve ortam kurulumu.
//!
//! `py/claudeops/providers/` + `spawn.py` + `routing.py` karşılığı. Crate SAF: süreç başlatmaz, dosyaya dokunmaz, ağa
//! çıkmaz. Dış olgular [`Probe`] ile içeri gelir, yazma/silme istekleri [`Effect`] listesi olarak dışarı döner;
//! ikisini de çağıran uygular. Doğruluk ölçütü Python ile paritedir (`tests/parity.rs`).

pub mod agy;
pub mod claude;
pub mod codex;
pub mod copilot;
pub mod effort;
pub mod ojson;
pub mod probe;
pub mod pyfmt;
pub mod provider;
pub mod py_re;
pub mod routing;
pub mod settings;
pub mod shell;
pub mod spawn;
pub mod ucli;
pub mod ucli_opts;

pub use probe::{BuildOutput, Diag, Effect, McpRegisterError, Paths, Probe, SpawnError};
pub use provider::{BuildArgs, Cli, McpSpec, ModelCatalog, Providers};
pub use settings::Settings;
