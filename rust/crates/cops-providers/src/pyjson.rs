//! Python `json.loads` + `str()`/`repr()`/`json.dumps(ensure_ascii=False[, indent=2])` anlamı.
//!
//! `serde_json` yerine ayrı ayrıştırıcı: Python `NaN`/`Infinity` kabul eder, 64 bite sığmayan tam sayı tam sayı kalır
//! ve eşlenmemiş vekil kaçışı (`"\ud83d"`, kesilmiş emoji: JS `JSON.stringify` böyle yazar) satırı düşürmez; `serde_json`
//! üçünde de belgeyi reddeder. Eşlenmemiş vekil U+FFFD olur; [`MAX_DEPTH`]ten derin belge ve 4300 basamaktan uzun tam
//! sayı hatadır. Sağlayıcı okuyucularının Python tarafı (`py/claudeops/jsonbound.py`, 28 Kas) ilk ikisini aynı kuralla
//! uygular; 4300 basamak Python'un kendi `ValueError`ıdır.
//!
//! `rs/state` (`cops-state::json::Json`) aynı ailenin okuyup YAZAN sürümü; o dal birleşince bu dosya onunla
//! tekleştirilmeli.

use crate::pyfmt::float_repr;
use cops_state::pycompat::repr_str;
use std::collections::HashMap;

/// İç içe dizi/nesne sınırı.
pub const MAX_DEPTH: usize = 512;
/// Python 3.10.7+ `int` dizge sınırı.
const MAX_INT_DIGITS: usize = 4300;

#[derive(Debug, Clone, PartialEq)]
pub enum Py {
    Null,
    Bool(bool),
    Int(i64),
    /// `i64`e sığmayan tam sayının ondalık metni.
    BigInt(String),
    Float(f64),
    Str(String),
    Array(Vec<Py>),
    /// Ekleme sırasıyla; yinelenen anahtarda SON değer İLK konumda.
    Object(Vec<(String, Py)>),
}

impl Py {
    pub fn parse(text: &str) -> Option<Py> {
        let mut p = Parser { s: text, i: 0 };
        p.ws();
        let v = p.value(0)?;
        p.ws();
        (p.i == text.len()).then_some(v)
    }

    pub fn is_object(&self) -> bool {
        matches!(self, Py::Object(_))
    }

    /// `dict.get`; nesne değilse ya da alan yoksa None.
    pub fn get(&self, key: &str) -> Option<&Py> {
        match self {
            Py::Object(o) => o.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Py::Str(s) => Some(s),
            _ => None,
        }
    }

    /// `serde_json` değeri. Sonlu olmayan float `null` olur; `i64`e sığmayan tam sayı yaklaşık float olur.
    pub fn to_value(&self) -> serde_json::Value {
        use serde_json::Value;
        match self {
            Py::Null => Value::Null,
            Py::Bool(b) => Value::Bool(*b),
            Py::Int(i) => Value::from(*i),
            Py::BigInt(s) => s.parse::<f64>().map(Value::from).unwrap_or(Value::Null),
            Py::Float(f) => Value::from(*f),
            Py::Str(s) => Value::String(s.clone()),
            Py::Array(a) => Value::Array(a.iter().map(Py::to_value).collect()),
            Py::Object(o) => {
                Value::Object(o.iter().map(|(k, v)| (k.clone(), v.to_value())).collect())
            }
        }
    }

    /// `bool(v)`.
    pub fn truthy(&self) -> bool {
        match self {
            Py::Null => false,
            Py::Bool(b) => *b,
            Py::Int(i) => *i != 0,
            Py::BigInt(_) => true,
            Py::Float(f) => *f != 0.0,
            Py::Str(s) => !s.is_empty(),
            Py::Array(a) => !a.is_empty(),
            Py::Object(o) => !o.is_empty(),
        }
    }

    /// `isinstance(v, int) and not isinstance(v, bool) and v >= 0`; `u64`e sığmayan değer `u64::MAX`.
    pub fn non_negative_int(&self) -> Option<u64> {
        match self {
            Py::Int(i) => u64::try_from(*i).ok(),
            Py::BigInt(s) if !s.starts_with('-') => Some(s.parse().unwrap_or(u64::MAX)),
            _ => None,
        }
    }

    /// `str(v)`.
    pub fn py_str(&self) -> String {
        match self {
            Py::Str(s) => s.clone(),
            other => other.py_repr(),
        }
    }

    /// `repr(v)`.
    pub fn py_repr(&self) -> String {
        let mut out = String::new();
        self.repr_into(&mut out);
        out
    }

