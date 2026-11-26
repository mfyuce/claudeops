//! Parite altyapısı: geçici kök (HOME, CLAUDEOPS_DIR, sahte PATH), Python alt süreci, dosya sistemi tabanlı `Probe`,
//! `Effect` uygulayıcı, dosya ağacı anlık görüntüsü ve karşılaştırma.
//!
//! Her vaka İKİ KEZ aynı başlangıç ağacından koşar: önce Python (alt süreç gerçek dosya yazar), ağacın görüntüsü alınır;
//! ağaç sıfırlanıp aynı fixture yeniden kurulur, Rust hesaplar, `Effect`ler uygulanır, görüntü alınır. İki görüntü,
//! dönüş değeri, istisna metni ve diag olayları birebir karşılaştırılır.

#![allow(dead_code)]

use cops_providers::ucli::LiveModels;
use cops_providers::ucli_opts::Toolchain;
use cops_providers::{BuildOutput, Diag, Effect, McpRegisterError, ModelCatalog, Paths, Probe, Settings};
use serde_json::{json, Map, Value};
use std::cell::RefCell;
use std::collections::BTreeMap;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt};
use std::path::Path;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use tempfile::TempDir;

const O_NOFOLLOW: i32 = 0o400000; // Linux
pub const COST_CAP_MSG: &str =
    "claude: günlük USD tavanı aşıldı (1.50 / 1.00); Ayarlar'dan ucli_cost.daily_cap_usd yükselt ya da yarın dene";

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
        Case { id: id.into(), op, args, settings: None, files: Vec::new(), env: Vec::new(), facts: json!({}), known: None }
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

pub struct Env {
    _tmp: TempDir,
    pub root: String,
    pub home: String,
    pub state: String,
    pub bin: String,
    pub work: String,
    pub repo: String,
    py: Option<Py>,
}

impl Env {
    pub fn new() -> Env {
        Env::with_prefix("cops-parity-")
    }

    /// Kök dizin adı `prefix` ile başlar (HOME dahil tüm yollar onu içerir: kabuk tırnaklama vakaları).
    pub fn with_prefix(prefix: &str) -> Env {
        let tmp = tempfile::Builder::new().prefix(prefix).tempdir().unwrap();
        let root = fs::canonicalize(tmp.path()).unwrap().to_string_lossy().into_owned();
        let mut e = Env {
            home: format!("{root}/home"),
            state: format!("{root}/state"),
            bin: format!("{root}/bin"),
            work: format!("{root}/work"),
            root,
            repo: repo_dir(),
            _tmp: tmp,
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
        e.py = Some(Py { child, stdin, stdout });
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
        let mut v = vec![Fx::Dir("home/.claude".into(), 0o755), Fx::Dir("home/.claude/claudeops".into(), 0o700)];
        for b in ["claude", "codex", "agy", "copilot", "ucli"] {
            v.push(Fx::File(format!("bin/{b}"), b"#!/bin/false\n".to_vec(), 0o755));
        }
        v.push(Fx::Dir("work/p1".into(), 0o755));
        v
    }

    pub fn apply_fixtures(&self, case: &Case) {
        let mut all = self.std_fixtures();
        all.extend(case.files.iter().cloned());
        if let Some(s) = &case.settings {
            all.push(Fx::File("state/settings.json".into(), s.as_bytes().to_vec(), 0o600));
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
                    fs::write(&p, content).unwrap();
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
        assert!(!line.is_empty(), "python koşucusu yanıt vermedi (vaka {})", case.id);
        serde_json::from_str(&line).unwrap_or_else(|e| panic!("python çıktısı JSON değil ({e}): {line}"))
    }

    /// Kök altındaki ağacın görüntüsü: yol -> tür/izin/içerik.
    pub fn snapshot(&self) -> BTreeMap<String, String> {
        let mut out = BTreeMap::new();
        walk(Path::new(&self.root), &self.root, &mut out);
        out
    }

    pub fn paths(&self) -> Paths {
        Paths { claudeops_dir: self.state.clone(), home: self.home.clone(), repo_dir: self.repo.clone() }
    }

    pub fn settings(&self) -> Settings {
        match fs::read(format!("{}/settings.json", self.state)) {
            Ok(b) => Settings::from_json(&String::from_utf8(b).expect("settings.json UTF-8 değil")),
            Err(_) => Settings::default(),
        }
    }

    pub fn catalog(&self, case: &Case) -> ModelCatalog {
        let parse = |p: String| fs::read_to_string(p).ok().and_then(|t| serde_json::from_str::<Value>(&t).ok());
        let live = case.fact("ucli_live");
        let ids = live
            .and_then(|l| l.get("ids"))
            .and_then(Value::as_array)
            .map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect())
            .unwrap_or_default();
        let caps = live.and_then(|l| l.get("caps")).and_then(Value::as_object).cloned().unwrap_or_default();
        ModelCatalog {
            claude_state: parse(format!("{}/claude_models.json", self.state)),
            agy_models: strs(case.fact("agy_models")),
            codex_cache: parse(format!("{}/.codex/models_cache.json", self.home)),
            ucli: LiveModels { ids, caps },
        }
    }
}

pub fn strs(v: Option<&Value>) -> Vec<String> {
    v.and_then(Value::as_array).map(|a| a.iter().map(|x| x.as_str().unwrap().to_string()).collect()).unwrap_or_default()
}

fn mkdir(p: &str, mode: u32) {
    fs::DirBuilder::new().recursive(true).mode(mode).create(p).unwrap();
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
        let rel = path.to_string_lossy().strip_prefix(root).unwrap_or("").to_string();
        let m = fs::symlink_metadata(&path).unwrap();
        let mode = m.permissions().mode() & 0o7777;
        if m.file_type().is_symlink() {
            out.insert(rel, format!("link -> {}", fs::read_link(&path).unwrap().to_string_lossy()));
        } else if m.is_dir() {
            out.insert(rel, format!("dir {mode:o}"));
            walk(&path, root, out);
        } else {
            let content = fs::read(&path).unwrap();
            out.insert(rel, format!("file {mode:o} {:?}", String::from_utf8_lossy(&content)));
        }
    }
}

