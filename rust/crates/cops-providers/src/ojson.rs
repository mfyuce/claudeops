//! Ekleme sırasını koruyan JSON değeri (Python `json.load` -> `dict` anlamı): nesne anahtarları dosyadaki sırayla kalır,
//! yinelenen anahtarda SON değer İLK konumda durur. `serde_json::Map` (workspace'te `preserve_order` kapalı) anahtarları
//! sıralar; sıranın anlamlı olduğu ayarlar (byok ortam dosyası satırları, hizmet effort tabloları) bunu kullanır.

use serde::de::{Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Number, Value};
use std::fmt;

#[derive(Debug, Clone, PartialEq)]
pub enum OValue {
    Null,
    Bool(bool),
    Number(Number),
    String(String),
    Array(Vec<OValue>),
    Object(Vec<(String, OValue)>),
}

impl OValue {
    pub fn parse(text: &str) -> Option<OValue> {
        serde_json::from_str(text).ok()
    }

    /// Sırası bilinmeyen değerden (anahtarlar `Map` sırasıyla).
    pub fn from_value(v: &Value) -> OValue {
        match v {
            Value::Null => OValue::Null,
            Value::Bool(b) => OValue::Bool(*b),
            Value::Number(n) => OValue::Number(n.clone()),
            Value::String(s) => OValue::String(s.clone()),
            Value::Array(a) => OValue::Array(a.iter().map(OValue::from_value).collect()),
            Value::Object(o) => OValue::Object(o.iter().map(|(k, v)| (k.clone(), OValue::from_value(v))).collect()),
        }
    }

    pub fn to_value(&self) -> Value {
        match self {
            OValue::Null => Value::Null,
            OValue::Bool(b) => Value::Bool(*b),
            OValue::Number(n) => Value::Number(n.clone()),
            OValue::String(s) => Value::String(s.clone()),
            OValue::Array(a) => Value::Array(a.iter().map(OValue::to_value).collect()),
            OValue::Object(o) => Value::Object(o.iter().map(|(k, v)| (k.clone(), v.to_value())).collect::<Map<_, _>>()),
        }
    }

    pub fn get(&self, key: &str) -> Option<&OValue> {
        self.entries()?.iter().find(|(k, _)| k == key).map(|(_, v)| v)
    }

    /// Nesne girdileri (sırayla); nesne değilse None.
    pub fn entries(&self) -> Option<&[(String, OValue)]> {
        match self {
            OValue::Object(o) => Some(o),
            _ => None,
        }
    }

    pub fn as_array(&self) -> Option<&[OValue]> {
        match self {
            OValue::Array(a) => Some(a),
            _ => None,
        }
    }
}

struct OVisitor;

impl<'de> Visitor<'de> for OVisitor {
    type Value = OValue;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("JSON değeri")
    }
    fn visit_bool<E>(self, v: bool) -> Result<OValue, E> {
        Ok(OValue::Bool(v))
    }
    fn visit_i64<E>(self, v: i64) -> Result<OValue, E> {
        Ok(OValue::Number(v.into()))
    }
    fn visit_u64<E>(self, v: u64) -> Result<OValue, E> {
        Ok(OValue::Number(v.into()))
    }
    fn visit_f64<E>(self, v: f64) -> Result<OValue, E> {
        Ok(Number::from_f64(v).map_or(OValue::Null, OValue::Number))
    }
    fn visit_str<E>(self, v: &str) -> Result<OValue, E> {
        Ok(OValue::String(v.to_string()))
    }
    fn visit_string<E>(self, v: String) -> Result<OValue, E> {
        Ok(OValue::String(v))
    }
    fn visit_unit<E>(self) -> Result<OValue, E> {
        Ok(OValue::Null)
    }
    fn visit_none<E>(self) -> Result<OValue, E> {
        Ok(OValue::Null)
    }
    fn visit_some<D: Deserializer<'de>>(self, d: D) -> Result<OValue, D::Error> {
        Deserialize::deserialize(d)
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<OValue, A::Error> {
        let mut out = Vec::new();
        while let Some(v) = seq.next_element()? {
            out.push(v);
        }
        Ok(OValue::Array(out))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<OValue, A::Error> {
        let mut out: Vec<(String, OValue)> = Vec::new();
        while let Some((k, v)) = map.next_entry::<String, OValue>()? {
            match out.iter_mut().find(|(have, _)| *have == k) {
                Some(slot) => slot.1 = v,
                None => out.push((k, v)),
            }
        }
        Ok(OValue::Object(out))
    }
}

impl<'de> Deserialize<'de> for OValue {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<OValue, D::Error> {
        d.deserialize_any(OVisitor)
    }
}
