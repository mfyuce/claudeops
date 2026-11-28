//! `roster.tsv` / `models.tsv` (Python `roster.py` ve `commands/web.py` TSV yardımcıları). Dosya doğruluk kaynağıdır; her
//! yazımdan sonra (kip `files` değilse) DB `tsv_rows` gölgesi eşitlenir. Satır: roster `ad\tcwd\tmodel[\tcli]`, models
//! `ad\tmodel`; `#` ile başlayan satır kapalı/emekli. Okumada satır sonları Python metin kipi gibi `\n`e çevrilir.
use crate::fsutil::{atomic_write_tsv, FileLock};
use crate::instances::Instances;
use crate::statedocs::StateDocs;
use crate::store::py_strip;
use indexmap::IndexMap;
use std::collections::HashSet;
use std::io;
use std::path::{Path, PathBuf};

/// Python `providers.PROVIDERS` anahtarları (parite testi denetler).
pub const PROVIDERS: [&str; 6] = ["claude", "agy", "codex", "copilot", "shell", "ucli"];
pub const DEFAULT_CLI: &str = "claude";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tsv {
    Roster,
    Models,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RawRow {
    pub name: String,
    pub rest: Vec<String>,
    pub active: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RosterEntry {
    pub name: String,
    pub cwd: String,
    pub model: String,
    pub cli: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProjectState {
    /// İki dosyada da açık.
    Active,
    /// Yalnız birinde yorumlu.
    Closed,
    /// İkisinde de yorumlu.
    Retired,
}

impl ProjectState {
    pub fn as_str(self) -> &'static str {
        match self {
            ProjectState::Active => "active",
            ProjectState::Closed => "closed",
            ProjectState::Retired => "retired",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Project {
    pub cwd: String,
    pub model: String,
    pub cli: String,
    pub state: ProjectState,
}

/// `register` reddi; [`RegisterError::code`] Python mesaj anahtarı.
#[derive(Debug)]
pub enum RegisterError {
    InvalidName,
    AlreadyRegistered,
    NameInUse,
    ConflictsRunning { other: String },
    DirNotFound { cwd: String },
    CwdBadChars,
    ModelBadChars,
    Io(io::Error),
}

impl RegisterError {
    pub fn code(&self) -> &'static str {
        match self {
            RegisterError::InvalidName => "invalid_name",
            RegisterError::AlreadyRegistered => "already_registered",
            RegisterError::NameInUse => "name_in_use",
            RegisterError::ConflictsRunning { .. } => "conflicts_running",
            RegisterError::DirNotFound { .. } => "dir_not_found",
            RegisterError::CwdBadChars => "cwd_bad_chars",
            RegisterError::ModelBadChars => "model_bad_chars",
            RegisterError::Io(_) => "io",
        }
    }
}
impl std::fmt::Display for RegisterError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RegisterError::Io(e) => write!(f, "io: {e}"),
            other => f.write_str(other.code()),
        }
    }
}
impl std::error::Error for RegisterError {}
impl From<io::Error> for RegisterError {
    fn from(e: io::Error) -> Self {
        RegisterError::Io(e)
    }
}

/// Python metin kipi okuma: dosya yoksa `None`; `\r\n` ve `\r` -> `\n`; UTF-8 değilse hata.
pub fn read_text(path: &Path) -> io::Result<Option<String>> {
    match std::fs::read_to_string(path) {
        Ok(t) if t.contains('\r') => Ok(Some(t.replace("\r\n", "\n").replace('\r', "\n"))),
        Ok(t) => Ok(Some(t)),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e),
    }
}

fn parse_raw(text: &str) -> Vec<RawRow> {
    text.split_inclusive('\n')
        .filter_map(|line| {
            let stripped = py_strip(line.trim_end_matches('\n'));
            if stripped.is_empty() {
                return None;
            }
            let active = !stripped.starts_with('#');
            let bare = if active { stripped } else { &stripped[1..] };
            let mut parts = py_strip(bare).split('\t');
            let name = parts.next().filter(|n| !n.is_empty())?;
            Some(RawRow {
                name: name.to_string(),
                rest: parts.map(String::from).collect(),
                active,
            })
        })
        .collect()
}

