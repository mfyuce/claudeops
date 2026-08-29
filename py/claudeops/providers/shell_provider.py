"""Düz shell provider — bir AI-agent CLI'ı değil, ham interaktif bash.

Amaç: panelin terminal view'ı (xterm.js + tmux_send_keys) zaten GERÇEK bir PTY'ye
(tmux pane) bağlanıyor — claude/agy panelin AYNI mekanizmasını kullanıyor. Bu
provider o pane'e claude/agy yerine düz `bash` koyuyor: sudo, ssh şifre sorması,
apt'ın [Y/n]'i, herhangi bir TUI — TTY isteyen HER ŞEY normal bir terminaldeki
gibi çalışır. "Komut çalıştır, çıktıyı döndür" tarzı fire-and-forget bir HTTP
kutusunda bunların hiçbiri çalışmazdı (gerçek TTY yok) — bu yüzden ayrı bir
mekanizma kurmak yerine mevcut tmux-backed terminal'i olduğu gibi ödünç alıyoruz.

İsimlendirme: claude `--remote-control NAME` bayrağını cmdline'a yazıyor, agy'nin
öyle bir bayrağı yok → COPS_NAME env'iyle çözüyor (ikisi de discovery.py'de
provider-agnostik proc-scan'e bağlı). Düz `bash`ın kendine özgü hiçbir flag'i
yok, o yüzden agy'nin deseni ödünç alınıyor + PROC_TAG argv[0] rename'i eklendi:
`matches_proc` çıplak "bash" ile eşleştirseydi sistemdeki HER bash proc'u (her
terminal sekmesi, her script) taranırdı (agy/claude gibi nadir bir binary DEĞİL,
"bash" en yaygın isimlerden biri) — argv[0]'ı `exec -a` ile PROC_TAG'e çevirmek
matches_proc'u claude/agy kadar ucuz+yanlış-pozitifsiz tutuyor (canlı doğrulandı).
COPS_NAME yoksa extract_name None döner (agy'nin "agy-<pid>" fallback'ının AKSİNE
placeholder ÜRETMEZ) — PROC_TAG kimsede rastgele oluşmaz ama yine de temkinli:
kanıt (env) yoksa göstermeyiz.
"""
from __future__ import annotations
import os
from typing import Dict, List, Optional

from .base import CliProvider

# Sistemdeki HER "bash" proc'una çarpmamak için argv[0] bilerek bununla değiştiriliyor
# (spawn tarafında `exec -a PROC_TAG bash`) — bkz. modül docstring'i.
PROC_TAG = "claudeops-shell"

# model/permission-mode/effort seçenekleri düz shell'e uygulanmıyor (build_inner_command
# hepsini yok sayıyor) — ama roster.py/rc.py/handover.py/web.py TÜM diğer provider'ların
# bu üç listeden en az bir eleman döndürdüğünü varsayıp [0]/[-1] ile indeksliyor; BOŞ
# liste dönmek 8+ çağrı noktasında IndexError'a çarpardı. Tek elemanlı sentinel bunu
# hiçbir çağrı yerine dokunmadan çözüyor (değeri zaten hiçbir yerde kullanılmıyor).
_SENTINEL = ["-"]


class ShellProvider(CliProvider):
    name = "shell"

    def has_conversation(self) -> bool:
        return False

    def resolve_resume_id(self, cwd: str) -> Optional[str]:
        return None  # düz shell'de "devam edilecek konuşma" kavramı yok, hep fresh

    def build_inner_command(self, cwd, model, permission_mode, effort,
                             resume_id, prompt, session_name) -> str:
        # model/permission_mode/effort/resume_id/prompt düz shell'de anlamsız — yok sayılır.
        return f"exec -a {PROC_TAG} bash"

    def env_overrides(self, session_name: str) -> Dict[str, str]:
        return {"COPS_NAME": session_name}

    def matches_proc(self, cmd: List[str]) -> bool:
        return bool(cmd) and os.path.basename(cmd[0]) == PROC_TAG

    def extract_name(self, proc, cmd: List[str]) -> Optional[str]:
        try:
            return proc.environ().get("COPS_NAME") or None
        except Exception:
            return None

    def extract_info(self, cmd: List[str]) -> Dict[str, Optional[str]]:
        return {"sid": None, "model": None, "permission_mode": None, "effort": None}

    def model_choices(self) -> List[str]:
        return _SENTINEL

    def permission_modes(self) -> List[str]:
        return _SENTINEL

    def effort_levels(self) -> List[str]:
        return _SENTINEL
