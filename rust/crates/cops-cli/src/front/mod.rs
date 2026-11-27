//! `cops front status|on|off [--apply]`: Python `commands/front_cmd.py` karşılığı (çıktı metinleri, birim ve drop-in metni,
//! systemctl sırası aynı) + sahip onaylı düzeltmeler (TBD#371/4). Bu düzeltmeler Python'a da taşındı (docs/rs-cli.md
//! "Python hatası?" 1-8; iki taraf aynı davranır, `tests/py_parity.rs`):
//! - (a) adres ayrıştırma [`net::parse_listen`] / [`net::parse_internal`]: geçersiz adres ENGEL olur;
//! - (b) drop-in varken iç portu başka bir süreç tutuyorsa ENGEL ([`net::port_owner`]: dinleyen soket cgroup'u
//!   `claudeops-web.service` olmalı);
//! - (c) `on`/`off` yarıda kalırsa (dosya yazımı, systemctl hatası, ön kapının dinlemeye başlamaması, web'in dış porta
//!   dönmemesi) önceki dosya ve birim durumuna dönülür; dönüş adımlarının her biri yazılır, başarısız olan açıkça söylenir.
//!   Ön kapının önceki durumu `systemctl is-active/is-enabled` ile okunur (port sahibi değil: `--listen` değişebilir);
//!   okunamazsa hiçbir şey değişmez. `on` web'in iç adreste olduğunu da doğrular; `off` web'i kendi adresinde
//!   ([`web_addr`], ön kapının `--listen`i değil) bekler.
//! - `on`: zaten çalışan ön kapı (yeniden uygulama dışı yol) `restart` edilir (`enable --now` yeni birim metnini uygulamaz).
//!   Göreli `--bin` engeldir.

pub mod fsx;
pub mod net;
pub mod secret;
pub mod systemctl;

use crate::argp::{Action, FrontArgs};
use crate::pyenv::{normpath, pathlib_str, Roots};
use fsx::Prev;
use net::{Net, FRONT_UNIT_NAME, WEB_UNIT_NAME};
use std::ffi::OsString;
use std::io::Write;
use std::net::SocketAddr;
use std::path::Path;
use std::time::{Duration, Instant};
use systemctl::{show, Systemctl};

/// `front_cmd.DEFAULT_LISTEN`
pub const DEFAULT_LISTEN: &str = "127.0.0.1:8765";
/// `front_cmd.DEFAULT_INTERNAL` (copsd `DEFAULT_UPSTREAM` ile aynı)
pub const DEFAULT_INTERNAL: &str = "127.0.0.1:28765";

/// `front_cmd.FRONT_UNIT_TEMPLATE` (metin aynı).
pub const FRONT_UNIT_TEMPLATE: &str = "[Unit]
Description=claudeops front (copsd, Rust vekil)
# Python birimine bağımlı DEĞİL: Python düşükken ön kapı ayakta kalır (vekil uçlar 502 verir).

[Service]
ExecStart={bin} --listen {listen} --upstream {internal} --dist {dist} --state-dir {state}
Restart=always
RestartSec=2
UMask=0077

[Install]
WantedBy=default.target
";

/// `Path(base) / rest` metni.
fn pl_join(base: &str, rest: &str) -> String {
    let b = pathlib_str(base);
    if b == "." {
        return pathlib_str(rest);
    }
    if b.ends_with('/') {
        format!("{b}{rest}")
    } else {
        format!("{b}/{rest}")
    }
}

/// `front_cmd` modül sabitlerinin metinleri.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Paths {
    /// `paths.CLAUDEOPS_DIR` (ham)
    pub claudeops_dir: String,
    /// `UNIT_DIR`
    pub unit_dir: String,
    /// `FRONT_UNIT`
    pub front_unit: String,
    /// `WEB_UNIT`
    pub web_unit: String,
    /// `DROPIN`
    pub dropin: String,
    /// `DEFAULT_BIN`
    pub default_bin: String,
    /// `front.secret_path()`
    pub secret_path: String,
    /// `web_static.DIST_DIR` (yalnız `on` için gerekir; Python deposundan çözülür)
    pub dist: Option<String>,
}

impl Paths {
    /// Python kurallarıyla.
    pub fn new(r: &Roots, dist: Option<String>) -> Paths {
        let unit_dir = pl_join(&r.home, ".config/systemd/user");
        Paths {
            claudeops_dir: r.claudeops_dir.clone(),
            front_unit: format!("{unit_dir}/claudeops-front.service"),
            web_unit: format!("{unit_dir}/claudeops-web.service"),
            dropin: format!("{unit_dir}/claudeops-web.service.d/front.conf"),
            unit_dir,
            default_bin: pl_join(&r.claudeops_dir, "bin/copsd"),
            secret_path: secret::secret_path(&r.claudeops_dir),
            dist,
        }
    }
}

