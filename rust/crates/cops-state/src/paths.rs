//! Durum dizini çözümü ve sabit yollar (Python `paths.py`): `CLAUDEOPS_DIR` (boş değilse), yoksa test koşucusu altında
//! süreç başına GEÇİCİ dizin, yoksa `$HOME/.claude/claudeops`.
//!
//! Test algısı (Python `_under_test_runner` karşılığı): ikili cargo'nun test ikilisiyse (`.../deps/<ad>-<16 hex>` ya da
//! rustdoc test dizini). `CLAUDEOPS_TEST_REAL_DIR=1` kapatır. Testin ALT SÜREÇ olarak başlattığı normal ikili test sayılmaz:
//! ona dizini [`StateDir::apply_env`] ile ver.
//!
//! CANLI DİZİN KORUMASI (H16): test ikilisi altında canlı durum dizinine (`<ev>/.claude/claudeops`) yazan her yol
//! [`guard_write`] ile PANİK verir (yazımdan ÖNCE). `$HOME` yalnız bu modülde okunur (`tests/scan.rs` denetler).
use std::cell::RefCell;
use std::ffi::{CStr, CString, OsString};
use std::io;
use std::os::unix::ffi::OsStringExt;
use std::path::{Component, Path, PathBuf};
use std::sync::OnceLock;

pub const ENV_DIR: &str = "CLAUDEOPS_DIR";
pub const ENV_TEST_REAL: &str = "CLAUDEOPS_TEST_REAL_DIR";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StateDir {
    root: PathBuf,
}

fn looks_like_test_binary(exe: &Path) -> bool {
    if exe
        .components()
        .any(|c| c.as_os_str().to_string_lossy().starts_with("rustdoctest"))
    {
        return true;
    }
    let in_deps = exe
        .parent()
        .and_then(Path::file_name)
        .is_some_and(|d| d == "deps");
    let hashed = exe
        .file_name()
        .and_then(|f| f.to_str())
        .and_then(|f| f.rsplit_once('-'))
        .is_some_and(|(_, h)| h.len() == 16 && h.bytes().all(|b| b.is_ascii_hexdigit()));
    in_deps && hashed
}

/// Bu süreç test ikilisi mi (ve `CLAUDEOPS_TEST_REAL_DIR=1` değil). Süreç başına bir kez hesaplanır.
pub fn under_test() -> bool {
    static T: OnceLock<bool> = OnceLock::new();
    *T.get_or_init(|| {
        let real = std::env::var_os(ENV_TEST_REAL).is_some_and(|v| v == "1");
        !real && std::env::current_exe().is_ok_and(|e| looks_like_test_binary(&e))
    })
}

static TEST_DIR: OnceLock<PathBuf> = OnceLock::new();

extern "C" fn remove_test_dir() {
    if let Some(d) = TEST_DIR.get() {
        // atexit: hata bildirilecek yer yok; kalan geçici dizin /tmp temizliğine kalır.
        let _ = std::fs::remove_dir_all(d);
    }
}

fn test_dir() -> PathBuf {
    TEST_DIR
        .get_or_init(|| {
            let nanos = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_or(0, |d| d.as_nanos());
            let name = format!("cops-test-state-{}-{nanos}", std::process::id());
            // SAFETY: atexit yalnız bir işlev göstericisi kaydeder; işleyici panik üretmez.
            unsafe { libc::atexit(remove_test_dir) };
            std::env::temp_dir().join(name)
        })
        .clone()
}

fn resolve_from(
    env_dir: Option<OsString>,
    test: bool,
    home: Option<OsString>,
) -> io::Result<PathBuf> {
    if let Some(d) = env_dir.filter(|d| !d.is_empty()) {
        let d = PathBuf::from(d);
        if !d.is_absolute() {
            // Python `paths.py` (ve `cops-cli` `Roots::check_absolute`) ile aynı metin: kapalı yön, hiçbir şey yazılmadan
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("CLAUDEOPS_DIR göreli ({}): mutlak yol verin", d.display()),
            ));
        }
        return Ok(d);
    }
    if test {
        return Ok(test_dir());
    }
    match home.filter(|h| !h.is_empty()) {
        Some(h) => Ok(PathBuf::from(h).join(".claude").join("claudeops")),
        None => Err(io::Error::new(
            io::ErrorKind::NotFound,
            "HOME tanımsız ve CLAUDEOPS_DIR yok",
        )),
    }
}

