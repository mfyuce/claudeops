//! `host_bridge.proto` istemcisi (Python `web_grpc` istemci tarafı). Mesajlar elle tanımlı (derlemede protoc yok); alan
//! numaralarını `tests/parity.rs` `.proto` ile karşılaştırır. Bağlantı ortak kurucudan geçer (her bağlanışta peer
//! denetimi).

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use futures_util::StreamExt;
use hyper_util::rt::TokioIo;
use serde_json::{json, Map, Value};
use tonic::client::Grpc;
use tonic::codegen::http::uri::PathAndQuery;
use tonic::transport::{Channel, Endpoint as TonicEndpoint, Uri};
use tonic_prost::ProstCodec;

use crate::endpoint::Endpoint;
use crate::net::Connector;
use crate::push::{FrameStream, Open};

pub mod pb {
    use std::collections::HashMap;

    #[derive(Clone, PartialEq, prost::Message)]
    pub struct PingRequest {}

    #[derive(Clone, PartialEq, prost::Message)]
    pub struct PingResponse {
        #[prost(string, tag = "1")]
        pub claudeops_version: String,
    }

    #[derive(Clone, PartialEq, prost::Message)]
    pub struct StreamStatusRequest {}

    #[derive(Clone, PartialEq, prost::Message)]
    pub struct CliOptions {
        #[prost(string, repeated, tag = "1")]
        pub models: Vec<String>,
        #[prost(string, repeated, tag = "2")]
        pub permission_modes: Vec<String>,
        #[prost(string, repeated, tag = "3")]
        pub effort_levels: Vec<String>,
        #[prost(string, repeated, tag = "4")]
        pub cyclable_modes: Vec<String>,
    }

    #[derive(Clone, PartialEq, prost::Message)]
    pub struct SessionRow {
        #[prost(string, tag = "1")]
        pub name: String,
        #[prost(string, tag = "2")]
        pub host: String,
        #[prost(string, tag = "3")]
        pub model: String,
        #[prost(string, tag = "4")]
        pub cwd: String,
        #[prost(string, tag = "5")]
        pub cli: String,
        #[prost(bool, tag = "6")]
        pub running: bool,
        #[prost(int32, optional, tag = "7")]
        pub pid: Option<i32>,
        #[prost(double, optional, tag = "8")]
        pub cpu: Option<f64>,
        #[prost(string, tag = "9")]
        pub kind: String,
        #[prost(bool, optional, tag = "10")]
        pub needs_ho: Option<bool>,
        #[prost(bool, optional, tag = "11")]
        pub busy: Option<bool>,
        #[prost(int32, optional, tag = "12")]
        pub history_size: Option<i32>,
        #[prost(bool, tag = "13")]
        pub registered: bool,
        #[prost(bool, tag = "14")]
        pub tmux: bool,
        #[prost(string, optional, tag = "15")]
        pub live_model: Option<String>,
        #[prost(string, optional, tag = "16")]
        pub live_effort: Option<String>,
        #[prost(bool, tag = "17")]
        pub instance: bool,
        #[prost(string, optional, tag = "18")]
        pub blueprint: Option<String>,
        #[prost(bool, optional, tag = "19")]
        pub ucli_write: Option<bool>,
        #[prost(bool, optional, tag = "20")]
        pub ucli_exec: Option<bool>,
        #[prost(double, optional, tag = "21")]
        pub ucli_max_cost_usd: Option<f64>,
    }

    #[derive(Clone, PartialEq, prost::Message)]
    pub struct StatusUpdate {
        #[prost(bool, tag = "1")]
        pub ok: bool,
        #[prost(string, tag = "2")]
        pub error: String,
        #[prost(message, repeated, tag = "3")]
        pub sessions: Vec<SessionRow>,
        #[prost(message, repeated, tag = "4")]
        pub closed: Vec<SessionRow>,
        #[prost(message, repeated, tag = "5")]
        pub retired: Vec<SessionRow>,
        #[prost(string, repeated, tag = "6")]
        pub cli_list: Vec<String>,
        #[prost(map = "string, message", tag = "7")]
        pub cli_options: HashMap<String, CliOptions>,
        #[prost(string, repeated, tag = "8")]
        pub dups: Vec<String>,
        #[prost(string, tag = "9")]
        pub extras_json: String,
    }

    #[derive(Clone, PartialEq, prost::Message)]
    pub struct StreamTermOutputRequest {
        #[prost(string, tag = "1")]
        pub name: String,
        #[prost(string, tag = "2")]
        pub lang: String,
    }