/// `DIST_DIR`: `<py/cops dizini>/claudeops/paths.py` gerçek yolundan iki üst = depo; `<depo>/py/webui/dist`, var olan kısmı
/// symlink'leri çözülmüş (pathlib `resolve(strict=False)`).
pub fn dist_dir(py_dir: &Path) -> std::io::Result<String> {
    let paths_py = std::fs::canonicalize(py_dir.join("claudeops/paths.py"))?;
    let repo = paths_py
        .parent()
        .and_then(Path::parent)
        .and_then(Path::parent)
        .ok_or_else(|| std::io::Error::other("depo kökü çözülemedi"))?;
    let want = repo.join("py/webui/dist");
    let mut existing = want.clone();
    let mut tail = Vec::new();
    let resolved = loop {
        match std::fs::canonicalize(&existing) {
            Ok(r) => break r,
            Err(_) => {
                let Some(name) = existing.file_name().map(|n| n.to_os_string()) else {
                    break existing.clone();
                };
                tail.push(name);
                if !existing.pop() {
                    break existing.clone();
                }
            }
        }
    };
    let mut out = resolved;
    for n in tail.into_iter().rev() {
        out.push(n);
    }
    out.into_os_string()
        .into_string()
        .map_err(|_| std::io::Error::other("dist yolu UTF-8 değil"))
}

/// Bekleme süreleri.
#[derive(Debug, Clone, Copy)]
pub struct Timing {
    /// `on` sonrası ön kapının dış portu dinlemesi
    pub front_up: Duration,
    /// `off`ta ön kapının dış portu bırakması
    pub port_free: Duration,
    /// `off` sonrası web'in dış portu dinlemesi
    pub web_up: Duration,
    /// yoklama aralığı
    pub poll: Duration,
    /// gizli kilidi
    pub lock: Duration,
}

impl Default for Timing {
    fn default() -> Self {
        Timing {
            front_up: Duration::from_secs(15),
            port_free: Duration::from_secs(10),
            web_up: Duration::from_secs(30),
            poll: Duration::from_millis(200),
            lock: Duration::from_secs(30),
        }
    }
}

/// Çalışma bağlamı (testte her şey enjekte edilir).
pub struct Ctx<'a> {
    /// Yollar
    pub paths: Paths,
    /// `CLAUDEOPS_FRONT_SECRET`
    pub env_secret: Option<String>,
    /// Ağ/süreç yoklaması
    pub net: &'a dyn Net,
    /// systemctl
    pub sc: &'a mut dyn Systemctl,
    /// stdout
    pub out: &'a mut dyn Write,
    /// Süreler
    pub timing: Timing,
}

/// `web_execstart`: ilk `^ExecStart=(.*)$` satırı (`re.M`; `.` yalnız `\n`i kapsamaz), `strip()`.
pub fn web_execstart(unit_text: &str) -> Option<String> {
    unit_text
        .split('\n')
        .find_map(|l| l.strip_prefix("ExecStart="))
        .map(|v| cops_auth::py_strip(v).to_string())
}

/// `with_internal_port`.
pub fn with_internal_port(execstart: &str, internal: &str) -> Option<String> {
    let (host, port) = match internal.rsplit_once(':') {
        Some((h, p)) => (h, p),
        None => ("", internal),
    };
    let flags = format!(" --host {host} --port {port}");
    if let Some(head) = execstart.strip_suffix('\'') {
        if execstart.ends_with("web'") {
            return Some(format!("{head}{flags}'"));
        }
    }
    if execstart.ends_with(" web") {
        return Some(format!("{execstart}{flags}"));
    }
    None
}

/// `dropin_text`.
pub fn dropin_text(execstart: &str) -> String {
    format!("[Service]\nExecStart=\nExecStart={execstart}\n")
}

/// systemd tırnağı (Python `_unit_text` `state` için): `\`, `"`, `%`, `$` kaçışlı, çift tırnak içinde.
pub fn sd_quote(s: &str) -> String {
    let e = s
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('%', "%%")
        .replace('$', "$$");
    format!("\"{e}\"")
}

/// `bin`/`dist`: systemd için anlamlı karakter varsa tırnaklı (Python `_sd_quote_if_needed` ile aynı).
fn sd_quote_if_needed(s: &str) -> String {
    if s.chars()
        .any(|c| c.is_whitespace() || matches!(c, '"' | '\'' | '\\' | '%' | '$'))
    {
        sd_quote(s)
    } else {
        s.to_string()
    }
}

/// `_unit_text`: `state` = `abspath(CLAUDEOPS_DIR)` tırnaklı (kök mutlak olmalı; bkz. [`Roots::check_absolute`]).
pub fn unit_text(p: &Paths, bin: &str, listen: &str, internal: &str) -> String {
    FRONT_UNIT_TEMPLATE
        .replace("{bin}", &sd_quote_if_needed(bin))
        .replace("{listen}", listen)
        .replace("{internal}", internal)
        .replace(
            "{dist}",
            &sd_quote_if_needed(p.dist.as_deref().unwrap_or("")),
        )
        .replace("{state}", &sd_quote(&normpath(&p.claudeops_dir)))
}

fn exists(p: &str) -> bool {
    Path::new(p).exists()
}

