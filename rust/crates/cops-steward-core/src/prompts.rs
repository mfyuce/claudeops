//! Prompt üreticileri ve tur hazırlığı (grup D): faz direktifi, beyin tur prompt'u, beyin `CLAUDE.md`'si, model/effort
//! seçimi, tur maddesi imzası/kesimi, bayat cevap ve not iddiası denetimi. Metinler Python ile BAYT BAYT aynıdır.

use crate::cards::{str_or_empty, BadValue};
use crate::consts_gen::*;
use crate::markers::reply_language_line;
use crate::pyc;
use crate::questions::{recent_answers, undelivered_answers};
use crate::types::{Config, Project, Question, SessionView};
use indexmap::IndexMap;
use regex::Regex;
use serde::Serialize;
use serde_json::{Map, Value};
use std::collections::BTreeSet;
use std::sync::LazyLock;

static OK_ONLY_RE: LazyLock<Option<Regex>> = LazyLock::new(|| Regex::new(r"(?i)\A(?:ok\.?|tamam\.?)\z").ok());

fn tr_en(tr: bool, t: &'static str, e: &'static str) -> &'static str {
    if tr {
        t
    } else {
        e
    }
}

/// `recent_answers`ın Python varsayılan `limit`i.
const RECENT_ANSWERS_LIMIT: i64 = 5;

// ── faz direktifi ─────────────────────────────────────────────────────────────

/// Bir proje oturumuna gönderilecek faz direktifi. `questions` = kimliğin soru deposu ("Önceki cevaplarım" buradan;
/// Python'da `paths` ile okunur).
///
/// py: build_directive
#[allow(clippy::too_many_arguments)]
pub fn build_directive(
    project: &Project,
    lang: &str,
    extra: &str,
    answer: Option<&Question>,
    more: &[Question],
    compact: bool,
    questions: &[Question],
) -> String {
    let tr = lang != "en";
    let mut parts: Vec<String> = Vec::new();
    parts.push(if tr {
        format!("[claudeops değnekçi — {}]", project.name)
    } else {
        format!("[claudeops steward — {}]", project.name)
    });
    if !project.goal.is_empty() && !compact {
        parts.push(format!("{}{}", tr_en(tr, "Amaç: ", "Goal: "), pyc::strip(&project.goal)));
    }
    let qa = |q: &Question| {
        [
            format!("{}{}", tr_en(tr, "Sorduğun soru: ", "Your question: "), pyc::strip(&q.text)),
            format!("{}{}", tr_en(tr, "Cevabım: ", "My answer: "), pyc::strip(&q.answer)),
        ]
    };
    if let Some(answer) = answer {
        parts.extend(qa(answer));
        if answer.repeats != 0 {
            parts.push(
                tr_en(
                    tr,
                    "Bunu zaten cevapladım, yukarıdaki cevap geçerli; yeniden sorma, devam et.",
                    "I already answered this; the answer above stands. Do not ask again, continue.",
                )
                .to_string(),
            );
        }
        for m in more {
            parts.extend(qa(m));
        }
        let mut prior = if compact {
            Vec::new()
        } else {
            recent_answers(&project.name, &answer.id, RECENT_ANSWERS_LIMIT, questions)
        };
        prior.retain(|q| !more.iter().any(|m| m.id == q.id));
        if !prior.is_empty() {
            let lines: Vec<String> = prior
                .iter()
                .map(|q| {
                    format!("- {} → {}", pyc::head(pyc::strip(&q.text), 140), pyc::head(pyc::strip(&q.answer), 200))
                })
                .collect();
            parts.push(format!("{}{}", tr_en(tr, "Önceki cevaplarım:\n", "My earlier answers:\n"), lines.join("\n")));
        }
    }
    if !pyc::strip(extra).is_empty() {
        parts.push(pyc::strip(extra).to_string());
    } else if compact && answer.is_some() {
        // cevap yolu: yalnız soru-cevap
    } else if project.phase == "planning" {
        parts.push(if tr {
            format!(
                concat!(
                    "Planlama fazındayız. Sırayla:\n",
                    "1. Konuyla ilgili literatürü ve mevcut çözümleri tara (web araması, kaynak listesi); bulduklarını ",
                    "KAYNAKLAR.md'ye kısa özetle yaz.\n",
                    "2. Zaten yapan var mı? İşe yarıyor mu, kullanılmalı mı? Daha iyisi var mı, daha iyisi olur mu? ",
                    "Gerekçeli değerlendir.\n",
                    "3. PLAN.md yaz: hedef, kapsam, adımlar (sıralı, küçük), riskler, açık kararlar.\n",
                    "Verdiğin kararları TOBEDECIDED.md'ye (TBD#), ertelenen işleri TODO.md'ye yaz. Her adımda commit+push.\n",
                    "Plan tamamlanıp uygulanmaya hazır olduğunda yanıtını `{}` satırıyla bitir."
                ),
                MARK_PLAN_READY
            )
        } else {
            format!(
                concat!(
                    "We are in the planning phase. In order:\n",
                    "1. Survey the literature and existing solutions (web search, source list); summarize into KAYNAKLAR.md.\n",
                    "2. Does something already do this? Is it usable? Is there something better, could there be? Judge with reasons.\n",
                    "3. Write PLAN.md: goal, scope, ordered small steps, risks, open decisions.\n",
                    "Record decisions in TOBEDECIDED.md (TBD#), deferred work in TODO.md. Commit+push at every step.\n",
                    "When the plan is ready to execute, end your reply with `{}`."
                ),
                MARK_PLAN_READY
            )
        });
    } else if project.phase == "planned" {
        parts.push(if tr {
            format!(
                concat!(
                    "Plan hazır, uygulama fazındayız. PLAN.md/TODO.md'deki SIRADAKİ işi al ve ilerlet: gerekli komutları ",
                    "çalıştır, sonucu doğrula. Aldığın kararları TOBEDECIDED.md'ye (TBD#), fark ettiğin edge case'leri ",
                    "TODO.md'ye kaydet. Takıldığın yerde önce kendin düşün, çözüm bulamazsan sor. İş bitince commit+push, ",
                    "DONE.md'ye tek satır.\n",
                    "Projedeki her şey bittiyse yanıtını `{done}` satırıyla bitir; motor bir teyit isteyecek, kanıtlı ",
                    "`{confirmed}: <kısa hash> kalan açık iş 0, <kanıt>` olmadan proje kapanmaz. Bir PARÇAYI bitirmek proje bitti demek değildir."
                ),
                done = MARK_DONE,
                confirmed = MARK_DONE_CONFIRMED
            )
        } else {
            format!(
                concat!(
                    "The plan is ready; execution phase. Take the NEXT item in PLAN.md/TODO.md and move it forward: run the ",
                    "needed commands, verify the result. Record decisions in TOBEDECIDED.md (TBD#), edge cases in TODO.md. ",
                    "When stuck, think first, ask only if you cannot resolve it. Commit+push when done, one line in DONE.md.\n",
                    "If the whole project is finished, end your reply with `{done}`; the engine will ask for a confirmation, and the ",
                    "project is not closed without an evidenced `{confirmed}: <short hash> open items 0, <evidence>`. Finishing one PART is not finishing the project."
                ),
                done = MARK_DONE,
                confirmed = MARK_DONE_CONFIRMED
            )
        });
    }
    if !compact {
        if !pyc::strip(&project.notes).is_empty() {
            parts.push(format!("{}{}", tr_en(tr, "Değnekçi notu: ", "Steward note: "), pyc::strip(&project.notes)));
        }
        parts.push(tr_en(tr, P_PROTOCOL_TR, P_PROTOCOL_EN).to_string());
    }
    parts.push(reply_language_line(lang).to_string());
    parts.join("\n\n")
}

