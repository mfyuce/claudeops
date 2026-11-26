//! Bulgu durum makinesi (saf): `new -> verify_sent -> verified|refuted|unclear -> approved|rejected -> exported` (+ `dup`).
use crate::badrec;
use crate::error::Result;
use crate::parse::{Verdict, VERDICTS, VERDICT_MARK, VERDICT_REASON_MAX};
use crate::py;
use crate::targets::{slug_model, MODES};
use cops_state::json::{Json, Map};
use sha1::{Digest, Sha1};

/// Doğrulama direktifi gönderilebilen durumlar.
pub const VERIFIABLE_STATES: [&str; 3] = ["new", "verify_sent", "unclear"];
/// `approve` edilebilen durumlar.
pub const APPROVABLE_STATES: [&str; 2] = ["verified", "unclear"];
/// `reject` edilebilen durumlar.
pub const REJECTABLE_STATES: [&str; 5] = ["new", "verify_sent", "verified", "refuted", "unclear"];
pub const VERIFY_MAX_FINDINGS: usize = 20;
pub const VERIFY_REQUEUE_SECONDS: f64 = 6.0 * 3600.0;
pub const VERIFY_MAX_TRIES: i64 = 3;

pub fn sha1_hex(bytes: &[u8]) -> String {
    Sha1::digest(bytes).iter().map(|b| format!("{b:02x}")).collect()
}

pub fn text_hash(text: &str) -> String {
    sha1_hex(text.as_bytes())
}

/// Rapor yolundan üreten modelin slug'ı (`-sub` atılır); çözülemezse "".
pub fn reviewer_slug_of(review_file: &str) -> String {
    let norm = review_file.replace('\\', "/");
    let parts: Vec<&str> = norm.split('/').collect();
    for i in 0..parts.len().saturating_sub(1) {
        if MODES.contains(&parts[i]) && i + 1 < parts.len() - 1 {
            return parts[i + 1].strip_suffix("-sub").unwrap_or(parts[i + 1]).to_string();
        }
    }
    String::new()
}

/// `findings`i yerinde günceller; uygulanan fid'ler döner.
pub fn apply_verdicts(
    findings: &mut Map,
    project: &str,
    verdicts: &[Verdict],
    src_hash: &str,
    session: &str,
    now: f64,
    verifier: &str,
) -> Vec<String> {
    let mut applied = Vec::new();
    for v in verdicts {
        let Some(rec) = findings.get_mut(&v.fid).and_then(Json::as_object_mut) else { continue };
        if !py::is_str(rec.get("project"), project) || !py::is_str(rec.get("state"), "verify_sent") {
            continue;
        }
        if !VERDICTS.contains(&v.verdict.as_str())
            || py::is_str(rec.get("verify_baseline"), src_hash)
            || py::is_str(rec.get("verdict_src"), src_hash)
        {
            continue;
        }
        rec.insert("state".into(), v.verdict.as_str().into());
        rec.insert("verdict".into(), v.reason.as_str().into());
        rec.insert("verdict_at".into(), Json::Float(now));
        rec.insert("verdict_session".into(), session.into());
        rec.insert("verdict_src".into(), src_hash.into());
        if !verifier.is_empty()
            && reviewer_slug_of(&py::str_or_empty(rec.get("review_file"))) == slug_model(verifier)
        {
            rec.insert("same_model".into(), Json::Bool(true));
            let text = format!("{} [aynı model doğruladı]", v.reason);
            rec.insert("verdict".into(), py::head(&text, VERDICT_REASON_MAX + 24).into());
        }
        applied.push(v.fid.clone());
    }
    applied
}

/// Karar/dışa aktarma `state`i ezmeden ÖNCE doğrulama sonucunu `verdict_state`e alır (Python `_keep_verdict_state`).
pub fn keep_verdict_state(rec: &mut Map) {
    let state = rec.get("state");
    if py::str_in(state, &VERDICTS) {
        if let Some(state) = state.cloned() {
            rec.insert("verdict_state".into(), state);
        }
    }
}

