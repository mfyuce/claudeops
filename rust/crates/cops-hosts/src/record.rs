//! Uzak host kaydı (`hosts.json`) modeli ve SAF kayıt işlemleri. Okuma/yazma ve kilit çağıranındır (`cops-state`
//! gelene kadar): bu modül yalnız parametre olarak aldığı listeyi dönüştürür.

use std::collections::BTreeSet;
use std::fmt;

use serde_json::{Map, Value};

use crate::consts::LOCAL_HOST_NAME;
use crate::endpoint::Endpoint;
use crate::guard;

/// Sır: `Debug`/`Display`/`Serialize` değeri vermez; yalnız [`expose`](Secret::expose) ile okunur.
#[derive(Clone, Default, PartialEq, Eq)]
pub struct Secret(String);

impl Secret {
    pub fn new(s: impl Into<String>) -> Secret {
        Secret(s.into())
    }
    pub fn expose(&self) -> &str {
        &self.0
    }
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

impl fmt::Debug for Secret {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(if self.0.is_empty() {
            "\"\""
        } else {
            "<redacted>"
        })
    }
}

/// Python `str.strip()`: Rust `trim` kümesine ek olarak U+001C..U+001F.
pub fn py_strip(s: &str) -> &str {
    s.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}

/// İstekten gelen `host` alanı (query ya da gövde): boş/yok = yerel.
pub fn normalize_host(raw: Option<&str>) -> &str {
    match raw.map(py_strip) {
        Some(h) if !h.is_empty() => h,
        _ => LOCAL_HOST_NAME,
    }
}

/// Bir host kaydı. Tanınmayan alanlar `extra`da korunur (ileri sürüm alanları yazımda silinmez).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct HostRecord {
    pub name: String,
    pub base_url: String,
    pub token: Secret,
    /// Boş = gRPC hiç denenmez.
    pub grpc_url: String,
    /// Öncelik sırasıyla ek aday adresler.
    pub extra_urls: Vec<String>,
    pub extra: Map<String, Value>,
}

const KNOWN: [&str; 5] = ["name", "base_url", "token", "grpc_url", "extra_urls"];

impl HostRecord {
    /// Nesne değilse ya da metin `name` yoksa `None`. Yanlış tipteki alanlar boş sayılır.
    pub fn from_value(v: &Value) -> Option<HostRecord> {
        let o = v.as_object()?;
        let s = |k: &str| o.get(k).and_then(Value::as_str).unwrap_or("").to_string();
        Some(HostRecord {
            name: o.get("name")?.as_str()?.to_string(),
            base_url: s("base_url"),
            token: Secret(s("token")),
            grpc_url: s("grpc_url"),
            extra_urls: o
                .get("extra_urls")
                .and_then(Value::as_array)
                .map(|a| {
                    a.iter()
                        .filter_map(|u| u.as_str().map(str::to_string))
                        .collect()
                })
                .unwrap_or_default(),
            extra: o
                .iter()
                .filter(|(k, _)| !KNOWN.contains(&k.as_str()))
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect(),
        })
    }

    /// Dosya biçimi: boş `grpc_url`/`extra_urls` yazılmaz.
    pub fn to_value(&self) -> Value {
        let mut o = self.extra.clone();
        o.insert("name".into(), self.name.clone().into());
        o.insert("base_url".into(), self.base_url.clone().into());
        o.insert("token".into(), self.token.expose().into());
        if !self.grpc_url.is_empty() {
            o.insert("grpc_url".into(), self.grpc_url.clone().into());
        }
        if !self.extra_urls.is_empty() {
            o.insert("extra_urls".into(), self.extra_urls.clone().into());
        }
        Value::Object(o)
    }

    /// Tarayıcıya giden TEK görünüm: token asla dönmez.
    pub fn public(&self) -> Value {
        serde_json::json!({
            "name": self.name,
            "base_url": self.base_url,
            "grpc_url": if self.grpc_url.is_empty() { Value::Null } else { self.grpc_url.clone().into() },
            "extra_urls": self.extra_urls,
            "has_token": !self.token.is_empty(),
        })
    }
}

/// `hosts` belgesinin ayrıştırma sonucu.
#[derive(Debug, Default, Clone, PartialEq)]
pub struct Parsed {
    pub hosts: Vec<HostRecord>,
    /// JSON değil ya da liste değil: bu listeyi yazmak TÜM kayıt ve token'ları silerdi, yazma REDDEDİLMELİ.
    pub corrupt: bool,
    /// Düşürülen kayıt var (nesne değil / adsız): yazmadan önce ham dosya yedeklenmeli.
    pub irregular: bool,
}

