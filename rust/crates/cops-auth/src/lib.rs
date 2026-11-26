//! Tek kullanıcı kimlik: `web.token` dosyası tek doğruluk kaynağı. Python `_authorized` ile AYNI kural (docs/rust-strangler-plan.md bölüm 4):
//! boş token = kapalı (fail-closed), aday `?token=` ya da `Authorization: Bearer`, sabit zamanlı karşılaştırma, ASCII olmayan aday = red.
//! Çok kullanıcı kipinin yalnız SÖZLEŞMESİ `authz`'da (tipler, eylem tablosu, trait'ler); doğrulama enterprise'ta, henüz bağlı değil.

pub mod authz;
mod sha256;
pub use sha256::{hex, hmac_sha256, sha256};

/// Panel oturum çerezinin adı (Python `extensions.COOKIE_NAME`).
pub const COOKIE_NAME: &str = "cops_ext";

/// Python `str.strip()` (argümansız): Rust `trim()` kümesine ek olarak U+001C..U+001F'yi de kırpar. Çekirdekte TEK yardımcı
/// (`cops-proxy` de bunu kullanır, H14).
pub fn py_strip(s: &str) -> &str {
    s.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}

/// Panel token'ı: sabit değer ([`Token::new`]) ya da dosya ([`Token::from_file`]). Dosyalı olan HER sorguda yeniden okunur
/// (Python gibi): silinen/döndürülen token anında geçersiz.
#[derive(Clone)]
pub struct Token {
    src: Source,
}

#[derive(Clone)]
enum Source {
    Fixed(Value),
    File(std::path::PathBuf),
}

/// `raw`: token baytları; `cookie`: `HMAC-SHA256(key=token, "claudeops-ext-session")` hex (token boşsa boş).
#[derive(Clone)]
struct Value {
    raw: Vec<u8>,
    cookie: String,
}

impl Value {
    fn new(raw: &str) -> Value {
        let raw = py_strip(raw).as_bytes().to_vec();
        let cookie = if raw.is_empty() {
            String::new()
        } else {
            hex(&hmac_sha256(&raw, b"claudeops-ext-session"))
        };
        Value { raw, cookie }
    }

    /// Okunamayan ya da grup/diğer izni olan dosya = boş (kapalı). İzin ve içerik aynı açık dosyadan okunur.
    fn read(path: &std::path::Path) -> Value {
        use std::io::Read;
        use std::os::unix::fs::PermissionsExt;
        let mut raw = String::new();
        let ok = std::fs::File::open(path).is_ok_and(|mut f| {
            f.metadata()
                .is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o077 == 0)
                && f.read_to_string(&mut raw).is_ok()
        });
        Value::new(if ok { &raw } else { "" })
    }

    fn matches(&self, cand: &str) -> bool {
        !self.raw.is_empty() && cand.is_ascii() && ct_eq(self.raw.as_slice(), cand.as_bytes())
    }
}

/// Sabit zamanlı bayt eşitliği (uzunluk farkı da tüm uzunluk boyunca gezer; erken çıkış yok).
pub fn ct_eq(a: &[u8], b: &[u8]) -> bool {
    let mut diff = (a.len() ^ b.len()) as u32;
    let n = a.len().max(b.len());
    for i in 0..n {
        diff |= (a.get(i).copied().unwrap_or(0) ^ b.get(i).copied().unwrap_or(0)) as u32;
    }
    diff == 0
}

