//! Uygulama başına yol öneki mount tablosu (`mounts.json`): `/<id>/` altındaki istekler yerel derbent'in o uygulamaya ayrılmış loopback
//! portuna gider. Biçim: `[{"path":"/grafana/","upstream":"127.0.0.1:18101"}]`. Dosya 0600 değilse ya da yoksa tablo BOŞ (mount kapalı);
//! bozuk dosyada son geçerli tablo korunur. Sıcak yolda dosya okuma yok: `refresh` arka plan görevinden (en çok 2 sn'de bir) çağrılır.

use std::collections::HashMap;
use std::net::SocketAddr;
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, RwLock};

/// Panelin (Python çekirdeği + enterprise eklentileri) kendi üst düzey yol segmentleri: mount kimliği bunlardan biri OLAMAZ.
/// Kaynak: py/claudeops/commands/web.py `do_GET`/`do_POST` dalları (`/api/`, `/ws*`, `/assets/`, `/q/`, `/readfile/`, `/v1/`, `/desktop/`,
/// `/favicon.svg`), extensions.py çekirdek yüzeyi, claudeops-enterprise `register_route` önekleri (`/readlist/`, `/missing/`).
pub const RESERVED: &[&str] = &[
    "api",
    "ws",
    "assets",
    "q",
    "readfile",
    "v1",
    "desktop",
    "favicon.svg",
    "readlist",
    "missing",
];

/// En çok mount sayısı ve dosya boyutu (yanlışlıkla büyük dosyayı belleğe almamak için).
const MAX_MOUNTS: usize = 256;
const MAX_FILE: u64 = 1 << 20;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Mount {
    /// Kimlik (`/grafana/` -> `grafana`).
    pub id: String,
    pub upstream: SocketAddr,
    /// Kök-göreli istekler (`/api/x`, mount önekini taşımayan) Referer'ı bu mount altındaysa bu mount'a gider (uygulama köke göre yol yazıyorsa).
    pub rootrel: bool,
}

#[derive(Default, Debug, PartialEq, Eq)]
pub struct MountTable {
    mounts: Vec<Mount>,
}

/// Yol eşleşmesi: `Under` = `/<id>/...` (aktar), `Bare` = tam `/<id>` (308 ile `/<id>/`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Hit {
    Under(SocketAddr),
    Bare(SocketAddr),
}

pub fn valid_id(id: &str) -> bool {
    let b = id.as_bytes();
    !b.is_empty()
        && b.len() <= 63
        && (b[0].is_ascii_lowercase() || b[0].is_ascii_digit())
        && b.iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'-' || *c == b'_')
}

/// `mounts.json` içeriğini doğrular. Hata = tüm dosya reddedilir (kısmi yükleme yok).
pub fn parse(data: &[u8]) -> Result<MountTable, String> {
    let v: serde_json::Value = serde_json::from_slice(data).map_err(|e| format!("json: {e}"))?;
    let arr = v.as_array().ok_or("kök bir dizi olmalı")?;
    if arr.len() > MAX_MOUNTS {
        return Err(format!("en çok {MAX_MOUNTS} mount"));
    }
    let mut mounts: Vec<Mount> = Vec::with_capacity(arr.len());
    for (i, it) in arr.iter().enumerate() {
        let o = it.as_object().ok_or(format!("#{i}: nesne olmalı"))?;
        if let Some(k) = o
            .keys()
            .find(|k| *k != "path" && *k != "upstream" && *k != "rootrel")
        {
            return Err(format!("#{i}: bilinmeyen anahtar {k:?}"));
        }
        let path = o
            .get("path")
            .and_then(|p| p.as_str())
            .ok_or(format!("#{i}: path (string) gerekli"))?;
        let up = o
            .get("upstream")
            .and_then(|p| p.as_str())
            .ok_or(format!("#{i}: upstream (string) gerekli"))?;
        let id = path
            .strip_prefix('/')
            .and_then(|p| p.strip_suffix('/'))
            .ok_or(format!("#{i}: path '/' ile başlayıp bitmeli: {path:?}"))?;
        if !valid_id(id) {
            return Err(format!(
                "#{i}: path tek segment kimlik olmalı ([a-z0-9][a-z0-9_-]*, en çok 63): {path:?}"
            ));
        }
        if RESERVED.contains(&id) {
            return Err(format!(
                "#{i}: path panelin kendi yoluyla çakışıyor: {path:?}"
            ));
        }
        if mounts.iter().any(|m| m.id == id) {
            return Err(format!("#{i}: path iki kez tanımlı: {path:?}"));
        }
        let upstream: SocketAddr = up
            .parse()
            .map_err(|_| format!("#{i}: upstream ip:port olmalı: {up:?}"))?;
        if !upstream.ip().is_loopback() || upstream.port() == 0 {
            return Err(format!(
                "#{i}: upstream yalnız loopback ve port != 0 olabilir: {up:?}"
            ));
        }
        let rootrel = match o.get("rootrel") {
            None => false,
            Some(v) => v
                .as_bool()
                .ok_or(format!("#{i}: rootrel true/false olmalı"))?,
        };
        mounts.push(Mount {
            id: id.to_string(),
            upstream,
            rootrel,
        });
    }
    Ok(MountTable { mounts })
}

