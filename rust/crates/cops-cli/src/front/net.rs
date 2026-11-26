//! Adres ayrıştırma, port yoklaması ve "portu kim dinliyor" (systemd birimi) tespiti.
//!
//! Python `front_cmd.port_busy` `rpartition(":")` + `int(port)` + AF_INET soketle `connect_ex` yapar: iki noktasız `--internal
//! 28765` `("", 28765)` olarak geçer, sayı olmayan port `ValueError` dökümü verir, `[::1]:port` AF_INET'te hata verir
//! (docs/rs-gate-eslik.md "Python hatası?" 4). Rust ([`parse_listen`], [`parse_internal`]):
//! - biçim `IPv4:port` ya da `[IPv6]:port`; port yalnız ASCII rakam, 1..=65535 (0 = rastgele port, reddedilir);
//! - ad (`localhost:8765`) REDDEDİLİR: copsd `--listen/--upstream`u `SocketAddr` olarak ayrıştırır, adı kabul etmez;
//! - `--internal` yalnız IPv4: Python web `ThreadingHTTPServer` AF_INET ile dinler, IPv6 iç adrese bağlanamaz.
//!
//! [`port_owner`]: portu dinleyen soket `/proc/net/tcp{,6}` (LISTEN, yerel adres eşleşmesi: kesin IP ya da joker), soketi
//! tutan süreçler yalnız KENDİ uid'imizin `/proc/<pid>/fd` bağlantılarından (`socket:[inode]`), birimi `/proc/<pid>/cgroup`
//! yolunun son parçasından (`.../app.slice/claudeops-web.service`). "Bizim web birimimiz" = soketi tutan HER süreç
//! `claudeops-web.service` cgroup'unda. Gerekçe: systemd her birimi kendi cgroup'una koyar; `MainPID` (`bash -ic` sarmalayıcı)
//! ya da komut satırı adı (`python3 -m claudeops web` başka bir kopya da olabilir) bunu kanıtlamaz. Bulunamayan, başka
//! kullanıcının ya da okunamayan dinleyici "bizim değil" sayılır (kapalı yön).

use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr, SocketAddrV4};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::time::Duration;

/// Python web birimi.
pub const WEB_UNIT_NAME: &str = "claudeops-web.service";
/// Ön kapı birimi.
pub const FRONT_UNIT_NAME: &str = "claudeops-front.service";

fn parse_port(p: &str) -> Result<u16, String> {
    if p.is_empty() || p.len() > 5 || !p.bytes().all(|b| b.is_ascii_digit()) {
        return Err(format!("port sayı değil: {p:?}"));
    }
    match p.parse::<u32>() {
        Ok(n) if (1..=65535).contains(&n) => Ok(n as u16),
        _ => Err(format!("port aralık dışı (1-65535): {p}")),
    }
}

/// `IPv4:port` ya da `[IPv6]:port`.
pub fn parse_listen(s: &str) -> Result<SocketAddr, String> {
    let Some((host, port)) = s.rsplit_once(':') else {
        return Err(format!("{s:?}: IP:port biçiminde değil (iki nokta yok)"));
    };
    let port = parse_port(port).map_err(|e| format!("{s:?}: {e}"))?;
    if let Some(inner) = host.strip_prefix('[').and_then(|h| h.strip_suffix(']')) {
        return inner
            .parse::<Ipv6Addr>()
            .map(|ip| SocketAddr::new(IpAddr::V6(ip), port))
            .map_err(|_| format!("{s:?}: geçersiz IPv6 adresi"));
    }
    host.parse::<Ipv4Addr>()
        .map(|ip| SocketAddr::new(IpAddr::V4(ip), port))
        .map_err(|_| {
            format!(
                "{s:?}: adres IPv4 ya da [IPv6] olmalı (ad kabul edilmez, copsd SocketAddr ister)"
            )
        })
}

