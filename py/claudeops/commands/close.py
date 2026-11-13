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
from typing import Optional

from ..atomic_json import atomic_write_text, roster_lock
from ..discovery import find_sessions
from ..instances import DERIVED_NAME_RE, get_instance
from ..kill import kill_session, kill_session_and_parent
from ..paths import MODELS_TSV

from ..session import _NAME_RE as _BASE_RE     # TEK kaynak (review R-1: kopya regex ayrışmıştı, `cli_2`/`cops20260824_1` close'da base'e inmiyordu)


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


def _rewrite_models(transform) -> str:
    """models.tsv oku-değiştir-yaz döngüsü: `roster_lock` altında (panel ile AYNI kilit) (panel/steward eşzamanlı yazımı kaybolmasın) ve atomik
    yazım (yarım dosya yok). `transform(lines) -> (status, new_lines|None)`; new_lines None ise dosyaya dokunulmaz."""
    with roster_lock(MODELS_TSV):
        try:
            with open(MODELS_TSV, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            return "notfound"
        status, out = transform(lines)
        if out is not None:
            atomic_write_text(MODELS_TSV, "\n".join(out) + "\n")
            from .. import statedocs
            statedocs.shadow_tsv(MODELS_TSV, force=True)
        return status


def comment_out_models(base: str, dry_run: bool) -> str:
    """models.tsv'de aktif `<base>` satırını `#` ile yorumla.

    Returns: 'commented' | 'already' | 'notfound'.
    """
    def tf(lines):
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
        return status, (out if status == "commented" and not dry_run else None)
    return _rewrite_models(tf)


def is_closed_in_models(name: str, path: Optional[str] = None) -> bool:
    """Salt-okunur: `name` (base ya da tam ad) models.tsv'de `close`'un bıraktığı `# CLOSED` satırı olarak duruyor mu
    (aktif satırı yoksa). Dosya okunamazsa False."""
    base = _base(name)
    closed = False
    try:
        with open(path or MODELS_TSV, encoding="utf-8") as f:
            for line in f.read().splitlines():
                s = line.lstrip()
                if s.startswith("#"):
                    if s.rstrip().endswith("# CLOSED") and _first_field(s[1:]) in (base, name):
                        closed = True
                elif _first_field(line) in (base, name):
                    return False
    except OSError:
        return False
    return closed


def uncomment_models(base: str, dry_run: bool = False) -> str:
    """`comment_out_models`'in tersi: `close`'un bıraktığı `#<satır>\t# CLOSED` kaydını geri aç (yalnız CLOSED işaretli).

    Returns: 'restored' | 'active' | 'notfound'."""
    def tf(lines):
        status = "notfound"
        out = []
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith("#"):
                if status != "restored" and stripped.rstrip().endswith("# CLOSED") and _first_field(stripped[1:]) == base:
                    status = "restored"
                    if not dry_run:
                        line = stripped[1:].rstrip()[: -len("# CLOSED")].rstrip("\t ")
            elif _first_field(line) == base and status == "notfound":
                status = "active"
            out.append(line)
        return status, (out if status == "restored" and not dry_run else None)
    return _rewrite_models(tf)


def _kill_with_parent(pid: int, grace: float, keep_terminal: bool, name: Optional[str] = None) -> str:
    """claude proc'u öldür; keep_terminal=False ise parent terminali de.

    `kill.py`'nin `kill_session_and_parent()`'ına delege eder — eskiden burada
    bağımsız bir PID-ancestry kill'i vardı (`psutil` ile parent'ı bulup köre
    kılıç `.kill()`), `is_tmux_backed` kontrolü YOKTU. tmux-backed session'larda
    pane'in parent'ı paylaşılan tmux SERVER'ı olabilir — o zaman bu, TEK bir
    session'ı kapatmaya çalışırken TÜM tmux-backed filoyu öldürüyordu (CLAUDE.md
    kural-#1 ihlali, TODO.md'nin "MİMARİ İHLAL" maddesi). `kill_session_and_parent`
    zaten bu ayrımı yapıyor (tmux-backed ise ad-bazlı `tmux kill-session`,
    değilse eski PID-ancestry yolu)."""
    if keep_terminal:
        return kill_session(pid, grace=grace)
    return kill_session_and_parent(pid, grace=grace, name=name)


def _models_names() -> set:
    try:
        lines = open(MODELS_TSV, encoding="utf-8").read().splitlines()
    except OSError:
        return set()
    return {_first_field(line.lstrip()[1:] if line.lstrip().startswith("#") else line) for line in lines}


def run(args) -> int:
    sessions = find_sessions(measure_cpu=False)
    models_names = _models_names()
    errors = 0
    for name in args.names:
        is_instance = name not in models_names and (
            get_instance(name) is not None or bool(DERIVED_NAME_RE.match(name)))
        known = is_instance or name in models_names
        # models.tsv hedefi: tam isim; base'e (hc58→hc) sadece bilinmeyen eski tarz isimde düş.
        # Instance'ın kapalı hâli yok — hiçbir zaman blueprint satırını kapatmaz.
        base = None if is_instance else (name if name in models_names else _base(name))
        # 2026-09-14 KRİTİK FIX: `s.name == name or s.base == base` base
        # eşleşmesi TEK BAŞINA aynı base'e indirgenen BAMBAŞKA canlı bir
        # session'ı da (ör. tarih+çakışma suffix'li bir YENİ session) yakalayıp
        # öldürüyordu (canlı olay: "cops" kapatılırken "cops20260914_1" de
        # gitti — web.py'nin `_find_running`'inin AYNI köklü bug'ı, bkz.
        # `_find_running_for_action`). Önce tam-isim denenir; bilinen bir satır
        # ya da instance ise base'e HİÇ düşülmez (çalışmayan `cops20260918`
        # kapatılırken canlı `cops` blueprint'i öldürülmesin); bilinmeyen eski
        # tarz isimde base'e düşülür AMA birden fazla canlı proc AYNI base'e
        # düşüyorsa (belirsizlik) HİÇBİRİ öldürülmez, kullanıcıdan tam isim istenir.
        exact = [s for s in sessions if s.name == name]
        if exact or known:
            matched = exact
        else:
            base_matches = [s for s in sessions if s.base == base]
            if len(base_matches) > 1:
                names = ", ".join(s.name for s in base_matches)
                print(f"  {name}: birden fazla çalışan session bu base'e ({base}) indirgeniyor "
                      f"({names}) — hangisi hedeflenecek belirsiz, tam isim kullanın, ATLANDI")
                errors += 1
                continue
            matched = base_matches

        if args.dry_run:
            st = comment_out_models(base, dry_run=True) if base else "instance (dokunulmaz)"
            print(f"  [dry-run] {name} (models.tsv hedefi={base or '-'}): {len(matched)} proc öldürülecek; "
                  f"models.tsv → {st}")
            continue

        # Önce models.tsv yorumlanır, SONRA öldürülür: tersi sırada öldürme ile yorumlama arasında guard satırı
        # hâlâ aktif görüp session'ı yeniden açabilirdi.
        st = None if is_instance else comment_out_models(base, dry_run=False)

        for s in matched:
            print(f"  {s.name} pid={s.pid} → kapatılıyor "
                  f"({'proc+terminal' if not args.keep_terminal else 'sadece proc'})...",
                  end="", flush=True)
            r = _kill_with_parent(s.pid, args.grace, args.keep_terminal, name=s.name)
            print(f" {r}")
        if is_instance:
            print(f"  {name}: instance — {'durduruldu' if matched else 'zaten çalışmıyor'}; "
                  f"models.tsv'ye dokunulmadı (instance'ın kapalı hâli yok)")
            continue
        if not matched:
            print(f"  {name}: çalışan proc yok (yine de models.tsv'de kapatılıyor)")

        msg = {
            "commented": "✓ models.tsv'de yorumlandı → guard AÇMAYACAK",
            "already":   "zaten kapalı (models.tsv'de yorumlu)",
            "notfound":  "⚠ models.tsv'de bulunamadı (roster-dışı? guard zaten açmaz)",
        }[st]
        print(f"  {base}: {msg}")
        if st == "notfound" and not matched:
            errors += 1
    return errors
