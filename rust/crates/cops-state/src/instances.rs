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
/// Python `DIAG_PREFIX`.
pub const DIAG_PREFIX: &str = "diag";

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

/// Python `re` `$`: dizenin sonu YA DA sondaki tek `\n`in önü (çok satırlı kip değil).
fn regex_body(name: &str) -> &str {
    name.strip_suffix('\n').unwrap_or(name)
}

/// `^([a-z][a-z0-9]*?)(\d{8})<kuyruk>$` ortak eşleyici (tembel önek: ilk uyan bölme kazanır). `\d` Unicode ondalık rakam.
fn match_dated(
    name: &str,
    tail_ok: impl Fn(&str) -> bool,
    no_digit_after: bool,
) -> Option<(&str, &str, &str)> {
    let body = regex_body(name);
    let idx: Vec<(usize, char)> = body.char_indices().collect();
    if !idx.first()?.1.is_ascii_lowercase() {
        return None;
    }
    for i in 1..idx.len() {
        let prev = idx[i - 1].1;
        if !(prev.is_ascii_lowercase() || prev.is_ascii_digit()) {
            return None;
        }
        let date = idx.get(i..i + 8)?;
        if !date.iter().all(|(_, c)| crate::pycompat::is_re_digit(*c)) {
            continue;
        }
        let end = idx.get(i + 8).map_or(body.len(), |(p, _)| *p);
        if no_digit_after
            && idx
                .get(i + 8)
                .is_some_and(|(_, c)| crate::pycompat::is_re_digit(*c))
        {
            continue;
        }
        let tail = &body[end..];
        if tail_ok(tail) {
            let start = idx[i].0;
            return Some((&body[..start], &body[start..end], tail));
        }
    }
    None
}

/// `DERIVED_NAME_RE` = `^([a-z][a-z0-9]*?)(\d{8})(?!\d)([a-z0-9_]*)$`: (taban, tarih, ek).
pub fn derived_name(name: &str) -> Option<(&str, &str, &str)> {
    match_dated(
        name,
        |t| {
            t.bytes()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_')
        },
        true,
    )
}

/// `AUTO_NAME_RE` = `^([a-z][a-z0-9]*?)(\d{8})((?:_\d+)*)$` (`_generate_new_chat_name` biçimi): (taban, tarih, ek).
pub fn auto_name(name: &str) -> Option<(&str, &str, &str)> {
    match_dated(
        name,
        |t| {
            t.is_empty()
                || t.strip_prefix('_').is_some_and(|r| {
                    r.split('_')
                        .all(|p| !p.is_empty() && p.chars().all(crate::pycompat::is_re_digit))
                })
        },
        false,
    )
}