// ------------------------------------------------------------------------------------------------------------- Probe

/// Dosya sistemi olguları gerçek geçici ağaçtan; süreç/ağ olguları vakanın `facts`ından (Python'da aynı sahte değerler).
pub struct FsProbe<'a> {
    pub e: &'a Env,
    pub case: &'a Case,
    pub mcp_calls: RefCell<Vec<Vec<String>>>,
}

impl<'a> FsProbe<'a> {
    pub fn new(e: &'a Env, case: &'a Case) -> Self {
        FsProbe { e, case, mcp_calls: RefCell::new(Vec::new()) }
    }

    fn path_env(&self) -> String {
        self.case.env.iter().rev().find(|(k, _)| k == "PATH").map_or(self.e.bin.clone(), |(_, v)| v.clone())
    }
}

fn is_exec(p: &str) -> bool {
    fs::metadata(p).is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o100 != 0)
}

/// `posixpath.realpath(path, strict=False)`.
pub fn py_realpath(path: &str, cwd: &str) -> String {
    let abs = if path.starts_with('/') { path.to_string() } else { format!("{cwd}/{path}") };
    let mut seen = 0;
    resolve("/", &abs, &mut seen)
}

fn resolve(base: &str, rest: &str, depth: &mut u32) -> String {
    let mut cur = base.to_string();
    for name in rest.split('/') {
        if name.is_empty() || name == "." {
            continue;
        }
        if name == ".." {
            cur = match cur.rfind('/') {
                Some(0) | None => "/".into(),
                Some(i) => cur[..i].into(),
            };
            continue;
        }
        let next = if cur == "/" { format!("/{name}") } else { format!("{cur}/{name}") };
        match fs::read_link(&next) {
            Ok(t) if *depth < 40 => {
                *depth += 1;
                let t = t.to_string_lossy().into_owned();
                cur = if t.starts_with('/') { resolve("/", &t, depth) } else { resolve(&cur, &t, depth) };
            }
            _ => cur = next,
        }
    }
    cur
}

