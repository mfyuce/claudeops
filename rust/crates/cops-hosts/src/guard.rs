//! Adres süzgeçleri (Python `hosts.py` + `web_hosts` yardımcıları): SSRF engeli, DNS zaman aşımı, token'ın şifresiz
//! gidebileceği adresler.

use std::collections::BTreeSet;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};
use std::time::Duration;

use crate::endpoint::Endpoint;

/// `getaddrinfo`nun kendi zaman aşımı yok; asılı DNS kaydı isteği bloklamasın.
pub const DNS_CHECK_TIMEOUT: Duration = Duration::from_secs(5);

/// `menzil reach` varsayılan loopback portları (ayar `host_loopback_ports`).
pub const LOOPBACK_REACH_DEFAULT: [u16; 2] = [18765, 18766];

/// Loopback / link-local / unspecified (IPv4-mapped IPv6 açılır).
pub fn ip_is_blocked(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(a) => v4_blocked(a),
        IpAddr::V6(a) => match a.to_ipv4_mapped() {
            Some(m) => v4_blocked(m),
            None => a.is_loopback() || a.is_unspecified() || v6_link_local(a),
        },
    }
}

fn v4_blocked(a: Ipv4Addr) -> bool {
    a.is_loopback() || a.is_link_local() || a.is_unspecified()
}

fn v6_link_local(a: Ipv6Addr) -> bool {
    a.segments()[0] & 0xffc0 == 0xfe80
}

/// `host_loopback_ports` ayarı: `None` (ayar yok) = varsayılan, "" = istisna yok, bozuk parça atlanır.
pub fn reach_loopback_ports(setting: Option<&str>) -> BTreeSet<u16> {
    let Some(raw) = setting else {
        return LOOPBACK_REACH_DEFAULT.into_iter().collect();
    };
    raw.split([',', ';'])
        .map(str::trim)
        .filter(|p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit()))
        .filter_map(|p| p.parse::<u16>().ok())
        .filter(|&p| p > 0)
        .collect()
}

/// Literal loopback + izinli port + http (menzil/tünel reach dinleyicisi). `localhost` gibi DNS adları istisna DEĞİL.
pub fn is_reach_loopback(url: &str, ports: &BTreeSet<u16>) -> bool {
    let Some(e) = Endpoint::parse(url) else {
        return false;
    };
    !e.https && e.host.parse::<IpAddr>().is_ok_and(|ip| ip.is_loopback()) && ports.contains(&e.port)
}

/// Kayıt anı denetimi: ad çözülür, adreslerden biri engelliyse `true`. Çözülemez / zaman aşımı = `false` (karar
/// verilemez; bağlantı anındaki peer denetimi ikinci kapıdır).
pub async fn host_is_blocked(url: &str) -> bool {
    let Some(e) = Endpoint::parse(url) else {
        return false;
    };
    if let Ok(ip) = e.host.parse::<IpAddr>() {
        return ip_is_blocked(ip);
    }
    let host = e.host.split('%').next().unwrap_or("").to_string();
    match tokio::time::timeout(DNS_CHECK_TIMEOUT, tokio::net::lookup_host((host, e.port))).await {
        Ok(Ok(mut addrs)) => addrs.any(|a| ip_is_blocked(a.ip())),
        _ => false,
    }
}

/// `http://<özel ağ IP literali>`: yerel ağ adresi. Python `is_private`ten dar: yalnız RFC1918 ve IPv6 ULA.
pub fn is_private_lan_http(url: &str) -> bool {
    let Some(e) = Endpoint::parse(url) else {
        return false;
    };
    if e.https {
        return false;
    }
    match e.host.parse::<IpAddr>() {
        Ok(IpAddr::V4(a)) => a.is_private(),
        Ok(IpAddr::V6(a)) => match a.to_ipv4_mapped() {
            Some(m) => m.is_private(),
            None => a.segments()[0] & 0xfe00 == 0xfc00,
        },
        Err(_) => false,
    }
}