/// Cevapsız kalan oturum doğrulamalarını yeniden sıraya alır (deneme dolunca `unclear`).
pub fn requeue_stale_verify(findings: &mut Map, now: f64, stale: f64) -> Result<Vec<String>> {
    let mut out = Vec::new();
    for (fid, rec) in findings.iter_mut() {
        let Some(rec) = rec.as_object_mut() else { continue };
        if !py::is_str(rec.get("state"), "verify_sent") || py::is_str(rec.get("verify_session"), "self") {
            continue;
        }
        let Some(sent) = badrec::field(rec, "verify_sent_at", "findings", fid) else { continue };
        if now - sent < stale {
            continue;
        }
        let Some(done) = badrec::field(rec, "verify_tries", "findings", fid) else { continue };
        let tries = (done.trunc() as i64).saturating_add(1);
        if tries >= VERIFY_MAX_TRIES {
            rec.insert("state".into(), "unclear".into());
            rec.insert("verify_tries".into(), Json::Int(tries));
            rec.insert("verdict_at".into(), Json::Float(now));
            let text = format!("doğrulama {tries} gönderimde sonuç vermedi (karar son mesajda görülmedi)");
            rec.insert("verdict".into(), py::head(&text, VERDICT_REASON_MAX).into());
        } else {
            rec.insert("state".into(), "new".into());
            rec.insert("verify_tries".into(), Json::Int(tries));
        }
        out.push(fid.clone());
    }
    Ok(out)
}

fn verify_items(rows: &[Map]) -> Result<String> {
    let mut items = Vec::new();
    for r in rows {
        let id = crate::export::row_id(r)?;
        let or_q = |k: &str| {
            let v = r.get(k);
            if py::truthy(v) {
                py::str_or_empty(v)
            } else {
                "?".to_string()
            }
        };
        let title = py::collapse_ws(&py::str_or_empty(r.get("title")));
        items.push(format!("- {id} | {} | {} | {}", or_q("severity"), or_q("where"), py::head(&title, 200)));
    }
    Ok(items.join("\n"))
}

/// Proje oturumuna giden doğrulama direktifi.
pub fn build_verify_message(rows: &[Map], lang: &str) -> Result<String> {
    let items = verify_items(rows)?;
    Ok(if lang == "en" {
        format!(
            concat!(
                "An independent code review reported the findings below. Start a Sonnet sub-agent (model: sonnet) and ",
                "have it check EACH finding against the current code. Do NOT fix anything, do not edit files, do not ",
                "commit.\nFindings (id | severity | location | title):\n{items}\n",
                "At the END of your answer write one line per finding, at the very start of the line (not inside a code ",
                "block or a quote):\n",
                "{mark} <id> verified|refuted|unclear <one-sentence reason>"
            ),
            items = items,
            mark = VERDICT_MARK
        )
    } else {
        format!(
            concat!(
                "Bağımsız bir kod incelemesi aşağıdaki bulguları raporladı. Bir Sonnet alt ajanı (model: sonnet) başlat ve ",
                "HER bulguyu güncel koda karşı doğrulat. Düzeltme YAPMA, dosya değiştirme, commit etme.\n",
                "Bulgular (kimlik | önem | yer | başlık):\n{items}\n",
                "Cevabının SONUNDA her bulgu için ayrı bir satır yaz, satırın EN BAŞINDA (kod bloğu ya da alıntı içinde ",
                "değil):\n",
                "{mark} <kimlik> verified|refuted|unclear <tek cümlelik gerekçe>"
            ),
            items = items,
            mark = VERDICT_MARK
        )
    })
}

/// Reviewer'ın kendi salt-okunur doğrulayıcısına giden istem.
pub fn build_self_verify_prompt(rows: &[Map], lang: &str) -> Result<String> {
    let items = verify_items(rows)?;
    Ok(if lang == "en" {
        format!(
            concat!(
                "An independent code review reported the findings below. Check EACH one against the CURRENT code in this ",
                "directory (read-only: Read/Grep/Glob). Do not edit anything. A finding is `verified` when the code really ",
                "shows it, `refuted` when the code contradicts it, `unclear` when you cannot tell.\nFindings (id | severity | ",
                "location | title):\n{items}\nAt the END write one line per finding, at the very start of the line ",
                "(not inside a code block or quote):\n{mark} <id> verified|refuted|unclear <one-sentence reason>"
            ),
            items = items,
            mark = VERDICT_MARK
        )
    } else {
        format!(
            concat!(
                "Bağımsız bir kod incelemesi aşağıdaki bulguları raporladı. HER birini bu klasördeki GÜNCEL koda karşı kontrol et ",
                "(salt okunur: Read/Grep/Glob). Hiçbir şeyi değiştirme. Kod bulguyu gerçekten gösteriyorsa `verified`, koda ",
                "aykırıysa `refuted`, karar veremiyorsan `unclear`.\nBulgular (kimlik | önem | yer | başlık):\n{items}\n",
                "SONUNDA her bulgu için ayrı bir satır yaz, satırın EN BAŞINDA (kod bloğu ya da alıntı içinde değil):\n",
                "{mark} <kimlik> verified|refuted|unclear <tek cümlelik gerekçe>"
            ),
            items = items,
            mark = VERDICT_MARK
        )
    })
}
