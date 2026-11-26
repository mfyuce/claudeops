//! CLI sağlayıcıları (claude, agy, codex, copilot, ucli, shell): spawn komut satırı ve ortam kurulumu.
//!
//! `py/claudeops/providers/` + `spawn.py` + `routing.py` karşılığı. Crate SAF: süreç başlatmaz, dosyaya dokunmaz, ağa
//! çıkmaz. Dış olgular [`Probe`] ile içeri gelir, yazma/silme istekleri [`Effect`] listesi olarak dışarı döner;
//! ikisini de çağıran uygular. Doğruluk ölçütü Python ile paritedir (`tests/parity.rs`).

pub mod agy;
pub mod agy_resume;
pub mod bg_work;
pub mod chat;
pub mod claude;
pub mod claude_resume;
pub mod claude_transcript;
pub mod codex;
pub mod codex_resume;
pub mod copilot;
pub mod effort;
pub mod live;
pub mod model_sources;
pub mod ojson;
pub mod probe;
pub mod pyfmt;
pub mod pyjson;
pub mod provider;
pub mod py_re;
pub mod resume;
pub mod routing;
pub mod settings;
pub mod shell;
pub mod spawn;
pub mod ucli;
pub mod ucli_opts;
pub mod ucli_status;
pub mod usage;

pub use chat::{ChatTurn, Exchange};
pub use probe::{BuildOutput, Diag, Effect, McpRegisterError, Paths, Probe, SpawnError};
pub use provider::{BuildArgs, Cli, McpSpec, ModelCatalog, Providers};
pub use agy_resume::AgySidStore;
pub use claude_resume::MetaCache;
pub use live::{FileStat, Live, LiveProbe, SqlCell};
pub use resume::{ids_held_by_others, LiveSession};
pub use model_sources::{HttpRequest, ModelIo, ModelSources, RunRequest, SecretValue};
pub use settings::Settings;
