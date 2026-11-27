//! `cops front` argüman ayrıştırması: Python 3.10 `argparse` davranışının bu ayrıştırıcıdaki karşılığı
//! (`commands/front_cmd.py` `register`; seçenekler `-h/--help`, `--apply`, `--listen`, `--internal`, `--bin`, konumsal `action`).
//!
//! Kapsanan kabul biçimleri (Python ile aynı sonuç, `tests/argparse_parity.rs` Python'un kendi ayrıştırıcısına karşı denetler):
//! `--x Y`, `--x=Y` (boş `Y` dahil), benzersiz önek kısaltması (`--app`, `--int=Y`; argparse `allow_abbrev`), seçenekler ve
//! konumsalın her sırası, tekrarlanan seçenekte son değer, ilk `--`ten sonrası konumsal, değer olarak `-` ve negatif sayı.
//! Bunların DIŞINDAKİ her şey (yardım `-h`, hata: eksik/fazla konumsal, geçersiz seçim, bilinmeyen/belirsiz seçenek, değersiz
//! seçenek, `--apply=..`, boşluk içeren ya da ASCII dışı `-`li belirteç, UTF-8 olmayan argüman) [`Parsed::Delegate`] olur:
//! Python aynı argv ile kendi mesajını ve çıkış kodunu (yardım 0, hata 2) üretir. Hata/yardım biçimleri Python'da hiçbir
//! eylem çalıştırmaz (argparse `run`dan önce çıkar), devir güvenlidir.

use std::ffi::OsString;

/// `front` eylemi.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Action {
    /// `status`
    Status,
    /// `on`
    On,
    /// `off`
    Off,
}

impl Action {
    /// Python `choices` metni.
    pub fn as_str(self) -> &'static str {
        match self {
            Action::Status => "status",
            Action::On => "on",
            Action::Off => "off",
        }
    }
}

/// Ayrıştırılmış `front` argümanları (`None` = Python varsayılanı kullanılacak).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FrontArgs {
    /// konumsal `action`
    pub action: Action,
    /// `--apply`
    pub apply: bool,
    /// `--listen`
    pub listen: Option<String>,
    /// `--internal`
    pub internal: Option<String>,
    /// `--bin`
    pub bin: Option<String>,
}

