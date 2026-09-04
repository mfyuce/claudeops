// screenshare — local X11 screen-capture + input-injection <-> WebSocket
// daemon for claudeops' web panel "Uzak Masaüstü" (remote desktop) tab.
//
// v1 (2026-09-04) was view-only. v2 (same day, follow-up request) adds
// mouse/keyboard/touch control via `enigo` — chosen over hand-rolling X11
// XTEST calls ourselves because arbitrary-Unicode keyboard input (this
// project's own language is Turkish: ğ/ü/ş/ı/ö/ç are almost certainly NOT
// in whatever the current X keyboard mapping is) requires temporarily
// remapping an unused keycode, which `enigo` already implements correctly
// on Linux/X11 — reinventing that ourselves was judged not worth the risk
// for a feature this security-sensitive. `enigo` pulls in its own x11rb
// 0.13 (separate from our 0.14, used only for capture) — a little
// redundant but harmless (two crate-version islands, no actual conflict).
//
// Protocol: unchanged for outgoing frames (binary JPEG, one per interval).
// NEW incoming direction: JSON text messages, one input event each (see
// `InputEvent`). The connection is now read+written from a SINGLE thread
// using a short read-timeout on the socket (acts as a poll: "any input
// waiting? handle it; otherwise, is it time for the next frame? send it")
// — deliberately not two threads + a mutex, which would need the reader
// thread to give up the lock while blocked waiting for the next keystroke,
// defeating the point.
//
// Still localhost-only / no auth of its own by design (see `remote_desktop.py`).
use std::env;
use std::io::{Cursor, ErrorKind};
use std::net::{TcpListener, TcpStream};
use std::time::{Duration, Instant};

use enigo::{Axis, Button, Coordinate, Direction, Enigo, Key, Keyboard, Mouse, Settings};
use image::codecs::jpeg::JpegEncoder;
use image::{ExtendedColorType, ImageEncoder};
use serde::Deserialize;
use tungstenite::{Message, WebSocket};
use x11rb::connection::Connection;
use x11rb::protocol::xproto::{ConnectionExt as _, ImageFormat};

const DEFAULT_PORT: u16 = 8877;
const FRAME_INTERVAL: Duration = Duration::from_millis(500); // ~2 fps, plenty for a "see what's happening" viewer
const JPEG_QUALITY: u8 = 70;
// How long a single read-attempt blocks before giving up and checking
// whether it's time to send the next frame. Small enough that frame
// pacing stays close to FRAME_INTERVAL, large enough not to busy-loop.
const READ_POLL_INTERVAL: Duration = Duration::from_millis(50);

#[derive(Deserialize)]
#[serde(tag = "t")]
enum InputEvent {
    #[serde(rename = "move")]
    Move { x: i32, y: i32 },
    #[serde(rename = "down")]
    ButtonDown { b: MouseButton },
    #[serde(rename = "up")]
    ButtonUp { b: MouseButton },
    #[serde(rename = "scroll")]
    Scroll { dx: i32, dy: i32 },
    #[serde(rename = "key")]
    KeyEvent { k: String, a: KeyAction },
    #[serde(rename = "text")]
    Text { s: String },
}

#[derive(Deserialize)]
enum MouseButton {
    #[serde(rename = "left")]
    Left,
    #[serde(rename = "middle")]
    Middle,
    #[serde(rename = "right")]
    Right,
}

#[derive(Deserialize)]
enum KeyAction {
    #[serde(rename = "down")]
    Down,
    #[serde(rename = "up")]
    Up,
    #[serde(rename = "click")]
    Click,
}

impl From<MouseButton> for Button {
    fn from(b: MouseButton) -> Self {
        match b {
            MouseButton::Left => Button::Left,
            MouseButton::Middle => Button::Middle,
            MouseButton::Right => Button::Right,
        }
    }
}

impl From<KeyAction> for Direction {
    fn from(a: KeyAction) -> Self {
        match a {
            KeyAction::Down => Direction::Press,
            KeyAction::Up => Direction::Release,
            KeyAction::Click => Direction::Click,
        }
    }
}

