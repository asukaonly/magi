"""Tests for subprocess lifecycle helpers."""

from magi_plugin_sdk import subprocess as managed_subprocess


def test_hidden_process_kwargs_is_empty_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(managed_subprocess.os, "name", "posix")

    assert managed_subprocess.hidden_process_kwargs() == {}


def test_hidden_process_kwargs_hides_windows_console(monkeypatch) -> None:
    class FakeStartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = -1

    monkeypatch.setattr(managed_subprocess.os, "name", "nt")
    monkeypatch.setattr(
        managed_subprocess.subprocess,
        "STARTUPINFO",
        FakeStartupInfo,
        raising=False,
    )
    monkeypatch.setattr(
        managed_subprocess.subprocess,
        "STARTF_USESHOWWINDOW",
        1,
        raising=False,
    )
    monkeypatch.setattr(
        managed_subprocess.subprocess,
        "SW_HIDE",
        0,
        raising=False,
    )
    monkeypatch.setattr(
        managed_subprocess.subprocess,
        "CREATE_NO_WINDOW",
        0x08000000,
        raising=False,
    )

    kwargs = managed_subprocess.hidden_process_kwargs()

    assert kwargs["creationflags"] == 0x08000000
    assert kwargs["startupinfo"].dwFlags == 1
    assert kwargs["startupinfo"].wShowWindow == 0
