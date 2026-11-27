//! G9 gerçek tmux uygulayıcısı: [`SpawnTmux`] `cops-tmux` üstüne ince sarmalayıcı (Python `tmux_backend`in spawn'da
//! kullanılan sekiz işlevi).
//!
//! Değişmezler `cops-tmux`tadır ve burada YENİDEN yazılmaz: hedef her zaman TAM ad (`=ad:`), hedeflenemeyen ad hiçbir
//! tmux komutu çalıştırmadan reddedilir, `;` ile biten argv elemanı kaçırılır, `new-session -c` biçim literali, her
//! çağrı zaman aşımlı. Bu sınır METİN GÖNDERMEZ (tuş/yapıştırma yok); `inner` komutu Python'daki gibi tmux argv'sinde
//! tek eleman olarak gider (`Sır / argv notları`, `docs/rs-prov.md`). `spawn_direct`in ortamı sürecin TÜM ortamıdır
//! (miras yok): çağıran ([`crate::spawn::child_env`]) CLI kimlik değişkenlerini süpürür.

use crate::real::{pathexec, Env};
use crate::spawn_exec::SpawnTmux;
use cops_tmux::{tmux_conf_path, Tmux, TmuxError};
use std::path::Path;
use std::sync::Arc;

/// Python `ValueError("tmux hedefi olamayan oturum adı")` metni.
pub const BAD_NAME: &str = "tmux hedefi olamayan oturum adı";

/// Hayalet kararının saati (`time.time()`); yalnız testler değiştirir.
pub type WallClock = Arc<dyn Fn() -> f64 + Send + Sync>;

/// `-L cops` (ya da testte yalıtılmış) sunucuya bağlı [`SpawnTmux`].
#[derive(Clone)]
pub struct CopsTmux {
    tmux: Tmux,
    /// `tmux_conf_path()` (`<depo>/py/claudeops/data/tmux.conf`, paket dizini çözülmüş).
    conf: String,
    /// `shutil.which("tmux")` için çağıran sürecin ortamı.
    env: Env,
    now: Option<WallClock>,
}

impl CopsTmux {
    /// Canlı filo: `tmux -L cops`, yapılandırma `repo_dir`deki paketli dosya.
    pub fn live(repo_dir: &str, env: Env) -> CopsTmux {
        CopsTmux::new(Tmux::cops(), repo_dir, env)
    }

    /// Verilen istemciyle (testte `Tmux::with_socket(..).tmpdir(..)`).
    pub fn new(tmux: Tmux, repo_dir: &str, env: Env) -> CopsTmux {
        let conf = tmux_conf_path(&Path::new(repo_dir).join("py"))
            .to_string_lossy()
            .into_owned();
        CopsTmux {
            tmux,
            conf,
            env,
            now: None,
        }
    }

    /// Hayalet yaşı için duvar saati (varsayılan sistem saati).
    pub fn with_wall_clock(mut self, now: WallClock) -> CopsTmux {
        self.now = Some(now);
        self
    }

    pub fn conf(&self) -> &str {
        &self.conf
    }

    pub fn tmux(&self) -> &Tmux {
        &self.tmux
    }
}

/// Parça kurucularının hatası Python `ValueError` metnine çevrilir (kurucular yalnız ad için hata verir).
fn fragment_error(e: TmuxError) -> String {
    match e {
        TmuxError::BadArgument("name") => BAD_NAME.to_string(),
        other => other.to_string(),
    }
}

impl SpawnTmux for CopsTmux {
    fn available(&self) -> bool {
        pathexec::which(&self.env, "tmux").is_some()
    }

    fn new_session_fragment(&self, name: &str, cwd: &str, inner: &str) -> Result<String, String> {
        self.tmux
            .new_session_shell_fragment(&self.conf, name, cwd, inner)
            .map_err(fragment_error)
    }

    fn attach_fragment(&self, name: &str) -> Result<String, String> {
        self.tmux
            .attach_shell_fragment(&self.conf, name)
            .map_err(fragment_error)
    }

    fn spawn_direct(&self, name: &str, cwd: &str, inner: &str, env: &[(String, String)]) -> bool {
        let envs = env.iter().map(|(k, v)| (k.as_str(), v.as_str()));
        self.tmux
            .spawn_direct(Path::new(&self.conf), name, cwd, inner, envs)
            .is_ok()
    }

    fn has_session(&self, name: &str) -> bool {
        // Python: yalnız çıkış kodu 0 ise True; zaman aşımı/hata False.
        matches!(self.tmux.has_session(name), Ok(true))
    }

    fn ghost_session(&self, name: &str) -> bool {
        self.tmux
            .ghost_session(name, self.now.as_ref().map(|f| f()))
    }

    fn capture(&self, name: &str, lines: u32) -> Option<String> {
        self.tmux.capture(name, lines).ok()
    }

    fn kill_session(&self, name: &str) {
        // Python hatayı yutar (oturum yok, sunucu yok, zaman aşımı).
        let _ = self.tmux.kill_session(name);
    }
}
