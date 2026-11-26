#![allow(dead_code)] // yardımcıların tümü her grupta kullanılmaz
use flate2::read::GzDecoder;
use serde::de::DeserializeOwned;
use serde_json::{Map, Value};
use std::collections::HashMap;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;

pub fn vectors_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("fixtures/vectors")
}

/// Kaydedilmiş tek çağrı: Python argümanları (ada göre), `_now()` değeri, geri çağrı tabloları.
pub struct Case {
    pub args: Map<String, Value>,
    pub now: f64,
    pub callbacks: Map<String, Value>,
    /// Python'un yerinde DEĞİŞTİRDİĞİ argümanlar (çağrı sonrası hâlleri).
    pub after: Map<String, Value>,
    pub ret: Value,
}

impl Case {
    /// Zorunlu argüman.
    pub fn arg<T: DeserializeOwned>(&self, name: &str) -> T {
        let v = self.args.get(name).unwrap_or_else(|| panic!("argüman yok: {name}"));
        serde_json::from_value(v.clone()).unwrap_or_else(|e| panic!("argüman çözülemedi: {name}: {e}: {v}"))
    }

    /// Verilmemiş (Python varsayılanı geçerli) ya da `None` olabilen argüman.
    pub fn opt<T: DeserializeOwned>(&self, name: &str) -> Option<T> {
        match self.args.get(name) {
            None | Some(Value::Null) => None,
            Some(_) => Some(self.arg(name)),
        }
    }

    /// Verilmemişse Python'daki varsayılan.
    pub fn or<T: DeserializeOwned>(&self, name: &str, default: T) -> T {
        if self.args.contains_key(name) {
            self.arg(name)
        } else {
            default
        }
    }

    pub fn str(&self, name: &str) -> String {
        self.arg(name)
    }

    /// Kaydedilmiş geri çağrı: `[[argümanlar], sonuç]` çiftlerinden arama tablosu (anahtar = argümanların JSON'u).
    pub fn callback(&self, name: &str) -> Option<HashMap<String, Value>> {
        let pairs = self.callbacks.get(name)?.as_array()?;
        Some(pairs.iter().map(|p| (p[0].to_string(), p[1].clone())).collect())
    }
}

/// JSON eşitliği: sayılar değerce (1 == 1.0), nesnelerde anahtar sırası önemsiz.
pub fn same(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Number(x), Value::Number(y)) => {
            x == y || matches!((x.as_f64(), y.as_f64()), (Some(p), Some(q)) if (p - q).abs() <= 1e-6)
        }
        (Value::Array(x), Value::Array(y)) => x.len() == y.len() && x.iter().zip(y).all(|(p, q)| same(p, q)),
        (Value::Object(x), Value::Object(y)) => {
            x.len() == y.len() && x.iter().all(|(k, p)| y.get(k).is_some_and(|q| same(p, q)))
        }
        _ => a == b,
    }
}

/// Kaydedilmiş vektörler + (varsa) elle yazılmış girdiler (`fixtures/hand`, parity/hand_cases.py).
pub fn cases(function: &str) -> Vec<Case> {
    let name = format!("{function}.jsonl.gz");
    let mut all = cases_in(&vectors_dir().join(&name));
    let hand = vectors_dir().with_file_name("hand").join(name);
    if hand.exists() {
        all.extend(cases_in(&hand));
    }
    all
}

fn cases_in(path: &std::path::Path) -> Vec<Case> {
    let file = std::fs::File::open(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    BufReader::new(GzDecoder::new(file))
        .lines()
        .map(|l| {
            let mut v: Value = serde_json::from_str(&l.expect("satır")).expect("vektör JSON");
            let map = |v: &mut Value, k: &str| v.get_mut(k).and_then(|x| x.as_object_mut()).map(std::mem::take).unwrap_or_default();
            Case {
                args: map(&mut v, "args"),
                callbacks: map(&mut v, "callbacks"),
                after: map(&mut v, "after"),
                now: v["now"].as_f64().unwrap_or(0.0),
                ret: v["ret"].take(),
            }
        })
        .collect()
}

/// İşlevin tüm vektörlerini oynat; ilk 3 farkı göster.
pub fn run(function: &str, call: impl Fn(&Case) -> Value) {
    // Testler TZ=UTC ile kaydedildi (yerel saat biçimleyen işlevler).
    static TZ: std::sync::Once = std::sync::Once::new();
    TZ.call_once(|| std::env::set_var("TZ", "UTC"));
    let all = cases(function);
    assert!(!all.is_empty(), "{function}: vektör yok");
    let mut bad = Vec::new();
    for (i, c) in all.iter().enumerate() {
        let got = call(c);
        if !same(&got, &c.ret) {
            bad.push(format!(
                "#{i}\n  args: {}\n  python: {}\n  rust:   {}",
                clip(&Value::Object(c.args.clone()).to_string()),
                clip(&c.ret.to_string()),
                clip(&got.to_string())
            ));
        }
    }
    assert!(bad.is_empty(), "{function}: {}/{} fark\n{}", bad.len(), all.len(), bad.iter().take(3).cloned().collect::<Vec<_>>().join("\n"));
}

fn clip(s: &str) -> String {
    s.chars().take(1500).collect()
}

/// `parity!(python_adı, test_adı, |c| ifade)`: vektörleri oynatan bir `#[test]` tanımlar; ifade serileştirilebilir döner.
#[allow(unused_macros)]
macro_rules! parity {
    ($py:literal, $name:ident, |$c:ident| $body:expr) => {
        #[test]
        fn $name() {
            $crate::harness::run($py, |$c: &$crate::harness::Case| serde_json::to_value($body).expect("serileştirme"));
        }
    };
}
#[allow(unused_imports)]
pub(crate) use parity;
