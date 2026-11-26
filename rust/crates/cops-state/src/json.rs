//! Python `json` modülüyle birebir JSON: anahtar SIRASI korunur, çıktı baytları `json.dumps(ensure_ascii=False)` ile aynıdır.
//!
//! Neden `serde_json::Value` değil: sıra korumak için gereken `preserve_order` özelliği workspace'teki TÜM crate'lerde açılır
//! (başka crate'ler sıralı anahtara dayanıyor). Ayrıştırıcı `json.load` gibi davranır (`NaN`/`Infinity` kabul, yinelenen
//! anahtarda son değer + ilk konum, dizede ham denetim karakteri hata); 64 bite sığmayan tam sayı metin olarak korunur.
//! Tek fark: eşlenmemiş vekil (`"\ud800"`) HATA (Rust dizesinde tutulamaz; fail closed).
use serde::ser::{Serialize, SerializeMap, SerializeSeq, Serializer};

pub type Map = indexmap::IndexMap<String, Json>;

/// Python'un özyineleme sınırına yakın derinlik; aşan belge hata.
const MAX_DEPTH: usize = 512;

#[derive(Debug, Clone, PartialEq, Default)]
pub enum Json {
    #[default]
    Null,
    Bool(bool),
    Int(i64),
    /// `i64`e sığmayan tam sayının ondalık metni.
    BigInt(String),
    Float(f64),
    Str(String),
    Array(Vec<Json>),
    Object(Map),
}

#[derive(Debug, Clone, PartialEq)]
pub struct ParseError {
    pub at: usize,
    pub msg: &'static str,
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "json: {} (bayt {})", self.msg, self.at)
    }
}
impl std::error::Error for ParseError {}

impl Json {
    pub fn parse(text: &str) -> Result<Json, ParseError> {
        Self::parse_inner(text, None).map(|(v, _)| v)
    }

    /// Python `json.loads` gibi eşlenmemiş vekil kaçışını (`"\ud800"`) KABUL eder: Rust dizesinde tutulamadığı için U+FFFD
    /// yazılır ve ikinci değer `true` döner. YALNIZ okuyucular için: bu değer geri yazılırsa veri değişir; yazıcılar
    /// `true` gördüğünde yazmamalı (Python da bu belgeyi yazamaz: UTF-8'e kodlanamaz).
    pub fn parse_lossy(text: &str) -> Result<(Json, bool), ParseError> {
        Self::parse_inner(text, Some(false))
    }

    fn parse_inner(text: &str, lossy: Option<bool>) -> Result<(Json, bool), ParseError> {
        let mut p = Parser {
            s: text,
            i: 0,
            lossy,
        };
        p.ws();
        let v = p.value(0)?;
        p.ws();
        if p.i != text.len() {
            return Err(p.err("fazla veri"));
        }
        Ok((v, p.lossy.unwrap_or(false)))
    }

