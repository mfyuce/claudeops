//! `py/claudeops/tmux_backend.py`nin Rust karşılığı: ayrı tmux soketi (`-L cops`) üzerinden oturum listesi,
//! capture, tuş gönderme, boyut ve pane bilgisi.
//!
//! Değişmez kurallar:
//! * Hedef HER ZAMAN `=ad:` biçiminde ([`exact_target`]): tmux'un ön ek eşleşmesi yanlış oturumu döndürür.
//! * `;` ile biten argv elemanı tmux'ta komut ayıracıdır: yazılan metin kaçırılır.
//! * Pane copy-mode'a SOKULMAZ: geçmiş yalnız `capture-pane -S/-E` ile okunur.
//! * Tuş gönderen her çağrı [`MaskGuard`] ister (parola istemine otomatik enjeksiyon engeli).
//! * Metin eşleştirmeden önce ANSI temizlenir ([`strip_ansi`], [`Tmux::capture_plain`]).
//!
//! Davranış Python ile eştir; Python'dan taşınan hata şüpheleri `docs/rs-tmux.md`de işaretlidir. Biçim farkı: hatalar
//! `None`/`False` yerine [`TmuxError`] döner. Hiçbir çağrı panik atmaz ve her tmux süreci zaman aşımıyla sınırlıdır;
//! zaman aşımında süreç öldürülüp toplanır, iş parçacığı ya da fd geride kalmaz. Çağırana dönmeyen hata yoktur:
//! temizlik adımının hatası bile [`swallowed_count`] sayacına ve günlüğe ([`set_swallow_hook`]) gider.
//! Çağrılar bloklayıcıdır (async bağlamda `spawn_blocking`).

mod diag;
mod error;
mod keys;
mod mask;
mod proc;
mod query;
mod runner;
mod shell;
mod text;

pub use diag::{set_swallow_hook, swallowed_count, SwallowHook, Swallowed};
pub use error::TmuxError;
pub use keys::{
    send_text_timeout, MaskGuard, ALLOWED_SPECIAL_KEYS, RAW_CHUNK_CHARS, RESIZE_COLS, RESIZE_ROWS,
};
pub use mask::tty_is_masked;
pub use proc::{pid_childless, CtxPusher, OuterBash, ANCESTOR_WALK_LIMIT};
pub use query::{PaneInfo, PaneSize, SessionInfo, Snapshot, HISTORY_LIMIT, SNAPSHOT_FORMAT};
pub use runner::{
    addressable, escape_arg, exact_target, format_literal, Tmux, DEFAULT_TIMEOUT, MAX_TIMEOUT,
    REAP_GRACE, TMUX_SOCKET,
};
pub use shell::{shell_quote, tmux_available, tmux_conf_path, GHOST_MIN_AGE_SECONDS, GHOST_SHELLS};
pub use text::{
    ctx_label, dim_fg, input_box, patterns, segment_typed, strip_ansi, typed_input_in_box,
    InputBox, BOX_RULE_CHAR, PROMPT,
};
