"""tmux pencere şeridi (data/tmux.conf + data/tmux-strip.conf, TODO.md 2026-10-16, TBD#86) testleri.

Çalıştırma:  python3 -m unittest discover -s py/tests -p 'test_tmux_strip.py' -v

GERÇEK tmux'a karşı koşar (>= 3.2 gerekir, yoksa atlanır) ama canlı `cops` soketine DOKUNMAZ: her test kendi atılabilir
soketlerinde (`cops_t_<pid>_<n>`) çalışır ve temizler. Menü UÇTAN UCA sınanır: ikinci bir tmux sunucusu "terminal öykünücüsü"
olur, içindeki bir pane `inner` sunucuya GERÇEK bir tmux istemcisi olarak bağlanır; tuşlar o pane'e yollanır, ekran
`capture-pane` ile okunur (tarayıcısız, TUI/ANSI sınaması için kullanılan yöntem). Gerçek `py/cops` yerine tmux'un çağırdığı
argümanları bir dosyaya yazan sahte bir başlatıcı konur: menünün oturum adını komuta HİÇ koymadığı, yalnız istemci adını
verdiği burada kanıtlanır.
"""
import itertools
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import tmux_backend  # noqa: E402

REAL_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claudeops", "data")
ENV = {k: v for k, v in os.environ.items() if k != "TMUX"}
ENV["TERM"] = "xterm-256color"
_counter = itertools.count()


