//! Oturum kimliği ve devam (G1) için parite dışında kalan sözleşme: başlık önbelleği, stub taramasının atlanması, okuma
//! üst sınırları, bozuk girdide panik olmaması ve `agy_sids` yazımı (kilit, aynı değer, kuru çalıştırma, hata).
//! Bellek içi, sentetik `Probe`.

use cops_providers::agy_resume::remember_agy_sid;
use cops_providers::bg_work::Clock;
use cops_providers::claude_resume::{META_CACHE_MAX, STUB_MAX_BYTES};
use cops_providers::pyjson::Py;
use cops_providers::resume::HEAD_MAX_BYTES;
use cops_providers::ucli_opts::Toolchain;
use cops_providers::{
    AgySidStore, Cli, FileStat, Live, LiveProbe, McpRegisterError, MetaCache, Paths, Probe, Settings, SqlCell,
};
use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

const DIR: &str = "/p";

#[derive(Default)]
struct Mem {
    /// yol -> (mtime_ns, içerik)
    files: BTreeMap<String, (i64, Vec<u8>)>,
    /// (yol, başlangıç, uzunluk)
    ranges: RefCell<Vec<(String, u64, u64)>>,
    /// (yol, üst sınır)
    whole: RefCell<Vec<(String, u64)>>,
}

impl Mem {
    fn with(files: &[(&str, i64, &str)]) -> Mem {
        let mut m = Mem::default();
        for (path, mtime, body) in files {
            m.put(path, *mtime, body.as_bytes().to_vec());
        }
        m
    }
    fn put(&mut self, path: &str, mtime: i64, body: Vec<u8>) {
        self.files.insert(path.to_string(), (mtime, body));
    }
}

impl Probe for Mem {
    fn is_file(&self, path: &str) -> bool {
        self.files.contains_key(path)
    }
    fn file_size(&self, path: &str) -> Option<u64> {
        self.files.get(path).map(|f| f.1.len() as u64)
    }
    fn is_dir(&self, _: &str) -> bool {
        unreachable!()
    }
    fn exists(&self, _: &str) -> bool {
        unreachable!()
    }
    fn is_symlink(&self, _: &str) -> bool {
        unreachable!()
    }
    fn is_executable_file(&self, _: &str) -> bool {
        unreachable!()
    }
    fn read_text(&self, _: &str) -> Option<String> {
        unreachable!()
    }
    fn realpath(&self, _: &str) -> String {
        unreachable!()
    }
    fn which(&self, _: &str) -> Option<String> {
        unreachable!()
    }
    fn env_var(&self, _: &str) -> Option<String> {
        unreachable!()
    }
    fn claude_help(&self, _: &str) -> String {
        unreachable!()
    }
    fn ucli_chat_help(&self, _: &str) -> String {
        unreachable!()
    }
    fn path_executables(&self) -> Vec<String> {
        unreachable!()
    }
    fn rust_toolchain(&self) -> Result<Toolchain, String> {
        unreachable!()
    }
    fn searxng_url(&self, _: &str, _: bool) -> Option<String> {
        unreachable!()
    }
    fn checks_registry(&self, _: &str) -> Result<(), String> {
        unreachable!()
    }
    fn claude_cost_gate(&self, _: &str) -> Result<(), String> {
        unreachable!()
    }
    fn issue_agent_token(&self, _: &str) -> Result<String, String> {
        unreachable!()
    }
    fn panel_port(&self) -> Option<u16> {
        unreachable!()
    }
    fn register_mcp(&self, _: &str, _: &str, _: &[String]) -> Result<(), McpRegisterError> {
        unreachable!()
    }
}