// ── tur prompt'u ──────────────────────────────────────────────────────────────

/// `text[:n-1].rstrip() + "…"` (kırpılmış metin `n` kod noktasını aşıyorsa); `n == 0` boş döner.
///
/// py: _clip
pub fn clip(text: &str, n: usize) -> String {
    let text = pyc::strip(text);
    if pyc::len(text) <= n {
        return text.to_string();
    }
    let Some(keep) = n.checked_sub(1) else {
        return String::new();
    };
    format!("{}…", pyc::rstrip(pyc::head(text, keep)))
}

fn bad(v: &Value) -> BadValue {
    BadValue(v.to_string())
}

/// `_clip(v, n)`: `v or ""`; dolu ama dizge olmayan değer Python'da hata.
fn clip_value(v: Option<&Value>, n: usize) -> Result<String, BadValue> {
    match v.filter(|v| pyc::truthy(v)) {
        None => Ok(String::new()),
        Some(Value::String(s)) => Ok(clip(s, n)),
        Some(other) => Err(bad(other)),
    }
}

/// `for x in (v or [])`: liste öğeleri, dizgenin karakterleri ya da sözlüğün anahtarları.
fn items_of(v: Option<&Value>) -> Result<Vec<Value>, BadValue> {
    match v.filter(|v| pyc::truthy(v)) {
        None => Ok(Vec::new()),
        Some(Value::Array(a)) => Ok(a.clone()),
        Some(Value::String(s)) => Ok(s.chars().map(|c| Value::from(c.to_string())).collect()),
        Some(Value::Object(o)) => Ok(o.keys().map(|k| Value::from(k.clone())).collect()),
        Some(other) => Err(bad(other)),
    }
}

