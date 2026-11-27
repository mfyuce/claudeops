"""Sabit yollar — tek kaynak (bash claudeops'taki dağınık path'lerin yerine)."""
import os
import stat
from pathlib import Path

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")


def _test_code_loaded() -> bool:
    """Süreçte test kodu var mı (argv'den bağımsız; 26 Kas 2026: `unittest.main()` çağıran özel koşucu canlıya yazdı):
    bu deponun `py/tests` altından modül yüklenmiş, ya da depo DIŞI bir betik `unittest` yüklemiş. Canlı giriş
    noktası (`__main__` depo içinde) `unittest` yüklese de gerçek dizinde kalır."""
    import sys
    repo = Path(__file__).resolve().parents[2]
    tests = str(repo / "py" / "tests") + os.sep
    if any((getattr(m, "__file__", None) or "").startswith(tests) for m in list(sys.modules.values())):
        return True
    if "unittest.case" not in sys.modules:
        return False
    main = getattr(sys.modules.get("__main__"), "__file__", None)
    return not main or repo not in Path(main).resolve().parents


def _under_test_runner() -> bool:
    """`python -m unittest` (argv[0]'ı "... -m unittest" yapar), pytest ya da yüklü test kodu (`_test_code_loaded`).
    `CLAUDEOPS_TEST_REAL_DIR=1` bilerek gerçek dizini isteyen (izole e2e değil, canlı) koşu içindir."""
    import sys
    if os.environ.get("CLAUDEOPS_TEST_REAL_DIR") == "1":
        return False
    argv0 = sys.argv[0] if sys.argv else ""
    return (argv0.endswith("-m unittest") or os.path.basename(argv0).startswith("test_")     # `python3 test_x.py` de
            or "pytest" in sys.modules or "_pytest" in sys.modules or _test_code_loaded())


# Env override izole test/e2e için (canlı roster yerine bir config kopyası); normalde set edilmez.
# L3 (10 Kas 2026): testler 6+ kez CANLI duruma yazdı (settings.json ezildi, steward log'a sahte satırlar, diag.log, gerçek
# oturum). Test koşucusu altında ve env yoksa dizin süreç başına GEÇİCİ dizine döner (alt süreçler env'den devralır);
# dosya dosya hatırlamaya gerek yok. Testler hiçbir zaman ~/.claude/claudeops'a yazmaz.
if not os.environ.get("CLAUDEOPS_DIR") and _under_test_runner():
    import atexit
    import shutil
    import tempfile
    os.environ["CLAUDEOPS_DIR"] = tempfile.mkdtemp(prefix="cops-test-state-")
    atexit.register(shutil.rmtree, os.environ["CLAUDEOPS_DIR"], True)    # yalnız oluşturan süreç siler (alt süreç env'den alır)
CLAUDEOPS_DIR = os.environ.get("CLAUDEOPS_DIR") or os.path.join(CLAUDE_DIR, "claudeops")
# Göreli değer sürecin dizinine göre çözülür; `py/cops` önce `cd py/` yaptığından gizli, birim `--state-dir`i, DB `py/`
# altına giderdi. Kapalı yön: açık hata, hiçbir şey yazılmadan (Rust `cops-cli` `Roots::check_absolute` ile aynı metin).
# Yalnız ortam değeri denetlenir (göreli HOME'dan türeyen varsayılan bu düzeltmenin kapsamı dışında).
if os.environ.get("CLAUDEOPS_DIR") and not os.path.isabs(CLAUDEOPS_DIR):
    raise SystemExit(f"CLAUDEOPS_DIR göreli ({CLAUDEOPS_DIR}): mutlak yol verin")
STATE_DIR = Path(CLAUDEOPS_DIR)   # needs_ho / handover timestamp için Path API

# claudeops repo'nun kendi kökü (bu dosyadan: claudeops/py/claudeops/paths.py → 2 parent yukarı).
# "LLM'e sor" diag session'ı için cwd — sorulan şey bu repo'nun kendi spawn koduysa mantıklı.
REPO_DIR = str(Path(__file__).resolve().parents[2])

ROSTER_TSV = os.path.join(CLAUDEOPS_DIR, "roster.tsv")   # name<TAB>cwd<TAB>model
MODELS_TSV = os.path.join(CLAUDEOPS_DIR, "models.tsv")   # name<TAB>model
CLAUDE_MODELS_JSON = os.path.join(CLAUDEOPS_DIR, "claude_models.json")  # {"models": {id: "enabled"|"disabled"}} — model_freshness.py