def tmux_version():
    try:
        out = subprocess.run(["tmux", "-V"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


VERSION = tmux_version()
needs_tmux = unittest.skipUnless(VERSION is not None and VERSION >= (3, 2), "tmux >= 3.2 gerekir")


def wait_for(fn, timeout=8.0, interval=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    return fn()


class Tree:
    """<kök>/py/claudeops/data/{tmux.conf,tmux-strip.conf} (gerçek dosyaların KOPYASI) + <kök>/py/cops (sahte başlatıcı)."""

    def __init__(self, tc, with_strip=True):
        self.root = tempfile.mkdtemp(prefix="cops_tmux_strip_")
        tc.addCleanup(shutil.rmtree, self.root, True)
        data = os.path.join(self.root, "py", "claudeops", "data")
        os.makedirs(data)
        shutil.copy(os.path.join(REAL_DATA, "tmux.conf"), data)
        if with_strip:
            shutil.copy(os.path.join(REAL_DATA, "tmux-strip.conf"), data)
        self.conf = os.path.join(data, "tmux.conf")
        self.launcher = os.path.join(self.root, "py", "cops")
        self.log = os.path.join(self.root, "log.txt")
        with open(self.launcher, "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/env bash\n"
                    "{ printf 'ARGV'; for a in \"$@\"; do printf ' [%s]' \"$a\"; done; printf '\\n'; }"
                    f" >> {shlex.quote(self.log)}\n")
        os.chmod(self.launcher, 0o755)

    def argv_lines(self):
        try:
            with open(self.log, encoding="utf-8") as f:
                return [ln.rstrip("\n") for ln in f]
        except OSError:
            return []


class Server:
    """Atılabilir bir tmux sunucusu (kendi soketi)."""

    def __init__(self, tc, tree):
        self.tree = tree
        self.sock = f"cops_t_{os.getpid()}_{next(_counter)}"
        tc.addCleanup(self.kill)

    def run(self, *args):
        return subprocess.run(["tmux", "-L", self.sock, *args], capture_output=True, text=True, env=ENV, timeout=15)

    def start(self, session, cmd="sleep 900"):
        r = self.run("-f", self.tree.conf, "new-session", "-d", "-s", session, "-x", "100", "-y", "30", cmd)
        if r.returncode != 0:
            raise AssertionError(f"tmux new-session başarısız: {r.stderr}")

    def new(self, session, cmd="sleep 900"):
        r = self.run("new-session", "-d", "-s", session, "-x", "100", "-y", "30", cmd)
        if r.returncode != 0:
            raise AssertionError(f"tmux new-session başarısız: {r.stderr}")

    def option(self, name):
        return self.run("show-options", "-gv", name).stdout.strip()

    def kill(self):
        subprocess.run(["tmux", "-L", self.sock, "kill-server"], capture_output=True, env=ENV, timeout=10)


class Terminal:
    """Dış tmux sunucusu = terminal öykünücüsü; pane'i `server`a GERÇEK bir istemci olarak bağlanır."""

    def __init__(self, tc, server, session):
        self.server = server
        self.sock = f"{server.sock}_o{next(_counter)}"
        tc.addCleanup(self.kill)
        script = os.path.join(server.tree.root, "attach.sh")
        with open(script, "w", encoding="utf-8") as f:
            f.write(f"#!/usr/bin/env bash\nunset TMUX\nexec tmux -L {server.sock} attach -t {shlex.quote('=' + session + ':')}\n")
        os.chmod(script, 0o755)
        self.run("-f", "/dev/null", "new-session", "-d", "-s", "o", "-x", "100", "-y", "30", script)
        def clients():
            return self.server.run("list-clients", "-t", f"={session}:", "-F", "#{client_name}").stdout.split()

        if not wait_for(clients):
            raise AssertionError("tmux istemcisi bağlanmadı")
        self.client = clients()[0]      # BU session'a bağlı istemci (aynı sunucuda birden çok olabilir)
        wait_for(lambda: "satır" in self.screen())

    def run(self, *args):
        return subprocess.run(["tmux", "-L", self.sock, *args], capture_output=True, text=True, env=ENV, timeout=15)

    def screen(self):
        return self.run("capture-pane", "-p", "-t", "=o:").stdout

    def keys(self, *names):
        self.run("send-keys", "-t", "=o:", *names)

    def literal(self, text):
        self.run("send-keys", "-t", "=o:", "-l", text)

    def wait_screen(self, needle, timeout=6.0):
        return wait_for(lambda: needle in self.screen(), timeout)

    def last_line(self):
        return self.screen().rstrip("\n").split("\n")[-1]

    def kill(self):
        subprocess.run(["tmux", "-L", self.sock, "kill-server"], capture_output=True, env=ENV, timeout=10)

    def open_menu(self):
        self.keys("C-b", "a")
        return self.wait_screen("│ Handover")

    def settle(self, seconds=0.25):
        time.sleep(seconds)


@needs_tmux
class ConfigLoadTests(unittest.TestCase):
    def test_base_options_still_apply_when_the_strip_file_is_missing(self):
        tree = Tree(self, with_strip=False)
        srv = Server(self, tree)
        srv.start("base")
        for name, want in (("history-limit", "2000"), ("mouse", "on"), ("set-titles", "on"), ("status", "off")):
            self.assertEqual(srv.option(name), want, name)
        self.assertEqual(srv.option("@cops_py"), "")

    def test_strip_file_turns_the_status_line_on_and_locates_the_launcher(self):
        tree = Tree(self)
        srv = Server(self, tree)
        srv.start("base")
        self.assertEqual(srv.option("status"), "on")
        self.assertEqual(os.path.normpath(srv.option("@cops_py")), tree.launcher)   # conf'un iki üst dizininde `cops`
        for name, want in (("history-limit", "2000"), ("mouse", "on"), ("set-titles", "on")):   # eskiler bozulmadı
            self.assertEqual(srv.option(name), want, name)

    def test_bindings_exist(self):
        tree = Tree(self)
        srv = Server(self, tree)
        srv.start("base")
        prefix = srv.run("list-keys", "-T", "prefix").stdout
        root = srv.run("list-keys", "-T", "root").stdout
        self.assertRegex(prefix, r"bind-key\s+-T prefix\s+a\s+run-shell -C")
        self.assertRegex(root, r"bind-key\s+-T root\s+MouseDown1StatusRight\s+run-shell -C")

    def test_status_right_shows_the_count_the_alt_screen_marker_and_the_amber_threshold(self):
        tree = Tree(self)
        srv = Server(self, tree)
        srv.start("low")
        srv.new("mid", "bash -c 'seq 1 1000; sleep 900'")
        srv.new("big", "bash -c 'seq 1 2600; sleep 900'")
        srv.new("alt", "bash -c 'printf \"\\033[?1049h\"; sleep 900'")

        def hist(name):
            return int(srv.run("display-message", "-p", "-t", f"={name}:", "#{history_size}").stdout.strip() or 0)

        wait_for(lambda: hist("big") > 1900 and hist("mid") > 900)

        def right(name):
            return srv.run("display-message", "-p", "-t", f"={name}:", "#{T:status-right}").stdout

        low, mid, big, alt = right("low"), right("mid"), right("big"), right("alt")
        self.assertRegex(low, r"^0/2000 satır")
        self.assertNotIn("colour214", low)
        # ~970 satır: eşiğin ALTINDA. Düz `>=` sözlüksel ("970" >= "1900" doğru çıkar) amber yakardı; `e|>=` sayısal.
        self.assertRegex(mid, r"^9\d\d/2000 satır")
        self.assertNotIn("colour214", mid)
        self.assertRegex(big, r"colour214 bold\]\d{4}/2000 satır")   # eşiği aştı: amber
        self.assertIn("alt ekran", alt)
        self.assertNotIn("satır", alt.split("│")[0])               # alt-ekranda sayaç yazılmaz
        self.assertIn("İşlemler", low)

    def test_window_list_is_hidden_for_a_single_window_but_shown_when_there_are_several(self):
        tree = Tree(self)
        srv = Server(self, tree)
        srv.start("one")
        status_line = lambda: srv.run("display-message", "-p", "-t", "=one:", "#{T:status-left}#{T:window-status-current-format}").stdout
        self.assertNotRegex(status_line(), r"0:")
        srv.run("new-window", "-t", "=one:", "sleep 900")
        self.assertRegex(status_line(), r"1:")                          # çoklu pencerede aktif pencere görünür
        self.assertRegex(srv.run("display-message", "-p", "-t", "=one:0", "#{T:window-status-format}").stdout, r"0:")

    def test_main_conf_only_uses_commands_every_supported_tmux_understands(self):
        """tmux, tanımadığı TEK bayrak/komutta dosyanın HİÇBİR satırını uygulamaz (TBD#86): ana dosya yalnız düz
        `set-option -g` ve sürüm kapılı `if-shell -F` içerir; yeni özellikler tmux-strip.conf'a girer."""
        allowed = {("set-option", "-g"), ("if-shell", "-F")}
        with open(os.path.join(REAL_DATA, "tmux.conf"), encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
        self.assertTrue(lines)
        for line in lines:
            tokens = shlex.split(line)
            self.assertIn((tokens[0], tokens[1]), allowed, f"ana tmux.conf'ta uyumsuzluk riski: {line!r}")
        gate = [ln for ln in lines if ln.startswith("if-shell")]
        self.assertEqual(len(gate), 1)
        self.assertIn("#{>=:#{version},3.2}", gate[0])
        self.assertIn("tmux-strip.conf", gate[0])


@needs_tmux
class MenuTests(unittest.TestCase):
    def setUp(self):
        self.tree = Tree(self)
        self.srv = Server(self, self.tree)

    def test_every_menu_item_calls_winact_with_only_the_client_name(self):
        self.srv.start("demo_1")
        term = Terminal(self, self.srv, "demo_1")
        self.assertTrue(term.open_menu(), term.screen())
        for label in ("Handover", "Durdur + yeni isimle başlat", "Durdur", "Yeni chat aç", "Sıfırla"):
            self.assertIn(label, term.screen())
        term.keys("h")
        self.assertTrue(wait_for(lambda: len(self.tree.argv_lines()) == 1))
        term.settle()
        term.open_menu()
        term.keys("n")
        self.assertTrue(wait_for(lambda: len(self.tree.argv_lines()) == 2))
        client = term.client
        self.assertEqual(self.tree.argv_lines(), [f"ARGV [winact] [handover] [--client] [{client}]",
                                                  f"ARGV [winact] [newchat] [--client] [{client}]"])

    def test_destructive_items_ask_first_and_only_y_runs_them(self):
        self.srv.start("demo_1")
        term = Terminal(self, self.srv, "demo_1")
        for key, action, prompt in (("y", "restart", "Durdur + yeni isimle başlat: demo_1? (y/n)"),
                                    ("d", "stop", "Durdur: demo_1? (y/n)"),
                                    ("r", "reset", "SIFIRLA (konuşma bir daha görünmez): demo_1? (y/n)")):
            before = len(self.tree.argv_lines())
            self.assertTrue(term.open_menu(), term.screen())
            term.keys(key)
            self.assertTrue(term.wait_screen(prompt), (action, term.screen()))
            self.assertEqual(len(self.tree.argv_lines()), before, "onaydan ÖNCE çalıştı")
            term.keys("n")                      # vazgeç
            term.settle()
            self.assertEqual(len(self.tree.argv_lines()), before, "vazgeçme çalıştırdı")
            self.assertTrue(term.open_menu())
            term.keys(key)
            self.assertTrue(term.wait_screen(prompt))
            term.keys("y")                      # onayla
            self.assertTrue(wait_for(lambda: len(self.tree.argv_lines()) == before + 1), action)
            self.assertEqual(self.tree.argv_lines()[-1], f"ARGV [winact] [{action}] [--client] [{term.client}]")
            term.settle()

    def test_a_hostile_session_name_neither_breaks_the_menu_nor_reaches_the_command(self):
        hostile = "we'ird name"
        self.srv.start(hostile)
        term = Terminal(self, self.srv, hostile)
        self.assertIn(hostile, term.last_line())            # şeritte olduğu gibi
        self.assertTrue(term.open_menu(), term.screen())
        term.keys("d")
        self.assertTrue(term.wait_screen("Durdur: we_ird_name? (y/n)"), term.screen())   # istemde güvenli karakterlere indirgenir
        term.keys("y")
        self.assertTrue(wait_for(lambda: self.tree.argv_lines()))
        line = self.tree.argv_lines()[-1]
        self.assertEqual(line, f"ARGV [winact] [stop] [--client] [{term.client}]")
        self.assertNotIn("ird", line)                        # ad komuta hiç girmedi
        with mock.patch.object(tmux_backend, "TMUX_SOCKET", self.srv.sock):
            self.assertEqual(tmux_backend.tmux_client_session(term.client), hostile)   # ad tmux'tan VERİ olarak çözülür

    def test_clicking_the_right_status_block_opens_the_menu_but_the_left_block_does_not(self):
        self.srv.start("demo_1")
        term = Terminal(self, self.srv, "demo_1")
        row = int(term.run("display-message", "-p", "-t", "=o:", "#{pane_height}").stdout.strip())
        col = term.last_line().index("İşlemler") + 3
        term.literal(f"\x1b[<0;5;{row}M\x1b[<0;5;{row}m")              # sol blok (ad)
        term.settle(0.8)      # çift tıklama süresinden (300 ms) uzun bekle: yoksa ikinci tıklama `SecondClick1…` olur
        self.assertNotIn("│ Handover", term.screen())
        term.literal(f"\x1b[<0;{col};{row}M\x1b[<0;{col};{row}m")      # sağ blok (sayaç + düğme)
        self.assertTrue(term.wait_screen("│ Handover"), term.screen())
        term.keys("h")
        self.assertTrue(wait_for(lambda: self.tree.argv_lines()))
        self.assertIn("[winact] [handover]", self.tree.argv_lines()[-1])

    def test_the_session_name_is_in_the_strip_and_the_window_list_is_hidden(self):
        self.srv.start("demo_1")
        term = Terminal(self, self.srv, "demo_1")
        line = term.last_line()
        self.assertIn("demo_1", line)
        self.assertNotIn("0:", line)         # "0:bash*" pencere listesi yok
        self.assertIn("0/2000 satır", line)


@needs_tmux
class ClientHelpersTests(unittest.TestCase):
    def test_each_client_resolves_to_ITS_OWN_session(self):
        tree = Tree(self)
        srv = Server(self, tree)
        srv.start("demo_1")
        srv.new("demo_2")
        t1, t2 = Terminal(self, srv, "demo_1"), Terminal(self, srv, "demo_2")
        self.assertNotEqual(t1.client, t2.client)
        with mock.patch.object(tmux_backend, "TMUX_SOCKET", srv.sock):
            self.assertEqual(tmux_backend.tmux_client_session(t1.client), "demo_1")
            self.assertEqual(tmux_backend.tmux_client_session(t2.client), "demo_2")


    def test_a_message_really_appears_on_the_clients_status_line_and_cannot_run_commands(self):
        """Gerçek tmux'a karşı: `display-message -c` 3.2a'da çalışmıyor, mock'lu test bunu göremezdi (e2e'de bulundu)."""
        tree = Tree(self)
        srv = Server(self, tree)
        srv.start("demo_1")
        term = Terminal(self, srv, "demo_1")
        marker = os.path.join(tree.root, "pwned")
        with mock.patch.object(tmux_backend, "TMUX_SOCKET", srv.sock):
            self.assertTrue(tmux_backend.tmux_message(term.client, f"✓ deneme #(touch {marker}) ;", 5000))
        self.assertTrue(term.wait_screen("✓ deneme"), term.screen())
        self.assertIn("#(touch", term.last_line())    # `##` ile kaçışlandı: ham metin görünür, KOMUT ÇALIŞMAZ
        time.sleep(0.5)
        self.assertFalse(os.path.exists(marker))
        with mock.patch.object(tmux_backend, "TMUX_SOCKET", srv.sock):
            self.assertFalse(tmux_backend.tmux_message("/dev/pts/999999", "x"))

    def test_client_session_is_none_for_unknown_or_hostile_client_names(self):
        tree = Tree(self)
        srv = Server(self, tree)
        srv.start("demo_1")
        with mock.patch.object(tmux_backend, "TMUX_SOCKET", srv.sock):
            self.assertIsNone(tmux_backend.tmux_client_session("/dev/pts/999999"))
            self.assertIsNone(tmux_backend.tmux_client_session("-t"))
            self.assertIsNone(tmux_backend.tmux_client_session(""))


class TmuxMessageTests(unittest.TestCase):
    """`tmux_message`: panelden gelen metin tmux biçim genişletmesine ve komut ayracına karşı güvenli."""

    def sent(self, text, client="/dev/pts/3", results=(0,), session="demo_1"):
        calls = []

        def fake_run(argv, **kw):
            if "list-clients" in argv:    # tmux_client_session: istemci -> session
                return subprocess.CompletedProcess(argv, 0, stdout=f"{client}\t{session}\n" if session else "", stderr="")
            calls.append(argv)
            return subprocess.CompletedProcess(argv, results[min(len(calls), len(results)) - 1])

        with mock.patch.object(tmux_backend.subprocess, "run", fake_run):
            ok = tmux_backend.tmux_message(client, text, 4000)
        return ok, calls

    def test_hash_is_doubled_so_a_shell_substitution_in_an_error_text_cannot_run(self):
        ok, calls = self.sent("hata #(rm -rf ~) ve #{x}")
        self.assertTrue(ok)
        self.assertEqual(calls[0][-1], "hata ##(rm -rf ~) ve ##{x}")

    def test_trailing_semicolons_are_dropped_because_they_are_tmux_command_separators(self):
        self.assertEqual(self.sent("foo;")[1][0][-1], "foo")
        self.assertEqual(self.sent("foo ;;")[1][0][-1], "foo")
        self.assertEqual(self.sent("a ; b")[1][0][-1], "a ; b")      # ortadaki `;` argv elemanını bitirmez

    def test_a_leading_dash_cannot_become_a_flag_and_newlines_collapse(self):
        self.assertEqual(self.sent("-t evil")[1][0][-1], " -t evil")
        self.assertEqual(self.sent("a\nb\r\nc")[1][0][-1], "a b c")

    def test_the_target_is_the_clients_session_never_the_broken_dash_c_flag(self):
        ok, calls = self.sent("merhaba")
        self.assertTrue(ok)
        self.assertNotIn("-c", calls[0])           # tmux 3.2a'da `display-message -c` her kullanımda "usage:" ile reddediliyor
        self.assertEqual(calls[0][-3:-1], ["-t", "=demo_1:"])   # tam eşleşme (`_exact`), ön ek eşleşmesi DEĞİL

    def test_a_vanished_client_is_false_and_sends_nothing(self):
        ok, calls = self.sent("x", session=None)
        self.assertFalse(ok)
        self.assertEqual(calls, [])

    def test_a_client_that_looks_like_a_flag_is_rejected_without_calling_tmux(self):
        ok, calls = self.sent("x", client="-t")
        self.assertFalse(ok)
        self.assertEqual(calls, [])
        self.assertFalse(self.sent("x", client="")[0])

    def test_falls_back_to_no_duration_on_a_tmux_without_display_message_d(self):
        ok, calls = self.sent("x", results=(1, 0))
        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)
        self.assertIn("-d", calls[0])
        self.assertNotIn("-d", calls[1])

    def test_failure_everywhere_is_false_not_an_exception(self):
        self.assertFalse(self.sent("x", results=(1, 1))[0])

        def boom(*a, **k):
            raise OSError("no tmux")

        with mock.patch.object(tmux_backend.subprocess, "run", boom):
            self.assertFalse(tmux_backend.tmux_message("/dev/pts/3", "x"))


if __name__ == "__main__":
    unittest.main()
