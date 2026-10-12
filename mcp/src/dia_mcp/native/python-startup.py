"""Dedicated startup for the local operations worker; no user Python plug-ins."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bridge import register  # noqa: E402

register()
