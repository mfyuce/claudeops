//! Gerçek tmux (yalıtılmış soket) + gerçek süreçlerle Python paritesi, bayt bayt: aynı pane'lere aynı istek dizisi önce
//! Python'da (`web._term_output` + `web_term_lite.to_lite`, `web._term_history`; `tmux_backend.TMUX_SOCKET` test soketine
//! yamalı), sonra Rust'ta (`frame::output_payload`, `frame::term_history`, `SysProbe`). Pane'ler durağan içeriklidir.
//!
//! Ek kanıtlar: (1) Rust'ın HER tmux çağrısı test soketine ve geçici `TMUX_TMPDIR`e gider (argv günlüğü sarmalayıcısı);
//! (2) Rust okuması durum ve ev dizinine hiçbir şey yazmaz; (3) önbellek: oturum gidince ilk istek `term_session_gone`,
//! kayıt düşer, sonraki istek taze çözer.
mod common;
use common::*;
use cops_ep_state::pyjson;
use cops_ep_term::frame::{output_payload, term_history};
use cops_ep_term::resolve::Resolver;
use cops_ep_term::SysProbe;
use cops_state::{Backend, Json};
use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;

const PY_RUN: &str = r#"
from claudeops.commands import web as w
from claudeops.commands import web_term_lite
out = []
for r in json.loads(sys.stdin.read()):
    if r["k"] == "out":
        res = w._term_output(r["name"], lang=r["lang"], viewport=r["vp"])
        if r["lite"]:
            res = web_term_lite.to_lite(res)
    else:
        res = w._term_history(r["name"], r["start"], r["end"], lang=r["lang"])
    out.append(json.dumps(res))
sys.stdout.write(json.dumps(out))
"#;

#[derive(Clone)]
enum Req {
    Out {
        name: String,
        en: bool,
        lite: bool,
        vp: bool,
    },
    Hist {
        name: String,
        start: i64,
        end: i64,
        en: bool,
    },
}

impl Req {
    fn json(&self) -> String {
        let lang = |en: bool| if en { "en" } else { "tr" };
        match self {
            Req::Out { name, en, lite, vp } => format!(
                r#"{{"k": "out", "name": {}, "lang": "{}", "lite": {lite}, "vp": {vp}}}"#,
                pyjson::dumps(&Json::Str(name.to_string())),
                lang(*en)
            ),
            Req::Hist {
                name,
                start,
                end,
                en,
            } => format!(
                r#"{{"k": "hist", "name": {}, "lang": "{}", "start": {start}, "end": {end}}}"#,
                pyjson::dumps(&Json::Str(name.to_string())),
                lang(*en)
            ),
        }
    }
}

struct World {
    env: Env,
    srv: Server,
    bare: std::process::Child,
    /// Paralel testlerin süreçleri aynı `/proc`ta: adlar dünya başına benzersiz (yalnız harf, taban kuralı bozulmasın).
    tag: String,
}

impl World {
    fn n(&self, s: &str) -> String {
        format!("qq{}{}", self.tag, s.strip_prefix("qq").unwrap_or(s))
    }
}

fn tag() -> String {
    static SEQ: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
    let mut n = std::process::id() * 8 + SEQ.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let mut t = String::new();
    while n > 0 {
        t.push((b'a' + (n % 26) as u8) as char);
        n /= 26;
    }
    t
}

impl Drop for World {
    fn drop(&mut self) {
        let _ = self.bare.kill();
        let _ = self.bare.wait();
    }
}

/// Pane'ler: tam ad, tek taban adayı, belirsiz taban, kayıtlı taban (null kayıt "yok" sayılır), maske, alternatif ekran,
/// copilot ve ucli modları, Türkçe ad, oturumu başka adla açılmış süreç (`:`'lı ad dahil), tmux dışı süreç.
fn world() -> World {
    let env = Env::new();
    let srv = Server::new();
    let tag = tag();
    let n = |s: &str| format!("qq{tag}{}", s.strip_prefix("qq").unwrap_or(s));
    let script = fake_script(srv.path());
    let s = |sess: &str, cli: &str, name: &str, lines: usize, mode: &str, flag: &str| {
        srv.spawn(
            &n(sess),
            &cli_command(&script, cli, &n(name), lines, mode, flag),
        );
    };
    s("qqtek", "claude", "qqtek", 400, "plan mode on", "-");
    s("qqbase7", "claude", "qqbase7", 5, "accept edits on", "-");
    s("qqamb1", "claude", "qqamb1", 3, "-", "-");
    s("qqamb2", "claude", "qqamb2", 3, "-", "-");
    s("qqreg3", "claude", "qqreg3", 3, "-", "-");
    s("qqnul4", "claude", "qqnul4", 3, "-", "-");
    s("qqmask", "claude", "qqmask", 3, "manual mode on", "mask");
    s("qqalt", "claude", "qqalt", 10, "auto mode on", "alt");
    s("qqcop", "copilot", "qqcop", 3, "· plan ·", "-");
    s("qqucli", "ucli", "qqucli", 3, "plan mode on", "-");
    s("qqçğ", "claude", "qqçğ", 60, "-", "-");
    s("qqother", "claude", "qqgone", 3, "-", "-");
    s("qqcolon", "claude", "qq:x", 3, "-", "-");
    for sess in [
        "qqtek", "qqbase7", "qqamb1", "qqamb2", "qqreg3", "qqnul4", "qqmask", "qqalt", "qqcop",
        "qqucli", "qqçğ", "qqother", "qqcolon",
    ] {
        wait_until(|| srv.screen(&n(sess)).contains("DONE"), sess);
    }
    env.write(
        "instances.json",
        format!(
            r#"{{"version": 1, "instances": {{"{}": {{"cwd": "/w"}}, "{}": null}}}}"#,
            n("qqreg3"),
            n("qqnul4")
        ),
    );
    let bare = bare_claude(&script, &n("qqbare"));
    World {
        env,
        srv,
        bare,
        tag,
    }
}

