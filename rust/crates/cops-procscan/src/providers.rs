//! CLI tanıma: Python `providers/*`in `matches_proc` / `extract_name` / `extract_info` karşılığı.
//! Eşleşme argv[0] dosya adına göredir, bir süreç en çok bir sağlayıcıya uyar.

use crate::procfs::OwnProc;
use crate::py;
use crate::Config;
use serde_json::{Map, Value};
use std::path::Path;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Cli {
    Claude,
    Agy,
    Codex,
    Copilot,
    Shell,
    Ucli,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Info {
    pub sid: Option<String>,
    pub model: Option<String>,
    pub permission_mode: Option<String>,
    pub effort: Option<String>,
}

/// `claude` dışında argv'si bağımsız oturum olmayan codex alt komutları.
const CODEX_NON_SESSION: &[&str] = &[
    "agents",
    "exec",
    "review",
    "login",
    "logout",
    "mcp",
    "plugin",
    "app-server",
    "remote-control",
    "completion",
    "update",
    "doctor",
    "sandbox",
    "debug",
    "apply",
    "queue",
    "archive",
    "delete",
    "migrate-rollouts",
    "unarchive",
    "fork",
    "cloud",
    "exec-server",
    "features",
    "help",
];

/// ucli effort ön ayarları (`ucli_provider._EFFORT_LIMITS`): max-steps, max-context-kib, max-tool-calls, max-output-tokens.
const UCLI_EFFORT: &[(&str, [&str; 4])] = &[
    ("medium", ["25", "256", "64", "4096"]),
    ("high", ["200", "16384", "256", "16000"]),
];

/// `os.path.basename`.
pub fn basename(path: &str) -> &str {
    path.rsplit('/').next().unwrap_or(path)
}

/// `flag`ten sonraki değer (ilk geçiş).
pub fn arg<'a>(cmd: &'a [String], flag: &str) -> Option<&'a str> {
    let i = cmd.iter().position(|c| c == flag)?;
    cmd.get(i + 1).map(String::as_str)
}

fn has(cmd: &[String], flag: &str) -> bool {
    cmd.iter().any(|c| c == flag)
}

fn owned(v: Option<&str>) -> Option<String> {
    v.map(str::to_owned)
}

impl Cli {
    pub fn as_str(self) -> &'static str {
        match self {
            Cli::Claude => "claude",
            Cli::Agy => "agy",
            Cli::Codex => "codex",
            Cli::Copilot => "copilot",
            Cli::Shell => "shell",
            Cli::Ucli => "ucli",
        }
    }

    pub fn detect(cmd: &[String]) -> Option<Cli> {
        let bin = basename(cmd.first()?);
        match bin {
            "claude" => Some(Cli::Claude),
            "agy" => Some(Cli::Agy),
            "codex" if cmd.get(1).is_none_or(|s| !CODEX_NON_SESSION.contains(&s.as_str())) => Some(Cli::Codex),
            // `--server`/`--stdio`: başka programın headless arka ucu
            "copilot" if !has(cmd, "--server") && !has(cmd, "--stdio") => Some(Cli::Copilot),
            "claudeops-shell" => Some(Cli::Shell),
            // `--repl`siz ucli (tek atımlık koşu) filo oturumu değil
            "ucli" if has(cmd, "--repl") => Some(Cli::Ucli),
            _ => None,
        }
    }

    /// Oturum adı; `None` = sağlayıcı adlandıramadı (claude'da süreç atlanır, diğerlerinde yedek ad).
    pub fn extract_name(self, proc: &OwnProc, cmd: &[String]) -> Option<String> {
        let cops_name = || {
            proc.environ()
                .and_then(|mut e| e.remove("COPS_NAME"))
                .filter(|n| !n.is_empty())
        };
        match self {
            Cli::Claude => owned(arg(cmd, "--remote-control")),
            Cli::Agy | Cli::Codex | Cli::Copilot => {
                Some(cops_name().unwrap_or_else(|| format!("{}-{}", self.as_str(), proc.pid())))
            }
            Cli::Shell => cops_name(),
            Cli::Ucli => owned(arg(cmd, "--session")),
        }
        .filter(|n| !n.is_empty())
    }

    pub fn extract_info(self, cmd: &[String], cwd: &str, session_name: &str, agy: &mut AgyState) -> Info {
        let model = owned(arg(cmd, "--model"));
        match self {
            Cli::Claude => Info {
                sid: owned(arg(cmd, "--resume")),
                model,
                permission_mode: owned(arg(cmd, "--permission-mode")),
                effort: owned(arg(cmd, "--effort")),
            },
            Cli::Codex => Info {
                sid: if cmd.len() >= 3 && cmd[1] == "resume" {
                    Some(cmd[2].clone())
                } else {
                    None
                },
                model,
                permission_mode: codex_mode(cmd),
                effort: codex_config(cmd, "model_reasoning_effort"),
            },
            Cli::Copilot => {
                let mode = arg(cmd, "--mode");
                let pm = if has(cmd, "--autopilot") || mode == Some("autopilot") {
                    "autopilot"
                } else if mode == Some("plan") {
                    "plan"
                } else if ["--allow-all-tools", "--allow-all", "--yolo"].iter().any(|f| has(cmd, f)) {
                    "auto"
                } else {
                    "manual"
                };
                Info {
                    sid: owned(arg(cmd, "--resume")),
                    model,
                    permission_mode: Some(pm.into()),
                    effort: owned(
                        arg(cmd, "--effort")
                            .filter(|e| !e.is_empty())
                            .or_else(|| arg(cmd, "--reasoning-effort")),
                    ),
                }
            }
            Cli::Shell => Info::default(),
            Cli::Agy => {
                let pm = if has(cmd, "--dangerously-skip-permissions") {
                    Some("auto")
                } else {
                    match arg(cmd, "--mode") {
                        Some("accept-edits") => Some("acceptEdits"),
                        Some("plan") => Some("plan"),
                        _ => None,
                    }
                };
                Info {
                    sid: agy.resolve(arg(cmd, "--conversation"), cwd, session_name),
                    model,
                    permission_mode: owned(pm),
                    effort: owned(arg(cmd, "--effort")),
                }
            }
            Cli::Ucli => ucli_info(cmd),
        }
    }
}

