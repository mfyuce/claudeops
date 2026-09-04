// screenshare — minimal local X11 screen-capture -> WebSocket (binary JPEG
// frames) daemon for claudeops' web panel "Uzak Masaüstü" (remote desktop)
// tab. View-only v1 (2026-09-04): captures the whole root window (combined
// virtual screen across monitors) at a fixed interval, streams JPEG frames
// over a plain WebSocket. No auth here by design — this binds to 127.0.0.1
// ONLY and is spawned/killed by `py/cops web` on demand; the EXISTING
// token-gated HTTP server is the only thing that can reach it (proxies the
// WS connection after its own `?token=` check already passed) — see
// TODO.md's "Uzak Masaüstü" entry for the full architecture/why.
//
// Deliberately NOT interactive yet (no mouse/keyboard injection) — that's
// a separate, higher-stakes fast-follow (this same x11rb dependency already
// has the `xtest` feature enabled for exactly that, unused for now).
use std::env;
use std::io::Cursor;
use std::net::{TcpListener, TcpStream};
use std::time::{Duration, Instant};

use image::codecs::jpeg::JpegEncoder;
use image::{ExtendedColorType, ImageEncoder};
use tungstenite::{Message, WebSocket};
use x11rb::connection::Connection;
use x11rb::protocol::xproto::{ConnectionExt as _, ImageFormat};

const DEFAULT_PORT: u16 = 8877;
const FRAME_INTERVAL: Duration = Duration::from_millis(500); // ~2 fps, plenty for a "see what's happening" viewer
const JPEG_QUALITY: u8 = 70;

struct X11Capture {
    conn: x11rb::rust_connection::RustConnection,
    root: u32,
    width: u16,
    height: u16,
}

impl X11Capture {
    fn connect() -> Result<Self, Box<dyn std::error::Error>> {
        let (conn, screen_num) = x11rb::connect(None)?;
        let screen = &conn.setup().roots[screen_num];
        Ok(Self { root: screen.root, width: screen.width_in_pixels, height: screen.height_in_pixels, conn })
    }
}

fn capture_rgb(x11: &X11Capture) -> Result<(u32, u32, Vec<u8>), Box<dyn std::error::Error>> {
    let (root, width, height) = (x11.root, x11.width, x11.height);
    let reply = x11
        .conn
        .get_image(ImageFormat::Z_PIXMAP, root, 0, 0, width, height, !0)?
        .reply()?;

    // See `screenshare`'s POC commit: this server's 32bpp visual is
    // BGRX (byte order confirmed live via a saved screenshot, not assumed) —
    // if this ever runs on a differently-configured X server, a garbled/
    // color-swapped stream is the symptom to watch for.
    let mut rgb = Vec::with_capacity(width as usize * height as usize * 3);
    for px in reply.data.chunks_exact(4) {
        rgb.push(px[2]); // R
        rgb.push(px[1]); // G
        rgb.push(px[0]); // B
    }
    Ok((width as u32, height as u32, rgb))
}

fn encode_jpeg(width: u32, height: u32, rgb: &[u8]) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut buf = Vec::new();
    JpegEncoder::new_with_quality(Cursor::new(&mut buf), JPEG_QUALITY)
        .write_image(rgb, width, height, ExtendedColorType::Rgb8)?;
    Ok(buf)
}

fn serve_client(stream: TcpStream) {
    let peer = stream.peer_addr().map(|a| a.to_string()).unwrap_or_default();
    let mut ws: WebSocket<TcpStream> = match tungstenite::accept(stream) {
        Ok(ws) => ws,
        Err(e) => {
            eprintln!("[screenshare] handshake failed ({peer}): {e}");
            return;
        }
    };
    println!("[screenshare] client connected: {peer}");
    let x11 = match X11Capture::connect() {
        Ok(x) => x,
        Err(e) => {
            eprintln!("[screenshare] X11 connect failed: {e}");
            return;
        }
    };
    loop {
        let started = Instant::now();
        let frame = match capture_rgb(&x11).and_then(|(w, h, rgb)| encode_jpeg(w, h, &rgb)) {
            Ok(f) => f,
            Err(e) => {
                eprintln!("[screenshare] capture/encode failed: {e}");
                break;
            }
        };
        if let Err(e) = ws.send(Message::Binary(frame.into())) {
            println!("[screenshare] client disconnected ({peer}): {e}");
            break;
        }
        let elapsed = started.elapsed();
        if elapsed < FRAME_INTERVAL {
            std::thread::sleep(FRAME_INTERVAL - elapsed);
        }
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let port: u16 = env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(DEFAULT_PORT);
    let addr = format!("127.0.0.1:{port}");
    let listener = TcpListener::bind(&addr)?;
    println!("[screenshare] listening on ws://{addr} (localhost-only, no auth by design)");

    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                std::thread::spawn(move || serve_client(stream));
            }
            Err(e) => eprintln!("[screenshare] accept error: {e}"),
        }
    }
    Ok(())
}
