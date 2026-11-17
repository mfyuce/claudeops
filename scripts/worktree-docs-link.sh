#!/bin/bash
# Çalışma notları (TODO.md, TOBEDECIDED.md, DONE.md) worktree'de ANA checkout'taki dosyaya SYMLINK olur (sahip kararı 17 Kas:
# ayrı kopya YOK, -prv commit'i yalnız ana checkout'tan). Kullanım: worktree-docs-link.sh [worktree-dizini ...] (boşsa cwd).
# Idempotent. Gerçek dosya varsa ezmeden önce yedeklenir; TODO.md'nin açık `- [ ]` satırları ana TODO'nun sonuna eklenir.
# `--install-hook`: ana checkout'un hooks/post-checkout'una kurar (git worktree add -> otomatik).
set -u
if [ "${1:-}" = "--install-hook" ]; then
  common=$(git rev-parse --git-common-dir) || exit 1
  main=$(cd "$common/.." && pwd)
  hook="$common/hooks/post-checkout"
  if [ -e "$hook" ] && ! grep -q worktree-docs-link "$hook"; then echo "başka bir post-checkout var, dokunulmadı: $hook" >&2; exit 1; fi
  printf '#!/bin/bash\n# worktree-docs-link: yeni worktree açılınca notları ana checkout symlink yap\n[ "$1" = "0000000000000000000000000000000000000000" ] && "%s/scripts/worktree-docs-link.sh" "$PWD" >/dev/null 2>&1\nexit 0\n' "$main" > "$hook"
  chmod +x "$hook"; echo "kuruldu: $hook"; exit 0
fi
targets=("$@"); [ ${#targets[@]} -eq 0 ] && targets=("$PWD")
for wt in "${targets[@]}"; do
  wt=$(cd "$wt" && pwd) || continue
  common=$(cd "$wt" && git rev-parse --git-common-dir 2>/dev/null) || continue
  main=$(cd "$wt" && cd "$common/.." && pwd)
  [ "$wt" = "$main" ] && { echo "ana checkout, atlandı: $wt"; continue; }
  bk="$HOME/.claude/claudeops/backups/worktree-docs-$(date +%Y%m%d)"
  for f in TODO.md TOBEDECIDED.md DONE.md; do
    dst="$wt/$f"
    if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$main/$f" ]; then echo "tamam: $dst"; continue; fi
    if [ -e "$dst" ] || [ -L "$dst" ]; then
      mkdir -p "$bk"; cp -P "$dst" "$bk/$(basename "$wt")-$f" 2>/dev/null
      if [ -f "$dst" ] && [ ! -L "$dst" ] && [ "$f" = "TODO.md" ]; then
        open=$(grep -E '^\s*[-*]\s*\[ \]' "$dst")
        if [ -n "$open" ]; then
          { printf '\n## Worktree TODO ile taşınan açık maddeler (%s, %s)\n' "$(basename "$wt")" "$(date +%F)"; printf '%s\n' "$open"; } >> "$main/TODO.md"
          echo "açık maddeler ana TODO'ya eklendi: $(printf '%s\n' "$open" | wc -l)"
        fi
      fi
      rm -f "$dst"
    fi
    [ -e "$main/$f" ] || touch "$main/$f"
    ln -s "$main/$f" "$dst" && echo "symlink: $dst -> $main/$f"
  done
done
