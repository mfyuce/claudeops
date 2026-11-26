//! `cops list` / `ls` arayüzü (ŞİMDİLİK yalnız tipler; komut Python'a devredilir).
//!
//! Hedef: `cops-procscan` (dal `rs/proc`, `list::render` + `discovery::find_sessions`) birleşince [`SessionSource`] onunla
//! uygulanır ve [`backend`] `Some` döner. O crate'e bağımlılık BU izde eklenmedi (izin verilen yollar dışında, birleştirme
//! sırası cops'ta). Alanlar Python `commands/ls.py` `run` ve procscan `list::Row` ile aynı.

/// `list` argümanları (Python `ls.register`).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ListArgs {
    /// `--no-cpu`
    pub no_cpu: bool,
    /// `--base`
    pub base: Option<String>,
    /// `--json`
    pub json: bool,
}

/// Tablo/JSON satırı (`ls.py` JSON alanları).
#[derive(Debug, Clone, PartialEq)]
pub struct SessionRow {
    /// oturum adı
    pub name: String,
    /// süreç
    pub pid: u32,
    /// `model_short`
    pub model: String,
    /// CPU yüzdesi
    pub cpu: f64,
    /// `fresh` | `resume`
    pub kind: String,
    /// çalışma dizini
    pub cwd: String,
}

/// Tarama hatası.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScanError(pub String);

/// Oturum kaynağı (procscan bağlanınca).
pub trait SessionSource {
    /// Kendi uid'imizin oturumları (CPU ölçümü isteğe bağlı).
    fn sessions(&self, measure_cpu: bool) -> Result<Vec<SessionRow>, ScanError>;
    /// Çıktı metni (`ls.py` ile bayt bayt aynı).
    fn render(&self, rows: Vec<SessionRow>, args: &ListArgs) -> String;
}

/// Bugün Rust uygulaması yok: `None` = Python'a devret.
pub fn backend() -> Option<&'static dyn SessionSource> {
    None
}

#[cfg(test)]
mod tests {
    #[test]
    fn list_is_delegated_until_procscan_lands() {
        assert!(super::backend().is_none());
    }
}