/// Boş / yalnız boşluk metin = temiz boş liste.
pub fn parse_document(raw: &[u8]) -> Parsed {
    let corrupt = Parsed {
        corrupt: true,
        ..Parsed::default()
    };
    let Ok(text) = std::str::from_utf8(raw) else {
        return corrupt;
    };
    if text.trim().is_empty() {
        return Parsed::default();
    }
    match serde_json::from_str::<Value>(text) {
        Ok(v) => parse_value(&v),
        Err(_) => corrupt,
    }
}

/// DB değeri gibi hazır ayrıştırılmış belge.
pub fn parse_value(v: &Value) -> Parsed {
    let Some(a) = v.as_array() else {
        return Parsed {
            corrupt: true,
            ..Parsed::default()
        };
    };
    let hosts: Vec<_> = a.iter().filter_map(HostRecord::from_value).collect();
    Parsed {
        irregular: hosts.len() != a.len(),
        hosts,
        corrupt: false,
    }
}

pub fn find<'a>(hosts: &'a [HostRecord], name: &str) -> Option<&'a HostRecord> {
    hosts.iter().find(|h| h.name == name)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecordError {
    InvalidName,
    ReservedName,
    InvalidUrl,
    InvalidGrpcUrl,
    InvalidExtraUrl,
    BlockedHost,
    TokenRequired,
    Corrupt,
}

impl RecordError {
    /// Panelin gösterdiği metin (Python `hosts.ERR`).
    pub fn message(self, lang: &str) -> &'static str {
        let (tr, en) = match self {
            RecordError::InvalidName => (
                "geçersiz host adı — küçük harfle başlamalı, sadece harf/rakam/_/- içerebilir",
                "invalid host name — must start with a lowercase letter, only letters/digits/_/- allowed",
            ),
            RecordError::ReservedName => (
                "'local' ayrılmış bir isim, host adı olarak kullanılamaz",
                "'local' is reserved, cannot be used as a host name",
            ),
            RecordError::InvalidUrl => (
                "geçersiz base URL — http:// veya https:// ile başlamalı",
                "invalid base URL — must start with http:// or https://",
            ),
            RecordError::InvalidGrpcUrl => (
                "geçersiz gRPC URL — http:// veya https:// ile başlamalı (boş bırakılabilir)",
                "invalid gRPC URL — must start with http:// or https:// (may be left empty)",
            ),
            RecordError::InvalidExtraUrl => (
                "ek URL listesindeki bir adres http:// veya https:// ile başlamıyor",
                "one of the extra URLs doesn't start with http:// or https://",
            ),
            RecordError::BlockedHost => (
                "bu adres loopback veya link-local bir IP'ye işaret ediyor (ör. bulut metadata servisi) — uzak host olarak kaydedilemez",
                "this address points at a loopback or link-local IP (e.g. a cloud metadata service) — it cannot be registered as a remote host",
            ),
            RecordError::TokenRequired => ("yeni bir host için token zorunlu", "token is required for a new host"),
            RecordError::Corrupt => (
                "hosts.json bozuk/okunamıyor — kayıtların silinmemesi için yazma reddedildi (yedek: hosts.json.corrupt-*); dosyayı elle düzeltin",
                "hosts.json is corrupt/unreadable — write refused so no records are lost (backup: hosts.json.corrupt-*); fix the file by hand",
            ),
        };
        if lang == "en" {
            en
        } else {
            tr
        }
    }
}

/// Doğrulanmış kayıt isteği. Ağ (DNS) denetimi [`Draft::new`]da, yani yazım kilidi DIŞINDA yapılır.
#[derive(Debug, Clone)]
pub struct Draft {
    name: String,
    base_url: String,
    token: Secret,
    grpc_url: String,
    extra_urls: Vec<String>,
}

