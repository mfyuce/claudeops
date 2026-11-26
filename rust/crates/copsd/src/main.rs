//! copsd ikilisi: bkz. kütüphane belgesi (`lib.rs`).
#[tokio::main]
async fn main() -> std::io::Result<()> {
    if std::env::args().any(|a| a == "--help" || a == "-h") {
        println!("{USAGE}");
        return Ok(());
    }
    copsd::run().await
}

const USAGE: &str = "copsd: claudeops ön sunucusu
  --listen ADRES (127.0.0.1:8765)   --upstream ADRES (127.0.0.1:18765)
  --secret-file --token-file --state-dir --mounts-file --db --metrics-db --instances YOL
  --dist DİZİN (statik dosyalar)    --once    -h, --help";
