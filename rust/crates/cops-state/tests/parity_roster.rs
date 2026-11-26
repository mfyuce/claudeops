//! `roster.tsv`/`models.tsv` (web TSV yardımcıları) ve `instances.py`: boşluk kapatma pariteleri.
use cops_state::instances::{Instances, Launch, NewInstance, DIAG_PREFIX};
use cops_state::roster::{known_names, Roster, Tsv};
use cops_state::{Backend, Json, Map, StateDocs, Store};

mod common;
use common::{j, Env};

const STORE: &str = "from claudeops.store import default_store\nst = default_store()\n";

fn sorted(v: impl IntoIterator<Item = String>) -> String {
    let mut v: Vec<String> = v.into_iter().collect();
    v.sort();
    Json::Array(v.into_iter().map(Json::from).collect()).to_compact()
}

/// K6: `_all_known_names` = roster (yorumlu dahil, `name` başlığı hariç) + instance kayıtları (unutulanlar dahil) +
/// canlı süreçlerin ad ve taban adları.
#[test]
fn known_names_matches_python() {
    let e = Env::new();
    e.write(
        "roster.tsv",
        "name\tcwd\tmodel\nacik\t/a\tm\n#kapali\t/k\tm\n\n#name\tx\nacik\t/b\tm\n",
    );
    let docs = e.docs(Backend::Files);
    let i = Instances::new(&docs);
    i.record("kayit20261126", &NewInstance::default()).unwrap();
    i.record("unutulan", &NewInstance::default()).unwrap();
    assert!(i.forget("unutulan").unwrap());
    let running = [
        ("canli20261126".to_string(), "canli".to_string()),
        ("name".to_string(), "acik".to_string()),
    ];
    let py = e.py(
        "files",
        "from types import SimpleNamespace as N\nfrom claudeops.commands import web as w\n\
         w.find_sessions = lambda **kw: [N(name='canli20261126', base='canli'), N(name='name', base='acik')]\n\
         print(json.dumps(sorted(w._all_known_names()), ensure_ascii=False))",
    );
    let got = known_names(&docs, &running).unwrap();
    for n in [
        "acik",
        "kapali",
        "kayit20261126",
        "unutulan",
        "canli",
        "canli20261126",
    ] {
        assert!(got.contains(n), "{n}");
    }
    assert_eq!(sorted(got), py.trim_end());
    // süreç yoksa canlı adlar da yok; başlık satırı tek başına ad üretmez
    assert!(!known_names(&docs, &[]).unwrap().contains("name"));
    assert!(!known_names(&docs, &[]).unwrap().contains("canli"));
}

/// `_first_rows`: `name` başlık satırı iki dosyada da dışlanır; yinelenen adda İLK satır.
#[test]
fn first_rows_header_excluded_like_python() {
    let e = Env::new();
    e.write(
        "roster.tsv",
        "name\tcwd\tmodel\tcli\na\t/ilk\tm\tagy\na\t/son\tm\tcodex\n",
    );
    e.write("models.tsv", "name\tmodel\na\tm1\na\tm2\n");
    let docs = e.docs(Backend::Files);
    let f = Roster::new(&docs).fleet_status().unwrap();
    assert_eq!(f.keys().collect::<Vec<_>>(), ["a"]);
    assert_eq!(
        (
            f["a"].cwd.as_str(),
            f["a"].model.as_str(),
            f["a"].cli.as_str()
        ),
        ("/ilk", "m1", "agy")
    );
    let py = e.py(
        "files",
        "from claudeops.commands import web as w\nf = w._fleet_status()\nr = w._first_rows(w._read_tsv_raw(w.ROSTER_TSV))\n\
         print(list(f), f['a']['cwd'], f['a']['model'], f['a']['cli'], list(r))",
    );
    assert_eq!(py.trim_end(), "['a'] /ilk m1 agy ['a']");
}

