"""Privacy controls for memory retrieval."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class SensitivityLevel(Enum):
    """Data sensitivity classification."""
    PUBLIC = "public"           # No confirmation needed
    INTERNAL = "internal"       # General usage, no confirmation
    SENSITIVE = "sensitive"     # Requires user confirmation
    RESTRICTED = "restricted"   # Never retrievable via tool


SENSITIVITY_RULES: Dict[str, SensitivityLevel] = {
    "browser_history": SensitivityLevel.INTERNAL,
    "chat": SensitivityLevel.INTERNAL,
    "note": SensitivityLevel.INTERNAL,
    "document": SensitivityLevel.INTERNAL,
    "password": SensitivityLevel.RESTRICTED,
    "credential": SensitivityLevel.RESTRICTED,
    "private_diary": SensitivityLevel.SENSITIVE,
    "health_data": SensitivityLevel.SENSITIVE,
    "financial": SensitivityLevel.SENSITIVE,
}


@dataclass
class PrivacyCheckResult:
    """Result of privacy sensitivity check."""
    allowed: bool
    requires_confirmation: bool
    confirm_prompt: Optional[str]
    blocked_types: List[str]


class PrivacyGuard:
    """Guard for memory retrieval privacy controls."""

    def __init__(self, user_preferences: Optional[Dict[str, Any]] = None):
        self.user_preferences = user_preferences or {}
        self._sensitivity_rules = SENSITIVITY_RULES

    def check(
        self,
        data_types: List[str],
        query_context: Dict[str, Any]
    ) -> PrivacyCheckResult:
        """
        Check if memory retrieval is allowed for given data types.

        Args:
            data_types: List of memory types to retrieve
            query_context: Context about the query (who, when, purpose)

        Returns:
            PrivacyCheckResult with permission status and confirmation requirements.
        """
        blocked: List[str] = []
        needs_confirmation: List[str] = []

        for dtype in data_types:
            level = self._sensitivity_rules.get(dtype, SensitivityLevel.INTERNAL)

            if level == SensitivityLevel.RESTRICTED:
                blocked.append(dtype)
            elif level == SensitivityLevel.SENSITIVE:
                needs_confirmation.append(dtype)

        if blocked:
            return PrivacyCheckResult(
                allowed=False,
                requires_confirmation=False,
                confirm_prompt=None,
                blocked_types=blocked
            )

        if needs_confirmation:
            prompt = self._build_confirmation_prompt(needs_confirmation, query_context)
            return PrivacyCheckResult(
                allowed=True,
                requires_confirmation=True,
                confirm_prompt=prompt,
                blocked_types=[]
            )

        return PrivacyCheckResult(
            allowed=True,
            requires_confirmation=False,
            confirm_prompt=None,
            blocked_types=[]
        )

    def _build_confirmation_prompt(
        self,
        sensitive_types: List[str],
        context: Dict[str, Any]
    ) -> str:
        """Build user-friendly confirmation prompt."""
        type_list = ", ".join(sensitive_types)
        return (
            f"This query will access sensitive data types: {type_list}. "
            f"Do you want to proceed with the retrieval?"
        )
