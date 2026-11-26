//! Günlük özet ve ölçüm raporu (grup 4): günlük kayıtlarından markdown. SAF; günlük dosyasını okumak/yazmak
//! çağırandadır.

use crate::cards::{str_or_empty, BadValue};
use crate::consts_gen::*;
use crate::identity::{self, InvalidStewardId, PathsArg};
use crate::prompts::{bad, clip, items_of};
use crate::pyc;
use crate::recovery::{int_of, truthy_at};
use crate::types::Project;
use indexmap::IndexMap;
use serde_json::{Map, Value};

type Doc = Map<String, Value>;

/// py: daily_path
pub fn daily_path(base: &str, date: &str, paths: PathsArg<'_>) -> Result<String, InvalidStewardId> {
    Ok(pyc::path_join(&identity::pp(base, paths)?.daily, &format!("{date}.md")))
}

/// `d[key]`
fn required<'a>(d: &'a Value, key: &str) -> Result<&'a Value, BadValue> {
    d.get(key).ok_or_else(|| BadValue(format!("missing key: {key}")))
}

fn number(d: &Value, key: &str) -> Result<f64, BadValue> {
    let v = required(d, key)?;
    v.as_f64().ok_or_else(|| bad(v))
}

/// Anahtarları verilen sayıya göre büyükten küçüğe (eşitlikte ekleme sırası) dizer.
fn by_count(map: &Doc, count: impl Fn(&Value) -> Result<f64, BadValue>) -> Result<Vec<(&String, &Value)>, BadValue> {
    let mut rows = Vec::new();
    for (k, v) in map {
        rows.push((count(v)?, k, v));
    }
    rows.sort_by(|a, b| b.0.total_cmp(&a.0));
    Ok(rows.into_iter().map(|(_, k, v)| (k, v)).collect())
}

/// Ölçüm (dry) raporunun metni. `rep`: `{tür: {count, names:{ad:n}, chars, first, last}}`.
///
/// py: dry_report_text
pub fn dry_report_text(rep: &Doc, hours: f64, lang: &str) -> Result<String, BadValue> {
    let span = hours.trunc();
    let en = lang == "en";
    if rep.is_empty() {
        return Ok(if en {
            format!("No `would:*` events in the last {span} hours.\n")
        } else {
            format!("Son {span} saatte `would:*` olayı yok.\n")
        });
    }
    let mut lines = vec![if en {
        format!("Measurement (dry) modes, last {span} hours:")
    } else {
        format!("Ölçüm (dry) kipleri, son {span} saat:")
    }];
    for (kind, r) in by_count(rep, |r| number(r, "count"))? {
        let names = required(r, "names")?;
        let names = names.as_object().ok_or_else(|| bad(names))?;
        let top: Vec<String> = by_count(names, |c| c.as_f64().ok_or_else(|| bad(c)))?
            .into_iter()
            .take(3)
            .map(|(n, c)| format!("{n}×{}", pyc::str_of(c)))
            .collect();
        let chars = required(r, "chars")?;
        let (unit, events) = if en { ("characters", "events") } else { ("karakter", "olay") };
        let extra = if pyc::truthy(chars) { format!(", ~{} {unit}", pyc::str_of(chars)) } else { String::new() };
        let kip = DRY_KIPS.get(kind).and_then(Value::as_str).map(|k| format!(" [{k}]")).unwrap_or_default();
        let count = pyc::str_of(required(r, "count")?);
        lines.push(format!("- would:{kind}{kip}: {count} {events}{extra} ({})", top.join(", ")));
    }
    Ok(lines.join("\n") + "\n")
}

/// "act?" sorusu sorulacak ölçüm kipleri (ayar anahtarı), sıralı.
///
/// py: dry_ask_due
pub fn dry_ask_due(rep: &Doc, asked: &Value, now: f64, hours: f64) -> Result<Vec<String>, BadValue> {
    let asked = items_of(Some(asked))?;
    if let Some(unhashable) = asked.iter().find(|v| v.is_array() || v.is_object()) {
        return Err(bad(unhashable));
    }
    let mut due: Vec<String> = Vec::new();
    for (kind, r) in rep {
        let Some(key) = DRY_KIPS.get(kind).and_then(Value::as_str) else { continue };
        if !asked.iter().any(|a| a.as_str() == Some(key))
            && !due.iter().any(|d| d == key)
            && now - number(r, "first")? >= hours * 3600.0
        {
            due.push(key.to_string());
        }
    }
    due.sort();
    Ok(due)
}

