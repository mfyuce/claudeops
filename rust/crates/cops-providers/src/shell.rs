//! Düz shell: model/izin/effort uygulanmaz; `argv[0]` keşif için etiketlenir.

/// `argv[0]` etiketi.
pub const PROC_TAG: &str = "claudeops-shell";
/// Seçici listeleri boş kalmasın diye tek elemanlı sentinel.
pub const SENTINEL: [&str; 1] = ["-"];

pub(crate) fn build_inner_command() -> String {
    format!("exec -a {PROC_TAG} bash")
}
