//! `searxng.py`nin SPAWN YOLU (`ensure_search_url`): bir ucli oturumunun `--search-url`ü. GEÇİCİ köprü (TBD#88: ucli
//! aramayı Docker'sız getirince kalkar), bu yüzden dar tutulur.
//!
//! Spawn yolu imaj ÇEKMEZ ve kapsayıcı KURMAZ: yavaş kurulum ayrık bir süreçte, Python komutuyla (`cops searxng
//! provision`) yürür ([`Provision`]); kurulum, durum, durdurma ve silme komutları Python'da kalır. Durum dosyası
//! (`searxng/state.json`), onun yazım kilidi (`state.json.lock`) ve kurulum kilidi (`searxng/.lock`) iki dilde ortaktır.
//!
//! Sağlık yoklaması yalnız `127.0.0.1`e gider: proxy yok, yönlendirme izlenmez.

use crate::pyfmt::{parse_int, splitlines, strip};
use crate::pyjson::Py;
use crate::real::diaglog::DiagLog;
use crate::real::docs::DOC_MAX_BYTES;
use crate::real::ledger::{system_clock, WallClock};
use crate::real::lock::{FileLock, LOCK_TIMEOUT};
use crate::real::probe::SearchUrl;
use crate::real::process::{self, Capture, RunError, Spec};
use crate::real::{effects, fsio, oserr, pathexec, Env};
use serde_json::{json, Value};
use sha1::{Digest, Sha1};
use std::fs::{OpenOptions, TryLockError};
use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::process::CommandExt;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::{Duration, Instant};

pub const LABEL_KEY: &str = "claudeops.managed";
pub const LABEL_VALUE: &str = "searxng";
const CONTAINER_PORT_KEY: &str = "8080/tcp";
pub const HEALTH_TIMEOUT: Duration = Duration::from_millis(1500);
pub const INSPECT_TIMEOUT: Duration = Duration::from_secs(5);
pub const START_TIMEOUT: Duration = Duration::from_secs(15);
pub const READY_WAIT: Duration = Duration::from_secs(8);
const READY_POLL: Duration = Duration::from_millis(400);
/// Başarısız kurulumdan sonra bu süre (sn) yenisi başlatılmaz.
pub const FAIL_COOLDOWN_S: f64 = 600.0;
/// Docker kullanılamıyorsa bu süre tekrar yoklanmaz.
pub const DOCKER_DOWN_TTL: Duration = Duration::from_secs(60);
/// Ayrık kurulum süreci kilidi alana dek (sn) ikinci süreç başlatılmaz.
pub const KICK_WINDOW_S: f64 = 20.0;
const DOCKER_OUTPUT_MAX: u64 = 4 << 20;

/// `search_url(port)`.
pub fn search_url_for(port: u16) -> String {
    format!("http://127.0.0.1:{port}/search")
}

/// `getpass.getuser()`: `LOGNAME`, `USER`, `LNAME`, `USERNAME`, yoksa parola veritabanı, yoksa kullanıcı numarası.
pub fn owner(env: &Env) -> String {
    ["LOGNAME", "USER", "LNAME", "USERNAME"]
        .iter()
        .find_map(|k| env.get(k).filter(|v| !v.is_empty()))
        .or_else(passwd_name)
        .unwrap_or_else(|| uid().to_string())
}

fn uid() -> libc::uid_t {
    // SAFETY: `getuid` her zaman başarılı, argümansız sistem çağrısı.
    unsafe { libc::getuid() }
}

fn passwd_name() -> Option<String> {
    // SAFETY: `passwd` yalnız tam sayı ve işaretçi alanlıdır; sıfır geçerli başlangıçtır.
    let mut record: libc::passwd = unsafe { std::mem::zeroed() };
    let mut buffer = vec![0 as libc::c_char; 16 * 1024];
    let mut found: *mut libc::passwd = std::ptr::null_mut();
    // SAFETY: bütün işaretçiler bu çağrıya özel ve geçerli; tampon boyu doğru veriliyor.
    let rc = unsafe {
        libc::getpwuid_r(
            uid(),
            &mut record,
            buffer.as_mut_ptr(),
            buffer.len(),
            &mut found,
        )
    };
    if rc != 0 || found.is_null() || record.pw_name.is_null() {
        return None;
    }
    // SAFETY: başarılı çağrıda `pw_name` tampon içinde NUL ile biten dizgedir.
    let name = unsafe { std::ffi::CStr::from_ptr(record.pw_name) };
    name.to_str().ok().map(String::from)
}