    fn repr_into(&self, out: &mut String) {
        match self {
            Py::Null => out.push_str("None"),
            Py::Bool(b) => out.push_str(if *b { "True" } else { "False" }),
            Py::Int(i) => out.push_str(&i.to_string()),
            Py::BigInt(s) => out.push_str(s),
            Py::Float(f) => out.push_str(&float_repr(*f)),
            Py::Str(s) => out.push_str(&repr_str(s)),
            Py::Array(a) => {
                out.push('[');
                for (i, v) in a.iter().enumerate() {
                    if i > 0 {
                        out.push_str(", ");
                    }
                    v.repr_into(out);
                }
                out.push(']');
            }
            Py::Object(o) => {
                out.push('{');
                for (i, (k, v)) in o.iter().enumerate() {
                    if i > 0 {
                        out.push_str(", ");
                    }
                    out.push_str(&repr_str(k));
                    out.push_str(": ");
                    v.repr_into(out);
                }
                out.push('}');
            }
        }
    }

    /// `json.dumps(v, ensure_ascii=False)`.
    pub fn dumps(&self) -> String {
        let mut out = String::new();
        self.dumps_into(&mut out);
        out
    }

    /// `json.dumps(v, ensure_ascii=False, indent=2)` (belge yazımı; sonda satır sonu yok).
    pub fn dumps_pretty(&self) -> String {
        let mut out = String::new();
        self.pretty_into(&mut out, 0);
        out
    }

    fn pretty_into(&self, out: &mut String, level: usize) {
        let pad = |out: &mut String, n: usize| {
            out.push('\n');
            out.extend(std::iter::repeat_n(' ', n * 2));
        };
        match self {
            Py::Array(a) if !a.is_empty() => {
                out.push('[');
                for (i, v) in a.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    pad(out, level + 1);
                    v.pretty_into(out, level + 1);
                }
                pad(out, level);
                out.push(']');
            }
            Py::Object(o) if !o.is_empty() => {
                out.push('{');
                for (i, (k, v)) in o.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    pad(out, level + 1);
                    dumps_str(k, out);
                    out.push_str(": ");
                    v.pretty_into(out, level + 1);
                }
                pad(out, level);
                out.push('}');
            }
            other => other.dumps_into(out),
        }
    }

    fn dumps_into(&self, out: &mut String) {
        match self {
            Py::Null => out.push_str("null"),
            Py::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            Py::Int(i) => out.push_str(&i.to_string()),
            Py::BigInt(s) => out.push_str(s),
            Py::Float(f) if f.is_nan() => out.push_str("NaN"),
            Py::Float(f) if f.is_infinite() => {
                out.push_str(if *f > 0.0 { "Infinity" } else { "-Infinity" })
            }
            Py::Float(f) => out.push_str(&float_repr(*f)),
            Py::Str(s) => dumps_str(s, out),
            Py::Array(a) => {
                out.push('[');
                for (i, v) in a.iter().enumerate() {
                    if i > 0 {
                        out.push_str(", ");
                    }
                    v.dumps_into(out);
                }
                out.push(']');
            }
            Py::Object(o) => {
                out.push('{');
                for (i, (k, v)) in o.iter().enumerate() {
                    if i > 0 {
                        out.push_str(", ");
                    }
                    dumps_str(k, out);
                    out.push_str(": ");
                    v.dumps_into(out);
                }
                out.push('}');
            }
        }
    }
}

fn dumps_str(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

struct Parser<'a> {
    s: &'a str,
    i: usize,
}