fn has_control(s: &str) -> bool {
    s.chars().any(char::is_control)
}

/// `plan_on` kararı.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Plan {
    /// Python adımları (metin aynı)
    pub steps: Vec<String>,
    /// Engeller (Python'unkiler aynı metin, sırayla; Rust'ın ekleri sonra)
    pub blockers: Vec<String>,
    /// drop-in var ve iç portu bizim web birimimiz tutuyor: yalnız ön kapı yenilenir
    pub reapply: bool,
    /// drop-in'e yazılacak ExecStart
    pub new_execstart: Option<String>,
    /// dış adres (geçerliyse)
    pub listen: Option<SocketAddr>,
    /// iç adres (geçerliyse)
    pub internal: Option<SocketAddr>,
}

/// Python `plan_on` (+ düzeltmeler a, b). `web_unit_text`: `WEB_UNIT` içeriği; yoksa `Ok("")`, okunamadıysa `Err`.
pub fn plan_on(
    ctx: &Ctx<'_>,
    listen: &str,
    internal: &str,
    binp: &str,
    web_unit_text: Result<String, String>,
) -> Plan {
    let p = &ctx.paths;
    let mut blockers = Vec::new();
    if !exists(binp) {
        blockers.push(format!(
            "ikili yok: {binp} (rust/ altında `cargo build --release`, sonra kopyala)"
        ));
    } else if !is_exec_file(binp) {
        blockers.push(format!("ikili çalıştırılabilir dosya değil: {binp}"));
    }
    // systemd `ExecStart=` göreli yolu reddeder (birim hiç başlamaz); Python da engel sayar.
    if !binp.starts_with('/') {
        blockers.push(format!(
            "ikili yolu mutlak değil: {binp} (systemd ExecStart mutlak yol ister)"
        ));
    }
    let (text, read_err) = match web_unit_text {
        Ok(t) => (t, None),
        Err(e) => (String::new(), Some(e)),
    };
    let files = web_dropin_files(Path::new(&p.dropin));
    let mine = Path::new(&p.dropin).file_name();
    let (mut es, mut late) = (None, Vec::new());
    if let Some(files) = &files {
        let mut base = text.clone();
        for (n, t) in files {
            if Some(n.as_os_str()) < mine {
                base.push('\n');
                base.push_str(t);
            } else if web_execstart(t).is_some() {
                late.push(n.to_string_lossy().into_owned());
            }
        }
        es = effective_execstart(&base);
    }
    let new = es.as_deref().and_then(|e| with_internal_port(e, internal));
    if let Some(e) = read_err {
        blockers.push(format!("claudeops-web.service okunamadı: {e}"));
    } else if files.is_none() {
        let dir = Path::new(&p.dropin).parent().unwrap_or(Path::new(""));
        blockers.push(format!(
            "claudeops-web.service drop-in'leri okunamadı: {}",
            dir.display()
        ));
    } else if new.is_none() {
        blockers.push(
            "claudeops-web.service ExecStart biçimi tanınmadı (…claudeops web); elle drop-in gerekir".into(),
        );
    }
    if !late.is_empty() {
        let name = mine.unwrap_or_default().to_string_lossy();
        blockers.push(format!(
            "{name} sonrasındaki drop-in ExecStart= atıyor: {:?} (ön kapının iç port ayarı ezilir; adını öne alın ya da birleştirin)",
            late.join(", ")
        ));
    }
    let dist = p.dist.as_deref().unwrap_or("");
    for (what, v) in [
        ("ikili", binp),
        ("dist", dist),
        ("durum dizini", p.claudeops_dir.as_str()),
    ] {
        if has_control(v) {
            blockers.push(format!(
                "{what} yolu denetim karakteri içeriyor (birim dosyasını bozar): {v:?}"
            ));
        }
    }
    let la = match net::parse_listen(listen) {
        Ok(a) => Some(a),
        Err(e) => {
            blockers.push(format!("geçersiz --listen: {e}"));
            None
        }
    };
    let ia = match net::parse_internal(internal) {
        Ok(a) => Some(SocketAddr::V4(a)),
        Err(e) => {
            blockers.push(format!("geçersiz --internal: {e}"));
            None
        }
    };
    if let (Some(l), Some(i)) = (la, ia) {
        if l.port() == i.port() && (l.ip() == i.ip() || l.ip().is_unspecified()) {
            blockers.push(format!("dış ve iç adres çakışıyor: {listen} / {internal}"));
        }
    }
    let dropin = exists(&p.dropin);
    let mut reapply = false;
    if let Some(i) = ia {
        if ctx.net.busy(i) {
            if !dropin {
                blockers.push(format!("iç port dolu: {internal}"));
            } else {
                let o = ctx.net.owner(i);
                if o.is_unit(WEB_UNIT_NAME) {
                    reapply = true;
                } else {
                    blockers.push(format!(
                        "iç port başka bir süreçte: {internal} ({}); drop-in var ama dinleyen {WEB_UNIT_NAME} değil",
                        o.describe()
                    ));
                }
            }
        }
    }
    // atomik yazım bağı düz dosyaya çevirirdi: kapalı yön, elle düzenlensin
    for u in [&p.front_unit, &p.dropin] {
        if std::fs::symlink_metadata(u).is_ok_and(|m| m.file_type().is_symlink()) {
            blockers.push(format!(
                "birim dosyası sembolik bağ: {u} (yazım bağı düz dosyaya çevirir; bağı kaldırın)"
            ));
        }
    }
    let steps = vec![
        format!("gizli: {} (0600, yoksa üret)", p.secret_path),
        format!(
            "yaz: {} ({binp} --listen {listen} --upstream {internal} --dist {dist} --state-dir {})",
            p.front_unit, p.claudeops_dir
        ),
        format!("yaz: {} (Python -> {internal})", p.dropin),
        "systemctl --user daemon-reload".into(),
        "systemctl --user restart claudeops-web.service (Python iç porta geçer, dış port boşalır)"
            .into(),
        "systemctl --user enable --now claudeops-front.service".into(),
    ];
    Plan {
        steps,
        blockers,
        reapply,
        new_execstart: new,
        listen: la,
        internal: ia,
    }
}

