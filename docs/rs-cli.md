# rs/cli (İz T6: Rust `cops` CLI)

**Durum (26 Kas 2026 21:30): YARIM, BİRLEŞTİRMEYE HAZIR DEĞİL.** İlk taslak Opus alt ajanıyla yazıldı; devir istendiği için ajan
iş bitmeden durduruldu ve son raporunu vermedi. Ana oturum yaptıkları: tek clippy hatası + `cargo fmt`, testler yeniden koşuldu,
yalnız komut çalıştırma/ağ/mutlak yol taraması ile `systemctl.rs`, `main.rs`, test ortamı okundu. Kodun satır satır gözden
geçirmesi YAPILMADI. Canlı birim dosyaları ve `front.secret` değişmemiş (21 Kas tarihli).

## Doğrulama (26 Kas)

`cargo test -p cops-cli` 67 geçti 0 kaldı; `cargo clippy -p cops-cli --all-targets -- -D warnings` ve `cargo fmt --check` temiz.
Workspace'in tamamı ve Python testleri bu dalda koşulmadı (Python dosyası değişmedi).

## Crate (`rust/crates/cops-cli`, ikili `cops-rs`)

| dosya | içerik |
|---|---|
| `src/lib.rs` | yönlendirme: `front`, `self` Rust; gerisi Python'a |
| `src/delegate.rs` | Python CLI'ı bulma (`COPS_PY`, ikilinin ataları, `<durum dizini>/bin/cops-py`), özyineleme koruması, `exec`, çıkış 125 |
| `src/argp.rs`, `src/pyenv.rs` | argparse biçimleri (taklit edilmeyen devredilir), Python yol kuralları |
| `src/front/` | `front status|on|off [--apply]`, TBD#371/4 (a) adres ayrıştırma, (b) yabancı porta vekillik, (c) geri alma; gizli üretimi |
| `src/selfcmd.rs` | `self` |
| `src/list.rs` | `list` yalnız arayüz; komut Python'a devredilir |

## Açık işler (sırayla)

1. [ ] İşlevce eşlik tablosu: `front_cmd.py`, `front.py` (kullanılan kısım), `self` karşılığı ve ilgili Python testlerinin ast
   listesiyle karşılaştırmalı tablo (`docs/rust-sprint-plan.md` "Sahip eki").
2. [ ] Ders listesi karşılığı (`docs/rust-lessons-from-python.md` bölüm 3 + ilgili H maddeleri).
3. [ ] Bilinçli sapmalar ve "Python hatası?" bölümü (ajan raporu alınamadı; koddan çıkarılacak).
4. [ ] Kod gözden geçirmesi: özellikle `front/mod.rs` geri alma yolları, `front/net.rs` port sahibi tespiti (cgroup),
   `front/secret.rs` Python ile aynı kilit sözleşmesi, Python bulma sırasının kurulumla uyumu (`bin/cops-py` kimin kuracağı).
5. [ ] `tests/py_argparse_oracle.py`: ajanın durdurulduğu anda bu dosyada düzenleme yapıyordu; son halini niyetle karşılaştır.
6. [ ] `rust/Cargo.lock` commit'siz (izin verilen yollar dışında; `cargo build` yeniden üretir).
