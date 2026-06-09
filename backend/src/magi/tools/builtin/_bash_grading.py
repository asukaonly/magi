"""Backward-compatibility shim for the bash/shell command risk classifier.

The classifier moved to :mod:`magi_plugin_sdk.command_risk` as part of the
control-plane extraction (Phase 3). It is pure command-risk classification
logic, so it was promoted to the SDK to keep both the L8 tools
(``bash_tool``, ``powershell_tool``) and the L4 permission classifier
depending downward on the SDK rather than on each other.

All names below are re-exported from :mod:`magi_plugin_sdk.command_risk` so
that existing ``magi.tools.builtin._bash_grading`` imports keep working
unchanged. Identity is preserved:
``magi.tools.builtin._bash_grading.classify_for_permission is
magi_plugin_sdk.command_risk.classify_for_permission``.
"""
from __future__ import annotations

from magi_plugin_sdk.command_risk import *  # noqa: F401,F403
from magi_plugin_sdk.command_risk import (
    CommandGrade,
    RiskLevel,
    classify_command,
    classify_for_permission,
)

__all__ = ["CommandGrade", "RiskLevel", "classify_command", "classify_for_permission"]
