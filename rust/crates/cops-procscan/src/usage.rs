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
    // Yedek yol `Value` üzerinden: yinelenen anahtarda Python gibi son değer kalır (türetilmiş struct hata verirdi).
    let Some(row) = serde_json::from_str::<Row>(text).ok().or_else(|| {
        let v = py::json(text.as_bytes())?;
        Row::deserialize(v).ok()
    }) else {
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

/// Ekleme sırasını koruyan yol tablosu (Python `dict`): var olan anahtarın üzerine yazmak yerini değiştirmez,
/// silinip yeniden eklenen anahtar sona gider. Tahliye bu sıraya göredir.
#[derive(Debug)]
struct Ordered<V> {
    map: HashMap<PathBuf, (u64, V)>,
    order: BTreeMap<u64, PathBuf>,
    next: u64,
}

impl<V> Default for Ordered<V> {
    fn default() -> Self {
        Ordered {
            map: HashMap::new(),
            order: BTreeMap::new(),
            next: 0,
        }
    }
}

impl<V> Ordered<V> {
    fn len(&self) -> usize {
        self.map.len()
    }

    fn get(&self, path: &Path) -> Option<&V> {
        self.map.get(path).map(|(_, v)| v)
    }

    fn get_mut(&mut self, path: &Path) -> Option<&mut V> {
        self.map.get_mut(path).map(|(_, v)| v)
    }

    fn entry_or_default(&mut self, path: &Path) -> &mut V
    where
        V: Default,
    {
        let (_, v) = self.map.entry(path.to_path_buf()).or_insert_with(|| {
            self.next += 1;
            self.order.insert(self.next, path.to_path_buf());
            (self.next, V::default())
        });
        v
    }

    fn remove(&mut self, path: &Path) {
        if let Some((seq, _)) = self.map.remove(path) {
            self.order.remove(&seq);
        }
    }

    /// En eski eklenen anahtarı atar.
    fn pop_oldest(&mut self) {
        if let Some((_, path)) = self.order.pop_first() {
            self.map.remove(&path);
        }
    }

    /// En eskiden en yeniye.
    fn iter(&self) -> impl Iterator<Item = (&Path, &V)> {
        self.order.values().filter_map(|p| Some((p.as_path(), self.get(p)?)))
    }
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
    files: Ordered<FileState>,
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
        // yeni ya da küçülmüş dosya: baştan. Python gibi, kapasite doluyken küçülmede de en eski girdi atılır
        // (o girdi dosyanın kendisiyse sona eklenir, değilse yeri değişmez).
        let fresh = self.files.get(path).is_none_or(|st| size < st.offset || size < st.size);
        if fresh {
            if self.files.len() >= MAX_CACHED_FILES {
                self.files.pop_oldest();
            }
            *self.files.entry_or_default(path) = FileState::default();
        }
        let Some(st) = self.files.get_mut(path) else {
            return Ok(None);
        };
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
    summaries: Arc<Mutex<Ordered<Summary>>>,
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
        let ent = map.entry_or_default(main);
        let value = ent.value.clone();
        if !ent.running && ent.at.is_none_or(|t| t.elapsed() >= self.ttl) {
            ent.running = true;
            // en eski eklenen 200 boştaki girdi
            if map.len() > MAX_CACHED_FILES {
                let old: Vec<PathBuf> = map
                    .iter()
                    .filter(|(k, v)| !v.running && *k != main)
                    .map(|(k, _)| k.to_path_buf())
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
        let ent = map.entry_or_default(main);
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
    use std::fs;
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
        let st = r.files.get(&p).unwrap();
        assert_eq!(
            (st.offset, st.size, st.turns.len()),
            ((row("m1", "\"x\"", 1).len() + row("m2", "5", 2).len()) as u64, 0, 1)
        );
        let u = r.usage_for_path(&p).unwrap();
        assert_eq!((u.main.turns, u.main.output), (2, 5));
        let st = r.files.get(&p).unwrap();
        assert_eq!(st.size, st.offset);
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
        let refreshed_after_delete = |c: &UsageCache| lock(&c.summaries).get(&p).unwrap().at;
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

    fn order<V>(t: &Ordered<V>) -> Vec<PathBuf> {
        t.iter().map(|(p, _)| p.to_path_buf()).collect()
    }

    /// Python `_files`: taşmada en eski EKLENEN atılır (okunmak yeri değiştirmez); küçülen dosya yerinde kalır ama
    /// kapasite doluyken yine en eskiyi attırır; kaybolup dönen dosya sona gider.
    #[test]
    fn file_cache_evicts_in_insertion_order() {
        assert_eq!(MAX_CACHED_FILES, 2000);
        let tmp = tempfile::tempdir().unwrap();
        let path = |i: usize| tmp.path().join(format!("f{i}.jsonl"));
        let two = row("a", "\"x\"", 1) + &row("b", "\"x\"", 1);
        let mut r = UsageReader::default();
        let read = |r: &mut UsageReader, i: usize| r.usage_for_path(&path(i)).map(|u| u.main.turns);
        for i in 0..MAX_CACHED_FILES + 2 {
            append(&path(i), &two);
        }
        for i in 0..MAX_CACHED_FILES {
            assert_eq!(read(&mut r, i), Some(2));
        }
        let all: Vec<PathBuf> = (0..MAX_CACHED_FILES).map(path).collect();
        assert_eq!(order(&r.files), all);

        // yeniden okuma (değişmemiş ya da büyümüş) sırayı değiştirmez
        append(&path(0), &row("c", "\"x\"", 1));
        assert_eq!(read(&mut r, 0), Some(3));
        assert_eq!(order(&r.files), all);

        // yeni dosya: en son okunmuş olsa da ilk eklenen gider
        assert_eq!(read(&mut r, MAX_CACHED_FILES), Some(2));
        assert_eq!(order(&r.files), (1..=MAX_CACHED_FILES).map(path).collect::<Vec<_>>());

        // ortadaki dosya küçüldü: en eski (f1) atılır, f5 yerinde kalır, tablo bir eksilir
        fs::write(path(5), row("z", "\"x\"", 1)).unwrap();
        assert_eq!(read(&mut r, 5), Some(1));
        let after: Vec<PathBuf> = (2..=MAX_CACHED_FILES).map(path).collect();
        assert_eq!(order(&r.files), after);

        // tablo dolu değilken yeni dosya kimseyi atmaz
        assert_eq!(read(&mut r, MAX_CACHED_FILES + 1), Some(2));
        assert_eq!(r.files.len(), MAX_CACHED_FILES);
        assert_eq!(order(&r.files)[0], path(2));

        // dolu ve küçülen dosya en eskinin kendisi: atılıp sona eklenir
        fs::write(path(2), row("z", "\"x\"", 1)).unwrap();
        assert_eq!(read(&mut r, 2), Some(1));
        assert_eq!(r.files.len(), MAX_CACHED_FILES);
        let o = order(&r.files);
        assert_eq!((o.first(), o.last()), (Some(&path(3)), Some(&path(2))));

        // kaybolan dosya tablodan çıkar, dönünce sona eklenir
        fs::remove_file(path(10)).unwrap();
        assert_eq!(read(&mut r, 10), None);
        assert_eq!(r.files.len(), MAX_CACHED_FILES - 1);
        assert!(r.files.get(&path(10)).is_none());
        append(&path(10), &two);
        assert_eq!(read(&mut r, 10), Some(2));
        let o = order(&r.files);
        assert_eq!((o.first(), o.last()), (Some(&path(3)), Some(&path(10))));
    }

    /// Python `_summaries`: bayat bir sorgu tablo 2000'i AŞINCA en eski 200 girdiyi atar; yenilenmekte olan ve
    /// sorulan yol korunur.
    #[test]
    fn summary_cache_evicts_oldest_200() {
        let path = |i: usize| PathBuf::from(format!("/yok/{i}.jsonl"));
        // `n` girdili tablo; hepsi taze, `busy` yenilenmekte
        let filled = |n: usize, busy: usize| {
            let c = UsageCache::new(Duration::from_secs(3600));
            let mut map = lock(&c.summaries);
            for i in 0..n {
                let e = map.entry_or_default(&path(i));
                e.at = Some(Instant::now());
                e.running = i == busy;
            }
            drop(map);
            c
        };
        let left = |c: &UsageCache| order(&lock(&c.summaries));
        let n = MAX_CACHED_FILES;

        // sınırda (2000) atma yok
        let c = filled(n - 1, n);
        c.get(&path(n - 1));
        assert_eq!(left(&c).len(), n);

        // taze girdinin sorgusu, tablo büyük olsa da atmaz
        let c = filled(n + 1, n + 5);
        c.get(&path(7));
        assert_eq!(left(&c).len(), n + 1);

        // 2001: en eski 200 (yenilenen 0 atlanır)
        let c = filled(n, 0);
        c.get(&path(n));
        let want: Vec<PathBuf> = std::iter::once(0).chain(201..=n).map(path).collect();
        assert_eq!(left(&c), want);

        // sorulan yol en eski ve bayatsa da korunur
        let c = filled(n + 1, n + 5);
        lock(&c.summaries).entry_or_default(&path(0)).at = None;
        c.get(&path(0));
        let want: Vec<PathBuf> = std::iter::once(0).chain(201..=n).map(path).collect();
        assert_eq!(left(&c), want);
    }

    #[test]
    fn fmt_tokens_python_examples() {
        assert_eq!([5, 12345, 1_234_567].map(fmt_tokens), ["5", "12.3K", "1.23M"]);
    }
}
