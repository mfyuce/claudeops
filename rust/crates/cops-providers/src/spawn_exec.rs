//! `spawn.py`nin yürütme kısmı (G9): `spawn_session` akışı (devam kimliği, eklenti MCP'si, kanca, komut kurulumu,
//! yan etkiler, hayalet oturum temizliği, gnome-terminal ya da penceresiz tmux), `_fallback_watchdog`, `open_window`,
//! `open_mirror_window`.
//!
//! Çekirdek SAF kalır: tmux ([`SpawnTmux`], gerçek uygulayıcı `cops-tmux`), pencere ([`Terminal`], gerçek
//! [`crate::real::launch::GnomeTerminal`]), saat ([`Clock`]), günlük ([`DiagSink`]), süreç taraması ([`SessionScan`], rs/proc
//! `find_sessions`), devam çözümü ([`ResumeResolver`], [`crate::Live`]) ve kancalar ([`crate::hooks::SpawnHooks`]) trait
//! arkasındadır. Süreç öldürme YOK: hayalet temizliği yalnız TAM adlı tmux oturumunu kapatır (`kill-session -t =ad:`).

use crate::cost::CostRefusal;
use crate::hooks::SpawnHooks;
use crate::live::Live;
use crate::probe::{BuildOutput, Diag, Paths, SpawnError};
use crate::provider::{Cli, McpSpec, Providers};
use crate::pyfmt::{splitlines, strip};
use crate::real::oserr;
use crate::resume::{ids_held_by_others, LiveSession};
use crate::spawn::{
    child_env, detect_display, gnome_terminal_argv, mirror_child_env, mirror_window_command,
    plan_spawn_with, window_command, SpawnRequest,
};
use crate::startup_desktop::StartupEnv;
use crate::tui::strip_ansi;
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;
use std::fmt;
use std::sync::Arc;
use std::thread::JoinHandle;

/// Her gnome-terminal denemesinden sonra tmux oturumunun belirmesi için beklenen süre.
pub const FALLBACK_ATTEMPT_WAIT_SECONDS: f64 = 4.0;
/// İlk deneme HARİÇ ek gnome-terminal denemesi; hepsi biterse penceresiz tmux'a düşülür.
pub const FALLBACK_RETRY_COUNT: u32 = 2;
/// Bekçinin yoklama aralığı.
pub const FALLBACK_POLL_SECONDS: f64 = 0.5;
/// Hayaletin son ekranından yakalanan geçmiş satırı.
pub const GHOST_CAPTURE_LINES: u32 = 40;

/// tmux sınırı. Gerçek uygulayıcı `cops-tmux` (`Tmux::cops()`); sözleşme `docs/rs-prov.md` G9. Hiçbir yöntem panik atmaz;
/// hedef her zaman TAM ad (`=ad:`), ön ek eşleşmesi yok.
pub trait SpawnTmux: Send + Sync {
    /// `tmux_available`: `PATH`te `tmux` var mı.
    fn available(&self) -> bool;
    /// `tmux_new_session_shell_fragment(ad, cwd, inner)` (ÇALIŞTIRILMAZ, gnome-terminal komutuna girer). `Err` =
    /// hedeflenemeyen ad (Python `ValueError`): spawn `spawn_bad_name` günlüğüyle hiçbir şey açmadan döner.
    fn new_session_fragment(&self, name: &str, cwd: &str, inner: &str) -> Result<String, String>;
    /// `tmux_attach_shell_fragment(ad)`; `Err` = hedeflenemeyen ad (Python `ValueError`): `open_window` reddedilir.
    fn attach_fragment(&self, name: &str) -> Result<String, String>;
    /// `tmux_spawn_direct`: `new-session -d -A`, `env` sürecin TÜM ortamı, `inner` tek argv elemanı (+ `; exec bash`).
    /// Her hata ve zaman aşımı false.
    fn spawn_direct(&self, name: &str, cwd: &str, inner: &str, env: &[(String, String)]) -> bool;
    /// `tmux_has_session`; hata false.
    fn has_session(&self, name: &str) -> bool;
    /// `tmux_ghost_session(ad)` (şimdiki saatle); her belirsizlik false.
    fn ghost_session(&self, name: &str) -> bool;
    /// `tmux_capture(ad, lines=)` (ANSI korunur); hata None.
    fn capture(&self, name: &str, lines: u32) -> Option<String>;
    /// `tmux_kill_session(ad)`: yalnız o oturum; hata yutulur.
    fn kill_session(&self, name: &str);
}

