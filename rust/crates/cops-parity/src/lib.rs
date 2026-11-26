//! Parite koşucusu: aynı isteği Python iç portuna ve Rust ön kapıya verir, yanıtları normalize edip karşılaştırır
//! (docs/rust-sprint-plan.md "PARITE"; docs/rs-gate.md). İstekler sırayla koşar; her isteğin iki yanı aynı anda gider
//! (zamana bağlı alan farkı en aza insin).

pub mod compare;
pub mod config;

use bytes::Bytes;
use compare::Diff;
use config::Case;
use http_body_util::{BodyExt, Full, Limited};
use hyper::header::{HeaderMap, HeaderName, HeaderValue, AUTHORIZATION, CONTENT_TYPE};
use hyper_util::client::legacy::{connect::HttpConnector, Client};
use hyper_util::rt::TokioExecutor;
use serde_json::Value;
use std::net::SocketAddr;
use std::time::Duration;

/// `cops_proxy::PARITY_HEADER` / `SERVED_HEADER`.
const PARITY_HEADER: &str = "x-cops-parity";
const SERVED_HEADER: &str = "x-cops-served";
pub const MAX_BODY: usize = 16 << 20;

pub struct Target {
    pub python: SocketAddr,
    pub rust: SocketAddr,
    /// Panel token'ı; `Authorization: Bearer` ile gider (URL'ye ve argv'ye girmez).
    pub token: Option<String>,
    pub timeout: Duration,
}

struct Reply {
    status: u16,
    headers: HeaderMap,
    body: Bytes,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    Pass,
    Fail,
    /// İstek yapılamadı (bağlantı, süre, boyut).
    Error,
    /// Yan etkisiz olduğu bilinmiyor: koşulmadı.
    Skipped,
}

#[derive(Debug)]
pub struct Outcome {
    pub name: String,
    pub verdict: Verdict,
    /// Rust tarafında isteği kimin cevapladığı (`local` / `python`); başlığı bilmeyen eski ön kapıda `None`.
    pub served: Option<String>,
    /// Gövde dışı sorunlar (durum, başlık, hata).
    pub notes: Vec<String>,
    pub diffs: Vec<Diff>,
}

async fn fetch(
    client: &Client<HttpConnector, Full<Bytes>>,
    addr: SocketAddr,
    case: &Case,
    t: &Target,
    mark: bool,
) -> Result<Reply, String> {
    let mut req = hyper::Request::builder()
        .method(case.method.as_str())
        .uri(format!("http://{addr}{}", case.path));
    let headers = req.headers_mut().ok_or("geçersiz yöntem ya da yol")?;
    if let Some(tok) = &t.token {
        let mut v = HeaderValue::from_str(&format!("Bearer {tok}"))
            .map_err(|_| "token başlığa yazılamıyor".to_string())?;
        v.set_sensitive(true);
        headers.insert(AUTHORIZATION, v);
    }
    if case.body.is_some() {
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
    }
    for (k, v) in &case.request_headers {
        headers.insert(
            HeaderName::from_bytes(k.as_bytes()).map_err(|_| format!("geçersiz başlık {k:?}"))?,
            HeaderValue::from_str(v).map_err(|_| format!("geçersiz başlık değeri: {k:?}"))?,
        );
    }
    if mark {
        headers.insert(PARITY_HEADER, HeaderValue::from_static("1"));
    }
    let req = req
        .body(Full::new(Bytes::from(
            case.body.clone().unwrap_or_default(),
        )))
        .map_err(|e| e.to_string())?;
    let work = async {
        let r = client.request(req).await.map_err(|e| e.to_string())?;
        let (parts, body) = r.into_parts();
        let body = Limited::new(body, MAX_BODY)
            .collect()
            .await
            .map_err(|e| e.to_string())?
            .to_bytes();
        Ok::<_, String>(Reply {
            status: parts.status.as_u16(),
            headers: parts.headers,
            body,
        })
    };
    tokio::time::timeout(t.timeout, work)
        .await
        .map_err(|_| "süre aşımı".to_string())?
}

fn header_values(h: &HeaderMap, name: &str) -> Vec<String> {
    h.get_all(name)
        .iter()
        .map(|v| String::from_utf8_lossy(v.as_bytes()).into_owned())
        .collect()
}

/// `content-type` medya türü (parametreler ve harf büyüklüğü atılır).
fn media_type(h: &HeaderMap) -> String {
    header_values(h, "content-type")
        .first()
        .and_then(|v| v.split(';').next())
        .map(|v| v.trim().to_ascii_lowercase())
        .unwrap_or_default()
}

