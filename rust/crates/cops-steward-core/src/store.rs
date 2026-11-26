//! Depo sarmalayıcılarının KARAR çekirdekleri (grup 1): belge + `now` + yeni kimlik girer, belge yerinde değişir, sonuç
//! döner. Dosya, kilit, olay günlüğü, saat ve rastgele kimlik çağırandadır; `dirty`/dönüş değeri "kaydet" demektir.

use crate::consts_gen::*;
use crate::identity::{self, OwnedElsewhere, OwnershipIndex, ReservedName, ReviewerRefused};
use crate::pyc;
use crate::questions::*;
use crate::types::{Idea, Project, Question};
use indexmap::IndexMap;
use serde_json::{Map, Value};
use std::collections::BTreeSet;
use std::fmt;

fn cap(text: &str, n: i64) -> String {
    pyc::head(text, n as usize).to_string()
}

/// Yeni soru kimliği ve soruya özel anahtar (`_new_id("q")`, `_unique_question_key`). Yalnız gerekince istenir.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Minted {
    pub id: String,
    pub key: String,
}

/// `add_question_ex`in ne yaptığı.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AddKind {
    New,
    Reasked,
    Same,
    Merged,
    Promoted,
}

impl AddKind {
    pub fn as_str(self) -> &'static str {
        match self {
            AddKind::New => "new",
            AddKind::Reasked => "reasked",
            AddKind::Same => "same",
            AddKind::Merged => "merged",
            AddKind::Promoted => "promoted",
        }
    }
}

/// `add_question_ex` sonucu: `questions[index]`; `dirty` = depo kaydedilmeli.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Added {
    pub index: usize,
    pub kind: AddKind,
    pub dirty: bool,
}

/// Boş metin (Python `ValueError`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmptyText(pub &'static str);

impl fmt::Display for EmptyText {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "empty {}", self.0)
    }
}

impl std::error::Error for EmptyText {}

/// Sorulan soru (`add_question_ex` argümanları).
#[derive(Debug, Clone, Copy)]
pub struct Ask<'a> {
    pub project: &'a str,
    pub text: &'a str,
    pub source: &'a str,
    pub options: &'a Value,
    pub routine: bool,
    pub detail: &'a str,
}

fn position(questions: &[Question], hit: Option<&Question>) -> Option<usize> {
    let hit = hit?;
    questions.iter().position(|q| std::ptr::eq(q, hit))
}

