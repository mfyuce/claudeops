//! `cops-rs`: claudeops CLI'ın Rust ikilisi (strangler, docs/rs-cli.md).
//!
//! Rust'ın işlediği komutlar: `front status|on|off` ([`front`]) ve `self` ([`selfcmd`]). Geri kalan her şey (bilinmeyen komut,
//! `list`, `--version`, `-h`, Rust'ın taklit etmediği argüman biçimleri) [`delegate`] ile Python `py/cops`a AYNEN devredilir.

// Ders H5: üretim yolunda panik yok (testler hariç).
#![cfg_attr(
    not(test),
    deny(clippy::unwrap_used, clippy::expect_used, clippy::panic)
)]

pub mod argp;
pub mod delegate;
pub mod front;
pub mod list;
pub mod pyenv;
pub mod selfcmd;

use std::ffi::OsString;

/// Yönlendirme kararı.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Route {
    /// `front ...`
    Front(argp::FrontArgs),
    /// `self`
    SelfCmd,
    /// Python'a (neden tanı içindir)
    Delegate(&'static str),
}

/// `args`: program adından SONRAKİ argümanlar.
pub fn route(args: &[OsString]) -> Route {
    match args.first().and_then(|a| a.to_str()) {
        Some("front") => match argp::parse_front(&args[1..]) {
            argp::Parsed::Front(f) => Route::Front(f),
            argp::Parsed::Delegate(why) => Route::Delegate(why),
        },
        // bash `cmd_self` yalnız $1'e bakar: fazladan argüman yok sayılır.
        Some("self") => Route::SelfCmd,
        _ => Route::Delegate("Rust'ta yok"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn r(v: &[&str]) -> Route {
        route(&v.iter().map(OsString::from).collect::<Vec<_>>())
    }

    #[test]
    fn routing() {
        assert!(matches!(r(&["front", "status"]), Route::Front(_)));
        assert_eq!(r(&["self", "x"]), Route::SelfCmd);
        for v in [
            &[][..],
            &["list"],
            &["ls", "--json"],
            &["--version"],
            &["-h"],
            &["front"],
            &["Front", "status"],
            &["--", "front", "status"],
        ] {
            assert!(matches!(r(v), Route::Delegate(_)), "{v:?}");
        }
    }
}
