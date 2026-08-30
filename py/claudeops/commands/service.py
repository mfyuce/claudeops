"""`service` — web panel + cloudflared tunnel'ı systemd --user ile KALICI hale getir:
logout/reboot'ta otomatik başlar, çökerse kendini toplar (Restart=on-failure).

Kullanım:
  py/cops service install [--tunnel-name NAME]   # unit'leri yaz + linger aç + enable+start
  py/cops service status                          # ikisinin durumu + güncel tunnel URL
  py/cops service uninstall                       # durdur + devre dışı bırak + unit'leri sil

Herkes kendi checkout'unda `install` çalıştırabilir — unit'ler REPO_DIR/`sys.executable`'dan
DİNAMİK üretilir, hiçbir yol/kullanıcı adı sabit kodlanmaz (bkz. paths.REPO_DIR).

Sabit (hiç değişmeyen) tunnel URL'i için: `cloudflared tunnel login` (bir kere, tarayıcı;
bir Cloudflare hesabı + domain gerekir) + `cloudflared tunnel create <isim>` +
`cloudflared tunnel route dns <isim> <hostname>` — kurulduktan SONRA run-tunnel.sh
(data/run-tunnel.sh, install'da ~/.claude/claudeops/'a kopyalanır) bunu OTOMATİK algılar,
unit'lere veya bu komuta DOKUNMAK GEREKMEZ. Seçilen hostname'i
~/.claude/claudeops/tunnel_fixed_hostname.txt'e yazarsan tunnel_url.txt'e de yansır.
Kurulu değilse (varsayılan durum) sessizce quick-tunnel'a (rastgele URL) düşer.
"""
from __future__ import annotations
import shutil
import subprocess
import sys
from pathlib import Path

from ..paths import CLAUDEOPS_DIR, REPO_DIR, HOME

SYSTEMD_USER_DIR = Path(HOME) / ".config" / "systemd" / "user"
WEB_UNIT = SYSTEMD_USER_DIR / "claudeops-web.service"
TUNNEL_UNIT = SYSTEMD_USER_DIR / "claudeops-tunnel.service"
RUN_TUNNEL_SRC = Path(__file__).resolve().parents[1] / "data" / "run-tunnel.sh"
RUN_TUNNEL_DEST = Path(CLAUDEOPS_DIR) / "run-tunnel.sh"
TUNNEL_LOG = Path(CLAUDEOPS_DIR) / "tunnel.log"
TUNNEL_URL_FILE = Path(CLAUDEOPS_DIR) / "tunnel_url.txt"
UNIT_NAMES = ["claudeops-web.service", "claudeops-tunnel.service"]

WEB_UNIT_TEMPLATE = """[Unit]
Description=claudeops web panel

[Service]
WorkingDirectory={repo_py}
ExecStart={python} -m claudeops web
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""

TUNNEL_UNIT_TEMPLATE = """[Unit]
Description=claudeops cloudflared tunnel (named tunnel if configured, else quick-tunnel)
After=claudeops-web.service
Requires=claudeops-web.service

[Service]
Environment=CLAUDEOPS_TUNNEL_NAME={tunnel_name}
ExecStart={run_tunnel}
StandardOutput=append:{tunnel_log}
StandardError=append:{tunnel_log}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def register(sub):
    p = sub.add_parser("service", help="web panel + tunnel'ı systemd --user ile kalıcı yap (logout/reboot'ta otomatik)")
    s = p.add_subparsers(dest="action", metavar="<install|status|uninstall>")

    p_install = s.add_parser("install", help="unit'leri yaz + linger aç + enable+start")
    p_install.add_argument("--tunnel-name", default="claudeops", metavar="NAME",
                            help="cloudflared NAMED tunnel adı (varsayılan: claudeops) — "
                                 "kurulu değilse otomatik quick-tunnel'a düşer")
    p_install.set_defaults(func=run_install)

    p_status = s.add_parser("status", help="servislerin durumu + güncel tunnel URL")
    p_status.set_defaults(func=run_status)

    p_uninstall = s.add_parser("uninstall", help="durdur + devre dışı bırak + unit dosyalarını sil")
    p_uninstall.set_defaults(func=run_uninstall)

    p.set_defaults(func=lambda args: p.print_help() or 1)