impl MountTable {
    pub fn is_empty(&self) -> bool {
        self.mounts.is_empty()
    }

    pub fn mounts(&self) -> &[Mount] {
        &self.mounts
    }

    /// Ham (yüzde-çözülmemiş) URL yolu için eşleşme. Büyük/küçük harf duyarlı; `//grafana/` gibi biçimler eşleşmez (Python'a gider).
    pub fn find(&self, path: &str) -> Option<Hit> {
        let rest = path.strip_prefix('/')?;
        let (id, bare) = match rest.find('/') {
            Some(i) => (&rest[..i], false),
            None => (rest, true),
        };
        let m = self.mounts.iter().find(|m| m.id == id)?;
        Some(if bare {
            Hit::Bare(m.upstream)
        } else {
            Hit::Under(m.upstream)
        })
    }
}

impl MountTable {
    /// `rootrel` mount'ları için: Referer yolu `/<id>/...` ya da `/<id>` ise o mount (kimlik, upstream).
    pub fn find_by_referer_path(&self, referer_path: &str) -> Option<(&str, SocketAddr)> {
        let rest = referer_path.strip_prefix('/')?;
        let id = rest.split(['/', '?', '#']).next()?;
        let m = self.mounts.iter().find(|m| m.rootrel && m.id == id)?;
        Some((m.id.as_str(), m.upstream))
    }
}

/// `Referer` değerinin yolu; yalnız `Host` ile aynı yetkili (host[:port]) ise (aynı köken), değilse None.
pub fn same_origin_referer_path<'a>(referer: &'a str, host: &str) -> Option<&'a str> {
    let rest = referer
        .strip_prefix("https://")
        .or_else(|| referer.strip_prefix("http://"))?;
    let (auth, path) = match rest.find(['/', '?', '#']) {
        Some(i) => (&rest[..i], &rest[i..]),
        None => (rest, "/"),
    };
    if auth.eq_ignore_ascii_case(host) && !host.is_empty() {
        Some(path)
    } else {
        None
    }
}

/// Dosya kimliği: içerik ya da izin değişince farklılaşır (mtime ns + ctime ns + boyut + inode + kip).
type Stamp = (u64, u64, i64, i64, i64, i64, u64, u32);

fn stamp(m: &std::fs::Metadata) -> Stamp {
    (
        m.dev(),
        m.ino(),
        m.mtime(),
        m.mtime_nsec(),
        m.ctime(),
        m.ctime_nsec(),
        m.len(),
        m.mode(),
    )
}

/// Canlı mount tablosu. `lookup` tablo boşken tek atomik okuma + tek dal; doluyken kısa süreli okuma kilidi.
pub struct Mounts {
    file: PathBuf,
    active: AtomicBool,
    table: RwLock<Arc<MountTable>>,
    last: Mutex<Option<Stamp>>,
    /// Yol kökü öğrenme: HTML belge yanıtı veren rootrel mount'un ilk yol parçası -> mount kimliği (`rootrel_learned.json`, 0600).
    learned: Mutex<HashMap<String, String>>,
    learned_file: PathBuf,
    /// Öğrenme tablosunun SQLite'ı (`claudeops.db`); None ya da hata durumunda JSON dosyası.
    learned_db: Option<PathBuf>,
}

impl Mounts {
    /// Dosyayı OKUMAZ; ilk yükleme için `refresh` çağrılır.
    pub fn new(file: PathBuf) -> Arc<Mounts> {
        Self::with_db(file, None)
    }

