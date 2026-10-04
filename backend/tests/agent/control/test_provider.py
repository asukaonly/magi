from __future__ import annotations

import pytest

from magi.control.provider import (
    resolve_control_session_store,
)


def test_resolve_control_session_store_raises_when_unbound() -> None:
    with pytest.raises(RuntimeError, match="control_session_store"):
        resolve_control_session_store()
