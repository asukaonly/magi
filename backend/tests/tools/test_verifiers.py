"""Unit tests for individual verifiers."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.builtin._verifiers import (
    get_verifier_for,
    verify_file,
)


@pytest.mark.asyncio
async def test_python_valid_file_passes(tmp_path: Path) -> None:
    target = tmp_path / "ok.py"
    target.write_text("x = 1\n")
    result = await verify_file(target, timeout_s=10)
    assert result.status == "pass"
    assert result.verifier == "python.compile"
    assert not (tmp_path / "__pycache__").exists()


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
@pytest.mark.parametrize(
    "content,status", [('{"a":1,"b":[2,3]}', "pass"), ("{invalid json}", "fail")]
)
async def test_json_verifier_reports_actual_parse_outcome(tmp_path, content, status):
    target = tmp_path / "content.json"
    target.write_text(content)
    result = await verify_file(target, timeout_s=10)
    assert result.status == status
    assert result.verifier == "json.loads"
    if status == "fail":
        assert result.stderr


@pytest.mark.parametrize(
    "filename,file_content,expected_status",
    [
        pytest.param("ok.toml", '[section]\nkey = "value"\n', "pass", id="toml_valid_passes"),
        pytest.param("bad.toml", "[unclosed\n", "fail", id="toml_invalid_fails"),
    ],
)
@pytest.mark.asyncio
async def test_toml_verifier_reports_syntax_validity(
    tmp_path: Path, filename, file_content, expected_status
) -> None:
    target = tmp_path / filename
    target.write_text(file_content)
    result = await verify_file(target, timeout_s=10)
    assert result.status == expected_status


@pytest.mark.asyncio
async def test_unknown_extension_skipped(tmp_path: Path) -> None:
    target = tmp_path / "thing.xyz"
    target.write_text("anything")
    result = await verify_file(target, timeout_s=10)
    assert result.status == "skipped"
    assert "extension" in (result.reason or "").lower()

    assert get_verifier_for(target) is None


@pytest.mark.asyncio
async def test_missing_file_returns_error(tmp_path: Path) -> None:
    result = await verify_file(tmp_path / "nope.py", timeout_s=10)
    assert result.status == "skipped"
    reason = (result.reason or "").lower()
    assert "not exist" in reason or "not found" in reason
