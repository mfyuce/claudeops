"""`py/claudeops/data/run-tunnel.sh` testleri (stdlib unittest, ek bağımlılık yok).

Çalıştırma:  python3 py/tests/test_run_tunnel_script.py -v

Ağa / gerçek cloudflared'a / gerçek ntfy.sh'ye ve CANLI tünele (~/.claude/claudeops) DOKUNMAZ:
HOME geçici dizine çevrilir, `$HOME/.local/bin/cloudflared` sahte bir kabuk betiğidir, PATH'in
başına sahte `curl` (ilk N çağrıyı başarısız kılabilir) ve `sleep` (tam sayı bekleyişleri kısaltır)
konur. Ortamdaki CLAUDEOPS_* değişkenleri sızdırılmaz (canlı dosya yollarını gösterebilirler).

Kapsadığı iki kusur (2026-10-12, kullanıcı: "tunnel uyarisi gelmedi kurulmadi mi?"):
  1. URL ayıklama regex'i, cloudflared'ın HATA satırındaki `https://api.trycloudflare.com`'u
     tünel URL'i sanıyordu (başarısız her açılışta URL_FILE'a sahte adres + sahte bildirim).
  2. ntfy bildirimi TEK ATIŞTI: reboot sonrası ağ dengesizken düşünce bir daha denenmiyordu,
     üstelik URL_FILE yazıldığı için sonraki açılışlar da "değişmedi" deyip susuyordu.
"""
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "claudeops" / "data" / "run-tunnel.sh"
URL_A = "https://aaa-bbb-ccc-ddd.trycloudflare.com"
URL_B = "https://eee-fff-ggg-hhh.trycloudflare.com"
SENT = "bildirim gönderildi"

# Gerçek cloudflared taklidi: `tunnel list` (named tunnel var mı), `tunnel ... --url` (quick) ve
# `tunnel ... run <ad>` (named). STOP_FILE oluşana kadar "çalışır" (en çok ~20 sn).
FAKE_CLOUDFLARED = r"""#!/bin/bash
if [ "$1" = tunnel ] && [ "$2" = list ]; then
    [ -n "${FAKE_NAMED:-}" ] && printf 'ID NAME CREATED CONNECTIONS\nabc claudeops 2026-01-01 1\n'
    exit 0
fi
if [ "${FAKE_SCENARIO:-ok}" = fail ]; then
    echo 'failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": dial tcp: lookup api.trycloudflare.com on 1.1.1.1:53: dial udp 1.1.1.1:53: connect: network is unreachable' >&2
    exit 1
fi
if [ -z "${FAKE_NAMED:-}" ]; then
    echo "2026-10-12T05:01:59Z INF Requesting new quick Tunnel on trycloudflare.com..." >&2
    echo "2026-10-12T05:02:10Z INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |" >&2
    echo "2026-10-12T05:02:10Z INF |  ${FAKE_URL}                                     |" >&2
fi
for _ in $(seq 1 400); do
    [ -e "$STOP_FILE" ] && exit 0
    sleep 0.05
done
"""

# `curl -fsS -m 10 -d MESAJ URL` taklidi: çağrıyı günlüğe yazar; FAILS_FILE'daki sayı kadar çağrı
# başarısız (curl -f'in 22'si) olur, sonrakiler başarılı.
FAKE_CURL = r"""#!/bin/bash
printf '%s\n' "$*" >> "$CURL_LOG"
n=$(cat "$FAILS_FILE" 2>/dev/null || echo 0)
if [ "$n" -gt 0 ]; then
    echo $((n - 1)) > "$FAILS_FILE"
    exit 22
fi
exit 0
"""

# Tam sayı bekleyişler (bildirim yeniden-deneme aralıkları: 10, 20, 40 ... sn) neredeyse anında
# geçer; kesirli bekleyişler (betiğin 0.5 sn'lik URL yoklaması, sahte cloudflared'ın 0.05'i)
# gerçekten beklenir ki yarış koşulları gerçek akışla aynı kalsın.
FAKE_SLEEP = r"""#!/bin/bash
case "$1" in
    *.*) exec /bin/sleep "$1" ;;
    *)   exec /bin/sleep 0.02 ;;
esac
"""


