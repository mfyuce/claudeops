//! `GET /api/instances` yerel dalı: web.py `_instances_list()` (Geçmiş sekmesi). Kayıtlar `instances.json` / DB
//! (`cops_state::instances::Instances`, salt okuma kipindeki [`StateDocs`]), "çalışıyor mu" süreç taramasından
//! (`cops_procscan::find_sessions`, CPU ölçmeden), rozet [`crate::badge`].
use crate::badge;
use cops_procscan::{find_sessions, Config, CpuMode};
use cops_state::instances::Instances;
use cops_state::{Json, Map, StateDocs};
use std::cmp::Ordering;
use std::collections::HashSet;

/// Python'un istisna verip YANIT YAZMADIĞI durumlar (ThreadingHTTPServer bağlantıyı kapatır; copsd arkasında 502). Rust
/// 500 `internal error` döner (bilinçli fark, `docs/rs-ep-state.md`).
#[derive(Debug, PartialEq)]
pub enum ListError {
    /// `/proc` listelenemedi (Python `psutil.process_iter` istisnası).
    Scan(String),
    /// Kayıt sözlük değil (`rec.get` -> `AttributeError`).
    NotDict(String),
    /// Sıralama anahtarları karşılaştırılamaz (`TypeError`: dize ile sayı, iki sözlük...).
    SortType,
}

impl std::fmt::Display for ListError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ListError::Scan(e) => write!(f, "süreç taraması: {e}"),
            ListError::NotDict(n) => write!(f, "kayıt sözlük değil: {n:?}"),
            ListError::SortType => f.write_str("sıralama anahtarları karşılaştırılamaz"),
        }
    }
}

/// `{s.name for s in find_sessions(measure_cpu=False)}`.
pub fn live_names(cfg: &Config) -> Result<HashSet<String>, ListError> {
    let scan = find_sessions(cfg, CpuMode::Skip);
    if let Some(e) = scan.diag.proc_root_error {
        return Err(ListError::Scan(e));
    }
    Ok(scan.sessions.into_iter().map(|s| s.name).collect())
}

/// Sıralama anahtarının Python karşılaştırma sınıfı.
enum Key<'a> {
    Num(&'a Json),
    Str(&'a str),
    /// Liste/sözlük (doğru değerli): Python'da yalnız kendi türüyle karşılaştırılır; burada desteklenmez.
    Other,
}

static ZERO: Json = Json::Int(0);

fn key_of(it: &Map) -> Key<'_> {
    let v = [it.get("last_started_at"), it.get("created_at")]
        .into_iter()
        .flatten()
        .find(|v| v.truthy());
    match v {
        None => Key::Num(&ZERO),
        Some(Json::Str(s)) => Key::Str(s),
        Some(j @ (Json::Int(_) | Json::BigInt(_) | Json::Float(_) | Json::Bool(_))) => Key::Num(j),
        Some(_) => Key::Other,
    }
}

/// Sayısal değer: tam sayı, `i64`e sığmayan tam sayı (işaret, ondalık basamaklar), kayan nokta.
enum Num<'a> {
    Int(i64),
    Big(bool, &'a str),
    Float(f64),
}

fn num(v: &Json) -> Num<'_> {
    match v {
        Json::Int(i) => Num::Int(*i),
        Json::Bool(b) => Num::Int(i64::from(*b)),
        Json::Float(f) => Num::Float(*f),
        Json::BigInt(s) => match s.strip_prefix('-') {
            Some(d) => Num::Big(true, d),
            None => Num::Big(false, s),
        },
        _ => Num::Int(0),
    }
}

/// Python `int` ile `float` karşılaştırması TAM (yuvarlamasız).
fn cmp_int_float(i: i64, f: f64) -> Ordering {
    const TWO63: f64 = 9_223_372_036_854_775_808.0;
    if f >= TWO63 {
        return Ordering::Less;
    }
    if f < -TWO63 {
        return Ordering::Greater;
    }
    let t = f.trunc();
    #[allow(clippy::cast_possible_truncation)]
    match i.cmp(&(t as i64)) {
        Ordering::Equal => (0.0).partial_cmp(&(f - t)).unwrap_or(Ordering::Equal),
        o => o,
    }
}

/// `i64`e sığmayan tam sayılar: işaret, sonra basamak sayısı ve sözlük sırası.
fn cmp_big(an: bool, a: &str, bn: bool, b: &str) -> Ordering {
    match (an, bn) {
        (true, false) => Ordering::Less,
        (false, true) => Ordering::Greater,
        _ => {
            let mag = a.len().cmp(&b.len()).then_with(|| a.cmp(b));
            if an {
                mag.reverse()
            } else {
                mag
            }
        }
    }
}

/// Sayıların TOPLAM sırası: Python ile aynı, yalnız NaN (Python'da sırasız) en küçük sayılır.
fn cmp_num(a: &Json, b: &Json) -> Ordering {
    let nan = |n: &Num| matches!(n, Num::Float(f) if f.is_nan());
    let (x, y) = (num(a), num(b));
    match (nan(&x), nan(&y)) {
        (true, true) => return Ordering::Equal,
        (true, false) => return Ordering::Less,
        (false, true) => return Ordering::Greater,
        _ => {}
    }
    match (x, y) {
        (Num::Int(p), Num::Int(q)) => p.cmp(&q),
        (Num::Float(p), Num::Float(q)) => p.partial_cmp(&q).unwrap_or(Ordering::Equal),
        (Num::Int(p), Num::Float(q)) => cmp_int_float(p, q),
        (Num::Float(p), Num::Int(q)) => cmp_int_float(q, p).reverse(),
        (Num::Big(an, a), Num::Big(bn, b)) => cmp_big(an, a, bn, b),
        (Num::Big(neg, _), Num::Int(_)) => {
            if neg {
                Ordering::Less
            } else {
                Ordering::Greater
            }
        }
        (Num::Int(_), Num::Big(neg, _)) => {
            if neg {
                Ordering::Greater
            } else {
                Ordering::Less
            }
        }
        // yaklaşık (f64'e çevrilir): 2^63 üstü tam sayı + kayan nokta zaman damgası gerçekçi değil
        (Num::Big(n, d), Num::Float(q)) => big_f64(n, d).partial_cmp(&q).unwrap_or(Ordering::Equal),
        (Num::Float(p), Num::Big(n, d)) => p.partial_cmp(&big_f64(n, d)).unwrap_or(Ordering::Equal),
    }
}

