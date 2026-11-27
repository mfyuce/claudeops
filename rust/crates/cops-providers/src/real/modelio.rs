//! Gerçek [`ModelIo`]: saat, belge deposu, sınırlı dosya okuma, alt süreç ve HTTP.

use crate::model_sources::{HttpRequest, ModelIo, RunRequest};
use crate::probe::{Diag, Paths};
use crate::real::docs::DocStore;
use crate::real::http::HttpClient;
use crate::real::process::{self, Capture, Spec};
use crate::real::{fsio, Env};
use crate::spawn_exec::DiagSink;
use serde_json::Value;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

pub struct RealModelIo {
    env: Env,
    docs: Arc<dyn DocStore>,
    claude_models_json: String,
    http: HttpClient,
    diag: Option<Arc<dyn DiagSink>>,
}

impl RealModelIo {
    pub fn new(paths: &Paths, env: Env, docs: Arc<dyn DocStore>) -> RealModelIo {
        let http = HttpClient::new(env.clone());
        RealModelIo {
            env,
            docs,
            claude_models_json: paths.claude_models_json(),
            http,
            diag: None,
        }
    }

    /// Yutulan çekim hatalarının (`models_fetch_failed`) yazılacağı günlük (gerçek: `diag_log`).
    pub fn with_diag(mut self, diag: Arc<dyn DiagSink>) -> RealModelIo {
        self.diag = Some(diag);
        self
    }

    pub fn with_http(mut self, http: HttpClient) -> RealModelIo {
        self.http = http;
        self
    }
}

impl ModelIo for RealModelIo {
    fn diag(&self, diag: &Diag) {
        if let Some(sink) = &self.diag {
            sink.log(diag);
        }
    }
    fn monotonic_secs(&self) -> f64 {
        let mut ts = libc::timespec {
            tv_sec: 0,
            tv_nsec: 0,
        };
        // SAFETY: `ts` geçerli ve bu çağrıya özel.
        if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut ts) } != 0 {
            return 0.0;
        }
        ts.tv_sec as f64 + ts.tv_nsec as f64 / 1e9
    }
    fn wall_secs(&self) -> f64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0.0, |d| d.as_secs_f64())
    }
    fn claude_models_doc(&self) -> Option<Value> {
        self.docs
            .read("claude_models", &self.claude_models_json)
            .map(|d| d.to_value())
    }
    fn read_file(&self, path: &str, max: u64) -> Option<Vec<u8>> {
        fsio::read_bytes(path, max)
    }
    fn run_stdout(&self, req: &RunRequest) -> Option<Vec<u8>> {
        let spec = Spec {
            argv: &req.argv,
            cwd: None,
            env: &self.env,
            timeout: req.timeout,
            stdout: Capture::Bounded(req.max_stdout),
            stderr: Capture::Discard,
        };
        let out = process::run(&spec).ok()?;
        (out.code == 0).then_some(out.stdout)
    }
    fn http_get(&self, req: &HttpRequest) -> Option<Vec<u8>> {
        self.http.get(req).ok()
    }
}
