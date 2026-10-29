"""tmux-backed sessions — dedicated socket ("-L cops"), isolated from any other
tmux usage on the machine.

Every helper here is best-effort: on any failure (tmux missing, session gone,
subprocess timeout) it returns None/False/[] rather than raising — a hung/missing
tmux must never hang or crash a caller, especially once capture/send-keys is
polled every ~150-250ms from a ThreadingHTTPServer request thread ([[tmux-backed
web CLI plan]]).
"""
from __future__ import annotations
import os
import re
import shlex
import shutil
import subprocess
import termios
import time
from pathlib import Path
from typing import List, Optional

TMUX_SOCKET = "cops"
_TIMEOUT = 5.0
_ANCESTOR_WALK_LIMIT = 6


def tmux_available() -> bool:
    return shutil.which("tmux") is not None


def tmux_conf_path() -> str:
    return str(Path(__file__).resolve().parent / "data" / "tmux.conf")


def _base_argv() -> List[str]:
    return ["tmux", "-L", TMUX_SOCKET]


def _exact(name: str) -> str:
    """Force tmux's `-t` target to EXACT-match `name`, never its unique-prefix
    fallback. Without this, a bare name that no longer has a live session
    (e.g. the pane's process was just killed and remain-on-exit=off already
    tore the session down) makes tmux fall back to matching any session whose
    name STARTS WITH it — exactly what `_generate_new_chat_name`'s `_1`/`_2`
    collision suffixes produce (`dccl20260917` + `dccl20260917_1`). 2026-09-17
    live incident: stopping the shorter-named session also killed the longer
    one via this fallback in `kill-session -t <name>`.

    `=name` alone is enough for session-target commands (`has-session`,
    `kill-session`) but pane-target commands (`capture-pane`, `send-keys`,
    `list-panes`, `list-clients`, `display-message`) parse `-t` as
    `session:window.pane` and fail outright on a bare `=name` ("can't find
    pane") — a trailing `:` (session, default window/pane) resolves on both,
    confirmed against disposable tmux sessions for every call site below."""
    return f"={name}:"


def tmux_new_session_shell_fragment(name: str, cwd: str, inner: str) -> str:
    """Bash-fragment (NOT executed here) spawn.py splices into its gnome-terminal
    command: `tmux -L cops -f <conf> new-session -A -s NAME -c CWD -x 100 -y 30 INNER`.

    -A = attach-if-exists-else-create (idempotent — safe to reopen the same window
    without creating a duplicate session). `inner` is spawn.py's own already
    shlex-quoted command string; shlex.quote nests safely over it.
    """
    return (
        f"{shlex.join(_base_argv())} -f {shlex.quote(tmux_conf_path())} "
        f"new-session -A -s {shlex.quote(name)} -c {shlex.quote(cwd)} "
        f"-x 100 -y 30 {shlex.quote(inner)}"
    )


def tmux_attach_shell_fragment(name: str) -> str:
    """Bash-fragment (NOT executed here) spawn.py splices into a gnome-terminal
    command to bind a NEW window to an EXISTING tmux session, without touching
    the CLI process inside it (used by spawn.py's `open_window` — the one-click
    fix for a session that ended up windowless)."""
    return f"{shlex.join(_base_argv())} -f {shlex.quote(tmux_conf_path())} attach-session -t {shlex.quote(name)}"


def tmux_spawn_direct(name: str, cwd: str, inner: str, env: dict) -> bool:
    """gnome-terminal'siz DOĞRUDAN tmux session aç — spawn.py'nin gnome-terminal
    fallback'ı ([[spawn-zombie-child-degrades-web-server]], gnome-terminal-server
    kendi D-Bus state'iyle bozulunca hiç pencere açmıyor, sessizce). `-A` sayesinde
    idempotent: session zaten varsa (gnome-terminal aslında başarmış, biz sadece
    geç kontrol ettiysek) no-op — ikinci bir claude başlatmaz.

    `inner` TEK bir argv elemanı olarak geçiriliyor (subprocess shell=False) — tmux
    bunu kendi `$SHELL -c` çağrısına verir, `tmux_new_session_shell_fragment`'ın
    dolaylı yolunun (outer bash -c → bu fragment) ürettiğiyle AYNI tek-geçişli
    shell-parse sonucunu verir, çift-quote uyumsuzluğu olmaz."""
    cmd = _base_argv() + [
        "-f", tmux_conf_path(), "new-session", "-d", "-A",
        "-s", name, "-c", cwd, "-x", "100", "-y", "30",
        f"{inner}; exec bash",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT, env=env)
        return r.returncode == 0
    except Exception:
        return False


