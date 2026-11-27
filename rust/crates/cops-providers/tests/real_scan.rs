//! G9 gerçek süreç taraması ([`ProcScan`]): sahte `/proc` ağacı (geçici dizin, `cops-procscan` testlerinin düzeni) ve
//! sahte ya da geçici dizinli `agy_sids` deposu. Gerçek süreçlere ve `~/.claude`a dokunulmaz; tek gerçek `/proc` testi
//! yalnız okur (kuru kip: hiçbir şey yazılmaz). `/proc` tarayan testler sıralı ([`proc_guard`]).

use cops_procscan::Config;
use cops_providers::agy_resume::AgySidStore;
use cops_providers::pyjson::Py;
use cops_providers::real::docs::{DocAgySidStore, StateDocStore};
use cops_providers::real::scan::{scan_config, ProcScan};
use cops_providers::spawn_exec::{DiagSink, SessionScan};
use cops_providers::{ids_held_by_others, Diag, LiveSession, Paths};
use cops_state::{Backend, StateDir, StateDocs};
use serde_json::json;
use std::cell::{Cell, RefCell};
use std::fs;
use std::os::unix::fs::symlink;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use tempfile::TempDir;

const ME: u32 = 1000;

fn proc_guard() -> MutexGuard<'static, ()> {
    static LOCK: Mutex<()> = Mutex::new(());
    LOCK.lock().unwrap_or_else(PoisonError::into_inner)
}

struct Fake {
    _tmp: TempDir,
    root: PathBuf,
    cfg: Config,
}

impl Fake {
    fn new() -> Fake {
        let tmp = TempDir::new().unwrap();
        let root = tmp.path().to_path_buf();
        for d in ["proc", "claude/sessions", "claude/projects"] {
            fs::create_dir_all(root.join(d)).unwrap();
        }
        fs::write(root.join("proc/stat"), "cpu 0\nbtime 1000000\n").unwrap();
        let cfg = Config {
            proc_root: root.join("proc"),
            claude_dir: root.join("claude"),
            agy_cache: root.join("agy_cache.json"),
            agy_sids: root.join("agy_sids.json"),
            uid: ME,
            clk_tck: 100,
        };
        Fake {
            _tmp: tmp,
            root,
            cfg,
        }
    }

    fn add(&self, pid: u32, cmd: &str, env: &[&str], cwd: &str) {
        let d = self.root.join("proc").join(pid.to_string());
        fs::create_dir_all(d.join("fd")).unwrap();
        fs::write(
            d.join("status"),
            format!("Name:\tx\nUid:\t{ME}\t{ME}\t{ME}\t{ME}\n"),
        )
        .unwrap();
        fs::write(
            d.join("stat"),
            format!(
                "{pid} (x) S 1 0 0 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 {} 0 0\n",
                pid * 10
            ),
        )
        .unwrap();
        let nul = |parts: Vec<&str>| parts.iter().map(|s| format!("{s}\0")).collect::<String>();
        fs::write(
            d.join("cmdline"),
            nul(cmd.split(' ').filter(|s| !s.is_empty()).collect()),
        )
        .unwrap();
        fs::write(d.join("environ"), nul(env.to_vec())).unwrap();
        symlink(cwd, d.join("cwd")).unwrap();
        symlink("/dev/pts/3", d.join("fd/0")).unwrap();
    }
}

/// Bellekte `agy_sids`; kilit ve yazım hatası seçilebilir.
#[derive(Default)]
struct Mem {
    doc: RefCell<Option<Py>>,
    lock_err: Option<String>,
    save_err: Option<String>,
    saves: Cell<u32>,
    locks: Cell<u32>,
}

impl AgySidStore for Mem {
    fn load(&self) -> Option<Py> {
        self.doc.borrow().clone()
    }
    fn locked(&self, f: &mut dyn FnMut() -> Result<bool, String>) -> Result<bool, String> {
        self.locks.set(self.locks.get() + 1);
        if let Some(e) = &self.lock_err {
            return Err(e.clone());
        }
        f()
    }
    fn save(&self, doc: &Py) -> Result<(), String> {
        if let Some(e) = &self.save_err {
            return Err(e.clone());
        }
        self.saves.set(self.saves.get() + 1);
        *self.doc.borrow_mut() = Some(doc.clone());
        Ok(())
    }
}

