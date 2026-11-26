//! claude konuşmasının bulunması (`claude_provider.py`: `jsonl_path_for`, `find_latest_jsonl`, `session_file_sid`,
//! `_jsonl_meta` ailesi, `resolve_resume_id`, `sid_for_stopped_session`).

use crate::live::Live;
use crate::pyfmt::{join_path, parse_int, strip};
use crate::pyjson::Py;
use crate::resume::universal_lines;
use std::collections::{BTreeSet, HashMap};
use std::sync::{Mutex, PoisonError};

/// Kimlik satırlarının arandığı baş satır sayısı.
pub const META_HEAD_LINES: usize = 15;
/// `--resume` seçiminde bakılan en yeni dosya sayısı.
pub const RESUME_SCAN_LIMIT: usize = 25;
/// Bundan küçük dosya, sohbet satırı taşımıyorsa "stub"dır.
pub const STUB_MAX_BYTES: u64 = 64 * 1024;
/// Başlık önbelleğinin girdi sınırı (dolunca boşaltılır).
pub const META_CACHE_MAX: usize = 20_000;
/// Stub taramasının okuma sınırı (yalnız stat boyutu [`STUB_MAX_BYTES`] altındaki dosya taranır; arada büyüyebilir).
const STUB_READ_MAX_BYTES: u64 = 8 * 1024 * 1024;
/// `sessions/<pid>.json` okuma sınırı.
const SESSION_FILE_MAX_BYTES: u64 = 1024 * 1024;

/// Transkriptin başındaki kimlik alanları.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Meta {
    /// İlk `customTitle` (oturumun `-n NAME` adı).
    pub title: Option<String>,
    /// İlk `cwd`.
    pub cwd: Option<String>,
}

/// Dosya imzası `(mtime_ns, boyut)`.
type Signature = (i64, u64);

/// Dosya yolu -> (imza, başlık). Süreç başına TEK örnek tutulur.
#[derive(Debug, Default)]
pub struct MetaCache(Mutex<HashMap<String, (Signature, Meta)>>);

impl MetaCache {
    /// İmza aynıysa kayıt, değilse `load` (kilit okuma sırasında tutulmaz).
    pub fn get(&self, path: &str, sig: Signature, load: impl FnOnce() -> Meta) -> Meta {
        let lock = || self.0.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some((_, meta)) = lock().get(path).filter(|(s, _)| *s == sig) {
            return meta.clone();
        }
        let meta = load();
        let mut map = lock();
        if map.len() >= META_CACHE_MAX {
            map.clear();
        }
        map.insert(path.to_string(), (sig, meta.clone()));
        meta
    }

