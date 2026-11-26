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
    // db: ayna dosyaya dokunmadan DB değişirse Rust yeni değeri görür (önbellek yok; sahibe soruldu)
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
