"""`py/cops mcp-ext <kimlik>` — eklentinin (K13 `register_mcp_server`) araçlarını stdio MCP sunucusu olarak sunar. Protokol döngüsü
`mcp_queue.run_server`dan paylaşılır. Eklenti AYNI süreçte yüklenir (`extensions.load()`), handler doğrudan çağrılır (panel/HTTP yok).
Eklenti yoksa ya da kimlik kayıtlı değilse çıkış kodu 2."""
from __future__ import annotations
import sys
from typing import Any, Callable, Dict

from .. import extensions
from . import mcp_queue


def default_spec(server_id: str):
    import os
    from ..paths import REPO_DIR
    from ..providers.base import McpServerSpec
    srv = extensions.mcp_servers().get(server_id, {"tools": []})
    return McpServerSpec(name=f"cops-ext-{server_id}", command=os.path.join(REPO_DIR, "py", "cops"), args=("mcp-ext", server_id),
                         allowed_tools=tuple(t["name"] for t in srv["tools"]))


def _dispatch_for(tools, handler) -> Dict[str, Callable[[int, dict], dict]]:
    def make(name: str):
        def call(_port: int, args: dict) -> dict:
            return handler(name, args or {})
        return call
    return {t["name"]: make(t["name"]) for t in tools}


def register(sub) -> None:
    p = sub.add_parser("mcp-ext", help="MCP stdio server: eklenti araçları (K13 register_mcp_server; örn. `mcp-ext notes`)")
    p.add_argument("server_id")
    p.set_defaults(func=run)


def run(args) -> int:
    extensions.load()
    srv = extensions.mcp_servers().get(args.server_id)
    if srv is None:
        print(f"mcp-ext: '{args.server_id}' kayıtlı değil (eklenti yüklü mü? durum: {extensions.status()['status']})", file=sys.stderr)
        return 2
    mcp_queue.run_server(mcp_queue.DEFAULT_PORT, tools=srv["tools"], dispatch=_dispatch_for(srv["tools"], srv["handler"]),
                         server_name=f"cops-ext-{args.server_id}")
    return 0