fn codex_mode(cmd: &[String]) -> Option<String> {
    if has(cmd, "--dangerously-bypass-approvals-and-sandbox") {
        return Some("auto".into());
    }
    let sandbox = arg(cmd, "--sandbox")?;
    let approval = arg(cmd, "--ask-for-approval")?;
    match (sandbox, approval) {
        ("workspace-write", "never") => Some("acceptEdits".into()),
        ("workspace-write", "on-request") => Some("manual".into()),
        ("read-only", "on-request") => Some("plan".into()),
        _ => None,
    }
}

fn codex_config(cmd: &[String], key: &str) -> Option<String> {
    cmd.windows(2)
        .filter(|w| w[0] == "-c" || w[0] == "--config")
        .find_map(|w| w[1].strip_prefix(key)?.strip_prefix('=').map(str::to_owned))
}

fn ucli_info(cmd: &[String]) -> Info {
    const FLAGS: [&str; 4] = ["--max-steps", "--max-context-kib", "--max-tool-calls", "--max-output-tokens"];
    let last = |flag: &str| cmd.windows(2).rev().find(|w| w[0] == flag).map(|w| w[1].clone());
    let limits = FLAGS.map(last);
    let mode = if has(cmd, "--allow-edit") {
        "allow-edit"
    } else if has(cmd, "--allow-create") {
        "allow-create"
    } else {
        "read-only"
    };
    let effort = UCLI_EFFORT.iter().find(|(_, want)| {
        want.iter().zip(&limits).enumerate().all(|(i, (w, got))| match got {
            Some(g) => g == w,
            // `--max-context-kib` isteğe bağlı
            None => i == 1,
        })
    });
    Info {
        sid: owned(arg(cmd, "--session")),
        model: last("--model"),
        permission_mode: Some(mode.into()),
        effort: effort.map(|(n, _)| (*n).to_owned()),
    }
}

/// agy argv'si taze oturumda sohbet id'si taşımaz: agy'nin cwd önbelleğinden, başka ada kayıtlı değilse alınır.
/// Python bunu `agy_sids.json`a yazar; burada yazılmaz, [`AgyState::learned`] ile çağırana bildirilir.
#[derive(Debug, Default)]
pub struct AgyState {
    known: Map<String, Value>,
    cache: Map<String, Value>,
    pub learned: Vec<(String, String)>,
}

impl AgyState {
    pub fn load(cfg: &Config) -> Self {
        AgyState {
            known: read_object(&cfg.agy_sids),
            cache: read_object(&cfg.agy_cache),
            learned: Vec::new(),
        }
    }

