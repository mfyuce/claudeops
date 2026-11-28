//! `cops-rs` ikilisi: bkz. `cops_cli` belgesi ve docs/rs-cli.md.
#![cfg_attr(
    not(test),
    deny(clippy::unwrap_used, clippy::expect_used, clippy::panic)
)]

use cops_cli::delegate::{self, Locate, EXIT_DELEGATE};
use cops_cli::front::{self, net::RealNet, systemctl::RealSystemctl, Ctx, Paths, Timing};
use cops_cli::pyenv::Roots;
use cops_cli::{list, route, selfcmd, Route};
use cops_state::{StateDir, StateDocs};
use std::ffi::OsString;
use std::io::Write;
use std::path::PathBuf;
use std::process::exit;

fn uid() -> u32 {
    // SAFETY: argümansız libc çağrısı.
    unsafe { libc::getuid() }
}

fn locate_input(roots: Option<&Roots>) -> Locate {
    Locate {
        cops_py: std::env::var_os("COPS_PY"),
        self_exe: std::fs::read_link("/proc/self/exe").ok(),
        state_dir: roots
            .filter(|r| r.claudeops_dir.starts_with('/'))
            .map(|r| PathBuf::from(&r.claudeops_dir)),
    }
}

fn run_delegate(args: &[OsString]) -> ! {
    let roots = Roots::from_env().ok();
    let py = match delegate::locate(&locate_input(roots.as_ref())) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("cops-rs: {e}");
            exit(EXIT_DELEGATE);
        }
    };
    let me = std::process::id();
    let depth = delegate::depth_from(std::env::var_os(delegate::DEPTH_ENV).as_deref(), |p| {
        delegate::is_self_or_ancestor(std::path::Path::new("/proc"), me, p)
    });
    let msg = delegate::exec(&py, args, depth);
    eprintln!("cops-rs: {msg}");
    exit(EXIT_DELEGATE)
}

fn run_front(fa: &cops_cli::argp::FrontArgs) -> i32 {
    let roots = match Roots::from_env().and_then(|r| r.check_absolute().map(|_| r)) {
        Ok(r) => r,
        Err(e) => {
            eprintln!("cops-rs: {e}");
            return 1;
        }
    };
    // `on` planı `DIST_DIR`ı yazar: Python deposundan çözülür (derleme anındaki yol gömülmez).
    let dist = if fa.action == cops_cli::argp::Action::On {
        let py = match delegate::locate(&locate_input(Some(&roots))) {
            Ok(p) => p,
            Err(e) => {
                eprintln!("cops-rs: front on: dist dizini için {e}");
                return EXIT_DELEGATE;
            }
        };
        match py.py_dir().map(front::dist_dir) {
            Some(Ok(d)) => Some(d),
            Some(Err(e)) => {
                eprintln!("cops-rs: front on: dist dizini çözülemedi: {e}");
                return EXIT_DELEGATE;
            }
            None => {
                eprintln!("cops-rs: front on: py/ dizini yok");
                return EXIT_DELEGATE;
            }
        }
    } else {
        None
    };
    let net = RealNet {
        proc_root: PathBuf::from("/proc"),
        uid: uid(),
    };
    let mut sc = RealSystemctl;
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    let mut ctx = Ctx {
        paths: Paths::new(&roots, dist),
        // UTF-8 olmayan değer Python gibi "dolu" sayılır (yok sayılıp dosyaya düşülmez)
        env_secret: std::env::var_os("CLAUDEOPS_FRONT_SECRET")
            .map(|v| v.to_string_lossy().into_owned()),
        net: &net,
        sc: &mut sc,
        out: &mut out,
        timing: Timing::default(),
    };
    front::run(&mut ctx, fa)
}

/// `None` = Python'a devret (hiçbir şey yazılmadı).
fn run_list(la: &cops_cli::argp::ListArgs) -> Option<i32> {
    let roots = Roots::from_env().ok()?;
    roots.check_absolute().ok()?;
    let cfg = cops_procscan::Config::from_env()?;
    let docs = StateDocs::new(StateDir::at(cfg.agy_sids.parent()?));
    if list::agy_mirror_reason(&docs, &cfg.agy_sids).is_some() {
        return None;
    }
    let text = list::run(&cfg, la).ok()?;
    let mut out = std::io::stdout().lock();
    match out.write_all(text.as_bytes()).and_then(|()| out.flush()) {
        Ok(()) => Some(0),
        Err(err) => {
            eprintln!("cops-rs: çıktı yazılamadı: {err}");
            Some(1)
        }
    }
}

fn run_self() -> i32 {
    let roots = match Roots::from_env() {
        Ok(r) => r,
        Err(e) => {
            eprintln!("cops-rs: {e}");
            return 1;
        }
    };
    let cfg = selfcmd::SelfCfg {
        sessions_dir: PathBuf::from(roots.claude_dir()).join("sessions"),
        proc_root: PathBuf::from("/proc"),
        uid: uid(),
        pid: std::process::id(),
        session_id: std::env::var("CLAUDE_CODE_SESSION_ID").ok(),
    };
    let (stdout, stderr) = (std::io::stdout(), std::io::stderr());
    let (mut o, mut e) = (stdout.lock(), stderr.lock());
    match selfcmd::run(&cfg, &mut o, &mut e) {
        Ok(c) => c,
        Err(err) => {
            eprintln!("cops-rs: çıktı yazılamadı: {err}");
            1
        }
    }
}

fn main() {
    // P2-2: güvenilmeyen PATH girdileri atılır (Python `__main__` eşi; devredilen Python ve çocuklar temiz PATH devralır)
    cops_state::paths::secure_path_environ();
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    // İkilinin kaynak sürümü (canlı ikili = main HEAD denetimi); stdout ve çıkış kodu devredilen Python'unkidir.
    if args.len() == 1 && args[0] == "--version" {
        eprintln!("cops-rs {}", env!("COPSD_GIT_SHA"));
    }
    match route(&args) {
        Route::Delegate(_) => run_delegate(&args),
        Route::Front(fa) => exit(run_front(&fa)),
        Route::List(la) => match run_list(&la) {
            Some(code) => exit(code),
            None => run_delegate(&args),
        },
        Route::SelfCmd => exit(run_self()),
    }
}
