//! Tek kullanıcı kimlik: `web.token` dosyası tek doğruluk kaynağı. Python `_authorized` ile AYNI kural (docs/rust-strangler-plan.md bölüm 4):
//! boş token = kapalı (fail-closed), aday `?token=` ya da `Authorization: Bearer`, sabit zamanlı karşılaştırma, ASCII olmayan aday = red.
//! Çok kullanıcı (enterprise authenticator) kipi BURADA YOK: o kipte yerel uçlar Python'a iç kimlik sorusu soracak (D1 sonrası).

pub struct Token(Vec<u8>);

/// Sabit zamanlı bayt eşitliği (uzunluk farkı da tüm uzunluk boyunca gezer; erken çıkış yok).
fn ct_eq(a: &[u8], b: &[u8]) -> bool {
    let mut diff = (a.len() ^ b.len()) as u32;
    let n = a.len().max(b.len());
    for i in 0..n {
        diff |= (a.get(i).copied().unwrap_or(0) ^ b.get(i).copied().unwrap_or(0)) as u32;
    }
    diff == 0
}

fn pct_decode(s: &str) -> Option<String> {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'%' => {
                let h = std::str::from_utf8(b.get(i + 1..i + 3)?).ok()?;
                out.push(u8::from_str_radix(h, 16).ok()?);
                i += 3;
            }
            b'+' => {
                out.push(b' ');
                i += 1;
            }
            c => {
                out.push(c);
                i += 1;
            }
        }
    }
    String::from_utf8(out).ok()
}

/// Sorgu dizesinden (ilk) `name` değeri, yüzde-çözülmüş.
pub fn query_param(query: &str, name: &str) -> Option<String> {
    query.split('&').filter_map(|kv| kv.split_once('=')).find(|(k, _)| *k == name).and_then(|(_, v)| pct_decode(v))
}

impl Token {
    /// `web.token` içeriği (satır sonu kırpılır). Boş = her istek reddedilir.
    pub fn new(raw: &str) -> Token {
        Token(raw.trim().as_bytes().to_vec())
    }

    pub fn from_file(path: &std::path::Path) -> Token {
        Token::new(&std::fs::read_to_string(path).unwrap_or_default())
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    fn matches(&self, cand: &str) -> bool {
        !self.0.is_empty() && cand.is_ascii() && ct_eq(self.0.as_slice(), cand.as_bytes())
    }

    /// `query`: ham sorgu dizesi (`?` olmadan); `authorization`: `Authorization` başlığı değeri.
    pub fn authorized(&self, query: &str, authorization: Option<&str>) -> bool {
        if self.0.is_empty() {
            return false;
        }
        let mut ok = false;
        if let Some(t) = query_param(query, "token") {
            ok |= self.matches(&t);
        }
        if let Some(a) = authorization {
            if let Some(b) = a.strip_prefix("Bearer ") {
                ok |= self.matches(b.trim());
            }
        }
        ok
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn query_and_bearer_accept_empty_token_is_closed_non_ascii_rejected() {
        let t = Token::new("abc123\n");
        assert!(t.authorized("token=abc123", None));
        assert!(t.authorized("x=1&token=abc123", None));
        assert!(t.authorized("", Some("Bearer abc123")));
        assert!(!t.authorized("token=abc124", None));
        assert!(!t.authorized("", Some("Basic abc123")));
        assert!(!t.authorized("token=", Some("Bearer ")));
        assert!(!t.authorized("token=abc%C3%A9", None), "ASCII olmayan aday red");
        assert!(t.authorized("token=abc%31%32%33", None), "yüzde çözme");
        let closed = Token::new("");
        assert!(!closed.authorized("token=", None), "boş token = kapalı");
        assert!(!closed.authorized("", Some("Bearer ")));
    }
}
