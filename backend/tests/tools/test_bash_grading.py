"""Unit tests for the bash command classifier."""
from __future__ import annotations

import pytest

from magi.tools.builtin._bash_grading import classify_command
from magi_plugin_sdk.command_risk import classify_powershell_command


@pytest.mark.parametrize("cmd", [
    "ls",
    "ls -la /tmp",
    "pwd",
    "cat README.md",
    "echo hello",
    "which python",
    "git status",
    "git log -3",
    "git diff",
    "git show HEAD",
    "git branch",
    "grep -r foo .",
    "find . -name '*.py'",
    "head -5 file.txt",
    "tail -f log.txt",
    "ps aux",
    "df -h",
    "python --version",
    "node --version",
    "wc -l file.txt",
])
def test_read_only_commands(cmd: str) -> None:
    grade = classify_command(cmd)
    assert grade.level == "read_only", f"{cmd!r} graded {grade.level}: {grade.reason}"


@pytest.mark.parametrize("cmd", [
    "git commit -m 'msg'",
    "git push",
    "git pull",
    "git checkout main",
    "git merge feature",
    "git rebase main",
    "npm install",
    "pip install requests",
    "make build",
    "echo hi > out.txt",
    "echo hi >> out.txt",
    "touch file",
    "mkdir foo",
    "mv a b",
    "cp a b",
    "rm file.txt",
    "rmdir empty_dir",
    "git reset HEAD~1",
])
def test_mutating_commands(cmd: str) -> None:
    grade = classify_command(cmd)
    assert grade.level == "mutating", f"{cmd!r} graded {grade.level}: {grade.reason}"


def test_find_with_only_filters_is_read_only() -> None:
    """find without -delete or -exec is purely a query."""
    assert classify_command("find . -name '*.tmp' -newer foo").level == "read_only"


@pytest.mark.parametrize("cmd,expected_keyword", [
    ("rm -rf /", "rm -rf"),
    ("rm -rf /tmp/anything", "rm -rf"),
    ("rm -fr foo", "rm -rf"),
    ("rm -r -f foo", "rm -rf"),
    ("sudo rm -rf .", "rm -rf"),
    ("git push --force", "force"),
    ("git push -f", "force"),
    ("git push --force-with-lease origin main", "force"),
    ("git reset --hard", "reset --hard"),
    ("git reset --hard HEAD~5", "reset --hard"),
    ("git clean -fd", "git clean"),
    ("git clean -fdx", "git clean"),
    ("find . -delete", "find -delete"),
    ("find . -name '*.py' -delete", "find -delete"),
    ("find . -exec rm {} ;", "find -exec rm"),
    ("find . -exec rm -rf {} +", "find -exec rm"),
    ("dd if=/dev/zero of=/dev/sda", "dd"),
    ("mkfs.ext4 /dev/sda1", "mkfs"),
    (":(){ :|:& };:", "fork bomb"),
    ("chmod -R 777 /", "chmod -R 777"),
    ("shutdown now", "shutdown"),
    ("reboot", "reboot"),
])
def test_destructive_commands(cmd: str, expected_keyword: str) -> None:
    grade = classify_command(cmd)
    assert grade.level == "destructive", f"{cmd!r} graded {grade.level}: {grade.reason}"
    assert expected_keyword.lower() in grade.reason.lower(), (
        f"reason {grade.reason!r} should mention {expected_keyword!r}"
    )


def test_chained_returns_max_tier() -> None:
    grade = classify_command("cd /tmp && rm -rf foo")
    assert grade.level == "destructive"
    assert "rm -rf" in grade.reason.lower()


def test_chained_pipe_returns_max_tier() -> None:
    grade = classify_command("ls | xargs rm -rf")
    assert grade.level == "destructive"


def test_chained_or_returns_max_tier() -> None:
    grade = classify_command("ls /nope || git reset --hard")
    assert grade.level == "destructive"


def test_subshell_treated_as_mutating_minimum() -> None:
    grade = classify_command("echo $(date)")
    assert grade.level in ("read_only", "mutating")
    grade2 = classify_command("X=$(uname -a) && echo $X")
    assert grade2.level in ("read_only", "mutating")


def test_subshell_with_destructive_inside_flags_destructive() -> None:
    grade = classify_command('echo "$(rm -rf /tmp/foo)"')
    assert grade.level == "destructive"


def test_eval_with_destructive_literal_flags_destructive() -> None:
    grade = classify_command('eval "rm -rf /"')
    assert grade.level == "destructive"


def test_empty_command_is_mutating() -> None:
    assert classify_command("").level == "mutating"
    assert classify_command("   ").level == "mutating"


def test_unknown_command_defaults_to_mutating() -> None:
    grade = classify_command("some-unknown-binary --weird-flag")
    assert grade.level == "mutating"


def test_redirect_to_file_is_mutating_not_destructive() -> None:
    assert classify_command("echo hi > /tmp/x").level == "mutating"
    assert classify_command("cat /etc/hosts >> /tmp/x").level == "mutating"


def test_sed_n_is_read_only_but_sed_i_is_mutating() -> None:
    assert classify_command("sed -n '1,5p' file").level == "read_only"
    assert classify_command("sed -i 's/foo/bar/' file").level == "mutating"


def test_grade_carries_reason() -> None:
    grade = classify_command("git push --force origin main")
    assert grade.reason


@pytest.mark.parametrize("cmd", [
    "Remove-Item -Recurse -Force C:\\Temp",
    "Remove-Item -Force -Recurse foo",
    "Format-Volume -DriveLetter D",
    "Stop-Computer",
    "Restart-Computer -Force",
])
def test_powershell_destructive(cmd: str) -> None:
    grade = classify_command(cmd)
    assert grade.level == "destructive", f"{cmd!r} graded {grade.level}"


@pytest.mark.parametrize(
    "cmd",
    [
        "ri C:\\* -r -fo",
        'del -LiteralPath "$HOME\\*" -Rec -Fo',
        "Clear-Disk -Number 0",
    ],
)
def test_powershell_dialect_destructive(cmd: str) -> None:
    grade = classify_powershell_command(cmd)
    assert grade.level == "destructive", f"{cmd!r} graded {grade.level}"


def test_powershell_whatif_is_not_destructive() -> None:
    grade = classify_powershell_command("ri C:\\* -r -fo -WhatIf")
    assert grade.level == "mutating"


def test_powershell_disabled_whatif_remains_destructive() -> None:
    grade = classify_powershell_command("ri C:\\* -r -fo -WhatIf:$false")
    assert grade.level == "destructive"


def test_powershell_dynamic_falsey_whatif_does_not_bypass_guard() -> None:
    grade = classify_powershell_command("ri C:\\* -r -fo -WhatIf:$null")
    assert grade.level == "destructive"
