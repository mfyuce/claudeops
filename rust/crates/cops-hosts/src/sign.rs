//! Giden isteklere imzalı kimlik başlıkları (Python `authz.outbound_headers`). Çekirdek yalnız sözleşmeyi bilir,
//! enterprise doldurur.

use std::panic::{catch_unwind, AssertUnwindSafe};

pub use cops_auth::authz::Principal;

/// İstek imzalanamaz ve politika bunu yasaklıyor. `reason` kısa makine kodu.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OutboundRefused {
    pub reason: String,
}

pub struct SignRequest<'a> {
    pub principal: &'a Principal,
    pub host_name: &'a str,
    pub method: &'a str,
    /// Sorgusuz yol (token imzaya girmez).
    pub path: &'a str,
    /// `None` = akış / gövdesiz.
    pub body: Option<&'a [u8]>,
}

pub trait OutboundSigner: Send + Sync {
    /// Her deneme için ayrı çağrılır (nonce). Engellememeli (senkron, G/Ç yok).
    fn sign(&self, req: SignRequest<'_>) -> Result<Vec<(String, String)>, OutboundRefused>;
}

/// İsteğin kimin adına gittiği. Python'daki iş parçacığına bağlı `current_principal()`in açık karşılığı: görevler arası
/// sızma olmaz.
#[derive(Debug, Clone, Copy)]
pub enum Caller<'a> {
    /// Kimlik bağlı değil (durum yoklaması, değnekçi): REST isteği imzalanmaz.
    Unbound,
    User(&'a Principal),
}

/// İmza başlıklarını doğrulanmış biçimde üretir. Signer yoksa boş. Panik ya da geçersiz başlık = RED (kapalı yön).
pub(crate) fn headers_for(
    signer: Option<&dyn OutboundSigner>,
    req: SignRequest<'_>,
) -> Result<Vec<(http::HeaderName, http::HeaderValue)>, OutboundRefused> {
    let Some(s) = signer else {
        return Ok(Vec::new());
    };
    let refused = |r: &str| OutboundRefused { reason: r.into() };
    let out =
        catch_unwind(AssertUnwindSafe(|| s.sign(req))).map_err(|_| refused("signer_failed"))??;
    out.into_iter()
        .map(|(k, v)| {
            let name =
                http::HeaderName::from_bytes(k.as_bytes()).map_err(|_| refused("bad_header"))?;
            // İmza kancası taşıma başlıklarını ezemez.
            if [
                http::header::HOST,
                http::header::CONTENT_LENGTH,
                http::header::TRANSFER_ENCODING,
                http::header::CONNECTION,
                http::header::UPGRADE,
            ]
            .contains(&name)
                || name.as_str().starts_with("sec-websocket-")
            {
                return Err(refused("bad_header"));
            }
            let value = http::HeaderValue::from_str(&v).map_err(|_| refused("bad_header"))?;
            Ok((name, value))
        })
        .collect()
}
