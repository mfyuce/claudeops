//! H1 (ders 3 madde 9): çok sayıda kapanan/reddedilen/zaman aşımına uğrayan bağlantıdan sonra süreçte açık tanıtıcı birikmez
//! (`/proc/self/fd`). Ayrı test ikilisi: aynı süreçte koşan başka test sayımı bozmasın.
use cops_proxy::Proxy;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

fn open_fds() -> usize {
    std::fs::read_dir("/proc/self/fd").unwrap().count()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn no_fd_leak_after_many_connections() {
    // Upstream: bağlantıyı kabul edip hemen 200 döner.
    let ln = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let up = ln.local_addr().unwrap();
    tokio::spawn(async move {
        loop {
            let (mut c, _) = ln.accept().await.unwrap();
            tokio::spawn(async move {
                let mut b = [0u8; 4096];
                let _ = c.read(&mut b).await;
                let _ = c
                    .write_all(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok",
                    )
                    .await;
            });
        }
    });
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = l.local_addr().unwrap();
    tokio::spawn(cops_proxy::serve_on_with(
        l,
        Proxy::with_secret(up, "onkapi"),
        Duration::from_millis(200),
    ));
    let round = |i: usize| async move {
        let mut s = TcpStream::connect(addr).await.unwrap();
        let req: &[u8] = match i % 4 {
            0 => b"GET /api/x HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n",
            1 => b"POST /api/_internal/authz HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}",
            2 => b"GET /api/x HTTP/1.1\r\nHost: x\r\n", // yarım başlık: süre sınırı keser
            _ => b"POST /api/x HTTP/1.1\r\nContent-Length: -1\r\n\r\n",
        };
        let _ = s.write_all(req).await;
        let mut out = Vec::new();
        let _ = tokio::time::timeout(Duration::from_secs(3), s.read_to_end(&mut out)).await;
    };
    for i in 0..8 {
        round(i).await;
    }
    tokio::time::sleep(Duration::from_millis(300)).await;
    let before = open_fds();
    for chunk in 0..10 {
        let tasks: Vec<_> = (0..20)
            .map(|i| tokio::spawn(round(chunk * 20 + i)))
            .collect();
        for t in tasks {
            t.await.unwrap();
        }
    }
    tokio::time::sleep(Duration::from_millis(500)).await;
    let after = open_fds();
    assert!(
        after <= before + 4,
        "tanıtıcı sızıntısı: önce {before}, sonra {after}"
    );
}
