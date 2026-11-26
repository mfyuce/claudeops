//! JSON farkı: anahtar sırası önemsiz, sayılar sayısal karşılaştırılır (`1` == `1.0`), izinli alanlar [`Rules`] ile.

use serde_json::{Number, Value};

#[derive(Debug, Clone, PartialEq, Eq)]
enum Part {
    One,
    Many,
    Key(String),
}

/// Nokta ile ayrılmış alan deseni; `*` tek parça, `**` sıfır ya da daha çok parça, `$` kökün kendisi.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Pattern(Vec<Part>);

impl Pattern {
    pub fn parse(s: &str) -> Result<Pattern, String> {
        if s == "$" {
            return Ok(Pattern(Vec::new()));
        }
        s.split('.')
            .map(|p| match p {
                "" => Err(format!("geçersiz desen {s:?}")),
                "*" => Ok(Part::One),
                "**" => Ok(Part::Many),
                k => Ok(Part::Key(k.to_string())),
            })
            .collect::<Result<_, _>>()
            .map(Pattern)
    }

    fn matches(&self, path: &[String]) -> bool {
        fn go(p: &[Part], s: &[String]) -> bool {
            match p.split_first() {
                None => s.is_empty(),
                Some((Part::Many, rest)) => (0..=s.len()).any(|i| go(rest, &s[i..])),
                Some((part, rest)) => s.split_first().is_some_and(|(head, tail)| {
                    (matches!(part, Part::One) || matches!(part, Part::Key(k) if k == head))
                        && go(rest, tail)
                }),
            }
        }
        go(&self.0, path)
    }
}

#[derive(Debug, Clone, Default)]
pub struct Rules {
    pub ignore: Vec<Pattern>,
    pub dynamic: Vec<Pattern>,
    pub unordered: Vec<Pattern>,
}

fn hit(list: &[Pattern], path: &[String]) -> bool {
    list.iter().any(|p| p.matches(path))
}

/// Tek fark. Değerler sır taşıyabilir: yazdırma kararı çağıranın.
#[derive(Debug, Clone, PartialEq)]
pub struct Diff {
    /// Nokta ile ayrılmış yer (`$` kök).
    pub at: String,
    pub what: &'static str,
    pub python: Option<Value>,
    pub rust: Option<Value>,
}

fn place(path: &[String]) -> String {
    if path.is_empty() {
        "$".into()
    } else {
        path.join(".")
    }
}

