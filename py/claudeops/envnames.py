"""Güvenli ortam değişkeni adı doğrulaması (leaf modül; settings/spawn/ucli_session_opts/copilot ortak kullanır).

Eskiden `^[A-Z_][A-Z0-9_]*$` 4 modülde ayrı tanımlıydı. `re.match` + `$` sondaki satır sonunu (`"FOO\\n"`) kabul eder; ad shell argv'ye
gömüldüğü için `fullmatch` kullanılır."""
import re

ENV_NAME_RE = re.compile(r"[A-Z_][A-Z0-9_]*")


def is_safe_env_name(name: object) -> bool:
    return isinstance(name, str) and ENV_NAME_RE.fullmatch(name) is not None
