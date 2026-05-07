from __future__ import annotations

import os

from magi.tools.builtin.bash_tool import (
    _build_subprocess_env,
    _decode_process_output_with_encoding,
)


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