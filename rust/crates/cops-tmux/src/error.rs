use std::fmt;

#[derive(Debug)]
pub enum TmuxError {
    /// tmux süreci başlatılamadı ya da borularında G/Ç hatası.
    Io(std::io::Error),
    /// tmux süre sınırında bitmedi (süreç öldürüldü).
    Timeout,
    /// tmux sıfırdan farklı kodla döndü (oturum yok, sunucu yok, geçersiz argüman).
    Failed { code: Option<i32>, stderr: String },
    /// Çıktı UTF-8 değil ya da beklenen biçimde değil.
    BadOutput,
    /// Argüman sınır dışı ya da izinli listede değil.
    BadArgument(&'static str),
    /// Pane gizli girdi (parola) bekliyor; [`crate::MaskGuard::RefuseMasked`] gönderimi engelledi.
    Masked,
}

impl fmt::Display for TmuxError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(e) => write!(f, "tmux çalıştırılamadı: {e}"),
            Self::Timeout => f.write_str("tmux zaman aşımı"),
            Self::Failed { code, stderr } => {
                write!(f, "tmux hata kodu {code:?}: {}", stderr.trim())
            }
            Self::BadOutput => f.write_str("tmux çıktısı okunamadı"),
            Self::BadArgument(what) => write!(f, "geçersiz argüman: {what}"),
            Self::Masked => f.write_str("pane gizli girdi bekliyor"),
        }
    }
}

impl std::error::Error for TmuxError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io(e) => Some(e),
            _ => None,
        }
    }
}

impl From<std::io::Error> for TmuxError {
    fn from(e: std::io::Error) -> Self {
        Self::Io(e)
    }
}
