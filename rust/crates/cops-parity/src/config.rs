//! İstek listesi (JSON). Bilinmeyen alan HATADIR: yazım yanlışı sessizce bir güvenceyi düşürmesin.
//!
//! ```json
//! {
//!   "defaults": {"ignore": ["server_started_at"], "dynamic": ["**.updated_at"]},
//!   "requests": [
//!     {"name": "durum", "path": "/api/status", "dynamic": ["sessions.*.cpu"], "unordered": ["sessions"]},
//!     {"path": "/api/context", "method": "POST", "body": {"name": "x"}, "side_effect_free": true, "expect": "local"}
//!   ]
//! }
//! ```
//!
//! - `ignore`: alan iki yanda da atılır (varlığı bile karşılaştırılmaz).
//! - `dynamic`: alan iki yanda da OLMALI ve JSON türü aynı olmalı; değeri karşılaştırılmaz.
//! - `unordered`: dizinin sırası önemsiz.
//! - desen: nokta ile ayrılmış anahtar / dizi sırası; `*` tek parça, `**` sıfır ya da daha çok parça; kök dizi için `$`.
//! - `headers`: karşılaştırılacak ek yanıt başlıkları (`content-type`in medya türü her zaman karşılaştırılır).
//! - `expect: "local"`: Rust ön kapı isteği KENDİSİ cevaplamalı (aksi halde parite sahte olur: iki yan da Python).

use crate::compare::{Pattern, Rules};
use serde_json::Value;

#[derive(Debug, Clone)]
pub struct Case {
    pub name: String,
    pub method: String,
    pub path: String,
    pub body: Option<Vec<u8>>,
    pub request_headers: Vec<(String, String)>,
    pub compare_headers: Vec<String>,
    pub rules: Rules,
    pub expect_local: bool,
    /// `Some(false)`: GET olsa da varsayılan koşuya girmez; `Some(true)`: yöntemi ne olursa olsun girer.
    pub side_effect_free: Option<bool>,
}

impl Case {
    /// Varsayılan koşuya girer mi: `side_effect_free` açıkça verilmemişse yalnız GET/HEAD.
    pub fn safe(&self) -> bool {
        self.side_effect_free
            .unwrap_or(matches!(self.method.as_str(), "GET" | "HEAD"))
    }
}

type Obj = serde_json::Map<String, Value>;

fn object<'a>(v: &'a Value, what: &str, allowed: &[&str]) -> Result<&'a Obj, String> {
    let o = v
        .as_object()
        .ok_or_else(|| format!("{what}: nesne olmalı"))?;
    match o.keys().find(|k| !allowed.contains(&k.as_str())) {
        Some(k) => Err(format!("{what}: bilinmeyen alan {k:?}")),
        None => Ok(o),
    }
}

fn strings(o: &Obj, key: &str, what: &str) -> Result<Vec<String>, String> {
    let bad = || format!("{what}: {key:?} metin dizisi olmalı");
    match o.get(key) {
        None => Ok(Vec::new()),
        Some(v) => v
            .as_array()
            .ok_or_else(bad)?
            .iter()
            .map(|s| s.as_str().map(str::to_string).ok_or_else(bad))
            .collect(),
    }
}

fn text(o: &Obj, key: &str, what: &str) -> Result<Option<String>, String> {
    match o.get(key) {
        None => Ok(None),
        Some(v) => v
            .as_str()
            .map(|s| Some(s.to_string()))
            .ok_or_else(|| format!("{what}: {key:?} metin olmalı")),
    }
}

fn rules(o: &Obj, what: &str, base: &Rules) -> Result<Rules, String> {
    let mut r = base.clone();
    for (key, list) in [
        ("ignore", &mut r.ignore),
        ("dynamic", &mut r.dynamic),
        ("unordered", &mut r.unordered),
    ] {
        for s in strings(o, key, what)? {
            list.push(Pattern::parse(&s).map_err(|e| format!("{what}: {key}: {e}"))?);
        }
    }
    Ok(r)
}

/// İstek yolu: tek `/` ile başlar (başka makineye yönlenemez), boşluk/denetim karakteri ve `#` yok.
fn valid_path(p: &str) -> bool {
    p.starts_with('/')
        && !p.starts_with("//")
        && p.bytes().all(|b| b.is_ascii_graphic() && b != b'#')
}

pub fn parse(text_in: &str) -> Result<Vec<Case>, String> {
    let root: Value = serde_json::from_str(text_in).map_err(|e| format!("JSON: {e}"))?;
    let root = object(&root, "kök", &["defaults", "requests"])?;
    let defaults = match root.get("defaults") {
        None => Rules::default(),
        Some(v) => rules(
            object(v, "defaults", &["ignore", "dynamic", "unordered"])?,
            "defaults",
            &Rules::default(),
        )?,
    };
    let list = root
        .get("requests")
        .and_then(Value::as_array)
        .ok_or("kök: \"requests\" dizisi gerekli")?;
    let mut out = Vec::with_capacity(list.len());
    for (i, v) in list.iter().enumerate() {
        let what = format!("requests[{i}]");
        let o = object(
            v,
            &what,
            &[
                "name",
                "method",
                "path",
                "body",
                "request_headers",
                "headers",
                "ignore",
                "dynamic",
                "unordered",
                "expect",
                "side_effect_free",
            ],
        )?;
        let path = text(o, "path", &what)?.ok_or_else(|| format!("{what}: \"path\" gerekli"))?;
        if !valid_path(&path) {
            return Err(format!("{what}: geçersiz yol"));
        }
        let method = text(o, "method", &what)?
            .unwrap_or_else(|| "GET".into())
            .to_ascii_uppercase();
        let request_headers = match o.get("request_headers") {
            None => Vec::new(),
            Some(v) => v
                .as_object()
                .ok_or_else(|| format!("{what}: \"request_headers\" nesne olmalı"))?
                .iter()
                .map(|(k, v)| {
                    v.as_str()
                        .map(|v| (k.clone(), v.to_string()))
                        .ok_or_else(|| format!("{what}: başlık değeri metin olmalı"))
                })
                .collect::<Result<_, _>>()?,
        };
        let expect_local = match text(o, "expect", &what)?.as_deref() {
            None => false,
            Some("local") => true,
            Some(_) => return Err(format!("{what}: \"expect\" yalnız \"local\"")),
        };
        let side_effect_free = match o.get("side_effect_free") {
            None => None,
            Some(v) => Some(
                v.as_bool()
                    .ok_or_else(|| format!("{what}: \"side_effect_free\" mantıksal olmalı"))?,
            ),
        };
        out.push(Case {
            name: text(o, "name", &what)?.unwrap_or_else(|| {
                // Sorguda sır olabilir: addan çıkar.
                format!("{method} {}", path.split('?').next().unwrap_or(""))
            }),
            body: match o.get("body") {
                None => None,
                Some(Value::String(s)) => Some(s.clone().into_bytes()),
                Some(v) => Some(v.to_string().into_bytes()),
            },
            request_headers,
            compare_headers: strings(o, "headers", &what)?
                .iter()
                .map(|h| h.to_ascii_lowercase())
                .collect(),
            rules: rules(o, &what, &defaults)?,
            expect_local,
            side_effect_free,
            method,
            path,
        });
    }
    Ok(out)
}