/// `subprocess.Popen` başlatılamadı ama `OSError` değil (Python istisnası yükselir).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LaunchError {
    /// `ValueError` (ör. argv/ortamda NUL: `embedded null byte`). Spawn ret sayılır.
    Value(String),
    /// `RuntimeError` (toplayıcı iş parçacığı başlatılamadı).
    Runtime(String),
}

/// Pencere sınırı: `shutil.which("gnome-terminal")`, `_launch_gnome_terminal` ve X soketi yoklaması.
pub trait Terminal: Send + Sync {
    /// `shutil.which("gnome-terminal") is not None` (çağıran sürecin `PATH`i).
    fn available(&self) -> bool;
    /// `Path(p).exists()` (`detect_display` için `/tmp/.X<n>-lock`, `/tmp/.X11-unix/X<n>`).
    fn path_exists(&self, path: &str) -> bool;
    /// Ateşle-unut: `argv` ortamı `env` (miras YOK), stdout/stderr boş; çocuk arka planda toplanır (zombi kalmaz).
    /// `Ok(true)` başladı, `Ok(false)` `OSError` (yok, izin).
    fn launch(&self, argv: &[String], env: &[(String, String)]) -> Result<bool, LaunchError>;
    /// `_window_titled`in okuması: `DISPLAY=display` ile `wmctrl -l` standart çıktısı (3 sn). Başlatılamaz, zaman aşımı ya
    /// da sıfır olmayan çıkış = None (bekçi eski davranışla yeniden dener). Zorunlu yöntem: sessiz varsayılan ikinci
    /// pencere açardı.
    fn window_list(&self, display: &str) -> Option<Vec<u8>>;
    /// `startup_desktop.startup_env(env, name)`: pencerenin hedef masaüstünde açılması için ortam (TBD#409). Varsayılan:
    /// özellik yok, ortam aynen.
    fn startup_env(&self, _name: &str, env: &[(String, String)]) -> StartupEnv {
        StartupEnv::unchanged(env)
    }
}

/// Bekçinin saati.
pub trait Clock: Send + Sync {
    /// `time.monotonic()`.
    fn monotonic(&self) -> f64;
    /// `time.sleep(s)`: [`Clock::monotonic`] en az `s` ilerler.
    fn sleep(&self, secs: f64);
}

/// `diag_log` (en iyi çaba).
pub trait DiagSink: Send + Sync {
    fn log(&self, diag: &Diag);
}

/// Canlı süreç taraması (rs/proc `find_sessions(measure_cpu=False)`; gerçek [`crate::real::scan::ProcScan`]):
/// (ad, `--resume` kimliği). None = tarama düştü. `preview` = kuru çalıştırma (Python `preview.active()`): taramanın
/// yan etkisi (öğrenilen agy kimliğinin yazımı) yapılmaz.
pub trait SessionScan {
    fn live_sessions(&self, preview: bool) -> Option<Vec<(String, Option<String>)>>;
}

/// `provider.resolve_resume_id(cwd, in_use=, session_name=)`.
pub trait ResumeResolver {
    fn resolve_resume_id(
        &self,
        cli: Cli,
        cwd: &str,
        in_use: &BTreeSet<String>,
        session_name: &str,
    ) -> Option<String>;
}

impl ResumeResolver for Live<'_> {
    fn resolve_resume_id(
        &self,
        cli: Cli,
        cwd: &str,
        in_use: &BTreeSet<String>,
        session_name: &str,
    ) -> Option<String> {
        Live::resolve_resume_id(self, cli, cwd, in_use, session_name)
    }
}

/// Günlük USD tavanı başlatma payını geri verme (`ucli_cost.release`; gerçek [`crate::real::ledger::CostLedger`]).
pub trait CostRelease {
    fn release(&self, session: &str);
}

impl<T: crate::real::probe::CostGate + ?Sized> CostRelease for T {
    fn release(&self, session: &str) {
        crate::real::probe::CostGate::release(self, session);
    }
}

