//! Soru bildirimi, bekleyen soru özeti, `/q/<id>` sayfası ve devir notu (grup 1, SAF metin üreticileri).

use crate::consts_gen::*;
use crate::identity::normalize_host;
use crate::pyc;
use crate::types::Question;
use indexmap::IndexMap;
use serde_json::Value;
use std::collections::BTreeSet;

/// Telefon sayfası bağlantısı; taban ya da soru anahtarı yoksa "".
///
/// py: question_link
pub fn question_link(q: &Question, base: &str, sid: &str) -> String {
    let base = base.trim_end_matches('/');
    if base.is_empty() || q.key.is_empty() {
        return String::new();
    }
    let suffix = if sid == "default" { String::new() } else { format!("&s={sid}") };
    format!("{base}/q/{}?k={}{suffix}", q.id, q.key)
}

/// CLI cevap ipucu.
///
/// py: ask_hint
pub fn ask_hint(question_id: &str, sid: &str) -> String {
    let flag = if sid == "default" { String::new() } else { format!(" -s {sid}") };
    format!("py/cops steward{flag} answer {question_id} \"...\"")
}

/// ntfy gövde öneki: `[proje]`, default dışı kimlikte `[<sid>/<proje>]`; uzak projede `proje@host`.
///
/// py: ask_prefix
pub fn ask_prefix(project: &str, sid: &str, host: &str) -> String {
    let h = normalize_host(&Value::from(host));
    let mut name = if project.is_empty() { "degnekci".to_string() } else { project.to_string() };
    if !h.is_empty() && !project.is_empty() {
        name = format!("{name}@{h}");
    }
    if sid == "default" {
        format!("[{name}]")
    } else {
        format!("[{sid}/{name}]")
    }
}

/// Bugün geçmiş EN SON özet dilimi `YYYY-MM-DD@HH` ("" = henüz yok). Yerel saat. `hours` varsayılanı
/// `PENDING_DIGEST_HOURS`.
///
/// py: pending_digest_slot
pub fn pending_digest_slot(now: f64, hours: &[i64]) -> String {
    let lt = pyc::localtime(now);
    let hour: i64 = lt.format("%H").to_string().parse().unwrap_or(0);
    let passed = hours.iter().copied().filter(|h| hour >= *h).max();
    passed.map_or_else(String::new, |h| format!("{}@{h:02}", lt.format("%Y-%m-%d")))
}

/// Açık, işleyiş OLMAYAN (ve ertelenmemiş) sahip sorularının özeti; soru yoksa "".
///
/// py: pending_digest_text
pub fn pending_digest_text(questions: &[Question], now: f64, lang: &str, sid: &str) -> String {
    let qs: Vec<&Question> = questions
        .iter()
        .filter(|q| q.status == "open" && !q.routine && !(q.deferred_until != 0.0 && q.deferred_until > now))
        .collect();
    let Some(first) = qs.first() else {
        return String::new();
    };
    // `max()`: eşitlikte ilk değer
    let oldest =
        qs.iter().map(|q| now - q.created_at).fold(now - first.created_at, |a, b| if b > a { b } else { a }) / 3600.0;
    let unnotified = qs.iter().filter(|q| q.notified_at == 0.0).count();
    let mut per: IndexMap<&str, usize> = IndexMap::new();
    for q in &qs {
        let key = if q.project.is_empty() { "-" } else { q.project.as_str() };
        *per.entry(key).or_insert(0) += 1;
    }
    let mut counts: Vec<(&str, usize)> = per.into_iter().collect();
    counts.sort_by_key(|(_, n)| std::cmp::Reverse(*n));
    let top: Vec<String> = counts.iter().take(5).map(|(k, v)| format!("{k}:{v}")).collect();
    let top = top.join(", ");
    let flag = if sid == "default" { String::new() } else { format!(" -s {sid}") };
    let hint = format!("py/cops steward questions{flag}");
    let n = qs.len();
    if lang == "en" {
        format!(
            "{n} owner question(s) waiting (oldest {oldest:.0} h; {unnotified} never sent to your phone). \
             By project: {top}. → {hint}"
        )
    } else {
        format!(
            "Sahibin cevabını bekleyen {n} soru var (en eskisi {oldest:.0} sa; {unnotified} tanesi telefona hiç gitmedi). \
             Proje başına: {top}. → {hint}"
        )
    }
}

/// ntfy gövdesi: önek + soru, numaralı seçenekler, bağlantı ya da CLI ipucu.
///
/// py: question_notification
pub fn question_notification(q: &Question, link: &str, lang: &str, sid: &str, host: &str) -> String {
    let mut lines = vec![format!("{} {}", ask_prefix(&q.project, sid, host), q.text)];
    lines.extend(q.options.iter().enumerate().map(|(i, o)| format!("{}) {o}", i + 1)));
    if link.is_empty() {
        lines.push(format!("→ {}", ask_hint(&q.id, sid)));
    } else {
        lines.push(format!("{}{link}", if lang != "en" { "→ cevapla: " } else { "→ answer: " }));
    }
    lines.join("\n")
}

/// `html.escape(s)` (tırnaklar dahil)
fn esc(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;").replace('\'', "&#x27;")
}

