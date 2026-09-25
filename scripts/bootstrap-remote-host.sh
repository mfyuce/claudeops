#!/usr/bin/env bash
# claudeops — yeni bir uzak makineyi fleet'e bağlamak için tek-seferlik kurulum.
#
# Kullanım (bu makinede, hangi kullanıcı çalıştırırsa o kullanıcının home'una kurulur):
#   git clone https://github.com/mfyuce/claudeops.git
#   bash claudeops/scripts/bootstrap-remote-host.sh
#
# İzole bir kurulum isterseniz (ör. arkadaşınızın kişisel hesabı yerine ayrı bir
# kullanıcı) önce scripts/provision-user.sh'e bakın — o script sistem paketlerini
# kurup ayrı bir kullanıcı açar, SONRA bu script o kullanıcı olarak çalıştırılır.
#
# Ne yapar: git/python3/pip kontrolü (kurmaz, sadece uyarır) -> py/requirements.txt
# kurulumu -> `py/cops service install` (systemd --user: web paneli + cloudflared
# quick-tunnel, sudo GEREKMEZ) -> ntfy.sh bildirimi kurar (tünel URL'i sonradan
# DEĞİŞİRSE haber verir, quick-tunnel'lar kalıcı değil) -> tünel URL'ini + bu
# makinenin bearer token'ını ekrana basar. Kurumsal ağlarda cloudflared'ın port
# 7844'ü (QUIC+HTTP2) engellenmiş olabilir (claudeops'un TOBEDECIDED#19'unda
# yuhem'de canlı doğrulandı) -- bu durumda script bunu tespit edip VS Code
# Remote Tunnel'a geçiş talimatı basar, çünkü o kanal aynı sınıf ağlarda
# kanıtlanmış şekilde çalışıyor (port 443/HTTPS).
#
# Bu script sudo'yu SADECE açıkça onay alarak çalıştırır (aşağıda "kurayım mı?"
# sorusu) -- hiçbir zaman sessiz/unattended sudo yok, ve tam çalıştırılacak komut
# önceden ekrana basılır. Gerçek bir terminalde (SSH/konsol) çalıştığınız için
# sudo'nun kendi parola sorması normal şekilde çalışır (bunun aksine, claudeops'un
# KENDİ web-terminal panelinden sudo çalıştırmak farklı/riskli bir durum --
# TOBEDECIDED#19'da parola maskesiz pane'e düz metin yazmıştı; bu script o
# senaryonun DIŞINDA, gerçek bir TTY'de çalışır).
set -euo pipefail

# NOT gerçek bir parametre: `py/cops service install`'in ürettiği systemd unit'i
# (service.py: WEB_UNIT_TEMPLATE) portu hiç parametrize etmiyor, her zaman
# web.py'nin DEFAULT_PORT'unu (8765) kullanır -- burada CLAUDEOPS_PORT gibi bir
# env var'la "override edilebilir" görünümü vermek yanıltıcı olurdu, o yüzden
# sabit. Gerçekten farklı bir port gerekiyorsa önce service.py'ye --port desteği
# eklenmeli.
PORT=8765
# paths.py'deki CLAUDEOPS_DIR ile AYNI override -- claudeops'un kendisi bu env
# var'ı destekliyor (izole test kurulumlarında kullanılıyor), bu script de aynı
# yeri okumazsa CLAUDEOPS_DIR özelleştirilmiş bir kurulumda yanlış dizine bakar.
STATE_DIR="${CLAUDEOPS_DIR:-$HOME/.claude/claudeops}"
# Sadece bu script'in kendi bekleme döngüsü -- gerçek bir claudeops ayarı değil,
# yavaş/kısıtlı bir ağda tünelin kurulması daha uzun sürebiliyorsa yükseltin.
TUNNEL_WAIT_SECS="${CLAUDEOPS_TUNNEL_WAIT_SECS:-25}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== claudeops remote-host bootstrap ==="
echo "repo: $SCRIPT_DIR"
echo

