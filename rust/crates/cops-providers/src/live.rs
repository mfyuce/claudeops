//! Canlı durum okuyucuları (`CliProvider.busy_status_pattern`, `background_work`, `live_*`). Crate yine G/Ç yapmaz:
//! dosya, dizin ve SQLite okuması [`LiveProbe`] ile çağırandadır.
//!
//! `None` her yerde "bilinmiyor" demektir; 0, `false` ya da boş listeyle karıştırılmaz.

use crate::bg_work::{self, Clock, TRANSCRIPT_TAIL_BYTES};
use crate::probe::{Paths, Probe};
use crate::provider::Cli;
use crate::pyfmt::{parse_int, splitlines};
use crate::pyjson::Py;
use crate::settings::Settings;
use crate::ucli_status::{FailedTurns, LivePhase, LiveUsage};

/// codex rollout dosyasının sonundan bağlam için okunan bayt.
pub const CODEX_CONTEXT_TAIL_BYTES: u64 = 262_144;

/// copilot oturum deposunda ana ajanın son isteğinin `input_tokens`ı (tek parametre: oturum kimliği).
pub const COPILOT_CONTEXT_SQL: &str = "SELECT input_tokens FROM assistant_usage_events WHERE session_id = ? AND agent_id IS NULL ORDER BY created_at DESC, turn_index DESC LIMIT 1";

/// SQLite hücresi (dinamik tipli).
#[derive(Debug, Clone, PartialEq)]
pub enum SqlCell {
    Null,
    Int(i64),
    Real(f64),
    Text(String),
    Blob(Vec<u8>),
}

/// Canlı okuyucuların dış olguları.
///
/// Uygulama sözleşmesi: yalnız NORMAL dosya okunur (FIFO/aygıt açılışta bloklamamalı); hata, `None`.
pub trait LiveProbe: Probe {
    /// Dosyanın tamamı; `max` bayttan büyükse None.
    fn read_bytes(&self, path: &str, max: u64) -> Option<Vec<u8>>;
    /// Dosyanın son en çok `max` baytı.
    fn read_tail(&self, path: &str, max: u64) -> Option<Vec<u8>>;
    /// `os.listdir` (UTF-8 olmayan adlar atlanabilir: hiçbir oturum adıyla eşleşemez).
    fn list_dir(&self, path: &str) -> Option<Vec<String>>;
    /// `claude_provider.jsonl_path_for(cwd, sid)` (transkript çözümü G1'in işi).
    fn claude_transcript(&self, cwd: &str, sid: Option<&str>) -> Option<String>;
    /// `CodexProvider._rollout_path(cwd, sid)` (G1).
    fn codex_rollout(&self, cwd: &str, sid: Option<&str>) -> Option<String>;
    /// `CopilotProvider.resolve_resume_id(cwd)` (G1).
    fn copilot_resume_id(&self, cwd: &str) -> Option<String>;
    /// `db` SALT OKUNUR (`mode=ro`, 2 sn meşgul beklemesi) açılır, tek parametreli sorgunun ilk satırının ilk hücresi;
    /// satır yoksa ya da SQLite hatasında None.
    fn sqlite_cell(&self, db: &str, sql: &str, param: &str) -> Option<SqlCell>;
}

/// Canlı okuma bağlamı.
pub struct Live<'a> {
    pub settings: &'a Settings,
    pub paths: &'a Paths,
    pub probe: &'a dyn LiveProbe,
    pub clock: Clock,
}

impl Cli {
    /// Oturum bir turu işlerken ekranda görünen metin (regex; `strip_ansi` uygulanmış ekrana `search`, büyük/küçük harf
    /// duyarlı). None = bu CLI'da ekran sinyali yok.
    pub fn busy_status_pattern(self) -> Option<&'static str> {
        match self {
            Cli::Claude => Some(crate::claude::BUSY_STATUS_PATTERN),
            Cli::Agy => Some(crate::agy::BUSY_STATUS_PATTERN),
            Cli::Codex => Some(crate::codex::BUSY_STATUS_PATTERN),
            Cli::Copilot => Some(crate::copilot::BUSY_STATUS_PATTERN),
            Cli::Ucli | Cli::Shell => None,
        }
    }
}

