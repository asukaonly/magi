"""Classifier matrix — asserts the risk level per ``(tool, args)``."""

from __future__ import annotations

import pytest

from magi.control.permission.classifier import RiskClassifier
from magi.control.permission.contracts import RiskLevel


@pytest.fixture()
def classifier() -> RiskClassifier:
    return RiskClassifier()


@pytest.mark.parametrize(
    ("tool", "args", "expected"),
    [
        # Shell — read-only pipelines stay LOW.
        ("bash", {"command": "ls -la"}, RiskLevel.LOW),
        ("bash", {"command": "cat file.txt | head -n 20"}, RiskLevel.LOW),
        ("bash", {"command": "rg 'foo' src/"}, RiskLevel.LOW),
        ("bash", {"command": "git status"}, RiskLevel.LOW),
        ("bash", {"command": "git log --oneline"}, RiskLevel.LOW),
        ("bash", {"command": "docker ps"}, RiskLevel.LOW),
        ("powershell", {"command": "echo hi"}, RiskLevel.LOW),
        # Shell — redirects and ordinary mutating ops stay MEDIUM.
        ("bash", {"command": "echo hi > /tmp/foo"}, RiskLevel.MEDIUM),
        ("bash", {"command": "rm note.txt"}, RiskLevel.MEDIUM),
        ("bash", {"command": "mv old.py new.py"}, RiskLevel.MEDIUM),
        ("bash", {"command": "chmod 755 script.sh"}, RiskLevel.MEDIUM),
        ("bash", {"command": "git commit -m 'x'"}, RiskLevel.MEDIUM),
        ("bash", {"command": "sed -i 's/a/b/' file.txt"}, RiskLevel.MEDIUM),
        # Shell — installers, sudo, and plain git push publish or persist.
        ("bash", {"command": "npm install react"}, RiskLevel.HIGH),
        ("bash", {"command": "pip install requests"}, RiskLevel.HIGH),
        ("bash", {"command": "sudo apt-get update"}, RiskLevel.HIGH),
        ("bash", {"command": "git push origin main"}, RiskLevel.HIGH),
        # Shell — destructive verbs.
        ("bash", {"command": "rm -rf ./node_modules"}, RiskLevel.DESTRUCTIVE),
        ("bash", {"command": "git push --force origin main"}, RiskLevel.DESTRUCTIVE),
        ("bash", {"command": "dd if=/dev/zero of=/dev/sda"}, RiskLevel.DESTRUCTIVE),
        ("bash", {"command": "docker system prune"}, RiskLevel.DESTRUCTIVE),
        (
            "powershell",
            {"command": "Remove-Item .\\build -Recurse -Force"},
            RiskLevel.DESTRUCTIVE,
        ),
        # File tools.
        ("file_write", {"path": "/tmp/note.md"}, RiskLevel.MEDIUM),
        ("file_edit", {"path": "src/app.py"}, RiskLevel.MEDIUM),
        (
            "file_write",
            {"path": "/Users/alice/.ssh/authorized_keys"},
            RiskLevel.DESTRUCTIVE,
        ),
        ("file_read", {"path": "src/app.py"}, RiskLevel.LOW),
        # Network.
        ("web_fetch", {"url": "https://example.com"}, RiskLevel.MEDIUM),
        ("web_search", {"query": "python asyncio"}, RiskLevel.LOW),
        # External side effects.
        ("send_message", {"channel": "#general", "text": "hi"}, RiskLevel.HIGH),
        ("image-generation", {"prompt": "draw a small desk"}, RiskLevel.HIGH),
    ],
)
def test_classifier_matrix(
    classifier: RiskClassifier,
    tool: str,
    args: dict,
    expected: RiskLevel,
) -> None:
    result = classifier.classify(tool_name=tool, arguments=args)
    assert result.level is expected, (
        f"tool={tool} args={args} expected={expected.value} got={result.level.value} "
        f"signals={[s.key for s in result.signals]}"
    )


def test_unknown_tool_low_by_default(classifier: RiskClassifier) -> None:
    result = classifier.classify(tool_name="totally_unknown", arguments={})
    assert result.level is RiskLevel.LOW
    assert result.signals == []