fn judge(case: &Case, py: Reply, rs: Reply, o: &mut Outcome) {
    o.served = header_values(&rs.headers, SERVED_HEADER).into_iter().next();
    if case.expect_local && o.served.as_deref() != Some("local") {
        o.notes.push(format!(
            "Rust'ta cevaplanması beklendi, cevaplayan: {}",
            o.served.as_deref().unwrap_or("bilinmiyor")
        ));
    }
    if py.status != rs.status {
        o.notes
            .push(format!("durum: python {} / rust {}", py.status, rs.status));
    }
    let (a, b) = (media_type(&py.headers), media_type(&rs.headers));
    if a != b {
        o.notes
            .push(format!("content-type: python {a:?} / rust {b:?}"));
    }
    for h in &case.compare_headers {
        if header_values(&py.headers, h) != header_values(&rs.headers, h) {
            o.notes.push(format!("başlık farklı: {h}"));
        }
    }
    let json = |b: &Bytes| serde_json::from_slice::<Value>(b).ok();
    match (json(&py.body), json(&rs.body)) {
        (Some(x), Some(y)) => o.diffs = compare::diff(&x, &y, &case.rules),
        _ => {
            if py.body != rs.body {
                o.notes.push(format!(
                    "gövde farklı (JSON değil): python {} bayt / rust {} bayt",
                    py.body.len(),
                    rs.body.len()
                ));
            }
        }
    }
    o.verdict = if o.notes.is_empty() && o.diffs.is_empty() {
        Verdict::Pass
    } else {
        Verdict::Fail
    };
}

/// Listeyi koşar. `include_unsafe`: yan etkisiz olduğu bilinmeyen istekler de koşar (her biri İKİ kez uygulanır).
pub async fn run(cases: &[Case], t: &Target, include_unsafe: bool) -> Vec<Outcome> {
    let client: Client<HttpConnector, Full<Bytes>> = Client::builder(TokioExecutor::new())
        .pool_max_idle_per_host(0)
        .build_http();
    let mut out = Vec::with_capacity(cases.len());
    for case in cases {
        let mut o = Outcome {
            name: case.name.clone(),
            verdict: Verdict::Skipped,
            served: None,
            notes: Vec::new(),
            diffs: Vec::new(),
        };
        if case.safe() || include_unsafe {
            let (py, rs) = tokio::join!(
                fetch(&client, t.python, case, t, false),
                fetch(&client, t.rust, case, t, true)
            );
            match (py, rs) {
                (Ok(py), Ok(rs)) => judge(case, py, rs, &mut o),
                (py, rs) => {
                    o.verdict = Verdict::Error;
                    for (side, r) in [("python", py), ("rust", rs)] {
                        if let Err(e) = r {
                            o.notes.push(format!("{side}: {e}"));
                        }
                    }
                }
            }
        }
        out.push(o);
    }
    out
}

fn shown(v: &Option<Value>, values: bool) -> String {
    match v {
        None => "yok".into(),
        Some(v) if values => {
            let s = v.to_string();
            match s.char_indices().nth(200) {
                Some((i, _)) => format!("{}…", &s[..i]),
                None => s,
            }
        }
        Some(v) => format!("<{}>", compare::kind(v)),
    }
}

/// İnsan okur rapor. Gövde değerleri sır taşıyabilir: yalnız `values` ile yazılır (aksi halde yer + tür).
pub fn report(outcomes: &[Outcome], values: bool) -> String {
    const MAX_LINES: usize = 40;
    let mut s = String::new();
    for o in outcomes {
        let tag = match o.verdict {
            Verdict::Pass => "GEÇTİ",
            Verdict::Fail => "FARK",
            Verdict::Error => "HATA",
            Verdict::Skipped => "ATLANDI",
        };
        let served = o
            .served
            .as_deref()
            .map(|v| format!(" [{v}]"))
            .unwrap_or_default();
        s.push_str(&format!("{tag}{served} {}\n", o.name));
        for n in &o.notes {
            s.push_str(&format!("    {n}\n"));
        }
        for d in o.diffs.iter().take(MAX_LINES) {
            s.push_str(&format!(
                "    {}: {} (python {} / rust {})\n",
                d.at,
                d.what,
                shown(&d.python, values),
                shown(&d.rust, values)
            ));
        }
        if o.diffs.len() > MAX_LINES {
            s.push_str(&format!("    … {} fark daha\n", o.diffs.len() - MAX_LINES));
        }
    }
    let count = |v| outcomes.iter().filter(|o| o.verdict == v).count();
    let proxied = outcomes
        .iter()
        .filter(|o| o.verdict == Verdict::Pass && o.served.as_deref() != Some("local"))
        .count();
    s.push_str(&format!(
        "toplam {}: geçti {} (bunun {proxied} tanesi Rust'ta cevaplanmadı), fark {}, hata {}, atlandı {}\n",
        outcomes.len(),
        count(Verdict::Pass),
        count(Verdict::Fail),
        count(Verdict::Error),
        count(Verdict::Skipped)
    ));
    s
}

/// 0 = hepsi geçti, 1 = fark/hata var ya da HİÇBİR istek koşmadı.
pub fn exit_code(outcomes: &[Outcome]) -> i32 {
    let bad = outcomes
        .iter()
        .any(|o| matches!(o.verdict, Verdict::Fail | Verdict::Error));
    let ran = outcomes.iter().any(|o| o.verdict == Verdict::Pass);
    i32::from(bad || !ran)
}
