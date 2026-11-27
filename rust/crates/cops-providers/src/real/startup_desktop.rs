//! [`DesktopIo`]nun gerçek uygulayıcısı: `wmctrl -d` ve libX11 (`dlopen`; Python `ctypes` gibi derleme bağımlılığı yok,
//! kitaplık bulunamazsa özellik kapalı).

use crate::real::process::{self, Capture, Spec};
use crate::real::Env;
use crate::startup_desktop::{chunks, startup_id, DesktopIo};
use std::ffi::{c_char, c_int, c_long, c_uint, c_ulong, c_void, CStr, CString};
use std::sync::{Mutex, PoisonError};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const WMCTRL_TIMEOUT: Duration = Duration::from_secs(3);
/// `wmctrl -d` çıktısının üst sınırı.
const WMCTRL_MAX_BYTES: u64 = 1 << 20;
const CLIENT_MESSAGE: c_int = 33;
const PROPERTY_CHANGE_MASK: c_long = 1 << 22;
const X11_LIBRARY: &CStr = c"libX11.so.6";

#[derive(Debug, Clone)]
pub struct X11Desktop {
    /// Çağıran sürecin ortamı (`wmctrl` bununla ve verilen `DISPLAY` ile koşar).
    env: Env,
}

impl X11Desktop {
    pub fn new(env: Env) -> X11Desktop {
        X11Desktop { env }
    }
}

impl DesktopIo for X11Desktop {
    fn desktop_count(&self, display: &str) -> Result<Option<usize>, String> {
        let env = self.env.with_var("DISPLAY", display);
        let argv = ["wmctrl".to_string(), "-d".to_string()];
        let Ok(out) = process::run(&Spec {
            argv: &argv,
            cwd: None,
            env: &env,
            timeout: WMCTRL_TIMEOUT,
            stdout: Capture::Bounded(WMCTRL_MAX_BYTES),
            stderr: Capture::Discard,
        }) else {
            return Ok(None);
        };
        if out.code != 0 {
            return Ok(None);
        }
        let text = String::from_utf8(out.stdout).map_err(|e| e.to_string())?;
        let rows = crate::pyfmt::splitlines(&text)
            .into_iter()
            .filter(|l| !crate::pyfmt::strip(l).is_empty())
            .count();
        Ok((rows > 0).then_some(rows))
    }

    fn new_startup_id(&self) -> String {
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |d| d.as_millis());
        startup_id(std::process::id(), millis)
    }

    fn send(&self, display: &str, msg: &[u8]) -> Result<bool, String> {
        let display = CString::new(display).map_err(|e| e.to_string())?;
        send_startup_x11(&display, msg)
    }
}

/// Xlib `XClientMessageEvent.data`: `union { char b[20]; short s[10]; long l[5]; }`. `long` hizalaması verinin konumunu
/// belirler (yalnız `char[20]` yazılırsa 64 bitte 4 bayt kayar ve mesaj bozulur).
#[repr(C)]
#[derive(Clone, Copy)]
union ClientData {
    b: [u8; 20],
    l: [c_long; 5],
}

#[repr(C)]
#[derive(Clone, Copy)]
struct ClientMessageEvent {
    kind: c_int,
    serial: c_ulong,
    send_event: c_int,
    display: *mut c_void,
    window: c_ulong,
    message_type: c_ulong,
    format: c_int,
    data: ClientData,
}

/// Xlib `XEvent` (`long pad[24]` birliği).
#[repr(C)]
union Event {
    client: ClientMessageEvent,
    pad: [c_long; 24],
}

type OpenDisplay = unsafe extern "C" fn(*const c_char) -> *mut c_void;
type DefaultRootWindow = unsafe extern "C" fn(*mut c_void) -> c_ulong;
type CreateSimpleWindow = unsafe extern "C" fn(
    *mut c_void,
    c_ulong,
    c_int,
    c_int,
    c_uint,
    c_uint,
    c_uint,
    c_ulong,
    c_ulong,
) -> c_ulong;
type InternAtom = unsafe extern "C" fn(*mut c_void, *const c_char, c_int) -> c_ulong;
type SendEvent = unsafe extern "C" fn(*mut c_void, c_ulong, c_int, c_long, *mut Event) -> c_int;
type Sync_ = unsafe extern "C" fn(*mut c_void, c_int) -> c_int;
type DestroyWindow = unsafe extern "C" fn(*mut c_void, c_ulong) -> c_int;
type CloseDisplay = unsafe extern "C" fn(*mut c_void) -> c_int;

#[derive(Clone, Copy)]
struct Xlib {
    open_display: OpenDisplay,
    default_root_window: DefaultRootWindow,
    create_simple_window: CreateSimpleWindow,
    intern_atom: InternAtom,
    send_event: SendEvent,
    sync: Sync_,
    destroy_window: DestroyWindow,
    close_display: CloseDisplay,
}