/// Süreç başına paylaşılan başlatma sınırları (bekçi iş parçacığı bunların kopyasını taşır).
#[derive(Clone)]
pub struct Launcher {
    pub tmux: Arc<dyn SpawnTmux>,
    pub terminal: Arc<dyn Terminal>,
    pub clock: Arc<dyn Clock>,
    pub diag: Arc<dyn DiagSink>,
    /// Python `os.environ` (çağıran sürecin ortamı, sırasıyla); CLI kimlik değişkenleri burada süpürülür.
    pub parent_env: Vec<(String, String)>,
}

impl Launcher {
    fn log(&self, event: &'static str, fields: Vec<(&'static str, Value)>) {
        self.diag.log(&Diag { event, fields });
    }

    /// `_launch_gnome_terminal`: masaüstü yönlendirmesi ([`Terminal::startup_env`], her denemede yeniden) + pencere.
    /// Çağıranın `env`i değişmez (penceresiz tmux'a düşüş onu kullanır).
    fn launch_window(
        &self,
        name: &str,
        argv: &[String],
        env: &[(String, String)],
    ) -> Result<bool, LaunchError> {
        let startup = self.terminal.startup_env(name, env);
        if let Some(error) = startup.error {
            self.log(
                "startup_desktop_error",
                vec![("name", json!(name)), ("error", json!(error))],
            );
        }
        self.terminal.launch(argv, &startup.env)
    }

    /// `_window_titled`: `env`in ekranında başlığı TAM `name` olan pencere var mı. Ekran yoksa hiç sorulmaz.
    fn window_titled(&self, name: &str, env: &[(String, String)]) -> bool {
        let display = env
            .iter()
            .find(|(k, _)| k == "DISPLAY")
            .map_or("", |(_, v)| v.as_str());
        !display.is_empty()
            && self
                .terminal
                .window_list(display)
                .is_some_and(|out| window_listed(&String::from_utf8_lossy(&out), name))
    }

    /// `detect_display()`: ortam -> var olan X soketi/kilidi -> `:1`.
    pub fn detect_display(&self) -> String {
        let env = self
            .parent_env
            .iter()
            .find(|(k, _)| k == "DISPLAY")
            .map(|(_, v)| v.as_str());
        detect_display(env, &|p| self.terminal.path_exists(p))
    }

    fn display(&self, display: Option<&str>) -> String {
        display.map_or_else(|| self.detect_display(), String::from)
    }
}

/// `wmctrl -l` satırı `<kimlik> <masaüstü> <makine> <başlık>`: başlık (Python `split(None, 3)[3]`: baştaki boşluk atılır,
/// sondaki korunur) `name`e eşit mi.
fn window_listed(output: &str, name: &str) -> bool {
    crate::pyfmt::splitlines(output).into_iter().any(|line| {
        let mut rest = line.trim_start_matches(crate::pyfmt::py_isspace);
        for _ in 0..3 {
            let Some(gap) = rest.find(crate::pyfmt::py_isspace) else {
                return false;
            };
            rest = rest[gap..].trim_start_matches(crate::pyfmt::py_isspace);
        }
        !rest.is_empty() && rest == name
    })
}

/// `spawn_session` girdileri (Python varsayılanları [`StartRequest::new`]de).
#[derive(Debug, Clone)]
pub struct StartRequest {
    pub name: String,
    pub cwd: String,
    pub model: String,
    /// None = [`Launcher::detect_display`].
    pub display: Option<String>,
    pub permission_mode: String,
    pub effort: String,
    pub force_new: bool,
    pub prompt: Option<String>,
    pub dry_run: bool,
    pub cli: String,
    pub mcp_server: Option<McpSpec>,
    pub hidden: bool,
    pub cli_opts: Option<Map<String, Value>>,
}

impl StartRequest {
    pub fn new(
        name: impl Into<String>,
        cwd: impl Into<String>,
        model: impl Into<String>,
    ) -> StartRequest {
        StartRequest {
            name: name.into(),
            cwd: cwd.into(),
            model: model.into(),
            display: None,
            permission_mode: "auto".into(),
            effort: "max".into(),
            force_new: false,
            prompt: None,
            dry_run: false,
            cli: "claude".into(),
            mcp_server: None,
            hidden: false,
            cli_opts: None,
        }
    }
}

