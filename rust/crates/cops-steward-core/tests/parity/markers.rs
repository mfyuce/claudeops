//! Grup B (işaret taraması, yanıt dili) paritesi. Beklenen değerler Python işlevleri çalıştırılarak alındı.
use crate::harness::{parity, same};
use cops_steward_core::markers::*;
use cops_steward_core::pyc::collapse_ws;
use cops_steward_core::types::*;
use serde_json::{json, Map, Value};

parity!("needs_ho.rfh_marker_in", needs_ho_rfh_marker_in, |c| {
    rfh_marker_in(&c.opt::<String>("text").unwrap_or_default())
});
parity!("_unwrap_ticks", p_unwrap_ticks, |c| unwrap_ticks(&c.str("prefix"), &c.str("body")).to_string());
parity!("count_open_tbd", count_open_tbd_vectors, |c| count_open_tbd(&c.opt::<String>("text").unwrap_or_default()));
parity!("done_blocked", done_blocked_vectors, |c| done_blocked(c.opt::<Project>("project").as_ref()));
parity!("_bare_marker", p_bare_marker, |c| bare_marker(&c.str("line"), &c.str("mark")));
parity!("_is_no_work_value", p_is_no_work_value, |c| is_no_work(&c.str("value")));
/// Beklenen değerler `py/tests/test_steward_review_notes.py` ile aynı.
/// py: _is_no_work_value
#[test]
fn done_then_work_is_work() {
    for v in [
        "bitti, şimdi testleri koş",
        "done; next: fix lint",
        "Bitti. Sıradaki iş: raporu yaz",
        "**bitti**, sırada F5 düzeltmesi",
        "done - now run the tests",
        "bitti; ŞİMDİ: eşlik koşusu",
        "done, then update the docs",
    ] {
        assert!(!is_no_work(v), "{v}");
        assert_eq!(marker_next_work(&format!("Rapor.\nSTEWARD-NEXT: {v}")), v);
    }
    for v in [
        "bitti, şimdi yok",
        "done; next: none",
        "done; next: -",
        "bitti, sıradaki: yok",
        "bitti, şimdi.",
        "done, now waiting",
        "bitti, şimdi bekliyorum",
        "bitti, sırada iş yok",
        "done, next: done",
        "done, nothing now",
        "bitti, kalanlar TBD'de",
        "bitti (devir yazıldı)",
        "bitti, şimdilik bu kadar",
        "done, nowhere else to go",
        "bitti, sonrası sahipte",
    ] {
        assert!(is_no_work(v), "{v}");
    }
}

parity!("scan_markers", scan_markers_vectors, |c| scan_markers(&c.opt::<String>("text").unwrap_or_default()));
parity!("_is_confirm_line", is_confirm_line_vectors, |c| is_confirm_line(&c.str("prefix"), &c.str("tail")));
parity!("reply_language_line", reply_language_line_vectors, |c| { reply_language_line(&c.str("lang")) });
parity!("text_lang_mismatch", text_lang_mismatch_vectors, |c| {
    text_lang_mismatch(&c.opt::<String>("text").unwrap_or_default(), &c.str("lang"))
});
parity!("marker_texts", marker_texts_vectors, |c| marker_texts(&c.arg("m")));
parity!("lang_fix_action", lang_fix_action_vectors, |c| {
    let before: Map<String, Value> = c.arg("state");
    let mut state = before.clone();
    let got = lang_fix_action(&c.str("name"), &c.str("proj"), &c.str("text"), &c.arg("cfg"), &mut state, c.arg("now"))
        .expect("durum");
    // Python `state`i yerinde değiştirir; değişmediyse vektörde `after` yoktur
    let want = c.after.get("state").cloned().unwrap_or(Value::Object(before));
    assert!(same(&Value::Object(state), &want), "state farkı: {want}");
    got
});

