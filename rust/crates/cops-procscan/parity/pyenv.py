"""Python tarafını SALT OKUR koşturan ortam (parite koşucusu ve altın vektör üreticisi ortak kullanır).

- `CLAUDEOPS_DIR` claudeops import edilmeden ÖNCE geçici dizine alınır; `CLAUDEOPS_EXTENSIONS` boş (eklenti yüklenmez).
- `GIT_OPTIONAL_LOCKS=0`: `git status` gerçek depolarda indeksi tazeleyip yazmasın.
- Audit hook: geçici dizin dışına her yazma açılışı, dosya silme/taşıma/dizin oluşturma, sqlite bağlantısı ve
  sinyal (`os.kill`/`os.killpg`) PermissionError ile DURDURULUR (kod okuması kaçırsa bile canlı duruma yazılamaz).
- Başka kullanıcının süreç İÇERİĞİ (cmdline/environ/cwd) okunmaz: psutil yamaları aşağıda (`install_psutil_guard`).
  Python üretimde bunları okur (process_iter tüm süreçlerin cmdline'ını önceden çeker, is_tmux_backed başka
  kullanıcının atasının cmdline'ını okur); sonuç aynıdır çünkü uid süzgeci/ata yürüyüşü bu süreçleri zaten eler ya da
  orada durur (Rust sapması 2 ile aynı yön).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]            # rust/crates/cops-procscan/parity -> repo kökü
PY_DIR = REPO / "py"

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_PATH_EVENTS = {"os.remove", "os.rename", "os.replace", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.symlink",
                "os.link", "os.truncate", "os.utime", "shutil.rmtree", "shutil.move", "shutil.copyfile"}
_blocked: list = []


def _allowed(path, roots) -> bool:
    if isinstance(path, int):
        return False
    try:
        p = os.path.realpath(os.fsdecode(path))
    except Exception:
        return False
    return any(p == r or p.startswith(r + os.sep) for r in roots)


def setup(extra_allowed=()) -> str:
    """Geçici durum dizinini kurar, korumaları takar, `py/`u yola ekler. Dönen: geçici dizin."""
    if "claudeops" in sys.modules:
        raise RuntimeError("claudeops setup()'tan önce import edilmiş")
    sys.dont_write_bytecode = True     # `py/**/__pycache__` de yazılmasın
    tmp = tempfile.mkdtemp(prefix="cops-procscan-parity-")
    os.environ["CLAUDEOPS_DIR"] = tmp
    os.environ["CLAUDEOPS_EXTENSIONS"] = ""
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    roots = [os.path.realpath(tmp)] + [os.path.realpath(x) for x in extra_allowed]

    def hook(event, args):
        if event == "open":
            path, mode, flags = (list(args) + [None, None, None])[:3]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                (isinstance(flags, int) and flags & _WRITE_FLAGS)
            if writing and not _allowed(path, roots):
                _blocked.append(("open", str(path)))
                raise PermissionError(f"parite: yazma engellendi {path}")
        elif event in _PATH_EVENTS:
            paths = [a for a in args[:2] if isinstance(a, (str, bytes, os.PathLike))]
            if not all(_allowed(p, roots) for p in paths):
                _blocked.append((event, str(paths)))
                raise PermissionError(f"parite: {event} engellendi {paths}")
        elif event == "sqlite3.connect":
            db = args[0] if args else None
            if not (isinstance(db, (str, bytes, os.PathLike)) and (str(db) == ":memory:" or _allowed(db, roots))):
                _blocked.append((event, str(db)))
                raise PermissionError(f"parite: sqlite engellendi {db}")
        elif event in ("os.kill", "os.killpg"):
            _blocked.append((event, str(args)))
            raise PermissionError("parite: sinyal yasak")

    sys.addaudithook(hook)
    sys.path.insert(0, str(PY_DIR))
    return tmp


def rmtree(path) -> None:
    """Mutlak yollarla alttan üste siler (`shutil.rmtree` dir_fd'li göreli adlar kullandığından korumaya takılır)."""
    if not os.path.isdir(path):
        return
    for root, dirs, files in os.walk(path, topdown=False):
        for f in files:
            os.unlink(os.path.join(root, f))
        for d in dirs:
            p = os.path.join(root, d)
            os.unlink(p) if os.path.islink(p) else os.rmdir(p)
    os.rmdir(path)


def blocked():
    return list(_blocked)


def _kill0(pid, sig):
    """`os.kill(pid, 0)` yerine: sinyal sistem çağrısı YAPMADAN çekirdeğin ayrıcalıksız kuralı (gönderenin uid'i hedefin
    gerçek ya da saklı uid'ine eşitse izin) `/proc/<pid>/status`tan. 0 dışı sinyal yasak."""
    if sig != 0:
        raise PermissionError("parite: sinyal yasak")
    try:
        pid = int(pid)
        if pid <= 0:
            raise PermissionError("parite: grup/negatif pid yasak")
        with open(f"/proc/{pid}/status", "rb") as f:
            uid_line = next(ln for ln in f.read().decode("latin-1").splitlines() if ln.startswith("Uid:"))
    except FileNotFoundError:
        raise ProcessLookupError(3, "No such process") from None
    ruid, _euid, suid = (int(x) for x in uid_line.split()[1:4])
    if os.getuid() not in (ruid, suid):
        raise PermissionError(1, "Operation not permitted")


def install_psutil_guard():
    """psutil'in başka kullanıcının süreç içeriğini okumasını engeller (yalnız `status`/`stat` meta verisi kalır);
    `os.kill(pid, 0)` canlılık denetimi sinyalsiz taklitle değişir."""
    import psutil

    os.kill = _kill0
    me = os.getuid()
    real_cmdline, real_environ, real_cwd = psutil.Process.cmdline, psutil.Process.environ, psutil.Process.cwd

    def owned(p) -> bool:
        try:
            return p.uids().real == me
        except psutil.Error:
            return False

    def guard(fn):
        def wrapped(self, *a, **k):
            if not owned(self):
                raise psutil.AccessDenied(self.pid)
            return fn(self, *a, **k)
        return wrapped

    psutil.Process.cmdline = guard(real_cmdline)
    psutil.Process.environ = guard(real_environ)
    psutil.Process.cwd = guard(real_cwd)
    real_iter = psutil.process_iter

    def process_iter(attrs=None, ad_value=None):
        """Önce yalnız uid; içerik öznitelikleri yalnız bizim süreçler için doldurulur."""
        attrs = list(attrs or [])
        for p in real_iter(["pid", "uids"]):
            info = dict(p.info)
            mine = info.get("uids") is not None and info["uids"].real == me
            for a in attrs:
                if a in ("pid", "uids"):
                    continue
                if not mine:
                    info[a] = ad_value
                    continue
                try:
                    info[a] = getattr(p, a)()
                except psutil.NoSuchProcess:
                    info = None
                    break
                except psutil.AccessDenied:
                    info[a] = ad_value
            if info is None:
                continue
            p.info = info
            yield p

    psutil.process_iter = process_iter


def web_function(name: str, namespace: dict):
    """`commands/web.py`den tek işlevi kaynağından derler (web.py'nin import yan etkileri ve bağımlılıkları olmadan).
    `namespace` işlevin kullandığı adları sağlar."""
    import ast
    src = (PY_DIR / "claudeops" / "commands" / "web.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            code = compile(ast.Module(body=[node], type_ignores=[]), "web.py", "exec")
            exec(code, namespace)
            return namespace[name]
    raise KeyError(name)
