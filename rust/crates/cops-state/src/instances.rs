//! `instances.json` (Python `instances.py`): bir blueprint'ten açılan, roster'a yazılmayan oturum kayıtları.
//! `{"version":1,"instances":{ad: kayıt}}`; kayıt silinmez (`forgotten`), adlar tekrar kullanılmaz. Okuma/yazma
//! [`StateDocs`] üstünden (db kipinde DB doğruluk kaynağı), yazım `instances.json.lock` altında ve 0600.
//! Kayıtlar ham [`Json`] nesnesidir: bilinmeyen alanlar korunur.
use crate::fsutil::FileLock;
use crate::json::{Json, Map};
use crate::statedocs::{read_file, Read, StateDocs, WriteError, WriteOutcome};
use indexmap::IndexMap;

const DOC: &str = "instances";
const VERSION: i64 = 1;

#[derive(Debug)]
pub enum InstancesError {
    /// Dosya/belge beklenen şekilde değil: üstüne YAZILMAZ.
    Corrupt(String),
    Lock(std::io::Error),
    Write(WriteError),
}

impl std::fmt::Display for InstancesError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            InstancesError::Corrupt(m) => write!(f, "instances bozuk: {m}"),
            InstancesError::Lock(e) => write!(f, "instances kilidi: {e}"),
            InstancesError::Write(e) => write!(f, "instances: {e}"),
        }
    }
}
impl std::error::Error for InstancesError {}

/// Başlatma parametreleri (`record_instance` / `mark_started`).
#[derive(Debug, Clone, Default)]
pub struct Launch {
    pub cli: String,
    pub model: String,
    pub permission_mode: String,
    pub effort: String,
    /// Boş değilse kayda yazılır; anahtar/parola taşımaz.
    pub cli_opts: Map,
}

#[derive(Debug, Clone, Default)]
pub struct NewInstance {
    pub blueprint: Option<String>,
    pub cwd: String,
    pub origin: String,
    pub created_at: Option<f64>,
    pub launch: Launch,
}

/// `<taban><YYYYMMDD><ek>` adının parçaları (`DERIVED_NAME_RE`).
pub fn derived_name(name: &str) -> Option<(&str, &str, &str)> {
    let b = name.as_bytes();
    let word = |c: &u8| c.is_ascii_lowercase() || c.is_ascii_digit();
    if !b.first()?.is_ascii_lowercase() {
        return None;
    }
    for i in 1..=b.len().saturating_sub(8) {
        if !word(&b[i - 1]) {
            return None;
        }
        let date = b.get(i..i + 8)?;
        if !date.iter().all(u8::is_ascii_digit) || b.get(i + 8).is_some_and(u8::is_ascii_digit) {
            continue;
        }
        if b[i + 8..].iter().all(|c| word(c) || *c == b'_') {
            return Some((&name[..i], &name[i..i + 8], &name[i + 8..]));
        }
    }
    None
}

/// `infer_blueprint`: önek+aynı cwd > aynı cwd'li TEK blueprint > önek. `blueprints` = {ad: cwd}.
pub fn infer_blueprint(
    name: &str,
    cwd: &str,
    blueprints: &IndexMap<String, String>,
) -> Option<String> {
    let norm = |p: &str| {
        if p.is_empty() {
            String::new()
        } else {
            crate::roster::normpath(p)
        }
    };
    let (prefix, _, _) = derived_name(name)?;
    let target = norm(cwd);
    if blueprints.get(prefix).is_some_and(|c| norm(c) == target) {
        return Some(prefix.into());
    }
    let mut same = blueprints.iter().filter(|(_, c)| norm(c) == target);
    if let (Some((b, _)), None) = (same.next(), same.next()) {
        return Some(b.clone());
    }
    blueprints.contains_key(prefix).then(|| prefix.into())
}

pub struct Instances<'a> {
    docs: &'a StateDocs,
}

