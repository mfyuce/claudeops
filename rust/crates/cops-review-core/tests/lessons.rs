//! `docs/rust-lessons-from-python.md` bölüm 2.7 (review çekirdeği) maddelerinin Rust tarafı testleri. Beklenen değerler
//! Python `review.py`den ölçüldü; aynı girdilerin Python ile eşliğini ayrıca parite düzeneği (`tests/parity.rs`) denetler.
//! Eşleme tablosu: `docs/rs-rev.md` "Python dersleri".
use cops_review_core::{export, flow, limits, redact, report, store, targets};
use cops_review_core::{Finding, ReviewPaths, ReviewStore, Verdict};
use cops_state::{Backend, Json, Map, StateDir, StateDocs};
use std::path::Path;
use std::sync::Arc;

fn store_at(root: &Path) -> ReviewStore {
    let docs = Arc::new(StateDocs::isolated(
        StateDir::at(root),
        Some(Backend::Files),
        "",
    ));
    ReviewStore::new(docs, ReviewPaths::at(root))
}

fn row(pairs: &[(&str, &str)]) -> Map {
    pairs
        .iter()
        .map(|(k, v)| (k.to_string(), Json::Str(v.to_string())))
        .collect()
}

fn finding(r: &str, sev: &str, w: &str, title: &str) -> Finding {
    Finding {
        r#ref: r.into(),
        severity: sev.into(),
        r#where: w.into(),
        title: title.into(),
        body: "gövde".into(),
    }
}

fn quota(out: &str, err: &str, jerr: &str, model_err: bool) -> bool {
    let parts = limits::limit_scan_texts(out, err, jerr, model_err);
    limits::is_quota_exhausted(&parts.iter().map(String::as_str).collect::<Vec<_>>())
}

const Q: &str = "RESOURCE_EXHAUSTED (code 429): Individual quota reached. Resets in 107h49m47s.";

