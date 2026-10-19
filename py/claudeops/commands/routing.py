"""`routing` — işe göre model/effort yönergesini göster ya da codex'in küresel AGENTS.md'sine yaz (TBD#91).

Kullanım:
  py/cops routing show    # etkin metin + durum (açık/kapalı, kaynak)
  py/cops routing sync    # codex ~/.codex/AGENTS.md işaretli bloğunu Ayarlar'a göre yaz/kaldır

Claude'a teslim her açılışta bayrakla olur (sync gerekmez). Açık oturumlara hiçbir şey göndermez.
"""
from __future__ import annotations
from .. import routing
from ..settings import load_settings, routing_guidance_enabled


def register(sub):
    p = sub.add_parser("routing", help="işe göre model/effort yönergesini göster / codex'e yaz")
    p.add_argument("action", choices=["show", "sync"])
    p.set_defaults(func=run)


def run(args) -> int:
    if args.action == "show":
        src = "Ayarlar (override)" if str(load_settings().get("routing_guidance_text") or "").strip() else routing.BUNDLED_PATH
        print(f"yönerge: {'AÇIK' if routing_guidance_enabled() else 'KAPALI'}  kaynak: {src}\n")
        print(routing.routing_text())
        return 0
    for target, result in routing.sync_global_files().items():
        print(f"{target}: {result}")
    return 0