impl LiveProbe for Mem {
    fn read_range(&self, path: &str, start: u64, len: u64) -> Option<Vec<u8>> {
        self.ranges.borrow_mut().push((path.to_string(), start, len));
        let data = &self.files.get(path)?.1;
        let from = (start as usize).min(data.len());
        let to = from.saturating_add(len as usize).min(data.len());
        Some(data[from..to].to_vec())
    }
    fn read_bytes(&self, path: &str, max: u64) -> Option<Vec<u8>> {
        self.whole.borrow_mut().push((path.to_string(), max));
        self.files.get(path).filter(|f| f.1.len() as u64 <= max).map(|f| f.1.clone())
    }
    fn list_dir(&self, path: &str) -> Option<Vec<String>> {
        let prefix = format!("{path}/");
        let names: Vec<String> = self
            .files
            .keys()
            .filter_map(|k| k.strip_prefix(&prefix))
            .filter(|n| !n.contains('/'))
            .map(String::from)
            .collect();
        (!names.is_empty()).then_some(names)
    }
    fn stat(&self, path: &str) -> Option<FileStat> {
        self.files.get(path).map(|(mtime_ns, body)| FileStat { is_file: true, mtime_ns: *mtime_ns, size: body.len() as u64 })
    }
    fn proc_stat(&self, pid: i64) -> Option<Vec<u8>> {
        Some(format!("{pid} (c) S 1 1 1 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 777 0").into_bytes())
    }
    fn current_dir(&self) -> String {
        "/".into()
    }
    fn agy_sids_doc(&self) -> Option<Py> {
        None
    }
    fn claude_project_dir(&self, _: &str) -> String {
        DIR.into()
    }
    fn read_tail(&self, _: &str, _: u64) -> Option<Vec<u8>> {
        unreachable!()
    }
    fn sqlite_cell(&self, _: &str, _: &str, _: &str) -> Option<SqlCell> {
        unreachable!()
    }
    fn sqlite_rows(&self, _: &str, _: &str, _: &[SqlCell], _: &mut dyn FnMut(Vec<SqlCell>) -> bool) -> bool {
        false
    }
}