/// `container_name()`: `claudeops-searxng-<kullanıcı>`; durum dizini varsayılan değilse dizin özeti eklenir.
pub fn container_name(owner: &str, home: &str, claudeops_dir: &str, cwd: &str) -> String {
    let mut safe = String::new();
    let mut gap = false;
    for c in owner.to_lowercase().chars() {
        if c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, '_' | '.' | '-') {
            safe.push(c);
            gap = false;
        } else if !gap {
            safe.push('-');
            gap = true;
        }
    }
    let trimmed = safe.trim_matches(|c| matches!(c, '-' | '_' | '.'));
    let safe = if trimmed.is_empty() {
        uid().to_string()
    } else {
        trimmed.to_string()
    };
    let mut name = format!("claudeops-searxng-{safe}");
    let default = pathexec::realpath(&format!("{home}/.claude/claudeops"), cwd);
    let actual = pathexec::realpath(claudeops_dir, cwd);
    if actual != default {
        let digest: String = Sha1::digest(actual.as_bytes())
            .iter()
            .take(4)
            .map(|b| format!("{b:02x}"))
            .collect();
        name.push('-');
        name.push_str(&digest);
    }
    name
}

/// `healthy(port)`: `GET /healthz` 200 mü. Süre TOPLAM süredir.
pub fn healthy(port: u16, timeout: Duration) -> bool {
    probe_health(port, timeout).unwrap_or(false)
}

fn probe_health(port: u16, timeout: Duration) -> io::Result<bool> {
    let deadline = Instant::now() + timeout;
    let left = || {
        let d = deadline.saturating_duration_since(Instant::now());
        if d.is_zero() {
            Err(io::Error::from(io::ErrorKind::TimedOut))
        } else {
            Ok(d)
        }
    };
    let mut stream =
        TcpStream::connect_timeout(&SocketAddr::from((Ipv4Addr::LOCALHOST, port)), left()?)?;
    stream.set_write_timeout(Some(left()?))?;
    let request = format!(
        "GET /healthz HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUser-Agent: claudeops\r\nConnection: close\r\n\r\n"
    );
    stream.write_all(request.as_bytes())?;
    // yalnız durum satırı gerekir
    let mut head = Vec::new();
    let mut buf = [0u8; 512];
    while !head.contains(&b'\n') && head.len() < 8192 {
        stream.set_read_timeout(Some(left()?))?;
        let n = stream.read(&mut buf)?;
        if n == 0 {
            break;
        }
        head.extend_from_slice(&buf[..n]);
    }
    let line = head.split(|b| *b == b'\n').next().unwrap_or_default();
    let mut words = line
        .split(|b| b.is_ascii_whitespace())
        .filter(|w| !w.is_empty());
    Ok(words.next().is_some_and(|v| v.starts_with(b"HTTP/")) && words.next() == Some(b"200"))
}

/// Ayrık kurulum süreci.
#[derive(Debug, Clone)]
pub struct Provision {
    pub argv: Vec<String>,
    pub cwd: String,
}

impl Provision {
    /// `<python> -m claudeops searxng provision`, `<depo>/py` dizininde.
    pub fn python(python: &str, repo_dir: &str) -> Provision {
        let argv = [python, "-m", "claudeops", "searxng", "provision"]
            .map(String::from)
            .to_vec();
        Provision {
            argv,
            cwd: format!("{repo_dir}/py"),
        }
    }
}

/// `Box`: kapsayıcının durumu.
#[derive(Debug, Default)]
struct Container {
    exists: bool,
    /// Etiket bizim mi (değilse DOKUNULMAZ).
    ours: bool,
    running: bool,
    status: String,
    port: Option<u16>,
}

/// Spawn yolunu kesen hatalar.
enum Fail {
    /// `DockerUnavailable`.
    Docker(String),
    Other(String),
}

/// `_tail`: son boş olmayan satır, en çok 240 karakter.
fn tail(text: &str) -> String {
    let last = splitlines(strip(text))
        .into_iter()
        .map(strip)
        .rfind(|l| !l.is_empty())
        .unwrap_or("");
    last.chars().take(240).collect()
}

fn clip(text: &str) -> String {
    text.chars().take(200).collect()
}

/// `_int`: 1..=65535 kapı numarası.
fn port_of(v: Option<&Py>) -> Option<u16> {
    let n = match v? {
        Py::Int(i) => *i,
        Py::Bool(b) => i64::from(*b),
        Py::Float(f) if f.is_finite() && f.abs() < 1e9 => f.trunc() as i64,
        Py::Str(s) => parse_int(s)?,
        _ => return None,
    };
    u16::try_from(n).ok().filter(|p| *p > 0)
}

