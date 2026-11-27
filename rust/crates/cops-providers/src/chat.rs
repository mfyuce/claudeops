//! Sohbet geçmişi okuyucuları (`CliProvider.last_exchange`/`full_history`/`last_message_role`/`extra_file_roots`,
//! `ucli_client.read_chat_history`). Beş ayrı biçim: claude jsonl, codex rollout jsonl, agy SQLite + protobuf, copilot
//! SQLite, ucli jsonl. Dosya ve SQLite okuması [`LiveProbe`](crate::live::LiveProbe) ile çağırandadır.
//!
//! Sözleşme (Python gibi): `None` = bu CLI'da sohbet görünümü yok ya da dosya okunamaz (ucli); boş liste / boş çift =
//! destekleniyor ama henüz mesaj yok.
//!
//! İki tarafta da claude/codex'te bozuk UTF-8, nesne olmayan satır ya da alan ve metin olmayan `text` yalnız o
//! satırı/bloğu atlatır; ucli'de bozuk bayt ya da ayrışmayan satır dosyayı okunamaz (`None`) yapar.
//! Eşlenmemiş vekil kaçışı U+FFFD olur. Dosya okumasına boyut sınırı YOKTUR (Python gibi).

use crate::live::{Live, SqlCell};
use crate::provider::Cli;
use crate::pyfmt::{is_path_part, join_path, strip};
use crate::pyjson::Py;
use std::collections::BTreeSet;

/// agy `steps.step_type`: kullanıcı turu.
pub const AGY_STEP_USER: i64 = 14;
/// agy `steps.step_type`: asistan turu.
pub const AGY_STEP_ASSISTANT: i64 = 15;
/// agy `/compact` kontrol noktası: bu tür VE yükte `<summary>` (tür tek başına kanıt değil).
pub const AGY_STEP_CHECKPOINT: i64 = 23;

/// Eskiden yeniye adımlar (parametreler: üç adım türü). Yalnız BLOB yük: bozuk metin hücresi okumayı kesmez.
pub const AGY_STEPS_SQL: &str = "SELECT step_type, step_payload FROM steps WHERE step_type IN (?, ?, ?) AND typeof(step_payload) = 'blob' ORDER BY idx";
/// Yeniden eskiye adımlar ([`AGY_STEPS_SQL`] ile aynı süzgeç).
pub const AGY_STEPS_DESC_SQL: &str = "SELECT step_type, step_payload FROM steps WHERE step_type IN (?, ?, ?) AND typeof(step_payload) = 'blob' ORDER BY idx DESC";
/// copilot oturumunun turları (tek parametre: oturum kimliği).
pub const COPILOT_TURNS_SQL: &str =
    "SELECT user_message, assistant_response FROM turns WHERE session_id = ? ORDER BY turn_index";

/// Bir sohbet satırı. claude/codex/agy'de ikisi de metindir; ucli dosyadaki `role`/`content` değerini, copilot SQLite
/// hücresini olduğu gibi geçirir (Python gibi: `null`, sayı ya da liste olabilir).
#[derive(Debug, Clone, PartialEq)]
pub struct ChatTurn {
    /// `user`, `assistant`, `summary`, `boundary` (ucli: dosyada ne yazıyorsa).
    pub role: Py,
    pub text: Py,
}

impl ChatTurn {
    fn new(role: &str, text: String) -> ChatTurn {
        ChatTurn {
            role: Py::Str(role.into()),
            text: Py::Str(text),
        }
    }
}

/// Son kullanıcı mesajı + son asistan yanıtı.
#[derive(Debug, Clone, PartialEq)]
pub struct Exchange {
    pub user: Py,
    pub assistant: Py,
}

impl Exchange {
    fn new(user: String, assistant: String) -> Exchange {
        Exchange {
            user: Py::Str(user),
            assistant: Py::Str(assistant),
        }
    }
    fn empty() -> Exchange {
        Exchange::new(String::new(), String::new())
    }
}

// ----------------------------------------------------------------------------------------------------------- ortak

/// Metin kipinde okunan jsonl'ın ham satırları (`\n`, `\r`, `\r\n`; boş parçalar çağıranda elenir).
fn raw_lines(data: &[u8]) -> impl DoubleEndedIterator<Item = &[u8]> {
    data.split(|b| matches!(b, b'\n' | b'\r'))
}

