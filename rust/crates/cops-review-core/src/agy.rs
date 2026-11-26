//! agy izin kuralı ve model etiketi doğrulama.
use crate::py;
use cops_state::json::{Json, Map};
use regex::Regex;
use std::sync::LazyLock;

pub const AGY_ALLOW_DEFAULT: [&str; 5] = ["ls", "grep", "head", "tail", "wc"];

pub fn agy_allow_list(spec: &str) -> Vec<String> {
    static NAME: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Za-z0-9._-]+$").unwrap());
    let t = py::strip(spec);
    if t.to_lowercase() == "off" {
        return Vec::new();
    }
    let mut names: Vec<&str> = t
        .split(',')
        .map(py::strip)
        .filter(|x| !x.is_empty())
        .collect();
    if names.is_empty() {
        names = AGY_ALLOW_DEFAULT.to_vec();
    }
    names
        .into_iter()
        .filter(|n| NAME.is_match(n))
        .map(str::to_string)
        .collect()
}

/// İzole agy HOME'unun `settings.json` içeriği.
pub fn agy_settings(cwd: &str, allow: &[String]) -> Json {
    let mut perm = Map::new();
    perm.insert(
        "allow".into(),
        Json::Array(
            allow
                .iter()
                .map(|a| Json::Str(format!("command({a})")))
                .collect(),
        ),
    );
    let mut m = Map::new();
    m.insert("allowNonWorkspaceAccess".into(), Json::Bool(false));
    m.insert("permissions".into(), Json::Object(perm));
    m.insert("trustedWorkspaces".into(), Json::Array(vec![cwd.into()]));
    Json::Object(m)
}

fn norm_label(s: &str) -> String {
    s.to_lowercase()
        .chars()
        .filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
        .collect()
}

/// Log'daki SON `label=` istenen modelle tam uyuşuyor mu: (uyuştu, görülen etiket).
pub fn agy_label_ok(log_text: &str, model: &str) -> (bool, String) {
    static LABEL: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(&format!(
            r#"Propagating selected model override\b.*?\blabel=("[^"]*"|'[^']*'|[^{}]+)"#,
            py::S
        ))
        .unwrap()
    });
    let Some(last) = LABEL.captures_iter(log_text).last() else {
        return (false, String::new());
    };
    let seen = last[1].trim_matches(['"', '\'']).to_string();
    let (a, b) = (norm_label(&seen), norm_label(model));
    (!a.is_empty() && !b.is_empty() && a == b, seen)
}
