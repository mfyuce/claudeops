"""ucli (unified-cli) — ilk (ve bugün tek) `IoProvider`. `ucli_client.py`'nin
(TOBEDECIDED#44(b)) ince bir sarmalayıcısı; asıl subprocess/pipe mekaniği
orada, burada sadece proje+session kimliği (`.ucli/chat/*.jsonl`) ile
`IoProvider` arayüzü arasındaki çeviri var."""
from __future__ import annotations
import glob
import os
from typing import Dict, List, Optional

from ..ucli_client import UcliError, chat_session_dir, read_chat_history, ucli_chat_once
from .base import FormField, IoProvider, IoProviderError


class UcliIoProvider(IoProvider):
    name = "ucli"

    def ask(self, cwd: str, session: str, prompt: str, fields: Dict[str, str]) -> dict:
        try:
            return ucli_chat_once(
                cwd, prompt,
                session=(session or None),
                model=(fields.get("model") or None),
                endpoint=(fields.get("endpoint") or None),
                api_key_env=(fields.get("api_key_env") or "UCLI_API_KEY"),
                api_key=(fields.get("api_key") or None),
                timeout=90.0,
            )
        except UcliError as e:
            raise IoProviderError(str(e)) from e

    def list_sessions(self, cwd: str) -> List[str]:
        paths = glob.glob(os.path.join(chat_session_dir(cwd), "*.jsonl"))
        paths.sort(key=os.path.getmtime, reverse=True)
        return [os.path.splitext(os.path.basename(p))[0] for p in paths]

    def history(self, cwd: str, session: str) -> Optional[List[Dict[str, str]]]:
        return read_chat_history(cwd, session)

    def form_fields(self) -> List[FormField]:
        """`label`/`placeholder` BİLEREK İngilizce/teknik, düzyazı DEĞİL —
        panelin geri kalanı gibi "backend ham veri döner, React yerelleştirir"
        (bkz. config.py'nin `validate_config` docstring'i) — gerçek TR/EN
        metni `strings.ts`'in `ioFieldMeta`'sı sağlar, `key`'i TANIMAYAN bir
        alan (ileride başka bir provider'dan) bu İngilizce haliyle DÜŞER,
        hiç kırılmaz. Canlı bulgu (2026-09-23): önce burada tam Türkçe
        düzyazı vardı, sayfa EN iken bile Türkçe görünüyordu."""
        return [
            FormField("model", "Model", placeholder="deepseek-v4-flash", required=True),
            FormField("endpoint", "Endpoint (optional)", placeholder="empty = local Ollama"),
            FormField("api_key", "API key (optional, never stored)", type="password"),
            FormField("api_key_env", "API key env name (optional)", placeholder="UCLI_API_KEY"),
        ]
