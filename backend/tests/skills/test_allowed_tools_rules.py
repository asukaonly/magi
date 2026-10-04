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


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            ["Read", "Grep", "Bash(git status *)"],
            [ToolRule("Read", None), ToolRule("Grep", None), ToolRule("Bash", "git status *")],
        ),
        (
            "Bash(git add *) Bash(git commit *) Bash(git status *)",
            [
                ToolRule("Bash", "git add *"),
                ToolRule("Bash", "git commit *"),
                ToolRule("Bash", "git status *"),
            ],
        ),
        (
            "Bash(agent-browser:*), Bash(npx agent-browser:*)",
            [ToolRule("Bash", "agent-browser:*"), ToolRule("Bash", "npx agent-browser:*")],
        ),
        (
            "Read,Grep ,Bash , Bash(npm:*)",
            [
                ToolRule("Read", None),
                ToolRule("Grep", None),
                ToolRule("Bash", None),
                ToolRule("Bash", "npm:*"),
            ],
        ),
        (["Bash(npm test)", "Read"], [ToolRule("Bash", "npm test"), ToolRule("Read", None)]),
    ],
)
def test_allowed_tool_formats_preserve_order_and_patterns_through_rendering(raw, expected):
    rules = parse_allowed_tools(raw)
    assert rules == expected
    rendered = rules_to_strings(rules)
    assert rendered == [
        rule.tool if rule.pattern is None else f"{rule.tool}({rule.pattern})" for rule in expected
    ]
    assert parse_allowed_tools(rendered) == expected


@pytest.mark.parametrize("raw", [None, 42, {"foo": "bar"}])
def test_missing_or_unsupported_rule_shapes_have_no_preapprovals(raw):
    assert parse_allowed_tools(raw) == []


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


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_tool_name,case_rule_pattern,case_argument_name,case_matching_value,case_nonmatching_value",
    [
        pytest.param(
            "Bash",
            "git add *",
            "command",
            "git add foo.txt",
            "git commit -m x",
            id="bash_pattern_matches_command_arg",
        ),
        pytest.param(
            "Read",
            "src/*.py",
            "path",
            "src/main.py",
            "tests/test.py",
            id="read_pattern_matches_path_arg",
        ),
    ],
)
def test_allowed_tool_patterns_match_the_owning_argument(
    case_tool_name,
    case_rule_pattern,
    case_argument_name,
    case_matching_value,
    case_nonmatching_value,
):
    rule = ToolRule(case_tool_name, case_rule_pattern)
    assert rule_matches(rule, case_tool_name, {case_argument_name: case_matching_value})
    assert not rule_matches(rule, case_tool_name, {case_argument_name: case_nonmatching_value})


def test_bash_pattern_matches_cmd_alias():
    """``cmd`` is accepted as an alias for ``command``."""
    rule = ToolRule("Bash", "npm test")
    assert rule_matches(rule, "Bash", {"cmd": "npm test"})


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


@pytest.mark.parametrize(
    "tool,args,expected",
    [
        ("Bash", {"command": "git add file.txt"}, True),
        ("Bash", {"command": "git commit -m x"}, True),
        ("Read", {"path": "/x"}, True),
        ("Read", {}, True),
        ("Bash", {"command": "rm -rf /"}, False),
        ("Write", {"path": "/x"}, False),
    ],
)
def test_any_rule_matches_the_union_of_named_preapprovals(tool, args, expected):
    rules = [
        ToolRule("Bash", "git add *"),
        ToolRule("Bash", "git commit *"),
        ToolRule("Read", None),
    ]
    assert any_rule_matches(rules, tool, args) is expected


def test_pattern_against_empty_specifier_fails():
    """A patterned rule against a tool with no derivable specifier doesn't accidentally match."""
    rule = ToolRule("CustomTool", "foo")
    assert not rule_matches(rule, "CustomTool", {})
