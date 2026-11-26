//! URL ayrıştırma ve sorgu kodlama. Doğrulama (SSRF süzgeci) ile bağlantı AYNI ayrıştırıcıyı kullanır: iki ayrı
//! ayrıştırıcı "denetlenen adres" ile "bağlanılan adres"i ayrıştırabilir.

use std::net::IpAddr;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Endpoint {
    pub https: bool,
    /// Köşeli parantezsiz, küçük harf. Normalize EDİLMEZ (`127.1` DNS adı sayılır ve bağlantıda denetlenir).
    pub host: String,
    pub port: u16,
    /// Başında `/` olan yol ya da boş (sondaki `/` korunur).
    pub path: String,
}

impl Endpoint {
    /// Yalnız `http(s)://host[:port][/yol]`. Kullanıcı bilgisi (`user@`), sorgu, parça, boşluk ve denetim karakteri reddedilir.
    pub fn parse(url: &str) -> Option<Endpoint> {
        if url.chars().any(|c| c.is_whitespace() || c.is_control())
            || url.contains(['?', '#', '\\'])
        {
            return None;
        }
        let (https, rest) = if let Some(r) = strip_prefix_ci(url, "https://") {
            (true, r)
        } else {
            (false, strip_prefix_ci(url, "http://")?)
        };
        let (authority, path) = match rest.find('/') {
            Some(i) => (&rest[..i], &rest[i..]),
            None => (rest, ""),
        };
        if authority.contains('@') {
            return None;
        }
        let (host, port) = if let Some(r) = authority.strip_prefix('[') {
            let (h, after) = r.split_once(']')?;
            h.split('%').next()?.parse::<std::net::Ipv6Addr>().ok()?;
            let port = match after {
                "" => None,
                a => Some(a.strip_prefix(':')?),
            };
            (h, port)
        } else {
            match authority.split_once(':') {
                Some((h, p)) => (h, Some(p)),
                None => (authority, None),
            }
        };
        if host.is_empty() || (!authority.starts_with('[') && host.contains(['[', ']', '%'])) {
            return None;
        }
        let port = match port {
            None | Some("") => {
                if https {
                    443
                } else {
                    80
                }
            }
            Some(p) if p.bytes().all(|b| b.is_ascii_digit()) => {
                p.parse::<u16>().ok().filter(|&p| p > 0)?
            }
            Some(_) => return None,
        };
        Some(Endpoint {
            https,
            host: host.to_ascii_lowercase(),
            port,
            path: path.to_string(),
        })
    }

    /// IP literali DEĞİL (DNS adı; kayıt anından sonra başka IP'ye çözülebilir).
    pub fn is_dns_name(&self) -> bool {
        host_is_dns_name(&self.host)
    }

    /// `Host` başlığı / `:authority`.
    pub fn authority(&self) -> String {
        let h = if self.host.contains(':') {
            format!("[{}]", self.host)
        } else {
            self.host.clone()
        };
        if self.port == if self.https { 443 } else { 80 } {
            h
        } else {
            format!("{h}:{}", self.port)
        }
    }

    /// Havuz anahtarı: şema + host + port.
    pub fn pool_key(&self) -> String {
        format!(
            "{}://{}:{}",
            if self.https { "https" } else { "http" },
            self.host,
            self.port
        )
    }
}

fn strip_prefix_ci<'a>(s: &'a str, p: &str) -> Option<&'a str> {
    let head = s.get(..p.len())?;
    head.eq_ignore_ascii_case(p).then(|| &s[p.len()..])
}

pub fn host_is_dns_name(host: &str) -> bool {
    !host.is_empty() && host.parse::<IpAddr>().is_err()
}

/// Python `urllib.parse.quote_plus`.
pub fn quote_plus(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' => {
                out.push(b as char)
            }
            b' ' => out.push('+'),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// Python `urlencode`: verilen sırayla.
pub fn urlencode<K: AsRef<str>, V: AsRef<str>>(q: &[(K, V)]) -> String {
    q.iter()
        .map(|(k, v)| format!("{}={}", quote_plus(k.as_ref()), quote_plus(v.as_ref())))
        .collect::<Vec<_>>()
        .join("&")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_common_forms() {
        let e = Endpoint::parse("HTTPS://Example.COM/prefix").unwrap();
        assert_eq!(
            (e.https, e.host.as_str(), e.port, e.path.as_str()),
            (true, "example.com", 443, "/prefix")
        );
        let e = Endpoint::parse("http://[::1]:8765").unwrap();
        assert_eq!(
            (e.host.as_str(), e.port, e.authority().as_str()),
            ("::1", 8765, "[::1]:8765")
        );
        assert!(!e.is_dns_name());
        assert!(Endpoint::parse("http://127.1").unwrap().is_dns_name());
    }

    #[test]
    fn rejects_ambiguous_forms() {
        for bad in [
            "ftp://x",
            "http://",
            "http://a@127.0.0.1",
            "http://x?y=1",
            "http://x#f",
            "http://x y",
            "http://x\r\nHost: z",
            "http://x:0",
            "http://x:99999",
            "http://x:+80",
            "http://[zz]",
            "http://[::1]x",
            "http://a\\b",
        ] {
            assert_eq!(Endpoint::parse(bad), None, "{bad:?}");
        }
    }

    #[test]
    fn quote_matches_python() {
        assert_eq!(urlencode(&[("a b", "ç/&=+%")]), "a+b=%C3%A7%2F%26%3D%2B%25");
    }
}
