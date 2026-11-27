"""Ortak yalıtım: `claudeops` içe aktarılmadan ÖNCE durum dizini/HOME geçici dizine döner."""
import atexit, os, shutil, sys, tempfile, time

CRATE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.abspath(os.path.join(CRATE, "..", "..", "..", "py"))

def isolate():
    d = tempfile.mkdtemp(prefix="cops-parity-")
    atexit.register(shutil.rmtree, d, True)
    os.makedirs(os.path.join(d, "tmux"), mode=0o700)
    os.environ.update(CLAUDEOPS_DIR=os.path.join(d, "state"), HOME=os.path.join(d, "home"), CLAUDEOPS_EXTENSIONS="0",
                      CLAUDEOPS_DIAG_LOG=os.path.join(d, "diag.log"), TMUX_TMPDIR=os.path.join(d, "tmux"), TZ="UTC")
    os.environ.pop("TMUX", None)
    os.makedirs(os.environ["HOME"])
    time.tzset()
    sys.dont_write_bytecode = True
    sys.path.insert(0, PY)
    return d
