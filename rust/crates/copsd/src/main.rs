//! copsd: OSS ön sunucu. D0 = saf vekil: `--listen` (varsayılan 127.0.0.1:8765) -> `--upstream` (Python iç port, varsayılan 127.0.0.1:18765).
//! Ön kapı gizlisi: `--secret-file` (varsayılan ~/.claude/claudeops/front.secret; 0600 değilse REDDEDİLİR) ya da `CLAUDEOPS_FRONT_SECRET`.
//! `--dist <py/webui/dist>`: /assets/* ve /favicon.svg diskten sunulur (yoksa Python'a aktarılır).
//! Ortam: `COPSD_LISTEN`, `COPSD_UPSTREAM` bayrakların yedeğidir.
use std::net::SocketAddr;
use std::os::unix::fs::PermissionsExt;

fn arg(name: &str) -> Option<String> {
    let a: Vec<String> = std::env::args().collect();
    a.iter().position(|x| x == name).and_then(|i| a.get(i + 1).cloned())
}

fn read_secret() -> Result<Option<String>, String> {
    if let Ok(s) = std::env::var("CLAUDEOPS_FRONT_SECRET") {
        if !s.is_empty() {
            return Ok(Some(s));
        }
    }
    let path = arg("--secret-file").unwrap_or_else(|| format!("{}/.claude/claudeops/front.secret", std::env::var("HOME").unwrap_or_default()));
    match std::fs::metadata(&path) {
        Err(_) => Ok(None),
        Ok(m) => {
            if m.permissions().mode() & 0o077 != 0 {
                return Err(format!("{path}: izinler 0600 değil, reddedildi"));
            }
            let s = std::fs::read_to_string(&path).map_err(|e| format!("{path}: {e}"))?;
            Ok(Some(s.trim().to_string()).filter(|s| !s.is_empty()))
        }
    }
}

#[tokio::main]
async fn main() -> std::io::Result<()> {
    let listen: SocketAddr = arg("--listen").or_else(|| std::env::var("COPSD_LISTEN").ok()).unwrap_or_else(|| "127.0.0.1:8765".into()).parse().expect("--listen");
    let up: SocketAddr = arg("--upstream").or_else(|| std::env::var("COPSD_UPSTREAM").ok()).unwrap_or_else(|| "127.0.0.1:18765".into()).parse().expect("--upstream");
    let secret = match read_secret() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("copsd: {e}");
            std::process::exit(2);
        }
    };
    eprintln!("copsd: {listen} -> {up} (gizli: {})", if secret.is_some() { "var" } else { "YOK, X-Forwarded-For güvenilmez" });
    let proxy = match secret {
        Some(sec) => cops_proxy::Proxy::with_secret(up, &sec),
        None => cops_proxy::Proxy::new(up),
    };
    let proxy = match arg("--dist") {
        Some(d) => proxy.with_dist(std::path::PathBuf::from(d)),
        None => proxy,
    };
    cops_proxy::serve(listen, proxy).await
}
