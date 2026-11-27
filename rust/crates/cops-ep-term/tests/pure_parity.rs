//! Saf işlevlerin Python paritesi (bayt bayt): hata şablonları (web.py `ERR`), mod algılama (`_detect_mode_in_text` +
//! `get_provider`), `web_term_lite` (`to_lite` memo'suz, `viewport_text`, URL/yol adayları) rastgele ekranlar üzerinde; ayrıca
//! mod desenlerinin harf sınıfları Python `re.IGNORECASE` ve `\s` ile tüm BMP'de aynı.
mod common;
use common::Env;
use cops_ep_state::pyjson;
use cops_ep_term::{err, lite, mode};
use cops_state::Json;

const PY: &str = r#"
from claudeops.commands import web as w
from claudeops.commands import web_term_lite as L
from claudeops.providers import get_provider
inp = json.loads(sys.stdin.read())
out = {"err": [], "mode": [], "lite": [], "vt": []}
for key in inp["keys"]:
    for lang in ("tr", "en", "xx"):
        out["err"].append(json.dumps(w._err(lang, key, name=inp["name"], candidates=inp["cand"])))
for t in inp["texts"]:
    out["mode"].append(json.dumps([w._detect_mode_in_text(t, get_provider(c)) for c in inp["clis"]]))
    for rows in (1, 3, 40):
        out["lite"].append(json.dumps(L.to_lite({"ok": True, "text": t, "cols": 80, "rows": rows, "masked": False, "mode": None})))
    out["vt"].append(json.dumps([L.viewport_text(t, r) for r in (0, 1, 2, 5)]))
sys.stdout.write(json.dumps(out))
"#;

const CLIS: [&str; 8] = [
    "claude",
    "agy",
    "codex",
    "copilot",
    "shell",
    "ucli",
    "bilinmeyen",
    "",
];

/// Belirlenimci rastgele ekranlar: ANSI, mod metinleri (büyük/küçük, `İ`/`ı`/`ſ`, Python boşlukları), URL/yol, satır
/// ayıraçlarının hepsi, sondaki noktalama.
fn corpus() -> Vec<String> {
    let parts = [
        "plan mode on",
        "PLAN MODE ON",
        "accept ed\u{131}ts on",
        "accept edits on",
        "auto mode on",
        "AUTO MODE ON",
        "manual mode on",
        "manual mode \u{130}n",
        "mode on",
        "· plan ·",
        "·\u{1c}autopilot\t·",
        "·plan·",
        "· autopilot ·",
        "\x1b[38;5;220m",
        "\x1b[0m",
        "\x1b[2m",
        "\x1b]8;;https://osc.test\x07",
        "\x1b]0;baslik\x1b\\",
        "https://a.test/x).",
        "https://b.test/y?q=1,",
        "http://c.test",
        "./src/a.rs",
        "../b/c",
        "~/d/e:",
        "/tmp/z]",
        "/",
        "x",
        "ç",
        "ı",
        "ſ",
        " ",
        "\t",
        "\n",
        "\r\n",
        "\r",
        "\x0b",
        "\x0c",
        "\x1c",
        "\x1d",
        "\x1e",
        "\x1f",
        "\u{85}",
        "\u{2028}",
        "\u{2029}",
        "\u{a0}",
        "'q'",
        "\"r\"",
        "<s>",
        "😀",
        "─",
        "❯",
    ];
    let mut seed: u64 = 0x2a2a_b2a0;
    let mut next = || {
        seed = seed
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        (seed >> 33) as usize
    };
    let mut out: Vec<String> = vec![
        String::new(),
        "\n".into(),
        "plan mode on\n".into(),
        format!("plan mode on\n{}", "a\n".repeat(8)),
        format!("plan mode on\n{}", "a\n \n".repeat(7)),
        format!("{}auto mode on\n", "x\n".repeat(50)),
    ];
    for _ in 0..400 {
        let n = 1 + next() % 40;
        out.push((0..n).map(|_| parts[next() % parts.len()]).collect());
    }
    out
}