impl StateDir {
    /// Ortamdan çöz (bkz. modül belgesi). Test ikilisinde canlı dizine çözülürse PANİK.
    pub fn resolve() -> io::Result<StateDir> {
        let root = resolve_from(std::env::var_os(ENV_DIR), under_test(), home_env())?;
        guard_write(&root);
        Ok(StateDir { root })
    }
    /// Açık dizin (`--state-dir` ve testler).
    pub fn at(root: impl Into<PathBuf>) -> StateDir {
        StateDir { root: root.into() }
    }
    pub fn root(&self) -> &Path {
        &self.root
    }
    pub fn join(&self, rel: impl AsRef<Path>) -> PathBuf {
        self.root.join(rel)
    }
    /// `docs` belge adının dosya yolu: `steward/quota` -> `<dizin>/steward/quota.json`. DİKKAT: ad ile dosya adı her zaman aynı
    /// değil (ör. `snapshots`/`snapshots.json` aynı, ama eski `last_snapshot.json` ayrı).
    pub fn doc_path(&self, name: &str) -> PathBuf {
        self.root.join(format!("{name}.json"))
    }
    /// `ROSTER_TSV`.
    pub fn roster_tsv(&self) -> PathBuf {
        self.join("roster.tsv")
    }
    /// `MODELS_TSV`.
    pub fn models_tsv(&self) -> PathBuf {
        self.join("models.tsv")
    }
    /// `CLAUDE_MODELS_JSON`.
    pub fn claude_models_json(&self) -> PathBuf {
        self.join("claude_models.json")
    }
    /// `settings.SETTINGS_JSON`.
    pub fn settings_json(&self) -> PathBuf {
        self.join("settings.json")
    }
    /// `instances.INSTANCES_JSON`.
    pub fn instances_json(&self) -> PathBuf {
        self.join("instances.json")
    }
    /// `store.default_path()`.
    pub fn db(&self) -> PathBuf {
        self.join("claudeops.db")
    }
    /// Alt sürece (ör. Python) aynı durum dizinini devret.
    pub fn apply_env(&self, cmd: &mut std::process::Command) {
        cmd.env(ENV_DIR, &self.root);
    }
    /// `ensure_private_state_dir`: dizini oluştur ve 0700 yap.
    pub fn ensure_private(&self) -> io::Result<()> {
        use std::os::unix::fs::PermissionsExt;
        guard_write(&self.root);
        std::fs::create_dir_all(&self.root)?;
        std::fs::set_permissions(&self.root, std::fs::Permissions::from_mode(0o700))
    }
}

// ---- ev dizini, `~` genişletme -------------------------------------------------------------------------------------

/// Süreç ortamındaki `HOME` (tanımsızsa `None`; boş dize olduğu gibi döner).
pub fn home_env() -> Option<OsString> {
    std::env::var_os("HOME")
}

fn passwd_dir(pw: *const libc::passwd) -> Option<String> {
    if pw.is_null() {
        return None;
    }
    // SAFETY: `pw` getpw*_r'nin doldurduğu, tampon yaşadığı sürece geçerli kayıt.
    let dir = unsafe { (*pw).pw_dir };
    if dir.is_null() {
        return None;
    }
    // SAFETY: pw_dir NUL ile biten C dizesi.
    let bytes = unsafe { CStr::from_ptr(dir) }.to_bytes().to_vec();
    Some(OsString::from_vec(bytes).to_string_lossy().into_owned())
}