/// Yeni soru mu, yeniden iletim mi, birleştirme mi.
///
/// py: add_question_ex
pub fn add_question_ex(
    questions: &mut Vec<Question>,
    ask: Ask<'_>,
    now: f64,
    mint: &mut dyn FnMut() -> Minted,
) -> Result<Added, EmptyText> {
    let Ask { project, source, options, routine, detail, .. } = ask;
    let text = cap(pyc::strip(ask.text), P_MAX_QUESTION_CHARS);
    if text.is_empty() {
        return Err(EmptyText("question"));
    }
    // farklı dosyalı iş istekleri Jaccard'da birbirine benzer: kopya/birleştirme sayılmaz
    let is_job = text.starts_with(JOB_REQUEST_PREFIX);
    let solo = is_job || text.starts_with(P_HELD_ANSWER_PREFIX);
    let mut dup = None;
    if !solo {
        let hit = find_answered_duplicate(questions.iter(), project, &text, now)
            .or_else(|| find_answered_hold(questions.iter(), project, &text, now));
        dup = position(questions, hit);
    }
    if let Some((index, q)) = dup.and_then(|i| questions.get_mut(i).map(|q| (i, q))) {
        // beynin RUTİN diye cevapladığı soru bu kez sahibe soruluyorsa eski cevapla bastırılmaz
        if !(q.routine && !routine) && q.repeats < REASK_MAX_REPEATS {
            q.repeats += 1;
            q.delivered_at = 0.0;
            return Ok(Added { index, kind: AddKind::Reasked, dirty: true });
        }
    }
    let identical =
        questions.iter_mut().enumerate().find(|(_, q)| q.status == "open" && q.project == project && q.text == text);
    if let Some((index, q)) = identical {
        if q.routine && !routine {
            q.routine = false;
            return Ok(Added { index, kind: AddKind::Promoted, dirty: true });
        }
        return Ok(Added { index, kind: AddKind::Same, dirty: false });
    }
    // Benzer AÇIK soru: yenisi açılmaz, sayaç artar. `newer`: birleşen soruda en yeni metin görünür.
    let (mut sim, mut newer) = (None, false);
    if !solo {
        let pool = || questions.iter().filter(|q| !q.text.starts_with(P_HELD_ANSWER_PREFIX));
        let mut hit = find_open_same_ask(pool(), project, &text, now);
        newer = hit.is_some();
        if hit.is_none() {
            hit = find_open_similar(pool(), project, &text, now);
        }
        if hit.is_none() {
            hit = find_open_topic(pool(), project, &text, now);
            newer = hit.is_some();
        }
        sim = position(questions, hit);
    }
    if let Some(q) = sim.filter(|_| newer).and_then(|i| questions.get_mut(i)) {
        if !is_paused_sweep(&text) {
            q.prev_texts.insert(0, q.text.clone());
            q.prev_texts.truncate(TOPIC_PREV_KEEP as usize);
        }
        q.text.clone_from(&text);
        if !source.is_empty() {
            q.source = source.to_string();
        }
    }
    if sim.is_none() && !solo && !routine {
        // L7b: proje başına açık soru sınırı; aşılınca en yeni açık soruya "ek" olarak eklenir
        let opened = || {
            questions.iter().enumerate().filter(|(_, q)| {
                q.status == "open" && q.project == project && !q.routine && !q.text.starts_with(JOB_REQUEST_PREFIX)
            })
        };
        if opened().count() >= MAX_OPEN_QUESTIONS_PER_PROJECT as usize {
            let newest = opened()
                .fold(None::<(usize, f64)>, |best, (i, q)| match best {
                    Some((_, at)) if q.created_at <= at => best,
                    _ => Some((i, q.created_at)),
                })
                .map(|(i, _)| i);
            sim = newest;
            if let Some(q) = newest.and_then(|i| questions.get_mut(i)) {
                if !q.extra_texts.contains(&text) {
                    q.extra_texts.push(text.clone());
                    let drop = q.extra_texts.len().saturating_sub(EXTRA_TEXTS_KEEP as usize);
                    q.extra_texts.drain(..drop);
                }
                if !source.is_empty() {
                    q.source = source.to_string();
                }
            }
        }
    }
    if let Some((index, q)) = sim.and_then(|i| questions.get_mut(i).map(|q| (i, q))) {
        if !detail.is_empty() && q.detail.is_empty() {
            q.detail = cap(detail, P_MAX_DETAIL_CHARS);
        }
        q.asked_again += 1;
        let promoted = q.routine && !routine;
        if promoted {
            q.routine = false;
        }
        let kind = if promoted { AddKind::Promoted } else { AddKind::Merged };
        return Ok(Added { index, kind, dirty: true });
    }
    let Minted { id, key } = mint();
    questions.push(Question {
        id,
        project: project.to_string(),
        text,
        created_at: now,
        source: source.to_string(),
        options: normalize_options(options),
        key,
        routine,
        detail: cap(detail, P_MAX_DETAIL_CHARS),
        ..Question::default()
    });
    Ok(Added { index: questions.len() - 1, kind: AddKind::New, dirty: true })
}

/// `add_question_ex`in yalnız soruyu döndüren hâli.
///
/// py: add_question
pub fn add_question<'a>(
    questions: &'a mut Vec<Question>,
    ask: Ask<'_>,
    now: f64,
    mint: &mut dyn FnMut() -> Minted,
) -> Result<Option<&'a Question>, EmptyText> {
    let added = add_question_ex(questions, ask, now, mint)?;
    Ok(questions.get(added.index))
}

/// Soruya detay yaz; dolu detay ezilmez. Yazıldıysa (kaydet) `true`.
///
/// py: set_question_detail
pub fn set_question_detail(questions: &mut [Question], question_id: &str, detail: &str) -> bool {
    let detail = cap(pyc::strip(detail), P_MAX_DETAIL_CHARS);
    if detail.is_empty() {
        return false;
    }
    match questions.iter_mut().find(|q| q.id == question_id && q.detail.is_empty()) {
        Some(q) => {
            q.detail = detail;
            true
        }
        None => false,
    }
}

/// `answer_question` sonucu (indeksler `questions` içine).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Answered {
    /// soru yok, ya da `only_open` iken açık değil: kaydetme
    Missing,
    /// erteleme: soru AÇIK kalır, kaydet, oturuma cevap gitmez
    Deferred(usize),
    /// cevaplandı, kaydet. `review_where`: çağıran (kilit dışında) `apply_review_where_answer` uygulamalı
    Done { index: usize, review_where: bool },
}

