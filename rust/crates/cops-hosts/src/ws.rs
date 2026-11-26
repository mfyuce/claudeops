//! Uzak `/ws` ve `/ws/term` istemcisi. Soket ve TLS ortak kurucudan (peer denetimi) gelir.

use std::time::Duration;

use futures_util::StreamExt;
use serde_json::Value;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::protocol::WebSocketConfig;
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::WebSocketStream;

use crate::endpoint::{urlencode, Endpoint};
use crate::net::Stream;
use crate::proxy::HostClient;
use crate::push::{FrameStream, Open, SkipLog};
use crate::record::HostRecord;

/// Büyük filoda durum karesi 1 MiB'ı aşabilir.
const MAX_MESSAGE: usize = 16 * 1024 * 1024;

pub type Parser = fn(&Value) -> Option<Value>;

/// `{"type":"status","data":{...}}` -> `finalize`ın beklediği ham şekil. `sessions` dizi değilse kare atlanır
/// (boş oturum listesi gibi kaydedilmez).
pub fn parse_status_frame(v: &Value) -> Option<Value> {
    let data = (v.get("type")? == "status")
        .then(|| v.get("data"))??
        .as_object()?;
    data.get("sessions")?.as_array()?;
    let mut out: serde_json::Map<String, Value> = [
        "sessions",
        "closed",
        "retired",
        "cli_list",
        "cli_options",
        "dups",
        "disk_clean",
        "orphan_watch",
        "fwd",
        "build",
    ]
    .iter()
    .filter_map(|k| data.get(*k).map(|v| (k.to_string(), v.clone())))
    .collect();
    out.insert("ok".into(), true.into());
    Some(Value::Object(out))
}

/// `{"type":"term","data":{...}}` -> `data`.
pub fn parse_term_frame(v: &Value) -> Option<Value> {
    let data = (v.get("type")? == "term").then(|| v.get("data"))??;
    data.is_object().then(|| data.clone())
}

/// Kare JSON nesnesi değil (okunamadı ya da dizi/sayı): atlanır ve loglanır.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SkippedFrame;

/// Python `_ws_envelope` + ayrıştırıcı: `Err(SkippedFrame)` = kare JSON nesnesi değil (atlanır ve loglanır),
/// `Ok(None)` = geçerli ama ilgisiz kare (loglanmaz), `Ok(Some)` = veri.
pub fn decode_frame(raw: &[u8], parse: Parser) -> Result<Option<Value>, SkippedFrame> {
    match serde_json::from_slice::<Value>(raw) {
        Ok(v) if v.is_object() => Ok(parse(&v)),
        _ => Err(SkippedFrame),
    }
}

impl HostClient {
    /// Bağlan + yükselt. Sorguya token eklenir; imza panelin kendi kimliğiyle (her bağlantıda yeni).
    pub(crate) async fn ws_connect(
        &self,
        host_name: &str,
        base_url: &str,
        token: &str,
        path: &str,
        extra: &[(String, String)],
        open_timeout: Duration,
    ) -> Result<WebSocketStream<Stream>, String> {
        let ep = Endpoint::parse(base_url).ok_or("invalid host URL")?;
        let signed_path = format!("{}{path}", ep.path);
        let mut q = vec![("token".to_string(), token.to_string())];
        q.extend_from_slice(extra);
        let url = format!(
            "{}://{}{signed_path}?{}",
            if ep.https { "wss" } else { "ws" },
            ep.authority(),
            urlencode(&q)
        );
        // Hata metni URL'yi (token) taşımasın.
        let mut req = url
            .into_client_request()
            .map_err(|_| "invalid websocket URL")?;
        for (k, v) in self
            .sign_service(host_name, &signed_path)
            .map_err(|e| e.to_string())?
        {
            req.headers_mut().insert(k, v);
        }
        let config = WebSocketConfig::default()
            .max_message_size(Some(MAX_MESSAGE))
            .max_frame_size(Some(MAX_MESSAGE));
        let connect = async {
            let stream = self
                .pool
                .connector
                .connect(&ep, &[])
                .await
                .map_err(|e| e.to_string())?;
            tokio_tungstenite::client_async_with_config(req, stream, Some(config))
                .await
                .map(|(ws, _)| ws)
                .map_err(|e| e.to_string())
        };
        tokio::time::timeout(open_timeout, connect)
            .await
            .map_err(|_| "timed out".to_string())?
    }

    /// `101`e ulaşmak yeterli.
    pub(crate) async fn ws_probe(&self, host: &HostRecord) -> bool {
        let t = self.timeouts.ws_probe;
        match self
            .ws_connect(
                &host.name,
                &host.base_url,
                host.token.expose(),
                "/ws",
                &[],
                t,
            )
            .await
        {
            Ok(mut ws) => {
                let _ = tokio::time::timeout(Duration::from_secs(1), ws.close(None)).await;
                true
            }
            Err(_) => false,
        }
    }
}

/// Tüketiciye verilecek akış açıcı. İstemci pingi YOK (sunucu kalp atışı var).
pub(crate) fn open(
    client: std::sync::Arc<HostClient>,
    host: HostRecord,
    path: &'static str,
    extra: Vec<(String, String)>,
    parse: Parser,
    skips: std::sync::Arc<SkipLog>,
) -> Open {
    // Python `_ws_envelope` türü: durum akışı "status", terminal akışı "term".
    let kind: &'static str = if path == "/ws/term" { "term" } else { "status" };
    Box::pin(async move {
        let ws = client
            .ws_connect(
                &host.name,
                &host.base_url,
                host.token.expose(),
                path,
                &extra,
                client.timeouts.ws_open,
            )
            .await?;
        let events = client.events.clone();
        let frames = ws.filter_map(move |m| {
            let envelope = |raw: &[u8]| {
                decode_frame(raw, parse).unwrap_or_else(|SkippedFrame| {
                    // Okunamayan ya da nesne olmayan kare atlanır (akış sürer), dakikada en çok bir kez loglanır.
                    skips.report(events.as_ref(), kind);
                    None
                })
            };
            let out = match m {
                Err(e) => Some(Err(e.to_string())),
                Ok(Message::Text(t)) => Some(Ok(envelope(t.as_bytes()))),
                Ok(Message::Binary(b)) => Some(Ok(envelope(&b))),
                // Denetim çerçeveleri tüketiciye ulaşmaz (Python ile aynı: canlılık veri çerçevesinden).
                Ok(_) => None,
            };
            async move { out }
        });
        Ok(Box::pin(frames) as FrameStream)
    })
}
