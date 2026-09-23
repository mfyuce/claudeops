"""tmux'suz IoProvider registry — web.py bu registry üzerinden dolaylı
çağırır, hiçbiri provider adına göre dallanmaz (bkz. base.py docstring'i)."""
from __future__ import annotations
from typing import Dict, Optional

from .base import FormField, IoProvider, IoProviderError
from .ucli_provider import UcliIoProvider

IO_PROVIDERS: Dict[str, IoProvider] = {
    "ucli": UcliIoProvider(),
}


def get_io_provider(name: str) -> Optional[IoProvider]:
    return IO_PROVIDERS.get(name)