    pub fn len(&self) -> usize {
        self.0.lock().unwrap_or_else(PoisonError::into_inner).len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

/// `str(Path(dir) / name)`: mutlak ad dizini yok sayar; `//` ve `.` parçaları düşer, `..` kalır.
fn path_join(dir: &str, name: &str) -> String {
    let full = join_path(dir, name);
    let slashes = match full.len() - full.trim_start_matches('/').len() {
        0 => 0,
        2 => 2,
        _ => 1,
    };
    let parts: Vec<&str> = full.split('/').filter(|c| !c.is_empty() && *c != ".").collect();
    format!("{}{}", "/".repeat(slashes), parts.join("/"))
}

/// `Path(name).suffix == ".jsonl"` (adı yalnız `.jsonl` olan gizli dosyanın uzantısı yoktur).
fn has_jsonl_suffix(name: &str) -> bool {
    name.len() > ".jsonl".len() && name.ends_with(".jsonl")
}

/// `Path(name).stem` (`.jsonl` ile biten ad için).
fn stem(name: &str) -> &str {
    if has_jsonl_suffix(name) {
        &name[..name.len() - ".jsonl".len()]
    } else {
        name
    }
}

fn file_name(path: &str) -> &str {
    crate::pyfmt::basename(path)
}

fn json_line(raw: &[u8]) -> Option<Py> {
    Py::parse(&String::from_utf8_lossy(raw)).filter(Py::is_object)
}

impl Live<'_> {
    /// `sid` verildiyse YALNIZ `<sid>.jsonl`; geçersiz (`/`, NUL) ya da dosyası olmayan sid `None` (TBD#365: tahmin ortak
    /// cwd'de kardeş oturumun transkriptini verirdi). Yalnız `sid` hiç yoksa cwd'deki en yeni transkript
    /// ([`Live::find_latest_jsonl`]).
    pub fn jsonl_path_for(&self, cwd: &str, sid: Option<&str>) -> Option<String> {
        if let Some(sid) = sid.filter(|s| !s.is_empty()) {
            if sid.contains(['/', '\0']) {
                return None;
            }
            let path = path_join(&self.probe.claude_project_dir(cwd), &format!("{sid}.jsonl"));
            return self.probe.is_file(&path).then_some(path);
        }
        self.find_latest_jsonl(cwd)
    }

    /// Proje dizinindeki `.jsonl` dosyaları, dizin okuma sırasıyla.
    fn project_jsonls(&self, cwd: &str) -> Vec<String> {
        let dir = self.probe.claude_project_dir(cwd);
        self.probe
            .list_dir(&dir)
            .unwrap_or_default()
            .into_iter()
            .filter(|name| has_jsonl_suffix(name))
            .map(|name| path_join(&dir, &name))
            .filter(|path| self.probe.is_file(path))
            .collect()
    }

    /// cwd'nin en son değiştirilen transkripti.
    pub fn find_latest_jsonl(&self, cwd: &str) -> Option<String> {
        self.newest_first(self.project_jsonls(cwd)).into_iter().next()
    }

    /// `sessions/<pid>.json`ın kırpılmış `sessionId`si. Yalnız dosyadaki `pid` eşleşiyor VE `procStart` canlı sürecin
    /// başlangıç tikine eşitse (pid yeniden kullanımı koruması); doğrulanamayan kayıt kullanılmaz.
    pub fn session_file_sid(&self, pid: i64) -> Option<String> {
        if pid == 0 {
            return None;
        }
        let path = join_path(&self.paths.claude_sessions_dir(), &format!("{pid}.json"));
        let bytes = self.probe.read_bytes(&path, SESSION_FILE_MAX_BYTES)?;
        let data = Py::parse(std::str::from_utf8(&bytes).ok()?).filter(Py::is_object)?;
        // `int(data.get("pid") or 0)`
        let recorded = match data.get("pid").filter(|v| v.truthy())? {
            Py::Int(n) => *n,
            Py::Float(f) if f.is_finite() => f.trunc() as i64,
            Py::Bool(b) => i64::from(*b),
            Py::Str(s) => parse_int(s)?,
            _ => return None,
        };
        if recorded != pid {
            return None;
        }
        let sid = strip(data.get("sessionId")?.as_str()?);
        let want = data.get("procStart").map(Py::py_str).unwrap_or_default();
        let want = strip(&want);
        if sid.is_empty() || want.is_empty() {
            return None;
        }
        let stat = self.probe.proc_stat(pid)?;
        let stat = String::from_utf8_lossy(&stat);
        // comm boşluk/parantez içerebilir: SON `)` sonrası; 19. alan starttime.
        let fields = &stat[stat.rfind(')')? + 1..];
        let start = fields.split(crate::pyfmt::py_isspace).filter(|f| !f.is_empty()).nth(19)?;
        (start == want).then(|| sid.to_string())
    }

    /// İlk [`META_HEAD_LINES`] satırdan başlık ve cwd; okunamayan dosya ya da bozuk satır sessizce atlanır.
    pub fn jsonl_meta(&self, path: &str) -> Meta {
        let mut meta = Meta::default();
        for row in self.head_lines(path, META_HEAD_LINES).unwrap_or_default().iter().filter_map(|l| json_line(l)) {
            let text = |key: &str| row.get(key).and_then(Py::as_str).map(String::from);
            meta.title = meta.title.or_else(|| text("customTitle"));
            meta.cwd = meta.cwd.or_else(|| text("cwd"));
            let filled = |v: &Option<String>| v.as_deref().is_some_and(|s| !s.is_empty());
            if filled(&meta.title) && filled(&meta.cwd) {
                break;
            }
        }
        meta
    }

    /// Dosya KENDİ `cwd`sini yazmışsa ve hedefle uyuşmuyorsa true (proje dizini kodlaması farklı yolları birleştirir).
    fn other_cwd(&self, meta: &Meta, cwd: &str) -> bool {
        meta.cwd.as_deref().is_some_and(|c| !c.is_empty() && !self.same_path(c, cwd))
    }

    /// Dosyada en az bir `user`/`assistant` satırı var mı.
    pub fn has_chat_rows(&self, path: &str) -> bool {
        let Some(data) = self.probe.read_range(path, 0, STUB_READ_MAX_BYTES) else { return false };
        universal_lines(&data)
            .iter()
            .filter_map(|l| json_line(l))
            .any(|row| matches!(row.get("type").and_then(Py::as_str), Some("user" | "assistant")))
    }

    /// En yeni [`RESUME_SCAN_LIMIT`] transkript içinden: başkasının tuttuğu (kimlik ya da başlık) ve başka cwd'ye ait
    /// olanlar elenir; adı `session_name` olan tercih edilir, yoksa en yeni uygun.
    pub(crate) fn claude_resume_id(&self, cwd: &str, in_use: &BTreeSet<String>, session_name: &str) -> Option<String> {
        let mut fallback = None;
        for path in self.newest_first(self.project_jsonls(cwd)).into_iter().take(RESUME_SCAN_LIMIT) {
            let id = stem(file_name(&path));
            if in_use.contains(id) {
                continue;
            }
            let meta = self.jsonl_meta(&path);
            if self.other_cwd(&meta, cwd) {
                continue;
            }
            let title = meta.title.as_deref().unwrap_or("");
            if !title.is_empty() && title != session_name && in_use.contains(title) {
                continue;
            }
            if !session_name.is_empty() && meta.title.as_deref() == Some(session_name) {
                return Some(id.to_string());
            }
            fallback.get_or_insert_with(|| id.to_string());
        }
        fallback
    }

    /// Başlığı TAM `session_name` olan en yeni gerçek konuşma (TÜM dosyalara bakılır); hepsi stub ise en yenisi.
    pub(crate) fn claude_stopped_sid(&self, cwd: &str, session_name: &str, cache: &MetaCache) -> Option<String> {
        if session_name.is_empty() {
            return None;
        }
        let dir = self.probe.claude_project_dir(cwd);
        let mut matches: Vec<(i64, u64, String)> = Vec::new();
        for name in self.probe.list_dir(&dir)?.into_iter().filter(|n| n.ends_with(".jsonl")) {
            let path = path_join(&dir, &name);
            let Some(st) = self.probe.stat(&path).filter(|s| s.is_file) else { continue };
            let meta = cache.get(&path, (st.mtime_ns, st.size), || self.jsonl_meta(&path));
            if meta.title.as_deref() != Some(session_name) || self.other_cwd(&meta, cwd) {
                continue;
            }
            matches.push((st.mtime_ns, st.size, path));
        }
        matches.sort_by_key(|m| std::cmp::Reverse(m.0));
        matches
            .iter()
            .find(|(_, size, path)| *size >= STUB_MAX_BYTES || self.has_chat_rows(path))
            .or_else(|| matches.first())
            .map(|(_, _, path)| stem(file_name(path)).to_string())
    }
}
