//! Aksiyon ve okuma vekili (Python `proxy_action`/`proxy_get`/`proxy_get_raw`/`proxy_post_raw`). Zincir TEK hop:
//! giden gövdede `host` hep `local`.

use std::sync::Arc;
use std::time::Duration;

use bytes::Bytes;
use http::{HeaderName, HeaderValue, Method};
use hyper::body::Body;
use serde_json::{json, Map, Value};

use crate::consts::{self, Timeouts, LOCAL_HOST_NAME};
use crate::endpoint::{urlencode, Endpoint};
use crate::events::{Events, NoEvents};
use crate::flight::{Begin, Flights};
use crate::guard;
use crate::http::{Attempt, BoxError, Pool, Response};
use crate::net::Connector;
use crate::record::{self, HostRecord};
use crate::sign::{self, Caller, OutboundSigner, Principal, SignRequest};

pub const MAX_JSON_BODY: usize = 64 * 1024 * 1024;
pub const MAX_RAW_BODY: usize = 1024 * 1024 * 1024;
/// İmzaya giren en büyük gövde (enterprise tasarımı); üstü gövdesiz imzalanmaz, vekil çağıranı zaten sınırlar.
pub const MAX_ACTION_BODY: usize = 64 * 1024 * 1024;

/// `/api/hosts` yanıtına ya da panele dönen (gövde, HTTP durumu).
pub type Reply = (Value, u16);

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CallError {
    Busy,
    Refused(String),
    Transport(String),
    BadResponse { status: u16, what: &'static str },
}

impl std::fmt::Display for CallError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CallError::Busy => {
                f.write_str("busy: an earlier request to this same endpoint is still in flight")
            }
            CallError::Refused(r) => write!(f, "outbound refused: {r}"),
            CallError::Transport(m) => f.write_str(m),
            CallError::BadResponse { what, .. } => write!(f, "bad response ({what})"),
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct GetOpts {
    /// Üst üste binen aynı-URL isteğini son başarılı yanıtla geri çevir. Benzersiz URL'li çağrılarda KAPAT.
    pub dedup: bool,
    /// `None` = `Timeouts::term_read`.
    pub timeout: Option<Duration>,
}

impl Default for GetOpts {
    fn default() -> Self {
        GetOpts {
            dedup: true,
            timeout: None,
        }
    }
}

pub(crate) struct JsonCall<'a> {
    pub host_name: &'a str,
    pub base_url: &'a str,
    pub path: &'a str,
    pub query: &'a [(String, String)],
    pub body: Option<Vec<u8>>,
    pub method: Method,
    pub timeout: Duration,
    pub dedup: bool,
    pub caller: Caller<'a>,
}

pub struct HostClient {
    pub pool: Pool,
    pub flights: Flights,
    pub signer: Option<Arc<dyn OutboundSigner>>,
    pub events: Arc<dyn Events>,
    pub timeouts: Timeouts,
}

impl Default for HostClient {
    fn default() -> Self {
        HostClient::new(Connector::default())
    }
}

fn unknown_host(name: &str) -> Reply {
    (
        json!({"ok": false, "error": format!("unknown host: {name}"), "code": "unknown_host"}),
        200,
    )
}

fn refused_reply(host: &str, reason: &str) -> Reply {
    (
        json!({"ok": false, "error": format!("{host}: signed identity required, request not sent ({reason})"), "reason": reason}),
        502,
    )
}

fn unreachable_reply(host: &str, detail: &str) -> Reply {
    (
        json!({"ok": false, "error": format!("{host} unreachable: {detail}"), "code": "host_unreachable"}),
        200,
    )
}

fn reply_of(host: &str, r: Result<(u16, Value), CallError>) -> Reply {
    match r {
        Ok((status, body)) => (body, status),
        Err(CallError::Refused(reason)) => refused_reply(host, &reason),
        Err(e) => unreachable_reply(host, &e.to_string()),
    }
}

/// Taban yolunu koruyarak `/taban/yol?sorgu`.
pub(crate) fn target(ep: &Endpoint, path: &str, query: &[(String, String)]) -> String {
    let mut t = format!("{}{}", ep.path, path);
    if !query.is_empty() {
        t.push('?');
        t.push_str(&urlencode(query));
    }
    t
}

