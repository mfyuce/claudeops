//! `instances.py` (ad düzenleri, `created_at_from_name`, `mark_models_gone`, `load_instances` önbelleği, bozuk kayıtta
//! istisna) ve `roster_by_name` / `web._blueprint_cwds` paritesi.
use cops_state::instances::{
    auto_name, created_at_from_name, derived_name, Instances, Launch, NewInstance,
};
use cops_state::roster::{blueprint_cwds, Roster};
use cops_state::{Backend, Json, Map};
use std::collections::{HashMap, HashSet};

mod common;
use common::{j, Env};

const NAMES: &[&str] = &[
    "hc20261126",
    "hc20261126\n",
    "hc20261126\n\n",
    "hc20261126_1_22",
    "hc20261126_1_",
    "hc20261126__1",
    "hc20261126_١",
    "a123456789",
    "a1234567890",
    "x٢٠٢٦١١٢٦",
    "x٢٠٢٦1126",
    "x2026١١٢٦",
    "x20261١٥5",
    "x2026111٥",
    "mtsyn20260909fablereview",
    "ysf220261105",
    "p1234567820261126",
    "a20260229",
    "a20240229",
    "a20261301",
    "a20261232",
    "a20261100",
    "a00001126",
    "a00011126",
    "a99991231",
    "a19700101",
    "a19691231",
    "a20160327",
    "a20161030",
    "a20261126x",
    "ş20261126",
    "a\n20261126",
    "",
];

#[test]
fn name_patterns_and_created_at_match_python() {
    let e = Env::new();
    let input = Json::Array(NAMES.iter().map(|s| Json::from(*s)).collect()).to_compact();
    let out = e.py_in(
        "files",
        r#"
from claudeops import instances as i
names = json.load(sys.stdin)
res = []
for n in names:
    d = i.DERIVED_NAME_RE.match(n); a = i.AUTO_NAME_RE.match(n)
    res.append([list(d.groups()) if d else None, list(a.groups()) if a else None, i.created_at_from_name(n)])
print(json.dumps(res, ensure_ascii=False))
"#,
        &input,
    );
    let groups = |g: Option<(&str, &str, &str)>| {
        g.map_or(Json::Null, |(a, b, c)| {
            Json::Array(vec![a.into(), b.into(), c.into()])
        })
    };
    let rs = Json::Array(
        NAMES
            .iter()
            .map(|n| {
                Json::Array(vec![
                    groups(derived_name(n)),
                    groups(auto_name(n)),
                    created_at_from_name(n).map_or(Json::Null, Json::Float),
                ])
            })
            .collect(),
    );
    assert_eq!(rs.to_compact(), out.trim_end());
}

#[test]
fn mark_models_gone_matches_python() {
    let recs = r#"{
      "a": {"cli": "ucli", "model": "m1"},
      "b": {"cli": "ucli", "model": "yok", "model_gone": false},
      "c": {"cli": "ucli", "model": "m2", "model_gone": true},
      "d": {"cli": "ucli", "model": "claude-x", "model_gone": true},
      "e": {"cli": "codex", "model": "q", "model_gone": 1},
      "f": {"cli": "bos", "model": "q", "model_gone": true},
      "g": {"cli": "", "model": "z"},
      "h": {"model": "-"},
      "i": {"cli": 5, "model": "m1", "model_gone": true},
      "k": {"cli": "ucli", "model": "", "model_gone": 0},
      "l": {"cli": "ucli", "model": "yok2"}
    }"#;
    let live_json = r#"{"ucli": ["m1", "m2"], "bos": [], "": ["z"]}"#;
    let (a, b) = (Env::new(), Env::new());
    for e in [&a, &b] {
        e.write(
            "instances.json",
            &format!(r#"{{"version": 1, "instances": {recs}}}"#),
        );
    }
    let py = a.py_in(
        "files",
        "from claudeops import instances as i\nlive = {k: set(v) for k, v in json.load(sys.stdin).items()}\nprint(i.mark_models_gone(live), i.mark_models_gone(live))",
        live_json,
    );
    let live: HashMap<String, HashSet<String>> = j(live_json)
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| {
            (
                k.clone(),
                v.as_array()
                    .unwrap()
                    .iter()
                    .map(|x| x.as_str().unwrap().to_string())
                    .collect(),
            )
        })
        .collect();
    let docs = b.docs(Backend::Files);
    let i = Instances::new(&docs);
    let n1 = i.mark_models_gone(&live).unwrap();
    let n2 = i.mark_models_gone(&live).unwrap();
    assert_eq!(format!("{n1} {n2}"), py.trim());
    assert_eq!(a.read("instances.json"), b.read("instances.json"));
}

