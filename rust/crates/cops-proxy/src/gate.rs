//! Çok kullanıcı kapısı (fail-closed). HENÜZ HİÇBİR UCA BAĞLI DEĞİL: kapı kurulmadıkça yerel uçlar bugünkü
//! `cops_auth::Token` yolunu kullanır. Kimlik ve yetki sağlayıcısı birlikte verilir (yarım kurulum yok).
//!
//! [`LocalAuth`]: yerel uçların (Rust'ın kendi cevapladığı uçlar) kararını dışarıdan takılan bir sağlayıcıya veren en küçük
//! kanca. Takılmamışsa ya da [`LocalVerdict::Default`] dönerse bugünkü `web.token` yolu AYNEN çalışır.
//!
//! [`ForwardFilter`]: Python'a aktarılan isteklerdeki kimlik bilgisini aktarmadan önce süzen kanca ([`CredStrip`]: silinecek
//! `Authorization` ve çerez adları; silme işini çekirdek [`crate::strip_credentials`] yapar). Takılmamışsa istek bayt bayt aynı.

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

/// Vekillenen (Python'a aktarılan) isteğin kimlik bilgisi süzme kararı. Varsayılan: hiçbir şey silinmez.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CredStrip {
    /// `true`: TÜM `Authorization` satırları silinir.
    pub authorization: bool,
    /// Adı (Python `strip()` boşluk kümesiyle kırpılmış, ASCII büyük/küçük harf duyarsız) bu listede olan TÜM çerez parçaları
    /// TÜM `Cookie` satırlarından silinir; boşalan satır kalkar. Dokunulmayan satır bayt bayt aynı kalır.
    pub cookies: Vec<String>,
}

impl CredStrip {
    pub fn is_noop(&self) -> bool {
        !self.authorization && self.cookies.is_empty()
    }
}

/// Vekillenen istekler için kimlik bilgisi ön süzgeci (enterprise; plan §7.3). Takılmamışsa istek bugünkü gibi aktarılır.
/// Süzgeç 401 DÖNMEZ: geçersiz bulduğunu siler, yanıt biçimi Python'da kalır.
pub trait ForwardFilter: Send + Sync {
    fn check<'a>(&'a self, view: &'a RequestView) -> BoxFut<'a, CredStrip>;
    /// [`check`](ForwardFilter::check) panikler ya da [`DECISION_TIMEOUT`]'u aşarsa uygulanan süzme (fail-closed). Her istekte
    /// `check`'ten ÖNCE hesaplanır: engellemez, G/Ç ve yan etki yok.
    fn on_failure(&self, view: &RequestView) -> CredStrip;
}

/// Süzgeci ayrı görevde, [`DECISION_TIMEOUT`] sınırıyla çağırır; panik ya da süre aşımı = `on_failure`.
pub async fn forward_check(f: Arc<dyn ForwardFilter>, view: RequestView) -> CredStrip {
    let fail = f.on_failure(&view);
    let task = tokio::spawn(async move { f.check(&view).await });
    bounded(
        task,
        Instant::now() + DECISION_TIMEOUT,
        "authz_forward_filter_failed",
    )
    .await
    .unwrap_or(fail)
}

/// [`RouteHook::handle`] için varsayılan süre (giriş uçları kasıtlı bekletebilir: hesap gecikmesi en çok 30 sn + yuva 5 sn).
pub const ROUTE_TIMEOUT: Duration = Duration::from_secs(60);

/// [`RouteHook::body_timeout`] varsayılanı: gövde bu sürede tamamlanmazsa 408.
pub const ROUTE_BODY_TIMEOUT: Duration = Duration::from_secs(10);

/// Kancaya verilen gövde okunamadı.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BodyError {
    /// Gövde [`RouteHook::route`]'un verdiği sınırı aşıyor (fazlası okunmadı).
    TooLarge,
    /// Bağlantı/akış hatası.
    Read,
}

/// Kancanın cevapladığı istek: görünüm (başlıklar her satır, Latin-1), sınırlı gövde, istemcinin https olup olmadığı
/// ([`crate::client_https`]: yalnız loopback eşin `X-Forwarded-Proto`'su).
#[derive(Debug, Clone)]
pub struct RouteRequest {
    pub view: RequestView,
    pub body: Result<bytes::Bytes, BodyError>,
    pub https: bool,
}

/// Kancanın yanıtı. Başlıklar sırayla eklenir (aynı ad birden çok kez olabilir); geçersiz ad/değer atlanır.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RouteResponse {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

impl RouteResponse {
    /// `{"ok": false, "error": <e>}` JSON (Python `json.dumps` ayırıcıları), `Cache-Control: no-store`.
    pub fn error(status: u16, e: &str) -> RouteResponse {
        RouteResponse {
            status,
            headers: vec![
                (
                    "Content-Type".into(),
                    "application/json; charset=utf-8".into(),
                ),
                ("Cache-Control".into(), "no-store".into()),
            ],
            body: format!(
                "{{\"ok\": false, \"error\": {}}}",
                serde_json::Value::from(e)
            )
            .into_bytes(),
        }
    }
}

/// Python'a gitmeden Rust'ın KENDİSİNİN cevapladığı uçlar (enterprise; ör. `/api/auth/*`, A6b-2). Takılmamışsa ya da
/// [`route`](RouteHook::route) `None` dönerse istek bugünkü gibi işlenir (yerel uç ya da Python'a aktarım).
pub trait RouteHook: Send + Sync {
    /// Her istekte çağrılır: G/Ç YOK, engellemez, yan etkisiz. `Some(sınır)` = bu istek kancanındır, gövde en çok `sınır`
    /// bayt okunur (aşarsa [`BodyError::TooLarge`]).
    fn route(&self, view: &RequestView) -> Option<usize>;
    fn handle(&self, req: RouteRequest) -> BoxFut<'_, RouteResponse>;
    /// Gövdenin tamamını okuma süre sınırı; aşılırsa kanca çağrılmadan 408 ve bağlantı kapanır (yavaş gövde saldırısı).
    fn body_timeout(&self) -> Duration {
        ROUTE_BODY_TIMEOUT
    }
    /// [`route_call`] süre sınırı.
    fn timeout(&self) -> Duration {
        ROUTE_TIMEOUT
    }
}

/// Kancayı ayrı görevde, kancanın süre sınırıyla çağırır: panik = 500, süre aşımı = 503 (Python'a DÜŞÜLMEZ: kanca üstlendiği
/// uçta tek yazardır).
pub async fn route_call(hook: Arc<dyn RouteHook>, req: RouteRequest) -> RouteResponse {
    let limit = hook.timeout();
    let mut task = tokio::spawn(async move { hook.handle(req).await });
    match timeout_at(Instant::now() + limit, &mut task).await {
        Ok(Ok(r)) => r,
        Ok(Err(e)) => {
            diag("route_hook_failed", &e.to_string());
            RouteResponse::error(500, "internal error")
        }
        Err(_) => {
            task.abort();
            diag("route_hook_failed", "timeout");
            RouteResponse::error(503, "timeout")
        }
    }
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