/// Kayıtlı token'ı koyar; çağıranın `host`/`token`/`ticket` parametreleri uzağa GİTMEZ.
fn remote_query(query: &[(&str, &str)], token: &str) -> Vec<(String, String)> {
    let mut q: Vec<(String, String)> = query
        .iter()
        .filter(|(k, _)| !matches!(*k, "host" | "token" | "ticket"))
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
    q.push(("token".into(), token.to_string()));
    q
}

impl HostClient {
    pub fn new(connector: Connector) -> HostClient {
        HostClient {
            pool: Pool::new(connector),
            flights: Flights::default(),
            signer: None,
            events: Arc::new(NoEvents),
            timeouts: Timeouts::default(),
        }
    }

    fn sign(
        &self,
        caller: Caller<'_>,
        host_name: &str,
        method: &str,
        path: &str,
        body: Option<&[u8]>,
    ) -> Result<Vec<(HeaderName, HeaderValue)>, CallError> {
        let Caller::User(principal) = caller else {
            return Ok(Vec::new());
        };
        sign::headers_for(
            self.signer.as_deref(),
            SignRequest {
                principal,
                host_name,
                method,
                path,
                body,
            },
        )
        .map_err(|e| CallError::Refused(e.reason))
    }

    /// WS el sıkışması: panelin kendi (LEGACY) kimliğiyle imza.
    pub(crate) fn sign_service(
        &self,
        host_name: &str,
        path: &str,
    ) -> Result<Vec<(HeaderName, HeaderValue)>, CallError> {
        self.sign(
            Caller::User(&Principal::legacy()),
            host_name,
            "GET",
            path,
            None,
        )
    }

    /// Bayat havuz bağlantısı TEK sefer taze bağlantıyla yeniden denenir. Yan etkili istek karşıya ulaşmış olabilirse
    /// TEKRAR DENENMEZ (aksiyon iki kez uygulanırdı).
    async fn exchange(&self, c: &JsonCall<'_>, max_body: usize) -> Result<Response, CallError> {
        let ep = Endpoint::parse(c.base_url)
            .ok_or_else(|| CallError::Transport("invalid host URL".into()))?;
        let signed_path = format!("{}{}", ep.path, c.path);
        let tgt = target(&ep, c.path, c.query);
        let mut last = String::new();
        for _ in 0..2 {
            // Her deneme yeni imza (nonce).
            let mut headers = self.sign(
                c.caller,
                c.host_name,
                c.method.as_str(),
                &signed_path,
                c.body.as_deref(),
            )?;
            if c.body.is_some() {
                headers.push((
                    http::header::CONTENT_TYPE,
                    HeaderValue::from_static("application/json"),
                ));
            }
            let r = self
                .pool
                .attempt(Attempt {
                    method: c.method.clone(),
                    endpoint: &ep,
                    target: &tgt,
                    headers,
                    body: c.body.clone().map(Bytes::from),
                    timeout: c.timeout,
                    total: self.timeouts.total_cap,
                    max_body,
                })
                .await;
            match r {
                Ok(resp) => return Ok(resp),
                Err(f) => {
                    let idempotent = c.method == Method::GET || c.method == Method::HEAD;
                    if f.from_pool && (!f.sent || idempotent) {
                        last = f.message;
                        continue;
                    }
                    return Err(CallError::Transport(f.message));
                }
            }
        }
        Err(CallError::Transport(last))
    }

    fn flight_key(c: &JsonCall<'_>) -> String {
        // Kimlik anahtarda: bir kullanıcının yanıtı başkasına önbellekten verilmez.
        let uid = match c.caller {
            Caller::Unbound => "",
            Caller::User(p) => p.uid.as_str(),
        };
        format!("{uid}\u{0}{}{}?{}", c.base_url, c.path, urlencode(c.query))
    }

