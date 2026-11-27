//! Tek atımlık çağrının süreç yarısı: `ucli_client.ucli_chat_once`, `CliProvider.oneshot` ve `UcliProvider.oneshot`.
//!
//! Alt süreç [`process::run`] ile koşar (stdin boş, toplam süre, grup öldür + bekle, sınırlı boru). API anahtarı yalnız
//! çocuğun ORTAMINDADIR: argv'ye, hata metnine, günlüğe ve onay kaydına girmez.

use crate::approval::{self, NewRun};
use crate::oneshot::{self, ChatArgv, OneshotError};
use crate::probe::SpawnError;
use crate::provider::{Cli, Providers};
use crate::pyfmt::{float_repr, join_path, py_str_repr, strip};
use crate::pyjson::Py;
use crate::real::approval::ApprovalStore;
use crate::real::diaglog::DiagLog;
use crate::real::effects::makedirs;
use crate::real::process::{self, Capture, RunError, Spec};
use crate::real::{fsio, oserr, Env};
use crate::ucli::{self, DEFAULT_ENDPOINT};
use serde_json::json;
use std::fs;
use std::time::Duration;

/// Her akış için çıktı sınırı (Python sınırsız).
pub const OUTPUT_MAX_BYTES: u64 = 16 << 20;

/// `ucli_chat_once` argümanları (varsayılanlar [`ChatRequest::new`]).
#[derive(Debug, Clone)]
pub struct ChatRequest<'a> {
    pub root: &'a str,
    pub prompt: &'a str,
    pub session: Option<&'a str>,
    pub model: Option<&'a str>,
    pub endpoint: Option<&'a str>,
    pub api_key_env: &'a str,
    /// Verilirse ortama `api_key_env` adıyla eklenir; `Debug`da maskeli.
    pub api_key: Option<ApiKey>,
    pub with_mcp: bool,
    pub max_steps: Option<i64>,
    pub binary: Option<&'a str>,
    /// Saniye.
    pub timeout: f64,
    pub extra_args: &'a [String],
    pub approval_run_key: Option<&'a str>,
    pub approval_owner: &'a str,
}

/// API anahtarı: `Debug` içeriği basmaz.
#[derive(Clone, PartialEq, Eq)]
pub struct ApiKey(String);

impl ApiKey {
    pub fn new(value: impl Into<String>) -> ApiKey {
        ApiKey(value.into())
    }
}

impl std::fmt::Debug for ApiKey {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("<redacted>")
    }
}

impl<'a> ChatRequest<'a> {
    pub fn new(root: &'a str, prompt: &'a str) -> ChatRequest<'a> {
        ChatRequest {
            root,
            prompt,
            session: None,
            model: None,
            endpoint: None,
            api_key_env: "UCLI_API_KEY",
            api_key: None,
            with_mcp: false,
            max_steps: None,
            binary: None,
            timeout: 120.0,
            extra_args: &[],
            approval_run_key: None,
            approval_owner: "",
        }
    }
}

fn duration(seconds: f64) -> Duration {
    // negatif / NaN: hemen zaman aşımı; temsil edilemeyecek kadar büyük: sınırsıza yakın
    if seconds > 0.0 {
        Duration::try_from_secs_f64(seconds).unwrap_or(Duration::MAX)
    } else {
        Duration::ZERO
    }
}

/// Süreç sonucu: kod ve metin akışları.
struct Text {
    code: i32,
    stdout: String,
    stderr: String,
}

enum Failed {
    Timeout,
    NotUtf8,
    /// argv/env/cwd içinde NUL.
    BadArgument,
    TooBig,
    Os(String),
}

/// Tek atımlık çağrıların bağlamı.
pub struct OneShot<'a, 'b> {
    pub providers: &'a Providers<'b>,
    /// Çocuk süreçlerin ortamı (Python `os.environ`).
    pub env: &'a Env,
    pub approvals: &'a ApprovalStore,
    pub diag: &'a DiagLog,
}