/// `name` sembolünü `T` işlev işaretçisi olarak alır.
///
/// # Safety
/// `handle` geçerli bir `dlopen` tanıtıcısı olmalı ve `T` sembolün gerçek C imzasında bir işlev işaretçisi olmalı.
unsafe fn symbol<T: Copy>(handle: *mut c_void, name: &CStr) -> Result<T, String> {
    // SAFETY: tanıtıcı çağırandan geçerli; ad NUL ile biter.
    let p = unsafe { libc::dlsym(handle, name.as_ptr()) };
    if p.is_null() || std::mem::size_of::<T>() != std::mem::size_of::<*mut c_void>() {
        return Err(format!("libX11: {} yok", name.to_string_lossy()));
    }
    // SAFETY: boyut eşit ve boş değil; `T`nin imzası çağıranın sözleşmesi.
    Ok(unsafe { std::mem::transmute_copy::<*mut c_void, T>(&p) })
}

/// Kitaplığı açar; yoksa `Ok(None)`. Tanıtıcı süreç boyunca açık kalır (`ctypes.CDLL` gibi).
fn load() -> Result<Option<Xlib>, String> {
    // SAFETY: sabit, NUL ile biten ad; sistem kitaplığı yüklenir.
    let h = unsafe { libc::dlopen(X11_LIBRARY.as_ptr(), libc::RTLD_NOW | libc::RTLD_LOCAL) };
    if h.is_null() {
        return Ok(None);
    }
    // SAFETY: `h` geçerli; her tür Xlib başlığındaki imzayla yazıldı.
    unsafe {
        Ok(Some(Xlib {
            open_display: symbol(h, c"XOpenDisplay")?,
            default_root_window: symbol(h, c"XDefaultRootWindow")?,
            create_simple_window: symbol(h, c"XCreateSimpleWindow")?,
            intern_atom: symbol(h, c"XInternAtom")?,
            send_event: symbol(h, c"XSendEvent")?,
            sync: symbol(h, c"XSync")?,
            destroy_window: symbol(h, c"XDestroyWindow")?,
            close_display: symbol(h, c"XCloseDisplay")?,
        }))
    }
}

/// Başlangıç bildirimini kök pencereye gönderir; kitaplık ya da ekran yoksa `Ok(false)`.
fn send_startup_x11(display: &CStr, msg: &[u8]) -> Result<bool, String> {
    // Xlib'in genel durumuna aynı süreçten tek iş parçacığı girer.
    static SERIAL: Mutex<()> = Mutex::new(());
    let _guard = SERIAL.lock().unwrap_or_else(PoisonError::into_inner);
    let Some(x) = load()? else { return Ok(false) };
    // SAFETY: `display` NUL ile biter; dönen işaretçi boşsa kullanılmaz.
    let d = unsafe { (x.open_display)(display.as_ptr()) };
    if d.is_null() {
        return Ok(false);
    }
    // SAFETY: `d` açık bir ekran; pencere ve atomlar bu bağlantıdan alınır, olay yapısı çağrı boyunca yaşar ve Xlib
    // `XEvent` düzenindedir (bkz. birim testi). Bağlantı sonda bir kez kapatılır.
    unsafe {
        let root = (x.default_root_window)(d);
        let window = (x.create_simple_window)(d, root, -100, -100, 1, 1, 0, 0, 0);
        let begin = (x.intern_atom)(d, c"_NET_STARTUP_INFO_BEGIN".as_ptr(), 0);
        let cont = (x.intern_atom)(d, c"_NET_STARTUP_INFO".as_ptr(), 0);
        for (i, part) in chunks(msg).into_iter().enumerate() {
            let mut event = Event { pad: [0; 24] };
            event.client = ClientMessageEvent {
                kind: CLIENT_MESSAGE,
                serial: 0,
                send_event: 1,
                display: d,
                window,
                message_type: if i == 0 { begin } else { cont },
                format: 8,
                data: ClientData { l: [0; 5] },
            };
            event.client.data.b = part;
            (x.send_event)(d, root, 0, PROPERTY_CHANGE_MASK, &mut event);
        }
        (x.sync)(d, 0);
        (x.destroy_window)(d, window);
        (x.sync)(d, 0);
        (x.close_display)(d);
    }
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 64 bit Xlib: `XClientMessageEvent.data` 56. baytta (`long` hizalı), `XEvent` 192 bayt.
    #[test]
    #[cfg(target_pointer_width = "64")]
    fn client_message_layout_matches_xlib() {
        assert_eq!(std::mem::offset_of!(ClientMessageEvent, data), 56);
        assert_eq!(std::mem::size_of::<Event>(), 192);
    }
}