/// Bekçi iş parçacığı. Python'da `daemon=False`: kısa ömürlü çağıran (CLI) çıkmadan önce [`Watchdog::join`] ETMELİ, yoksa
/// yedek yol hiç çalışmaz; uzun yaşayan süreç bırakabilir.
#[must_use = "kısa ömürlü süreçte join edilmezse bekçi süreçle ölür"]
pub struct Watchdog(JoinHandle<()>);

impl Watchdog {
    /// Bekçi bitene dek bekler (en çok ~(RETRY+1) x WAIT + tmux zaman aşımları).
    pub fn join(self) {
        let _ = self.0.join();
    }

    pub fn is_finished(&self) -> bool {
        self.0.is_finished()
    }
}

/// Başarılı `spawn_session`.
pub struct Started {
    /// `new`, `resume:<id[:8]>` ya da kuru çalıştırmada `[dry-run] ...` satırı.
    pub kind: String,
    pub watchdog: Option<Watchdog>,
}

impl fmt::Debug for Started {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Started")
            .field("kind", &self.kind)
            .field("watchdog", &self.watchdog.is_some())
            .finish()
    }
}

/// `spawn_session` hatası.
#[derive(Debug, Clone, PartialEq)]
pub enum SpawnFailure {
    /// Python `ValueError` ailesi (anahtar yok, tavan, kanca reddi, `UcliError`, `Popen` `ValueError`): web temiz ret
    /// döner ([`SpawnFailure::web_refusal`]).
    Refused {
        error: SpawnError,
        cost: Option<CostRefusal>,
    },
    /// Başka istisna (`OSError` yazım hatası, `RuntimeError`): `class` = `type(e).__name__`, `message` = `str(e)`.
    Error { class: String, message: String },
}

impl SpawnFailure {
    /// `ucli_cost.refusal(e)` ([`crate::cost::refusal`]); `Error` için None (web genel hata yolunu kullanır:
    /// `{"ok": false, "error": "<sınıf>: <metin>"}`).
    pub fn web_refusal(&self) -> Option<Value> {
        match self {
            SpawnFailure::Refused { error, cost } => {
                Some(crate::cost::refusal(&error.0, cost.as_ref()))
            }
            SpawnFailure::Error { .. } => None,
        }
    }
}

impl fmt::Display for SpawnFailure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SpawnFailure::Refused { error, .. } => f.write_str(&error.0),
            SpawnFailure::Error { message, .. } => f.write_str(message),
        }
    }
}

impl std::error::Error for SpawnFailure {}

fn refused(message: impl Into<String>) -> SpawnFailure {
    SpawnFailure::Refused {
        error: SpawnError(message.into()),
        cost: None,
    }
}

fn launch_failure(e: LaunchError) -> SpawnFailure {
    match e {
        LaunchError::Value(m) => refused(m),
        LaunchError::Runtime(m) => SpawnFailure::Error {
            class: "RuntimeError".into(),
            message: m,
        },
    }
}

/// Komut kurulumunun dış sınırları.
pub struct SpawnDeps<'a> {
    pub providers: &'a Providers<'a>,
    pub resume: &'a dyn ResumeResolver,
    pub scan: &'a dyn SessionScan,
    pub hooks: &'a dyn SpawnHooks,
    /// Başarısız ya da kuru başlatmada pay geri verilir (Python'da bunu web çağıranları yapar; bkz. belge).
    pub cost: &'a dyn CostRelease,
}

/// `spawn_session`. Başarısız (`Err`) ya da kuru başlatmada maliyet payı burada geri verilir; başarıda pay KALIR
/// (oturum açılamazsa çağıran yine `release` eder, Python `web._start` gibi).
pub fn spawn_session(
    deps: &SpawnDeps<'_>,
    launcher: &Launcher,
    req: &StartRequest,
) -> Result<Started, SpawnFailure> {
    let out = run(deps, launcher, req);
    if req.dry_run || out.is_err() {
        deps.cost.release(&req.name);
    }
    out
}