fn is_exec_file(p: &str) -> bool {
    use std::os::unix::fs::PermissionsExt;
    std::fs::metadata(p)
        .map(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
        .unwrap_or(false)
}

fn read_web_unit(p: &str) -> Result<String, String> {
    match std::fs::read(p) {
        Ok(b) => String::from_utf8(b).map_err(|_| format!("{p}: UTF-8 değil")),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(String::new()),
        Err(e) => Err(format!("{p}: {e}")),
    }
}

/// Giriş noktası: çıkış kodu.
pub fn run(ctx: &mut Ctx<'_>, a: &FrontArgs) -> i32 {
    let listen = a.listen.clone().unwrap_or_else(|| DEFAULT_LISTEN.into());
    let internal = a
        .internal
        .clone()
        .unwrap_or_else(|| DEFAULT_INTERNAL.into());
    let bin = a
        .bin
        .clone()
        .unwrap_or_else(|| ctx.paths.default_bin.clone());
    let r = match a.action {
        Action::Status => status(ctx, &listen, &internal, &bin),
        Action::On => on(ctx, a.apply, &listen, &internal, &bin),
        Action::Off => off(ctx, a.apply, &listen),
    };
    // Yazılamayan çıktı (kapalı boru) yutulmaz (ders H9).
    match r.and_then(|c| ctx.out.flush().map(|_| c)) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("cops-rs: çıktı yazılamadı: {e}");
            1
        }
    }
}

fn status(ctx: &mut Ctx<'_>, listen: &str, internal: &str, bin: &str) -> std::io::Result<i32> {
    let p = ctx.paths.clone();
    let sec = secret::read_secret(ctx.env_secret.as_deref(), Path::new(&p.secret_path));
    writeln!(
        ctx.out,
        "gizli: {} ({})",
        if sec.is_empty() { "YOK" } else { "var" },
        p.secret_path
    )?;
    writeln!(
        ctx.out,
        "ikili: {} ({bin})",
        if exists(bin) { "var" } else { "YOK" }
    )?;
    writeln!(
        ctx.out,
        "front birimi: {}; drop-in: {}",
        if exists(&p.front_unit) {
            "yazılı"
        } else {
            "yok"
        },
        if exists(&p.dropin) { "yazılı" } else { "yok" }
    )?;
    let mut rc = 0;
    for hp in [listen, internal] {
        match net::parse_listen(hp) {
            Ok(a) => writeln!(
                ctx.out,
                "port {hp}: {}",
                if ctx.net.busy(a) { "dolu" } else { "boş" }
            )?,
            Err(e) => {
                writeln!(ctx.out, "port {hp}: geçersiz adres ({e})")?;
                rc = 1;
            }
        }
    }
    Ok(rc)
}

/// Geri alma günlüğü.
struct Undo {
    lines: Vec<String>,
    failed: bool,
}

impl Undo {
    fn new() -> Undo {
        Undo {
            lines: Vec::new(),
            failed: false,
        }
    }

    fn file(&mut self, path: &str, prev: &Prev) {
        let what = match prev {
            Prev::Absent => format!("sil: {path} (önceden yoktu)"),
            Prev::Content(..) => format!("geri yaz: {path} (önceki içerik)"),
            Prev::Link(_) => format!("geri yaz: {path} (önceki sembolik bağ)"),
        };
        match fsx::restore(Path::new(path), prev) {
            Ok(()) => self.lines.push(format!("  {what}: tamam")),
            Err(e) => {
                self.failed = true;
                self.lines.push(format!("  {what}: HATA ({e})"));
            }
        }
    }

    fn sc(&mut self, sc: &mut dyn Systemctl, args: &[&str]) {
        match sc.run(args) {
            Ok(0) => self.lines.push(format!("  {}: tamam", show(args))),
            Ok(rc) => {
                self.failed = true;
                self.lines
                    .push(format!("  {}: HATA (çıkış {rc})", show(args)));
            }
            Err(e) => {
                self.failed = true;
                self.lines.push(format!("  {}: HATA ({e})", show(args)));
            }
        }
    }