def test_unknown_tool_dangerous_flag_promotes_to_high(
    classifier: RiskClassifier,
) -> None:
    result = classifier.classify(
        tool_name="totally_unknown", arguments={}, tool_is_dangerous=True
    )
    assert result.level is RiskLevel.HIGH
    assert any(s.key == "tool_flagged_dangerous" for s in result.signals)


def test_file_read_inside_workspace_stays_low_risk(
    classifier: RiskClassifier, tmp_path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = classifier.classify(
        tool_name="file_read",
        arguments={"path": "src/app.py"},
        workspace=str(workspace),
    )

    assert result.level is RiskLevel.LOW
    assert {signal.key for signal in result.signals} == {"fs_read"}


def test_file_read_outside_workspace_promotes_to_high(
    classifier: RiskClassifier, tmp_path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"

    result = classifier.classify(
        tool_name="file_read",
        arguments={"path": str(outside)},
        workspace=str(workspace),
    )

    assert result.level is RiskLevel.HIGH
    assert {signal.key for signal in result.signals} == {"fs_read", "outside_workspace"}


def test_file_read_sensitive_path_promotes_to_destructive(
    classifier: RiskClassifier,
) -> None:
    result = classifier.classify(
        tool_name="file_read",
        arguments={"path": "~/.ssh/id_rsa"},
        workspace="/tmp/workspace",
    )

    assert result.level is RiskLevel.DESTRUCTIVE
    assert {signal.key for signal in result.signals} == {
        "fs_read",
        "sensitive_user_path",
    }


@pytest.mark.parametrize(
    "tool_name",
    [
        "custom_send_message",
        "slack_send_message",
        "acme_send_email",
        "discord_post_message",
        "publish_message_to_bus",
        "notify_user_via_push",
        "foo_send_sms",
    ],
)
def test_external_send_substring_fallback_high(
    classifier: RiskClassifier, tool_name: str
) -> None:
    """Plugins that forget dangerous=True still get gated if the name
    contains a canonical external-send substring."""
    result = classifier.classify(tool_name=tool_name, arguments={"channel": "#x"})
    assert result.level is RiskLevel.HIGH
    assert any(s.key == "external_side_effect" for s in result.signals)


def test_remote_tool_risk_cannot_lower_host_external_send_rule(
    classifier: RiskClassifier,
) -> None:
    result = classifier.classify(
        tool_name="mcp__chat__send_message",
        arguments={"channel": "#x"},
        tool_risk_level="low",
    )

    assert result.level is RiskLevel.HIGH
    assert any(s.key == "external_side_effect" for s in result.signals)


def test_authoritative_host_override_can_lower_heuristic_risk(
    classifier: RiskClassifier,
) -> None:
    result = classifier.classify(
        tool_name="mcp__chat__send_message",
        arguments={"channel": "#x"},
        tool_risk_level="low",
        tool_risk_authoritative=True,
    )

    assert result.level is RiskLevel.LOW
    assert any(s.key == "tool_risk_authoritative" for s in result.signals)


def test_invalid_declared_risk_falls_back_to_dangerous_flag(
    classifier: RiskClassifier,
) -> None:
    result = classifier.classify(
        tool_name="mcp__demo__unknown",
        arguments={},
        tool_is_dangerous=True,
        tool_risk_level="invalid",
    )

    assert result.level is RiskLevel.HIGH
    assert any(s.key == "tool_flagged_dangerous" for s in result.signals)


def test_empty_shell_command_low(classifier: RiskClassifier) -> None:
    result = classifier.classify(tool_name="bash", arguments={"command": "   "})
    assert result.level is RiskLevel.LOW


def test_image_generation_records_generation_and_write_signals(
    classifier: RiskClassifier,
) -> None:
    result = classifier.classify(
        tool_name="image-generation",
        arguments={"prompt": "draw a small desk"},
    )

    assert result.level is RiskLevel.HIGH
    assert result.preview == "draw a small desk"
    assert {signal.key for signal in result.signals} == {
        "provider_generation",
        "fs_write",
    }