    pub fn object() -> Json {
        Json::Object(Map::new())
    }
    pub fn as_object(&self) -> Option<&Map> {
        match self {
            Json::Object(m) => Some(m),
            _ => None,
        }
    }
    pub fn as_object_mut(&mut self) -> Option<&mut Map> {
        match self {
            Json::Object(m) => Some(m),
            _ => None,
        }
    }
    pub fn as_array(&self) -> Option<&[Json]> {
        match self {
            Json::Array(a) => Some(a),
            _ => None,
        }
    }
    pub fn as_array_mut(&mut self) -> Option<&mut Vec<Json>> {
        match self {
            Json::Array(a) => Some(a),
            _ => None,
        }
    }
    pub fn as_str(&self) -> Option<&str> {
        match self {
            Json::Str(s) => Some(s),
            _ => None,
        }
    }
    pub fn as_i64(&self) -> Option<i64> {
        match self {
            Json::Int(i) => Some(*i),
            _ => None,
        }
    }
    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Json::Int(i) => Some(*i as f64),
            Json::BigInt(s) => s.parse().ok(),
            Json::Float(f) => Some(*f),
            _ => None,
        }
    }
    pub fn as_bool(&self) -> Option<bool> {
        match self {
            Json::Bool(b) => Some(*b),
            _ => None,
        }
    }
    /// Nesne alanı; nesne değilse ya da alan yoksa `None`.
    pub fn get(&self, key: &str) -> Option<&Json> {
        self.as_object().and_then(|m| m.get(key))
    }
    /// Python doğruluk değeri (`bool(x)`).
    pub fn truthy(&self) -> bool {
        match self {
            Json::Null => false,
            Json::Bool(b) => *b,
            Json::Int(i) => *i != 0,
            Json::BigInt(_) => true,
            Json::Float(f) => *f != 0.0,
            Json::Str(s) => !s.is_empty(),
            Json::Array(a) => !a.is_empty(),
            Json::Object(m) => !m.is_empty(),
        }
    }

    /// Python `==`: nesnede sıra önemsiz, `1 == 1.0 == True`.
    pub fn py_eq(&self, other: &Json) -> bool {
        fn num(v: &Json) -> Option<f64> {
            match v {
                Json::Bool(b) => Some(f64::from(u8::from(*b))),
                _ => v.as_f64(),
            }
        }
        match (self, other) {
            (Json::Int(a), Json::Int(b)) => a == b,
            (Json::BigInt(a), Json::BigInt(b)) => a == b,
            (Json::Array(a), Json::Array(b)) => {
                a.len() == b.len() && a.iter().zip(b).all(|(x, y)| x.py_eq(y))
            }
            (Json::Object(a), Json::Object(b)) => {
                a.len() == b.len() && a.iter().all(|(k, v)| b.get(k).is_some_and(|w| v.py_eq(w)))
            }
            _ => match (num(self), num(other)) {
                (Some(a), Some(b)) => a == b || (a.is_nan() && b.is_nan()),
                _ => self == other,
            },
        }
    }

    /// `json.dumps(obj, ensure_ascii=False)` (DB `docs.body` biçimi).
    pub fn to_compact(&self) -> String {
        let mut s = String::new();
        write_val(&mut s, self, false, 0);
        s
    }
    /// `json.dump(obj, f, ensure_ascii=False, indent=2)` (durum dosyası biçimi; sonda satır sonu yok).
    pub fn to_indented(&self) -> String {
        let mut s = String::new();
        write_val(&mut s, self, true, 0);
        s
    }
}

impl From<&str> for Json {
    fn from(s: &str) -> Json {
        Json::Str(s.to_string())
    }
}
impl From<String> for Json {
    fn from(s: String) -> Json {
        Json::Str(s)
    }
}
impl From<bool> for Json {
    fn from(b: bool) -> Json {
        Json::Bool(b)
    }
}
impl From<i64> for Json {
    fn from(i: i64) -> Json {
        Json::Int(i)
    }
}
impl From<f64> for Json {
    fn from(f: f64) -> Json {
        Json::Float(f)
    }
}

/// HTTP yanıtlarında doğrudan kullanım (`serde_json::to_vec(&json)` sırayı korur). `NaN`/sonsuz `null` olur.
impl Serialize for Json {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        match self {
            Json::Null => s.serialize_unit(),
            Json::Bool(b) => s.serialize_bool(*b),
            Json::Int(i) => s.serialize_i64(*i),
            Json::BigInt(t) => match t.parse::<u64>() {
                Ok(u) => s.serialize_u64(u),
                Err(_) => s.serialize_f64(t.parse().unwrap_or(f64::NAN)),
            },
            Json::Float(f) => s.serialize_f64(*f),
            Json::Str(t) => s.serialize_str(t),
            Json::Array(a) => {
                let mut q = s.serialize_seq(Some(a.len()))?;
                for x in a {
                    q.serialize_element(x)?;
                }
                q.end()
            }
            Json::Object(m) => {
                let mut q = s.serialize_map(Some(m.len()))?;
                for (k, v) in m {
                    q.serialize_entry(k, v)?;
                }
                q.end()
            }
        }
    }
}

