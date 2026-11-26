//! `urllib.request` proxy kuralları (Python 3.10): `getproxies_environment`, `proxy_bypass_environment`,
//! `_parse_proxy`, `ProxyHandler.proxy_open`. Saf: ortam listesi içeri verilir.

use crate::model_sources::SecretValue;
use crate::pyfmt::strip;
use base64::Engine as _;

/// İsteğin gideceği yol.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Route {
    Direct,
    Proxy {
        /// Proxy'nin `host[:port]` metni.
        hostport: String,
        /// Proxy'ye bağlantı TLS mi (yalnız düz `http` hedefte anlamlı; `https` hedefte proxy'ye düz `CONNECT`).
        tls_to_proxy: bool,
        /// `Proxy-Authorization` değeri.
        auth: Option<SecretValue>,
    },
    /// Proxy ayarı kullanılamıyor: istek YAPILMAZ (Python `URLError`/`ValueError`).
    Unusable,
}

/// `getproxies_environment`: `<ad>_proxy` değişkenleri; küçük harfli `_proxy` son sözü söyler, boş değeri siler.
pub fn environment(vars: &[(String, String)]) -> Vec<(String, String)> {
    fn set(map: &mut Vec<(String, String)>, k: &str, v: &str) {
        match map.iter_mut().find(|(have, _)| have == k) {
            Some(slot) => slot.1 = v.to_string(),
            None => map.push((k.to_string(), v.to_string())),
        }
    }
    let mut proxies = Vec::new();
    let mut seen = Vec::new();
    for (name, value) in vars {
        let n = name.len();
        if n > 5 && name.is_char_boundary(n - 6) && name.as_bytes()[n - 6] == b'_' && name[n - 5..].eq_ignore_ascii_case("proxy")
        {
            let proxy_name = name[..n - 6].to_lowercase();
            if !value.is_empty() {
                set(&mut proxies, &proxy_name, value);
            }
            seen.push((name, value, proxy_name));
        }
    }
    // CVE-2016-1000110: CGI altında büyük harfli HTTP_PROXY yok sayılır
    if vars.iter().any(|(k, _)| k == "REQUEST_METHOD") {
        proxies.retain(|(k, _)| k != "http");
    }
    for (name, value, proxy_name) in seen {
        if name.ends_with("_proxy") {
            if value.is_empty() {
                proxies.retain(|(k, _)| *k != proxy_name);
            } else {
                set(&mut proxies, &proxy_name, value);
            }
        }
    }
    proxies
}

/// `_splitport`: sondaki `:<rakamlar>`.
fn without_port(host: &str) -> &str {
    match host.rsplit_once(':') {
        Some((h, port)) if port.bytes().all(|b| b.is_ascii_digit()) => h,
        _ => host,
    }
}

/// `proxy_bypass_environment`.
pub fn bypass(host: &str, no_proxy: &str) -> bool {
    if no_proxy == "*" {
        return true;
    }
    let host = host.to_lowercase();
    let bare = without_port(&host);
    no_proxy.split(',').map(strip).filter(|n| !n.is_empty()).any(|name| {
        let name = name.trim_start_matches('.').to_lowercase();
        let suffix = format!(".{name}");
        bare == name || host == name || bare.ends_with(&suffix) || host.ends_with(&suffix)
    })
}

/// `urllib.parse.unquote` (UTF-8, geçersiz baytlar U+FFFD).
fn unquote(s: &str) -> String {
    let bytes = s.as_bytes();
    let hex = |b: u8| (b as char).to_digit(16);
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' {
            if let (Some(a), Some(b)) = (bytes.get(i + 1).and_then(|b| hex(*b)), bytes.get(i + 2).and_then(|b| hex(*b))) {
                out.push((a * 16 + b) as u8);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

struct Parsed<'a> {
    scheme: Option<String>,
    user: Option<&'a str>,
    password: Option<&'a str>,
    hostport: &'a str,
}

/// `_splittype`: `([^/:]+):(.*)`.
fn split_type(url: &str) -> (Option<String>, &str) {
    match url.find([':', '/']) {
        Some(i) if i > 0 && url.as_bytes()[i] == b':' => (Some(url[..i].to_lowercase()), &url[i + 1..]),
        _ => (None, url),
    }
}

/// `_parse_proxy`; yetki bölümü olmayan adreste None (Python `ValueError`).
fn parse_proxy(proxy: &str) -> Option<Parsed<'_>> {
    let (scheme, rest) = split_type(proxy);
    let (scheme, authority) = if !rest.starts_with('/') {
        // adres değil, doğrudan yetki bölümü
        (None, proxy)
    } else {
        if !rest.starts_with("//") {
            return None;
        }
        let from = rest.find('@').unwrap_or(2);
        let end = rest[from..].find('/').map_or(rest.len(), |i| i + from);
        (scheme, &rest[2..end.max(2)])
    };
    let (userinfo, hostport) = match authority.rsplit_once('@') {
        Some((u, h)) => (Some(u), h),
        None => (None, authority),
    };
    let (user, password) = match userinfo {
        Some(u) => u.split_once(':').map_or((Some(u), None), |(a, b)| (Some(a), Some(b))),
        None => (None, None),
    };
    Some(Parsed { scheme, user, password, hostport })
}

/// `scheme` (`http`/`https`) ve hedefin `host[:port]` metni için yol. Yalnız hedef şemasının değişkeni kullanılır
/// (`all_proxy` Python'da etkisizdir).
pub fn route(vars: &[(String, String)], scheme: &str, netloc: &str) -> Route {
    let proxies = environment(vars);
    let get = |k: &str| proxies.iter().find(|(have, _)| have == k).map(|(_, v)| v.as_str());
    let Some(proxy) = get(scheme) else { return Route::Direct };
    let Some(Parsed { scheme: proxy_type, user, password, hostport }) = parse_proxy(proxy) else { return Route::Unusable };
    if !netloc.is_empty() && get("no").is_some_and(|no| bypass(netloc, no)) {
        return Route::Direct;
    }
    let proxy_type = proxy_type.unwrap_or_else(|| scheme.to_string());
    let auth = match (user.filter(|u| !u.is_empty()), password.filter(|p| !p.is_empty())) {
        (Some(u), Some(p)) => {
            let raw = format!("{}:{}", unquote(u), unquote(p));
            SecretValue::new(&format!("Basic {}", base64::engine::general_purpose::STANDARD.encode(raw)))
        }
        _ => None,
    };
    let hostport = unquote(hostport);
    let tls_to_proxy = match (scheme, proxy_type.as_str()) {
        ("https", _) | ("http", "http") => false,
        ("http", "https") => true,
        _ => return Route::Unusable,
    };
    if hostport.is_empty() {
        return Route::Unusable;
    }
    Route::Proxy { hostport, tls_to_proxy, auth }
}