fn getpw(name: Option<&str>) -> Option<String> {
    let cname = match name {
        Some(n) => Some(CString::new(n).ok()?),
        None => None,
    };
    let mut buf = vec![0u8; 16 * 1024];
    for _ in 0..4 {
        // SAFETY: sıfırlanmış passwd ve yeterli tampon; çıktı göstericisi yalnız başarıda kullanılır.
        let mut pwd: libc::passwd = unsafe { std::mem::zeroed() };
        let mut out: *mut libc::passwd = std::ptr::null_mut();
        let rc = unsafe {
            match &cname {
                Some(c) => libc::getpwnam_r(
                    c.as_ptr(),
                    &mut pwd,
                    buf.as_mut_ptr().cast(),
                    buf.len(),
                    &mut out,
                ),
                None => libc::getpwuid_r(
                    libc::getuid(),
                    &mut pwd,
                    buf.as_mut_ptr().cast(),
                    buf.len(),
                    &mut out,
                ),
            }
        };
        if rc == libc::ERANGE {
            buf.resize(buf.len() * 4, 0);
            continue;
        }
        return if rc == 0 { passwd_dir(out) } else { None };
    }
    None
}

/// `os.path.expanduser(path)`; `home` = ortamdaki `HOME` (`None` = tanımsız, o zaman passwd kaydı).
/// Python farkı: adında NUL olan `~ad` Python'da `ValueError` fırlatır, burada genişletilmeden döner.
pub fn expanduser_with(path: &str, home: Option<&str>) -> String {
    let Some(after) = path.strip_prefix('~') else {
        return path.to_string();
    };
    let i = after.find('/').unwrap_or(after.len());
    let userhome = if i == 0 {
        match home {
            Some(h) => h.to_string(),
            None => match getpw(None) {
                Some(h) => h,
                None => return path.to_string(),
            },
        }
    } else {
        match getpw(Some(&after[..i])) {
            Some(h) => h,
            None => return path.to_string(),
        }
    };
    let joined = format!("{}{}", userhome.trim_end_matches('/'), &after[i..]);
    if joined.is_empty() {
        "/".into()
    } else {
        joined
    }
}

/// Süreç ortamıyla `os.path.expanduser`.
pub fn expanduser(path: &str) -> String {
    let home = home_env().map(|h| h.to_string_lossy().into_owned());
    expanduser_with(path, home.as_deref())
}

/// `paths.HOME` (`os.path.expanduser("~")`).
pub fn home() -> String {
    expanduser("~")
}

/// `paths.CLAUDE_DIR`.
pub fn claude_dir() -> PathBuf {
    PathBuf::from(home()).join(".claude")
}
/// `paths.SESSIONS_DIR` (`<pid>.json`, gecikmeli yazılır).
pub fn sessions_dir() -> PathBuf {
    claude_dir().join("sessions")
}
/// `paths.PROJECTS_DIR` (`<kodlanmış cwd>/<sid>.jsonl`).
pub fn projects_dir() -> PathBuf {
    claude_dir().join("projects")
}
/// `paths.CONFIG_JSON` (`~/.claude.json`).
pub fn config_json() -> PathBuf {
    PathBuf::from(home()).join(".claude.json")
}
/// `paths.GUARD_LOCK`: kullanıcıya özel `/tmp/claudeops-<uid>/guard.lock`.
pub fn guard_lock() -> PathBuf {
    // SAFETY: getuid her zaman başarılıdır.
    let uid = unsafe { libc::getuid() };
    PathBuf::from(format!("/tmp/claudeops-{uid}/guard.lock"))
}

/// `paths.ucli_key_file(service)`: `service` boşsa `ucli_api_key`, doluysa `ucli_key_<service>`. Taban
/// `~/.claude/claudeops` (Python'daki gibi `CLAUDEOPS_DIR`DEN BAĞIMSIZ: anahtarı ucli oturum açılırken oraya yazar).
pub fn ucli_key_file(service: &str) -> String {
    let name = if service.is_empty() {
        "ucli_api_key".to_string()
    } else {
        format!("ucli_key_{service}")
    };
    expanduser(&format!("~/.claude/claudeops/{name}"))
}

