"""Whole-reply controls and their streaming boundary."""

import pytest

from magi.core.chat_expression import ChatExpressionStreamBuffer, is_single_emoji, parse_chat_expression


@pytest.mark.parametrize("emoji", ["👌", "🥹", "❤️", "👍🏽", "👩🏽‍💻", "👨‍👩‍👧‍👦", "🇨🇳", "1️⃣", "🏳️‍🌈"])
def test_reaction_accepts_one_complete_emoji(emoji: str) -> None:
    assert is_single_emoji(emoji)
    parsed = parse_chat_expression(f"[[REACT:{emoji}]]")
    assert parsed is not None and parsed.emoji == emoji


@pytest.mark.parametrize("emoji", ["", "ok", "1", "🇨", "👌👌", "hello👌", "👌\n", "<img>"])
def test_reaction_rejects_non_emoji_or_multiple_graphemes(emoji: str) -> None:
    assert not is_single_emoji(emoji)


@pytest.mark.parametrize("text", ["哦？", "`[[SILENT]]`", "示例：[[REACT:😂]]", "[[SILENT]] 然后呢", "```\n[[SILENT]]\n```"])
def test_prose_and_quoted_controls_are_preserved(text: str) -> None:
    assert parse_chat_expression(text) is None


def test_invalid_reaction_is_an_error_not_silence() -> None:
    with pytest.raises(ValueError, match="exactly one emoji"):
        parse_chat_expression("[[REACT:hello]]")


@pytest.mark.parametrize("text", ["[[SILENT]]", " [[REACT:👩🏽‍💻]] ", "[[REACT:hello]]"])
def test_controls_do_not_leak_at_any_stream_boundary(text: str) -> None:
    for split in range(len(text) + 1):
        buffer = ChatExpressionStreamBuffer()
        assert buffer.feed(text[:split]) + buffer.feed(text[split:]) + buffer.flush() == ""


@pytest.mark.parametrize("text", ["[", "  hello", "[[SILENT]] is an example", "`[[REACT:😂]]`", "普通文本"])
def test_stream_preserves_normal_text(text: str) -> None:
    buffer = ChatExpressionStreamBuffer()
    assert "".join(buffer.feed(char) for char in text) + buffer.flush() == text