/// Ayrıştırma sonucu.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Parsed {
    /// Rust işler.
    Front(FrontArgs),
    /// Python'a devredilir (neden tanı içindir).
    Delegate(&'static str),
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Opt {
    Help,
    Apply,
    Listen,
    Internal,
    Bin,
}

/// `_option_string_actions` (argparse sırası).
const OPTS: [(&str, Opt); 6] = [
    ("-h", Opt::Help),
    ("--help", Opt::Help),
    ("--apply", Opt::Apply),
    ("--listen", Opt::Listen),
    ("--internal", Opt::Internal),
    ("--bin", Opt::Bin),
];

enum Class {
    /// konumsal ('A')
    Pos,
    /// seçenek ve varsa `=` sonrası açık değer
    Opt(Opt, Option<String>),
    /// devret
    Delegate(&'static str),
}

/// argparse `_negative_number_matcher` (`^-\d+$|^-\d*\.\d+$`), yalnız ASCII rakam (ASCII dışı belirteç zaten devredilir).
fn negative_number(s: &str) -> bool {
    let Some(r) = s.strip_prefix('-') else {
        return false;
    };
    let digits = |t: &str| !t.is_empty() && t.bytes().all(|b| b.is_ascii_digit());
    if digits(r) {
        return true;
    }
    match r.split_once('.') {
        Some((a, b)) => (a.is_empty() || a.bytes().all(|c| c.is_ascii_digit())) && digits(b),
        None => false,
    }
}

/// argparse `_parse_optional` + `_get_option_tuples` (bu seçenek kümesi için).
fn classify(s: &str) -> Class {
    if !s.starts_with('-') || s.len() == 1 {
        return Class::Pos;
    }
    if !s.is_ascii() {
        return Class::Delegate("ASCII dışı '-' belirteci");
    }
    if let Some(&(_, o)) = OPTS.iter().find(|(n, _)| *n == s) {
        return Class::Opt(o, None);
    }
    if let Some((name, val)) = s.split_once('=') {
        if let Some(&(_, o)) = OPTS.iter().find(|(n, _)| *n == name) {
            return Class::Opt(o, Some(val.to_string()));
        }
    }
    let mut hits: Vec<(Opt, Option<String>)> = Vec::new();
    if s.starts_with("--") {
        let (prefix, explicit) = match s.split_once('=') {
            Some((p, v)) => (p, Some(v.to_string())),
            None => (s, None),
        };
        for (n, o) in OPTS {
            if n.starts_with(prefix) {
                hits.push((o, explicit.clone()));
            }
        }
    } else {
        // tek tire: kısa önek `-h` + bitişik değer ya da tam önek
        for (n, o) in OPTS {
            if n == &s[..2] {
                hits.push((o, Some(s[2..].to_string())));
            } else if n.starts_with(s) {
                hits.push((o, None));
            }
        }
    }
    match hits.len() {
        0 => {}
        1 => {
            let (o, v) = hits.remove(0);
            return Class::Opt(o, v);
        }
        _ => return Class::Delegate("belirsiz seçenek kısaltması"),
    }
    if negative_number(s) {
        return Class::Pos;
    }
    if s.contains(' ') {
        // argparse konumsal sayar; değer olarak anlamsız, Python'a bırak.
        return Class::Delegate("boşluk içeren '-' belirteci");
    }
    Class::Delegate("bilinmeyen seçenek")
}

/// `front` sonrası argümanları ayrıştırır (`args` = `front`tan SONRAKİLER).
pub fn parse_front(args: &[OsString]) -> Parsed {
    let mut toks: Vec<&str> = Vec::with_capacity(args.len());
    for a in args {
        match a.to_str() {
            Some(s) => toks.push(s),
            None => return Parsed::Delegate("UTF-8 olmayan argüman"),
        }
    }
    // 1) argparse ilk geçişi: her belirteç sınıflanır (belirsiz seçenek burada hata verir); ilk `--` işaret ('-'),
    //    sonrası hep konumsal.
    #[derive(Clone, PartialEq, Eq)]
    enum K {
        Pos,
        Marker,
        Opt(Opt, Option<String>),
    }
    let mut kinds: Vec<K> = Vec::with_capacity(toks.len());
    let mut after_marker = false;
    for t in &toks {
        kinds.push(if after_marker {
            K::Pos
        } else if *t == "--" {
            after_marker = true;
            K::Marker
        } else {
            match classify(t) {
                Class::Pos => K::Pos,
                Class::Opt(o, e) => K::Opt(o, e),
                Class::Delegate(why) => return Parsed::Delegate(why),
            }
        });
    }
    let n = toks.len();
    // 2) `_parse_known_args` döngüsü: konumsal (`-*A-*`) yalnız bir seçeneğe kadar olan dilimde ve tek kez tüketilir; artan
    //    her belirteç "unrecognized arguments" hatasıdır.
    let consume_pos = |start: usize| -> Option<(usize, usize)> {
        let mut j = start;
        while j < n && kinds[j] == K::Marker {
            j += 1;
        }
        if j < n && kinds[j] == K::Pos {
            let v = j;
            j += 1;
            while j < n && kinds[j] == K::Marker {
                j += 1;
            }
            Some((j, v))
        } else {
            None
        }
    };
    let (mut apply, mut listen, mut internal, mut bin) = (false, None, None, None);
    let mut action_idx: Option<usize> = None;
    let mut start = 0;
    while let Some(next_opt) = (start..n).find(|&i| matches!(kinds[i], K::Opt(..))) {
        if action_idx.is_none() {
            if let Some((end, v)) = consume_pos(start) {
                action_idx = Some(v);
                start = end;
                continue;
            }
        }
        if start != next_opt {
            return Parsed::Delegate("fazla argüman");
        }
        let K::Opt(o, explicit) = kinds[start].clone() else {
            return Parsed::Delegate("iç hata");
        };
        match (o, explicit) {
            (Opt::Help, _) => return Parsed::Delegate("yardım"),
            (Opt::Apply, Some(_)) => return Parsed::Delegate("--apply değer almaz"),
            (Opt::Apply, None) => {
                apply = true;
                start += 1;
            }
            (o, explicit) => {
                let v = match explicit {
                    Some(v) => {
                        start += 1;
                        v
                    }
                    None if start + 1 < n && kinds[start + 1] == K::Pos => {
                        start += 2;
                        toks[start - 1].to_string()
                    }
                    None => return Parsed::Delegate("seçenek değeri eksik"),
                };
                match o {
                    Opt::Listen => listen = Some(v),
                    Opt::Internal => internal = Some(v),
                    _ => bin = Some(v),
                }
            }
        }
    }
    if action_idx.is_none() {
        if let Some((end, v)) = consume_pos(start) {
            action_idx = Some(v);
            start = end;
        }
    }
    if start < n {
        return Parsed::Delegate("fazla argüman");
    }
    let positionals: Vec<&str> = action_idx.map(|i| toks[i]).into_iter().collect();
    let action = match positionals.as_slice() {
        ["status"] => Action::Status,
        ["on"] => Action::On,
        ["off"] => Action::Off,
        [] => return Parsed::Delegate("eylem eksik"),
        [_] => return Parsed::Delegate("geçersiz eylem"),
        _ => return Parsed::Delegate("fazla konumsal argüman"),
    };
    Parsed::Front(FrontArgs {
        action,
        apply,
        listen,
        internal,
        bin,
    })
}

/// `list`/`ls` argümanları (Python `commands/ls.py` `register`).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ListArgs {
    /// `--no-cpu`
    pub no_cpu: bool,
    /// `--base`
    pub base: Option<String>,
    /// `--json`
    pub json: bool,
}

/// `list` sonrası argümanlar. Yalnız açıkça kabul edilen biçimler (`--x`, `--base Y`, `--base=Y`, benzersiz önek
/// kısaltması); gerisi (yardım, hata, konumsal, `--`, `-`li değer) `Err(neden)` = Python'a devir.
pub fn parse_list(args: &[OsString]) -> Result<ListArgs, &'static str> {
    let mut out = ListArgs::default();
    let mut it = args.iter().map(|a| a.to_str());
    while let Some(t) = it.next() {
        let t = t.ok_or("UTF-8 olmayan argüman")?;
        let (name, explicit) = match t.split_once('=') {
            Some((n, v)) => (n, Some(v)),
            None => (t, None),
        };
        if name.len() <= 2 || !name.starts_with("--") {
            return Err("Rust'ın taklit etmediği list argümanı");
        }
        let hits: Vec<&str> = ["--help", "--no-cpu", "--base", "--json"]
            .into_iter()
            .filter(|o| o.starts_with(name))
            .collect();
        match (hits.as_slice(), explicit) {
            (["--no-cpu"], None) => out.no_cpu = true,
            (["--json"], None) => out.json = true,
            (["--base"], Some(v)) => out.base = Some(v.to_string()),
            (["--base"], None) => {
                let v = it.next().flatten().ok_or("--base değeri yok")?;
                if v.starts_with('-') && v.len() > 1 {
                    return Err("'-' ile başlayan --base değeri");
                }
                out.base = Some(v.to_string());
            }
            _ => return Err("Rust'ın taklit etmediği list argümanı"),
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn p(v: &[&str]) -> Parsed {
        parse_front(&v.iter().map(OsString::from).collect::<Vec<_>>())
    }

    fn f(v: &[&str]) -> FrontArgs {
        match p(v) {
            Parsed::Front(a) => a,
            d => panic!("{v:?} -> {d:?}"),
        }
    }

    #[test]
    fn accepted_forms() {
        let a = f(&[
            "--int=x:1",
            "on",
            "--app",
            "--li",
            "a:2",
            "--bin=",
            "--listen=b:3",
        ]);
        assert_eq!(a.action, Action::On);
        assert!(a.apply);
        assert_eq!(a.listen.as_deref(), Some("b:3"));
        assert_eq!(a.internal.as_deref(), Some("x:1"));
        assert_eq!(a.bin.as_deref(), Some(""));
        assert_eq!(f(&["--", "off"]).action, Action::Off);
        assert_eq!(f(&["off", "--"]).action, Action::Off);
        assert_eq!(f(&["--apply", "--", "on"]).action, Action::On);
        assert_eq!(f(&["status", "--bin", "-"]).bin.as_deref(), Some("-"));
        assert_eq!(
            f(&["status", "--internal", "-5"]).internal.as_deref(),
            Some("-5")
        );
        assert_eq!(
            f(&["status", "--internal", "-.5"]).internal.as_deref(),
            Some("-.5")
        );
    }

    #[test]
    fn errors_and_help_are_delegated() {
        for v in [
            &["on", "-h"][..],
            &["--he"],
            &["-hx"],
            &[],
            &["foo"],
            &["on", "off"],
            &["on", "--apply=1"],
            &["on", "--bin"],
            &["on", "--bin", "--apply"],
            &["on", "--bin", "--"],
            &["on", "-x"],
            &["on", "--=x"],
            &["on", "--bin", "-x y"],
            &["on", "--zz"],
            &["--", "--", "on"],
            &["on", "--", "--apply"],
            &["on", "--apply", "--"],
            &["--", "--apply", "on"],
        ] {
            assert!(matches!(p(v), Parsed::Delegate(_)), "{v:?}");
        }
        use std::os::unix::ffi::OsStringExt;
        let bad = OsString::from_vec(vec![0xff]);
        assert!(matches!(
            parse_front(&[OsString::from("status"), OsString::from("--bin"), bad]),
            Parsed::Delegate(_)
        ));
    }
}
