"""`close` — session'ı KALICI kapat: öldür (claude proc + parent terminal) +
models.tsv'de yorum-satırı yap → guard (cron) onu "kapalı" görür, REOPEN ETMEZ.

Mekanizma: guard `read_models()` ile aktif base'leri okur ve `#` ile başlayan
satırları ATLAR (roster.py). Bir base models.tsv'de yorumlanınca active_bases'e
girmez → missing listesine düşmez → guard açmaz. carla/mecdtfl/EMEKLİ de böyle.

`open` (ters işlem) için: models.tsv'de `#`'i elle kaldır + guard açar
(veya `rc <name> --new`).
"""
from __future__ import annotations
import re

import psutil

from ..discovery import find_sessions
from ..kill import kill_session
from ..paths import MODELS_TSV

_BASE_RE = re.compile(r"^([a-z]+)\d*$")


def register(sub):
    p = sub.add_parser("close",
                       help="session'ı KALICI kapat (öldür + guard'a 'açma' = models.tsv yorumla)")
    p.add_argument("names", nargs="+", metavar="NAME",
                   help="base veya tam isim (ör. carla, evolvi56)")
    p.add_argument("--grace", type=float, default=8.0, metavar="SEC",
                   help="SIGKILL öncesi bekleme sn (varsayılan: 8)")
    p.add_argument("--keep-terminal", action="store_true",
                   help="parent terminal'i kapatma, sadece claude proc'u öldür")
    p.add_argument("--dry-run", action="store_true",
                   help="sadece göster, öldürme/yazma yapma")
    p.set_defaults(func=run)


def _base(name: str) -> str:
    m = _BASE_RE.match(name)
    return m.group(1) if m else name


def _first_field(line: str) -> str:
    """TSV satırının ilk alanı (base ismi). Tab yoksa whitespace'e göre."""
    s = line.strip()
    if not s:
        return ""
    return (s.split("\t", 1)[0] if "\t" in s else s.split()[0]).strip()


def comment_out_models(base: str, dry_run: bool) -> str:
    """models.tsv'de aktif `<base>` satırını `#` ile yorumla.

    Returns: 'commented' | 'already' | 'notfound'.
    """
    try:
        lines = open(MODELS_TSV, encoding="utf-8").read().splitlines()
    except OSError:
        return "notfound"

    status = "notfound"
    out = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            # zaten yorumlu — bu base mi?
            if _first_field(stripped[1:]) == base and status == "notfound":
                status = "already"
        elif _first_field(line) == base:
            status = "commented"
            if not dry_run:
                line = f"#{line}\t# CLOSED"
        out.append(line)

    if status == "commented" and not dry_run:
        open(MODELS_TSV, "w", encoding="utf-8").write("\n".join(out) + "\n")
    return status


def _kill_with_parent(pid: int, grace: float, keep_terminal: bool) -> str:
    """claude proc'u öldür; keep_terminal=False ise parent bash/sh'i de
    (create_time + name guard ile pid-reuse'a karşı güvenli)."""
    parent_pid = None
    parent_ct = None
    if not keep_terminal:
        try:
            par = psutil.Process(pid).parent()
            if par is not None and par.name() in ("bash", "sh"):
                parent_pid = par.pid
                parent_ct = par.create_time()
        except psutil.NoSuchProcess:
            pass

    result = kill_session(pid, grace=grace)

    if parent_pid is not None:
        try:
            par = psutil.Process(parent_pid)
            if par.create_time() == parent_ct:
                par.kill()
        except psutil.NoSuchProcess:
            pass
    return result


def run(args) -> int:
    sessions = find_sessions(measure_cpu=False)
    errors = 0
    for name in args.names:
        base = _base(name)
        matched = [s for s in sessions if s.name == name or s.base == base]

        if args.dry_run:
            st = comment_out_models(base, dry_run=True)
            print(f"  [dry-run] {name} (base={base}): {len(matched)} proc öldürülecek; "
                  f"models.tsv → {st}")
            continue

        for s in matched:
            print(f"  {s.name} pid={s.pid} → kapatılıyor "
                  f"({'proc+terminal' if not args.keep_terminal else 'sadece proc'})...",
                  end="", flush=True)
            r = _kill_with_parent(s.pid, args.grace, args.keep_terminal)
            print(f" {r}")
        if not matched:
            print(f"  {name}: çalışan proc yok (yine de models.tsv'de kapatılıyor)")

        st = comment_out_models(base, dry_run=False)
        msg = {
            "commented": "✓ models.tsv'de yorumlandı → guard AÇMAYACAK",
            "already":   "zaten kapalı (models.tsv'de yorumlu)",
            "notfound":  "⚠ models.tsv'de bulunamadı (roster-dışı? guard zaten açmaz)",
        }[st]
        print(f"  {base}: {msg}")
        if st == "notfound" and not matched:
            errors += 1
    return errors