def tmux_has_session(name: str) -> bool:
    try:
        r = subprocess.run(_base_argv() + ["has-session", "-t", _exact(name)],
                            capture_output=True, timeout=_TIMEOUT)
        return r.returncode == 0
    except Exception:
        return False


def tmux_capture(name: str, lines: int = 2000) -> Optional[str]:
    try:
        r = subprocess.run(
            _base_argv() + ["capture-pane", "-t", _exact(name), "-e", "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if r.returncode != 0:
            return None
        return r.stdout
    except Exception:
        return None


def tmux_capture_range(name: str, start: int, end: int) -> Optional[str]:
    """`capture-pane -S start -E end`: pane'in KÜÇÜK bir aralığı (mirror'ın geçmişte kaydırması, TBD#79).

    tmux satır numaraları: 0 = görünür alanın ilk satırı, `rows-1` = son görünür satır; negatifler scrollback
    (-1 en yeni geçmiş satırı, `-history_size` en eskisi). `tmux_capture`ın aksine 2000 satırın tamamını çekmez:
    çıktı `end-start+1` satırdır, her satır "\n" ile biter ve `-e` ile renklidir. Hata (oturum yok) → None.
    `-S`/`-E` değerleri `int()`e zorlanır: argv'ye başka hiçbir şey sızamaz."""
    try:
        r = subprocess.run(
            _base_argv() + ["capture-pane", "-t", _exact(name), "-e", "-p", "-S", str(int(start)), "-E", str(int(end))],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if r.returncode != 0:
            return None
        return r.stdout
    except Exception:
        return None


# `tmux capture-pane -e` ANSI'yi KORUR ve claude'un durum çubuğunu/dialoglarını
# kelime kelime renklendirir — ham metinde "Switch model?" aslında
# `\x1b[1m\x1b[38;5;220mSwitch\x1b[0m\x1b[39m\x1b[49m \x1b[1m\x1b[38;5;220mmodel?...`
# olarak duruyor, yani düz bir substring/regex ASLA eşleşmez ([[web.py'nin
# mode-durumu tespiti 2026-09-08'de AYNI sınıf bug'ı yaşadı ve buraya taşındı]]).
# Eşleştirmeden önce mutlaka ANSI temizlenmeli — frontend'in `stripAnsi`'siyle
# aynı iki desen (SGR + OSC).
ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
ANSI_OSC_RE = re.compile(r"\x1b\][^\x07]*\x07")


def strip_ansi(text: str) -> str:
    return ANSI_OSC_RE.sub("", ANSI_SGR_RE.sub("", text))


def tmux_send_keys(name: str, text: str, settle_delay: float = 0.0) -> bool:
    """`settle_delay` — literal metni gönderdikten SONRA, Enter'ı göndermeden
    ÖNCE bekle (saniye). Varsayılan 0.0: claude/agy/shell zaten anlık Enter'ı
    doğru işliyor. codex GEREKTİRİYOR (2026-09-05, canlı bulundu: literal metin +
    AYNI anda ayrı bir Enter kombinasyonu mesajı input kutusunda gönderilmemiş
    bırakıyor — codex bunu ikinci, gecikmeli bir Enter'la işliyor, muhtemelen
    kendi input-render döngüsünün metni "görmesi" için bir an gerektirdiği için;
    150ms hem tek-satır hem çok-satırlı/Türkçe-karakterli mesajlarla izole bir
    tmux-only test session'ında güvenilir şekilde doğrulandı). Çağıran taraf
    `CliProvider.input_settle_delay()` ile provider-bazlı değeri geçer — burada
    `if cli==...` YOK, sadece parametrenin kendisi."""
    # Uzun metin (beyin turu ~10-25 KB) TUI'de yapıştırma işlenirken tmux'u 5 sn'den uzun tutabilir: zaman aşımı metni
    # yazılmış ama Enter'sız bırakıyordu (kutuda "[Pasted text]" birikiyor, sonraki turlar hep başarısız). Süre metinle büyür.
    timeout = max(_TIMEOUT, 5.0 + len(text) / 1500.0)
    try:
        # `--` ZORUNLU (`tmux_send_raw`'daki AYNI tuzak, burada 2026-09-14'e
        # kadar eksikti — bilinen açık bug, bkz. TODO.md): `--` olmadan tire
        # ile başlayan literal metin ("-help", "--foo", markdown "- item",
        # unified diff "--- a/file") tmux'un KENDİ `send-keys` bayrağı sanılıp
        # `unknown option` ile reddediliyordu, girdi pane'e HİÇ ulaşmıyordu.
        r1 = subprocess.run(_base_argv() + ["send-keys", "-t", _exact(name), "-l", "--", text],
                             capture_output=True, timeout=timeout)
        if r1.returncode != 0:
            return False
        if settle_delay > 0:
            time.sleep(settle_delay)
        r2 = subprocess.run(_base_argv() + ["send-keys", "-t", _exact(name), "Enter"],
                             capture_output=True, timeout=_TIMEOUT)
        return r2.returncode == 0
    except Exception:
        return False


# Only these key-names may go through non-literal send-keys (never pass arbitrary
# strings this way — literal text always goes through tmux_send_keys's `-l` path).
ALLOWED_SPECIAL_KEYS = {"C-c", "C-d", "Escape", "Up", "Down", "Left", "Right", "Tab", "Enter", "BTab"}


RESIZE_COLS = (20, 500)
RESIZE_ROWS = (5, 200)


def tmux_resize_window(name: str, cols: int, rows: int) -> bool:
    """Oturumun pencere boyutunu `cols x rows` yapar (`resize-window -x -y`, tmux >= 2.9). tmux 3.1+ bunu pencereyi
    `window-size manual` yapar: işi bitince `tmux_release_size` ŞART (yoksa sonradan bağlanan istemci boyutu
    değiştiremez). Bağlı istemci olan oturumda ÇAĞIRMA (çağıran `tmux_client_count` ile eler). Sınır dışı değer reddedilir."""
    if not (RESIZE_COLS[0] <= cols <= RESIZE_COLS[1] and RESIZE_ROWS[0] <= rows <= RESIZE_ROWS[1]):
        return False
    try:
        r = subprocess.run(_base_argv() + ["resize-window", "-t", _exact(name), "-x", str(cols), "-y", str(rows)],
                            capture_output=True, timeout=_TIMEOUT)
        return r.returncode == 0
    except Exception:
        return False


def tmux_release_size(name: str) -> bool:
    """`tmux_resize_window`un bıraktığı elle boyutu geri alır: pencerenin `window-size` seçeneğini kaldırır (genel
    `latest`e döner); boyutun kendisi yerinde kalır, sonraki istemci bağlanınca tmux normal şekilde ayarlar.
    `window-size` seçeneği yoksa (tmux 3.0a) hata verir ve zararsızdır: False döner."""
    try:
        r = subprocess.run(_base_argv() + ["set-option", "-wu", "-t", _exact(name), "window-size"],
                            capture_output=True, timeout=_TIMEOUT)
        return r.returncode == 0
    except Exception:
        return False


def tmux_send_special_key(name: str, key: str) -> bool:
    if key not in ALLOWED_SPECIAL_KEYS:
        return False
    try:
        r = subprocess.run(_base_argv() + ["send-keys", "-t", _exact(name), key],
                            capture_output=True, timeout=_TIMEOUT)
        return r.returncode == 0
    except Exception:
        return False


# Tek bir `send-keys -l` çağrısında gönderilen en fazla karakter — `argv`
# sınırına (yüzlerce KB) göre fazlasıyla muhafazakâr; 5000 karakterlik tek
# parça izole testte sorunsuz geçti, bu yüzden bölme SADECE bir güvenlik
# marjı, davranışsal bir gereklilik değil.
_RAW_CHUNK_CHARS = 2000


def tmux_send_raw(name: str, data: str) -> bool:
    """xterm.js'in `onData`'sından gelen HAM tuş verisini pane'e OLDUĞU GİBİ
    iletir — Terminal görünümünün "canlı yazma" modu için (kullanıcı siyah
    terminal alanına doğrudan yazıyor, alttaki komut kutusuna değil).

    `tmux_send_keys`'ten iki farkı var: (1) sonuna Enter EKLEMEZ — Enter'ın
    kendisi zaten veri içinde `\\r` olarak gelir, (2) tek bir "mesaj" değil,
    tuş vuruşu/kontrol dizisi/yapıştırma bloğu taşır.

    tmux 3.2a'da izole bir scratch pane'e (raw-mode okuyan bir python) karşı
    doğrulandı: `send-keys -l` ham baytları (0x03, `ESC [ A`, çok baytlı UTF-8
    `şğüİ`) HİÇ dokunmadan geçiriyor ve ters-bölü kaçışlarını YORUMLAMIYOR
    (`a\\nb` literal olarak `a\\nb` gidiyor). İki gerçek tuzak da orada
    bulundu: `--` ZORUNLU (tire ile başlayan bir parça — kullanıcının yazdığı
    düz bir `-` bile — aksi halde `tmux: unknown option` ile ölür) ve NUL
    baytı argv'den geçemez (Ctrl+Space) — sessizce atılır, tuş vuruşunun
    tamamını başarısız saymaktansa o tek karakteri kaybetmek yeğdir."""
    data = data.replace("\x00", "")
    if not data:
        return True
    try:
        for i in range(0, len(data), _RAW_CHUNK_CHARS):
            chunk = data[i:i + _RAW_CHUNK_CHARS]
            r = subprocess.run(_base_argv() + ["send-keys", "-t", _exact(name), "-l", "--", chunk],
                                capture_output=True, timeout=_TIMEOUT)
            if r.returncode != 0:
                return False
        return True
    except Exception:
        return False


def tmux_client_count(name: str) -> Optional[int]:
    """`name` session'ına ŞU AN kaç terminal istemcisi bağlı (0 = penceresiz).
    Hata/tmux yok → None ("bilinmiyor", 0 DEĞİL — 0 "kesinlikle penceresiz"
    demek ve panelde uyarı üretiyor, tahminle üretilmemeli).

    Pencere var mı sorusunun DOĞRU kaynağı budur; pencere BAŞLIĞINA bakmak
    değil: başlık `set-titles-string "#S"` ile session adına ayarlanıyor ama
    pencere yeni açılmışken (VTE başlığı henüz almamışken) ya da CLI'ın kendi
    TUI'si başlığı eski bir adda bıraktığında ([[stale-tui-title-cross-suffix-
    resume]]) eşleşme kaçıyor → penceresi OLAN session "penceresiz" görünüyor."""
    try:
        r = subprocess.run(_base_argv() + ["list-clients", "-t", _exact(name), "-F", "#{client_tty}"],
                            capture_output=True, text=True, timeout=_TIMEOUT)
        if r.returncode != 0:
            # session yoksa tmux da hata döner — "bilinmiyor" demek doğru
            return None
        return len([ln for ln in r.stdout.splitlines() if ln.strip()])
    except Exception:
        return None


def tmux_client_session(client: str) -> Optional[str]:
    """`client` (tmux istemci adı, ör. `/dev/pts/105`; tmux.conf'ta `#{client_name}`) şu an hangi session'a bağlı.

    tmux şerit menüsü (data/tmux-strip.conf) `winact`a oturum adını DEĞİL istemci adını verir: display-menu öğe
    komutlarındaki biçimleri önce genişletip sonra yeniden ayrıştırır, serbest bir oturum adı (`we'ird name`)
    tırnakları bozar. İstemci adı `/dev/pts/N` gibi güvenli karakterlerdir; ad buradan tmux'tan VERİ olarak okunur.
    `list-clients -F` ile tam eşleşme aranır (`display-message -c` 3.2a'da hiç çalışmıyor, aşağıya bkz.).
    Bulunamazsa / tmux yoksa None."""
    if not client or client.startswith("-"):
        return None
    try:
        r = subprocess.run(_base_argv() + ["list-clients", "-F", "#{client_name}\t#{client_session}"],
                           capture_output=True, text=True, timeout=_TIMEOUT)
        if r.returncode != 0:
            return None
        for line in r.stdout.splitlines():
            name, sep, session = line.partition("\t")
            if sep and name == client and session:
                return session
    except Exception:
        pass
    return None


def tmux_message(client: str, text: str, ms: int = 4000) -> bool:
    """`client`ın bağlı olduğu session'ın istemcisinin alt satırında `ms` milisaniye tek satırlık mesaj gösterir
    (display-message). Ham metin güvenli: `#` ikilenir (tmux biçim genişletmesi: panelden gelen bir hata metnindeki
    `#(komut)` KABUKTA çalışırdı), satır sonları boşluğa çevrilir, sondaki `;` atılır (`;` ile biten argv elemanı tmux
    komut ayıracıdır, bkz. CLAUDE.md), baştaki `-` bayrak olmasın diye boşlukla korunur.

    HEDEF `-t =<session>:`, `-c <istemci>` DEĞİL: tmux 3.2a'da `display-message -c` HİÇ çalışmıyor (getopt dizgesinde `c:` yok,
    usage metni `-c`yi listelese de her kullanımı "usage:" ile reddediliyor; gerçek tmux'a karşı denendi, mock'lu birim test
    bunu göremezdi). `-t` ile mesaj session'ın en son etkin istemcisinde görünür; menüyü açan kişi odur.
    `-d` (süre) tmux 3.2+; eskisinde süresiz denenir. Hata/yok/istemci gitmiş → False."""
    session = tmux_client_session(client)
    if not session:
        return False
    safe = " ".join(text.replace("#", "##").split())
    safe = safe.rstrip(";").rstrip() or "…"
    if safe.startswith("-"):
        safe = " " + safe
    for extra in (["-d", str(int(ms))], []):
        try:
            r = subprocess.run(_base_argv() + ["display-message", *extra, "-t", _exact(session), safe],
                               capture_output=True, timeout=_TIMEOUT)
        except Exception:
            return False
        if r.returncode == 0:
            return True
    return False


# tmux.conf'un `history-limit`'iyle AYNI değer, KASITLI pinlenmiş (bkz. o
# dosyadaki yorum) — pane'in scrollback'i bu sayıya ulaşınca tmux eski
# satırları SESSİZCE eviction'a uğratır, ring buffer bunun üstüne asla
# çıkmaz. Terminal view'ın satır-sayısı göstergesi (2026-09-14) bu sabiti
# `#{history_size}`'a karşı oranlamak için kullanır.
HISTORY_LIMIT = 2000


def tmux_pane_size(name: str) -> Optional[tuple]:
    """Panelin GERÇEK boyutu — new-session'daki -x/-y sadece istemci hiç bağlanmamışsa
    geçerli; attach eden bir client (bizim gnome-terminal penceremiz) varsa tmux paneli
    o client'ın gerçek boyutuna göre yeniden boyutlandırır (örn. -x 100 -y 30 istense
    bile pencere gerçekte 211x23 olabilir) — xterm.js'in doğru sarmalama/hizalama
    göstermesi için gerçek boyutu döndürüp frontend'in `term.resize()` çağırması gerekir.

    Üçüncü değer `history_size` (`#{history_size}`) — pane'in ŞU ANKİ gerçek
    scrollback satır sayısı (tmux'un kendi ring buffer'ı, `HISTORY_LIMIT`'te
    tavan yapar). AYNI `list-panes` çağrısına eklendi (2026-09-14) — ayrı bir
    subprocess GEREKMEDİ, tek çağıran (`_term_output`, zaten 200ms'de bir
    poll'lanıyor) ikisini birden bedavaya alır.

    Dördüncü değer `alternate_on` (`#{alternate_on}`, 0/1 → bool) — pane ALTERNATE
    SCREEN BUFFER'da mı (vim/htop/less gibi tam-ekran programların, VE Claude/agy/
    codex'in normal interaktif TUI modunun kullandığı mod). tmux (evrensel terminal
    davranışı) alternate-screen'e yazılanı normal scrollback'e HİÇ eklemez — yani bu
    moddayken `history_size` YAPISAL olarak ~0'da donar, gerçek konuşma/iş hacminden
    tamamen bağımsız (TODO.md 2026-09-29, oiso/ulak_31 canlı doğrulaması: 100×30 gibi
    tamamen normal bir pane'de bile `hist=0`). AYNI `list-panes` çağrısına eklendi,
    yine ekstra subprocess YOK — çağıranın `history_size`'ı alternate-screen'deyken
    yanıltıcı (sürekli "0/2000") göstermek yerine gizlemesi/farklı yorumlaması için."""
    try:
        r = subprocess.run(
            _base_argv() + ["list-panes", "-t", _exact(name),
                             "-F", "#{pane_width} #{pane_height} #{history_size} #{alternate_on}"],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        w, h, hist, alt = r.stdout.strip().splitlines()[0].split()
        return int(w), int(h), int(hist), bool(int(alt))
    except Exception:
        return None


def pane_is_masked_input(name: str) -> Optional[bool]:
    """Pane şu an gizli-girdi (parola/getpass tarzı) mi bekliyor? Kernel ECHO
    bayrağı TEK BAŞINA güvenilir değil — interaktif shell/readline zaten
    ECHO'yu kendi karakter-editörü için sürekli KAPALI tutuyor (izole testte
    doğrulandı, 2026-09-08), yani "echo kapalı" normal komut satırında da hep
    true çıkar. Ayırt edici olan ICANON+ECHO KOMBİNASYONU: normal
    shell/readline `-icanon -echo` (raw, kendi echo'sunu kendi basar), ama
    sudo/getpass-tarzı parola okuma `icanon -echo` (cooked mode + echo kapalı)
    — bu kombinasyon hem Python `getpass.getpass()` hem gerçek `sudo`'ya karşı
    izole bir tmux pane'inde ayrı ayrı doğrulandı."""
    try:
        r = subprocess.run(
            _base_argv() + ["display-message", "-p", "-t", _exact(name), "#{pane_tty}"],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if r.returncode != 0:
            return None
        return tty_is_masked(r.stdout.strip())
    except Exception:
        return None


def tty_is_masked(pty_path: str) -> Optional[bool]:
    """`pane_is_masked_input`'un ikinci yarısı: pane'in pty'sine bakıp parola istemi mi diye karar verir (ICANON
    açık + ECHO kapalı). `pty_path` boş/açılamaz → None. Yolu zaten bilen çağıran (`tmux_pane_snapshot` aynı
    çağrıda `#{pane_tty}` de verir) ek bir tmux süreci başlatmadan kullanır."""
    if not pty_path:
        return None
    try:
        # O_NOCTTY — TODO.md K-02: açık `open(pty_path,"r")` bu slave pty'yi
        # (pane_tty, tmux SERVER'ın tuttuğu master'a karşılık gelir) bu
        # sürecin controlling terminal'i edinmesine yol açabiliyordu (bu süreç
        # systemd --user altında ctty'siz bir session leader — `ps -o sid`
        # ile pid==sid doğrulandı). Edinilince, O ÖZEL tmux session'ı
        # kapandığında kernel bu sürece SIGHUP gönderiyor — sandbox'ta 2 kez +
        # bağımsız bir review turunda 3. kez tekrar üretildi (fable
        # 2026100321270920.md). O_NOCTTY bu edinimi baştan engeller; fonksiyon
        # zaten salt-okunur bir tcgetattr çağrısı, davranış değişmiyor.
        fd = os.open(pty_path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            lflag = termios.tcgetattr(fd)[3]
        finally:
            os.close(fd)
        return bool(lflag & termios.ICANON) and not bool(lflag & termios.ECHO)
    except Exception:
        return None


# `tmux_pane_snapshot`'ın tek çağrıdaki biçimi: boşlukla ayrılmış dört sayı + pty yolu (pty boş olabilir).
_SNAPSHOT_FORMAT = "#{pane_width} #{pane_height} #{history_size} #{alternate_on} #{pane_tty}"


_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
_ANSI_ANY_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_BOX_RULE_CHARS = "\u2500"         # ─
_PROMPT_CHAR = "\u276f"            # ❯ (Claude TUI giriş kutusu istemi)


def _is_dim_fg(params: List[int], cur_dim: bool) -> Optional[bool]:
    """SGR parametrelerinden "soluk/gri" ön plan durumu: True gri/soluk, False varsayılan ya da renkli, None değişmedi."""
    if not params:
        return False
    state: Optional[bool] = None
    i = 0
    while i < len(params):
        p = params[i]
        if p in (0, 22, 39):
            state = False
        elif p in (2, 90):
            state = True
        elif p == 38 and i + 2 < len(params) and params[i + 1] == 5:
            state = 232 <= params[i + 2] <= 252 or params[i + 2] in (8, 59, 102, 145)     # gri tonlar (öneri/yer tutucu)
            i += 2
        elif 30 <= p <= 37 or 91 <= p <= 97:
            state = False
        i += 1
    return state


def typed_input_in_box(ansi_text: str) -> Optional[bool]:
    """Claude TUI giriş kutusunda KULLANICININ yazdığı (gönderilmemiş) metin var mı? Girdi: `capture-pane -e` ekranı.
    Kutu = iki `───` çizgisi arasındaki `❯` satırı (son kutu). Gri/soluk ön planla çizilen metin (boş kutu istemi, "devam"
    gibi yer tutucu ÖNERİ) yazılmış SAYILMAZ; varsayılan/renkli ön planda görünür karakter varsa True. Kutu bulunamazsa None
    (bilinmiyor: çağıran eski davranışta kalır). SAF; heuristik: yanlış pozitif yalnız bir dürtmeyi erteler."""
    lines = (ansi_text or "").split("\n")
    plain = [_ANSI_ANY_RE.sub("", ln) for ln in lines]
    prompt_idx = [i for i, ln in enumerate(plain) if ln.lstrip().startswith(_PROMPT_CHAR)]
    for i in reversed(prompt_idx):
        above = any(_BOX_RULE_CHARS * 4 in plain[j] for j in range(max(0, i - 1), i)) or i == 0
        if not above:
            continue
        raw = lines[i]
        dim, seen_prompt, typed = False, False, False
        pos = 0
        for m in _SGR_RE.finditer(raw):
            seg = _SGR_RE.sub("", raw[pos:m.start()])
            typed |= _seg_typed(seg, dim, seen_prompt)
            seen_prompt = seen_prompt or _PROMPT_CHAR in seg
            st = _is_dim_fg([int(x) for x in m.group(1).split(";") if x.isdigit()], dim)
            dim = dim if st is None else st
            pos = m.end()
        seg = _SGR_RE.sub("", raw[pos:])
        typed |= _seg_typed(seg, dim, seen_prompt)
        return typed
    return None


def _seg_typed(seg: str, dim: bool, seen_prompt: bool) -> bool:
    """Bir renk parçasında, istem karakterinden SONRA gelen görünür (boşluk/NBSP/kenar çizgisi olmayan) karakter var mı
    ve ön plan gri değil mi."""
    if dim or not seg:
        return False
    if not seen_prompt:
        if _PROMPT_CHAR not in seg:
            return False
        seg = seg.split(_PROMPT_CHAR, 1)[1]
    return any(not c.isspace() and c not in "\u00a0\u2502" for c in seg)


def tmux_pane_snapshot(name: str) -> Optional[tuple]:
    """Pane'in boyutu + GÖRÜNÜR ekranı TEK tmux sürecinde: `((cols, rows, history_size, alternate_on, pane_tty), text)`.

    `display-message -p -t T FORMAT ; capture-pane -t T -e -p`: argv'deki yalın `;` elemanı tmux'ta komut ayıracıdır;
    iki komut aynı komut kuyruğunda arka arkaya koşar (boyut ile metin aynı andan, ayrı çağrılardaki gibi
    aralarına çıktı girmez). `text` yalnız görünür `rows` satırdır (her satır "\\n" ile biter, `-e` renkli), 2000
    satırlık scrollback DEĞİL: mirror görüntüleyici yalnız ekranı çizer (TBD#80 A, 2026-10-13 ölçümü: tam capture
    tmux sunucusunda 12,7 ms CPU / 143 KB, görünür capture 1,5 ms / 2 KB; her ek tmux süreci ~3 ms toplam CPU).
    `-S`/`-E` yoktur, yani çağıranın hiçbir sayısı argv'ye girmez; hedef `=ad:` biçiminde (`_exact`) ve `:` ile
    biter, `;` ile bitmez.

    Hata (oturum yok, tmux yok, çıktı beklenen biçimde değil) → None; çağıran tek tek çağrılara düşebilir."""
    target = _exact(name)
    try:
        r = subprocess.run(
            _base_argv() + ["display-message", "-p", "-t", target, _SNAPSHOT_FORMAT, ";",
                             "capture-pane", "-t", target, "-e", "-p"],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if r.returncode != 0:
            return None
        head, sep, text = r.stdout.partition("\n")
        if not sep:
            return None
        fields = head.split(" ", 4)
        if len(fields) != 5:
            return None
        return (int(fields[0]), int(fields[1]), int(fields[2]), bool(int(fields[3])), fields[4].strip()), text
    except Exception:
        return None


def tmux_kill_session(name: str) -> None:
    try:
        subprocess.run(_base_argv() + ["kill-session", "-t", _exact(name)],
                        capture_output=True, timeout=_TIMEOUT)
    except Exception:
        pass


def find_outer_bash_pids(name: str) -> List[tuple]:
    """Find gnome-terminal-launched `bash -c "... ; exec bash"` windows attached
    to tmux session `name`, BEFORE tearing it down (TODO: tmux-backed "stop"
    leaves an orphan window).

    spawn.py opens a window with `bash -c "tmux -L cops ... new-session -A -s
    NAME ...; exec bash"` (no `-d` — the window itself IS the attached tmux
    client); `open_window()`'s one-click "pencere aç" adds more windows the
    same way via `attach-session -t NAME; exec bash`. Neither is an ancestor
    of the pane's own claude/agy pid (both reach the pane only through the
    shared tmux SERVER, never through the OS process tree — see
    `kill_session_and_parent`'s docstring), so they can't be found by walking
    up from `pid`; they must be matched by cmdline instead.

    That cmdline is only readable in this window: once the session dies (the
    pane's command exiting already ends it by default, before an explicit
    `tmux kill-session` even runs) the attached client returns and `exec
    bash` REPLACES this process's argv, permanently erasing the `-s NAME`/
    `-t NAME` text `cmdline()` would otherwise match on. Callers must call
    this BEFORE killing the pane's process, not just before `tmux_kill_session`.

    Returns a list of (pid, create_time) — create_time lets a caller that
    kills later re-check it's still the same process, not a reused pid
    (mirrors kill_session_and_parent's own parent-pid-before-kill pattern).
    A session can have more than one attached window (original + "pencere
    aç" extras), so this returns every match rather than just the first.
    """
    import psutil

    needles = (
        f"-s {shlex.quote(name)} -c ",              # spawn.py's initial window
        f"attach-session -t {shlex.quote(name)};",  # open_window()'s extra window(s)
    )
    found: List[tuple] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] != "bash":
                continue
            cmdline = proc.cmdline()
            if len(cmdline) < 3 or cmdline[1] != "-c":
                continue
            script = cmdline[2]
            if any(needle in script for needle in needles):
                found.append((proc.pid, proc.create_time()))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return found


def is_tmux_backed(pid: int) -> bool:
    """Walk the psutil ancestor chain (bounded) looking for our tmux server.

    Conservative: any lookup failure (NoSuchProcess/AccessDenied/zombie) at any
    hop stops the walk and returns False — uncertain means "treat as a legacy
    bare session", never over-claims tmux-backed status. This is what keeps
    already-running plain sessions correctly untouched by the tmux-aware kill
    path until they're naturally respawned.
    """
    import psutil

    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return False

    want = ["tmux", "-L", TMUX_SOCKET]
    for _ in range(_ANCESTOR_WALK_LIMIT):
        try:
            proc = proc.parent()
            if proc is None:
                return False
            cmd = proc.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False
        if not cmd:
            continue
        if os.path.basename(cmd[0]) == "tmux" and cmd[1:3] == want[1:3]:
            return True
    return False