/// `v or {}` sonrasında `.get`/`.items` çağrılan değer.
fn object_of(v: Option<&Value>) -> Result<Option<&Map<String, Value>>, BadValue> {
    match v.filter(|v| pyc::truthy(v)) {
        None => Ok(None),
        Some(Value::Object(o)) => Ok(Some(o)),
        Some(other) => Err(bad(other)),
    }
}

fn joined(v: Option<&Value>, n: usize) -> Result<String, BadValue> {
    let parts = items_of(v)?.iter().map(|x| clip_value(Some(x), n)).collect::<Result<Vec<_>, _>>()?;
    Ok(parts.join("; "))
}

/// Proje kartını tur prompt'una / insan çıktısına gidecek kısa satırlara döker (boş alanlar atlanır).
///
/// py: card_lines
pub fn card_lines(card: &Map<String, Value>, tr: bool, now: f64) -> Result<Vec<String>, BadValue> {
    let truthy = |k: &str| card.get(k).filter(|v| pyc::truthy(v));
    let mut age = String::new();
    if let Some(updated) = truthy("updated_at") {
        let hours = (now - pyc::to_float(updated).ok_or_else(|| bad(updated))?) / 3600.0;
        if !hours.is_finite() {
            return Err(bad(updated));
        }
        let h = (hours.trunc() as i64).max(0);
        age = if tr { format!(" ({h} sa önce") } else { format!(" ({h}h ago") };
        age.push_str(match (truthy("stale").is_some(), tr) {
            (true, true) => ", bayat)",
            (true, false) => ", stale)",
            (false, _) => ")",
        });
    }
    let summarized = card.get("summarized").is_none_or(pyc::truthy);
    let raw_tag = if summarized { "" } else { tr_en(tr, " [ham]", " [raw]") };
    let mut out = vec![format!("{}{age}{raw_tag}:", tr_en(tr, "kart", "card"))];
    for (key, label_tr, label_en) in [
        ("goal", "amaç", "goal"),
        ("phase_guess", "faz tahmini", "phase guess"),
        ("next_step", "sıradaki adım", "next step"),
    ] {
        if let Some(v) = truthy(key) {
            out.push(format!("- {}: {}", tr_en(tr, label_tr, label_en), clip_value(Some(v), 300)?));
        }
    }
    for (key, label_tr, label_en) in [
        ("open_tbds", "açık TBD", "open TBDs"),
        ("blockers", "engeller", "blockers"),
        ("recent_done", "son biten", "recently done"),
    ] {
        if let Some(v) = truthy(key) {
            if !matches!(v, Value::Array(_) | Value::String(_)) {
                return Err(bad(v)); // Python: dilimlenemez
            }
            let vals =
                items_of(Some(v))?.iter().take(5).map(|x| clip_value(Some(x), 120)).collect::<Result<Vec<_>, _>>()?;
            out.push(format!("- {}: {}", tr_en(tr, label_tr, label_en), vals.join("; ")));
        }
    }
    Ok(out)
}

fn kind_label(kind: &str, tr: bool) -> String {
    let (t, e) = match kind {
        "idle" => ("BOŞTA", "IDLE"),
        "review" => ("GÖZDEN GEÇİR", "REVIEW"),
        "idea" => ("FİKİR", "IDEA"),
        "due" => ("SIRASI GELDİ", "DUE"),
        "blocked" => ("TAKILDI", "BLOCKED"),
        "routine" => ("RUTİN SORU", "ROUTINE QUESTION"),
        "ask" => ("SAHİP SORUSU", "OWNER QUESTION"),
        _ => return kind.to_uppercase(),
    };
    tr_en(tr, t, e).to_string()
}

fn is_kind(it: &Map<String, Value>, kind: &str) -> bool {
    it.get("kind").and_then(Value::as_str) == Some(kind)
}