    #[derive(Clone, PartialEq, prost::Message)]
    pub struct TermUpdate {
        #[prost(bool, tag = "1")]
        pub ok: bool,
        #[prost(string, tag = "2")]
        pub error: String,
        #[prost(string, tag = "3")]
        pub text: String,
        #[prost(int32, optional, tag = "4")]
        pub cols: Option<i32>,
        #[prost(int32, optional, tag = "5")]
        pub rows: Option<i32>,
        #[prost(int32, optional, tag = "6")]
        pub history_size: Option<i32>,
        #[prost(bool, tag = "7")]
        pub masked: bool,
        #[prost(string, tag = "8")]
        pub mode: String,
    }
}

const SERVICE: &str = "/claudeops.hostbridge.v1.HostBridge";
const EXTRA_KEYS: [&str; 4] = ["disk_clean", "orphan_watch", "fwd", "build"];

fn opt_str(s: &str) -> Value {
    if s.is_empty() {
        Value::Null
    } else {
        s.into()
    }
}

pub fn session_row_to_value(r: &pb::SessionRow) -> Value {
    let flags = match r.ucli_write {
        Some(write) => {
            json!({"write": write, "exec": r.ucli_exec.unwrap_or(false), "max_cost_usd": r.ucli_max_cost_usd})
        }
        None => Value::Null,
    };
    json!({
        "name": r.name, "host": r.host, "model": r.model, "cwd": r.cwd, "cli": r.cli, "running": r.running,
        "kind": opt_str(&r.kind), "registered": r.registered, "tmux": r.tmux, "instance": r.instance,
        "pid": r.pid, "cpu": r.cpu, "needs_ho": r.needs_ho, "busy": r.busy, "history_size": r.history_size,
        "live_model": r.live_model, "live_effort": r.live_effort, "blueprint": r.blueprint, "ucli_flags": flags,
    })
}

pub fn status_to_value(m: &pb::StatusUpdate) -> Value {
    let rows = |v: &[pb::SessionRow]| v.iter().map(session_row_to_value).collect::<Vec<_>>();
    let cli: Map<String, Value> = m
        .cli_options
        .iter()
        .map(|(k, o)| {
            (
                k.clone(),
                json!({"models": o.models, "permission_modes": o.permission_modes,
                       "effort_levels": o.effort_levels, "cyclable_modes": o.cyclable_modes}),
            )
        })
        .collect();
    let mut out = json!({
        "ok": true, "error": null,
        "sessions": rows(&m.sessions), "closed": rows(&m.closed), "retired": rows(&m.retired),
        "cli_list": m.cli_list, "cli_options": cli, "dups": m.dups,
    });
    if let Ok(Value::Object(extras)) = serde_json::from_str::<Value>(&m.extras_json) {
        for k in EXTRA_KEYS {
            if let Some(v) = extras.get(k) {
                out[k] = v.clone();
            }
        }
    }
    out
}

pub fn term_to_value(m: &pb::TermUpdate) -> Value {
    if !m.ok {
        return json!({"ok": false, "error": opt_str(&m.error)});
    }
    json!({"ok": true, "text": m.text, "masked": m.masked, "mode": opt_str(&m.mode),
           "cols": m.cols, "rows": m.rows, "history_size": m.history_size})
}

/// Uzak host terminal akışını bu taşıma yolunda reddetti (`PERMISSION_DENIED`) nedeninin öneki; bağlantı hatası DEĞİL.
pub(crate) const REFUSED_BY_HOST: &str = "grpc permission denied: ";

fn stream_error(s: tonic::Status) -> String {
    if s.code() == tonic::Code::PermissionDenied {
        format!("{REFUSED_BY_HOST}{}", s.message())
    } else {
        s.to_string()
    }
}

/// URL başına TEK kalıcı kanal (keepalive açık; kopunca tonic yeniden bağlanır, her bağlanış kurucudan geçer).
#[derive(Clone)]
pub struct GrpcClient {
    connector: Connector,
    channels: Arc<Mutex<HashMap<String, Channel>>>,
}

#[derive(Clone)]
struct Dial {
    connector: Connector,
    target: Endpoint,
}

impl tower_service::Service<Uri> for Dial {
    type Response = TokioIo<crate::net::Stream>;
    type Error = std::io::Error;
    type Future = futures_util::future::BoxFuture<'static, std::io::Result<Self::Response>>;

    fn poll_ready(
        &mut self,
        _: &mut std::task::Context<'_>,
    ) -> std::task::Poll<std::io::Result<()>> {
        std::task::Poll::Ready(Ok(()))
    }

