//! `force_proxy`: listedeki öneke giren istek, Rust'ta yerel karşılığı olsa bile Python'a aktarılır (uç bazında geri alma;
//! strangler planı §9). Kaynak durum dizinindeki dosya (`front_force_proxy`), SIGHUP ile yeniden okunur (copsd).
//!
//! Dosya: satır başına bir yol öneki; boş ve `#` satırlar atlanır; baştaki `/` eksikse eklenir; `*` hepsi. Eşleşme düz önektir
//! (`/api/files` hem `/api/files/list`i hem `/api/filesx`i tutar: şüphede Python). Enterprise `ent_auth_force_proxy` ile aynı
//! yazım; o dosya yalnız KARARI Python'a verir, bu dosya İSTEĞİN TAMAMINI.

use std::path::{Path, PathBuf};
use std::sync::RwLock;

/// Satır sınırı (fazlası yok sayılır ve günlüğe yazılır).
pub const MAX_ENTRIES: usize = 512;
const MAX_BYTES: u64 = 64 * 1024;

/// Dosya içeriği -> önek listesi.
pub fn parse(text: &str) -> Vec<String> {
    text.trim_start_matches('\u{feff}')
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
        .map(|l| {
            if l == "*" || l.starts_with('/') {
                l.to_string()
            } else {
                format!("/{l}")
            }
        })
        .collect()
}

pub struct ForceProxy {
    path: PathBuf,
    list: RwLock<Vec<String>>,
}

impl ForceProxy {
    /// Dosyayı hemen okur. Dosya VAR ama okunamıyorsa liste `*` (her şey Python'a): istenen geri alma sessizce kaybolmasın.
    pub fn load(path: impl Into<PathBuf>) -> ForceProxy {
        let f = ForceProxy {
            path: path.into(),
            list: RwLock::new(Vec::new()),
        };
        if let Err(e) = f.reload() {
            eprintln!(
                "copsd: force_proxy okunamadı, TÜM istekler Python'a: {}: {e}",
                f.path.display()
            );
            f.set(vec!["*".into()]);
        }
        f
    }

    /// Yeniden okur; yeni önek sayısını döner. Dosya yoksa liste boşalır. Okuma hatasında ESKİ liste kalır.
    pub fn reload(&self) -> std::io::Result<usize> {
        let mut list = match read(&self.path) {
            Ok(t) => parse(&t),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Vec::new(),
            Err(e) => return Err(e),
        };
        if list.len() > MAX_ENTRIES {
            // Sessiz kesme geri almayı kaybettirir: sınır aşıldıysa her şey Python'a.
            eprintln!(
                "copsd: force_proxy {} satır (> {MAX_ENTRIES}): TÜM istekler Python'a",
                list.len()
            );
            list = vec!["*".into()];
        }
        let n = list.len();
        self.set(list);
        Ok(n)
    }

    fn set(&self, list: Vec<String>) {
        *self.list.write().unwrap_or_else(|p| p.into_inner()) = list;
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn list(&self) -> Vec<String> {
        self.list.read().unwrap_or_else(|p| p.into_inner()).clone()
    }

    pub fn matches(&self, path: &str) -> bool {
        self.list
            .read()
            .unwrap_or_else(|p| p.into_inner())
            .iter()
            .any(|p| p == "*" || path.starts_with(p.as_str()))
    }
}

/// Yalnız düzenli dosya okunur (FIFO açılışı kilitlemesin), boyut sınırlı.
fn read(path: &Path) -> std::io::Result<String> {
    use std::io::{Error, ErrorKind, Read};
    let meta = std::fs::metadata(path)?;
    if !meta.is_file() || meta.len() > MAX_BYTES {
        return Err(Error::new(
            ErrorKind::InvalidData,
            "düzenli dosya değil ya da çok büyük",
        ));
    }
    let mut s = String::new();
    std::fs::File::open(path)?
        .take(MAX_BYTES)
        .read_to_string(&mut s)?;
    Ok(s)
}