fn requests(w: &World) -> Vec<Req> {
    let o = |name: &str, en, lite, vp| Req::Out {
        name: w.n(name),
        en,
        lite,
        vp,
    };
    let h = |name: &str, start, end, en| Req::Hist {
        name: w.n(name),
        start,
        end,
        en,
    };
    let mut v = vec![];
    for name in [
        "qqtek", "qqbase", "qqamb", "qqreg", "qqnul", "qqmask", "qqalt", "qqcop", "qqucli", "qqçğ",
        "qqgone", "qq:x", "qqbare", "qqyok", "qqtek ",
    ] {
        for (en, lite, vp) in [
            (false, false, false),
            (true, true, false),
            (false, true, true),
            (true, false, true),
        ] {
            v.push(o(name, en, lite, vp));
        }
    }
    for (s, e) in [
        (-10, -1),
        (0, 5),
        (-100_000, 100_000),
        (5, 2),
        (100, 200),
        (-5, -5),
        (-399, -399),
        (i64::MIN, i64::MAX),
        (i64::MAX, i64::MAX),
        (i64::MIN, i64::MIN),
        (29, 29),
        (-2000, 29),
    ] {
        v.push(h("qqtek", s, e, false));
    }
    for name in ["qqalt", "qqçğ", "qqamb", "qqyok", "qqbare", "qqgone"] {
        v.push(h(name, -50, 10, false));
        v.push(h(name, 0, 3, true));
    }
    v
}

fn probe(w: &World, tmux: cops_tmux::Tmux) -> SysProbe {
    SysProbe {
        scan: cops_procscan::Config::for_dirs(&w.env.home, &w.env.state),
        docs: Arc::new(w.env.ro(Backend::Files)),
        tmux,
    }
}

fn rust(w: &World, tmux: &cops_tmux::Tmux, reqs: &[Req]) -> Vec<String> {
    let p = probe(w, tmux.clone());
    let cache = Resolver::default();
    reqs.iter()
        .map(|r| {
            let v = match r {
                Req::Out { name, en, lite, vp } => {
                    output_payload(&p, tmux, &cache, name, *en, *lite, *vp)
                }
                Req::Hist {
                    name,
                    start,
                    end,
                    en,
                } => term_history(&p, tmux, &cache, name, *start, *end, *en),
            };
            pyjson::dumps(&v.expect("tarama"))
        })
        .collect()
}

fn python(w: &World, reqs: &[Req]) -> Vec<String> {
    let input = format!(
        "[{}]",
        reqs.iter().map(Req::json).collect::<Vec<_>>().join(",")
    );
    let out = w.env.py(Some(&w.srv), PY_RUN, &input);
    let v = Json::parse(&out).unwrap();
    v.as_array()
        .unwrap()
        .iter()
        .map(|s| s.as_str().unwrap().to_string())
        .collect()
}

fn snapshot(root: &Path) -> BTreeMap<String, Vec<u8>> {
    let mut out = BTreeMap::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(d) = stack.pop() {
        for e in std::fs::read_dir(&d).unwrap() {
            let p = e.unwrap().path();
            let key = p.strip_prefix(root).unwrap().to_string_lossy().into_owned();
            if p.is_dir() {
                out.insert(key, b"<dizin>".to_vec());
                stack.push(p);
            } else {
                out.insert(key, std::fs::read(&p).unwrap());
            }
        }
    }
    out
}