    /// Öğrenme tablosu `db`de (`rootrel_learned`); tablo boşsa eski `rootrel_learned.json` bir kez içe alınır
    /// (dosya `.migrated` adını alır). DB açılamazsa JSON'a düşer.
    pub fn with_db(file: PathBuf, db: Option<PathBuf>) -> Arc<Mounts> {
        let learned_file = file
            .parent()
            .map(|p| p.join("rootrel_learned.json"))
            .unwrap_or_else(|| PathBuf::from("rootrel_learned.json"));
        let mut learned_db = db;
        let learned = match learned_db.as_deref().map(cops_local::learned::load) {
            Some(Ok(mut m)) => {
                if m.is_empty() {
                    let old = load_learned(&learned_file);
                    if !old.is_empty() {
                        let db = learned_db.as_deref().unwrap();
                        if old
                            .iter()
                            .all(|(k, v)| cops_local::learned::upsert(db, k, v).is_ok())
                        {
                            let _ = std::fs::rename(
                                &learned_file,
                                learned_file.with_extension("json.migrated"),
                            );
                            eprintln!("copsd: rootrel_learned.json -> SQLite ({} satır)", old.len());
                        }
                        m = old;
                    }
                }
                m.into_iter()
                    .filter(|(k, v)| learnable(k) && valid_id(v))
                    .collect()
            }
            Some(Err(e)) => {
                eprintln!("copsd: rootrel_learned SQLite açılamadı ({e}); JSON'a düşüldü");
                learned_db = None;
                load_learned(&learned_file)
            }
            None => load_learned(&learned_file),
        };
        Arc::new(Mounts {
            file,
            active: AtomicBool::new(false),
            table: RwLock::new(Arc::new(MountTable::default())),
            last: Mutex::new(None),
            learned: Mutex::new(learned),
            learned_file,
            learned_db,
        })
    }

    /// Öğrenilmiş yol parçası -> (mount kimliği, upstream); mount artık yok ya da rootrel değilse None (satır yok sayılır).
    pub fn learned(&self, seg: &str) -> Option<(String, SocketAddr)> {
        let id = self
            .learned
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(seg)?
            .clone();
        let addr = self.rootrel_upstream(&id)?;
        Some((id, addr))
    }

    /// `id` mount'unun HTML belgesinden `seg` parçasını öğrenir (panel kökleri/geçersiz parça reddedilir). Değişince dosyaya yazar.
    pub fn learn(&self, seg: &str, id: &str) {
        if !learnable(seg) || seg == id {
            return;
        }
        let mut m = self.learned.lock().unwrap_or_else(|e| e.into_inner());
        match m.get(seg) {
            Some(cur) if cur == id => return,
            Some(cur) => {
                eprintln!("copsd: rootrel öğrenme: /{seg} {cur} -> {id} (son öğretilen kazanır)")
            }
            None => {}
        }
        m.insert(seg.to_string(), id.to_string());
        if let Some(db) = &self.learned_db {
            if cops_local::learned::upsert(db, seg, id).is_ok() {
                return;
            }
            eprintln!("copsd: rootrel_learned SQLite yazımı başarısız; JSON'a yazıldı");
        }
        save_learned(&self.learned_file, &m);
    }

    pub fn file(&self) -> &std::path::Path {
        &self.file
    }

    #[inline]
    pub fn lookup(&self, path: &str) -> Option<Hit> {
        if !self.active.load(Ordering::Acquire) {
            return None;
        }
        self.snapshot().find(path)
    }

    /// Kök-göreli istek (mount'suz yol) için Referer'a göre `rootrel` mount: `(kimlik, upstream)`.
    pub fn lookup_by_referer(&self, referer: &str, host: &str) -> Option<(String, SocketAddr)> {
        if !self.active.load(Ordering::Acquire) {
            return None;
        }
        let path = same_origin_referer_path(referer, host)?;
        let t = self.snapshot();
        t.find_by_referer_path(path)
            .map(|(i, a)| (i.to_string(), a))
    }

    /// `rootrel` mount kimliği -> upstream (çerezle yönlendirme ve çerez koyma için). Bilinmeyen / rootrel olmayan kimlik None.
    pub fn rootrel_upstream(&self, id: &str) -> Option<SocketAddr> {
        if !self.active.load(Ordering::Acquire) {
            return None;
        }
        self.snapshot()
            .mounts
            .iter()
            .find(|m| m.rootrel && m.id == id)
            .map(|m| m.upstream)
    }

    pub fn snapshot(&self) -> Arc<MountTable> {
        self.table.read().unwrap_or_else(|e| e.into_inner()).clone()
    }

