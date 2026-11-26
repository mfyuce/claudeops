//! Python `datetime(y, m, d).timestamp()` (saf/naive yerel saat): CPython `local_to_seconds` algoritması birebir
//! (`fold=0`: belirsiz saatte ilk geçiş; boşluktaki saatte iki adayın büyüğü). Saat dilimi süreç ortamından (`TZ`,
//! `/etc/localtime`), `localtime_r` ile.

const MAX_FOLD_SECONDS: i64 = 24 * 3600;

fn is_leap(y: i64) -> bool {
    y % 4 == 0 && (y % 100 != 0 || y % 400 == 0)
}

fn days_in_month(y: i64, m: i64) -> i64 {
    match m {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        _ if is_leap(y) => 29,
        _ => 28,
    }
}

/// Önceki günler (0001-01-01 = 1. gün; `ymd_to_ord`).
fn ymd_to_ord(y: i64, m: i64, d: i64) -> i64 {
    let y1 = y - 1;
    let before_year = y1 * 365 + y1 / 4 - y1 / 100 + y1 / 400;
    let before_month: i64 = (1..m).map(|k| days_in_month(y, k)).sum();
    before_year + before_month + d
}

fn utc_to_seconds(y: i64, m: i64, d: i64, hh: i64, mm: i64, ss: i64) -> i64 {
    ((ymd_to_ord(y, m, d) * 24 + hh) * 60 + mm) * 60 + ss
}

fn epoch() -> i64 {
    utc_to_seconds(1970, 1, 1, 0, 0, 0)
}

/// `local(u)`: u (0001 tabanlı saniye) anındaki yerel duvar saati, aynı tabanda.
fn local(u: i64) -> Option<i64> {
    let t = libc::time_t::try_from(u - epoch()).ok()?;
    // SAFETY: sıfırlanmış tm; localtime_r yalnız başarıda dolu döner.
    let mut tm: libc::tm = unsafe { std::mem::zeroed() };
    let r = unsafe { libc::localtime_r(&t, &mut tm) };
    if r.is_null() {
        return None;
    }
    Some(utc_to_seconds(
        i64::from(tm.tm_year) + 1900,
        i64::from(tm.tm_mon) + 1,
        i64::from(tm.tm_mday),
        i64::from(tm.tm_hour),
        i64::from(tm.tm_min),
        i64::from(tm.tm_sec),
    ))
}

/// `datetime(year, month, day).timestamp()`; geçersiz tarih (`ValueError`) ya da dönüşüm hatası `None`.
pub fn naive_local_timestamp(year: i64, month: i64, day: i64) -> Option<f64> {
    if !(1..=9999).contains(&year) || !(1..=12).contains(&month) {
        return None;
    }
    if day < 1 || day > days_in_month(year, month) {
        return None;
    }
    let t = utc_to_seconds(year, month, day, 0, 0, 0);
    let a = local(t)? - t;
    let u1 = t - a;
    let t1 = local(u1)?;
    let b = if t1 == t {
        let u2 = u1 - MAX_FOLD_SECONDS;
        let bb = local(u2)? - u2;
        if a == bb {
            return Some((u1 - epoch()) as f64);
        }
        bb
    } else {
        t1 - u1
    };
    let u2 = t - b;
    let t2 = local(u2)?;
    let u = if t2 == t {
        u2
    } else if t1 == t {
        u1
    } else {
        u1.max(u2) // boşluk (gap), fold=0
    };
    Some((u - epoch()) as f64)
}