#[derive(Default)]
struct Sink(Mutex<Vec<Diag>>);

impl DiagSink for Sink {
    fn log(&self, diag: &Diag) {
        self.0.lock().unwrap().push(diag.clone());
    }
}

impl Sink {
    fn events(&self) -> Vec<String> {
        self.0
            .lock()
            .unwrap()
            .iter()
            .map(|d| format!("{} {:?}", d.event, d.fields))
            .collect()
    }
}

fn obj(pairs: &[(&str, &str)]) -> Py {
    Py::Object(
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), Py::Str(v.to_string())))
            .collect(),
    )
}

type Rows = Option<Vec<(String, Option<String>)>>;

fn rows(v: &[(&str, Option<&str>)]) -> Rows {
    Some(
        v.iter()
            .map(|(n, s)| (n.to_string(), s.map(String::from)))
            .collect(),
    )
}

/// Bir claude (argv kimlikli), bir codex ve öğrenilen kimlikli bir agy.
fn fleet() -> Fake {
    let f = Fake::new();
    f.add(
        10,
        "/bin/claude --remote-control cl --resume S1",
        &[],
        "/w/a",
    );
    f.add(11, "codex", &["COPS_NAME=cx"], "/w/b");
    f.add(12, "agy", &["COPS_NAME=ag"], "/w/proj");
    fs::write(&f.cfg.agy_cache, r#"{"/w/proj": " c1 "}"#).unwrap();
    f
}

#[test]
fn rows_are_name_and_sid_and_the_learned_agy_id_is_saved() {
    let _g = proc_guard();
    let f = fleet();
    let (store, sink) = (Mem::default(), Sink::default());
    let got = ProcScan::new(f.cfg.clone(), &store, &sink).live_sessions(false);
    assert_eq!(
        got,
        rows(&[("cl", Some("S1")), ("cx", None), ("ag", Some("c1"))])
    );
    assert_eq!(*store.doc.borrow(), Some(obj(&[("ag", "c1")])));
    assert_eq!((store.saves.get(), store.locks.get()), (1, 1));
    assert!(sink.events().is_empty());
    // Aynı değer zaten kayıtlı: kilit bile alınmaz (Python'un ucuz yolu).
    let again = ProcScan::new(f.cfg.clone(), &store, &sink).live_sessions(false);
    assert_eq!(again, got);
    assert_eq!((store.saves.get(), store.locks.get()), (1, 1));
    // spawn'ın gördüğü küme: kendisi hariç kimlikler ve adlar.
    let live = got.unwrap();
    let ls: Vec<LiveSession<'_>> = live
        .iter()
        .map(|(n, s)| LiveSession {
            name: n,
            sid: s.as_deref(),
        })
        .collect();
    let held: Vec<String> = ids_held_by_others("ag", Some(&ls)).into_iter().collect();
    assert_eq!(held, ["S1", "cl", "cx"]);
}

/// Kuru çalıştırma (Python `preview.active()`): sonuç aynı, `agy_sids`e hiçbir şey yazılmaz.
#[test]
fn preview_scan_writes_nothing() {
    let _g = proc_guard();
    let f = fleet();
    let (store, sink) = (Mem::default(), Sink::default());
    let got = ProcScan::new(f.cfg.clone(), &store, &sink).live_sessions(true);
    assert_eq!(
        got,
        rows(&[("cl", Some("S1")), ("cx", None), ("ag", Some("c1"))])
    );
    assert_eq!((store.saves.get(), store.locks.get()), (0, 0));
    assert_eq!(*store.doc.borrow(), None);
}

/// Python: `LockError` taramayı düşürmez, `agy_sids_lock_busy` (metin 200 karakter); yazım istisnası taramayı düşürür
/// (`_ids_held_by_others` boş küme).
#[test]
fn lock_failure_is_logged_but_a_save_failure_drops_the_scan() {
    let _g = proc_guard();
    let f = fleet();
    let sink = Sink::default();
    let busy = Mem {
        lock_err: Some("ğ".repeat(300)),
        ..Mem::default()
    };
    let got = ProcScan::new(f.cfg.clone(), &busy, &sink).live_sessions(false);
    assert_eq!(
        got,
        rows(&[("cl", Some("S1")), ("cx", None), ("ag", Some("c1"))])
    );
    let ev = sink.0.lock().unwrap().clone();
    assert_eq!(ev.len(), 1);
    assert_eq!(ev[0].event, "agy_sids_lock_busy");
    assert_eq!(ev[0].fields, vec![("error", json!("ğ".repeat(200)))]);
    let broken = Mem {
        save_err: Some("disk dolu".into()),
        ..Mem::default()
    };
    let sink2 = Sink::default();
    assert_eq!(
        ProcScan::new(f.cfg.clone(), &broken, &sink2).live_sessions(false),
        None
    );
    assert!(sink2.events().is_empty());
}

#[test]
fn unreadable_process_list_drops_the_scan_and_writes_nothing() {
    let _g = proc_guard();
    let f = fleet();
    let mut cfg = f.cfg.clone();
    cfg.proc_root = f.root.join("yok");
    let (store, sink) = (Mem::default(), Sink::default());
    assert_eq!(ProcScan::new(cfg, &store, &sink).live_sessions(false), None);
    assert_eq!((store.saves.get(), store.locks.get()), (0, 0));
    // Boş ama okunabilir liste "tarama düştü" DEĞİL.
    let empty = Fake::new();
    assert_eq!(
        ProcScan::new(empty.cfg.clone(), &store, &sink).live_sessions(false),
        Some(vec![])
    );
}

/// Gerçek yazım yolu: `DocAgySidStore` + dosya kipi (geçici `CLAUDEOPS_DIR`), Python ile aynı dosya ve kilit.
#[test]
fn learned_id_reaches_the_agy_sids_file() {
    let _g = proc_guard();
    let f = fleet();
    let state = f.root.join("state");
    fs::create_dir_all(&state).unwrap();
    let paths = Paths {
        claudeops_dir: state.to_str().unwrap().into(),
        home: f.root.join("home").to_str().unwrap().into(),
        repo_dir: f.root.join("repo").to_str().unwrap().into(),
    };
    let docs = StateDocs::isolated(StateDir::at(&paths.claudeops_dir), Some(Backend::Files), "");
    let store = DocAgySidStore::new(&paths, Arc::new(StateDocStore::new(Arc::new(docs))));
    fs::write(state.join("agy_sids.json"), r#"{"eski": "e1"}"#).unwrap();
    let sink = Sink::default();
    let got = ProcScan::new(f.cfg.clone(), &store, &sink).live_sessions(false);
    assert!(got.unwrap().contains(&("ag".into(), Some("c1".into()))));
    let saved: serde_json::Value =
        serde_json::from_slice(&fs::read(state.join("agy_sids.json")).unwrap()).unwrap();
    assert_eq!(saved, json!({"eski": "e1", "ag": "c1"}));
    assert!(sink.events().is_empty(), "{:?}", sink.events());
}

/// Gerçek `/proc` (yalnız okuma, kuru kip, geçici kökler): tarama düşmez ve uydurma satır yok.
#[test]
fn real_proc_scan_reads_without_side_effects() {
    let _g = proc_guard();
    let tmp = TempDir::new().unwrap();
    let paths = Paths {
        claudeops_dir: tmp.path().join("state").to_str().unwrap().into(),
        home: tmp.path().join("home").to_str().unwrap().into(),
        repo_dir: tmp.path().join("repo").to_str().unwrap().into(),
    };
    let cfg = scan_config(&paths);
    assert_eq!(cfg.proc_root, PathBuf::from("/proc"));
    assert_eq!(cfg.agy_sids, PathBuf::from(paths.agy_sids_json()));
    assert_eq!(
        cfg.agy_cache,
        PathBuf::from(paths.agy_conversations_cache())
    );
    let (store, sink) = (Mem::default(), Sink::default());
    let got = ProcScan::new(cfg, &store, &sink).live_sessions(true);
    assert!(got.is_some());
    assert_eq!((store.saves.get(), store.locks.get()), (0, 0));
    assert!(!tmp.path().join("state").exists() && !tmp.path().join("home").exists());
}