/// Yalnız `IPv4:port` (Python web AF_INET).
pub fn parse_internal(s: &str) -> Result<SocketAddrV4, String> {
    match parse_listen(s)? {
        SocketAddr::V4(a) => Ok(a),
        SocketAddr::V6(_) => Err(format!(
            "{s:?}: iç adres IPv6 olamaz (Python web yalnız IPv4 dinler: ThreadingHTTPServer AF_INET)"
        )),
    }
}

/// Portu dinleyen.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PortOwner {
    /// Dinleyen soket bulunamadı.
    NoListener,
    /// Soket başka kullanıcının (uid).
    OtherUser(u32),
    /// Soket bizim ama tutan süreç bulunamadı (başka ad alanı ya da yarış).
    Unknown,
    /// Tutan süreçler (pid, birim adı; birimsizse `None`).
    Holders(Vec<(u32, Option<String>)>),
}

impl PortOwner {
    /// Soketi tutan her süreç `unit` biriminde mi.
    pub fn is_unit(&self, unit: &str) -> bool {
        matches!(self, PortOwner::Holders(h) if !h.is_empty() && h.iter().all(|(_, u)| u.as_deref() == Some(unit)))
    }

    /// İnsan için kısa açıklama.
    pub fn describe(&self) -> String {
        match self {
            PortOwner::NoListener => "dinleyen soket bulunamadı".into(),
            PortOwner::OtherUser(u) => format!("başka kullanıcının soketi (uid {u})"),
            PortOwner::Unknown => "soketi tutan süreç bulunamadı".into(),
            PortOwner::Holders(h) => h
                .iter()
                .map(|(p, u)| format!("pid {p} ({})", u.as_deref().unwrap_or("birimsiz")))
                .collect::<Vec<_>>()
                .join(", "),
        }
    }
}

/// Ağ yoklamaları (testte sahte).
pub trait Net {
    /// Python `port_busy`: bağlantı kurulabiliyor mu (0,5 sn).
    fn busy(&self, a: SocketAddr) -> bool;
    /// Portu dinleyen süreçler ve birimleri.
    fn owner(&self, a: SocketAddr) -> PortOwner;
}

/// Gerçek makine: TCP bağlantısı + `/proc`.
pub struct RealNet {
    /// `/proc`
    pub proc_root: PathBuf,
    /// Gerçek uid.
    pub uid: u32,
}

impl Net for RealNet {
    fn busy(&self, a: SocketAddr) -> bool {
        std::net::TcpStream::connect_timeout(&a, Duration::from_millis(500)).is_ok()
    }

    fn owner(&self, a: SocketAddr) -> PortOwner {
        port_owner(&self.proc_root, self.uid, a)
    }
}

/// `/proc/net/tcp` adres alanı (`0100007F:1F90`): çekirdek her 32 bitlik sözcüğü konak bayt sırasıyla yazar.
fn parse_hex_addr(s: &str) -> Option<(IpAddr, u16)> {
    let (ip, port) = s.split_once(':')?;
    let port = u16::from_str_radix(port, 16).ok()?;
    let word = |w: &str| u32::from_str_radix(w, 16).ok().map(u32::to_ne_bytes);
    match ip.len() {
        8 => Some((IpAddr::V4(Ipv4Addr::from(word(ip)?)), port)),
        32 => {
            let mut b = [0u8; 16];
            for i in 0..4 {
                b[i * 4..i * 4 + 4].copy_from_slice(&word(ip.get(i * 8..i * 8 + 8)?)?);
            }
            Some((IpAddr::V6(Ipv6Addr::from(b)), port))
        }
        _ => None,
    }
}

/// `a`'ya gelen bağlantıyı kabul eden dinleyici adresi mi.
fn accepts(local: IpAddr, a: IpAddr) -> bool {
    let a = a.to_canonical();
    match local {
        IpAddr::V4(l) => l.is_unspecified() || IpAddr::V4(l) == a,
        IpAddr::V6(l) => {
            l.is_unspecified() || IpAddr::V6(l) == a || IpAddr::V6(l).to_canonical() == a
        }
    }
}

