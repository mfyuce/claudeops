//! `systemctl --user ...` çalıştırıcısı (Python `front_cmd._sc`): `PATH`teki `systemctl`, çıktısı terminale akar, dönüş kodu.
//! Testler [`Systemctl`]i sahtesiyle değiştirir; gerçek `systemctl` testte HİÇ çağrılmaz.

/// Çalıştırıcı.
pub trait Systemctl {
    /// `systemctl --user <args>`; başlatılamazsa `Err`, sinyalle biterse `128 + sinyal`.
    fn run(&mut self, args: &[&str]) -> Result<i32, String>;
}

/// Gerçek `systemctl`.
pub struct RealSystemctl;

impl Systemctl for RealSystemctl {
    fn run(&mut self, args: &[&str]) -> Result<i32, String> {
        use std::os::unix::process::ExitStatusExt;
        let st = std::process::Command::new("systemctl")
            .arg("--user")
            .args(args)
            .status()
            .map_err(|e| format!("systemctl başlatılamadı: {e}"))?;
        Ok(st.code().unwrap_or_else(|| 128 + st.signal().unwrap_or(0)))
    }
}

/// Komut metni (`systemctl --user a b`).
pub fn show(args: &[&str]) -> String {
    format!("systemctl --user {}", args.join(" "))
}