/// Beyne gönderilen tur prompt'u. `stamp` = Python'un `now` argümanı (başlık saati ve kart yaşı; verilmezse ya da
/// 0 ise `now`); `now` = saat (`_now()`).
///
/// py: build_tour_prompt
pub fn build_tour_prompt(
    items: &[Map<String, Value>],
    lang: &str,
    open_qs: &[Question],
    stamp: Option<f64>,
    now: f64,
) -> Result<String, BadValue> {
    let tr = lang != "en";
    let at = stamp.filter(|s| *s != 0.0).unwrap_or(now);
    let ts = pyc::localtime(at).format("%Y-%m-%d %H:%M");
    let mut lines: Vec<String> = Vec::new();
    lines.push(if tr {
        format!("[claudeops değnekçi turu — {ts}]")
    } else {
        format!("[claudeops steward tour — {ts}]")
    });
    lines.push(
        tr_en(
            tr,
            concat!(
                "Aşağıdaki maddelerin HER BİRİ için bir karar ver ve ilgili MCP aracını çağır ",
                "(steward_project_context ile daha fazla bağlam alabilirsin): ",
                "steward_directive (sıradaki işi ver), steward_restart (boş/yanlış iş yapıyor → durdur, daha iyi ",
                "direktifle ve gerekirse başka model/effort ile yeniden aç), steward_stop (şimdilik dursun), ",
                "steward_answer (RUTİN SORU: ne zaman/hangi sıra/hangi model gibi işleyiş sorusunu sen cevapla, bana sorma), ",
                "steward_ask_user (benim kararım gerekiyor), steward_set_project (faz/öncelik/not), ",
                "steward_idea_update (fikir: proje/sonra/çöp), steward_register_project (fikirden proje), ",
                "steward_skip (bu tur dokunma). Kararsız kaldığında sor, ama sormadan verebileceğin kararı sorma."
            ),
            concat!(
                "For EACH item below decide and call the matching MCP tool (steward_project_context gives more context): ",
                "steward_directive (next task), steward_restart (idle/wrong work → stop and reopen with a better directive, ",
                "other model/effort if needed), steward_stop, steward_answer (ROUTINE QUESTION: answer process questions yourself, do not ask me), steward_ask_user (needs my decision), steward_set_project, ",
                "steward_idea_update, steward_register_project, steward_skip. Ask when unsure, never ask what you can decide."
            ),
        )
        .to_string(),
    );
    if items.iter().any(|it| is_kind(it, "ask")) {
        lines.push(
            tr_en(
                tr,
                concat!(
                    "SAHİP SORUSU maddelerinde sahibin ne diyeceğini tahmin edip `steward_answer id cevap` çağır (seçenek varsa ",
                    "seçenek metnini aynen yaz); cevap kapıdan geçer. Karar gerçekten sahibinse ya da emin değilsen `steward_skip`; ",
                    "reddedilen cevabı yeniden deneme."
                ),
                concat!(
                    "For OWNER QUESTION items predict the owner's answer and call `steward_answer id answer` (copy the option text ",
                    "when there are options); the answer goes through a gate. If it is truly the owner's call or you are unsure, ",
                    "`steward_skip`; never retry a refused answer."
                ),
            )
            .to_string(),
        );
    }
    if !open_qs.is_empty() {
        lines.push(String::new());
        lines.push(
            tr_en(
                tr,
                "Bana sorulmuş, hâlâ cevapsız sorular (tekrar sorma):",
                "Open questions already waiting on me (do not re-ask):",
            )
            .to_string(),
        );
        for q in open_qs.iter().filter(|q| !q.routine).take(10) {
            let project = if q.project.is_empty() { "-" } else { &q.project };
            lines.push(format!("- [{}] {project}: {}", q.id, clip(&q.text, 200)));
        }
    }
    for (n, it) in items.iter().enumerate() {
        tour_item(&mut lines, n + 1, it, tr, at)?;
    }
    lines.push(String::new());
    lines.push(if tr {
        format!("Bütün maddeleri işledikten sonra yanıtını tek başına `{MARK_END}` satırıyla bitir.")
    } else {
        format!("After handling every item, end your reply with a line containing only `{MARK_END}`.")
    });
    Ok(lines.join("\n"))
}

