"""Language policy and validation for L3 temporal summaries."""

from __future__ import annotations

import re

from ... import i18n as core_i18n
from .models import TemporalSummaryLLMOutput
from .temporal_prompts import TEMPORAL_SUMMARY_SYSTEM_PROMPT

_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
_LATIN_WORD_PATTERN = re.compile(r"[A-Za-z]{3,}")


def target_language_code() -> str:
    return core_i18n.effective_app_language_code()


def target_language_label() -> str:
    return core_i18n.llm_language_label()


def target_language_instruction() -> str:
    target = target_language_label()
    return (
        f"- The target language is {target}.\n"
        f"- Write every user-facing generated field in {target}: content, essence_prose, key_topics, "
        "sentiment_summary natural-language strings, and change_and_pattern strings.\n"
        "- This language rule is mandatory even when evidence, rule_hints, or plugin_summary_features are written in another language.\n"
        "- Preserve event ids, entity ids, URLs, file paths, source names, product names, song titles, and quoted user text as evidence presents them."
    )


def render_temporal_summary_system_prompt() -> str:
    return (
        TEMPORAL_SUMMARY_SYSTEM_PROMPT
        + "\nLanguage Rules:\n"
        + f"- Target language: {target_language_label()}.\n"
        + "- All user-facing JSON string values MUST use the target language.\n"
        + "- Evidence text may be in another language; summarize it in the target language unless preserving a name, URL, ID, path, title, or direct quote.\n"
    )


class TemporalLanguageGuard:
    """Validate that user-facing temporal summary text matches the target language."""

    def validate_output(self, output: TemporalSummaryLLMOutput) -> None:
        if target_language_code() != "zh":
            return
        for text in self.user_facing_strings(output):
            if self.looks_like_non_zh_user_text(text):
                raise ValueError("Temporal LLM output does not match target language zh-CN")

    def validate_prose(self, content: str) -> None:
        if target_language_code() == "zh" and self.looks_like_non_zh_user_text(content):
            raise ValueError("Temporal LLM prose does not match target language zh-CN")

    def user_facing_strings(self, output: TemporalSummaryLLMOutput) -> list[str]:
        strings = [output.content]
        if output.essence_prose:
            strings.append(output.essence_prose)
        strings.extend(output.key_topics)
        if isinstance(output.sentiment_summary, dict):
            strings.extend(
                str(value) for value in output.sentiment_summary.values() if isinstance(value, str)
            )
        if isinstance(output.change_and_pattern, dict):
            for value in output.change_and_pattern.values():
                if isinstance(value, list):
                    strings.extend(str(item) for item in value if isinstance(item, str))
                elif isinstance(value, str):
                    strings.append(value)
        return [item.strip() for item in strings if item.strip()]

    def looks_like_non_zh_user_text(self, text: str) -> bool:
        if _CJK_PATTERN.search(text):
            return False
        return bool(_LATIN_WORD_PATTERN.search(text))


__all__ = [
    "TemporalLanguageGuard",
    "render_temporal_summary_system_prompt",
    "target_language_code",
    "target_language_instruction",
    "target_language_label",
]