/// Named keys the frontend can send (a deliberately small, explicit allowlist
/// — anything not on this list falls back to `Key::Unicode` of its first
/// char, so a stray/unexpected name never turns into an X11 protocol error,
/// it just does nothing useful rather than crashing the connection).
fn named_key(name: &str) -> Option<Key> {
    Some(match name {
        "Return" | "Enter" => Key::Return,
        "Backspace" => Key::Backspace,
        "Delete" => Key::Delete,
        "Tab" => Key::Tab,
        "Escape" => Key::Escape,
        "Space" => Key::Space,
        "ArrowLeft" => Key::LeftArrow,
        "ArrowRight" => Key::RightArrow,
        "ArrowUp" => Key::UpArrow,
        "ArrowDown" => Key::DownArrow,
        "Home" => Key::Home,
        "End" => Key::End,
        "PageUp" => Key::PageUp,
        "PageDown" => Key::PageDown,
        "Control" => Key::Control,
        "Shift" => Key::Shift,
        "Alt" => Key::Alt,
        "Meta" | "Super" => Key::Meta,
        "CapsLock" => Key::CapsLock,
        "F1" => Key::F1,
        "F2" => Key::F2,
        "F3" => Key::F3,
        "F4" => Key::F4,
        "F5" => Key::F5,
        "F6" => Key::F6,
        "F7" => Key::F7,
        "F8" => Key::F8,
        "F9" => Key::F9,
        "F10" => Key::F10,
        "F11" => Key::F11,
        "F12" => Key::F12,
        _ => return None,
    })
}

fn apply_input_event(enigo: &mut Enigo, event: InputEvent) {
    // Best-effort throughout: an occasional failed injection (e.g. a
    // transient X11 hiccup) should never take down the whole connection —
    // the next event just tries again.
    let _ = match event {
        InputEvent::Move { x, y } => enigo.move_mouse(x, y, Coordinate::Abs),
        InputEvent::ButtonDown { b } => enigo.button(b.into(), Direction::Press),
        InputEvent::ButtonUp { b } => enigo.button(b.into(), Direction::Release),
        InputEvent::Scroll { dx, dy } => {
            if dy != 0 {
                let _ = enigo.scroll(dy, Axis::Vertical);
            }
            if dx != 0 {
                let _ = enigo.scroll(dx, Axis::Horizontal);
            }
            Ok(())
        }
        InputEvent::KeyEvent { k, a } => {
            let key = named_key(&k).unwrap_or_else(|| Key::Unicode(k.chars().next().unwrap_or(' ')));
            enigo.key(key, a.into())
        }
        InputEvent::Text { s } => enigo.text(&s),
    };
}

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

fn is_timeout(err: &tungstenite::Error) -> bool {
    matches!(
        err,
        tungstenite::Error::Io(e) if matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut)
    )
}

fn serve_client(stream: TcpStream) {
    let peer = stream.peer_addr().map(|a| a.to_string()).unwrap_or_default();
    if let Err(e) = stream.set_read_timeout(Some(READ_POLL_INTERVAL)) {
        eprintln!("[screenshare] set_read_timeout failed ({peer}): {e}");
        return;
    }
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
    let mut enigo = match Enigo::new(&Settings::default()) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("[screenshare] enigo init failed (input control disabled for this connection): {e}");
            // Capture-only is still useful — don't drop the connection over this.
            serve_view_only(ws, &x11, &peer);
            return;
        }
    };

    let mut last_frame = Instant::now() - FRAME_INTERVAL; // send the first frame immediately
    loop {
        match ws.read() {
            Ok(Message::Text(text)) => match serde_json::from_str::<InputEvent>(&text) {
                Ok(event) => apply_input_event(&mut enigo, event),
                Err(e) => eprintln!("[screenshare] bad input event ({peer}): {e}"),
            },
            Ok(Message::Close(_)) => {
                println!("[screenshare] client closed ({peer})");
                break;
            }
            Ok(_) => {} // Binary/Ping/Pong/Frame — nothing else expected from the client
            Err(e) if is_timeout(&e) => {} // no input waiting right now, normal
            Err(e) => {
                println!("[screenshare] client disconnected ({peer}): {e}");
                break;
            }
        }

        if last_frame.elapsed() >= FRAME_INTERVAL {
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
            last_frame = Instant::now();
        }
    }
}

/// Fallback used only if `Enigo::new()` itself fails (e.g. some X11 extension
/// genuinely unavailable) — keeps the view working even though control can't.
fn serve_view_only(mut ws: WebSocket<TcpStream>, x11: &X11Capture, peer: &str) {
    loop {
        let started = Instant::now();
        match ws.read() {
            Err(e) if is_timeout(&e) => {}
            Err(e) => {
                println!("[screenshare] client disconnected ({peer}): {e}");
                return;
            }
            Ok(Message::Close(_)) => return,
            Ok(_) => {}
        }
        let frame = match capture_rgb(x11).and_then(|(w, h, rgb)| encode_jpeg(w, h, &rgb)) {
            Ok(f) => f,
            Err(e) => {
                eprintln!("[screenshare] capture/encode failed: {e}");
                return;
            }
        };
        if ws.send(Message::Binary(frame.into())).is_err() {
            return;
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