fn run(
    deps: &SpawnDeps<'_>,
    launcher: &Launcher,
    req: &StartRequest,
) -> Result<Started, SpawnFailure> {
    let p = deps.providers;
    let cli = Cli::parse(&req.cli);
    let display = launcher.display(req.display.as_deref());
    let resume_id = if req.force_new {
        None
    } else {
        let live = deps.scan.live_sessions(req.dry_run);
        let rows: Option<Vec<LiveSession<'_>>> = live.as_ref().map(|v| {
            v.iter()
                .map(|(name, sid)| LiveSession {
                    name,
                    sid: sid.as_deref(),
                })
                .collect()
        });
        let in_use = ids_held_by_others(&req.name, rows.as_deref());
        deps.resume
            .resolve_resume_id(cli, &req.cwd, &in_use, &req.name)
    };
    // K14: eklenti MCP'si yalnız claude'da ve açıkça `mcp_server` verilmediyse (ham ad; bilinmeyen CLI claude sağlayıcısı
    // kullanır ama eklenti almaz).
    let extension_mcp = if req.mcp_server.is_none() && req.cli == "claude" {
        deps.hooks.session_mcp(&req.cwd)
    } else {
        None
    };
    let spawn_req = SpawnRequest {
        name: req.name.clone(),
        cwd: req.cwd.clone(),
        model: req.model.clone(),
        permission_mode: req.permission_mode.clone(),
        effort: req.effort.clone(),
        resume_id,
        prompt: req.prompt.clone(),
        cli: req.cli.clone(),
        mcp_server: req.mcp_server.clone(),
        extension_mcp,
        hook_env: Vec::new(),
        cli_opts: req.cli_opts.clone(),
        dry_run: req.dry_run,
    };
    let mut out = BuildOutput::default();
    let mut hook = |o: &mut BuildOutput| {
        deps.hooks
            .spawn_env(&req.cli, &req.name, &req.cwd, req.dry_run, o)
            .map_err(|r| SpawnError(r.to_string()))
    };
    let plan = plan_spawn_with(p, &spawn_req, &mut hook, &mut out);
    // Python'da günlük ve yazımlar komut kurulurken olur: hata olsa da o ana dek birikenler bırakılır.
    for d in &out.diags {
        launcher.diag.log(d);
    }
    for effect in &out.effects {
        p.probe.apply_now(effect).map_err(|e| SpawnFailure::Error {
            class: oserr::class_name(&e.error).into(),
            message: e.to_string(),
        })?;
    }
    let plan = plan.map_err(|error| SpawnFailure::Refused {
        error,
        cost: out.cost_refusal.clone(),
    })?;
    if req.dry_run {
        return Ok(Started {
            kind: plan.dry_run_line(&req.cwd),
            watchdog: None,
        });
    }

    // NUL taşıyan açılış başlayamaz (`Popen` reddi): eski oturuma dokunulmaz.
    let launchable = [&req.name, &req.cwd, &plan.inner, &display]
        .iter()
        .all(|s| !s.contains('\0'));
    if launchable {
        reclaim_ghost_session(launcher, &req.name, &req.cli);
    }

    let env = child_env(launcher.parent_env.iter().cloned(), &display);
    // gnome-terminal yoksa (masaüstüsüz sunucu) deneme/bekçi yok: doğrudan penceresiz tmux.
    let no_gt = !launcher.terminal.available();
    if req.hidden || no_gt {
        if no_gt {
            launcher.log(
                "spawn_no_gnome_terminal",
                vec![
                    ("name", json!(req.name)),
                    ("cwd", json!(req.cwd)),
                    ("tmux", json!(launcher.tmux.available())),
                ],
            );
        }
        if launcher.tmux.available() {
            let ok = launcher
                .tmux
                .spawn_direct(&req.name, &req.cwd, &plan.inner, &env);
            let event = if req.hidden && !no_gt {
                "spawn_hidden"
            } else {
                "spawn_direct_headless"
            };
            launcher.log(
                event,
                vec![
                    ("name", json!(req.name)),
                    ("cwd", json!(req.cwd)),
                    ("ok", json!(ok)),
                ],
            );
        } else if !no_gt {
            // gizli başlatma + tmux yok: hiçbir şey açılmadı (gtsiz dalda iz zaten yukarıda)
            launcher.log(
                "spawn_hidden_no_tmux",
                vec![("name", json!(req.name)), ("cwd", json!(req.cwd))],
            );
        }
        return Ok(Started {
            kind: plan.kind,
            watchdog: None,
        });
    }

    let fragment = if launcher.tmux.available() {
        match launcher
            .tmux
            .new_session_fragment(&req.name, &req.cwd, &plan.inner)
        {
            Ok(f) => Some(f),
            Err(_) => {
                // tmux'ta hedeflenemeyen ad: hiçbir şey açılmaz (pencere de bekçi de yok); çağıran süreç yokluğundan
                // "olmadı" görür (Python `spawn_bad_name`, `bb26564e`).
                launcher.log(
                    "spawn_bad_name",
                    vec![("name", json!(req.name)), ("cwd", json!(req.cwd))],
                );
                return Ok(Started {
                    kind: plan.kind,
                    watchdog: None,
                });
            }
        }
    } else {
        None
    };
    let window_cmd = window_command(&plan.inner, fragment.as_deref());
    let argv = gnome_terminal_argv(&req.name, &req.cwd, &window_cmd);
    if !launcher
        .launch_window(&req.name, &argv, &env)
        .map_err(launch_failure)?
    {
        launcher.log(
            "spawn_launch_failed",
            vec![("name", json!(req.name)), ("cwd", json!(req.cwd))],
        );
    }
    let watchdog = if launcher.tmux.available() {
        let l = launcher.clone();
        let (name, cwd, inner) = (req.name.clone(), req.cwd.clone(), plan.inner.clone());
        let handle = std::thread::Builder::new()
            .name("cops-spawn-watchdog".into())
            .spawn(move || fallback_watchdog(&l, &name, &cwd, &inner, &env, &window_cmd))
            .map_err(|_| SpawnFailure::Error {
                class: "RuntimeError".into(),
                message: "can't start new thread".into(),
            })?;
        Some(Watchdog(handle))
    } else {
        None
    };
    Ok(Started {
        kind: plan.kind,
        watchdog,
    })
}