/// Bugünün (yerel) günlük özeti yazılmalı mı: tarih, yoksa "".
///
/// py: summary_due
pub fn summary_due(state: &Doc, now: f64, hour: i64) -> String {
    use chrono::Timelike;
    let local = pyc::localtime(now);
    let today = local.format("%Y-%m-%d").to_string();
    if i64::from(local.hour()) >= hour && state.get("summary_date").and_then(Value::as_str) != Some(today.as_str()) {
        today
    } else {
        String::new()
    }
}

/// İlk `n` tekil, boş olmayan ad; kalanı "+k".
///
/// py: _names
pub fn names_line(names: &[String], n: usize) -> String {
    let mut unique: Vec<&str> = Vec::new();
    for name in names {
        if !name.is_empty() && !unique.contains(&name.as_str()) {
            unique.push(name);
        }
    }
    let shown = unique.iter().take(n).copied().collect::<Vec<_>>().join(", ");
    if unique.len() > n {
        format!("{shown} +{}", unique.len() - n)
    } else {
        shown
    }
}

/// `key` değerine göre sayım: "a 2, b 1" (ada göre sıralı).
///
/// py: _kind_counts
pub fn kind_counts(entries: &[&Doc], key: &str) -> String {
    let mut counts = std::collections::BTreeMap::<String, usize>::new();
    for e in entries {
        let value = e.get(key).filter(|v| pyc::truthy(v)).map_or_else(|| "?".to_string(), pyc::str_of);
        *counts.entry(value).or_default() += 1;
    }
    counts.iter().map(|(k, v)| format!("{k} {v}")).collect::<Vec<_>>().join(", ")
}

/// `str(e.get(key))`
fn shown(e: &Doc, key: &str) -> String {
    pyc::str_of(e.get(key).unwrap_or(&Value::Null))
}

fn is_text(e: &Doc, key: &str, want: &str) -> bool {
    e.get(key).and_then(Value::as_str) == Some(want)
}

fn ask_gate_rows(events: &[&Doc], answered_by: &IndexMap<String, String>, en: bool) -> Vec<String> {
    if events.is_empty() {
        return Vec::new();
    }
    let applied: Vec<&&Doc> = events.iter().filter(|e| truthy_at(e, "applied")).collect();
    // yazılan cevap bir kez (uygulanan) sayılır
    let shadow: Vec<&&Doc> =
        events.iter().filter(|e| is_text(e, "mode", "shadow") && !truthy_at(e, "applied")).collect();
    let denied = events.len() as i64 - applied.len() as i64 - shadow.len() as i64;
    let passed = shadow.iter().filter(|e| truthy_at(e, "allow")).count();
    let head = if en {
        format!(
            "- ASK gate: brain answered for the owner {}, refused {denied}, shadow {} ({passed} would pass)",
            applied.len(),
            shadow.len()
        )
    } else {
        format!(
            "- ASK kapısı: beyin sahip adına {}, kapıdan dönen {denied}, gölge {} (geçerdi {passed})",
            applied.len(),
            shadow.len()
        )
    };
    let mut out = vec![head];
    for e in applied {
        let over = !matches!(answered_by.get(&shown(e, "id")).map_or("", String::as_str), "" | "brain");
        let mark = match (over, en) {
            (false, _) => "",
            (true, true) => " (overridden by owner)",
            (true, false) => " (sahip ezdi)",
        };
        let cut = |key: &str| clip(&str_or_empty(e.get(key)), 120);
        out.push(format!(
            "  - [{}] {}: {} → {}{mark}",
            shown(e, "id"),
            shown(e, "project"),
            cut("question"),
            cut("answer")
        ));
    }
    out
}

/// Günün ASK kapısı kayıtları: beynin sahip adına yazdığı cevaplar (sahip sonradan ezdiyse işaretli) + sayılar.
///
/// py: _ask_gate_lines
pub fn ask_gate_lines(events: &[Doc], answered_by: &IndexMap<String, String>, en: bool) -> Vec<String> {
    ask_gate_rows(&events.iter().collect::<Vec<_>>(), answered_by, en)
}

/// `daily_summary`in depodan gelen ekleri.
#[derive(Debug, Clone, Copy, Default)]
pub struct SummaryExtras<'a> {
    /// Açık soru / yeni fikir / bekleyen madde / iletilmemiş cevap sayıları.
    pub pending: Option<&'a Doc>,
    /// Sahipsiz kaynak sayıları (`servers`, `procs`).
    pub orphans: Option<&'a Doc>,
    pub answered_by: Option<&'a IndexMap<String, String>>,
}

fn event<'a>(day: &[&'a Doc], name: &str) -> Vec<&'a Doc> {
    day.iter().copied().filter(|e| is_text(e, "event", name)).collect()
}