impl Parser<'_> {
    fn peek(&self) -> Option<u8> {
        self.s.as_bytes().get(self.i).copied()
    }

    fn ws(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\n' | b'\r')) {
            self.i += 1;
        }
    }

    fn eat(&mut self, lit: &str) -> bool {
        if self.s.as_bytes()[self.i..].starts_with(lit.as_bytes()) {
            self.i += lit.len();
            true
        } else {
            false
        }
    }

    fn value(&mut self, depth: usize) -> Option<Py> {
        match self.peek()? {
            b'"' => self.string().map(Py::Str),
            b'{' => {
                if depth >= MAX_DEPTH {
                    return None;
                }
                self.i += 1;
                let mut entries: Vec<(String, Py)> = Vec::new();
                let mut index: HashMap<String, usize> = HashMap::new();
                self.ws();
                if self.eat("}") {
                    return Some(Py::Object(entries));
                }
                loop {
                    self.ws();
                    if self.peek() != Some(b'"') {
                        return None;
                    }
                    let k = self.string()?;
                    self.ws();
                    if !self.eat(":") {
                        return None;
                    }
                    self.ws();
                    let v = self.value(depth + 1)?;
                    match index.get(&k) {
                        Some(&at) => entries[at].1 = v,
                        None => {
                            index.insert(k.clone(), entries.len());
                            entries.push((k, v));
                        }
                    }
                    self.ws();
                    if self.eat("}") {
                        return Some(Py::Object(entries));
                    }
                    if !self.eat(",") {
                        return None;
                    }
                }
            }
            b'[' => {
                if depth >= MAX_DEPTH {
                    return None;
                }
                self.i += 1;
                let mut a = Vec::new();
                self.ws();
                if self.eat("]") {
                    return Some(Py::Array(a));
                }
                loop {
                    self.ws();
                    a.push(self.value(depth + 1)?);
                    self.ws();
                    if self.eat("]") {
                        return Some(Py::Array(a));
                    }
                    if !self.eat(",") {
                        return None;
                    }
                }
            }
            _ => {
                if self.eat("null") {
                    Some(Py::Null)
                } else if self.eat("true") {
                    Some(Py::Bool(true))
                } else if self.eat("false") {
                    Some(Py::Bool(false))
                } else if self.eat("NaN") {
                    Some(Py::Float(f64::NAN))
                } else if self.eat("Infinity") {
                    Some(Py::Float(f64::INFINITY))
                } else if self.eat("-Infinity") {
                    Some(Py::Float(f64::NEG_INFINITY))
                } else {
                    self.number()
                }
            }
        }
    }

    fn digits(&mut self) -> usize {
        let start = self.i;
        while self.peek().is_some_and(|c| c.is_ascii_digit()) {
            self.i += 1;
        }
        self.i - start
    }

    fn number(&mut self) -> Option<Py> {
        let start = self.i;
        self.eat("-");
        match self.peek()? {
            b'0' => self.i += 1,
            b'1'..=b'9' => {
                self.digits();
            }
            _ => return None,
        }
        let int_end = self.i;
        let mut float = false;
        let mark = self.i;
        if self.eat(".") {
            if self.digits() == 0 {
                self.i = mark;
            } else {
                float = true;
            }
        }
        let mark = self.i;
        if self.eat("e") || self.eat("E") {
            if !self.eat("+") {
                self.eat("-");
            }
            if self.digits() == 0 {
                self.i = mark;
            } else {
                float = true;
            }
        }
        let t = &self.s[start..self.i];
        if float {
            t.parse().ok().map(Py::Float)
        } else if int_end - start - usize::from(t.starts_with('-')) > MAX_INT_DIGITS {
            None
        } else {
            Some(
                t.parse()
                    .map(Py::Int)
                    .unwrap_or_else(|_| Py::BigInt(t.to_string())),
            )
        }
    }

    fn hex4(&mut self) -> Option<u32> {
        let h = self
            .s
            .get(self.i..self.i + 4)
            .filter(|h| h.bytes().all(|b| b.is_ascii_hexdigit()))?;
        let v = u32::from_str_radix(h, 16).ok()?;
        self.i += 4;
        Some(v)
    }

    fn string(&mut self) -> Option<String> {
        self.i += 1; // açılış tırnağı
        let mut out = String::new();
        loop {
            let start = self.i;
            while self
                .peek()
                .is_some_and(|c| c != b'"' && c != b'\\' && c >= 0x20)
            {
                self.i += 1;
            }
            out.push_str(&self.s[start..self.i]);
            match self.peek()? {
                b'"' => {
                    self.i += 1;
                    return Some(out);
                }
                b'\\' => {
                    self.i += 1;
                    let c = self.peek()?;
                    self.i += 1;
                    out.push(match c {
                        b'"' => '"',
                        b'\\' => '\\',
                        b'/' => '/',
                        b'b' => '\u{8}',
                        b'f' => '\u{c}',
                        b'n' => '\n',
                        b'r' => '\r',
                        b't' => '\t',
                        b'u' => {
                            let mut u = self.hex4()?;
                            if (0xD800..0xDC00).contains(&u) {
                                let mark = self.i;
                                if self.eat("\\u") {
                                    let lo = self.hex4()?;
                                    if (0xDC00..0xE000).contains(&lo) {
                                        u = 0x10000 + ((u - 0xD800) << 10) + (lo - 0xDC00);
                                    } else {
                                        self.i = mark; // ikinci kaçış ayrı karakter olarak okunur
                                    }
                                }
                            }
                            char::from_u32(u).unwrap_or('\u{fffd}')
                        }
                        _ => return None,
                    });
                }
                _ => return None, // dizede ham denetim karakteri
            }
        }
    }
}
