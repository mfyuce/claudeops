"""cops-cli testi için argparse kâhini: Python CLI'ın GERÇEK ayrıştırıcısıyla (`claudeops.cli.build_parser`) her argv'yi ayrıştırır.

Kullanım: python3 -I py_argparse_oracle.py <py dizini> <json argv listesi dosyası>
Çıktı: satır başına JSON: {"ok": true, "action":..., "apply":..., "listen":..., "internal":..., "bin":...} ya da {"ok": false, "exit": kod}.
Yalnız ayrıştırır; komut işlevi (`args.func`) ÇAĞRILMAZ.
"""
import contextlib
import io
import json
import sys

sys.path.insert(0, sys.argv[1])
from claudeops import cli  # noqa: E402

cases = json.load(open(sys.argv[2], encoding="utf-8"))
# Hepsi `front` ile başlar: `build_parser` argv'ye yalnız eklenti komutları için bakar (çekirdek komutta eklenti yüklenmez);
# ayrıştırıcı bir kez kurulur (argparse ayrıştırıcısı yeniden kullanılabilir).
assert all(c and c[0] == "front" for c in cases)
parser = cli.build_parser(["front"])
for argv in cases:
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            ns = parser.parse_args(argv)
        print(json.dumps({"ok": True, "action": getattr(ns, "action", None), "apply": getattr(ns, "apply", None),
                          "listen": getattr(ns, "listen", None), "internal": getattr(ns, "internal", None),
                          "bin": getattr(ns, "bin", None)}))
    except SystemExit as e:
        print(json.dumps({"ok": False, "exit": e.code}))