/// `answer_question` hatası.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AnswerError {
    Empty(EmptyText),
}

impl fmt::Display for AnswerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AnswerError::Empty(e) => e.fmt(f),
        }
    }
}

impl std::error::Error for AnswerError {}

/// `answer_question` argümanları.
#[derive(Debug, Clone, Copy, Default)]
pub struct Reply<'a> {
    pub question_id: &'a str,
    pub answer: &'a str,
    pub by: &'a str,
    pub only_open: bool,
    pub prefix: &'a str,
}

/// py: answer_question
pub fn answer_question(
    questions: &mut Vec<Question>,
    reply: Reply<'_>,
    now: f64,
    mint: &mut dyn FnMut() -> Minted,
) -> Result<Answered, AnswerError> {
    let by = if ANSWERED_BY.contains(&reply.by) { reply.by } else { "" };
    let answer = pyc::strip(reply.answer);
    if answer.is_empty() {
        return Err(AnswerError::Empty(EmptyText("answer")));
    }
    let Some((index, q)) = questions.iter_mut().enumerate().find(|(_, q)| q.id == reply.question_id) else {
        return Ok(Answered::Missing);
    };
    if reply.only_open && q.status != "open" {
        return Ok(Answered::Missing); // beyin kapıdayken sahip cevapladı: ezilmez
    }
    if q.status == "open" && !q.routine && is_defer_answer(answer) {
        let folded = pyc::casefold(&pyc::collapse_ws(answer));
        if !q.options.iter().any(|o| pyc::casefold(o) == folded) {
            q.deferred_until = now + DEFER_SECONDS as f64;
            return Ok(Answered::Deferred(index));
        }
    }
    let resolved = resolve_answer(q, answer);
    q.deferred_until = 0.0;
    q.answer = cap(&resolved, P_MAX_QUESTION_CHARS);
    if by == "cops" && q.source != REVIEW_ASK_SOURCE && !q.answer.starts_with(ON_BEHALF_PREFIX) {
        q.answer = cap(&format!("{ON_BEHALF_PREFIX}{}", q.answer), P_MAX_QUESTION_CHARS);
    }
    if !reply.prefix.is_empty() {
        q.answer = cap(&format!("{}{}", reply.prefix, q.answer), P_MAX_QUESTION_CHARS);
    }
    q.answered_by = by.to_string();
    q.status = "answered".to_string();
    q.answered_at = now;
    q.delivered_at = 0.0;
    let review_where = q.source == REVIEW_ASK_SOURCE;
    // Tek seçenek harfi yalnız ana metni cevaplar: ekler ayrı açık soru olur
    let mut split = None;
    if !q.extra_texts.is_empty() && !q.routine && pyc::match_dollar(&P_BARE_CHOICE_RE, answer) {
        let mut rest = std::mem::take(&mut q.extra_texts);
        let first = rest.remove(0);
        split = Some((q.project.clone(), q.source.clone(), first, rest));
    }
    if let Some((project, source, text, extra_texts)) = split {
        let Minted { id, key } = mint();
        questions.push(Question {
            id,
            project,
            text,
            created_at: now,
            source,
            key,
            extra_texts,
            ..Question::default()
        });
    }
    Ok(Answered::Done { index, review_where })
}

/// Tanınmayan `answered_by` (Python `ValueError`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BadAnsweredBy;

impl fmt::Display for BadAnsweredBy {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("bad answered_by")
    }
}

impl std::error::Error for BadAnsweredBy {}

/// CEVAPLANMIŞ soruların `answered_by` alanını düzeltir; düzeltilen kimlikler (boş değilse kaydet).
///
/// py: set_answered_by
pub fn set_answered_by(questions: &mut [Question], ids: &[String], by: &str) -> Result<Vec<String>, BadAnsweredBy> {
    if !ANSWERED_BY.contains(&by) {
        return Err(BadAnsweredBy);
    }
    let mut done = Vec::new();
    for q in questions.iter_mut().filter(|q| q.status == "answered" && ids.contains(&q.id)) {
        q.answered_by = by.to_string();
        done.push(q.id.clone());
    }
    Ok(done)
}

