"""Sohbet kayıt yerleri listesi (TEK KAYNAK, docs/chat-ingest-plan.md §2.1/D1). Yedek betiği (`chat_mirror.sh`) bu listeden ÜRETİLİR;
yeni bir yer eklemek tek satırdır. Bugünkü elle yazılmış betik yalnız kullanıcı CLI'larını alıyordu; reviewer kökü (agy_home*,
reviews, claude_cfg), copilot `session-store.db`/`session-state` ve `ucli_usage` hiçbir yedeğe girmiyordu.

İsteğe bağlı üzerine yazma: `<CLAUDEOPS_DIR>/chat_sources.toml` (`[[source]]` tabloları; alanlar `Source` ile aynı). Dosya yoksa/bozuksa
yerleşik liste kullanılır. KİMLİK/ANAHTAR dosyaları her yerde hariçtir (`SECRET_EXCLUDES`); önbellekler (`.rustup`, `.cargo`, `.cache`)
yedeğe girmez (ölçüm 22 Kas: agy_home* toplamının büyük kısmı bunlar; gerçek sohbet verisi 2,6 GB).
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .paths import CLAUDEOPS_DIR

HOME = os.path.expanduser("~")
REVIEWER_ROOT = os.path.join(CLAUDEOPS_DIR, "steward", "stewards", "reviewer")
TOML_PATH = os.path.join(CLAUDEOPS_DIR, "chat_sources.toml")

# Hiçbir kaynakta yedeğe girmez: kimlik, anahtar, izin ayarı, çalışma önbelleği.
# Desenler dar tutulur: genel "*oauth*" adında oauth geçen sohbet/hafıza dosyalarını da yedekten düşürürdü.
SECRET_EXCLUDES = ("auth.json", "auth.lock", "google_accounts.json", "oauth_creds.json", "*oauth-token*", "installation_id", "*.credentials*",
                   "settings.json")
CACHE_EXCLUDES = (".rustup", ".cargo", ".cache", "tmp", "bin", "node_repl", "packages")


@dataclass
class Source:
    id: str
    cli: str                    # claude | codex | agy | copilot | ucli | claude_p | evren | anthropic ...
    role: str                   # main | reviewer
    path: str                   # kaynak kök (glob DEĞİL; `glob_parent` ile çoğul)
    dest: str                   # ayna altındaki hedef dizin
    includes: List[str] = field(default_factory=list)    # rsync --include (boş = hepsi)
    excludes: List[str] = field(default_factory=list)
    backup: bool = True
    glob: str = ""              # path altında birden çok kök (örn. agy_home*): kabuk glob'u, her eşleşme `dest/<ad>` olur


def default_sources() -> List[Source]:
    """Yerleşik liste: bugünkü betiğin (chat_mirror.sh) kapsadıkları + D1 ile eklenenler."""
    cache = list(CACHE_EXCLUDES)
    sec = list(SECRET_EXCLUDES)
    return [
        Source("claude", "claude", "main", f"{HOME}/.claude/projects", "claude-projects", excludes=[]),
        Source("codex", "codex", "main", f"{HOME}/.codex", "codex",
               excludes=["cache", "tmp", "node_repl", "packages", "vendor_imports"]),
        Source("agy", "agy", "main", f"{HOME}/.gemini", "gemini", excludes=["tmp"]),
        Source("copilot", "copilot", "main", f"{HOME}/.copilot", "copilot",
               includes=["data.db*", "command-history-state.json", "session-store.db*", "session-state/", "session-state/*/", "session-state/*/events.jsonl"],
               excludes=["*"]),
        # ── D1 (22 Kas, sahip onayı): reviewer kayıtları ──
        Source("reviewer-agy", "agy", "reviewer", REVIEWER_ROOT, "reviewer/agy", glob="agy_home*",
               includes=[".gemini/", ".gemini/antigravity-cli/", ".gemini/antigravity-cli/conversations/", ".gemini/antigravity-cli/conversations/**",
                         ".gemini/antigravity-cli/conversation_summaries.db*"],
               excludes=["*"]),
        Source("reviewer-reviews", "reviews", "reviewer", f"{REVIEWER_ROOT}/reviews", "reviewer/reviews",
               excludes=["*.rc"] + sec),
        Source("reviewer-claude-p", "claude_p", "reviewer", f"{REVIEWER_ROOT}/claude_cfg/projects", "reviewer/claude_cfg-projects"),
        Source("ucli-usage", "ucli", "main", f"{HOME}/.claude/claudeops/ucli_usage", "ucli-usage"),
        # `--state-dir` açıkken ucli sohbetleri proje kökünde değil burada (ikinci örneğinki yedeğe `periodic`ten girer)
        Source("ucli-state", "ucli", "main", f"{HOME}/.claude/claudeops/ucli-state", "ucli-state"),
    ]


def load_sources(toml_path: Optional[str] = None) -> List[Source]:
    """Yerleşik liste; `chat_sources.toml` varsa ve geçerliyse O (tamamen) kullanılır."""
    p = toml_path or TOML_PATH
    try:
        import tomllib
        with open(p, "rb") as f:
            data = tomllib.load(f)
        rows = data.get("source") or []
        out = [Source(**{k: v for k, v in r.items() if k in Source.__dataclass_fields__}) for r in rows if isinstance(r, dict) and r.get("id")]
        return out or default_sources()
    except (OSError, ValueError, TypeError, ImportError):     # tomllib yok (Python < 3.11) ya da dosya yok/bozuk: yerleşik liste
        return default_sources()


def _rsync_line(s: Source) -> str:
    """Tek kaynağın rsync komutu. `glob` doluysa her eşleşme ayrı hedefe (`dest/<ad>`)."""
    opts = ["-a"]
    # kimlik dışlamaları HER kaynağa (toml üzerine yazması dahil) ve include'lardan ÖNCE (rsync: ilk eşleşen kazanır)
    for exc in SECRET_EXCLUDES:
        opts.append("--exclude=" + shlex.quote(exc))
    for inc in s.includes:
        opts.append("--include=" + shlex.quote(inc))
    for exc in (e for e in s.excludes if e not in SECRET_EXCLUDES):
        opts.append("--exclude=" + shlex.quote(exc))
    flags = " ".join(opts)
    if s.glob:
        return (f'for d in {shlex.quote(s.path)}/{s.glob}; do [ -d "$d" ] || continue; n=$(basename "$d"); '
                f'mkdir -p "$DST/{s.dest}/$n"; rsync {flags} "$d"/ "$DST/{s.dest}/$n"/ 2>>"$DST/mirror.log" && log "ok {s.dest}/$n"; done')
    return (f'[ -e {shlex.quote(s.path)} ] && {{ mkdir -p "$DST/{s.dest}"; rsync {flags} {shlex.quote(s.path)}/ "$DST/{s.dest}"/ '
            f'2>>"$DST/mirror.log" && log "ok {s.dest}"; }}')


def mirror_script(sources: Optional[List[Source]] = None) -> str:
    """`chat_mirror.sh` içeriği (rsync --delete YOK: kaynakta silinen dosya yedekte kalır). ucli sohbetleri (`.ucli/chat`) eskisi gibi
    proje kökü taramasıyla alınır."""
    lines = ["#!/bin/bash",
             "# ÜRETİLDİ: claudeops/chat_sources.py (TEK KAYNAK; elle düzenleme). Sohbet ayna yedeği; rsync --delete YOK.",
             "set -u", 'DST=$HOME/.claude/claudeops/backups/chat-mirror', 'mkdir -p "$DST"', "umask 077",
             'log() { echo "$(date \'+%F %T\') $*" >> "$DST/mirror.log"; }',
             'sync() { [ -e "$1" ] || return 0; mkdir -p "$DST/$2"; rsync -a "$1"/ "$DST/$2"/ 2>>"$DST/mirror.log" && log "ok $2"; }',
             'cp -p "$HOME/.claude/history.jsonl" "$DST/claude-history.jsonl" 2>/dev/null']
    for s in (sources if sources is not None else load_sources()):
        if s.backup:
            lines.append(_rsync_line(s))
    lines += ["# ucli sohbetleri proje köklerinde (.ucli/chat); kök başına ayrı klasör",
              'for d in $(find "$HOME/work" -maxdepth 6 -type d -path \'*/.ucli/chat\' 2>/dev/null); do',
              '  name=$(echo "${d%/.ucli/chat}" | sed "s#^$HOME/##; s#/#__#g")', '  sync "$d" "ucli/$name"', "done",
              'log "done $(du -sh "$DST" | cut -f1)"', ""]
    return "\n".join(lines)


def write_mirror_script(path: str, sources: Optional[List[Source]] = None) -> bool:
    """Üretilen betiği yazar (içerik aynıysa dokunmaz). Dönen: yazıldı mı."""
    body = mirror_script(sources)
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == body:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(tmp, 0o755)
    os.replace(tmp, path)
    return True
