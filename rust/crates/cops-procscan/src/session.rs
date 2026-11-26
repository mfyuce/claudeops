//! Çalışan oturum modeli ve satır katlama kuralları (`session.py`, `discovery.fold_*`).

use regex::Regex;
use serde::Serialize;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::LazyLock;

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Session {
    pub name: String,
    pub pid: u32,
    pub cwd: String,
    /// Konuşma id'si: canlı `sessions/<pid>.json` `sessionId`, yoksa argv.
    pub sid: Option<String>,
    pub model: Option<String>,
    pub permission_mode: Option<String>,
    pub effort: Option<String>,
    /// Anlık %CPU (100 = bir çekirdek), tek ondalık.
    pub cpu: f64,
    pub cli: String,
    /// argv'de devam bayrağı VARDI mı; `None` = yalnız json kaynağı (bilinmiyor).
    pub resumed: Option<bool>,
    pub kind: String,
    pub job_id: Option<String>,
    pub parked_job_id: Option<String>,
    /// Ön yüz satırına katlanmış arka plan süreci.
    pub bg_pid: Option<u32>,
}

impl Session {
    /// CPU > %2 = işliyor.
    pub fn active(&self) -> bool {
        self.cpu > 2.0
    }

    pub fn is_fresh(&self) -> bool {
        match self.resumed {
            Some(r) => !r,
            None => self.sid.is_none(),
        }
    }

    /// Taban isim: `^([a-z]+)\d*(?:_\d+)*$` eşleşirse harf kısmı, değilse adın kendisi.
    pub fn base(&self) -> &str {
        base_name(&self.name)
    }

    pub fn model_short(&self) -> &str {
        let m = self.model.as_deref().unwrap_or("");
        if self.cli == "claude" {
            if let Some(k) = ["sonnet", "opus", "haiku", "fable"].into_iter().find(|k| m.contains(k)) {
                return k;
            }
        }
        if m.is_empty() {
            "?"
        } else {
            m
        }
    }
}

pub fn base_name(name: &str) -> &str {
    static RE: LazyLock<Option<Regex>> = LazyLock::new(|| Regex::new("^([a-z]+)\\d*(?:_\\d+)*\n?$").ok());
    RE.as_ref()
        .and_then(|re| re.captures(name))
        .and_then(|c| c.get(1))
        .map_or(name, |m| m.as_str())
}

/// Birden fazla süreci olan adlar (sıralı).
pub fn duplicates(sessions: &[Session]) -> Vec<String> {
    let mut counts: BTreeMap<&str, usize> = BTreeMap::new();
    for s in sessions {
        *counts.entry(&s.name).or_default() += 1;
    }
    counts
        .into_iter()
        .filter(|(_, c)| *c > 1)
        .map(|(n, _)| n.to_owned())
        .collect()
}

/// Claude arka plan oturumunu (`kind == "bg"`) canlı ön yüz satırına katlar: ön yüz bg'nin `sid`ini ve `bg_pid`i alır.
/// Eşleşme `jobId == parkedJobId`, yoksa aynı ad+cli+cwd'de TEK ön yüz. Belirsiz bg satırı ayrı kalır.
pub fn fold_background(mut sessions: Vec<Session>) -> Vec<Session> {
    let bgs: Vec<usize> = (0..sessions.len()).filter(|&i| sessions[i].kind == "bg").collect();
    let mut drop = HashSet::new();
    for bi in bgs {
        let b = sessions[bi].clone();
        let fronts: Vec<usize> = (0..sessions.len())
            .filter(|&i| {
                let f = &sessions[i];
                i != bi && f.kind != "bg" && f.name == b.name && f.cli == b.cli
            })
            .collect();
        let mut link: Vec<usize> = fronts
            .iter()
            .copied()
            .filter(|&i| b.job_id.is_some() && sessions[i].parked_job_id == b.job_id)
            .collect();
        if link.is_empty() {
            let same: Vec<usize> = fronts.iter().copied().filter(|&i| sessions[i].cwd == b.cwd).collect();
            if same.len() == 1 {
                link = same;
            }
        }
        let [fi] = link[..] else { continue };
        let f = &mut sessions[fi];
        if f.bg_pid.is_some_and(|p| p != b.pid) {
            continue;
        }
        f.bg_pid = Some(b.pid);
        if b.sid.is_some() {
            f.sid = b.sid;
        }
        drop.insert(bi);
    }
    sessions
        .into_iter()
        .enumerate()
        .filter(|(i, _)| !drop.contains(i))
        .map(|(_, s)| s)
        .collect()
}

