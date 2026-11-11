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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,content,status,verifier,kind",
    [
        ("draft.md", b"# Draft\nComplete text.\n", "pass", "text.readback", "readback"),
        ("note.txt", "caf\u00e9".encode("latin-1"), "pass", "text.readback", "readback"),
        ("README", b"Project notes\n", "pass", "text.readback", "readback"),
        ("config.yaml", b"enabled: true\n---\nitems: [one, two]\n", "pass", "yaml.safe_load_all", "format"),
        ("config.yml", b"items: [unclosed\n", "fail", "yaml.safe_load_all", "format"),
        ("unsafe.yaml", b"!!python/object/apply:os.system [echo unsafe]", "fail", "yaml.safe_load_all", "format"),
        ("data.csv", b'name,note\r\nAlice,"two, words"\r\n', "pass", "csv.reader", "format"),
        ("data.tsv", b"name\tnote\nAlice\tok\n", "pass", "csv.reader", "format"),
        ("broken.csv", b'name,note\nAlice,"unclosed\n', "fail", "csv.reader", "format"),
    ],
)
async def test_document_verification_reports_its_actual_check(
    tmp_path, name, content, status, verifier, kind,
):
    target = tmp_path / name
    target.write_bytes(content)
    result = await verify_file(target, timeout_s=10)
    assert (result.status, result.verifier, result.check_kind) == (status, verifier, kind)
    if status == "fail":
        assert result.stderr


@pytest.mark.asyncio
async def test_document_read_failure_cannot_pass(tmp_path, monkeypatch):
    target = tmp_path / "draft.md"
    target.write_text("draft")

    def denied_open(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "open", denied_open)
    result = await verify_file(target, timeout_s=10)
    assert result.status == "fail"
    assert "denied" in result.stderr