/// Telefona bildirildi. Kayıt bulundu mu (= kaydet).
///
/// py: mark_notified
pub fn mark_notified(questions: &mut [Question], question_id: &str, now: f64) -> bool {
    let mut hit = false;
    for q in questions.iter_mut().filter(|q| q.id == question_id) {
        q.notified_at = now;
        hit = true;
    }
    hit
}

/// Cevapsız kalan rutin soruyu sahibine açık soruya çevirir; bulunan sorunun indeksi (`Some` = kaydet).
///
/// py: escalate_routine
pub fn escalate_routine(questions: &mut [Question], question_id: &str) -> Option<usize> {
    let mut hit = None;
    for (i, q) in questions.iter_mut().enumerate() {
        if q.id == question_id && q.status == "open" && q.routine {
            q.routine = false;
            hit = Some(i);
        }
    }
    hit
}

/// Cevap teslim edildi. Kayıt bulundu mu (= kaydet).
///
/// py: mark_delivered
pub fn mark_delivered(questions: &mut [Question], question_id: &str, now: f64) -> bool {
    let mut hit = false;
    for q in questions.iter_mut().filter(|q| q.id == question_id) {
        q.delivered_at = now;
        hit = true;
    }
    hit
}

/// Cevap teslim EDİLEMEDİ: yeniden deneme durur, neden kaydedilir. Kayıt bulundu mu (= kaydet).
///
/// py: mark_undeliverable
pub fn mark_undeliverable(questions: &mut [Question], question_id: &str, reason: &str, now: f64) -> bool {
    let mut hit = false;
    for q in questions.iter_mut().filter(|q| q.id == question_id) {
        q.delivered_at = now;
        q.undeliverable = cap(if reason.is_empty() { "undeliverable" } else { reason }, 200);
        hit = true;
    }
    hit
}

// ── fikirler ──────────────────────────────────────────────────────────────────

/// Yeni fikir ekler; eklenen fikrin indeksi.
///
/// py: add_idea
pub fn add_idea(
    ideas: &mut Vec<Idea>,
    text: &str,
    source: &str,
    project: &str,
    now: f64,
    new_id: &mut dyn FnMut() -> String,
) -> Result<usize, EmptyText> {
    let text = cap(pyc::strip(text), P_MAX_IDEA_CHARS);
    if text.is_empty() {
        return Err(EmptyText("idea"));
    }
    ideas.push(Idea {
        id: new_id(),
        text,
        created_at: now,
        source: source.to_string(),
        project: project.to_string(),
        ..Idea::default()
    });
    Ok(ideas.len() - 1)
}

/// `update_idea`ın isteğe bağlı alanları.
#[derive(Debug, Clone, Copy, Default)]
pub struct IdeaUpdate<'a> {
    pub status: Option<&'a str>,
    pub project: Option<&'a str>,
    pub reason: Option<&'a str>,
}

/// Fikri günceller; bulunan fikrin indeksi (`Some` = kaydet). Tanınmayan durum yok sayılır.
///
/// py: update_idea
pub fn update_idea(ideas: &mut [Idea], idea_id: &str, update: IdeaUpdate<'_>) -> Option<usize> {
    let (index, idea) = ideas.iter_mut().enumerate().find(|(_, i)| i.id == idea_id)?;
    if let Some(s) = update.status.filter(|s| ["new", "project", "dropped", "later", "exported"].contains(s)) {
        idea.status = s.to_string();
    }
    if let Some(p) = update.project {
        idea.project = p.to_string();
    }
    if let Some(r) = update.reason {
        idea.reason = cap(&pyc::collapse_ws(r), 300);
    }
    Some(index)
}

/// Fikri `exported` yapar ve aktarım kaydını ekler.
///
/// py: record_idea_export
pub fn record_idea_export(ideas: &mut [Idea], idea_id: &str, record: &Value) -> Option<usize> {
    let (index, idea) = ideas.iter_mut().enumerate().find(|(_, i)| i.id == idea_id)?;
    idea.status = "exported".to_string();
    idea.exported.push(record.clone());
    Some(index)
}

// ── projeler ──────────────────────────────────────────────────────────────────

/// Proje `host`u değiştirilemez: geçersiz/kayıtsız host ya da çalışan (ya da bilinmeyen) oturum.
///
/// py: HostChangeRefused
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HostChangeRefused(pub String);

