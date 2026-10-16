"""`py/cops winact <eylem> [ad]` — pencere eylemi: handover / restart (durdur + yeni isim) / stop / newchat / reset.

Yerel session pencerelerinin tmux şeridindeki menü (`C-b a` ya da sağ şerit bloğuna tıklama, `data/tmux-strip.conf`) bunu
`run-shell -b` ile çağırır: `winact stop --client /dev/pts/105`. Oturum adı komut satırına tmux'tan GİRMEZ (display-menu
komutlardaki biçimleri genişletip yeniden ayrıştırır, serbest bir ad tırnakları bozar); `--client` verilip ad verilmezse
ad tmux'tan veri olarak çözülür (`tmux_backend.tmux_client_session`). Elle de kullanılır: `winact stop cops20261016`,
uzak oturum için `--host yuhem`.

Mantık `window_actions.run_action`da (aynı fonksiyonu `cops watch`ın `a` tuşu da çağırır). Sonuç `--client` varsa o
istemcinin alt satırında kısa bir mesaj olarak görünür (başarıda yalnız oturumu bırakmayan eylemler: handover, yeni
chat; durdur / yeniden başlat / sıfırla'da pencere zaten kapanır ya da değişir). `--client` verilince stdout/stderr'e
HİÇBİR şey basılmaz: `run-shell` çıktıyı pane'in üstünde bir görünüm olarak açardı.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from ..diaglog import diag_log
from ..hosts import LOCAL_HOST_NAME
from ..tmux_backend import tmux_client_session, tmux_message
from ..window_actions import BY_ID, ActionBusy, ActionLock, PanelClient, Result, run_action
from .watch import read_token
from .web import DEFAULT_PORT

NOTICE_OK_MS = 5000
NOTICE_ERR_MS = 9000
NOTICE_START_MS = 3000
_SILENT_OK = ("stop", "restart", "reset")   # pencere kapanır/değişir; başarı mesajı gereksiz


def register(sub) -> None:
    p = sub.add_parser("winact", help="pencere eylemi (tmux şeridi menüsü çağırır): "
                                      "winact <handover|restart|stop|newchat|reset> [ad] [--host H] [--client C]")
    p.add_argument("action", choices=sorted(BY_ID), help="handover | restart (durdur + yeni isim) | stop | newchat | reset")
    p.add_argument("name", nargs="?", default="",
                   help="oturum adı; verilmezse --client'in bağlı olduğu tmux session'ı")
    p.add_argument("--host", default=LOCAL_HOST_NAME, help="oturumun host'u (varsayılan: yerel)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"yerel panelin portu (varsayılan {DEFAULT_PORT}); `py/cops web [--port]` ile aynı olmalı")
    p.add_argument("--client", default="",
                   help="tmux istemci adı (#{client_name}): sonuç o istemcinin alt satırında gösterilir, stdout susar")
    p.set_defaults(func=run)


def _execute(action_id: str, host: str, name: str, port: int) -> Result:
    """Kilitle, çalıştır, günlüğe yaz. Hiçbir istisna dışarı çıkmaz (çağıran tmux: sessiz ölüm yerine mesaj)."""
    lock = ActionLock(host, name)
    try:
        lock.acquire()
    except ActionBusy as e:
        return Result(False, f"✗ {e}")
    try:
        diag_log("winact_begin", action=action_id, host=host, name=name)
        result = run_action(PanelClient(port, read_token), action_id, host, name)
        diag_log("winact_end", action=action_id, host=host, name=name, ok=result.ok, message=result.message[:200],
                 new=result.name)
        return result
    except Exception as e:   # beklenmedik: yutma, nedenini göster
        diag_log("winact_error", action=action_id, host=host, name=name, error=f"{type(e).__name__}: {e}"[:200])
        return Result(False, f"✗ iç hata: {type(e).__name__}: {e}")
    finally:
        lock.release()


def run(args: argparse.Namespace) -> int:
    action = BY_ID[args.action]
    client: str = (args.client or "").strip()
    name: str = (args.name or "").strip()
    host: str = (args.host or LOCAL_HOST_NAME).strip()
    if not name:
        resolved: Optional[str] = tmux_client_session(client) if client else None
        if not resolved:
            msg = ("✗ oturum adı yok" if not client else f"✗ tmux istemcisi {client} bir session'a bağlı görünmüyor")
            if client:
                tmux_message(client, msg, NOTICE_ERR_MS)
            else:
                print(f"cops winact: {msg}; ad verin ya da --client kullanın", file=sys.stderr)
            return 2
        name = resolved
    if client:
        tmux_message(client, f"… {action.label}: {name}", NOTICE_START_MS)
    result = _execute(action.id, host, name, args.port)
    if client:
        # Başarıda oturumu bırakan eylemlerde (handover, yeni chat) sonucu göster; yıkıcı olanlarda pencere gidiyor/değişiyor.
        if not result.ok:
            tmux_message(client, result.message, NOTICE_ERR_MS)
        elif action.id not in _SILENT_OK:
            tmux_message(client, result.message, NOTICE_OK_MS)
    else:
        print(result.message, file=sys.stdout if result.ok else sys.stderr)
    return 0 if result.ok else 1