impl OneShot<'_, '_> {
    fn exec(
        &self,
        argv: &[String],
        cwd: Option<&str>,
        env: &Env,
        timeout: f64,
    ) -> Result<Text, Failed> {
        let spec = Spec {
            argv,
            cwd,
            env,
            timeout: duration(timeout),
            stdout: Capture::Bounded(OUTPUT_MAX_BYTES),
            stderr: Capture::Bounded(OUTPUT_MAX_BYTES),
        };
        let program = argv.first().map(String::as_str).unwrap_or("");
        let out = process::run(&spec).map_err(|e| match e {
            RunError::Timeout => Failed::Timeout,
            RunError::Overflow => Failed::TooBig,
            // işletim sistemi kodu olmayan `InvalidInput`: std argümandaki NUL'u böyle reddeder
            RunError::Spawn(e)
                if e.raw_os_error().is_none() && e.kind() == std::io::ErrorKind::InvalidInput =>
            {
                Failed::BadArgument
            }
            RunError::Spawn(e) | RunError::Io(e) => Failed::Os(oserr::text(&e, program)),
        })?;
        match (
            oneshot::decode_text(out.stdout),
            oneshot::decode_text(out.stderr),
        ) {
            (Some(stdout), Some(stderr)) => Ok(Text {
                code: out.code,
                stdout,
                stderr,
            }),
            _ => Err(Failed::NotUtf8),
        }
    }

    /// `--state-dir` (oturum durumu depo dışına): ayar açık ya da dosya zaten yeni dizinde, geçmiş yalnız eski dizinde
    /// değil ve ikili bayrağı tanıyor.
    fn state_dir_args(&self, binary: &str, root: &str, session: &str) -> Vec<String> {
        let p = self.providers;
        let sdir = ucli::state_dir_for(&p.paths.ucli_state_root(), &p.probe.realpath(root));
        let file = format!("{session}.jsonl");
        let in_new = p.probe.exists(&join_path(&sdir, &file));
        let in_old = p.probe.exists(&join_path(
            &join_path(&join_path(root, ".ucli"), "chat"),
            &file,
        ));
        if (p.settings.ucli_state_dir() || in_new)
            && !(in_old && !in_new)
            && self.supports(binary, "--state-dir")
        {
            vec!["--state-dir".into(), sdir]
        } else {
            Vec::new()
        }
    }

    fn supports(&self, binary: &str, flag: &str) -> bool {
        ucli::supports_flag(&self.providers.probe.ucli_chat_help(binary), flag)
    }

