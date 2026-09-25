#!/usr/bin/env bash
# claudeops -- yeni bir makinede (ör. 10.20.4.31), claudeops'u arkadaşınızın
# KENDİ kişisel hesabından İZOLE, ayrı bir kullanıcının home'una kurmak için.
#
# Kullanım (arkadaşınızın KENDİ hesabında, KENDİ sudo'suyla, bir kerelik):
#   curl -fsSL https://raw.githubusercontent.com/mfyuce/claudeops/main/scripts/provision-user.sh | bash -s claudeops
#   (veya: git clone .../claudeops.git && bash claudeops/scripts/provision-user.sh claudeops)
# İkinci argüman istenirse başka bir kullanıcı adı da olabilir (varsayılan: claudeops).
#
# Ne yapar: git/python3/pip/tmux'u SİSTEM GENELİNDE kurar (bir kerelik sudo,
# arkadaşınızın ZATEN sahip olduğu yetkiyle) -> yeni kullanıcıyı oluşturur
# (`useradd -m`, normal home dizini) -> bootstrap-remote-host.sh'i o kullanıcı
# olarak çalıştırmanız için tam komutu ekrana basar.
#
# Yeni kullanıcıya RASTGELE bir şifre üretilip `chpasswd` ile atanır ve sonda
# BİR KERE ekrana basılır (başka hiçbir yere yazılmaz) -- sadece o an kopyalayıp
# saklayın, script çıktısında bir daha görünmez. Sadece kullanıcı YENİ
# oluşturulduysa üretilir; script tekrar çalıştırılırsa (kullanıcı zaten
# varsa) mevcut şifre DOKUNULMADAN kalır.
#
# BİLEREK YAPMADIĞI: yeni kullanıcıyı admin/sudo grubuna EKLEMEZ, SSH anahtarı
# KURMAZ. claudeops'un kendi çalışması (service install) sudo istemiyor -- tek
# sudo ihtiyacı bu script'in kendisindeki (bir kerelik) paket kurulumu, o da
# arkadaşınızın KENDİ yetkisiyle şimdi yapılıyor. Farklı bir tercihiniz varsa
# (ör. gerçekten admin olsun) bunu elle `usermod -aG sudo <kullanıcı>` ile
# siz/arkadaşınız ekleyebilirsiniz.
set -euo pipefail

NEW_USER="${1:-claudeops}"

if ! [[ "$NEW_USER" =~ ^[a-z][a-z0-9_-]*$ ]]; then
    echo "geçersiz kullanıcı adı: $NEW_USER" >&2
    exit 1
fi

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"

if ! command -v apt-get >/dev/null 2>&1; then
    echo "Bu script apt-get gerektiriyor (Debian/Ubuntu). Farklı bir dağıtımdaysanız" >&2
    echo "git/python3/python3-pip/tmux'u kendi paket yöneticinizle kurup" >&2
    echo "aşağıdaki useradd adımını elle yapın." >&2
    exit 1
fi

echo "=== sistem paketleri (git/python3/python3-pip/tmux) kuruluyor ==="
$SUDO apt-get update
$SUDO apt-get install -y git python3 python3-pip tmux

gen_password() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 18
    else
        tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24
    fi
}

NEW_PASSWORD=""
if id "$NEW_USER" >/dev/null 2>&1; then
    echo "kullanıcı '$NEW_USER' zaten var, oluşturma/şifre adımı atlanıyor (mevcut şifre korunuyor)"
else
    echo "=== '$NEW_USER' kullanıcısı oluşturuluyor (admin/sudo grubuna EKLENMİYOR) ==="
    $SUDO useradd -m -s /bin/bash "$NEW_USER"
    NEW_PASSWORD="$(gen_password)"
    printf '%s:%s\n' "$NEW_USER" "$NEW_PASSWORD" | $SUDO chpasswd
fi

# `loginctl enable-linger` burada, kullanıcı oluşturulur oluşturulmaz (sizin
# sudo'nuzla) çalıştırılıyor -- yoksa `sudo -iu` ile o kullanıcıya geçildiğinde
# systemd --user'ın bus'ı (XDG_RUNTIME_DIR/DBUS_SESSION_BUS_ADDRESS) hiç kurulu
# olmuyor ve `py/cops service install` "Failed to connect to bus" ile patlıyor
# (canlı doğrulandı, 2026-09-25). Linger etkinse logind bu kullanıcı için
# --user instance'ını HEMEN başlatıyor, bir login/logout beklemeye gerek yok.
if command -v loginctl >/dev/null 2>&1; then
    if $SUDO loginctl enable-linger "$NEW_USER" 2>/tmp/claudeops-provision-linger.err; then
        echo "✓ loginctl enable-linger $NEW_USER"
    else
        echo "⚠ loginctl enable-linger başarısız: $(cat /tmp/claudeops-provision-linger.err 2>/dev/null)" >&2
        echo "  (devam ediliyor -- sonraki adımda 'Failed to connect to bus' görürseniz" >&2
        echo "  bunu elle çalıştırıp tekrar deneyin: sudo loginctl enable-linger $NEW_USER)" >&2
    fi
    rm -f /tmp/claudeops-provision-linger.err
fi

echo
echo "=========================================================="
if [ -n "$NEW_PASSWORD" ]; then
    echo "'$NEW_USER' şifresi (SADECE ŞİMDİ gösteriliyor, bir yere kaydedin):"
    echo "  $NEW_PASSWORD"
    echo
fi
echo "Hazır. Şimdi '$NEW_USER' olarak claudeops'u kurup başlatmak için:"
echo
echo "  $SUDO -iu $NEW_USER bash -c 'git clone https://github.com/mfyuce/claudeops.git && bash claudeops/scripts/bootstrap-remote-host.sh'"
echo
echo "(paketler zaten kurulu olduğu için bootstrap script sudo İSTEMEYECEK,"
echo "doğrudan servis kurulumuna geçecek.)"
echo "=========================================================="
