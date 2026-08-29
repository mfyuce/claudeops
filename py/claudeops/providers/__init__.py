"""CLI provider registry — spawn.py/discovery.py/commands/web.py bu registry
üzerinden dolaylı çağırır, hiçbiri `cli` string'ine göre dallanmaz."""
from __future__ import annotations
from typing import Dict

from .base import CliProvider
from .claude_provider import ClaudeProvider
from .agy_provider import AgyProvider
from .shell_provider import ShellProvider

DEFAULT_CLI = "claude"

PROVIDERS: Dict[str, CliProvider] = {
    "claude": ClaudeProvider(),
    "agy": AgyProvider(),
    "shell": ShellProvider(),
}


def get_provider(cli: str) -> CliProvider:
    return PROVIDERS.get(cli, PROVIDERS[DEFAULT_CLI])
