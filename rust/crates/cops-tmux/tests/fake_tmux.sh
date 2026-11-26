#!/bin/sh
# Sahte tmux (argv testleri). Test dizinine SEMBOLİK BAĞ olarak konur; ayarını oradan okur.
#   argv      : her çağrı bir kayıt (argümanlar US, kayıtlar RS ile ayrılır)
#   <alt>.out : alt komutun stdout'u
#   <alt>.rc  : satır başına bir çıkış kodu (n'inci çağrı n'inci satır, sonra son satır)
#   stdin     : load-buffer'a gelen veri
d=$(dirname "$0")
{
    for a in "$@"; do printf '%s\037' "$a"; done
    printf '\036'
} >>"$d/argv"
[ "$1" = "-u" ] && shift
[ "$1" = "-L" ] && shift 2
sub=$1
[ "$sub" = "load-buffer" ] && cat >"$d/stdin"
[ -f "$d/$sub.out" ] && cat "$d/$sub.out"
if [ -f "$d/$sub.rc" ]; then
    echo x >>"$d/$sub.n"
    n=$(wc -l <"$d/$sub.n")
    rc=$(sed -n "${n}p" "$d/$sub.rc")
    [ -n "$rc" ] || rc=$(tail -n 1 "$d/$sub.rc")
    exit "$rc"
fi
exit 0