/// Satırdaki JSON NESNESİ; boş, bozuk, UTF-8 olmayan ya da nesne olmayan satır None.
fn object_line(raw: &[u8]) -> Option<Py> {
    let line = strip(std::str::from_utf8(raw).ok()?);
    if line.is_empty() {
        return None;
    }
    Py::parse(line).filter(Py::is_object)
}

/// Transkriptin son dolu satırı okunamıyor mu: UTF-8 değil, nesne olmayan JSON ya da boş nesne. JSON olarak
/// ayrışmayan (yarım) satır sayılmaz, bir önceki dolu satıra bakılır (Python gibi).
fn unreadable_tail(data: &[u8]) -> bool {
    raw_lines(data)
        .rev()
        .find_map(|raw| match std::str::from_utf8(raw) {
            Err(_) => Some(true),
            Ok(text) => {
                let line = strip(text);
                let row = (!line.is_empty()).then(|| Py::parse(line)).flatten()?;
                Some(!matches!(&row, Py::Object(entries) if !entries.is_empty()))
            }
        })
        .unwrap_or(false)
}

fn flag(row: &Py, key: &str) -> bool {
    row.get(key).is_some_and(Py::truthy)
}

fn kind(row: &Py) -> Option<&str> {
    row.get("type").and_then(Py::as_str)
}

/// İçerik listesinde türü `types` içinde olan blokların boş olmayan metinleri, boş satırla birleşik.
fn joined_blocks(blocks: &[Py], types: &[&str]) -> String {
    blocks
        .iter()
        .filter(|b| kind(b).is_some_and(|t| types.contains(&t)))
        .filter_map(|b| b.get("text").and_then(Py::as_str))
        .filter(|t| !t.is_empty())
        .collect::<Vec<_>>()
        .join("\n\n")
}

// ----------------------------------------------------------------------------------------------------------- claude

/// `message.content`ten düz metin: dize ya da blok listesi (yalnız `text` blokları).
fn claude_text(content: Option<&Py>) -> String {
    match content {
        Some(Py::Str(s)) => s.clone(),
        Some(Py::Array(blocks)) => joined_blocks(blocks, &["text"]),
        _ => String::new(),
    }
}

/// İnsan yazmış `user` satırı mı (araç sonucu `user` rolüyle kodlanır).
fn claude_real_user(content: Option<&Py>) -> bool {
    match content {
        Some(Py::Str(s)) => !strip(s).is_empty(),
        Some(Py::Array(blocks)) => !blocks.iter().any(|b| kind(b) == Some("tool_result")),
        _ => false,
    }
}

fn claude_content(row: &Py) -> Option<&Py> {
    row.get("message")?.get("content")
}

fn claude_last(data: &[u8]) -> Exchange {
    let mut rows = raw_lines(data).rev().filter_map(object_line);
    let Some(answer) = rows.find(|r| kind(r) == Some("assistant") && !flag(r, "isSidechain"))
    else {
        return Exchange::empty();
    };
    let user = rows
        // Sıkıştırma özeti kullanıcının mesajı değildir.
        .filter(|r| {
            kind(r) == Some("user")
                && !["isSidechain", "isMeta", "isCompactSummary"]
                    .iter()
                    .any(|k| flag(r, k))
        })
        .find(|r| claude_real_user(claude_content(r)))
        .map(|r| claude_text(claude_content(&r)))
        .unwrap_or_default();
    Exchange::new(user, claude_text(claude_content(&answer)))
}

/// `compactMetadata` alanının `str()` hali (alan yoksa "").
fn meta_field(meta: Option<&Py>, key: &str) -> String {
    meta.and_then(|m| m.get(key))
        .map(Py::py_str)
        .unwrap_or_default()
}