    fn report(self, out: &mut dyn Write) -> std::io::Result<()> {
        writeln!(out, "GERİ ALMA:")?;
        for l in &self.lines {
            writeln!(out, "{l}")?;
        }
        if self.failed {
            writeln!(
                out,
                "GERİ ALMA BAŞARISIZ: yukarıda HATA yazan adımları elle tamamlayın (`py/cops front status` ile denetleyin)"
            )
        } else {
            writeln!(
                out,
                "geri alındı: birim dosyaları ve servisler önceki durumda"
            )
        }
    }
}

fn wait_for(limit: Duration, poll: Duration, mut cond: impl FnMut() -> bool) -> bool {
    let start = Instant::now();
    loop {
        if cond() {
            return true;
        }
        if start.elapsed() >= limit {
            return false;
        }
        std::thread::sleep(poll);
    }
}

fn run_sc(sc: &mut dyn Systemctl, args: &[&str]) -> Result<(), String> {
    match sc.run(args) {
        Ok(0) => Ok(()),
        Ok(rc) => Err(format!("çıkış {rc}")),
        Err(e) => Err(e),
    }
}

/// Ön kapı biriminin değişiklikten önceki durumu. Geri alma bunu geri kurar: dış portun sahibine bakmak `--listen`
/// değişince yanılır (eski adreste çalışan ön kapı "çalışmıyordu" sanılıp kapatılırdı).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct UnitState {
    active: bool,
    enabled: bool,
}

/// `systemctl --user is-active|is-enabled --quiet claudeops-front.service` (0 = evet). Çalıştırılamazsa hata: durum
/// bilinmeden hiçbir şey değiştirilmez.
fn front_state(sc: &mut dyn Systemctl) -> Result<UnitState, String> {
    let active = sc.run(&["is-active", "--quiet", FRONT_UNIT_NAME])? == 0;
    let enabled = sc.run(&["is-enabled", "--quiet", FRONT_UNIT_NAME])? == 0;
    Ok(UnitState { active, enabled })
}

impl Undo {
    /// Önceden çalışmayan ön kapıyı durdurur; etkinlik durumu önceki gibi kalır.
    fn front_stop(&mut self, sc: &mut dyn Systemctl, prev: UnitState) {
        if prev.enabled {
            self.sc(sc, &["stop", FRONT_UNIT_NAME]);
        } else {
            self.sc(sc, &["disable", "--now", FRONT_UNIT_NAME]);
        }
    }

    /// Durdurulmuş ön kapının önceki etkin/çalışır durumunu geri kurar.
    fn front_back(&mut self, sc: &mut dyn Systemctl, prev: UnitState) {
        match (prev.enabled, prev.active) {
            (true, true) => self.sc(sc, &["enable", "--now", FRONT_UNIT_NAME]),
            (false, true) => self.sc(sc, &["start", FRONT_UNIT_NAME]),
            (true, false) => self.sc(sc, &["enable", FRONT_UNIT_NAME]),
            (false, false) => {}
        }
    }
}