/// `build_tour_prompt`ın tek maddelik gövdesi.
fn tour_item(lines: &mut Vec<String>, n: usize, it: &Map<String, Value>, tr: bool, now: f64) -> Result<(), BadValue> {
    let truthy = |k: &str| it.get(k).filter(|v| pyc::truthy(v));
    let str_or_none = |k: &str| pyc::str_of(it.get(k).unwrap_or(&Value::Null));
    lines.push(String::new());
    let kind = match it.get("kind") {
        None => "",
        Some(Value::String(s)) => s,
        Some(other) => return Err(bad(other)),
    };
    let title = match truthy("name") {
        Some(name) => pyc::str_of(name),
        None => it.get("id").map(pyc::str_of).unwrap_or_default(),
    };
    lines.push(format!("### {n}. {} — {title}", kind_label(kind, tr)));
    if kind == "idea" {
        lines.push(format!("id={}  {}", str_or_none("id"), clip_value(it.get("text"), 600)?));
        return Ok(());
    }
    if let Some(phase) = truthy("phase") {
        let tail = truthy("kindp")
            .map(|k| format!("{}{}", tr_en(tr, "  tür: ", "  kind: "), pyc::str_of(k)))
            .unwrap_or_default();
        lines.push(format!("{}{}{tail}", tr_en(tr, "faz: ", "phase: "), pyc::str_of(phase)));
    }
    let labelled = |lines: &mut Vec<String>, v: Option<&Value>, t, e, max| -> Result<(), BadValue> {
        if let Some(v) = v.filter(|v| pyc::truthy(v)) {
            lines.push(format!("{}{}", tr_en(tr, t, e), clip_value(Some(v), max)?));
        }
        Ok(())
    };
    labelled(lines, it.get("goal"), "amaç: ", "goal: ", 300)?;
    if let Some(v) = it.get("idle_minutes").filter(|v| !v.is_null()) {
        let mins = pyc::to_int(v).ok_or_else(|| bad(v))?;
        lines.push(if tr { format!("boşta: {mins} dk") } else { format!("idle: {mins} min") });
    }
    for c in items_of(it.get("contradictions"))? {
        lines.push(format!(
            "{}{}",
            tr_en(tr, "⚠ MOTOR ÇELİŞKİ: ", "⚠ ENGINE CONTRADICTION: "),
            clip_value(Some(&c), 300)?
        ));
    }
    labelled(lines, it.get("last_directive"), "son direktif: ", "last directive: ", 300)?;
    let ex = object_of(it.get("last_exchange"))?;
    labelled(lines, ex.and_then(|e| e.get("user")), "son istek: ", "last request: ", 300)?;
    labelled(lines, ex.and_then(|e| e.get("assistant")), "son yanıt: ", "last reply: ", 700)?;
    labelled(
        lines,
        it.get("stated_next"),
        "oturumun KENDİ bildirdiği sıradaki iş (STEWARD-NEXT): ",
        "next work the session itself stated (STEWARD-NEXT): ",
        300,
    )?;
    if let Some(card) = object_of(it.get("card"))? {
        lines.extend(card_lines(card, tr, now)?);
    } else if let Some(docs) = object_of(it.get("docs"))? {
        for (doc, body) in docs {
            if pyc::truthy(body) {
                lines.push(format!("{doc} {}", tr_en(tr, "(baş):", "(head):")));
                lines.push(clip_value(Some(body), 600)?);
            }
        }
    }
    if let Some(bl) = object_of(it.get("backlog"))? {
        if bl.get("auto").is_some_and(pyc::truthy) {
            lines.push(format!(
                "{}{}",
                tr_en(
                    tr,
                    "otonom ilerletilebilir (sahibin cevabı gerekmez): ",
                    "autonomous (no owner answer needed): "
                ),
                joined(bl.get("auto"), 160)?
            ));
        }
        if bl.get("decide").is_some_and(pyc::truthy) {
            lines.push(format!(
                "{}{}",
                tr_en(
                    tr,
                    "karar gerekir (ATLA, varsayılanı uygulama; açık değilse steward_ask_user): ",
                    "needs a decision (SKIP, never apply a default; steward_ask_user unless already open): "
                ),
                joined(bl.get("decide"), 160)?
            ));
        }
    }
    if let Some(text) = truthy("text") {
        lines.push(clip_value(Some(text), 600)?);
    }
    for sq in items_of(it.get("similar"))? {
        let Value::Object(sq) = &sq else {
            return Err(bad(&sq));
        };
        let project = Some(str_or_empty(sq.get("project"))).filter(|p| !p.is_empty()).unwrap_or_else(|| "-".into());
        let label = tr_en(tr, "benzer geçmiş karar", "similar past decision");
        lines.push(format!(
            "{label} [{project}]: {} → {}",
            clip_value(sq.get("text"), 160)?,
            clip_value(sq.get("answer"), 200)?
        ));
    }
    Ok(())
}

// ── beynin CLAUDE.md'si ───────────────────────────────────────────────────────

/// Default DIŞI kimliğin beyni için kısa kimlik bölümü (`default` için "").
///
/// py: identity_section
pub fn identity_section(sid: &str, label: &str, lang: &str) -> String {
    if sid == "default" {
        return String::new();
    }
    let who = if label.is_empty() { format!("`{sid}`") } else { format!("`{sid}` (`{label}`)") };
    if lang != "en" {
        format!(
            concat!(
                "## Kimliğin\n",
                "Sen {who} değnekçisisin. Yalnız `steward_overview`'daki projeler senin; başka proje ya da oturuma hâkim değilsin.\n",
                "`degnekci*` adlı oturumlar başka değnekçilerin beyinleri, paylaşımlı servis oturumları da senin değil: hiçbirine yazma; ",
                "araçlar reddeder, reddi yeniden deneme.\n",
                "MCP araçları kimliğini (`{sid}`) her çağrıya OTOMATİK ekler; kimlik parametresi yoktur, değiştirilemez.\n\n"
            ),
            who = who,
            sid = sid
        )
    } else {
        format!(
            concat!(
                "## Your identity\n",
                "You are the steward {who}. Only the projects listed by `steward_overview` are yours; you do not govern any other project or session.\n",
                "Sessions named `degnekci*` are the brains of other stewards, and shared service sessions are not yours either: never write to ",
                "them; the tools refuse, and you must not retry a refusal.\n",
                "The MCP tools add your identity (`{sid}`) to every call AUTOMATICALLY; there is no identity parameter and it cannot be changed.\n\n"
            ),
            who = who,
            sid = sid
        )
    }
}