// ---- yol yardımcıları -----------------------------------------------------------------------------------------------

/// `os.path.normpath` (posix).
pub fn normpath(p: &str) -> String {
    if p.is_empty() {
        return ".".into();
    }
    let slashes = p.len() - p.trim_start_matches('/').len();
    let lead = match slashes {
        0 => "",
        2 => "//",
        _ => "/",
    };
    let mut parts: Vec<&str> = Vec::new();
    for c in p.split('/') {
        match c {
            "" | "." => {}
            ".." if parts.last().is_some_and(|l| *l != "..") => {
                parts.pop();
            }
            ".." if !lead.is_empty() && parts.is_empty() => {}
            _ => parts.push(c),
        }
    }
    let out = format!("{lead}{}", parts.join("/"));
    if out.is_empty() {
        ".".into()
    } else {
        out
    }
}

/// `os.path.normpath(os.path.abspath(p))` (bağ izlenmez).
pub fn abs_normpath(p: &Path) -> PathBuf {
    let s = p.to_string_lossy();
    let abs = if s.starts_with('/') {
        s.into_owned()
    } else {
        let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("/"));
        format!("{}/{s}", cwd.to_string_lossy())
    };
    PathBuf::from(normpath(&abs))
}

/// `os.path.realpath` (katı değil; CPython 3.10 `posixpath._joinrealpath`): bileşen bileşen ilerler, sembolik bağ hedefi
/// (var olmasa da) aynı kuralla yeniden işlenir (`..` ve ara bağlar dahil); var olmayan kuyruk olduğu gibi kalır, döngüde
/// kalan kuyruk eklenip bırakılır. Sonuç `abspath` (normpath).
pub fn realpath(p: &Path) -> PathBuf {
    let abs = std::path::absolute(p).unwrap_or_else(|_| p.to_path_buf());
    let mut seen = std::collections::HashMap::new();
    let (out, _) = join_realpath(PathBuf::from("/"), &abs, &mut seen);
    abs_normpath(&out)
}

/// `_joinrealpath(path, rest, strict=False, seen)`: (yol, döngü yok mu).
fn join_realpath(
    mut path: PathBuf,
    rest: &Path,
    seen: &mut std::collections::HashMap<PathBuf, Option<PathBuf>>,
) -> (PathBuf, bool) {
    let comps: Vec<Component<'_>> = rest.components().collect();
    let tail = |i: usize| -> PathBuf { comps[i + 1..].iter().collect() };
    for (i, c) in comps.iter().enumerate() {
        let name = match c {
            Component::RootDir => {
                path = PathBuf::from("/");
                continue;
            }
            Component::CurDir | Component::Prefix(_) => continue,
            Component::ParentDir => {
                path.pop(); // `path` hep mutlak ve `..` içermez: Python `split` ile aynı
                continue;
            }
            Component::Normal(n) => n,
        };
        let newpath = path.join(name);
        let is_link = std::fs::symlink_metadata(&newpath).is_ok_and(|m| m.file_type().is_symlink());
        if !is_link {
            path = newpath;
            continue;
        }
        match seen.get(&newpath) {
            Some(Some(done)) => {
                path = done.clone();
                continue;
            }
            Some(None) => return (newpath.join(tail(i)), false), // döngü
            None => {}
        }
        let Ok(target) = std::fs::read_link(&newpath) else {
            path = newpath; // okunamayan bağ: bileşen olduğu gibi
            continue;
        };
        seen.insert(newpath.clone(), None);
        let (resolved, ok) = join_realpath(path, &target, seen);
        if !ok {
            return (resolved.join(tail(i)), false);
        }
        seen.insert(newpath, Some(resolved.clone()));
        path = resolved;
    }
    (path, true)
}

/// `os.path.isfile(p) and os.access(p, os.X_OK)`.
pub fn is_executable_file(p: &str) -> bool {
    std::fs::metadata(p).is_ok_and(|m| m.is_file()) && access_x(p)
}

