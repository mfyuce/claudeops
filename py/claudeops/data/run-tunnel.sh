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
# URL DEĞİŞTİĞİNDE (daha önce BAŞARIYLA bildirilmiş aynı URL'de sessiz) bildirim:
# ~/.claude/claudeops/ntfy_topic.txt varsa https://ntfy.sh/<topic>'e POST edilir — dosya yoksa
# hiçbir şey yapılmaz (no-op). Gönderim başarısız olursa arka planda yeniden denenir
# (bkz. _notify_retry); her karar tunnel.log'a bir [run-tunnel] satırı olarak düşer.
#
# Quick-tunnel dalında SAĞLIK BEKÇİSİ (bkz. _watch_tunnel, 2026-10-17): genel adres art arda HTTP 530
# verirse (Cloudflare: bu adrese bağlı tünel yok) cloudflared sonlandırılır, systemd 5 sn sonra yeni
# bir tünel açar (YENİ URL + ntfy). Panelden SEÇİMLİK: Ayarlar > Genel > "tünel sağlık bekçisi" =
# settings.json `tunnel_watch` ("on" varsayılan, "off" kapatır); her yoklamada yeniden okunur, yani
# değişiklik tüneli (ve URL'i) yeniden başlatmadan geçerli olur. Ortam: CLAUDEOPS_TUNNEL_WATCH=0 (bekçiyi
# HİÇ başlatma), _WATCH_INTERVAL (60 sn), _WATCH_FAILS (3), _WATCH_GRACE (90 sn).
set -u
TUNNEL_NAME="${CLAUDEOPS_TUNNEL_NAME:-claudeops}"
PORT="${CLAUDEOPS_PORT:-8765}"
STATE_DIR="$HOME/.claude/claudeops"
# İkinci (paralel) bir deploy'un (ör. react-ui denemesi) kendi tunnel URL/log
# dosyasına ihtiyacı var — aynı sabit dosyaları paylaşırsa canlı tünelin
# URL'ini/log'unu ezer ([[tunnel-flag-shares-live-log-file]] dersi). Varsayılan
# (env verilmezse) TAM ESKİSİ GİBİ — mevcut tek-instance kurulum davranışı
# DEĞİŞMEZ, sadece ikinci bir systemd unit'i farklı bir yol geçebiliyor.
URL_FILE="${CLAUDEOPS_TUNNEL_URL_FILE:-$STATE_DIR/tunnel_url.txt}"
LOG_FILE="${CLAUDEOPS_TUNNEL_LOG:-$STATE_DIR/tunnel.log}"
NTFY_TOPIC_FILE="${CLAUDEOPS_NTFY_TOPIC_FILE:-$STATE_DIR/ntfy_topic.txt}"
# En son BAŞARIYLA bildirilen URL. URL_FILE'dan AYRI: URL_FILE her zaman güncel URL'i tutar
# (panel/service status okur), "bildirim gitti mi" bilgisi ise yalnız bu dosyada. İkinci
# (paralel) instance kendi URL_FILE'ını verdiyse bunun da kendi dosyası olur.
NOTIFIED_FILE="$URL_FILE.notified"
# Başarısız ntfy bildirimi bu kadar saniye boyunca yeniden denenir (10, 20, 40 ... en çok 300 sn arayla).
NTFY_RETRY_SECS="${CLAUDEOPS_NTFY_RETRY_SECS:-3600}"
# Bildirim metnine eklenen etiket — birden fazla instance aynı ntfy hesabına
# push atarsa hangi deploy'a ait olduğu telefonda anında görünsün.
TUNNEL_LABEL="${CLAUDEOPS_TUNNEL_LABEL:-}"
# Bazı ağlar (ör. kısıtlı/kurumsal firewall'lar) cloudflared'ın varsayılan QUIC
# (UDP) taşımasını engelliyor — "failed to dial to edge with quic: timeout"
# döngüsüyle tünel HİÇ kurulamıyor (canlı bulundu, 2026-09-07, yuhem). Boşsa
# cloudflared'ın kendi varsayılanı (quic dener, gerekirse düşer) DEĞİŞMEZ;
# "http2" verilirse TCP/443 üzerinden zorlanır, kısıtlı ağlarda çalışan çözüm.
TUNNEL_PROTOCOL="${CLAUDEOPS_TUNNEL_PROTOCOL:-}"
PROTOCOL_ARGS=()
[ -n "$TUNNEL_PROTOCOL" ] && PROTOCOL_ARGS=(--protocol "$TUNNEL_PROTOCOL")
# Sağlık bekçisi ayarları (bkz. _watch_tunnel). WATCH=0/off kapatır; YALNIZ quick-tunnel dalında çalışır.
WATCH="${CLAUDEOPS_TUNNEL_WATCH:-1}"
WATCH_INTERVAL="${CLAUDEOPS_TUNNEL_WATCH_INTERVAL:-60}"
WATCH_FAILS="${CLAUDEOPS_TUNNEL_WATCH_FAILS:-3}"
WATCH_GRACE="${CLAUDEOPS_TUNNEL_WATCH_GRACE:-90}"
# Bekçinin Ayarlar'daki açma/kapama anahtarını okuduğu dosya (panelin settings.json'ı).
SETTINGS_FILE="${CLAUDEOPS_SETTINGS_FILE:-$STATE_DIR/settings.json}"
CLOUDFLARED="$HOME/.local/bin/cloudflared"
command -v "$CLOUDFLARED" >/dev/null 2>&1 || CLOUDFLARED="cloudflared"
mkdir -p "$STATE_DIR"

