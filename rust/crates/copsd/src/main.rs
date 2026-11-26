//! copsd ikilisi: bkz. kütüphane belgesi (`lib.rs`).
#[tokio::main]
async fn main() -> std::io::Result<()> {
    // Yan etkisiz: hiçbir dosya okunmaz/yazılmaz, port açılmaz.
    if std::env::args().any(|a| a == "--help" || a == "-h") {
        println!("{USAGE}");
        return Ok(());
    }
    if std::env::args().any(|a| a == "--version" || a == "-V") {
        println!("copsd {}", copsd::GIT_SHA);
        return Ok(());
    }
    copsd::run().await
}

const USAGE: &str = "copsd: claudeops ön sunucusu
  --listen ADRES (127.0.0.1:8765)   --upstream ADRES (127.0.0.1:28765)
  --secret-file --token-file --state-dir --mounts-file --db --metrics-db --instances YOL
  --force-proxy-file YOL (SIGHUP ile yeniden okunur)
  --dist DİZİN (statik dosyalar)    --once    -h, --help    -V, --version";