const TOOLS_TR_HEAD: &str = concat!(
    "## Araçların (MCP `cops-steward`)\n",
    "- `steward_overview` — filo + projeler (sıradaki adım dahil) + açık sorular + yeni fikirler (her turun başında bak)\n",
    "- `steward_project_context name` — projenin fazı/amacı/notu, son konuşma, PROJE KARTI (hedef, sıradaki adım, açık TBD'ler, engeller; ",
    "kart yoksa TODO/PLAN/TOBEDECIDED başları; `docs=true` ikisini birden), git durumu\n",
    "- `steward_read_file name path` — proje klasöründen dosya oku (salt-okunur)\n",
    "- `steward_directive name text [model effort]` — oturuma sıradaki işi gönder (kapalıysa açar)\n",
    "- `steward_restart name directive reason [model effort]` — durdur + aynı konuşmayla yeniden aç + yeni direktif\n",
    "- `steward_handover name` — kapanış mesajı gönder (dolan oturum; motor zaten 1900 satırda bunu kendisi yapar)\n",
    "- `steward_stop name reason` — oturumu durdur\n",
    "- `steward_set_project name [phase kind goal priority cadence_minutes notes model effort]`\n",
    "- `steward_register_project name cwd goal [kind phase cli model resources]` — yeni proje (klasör yoksa açar, GOAL.md yazar)\n",
    "- `steward_answer id answer` — bir RUTİN SORU'yu (projenin işleyiş sorusu) cevapla; motor cevabı oturuma iletir. Sahibe ait kararları ("
);

const TOOLS_TR_TAIL: &str = concat!(
    ") sahibine bırak; commit/push/merge/build/deploy kalıcı izinlidir\n",
    "- `steward_ask_user project question [options]` — bana soru (telefona bildirim gider, `options` verirsen ",
    "(en çok 6 kısa seçenek: evet/hayır, A/B/C, sonra) tek dokunuşla cevaplarım; cevabı motor oturuma iletir)\n",
    "- `steward_note project text` — kendi notun (bir sonraki direktifte oturuma da gider)\n",
    "- `steward_idea text` / `steward_idea_update id status [project]` — fikir kutusu\n",
    "- `steward_questions` / `steward_log` — açık sorular / son olaylar\n",
    "- `steward_skip name reason` — bu tur dokunmuyorum (kayda geçer)\n",
    "\n`steward_overview` içindeki `config.mode` `observe` ise `steward_directive`/`steward_restart`/`steward_stop`/",
    "`steward_handover` KAYDA geçer ama UYGULANMAZ (yanıtta `dry: true`); soru, fikir, faz/not değişikliği çalışır. ",
    "Kararını yine ver: sahibi `would:` kayıtlarından neyi yapacağını görüp güven kazandırır.\n"
);

const TOOLS_EN: &str = concat!(
    "## Your tools (MCP `cops-steward`)\n",
    "- `steward_overview`, `steward_project_context name`, `steward_read_file name path`\n",
    "- `steward_directive`, `steward_restart`, `steward_handover`, `steward_stop`\n",
    "- `steward_set_project`, `steward_register_project`, `steward_ask_user`, `steward_note`\n",
    "- `steward_idea`, `steward_idea_update`, `steward_questions`, `steward_log`, `steward_skip`\n",
    "\nWhen `config.mode` in `steward_overview` is `observe`, `steward_directive`/`steward_restart`/`steward_stop`/",
    "`steward_handover` are recorded but NOT applied (`dry: true` in the reply); questions, ideas and phase/note ",
    "changes still work. Decide anyway: the owner reads the `would:` records to learn what you would do.\n"
);

/// Beynin cwd'sindeki `CLAUDE.md`. `persona` metni çağırandan gelir.
///
/// py: build_workspace_claude_md
pub fn build_workspace_claude_md(
    persona: &str,
    lang: &str,
    sid: &str,
    label: &str,
    remote: bool,
    role: &str,
) -> String {
    let tr = lang != "en";
    let tools = if tr { format!("{TOOLS_TR_HEAD}{OWNER_ONLY_TOPICS_TR}{TOOLS_TR_TAIL}") } else { TOOLS_EN.to_string() };
    let tail = if tr {
        format!(
            concat!(
                "\n## Tur protokolü\nHer tur prompt'unda listelenen her madde için bir araç çağır; bitince yanıtını tek başına ",
                "`{}` satırıyla kapat. Araç çağırmadan verilen karar KAYDA GEÇMEZ.\n"
            ),
            MARK_END
        )
    } else {
        format!(
            concat!(
                "\n## Tour protocol\nCall one tool per listed item; finish with a line containing only `{}`. ",
                "A decision without a tool call is not recorded.\n"
            ),
            MARK_END
        )
    };
    let note = if remote { tr_en(tr, REMOTE_NOTE_TR, REMOTE_NOTE_EN) } else { "" };
    let generic = if role == "generic" { tr_en(tr, GENERIC_RULE_TR, GENERIC_RULE_EN) } else { "" };
    [
        pyc::rstrip(persona),
        "\n\n",
        &identity_section(sid, label, lang),
        &tools,
        note,
        tr_en(tr, MODEL_RULE_TR, MODEL_RULE_EN),
        generic,
        tr_en(tr, MEMORY_TR, MEMORY_EN),
        &tail,
    ]
    .concat()
}

