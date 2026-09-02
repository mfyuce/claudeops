"""~/.claude.json doğrulama — bozuksa --resume BLANK-TUI hang eder.

Referans: [[config-corruption-resume-hang]] — eşzamanlı yazma/toplu-ho sonrası
bozulur; fresh --new çalışır ama --resume askıya girer. Teşhis: bu kontrol.
"""
from __future__ import annotations
import json
from .paths import CONFIG_JSON


def validate_config() -> tuple[bool, str, str]:
    """(ok, code, detail) döndür. ok=False → bozuk veya eksik config.

    `code` dil-nötr (frontend'in kendi `t.configMsg(code, detail)`'ı ile
    yerelleştirilir — web panelin geri kalanındaki "backend ham veri döner,
    React yerelleştirir" deseniyle tutarlı olsun diye; eskiden burada
    hazır-Türkçe bir cümle dönüyordu, panel dili EN'de olsa da bu cümle hep
    Türkçe kalıyordu). `detail` sadece corrupt/unreadable'da dolu (istisna
    metni, teknik/dil-nötr).
    """
    try:
        with open(CONFIG_JSON, encoding="utf-8") as f:
            json.load(f)
        return True, "valid", ""
    except FileNotFoundError:
        return False, "not_found", ""
    except json.JSONDecodeError as e:
        return False, "corrupt", str(e)
    except Exception as e:
        return False, "unreadable", str(e)