/// Etkin satırların sütunları (`roster._parse_tsv`).
fn parse_active(text: &str) -> impl Iterator<Item = Vec<&str>> {
    text.split_inclusive('\n').filter_map(|line| {
        let l = py_strip(line);
        (!l.is_empty() && !l.starts_with('#')).then(|| l.split('\t').collect())
    })
}

/// `_first_rows`: başlık satırı (`name`) hariç, yinelenen adda İLK satır.
fn first_rows(rows: Vec<RawRow>) -> IndexMap<String, RawRow> {
    let mut m = IndexMap::new();
    for r in rows {
        if r.name != "name" {
            m.entry(r.name.clone()).or_insert(r);
        }
    }
    m
}

pub use crate::paths::normpath;

/// `^[a-z][a-z0-9_]*$`.
pub fn valid_project_name(name: &str) -> bool {
    name.starts_with(|c: char| c.is_ascii_lowercase())
        && name
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
}

/// `(satır indeksi, yorumlu mu, '#'siz satır)`: ilk alanı `name` olan ilk satır.
fn find_line<'a>(lines: &[&'a str], name: &str) -> Option<(usize, bool, &'a str)> {
    lines.iter().enumerate().find_map(|(i, line)| {
        let core = line.trim_end_matches('\n');
        let commented = core.starts_with('#');
        let bare = if commented { &core[1..] } else { core };
        (py_strip(bare).split('\t').next() == Some(name)).then_some((i, commented, bare))
    })
}

/// `web._tsv_unsafe`: TSV alanında sekme ya da satır sonu.
fn tsv_unsafe(value: &str) -> bool {
    value.contains(['\t', '\n', '\r'])
}

fn check_fields(fields: &[&str]) -> io::Result<()> {
    if fields.iter().any(|f| tsv_unsafe(f)) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "TSV alanında sekme/satır sonu",
        ));
    }
    Ok(())
}

#[derive(Clone, Copy)]
pub struct Roster<'a> {
    docs: &'a StateDocs,
}

