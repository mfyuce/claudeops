"""`migrate-instances`: roster.tsv/models.tsv'deki instance satırlarını instances.json'a taşır.

Varsayılan dry-run. `--apply` önce yedek alır; taşınan/atılan satırlar dışındaki her
satır bayt bayt korunur. Yeni kod deploy+restart EDİLDİKTEN SONRA çalıştırılmalı:
eski kod, satırı kalkan canlı bir instance'ı "kayıtsız" gösterir.
"""
from __future__ import annotations
import os
import shutil
import tempfile
import time
from collections import Counter
from typing import Dict, List, Optional, Tuple

from ..discovery import find_sessions
from ..instances import (AUTO_NAME_RE, DERIVED_NAME_RE, DIAG_PREFIX, INSTANCES_JSON,
                         InstancesCorrupt, add_missing, created_at_from_name, infer_blueprint,
                         read_strict)
from ..paths import CLAUDEOPS_DIR, MODELS_TSV, ROSTER_TSV
from ..providers import DEFAULT_CLI, PROVIDERS

Row = Tuple[int, Optional[str], List[str], bool]   # (satır no, ad, geri kalan alanlar, aktif mi)


def register(sub):
    p = sub.add_parser("migrate-instances",
                       help="roster'daki tarihli instance satırlarını instances.json'a taşı (varsayılan dry-run)")
    p.add_argument("--apply", action="store_true", help="gerçekten uygula (önce yedek alır)")
    p.add_argument("--drop", action="append", default=[], metavar="AD",
                   help="bu satırı taşımadan roster/models'tan at (tekrarlanabilir; yedekte kalır)")
    p.add_argument("-v", "--verbose", action="store_true", help="taşınacak her satırı listele")
    p.set_defaults(func=run)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _parse(content: str) -> List[Row]:
    """web.py `_read_tsv_raw` ile AYNI ayrıştırma, ama satır numarasını da tutar."""
    rows: List[Row] = []
    for i, line in enumerate(content.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        active = not stripped.startswith("#")
        bare = stripped if active else stripped[1:]
        parts = bare.strip().split("\t")
        if parts and parts[0]:
            rows.append((i, parts[0], parts[1:], active))
    return rows


def _without_lines(content: str, drop_idx: set) -> str:
    lines = content.splitlines(keepends=True)
    return "".join(line for i, line in enumerate(lines) if i not in drop_idx)


def _atomic_write_text(path: str, content: str) -> None:
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".tsv")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        try:
            os.chmod(tmp, os.stat(path).st_mode & 0o777)
        except FileNotFoundError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _same(a: str, b: str) -> bool:
    return os.path.normpath(a or "") == os.path.normpath(b or "")


def plan(roster_content: str, models_content: str, drop: set) -> dict:
    """Saf fonksiyon: hangi satır taşınır/atılır/kalır + taşınacak kayıtlar. Dosyaya dokunmaz."""
    roster_rows = _parse(roster_content)
    models_rows = _parse(models_content)
    models_by_name: Dict[str, str] = {}
    for _, name, rest, active in models_rows:
        if rest and (active or name not in models_by_name):
            models_by_name[name] = rest[0]

    bp_cwds = {name: (rest[0] if rest else "") for _, name, rest, _ in roster_rows
               if name != "name" and name not in drop and not DERIVED_NAME_RE.match(name)}

    instances: Dict[str, dict] = {}
    rules: Dict[str, str] = {}
    dropped: List[str] = []
    remove_names: set = set()
    kept: List[str] = []
    for _, name, rest, active in roster_rows:
        if name == "name":
            continue
        cwd = rest[0] if rest else ""
        if name in drop:
            dropped.append(name)
            remove_names.add(name)
            continue
        auto = AUTO_NAME_RE.match(name)
        derived = DERIVED_NAME_RE.match(name)
        if not derived:
            kept.append(name)
            continue
        prefix = derived.group(1)
        if prefix == DIAG_PREFIX and DIAG_PREFIX not in bp_cwds:
            bp = None
        else:
            bp = infer_blueprint(name, cwd, bp_cwds)
        if not auto and not (bp and _same(bp_cwds[bp], cwd)):
            kept.append(name)
            continue
        if bp is None:
            rule = "blueprint yok"
        elif bp == prefix and _same(bp_cwds[bp], cwd):
            rule = "önek+cwd" if auto else "el adlı türev"
        elif bp == prefix:
            rule = "önek (cwd farklı)"
        else:
            rule = "sadece cwd"
        if name in instances and not active:
            remove_names.add(name)
            continue
        cli = rest[2] if len(rest) >= 3 and rest[2] in PROVIDERS else DEFAULT_CLI
        instances[name] = {
            "blueprint": bp,
            "cwd": cwd,
            "cli": cli,
            "model": models_by_name.get(name) or (rest[1] if len(rest) >= 2 else ""),
            "permission_mode": "",
            "effort": "",
            "created_at": created_at_from_name(name) or time.time(),
            "last_started_at": None,
            "origin": "migrated",
        }
        rules[name] = rule
        remove_names.add(name)

    roster_drop_idx = {i for i, name, _, _ in roster_rows if name in remove_names}
    models_drop_idx = {i for i, name, _, _ in models_rows if name in remove_names}
    return {
        "instances": instances,
        "rules": rules,
        "dropped": dropped,
        "kept": kept,
        "roster_rows": len([r for r in roster_rows if r[1] != "name"]),
        "new_roster": _without_lines(roster_content, roster_drop_idx),
        "new_models": _without_lines(models_content, models_drop_idx),
        "roster_lines_removed": len(roster_drop_idx),
        "models_lines_removed": len(models_drop_idx),
    }


