#!/usr/bin/env bash
# claudeops -- unified-cli'nin (ucli) bir build'ini claudeops'un KENDİ kopyasına
# teslim eder: <repo>/bin/ucli (+ bin/ucli.info). Kullanıcı kararı, 2026-10-09:
# "claudeops ucli'yi kendi reposunda tutsun, gerektiğinde release'i/debug'ı oraya
# gönderelim".
#
# Kullanım:
#   scripts/install-ucli.sh [release|debug] [--build] [--from DOSYA] [--force]
#     release|debug  hangi profil teslim edilir (varsayılan: release). TEK aktif
#                    kopya vardır: teslim ettiğin profil bin/ucli'yi DEĞİŞTİRİR.
#     --build        önce unified-cli'de `cargo build [--release] --locked` koş.
#     --from DOSYA   kaynak ikili (varsayılan: $UNIFIED_CLI_DIR/target/<profil>/ucli).
#     --force        kaynak, unified-cli kaynaklarından ESKİ görünse de kopyala.
#   Ortam: UNIFIED_CLI_DIR      kaynak proje (varsayılan ~/work/projects/tmp/unified-cli)
#          CLAUDEOPS_UCLI_DEST  hedef dosya (varsayılan <repo>/bin/ucli; testler için)
#
# Neden: claudeops eskiden kardeş projenin target/{debug,release} build'ini doğrudan
# seçiyordu. Bayat bir release spawn anında "unexpected argument" ile ölüyor, sadece
# debug derlenince de yeni özellikler claudeops'a hiç ulaşmıyordu. Şimdi claudeops'un
# kullandığı ikili, biz bilerek teslim edene kadar sabit kalır.
#
# Özen: (1) kaynak `chat --help` ile denenir (yarım/bozuk build'i teslim etme);
# (2) kaynak, unified-cli'nin .rs/Cargo dosyalarından (test dosyaları hariç) ESKİYSE
# reddedilir (--build ya da --force ile aşılır); (3) kopya geçici dosyaya yazılıp
# `mv` ile yerine konur: çalışan ucli oturumları eski inode'la sürer ("Text file busy"
# yok), YENİ açılan oturumlar yeni ikiliyi kullanır; (4) hangi build olduğu
# bin/ucli.info'da. İkili git'e GİRMEZ (.gitignore: /bin/ucli*).
#
# Uzak host'a teslim (federasyon): aynı dosyayı host'taki <repo>/bin/ucli'ye
# `scp` + `mv` ile koy (aynı mimari/glibc şartıyla); `git pull` ikiliyi taşımaz.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_ROOT="${UNIFIED_CLI_DIR:-$HOME/work/projects/tmp/unified-cli}"
DEST="${CLAUDEOPS_UCLI_DEST:-$REPO/bin/ucli}"

profile="release"
build=0
force=0
from=""

usage() {
    echo "kullanım: scripts/install-ucli.sh [release|debug] [--build] [--from DOSYA] [--force]" >&2
}

while [ $# -gt 0 ]; do
    case "$1" in
        release|debug) profile="$1" ;;
        --build) build=1 ;;
        --force) force=1 ;;
        --from)
            if [ $# -lt 2 ] || [ -z "$2" ]; then
                echo "--from bir dosya yolu ister" >&2
                exit 2
            fi
            from="$2"
            shift
            ;;
        -h|--help) usage; exit 0 ;;
        *) echo "bilinmeyen argüman: $1" >&2; usage; exit 2 ;;
    esac
    shift
done

cargo_flags=(--locked)
if [ "$profile" = "release" ]; then
    cargo_flags=(--release --locked)
fi

if [ "$build" -eq 1 ]; then
    echo "==> cargo build ${cargo_flags[*]}  ($SRC_ROOT)"
    (cd "$SRC_ROOT" && cargo build "${cargo_flags[@]}")
fi