fn sum_of(entries: &[&Doc], key: &str) -> Result<i64, BadValue> {
    entries.iter().try_fold(0_i64, |acc, e| Ok(acc.saturating_add(int_of(e.get(key))?)))
}

fn names_of(entries: &[&Doc]) -> String {
    names_line(&entries.iter().map(|e| shown(e, "name")).collect::<Vec<_>>(), 5)
}

/// Mod satırı ve tick satırı.
fn tick_lines(day: &[&Doc], text: &dyn Fn(&str) -> String, lines: &mut Vec<String>) -> Result<(), BadValue> {
    let ticks = event(day, "tick");
    let folded = event(day, "ticks"); // sıkıştırma sonrası: o günün tick'leri tek toplam satırında
    let mode = ticks.iter().chain(&folded).rev().find(|e| truthy_at(e, "mode")).map(|e| shown(e, "mode"));
    let count = (ticks.len() as i64).saturating_add(sum_of(&folded, "n")?);
    if let Some(mode) = mode.filter(|m| !m.is_empty()) {
        let note = if mode == "observe" { format!(" ({})", text("obs_note")) } else { String::new() };
        lines.push(format!("{}: **{mode}**{note}", text("mode")));
    }
    lines.push(String::new());
    if count == 0 {
        lines.push(format!("- {}: {}", text("ticks"), text("no_ticks")));
        return Ok(());
    }
    let by_hand = ticks.iter().filter(|e| !is_text(e, "trigger", "timer")).count() as i64;
    let manual = by_hand.saturating_add(sum_of(&folded, "manual")?);
    let failed = ticks.iter().filter(|e| truthy_at(e, "error")).count() as i64;
    let bad_ticks = failed.saturating_add(sum_of(&folded, "errors")?);
    let extra: Vec<String> = [(manual, "manual"), (bad_ticks, "errors")]
        .iter()
        .filter(|(n, _)| *n != 0)
        .map(|(n, key)| format!("{n} {}", text(key)))
        .collect();
    let tail = if extra.is_empty() { String::new() } else { format!(" ({})", extra.join(", ")) };
    lines.push(format!("- {}: {count}{tail}", text("ticks")));
    Ok(())
}