# ntfy bildirimi TEK ATIŞ olamaz: 2026-10-12 08:02'de reboot sonrası ağ dengesizken 10 sn'lik tek
# `curl` düştü, bir daha denenmedi ve telefona hiç bildirim gitmedi. Başarısız olursa üstel
# geri çekilmeyle (10, 20, 40 ... en çok 300 sn arayla) NTFY_RETRY_SECS boyunca tekrar dener.
# Arka planda çalışır (cloudflared'ı beklemeyi bloklamasın); unit'in cgroup'unda kaldığı için
# unit durunca/yeniden başlayınca systemd onu da sonlandırır.
_notify_retry() {
    local url="$1" topic prefix note waited=0 delay=10 attempt=1
    prefix="claudeops tunnel"
    [ -n "$TUNNEL_LABEL" ] && prefix="claudeops [$TUNNEL_LABEL] tunnel"
    while :; do
        # Topic her denemede yeniden okunur: bekleme sürerken `service notify --off`
        # (dosyayı siler) çalıştırılırsa bekleyen bildirim de iptal olur.
        topic=$(cat "$NTFY_TOPIC_FILE" 2>/dev/null || true)
        [ -n "$topic" ] || return 0
        if curl -fsS -m 10 -d "$prefix: $url" "https://ntfy.sh/${topic}" >/dev/null 2>&1; then
            echo "$url" > "$NOTIFIED_FILE"
            note=""
            [ "$attempt" -gt 1 ] && note=" (deneme $attempt)"
            echo "[run-tunnel] bildirim gönderildi (ntfy.sh/${topic})$note"
            return 0
        fi
        if [ "$waited" -ge "$NTFY_RETRY_SECS" ]; then
            echo "[run-tunnel] ⚠ ntfy bildirimi başarısız: $NTFY_RETRY_SECS sn boyunca gönderilemedi ($attempt deneme), vazgeçildi"
            return 1
        fi
        [ "$attempt" -eq 1 ] && echo "[run-tunnel] ⚠ ntfy bildirimi başarısız (ağ/topic sorunu olabilir), yeniden denenecek"
        sleep "$delay"
        waited=$((waited + delay))
        delay=$((delay * 2))
        [ "$delay" -gt 300 ] && delay=300
        attempt=$((attempt + 1))
    done
}