fn with<T>(mem: &Mem, f: impl FnOnce(&Live<'_>) -> T) -> T {
    let settings = Settings::default();
    let paths = Paths { claudeops_dir: "/s".into(), home: "/h".into(), repo_dir: "/r".into() };
    f(&Live { settings: &settings, paths: &paths, probe: mem, clock: Clock { now: 0.0, utc_offset_secs: 0 } })
}

fn titled(title: &str) -> String {
    format!("{{\"customTitle\":\"{title}\"}}\n{{\"cwd\":\"/w\"}}\n{{\"type\":\"user\"}}\n")
}

#[test]
fn sidless_or_missing_transcript_falls_back_to_the_newest() {
    let mem = Mem::with(&[("/p/mine.jsonl", 1, "{}"), ("/p/sibling.jsonl", 2, "{}")]);
    with(&mem, |l| {
        assert_eq!(l.jsonl_path_for("/w", Some("mine")).as_deref(), Some("/p/mine.jsonl"));
        for sid in [None, Some(""), Some("gone")] {
            assert_eq!(l.jsonl_path_for("/w", sid).as_deref(), Some("/p/sibling.jsonl"), "{sid:?}");
        }
    });
}

#[test]
fn unchanged_files_are_not_reread_but_changed_ones_are() {
    let mut mem = Mem::with(&[("/p/x.jsonl", 1, &titled("inst"))]);
    let cache = MetaCache::default();
    let ask = |mem: &Mem, name: &str| with(mem, |l| l.sid_for_stopped_session(Cli::Claude, "/w", name, &cache));
    assert_eq!(ask(&mem, "inst").as_deref(), Some("x"));
    // başlık okuması 0'dan başlayan parça; stub taraması da öyle, ikisini uzunlukla ayır
    let heads = |mem: &Mem| mem.ranges.borrow().iter().filter(|r| r.2 == 65_536).count();
    assert_eq!(heads(&mem), 1);
    assert_eq!(ask(&mem, "inst").as_deref(), Some("x"));
    assert_eq!(heads(&mem), 1);
    mem.put("/p/x.jsonl", 2, titled("renamed").into_bytes());
    assert_eq!(ask(&mem, "inst"), None);
    assert_eq!(ask(&mem, "renamed").as_deref(), Some("x"));
    assert_eq!(heads(&mem), 2);
    // yalnız boyut değişse de imza değişir
    mem.put("/p/x.jsonl", 2, titled("other-name").into_bytes());
    assert_eq!(ask(&mem, "other-name").as_deref(), Some("x"));
}

#[test]
fn meta_cache_is_bounded() {
    let cache = MetaCache::default();
    for i in 0..META_CACHE_MAX {
        cache.get(&i.to_string(), (0, 0), Default::default);
    }
    assert_eq!(cache.len(), META_CACHE_MAX);
    cache.get("tasan", (0, 0), Default::default);
    assert_eq!(cache.len(), 1);
}

#[test]
fn a_large_file_counts_as_real_without_being_scanned() {
    let mut mem = Mem::with(&[("/p/small.jsonl", 1, &titled("big"))]);
    let mut large = titled("big").into_bytes();
    large.resize(STUB_MAX_BYTES as usize, b' ');
    mem.put("/p/large.jsonl", 2, large);
    let got = with(&mem, |l| l.sid_for_stopped_session(Cli::Claude, "/w", "big", &MetaCache::default()));
    assert_eq!(got.as_deref(), Some("large"));
    // yalnız başlık parçaları okundu (stub taraması 8 MiB ister)
    assert!(mem.ranges.borrow().iter().all(|r| r.2 == 65_536), "{:?}", mem.ranges.borrow());
}

#[test]
fn head_reading_is_bounded_and_drops_the_unfinished_line() {
    // tek dev satır: okuma üst sınırda durur, yarım satır değerlendirilmez
    let mut huge = b"{\"customTitle\":\"t\",\"x\":\"".to_vec();
    huge.resize(HEAD_MAX_BYTES as usize + 100_000, b'y');
    huge.extend(b"\"}\n");
    let mut mem = Mem::default();
    mem.put("/p/h.jsonl", 1, huge);
    assert_eq!(with(&mem, |l| l.jsonl_meta("/p/h.jsonl")), Default::default());
    let read: u64 = mem.ranges.borrow().iter().map(|r| r.2).sum();
    assert_eq!(read, HEAD_MAX_BYTES);
    // sınırın altında 64 KiB parçaları aşan satır tam okunur ve dosyanın kalanı okunmaz
    let mut long = format!("{{\"x\":\"{}\"}}\n{{\"customTitle\":\"t\",\"cwd\":\"/w\"}}\n", "y".repeat(200_000));
    long.push_str(&"{}\n".repeat(500_000));
    let mem = Mem::with(&[("/p/l.jsonl", 1, &long)]);
    assert_eq!(with(&mem, |l| l.jsonl_meta("/p/l.jsonl")).title.as_deref(), Some("t"));
    assert!(mem.ranges.borrow().len() <= 5);
}

#[test]
fn whole_file_reads_carry_a_limit() {
    let mem = Mem::default();
    with(&mem, |l| {
        l.session_file_sid(7);
        l.resolve_resume_id(Cli::Agy, "/w", &BTreeSet::new(), "a");
    });
    let limits: Vec<u64> = mem.whole.borrow().iter().map(|r| r.1).collect();
    assert_eq!(limits, [1024 * 1024, 8 * 1024 * 1024]);
}

#[test]
fn truncated_and_mutated_input_never_panics() {
    let session = br#"{"pid":7,"sessionId":"s","procStart":"777"}"#.to_vec();
    let transcript = titled("inst").into_bytes();
    let mut seed = 0x9e37_79b9_7f4a_7c15u64;
    for round in 0..3_000 {
        seed ^= seed << 13;
        seed ^= seed >> 7;
        seed ^= seed << 17;
        let mut mem = Mem::default();
        for (path, good) in [("/h/.claude/sessions/7.json", &session), ("/p/a.jsonl", &transcript)] {
            let mut bad = good.clone();
            let at = seed as usize % bad.len();
            if round % 2 == 0 {
                bad[at] = (seed >> 24) as u8;
            } else {
                bad.truncate(at);
                bad.extend_from_slice(&seed.to_le_bytes());
            }
            mem.put(path, 1, bad);
        }
        mem.put("/h/.gemini/antigravity-cli/cache/last_conversations.json", 1, mem.files["/p/a.jsonl"].1.clone());
        with(&mem, |l| {
            l.session_file_sid(7);
            l.session_file_sid(i64::MIN);
            for cli in Cli::ALL {
                l.resolve_resume_id(cli, "/w", &BTreeSet::new(), "inst");
                l.sid_for_stopped_session(cli, "/w", "inst", &MetaCache::default());
            }
        });
    }
}

// ------------------------------------------------------------------------------------------------------- agy yazımı

#[derive(Default)]
struct Store {
    doc: Mutex<Option<Py>>,
    lock: Mutex<()>,
    locks: AtomicUsize,
    saves: AtomicUsize,
    fail_save: bool,
    /// Kilit alınmadan hemen önce başka bir yazar belgeyi bu hale getirir.
    race: Mutex<Option<Py>>,
}

impl AgySidStore for Store {
    fn load(&self) -> Option<Py> {
        self.doc.lock().unwrap().clone()
    }
    fn locked(&self, f: &mut dyn FnMut() -> Result<bool, String>) -> Result<bool, String> {
        let _guard = self.lock.lock().unwrap();
        self.locks.fetch_add(1, Ordering::SeqCst);
        if let Some(doc) = self.race.lock().unwrap().take() {
            *self.doc.lock().unwrap() = Some(doc);
        }
        f()
    }
    fn save(&self, doc: &Py) -> Result<(), String> {
        if self.fail_save {
            return Err("disk".into());
        }
        // yazım penceresi: kilitsiz bir oku-değiştir-yaz burada kayıt kaybeder
        std::thread::yield_now();
        *self.doc.lock().unwrap() = Some(doc.clone());
        self.saves.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

fn object(pairs: &[(&str, &str)]) -> Py {
    Py::Object(pairs.iter().map(|(k, v)| (k.to_string(), Py::Str(v.to_string()))).collect())
}

#[test]
fn remember_saves_through_the_store_once() {
    let store = Store::default();
    assert_eq!(remember_agy_sid(&store, "a", "sid-1", false), Ok(true));
    assert_eq!(store.load(), Some(object(&[("a", "sid-1")])));
    assert_eq!(remember_agy_sid(&store, "b", "sid-2", false), Ok(true));
    assert_eq!(remember_agy_sid(&store, "a", "sid-3", false), Ok(true));
    // güncellenen ad yerinde kalır
    assert_eq!(store.load(), Some(object(&[("a", "sid-3"), ("b", "sid-2")])));
}

#[test]
fn unchanged_value_does_not_rewrite_or_lock() {
    let store = Store::default();
    remember_agy_sid(&store, "a", "sid-1", false).unwrap();
    assert_eq!(remember_agy_sid(&store, "a", "sid-1", false), Ok(false));
    assert_eq!((store.locks.load(Ordering::SeqCst), store.saves.load(Ordering::SeqCst)), (1, 1));
}

#[test]
fn value_is_checked_again_under_the_lock() {
    let store = Store::default();
    *store.race.lock().unwrap() = Some(object(&[("a", "sid-1"), ("kardes", "k")]));
    assert_eq!(remember_agy_sid(&store, "a", "sid-1", false), Ok(false));
    assert_eq!(store.saves.load(Ordering::SeqCst), 0);
    *store.race.lock().unwrap() = Some(object(&[("kardes", "k2")]));
    assert_eq!(remember_agy_sid(&store, "a", "sid-9", false), Ok(true));
    assert_eq!(store.load(), Some(object(&[("kardes", "k2"), ("a", "sid-9")])));
}

#[test]
fn preview_writes_nothing_and_save_errors_surface() {
    let store = Store::default();
    assert_eq!(remember_agy_sid(&store, "a", "s", true), Ok(false));
    assert_eq!((store.locks.load(Ordering::SeqCst), store.load()), (0, None));
    let broken = Store { fail_save: true, ..Default::default() };
    assert_eq!(remember_agy_sid(&broken, "a", "s", false), Err("disk".into()));
}

#[test]
fn concurrent_remembers_lose_nothing() {
    let store = Store::default();
    std::thread::scope(|scope| {
        for i in 0..6 {
            let store = &store;
            scope.spawn(move || {
                for j in 0..8 {
                    remember_agy_sid(store, &format!("s{i}_{j}"), &format!("id{i}_{j}"), false).unwrap();
                }
            });
        }
    });
    let Some(Py::Object(entries)) = store.load() else { panic!("belge yok") };
    assert_eq!(entries.len(), 48);
}
