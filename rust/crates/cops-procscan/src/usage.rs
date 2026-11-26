//! Oturumun kümülatif token harcaması (`session_usage.py`): ana transkript + `subagents/agent-*.jsonl`,
//! tur `(message.id, requestId)` ile tekilleştirilir, tekrarlar arasında alan başına en büyük değer tutulur.
//! Okuma artımlıdır; yarım son satır beklenir, küçülen dosya baştan okunur.

use crate::py;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::fs::File;
use std::io::{BufRead, BufReader, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::{Duration, Instant};

/// Önbellek tazelik süresi.
pub const CACHE_TTL: Duration = Duration::from_secs(30);

const MAX_CACHED_FILES: usize = 2000;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
pub struct Totals {
    #[serde(rename = "in")]
    pub input: u64,
    #[serde(rename = "out")]
    pub output: u64,
    pub cache_write: u64,
    pub cache_read: u64,
    pub turns: u64,
}

impl Totals {
    fn add(&mut self, c: &[u64; 4]) {
        self.input = self.input.saturating_add(c[0]);
        self.output = self.output.saturating_add(c[1]);
        self.cache_write = self.cache_write.saturating_add(c[2]);
        self.cache_read = self.cache_read.saturating_add(c[3]);
        self.turns += 1;
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct Subagents {
    pub n: u64,
    #[serde(flatten)]
    pub totals: Totals,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct Usage {
    /// Yalnız ana oturum.
    #[serde(flatten)]
    pub main: Totals,
    pub subagents: Subagents,
    /// Ana + alt ajanlar, model ailesine göre.
    pub by_family: BTreeMap<&'static str, Totals>,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
enum Key {
    /// Python demeti: `(message.id, requestId)` ya da `("row", uuid)` (aynı uzayda; Python'da da çakışabilirler).
    Pair(String, String),
    /// Kimliksiz satır: her biri ayrı tur.
    Unique(u64),
}

#[derive(Debug, Clone, Copy)]
struct Turn {
    family: &'static str,
    counts: [u64; 4],
}

// `content` bilerek alınmıyor: atlanan dizgiler doğrulanmaz (yalnız vekil `\udxxx` içeren satır kaybolmasın).
#[derive(Deserialize)]
struct Row {
    #[serde(rename = "type")]
    kind: Option<Value>,
    message: Option<Message>,
    #[serde(rename = "requestId")]
    request_id: Option<Value>,
    uuid: Option<Value>,
}

#[derive(Deserialize)]
struct Message {
    id: Option<Value>,
    model: Option<Value>,
    usage: Option<Value>,
}

fn family(model: &str) -> &'static str {
    let m = model.to_lowercase();
    ["fable", "opus", "sonnet", "haiku"]
        .into_iter()
        .find(|f| m.contains(f))
        .unwrap_or("other")
}

fn count(v: Option<&Value>) -> u64 {
    match v {
        Some(Value::Number(n)) => n.as_u64().unwrap_or_else(|| n.as_f64().map_or(0, |f| f.max(0.0) as u64)),
        Some(Value::String(s)) => py::int(s).map_or(0, |n| u64::try_from(n).unwrap_or(0)),
        Some(Value::Bool(b)) => u64::from(*b),
        _ => 0,
    }
}

/// Python'un `usage_for_path`i `None`a düşüren satır: doğru ama dizgi olmayan `model`, ya da tur anahtarında
/// hashlenemeyen (dizi/nesne) değer.
#[derive(Debug, PartialEq, Eq)]
struct BadRow;

/// Python sözlük anahtarı eşitliği: `True == 1 == 1.0`, `None` ayrı, dizi/nesne hashlenemez (`TypeError`).
fn py_key(v: Option<&Value>) -> Result<String, BadRow> {
    Ok(match v {
        None | Some(Value::Null) => "N".into(),
        Some(Value::Bool(b)) => format!("n{}", u8::from(*b)),
        Some(Value::Number(n)) => match (n.as_i64(), n.as_u64(), n.as_f64()) {
            (Some(i), _, _) => format!("n{i}"),
            (_, Some(u), _) => format!("n{u}"),
            (_, _, Some(f)) if f.fract() == 0.0 && f.abs() < 9.0e18 => format!("n{}", f as i64),
            (_, _, Some(f)) => format!("f{f}"),
            _ => format!("f{n}"),
        },
        Some(Value::String(s)) => format!("s{s}"),
        Some(Value::Array(_) | Value::Object(_)) => return Err(BadRow),
    })
}

fn parse(line: &[u8], unique: &mut u64) -> Result<Option<(Key, Turn)>, BadRow> {
    if !line.windows(7).any(|w| w == b"\"usage\"") {
        return Ok(None);
    }
    let Ok(text) = std::str::from_utf8(line) else {
        return Ok(None);
    };
    if !text.trim_start().starts_with('{') {
        return Ok(None);
    }
    // Python eşsiz vekil kaçışını (`\ud800`) kabul eder: kimlik/model alanında olsa da satır kaybolmasın.
    let Ok(row) = serde_json::from_str::<Row>(text).or_else(|_| serde_json::from_str::<Row>(&py::mask_lone_surrogates(text)))
    else {
        return Ok(None);
    };
    if row.kind.as_ref().and_then(Value::as_str) != Some("assistant") {
        return Ok(None);
    }
    let Some(m) = row.message else { return Ok(None) };
    let Some(Value::Object(u)) = m.usage else { return Ok(None) };
    let model = match &m.model {
        Some(Value::String(s)) => s.as_str(),
        Some(v) if py::truthy(v) => return Err(BadRow),
        _ => "",
    };
    if model == "<synthetic>" {
        return Ok(None); // API hata/kesinti sentetik mesajı
    }
    // `(mid, requestId) if mid else ("row", uuid or object())`
    let key = match (&m.id, &row.uuid) {
        (Some(id), _) if py::truthy(id) => Key::Pair(py_key(Some(id))?, py_key(row.request_id.as_ref())?),
        (_, Some(uuid)) if py::truthy(uuid) => Key::Pair("srow".into(), py_key(Some(uuid))?),
        _ => {
            *unique += 1;
            Key::Unique(*unique)
        }
    };
    let counts = [
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ]
    .map(|k| count(u.get(k)));
    Ok(Some((
        key,
        Turn {
            family: family(model),
            counts,
        },
    )))
}

#[derive(Debug, Default)]
struct FileState {
    offset: u64,
    size: u64,
    turns: HashMap<Key, Turn>,
}

/// Dosya başına artımlı okuma durumu. Uzun yaşayan süreç tek örnek tutar.
#[derive(Debug, Default)]
pub struct UsageReader {
    files: HashMap<PathBuf, FileState>,
    unique: u64,
}

impl UsageReader {
    /// Dosya yok/okunamıyor `Ok(None)`; Python'un istisna fırlattığı satır `Err` (offset satırın ötesinde kalır).
    fn update(&mut self, path: &Path) -> Result<Option<&FileState>, BadRow> {
        let Ok(meta) = std::fs::metadata(path) else {
            self.files.remove(path);
            return Ok(None);
        };
        let size = meta.len();
        if !self.files.contains_key(path) && self.files.len() >= MAX_CACHED_FILES {
            if let Some(old) = self.files.keys().next().cloned() {
                self.files.remove(&old);
            }
        }
        let st = self.files.entry(path.to_path_buf()).or_default();
        if size < st.offset || size < st.size {
            *st = FileState::default();
        }
        if size != st.offset {
            let Ok(mut f) = File::open(path) else { return Ok(None) };
            if f.seek(SeekFrom::Start(st.offset)).is_err() {
                return Ok(None);
            }
            let mut r = BufReader::new(f);
            let mut line = Vec::new();
            loop {
                line.clear();
                match r.read_until(b'\n', &mut line) {
                    Err(_) => return Ok(None),
                    Ok(0) => break,
                    Ok(_) if line.last() != Some(&b'\n') => break,
                    Ok(_) => {}
                }
                st.offset += line.len() as u64;
                if let Some((key, turn)) = parse(&line, &mut self.unique)? {
                    st.turns
                        .entry(key)
                        .and_modify(|old| {
                            old.family = turn.family;
                            for (o, n) in old.counts.iter_mut().zip(turn.counts) {
                                *o = (*o).max(n);
                            }
                        })
                        .or_insert(turn);
                }
            }
        }
        st.size = size;
        Ok(Some(st))
    }

    /// Ana transkript okunamazsa ya da (ana ya da alt ajan) dosyada Python'un istisna fırlattığı satır varsa `None`
    /// (o satır bir sonraki çağrıda atlanmış olur, Python gibi).
    pub fn usage_for_path(&mut self, main: &Path) -> Option<Usage> {
        fn sum(st: &FileState, into: &mut Totals, fams: &mut BTreeMap<&'static str, Totals>) {
            for t in st.turns.values() {
                into.add(&t.counts);
                fams.entry(t.family).or_default().add(&t.counts);
            }
        }
        let mut out = Usage::default();
        sum(self.update(main).ok()??, &mut out.main, &mut out.by_family);
        let stem = match main.extension() {
            Some(e) if e == "jsonl" => main.with_extension(""),
            _ => main.to_path_buf(),
        };
        let mut subs: Vec<PathBuf> = std::fs::read_dir(stem.join("subagents"))
            .into_iter()
            .flatten()
            .flatten()
            .filter(|e| {
                let n = e.file_name();
                let n = n.to_string_lossy();
                n.starts_with("agent-") && n.ends_with(".jsonl")
            })
            .map(|e| e.path())
            .collect();
        subs.sort();
        for p in subs {
            // Python: alt ajan dosyasındaki istisna da tüm toplamı `None` yapar
            if let Some(st) = self.update(&p).ok()? {
                out.subagents.n += 1;
                sum(st, &mut out.subagents.totals, &mut out.by_family);
            }
        }
        Some(out)
    }
}

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(PoisonError::into_inner)
}

#[derive(Debug, Default)]
struct Summary {
    at: Option<Instant>,
    value: Option<Usage>,
    running: bool,
}

/// `/api/status` için bekletmeyen önbellek (`cached_usage_for_path`): bayatsa arka plan iş parçacığı yeniler,
/// çağrı eldeki değeri (ilk seferde `None`) hemen döner. Klonlar aynı durumu paylaşır.
#[derive(Debug, Clone)]
pub struct UsageCache {
    ttl: Duration,
    reader: Arc<Mutex<UsageReader>>,
    summaries: Arc<Mutex<HashMap<PathBuf, Summary>>>,
}

impl Default for UsageCache {
    fn default() -> Self {
        UsageCache::new(CACHE_TTL)
    }
}

impl UsageCache {
    pub fn new(ttl: Duration) -> Self {
        UsageCache {
            ttl,
            reader: Arc::default(),
            summaries: Arc::default(),
        }
    }

    pub fn get(&self, main: &Path) -> Option<Usage> {
        let mut map = lock(&self.summaries);
        let ent = map.entry(main.to_path_buf()).or_default();
        let value = ent.value.clone();
        if !ent.running && ent.at.is_none_or(|t| t.elapsed() >= self.ttl) {
            ent.running = true;
            if map.len() > MAX_CACHED_FILES {
                let old: Vec<PathBuf> = map
                    .iter()
                    .filter(|(k, v)| !v.running && k.as_path() != main)
                    .map(|(k, _)| k.clone())
                    .take(200)
                    .collect();
                old.iter().for_each(|k| {
                    map.remove(k);
                });
            }
            let (this, path) = (self.clone(), main.to_path_buf());
            let spawned = std::thread::Builder::new()
                .name("session-usage".into())
                .spawn(move || this.refresh(&path));
            if spawned.is_err() {
                if let Some(e) = map.get_mut(main) {
                    e.running = false;
                }
                return None;
            }
        }
        value
    }

    fn refresh(&self, main: &Path) {
        let value = lock(&self.reader).usage_for_path(main);
        let mut map = lock(&self.summaries);
        let ent = map.entry(main.to_path_buf()).or_default();
        if value.is_some() || ent.value.is_none() {
            ent.value = value;
        }
        ent.at = Some(Instant::now());
        ent.running = false;
    }
}

/// 12345 -> `12.3K`, 1234567 -> `1.23M`.
pub fn fmt_tokens(n: u64) -> String {
    if n >= 1_000_000 {
        format!("{:.2}M", n as f64 / 1_000_000.0)
    } else if n >= 1000 {
        format!("{:.1}K", n as f64 / 1000.0)
    } else {
        n.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn row(id: &str, model: &str, out: u64) -> String {
        format!(
            r#"{{"type":"assistant","requestId":"r","message":{{"id":"{id}","model":{model},"usage":{{"output_tokens":{out}}}}}}}"#
        ) + "\n"
    }

    fn append(p: &Path, s: &str) {
        std::fs::OpenOptions::new()
            .append(true)
            .create(true)
            .open(p)
            .unwrap()
            .write_all(s.as_bytes())
            .unwrap();
    }

    #[test]
    fn bad_row_returns_none_once_and_offset_moves_past_it() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("s.jsonl");
        append(&p, &(row("m1", "\"x\"", 1) + &row("m2", "5", 2) + &row("m3", "\"x\"", 4)));
        let mut r = UsageReader::default();
        assert_eq!(r.usage_for_path(&p), None);
        // Python gibi: offset bozuk satırın ötesinde, önceki tur korunur, sonraki tur okunur
        let st = &r.files[&p];
        assert_eq!(
            (st.offset, st.size, st.turns.len()),
            ((row("m1", "\"x\"", 1).len() + row("m2", "5", 2).len()) as u64, 0, 1)
        );
        let u = r.usage_for_path(&p).unwrap();
        assert_eq!((u.main.turns, u.main.output), (2, 5));
        assert_eq!(r.files[&p].size, r.files[&p].offset);
    }

    #[test]
    fn python_key_equality() {
        let k = |v: Value| py_key(Some(&v));
        assert_eq!(k(json(1)), k(json(1.0)));
        assert_eq!(k(json(true)), k(json(1)));
        assert_ne!(k(json("1")), k(json(1)));
        assert_eq!(py_key(None), k(Value::Null));
        assert_eq!(k(json([1])), Err(BadRow));
        assert_eq!(k(serde_json::json!({})), Err(BadRow));
        assert_ne!(k(json(1.5)), k(json(1)));
    }

    fn json<T: Serialize>(v: T) -> Value {
        serde_json::to_value(v).unwrap()
    }

    /// İlk çağrı `None` (beklemez), arka plan yenilemesinden sonra değer; okuma hatası eski değeri EZMEZ.
    #[test]
    fn cache_first_none_then_value_and_error_keeps_last_good() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("s.jsonl");
        append(&p, &row("m1", "\"claude-opus\"", 3));
        let cache = UsageCache::new(Duration::ZERO);
        let wait_for = |want: &dyn Fn(&Option<Usage>) -> bool| {
            let t = Instant::now();
            loop {
                let v = cache.get(&p);
                if want(&v) || t.elapsed() > Duration::from_secs(5) {
                    return v;
                }
                std::thread::sleep(Duration::from_millis(5));
            }
        };
        assert_eq!(cache.get(&p), None);
        let v = wait_for(&|v| v.is_some()).unwrap();
        assert_eq!((v.main.turns, v.main.output), (1, 3));

        // dosya gitti: yenilemeler `None` üretir ama son iyi değer kalır
        std::fs::remove_file(&p).unwrap();
        let refreshed_after_delete = |c: &UsageCache| lock(&c.summaries)[&p].at;
        let before = refreshed_after_delete(&cache);
        let t = Instant::now();
        while refreshed_after_delete(&cache) == before && t.elapsed() < Duration::from_secs(5) {
            assert_eq!(cache.get(&p).map(|u| u.main.turns), Some(1));
            std::thread::sleep(Duration::from_millis(5));
        }
        assert_ne!(refreshed_after_delete(&cache), before, "yenileme koşmadı");
        assert_eq!(cache.get(&p).map(|u| u.main.turns), Some(1));

        // yeni içerik gelince güncellenir
        append(&p, &(row("a", "\"x\"", 1) + &row("b", "\"x\"", 1)));
        let v = wait_for(&|v| v.as_ref().is_some_and(|u| u.main.turns == 2)).unwrap();
        assert_eq!(v.main.turns, 2);
    }

    /// TTL içinde ikinci yenileme başlatılmaz.
    #[test]
    fn cache_respects_ttl() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("s.jsonl");
        append(&p, &row("m1", "\"x\"", 3));
        let cache = UsageCache::new(Duration::from_secs(3600));
        assert_eq!(cache.get(&p), None);
        let t = Instant::now();
        while cache.get(&p).is_none() && t.elapsed() < Duration::from_secs(5) {
            std::thread::sleep(Duration::from_millis(5));
        }
        append(&p, &row("m2", "\"x\"", 3));
        std::thread::sleep(Duration::from_millis(50));
        assert_eq!(cache.get(&p).map(|u| u.main.turns), Some(1));
    }

    #[test]
    fn fmt_tokens_python_examples() {
        assert_eq!([5, 12345, 1_234_567].map(fmt_tokens), ["5", "12.3K", "1.23M"]);
    }
}
