//! İletilemeyen sahip cevabının ve direktifin TODO/TOBEDECIDED içeriğine eklenmesi (grup 1, SAF metin işlevleri).

use crate::consts_gen::{P_ITEM_START_RE, P_TBD_ID_RE};
use crate::pyc;
use std::sync::LazyLock;

type Fancy = LazyLock<Option<fancy_regex::Regex>>;
static TBD_ID_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_TBD_ID_RE.as_str()));
static ITEM_START_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_ITEM_START_RE.as_str()));
// satır içi desen: `^- \[ \] \([^)]*direktif [0-9a-f]+\) (.*)$`
static OPEN_DIRECTIVE_RE: Fancy = LazyLock::new(|| pyc::py_regex(r"^- \[ \] \([^)]*direktif [0-9a-f]+\) (.*)$"));

fn collapsed_head(text: &str, n: usize) -> String {
    pyc::head(&pyc::collapse_ws(text), n).to_string()
}

/// Girinti (kod noktası): `len(ln) - len(ln.lstrip())`
fn indent_of(line: &str) -> usize {
    pyc::len(line) - pyc::len(pyc::lstrip(line))
}

/// `mm and len(mm.group(1)) <= ind`: aynı ya da daha az girintili madde/başlık başlangıcı.
fn starts_sibling(line: &str, indent: usize) -> bool {
    ITEM_START_RE
        .as_ref()
        .and_then(|r| r.captures(line).ok().flatten())
        .is_some_and(|c| c.get(1).map_or(0, |g| pyc::len(g.as_str())) <= indent)
}

/// İletilemeyen sahip cevabını TOBEDECIDED.md içeriğine ekler: sorudaki `TBD#N`in geçtiği maddenin bloğunun altına,
/// bulunamazsa dosyanın sonuna. Aynı soru kimliği zaten varsa `None`.
///
/// py: tbd_insert_answer
pub fn tbd_insert_answer(text: &str, qid: &str, q_text: &str, answer: &str, date: &str) -> Option<String> {
    if !qid.is_empty() && text.contains(&format!("[{qid}]")) {
        return None;
    }
    let ans = collapsed_head(answer, 1500);
    let mut lines: Vec<String> = text.split('\n').map(str::to_string).collect();
    for m in TBD_ID_RE.iter().flat_map(|r| r.captures_iter(q_text)).map_while(Result::ok) {
        let n = m.get(1).map_or("", |g| g.as_str());
        let Some(pat) = pyc::py_regex(&format!(r"(?i)TBD\s*#?\s*{n}(?!\d)")) else {
            continue;
        };
        let found = lines.iter().position(|ln| pat.is_match(ln).unwrap_or(false));
        let Some(i) = found else {
            continue;
        };
        let ind = lines.get(i).map_or(0, |l| indent_of(l));
        let mut j = i + 1;
        while lines.get(j).is_some_and(|l| !starts_sibling(l, ind)) {
            j += 1;
        }
        while j > i + 1 && lines.get(j - 1).is_some_and(|l| pyc::strip(l).is_empty()) {
            j -= 1; // bloğun sonundaki boş satırların ÜSTÜNE
        }
        let pad = " ".repeat(ind + 2);
        lines.insert(j.min(lines.len()), format!("{pad}- Sahip cevabı ({date}, değnekçi) [{qid}]: {ans}"));
        return Some(lines.join("\n"));
    }
    let body = text.trim_end_matches('\n');
    let head = if body.is_empty() { String::new() } else { format!("{body}\n\n") };
    let q = collapsed_head(q_text, 140);
    Some(format!("{head}- Sahip cevabı ({date}, değnekçi) [{qid}] (soru: {q}): {ans}\n"))
}

/// Cevap bir EYLEM taşıyor mu: 4+ sözcük ya da 40+ karakter.
///
/// py: answer_has_action
pub fn answer_has_action(answer: &str) -> bool {
    let a = pyc::collapse_ws(answer);
    pyc::split_ws(&a).count() >= 4 || pyc::len(&a) >= 40
}

/// TODO.md içeriğine direktif satırı ekler. Aynı kimlik ya da aynı özet açık satırsa `None`.
///
/// py: todo_insert_directive
pub fn todo_insert_directive(body: &str, did: &str, summary: &str, date: &str) -> Option<String> {
    if body.contains(&format!("direktif {did})")) || body.contains(&format!("direktif {did},")) {
        return None;
    }
    let duplicate = pyc::splitlines(body).into_iter().any(|ln| {
        OPEN_DIRECTIVE_RE
            .as_ref()
            .and_then(|r| r.captures(ln).ok().flatten())
            .is_some_and(|c| c.get(1).is_some_and(|g| pyc::collapse_ws(g.as_str()) == summary))
    });
    if duplicate {
        return None;
    }
    let sep = if body.ends_with('\n') || body.is_empty() { "" } else { "\n" };
    Some(format!("{body}{sep}- [ ] ({date}, direktif {did}) {summary}\n"))
}

/// TODO.md içeriğine `(sahip cevabı <qid>)` satırı ekler. Aynı kimlik zaten varsa `None`.
///
/// py: todo_insert_answer
pub fn todo_insert_answer(text: &str, qid: &str, answer: &str, date: &str) -> Option<String> {
    if !qid.is_empty() && text.contains(&format!("(sahip cevabı {qid},")) {
        return None;
    }
    let ans = collapsed_head(answer, 600);
    let body = text.trim_end_matches('\n');
    let sep = if body.is_empty() { "" } else { "\n" };
    Some(format!("{body}{sep}- [ ] (sahip cevabı {qid}, {date}) {ans}\n"))
}
