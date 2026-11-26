//! `GET /api/front/stats`: uç başına kaç istek Rust'ta cevaplandı (`local`), kaçı Python'a aktarıldı (`fallback`; içinde
//! `forced` = `force_proxy` yüzünden, `upstream_error` = Python'a ulaşılamadı). Mount istekleri sayılmaz.
//!
//! Anahtarlar istemci denetiminde olduğu için sınırlıdır: sır taşıyabilen yollar (`/q/`, `/readfile/`) ve API dışı yollar ilk
//! parçaya indirgenir, kimlik benzeri parçalar `*` olur. Yeni anahtarı yalnız Rust'ın cevapladığı (yerel) ya da panel kimliği
//! taşıyan (web.token / ön kapı gizlisi) bir istek açar, 401/403/404 yanıtı hiç açmaz, en çok [`MAX_KEYS`] tanedir; gerisi `other`
//! sayacına gider. Böylece kimliksiz 200 yanıtları tabloyu dolduramaz. Sınır: yalnız eklenti çerezi taşıyan (çok kullanıcı) aktarım
//! istekleri, anahtarı henüz açılmamışsa `other`da kalır.
//!
//! `/api/front/stats` `force_proxy`den ÖNCE cevaplanır (`*` dahil): Python'da karşılığı yoktur ve geri almanın etkisi buradan
//! doğrulanır.

use std::collections::BTreeMap;
use std::sync::Mutex;

pub const MAX_KEYS: usize = 512;
const MAX_SEGMENTS: usize = 4;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Counts {
    pub local: u64,
    pub fallback: u64,
    pub forced: u64,
    pub upstream_error: u64,
}

impl Counts {
    fn add(&mut self, o: Outcome) {
        match o {
            Outcome::Local => self.local += 1,
            Outcome::Python {
                forced,
                upstream_error,
            } => {
                self.fallback += 1;
                self.forced += u64::from(forced);
                self.upstream_error += u64::from(upstream_error);
            }
        }
    }

    fn json(&self) -> serde_json::Value {
        serde_json::json!({"local": self.local, "fallback": self.fallback, "forced": self.forced,
            "upstream_error": self.upstream_error})
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Local,
    Python { forced: bool, upstream_error: bool },
}

#[derive(Default)]
struct Inner {
    keys: BTreeMap<(&'static str, String), Counts>,
    other: Counts,
    totals: Counts,
}

pub struct Stats {
    started_at: f64,
    inner: Mutex<Inner>,
}

fn method_name(m: &str) -> &'static str {
    ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
        .into_iter()
        .find(|k| *k == m)
        .unwrap_or("OTHER")
}

/// Yolu sayaç anahtarına indirger.
pub fn normalize(path: &str) -> String {
    let word = |s: &str| {
        (1..=32).contains(&s.len())
            && s.starts_with(|c: char| c.is_ascii_lowercase() || c == '_')
            && s.bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b"_-.".contains(&b))
    };
    let mut parts = path.strip_prefix('/').unwrap_or(path).split('/');
    let first = parts.next().unwrap_or("");
    if first.is_empty() {
        return if path == "/" { "/".into() } else { "/*".into() };
    }
    if !word(first) {
        return "/*".into();
    }
    let rest: Vec<&str> = parts.collect();
    if !matches!(first, "api" | "v1" | "ws" | "desktop") {
        return if rest.is_empty() {
            format!("/{first}")
        } else {
            format!("/{first}/*")
        };
    }
    let mut out = format!("/{first}");
    // `/api/ui/ext/<id>/<dosya>`: eklenti kimliği ve dosya yolu sınırsız.
    let max = if path.starts_with("/api/ui/ext/") {
        2
    } else {
        MAX_SEGMENTS - 1
    };
    for (i, s) in rest.iter().enumerate() {
        if i >= max {
            out.push_str("/*");
            break;
        }
        out.push('/');
        out.push_str(if s.is_empty() || word(s) { s } else { "*" });
    }
    out
}

impl Default for Stats {
    fn default() -> Self {
        Stats {
            started_at: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs_f64())
                .unwrap_or(0.0),
            inner: Mutex::new(Inner::default()),
        }
    }
}