// ── kural motoru yardımcıları ─────────────────────────────────────────────────

/// py: _is_project_session
pub fn is_project_session(v: &SessionView, projects: &IndexMap<String, Project>) -> bool {
    projects.contains_key(v.project())
}

/// (model, effort): proje değeri > faz varsayılanı > "".
///
/// py: phase_model_effort
pub fn phase_model_effort(project: &Project, cfg: &Config) -> (String, String) {
    let (model, effort) = if project.phase == "planning" {
        (&cfg.planning_model, &cfg.planning_effort)
    } else {
        (&cfg.planned_model, &cfg.planned_effort)
    };
    let pick = |own: &String, default: &String| {
        if own.is_empty() {
            default.clone()
        } else {
            own.clone()
        }
    };
    (pick(&project.model, model), pick(&project.effort, effort))
}

/// Değnekçinin açtığı claude ana oturumu en yeni Sonnet + `medium`; claude dışı cli/model dokunulmadan döner.
///
/// py: main_session_model_effort
pub fn main_session_model_effort(model: &str, effort: &str, cli: &str, sonnet: &str) -> (String, String) {
    let m = pyc::strip(model);
    let claude_model = m.to_lowercase().starts_with("claude");
    let is_claude = cli == "claude" || (cli.is_empty() && claude_model);
    if !is_claude || sonnet.is_empty() || (!m.is_empty() && !claude_model) {
        return (model.to_string(), effort.to_string());
    }
    (sonnet.to_string(), "medium".to_string())
}

/// Oturum maddesinin DURUM imzası: son asistan metni, projenin fazı, ilgili soruların (kimlik, durum) listesi.
///
/// py: item_signature
pub fn item_signature(v: &SessionView, projects: &IndexMap<String, Project>, questions: &[Question]) -> String {
    let project = v.project();
    let mut rel: Vec<(&str, &str)> = questions
        .iter()
        .filter(|q| q.source == v.name || (!project.is_empty() && q.project == project))
        .map(|q| (q.id.as_str(), q.status.as_str()))
        .collect();
    rel.sort_unstable();
    let phase = projects.get(project).map_or("", |p| p.phase.as_str());
    let mut last = pyc::strip(&v.last_assistant);
    if OK_ONLY_RE.as_ref().is_some_and(|r| r.is_match(last)) {
        last = ""; // keepwarm dürtmesinin "ok" cevabı
    }
    let digest = pyc::sha1_hex(last.as_bytes());
    let pairs: Vec<String> = rel
        .iter()
        .map(|(id, status)| format!("[{}, {}]", pyc::json_str_ascii(id), pyc::json_str_ascii(status)))
        .collect();
    let raw = format!(
        "[{}, {}, [{}]]",
        pyc::json_str_ascii(pyc::head(&digest, 12)),
        pyc::json_str_ascii(phase),
        pairs.join(", ")
    );
    pyc::head(&pyc::sha1_hex(raw.as_bytes()), 16).to_string()
}

/// Projesi kayıtlı olmayan, bayat ve teslim edilmemiş cevaplar. `questions` = kimliğin soru deposu, `live` = çalışan
/// oturum adları.
///
/// py: stale_answers
pub fn stale_answers<'a>(
    questions: &'a [Question],
    projects: &IndexMap<String, Project>,
    cfg: &Config,
    now: f64,
    live: &BTreeSet<String>,
) -> Vec<&'a Question> {
    let brain_live = !cfg.brain_name.is_empty() && live.contains(&cfg.brain_name);
    undelivered_answers(questions)
        .into_iter()
        .filter(|q| {
            let at = if q.answered_at != 0.0 { q.answered_at } else { q.created_at };
            let brainish = q.project.is_empty() || q.project == cfg.brain_name;
            let orphan = !q.project.is_empty()
                && q.project != cfg.brain_name
                && !projects.contains_key(&q.project)
                && !live.contains(&q.project)
                && !live.contains(&q.source);
            now - at >= STALE_ANSWER_SECONDS && (orphan || (!brain_live && brainish && !live.contains(&q.source)))
        })
        .collect()
}

