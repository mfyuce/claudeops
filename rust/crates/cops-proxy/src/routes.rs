//! Çoklu [`RouteHook`] kaydı: yöntem + yol (tam ya da önek) tablosu. Strangler izleri yerel uçlarını buraya tek satırla ekler
//! (`copsd::routes::register`). Tek yuvalı eski kanca (`Proxy::with_routes`, enterprise `/api/auth/*`) aynen durur ve tablodan
//! SONRA sorulur.
//!
//! Eşleşme: tam yol önekten, uzun önek kısadan önce. Aday kancanın [`RouteHook::route`]'u `None` dönerse sıradaki adaya, o da
//! yoksa eski kancaya / Python'a geçilir. Yol HAM karşılaştırılır (yüzde çözme yok).

use crate::gate::RouteHook;
use std::sync::Arc;

/// Kaydın kimlik kuralı.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Auth {
    /// Vekil denetler (yalnız GET): [`crate::gate::LocalAuth`] takılıysa ona sorulur, yoksa `web.token`.
    Panel,
    /// Kimlik ve yetki tamamen kancanın işi.
    Own,
}

#[derive(Clone)]
pub(crate) struct Entry {
    pub(crate) method: &'static str,
    /// Kayıttaki yazım (`/api/files/*` ya da `/api/files/list`); sayaç anahtarı da budur.
    pub(crate) pattern: &'static str,
    pub(crate) auth: Auth,
    pub(crate) hook: Arc<dyn RouteHook>,
}

impl Entry {
    fn matches(&self, method: &str, path: &str) -> bool {
        if self.method != method {
            return false;
        }
        match self.pattern.strip_suffix('*') {
            Some(prefix) => path.starts_with(prefix),
            None => path == self.pattern,
        }
    }

    /// Büyük olan önce sorulur: tam yol > uzun önek > kısa önek.
    fn rank(&self) -> (bool, usize) {
        (!self.pattern.ends_with('*'), self.pattern.len())
    }
}

/// Yöntem + yol -> kanca tablosu. Hatalı kayıt (yinelenen, bozuk desen) programlama hatasıdır ve açılışta PANİKLER.
#[derive(Default, Clone)]
pub struct RouteTable {
    entries: Vec<Entry>,
}

const OWN_METHODS: [&str; 6] = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"];

impl RouteTable {
    pub fn new() -> RouteTable {
        RouteTable::default()
    }

    /// `GET <desen>`: kimliği vekil denetler (`web.token` ya da takılıysa `LocalAuth`), kanca yalnız yetkili isteği görür.
    /// Desen tam yol (`/api/files/list`) ya da önek (`/api/files/*`).
    ///
    /// `LocalAuth` "izin" derse kanca KİMİN sorduğunu bilmez: kullanıcıya göre süzülmesi gereken veri (çok kullanıcı kipi) için
    /// [`RouteTable::own_auth`] kullanılır ya da `LocalAuth` o yolu yalnız yöneticiye açar.
    pub fn get(&mut self, pattern: &'static str, hook: Arc<dyn RouteHook>) -> &mut Self {
        self.add("GET", pattern, Auth::Panel, hook)
    }

    /// Kimliği kancanın KENDİSİNİN denetlediği kayıt (yazma yöntemleri yalnız buradan: yetki kaynağı gövdede olabilir).
    pub fn own_auth(
        &mut self,
        method: &'static str,
        pattern: &'static str,
        hook: Arc<dyn RouteHook>,
    ) -> &mut Self {
        self.add(method, pattern, Auth::Own, hook)
    }

    fn add(
        &mut self,
        method: &'static str,
        pattern: &'static str,
        auth: Auth,
        hook: Arc<dyn RouteHook>,
    ) -> &mut Self {
        assert!(
            OWN_METHODS.contains(&method),
            "rota: bilinmeyen yöntem {method:?} ({pattern})"
        );
        let body = pattern.strip_suffix('*').unwrap_or(pattern);
        assert!(
            body.len() > 1
                && body.starts_with('/')
                && !body.contains(['*', '?', '#'])
                && (body == pattern || body.ends_with('/')),
            "rota: geçersiz desen {pattern:?} (tam yol ya da `/.../*`)"
        );
        let lower = body.trim_start_matches('/').to_ascii_lowercase();
        assert!(
            !lower.starts_with("api/_internal") && !lower.starts_with("api/front/"),
            "rota: ayrılmış yol {pattern:?}"
        );
        assert!(
            !self
                .entries
                .iter()
                .any(|e| e.method == method && e.pattern == pattern),
            "rota: yinelenen kayıt {method} {pattern}"
        );
        let entry = Entry {
            method,
            pattern,
            auth,
            hook,
        };
        let at = self
            .entries
            .iter()
            .position(|e| e.rank() < entry.rank())
            .unwrap_or(self.entries.len());
        self.entries.insert(at, entry);
        self
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// `(yöntem, desen)` listesi, sorulma sırasıyla.
    pub fn routes(&self) -> impl Iterator<Item = (&'static str, &'static str)> + '_ {
        self.entries.iter().map(|e| (e.method, e.pattern))
    }

    pub(crate) fn candidates<'a>(
        &'a self,
        method: &'a str,
        path: &'a str,
    ) -> impl Iterator<Item = &'a Entry> + 'a {
        self.entries.iter().filter(move |e| e.matches(method, path))
    }
}
