//! Yetki sözleşmesi (Python `claudeops/authz.py` ile aynı): kimlik/kaynak tipleri, eylem tablosu ve kapı trait'leri.
//! Davranış YOK: doldurma enterprise tarafında. Eşitlik `tests/data/authz_vectors.json` ile denetlenir
//! (üreten: `py/tests/test_authz_vectors.py`).

use std::future::Future;
use std::net::IpAddr;
use std::pin::Pin;

/// Tablo dışı yolun eylemi: yalnız admin (varsayılan RED authorizer'ın sorumluluğu).
pub const UNMAPPED: &str = "admin.unmapped";
/// `web.token` sahibinin kimliği (Python `LEGACY.uid`).
pub const LEGACY_UID: &str = "owner";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Human,
    Agent,
    Legacy,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Principal {
    pub uid: String,
    pub roles: Vec<String>,
    pub kind: Kind,
    pub ticket_id: String,
}

impl Principal {
    pub fn legacy() -> Principal {
        Principal {
            uid: LEGACY_UID.into(),
            roles: vec!["admin".into()],
            kind: Kind::Legacy,
            ticket_id: String::new(),
        }
    }

    pub fn has_role(&self, role: &str) -> bool {
        self.roles.iter().any(|r| r == role)
    }
}

/// İsteğin dokunduğu kaynak. `kind`: `session` | `project` | `host` | `global` | `steward`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Resource {
    pub kind: String,
    pub host: String,
    pub name: String,
    pub cwd: String,
    pub steward: String,
}

impl Default for Resource {
    fn default() -> Resource {
        Resource {
            kind: "global".into(),
            host: String::new(),
            name: String::new(),
            cwd: String::new(),
            steward: String::new(),
        }
    }
}

/// Authenticator'a verilen salt okunur istek görünümü.
#[derive(Debug, Clone)]
pub struct RequestView {
    pub method: String,
    pub path: String,
    pub raw_query: String,
    /// Ad küçük harf; sıra istekteki sıra.
    pub headers: Vec<(String, String)>,
    pub client_ip: IpAddr,
    pub peer_loopback: bool,
}

impl RequestView {
    /// Aynı adlı başlıklardan İLKİ (Python `headers.get`). `name` küçük harf.
    pub fn header(&self, name: &str) -> Option<&str> {
        self.headers
            .iter()
            .find(|(k, _)| k == name)
            .map(|(_, v)| v.as_str())
    }

    /// Yinelenen çerezde SONUNCU (Python `_request_view` sözlüğü; çıkış/parola da aynı kuralı kullanır).
    pub fn cookie(&self, name: &str) -> Option<&str> {
        self.header("cookie")?
            .split(';')
            .map(|p| {
                let p = crate::py_strip(p);
                p.split_once('=').unwrap_or((p, ""))
            })
            .rfind(|(k, _)| *k == name)
            .map(|(_, v)| v)
    }
}

pub type BoxFut<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

/// Karar arka ucunun hatası; metin tanıya yazılır, içine sır KONMAZ.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AuthError {
    Unavailable(String),
    Internal(String),
}

pub trait Authenticator: Send + Sync {
    /// `Ok(None)` = kimlik yok (401). `Err` = arka uç hatası (401). Asla varsayılan kimlik uydurmaz.
    fn authenticate<'a>(
        &'a self,
        req: &'a RequestView,
    ) -> BoxFut<'a, Result<Option<Principal>, AuthError>>;
}

pub trait Authorizer: Send + Sync {
    /// `Ok(false)` ya da `Err` = 403.
    fn authorize<'a>(
        &'a self,
        p: &'a Principal,
        action: &'a str,
        res: &'a Resource,
    ) -> BoxFut<'a, Result<bool, AuthError>>;
}

pub trait AuditSink: Send + Sync {
    /// Engellemez ve kararı değiştirmez; hatayı kendisi tanıya yazar.
    fn record(&self, p: &Principal, action: &str, res: &Resource, status: u16);
}

