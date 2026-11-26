//! Ön kapı gizlisi (`front.secret`) ve güvenilen istemci IP'si: Python `front.py` (`read_secret`, `trusted_front`) ve
//! `commands/web.py` `trusted_forwarded_ip` karşılıkları.
//!
//! - [`FrontSecret`]: ortam değişkeni `CLAUDEOPS_FRONT_SECRET` (boş değilse, kırpılmadan) ya da dosya. Dosya her sorguda `stat`
//!   edilir, imzası (aygıt, inode, boyut, mtime, ctime, mod) değişince yeniden okunur (Python her çağrıda okur). Yok, grup/diğer
//!   izinli, düzenli dosya değil, UTF-8 değil, 64 KiB üstü ya da boş = gizli YOK (kapalı yön: hiçbir `X-Cops-Front`a güvenilmez,
//!   aktarılan isteğe gizli eklenmez). Python bozuk UTF-8'de istisna fırlatır ("Python hatası?" 1); Rust kapalı yöne düşer.
//! - [`FrontSecret::trusted`]: Python `trusted_front` (gizli dolu, eş loopback, başlık sabit zamanlı eşit).
//! - [`trusted_client_ip`]: Python `trusted_forwarded_ip` ile aynı kural (metin üstünde).
//! - [`pin_client_ip`]: gizli olsun olmasın, Python'un uzak istemciyi `127.0.0.1` görmemesi için copsd uzak eşin adresini
//!   `Cf-Connecting-IP`ye yazar (gerekçe: `docs/rs-gate.md` "Gizli yaşam döngüsü").

use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

/// Python `front.LOOPBACK` ve `trusted_forwarded_ip` içindeki küme (metin).
pub const LOOPBACK: [&str; 2] = ["127.0.0.1", "::1"];

/// Gizli dosyası okuma sınırı (gizli 64 hex karakter; fazlası bozuk sayılır).
const MAX_SECRET_BYTES: u64 = 64 * 1024;

use cops_auth::{ct_eq, py_strip};

/// Eş, Python'un loopback saydığı iki adresten biri mi (IPv4 eşlemeli `::ffff:127.0.0.1` kanonik yazımıyla `127.0.0.1`
/// sayılır, 030b4ab). `127.0.0.2` gibi diğer 127/8 adresleri SAYILMAZ (Python ile aynı, `is_loopback`ten sıkı).
pub fn python_loopback(ip: IpAddr) -> bool {
    match ip.to_canonical() {
        IpAddr::V4(a) => a == Ipv4Addr::LOCALHOST,
        IpAddr::V6(a) => a == Ipv6Addr::LOCALHOST,
    }
}

/// Dosya imzası: değişince içerik yeniden okunur.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Sig {
    dev: u64,
    ino: u64,
    size: u64,
    mtime: (i64, i64),
    ctime: (i64, i64),
    mode: u32,
}

fn sig(m: &std::fs::Metadata) -> Sig {
    use std::os::unix::fs::MetadataExt;
    Sig {
        dev: m.dev(),
        ino: m.ino(),
        size: m.size(),
        mtime: (m.mtime(), m.mtime_nsec()),
        ctime: (m.ctime(), m.ctime_nsec()),
        mode: m.mode(),
    }
}

/// Gizli dosyasının durumu.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SecretFile {
    /// Dosya yok.
    Missing,
    /// Okundu; değer kırpılmış (Python `strip()`), boş olabilir.
    Value(String),
    /// Var ama kullanılamaz (grup/diğer izni, düzenli dosya değil, okunamadı, UTF-8 değil, çok büyük). Metin tanı içindir, sır taşımaz.
    Unusable(String),
}

