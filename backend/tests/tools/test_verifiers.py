"""Unit tests for individual verifiers."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.builtin._verifiers import (
    VerifyOutcome,
    get_verifier_for,
    verify_file,
)


@pytest.mark.asyncio
async def test_python_valid_file_passes(tmp_path: Path) -> None:
    target = tmp_path / "ok.py"
    target.write_text("x = 1\n")
    result = await verify_file(target, timeout_s=10)
    assert result.status == "pass"
    assert result.verifier == "py_compile"


@pytest.mark.asyncio
async def test_python_syntax_error_fails(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    target.write_text("def broken(:\n  pass\n")
    result = await verify_file(target, timeout_s=10)
    assert result.status == "fail"
    assert result.exit_code != 0
    combined = (result.stderr or "") + (result.stdout or "")
    assert "broken" in combined or "SyntaxError" in combined


@pytest.mark.asyncio
async def test_json_valid_passes(tmp_path: Path) -> None:
    target = tmp_path / "ok.json"
    target.write_text('{"a": 1, "b": [2, 3]}')
    result = await verify_file(target, timeout_s=10)
    assert result.status == "pass"
    assert result.verifier == "json.loads"


@pytest.mark.asyncio
async def test_json_invalid_fails(tmp_path: Path) -> None:
    target = tmp_path / "bad.json"
    target.write_text("{invalid json}")
    result = await verify_file(target, timeout_s=10)
    assert result.status == "fail"
    assert (result.stderr or "")


@pytest.mark.asyncio
async def test_toml_valid_passes(tmp_path: Path) -> None:
    target = tmp_path / "ok.toml"
    target.write_text('[section]\nkey = "value"\n')
    result = await verify_file(target, timeout_s=10)
    assert result.status == "pass"


@pytest.mark.asyncio
async def test_toml_invalid_fails(tmp_path: Path) -> None:
    target = tmp_path / "bad.toml"
    target.write_text("[unclosed\n")
    result = await verify_file(target, timeout_s=10)
    assert result.status == "fail"


@pytest.mark.asyncio
async def test_unknown_extension_skipped(tmp_path: Path) -> None:
    target = tmp_path / "thing.xyz"
    target.write_text("anything")
    result = await verify_file(target, timeout_s=10)
    assert result.status == "skipped"
    assert "extension" in (result.reason or "").lower()


@pytest.mark.asyncio
async def test_missing_file_returns_error(tmp_path: Path) -> None:
    result = await verify_file(tmp_path / "nope.py", timeout_s=10)
    assert result.status == "skipped"
    reason = (result.reason or "").lower()
    assert "not exist" in reason or "not found" in reason


def test_get_verifier_for_known_extensions() -> None:
    assert get_verifier_for(Path("a.py")) is not None
    assert get_verifier_for(Path("a.json")) is not None
    assert get_verifier_for(Path("a.toml")) is not None


def test_get_verifier_for_unknown_returns_none() -> None:
    assert get_verifier_for(Path("a.xyz")) is None


def test_verify_outcome_serializable() -> None:
    outcome = VerifyOutcome(
        path="src/a.py",
        verifier="py_compile",
        status="pass",
        exit_code=0,
        stdout="",
        stderr="",
        reason=None,
        duration_ms=12,
    )
    payload = outcome.to_dict()
    assert payload["status"] == "pass"
    assert payload["verifier"] == "py_compile"
