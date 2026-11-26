//! `discovery.find_sessions`: iki kaynak (sessions json + süreç taraması), CPU örneklemesi, katlama.

use crate::mirrors::note_mirror;
use crate::procfs::{OwnProc, ProcFs, Stat};
use crate::providers::{AgyState, Cli};
use crate::py;
use crate::session::{fold_background, fold_subshells, Session};
use crate::Config;
use serde::Serialize;
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::time::{Duration, Instant};

/// Python ile aynı örnekleme aralığı.
pub const CPU_SAMPLE: Duration = Duration::from_millis(300);

/// CPU ölçümü: iki örnek arasında `wait` çağrılır, dönen süre iki örnek arasındaki duvar saatidir.
pub enum CpuMode<'a> {
    Skip,
    Sleep,
    Custom(&'a mut dyn FnMut() -> Duration),
}

#[derive(Debug, Default)]
pub struct Scan {
    pub sessions: Vec<Session>,
    /// Açık `cops watch` pencereleri: `host:ad` -> pid'ler.
    pub mirrors: BTreeMap<String, Vec<u32>>,
    /// Yeni öğrenilen agy (ad, sohbet) eşlemeleri; kalıcılaştırmak çağıranın işi.
    pub agy_learned: Vec<(String, String)>,
    /// Python gibi yutulan okuma hataları (sonuç aynı kalır, burada sayılır).
    pub diag: ScanDiag,
}

/// Taramanın yuttuğu hatalar. Davranış Python'la aynıdır (satır atlanır, alan boş kalır); bu sayaçlar
/// "yok" ile "okunamadı"yı ayırır. Hepsi sıfır/`None` ise tarama tam görmüştür.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct ScanDiag {
    /// `/proc` listelenemedi: süreç listesi boş döner ama bu "süreç yok" DEĞİL, "bilinmiyor"dur
    /// (Python'da psutil burada istisna fırlatır).
    pub proc_root_error: Option<String>,
    /// `sessions/` var ama listelenemedi (yokluğu hata değil).
    pub sessions_dir_error: Option<String>,
    /// Tarama sırasında çıkan süreçler (`ENOENT`/`ESRCH`).
    pub procs_vanished: u32,
    /// `status`ı okunamayan ya da `Uid:` satırı bozuk süreçler (atlandı).
    pub procs_unreadable: u32,
    /// Bize ait ama `cmdline`ı okunamayan süreçler (boş sayıldı).
    pub cmdline_unreadable: u32,
    /// Tanınan CLI sürecinin `cwd`si okunamadı (satır atlandı).
    pub cwd_unreadable: u32,
    /// `stat` okunamadı ya da ayrıştırılamadı (`procStart` denetimi atlandı, CPU 0 kaldı).
    pub stat_unreadable: u32,
    /// `sessions/*.json` okunamadı.
    pub session_files_unreadable: u32,
    /// `sessions/*.json` geçerli JSON değil.
    pub session_files_invalid: u32,
    /// agy önbelleği ya da `agy_sids` aynası var ama okunamadı ya da nesne değil (boş sayıldı).
    pub agy_files_unreadable: u32,
}

impl ScanDiag {
    pub fn is_clean(&self) -> bool {
        *self == ScanDiag::default()
    }
}

/// Python'un taramayı istisnayla bitirdiği girdi (bozuk ama ayrıştırılabilir oturum dosyası).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ScanError {
    /// Kök nesne değil, ya da `name` dizgi olmayan doğru bir değer.
    BadSessionFile(std::path::PathBuf),
}

impl std::fmt::Display for ScanError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let ScanError::BadSessionFile(p) = self;
        write!(f, "bozuk oturum dosyası: {}", p.display())
    }
}

impl std::error::Error for ScanError {}

fn json_pid(v: Option<&Value>) -> Option<u32> {
    let n = match v? {
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64))?,
        Value::String(s) => py::int(s)?,
        Value::Bool(b) => i64::from(*b),
        _ => return None,
    };
    u32::try_from(n).ok().filter(|p| *p > 0)
}