    /// `ucli_chat_once`. `approval_run_key` verilmişse ve ucli 75 + `suspended` satırıyla çıkarsa koşu onay kaydına
    /// `suspended` yazılır ve `{"ok", "status", "run_key", "approval_id"}` döner.
    pub fn chat_once(&self, req: &ChatRequest<'_>) -> Result<Py, SpawnError> {
        oneshot::check_prompt(req.prompt)?;
        let binary = match req.binary.filter(|b| !b.is_empty()) {
            Some(b) => b.to_string(),
            None => ucli::resolve_binary(self.providers)?,
        };
        let session = req.session.filter(|s| !s.is_empty());
        let mut extra =
            session.map_or_else(Vec::new, |s| self.state_dir_args(&binary, req.root, s));
        let run_key = req.approval_run_key.filter(|k| !k.is_empty());
        if let Some(key) = run_key {
            if !self.supports(&binary, "--approval-dir") {
                return Err(SpawnError(
                    "ucli ikilisi --approval-dir bayrağını tanımıyor (onay kanalı yarım uygulanmaz)".into(),
                ));
            }
            if !self.approvals.slot_free(key) {
                return Err(SpawnError(format!(
                    "run_key kullanımda (bitmemiş onay koşusu var): {}",
                    py_str_repr(key)
                )));
            }
            let dir = self
                .approvals
                .dir_for(key, true)
                .map_err(|e| SpawnError(e.text))?;
            extra.extend(["--approval-dir".into(), dir]);
        }
        extra.extend(req.extra_args.iter().cloned());
        let argv_resume = oneshot::build_chat_argv(&ChatArgv {
            binary: &binary,
            root: req.root,
            repl: false,
            session,
            model: req.model,
            endpoint: req.endpoint,
            api_key_env: req.api_key_env,
            with_mcp: req.with_mcp,
            max_steps: req.max_steps,
            extra_args: &extra,
        });
        let mut argv = argv_resume.clone();
        argv.push(req.prompt.to_string());
        let (env, secret) = match &req.api_key {
            Some(ApiKey(key)) => {
                if !oneshot::is_api_key_env_name(req.api_key_env) {
                    return Err(SpawnError(format!(
                        "invalid api_key_env name: {}",
                        py_str_repr(req.api_key_env)
                    )));
                }
                (self.env.with_var(req.api_key_env, key), Some(key.clone()))
            }
            None => (self.env.clone(), self.env.get(req.api_key_env)),
        };
        let out = self.exec(&argv, None, &env, req.timeout).map_err(|f| {
            SpawnError(match f {
                Failed::Timeout => {
                    format!("ucli {}s içinde cevap vermedi", float_repr(req.timeout))
                }
                Failed::NotUtf8 => "ucli çıktısı UTF-8 değildi".into(),
                Failed::BadArgument => {
                    "ucli çalıştırılamadı: geçersiz argüman ya da ortam değeri".into()
                }
                Failed::TooBig => "ucli çıktısı sınırı aştı".into(),
                Failed::Os(text) => format!("ucli çalıştırılamadı: {text}"),
            })
        })?;
        if let (Some(key), 75) = (run_key, out.code) {
            if let Some(id) = approval::parse_suspended(&out.stdout) {
                let run = NewRun {
                    cwd: req.root,
                    session: session.unwrap_or(""),
                    argv_resume: &argv_resume,
                    owner: req.approval_owner,
                };
                let recorded = self
                    .approvals
                    .register(key, run)
                    .and_then(|_| self.approvals.set_state(key, "suspended"));
                if let Err(e) = recorded {
                    // kayıt yoksa koşu sürdürülemez: sessizce düşmesin
                    let short: String = format!("{}: {}", e.class, e.text)
                        .chars()
                        .take(200)
                        .collect();
                    self.diag.log(
                        "ucli_approval_record_failed",
                        &[("run_key", json!(key)), ("error", json!(short))],
                    );
                    return Err(SpawnError(format!(
                        "ucli koşusu onay bekliyor (onay {id}) ama kayıt yazılamadı: {}",
                        e.text
                    )));
                }
                let text = |s: &str| Py::Str(s.to_string());
                return Ok(Py::Object(vec![
                    ("ok".into(), Py::Bool(true)),
                    ("status".into(), text("suspended")),
                    ("run_key".into(), text(key)),
                    ("approval_id".into(), text(&id)),
                ]));
            }
        }
        oneshot::chat_result(out.code, &out.stdout, &out.stderr, secret.as_deref())
    }

    /// `CliProvider.oneshot` / `UcliProvider.oneshot`: `Ok(None)` = bu CLI'da tek atımlık çağrı yok.
    pub fn oneshot(
        &self,
        cli: Cli,
        prompt: &str,
        model: Option<&str>,
        cwd: &str,
        timeout: f64,
    ) -> Result<Option<String>, OneshotError> {
        if cli == Cli::Ucli {
            return self.ucli_oneshot(prompt, model, cwd, timeout).map(Some);
        }
        let Some(argv) = self.providers.oneshot_argv(cli, prompt, model) else {
            return Ok(None);
        };
        self.run_argv(cli.name(), &argv, cwd, timeout).map(Some)
    }