/// Dosyayı tek açık tanıtıcıdan okur (izin ve içerik aynı dosyadan).
pub fn read_secret_file(path: &Path) -> SecretFile {
    use std::io::Read;
    use std::os::unix::fs::PermissionsExt;
    let f = match std::fs::File::open(path) {
        Ok(f) => f,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return SecretFile::Missing,
        Err(e) => return SecretFile::Unusable(format!("açılamadı: {}", e.kind())),
    };
    let m = match f.metadata() {
        Ok(m) => m,
        Err(e) => return SecretFile::Unusable(format!("stat: {}", e.kind())),
    };
    if !m.is_file() {
        return SecretFile::Unusable("düzenli dosya değil".into());
    }
    if m.permissions().mode() & 0o077 != 0 {
        return SecretFile::Unusable("izinler 0600 değil".into());
    }
    let mut buf = Vec::new();
    if let Err(e) = f.take(MAX_SECRET_BYTES + 1).read_to_end(&mut buf) {
        return SecretFile::Unusable(format!("okunamadı: {}", e.kind()));
    }
    if buf.len() as u64 > MAX_SECRET_BYTES {
        return SecretFile::Unusable("çok büyük".into());
    }
    match String::from_utf8(buf) {
        Ok(s) => SecretFile::Value(py_strip(&s).to_string()),
        Err(_) => SecretFile::Unusable("UTF-8 değil".into()),
    }
}

enum Src {
    Fixed(Option<String>),
    File {
        path: PathBuf,
        cache: Mutex<Option<(Sig, Option<String>)>>,
    },
}

/// Ön kapı gizlisi (bkz. modül belgesi).
pub struct FrontSecret {
    src: Src,
}

impl FrontSecret {
    /// Sabit değer (boş = gizli yok). Python ortam değişkeni gibi KIRPILMAZ.
    pub fn fixed(v: Option<&str>) -> FrontSecret {
        FrontSecret {
            src: Src::Fixed(v.filter(|s| !s.is_empty()).map(str::to_string)),
        }
    }

    /// Dosya: her sorguda `stat`, imza değişince yeniden okuma.
    pub fn file(path: impl Into<PathBuf>) -> FrontSecret {
        FrontSecret {
            src: Src::File {
                path: path.into(),
                cache: Mutex::new(None),
            },
        }
    }

    /// Python `read_secret` önceliği: `CLAUDEOPS_FRONT_SECRET` boş değilse o (sabit), yoksa `path`.
    pub fn from_env_or_file(path: impl Into<PathBuf>) -> FrontSecret {
        match std::env::var("CLAUDEOPS_FRONT_SECRET") {
            Ok(s) if !s.is_empty() => FrontSecret::fixed(Some(&s)),
            _ => FrontSecret::file(path),
        }
    }

    /// Dosya kaynaklıysa yolu.
    pub fn path(&self) -> Option<&Path> {
        match &self.src {
            Src::Fixed(_) => None,
            Src::File { path, .. } => Some(path),
        }
    }

    /// Şu anki gizli; yoksa ya da kullanılamazsa `None`.
    pub fn current(&self) -> Option<String> {
        let (path, cache) = match &self.src {
            Src::Fixed(v) => return v.clone(),
            Src::File { path, cache } => (path, cache),
        };
        // `stat` başarısızsa (yok, erişilemez) önbellek de silinir: eski değer yaşamaz.
        let now = match std::fs::metadata(path) {
            Ok(m) => sig(&m),
            Err(_) => {
                *cache.lock().unwrap_or_else(|p| p.into_inner()) = None;
                return None;
            }
        };
        let mut g = cache.lock().unwrap_or_else(|p| p.into_inner());
        if let Some((s, v)) = g.as_ref() {
            if *s == now {
                return v.clone();
            }
        }
        let v = match read_secret_file(path) {
            SecretFile::Value(v) if !v.is_empty() => Some(v),
            _ => None,
        };
        *g = Some((now, v.clone()));
        v
    }

    /// Python `trusted_front`: gizli dolu, eş Python loopback'i, `X-Cops-Front` (ilk satır, ham bayt) sabit zamanlı eşit.
    pub fn trusted(&self, peer: IpAddr, header: Option<&[u8]>) -> bool {
        if !python_loopback(peer) {
            return false;
        }
        match self.current() {
            Some(sec) => ct_eq(header.unwrap_or(b""), sec.as_bytes()),
            None => false,
        }
    }
}

