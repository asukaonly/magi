"""Parse whole-reply chat controls without interpreting ordinary prose."""

from __future__ import annotations

from dataclasses import dataclass
import re

import regex


@dataclass(frozen=True, slots=True)
class ChatExpression:
    mode: str
    emoji: str | None = None


def is_single_emoji(value: str) -> bool:
    """Accept one emoji grapheme, including flags, modifiers and ZWJ sequences."""
    if not value or len(value) > 32 or regex.fullmatch(r"\X", value) is None:
        return False
    return regex.fullmatch(
        r"(?:\p{Regional_Indicator}{2}|[#*0-9]\uFE0F?\u20E3|"
        r"\p{Extended_Pictographic}(?:\uFE0F|\p{Emoji_Modifier})*"
        r"(?:\u200D\p{Extended_Pictographic}(?:\uFE0F|\p{Emoji_Modifier})*)*"
        r"(?:[\U000E0020-\U000E007E]+\U000E007F)?)",
        value,
    ) is not None


def parse_chat_expression(text: str) -> ChatExpression | None:
    """Consume only a standalone control; quoted or mixed text remains text."""
    value = text.strip()
    if value == "[[SILENT]]":
        return ChatExpression("none")
    match = re.fullmatch(r"\[\[REACT:([^\[\]\r\n]*)\]\]", value)
    if match is not None:
        emoji = match.group(1).strip()
        if not is_single_emoji(emoji):
            raise ValueError("A chat reaction must contain exactly one emoji.")
        return ChatExpression("reaction_only", emoji)
    return None


class ChatExpressionStreamBuffer:
    """Hold a possible control until its text block ends; stream prose normally."""

    def __init__(self) -> None:
        self.pending = ""
        self.passthrough = False

    def feed(self, text: str) -> str:
        if self.passthrough:
            return text
        self.pending += text
        stripped = self.pending.lstrip()
        prefixes = ("[[SILENT]]", "[[REACT:")
        if not stripped or any(prefix.startswith(stripped) for prefix in prefixes):
            return ""
        if stripped.startswith("[[REACT:") and "]]" not in stripped:
            if len(stripped) <= 64:
                return ""
        try:
            control = parse_chat_expression(stripped)
        except ValueError:
            return ""
        if control is not None:
            return ""
        self.passthrough = True
        result, self.pending = self.pending, ""
        return result

    def flush(self) -> str:
        try:
            control = parse_chat_expression(self.pending)
        except ValueError:
            control = ChatExpression("none")
        result = "" if control is not None else self.pending
        self.pending = ""
        self.passthrough = False
        return result
