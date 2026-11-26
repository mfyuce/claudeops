//! `ucli_agents.py` token yarısı: oturuma özel ajan token'ı (0600 dosya) ve kayıt defteri (yalnız SHA-256 özeti).
//!
//! Token hiçbir dönüşe, hata metnine, `Debug`a ya da günlüğe girmez; yalnız dosyaya yazılır.
//!
//! Python'dan fark: kayıt defteri oku-değiştir-yazı Python'da yalnız süreç İÇİ kilitlidir; burada ek olarak
//! `ucli_agents.json.lock` (`flock`) tutulur (Rust süreçleri arasında kayıp yok; Python bu kilidi ALMAZ).

use crate::probe::Paths;
use crate::pyjson::Py;
use crate::real::lock::{FileLock, LOCK_TIMEOUT};
use crate::real::{docs::DOC_MAX_BYTES, effects, fsio, oserr};
use crate::ucli::is_child_name;
use regex::Regex;
use sha2::{Digest, Sha256};
use std::fs::{self, Permissions};
use std::io::{self, Read};
use std::os::unix::fs::PermissionsExt;
use std::sync::LazyLock;
use std::time::{SystemTime, UNIX_EPOCH};

/// `_SAFE_NAME_RE` (Python `$`: sondaki tek satır sonu kabul edilir).
static SAFE_NAME: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\n?$").expect("sabit desen"));

/// Token baytı sayısı (`secrets.token_hex(32)`).
const TOKEN_BYTES: usize = 32;
/// `parent_for_token`ın baktığı en uzun aday (karakter).
const TOKEN_MAX_CHARS: usize = 256;

/// Rastgele bayt ve saat kaynağı (testte sabitlenir).
#[derive(Debug, Clone, Copy)]
pub struct Sources {
    pub entropy: fn(&mut [u8]) -> io::Result<()>,
    /// `time.time()`.
    pub now: fn() -> f64,
}

fn urandom(buf: &mut [u8]) -> io::Result<()> {
    fs::File::open("/dev/urandom")?.read_exact(buf)
}

fn unix_now() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map_or(0.0, |d| d.as_secs_f64())
}

impl Default for Sources {
    fn default() -> Self {
        Sources { entropy: urandom, now: unix_now }
    }
}

#[derive(Debug, Clone)]
pub struct AgentRegistry {
    state_file: String,
    token_dir: String,
    sources: Sources,
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn digest(token: &str) -> String {
    hex(&Sha256::digest(token.as_bytes()))
}

/// Sabit zamanlı eşitlik (`secrets.compare_digest`; uzunluk sızabilir).
fn same_digest(a: &str, b: &str) -> bool {
    a.len() == b.len() && a.bytes().zip(b.bytes()).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

fn entry<'a>(object: &'a mut Vec<(String, Py)>, key: &str, empty: Py) -> &'a mut Py {
    let at = match object.iter().position(|(k, _)| k == key) {
        Some(i) => i,
        None => {
            object.push((key.to_string(), empty));
            object.len() - 1
        }
    };
    &mut object[at].1
}

fn object_mut(v: &mut Py) -> Option<&mut Vec<(String, Py)>> {
    match v {
        Py::Object(o) => Some(o),
        _ => None,
    }
}

impl AgentRegistry {
    pub fn new(paths: &Paths) -> AgentRegistry {
        AgentRegistry {
            state_file: paths.ucli_agents_json(),
            token_dir: paths.ucli_agent_token_dir(),
            sources: Sources::default(),
        }
    }

    pub fn with_sources(mut self, sources: Sources) -> AgentRegistry {
        self.sources = sources;
        self
    }

    pub fn token_file(&self, session: &str) -> String {
        format!("{}/{session}", self.token_dir)
    }

    fn lock(&self) -> io::Result<FileLock> {
        FileLock::acquire(&self.state_file, "/", LOCK_TIMEOUT)
    }

    /// `_load`: yok/bozuk/nesne olmayan belge boş defter; `parents`/`children` nesne değilse boşaltılır.
    fn load(&self) -> Vec<(String, Py)> {
        let parsed = fsio::read_bytes(&self.state_file, DOC_MAX_BYTES)
            .and_then(|b| Py::parse(std::str::from_utf8(&b).ok()?));
        let mut data = match parsed {
            Some(Py::Object(o)) => o,
            _ => Vec::new(),
        };
        for key in ["parents", "children"] {
            let slot = entry(&mut data, key, Py::Object(Vec::new()));
            if !slot.is_object() {
                *slot = Py::Object(Vec::new());
            }
        }
        data
    }

