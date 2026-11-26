//! Değnekçi (steward) SAF çekirdeği: `py/claudeops/steward.py`'nin G/Ç'siz kısmının birebir Rust karşılığı.
//!
//! Kurallar: dosya/süreç/ağ/saat okuması YOK (saat `now` parametresiyle gelir); davranış Python ile aynıdır
//! (parite: `tests/parity`, eşleme tablosu: `docs/rs-stew.md`). Sabitler ve veri tipleri `parity/gen.py` ile üretilir.

#![cfg_attr(not(test), deny(clippy::unwrap_used, clippy::expect_used, clippy::panic))]

pub mod cards;
#[allow(clippy::expect_used)] // sabit desenler: derleme `generated` + parite testleriyle sınanır
#[rustfmt::skip]
pub mod consts_gen;
pub mod identity;
pub mod inserts;
pub mod logdedup;
pub mod markers;
pub mod notify;
pub mod prompts;
pub mod questions;
pub mod store;
#[rustfmt::skip]
mod types_gen;
#[rustfmt::skip]
mod unicode_gen;
pub mod pyc;
pub mod types;
