//! Çağırana dönmeyen (yutulan) hataların sayacı ve günlüğü. Bir hata ancak asıl sonucu değiştirmiyorsa yutulur
//! (ör. asıl hata zaten dönerken temizlik adımının hatası); o zaman bile sessiz kalmaz: sayaç artar ve günlüğe gider.

use std::fmt;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::OnceLock;

/// Yutulan hatanın yeri.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Swallowed {
    /// Başarısız yapıştırmadan sonra tamponu silme (`delete-buffer`) başarısız; asıl hata çağırana döner.
    DeleteBuffer,
    /// tmux sıfırdan farklı kodla çıktı VE girdisini (stdin) sonuna dek almadı; çağırana `Failed` döner.
    StdinWrite,
    /// Zaman aşımında tmux istemci sürecine SIGKILL gönderilemedi.
    KillChild,
    /// Öldürülen süreç [`REAP_GRACE`](crate::REAP_GRACE) içinde toplanamadı; arka plan iş parçacığı bekler (zombi kalmaz).
    ReapChild,
}

impl Swallowed {
    pub const ALL: [Swallowed; 4] = [
        Self::DeleteBuffer,
        Self::StdinWrite,
        Self::KillChild,
        Self::ReapChild,
    ];

    fn index(self) -> usize {
        match self {
            Self::DeleteBuffer => 0,
            Self::StdinWrite => 1,
            Self::KillChild => 2,
            Self::ReapChild => 3,
        }
    }

    /// Günlük için sabit sebep kodu.
    pub fn code(self) -> &'static str {
        match self {
            Self::DeleteBuffer => "delete_buffer_failed",
            Self::StdinWrite => "stdin_write_failed",
            Self::KillChild => "kill_child_failed",
            Self::ReapChild => "reap_child_slow",
        }
    }
}

impl fmt::Display for Swallowed {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}

static COUNTS: [AtomicU64; 4] = [
    AtomicU64::new(0),
    AtomicU64::new(0),
    AtomicU64::new(0),
    AtomicU64::new(0),
];

/// Yutulan hata günlükçüsü: (yer, hata metni). Hata metni tmux'un stderr'i ya da G/Ç hatasıdır; gönderilen metni
/// (argv, stdin) İÇERMEZ.
pub type SwallowHook = fn(Swallowed, &str);

static HOOK: OnceLock<SwallowHook> = OnceLock::new();

/// Süreç başına bir kez günlükçü kurar (ör. copsd'nin kendi günlüğü). Kurulmazsa stderr'e tek satır yazılır.
/// `false` = zaten kurulu, değişmedi.
pub fn set_swallow_hook(hook: SwallowHook) -> bool {
    HOOK.set(hook).is_ok()
}

/// Süreç başından beri bu yerde yutulan hata sayısı.
pub fn swallowed_count(kind: Swallowed) -> u64 {
    COUNTS[kind.index()].load(Ordering::Relaxed)
}

pub(crate) fn swallow(kind: Swallowed, err: &dyn fmt::Display) {
    COUNTS[kind.index()].fetch_add(1, Ordering::Relaxed);
    let text = err.to_string();
    match HOOK.get() {
        Some(hook) => hook(kind, &text),
        None => eprintln!("cops-tmux: yutulan hata {kind}: {text}"),
    }
}
