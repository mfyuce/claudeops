//! Tek kullanıcı kimlik: `web.token` dosyası tek doğruluk kaynağı. Python `_authorized` ile AYNI kural (docs/rust-strangler-plan.md bölüm 4):
//! boş token = kapalı (fail-closed), aday `?token=` ya da `Authorization: Bearer`, sabit zamanlı karşılaştırma, ASCII olmayan aday = red.
//! Çok kullanıcı (enterprise authenticator) kipi BURADA YOK: o kipte yerel uçlar Python'a iç kimlik sorusu soracak (D1 sonrası).

mod sha256;
pub use sha256::{hex, hmac_sha256, sha256};

/// Panel oturum çerezinin adı (Python `extensions.COOKIE_NAME`).
pub const COOKIE_NAME: &str = "cops_ext";

/// `raw`: token baytları; `cookie`: `HMAC-SHA256(key=token, "claudeops-ext-session")` hex (token boşsa boş), kurulumda bir kez hesaplanır.
pub struct Token {
    raw: Vec<u8>,
    cookie: String,
}

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

/// Sorgu dizesinden adı (yüzde-çözülmüş hâliyle) `name` olan TÜM parametreleri siler, kalanları (boş parçalar dahil) aynen ve sırayla korur (Python `parse_qs` anahtarı
/// da çözdüğü için `tok%65n=` gibi kodlu ad da silinir: token'ın vekil arkasına sızmasını önler).
pub fn strip_query_param(query: &str, name: &str) -> String {
    query
        .split('&')
        .filter(|kv| {
            let k = kv.split_once('=').map_or(*kv, |(k, _)| k);
            pct_decode(k).as_deref() != Some(name)
        })
        .collect::<Vec<_>>()
        .join("&")
}

/// Sorgu dizesinden (ilk) `name` değeri, yüzde-çözülmüş.
pub fn query_param(query: &str, name: &str) -> Option<String> {
    query
        .split('&')
        .filter_map(|kv| kv.split_once('='))
        .find(|(k, _)| *k == name)
        .and_then(|(_, v)| pct_decode(v))
}

impl Token {
    /// `web.token` içeriği (satır sonu kırpılır). Boş = her istek reddedilir.
    pub fn new(raw: &str) -> Token {
        let raw = raw.trim().as_bytes().to_vec();
        let cookie = if raw.is_empty() {
            String::new()
        } else {
            hex(&hmac_sha256(&raw, b"claudeops-ext-session"))
        };
        Token { raw, cookie }
    }

    pub fn from_file(path: &std::path::Path) -> Token {
        Token::new(&std::fs::read_to_string(path).unwrap_or_default())
    }

    pub fn is_empty(&self) -> bool {
        self.raw.is_empty()
    }

    fn matches(&self, cand: &str) -> bool {
        !self.raw.is_empty() && cand.is_ascii() && ct_eq(self.raw.as_slice(), cand.as_bytes())
    }

    /// `cops_ext` çerez değeri (Python `extensions.cookie_value`); token boşsa None.
    pub fn cookie_value(&self) -> Option<&str> {
        if self.cookie.is_empty() {
            None
        } else {
            Some(&self.cookie)
        }
    }

    /// Python `extensions.cookie_ok` ile aynı kural: `;` ile bölünen parçalardan adı `cops_ext` olanın değeri sabit zamanlı eşit mi.
    pub fn cookie_ok(&self, cookie_header: &str) -> bool {
        if self.cookie.is_empty() || cookie_header.is_empty() {
            return false;
        }
        let mut ok = false;
        for part in cookie_header.split(';') {
            let (k, v) = part.trim().split_once('=').unwrap_or((part.trim(), ""));
            if k == COOKIE_NAME {
                ok |= ct_eq(v.as_bytes(), self.cookie.as_bytes());
            }
        }
        ok
    }

    /// `query`: ham sorgu dizesi (`?` olmadan); `authorization`: `Authorization` başlığı değeri.
    pub fn authorized(&self, query: &str, authorization: Option<&str>) -> bool {
        if self.raw.is_empty() {
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
        assert!(
            !t.authorized("token=abc%C3%A9", None),
            "ASCII olmayan aday red"
        );
        assert!(t.authorized("token=abc%31%32%33", None), "yüzde çözme");
        let closed = Token::new("");
        assert!(!closed.authorized("token=", None), "boş token = kapalı");
        assert!(!closed.authorized("", Some("Bearer ")));
    }

    #[test]
    fn cookie_matches_python_rule() {
        let t = Token::new("sekret\n");
        let v = "fd10ed735fac0d564927ae5896d62a45609190913ff450ca45453c6c12801d81";
        assert_eq!(t.cookie_value(), Some(v));
        assert!(t.cookie_ok(&format!("cops_ext={v}")));
        assert!(t.cookie_ok(&format!("a=1; cops_ext={v}; grafana_session=x")));
        assert!(!t.cookie_ok("cops_ext=fd10"));
        assert!(!t.cookie_ok(&format!("xcops_ext={v}")));
        assert!(!t.cookie_ok(""));
        let closed = Token::new("");
        assert_eq!(closed.cookie_value(), None);
        assert!(!closed.cookie_ok("cops_ext="));
    }

    #[test]
    fn strip_query_param_drops_all_and_encoded_names() {
        assert_eq!(strip_query_param("a=1&token=x&b=2", "token"), "a=1&b=2");
        assert_eq!(strip_query_param("token=x", "token"), "");
        assert_eq!(
            strip_query_param("token=x&tok%65n=y&token&tokens=3", "token"),
            "tokens=3"
        );
        assert_eq!(strip_query_param("", "token"), "");
        assert_eq!(
            strip_query_param("a=1&&b", "token"),
            "a=1&&b",
            "token yoksa sorgu birebir aynı kalır"
        );
    }
}