    fn set(&self, t: MountTable) {
        let on = !t.is_empty();
        *self.table.write().unwrap_or_else(|e| e.into_inner()) = Arc::new(t);
        self.active.store(on, Ordering::Release);
    }

    fn describe(t: &MountTable) -> String {
        if t.is_empty() {
            return "tablo boş".into();
        }
        t.mounts
            .iter()
            .map(|m| format!("/{}/ -> {}", m.id, m.upstream))
            .collect::<Vec<_>>()
            .join(", ")
    }

    /// Dosyaya bakar; değişmişse yeniden yükler. Değişiklik olduysa günlüğe yazılacak satırı döner (değişiklik yoksa None).
    pub fn refresh(&self) -> Option<String> {
        let mut last = self.last.lock().unwrap_or_else(|e| e.into_inner());
        let f = self.file.display();
        let meta = match std::fs::metadata(&self.file) {
            Ok(m) => m,
            Err(_) => {
                if last.is_none() && !self.active.load(Ordering::Acquire) {
                    return None;
                }
                *last = None;
                self.set(MountTable::default());
                return Some(format!("mount kapalı: {f} yok"));
            }
        };
        let st = stamp(&meta);
        if *last == Some(st) {
            return None;
        }
        *last = Some(st);
        if !meta.is_file() || meta.permissions().mode() & 0o077 != 0 {
            self.set(MountTable::default());
            return Some(format!(
                "mount kapalı: {f} düz dosya değil ya da izinleri 0600 değil"
            ));
        }
        if meta.len() > MAX_FILE {
            return Some(format!(
                "mount dosyası çok büyük ({} bayt), eski yapılandırma korunuyor: {}",
                meta.len(),
                Self::describe(&self.snapshot())
            ));
        }
        let parsed = std::fs::read(&self.file)
            .map_err(|e| format!("okunamadı: {e}"))
            .and_then(|d| parse(&d));
        match parsed {
            Ok(t) => {
                let msg = format!("mount yüklendi ({f}): {}", Self::describe(&t));
                self.set(t);
                Some(msg)
            }
            Err(e) => Some(format!(
                "mount dosyası bozuk ({f}: {e}), eski yapılandırma korunuyor: {}",
                Self::describe(&self.snapshot())
            )),
        }
    }

    /// Arka plan izleyici: `every` aralıkla `refresh` (stat) çağırır, değişiklikleri stderr'e yazar. Tokio çalışma zamanı içinde çağrılmalı.
    pub fn spawn_watch(
        self: &Arc<Self>,
        every: std::time::Duration,
    ) -> tokio::task::JoinHandle<()> {
        let me = self.clone();
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(every).await;
                let m = me.clone();
                if let Ok(Some(line)) = tokio::task::spawn_blocking(move || m.refresh()).await {
                    eprintln!("copsd: {line}");
                }
            }
        })
    }
}

/// Öğrenilebilir yol parçası: `[A-Za-z0-9_-]{1,63}` ve panelin kendi kökü değil (`api`, `v1`, `q`, `desktop`, `assets` ...).
pub fn learnable(seg: &str) -> bool {
    !seg.is_empty()
        && seg.len() <= 63
        && seg
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
        && !RESERVED.contains(&seg.to_ascii_lowercase().as_str())
}

fn load_learned(f: &std::path::Path) -> HashMap<String, String> {
    let Ok(md) = std::fs::metadata(f) else {
        return HashMap::new();
    };
    if md.permissions().mode() & 0o077 != 0 || md.len() > MAX_FILE {
        return HashMap::new();
    }
    std::fs::read(f)
        .ok()
        .and_then(|b| serde_json::from_slice::<HashMap<String, String>>(&b).ok())
        .map(|m| {
            m.into_iter()
                .filter(|(k, v)| learnable(k) && valid_id(v))
                .collect()
        })
        .unwrap_or_default()
}

