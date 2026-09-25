#!/usr/bin/env bash
# claudeops — yeni bir uzak makineyi fleet'e bağlamak için tek-seferlik kurulum.
#
# Kullanım (bu makinede, "friend" hesabında):
#   git clone https://github.com/mfyuce/claudeops.git
#   bash claudeops/scripts/bootstrap-remote-host.sh
#
# Ne yapar: git/python3/pip kontrolü (kurmaz, sadece uyarır) -> py/requirements.txt
# kurulumu -> `py/cops service install` (systemd --user: web paneli + cloudflared
# quick-tunnel, sudo GEREKMEZ) -> tünel URL'ini + bu makinenin bearer token'ını
# ekrana basar. Kurumsal ağlarda cloudflared'ın port 7844'ü (QUIC+HTTP2) engellenmiş
# olabilir (claudeops'un TOBEDECIDED#19'unda yuhem'de canlı doğrulandı) -- bu
# durumda script bunu tespit edip VS Code Remote Tunnel'a geçiş talimatı basar,
# çünkü o kanal aynı sınıf ağlarda kanıtlanmış şekilde çalışıyor (port 443/HTTPS).
#
# Bu script sudo ÇALIŞTIRMAZ. Eksik bir paket varsa (git/python3/pip/tmux) kurup
# tekrar çalıştırmanızı ister, kendisi kurmaya çalışmaz -- şirket makinesinde
# yetkisiz bir kullanıcı için de güvenli, ve neyin değiştiğini önceden görebilirsiniz.
set -euo pipefail

PORT="${CLAUDEOPS_PORT:-8765}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$HOME/.claude/claudeops"

echo "=== claudeops remote-host bootstrap ==="
echo "repo: $SCRIPT_DIR"
echo

missing=()
for bin in git python3; do
    command -v "$bin" >/dev/null 2>&1 || missing+=("$bin")
done
if ! command -v pip3 >/dev/null 2>&1 && ! command -v pip >/dev/null 2>&1; then
    missing+=("pip3")
fi
if [ "${#missing[@]}" -gt 0 ]; then
    echo "Eksik: ${missing[*]} -- kurup tekrar çalıştırın, ör:"
    echo "  sudo apt install -y ${missing[*]}"
    exit 1
fi
if ! command -v tmux >/dev/null 2>&1; then
    echo "UYARI: tmux bulunamadı. Bu makine masaüstsüz (headless) ise oturumlar"
    echo "tmux gerektirir -- önerilir: sudo apt install -y tmux (devam ediliyor)"
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
echo "--- servis kurulumu (web paneli + tünel, sudo YOK) ---"
py/cops service install

echo
echo "--- tünel URL'i bekleniyor (en fazla ~25 sn) ---"
for _ in $(seq 1 25); do
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
