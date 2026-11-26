//! Python `re` (3.10, `str` deseni) sözdizimini fancy-regex'e çevirir. `exec_cmds` içindeki `re:` desenleri izin
//! listesini PATH üzerinde açtığından, iki lehçe aynı deseni FARKLI yorumlarsa farklı komutlara izin verilir
//! (ör. `[[:alpha:]]` Python'da harf kümesi `[:alph` + `]`, fancy-regex'te POSIX sınıfı). Burada:
//! - Python'un reddettiği desen Python iletisiyle reddedilir (`bad escape`, `nothing to repeat`, `multiple repeat`,
//!   `missing ), unterminated subpattern`, `unterminated character set`, `unbalanced parenthesis`,
//!   `unknown extension`, `bad character range`, `min repeat greater than max repeat`, `unknown group name`).
//! - Anlam farkları eşlenir: `\Z` -> `\z`, sınıf içindeki `[ & ~ | -` düz karakter, küresel satır içi bayraklar desenin
//!   başına taşınır, `{,n}` -> `{0,n}`, geçersiz `{` düz karakter, adlı gruplar numaralı gruba, `(?P=ad)` numaralı geri
//!   başvuruya çevrilir.
//! - Taşınmayan (nadir) yapılar DAHA SIKI yönde reddedilir: koşullu grup `(?(..)`, `\N{..}`, `x` (verbose) bayrağı.

fn err(msg: impl AsRef<str>, pos: usize) -> String {
    format!("{} at position {pos}", msg.as_ref())
}

fn hex_lit(c: char) -> String {
    if c.is_ascii_alphanumeric() || c == '_' {
        c.to_string()
    } else {
        format!("\\x{{{:x}}}", c as u32)
    }
}

#[derive(Clone, Copy, PartialEq)]
enum Last {
    /// Desen/grup/alternatif başı ya da sıfır genişlikli iddia: niceleyici alamaz.
    Nothing,
    Atom,
    /// Niceleyici; `lazy` = arkasından `?` geldi.
    Quant { lazy: bool },
}

struct P<'a> {
    c: &'a [char],
    i: usize,
}