/// Atomik yazım (geçici dosya 0600 + rename); hata sessiz (öğrenme bellekte sürer).
fn save_learned(f: &std::path::Path, m: &HashMap<String, String>) {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    let tmp = f.with_extension("json.tmp");
    let Ok(body) = serde_json::to_vec(m) else {
        return;
    };
    let ok = std::fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .open(&tmp)
        .and_then(|mut h| h.write_all(&body))
        .is_ok();
    if ok {
        let _ = std::fs::rename(&tmp, f);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn up(p: u16) -> SocketAddr {
        SocketAddr::from(([127, 0, 0, 1], p))
    }

    #[test]
    fn parse_valid_and_find() {
        let t = parse(br#"[{"path":"/grafana/","upstream":"127.0.0.1:18101"},{"path":"/n8n-2/","upstream":"[::1]:18102"}]"#).unwrap();
        assert_eq!(t.mounts().len(), 2);
        assert_eq!(t.find("/grafana/"), Some(Hit::Under(up(18101))));
        assert_eq!(t.find("/grafana/api/live/ws"), Some(Hit::Under(up(18101))));
        assert_eq!(t.find("/grafana"), Some(Hit::Bare(up(18101))));
        assert!(matches!(t.find("/n8n-2/x"), Some(Hit::Under(a)) if a.port() == 18102));
        for p in [
            "/",
            "",
            "/grafanax/",
            "/Grafana/",
            "//grafana/",
            "/api/status",
            "grafana/",
            "/gra",
        ] {
            assert_eq!(t.find(p), None, "{p}");
        }
        assert!(parse(b"[]").unwrap().is_empty());
    }

    #[test]
    fn rootrel_by_referer() {
        let t = parse(br#"[{"path":"/gw/","upstream":"127.0.0.1:18104","rootrel":true},{"path":"/grafana/","upstream":"127.0.0.1:18102"}]"#).unwrap();
        assert_eq!(t.find_by_referer_path("/gw/x?y=1"), Some(("gw", up(18104))));
        assert_eq!(t.find_by_referer_path("/gw"), Some(("gw", up(18104))));
        assert_eq!(t.find_by_referer_path("/grafana/d/1"), None); // rootrel degil
        assert_eq!(t.find_by_referer_path("/gwx/"), None);
        assert_eq!(t.find_by_referer_path("/"), None);
        assert!(parse(br#"[{"path":"/g/","upstream":"127.0.0.1:1","rootrel":"x"}]"#).is_err());
        assert_eq!(
            same_origin_referer_path("https://t.example/gw/a?b", "t.example"),
            Some("/gw/a?b")
        );
        assert_eq!(
            same_origin_referer_path("https://t.example", "t.example"),
            Some("/")
        );
        assert_eq!(
            same_origin_referer_path("https://evil.example/gw/", "t.example"),
            None
        );
        assert_eq!(
            same_origin_referer_path("https://t.example.evil/gw/", "t.example"),
            None
        );
        assert_eq!(
            same_origin_referer_path("ftp://t.example/gw/", "t.example"),
            None
        );
    }

    #[test]
    fn parse_rejects_bad_paths_collisions_and_upstreams() {
        let bad = [
            r#"{}"#,
            r#"[1]"#,
            r#"[{"path":"/grafana/"}]"#,
            r#"[{"path":"/grafana/","upstream":"127.0.0.1:1","x":1}]"#,
            r#"[{"path":"grafana/","upstream":"127.0.0.1:1"}]"#,
            r#"[{"path":"/grafana","upstream":"127.0.0.1:1"}]"#,
            r#"[{"path":"/","upstream":"127.0.0.1:1"}]"#,
            r#"[{"path":"//","upstream":"127.0.0.1:1"}]"#,
            r#"[{"path":"/a/b/","upstream":"127.0.0.1:1"}]"#,
            r#"[{"path":"/Grafana/","upstream":"127.0.0.1:1"}]"#,
            r#"[{"path":"/-x/","upstream":"127.0.0.1:1"}]"#,
            r#"[{"path":"/g%20/","upstream":"127.0.0.1:1"}]"#,
            r#"[{"path":"/g/","upstream":"127.0.0.1:1"},{"path":"/g/","upstream":"127.0.0.1:2"}]"#,
            r#"[{"path":"/g/","upstream":"10.0.0.1:80"}]"#,
            r#"[{"path":"/g/","upstream":"0.0.0.0:80"}]"#,
            r#"[{"path":"/g/","upstream":"127.0.0.1:0"}]"#,
            r#"[{"path":"/g/","upstream":"localhost:80"}]"#,
            r#"[{"path":"/g/","upstream":18101}]"#,
            "nope",
        ];
        for b in bad {
            assert!(parse(b.as_bytes()).is_err(), "kabul edilmemeliydi: {b}");
        }
        let long = format!(
            r#"[{{"path":"/{}/","upstream":"127.0.0.1:1"}}]"#,
            "a".repeat(64)
        );
        assert!(parse(long.as_bytes()).is_err());
    }

    #[test]
    fn every_reserved_panel_segment_is_rejected() {
        // Sabit liste değişirse bu test de bilinçli güncellenmeli (panel yolu mount ile gölgelenemez).
        assert_eq!(
            RESERVED,
            &[
                "api",
                "ws",
                "assets",
                "q",
                "readfile",
                "v1",
                "desktop",
                "favicon.svg",
                "readlist",
                "missing"
            ]
        );
        for id in RESERVED {
            let j = format!(r#"[{{"path":"/{id}/","upstream":"127.0.0.1:18101"}}]"#);
            assert!(parse(j.as_bytes()).is_err(), "{id}");
        }
    }

    fn write(p: &std::path::Path, s: &str, mode: u32) {
        let tmp = p.with_extension("tmp");
        std::fs::write(&tmp, s).unwrap();
        std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(mode)).unwrap();
        std::fs::rename(&tmp, p).unwrap();
    }

    #[test]
    fn refresh_reloads_on_change_keeps_old_on_broken_and_closes_on_perm_or_missing() {
        let d = tempfile::tempdir().unwrap();
        let f = d.path().join("mounts.json");
        let m = Mounts::new(f.clone());
        assert_eq!(m.refresh(), None, "dosya yok + daha önce de yoktu: sessiz");
        assert_eq!(m.lookup("/grafana/"), None);

        write(
            &f,
            r#"[{"path":"/grafana/","upstream":"127.0.0.1:18101"}]"#,
            0o600,
        );
        assert!(m
            .refresh()
            .unwrap()
            .contains("/grafana/ -> 127.0.0.1:18101"));
        assert_eq!(m.lookup("/grafana/x"), Some(Hit::Under(up(18101))));
        assert_eq!(m.refresh(), None, "değişiklik yok: yeniden okuma yok");

        write(
            &f,
            r#"[{"path":"/grafana/","upstream":"127.0.0.1:18105"},{"path":"/n8n/","upstream":"127.0.0.1:18106"}]"#,
            0o600,
        );
        assert!(m.refresh().is_some());
        assert_eq!(m.lookup("/grafana/x"), Some(Hit::Under(up(18105))));
        assert_eq!(m.lookup("/n8n/"), Some(Hit::Under(up(18106))));

        write(&f, r#"[{"path":"/api/","upstream":"127.0.0.1:1"}]"#, 0o600);
        assert!(m.refresh().unwrap().contains("bozuk"));
        assert_eq!(
            m.lookup("/grafana/x"),
            Some(Hit::Under(up(18105))),
            "bozuk dosyada eski tablo korunur"
        );
        assert_eq!(m.lookup("/api/x"), None);
        write(&f, "{bozuk", 0o600);
        assert!(m.refresh().unwrap().contains("bozuk"));
        assert_eq!(m.lookup("/n8n/"), Some(Hit::Under(up(18106))));

        write(
            &f,
            r#"[{"path":"/grafana/","upstream":"127.0.0.1:18101"}]"#,
            0o644,
        );
        assert!(m.refresh().unwrap().contains("0600"));
        assert_eq!(m.lookup("/grafana/x"), None, "0600 değil: kapalı");
        std::fs::set_permissions(&f, std::fs::Permissions::from_mode(0o600)).unwrap();
        assert!(m.refresh().is_some(), "chmod (ctime) da değişiklik sayılır");
        assert_eq!(m.lookup("/grafana/x"), Some(Hit::Under(up(18101))));

        write(&f, "[]", 0o600);
        assert!(m.refresh().is_some());
        assert_eq!(m.lookup("/grafana/x"), None, "boş tablo = kapalı");

        write(
            &f,
            r#"[{"path":"/grafana/","upstream":"127.0.0.1:18101"}]"#,
            0o600,
        );
        m.refresh();
        std::fs::remove_file(&f).unwrap();
        assert!(m.refresh().unwrap().contains("yok"));
        assert_eq!(m.lookup("/grafana/x"), None, "dosya silindi: kapalı");
    }

    #[tokio::test]
    async fn watcher_picks_up_changes() {
        let d = tempfile::tempdir().unwrap();
        let f = d.path().join("mounts.json");
        let m = Mounts::new(f.clone());
        let h = m.spawn_watch(std::time::Duration::from_millis(20));
        write(
            &f,
            r#"[{"path":"/grafana/","upstream":"127.0.0.1:18101"}]"#,
            0o600,
        );
        let mut ok = false;
        for _ in 0..100 {
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
            if m.lookup("/grafana/").is_some() {
                ok = true;
                break;
            }
        }
        h.abort();
        assert!(ok, "izleyici yeni dosyayı yüklemedi");
    }
}
