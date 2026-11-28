"""`python3 -m claudeops ...` girişi."""
import sys

from .paths import secure_path_environ

_dropped = secure_path_environ()     # P2-2: güvenilmeyen PATH girdileri (var olmayan /tmp dizini vb.) atılır, çocuklar da devralır
if _dropped:
    from .diaglog import diag_log
    diag_log("path_env_dropped", dropped=_dropped)

from .cli import main  # noqa: E402

sys.exit(main())
