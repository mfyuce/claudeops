//! Salt okunur deneme/parite ikilisi.
//!   cops-procscan list [--no-cpu] [--base AD] [--json]   (`cops list` çıktısı)
//!   cops-procscan scan [--no-cpu]                        (süreç alanları, JSON)
//!   cops-procscan usage TRANSKRIPT.jsonl                 (token toplamı, JSON)

use cops_procscan::status::{OrphanTracker, Probe};
use cops_procscan::transcript::jsonl_path_for;
use cops_procscan::usage::UsageReader;
use cops_procscan::{duplicates, find_sessions, list, Config, CpuMode, Scan};
use serde_json::{json, Value};
use std::io::Write;
use std::process::ExitCode;

const USAGE: &str = "kullanım: cops-procscan list [--no-cpu] [--base AD] [--json] | scan [--no-cpu] | usage DOSYA";

fn scan(cfg: &Config, mode: CpuMode<'_>) -> std::io::Result<Scan> {
    find_sessions(cfg, mode).map_err(std::io::Error::other)
}

fn run(args: &[String], out: &mut impl Write) -> std::io::Result<bool> {
    let Some(cfg) = Config::from_env() else { return Ok(false) };
    let Some((cmd, rest)) = args.split_first() else {
        return Ok(false);
    };
    if cmd == "usage" {
        let [path] = rest else { return Ok(false) };
        let u = UsageReader::default().usage_for_path(path.as_ref());
        writeln!(out, "{}", json!(u))?;
        return Ok(true);
    }
    let (mut no_cpu, mut as_json, mut base) = (false, false, None);
    let mut it = rest.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--no-cpu" => no_cpu = true,
            "--json" if cmd == "list" || cmd == "ls" => as_json = true,
            "--base" if cmd == "list" || cmd == "ls" => match it.next() {
                Some(b) => base = Some(b.clone()),
                None => return Ok(false),
            },
            _ => return Ok(false),
        }
    }
    let mode = if no_cpu { CpuMode::Skip } else { CpuMode::Sleep };
    match cmd.as_str() {
        "list" | "ls" => {
            let sessions = scan(&cfg, mode)?.sessions;
            write!(out, "{}", list::render(sessions, base.as_deref(), as_json))?;
        }
        "scan" => {
            let scan = scan(&cfg, mode)?;
            let probe = Probe::new(&cfg);
            let mut usage = UsageReader::default();
            let rows: Vec<Value> = scan
                .sessions
                .iter()
                .map(|s| {
                    let path = (s.cli == "claude")
                        .then(|| jsonl_path_for(&cfg, &s.cwd, s.sid.as_deref()))
                        .flatten();
                    let mut row = json!(s);
                    let extra = json!({
                        "base": s.base(),
                        "fresh": s.is_fresh(),
                        "tmux": probe.is_tmux_backed(s.pid),
                        "no_terminal": probe.no_terminal(s.pid),
                        "idle_spin": probe.idle_spin(s.pid, s.cpu),
                        "ucli_flags": probe.ucli_flags(s),
                        "usage_total": path.as_deref().and_then(|p| usage.usage_for_path(p)),
                        "transcript": path,
                    });
                    if let (Value::Object(r), Value::Object(e)) = (&mut row, extra) {
                        r.extend(e);
                    }
                    row
                })
                .collect();
            let orphans = OrphanTracker::default().report(&probe, &scan.sessions, 0.0);
            let doc = json!({"sessions": rows, "duplicates": duplicates(&scan.sessions),
                             "mirrors": scan.mirrors, "orphans": orphans});
            writeln!(out, "{doc}")?;
        }
        _ => return Ok(false),
    }
    Ok(true)
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match run(&args, &mut std::io::stdout().lock()) {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => {
            eprintln!("{USAGE}");
            ExitCode::from(2)
        }
        // `| head` gibi kapanan boru hata değil
        Err(e) if e.kind() == std::io::ErrorKind::BrokenPipe => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("{e}");
            ExitCode::FAILURE
        }
    }
}