apt_missing=()
for bin in git python3; do
    command -v "$bin" >/dev/null 2>&1 || apt_missing+=("$bin")
done
if ! command -v pip3 >/dev/null 2>&1 && ! command -v pip >/dev/null 2>&1; then
    apt_missing+=("python3-pip")
fi
if ! command -v tmux >/dev/null 2>&1; then
    apt_missing+=("tmux")
fi

if [ "${#apt_missing[@]}" -gt 0 ]; then
    echo "Eksik paket(ler): ${apt_missing[*]}"
    if [ -t 0 ] && command -v sudo >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
        echo "Şu komut çalıştırılacak:"
        echo "  sudo apt-get install -y ${apt_missing[*]}"
        read -r -p "Şimdi kurulsun mu? [y/N] " reply
        if [[ "$reply" =~ ^[Yy]$ ]]; then
            sudo apt-get install -y "${apt_missing[@]}"
        else
            echo "Geçildi -- elle kurup script'i tekrar çalıştırın."
            exit 1
        fi
    else
        echo "Otomatik kuramıyorum (interaktif TTY yok veya apt-get/sudo yok)."
        echo "Kurup tekrar çalıştırın: sudo apt-get install -y ${apt_missing[*]}"
        exit 1
    fi
fi

cd "$SCRIPT_DIR"

echo "--- Python bağımlılıkları ---"
PIP=(pip3 install --user -r py/requirements.txt)
command -v pip3 >/dev/null 2>&1 || PIP=(pip install --user -r py/requirements.txt)
if ! "${PIP[@]}" 2>/tmp/claudeops-bootstrap-pip.err; then
    if grep -q "externally-managed-environment" /tmp/claudeops-bootstrap-pip.err 2>/dev/null; then
        echo "sistem pip'i kısıtlı (PEP 668) -- --break-system-packages ile tekrar deneniyor"
        "${PIP[@]}" --break-system-packages
    else
        cat /tmp/claudeops-bootstrap-pip.err >&2
        exit 1
    fi
fi
rm -f /tmp/claudeops-bootstrap-pip.err

echo
echo "--- systemd --user bus kontrolü ---"
# `sudo -iu`/`su -` ile girilen, hiç `loginctl enable-linger` almamış bir
# hesapta XDG_RUNTIME_DIR/DBUS_SESSION_BUS_ADDRESS boş kalabiliyor -- bu durumda
# `systemctl --user` "Failed to connect to bus" ile patlıyor (canlı doğrulandı,
# 2026-09-25). `/run/user/<uid>/bus` zaten çalışıyorsa (ör. linger scripts/
# provision-user.sh tarafından önceden açıldıysa) sessizce onu kullan; hiç
# yoksa net bir hata + tam düzeltme komutu ver, kriptik systemd hatasında bırakma.
if [ -z "${XDG_RUNTIME_DIR:-}" ] || [ ! -S "${XDG_RUNTIME_DIR:-/nonexistent}/bus" ]; then
    RUNTIME_GUESS="/run/user/$(id -u)"
    if [ -S "$RUNTIME_GUESS/bus" ]; then
        export XDG_RUNTIME_DIR="$RUNTIME_GUESS"
        export DBUS_SESSION_BUS_ADDRESS="unix:path=$RUNTIME_GUESS/bus"
        echo "XDG_RUNTIME_DIR/DBUS_SESSION_BUS_ADDRESS otomatik ayarlandı ($RUNTIME_GUESS)"
    else
        echo "systemd --user bus'ı hazır değil ($RUNTIME_GUESS/bus yok)." >&2
        echo "Muhtemel sebep: bu kullanıcı için 'loginctl enable-linger' hiç çalıştırılmadı." >&2
        echo "Sudo yetkiniz olan BAŞKA bir hesapta/terminalde şunu çalıştırıp bu script'i" >&2
        echo "tekrar deneyin (logout/login GEREKMEZ, linger etkinleşince hemen çalışır):" >&2
        echo "  sudo loginctl enable-linger $(whoami)" >&2
        exit 1
    fi
fi