/// `os.access(p, os.X_OK)` (gerçek uid).
pub fn access_x(p: &str) -> bool {
    CString::new(p).is_ok_and(|c| {
        // SAFETY: geçerli C dizesi.
        unsafe { libc::access(c.as_ptr(), libc::X_OK) == 0 }
    })
}

// ---- /proc ---------------------------------------------------------------------------------------------------------

/// `parse_proc_stat`: `/proc/<pid>/stat` metninin comm'dan SONRAKİ alanları (0=state, 1=ppid, 19=starttime). comm boşluk/parantez
/// içerebilir: SON `)` sonrası ayrıştırılır. `)` yoksa `None` (Python `ValueError`).
pub fn parse_proc_stat(raw: &str) -> Option<Vec<String>> {
    let i = raw.rfind(')')?;
    Some(
        raw[i + 1..]
            .split(crate::pycompat::is_space)
            .filter(|s| !s.is_empty())
            .map(String::from)
            .collect(),
    )
}

/// `/proc/<pid>/stat` hatası.
#[derive(Debug)]
pub enum ProcError {
    Io(io::Error),
    /// Python `ValueError`: `)` yok ya da alan sayı değil.
    Parse,
}

/// `proc_stat_fields` (UTF-8 olmayan bayt `replace` ile çözülür).
pub fn proc_stat_fields(pid: u32) -> Result<Vec<String>, ProcError> {
    let raw = std::fs::read(format!("/proc/{pid}/stat")).map_err(ProcError::Io)?;
    parse_proc_stat(&String::from_utf8_lossy(&raw)).ok_or(ProcError::Parse)
}

/// `proc_ppid`.
pub fn proc_ppid(pid: u32) -> Result<i64, ProcError> {
    let f = proc_stat_fields(pid)?;
    let s = f.get(1).ok_or(ProcError::Parse)?;
    crate::pycompat::parse_int(s)
        .and_then(|n| n.as_i64())
        .ok_or(ProcError::Parse)
}

// ---- canlı dizin koruması (test) -------------------------------------------------------------------------------------

thread_local! {
    static EXTRA_LIVE: RefCell<Vec<PathBuf>> = const { RefCell::new(Vec::new()) };
}

/// Canlı durum dizinleri: `$HOME` ve passwd ev dizininden `<ev>/.claude/claudeops` (ikisi farklı olabilir).
pub fn live_dirs() -> Vec<PathBuf> {
    let mut v = Vec::new();
    if let Some(h) = home_env().filter(|h| !h.is_empty()) {
        v.push(PathBuf::from(h).join(".claude/claudeops"));
    }
    if let Some(h) = getpw(None) {
        v.push(PathBuf::from(h).join(".claude/claudeops"));
    }
    v
}

/// Test ikilisinde `path` canlı durum dizini altındaysa PANİK (dosya sistemine dokunmadan önce çağrılır).
/// Test ikilisi dışında hiçbir şey yapmaz.
pub fn guard_write(path: &Path) {
    if !under_test() {
        return;
    }
    let p = realpath(path);
    let extra = EXTRA_LIVE.with(|e| e.borrow().clone());
    for live in live_dirs().into_iter().chain(extra) {
        if p.starts_with(realpath(&live)) {
            panic!(
                "test ikilisi canlı durum dizinine yazmaya çalıştı: {} (canlı: {})",
                path.display(),
                live.display()
            );
        }
    }
}

/// YALNIZ testler: bu iş parçacığında `dir` de canlı sayılır (korumanın yazıcılara bağlı olduğunu GERÇEK canlı dizine
/// dokunmadan sınamak için).
#[doc(hidden)]
pub fn with_extra_live_dir<T>(dir: &Path, f: impl FnOnce() -> T) -> T {
    struct Pop;
    impl Drop for Pop {
        fn drop(&mut self) {
            EXTRA_LIVE.with(|e| e.borrow_mut().pop());
        }
    }
    EXTRA_LIVE.with(|e| e.borrow_mut().push(dir.to_path_buf()));
    let _pop = Pop;
    f()
}

