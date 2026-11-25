//! copsd ikilisi: bkz. kütüphane belgesi (`lib.rs`).
#[tokio::main]
async fn main() -> std::io::Result<()> {
    copsd::run().await
}