impl fmt::Display for HostChangeRefused {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for HostChangeRefused {}

/// Host değişince o projenin `state` izleri silinir; silinen `anahtar.ad` listesi (boş değilse kaydet).
///
/// py: _clear_project_state
pub fn clear_project_state(
    name: &str,
    projects: &IndexMap<String, Project>,
    state: &mut Map<String, Value>,
) -> Vec<String> {
    let mut gone = Vec::new();
    for key in P_HOST_STATE_KEYS {
        let Some(d) = state.get_mut(*key).and_then(Value::as_object_mut) else {
            continue;
        };
        let keys: Vec<String> = d.keys().cloned().collect();
        for k in keys {
            let bare = k.split_once(':').map_or(k.as_str(), |(_, rest)| rest);
            let mine = identity::project_key(bare, projects.keys().map(String::as_str)) == name
                || (*key == "done_pending" && d.get(&k).and_then(Value::as_str) == Some(name));
            if mine {
                d.shift_remove(&k);
                gone.push(format!("{key}.{k}"));
            }
        }
    }
    gone
}

/// `upsert_project`in dış dünyaya sorduğu her şey (depo, ayar, host listesi, süreçler, saat).
pub struct UpsertContext<'a> {
    /// yazan değnekçi kimliği ve reviewer rolündeki kimlikler
    pub sid: &'a str,
    pub reviewers: &'a BTreeSet<String>,
    /// `hosts.get_host(ad) is not None`
    pub host_known: &'a dyn Fn(&str) -> bool,
    /// `project_owner(name, exclude=sid)`: adın başka kimlikteki sahibi
    pub owner_elsewhere: &'a dyn Fn(&str) -> Option<String>,
    /// taze sahiplik indeksi (yalnız yeni projede okunur)
    pub index: &'a dyn Fn() -> OwnershipIndex,
    /// projenin çalışan oturumu var mı (`None` = bilinmiyor); verilmediyse de reddedilir
    pub running: Option<&'a dyn Fn() -> Option<bool>>,
    /// `os.path.expanduser`
    pub expanduser: &'a dyn Fn(&str) -> String,
    pub force: bool,
    pub now: f64,
}

/// `upsert_project` sonucu. Çağıran projeleri kaydeder; `host_changed` ise `clear_project_state` + `project_host`
/// olayı; `auto_label_via` doluysa `auto_remove_labels`.
#[derive(Debug, Clone, PartialEq)]
pub struct Upserted {
    pub project: Project,
    pub host_changed: bool,
    pub auto_label_via: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// `upsert_project` hatası (hata durumunda `projects` değişmez).
///
/// py: _BadFieldType
pub enum UpsertError {
    InvalidName(String),
    Reviewer(ReviewerRefused),
    Host(HostChangeRefused),
    Owned(OwnedElsewhere),
    Reserved(ReservedName),
    /// alan tipi uymuyor. Metin alanlarında Python da reddeder (`_BadFieldType`); sayı alanını Python saklar.
    BadType(String),
}

impl fmt::Display for UpsertError {
    /// py: _BadFieldType.__init__
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            UpsertError::InvalidName(n) => write!(f, "invalid project name: {}", pyc::repr_str(n)),
            UpsertError::Reviewer(e) => e.fmt(f),
            UpsertError::Host(e) => e.fmt(f),
            UpsertError::Owned(e) => e.fmt(f),
            UpsertError::Reserved(e) => e.fmt(f),
            UpsertError::BadType(n) if P_PROJECT_TEXT_FIELDS.contains(&n.as_str()) => {
                write!(f, "bad field type: {n} (expected a string)")
            }
            UpsertError::BadType(n) => write!(f, "bad field type: {n}"),
        }
    }
}

impl std::error::Error for UpsertError {}

fn host_label(host: &str) -> &str {
    if host.is_empty() {
        identity::LOCAL_HOST_NAME
    } else {
        host
    }
}

