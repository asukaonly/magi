"""Classifier matrix — asserts the risk level per ``(tool, args)``."""

from __future__ import annotations

import pytest

from magi.agent.control.permission.classifier import RiskClassifier
from magi.agent.control.permission.contracts import RiskLevel


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
        # Shell — redirects push to at least MEDIUM.
        ("bash", {"command": "echo hi > /tmp/foo"}, RiskLevel.MEDIUM),
        # Shell — destructive verbs.
        ("bash", {"command": "rm -rf ./node_modules"}, RiskLevel.DESTRUCTIVE),
        ("bash", {"command": "sudo apt-get update"}, RiskLevel.DESTRUCTIVE),
        ("bash", {"command": "npm install react"}, RiskLevel.HIGH),
        ("bash", {"command": "git commit -m 'x'"}, RiskLevel.HIGH),
        ("bash", {"command": "git push --force origin main"}, RiskLevel.DESTRUCTIVE),
        ("bash", {"command": "git push origin main"}, RiskLevel.HIGH),
        ("bash", {"command": "sed -i 's/a/b/' file.txt"}, RiskLevel.HIGH),
        # File tools.
        ("file_write", {"path": "/tmp/note.md"}, RiskLevel.HIGH),
        ("file_edit", {"path": "src/app.py"}, RiskLevel.HIGH),
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


def test_empty_shell_command_low(classifier: RiskClassifier) -> None:
    result = classifier.classify(tool_name="bash", arguments={"command": "   "})
    assert result.level is RiskLevel.LOW
