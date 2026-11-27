//! Python `json.dumps(obj)` (varsayılan: `ensure_ascii=True`, ayırıcılar `", "`/`": "`, `allow_nan=True`) bayt bayt.
//! web.py `_json` yanıt gövdeleri bu biçimdedir. Anahtar sırası [`cops_state::Json`]da korunur (`preserve_order` YOK).
use cops_state::Json;

/// `json.dumps(v)`: [`Json::to_compact`] (`ensure_ascii=False`) + ASCII dışı ve DEL (U+007F) karakterlerin `\uXXXX` kaçışı
/// (BMP dışı vekil çifti). `to_compact` U+0020 altını zaten Python gibi kaçırır; sözdizimi karakterleri ASCII olduğu için
/// ASCII dışı her karakter bir dize ya da anahtar içindedir.
pub fn dumps(v: &Json) -> String {
    let compact = v.to_compact();
    let mut out = String::with_capacity(compact.len());
    let mut units = [0u16; 2];
    for c in compact.chars() {
        if (c as u32) < 0x7f {
            out.push(c);
        } else {
            for u in c.encode_utf16(&mut units) {
                out.push_str(&format!("\\u{u:04x}"));
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ensure_ascii_like_python() {
        // python3 -c 'import json;print(json.dumps({"a":"ç\x7f\x01😀\"\\/","b":[1.5,True,None,1e400]}))'
        let v = Json::parse(r#"{"a":"ç\u007f\u0001😀\"\\/","b":[1.5,true,null,1e400]}"#).unwrap();
        assert_eq!(
            dumps(&v),
            r#"{"a": "\u00e7\u007f\u0001\ud83d\ude00\"\\/", "b": [1.5, true, null, Infinity]}"#
        );
    }
}