/// Tek alanı uygular; Python'un yok saydığı değer sessizce atlanır.
fn apply_field(p: &mut Project, key: &str, v: &Value, ctx: &UpsertContext<'_>) -> Result<(), UpsertError> {
    let bad = || UpsertError::BadType(key.to_string());
    let text = || v.as_str().map(str::to_string).ok_or_else(bad);
    let float = || v.as_f64().ok_or_else(bad);
    match key {
        "phase" => {
            if let Some(s) = v.as_str().filter(|s| PHASES.contains(s)) {
                p.phase = s.to_string();
            }
        }
        "kind" => {
            if let Some(s) = v.as_str().filter(|s| s.is_empty() || KINDS.contains(s)) {
                p.kind = s.to_string();
            }
        }
        "review_where" => {
            if let Some(s) = v.as_str().filter(|s| REVIEW_WHERE_VALUES.contains(s)) {
                p.review_where = s.to_string();
            }
        }
        "priority" => {
            if let Some(n) = pyc::to_int(v) {
                p.priority = n.clamp(1, 5);
            }
        }
        "cadence_minutes" => {
            if let Some(n) = pyc::to_int(v) {
                p.cadence_minutes = n.max(0);
            }
        }
        "visits" => {
            if let Some(n) = pyc::to_int(v) {
                p.visits = n;
            }
        }
        "notes" => p.notes = cap(&pyc::str_of(v), P_MAX_NOTE_CHARS),
        "local_path" => {
            let path = (ctx.expanduser)(pyc::strip(&pyc::str_of(v)));
            if path.is_empty() || path.starts_with('/') {
                p.local_path = path;
            }
        }
        "goal" => p.goal = text()?,
        "model" => p.model = text()?,
        "effort" => p.effort = text()?,
        "last_directive" => p.last_directive = text()?,
        "host" => p.host = text()?,
        "last_visit" => p.last_visit = float()?,
        "updated_at" => p.updated_at = float()?,
        // `name`, `created_at` ve tanınmayan anahtarlar
        _ => {}
    }
    Ok(())
}

/// Alan bazlı güncelleme/yeni talep kararı (`fields`: Python anahtar sözcük argümanları; `null` = verilmedi).
///
/// py: upsert_project
pub fn upsert_project(
    projects: &mut IndexMap<String, Project>,
    name: &str,
    fields: &Map<String, Value>,
    ctx: &UpsertContext<'_>,
) -> Result<Upserted, UpsertError> {
    if !identity::valid_name(name) {
        return Err(UpsertError::InvalidName(name.to_string()));
    }
    if identity::is_reviewer(Some(ctx.sid), ctx.reviewers) {
        return Err(UpsertError::Reviewer(ReviewerRefused(format!(
            "steward {} is a reviewer: it cannot own projects (use its review pool)",
            pyc::repr_str(ctx.sid)
        ))));
    }
    let mut fields = fields.clone();
    let mut new_host = None;
    if let Some(h) = fields.get("host").filter(|h| !h.is_null()) {
        let h = identity::normalize_host(h);
        if !h.is_empty() && !(ctx.host_known)(&h) {
            return Err(UpsertError::Host(HostChangeRefused(format!(
                "unknown host: {} (not in hosts.json)",
                pyc::repr_str(&h)
            ))));
        }
        fields.insert("host".to_string(), Value::from(h.clone()));
        new_host = Some(h);
    }
    if let Some(other) = (ctx.owner_elsewhere)(name).filter(|o| !o.is_empty()) {
        return Err(UpsertError::Owned(OwnedElsewhere::new(name, other)));
    }
    let existing = projects.get(name);
    if existing.is_none() {
        // yeni talep: rezerve ad reddi (mevcut kayıt etkilenmez)
        let why = identity::reserved_reason(name, &(ctx.index)());
        if !why.is_empty() {
            return Err(UpsertError::Reserved(ReservedName::new(name, why)));
        }
    }
    let host_changed = existing.zip(new_host.as_ref()).is_some_and(|(p, h)| *h != p.host);
    let old_phase = existing.map(|p| p.phase.clone());
    let mut p = existing.cloned().unwrap_or_else(|| Project {
        name: name.to_string(),
        created_at: ctx.now,
        ..Project::default()
    });
    if host_changed && !ctx.force && ctx.running.and_then(|f| f()) != Some(false) {
        return Err(UpsertError::Host(HostChangeRefused(format!(
            "project {} has a running session (or its state is unknown): stop it before moving it from {} to {} (or force)",
            pyc::repr_str(name),
            pyc::repr_str(host_label(&p.host)),
            pyc::repr_str(host_label(new_host.as_deref().unwrap_or_default()))
        ))));
    }
    for (k, v) in fields.iter().filter(|(_, v)| !v.is_null()) {
        apply_field(&mut p, k, v, ctx)?;
    }
    p.updated_at = ctx.now;
    projects.insert(name.to_string(), p.clone());
    let auto_label_via = old_phase
        .filter(|o| (o == "paused" || o == "done") && (p.phase == "planned" || p.phase == "planning"))
        .map(|o| format!("phase {o}->{}", p.phase));
    Ok(Upserted { project: p, host_changed, auto_label_via })
}