impl P<'_> {
    fn peek(&self, k: usize) -> Option<char> {
        self.c.get(self.i + k).copied()
    }

    fn hex(&mut self, n: usize, start: usize, kind: char) -> Result<char, String> {
        let digits: String = self.c.iter().skip(self.i).take(n).collect();
        if digits.chars().count() != n || !digits.chars().all(|d| d.is_ascii_hexdigit()) {
            return Err(err(format!("incomplete escape \\{kind}{digits}"), start));
        }
        self.i += n;
        let cp = u32::from_str_radix(&digits, 16).unwrap_or(0);
        char::from_u32(cp).ok_or_else(|| err(format!("bad escape \\{kind}{digits}"), start))
    }

    /// Ters bölü sonrası (`self.i` kaçış harfinde). Sınıf içinde mi dışında mı: `in_class`.
    /// Dönüş: (çıktı parçası, sınıf aralığında uç olabilecek tek karakter).
    fn escape(&mut self, start: usize, in_class: bool, groups: usize) -> Result<(String, Option<char>, bool), String> {
        let Some(n) = self.peek(0) else { return Err(err("bad escape (end of pattern)", start)) };
        self.i += 1;
        let lit = |c: char| Ok((hex_lit(c), Some(c), false));
        match n {
            'd' | 'D' | 's' | 'S' | 'w' | 'W' => Ok((format!("\\{n}"), None, false)),
            'b' if in_class => lit('\u{8}'),
            'b' | 'B' | 'A' => Ok((format!("\\{n}"), None, true)),
            'Z' if !in_class => Ok(("\\z".into(), None, true)),
            'a' => lit('\u{7}'),
            'f' => lit('\u{c}'),
            'n' => lit('\n'),
            'r' => lit('\r'),
            't' => lit('\t'),
            'v' => lit('\u{b}'),
            'x' => {
                let digits: String = self.c.iter().skip(self.i).take(2).collect();
                if digits.chars().count() != 2 || !digits.chars().all(|d| d.is_ascii_hexdigit()) {
                    return Err(err(format!("incomplete escape \\x{digits}"), start));
                }
                self.i += 2;
                lit(char::from_u32(u32::from_str_radix(&digits, 16).unwrap()).unwrap())
            }
            'u' => lit(self.hex(4, start, 'u')?),
            'U' => lit(self.hex(8, start, 'U')?),
            '0'..='7' if n == '0' || in_class => {
                // sekizlik: en çok 3 basamak (ilki dahil)
                let mut v = n.to_digit(8).unwrap();
                for _ in 0..2 {
                    match self.peek(0).and_then(|d| d.to_digit(8)) {
                        Some(d) => {
                            v = v * 8 + d;
                            self.i += 1;
                        }
                        None => break,
                    }
                }
                if v > 0o377 {
                    return Err(err(format!("octal escape value \\{:o} outside of range 0-0o377", v), start));
                }
                lit(char::from_u32(v).unwrap())
            }
            '1'..='9' if !in_class => {
                // geri başvuru (üç sekizlik basamak ise sekizlik kaçış)
                let d2 = self.peek(0).filter(char::is_ascii_digit);
                let d3 = self.peek(1).filter(char::is_ascii_digit);
                if let (Some(a), Some(b)) = (d2, d3) {
                    if n < '8' && a < '8' && b < '8' {
                        self.i += 2;
                        let v = n.to_digit(8).unwrap() * 64 + a.to_digit(8).unwrap() * 8 + b.to_digit(8).unwrap();
                        if v > 0o377 {
                            return Err(err(format!("octal escape value \\{n}{a}{b} outside of range 0-0o377"), start));
                        }
                        return lit(char::from_u32(v).unwrap());
                    }
                }
                let mut num = n.to_digit(10).unwrap() as usize;
                if let Some(a) = d2 {
                    num = num * 10 + a.to_digit(10).unwrap() as usize;
                    self.i += 1;
                }
                if num > groups {
                    return Err(err(format!("invalid group reference {num}"), start + 1));
                }
                Ok((format!("\\{num}"), None, false))
            }
            '8' | '9' if in_class => Err(err(format!("bad escape \\{n}"), start)),
            'N' => Err(err("bad escape \\N (adlı karakter desteklenmiyor)", start)),
            c if c.is_ascii_alphanumeric() => Err(err(format!("bad escape \\{c}"), start)),
            c => lit(c),
        }
    }

    fn class(&mut self) -> Result<String, String> {
        let start = self.i;
        self.i += 1;
        let mut out = String::from("[");
        if self.peek(0) == Some('^') {
            out.push('^');
            self.i += 1;
        }
        let mut first = true;
        loop {
            let Some(c) = self.peek(0) else { return Err(err("unterminated character set", start)) };
            if c == ']' && !first {
                self.i += 1;
                break;
            }
            first = false;
            let item_start = self.i;
            let (lo_s, lo_c) = if c == '\\' {
                self.i += 1;
                let (s, ch, _) = self.escape(item_start, true, 0)?;
                (s, ch)
            } else {
                self.i += 1;
                (hex_lit(c), Some(c))
            };
            // aralık?
            if self.peek(0) == Some('-') && self.peek(1).is_some_and(|n| n != ']') {
                self.i += 1;
                let hi_start = self.i;
                let h = self.peek(0).unwrap();
                let (hi_s, hi_c) = if h == '\\' {
                    self.i += 1;
                    let (s, ch, _) = self.escape(hi_start, true, 0)?;
                    (s, ch)
                } else {
                    self.i += 1;
                    (hex_lit(h), Some(h))
                };
                let text: String = self.c[item_start..self.i].iter().collect();
                let (Some(lo), Some(hi)) = (lo_c, hi_c) else {
                    return Err(err(format!("bad character range {text}"), item_start));
                };
                if hi < lo {
                    return Err(err(format!("bad character range {text}"), item_start));
                }
                out.push_str(&format!("{lo_s}-{hi_s}"));
            } else {
                out.push_str(&lo_s);
            }
        }
        out.push(']');
        Ok(out)
    }
}