/// Python `float.__repr__` (JSON yazımındaki biçim).
pub fn py_float_repr(x: f64) -> String {
    if x.is_nan() {
        return "NaN".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "Infinity" } else { "-Infinity" }.into();
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0" } else { "0.0" }.into();
    }
    let neg = if x < 0.0 { "-" } else { "" };
    // `{:e}` en kısa gidiş-dönüş basamakları: "1.2345e3", "1e16", "5e-324".
    let mut sci = format!("{:e}", x.abs());
    // Eşit uzaklıkta iki en kısa aday varsa Python çift basamağı seçer, `{:e}` üsttekini; sabit duyarlıklı biçim
    // yarımı çifte yuvarlar, aynı değere dönüyorsa o kullanılır (örnek: 223712169836953.625 -> ...953.62).
    let nd = sci
        .split('e')
        .next()
        .map_or(1, |m| m.chars().filter(|c| *c != '.').count());
    let even = format!("{:.*e}", nd.saturating_sub(1), x.abs());
    if even.parse() == Ok(x.abs()) {
        sci = even;
    }
    let (mant, exp) = sci.split_once('e').unwrap_or((sci.as_str(), "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    let digits: String = mant.chars().filter(|c| *c != '.').collect();
    let nd = digits.len() as i32;
    let decpt = exp + 1;
    if decpt <= -4 || decpt > 16 {
        let (first, rest) = digits.split_at(1);
        let m = if rest.is_empty() {
            first.to_string()
        } else {
            format!("{first}.{rest}")
        };
        let sign = if exp < 0 { '-' } else { '+' };
        format!("{neg}{m}e{sign}{:02}", exp.unsigned_abs())
    } else if decpt <= 0 {
        let zeros = "0".repeat(decpt.unsigned_abs() as usize);
        format!("{neg}0.{zeros}{digits}")
    } else if decpt >= nd {
        let zeros = "0".repeat((decpt - nd) as usize);
        format!("{neg}{digits}{zeros}.0")
    } else {
        let (a, b) = digits.split_at(decpt as usize);
        format!("{neg}{a}.{b}")
    }
}

fn write_str(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn newline(out: &mut String, depth: usize) {
    out.push('\n');
    for _ in 0..depth {
        out.push_str("  ");
    }
}

fn write_val(out: &mut String, v: &Json, indent: bool, depth: usize) {
    let sep = |out: &mut String, i: usize| {
        if i > 0 {
            out.push_str(if indent { "," } else { ", " });
        }
        if indent {
            newline(out, depth + 1);
        }
    };
    match v {
        Json::Null => out.push_str("null"),
        Json::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Json::Int(i) => {
            out.push_str(&i.to_string());
        }
        Json::BigInt(t) => out.push_str(t),
        Json::Float(f) => out.push_str(&py_float_repr(*f)),
        Json::Str(s) => write_str(out, s),
        Json::Array(a) if a.is_empty() => out.push_str("[]"),
        Json::Object(m) if m.is_empty() => out.push_str("{}"),
        Json::Array(a) => {
            out.push('[');
            for (i, x) in a.iter().enumerate() {
                sep(out, i);
                write_val(out, x, indent, depth + 1);
            }
            if indent {
                newline(out, depth);
            }
            out.push(']');
        }
        Json::Object(m) => {
            out.push('{');
            for (i, (k, x)) in m.iter().enumerate() {
                sep(out, i);
                write_str(out, k);
                out.push_str(": ");
                write_val(out, x, indent, depth + 1);
            }
            if indent {
                newline(out, depth);
            }
            out.push('}');
        }
    }
}

struct Parser<'a> {
    s: &'a str,
    i: usize,
    /// `Some`: eşlenmemiş vekil U+FFFD olur ve bayrak kalkar; `None`: hata.
    lossy: Option<bool>,
}

impl Parser<'_> {
    fn err(&self, msg: &'static str) -> ParseError {
        ParseError { at: self.i, msg }
    }
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

    fn value(&mut self, depth: usize) -> Result<Json, ParseError> {
        if depth > MAX_DEPTH {
            return Err(self.err("çok derin"));
        }
        match self.peek() {
            Some(b'"') => Ok(Json::Str(self.string()?)),
            Some(b'{') => {
                self.i += 1;
                let mut m = Map::new();
                self.ws();
                if self.eat("}") {
                    return Ok(Json::Object(m));
                }
                loop {
                    self.ws();
                    if self.peek() != Some(b'"') {
                        return Err(self.err("anahtar bekleniyor"));
                    }
                    let k = self.string()?;
                    self.ws();
                    if !self.eat(":") {
                        return Err(self.err("':' bekleniyor"));
                    }
                    self.ws();
                    let v = self.value(depth + 1)?;
                    m.insert(k, v);
                    self.ws();
                    if self.eat("}") {
                        return Ok(Json::Object(m));
                    }
                    if !self.eat(",") {
                        return Err(self.err("',' bekleniyor"));
                    }
                }
            }
            Some(b'[') => {
                self.i += 1;
                let mut a = Vec::new();
                self.ws();
                if self.eat("]") {
                    return Ok(Json::Array(a));
                }
                loop {
                    self.ws();
                    a.push(self.value(depth + 1)?);
                    self.ws();
                    if self.eat("]") {
                        return Ok(Json::Array(a));
                    }
                    if !self.eat(",") {
                        return Err(self.err("',' bekleniyor"));
                    }
                }
            }
            _ => {
                if self.eat("null") {
                    Ok(Json::Null)
                } else if self.eat("true") {
                    Ok(Json::Bool(true))
                } else if self.eat("false") {
                    Ok(Json::Bool(false))
                } else if self.eat("NaN") {
                    Ok(Json::Float(f64::NAN))
                } else if self.eat("Infinity") {
                    Ok(Json::Float(f64::INFINITY))
                } else if self.eat("-Infinity") {
                    Ok(Json::Float(f64::NEG_INFINITY))
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

    fn number(&mut self) -> Result<Json, ParseError> {
        let start = self.i;
        self.eat("-");
        match self.peek() {
            Some(b'0') => self.i += 1,
            Some(b'1'..=b'9') => {
                self.digits();
            }
            _ => return Err(self.err("değer bekleniyor")),
        }
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
            t.parse().map(Json::Float).map_err(|_| self.err("sayı"))
        } else {
            Ok(t.parse()
                .map(Json::Int)
                .unwrap_or_else(|_| Json::BigInt(t.to_string())))
        }
    }

    fn hex4(&mut self) -> Result<u32, ParseError> {
        let h = self
            .s
            .get(self.i..self.i + 4)
            .filter(|h| h.bytes().all(|b| b.is_ascii_hexdigit()))
            .ok_or_else(|| self.err("\\u kaçışı"))?;
        let v = u32::from_str_radix(h, 16).map_err(|_| self.err("\\u kaçışı"))?;
        self.i += 4;
        Ok(v)
    }

    fn string(&mut self) -> Result<String, ParseError> {
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
            match self.peek() {
                Some(b'"') => {
                    self.i += 1;
                    return Ok(out);
                }
                Some(b'\\') => {
                    self.i += 1;
                    let c = self.peek().ok_or_else(|| self.err("yarım dize"))?;
                    self.i += 1;
                    out.push(match c {
                        b'"' => '"',
                        b'\\' => '\\',
                        b'/' => '/',
                        b'b' => '\u{08}',
                        b'f' => '\u{0c}',
                        b'n' => '\n',
                        b'r' => '\r',
                        b't' => '\t',
                        b'u' => {
                            let mut u = self.hex4()?;
                            if (0xD800..0xDC00).contains(&u) && self.eat("\\u") {
                                let lo = self.hex4()?;
                                if (0xDC00..0xE000).contains(&lo) {
                                    u = 0x10000 + ((u - 0xD800) << 10) + (lo - 0xDC00);
                                } else {
                                    // Python: ikinci kaçış tüketilmez, ayrı karakter olarak okunur
                                    self.i -= 6;
                                }
                            }
                            match (char::from_u32(u), &mut self.lossy) {
                                (Some(c), _) => c,
                                (None, Some(flag)) => {
                                    *flag = true;
                                    '\u{fffd}'
                                }
                                (None, None) => return Err(self.err("eşlenmemiş vekil")),
                            }
                        }
                        _ => return Err(self.err("geçersiz kaçış")),
                    });
                }
                Some(_) => return Err(self.err("dizede denetim karakteri")),
                None => return Err(self.err("yarım dize")),
            }
        }
    }
}