impl Live<'_> {
    /// Arka plan işi (kabuk işi, Monitor, alt ajan) sayısı. `pane_text`: ANSI'si ayıklanmış ekran.
    pub fn background_work(&self, cli: Cli, pane_text: &str, cwd: &str, sid: Option<&str>) -> Option<u64> {
        match cli {
            Cli::Claude => Some(match bg_work::screen_bg_count(pane_text) {
                0 => u64::from(self.transcript_pending_path(self.probe.claude_transcript(cwd, sid).as_deref())),
                n => n,
            }),
            Cli::Codex => {
                let lines = self.tail_lines(self.probe.codex_rollout(cwd, sid).as_deref());
                let agents = bg_work::codex_subagents_pending(lines.iter().map(String::as_str), self.clock);
                Some(bg_work::codex_screen_count(pane_text).saturating_add(agents))
            }
            Cli::Ucli => self.ucli_background_work(cwd, sid),
            Cli::Agy | Cli::Copilot | Cli::Shell => None,
        }
    }

    /// Yapılandırılmış meşgul bilgisi (ekran regex'inden önce denenir).
    pub fn live_busy(&self, cli: Cli, cwd: &str, sid: Option<&str>) -> Option<bool> {
        match cli {
            Cli::Ucli => self.ucli_busy(cwd, sid),
            _ => None,
        }
    }

    /// Modele sunulan araç adları.
    pub fn live_tools(&self, cli: Cli, cwd: &str, sid: Option<&str>) -> Option<Vec<String>> {
        match cli {
            Cli::Ucli => self.ucli_tools(cwd, sid),
            _ => None,
        }
    }

    /// Güncel bağlam boyutu (token). claude'un okuyucusu burada değil (`web_steward.context_tokens_for`).
    pub fn live_context(&self, cli: Cli, cwd: &str, sid: Option<&str>) -> Option<i64> {
        match cli {
            Cli::Codex => self.codex_context(cwd, sid),
            Cli::Copilot => self.copilot_context(cwd, sid),
            Cli::Ucli => self.ucli_context(cwd, sid).map(|t| i64::try_from(t).unwrap_or(i64::MAX)),
            Cli::Claude | Cli::Agy | Cli::Shell => None,
        }
    }

    pub fn live_usage(&self, cli: Cli, cwd: &str, sid: Option<&str>) -> Option<LiveUsage> {
        match cli {
            Cli::Ucli => self.ucli_usage(cwd, sid),
            _ => None,
        }
    }

    pub fn live_failed_turns(&self, cli: Cli, cwd: &str, sid: Option<&str>) -> Option<FailedTurns> {
        match cli {
            Cli::Ucli => self.ucli_failed_turns(cwd, sid),
            _ => None,
        }
    }

    pub fn live_phase(&self, cli: Cli, cwd: &str, sid: Option<&str>) -> Option<LivePhase> {
        match cli {
            Cli::Ucli => self.ucli_phase(cwd, sid),
            _ => None,
        }
    }

    /// Dosyanın son [`TRANSCRIPT_TAIL_BYTES`] baytının satırları; okunamazsa boş.
    pub fn tail_lines(&self, path: Option<&str>) -> Vec<String> {
        path.filter(|p| !p.is_empty() && self.probe.is_file(p))
            .and_then(|p| self.probe.read_tail(p, TRANSCRIPT_TAIL_BYTES))
            .map(|data| bg_work::decode_lines(&data))
            .unwrap_or_default()
    }

    /// Dosya kuyruğunda bildirimi gelmemiş iş var mı; okunamazsa `false`.
    pub fn transcript_pending_path(&self, path: Option<&str>) -> bool {
        let lines = self.tail_lines(path);
        bg_work::transcript_pending(lines.iter().map(String::as_str), self.clock)
    }

    /// Son `token_count` olayının `last_token_usage.input_tokens`ı (0 = bilinmiyor). Boolean değer sayı sayılmaz
    /// (Python `True` döndürür).
    fn codex_context(&self, cwd: &str, sid: Option<&str>) -> Option<i64> {
        let path = self.probe.codex_rollout(cwd, sid).filter(|p| !p.is_empty())?;
        let data = self.probe.read_tail(&path, CODEX_CONTEXT_TAIL_BYTES)?;
        let tail = String::from_utf8_lossy(&data);
        for raw in splitlines(&tail).into_iter().rev() {
            if !raw.contains("\"token_count\"") {
                continue;
            }
            let Some(o) = Py::parse(raw) else { continue };
            let tokens = o
                .get("payload")
                .filter(|p| p.get("type").and_then(Py::as_str) == Some("token_count"))
                .and_then(|p| p.get("info"))
                .and_then(|i| i.get("last_token_usage"))
                .and_then(|u| u.get("input_tokens"));
            let n = match tokens {
                Some(Py::Int(n)) => *n,
                Some(Py::BigInt(s)) => {
                    if s.starts_with('-') {
                        i64::MIN
                    } else {
                        i64::MAX
                    }
                }
                _ => continue,
            };
            return (n != 0).then_some(n);
        }
        None
    }

    fn copilot_context(&self, cwd: &str, sid: Option<&str>) -> Option<i64> {
        let session = match sid.filter(|s| !s.is_empty()) {
            Some(s) => s.to_string(),
            None => self.probe.copilot_resume_id(cwd).filter(|s| !s.is_empty())?,
        };
        match self.probe.sqlite_cell(&self.paths.copilot_session_db(), COPILOT_CONTEXT_SQL, &session)? {
            SqlCell::Null => None,
            SqlCell::Int(n) => (n != 0).then_some(n),
            // `int(f)`: sıfıra doğru keser; sonsuz/NaN Python'da istisna
            SqlCell::Real(f) => (f != 0.0 && f.is_finite()).then(|| f.trunc() as i64),
            // `int(metin)`: sayı olmayan metin Python'da istisna
            SqlCell::Text(s) => parse_int(&s),
            SqlCell::Blob(b) => parse_int(std::str::from_utf8(&b).ok()?),
        }
    }
}