impl Draft {
    pub async fn new(
        name: &str,
        base_url: &str,
        token: &str,
        grpc_url: &str,
        extra_urls: &str,
        reach_ports: &BTreeSet<u16>,
    ) -> Result<Draft, RecordError> {
        let clean = |u: &str| py_strip(u).trim_end_matches('/').to_string();
        let d = Draft {
            name: py_strip(name).to_string(),
            base_url: clean(base_url),
            token: Secret::new(py_strip(token)),
            grpc_url: clean(grpc_url),
            extra_urls: extra_urls
                .split([',', '\n'])
                .filter(|u| !py_strip(u).is_empty())
                .map(clean)
                .collect(),
        };
        if !valid_name(&d.name) {
            return Err(RecordError::InvalidName);
        }
        if d.name == LOCAL_HOST_NAME {
            return Err(RecordError::ReservedName);
        }
        let ok = |u: &str| Endpoint::parse(u).is_some();
        if !ok(&d.base_url) {
            return Err(RecordError::InvalidUrl);
        }
        if !d.grpc_url.is_empty() && !ok(&d.grpc_url) {
            return Err(RecordError::InvalidGrpcUrl);
        }
        if !d.extra_urls.iter().all(|u| ok(u)) {
            return Err(RecordError::InvalidExtraUrl);
        }
        // Token başlığa/URL'e gider: denetim karakteri taşıyamaz.
        if d.token.expose().chars().any(char::is_control) {
            return Err(RecordError::TokenRequired);
        }
        let mut check: Vec<&str> = vec![&d.base_url];
        if !d.grpc_url.is_empty() {
            check.push(&d.grpc_url);
        }
        check.extend(
            d.extra_urls
                .iter()
                .map(String::as_str)
                .filter(|u| !guard::is_reach_loopback(u, reach_ports)),
        );
        for u in check {
            if guard::host_is_blocked(u).await {
                return Err(RecordError::BlockedHost);
            }
        }
        Ok(d)
    }

    /// Upsert. Var olan adda boş token mevcut olanı KORUR; boş `grpc_url`/`extra_urls` KALDIRIR.
    pub fn apply(&self, current: &Parsed) -> Result<Vec<HostRecord>, RecordError> {
        if current.corrupt {
            return Err(RecordError::Corrupt);
        }
        let mut hosts = current.hosts.clone();
        let existing = find(&hosts, &self.name).cloned();
        let token = match (&existing, self.token.is_empty()) {
            (None, true) => return Err(RecordError::TokenRequired),
            (Some(e), true) => e.token.clone(),
            (_, false) => self.token.clone(),
        };
        let record = HostRecord {
            name: self.name.clone(),
            base_url: self.base_url.clone(),
            token,
            grpc_url: self.grpc_url.clone(),
            extra_urls: self.extra_urls.clone(),
            extra: existing
                .as_ref()
                .map(|e| e.extra.clone())
                .unwrap_or_default(),
        };
        if existing.is_none() {
            hosts.push(record);
        } else {
            for h in hosts.iter_mut().filter(|h| h.name == self.name) {
                *h = record.clone();
            }
        }
        Ok(hosts)
    }
}

fn valid_name(n: &str) -> bool {
    n.starts_with(|c: char| c.is_ascii_lowercase())
        && n.bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'-')
}

/// Çalışan ek adresi `base_url` yapar, eskisini `extra_urls` başına koyar. Değişiklik yoksa (host yok, zaten o adres,
/// bozuk belge) `None`: çağıran yazmaz.
pub fn promote_base_url(
    current: &Parsed,
    name: &str,
    new_base_url: &str,
) -> Option<Vec<HostRecord>> {
    if current.corrupt {
        return None;
    }
    let mut hosts = current.hosts.clone();
    let h = hosts.iter_mut().find(|h| h.name == name)?;
    if h.base_url == new_base_url {
        return None;
    }
    let old = std::mem::replace(&mut h.base_url, new_base_url.to_string());
    h.extra_urls.retain(|u| u != new_base_url);
    if !old.is_empty() {
        h.extra_urls.insert(0, old);
    }
    Some(hosts)
}

/// İdempotent silme.
pub fn remove(current: &Parsed, name: &str) -> Result<Vec<HostRecord>, RecordError> {
    if current.corrupt {
        return Err(RecordError::Corrupt);
    }
    Ok(current
        .hosts
        .iter()
        .filter(|h| h.name != name)
        .cloned()
        .collect())
}

