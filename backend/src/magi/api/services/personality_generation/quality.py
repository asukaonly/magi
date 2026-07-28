"""Deterministic quality checks for generated persona copy."""

from __future__ import annotations

from typing import Any, Optional, Sequence

from ...routers.personality_config_schemas import PersonaGenerationIntentModel


ASSISTANT_ROLE_TERMS = (
    "助手",
    "陪伴者",
    "客服",
    "assistant",
    "companion",
    "helper",
)
CONFIG_VOCAB_TERMS = (
    "自然交流模式",
    "沉浸模式",
    "还原模式",
    "表达模式",
    "交流模式",
    "adaptation mode",
    "expression profile",
    "fidelity level",
    "expression level",
    "research preference",
    "fidelity_level",
    "expression_level",
    "research_preference",
    "fictional_inspired",
    "fictional_natural",
    "fictional_immersive",
    "public_traits",
    "public_expression",
    "public_image",
    "private_traits",
)


def _display_field_texts(
    combined: dict[str, Any],
) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for key in ("name", "description"):
        value = combined.get(key)
        if isinstance(value, str) and value.strip():
            fields.append((key, value))
    identity_core = combined.get("identity_core")
    if isinstance(identity_core, dict):
        statement = identity_core.get("identity_statement")
        if isinstance(statement, str) and statement.strip():
            fields.append(("identity_core.identity_statement", statement))
    bootstrap = combined.get("bootstrap")
    if isinstance(bootstrap, dict):
        opening = bootstrap.get("opening_line")
        if isinstance(opening, str) and opening.strip():
            fields.append(("bootstrap.opening_line", opening))
    return fields


def _user_requested_assistant_role(
    description: str,
    intent: Optional[PersonaGenerationIntentModel],
) -> bool:
    texts = [description]
    if intent is not None:
        texts.extend(intent.explicit_constraints or [])
    sample = " ".join(texts).casefold()
    return any(term in sample for term in ASSISTANT_ROLE_TERMS)


def _dedupe_substring_hits(hits: list[str]) -> list[str]:
    return [hit for hit in hits if not any(hit != other and hit in other for other in hits)]


def _generation_quality_findings(
    combined: dict[str, Any],
    description: str,
    intent: Optional[PersonaGenerationIntentModel],
) -> list[str]:
    """Detect role framing and configuration vocabulary in display fields."""
    findings: list[str] = []
    assistant_requested = _user_requested_assistant_role(description, intent)
    for field, text in _display_field_texts(combined):
        lowered = text.casefold()
        if not assistant_requested:
            role_hits = _dedupe_substring_hits(
                [term for term in ASSISTANT_ROLE_TERMS if term in lowered]
            )
            if role_hits:
                findings.append(
                    f"{field} frames the persona as a service role "
                    f"({', '.join(role_hits)}) that the user never requested. "
                    "Rewrite it as the character itself, not an assistant, "
                    "helper, or companion."
                )
        vocab_hits = _dedupe_substring_hits(
            [term for term in CONFIG_VOCAB_TERMS if term in lowered]
        )
        if vocab_hits:
            findings.append(
                f"{field} leaks configuration vocabulary "
                f"({', '.join(vocab_hits)}). Remove mode/config language from "
                "user-visible prose and keep it in-world character copy."
            )
    return findings


def _quality_findings_block(
    findings: Optional[Sequence[str]],
) -> str:
    if not findings:
        return ""
    lines = "\n".join(f"- {item}" for item in findings)
    return f"""\n\n# Detected Quality Findings
Automated checks flagged these issues in the combined draft. Fix each one in your correction patch:
{lines}"""
