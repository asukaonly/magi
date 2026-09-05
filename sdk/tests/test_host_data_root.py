"""The host data root never changes the operating-system home directory."""
from pathlib import Path

import pytest
from magi_plugin_sdk.runtime_paths import get_magi_home


def test_default_and_explicit_home(monkeypatch, tmp_path):
    monkeypatch.delenv("MAGI_HOME", raising=False)
    assert get_magi_home() == Path.home() / ".magi"
    candidate = tmp_path / "candidate"
    monkeypatch.setenv("MAGI_HOME", str(candidate))
    assert get_magi_home() == candidate
    assert not candidate.exists()


@pytest.mark.parametrize("value", ["", "relative", "/", str(Path.home()), "/tmp/../"])
def test_rejects_unsafe_or_ambiguous_roots(monkeypatch, value):
    monkeypatch.setenv("MAGI_HOME", value)
    with pytest.raises(ValueError, match="dedicated absolute"):
        get_magi_home()