pub fn to_document(hosts: &[HostRecord]) -> Value {
    Value::Array(hosts.iter().map(HostRecord::to_value).collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::guard::reach_loopback_ports;

    async fn draft(
        name: &str,
        url: &str,
        token: &str,
        grpc: &str,
        extra: &str,
    ) -> Result<Draft, RecordError> {
        Draft::new(name, url, token, grpc, extra, &reach_loopback_ports(None)).await
    }

    fn err(r: Result<Draft, RecordError>) -> RecordError {
        r.expect_err("error expected")
    }

    #[test]
    fn corrupt_and_irregular_documents() {
        assert_eq!(parse_document(b"  \n"), Parsed::default());
        for bad in [&b"{"[..], b"{\"a\":1}", b"\xff\xfe", b"null"] {
            assert!(parse_document(bad).corrupt, "{bad:?}");
        }
        let p = parse_document(
            br#"[{"name":"a","token":5,"extra_urls":"x"}, 3, {"base_url":"u"}, {"name":7}]"#,
        );
        assert!(!p.corrupt && p.irregular);
        assert_eq!(p.hosts.len(), 1);
        assert_eq!(
            (p.hosts[0].token.expose(), p.hosts[0].extra_urls.len()),
            ("", 0)
        );
    }

    #[test]
    fn unknown_fields_survive_and_token_never_public() {
        let p = parse_document(
            br#"[{"name":"a","base_url":"http://10.0.0.1","token":"SECRET","future":{"x":1}}]"#,
        );
        let h = &p.hosts[0];
        assert_eq!(h.to_value()["future"]["x"], 1);
        assert!(!h.public().to_string().contains("SECRET"));
        assert!(!format!("{h:?}").contains("SECRET"));
        assert_eq!(h.public()["has_token"], true);
        assert!(h.public()["grpc_url"].is_null());
    }

    #[tokio::test]
    async fn validation_order() {
        use RecordError::*;
        assert_eq!(
            err(draft("A", "http://10.0.0.1", "t", "", "").await),
            InvalidName
        );
        assert_eq!(err(draft("a\n", "x", "t", "", "").await), InvalidUrl);
        assert_eq!(
            err(draft("local", "http://10.0.0.1", "t", "", "").await),
            ReservedName
        );
        assert_eq!(err(draft("a", "ftp://x", "t", "", "").await), InvalidUrl);
        assert_eq!(
            err(draft("a", "http://10.0.0.1", "t", "x", "").await),
            InvalidGrpcUrl
        );
        assert_eq!(
            err(draft("a", "http://10.0.0.1", "t", "", "http://10.0.0.2, nope").await),
            InvalidExtraUrl
        );
        assert_eq!(
            err(draft("a", "http://127.0.0.1:18765", "t", "", "").await),
            BlockedHost
        );
        assert_eq!(
            err(draft("a", "http://10.0.0.1", "t", "http://169.254.169.254", "").await),
            BlockedHost
        );
        assert_eq!(
            err(draft("a", "http://10.0.0.1", "t", "", "http://127.0.0.1:1").await),
            BlockedHost
        );
        assert!(
            draft("a", "http://10.0.0.1", "t", "", "http://127.0.0.1:18765")
                .await
                .is_ok()
        );
    }

    #[tokio::test]
    async fn upsert_keeps_token_and_unknown_fields_clears_optionals() {
        let cur = parse_document(
            br#"[{"name":"a","base_url":"http://10.0.0.1","token":"T","grpc_url":"http://10.0.0.1:1","extra_urls":["http://10.0.0.9"],"k":1}]"#,
        );
        let d = draft("a", " http://10.0.0.2/ ", "", "", "").await.unwrap();
        let h = &d.apply(&cur).unwrap()[0];
        assert_eq!(
            (h.base_url.as_str(), h.token.expose(), h.grpc_url.as_str()),
            ("http://10.0.0.2", "T", "")
        );
        assert!(h.extra_urls.is_empty() && h.extra["k"] == 1);
        assert!(h.to_value().get("grpc_url").is_none());
        let new = draft("b", "http://10.0.0.2", "", "", "").await.unwrap();
        assert_eq!(new.apply(&cur).err(), Some(RecordError::TokenRequired));
        assert_eq!(
            d.apply(&parse_document(b"{")).err(),
            Some(RecordError::Corrupt)
        );
    }

    #[test]
    fn promote_and_remove() {
        let cur = parse_document(br#"[{"name":"a","base_url":"u1","extra_urls":["u2","u3"]}]"#);
        let h = &promote_base_url(&cur, "a", "u3").unwrap()[0];
        assert_eq!(
            (h.base_url.as_str(), h.extra_urls.clone()),
            ("u3", vec!["u1".to_string(), "u2".to_string()])
        );
        assert!(promote_base_url(&cur, "a", "u1").is_none());
        assert!(promote_base_url(&cur, "zz", "u3").is_none());
        assert!(promote_base_url(&parse_document(b"{"), "a", "u3").is_none());
        assert!(remove(&cur, "zz").unwrap().len() == 1 && remove(&cur, "a").unwrap().is_empty());
        assert_eq!(
            remove(&parse_document(b"{"), "a").err(),
            Some(RecordError::Corrupt)
        );
    }
}