/// LISTEN soketleri: (inode, uid).
fn listeners(proc_root: &Path, a: SocketAddr) -> Vec<(u64, u32)> {
    let mut out = Vec::new();
    for f in ["net/tcp", "net/tcp6"] {
        let Ok(text) = std::fs::read_to_string(proc_root.join(f)) else {
            continue;
        };
        for line in text.lines().skip(1) {
            let c: Vec<&str> = line.split_whitespace().collect();
            if c.len() < 10 || c[3] != "0A" {
                continue;
            }
            let Some((ip, port)) = parse_hex_addr(c[1]) else {
                continue;
            };
            if port != a.port() || !accepts(ip, a.ip()) {
                continue;
            }
            if let (Ok(uid), Ok(ino)) = (c[7].parse::<u32>(), c[9].parse::<u64>()) {
                out.push((ino, uid));
            }
        }
    }
    out
}

/// `/proc/<pid>/cgroup` içindeki birim adı (yolun son parçası `.service`/`.scope` ise).
pub fn unit_of(proc_root: &Path, pid: u32) -> Option<String> {
    let text = std::fs::read_to_string(proc_root.join(pid.to_string()).join("cgroup")).ok()?;
    for line in text.lines() {
        let path = line.splitn(3, ':').nth(2)?;
        let last = path.rsplit('/').next()?;
        if last.ends_with(".service") || last.ends_with(".scope") {
            return Some(last.to_string());
        }
    }
    None
}

