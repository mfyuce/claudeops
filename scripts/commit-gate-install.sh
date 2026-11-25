#!/usr/bin/env bash
# commit-gate'i derle, <durum dizini>/bin'e kur ve çekirdek + enterprise repolarına commit-msg/pre-push kancalarını yaz.
# Kural: yeni geliştirme Rust; Python büyüten feat commit'i yalnız sahip onaylı 'Python-exception: TBD#<n>' ile geçer.
set -euo pipefail
core="$(cd "$(dirname "$0")/.." && pwd)"
# worktree'den koşulsa da TOBEDECIDED.md ve yan repo ana checkout'a göre bulunur
main="$(cd "$core" && cd "$(git rev-parse --git-common-dir)/.." && pwd)"
state="${CLAUDEOPS_DIR:-$HOME/.claude/claudeops}"
cargo install --quiet --locked --offline --force --no-track --root "$state" --path "$core/rust/crates/commit-gate"
args=(install --tbd "$main/TOBEDECIDED.md" --repo "$main")
ent="${1:-$(dirname "$main")/claudeops-enterprise}"
[ -d "$ent/.git" ] && args+=(--repo "$ent")
exec "$state/bin/commit-gate" "${args[@]}"