/// Python `trusted_forwarded_ip(peer, headers, secret)`: `header(ad)` adı harf duyarsız İLK değer.
///
/// Kural: (1) eş (metin) `127.0.0.1`/`::1` değilse eş; (2) gizli dolu ve `X-Cops-Front` eşitse `X-Forwarded-For`un son parçası
/// (kırpılmış; boşsa eş); (3) sonuç hâlâ loopback metniyse geçerli `Cf-Connecting-IP`nin kanonik yazımı.
///
/// Biçim farkı: Python IPv4 eşlemeli adresi `::ffff:102:304`, Rust `::ffff:1.2.3.4` yazar; kapsam kimlikli IPv6'yı Rust kabul
/// etmez (loopback kalır).
pub fn trusted_client_ip<'a, H>(peer: &'a str, header: H, secret: &str) -> String
where
    H: Fn(&str) -> Option<&'a str>,
{
    if !LOOPBACK.contains(&peer) {
        return peer.to_string();
    }
    let mut ip = peer.to_string();
    let got = header("X-Cops-Front").unwrap_or("");
    if !secret.is_empty() && ct_eq(got.as_bytes(), secret.as_bytes()) {
        let xff = header("X-Forwarded-For").unwrap_or("");
        let last = py_strip(xff.rsplit(',').next().unwrap_or(""));
        if !last.is_empty() {
            ip = last.to_string();
        }
    }
    if LOOPBACK.contains(&ip.as_str()) {
        if let Ok(a) = py_strip(header("Cf-Connecting-IP").unwrap_or("")).parse::<IpAddr>() {
            ip = a.to_string();
        }
    }
    ip
}

/// Vekillenen istekte Python'un göreceği istemci IP'si, Rust görünümünden ([`crate::request_view`]: `client_ip` = soket eşi).
/// copsd istemcinin `X-Cops-Front`/`X-Forwarded-For` kopyasını siler, kendi eşini yazar: gizli adımı sonucu değiştirmez, kalan
/// kural "eş loopback ise geçerli `Cf-Connecting-IP`". `RequestView.client_ip` sözleşmesi DEĞİŞMEDİ (soket eşi); Python
/// `_client_ip`ye eşit değer isteyen uç (T7/T9) bunu çağırır.
pub fn view_client_ip(view: &cops_auth::authz::RequestView) -> IpAddr {
    let peer = view.client_ip.to_canonical().to_string();
    let ip = trusted_client_ip(&peer, |n| view.header(&n.to_ascii_lowercase()), "");
    ip.parse().unwrap_or(view.client_ip)
}