/// TBD#53 (b): `base_url` https ise token'ı şifresiz gönderecek http aday DENENMEZ (istisna: özel ağ literali, reach loopback).
pub fn candidate_allowed(base_url: &str, candidate: &str, ports: &BTreeSet<u16>) -> bool {
    let is = |u: &str, s: &str| u.get(..s.len()).is_some_and(|h| h.eq_ignore_ascii_case(s));
    if is(base_url, "https://") && !is(candidate, "https://") {
        return is_private_lan_http(candidate) || is_reach_loopback(candidate, ports);
    }
    true
}

/// Sır taşıyan gövde yalnız https ya da loopback (tünel) adresine.
pub fn secret_safe_url(url: &str) -> bool {
    Endpoint::parse(url)
        .is_some_and(|e| e.https || matches!(e.host.as_str(), "127.0.0.1" | "localhost" | "::1"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn blocked(s: &str) -> bool {
        ip_is_blocked(s.parse().unwrap())
    }

    #[test]
    fn blocked_ranges() {
        for s in [
            "127.0.0.1",
            "127.9.9.9",
            "169.254.169.254",
            "0.0.0.0",
            "::1",
            "::",
            "fe80::1",
            "::ffff:169.254.169.254",
            "::ffff:127.0.0.1",
        ] {
            assert!(blocked(s), "{s}");
        }
        for s in [
            "10.0.0.1",
            "192.168.1.5",
            "8.8.8.8",
            "fc00::1",
            "::ffff:10.0.0.1",
        ] {
            assert!(!blocked(s), "{s}");
        }
    }

    #[tokio::test]
    async fn legacy_ipv4_forms_are_blocked_at_registration() {
        for u in [
            "http://2130706433",
            "http://127.1",
            "http://0x7f000001",
            "http://localhost:1",
            "http://[::ffff:169.254.169.254]",
        ] {
            assert!(host_is_blocked(u).await, "{u}");
        }
        assert!(!host_is_blocked("http://10.1.2.3").await);
        assert!(!host_is_blocked("http://no-such-host.invalid").await);
    }

    #[test]
    fn reach_ports_setting() {
        assert_eq!(
            reach_loopback_ports(None).into_iter().collect::<Vec<_>>(),
            vec![18765, 18766]
        );
        assert!(reach_loopback_ports(Some("")).is_empty());
        assert_eq!(
            reach_loopback_ports(Some("1; 2,x,70000,0,+3"))
                .into_iter()
                .collect::<Vec<_>>(),
            vec![1, 2]
        );
        let p = reach_loopback_ports(None);
        assert!(is_reach_loopback("http://127.0.0.1:18765", &p));
        assert!(is_reach_loopback("http://[::1]:18766", &p));
        for u in [
            "https://127.0.0.1:18765",
            "http://127.0.0.1:8765",
            "http://localhost:18765",
            "http://10.0.0.1:18765",
            "http://127.0.0.1",
        ] {
            assert!(!is_reach_loopback(u, &p), "{u}");
        }
    }

    #[test]
    fn https_never_downgrades_to_public_http() {
        let p = reach_loopback_ports(None);
        let ok = |c| candidate_allowed("https://a.example", c, &p);
        assert!(ok("https://b.example"));
        assert!(ok("http://10.20.4.1:8765"));
        assert!(ok("http://127.0.0.1:18765"));
        for c in [
            "http://b.example",
            "HTTP://b.example",
            "http://8.8.8.8",
            "http://169.254.1.1",
            "http://127.0.0.1:1",
            "ftp://x",
        ] {
            assert!(!ok(c), "{c}");
        }
        assert!(candidate_allowed("HTTPS://a", "https://b", &p));
        assert!(!candidate_allowed("HTTPS://a", "http://b.example", &p));
        assert!(candidate_allowed("http://a", "http://b.example", &p));
    }

    #[test]
    fn secret_urls() {
        assert!(secret_safe_url("https://x"));
        assert!(secret_safe_url("http://127.0.0.1:1"));
        assert!(secret_safe_url("http://[::1]:1"));
        assert!(!secret_safe_url("http://10.0.0.1"));
        assert!(!secret_safe_url("http://127.0.0.1@evil.example"));
    }
}