# Yeni URL'i URL_FILE'a yazar (HER ZAMAN; panel/service status oradan okur) ve bu URL daha önce
# BAŞARIYLA bildirilmediyse (topic varsa) arka planda bildirir. Aynı URL'de sessiz kalmak önemli:
# ör. named-tunnel modunda her restart'ta aynı sabit hostname'i "değişti" sanıp gereksiz bildirim
# atmamalı. Her dalda tunnel.log'a bir satır düşer; sessizlik "neden bildirim gelmedi?" sorusunu
# log'dan cevaplanamaz bırakıyordu.
_write_url_and_notify() {
    local new_url="$1"
    echo "$new_url" > "$URL_FILE"
    if [ "$new_url" = "$(cat "$NOTIFIED_FILE" 2>/dev/null || true)" ]; then
        echo "[run-tunnel] URL daha önce bildirilmişti, bildirim atlandı"
    elif [ ! -s "$NTFY_TOPIC_FILE" ]; then
        echo "[run-tunnel] ntfy kapalı (topic dosyası yok/boş), bildirim atlandı"
    else
        # Çift fork: iş script'ten kopar. Named-tunnel dalındaki `exec`ten sonra da cloudflared'ın
        # altında bitmiş-ama-toplanmamış (zombi) çocuk olarak asılı kalmaz.
        ( _notify_retry "$new_url" & )
    fi
}

# Bekçinin Ayarlar'dan seçimli açma/kapama anahtarı: settings.json `tunnel_watch` ("on" varsayılan;
# off/0/false/no/n/hayir/kapali/disabled/none kapatır, `settings.py::_OFF_WORDS` ile AYNI küme, bir test
# ikisinin eşit kaldığını denetler). Dosya yok/bozuk/python3 yok/anahtar yok/tanınmayan değer = AÇIK.
_watch_enabled() {
    local v
    v=$(python3 -c '
import json, sys
try:
    v = json.load(open(sys.argv[1])).get("tunnel_watch", "on")
except Exception:
    v = "on"
print("on" if v is None else str(v).strip().lower())
' "$SETTINGS_FILE" 2>/dev/null) || v=on
    case "$v" in
        off|0|false|no|n|hayir|hayır|kapali|kapalı|disabled|none) return 1 ;;
    esac
    return 0
}

# Quick tunnel kopunca cloudflared kendiliğinden yeni tünel İSTEMİYOR: süreç canlı kalıp genel adres
# HTTP 530 vermeye devam ediyor ve systemd `Restart=always` yalnız süreç ÖLÜNCE devreye giriyor
# (2026-10-17 13:11: makinenin DNS sorgusu zaman aşımına uğradı, tünel 15 dk sessizce ölü kaldı,
# servis "active" göründü). Bekçi genel adresi her WATCH_INTERVAL sn'de yoklar; ART ARDA WATCH_FAILS
# kez HTTP 530 görürse cloudflared'ı sonlandırır: script `wait`ten çıkar, systemd yeni tüneli açar.
# YALNIZ 530 ölü sayılır: 502/503/504 panelin (origin) yeniden başlamasıdır, 000 (curl ağa/DNS'e
# ulaşamadı) yerel ağ sorunudur (makinenin çözümleyicisi aralıklı zaman aşımı veriyor); tüneli yeniden
# açmak ikisini de düzeltmez, boşuna URL değiştirirdi. 000 sayacı SIFIRLAMAZ ve ARTIRMAZ (kopuk tünel +
# dalgalı DNS'te teşhis gecikmesin); başka her yanıt (401 panel kimlik doğrulaması dahil) sıfırlar.
# İlk yoklamadan önce WATCH_GRACE sn beklenir (yeni tünelin adresi hemen yayılmayabilir).
_watch_tunnel() {
    local url="$1" pid="$2" fails=0 code enabled=1
    sleep "$WATCH_GRACE"
    while kill -0 "$pid" 2>/dev/null; do
        # Anahtar HER turda okunur: Ayarlar'dan değişiklik tüneli yeniden başlatmadan (URL değişmeden) geçerli olur.
        if _watch_enabled; then
            [ "$enabled" = 0 ] && echo "[run-tunnel] sağlık bekçisi: Ayarlar'dan AÇILDI"
            enabled=1
            code=$(curl -s -m 15 -o /dev/null -w '%{http_code}' "$url/" 2>/dev/null || true)
            case "$code" in
                530)
                    fails=$((fails + 1))
                    [ "$fails" -eq 1 ] && echo "[run-tunnel] ⚠ sağlık bekçisi: $url HTTP 530 veriyor (tünel bağlı değil)"
                    if [ "$fails" -ge "$WATCH_FAILS" ]; then
                        echo "[run-tunnel] ⚠ sağlık bekçisi: $fails yoklamadır HTTP 530, cloudflared sonlandırılıyor (systemd yeni tünel açacak)"
                        kill "$pid" 2>/dev/null
                        return 0
                    fi
                    ;;
                000|"") : ;;
                *)
                    [ "$fails" -gt 0 ] && echo "[run-tunnel] sağlık bekçisi: $url yeniden yanıt veriyor (HTTP $code)"
                    fails=0
                    ;;
            esac
        else
            [ "$enabled" = 1 ] && echo "[run-tunnel] sağlık bekçisi: Ayarlar'dan KAPATILDI (yoklama durdu)"
            enabled=0
            fails=0
        fi
        sleep "$WATCH_INTERVAL"
    done
}