def run(args) -> int:
    drop = set(args.drop)
    try:
        read_strict()
    except InstancesCorrupt as e:
        print(f"HATA: {e} — önce bu dosyayı düzelt/kenara al, migrasyon üstüne yazmaz.")
        return 1

    roster_content = _read(ROSTER_TSV)
    models_content = _read(MODELS_TSV)
    p = plan(roster_content, models_content, drop)
    live = {s.name for s in find_sessions(measure_cpu=False)}

    unknown_drop = drop - set(p["dropped"])
    if unknown_drop:
        print(f"HATA: --drop ile verilen ad(lar) roster'da yok: {', '.join(sorted(unknown_drop))}")
        return 1

    inst = p["instances"]
    rule_counts = Counter(p["rules"].values())
    live_moved = sorted(n for n in inst if n in live)
    per_bp = Counter(rec["blueprint"] or "(yok)" for rec in inst.values())

    print(f"roster.tsv: {p['roster_rows']} satır")
    print(f"  taşınacak instance: {len(inst)}  " + ", ".join(f"{k}: {v}" for k, v in rule_counts.most_common()))
    print(f"    bunlardan şu an çalışan: {len(live_moved)}")
    print(f"  atılacak (--drop): {len(p['dropped'])}  {', '.join(p['dropped'])}")
    print(f"  kalacak (blueprint): {len(p['kept'])}")
    print(f"  sonuç: roster {p['roster_rows']} → {p['roster_rows'] - p['roster_lines_removed']} satır, "
          f"models.tsv'den {p['models_lines_removed']} satır çıkar")
    print("  blueprint başına: " + ", ".join(f"{b} {n}" for b, n in per_bp.most_common()))
    special = sorted(n for n, r in p["rules"].items() if r != "önek+cwd")
    if special:
        print("  özel eşleşmeler:")
        for n in special:
            print(f"    {n:36s} → {str(inst[n]['blueprint']):20s} ({p['rules'][n]})")
    if args.verbose:
        print("  tüm taşınanlar:")
        for n in sorted(inst):
            print(f"    {n:36s} → {str(inst[n]['blueprint']):20s} {inst[n]['cli']:8s} {'CANLI' if n in live else ''}")
    print("  kalan blueprint'ler: " + ", ".join(sorted(p["kept"])))

    if not args.apply:
        print("\nDry-run: hiçbir dosya değişmedi. Uygulamak için --apply ekle.")
        return 0
    if not inst and not p["dropped"]:
        print("\nTaşınacak/atılacak satır yok, yapılacak bir şey yok.")
        return 0

    ts = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(CLAUDEOPS_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    backups = []
    for path in (ROSTER_TSV, MODELS_TSV, INSTANCES_JSON):
        if os.path.exists(path):
            dst = os.path.join(backup_dir, f"{os.path.basename(path)}.migrate-{ts}")
            shutil.copy2(path, dst)
            backups.append(dst)

    if _read(ROSTER_TSV) != roster_content or _read(MODELS_TSV) != models_content:
        print("\nHATA: roster.tsv/models.tsv okunduktan sonra değişti (panelden bir işlem?). "
              "Hiçbir şey yazılmadı, tekrar çalıştır.")
        return 1

    added = add_missing(inst)
    _atomic_write_text(MODELS_TSV, p["new_models"])
    _atomic_write_text(ROSTER_TSV, p["new_roster"])
    print(f"\nUygulandı: {added} instance kaydı eklendi, roster'dan {p['roster_lines_removed']}, "
          f"models.tsv'den {p['models_lines_removed']} satır çıkarıldı.")
    print("Yedekler: " + ", ".join(backups))
    return 0