/// `a or {}` + nesne olma şartı.
fn object_or_empty(v: Option<&Py>) -> Option<Py> {
    match v.filter(|v| v.truthy()) {
        None => Some(Py::Object(Vec::new())),
        Some(v) if v.is_object() => Some(v.clone()),
        Some(_) => None,
    }
}

fn parse_inspect(stdout: &str) -> Option<Container> {
    let Py::Array(list) = Py::parse(stdout)? else {
        return None;
    };
    let info = list.first().filter(|i| i.is_object())?;
    let labels = object_or_empty(object_or_empty(info.get("Config"))?.get("Labels"))?;
    let state = object_or_empty(info.get("State"))?;
    let bindings = object_or_empty(object_or_empty(info.get("HostConfig"))?.get("PortBindings"))?;
    let port = match bindings.get(CONTAINER_PORT_KEY).filter(|v| v.truthy()) {
        None => None,
        Some(Py::Array(a)) => port_of(object_or_empty(a.first())?.get("HostPort")),
        Some(_) => return None,
    };
    Some(Container {
        exists: true,
        ours: labels.get(LABEL_KEY).and_then(Py::as_str) == Some(LABEL_VALUE),
        running: state.get("Running").is_some_and(Py::truthy),
        status: state
            .get("Status")
            .filter(|s| s.truthy())
            .map(Py::py_str)
            .unwrap_or_default(),
        port,
    })
}

type Health = Arc<dyn Fn(u16) -> bool + Send + Sync>;

/// Yönetilen yerel SearXNG'nin spawn yolu. Süreç başına TEK örnek (docker kapalı önbelleği örneğe aittir).
pub struct ManagedSearch {
    state_dir: String,
    container: String,
    env: Env,
    diag: DiagLog,
    provision: Provision,
    health: Health,
    clock: WallClock,
    ready_wait: Duration,
    down_until: Mutex<Option<Instant>>,
}

impl ManagedSearch {
    /// `home` = `os.path.expanduser("~")`, `claudeops_dir` = durum dizini ([`crate::Paths`]).
    pub fn new(
        home: &str,
        claudeops_dir: &str,
        env: Env,
        diag: DiagLog,
        provision: Provision,
    ) -> ManagedSearch {
        let container = container_name(&owner(&env), home, claudeops_dir, "/");
        ManagedSearch {
            state_dir: format!("{claudeops_dir}/searxng"),
            container,
            env,
            diag,
            provision,
            health: Arc::new(|port| healthy(port, HEALTH_TIMEOUT)),
            clock: system_clock(),
            ready_wait: READY_WAIT,
            down_until: Mutex::new(None),
        }
    }

    /// Sağlık yoklaması yerine başka kaynak (test).
    pub fn with_health(
        mut self,
        health: impl Fn(u16) -> bool + Send + Sync + 'static,
    ) -> ManagedSearch {
        self.health = Arc::new(health);
        self
    }

    pub fn with_clock(mut self, clock: WallClock) -> ManagedSearch {
        self.clock = clock;
        self
    }

    pub fn with_ready_wait(mut self, wait: Duration) -> ManagedSearch {
        self.ready_wait = wait;
        self
    }

    pub fn container(&self) -> &str {
        &self.container
    }

    fn state_path(&self) -> String {
        format!("{}/state.json", self.state_dir)
    }

    fn read_state(&self) -> Vec<(String, Py)> {
        let parsed = fsio::read_bytes(&self.state_path(), DOC_MAX_BYTES)
            .and_then(|b| Py::parse(std::str::from_utf8(&b).ok()?));
        match parsed {
            Some(Py::Object(o)) => o,
            _ => Vec::new(),
        }
    }

    /// `_update_state`: en iyi çaba; kilit alınamazsa yazılmaz.
    fn update_state(&self, key: &str, value: Py) {
        let path = self.state_path();
        let Ok(_lock) = FileLock::acquire(&path, "/", LOCK_TIMEOUT) else {
            return;
        };
        let mut state = self.read_state();
        match state.iter_mut().find(|(k, _)| k == key) {
            Some(slot) => slot.1 = value,
            None => state.push((key.to_string(), value)),
        }
        let _ = effects::atomic_write_text(&path, &Py::Object(state).dumps_pretty(), Some(0o600));
    }

    fn log(&self, event: &str, fields: &[(&str, Value)]) {
        self.diag.log(event, fields);
    }

