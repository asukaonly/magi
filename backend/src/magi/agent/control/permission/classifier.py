"""Risk classifier for ``(tool, args)``."""

from __future__ import annotations

from typing import Any

from .classifier_models import ClassificationResult, RiskSignal
from .classifier_rules import EXTERNAL_SEND_SUBSTRINGS, RULES, classify_external_send
from .contracts import RiskLevel

__all__ = ["RiskClassifier", "RiskSignal", "ClassificationResult"]


class RiskClassifier:
    """Assign a :class:`RiskLevel` to a tool invocation."""

    def __init__(
        self,
        *,
        default_dangerous_level: RiskLevel = RiskLevel.HIGH,
        default_level: RiskLevel = RiskLevel.LOW,
    ) -> None:
        self._default_dangerous_level = default_dangerous_level
        self._default_level = default_level

    def classify(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        tool_is_dangerous: bool = False,
    ) -> ClassificationResult:
        rule = RULES.get(tool_name)
        if rule is not None:
            return rule(dict(arguments))
        lowered = tool_name.lower()
        if any(marker in lowered for marker in EXTERNAL_SEND_SUBSTRINGS):
            return classify_external_send(dict(arguments))
        if tool_is_dangerous:
            return ClassificationResult(
                level=self._default_dangerous_level,
                signals=[
                    RiskSignal(
                        key="tool_flagged_dangerous",
                        description="tool schema flagged as dangerous",
                    )
                ],
                preview=None,
            )
        return ClassificationResult(
            level=self._default_level, signals=[], preview=None
        )