    fn call(&mut self, _: Uri) -> Self::Future {
        let d = self.clone();
        Box::pin(async move {
            d.connector
                .connect(&d.target, &[b"h2"])
                .await
                .map(TokioIo::new)
        })
    }
}

impl GrpcClient {
    pub fn new(connector: Connector) -> GrpcClient {
        GrpcClient {
            connector,
            channels: Arc::default(),
        }
    }

    fn channel(&self, url: &str) -> Result<Channel, String> {
        let mut map = self.channels.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(c) = map.get(url) {
            return Ok(c.clone());
        }
        let target = Endpoint::parse(url).ok_or("invalid gRPC URL")?;
        let scheme = if target.https { "https" } else { "http" };
        let origin: Uri = format!("{scheme}://{}", target.authority())
            .parse()
            .map_err(|_| "invalid gRPC URL")?;
        // Bağlantı (TLS dahil) kendi kurucumuzda: tonic'e düz `http` verilir, `:scheme` `origin`den.
        let ep = TonicEndpoint::from_shared(format!("http://{}", target.authority()))
            .map_err(|_| "invalid gRPC URL")?
            .origin(origin)
            .connect_timeout(Duration::from_secs(10))
            .http2_keep_alive_interval(Duration::from_secs(20))
            .keep_alive_timeout(Duration::from_secs(5))
            .keep_alive_while_idle(true);
        let channel = ep.connect_with_connector_lazy(Dial {
            connector: self.connector.clone(),
            target,
        });
        map.insert(url.to_string(), channel.clone());
        Ok(channel)
    }

    /// Kayıtta olmayan adreslerin kanalları bırakılır.
    pub fn retain(&self, keep: impl Fn(&str) -> bool) {
        self.channels
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .retain(|k, _| keep(k));
    }

    fn request<T>(msg: T, token: &str) -> Result<tonic::Request<T>, String> {
        let mut req = tonic::Request::new(msg);
        let v = format!("Bearer {token}")
            .parse()
            .map_err(|_| "invalid token")?;
        req.metadata_mut().insert("authorization", v);
        Ok(req)
    }

    async fn ready(&self, url: &str) -> Result<Grpc<Channel>, String> {
        let mut g = Grpc::new(self.channel(url)?).max_decoding_message_size(4 * 1024 * 1024);
        g.ready().await.map_err(|e| e.to_string())?;
        Ok(g)
    }

    /// Transport + kimlik + servis gerçekten çalışıyor mu.
    pub async fn probe(&self, url: &str, token: &str, timeout: Duration) -> bool {
        let call = async {
            let mut g = self.ready(url).await?;
            g.unary::<_, pb::PingResponse, _>(
                Self::request(pb::PingRequest {}, token)?,
                PathAndQuery::from_maybe_shared(format!("{SERVICE}/Ping"))
                    .map_err(|e| e.to_string())?,
                ProstCodec::default(),
            )
            .await
            .map_err(|s| s.code().to_string())
        };
        matches!(tokio::time::timeout(timeout, call).await, Ok(Ok(_)))
    }

    fn open<Req, Resp>(
        &self,
        url: String,
        token: String,
        method: &'static str,
        msg: Req,
        map: fn(&Resp) -> Value,
    ) -> Open
    where
        Req: prost::Message + 'static,
        Resp: prost::Message + Default + 'static,
    {
        let me = self.clone();
        Box::pin(async move {
            let mut g = me.ready(&url).await?;
            let stream = g
                .server_streaming::<Req, Resp, _>(
                    Self::request(msg, &token)?,
                    PathAndQuery::from_maybe_shared(format!("{SERVICE}/{method}"))
                        .map_err(|e| e.to_string())?,
                    ProstCodec::default(),
                )
                .await
                .map_err(stream_error)?
                .into_inner();
            let frames = stream.map(move |m| match m {
                Ok(m) => Ok(Some(map(&m))),
                Err(s) => Err(stream_error(s)),
            });
            Ok(Box::pin(frames) as FrameStream)
        })
    }

    pub fn status_stream(&self, url: &str, token: &str) -> Open {
        self.open(
            url.into(),
            token.into(),
            "StreamStatus",
            pb::StreamStatusRequest {},
            status_to_value,
        )
    }

    pub fn term_stream(&self, url: &str, token: &str, name: &str, lang: &str) -> Open {
        let req = pb::StreamTermOutputRequest {
            name: name.into(),
            lang: lang.into(),
        };
        self.open(
            url.into(),
            token.into(),
            "StreamTermOutput",
            req,
            term_to_value,
        )
    }
}