/// Beynin proje notundaki doğrulanabilir iddialar.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct NoteClaims {
    pub pids: Vec<i64>,
    pub gate: bool,
}

/// "koşu sürüyor, PID 1234" (`pids`) ve "kapıda bekliyor" (`gate`).
///
/// py: note_claims
pub fn note_claims(notes: &str) -> NoteClaims {
    // Python `re.I`de `i`, `İ` ve `ı` ile de eşleşir
    let t = notes.replace(['İ', 'ı'], "i");
    let pids: BTreeSet<i64> = NOTE_PID_RE
        .captures_iter(&t)
        .filter_map(|c| c.get(1))
        .map(|m| m.as_str().chars().fold(0, |acc, c| acc * 10 + pyc::decimal_value(c)))
        .collect();
    NoteClaims { pids: pids.into_iter().collect(), gate: NOTE_GATE_RE.is_match(&t) }
}

/// Not iddialarını gerçekle karşılaştırır; yalnız KANITLI çelişki metinleri döner.
///
/// py: check_note_claims
pub fn check_note_claims(
    notes: &str,
    pid_alive: &dyn Fn(i64) -> Option<bool>,
    gate_ahead: &dyn Fn() -> Option<i64>,
    tr: bool,
) -> Vec<String> {
    let c = note_claims(notes);
    let mut out = Vec::new();
    for pid in c.pids {
        if pid_alive(pid) == Some(false) {
            out.push(if tr {
                format!("notta PID {pid} \"sürüyor\" deniyor ama bu süreç YOK (ölü); koşu bitmiş olabilir, notu güncelle / işi ilerlet")
            } else {
                format!("the note says PID {pid} is running but that process is GONE; the run may have finished, update the note / move on")
            });
        }
    }
    if c.gate && gate_ahead() == Some(0) {
        out.push(
            tr_en(
                tr,
                "notta \"kapıda bekliyor\" deniyor ama dal ana dalın İLERİSİNDE değil (0 commit: zaten birleşmiş ya da iş yok); notu düzelt",
                "the note says \"waiting at the gate\" but the branch is not ahead of the main branch (0 commits: already merged or nothing to land); fix the note",
            )
            .to_string(),
        );
    }
    out
}

/// Bir turda gidecek maddeler: soru/takılma önce, tavanlar `ask_gate`e göre.
///
/// py: cut_tour_items
pub fn cut_tour_items(items: &[Map<String, Value>], ask_gate: &str) -> Vec<Map<String, Value>> {
    let rank = |it: &&Map<String, Value>| match it.get("kind").and_then(Value::as_str) {
        Some("routine" | "blocked") => 0,
        Some("ask") => 1,
        _ => 2,
    };
    let max_items = usize::try_from(TOUR_MAX_ITEMS).unwrap_or(0);
    let max_questions = usize::try_from(TOUR_MAX_QUESTION_ITEMS).unwrap_or(0);
    let mut ordered: Vec<&Map<String, Value>> = items.iter().collect();
    ordered.sort_by_key(rank);
    if ask_gate == "off" {
        return ordered.into_iter().take(max_items).cloned().collect();
    }
    let (questions, others): (Vec<_>, Vec<_>) =
        ordered.into_iter().partition(|it| is_kind(it, "routine") || is_kind(it, "ask"));
    let mut cut: Vec<&Map<String, Value>> =
        questions.into_iter().take(max_questions).chain(others.into_iter().take(max_items)).collect();
    cut.sort_by_key(rank);
    cut.into_iter().cloned().collect()
}

/// Turda gönderilen sahip sorularını `state.ask_seen`e say (soru maddesi yoksa state'e dokunmaz).
///
/// py: mark_ask_seen
pub fn mark_ask_seen(state: &mut Map<String, Value>, items: &[Map<String, Value>], now: f64) -> Result<(), BadValue> {
    let asked: Vec<String> = items
        .iter()
        .filter(|it| is_kind(it, "ask"))
        .map(|it| pyc::str_of(it.get("id").unwrap_or(&Value::Null)))
        .collect();
    if asked.is_empty() {
        return Ok(());
    }
    let mut seen = object_of(state.get("ask_seen"))?.cloned().unwrap_or_default();
    for qid in asked {
        let n = match object_of(seen.get(&qid))?.and_then(|e| e.get("n")).filter(|v| pyc::truthy(v)) {
            None => 0,
            Some(v) => pyc::to_int(v).ok_or_else(|| bad(v))?,
        };
        let mut entry = Map::new();
        entry.insert("n".into(), Value::from(n.saturating_add(1)));
        entry.insert("at".into(), Value::from(now));
        seen.insert(qid, Value::Object(entry));
    }
    state.insert("ask_seen".into(), Value::Object(seen));
    Ok(())
}