SESSIONS_DIR = os.path.join(CLAUDE_DIR, "sessions")      # <pid>.json (gecikmeli yazılır!)
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")      # <encoded-cwd>/<sid>.jsonl
CONFIG_JSON = os.path.join(HOME, ".claude.json")         # bozulursa resume-hang

_SESSION_RECORD_MAX_BYTES = 1024 * 1024      # Rust okuyucusunun sınırı


def _read_session_record(path: str) -> str:
    """`sessions/<pid>.json` metni: yalnız sınırı aşmayan normal dosya (FIFO açılışta bloklamaz); aksi halde `OSError`
    (bozuk UTF-8 `ValueError`)."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with open(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"normal dosya değil: {path}")
        raw = f.read(_SESSION_RECORD_MAX_BYTES + 1)
    if len(raw) > _SESSION_RECORD_MAX_BYTES:
        raise OSError(f"süreç kaydı çok büyük: {path}")
    return raw.decode("utf-8")


def parse_proc_stat(raw: str) -> list:
    """`/proc/<pid>/stat` metninin comm'dan SONRAKİ alanları (0=state, 1=ppid, 19=starttime). comm boşluk/parantez
    içerebilir: SON ')' sonrası ayrıştırılır. ')' yoksa ValueError."""
    return raw[raw.rindex(")") + 1:].split()


def proc_stat_fields(pid) -> list:
    """`parse_proc_stat` + dosya okuma (OSError/ValueError çağırana)."""
    with open(f"/proc/{pid}/stat", "rb") as f:
        return parse_proc_stat(f.read().decode("utf-8", "replace"))


def proc_ppid(pid) -> int:
    return int(proc_stat_fields(pid)[1])


def ucli_key_file(service: str = "") -> str:
    """ucli anahtar dosyası TEK yerde: `service` boşsa Evren `ucli_api_key`, doluysa `ucli_key_<service>`.
    Taban `~/.claude/claudeops` (CLAUDEOPS_DIR env'inden BAĞIMSIZ: eski davranış birebir). Hizmet anahtarını ikinci
    örnek kendi dizininde tutar (`ucli_provider._service_key_file`)."""
    name = f"ucli_key_{service}" if service else "ucli_api_key"
    return os.path.expanduser(f"~/.claude/claudeops/{name}")


def shared_write_allowed(path: str) -> bool:
    """Ortak durum kökü (`~/.claude/claudeops`) altındaki anahtar/kullanım yolu bu süreçte yazılıp silinebilir mi
    (TBD#412 b). `CLAUDEOPS_DIR` başka dizini gösteriyorsa (deneme/ikinci örnek) HAYIR: ortak dosyalar yalnız okunur.
    Kök dışındaki yol serbest. Sembolik bağ iki yönde de sayılır (sözcüksel ya da çözülmüş yol kökteyse ortak)."""
    shared = os.path.expanduser("~/.claude/claudeops")
    if os.path.realpath(CLAUDEOPS_DIR) == os.path.realpath(shared):
        return True
    for norm in (os.path.abspath, os.path.realpath):
        root, p = norm(shared), norm(path)
        if p == root or p.startswith(root + os.sep):
            return False
    return True


GUARD_LOCK = f"/tmp/claudeops-{os.getuid()}/guard.lock"   # kullanıcıya özel: çok kullanıcılı makinede ikinci kullanıcı PermissionError almaz


def ensure_private_state_dir() -> None:
    """`CLAUDEOPS_DIR` (roster.tsv/models.tsv/settings.json/hosts.json/
    web.token/instances.json/ucli_api_key — every piece of this
    tool's own state) must not be readable/traversable by another local
    account: this machine is multi-user (see project CLAUDE.md), and several
    of these files carry bearer tokens/API keys. A single `chmod 0700` on the
    directory covers every file inside it regardless of each file's own mode
    bits (a non-owner can't even `stat` a filename inside a 0700 dir) — cheaper
    and more robust than chasing down every individual writer. Call at the
    start of each long-lived entrypoint (`cops web`) — idempotent,
    a plain `os.chmod` on an already-0700 dir is a no-op."""
    os.makedirs(CLAUDEOPS_DIR, exist_ok=True)
    os.chmod(CLAUDEOPS_DIR, 0o700)
