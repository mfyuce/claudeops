//! Hata tipi: Python'un istisna fırlattığı her yerde `Err` döner (sessiz düzeltme yok).
use std::fmt;

#[derive(Debug)]
pub enum Error {
    /// Python `ValueError`/`TypeError`/`KeyError`/`AttributeError` karşılığı (bozuk kayıt, geçersiz girdi).
    Value(String),
    Io(std::io::Error),
    /// Durum deposu (`cops-state`) yazımı başarısız.
    State(String),
    /// `StoreCorrupt`: depo bozuk, yazım reddedildi.
    StoreCorrupt(String),
    /// `LockTimeout`: kilit alınamadı, yazım yapılmadı.
    LockTimeout(String),
}

pub type Result<T> = std::result::Result<T, Error>;

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Value(s) => write!(f, "{s}"),
            Error::Io(e) => write!(f, "{e}"),
            Error::State(s) => write!(f, "{s}"),
            Error::StoreCorrupt(s) => write!(f, "bozuk depo, yazım reddedildi: {s}"),
            Error::LockTimeout(s) => write!(f, "could not lock {s}"),
        }
    }
}
impl std::error::Error for Error {}
impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::Io(e)
    }
}
