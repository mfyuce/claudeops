//! Claude transkript yolu.

use crate::Config;
use std::path::PathBuf;

/// claude'un `projects/` altı adlandırması: harf/rakam olmayan her karakter `-`.
pub fn encode_cwd(cwd: &str) -> String {
    cwd.chars().map(|c| if c.is_ascii_alphanumeric() { c } else { '-' }).collect()
}

/// `<projects>/<cwd>/<sid>.jsonl`, yalnız TAM eşleşme. Python'un "sid yok/dosya yok -> cwd'deki en yeni dosya"
/// düşüşü BİLEREK yok: ortak cwd'de başka oturumun transkriptini verir. `sid` tek yol parçası olmalı: `/` ya da NUL
/// içeren sid yok sayılır (TBD#365; Python `jsonl_path_for` da süzer).
pub fn jsonl_path_for(cfg: &Config, cwd: &str, sid: Option<&str>) -> Option<PathBuf> {
    let sid = sid.filter(|s| !s.is_empty() && !s.contains(['/', '\0']))?;
    let path = cfg
        .claude_dir
        .join("projects")
        .join(encode_cwd(cwd))
        .join(format!("{sid}.jsonl"));
    path.is_file().then_some(path)
}

#[cfg(test)]
mod tests {
    #[test]
    fn encodes_non_ascii_per_char() {
        assert_eq!(super::encode_cwd("/a_b/veri_madenciliği.x"), "-a-b-veri-madencili-i-x");
    }
}