/// Python deseni -> fancy-regex deseni (ya da Python biçiminde hata metni).
pub fn translate(pat: &str) -> Result<String, String> {
    let chars: Vec<char> = pat.chars().collect();
    let mut p = P { c: &chars, i: 0 };
    let mut out = String::new();
    let mut global_flags = String::new();
    let mut stack: Vec<usize> = Vec::new();
    let mut groups = 0usize;
    let mut names: Vec<String> = Vec::new();
    let mut group_index: Vec<usize> = Vec::new();
    let mut last = Last::Nothing;
    while let Some(c) = p.peek(0) {
        let pos = p.i;
        match c {
            '\\' => {
                p.i += 1;
                let (s, _, zero_width) = p.escape(pos, false, groups)?;
                out.push_str(&s);
                last = if zero_width { Last::Nothing } else { Last::Atom };
            }
            '[' => {
                out.push_str(&p.class()?);
                last = Last::Atom;
            }
            '(' => {
                p.i += 1;
                if p.peek(0) != Some('?') {
                    groups += 1;
                    stack.push(pos);
                    out.push('(');
                    last = Last::Nothing;
                    continue;
                }
                p.i += 1;
                match (p.peek(0), p.peek(1)) {
                    (Some(':'), _) => {
                        p.i += 1;
                        stack.push(pos);
                        out.push_str("(?:");
                    }
                    (Some('='), _) | (Some('!'), _) => {
                        out.push_str(&format!("(?{}", p.peek(0).unwrap()));
                        p.i += 1;
                        stack.push(pos);
                    }
                    (Some('<'), Some(d)) if d == '=' || d == '!' => {
                        out.push_str(&format!("(?<{d}"));
                        p.i += 2;
                        stack.push(pos);
                    }
                    (Some('#'), _) => {
                        while let Some(x) = p.peek(0) {
                            p.i += 1;
                            if x == ')' {
                                break;
                            }
                        }
                        if p.c.get(p.i - 1) != Some(&')') {
                            return Err(err("missing ), unterminated comment", pos));
                        }
                        continue;
                    }
                    (Some('P'), Some('<')) => {
                        p.i += 2;
                        let name_start = p.i;
                        let mut name = String::new();
                        loop {
                            match p.peek(0) {
                                None => return Err(err("missing >, unterminated name", name_start)),
                                Some('>') => {
                                    p.i += 1;
                                    break;
                                }
                                Some(x) => {
                                    name.push(x);
                                    p.i += 1;
                                }
                            }
                        }
                        if name.is_empty() {
                            return Err(err("missing group name", name_start));
                        }
                        let ident = name.chars().next().is_some_and(|f| f.is_alphabetic() || f == '_')
                            && name.chars().all(|x| x.is_alphanumeric() || x == '_');
                        if !ident {
                            return Err(err(format!("bad character in group name '{name}'"), name_start));
                        }
                        if let Some(k) = names.iter().position(|n| *n == name) {
                            return Err(err(
                                format!("redefinition of group name '{name}' as group {}; was group {}", groups + 1, group_index[k]),
                                name_start,
                            ));
                        }
                        group_index.push(groups + 1);
                        // fancy-regex adlı grupla numaralı geri başvuruyu birlikte kabul etmez: ad yalnız burada çözülür,
                        // çıktıda numaralı grup (Python numaralandırması aynı).
                        groups += 1;
                        names.push(name.clone());
                        stack.push(pos);
                        out.push('(');
                    }
                    (Some('P'), Some('=')) => {
                        p.i += 2;
                        let name_start = p.i;
                        let mut name = String::new();
                        loop {
                            match p.peek(0) {
                                None => return Err(err("missing ), unterminated name", name_start)),
                                Some(')') => {
                                    p.i += 1;
                                    break;
                                }
                                Some(x) => {
                                    name.push(x);
                                    p.i += 1;
                                }
                            }
                        }
                        if name.is_empty() {
                            return Err(err("missing group name", name_start));
                        }
                        let Some(idx) = names.iter().position(|n| *n == name) else {
                            return Err(err(format!("unknown group name '{name}'"), name_start));
                        };
                        out.push_str(&format!("\\{}", group_index[idx]));
                        last = Last::Atom;
                        continue;
                    }
                    (Some('P'), x) => {
                        let shown = x.map_or(String::new(), String::from);
                        return Err(err(format!("unknown extension ?P{shown}"), pos + 1));
                    }
                    (Some('('), _) => return Err(err("koşullu grup desteklenmiyor", pos + 1)),
                    (Some(f), _) if "aiLmsux-".contains(f) => {
                        let mut on = String::new();
                        while let Some(x) = p.peek(0).filter(|x| "aiLmsux".contains(*x)) {
                            on.push(x);
                            p.i += 1;
                        }
                        let mut off = String::new();
                        if p.peek(0) == Some('-') {
                            p.i += 1;
                            while let Some(x) = p.peek(0).filter(|x| "imsx".contains(*x)) {
                                off.push(x);
                                p.i += 1;
                            }
                            if off.is_empty() {
                                return Err(err("missing flag", p.i));
                            }
                        }
                        if on.contains('x') || off.contains('x') {
                            return Err(err("x (verbose) bayrağı desteklenmiyor", pos + 1));
                        }
                        if on.contains('L') {
                            return Err(err("bad inline flags: cannot use 'L' flag with a str pattern", p.i));
                        }
                        let keep = |s: &str| s.chars().filter(|x| "ims".contains(*x)).collect::<String>();
                        match p.peek(0) {
                            Some(')') if off.is_empty() => {
                                // küresel bayrak: Python'da desenin tamamına uygulanır
                                p.i += 1;
                                global_flags.push_str(&keep(&on));
                                continue;
                            }
                            Some(':') => {
                                p.i += 1;
                                stack.push(pos);
                                let (k_on, k_off) = (keep(&on), keep(&off));
                                out.push_str(&format!("(?{k_on}{}{k_off}:", if k_off.is_empty() { "" } else { "-" }));
                            }
                            Some(_) => return Err(err("unknown flag", p.i)),
                            None => return Err(err("missing -, : or )", p.i)),
                        }
                    }
                    (Some('<'), Some(d)) => return Err(err(format!("unknown extension ?<{d}"), pos + 1)),
                    (Some(x), _) => return Err(err(format!("unknown extension ?{x}"), pos + 1)),
                    (None, _) => return Err(err("unexpected end of pattern", p.i)),
                }
                last = Last::Nothing;
            }
            ')' => {
                if stack.pop().is_none() {
                    return Err(err("unbalanced parenthesis", pos));
                }
                p.i += 1;
                out.push(')');
                last = Last::Atom;
            }
            '*' | '+' | '?' => {
                p.i += 1;
                match last {
                    Last::Nothing => return Err(err("nothing to repeat", pos)),
                    Last::Quant { lazy: false } if c == '?' => {
                        out.push('?');
                        last = Last::Quant { lazy: true };
                    }
                    Last::Quant { .. } => return Err(err("multiple repeat", pos)),
                    Last::Atom => {
                        out.push(c);
                        last = Last::Quant { lazy: false };
                    }
                }
            }
            '{' => {
                // {m}, {m,}, {,n}, {m,n}; başka biçim düz `{`
                let rest: String = chars[pos + 1..].iter().collect();
                let close = rest.find('}');
                let body = close.map(|k| &rest[..k]);
                let parsed = body.and_then(|b| {
                    let (a, z) = match b.split_once(',') {
                        Some((a, z)) => (a, Some(z)),
                        None => (b, None),
                    };
                    let digits = |s: &str| s.chars().all(|d| d.is_ascii_digit());
                    if !digits(a) || !z.is_none_or(digits) || (a.is_empty() && z.is_none()) {
                        return None;
                    }
                    Some((a.to_string(), z.map(str::to_string)))
                });
                match parsed {
                    None => {
                        p.i += 1;
                        out.push_str("\\{");
                        last = Last::Atom;
                    }
                    Some((lo, hi)) => {
                        match last {
                            Last::Nothing => return Err(err("nothing to repeat", pos)),
                            Last::Quant { .. } => return Err(err("multiple repeat", pos)),
                            Last::Atom => {}
                        }
                        let lo_n: u64 = if lo.is_empty() { 0 } else { lo.parse().unwrap_or(u64::MAX) };
                        if let Some(h) = hi.as_deref().filter(|h| !h.is_empty()) {
                            if h.parse::<u64>().unwrap_or(u64::MAX) < lo_n {
                                return Err(err("min repeat greater than max repeat", pos + 1));
                            }
                        }
                        let q = match hi {
                            None => format!("{{{lo_n}}}"),
                            Some(h) => format!("{{{lo_n},{h}}}"),
                        };
                        p.i += 1 + body.unwrap().chars().count() + 1;
                        out.push_str(&q);
                        last = Last::Quant { lazy: false };
                    }
                }
            }
            '|' => {
                p.i += 1;
                out.push('|');
                last = Last::Nothing;
            }
            '^' | '$' => {
                p.i += 1;
                out.push(c);
                last = Last::Nothing;
            }
            '.' => {
                p.i += 1;
                out.push('.');
                last = Last::Atom;
            }
            _ => {
                p.i += 1;
                out.push_str(&hex_lit(c));
                last = Last::Atom;
            }
        }
    }
    if let Some(open) = stack.last() {
        return Err(err("missing ), unterminated subpattern", *open));
    }
    Ok(if global_flags.is_empty() { out } else { format!("(?{global_flags}){out}") })
}

/// Çevrilmiş deseni derle (Python'un kabul ettiği ama fancy-regex'in reddettiği nadir durumda fancy iletisi).
pub fn compile(pat: &str, wrap: impl Fn(&str) -> String) -> Result<fancy_regex::Regex, String> {
    let t = translate(pat)?;
    fancy_regex::Regex::new(&wrap(&t)).map_err(|e| e.to_string())
}
