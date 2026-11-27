//! Parite altyapısı: geçici kök (HOME, CLAUDEOPS_DIR, sahte PATH), Python alt süreci, dosya sistemi tabanlı `Probe`,
//! `Effect` uygulayıcı, dosya ağacı anlık görüntüsü ve karşılaştırma.
//!
//! Her vaka İKİ KEZ aynı başlangıç ağacından koşar: önce Python (alt süreç gerçek dosya yazar), ağacın görüntüsü alınır;
//! ağaç sıfırlanıp aynı fixture yeniden kurulur, Rust hesaplar, `Effect`ler uygulanır, görüntü alınır. İki görüntü,
//! dönüş değeri, istisna metni ve diag olayları birebir karşılaştırılır.

#![allow(dead_code)]

use cops_providers::cost::CostRefusal;
use cops_providers::real::docs::StateDocStore;
use cops_providers::real::effects::{self, EffectError};
use cops_providers::real::help::HelpCache;
use cops_providers::real::probe::{CostGate, ProjectDirs, SearchUrl};
use cops_providers::real::{Env as OsEnv, RealDeps, RealProbe};
use cops_providers::ucli::LiveModels;
use cops_providers::ucli_opts::Toolchain;
use cops_providers::{
    BuildOutput, Diag, Effect, McpRegisterError, ModelCatalog, Paths, Probe, Settings,
};
use cops_state::{Backend, StateDir, StateDocs};
use serde_json::{json, Map, Value};
use std::cell::RefCell;
use std::collections::BTreeMap;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::path::Path;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::Arc;
use tempfile::TempDir;

/// Maliyet defteri `ledger` ailesinde gerçek uygulamayla sınanır; öteki ailelerde kapı vaka olgusudur.
struct OpenGate;

impl CostGate for OpenGate {
    fn check_and_reserve(&self, _session: &str) -> Result<(), CostRefusal> {
        Ok(())
    }
    fn release(&self, _session: &str) {}
}

struct NoSearch;

impl SearchUrl for NoSearch {
    fn search_url(&self, _session: &str, _preview: bool) -> Option<String> {
        None
    }
}

pub fn repo_dir() -> String {
    let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
    fs::canonicalize(p).unwrap().to_string_lossy().into_owned()
}

/// Fixture girdisi (yol köke göreli).
#[derive(Clone, Debug)]
pub enum Fx {
    File(String, Vec<u8>, u32),
    Dir(String, u32),
    Link(String, String),
    /// Standart iskeletten bir yolu kaldır (ör. `home/.claude/claudeops` yokken).
    Remove(String),
}

pub fn file(rel: &str, content: &str, mode: u32) -> Fx {
    Fx::File(rel.into(), content.as_bytes().to_vec(), mode)
}

#[derive(Clone, Debug)]
pub struct Case {
    pub id: String,
    pub op: &'static str,
    pub args: Value,
    /// `CLAUDEOPS_DIR/settings.json` ham içeriği (None = dosya yok).
    pub settings: Option<String>,
    pub files: Vec<Fx>,
    pub env: Vec<(String, String)>,
    pub facts: Value,
    /// Bilinen, gerekçeli ayrışma: vaka FARKLI çıkmalı (eşit çıkarsa test düşer, kayıt kaldırılmalı). Rapor listesinde.
    pub known: Option<&'static str>,
}

