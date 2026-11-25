//! Çok kullanıcı kapısı (fail-closed). HENÜZ HİÇBİR UCA BAĞLI DEĞİL: kapı kurulmadıkça yerel uçlar bugünkü
//! `cops_auth::Token` yolunu kullanır. Kimlik ve yetki sağlayıcısı birlikte verilir (yarım kurulum yok).
//!
//! [`LocalAuth`]: yerel uçların (Rust'ın kendi cevapladığı uçlar) kararını dışarıdan takılan bir sağlayıcıya veren en küçük
//! kanca. Takılmamışsa ya da [`LocalVerdict::Default`] dönerse bugünkü `web.token` yolu AYNEN çalışır.

use cops_auth::authz::{
    AuditSink, Authenticator, Authorizer, BoxFut, Principal, RequestView, Resource,
};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::Arc;
use std::time::Duration;
use tokio::task::JoinHandle;
use tokio::time::{timeout_at, Instant};

/// Tek istek için karar süresi (kimlik + tüm kaynakların yetkisi). Aşan karar REDDİR.
pub const DECISION_TIMEOUT: Duration = Duration::from_secs(2);
/// 403 gövdesi (Python `_gate` ile aynı alanlar).
pub const FORBIDDEN_BODY: &str = r#"{"ok": false, "error": "forbidden"}"#;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Decision {
    Allow(Principal),
    /// 401: kimlik yok ya da doğrulanamadı.
    Unauthorized,
    /// 403: kimlik var, yetki yok ya da karar verilemedi.
    Forbidden,
}

#[derive(Clone)]
pub struct Gate {
    authenticator: Arc<dyn Authenticator>,
    authorizer: Arc<dyn Authorizer>,
    sinks: Vec<Arc<dyn AuditSink>>,
    timeout: Duration,
}

fn diag(event: &str, detail: &str) {
    let detail: String = detail.chars().take(200).collect();
    eprintln!("copsd: {event}: {detail}");
}

/// Görevi süre sınırıyla bekler; panik ya da zaman aşımı = `None` (görev iptal edilir).
async fn bounded<T>(mut task: JoinHandle<T>, deadline: Instant, event: &str) -> Option<T> {
    match timeout_at(deadline, &mut task).await {
        Ok(Ok(v)) => Some(v),
        Ok(Err(e)) => {
            diag(event, &e.to_string());
            None
        }
        Err(_) => {
            task.abort();
            diag(event, "timeout");
            None
        }
    }
}

/// Yerel uç kararı.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LocalVerdict {
    /// Sağlayıcı bu isteğe karar vermiyor: bugünkü `web.token` yolu.
    Default,
    Allow,
    /// 401.
    Unauthorized,
    /// 403.
    Forbidden,
}

/// Yerel uç kimlik/yetki kancası. Çağrı [`local_decide`] ile süre sınırlı ve panik korumalıdır.
pub trait LocalAuth: Send + Sync {
    fn decide<'a>(&'a self, view: &'a RequestView) -> BoxFut<'a, LocalVerdict>;
}

/// Kancayı ayrı görevde, [`DECISION_TIMEOUT`] sınırıyla çağırır: panik ya da süre aşımı = 401 (fail-closed).
pub async fn local_decide(hook: Arc<dyn LocalAuth>, view: RequestView) -> LocalVerdict {
    let task = tokio::spawn(async move { hook.decide(&view).await });
    bounded(
        task,
        Instant::now() + DECISION_TIMEOUT,
        "authz_local_hook_failed",
    )
    .await
    .unwrap_or(LocalVerdict::Unauthorized)
}

impl Gate {
    pub fn new(authenticator: Arc<dyn Authenticator>, authorizer: Arc<dyn Authorizer>) -> Gate {
        Gate {
            authenticator,
            authorizer,
            sinks: Vec::new(),
            timeout: DECISION_TIMEOUT,
        }
    }

    pub fn with_sink(mut self, sink: Arc<dyn AuditSink>) -> Gate {
        self.sinks.push(sink);
        self
    }

    pub fn with_timeout(mut self, timeout: Duration) -> Gate {
        self.timeout = timeout;
        self
    }

    fn audit(&self, p: &Principal, action: &str, res: &Resource, status: u16) {
        for s in &self.sinks {
            if catch_unwind(AssertUnwindSafe(|| s.record(p, action, res, status))).is_err() {
                diag("authz_audit_failed", action);
            }
        }
    }

    /// `resources` boşsa RED. Her yetki kararı (200/403) denetime düşer; ilk redde durulur. 401 denetlenmez (kimlik yok).
    pub async fn decide(&self, view: RequestView, resources: &[Resource]) -> Decision {
        let deadline = Instant::now() + self.timeout;
        let action = cops_auth::authz::action_for(&view.method, &view.path);
        let authn = self.authenticator.clone();
        let task = tokio::spawn(async move { authn.authenticate(&view).await });
        let p = match bounded(task, deadline, "authz_authenticator_failed").await {
            Some(Ok(Some(p))) => p,
            Some(Ok(None)) | None => return Decision::Unauthorized,
            Some(Err(e)) => {
                diag("authz_authenticator_failed", &format!("{e:?}"));
                return Decision::Unauthorized;
            }
        };
        if resources.is_empty() {
            return Decision::Forbidden;
        }
        for res in resources {
            let (authz, who, what) = (self.authorizer.clone(), p.clone(), res.clone());
            let task = tokio::spawn(async move { authz.authorize(&who, action, &what).await });
            let ok = match bounded(task, deadline, "authz_authorizer_failed").await {
                Some(Ok(ok)) => ok,
                Some(Err(e)) => {
                    diag("authz_authorizer_failed", &format!("{e:?}"));
                    false
                }
                None => false,
            };
            self.audit(&p, action, res, if ok { 200 } else { 403 });
            if !ok {
                return Decision::Forbidden;
            }
        }
        Decision::Allow(p)
    }
}