/// `log.jsonl` kayıtlarından (o güne ait olanlar süzülür) bir günün markdown özeti.
///
/// py: daily_summary
pub fn daily_summary(entries: &[Doc], date: &str, lang: &str, extras: SummaryExtras<'_>) -> Result<String, BadValue> {
    let en = lang == "en";
    let table = P_SUMMARY_TXT.get(if en { "en" } else { "tr" });
    let text = |key: &str| table.and_then(|t| t.get(key)).and_then(Value::as_str).unwrap_or("").to_string();
    let day: Vec<&Doc> =
        entries.iter().filter(|e| e.get("ts").map(pyc::str_of).unwrap_or_default().starts_with(date)).collect();
    let actions = event(&day, "action");
    let would: Vec<(&Doc, String)> = day
        .iter()
        .filter_map(|e| {
            let name = e.get("event").map(pyc::str_of).unwrap_or_default();
            name.strip_prefix("would:").map(|kind| (*e, kind.to_string()))
        })
        .collect();
    let done = |kind: &str| -> Vec<&Doc> {
        actions.iter().copied().filter(|e| is_text(e, "kind", kind) && truthy_at(e, "ok")).collect()
    };
    let with_event = |kind: &str, name: &str| {
        let mut all = done(kind);
        all.extend(event(&day, name));
        all
    };
    let asks = with_event("ask_user", "ask");
    let ideas = with_event("idea", "idea");
    let cards = event(&day, "card");
    let phases = done("set_phase");
    let handovers = with_event("handover", "handover");
    let applied: Vec<&Doc> = actions
        .iter()
        .copied()
        .filter(|e| !["ask_user", "idea", "set_phase"].iter().any(|k| is_text(e, "kind", k)))
        .collect();

    let mut lines = vec![format!("# {} \u{2014} {date}", text("title"))];
    tick_lines(&day, &text, &mut lines)?;
    if !applied.is_empty() {
        let failed = applied.iter().filter(|e| !truthy_at(e, "ok")).count();
        let tail = if failed != 0 { format!(" ({failed} {})", text("failed")) } else { String::new() };
        let counts = kind_counts(&applied, "kind");
        lines.push(format!("- {}: {} \u{2014} {counts}{tail}", text("applied"), applied.len()));
    }
    if !would.is_empty() {
        let mut per_kind = std::collections::BTreeMap::<&str, Vec<String>>::new();
        for (e, kind) in &would {
            per_kind.entry(kind).or_default().push(str_or_empty(e.get("name")));
        }
        let parts: Vec<String> = per_kind
            .iter()
            .map(|(kind, names)| {
                let list = names_line(names, 5);
                let tail = if list.is_empty() { list } else { format!(" ({list})") };
                format!("{kind} {}{tail}", names.len())
            })
            .collect();
        lines.push(format!("- {}: {} \u{2014} {}", text("would"), would.len(), parts.join("; ")));
    }
    let answers = event(&day, "answer");
    if !asks.is_empty() || !answers.is_empty() {
        lines.push(format!(
            "- {}: {} {}, {} {}",
            text("questions"),
            asks.len(),
            text("opened"),
            answers.len(),
            text("answered")
        ));
    }
    let nobody = IndexMap::new();
    lines.extend(ask_gate_rows(&event(&day, "ask_gate"), extras.answered_by.unwrap_or(&nobody), en));
    if !ideas.is_empty() {
        lines.push(format!("- {}: {} {}", text("ideas"), ideas.len(), text("new")));
    }
    if !cards.is_empty() {
        let (ok, failed): (Vec<&Doc>, Vec<&Doc>) = cards.iter().copied().partition(|e| truthy_at(e, "ok"));
        let list = if ok.is_empty() { String::new() } else { format!(" ({})", names_of(&ok)) };
        let tail = if failed.is_empty() { String::new() } else { format!(", {} {}", failed.len(), text("failed")) };
        lines.push(format!("- {}: {} {}{list}{tail}", text("cards"), ok.len(), text("refreshed")));
    }
    if !handovers.is_empty() {
        lines.push(format!("- {}: {} ({})", text("handovers"), handovers.len(), names_of(&handovers)));
    }
    if let Some(held) = event(&day, "review_store_held").last() {
        let label = if en {
            "review store: files held back by the secret scan"
        } else {
            "review saklama: gizli değer taramasında dışarıda kalan dosya"
        };
        let files: Vec<String> = items_of(held.get("files"))?.iter().map(pyc::str_of).collect();
        lines.push(format!("- {label}: {} ({})", int_of(held.get("n"))?, names_line(&files, 5)));
    }
    let directives = event(&day, "directive");
    if !directives.is_empty() {
        lines.push(format!("- {}: {} ({})", text("directives"), directives.len(), names_of(&directives)));
    }
    let (tours, skips) = (event(&day, "tour").len(), event(&day, "skip").len());
    if tours != 0 || skips != 0 {
        // tur başına skip oranı yüksekse maddeler gereksiz turlanıyor demektir
        let ratio = if tours != 0 {
            let pct = pyc::round((100 * skips) as f64 / tours as f64);
            if en {
                format!("{pct}%")
            } else {
                format!("%{pct}")
            }
        } else {
            "-".to_string()
        };
        let sent = directives.len();
        lines.push(if en {
            format!("- brain tours: {tours} tours, {skips} skips ({ratio}), {sent} directives")
        } else {
            format!("- beyin turu: {tours} tur, {skips} skip ({ratio}), {sent} direktif")
        });
    }
    if !phases.is_empty() {
        let list: Vec<String> =
            phases.iter().map(|e| format!("{} ({})", shown(e, "name"), shown(e, "reason"))).collect();
        lines.push(format!("- {}: {}", text("phases"), names_line(&list, 8)));
    }
    let count = |d: &Doc, key: &str| d.get(key).map_or_else(|| "0".to_string(), pyc::str_of);
    if let Some(p) = extras.pending {
        lines.push(format!(
            "- {}: {} {}, {} {}, {} {}, {} {}",
            text("pending"),
            count(p, "open_questions"),
            text("open_q"),
            count(p, "ideas_new"),
            text("ideas_new"),
            count(p, "pending_items"),
            text("items"),
            count(p, "undelivered_answers"),
            text("undelivered")
        ));
    }
    if let Some(o) = extras.orphans.filter(|o| truthy_at(o, "servers") || truthy_at(o, "procs")) {
        lines.push(format!(
            "- {}: {} {}, {} {}",
            text("orphans"),
            count(o, "servers"),
            text("orph_servers"),
            count(o, "procs"),
            text("orph_procs")
        ));
    }
    Ok(lines.join("\n") + "\n")
}

/// Faz başına proje sayısı (bilinen fazlar sıfır da olsa listelenir).
///
/// py: summarize_projects
pub fn summarize_projects(projects: &IndexMap<String, Project>) -> IndexMap<String, i64> {
    let mut out: IndexMap<String, i64> = PHASES.iter().map(|p| (p.to_string(), 0)).collect();
    for p in projects.values() {
        *out.entry(p.phase.clone()).or_default() += 1;
    }
    out
}
