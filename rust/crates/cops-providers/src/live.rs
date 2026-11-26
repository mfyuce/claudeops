//! Canlı durum okuyucuları (`CliProvider.busy_status_pattern`, `background_work`, `live_*`; sohbet geçmişi
//! `chat`te). Crate yine G/Ç yapmaz: dosya, dizin ve SQLite okuması [`LiveProbe`] ile çağırandadır.
//!
//! `None` her yerde "bilinmiyor" demektir; 0, `false` ya da boş listeyle karıştırılmaz.

use crate::bg_work::{self, Clock, TRANSCRIPT_TAIL_BYTES};
use crate::probe::{Paths, Probe};
use crate::provider::Cli;
use crate::pyfmt::{parse_int, splitlines};
use crate::pyjson::Py;
use crate::settings::Settings;
use crate::ucli_status::{FailedTurns, LivePhase, LiveUsage};
use std::collections::BTreeSet;

/// codex rollout dosyasının sonundan bağlam için okunan bayt.
pub const CODEX_CONTEXT_TAIL_BYTES: u64 = 262_144;

/// copilot oturum deposunda ana ajanın son isteğinin `input_tokens`ı (tek parametre: oturum kimliği).
pub const COPILOT_CONTEXT_SQL: &str = "SELECT input_tokens FROM assistant_usage_events WHERE session_id = ? AND agent_id IS NULL ORDER BY created_at DESC, turn_index DESC LIMIT 1";

/// [`LiveProbe::stat`] sonucu.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FileStat {
    /// Normal dosya (`S_ISREG`).
    pub is_file: bool,
    pub mtime_ns: i64,
    pub size: u64,
}

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
    /// `os.listdir`: dizin okuma sırası KORUNUR (eşit zamanlı dosyalarda seçim sıraya bağlıdır); UTF-8 olmayan adlar
    /// atlanabilir (hiçbir oturum adıyla eşleşemez). Dizin değilse ya da okunamazsa None.
    fn list_dir(&self, path: &str) -> Option<Vec<String>>;
    /// `os.stat` (symlink izlenir); yoksa ya da erişilemezse None.
    fn stat(&self, path: &str) -> Option<FileStat>;
    /// `/proc/<pid>/stat`ın ham içeriği (küçük sözde dosya); okunamazsa None.
    fn proc_stat(&self, pid: i64) -> Option<Vec<u8>>;
    /// Çağıran sürecin çalışma dizini (`os.getcwd`; göreli yolların `abspath`i için).
    fn current_dir(&self) -> String;
    /// `agy_sids` belgesi (öğrenilen oturum adı -> konuşma kimliği; Python `statedocs.read_json("agy_sids", ..)`).
    /// Yok, bozuk ya da okunamıyorsa None.
    fn agy_sids_doc(&self) -> Option<Py>;
    /// Dosyanın `start`tan başlayan en çok `len` baytı (dosya kısaldıysa daha az).
    fn read_range(&self, path: &str, start: u64, len: u64) -> Option<Vec<u8>>;
    /// `db` SALT OKUNUR (`mode=ro`, 2 sn meşgul beklemesi) açılır, tek parametreli sorgunun ilk satırının ilk hücresi;
    /// satır yoksa ya da SQLite hatasında None.
    fn sqlite_cell(&self, db: &str, sql: &str, param: &str) -> Option<SqlCell>;
    /// [`LiveProbe::sqlite_cell`] gibi açılır; sorgunun satırları tek tek (belleğe toplanmadan) `row`a verilir, `row`
    /// `false` dönerse okuma kesilir (dönüş `true`). SQLite hatasında (açılamayan/bozuk dosya, eksik tablo, UTF-8 olmayan
    /// metin hücresi) `false`; o ana kadarki satırlar verilmiş kalır. `db` yolu OLDUĞU GİBİ açılır (URI ayrıştırması yok).
    fn sqlite_rows(&self, db: &str, sql: &str, params: &[SqlCell], row: &mut dyn FnMut(Vec<SqlCell>) -> bool) -> bool;
    /// `~/.claude/projects/<kodlanmış cwd>` (`claude_provider._encode_cwd`: rs/proc `transcript.rs::encode_cwd`).
    fn claude_project_dir(&self, cwd: &str) -> String;
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
                0 => u64::from(self.transcript_pending_path(self.jsonl_path_for(cwd, sid).as_deref())),
                n => n,
            }),
            Cli::Codex => {
                let lines = self.tail_lines(self.codex_rollout_path(cwd, sid).as_deref());
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

    /// Son `token_count` olayının `last_token_usage.input_tokens`ı (0 = bilinmiyor). Boolean ve negatif değer sayaç
    /// sayılmaz: olay atlanır.
    fn codex_context(&self, cwd: &str, sid: Option<&str>) -> Option<i64> {
        let path = self.codex_rollout_path(cwd, sid)?;
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
                Some(Py::Int(n)) if *n >= 0 => *n,
                Some(Py::BigInt(s)) if !s.starts_with('-') => i64::MAX,
                _ => continue,
            };
            return (n != 0).then_some(n);
        }
        None
    }

    fn copilot_context(&self, cwd: &str, sid: Option<&str>) -> Option<i64> {
        let session = match sid.filter(|s| !s.is_empty()) {
            Some(s) => s.to_string(),
            None => self.copilot_resume_id(cwd, &BTreeSet::new()).filter(|s| !s.is_empty())?,
        };
        match self.probe.sqlite_cell(&self.paths.copilot_session_db(), COPILOT_CONTEXT_SQL, &session)? {
            SqlCell::Null => None,
            SqlCell::Int(n) => (n != 0).then_some(n),
            // `int(f)`: sıfıra doğru keser; sonsuz/NaN bilinmiyor
            SqlCell::Real(f) => (f != 0.0 && f.is_finite()).then(|| f.trunc() as i64),
            // `int(metin)`: sayı olmayan metin bilinmiyor
            SqlCell::Text(s) => parse_int(&s),
            SqlCell::Blob(b) => parse_int(std::str::from_utf8(&b).ok()?),
        }
    }
}