    /// `_save`: dizin 0700 (yoksa), dosya 0600 atomik.
    fn save(&self, data: Vec<(String, Py)>) -> io::Result<()> {
        if let Some((dir, _)) = self.state_file.rsplit_once('/') {
            effects::makedirs(dir, 0o700).map_err(|(_, e)| e)?;
        }
        effects::atomic_write_text(&self.state_file, &Py::Object(data).dumps_pretty(), Some(0o600))
    }

    fn write_token_file(&self, session: &str, token: &str) -> io::Result<String> {
        effects::makedirs(&self.token_dir, 0o700).map_err(|(_, e)| e)?;
        fs::set_permissions(&self.token_dir, Permissions::from_mode(0o700))?;
        let path = self.token_file(session);
        effects::atomic_write_text(&path, token, Some(0o600))?;
        Ok(path)
    }

    /// `issue_token`: yeni token (eskisi geçersizleşir). Dönen DOSYA YOLU. Hata: Python istisna SINIF ADI
    /// (`ValueError` çocuk/güvensiz ad; `PermissionError` vb.).
    pub fn issue_token(&self, session: &str) -> Result<String, String> {
        if is_child_name(session) {
            return Err("ValueError".into());
        }
        let os = |e: io::Error| oserr::class_name(&e).to_string();
        let mut raw = [0u8; TOKEN_BYTES];
        (self.sources.entropy)(&mut raw).map_err(os)?;
        let token = hex(&raw);
        // dosya adı olacak: yan etkiden (kilit dosyası, dizin) ÖNCE denetlenir
        if !SAFE_NAME.is_match(session) {
            return Err("ValueError".into());
        }
        // dosya + özet TEK kilitte: eşzamanlı çağrılarda ayrışmasın
        let _lock = self.lock().map_err(os)?;
        let path = self.write_token_file(session, &token).map_err(os)?;
        let mut data = self.load();
        let parents = object_mut(entry(&mut data, "parents", Py::Object(Vec::new())));
        let record = parents.map(|p| entry(p, session, Py::Object(Vec::new())));
        // nesne olmayan eski kayıt: Python `AttributeError` (token dosyası yazılmış kalır)
        let Some(record) = record.and_then(object_mut) else { return Err("AttributeError".into()) };
        *entry(record, "sha256", Py::Null) = Py::Str(digest(&token));
        *entry(record, "issued", Py::Null) = Py::Float((self.sources.now)());
        entry(record, "seq", Py::Int(0));
        self.save(data).map_err(os)?;
        Ok(path)
    }

    /// Bearer token -> üst oturum adı; geçerli değilse None. Bütün kayıtlar karşılaştırılır.
    pub fn parent_for_token(&self, token: &str) -> Option<String> {
        if token.is_empty() || token.chars().count() > TOKEN_MAX_CHARS {
            return None;
        }
        let wanted = digest(token);
        let data = self.load();
        let Some((_, Py::Object(parents))) = data.iter().find(|(k, _)| k == "parents") else { return None };
        let mut found = None;
        for (name, record) in parents {
            if record.get("sha256").and_then(Py::as_str).is_some_and(|d| same_digest(&wanted, d)) {
                found = Some(name.clone());
            }
        }
        found
    }

    /// Üst oturum kapandı: token dosyası silinir (güvensiz adda dosyaya dokunulmaz), özet düşer.
    pub fn revoke_parent(&self, session: &str) -> Result<(), String> {
        let os = |e: io::Error| oserr::class_name(&e).to_string();
        let _lock = self.lock().map_err(os)?;
        if SAFE_NAME.is_match(session) {
            let _ = fs::remove_file(self.token_file(session));
        }
        let mut data = self.load();
        let record = object_mut(entry(&mut data, "parents", Py::Object(Vec::new())))
            .and_then(|p| p.iter_mut().find(|(k, _)| k == session))
            .and_then(|(_, v)| object_mut(v));
        let Some(record) = record else { return Ok(()) };
        let before = record.len();
        record.retain(|(k, _)| k != "sha256");
        if record.len() != before {
            self.save(data).map_err(os)?;
        }
        Ok(())
    }
}
