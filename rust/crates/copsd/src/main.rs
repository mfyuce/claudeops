//! copsd ikilisi: bkz. kütüphane belgesi (`lib.rs`).
fn main() -> std::io::Result<()> {
    // Yan etkisiz: hiçbir dosya okunmaz/yazılmaz, port açılmaz.
    if std::env::args().any(|a| a == "--help" || a == "-h") {
        println!("{USAGE}");
        return Ok(());
    }
    if std::env::args().any(|a| a == "--version" || a == "-V") {
        println!("copsd {}", copsd::GIT_SHA);
        return Ok(());
    }
    // P2-2: güvenilmeyen PATH girdileri (var olmayan /tmp dizini vb.) atılır; tokio iş parçacıklarından ÖNCE (tek iş parçacığı)
    let dropped = cops_state::paths::secure_path_environ();
    if !dropped.is_empty() {
        eprintln!("copsd: PATH'ten güvenilmeyen girdiler atıldı: {dropped:?}");
    }
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?
        .block_on(copsd::run())
}

const USAGE: &str = "copsd: claudeops ön sunucusu
  --listen ADRES (127.0.0.1:8765)   --upstream ADRES (127.0.0.1:28765)
  --secret-file --token-file --state-dir --mounts-file --db --metrics-db --instances YOL
  --force-proxy-file YOL (SIGHUP ile yeniden okunur)   --tmux-socket AD (cops; yalnız yalıtılmış deneme)
  --dist DİZİN (statik dosyalar)    --once    -h, --help    -V, --version";
