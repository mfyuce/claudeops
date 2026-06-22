"""~/.claude.json doğrulama — bozuksa --resume BLANK-TUI hang eder.

Referans: [[config-corruption-resume-hang]] — eşzamanlı yazma/toplu-ho sonrası
bozulur; fresh --new çalışır ama --resume askıya girer. Teşhis: bu kontrol.
"""
from __future__ import annotations
import json
from .paths import CONFIG_JSON


def validate_config() -> tuple[bool, str]:
    """(ok, mesaj) döndür. ok=False → bozuk veya eksik config."""
    try:
        with open(CONFIG_JSON) as f:
            json.load(f)
        return True, "~/.claude.json geçerli"
    except FileNotFoundError:
        return False, "~/.claude.json bulunamadı"
    except json.JSONDecodeError as e:
        return False, f"~/.claude.json BOZUK ({e}) — ~/.claude/backups/'tan geri yükle"
    except Exception as e:
        return False, f"~/.claude.json okunamadı: {e}"