#[test]
fn every_request_matches_python_byte_for_byte() {
    let w = world();
    let reqs = requests(&w);
    let py = python(&w, &reqs);
    let before = snapshot(&w.env.root);
    let rs = rust(&w, &w.srv.tmux, &reqs);
    assert_eq!(
        snapshot(&w.env.root),
        before,
        "Rust okuması durum/ev dizinine yazdı"
    );
    assert_eq!(py.len(), rs.len());
    let mut codes = BTreeMap::new();
    for (i, (p, r)) in py.iter().zip(&rs).enumerate() {
        assert_eq!(r, p, "istek {i}: {}", reqs[i].json());
        let v = Json::parse(r).unwrap();
        let k = v
            .get("code")
            .and_then(Json::as_str)
            .map(str::to_string)
            .unwrap_or_else(|| format!("ok mode={:?} masked={:?}", v.get("mode"), v.get("masked")));
        *codes.entry(k).or_insert(0) += 1;
    }
    // senaryo gerçekten sınandı mı (Python ve Rust aynı sonuca ulaştı ama ikisi de hep hata vermiş olmasın)
    let seen: Vec<&String> = codes.keys().collect();
    for want in [
        "ambiguous_name",
        "not_running",
        "not_tmux_backed",
        "term_session_gone",
        "invalid_range",
        "ok mode=Some(Str(\"plan\")) masked=Some(Bool(false))",
        "ok mode=Some(Str(\"manual\")) masked=Some(Bool(true))",
        "ok mode=Some(Str(\"acceptEdits\")) masked=Some(Bool(false))",
        "ok mode=Some(Str(\"auto\")) masked=Some(Bool(false))",
        "ok mode=Some(Null) masked=Some(Bool(false))",
        "ok mode=None masked=None",
    ] {
        assert!(
            seen.iter().any(|k| k.starts_with(want)),
            "{want} görülmedi: {codes:?}"
        );
    }
    println!("istek {} sonuç sınıfları {codes:?}", reqs.len());
}

/// Rust'ın her tmux çağrısı yalnız test soketine gider: tmux yerine argv + `TMUX_TMPDIR` günlüğü yazıp gerçek tmux'u aynı
/// argv ile çağıran sarmalayıcı.
#[test]
fn every_tmux_call_uses_the_test_socket() {
    let w = world();
    let log = w.srv.path().join("argv.log");
    let wrap = w.srv.path().join("tmux-wrap.sh");
    std::fs::write(
        &wrap,
        format!(
            "#!/bin/sh\nprintf '%s|%s\\n' \"$TMUX_TMPDIR\" \"$*\" >> {}\nexec tmux \"$@\"\n",
            sq(log.to_str().unwrap())
        ),
    )
    .unwrap();
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(&wrap, std::fs::Permissions::from_mode(0o700)).unwrap();
    let tmux = w.srv.tmux.clone().program(&wrap);
    let rs = rust(&w, &tmux, &requests(&w));
    assert!(rs.iter().any(|r| r.contains("\"ok\": true")));
    let text = std::fs::read_to_string(&log).unwrap();
    let want = format!("{}|-L {} ", w.srv.path().display(), w.srv.tmux.socket());
    let lines: Vec<&str> = text.lines().collect();
    assert!(lines.len() > 20, "{}", lines.len());
    for l in &lines {
        assert!(l.starts_with(&want), "başka sokete/dizine giden çağrı: {l}");
        assert!(
            !l.contains(" -t qq") && !l.contains("copy-mode") && !l.contains("send-keys"),
            "{l}"
        );
    }
    let kinds: std::collections::BTreeSet<&str> =
        lines.iter().filter_map(|l| l.split(' ').nth(2)).collect();
    assert_eq!(
        kinds.into_iter().collect::<Vec<_>>(),
        vec![
            "capture-pane",
            "display-message",
            "has-session",
            "list-panes"
        ],
        "yalnız okuma komutları"
    );
}

#[test]
fn gone_session_drops_the_cache_and_rescans() {
    let w = world();
    let p = probe(&w, w.srv.tmux.clone());
    let cache = Resolver::default();
    let t = &w.srv.tmux;
    let code = |v: Json| {
        v.get("code")
            .and_then(Json::as_str)
            .unwrap_or("ok")
            .to_string()
    };
    let (base, sess) = (w.n("qqbase"), w.n("qqbase7"));
    let out = |c: &Resolver| code(output_payload(&p, t, c, &base, true, false, false).unwrap());
    assert_eq!(out(&cache), "ok");
    assert_eq!(cache.cached(&base).unwrap().name, sess);
    w.srv.raw(&["kill-session", "-t", &format!("={sess}")]);
    wait_until(
        || {
            !w.srv
                .raw(&["ls", "-F", "#{session_name}"])
                .lines()
                .any(|l| l == sess)
        },
        "oturum kapandı",
    );
    // önbellek hâlâ dolu: tam tarama yok, capture başarısız -> term_session_gone ve kayıt düşer
    assert_eq!(out(&cache), "term_session_gone");
    assert_eq!(cache.cached(&base), None);
    // süreç tmux'la birlikte öldü: taze tarama bulamaz
    wait_until(|| out(&cache) == "not_running", "taze çözüm");
}