/// Python'un `AttributeError`/`TypeError` verdiği kayıtlar: iki dilde de hata ve dosya DEĞİŞMEZ.
#[test]
fn bad_records_fail_like_python() {
    let doc = r#"{"version": 1, "instances": {"liste": [1], "sayi": 0, "bos": null, "iyi": {"cli": "ucli", "model": 5}}}"#;
    let ops: [(&str, &str); 9] = [
        ("record", "i.record_instance('liste', blueprint=None, cwd='/c', cli='claude', model='m', origin='t')"),
        ("record0", "i.record_instance('sayi', blueprint=None, cwd='/c', cli='claude', model='m', origin='t')"),
        ("forget", "i.forget_instance('sayi')"),
        ("forget_null", "i.forget_instance('bos')"),
        ("mark", "i.mark_started('liste', cli='c', model='m', permission_mode='', effort='')"),
        ("mark_null", "i.mark_started('bos', cli='c', model='m', permission_mode='', effort='')"),
        ("rename", "i.rename_blueprint('x', 'y')"),
        ("gone", "i.mark_models_gone({'ucli': {'a'}})"),
        ("add", "i.add_missing({'yeni': [1]})"),
    ];
    for (op, code) in ops {
        let (a, b) = (Env::new(), Env::new());
        for e in [&a, &b] {
            e.write("instances.json", doc);
        }
        let py = a.py(
            "files",
            &format!("from claudeops import instances as i\ntry:\n    {code}\n    print('ok')\nexcept Exception as ex:\n    print('hata')"),
        );
        let docs = b.docs(Backend::Files);
        let i = Instances::new(&docs);
        let l = Launch {
            cli: "c".into(),
            model: "m".into(),
            ..Launch::default()
        };
        let rs_ok = match op {
            "record" | "record0" => i
                .record(
                    if op == "record" { "liste" } else { "sayi" },
                    &NewInstance {
                        cwd: "/c".into(),
                        origin: "t".into(),
                        launch: Launch {
                            cli: "claude".into(),
                            model: "m".into(),
                            ..Launch::default()
                        },
                        ..NewInstance::default()
                    },
                )
                .is_ok(),
            "forget" => i.forget("sayi").is_ok(),
            "forget_null" => i.forget("bos").is_ok(),
            "mark" => i.mark_started("liste", &l).is_ok(),
            "mark_null" => i.mark_started("bos", &l).is_ok(),
            "rename" => i.rename_blueprint("x", "y").is_ok(),
            "gone" => {
                let live = HashMap::from([("ucli".to_string(), HashSet::from(["a".to_string()]))]);
                i.mark_models_gone(&live).is_ok()
            }
            "add" => {
                let m: Map = j(r#"{"yeni": [1]}"#).as_object().unwrap().clone();
                i.add_missing(&m).is_ok()
            }
            _ => unreachable!(),
        };
        assert_eq!(if rs_ok { "ok" } else { "hata" }, py.trim(), "{op}");
        let norm = |e: &Env| {
            let mut v = j(&e.read("instances.json"));
            for rec in v.as_object_mut().unwrap()["instances"]
                .as_object_mut()
                .unwrap()
                .values_mut()
            {
                if let Some(o) = rec.as_object_mut() {
                    for k in ["created_at", "last_started_at"] {
                        if o.get(k).and_then(Json::as_f64).is_some_and(|f| f > 1e9) {
                            o.insert(k.into(), "ZAMAN".into());
                        }
                    }
                }
            }
            v.to_indented()
        };
        assert_eq!(norm(&a), norm(&b), "{op}");
    }
}

#[test]
fn load_cache_semantics() {
    // files: dosya anahtarı değişince yeniden okunur (başka yazar, yeni inode)
    let e = Env::new();
    let docs = e.docs(Backend::Files);
    let i = Instances::new(&docs);
    assert!(i.load().is_empty());
    e.py("files", "from claudeops import instances as i\ni.record_instance('a', blueprint=None, cwd='/c', cli='claude', model='m', origin='t')");
    assert_eq!(i.load().len(), 1);
    assert_eq!(i.load().len(), 1, "önbellekten");
    e.py("files", "from claudeops import instances as i\ni.record_instance('b', blueprint=None, cwd='/c', cli='claude', model='m', origin='t')");
    assert_eq!(i.load().len(), 2);
    // db: ayna dosyaya dokunmadan DB değişirse yeni değer görülür (TBD#374 S4)
    let e = Env::new();
    e.py("db", "from claudeops import instances as i\ni.record_instance('a', blueprint=None, cwd='/c', cli='claude', model='m', origin='t')");
    let docs = e.docs(Backend::Db);
    let i = Instances::new(&docs);
    assert_eq!(i.load().len(), 1);
    e.py(
        "db",
        "from claudeops.store import default_store\nst = default_store()\nd = st.get_doc('instances'); d['instances']['z'] = {'cwd': '/z'}; st.set_doc('instances', d)",
    );
    assert_eq!(i.load().len(), 2, "db kipinde ayna değişmese de DB okunur");
}

/// db kipi: önbellek anahtarı DB satır damgasıdır (Python `test_state_instances_db_version_cache.py`).
#[test]
fn load_db_cache_follows_row_stamp() {
    let e = Env::new();
    e.py(
        "db",
        "from claudeops.store import default_store\ndefault_store()",
    );
    let docs = e.docs(Backend::Db);
    let i = Instances::new(&docs);
    let path = e.dir().instances_json();
    let doc = |n: &str| j(&format!(r#"{{"version":1,"instances":{{"{n}":{{}}}}}}"#));
    let put = |n: &str| docs.store().unwrap().set_doc("instances", &doc(n)).unwrap();
    let names = || i.load().keys().cloned().collect::<Vec<_>>();
    // damgaya dokunmadan gövde: önbellek isabetini ve düşen okumayı gözlemek için
    let body = |b: &str| {
        let c = rusqlite::Connection::open(e.dir().db()).unwrap();
        c.execute("UPDATE docs SET body=?1 WHERE name='instances'", [b])
            .unwrap();
    };

    put("a");
    assert_eq!(names(), ["a"]);
    body(&doc("gizli").to_compact());
    assert_eq!(names(), ["a"], "damga aynı: yeniden ayrıştırılmaz");
    put("b");
    assert_eq!(names(), ["b"], "sürüm değişti");
    docs.store().unwrap().delete_doc("instances").unwrap();
    std::fs::remove_file(&path).ok();
    assert!(names().is_empty(), "satır yok");
    put("z");
    assert_eq!(names(), ["z"], "sil + yeniden yaz: sürüm yine 1");

    // DB okuması düşüp dosyaya dönen sonuç saklanmaz
    put("c");
    std::fs::write(&path, doc("eski").to_compact()).unwrap();
    body("{yarim");
    assert_eq!(names(), ["eski"]);
    body(&doc("c").to_compact());
    assert_eq!(names(), ["c"]);

    // dönen sözlük kopyadır
    i.load().clear();
    assert_eq!(names(), ["c"]);
}

#[test]
fn roster_by_name_and_blueprint_cwds_match_python() {
    let e = Env::new();
    e.write(
        "roster.tsv",
        "a\t/a\tm\na\t/a2\tm2\tcodex\nhc20261126\t/h\tm\nb\t/b//\tm\n#c\t/c\tm\n",
    );
    e.write("models.tsv", "a\tm\nhc20261126\tm\nb\tm\nc\tm\n");
    let py = e.py(
        "files",
        "from claudeops import roster\nfrom claudeops.commands import web\n\
         print(json.dumps([[k, v.cwd, v.model, v.cli] for k, v in roster.roster_by_name().items()]))\n\
         print(json.dumps(web._blueprint_cwds(web._fleet_status())))",
    );
    let docs = e.docs(Backend::Files);
    let r = Roster::new(&docs);
    let by = Json::Array(
        r.by_name()
            .unwrap()
            .into_iter()
            .map(|(k, v)| Json::Array(vec![k.into(), v.cwd.into(), v.model.into(), v.cli.into()]))
            .collect(),
    );
    let bp = Json::Object(
        blueprint_cwds(&r.fleet_status().unwrap())
            .into_iter()
            .map(|(k, v)| (k, v.into()))
            .collect(),
    );
    assert_eq!(format!("{}\n{}\n", by.to_compact(), bp.to_compact()), py);
}

/// Eşlenmemiş vekil (`"\ud800"`): Python okur ama yazamaz; Rust okur (U+FFFD), yazıcı hata verir, dosya ve DB değişmez.
#[test]
fn lone_surrogate_readable_not_writable() {
    let doc = r#"{"version": 1, "instances": {"a": {"cwd": "/x\ud800y", "cli": "claude"}, "b": {"cwd": "/b"}}}"#;
    for (mode, backend) in [
        ("files", Backend::Files),
        ("dual", Backend::Dual),
        ("db", Backend::Db),
    ] {
        let (a, b) = (Env::new(), Env::new());
        for e in [&a, &b] {
            e.py(
                mode,
                "from claudeops.store import default_store\ndefault_store()",
            );
            e.write("instances.json", doc);
        }
        let py = a.py(
            mode,
            "from claudeops import instances as i\nprint(sorted(i.load_instances()))\ntry:\n    i.forget_instance('b'); print('yazdi')\nexcept Exception as ex:\n    print('hata')\n\
             from claudeops.store import default_store\nprint(default_store().get_doc('instances') is None)",
        );
        let docs = b.docs(backend);
        let i = Instances::new(&docs);
        let mut keys: Vec<String> = i.load().keys().cloned().collect();
        keys.sort();
        let wrote = if i.forget("b").is_ok() {
            "yazdi"
        } else {
            "hata"
        };
        let db_none = b.py(mode, "from claudeops.store import default_store\nprint(default_store().get_doc('instances') is None)");
        assert_eq!(
            format!("{keys:?}\n{wrote}\n{}", db_none.trim()).replace('"', "'"),
            py.trim_end(),
            "{mode}"
        );
        assert_eq!(a.read("instances.json"), doc);
        assert_eq!(b.read("instances.json"), doc);
    }
    // settings: diğer anahtarlar okunur (Python gibi), varsayılanlara düşülmez
    let e = Env::new();
    e.write(
        "settings.json",
        r#"{"theme": "dark", "handover_effort": "x\udc00", "store_backend": "db"}"#,
    );
    let s = cops_state::settings::load(&e.dir());
    assert_eq!(s.str_of("theme"), "dark");
    assert_eq!(e.docs(Backend::Files).backend(), Backend::Files, "isolated");
    let docs = cops_state::StateDocs::isolated(e.dir(), None, "");
    assert_eq!(
        docs.backend(),
        Backend::Db,
        "store_backend vekilli dosyadan da okunur"
    );
    let py = e.py(
        "files",
        "from claudeops.settings import load_settings\nprint(load_settings()['theme'])",
    );
    assert_eq!(py.trim(), "dark");
}

/// UTF-8 olmayan durum dosyaları (Python `test_bad_encoding_state_files`): okuyucu çökmez, yazıcı üstüne YAZMAZ.
#[test]
fn bad_encoding_files_not_overwritten() {
    let (a, b) = (Env::new(), Env::new());
    let bad: &[u8] = b"alfa\t/a\tm\n\xff\xfe\n";
    for e in [&a, &b] {
        std::fs::write(e.state.join("roster.tsv"), bad).unwrap();
        std::fs::write(
            e.state.join("instances.json"),
            b"{\"version\": 1, \"instances\": {\"a\": \"\xff\"}}",
        )
        .unwrap();
    }
    let py = a.py(
        "files",
        "from claudeops.commands import web as w\nfrom claudeops import instances as i\n\
         def t(f):\n    try:\n        f(); return 'ok'\n    except Exception as ex:\n        return 'hata'\n\
         print(t(lambda: w._read_tsv_raw(w.ROSTER_TSV)), t(lambda: w._append_tsv_line(w.ROSTER_TSV, ['x', '/x', 'm'])), \
         len(i.load_instances()), t(lambda: i.forget_instance('a')))",
    );
    let docs = b.docs(Backend::Files);
    let r = Roster::new(&docs);
    let t = |ok: bool| if ok { "ok" } else { "hata" };
    let append = r
        .lock()
        .and_then(|g| g.append(cops_state::roster::Tsv::Roster, &["x", "/x", "m"]));
    let i = Instances::new(&docs);
    let rs = format!(
        "{} {} {} {}",
        t(r.raw_rows(cops_state::roster::Tsv::Roster).is_ok()),
        t(append.is_ok()),
        i.load().len(),
        t(i.forget("a").is_ok())
    );
    assert_eq!(rs, py.trim());
    for e in [&a, &b] {
        assert_eq!(std::fs::read(e.state.join("roster.tsv")).unwrap(), bad);
    }
}

/// R2-3/R2-4: kip geçişleri ve "kapalı dönemde" (files kipindeki eski yazar) yazılan veri: iki dil aynı değeri görür.
#[test]
fn mode_transitions_match_python() {
    let e = Env::new();
    e.py(
        "db",
        "from claudeops.store import default_store\ndefault_store()",
    );
    let call = |name: &str| {
        format!("from claudeops import statedocs\nfrom claudeops.paths import CLAUDEOPS_DIR as D\np = os.path.join(D, '{name}.json')\n")
    };
    let py_read = |mode: &str, name: &str| {
        e.py(
            mode,
            &format!(
                "{}print(json.dumps(statedocs.read_json('{name}', p, None)))",
                call(name)
            ),
        )
        .trim()
        .to_string()
    };
    let py_write = |mode: &str, name: &str, v: &str| {
        e.py(
            mode,
            &format!(
                "{}statedocs.write_json('{name}', p, json.loads('{v}'))",
                call(name)
            ),
        );
    };
    let rs_read = |b: Backend, name: &str| {
        e.docs(b)
            .read(name, &e.dir().doc_path(name))
            .into_option()
            .map_or("null".to_string(), |v| v.to_compact())
    };
    for name in ["hosts", "orchdraft"] {
        py_write("files", name, "[\"A\"]"); // yalnız dosya
        assert_eq!(
            rs_read(Backend::Db, name),
            "[\"A\"]",
            "{name}: tembel içe aktarma"
        );
        assert_eq!(py_read("db", name), "[\"A\"]");
        e.docs(Backend::Db)
            .write(name, &e.dir().doc_path(name), &j("[\"B\"]"), None)
            .unwrap();
        assert_eq!(py_read("db", name), "[\"B\"]");
        py_write("files", name, "[\"C\"]"); // kapalı dönem: eski yazar yalnız dosyaya
        let want_db = if name == "hosts" {
            "[\"B\"]"
        } else {
            "[\"C\"]"
        };
        assert_eq!(
            rs_read(Backend::Db, name),
            want_db,
            "{name}: db kipinde DB doğruluk kaynağı"
        );
        assert_eq!(py_read("db", name), want_db, "{name}");
        assert_eq!(
            rs_read(Backend::Dual, name),
            "[\"C\"]",
            "{name}: dual dosya kaynağı"
        );
        assert_eq!(
            rs_read(Backend::Db, name),
            "[\"C\"]",
            "{name}: dual okuma DB'yi uydurdu"
        );
        assert_eq!(py_read("db", name), "[\"C\"]", "{name}");
        assert_eq!(rs_read(Backend::Files, name), py_read("files", name));
    }
}

/// TBD#374 S3: sekme/satır sonu içeren model iki dilde de reddedilir, dosyalar yazılmaz.
#[test]
fn register_model_bad_chars_like_python() {
    for (py_model, model) in [
        ("m\\nsahte\\t/etc", "m\nsahte\t/etc"),
        ("a\\tb", "a\tb"),
        ("a\\rb", "a\rb"),
    ] {
        let (a, b) = (Env::new(), Env::new());
        let cwd = a.root.display().to_string();
        let py = a.py(
            "files",
            &format!("from claudeops.commands import web as w\nprint(w._register_project('zza', '{cwd}', '{py_model}', lang='en')['error'])"),
        );
        assert_eq!(py.trim(), "model contains invalid characters");
        let docs = b.docs(Backend::Files);
        let r = Roster::new(&docs)
            .register_project("zza", &b.root.display().to_string(), model, "", &[], |_| {
                String::new()
            })
            .map_err(|e| e.code());
        assert_eq!(r, Err("model_bad_chars"));
        for e in [&a, &b] {
            assert!(!e.state.join("roster.tsv").exists() && !e.state.join("models.tsv").exists());
        }
    }
}