impl<'a> Roster<'a> {
    pub fn new(docs: &'a StateDocs) -> Roster<'a> {
        Roster { docs }
    }

    pub fn path(&self, which: Tsv) -> PathBuf {
        match which {
            Tsv::Roster => self.docs.dir().roster_tsv(),
            Tsv::Models => self.docs.dir().models_tsv(),
        }
    }

    /// Yorumlu satırlar DAHİL (`_read_tsv_raw`; DB gölgesini de eşitler).
    pub fn raw_rows(&self, which: Tsv) -> io::Result<Vec<RawRow>> {
        let path = self.path(which);
        self.docs.shadow_tsv(&path, false);
        Ok(read_text(&path)?.map_or_else(Vec::new, |t| parse_raw(&t)))
    }

    /// `read_roster`: etkin girdiler; tanınmayan 4. sütun `claude` sayılır.
    pub fn entries(&self) -> io::Result<Vec<RosterEntry>> {
        let text = read_text(&self.path(Tsv::Roster))?.unwrap_or_default();
        Ok(parse_active(&text)
            .filter(|row| row.len() >= 2)
            .map(|row| RosterEntry {
                name: row[0].into(),
                cwd: row[1].into(),
                model: row.get(2).copied().unwrap_or("").into(),
                cli: row
                    .get(3)
                    .copied()
                    .filter(|c| PROVIDERS.contains(c))
                    .unwrap_or(DEFAULT_CLI)
                    .into(),
            })
            .collect())
    }

    /// `read_models`: {ad: model}, etkin girdiler (yinelenende son geçer).
    pub fn models(&self) -> io::Result<IndexMap<String, String>> {
        let text = read_text(&self.path(Tsv::Models))?.unwrap_or_default();
        Ok(parse_active(&text)
            .filter(|row| row.len() >= 2)
            .map(|row| (row[0].to_string(), row[1].to_string()))
            .collect())
    }

    /// `roster_by_name`: {ad: girdi} (yinelenen adda SON satır, ilk konumda; Python sözlüğü gibi).
    pub fn by_name(&self) -> io::Result<IndexMap<String, RosterEntry>> {
        Ok(self
            .entries()?
            .into_iter()
            .map(|e| (e.name.clone(), e))
            .collect())
    }

    /// `_fleet_status`: iki dosyanın birleşimi (models sırasıyla; roster'da olmayan ad atlanır).
    pub fn fleet_status(&self) -> io::Result<IndexMap<String, Project>> {
        let models = first_rows(self.raw_rows(Tsv::Models)?);
        let roster = first_rows(self.raw_rows(Tsv::Roster)?);
        Ok(models
            .into_iter()
            .filter_map(|(name, m)| {
                let r = roster.get(&name)?;
                let cwd = r.rest.first().map_or("", String::as_str);
                let cwd = if cwd.is_empty() {
                    String::new()
                } else {
                    normpath(cwd)
                };
                let cli = r
                    .rest
                    .get(2)
                    .filter(|c| PROVIDERS.contains(&c.as_str()))
                    .map_or(DEFAULT_CLI, String::as_str)
                    .to_string();
                let state = match (m.active, r.active) {
                    (true, true) => ProjectState::Active,
                    (false, false) => ProjectState::Retired,
                    _ => ProjectState::Closed,
                };
                let model = m.rest.into_iter().next().unwrap_or_default();
                Some((
                    name,
                    Project {
                        cwd,
                        model,
                        cli,
                        state,
                    },
                ))
            })
            .collect())
    }

    /// İki TSV için TEK kilit (`<dizin>/roster.lock`; Python panel/CLI ile aynı). İç içe alma.
    pub fn lock(&self) -> io::Result<RosterGuard<'a>> {
        if self.docs.is_read_only() {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "roster: salt okuma kipi (kilit dosyası açılmadı)",
            ));
        }
        let lock = FileLock::roster(&self.path(Tsv::Roster)).inspect_err(|_| {
            // Python `_file_lock_outer(path)`: `path` = `<dizin>/roster` (`.lock` eksiz)
            let p = crate::paths::abs_normpath(&self.path(Tsv::Roster));
            self.docs.log_lock_refused(
                &p.parent()
                    .unwrap_or(std::path::Path::new("/"))
                    .join("roster"),
            );
        })?;
        Ok(RosterGuard {
            roster: *self,
            _lock: lock,
        })
    }

    /// `_register_project`: yeni projeyi iki dosyaya ekler (oturum açmaz).
    /// `running`: canlı süreçlerin `(ad, taban ad)` listesi (tarama çağıranın işi).
    /// `default_model`: model boşsa cli için varsayılan (sağlayıcı bilgisi çağıranda).
    pub fn register_project(
        &self,
        name: &str,
        cwd: &str,
        model: &str,
        cli: &str,
        running: &[(String, String)],
        default_model: impl FnOnce(&str) -> String,
    ) -> Result<(), RegisterError> {
        let name = py_strip(name);
        if !valid_project_name(name) {
            return Err(RegisterError::InvalidName);
        }
        let taken = || -> io::Result<bool> {
            Ok(self.raw_rows(Tsv::Roster)?.iter().any(|r| r.name == name))
        };
        if name != "name" && taken()? {
            return Err(RegisterError::AlreadyRegistered);
        }
        if Instances::new(self.docs).get(name).is_some() {
            return Err(RegisterError::NameInUse);
        }
        if let Some((other, _)) = running.iter().find(|(n, b)| n == name || b == name) {
            return Err(RegisterError::ConflictsRunning {
                other: other.clone(),
            });
        }
        let cwd = crate::paths::expanduser(py_strip(cwd));
        if cwd.is_empty() || !Path::new(&cwd).is_dir() {
            return Err(RegisterError::DirNotFound { cwd });
        }
        if tsv_unsafe(&cwd) {
            return Err(RegisterError::CwdBadChars);
        }
        let cli = Some(py_strip(cli))
            .filter(|c| PROVIDERS.contains(c))
            .unwrap_or(DEFAULT_CLI);
        let model = match py_strip(model) {
            "" => default_model(cli),
            m => m.to_string(),
        };
        if tsv_unsafe(&model) {
            return Err(RegisterError::ModelBadChars);
        }
        let guard = self.lock()?;
        if taken()? {
            return Err(RegisterError::AlreadyRegistered);
        }
        guard.append(Tsv::Roster, &[name, &cwd, &model, cli])?;
        guard.append(Tsv::Models, &[name, &model])?;
        Ok(())
    }
}