    /// Yanıt her zaman JSON NESNESİ. Hiç panik/istisna yok, hata değeri döner.
    pub(crate) async fn json(&self, c: JsonCall<'_>) -> Result<(u16, Value), CallError> {
        let flight = if c.dedup {
            match self.flights.begin(&Self::flight_key(&c)) {
                Begin::Go(f) => Some(f),
                Begin::Busy(Some(good)) => return Ok(good),
                Begin::Busy(None) => return Err(CallError::Busy),
            }
        } else {
            None
        };
        let resp = self.exchange(&c, MAX_JSON_BODY).await?;
        let bad = |what| CallError::BadResponse {
            status: resp.status,
            what,
        };
        let parsed: Value = serde_json::from_slice(&resp.body).map_err(|_| bad("not JSON"))?;
        if !parsed.is_object() {
            return Err(bad("not an object"));
        }
        if let Some(f) = &flight {
            f.remember(resp.status, &parsed);
        }
        Ok((resp.status, parsed))
    }

    /// Salt okuma GET vekili.
    pub async fn proxy_get(
        &self,
        hosts: &[HostRecord],
        host_name: &str,
        path: &str,
        query: &[(&str, &str)],
        opts: GetOpts,
        caller: Caller<'_>,
    ) -> Reply {
        let Some(host) = record::find(hosts, host_name) else {
            return unknown_host(host_name);
        };
        let q = remote_query(query, host.token.expose());
        let r = self
            .json(JsonCall {
                host_name,
                base_url: &host.base_url,
                path,
                query: &q,
                body: None,
                method: Method::GET,
                timeout: opts.timeout.unwrap_or(self.timeouts.term_read),
                dedup: opts.dedup,
                caller,
            })
            .await;
        reply_of(host_name, r)
    }

    /// Aksiyon vekili. Taşıma hatası = (200, ok:false). ASLA dedup'lanmaz.
    pub async fn proxy_action(
        &self,
        hosts: &[HostRecord],
        host_name: &str,
        path: &str,
        mut body: Map<String, Value>,
        timeout: Option<Duration>,
        caller: Caller<'_>,
    ) -> Reply {
        let Some(host) = record::find(hosts, host_name) else {
            return unknown_host(host_name);
        };
        if consts::SECRET_BODY_PATHS.contains(&path)
            && body.contains_key("value")
            && !guard::secret_safe_url(&host.base_url)
        {
            return (
                json!({"ok": false, "error": format!("{host_name}: address is plain http, key not sent (use an https or loopback address)"), "code": "insecure_host"}),
                200,
            );
        }
        body.insert("host".into(), LOCAL_HOST_NAME.into());
        let payload = Value::Object(body).to_string().into_bytes();
        if payload.len() > MAX_ACTION_BODY {
            return (json!({"ok": false, "error": "request body too large"}), 413);
        }
        let q = vec![("token".to_string(), host.token.expose().to_string())];
        let r = self
            .json(JsonCall {
                host_name,
                base_url: &host.base_url,
                path,
                query: &q,
                body: Some(payload),
                method: Method::POST,
                timeout: timeout.unwrap_or(self.timeouts.action),
                dedup: false,
                caller,
            })
            .await;
        reply_of(host_name, r)
    }

    /// Terminal girdisi: geçerli `input_id` varsa kısa zaman aşımıyla en çok 3 deneme AYNI kimlikle (uzak taraf tekrarı
    /// yazmaz). Yalnız taşıma hatası yeniden denenir.
    pub async fn proxy_term_action(
        &self,
        hosts: &[HostRecord],
        host_name: &str,
        path: &str,
        body: Map<String, Value>,
        caller: Caller<'_>,
    ) -> Reply {
        let retryable = consts::TERM_RETRY_PATHS.contains(&path)
            && body.get("input_id").is_some_and(valid_input_id);
        if !retryable {
            return self
                .proxy_action(hosts, host_name, path, body, None, caller)
                .await;
        }
        let mut attempt = 1;
        loop {
            let r = self
                .proxy_action(
                    hosts,
                    host_name,
                    path,
                    body.clone(),
                    Some(self.timeouts.term_attempt),
                    caller,
                )
                .await;
            let transport = r.0["ok"] == false
                && r.0["error"]
                    .as_str()
                    .is_some_and(|e| e.contains(" unreachable"));
            if !transport || attempt >= consts::TERM_MAX_ATTEMPTS {
                return r;
            }
            attempt += 1;
        }
    }

