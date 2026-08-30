#!/usr/bin/env bash
# claudeops tunnel launcher (bundled template — `py/cops service install` bunu
# ~/.claude/claudeops/run-tunnel.sh'e kopyalar, elle çalıştırılmak için değil).
#
# Named tunnel varsa (bkz. README: "sabit tunnel URL kurulumu") sabit URL kullanır,
# yoksa quick-tunnel'a (login gerekmez, rastgele URL) düşer — AYNI script/systemd
# unit'i ikisini de destekler, hangisi kullanılacağı sadece named tunnel'ın kurulu
# olup olmamasına bağlı.
#
# Güncel URL her zaman: ~/.claude/claudeops/tunnel_url.txt
set -u
TUNNEL_NAME="${CLAUDEOPS_TUNNEL_NAME:-claudeops}"
PORT="${CLAUDEOPS_PORT:-8765}"
STATE_DIR="$HOME/.claude/claudeops"
URL_FILE="$STATE_DIR/tunnel_url.txt"
CLOUDFLARED="$HOME/.local/bin/cloudflared"
command -v "$CLOUDFLARED" >/dev/null 2>&1 || CLOUDFLARED="cloudflared"
mkdir -p "$STATE_DIR"

if "$CLOUDFLARED" tunnel list 2>/dev/null | awk '{print $2}' | grep -qx "$TUNNEL_NAME"; then
    echo "[run-tunnel] named tunnel '$TUNNEL_NAME' bulundu — sabit URL kullanılıyor"
    # Sabit hostname'i (kurulum sırasında elle yazılır, bkz. README) URL_FILE'a yansıt.
    [ -f "$STATE_DIR/tunnel_fixed_hostname.txt" ] && cp "$STATE_DIR/tunnel_fixed_hostname.txt" "$URL_FILE"
    exec "$CLOUDFLARED" tunnel run "$TUNNEL_NAME"
fi

echo "[run-tunnel] named tunnel yok — quick-tunnel (rastgele URL) başlatılıyor"
# tunnel.log APPEND modunda (systemd StandardOutput=append:...) — eski çalıştırmalardan
# kalma bir önceki (artık ÖLÜ) URL hâlâ dosyada duruyor olabilir. Bu run'dan ÖNCEKİ satır
# sayısını kaydedip SADECE ondan SONRA eklenen satırlarda arıyoruz, yoksa `tail -1` stale
# URL'i "yeni" sanıp URL_FILE'a yazabilirdi (canlı doğrulandı, ilk sürümde tam bunu yaptı).
STARTLINE=$(wc -l < "$STATE_DIR/tunnel.log" 2>/dev/null || echo 0)
"$CLOUDFLARED" tunnel --url "http://127.0.0.1:${PORT}" &
CLOUDFLARED_PID=$!
trap 'kill "$CLOUDFLARED_PID" 2>/dev/null' TERM INT

for _ in $(seq 1 40); do
    URL=$(tail -n "+$((STARTLINE + 1))" "$STATE_DIR/tunnel.log" 2>/dev/null \
          | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1)
    [ -n "$URL" ] && { echo "$URL" > "$URL_FILE"; break; }
    sleep 0.5
done
wait "$CLOUDFLARED_PID"
