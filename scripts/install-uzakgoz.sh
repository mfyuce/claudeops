#!/usr/bin/env bash
# claudeops -- uzakgoz'un (ayrı repo, "uzakgoz artık claudeops'un" 21 Kas) release build'ini claudeops'un KENDİ kopyasına teslim eder:
# <canlı checkout>/bin/uzakgoz (+ bin/uzakgoz.info + bin/uzakgoz.commit). `remote_desktop.start()` LOCAL_BIN varsa derlemeyi HİÇ denemez,
# bu yüzden teslim bilerek yapılır (bin/ucli ile aynı model, scripts/install-ucli.sh).
#
# Kullanım: scripts/install-uzakgoz.sh [--build] [--force]
#   --build  önce uzakgoz'da `nice -n 19 ionice -c3 cargo build --release --locked` (ağır; yük yüksekken bile ölçülü)
#   --force  kaynak uzakgoz kaynaklarından ESKİ görünse de kopyala
# Ortam: UZAKGOZ_DIR (varsayılan ~/work/projects/tmp/uzakgoz), CARGO_TARGET_DIR (varsayılan ~/.cargo-target),
#        CLAUDEOPS_UZAKGOZ_DEST (hedef dosya; varsayılan <repo>/bin/uzakgoz, canlı checkout'tan çalıştırılınca doğru olur)
# Özen: (1) kaynak ikili çalıştırılabilir olmalı; (2) kaynaklardan eskiyse reddedilir (--build/--force); (3) eski ikili `.prev`e alınır,
# kopya geçici dosya + `mv` ile yerine konur (çalışan süreç eski inode ile sürer); (4) derlenen commit `uzakgoz.commit` dosyasında
# (status/cops check "N commit geride" uyarısı bunu okur). İkili git'e GİRMEZ (.gitignore: /bin/uzakgoz*).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_ROOT="${UZAKGOZ_DIR:-$HOME/work/projects/tmp/uzakgoz}"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$HOME/.cargo-target}"
DEST="${CLAUDEOPS_UZAKGOZ_DEST:-$REPO/bin/uzakgoz}"
build=0; force=0
for a in "$@"; do
  case "$a" in
    --build) build=1 ;; --force) force=1 ;;
    -h|--help) sed -n 2,13p "$0"; exit 0 ;;
    *) echo "bilinmeyen argüman: $a" >&2; exit 2 ;;
  esac
done
[ -f "$SRC_ROOT/Cargo.toml" ] || { echo "uzakgoz kaynağı yok: $SRC_ROOT" >&2; exit 1; }
NAME=$(sed -n 's/^name = "\(.*\)"/\1/p' "$SRC_ROOT/Cargo.toml" | head -1)
SRC="$CARGO_TARGET_DIR/release/$NAME"
if [ $build = 1 ]; then
  (cd "$SRC_ROOT" && nice -n 19 ionice -c3 cargo build --release --locked)
fi
[ -x "$SRC" ] || { echo "ikili yok: $SRC (--build ile derle)" >&2; exit 1; }
if [ $force = 0 ] && [ -n "$(find "$SRC_ROOT/src" "$SRC_ROOT/web" "$SRC_ROOT/Cargo.toml" "$SRC_ROOT/Cargo.lock" -newer "$SRC" -print -quit 2>/dev/null)" ]; then
  echo "ikili kaynaklardan eski; --build ile derle (ya da --force)" >&2; exit 1
fi
"$SRC" --help >/dev/null 2>&1 || "$SRC" --version >/dev/null 2>&1 || echo "uyarı: ikili --help/--version ile denenemedi" >&2
mkdir -p "$(dirname "$DEST")"
[ -f "$DEST" ] && cp -p "$DEST" "$DEST.prev"
tmp="$(dirname "$DEST")/.uzakgoz.$$"
cp "$SRC" "$tmp" && chmod 755 "$tmp" && mv "$tmp" "$DEST"
COMMIT="$(git -C "$SRC_ROOT" rev-parse --short HEAD)"
printf 'delivered_at=%s\nsource=%s\nsource_git=%s\n' "$(date '+%F %T %z')" "$SRC" "$COMMIT" > "$DEST.info"
printf '%s\n' "$COMMIT" > "$DEST.commit"
echo "teslim edildi -> $DEST (uzakgoz $COMMIT)"
