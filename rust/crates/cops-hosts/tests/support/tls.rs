//! Test PKI: geçici kök (CA) + 127.0.0.1 yaprak sertifikası. İstemci tarafı yalnız programatik `Connector.tls` ile özel
//! kök alır (üretimde ortam değişkeni/ayar yok); doğrulama GEVŞETİLMEZ (ad ve zincir denetimi rustls'te).

use std::sync::Arc;

use cops_hosts::net::{tls_config, Connector, Resolver};
use rcgen::{BasicConstraints, CertificateParams, CertifiedIssuer, IsCa, KeyPair};
use tokio_rustls::rustls::crypto::ring::default_provider;
use tokio_rustls::rustls::pki_types::{CertificateDer, PrivateKeyDer, PrivatePkcs8KeyDer};
use tokio_rustls::rustls::{RootCertStore, ServerConfig};
use tokio_rustls::TlsAcceptor;

pub struct Ca {
    issuer: CertifiedIssuer<'static, KeyPair>,
}

impl Ca {
    pub fn new(cn: &str) -> Ca {
        let mut p = CertificateParams::new(Vec::<String>::new()).unwrap();
        p.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
        p.distinguished_name
            .push(rcgen::DnType::CommonName, cn.to_string());
        let issuer = CertifiedIssuer::self_signed(p, KeyPair::generate().unwrap()).unwrap();
        Ca { issuer }
    }

    pub fn der(&self) -> CertificateDer<'static> {
        self.issuer.der().clone()
    }

    /// Verilen SAN'lar için (IP literali ya da DNS adı) yaprak sertifika + anahtar.
    pub fn leaf(&self, sans: &[&str]) -> (Vec<CertificateDer<'static>>, PrivateKeyDer<'static>) {
        let p =
            CertificateParams::new(sans.iter().map(|s| s.to_string()).collect::<Vec<_>>()).unwrap();
        let key = KeyPair::generate().unwrap();
        let cert = p.signed_by(&key, &self.issuer).unwrap();
        (
            vec![cert.der().clone(), self.der()],
            PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(key.serialize_der())),
        )
    }

    /// Bu kökle `127.0.0.1` için sunucu.
    pub fn acceptor(&self, sans: &[&str], alpn: &[&[u8]]) -> TlsAcceptor {
        let (chain, key) = self.leaf(sans);
        let mut cfg = ServerConfig::builder_with_provider(Arc::new(default_provider()))
            .with_safe_default_protocol_versions()
            .unwrap()
            .with_no_client_auth()
            .with_single_cert(chain, key)
            .unwrap();
        cfg.alpn_protocols = alpn.iter().map(|p| p.to_vec()).collect();
        TlsAcceptor::from(Arc::new(cfg))
    }
}

/// Yalnız `ca` köküne güvenen bağlantı kurucu (sistem kökleri YOK).
pub fn connector_trusting(ca: &Ca, resolver: Option<Resolver>) -> Connector {
    let mut roots = RootCertStore::empty();
    roots.add(ca.der()).unwrap();
    let mut c = Connector {
        tls: Some(tls_config(roots).unwrap()),
        ..Default::default()
    };
    if let Some(r) = resolver {
        c.resolver = r;
    }
    c
}