echo
echo "--- servis kurulumu (web paneli + tünel, sudo YOK) ---"
py/cops service install

echo
echo "--- telefon bildirimi (ntfy.sh, hesap gerekmez) ---"
# Quick-tunnel URL'leri kalıcı değil -- cloudflared herhangi bir sebeple
# yeniden bağlanırsa (ağ blip'i, restart) YENİ bir URL üretir ve eski URL
# Cloudflare'in "Error 1033"üyle kalıcı olarak ölür (canlı yaşandı, ulak/
# 10.20.40.31, 2026-09-25). Bunu elle fark etmek yerine ntfy.sh'e (ücretsiz,
# hesap yok) URL DEĞİŞTİĞİNDE otomatik bildirim kurulur. Zaten kuruluysa
# (script tekrar çalıştırıldıysa) topic DEĞİŞTİRİLMEZ -- yeniden abone olmaya
# gerek kalmasın diye.
if [ -s "$STATE_DIR/ntfy_topic.txt" ]; then
    echo "zaten kurulu: ntfy.sh/$(cat "$STATE_DIR/ntfy_topic.txt")"
else
    NTFY_TOPIC="${CLAUDEOPS_NTFY_TOPIC:-claudeops-$(tr -dc 'a-z0-9' < /dev/urandom | head -c 10)}"
    py/cops service notify "$NTFY_TOPIC"
    echo "abone olun: https://ntfy.sh/${NTFY_TOPIC} (ntfy mobil app'te de aynı topic adı)"
    echo "tünel URL'i BUNDAN SONRA değişirse oraya bildirim gelir (şu anki URL retroaktif bildirilmez)"
fi

echo
echo "--- tünel URL'i bekleniyor (en fazla ~${TUNNEL_WAIT_SECS} sn) ---"
for _ in $(seq 1 "$TUNNEL_WAIT_SECS"); do
    [ -s "$STATE_DIR/tunnel_url.txt" ] && break
    sleep 1
done

URL_FILE="$STATE_DIR/tunnel_url.txt"
TOKEN_FILE="$STATE_DIR/web.token"
LOG_FILE="$STATE_DIR/tunnel.log"

if [ -s "$URL_FILE" ] && ! tail -20 "$LOG_FILE" 2>/dev/null | grep -qE "i/o timeout|context deadline exceeded|Unauthorized: Tunnel not found"; then
    echo
    echo "=========================================================="
    echo "BAŞARILI -- bu bilgileri Fatih'e gönderin (base_url + token):"
    echo "  base_url : $(cat "$URL_FILE")"
    echo "  token    : $(cat "$TOKEN_FILE")"
    echo "=========================================================="
else
    echo
    echo "=========================================================="
    echo "Cloudflare tunnel bu ağda kurulamadı (kurumsal ağlarda port"
    echo "7844 sık engelleniyor -- claudeops'ta bu daha önce de görüldü)."
    echo "Son log satırları:"
    tail -8 "$LOG_FILE" 2>/dev/null || echo "  (log dosyası henüz yok)"
    echo
    echo "Alternatif -- VS Code'un kendi Remote Tunnel'ı (port 443/HTTPS"
    echo "kullanır, bu tarz ağlarda daha güvenilir):"
    echo "  1) VS Code kurulu değilse: https://code.visualstudio.com/download"
    echo "  2) code tunnel --accept-server-license-terms"
    echo "     (bir kod gösterecek, açılan sayfada GitHub/Microsoft hesabınızla"
    echo "     giriş yapıp o kodu onaylayın)"
    echo "  3) VS Code'da PORTS panelinden ${PORT} portunu bulun, sağ tık ->"
    echo "     Port Visibility -> Public yapın (varsayılan Private OAuth ister)"
    echo "  4) Açılan https://*.devtunnels.ms URL'ini + şu token'ı Fatih'e gönderin:"
    echo "     $(cat "$TOKEN_FILE" 2>/dev/null || echo '(henüz yok, service install tamamlanmamış olabilir)')"
    echo "=========================================================="
fi