fn on(
    ctx: &mut Ctx<'_>,
    apply: bool,
    listen: &str,
    internal: &str,
    bin: &str,
) -> std::io::Result<i32> {
    let p = ctx.paths.clone();
    let plan = plan_on(ctx, listen, internal, bin, read_web_unit(&p.web_unit));
    writeln!(ctx.out, "PLAN:\n  {}", plan.steps.join("\n  "))?;
    if !plan.blockers.is_empty() {
        writeln!(ctx.out, "ENGEL:\n  {}", plan.blockers.join("\n  "))?;
        return Ok(1);
    }
    if !apply {
        writeln!(ctx.out, "(plan; uygulamak için --apply)")?;
        return Ok(0);
    }
    let (Some(new_es), Some(la), Some(ia)) =
        (plan.new_execstart.clone(), plan.listen, plan.internal)
    else {
        writeln!(ctx.out, "HATA: plan eksik (iç hata)")?;
        return Ok(1);
    };
    let prev = match front_state(ctx.sc) {
        Ok(s) => s,
        Err(e) => {
            writeln!(
                ctx.out,
                "HATA: {FRONT_UNIT_NAME} durumu okunamadı: {e} (hiçbir şey değişmedi)"
            )?;
            return Ok(1);
        }
    };
    if let Err(e) = secret::ensure_secret_file(&p.claudeops_dir, ctx.timing.lock) {
        writeln!(ctx.out, "HATA: gizli üretilemedi: {}: {e}", p.secret_path)?;
        return Ok(1);
    }
    let prev_front = match fsx::snapshot(Path::new(&p.front_unit)) {
        Ok(s) => s,
        Err(e) => {
            writeln!(
                ctx.out,
                "HATA: okunamadı: {}: {e} (hiçbir şey değişmedi)",
                p.front_unit
            )?;
            return Ok(1);
        }
    };
    let prev_drop = match fsx::snapshot(Path::new(&p.dropin)) {
        Ok(s) => s,
        Err(e) => {
            writeln!(
                ctx.out,
                "HATA: okunamadı: {}: {e} (hiçbir şey değişmedi)",
                p.dropin
            )?;
            return Ok(1);
        }
    };
    let writes: [(&str, String); 2] = [
        (&p.front_unit, unit_text(&p, bin, listen, internal)),
        (&p.dropin, dropin_text(&new_es)),
    ];
    for (i, (path, text)) in writes.iter().enumerate() {
        let r = Path::new(path)
            .parent()
            .map(std::fs::create_dir_all)
            .unwrap_or(Ok(()))
            .and_then(|_| fsx::atomic_write(Path::new(path), text.as_bytes(), None));
        if let Err(e) = r {
            writeln!(ctx.out, "HATA: yazılamadı: {path}: {e}")?;
            let mut u = Undo::new();
            if i == 1 {
                u.file(&p.front_unit, &prev_front);
            }
            u.file(&p.dropin, &prev_drop);
            u.report(ctx.out)?;
            return Ok(1);
        }
    }
    let mut cmds: Vec<&[&str]> = if plan.reapply {
        vec![
            &["daemon-reload"],
            &["enable", "--now", "claudeops-front.service"],
            &["restart", "claudeops-front.service"],
        ]
    } else {
        vec![
            &["daemon-reload"],
            &["restart", "claudeops-web.service"],
            &["enable", "--now", "claudeops-front.service"],
        ]
    };
    // Zaten çalışan ön kapıda `enable --now` yeni birim metnini (ör. yeni `--upstream`) uygulamaz (Python da restart eder).
    if !plan.reapply && prev.active {
        cmds.push(&["restart", "claudeops-front.service"]);
    }
    let mut ran = 0;
    let mut failure: Option<String> = None;
    for cmd in &cmds {
        ran += 1;
        if let Err(e) = run_sc(ctx.sc, cmd) {
            // Python metni aynı ("HATA: systemctl --user ..."); neden ayrı satırda.
            writeln!(ctx.out, "HATA: {}", show(cmd))?;
            failure = Some(e);
            break;
        }
    }
    if failure.is_none() {
        // Doğrulama: ön kapı dış adreste, web (yeniden başlatıldıysa) iç adreste.
        let net = ctx.net;
        let web_needed = !plan.reapply;
        let ok = |n: &dyn Net| {
            n.owner(la).is_unit(FRONT_UNIT_NAME)
                && (!web_needed || n.owner(ia).is_unit(WEB_UNIT_NAME))
        };
        // web yeniden başlatıldıysa açılışı ön kapınınkinden uzun sürer: `off` ile aynı pay.
        let limit = if web_needed {
            ctx.timing.front_up.max(ctx.timing.web_up)
        } else {
            ctx.timing.front_up
        };
        if !wait_for(limit, ctx.timing.poll, || ok(net)) {
            if !net.owner(la).is_unit(FRONT_UNIT_NAME) {
                writeln!(
                    ctx.out,
                    "HATA: ön kapı {listen} üzerinde dinlemiyor ({} sn içinde {FRONT_UNIT_NAME} görülmedi: {})",
                    limit.as_secs(),
                    net.owner(la).describe()
                )?;
            } else {
                writeln!(
                    ctx.out,
                    "HATA: web iç adreste {internal} doğrulanamadı ({} sn içinde {WEB_UNIT_NAME} görülmedi: {})",
                    limit.as_secs(),
                    net.owner(ia).describe()
                )?;
            }
            failure = Some("doğrulama".into());
        }
    } else if let Some(e) = &failure {
        writeln!(ctx.out, "  neden: {e}")?;
    }
    if failure.is_none() {
        writeln!(ctx.out, "açıldı: dış {listen} -> iç {internal}")?;
        return Ok(0);
    }
    // Geri alma: önceden çalışmayan ön kapıyı durdur, dosyaları geri koy, yeniden yükle, web'i eski portuna, önceden çalışan
    // ön kapıyı eski birimiyle yeniden başlat; etkinlik durumu önceki gibi.
    let mut u = Undo::new();
    let front_touched = cmds[..ran]
        .iter()
        .any(|c| c.last() == Some(&"claudeops-front.service"));
    let web_restarted = cmds[..ran]
        .iter()
        .any(|c| *c == ["restart", "claudeops-web.service"]);
    if front_touched && !prev.active {
        u.front_stop(ctx.sc, prev);
    }
    u.file(&p.front_unit, &prev_front);
    u.file(&p.dropin, &prev_drop);
    u.sc(ctx.sc, &["daemon-reload"]);
    if web_restarted {
        u.sc(ctx.sc, &["restart", "claudeops-web.service"]);
    }
    if front_touched && prev.active {
        u.sc(ctx.sc, &["restart", "claudeops-front.service"]);
        if !prev.enabled {
            u.sc(ctx.sc, &["disable", "claudeops-front.service"]);
        }
    }
    u.report(ctx.out)?;
    Ok(1)
}

