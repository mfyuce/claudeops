//! Canlı durum okuyucuları (`CliProvider.busy_status_pattern`, `background_work`, `live_*`; sohbet geçmişi
//! `chat`te). Crate yine G/Ç yapmaz: dosya, dizin ve SQLite okuması [`LiveProbe`] ile çağırandadır.
//!
//! `None` her yerde "bilinmiyor" demektir; 0, `false` ya da boş listeyle karıştırılmaz.

use crate::bg_work::{self, Clock, SHELL_ONLY_DIRECTIVE_SECONDS, TRANSCRIPT_TAIL_BYTES};
use crate::claude_resume::py_int;
use crate::probe::{Paths, Probe};
use crate::provider::Cli;
use crate::pyfmt::{parse_float, splitlines};
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
    fn sqlite_rows(
        &self,
        db: &str,
        sql: &str,
        params: &[SqlCell],
        row: &mut dyn FnMut(Vec<SqlCell>) -> bool,
    ) -> bool;
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
    pub fn background_work(
        &self,
        cli: Cli,
        pane_text: &str,
        cwd: &str,
        sid: Option<&str>,
    ) -> Option<u64> {
        match cli {
            // ekran sayısı yoksa süreç kaydı karar verir (`busy`/`shell` = 1, `idle` = 0: claude'un kendi kaydı
            // transkript geçmişini ezer); kayıt yok, bayat ya da tanınmayan durumdaysa transkript yedeği
            Cli::Claude => Some(match bg_work::screen_bg_count(pane_text) {
                0 => match self.session_record_status(sid).as_deref() {
                    Some("busy" | "shell") => 1,
                    Some("idle") => 0,
                    _ => u64::from(
                        self.transcript_pending_path(self.jsonl_path_for(cwd, sid).as_deref()),
                    ),
                },
                n => n,
            }),
            Cli::Codex => {
                let lines = self.tail_lines(self.codex_rollout_path(cwd, sid).as_deref());
                let agents =
                    bg_work::codex_subagents_pending(lines.iter().map(String::as_str), self.clock);
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
            Cli::Ucli => self
                .ucli_context(cwd, sid)
                .map(|t| i64::try_from(t).unwrap_or(i64::MAX)),
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

    /// claude'un süreç kaydının (`sessions/<pid>.json`) bu konuşma için bildirdiği durum (`str(status or "")`):
    /// `busy` (tur ya da devredilen ajan), `shell` (tur bitti, kabuk/Monitor açık), `idle` (açık iş yok). Aynı
    /// konuşmanın birden çok canlı kaydında `busy`/`shell` kazanır, sonra tanınmayan durum (sıralı ilk, ör. `waiting`).
    /// Canlı kayıt yoksa, pid yeniden kullanılmışsa (`procStart` tutmuyorsa) ya da kayıt okunamıyorsa `None`.
    pub fn session_record_status(&self, sid: Option<&str>) -> Option<String> {
        let sid = sid.filter(|s| !s.is_empty())?;
        let names = self.probe.list_dir(&self.paths.claude_sessions_dir())?;
        let mut found: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
        for name in names.iter().filter(|n| n.ends_with(".json")) {
            let Some(data) = self.session_file(name) else {
                continue;
            };
            if data.get("sessionId").and_then(Py::as_str) != Some(sid) {
                continue;
            }
            // `str(d.get("procStart"))`: kırpılmaz
            let live = data
                .get("pid")
                .and_then(py_int)
                .and_then(|pid| self.proc_start(pid))
                .is_some_and(|start| data.get("procStart").is_some_and(|w| w.py_str() == start));
            if live {
                found.insert(
                    data.get("status")
                        .filter(|v| v.truthy())
                        .map(Py::py_str)
                        .unwrap_or_default(),
                );
            }
        }
        for st in ["busy", "shell"] {
            if found.contains(st) {
                return Some(st.to_string());
            }
        }
        found
            .iter()
            .find(|s| *s != "idle")
            .cloned()
            .or_else(|| found.contains("idle").then(|| "idle".to_string()))
    }

    /// `bg_work.session_record_shell_since` (TBD#442 a): bu konuşmanın canlı kayıtlarının birleşik durumu `shell` ise
    /// o duruma geçiş anı (epoch sn, `statusUpdatedAt` ms / 1000; birden çok CANLI `shell` kaydında en yenisi). Ölü ya da
    /// yeniden kullanılmış pid'in kaydı sayılmaz (`procStart`); `float()` dönüşmeyen, NaN ya da pozitif olmayan damga atlanır.
    pub fn session_record_shell_since(&self, sid: Option<&str>) -> Option<f64> {
        if self.session_record_status(sid).as_deref() != Some("shell") {
            return None;
        }
        let sid = sid?;
        let names = self.probe.list_dir(&self.paths.claude_sessions_dir())?;
        let mut best: Option<f64> = None;
        for name in names.iter().filter(|n| n.ends_with(".json")) {
            let Some(data) = self.session_file(name) else {
                continue;
            };
            if data.get("sessionId").and_then(Py::as_str) != Some(sid)
                || data.get("status").and_then(Py::as_str) != Some("shell")
            {
                continue;
            }
            let live = data
                .get("pid")
                .and_then(py_int)
                .and_then(|pid| self.proc_start(pid))
                .is_some_and(|start| data.get("procStart").is_some_and(|w| w.py_str() == start));
            if !live {
                continue;
            }
            let Some(t) = data
                .get("statusUpdatedAt")
                .and_then(py_float_of)
                .map(|ms| ms / 1000.0)
            else {
                continue;
            };
            if t > 0.0 && best.is_none_or(|b| t > b) {
                best = Some(t);
            }
        }
        best
    }

    /// `bg_work.shell_only_stale`: tur bitmiş, `SHELL_ONLY_DIRECTIVE_SECONDS`ten uzun süredir yalnız kabuk/Monitor açık.
    pub fn shell_only_stale(&self, sid: Option<&str>, now: f64) -> bool {
        self.session_record_shell_since(sid)
            .is_some_and(|since| now - since >= SHELL_ONLY_DIRECTIVE_SECONDS)
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
            None => self
                .copilot_resume_id(cwd, &BTreeSet::new())
                .filter(|s| !s.is_empty())?,
        };
        match self.probe.sqlite_cell(
            &self.paths.copilot_session_db(),
            COPILOT_CONTEXT_SQL,
            &session,
        )? {
            SqlCell::Null => None,
            SqlCell::Int(n) => (n != 0).then_some(n),
            // `int(f)`: sıfıra doğru keser; sonsuz/NaN bilinmiyor
            SqlCell::Real(f) => (f != 0.0 && f.is_finite()).then(|| f.trunc() as i64),
            // `int(metin)`: sayı olmayan metin bilinmiyor; i64'e sığmayan değer Int/Real yolları gibi doyar (R-G6-4)
            SqlCell::Text(s) => cell_int(&s),
            // `int(bytes)` yalnız ASCII rakam ve ASCII boşluk (`Py_ISSPACE`: U+001C..U+001F boşluk SAYILMAZ) kabul eder
            SqlCell::Blob(b) => {
                if b.iter().any(|c| !c.is_ascii() || (0x1c..=0x1f).contains(c)) {
                    return None;
                }
                cell_int(std::str::from_utf8(&b).ok()?)
            }
        }
    }
}

/// SQLite hücresinde `int(metin)`: sığmayan değer uca doyar; 4300 basamaktan uzun değer Python'da `ValueError` (None).
fn cell_int(s: &str) -> Option<i64> {
    let n = cops_state::pycompat::parse_int(s)?;
    (n.as_str().trim_start_matches('-').len() <= 4300).then(|| n.saturating_i64())
}

/// Python `float(v)` bir süreç kaydı değerinde: sayı, bool (0/1), dize (`float(str)`); `float()`ın taşma verdiği dev tam
/// sayı ve başka tip `None`.
fn py_float_of(v: &Py) -> Option<f64> {
    match v {
        Py::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
        Py::Int(n) => Some(*n as f64),
        Py::BigInt(s) => s.parse::<f64>().ok().filter(|f| f.is_finite()),
        Py::Float(f) => Some(*f),
        Py::Str(s) => parse_float(s),
        _ => None,
    }
}