impl<'a> Instances<'a> {
    pub fn new(docs: &'a StateDocs) -> Instances<'a> {
        Instances { docs }
    }

    /// Belgenin tamamı; yoksa boş şekil, bozuksa hata.
    pub fn read_strict(&self) -> Result<Json, InstancesError> {
        let path = self.docs.dir().instances_json();
        let corrupt = |m: &str| InstancesError::Corrupt(format!("{} {m}", path.display()));
        let from_file = match read_file(&path) {
            Read::Value(v) => v,
            Read::Corrupt => return Err(corrupt("okunamadı")),
            Read::Missing if path.exists() => return Err(corrupt("okunamadı")),
            Read::Missing => {
                let mut m = Map::new();
                m.insert("version".into(), Json::Int(VERSION));
                m.insert("instances".into(), Json::object());
                Json::Object(m)
            }
        };
        let data = self
            .docs
            .read(DOC, &path)
            .into_option()
            .unwrap_or(from_file);
        match data.get("instances") {
            Some(Json::Object(_)) => Ok(data),
            _ => Err(corrupt("beklenen şekilde değil")),
        }
    }

    /// {ad: kayıt}; bozuk belgede boş (okuyucular için).
    pub fn load(&self) -> Map {
        match self.read_strict() {
            Ok(Json::Object(mut d)) => match d.swap_remove("instances") {
                Some(Json::Object(m)) => m,
                _ => Map::new(),
            },
            _ => Map::new(),
        }
    }

    pub fn get(&self, name: &str) -> Option<Json> {
        self.load().swap_remove(name)
    }

    /// Kilit altında oku-değiştir-yaz. `f` instance sözlüğünü alır.
    pub fn mutate<T>(
        &self,
        f: impl FnOnce(&mut Map) -> T,
    ) -> Result<(T, WriteOutcome), InstancesError> {
        let path = self.docs.dir().instances_json();
        let _lock = FileLock::blocking(&self.docs.dir().join("instances.json.lock"))
            .map_err(InstancesError::Lock)?;
        let mut data = self.read_strict()?;
        let shape = || InstancesError::Corrupt("beklenen şekilde değil".into());
        let obj = data.as_object_mut().ok_or_else(shape)?;
        let items = obj
            .get_mut("instances")
            .and_then(Json::as_object_mut)
            .ok_or_else(shape)?;
        let out = f(items);
        obj.insert("version".into(), Json::Int(VERSION));
        let written = self
            .docs
            .write(DOC, &path, &data, Some(0o600))
            .map_err(InstancesError::Write)?;
        Ok((out, written))
    }

    /// `record_instance`: upsert; var olanın `created_at`/`origin`/`last_started_at`i korunur.
    pub fn record(&self, name: &str, new: &NewInstance) -> Result<WriteOutcome, InstancesError> {
        let now = crate::now();
        self.mutate(|items| {
            let old = items.get(name).cloned().unwrap_or_else(Json::object);
            let keep = |k: &str| old.get(k).filter(|v| v.truthy()).cloned();
            let l = &new.launch;
            let mut r = Map::new();
            let mut put = |k: &str, v: Json| {
                r.insert(k.to_string(), v);
            };
            put(
                "blueprint",
                new.blueprint.clone().map_or(Json::Null, Json::from),
            );
            put("cwd", new.cwd.as_str().into());
            put("cli", l.cli.as_str().into());
            put("model", l.model.as_str().into());
            put("permission_mode", l.permission_mode.as_str().into());
            put("effort", l.effort.as_str().into());
            let created = new.created_at.filter(|c| *c != 0.0).unwrap_or(now);
            put(
                "created_at",
                keep("created_at").unwrap_or(Json::Float(created)),
            );
            put(
                "last_started_at",
                old.get("last_started_at").cloned().unwrap_or(Json::Null),
            );
            put(
                "origin",
                keep("origin").unwrap_or_else(|| new.origin.as_str().into()),
            );
            if !l.cli_opts.is_empty() {
                put("cli_opts", Json::Object(l.cli_opts.clone()));
            }
            items.insert(name.to_string(), Json::Object(r));
        })
        .map(|(_, w)| w)
    }

    /// `mark_started`: son başlatmanın parametrelerini yaz; kayıt yoksa hiçbir alan değişmez.
    pub fn mark_started(&self, name: &str, l: &Launch) -> Result<WriteOutcome, InstancesError> {
        self.mutate(|items| {
            let Some(rec) = items.get_mut(name).and_then(Json::as_object_mut) else {
                return;
            };
            if !l.cli_opts.is_empty() {
                rec.insert("cli_opts".into(), Json::Object(l.cli_opts.clone()));
            } else if rec.get("cli").and_then(Json::as_str) != Some(l.cli.as_str()) {
                rec.shift_remove("cli_opts"); // cli değişti: eski seçenekler geçersiz
            }
            rec.insert("cli".into(), l.cli.as_str().into());
            rec.insert("model".into(), l.model.as_str().into());
            rec.insert("permission_mode".into(), l.permission_mode.as_str().into());
            rec.insert("effort".into(), l.effort.as_str().into());
            rec.insert("last_started_at".into(), Json::Float(crate::now()));
            rec.shift_remove("forgotten");
        })
        .map(|(_, w)| w)
    }

    /// `forget_instance`: Geçmiş'ten gizle (kayıt kalır). Değişiklik olduysa `true`.
    pub fn forget(&self, name: &str) -> Result<bool, InstancesError> {
        self.mutate(
            |items| match items.get_mut(name).and_then(Json::as_object_mut) {
                Some(rec) if !rec.get("forgotten").is_some_and(Json::truthy) => {
                    rec.insert("forgotten".into(), true.into());
                    true
                }
                _ => false,
            },
        )
        .map(|(b, _)| b)
    }

    /// `rename_blueprint`: değişen kayıt sayısı.
    pub fn rename_blueprint(&self, old: &str, new: &str) -> Result<usize, InstancesError> {
        self.mutate(|items| {
            let mut n = 0;
            for rec in items.values_mut().filter_map(Json::as_object_mut) {
                if rec.get("blueprint").and_then(Json::as_str) == Some(old) {
                    rec.insert("blueprint".into(), new.into());
                    n += 1;
                }
            }
            n
        })
        .map(|(n, _)| n)
    }

    /// `add_missing`: yalnız olmayan adları ekle; eklenen sayı.
    pub fn add_missing(&self, records: &Map) -> Result<usize, InstancesError> {
        self.mutate(|items| {
            let mut n = 0;
            for (name, rec) in records {
                if !items.contains_key(name) {
                    items.insert(name.clone(), rec.clone());
                    n += 1;
                }
            }
            n
        })
        .map(|(n, _)| n)
    }
}