/// `~/.claude/sessions/*.json`: canlı (ve bize ait), `procStart`ı tutan kayıtlar.
fn sessions_from_json(cfg: &Config, proc: &ProcFs, diag: &mut ScanDiag) -> Result<Vec<Session>, ScanError> {
    let rd = match std::fs::read_dir(cfg.claude_dir.join("sessions")) {
        Ok(rd) => rd,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(e) => {
            diag.sessions_dir_error = Some(e.to_string());
            return Ok(Vec::new());
        }
    };
    let mut out = Vec::new();
    for entry in rd.flatten() {
        let file = entry.file_name();
        let file = file.to_string_lossy();
        if !file.ends_with(".json") || file.starts_with('.') {
            continue;
        }
        let value = match std::fs::read(entry.path()) {
            Ok(raw) => py::json(&raw),
            Err(_) => {
                diag.session_files_unreadable += 1;
                continue;
            }
        };
        let Some(value) = value else {
            diag.session_files_invalid += 1;
            continue;
        };
        let Value::Object(d) = value else {
            return Err(ScanError::BadSessionFile(entry.path()));
        };
        let Some(pid) = json_pid(d.get("pid")) else { continue };
        let name = match d.get("name") {
            Some(v) if py::truthy(v) => v.as_str().ok_or_else(|| ScanError::BadSessionFile(entry.path()))?,
            _ => continue,
        };
        // Python `os.kill(pid, 0)`: ölü ya da başkasının süreci atlanır.
        let Some(own) = proc.own(pid) else { continue };
        // `str(d.get("procStart", "")).strip()`: `null` -> "None" (eşleşmez)
        let want = d
            .get("procStart")
            .map(|v| py::strip(&py::to_str(v)).to_owned())
            .unwrap_or_default();
        let stat = own.stat();
        if stat.is_none() {
            diag.stat_unreadable += 1; // Python: `/proc` okunamazsa denetim atlanır
        }
        if !want.is_empty() && stat.is_some_and(|s| s.starttime.to_string() != want) {
            continue;
        }
        let Some(cwd) = own
            .cwd_raw()
            .or_else(|| py::truthy_str(d.get("cwd")))
            .filter(|c| !c.is_empty())
        else {
            continue;
        };
        out.push(Session {
            name: name.to_owned(),
            pid,
            cwd,
            sid: py::truthy_str(d.get("sessionId")),
            cli: "claude".into(),
            kind: py::truthy_str(d.get("kind")).unwrap_or_default(),
            job_id: py::truthy_str(d.get("jobId")),
            parked_job_id: py::truthy_str(d.get("parkedJobId")),
            proc_id: own.id(),
            ..Default::default()
        });
    }
    Ok(out)
}

/// Adsız (claude dışı) süreç için yedek ad: `<cli>@<cwd dizin adı>#<pid>`.
pub fn fallback_name(cli: &str, cwd: &str, pid: u32) -> String {
    let base = cwd
        .trim_end_matches('/')
        .rsplit('/')
        .next()
        .filter(|b| !b.is_empty())
        .unwrap_or("root");
    format!("{cli}@{base}#{pid}")
}

/// Ata pid zinciri (init hariç); bize ait olmayan ya da okunamayan halkada durur.
fn ancestors(proc: &ProcFs, mut pid: u32) -> Vec<u32> {
    let mut out = Vec::new();
    for _ in 0..64 {
        let Some(st) = proc.own(pid).and_then(|p| p.stat()) else {
            break;
        };
        pid = st.ppid;
        if pid <= 1 {
            break;
        }
        out.push(pid);
    }
    out
}

/// Ekleme sırasını koruyan `(ad, pid)` anahtarlı tablo (Python dict davranışı).
#[derive(Default)]
struct Table {
    rows: Vec<Option<Session>>,
    index: HashMap<(String, u32), usize>,
}

impl Table {
    fn put(&mut self, s: Session) {
        match self.index.get(&(s.name.clone(), s.pid)) {
            Some(&i) => self.rows[i] = Some(s),
            None => {
                self.index.insert((s.name.clone(), s.pid), self.rows.len());
                self.rows.push(Some(s));
            }
        }
    }

    fn remove(&mut self, name: &str, pid: u32) {
        if let Some(i) = self.index.remove(&(name.to_owned(), pid)) {
            self.rows[i] = None;
        }
    }
}

fn sample(p: &OwnProc) -> Option<Stat> {
    p.stat()
}

fn cpu_percent(before: Stat, after: Stat, wall: Duration, clk_tck: u64) -> f64 {
    // pid yeniden kullanıldıysa fark anlamsız
    if before.starttime != after.starttime || wall.is_zero() {
        return 0.0;
    }
    let ticks = (after.utime + after.stime).saturating_sub(before.utime + before.stime);
    let pct = ticks as f64 / clk_tck as f64 / wall.as_secs_f64() * 100.0;
    (pct * 10.0).round() / 10.0
}