/// Python `urllib.parse.unquote_plus` (`errors="replace"`): `+` boşluk, `%XX` bayt; bozuk kaçış (`%zz`, sondaki `%2`) AYNEN
/// kalır, geçersiz UTF-8 U+FFFD olur.
pub fn unquote_plus(s: &str) -> String {
    let b = s.as_bytes();
    let hex = |i: usize| b.get(i).and_then(|c| (*c as char).to_digit(16));
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        match (b[i], hex(i + 1), hex(i + 2)) {
            (b'%', Some(h), Some(l)) => {
                out.push((h * 16 + l) as u8);
                i += 3;
            }
            (b'+', ..) => {
                out.push(b' ');
                i += 1;
            }
            (c, ..) => {
                out.push(c);
                i += 1;
            }
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// Python `parse_qs` (`keep_blank_values=False`, ayraç yalnız `&`): `=`siz ve boş değerli parçalar atlanır, ad ve değer
/// [`unquote_plus`] ile çözülür; sıra korunur.
pub fn parse_qs(query: &str) -> Vec<(String, String)> {
    query
        .split('&')
        .filter_map(|kv| kv.split_once('='))
        .filter(|(_, v)| !v.is_empty())
        .map(|(k, v)| (unquote_plus(k), unquote_plus(v)))
        .collect()
}

/// Sorgu dizesinden adı (yüzde-çözülmüş hâliyle) `name` olan TÜM parametreleri siler, kalanları (boş parçalar dahil) aynen ve sırayla korur (Python `parse_qs` anahtarı
/// da çözdüğü için `tok%65n=` gibi kodlu ad da silinir: token'ın vekil arkasına sızmasını önler).
pub fn strip_query_param(query: &str, name: &str) -> String {
    query
        .split('&')
        .filter(|kv| {
            let k = kv.split_once('=').map_or(*kv, |(k, _)| k);
            unquote_plus(k) != name
        })
        .collect::<Vec<_>>()
        .join("&")
}

/// `name`'in değeri, Python `(parse_qs(sorgu).get(name) or [""])[0]` ile aynı (R1-11): ad da çözülür (`tok%65n` = `token`), boş
/// değerler atlanır, İLK dolu değer. Yoksa `None`. Önceden ham adın ilk eşleşmesi (boş dahil) alınıyordu; Python başka bir
/// aday görüyordu.
pub fn query_param(query: &str, name: &str) -> Option<String> {
    parse_qs(query)
        .into_iter()
        .find(|(k, _)| k == name)
        .map(|(_, v)| v)
}

impl Token {
    /// Sabit değer (satır sonu kırpılır). Boş = her istek reddedilir.
    pub fn new(raw: &str) -> Token {
        Token {
            src: Source::Fixed(Value::new(raw)),
        }
    }

    /// `web.token` dosyası: her sorguda yeniden okunur; yok/okunamaz/0600 değil = boş.
    pub fn from_file(path: &std::path::Path) -> Token {
        Token {
            src: Source::File(path.to_path_buf()),
        }
    }

    fn value(&self) -> std::borrow::Cow<'_, Value> {
        match &self.src {
            Source::Fixed(v) => std::borrow::Cow::Borrowed(v),
            Source::File(p) => std::borrow::Cow::Owned(Value::read(p)),
        }
    }

    /// Şu anki değeri sabitleyen kopya: tek isteğin birden çok sorgusu (kimlik + çerez basma) AYNI token'ı görsün.
    pub fn snapshot(&self) -> Token {
        Token {
            src: Source::Fixed(self.value().into_owned()),
        }
    }

    pub fn is_empty(&self) -> bool {
        self.value().raw.is_empty()
    }

    /// `cops_ext` çerez değeri (Python `extensions.cookie_value`); token boşsa None.
    pub fn cookie_value(&self) -> Option<String> {
        Some(self.value().into_owned().cookie).filter(|c| !c.is_empty())
    }

    /// Python `extensions.cookie_ok` ile aynı kural: `;` ile bölünen parçalardan adı `cops_ext` olanın değeri sabit zamanlı eşit mi.
    pub fn cookie_ok(&self, cookie_header: &str) -> bool {
        if cookie_header.is_empty() {
            return false;
        }
        let v_now = self.value();
        if v_now.cookie.is_empty() {
            return false;
        }
        let mut ok = false;
        for part in cookie_header.split(';') {
            let part = py_strip(part);
            let (k, v) = part.split_once('=').unwrap_or((part, ""));
            if k == COOKIE_NAME {
                ok |= ct_eq(v.as_bytes(), v_now.cookie.as_bytes());
            }
        }
        ok
    }

    /// `query`: ham sorgu dizesi (`?` olmadan); `authorization`: `Authorization` başlığı değeri.
    pub fn authorized(&self, query: &str, authorization: Option<&str>) -> bool {
        let v = self.value();
        if v.raw.is_empty() {
            return false;
        }
        let mut ok = false;
        if let Some(t) = query_param(query, "token") {
            ok |= v.matches(&t);
        }
        if let Some(a) = authorization {
            if let Some(b) = a.strip_prefix("Bearer ") {
                ok |= v.matches(py_strip(b));
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
        assert_eq!(t.cookie_value().as_deref(), Some(v));
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
    fn whitespace_stripping_matches_python_str_strip() {
        let t = Token::new("\u{1c}sekret\u{1f}\n");
        assert!(t.authorized("token=sekret", None), "token dosyası");
        assert!(t.authorized("", Some("Bearer \u{1d}sekret\u{1e}")));
        let v = t.cookie_value().unwrap();
        assert!(t.cookie_ok(&format!("a=1;\u{1c}cops_ext={v}\u{1f}")));
        let req = authz::RequestView {
            headers: vec![("cookie".into(), "a=1;\u{1c}b=2\u{1f}".into())],
            method: "GET".into(),
            path: "/".into(),
            raw_query: String::new(),
            client_ip: std::net::Ipv4Addr::LOCALHOST.into(),
            peer_loopback: true,
        };
        assert_eq!(req.cookie("b"), Some("2"));
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

    #[test]
    fn file_token_follows_rotation_deletion_and_mode() {
        use std::os::unix::fs::PermissionsExt;
        let path = std::env::temp_dir().join(format!("cops-auth-tok-{}", std::process::id()));
        let put = |v: &str, mode: u32| {
            std::fs::write(&path, v).unwrap();
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(mode)).unwrap();
        };
        put("eski\n", 0o600);
        let t = Token::from_file(&path);
        assert!(t.authorized("token=eski", None));
        let old_cookie = t.cookie_value().unwrap();
        let snap = t.snapshot();
        put("yeni\n", 0o600);
        assert!(snap.authorized("token=eski", None), "anlık görüntü sabit");
        assert!(
            !t.authorized("token=eski", None),
            "döndürülen token geçersiz"
        );
        assert!(t.authorized("", Some("Bearer yeni")));
        assert!(!t.cookie_ok(&format!("cops_ext={old_cookie}")));
        assert!(t.cookie_ok(&format!("cops_ext={}", t.cookie_value().unwrap())));
        put("yeni\n", 0o644);
        assert!(!t.authorized("token=yeni", None), "0600 değilse kapalı");
        std::fs::remove_file(&path).unwrap();
        assert!(!t.authorized("token=yeni", None), "silinen token geçersiz");
        assert!(t.is_empty());
    }
}