/// `/q/<id>` kompakt mobil sayfası. `state`: ask | done | already | missing | denied.
///
/// py: question_page_html
pub fn question_page_html(q: Option<&Question>, lang: &str, state: &str, error: &str, action: &str) -> String {
    let code = if lang == "en" { "en" } else { "tr" };
    let t = |key: &str| P_QPAGE_TXT.get(code).and_then(|m| m.get(key)).and_then(Value::as_str).unwrap_or_default();
    let mut body: Vec<String> = vec![format!("<h1>{}</h1>", t("title"))];
    match q.filter(|_| state != "missing" && state != "denied") {
        None => body.push(format!("<p class='err'>{}</p>", t(if state != "denied" { "missing" } else { "denied" }))),
        Some(q) => {
            body.push(format!("<p class='q'>{}</p>", esc(&q.text)));
            if !q.detail.is_empty() {
                body.push(format!(
                    "<details><summary class='meta'>{}</summary><div class='q' style='white-space:pre-wrap'>{}</div></details>",
                    t("detail"),
                    esc(&q.detail)
                ));
            }
            let paragraphs = |items: &[String], class: &str| -> String {
                items.iter().map(|x| format!("<p class='{class}'>{}</p>", esc(x))).collect()
            };
            if !q.extra_texts.is_empty() {
                body.push(format!(
                    "<details open><summary class='meta'>{} ({})</summary>{}</details>",
                    t("extra"),
                    q.extra_texts.len(),
                    paragraphs(&q.extra_texts, "q")
                ));
            }
            if !q.prev_texts.is_empty() {
                body.push(format!(
                    "<details><summary class='meta'>{} ({})</summary>{}</details>",
                    t("prev"),
                    q.prev_texts.len(),
                    paragraphs(&q.prev_texts, "meta")
                ));
            }
            let when = if q.created_at != 0.0 {
                pyc::localtime(q.created_at).format("%Y-%m-%d %H:%M").to_string()
            } else {
                String::new()
            };
            let project = if q.project.is_empty() { "degnekci" } else { &q.project };
            let by = if q.source.is_empty() { String::new() } else { format!(" · {}: {}", t("by"), esc(&q.source)) };
            body.push(format!(
                "<p class='meta'>{}: <b>{}</b> · {}: {when}{by}</p>",
                t("project"),
                esc(project),
                t("asked")
            ));
            if state == "done" || state == "already" {
                body.push(format!("<p class='ok'>{}</p>", t(if state == "done" { "done" } else { "already" })));
                body.push(format!("<p class='ans'>→ {}</p>", esc(&q.answer)));
                if state == "done" {
                    body.push(format!("<p class='meta'>{}</p>", t("deliver")));
                }
            } else {
                if !error.is_empty() {
                    body.push(format!("<p class='err'>{}</p>", esc(error)));
                }
                body.push(format!("<form method='post' action='{}'>", esc(action)));
                if !q.options.is_empty() {
                    body.push(format!("<p class='meta'>{}</p>", t("opts_hint")));
                    for o in &q.options {
                        let o = esc(o);
                        body.push(format!("<button class='opt' type='submit' name='answer' value='{o}'>{o}</button>"));
                    }
                }
                body.push(format!(
                    "<div class='row'><input name='answer' placeholder='{}' autocomplete='off'><button class='send' type='submit'>{}</button></div></form>",
                    esc(t("free")),
                    t("send")
                ));
            }
        }
    }
    format!(
        "<!doctype html><html lang='{code}'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='robots' content='noindex'><title>{}</title><style>{P_QPAGE_CSS}</style></head><body><div class='card'>{}</div></body></html>",
        t("title"),
        body.concat()
    )
}

/// Devir mesajına eklenecek "sorduğum AÇIK sorular" bölümü; açık soru yoksa "".
///
/// py: handover_questions_note
pub fn handover_questions_note(questions: &[Question], name: &str, lang: &str, project: &str) -> String {
    let keys: BTreeSet<&str> = [name, project].into_iter().filter(|k| !k.is_empty()).collect();
    let mut rows: Vec<&Question> = questions
        .iter()
        .filter(|q| q.status == "open" && (keys.contains(q.source.as_str()) || keys.contains(q.project.as_str())))
        .collect();
    if rows.is_empty() {
        return String::new();
    }
    rows.sort_by(|a, b| a.created_at.partial_cmp(&b.created_at).unwrap_or(std::cmp::Ordering::Equal));
    let max = HANDOVER_QUESTION_CHARS as usize;
    let lines: Vec<String> = rows
        .iter()
        .take(HANDOVER_QUESTIONS_MAX as usize)
        .map(|q| {
            let mut text = pyc::collapse_ws(&q.text);
            if pyc::len(&text) > max {
                text = format!("{}…", pyc::head(&text, max - 1));
            }
            let again = match q.asked_again {
                0 => String::new(),
                n if lang != "en" => format!(" (+{n} kez yeniden soruldu)"),
                n => format!(" (+{n} re-asks)"),
            };
            format!("- [{}] {text}{again}", q.id)
        })
        .collect();
    let more = rows.len() - lines.len();
    let (head, tail) = if lang == "en" {
        (
            "OPEN QUESTIONS I asked (still unanswered; the new session must NOT ask them again, the steward delivers \
             the answer). Copy them under a \"## Open questions\" line in your READY FOR HANDOVER summary:",
            format!("\n- … and {more} more"),
        )
    } else {
        (
            "Sorduğum AÇIK sorular (hâlâ cevapsız; yeni oturum AYNISINI yeniden SORMASIN, cevabı değnekçi iletir). \
             READY FOR HANDOVER özetine \"## Açık sorular\" başlığıyla aynen kopyala:",
            format!("\n- … ve {more} soru daha"),
        )
    };
    let tail = if more > 0 { tail } else { String::new() };
    format!("{head}\n{}{tail}", lines.join("\n"))
}