/// Ön kapı biriminin `--listen` değeri (varsa), yoksa `fallback`.
fn front_listen(front_unit: &str, fallback: &str) -> String {
    let Ok(text) = std::fs::read_to_string(front_unit) else {
        return fallback.into();
    };
    let Some(es) = web_execstart(&text) else {
        return fallback.into();
    };
    let toks: Vec<&str> = es.split_whitespace().collect();
    toks.iter()
        .position(|t| *t == "--listen")
        .and_then(|i| toks.get(i + 1))
        .map(|s| s.to_string())
        .unwrap_or_else(|| fallback.into())
}

/// `web` alt komutunun uzun seçenekleri (Python `_WEB_LONG_OPTS`; argparse kısaltmaları için).
const WEB_LONG_OPTS: [&str; 6] = [
    "--help",
    "--port",
    "--host",
    "--print-token",
    "--tunnel",
    "--grpc-port",
];

/// Python `_effective_execstart`: birim + drop-in metinlerinde son `ExecStart=` kazanır, boş atama sıfırlar.
fn effective_execstart(text: &str) -> Option<String> {
    text.split('\n')
        .filter_map(|l| l.strip_prefix("ExecStart="))
        .map(cops_auth::py_strip)
        .next_back()
        .filter(|v| !v.is_empty())
        .map(str::to_string)
}

/// Python `_web_dropin_files`: `front.conf` dışındaki drop-in'ler (ad, metin) ad sırasıyla; biri okunamazsa `None`.
fn web_dropin_files(dropin: &Path) -> Option<Vec<(OsString, String)>> {
    let dir = dropin.parent()?;
    let rd = match std::fs::read_dir(dir) {
        Ok(r) => r,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Some(Vec::new()),
        Err(_) => return None,
    };
    let mut names = rd
        .map(|e| e.map(|e| e.file_name()))
        .collect::<std::io::Result<Vec<_>>>()
        .ok()?;
    names.retain(|n| {
        let b = n.as_encoded_bytes();
        b.ends_with(b".conf") && !b.starts_with(b".") && Some(n.as_os_str()) != dropin.file_name()
    });
    names.sort();
    names
        .into_iter()
        .map(|n| {
            let t = std::fs::read_to_string(dir.join(&n)).ok()?;
            Some((n, t))
        })
        .collect()
}

/// Python `_web_dropins`: drop-in metinleri birleşik; biri okunamazsa `None`.
fn web_dropins(dropin: &Path) -> Option<String> {
    Some(
        web_dropin_files(dropin)?
            .iter()
            .map(|(_, t)| format!("\n{t}"))
            .collect(),
    )
}

/// `off` sonrası web'in döneceği adres: web biriminin ve drop-in'lerinin geçerli ExecStart'ındaki `--host`/`--port` (ya da `=`li biçim),
/// yoksa web varsayılanı `127.0.0.1:8765` (`web.DEFAULT_HOST/DEFAULT_PORT`). Joker ya da ad olan host loopback'ten yoklanır.
/// Biçim tanınmazsa `None` (çağıran ön kapının dış adresine düşer).
pub fn web_addr(web_unit_text: &str) -> Option<SocketAddr> {
    let es = effective_execstart(web_unit_text)?;
    let es = es.strip_suffix('\'').unwrap_or(&es);
    let toks: Vec<&str> = es.split_whitespace().collect();
    let (mut host, mut port) = ("127.0.0.1".to_string(), "8765".to_string());
    let mut i = 0;
    while i < toks.len() {
        let mut t = toks[i].to_string();
        let (name, rest) = t.split_at(t.find('=').unwrap_or(t.len()));
        if name.len() > 2 && name.starts_with("--") && !WEB_LONG_OPTS.contains(&name) {
            let mut full = WEB_LONG_OPTS.iter().filter(|o| o.starts_with(name));
            match (full.next(), full.next()) {
                // argparse "ambiguous option": web açılmaz, adres bilinmiyor
                (Some(_), Some(_)) => return None,
                (Some(o), None) => t = format!("{o}{rest}"),
                _ => {}
            }
        }
        if t == "--host" || t == "--port" {
            if let Some(v) = toks.get(i + 1) {
                *(if t == "--host" { &mut host } else { &mut port }) = v.to_string();
                i += 1;
            }
        } else if let Some(v) = t.strip_prefix("--host=") {
            host = v.to_string();
        } else if let Some(v) = t.strip_prefix("--port=") {
            port = v.to_string();
        }
        i += 1;
    }
    let ip = match host.parse::<std::net::Ipv4Addr>() {
        Ok(ip) if !ip.is_unspecified() => ip,
        _ => std::net::Ipv4Addr::LOCALHOST,
    };
    net::parse_listen(&format!("{ip}:{port}")).ok()
}