/// `created_at_from_name`: türev addaki tarihin YEREL gece yarısı epoch saniyesi (`strptime(.., "%Y%m%d").timestamp()`).
pub fn created_at_from_name(name: &str) -> Option<f64> {
    let (_, date, _) = derived_name(name)?;
    let c: Vec<char> = date.chars().collect();
    // %Y = \d{4} (Unicode), %m = 1[0-2]|0[1-9] (ASCII), %d = 3[01]|[12]\d|0[1-9] (ikinci rakam Unicode olabilir)
    let dv = |ch: char| crate::pycompat::decimal_value(ch).map(i64::from);
    let year = c[..4]
        .iter()
        .try_fold(0i64, |a, ch| Some(a * 10 + dv(*ch)?))?;
    let month = match (c[4], c[5]) {
        ('1', m @ '0'..='2') => 10 + i64::from(m as u8 - b'0'),
        ('0', m @ '1'..='9') => i64::from(m as u8 - b'0'),
        _ => return None,
    };
    let day = match (c[6], c[7]) {
        ('3', d @ ('0' | '1')) => 30 + i64::from(d as u8 - b'0'),
        (t @ ('1' | '2'), d) => i64::from(t as u8 - b'0') * 10 + dv(d)?,
        ('0', d @ '1'..='9') => i64::from(d as u8 - b'0'),
        _ => return None,
    };
    crate::pytime::naive_local_timestamp(year, month, day)
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

/// Python'un `AttributeError` verdiği kayıt şekli (sözlük olmayan kayıt / dize olmayan `model`).
fn not_dict() -> InstancesError {
    InstancesError::Corrupt("kayıt beklenen tipte değil (Python AttributeError)".into())
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
        self.read_checked().map(|(d, _)| d)
    }

    /// (belge, eşlenmemiş vekil okundu mu): `true` ise belge okunabilir ama yazılamaz (Python'da yazım
    /// `UnicodeEncodeError` verir; burada [`Self::try_mutate`] yazmadan hata döner).
    fn read_checked(&self) -> Result<(Json, bool), InstancesError> {
        let path = self.docs.dir().instances_json();
        let corrupt = |m: &str| InstancesError::Corrupt(format!("{} {m}", path.display()));
        let mut lossy = false;
        let from_file = match read_file(&path) {
            Read::Value(v) => v,
            Read::Lossy(v) => {
                lossy = true;
                v
            }
            Read::Corrupt => return Err(corrupt("okunamadı")),
            Read::Missing if path.exists() => return Err(corrupt("okunamadı")),
            Read::Missing => {
                let mut m = Map::new();
                m.insert("version".into(), Json::Int(VERSION));
                m.insert("instances".into(), Json::object());
                Json::Object(m)
            }
        };
        let data = match self.docs.read(DOC, &path) {
            Read::Value(v) => v,
            Read::Lossy(v) => {
                lossy = true;
                v
            }
            _ => from_file,
        };
        match data.get("instances") {
            Some(Json::Object(_)) => Ok((data, lossy)),
            _ => Err(corrupt("beklenen şekilde değil")),
        }
    }

    /// `load_instances`: {ad: kayıt}; bozuk belgede boş (okuyucular için). `files`/`dual` kipte dosya anahtarına
    /// (inode, mtime_ns, boyut) bağlı önbellek (Python gibi); `db` kipte ÖNBELLEKSİZ (sahibe soruldu: ayna dosya
    /// yazılamazsa anahtar değişmez, önbellek bayat kalırdı; `docs/rs-state.md`).
    pub fn load(&self) -> Map {
        let path = self.docs.dir().instances_json();
        let key = match crate::statedocs::file_key(&path) {
            Ok(Some(k)) if self.docs.effective_backend(DOC) != crate::Backend::Db => k,
            _ => {
                self.docs.cache_put(DOC, None, &Json::Null);
                return self.load_uncached();
            }
        };
        if let Some(Json::Object(m)) = self.docs.cache_get(DOC, key) {
            return m;
        }
        let m = self.load_uncached();
        self.docs
            .cache_put(DOC, Some(key), &Json::Object(m.clone()));
        m
    }

    fn load_uncached(&self) -> Map {
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
        self.try_mutate(|m| Ok(f(m)))
    }

    /// [`Self::mutate`]; `f` hata dönerse HİÇBİR ŞEY yazılmaz (Python `_mutate` içindeki istisna gibi).
    pub fn try_mutate<T>(
        &self,
        f: impl FnOnce(&mut Map) -> Result<T, InstancesError>,
    ) -> Result<(T, WriteOutcome), InstancesError> {
        let path = self.docs.dir().instances_json();
        let _lock = FileLock::blocking(&self.docs.dir().join("instances.json.lock"))
            .map_err(InstancesError::Lock)?;
        let (mut data, lossy) = self.read_checked()?;
        if lossy {
            return Err(InstancesError::Corrupt(
                "eşlenmemiş vekil içeren belge yazılamaz (Python UnicodeEncodeError)".into(),
            ));
        }
        let shape = || InstancesError::Corrupt("beklenen şekilde değil".into());
        let obj = data.as_object_mut().ok_or_else(shape)?;
        let items = obj
            .get_mut("instances")
            .and_then(Json::as_object_mut)
            .ok_or_else(shape)?;
        let out = f(items)?;
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
        self.try_mutate(|items| {
            // `items.get(name) or {}`: doğru değerli ama sözlük olmayan eski kayıt Python'da AttributeError
            let old = match items.get(name) {
                Some(v) if v.truthy() && v.as_object().is_none() => return Err(not_dict()),
                Some(v) if v.truthy() => v.clone(),
                _ => Json::object(),
            };
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
            Ok(())
        })
        .map(|(_, w)| w)
    }

    /// `mark_started`: son başlatmanın parametrelerini yaz; kayıt yoksa hiçbir alan değişmez.
    pub fn mark_started(&self, name: &str, l: &Launch) -> Result<WriteOutcome, InstancesError> {
        self.try_mutate(|items| {
            let rec = match items.get_mut(name) {
                None | Some(Json::Null) => return Ok(()),
                Some(v) => v.as_object_mut().ok_or_else(not_dict)?,
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
            Ok(())
        })
        .map(|(_, w)| w)
    }

    /// `mark_models_gone(live)`: canlı model listesinde olmayan kayda `model_gone: true` (silmez); geri gelende kalkar.
    /// `live` = {cli: modeller}; yalnız listesi BOŞ OLMAYAN cli'lar değerlendirilir. Değişen kayıt sayısı. Python'un
    /// `AttributeError` verdiği kayıt (sözlük olmayan kayıt, dize olmayan doğru değerli `model`) hata: hiçbir şey yazılmaz.
    pub fn mark_models_gone(
        &self,
        live: &std::collections::HashMap<String, std::collections::HashSet<String>>,
    ) -> Result<usize, InstancesError> {
        self.try_mutate(|items| {
            let mut n = 0;
            for rec in items.values_mut() {
                let rec = rec.as_object_mut().ok_or_else(not_dict)?;
                let models = match rec.get("cli") {
                    Some(Json::Str(c)) => live.get(c.as_str()),
                    Some(v) if v.truthy() => None,
                    _ => live.get(""),
                };
                let m = rec.get("model").cloned();
                let skip = match (&m, models) {
                    (_, None) => true,
                    (_, Some(set)) if set.is_empty() => true,
                    (None, _) => true,
                    (Some(v), _) if !v.truthy() => true,
                    (Some(Json::Str(s)), _) => s == "-" || s == "auto" || s.starts_with("claude-"),
                    (Some(_), _) => return Err(not_dict()),
                };
                if skip {
                    if rec.shift_remove("model_gone").is_some_and(|v| v.truthy()) {
                        n += 1;
                    }
                    continue;
                }
                let gone = match (&m, models) {
                    (Some(Json::Str(s)), Some(set)) => !set.contains(s),
                    _ => false,
                };
                if rec.get("model_gone").is_some_and(Json::truthy) != gone {
                    if gone {
                        rec.insert("model_gone".into(), true.into());
                    } else {
                        rec.shift_remove("model_gone");
                    }
                    n += 1;
                }
            }
            Ok(n)
        })
        .map(|(n, _)| n)
    }

    /// `forget_instance`: Geçmiş'ten gizle (kayıt kalır). Değişiklik olduysa `true`.
    pub fn forget(&self, name: &str) -> Result<bool, InstancesError> {
        self.try_mutate(|items| {
            let rec = match items.get_mut(name) {
                None | Some(Json::Null) => return Ok(false),
                Some(v) => v.as_object_mut().ok_or_else(not_dict)?,
            };
            if rec.get("forgotten").is_some_and(Json::truthy) {
                return Ok(false);
            }
            rec.insert("forgotten".into(), true.into());
            Ok(true)
        })
        .map(|(b, _)| b)
    }

    /// `rename_blueprint`: değişen kayıt sayısı.
    pub fn rename_blueprint(&self, old: &str, new: &str) -> Result<usize, InstancesError> {
        self.try_mutate(|items| {
            let mut n = 0;
            for rec in items.values_mut() {
                let rec = rec.as_object_mut().ok_or_else(not_dict)?;
                if rec.get("blueprint").and_then(Json::as_str) == Some(old) {
                    rec.insert("blueprint".into(), new.into());
                    n += 1;
                }
            }
            Ok(n)
        })
        .map(|(n, _)| n)
    }

    /// `add_missing`: yalnız olmayan adları ekle; eklenen sayı.
    pub fn add_missing(&self, records: &Map) -> Result<usize, InstancesError> {
        self.try_mutate(|items| {
            let mut n = 0;
            for (name, rec) in records {
                if !items.contains_key(name) {
                    // `dict(rec)`: sözlük olmayan kayıt Python'da TypeError/ValueError
                    if rec.as_object().is_none() {
                        return Err(not_dict());
                    }
                    items.insert(name.clone(), rec.clone());
                    n += 1;
                }
            }
            Ok(n)
        })
        .map(|(n, _)| n)
    }
}
