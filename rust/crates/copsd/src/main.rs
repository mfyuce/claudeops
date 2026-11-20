//! copsd: OSS ön sunucu. D0 = saf vekil: `COPSD_LISTEN` (varsayılan 127.0.0.1:8765) -> `COPSD_UPSTREAM` (Python iç port).
use std::net::SocketAddr;

#[tokio::main]
async fn main() -> std::io::Result<()> {
    let listen: SocketAddr = std::env::var("COPSD_LISTEN").unwrap_or_else(|_| "127.0.0.1:8765".into()).parse().expect("COPSD_LISTEN");
    let up: SocketAddr = std::env::var("COPSD_UPSTREAM").unwrap_or_else(|_| "127.0.0.1:8766".into()).parse().expect("COPSD_UPSTREAM");
    eprintln!("copsd: {listen} -> {up}");
    let proxy = match std::env::var("CLAUDEOPS_FRONT_SECRET") {
        Ok(sec) if !sec.is_empty() => cops_proxy::Proxy::with_secret(up, &sec),
        _ => cops_proxy::Proxy::new(up),
    };
    cops_proxy::serve(listen, proxy).await
}