if "$CLOUDFLARED" tunnel list 2>/dev/null | awk '{print $2}' | grep -qx "$TUNNEL_NAME"; then
    echo "[run-tunnel] named tunnel '$TUNNEL_NAME' bulundu — sabit URL kullanılıyor"
    # Sabit hostname'i (kurulum sırasında elle yazılır, bkz. README) URL_FILE'a yansıt.
    if [ -f "$STATE_DIR/tunnel_fixed_hostname.txt" ]; then
        _write_url_and_notify "$(cat "$STATE_DIR/tunnel_fixed_hostname.txt")"
    fi
    exec "$CLOUDFLARED" tunnel "${PROTOCOL_ARGS[@]}" run "$TUNNEL_NAME"
fi

echo "[run-tunnel] named tunnel yok — quick-tunnel (rastgele URL) başlatılıyor"
# LOG_FILE APPEND modunda (systemd StandardOutput=append:...) — eski çalıştırmalardan
# kalma bir önceki (artık ÖLÜ) URL hâlâ dosyada duruyor olabilir. Bu run'dan ÖNCEKİ satır
# sayısını kaydedip SADECE ondan SONRA eklenen satırlarda arıyoruz, yoksa `tail -1` stale
# URL'i "yeni" sanıp URL_FILE'a yazabilirdi (canlı doğrulandı, ilk sürümde tam bunu yaptı).
STARTLINE=$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)
"$CLOUDFLARED" tunnel "${PROTOCOL_ARGS[@]}" --url "http://127.0.0.1:${PORT}" &
CLOUDFLARED_PID=$!
trap 'kill "$CLOUDFLARED_PID" 2>/dev/null' TERM INT

for _ in $(seq 1 40); do
    # Canlılık TARAMADAN ÖNCE ölçülür: süreç ölmüşse taramanın göreceği çıktı artık son çıktıdır,
    # arada bir URL kaçırma yarışı olmaz.
    alive=1
    kill -0 "$CLOUDFLARED_PID" 2>/dev/null || alive=0
    # `api.trycloudflare.com` quick-tunnel API'sinin KENDİ adresidir: cloudflared'ın HATA satırında
    # ("failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": ...") geçer,
    # tünel URL'i DEĞİLDİR. Ayıklanmazsa başarısız her açılışta URL_FILE'a sahte adres yazılıp
    # (ağ varsa) telefona yanlış link bildiriliyordu (2026-10-12, aynı gün 3 açılışta log'da görüldü).
    URL=$(tail -n "+$((STARTLINE + 1))" "$LOG_FILE" 2>/dev/null \
          | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | grep -v '^https://api\.' | tail -1)
    if [ -n "$URL" ]; then
        _write_url_and_notify "$URL"
        break
    fi
    # cloudflared URL basmadan öldüyse (ağ yok: "failed to request quick Tunnel") 20 sn boşuna
    # yoklama; hemen çık ki systemd (RestartSec=5) yeniden başlatsın. Sahte api URL'i bu yüzden
    # eskiden döngüyü KAZAYLA kısa kesiyordu; regex düzelince bu çıkış açıkça gerekti.
    [ "$alive" = 1 ] || break
    sleep 0.5
done
# Bekçi yalnız URL biliniyorsa başlar (yoklanacak adres yok demek). Çift fork (_notify_retry gibi):
# iş script'ten kopar; cloudflared ölünce `kill -0` döngüyü bitirir.
if [ -n "${URL:-}" ] && [ "$WATCH" != 0 ] && [ "$WATCH" != off ]; then
    ( _watch_tunnel "$URL" "$CLOUDFLARED_PID" & )
fi
wait "$CLOUDFLARED_PID"
