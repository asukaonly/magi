"""Pytest root conftest — bootstraps shared test helpers onto sys.path.

Without this, the conftests under tests/memory/l2, tests/memory/l3, and
tests/api would each need their own copy of the schema-application helpers.
Centralizing the helpers under tests/_shared/ avoids drift when migrations
are added.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent / "tests"
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