def _sh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def run_install(args) -> int:
    repo_py = str(Path(REPO_DIR) / "py")
    if not (Path(repo_py) / "claudeops").is_dir():
        print(f"✗ {repo_py} altında claudeops paketi bulunamadı — beklenmeyen repo düzeni", file=sys.stderr)
        return 1

    Path(CLAUDEOPS_DIR).mkdir(parents=True, exist_ok=True)
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(RUN_TUNNEL_SRC, RUN_TUNNEL_DEST)
    RUN_TUNNEL_DEST.chmod(0o755)
    print(f"✓ {RUN_TUNNEL_DEST}")

    WEB_UNIT.write_text(WEB_UNIT_TEMPLATE.format(repo_py=repo_py, python=sys.executable))
    print(f"✓ {WEB_UNIT}")

    TUNNEL_UNIT.write_text(TUNNEL_UNIT_TEMPLATE.format(
        tunnel_name=args.tunnel_name, run_tunnel=RUN_TUNNEL_DEST, tunnel_log=TUNNEL_LOG,
    ))
    print(f"✓ {TUNNEL_UNIT}")

    r = _sh("systemctl", "--user", "daemon-reload")
    if r.returncode != 0:
        print(f"✗ daemon-reload: {r.stderr.strip()}", file=sys.stderr)
        return 1

    import getpass
    r = _sh("loginctl", "enable-linger", getpass.getuser())
    if r.returncode != 0:
        print(f"⚠ enable-linger başarısız (sudo/polkit gerekebilir): {r.stderr.strip()}", file=sys.stderr)
        print("  linger olmadan da çalışır AMA sadece siz login olduğunuzda; logout'ta durur.", file=sys.stderr)

    r = _sh("systemctl", "--user", "enable", "--now", *UNIT_NAMES)
    if r.returncode != 0:
        print(f"✗ enable --now: {r.stderr.strip()}", file=sys.stderr)
        print("  İpucu: port 8765 zaten elle çalışan bir `claudeops web` tarafından kullanılıyor olabilir "
              "— önce onu durdurun (Ctrl-C / kill), sonra tekrar deneyin.", file=sys.stderr)
        return 1

    print()
    print("✓ kuruldu ve başlatıldı. Durum için: py/cops service status")
    return 0


def run_status(args) -> int:
    ok = True
    for unit in UNIT_NAMES:
        active = _sh("systemctl", "--user", "is-active", unit).stdout.strip() or "unknown"
        enabled = _sh("systemctl", "--user", "is-enabled", unit).stdout.strip() or "unknown"
        mark = "✓" if active == "active" else "✗"
        if active != "active":
            ok = False
        print(f"{mark} {unit}: active={active} enabled={enabled}")

    import getpass
    linger = _sh("loginctl", "show-user", getpass.getuser(), "-p", "Linger").stdout.strip()
    print(f"  {linger or 'Linger=unknown'} (logout sonrası da çalışmaya devam eder mi?)")

    if TUNNEL_URL_FILE.exists():
        print(f"\n  tunnel URL: {TUNNEL_URL_FILE.read_text().strip()}")
    else:
        print(f"\n  ⚠ {TUNNEL_URL_FILE} henüz yok — tunnel servisi ilk kez ayağa kalkıyor olabilir, birkaç sn sonra tekrar deneyin.")
    return 0 if ok else 1


def run_uninstall(args) -> int:
    r = _sh("systemctl", "--user", "disable", "--now", *UNIT_NAMES)
    if r.returncode != 0:
        print(f"⚠ disable --now: {r.stderr.strip()}", file=sys.stderr)

    for unit_path in (WEB_UNIT, TUNNEL_UNIT):
        if unit_path.exists():
            unit_path.unlink()
            print(f"✓ silindi: {unit_path}")

    _sh("systemctl", "--user", "daemon-reload")
    print("✓ kaldırıldı. (Linger açık bırakıldı — başka kalıcı user-servisleriniz olabilir; "
          "kapatmak isterseniz: loginctl disable-linger $(whoami))")
    return 0