/// Test ortamı (RAII): geçici kök (`mkdtemp`, 0700) ve altında `state/` durum dizini; düşünce silinir.
/// Testler durum dizinini YALNIZ bununla kurar; alt sürece [`StateDir::apply_env`] ile verilir.
#[derive(Debug)]
pub struct TestEnv {
    root: PathBuf,
    state: StateDir,
}

impl TestEnv {
    pub fn new() -> io::Result<TestEnv> {
        let tmpl = std::env::temp_dir().join("cops-state-testenv-XXXXXX");
        let mut buf = CString::new(tmpl.as_os_str().to_string_lossy().into_owned())
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))?
            .into_bytes_with_nul();
        // SAFETY: NUL ile biten, değiştirilebilir şablon tamponu.
        let p = unsafe { libc::mkdtemp(buf.as_mut_ptr().cast()) };
        if p.is_null() {
            return Err(io::Error::last_os_error());
        }
        buf.pop();
        let root = PathBuf::from(OsString::from_vec(buf)).canonicalize()?;
        let state = StateDir::at(root.join("state"));
        guard_write(state.root());
        std::fs::create_dir_all(state.root())?;
        Ok(TestEnv { root, state })
    }
    pub fn root(&self) -> &Path {
        &self.root
    }
    pub fn dir(&self) -> &StateDir {
        &self.state
    }
}