/// Aktarılan isteğin istemci IP başlıkları: eş Python loopback'i DEĞİLSE `Cf-Connecting-IP` = eşin kanonik adresi (istemcinin
/// kopyası ezilir). Loopback eşte (aynı makinedeki tünel) tünelin başlığı aynen kalır. Böylece gizli yokken de (Python
/// `X-Forwarded-For`a güvenmez, eşi `127.0.0.1` görür) Python `_client_ip` loopback adımında uzak istemcinin GERÇEK adresini
/// bulur; gizli varken `X-Forwarded-For` = eş loopback olmadığından başlık okunmaz (sonuç değişmez).
pub fn pin_client_ip(h: &mut hyper::HeaderMap, peer: SocketAddr) {
    let ip = peer.ip().to_canonical();
    if python_loopback(ip) {
        return;
    }
    h.remove("cf-connecting-ip");
    if let Ok(v) = hyper::header::HeaderValue::from_str(&ip.to_string()) {
        h.insert("cf-connecting-ip", v);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    /// `py/tests/test_front_xff.py` vektörleri (adı ve beklenen değer aynı).
    #[test]
    fn trusted_client_ip_matches_python_test_front_xff() {
        let t = |peer: &str, hs: &[(&str, &str)], sec: &str| {
            let h = |n: &str| -> Option<&str> {
                hs.iter()
                    .find(|(k, _)| k.eq_ignore_ascii_case(n))
                    .map(|(_, v)| *v)
            };
            trusted_client_ip(peer, h, sec)
        };
        // test_no_secret_ignores_header
        assert_eq!(
            t("127.0.0.1", &[("X-Forwarded-For", "9.9.9.9")], ""),
            "127.0.0.1"
        );
        // test_wrong_or_missing_secret
        assert_eq!(
            t(
                "127.0.0.1",
                &[("X-Forwarded-For", "9.9.9.9"), ("X-Cops-Front", "x")],
                "s"
            ),
            "127.0.0.1"
        );
        assert_eq!(
            t("127.0.0.1", &[("X-Forwarded-For", "9.9.9.9")], "s"),
            "127.0.0.1"
        );
        // test_non_loopback_peer_never_trusted
        assert_eq!(
            t(
                "10.0.0.5",
                &[("X-Forwarded-For", "9.9.9.9"), ("X-Cops-Front", "s")],
                "s"
            ),
            "10.0.0.5"
        );
        // test_tunnel_client_ip_only_from_loopback
        let cf = ("Cf-Connecting-IP", "203.0.113.7");
        assert_eq!(t("127.0.0.1", &[cf], ""), "203.0.113.7");
        assert_eq!(t("10.0.0.5", &[cf], ""), "10.0.0.5");
        let front = ("X-Cops-Front", "s");
        assert_eq!(
            t(
                "127.0.0.1",
                &[cf, front, ("X-Forwarded-For", "127.0.0.1")],
                "s"
            ),
            "203.0.113.7"
        );
        assert_eq!(
            t(
                "127.0.0.1",
                &[cf, front, ("X-Forwarded-For", "10.0.0.5")],
                "s"
            ),
            "10.0.0.5"
        );
        assert_eq!(
            t("127.0.0.1", &[("Cf-Connecting-IP", "1.1.1.1|*")], ""),
            "127.0.0.1"
        );
        // test_valid_secret_uses_last_xff
        assert_eq!(
            t(
                "127.0.0.1",
                &[
                    ("X-Forwarded-For", "6.6.6.6, 1.2.3.4"),
                    ("X-Cops-Front", "s")
                ],
                "s"
            ),
            "1.2.3.4"
        );
        assert_eq!(t("::1", &[("X-Cops-Front", "s")], "s"), "::1");
        // Ek: boş XFF eşi bırakır; 127.0.0.2 Python'da loopback değil; kırpma U+001C dahil.
        assert_eq!(
            t("127.0.0.1", &[("X-Forwarded-For", " "), front], "s"),
            "127.0.0.1"
        );
        assert_eq!(t("127.0.0.2", &[cf], ""), "127.0.0.2");
        assert_eq!(
            t(
                "127.0.0.1",
                &[("Cf-Connecting-IP", "\u{1c}203.0.113.7 ")],
                ""
            ),
            "203.0.113.7"
        );
    }

    /// Adres tablosu: Python loopback kümesi kanonik yazımdan sonra; 127/8'in geri kalanı, belirsiz ve özel adresler DEĞİL.
    #[test]
    fn python_loopback_address_table() {
        for (ip, want) in [
            ("127.0.0.1", true),
            ("::1", true),
            ("::ffff:127.0.0.1", true),
            ("127.0.0.2", false),
            ("::ffff:127.0.0.2", false),
            ("0.0.0.0", false),
            ("::", false),
            ("10.0.0.5", false),
            ("192.168.1.1", false),
            ("::ffff:10.0.0.5", false),
            ("fe80::1", false),
            ("169.254.1.1", false),
        ] {
            assert_eq!(python_loopback(ip.parse().unwrap()), want, "{ip}");
        }
    }

    #[test]
    fn pin_client_ip_overwrites_only_for_non_loopback_peers() {
        for (peer, client_cf, want) in [
            ("127.0.0.1:5", Some("203.0.113.7"), Some("203.0.113.7")),
            ("[::1]:5", None, None),
            (
                "[::ffff:127.0.0.1]:5",
                Some("203.0.113.7"),
                Some("203.0.113.7"),
            ),
            ("10.0.0.5:5", Some("1.1.1.1"), Some("10.0.0.5")),
            ("10.0.0.5:5", None, Some("10.0.0.5")),
            ("[::ffff:10.0.0.5]:5", None, Some("10.0.0.5")),
            ("[2001:db8::7]:5", None, Some("2001:db8::7")),
            ("127.0.0.2:5", Some("1.1.1.1"), Some("127.0.0.2")),
        ] {
            let mut h = hyper::HeaderMap::new();
            if let Some(v) = client_cf {
                h.append("cf-connecting-ip", v.parse().unwrap());
                h.append("cf-connecting-ip", "9.9.9.9".parse().unwrap());
            }
            pin_client_ip(&mut h, peer.parse().unwrap());
            assert_eq!(
                h.get("cf-connecting-ip").map(|v| v.to_str().unwrap()),
                want,
                "{peer}"
            );
            if !python_loopback(peer.parse::<SocketAddr>().unwrap().ip()) {
                assert_eq!(h.get_all("cf-connecting-ip").iter().count(), 1, "{peer}");
            }
        }
    }

    /// Uçtan uca kural: copsd'nin aktardığı başlıklar ([`crate::prepare_forward_headers`]) + Python `trusted_forwarded_ip`
    /// (eş = copsd, `127.0.0.1`). Gizli VAR ya da YOK, Python'un bulduğu istemci = Python'a doğrudan bağlansa bulacağı adres:
    /// uzak istemci loopback GÖRÜNMEZ, tünelin (loopback eş) `Cf-Connecting-IP`si korunur, uzak eşin sahte başlıkları etkisiz.
    #[test]
    fn python_sees_real_client_with_or_without_secret() {
        type Case<'a> = (&'a str, &'a [(&'a str, &'a str)], &'a str);
        let cases: [Case; 6] = [
            ("10.0.0.5:4", &[], "10.0.0.5"),
            (
                "10.0.0.5:4",
                &[
                    ("cf-connecting-ip", "127.0.0.1"),
                    ("x-forwarded-for", "127.0.0.1"),
                    ("x-cops-front", "s"),
                ],
                "10.0.0.5",
            ),
            (
                "[2001:db8::7]:4",
                &[("cf-connecting-ip", "1.2.3.4")],
                "2001:db8::7",
            ),
            (
                "127.0.0.1:4",
                &[("cf-connecting-ip", "203.0.113.7")],
                "203.0.113.7",
            ),
            ("127.0.0.1:4", &[], "127.0.0.1"),
            (
                "127.0.0.2:4",
                &[("cf-connecting-ip", "203.0.113.7")],
                "127.0.0.2",
            ),
        ];
        for secret in [None, Some("s3cret")] {
            for (peer, hs, want) in cases {
                let mut h = hyper::HeaderMap::new();
                for (k, v) in hs {
                    h.append(*k, v.parse().unwrap());
                }
                crate::prepare_forward_headers(&mut h, peer.parse().unwrap(), secret);
                let get = |n: &str| h.get(n.to_ascii_lowercase()).and_then(|v| v.to_str().ok());
                let got = trusted_client_ip("127.0.0.1", get, secret.unwrap_or(""));
                assert_eq!(got, want, "{peer} gizli={secret:?}");
            }
        }
    }

    fn tmpfile(tag: &str) -> PathBuf {
        std::env::temp_dir().join(format!("cops-front-{tag}-{}", std::process::id()))
    }

    fn put(p: &Path, b: &[u8], mode: u32) {
        let _ = std::fs::remove_file(p);
        std::fs::write(p, b).unwrap();
        std::fs::set_permissions(p, std::fs::Permissions::from_mode(mode)).unwrap();
    }

    /// Python `Secret.test_loose_permissions_are_not_trusted` / `test_env_wins_and_missing_is_empty` karşılığı + bozuk UTF-8,
    /// boş, dizin, değişiklik, geri gelme.
    #[test]
    fn file_secret_follows_changes_and_fails_closed() {
        let p = tmpfile("lifecycle");
        let fs = FrontSecret::file(&p);
        let _ = std::fs::remove_file(&p);
        assert_eq!(fs.current(), None, "yok = gizli yok");
        put(&p, b"ilk\n", 0o600);
        assert_eq!(
            fs.current().as_deref(),
            Some("ilk"),
            "sonradan oluşan okunur"
        );
        put(&p, b"\x1c ikinci \x1f\n", 0o600);
        assert_eq!(
            fs.current().as_deref(),
            Some("ikinci"),
            "değişince yeniden okunur, Python strip"
        );
        put(&p, b"ikinci\n", 0o644);
        assert_eq!(fs.current(), None, "gevşek izin = kapalı");
        put(&p, b"\xff\xfe\n", 0o600);
        assert_eq!(fs.current(), None, "UTF-8 değil = kapalı");
        assert!(matches!(read_secret_file(&p), SecretFile::Unusable(_)));
        put(&p, b" \t \n", 0o600);
        assert_eq!(fs.current(), None, "yalnız boşluk = yok");
        assert_eq!(read_secret_file(&p), SecretFile::Value(String::new()));
        put(&p, &vec![b'a'; 70 * 1024], 0o600);
        assert_eq!(fs.current(), None, "çok büyük = kapalı");
        put(&p, b"geri\n", 0o600);
        assert_eq!(fs.current().as_deref(), Some("geri"));
        std::fs::remove_file(&p).unwrap();
        assert_eq!(fs.current(), None, "silinen gizli anında geçersiz");
        let d = tmpfile("dir");
        std::fs::create_dir_all(&d).unwrap();
        std::fs::set_permissions(&d, std::fs::Permissions::from_mode(0o700)).unwrap();
        assert_eq!(FrontSecret::file(&d).current(), None, "dizin = kapalı");
        std::fs::remove_dir(&d).unwrap();
    }

    /// Python `Secret.test_trusted_front`: loopback dışı eş, boş gizli, yanlış ve eksik başlık.
    #[test]
    fn trusted_front_needs_secret_loopback_and_exact_header() {
        let lo: IpAddr = "127.0.0.1".parse().unwrap();
        let s = FrontSecret::fixed(Some("s3cret"));
        assert!(s.trusted(lo, Some(b"s3cret")));
        assert!(s.trusted("::1".parse().unwrap(), Some(b"s3cret")));
        assert!(s.trusted("::ffff:127.0.0.1".parse().unwrap(), Some(b"s3cret")));
        assert!(
            !s.trusted("10.0.0.5".parse().unwrap(), Some(b"s3cret")),
            "uzak eş"
        );
        assert!(
            !s.trusted("127.0.0.2".parse().unwrap(), Some(b"s3cret")),
            "Python kümesi dışında"
        );
        assert!(!s.trusted(lo, Some(b"s3cre")));
        assert!(
            !s.trusted(lo, Some(b" s3cret")),
            "başlık kırpılmaz (Python gibi)"
        );
        assert!(!s.trusted(lo, None));
        let empty = FrontSecret::fixed(Some(""));
        assert!(!empty.trusted(lo, Some(b"")), "boş gizli = kapalı");
        assert!(!FrontSecret::fixed(None).trusted(lo, Some(b"")));
        let env_like = FrontSecret::fixed(Some(" boşluklu "));
        assert!(
            env_like.trusted(lo, Some(" boşluklu ".as_bytes())),
            "ortam değeri kırpılmaz"
        );
    }
}
