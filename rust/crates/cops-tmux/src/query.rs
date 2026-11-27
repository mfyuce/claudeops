//! Salt okuma: oturum/pane listesi, capture, boyut, istemciler.

use crate::mask::tty_is_masked;
use crate::runner::{escape_arg, exact_target, Tmux};
use crate::text::{py_split, py_splitlines, py_strip, strip_ansi};
use crate::TmuxError;

/// `data/tmux.conf`un `history-limit` değeriyle aynı.
pub const HISTORY_LIMIT: u32 = 2000;

/// Python `_SNAPSHOT_FORMAT`.
pub const SNAPSHOT_FORMAT: &str =
    "#{pane_width} #{pane_height} #{history_size} #{alternate_on} #{pane_tty}";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PaneSize {
    pub cols: u32,
    pub rows: u32,
    pub history_size: u32,
    /// Alternate screen'de `history_size` yapısal olarak ~0'da kalır.
    pub alternate_on: bool,
}

/// Boyut + görünür ekran, tek tmux sürecinde (aynı andan).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Snapshot {
    pub size: PaneSize,
    pub tty: String,
    /// Yalnız görünür satırlar, renkli (`-e`), her satır `\n` ile biter.
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionInfo {
    pub name: String,
    /// Unix saniyesi.
    pub created: i64,
    /// Bağlı terminal istemcisi sayısı.
    pub attached: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PaneInfo {
    pub session: String,
    pub pane_pid: u32,
    pub tty: String,
    /// Ön plan sürecinin adı.
    pub current_command: String,
    /// Ön plan sürecinin çalışma dizini (tmux bilemiyorsa boş).
    pub cwd: String,
}

// Serbest metin (ad, yol) sona: önceki alanlarda sekme olamaz. tmux oturum adındaki denetim karakterlerini kaçırır.
const SESSION_FORMAT: &str = "#{session_created}\t#{session_attached}\t#{session_name}";
// Yol satır sonu içerebilir: pane kaydı satırla değil [`RECORD_END`] + satır sonuyla biter.
const PANE_FORMAT: &str =
    "#{pane_pid}\t#{pane_tty}\t#{pane_current_command}\t#{session_name}\t#{pane_current_path}\u{241e}";
const RECORD_END: &str = "\u{241e}\n";

fn num<T: std::str::FromStr>(s: &str) -> Result<T, TmuxError> {
    s.parse().map_err(|_| TmuxError::BadOutput)
}

fn parse_size(fields: &[&str]) -> Result<PaneSize, TmuxError> {
    match fields {
        [w, h, hist, alt] => Ok(PaneSize {
            cols: num(w)?,
            rows: num(h)?,
            history_size: num(hist)?,
            // Python `bool(int(alt))`: 0 dışındaki her tamsayı doğru.
            alternate_on: num::<i64>(alt)? != 0,
        }),
        _ => Err(TmuxError::BadOutput),
    }
}

fn parse_session(line: &str) -> Result<SessionInfo, TmuxError> {
    let mut f = line.splitn(3, '\t');
    match (f.next(), f.next(), f.next()) {
        (Some(created), Some(attached), Some(name)) => Ok(SessionInfo {
            name: name.to_string(),
            created: num(created)?,
            attached: num(attached)?,
        }),
        _ => Err(TmuxError::BadOutput),
    }
}

fn parse_pane(line: &str) -> Result<PaneInfo, TmuxError> {
    let mut f = line.splitn(5, '\t');
    match (f.next(), f.next(), f.next(), f.next(), f.next()) {
        (Some(pid), Some(tty), Some(cmd), Some(session), Some(cwd)) => Ok(PaneInfo {
            session: session.to_string(),
            pane_pid: num(pid)?,
            tty: tty.to_string(),
            current_command: cmd.to_string(),
            cwd: cwd.to_string(),
        }),
        _ => Err(TmuxError::BadOutput),
    }
}

/// [`Tmux::snapshot`] çıktısı: ilk satır [`SNAPSHOT_FORMAT`] (pty boş olabilir), gerisi ekran.
fn parse_snapshot(out: &str) -> Result<Snapshot, TmuxError> {
    let (head, text) = out.split_once('\n').ok_or(TmuxError::BadOutput)?;
    let fields: Vec<&str> = head.splitn(5, ' ').collect();
    if fields.len() != 5 {
        return Err(TmuxError::BadOutput);
    }
    Ok(Snapshot {
        size: parse_size(&fields[..4])?,
        tty: fields[4].trim().to_string(),
        text: text.to_string(),
    })
}

fn lines(out: &str) -> impl Iterator<Item = &str> {
    out.split('\n').filter(|l| !l.is_empty())
}

fn parse_panes(out: &str) -> Result<Vec<PaneInfo>, TmuxError> {
    out.split_terminator(RECORD_END).map(parse_pane).collect()
}

impl Tmux {
    /// `Ok(false)` = tmux "yok" dedi; `Err` = soruya cevap alınamadı (bilinmiyor).
    pub fn has_session(&self, name: &str) -> Result<bool, TmuxError> {
        match self.run(&["has-session", "-t", &exact_target(name)?]) {
            Ok(_) => Ok(true),
            Err(TmuxError::Failed { .. }) => Ok(false),
            Err(e) => Err(e),
        }
    }

    /// Soketteki tüm oturumlar. Sunucu çalışmıyorsa `Failed`.
    pub fn list_sessions(&self) -> Result<Vec<SessionInfo>, TmuxError> {
        lines(&self.text_utf8(&["list-sessions", "-F", SESSION_FORMAT])?)
            .map(parse_session)
            .collect()
    }

    /// Soketteki tüm pane'ler (pid, tty, komut, cwd).
    pub fn list_panes(&self) -> Result<Vec<PaneInfo>, TmuxError> {
        parse_panes(&self.text_utf8(&["list-panes", "-a", "-F", PANE_FORMAT])?)
    }

    /// Tek oturumun tüm pencerelerindeki pane'ler.
    pub fn session_panes(&self, name: &str) -> Result<Vec<PaneInfo>, TmuxError> {
        let target = exact_target(name)?;
        parse_panes(&self.text_utf8(&["list-panes", "-s", "-t", &target, "-F", PANE_FORMAT])?)
    }

    /// Son `history` geçmiş satırı + görünür alan, ANSI korunur (`-e`). Eşleştirme için [`Tmux::capture_plain`].
    pub fn capture(&self, name: &str, history: u32) -> Result<String, TmuxError> {
        self.capture_with(name, history, false)
    }

    /// [`Tmux::capture`], tmux'un sardığı uzun satırlar tek satır (`-J`; Python `tmux_capture(join=True)`). Yalnız metin
    /// aramak için: ekran yerleşimine bakan okuyucular (giriş kutusu, diyalog) [`Tmux::capture`] kullanır.
    pub fn capture_joined(&self, name: &str, history: u32) -> Result<String, TmuxError> {
        self.capture_with(name, history, true)
    }

    fn capture_with(&self, name: &str, history: u32, join: bool) -> Result<String, TmuxError> {
        let target = exact_target(name)?;
        let start = format!("-{history}");
        let mut args = vec!["capture-pane", "-t", &target, "-e", "-p", "-S", &start];
        if join {
            args.push("-J");
        }
        self.run(&args)?.text()
    }

    /// [`Tmux::capture`] + [`strip_ansi`].
    pub fn capture_plain(&self, name: &str, history: u32) -> Result<String, TmuxError> {
        Ok(strip_ansi(&self.capture(name, history)?))
    }

    /// Pane'in küçük bir aralığı: 0 = görünür ilk satır, negatif = geçmiş (-1 en yeni).
    pub fn capture_range(&self, name: &str, start: i64, end: i64) -> Result<String, TmuxError> {
        let (start, end) = (start.to_string(), end.to_string());
        self.run(&[
            "capture-pane",
            "-t",
            &exact_target(name)?,
            "-e",
            "-p",
            "-S",
            &start,
            "-E",
            &end,
        ])?
        .text()
    }

    /// Pane'in GERÇEK boyutu (bağlı istemci varsa onun boyutu).
    pub fn pane_size(&self, name: &str) -> Result<PaneSize, TmuxError> {
        let out = self.text(&[
            "list-panes",
            "-t",
            &exact_target(name)?,
            "-F",
            "#{pane_width} #{pane_height} #{history_size} #{alternate_on}",
        ])?;
        // Python: `stdout.strip().splitlines()[0].split()`.
        let first = py_splitlines(py_strip(&out))
            .into_iter()
            .next()
            .ok_or(TmuxError::BadOutput)?;
        parse_size(&py_split(first).collect::<Vec<_>>())
    }

    pub fn snapshot(&self, name: &str) -> Result<Snapshot, TmuxError> {
        let target = exact_target(name)?;
        // Yalın `;` elemanı BİLEREK: tmux komut ayıracı, iki komut aynı kuyrukta koşar.
        let out = self.text(&[
            "display-message",
            "-p",
            "-t",
            &target,
            SNAPSHOT_FORMAT,
            ";",
            "capture-pane",
            "-t",
            &target,
            "-e",
            "-p",
        ])?;
        parse_snapshot(&out)
    }

    /// Pane şu an gizli girdi bekliyor mu; `None` = bilinmiyor.
    pub fn pane_is_masked_input(&self, name: &str) -> Option<bool> {
        let tty = exact_target(name)
            .and_then(|target| self.text(&["display-message", "-p", "-t", &target, "#{pane_tty}"]))
            .ok()?;
        tty_is_masked(tty.trim())
    }

    /// Bağlı terminal istemcisi sayısı. `Err` = bilinmiyor (0 DEĞİL).
    pub fn client_count(&self, name: &str) -> Result<usize, TmuxError> {
        let out = self.text(&[
            "list-clients",
            "-t",
            &exact_target(name)?,
            "-F",
            "#{client_tty}",
        ])?;
        Ok(py_splitlines(&out)
            .into_iter()
            .filter(|l| !py_strip(l).is_empty())
            .count())
    }

    /// `client` (ör. `/dev/pts/105`) hangi oturuma bağlı. `Ok(None)` = böyle bir istemci yok (ya da ad geçersiz);
    /// `Err` = tmux sorulamadı (Python ikisini de `None` döner; davranış aynı, yalnız sebep korunur).
    pub fn client_session(&self, client: &str) -> Result<Option<String>, TmuxError> {
        if client.is_empty() || client.starts_with('-') {
            return Ok(None);
        }
        // `-u`: C yerelinde sekme `_` olurdu (TBD#366 P5).
        let out = self.text_utf8(&["list-clients", "-F", "#{client_name}\t#{client_session}"])?;
        Ok(py_splitlines(&out)
            .into_iter()
            .find_map(|line| match line.split_once('\t') {
                Some((name, session)) if name == client && !session.is_empty() => {
                    Some(session.to_string())
                }
                _ => None,
            }))
    }

    /// `@cops_ctx` kullanıcı seçeneğini yazar; boş etiket seçeneği siler. Sondaki `;` kaçırılır (TBD#366 P6).
    pub fn set_ctx(&self, name: &str, label: &str) -> Result<(), TmuxError> {
        let target = exact_target(name)?;
        let label = escape_arg(label);
        let mut args = vec!["set-option", "-t", &target];
        if label.is_empty() {
            args.extend(["-u", "@cops_ctx"]);
        } else {
            args.extend(["@cops_ctx", &label]);
        }
        self.run(&args).map(drop)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshot_with_empty_tty_keeps_empty_string() {
        let s = parse_snapshot("80 24 0 1 \nekran\n").unwrap();
        assert_eq!(
            (s.tty.as_str(), s.size.alternate_on, s.text.as_str()),
            ("", true, "ekran\n")
        );
    }

    #[test]
    fn malformed_snapshot_is_an_error() {
        for bad in [
            "",
            "80 24 0 0 /dev/pts/1",
            "80 24 0\nx",
            "a b c d e\nx",
            "80 24 0 0\nx",
        ] {
            assert!(parse_snapshot(bad).is_err(), "{bad:?}");
        }
    }

    #[test]
    fn parsers_keep_free_text_last_and_reject_garbage() {
        let p = parse_pane("42\t/dev/pts/3\tbash\tad boşluklu\t/tmp/a\tb").unwrap();
        assert_eq!(
            (p.pane_pid, p.session.as_str(), p.cwd.as_str()),
            (42, "ad boşluklu", "/tmp/a\tb")
        );
        assert_eq!(
            parse_session("10\t0\tx").unwrap(),
            SessionInfo {
                name: "x".into(),
                created: 10,
                attached: 0
            }
        );
        assert!(parse_pane("42\tx").is_err());
        let two = "1\tt\tc\ta\t/x\ny\u{241e}\n2\tt\tc\tb\t/z\u{241e}\n";
        let panes = parse_panes(two).unwrap();
        assert_eq!(
            (panes.len(), panes[0].cwd.as_str(), panes[1].pane_pid),
            (2, "/x\ny", 2)
        );
        assert!(parse_session("a\t0\tx").is_err());
        assert!(parse_size(&["80", "24", "0"]).is_err());
    }
}
