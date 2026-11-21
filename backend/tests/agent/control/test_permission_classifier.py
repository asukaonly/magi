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
        ("bash", {"command": "   "}, RiskLevel.LOW),
        ("bash", {"command": "ls -la"}, RiskLevel.LOW),
        ("bash", {"command": "cat file.txt | head -n 20"}, RiskLevel.LOW),
        ("bash", {"command": "rg 'foo' src/"}, RiskLevel.LOW),
        ("bash", {"command": "git status"}, RiskLevel.LOW),
        ("bash", {"command": "git log --oneline"}, RiskLevel.LOW),
        ("bash", {"command": "docker ps"}, RiskLevel.LOW),
        ("powershell", {"command": "echo hi"}, RiskLevel.LOW),
        (
            "powershell",
            {
                "command": (
                    "Get-Process | Select-Object -First 3 Name,Id " "| ConvertTo-Json -Compress"
                )
            },
            RiskLevel.LOW,
        ),
        # Shell — redirects and ordinary mutating ops stay MEDIUM.
        ("bash", {"command": "echo hi > /tmp/foo"}, RiskLevel.MEDIUM),
        ("bash", {"command": "rm note.txt"}, RiskLevel.MEDIUM),
        ("bash", {"command": "mv old.py new.py"}, RiskLevel.MEDIUM),
        ("bash", {"command": "chmod 755 script.sh"}, RiskLevel.MEDIUM),
        ("bash", {"command": "git commit -m 'x'"}, RiskLevel.MEDIUM),
        ("bash", {"command": "sed -i 's/a/b/' file.txt"}, RiskLevel.MEDIUM),
        (
            "powershell",
            {"command": "Set-Content -Path .\\note.txt -Value hello"},
            RiskLevel.MEDIUM,
        ),
        (
            "powershell",
            {"command": "Remove-Item .\\note.txt"},
            RiskLevel.MEDIUM,
        ),
        # Shell — installers, sudo, and plain git push publish or persist.
        ("bash", {"command": "npm install react"}, RiskLevel.HIGH),
        ("bash", {"command": "pip install requests"}, RiskLevel.HIGH),
        ("bash", {"command": "sudo apt-get update"}, RiskLevel.HIGH),
        ("bash", {"command": "git push origin main"}, RiskLevel.HIGH),
        (
            "powershell",
            {"command": "Some-CustomCommand -DoSomething"},
            RiskLevel.HIGH,
        ),
        (
            "powershell",
            {"command": "Set-Content -Path $target -Value hello"},
            RiskLevel.HIGH,
        ),
        (
            "powershell",
            {"command": "Remove-Item @dynamicParameters"},
            RiskLevel.HIGH,
        ),
        (
            "powershell",
            {"command": "winget install Example.Package"},
            RiskLevel.HIGH,
        ),
        (
            "powershell",
            {"command": ("Set-Content C:\\Windows\\System32\\drivers\\etc\\hosts " "127.0.0.1")},
            RiskLevel.HIGH,
        ),
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
        (
            "powershell",
            {"command": "ri C:\\* -r -fo"},
            RiskLevel.DESTRUCTIVE,
        ),
        ("powershell", {"command": "Clear-Disk -Number 0"}, RiskLevel.DESTRUCTIVE),
        # File tools.
        ("file_write", {"path": "note.md"}, RiskLevel.MEDIUM),
        ("file_write", {"path": "/tmp/note.md"}, RiskLevel.HIGH),
        ("file_edit", {"path": "src/app.py"}, RiskLevel.MEDIUM),
        ("file_edit", {"path": "/tmp/outside.py"}, RiskLevel.HIGH),
        (
            "file_write",
            {"path": "/Users/alice/.ssh/authorized_keys"},
            RiskLevel.DESTRUCTIVE,
        ),
        (
            "file_write",
            {"path": "/Users/alice/.magi/config/llm.yaml"},
            RiskLevel.DESTRUCTIVE,
        ),
        (
            "file_write",
            {"path": "/Users/alice/Library/LaunchAgents/com.test.plist"},
            RiskLevel.DESTRUCTIVE,
        ),
        (
            "file_edit",
            {"path": "/Users/alice/.zshrc"},
            RiskLevel.DESTRUCTIVE,
        ),
        ("file_write", {"path": ".env.local"}, RiskLevel.DESTRUCTIVE),
        ("file_read", {"path": "src/app.py"}, RiskLevel.LOW),
        # Network.
        ("web-fetch", {"url": "https://example.com"}, RiskLevel.MEDIUM),
        ("web_fetch", {"url": "https://example.com"}, RiskLevel.MEDIUM),
        ("web-search", {"query": "python asyncio"}, RiskLevel.LOW),
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


