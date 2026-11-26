//! Python paritesi: `py/claudeops/providers/*`, `spawn.py`, `routing.py`, `effort.py`, `ucli_session_opts.py` ve ilgili
//! `settings.py` okuyucularıyla tablo testi. Python alt süreçte (`tests/parity/harness.py`), yalıtılmış geçici HOME +
//! CLAUDEOPS_DIR + sahte PATH ile çalışır; dış olgular iki tarafta aynı sahte değerlerle verilir. Altyapı:
//! `tests/parity/common.rs`.
//!
//! Karşılaştırmada NORMALLEŞTİRİLEN alanlar (gerekçeli):
//! - Dosya yazma hatasında (ör. üst dizin yok) Python istisnasının METNİ ile Rust `Effect` uygulayıcısının io hatası
//!   metni karşılaştırılmaz; yalnız "ikisi de OS hatası" aranır (metin uygulayıcıya aittir, crate'in değil).
//! - `spawn` ailesinde Python'un başlatma aşaması olayları (`spawn_hidden`, `spawn_direct_headless`,
//!   `spawn_no_gnome_terminal`, `spawn_launch_failed`) atılır: süreç başlatma crate kapsamı dışında (cops-tmux/çağıran).
//! - Sözlük dönüşleri (ör. temiz `cli_opts`) anahtar sırasından bağımsız karşılaştırılır (tüketiciler sıraya bakmaz);
//!   SIRA ANLAMLI olan her şey (argv, env, diag alanları, dosya içerikleri, hizmet effort tabloları) liste olarak ve
//!   sırasıyla karşılaştırılır.

#[path = "parity/common.rs"]
mod common;
#[path = "parity/fam_model.rs"]
mod fam_model;

#[test]
fn parity_model_effort() {
    fam_model::run();
}
#[path = "parity/fam_settings.rs"]
mod fam_settings;

#[test]
fn parity_settings_pyfmt() {
    fam_settings::run();
}
#[path = "parity/fam_build.rs"]
mod fam_build;

#[test]
fn parity_build() {
    fam_build::run();
}
#[path = "parity/fam_ucli.rs"]
mod fam_ucli;

#[test]
fn parity_ucli() {
    fam_ucli::run();
}
#[path = "parity/fam_spawn.rs"]
mod fam_spawn;

#[test]
fn parity_spawn() {
    fam_spawn::run();
}
#[path = "parity/fam_misc.rs"]
mod fam_misc;

#[test]
fn parity_misc() {
    fam_misc::run();
}
#[path = "parity/fam_usage.rs"]
mod fam_usage;

#[test]
fn parity_usage() {
    fam_usage::run();
}
#[path = "parity/fam_chat.rs"]
mod fam_chat;

#[test]
fn parity_chat() {
    fam_chat::run();
}
#[path = "parity/fam_transcript.rs"]
mod fam_transcript;

#[test]
fn parity_transcript() {
    fam_transcript::run();
}
#[path = "parity/fam_panel.rs"]
mod fam_panel;

#[test]
fn parity_panel() {
    fam_panel::run();
}
#[path = "parity/fam_live.rs"]
mod fam_live;

#[test]
fn parity_live() {
    fam_live::run();
}
#[path = "parity/fam_bg.rs"]
mod fam_bg;

#[test]
fn parity_bg_work() {
    fam_bg::run();
}
#[path = "parity/fam_sources.rs"]
mod fam_sources;

#[test]
fn parity_model_sources() {
    fam_sources::run();
}
#[path = "parity/fam_resume.rs"]
mod fam_resume;

#[test]
fn parity_resume() {
    fam_resume::run();
}
#[path = "parity/fam_g8.rs"]
mod fam_g8;

#[test]
fn parity_real() {
    fam_g8::run();
}
#[path = "parity/fam_ledger.rs"]
mod fam_ledger;

#[test]
fn parity_ledger() {
    fam_ledger::run();
}
#[path = "parity/fam_searxng.rs"]
mod fam_searxng;

#[test]
fn parity_searxng() {
    fam_searxng::run();
}
