"""Parite köprüsü: stdin'den {"socket", "calls": [[işlev, ...argüman]]} okur, `claudeops.tmux_backend` sonuçlarını JSON basar.

Çağrı biçimleri:
  [işlev, *argüman]   tmux_backend işlevi (yalnız ALLOWED); dönüş JSON'a (demet -> liste) çevrilir
  ["const", ad]       modül sabiti: derlenmiş regex -> `.pattern`, küme -> sıralı liste, demet -> liste
Tek bir süreçte sırayla koşar (ör. `push_ctx` önbelleği çağrılar arasında yaşar).
"""
import json
import os
import re
import sys

from claudeops import tmux_backend as tb

ORIGINAL_SOCKET = tb.TMUX_SOCKET   # test soketiyle ezilmeden önceki değer (sabit paritesi için)

ALLOWED = {
    "tmux_available", "tmux_conf_path", "_base_argv", "_exact",
    "tmux_new_session_shell_fragment", "tmux_attach_shell_fragment", "tmux_spawn_direct",
    "tmux_has_session", "tmux_capture", "tmux_capture_range", "strip_ansi",
    "tmux_send_keys", "tmux_resize_window", "ctx_label", "tmux_set_ctx", "push_ctx", "tmux_release_size",
    "tmux_send_special_key", "tmux_send_raw", "tmux_client_count", "tmux_client_session", "tmux_message",
    "tmux_pane_size", "pane_is_masked_input", "tty_is_masked",
    "_is_dim_fg", "typed_input_in_box", "input_box", "_seg_typed", "tmux_pane_snapshot",
    "tmux_ghost_session", "_pid_childless", "tmux_kill_session",
    "_outer_bash_via_list_clients", "find_outer_bash_pids", "is_tmux_backed",
}


def const(name: str):
    v = ORIGINAL_SOCKET if name == "TMUX_SOCKET" else getattr(tb, name)
    if isinstance(v, re.Pattern):
        return v.pattern
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    return v


def main() -> None:
    req = json.load(sys.stdin)
    # Canlı sokete ve kullanıcının soket dizinine asla dokunma: test soketi ve geçici TMUX_TMPDIR şart.
    if not req["socket"].startswith("cxrs") or not os.environ.get("TMUX_TMPDIR"):
        sys.exit("test soketi/TMUX_TMPDIR değil")
    tb.TMUX_SOCKET = req["socket"]
    out = []
    for fn, *args in req["calls"]:
        if fn == "const":
            out.append(const(args[0]))
        elif fn in ALLOWED:
            out.append(getattr(tb, fn)(*args))
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