    /// Dosya indirme: ham gövde + `content-type`/`content-disposition`. Hata = (durum, mesaj).
    pub async fn proxy_get_raw(
        &self,
        hosts: &[HostRecord],
        host_name: &str,
        path: &str,
        query: &[(&str, &str)],
        caller: Caller<'_>,
    ) -> Result<Response, (u16, String)> {
        let Some(host) = record::find(hosts, host_name) else {
            return Err((200, format!("unknown host: {host_name}")));
        };
        let q = remote_query(query, host.token.expose());
        let c = JsonCall {
            host_name,
            base_url: &host.base_url,
            path,
            query: &q,
            body: None,
            method: Method::GET,
            timeout: self.timeouts.action,
            dedup: true,
            caller,
        };
        // Ham gövde önbelleğe ALINMAZ; yalnız eşzamanlı aynı indirme geri çevrilir.
        let _flight = match self
            .flights
            .begin(&format!("raw\u{0}{}", Self::flight_key(&c)))
        {
            Begin::Go(f) => f,
            Begin::Busy(_) => {
                return Err((200, format!("{host_name} unreachable: {}", CallError::Busy)))
            }
        };
        match self.exchange(&c, MAX_RAW_BODY).await {
            Ok(mut r) => {
                let keep: Vec<_> = [
                    http::header::CONTENT_TYPE,
                    http::header::CONTENT_DISPOSITION,
                ]
                .into_iter()
                .filter_map(|n| r.headers.get(&n).cloned().map(|v| (n, v)))
                .collect();
                r.headers = keep.into_iter().collect();
                Ok(r)
            }
            Err(CallError::Refused(reason)) => Err((
                502,
                format!("{host_name}: signed identity required, request not sent ({reason})"),
            )),
            Err(e) => Err((200, format!("{host_name} unreachable: {e}"))),
        }
    }

    /// Dosya yükleme: ham istek gövdesi uçtan uca akıtılır.
    #[allow(clippy::too_many_arguments)]
    pub async fn proxy_post_raw<B>(
        &self,
        hosts: &[HostRecord],
        host_name: &str,
        path: &str,
        query: &[(&str, &str)],
        body: B,
        content_length: u64,
        content_type: &str,
        caller: Caller<'_>,
    ) -> Reply
    where
        B: Body<Data = Bytes> + Send + Unpin + 'static,
        B::Error: Into<BoxError>,
    {
        let Some(host) = record::find(hosts, host_name) else {
            return unknown_host(host_name);
        };
        let Some(ep) = Endpoint::parse(&host.base_url) else {
            return unreachable_reply(host_name, "invalid host URL");
        };
        let q = remote_query(query, host.token.expose());
        let mut headers = match self.sign(
            caller,
            host_name,
            "POST",
            &format!("{}{path}", ep.path),
            None,
        ) {
            Ok(h) => h,
            Err(CallError::Refused(reason)) => return refused_reply(host_name, &reason),
            Err(e) => return unreachable_reply(host_name, &e.to_string()),
        };
        let Ok(ct) = HeaderValue::from_str(content_type) else {
            return (json!({"ok": false, "error": "invalid content type"}), 400);
        };
        headers.push((http::header::CONTENT_TYPE, ct));
        match self
            .pool
            .upload(
                &ep,
                &target(&ep, path, &q),
                headers,
                body,
                content_length,
                self.timeouts.action,
                MAX_JSON_BODY,
            )
            .await
        {
            Err(m) => unreachable_reply(host_name, &m),
            Ok(r) => match serde_json::from_slice::<Value>(&r.body) {
                Ok(v) if v.is_object() => (v, r.status),
                _ => (
                    json!({"ok": false, "error": format!("{host_name}: bad response")}),
                    200,
                ),
            },
        }
    }
}

/// Python `term_dedup.valid_id`.
pub fn valid_input_id(v: &Value) -> bool {
    v.as_str().is_some_and(|s| {
        !s.is_empty()
            && s.chars().count() <= 64
            && !s.chars().any(|c| c.is_control() || c.is_whitespace())
    })
}
