//! Sahip kuralı (25 Kas 2026): yeni geliştirmelerin hepsi Rust; Python'a yalnız hata düzeltmesi.
//! Burası saf karar: commit mesajı + değişiklik listesi -> ret nedenleri ve uyarılar. git çağrısı `main.rs`te.

/// Kuralın kapsadığı Python ağaçları (çekirdek ve enterprise).
const SCOPES: [&str; 2] = ["py/", "claudeops_enterprise/"];
const TRAILER: &str = "Python-exception:";
/// TBD bölümünde sahibin onayını gösteren satır başı. "(sahip adına ...)" bilerek eşleşmez.
pub const APPROVAL: &str = "Python-istisnası: ONAYLI (sahip,";

#[derive(Debug, Clone, PartialEq)]
pub struct FileStat {
    pub path: String,
    pub added: u64,
    pub deleted: u64,
}

#[derive(Debug, Default, PartialEq)]
pub struct Verdict {
    pub errors: Vec<String>,
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Kind {
    Feat,
    Fix,
    Other,
}

/// Mesajın yorum olmayan satırları (`git commit -v` makas çizgisinden sonrası atılır).
fn message_lines(msg: &str) -> impl Iterator<Item = &str> {
    msg.lines()
        .take_while(|l| !(l.starts_with('#') && l.contains(">8")))
        .filter(|l| !l.starts_with('#'))
}

pub fn kind(msg: &str) -> Kind {
    let mut subject = message_lines(msg)
        .map(str::trim)
        .find(|l| !l.is_empty())
        .unwrap_or("");
    for p in ["fixup! ", "squash! ", "amend! "] {
        while let Some(rest) = subject.strip_prefix(p) {
            subject = rest;
        }
    }
    let low = subject.to_ascii_lowercase();
    let is = |t: &str| {
        low.strip_prefix(t)
            .is_some_and(|r| r.starts_with(['(', ':', '!']))
    };
    if is("feat") {
        Kind::Feat
    } else if is("fix") {
        Kind::Fix
    } else {
        Kind::Other
    }
}

/// `Python-exception: TBD#<n>` trailer'larındaki numaralar.
pub fn exception_ids(msg: &str) -> Vec<u32> {
    message_lines(msg)
        .filter_map(|l| l.strip_prefix(TRAILER))
        .filter_map(|v| v.trim().strip_prefix("TBD#"))
        .filter_map(|n| n.trim().parse().ok())
        .collect()
}

/// `## #<n> ...` ya da `### <n>) ...` başlıklı bölümde onay satırı var mı.
pub fn approved(tbd: &str, id: u32) -> bool {
    let (a, b) = (format!("## #{id} "), format!("### {id})"));
    let mut inside = false;
    for line in tbd.lines() {
        if line.starts_with("## ") || line.starts_with("### ") {
            inside = line.starts_with(&a) || line.starts_with(&b);
        } else if inside
            && line
                .trim_start_matches(['-', ' ', '*'])
                .starts_with(APPROVAL)
        {
            return true;
        }
    }
    false
}

fn in_scope(path: &str) -> bool {
    path.ends_with(".py") && SCOPES.iter().any(|s| path.starts_with(s))
}

fn is_test(path: &str) -> bool {
    path.starts_with("py/tests/") || path.contains("/tests/")
}

fn def_name(line: &str) -> Option<&str> {
    // yalnız modül düzeyi ve sınıf yöntemi (en çok 4 boşluk girinti); iç işlevler public sayılmaz
    let body = line.trim_start_matches(' ');
    if line.len() - body.len() > 4 {
        return None;
    }
    let rest = body
        .strip_prefix("async ")
        .unwrap_or(body)
        .strip_prefix("def ")?;
    let name = &rest[..rest.find('(')?];
    (!name.starts_with('_') && !name.starts_with("test")).then_some(name)
}

fn api_literals(line: &str) -> impl Iterator<Item = &str> {
    line.split(['"', '\''])
        .skip(1)
        .step_by(2)
        .filter(|s| s.starts_with("/api/"))
}

/// `git diff -U0` çıktısından kapsamdaki (test olmayan) dosyalarda yeni public işlev ve uç adları.
pub fn new_public(diff: &str) -> Vec<String> {
    let (mut added, mut removed) = (Vec::new(), Vec::new());
    let mut take = false;
    let mut in_header = false;
    for line in diff.lines() {
        if line.starts_with("diff --git ") {
            in_header = true;
            take = false;
        } else if in_header {
            if let Some(p) = line.strip_prefix("+++ b/") {
                take = in_scope(p) && !is_test(p);
            }
            in_header = !line.starts_with("@@");
        } else if take {
            if let Some(l) = line.strip_prefix('+') {
                added.push(l);
            } else if let Some(l) = line.strip_prefix('-') {
                removed.push(l);
            }
        }
    }
    let old_defs: Vec<&str> = removed.iter().filter_map(|l| def_name(l)).collect();
    let old_apis: Vec<&str> = removed.iter().flat_map(|l| api_literals(l)).collect();
    let mut out: Vec<String> = added
        .iter()
        .filter_map(|l| def_name(l))
        .filter(|n| !old_defs.contains(n))
        .map(|n| format!("işlev {n}"))
        .chain(
            added
                .iter()
                .flat_map(|l| api_literals(l))
                .filter(|a| !old_apis.contains(a))
                .map(|a| format!("uç {a}")),
        )
        .collect();
    out.sort();
    out.dedup();
    out
}

/// Tek commit'in kararı. `tbd`: TOBEDECIDED.md içeriği (okunamadıysa `None`: istisna kabul edilmez).
pub fn evaluate(msg: &str, files: &[FileStat], diff: &str, tbd: Option<&str>) -> Verdict {
    let mut v = Verdict::default();
    match kind(msg) {
        Kind::Feat => {
            let grown: Vec<&str> = files
                .iter()
                .filter(|f| in_scope(&f.path) && f.added > f.deleted)
                .map(|f| f.path.as_str())
                .collect();
            if grown.is_empty() {
                return v;
            }
            let ids = exception_ids(msg);
            if let Some(id) = ids.iter().find(|&&id| tbd.is_some_and(|t| approved(t, id))) {
                v.warnings.push(format!(
                    "Python istisnası TBD#{id} ile geçti: {}",
                    grown.join(", ")
                ));
                return v;
            }
            let why = match (ids.first(), tbd) {
                (None, _) => format!("trailer yok ('{TRAILER} TBD#<n>')"),
                (Some(_), None) => "TOBEDECIDED.md okunamadı".to_string(),
                (Some(id), Some(_)) => format!(
                    "TBD#{id} sahip onaylı değil (bölümde '{APPROVAL} <tarih>)' satırı yok)"
                ),
            };
            v.errors.push(format!(
                "feat commit'i Python büyütüyor: {}. Yeni geliştirme Rust'ta yazılır; {why}.",
                grown.join(", ")
            ));
        }
        Kind::Fix => {
            let new = new_public(diff);
            if !new.is_empty() {
                v.warnings.push(format!(
                    "fix commit'i Python'a yeni public yüzey ekliyor: {}. Özellikse Rust'ta yaz.",
                    new.join(", ")
                ));
            }
        }
        Kind::Other => {}
    }
    v
}

/// `git diff --numstat -z -M` çıktısı. İkili dosya ("-") 0 sayılır; yeniden adlandırmada yeni yol alınır.
pub fn parse_numstat(raw: &str) -> Vec<FileStat> {
    let mut out = Vec::new();
    let mut it = raw.split('\0');
    while let Some(rec) = it.next() {
        let mut cols = rec.splitn(3, '\t');
        let (Some(a), Some(d), Some(p)) = (cols.next(), cols.next(), cols.next()) else {
            continue;
        };
        let path = if p.is_empty() {
            let _old = it.next();
            it.next().unwrap_or("")
        } else {
            p
        };
        out.push(FileStat {
            path: path.to_string(),
            added: a.trim().parse().unwrap_or(0),
            deleted: d.parse().unwrap_or(0),
        });
    }
    out
}