/// `_reclaim_ghost_session` (PROC-03): CLI'si çıkmış, `exec bash`le canlı kalan TAM adlı tmux oturumu spawn'dan önce
/// kapatılır. Ekran metni sır taşıyabilir: `spawn_ghost_reclaimed` günlüğüne HİÇ girmez, yalnız boş olmayan satır ve
/// karakter sayısı yazılır. `shell` sağlayıcısı (ham ad) hariç. Hayalet kararı belirsizse dokunulmaz. Python'daki `spawn_ghost_reclaim_error` dalı yok: trait yöntemleri hata yükseltmez.
pub fn reclaim_ghost_session(launcher: &Launcher, name: &str, cli: &str) {
    if cli == "shell" || !launcher.tmux.available() || !launcher.tmux.ghost_session(name) {
        return;
    }
    let screen = strip_ansi(
        &launcher
            .tmux
            .capture(name, GHOST_CAPTURE_LINES)
            .unwrap_or_default(),
    );
    let kept: Vec<&str> = splitlines(&screen)
        .into_iter()
        .filter(|l| !strip(l).is_empty())
        .collect();
    let chars = kept.join("\n").chars().count();
    launcher.tmux.kill_session(name);
    launcher.log(
        "spawn_ghost_reclaimed",
        vec![
            ("name", json!(name)),
            ("cli", json!(cli)),
            ("screen_lines", json!(kept.len())),
            ("screen_chars", json!(chars)),
        ],
    );
}