/// Bkz. modül belgesi.
pub fn port_owner(proc_root: &Path, uid: u32, a: SocketAddr) -> PortOwner {
    let socks = listeners(proc_root, a);
    if socks.is_empty() {
        return PortOwner::NoListener;
    }
    if let Some(&(_, u)) = socks.iter().find(|(_, u)| *u != uid) {
        return PortOwner::OtherUser(u);
    }
    let want: Vec<String> = socks.iter().map(|(i, _)| format!("socket:[{i}]")).collect();
    let mut holders = Vec::new();
    let Ok(rd) = std::fs::read_dir(proc_root) else {
        return PortOwner::Unknown;
    };
    for e in rd.flatten() {
        let Some(pid) = e.file_name().to_str().and_then(|s| s.parse::<u32>().ok()) else {
            continue;
        };
        match e.metadata() {
            Ok(m) if m.uid() == uid => {}
            _ => continue,
        }
        let Ok(fds) = std::fs::read_dir(e.path().join("fd")) else {
            continue;
        };
        let held = fds.flatten().any(|fd| {
            std::fs::read_link(fd.path())
                .ok()
                .and_then(|t| t.to_str().map(|s| want.iter().any(|w| w == s)))
                .unwrap_or(false)
        });
        if held {
            holders.push((pid, unit_of(proc_root, pid)));
        }
    }
    if holders.is_empty() {
        PortOwner::Unknown
    } else {
        holders.sort();
        PortOwner::Holders(holders)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn listen_and_internal_parsing() {
        assert_eq!(
            parse_listen("127.0.0.1:8765").unwrap().to_string(),
            "127.0.0.1:8765"
        );
        assert_eq!(
            parse_listen("[::1]:8765").unwrap().to_string(),
            "[::1]:8765"
        );
        assert_eq!(parse_listen("127.0.0.1:08765").unwrap().port(), 8765);
        for bad in [
            "28765",
            "127.0.0.1:",
            "127.0.0.1:abc",
            "127.0.0.1:+80",
            "127.0.0.1:0",
            "127.0.0.1:65536",
            "127.0.0.1:999999",
            "localhost:8765",
            ":8765",
            "[::1:8765",
            "::1:8765",
            "127.0.0.1:８７",
        ] {
            assert!(parse_listen(bad).is_err(), "{bad}");
        }
        assert!(parse_internal("[::1]:28765").unwrap_err().contains("IPv6"));
        assert!(parse_internal("28765").unwrap_err().contains("iki nokta"));
        assert_eq!(parse_internal("127.0.0.1:28765").unwrap().port(), 28765);
    }

    #[test]
    fn proc_net_hex_addresses() {
        let (ip, port) = parse_hex_addr("0100007F:6FDD").unwrap();
        if cfg!(target_endian = "little") {
            assert_eq!(ip, IpAddr::V4(Ipv4Addr::LOCALHOST));
        }
        assert_eq!(port, 0x6FDD);
        let (ip6, _) = parse_hex_addr("00000000000000000000000001000000:1F90").unwrap();
        if cfg!(target_endian = "little") {
            assert_eq!(ip6, IpAddr::V6(Ipv6Addr::LOCALHOST));
        }
        assert!(accepts(
            "0.0.0.0".parse().unwrap(),
            "127.0.0.1".parse().unwrap()
        ));
        assert!(accepts("::".parse().unwrap(), "127.0.0.1".parse().unwrap()));
        assert!(!accepts(
            "127.0.0.2".parse().unwrap(),
            "127.0.0.1".parse().unwrap()
        ));
    }

    #[test]
    fn real_listener_is_found_with_our_pid() {
        let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let a = l.local_addr().unwrap();
        // SAFETY: argümansız libc çağrısı.
        let uid = unsafe { libc::getuid() };
        let o = port_owner(Path::new("/proc"), uid, a);
        match &o {
            PortOwner::Holders(h) => {
                assert!(h.iter().any(|(p, _)| *p == std::process::id()), "{o:?}")
            }
            other => panic!("{other:?}"),
        }
        assert!(!o.is_unit(WEB_UNIT_NAME));
        drop(l);
        assert_eq!(
            port_owner(Path::new("/proc"), uid, a),
            PortOwner::NoListener
        );
    }

    #[test]
    fn fake_proc_tree_unit_detection() {
        let t = tempfile::tempdir().unwrap();
        let p = t.path();
        std::fs::create_dir_all(p.join("net")).unwrap();
        let head = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n";
        // SAFETY: argümansız libc çağrısı.
        let uid = unsafe { libc::getuid() };
        let addr = if cfg!(target_endian = "little") {
            "0100007F"
        } else {
            "7F000001"
        };
        std::fs::write(
            p.join("net/tcp"),
            format!("{head}   0: {addr}:6FDD 00000000:0000 0A 00000000:00000000 00:00000000 00000000  {uid}        0 4242 1 0 100 0 0 10 0\n"),
        )
        .unwrap();
        std::fs::create_dir_all(p.join("77/fd")).unwrap();
        std::os::unix::fs::symlink("socket:[4242]", p.join("77/fd/3")).unwrap();
        std::fs::write(
            p.join("77/cgroup"),
            "0::/user.slice/user-1000.slice/user@1000.service/app.slice/claudeops-web.service\n",
        )
        .unwrap();
        let a: SocketAddr = "127.0.0.1:28637".parse().unwrap();
        let o = port_owner(p, uid, a);
        assert!(o.is_unit(WEB_UNIT_NAME), "{o:?}");
        // başka bir süreç (birimsiz) de aynı soketi tutuyorsa bizim değil
        std::fs::create_dir_all(p.join("78/fd")).unwrap();
        std::os::unix::fs::symlink("socket:[4242]", p.join("78/fd/9")).unwrap();
        std::fs::write(p.join("78/cgroup"), "0::/user.slice/x.scope/\n").unwrap();
        assert!(!port_owner(p, uid, a).is_unit(WEB_UNIT_NAME));
        // başka kullanıcının soketi
        assert_eq!(
            port_owner(p, uid.wrapping_add(1), a),
            PortOwner::OtherUser(uid)
        );
    }
}