    /// argv id'si varsa o (öğrenilir); boşsa agy önbelleği. Bulunamazsa argv değeri (boş dizgi dahil) aynen döner.
    fn resolve(&mut self, argv_sid: Option<&str>, cwd: &str, session_name: &str) -> Option<String> {
        let unchanged = argv_sid.map(str::to_owned);
        let sid = match argv_sid.filter(|s| !s.is_empty()) {
            Some(s) if !session_name.is_empty() => s.to_owned(),
            Some(_) => return unchanged,
            None => {
                if cwd.is_empty() || session_name.is_empty() {
                    return unchanged;
                }
                let cached = self.cache.get(cwd).and_then(Value::as_str).map(py::strip).unwrap_or("");
                let claimed = self
                    .known
                    .iter()
                    .any(|(n, s)| s.as_str() == Some(cached) && n != session_name);
                if cached.is_empty() || claimed {
                    return unchanged;
                }
                cached.to_owned()
            }
        };
        if self.known.get(session_name).and_then(Value::as_str) != Some(&sid) {
            self.known.insert(session_name.to_owned(), Value::String(sid.clone()));
            self.learned.push((session_name.to_owned(), sid.clone()));
        }
        Some(sid)
    }
}

fn read_object(path: &Path) -> Map<String, Value> {
    match std::fs::read(path).ok().and_then(|raw| py::json(&raw)) {
        Some(Value::Object(o)) => o,
        _ => Map::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(s: &str) -> Vec<String> {
        s.split(' ').map(str::to_owned).collect()
    }

    fn info(cmd: &str) -> Info {
        let c = v(cmd);
        Cli::detect(&c).unwrap().extract_info(&c, "", "", &mut AgyState::default())
    }

    #[test]
    fn detect() {
        assert_eq!(Cli::detect(&v("/usr/bin/claude --x")), Some(Cli::Claude));
        assert_eq!(Cli::detect(&v("bash -c claude")), None);
        assert_eq!(Cli::detect(&v("codex")), Some(Cli::Codex));
        assert_eq!(Cli::detect(&v("codex resume u")), Some(Cli::Codex));
        assert_eq!(Cli::detect(&v("codex app-server")), None);
        assert_eq!(Cli::detect(&v("copilot --server --stdio")), None);
        assert_eq!(Cli::detect(&v("ucli chat x")), None);
        assert_eq!(Cli::detect(&v("ucli chat --repl")), Some(Cli::Ucli));
        assert_eq!(Cli::detect(&v("claudeops-shell -")), Some(Cli::Shell));
        assert_eq!(Cli::detect(&v("claude/")), None);
        assert_eq!(Cli::detect(&v("claude/.")), None);
        assert_eq!(Cli::detect(&[]), None);
    }

    #[test]
    fn claude_info() {
        let i = info("claude --remote-control a --resume S --model m --permission-mode auto --effort max");
        assert_eq!((i.sid.as_deref(), i.model.as_deref()), (Some("S"), Some("m")));
        assert_eq!(
            (i.permission_mode.as_deref(), i.effort.as_deref()),
            (Some("auto"), Some("max"))
        );
        assert_eq!(info("claude --model").model, None);
    }

    #[test]
    fn codex_info() {
        let i = info("codex resume U --sandbox read-only --ask-for-approval on-request -c model_reasoning_effort=high");
        assert_eq!(
            (i.sid.as_deref(), i.permission_mode.as_deref(), i.effort.as_deref()),
            (Some("U"), Some("plan"), Some("high"))
        );
        assert_eq!(info("codex --sandbox read-only").permission_mode, None);
    }

    #[test]
    fn copilot_info() {
        assert_eq!(info("copilot").permission_mode.as_deref(), Some("manual"));
        assert_eq!(info("copilot --yolo").permission_mode.as_deref(), Some("auto"));
        assert_eq!(info("copilot --mode plan --yolo").permission_mode.as_deref(), Some("plan"));
        assert_eq!(info("copilot --reasoning-effort low").effort.as_deref(), Some("low"));
    }

    #[test]
    fn ucli_effort_presets() {
        let base = "ucli chat --repl --session s --max-steps 200 --max-tool-calls 256 --max-output-tokens 16000";
        assert_eq!(info(base).effort.as_deref(), Some("high"));
        assert_eq!(
            info(&format!("{base} --max-context-kib 16384")).effort.as_deref(),
            Some("high")
        );
        assert_eq!(info(&format!("{base} --max-context-kib 1")).effort, None);
        assert_eq!(info("ucli --repl --allow-edit").effort, None);
        assert_eq!(
            info("ucli --repl --allow-edit").permission_mode.as_deref(),
            Some("allow-edit")
        );
    }

    #[test]
    fn agy_sid_rules() {
        let mut st = AgyState::default();
        st.cache.insert("/w".into(), " c1 ".into());
        st.known.insert("other".into(), "c1".into());
        assert_eq!(st.resolve(None, "/w", "me"), None);
        assert_eq!(st.resolve(None, "/w", "other").as_deref(), Some("c1"));
        assert!(st.learned.is_empty());
        assert_eq!(st.resolve(Some("c2"), "/w", "me").as_deref(), Some("c2"));
        assert_eq!(st.learned, [("me".to_owned(), "c2".to_owned())]);
    }
}
