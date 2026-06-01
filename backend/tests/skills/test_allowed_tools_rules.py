"""Tests for the ``allowed-tools`` parser and matcher.

Covers the YAML-shape variants accepted by the spec (list of strings,
space-separated string, comma-separated string, Tool(pattern) form) and
the matching semantics against tool-specific specifiers.
"""

from __future__ import annotations

import pytest

from magi.skills.allowed_tools_rules import (
    ToolRule,
    any_rule_matches,
    parse_allowed_tools,
    rule_matches,
    rules_to_strings,
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_yaml_list_of_strings():
    rules = parse_allowed_tools(["Read", "Grep", "Bash(git status *)"])
    assert rules == [
        ToolRule("Read", None),
        ToolRule("Grep", None),
        ToolRule("Bash", "git status *"),
    ]


def test_parse_space_separated_string():
    rules = parse_allowed_tools("Bash(git add *) Bash(git commit *) Bash(git status *)")
    assert len(rules) == 3
    assert all(r.tool == "Bash" for r in rules)
    assert {r.pattern for r in rules} == {"git add *", "git commit *", "git status *"}


def test_parse_comma_separated_string_with_colon_pattern():
    """The agent-browser case from the wild."""
    rules = parse_allowed_tools("Bash(agent-browser:*), Bash(npx agent-browser:*)")
    assert rules == [
        ToolRule("Bash", "agent-browser:*"),
        ToolRule("Bash", "npx agent-browser:*"),
    ]


def test_parse_mixed_whitespace_and_commas():
    rules = parse_allowed_tools("Read,Grep ,Bash , Bash(npm:*)")
    assert {r.display for r in rules} == {"Read", "Grep", "Bash", "Bash(npm:*)"}


def test_parse_returns_empty_for_none():
    assert parse_allowed_tools(None) == []


def test_parse_returns_empty_for_unsupported_type():
    assert parse_allowed_tools(42) == []
    assert parse_allowed_tools({"foo": "bar"}) == []


def test_parse_skips_invalid_tokens_but_keeps_valid_ones():
    rules = parse_allowed_tools("Read 123invalid Bash(git *) ((bogus")
    displays = [r.display for r in rules]
    assert "Read" in displays
    assert "Bash(git *)" in displays
    assert "123invalid" not in displays
    assert "((bogus" not in displays


def test_parse_handles_nested_parens_in_pattern():
    rules = parse_allowed_tools("Bash(echo (hello))")
    assert len(rules) == 1
    assert rules[0].tool == "Bash"
    assert rules[0].pattern == "echo (hello)"


def test_parse_list_items_may_themselves_be_multi_token_strings():
    """A user can mix list + multi-token entries — both should expand."""
    rules = parse_allowed_tools(
        ["Read", "Bash(git add *) Bash(git commit *)", "Write"]
    )
    assert [r.display for r in rules] == [
        "Read",
        "Bash(git add *)",
        "Bash(git commit *)",
        "Write",
    ]


def test_rules_to_strings_roundtrip():
    rules = parse_allowed_tools(["Bash(npm test)", "Read"])
    assert rules_to_strings(rules) == ["Bash(npm test)", "Read"]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def test_bare_rule_matches_any_args_for_that_tool():
    rule = ToolRule("Read", None)
    assert rule_matches(rule, "Read", {"path": "/a"})
    assert rule_matches(rule, "Read", {})
    assert not rule_matches(rule, "Write", {"path": "/a"})


def test_bash_pattern_matches_command_arg():
    rule = ToolRule("Bash", "git add *")
    assert rule_matches(rule, "Bash", {"command": "git add foo.txt"})
    assert not rule_matches(rule, "Bash", {"command": "git commit -m x"})


def test_bash_pattern_matches_cmd_alias():
    """``cmd`` is accepted as an alias for ``command``."""
    rule = ToolRule("Bash", "npm test")
    assert rule_matches(rule, "Bash", {"cmd": "npm test"})


def test_read_pattern_matches_path_arg():
    rule = ToolRule("Read", "src/*.py")
    assert rule_matches(rule, "Read", {"path": "src/main.py"})
    assert not rule_matches(rule, "Read", {"path": "tests/test.py"})


def test_edit_pattern_matches_file_path_arg():
    rule = ToolRule("Edit", "docs/*.md")
    assert rule_matches(rule, "Edit", {"file_path": "docs/readme.md"})


def test_pattern_with_glob_question_mark():
    """``?`` is fnmatch glob: matches exactly one character."""
    rule = ToolRule("Bash", "git status?")
    # Exactly one trailing char → match.
    assert rule_matches(rule, "Bash", {"command": "git statuss"})
    # Zero trailing chars → no match.
    assert not rule_matches(rule, "Bash", {"command": "git status"})
    # Two trailing chars → no match (would need ``status??`` or ``status*``).
    assert not rule_matches(rule, "Bash", {"command": "git statussr"})


def test_any_rule_matches_short_circuits():
    rules = [
        ToolRule("Bash", "git add *"),
        ToolRule("Bash", "git commit *"),
        ToolRule("Read", None),
    ]
    assert any_rule_matches(rules, "Bash", {"command": "git commit -m x"})
    assert any_rule_matches(rules, "Read", {"path": "/x"})
    assert not any_rule_matches(rules, "Bash", {"command": "rm -rf /"})
    assert not any_rule_matches(rules, "Write", {"path": "/x"})


def test_pattern_against_empty_specifier_fails():
    """A patterned rule against a tool with no derivable specifier doesn't accidentally match."""
    rule = ToolRule("CustomTool", "foo")
    assert not rule_matches(rule, "CustomTool", {})
