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

Web unit'i `bash -ic '<python> -m claudeops web'` ile çalışır (düz `<python> -m claudeops web`
DEĞİL): systemd --user servisleri `.bashrc`/`.profile`'ı hiç sourcelamaz, PATH'i sadece
sistem varsayılanı olur (`/usr/bin:/bin:...` — `~/.local/bin` YOK, `claude`/`agy` orada).
Bu servis ilk spawn_session()'ı tetiklediğinde (ör. OOM'dan sonra session sıfırdan
kurulurken) yeni açılan tmux server'a BU minimal PATH miras kalıyor — o server'ın TÜM
gelecekteki pane'lerinde `claude: command not found` (canlı bulundu, 2026-08-30, saseppr
resume'unda). `-ic` (interactive) `.bashrc`'nin en baştaki "interactive değilse dur"
guard'ını (`case $- in *i*) ;; *) return;; esac`) atlatıp nvm/sdkman/deno/cargo/vb.
araçların PATH'e eklediği satırları da içeri alıyor — canlı doğrulandı
(`bash -ic 'which claude agy'` → ikisi de bulundu). Stderr'de zararsız "cannot set
terminal process group"/"no job control" uyarıları çıkar (tty yok, beklenen).

`KillMode=process` ŞART (systemd varsayılanı `control-group` DEĞİL): bu servis
spawn_session() ile tmux server'lar/gnome-terminal'ler başlatıyor — bunlar KASITLI
olarak claudeops-web.service'ten UZUN ÖMÜRLÜ olmalı (panel restart/upgrade edilirken
fleet ayakta kalmalı, bu tüm tmux-backed mimarinin amacı). `control-group` (varsayılan)
ile servisi durdurmak/restart etmek CGROUP'taki HER ŞEYİ (windowless/tmux-direct modda
kalan sessionlar dahil) öldürür — canlı doğrulandı (2026-08-30: PATH fix'i deploy etmek
için yapılan restart, o an windowless olan `saseppr` session'ını tamamen sildi; gnome-
terminal'e bağlı session'lar hayatta kaldı çünkü onlar AYRI bir cgroup'ta/scope'ta —
`--remote-control` claude proc'unun SIGHUP'a dayanıklı olması da yardımcı oldu ama
windowless/tmux-direct session'lar için tek koruma budur).
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
NTFY_TOPIC_FILE = Path(CLAUDEOPS_DIR) / "ntfy_topic.txt"
UNIT_NAMES = ["claudeops-web.service", "claudeops-tunnel.service"]

WEB_UNIT_TEMPLATE = """[Unit]
Description=claudeops web panel

[Service]
WorkingDirectory={repo_py}
ExecStart=/bin/bash -ic '{python} -m claudeops web'
Restart=on-failure
RestartSec=5
KillMode=process

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
    s = p.add_subparsers(dest="action", metavar="<install|status|uninstall|notify>")

    p_install = s.add_parser("install", help="unit'leri yaz + linger aç + enable+start")
    p_install.add_argument("--tunnel-name", default="claudeops", metavar="NAME",
                            help="cloudflared NAMED tunnel adı (varsayılan: claudeops) — "
                                 "kurulu değilse otomatik quick-tunnel'a düşer")
    p_install.set_defaults(func=run_install)

    p_status = s.add_parser("status", help="servislerin durumu + güncel tunnel URL")
    p_status.set_defaults(func=run_status)

    p_uninstall = s.add_parser("uninstall", help="durdur + devre dışı bırak + unit dosyalarını sil")
    p_uninstall.set_defaults(func=run_uninstall)

    p_notify = s.add_parser("notify", help="tunnel URL değişince ntfy.sh push bildirimi aç/kapat")
    p_notify.add_argument("topic", nargs="?", default=None, metavar="TOPIC",
                           help="ntfy.sh topic adı (verilmezse rastgele/tahmin-zor biri üretilir)")
    p_notify.add_argument("--off", action="store_true", help="bildirimi kapat (topic dosyasını sil)")
    p_notify.set_defaults(func=run_notify)

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

    if NTFY_TOPIC_FILE.exists():
        print(f"  bildirim: AÇIK (ntfy.sh/{NTFY_TOPIC_FILE.read_text().strip()})")
    else:
        print("  bildirim: kapalı (aç: py/cops service notify)")
    return 0 if ok else 1


def run_notify(args) -> int:
    if args.off:
        if NTFY_TOPIC_FILE.exists():
            NTFY_TOPIC_FILE.unlink()
            print(f"✓ bildirim kapatıldı ({NTFY_TOPIC_FILE} silindi)")
        else:
            print("zaten kapalıydı")
        return 0

    import secrets
    topic = args.topic or ("claudeops-" + secrets.token_urlsafe(6).translate(str.maketrans("_-", "ab")))
    NTFY_TOPIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    NTFY_TOPIC_FILE.write_text(topic)
    print(f"✓ topic: {topic}")
    print(f"  ({NTFY_TOPIC_FILE} — run-tunnel.sh tunnel URL DEĞİŞTİĞİNDE buraya otomatik POST eder)")
    print()
    print("  1. Telefona 'ntfy' uygulamasını kur (App Store / Play Store)")
    print(f"  2. Uygulamada '+' → şu topic'e abone ol: {topic}")
    print(f"  3. Test etmek için: curl -d 'test' https://ntfy.sh/{topic}")
    print()
    print("  Kapatmak için: py/cops service notify --off")
    return 0


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