/// Tüm çalışan oturumlar. Aynı adda birden çok canlı süreç varsa hepsi döner.
pub fn find_sessions(cfg: &Config, cpu: CpuMode<'_>) -> Result<Scan, ScanError> {
    let proc = ProcFs::new(&cfg.proc_root, cfg.uid);
    let mut scan = Scan::default();
    let mut table = Table::default();
    let from_json = sessions_from_json(cfg, &proc, &mut scan.diag)?;
    let json_by_pid: HashMap<u32, Session> = from_json.iter().map(|s| (s.pid, s.clone())).collect();
    from_json.into_iter().for_each(|s| table.put(s));

    let procs = match proc.own_processes_checked() {
        Ok((v, counts)) => {
            scan.diag.procs_vanished += counts.vanished;
            scan.diag.procs_unreadable += counts.unreadable;
            v
        }
        Err(e) => {
            scan.diag.proc_root_error = Some(e.to_string());
            Vec::new()
        }
    };
    let mut raw = Vec::new();
    for p in procs {
        let cmd = p.try_cmdline().unwrap_or_else(|_| {
            scan.diag.cmdline_unreadable += 1;
            Vec::new()
        });
        note_mirror(&mut scan.mirrors, p.pid(), &cmd);
        if let Some(cli) = Cli::detect(&cmd) {
            raw.push((p, cmd, cli));
        }
    }

    let measured: HashMap<u32, f64> = {
        let mut wait: Box<dyn FnMut() -> Duration + '_> = match cpu {
            CpuMode::Skip => Box::new(|| Duration::ZERO),
            CpuMode::Sleep => Box::new(|| {
                let t = Instant::now();
                std::thread::sleep(CPU_SAMPLE);
                t.elapsed()
            }),
            CpuMode::Custom(f) => Box::new(f),
        };
        let mut targets: HashMap<u32, OwnProc> = raw.iter().map(|(p, _, _)| (p.pid(), p.clone())).collect();
        for pid in json_by_pid.keys() {
            if let Some(p) = proc.own(*pid) {
                targets.entry(*pid).or_insert(p);
            }
        }
        let before: Vec<(u32, Stat)> = targets.iter().filter_map(|(pid, p)| Some((*pid, sample(p)?))).collect();
        let wall = wait();
        before
            .into_iter()
            .filter_map(|(pid, b)| Some((pid, cpu_percent(b, sample(&targets[&pid])?, wall, cfg.clk_tck))))
            .collect()
    };

    let mut agy = AgyState::load(cfg);
    scan.diag.agy_files_unreadable += agy.unreadable;
    for (p, cmd, cli) in raw {
        let pid = p.pid();
        let cwd = p.try_cwd().unwrap_or_else(|_| {
            scan.diag.cwd_unreadable += 1;
            String::new()
        });
        let mut name = cli.extract_name(&p, &cmd);
        if name.is_none() && cli != Cli::Claude && !cwd.is_empty() {
            name = Some(fallback_name(cli.as_str(), &cwd, pid));
        }
        let Some(name) = name else { continue };
        if cwd.is_empty() {
            continue;
        }
        let info = cli.extract_info(&cmd, &cwd, &name, &mut agy);
        let resumed = Some(info.sid.as_deref().is_some_and(|s| !s.is_empty()));
        // Yalnız aynı sağlayıcının json kaydı sayılır (pid yeniden kullanımı).
        let prior = json_by_pid.get(&pid).filter(|j| j.cli == cli.as_str());
        if let Some(j) = prior.filter(|j| j.name != name) {
            // TUI `/name`: aynı süreç iki satır görünmesin, fleet kimliği spawn adıdır.
            table.remove(&j.name, pid);
        }
        table.put(Session {
            name,
            pid,
            cwd,
            sid: prior.and_then(|j| j.sid.clone()).or(info.sid),
            model: info.model,
            permission_mode: info.permission_mode,
            effort: info.effort,
            cpu: 0.0,
            cli: cli.as_str().into(),
            resumed,
            kind: prior.map(|j| j.kind.clone()).unwrap_or_default(),
            job_id: prior.and_then(|j| j.job_id.clone()),
            parked_job_id: prior.and_then(|j| j.parked_job_id.clone()),
            bg_pid: None,
            proc_id: p.id(),
        });
    }
    scan.agy_learned = agy.learned;

    let mut sessions: Vec<Session> = table.rows.into_iter().flatten().collect();
    for s in &mut sessions {
        s.cpu = measured.get(&s.pid).copied().unwrap_or(0.0);
    }
    scan.sessions = fold_subshells(fold_background(sessions), |pid| ancestors(&proc, pid));
    Ok(scan)
}

/// Belirli addaki oturumlar (çoklu süreç tespiti için liste).
pub fn find_by_name(cfg: &Config, name: &str, cpu: CpuMode<'_>) -> Result<Vec<Session>, ScanError> {
    let mut v = find_sessions(cfg, cpu)?.sessions;
    v.retain(|s| s.name == name);
    Ok(v)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fallback_names() {
        assert_eq!(fallback_name("ucli", "/a/b/", 5), "ucli@b#5");
        assert_eq!(fallback_name("shell", "/", 5), "shell@root#5");
    }
}
