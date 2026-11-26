//! İsteğin dokunduğu TÜM kaynaklar (Python `authz.resources_from`): authorizer hepsine izin vermeli.
//! Python'dan BİLEREK daha sıkı: nesne olmayan/bozuk gövde ve metin olmayan dolu kaynak alanı `BadResource` (çağıran reddeder).

use cops_auth::authz::Resource;
use serde_json::{Map, Value};

/// Kaynak çıkarılamadı: istek REDDEDİLMELİ.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BadResource;

/// Python `str.strip()` boşluk kümesi: Unicode White_Space ve U+001C..U+001F.
fn strip(s: &str) -> &str {
    s.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}

/// Python `parse_qs`: `=`siz ve boş değerli parçalar atlanır, ad ve değer yüzde çözülür (bozuk kaçış aynen kalır). Tek
/// gerçekleştirme `cops_auth::parse_qs` (token ayrıştırması da onu kullanır).
pub use cops_auth::parse_qs;

/// Gövde alanı: boş sayılan değer (Python "falsy") = `None`; dolu ama metin olmayan = red.
fn text(v: Option<&Value>) -> Result<Option<&str>, BadResource> {
    let empty = match v {
        None | Some(Value::Null) | Some(Value::Bool(false)) => true,
        Some(Value::Number(n)) => n.as_f64() == Some(0.0),
        Some(Value::String(s)) => s.is_empty(),
        Some(Value::Array(a)) => a.is_empty(),
        Some(Value::Object(o)) => o.is_empty(),
        Some(Value::Bool(true)) => false,
    };
    match v {
        _ if empty => Ok(None),
        Some(Value::String(s)) => Ok(Some(s)),
        _ => Err(BadResource),
    }
}

fn session(out: &mut Vec<Resource>, host: &str, name: &str) {
    let name = strip(name);
    if !name.is_empty() && !out.iter().any(|r| r.host == host && r.name == name) {
        out.push(Resource {
            kind: "session".into(),
            host: host.into(),
            name: name.into(),
            ..Resource::default()
        });
    }
}

/// `path`/`raw_query`: istek hedefi; `body`: JSON gövde (gövdesiz istekte `None`); `approval_session`: onay koşu anahtarı ->
/// oturum adı (kayıt Python'da/depoda; bilinmiyorsa `None`). Dönüş hiçbir zaman boş değildir.
pub fn resources_from(
    path: &str,
    raw_query: &str,
    body: Option<&[u8]>,
    approval_session: &dyn Fn(&str) -> Option<String>,
) -> Result<Vec<Resource>, BadResource> {
    let src: Map<String, Value> = match body {
        None | Some([]) => Map::new(),
        Some(b) => serde_json::from_slice(b).map_err(|_| BadResource)?,
    };
    let qs = parse_qs(raw_query);
    let first = |key: &str| {
        qs.iter()
            .find(|(k, _)| k == key)
            .map_or("", |(_, v)| v.as_str())
    };
    // gövde doluysa gövde, değilse sorgu
    let pick = |key: &str| -> Result<String, BadResource> {
        Ok(text(src.get(key))?
            .unwrap_or_else(|| first(key))
            .to_string())
    };

    if path.starts_with("/api/steward/") {
        // burada `name` PROJE adıdır: kaynak değnekçi kimliği
        let sid = pick("steward")?;
        let sid = match strip(&sid) {
            "" => "default",
            s => s,
        };
        return Ok(vec![Resource {
            kind: "steward".into(),
            steward: sid.into(),
            ..Resource::default()
        }]);
    }
    if path == "/api/ucli/approvals" {
        let sess = approval_session(&pick("run_key")?).unwrap_or_default();
        return Ok(vec![if sess.is_empty() {
            Resource::default()
        } else {
            Resource {
                kind: "session".into(),
                name: sess,
                ..Resource::default()
            }
        }]);
    }
    let host = pick("host")?;
    let mut out = Vec::new();
    if path == "/api/new-chat" {
        // handler gövdedeki `base`ten türetir, `name`i okumaz: kaynak `base`
        session(&mut out, &host, text(src.get("base"))?.unwrap_or(""));
    } else {
        session(&mut out, &host, &pick("name")?);
    }
    if path.starts_with("/v1/") {
        session(&mut out, "", text(src.get("model"))?.unwrap_or(""));
    }
    if let Some(Value::Array(parts)) = src.get("participants") {
        for it in parts.iter().filter_map(Value::as_object) {
            let h = text(it.get("host"))?.unwrap_or("");
            session(&mut out, h, text(it.get("name"))?.unwrap_or(""));
        }
    }
    if let Some(Value::Array(names)) = src.get("names") {
        for n in names {
            session(&mut out, &host, text(Some(n))?.unwrap_or(""));
        }
    }
    for (_, chunk) in qs.iter().filter(|(k, _)| k == "names") {
        for n in chunk.split(',') {
            session(&mut out, &host, n);
        }
    }
    if out.is_empty() {
        out.push(Resource {
            host,
            ..Resource::default()
        });
    }
    Ok(out)
}
