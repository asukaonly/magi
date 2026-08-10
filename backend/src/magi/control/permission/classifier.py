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
        workspace: str | None = None,
        tool_is_dangerous: bool = False,
        tool_risk_level: RiskLevel | str | None = None,
        tool_risk_authoritative: bool = False,
    ) -> ClassificationResult:
        declared_risk = _parse_risk_level(tool_risk_level)
        rule = RULES.get(tool_name)
        if rule is not None:
            return rule(dict(arguments), workspace=workspace)
        if declared_risk is not None and tool_risk_authoritative:
            return _declared_risk_result(declared_risk, authoritative=True)
        lowered = tool_name.lower()
        if any(marker in lowered for marker in EXTERNAL_SEND_SUBSTRINGS):
            return classify_external_send(dict(arguments))
        if declared_risk is not None:
            return _declared_risk_result(declared_risk, authoritative=False)
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


def _parse_risk_level(value: RiskLevel | str | None) -> RiskLevel | None:
    if value is None:
        return None
    if isinstance(value, RiskLevel):
        return value
    try:
        return RiskLevel(value)
    except (TypeError, ValueError):
        return None


def _declared_risk_result(
    risk: RiskLevel,
    *,
    authoritative: bool,
) -> ClassificationResult:
    source = "host override" if authoritative else "tool metadata"
    return ClassificationResult(
        level=risk,
        signals=[
            RiskSignal(
                key=(
                    "tool_risk_authoritative"
                    if authoritative
                    else "tool_risk_declared"
                ),
                description=f"{source} declares {risk.value} risk",
            )
        ],
        preview=None,
    )