#[test]
fn pure_functions_match_python() {
    let env = Env::new();
    let texts = corpus();
    let (name, cand) = ("ad {x} ç\u{1c}", "a, {name}");
    let keys: Vec<Json> = err::Key::ALL
        .iter()
        .map(|k| Json::Str(k.code().into()))
        .collect();
    let input = format!(
        r#"{{"keys": {}, "name": {}, "cand": {}, "clis": {}, "texts": {}}}"#,
        pyjson::dumps(&Json::Array(keys)),
        pyjson::dumps(&Json::Str(name.into())),
        pyjson::dumps(&Json::Str(cand.into())),
        pyjson::dumps(&lite::strs(CLIS.iter().map(|s| s.to_string()).collect())),
        pyjson::dumps(&lite::strs(texts.clone())),
    );
    let py = Json::parse(&env.py(None, PY, &input)).unwrap();
    let list = |k: &str| -> Vec<String> {
        py.get(k)
            .unwrap()
            .as_array()
            .unwrap()
            .iter()
            .map(|s| s.as_str().unwrap().to_string())
            .collect()
    };
    let mut i = 0;
    let pe = list("err");
    for k in err::Key::ALL {
        for en in [false, true, false] {
            assert_eq!(
                pyjson::dumps(&err::err(en, k, name, cand)),
                pe[i],
                "{k:?} en={en}"
            );
            i += 1;
        }
    }
    let (pm, pl, pv) = (list("mode"), list("lite"), list("vt"));
    let (mut modes, mut urls) = (0, 0);
    for (j, t) in texts.iter().enumerate() {
        let got: Vec<Json> = CLIS
            .iter()
            .map(|c| mode::detect(t, c).map_or(Json::Null, |m| Json::Str(m.into())))
            .collect();
        modes += got.iter().filter(|m| **m != Json::Null).count();
        assert_eq!(pyjson::dumps(&Json::Array(got)), pm[j], "mod, metin {t:?}");
        for (r, rows) in [1i64, 3, 40].into_iter().enumerate() {
            let f = lite::obj(vec![
                ("ok", Json::Bool(true)),
                ("text", Json::Str(t.clone())),
                ("cols", Json::Int(80)),
                ("rows", Json::Int(rows)),
                ("masked", Json::Bool(false)),
                ("mode", Json::Null),
            ]);
            let got = pyjson::dumps(&lite::to_lite(f));
            urls += usize::from(got.contains("\"urls\": [\""));
            assert_eq!(got, pl[j * 3 + r], "lite rows={rows}, metin {t:?}");
        }
        let vt: Vec<String> = [0u64, 1, 2, 5]
            .iter()
            .map(|r| lite::viewport_text(t, *r))
            .collect();
        assert_eq!(
            pyjson::dumps(&lite::strs(vt)),
            pv[j],
            "viewport_text, metin {t:?}"
        );
    }
    assert!(
        modes > 100 && urls > 100,
        "külliyat zayıf: mod {modes}, url {urls}"
    );
}

/// Mod desenlerinin harf sınıfları ve `\s` sınıfı, tüm BMP'de (vekil yarımlar hariç) Python ile aynı karakterleri eşler.
#[test]
fn pattern_classes_match_python_over_the_bmp() {
    let env = Env::new();
    let py = env.py(
        None,
        r#"
import re
out = {}
for c in "acdeilmnopstu":
    r = re.compile(c, re.I)
    out[c] = [i for i in range(0x10000) if not 0xd800 <= i < 0xe000 and r.fullmatch(chr(i))]
r = re.compile(r"\s")
out["space"] = [i for i in range(0x10000) if not 0xd800 <= i < 0xe000 and r.fullmatch(chr(i))]
sys.stdout.write(json.dumps(out))
"#,
        "",
    );
    let py = Json::parse(&py).unwrap();
    let chars = |k: &str| -> Vec<i64> {
        py.get(k)
            .unwrap()
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_i64().unwrap())
            .collect()
    };
    let bmp = || (0u32..0x10000).filter_map(char::from_u32);
    for c in "acdeilmnopstu".chars() {
        let re = regex::Regex::new(&format!("^(?:{})$", mode::ci_class(c))).unwrap();
        let rs: Vec<i64> = bmp()
            .filter(|ch| re.is_match(&ch.to_string()))
            .map(|ch| ch as i64)
            .collect();
        assert_eq!(rs, chars(&c.to_string()), "harf {c}");
    }
    let sp = regex::Regex::new(&format!("^{}$", mode::PY_SPACE_CLASS)).unwrap();
    let rs: Vec<i64> = bmp()
        .filter(|ch| sp.is_match(&ch.to_string()))
        .map(|ch| ch as i64)
        .collect();
    assert_eq!(rs, chars("space"));
}
