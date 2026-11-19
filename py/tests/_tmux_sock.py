"""tmux 3.2a `kill-server` sonrası soket DOSYASINI silmiyor (`/tmp/tmux-UID/<soket>` şişiyordu, 20 bin dosya): testler
`kill-server` sonrası bunu çağırır. Yalnız verilen adlı soketi siler; hata (yok/izin) yutulur."""
import os


def unlink_socket(name: str) -> None:
    d = os.path.join(os.environ.get("TMUX_TMPDIR") or "/tmp", f"tmux-{os.getuid()}")
    try:
        os.unlink(os.path.join(d, name))
    except OSError:
        pass
