//! Yeni CLI penceresini doğrudan hedef masaüstünde açtırma (Python `startup_desktop.py`, TBD#409), saf yarı: hedef seçimi,
//! X11 başlangıç bildirimi metni ve 20 baytlık parçaları, ortam kurulumu. `wmctrl` ve libX11 [`DesktopIo`] arkasında
//! (gerçek: [`crate::real::startup_desktop::X11Desktop`]).
//!
//! Özellik pencere açılışını ASLA engellemez: her başarısızlıkta ortam aynen döner.

use crate::pyfmt::py_int;
use crate::settings::Settings;
use serde_json::Value;

pub const DEFAULT_DESKTOP: i64 = 1;
/// Tanı günlüğündeki hata metninin üst sınırı (karakter).
const ERROR_CHARS: usize = 200;

/// X sunucusu ve saat sınırı. `Err` = beklenmeyen hata (günlüğe yazılır; Python'da yakalanan istisna).
pub trait DesktopIo: Send + Sync {
    /// `desktop_count`: `wmctrl -d`nin boş olmayan satır sayısı; okunamazsa `Ok(None)`.
    fn desktop_count(&self, display: &str) -> Result<Option<usize>, String>;
    /// `new_startup_id()` (süreç kimliği + saat).
    fn new_startup_id(&self) -> String;
    /// `send_startup_x11`: bildirimi kök pencereye gönderir; gönderilemezse `Ok(false)`.
    fn send(&self, display: &str, msg: &[u8]) -> Result<bool, String>;
}

/// [`startup_env`] sonucu.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StartupEnv {
    /// Pencereye verilecek ortam.
    pub env: Vec<(String, String)>,
    /// `startup_desktop_error` günlüğüne yazılacak metin.
    pub error: Option<String>,
}

impl StartupEnv {
    pub fn unchanged(env: &[(String, String)]) -> StartupEnv {
        StartupEnv {
            env: env.to_vec(),
            error: None,
        }
    }
}

/// `resolve_desktop`: hedef yoksa 1'e, o da yoksa 0'a düşer; `None` = kapalı ya da uygulanamaz.
pub fn resolve_desktop(want: Option<i64>, count: Option<usize>) -> Option<i64> {
    let (want, count) = (want?, count?);
    let count = i64::try_from(count).unwrap_or(i64::MAX);
    if count <= 0 || want < 0 {
        return None;
    }
    if want < count {
        return Some(want);
    }
    Some(i64::from(count > 1))
}

/// `wanted_desktop`: `settings.spawn_desktop` (yoksa ve sayı değilse 1; bool ve negatif = kapalı).
pub fn wanted_desktop(settings: &Settings) -> Option<i64> {
    let want = match settings.get("spawn_desktop") {
        None => DEFAULT_DESKTOP,
        Some(Value::Bool(_)) => return None,
        Some(v) => py_int(v).unwrap_or(DEFAULT_DESKTOP),
    };
    (want >= 0).then_some(want)
}

fn quote(v: &str) -> String {
    format!("\"{}\"", v.replace('\\', "\\\\").replace('"', "\\\""))
}

/// `build_message`: `new: ID=... NAME=... SCREEN=0 DESKTOP=N\0` (UTF-8).
pub fn build_message(sid: &str, name: &str, desktop: i64) -> Vec<u8> {
    format!(
        "new: ID={} NAME={} SCREEN=0 DESKTOP={desktop}\0",
        quote(sid),
        quote(name)
    )
    .into_bytes()
}

/// `chunks`: 20 baytlık ClientMessage parçaları (sonuncusu NUL ile doldurulur).
pub fn chunks(msg: &[u8]) -> Vec<[u8; 20]> {
    msg.chunks(20)
        .map(|part| {
            let mut out = [0u8; 20];
            out[..part.len()].copy_from_slice(part);
            out
        })
        .collect()
}

/// `new_startup_id`: `claudeops-<pid>-<ms>_TIME<ms'nin alt 32 biti>`.
pub fn startup_id(pid: u32, millis: u128) -> String {
    format!("claudeops-{pid}-{millis}_TIME{}", millis & 0xFFFF_FFFF)
}

/// `startup_env`: `env` + `DESKTOP_STARTUP_ID` (ebeveynden gelen varsa yerinde değişir). Uygulanamazsa `env` aynen döner.
pub fn startup_env(
    settings: &Settings,
    env: &[(String, String)],
    name: &str,
    io: &dyn DesktopIo,
) -> StartupEnv {
    let attempt = || -> Result<Option<String>, String> {
        let want = wanted_desktop(settings);
        let display = env
            .iter()
            .find(|(k, _)| k == "DISPLAY")
            .map_or("", |(_, v)| v.as_str());
        if want.is_none() || display.is_empty() {
            return Ok(None);
        }
        let Some(desktop) = resolve_desktop(want, io.desktop_count(display)?) else {
            return Ok(None);
        };
        let sid = io.new_startup_id();
        let sent = io.send(display, &build_message(&sid, name, desktop))?;
        Ok(sent.then_some(sid))
    };
    let mut out = StartupEnv::unchanged(env);
    match attempt() {
        Ok(Some(sid)) => match out.env.iter_mut().find(|(k, _)| k == "DESKTOP_STARTUP_ID") {
            Some(slot) => slot.1 = sid,
            None => out.env.push(("DESKTOP_STARTUP_ID".into(), sid)),
        },
        Ok(None) => {}
        Err(e) => out.error = Some(e.chars().take(ERROR_CHARS).collect()),
    }
    out
}