impl Case {
    pub fn new(id: impl Into<String>, op: &'static str, args: Value) -> Self {
        Case {
            id: id.into(),
            op,
            args,
            settings: None,
            files: Vec::new(),
            env: Vec::new(),
            facts: json!({}),
            known: None,
        }
    }
    pub fn settings(mut self, s: impl Into<String>) -> Self {
        self.settings = Some(s.into());
        self
    }
    pub fn settings_json(self, v: Value) -> Self {
        self.settings(v.to_string())
    }
    pub fn file(mut self, f: Fx) -> Self {
        self.files.push(f);
        self
    }
    /// Varsayılan (canlı) örnek: ortak kök `home/.claude/claudeops` durum dizininin kendisi (bağlantı). Bu olmadan
    /// vaka "ikinci örnek"tir (`CLAUDEOPS_DIR` başka dizin; ortak anahtar ve günlük dosyaları salt okunur, TBD#412 b).
    pub fn default_instance(mut self) -> Self {
        let link = [
            Fx::Remove("home/.claude/claudeops".into()),
            Fx::Link("home/.claude/claudeops".into(), "../../state".into()),
        ];
        self.files.splice(0..0, link);
        self
    }
    pub fn env(mut self, k: &str, v: &str) -> Self {
        self.env.push((k.into(), v.into()));
        self
    }
    pub fn facts(mut self, v: Value) -> Self {
        if let (Value::Object(a), Value::Object(b)) = (&mut self.facts, v) {
            a.extend(b);
        }
        self
    }
    pub fn known(mut self, why: &'static str) -> Self {
        self.known = Some(why);
        self
    }
    pub fn known_if(self, cond: bool, why: &'static str) -> Self {
        if cond {
            self.known(why)
        } else {
            self
        }
    }
    pub fn fact(&self, k: &str) -> Option<&Value> {
        self.facts.get(k).filter(|v| !v.is_null())
    }
}

struct Py {
    child: Child,
    stdin: Option<ChildStdin>,
    stdout: BufReader<ChildStdout>,
}

impl Drop for Py {
    fn drop(&mut self) {
        // stdin kapanınca koşucu kendiliğinden çıkar (öldürme yok).
        drop(self.stdin.take());
        let _ = self.child.wait();
    }
}

/// `std_fixtures` ikililerinin içeriği ve izni.
const STUB: &[u8] = b"#!/bin/false\n";
const STUB_MODE: u32 = 0o755;

/// Çalıştırılacak dosyayı ALT SÜREÇ yazar. Aileler paralel koşar: testin kendisi yazma tanıtıcısı açsaydı başka iş
/// parçacığının o anki `fork`u tanıtıcıyı taşır ve betiğin `exec`i `ETXTBSY` alırdı (bir tarafta "bayrak yok" ya da
/// `ucli_mcp_register_failed`, yani rastgele parite farkı).
fn write_script(path: &str, content: &[u8]) {
    let mut child = Command::new("/bin/sh")
        .args(["-c", "cat > \"$1\"", "sh", path])
        .stdin(Stdio::piped())
        .spawn()
        .expect("sh çalıştırılamadı");
    child.stdin.take().unwrap().write_all(content).unwrap();
    assert!(child.wait().unwrap().success(), "betik yazılamadı: {path}");
}

pub struct Env {
    _tmp: TempDir,
    /// Kök DIŞINDA duran saplama ikili: her vakada yeniden yazılmaz, sert bağlanır.
    _stub_dir: TempDir,
    stub: String,
    pub root: String,
    pub home: String,
    pub state: String,
    pub bin: String,
    pub work: String,
    pub repo: String,
    py: Option<Py>,
}

impl Drop for Env {
    /// İzinsiz bırakılan fixture dizinleri geçici ağacın silinmesini engellemesin.
    fn drop(&mut self) {
        make_writable(Path::new(&self.root));
    }
}

impl Env {
    pub fn new() -> Env {
        Env::with_prefix("cops-parity-")
    }