class TunnelEnv:
    """Geçici HOME + sahte ikililer. Her `boot()` = systemd'nin run-tunnel.sh'ı bir kez başlatması."""

    def __init__(self, case, topic="testtopic"):
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        self.case = case
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.state = self.home / ".claude" / "claudeops"
        self.bindir = self.root / "bin"
        local_bin = self.home / ".local" / "bin"
        for d in (self.state, local_bin, self.bindir):
            d.mkdir(parents=True)
        self._script(local_bin / "cloudflared", FAKE_CLOUDFLARED)
        self._script(self.bindir / "curl", FAKE_CURL)
        self._script(self.bindir / "sleep", FAKE_SLEEP)
        self.url_file = self.state / "tunnel_url.txt"
        self.notified = self.state / "tunnel_url.txt.notified"
        self.log = self.state / "tunnel.log"
        self.curl_log = self.root / "curl.log"
        self.fails_file = self.root / "curl_fails"
        self.stop_file = self.root / "stop"
        if topic:
            (self.state / "ntfy_topic.txt").write_text(topic + "\n")
        self.procs = []
        case.addCleanup(self._kill_all)

    @staticmethod
    def _script(path, body):
        path.write_text(body)
        path.chmod(0o755)

    def boot(self, *, scenario="ok", url=URL_A, named=False, curl_fails=0, retry_secs=30):
        self.stop_file.unlink(missing_ok=True)
        self.fails_file.write_text(str(curl_fails))
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDEOPS_")}
        env.pop("FAKE_NAMED", None)
        env.update(
            HOME=str(self.home),
            PATH=f"{self.bindir}:{os.environ['PATH']}",
            CLAUDEOPS_NTFY_RETRY_SECS=str(retry_secs),
            FAKE_SCENARIO=scenario,
            FAKE_URL=url,
            STOP_FILE=str(self.stop_file),
            CURL_LOG=str(self.curl_log),
            FAILS_FILE=str(self.fails_file),
        )
        if named:
            env["FAKE_NAMED"] = "1"
            (self.state / "tunnel_fixed_hostname.txt").write_text(url + "\n")
        # systemd gibi: stdout+stderr aynı dosyaya APPEND (script URL'i oradan okur).
        with open(self.log, "ab") as log:
            proc = subprocess.Popen(
                ["bash", str(SCRIPT)], env=env, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True,
            )
        self.procs.append(proc)
        return proc

    def finish(self, proc):
        self.stop_file.touch()
        proc.wait(timeout=10)

    @staticmethod
    def text(path):
        try:
            return path.read_text()
        except FileNotFoundError:
            return ""

    def log_text(self):
        return self.text(self.log)

    def curl_calls(self):
        return [line for line in self.text(self.curl_log).splitlines() if line]

    def wait_for(self, condition, what, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if condition():
                return
            time.sleep(0.05)
        self.case.fail(f"zaman aşımı: {what}\n--- tunnel.log ---\n{self.log_text()}")

    def _kill_all(self):
        for proc in self.procs:
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # script + sahte cloudflared + yetim bildirici
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()


class RunTunnelScriptTests(unittest.TestCase):
    def test_error_line_is_not_taken_for_the_tunnel_url(self):
        env = TunnelEnv(self)
        # 1. açılış: ağ yok, cloudflared quick-tunnel API'sine ulaşamadan 1 ile çıkar.
        proc = env.boot(scenario="fail")
        # cloudflared URL basmadan ölünce script da hemen çıkmalı (systemd 5 sn sonra yeniden
        # başlatsın), 40 x 0.5 sn'lik URL yoklamasının sonunu BEKLEMEDEN.
        proc.wait(timeout=8)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(env.url_file.exists(), f"sahte URL yazıldı: {env.text(env.url_file)!r}")
        self.assertEqual(env.curl_calls(), [], "hata satırındaki api adresi için bildirim denendi")
        # 2. açılış (systemd 5 sn sonra yeniden başlatır): gerçek URL alınır ve bildirilir.
        proc = env.boot(url=URL_A)
        env.wait_for(lambda: SENT in env.log_text(), "gerçek URL'in bildirimi")
        self.assertEqual(env.text(env.url_file).strip(), URL_A)
        self.assertEqual(len(env.curl_calls()), 1)
        env.finish(proc)

    def test_notifies_once_and_stays_silent_for_an_already_notified_url(self):
        env = TunnelEnv(self)
        proc = env.boot(url=URL_A)
        env.wait_for(lambda: SENT in env.log_text(), "ilk bildirim")
        call = env.curl_calls()[0]
        self.assertIn("claudeops tunnel: " + URL_A, call)
        self.assertIn("https://ntfy.sh/testtopic", call)
        self.assertEqual(env.text(env.notified).strip(), URL_A)
        env.finish(proc)
        # Aynı URL ile yeniden başlatma (named tunnel'da her restart böyledir): ikinci bildirim YOK.
        proc = env.boot(url=URL_A)
        env.wait_for(lambda: "URL daha önce bildirilmişti" in env.log_text(), "atlama satırı")
        self.assertEqual(len(env.curl_calls()), 1)
        env.finish(proc)
        # Yeni URL: yeniden bildirilir.
        proc = env.boot(url=URL_B)
        env.wait_for(lambda: env.log_text().count(SENT) == 2, "yeni URL'in bildirimi")
        self.assertEqual(env.text(env.notified).strip(), URL_B)
        self.assertEqual(len(env.curl_calls()), 2)
        env.finish(proc)

    def test_failed_push_is_retried_until_it_goes_through(self):
        env = TunnelEnv(self)
        # Denemeler 0, 10, 30, 70. sn'de: 4. deneme için pencere 30'dan büyük olmalı.
        proc = env.boot(url=URL_A, curl_fails=3, retry_secs=100)
        env.wait_for(lambda: SENT in env.log_text(), "yeniden denemeyle giden bildirim")
        self.assertEqual(len(env.curl_calls()), 4)  # 3 başarısız + 1 başarılı
        log = env.log_text()
        self.assertEqual(log.count("yeniden denenecek"), 1, "ilk başarısızlıktan sonra TEK uyarı satırı")
        self.assertIn("(deneme 4)", log)
        self.assertEqual(env.text(env.notified).strip(), URL_A)
        env.finish(proc)

    def test_gives_up_after_the_window_and_the_next_start_tries_again(self):
        env = TunnelEnv(self)
        proc = env.boot(url=URL_A, curl_fails=1000, retry_secs=25)
        env.wait_for(lambda: "vazgeçildi" in env.log_text(), "vazgeçme satırı")
        self.assertEqual(len(env.curl_calls()), 3)  # bekleyişler 0, 10, 30 sn: 25'i aşınca durur
        self.assertFalse(env.notified.exists())
        self.assertEqual(env.text(env.url_file).strip(), URL_A, "URL, bildirim gitmese de kaydedilir")
        env.finish(proc)
        # Bildirilmemiş URL bir sonraki açılışta (named tunnel'da URL aynı kalsa bile) yeniden denenir.
        proc = env.boot(url=URL_A)  # curl artık başarılı
        env.wait_for(lambda: SENT in env.log_text(), "sonraki açılışta bildirim")
        self.assertEqual(env.text(env.notified).strip(), URL_A)
        env.finish(proc)

    def test_silent_but_logged_when_notifications_are_off(self):
        env = TunnelEnv(self, topic=None)
        proc = env.boot(url=URL_A)
        env.wait_for(lambda: "ntfy kapalı" in env.log_text(), "kapalı satırı")
        self.assertEqual(env.curl_calls(), [])
        self.assertEqual(env.text(env.url_file).strip(), URL_A)
        self.assertFalse(env.notified.exists())
        env.finish(proc)

    def test_named_tunnel_branch_notifies_with_the_fixed_hostname(self):
        env = TunnelEnv(self)
        proc = env.boot(named=True, url="https://panel.example.com")
        env.wait_for(lambda: SENT in env.log_text(), "named tunnel bildirimi")
        self.assertIn("named tunnel 'claudeops' bulundu", env.log_text())
        self.assertEqual(env.text(env.url_file).strip(), "https://panel.example.com")
        self.assertIn("claudeops tunnel: https://panel.example.com", env.curl_calls()[0])
        env.finish(proc)


if __name__ == "__main__":
    unittest.main()