    /// `CliProvider.oneshot`un gövdesi: `cwd` açılır, `argv` orada koşar, çıktı metni döner.
    pub fn run_argv(
        &self,
        name: &str,
        argv: &[String],
        cwd: &str,
        timeout: f64,
    ) -> Result<String, OneshotError> {
        let bad = || OneshotError(format!("{name}: çalıştırılamadı: geçersiz argüman"));
        if cwd.contains('\0') {
            return Err(bad());
        }
        makedirs(cwd, 0o777).map_err(|(p, e)| {
            OneshotError(format!("{name}: çalıştırılamadı: {}", oserr::text(&e, &p)))
        })?;
        let out = self
            .exec(argv, Some(cwd), self.env, timeout)
            .map_err(|f| match f {
                Failed::Timeout => {
                    OneshotError(format!("{name}: {timeout:.0}s içinde yanıt vermedi"))
                }
                Failed::NotUtf8 => OneshotError(format!("{name}: çıktı UTF-8 değil")),
                Failed::BadArgument => bad(),
                Failed::TooBig => OneshotError(format!("{name}: çıktı sınırı aşıldı")),
                Failed::Os(text) => OneshotError(format!("{name}: çalıştırılamadı: {text}")),
            })?;
        oneshot::argv_result(name, out.code, &out.stdout, &out.stderr)
    }

    /// Ayarlardaki anahtar, yoksa anahtar dosyası. Dosya yok / dizin: anahtarsız. Var ama açılamıyor (izin), normal dosya
    /// değil ya da UTF-8 değil: ret (açılamayan dosya "yok" sayılıp miras ortam anahtarıyla sürülmez).
    fn oneshot_key(&self) -> Result<Option<ApiKey>, OneshotError> {
        let p = self.providers;
        let configured = p.settings.byok_value("ucli", "UCLI_API_KEY");
        if !configured.is_empty() {
            return Ok(Some(ApiKey(configured)));
        }
        let path = p.paths.ucli_key_file("");
        let bad = |why: &str| OneshotError(format!("ucli: anahtar dosyası okunamadı ({why})"));
        match fs::metadata(&path) {
            Ok(m) if !m.is_file() && !m.is_dir() => return Err(bad("normal dosya değil")),
            _ => {}
        }
        let size = match fsio::open_regular(&path) {
            Ok((_, size)) => size,
            Err(e) => {
                let gone = matches!(
                    e.raw_os_error(),
                    Some(libc::ENOENT | libc::ENOTDIR | libc::EISDIR)
                ) || fs::metadata(&path).is_ok_and(|m| m.is_dir());
                return if gone {
                    Ok(None)
                } else {
                    Err(bad("açılamadı"))
                };
            }
        };
        let Some(raw) = fsio::read_bytes(&path, fsio::TEXT_MAX_BYTES) else {
            return Err(bad(if size > fsio::TEXT_MAX_BYTES {
                "çok büyük"
            } else {
                "açılamadı"
            }));
        };
        let text = String::from_utf8(raw).map_err(|_| bad("UTF-8 değil"))?;
        let key = strip(&text);
        Ok((!key.is_empty()).then(|| ApiKey(key.to_string())))
    }

    fn ucli_oneshot(
        &self,
        prompt: &str,
        model: Option<&str>,
        cwd: &str,
        timeout: f64,
    ) -> Result<String, OneshotError> {
        let key = self.oneshot_key()?;
        makedirs(cwd, 0o777).map_err(|(p, e)| {
            OneshotError(format!(
                "ucli: çalışma dizini açılamadı: {}",
                oserr::text(&e, &p)
            ))
        })?;
        let configured = self.providers.settings.ucli_endpoint();
        let endpoint = if configured.is_empty() {
            DEFAULT_ENDPOINT
        } else {
            &configured
        };
        let mut req = ChatRequest::new(cwd, prompt);
        req.model = model;
        req.endpoint = Some(endpoint);
        req.api_key = key;
        req.timeout = timeout;
        let value = self
            .chat_once(&req)
            .map_err(|e| OneshotError(format!("ucli: {e}")))?;
        oneshot::ucli_answer(&value)
    }
}
