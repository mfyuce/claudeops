"""Parite köprüsü: stdin'den {"socket", "calls": [[işlev, ...argüman]]} okur, `claudeops.tmux_backend` sonuçlarını JSON basar."""
import json
import sys

from claudeops import tmux_backend as tb

ALLOWED = {
    "strip_ansi", "typed_input_in_box", "input_box", "ctx_label",
    "tmux_has_session", "tmux_capture", "tmux_capture_range", "tmux_pane_size", "tmux_pane_snapshot",
    "pane_is_masked_input", "tmux_client_count",
    "tmux_send_keys", "tmux_send_raw", "tmux_send_special_key", "tmux_resize_window",
}


def main() -> None:
    req = json.load(sys.stdin)
    # Canlı sokete asla dokunma: test soketi verilmemişse çık.
    if not req["socket"].startswith("cxrs"):
        sys.exit("test soketi değil")
    tb.TMUX_SOCKET = req["socket"]
    json.dump([getattr(tb, fn)(*args) for fn, *args in req["calls"] if fn in ALLOWED], sys.stdout)


if __name__ == "__main__":
    main()