/// Ön ek -> eylem. SIRA ÖNEMLİ (ilk eşleşen kazanır). Python `_ACTION_TABLE` ile birebir.
pub const ACTION_TABLE: &[(&str, &str)] = &[
    ("/api/auth/", "auth.login"),
    ("/api/ws-ticket", "status.read"),
    ("/api/status", "status.read"),
    ("/api/ui/", "status.read"),
    ("/api/usage", "usage.read"),
    ("/api/context", "usage.read"),
    ("/ws/term", "term.read"),
    ("/ws/desktop", "desktop.use"),
    ("/ws", "status.read"),
    ("/api/term/open-window", "admin.desktop"),
    ("/api/term/mirror-window", "admin.desktop"),
    ("/api/term/input", "term.write"),
    ("/api/term/key", "term.write"),
    ("/api/term/raw", "term.write"),
    ("/api/term/resize", "term.write"),
    ("/api/term/set-mode", "term.write"),
    ("/api/term/", "term.read"),
    ("/api/files/upload", "files.write"),
    ("/api/files/write", "files.write"),
    ("/api/files/delete", "files.write"),
    ("/api/files/rename", "files.write"),
    ("/api/files/mkdir", "files.write"),
    ("/api/files/", "files.read"),
    ("/api/orch/", "orch.run"),
    ("/api/ucli/ask", "session.chat"),
    ("/api/_internal/", "admin.config"),
    ("/api/chat-backup", "admin.config"),
    ("/api/ucli/metrics", "status.read"),
    ("/api/uzakgoz/freshness", "status.read"),
    ("/api/ucli/checks-mode", "session.control"),
    ("/api/ucli/checks", "admin.config"),
    ("/api/ucli/approvals", "session.chat"),
    ("/api/agents/", "agents.use"),
    ("/api/register", "session.create"),
    ("/api/adopt", "fleet.admin"),
    ("/api/instances/", "fleet.admin"),
    ("/api/snapshot", "fleet.admin"),
    ("/api/start", "session.control"),
    ("/api/stop", "session.control"),
    ("/api/retire", "session.control"),
    ("/api/reactivate", "session.control"),
    ("/api/close", "session.control"),
    ("/api/handover", "session.control"),
    ("/api/compact", "session.control"),
    ("/api/new-chat", "session.control"),
    ("/api/edit", "session.control"),
    ("/api/session/activate", "session.control"),
    ("/api/live-model", "session.control"),
    ("/api/live-effort", "session.control"),
    ("/api/hosts", "admin.hosts"),
    ("/api/steward/", "steward.use"),
    ("/api/layout", "admin.desktop"),
    ("/api/vscode/", "admin.desktop"),
    ("/api/desktop/", "desktop.use"),
    ("/api/audio/", "desktop.use"),
    ("/api/settings", "admin.config"),
    ("/api/cli/", "admin.config"),
    ("/api/diag/", "admin.config"),
    ("/api/io/", "admin.config"),
    ("/api/labels", "admin.config"),
    ("/api/periodic", "admin.config"),
    ("/api/session/facts", "status.read"),
    ("/api/session/graphical", "admin.desktop"),
    ("/api/ucli/", "admin.config"),
    ("/desktop/", "desktop.use"),
    ("/api/session/lock", "admin.config"),
    ("/api/session/unlock", "admin.config"),
    ("/v1/", "session.chat"),
    ("/q/", "steward.answer"),
    ("/", "status.read"),
];

/// Yol -> eylem adı. Eklenti uçlarının eylem kaydı (`register_action`) henüz taşınmadı: o yollar `UNMAPPED` kalır.
pub fn action_for(method: &str, path: &str) -> &'static str {
    if path == "/" {
        return "status.read";
    }
    if path == "/api/ucli/approvals" && method.eq_ignore_ascii_case("GET") {
        return "status.read";
    }
    ACTION_TABLE
        .iter()
        .find(|(prefix, _)| {
            *prefix != "/" && (path == prefix.trim_end_matches('/') || path.starts_with(prefix))
        })
        .map_or(UNMAPPED, |(_, action)| action)
}