    /// Bu modüldeki tek docker çağrı noktası. Komutun kendi hatası (rc != 0) hata DEĞİL.
    fn docker(&self, args: &[&str], timeout: Duration) -> Result<(i32, String, String), Fail> {
        let exe = pathexec::which(&self.env, "docker")
            .ok_or_else(|| Fail::Docker("docker PATH'te yok".into()))?;
        let argv: Vec<String> = std::iter::once(exe.as_str())
            .chain(args.iter().copied())
            .map(String::from)
            .collect();
        let spec = Spec {
            argv: &argv,
            cwd: None,
            env: &self.env,
            timeout,
            stdout: Capture::Bounded(DOCKER_OUTPUT_MAX),
            stderr: Capture::Tail(64 * 1024),
        };
        let out = process::run(&spec).map_err(|e| {
            Fail::Docker(match e {
                RunError::Timeout => format!(
                    "docker {} {} sn içinde bitmedi",
                    args.first().copied().unwrap_or(""),
                    timeout.as_secs_f64()
                ),
                RunError::Spawn(io) | RunError::Io(io) => oserr::text(&io, &exe),
                RunError::Overflow => "docker çıktısı sınırı aştı".into(),
            })
        })?;
        let text = |b: &[u8]| {
            String::from_utf8_lossy(b)
                .replace("\r\n", "\n")
                .replace('\r', "\n")
        };
        Ok((out.code, text(&out.stdout), text(&out.stderr)))
    }

    fn inspect(&self) -> Result<Container, Fail> {
        let (code, stdout, stderr) =
            self.docker(&["container", "inspect", &self.container], INSPECT_TIMEOUT)?;
        if code != 0 {
            if format!("{stderr}{stdout}")
                .to_lowercase()
                .contains("no such")
            {
                return Ok(Container::default());
            }
            let reason = tail(if stderr.is_empty() { &stdout } else { &stderr });
            return Err(Fail::Docker(if reason.is_empty() {
                format!("inspect rc={code}")
            } else {
                reason
            }));
        }
        parse_inspect(&stdout).ok_or_else(|| Fail::Docker("inspect çıktısı ayrıştırılamadı".into()))
    }

    fn wait_healthy(&self, port: u16) -> bool {
        let deadline = Instant::now() + self.ready_wait;
        loop {
            if (self.health)(port) {
                return true;
            }
            if Instant::now() >= deadline {
                return false;
            }
            std::thread::sleep(READY_POLL);
        }
    }