impl Probe for FsProbe<'_> {
    fn is_file(&self, path: &str) -> bool {
        Path::new(path).is_file()
    }
    fn is_dir(&self, path: &str) -> bool {
        Path::new(path).is_dir()
    }
    fn exists(&self, path: &str) -> bool {
        Path::new(path).exists()
    }
    fn is_symlink(&self, path: &str) -> bool {
        fs::symlink_metadata(path).is_ok_and(|m| m.file_type().is_symlink())
    }
    fn is_executable_file(&self, path: &str) -> bool {
        is_exec(path)
    }
    fn file_size(&self, path: &str) -> Option<u64> {
        fs::metadata(path).ok().map(|m| m.len())
    }
    fn read_text(&self, path: &str) -> Option<String> {
        // Python metin kipi: evrensel satır sonu (`\r\n` ve `\r` -> `\n`).
        let s = String::from_utf8(fs::read(path).ok()?).ok()?;
        Some(s.replace("\r\n", "\n").replace('\r', "\n"))
    }
    fn realpath(&self, path: &str) -> String {
        py_realpath(path, &self.e.root)
    }
    fn which(&self, name: &str) -> Option<String> {
        if name.contains('/') {
            return (is_exec(name) && !Path::new(name).is_dir()).then(|| name.to_string());
        }
        if name.is_empty() {
            return None;
        }
        self.path_env().split(':').filter(|d| !d.is_empty()).map(|d| format!("{d}/{name}")).find(|p| is_exec(p))
    }
    fn env_var(&self, name: &str) -> Option<String> {
        self.case.env.iter().rev().find(|(k, _)| k == name).map(|(_, v)| v.clone())
    }
    fn claude_help(&self, binary: &str) -> String {
        if fs::metadata(binary).is_err() {
            return String::new();
        }
        self.case.fact("claude_help").and_then(Value::as_str).unwrap_or("").to_string()
    }
    fn ucli_chat_help(&self, binary: &str) -> String {
        if fs::metadata(binary).is_err() {
            return String::new();
        }
        self.case.fact("ucli_help").and_then(Value::as_str).unwrap_or("").to_string()
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
        self.case.fact("searxng_url").and_then(Value::as_str).map(String::from)
    }
    fn checks_registry(&self, _path: &str) -> Result<(), String> {
        match self.case.fact("checks_err").and_then(Value::as_str) {
            Some(e) if !e.is_empty() => Err(e.into()),
            _ => Ok(()),
        }
    }
    fn claude_cost_gate(&self, _session: &str) -> Result<(), String> {
        if self.case.fact("cost_exceeded").is_some_and(|v| v.as_bool() == Some(true)) {
            Err(COST_CAP_MSG.into())
        } else {
            Ok(())
        }
    }
    fn issue_agent_token(&self, _session: &str) -> Result<String, String> {
        let t = self.case.fact("agent_token");
        if t.and_then(|t| t.get("error")).is_some() {
            return Err("OSError".into());
        }
        Ok(t.and_then(|t| t.get("path")).and_then(Value::as_str).unwrap_or("").to_string())
    }
    fn panel_port(&self) -> Option<u16> {
        self.case.fact("panel_port").and_then(Value::as_u64).map(|p| p as u16)
    }
    fn register_mcp(&self, _cwd: &str, config_path: &str, argv: &[String]) -> Result<(), McpRegisterError> {
        if fs::symlink_metadata(config_path).is_ok() {
            fs::remove_file(config_path).map_err(|e| McpRegisterError::Unlink(format!("{e:?}")))?;
        }
        self.mcp_calls.borrow_mut().push(argv.to_vec());
        let r = self.case.fact("mcp_register");
        if let Some(msg) = r.and_then(|r| r.get("raise")).and_then(Value::as_str) {
            return Err(McpRegisterError::Spawn(format!("OSError('{msg}')")));
        }
        let rc = r.and_then(|r| r.get("rc")).and_then(Value::as_i64).unwrap_or(0) as i32;
        if rc != 0 {
            let s = |k: &str| r.and_then(|r| r.get(k)).and_then(Value::as_str).unwrap_or("").to_string();
            return Err(McpRegisterError::Exit { rc, stdout: s("stdout"), stderr: s("stderr") });
        }
        Ok(())
    }
}

// ----------------------------------------------------------------------------------------------------- Effect uygulama

/// `Effect` sözleşmesini (bkz. crate belgesi) Python'un yazım yardımcılarıyla aynı anlamda uygular.
pub fn apply_effects(effects: &[Effect]) -> std::io::Result<()> {
    for ef in effects {
        match ef {
            Effect::WriteSecret { path, content } => write_private(path, content.as_bytes())?,
            Effect::Touch { path } => write_private(path, b"")?,
            Effect::Remove { path } => {
                let _ = fs::remove_file(path);
            }
            Effect::MkdirPrivate { path } => {
                // `os.makedirs(mode=0o700, exist_ok=True)`: ara dizinler varsayılan izinle, son dizin 0700 & ~umask.
                if let Some(parent) = Path::new(path).parent() {
                    fs::create_dir_all(parent)?;
                }
                match fs::DirBuilder::new().mode(0o700).create(path) {
                    Ok(()) => {}
                    Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists && Path::new(path).is_dir() => {}
                    Err(e) => return Err(e),
                }
            }
            Effect::ChmodPrivate { path } => fs::set_permissions(path, fs::Permissions::from_mode(0o700))?,
            Effect::WriteAtomic { path, content } => {
                // `atomic_write_text`: üst dizinler oluşturulur, var olan normal dosyanın izni korunur, tmp + rename.
                if let Some(parent) = Path::new(path).parent() {
                    fs::create_dir_all(parent)?;
                }
                let keep = fs::metadata(path).ok().filter(|m| m.is_file()).map(|m| m.permissions().mode() & 0o7777);
                let tmp = format!("{path}.rs-parity.tmp");
                let mut opts = fs::OpenOptions::new();
                opts.write(true).create_new(true).custom_flags(O_NOFOLLOW);
                if let Some(m) = keep {
                    opts.mode(m);
                }
                let mut f = opts.open(&tmp)?;
                if let Some(m) = keep {
                    f.set_permissions(fs::Permissions::from_mode(m))?;
                }
                f.write_all(content.as_bytes())?;
                drop(f);
                if let Err(err) = fs::rename(&tmp, path) {
                    let _ = fs::remove_file(&tmp);
                    return Err(err);
                }
            }
        }
    }
    Ok(())
}