/// Kilit tutulurken yazım işlemleri.
pub struct RosterGuard<'a> {
    roster: Roster<'a>,
    _lock: FileLock,
}

impl RosterGuard<'_> {
    pub fn roster(&self) -> Roster<'_> {
        self.roster
    }

    fn write(&self, path: &Path, text: &str) -> io::Result<()> {
        atomic_write_tsv(path, text)?;
        self.roster.docs.shadow_tsv(path, true);
        Ok(())
    }

    /// Sona satır ekle (eksik satır sonu tamamlanır).
    pub fn append(&self, which: Tsv, fields: &[&str]) -> io::Result<()> {
        check_fields(fields)?;
        let path = self.roster.path(which);
        let mut text = read_text(&path)?.unwrap_or_default();
        if !text.is_empty() && !text.ends_with('\n') {
            text.push('\n');
        }
        text.push_str(&fields.join("\t"));
        text.push('\n');
        self.write(&path, &text)
    }

    fn edit_line(
        &self,
        which: Tsv,
        name: &str,
        f: impl FnOnce(bool, &str) -> String,
    ) -> io::Result<bool> {
        let path = self.roster.path(which);
        let Some(text) = read_text(&path)? else {
            return Ok(false);
        };
        let mut lines: Vec<&str> = text.split_inclusive('\n').collect();
        let Some((i, commented, bare)) = find_line(&lines, name) else {
            return Ok(false);
        };
        let new = f(commented, bare) + "\n";
        lines[i] = &new;
        self.write(&path, &lines.concat())?;
        Ok(true)
    }

    /// `_toggle_comment`: satırın `#` durumunu ayarla. Satır yoksa `false`.
    pub fn set_active(&self, which: Tsv, name: &str, active: bool) -> io::Result<bool> {
        self.edit_line(which, name, |_, bare| {
            if active {
                bare.to_string()
            } else {
                format!("#{bare}")
            }
        })
    }

    /// `_replace_tsv_line`: satırın alanlarını değiştir (`#` durumu korunur; `fields[0]` yeni ad olabilir).
    pub fn replace(&self, which: Tsv, name: &str, fields: &[&str]) -> io::Result<bool> {
        check_fields(fields)?;
        let core = fields.join("\t");
        self.edit_line(which, name, |commented, _| {
            if commented {
                format!("#{core}")
            } else {
                core
            }
        })
    }
}

/// `web._blueprint_cwds`: blueprint adayı satırlar (tarihli/türev adlı eski instance satırları hariç) -> {ad: cwd}.
pub fn blueprint_cwds(fleet: &IndexMap<String, Project>) -> IndexMap<String, String> {
    fleet
        .iter()
        .filter(|(n, _)| crate::instances::derived_name(n).is_none())
        .map(|(n, p)| (n.clone(), p.cwd.clone()))
        .collect()
}

/// `_all_known_names`: roster'daki (yorumlu dahil, `name` başlığı hariç) ve instance kaydındaki tüm adlar + çalışan
/// süreçlerin ad ve taban adları. `running`: canlı süreçlerin `(ad, taban ad)` listesi (tarama çağıranın işi,
/// [`Roster::register_project`] ile aynı biçim).
pub fn known_names(docs: &StateDocs, running: &[(String, String)]) -> io::Result<HashSet<String>> {
    let mut s: HashSet<String> = Roster::new(docs)
        .raw_rows(Tsv::Roster)?
        .into_iter()
        .map(|r| r.name)
        .filter(|n| n != "name")
        .collect();
    s.extend(Instances::new(docs).load().into_keys());
    for (name, base) in running {
        s.insert(name.clone());
        s.insert(base.clone());
    }
    Ok(s)
}
