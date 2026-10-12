"""Çalışan `cops watch` mirror pencereleri (TBD#74 Faz 2): süreç taraması + öne getirme.

`cops watch <host>:<ad>` bir terminal penceresinin İÇİNDE koşar ve pencere başlığını TAM `host:ad`
yapar. Panelin "masaüstüne aç" düğmesi (`web._open_mirror_window`) ve `layout` bu pencereleri süreç
taramasıyla tanır: ek bir state dosyası yok (fleet'in proc-scan tarzı), pencere kapanınca süreç de
gider, yani liste kendiliğinden doğru kalır. Makine ÇOK-KULLANICILI: yalnız bu kullanıcının süreçleri.

Leaf modül: `commands/` paketine bağımlı DEĞİL (yön commands → root); `commands/watch.py`'nin
`parse_target`ını bu yüzden burada TEKRARLAMAK yerine yalnız gereken kadarı (`host:ad`/çıplak ad)
yazıldı.
"""
from __future__ import annotations

import os
import subprocess
from typing import Callable, Dict, List, Optional, Sequence

import psutil

LOCAL_HOST = "local"  # hosts.LOCAL_HOST_NAME ile AYNI, hosts.py'ye bağlanmamak için (leaf modül)

# `watch`in değer alan bayrakları: hedef, bunların DEĞERİ değil, bayraksız ilk argümandır.
_VALUE_FLAGS = frozenset({"--port", "--transport"})


def spec_from_cmdline(cmdline: Optional[Sequence[str]]) -> Optional[str]:
    """`python3 -m claudeops watch <hedef> [bayraklar]` komut satırından `host:ad`; başka her şeye None.

    Çıplak ad yerel session demektir (`local:ad`, `watch.parse_target` ile aynı). `--once` (tek kare
    basıp çıkan) bir pencere DEĞİLDİR, sayılmaz. Hedef bayraklardan ÖNCE ya da SONRA gelebilir."""
    if not cmdline:
        return None
    args = list(cmdline)
    for i in range(1, len(args) - 1):
        if args[i - 1] == "claudeops" and args[i] == "watch":
            rest = args[i + 1:]
            break
    else:
        return None
    if "--once" in rest:
        return None
    target: Optional[str] = None
    skip = False
    for tok in rest:
        if skip:
            skip = False
        elif tok in _VALUE_FLAGS:
            skip = True
        elif not tok.startswith("-"):
            target = tok
            break
    if not target:
        return None
    host, sep, name = target.partition(":")
    if not sep:
        host, name = LOCAL_HOST, target
    host, name = host.strip(), name.strip()
    return f"{host}:{name}" if host and name else None


def running_mirrors(uid: Optional[int] = None) -> Dict[str, List[int]]:
    """Şu an çalışan mirror görüntüleyicileri: `host:ad` → [pid, ...] (yalnız `uid`'in, varsayılan bu kullanıcı)."""
    uid = os.getuid() if uid is None else uid
    found: Dict[str, List[int]] = {}
    for proc in psutil.process_iter(["pid", "cmdline", "uids"]):
        try:
            info = proc.info
            uids = info.get("uids")
            if uids is None or uids.real != uid:
                continue
            spec = spec_from_cmdline(info.get("cmdline"))
        except (psutil.Error, OSError):
            continue
        if spec:
            found.setdefault(spec, []).append(info["pid"])
    return found


def focus_window(spec: str, display: str, *, run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run) -> bool:
    """Açık mirror penceresini öne getirir. `wmctrl -F -a`: `-F` başlığı TAM eşleştirir; `-F`siz alt-dize
    eşleşir ve `host:ad` başka bir `host:ad2` penceresini de yakalardı. Best-effort: başarısızlık False."""
    env = {**os.environ, "DISPLAY": display}
    try:
        result = run(["wmctrl", "-F", "-a", spec], env=env, capture_output=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0