/// 2.7 kota taraması (`d6d5a0e`): modelin kendi metnindeki alıntı kota sayılmaz, sağlayıcı kanalı sayılır.
#[test]
fn quota_scan_ignores_model_text() {
    let model_json = format!(r#"{{"partial_turn": "{Q}", "answer": "{Q}"}}"#);
    assert!(!quota(&model_json, "", "", false), "ucli JSON model alanı");
    assert!(
        !quota(&format!("{}{Q}", "x".repeat(600)), "", "", false),
        "uzun düz stdout"
    );
    assert!(
        !quota("{}", &format!("{}{Q}", "stream ".repeat(200)), "", true),
        "ucli stderr akışı"
    );
    assert!(quota("{}", Q, "", true), "kısa stderr sağlayıcı mesajı");
    assert!(
        quota(&format!(r#"{{"error": "{Q}"}}"#), "", "", false),
        "JSON sağlayıcı alanı"
    );
    assert!(quota("", "", Q, false), "ayrıştırılmış JSON hatası");
}

/// 2.7 kota bloğu (`ca9a717`): "hit your usage limit ... try again at" mutlak zamana kadar, tavanlı.
#[test]
fn usage_limit_try_again_at_blocks() {
    let u = ["You've hit your usage limit. try again at Nov 20th, 2026 6:37 PM."];
    assert!(limits::is_usage_limit(&u));
    assert!(limits::is_quota_exhausted(&u));
    let at = limits::reset_at(&u).expect("zaman ayrıştırılmalı");
    let now = 1_790_000_000.0;
    let until = limits::quota_block_until(now, &u);
    assert!(
        until > now && until <= at,
        "blok gelecekte ve sıfırlamadan sonra değil: {until} {at}"
    );
}

/// 2.7 tekilleştirme anahtarı (`412f5d3`, `ae0fe1d`, `fa5102d`): yol biçimi, Markdown bağlantısı, Türkçe İ/I.
#[test]
fn finding_key_normalizes_path_link_and_turkish_case() {
    let k = store::finding_key("p", "a.py:3", "İşlem hatası");
    for (w, t) in [
        ("`a.py`:9", "ISLEM HATASI"),
        ("./a.py#L1", "islem hatasi"),
        ("[a.py:3](file:///x/a.py#L3)", "İŞLEM  hatası!"),
    ] {
        assert_eq!(store::finding_key("p", w, t), k, "{w} / {t}");
    }
    assert_ne!(
        store::finding_key("p", "b.py", "işlem hatası"),
        k,
        "başka dosya"
    );
    assert_ne!(
        store::finding_key("q", "a.py", "işlem hatası"),
        k,
        "başka proje"
    );
    // Python'da `file://` öneki ':' bölmesinden SONRA silinir: anahtar "file" yoluna düşer (docs "Python hatası?" 5).
    assert_eq!(
        store::finding_key("p", "file://a.py", "işlem hatası"),
        store::finding_key("p", "file", "işlem hatası")
    );
}

/// 2.7 (`57b9417`): aynı raporun bulguları birbirine karşı asla `dup` olmaz; başka rapordaki aynısı `dup`, `undup` geri alır.
#[test]
fn same_report_never_dup_other_report_dup_and_undup() {
    let d = tempfile::tempdir().unwrap();
    let st = store_at(d.path());
    let r1 = d
        .path()
        .join("reviews/p/agy/m/1/1.md")
        .to_string_lossy()
        .into_owned();
    let r2 = d
        .path()
        .join("reviews/p/evren/n/2/2.md")
        .to_string_lossy()
        .into_owned();
    let same = [
        finding("R-1", "P3", "a.py:1", "İşlem"),
        finding("R-2", "P3", "a.py:9", "işlem"),
    ];
    assert_eq!(st.add_findings("p", &r1, &same).unwrap().len(), 2);
    assert!(
        st.add_findings("p", &r1, &same).unwrap().is_empty(),
        "aynı rapor ikinci kez: çoğalmaz"
    );
    assert!(st
        .add_findings("p", &r2, &[finding("R-1", "P1", "`a.py`:7", "islem")])
        .unwrap()
        .is_empty());
    let data = st.load_findings().unwrap();
    let dups: Vec<&String> = data
        .iter()
        .filter(|(_, v)| v.get("state").and_then(Json::as_str) == Some("dup"))
        .map(|(k, _)| k)
        .collect();
    assert_eq!(dups.len(), 1);
    let canon = data[dups[0]]
        .get("dup_of")
        .and_then(Json::as_str)
        .unwrap()
        .to_string();
    assert_eq!(
        data[&canon].get("severity").and_then(Json::as_str),
        Some("P1"),
        "kanonik kayıt ağırlaşır"
    );
    let res = st
        .decide_finding(dups[0], "undup", 5.0, "owner_cli")
        .unwrap();
    assert_eq!(res.get("state").and_then(Json::as_str), Some("new"));
    let data = st.load_findings().unwrap();
    assert!(data[dups[0]].get("dup_of").is_none());
}

/// 2.7 durum zinciri: karar `state`/`decided_by`/`decided_at`i değiştirir, doğrulama gerekçesi ve diğer alanlar kalır.
/// Önceki durum (verified/unclear/refuted) `verdict_state` alanında saklanır (Python ile aynı, TBD#375).
#[test]
fn decision_keeps_verdict_fields() {
    let d = tempfile::tempdir().unwrap();
    let st = store_at(d.path());
    let r1 = d
        .path()
        .join("reviews/p/agy/m/1/1.md")
        .to_string_lossy()
        .into_owned();
    let ids = st
        .add_findings(
            "p",
            &r1,
            &[
                finding("R-1", "P2", "a.py:1", "t"),
                finding("R-2", "P2", "b.py", "u"),
            ],
        )
        .unwrap();
    st.mark_verify_sent(&ids, "s", "h", 10.0).unwrap();
    let mut data = st.load_findings().unwrap();
    let v = |fid: &str, verdict: &str| Verdict {
        fid: fid.into(),
        verdict: verdict.into(),
        reason: "kodda gördüm".into(),
    };
    let applied = flow::apply_verdicts(
        &mut data,
        "p",
        &[v(&ids[0], "verified"), v(&ids[1], "refuted")],
        "src",
        "s",
        20.0,
        "",
    );
    assert_eq!(applied.len(), 2);
    st.save_findings(data).unwrap();
    let before = st.load_findings().unwrap();
    for (fid, action, to) in [
        (&ids[0], "approve", "approved"),
        (&ids[1], "reject", "rejected"),
    ] {
        let res = st.decide_finding(fid, action, 30.0, "owner_cli").unwrap();
        assert_eq!(res.get("state").and_then(Json::as_str), Some(to));
    }
    let after = st.load_findings().unwrap();
    for fid in &ids {
        let (b, a) = (
            before[fid].as_object().unwrap(),
            after[fid].as_object().unwrap(),
        );
        let mut keys = b.keys().map(String::as_str).collect::<Vec<_>>();
        keys.push("verdict_state");
        assert_eq!(
            a.keys().map(String::as_str).collect::<Vec<_>>(),
            keys,
            "alan silinmedi, sıra korundu"
        );
        assert_eq!(a["verdict_state"], b["state"]);
        for k in b
            .keys()
            .filter(|k| !["state", "decided_by", "decided_at"].contains(&k.as_str()))
        {
            assert_eq!(b[k], a[k], "{fid}.{k}");
        }
        assert_eq!(a["verdict"], Json::Str("kodda gördüm".into()));
    }
    // refuted bulgu onaylanamaz
    let res = st
        .decide_finding(&ids[1], "approve", 40.0, "owner_cli")
        .unwrap();
    assert_eq!(res.get("ok"), Some(&Json::Bool(false)));
}

/// 2.7 gizli değer corpus'u (`aee9a43`): tırnaklı, kaçışlı JSON, DSN (öğrenilen parola tekrarı dahil), `sk-proj`, Bearer, argv.
#[test]
fn redact_secrets_corpus() {
    let cases = [
        (r#"db_password = "supersecret1""#, "supersecret1"),
        ("API_KEY:'abcdefgh12'", "abcdefgh12"),
        (r#"{\"api_key\": \"abcdefghij\"}"#, "abcdefghij"),
        (r#"{"api_key": "abcdefghij"}"#, "abcdefghij"),
        (
            "postgres://u:parola123@host/db ve parola123 tekrar",
            "parola123",
        ),
        ("mysql://İ:şifre1@h şifre1", "şifre1"),
        (
            &format!("sk-proj-{}", "A".repeat(30)),
            "AAAAAAAAAAAAAAAAAAAA",
        ),
        (
            &format!(r#"x="sk-proj-{}""#, "B".repeat(30)),
            "BBBBBBBBBBBBBBBBBBBB",
        ),
        (
            "Authorization: Bearer abcdefghijklmnop.qrst",
            "abcdefghijklmnop",
        ),
        ("--password hunter22 --token=abcd1234", "hunter22"),
        ("--password hunter22 --token=abcd1234", "abcd1234"),
        (&format!("ghp_{}", "a".repeat(36)), "aaaaaaaaaaaaaaaaaaaa"),
        (
            "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
            "\nabc\n",
        ),
    ];
    for (text, secret) in cases {
        let out = redact::redact_secrets(text, &[]);
        assert!(!out.contains(secret), "{text:?} -> {out:?}");
        assert!(out.contains("[REDACTED]"), "{text:?} -> {out:?}");
    }
    assert_eq!(
        redact::redact_secrets("düz metin, sır yok", &[]),
        "düz metin, sır yok"
    );
    // öğrenilmiş kısa parola metni bozmaz, uzun olan her yerde maskelenir
    assert_eq!(redact::redact_secrets("ab abc", &["ab".into()]), "ab abc");
    assert!(
        !redact::redact_secrets("x kodparola1 y", &["kodparola1".into()]).contains("kodparola1")
    );
}

/// 2.7 (`c34395e`): başlığı olup gövdesi boş/çöp rapor; karar (error, bulgu kaydı yok) koşucuda (T8).
#[test]
fn bodyless_report_detected() {
    assert!(report::report_bodyless("## R-1 | P1 | a | b\n"));
    assert!(report::report_bodyless("## R-1 | P1 | a | b\n..."));
    assert!(report::report_bodyless("## R-1 | P1 | a | b\naaa"));
    assert!(!report::report_bodyless("## R-1 | P1 | a | b\nok"));
    assert!(!report::report_bodyless("BULGU YOK"));
}

/// 2.7 aktarım deposu (`export_root`): kayıtlı depo, worktree'nin ana deposu; silinmiş worktree izlenmez, çözülemeyen "".
#[test]
fn export_root_routes_and_never_follows_deleted_worktree() {
    let t = tempfile::tempdir().unwrap();
    let d = std::fs::canonicalize(t.path()).unwrap();
    let s = |p: &str| d.join(p).to_string_lossy().into_owned();
    for p in [
        "reg/.git",
        "main/.git/worktrees/w",
        "combo/wt",
        "combo/gone",
        "combo/plain",
    ] {
        std::fs::create_dir_all(d.join(p)).unwrap();
    }
    std::fs::write(
        d.join("combo/wt/.git"),
        format!("gitdir: {}/.git/worktrees/w\n", s("main")),
    )
    .unwrap();
    std::fs::write(
        d.join("combo/gone/.git"),
        format!("gitdir: {}/.git/worktrees/w\n", s("silindi")),
    )
    .unwrap();
    let reg = s("reg");
    let yok = s("yok");
    let resolve = |p: &str| match p {
        "reg" => reg.clone(),
        "bad" => yok.clone(),
        _ => String::new(),
    };
    let combo = s("combo");
    let root = |w: &str, cwd: &str| {
        export::export_root(&row(&[("where", w)]), "combo", cwd, resolve).unwrap()
    };
    assert_eq!(root("reg/a.py:1", &combo), s("reg"));
    assert_eq!(root("wt/a.py:2", &combo), s("main"));
    assert_eq!(
        root("gone/a.py:3", &combo),
        "",
        "silinmiş ana depoya işaret eden worktree"
    );
    assert_eq!(root("plain/a.py", &combo), "", "depo olmayan alt dizin");
    assert_eq!(
        root("missing/a.py", &combo),
        combo,
        "Python: dizin yoksa cwd"
    );
    for w in ["a.py", "/etc/x.py", "../x.py", "combo/a.py"] {
        assert_eq!(root(w, &combo), combo, "{w}");
    }
    assert_eq!(
        root("bad/a.py", &s("reg")),
        s("reg"),
        "kayıtlı yol yoksa git'li cwd"
    );
    // bozuk (UTF-8 olmayan) .git dosyası: Python UnicodeDecodeError, Rust Err
    std::fs::create_dir_all(d.join("combo/bin")).unwrap();
    std::fs::write(d.join("combo/bin/.git"), b"gitdir: \xff\n").unwrap();
    assert!(
        export::export_root(&row(&[("where", "bin/a.py")]), "combo", &combo, |_| {
            String::new()
        })
        .is_err()
    );
}

/// Bölüm 3 madde 2/7: depo yazımları Python ile aynı `<kök>/.lock` flock'u altında; bekleme süreyle sınırlı, 0600.
#[test]
fn lock_is_bounded_and_private() {
    use std::os::unix::fs::PermissionsExt;
    let d = tempfile::tempdir().unwrap();
    let mut st = store_at(d.path());
    let held = st.lock().unwrap();
    st.lock_timeout = std::time::Duration::from_millis(200);
    let t0 = std::time::Instant::now();
    assert!(matches!(
        st.lock(),
        Err(cops_review_core::Error::LockTimeout(_))
    ));
    assert!(t0.elapsed() < std::time::Duration::from_secs(5));
    assert!(matches!(
        st.add_findings("p", "/r.md", &[]),
        Err(cops_review_core::Error::LockTimeout(_))
    ));
    drop(held);
    st.add_findings("p", "/r.md", &[finding("R-1", "P1", "a", "b")])
        .unwrap();
    let mode = |p: &Path| std::fs::metadata(p).unwrap().permissions().mode() & 0o777;
    assert_eq!(mode(&st.paths.lock), 0o600);
    assert_eq!(mode(&st.paths.findings), 0o600);
}

/// 2.7 bozuk girdi: bozuk JSON yedeklenip boş sayılır ve ÜSTÜNE YAZILMAZ, UTF-8 olmayan dosya `Err`, nesne olmayan çift kaydı sayılmaz.
#[test]
fn broken_inputs_fail_loud_or_backup() {
    let d = tempfile::tempdir().unwrap();
    let st = store_at(d.path());
    std::fs::write(&st.paths.findings, b"{bozuk").unwrap();
    assert!(st.load_findings().unwrap().is_empty());
    let backups = std::fs::read_dir(d.path())
        .unwrap()
        .filter(|e| {
            e.as_ref()
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with("findings.json.corrupt-")
        })
        .count();
    assert_eq!(backups, 1, "kanıt yedeği");
    assert!(matches!(
        st.save_findings(Map::new()),
        Err(cops_review_core::Error::StoreCorrupt(_))
    ));
    assert_eq!(std::fs::read(&st.paths.findings).unwrap(), b"{bozuk");
    // Eşlenmemiş vekil: okunur (Python gibi), geri yazılmaz, bozuk yedeği alınmaz.
    let raw = br#"{"projects": {}, "not": "\ud800"}"#;
    std::fs::write(&st.paths.review_pool, raw).unwrap();
    let pool = st.load_pool().unwrap();
    assert!(st.save_pool(&pool).is_err());
    assert_eq!(std::fs::read(&st.paths.review_pool).unwrap(), raw);
    std::fs::write(&st.paths.review_history, b"\xff\xfe{}").unwrap();
    assert!(st.load_history().is_err());
    std::fs::write(&st.paths.review_pool, b"[]").unwrap();
    assert_eq!(
        st.load_pool().unwrap().get("projects"),
        Some(&Json::object())
    );
    assert!(matches!(
        st.save_history(&Map::new()),
        Err(cops_review_core::Error::StoreCorrupt(_))
    ));
    assert!(matches!(
        st.save_pool(&Json::object()),
        Err(cops_review_core::Error::StoreCorrupt(_)) | Err(cops_review_core::Error::Value(_))
    ));
    assert!(!targets::counts_as_attempt(Some(&Json::Str(
        "bozuk".into()
    ))));
    assert!(targets::counts_as_attempt(Some(&Json::Str(String::new()))));
    assert!(targets::counts_as_attempt(None));
}

/// U+1D7CE..U+1D7FF bitişik beş `Nd` bloğudur: her blokta rakam 0..=9 (Python `int()` ile aynı).
#[test]
fn adjacent_decimal_blocks_keep_their_values() {
    for block in 0..5u32 {
        for d in 0..10u32 {
            let c = char::from_u32(0x1D7CE + block * 10 + d).unwrap();
            assert_eq!(
                targets::parse_slots(&format!("agy={c}"))
                    .iter()
                    .find(|(m, _)| *m == "agy")
                    .map(|(_, n)| *n),
                Some(u64::from(d)),
                "U+{:04X}",
                c as u32
            );
        }
    }
}