fn big_f64(neg: bool, digits: &str) -> f64 {
    let v: f64 = digits.parse().unwrap_or(f64::INFINITY);
    if neg {
        -v
    } else {
        v
    }
}

/// `items.sort(key=..., reverse=True)`: azalan, eşitlerde ilk sıra korunur (Python `reverse` kararlıdır).
fn sort_desc(items: &mut [Map]) -> Result<(), ListError> {
    if items.len() >= 2 {
        let (mut nums, mut strs) = (false, false);
        for it in items.iter() {
            match key_of(it) {
                Key::Num(_) => nums = true,
                Key::Str(_) => strs = true,
                Key::Other => return Err(ListError::SortType),
            }
        }
        if nums && strs {
            return Err(ListError::SortType);
        }
    }
    items.sort_by(|a, b| match (key_of(b), key_of(a)) {
        (Key::Num(x), Key::Num(y)) => cmp_num(x, y),
        (Key::Str(x), Key::Str(y)) => x.cmp(y),
        _ => Ordering::Equal, // yukarıda elendi
    });
    Ok(())
}

/// `_instances_list()`: `{"ok": true, "instances": [...]}`. `live` = çalışan oturum adları ([`live_names`]).
pub fn payload(docs: &StateDocs, live: &HashSet<String>) -> Result<Json, ListError> {
    let mut items: Vec<Map> = Vec::new();
    for (name, rec) in Instances::new(docs).load() {
        let Json::Object(mut it) = rec else {
            return Err(ListError::NotDict(name));
        };
        if it.get("forgotten").is_some_and(Json::truthy) {
            continue;
        }
        let running = live.contains(&name);
        it.insert("name".into(), Json::Str(name));
        it.insert("running".into(), Json::Bool(running));
        it.insert("host".into(), "local".into());
        items.push(it);
    }
    sort_desc(&mut items)?;
    // rozet yalnız ek bilgi: indeks kurulamazsa (Python istisnayı yutar) hiçbir satıra konmaz
    if let Ok(owners) = badge::owners(docs) {
        for it in &mut items {
            let name = it.get("name").and_then(Json::as_str).unwrap_or("");
            if let Some(b) = badge::badge(name, &owners) {
                let title = b.get("title").cloned().unwrap_or_default();
                it.insert("badge".into(), b);
                it.insert("title".into(), title);
            }
        }
    }
    let mut out = Map::new();
    out.insert("ok".into(), Json::Bool(true));
    out.insert(
        "instances".into(),
        Json::Array(items.into_iter().map(Json::Object).collect()),
    );
    Ok(Json::Object(out))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn j(s: &str) -> Json {
        Json::parse(s).unwrap()
    }

    #[test]
    fn numeric_order_is_exact_and_total() {
        let big = (1i64 << 53) + 1;
        assert_eq!(
            cmp_num(&Json::Int(big), &Json::Float((1i64 << 53) as f64)),
            Ordering::Greater
        );
        assert_eq!(cmp_num(&Json::Int(5), &Json::Float(5.0)), Ordering::Equal);
        assert_eq!(cmp_num(&Json::Int(5), &Json::Float(5.5)), Ordering::Less);
        assert_eq!(
            cmp_num(&Json::Int(-5), &Json::Float(-5.5)),
            Ordering::Greater
        );
        assert_eq!(cmp_num(&Json::Bool(true), &Json::Int(1)), Ordering::Equal);
        assert_eq!(
            cmp_num(&j("99999999999999999999"), &Json::Int(i64::MAX)),
            Ordering::Greater
        );
        assert_eq!(
            cmp_num(&j("-99999999999999999999"), &j("-99999999999999999998")),
            Ordering::Less
        );
        assert_eq!(
            cmp_num(&Json::Float(f64::NAN), &Json::Int(i64::MIN)),
            Ordering::Less
        );
        assert_eq!(
            cmp_num(&Json::Int(1), &Json::Float(f64::INFINITY)),
            Ordering::Less
        );
    }

    #[test]
    fn mixed_sort_keys_are_a_type_error() {
        let mk = |v: &str| match j(&format!(r#"{{"created_at": {v}}}"#)) {
            Json::Object(m) => m,
            _ => unreachable!(),
        };
        assert_eq!(
            sort_desc(&mut [mk("1"), mk(r#""x""#)]),
            Err(ListError::SortType)
        );
        assert_eq!(
            sort_desc(&mut [mk("[1]"), mk("[2]")]),
            Err(ListError::SortType)
        );
        assert_eq!(
            sort_desc(&mut [mk(r#""x""#)]),
            Ok(()),
            "tek öğe karşılaştırılmaz"
        );
        // falsy anahtar 0 olur: "" ile sayı karışabilir
        assert_eq!(sort_desc(&mut [mk(r#""""#), mk("3")]), Ok(()));
    }
}