impl Stats {
    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(|p| p.into_inner())
    }

    /// Kayıtlı rota baştan sıfırla listelensin.
    pub fn seed(&self, method: &str, pattern: &str) {
        self.lock()
            .keys
            .entry((method_name(method), pattern.to_string()))
            .or_default();
    }

    /// `key`: tablo deseni ya da [`normalize`] çıktısı. `authed`: istek panel kimliği taşıyordu (yerel yanıtta gereksiz).
    pub fn record(&self, method: &str, key: String, status: u16, o: Outcome, authed: bool) {
        let mut g = self.lock();
        g.totals.add(o);
        let k = (method_name(method), key);
        let room = g.keys.len() < MAX_KEYS
            && !matches!(status, 401 | 403 | 404)
            && (authed || o == Outcome::Local);
        if let Some(c) = g.keys.get_mut(&k) {
            c.add(o);
        } else if room {
            g.keys.entry(k).or_default().add(o);
        } else {
            g.other.add(o);
        }
    }

    pub fn snapshot(
        &self,
        routes: Vec<(&'static str, &'static str)>,
        force_proxy: Vec<String>,
    ) -> serde_json::Value {
        let g = self.lock();
        let endpoints: Vec<serde_json::Value> = g
            .keys
            .iter()
            .map(|((m, p), c)| {
                let mut v = c.json();
                v["method"] = (*m).into();
                v["path"] = p.as_str().into();
                v
            })
            .collect();
        let routes: Vec<serde_json::Value> = routes
            .into_iter()
            .map(|(m, p)| serde_json::json!({"method": m, "pattern": p}))
            .collect();
        serde_json::json!({"ok": true, "started_at": self.started_at, "totals": g.totals.json(),
            "other": g.other.json(), "endpoints": endpoints, "routes": routes, "force_proxy": force_proxy})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keys_hide_secrets_and_ids() {
        for (path, key) in [
            ("/", "/"),
            ("/api/status", "/api/status"),
            ("/api/term/output", "/api/term/output"),
            ("/api/_x/a", "/api/_x/a"),
            ("/api/users/AbC123", "/api/users/*"),
            ("/api/a/b/c/d/e", "/api/a/b/c/*"),
            ("/api/ui/ext/foo/js/app.js", "/api/ui/ext/*"),
            ("/readfile/deadbeefSECRET/x.md", "/readfile/*"),
            ("/q/20261126_ab", "/q/*"),
            ("/assets/index-Ab12.js", "/assets/*"),
            ("/favicon.svg", "/favicon.svg"),
            ("//evil/x", "/*"),
            ("/SECRET", "/*"),
            ("/ws/term", "/ws/term"),
        ] {
            assert_eq!(normalize(path), key, "{path}");
        }
    }

    #[test]
    fn junk_paths_cannot_grow_the_table() {
        let s = Stats::default();
        let py = Outcome::Python {
            forced: false,
            upstream_error: false,
        };
        for i in 0..50 {
            s.record("GET", format!("/api/junk{i}"), 404, py, true);
        }
        for i in 0..MAX_KEYS + 10 {
            s.record("GET", format!("/api/ok{i}"), 200, py, true);
        }
        // Açılmış anahtar sonradan 404 alsa da kendi sayacına yazar.
        s.record("GET", "/api/ok0".into(), 404, py, true);
        let v = s.snapshot(vec![], vec![]);
        assert_eq!(v["endpoints"].as_array().unwrap().len(), MAX_KEYS);
        assert_eq!(v["other"]["fallback"], 60);
        assert_eq!(v["totals"]["fallback"], 50 + MAX_KEYS as u64 + 10 + 1);
        let first = &v["endpoints"][0];
        assert_eq!(
            (first["path"].as_str(), first["fallback"].as_u64()),
            (Some("/api/ok0"), Some(2))
        );
    }

    #[test]
    fn unauthenticated_forwards_cannot_open_keys() {
        let s = Stats::default();
        let py = Outcome::Python {
            forced: false,
            upstream_error: false,
        };
        for i in 0..MAX_KEYS + 10 {
            s.record("GET", format!("/api/anon{i}"), 200, py, false);
        }
        assert!(s.snapshot(vec![], vec![])["endpoints"]
            .as_array()
            .unwrap()
            .is_empty());
        s.record("GET", "/api/mine".into(), 200, py, true);
        s.record("GET", "/api/local".into(), 200, Outcome::Local, false);
        // Açılmış anahtara kimliksiz istek de yazılır.
        s.record("GET", "/api/mine".into(), 200, py, false);
        let v = s.snapshot(vec![], vec![]);
        assert_eq!(v["endpoints"].as_array().unwrap().len(), 2);
        assert_eq!(v["endpoints"][1]["fallback"], 2);
        assert_eq!(v["other"]["fallback"], MAX_KEYS as u64 + 10);
    }
}