fn off(ctx: &mut Ctx<'_>, apply: bool, listen_arg: &str) -> std::io::Result<i32> {
    let p = ctx.paths.clone();
    let steps = [
        "systemctl --user disable --now claudeops-front.service".to_string(),
        format!("sil: {}", p.dropin),
        "systemctl --user daemon-reload".into(),
        "systemctl --user restart claudeops-web.service (Python dış porta döner)".into(),
    ];
    writeln!(ctx.out, "PLAN:\n  {}", steps.join("\n  "))?;
    if !apply {
        writeln!(ctx.out, "(plan; uygulamak için --apply)")?;
        return Ok(0);
    }
    // Doğrulanacak adres: web'in kendi adresi (ön kapının `--listen`i farklı olabilir; web oraya değil kendi portuna döner).
    let wa = match read_web_unit(&p.web_unit)
        .ok()
        .zip(web_dropins(Path::new(&p.dropin)))
        .and_then(|(unit, extra)| web_addr(&(unit + &extra)))
    {
        Some(a) => a,
        None => match net::parse_listen(&front_listen(&p.front_unit, listen_arg)) {
            Ok(a) => a,
            Err(e) => {
                writeln!(
                    ctx.out,
                    "HATA: geçersiz dış adres: {e} (hiçbir şey değişmedi)"
                )?;
                return Ok(1);
            }
        },
    };
    let prev = match front_state(ctx.sc) {
        Ok(s) => s,
        Err(e) => {
            writeln!(
                ctx.out,
                "HATA: {FRONT_UNIT_NAME} durumu okunamadı: {e} (hiçbir şey değişmedi)"
            )?;
            return Ok(1);
        }
    };
    let prev_drop = match fsx::snapshot(Path::new(&p.dropin)) {
        Ok(s) => s,
        Err(e) => {
            writeln!(
                ctx.out,
                "HATA: okunamadı: {}: {e} (hiçbir şey değişmedi)",
                p.dropin
            )?;
            return Ok(1);
        }
    };
    let unit_exists = exists(&p.front_unit);
    let disable = ["disable", "--now", "claudeops-front.service"];
    if let Err(e) = run_sc(ctx.sc, &disable) {
        if unit_exists {
            writeln!(ctx.out, "HATA: {}\n  neden: {e}", show(&disable))?;
            let mut u = Undo::new();
            u.front_back(ctx.sc, prev);
            u.report(ctx.out)?;
            return Ok(1);
        }
        writeln!(
            ctx.out,
            "(not: {FRONT_UNIT_NAME} birimi yok; durdurma hatası yok sayıldı)"
        )?;
    }
    let net = ctx.net;
    let freed = wait_for(ctx.timing.port_free, ctx.timing.poll, || {
        let o = net.owner(wa);
        !o.is_unit(FRONT_UNIT_NAME) && (o.is_unit(WEB_UNIT_NAME) || !net.busy(wa))
    });
    if !freed {
        writeln!(
            ctx.out,
            "HATA: dış port {wa} boşalmadı ({}); web oraya dönemez",
            ctx.net.owner(wa).describe()
        )?;
        let mut u = Undo::new();
        u.front_back(ctx.sc, prev);
        u.report(ctx.out)?;
        return Ok(1);
    }
    let full_undo = |ctx: &mut Ctx<'_>, web: bool| -> std::io::Result<()> {
        let mut u = Undo::new();
        u.file(&p.dropin, &prev_drop);
        u.sc(ctx.sc, &["daemon-reload"]);
        if web {
            u.sc(ctx.sc, &["restart", "claudeops-web.service"]);
        }
        u.front_back(ctx.sc, prev);
        u.report(ctx.out)
    };
    if let Err(e) = fsx::restore(Path::new(&p.dropin), &Prev::Absent) {
        writeln!(ctx.out, "HATA: silinemedi: {}: {e}", p.dropin)?;
        full_undo(ctx, false)?;
        return Ok(1);
    }
    if let Err(e) = run_sc(ctx.sc, &["daemon-reload"]) {
        writeln!(
            ctx.out,
            "HATA: systemctl --user daemon-reload\n  neden: {e}"
        )?;
        full_undo(ctx, false)?;
        return Ok(1);
    }
    let restart = ["restart", "claudeops-web.service"];
    let rc = match ctx.sc.run(&restart) {
        Ok(rc) => rc,
        Err(e) => {
            writeln!(ctx.out, "  neden: {e}")?;
            127
        }
    };
    if rc != 0 {
        writeln!(ctx.out, "HATA: web restart")?;
        full_undo(ctx, true)?;
        return Ok(rc);
    }
    let up = wait_for(ctx.timing.web_up, ctx.timing.poll, || {
        net.owner(wa).is_unit(WEB_UNIT_NAME)
    });
    if !up {
        writeln!(
            ctx.out,
            "HATA: web {wa} üzerinde doğrulanamadı ({} sn: {})",
            ctx.timing.web_up.as_secs(),
            ctx.net.owner(wa).describe()
        )?;
        full_undo(ctx, true)?;
        return Ok(1);
    }
    writeln!(ctx.out, "kapandı")?;
    Ok(0)
}

#[cfg(test)]
mod tests;