/// `_fallback_watchdog`: ilk gnome-terminal denemesi tmux oturumunu getirmezse [`FALLBACK_RETRY_COUNT`] kez yeniden
/// dener (bu başlıkta pencere zaten açıksa yenisini açmadan bekler, `spawn_retry_window_exists`); hepsi biterse ANCAK O ZAMAN penceresiz tmux. `Popen` istisnası bekçiyi bitirir; `ValueError`
/// `spawn_retry_launch_error` günlüğüne yalnız sınıf adıyla yazılır (metin argv/ortam değeri taşıyabilir).
pub fn fallback_watchdog(
    launcher: &Launcher,
    name: &str,
    cwd: &str,
    inner: &str,
    env: &[(String, String)],
    window_cmd: &str,
) {
    let (tmux, clock) = (&launcher.tmux, &launcher.clock);
    for attempt in 0..=FALLBACK_RETRY_COUNT {
        let deadline = clock.monotonic() + FALLBACK_ATTEMPT_WAIT_SECONDS;
        while clock.monotonic() < deadline {
            if tmux.has_session(name) {
                if attempt > 0 {
                    launcher.log(
                        "spawn_retry_succeeded",
                        vec![
                            ("name", json!(name)),
                            ("cwd", json!(cwd)),
                            ("attempt", json!(attempt)),
                        ],
                    );
                }
                return;
            }
            clock.sleep(FALLBACK_POLL_SECONDS);
        }
        if attempt < FALLBACK_RETRY_COUNT {
            let next = attempt + 1;
            if launcher.window_titled(name, env) {
                launcher.log(
                    "spawn_retry_window_exists",
                    vec![
                        ("name", json!(name)),
                        ("cwd", json!(cwd)),
                        ("attempt", json!(next)),
                    ],
                );
                continue;
            }
            launcher.log(
                "spawn_retry",
                vec![
                    ("name", json!(name)),
                    ("cwd", json!(cwd)),
                    ("attempt", json!(next)),
                ],
            );
            match launcher.launch_window(name, &gnome_terminal_argv(name, cwd, window_cmd), env) {
                Ok(true) => {}
                Ok(false) => launcher.log(
                    "spawn_retry_launch_failed",
                    vec![
                        ("name", json!(name)),
                        ("cwd", json!(cwd)),
                        ("attempt", json!(next)),
                    ],
                ),
                Err(LaunchError::Value(_)) => {
                    launcher.log(
                        "spawn_retry_launch_error",
                        vec![
                            ("name", json!(name)),
                            ("cwd", json!(cwd)),
                            ("attempt", json!(next)),
                            ("error", json!("ValueError")),
                        ],
                    );
                    return;
                }
                // Python `RuntimeError`ı yakalamaz (iş parçacığı izini stderr'e basar).
                Err(LaunchError::Runtime(_)) => return,
            }
        }
    }
    if tmux.has_session(name) {
        return;
    }
    let ok = tmux.spawn_direct(name, cwd, inner, env);
    launcher.log(
        "spawn_fallback_used",
        vec![
            ("name", json!(name)),
            ("cwd", json!(cwd)),
            ("ok", json!(ok)),
        ],
    );
}

/// `open_window`: VAR OLAN tmux oturumuna yeni gnome-terminal penceresi (CLI yeniden başlamaz). Oturum yoksa false.
pub fn open_window(
    launcher: &Launcher,
    name: &str,
    cwd: &str,
    display: Option<&str>,
) -> Result<bool, SpawnFailure> {
    if !launcher.tmux.has_session(name) {
        return Ok(false);
    }
    let display = launcher.display(display);
    let env = child_env(launcher.parent_env.iter().cloned(), &display);
    let fragment = launcher.tmux.attach_fragment(name).map_err(refused)?;
    let argv = gnome_terminal_argv(name, cwd, &window_command("", Some(&fragment)));
    launcher
        .launch_window(name, &argv, &env)
        .map_err(launch_failure)
}

/// `open_mirror_window`: `cops watch <host>:<ad> --port <port>` çalıştıran pencere (tmux'a bağlanmaz). `CLAUDEOPS_DIR`
/// süpürmeden sonra geri konur (görüntüleyici aynı panelin token'ını okur).
pub fn open_mirror_window(
    launcher: &Launcher,
    paths: &Paths,
    host: &str,
    name: &str,
    port: u16,
    display: Option<&str>,
) -> Result<bool, SpawnFailure> {
    let display = launcher.display(display);
    let env = mirror_child_env(
        launcher.parent_env.iter().cloned(),
        &display,
        &paths.claudeops_dir,
    );
    let window_cmd = mirror_window_command(&paths.repo_dir, host, name, port);
    let spec = format!("{host}:{name}");
    let argv = gnome_terminal_argv(&spec, &paths.home, &window_cmd);
    launcher
        .launch_window(&spec, &argv, &env)
        .map_err(launch_failure)
}