fn claude_history(data: &[u8]) -> Vec<ChatTurn> {
    let mut out = Vec::new();
    for row in raw_lines(data).filter_map(object_line) {
        let t = kind(&row);
        let sidechain = flag(&row, "isSidechain");
        let role = if t == Some("system")
            && row.get("subtype").and_then(Py::as_str) == Some("compact_boundary")
        {
            // Sıkıştırma öncesi mesajlar dosyada durur: sınır yalnız işaret ("tetikleyen, öncesi token").
            let meta = row.get("compactMetadata");
            let text = format!(
                "{}, {}",
                meta_field(meta, "trigger"),
                meta_field(meta, "preTokens")
            );
            out.push(ChatTurn::new("boundary", text));
            continue;
        } else if t == Some("user") && flag(&row, "isCompactSummary") && !sidechain {
            "summary"
        } else if t == Some("assistant") && !sidechain {
            "assistant"
        } else if t == Some("user")
            && !sidechain
            && !flag(&row, "isMeta")
            && claude_real_user(claude_content(&row))
        {
            "user"
        } else {
            continue;
        };
        let text = claude_text(claude_content(&row));
        if !text.is_empty() {
            out.push(ChatTurn::new(role, text));
        }
    }
    out
}

// ------------------------------------------------------------------------------------------------------------ codex

/// `input_text`/`output_text` blokları (akıl yürütme ve araç blokları sayılmaz).
fn codex_text(content: Option<&Py>) -> String {
    match content {
        Some(Py::Array(blocks)) => joined_blocks(blocks, &["input_text", "output_text"]),
        _ => String::new(),
    }
}

/// codex'in kendi eklediği `<environment_context>` sarmalayıcısı insan mesajı değildir.
fn codex_real_user(text: &str) -> bool {
    let trimmed = strip(text);
    !trimmed.is_empty() && !trimmed.starts_with("<environment_context>")
}

/// `response_item` + `payload.type == "message"` satırının `(role, content)`i.
fn codex_message(row: &Py) -> Option<(&str, Option<&Py>)> {
    if kind(row) != Some("response_item") {
        return None;
    }
    let payload = row.get("payload")?;
    if kind(payload) != Some("message") {
        return None;
    }
    Some((payload.get("role")?.as_str()?, payload.get("content")))
}

fn codex_last(data: &[u8]) -> Exchange {
    let mut rows = raw_lines(data).rev().filter_map(object_line);
    let answer = rows.find_map(|r| match codex_message(&r) {
        Some(("assistant", content)) => Some(codex_text(content)),
        _ => None,
    });
    let Some(answer) = answer else {
        return Exchange::empty();
    };
    let user = rows
        .find_map(|r| match codex_message(&r) {
            Some(("user", content)) => Some(codex_text(content)).filter(|t| codex_real_user(t)),
            _ => None,
        })
        .unwrap_or_default();
    Exchange::new(user, answer)
}

fn codex_history(data: &[u8]) -> Vec<ChatTurn> {
    let mut out = Vec::new();
    for row in raw_lines(data).filter_map(object_line) {
        let Some((role, content)) = codex_message(&row) else {
            continue;
        };
        let text = codex_text(content);
        let keep = match role {
            "assistant" => !text.is_empty(),
            "user" => codex_real_user(&text),
            _ => false,
        };
        if keep {
            out.push(ChatTurn::new(role, text));
        }
    }
    out
}

// -------------------------------------------------------------------------------------------------------------- agy

/// protobuf varint: `(alt 64 bit, 64 bite sığmadı mı)`; veri biterse None.
fn read_varint(data: &[u8], at: &mut usize) -> Option<(u64, bool)> {
    let (mut value, mut overflow, mut shift) = (0u64, false, 0u32);
    loop {
        let byte = *data.get(*at)?;
        *at += 1;
        let bits = u64::from(byte & 0x7f);
        if shift < 64 {
            value |= bits << shift;
            overflow |= shift > 57 && bits >> (64 - shift) != 0;
        } else {
            overflow |= bits != 0;
        }
        if byte & 0x80 == 0 {
            return Some((value, overflow));
        }
        shift = shift.saturating_add(7);
    }
}