/// `cwd_bad_chars`: VAR OLAN ama adında sekme/satır sonu olan dizin iki dilde de reddedilir, dosyalar yazılmaz.
#[test]
fn register_cwd_bad_chars_like_python() {
    let e = Env::new();
    let docs = e.docs(Backend::Files);
    let r = Roster::new(&docs);
    for (i, bad) in ["se\tkme", "sat\nir"].iter().enumerate() {
        let dir = e.root.join(bad);
        std::fs::create_dir(&dir).unwrap();
        // sondaki bileşen: strip() uçtaki boşlukları atar, içtekiler kalır
        let cwd = dir.display().to_string();
        let name = format!("zz{i}");
        assert_eq!(
            r.register_project(&name, &cwd, "m", "claude", &[], |_| unreachable!())
                .map_err(|x| x.code()),
            Err("cwd_bad_chars")
        );
        let py = e.py_in(
            "files",
            &format!(
                "from claudeops.commands import web as w\nw.find_sessions = lambda **kw: []\n\
                 r = w._register_project('{name}', sys.stdin.read(), 'm', 'claude')\n\
                 print(r['ok'], r.get('error') == w._err('tr', 'cwd_bad_chars')['error'])"
            ),
            &cwd,
        );
        assert_eq!(py.trim_end(), "False True");
    }
    assert!(!e.dir().roster_tsv().exists() && !e.dir().models_tsv().exists());
}

/// `_toggle_comment` olmayan dosyada `false` döner ve dosya yaratmaz (`replace` de).
#[test]
fn toggle_missing_file_false() {
    let e = Env::new();
    let docs = e.docs(Backend::Files);
    {
        let g = Roster::new(&docs).lock().unwrap();
        assert!(!g.set_active(Tsv::Roster, "a", true).unwrap());
        assert!(!g.set_active(Tsv::Models, "a", false).unwrap());
        assert!(!g.replace(Tsv::Roster, "a", &["a", "b"]).unwrap());
    }
    assert!(!e.dir().roster_tsv().exists() && !e.dir().models_tsv().exists());
    let py = e.py(
        "files",
        "from claudeops.commands import web as w\nprint(w._toggle_comment(w.ROSTER_TSV, 'a', True), \
         w._replace_tsv_line(w.ROSTER_TSV, 'a', ['a', 'b']), os.path.exists(w.ROSTER_TSV))",
    );
    assert_eq!(py.trim_end(), "False False False");
}

/// Eşzamanlı aç/kapat: 20 Rust iş parçacığı + 20 Python iş parçacığı aynı dosyada; hiçbir güncelleme kaybolmaz.
#[test]
fn concurrent_toggles_lose_nothing() {
    let e = Env::new();
    let text: String = (0..40).map(|i| format!("n{i}\tv\n")).collect();
    e.write("roster.tsv", &text);
    let docs: StateDocs = e.docs(Backend::Files);
    let mut child = e
        .command(
            "files",
            "import threading\nfrom claudeops.commands import web as w\n\
             ts = [threading.Thread(target=w._toggle_comment, args=(w.ROSTER_TSV, 'n%d' % i, False)) for i in range(20, 40)]\n\
             [t.start() for t in ts]; [t.join() for t in ts]",
        )
        .spawn()
        .unwrap();
    std::thread::scope(|s| {
        for i in 0..20 {
            let docs = &docs;
            s.spawn(move || {
                let g = Roster::new(docs).lock().unwrap();
                assert!(g.set_active(Tsv::Roster, &format!("n{i}"), false).unwrap());
            });
        }
    });
    assert!(child.wait().unwrap().success());
    let out = e.read("roster.tsv");
    let want: String = (0..40).map(|i| format!("#n{i}\tv\n")).collect();
    assert_eq!(out, want);
}