@pytest.mark.parametrize(
    "path_kind,expected,signals",
    [
        ("inside", RiskLevel.LOW, {"fs_read"}),
        ("outside", RiskLevel.HIGH, {"fs_read", "outside_workspace"}),
        ("sensitive", RiskLevel.DESTRUCTIVE, {"fs_read", "sensitive_user_path"}),
    ],
)
def test_file_read_classification_respects_workspace_and_sensitive_paths(
    classifier, tmp_path, path_kind, expected, signals
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = {
        "inside": "src/app.py",
        "outside": str(tmp_path / "outside.txt"),
        "sensitive": "~/.ssh/id_rsa",
    }[path_kind]
    result = classifier.classify(
        tool_name="file_read", arguments={"path": path}, workspace=str(workspace)
    )
    assert result.level is expected
    assert {signal.key for signal in result.signals} == signals


@pytest.mark.parametrize("path_kind", ["environment", "whitespace", "symlink"])
@pytest.mark.parametrize("sensitive", [False, True])
def test_file_read_classifies_resolved_target(
    classifier, tmp_path, monkeypatch, path_kind, sensitive
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / (".ssh/id_rsa" if sensitive else "outside.txt")
    target.parent.mkdir(exist_ok=True)
    target.write_text("canary")
    monkeypatch.setenv("MAGI_TEST_TARGET", str(target))
    monkeypatch.setenv("MAGI_TEST_WORKSPACE", str(workspace))
    link = workspace / "linked.txt"
    link.symlink_to(target)
    path = {
        "environment": " $MAGI_TEST_TARGET ",
        "whitespace": f" {target} ",
        "symlink": "linked.txt",
    }[path_kind]

    result = classifier.classify(
        tool_name="file_read", arguments={"path": path}, workspace="$MAGI_TEST_WORKSPACE"
    )

    assert result.level is (RiskLevel.DESTRUCTIVE if sensitive else RiskLevel.HIGH)


def test_file_read_expanded_workspace_remains_low_risk(classifier, tmp_path, monkeypatch):
    monkeypatch.setenv("MAGI_TEST_WORKSPACE", str(tmp_path))
    result = classifier.classify(
        tool_name="file_read", arguments={"path": " $MAGI_TEST_WORKSPACE/note.txt "},
        workspace=" $MAGI_TEST_WORKSPACE ",
    )
    assert result.level is RiskLevel.LOW


@pytest.mark.parametrize("tool_name", ["file_write", "file_edit"])
@pytest.mark.parametrize(
    "path_kind,expected,signal_key",
    [
        ("inside", RiskLevel.MEDIUM, None),
        ("outside", RiskLevel.HIGH, "outside_workspace"),
        ("magi_home", RiskLevel.DESTRUCTIVE, "sensitive_user_path"),
        ("launch_agent", RiskLevel.DESTRUCTIVE, "sensitive_user_path"),
        ("env_file", RiskLevel.DESTRUCTIVE, "sensitive_user_path"),
    ],
)
def test_file_write_and_edit_respect_workspace_and_sensitive_paths(
    classifier, tmp_path, monkeypatch, tool_name, path_kind, expected, signal_key
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    magi_home = tmp_path / "custom-magi-home"
    magi_home.mkdir()
    monkeypatch.setenv("MAGI_HOME", str(magi_home))
    path = {
        "inside": "src/app.py",
        "outside": str(tmp_path / "outside.txt"),
        "magi_home": str(magi_home / "config" / "llm.yaml"),
        "launch_agent": "~/Library/LaunchAgents/com.example.plist",
        "env_file": ".env",
    }[path_kind]
    result = classifier.classify(
        tool_name=tool_name, arguments={"path": path}, workspace=str(workspace)
    )
    assert result.level is expected
    if signal_key is not None:
        assert any(s.key == signal_key for s in result.signals)


def test_builtin_web_fetch_and_search_names_match_classifier_rules(classifier):
    from magi.tools.builtin.web_fetch_tool import WebFetchTool
    from magi.tools.builtin.web_search_tool import WebSearchTool

    fetch_name = WebFetchTool().get_schema().name
    search_name = WebSearchTool().get_schema().name
    assert classifier.classify(tool_name=fetch_name, arguments={"url": "https://example.com"}).level is RiskLevel.MEDIUM
    assert classifier.classify(tool_name=search_name, arguments={"query": "magi"}).level is RiskLevel.LOW


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