/// Üst düzeyde `field` numaralı SON uzunluk-önekli (wire type 2) alan. Şemasız ve hoşgörülü: bozuk ya da bilinmeyen
/// türde durur ve o ana kadar bulunanı verir; veriyi aşan uzunluk kalan baytlara kırpılır.
fn bytes_field(data: &[u8], field: u64) -> Option<&[u8]> {
    let mut found = None;
    let mut at = 0usize;
    while at < data.len() {
        let Some((tag, big_tag)) = read_varint(data, &mut at) else {
            break;
        };
        match tag & 0x7 {
            0 => {
                if read_varint(data, &mut at).is_none() {
                    break;
                }
            }
            1 => at = at.saturating_add(8),
            5 => at = at.saturating_add(4),
            2 => {
                let Some((len, big_len)) = read_varint(data, &mut at) else {
                    break;
                };
                let len = if big_len {
                    usize::MAX
                } else {
                    usize::try_from(len).unwrap_or(usize::MAX)
                };
                let start = at.min(data.len());
                at = at.saturating_add(len);
                if !big_tag && tag >> 3 == field {
                    found = data.get(start..at.min(data.len()));
                }
            }
            _ => break,
        }
    }
    found
}

/// `outer` alt mesajının `inner` metni (bozuk UTF-8 U+FFFD); yoksa "".
fn nested_text(payload: &[u8], outer: u64, inner: u64) -> String {
    bytes_field(payload, outer)
        .and_then(|m| bytes_field(m, inner))
        .map(|t| String::from_utf8_lossy(t).into_owned())
        .unwrap_or_default()
}

/// Kullanıcı adımının metni (alan 19 -> 2).
fn agy_user_text(payload: &[u8]) -> String {
    nested_text(payload, 19, 2)
}

/// Asistan adımının görünür yanıtı (alan 20 -> 1; iç düşünce alan 3 bilerek atlanır).
fn agy_assistant_text(payload: &[u8]) -> String {
    nested_text(payload, 20, 1)
}

fn cell_is(cell: &SqlCell, n: i64) -> bool {
    match cell {
        SqlCell::Int(i) => *i == n,
        SqlCell::Real(f) => *f == n as f64,
        _ => false,
    }
}

/// Satır geçerli bir adımsa `(tür, yük)`: yük BLOB olmalı, kontrol noktası `<summary>` taşımalı.
fn agy_step(row: &[SqlCell]) -> Option<(i64, &[u8])> {
    let [step_type, SqlCell::Blob(payload)] = row else {
        return None;
    };
    let t = [AGY_STEP_USER, AGY_STEP_ASSISTANT, AGY_STEP_CHECKPOINT]
        .into_iter()
        .find(|n| cell_is(step_type, *n))?;
    let marker = b"<summary>";
    (t != AGY_STEP_CHECKPOINT || payload.windows(marker.len()).any(|w| w == marker))
        .then_some((t, payload.as_slice()))
}

// ---------------------------------------------------------------------------------------------------------- copilot

/// `hücre or ""`.
fn cell_or_empty(cell: &SqlCell) -> Py {
    match cell {
        SqlCell::Int(i) if *i != 0 => Py::Int(*i),
        SqlCell::Real(f) if *f != 0.0 => Py::Float(*f),
        SqlCell::Text(s) => Py::Str(s.clone()),
        // BLOB geçerli UTF-8 ise metin, değilse boş.
        SqlCell::Blob(b) => Py::Str(std::str::from_utf8(b).unwrap_or_default().to_string()),
        _ => Py::Str(String::new()),
    }
}

// ------------------------------------------------------------------------------------------------------------- ucli

/// `value or ""`.
fn value_or_empty(value: Option<&Py>) -> Py {
    value
        .filter(|v| v.truthy())
        .cloned()
        .unwrap_or_else(|| Py::Str(String::new()))
}

fn ucli_last(turns: &[ChatTurn]) -> Exchange {
    let is = |t: &ChatTurn, role: &str| t.role.as_str() == Some(role);
    let user = turns.iter().rev().find(|t| is(t, "user")).map(|t| &t.text);
    // Asistan yalnız son kullanıcı turundan SONRA gelmişse sayılır.
    let assistant = turns
        .iter()
        .rev()
        .take_while(|t| !is(t, "user"))
        .find(|t| is(t, "assistant"))
        .map(|t| &t.text);
    Exchange {
        user: value_or_empty(user),
        assistant: value_or_empty(assistant),
    }
}

// ----------------------------------------------------------------------------------------------------------- okuyucu

