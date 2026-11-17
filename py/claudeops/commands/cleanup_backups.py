"""`cleanup-backups` — TBD#4: backups/ altında en yeni N girdiyi bırak, eskileri tek tar.gz'ye taşı (silmez; varsayılan dry-run)."""
from __future__ import annotations

import os
import tarfile
import time
from typing import List, Optional, Tuple

from ..paths import CLAUDEOPS_DIR


def _backup_dir() -> str:
    return os.path.join(CLAUDEOPS_DIR, "backups")


LIVE_NAMES = {"chat-mirror"}          # canlı güncellenen dizinler (araçlar bunun içine yazar): arşivlenip silinmez
LIVE_SUFFIXES = (".sh", ".py")        # backups/ içindeki canlı betikler (chat_mirror.sh, gate_watch.sh, brain_usage.py)
RECENT_SECONDS = 3 * 86400            # ağaçta bu süreden yeni dosya = kullanımda olabilir (üst dizin mtime'ı iç değişikliği göstermez)
_WALK_MAX = 20000


def _is_live(path: str, name: str, now: float) -> bool:
    """Arşivlenip SİLİNMEMESİ gereken girdi: adlandırılmış canlı dizin, betik ya da ağacında yakın zamanda yazılmış dosya olan
    (review cliops 17 Kas: `--apply` canlı çalışma dizinlerini de arşivleyip siliyordu)."""
    if name in LIVE_NAMES or name.endswith(LIVE_SUFFIXES):
        return True
    cut = now - RECENT_SECONDS
    try:
        if os.path.getmtime(path) >= cut:
            return True
        if os.path.isdir(path):
            n = 0
            for dp, _ds, fs in os.walk(path):
                for fn in fs:
                    n += 1
                    if n > _WALK_MAX:
                        return True          # çok büyük ağaç: tarayamadık, korumacı davran
                    try:
                        if os.path.getmtime(os.path.join(dp, fn)) >= cut:
                            return True
                    except OSError:
                        continue
    except OSError:
        return True
    return False


def plan(backup_dir: str, keep: int) -> Tuple[List[str], List[str]]:
    """(tutulacaklar, arşivlenecekler) — yalnız üst düzey girdiler; mevcut `*.tar.gz` arşivleri ve sembolik bağlar dokunulmaz.
    Sıra: mtime yeni -> eski."""
    try:
        names = os.listdir(backup_dir)
    except OSError:
        return [], []
    items = []
    for n in names:
        p = os.path.join(backup_dir, n)
        if n.endswith(".tar.gz") or os.path.islink(p) or _is_live(p, n, time.time()):
            continue
        try:
            items.append((os.path.getmtime(p), n))
        except OSError:
            continue
    items.sort(key=lambda t: (-t[0], t[1]))
    keep = max(0, keep)
    return [n for _, n in items[:keep]], [n for _, n in items[keep:]]


def archive(backup_dir: str, names: List[str], now: Optional[float] = None) -> str:
    """`names`'i `archive-<ts>.tar.gz`'ye yaz; arşiv doğrulandıktan SONRA orijinalleri kaldır. Arşiv yolunu döndürür."""
    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() if now is None else now))
    dest = os.path.join(backup_dir, f"archive-{ts}.tar.gz")
    n = 1
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(backup_dir, f"archive-{ts}-{n}.tar.gz")
    with tarfile.open(dest, "w:gz") as tf:
        for name in names:
            tf.add(os.path.join(backup_dir, name), arcname=name)
    with tarfile.open(dest, "r:gz") as tf:
        have = {m.name.split("/")[0] for m in tf.getmembers()}
    if not set(names) <= have:
        raise RuntimeError(f"arşiv eksik, orijinaller korundu: {dest}")
    import shutil
    for name in names:
        p = os.path.join(backup_dir, name)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
    return dest


def register(sub):
    p = sub.add_parser("cleanup-backups", help="backups/ eskilerini tar.gz'ye taşı (varsayılan dry-run)")
    p.add_argument("--keep", type=int, default=10, metavar="N", help="en yeni N girdi yerinde kalır (varsayılan: 10)")
    p.add_argument("--apply", action="store_true", help="gerçekten arşivle (yoksa yalnız göster)")
    p.set_defaults(func=run)


def run(args) -> int:
    d = _backup_dir()
    kept, old = plan(d, args.keep)
    print(f"  {d}: {len(kept)} kalır, {len(old)} arşivlenecek")
    if not old:
        return 0
    if not args.apply:
        for n in old:
            print(f"  [dry-run] {n}")
        print("  uygulamak için --apply")
        return 0
    try:
        dest = archive(d, old)
    except (OSError, RuntimeError, tarfile.TarError) as e:
        print(f"  hata: {e}")
        return 1
    print(f"  ✓ {len(old)} girdi -> {dest}")
    return 0
