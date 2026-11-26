//! Yönlendirme kümeleri ve zaman aşımları (Python `web_hosts.py` ile AYNI olmalı; eşitlik testi henüz YOK, docs/rs-hosts.md).

use std::time::Duration;

/// Yerel panelin kendi oturumlarını etiketlediği ad; kayıtlı uzak host adı olamaz.
pub const LOCAL_HOST_NAME: &str = "local";

/// Gövdesinde `host` taşıyan, uzağa vekillenen POST yolları.
pub const HOST_ROUTED_PATHS: &[&str] = &[
    "/api/start",
    "/api/stop",
    "/api/retire",
    "/api/reactivate",
    "/api/close",
    "/api/handover",
    "/api/compact",
    "/api/adopt",
    "/api/new-chat",
    "/api/register",
    "/api/edit",
    "/api/term/input",
    "/api/term/key",
    "/api/term/raw",
    "/api/term/resize",
    "/api/term/open-window",
    "/api/term/set-mode",
    "/api/instances/forget",
    "/api/cli/install",
    "/api/files/delete",
    "/api/files/rename",
    "/api/files/mkdir",
    "/api/files/write",
    "/api/files/validate",
    "/api/context",
    "/api/live-model",
    "/api/live-effort",
    "/api/session/activate",
    "/api/ucli/checks",
    "/api/ucli/checks-mode",
    "/api/usage",
    "/api/settings/byok",
];

/// Gövdesi sır taşıyan yollar: `value` alanı yalnız https ya da loopback adresine gider.
pub const SECRET_BODY_PATHS: &[&str] = &["/api/settings/byok"];

/// Uzağa vekillenen salt okuma GET yolları (query tabanlı, JSON yanıt).
pub const GET_HOST_ROUTED_PATHS: &[&str] = &[
    "/api/term/output",
    "/api/term/history",
    "/api/term/chat",
    "/api/files/list",
    "/api/files/read",
    "/api/instances",
    "/api/cli/status",
    "/api/session/facts",
    "/api/session/graphical",
    "/api/ucli/checks",
    "/api/ucli/checks-mode",
    "/api/ucli/metrics",
    "/api/ucli/metrics/sessions",
    "/api/ucli/compare",
];

/// Ham ikili yanıt (JSON değil).
pub const FILE_DOWNLOAD_PATH: &str = "/api/files/download";
/// Ham ikili istek gövdesi (akıtılır).
pub const FILE_UPLOAD_PATH: &str = "/api/files/upload";
/// Aynı `input_id` ile yeniden denenebilen terminal girdi yolları.
pub const TERM_RETRY_PATHS: &[&str] = &["/api/term/input", "/api/term/raw", "/api/term/key"];

pub fn is_host_routed_post(path: &str) -> bool {
    HOST_ROUTED_PATHS.contains(&path)
}

pub fn is_host_routed_get(path: &str) -> bool {
    GET_HOST_ROUTED_PATHS.contains(&path)
}

/// Zaman aşımları. `status`..`term_attempt` Python sabitleriyle aynı; her biri TEK bir ağ adımının (bağlanma, yanıt başlığı,
/// gövde parçası) sınırıdır (Python soket zaman aşımı gibi), `total_cap` ise damla damla gelen yanıt için mutlak tavandır.
#[derive(Debug, Clone, Copy)]
pub struct Timeouts {
    /// Durum yoklaması.
    pub status: Duration,
    /// Terminal/dosya okuma GET'leri.
    pub term_read: Duration,
    /// Aksiyon vekili ve dosya aktarımı (uzak compact 180 sn sürebilir).
    pub action: Duration,
    /// `extra_urls` aday denemesi.
    pub fallback: Duration,
    /// Yavaş host'larda uzun okuma (yuhem; Python `chat_remote.TO`): çağıran bilerek seçer.
    pub long_read: Duration,
    /// Terminal girdisinde deneme başı sınır.
    pub term_attempt: Duration,
    pub ws_probe: Duration,
    pub grpc_probe: Duration,
    pub ws_open: Duration,
    /// Bir isteğin (tüm adımlar toplamı) mutlak tavanı; çağrının kendi zaman aşımı bundan büyükse o geçerli.
    pub total_cap: Duration,
}

impl Default for Timeouts {
    fn default() -> Self {
        let s = Duration::from_secs;
        Timeouts {
            status: s(8),
            term_read: s(12),
            action: s(200),
            fallback: s(3),
            long_read: s(90),
            term_attempt: s(12),
            ws_probe: s(3),
            grpc_probe: s(3),
            ws_open: s(10),
            total_cap: s(600),
        }
    }
}

pub const TERM_MAX_ATTEMPTS: usize = 3;
pub const POLL_INTERVAL: Duration = Duration::from_secs(3);
/// Poller bu kadar süredir tur bitirmediyse takılı sayılır.
pub const POLLER_STALL: Duration = Duration::from_secs(90);
pub const WATCHDOG_INTERVAL: Duration = Duration::from_secs(15);
pub const PROBE_MIN_GAP: Duration = Duration::from_secs(15);
pub const CONSECUTIVE_FAILURES_BEFORE_ERROR: u32 = 5;
/// Push akışı bu kadar süre hiç çerçeve getirmezse ölü sayılır.
pub const STATUS_PUSH_SILENCE: Duration = Duration::from_secs(45);
pub const CAPABILITY_PROBE_INTERVAL: Duration = Duration::from_secs(60);
pub const TERM_RELAY_IDLE_TTL: Duration = Duration::from_secs(10);
pub const TERM_RELAY_RESTART_MIN_INTERVAL: Duration = Duration::from_secs(2);
pub const TERM_RELAY_SILENCE: Duration = Duration::from_secs(45);
pub const CONSUMER_DEATH_LOG_MIN_INTERVAL: Duration = Duration::from_secs(60);
