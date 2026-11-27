//! Ortam değişkenleri: gerçek süreç ortamı ya da çağıranın verdiği sabit liste (test ve yalıtım).

use std::fmt;
use std::process::Command;
use std::sync::Arc;

/// `os.environ` karşılığı. Sabit listede SIRA korunur (proxy değişkenlerinde büyük/küçük harf çakışmasını sıra çözer).
#[derive(Clone, Default)]
pub struct Env {
    fixed: Option<Arc<Vec<(String, String)>>>,
    /// Tabanın üstüne yazılan tek değişkenler ([`Env::with_var`]).
    over: Vec<(String, String)>,
}

impl fmt::Debug for Env {
    /// Ortam sır taşır: yalnız kaynağın türü basılır.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(if self.fixed.is_some() {
            "Env(fixed)"
        } else {
            "Env(process)"
        })
    }
}

impl Env {
    /// Sürecin o anki ortamı (her okumada yeniden).
    pub fn process() -> Env {
        Env::default()
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
        Env {
            fixed: Some(Arc::new(out)),
            over: Vec::new(),
        }
    }

    /// `{**os.environ, name: value}`: tabanın (UTF-8 olmayanlar dahil) üstüne tek değişken.
    pub fn with_var(&self, name: &str, value: &str) -> Env {
        let mut out = self.clone();
        out.over.retain(|(k, _)| k != name);
        out.over.push((name.to_string(), value.to_string()));
        out
    }

    /// Değer UTF-8 değilse None.
    pub fn get(&self, name: &str) -> Option<String> {
        if let Some((_, v)) = self.over.iter().find(|(k, _)| k == name) {
            return Some(v.clone());
        }
        match &self.fixed {
            Some(v) => v.iter().find(|(k, _)| k == name).map(|(_, v)| v.clone()),
            None => std::env::var(name).ok(),
        }
    }

    /// Bütün değişkenler (UTF-8 olmayanlar atlanır), ortam sırasıyla.
    pub fn vars(&self) -> Vec<(String, String)> {
        let mut out: Vec<(String, String)> = match &self.fixed {
            Some(v) => v.as_ref().clone(),
            None => std::env::vars_os()
                .filter_map(|(k, v)| Some((k.into_string().ok()?, v.into_string().ok()?)))
                .collect(),
        };
        for (name, value) in &self.over {
            match out.iter_mut().find(|(k, _)| k == name) {
                Some(slot) => slot.1.clone_from(value),
                None => out.push((name.clone(), value.clone())),
            }
        }
        out
    }

    /// Alt sürece aynı ortamı verir (süreç ortamında miras).
    pub fn apply(&self, cmd: &mut Command) {
        if let Some(v) = &self.fixed {
            cmd.env_clear().envs(v.iter().map(|(k, v)| (k, v)));
        }
        cmd.envs(self.over.iter().map(|(k, v)| (k, v)));
    }
}
