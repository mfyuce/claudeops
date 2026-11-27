//! `systemctl --user ...` çalıştırıcısı (Python `front_cmd._sc`): `PATH`teki `systemctl`, çıktısı terminale akar, dönüş kodu.
//! Testler [`Systemctl`]i sahtesiyle değiştirir; gerçek `systemctl` testte HİÇ çağrılmaz.

/// Çalıştırıcı.
pub trait Systemctl {
    /// `systemctl --user <args>`; başlatılamazsa `Err`, sinyalle biterse `128 + sinyal`.
    fn run(&mut self, args: &[&str]) -> Result<i32, String>;
    /// Web biriminin systemd'nin bildirdiği yolları (`show -p FragmentPath -p DropInPaths`); okunamazsa `Err`.
    fn unit_paths(&mut self) -> Result<UnitPaths, String>;
}

/// `systemctl show` yanıtı.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct UnitPaths {
    /// `FragmentPath` (yoksa boş)
    pub fragment: String,
    /// `DropInPaths`
    pub dropins: Vec<String>,
}

/// `show` çıktısı.
pub fn parse_unit_paths(out: &str) -> UnitPaths {
    let mut u = UnitPaths::default();
    for line in out.split('\n') {
        match line.split_once('=') {
            Some(("FragmentPath", v)) => u.fragment = v.into(),
            Some(("DropInPaths", v)) => u.dropins = v.split_whitespace().map(Into::into).collect(),
            _ => {}
        }
    }
    u
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
    fn unit_paths(&mut self) -> Result<UnitPaths, String> {
        use std::os::unix::process::ExitStatusExt;
        let out = std::process::Command::new("systemctl")
            .args(["--user", "show", super::WEB_UNIT_NAME])
            .args(["-p", "FragmentPath", "-p", "DropInPaths"])
            .stdin(std::process::Stdio::null())
            .output()
            .map_err(|e| format!("systemctl başlatılamadı: {e}"))?;
        if !out.status.success() {
            let st = out.status;
            let rc = st.code().unwrap_or_else(|| 128 + st.signal().unwrap_or(0));
            return Err(format!("çıkış {rc}"));
        }
        Ok(parse_unit_paths(&String::from_utf8_lossy(&out.stdout)))
    }
}

/// Komut metni (`systemctl --user a b`).
pub fn show(args: &[&str]) -> String {
    format!("systemctl --user {}", args.join(" "))
}
