//! G9 gerçek uygulayıcıları: gnome-terminal başlatma ([`GnomeTerminal`]), sistem saati ([`SystemClock`]), günlük
//! ([`DiagLog`] -> [`DiagSink`]) ve `paths.REPO_DIR` çözümü ([`repo_dir_of`]). tmux uygulayıcısı burada YOK (`cops-tmux`).

use crate::probe::Diag;
use crate::real::diaglog::DiagLog;
use crate::real::{pathexec, Env};
use crate::settings::Settings;
use crate::spawn_exec::{Clock, DiagSink, LaunchError, Terminal};
use crate::startup_desktop::{startup_env, DesktopIo, StartupEnv};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

/// `subprocess.Popen(["gnome-terminal", ...], env=env, stdout=DEVNULL, stderr=DEVNULL)` + arka planda `proc.wait()`.
///
/// - `env` çocuğun TÜM ortamıdır (miras yok); program `env`deki `PATH`te aranır (Python `Popen(env=)` gibi).
/// - stdin miras alınır (Python gibi); stdout/stderr `/dev/null`.
/// - Yalnız bu çağrının başlattığı çocuk beklenir (zombi kalmaz); hiçbir süreç öldürülmez.
#[derive(Debug, Clone)]
pub struct GnomeTerminal {
    /// [`Terminal::available`] için çağıran sürecin ortamı (`shutil.which` `os.environ["PATH"]`).
    env: Env,
    desktop: Option<Desktop>,
}

/// Masaüstü yönlendirmesinin girdileri.
#[derive(Clone)]
struct Desktop {
    settings_json: String,
    io: Arc<dyn DesktopIo>,
}

impl std::fmt::Debug for Desktop {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Desktop")
            .field("settings_json", &self.settings_json)
            .finish_non_exhaustive()
    }
}

impl GnomeTerminal {
    /// Masaüstü yönlendirmesi KAPALI (X'e ve `wmctrl`e dokunulmaz); açmak için [`GnomeTerminal::with_desktop`].
    pub fn new(env: Env) -> GnomeTerminal {
        GnomeTerminal { env, desktop: None }
    }

    /// `settings_json` her açılışta yeniden okunur (okunamaz/bozuk = varsayılanlar, Python `load_settings`).
    pub fn with_desktop(mut self, settings_json: String, io: Arc<dyn DesktopIo>) -> GnomeTerminal {
        self.desktop = Some(Desktop { settings_json, io });
        self
    }
}

/// `Popen`in `ValueError`ları (CPython `_posixsubprocess` öncesi denetimler).
fn popen_value_error(argv: &[String], env: &[(String, String)]) -> Option<&'static str> {
    if argv.iter().any(|a| a.contains('\0'))
        || env
            .iter()
            .any(|(k, v)| k.contains('\0') || v.contains('\0'))
    {
        return Some("embedded null byte");
    }
    if env.iter().any(|(k, _)| k.contains('=')) {
        return Some("illegal environment variable name");
    }
    None
}

fn reap(slot: &Mutex<Option<Child>>) {
    let child = slot.lock().ok().and_then(|mut c| c.take());
    if let Some(mut child) = child {
        let _ = child.wait();
    }
}

impl Terminal for GnomeTerminal {
    fn available(&self) -> bool {
        pathexec::which(&self.env, "gnome-terminal").is_some()
    }

    fn path_exists(&self, path: &str) -> bool {
        Path::new(path).exists()
    }

    fn startup_env(&self, name: &str, env: &[(String, String)]) -> StartupEnv {
        let Some(desktop) = &self.desktop else {
            return StartupEnv::unchanged(env);
        };
        let text = std::fs::read_to_string(&desktop.settings_json).unwrap_or_default();
        startup_env(&Settings::from_json(&text), env, name, desktop.io.as_ref())
    }

    fn launch(&self, argv: &[String], env: &[(String, String)]) -> Result<bool, LaunchError> {
        if let Some(why) = popen_value_error(argv, env) {
            return Err(LaunchError::Value(why.into()));
        }
        let Some((program, args)) = argv.split_first() else {
            return Ok(false);
        };
        let spawned = Command::new(program)
            .args(args)
            .env_clear()
            .envs(env.iter().map(|(k, v)| (k, v)))
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn();
        let Ok(child) = spawned else { return Ok(false) };
        let slot = Arc::new(Mutex::new(Some(child)));
        let theirs = Arc::clone(&slot);
        let started = std::thread::Builder::new()
            .name("cops-gt-reap".into())
            .spawn(move || reap(&theirs));
        if started.is_err() {
            // Python `RuntimeError` yükselir; çocuk yine de toplanır (istemci hemen çıkar).
            reap(&slot);
            return Err(LaunchError::Runtime("can't start new thread".into()));
        }
        Ok(true)
    }
}

/// `time.monotonic` / `time.sleep`.
#[derive(Debug, Clone, Copy, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn monotonic(&self) -> f64 {
        static ORIGIN: OnceLock<Instant> = OnceLock::new();
        ORIGIN.get_or_init(Instant::now).elapsed().as_secs_f64()
    }
    /// NaN, negatif ve `Duration`a sığmayan süre beklemez (`from_secs_f64` panik atardı; Python `ValueError` /
    /// `OverflowError` verir, çağıranlar yalnız sabit süre geçirir).
    fn sleep(&self, secs: f64) {
        if secs > 0.0 {
            if let Ok(d) = Duration::try_from_secs_f64(secs) {
                std::thread::sleep(d);
            }
        }
    }
}

impl DiagSink for DiagLog {
    fn log(&self, diag: &Diag) {
        DiagLog::log(self, diag.event, &diag.fields);
    }
}

/// `paths.REPO_DIR = str(Path(__file__).resolve().parents[2])`: `paths_py` (`<depo>/py/claudeops/paths.py`) bağlantıları
/// çözülerek iki üst dizin. Çözülemezse (dosya yok, yetersiz derinlik, UTF-8 olmayan yol) None.
pub fn repo_dir_of(paths_py: &Path) -> Option<String> {
    let real = std::fs::canonicalize(paths_py).ok()?;
    let repo = real.parent()?.parent()?.parent()?;
    repo.to_str().map(String::from)
}
