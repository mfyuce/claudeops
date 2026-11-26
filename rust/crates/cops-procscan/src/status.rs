//! `/api/status` satırının süreçten okunan alanları: tmux bağlılığı, terminalsiz/boşa dönen süreçler,
//! ucli rozetleri, süreç başlangıcı.

use crate::procfs::ProcFs;
use crate::providers::basename;
use crate::py;
use crate::session::Session;
use crate::transcript::jsonl_path_for;
use crate::usage::{Usage, UsageCache};
use crate::Config;
use serde::Serialize;
use std::collections::{HashMap, HashSet};

const TMUX_SOCKET: &str = "cops";
const ANCESTOR_WALK_LIMIT: usize = 6;
pub const IDLE_SPIN_CPU: f64 = 50.0;
pub const SPIN_SECONDS: f64 = 600.0;

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct UcliFlags {
    pub write: bool,
    pub exec: bool,
    pub max_cost_usd: Option<f64>,
    pub ask: bool,
    pub checks: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Orphan {
    pub name: String,
    pub pid: u32,
    pub cli: String,
    pub cpu: f64,
    /// CPU >= %50 kesintisiz 10 dk sürdü.
    pub spinning: bool,
}

/// Süreç sorguları.
#[derive(Debug, Clone)]
pub struct Probe {
    proc: ProcFs,
    clk_tck: u64,
}

impl Probe {
    pub fn new(cfg: &Config) -> Self {
        Probe {
            proc: ProcFs::new(&cfg.proc_root, cfg.uid),
            clk_tck: cfg.clk_tck,
        }
    }

    /// Atalarda `tmux -L cops` var mı. Belirsizlik (okunamayan ya da başkasına ait halka) = hayır.
    pub fn is_tmux_backed(&self, pid: u32) -> bool {
        let Some(mut cur) = self.proc.own(pid) else { return false };
        for _ in 0..ANCESTOR_WALK_LIMIT {
            let Some(parent) = cur.stat().and_then(|s| self.proc.own(s.ppid)) else {
                return false;
            };
            cur = parent;
            let cmd = cur.cmdline();
            if cmd.len() >= 3 && basename(&cmd[0]) == "tmux" && cmd[1] == "-L" && cmd[2] == TMUX_SOCKET {
                return true;
            }
        }
        false
    }

    pub fn terminal_lost(&self, pid: u32) -> bool {
        self.proc.own(pid).is_some_and(|p| p.terminal_lost())
    }

    pub fn no_terminal(&self, pid: u32) -> bool {
        !self.is_tmux_backed(pid) && self.terminal_lost(pid)
    }

    /// Terminali yok VE CPU yüksek.
    pub fn idle_spin(&self, pid: u32, cpu: f64) -> bool {
        cpu >= IDLE_SPIN_CPU && self.no_terminal(pid)
    }

    /// Süreç başlangıcı (epoch sn).
    pub fn started_at(&self, pid: u32) -> Option<f64> {
        let start = self.proc.own(pid)?.stat()?.starttime;
        Some(self.proc.boot_time()? as f64 + start as f64 / self.clk_tck as f64)
    }

    /// Çalışan claude oturumunun kümülatif harcaması (`web._usage_total`); beklemez.
    pub fn usage_total(&self, cfg: &Config, cache: &UsageCache, s: &Session) -> Option<Usage> {
        if s.cli != "claude" {
            return None;
        }
        cache.get(&jsonl_path_for(cfg, &s.cwd, s.sid.as_deref())?)
    }

    /// Çalışan ucli oturumunun cmdline'ından panel rozetleri (`web._ucli_flags`; `tools` durum dosyasından gelir, burada yok).
    pub fn ucli_flags(&self, s: &Session) -> Option<UcliFlags> {
        if s.cli != "ucli" {
            return None;
        }
        let cmd = self.proc.own(s.pid)?.cmdline();
        let has = |f: &str| cmd.iter().any(|c| c == f);
        Some(UcliFlags {
            write: has("--allow-edit"),
            exec: cmd.iter().any(|t| t.starts_with("--allow-exec")),
            max_cost_usd: cmd
                .windows(2)
                .rev()
                .find(|w| w[0] == "--max-cost-usd")
                .and_then(|w| py::strip(&w[1]).parse().ok()),
            ask: has("--ask-dir"),
            checks: has("--allow-checks"),
        })
    }
}

/// `orphan_report`: yüksek CPU'nun ilk görüldüğü anı çağrılar arasında tutar.
#[derive(Debug, Default)]
pub struct OrphanTracker {
    since: HashMap<u32, f64>,
}

impl OrphanTracker {
    /// Terminalsiz süreçler; `now` saniye (herhangi bir tekdüze saat).
    pub fn report(&mut self, probe: &Probe, sessions: &[Session], now: f64) -> Vec<Orphan> {
        let live: HashSet<u32> = sessions.iter().map(|s| s.pid).collect();
        self.since.retain(|pid, _| live.contains(pid));
        let mut out = Vec::new();
        for s in sessions {
            if !probe.no_terminal(s.pid) {
                self.since.remove(&s.pid);
                continue;
            }
            if s.cpu >= IDLE_SPIN_CPU {
                self.since.entry(s.pid).or_insert(now);
            } else {
                self.since.remove(&s.pid);
            }
            let spinning = self.since.get(&s.pid).is_some_and(|t0| now - t0 >= SPIN_SECONDS);
            out.push(Orphan {
                name: s.name.clone(),
                pid: s.pid,
                cli: s.cli.clone(),
                cpu: s.cpu,
                spinning,
            });
        }
        out
    }
}