SRC="${from:-$SRC_ROOT/target/$profile/ucli}"
if [ ! -f "$SRC" ] || [ ! -x "$SRC" ]; then
    echo "kaynak ikili yok ya da çalıştırılabilir değil: $SRC" >&2
    echo "önce derle: (cd $SRC_ROOT && cargo build ${cargo_flags[*]})  ya da --build ver" >&2
    exit 1
fi

if ! "$SRC" chat --help >/dev/null 2>&1; then
    echo "kaynak ikili \`chat --help\` denemesini geçemedi (bozuk/yarım build?): $SRC" >&2
    exit 1
fi

# Bayatlık: --build cargo'ya sordu (otorite o), --from başka bir yerden geliyor,
# --force bilerek eskiyi istiyor. Test dosyaları ikiliyi değiştirmediği için sayılmaz.
if [ "$build" -eq 0 ] && [ "$force" -eq 0 ] && [ -z "$from" ] && [ -d "$SRC_ROOT/crates" ]; then
    newer="$(find "$SRC_ROOT/crates" "$SRC_ROOT/Cargo.toml" "$SRC_ROOT/Cargo.lock" -type f \
        \( -name '*.rs' -o -name 'Cargo.toml' -o -name 'Cargo.lock' \) \
        -not -name 'tests.rs' -not -path '*/tests/*' -not -path '*/target/*' \
        -newer "$SRC" -print -quit 2>/dev/null || true)"
    if [ -n "$newer" ]; then
        echo "kaynak ikili BAYAT: $newer ondan daha yeni ($SRC)" >&2
        echo "önce derle (--build bunu yapar); eskisini bilerek teslim edeceksen --force ver" >&2
        exit 1
    fi
fi

dest_dir="$(dirname "$DEST")"
mkdir -p "$dest_dir"
tmp=""
info_tmp=""
trap 'rm -f "$tmp" "$info_tmp"' EXIT

# Geçici dosya + mv: yerinde üzerine yazmak çalışan bir ikilide "Text file busy" verir.
tmp="$(mktemp "$dest_dir/.ucli.XXXXXX")"
cp "$SRC" "$tmp"
chmod 755 "$tmp"
mv -f "$tmp" "$DEST"
tmp=""

sha="$(sha256sum "$DEST" | cut -d' ' -f1)"
size="$(stat -c %s "$DEST")"
src_mtime="$(date -d "@$(stat -c %Y "$SRC")" '+%Y-%m-%d %H:%M:%S %z')"
git_rev="-"
git_dirty="-"
if [ -z "$from" ] && git -C "$SRC_ROOT" rev-parse --short HEAD >/dev/null 2>&1; then
    git_rev="$(git -C "$SRC_ROOT" rev-parse --short HEAD)"
    if [ -n "$(git -C "$SRC_ROOT" status --porcelain -- crates Cargo.toml Cargo.lock 2>/dev/null)" ]; then
        git_dirty="yes"
    else
        git_dirty="no"
    fi
fi

info_tmp="$(mktemp "$dest_dir/.ucli.info.XXXXXX")"
{
    echo "profile=$profile"
    echo "delivered_at=$(date '+%Y-%m-%d %H:%M:%S %z')"
    echo "source=$SRC"
    echo "source_mtime=$src_mtime"
    echo "source_git=$git_rev"
    echo "source_tree_dirty=$git_dirty"
    echo "size_bytes=$size"
    echo "sha256=$sha"
} > "$info_tmp"
chmod 644 "$info_tmp"
mv -f "$info_tmp" "$DEST.info"
info_tmp=""

echo "==> teslim edildi: $DEST"
echo "    profil=$profile  boyut=${size} bayt  sha256=${sha:0:12}  kaynak git=$git_rev (kirli=$git_dirty)"
echo "    YENİ açılan claudeops ucli oturumları bunu kullanır; AÇIK oturumlar eski ikiliyle sürer."
