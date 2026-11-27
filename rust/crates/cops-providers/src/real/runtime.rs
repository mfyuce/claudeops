//! Spawn yolunun SÜREÇ BAŞINA TEK örnekleri (Python'da modül düzeyi durum): maliyet defteri (`ucli_cost._RESERVED`,
//! `_CACHE`), SearXNG yöneticisi, `--help` önbelleği, tanı günlüğü. Panel/copsd süreci bunu BİR kez kurar ve her spawn'da
//! aynı örneği verir; iki örnek iki ayrı başlatma payı tablosu demektir (tavan aşılabilir).

use crate::probe::Paths;
use crate::real::diaglog::DiagLog;
use crate::real::docs::DocStore;
use crate::real::help::HelpCache;
use crate::real::launch::{GnomeTerminal, SystemClock};
use crate::real::ledger::{file_cost_settings, CostLedger, CostSettings};
use crate::real::pathexec;
use crate::real::probe::{ProjectDirs, RealDeps};
use crate::real::searxng::{ManagedSearch, Provision};
use crate::real::startup_desktop::X11Desktop;
use crate::real::Env;
use crate::spawn_exec::{Launcher, SpawnTmux};
use std::sync::Arc;

pub struct SpawnRuntime {
    pub ledger: Arc<CostLedger>,
    pub search: Arc<ManagedSearch>,
    pub help: Arc<HelpCache>,
    pub diag: DiagLog,
    /// Masaüstü yönlendirmesinin okuduğu ayar dosyası (`spawn_desktop`).
    settings_json: String,
}

impl SpawnRuntime {
    /// `python`: SearXNG ayrık kurulumunu (`-m claudeops searxng provision`) çalıştıracak, PANEL SERVİSİNİN KENDİ
    /// Python'u (Python'da `sys.executable`; ör. yuhem `py/.venv/bin/python3`, ulak_31 `/usr/bin/python3`).
    pub fn new(paths: &Paths, env: &Env, python: &str) -> SpawnRuntime {
        let settings = file_cost_settings(paths.settings_json());
        SpawnRuntime::with_cost_settings(paths, env, python, settings)
    }

    /// [`SpawnRuntime::new`], maliyet ayarı başka kaynaktan (rs/state yükleyicisi bağlanınca).
    pub fn with_cost_settings(
        paths: &Paths,
        env: &Env,
        python: &str,
        settings: CostSettings,
    ) -> SpawnRuntime {
        let diag = DiagLog::from_env(paths, env);
        let provision = Provision::python(python, &paths.repo_dir);
        SpawnRuntime {
            ledger: Arc::new({
                let cwd = std::env::current_dir()
                    .map_or_else(|_| "/".into(), |p| p.to_string_lossy().into_owned());
                let usage = paths.ucli_usage_dir();
                let own = paths.usage_write_dir(&usage, &|p| pathexec::realpath(p, &cwd));
                CostLedger::new(usage, settings).with_write_dir(own)
            }),
            search: Arc::new(ManagedSearch::new(
                &paths.home,
                &paths.claudeops_dir,
                env.clone(),
                diag.clone(),
                provision,
            )),
            help: Arc::new(HelpCache::default().with_diag(Arc::new(diag.clone()))),
            diag,
            settings_json: paths.settings_json(),
        }
    }

    /// Bu örneklerle [`RealDeps`].
    pub fn deps(
        &self,
        docs: Arc<dyn DocStore>,
        projects: Arc<dyn ProjectDirs>,
        panel_port: Option<u16>,
    ) -> RealDeps {
        RealDeps {
            docs,
            projects,
            cost: self.ledger.clone(),
            search: self.search.clone(),
            help: self.help.clone(),
            panel_port,
        }
    }

    /// Ayar kaydedildi (`web` ayar kaydı `ucli_cost.invalidate()`): tavan/önbellek süresi hemen yeniden okunur.
    pub fn settings_saved(&self) {
        self.ledger.invalidate();
    }

    /// Gerçek pencere, saat ve günlükle [`Launcher`]; tmux uygulayıcısını çağıran verir (`cops-tmux`).
    pub fn launcher(&self, tmux: Arc<dyn SpawnTmux>, env: &Env) -> Launcher {
        Launcher {
            tmux,
            terminal: Arc::new(GnomeTerminal::new(env.clone()).with_desktop(
                self.settings_json.clone(),
                Arc::new(X11Desktop::new(env.clone())),
            )),
            clock: Arc::new(SystemClock),
            diag: Arc::new(self.diag.clone()),
            parent_env: env.vars(),
        }
    }
}