#[test]
fn diag_prefix_matches_python() {
    let e = Env::new();
    let py = e.py(
        "files",
        "from claudeops import instances as i\nprint(i.DIAG_PREFIX)",
    );
    assert_eq!(py.trim_end(), DIAG_PREFIX);
}

/// `mark_started`: aynı cli ve seçeneksiz başlatmada `cli_opts` korunur; cli değişince silinir; yeni seçenek yazılır.
#[test]
fn mark_started_cli_opts_like_python() {
    for (mode, backend) in [("files", Backend::Files), ("db", Backend::Db)] {
        let (a, b) = (Env::new(), Env::new());
        a.py(mode, STORE);
        b.py(mode, STORE);
        let py = a.py(
            mode,
            "from claudeops import instances as i\nout = []\n\
             i.record_instance('a', blueprint='kod', cwd='/x', cli='ucli', model='m', origin='t', cli_opts={'service': 'claude'})\n\
             for cli, opts in (('ucli', None), ('ucli', {}), ('claude', None), ('ucli', {'service': 'evren'}), ('ucli', None)):\n\
             \x20   i.mark_started('a', cli=cli, model='m', permission_mode='auto', effort='e', cli_opts=opts)\n\
             \x20   out.append(i.get_instance('a').get('cli_opts'))\n\
             print(json.dumps(out))",
        );
        let docs = b.docs(backend);
        let i = Instances::new(&docs);
        let opts = |s: &str| -> Map {
            [("service".to_string(), Json::from(s))]
                .into_iter()
                .collect()
        };
        let launch = |cli: &str, o: Map| Launch {
            cli: cli.into(),
            model: "m".into(),
            permission_mode: "auto".into(),
            effort: "e".into(),
            cli_opts: o,
        };
        i.record(
            "a",
            &NewInstance {
                blueprint: Some("kod".into()),
                cwd: "/x".into(),
                origin: "t".into(),
                created_at: None,
                launch: Launch {
                    cli: "ucli".into(),
                    model: "m".into(),
                    cli_opts: opts("claude"),
                    ..Default::default()
                },
            },
        )
        .unwrap();
        let got: Vec<Json> = [
            ("ucli", Map::new()),
            ("ucli", Map::new()),
            ("claude", Map::new()),
            ("ucli", opts("evren")),
            ("ucli", Map::new()),
        ]
        .into_iter()
        .map(|(cli, o)| {
            i.mark_started("a", &launch(cli, o)).unwrap();
            i.get("a")
                .unwrap()
                .get("cli_opts")
                .cloned()
                .unwrap_or(Json::Null)
        })
        .collect();
        let want = j(
            r#"[{"service": "claude"}, {"service": "claude"}, null, {"service": "evren"}, {"service": "evren"}]"#,
        );
        assert_eq!(Json::Array(got.clone()), want, "{mode}");
        assert_eq!(j(&py), want, "{mode} python");
    }
}

/// `dual` kipte instance yazımı DB gölgesine de gider (Python `test_instances_shadow`); iki dilin gölgesi aynı şekilde.
#[test]
fn instances_dual_shadow() {
    let e = Env::new();
    e.py("dual", STORE);
    let docs = e.docs(Backend::Dual);
    Instances::new(&docs)
        .record("a", &NewInstance::default())
        .unwrap();
    let st = Store::open(&e.dir().db()).unwrap();
    let shadow = st.get_doc("instances").unwrap().expect("DB gölgesi");
    assert!(shadow.get("instances").and_then(|i| i.get("a")).is_some());
    assert_eq!(shadow, j(&e.read("instances.json")));
    e.py(
        "dual",
        "from claudeops import instances as i\ni.record_instance('p', blueprint=None, cwd='/x', cli='claude', model='m', origin='t')",
    );
    let shadow = st.get_doc("instances").unwrap().unwrap();
    for n in ["a", "p"] {
        assert!(
            shadow.get("instances").and_then(|i| i.get(n)).is_some(),
            "{n}"
        );
    }
}