/// (ad, metin, Python `scan_markers` sonucu)
const CORPUS: &[(&str, &str, &str)] = &[
    ("empty", "", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("only_newlines", "\n\r\n\n", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("plain", "STEWARD-ASK: hangisi?\nSTEWARD-IDEA: yeni fikir\nSTEWARD-NEXT: TODO 3\nSTEWARD-NEXT: yok", "{\"asks\": [\"hangisi?\"], \"routines\": [], \"ideas\": [\"yeni fikir\"], \"blocked\": [], \"jobs\": [], \"nexts\": [\"TODO 3\", \"yok\"], \"next\": \"yok\", \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("fenced", "```\nSTEWARD-ASK: örnek\nSTEWARD-DONE\n```\nson", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("fenced_indented_lang", "  ```text\nSTEWARD-BLOCKED: x\n  ```\nSTEWARD-IDEA: dışarıda", "{\"asks\": [], \"routines\": [], \"ideas\": [\"dışarıda\"], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("fence_unclosed", "```\nSTEWARD-ASK: a\nSTEWARD-DONE-CONFIRMED abc1234 0", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("fence_cuts_cont", "STEWARD-ASK: seçenekler:\n```\nkod\n```\n- a", "{\"asks\": [\"seçenekler:\"], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("quote", "> STEWARD-ASK: alıntı\n   > STEWARD-DONE\n>STEWARD-PLAN-READY", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("quote_inside_cont", "STEWARD-ASK: şunlar:\n> alıntı\n- a\n- b\n\n- c", "{\"asks\": [\"şunlar: a b\"], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("placeholder", "STEWARD-ASK: <soru>\nSTEWARD-BLOCKED: <nerede takıldın>`.\nSTEWARD-IDEA: <fikir> …\nSTEWARD-DONE-CONFIRMED <hash>\nSTEWARD-ASK: <a> ya da <b>?", "{\"asks\": [\"<a> ya da <b>?\"], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("mid_sentence", "Kalan iş yok, STEWARD-DONE yazmıyorum.\nBunu STEWARD-NEXT: ile bildiririm\nAçıklama: STEWARD-ASK: ortadaki soru?\nartık ` , STEWARD-JOB: embed x\nSTEWARD-JOB: , embed\nNO-STEWARD-DONE\nxSTEWARD-DONE\nSTEWARD-DONE-X\nSTEWARD-DONE2", "{\"asks\": [\"ortadaki soru?\"], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("inline_code_mention", "Soru için `STEWARD-IDEA: <fikir>` yaz ve devam et.\nşöyle: `STEWARD-ASK: x` kullan", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("ticks", "`STEWARD-ASK: soru?`\nSTEWARD-ASK: `kod` hakkında?\nSTEWARD-IDEA: `tümü kod`\n`STEWARD-NEXT: iş`\n`STEWARD-JOB: embed a.json`\n`STEWARD-DONE`\n**STEWARD-PLAN-READY**", "{\"asks\": [\"soru?\", \"`kod` hakkında?\"], \"routines\": [], \"ideas\": [\"tümü kod\"], \"blocked\": [], \"jobs\": [\"embed a.json\"], \"nexts\": [\"iş\"], \"next\": \"iş\", \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": true, \"confirmed\": null}"),
    ("turkish", "- STEWARD-ASK: İçerik şöyle mi olsun, öneri: ığüşöç İŞ?\n• STEWARD-BLOCKED: çözemedim\n* STEWARD-ROUTINE: Şimdi açayım mı?\nSTEWARD-LESSON: l1 todo düzeltildi\nSTEWARD-JOB: çeviri dosya.txt\nSTEWARD-JOB: İndir x", "{\"asks\": [\"İçerik şöyle mi olsun, öneri: ığüşöç İŞ?\"], \"routines\": [\"Şimdi açayım mı?\"], \"ideas\": [], \"blocked\": [\"çözemedim\"], \"jobs\": [\"çeviri dosya.txt\", \"İndir x\"], \"nexts\": [], \"next\": null, \"lessons\": [\"l1 todo düzeltildi\"], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("crlf", "STEWARD-ASK: seçenekler:\r\n- bir\r\n- iki\r\n\r\nSTEWARD-DETAIL: Durum\r\n  - a\r\nSTEWARD-DONE\r\n", "{\"asks\": [\"seçenekler: bir iki\"], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [\"Durum\\n- a\"], \"plan_ready\": false, \"done\": true, \"confirmed\": null}"),
    ("cr_and_unicode_breaks", "STEWARD-IDEA: a\rSTEWARD-IDEA: b\u{2028}STEWARD-IDEA: c\u{c}STEWARD-IDEA: d\u{1c}STEWARD-IDEA: e\u{85}STEWARD-IDEA: f", "{\"asks\": [], \"routines\": [], \"ideas\": [\"a\", \"b\", \"c\", \"d\", \"e\", \"f\"], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("details", "STEWARD-ASK: uzun?\nSTEWARD-DETAIL: **Durum**\n- a\n    - girintili\nSTEWARD-NEXT: x\ndevam değil", "{\"asks\": [\"uzun?\"], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [\"x\"], \"next\": \"x\", \"lessons\": [], \"details\": [\"**Durum**\\n- a\\n- girintili\"], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("detail_empty", "STEWARD-DETAIL:\nalt satır", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("cont_interrupted", "STEWARD-BLOCKED: şu:\nSTEWARD-bilinmeyen satır\nsonraki", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [\"şu:\"], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("empty_bodies", "STEWARD-ASK:\nSTEWARD-ASK:    \nSTEWARD-NEXT: ``\nSTEWARD-IDEA: `", "{\"asks\": [], \"routines\": [], \"ideas\": [\"`\"], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("two_marks_one_line", "STEWARD-ASK: bkz STEWARD-ROUTINE: x?\nSTEWARD-IDEA: STEWARD-NEXT: y", "{\"asks\": [], \"routines\": [\"x?\"], \"ideas\": [\"STEWARD-NEXT: y\"], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("done_variants", "STEWARD-DONE: bitti\n", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": true, \"confirmed\": null}"),
    ("done_end", "STEWARD-DONE: COPS-STEWARD-END", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("done_prefix_label", "Sonuç: STEWARD-DONE\n", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": true, \"confirmed\": null}"),
    ("plan_ready", "Durum: `STEWARD-PLAN-READY`", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": true, \"done\": false, \"confirmed\": null}"),
    ("confirmed", "STEWARD-DONE-CONFIRMED abc1234 kalan açık iş 0, testler yeşil", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": \"abc1234 kalan açık iş 0, testler yeşil\"}"),
    ("confirmed_colon_empty", "STEWARD-DONE-CONFIRMED:", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": \"\"}"),
    ("confirmed_ticks", "`STEWARD-DONE-CONFIRMED abc 0`", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("confirmed_mention", "yaz: `STEWARD-DONE-CONFIRMED ...` sonra", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("confirmed_angle", "STEWARD-DONE-CONFIRMED a<b 0", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("nbsp_and_controls", "\u{a0}STEWARD-ASK:\u{a0}boşluk?\u{a0}\n\u{1f}STEWARD-IDEA: <x>\u{1f}\nSTEWARD-IDEA: <x\u{1f}y>\u{1f}.", "{\"asks\": [\"boşluk?\"], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("combining_before_done", "i̇STEWARD-DONE\nSTEWARD-DONĖ", "{\"asks\": [], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
    ("nested_bullets", "-*• - STEWARD-ASK: a\n1. STEWARD-NEXT: numaralı", "{\"asks\": [\"a\"], \"routines\": [], \"ideas\": [], \"blocked\": [], \"jobs\": [], \"nexts\": [], \"next\": null, \"lessons\": [], \"details\": [], \"plan_ready\": false, \"done\": false, \"confirmed\": null}"),
];

/// py: scan_markers
#[test]
fn scan_markers_corpus() {
    let mut bad = Vec::new();
    for (name, text, python) in CORPUS {
        let want: Value = serde_json::from_str(python).expect("beklenen");
        let got = serde_json::to_value(scan_markers(text)).expect("sonuç");
        if !same(&got, &want) {
            bad.push(format!("{name}\n  python: {want}\n  rust:   {got}"));
        }
    }
    assert!(bad.is_empty(), "{}/{} fark\n{}", bad.len(), CORPUS.len(), bad.join("\n"));
}

/// py: rfh_marker_in
#[test]
fn rfh_marker_edges() {
    for (text, want) in [
        ("", false),
        ("READY FOR HANDOVER", true),
        ("  ## **READY FOR HANDOVER** x", true),
        ("bak READY FOR HANDOVER", false),
        ("`READY FOR HANDOVER`", false),
        ("> READY FOR HANDOVER", false),
        ("```\nREADY FOR HANDOVER\n```", false),
        ("```\n```\r\nREADY FOR HANDOVER", true),
        ("\u{1f}#\u{a0}READY FOR HANDOVER", true),
        ("- READY FOR HANDOVER", false),
        ("ready for handover", false),
    ] {
        assert_eq!(rfh_marker_in(text), want, "{text:?}");
    }
}

/// py: collapse_ws
#[test]
fn collapse_ws_edges() {
    assert_eq!(collapse_ws(""), "");
    assert_eq!(collapse_ws(" a\r\n b\u{1c}\u{a0}c\u{200b}d "), "a b c\u{200b}d");
}

/// py: count_open_tbd
#[test]
fn count_open_tbd_edges() {
    for (text, want) in [
        ("", 0),
        ("### 1) a\n### 2. b\n###3) c", 2),
        ("## Açık\n### 1) a ~~\n### 2) KARAR: x\n### 3) KARARI\n### 4) ✅\n### 5) KAPANDI\n## Kapalı\n### 6) y", 1),
        ("##\u{a0}Açık\n### 1) a", 0),
        ("##\nAçık\n### 1) a", 0),
        ("## TBD#1: AÇIK\n## TBD#2: AÇIKTA\n## TBD#3 AÇIK ~~\n## TBD#4 AÇIK KARAR\n##\tTBD#5 AÇIK\r\n###\t7) z\r\n### ٣) arabic", 3),
        ("## TBD#9: AÇIK\u{307} KARAR\u{307}", 0),
    ] {
        assert_eq!(count_open_tbd(text), want, "{text:?}");
    }
}

/// py: text_lang_mismatch
#[test]
fn text_lang_mismatch_edges() {
    for (text, lang, want) in [
        ("İş İş İş İş İş İş", "en", true),
        ("İş İş İş İş İş İş", "tr", false),
        ("the and is are not with 1 2 3", "tr", true),
        ("der die das und ist nicht", "en", true),
        ("der die das und ist the", "en", false),
        ("a b c d e", "tr", false),
        ("ve bir bu one two three", "en", true),
        ("ve bir bu one two three", "xx", false),
        ("½ ² Ⅻ the and is", "tr", true),
        ("a_b_the_and_is_1x2y", "tr", true),
    ] {
        assert_eq!(text_lang_mismatch(text, lang), want, "{text:?} {lang}");
    }
}

/// py: lang_fix_action
#[test]
fn lang_fix_action_state_handling() {
    let cfg = Config::default();
    let text = "the and is are not with this";
    let run = |state: Value, name: &str| {
        let mut s = state.as_object().cloned().expect("nesne");
        let r = lang_fix_action(name, "p", text, &cfg, &mut s, 100_000.0).map(|a| a.map(|a| a.kind));
        (r, Value::Object(s))
    };
    let nudge = Ok(Some("nudge".to_string()));
    assert_eq!(run(json!({}), ""), (Ok(None), json!({})));
    for empty in [json!(null), json!([]), json!(0), json!({})] {
        assert_eq!(run(json!({"lang_fix_at": empty}), "a"), (nudge.clone(), json!({"lang_fix_at": {"a": 100_000.0}})));
    }
    assert_eq!(run(json!({"lang_fix_at": {"a": "99999"}}), "a").0, Ok(None));
    assert_eq!(run(json!({"lang_fix_at": {"a": null, "b": "x"}}), "a").0, nudge);
    assert!(run(json!({"lang_fix_at": {"a": "x"}}), "a").0.is_err());
    assert!(run(json!({"lang_fix_at": 5}), "a").0.is_err());
}
