//! Ortam değişkenleri: gerçek süreç ortamı ya da çağıranın verdiği sabit liste (test ve yalıtım).

use std::fmt;
use std::process::Command;
use std::sync::Arc;

/// `os.environ` karşılığı. Sabit listede SIRA korunur (proxy değişkenlerinde büyük/küçük harf çakışmasını sıra çözer).
#[derive(Clone, Default)]
pub struct Env(Option<Arc<Vec<(String, String)>>>);

impl fmt::Debug for Env {
    /// Ortam sır taşır: yalnız kaynağın türü basılır.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(if self.0.is_some() { "Env(fixed)" } else { "Env(process)" })
    }
}

impl Env {
    /// Sürecin o anki ortamı (her okumada yeniden).
    pub fn process() -> Env {
        Env(None)
    }

    /// Yalnız verilen değişkenler; yinelenen adda SON değer geçerli.
    pub fn fixed<K: Into<String>, V: Into<String>>(vars: impl IntoIterator<Item = (K, V)>) -> Env {
        let mut out: Vec<(String, String)> = Vec::new();
        for (k, v) in vars {
            let (k, v) = (k.into(), v.into());
            match out.iter_mut().find(|(have, _)| *have == k) {
                Some(slot) => slot.1 = v,
                None => out.push((k, v)),
            }
        }
        Env(Some(Arc::new(out)))
    }

    /// Değer UTF-8 değilse None.
    pub fn get(&self, name: &str) -> Option<String> {
        match &self.0 {
            Some(v) => v.iter().find(|(k, _)| k == name).map(|(_, v)| v.clone()),
            None => std::env::var(name).ok(),
        }
    }

    /// Bütün değişkenler (UTF-8 olmayanlar atlanır), ortam sırasıyla.
    pub fn vars(&self) -> Vec<(String, String)> {
        match &self.0 {
            Some(v) => v.as_ref().clone(),
            None => std::env::vars_os().filter_map(|(k, v)| Some((k.into_string().ok()?, v.into_string().ok()?))).collect(),
        }
    }

    /// Alt sürece aynı ortamı verir (süreç ortamında miras).
    pub fn apply(&self, cmd: &mut Command) {
        if let Some(v) = &self.0 {
            cmd.env_clear().envs(v.iter().map(|(k, v)| (k, v)));
        }
    }
}