impl Live<'_> {
    /// Son kullanıcı mesajı + son asistan yanıtı; None = desteklenmiyor (shell) ya da ucli geçmişi okunamıyor.
    pub fn last_exchange(&self, cli: Cli, cwd: &str, sid: Option<&str>) -> Option<Exchange> {
        match cli {
            Cli::Claude => Some(claude_last(
                &self.transcript_bytes(self.jsonl_path_for(cwd, sid)),
            )),
            Cli::Codex => Some(codex_last(
                &self.transcript_bytes(self.codex_rollout_path(cwd, sid)),
            )),
            Cli::Agy => Some(self.agy_last(cwd, sid)),
            Cli::Copilot => Some(match self.copilot_turns(cwd, sid).pop() {
                Some((user, assistant)) => Exchange { user, assistant },
                None => Exchange::empty(),
            }),
            Cli::Ucli => self
                .full_history(cli, cwd, sid)
                .map(|turns| ucli_last(&turns)),
            Cli::Shell => None,
        }
    }

    /// Bütün konuşma, eskiden yeniye; None = desteklenmiyor (shell), ucli'de kimlik yok ya da dosya okunamıyor.
    pub fn full_history(&self, cli: Cli, cwd: &str, sid: Option<&str>) -> Option<Vec<ChatTurn>> {
        match cli {
            Cli::Claude => Some(claude_history(
                &self.transcript_bytes(self.jsonl_path_for(cwd, sid)),
            )),
            Cli::Codex => Some(codex_history(
                &self.transcript_bytes(self.codex_rollout_path(cwd, sid)),
            )),
            Cli::Agy => Some(self.agy_history(cwd, sid)),
            Cli::Copilot => {
                let mut out = Vec::new();
                for (user, assistant) in self.copilot_turns(cwd, sid) {
                    for (role, text) in [("user", user), ("assistant", assistant)] {
                        if text.truthy() {
                            out.push(ChatTurn {
                                role: Py::Str(role.into()),
                                text,
                            });
                        }
                    }
                }
                Some(out)
            }
            Cli::Ucli => self.read_chat_history(cwd, sid.filter(|s| !s.is_empty())?),
            Cli::Shell => None,
        }
    }

    /// Kronolojik olarak son satırın rolü (takılma tespiti); None = bilinmiyor. claude/codex'te son satır okunamıyorsa,
    /// ucli'de yarım yazılmışsa da bilinmiyor: öncekine bakıp oturum yeniden açılmaz.
    pub fn last_message_role(&self, cli: Cli, cwd: &str, sid: Option<&str>) -> Option<Py> {
        let history = match cli {
            Cli::Claude | Cli::Codex => {
                let path = match cli {
                    Cli::Claude => self.jsonl_path_for(cwd, sid),
                    _ => self.codex_rollout_path(cwd, sid),
                };
                let data = self.transcript_bytes(path);
                if unreadable_tail(&data) {
                    return None;
                }
                match cli {
                    Cli::Claude => claude_history(&data),
                    _ => codex_history(&data),
                }
            }
            Cli::Ucli => {
                let (turns, half) = self.ucli_turns(cwd, sid.filter(|s| !s.is_empty())?)?;
                if half {
                    return None;
                }
                turns
            }
            _ => self.full_history(cli, cwd, sid)?,
        };
        let role = history.into_iter().next_back()?.role;
        (role != Py::Null).then_some(role)
    }

    /// Dosya gezgini için CLI'ya özgü ek kökler `(anahtar, mutlak yol)`; yol var olmayabilir.
    pub fn extra_file_roots(&self, cli: Cli, cwd: &str) -> Vec<(&'static str, String)> {
        match cli {
            Cli::Claude => vec![("claude-transcripts", self.probe.claude_project_dir(cwd))],
            _ => Vec::new(),
        }
    }

    /// ucli `{session}.jsonl`: dosya yoksa boş liste; okunamaz ya da bozuksa None. `role`süz satır (şema başlığı)
    /// atlanır; `role` olup `content` olmayan satır dosyayı bozuk sayar. Yazım sürerken yarım kalan SON satır (satır sonu
    /// yok ve ayrışmıyor) atlanır.
    pub fn read_chat_history(&self, cwd: &str, session: &str) -> Option<Vec<ChatTurn>> {
        self.ucli_turns(cwd, session).map(|(turns, _)| turns)
    }

    /// [`Live::read_chat_history`] gövdesi: `(turlar, yarım son satır atlandı mı)`.
    fn ucli_turns(&self, cwd: &str, session: &str) -> Option<(Vec<ChatTurn>, bool)> {
        if session.contains(['/', '\0']) {
            return None; // yol parçası olamayan ad: okunamaz sayılır, dizinin dışı okunmaz
        }
        let path = self.find_chat_file(cwd, &format!("{session}.jsonl"));
        if !self.probe.is_file(&path) {
            return Some((Vec::new(), false));
        }
        let data = self.probe.read_bytes(&path, u64::MAX)?;
        let mut out = Vec::new();
        let mut pieces = data.split(|b| matches!(b, b'\n' | b'\r')).peekable();
        while let Some(raw) = pieces.next() {
            let line = std::str::from_utf8(raw).ok().map(strip);
            if line == Some("") {
                continue;
            }
            let Some(turn) = line.and_then(Py::parse) else {
                return pieces.peek().is_none().then_some((out, true));
            };
            let Some(role) = turn.get("role") else {
                continue;
            };
            out.push(ChatTurn {
                role: role.clone(),
                text: turn.get("content")?.clone(),
            });
        }
        Some((out, false))
    }

    /// Transkriptin tamamı; yol yoksa ya da okunamazsa boş.
    fn transcript_bytes(&self, path: Option<String>) -> Vec<u8> {
        path.filter(|p| !p.is_empty())
            .and_then(|p| self.probe.read_bytes(&p, u64::MAX))
            .unwrap_or_default()
    }

    /// Konuşma veritabanı (dosya varsa).
    fn agy_db(&self, cwd: &str, sid: Option<&str>) -> Option<String> {
        let id = match sid.filter(|s| !s.is_empty()) {
            Some(s) => s.to_string(),
            None => self
                .agy_resume_id(cwd, &BTreeSet::new(), "")
                .filter(|s| !s.is_empty())?,
        };
        if !is_path_part(&id) {
            return None;
        }
        let path = join_path(&self.paths.agy_conversations_dir(), &format!("{id}.db"));
        self.probe.is_file(&path).then_some(path)
    }

    /// Adımları gezer; `false` dönen ziyaretçi okumayı keser. Dönüş: SQLite hatası çıkmadı.
    fn agy_steps(&self, db: &str, sql: &str, visit: &mut dyn FnMut(i64, &[u8]) -> bool) -> bool {
        let types = [AGY_STEP_USER, AGY_STEP_ASSISTANT, AGY_STEP_CHECKPOINT].map(SqlCell::Int);
        self.probe
            .sqlite_rows(db, sql, &types, &mut |row| match agy_step(&row) {
                Some((t, payload)) => visit(t, payload),
                None => true,
            })
    }

    /// Sondan tembel okuma: son asistan metni ve ondan önceki ilk kullanıcı adımı. Hata, bulunanı silmez.
    fn agy_last(&self, cwd: &str, sid: Option<&str>) -> Exchange {
        let Some(db) = self.agy_db(cwd, sid) else {
            return Exchange::empty();
        };
        let mut answer: Option<String> = None;
        let mut user = String::new();
        self.agy_steps(&db, AGY_STEPS_DESC_SQL, &mut |t, payload| {
            if answer.is_none() {
                if t == AGY_STEP_ASSISTANT {
                    answer = Some(agy_assistant_text(payload)).filter(|a| !a.is_empty());
                }
                true
            } else if t == AGY_STEP_USER {
                user = agy_user_text(payload);
                false
            } else {
                true
            }
        });
        match answer {
            Some(answer) => Exchange::new(user, answer),
            None => Exchange::empty(),
        }
    }

    fn agy_history(&self, cwd: &str, sid: Option<&str>) -> Vec<ChatTurn> {
        let Some(db) = self.agy_db(cwd, sid) else {
            return Vec::new();
        };
        let mut out = Vec::new();
        let complete = self.agy_steps(&db, AGY_STEPS_SQL, &mut |t, payload| {
            let (role, text) = match t {
                AGY_STEP_USER => ("user", agy_user_text(payload)),
                AGY_STEP_ASSISTANT => ("assistant", agy_assistant_text(payload)),
                // Yalnız sınır işareti; özet metni şemasız okunmaz.
                _ => {
                    out.push(ChatTurn::new("boundary", String::new()));
                    return true;
                }
            };
            if !text.is_empty() {
                out.push(ChatTurn::new(role, text));
            }
            true
        });
        if complete {
            out
        } else {
            Vec::new()
        }
    }

    /// `(kullanıcı, asistan)` turları; veritabanı yok ya da SQLite hatasında boş.
    fn copilot_turns(&self, cwd: &str, sid: Option<&str>) -> Vec<(Py, Py)> {
        let session = match sid.filter(|s| !s.is_empty()) {
            Some(s) => Some(s.to_string()),
            None => self
                .copilot_resume_id(cwd, &BTreeSet::new())
                .filter(|s| !s.is_empty()),
        };
        let Some(session) = session else {
            return Vec::new();
        };
        let mut out = Vec::new();
        let complete = self.probe.sqlite_rows(
            &self.paths.copilot_session_db(),
            COPILOT_TURNS_SQL,
            &[SqlCell::Text(session)],
            &mut |row| {
                if let [user, assistant] = row.as_slice() {
                    out.push((cell_or_empty(user), cell_or_empty(assistant)));
                }
                true
            },
        );
        if complete {
            out
        } else {
            Vec::new()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn varint(mut n: u64) -> Vec<u8> {
        let mut out = Vec::new();
        loop {
            let byte = (n & 0x7f) as u8;
            n >>= 7;
            out.push(if n == 0 { byte } else { byte | 0x80 });
            if n == 0 {
                return out;
            }
        }
    }

    fn field(no: u64, data: &[u8]) -> Vec<u8> {
        let mut out = varint((no << 3) | 2);
        out.extend(varint(data.len() as u64));
        out.extend_from_slice(data);
        out
    }

    #[test]
    fn varint_limits() {
        let read = |b: &[u8]| read_varint(b, &mut 0);
        assert_eq!(read(&varint(u64::MAX)), Some((u64::MAX, false)));
        // 2^64: alt bitler 0, taşma işaretli
        assert_eq!(
            read(&[0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x02]),
            Some((0, true))
        );
        // sıfır dolgulu uzun varint taşma değildir
        let mut padded = vec![0x80u8; 1000];
        padded.push(0);
        assert_eq!(read(&padded), Some((0, false)));
        assert_eq!(read(&[0x80, 0x80]), None);
        assert_eq!(read(&[]), None);
    }

    #[test]
    fn huge_length_and_field_number_do_not_wrap() {
        let mut data = varint((19 << 3) | 2);
        data.extend(varint(u64::MAX));
        data.extend_from_slice(b"abc");
        assert_eq!(bytes_field(&data, 19), Some(&b"abc"[..]));
        // 64 biti aşan etiketin alt bitleri 19'a benzese de alan eşleşmez
        let mut tag = vec![0x9a, 0x81, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x02];
        tag.extend([1, b'x']);
        assert_eq!(bytes_field(&tag, 19), None);
    }

    #[test]
    fn truncated_and_mutated_protobuf_never_panics() {
        let good = field(19, &field(2, "merhaba ğ".as_bytes()));
        assert_eq!(agy_user_text(&good), "merhaba ğ");
        let mut seed = 0x2545_f491_4f6c_dd1du64;
        for round in 0..20_000 {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            let mut bad = good.clone();
            let at = (seed as usize) % bad.len();
            if round % 2 == 0 {
                bad[at] = (seed >> 24) as u8;
            } else {
                bad.truncate(at);
                bad.extend_from_slice(&seed.to_le_bytes());
            }
            let _ = (agy_user_text(&bad), agy_assistant_text(&bad));
        }
    }

    #[test]
    fn broken_transcript_lines_are_skipped_not_fatal() {
        let data = b"[1]\n\xff\xfe\n{\"type\":\"user\",\"message\":\"x\"}\n{\"type\":\"user\",\"message\":{\"content\":\"soru\"}}\n{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":5},{\"type\":\"text\",\"text\":\"cevap\"}]}}\n\"x\"\n{\"type\":\"assist";
        assert_eq!(
            claude_last(data),
            Exchange::new("soru".into(), "cevap".into())
        );
        let roles: Vec<Py> = claude_history(data).into_iter().map(|t| t.role).collect();
        assert_eq!(roles, [Py::Str("user".into()), Py::Str("assistant".into())]);
    }
}