fn write_private(path: &str, data: &[u8]) -> std::io::Result<()> {
    let mut f = fs::OpenOptions::new().write(true).create(true).truncate(true).mode(0o600).custom_flags(O_NOFOLLOW).open(path)?;
    f.set_permissions(fs::Permissions::from_mode(0o600))?;
    f.write_all(data)
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
        RsOut { ret: v, ..Default::default() }
    }
}

pub fn diag_json(d: &Diag) -> Value {
    json!([d.event, d.fields.iter().map(|(k, v)| json!([k, v])).collect::<Vec<_>>()])
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
                json_diff(&format!("{path}.{k}"), x.get(k).unwrap_or(&Value::Null), y.get(k).unwrap_or(&Value::Null), out);
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
        Runner { e, known: Vec::new(), fails: Vec::new(), count: 0 }
    }

    /// Python `diags` içinden Rust kapsamı DIŞINDAKİ olayları atar (yalnız `spawn` başlatma kısmının olayları, bkz. çağıran).
    pub fn run<F>(&mut self, cases: Vec<Case>, drop_events: &[&str], rust: F)
    where
        F: Fn(&Env, &Case) -> RsOut,
    {
        for case in cases {
            self.count += 1;
            self.e.reset();
            self.e.apply_fixtures(&case);
            let py = self.e.py_call(&case);
            let snap_py = self.e.snapshot();
            if std::env::var("COPS_PARITY_DUMP").is_ok_and(|d| case.id.contains(&d)) {
                eprintln!("DUMP [{}] py: {py}\n  dosyalar: {snap_py:?}", case.id);
            }
            self.e.reset();
            self.e.apply_fixtures(&case);
            let mut rs = rust(&self.e, &case);
            let apply_err = if rs.skip_effects { Ok(()) } else { apply_effects(&rs.out.effects) };
            let snap_rs = self.e.snapshot();
            self.compare(&case, &py, &mut rs, apply_err, &snap_py, &snap_rs, drop_events);
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn compare(
        &mut self,
        case: &Case,
        py: &Value,
        rs: &mut RsOut,
        apply_err: std::io::Result<()>,
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
        let rd: Vec<Value> = rs.out.diags.iter().chain(rs.extra_diags.iter()).map(diag_json).collect();
        if pd != rd {
            diffs.push(format!("diag\n    py: {}\n    rs: {}", Value::from(pd), Value::from(rd)));
        }
        let pm: Vec<Value> = py["run"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|a| a.get(3).and_then(Value::as_str) == Some("mcp") && a.get(4).and_then(Value::as_str) == Some("add"))
            .cloned()
            .collect();
        let rm: Vec<Value> = rs.mcp_calls.iter().map(|a| json!(a)).collect();
        if pm != rm {
            diffs.push(format!("mcp add argv\n    py: {}\n    rs: {}", Value::from(pm), Value::from(rm)));
        }
        if py["popen"].as_array().unwrap() != &rs.popen {
            diffs.push(format!("popen\n    py: {}\n    rs: {}", py["popen"], Value::from(rs.popen.clone())));
        }
        if snap_py != snap_rs {
            let keys: std::collections::BTreeSet<&String> = snap_py.keys().chain(snap_rs.keys()).collect();
            for k in keys {
                let (a, b) = (snap_py.get(k), snap_rs.get(k));
                if a != b {
                    diffs.push(format!("dosya {k}\n    py: {a:?}\n    rs: {b:?}"));
                }
            }
        }
        if let Some(why) = case.known {
            if diffs.is_empty() {
                self.fails.push(format!("[{}] bilinen ayrışma kaydı var ama çıktılar EŞİT: kaydı kaldır ({why})", case.id));
            } else {
                self.known.push(format!("[{}] {why}", case.id));
            }
            return;
        }
        if !diffs.is_empty() {
            self.fails.push(format!("[{}] {} {}\n  {}", case.id, case.op, case.args, diffs.join("\n  ")));
        }
    }

    pub fn finish(self, family: &str) {
        if !self.fails.is_empty() {
            panic!("{family}: {} / {} vakada fark\n\n{}", self.fails.len(), self.count, self.fails.join("\n\n"));
        }
        eprintln!("{family}: {} vaka; bilinen ayrışma {}:", self.count, self.known.len());
        for k in &self.known {
            eprintln!("  {k}");
        }
    }
}

pub fn map(v: Value) -> Map<String, Value> {
    v.as_object().cloned().unwrap_or_default()
}