    /// Kurulum kilidi şu an boş mu (`_exclusive`; bloklamaz, hemen bırakır).
    fn provision_idle(&self) -> io::Result<bool> {
        effects::makedirs(&self.state_dir, 0o777).map_err(|(_, e)| e)?;
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_NOCTTY)
            .open(format!("{}/.lock", self.state_dir))?;
        match file.try_lock() {
            Ok(()) => Ok(true),
            Err(TryLockError::WouldBlock) => Ok(false),
            Err(TryLockError::Error(e)) => Err(e),
        }
    }

    /// `_spawn_provision_child`: yeni oturumda, çıktısı `provision.log`a.
    fn spawn_provision(&self) -> bool {
        let log = effects::makedirs(&self.state_dir, 0o777)
            .ok()
            .and_then(|()| {
                OpenOptions::new()
                    .append(true)
                    .create(true)
                    .mode(0o666)
                    .custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY)
                    .open(format!("{}/provision.log", self.state_dir))
                    .ok()
            });
        let output = || {
            log.as_ref()
                .and_then(|f| f.try_clone().ok())
                .map_or_else(Stdio::null, Stdio::from)
        };
        let Some((program, args)) = self.provision.argv.split_first() else {
            return false;
        };
        let mut cmd = Command::new(program);
        cmd.args(args)
            .current_dir(&self.provision.cwd)
            .stdin(Stdio::null())
            .stdout(output())
            .stderr(output());
        self.env.apply(&mut cmd);
        // SAFETY: `fork` ile `exec` arasında yalnız eşzamansız-sinyal-güvenli `setsid` çağrılır, bellek ayrılmaz.
        unsafe {
            cmd.pre_exec(|| {
                if libc::setsid() < 0 {
                    return Err(io::Error::last_os_error());
                }
                Ok(())
            });
        }
        match cmd.spawn() {
            Ok(mut child) => {
                // zombi kalmasın; iş parçacığı açılamazsa süreç bittiğinde ana süreçle toplanır
                let _ = std::thread::Builder::new()
                    .name("searxng-provision".into())
                    .spawn(move || child.wait());
                true
            }
            Err(e) => {
                self.log(
                    "searxng_provision_spawn_failed",
                    &[("error", json!(clip(&oserr::text(&e, program))))],
                );
                false
            }
        }
    }

    /// `_kick_provision`.
    fn kick(&self, session: &str) -> Result<(), Fail> {
        let state = self.read_state();
        let now = (self.clock)();
        // `isinstance(x, (int, float))` (bool dahil) ve `0 <= now - x < pencere`
        let within = |key: &str, window: f64| {
            let at = state
                .iter()
                .find(|(k, _)| k == key)
                .and_then(|(_, v)| match v {
                    Py::Int(i) => Some(*i as f64),
                    Py::Float(f) => Some(*f),
                    Py::Bool(b) => Some(f64::from(u8::from(*b))),
                    _ => None,
                });
            at.is_some_and(|at| (0.0..window).contains(&(now - at)))
        };
        if within("provision_failed_at", FAIL_COOLDOWN_S) {
            self.log("searxng_provision_cooldown", &[("name", json!(session))]);
            return Ok(());
        }
        if within("provision_started_at", KICK_WINDOW_S) {
            return Ok(());
        }
        if !self
            .provision_idle()
            .map_err(|e| Fail::Other(oserr::repr(&e)))?
        {
            return Ok(());
        }
        self.update_state("provision_started_at", Py::Float(now));
        if self.spawn_provision() {
            self.log("searxng_provision_started", &[("name", json!(session))]);
        }
        Ok(())
    }

    fn mark_down(&self) {
        *self
            .down_until
            .lock()
            .unwrap_or_else(PoisonError::into_inner) = Some(Instant::now() + DOCKER_DOWN_TTL);
    }

    fn ensure(&self, session: &str, preview: bool) -> Result<Option<String>, Fail> {
        let saved = port_of(
            self.read_state()
                .iter()
                .find(|(k, _)| k == "port")
                .map(|(_, v)| v),
        );
        if let Some(port) = saved.filter(|p| (self.health)(*p)) {
            return Ok(Some(search_url_for(port)));
        }
        // kuru çalıştırma docker'a dokunmaz
        if preview {
            return Ok(None);
        }
        let down = *self
            .down_until
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if down.is_some_and(|until| Instant::now() < until) {
            return Ok(None);
        }
        let found = self.inspect()?;
        if found.exists && !found.ours {
            self.log(
                "searxng_name_conflict",
                &[
                    ("name", json!(session)),
                    ("container", json!(self.container)),
                ],
            );
            return Ok(None);
        }
        let Some(port) = found.port.filter(|_| found.exists) else {
            self.kick(session)?;
            return Ok(None);
        };
        if !found.running {
            let (code, stdout, stderr) = self.docker(&["start", &self.container], START_TIMEOUT)?;
            if code != 0 {
                let reason = tail(if stderr.is_empty() { &stdout } else { &stderr });
                self.log(
                    "searxng_start_failed",
                    &[("name", json!(session)), ("error", json!(reason))],
                );
                self.kick(session)?;
                return Ok(None);
            }
            self.log(
                "searxng_started",
                &[("name", json!(session)), ("port", json!(port))],
            );
        }
        if self.wait_healthy(port) {
            self.update_state("port", Py::Int(i64::from(port)));
            return Ok(Some(search_url_for(port)));
        }
        self.log(
            "searxng_not_ready",
            &[
                ("name", json!(session)),
                ("port", json!(port)),
                ("status", json!(found.status)),
            ],
        );
        if matches!(found.status.as_str(), "restarting" | "dead") {
            self.kick(session)?;
        }
        Ok(None)
    }
}

impl SearchUrl for ManagedSearch {
    /// `ensure_search_url`: hata hiçbir zaman çağırana çıkmaz (web araması yüzünden spawn kırılmaz).
    fn search_url(&self, session: &str, preview: bool) -> Option<String> {
        match self.ensure(session, preview) {
            Ok(url) => url,
            Err(Fail::Docker(reason)) => {
                self.mark_down();
                self.log(
                    "searxng_unavailable",
                    &[("name", json!(session)), ("reason", json!(clip(&reason)))],
                );
                None
            }
            Err(Fail::Other(error)) => {
                self.log(
                    "searxng_ensure_error",
                    &[("name", json!(session)), ("error", json!(clip(&error)))],
                );
                None
            }
        }
    }
}
