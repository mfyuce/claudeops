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
import json
import os
import re
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
case "$*" in
    *"%{http_code}"*)
        # Sağlık bekçisinin yoklaması: ntfy çağrılarından AYRI günlük ve yanıt dizisi. PROBE_CODES'taki
        # kodlar sırayla verilir; dizi bitince SON kod tekrarlanır (hiç kod yoksa 401: panel kimlik doğrulaması).
        printf '%s\n' "$*" >> "$PROBE_LOG"
        code=$(head -n 1 "$PROBE_CODES" 2>/dev/null)
        if [ -n "$code" ]; then sed -i 1d "$PROBE_CODES"; else code=$(cat "$PROBE_LAST" 2>/dev/null || echo 401); fi
        echo "$code" > "$PROBE_LAST"
        printf '%s' "$code"
        [ "$code" = 000 ] && exit 28
        exit 0
        ;;
esac
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
        self.probe_log = self.root / "probe.log"
        self.probe_codes = self.root / "probe_codes"
        self.probe_last = self.root / "probe_last"
        if topic:
            (self.state / "ntfy_topic.txt").write_text(topic + "\n")
        self.procs = []
        case.addCleanup(self._kill_all)

    @staticmethod
    def _script(path, body):
        path.write_text(body)
        path.chmod(0o755)

    def boot(self, *, scenario="ok", url=URL_A, named=False, curl_fails=0, retry_secs=30,
             watch=False, probes=(), watch_fails=3):
        """`watch=True`: sağlık bekçisi AÇIK (aralık ve ilk bekleme 0,3 sn: kesirli bekleyişler sahte
        `sleep`te gerçekten beklenir); `probes`: sahte curl'ün yoklamalara vereceği HTTP kodları."""
        self.stop_file.unlink(missing_ok=True)
        self.fails_file.write_text(str(curl_fails))
        self.probe_codes.write_text("".join(f"{c}\n" for c in probes))
        self.probe_last.unlink(missing_ok=True)
        self.probe_log.unlink(missing_ok=True)
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
            PROBE_LOG=str(self.probe_log),
            PROBE_CODES=str(self.probe_codes),
            PROBE_LAST=str(self.probe_last),
            CLAUDEOPS_TUNNEL_WATCH="0",  # eski testler bekçiden etkilenmesin (curl günlüğü sayılıyor)
        )
        if watch:
            env.update(CLAUDEOPS_TUNNEL_WATCH="1", CLAUDEOPS_TUNNEL_WATCH_INTERVAL="0.3",
                       CLAUDEOPS_TUNNEL_WATCH_GRACE="0.3", CLAUDEOPS_TUNNEL_WATCH_FAILS=str(watch_fails))
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

    def probe_calls(self):
        return [line for line in self.text(self.probe_log).splitlines() if line]

    def write_settings(self, content):
        """Panelin settings.json'ı (bekçi `tunnel_watch` anahtarını buradan okur). dict -> JSON, str -> ham metin,
        None -> dosyayı sil."""
        path = self.state / "settings.json"
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(content if isinstance(content, str) else json.dumps(content))

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


