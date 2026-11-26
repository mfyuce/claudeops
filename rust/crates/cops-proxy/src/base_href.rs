//! Rootrel mount kökündeki HTML'in `<base href>`ini bulur: yalnız belge başı okunur, okunan baytlar gövdeye geri eklenir.
use crate::Body;
use bytes::Bytes;
use http_body_util::BodyExt;
use hyper::body::{Body as HttpBody, Frame, SizeHint};
use hyper::header::{CONTENT_ENCODING, CONTENT_TYPE};
use hyper::{Response, StatusCode};
use std::pin::Pin;
use std::task::{Context, Poll};

/// En çok bu kadar bayt (ya da `</head>`e kadar) okunur.
const HEAD_LIMIT: usize = 64 * 1024;

/// Okunmuş çerçeve + gövdenin kalanı.
struct Replay {
    first: Option<Bytes>,
    err: Option<hyper::Error>,
    rest: Body,
}

impl HttpBody for Replay {
    type Data = Bytes;
    type Error = hyper::Error;

    fn poll_frame(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, hyper::Error>>> {
        if let Some(b) = self.first.take() {
            return Poll::Ready(Some(Ok(Frame::data(b))));
        }
        if let Some(e) = self.err.take() {
            return Poll::Ready(Some(Err(e)));
        }
        Pin::new(&mut self.rest).poll_frame(cx)
    }

    fn size_hint(&self) -> SizeHint {
        let n = self.first.as_ref().map_or(0, |b| b.len() as u64);
        let r = self.rest.size_hint();
        let mut h = SizeHint::new();
        h.set_lower(r.lower() + n);
        if let Some(u) = r.upper() {
            h.set_upper(u + n);
        }
        h
    }
}

/// 200 + sıkıştırılmamış HTML ise belge başını okuyup `<base href>` değerini döner; yanıt her durumda aynen geri verilir.
pub(crate) async fn inspect(resp: Response<Body>) -> (Response<Body>, Option<String>) {
    let html = resp.status() == StatusCode::OK
        && !resp.headers().contains_key(CONTENT_ENCODING)
        && resp
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .is_some_and(|v| v.trim_start().to_ascii_lowercase().starts_with("text/html"));
    if !html {
        return (resp, None);
    }
    let (parts, mut rest) = resp.into_parts();
    let mut buf = Vec::new();
    let mut err = None;
    while buf.len() < HEAD_LIMIT && !contains_head_end(&buf) {
        match rest.frame().await {
            Some(Ok(f)) => {
                if let Ok(d) = f.into_data() {
                    buf.extend_from_slice(&d);
                }
            }
            Some(Err(e)) => {
                err = Some(e);
                break;
            }
            None => break,
        }
    }
    let href = find_base_href(&buf);
    let body = Replay {
        first: (!buf.is_empty()).then(|| Bytes::from(buf)),
        err,
        rest,
    }
    .boxed();
    (Response::from_parts(parts, body), href)
}

fn contains_head_end(b: &[u8]) -> bool {
    b.windows(7).any(|w| w.eq_ignore_ascii_case(b"</head>"))
}

fn find_base_href(html: &[u8]) -> Option<String> {
    let text = String::from_utf8_lossy(html);
    let low = text.to_ascii_lowercase();
    let start = low.match_indices("<base").map(|(i, _)| i).find(|i| {
        low[i + 5..]
            .chars()
            .next()
            .is_some_and(|c| c.is_ascii_whitespace())
    })?;
    let end = start + low[start..].find('>')?;
    let tag = &low[start..end];
    let at = tag
        .match_indices("href=")
        .map(|(i, _)| i)
        .find(|i| tag[..*i].ends_with(|c: char| c.is_ascii_whitespace()))?;
    let v = start + at + 5;
    let quote = text[v..]
        .chars()
        .next()
        .filter(|c| *c == '"' || *c == '\'')?;
    let val = &text[v + 1..];
    Some(val[..val.find(quote)?].to_string())
}

/// `href` aynı kökende, mount `id` DIŞINDA bir yol kökü mü: (yönlendirilecek yol, öğrenilecek ilk parça). Göreli, `//host`,
/// ters bölü, sorgu/fragment ve panel kökleri reddedilir.
pub(crate) fn foreign_root(href: String, id: &str) -> Option<(String, String)> {
    let safe = href.starts_with('/')
        && !href.starts_with("//")
        && href
            .bytes()
            .all(|c| c.is_ascii_graphic() && !matches!(c, b'\\' | b'?' | b'#' | b'%'));
    if !safe || href.split('/').any(|s| s == "." || s == "..") {
        return None;
    }
    let seg = href[1..].split('/').next()?.to_string();
    (seg != id && crate::mount::learnable(&seg)).then_some((href, seg))
}

/// Mount `id` altındaki `path` için yönlendirme yolu: mount kökü `href`e gider; `href`in (sonu `/`) altındaki sayfa kendi
/// öneksiz yoluna. Başka sayfa None.
pub(crate) fn target(path: &str, id: &str, href: &str) -> Option<String> {
    let rest = path.strip_prefix('/')?.strip_prefix(id)?;
    if rest == "/" {
        return Some(href.to_string());
    }
    (href.ends_with('/') && rest.to_ascii_lowercase().starts_with(href)).then(|| rest.to_string())
}
