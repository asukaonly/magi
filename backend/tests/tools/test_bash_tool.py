from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi_plugin_sdk.subprocess import BoundedStreamOutput, BoundedSubprocessResult
from magi.tools.builtin.bash_tool import (
    BashTool,
    _build_subprocess_env,
    _decode_bounded_stream,
    _decode_process_output_with_encoding,
)
from magi.tools.schema import ToolExecutionContext


def test_decode_process_output_prefers_utf8(monkeypatch):
    monkeypatch.setattr(
        "magi.tools.builtin.bash_tool._candidate_output_encodings",
        lambda: ["utf-8", "cp936"],
    )

    text = "path: Z:\\测试目录"

    decoded, _ = _decode_process_output_with_encoding(text.encode("utf-8"))
    assert decoded == text


def test_decode_process_output_falls_back_to_windows_code_page(monkeypatch):
    monkeypatch.setattr(
        "magi.tools.builtin.bash_tool._candidate_output_encodings",
        lambda: ["utf-8", "cp936"],
    )

    text = "'ls' 不是内部或外部命令"

    decoded, _ = _decode_process_output_with_encoding(text.encode("cp936"))
    assert decoded == text


def test_decode_with_encoding_reports_winning_codec(monkeypatch):
    monkeypatch.setattr(
        "magi.tools.builtin.bash_tool._candidate_output_encodings",
        lambda: ["utf-8", "cp936"],
    )

    text = "'ls' 不是内部或外部命令"
    decoded, encoding = _decode_process_output_with_encoding(text.encode("cp936"))

    assert decoded == text
    assert encoding == "cp936"


def test_decode_with_encoding_falls_back_with_replacement(monkeypatch):
    monkeypatch.setattr(
        "magi.tools.builtin.bash_tool._candidate_output_encodings",
        lambda: ["ascii"],
    )

    decoded, encoding = _decode_process_output_with_encoding(b"\xff\xfe")

    assert encoding == "utf-8/replace"
    assert "\ufffd" in decoded


def test_build_subprocess_env_sets_utf8_hints(monkeypatch):
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LANG", raising=False)

    env = _build_subprocess_env()

    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"

    if os.name != "nt":
        assert env["LC_ALL"] == "C.UTF-8"
        assert env["LANG"] == "C.UTF-8"


def test_build_subprocess_env_respects_existing_locale(monkeypatch):
    monkeypatch.setenv("LANG", "ja_JP.eucJP")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)

    env = _build_subprocess_env()

    if os.name != "nt":
        # Should not clobber an explicit non-UTF-8 locale set by the operator.
        assert env["LANG"] == "ja_JP.eucJP"
        assert "LC_ALL" not in env
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_build_subprocess_env_removes_proxy_when_disabled(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://env-proxy:7890")
    monkeypatch.setattr(
        "magi.config.get_config",
        lambda: SimpleNamespace(network=SimpleNamespace(proxy_url=lambda: None)),
    )

    env = _build_subprocess_env()

    assert "HTTP_PROXY" not in env
    assert "http_proxy" not in env


def test_build_subprocess_env_uses_configured_proxy(monkeypatch):
    monkeypatch.setattr(
        "magi.config.get_config",
        lambda: SimpleNamespace(network=SimpleNamespace(proxy_url=lambda: "http://127.0.0.1:7890")),
    )

    env = _build_subprocess_env()

    assert env["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:7890"


def test_decode_truncated_utf8_tail_uses_replacement() -> None:
    encoded = "前后".encode("utf-8")
    stream = BoundedStreamOutput(
        tail=encoded[1:],
        total_bytes=len(encoded) + 10,
        truncated=True,
        spill_path=None,
    )

    decoded, encoding = _decode_bounded_stream(stream)

    assert decoded.endswith("后")
    assert "\ufffd" in decoded
    assert encoding == "utf-8/replace"


@pytest.mark.asyncio
async def test_bash_timeout_keeps_partial_output_and_bounded_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, dict[str, object]]] = []
    spill_path = Path("C:/temp/full-stdout.bin")

    async def fake_run(command: object, **kwargs: object) -> BoundedSubprocessResult:
        calls.append((command, kwargs))
        return BoundedSubprocessResult(
            returncode=1,
            stdout=BoundedStreamOutput(
                tail="部分输出".encode("utf-8"),
                total_bytes=100_000,
                truncated=True,
                spill_path=spill_path,
            ),
            stderr=BoundedStreamOutput(
                tail=b"",
                total_bytes=0,
                truncated=False,
                spill_path=None,
            ),
            timed_out=True,
        )

    monkeypatch.setattr("magi.tools.builtin.bash_tool.run_bounded_subprocess", fake_run)
    tool = BashTool()
    result = await tool.execute(
        {"command": "echo hi", "cwd": ".", "timeout": 7},
        ToolExecutionContext(agent_id="test-agent", workspace="."),
    )

    assert result.success is False
    assert result.error_code == "TIMEOUT"
    assert result.data["command"] == "echo hi"
    assert result.data["stdout"] == "部分输出"
    assert result.data["return_code"] == 1
    assert result.data["stdout_total_bytes"] == 100_000
    assert result.data["stdout_truncated"] is True
    assert result.data["stdout_spill_path"] == str(spill_path)
    assert result.data["timed_out"] is True
    command, kwargs = calls[0]
    assert command == "echo hi"
    assert kwargs["shell"] is True
    assert kwargs["timeout"] == 7
    assert kwargs["max_spill_bytes"] == 0