class WatchdogTests(unittest.TestCase):
    """Sağlık bekçisi (2026-10-17, "tunnel gitti"): quick tunnel kopunca cloudflared canlı kalıp adres HTTP 530
    veriyordu ve systemd yalnız süreç ÖLÜNCE yeniden başlatır. Bekçi art arda 530 görürse cloudflared'ı
    sonlandırır, script çıkar, systemd yeni tüneli açar."""

    def alive_after(self, env, proc, probes, seconds=3.0):
        env.wait_for(lambda: len(env.probe_calls()) >= probes, f"{probes} yoklama", timeout=10)
        time.sleep(seconds / 10)  # kısa pay: yanlışlıkla sonlandırma varsa yakalansın
        return proc.poll() is None

    def test_three_consecutive_530_terminate_cloudflared_and_the_script_exits(self):
        env = TunnelEnv(self)
        proc = env.boot(watch=True, probes=["530"])  # dizi bitince son kod (530) tekrarlanır
        proc.wait(timeout=10)
        self.assertNotEqual(proc.returncode, 0, "systemd yeniden başlatsın diye sıfırdan farklı çıkış")
        log = env.log_text()
        self.assertEqual(log.count("HTTP 530 veriyor"), 1, "ilk 530'da TEK uyarı satırı")
        self.assertIn("3 yoklamadır HTTP 530, cloudflared sonlandırılıyor", log)
        self.assertEqual(len(env.probe_calls()), 3)

    def test_the_probe_hits_the_tunnel_url_with_no_credentials(self):
        env = TunnelEnv(self)
        proc = env.boot(watch=True, probes=["401"])
        env.wait_for(lambda: env.probe_calls(), "ilk yoklama")
        call = env.probe_calls()[0]
        self.assertIn(URL_A + "/", call)
        self.assertNotIn("token", call)
        self.assertIn("-m 15", call)
        env.finish(proc)

    def test_a_healthy_tunnel_is_left_alone(self):
        env = TunnelEnv(self)
        proc = env.boot(watch=True, probes=["401"])
        self.assertTrue(self.alive_after(env, proc, probes=4))
        self.assertNotIn("sonlandırılıyor", env.log_text())
        env.finish(proc)

    def down_alerts(self, env):
        return [c for c in env.curl_calls() if "KOPUK" in c]

    def test_two_consecutive_530_send_one_down_alert_before_the_restart(self):
        env = TunnelEnv(self)
        proc = env.boot(watch=True, probes=["530"], watch_fails=6)
        env.wait_for(lambda: len(env.probe_calls()) >= 5, "5 yoklama")
        alerts = self.down_alerts(env)
        self.assertEqual(len(alerts), 1, "ALERT_GAP içinde TEK uyarı")
        self.assertIn(URL_A, alerts[0])
        self.assertIn("kopuş uyarısı gönderildi", env.log_text())
        env.finish(proc)

    def test_flapping_530_401_alerts_although_the_counter_never_reaches_the_threshold(self):
        """07:48-08:32 olayı: her 401 sayacı sıfırlıyor, yeniden başlatma yok, eskiden uyarı da yoktu."""
        env = TunnelEnv(self)
        proc = env.boot(watch=True, probes=["530", "401"] * 4)
        env.wait_for(lambda: len(env.probe_calls()) >= 9, "9 yoklama")
        self.assertEqual(len(self.down_alerts(env)), 1)
        self.assertIn("kararsız", env.log_text())
        self.assertNotIn("sonlandırılıyor", env.log_text())
        env.finish(proc)

    def test_a_healthy_or_single_blip_tunnel_sends_no_down_alert(self):
        env = TunnelEnv(self)
        proc = env.boot(watch=True, probes=["401", "530", "401", "401", "401", "401"])
        env.wait_for(lambda: len(env.probe_calls()) >= 7, "7 yoklama")
        self.assertEqual(self.down_alerts(env), [])
        env.finish(proc)

    def test_down_alert_is_silent_but_logged_when_notifications_are_off(self):
        env = TunnelEnv(self, topic=None)
        proc = env.boot(watch=True, probes=["530"], watch_fails=6)
        env.wait_for(lambda: "kopuş uyarısı atlandı" in env.log_text(), "atlama satırı")
        self.assertEqual(env.curl_calls(), [])
        env.finish(proc)

    def test_a_response_between_failures_resets_the_counter(self):
        env = TunnelEnv(self)
        proc = env.boot(watch=True, probes=["530", "530", "401", "530", "530", "401"])
        self.assertTrue(self.alive_after(env, proc, probes=7))
        log = env.log_text()
        self.assertEqual(log.count("HTTP 530 veriyor"), 2)
        self.assertEqual(log.count("yeniden yanıt veriyor (HTTP 401)"), 2)
        self.assertNotIn("sonlandırılıyor", log)
        env.finish(proc)

    def test_no_answer_000_neither_counts_nor_resets(self):
        """Kopuk tünel + dalgalı DNS: 000'lar teşhisi geciktirmemeli (sayaç korunur), kendileri de sayılmamalı."""
        env = TunnelEnv(self)
        proc = env.boot(watch=True, probes=["530", "000", "530", "000", "530"])
        proc.wait(timeout=10)
        self.assertIn("3 yoklamadır HTTP 530", env.log_text())
        self.assertEqual(len(env.probe_calls()), 5)

    def test_only_a_run_of_000_never_restarts_the_tunnel(self):
        env = TunnelEnv(self)
        proc = env.boot(watch=True, probes=["000"])
        self.assertTrue(self.alive_after(env, proc, probes=6))
        self.assertNotIn("sonlandırılıyor", env.log_text())
        env.finish(proc)

    def test_origin_errors_are_not_a_dead_tunnel(self):
        """502/503/504 = panelin (origin) yeniden başlaması: tüneli yeniden açmak düzeltmez, sayacı sıfırlar."""
        env = TunnelEnv(self)
        proc = env.boot(watch=True, probes=["530", "530", "502", "530", "530", "503", "530", "530", "504", "401"])
        self.assertTrue(self.alive_after(env, proc, probes=11))
        self.assertNotIn("sonlandırılıyor", env.log_text())
        env.finish(proc)

    def test_the_failure_threshold_is_configurable(self):
        env = TunnelEnv(self)
        proc = env.boot(watch=True, probes=["530"], watch_fails=2)
        proc.wait(timeout=10)
        self.assertIn("2 yoklamadır HTTP 530", env.log_text())
        self.assertEqual(len(env.probe_calls()), 2)

    def test_it_can_be_switched_off(self):
        env = TunnelEnv(self)
        proc = env.boot(watch=False, probes=["530"])  # CLAUDEOPS_TUNNEL_WATCH=0
        time.sleep(1.5)
        self.assertIsNone(proc.poll())
        self.assertEqual(env.probe_calls(), [])
        env.finish(proc)

    def test_the_named_tunnel_branch_has_no_watchdog(self):
        env = TunnelEnv(self)
        proc = env.boot(named=True, url="https://panel.example.com", watch=True, probes=["530"])
        env.wait_for(lambda: SENT in env.log_text(), "named tunnel bildirimi")
        time.sleep(1.5)
        self.assertEqual(env.probe_calls(), [])
        self.assertIsNone(proc.poll())
        env.finish(proc)

    def test_no_watchdog_when_cloudflared_never_gave_a_url(self):
        env = TunnelEnv(self)
        proc = env.boot(scenario="fail", watch=True, probes=["530"])
        proc.wait(timeout=8)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(env.probe_calls(), [])

    def test_the_settings_switch_keeps_the_watchdog_off(self):
        """Ayarlar > Genel > "tünel sağlık bekçisi" = kapalı (settings.json `tunnel_watch`): yoklama HİÇ yapılmaz."""
        env = TunnelEnv(self)
        env.write_settings({"tunnel_watch": "off"})
        proc = env.boot(watch=True, probes=["530"])
        env.wait_for(lambda: "Ayarlar'dan KAPATILDI" in env.log_text(), "kapatıldı satırı")
        time.sleep(1.2)
        self.assertEqual(env.probe_calls(), [])
        self.assertIsNone(proc.poll(), "kapalıyken tünel/cloudflared dokunulmaz")
        env.finish(proc)

    def test_every_off_spelling_switches_it_off(self):
        for value in ("off", "OFF", " 0 ", "false", "no", "kapali", "kapalı", "disabled", False, 0):
            with self.subTest(value=value):
                env = TunnelEnv(self)
                env.write_settings({"tunnel_watch": value})
                proc = env.boot(watch=True, probes=["530"])
                env.wait_for(lambda: "KAPATILDI" in env.log_text(), "kapatıldı satırı")
                time.sleep(0.7)
                self.assertEqual(env.probe_calls(), [])
                env.finish(proc)

    def test_toggling_in_settings_takes_effect_without_restarting_the_tunnel(self):
        """Anahtar HER turda okunur: kapatıp açmak tüneli (ve URL'i) yeniden başlatmaz, süreç aynı kalır."""
        env = TunnelEnv(self)
        env.write_settings({"tunnel_watch": "on"})
        proc = env.boot(watch=True, probes=["401"])
        env.wait_for(lambda: len(env.probe_calls()) >= 2, "açıkken yoklamalar")
        env.write_settings({"tunnel_watch": "off"})
        env.wait_for(lambda: "Ayarlar'dan KAPATILDI" in env.log_text(), "kapatma satırı")
        time.sleep(0.5)  # uçuştaki bir tur bitsin
        frozen = len(env.probe_calls())
        time.sleep(1.2)
        self.assertEqual(len(env.probe_calls()), frozen, "kapalıyken yoklama sürdü")
        env.write_settings({"tunnel_watch": "on"})
        env.wait_for(lambda: "Ayarlar'dan AÇILDI" in env.log_text(), "açma satırı")
        env.wait_for(lambda: len(env.probe_calls()) > frozen, "açıldıktan sonra yoklama")
        self.assertIsNone(proc.poll(), "anahtar tüneli yeniden başlatmamalı")
        self.assertNotIn("sonlandırılıyor", env.log_text())
        env.finish(proc)

    def test_turning_it_off_forgets_a_half_counted_run_of_530(self):
        env = TunnelEnv(self)
        env.write_settings({"tunnel_watch": "on"})
        proc = env.boot(watch=True, probes=["530", "530"], watch_fails=3)
        env.wait_for(lambda: len(env.probe_calls()) >= 2, "iki 530")
        env.write_settings({"tunnel_watch": "off"})
        env.wait_for(lambda: "KAPATILDI" in env.log_text(), "kapatma satırı")
        env.write_settings({"tunnel_watch": "on"})
        env.wait_for(lambda: "AÇILDI" in env.log_text(), "açma satırı")
        # Dizi bitti, son kod (530) tekrarlanır: sayaç SIFIRDAN sayılır, yeniden 3 yoklama gerekir.
        proc.wait(timeout=10)
        self.assertGreaterEqual(len(env.probe_calls()), 5, "kapatma sayacı sıfırlamadı")

    def test_missing_unreadable_or_odd_settings_mean_on(self):
        cases = {"dosya yok": None, "bozuk JSON": "{not json", "dizi": "[]", "boş değer": '{"tunnel_watch": ""}',
                 "null": '{"tunnel_watch": null}', "tanınmayan": '{"tunnel_watch": "açık"}', "on": '{"tunnel_watch": "on"}'}
        for name, content in cases.items():
            with self.subTest(case=name):
                env = TunnelEnv(self)
                env.write_settings(content)
                proc = env.boot(watch=True, probes=["401"])
                env.wait_for(lambda: env.probe_calls(), "yoklama (varsayılan AÇIK)")
                self.assertNotIn("KAPATILDI", env.log_text())
                env.finish(proc)

    def test_the_environment_switch_still_wins_over_an_enabled_setting(self):
        env = TunnelEnv(self)
        env.write_settings({"tunnel_watch": "on"})
        proc = env.boot(watch=False, probes=["530"])  # CLAUDEOPS_TUNNEL_WATCH=0
        time.sleep(1.2)
        self.assertEqual(env.probe_calls(), [])
        self.assertNotIn("Ayarlar'dan", env.log_text())
        env.finish(proc)

    def test_the_off_words_in_the_script_match_settings_py(self):
        """Betikteki `case` kümesi ile `settings.py::_OFF_WORDS` aynı kalmalı (iki dil, tek kural)."""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from claudeops import settings
        match = re.search(r"case \"\$v\" in\s*\n\s*([^)]+)\) return 1", SCRIPT.read_text(encoding="utf-8"))
        self.assertIsNotNone(match, "betikte _watch_enabled case kümesi bulunamadı")
        self.assertEqual(set(match.group(1).split("|")), set(settings._OFF_WORDS))

    def test_the_script_has_valid_bash_syntax(self):
        self.assertEqual(subprocess.run(["bash", "-n", str(SCRIPT)]).returncode, 0)


if __name__ == "__main__":
    unittest.main()