/// Düz shell oturumunun alt kabukları (aynı ad, atası da o adda shell satırı) düşer.
pub fn fold_subshells(sessions: Vec<Session>, ancestors: impl Fn(u32) -> Vec<u32>) -> Vec<Session> {
    let mut pids: HashMap<String, HashSet<u32>> = HashMap::new();
    for s in sessions.iter().filter(|s| s.cli == "shell") {
        pids.entry(s.name.clone()).or_default().insert(s.pid);
    }
    sessions
        .into_iter()
        .filter(|s| {
            if s.cli != "shell" {
                return true;
            }
            let same = &pids[&s.name];
            !(same.len() > 1 && ancestors(s.pid).iter().any(|a| same.contains(a)))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base_matches_python_regex() {
        for (n, b) in [
            ("hc", "hc"),
            ("hc58", "hc"),
            ("cops20260824_1", "cops"),
            ("mo_1_2", "mo"),
            ("a_", "a_"),
            ("a1b", "a1b"),
            ("a\u{661}", "a"),
            ("hc1\n", "hc"),
            ("a\u{b2}", "a\u{b2}"),
            ("Hc1", "Hc1"),
            ("claude@x#1", "claude@x#1"),
            ("", ""),
        ] {
            assert_eq!(base_name(n), b, "{n}");
        }
    }

    #[test]
    fn model_short() {
        let mut s = Session {
            cli: "claude".into(),
            model: Some("claude-opus-5-5".into()),
            ..Default::default()
        };
        assert_eq!(s.model_short(), "opus");
        s.cli = "agy".into();
        assert_eq!(s.model_short(), "claude-opus-5-5");
        s.model = None;
        assert_eq!(s.model_short(), "?");
    }

    fn s(name: &str, pid: u32, cli: &str) -> Session {
        Session {
            name: name.into(),
            pid,
            cli: cli.into(),
            cwd: "/w".into(),
            ..Default::default()
        }
    }

    #[test]
    fn background_folds_into_single_front() {
        let front = Session {
            sid: Some("f".into()),
            ..s("a", 1, "claude")
        };
        let bg = Session {
            kind: "bg".into(),
            sid: Some("b".into()),
            ..s("a", 2, "claude")
        };
        let out = fold_background(vec![front.clone(), bg.clone()]);
        assert_eq!(out.len(), 1);
        assert_eq!((out[0].sid.as_deref(), out[0].bg_pid), (Some("b"), Some(2)));
        // iki aday ön yüz, bağ yok: bg ayrı kalır
        assert_eq!(fold_background(vec![front.clone(), s("a", 3, "claude"), bg.clone()]).len(), 3);
        // jobId bağı belirsizliği çözer
        let parked = Session {
            parked_job_id: Some("j".into()),
            ..s("a", 3, "claude")
        };
        let bgj = Session {
            job_id: Some("j".into()),
            ..bg
        };
        let out = fold_background(vec![front, parked, bgj]);
        assert_eq!(out.iter().find(|x| x.pid == 3).unwrap().bg_pid, Some(2));
        assert_eq!(out.len(), 2);
    }

    #[test]
    fn subshells_fold_only_for_shell() {
        let v = vec![
            s("x", 10, "shell"),
            s("x", 11, "shell"),
            s("x", 12, "shell"),
            s("y", 13, "codex"),
            s("y", 14, "codex"),
        ];
        let out = fold_subshells(v, |p| match p {
            11 => vec![10],
            14 => vec![13],
            _ => vec![],
        });
        assert_eq!(out.iter().map(|s| s.pid).collect::<Vec<_>>(), [10, 12, 13, 14]);
        assert_eq!(duplicates(&out), ["x", "y"]);
    }
}