    /// Kök dizin adı `prefix` ile başlar (HOME dahil tüm yollar onu içerir: kabuk tırnaklama vakaları).
    pub fn with_prefix(prefix: &str) -> Env {
        let tmp = tempfile::Builder::new().prefix(prefix).tempdir().unwrap();
        let root = fs::canonicalize(tmp.path())
            .unwrap()
            .to_string_lossy()
            .into_owned();
        let stub_dir = tempfile::Builder::new()
            .prefix("cops-parity-stub-")
            .tempdir()
            .unwrap();
        let stub = format!("{}/false", stub_dir.path().to_string_lossy());
        write_script(&stub, STUB);
        fs::set_permissions(&stub, fs::Permissions::from_mode(STUB_MODE)).unwrap();
        let mut e = Env {
            home: format!("{root}/home"),
            state: format!("{root}/state"),
            bin: format!("{root}/bin"),
            work: format!("{root}/work"),
            root,
            repo: repo_dir(),
            _tmp: tmp,
            _stub_dir: stub_dir,
            stub,
            py: None,
        };
        e.reset();
        let harness = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/parity/harness.py");
        let mut child = Command::new("/usr/bin/python3")
            .args(["-s", "-B", "-W", "ignore", harness])
            .env_clear()
            .env("HOME", &e.home)
            .env("CLAUDEOPS_DIR", &e.state)
            .env("PATH", &e.bin)
            .env("PYTHONPATH", format!("{}/py", e.repo))
            .env("CLAUDEOPS_EXTENSIONS", "0")
            .env("COPS_PARITY_ROOT", &e.root)
            .env("LANG", "C.UTF-8")
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .current_dir(&e.root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .expect("python3 çalıştırılamadı");
        let stdin = child.stdin.take();
        let stdout = BufReader::new(child.stdout.take().unwrap());
        e.py = Some(Py {
            child,
            stdin,
            stdout,
        });
        e
    }

    /// Ağacı boşalt ve standart iskeleti kur (dizinler 0755, sahte ikililer 0755).
    pub fn reset(&self) {
        for d in [&self.home, &self.state, &self.bin, &self.work] {
            if Path::new(d).exists() {
                make_writable(Path::new(d));
                fs::remove_dir_all(d).unwrap();
            }
            mkdir(d, 0o755);
        }
    }

    pub fn std_fixtures(&self) -> Vec<Fx> {
        let mut v = vec![
            Fx::Dir("home/.claude".into(), 0o755),
            Fx::Dir("home/.claude/claudeops".into(), 0o700),
        ];
        for b in ["claude", "codex", "agy", "copilot", "ucli"] {
            v.push(Fx::File(format!("bin/{b}"), STUB.to_vec(), STUB_MODE));
        }
        v.push(Fx::Dir("work/p1".into(), 0o755));
        v
    }

    pub fn apply_fixtures(&self, case: &Case) {
        let mut all = self.std_fixtures();
        all.extend(case.files.iter().cloned());
        if let Some(s) = &case.settings {
            all.push(Fx::File(
                "state/settings.json".into(),
                s.as_bytes().to_vec(),
                0o600,
            ));
        }
        for fx in all {
            match fx {
                Fx::Dir(rel, mode) => {
                    let p = format!("{}/{rel}", self.root);
                    fs::create_dir_all(&p).unwrap();
                    fs::set_permissions(&p, fs::Permissions::from_mode(mode)).unwrap();
                }
                Fx::File(rel, content, mode) => {
                    let p = format!("{}/{rel}", self.root);
                    fs::create_dir_all(Path::new(&p).parent().unwrap()).unwrap();
                    // önceki dosya (saplamaya sert bağ olabilir) üstüne yazılmaz, yenisi açılır
                    let _ = fs::remove_file(&p);
                    if content == STUB && mode == STUB_MODE {
                        fs::hard_link(&self.stub, &p).unwrap();
                    } else if mode & 0o111 != 0 {
                        write_script(&p, &content);
                    } else {
                        fs::write(&p, content).unwrap();
                    }
                    fs::set_permissions(&p, fs::Permissions::from_mode(mode)).unwrap();
                }
                Fx::Remove(rel) => {
                    let p = format!("{}/{rel}", self.root);
                    if Path::new(&p).is_dir() {
                        fs::remove_dir_all(&p).unwrap();
                    } else {
                        let _ = fs::remove_file(&p);
                    }
                }
                Fx::Link(rel, target) => {
                    let p = format!("{}/{rel}", self.root);
                    fs::create_dir_all(Path::new(&p).parent().unwrap()).unwrap();
                    let _ = fs::remove_file(&p);
                    std::os::unix::fs::symlink(target, &p).unwrap();
                }
            }
        }
    }

    pub fn py_call(&mut self, case: &Case) -> Value {
        let msg = json!({
            "id": case.id, "op": case.op, "args": case.args, "facts": case.facts,
            "env": case.env.iter().map(|(k, v)| json!([k, v])).collect::<Vec<_>>(),
        });
        let py = self.py.as_mut().unwrap();
        let stdin = py.stdin.as_mut().unwrap();
        writeln!(stdin, "{msg}").unwrap();
        stdin.flush().unwrap();
        let mut line = String::new();
        py.stdout.read_line(&mut line).unwrap();
        assert!(
            !line.is_empty(),
            "python koşucusu yanıt vermedi (vaka {})",
            case.id
        );
        serde_json::from_str(&line)
            .unwrap_or_else(|e| panic!("python çıktısı JSON değil ({e}): {line}"))
    }

    /// Kök altındaki ağacın görüntüsü: yol -> tür/izin/içerik.
    pub fn snapshot(&self) -> BTreeMap<String, String> {
        let mut out = BTreeMap::new();
        walk(Path::new(&self.root), &self.root, &mut out);
        out
    }

    pub fn paths(&self) -> Paths {
        Paths {
            claudeops_dir: self.state.clone(),
            home: self.home.clone(),
            repo_dir: self.repo.clone(),
        }
    }

    pub fn settings(&self) -> Settings {
        match fs::read(format!("{}/settings.json", self.state)) {
            Ok(b) => Settings::from_json(&String::from_utf8(b).expect("settings.json UTF-8 değil")),
            Err(_) => Settings::default(),
        }
    }

    pub fn catalog(&self, case: &Case) -> ModelCatalog {
        let parse = |p: String| {
            fs::read_to_string(p)
                .ok()
                .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        };
        let live = case.fact("ucli_live");
        let ids = live
            .and_then(|l| l.get("ids"))
            .and_then(Value::as_array)
            .map(|a| {
                a.iter()
                    .filter_map(|x| x.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();
        let caps = live
            .and_then(|l| l.get("caps"))
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        ModelCatalog {
            claude_state: parse(format!("{}/claude_models.json", self.state)),
            agy_models: strs(case.fact("agy_models")),
            codex_cache: parse(format!("{}/.codex/models_cache.json", self.home)),
            codex_choices: None,
            ucli: LiveModels { ids, caps },
        }
    }
}

pub fn strs(v: Option<&Value>) -> Vec<String> {
    v.and_then(Value::as_array)
        .map(|a| a.iter().map(|x| x.as_str().unwrap().to_string()).collect())
        .unwrap_or_default()
}

fn mkdir(p: &str, mode: u32) {
    fs::DirBuilder::new()
        .recursive(true)
        .mode(mode)
        .create(p)
        .unwrap();
    fs::set_permissions(p, fs::Permissions::from_mode(mode)).unwrap();
}

fn make_writable(p: &Path) {
    if let Ok(m) = fs::symlink_metadata(p) {
        if m.is_dir() {
            let _ = fs::set_permissions(p, fs::Permissions::from_mode(0o755));
            if let Ok(rd) = fs::read_dir(p) {
                for ent in rd.flatten() {
                    make_writable(&ent.path());
                }
            }
        }
    }
}

fn walk(p: &Path, root: &str, out: &mut BTreeMap<String, String>) {
    let Ok(rd) = fs::read_dir(p) else { return };
    for ent in rd.flatten() {
        let path = ent.path();
        let rel = path
            .to_string_lossy()
            .strip_prefix(root)
            .unwrap_or("")
            .to_string();
        let m = fs::symlink_metadata(&path).unwrap();
        let mode = m.permissions().mode() & 0o7777;
        if m.file_type().is_symlink() {
            out.insert(
                rel,
                format!(
                    "link -> {}",
                    fs::read_link(&path).unwrap().to_string_lossy()
                ),
            );
        } else if m.is_dir() {
            out.insert(rel, format!("dir {mode:o}"));
            walk(&path, root, out);
        } else {
            // izinsiz bırakılan fixture (okuma hatası vakaları) iki görüntüde de aynı işaretle geçer
            let content = fs::read(&path).unwrap_or_else(|_| b"<okunamaz>".to_vec());
            out.insert(
                rel,
                format!("file {mode:o} {:?}", String::from_utf8_lossy(&content)),
            );
        }
    }
}

// ------------------------------------------------------------------------------------------------------------- Probe

/// Python `claude_provider._encode_cwd` (gerçek karşılığı rs/proc `transcript.rs::encode_cwd`).
pub fn encode_cwd(cwd: &str) -> String {
    cwd.chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
        .collect()
}

pub struct TestProjects(pub String);

impl ProjectDirs for TestProjects {
    fn claude_project_dir(&self, cwd: &str) -> String {
        format!("{}/.claude/projects/{}", self.0, encode_cwd(cwd))
    }
}

/// Koşucu Python'unun ortamı: taban + vakanın değişkenleri.
pub fn case_env(e: &Env, case: &Case) -> OsEnv {
    let mut vars = vec![
        ("HOME".to_string(), e.home.clone()),
        ("CLAUDEOPS_DIR".to_string(), e.state.clone()),
        ("PATH".to_string(), e.bin.clone()),
        ("CLAUDEOPS_STORE_BACKEND".to_string(), "files".to_string()),
    ];
    vars.extend(case.env.iter().cloned());
    OsEnv::fixed(vars)
}

/// Dosya kipinde gerçek belge deposu (geçici durum dizini; süreç ortamı okunmaz).
pub fn file_docs(paths: &Paths) -> Arc<StateDocStore> {
    let dir = StateDir::at(&paths.claudeops_dir);
    let docs = StateDocs::isolated(dir, Some(Backend::Files), "");
    Arc::new(StateDocStore::new(Arc::new(docs)))
}

/// Geçici ağaç üzerinde GERÇEK uygulayıcı.
pub fn real_probe(e: &Env, case: &Case) -> RealProbe {
    real_probe_at(e, case, e.paths())
}

/// [`real_probe`], başka yollarla (ör. `repo_dir` ağaca çevrilmiş).
pub fn real_probe_at(e: &Env, case: &Case, paths: Paths) -> RealProbe {
    probe_over(e, case, paths, HelpCache::default())
}

/// [`real_probe`], verilen `--help` önbelleğiyle.
pub fn real_probe_with_help(e: &Env, case: &Case, help: HelpCache) -> RealProbe {
    probe_over(e, case, e.paths(), help)
}

fn probe_over(e: &Env, case: &Case, paths: Paths, help: HelpCache) -> RealProbe {
    let env = case_env(e, case);
    let deps = RealDeps {
        docs: file_docs(&paths),
        projects: Arc::new(TestProjects(e.home.clone())),
        cost: Arc::new(OpenGate),
        search: Arc::new(NoSearch),
        help: Arc::new(help),
        panel_port: None,
    };
    RealProbe::new(paths, env, deps).with_cwd(e.root.clone())
}

/// Dosya sistemi olguları GERÇEK uygulayıcıdan ([`RealProbe`]; parite onu da sınar); süreç/ağ olguları vakanın
/// `facts`ından (Python'da aynı sahte değerler).
pub struct FsProbe<'a> {
    pub e: &'a Env,
    pub case: &'a Case,
    pub real: RealProbe,
    pub mcp_calls: RefCell<Vec<Vec<String>>>,
}

impl<'a> FsProbe<'a> {
    pub fn new(e: &'a Env, case: &'a Case) -> Self {
        FsProbe {
            e,
            case,
            real: real_probe(e, case),
            mcp_calls: RefCell::new(Vec::new()),
        }
    }
}

impl Probe for FsProbe<'_> {
    fn is_file(&self, path: &str) -> bool {
        self.real.is_file(path)
    }
    fn is_dir(&self, path: &str) -> bool {
        self.real.is_dir(path)
    }
    fn exists(&self, path: &str) -> bool {
        self.real.exists(path)
    }
    fn is_symlink(&self, path: &str) -> bool {
        self.real.is_symlink(path)
    }
    fn is_executable_file(&self, path: &str) -> bool {
        self.real.is_executable_file(path)
    }
    fn file_size(&self, path: &str) -> Option<u64> {
        self.real.file_size(path)
    }
    fn read_text(&self, path: &str) -> Option<String> {
        self.real.read_text(path)
    }
    fn realpath(&self, path: &str) -> String {
        self.real.realpath(path)
    }
    fn which(&self, name: &str) -> Option<String> {
        self.real.which(name)
    }
    fn env_var(&self, name: &str) -> Option<String> {
        self.case
            .env
            .iter()
            .rev()
            .find(|(k, _)| k == name)
            .map(|(_, v)| v.clone())
    }
    fn claude_help(&self, binary: &str) -> String {
        if fs::metadata(binary).is_err() {
            return String::new();
        }
        self.case
            .fact("claude_help")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string()
    }
    fn ucli_chat_help(&self, binary: &str) -> String {
        if fs::metadata(binary).is_err() {
            return String::new();
        }
        self.case
            .fact("ucli_help")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string()
    }
    fn path_executables(&self) -> Vec<String> {
        strs(self.case.fact("path_executables"))
    }
    fn rust_toolchain(&self) -> Result<Toolchain, String> {
        match self.case.fact("toolchain") {
            Some(Value::Object(t)) => {
                let g = |k: &str| t.get(k).and_then(Value::as_str).unwrap_or("").to_string();
                Ok(Toolchain {
                    root: g("root"),
                    cargo: g("cargo"),
                    rustc: g("rustc"),
                    registry: g("registry"),
                    git: g("git"),
                    rustup_home: g("rustup_home"),
                    cargo_home: g("cargo_home"),
                })
            }
            Some(Value::String(s)) if !s.is_empty() => Err(s.clone()),
            _ => Err("Rust araç zinciri bulunamadı: <sahte>".into()),
        }
    }
    fn searxng_url(&self, _session: &str, _preview: bool) -> Option<String> {
        self.case
            .fact("searxng_url")
            .and_then(Value::as_str)
            .map(String::from)
    }
    fn checks_registry(&self, _path: &str) -> Result<(), String> {
        match self.case.fact("checks_err").and_then(Value::as_str) {
            Some(e) if !e.is_empty() => Err(e.into()),
            _ => Ok(()),
        }
    }
    fn claude_cost_gate(&self, _session: &str) -> Result<(), CostRefusal> {
        if self
            .case
            .fact("cost_exceeded")
            .is_some_and(|v| v.as_bool() == Some(true))
        {
            Err(CostRefusal::CapExceeded {
                today_usd: 1.5,
                cap_usd: 1.0,
            })
        } else {
            Ok(())
        }
    }
    fn issue_agent_token(&self, _session: &str) -> Result<String, String> {
        let t = self.case.fact("agent_token");
        if t.and_then(|t| t.get("error")).is_some() {
            return Err("OSError".into());
        }
        Ok(t.and_then(|t| t.get("path"))
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string())
    }
    fn panel_port(&self) -> Option<u16> {
        self.case
            .fact("panel_port")
            .and_then(Value::as_u64)
            .map(|p| p as u16)
    }
    fn register_mcp(
        &self,
        _cwd: &str,
        config_path: &str,
        argv: &[String],
    ) -> Result<bool, McpRegisterError> {
        if fs::symlink_metadata(config_path).is_ok() {
            fs::remove_file(config_path).map_err(|e| McpRegisterError::Unlink(format!("{e:?}")))?;
        }
        self.mcp_calls.borrow_mut().push(argv.to_vec());
        let r = self.case.fact("mcp_register");
        if let Some(msg) = r.and_then(|r| r.get("raise")).and_then(Value::as_str) {
            return Err(McpRegisterError::Spawn(format!("OSError('{msg}')")));
        }
        let rc = r
            .and_then(|r| r.get("rc"))
            .and_then(Value::as_i64)
            .unwrap_or(0) as i32;
        if rc != 0 {
            let s = |k: &str| {
                r.and_then(|r| r.get(k))
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string()
            };
            return Err(McpRegisterError::Exit {
                rc,
                stdout: s("stdout"),
                stderr: s("stderr"),
            });
        }
        Ok(false)
    }
    fn apply_now(&self, effect: &Effect) -> Result<(), EffectError> {
        effects::apply(effect)
    }
}

// ------------------------------------------------------------------------------------------------------ karşılaştırma

/// Rust tarafının bir vakadaki çıktısı.
#[derive(Default)]
pub struct RsOut {
    pub ret: Value,
    /// SpawnError metni.
    pub exc: Option<String>,
    pub out: BuildOutput,
    /// Rust'ın diag olayları dışında ürettiği (BuildOutput'a girmeyen) olaylar.
    pub extra_diags: Vec<Diag>,
    pub popen: Vec<Value>,
    /// `Effect` uygulanmadan önce kontrol edilen ret: true ise effect'ler uygulanmaz.
    pub skip_effects: bool,
    pub mcp_calls: Vec<Vec<String>>,
}

impl RsOut {
    pub fn ret(v: Value) -> RsOut {
        RsOut {
            ret: v,
            ..Default::default()
        }
    }
}

pub fn diag_json(d: &Diag) -> Value {
    json!([
        d.event,
        d.fields
            .iter()
            .map(|(k, v)| json!([k, v]))
            .collect::<Vec<_>>()
    ])
}

/// Python `_jsonable` biçimi: sonlu olmayan float `{"$float": ...}`.
pub fn fjson(f: f64) -> Value {
    if f.is_nan() {
        json!({"$float": "nan"})
    } else if f.is_infinite() {
        json!({"$float": if f > 0.0 { "inf" } else { "-inf" }})
    } else {
        json!(f)
    }
}

/// Sayı eşitliği tipten bağımsız (Python `8.0` ile JSON `8` aynı değer değildir: tip de korunur). Burada serde_json
/// `Value` eşitliği kullanılır: `1` (int) ile `1.0` (float) FARKLIDIR, bu bilinçli.
pub fn same(a: &Value, b: &Value) -> bool {
    a == b
}

/// En derin farklı alt değerleri listeler (en çok 12).
pub fn json_diff(path: &str, a: &Value, b: &Value, out: &mut Vec<String>) {
    if a == b || out.len() >= 12 {
        return;
    }
    match (a, b) {
        (Value::Object(x), Value::Object(y)) => {
            let keys: std::collections::BTreeSet<&String> = x.keys().chain(y.keys()).collect();
            for k in keys {
                json_diff(
                    &format!("{path}.{k}"),
                    x.get(k).unwrap_or(&Value::Null),
                    y.get(k).unwrap_or(&Value::Null),
                    out,
                );
            }
        }
        (Value::Array(x), Value::Array(y)) if x.len() == y.len() => {
            for (i, (p, q)) in x.iter().zip(y).enumerate() {
                json_diff(&format!("{path}[{i}]"), p, q, out);
            }
        }
        _ => out.push(format!("{path}\n    py: {a}\n    rs: {b}")),
    }
}

pub struct Runner {
    pub e: Env,
    pub known: Vec<String>,
    pub fails: Vec<String>,
    pub count: usize,
}

impl Runner {
    pub fn new() -> Runner {
        Runner::with_env(Env::new())
    }

    pub fn with_env(e: Env) -> Runner {
        Runner {
            e,
            known: Vec::new(),
            fails: Vec::new(),
            count: 0,
        }
    }

    /// Python `diags` içinden Rust kapsamı DIŞINDAKİ olayları atar (yalnız `spawn` başlatma kısmının olayları, bkz. çağıran).
    pub fn run<F>(&mut self, cases: Vec<Case>, drop_events: &[&str], rust: F)
    where
        F: Fn(&Env, &Case) -> RsOut,
    {
        self.run_prepared(cases, drop_events, |_, _| {}, rust)
    }

    /// [`Runner::run`] + her tarafta fixture kurulduktan sonra `prepare` (ör. dosya zamanları).
    pub fn run_prepared<P, F>(
        &mut self,
        cases: Vec<Case>,
        drop_events: &[&str],
        prepare: P,
        rust: F,
    ) where
        P: Fn(&Env, &Case),
        F: Fn(&Env, &Case) -> RsOut,
    {
        for case in cases {
            self.count += 1;
            self.e.reset();
            self.e.apply_fixtures(&case);
            prepare(&self.e, &case);
            let py = self.e.py_call(&case);
            let snap_py = self.e.snapshot();
            if std::env::var("COPS_PARITY_DUMP").is_ok_and(|d| case.id.contains(&d)) {
                eprintln!("DUMP [{}] py: {py}\n  dosyalar: {snap_py:?}", case.id);
            }
            self.e.reset();
            self.e.apply_fixtures(&case);
            prepare(&self.e, &case);
            let mut rs = rust(&self.e, &case);
            // GERÇEK uygulayıcı: dosya ağacı karşılaştırması onu da sınar
            let apply_err = if rs.skip_effects {
                Ok(())
            } else {
                effects::apply_all(&rs.out.effects)
            };
            let snap_rs = self.e.snapshot();
            self.compare(
                &case,
                &py,
                &mut rs,
                apply_err,
                &snap_py,
                &snap_rs,
                drop_events,
            );
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn compare(
        &mut self,
        case: &Case,
        py: &Value,
        rs: &mut RsOut,
        apply_err: Result<(), EffectError>,
        snap_py: &BTreeMap<String, String>,
        snap_rs: &BTreeMap<String, String>,
        drop_events: &[&str],
    ) {
        let mut diffs: Vec<String> = Vec::new();
        let pexc = py.get("exc").filter(|v| !v.is_null());
        match (pexc, &rs.exc, &apply_err) {
            (None, None, Ok(())) => {
                if !same(&py["ret"], &rs.ret) {
                    let mut d = Vec::new();
                    json_diff("ret", &py["ret"], &rs.ret, &mut d);
                    diffs.extend(d);
                }
            }
            (Some(p), _, Err(_)) if p[2] == json!(true) => {} // ikisi de OS hatası (metin uygulayıcıya ait)
            (Some(p), Some(r), Ok(())) if p[1].as_str() == Some(r.as_str()) => {}
            (p, r, a) => diffs.push(format!(
                "istisna\n    py: {}\n    rs: {:?} / uygulama: {:?}\n    py ret: {}\n    rs ret: {}",
                p.map_or("-".into(), |v| v.to_string()),
                r,
                a.as_ref().err(),
                py["ret"],
                rs.ret
            )),
        }
        let pd: Vec<Value> = py["diags"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|d| !drop_events.contains(&d[0].as_str().unwrap()))
            .cloned()
            .collect();
        let rd: Vec<Value> = rs
            .out
            .diags
            .iter()
            .chain(rs.extra_diags.iter())
            .map(diag_json)
            .collect();
        if pd != rd {
            diffs.push(format!(
                "diag\n    py: {}\n    rs: {}",
                Value::from(pd),
                Value::from(rd)
            ));
        }
        let pm: Vec<Value> = py["run"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|a| {
                a.get(3).and_then(Value::as_str) == Some("mcp")
                    && a.get(4).and_then(Value::as_str) == Some("add")
            })
            .cloned()
            .collect();
        let rm: Vec<Value> = rs.mcp_calls.iter().map(|a| json!(a)).collect();
        if pm != rm {
            diffs.push(format!(
                "mcp add argv\n    py: {}\n    rs: {}",
                Value::from(pm),
                Value::from(rm)
            ));
        }
        if py["popen"].as_array().unwrap() != &rs.popen {
            diffs.push(format!(
                "popen\n    py: {}\n    rs: {}",
                py["popen"],
                Value::from(rs.popen.clone())
            ));
        }
        if snap_py != snap_rs {
            let keys: std::collections::BTreeSet<&String> =
                snap_py.keys().chain(snap_rs.keys()).collect();
            for k in keys {
                let (a, b) = (snap_py.get(k), snap_rs.get(k));
                if a != b {
                    diffs.push(format!("dosya {k}\n    py: {a:?}\n    rs: {b:?}"));
                }
            }
        }
        if let Some(why) = case.known {
            if diffs.is_empty() {
                self.fails.push(format!(
                    "[{}] bilinen ayrışma kaydı var ama çıktılar EŞİT: kaydı kaldır ({why})",
                    case.id
                ));
            } else {
                self.known.push(format!("[{}] {why}", case.id));
            }
            return;
        }
        if !diffs.is_empty() {
            self.fails.push(format!(
                "[{}] {} {}\n  {}",
                case.id,
                case.op,
                case.args,
                diffs.join("\n  ")
            ));
        }
    }

    pub fn finish(self, family: &str) {
        if !self.fails.is_empty() {
            panic!(
                "{family}: {} / {} vakada fark\n\n{}",
                self.fails.len(),
                self.count,
                self.fails.join("\n\n")
            );
        }
        eprintln!(
            "{family}: {} vaka; bilinen ayrışma {}:",
            self.count,
            self.known.len()
        );
        for k in &self.known {
            eprintln!("  {k}");
        }
    }
}

pub fn map(v: Value) -> Map<String, Value> {
    v.as_object().cloned().unwrap_or_default()
}

/// Toplayan `DiagSink` (G9: `sync_one`, spawn yürütücüsü, bekçi).
#[derive(Default)]
pub struct VecSink(pub std::sync::Mutex<Vec<Diag>>);

impl VecSink {
    pub fn take(&self) -> Vec<Diag> {
        std::mem::take(&mut *self.0.lock().unwrap())
    }
}

impl cops_providers::spawn_exec::DiagSink for VecSink {
    fn log(&self, diag: &Diag) {
        self.0.lock().unwrap().push(diag.clone());
    }
}
