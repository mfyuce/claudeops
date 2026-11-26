//! Paketli tmux yapılandırması kuralları (CLAUDE.md "`data/tmux.conf` uyumluluğu"; Python `test_tmux_strip.py` ile
//! aynı kurallar, Rust izi için): tmux tanımadığı TEK satırda dosyanın hiçbir satırını uygulamaz (yuhem 3.0a).

use std::fs;

const DATA: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../py/claudeops/data");

fn code_lines(text: &str) -> Vec<&str> {
    text.lines()
        .map(str::trim)
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
        .collect()
}

#[test]
fn main_conf_is_only_plain_global_options_and_version_gated_includes() {
    let text = fs::read_to_string(format!("{DATA}/tmux.conf")).unwrap();
    let lines = code_lines(&text);
    assert!(!lines.is_empty());
    for line in lines {
        let ok = line.starts_with("set-option -g ")
            || (line.starts_with("if-shell -F \"#{>=:#{version},") && line.contains("source-file"));
        assert!(ok, "ana tmux.conf'ta izinsiz satır: {line}");
        assert!(!line.ends_with(';'), "satır sonu `;`: {line}");
    }
}

#[test]
fn menu_commands_take_the_client_name_never_the_session_name() {
    let text = fs::read_to_string(format!("{DATA}/tmux-strip.conf")).unwrap();
    // `run-shell` komutları biçimi genişletip YENİDEN ayrıştırır: oturum adı komuta girmez, `#{q:client_name}` girer.
    let code = code_lines(&text).join("\n");
    let runs: Vec<&str> = code
        .split("run-shell")
        .skip(1)
        .map(|rest| {
            rest.split(['\n', '"'])
                .find(|s| !s.trim().is_empty())
                .unwrap_or("")
        })
        .collect();
    assert!(!runs.is_empty(), "menü komutu bulunamadı");
    for cmd in runs {
        assert!(!cmd.contains("session_name"), "komutta oturum adı: {cmd}");
        if cmd.contains("winact") {
            assert!(cmd.contains("#{q:client_name}"), "istemci adı yok: {cmd}");
        }
    }
}

#[test]
fn strip_reads_cops_ctx_and_main_conf_stays_plain() {
    // Python `test_tmux_ctx_strip.StripConfTests`: yeni özellik yalnız sürüm kapılı ayrı dosyada (tmux 3.0a'yı bozmasın).
    let strip = fs::read_to_string(format!("{DATA}/tmux-strip.conf")).unwrap();
    assert!(strip.contains("#{@cops_ctx}"));
    let main = fs::read_to_string(format!("{DATA}/tmux.conf")).unwrap();
    assert!(!main.contains("cops_ctx"));
}
