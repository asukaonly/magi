"""Deterministic Markdown cleaning and Unicode segment boundaries."""

import re

from markdown_it import MarkdownIt

_PARSER = MarkdownIt("commonmark").enable("table")


def clean_segments(text: str) -> list[str]:
    """Keep prose, skip code/tables/URLs, and never silently truncate input."""
    if len(text) > 4096:
        raise ValueError("text_too_long")
    text = re.sub(r"<!--.*?-->|\[\[/?bubble[^\]]*\]\]|【[^】]*†[^】]*】", "", text, flags=re.S)
    parts: list[str] = []
    in_table = False
    for token in _PARSER.parse(text):
        if token.type == "table_open":
            in_table = True
        elif token.type == "table_close":
            in_table = False
        elif token.type == "inline" and not in_table:
            line: list[str] = []
            for child in token.children or []:
                if child.type == "text":
                    line.append(child.content)
                elif child.type in {"softbreak", "hardbreak"}:
                    line.append(" ")
                elif child.type == "code_inline" and re.fullmatch(r"[\w .-]{1,32}", child.content):
                    line.append(child.content)
            parts.append("".join(line))
    prose = re.sub(r"(?:https?://|www\.)\S+", "", "\n".join(parts))
    prose = re.sub(r"[^\S\n]+", " ", prose).strip()
    if not any(char.isalnum() for char in prose):
        raise ValueError("no_readable_text")
    segments: list[str] = []
    for sentence in re.split(r"(?<=[。！？!?；;])|(?<=\.)\s+|(?<=\.)(?=[\u4e00-\u9fff])|\n+", prose):
        sentence = sentence.strip()
        while sentence:
            end = min(len(sentence), 200)
            if end < len(sentence):
                boundary = max(sentence.rfind(" ", 0, end), sentence.rfind("，", 0, end))
                if boundary >= 100:
                    end = boundary + 1
            chunk, sentence = sentence[:end].strip(), sentence[end:].strip()
            if chunk:
                segments.append(chunk)
    return segments