impl Drop for TestEnv {
    fn drop(&mut self) {
        // Drop'ta hata döndürülemez; kalan geçici dizin /tmp temizliğine kalır.
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

/// PATH değerinden güvenilmeyen girdileri atar (P2-2, 28 Kas: servis PATH'inin başında var olmayan `/tmp/tmp.*` vardı; çok
/// kullanıcılı makinede başkası o dizini kurup `tmux`/`claude`/`git` koyarsa servis onu çalıştırırdı). Kalır: mutlak, var
/// olan (bağ çözülerek) dizin, sahibi root ya da bu kullanıcı, başkalarınca (other) yazılamaz. Sıra korunur, tekrar atılır.
///
/// py: paths.trusted_path_env
pub fn trusted_path_env(value: &str) -> String {
    use std::os::unix::fs::MetadataExt;
    // SAFETY: getuid her zaman başarılıdır.
    let uid = unsafe { libc::getuid() };
    let mut out: Vec<&str> = Vec::new();
    for p in value.split(':') {
        if !p.starts_with('/') || out.contains(&p) {
            continue;
        }
        let Ok(md) = std::fs::metadata(p) else {
            continue;
        };
        if md.is_dir() && (md.uid() == 0 || md.uid() == uid) && md.mode() & 0o002 == 0 {
            out.push(p);
        }
    }
    out.join(":")
}

/// Süreç girişinde `PATH`i [`trusted_path_env`] ile yeniden yazar; atılan girdileri döndürür (çocuk süreçler temiz PATH
/// devralır). `PATH` yoksa ya da UTF-8 değilse dokunmaz. Tek iş parçacıklıyken (ana işlevin başında) çağrılmalı.
///
/// py: paths.secure_path_environ
pub fn secure_path_environ() -> Vec<String> {
    // yok ya da UTF-8 değil: bilerek dokunulmaz (Python `os.environ` yoksa dokunmaz; UTF-8 dışı PATH süzülemez)
    let cur = match std::env::var("PATH") {
        Ok(v) => v,
        Err(std::env::VarError::NotPresent | std::env::VarError::NotUnicode(_)) => {
            return Vec::new()
        }
    };
    let new = trusted_path_env(&cur);
    let kept: Vec<&str> = if new.is_empty() {
        Vec::new()
    } else {
        new.split(':').collect()
    };
    let dropped = cur
        .split(':')
        .filter(|p| !kept.contains(p))
        .map(str::to_string)
        .collect();
    if new != cur {
        // sözleşme: çağıran tek iş parçacıklı açılışta çağırır (2021 sürümünde `set_var` güvenli işlev, yarış yine kaçınılır)
        std::env::set_var("PATH", &new);
    }
    dropped
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rules() {
        let home = Some(OsString::from("/h"));
        let r = |e: Option<&str>, t| resolve_from(e.map(Into::into), t, home.clone()).unwrap();
        assert_eq!(r(Some("/x"), true), PathBuf::from("/x"));
        assert_eq!(r(Some(""), false), PathBuf::from("/h/.claude/claudeops"));
        assert_eq!(r(None, false), PathBuf::from("/h/.claude/claudeops"));
        assert!(r(None, true).starts_with(std::env::temp_dir()));
        assert!(resolve_from(None, false, None).is_err());
        // Python `paths.py`: göreli ortam değeri açık hata (süreç dizinine göre çözülüp `py/` altına yazılmasın)
        let e = resolve_from(Some("rel/state".into()), false, home.clone()).unwrap_err();
        assert_eq!(
            e.to_string(),
            "CLAUDEOPS_DIR göreli (rel/state): mutlak yol verin"
        );
        assert!(resolve_from(Some("./x".into()), true, home.clone()).is_err());
    }

    #[test]
    fn test_binary_detection() {
        let t = |p: &str| looks_like_test_binary(Path::new(p));
        assert!(t("/c/debug/deps/cops_state-0123456789abcdef"));
        assert!(t("/tmp/rustdoctestAb12/rust_out"));
        assert!(!t("/c/release/copsd"));
        assert!(!t("/home/u/.claude/claudeops/bin/copsd"));
        assert!(!t("/c/debug/deps/copsd"));
    }

    /// Bu testin kendisi test ikilisi: `CLAUDEOPS_DIR` yoksa CANLI dizin asla dönmez.
    #[test]
    fn under_cargo_test_never_real_dir() {
        if std::env::var_os(ENV_DIR).is_none() && std::env::var_os(ENV_TEST_REAL).is_none() {
            let d = StateDir::resolve().unwrap();
            assert!(d.root().starts_with(std::env::temp_dir()), "{d:?}");
        }
    }

    #[test]
    fn parse_proc_stat_rules() {
        let f = parse_proc_stat("12 (a) b) c) S 1 2").unwrap();
        assert_eq!(f, ["S", "1", "2"]);
        assert!(parse_proc_stat("12 abc").is_none());
    }

    /// P2-2 (Python `test_path_env.py` eşi): güvenilmeyen PATH girdileri atılır.
    #[test]
    fn trusted_path_env_drops_untrusted() {
        use std::os::unix::fs::PermissionsExt;
        let root = std::env::temp_dir().join(format!("cops-pathenv-{}", std::process::id()));
        if root.exists() {
            std::fs::remove_dir_all(&root).unwrap();
        }
        let mine = root.join("mine");
        let ww = root.join("ww");
        std::fs::create_dir_all(&mine).unwrap();
        std::fs::create_dir_all(&ww).unwrap();
        std::fs::set_permissions(&ww, std::fs::Permissions::from_mode(0o777)).unwrap();
        let file = root.join("dosya");
        std::fs::write(&file, "").unwrap();
        let (m, w, f) = (
            mine.to_str().unwrap(),
            ww.to_str().unwrap(),
            file.to_str().unwrap(),
        );
        let missing = root.join("tmp.aEx49Kzuf1");
        let val = [
            missing.to_str().unwrap(),
            "",
            ".",
            "bin",
            f,
            w,
            m,
            "/usr/bin",
            m,
        ]
        .join(":");
        assert_eq!(trusted_path_env(&val), format!("{m}:/usr/bin"));
        assert_eq!(trusted_path_env("/usr/bin:/bin"), "/usr/bin:/bin");
        assert_eq!(trusted_path_env(""), "");
        std::fs::remove_dir_all(&root).unwrap();
    }
}