pub fn kind(v: &Value) -> &'static str {
    match v {
        Value::Null => "null",
        Value::Bool(_) => "bool",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

fn same_number(a: &Number, b: &Number) -> bool {
    if a == b {
        return true;
    }
    let int = |n: &Number| {
        n.as_i64()
            .map(i128::from)
            .or_else(|| n.as_u64().map(i128::from))
    };
    match (int(a), int(b)) {
        (Some(x), Some(y)) => x == y,
        // Biri kayan: yalnız tam temsil edilen değerler eşit (büyük tamsayıda yuvarlama eşitlik sayılmaz).
        (Some(i), None) => b.as_f64().is_some_and(|f| f == i as f64 && f as i128 == i),
        (None, Some(i)) => a.as_f64().is_some_and(|f| f == i as f64 && f as i128 == i),
        (None, None) => a.as_f64() == b.as_f64(),
    }
}

/// Sırasız dizi elemanlarının kıyas anahtarı: atılan/dinamik alanlar çıkarılmış, sayıları tekleştirilmiş kanonik metin
/// (`serde_json` nesne anahtarlarını sıralı tutar).
fn canonical(v: &Value, path: &mut Vec<String>, r: &Rules) -> Value {
    if hit(&r.dynamic, path) {
        return Value::from(kind(v));
    }
    let mut child = |k: String, v: &Value| {
        path.push(k);
        let out = (!hit(&r.ignore, path)).then(|| canonical(v, path, r));
        path.pop();
        out
    };
    match v {
        Value::Object(o) => Value::Object(
            o.iter()
                .filter_map(|(k, v)| child(k.clone(), v).map(|v| (k.clone(), v)))
                .collect(),
        ),
        Value::Array(a) => {
            let mut out: Vec<Value> = a
                .iter()
                .enumerate()
                .filter_map(|(i, v)| child(i.to_string(), v))
                .collect();
            if hit(&r.unordered, path) {
                out.sort_by_cached_key(Value::to_string);
            }
            Value::Array(out)
        }
        Value::Number(n) => match n.as_f64() {
            Some(f) if n.is_f64() && f.fract() == 0.0 && f.abs() < 9e15 => Value::from(f as i64),
            _ => v.clone(),
        },
        _ => v.clone(),
    }
}

fn walk(py: &Value, rs: &Value, path: &mut Vec<String>, r: &Rules, out: &mut Vec<Diff>) {
    let diff = |what, path: &[String]| Diff {
        at: place(path),
        what,
        python: Some(py.clone()),
        rust: Some(rs.clone()),
    };
    if hit(&r.dynamic, path) {
        if kind(py) != kind(rs) {
            out.push(diff("tür", path));
        }
        return;
    }
    match (py, rs) {
        (Value::Object(a), Value::Object(b)) => {
            let mut keys: Vec<&String> = a.keys().chain(b.keys()).collect();
            keys.sort();
            keys.dedup();
            for k in keys {
                path.push(k.clone());
                if !hit(&r.ignore, path) {
                    match (a.get(k), b.get(k)) {
                        (Some(x), Some(y)) => walk(x, y, path, r, out),
                        (x, y) => out.push(Diff {
                            at: place(path),
                            what: if x.is_some() {
                                "Rust'ta yok"
                            } else {
                                "Python'da yok"
                            },
                            python: x.cloned(),
                            rust: y.cloned(),
                        }),
                    }
                }
                path.pop();
            }
        }
        (Value::Array(a), Value::Array(b)) => {
            if hit(&r.unordered, path) {
                let sorted = |list: &[Value], path: &mut Vec<String>| {
                    let mut v: Vec<(String, Value)> = Vec::new();
                    for (i, item) in list.iter().enumerate() {
                        path.push(i.to_string());
                        if !hit(&r.ignore, path) {
                            let c = canonical(item, path, r);
                            v.push((c.to_string(), item.clone()));
                        }
                        path.pop();
                    }
                    v.sort_by(|x, y| x.0.cmp(&y.0));
                    v
                };
                let (x, mut y) = (sorted(a, path), sorted(b, path));
                for (key, item) in x {
                    match y.iter().position(|(k, _)| *k == key) {
                        Some(i) => {
                            y.remove(i);
                        }
                        None => out.push(Diff {
                            at: place(path),
                            what: "eleman Rust'ta yok",
                            python: Some(item),
                            rust: None,
                        }),
                    }
                }
                out.extend(y.into_iter().map(|(_, item)| Diff {
                    at: place(path),
                    what: "eleman Python'da yok",
                    python: None,
                    rust: Some(item),
                }));
                return;
            }
            if a.len() != b.len() {
                out.push(diff("dizi uzunluğu", path));
            }
            for (i, (x, y)) in a.iter().zip(b).enumerate() {
                path.push(i.to_string());
                if !hit(&r.ignore, path) {
                    walk(x, y, path, r, out);
                }
                path.pop();
            }
        }
        (Value::Number(a), Value::Number(b)) => {
            if !same_number(a, b) {
                out.push(diff("değer", path));
            }
        }
        _ if kind(py) != kind(rs) => out.push(diff("tür", path)),
        _ => {
            if py != rs {
                out.push(diff("değer", path));
            }
        }
    }
}

/// Python ve Rust yanıt gövdelerinin farkları (boş = eşit).
pub fn diff(python: &Value, rust: &Value, rules: &Rules) -> Vec<Diff> {
    let mut out = Vec::new();
    let mut path = Vec::new();
    if !hit(&rules.ignore, &path) {
        walk(python, rust, &mut path, rules, &mut out);
    }
    out
}
